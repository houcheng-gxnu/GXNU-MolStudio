# -*- coding: utf-8 -*-
"""Unit tests for MolStudio's TDOS/PDOS/OPDOS workflow."""

import os

import numpy as np
import pytest

from molstudio.core import dos


def test_parse_orginfo_keeps_occupations_and_strengths(tmp_path):
    path = tmp_path / "orginfo.txt"
    path.write_text(
        "3 2\n"
        "-0.500000 2.000000 1.000000 0.050000\n"
        "not a data row\n"
        "0.100000 0.000000 1.000000 0.050000\n"
        "0.200000 0.000000 1.000000 0.050000\n",
        encoding="utf-8")
    levels = dos.parse_orginfo(str(path))
    assert len(levels) == 3
    assert levels[0].energy == pytest.approx(-0.5)
    assert levels[0].occupation == pytest.approx(2.0)
    assert levels[1].occupation == 0.0


@pytest.mark.parametrize("kind", ["gaussian", "lorentzian", "pseudo_voigt"])
def test_broadening_normalises_to_total_strength(kind):
    levels = [
        dos.OrbitalLevel(-0.2, 2.0, 1.0),
        dos.OrbitalLevel(0.1, 0.0, 3.0),
    ]
    x, y = dos.broaden_levels(
        levels, -20.0, 20.0, 0.05, broadening=kind, npts=40001)
    integral = np.trapezoid(y, x) if hasattr(np, "trapezoid") else np.trapz(y, x)
    assert integral == pytest.approx(4.0, rel=3e-3)


def test_tdos_sequence_exports_without_opening_plot_window():
    sequence = dos.build_multiwfn_dos_sequence(
        fwhm=0.3, unit="eV", broadening="lorentzian",
        spin="beta", emin=-7, emax=2, step=0.5, open_shell=True)
    assert sequence.startswith("\n10\n")
    assert "\n1\n2\n" in sequence
    assert (
        "\n8\n2\n-7,2,0.5\n3\n0.3\n6\n2\n0\n3\n"
        in sequence)
    scaled = dos.build_multiwfn_dos_sequence(
        fwhm=0.3, unit="eV", curve_scale=0.5)
    assert "\n3\n0.3\n4\n0.5\n" in scaled


def test_pdos_sequence_defines_atom_and_basis_fragments():
    fragments = [
        dos.DOSFragment("Fe", atoms="1-3", scope="atoms"),
        dos.DOSFragment("C pz proxy", atoms="4-9", scope="atom_basis",
                        angular_momentum="p"),
        dos.DOSFragment("all d", scope="all_basis",
                        angular_momentum="d"),
    ]
    sequence = dos.build_multiwfn_dos_sequence(
        fragments, method="mulliken", fwhm=0.05, open_shell=False)
    assert "\n7\n1\n-1\n1\na 1-3\nq\n2\ncond\n4-9\na\nP\nq\n" in sequence
    assert "\n3\nl d\nq\n0\n" in sequence
    assert sequence.endswith("\n0\n3\n0\n-10\nq\n\n")


def test_hirshfeld_rejects_basis_level_fragment():
    with pytest.raises(dos.DOSWorkflowError, match="只能按原子"):
        dos.build_multiwfn_dos_sequence(
            [dos.DOSFragment("all p", scope="all_basis",
                             angular_momentum="p")],
            method="hirshfeld")


def test_hirshfeld_atom_fragments_do_not_use_basis_submenu_quit():
    sequence = dos.build_multiwfn_dos_sequence(
        [dos.DOSFragment("left", atoms="1-3"),
         dos.DOSFragment("right", atoms="4-6")],
        method="hirshfeld", fwhm=0.05)
    assert "\n-1\n1\n1-3\n2\n4-6\n0\n" in sequence
    assert "\n1-3\nq\n2\n" not in sequence


def test_multiple_directional_basis_conditions_are_expanded():
    fragment = dos.DOSFragment(
        "Carbon S,Px,Py", atoms="1-3,7-8,12-16",
        scope="atom_basis", angular_momentum="s,px,py")
    sequence = dos.build_multiwfn_dos_sequence([fragment])
    assert (
        "\ncond\n1-3,7-8,12-16\na\nS\n"
        "cond\n1-3,7-8,12-16\na\nX\n"
        "cond\n1-3,7-8,12-16\na\nY\nq\n"
        in sequence)


def test_pz_uses_multiwfn_z_condition():
    fragment = dos.DOSFragment(
        "Carbon Pz", atoms="1-3,7-8,12-16",
        scope="atom_basis", angular_momentum="pz")
    sequence = dos.build_multiwfn_dos_sequence([fragment])
    assert "\ncond\n1-3,7-8,12-16\na\nZ\nq\n" in sequence


def test_diagnostics_identify_opdos_homo_centers(tmp_path):
    text = (
        "Formula: H3 B1 C1 O1 Total atoms: 6\n"
        "Total/Alpha/Beta electrons: 22.0000 11.0000 11.0000\n"
        "Center of TDOS: -0.242453 a.u.\n"
        "Center of PDOS  1: -0.260845 a.u.\n"
        "Column 1: Energy ( a.u.)\n"
        "Column 2: TDOS\n"
        "Column 3: OPDOS\n"
        "Column 4-13: PDOS of fragment 1-10\n"
        "Note: The vertical dash line corresponds to HOMO level at "
        "-0.33676 a.u.\n"
    )
    info = dos.parse_multiwfn_diagnostics(text)
    assert info["has_opdos"] is True
    assert info["formula"].startswith("H3 B1")
    assert info["centers"][0] == ("TDOS", pytest.approx(-0.242453))
    assert info["homo_values"][0][1] == pytest.approx(-0.33676)


def test_plot_and_csv_export(tmp_path):
    pytest.importorskip("matplotlib")
    result = dos.DOSResult(
        source_path="input.fchk",
        output_dir=str(tmp_path),
        unit="eV",
        fwhm=0.3,
        broadening="gaussian",
        spin="all",
        method="mulliken",
        fragments=["Fe", "ring"],
        energies=[-2.0, -1.0, 0.0, 1.0],
        curves={
            "TDOS": [0.0, 2.0, 1.0, 0.0],
            "Fe": [0.0, 1.0, 0.2, 0.0],
            "ring": [0.0, 1.0, 0.8, 0.0],
            "OPDOS": [0.0, -0.5, 0.4, 0.0],
        },
        line_energies=[-1.0, 0.0],
        line_heights=[1.0, 1.0],
        homo=-1.0,
        centers=[("Fe center", -0.8)],
        has_opdos=True,
    )
    image = tmp_path / "dos.png"
    csv_path = tmp_path / "dos.csv"
    dos.render_saved_dos(result, str(image), shift_homo=True)
    dos.export_dos_csv(result, str(csv_path), shift_homo=True)
    assert image.stat().st_size > 1000
    header = csv_path.read_text(encoding="utf-8").splitlines()[0]
    assert header.startswith("Energy_eV,TDOS,Fe,ring,OPDOS")
    assert csv_path.read_text(encoding="utf-8").splitlines()[1].startswith(
        "-1.000000")


def test_dos_source_formats_and_pdos_restriction(tmp_path):
    log_path = tmp_path / "job.log"
    log_path.write_text("Gaussian output placeholder", encoding="utf-8")
    assert dos.validate_dos_source(str(log_path)) == os.path.abspath(str(log_path))
    with pytest.raises(dos.DOSWorkflowError, match="只能导出 TDOS"):
        dos.validate_dos_source(
            str(log_path), [dos.DOSFragment("frag", atoms="1")])
