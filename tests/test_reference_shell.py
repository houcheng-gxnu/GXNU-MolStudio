# -*- coding: utf-8 -*-
"""默认界面「参考稿外壳」回归：顶栏 / 画布头 / 属性卡片 / 日志三页签 / 状态栏 / 工具卡片。

    pytest tests/test_reference_shell.py -q
"""

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtGui import QSurfaceFormat  # noqa: E402
from PyQt5.QtWidgets import QApplication, QFrame  # noqa: E402

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
    from molstudio.ui.main_window_classic_nav import MolStudioClassicNavWindow

    _window = MolStudioClassicNavWindow()
    _window.resize(1680, 1000)
    _window.setAttribute(Qt.WA_DontShowOnScreen, True)
    _window.show()
    _pump(2400)
    yield _window
    try:
        _window.close()
    except Exception:
        pass


def test_reference_topbar_replaces_input_panel(win):
    bar = win.grp_input
    assert isinstance(bar, QFrame)
    assert bar.objectName() == "RefTopBar"
    # 原「输入文件」大面板已退出布局但保留对象（结构库/PPT3D 按钮仍被引用）
    legacy = getattr(win, "_ref_legacy_topbar", None)
    assert legacy is not None and legacy.isHidden()
    # 文件 chip / 打开 / 截图 / 保存图片 / 测量 / 重置视角 都在
    assert win.var_path.parentWidget() is bar
    for key in ("open", "snapshot", "export", "measure", "reset"):
        btn = win._ref_tool_buttons.get(key)
        assert btn is not None and btn.parentWidget() is bar
    assert win.btn_molecule_library.isHidden()
    assert win.btn_ppt3d.isHidden()


def test_canvas_header_and_cards_toggle(win):
    assert win._ref_canvas_header is not None
    assert win._ref_canvas_header.parentWidget() is win.grp_canvas
    cards = getattr(win, "_ref_cards", None)
    assert cards is not None, "画布工具卡片未安装"
    assert cards.isHidden(), "工具卡片默认收起（保留经典紧凑条与画布高度）"
    assert win._ref_cards_btn is not None
    # 展开 → 四张卡片出现，42px 紧凑条收起
    win._ref_cards_btn.setChecked(True)
    win._toggle_canvas_cards(True)
    _pump(120)
    assert cards.isVisible() and cards.height() > 40
    bar = getattr(win, "_studio_canvas_bar", None)
    if bar is not None:
        assert bar.isHidden()
    # 收起 → 紧凑条回来
    win._ref_cards_btn.setChecked(False)
    win._toggle_canvas_cards(False)
    _pump(80)
    assert cards.isHidden()
    if bar is not None:
        assert bar.isVisible()


def test_orca_entry_available(win):
    btn = getattr(win, "_ref_orca_btn", None)
    assert btn is not None, "默认界面顶栏缺少 ORCA 入口"
    assert btn.text() == "ORCA"
    assert btn.toolTip()
    assert getattr(win, "orca_panel", None) is not None
    assert "tab_orca" in win._tab_keys
    # 顶栏按钮应跳到左侧「常用」下的 ORCA 页
    btn.click()
    _pump(150)
    assert win._tab_keys[win.tabs.currentIndex()] == "tab_orca"


def test_property_card_and_quick_info(win):
    card = getattr(win, "_ref_props", None)
    assert card is not None, "右侧属性卡片未安装"
    # 属性信息是右侧独立的第一个页签（属性信息 / 设置 / 引文）
    assert win.right_tabs.count() == 3
    assert win.right_tabs.tabText(0) in ("属性信息", "Properties")
    assert win.right_tabs.tabText(1) in ("设置", "Settings")
    assert win.right_tabs.tabText(2) in ("引文", "Citations")
    assert win.right_tabs.widget(0) is getattr(win, "_ref_prop_page", None)
    assert card.parentWidget() is not win.right_card
    assert getattr(win, "_ref_prop_load_btn", None) is not None
    # 未载入文件时全为占位符
    card.clear()
    assert card.value_labels["energy"].text() == "—"
    fchk = r"D:\test-est\DA-5.fchk"
    if not os.path.isfile(fchk):
        pytest.skip("DA-5.fchk 不存在")
    win.var_path.setText(fchk)
    win._load_molecule(fchk)
    _pump(120)
    assert card.value_labels["formula"].text() == "C6H10"
    assert "Hartree" in card.value_labels["energy"].text()
    assert card.value_labels["method"].text().upper().startswith("RM06L")
    assert card.value_labels["homo"].text() != "—"


def test_runlog_tabs_filter_by_level(win):
    console = getattr(win, "_ref_log_console", None)
    assert console is not None, "日志三页签未安装"
    assert console.tabs.count() == 3
    console.clear_all()
    win._append_log("SCF Done: E(RM06L) = -234.335136146")
    win._append_log("Error termination: something failed")
    _pump(80)
    assert "SCF Done" in console.output_text.toPlainText()
    assert "Error termination" in console.error_text.toPlainText()
    # 运行日志本身仍走父类 log_text
    assert "SCF Done" in win.log_text.toPlainText()


def test_statusbar_labels(win):
    sb = getattr(win, "_ref_statusbar", None)
    assert sb is not None
    assert win._ref_ver_label is not None and "MolStudio" in win._ref_ver_label.text()
    assert win._ref_cpu_label is not None and "CPU" in win._ref_cpu_label.text()
    assert win._ref_mem_label is not None and "内存" in win._ref_mem_label.text()


def test_library_page_still_shows_its_own_tabs(win):
    """结构库页隐藏右侧全局页签栏时，必须回到「设置」页而不是属性页。"""
    assert "tab_library" in win._tab_keys
    idx = win._tab_keys.index("tab_library")
    win._on_sidebar_page(idx)
    _pump(250)
    assert win.tabs.currentIndex() == idx
    # 0 号页签是属性信息，结构库页必须切到 right_card（设置）所在的下标
    assert win.right_tabs.currentIndex() == win._ref_settings_tab_index()
    assert not win.right_tabs.tabBar().isVisible()
    if getattr(win, "library_panel", None) is not None:
        assert win.tabs.currentWidget() is win.library_panel
    win._on_sidebar_page(0)
    _pump(250)
    assert win.right_tabs.tabBar().isVisible()


def test_shell_survives_language_switch(win):
    win._switch_lang()
    _pump(400)
    win._apply_lang_ui()
    _pump(200)
    assert win.grp_input.objectName() == "RefTopBar"
    assert win._ref_tool_buttons["open"].text() in ("打开", "Open")
    # 右栏三个页签也要跟着切
    texts = [win.right_tabs.tabText(i) for i in range(win.right_tabs.count())]
    assert texts[0] in ("属性信息", "Properties")
    assert texts[1] in ("设置", "Settings")
    assert texts[2] in ("引文", "Citations")
    win._switch_lang()
    _pump(400)
