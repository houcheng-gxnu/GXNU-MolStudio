# -*- coding: utf-8 -*-
"""Bundled molecule library and PowerPoint GLB export tests."""

import json
import os
import struct
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication
import numpy as np
import pytest

from molstudio.core.molecule_export import export_glb, validate_glb
from molstudio.core.molecule_library import (
    CATEGORY_ORDER, filter_molecules, load_library, load_molecule,
    molecule_path,
)


def test_manifest_and_all_xyz_assets_are_valid():
    entries = load_library()
    assert len(entries) >= 60
    assert len({entry.id for entry in entries}) == len(entries)
    assert {entry.category for entry in entries} == set(CATEGORY_ORDER)
    for entry in entries:
        assert entry.name_zh and entry.name_en and entry.formula
        path = molecule_path(entry)
        assert path.suffix.lower() == ".xyz"
        molecule = load_molecule(entry)
        assert molecule.atom_count > 0
        assert len(molecule.symbols) == molecule.positions.shape[0]
        expected = {
            tuple(sorted((int(a), int(b)))) for a, b, _order in entry.bond_orders
        }
        inferred = {
            tuple(sorted((int(a), int(b)))) for a, b in molecule.bonds
        }
        assert inferred == expected, f"{entry.id} 的缩略图键连与结构清单不一致"
    ethene = next(entry for entry in entries if entry.id == "ethene")
    assert any(order == 2 for _a, _b, order in ethene.bond_orders)
    serotonin = next(entry for entry in entries if entry.id == "serotonin")
    assert serotonin.formula == "C10H12N2O"
    assert load_molecule(serotonin).atom_count == 25
    sf6 = next(entry for entry in entries if entry.id == "sulfur-hexafluoride")
    sf6_mol = load_molecule(sf6)
    dists = sorted(
        float(np.linalg.norm(sf6_mol.positions[i] - sf6_mol.positions[0]))
        for i in range(1, 7)
    )
    assert dists == pytest.approx([1.56] * 6, abs=1e-6)


def test_library_category_and_alias_search():
    entries = load_library()
    water = filter_molecules(entries, query="H2O")
    assert any(entry.id == "water" for entry in water)
    organic = filter_molecules(entries, category="organic")
    assert organic
    assert all(entry.category == "organic" for entry in organic)
    assert any(entry.id == "benzene" for entry in filter_molecules(entries, query="苯"))


def test_powerpoint_glb_is_self_contained(tmp_path):
    entry = next(item for item in load_library() if item.id == "ethanol")
    molecule = load_molecule(entry)
    target = export_glb(
        tmp_path / "ethanol.glb", molecule.symbols, molecule.positions,
        bonds=molecule.bonds, title=entry.name_en)

    raw = target.read_bytes()
    magic, version, total = struct.unpack("<III", raw[:12])
    json_len, json_type = struct.unpack("<II", raw[12:20])
    assert magic == 0x46546C67
    assert version == 2
    assert total == len(raw)
    assert json_type == 0x4E4F534A

    gltf = json.loads(raw[20:20 + json_len].decode("utf-8"))
    assert validate_glb(target)["asset"]["version"] == "2.0"
    assert gltf["asset"]["version"] == "2.0"
    assert gltf["meshes"][0]["primitives"]
    assert gltf["buffers"][0]["byteLength"] > 0
    assert gltf["extras"]["chemistry"]["atoms"] == molecule.atom_count
    assert gltf["extras"]["chemistry"]["bonds"] == molecule.bond_count
    assert {mat["name"] for mat in gltf["materials"]} >= {"C", "H", "O", "Bond"}

    binary_len, binary_type = struct.unpack(
        "<II", raw[20 + json_len:28 + json_len])
    assert binary_type == 0x004E4942
    assert binary_len == gltf["buffers"][0]["byteLength"]
    assert 20 + json_len + 8 + binary_len == len(raw)
    for accessor in gltf["accessors"]:
        view = gltf["bufferViews"][accessor["bufferView"]]
        components = {"SCALAR": 1, "VEC3": 3}[accessor["type"]]
        component_bytes = {5126: 4, 5125: 4, 5123: 2}[
            accessor["componentType"]]
        size = (accessor.get("byteOffset", 0)
                + accessor["count"] * components * component_bytes)
        assert size <= view["byteLength"]

    ethene = next(item for item in load_library() if item.id == "ethene")
    molecule = load_molecule(ethene)
    target = export_glb(
        tmp_path / "ethene.glb", molecule.symbols, molecule.positions,
        bonds=molecule.bonds)
    raw = target.read_bytes()
    json_len = struct.unpack("<I", raw[12:16])[0]
    gltf = json.loads(raw[20:20 + json_len].decode("utf-8"))
    assert gltf["extras"]["chemistry"]["multiple_bonds"] == 0


def test_canvas_style_colours_and_orientation_are_exported(tmp_path):
    entry = next(item for item in load_library() if item.id == "water")
    molecule = load_molecule(entry)
    colours = [(0.667, 0.667, 0.667), (1.0, 1.0, 1.0), (1.0, 1.0, 1.0)]
    rotation = np.array([[0.0, -1.0, 0.0],
                         [1.0, 0.0, 0.0],
                         [0.0, 0.0, 1.0]])
    target = export_glb(
        tmp_path / "water_style.glb", molecule.symbols, molecule.positions,
        bonds=molecule.bonds, atom_colors=colours,
        atom_radii=[0.22, 0.16, 0.16], visible_atoms=[True, True, False],
        bond_color=(0.0, 0.0, 0.0), bond_radius=0.09,
        view_rotation=rotation, roughness=0.5, native_pbr=True,
        high_detail=True, atom_outline=True, title="Water")
    gltf = validate_glb(target)
    assert len(gltf["materials"]) == 2
    assert {mat["doubleSided"] for mat in gltf["materials"]} == {True, False}
    for primitive in gltf["meshes"][0]["primitives"]:
        assert set(primitive["attributes"]) == {"POSITION", "NORMAL", "COLOR_0"}
    assert gltf["extras"]["chemistry"]["atoms"] == 2
    assert gltf["extras"]["chemistry"]["hidden_atoms"] == 1
    assert gltf["extras"]["chemistry"]["contact_ao"] is True
    assert gltf["extras"]["chemistry"]["atom_outline"] is True
    assert "extensionsUsed" not in gltf
    assert "textures" not in gltf and "images" not in gltf


def test_library_dialog_filters_and_visualizes():
    app = QApplication.instance() or QApplication(sys.argv)
    from PyQt5.QtCore import Qt
    from molstudio.ui.molecule_library_dialog import MoleculeLibraryDialog

    selected = []
    dialog = MoleculeLibraryDialog(
        lang="zh", on_visualize=lambda path, entry: selected.append((path, entry.id)))
    try:
        dialog.show()
        app.processEvents()
        assert dialog.list_widget.count() >= 60
        cached_ids = {key[0] for key in dialog._icons
                      if isinstance(key[0], str)}
        assert {entry.id for entry in load_library()} <= cached_ids
        icon_keys = [dialog.list_widget.item(i).icon().cacheKey()
                     for i in range(dialog.list_widget.count())]
        assert len(set(icon_keys)) == len(icon_keys), "不同分子的缩略图发生串图"
        dialog.edit_search.setText("H2O")
        app.processEvents()
        assert dialog.list_widget.count() >= 1
        item = dialog.list_widget.item(0)
        dialog.list_widget.setCurrentItem(item)
        app.processEvents()
        assert "O" in dialog.lbl_formula.text() or "H" in dialog.lbl_formula.text()
        dialog._visualize_selected()
        assert selected and selected[0][1] == "water"
    finally:
        dialog.close()


def test_library_ppt_export_uses_canvas_style_callback(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication(sys.argv)
    from PyQt5.QtWidgets import QFileDialog, QMessageBox
    from molstudio.ui.molecule_library_dialog import MoleculeLibraryDialog

    dialog = MoleculeLibraryDialog(lang="zh")
    calls = []
    target = tmp_path / "water_canvas_style.glb"
    dialog._on_export_ppt = lambda path, entry: calls.append((path, entry.id))
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        lambda *args, **kwargs: (str(target), "PowerPoint 3D model (*.glb)"))
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *args, **kwargs: QMessageBox.Ok)
    try:
        dialog.show()
        app.processEvents()
        dialog.edit_search.setText("H2O")
        app.processEvents()
        dialog.list_widget.setCurrentItem(dialog.list_widget.item(0))
        app.processEvents()
        dialog._export_selected_ppt()
        assert calls and calls[0][1] == "water"
        assert calls[0][0] == target
    finally:
        dialog.close()


__all__ = []
