# -*- coding: utf-8 -*-
"""默认界面冒烟：经典蓝色主题 + 分组侧栏，且灰色 Focus 主题仍完整保留。"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

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
    _window.resize(1560, 900)
    _window.setAttribute(Qt.WA_DontShowOnScreen, True)
    _window.show()
    _pump(1600)
    yield _window
    try:
        _window.close()
    except Exception:
        pass


def test_default_ui_is_classic_nav():
    """默认启动 = 经典蓝 + 分级侧栏；focus / classic 仍是有效开关。"""
    import importlib
    import molstudio.app as app_mod
    importlib.reload(app_mod)
    assert app_mod._pick_ui() == "classic_nav"
    old = sys.argv[:]
    try:
        for ui in ("focus", "classic", "studio", "clean", "clean2", "canvas"):
            sys.argv[:] = ["main.py", "--ui", ui]
            assert app_mod._pick_ui() == ui
    finally:
        sys.argv[:] = old


def test_classic_blue_theme_kept(win):
    """主题必须是 classic 的 LIGHT_QSS，不是 Studio / Focus 的中性灰。"""
    qss = win.styleSheet()
    assert "#1565C0" in qss                 # 经典蓝分节徽章 / 主题色
    assert "QWidget#FocusShell" not in qss  # 没有 Focus 的灰色卡片壳
    assert "border-radius: 12px" not in qss or "FocusCard" not in qss


def test_group_sidebar_installed(win):
    """第 0 栏换成分组侧栏，main_nav 留作隐藏状态模型。"""
    from molstudio.ui.studio_sidebar import StudioSidebar

    split = win._body_splitter
    assert isinstance(split.widget(0), StudioSidebar)
    assert win._sidebar is not None
    assert win._sidebar.is_rail() is False
    assert win.main_nav is not None
    assert win.main_nav.count() == win.tabs.count()
    # 分组定义来自 GROUP_DEFS，至少 6 组
    groups = win._build_sidebar_groups()
    assert len(groups) >= 6
    assert sum(len(entries) for _t, entries in groups) >= win.tabs.count()
    # 侧栏自带蓝色主题皮肤
    assert "ClassicNav" in (win._sidebar.styleSheet() or "")


def test_all_pages_reachable_via_sidebar(win):
    """27 个分析面板一个没少，分组项点击照样切页 + 高亮。"""
    assert win.tabs.count() >= 16
    for i in range(win.tabs.count()):
        win._on_sidebar_page(i)
        _pump(8)
        assert win.tabs.currentIndex() == i
        assert win.main_nav.currentRow() == i
    win._on_sidebar_page(0)
    _pump(20)


def test_right_panel_width_matches_classic(win):
    """侧栏从 122 → 232 不许挤窄右栏，否则 EDD 表单文字会被裁。"""
    sizes = win._body_splitter.sizes()
    assert sizes[0] == 232, "分级侧栏展开宽度"
    assert sizes[2] >= 700, "右栏必须保持经典版的 ~764px"


def test_footer_buttons_moved_below_version(win):
    """「路径设置 / 关于」搬到侧栏版本文字下方，顶栏不再有这两个按钮。"""
    sb = win._sidebar
    lay = sb.layout()
    pos = {}
    for i in range(lay.count()):
        w = lay.itemAt(i).widget()
        if w is not None:
            pos[w] = i

    for btn in (win.btn_paths, win.btn_about):
        assert btn.parentWidget() is sb, "按钮必须 reparent 到侧栏"
        assert btn.parentWidget() is not win.grp_input, "顶栏输入行应已移除"
        assert not btn.isHidden()
    # 顺序：版本文字 → 路径设置 → 关于
    bottom = getattr(sb, "_bottom", None)
    if bottom is not None and bottom in pos:
        assert pos[bottom] < pos[win.btn_paths] < pos[win.btn_about]
    # 短名：232px 侧栏里不能出现被裁掉一半的长文字
    assert win.btn_paths.text() == "路径设置"
    assert win.btn_about.text() == "关于 MolStudio"
    assert win.btn_paths.toolTip(), "完整说明应留在 tooltip"
    # 原信号连线仍在（reparent 不会断开 clicked）
    assert win.btn_paths.receivers(win.btn_paths.clicked) >= 1
    assert win.btn_about.receivers(win.btn_about.clicked) >= 1


def test_footer_buttons_hidden_in_rail(win):
    """56px rail 下放不下文字按钮，跟版本文字一起收起；展开后恢复。"""
    win._sidebar.set_rail(True)
    _pump(40)
    assert win.btn_paths.isHidden() and win.btn_about.isHidden()
    win._sidebar.set_rail(False)
    _pump(40)
    assert not win.btn_paths.isHidden() and not win.btn_about.isHidden()
    win._sync_group_nav()


def test_topbar_library_and_ppt3d_hidden(win):
    """「结构库 / PPT 3D」从顶栏收掉；刷新语言后仍保持隐藏。"""
    assert win.btn_molecule_library.isHidden()
    assert win.btn_ppt3d.isHidden()
    win._apply_lang_ui()
    _pump(20)
    assert win.btn_molecule_library.isHidden()
    assert win.btn_ppt3d.isHidden()


def test_library_still_reachable_from_sidebar(win):
    """顶栏结构库按钮只是切 tab，侧栏「常用」组里必须有等价入口。"""
    groups = win._build_sidebar_groups()
    texts = [(e["key"], e["index"]) for _t, items in groups for e in items]
    assert ("tab_library", win._tab_keys.index("tab_library")) in texts
    win._on_sidebar_page(win._tab_keys.index("tab_library"))
    _pump(20)
    assert win._tab_keys[win.tabs.currentIndex()] == "tab_library"
    win._on_sidebar_page(0)
    _pump(20)


def test_ppt3d_action_kept_in_command_palette(win, monkeypatch):
    """PPT 3D 不是功能页，隐藏按钮后必须仍能从 Ctrl+K 触发导出。"""
    entries = win._palette_entries()
    page_payloads = [e[1] for e in entries if isinstance(e[1], int)]
    assert len(page_payloads) >= win.tabs.count()
    actions = [e for e in entries if e[1] == "ppt3d"]
    assert len(actions) == 1
    assert "PPT 3D" in actions[0][0]
    assert len(actions[0]) == 3 and "glb" in actions[0][2]

    called = []
    monkeypatch.setattr(win, "_export_current_ppt3d",
                        lambda: called.append("ppt3d"))
    assert win._run_palette_action("ppt3d") is True
    assert called == ["ppt3d"]
    assert win._run_palette_action("unknown-action") is False
    assert called == ["ppt3d"]


def test_focus_theme_still_available():
    """灰色卡片主题完整保留，没被删、没被改成默认。"""
    import molstudio.app as app_mod
    from molstudio.ui.main_window_focus import MolStudioFocusWindow

    w = app_mod._make_window("focus")
    assert isinstance(w, MolStudioFocusWindow)
    assert w._focus_on is True
    try:
        w.close()
    except Exception:
        pass


def _canvas_bar(win):
    bar = getattr(win, "_studio_canvas_bar", None)
    assert bar is not None, "classic_nav 也要把画布底部卡片压成单行工具条"
    return bar


def _menu_rows(btn):
    """菜单里 QWidgetAction 承载的原控件行 → [(小盒, [行内标签文字])]。"""
    from PyQt5.QtWidgets import QLabel, QWidgetAction

    out = []
    for act in btn.menu().actions():
        if not isinstance(act, QWidgetAction):
            continue
        w = act.defaultWidget()
        if w is not None:
            out.append((w, [(lab.text() or "").strip()
                            for lab in w.findChildren(QLabel)]))
    return out


def test_canvas_bar_collapses_style_card(win):
    """画布底部 320px 的多行设置卡片 → 42px 单行工具条。

    原卡片 7 行 22 个控件（9 个一键样式 + 4 个显示开关 + 观感/DPI/格式/测量/导出）
    把画布吃掉 300 多像素，这是「繁杂」的量化来源。
    """
    bar = _canvas_bar(win)
    assert bar.height() <= 44
    wrap = getattr(win.cub_canvas, "_style_wrap", None)
    assert wrap is not None and wrap.height() > 200
    assert not wrap.isVisible(), "原卡片必须隐藏，否则画布还是被压扁"


def test_canvas_bar_quick_chips(win):
    """常用样式常显在左端；高亮只认真实样式，点了哪条就亮哪条。"""
    bar = _canvas_bar(win)
    texts = [chip.text() for chip, _src in bar._chips]
    assert texts == ["sob-art", "HoukMol3d", "2D 平涂", "IQmol"]

    # 开箱样式是 ultra-glass（既不在四条常用胶囊里、也不在九个样式按钮里）：
    # 此时**一条都不该高亮**。退回去点亮第一条会让屏幕上那个高亮说谎。
    assert bar._canvas_style_name() == "ultraglass"
    assert not any(chip.property("active") for chip, _src in bar._chips), \
        "当前样式不在胶囊里时不该有高亮"
    bar._refresh_style_menu()
    checked = [act.text() for act, src in bar._style_acts if act.isChecked()]
    assert checked == [], f"样式不在九条里就不该勾任何一条：{checked}"

    # 点第一条胶囊 → 只有它高亮，样式菜单也勾到它
    bar._chips[0][0].click()
    _pump(60)
    states = [bool(chip.property("active")) for chip, _src in bar._chips]
    assert states == [True, False, False, False], f"点完高亮不对：{states}"
    checked = [act.text() for act, src in bar._style_acts if act.isChecked()]
    assert checked == ["sob-art"], f"菜单没跟上胶囊：{checked}"


def test_canvas_bar_menus_keep_every_control(win):
    """收进菜单的控件一项不能少：清空样式进样式菜单、观感与 DPI 进更多。"""
    bar = _canvas_bar(win)

    style_acts = [a.text() for a in bar._style_btn.menu().actions()]
    for name in ("sob-art", "VESTA", "清空样式"):
        assert name in style_acts

    # 观感与 DPI 现在并在「导出 ▾」的「导出设置」组里（不再单独占一个按钮）
    export_labels = [t for _w, labs in _menu_rows(bar._export_btn) for t in labs]
    assert any("观感" in t for t in export_labels), "出图观感没搬进导出"
    assert any("DPI" in t.upper() for t in export_labels), "DPI 没搬进导出"

    # 显示菜单里「保留 H 编号」输入框也要在，且标签不重复
    disp_rows = _menu_rows(bar._display_btn)
    assert disp_rows, "保留 H 编号输入框丢了"
    keep_labels = disp_rows[-1][1]
    assert sum("H" in t for t in keep_labels) <= 1, "标签重复了两次"


def test_canvas_bar_chips_fold_when_narrow(win):
    """画布窄到 360px 时先收胶囊，样式/导出这些入口一个都不能被挤掉。"""
    bar = _canvas_bar(win)
    parent_w = bar.width()
    bar.resize(1400, bar.height())
    _pump(60)
    wide = [chip.isVisible() for chip, _s in bar._chips]
    bar.resize(360, bar.height())
    _pump(60)
    narrow = [chip.isVisible() for chip, _s in bar._chips]
    assert sum(wide) == 4, "宽画布下四个胶囊应全部常显"
    # 能放几条放几条：保留的是前缀（从右往左收），不是跳着留。
    # 收掉的那条如果正是当前样式，屏幕上是「一条都没高亮」，不会错亮到别的胶囊。
    assert narrow == sorted(narrow, reverse=True), "胶囊必须按顺序从右往左收起"
    assert sum(narrow) < 4, "360px 下不可能四条都放得下"
    for btn in (bar._style_btn, bar._display_btn, bar._export_btn):
        assert btn is not None and btn.isVisible(), "菜单入口被挤出工具条"
    bar.resize(parent_w, bar.height())
    _pump(60)
