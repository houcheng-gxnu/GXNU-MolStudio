# -*- coding: utf-8 -*-
"""ORCA 弹窗的构造 / 结构载入 / 输入预览测试（不真正跑 ORCA）。"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PyQt5.QtCore import QSettings, Qt
from PyQt5.QtWidgets import QApplication

QApplication.setAttribute(Qt.AA_DisableWindowContextHelpButton, True)

_app = QApplication.instance() or QApplication(sys.argv)

from molstudio.panels.orca_local_dialog import (  # noqa: E402
    OrcaLocalDialog, _read_structure,
)


@pytest.fixture(autouse=True)
def _isolated_qsettings(tmp_path, monkeypatch):
    """隔离注册表/ini（QSettings 两参构造默认走原生格式，setDefaultFormat 无效）。"""
    import molstudio.panels.orca_local_dialog as mod

    cfg = tmp_path / "qsettings"
    cfg.mkdir(parents=True, exist_ok=True)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(cfg))

    class IniSettings(QSettings):
        def __init__(self, org, app):
            super().__init__(QSettings.IniFormat, QSettings.UserScope, org, app)

    monkeypatch.setattr(mod, "QSettings", IniSettings)
    yield

WATER_XYZ = """3
water
O 0 0 0.0626
H -0.792 0 -0.4973
H 0.792 0 -0.4973
"""

DA_FCHK = r"C:\Users\Administrator\Desktop\DA-5_TS_DA反应过渡态\DA-5_TS.fchk"


def test_dialog_loads_xyz_and_previews_input(tmp_path):
    xyz = tmp_path / "water.xyz"
    xyz.write_text(WATER_XYZ, encoding="utf-8")
    dlg = OrcaLocalDialog(initial_path=str(xyz), orca_exe="")
    try:
        assert dlg._symbols == ["O", "H", "H"]
        text = dlg.preview.toPlainText()
        assert "! B3LYP def2-SVP" in text
        assert "%pal nprocs 4 end" in text
        assert "* xyz 0 1" in text
        cfg = dlg._config()
        assert cfg["symbols"] == ["O", "H", "H"]
        assert cfg["task"] == "sp"
        assert cfg["nprocs"] >= 2
    finally:
        dlg.close()


def test_dialog_orca_path_is_editable(tmp_path):
    """备用弹窗也能指定 orca.exe（并落盘）。"""
    from molstudio.core import orca_run as ORCA

    fake = tmp_path / "orca.exe"
    fake.write_bytes(b"")
    dlg = OrcaLocalDialog(orca_exe="")
    try:
        assert dlg.edit_orca is not None
        dlg.edit_orca.setText(str(fake))
        assert dlg._config()["orca_exe"] == str(fake)
        dlg._save_settings()
        assert dlg._settings.value("orca", "", type=str) == str(fake)
        dlg.edit_orca.setText("")
        assert dlg._config()["orca_exe"] == ORCA.find_orca_exe()
    finally:
        dlg.close()


def test_dialog_ts_preview_adds_hess(tmp_path):
    xyz = tmp_path / "c.xyz"
    xyz.write_text("2\nC2\nC 0 0 0\nH 1 0 0\n", encoding="utf-8")
    dlg = OrcaLocalDialog(initial_path=str(xyz))
    try:
        idx = dlg.cmb_task.findData("ts_freq")
        dlg.cmb_task.setCurrentIndex(idx)
        dlg._refresh_preview()
        text = dlg.preview.toPlainText()
        assert "OptTS Freq" in text
        assert "Calc_Hess true" in text
        assert "%pal nprocs" in text
    finally:
        dlg.close()


def test_dialog_english_labels(tmp_path):
    xyz = tmp_path / "w.xyz"
    xyz.write_text(WATER_XYZ, encoding="utf-8")
    dlg = OrcaLocalDialog(initial_path=str(xyz), lang="en")
    try:
        assert dlg.windowTitle() == "Local ORCA calculation"
        assert "Standalone module" in dlg._t("subtitle")
        assert dlg._t("method") == "Method"
        assert "B3LYP" in dlg.preview.toPlainText()
    finally:
        dlg.close()


def test_dialog_follows_gjf_name_charge_and_folder(tmp_path):
    gjf = tmp_path / "anion.gjf"
    gjf.write_text(
        "#p b3lyp/def2svp\n\nanion\n\n-1 2\n"
        "O  0.0  0.0  0.0626\nH -0.792 0.0 -0.4973\n"
        "H  0.792 0.0 -0.4973\n\n", encoding="utf-8")
    dlg = OrcaLocalDialog(initial_path=str(gjf), orca_exe="")
    try:
        assert dlg.spin_charge.value() == -1
        assert dlg.spin_mult.value() == 2
        assert dlg.edit_name.text() == "anion_orca"
        assert "* xyz -1 2" in dlg.preview.toPlainText()
        base = dlg.edit_workdir.text()
        assert base.endswith("anion_ORCA")
        run_dir = dlg._resolve_run_dir()
        assert os.path.dirname(run_dir) == base
        assert os.path.basename(run_dir) != ""
    finally:
        dlg.close()


def test_read_structure_fchk():
    if not os.path.isfile(DA_FCHK):
        pytest.skip("DA-5_TS.fchk 不存在")
    symbols, coords = _read_structure(DA_FCHK)
    assert len(symbols) == 16
    assert len(coords) == 16
    assert symbols.count("C") == 6
    assert symbols.count("H") == 10
