# -*- coding: utf-8 -*-
"""Regression tests for ETS-NOCV structure parsing and local job generation."""

import os

from molstudio.panels.etsnocv import local_jobs
from molstudio.panels.etsnocv.molcanvas import get_atoms_from_any
from molstudio.core.gaussian_run import GaussianJobResult


def _log_orientation(kind, rows):
    lines = [
        kind + ":",
        " ---------------------------------------------------------------------",
        " Center     Atomic      Atomic             Coordinates (Angstroms)",
        " Number     Number       Type             X           Y           Z",
        " ---------------------------------------------------------------------",
    ]
    for idx, atomic_number, x, y, z in rows:
        lines.append(" %6d %6d %6d %14.6f %14.6f %14.6f" %
                     (idx, atomic_number, 0, x, y, z))
    lines.append(" ---------------------------------------------------------------------")
    lines.append("")
    return "\n".join(lines)


def test_log_parser_uses_last_standard_orientation_without_reading_basis(tmp_path):
    path = tmp_path / "job.log"
    path.write_text(
        _log_orientation("Standard orientation", [(1, 6, 0.0, 0.0, 0.0)]) +
        " Basis set exchange information\n" +
        _log_orientation("Standard orientation", [(1, 8, 1.0, 2.0, 3.0)]) +
        " Basis\n",
        encoding="utf-8")
    atoms = get_atoms_from_any(str(path))
    assert len(atoms) == 1
    assert atoms[0][1] == "O"
    assert atoms[0][3] == (1.0, 2.0, 3.0)


def test_log_parser_falls_back_to_input_orientation(tmp_path):
    path = tmp_path / "job.out"
    path.write_text(
        _log_orientation("Input orientation", [(1, 7, 0.0, 0.0, 0.0)]),
        encoding="utf-8")
    atoms = get_atoms_from_any(str(path))
    assert len(atoms) == 1 and atoms[0][1] == "N"


def test_log_parser_uses_last_table_even_if_it_is_input_orientation(tmp_path):
    path = tmp_path / "job.log"
    path.write_text(
        _log_orientation("Standard orientation", [(1, 6, 0.0, 0.0, 0.0)]) +
        _log_orientation("Input orientation", [(1, 6, 9.0, 8.0, 7.0)]) +
        " Normal termination of Gaussian 16\n",
        encoding="utf-8")
    atoms = get_atoms_from_any(str(path))
    assert len(atoms) == 1
    assert atoms[0][1] == "C"
    assert atoms[0][3] == (9.0, 8.0, 7.0)


def test_log_parser_accepts_last_zmatrix_orientation(tmp_path):
    path = tmp_path / "job.log"
    path.write_text(
        _log_orientation("Input orientation", [(1, 6, 0.0, 0.0, 0.0)]) +
        _log_orientation("Z-Matrix orientation", [(1, 6, 4.0, 5.0, 6.0)]),
        encoding="utf-8")
    atoms = get_atoms_from_any(str(path))
    assert atoms[0][3] == (4.0, 5.0, 6.0)


def test_gjf_parser_stops_at_coordinate_blank(tmp_path):
    path = tmp_path / "in.gjf"
    path.write_text(
        "%chk=in.chk\n"
        "#p hf/sto-3g\n\n"
        "title\n\n"
        "0 1\n"
        " C 0.0 0.0 0.0\n"
        " H 1.0 0.0 0.0\n\n"
        "--Link1--\n"
        "#p hf/sto-3g\n\n"
        "second\n\n"
        "0 1\n"
        " O 9.0 9.0 9.0\n\n",
        encoding="utf-8")
    atoms = get_atoms_from_any(str(path))
    assert [atom[1] for atom in atoms] == ["C", "H"]
    assert atoms[0][3] == (0.0, 0.0, 0.0)


def test_generated_complex_has_two_contiguous_fragment_blocks(tmp_path):
    atoms = [
        (1, "C", 6, (1.0, 1.0, 1.0)),
        (2, "N", 7, (2.0, 2.0, 2.0)),
        (3, "O", 8, (3.0, 3.0, 3.0)),
        (4, "H", 1, (4.0, 4.0, 4.0)),
    ]
    fragments = [
        {"atoms": {1, 3}, "charge": 0, "multiplicity": 1},
        {"atoms": {2, 4}, "charge": 0, "multiplicity": 1},
    ]
    jobs = local_jobs.prepare_ets_jobs(
        atoms, fragments, str(tmp_path), "complex", "m06l/def2svp", 0, 1)
    assert [job["role"] for job in jobs] == [
        "complex", "fragment1", "fragment2"]
    assert len({job["gjf"] for job in jobs}) == 3

    complex_text = open(jobs[0]["gjf"], encoding="ascii").read()
    fragment1_text = open(jobs[1]["gjf"], encoding="ascii").read()
    fragment2_text = open(jobs[2]["gjf"], encoding="ascii").read()
    assert complex_text.count("nosymm") == 1
    assert fragment1_text.count("nosymm") == 1
    assert fragment2_text.count("nosymm") == 1

    complex_coords = [line.split() for line in complex_text.splitlines()
                      if line.strip() and line.split()[0] in {"C", "N", "O", "H"}]
    assert [row[0] for row in complex_coords] == ["C", "O", "N", "H"]
    assert [row[1:4] for row in complex_coords[0:2]] == [
        ["1.00000000", "1.00000000", "1.00000000"],
        ["3.00000000", "3.00000000", "3.00000000"],
    ]
    assert [line.split()[0] for line in fragment1_text.splitlines()
            if line.strip() and line.split()[0] in {"C", "O"}] == ["C", "O"]
    assert [line.split()[0] for line in fragment2_text.splitlines()
            if line.strip() and line.split()[0] in {"N", "H"}] == ["N", "H"]


def test_run_ets_jobs_runs_three_jobs_then_formchk(tmp_path, monkeypatch):
    jobs = local_jobs.prepare_ets_jobs(
        [(1, "H", 1, (0.0, 0.0, 0.0)), (2, "H", 1, (1.0, 0.0, 0.0))],
        [{"atoms": {1}, "charge": 0, "multiplicity": 1},
         {"atoms": {2}, "charge": 0, "multiplicity": 1}],
        str(tmp_path), "complex", "hf/sto-3g", 0, 1)
    exe = tmp_path / "g16.exe"
    converter = tmp_path / "formchk.exe"
    exe.write_bytes(b"")
    converter.write_bytes(b"")
    called = []

    def fake_run(gjf, g16_exe, log_path=None, on_line=None, cancel=None):
        called.append(os.path.basename(gjf))
        with open(log_path, "w", encoding="utf-8") as fh:
            fh.write(" Normal termination of Gaussian 16\n")
        chk = os.path.splitext(gjf)[0] + ".chk"
        with open(chk, "wb") as fh:
            fh.write(b"checkpoint")
        return GaussianJobResult(True, log_path, 0)

    def fake_formchk(chk, formchk_exe=None, timeout=300, output_path=None):
        assert formchk_exe == str(converter)
        with open(output_path, "wb") as fh:
            fh.write(b"formatted")
        return output_path

    monkeypatch.setattr(local_jobs, "run_gaussian", fake_run)
    monkeypatch.setattr(local_jobs, "chk_to_fchk", fake_formchk)
    result = local_jobs.run_ets_jobs(jobs, str(exe), str(converter))
    assert called == [
        "complex_complex.gjf", "complex_fragment1.gjf",
        "complex_fragment2.gjf"]
    assert result["complex"].endswith("_complex.fch")
    assert result["frag1"].endswith("_fragment1.fch")
    assert result["frag2"].endswith("_fragment2.fch")
    assert all(os.path.isfile(result[k]) for k in ("complex", "frag1", "frag2"))
