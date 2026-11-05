# -*- coding: utf-8 -*-
"""Portable 3D model export for molecules.

The current public target is PowerPoint's ``Insert > 3D Models`` workflow.
GLB is preferred because it is a single binary file and carries element
colours/materials without auxiliary MTL files.
"""

from __future__ import annotations

import json
import math
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence

import numpy as np


#: CPK-like colours used by the exported model.
ELEMENT_COLOURS = {
    "H": "#eeeeee", "B": "#ffb5b5", "C": "#454545", "N": "#3050f8",
    "O": "#ff2020", "F": "#90e050", "Si": "#c8a078", "P": "#ff8000",
    "S": "#d8c800", "Cl": "#1fd11f", "Br": "#a62929", "I": "#940094",
    "Li": "#cc80ff", "Na": "#ab5cf2", "K": "#8f40d4", "Mg": "#8aff00",
    "Ca": "#3dff00", "Al": "#bfa6a6", "Fe": "#e06633", "Co": "#f090a0",
    "Ni": "#50d050", "Cu": "#c88033", "Zn": "#7d80b0", "Cr": "#8a99c7",
}

#: Ball-and-stick radii in angstrom. Deliberately smaller than VDW radii so
#: bonds remain visible after import into PowerPoint.
ATOM_RADII = {
    "H": 0.25, "B": 0.40, "C": 0.38, "N": 0.38, "O": 0.36,
    "F": 0.34, "Si": 0.45, "P": 0.46, "S": 0.46, "Cl": 0.48,
    "Br": 0.52, "I": 0.56, "Li": 0.50, "Na": 0.50, "K": 0.54,
    "Mg": 0.50, "Ca": 0.52, "Al": 0.48, "Fe": 0.50, "Co": 0.50,
    "Ni": 0.50, "Cu": 0.50, "Zn": 0.50, "Cr": 0.50,
}
DEFAULT_ATOM_RADIUS = 0.42
BOND_RADIUS = 0.105

_COMPONENT_BYTES = {
    5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4,
}
_TYPE_COMPONENTS = {
    "SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4,
    "MAT2": 4, "MAT3": 9, "MAT4": 16,
}


@dataclass
class SurfaceLayer:
    """A self-contained triangle surface for a combined molecular-scene GLB.

    ``vertices`` use the same Angstrom coordinate system as the molecule.
    ``colors`` may be RGB/RGBA values in display sRGB space; they are converted
    to linear vertex colours when the GLB is built. The material alpha is kept
    in ``opacity`` so PowerPoint receives a standard alpha-blended PBR material.
    """

    name: str
    vertices: np.ndarray
    indices: np.ndarray
    normals: Optional[np.ndarray] = None
    colors: Optional[np.ndarray] = None
    opacity: float = 0.72
    roughness: float = 0.52
    kind: str = "isosurface"
    visible: bool = True
    double_sided: bool = True
    color: tuple[float, float, float] = (0.65, 0.75, 0.90)


def _symbol(value) -> str:
    text = str(value or "").strip()
    return text[:1].upper() + text[1:].lower()


def _rgb(hex_colour: str) -> list[float]:
    value = str(hex_colour).lstrip("#")
    if len(value) != 6:
        value = "9aa4b2"
    srgb = [int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    # glTF baseColorFactor is linear. Passing canvas sRGB values verbatim
    # washes dark colours out badly in PowerPoint's PBR renderer.
    linear = [c / 12.92 if c <= 0.04045
              else ((c + 0.055) / 1.055) ** 2.4 for c in srgb]
    return linear + [1.0]


def _colour_rgba(value, fallback="#9aa4b2") -> list[float]:
    try:
        text = value.lstrip("#") if isinstance(value, str) else ""
        if len(text) == 6:
            return _rgb("#" + text)
    except Exception:                                      # noqa: BLE001
        pass
    try:
        rgb = [float(v) for v in list(value)[:3]]
        if len(rgb) == 3 and all(math.isfinite(v) for v in rgb):
            linear = [c / 12.92 if c <= 0.04045
                      else ((c + 0.055) / 1.055) ** 2.4
                      for c in (max(0.0, min(1.0, v)) for v in rgb)]
            return linear + [1.0]
    except Exception:                                      # noqa: BLE001
        pass
    return _rgb(fallback)


def _colour_array(rgba, fallback=(0.65, 0.75, 0.90)) -> np.ndarray:
    """Convert sRGB surface colours to linear RGB, one row per vertex."""
    if rgba is None:
        src = np.asarray(fallback, dtype=np.float64).reshape(1, 3)
    else:
        src = np.asarray(rgba, dtype=np.float64)
        if src.ndim == 1 and src.size >= 3:
            src = src[:3].reshape(1, 3)
        elif src.ndim != 2 or src.shape[1] < 3:
            raise ValueError("surface colors must be RGB or RGBA values")
        src = src[:, :3]
    src = np.clip(src, 0.0, 1.0)
    return np.where(
        src <= 0.04045,
        src / 12.92,
        ((src + 0.055) / 1.055) ** 2.4,
    )


def _compute_vertex_normals(vertices: np.ndarray,
                            indices: np.ndarray) -> np.ndarray:
    """Area-weighted smooth normals, used only when a surface omits normals."""
    triangles = vertices[indices.reshape(-1, 3)]
    face_normals = np.cross(
        triangles[:, 1] - triangles[:, 0],
        triangles[:, 2] - triangles[:, 0],
    )
    normals = np.zeros_like(vertices, dtype=np.float64)
    np.add.at(
        normals,
        indices.reshape(-1),
        np.repeat(face_normals, 3, axis=0),
    )
    lengths = np.linalg.norm(normals, axis=1)
    valid = lengths > 1e-12
    normals[valid] /= lengths[valid, None]
    normals[~valid] = np.array((0.0, 0.0, 1.0))
    return normals.astype(np.float32)


def _prepare_surface(layer: SurfaceLayer):
    """Validate and convert a public surface layer into indexed mesh arrays."""
    if not isinstance(layer, SurfaceLayer):
        raise TypeError("surfaces must contain SurfaceLayer objects")
    if not layer.visible:
        return None
    try:
        opacity = max(0.0, min(1.0, float(layer.opacity)))
        roughness = max(0.03, min(1.0, float(layer.roughness)))
    except (TypeError, ValueError) as exc:
        raise ValueError("surface opacity/roughness must be numeric") from exc
    if opacity <= 0.001:
        return None

    vertices = np.asarray(layer.vertices, dtype=np.float32)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not vertices.size:
        raise ValueError("surface vertices must be a non-empty (N, 3) array")
    if not np.isfinite(vertices).all():
        raise ValueError("surface vertices contain non-finite coordinates")

    indices = np.asarray(layer.indices)
    if indices.ndim != 1 or indices.size == 0 or indices.size % 3:
        raise ValueError("surface indices must be a non-empty triangle list")
    if not np.issubdtype(indices.dtype, np.integer):
        if not np.equal(indices, np.floor(indices)).all():
            raise ValueError("surface indices must be integers")
    indices = indices.astype(np.uint32, copy=False)
    if int(indices.min()) < 0 or int(indices.max()) >= len(vertices):
        raise ValueError("surface index is outside the vertex array")

    normals = layer.normals
    if normals is None:
        normals = _compute_vertex_normals(vertices, indices)
    else:
        normals = np.asarray(normals, dtype=np.float32)
        if normals.shape != vertices.shape or not np.isfinite(normals).all():
            raise ValueError("surface normals must match the (N, 3) vertices")
        lengths = np.linalg.norm(normals, axis=1)
        valid = lengths > 1e-12
        normals[valid] /= lengths[valid, None]
        normals[~valid] = np.array((0.0, 0.0, 1.0), dtype=np.float32)

    colours = _colour_array(layer.colors, layer.color)
    if len(colours) == 1:
        colours = np.repeat(colours, len(vertices), axis=0)
    elif len(colours) != len(vertices):
        raise ValueError("surface colors must have one row per vertex")
    return (str(layer.name or "Surface"), vertices, normals, indices,
            colours.astype(np.float32), opacity, roughness,
            bool(layer.double_sided), str(layer.kind or "isosurface"))


def _baked_vertex_colours(normals) -> np.ndarray:
    """Bake soft studio lighting into unlit-material vertex colours."""
    arr = np.asarray(normals, dtype=np.float32).reshape(-1, 3)
    light = np.array((-0.38, 0.62, 0.72), dtype=np.float32)
    light /= np.linalg.norm(light)
    ndl = np.clip(arr @ light, 0.0, 1.0)
    shade = 0.48 + 0.52 * ndl
    out = np.ones((arr.shape[0], 4), dtype=np.float32)
    out[:, :3] = shade[:, None]
    return out


def _linear_to_srgb_byte(value: float) -> int:
    value = max(0.0, min(1.0, float(value)))
    srgb = (12.92 * value if value <= 0.0031308
            else 1.055 * value ** (1.0 / 2.4) - 0.055)
    return int(round(max(0.0, min(1.0, srgb)) * 255.0))


def _solid_png(rgba) -> bytes:
    """Smallest possible opaque 1x1 RGBA PNG for a solid material colour."""
    red, green, blue = (_linear_to_srgb_byte(c) for c in rgba[:3])
    raw_scanline = bytes((0, red, green, blue, 255))

    def chunk(kind, payload):
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw_scanline))
            + chunk(b"IEND", b""))


def _sphere_texture_png(rgba, size: int = 64) -> bytes:
    """Bake a HoukMol-like sphere: diffuse falloff, highlight and dark rim."""
    base = np.asarray(rgba[:3], dtype=np.float64)
    light = np.array((-0.42, 0.55, 0.72), dtype=np.float64)
    light /= np.linalg.norm(light)
    scanlines = bytearray()
    for iy in range(size):
        scanlines.append(0)                          # PNG filter=None
        y = 1.0 - 2.0 * (iy + 0.5) / size
        for ix in range(size):
            x = -1.0 + 2.0 * (ix + 0.5) / size
            radial2 = x * x + y * y
            if radial2 > 1.0:
                scanlines.extend((0, 0, 0, 0))
                continue
            z = math.sqrt(max(0.0, 1.0 - radial2))
            normal = np.array((x, y, z), dtype=np.float64)
            diffuse = 0.34 + 0.66 * max(0.0, float(np.dot(normal, light)))
            # Soft highlight centred in the upper-left quadrant.
            dx, dy = x + 0.34, y - 0.46
            highlight = 0.72 * math.exp(-(dx * dx + dy * dy) / 0.055)
            radius = math.sqrt(radial2)
            rim = max(0.0, min(1.0, (radius - 0.82) / 0.18))
            shade = diffuse * (1.0 - 0.46 * rim * rim)
            rgb = np.clip(base * shade + (1.0 - base) * highlight, 0.0, 1.0)
            scanlines.extend((
                _linear_to_srgb_byte(float(rgb[0])),
                _linear_to_srgb_byte(float(rgb[1])),
                _linear_to_srgb_byte(float(rgb[2])),
                255,
            ))

    def chunk(kind, payload):
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(
                ">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(scanlines), 9))
            + chunk(b"IEND", b""))


@dataclass
class _Part:
    positions: list[float] = field(default_factory=list)
    normals: list[float] = field(default_factory=list)
    indices: list[int] = field(default_factory=list)

    def add_sphere(self, center: np.ndarray, radius: float,
                   latitude: int = 10, longitude: int = 16,
                   flip: bool = False) -> None:
        base = len(self.positions) // 3
        for iy in range(latitude + 1):
            theta = math.pi * iy / latitude
            st, ct = math.sin(theta), math.cos(theta)
            for ix in range(longitude + 1):
                phi = 2.0 * math.pi * ix / longitude
                normal = np.array((st * math.cos(phi), ct, st * math.sin(phi)),
                                  dtype=float)
                point = center + radius * normal
                self.positions.extend(point.tolist())
                self.normals.extend((-normal if flip else normal).tolist())
        stride = longitude + 1
        for iy in range(latitude):
            for ix in range(longitude):
                a = base + iy * stride + ix
                b = a + stride
                if flip:
                    self.indices.extend((a, b, a + 1, a + 1, b, b + 1))
                else:
                    self.indices.extend((a, a + 1, b, a + 1, b + 1, b))

    def add_cylinder(self, start: np.ndarray, end: np.ndarray, radius: float,
                     sides: int = 12) -> None:
        axis = end - start
        length = float(np.linalg.norm(axis))
        if length <= 1e-9:
            return
        axis /= length
        helper = np.array((0.0, 1.0, 0.0))
        if abs(float(np.dot(axis, helper))) > 0.92:
            helper = np.array((1.0, 0.0, 0.0))
        u = np.cross(axis, helper)
        u /= np.linalg.norm(u)
        v = np.cross(axis, u)
        base = len(self.positions) // 3
        for point in (start, end):
            for i in range(sides + 1):
                ang = 2.0 * math.pi * i / sides
                normal = math.cos(ang) * u + math.sin(ang) * v
                pos = point + radius * normal
                self.positions.extend(pos.tolist())
                self.normals.extend(normal.tolist())
        stride = sides + 1
        for i in range(sides):
            a = base + i
            b = a + stride
            self.indices.extend((a, a + 1, b, a + 1, b + 1, b))


def _normalise_bonds(bonds, atom_count: int) -> list[tuple[int, int]]:
    if bonds is None:
        return []
    raw = []
    for pair in bonds:
        try:
            a, b = int(pair[0]), int(pair[1])
        except (TypeError, ValueError, IndexError):
            continue
        raw.append((a, b))
    if not raw:
        return []
    # MolStudio's canvas uses 1-based atom ids; XYZ bond estimators may use
    # 0-based ids. Normalise whichever convention the caller supplied.
    zero_based = any(min(a, b) == 0 for a, b in raw)
    if not zero_based:
        raw = [(a - 1, b - 1) for a, b in raw]
    out = set()
    for a, b in raw:
        if a == b or not (0 <= a < atom_count and 0 <= b < atom_count):
            continue
        out.add((min(a, b), max(a, b)))
    return sorted(out)


def _infer_bonds(symbols: Sequence[str], coords: np.ndarray) -> list[tuple[int, int]]:
    try:
        from molstudio.core.steric.render import bonds
        return _normalise_bonds(bonds(symbols, coords), len(symbols))
    except Exception:                                      # noqa: BLE001
        return []


def _normalise_bond_orders(values, atom_count: int):
    out = []
    for item in values or []:
        try:
            a, b, order = int(item[0]), int(item[1]), int(item[2])
        except (TypeError, ValueError, IndexError):
            continue
        a, b = a - 1, b - 1
        if a == b or not (0 <= a < atom_count and 0 <= b < atom_count):
            continue
        out.append((min(a, b), max(a, b), max(1, min(order, 3))))
    return out


def _bond_perpendicular(axis: np.ndarray) -> np.ndarray:
    helper = np.array((0.0, 1.0, 0.0))
    if abs(float(np.dot(axis, helper))) > 0.92:
        helper = np.array((1.0, 0.0, 0.0))
    perp = np.cross(axis, helper)
    norm = float(np.linalg.norm(perp))
    return perp / norm if norm > 1e-9 else np.array((1.0, 0.0, 0.0))


def _hemisphere_directions(normal: np.ndarray, count: int) -> np.ndarray:
    """Deterministic cosine-weighted hemisphere samples around ``normal``."""
    helper = np.array((0.0, 1.0, 0.0), dtype=float)
    if abs(float(np.dot(normal, helper))) > 0.92:
        helper = np.array((1.0, 0.0, 0.0), dtype=float)
    tangent = np.cross(normal, helper)
    tangent /= max(float(np.linalg.norm(tangent)), 1e-12)
    bitangent = np.cross(normal, tangent)
    out = np.empty((count, 3), dtype=float)
    golden = 0.6180339887498949
    for i in range(count):
        u = (i + 0.5) / count
        phi = 2.0 * math.pi * ((i * golden) % 1.0)
        radial = math.sqrt(u)
        out[i] = (radial * math.cos(phi) * tangent
                  + radial * math.sin(phi) * bitangent
                  + math.sqrt(max(0.0, 1.0 - u)) * normal)
    return out


class _ContactAOBaker:
    """Small KDTree-backed hemisphere-ray AO baker for exported vertices."""

    def __init__(self, centers, radii, *, rays=8, max_distance=3.8):
        self.centers = np.asarray(centers, dtype=float).reshape(-1, 3)
        self.radii = np.asarray(radii, dtype=float).reshape(-1)
        self.rays = max(1, int(rays))
        self.max_distance = max(0.1, float(max_distance))
        if self.centers.size and self.radii.size != len(self.centers):
            self.radii = np.resize(self.radii, len(self.centers))
        self.tree = None
        if self.centers.size:
            try:
                from scipy.spatial import cKDTree
                self.tree = cKDTree(self.centers)
            except Exception:                              # noqa: BLE001
                self.tree = None

    def factors(self, points, normals) -> np.ndarray:
        pts = np.asarray(points, dtype=float).reshape(-1, 3)
        nrm = np.asarray(normals, dtype=float).reshape(-1, 3)
        if not pts.size or not self.centers.size:
            return np.ones(len(pts), dtype=float)
        if self.tree is not None:
            search_radius = self.max_distance + float(self.radii.max(initial=0.0))
        ao = np.ones(len(pts), dtype=float)
        for index, (point, normal) in enumerate(zip(pts, nrm)):
            norm = float(np.linalg.norm(normal))
            if norm <= 1e-12:
                continue
            normal = normal / norm
            if self.tree is not None:
                nearby = self.tree.query_ball_point(point, search_radius)
            else:
                nearby = range(len(self.centers))
            if not nearby:
                continue
            idx = np.asarray(list(nearby), dtype=int)
            centers = self.centers[idx]
            radii = self.radii[idx]
            origin = point + normal * 1e-3
            directions = _hemisphere_directions(normal, self.rays)
            oc = origin[None, :] - centers
            b = directions @ oc.T
            c = np.einsum("ij,ij->i", oc, oc) - radii * radii
            disc = b * b - c[None, :]
            valid = disc >= 0.0
            if not valid.any():
                continue
            roots = -b - np.sqrt(np.maximum(disc, 0.0))
            # If the ray origin lies inside another atom sphere, the contact
            # is fully occluded there even though the first root is negative.
            hit = (valid & (roots > 1e-3) & (roots < self.max_distance))
            hit |= (c <= 0.0)[None, :]
            hits = int(np.any(hit, axis=1).sum())
            visibility = 1.0 - hits / float(self.rays)
            ao[index] = 0.65 + 0.35 * visibility
        return ao


def _build_gltf(symbols: Sequence[str], coords: np.ndarray, bonds,
                title: str, bond_orders=None, atom_colors=None,
                atom_radii=None, visible_atoms=None, bond_color=None,
                bond_radius=None, bond_dual_colors=False,
                view_rotation=None, roughness=0.48, bond_roughness=0.65,
                unlit=False, texture_colours=False, native_pbr=False,
                high_detail=False, bake_ao=True, ao_rays=8,
                atom_outline=False, outline_ratio=0.045,
                outline_color=(0.0, 0.0, 0.0), surfaces=None):
    n = len(symbols)
    visible = np.ones(n, dtype=bool)
    if visible_atoms is not None:
        try:
            visible = np.asarray(visible_atoms, dtype=bool).reshape(-1)
            if visible.size != n:
                visible = np.ones(n, dtype=bool)
        except (TypeError, ValueError):
            visible = np.ones(n, dtype=bool)
    if n and not visible.any():
        visible[:] = True
    center = coords[visible].mean(axis=0) if visible.any() else np.zeros(3)
    oriented = coords - center
    if view_rotation is not None:
        try:
            rotation = np.asarray(view_rotation, dtype=float)
            if rotation.shape == (3, 3) and np.isfinite(rotation).all():
                pass
            else:
                rotation = None
        except (TypeError, ValueError):
            rotation = None
    else:
        rotation = None

    def _orient_points(points):
        points = np.asarray(points, dtype=float) - center
        if rotation is not None:
            # Camera view coordinates are already x-right / y-up / z-towards-eye.
            return points @ rotation.T
        # Convert the chemistry convention (z up) to glTF's y-up convention.
        return np.column_stack(
            (points[:, 0], points[:, 2], -points[:, 1]))

    def _orient_vectors(vectors):
        vectors = np.asarray(vectors, dtype=float)
        if rotation is not None:
            return vectors @ rotation.T
        return np.column_stack(
            (vectors[:, 0], vectors[:, 2], -vectors[:, 1]))

    converted = _orient_points(coords)

    try:
        roughness = max(0.03, min(1.0, float(roughness)))
    except (TypeError, ValueError):
        roughness = 0.48
    try:
        bond_roughness = max(0.03, min(1.0, float(bond_roughness)))
    except (TypeError, ValueError):
        bond_roughness = 0.65

    custom_atoms = atom_colors is not None
    colors = list(atom_colors or [])
    if len(colors) != n:
        custom_atoms = False
        colors = [ELEMENT_COLOURS.get(_symbol(sym), "#9aa4b2")
                  for sym in symbols]
    radii = list(atom_radii or [])
    if len(radii) != n:
        radii = [ATOM_RADII.get(_symbol(sym), DEFAULT_ATOM_RADIUS)
                 for sym in symbols]

    material_specs = {}
    parts: dict[str, _Part] = {}
    outline_part = _Part()
    outline_rgba = _colour_rgba(outline_color, "#000000")[:3]
    ao_baker = None
    if native_pbr and bake_ao:
        ao_baker = _ContactAOBaker(
            converted[visible], np.asarray(radii, dtype=float)[visible],
            rays=ao_rays)

    for i, (sym, point) in enumerate(zip(symbols, converted)):
        if not visible[i]:
            continue
        element = _symbol(sym)
        if custom_atoms:
            key = f"atom:{_colour_rgba(colors[i])[:3]}"
            material_specs.setdefault(
                key, (_colour_rgba(colors[i]), roughness, f"Atom {element}"))
        else:
            key = element
            material_specs.setdefault(
                key, (_rgb(ELEMENT_COLOURS.get(element, "#9aa4b2")),
                      roughness, element))
        try:
            radius = max(0.03, float(radii[i]))
        except (TypeError, ValueError):
            radius = ATOM_RADII.get(element, DEFAULT_ATOM_RADIUS)
        if high_detail:
            # Keep very large molecules manageable while giving small,
            # classroom-sized structures a visibly smoother silhouette.
            latitude, longitude = (
                (48, 64) if n <= 16 else
                (32, 48) if n <= 64 else (24, 32)
            )
        else:
            latitude, longitude = 10, 16
        parts.setdefault(key, _Part()).add_sphere(
            point, radius, latitude=latitude, longitude=longitude)
        if atom_outline:
            outline_radius = radius + max(
                0.008, min(0.025, radius * max(0.01, float(outline_ratio))))
            outline_part.add_sphere(
                point, outline_radius,
                latitude=max(12, latitude // 2),
                longitude=max(16, longitude // 2),
                flip=True)

    ordered = _normalise_bond_orders(bond_orders, n)
    if not ordered:
        ordered = [(i, j, 1) for i, j in _normalise_bonds(bonds, n)]

    base_bond_radius = BOND_RADIUS
    try:
        if bond_radius is not None:
            base_bond_radius = max(0.02, float(bond_radius))
    except (TypeError, ValueError):
        pass

    def _bond_part_for_colour(value, default="#6f7782"):
        rgba = _colour_rgba(value, default)
        key = f"bond:{rgba[0]:.5f}:{rgba[1]:.5f}:{rgba[2]:.5f}"
        if key not in parts:
            parts[key] = _Part()
            material_specs[key] = (rgba, bond_roughness, "Bond")
        return parts[key]

    for i, j, order in ordered:
        if not (visible[i] and visible[j]):
            continue
        start, end = converted[i], converted[j]
        axis = end - start
        length = float(np.linalg.norm(axis))
        if length <= 1e-9:
            continue
        unit = axis / length
        perp = _bond_perpendicular(unit)
        if order <= 1:
            offsets = (0.0,)
            radius = base_bond_radius
        elif order == 2:
            offsets = (-1.0, 1.0)
            radius = base_bond_radius * 0.78
        else:
            offsets = (-1.0, 0.0, 1.0)
            radius = base_bond_radius * 0.68
        spacing = base_bond_radius * 1.55
        if bond_color is not None:
            segments = [(start, end, bond_color)]
        elif bond_dual_colors:
            mid = 0.5 * (start + end)
            segments = [(start, mid, colors[i]), (mid, end, colors[j])]
        else:
            segments = [(start, end, "#6f7782")]
        for offset in offsets:
            delta = perp * spacing * offset
            for p0, p1, colour in segments:
                _bond_part_for_colour(colour).add_cylinder(
                    p0 + delta, p1 + delta, radius,
                    sides=(32 if high_detail else 12))

    # Build one primitive per colour/material group.
    parts = {key: part for key, part in parts.items() if part.indices}
    if outline_part.indices:
        parts["__outline__"] = outline_part
        material_specs["__outline__"] = (
            list(outline_rgba) + [1.0], 0.55, "Atom outline")
    native_colours = {}
    if native_pbr:
        positions = []
        normals = []
        colours = []
        indices = []
        offset = 0
        for key, part in list(parts.items()):
            if key == "__outline__":
                continue
            vertex_count = len(part.positions) // 3
            rgba = material_specs[key][0]
            positions.extend(part.positions)
            normals.extend(part.normals)
            if ao_baker is not None:
                ao = ao_baker.factors(part.positions, part.normals)
                vertex_rgb = (
                    np.asarray(rgba[:3], dtype=float)[None, :]
                    * ao[:, None]
                )
                colours.extend(vertex_rgb.reshape(-1).tolist())
            else:
                colours.extend(rgba[:3] * vertex_count)
            indices.extend(int(i) + offset for i in part.indices)
            offset += vertex_count
        merged = _Part(positions=positions, normals=normals, indices=indices)
        native_parts = {"__native__": merged}
        if "__outline__" in parts:
            native_parts["__outline__"] = parts["__outline__"]
        parts = native_parts
        native_colours["__native__"] = colours
        material_specs = {
            "__native__": ([1.0, 1.0, 1.0, 1.0], roughness, "Molecule"),
            "__outline__": (
                list(outline_rgba) + [1.0], 0.55, "Atom outline"),
        }
        if "__outline__" in parts:
            native_colours["__outline__"] = (
                outline_rgba * (len(parts["__outline__"].positions) // 3))
        else:
            material_specs.pop("__outline__", None)

    # Surfaces deliberately remain separate primitives from the molecule:
    # their alpha/material must not make the opaque atoms and bonds translucent.
    surface_materials = {}
    surface_metadata = []
    for surface_index, layer in enumerate(surfaces or []):
        prepared = _prepare_surface(layer)
        if prepared is None:
            continue
        (name, vertices, normals, indices, colours,
         opacity, surface_roughness, double_sided, kind) = prepared
        vertices = _orient_points(vertices)
        normals = _orient_vectors(normals)
        normal_lengths = np.linalg.norm(normals, axis=1)
        valid_normals = normal_lengths > 1e-12
        normals[valid_normals] /= normal_lengths[valid_normals, None]
        normals[~valid_normals] = np.array(
            (0.0, 0.0, 1.0), dtype=float)

        key = f"__surface_{surface_index}__"
        while key in parts:
            key += "_"
        parts[key] = _Part(
            positions=vertices.reshape(-1).astype(float).tolist(),
            normals=normals.reshape(-1).astype(float).tolist(),
            indices=indices.astype(int).tolist(),
        )
        material_specs[key] = (
            [1.0, 1.0, 1.0, opacity], surface_roughness, name)
        native_colours[key] = colours.reshape(-1).astype(float).tolist()
        surface_materials[key] = {
            "double_sided": double_sided,
            "opacity": opacity,
        }
        surface_metadata.append({
            "name": name,
            "kind": kind,
            "vertices": int(len(vertices)),
            "triangles": int(len(indices) // 3),
            "opacity": round(float(opacity), 4),
        })

    material_index = {}
    materials = []
    material_images = {}
    for key in parts:
        rgba, rough, name = material_specs[key]
        material_index[key] = len(materials)
        base_factor = [1.0, 1.0, 1.0, 1.0] if texture_colours else rgba
        materials.append({
            "name": name,
            "pbrMetallicRoughness": {
                "baseColorFactor": base_factor,
                "metallicFactor": 0.0,
                "roughnessFactor": rough,
            },
        })
        if unlit:
            materials[-1]["extensions"] = {"KHR_materials_unlit": {}}
        if texture_colours and not native_pbr:
            material_images[key] = (
                _sphere_texture_png(rgba)
                if str(name).startswith("Atom ")
                else _solid_png(rgba))
        if native_pbr or key == "__outline__":
            materials[-1]["doubleSided"] = key != "__outline__"
        if key in surface_materials:
            surface_material = surface_materials[key]
            materials[-1]["doubleSided"] = surface_material["double_sided"]
            materials[-1]["alphaMode"] = (
                "BLEND" if surface_material["opacity"] < 0.999 else "OPAQUE")

    buffer = bytearray()
    buffer_views = []
    accessors = []
    primitives = []

    def append_array(values, component_type, type_name, target, with_bounds=False):
        nonlocal buffer
        while len(buffer) % 4:
            buffer.append(0)
        offset = len(buffer)
        dtype = {
            5126: np.float32, 5125: np.uint32, 5123: np.uint16,
        }[component_type]
        array = np.asarray(values, dtype=dtype)
        if type_name in ("VEC2", "VEC3", "VEC4"):
            array = np.asarray(array, dtype=dtype).reshape(
                -1, {"VEC2": 2, "VEC3": 3, "VEC4": 4}[type_name])
        payload = array.tobytes(order="C")
        buffer.extend(payload)
        view_index = len(buffer_views)
        buffer_views.append({
            "buffer": 0, "byteOffset": offset, "byteLength": len(payload),
            "target": target,
        })
        accessor = {
            "bufferView": view_index, "componentType": component_type,
            "count": int(array.size if type_name == "SCALAR" else array.shape[0]),
            "type": type_name,
        }
        if with_bounds:
            accessor["min"] = np.min(array, axis=0).astype(float).tolist()
            accessor["max"] = np.max(array, axis=0).astype(float).tolist()
        accessors.append(accessor)
        return len(accessors) - 1

    for key, part in parts.items():
        if not part.indices:
            continue
        pos_accessor = append_array(part.positions, 5126, "VEC3", 34962, True)
        norm_accessor = append_array(part.normals, 5126, "VEC3", 34962)
        index_type = 5123 if max(part.indices, default=0) < 65536 else 5125
        idx_accessor = append_array(part.indices, index_type, "SCALAR", 34963)
        attributes = {"POSITION": pos_accessor, "NORMAL": norm_accessor}
        vertex_count = len(part.positions) // 3
        if texture_colours and not native_pbr:
            material_name = material_specs[key][2]
            if str(material_name).startswith("Atom "):
                normals = np.asarray(part.normals, dtype=np.float32).reshape(
                    -1, 3)
                uvs = np.column_stack((
                    0.5 + 0.5 * normals[:, 0],
                    0.5 + 0.5 * normals[:, 1],
                ))
            else:
                uvs = np.tile(np.array((0.5, 0.5), dtype=np.float32),
                              (vertex_count, 1))
            attributes["TEXCOORD_0"] = append_array(
                uvs.reshape(-1), 5126, "VEC2", 34962)
        if key in native_colours:
            attributes["COLOR_0"] = append_array(
                native_colours[key], 5126, "VEC3", 34962)
        elif unlit:
            if (texture_colours
                    and str(material_specs[key][2]).startswith("Atom ")):
                # Sphere texture already contains the highlight and rim.
                colours = np.ones((vertex_count, 4), dtype=np.float32)
            else:
                colours = _baked_vertex_colours(part.normals)
            attributes["COLOR_0"] = append_array(
                colours.reshape(-1), 5126, "VEC4", 34962)
        primitives.append({
            "attributes": attributes,
            "indices": idx_accessor,
            "material": material_index[key],
            "mode": 4,
        })

    images = []
    textures = []
    if texture_colours and not native_pbr:
        for key in parts:
            while len(buffer) % 4:
                buffer.append(0)
            image = material_images[key]
            offset = len(buffer)
            buffer.extend(image)
            buffer_views.append({
                "buffer": 0, "byteOffset": offset, "byteLength": len(image),
            })
            images.append({"bufferView": len(buffer_views) - 1,
                           "mimeType": "image/png"})
            textures.append({"sampler": 0, "source": len(images) - 1})
            pbr = materials[material_index[key]]["pbrMetallicRoughness"]
            pbr["baseColorTexture"] = {"index": len(textures) - 1}

    gltf = {
        "asset": {"version": "2.0", "generator": "MolStudio molecule exporter"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": title}],
        "meshes": [{"name": title, "primitives": primitives}],
        "materials": materials,
        "buffers": [{"byteLength": len(buffer)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
        "extras": {
            "chemistry": {
                "atoms": int(visible.sum()),
                "hidden_atoms": int((~visible).sum()),
                "bonds": int(len(ordered)),
                "multiple_bonds": int(sum(1 for _i, _j, order in ordered
                                          if order > 1)),
                "contact_ao": bool(native_pbr and bake_ao),
                "ao_rays": int(ao_rays if native_pbr and bake_ao else 0),
                "atom_outline": bool("__outline__" in parts),
                "surface_layers": surface_metadata,
                "source": "MolStudio",
                "powerpoint": "Insert > 3D Models > This Device",
            }
        },
    }
    if unlit:
        gltf["extensionsUsed"] = ["KHR_materials_unlit"]
    if texture_colours and not native_pbr:
        gltf["samplers"] = [{
            "magFilter": 9728, "minFilter": 9728,
            "wrapS": 33071, "wrapT": 33071,
        }]
        gltf["images"] = images
        gltf["textures"] = textures
    return gltf, bytes(buffer)


def surface_layers_from_canvas(glw, *,
                               bohr_to_angstrom: float = 0.529177210903):
    """Snapshot visible isosurfaces from a MolStudio OpenGL canvas.

    The canvas stores positions in Bohr; GLB uses Angstrom. Vertex colours
    and normals are preserved so ESP maps and multi-orbital phase colours
    survive the transfer. AICD current arrows are exported as an opaque
    vertex-coloured overlay when they are visible.
    """
    if glw is None:
        return []
    try:
        opacity = max(0.0, min(1.0, float(glw._sp.get("opacity", 1.0))))
        roughness = max(0.03, min(1.0, float(glw._sp.get("roughness", 0.52))))
    except (AttributeError, TypeError, ValueError):
        opacity, roughness = 1.0, 0.52

    if getattr(glw, "_surf_vcolor", False):
        kind = "esp"
        names = ("Electrostatic potential surface", "")
    elif getattr(glw, "_orbital_recs", None):
        kind = "orbital"
        names = ("Molecular orbital — positive phase",
                 "Molecular orbital — negative phase")
    else:
        kind = "isosurface"
        names = ("Positive-phase isosurface", "Negative-phase isosurface")

    layers = []
    for index, (surface, name) in enumerate(zip(
            (getattr(glw, "_pos_surf", None),
             getattr(glw, "_neg_surf", None)), names)):
        if surface is None or getattr(surface, "vertex_count", 0) <= 0:
            continue
        colors = getattr(surface, "colors", None)
        if colors is None:
            fallback = (getattr(glw, "_pc", (0.65, 0.75, 0.90))
                        if index == 0 else
                        getattr(glw, "_nc", (0.90, 0.55, 0.45)))
            colors = tuple(float(v) for v in fallback[:3])
        normals = getattr(surface, "normals", None)
        layers.append(SurfaceLayer(
            name=name or f"Isosurface {index + 1}",
            vertices=np.asarray(surface.vertices, dtype=float)
            * float(bohr_to_angstrom),
            normals=(None if normals is None
                     else np.asarray(normals, dtype=float)),
            indices=np.asarray(surface.indices),
            colors=colors,
            opacity=opacity,
            roughness=roughness,
            kind=kind,
        ))

    aicd = getattr(glw, "_aicd_surf", None)
    if (aicd is not None and getattr(glw, "_aicd_show", False)
            and getattr(aicd, "vertex_count", 0) > 0):
        normals = getattr(aicd, "normals", None)
        layers.append(SurfaceLayer(
            name="AICD induced-current arrows",
            vertices=np.asarray(aicd.vertices, dtype=float)
            * float(bohr_to_angstrom),
            normals=(None if normals is None
                     else np.asarray(normals, dtype=float)),
            indices=np.asarray(aicd.indices),
            colors=aicd.colors,
            opacity=1.0,
            roughness=0.55,
            kind="aicd_arrows",
        ))
    return layers


def export_glb(path, symbols: Iterable[str], coords, *, bonds=None,
               bond_orders=None, atom_colors=None, atom_radii=None,
               visible_atoms=None, bond_color=None, bond_radius=None,
               bond_dual_colors=False, view_rotation=None,
               roughness=0.48, bond_roughness=0.65, unlit=False,
               texture_colours=False, native_pbr=False, high_detail=False,
               bake_ao=True, ao_rays=8, atom_outline=False,
               outline_ratio=0.045, outline_color=(0.0, 0.0, 0.0),
               surfaces=None, title: str = "Molecule") -> Path:
    """Write a molecule and optional isosurfaces as a PowerPoint GLB.

    The returned file can be inserted in Microsoft 365 PowerPoint through
    ``Insert > 3D Models > This Device``. PowerPoint normalises the model size
    and provides rotation controls; the source remains editable in MolStudio.
    Surface layers use the same Angstrom coordinate system as ``coords``.
    """
    symbols = [_symbol(s) for s in symbols]
    coords = np.asarray(coords, dtype=float)
    if not symbols or coords.ndim != 2 or coords.shape[1] != 3:
        raise ValueError("分子结构为空或坐标格式不正确")
    if coords.shape[0] != len(symbols):
        raise ValueError("原子数与坐标行数不一致")
    if not np.isfinite(coords).all():
        raise ValueError("分子坐标含非有限数值")

    if bonds is None:
        bonds = _infer_bonds(symbols, coords)
    gltf, binary = _build_gltf(
        symbols, coords, bonds, str(title or "Molecule"),
        bond_orders=bond_orders, atom_colors=atom_colors,
        atom_radii=atom_radii, visible_atoms=visible_atoms,
        bond_color=bond_color, bond_radius=bond_radius,
        bond_dual_colors=bond_dual_colors,
        view_rotation=view_rotation, roughness=roughness,
        bond_roughness=bond_roughness, unlit=unlit,
        texture_colours=texture_colours, native_pbr=native_pbr,
        high_detail=high_detail, bake_ao=bake_ao, ao_rays=ao_rays,
        atom_outline=atom_outline, outline_ratio=outline_ratio,
        outline_color=outline_color, surfaces=surfaces)
    json_bytes = json.dumps(gltf, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * ((4 - len(json_bytes) % 4) % 4)
    binary += b"\0" * ((4 - len(binary) % 4) % 4)

    total = 12 + 8 + len(json_bytes) + 8 + len(binary)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as fh:
        fh.write(struct.pack("<III", 0x46546C67, 2, total))
        fh.write(struct.pack("<II", len(json_bytes), 0x4E4F534A))
        fh.write(json_bytes)
        fh.write(struct.pack("<II", len(binary), 0x004E4942))
        fh.write(binary)
    validate_glb(output)
    return output


def validate_glb(path) -> dict:
    """Validate the GLB invariants PowerPoint is strict about.

    In particular every accessor must fit inside its referenced bufferView.
    The Khronos validator reports this as ``ACCESSOR_TOO_LONG``; PowerPoint
    refuses to import such a file with a generic "error importing this file".
    """
    raw = Path(path).read_bytes()
    if len(raw) < 20:
        raise ValueError("GLB 文件头不完整")
    magic, version, total = struct.unpack_from("<III", raw, 0)
    if magic != 0x46546C67 or version != 2 or total != len(raw):
        raise ValueError("GLB 文件头或总长度无效")
    json_len, json_type = struct.unpack_from("<II", raw, 12)
    if json_type != 0x4E4F534A:
        raise ValueError("GLB 缺少 JSON 数据块")
    json_end = 20 + json_len
    if json_end + 8 > len(raw):
        raise ValueError("GLB JSON 数据块被截断")
    try:
        gltf = json.loads(raw[20:json_end].decode("utf-8").rstrip(" \x00"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("GLB JSON 数据无效") from exc
    binary_len, binary_type = struct.unpack_from("<II", raw, json_end)
    if binary_type != 0x004E4942 or json_end + 8 + binary_len != len(raw):
        raise ValueError("GLB 二进制数据块无效")
    if not gltf.get("meshes") or not gltf["meshes"][0].get("primitives"):
        raise ValueError("GLB 不包含可显示的 3D 网格")
    views = gltf.get("bufferViews") or []
    for index, accessor in enumerate(gltf.get("accessors") or []):
        try:
            view = views[int(accessor["bufferView"])]
            component = _COMPONENT_BYTES[int(accessor["componentType"])]
            components = _TYPE_COMPONENTS[str(accessor["type"])]
            needed = (int(accessor.get("byteOffset", 0))
                      + int(accessor["count"]) * component * components)
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise ValueError(f"GLB accessor {index} 无效") from exc
        if needed > int(view["byteLength"]):
            raise ValueError(f"GLB accessor {index} 超出 bufferView 边界")
    return gltf


__all__ = [
    "ATOM_RADII", "BOND_RADIUS", "ELEMENT_COLOURS",
    "SurfaceLayer", "export_glb", "surface_layers_from_canvas", "validate_glb",
]
