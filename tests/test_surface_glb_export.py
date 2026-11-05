# -*- coding: utf-8 -*-
"""Combined molecule + isosurface export for PowerPoint GLB."""

import json
import os
import struct
import sys
from types import SimpleNamespace

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtGui import QColor, QImage
from PyQt5.QtWidgets import QApplication

from molstudio.core.marching_cubes import IsoSurface
from molstudio.core.molecule_export import (
    SurfaceLayer, export_glb, surface_layers_from_canvas, validate_glb,
)


def _tetra_surface(*, colors=None, opacity=0.62, normals=True):
    return SurfaceLayer(
        name="ESP surface",
        vertices=np.array([
            (-1.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0),
        ]),
        normals=(np.array([
            (-1.0, -1.0, -1.0),
            (1.0, -1.0, -1.0),
            (-1.0, 1.0, -1.0),
            (-1.0, -1.0, 1.0),
        ]) if normals else None),
        indices=np.array([0, 2, 1, 0, 1, 3, 1, 2, 3, 2, 0, 3]),
        colors=colors,
        opacity=opacity,
        roughness=0.58,
        kind="esp",
    )


def _read_gltf(path):
    raw = path.read_bytes()
    json_len = struct.unpack_from("<I", raw, 12)[0]
    return raw, json.loads(raw[20:20 + json_len].decode("utf-8"))


def _float_accessor(raw, gltf, accessor_index):
    accessor = gltf["accessors"][accessor_index]
    view = gltf["bufferViews"][accessor["bufferView"]]
    json_len = struct.unpack_from("<I", raw, 12)[0]
    binary_start = 20 + json_len + 8
    start = binary_start + view["byteOffset"] + accessor.get("byteOffset", 0)
    components = {"VEC3": 3, "VEC4": 4, "SCALAR": 1}[accessor["type"]]
    return np.frombuffer(
        raw, dtype=np.float32 if accessor["componentType"] == 5126
        else np.uint32,
        count=accessor["count"] * components, offset=start,
    ).reshape(accessor["count"], components)


def test_glb_contains_transparent_vertex_coloured_surface(tmp_path):
    symbols = ["O", "H", "H"]
    coords = np.array([[0.0, 0.0, 0.0], [0.96, 0.0, 0.0], [-0.24, 0.93, 0.0]])
    colors = np.array([
        [1.0, 0.0, 0.0],
        [1.0, 1.0, 1.0],
        [0.0, 0.0, 1.0],
        [0.0, 1.0, 0.0],
    ])
    target = export_glb(
        tmp_path / "esp_scene.glb", symbols, coords,
        bonds=[(0, 1), (0, 2)], surfaces=[_tetra_surface(colors=colors)],
        native_pbr=True, atom_outline=True, title="ESP scene",
    )

    raw, gltf = _read_gltf(target)
    assert validate_glb(target)["asset"]["version"] == "2.0"
    surface_primitive = next(
        primitive for primitive in gltf["meshes"][0]["primitives"]
        if gltf["materials"][primitive["material"]]["name"] == "ESP surface"
    )
    material = gltf["materials"][surface_primitive["material"]]
    assert material["alphaMode"] == "BLEND"
    assert material["doubleSided"] is True
    assert material["pbrMetallicRoughness"]["baseColorFactor"][3] == pytest.approx(0.62)
    assert set(surface_primitive["attributes"]) == {
        "POSITION", "NORMAL", "COLOR_0",
    }

    surface_colors = _float_accessor(
        raw, gltf, surface_primitive["attributes"]["COLOR_0"])
    assert surface_colors.shape == (4, 3)
    assert surface_colors[0] == pytest.approx([1.0, 0.0, 0.0], abs=2e-6)
    assert surface_colors[1] == pytest.approx([1.0, 1.0, 1.0], abs=2e-6)
    assert gltf["extras"]["chemistry"]["surface_layers"] == [{
        "name": "ESP surface",
        "kind": "esp",
        "vertices": 4,
        "triangles": 4,
        "opacity": 0.62,
    }]

    molecule_primitive = next(
        primitive for primitive in gltf["meshes"][0]["primitives"]
        if gltf["materials"][primitive["material"]]["name"] == "Molecule"
    )
    assert gltf["materials"][molecule_primitive["material"]].get(
        "alphaMode", "OPAQUE") == "OPAQUE"


def test_canvas_surface_snapshot_converts_bohr_and_keeps_colours():
    pos = IsoSurface()
    pos.vertices = np.array([[1.0, 2.0, 3.0]], dtype=np.float32)
    pos.normals = np.array([[0.0, 0.0, 1.0]], dtype=np.float32)
    pos.indices = np.array([0, 0, 0], dtype=np.uint32)
    pos.colors = np.array([[0.2, 0.4, 0.8, 1.0]], dtype=np.float32)
    glw = SimpleNamespace(
        _pos_surf=pos,
        _neg_surf=None,
        _surf_vcolor=True,
        _orbital_recs=[],
        _pc=(0.2, 0.4, 0.8),
        _nc=(0.8, 0.4, 0.2),
        _sp={"opacity": 0.7, "roughness": 0.44},
        _aicd_surf=None,
        _aicd_show=False,
    )

    layers = surface_layers_from_canvas(glw)
    assert len(layers) == 1
    layer = layers[0]
    assert layer.kind == "esp"
    assert layer.vertices[0] == pytest.approx(
        np.array([1.0, 2.0, 3.0]) * 0.529177210903)
    assert layer.opacity == pytest.approx(0.7)
    assert layer.roughness == pytest.approx(0.44)
    assert layer.colors.shape == (1, 4)


def test_hidden_or_zero_opacity_surface_is_not_exported(tmp_path):
    hidden = _tetra_surface(opacity=0.0)
    target = export_glb(
        tmp_path / "molecule_only.glb", ["H", "H"],
        [[0.0, 0.0, 0.0], [0.74, 0.0, 0.0]],
        bonds=[(1, 2)], surfaces=[hidden], native_pbr=True,
    )
    _raw, gltf = _read_gltf(target)
    assert gltf["extras"]["chemistry"]["surface_layers"] == []
    assert all(mat["name"] != "ESP surface" for mat in gltf["materials"])


def test_missing_surface_normals_are_computed(tmp_path):
    target = export_glb(
        tmp_path / "computed_normals.glb", ["H", "H"],
        [[0.0, 0.0, 0.0], [0.74, 0.0, 0.0]],
        bonds=[(1, 2)], surfaces=[_tetra_surface(normals=False)],
        native_pbr=True,
    )
    _raw, gltf = _read_gltf(target)
    surface_primitive = next(
        primitive for primitive in gltf["meshes"][0]["primitives"]
        if gltf["materials"][primitive["material"]]["name"] == "ESP surface"
    )
    normals = _float_accessor(
        _raw, gltf, surface_primitive["attributes"]["NORMAL"])
    assert np.linalg.norm(normals, axis=1) == pytest.approx(
        np.ones(4), abs=2e-6)


def test_esp_legend_png_is_written_beside_glb(tmp_path):
    app = QApplication.instance() or QApplication(sys.argv)
    from molstudio.ui.main_window import OrbitalVisApp

    glw = SimpleNamespace(
        _surf_vcolor=True,
        _cs_low=-0.04,
        _cs_high=0.06,
        _cs_unit="ESP (a.u.)",
        _cs_cmap_rgb=lambda t: (1.0 - t, t, 0.25),
    )
    layer = _tetra_surface()
    target = tmp_path / "esp_scene.glb"
    legend = OrbitalVisApp._write_ppt3d_esp_legend(
        target, glw, [layer])
    assert legend == str(tmp_path / "esp_scene_legend.png")
    image = QImage(legend)
    assert image.width() == 1200 and image.height() == 256
    assert QColor(image.pixel(200, 150)) != QColor("#FFFFFF")
    app.processEvents()
