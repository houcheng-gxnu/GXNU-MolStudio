# -*- coding: utf-8 -*-
"""Tests for the Gaussian NBO input generator."""

from molstudio.core.nbo_input import (
    build_nbo_input,
    inspect_nbo_source,
    parse_route_for_reuse,
)


LOG = """\
 %nprocshared=6
 %mem=12GB
 %chk=old.chk
 ----------------------------------------------------------------------
 #p opt freq m06l/def2svp geom=connectivity int=ultrafin
 e pop=NBO
 ----------------------------------------------------------------------
 Charge =  0 Multiplicity = 1
 Standard orientation:
 ---------------------------------------------------------------------
 Center     Atomic      Atomic             Coordinates (Angstroms)
 Number     Number       Type             X           Y           Z
 ---------------------------------------------------------------------
      1          8           0        0.000000    0.000000    0.100000
      2          1           0        0.000000    0.750000   -0.500000
      3          1           0        0.000000   -0.750000   -0.500000
 ---------------------------------------------------------------------
 Normal termination of Gaussian
"""


def _write_log(tmp_path):
    path = tmp_path / "water.log"
    path.write_text(LOG, encoding="utf-8")
    return path


def test_route_reuse_repairs_gaussian_line_wrap(tmp_path):
    path = _write_log(tmp_path)
    route = parse_route_for_reuse(str(path))
    assert "int=ultrafine" in route
    assert "int=ultrafin e" not in route


def test_plot_input_uses_final_geometry_and_original_route(tmp_path):
    log = _write_log(tmp_path)
    text, meta = build_nbo_input(
        str(log), output_stem="water_nbo", mode="plot")

    assert "#p m06l/def2svp int=ultrafine pop=nboread" in text
    assert "geom=connectivity" not in text
    assert "freq" not in text.lower()
    assert "%nprocshared=6" in text
    assert "%mem=12GB" in text
    assert "0 1" in text
    assert "$NBO plot file=water_nbo $END" in text
    assert text.rstrip().endswith("$NBO plot file=water_nbo $END")
    assert meta["symbols"] == ["O", "H", "H"]
    assert meta["charge"] == 0 and meta["multiplicity"] == 1


def test_save_nbo_mode_has_no_plot_footer(tmp_path):
    log = _write_log(tmp_path)
    text, meta = build_nbo_input(
        str(log), output_stem="water_store", mode="saveNBO")

    assert "pop=saveNBO" in text
    assert "$NBO" not in text
    assert meta["plot_base"] == ""
    assert "%chk=water_store.chk" in text


def test_default_title_follows_output_mode(tmp_path):
    """saveNBO 的输入不该在标题里自称 "NBO plot"。"""
    log = _write_log(tmp_path)
    plot_text, _ = build_nbo_input(
        str(log), output_stem="water", mode="plot")
    save_text, _ = build_nbo_input(
        str(log), output_stem="water", mode="saveNBO")

    assert "water NBO plot" in plot_text.splitlines()
    assert "water saveNBO" in save_text.splitlines()
    assert "water NBO plot" not in save_text.splitlines()


def test_overrides_charge_multiplicity_and_resources(tmp_path):
    log = _write_log(tmp_path)
    text, meta = build_nbo_input(
        str(log), output_stem="ion", mode="plot", charge=-1,
        multiplicity=2, nproc=4, mem_gb=8)

    assert "-1 2" in text
    assert "%nprocshared=4" in text
    assert "%mem=8GB" in text
    assert meta["charge"] == -1 and meta["multiplicity"] == 2


def test_source_metadata_is_available_to_ui(tmp_path):
    log = _write_log(tmp_path)
    info = inspect_nbo_source(str(log))
    assert info["route"].endswith("pop=NBO")
    assert info["nproc"] == 6
    assert info["mem_gb"] == 12


def test_generator_can_start_directly_from_gjf(tmp_path):
    gjf = tmp_path / "input.gjf"
    gjf.write_text(
        "%nprocshared=4\n"
        "%mem=6GB\n"
        "#p b3lyp/def2svp opt freq pop=nbo\n"
        "\n"
        "water\n"
        "\n"
        "-1 2\n"
        "O 0.0 0.0 0.1\n"
        "H 0.0 0.75 -0.5\n"
        "H 0.0 -0.75 -0.5\n"
        "\n",
        encoding="utf-8",
    )

    text, meta = build_nbo_input(
        str(gjf), output_stem="from_gjf", mode="plot")

    assert "#p b3lyp/def2svp pop=nboread" in text
    assert "opt" not in text.splitlines()[3].lower()
    assert "-1 2" in text
    assert "%nprocshared=4" in text and "%mem=6GB" in text
    assert "$NBO plot file=from_gjf $END" in text
    assert meta["symbols"] == ["O", "H", "H"]
