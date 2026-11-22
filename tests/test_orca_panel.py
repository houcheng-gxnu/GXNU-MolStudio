# -*- coding: utf-8 -*-
"""ORCA 计算页（左侧「常用」下的 tab）测试。"""

import os
import re
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5.QtCore import QSettings, Qt
from PyQt5.QtWidgets import QApplication, QWidget

QApplication.setAttribute(Qt.AA_DisableWindowContextHelpButton, True)

_app = QApplication.instance() or QApplication(sys.argv)

from molstudio.panels.orca_panel import TEXT, OrcaPanel  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_qsettings(tmp_path, monkeypatch):
    """本机注册表里的旧设置会让面板沿用别的目录/路径，测试里隔离掉。

    ``QSettings("MolStudio", "OrcaPanel")`` 默认走原生格式（Windows 注册表），
    ``setDefaultFormat`` 对已存在的实例无效，所以直接把面板模块里的
    ``QSettings`` 换成一个显式 IniFormat 的子类。
    """
    import molstudio.panels.orca_panel as mod

    cfg = tmp_path / "qsettings"
    cfg.mkdir(parents=True, exist_ok=True)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(cfg))

    class IniSettings(QSettings):
        def __init__(self, org, app):
            super().__init__(QSettings.IniFormat, QSettings.UserScope, org, app)

    monkeypatch.setattr(mod, "QSettings", IniSettings)
    yield

WATER = (["O", "H", "H"],
         [[0.0, 0.0, 0.0626], [-0.792, 0.0, -0.4973],
          [0.792, 0.0, -0.4973]])


def _make(**kwargs):
    symbols, coords = WATER
    kwargs.setdefault("get_structure", lambda: (list(symbols),
                                                [list(r) for r in coords]))
    kwargs.setdefault("orca_exe", "")
    panel = OrcaPanel(**kwargs)
    panel.sync_from_canvas(force=True)
    return panel


def test_panel_reads_canvas_and_builds_input():
    panel = _make()
    try:
        assert panel._symbols == WATER[0]
        text = panel.preview.toPlainText()
        assert "! B3LYP def2-SVP" in text
        assert "%pal nprocs" in text
        assert "* xyz 0 1" in text
    finally:
        panel.close()


def test_panel_ts_preview_has_hess():
    panel = _make()
    try:
        idx = panel.cmb_task.findData("ts_freq")
        panel.cmb_task.setCurrentIndex(idx)
        panel._refresh_preview()
        text = panel.preview.toPlainText()
        assert "OptTS Freq" in text
        assert "Calc_Hess true" in text
    finally:
        panel.close()


def test_panel_english_labels_have_no_chinese():
    panel = _make(lang="en")
    try:
        assert panel._t("run") == "Run ORCA"
        assert panel.btn_run.text() == "Run ORCA"
        cjk = re.compile(r"[\u4e00-\u9fff]")
        bad = []
        for w in [panel] + panel.findChildren(QWidget):
            for attr in ("text", "placeholderText", "toolTip"):
                getter = getattr(w, attr, None)
                if callable(getter):
                    try:
                        val = getter()
                    except Exception:                    # noqa: BLE001
                        val = ""
                    if isinstance(val, str) and cjk.search(val):
                        bad.append((type(w).__name__, val))
        assert not bad, bad[:5]
    finally:
        panel.close()


def test_panel_without_structure_status():
    panel = OrcaPanel(get_structure=lambda: None, orca_exe="")
    try:
        panel.sync_from_canvas(force=True)
        assert not panel._symbols
        assert "结构" in panel.lbl_status.text() or \
            "structure" in panel.lbl_status.text().lower()
    finally:
        panel.close()


def test_panel_loads_gjf_and_notifies_main(tmp_path):
    gjf = tmp_path / "water.gjf"
    gjf.write_text(
        "#p b3lyp/def2svp\n\nwater\n\n0 1\n"
        "O  0.0  0.0  0.0626\nH -0.792 0.0 -0.4973\n"
        "H  0.792 0.0 -0.4973\n\n", encoding="utf-8")
    opened = []
    panel = OrcaPanel(get_structure=lambda: None,
                      on_open_structure=lambda p: opened.append(p),
                      orca_exe="")
    try:
        assert panel.load_structure_path(str(gjf))
        assert opened == [str(gjf)]
        assert panel._symbols == ["O", "H", "H"]
        assert panel.edit_name.text().startswith("water")
        assert "* xyz 0 1" in panel.preview.toPlainText()
    finally:
        panel.close()


def test_panel_reads_gjf_charge_mult_and_follows_file_name(tmp_path):
    gjf = tmp_path / "anion.gjf"
    gjf.write_text(
        "#p b3lyp/def2svp\n\nanion\n\n-1 2\n"
        "O  0.0  0.0  0.0626\nH -0.792 0.0 -0.4973\n"
        "H  0.792 0.0 -0.4973\n\n", encoding="utf-8")
    panel = OrcaPanel(get_structure=lambda: None, orca_exe="")
    try:
        assert panel.load_structure_path(str(gjf))
        assert panel.spin_charge.value() == -1
        assert panel.spin_mult.value() == 2
        assert "* xyz -1 2" in panel.preview.toPlainText()
        # 输出基目录跟到文件同级的 <文件名>_ORCA
        assert panel._default_workdir().endswith("anion_ORCA")
        base = panel.edit_workdir.text().strip()
        assert base.endswith("anion_ORCA")
        # 每次运行再在基目录下建时间戳子目录
        run_dir = panel._resolve_run_dir()
        assert os.path.dirname(run_dir) == base
        assert os.path.basename(run_dir) != ""
    finally:
        panel.close()


def test_panel_switching_molecule_updates_name_and_run_dir(tmp_path):
    water = tmp_path / "water.gjf"
    water.write_text("#p b3lyp/def2svp\n\nwater\n\n0 1\n"
                     "O 0 0 0.0626\nH -0.792 0 -0.4973\n"
                     "H 0.792 0 -0.4973\n\n", encoding="utf-8")
    methane = tmp_path / "methane.gjf"
    methane.write_text("#p b3lyp/def2svp\n\nmethane\n\n0 1\n"
                       "C 0 0 0\nH 0.63 0.63 0.63\nH -0.63 -0.63 0.63\n"
                       "H -0.63 0.63 -0.63\nH 0.63 -0.63 -0.63\n\n",
                       encoding="utf-8")
    panel = OrcaPanel(get_structure=lambda: None, orca_exe="")
    try:
        assert panel.load_structure_path(str(water))
        first_name = panel.edit_name.text()
        first_dir = panel._resolve_run_dir()
        assert panel.load_structure_path(str(methane))
        assert panel.edit_name.text() == "methane_orca"
        assert panel.edit_name.text() != first_name
        second_dir = panel._resolve_run_dir()
        assert os.path.dirname(second_dir).endswith("methane_ORCA")
        assert os.path.dirname(first_dir).endswith("water_ORCA")
    finally:
        panel.close()


def test_panel_adopts_main_window_gjf(tmp_path):
    """主窗口打开 gjf 后切到 ORCA 页：认领文件来源（名字/目录/电荷）。"""
    from molstudio.core import orca_run as ORCA

    gjf = tmp_path / "anion.gjf"
    gjf.write_text(
        "#p b3lyp/def2svp\n\nanion\n\n-1 2\n"
        "O  0.0  0.0  0.0626\nH -0.792 0.0 -0.4973\n"
        "H  0.792 0.0 -0.4973\n\n", encoding="utf-8")
    panel = OrcaPanel(get_structure=lambda: None,
                      get_structure_path=lambda: str(gjf), orca_exe="")
    try:
        symbols, coords = ORCA.read_structure_file(str(gjf))
        panel._symbols = list(symbols)
        panel._coords = [list(r) for r in coords]
        panel._source_kind = "canvas"
        panel._sync_source_meta()
        panel._on_structure_switched()
        assert panel._source_kind == "file"
        assert panel._source_path == str(gjf)
        assert panel.edit_name.text() == "anion_orca"
        assert panel.spin_charge.value() == -1
        assert panel.spin_mult.value() == 2
        assert panel.edit_workdir.text().endswith("anion_ORCA")
    finally:
        panel.close()


def test_panel_run_creates_timestamped_folder(tmp_path, monkeypatch):
    """点「开始计算」要在基目录下新建时间戳目录，并把 .inp 写进去。"""
    import molstudio.panels.orca_panel as mod

    captured = {}

    class FakeWorker:
        def __init__(self, cfg, parent=None):
            captured.update(cfg)
            self.log_line = _Sig()
            self.stage = _Sig()
            self.finished_ok = _Sig()
            self.failed = _Sig()

        def start(self):
            pass

    monkeypatch.setattr(mod, "OrcaWorker", FakeWorker)
    panel = _make(orca_exe="orca.exe")
    try:
        panel.edit_name.setText("water_orca")
        panel.edit_workdir.setText(str(tmp_path / "base"))
        panel._workdir_auto = False
        panel._workdir_user_edited = True
        panel.run()
        run_dir = captured["workdir"]
        assert os.path.dirname(run_dir) == str(tmp_path / "base")
        assert os.path.isdir(run_dir)
        assert panel.edit_workdir.text() == run_dir
        assert panel._workdir_base == str(tmp_path / "base")
        assert os.path.isfile(os.path.join(run_dir, "water_orca.inp"))
    finally:
        panel.close()


class _Sig:
    def connect(self, *_args, **_kwargs):
        pass

    def emit(self, *_args, **_kwargs):
        pass


def test_orca_path_is_editable_and_persisted(tmp_path):
    """右侧能直接指定 orca.exe：立即生效、落盘、下次启动恢复。"""
    from molstudio.core import orca_run as ORCA

    fake = tmp_path / "orca.exe"
    fake.write_bytes(b"")
    panel = OrcaPanel(get_structure=lambda: None, orca_exe="")
    try:
        # 表单里有「ORCA 可执行文件」这一行
        assert panel._labels["orca_exe"].text() == TEXT["zh"]["orca_exe"]
        assert panel.btn_browse_orca.text() == TEXT["zh"]["browse"]
        assert panel.btn_detect_orca.text() == TEXT["zh"]["detect"]

        panel.edit_orca.setText(str(fake))
        assert panel._config()["orca_exe"] == str(fake)
        panel._save_settings()

        other = OrcaPanel(get_structure=lambda: None, orca_exe="")
        try:
            assert other.edit_orca.text() == str(fake)
            assert other._config()["orca_exe"] == str(fake)
        finally:
            other.close()

        # 清空 → 回落到自动检测
        panel.edit_orca.setText("")
        assert panel._config()["orca_exe"] == ORCA.find_orca_exe()
    finally:
        panel.close()


def test_orca_detect_button_finds_exe(tmp_path, monkeypatch):
    from molstudio.core import orca_run as ORCA

    fake = tmp_path / "orca.exe"
    fake.write_bytes(b"")
    monkeypatch.setattr(ORCA, "find_orca_exe", lambda *_a, **_k: str(fake))
    panel = OrcaPanel(get_structure=lambda: None, orca_exe="")
    try:
        panel.edit_orca.setText("")
        panel._detect_orca()
        assert panel.edit_orca.text() == str(fake)
    finally:
        panel.close()


def test_orca_run_uses_edited_path(tmp_path, monkeypatch):
    captured = {}

    class FakeWorker:
        def __init__(self, cfg, parent=None):
            captured.update(cfg)
            self.log_line = _Sig()
            self.stage = _Sig()
            self.finished_ok = _Sig()
            self.failed = _Sig()

        def start(self):
            pass

    import molstudio.panels.orca_panel as mod
    monkeypatch.setattr(mod, "OrcaWorker", FakeWorker)
    fake = tmp_path / "my_orca.exe"
    fake.write_bytes(b"")
    panel = _make(orca_exe="")
    try:
        panel.edit_orca.setText(str(fake))
        panel.edit_workdir.setText(str(tmp_path / "base"))
        panel._workdir_auto = False
        panel._workdir_user_edited = True
        panel.run()
        assert captured["orca_exe"] == str(fake)
    finally:
        panel.close()
