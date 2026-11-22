# -*- coding: utf-8 -*-
"""原子自旋布居（Hirshfeld*）解析、输入序列与本机联调。"""

import os
import re
import sys

import pytest

from molstudio.core.spin_density import (
    build_spin_population_sequence,
    parse_spin_population_output,
    run_atomic_spin_population,
)
from molstudio.core.i18n import TR


_MW_EXE = r"E:\Multiwfn_2026.4.10_bin_Win64\Multiwfn.exe"
_LIVE_FCH = r"D:\OrbitalViewer 5.3\_dev\tmp\lmo_probe\triplet.fch"


SPIN_POP_TEXT = """\
 Total/Alpha/Beta electrons:     26.0000     14.0000     12.0000
   Atomic space        Value                % of sum            % of sum abs
     1(C )            0.02563871             1.281941             1.281941
     2(H )            0.00895332             0.447668             0.447668
     3(H )            0.00895332             0.447668             0.447668
     4(H )            0.02404576             1.202293             1.202293
     5(C )            0.23018592            11.509344            11.509344
     6(H )            0.11104560             5.552303             5.552303
     7(H )            0.11104560             5.552303             5.552303
     8(O )            0.99450575            49.725493            49.725493
     9(H )            0.48561774            24.280987            24.280987
 Summing up above values:          1.99999174
 Summing up absolute value of above values:          1.99999174
"""


MIXED_SIGN_TEXT = """\
 Total/Alpha/Beta electrons:     20.0000     10.0000     10.0000
   Atomic space        Value                % of sum            % of sum abs
     1(Fe)            1.20000000                0.000000            60.000000
     2(O )           -0.80000000                0.000000            40.000000
     3(H )            0.00000000                0.000000             0.000000
 Summing up above values:          0.40000000
 Summing up absolute value of above values:          2.00000000
"""


def test_spin_population_sequence():
    assert build_spin_population_sequence() == (
        "\n15\n-1\n3\n1\n5\n0\nq\n")


def test_parse_spin_population_positive_rows():
    result = parse_spin_population_output(SPIN_POP_TEXT)
    assert result["ok"] is True
    assert len(result["atoms"]) == 9
    assert result["expected_spin_population"] == pytest.approx(2.0)
    assert result["sum"] == pytest.approx(1.99999174)
    assert result["sum_abs"] == pytest.approx(1.99999174)
    assert result["integration_error"] == pytest.approx(-8.26e-6)
    assert result["atoms"][7] == {
        "index": 8, "element": "O", "value": 0.99450575,
        "abs_value": 0.99450575, "percent_sum": 49.725493,
        "percent_abs": 49.725493,
    }
    assert result["warnings"] == []


def test_parse_spin_population_keeps_sign_and_absolute_value():
    result = parse_spin_population_output(MIXED_SIGN_TEXT)
    assert result["atoms"][0]["value"] == pytest.approx(1.2)
    assert result["atoms"][1]["value"] == pytest.approx(-0.8)
    assert result["atoms"][1]["abs_value"] == pytest.approx(0.8)
    assert result["sum"] == pytest.approx(0.4)
    assert result["sum_abs"] == pytest.approx(2.0)


def test_parse_spin_population_empty_or_garbage_is_safe():
    for text in ("", "menu only\n", "forrtl: severe (59)"):
        result = parse_spin_population_output(text)
        assert result["ok"] is False
        assert result["atoms"] == []
        assert result["warnings"]


def test_run_atomic_spin_population_missing_inputs():
    with pytest.raises(RuntimeError, match="找不到 fchk"):
        run_atomic_spin_population(os.path.join("no_such", "x.fchk"),
                                   sys.executable)
    with pytest.raises(RuntimeError, match="找不到 Multiwfn"):
        run_atomic_spin_population(__file__, os.path.join(
            os.path.dirname(__file__), "missing.exe"))


def test_spin_population_ui_strings_have_english():
    keys = [key for key in TR if key.startswith("spin_pop_")]
    assert keys
    cjk = re.compile(r"[\u4e00-\u9fff]")
    for key in keys:
        english = TR[key].get("en", "")
        assert english, key
        assert not cjk.search(english), (key, english)


@pytest.mark.skipif(
    not os.path.exists(_MW_EXE) or not os.path.exists(_LIVE_FCH),
    reason="Multiwfn/open-shell sample unavailable")
def test_live_atomic_spin_population(tmp_path):
    result = run_atomic_spin_population(
        _LIVE_FCH, _MW_EXE, out_dir=str(tmp_path), timeout=120)
    assert result["ok"], result["error"]
    assert len(result["atoms"]) == 9
    assert result["sum"] == pytest.approx(2.0, abs=0.01)
    assert result["expected_spin_population"] == pytest.approx(2.0)
    assert (tmp_path / "triplet_spin_population.log").is_file()
