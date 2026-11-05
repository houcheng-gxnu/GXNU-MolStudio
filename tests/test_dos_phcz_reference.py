# -*- coding: utf-8 -*-
"""PhCz regressions from sections 3.2.1 and 3.2.2 of sobereva.com/482."""

import os
import shutil
from pathlib import Path

import pytest

from molstudio.core import dos


PHCZ = Path(r"C:\Users\Administrator\Desktop\DOS-file\file\PhCz.fchk")
MULTIWFN = Path(r"E:\Multiwfn_2026.4.10_bin_Win64\Multiwfn.exe")


@pytest.mark.skipif(
    not PHCZ.is_file() or not MULTIWFN.is_file(),
    reason="PhCz acceptance input or local Multiwfn is unavailable")
def test_phcz_angular_momentum_case(tmp_path):
    source = tmp_path / "PhCz.fchk"
    shutil.copy2(str(PHCZ), str(source))
    result = dos.run_dos_pipeline(
        str(source),
        str(tmp_path),
        str(MULTIWFN),
        fwhm=dos.AU_TO_EV * 0.05,
        unit="eV",
        broadening="gaussian",
        spin="all",
        fragments=[
            dos.DOSFragment("s", scope="all_basis", angular_momentum="s"),
            dos.DOSFragment("p", scope="all_basis", angular_momentum="p"),
            dos.DOSFragment("d", scope="all_basis", angular_momentum="d"),
            dos.DOSFragment(
                "p(phenyl)", atoms="22-25,27,29", scope="atom_basis",
                angular_momentum="p"),
        ],
        method="mulliken",
        curve_scale=None,
        emin=-20,
        emax=2,
        step=3,
        show_opdos=False,
        flat_output=True,
        output_stem="PhCz_321_DOS",
    )

    assert result.plot_path == str(tmp_path / "PhCz_321_DOS.png")
    assert os.path.isfile(result.plot_path)
    assert list(result.curves) == [
        "TDOS", "s", "p", "d", "p(phenyl)", "OPDOS"]
    assert result.homo == pytest.approx(-5.3296266, abs=2e-5)
    assert result.lumo == pytest.approx(-0.6499310, abs=2e-5)
    expected_peaks = {
        "TDOS": 0.505995,
        "s": 0.192766,
        "p": 0.374420,
        "d": 0.006469,
        "p(phenyl)": 0.138075,
    }
    for name, peak in expected_peaks.items():
        assert max(result.curves[name]) == pytest.approx(peak, rel=3e-4)


@pytest.mark.skipif(
    not PHCZ.is_file() or not MULTIWFN.is_file(),
    reason="PhCz acceptance input or local Multiwfn is unavailable")
def test_phcz_hirshfeld_fragment_case(tmp_path):
    source = tmp_path / "PhCz.fchk"
    shutil.copy2(str(PHCZ), str(source))
    result = dos.run_dos_pipeline(
        str(source),
        str(tmp_path),
        str(MULTIWFN),
        fwhm=0.05,
        unit="a.u.",
        broadening="gaussian",
        spin="all",
        fragments=[
            dos.DOSFragment("Phenyl", atoms="22-32"),
            dos.DOSFragment("Nitrogen", atoms="21"),
            dos.DOSFragment("Other atoms", atoms="1-20"),
        ],
        method="hirshfeld",
        curve_scale=None,
        emin=-0.8,
        emax=0.2,
        step=0.1,
        show_opdos=False,
        flat_output=True,
        output_stem="PhCz_322_DOS",
    )

    assert result.plot_path == str(tmp_path / "PhCz_322_DOS.png")
    assert os.path.isfile(result.plot_path)
    assert list(result.curves) == [
        "TDOS", "Phenyl", "Nitrogen", "Other atoms"]
    assert result.has_opdos is False
    assert result.homo == pytest.approx(-0.1958602, abs=2e-5)
    assert result.lumo == pytest.approx(-0.0238845, abs=2e-5)
    expected_peaks = {
        "TDOS": 15.438992,
        "Phenyl": 6.447280,
        "Nitrogen": 0.586838,
        "Other atoms": 9.396628,
    }
    for name, peak in expected_peaks.items():
        assert max(result.curves[name]) == pytest.approx(peak, rel=3e-4)
