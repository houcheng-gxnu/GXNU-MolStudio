# -*- coding: utf-8 -*-

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from molstudio.core import spectra


WATER = [
    (1, "O", 8, (0.0, 0.0, 0.0)),
    (2, "H", 1, (0.0, 0.0, 0.96)),
    (3, "H", 1, (0.93, 0.0, -0.24)),
]


def test_routes_match_spectrum_keywords():
    assert spectra.build_gaussian_route(
        "uvvis", "PBE0/def2SVP", nstates=25) == (
            "#P PBE0/def2SVP TD=(NStates=25)")
    assert spectra.build_gaussian_route(
        "ecd", "PBE0/def2TZVP", nstates=30,
        solvent="Water") == (
            "#P PBE0/def2TZVP TD=(NStates=30) SCRF=(Solvent=Water)")
    assert spectra.build_gaussian_route(
        "ir", "B3LYP/6-31G(d)") == "#P B3LYP/6-31G(d) Opt freq"
    assert spectra.build_gaussian_route(
        "raman", "B3LYP/6-31G(d)", optimize=False) == (
            "#P B3LYP/6-31G(d) freq=raman")
    assert spectra.build_gaussian_route(
        "vcd", "B3LYP/6-31G(d)") == "#P B3LYP/6-31G(d) Opt freq=VCD"
    assert spectra.build_gaussian_route(
        "roa", "B3LYP/aug-cc-pVDZ", optimize=False) == (
            "#P B3LYP/aug-cc-pVDZ freq=ROA")
    assert spectra.build_gaussian_route(
        "fluorescence", "B3LYP/6-31G(d)", job_kind="excited_opt",
        nstates=5) == (
            "#P B3LYP/6-31G(d) TD=(NStates=5,Root=1) "
            "Opt=(MaxCycles=100)")
    assert spectra.build_gaussian_route(
        "phosphorescence", "B3LYP/6-31G(d)", job_kind="triplet_opt") == (
            "#P B3LYP/6-31G(d) Opt=(MaxCycles=100)")
    assert spectra.build_gaussian_route(
        "phosphorescence", "B3LYP/6-31G(d)", job_kind="triplet_td",
        nstates=5) == (
            "#P B3LYP/6-31G(d) TD=(NStates=5,Triplet)")
    assert spectra.build_gaussian_route(
        "phosphorescence", "B3LYP/6-31G(d)",
        job_kind="reference_stable") == (
            "#P B3LYP/6-31G(d) Stable=Opt")


def test_electronic_workflow_uses_optimised_checkpoint(tmp_path):
    jobs = spectra.prepare_spectrum_jobs(
        WATER, str(tmp_path), "water.xyz", "uvvis",
        "PBE0/def2SVP", nstates=20, optimize=True)
    assert [job["role"] for job in jobs] == ["opt", "spectrum"]

    opt_text = open(jobs[0]["gjf"], encoding="ascii").read()
    spectrum_text = open(jobs[1]["gjf"], encoding="ascii").read()
    assert "#P PBE0/def2SVP Opt" in opt_text
    assert "%chk=water_uvvis_opt.chk" in spectrum_text
    assert "TD=(NStates=20) Geom=Check Guess=Read" in spectrum_text
    assert " O " in opt_text
    assert " O " not in spectrum_text
    # Gaussian requires a true blank line after a molecule specification.
    assert opt_text.endswith("\n\n")
    assert spectrum_text.endswith("\n\n")


def test_roa_wavelengths_are_written_in_input(tmp_path):
    jobs = spectra.prepare_spectrum_jobs(
        WATER, str(tmp_path), "water.xyz", "roa",
        "B3LYP/aug-cc-pVDZ", optimize=False,
        wavelengths="450nm, 532 600nm")
    text = open(jobs[0]["gjf"], encoding="ascii").read()
    assert "freq=ROA" in text
    assert "450nm 532nm 600nm" in text


def test_multiwfn_sequence_has_startup_blank_and_menu_paths():
    uv = spectra.multiwfn_plot_sequence(
        "uvvis", fwhm="0.35", x_range="100,300,20")
    assert uv.startswith("\n11\n3\n")
    assert "\n8\n0.35\n" in uv
    assert "\n3\n100,300,20\n2\n" in uv

    ecd = spectra.multiwfn_plot_sequence("ecd")
    assert ecd.startswith("\n11\n4\n2\n")

    ir = spectra.multiwfn_plot_sequence(
        "ir", fwhm="20", frequency_scale=0.9614)
    assert "\n14\n\n0.9614\n" in ir
    assert "\n8\n20\n2\n" in ir

    roa = spectra.multiwfn_plot_sequence(
        "roa", roa_wavelengths="450nm 532nm 600nm",
        roa_wavelength_index=2)
    assert roa.startswith("\n11\n6\n2\n2\n")
    fluorescence = spectra.multiwfn_plot_sequence(
        "fluorescence", nstates=5)
    assert fluorescence.startswith("\n11\n3\n20\n2-5\n0\n2\n1\n")


def test_roa_always_sends_wavelength_index():
    # Multiwfn 无条件询问 "Load data for which frequency?"，即使只有一个波长。
    # 以前单波长时省略序号，后续命令整体错位并触发 EOF 崩溃。
    one = spectra.multiwfn_plot_sequence("roa", roa_wavelengths="532nm")
    assert one.startswith("\n11\n6\n1\n2\n")
    # 文章 5.6 节示例：输出文件含 600/532/500 nm，选 532nm 应落在第 2 项。
    matched = spectra.multiwfn_plot_sequence(
        "roa", roa_wavelengths="532nm",
        available_wavelengths=[600.0, 532.0, 500.0])
    assert matched.startswith("\n11\n6\n2\n2\n")


def test_parse_roa_wavelengths_reads_gaussian_output(tmp_path):
    path = tmp_path / "roa.out"
    path.write_text(
        " Incident light (cm**-1):   16666.67  18796.99  20000.00\n"
        " Alpha(-w;w) w=  600.0nm:\n"
        " Alpha(-w;w) w=  532.0nm:\n"
        " Alpha(-w;w) w=  500.0nm:\n"
        " Alpha(-w;w) w=  600.0nm:\n",
        encoding="utf-8")
    assert spectra.parse_roa_wavelengths(str(path)) == [600.0, 532.0, 500.0]
    fallback = tmp_path / "fallback.out"
    fallback.write_text(
        " Incident light (cm**-1):   16666.67  18796.99  20000.00\n",
        encoding="utf-8")
    assert spectra.parse_roa_wavelengths(str(fallback))[1] == \
        pytest.approx(532.0, abs=0.01)


def test_parse_curve_accepts_fortran_exponents(tmp_path):
    path = tmp_path / "spectrum_curve.txt"
    path.write_text(
        "Wavelength Molar absorption\n"
        "200.0 1.0D+03\n"
        "not a numeric row\n"
        "250.5 5.5\n",
        encoding="utf-8")
    assert spectra.parse_spectrum_curve(str(path)) == [
        (200.0, 1000.0), (250.5, 5.5)]


def test_parse_discrete_lines_collapses_each_three_point_bar(tmp_path):
    path = tmp_path / "spectrum_line.txt"
    path.write_text(
        "200.0 0.0\n200.0 0.25\n200.0 0.0\n"
        "250.0 0.0\n250.0 -0.5\n250.0 0.0\n",
        encoding="utf-8")
    assert spectra.parse_spectrum_lines(str(path)) == [
        (200.0, 0.25), (250.0, -0.5)]


def test_parse_first_triplet_excitation_and_transition_file(tmp_path):
    log = tmp_path / "t1_td.log"
    log.write_text(
        "Excited State   1:      Triplet-A      1.9000 eV  652.50 nm  "
        "f=0.0000  <S**2>=2.000\n"
        "Excited State   1:      Triplet-A      1.8750 eV  661.20 nm  "
        "f=0.0000  <S**2>=2.000\n",
        encoding="utf-8")
    excited = spectra.parse_first_excitation(
        str(log), triplet_only=True)
    assert excited["ev"] == 1.875
    assert excited["nm"] == 661.2
    target = tmp_path / "phosphorescence_transitions.txt"
    spectra.write_transition_file([(excited["ev"], 1.0)], str(target))
    lines = target.read_text(encoding="ascii").splitlines()
    assert lines[0] == "1 1"
    assert [float(value) for value in lines[1].split()] == [1.875, 1.0]


def test_invalid_roa_without_wavelength_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="入射波长"):
        spectra.prepare_spectrum_jobs(
            WATER, str(tmp_path), "water.xyz", "roa",
            "B3LYP/aug-cc-pVDZ", optimize=False)


def test_existing_log_replot_uses_unique_output_directories(
        tmp_path, monkeypatch):
    log_path = tmp_path / "sample.log"
    log_path.write_text("Gaussian output placeholder", encoding="utf-8")

    def fake_draw(*_args, **_kwargs):
        return {"plot_path": str(tmp_path / "plot.png"), "curve": []}

    monkeypatch.setattr(spectra, "draw_multiwfn_spectrum", fake_draw)
    out_parent = tmp_path / "results"
    common = dict(
        atoms=WATER, source_name="sample.log", output_dir=str(out_parent),
        kind_key="uvvis", theory="PBE0/def2SVP", gaussian_exe="",
        multiwfn_exe="Multiwfn.exe", existing_log=str(log_path))
    first = spectra.run_spectrum_pipeline(**common)
    second = spectra.run_spectrum_pipeline(**common)
    assert first["output_dir"] != second["output_dir"]
    assert os.path.isdir(first["output_dir"])
    assert os.path.isdir(second["output_dir"])


def test_emission_chain_builds_sequential_geometry_jobs(tmp_path, monkeypatch):
    orientation = """\
 Standard orientation:
 ---------------------------------------------------------------------
 Center     Atomic      Atomic             Coordinates (Angstroms)
 Number     Number       Type             X           Y           Z
 ---------------------------------------------------------------------
      1          8           0        0.000000    0.000000    0.000000
      2          1           0        0.000000    0.000000    0.960000
      3          1           0        0.930000    0.000000   -0.240000
 ---------------------------------------------------------------------
"""

    def fake_run(gjf_path, *_args, **_kwargs):
        log_path = os.path.splitext(gjf_path)[0] + ".log"
        Path(log_path).write_text(
            orientation +
            ("Excited State   1:      Triplet-A      1.8750 eV  "
             "661.20 nm  f=0.0000  <S**2>=2.000\n"
             if gjf_path.endswith("t1_td.gjf") else ""),
            encoding="utf-8")
        return SimpleNamespace(
            ok=True, cancelled=False, error="", log_path=log_path)

    monkeypatch.setattr(spectra, "run_gaussian", fake_run)
    final_log, jobs, emission = spectra._run_emission_chain(
        WATER, "water.xyz", str(tmp_path), "phosphorescence",
        "B3LYP/6-31G(d)", "g16.exe", 0, 1, 3, 1, "1GB", True, "",
        lambda: False, lambda *_args: None, lambda *_args: None, lambda: False)
    assert [job["role"] for job in jobs] == [
        "ground_opt", "t1_opt", "t1_s0_ref", "t1_td"]
    assert emission["ev"] == 1.875
    t1_td = Path(final_log).with_suffix(".gjf").read_text(encoding="ascii")
    assert "TD=(NStates=3,Triplet) Geom=Check Guess=Read" in t1_td
    assert "%chk=water_phosphorescence_t1_s0_ref.chk" in t1_td
