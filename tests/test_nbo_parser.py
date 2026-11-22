# -*- coding: utf-8 -*-
"""Regression tests for Gaussian NBO parsing and visualization provenance."""

from molstudio.panels.nbo_parser import (
    build_nbo_visual_ref,
    parse_e2_section,
    parse_nbo_storage_order,
    parse_nbo_summary,
    resolve_nbo_visual_source,
)


def test_summary_parses_three_centre_and_scientific_values(tmp_path):
    log = tmp_path / "three_centre.log"
    log.write_text(
        "Natural Bond Orbitals (Summary):\n"
        " 3. 3C ( 1) C 1 - O 2 - N 3   1.99900E+00 -4.00000E-01\n"
        "\n"
        "Natural Population Analysis\n",
        encoding="utf-8",
    )

    parsed = parse_nbo_summary(str(log))

    assert parsed[3]["type"] == "3C"
    assert parsed[3]["atoms"] == [1, 2, 3]
    assert parsed[3]["atom_elems"] == ["C", "O", "N"]
    assert parsed[3]["occupancy"] == 1.999
    assert parsed[3]["energy"] == -0.4


def test_only_final_e2_pass_is_kept_and_units_are_tracked(tmp_path):
    log = tmp_path / "two_passes.log"
    log.write_text(
        "Second Order Perturbation Theory Analysis of Fock Matrix in NBO Basis\n"
        " within unit  1\n"
        "   1. BD (   1) C   1 - O   2 / 14. RY*(   1) C   1   1.35 1.41 0.039\n"
        "\n"
        "Second Order Perturbation Theory Analysis of Fock Matrix in NBO Basis\n"
        " within unit  2\n"
        "   5. BD (   1) O   5 - H   6 / 55. RY*(   3) H   7   0.59 2.04 0.031\n"
        " from unit  1 to unit  2\n"
        "   2. BD (   2) C   1 - O   2 / 40. RY*(   1) O   5   0.05 1.49 0.008\n"
        "\n"
        "Natural Bond Orbitals (Summary):\n",
        encoding="utf-8",
    )

    parsed = parse_e2_section(str(log))

    assert len(parsed) == 2
    assert parsed[0]["donor_unit"] == parsed[0]["acceptor_unit"] == 2
    assert parsed[1]["donor_unit"] == 1
    assert parsed[1]["acceptor_unit"] == 2


def test_storage_permutation_and_save_nbo_mapping(tmp_path):
    log = tmp_path / "pop_savenbo.log"
    log.write_text(
        " #p b3lyp/6-31g* pop=saveNBO\n"
        "Reordering of NBOs for storage:  7  8  3\n"
        " 1 2 4 6\n"
        "\n",
        encoding="utf-8",
    )
    fchk = tmp_path / "pop_savenbo.fchk"
    fchk.write_text("formatted checkpoint", encoding="utf-8")

    assert parse_nbo_storage_order(str(log)) == [7, 8, 3, 1, 2, 4, 6]
    source = resolve_nbo_visual_source(str(log), str(fchk))

    assert source["kind"] == "saveNBO"
    assert source["direct"] is True
    assert source["storage_map"][7] == 1


def test_storage_permutation_accepts_repeated_banner_lines(tmp_path):
    log = tmp_path / "save_multi.log"
    log.write_text(
        "pop=saveNBO\n"
        "Natural Bond Orbitals (Summary):\n"
        " 1. BD (   1) C   1 - C   2   1.99000  -0.50000\n"
        " 2. BD (   1) C   1 - H   3   1.99000  -0.60000\n"
        " 3. BD (   1) C   2 - H   4   1.99000  -0.70000\n"
        "Reordering of NBOs for storage:     2    3\n"
        "Reordering of NBOs for storage:     1\n"
        "\n",
        encoding="utf-8",
    )
    assert parse_nbo_storage_order(str(log)) == [2, 3, 1]


def test_nbo_plot_pair_has_priority_over_fchk(tmp_path):
    stem = tmp_path / "sample"
    log = tmp_path / "sample.log"
    log.write_text("pop=nbo\n", encoding="utf-8")
    fchk = tmp_path / "sample.fchk"
    fchk.write_text("formatted checkpoint", encoding="utf-8")
    (tmp_path / "sample.31").write_text("basis", encoding="utf-8")
    (tmp_path / "sample.37").write_text("orbitals", encoding="utf-8")

    source = resolve_nbo_visual_source(
        str(log), str(fchk), str(stem) + ".37")
    visual = build_nbo_visual_ref(source, 12)

    assert source["kind"] == "plot"
    assert source["direct"] is True
    assert visual["source"].endswith("sample.31")
    assert visual["orbital"] == "12"
    assert "NBO 12" in visual["display"]


def test_normal_fchk_is_marked_canonical_approximation(tmp_path):
    log = tmp_path / "ordinary.log"
    log.write_text("pop=nbo\n", encoding="utf-8")
    fchk = tmp_path / "ordinary.fchk"
    fchk.write_text("formatted checkpoint", encoding="utf-8")

    source = resolve_nbo_visual_source(str(log), str(fchk))

    assert source["kind"] == "canonical"
    assert source["direct"] is False


def test_canonical_fallback_keeps_legacy_double_click_renderable(tmp_path):
    log = tmp_path / "ordinary.log"
    log.write_text("pop=nbo\n", encoding="utf-8")
    fchk = tmp_path / "ordinary.fchk"
    fchk.write_text(
        "Alpha Orbital Energies                    R   N=           2\n"
        "  -0.80000000  -0.20000000\n",
        encoding="utf-8",
    )

    source = resolve_nbo_visual_source(str(log), str(fchk))
    visual = build_nbo_visual_ref(source, 7, energy=-0.18)

    assert visual["kind"] == "canonical"
    assert visual["renderable"] is True
    assert visual["mo_num"] == 2
    assert visual["display"] == "Alpha#2"


def test_save_nbo_without_reorder_banner_uses_energy_order(tmp_path):
    log = tmp_path / "save.log"
    log.write_text(
        "pop=saveNBO\n"
        "Natural Bond Orbitals (Summary):\n"
        " 1. BD (   1) C   1 - O   2   1.99900  -0.50000\n"
        " 2. LP (   1) O   2          1.99000  -1.00000\n",
        encoding="utf-8",
    )
    fchk = tmp_path / "save.fchk"
    fchk.write_text(
        "Alpha Orbital Energies                    R   N=           2\n"
        "  -1.00000000  -0.50000000\n",
        encoding="utf-8",
    )

    source = resolve_nbo_visual_source(str(log), str(fchk))

    assert source["kind"] == "saveNBO"
    assert source["storage_order"] == [2, 1]
    assert build_nbo_visual_ref(source, 2, energy=-1.0)["orbital"] == "1"
