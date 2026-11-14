# -*- coding: utf-8 -*-
"""DI 本机一键计算弹窗 + 面板联动回归测试（不真跑 Gaussian）。

覆盖链路：弹窗载入过渡态 log → Shift 框选信号分片段 → 生成 4 个 gjf
（参数沿用 TS route）→ 后台运行（假 run_gaussian）→ 关闭弹窗后主 DI 页
自动载入 5 个 log、计算能量分解并出图。

    pytest tests/test_di_panel_workflow.py -q
"""

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtGui import QSurfaceFormat  # noqa: E402
from PyQt5.QtWidgets import QApplication, QDialog  # noqa: E402

_fmt = QSurfaceFormat()
_fmt.setSamples(0)
_fmt.setDepthBufferSize(24)
_fmt.setVersion(3, 3)
_fmt.setProfile(QSurfaceFormat.CoreProfile)
QSurfaceFormat.setDefaultFormat(_fmt)
QApplication.setAttribute(Qt.AA_DisableWindowContextHelpButton, True)

_app = None


def _app_instance():
    global _app
    _app = QApplication.instance() or QApplication(sys.argv)
    _app.setStyle("Fusion")
    return _app


def _pump(ms=60):
    t0 = time.time()
    while (time.time() - t0) * 1000 < ms:
        _app.processEvents()
        time.sleep(0.004)


def _wait_until(predicate, timeout=20.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        _app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _orientation(rows):
    lines = [
        " Standard orientation:",
        " ---------------------------------------------------------------------",
        " Center     Atomic      Atomic             Coordinates (Angstroms)",
        " Number     Number       Type             X           Y           Z",
        " ---------------------------------------------------------------------",
    ]
    for idx, anum, x, y, z in rows:
        lines.append(" %6d %6d %6d %14.6f %14.6f %14.6f"
                     % (idx, anum, 0, x, y, z))
    lines.append(" ---------------------------------------------------------------------")
    lines.append("")
    return "\n".join(lines)


def _write_ts_log(path, energy=-100.3000000000):
    rows = [
        (1, 8, 0.000, 0.000, 0.000),
        (2, 1, 0.957, 0.000, 0.000),
        (3, 1, -0.240, 0.927, 0.000),
        (4, 6, 3.000, 0.000, 0.000),
        (5, 1, 3.700, 0.000, 0.000),
    ]
    text = "\n".join([
        " Entering Gaussian System, Link 0=g16",
        " %chk=ts.chk",
        " %mem=8GB",
        " %nprocshared=8",
        " ----------------------",
        " #p opt=(ts,calcfc,noeigentest) freq m06l/def2svp int=ultrafine",
        " ----------------------",
        " 1/38=1/1;",
        " Symbolic Z-matrix:",
        " Charge =  0 Multiplicity = 1",
        "",
        _orientation(rows),
        " SCF Done:  E(RM06L) = %.10f     A.U. after   10 cycles" % energy,
        " Normal termination of Gaussian 16",
        "",
    ])
    path.write_text(text, encoding="utf-8")
    return str(path)


def _make_dialog(initial=None):
    _app_instance()
    from molstudio.panels.di_local_dialog import DiLocalDialog

    dialog = DiLocalDialog(initial=initial or {})
    dialog.setAttribute(Qt.WA_DontShowOnScreen, True)
    dialog.show()
    _pump(120)
    return dialog


def _make_panel(tmp_path, monkeypatch):
    from molstudio.panels import di_analysis_panel as mod

    monkeypatch.setattr(
        mod.DiAnalysisPanel, "_settings_path",
        lambda self: str(tmp_path / "di_panel_settings.ini"))
    panel = mod.DiAnalysisPanel()
    panel.resize(1120, 760)
    panel.setAttribute(Qt.WA_DontShowOnScreen, True)
    panel.show()
    _pump(120)
    return panel, mod


def _fake_log(path, energy):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(" SCF Done:  E(RM06L) = %.10f     A.U. after   8 cycles\n"
                 % energy)
        fh.write(" Normal termination of Gaussian 16\n")
    return path


def test_dialog_load_ts_fragments_and_generate_inputs(tmp_path):
    _app_instance()
    ts_log = _write_ts_log(tmp_path / "DA_TS.log")
    dialog = _make_dialog()
    try:
        dialog._load_ts_from_path(ts_log)
        assert len(dialog._ts_atoms) == 5
        assert "opt=" in dialog._ts_route
        assert "已载入过渡态" in dialog.lbl_ts_info.text()

        dialog.edit_frag1.setText("1-3")
        dialog.edit_frag2.setText("4-5")
        dialog._apply_frag_edits()
        assert dialog._frag1 == {1, 2, 3}
        assert dialog._frag2 == {4, 5}
        assert dialog.mol_canvas.fragment_atoms[0] == {1, 2, 3}
        assert dialog.mol_canvas.fragment_atoms[1] == {4, 5}

        # 画布 Shift+框选信号链路：box_selected(1-based) → 片段归属
        dialog._clear_fragments()
        dialog._set_target(1)
        dialog.mol_canvas.box_selected.emit([1, 2])
        dialog._set_target(2)
        dialog.mol_canvas.box_selected.emit([3, 4, 5])
        assert dialog._frag1 == {1, 2}
        assert dialog._frag2 == {3, 4, 5}
        dialog.edit_frag1.setText("1-3")
        dialog.edit_frag2.setText("4-5")
        dialog._apply_frag_edits()

        out_dir = tmp_path / "di_out"
        dialog.edit_out.setText(str(out_dir))
        dialog.edit_mem.setText("4GB")
        dialog.edit_nproc.setText("4")
        jobs = dialog._prepare_jobs()
        assert jobs is not None and len(jobs) == 4
        assert [job["role"] for job in jobs] == [
            "frag1_def", "frag2_def", "frag1_opt", "frag2_opt"]
        assert [job["kind"] for job in jobs] == ["sp", "sp", "opt", "opt"]
        for job in jobs:
            assert os.path.isfile(job["gjf"])
            assert job["log"].endswith(".log")
        text0 = open(jobs[0]["gjf"], encoding="ascii").read()
        assert "%mem=4GB" in text0 and "%nprocshared=4" in text0
        assert "m06l/def2svp" in text0 and "int=ultrafine" in text0
        assert "opt=" not in text0 and "freq" not in text0
        route0 = [ln for ln in text0.splitlines() if ln.startswith("#")][0]
        assert route0.rstrip().endswith(" sp"), route0
        coord_rows = [ln for ln in text0.splitlines()
                      if ln.strip() and ln.split()[0] in {"O", "H", "C"}]
        assert len(coord_rows) == 3
        text2 = open(jobs[2]["gjf"], encoding="ascii").read()
        route2 = [ln for ln in text2.splitlines() if ln.startswith("#")][0]
        assert route2.rstrip().endswith(" opt"), route2
    finally:
        dialog.close()
        dialog.deleteLater()


def test_dialog_one_click_with_fake_gaussian(tmp_path, monkeypatch):
    _app_instance()
    ts_log = _write_ts_log(tmp_path / "DA_TS.log")
    dialog = _make_dialog()
    energies = {
        "frag1_def": -50.1000000000,
        "frag2_def": -50.0000000000,
        "frag1_opt": -50.5000000000,
        "frag2_opt": -50.4000000000,
    }

    def fake_run_gaussian(gjf, g16_exe=None, log_path=None, on_line=None,
                          cancel=None, timeout=None):
        from molstudio.core.gaussian_run import GaussianJobResult
        stem = os.path.splitext(os.path.basename(gjf))[0]
        role = ""
        for key in energies:
            if stem.endswith(key):
                role = key
        e = energies.get(role)
        if e is None:
            raise AssertionError("unexpected job: %s" % gjf)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as fh:
            fh.write(" SCF Done:  E(RM06L) = %.10f     A.U. after   8 cycles\n" % e)
            fh.write(" Normal termination of Gaussian 16\n")
        if on_line:
            on_line("SCF Done:  E(RM06L) = %.10f" % e)
            on_line("Normal termination of Gaussian 16")
        return GaussianJobResult(True, log_path, 0)

    monkeypatch.setattr(
        "molstudio.core.di_local.run_gaussian", fake_run_gaussian)
    fake_g16 = tmp_path / "g16.exe"
    fake_g16.write_bytes(b"")
    try:
        dialog._load_ts_from_path(ts_log)
        dialog.edit_frag1.setText("1-3")
        dialog.edit_frag2.setText("4-5")
        dialog._apply_frag_edits()
        dialog.edit_out.setText(str(tmp_path / "di_out"))
        dialog._get_g16 = lambda: str(fake_g16)

        dialog._run_local_workflow()
        assert _wait_until(lambda: dialog.is_done, 20.0), "弹窗没有跑完"
        assert dialog.progress.value() == dialog.progress.maximum()
        logs = dialog.log_data()
        assert logs is not None
        assert logs["ts"] == ts_log
        for key in ("frag1_def", "frag2_def", "frag1_opt", "frag2_opt"):
            assert os.path.basename(logs[key]) == "DA_TS_" + key + ".log"
            assert os.path.isfile(logs[key])
        assert dialog.btn_close.text() == "关闭并出图"
        # 已完成后用 Esc / 窗口 X 关闭也不能丢结果：统一按 accept 处理
        dialog.reject()
        assert dialog.result() == QDialog.Accepted
    finally:
        dialog.close()
        dialog.deleteLater()


def test_panel_dialog_result_loads_logs_and_plots(tmp_path, monkeypatch):
    _app_instance()
    ts_log = _write_ts_log(tmp_path / "DA_TS.log")
    di_dir = tmp_path / "di_out"
    logs = {"ts": ts_log}
    energies = {
        "frag1_def": -50.1000000000,
        "frag2_def": -50.0000000000,
        "frag1_opt": -50.5000000000,
        "frag2_opt": -50.4000000000,
    }
    for key, energy in energies.items():
        logs[key] = _fake_log(str(di_dir / ("DA_TS_" + key + ".log")), energy)

    from molstudio.panels import di_local_dialog as dialog_mod

    class FakeDialog:
        def __init__(self, parent=None, get_g16=None, log_func=None,
                     initial=None, lang="zh"):
            self._initial = dict(initial or {})

        def exec_(self):
            return QDialog.Accepted

        @property
        def is_done(self):
            return True

        def log_data(self):
            return dict(logs)

        def config(self):
            return dict(self._initial, ts_log=ts_log,
                        out_dir=str(di_dir), mem="4GB", nproc="4")

        def deleteLater(self):
            pass

    monkeypatch.setattr(dialog_mod, "DiLocalDialog", FakeDialog)
    panel, _mod = _make_panel(tmp_path, monkeypatch)
    try:
        assert hasattr(panel, "btn_open_local")
        assert not hasattr(panel, "mol_canvas")
        panel._open_local_dialog()

        R = panel._last_results
        assert R is not None
        assert abs(R["e1_opt"] - (-50.5)) < 1e-8
        assert abs(R["e2_opt"] - (-50.4)) < 1e-8
        assert abs(R["e1_def"] - (-50.1)) < 1e-8
        assert abs(R["e2_def"] - (-50.0)) < 1e-8
        assert abs(R["e_ts"] - (-100.3)) < 1e-8
        # ΔE_strain = 0.4 + 0.4 ; ΔE_int = -100.3 + 50.1 + 50.0 = -0.2
        assert abs(R["dE_strain"] - 0.8) < 1e-8
        assert abs(R["dE_int"] - (-0.2)) < 1e-8
        assert abs(R["dE_total"] - 0.6) < 1e-8
        assert panel.table.item(8, 2).text() == "502.0"
        assert panel._file_edits["ts"].text() == ts_log
        for key in ("frag1_def", "frag2_def", "frag1_opt", "frag2_opt"):
            assert panel._file_edits[key].text() == logs[key]
        assert not panel.chk_zpe.isChecked() and not panel.chk_gibbs.isChecked()
        assert panel._canvas is not None
        # 弹窗配置写回面板，供下次打开
        assert panel._local_config["mem"] == "4GB"
        assert panel._local_config["nproc"] == "4"
    finally:
        panel.shutdown()
        panel.hide()


def test_dialog_auto_fragments_and_fchk_route(tmp_path):
    """真实 TS fchk：连通性分成 乙烯(C2H4, 6) + 丁二烯(C4H6, 10)，且能出 route。"""
    fchk = r"D:\test-est\DA-5.fchk"
    if not os.path.isfile(fchk):
        import pytest
        pytest.skip("DA-5.fchk 不存在")
    _app_instance()
    dialog = _make_dialog({"mem": "4GB", "nproc": "4"})
    try:
        dialog._load_ts_from_path(fchk)
        assert len(dialog._ts_atoms) == 16
        dialog._auto_fragments()
        sizes = sorted([len(dialog._frag1), len(dialog._frag2)])
        assert sizes == [6, 10]

        def formula(ids):
            counts = {}
            for atom in dialog._ts_atoms:
                if atom[0] in ids:
                    counts[atom[1]] = counts.get(atom[1], 0) + 1
            return tuple(sorted(counts.items()))
        formulas = sorted((formula(dialog._frag1), formula(dialog._frag2)))
        assert (("C", 2), ("H", 4)) in formulas
        assert (("C", 4), ("H", 6)) in formulas

        # 只给 .fchk 时从 fchk 头拿到方法/基组并生成 4 个输入
        dialog.edit_out.setText(str(tmp_path / "out_fchk"))
        jobs = dialog._prepare_jobs()
        assert jobs is not None and len(jobs) == 4
        assert "RM06L/def2SVP" in jobs[0]["route"]
        assert os.path.isfile(jobs[0]["gjf"])
    finally:
        dialog.close()
        dialog.deleteLater()


def test_panel_settings_roundtrip(tmp_path, monkeypatch):
    _app_instance()
    panel, _mod = _make_panel(tmp_path, monkeypatch)
    try:
        panel._local_config.update({
            "ts_log": r"D:\test-est\DA-5.fchk",
            "out_dir": str(tmp_path / "di_out"),
            "mem": "6GB", "nproc": "6",
            "frag1": "1-7,14-16", "frag2": "8-13",
        })
        panel._save_settings()
    finally:
        panel.shutdown()
        panel.hide()

    from molstudio.panels import di_analysis_panel as mod
    second = mod.DiAnalysisPanel()
    second.resize(1120, 760)
    second.setAttribute(Qt.WA_DontShowOnScreen, True)
    second.show()
    _pump(120)
    try:
        assert second._local_config["ts_log"].endswith("DA-5.fchk")
        assert second._local_config["mem"] == "6GB"
        assert second._local_config["nproc"] == "6"
        assert second._local_config["frag1"] == "1-7,14-16"
        assert second._local_config["frag2"] == "8-13"
        # 弹窗默认值取自面板配置
        defaults = second._local_dialog_defaults()
        assert defaults["ts_log"].endswith("DA-5.fchk")
        assert defaults["out_dir"] == str(tmp_path / "di_out")
    finally:
        second.shutdown()
        second.hide()
