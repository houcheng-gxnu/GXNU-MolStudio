# -*- coding: utf-8 -*-
"""微动力学面板的 UI 冒烟测试（offscreen，不弹窗、不写用户配置）。

    pytest tests/test_microkinetics_panel.py -q
"""

import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from PyQt5.QtWidgets import (QApplication, QComboBox, QTableWidget,  # noqa: E402
                             QWidget)

_CJK = re.compile(r"[\u4e00-\u9fff]")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _panel():
    from molstudio.panels.microkinetics_panel import (_autof_example_data,
                                                      MicrokineticsPanel)
    panel = MicrokineticsPanel()
    panel._save_settings = lambda: None       # 不写仓库根目录的 ini
    panel._restore(_autof_example_data())
    return panel


def _chinese_texts(root):
    out = []
    for w in [root] + root.findChildren(QWidget):
        for attr in ("text", "windowTitle", "placeholderText", "toolTip"):
            getter = getattr(w, attr, None)
            if callable(getter):
                try:
                    value = getter()
                except RuntimeError:
                    value = None
                if isinstance(value, str):
                    out.append(value)
        if isinstance(w, QComboBox):
            out += [w.itemText(i) for i in range(w.count())]
        if isinstance(w, QTableWidget):
            out += [w.horizontalHeaderItem(c).text()
                    for c in range(w.columnCount())
                    if w.horizontalHeaderItem(c)]
    return [t for t in out if _CJK.search(t)]


def test_panel_computes_autof_example(app):
    panel = _panel()
    assert panel.table.rowCount() == 4
    panel._calculate()
    assert "18.50" in panel._result_labels["delta_e"].text()
    assert panel._result_labels["tof"].text().startswith("1.62")
    assert panel._result_labels["ton"].text().startswith("1935")
    assert panel.table.item(1, 5).text().startswith("0.974")
    assert panel.table.item(1, 11).text() == "TDI"
    assert panel.table.item(2, 11).text() == "TDTS"
    assert panel._canvas is not None
    assert all(b.isEnabled() for b in panel._export_buttons)
    assert panel.trajectory is not None and panel.trajectory.success


def test_panel_language_switch(app):
    panel = _panel()
    zh_count = len(_chinese_texts(panel))
    assert zh_count > 0
    panel.set_lang("en")
    assert not _chinese_texts(panel), "英文界面仍残留中文"
    panel.set_lang("zh")
    assert len(_chinese_texts(panel)) == zh_count
