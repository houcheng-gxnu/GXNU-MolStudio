# -*- coding: utf-8 -*-
"""高斯计算页（左侧「常用」下的 tab）测试：版面 / 预览 / 联用 / 运行流程。"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PyQt5.QtCore import QSettings, Qt
from PyQt5.QtWidgets import QApplication, QGridLayout, QWidget

QApplication.setAttribute(Qt.AA_DisableWindowContextHelpButton, True)

_app = QApplication.instance() or QApplication(sys.argv)

from molstudio.panels import gaussian_panel as gp  # noqa: E402
from molstudio.panels.gaussian_panel import TEXT, GaussianPanel  # noqa: E402

WATER = (["O", "H", "H"],
         np.array([[0.0, 0.0, 0.1173],
                   [0.0, 0.7572, -0.4692],
                   [0.0, -0.7572, -0.4692]]))


@pytest.fixture(autouse=True)
def _isolated_qsettings(tmp_path, monkeypatch):
    """隔离注册表/ini，避免本机旧设置影响目录与路径断言。

    ``QSettings("MolStudio", ...)`` 默认走原生格式（Windows 注册表），
    ``setDefaultFormat`` 对已存在的实例无效，所以直接把面板模块里的
    ``QSettings`` 换成显式 IniFormat 的子类。
    """
    cfg = tmp_path / "qsettings"
    cfg.mkdir(parents=True, exist_ok=True)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(cfg))

    class IniSettings(QSettings):
        def __init__(self, org, app):
            super().__init__(QSettings.IniFormat, QSettings.UserScope, org, app)

    monkeypatch.setattr(gp, "QSettings", IniSettings)
    yield


def _make(**kwargs):
    symbols, coords = WATER
    kwargs.setdefault("get_structure", lambda: (list(symbols),
                                                [list(r) for r in coords]))
    kwargs.setdefault("g16_exe", "")
    panel = GaussianPanel(**kwargs)
    panel.sync_from_canvas(force=True)
    return panel


class _Sig:
    def connect(self, *_args, **_kwargs):
        pass

    def emit(self, *_args, **_kwargs):
        pass


def test_panel_reads_canvas_and_previews_gjf():
    panel = _make()
    try:
        assert panel._symbols == WATER[0]
        text = panel.preview.toPlainText()
        assert "#p " in text
        assert "%nprocshared=" in text
        assert "%chk=" in text
        assert "0 1" in text
        assert "O " in text
    finally:
        panel.close()


def test_layout_matches_orca_shape():
    panel = _make()
    try:
        assert [panel.tabs.tabText(i) for i in range(panel.tabs.count())] == [
            TEXT["zh"]["tab_input"], TEXT["zh"]["tab_log"],
            TEXT["zh"]["tab_result"]]
        # 结构区：来源文字在按钮上面
        assert panel.grp_struct.layout().itemAt(0).widget() is panel.lbl_source
        # 计算设置是两列表单
        grid = panel.grp_calc.layout()
        assert isinstance(grid, QGridLayout)
        assert grid.itemAtPosition(0, 0).widget() is panel._labels["method"]
        assert grid.itemAtPosition(0, 1).widget() is panel.cmb_method
        # 按钮行顺序：生成输入 / 保存 / 复制 …… 停止 / 开始
        row = panel.layout().itemAt(2).layout()
        assert row.itemAt(0).widget() is panel.btn_gen
        assert row.itemAt(1).widget() is panel.btn_save
        assert row.itemAt(2).widget() is panel.btn_copy
        assert row.itemAt(4).widget() is panel.btn_stop
        assert row.itemAt(5).widget() is panel.btn_run
        assert panel.progress.maximumHeight() == 6
    finally:
        panel.close()


def test_load_gjf_sets_charge_mult_name_and_workdir(tmp_path):
    gjf = tmp_path / "anion.gjf"
    gjf.write_text("#p B3LYP/def2SVP\n\nanion\n\n-1 2\n"
                   "O  0.0  0.0  0.0626\nH -0.792 0.0 -0.4973\n"
                   "H  0.792 0.0 -0.4973\n\n", encoding="utf-8")
    opened = []
    panel = GaussianPanel(get_structure=lambda: None,
                          on_open_structure=lambda p: opened.append(p),
                          g16_exe="")
    try:
        assert panel.load_structure_path(str(gjf))
        assert opened == [str(gjf)]
        assert panel.spin_charge.value() == -1
        assert panel.spin_mult.value() == 2
        assert panel.edit_name.text() == "anion_gauss"
        assert panel.edit_workdir.text().endswith("anion_GAUSS")
        run_dir = panel._resolve_run_dir()
        assert os.path.dirname(run_dir) == panel.edit_workdir.text()
        assert os.path.basename(run_dir) != ""
    finally:
        panel.close()


def test_nbo_input_button_opens_generator_with_loaded_gjf(tmp_path, monkeypatch):
    gjf = tmp_path / "nbo_source.gjf"
    gjf.write_text("#p b3lyp/def2svp\n\nwater\n\n0 1\n"
                   "O  0.0  0.0  0.0626\nH -0.792 0.0 -0.4973\n"
                   "H  0.792 0.0 -0.4973\n\n", encoding="utf-8")
    captured = {}

    class FakeDialog:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def exec_(self):
            captured["executed"] = True

    import molstudio.panels.nbo_input_dialog as nbo_dialog
    monkeypatch.setattr(nbo_dialog, "NboInputDialog", FakeDialog)
    panel = GaussianPanel(get_structure=lambda: None, g16_exe="")
    try:
        assert panel.load_structure_path(str(gjf))
        panel.btn_nbo_input.click()
        assert captured["initial_source"] == str(gjf)
        assert captured["executed"] is True
    finally:
        panel.close()


def test_bridge_toggle_injects_external_and_env(tmp_path):
    panel = _make()
    try:
        panel.edit_xexe.setText(sys.executable)      # 只要求是真实存在的文件
        panel.edit_workdir.setText(str(tmp_path / "base"))
        panel._workdir_auto = False
        panel._workdir_user_edited = True
        panel.chk_bridge.setChecked(True)
        panel._refresh_preview()
        text = panel.preview.toPlainText()
        assert "external='" in text
        assert "gau_xtb_client.bat" in text
        assert "B3LYP" not in text
        route, notes = panel._route_for(str(tmp_path / "base"))
        assert route.startswith("#P") and "external='" in route
        assert not panel.cmb_method.isEnabled()
        env = panel._bridge_env()
        assert env["GAU_XTB_COMMAND"] == sys.executable
        assert env["GAU_XTB_METHOD"] == "--gfn 2"
        assert env["GAU_XTB_THREADS"]

        prepared = panel._prepare_input(str(tmp_path / "base"))
        assert os.path.isfile(prepared["gjf_path"])
        assert os.path.isfile(os.path.join(str(tmp_path / "base"),
                                           gp.BRIDGE.CLIENT_BAT_NAME))
        # 关掉联用后方法关键字回来
        panel.chk_bridge.setChecked(False)
        panel._refresh_preview()
        assert "B3LYP" in panel.preview.toPlainText()
        assert panel.cmb_method.isEnabled()
    finally:
        panel.close()


def test_run_creates_timestamped_folder(tmp_path, monkeypatch):
    captured = {}

    class FakeWorker:
        def __init__(self, cfg, parent=None):
            captured.update(cfg)
            self.log_line = _Sig()
            self.stage = _Sig()
            self.finished_ok = _Sig()
            self.failed = _Sig()

        def isRunning(self):
            return False

        def start(self):
            pass

    monkeypatch.setattr(gp, "GaussianWorker", FakeWorker)
    panel = _make(g16_exe=r"E:\g16w\g16.exe")
    try:
        panel.edit_workdir.setText(str(tmp_path / "base"))
        panel._workdir_auto = False
        panel._workdir_user_edited = True
        panel.edit_name.setText("water_gauss")
        panel.run()
        run_dir = captured["gjf_path"].rsplit(os.sep, 1)[0]
        assert os.path.dirname(run_dir) == str(tmp_path / "base")
        assert os.path.isfile(captured["gjf_path"])
        assert captured["log_path"].endswith("water_gauss.log")
        assert captured["g16_exe"] == r"E:\g16w\g16.exe"
        assert panel.tabs.currentIndex() == 1
        assert panel._last_run_dir == run_dir
    finally:
        panel.close()


def test_english_labels_have_no_chinese():
    import re
    panel = _make(lang="en")
    cjk = re.compile(r"[\u4e00-\u9fff]")
    try:
        assert panel.btn_run.text() == TEXT["en"]["run"]
        assert panel.grp_calc.title() == TEXT["en"]["grp_calc"]
        bad = []
        for widget in [panel] + panel.findChildren(QWidget):
            for attr in ("text", "title", "placeholderText", "toolTip"):
                getter = getattr(widget, attr, None)
                if callable(getter):
                    try:
                        value = getter()
                    except Exception:                    # noqa: BLE001
                        value = ""
                    if isinstance(value, str) and cjk.search(value):
                        bad.append((type(widget).__name__, attr, value))
        assert not bad, bad[:5]
    finally:
        panel.close()


def test_run_requires_g16(tmp_path):
    panel = _make(g16_exe="")
    try:
        panel.edit_g16.setText("")
        panel.run()
        assert "g16" in panel.lbl_status.text().lower() or \
            "Gaussian" in panel.lbl_status.text()
    finally:
        panel.close()


def test_fill_results_from_parsed(tmp_path):
    from molstudio.panels.gaussian_worker import GaussianTabResult

    panel = _make()
    try:
        result = GaussianTabResult(
            workdir=str(tmp_path), gjf_path="a.gjf", log_path="a.log",
            chk_path="a.chk", fchk_path="a.fchk",
            parsed={"final_energy": -76.4, "homo": -0.20835, "lumo": 0.05,
                    "homo_lumo_gap_ev": 7.03, "frequencies": [100.0, 200.0],
                    "imaginary": [], "terminated_normally": True,
                    "opt_converged": True, "steps": 3, "bridge": True},
            elapsed=1.5, normal=True)
        panel._active_task = "opt"
        panel._fill_results(result)
        assert "-76.400000" in panel._res_labels["energy"].text()
        assert "7.03" in panel._res_labels["gap"].text()
        assert panel._res_labels["opt"].text() == TEXT["zh"]["yes"]
        assert panel._res_labels["normal"].text() == TEXT["zh"]["yes"]
        assert "3" in panel._res_labels["steps"].text()
        assert panel._res_labels["fchk_file"].text() == "a.fchk"
    finally:
        panel.close()


# ── pop 关键词：载入 gjf / NBO 生成器交接时不能丢 ──────────────────

def test_route_pop_keyword_parsing():
    assert gp.route_pop_keyword(
        "#p b3lyp/def2svp pop=saveNBO") == "pop=saveNBO"
    assert gp.route_pop_keyword(
        "%chk=a.chk\n#p m06l/def2svp pop=nboread\n\ntitle\n") == "pop=nboread"
    assert gp.route_pop_keyword("#p b3lyp/def2svp") == ""
    assert gp.route_pop_keyword("") == ""


def test_loading_gjf_keeps_pop_keyword(tmp_path):
    gjf = tmp_path / "nbo_src.gjf"
    gjf.write_text(
        "#p b3lyp/def2svp pop=saveNBO\n\nwater\n\n0 1\n"
        "O  0.0  0.0  0.1173\nH  0.0  0.7572 -0.4692\n"
        "H  0.0 -0.7572 -0.4692\n\n", encoding="utf-8")
    panel = GaussianPanel(get_structure=lambda: None, g16_exe="")
    try:
        assert panel.load_structure_path(str(gjf))
        assert "pop=saveNBO" in panel.edit_extra.text()
        assert "pop=saveNBO" in panel.preview.toPlainText()
        assert "saveNBO" in panel.lbl_status.text()
    finally:
        panel.close()


class _FakeNboDialog:
    def __init__(self, route):
        self._route = route

        class _Editor:
            def __init__(self, route_text):
                self._text = route_text

            def toPlainText(self):                     # noqa: N802
                return self._text

        self.editor = _Editor(route)


def test_nbo_dialog_handoff_fills_pop_keyword():
    panel = _make()
    try:
        panel._adopt_nbo_pop(_FakeNboDialog(
            "%chk=x.chk\n#p b3lyp/def2svp pop=saveNBO\n\nwater\n\n0 1\n"))
        assert panel.edit_extra.text().strip() == "pop=saveNBO"
        assert "pop=saveNBO" in panel.lbl_status.text()
        assert "pop=saveNBO" in panel.preview.toPlainText()
        # 再交接一次不重复叠加
        panel._adopt_nbo_pop(_FakeNboDialog(
            "#p b3lyp/def2svp pop=saveNBO\n"))
        assert panel.edit_extra.text().count("pop=") == 1
    finally:
        panel.close()


def test_nbo_plot_handoff_warns_about_missing_data_block():
    panel = _make()
    try:
        panel._adopt_nbo_pop(_FakeNboDialog(
            "#p b3lyp/def2svp pop=nboread\n\nwater\n\n0 1\n"
            "$NBO plot file=water $END\n"))
        assert "pop=" not in panel.edit_extra.text()
        status = panel.lbl_status.text()
        assert "数据块" in status or "data block" in status.lower()
    finally:
        panel.close()
