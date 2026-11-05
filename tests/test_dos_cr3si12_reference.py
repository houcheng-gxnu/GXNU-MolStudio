# -*- coding: utf-8 -*-
"""Open-shell Cr3Si12- regression from sobereva.com/482 section 3.3."""

import shutil
from pathlib import Path

import pytest

from molstudio.core import dos


CLUSTER = Path(r"C:\Users\Administrator\Desktop\DOS-file\file\Cr3Si12-.fchk")
MULTIWFN = Path(r"E:\Multiwfn_2026.4.10_bin_Win64\Multiwfn.exe")


def _run(source, tmp_path, spin):
    result = dos.run_dos_pipeline(
        str(source),
        str(tmp_path),
        str(MULTIWFN),
        fwhm=0.3,
        unit="eV",
        broadening="gaussian",
        spin=spin,
        fragments=[dos.DOSFragment("Cr3", atoms="1,2,15")],
        method="becke",
        curve_scale=0.5,
        emin=-7,
        emax=2,
        step=1,
        show_opdos=False,
        show_centers=False,
        flat_output=True,
        output_stem="Cr3Si12_%s_DOS" % spin,
    )
    return result


@pytest.mark.skipif(
    not CLUSTER.is_file() or not MULTIWFN.is_file(),
    reason="Cr3Si12- acceptance input or local Multiwfn is unavailable")
def test_cr3si12_alpha_beta_and_combined_spins(tmp_path):
    source = tmp_path / "Cr3Si12-.fchk"
    shutil.copy2(str(CLUSTER), str(source))
    assert dos.detect_open_shell(str(source)) is True

    alpha = _run(source, tmp_path, "alpha")
    beta = _run(source, tmp_path, "beta")
    both = _run(source, tmp_path, "all")

    assert alpha.curves["TDOS"] != beta.curves["TDOS"]
    assert alpha.homo == pytest.approx(-0.7732404, abs=2e-5)
    assert beta.homo == pytest.approx(-1.6026325, abs=2e-5)
    assert alpha.homo > beta.homo
    assert max(alpha.curves["TDOS"]) == pytest.approx(0.424834, rel=3e-4)
    assert max(beta.curves["TDOS"]) == pytest.approx(0.387987, rel=3e-4)
    assert max(alpha.curves["Cr3"]) == pytest.approx(0.134924, rel=3e-4)
    assert max(beta.curves["Cr3"]) == pytest.approx(0.135489, rel=3e-4)
    assert alpha.d_band_centers[0]["center"] == pytest.approx(
        -1.563171, abs=3e-5)
    assert alpha.d_band_centers[0]["relative"] == pytest.approx(
        -0.789931, abs=3e-5)
    assert beta.d_band_centers[0]["center"] == pytest.approx(
        -0.432017, abs=3e-5)
    assert beta.d_band_centers[0]["relative"] == pytest.approx(
        1.170616, abs=3e-5)
    assert both.diagnostics["mirrored_spins"] is True
    assert max(both.curves["α TDOS"]) == pytest.approx(0.424834, rel=3e-4)
    assert min(both.curves["β TDOS"]) == pytest.approx(-0.387987, rel=3e-4)
    assert max(both.curves["α Cr3"]) == pytest.approx(0.134924, rel=3e-4)
    assert min(both.curves["β Cr3"]) == pytest.approx(-0.135489, rel=3e-4)
    assert both.diagnostics["beta_homo"] == pytest.approx(
        -1.6026325, abs=2e-5)
    assert len(both.d_band_centers) == 2
    assert both.d_band_centers[0]["spin"] == "alpha"
    assert both.d_band_centers[1]["spin"] == "beta"
    assert (tmp_path / "Cr3Si12_alpha_DOS.png").is_file()
    assert (tmp_path / "Cr3Si12_beta_DOS.png").is_file()
    assert (tmp_path / "Cr3Si12_all_DOS.png").is_file()
    assert list(both.curves) == ["α TDOS", "α Cr3", "β TDOS", "β Cr3"]
