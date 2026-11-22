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


# ── surface-only atomic-orbital export (structure library) ──────────────

def _orbital_layers(ident="2pz", **kwargs):
    from molstudio.core.atomic_orbital import orbital_by_id
    from molstudio.core.molecule_export import orbital_surface_layers

    return orbital_surface_layers(orbital_by_id(ident), **kwargs)


def test_atomless_surface_only_glb_is_valid(tmp_path):
    """A model with no atoms must still be a valid, PowerPoint-importable GLB."""
    layers = _orbital_layers(iso=0.08, quality="low")
    assert [layer.kind for layer in layers] == ["orbital", "orbital"]
    assert [layer.name for layer in layers] == [
        "Orbital — positive phase", "Orbital — negative phase"]
    # The orbital mesh uses the same phase colours as the library preview.
    assert layers[0].colors == pytest.approx((43 / 255, 108 / 255, 176 / 255))
    assert layers[1].colors == pytest.approx((224 / 255, 83 / 255, 59 / 255))
    # Cube coordinates are Bohr; the GLB is Angstrom (2p_z reaches ~5.5 A).
    assert float(np.abs(layers[0].vertices).max()) < 6.0

    target = export_glb(
        tmp_path / "2pz.glb", [], np.zeros((0, 3)), surfaces=layers,
        native_pbr=True, high_detail=True, title="2p_z")

    gltf = validate_glb(target)
    assert gltf["extras"]["chemistry"]["atoms"] == 0
    assert gltf["extras"]["chemistry"]["surface_layers"] == [
        {"name": layer.name, "kind": "orbital",
         "vertices": len(layer.vertices), "triangles": len(layer.indices) // 3,
         "opacity": 1.0}
        for layer in layers
    ]
    names = [material["name"] for material in gltf["materials"]]
    # No empty "Molecule" material is left behind for an atom-less scene.
    assert "Molecule" not in names
    assert names == ["Orbital — positive phase", "Orbital — negative phase"]
    assert len(gltf["meshes"][0]["primitives"]) == 2
    for primitive in gltf["meshes"][0]["primitives"]:
        material = gltf["materials"][primitive["material"]]
        assert material["alphaMode"] == "OPAQUE"     # phase lobes are solid
        assert material["doubleSided"] is True
        assert set(primitive["attributes"]) == {"POSITION", "NORMAL", "COLOR_0"}


def test_orbital_surface_mesh_is_closed():
    """Exported lobes must be watertight: the canvas grid is clipped, GLB is not."""
    layers = _orbital_layers(ident="3dz2", iso=0.08, quality="low")
    for layer in layers:
        tri = np.asarray(layer.indices).reshape(-1, 3)
        edges = np.sort(np.concatenate(
            [tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]), axis=1)
        _, counts = np.unique(edges, axis=0, return_counts=True)
        assert int((counts == 1).sum()) == 0, layer.name


def test_orbital_export_follows_canvas_phase_colours(tmp_path):
    """改画布配色 / 透明度 / 粗糙度 / 翻转相位后，导出的 .glb 必须跟着变。"""
    from types import SimpleNamespace

    from molstudio.core.atomic_orbital import orbital_by_id
    from molstudio.core.ppt3d_options import Ppt3dOptions
    from molstudio.ui.main_window import OrbitalVisApp

    app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841

    def _export(flipped: bool):
        glw = SimpleNamespace(
            _surf_vcolor=False,
            _orbital_recs=[object()],
            _pc=(1.0, 0.0, 0.0),        # 正相位：红
            _nc=(0.0, 0.0, 1.0),        # 负相位：蓝
            _orbital_flipped=[flipped],
            _sp={"opacity": 0.5, "roughness": 0.2},
            cam=None,
        )
        out = tmp_path / ("flipped.glb" if flipped else "palette.glb")
        window = SimpleNamespace(
            cub_canvas=SimpleNamespace(glw=glw),
            _lang="zh",
            _current_cubes=["2pz_low.cub"],
            _library_orbital_cube="2pz_low.cub",
            _library_orbital_spec="2pz",
            ORBITAL_PHASE_POS=(43, 108, 176),
            ORBITAL_PHASE_NEG=(224, 83, 59),
            _canvas_orbital_style=OrbitalVisApp._canvas_orbital_style,
            _ppt3d_save_path=lambda stem, start_dir=None: str(out),
            _ppt3d_report=lambda *args, **kwargs: None,
        )
        OrbitalVisApp._library_export_orbital(
            window, orbital_by_id("2pz"), 0.08, "low", Ppt3dOptions())
        return validate_glb(out), out.read_bytes()

    def _colour_of(gltf, raw, name):
        primitive = next(
            prim for prim in gltf["meshes"][0]["primitives"]
            if gltf["materials"][prim["material"]]["name"] == name)
        return _float_accessor(raw, gltf, primitive["attributes"]["COLOR_0"])[0]

    gltf, raw = _export(flipped=False)
    pos = next(m for m in gltf["materials"] if m["name"].endswith("positive phase"))
    neg = next(m for m in gltf["materials"] if m["name"].endswith("negative phase"))
    for material in (pos, neg):
        assert material["alphaMode"] == "BLEND"
        assert material["pbrMetallicRoughness"]["baseColorFactor"][3] == \
            pytest.approx(0.5)
        assert material["pbrMetallicRoughness"]["roughnessFactor"] == \
            pytest.approx(0.2)
    assert _colour_of(gltf, raw, "Orbital — positive phase") == pytest.approx(
        [1.0, 0.0, 0.0], abs=2e-6)
    assert _colour_of(gltf, raw, "Orbital — negative phase") == pytest.approx(
        [0.0, 0.0, 1.0], abs=2e-6)

    # 翻转相位后正 / 负两层的颜色互换（_pc/_nc 本身不变）
    gltf_f, raw_f = _export(flipped=True)
    assert _colour_of(gltf_f, raw_f, "Orbital — positive phase") == pytest.approx(
        [0.0, 0.0, 1.0], abs=2e-6)
    assert _colour_of(gltf_f, raw_f, "Orbital — negative phase") == pytest.approx(
        [1.0, 0.0, 0.0], abs=2e-6)


def test_export_glb_rejects_empty_scene(tmp_path):
    target = tmp_path / "empty.glb"
    with pytest.raises(ValueError):
        export_glb(target, [], np.zeros((0, 3)))
    assert not target.exists(), "失败时不能留下只有文件头的 .glb"

    invisible = _tetra_surface(opacity=0.0)
    with pytest.raises(ValueError):
        export_glb(target, [], np.zeros((0, 3)), surfaces=[invisible])
    assert not target.exists()
