# -*- coding: utf-8 -*-
"""Regression tests for Multiwfn option-15 transition decomposition.

Reference: sobereva.com/224 sec. 2.1 and sec. 5.3.  Option 15 exports one
extra column per strong transition; column 2 stays the FULL total spectrum.
The critical invariant is that the black Total line must never be replaced
by the sum of the drawn contribution curves.
"""
import os
import shutil

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from molstudio.core import spectra  # noqa: E402


def test_option15_replaces_option2():
    plain = spectra.multiwfn_plot_sequence("uvvis")
    assert plain.endswith("\n2\n1\n")
    decomposed = spectra.multiwfn_plot_sequence(
        "uvvis", decompose_threshold=0.01)
    assert decomposed.endswith("\n15\n0.01\n1\n")
    assert "\n2\n1\n" not in decomposed


def test_threshold_must_be_strictly_positive():
    # Multiwfn treats 0 as "show the 10 largest contributions at an X" and
    # then asks for that X; sending it would shift every later command.
    for bad in (0, -0.1, "abc", object()):
        with pytest.raises(ValueError):
            spectra.multiwfn_plot_sequence("uvvis", decompose_threshold=bad)


def test_option15_coexists_with_fwhm_scale_and_xrange():
    seq = spectra.multiwfn_plot_sequence(
        "ir", fwhm=20, frequency_scale=0.9614,
        x_range="200,3800,200", decompose_threshold=0.05)
    items = seq.strip().split("\n")
    assert items.index("14") < items.index("8") < items.index("3")
    assert items[-3:] == ["15", "0.05", "1"]


def test_parse_decomposition_and_two_column_fallback(tmp_path):
    path = tmp_path / "spectrum_curve.txt"
    path.write_text(
        "100.0 10.0 1.0 2.0\n"
        "101.0 20.0 3.0 4.0\n"
        "102.0 5.0 0.5 0.6\n", encoding="utf-8")
    parsed = spectra.parse_spectrum_decomposition(str(path))
    assert parsed["x"] == [100.0, 101.0, 102.0]
    assert parsed["total"] == [10.0, 20.0, 5.0]
    assert parsed["columns"] == [[1.0, 3.0, 0.5], [2.0, 4.0, 0.6]]

    path.write_text("100.0 10.0\n101.0 20.0\n", encoding="utf-8")
    assert spectra.parse_spectrum_decomposition(str(path)) is None
    assert spectra.parse_spectrum_decomposition("") is None


def test_parse_transition_columns_from_multiwfn_stdout():
    text = (
        " The total spectrum and the contributions from    5 transitions\n"
        " Column 1: Wavelength (nm)\n"
        " Column 2: Molar absorption coefficient (L/mol/cm)\n"
        " Correspondence between the columns and individual transitions:\n"
        "      Column#   Transition#\n"
        "           3           2\n"
        "           4           3\n"
        "           5           5\n"
        "           6          11\n"
        "           7          13\n"
        "\n"
        " Discrete line data have been written to spectrum_line.txt\n")
    assert spectra.parse_transition_columns(text) == [2, 3, 5, 11, 13]
    assert spectra.parse_transition_columns("no table here") == []
    assert spectra.parse_transition_columns("") == []


def _render_decomp(tmp_path, curve, columns):
    pytest.importorskip("matplotlib")
    out = str(tmp_path / "decomp.png")
    decomp = {"x": [p[0] for p in curve], "columns": columns,
              "threshold": 0.01}
    spectra._render_curve(
        curve, spectra.get_spectrum_kind("uvvis"), out,
        transitions=[], decomposition=decomp)
    assert os.path.isfile(out)
    return out


def test_total_line_uses_column2_not_sum_of_parts(tmp_path):
    curve = [(100.0 + i, 10.0 + i) for i in range(21)]   # total peak = 30
    columns = [
        {"state": 2, "y": [1000.0] * 21},
        {"state": 3, "y": [2000.0] * 21},
    ]
    _render_decomp(tmp_path, curve, columns)
    assert spectra._LAST_RENDER_DECOMPOSITION == (2, 2)
    # If the renderer ever swapped in the sum, this would be 3000.
    assert spectra._LAST_RENDER_TOTAL_PEAK == pytest.approx(30.0)


def test_many_columns_keep_legend_bounded(tmp_path):
    curve = [(100.0 + i, float(i)) for i in range(21)]
    columns = [{"state": n, "y": [float(n)] * 21} for n in range(2, 14)]
    _render_decomp(tmp_path, curve, columns)
    assert spectra._LAST_RENDER_DECOMPOSITION == (12, 10)


def test_plain_render_reports_no_decomposition(tmp_path):
    pytest.importorskip("matplotlib")
    curve = [(100.0 + i, float(i)) for i in range(21)]
    spectra._render_curve(
        curve, spectra.get_spectrum_kind("uvvis"),
        str(tmp_path / "plain.png"), transitions=[])
    assert spectra._LAST_RENDER_DECOMPOSITION is None
    assert spectra._LAST_RENDER_TOTAL_PEAK == pytest.approx(20.0)


def test_spectrum_scratch_dir_stays_out_of_temp(tmp_path):
    work = tmp_path / "run"
    work.mkdir()
    scratch = spectra._spectrum_scratch_dir(str(work))
    try:
        assert os.path.isdir(scratch)
        assert os.path.dirname(scratch) == str(work)
        assert all(ord(ch) <= 127 for ch in scratch)
        with open(os.path.join(scratch, "probe.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write("ok")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


class _FakeProc:
    """Minimal stand-in so _run_multiwfn can finish without Multiwfn."""

    def __init__(self):
        self.stdout = iter([])
        self.stdin = self

    def write(self, _text):
        return 0

    def flush(self):
        return None

    def close(self):
        return None

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0


def _expected_flags():
    if __import__("sys").platform != "win32":
        return 0
    return (spectra.subprocess.CREATE_NO_WINDOW |
            spectra.subprocess.CREATE_NEW_PROCESS_GROUP)


def test_multiwfn_retries_plain_createprocess_after_winerror5(monkeypatch,
                                                             tmp_path):
    calls = []

    def fake_popen(_cmd, cwd, creationflags=0, **_kw):
        calls.append(creationflags)
        if len(calls) == 1:
            raise PermissionError(5, "拒绝访问")
        return _FakeProc()

    monkeypatch.setattr(spectra.subprocess, "Popen", fake_popen)
    text = spectra._run_multiwfn("mw.exe", str(tmp_path / "input.log"),
                                 "1\n", str(tmp_path))
    assert calls == [_expected_flags(), 0]
    assert text == ""


def test_multiwfn_permission_error_explains_whitelisting(monkeypatch,
                                                         tmp_path):
    def always_denied(*_args, **_kw):
        raise PermissionError(5, "拒绝访问")

    monkeypatch.setattr(spectra.subprocess, "Popen", always_denied)
    with pytest.raises(spectra.SpectrumWorkflowError) as info:
        spectra._run_multiwfn("mw.exe", str(tmp_path / "input.log"),
                              "1\n", str(tmp_path))
    message = str(info.value)
    assert "白名单" in message
    assert "Multiwfn" in message


def test_panel_exposes_decomposition_controls():
    from PyQt5.QtWidgets import QApplication  # noqa: E402
    from molstudio.panels import spectrum_panel as sp  # noqa: E402

    app = QApplication.instance() or QApplication([])
    assert app is not None
    panel = sp.SpectrumPanel()
    assert panel.chk_decompose.isChecked() is False
    assert panel.spin_decompose.value() == pytest.approx(0.01)
    assert panel.spin_decompose.isEnabled() is False
    panel.chk_decompose.setChecked(True)
    assert panel.spin_decompose.isEnabled() is True
    assert "decompose" in sp.TEXT["zh"]
    assert "decompose_status" in sp.TEXT["en"]
