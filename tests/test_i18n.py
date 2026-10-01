# -*- coding: utf-8 -*-
"""语言切换回归：切到英文后每个页签都不应再有中文；切回中文要完全还原。

（2026-10-01：新增面板当时没有 i18n，切英文后 11 个页签仍是中文。）

    pytest tests -q
"""

import os
import re
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtGui import QSurfaceFormat  # noqa: E402
from PyQt5.QtWidgets import (QApplication, QComboBox, QTableWidget,  # noqa: E402
                             QTabWidget, QWidget)

_fmt = QSurfaceFormat()
_fmt.setSamples(0)
_fmt.setDepthBufferSize(24)
_fmt.setVersion(3, 3)
_fmt.setProfile(QSurfaceFormat.CoreProfile)
QSurfaceFormat.setDefaultFormat(_fmt)
QApplication.setAttribute(Qt.AA_DisableWindowContextHelpButton, True)

_CJK = re.compile(r"[\u4e00-\u9fff]")
_app = None


def _pump(ms=100):
    t0 = time.time()
    while (time.time() - t0) * 1000 < ms:
        _app.processEvents()
        time.sleep(0.005)


def _texts(widget):
    out = []
    for attr in ("text", "windowTitle", "placeholderText", "toolTip"):
        getter = getattr(widget, attr, None)
        if callable(getter):
            try:
                value = getter()
            except RuntimeError:
                value = None
            if isinstance(value, str) and value.strip():
                out.append(value)
    if isinstance(widget, QComboBox):
        out += [widget.itemText(i) for i in range(widget.count())]
    if isinstance(widget, QTabWidget):
        out += [widget.tabText(i) for i in range(widget.count())]
    if isinstance(widget, QTableWidget):
        out += [widget.horizontalHeaderItem(c).text()
                for c in range(widget.columnCount())
                if widget.horizontalHeaderItem(c)]
    for action in getattr(widget, "actions", lambda: [])():
        if action.text():
            out.append(action.text())
    return out


def _chinese_per_tab(window):
    result = {}
    for i in range(window.main_nav.count()):
        window.main_nav.setCurrentRow(i)
        _pump(90)
        page = window.tabs.currentWidget()
        widgets = ([page] if page else []) + (page.findChildren(QWidget) if page else [])
        hits = 0
        for widget in widgets:
            for text in _texts(widget):
                if _CJK.search(text):
                    hits += 1
        result[window.main_nav.item(i).text()] = hits
    return result


def test_every_tab_speaks_english_after_switch():
    global _app
    _app = QApplication.instance() or QApplication(sys.argv)
    _app.setStyle("Fusion")

    import molstudio.core.i18n as i18n
    from molstudio.ui.main_window_clean import MolStudioCleanWindow

    i18n._CURRENT_LANG = "zh"        # 前面的测试可能把语言留在英文
    window = MolStudioCleanWindow()
    window.resize(1280, 660)
    window.setAttribute(Qt.WA_DontShowOnScreen, True)
    window.show()
    _pump(1400)
    baseline = _chinese_per_tab(window)
    assert sum(baseline.values()) > 0, "中文界面本应含中文"

    # 回归：切语言不能改动画布状态。ESP 的色标条曾经会在第一次切英文时自己冒出来
    # （改下拉条目触发 currentTextChanged → 槽函数顺手打开了色标条）。
    glw = getattr(getattr(window, "esp_panel", None), "glw", None)
    cs_before = getattr(glw, "_cs_show", None)

    window._switch_lang()
    _pump(900)
    assert i18n._CURRENT_LANG == "en"
    assert getattr(glw, "_cs_show", None) == cs_before, "切语言不应改变画布色标条状态"
    remaining = _chinese_per_tab(window)
    offenders = {k: v for k, v in remaining.items() if v}
    assert not offenders, f"切到英文后仍有中文的页签：{offenders}"

    window._switch_lang()
    _pump(900)
    assert i18n._CURRENT_LANG == "zh"
    restored = _chinese_per_tab(window)
    assert restored == baseline, (
        "切回中文后与初始不一致："
        + str({k: (baseline[k], restored[k]) for k in baseline if baseline[k] != restored[k]})
    )
    window.hide()
