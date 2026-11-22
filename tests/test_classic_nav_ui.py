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


def test_spin_population_table_summary_and_csv(win, tmp_path, monkeypatch):
    """自旋密度入口下必须列出逐原子 α−β、绝对值和占比，并可导出。"""
    result = {
        "ok": True,
        "method": "Hirshfeld*",
        "atoms": [
            {"index": 1, "element": "C", "value": 0.25,
             "abs_value": 0.25, "percent_abs": 20.0},
            {"index": 2, "element": "O", "value": -1.00,
             "abs_value": 1.00, "percent_abs": 80.0},
        ],
        "sum": -0.75,
        "sum_abs": 1.25,
        "expected_spin_population": -1.0,
        "integration_error": 0.25,
        "log_path": str(tmp_path / "mol_spin_population.log"),
        "source_path": str(tmp_path / "mol.fchk"),
    }
    win._apply_spin_population_result(result)
    table = win.spin_population_table
    assert win.orbital_tabs.indexOf(win.spin_population_page) >= 0
    assert win.orbital_tabs.tabText(
        win.orbital_tabs.indexOf(win.spin_population_page)) == "自旋布居"
    assert table.rowCount() == 2
    assert table.item(0, 0).text() == "1"
    assert table.item(0, 1).text() == "C"
    assert table.item(0, 2).text() == "+0.25000000"
    assert table.item(1, 2).text() == "-1.00000000"
    assert table.item(1, 3).text() == "1.00000000"
    assert table.minimumHeight() >= 220
    assert win.spin_population_metric_values["sum"].text() == "-0.75000000"
    assert win.spin_population_metric_values["abs"].text() == "1.25000000"
    assert win.spin_population_metric_values["expected"].text() == "-1.00000000"
    assert win.spin_population_metric_values["error"].text() == "+0.25000000"
    assert "积分总和与体系" in win.lbl_spin_population_summary.text()
    assert win.btn_spin_population_export.isEnabled()

    captured = {}

    def _fake_save(_parent, _caption, default, _filt):
        captured["default"] = default
        return str(tmp_path / "spin.csv"), _filt

    monkeypatch.setattr(
        "molstudio.ui.main_window.QFileDialog.getSaveFileName",
        staticmethod(_fake_save))
    win._export_spin_population_csv()
    lines = (tmp_path / "spin.csv").read_text(
        encoding="utf-8-sig").splitlines()
    assert lines[0] == "原子,元素,α−β,|α−β|,占比 (%)"
    assert lines[1] == "1,C,0.25,0.25,20"
    assert captured["default"].endswith("mol_spin_population.csv")


def test_vmd_console_exposes_softbox_style(win):
    index = win.var_style.findText("  softbox")
    assert index >= 0
    tooltip = win.var_style.itemData(index, Qt.ToolTipRole) or ""
    assert "Softbox" in tooltip


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
    assert texts == ["Softbox", "sob-art", "HoukMol3d", "2D 平涂"]

    # 开箱样式是 ultra-glass（既不在四条常用胶囊里、也不在全部样式按钮里）：
    # 此时**一条都不该高亮**。退回去点亮第一条会让屏幕上那个高亮说谎。
    assert bar._canvas_style_name() == "ultraglass"
    assert not any(chip.property("active") for chip, _src in bar._chips), \
        "当前样式不在胶囊里时不该有高亮"
    bar._refresh_style_menu()
    checked = [act.text() for act, src in bar._style_acts if act.isChecked()]
    assert checked == [], f"样式不在快捷列表里就不该勾任何一条：{checked}"

    # 点 sob-art 胶囊 → 只有它高亮，样式菜单也勾到它
    next(chip for chip, _src in bar._chips if chip.text() == "sob-art").click()
    _pump(60)
    states = [bool(chip.property("active")) for chip, _src in bar._chips]
    assert states == [False, True, False, False], f"点完高亮不对：{states}"
    checked = [act.text() for act, src in bar._style_acts if act.isChecked()]
    assert checked == ["sob-art"], f"菜单没跟上胶囊：{checked}"

    # Softbox 是出图观感型快捷样式：点一次同时切材质、背景和 3× AA。
    bar._chips[0][0].click()
    _pump(120)
    states = [bool(chip.property("active")) for chip, _src in bar._chips]
    assert states == [True, False, False, False], f"Softbox 高亮不对：{states}"
    assert win.cub_canvas.glw._active_look_key == "reference-gloss"
    assert win.cub_canvas.glw._sp.get("env_softbox") == 1
    assert win.cub_canvas.glw.get_postprocess()["scale"] == 3.0
    checked = [act.text() for act, src in bar._style_acts if act.isChecked()]
    assert checked == ["Softbox"], f"菜单没跟上 Softbox：{checked}"

    # Lemon 是第二套出图观感；通过样式菜单选择后它会成为唯一高亮项。
    lemon = next(act for act, _src in bar._style_acts if act.text() == "Lemon")
    lemon.trigger()
    _pump(120)
    assert win.cub_canvas.glw._active_look_key == "lemon-orbital"
    assert win.cub_canvas.glw._pc == pytest.approx((0.96, 0.90, 0.36),
                                                   abs=5e-3)
    assert win.cub_canvas.glw._nc == pytest.approx((0.50, 0.84, 0.46),
                                                   abs=5e-3)
    checked = [act.text() for act, src in bar._style_acts if act.isChecked()]
    assert checked == ["Lemon"], f"菜单没跟上 Lemon：{checked}"


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
    fmt_actions = [a.text() for a in bar._export_btn.menu().actions()]
    assert "GLB" in fmt_actions, "PowerPoint 3D 格式没进入画布导出下拉"

    # 显示菜单里「保留 H 编号」输入框也要在，且标签不重复
    disp_rows = _menu_rows(bar._display_btn)
    assert disp_rows, "保留 H 编号输入框丢了"
    keep_labels = disp_rows[-1][1]
    assert sum("H" in t for t in keep_labels) <= 1, "标签重复了两次"

    # 三个菜单都要显示 tooltip：只看名字容易误判（透明背景只在导出时生效、
    # 保留 H 编号要先勾隐藏氢原子）
    for btn in (bar._style_btn, bar._display_btn, bar._export_btn):
        assert btn.menu().toolTipsVisible(), f"{btn.text()} 的 tooltip 被关掉了"


def test_canvas_bar_display_menu_items_really_apply(win):
    """「显示 ▾」每一项都要真的落到画布（回归：点了没反应）。

    2026-11-21 反馈「显示 / 导出里面的按钮都完全没有用」。根因是菜单项用
    ``blockSignals`` 只改原 QCheckBox 的 checked：业务槽全连在 ``toggled`` 上
    （``_on_hide_hydrogens`` / ``_on_atom_label_idx`` / ``_on_atom_label_sym``），
    信号被 block 掉，画布一点没变。这里按「原控件 toggled 有没有发出」逐项锁定。
    """
    from PyQt5.QtTest import QSignalSpy

    bar = _canvas_bar(win)
    cub = win.cub_canvas
    assert len(bar._display_acts) >= 4, "显示菜单项丢了"

    for act, chk in bar._display_acts:
        before = bool(chk.isChecked())
        spy = QSignalSpy(chk.toggled)
        act.setChecked(not before)
        _pump(40)
        assert len(spy) == 1, (
            f"「{act.text()}」点了没反应：原控件 toggled 没发出"
            f"（checkbox={chk.isChecked()}）")
        act.setChecked(before)
        _pump(40)

    # 隐藏氢原子：状态要真的落到 GL 画布（不是只改勾）
    hide_act, hide_chk = next((a, c) for a, c in bar._display_acts
                              if c is cub._hide_h_chk)
    was = bool(cub.glw._hide_hydrogens)
    hide_act.setChecked(not was)
    _pump(40)
    assert bool(cub.glw._hide_hydrogens) is (not was), "勾了隐藏氢原子，画布没变"
    hide_act.setChecked(was)
    _pump(40)
    assert bool(cub.glw._hide_hydrogens) is was, "取消隐藏氢原子，画布没回来"

    # 原子编号 / 元素符号互斥：菜单的勾要跟着原控件的真实状态走
    idx_act, idx_chk = next((a, c) for a, c in bar._display_acts
                            if c is cub._lbl_idx_chk)
    sym_act, sym_chk = next((a, c) for a, c in bar._display_acts
                            if c is cub._lbl_sym_chk)
    idx_before, sym_before = bool(idx_chk.isChecked()), bool(sym_chk.isChecked())
    idx_act.setChecked(True)
    _pump(40)
    assert not sym_chk.isChecked(), "开编号时元素符号没关（原控件互斥失效）"
    assert not sym_act.isChecked(), "菜单里元素符号还勾着（勾没跟上原控件）"
    idx_act.setChecked(idx_before)
    if sym_before:
        sym_act.setChecked(True)
    _pump(40)


def test_canvas_bar_export_menu_items_really_apply(win, monkeypatch):
    """「导出 ▾」的每一项都要真的动到原控件/画布（回归：点了没反应）。"""
    from PyQt5.QtTest import QSignalSpy

    bar = _canvas_bar(win)
    cub = win.cub_canvas
    menu = bar._export_btn.menu()
    texts = [a.text() for a in menu.actions()]

    # ① 测量开关：菜单的勾要真的把画布切进测量模式（同样死在 blockSignals 上）
    assert bar._measure_act is not None
    spy = QSignalSpy(cub._measure_btn.toggled)
    bar._measure_act.setChecked(True)
    _pump(40)
    assert len(spy) == 1, "勾「测量」时原按钮没收到 toggled"
    assert cub._measure_btn.isChecked(), "菜单勾了测量，原按钮没跟着勾"
    assert bool(cub.glw._measure_mode), "菜单勾了测量，画布没进测量模式"
    bar._measure_act.setChecked(False)
    _pump(40)
    assert not bool(cub.glw._measure_mode), "取消测量后画布还停在测量模式"

    # ② 导出格式：改下拉，且导出按钮文字跟着 PNG ↔ 3D 变
    assert [a.text() for a, _i in bar._fmt_acts] == ["PNG", "JPG", "TIFF",
                                                     "SVG", "GLB"]
    old_idx = cub._export_cb.currentIndex()
    try:
        for act, idx in bar._fmt_acts:
            act.trigger()
            _pump(20)
            assert cub._export_cb.currentIndex() == idx, f"{act.text()} 没选中"
            assert [a.isChecked() for a, _j in bar._fmt_acts].count(True) == 1, \
                "导出格式必须是单选"
        glb = next(a for a, i in bar._fmt_acts if i == 4)
        glb.trigger()
        _pump(40)
        assert cub._export_btn.text() in ("导出3D", "Export 3D"), \
            f"选 GLB 后导出按钮文字没变：{cub._export_btn.text()}"
    finally:
        cub._export_cb.setCurrentIndex(old_idx)
        _pump(20)

    # ③ 测量类型：三个都在，点了改下拉
    assert [a.text() for a, _i in bar._kind_acts][:3] == ["距离", "键角", "二面角"]
    for act, idx in bar._kind_acts[:3]:
        act.trigger()
        _pump(20)
        assert cub._measure_kind_cb.currentIndex() == idx, f"{act.text()} 没生效"

    # ④ 截图 / 导出图片：必须点到原按钮（保存对话框用探针替掉，不弹窗）
    import molstudio.render.ovcanvas._panel as panel_mod

    saved = []

    def _fake_save(parent, title, default, filt, *a, **k):
        saved.append((title, default))
        return "", ""

    monkeypatch.setattr(panel_mod, "save_file", _fake_save)
    shot = next(a for a in menu.actions() if a.text() == "截图")
    shot.trigger()
    _pump(40)
    assert saved, "点「截图」没有走到保存流程"
    assert saved[-1][0].startswith("保存截图"), saved[-1]

    exported = []
    monkeypatch.setattr(cub, "_export_image",
                        lambda fmt, *a, **k: exported.append(fmt))
    exp = next(a for a in menu.actions() if a.text() == "导出图片")
    exp.trigger()
    _pump(40)
    assert exported, "点「导出图片」没有走到导出流程"

    # ⑤ 清除 / 同步到 VMD：必须点到原按钮
    cleared, synced = [], []
    monkeypatch.setattr(cub.glw, "clear_measure_items",
                        lambda *a, **k: cleared.append(1))
    monkeypatch.setattr(cub, "on_sync_vmd", lambda: synced.append(1))
    next(a for a in menu.actions() if a.text() == "清除").trigger()
    _pump(40)
    assert cleared, "点「清除」没有清测量标注"
    next(a for a in menu.actions() if a.text() == "同步到VMD").trigger()
    _pump(40)
    assert synced, "点「同步到VMD」没有回调"

    # ⑥ 导出设置：观感下拉与 DPI 输入框仍是原控件、还能读
    assert any("观感" in t for _w, labs in _menu_rows(bar._export_btn)
               for t in labs)
    assert any("DPI" in t.upper() for _w, labs in _menu_rows(bar._export_btn)
               for t in labs)
    assert cub._dpi_edit.text().strip(), "DPI 输入框丢了内容"
    assert "导出格式" in texts and "导出设置" in texts


def test_log_dock_arrow_and_drag(win):
    """运行日志：上边缘拖动条能调高度，箭头能真的收起（回归两个问题）。

    1. ``QToolButton.clicked`` 会带一个 ``checked=False``，直接连
       ``_toggle_log_dock`` 会把 False 当 collapsed → 永远「展开」；
    2. 日志正文被 ``RunLogConsole`` 摘进页签后，只藏 log_text 页签仍占高度，
       收起看起来毫无反应。
    """
    grip = getattr(win, "_log_grip", None)
    assert grip is not None, "画布与日志之间没有拖动条"
    dock = win.log_dock
    console = getattr(win, "_ref_log_console", None)
    if getattr(win, "_log_collapsed", False):
        win._toggle_log_dock(False)
        _pump(60)

    # 拖动条在画布下方、日志上方
    top = dock.mapTo(win, dock.rect().topLeft()).y()
    bottom = win.cub_canvas.mapTo(win, win.cub_canvas.rect().bottomLeft()).y()
    assert top >= bottom - 2, "拖动条/日志被排到画布上面去了"

    h_canvas = win.cub_canvas.height()
    win._log_toggle_btn.click()          # 用户点的就是这条箭头
    _pump(80)
    assert win._log_collapsed, "点箭头没有收起（clicked 的 checked 被当成 collapsed 了）"
    assert not win.log_text.isVisible()
    if console is not None:
        assert not console.isVisible(), "页签容器还占着高度，看起来就像没反应"
    assert win.cub_canvas.height() > h_canvas, "收起后画布没拿回高度"
    assert win._log_toggle_btn.collapsed(), "收起后箭头没朝上"

    win._log_toggle_btn.click()
    _pump(80)
    assert not win._log_collapsed and win.log_text.isVisible(), "再点没有展开"

    # 拖动：往上 60px → 日志更高
    h0 = win.log_text.height()
    win._on_log_grip_start()
    win._on_log_grip_move(60)
    win._on_log_grip_end()
    _pump(60)
    assert win.log_text.height() >= h0 + 40, "往上拖日志没变高"
    # 往下拖 → 变矮
    h1 = win.log_text.height()
    win._on_log_grip_start()
    win._on_log_grip_move(-50)
    win._on_log_grip_end()
    _pump(60)
    assert win.log_text.height() <= h1 - 30, "往下拖日志没变矮"
    # 双击复位
    win._reset_log_height()
    _pump(60)
    assert win.log_text.height() == 144, "复位没回到默认高度"


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
