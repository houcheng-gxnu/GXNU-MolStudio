# -*- coding: utf-8 -*-
"""Regression for the Ferrocene DOS tutorial used as the UI acceptance case."""

import os
import shutil
from pathlib import Path

import pytest

from molstudio.core import dos


FERROCENE = Path(r"C:\Users\Administrator\Desktop\DOS-file\file\Ferrocene.fch")
MULTIWFN = Path(r"E:\Multiwfn_2026.4.10_bin_Win64\Multiwfn.exe")


@pytest.mark.skipif(
    not FERROCENE.is_file() or not MULTIWFN.is_file(),
    reason="Ferrocene acceptance input or local Multiwfn is unavailable")
def test_ferrocene_tutorial_curves_and_same_folder_output(tmp_path):
    source = tmp_path / "Ferrocene.fch"
    shutil.copy2(str(FERROCENE), str(source))
    carbons = "1-3,7-8,12-16"
    result = dos.run_dos_pipeline(
        str(source),
        str(source.parent),
        str(MULTIWFN),
        fwhm=0.03,
        unit="a.u.",
        broadening="gaussian",
        spin="all",
        fragments=[
            dos.DOSFragment("Fe", atoms="6"),
            dos.DOSFragment(
                "Carbon Pz", atoms=carbons, scope="atom_basis",
                angular_momentum="pz"),
            dos.DOSFragment(
                "Carbon S,Px,Py", atoms=carbons, scope="atom_basis",
                angular_momentum="s,px,py"),
        ],
        method="mulliken",
        curve_scale=0.05,
        flat_output=True,
    )

    assert result.output_dir == str(tmp_path)
    assert result.plot_path == str(tmp_path / "Ferrocene_DOS.png")
    assert os.path.isfile(result.plot_path)
    assert os.path.isfile(str(tmp_path / "Ferrocene_DOS.csv")) is False
    assert list(result.curves) == [
        "TDOS", "Fe", "Carbon Pz", "Carbon S,Px,Py", "OPDOS"]
    assert result.has_opdos is True
    assert result.energy_range[0] == pytest.approx(-0.60)
    assert result.energy_range[1] == pytest.approx(0.10)
    assert result.energy_range[2] == pytest.approx(0.07)
    assert result.homo == pytest.approx(-0.150462, abs=2e-5)
    assert result.lumo == pytest.approx(-0.041529, abs=2e-5)
    assert max(result.curves["TDOS"]) == pytest.approx(10.1139, rel=2e-4)
    assert max(result.curves["Fe"]) == pytest.approx(4.68546, rel=2e-4)
    assert max(result.curves["Carbon Pz"]) == pytest.approx(5.02508, rel=2e-4)
    assert max(result.curves["Carbon S,Px,Py"]) == pytest.approx(
        5.96740, rel=2e-4)
