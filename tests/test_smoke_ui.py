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


def test_startup_poem_is_framed_and_centered():
    """启动诗词：整块字符框、框内居中，且居中格式不泄漏到后面的日志行。"""
    os.environ["MOLSTUDIO_POEM"] = "咏梅"      # 固定一首，内容才可预期
    try:
        w = _window()
        try:
            doc = w.log_text.document()
            blocks = [doc.findBlockByNumber(i) for i in range(doc.blockCount())]
            texts = [b.text() for b in blocks]

            def _find(needle):
                for k, t in enumerate(texts):
                    if needle in t:
                        return k
                raise AssertionError(f"日志里找不到 {needle!r}；末尾内容：{texts[-16:]}")

            ti, mi, bi = _find("卜算子·咏梅"), _find("毛泽东"), _find("风雨送春归")
            for k, what in ((ti, "标题"), (mi, "作者"), (bi, "正文")):
                assert texts[k].startswith("│") and texts[k].endswith("│"), \
                    f"{what}行不在字符框内：{texts[k]!r}"
                assert blocks[k].blockFormat().alignment() & Qt.AlignHCenter, \
                    f"{what}行应当居中：{texts[k]!r}"
                # 框内不许混入半角字符：半角与全角宽度不同，框线会参差
                assert not any(ord(c) < 0x80 for c in texts[k]), \
                    f"{what}行混入了半角字符：{texts[k]!r}"
            assert texts[ti - 1].startswith("┌"), f"标题上方应有上框线：{texts[ti - 1]!r}"
            assert any(t.startswith("└") for t in texts[bi + 1:]), "正文下方应有下框线"
        finally:
            w.hide()
    finally:
        os.environ.pop("MOLSTUDIO_POEM", None)
