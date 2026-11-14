# -*- coding: utf-8 -*-
"""ORCA 本机模块单元测试（不依赖本机 ORCA 可执行文件）。"""

import os

import pytest

from molstudio.core import orca_run as O

SAMPLE = """
! B3LYP def2-SVP

%pal nprocs 4 end

%maxcore 2000

FINAL SINGLE POINT ENERGY      -76.320286403201
----------------
ORBITAL ENERGIES
----------------
  NO   OCC          E(Eh)            E(eV)
   0   2.0000     -19.1300000000    -520.5550
   1   2.0000      -1.0000000000     -27.2114
   2   2.0000      -0.5000000000     -13.6057
   3   2.0000      -0.4000000000     -10.8845
   4   0.0000       0.0500000000       1.3606
   5   0.0000       0.1000000000       2.7211
----------------
MULLIKEN ATOMIC CHARGES
----------------
   0 O :     -0.500000
   1 H :      0.250000
   2 H :      0.250000
Sum of atomic charges:      0.000000
----------------
CARTESIAN COORDINATES (ANGSTROEM)
---------------------------------
  O      0.000000000000     0.000000000000     0.062600000000
  H     -0.792000000000     0.000000000000    -0.497300000000
  H      0.792000000000     0.000000000000    -0.497300000000

FINAL SINGLE POINT ENERGY      -76.320286403201
TOTAL RUN TIME: 0 days 0 hours 0 minutes 1 seconds 263 msec
****ORCA TERMINATED NORMALLY****
"""

TS_SAMPLE = """
! r2SCAN-3c OptTS Freq

%geom
  Calc_Hess true
end

CARTESIAN COORDINATES (ANGSTROEM)
---------------------------------
  O      0.000000000000     0.000000000000     0.062600000000

VIBRATIONAL FREQUENCIES
-----------------------

Scaling factor for frequencies =  1.000000000  (already applied!)

   0:       0.00 cm**-1
   1:       0.00 cm**-1
   6:    -189.59 cm**-1  ***imaginary mode***
   7:     277.42 cm**-1
   8:     300.00 cm**-1

****ORCA TERMINATED NORMALLY****
"""


def test_build_input_sp():
    text = O.build_input(
        ["O", "H", "H"],
        [[0, 0, 0.0626], [-0.792, 0, -0.4973], [0.792, 0, -0.4973]],
        method="B3LYP", basis="def2-SVP", task="sp",
        nprocs=4, maxcore=2000)
    assert "! B3LYP def2-SVP" in text
    assert "%pal nprocs 4 end" in text
    assert "%maxcore 2000" in text
    assert "* xyz 0 1" in text
    assert "O " in text and "*" in text
    assert "Opt" not in text.split("*")[0]


def test_build_input_ts_adds_hess():
    text = O.build_input(
        ["C", "H"], [[0, 0, 0], [1, 0, 0]], task="ts_freq",
        method="B3LYP", basis="def2-SVP", nprocs=4)
    assert "OptTS Freq" in text
    assert "%geom" in text
    assert "Calc_Hess true" in text
    assert "%pal nprocs 4 end" in text


def test_build_input_solvent_and_dispersion():
    text = O.build_input(
        ["C"], [[0, 0, 0]], task="opt", solvent="water",
        solvent_model="cpcm", dispersion="D3BJ")
    assert "CPCM(water)" in text
    assert "D3BJ" in text
    assert "Opt" in text
    smd = O.build_input(["C"], [[0, 0, 0]], solvent="water",
                        solvent_model="smd")
    assert '%cpcm smd true smdsolvent "water" end' in smd
    assert "CPCM(" not in smd


def test_build_input_td():
    text = O.build_input(["C"], [[0, 0, 0]], task="td", td_nroots=15)
    assert "TDDFT" in text
    assert "%tddft" in text and "NRoots 15" in text


def test_build_input_validation():
    with pytest.raises(O.OrcaError):
        O.build_input([], [], task="sp")
    with pytest.raises(O.OrcaError):
        O.build_input(["C"], [], task="sp")
    with pytest.raises(O.OrcaError):
        O.build_input(["C"], [[0, 0, 0]], charge="x")
    with pytest.raises(O.OrcaError):
        O.build_input(["C"], [[0, 0, 0]], nprocs=0)
    with pytest.raises(O.OrcaError):
        O.build_input(["C"], [[0, 0, 0]], task="nonsense")


def test_prepare_job_writes_input(tmp_path):
    prepared = O.prepare_job(
        str(tmp_path), "water job", ["O", "H"], [[0, 0, 0], [1, 0, 0]],
        task="sp", nprocs=4, orca_exe="")
    assert prepared.inp_path.endswith("water_job.inp")
    assert os.path.isfile(prepared.inp_path)
    text = open(prepared.inp_path, encoding="utf-8").read()
    assert text == prepared.input_text
    assert prepared.command_str


def test_parse_energy_geometry_orbitals_charges():
    parsed = O.parse_output(SAMPLE)
    assert parsed["terminated_normally"] is True
    assert parsed["final_energy"] == pytest.approx(-76.320286403201)
    assert parsed["homo"]["index"] == 3
    assert parsed["lumo"]["index"] == 4
    assert parsed["homo_lumo_gap_ev"] == pytest.approx(12.2451)
    assert len(parsed["geometry"]) == 3
    assert parsed["symbols"] == ["O", "H", "H"]
    assert len(parsed["charges"]) == 3
    assert parsed["charges_type"] == "Mulliken"
    assert parsed["charges"][0]["charge"] == pytest.approx(-0.5)
    assert "0 days" in parsed["run_time_text"]


def test_parse_frequencies_and_imaginary():
    parsed = O.parse_output(TS_SAMPLE)
    assert parsed["imaginary"] == [pytest.approx(-189.59)]
    assert len(parsed["frequencies"]) == 3
    assert len(parsed["all_frequencies"]) == 5
    assert parsed["opt_converged"] is False  # 没有 HURRAY 行
    assert parsed["terminated_normally"] is True


def test_parse_empty():
    parsed = O.parse_output("")
    assert parsed["final_energy"] is None
    assert parsed["terminated_normally"] is False
    assert parsed["frequencies"] == []


def test_find_orca_exe_hint(tmp_path):
    fake = tmp_path / "orca.exe"
    fake.write_bytes(b"")
    assert O.find_orca_exe(str(fake)) == str(fake)
    found = O.find_orca_exe(str(tmp_path / "missing.exe"))
    assert found == "" or os.path.isfile(found)


def test_convert_gbw_missing_raises(tmp_path):
    with pytest.raises(O.OrcaError):
        O.convert_gbw(str(tmp_path / "missing.gbw"))


def test_molden_to_fchk_missing_raises(tmp_path):
    with pytest.raises(O.OrcaError):
        O.molden_to_fchk(str(tmp_path / "missing.molden.input"))
