# -*- coding: utf-8 -*-
"""ORCA 弹窗的构造 / 结构载入 / 输入预览测试（不真正跑 ORCA）。"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

QApplication.setAttribute(Qt.AA_DisableWindowContextHelpButton, True)

_app = QApplication.instance() or QApplication(sys.argv)

from molstudio.panels.orca_local_dialog import (  # noqa: E402
    OrcaLocalDialog, _read_structure,
)

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


def test_read_structure_fchk():
    if not os.path.isfile(DA_FCHK):
        pytest.skip("DA-5_TS.fchk 不存在")
    symbols, coords = _read_structure(DA_FCHK)
    assert len(symbols) == 16
    assert len(coords) == 16
    assert symbols.count("C") == 6
    assert symbols.count("H") == 10
