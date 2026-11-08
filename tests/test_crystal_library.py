# -*- coding: utf-8 -*-
"""Built-in crystal library: manifest, filtering and every bundled CIF."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from molstudio.core import crystal_library as cl  # noqa: E402
from molstudio.core import ppt3d_options as po  # noqa: E402


def test_manifest_is_complete():
    root = cl.crystal_library_dir()
    assert root is not None, "crystal_library assets missing"
    entries = cl.load_crystal_library()
    assert len(entries) >= 40
    assert len({e.id for e in entries}) == len(entries)
    for entry in entries:
        assert entry.category in cl.CATEGORY_ORDER
        assert entry.level in cl.LEVEL_LABELS
        assert cl.crystal_path(entry).is_file(), entry.id
        assert entry.structure_type and entry.teaching_point
        assert entry.source
    # Every real COD CIF must keep its citation/database header.
    for entry in entries:
        if not entry.generated:
            text = cl.crystal_path(entry).read_text(
                encoding="utf-8", errors="replace")
            assert "_cell_length_a" in text
            assert "COD" in text.upper() or "AMCSD" in text.upper()


def test_previews_and_categories():
    entries = cl.load_crystal_library()
    previews = sum(1 for e in entries if cl.crystal_preview(e) is not None)
    assert previews >= len(entries) - 6
    for key in cl.CATEGORY_ORDER:
        assert cl.filter_crystals(entries, key)


def test_filter_crystals():
    entries = cl.load_crystal_library()
    nacl = cl.filter_crystals(entries, "ionic", "NaCl")
    assert any(e.id == "nacl-halite" for e in nacl)
    assert all(e.category == "ionic" for e in nacl)
    assert cl.filter_crystals(entries, "all", "配位数 6") or \
        cl.filter_crystals(entries, "all", "均摊法")
    textbook = cl.filter_crystals(entries, "all", "", 1)
    assert textbook and all(e.level == 1 for e in textbook)
    assert not cl.filter_crystals(entries, "all", "不存在的结构xyz")


def test_generated_models_are_marked():
    entries = {e.id: e for e in cl.load_crystal_library()}
    assert entries["po-simple-cubic"].generated
    assert entries["dry-ice"].generated
    assert not entries["nacl-halite"].generated
    assert "教学" in entries["dry-ice"].description_zh
    assert "教学模型" in entries["dry-ice"].source
    assert entries["nacl-halite"].space_group.startswith("F m -3 m")


def test_options_scaling_and_view():
    opt = po.Ppt3dOptions(atom_scale=1.5, bond_scale=0.8,
                          hide_hydrogens=True, keep_view=False,
                          native_pbr=True, unlit=True,
                          include_surfaces=False)
    base = {"atom_radii": [0.4, 0.3], "bond_radius": 0.1,
            "view_rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            "surfaces": ["layer"]}
    out = opt.apply_to(base, ["C", "H"])
    assert out["atom_radii"] == pytest.approx([0.6, 0.45])
    assert out["bond_radius"] == pytest.approx(0.08)
    assert out["visible_atoms"] == [True, False]
    assert "view_rotation" not in out
    assert out["surfaces"] == []
    # unlit and native PBR are mutually exclusive
    assert out["unlit"] is True and out["native_pbr"] is False


def test_options_cell_box_spec_and_roundtrip():
    opt = po.Ppt3dOptions(show_cell_box=True, cell_line_width=0.08,
                          cell_color="#112233", supercell=(2, 1, 3))
    spec = opt.cell_box_spec([[0, 0, 0]] * 8)
    assert spec["radius"] == 0.08
    assert spec["color"] == "#112233"
    assert opt.reps() == (2, 1, 3)
    assert po.Ppt3dOptions(show_cell_box=False).cell_box_spec([[0, 0, 0]] * 8) is None
    data = opt.as_dict()
    assert po.Ppt3dOptions.from_dict(data) == opt
    assert po.Ppt3dOptions.from_dict({"supercell": [9, -2, 2]}).reps() == (3, 1, 2)


def _load_parser():
    """Import crystal_lib's pure CIF parser without the OpenGL canvas module.

    The real module imports ``ovcanvas._glwidget``, which needs a live GL
    context; headless tests only need ``parse_cif`` / ``cell_matrix``.
    """
    source = (ROOT / "molstudio" / "core" / "crystal_lib.py").read_text(
        encoding="utf-8")
    pattern = (r"from molstudio\.render\.ovcanvas\._glwidget import "
               r"\([\s\S]*?\)\n")
    assert re.search(pattern, source), "GL import block changed"
    source = re.sub(
        pattern,
        "BOHR_TO_ANGSTROM = 0.529177210903\n"
        "CubGLWidget = object\n_COV_RADII_BOHR = {}\n",
        source, count=1)
    namespace = {
        "__name__": "crystal_lib_headless",
        "__package__": "molstudio.core",
        "__file__": str(ROOT / "molstudio" / "core" / "crystal_lib.py"),
    }
    exec(compile(source, "crystal_lib.py", "exec"), namespace)  # noqa: S102
    return namespace


def test_every_cif_parses_to_atoms():
    ns = _load_parser()
    parse_cif = ns["parse_cif"]
    entries = cl.load_crystal_library()
    for entry in entries:
        text = cl.crystal_path(entry).read_text(
            encoding="utf-8", errors="replace")
        cell, sites = parse_cif(text)
        assert len(cell) == 6 and cell[0] > 0, entry.id
        assert sites, entry.id
        assert all(sym and len(frac) == 3 for sym, frac in sites), entry.id
    # The two teaching cells have the textbook cell contents.
    by_id = {e.id: e for e in entries}
    _, po_sites = parse_cif(
        cl.crystal_path(by_id["po-simple-cubic"]).read_text(encoding="utf-8"))
    assert len(po_sites) == 1
    _, co2_sites = parse_cif(
        cl.crystal_path(by_id["dry-ice"]).read_text(encoding="utf-8"))
    assert len(co2_sites) == 12
