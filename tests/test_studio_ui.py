# -*- coding: utf-8 -*-
"""Studio 界面冒烟：分组侧栏 / 单行顶栏 / 检查器 / 27 页可达 / 切语言。

与 tests/test_smoke_ui.py 同款离屏构建方式；只验证「外壳 + 联动」，
面板内部的业务逻辑由各自的测试覆盖。
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtGui import QSurfaceFormat  # noqa: E402
from PyQt5.QtWidgets import QApplication, QToolButton  # noqa: E402

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
    from molstudio.ui.main_window_studio import MolStudioStudioWindow

    _window = MolStudioStudioWindow()
    _window.resize(1400, 820)
    _window.setAttribute(Qt.WA_DontShowOnScreen, True)
    _window.show()
    _pump(1200)
    # 离屏平台可用屏幕很小，窗口会被 showEvent 收到 1080×620；
    # 这里再放大一次，按真实默认尺寸校验比例。
    _window.resize(1400, 820)
    _window._apply_sizes(force=True)
    _pump(300)
    yield _window
    try:
        _window.close()
    except Exception:
        pass


def test_studio_shell(win):
    """顶栏 / 侧栏 / 检查器 / 状态栏都要就位，旧输入行要退场。"""
    assert win.tabs.count() >= 16, win.tabs.count()
    assert len(win._tab_keys) == win.tabs.count()

    assert win._topbar is not None, "顶栏没建起来"
    assert win._topbar.objectName() == "TopBar"
    assert win.grp_input.isVisibleTo(win) is False, "旧输入行应已隐藏"

    assert win._sidebar is not None, "分组侧栏没建起来"
    items = win._sidebar.findChildren(QToolButton, "NavItem")
    assert len(items) == win.tabs.count(), "侧栏条目应与页面一一对应"

    assert win._inspector_header is not None, "检查器页头没建起来"
    assert win.right_tabs.tabBar().isVisible() is False, "全局页签栏应隐藏"
    assert win._statusbar is not None, "状态栏没建起来"


def test_studio_all_pages_reachable(win):
    """侧栏可以到达每一页（隐藏的 main_nav 仍是状态模型）。"""
    for i in range(win.tabs.count()):
        win._on_sidebar_page(i)
        _pump(15)
        assert win.tabs.currentIndex() == i, f"第 {i} 页没切过去"
        assert win.main_nav.currentRow() == i, f"main_nav 与页面不同步：{i}"


def test_studio_citation_toggle(win):
    """引文从页签变成页头按钮：点一下切引文，再点回参数。"""
    win._on_sidebar_page(0)
    _pump(40)
    assert win.right_tabs.currentIndex() == 0
    win._inspector_cite.click()
    _pump(40)
    assert win.right_tabs.currentIndex() == 1
    assert win._inspector_cite.isChecked() is True
    win._inspector_cite.click()
    _pump(40)
    assert win.right_tabs.currentIndex() == 0


def test_studio_language_roundtrip(win):
    """中英切换后侧栏条目数量不丢、图标仍在。"""
    before = len(win._sidebar.findChildren(QToolButton, "NavItem"))
    win._switch_lang()
    _pump(300)
    after_en = len(win._sidebar.findChildren(QToolButton, "NavItem"))
    win._switch_lang()
    _pump(300)
    after_zh = len(win._sidebar.findChildren(QToolButton, "NavItem"))
    assert before == after_en == after_zh, (before, after_en, after_zh)
    assert win._inspector_title.text(), "语言切换后页头标题为空"


def test_studio_layout_priority(win):
    """画布必须比右栏宽（旧界面是反的：677 > 557）。"""
    sizes = win._body_splitter.sizes()
    assert len(sizes) == 3
    assert sizes[0] == win.SIDEBAR_W, sizes
    assert sizes[1] > sizes[2], f"画布应比右栏宽：{sizes}"
    assert sizes[2] / max(sum(sizes), 1) <= 0.50, sizes


def test_studio_section_collapse(win):
    """附属参数分区默认收起，运行类分区保持展开。"""
    win._on_sidebar_page(0)
    _pump(60)
    states = getattr(win, "_section_state", {})
    assert states, "没有登记任何可折叠分区"
    collapsed = [gb for gb, st in states.items() if st.get("collapsed")]
    assert collapsed, "默认折叠规则没有生效"


def test_studio_ui_selector(monkeypatch):
    """入口开关：--ui studio 能被解析并摘掉，不影响批处理参数。"""
    import molstudio.app as app_mod

    monkeypatch.setattr(sys, "argv", ["main.py", "--ui", "studio"])
    assert app_mod._pick_ui() == "studio"
    assert "--ui" not in sys.argv
    monkeypatch.setattr(sys, "argv", ["main.py", "--ui", "nope"])
    # 无效 / 缺省值一律回落到默认界面
    # （2026-11-12 起默认是 classic_nav：经典蓝色主题 + 分级侧栏）
    assert app_mod._pick_ui() == "classic_nav"
    monkeypatch.setattr(sys, "argv", ["main.py"])
    assert app_mod._pick_ui() == "classic_nav"


def test_studio_sidebar_rail(win):
    """Ctrl+B / 顶栏按钮对应的 rail 折叠：宽度 232 ↔ 56。"""
    win.setAttribute(Qt.WA_DontShowOnScreen, True)
    win._on_sidebar_page(0)
    _pump(80)
    assert win._sidebar.is_rail() is False
    assert win._sidebar.width() == win.SIDEBAR_W
    win._toggle_sidebar_rail()
    _pump(120)
    assert win._sidebar.is_rail() is True
    assert win._sidebar.width() == win.RAIL_W
    win._toggle_sidebar_rail()
    _pump(120)
    assert win._sidebar.is_rail() is False
