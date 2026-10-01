# -*- coding: utf-8 -*-
"""界面冒烟：离屏构建 Clean 界面，遍历全部功能页、切语言、切渲染风格。

    pytest tests -q
"""

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtGui import QSurfaceFormat  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

_fmt = QSurfaceFormat()
_fmt.setSamples(0)
_fmt.setDepthBufferSize(24)
_fmt.setVersion(3, 3)
_fmt.setProfile(QSurfaceFormat.CoreProfile)
QSurfaceFormat.setDefaultFormat(_fmt)
QApplication.setAttribute(Qt.AA_DisableWindowContextHelpButton, True)

_app = None


def _pump(ms=80):
    t0 = time.time()
    while (time.time() - t0) * 1000 < ms:
        _app.processEvents()
        time.sleep(0.005)


def _window():
    global _app
    _app = QApplication.instance() or QApplication(sys.argv)
    _app.setStyle("Fusion")
    from molstudio.ui.main_window_clean import MolStudioCleanWindow

    w = MolStudioCleanWindow()
    w.resize(1280, 660)
    w.setAttribute(Qt.WA_DontShowOnScreen, True)
    w.show()
    _pump(900)
    return w


def test_nav_and_tabs():
    w = _window()
    try:
        assert w.main_nav.count() >= 16, w.main_nav.count()
        assert w.tabs.count() >= 16, w.tabs.count()
        for i in range(w.main_nav.count()):
            w.main_nav.setCurrentRow(i)
            _pump(25)
    finally:
        w.hide()


def test_language_and_style_switch():
    from molstudio.core.fchk_orbital import STYLES

    w = _window()
    try:
        w._switch_lang()
        _pump(200)
        w._switch_lang()
        _pump(200)
        for name in list(STYLES.keys())[:4]:
            w._on_style_changed(name)
            _pump(40)
        # 切完之后皮肤必须还在（导航卡宽度与全局样式表）
        from PyQt5.QtWidgets import QFrame

        nav_card = w.findChild(QFrame, "NavCard")
        assert nav_card is not None
        assert nav_card.width() == 150
    finally:
        w.hide()
