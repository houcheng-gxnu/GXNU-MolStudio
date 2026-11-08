# -*- coding: utf-8 -*-
"""Periodic crystals must bond only within the first coordination shell.

Regression: the covalent-radius heuristic (1.3 * (cov_i + cov_j)) draws
Na-Na contacts at 3.99 A in a NaCl cell because Na has a 1.66 A covalent
radius.  The crystal tab and PowerPoint GLB export now share
``molstudio.core.bonding``'s first-shell rule instead.
"""
from __future__ import annotations

import json
import os
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from molstudio.core.bonding import (  # noqa: E402
    crystal_bond_pairs, first_shell_pairs,
    nearest_neighbour_distances,
)
from molstudio.core.crystal_library import (  # noqa: E402
    crystal_geometry, load_crystal_library,
)
from molstudio.core.molecule_export import export_glb  # noqa: E402
from molstudio.core.steric.render import bonds as old_covalent_bonds  # noqa: E402

BOHR_TO_ANGSTROM = 0.529177210903


def _library():
    return {e.id: e for e in load_crystal_library()}


def _geometry(entry_id):
    return crystal_geometry(_library()[entry_id], (1, 1, 1), True, True)


def _gltf_bond_count(path):
    raw = Path(path).read_bytes()
    length, kind = struct.unpack("<II", raw[12:20])
    assert kind == 0x4E4F534A
    gltf = json.loads(raw[20:20 + length].decode("utf-8").rstrip(" "))
    return gltf["extras"]["chemistry"]["bonds"]


def test_nacl_has_no_distant_na_na_bonds():
    symbols, coords, _corners, _crystal = _geometry("nacl-halite")
    pos = np.asarray(coords)
    old = old_covalent_bonds(symbols, coords)
    new = crystal_bond_pairs(coords)
    assert len(old) == 90, "baseline changed; re-check the regression numbers"
    assert len(new) == 54
    lengths = [np.linalg.norm(pos[j] - pos[i]) for i, j in new]
    assert min(lengths) == pytest.approx(2.820, abs=0.01)
    assert max(lengths) == pytest.approx(2.820, abs=0.01)
    # every bond is Na-Cl; no Na-Na / Cl-Cl diagonal survives
    for i, j in new:
        assert {symbols[i], symbols[j]} == {"Na", "Cl"}
    dmin = nearest_neighbour_distances(coords)
    assert np.nanmin(dmin) == pytest.approx(2.820, abs=0.01)


def test_first_shell_rejects_second_neighbours_across_lattice_types():
    cases = {
        "c-diamond": (1.54, 1.54),
        "cscl": (3.57, 3.57),
        "caf2-fluorite": (2.37, 2.37),
        "catio3-perovskite": (1.94, 1.97),
        "c-graphite": (1.42, 1.42),
        "si-silicon": (2.35, 2.35),
    }
    for entry_id, (lo, hi) in cases.items():
        symbols, coords, _c, _x = _geometry(entry_id)
        pos = np.asarray(coords)
        pairs = crystal_bond_pairs(coords)
        assert pairs, entry_id
        lengths = [np.linalg.norm(pos[j] - pos[i]) for i, j in pairs]
        assert lo - 0.02 <= min(lengths) <= hi + 0.02, entry_id
        assert max(lengths) <= hi + 0.02, entry_id
        # first shell is a strict subset of the old heuristic
        assert len(pairs) <= len(old_covalent_bonds(symbols, coords)), entry_id


def test_canvas_bohr_rule_matches_export_angstrom_rule():
    """One numeric rule, two units: canvas (Bohr) == GLB export (Angstrom)."""
    _sym, coords, _c, _x = _geometry("nacl-halite")
    pos = np.asarray(coords)
    items_a = [(i, j, float(np.linalg.norm(pos[j] - pos[i])))
               for i in range(len(pos)) for j in range(i + 1, len(pos))]
    items_a = [t for t in items_a if t[2] > 1e-6]
    ang = set(crystal_bond_pairs(coords))
    bohr_items = [(i, j, r / BOHR_TO_ANGSTROM) for i, j, r in items_a]
    bohr = first_shell_pairs(
        bohr_items, len(pos),
        max_dist=4.5 / BOHR_TO_ANGSTROM)
    assert bohr == ang


def test_glb_export_uses_explicit_crystal_bonds(tmp_path):
    symbols, coords, _c, _x = _geometry("nacl-halite")
    bonds = [(i + 1, j + 1) for i, j in crystal_bond_pairs(coords)]
    out = tmp_path / "nacl.glb"
    export_glb(out, symbols, coords, title="NaCl", bonds=bonds)
    assert _gltf_bond_count(out) == 54


def test_glb_without_explicit_bonds_keeps_the_old_behaviour(tmp_path):
    """Molecule exports are deliberately untouched."""
    symbols, coords, _c, _x = _geometry("nacl-halite")
    out = tmp_path / "nacl_auto.glb"
    export_glb(out, symbols, coords, title="NaCl")
    assert _gltf_bond_count(out) == 90


def test_crystal_bonding_toggle_is_opt_in():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication
    from molstudio.render.ovcanvas._glwidget import CubGLWidget

    app = QApplication.instance() or QApplication([])  # noqa: F841
    glw = CubGLWidget()
    assert glw._crystal_bonding is False
    atoms = [(1, "Na", 11, (0.0, 0.0, 0.0)),
             (2, "Cl", 17, (2.82, 0.0, 0.0))]
    glw.set_molecule(atoms, crystal_bonding=True)
    assert glw._crystal_bonding is True
    glw.set_molecule(atoms)                 # molecule load resets the mode
    assert glw._crystal_bonding is False
    glw.set_crystal_bonding(True)
    assert glw._crystal_bonding is True


def test_coordination_polyhedra_follow_the_bond_table():
    from molstudio.core.crystal_lib import coordination_polyhedra
    _sym, coords, _c, crystal = _geometry("nacl-halite")
    atoms = crystal.supercell(1, 1, 1, fill_boundary=True)
    pairs = crystal_bond_pairs(coords)
    with_pairs = coordination_polyhedra(atoms, 11, bond_pairs=pairs)
    without = coordination_polyhedra(atoms, 11)
    assert with_pairs, "Na should have a Cl coordination polyhedron"
    # boundary atoms are truncated to 3/5 neighbours; the interior ones are 5
    assert all(3 <= len(p["nbrs"]) <= 6 for p in with_pairs)
    assert len(with_pairs) == len(without)

    # CsCl: the old 3.5 A cap misses Cs-Cl (3.57 A) entirely; the bond table
    # restores the 8-fold Cl coordination cube.
    _s, cs_co, _cc, cs = _geometry("cscl")
    cs_atoms = cs.supercell(1, 1, 1, fill_boundary=True)
    cs_pairs = crystal_bond_pairs(cs_co)
    assert coordination_polyhedra(cs_atoms, 17, bond_pairs=cs_pairs)
    assert coordination_polyhedra(cs_atoms, 17) == []
