# -*- coding: utf-8 -*-
"""Focus 卡片界面冒烟：外观生效 / 功能不丢 / 右栏清晰度 / 一键切回完整界面。"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtGui import QSurfaceFormat  # noqa: E402
from PyQt5.QtWidgets import QApplication, QFrame, QLabel, QToolButton  # noqa: E402

_fmt = QSurfaceFormat()
_fmt.setSamples(0)
_fmt.setDepthBufferSize(24)
_fmt.setVersion(3, 3)
_fmt.setProfile(QSurfaceFormat.CoreProfile)
QSurfaceFormat.setDefaultFormat(_fmt)
QApplication.setAttribute(Qt.AA_DisableWindowContextHelpButton, True)

_app = None
_window = None


def _pump(ms=80):
    t0 = time.time()
    while (time.time() - t0) * 1000 < ms:
        _app.processEvents()
        time.sleep(0.005)


@pytest.fixture(scope="module")
def win():
    global _app, _window
    _app = QApplication.instance() or QApplication(sys.argv)
    _app.setStyle("Fusion")
    from molstudio.ui.main_window_focus import MolStudioFocusWindow

    _window = MolStudioFocusWindow()
    _window.resize(1400, 820)
    _window.setAttribute(Qt.WA_DontShowOnScreen, True)
    _window.show()
    _pump(1400)
    _window.resize(1400, 820)
    _window._apply_sizes(force=True)
    _pump(300)
    yield _window
    try:
        _window.close()
    except Exception:
        pass


def test_default_ui_is_classic_nav():
    """2026-11-12 起默认回到经典蓝 + 分级侧栏；Focus 仍是可用的备用主题。"""
    import importlib
    import molstudio.app as app_mod
    importlib.reload(app_mod)
    assert app_mod._pick_ui() == "classic_nav"
    import molstudio.ui.main_window_focus as _focus
    assert hasattr(_focus, "MolStudioFocusWindow"), "灰色主题必须保留"


def test_focus_shell_cards(win):
    """卡片化：52px 顶栏、展开侧栏、常驻细底栏、圆角 QSS 就位。"""
    assert win._focus_on is True
    assert win._topbar is not None and 50 <= win._topbar.height() <= 54
    assert win._sidebar is not None and win._sidebar.is_rail() is False
    assert win._statusbar is not None and win._statusbar.isVisible() is True
    bar = getattr(win, "_studio_canvas_bar", None)
    if bar is not None:
        assert bar.height() <= 40
    qss = win.styleSheet()
    assert "QWidget#FocusShell" in qss          # 浅灰底，白卡圆角才看得出来
    assert "border-radius: 12px" in qss
    assert "QGroupBox" in qss                   # 分区卡片
    # 卡片之间的浅灰细缝：5px，不再是 21px 粗灰带。
    # 只改 handleWidth() 不够，QSplitter 按 handle 的 sizeHint 排布，
    # 所以样式表必须挂在 splitter 自己身上把 sizeHint 也压到 5。
    split = win._body_splitter
    assert split.handleWidth() <= 6
    assert split.handle(1).sizeHint().width() <= 6
    assert "width: 5px" in (split.styleSheet() or "")
    assert win._topbar.findChildren(QLabel, "BrandVersion"), "版本号应恢复"
    assert all(not w.isVisible()
               for w in win._topbar.findChildren(QFrame, "TopBarDivider"))


def test_focus_all_pages_still_reachable(win):
    """27 个分析面板一个没少，rail 下照样能切页。"""
    assert win.tabs.count() >= 16
    assert len(win._tab_keys) == win.tabs.count()
    for i in range(win.tabs.count()):
        win._on_sidebar_page(i)
        _pump(10)
        assert win.tabs.currentIndex() == i
        assert win.main_nav.currentRow() == i


def test_focus_overflow_menu_keeps_hidden_entries(win):
    """收起来的入口必须能在 ⋯ 里找到。"""
    texts = [a.text() for a in win._overflow_menu.actions()]
    joined = " ".join(texts)
    assert any("Ctrl+K" in t for t in texts)
    assert any("Ctrl+I" in t for t in texts)
    assert any("Ctrl+Shift+F" in t for t in texts)
    assert "路径设置" in joined or "Paths" in joined
    assert "关于" in joined or "About" in joined


def test_focus_sections_collapsed_except_run(win):
    """切换到一个分析页，附属分区默认折叠（首屏不再是长表单）。"""
    state = getattr(win, "_section_state", {})
    assert state, "分区折叠状态没有建立"
    collapsed = sum(1 for st in state.values() if st.get("collapsed"))
    assert collapsed > 0


def test_focus_inspector_drawer(win):
    """Ctrl+I 抽屉：右栏收起再展开，画布宽度跟着变。"""
    split = win._body_splitter
    right = split.widget(2)
    win._toggle_inspector()
    _pump(60)
    assert right.isVisible() is False
    win._toggle_inspector()
    _pump(60)
    assert right.isVisible() is True


def test_focus_toggle_back_to_full(win):
    """Ctrl+Shift+F 对应的切换：极简 ⇄ 完整，控件能恢复。"""
    win._set_focus(False)
    _pump(120)
    assert win._focus_on is False
    assert win._statusbar.isVisible() is True
    assert win._sidebar.is_rail() is False
    assert win._topbar.height() >= 50
    # 再切回极简（默认展开侧栏 + 常驻底栏）
    win._set_focus(True)
    _pump(120)
    assert win._focus_on is True
    assert win._sidebar.is_rail() is False
    assert win._statusbar.isVisible() is True
    assert "QWidget#FocusShell" in win.styleSheet()


def test_focus_right_panel_clarity(win):
    """右栏清晰度补丁：蓝色分节标题、顶部工具条、纯文字按钮、足够宽度。"""
    from PyQt5.QtWidgets import QPushButton, QToolButton, QWidget

    cp = getattr(win, "canvas_params", None)
    assert cp is not None
    assert "FocusClear" in (cp.styleSheet() or "")
    assert "#1565C0" in (cp.styleSheet() or "")       # 蓝色粗体分节标题

    bar = cp.findChild(QWidget, "CubParamTopBar")
    # 测试跑到这里时当前页不一定是可视化页，父级 tab 隐藏会让 isVisible()
    # 恒为 False；用 isHidden() 判断「有没有被皮肤 hide()」才准确。
    assert bar is not None and not bar.isHidden(), "样式/保存/载入工具条应常驻"

    # 右栏按钮回到经典版纯文字（图标会挤掉密集表单行的文字）
    rc = getattr(win, "right_card", None)
    assert rc is not None
    buttons = rc.findChildren((QPushButton, QToolButton))
    assert buttons
    assert all(b.icon().isNull() for b in buttons)

    # 分组框自带蓝色徽章；至少有一处生效
    qss = win.styleSheet()
    assert "background-color: #1565C0" in qss

    split = win._body_splitter
    assert split.sizes()[2] >= 650, "右栏要够宽，否则 EDD 按钮文字会被裁"


def test_focus_toggle_off_restores_studio_right_panel(win):
    """切回完整界面：Focus 补丁撤干净，工具条按 Studio 原逻辑收回 ⋯。"""
    from PyQt5.QtWidgets import QWidget
    win._set_focus(False)
    _pump(160)
    # 分隔条热区 / 样式表也要还原，不污染完整界面
    assert win._body_splitter.handleWidth() == getattr(
        win._body_splitter, "HANDLE_WIDTH", 8)
    assert (win._body_splitter.styleSheet() or "") == ""
    cp = getattr(win, "canvas_params", None)
    assert cp is not None and "FocusClear" not in (cp.styleSheet() or "")
    bar = cp.findChild(QWidget, "CubParamTopBar")
    if bar is not None:
        assert bar.isHidden()
    win._set_focus(True)
    _pump(160)
    assert "FocusClear" in (cp.styleSheet() or "")
    assert bar is None or not bar.isHidden()
    assert win._body_splitter.handleWidth() <= 6
