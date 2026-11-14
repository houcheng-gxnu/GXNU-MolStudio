# -*- coding: utf-8 -*-
"""ORCA 计算页（左侧「常用」下的 tab）测试。"""

import os
import re
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QWidget

QApplication.setAttribute(Qt.AA_DisableWindowContextHelpButton, True)

_app = QApplication.instance() or QApplication(sys.argv)

from molstudio.panels.orca_panel import OrcaPanel  # noqa: E402

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
