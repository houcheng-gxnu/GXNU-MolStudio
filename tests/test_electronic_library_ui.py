# -*- coding: utf-8 -*-
"""结构库第 3 页「电子结构库」的 UI 回归：页签、筛选、回调、语言。"""
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
    from molstudio import app as app_mod
    _window = app_mod._make_window("classic_nav")
    _window.resize(1560, 900)
    _window.setAttribute(Qt.WA_DontShowOnScreen, True)
    _window.show()
    _pump(1200)
    yield _window
    try:
        _window.close()
    except Exception:
        pass


@pytest.fixture
def lib(win):
    panel = win.library_panel
    assert panel is not None
    panel.sub_tabs.setCurrentIndex(2)
    _pump(30)
    return panel


def test_library_has_five_tabs(win):
    tabs = win.library_panel.sub_tabs
    assert tabs.count() == 5
    texts = [tabs.tabText(i) for i in range(tabs.count())]
    assert any("电子结构" in t for t in texts)
    assert any("分子库" in t for t in texts)
    assert any("晶体库" in t for t in texts)
    assert any("导出设置" in t for t in texts)
    assert any("引文" in t for t in texts)
    # 引文页要说明这不是实验数据、不是 SCF 分子轨道
    assert "解析波函数" in win.library_panel.txt_citation.toHtml()


def test_orbital_tab_controls(lib):
    assert lib.is_orbital_page()
    assert lib.btn_visualize.isEnabled()
    assert "等值面" in lib.btn_visualize.text()
    # 轨道等值面可以导出 .glb（只含正 / 负相位两层，不含原子与键）
    assert lib.btn_export.isEnabled()
    assert "轨道" in lib.btn_export.text() and "glb" in lib.btn_export.text().lower()
    assert lib.btn_export.toolTip()
    assert not lib.btn_crystal_tab.isEnabled()
    assert lib.current_entry() is None
    view = lib.orbital_view
    assert view.list_widget.count() == 27
    assert view.current_spec() is not None
    assert view.lbl_preview.pixmap() is not None
    assert "电子结构" in lib.lbl_active.text()     # 底部「当前页签」标签


def test_filters_and_search(lib):
    view = lib.orbital_view
    groups = [view.cmb_group.itemData(i) for i in range(view.cmb_group.count())]
    assert groups[0] == "all" and "hybrid" in groups

    view.cmb_group.setCurrentIndex(view.cmb_group.findData("hybrid"))
    _pump(20)
    assert view.list_widget.count() == 9
    assert view.current_spec().group == "hybrid"
    assert view.current_spec().id == "sp_1"   # 教学顺序 sp → sp² → sp³

    view.cmb_group.setCurrentIndex(0)
    view.edit_search.setText("dz2")
    _pump(20)
    assert view.list_widget.count() == 1
    assert view.current_spec().id == "3dz2"
    view.edit_search.clear()
    _pump(20)


def test_per_orbital_iso_hint(lib):
    view = lib.orbital_view
    view.edit_search.setText("2s")
    _pump(20)
    s2 = view.current_spec()
    assert s2.id == "2s"
    assert view.iso() == pytest.approx(s2.iso_hint)
    assert view.iso() < 0.08   # 有径向节点，需更小的 iso 才能看到外瓣
    view.edit_search.clear()
    _pump(20)


def test_visualize_forwards_spec_iso_quality(lib, monkeypatch):
    calls = []
    monkeypatch.setattr(lib, "_on_visualize_orbital",
                        lambda spec, iso, quality: calls.append(
                            (spec.id, iso, quality)))
    view = lib.orbital_view
    view.edit_search.setText("3dxy")
    _pump(20)
    view.spin_iso.setValue(0.12)
    view.cmb_quality.setCurrentIndex(view.cmb_quality.findData("high"))
    lib._visualize_current()
    assert calls and calls[-1][0] == "3dxy"
    assert calls[-1][1] == pytest.approx(0.12)
    assert calls[-1][2] == "high"
    view.edit_search.clear()
    _pump(20)


def test_export_forwards_spec_iso_quality():
    """「导出轨道 3D」必须把轨道页当前选中的 spec / iso / 精度交给主窗口。"""
    from molstudio.panels.library_panel import LibraryPanel

    captured = []
    panel = LibraryPanel(
        lang="zh",
        on_export_orbital=lambda spec, iso, quality, opt: captured.append(
            (spec.id, iso, quality, opt)))
    try:
        panel.sub_tabs.setCurrentIndex(2)
        _pump(30)
        view = panel.orbital_view
        view.edit_search.setText("3dxy")
        _pump(20)
        view.spin_iso.setValue(0.12)
        view.cmb_quality.setCurrentIndex(view.cmb_quality.findData("high"))
        panel._export_current()
        assert len(captured) == 1
        ident, iso, quality, options = captured[0]
        assert ident == "3dxy"
        assert iso == pytest.approx(0.12)
        assert quality == "high"
        assert options.include_surfaces is True
    finally:
        panel.deleteLater()


def test_main_window_exports_surface_only_orbital_glb(win, monkeypatch, tmp_path):
    """结构库按钮 → 主窗口回调 → .glb：只有正负相位两层，没有原子 / Molecule 材质。"""
    from molstudio.core.molecule_export import validate_glb

    out = tmp_path / "2pz_ppt3d.glb"
    monkeypatch.setattr(
        win, "_ppt3d_save_path", lambda stem, start_dir=None: str(out))
    reports = []
    monkeypatch.setattr(win, "_ppt3d_report",
                        lambda *args, **kwargs: reports.append((args, kwargs)))

    panel = win.library_panel
    panel.sub_tabs.setCurrentIndex(2)
    _pump(30)
    view = panel.orbital_view
    view.edit_search.setText("2pz")
    _pump(20)
    view.spin_iso.setValue(0.08)
    view.cmb_quality.setCurrentIndex(view.cmb_quality.findData("low"))
    try:
        panel._export_current()          # 真的走面板 → 回调这条链路
    finally:
        view.edit_search.clear()
        _pump(20)

    gltf = validate_glb(out)
    chemistry = gltf["extras"]["chemistry"]
    assert chemistry["atoms"] == 0 and chemistry["bonds"] == 0
    assert [layer["kind"] for layer in chemistry["surface_layers"]] == [
        "orbital", "orbital"]
    assert len(gltf["meshes"][0]["primitives"]) == 2
    assert "Molecule" not in [m["name"] for m in gltf["materials"]]
    assert reports, "导出后必须给用户结果反馈"
    note = reports[-1][1]["note"]
    assert "2p" in note and "iso=0.080" in note


def test_orbital_visualization_clears_stale_molecule(win):
    """画布上的旧分子必须让位给轨道：否则屏幕有球棍、导出的 .glb 只有等值面。"""
    from molstudio.core.atomic_orbital import orbital_by_id
    from molstudio.core.molecule_library import load_library, molecule_path

    entry = load_library()[0]
    win._library_visualize_molecule(str(molecule_path(entry)), entry)
    _pump(200)
    glw = win.cub_canvas.glw
    assert glw._molecule, "分子没有送到画布，测试前提不成立"

    win._library_visualize_orbital(orbital_by_id("2pz"), 0.08, "low")
    _pump(300)
    assert glw._molecule is None, "载入原子轨道后旧分子的球棍仍留在画布上"
    assert win._get_canvas_structure() is None
    assert glw._pos_surf is not None and glw._pos_surf.vertex_count > 0
    assert glw._neg_surf is not None and glw._neg_surf.vertex_count > 0


def test_toolbar_export_points_to_the_orbital_export(monkeypatch):
    """画布上只有等值面（无原子）时，工具栏 PPT 3D 直接走等值面 GLB 导出，
    而不是弹「请先载入分子」。"""
    from types import SimpleNamespace

    from PyQt5.QtWidgets import QMessageBox

    from molstudio.ui.main_window import OrbitalVisApp

    exported = []
    fake = SimpleNamespace(
        cub_canvas=SimpleNamespace(
            glw=SimpleNamespace(_pos_surf=object(), _neg_surf=None)),
        _get_canvas_structure=lambda: None,
        _lang="zh",
        _export_canvas_surfaces_ppt3d=lambda: exported.append(True))
    messages = []
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *args, **kwargs: messages.append(args))
    OrbitalVisApp._export_current_ppt3d(fake)
    assert exported == [True], "纯等值面画布应直接导出 GLB"
    assert not messages, "不应再提示「请先载入分子」"


def test_small_iso_cube_expands_and_surface_closes(win):
    """iso 调到 0.005 时 4f 会伸出基准立方体：cube 必须外扩，画布表面要闭合。"""
    import numpy as np

    from molstudio.core.atomic_orbital import orbital_by_id

    # 先生成在默认 iso，cube 仍按 iso 下限（0.005）预留外扩量
    win._library_visualize_orbital(orbital_by_id("4fz3"), 0.06, "low")
    _pump(400)
    glw = win.cub_canvas.glw
    half = float(-glw._cube.origin[0])
    assert half > 27 * 1.5, "4f 在 iso=0.005 时 cube 没有外扩（半边长 %.1f）" % half
    # 之后在画布上把 iso 继续调到下限，同一份 cube 仍应抽得出闭合表面
    win.cub_canvas.set_isovalue(0.005)
    _pump(300)
    assert glw._isovalue == 0.005
    for surface in (glw._pos_surf, glw._neg_surf):
        assert surface is not None and surface.vertex_count > 0
        tri = np.asarray(surface.indices).reshape(-1, 3)
        edges = np.sort(np.concatenate(
            [tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]), axis=1)
        _, counts = np.unique(edges, axis=0, return_counts=True)
        assert int((counts == 1).sum()) == 0, "画布等值面仍有开放边（被截断）"
    assert "已按 iso 下限" in win.log_text.toPlainText()


def test_main_window_writes_cube(win, lib, monkeypatch, tmp_path):
    """主窗口回调：生成 cube + 送画布，参数与日志都要对。"""
    import os
    from molstudio.core.atomic_orbital import orbital_by_id
    from molstudio.core.marching_cubes import read_cube

    pushed = []
    monkeypatch.setattr(win, "_push_cubes_to_canvas",
                        lambda cubes, auto_load=True, iso=None: pushed.append(
                            (list(cubes), auto_load, iso)))
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    spec = orbital_by_id("3dz2")
    win._library_visualize_orbital(spec, 0.075, "low")
    assert pushed, "必须把 cube 送进画布"
    cubes, auto_load, iso = pushed[-1]
    assert auto_load is True and iso == pytest.approx(0.075)
    path = cubes[0]
    assert os.path.isfile(path) and path.endswith("3dz2_low.cub")
    cube = read_cube(path)
    assert cube.data.shape == (49, 49, 49)
    assert float(cube.data.max()) == pytest.approx(1.0, abs=1e-5)
    assert win._current_cubes == [path]


def test_tabbar_fits_in_right_column(lib):
    """五个页签必须塞进 764px 宽的右栏，否则 QTabWidget 折叠成滚动箭头。

    带 emoji 的页签名实测把总宽顶到 780+，「引文」直接被卷进箭头里。
    """
    hint = lib.sub_tabs.tabBar().sizeHint().width()
    assert hint <= 720, "页签总宽 %d px，右栏放不下会折叠" % hint


def test_detail_column_can_shrink(lib):
    """详情栏的最小宽度必须让着右栏（实际只有 ~275px）。

    等值面 / 精度控件排成一行时最小宽度是 518px，QSplitter 会把详情框整个
    顶出窗口右边界 —— 缩略图与说明文字都被裁掉。
    """
    # 必须在结构库页真正显示出来后再量：面板还在隐藏态时 QLabel 不换行，
    # 最小宽度会被最长那行说明文字撑到 279px（实测），显示的同一控件只有 234px。
    win = lib.window()
    try:
        win.main_nav.setCurrentRow(win._tab_keys.index("tab_library"))
        _pump(200)
    except Exception:
        pass
    det = lib.orbital_view.lbl_preview.parentWidget()
    assert det.minimumSizeHint().width() <= 260


def test_thumbnail_is_solid_3d_render():
    """缩略图是**真实等值面的 3D 渲染**，不是 2D 截面图。

    学生的直觉是"哑铃""花瓣"，所以列表里必须给实心立体图形：既要有大面积的
    着色像素（不是几条线），也要同时出现蓝 / 橙两种相位色。
    """
    from PyQt5.QtCore import QSize

    from molstudio.core.atomic_orbital import orbital_by_id
    from molstudio.ui.electronic_library_view import orbital_thumbnail

    img = orbital_thumbnail(orbital_by_id("3dz2"), 240, 170).pixmap(
        QSize(240, 170)).toImage().convertToFormat(4)     # Format_RGB32
    w, h = img.width(), img.height()
    blue = orange = 0
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            c = img.pixel(x, y)
            r, g, b = (c >> 16) & 255, (c >> 8) & 255, c & 255
            if b > r + 25:                    # 蓝相位
                blue += 1
            elif r > b + 25:                  # 橙相位
                orange += 1
    total = (w // 2) * (h // 2)
    assert blue > 0.02 * total, "正相位像素太少，图形可能是空的"
    assert orange > 0.02 * total, "负相位像素太少，d_z² 的腰环没画出来"
    assert blue + orange > 0.10 * total, "整体着色面积太小，不像实心立体"


def test_thumbnail_mesh_is_closed():
    """缩略图的等值面必须**闭合**。

    ``spec.extent`` 是按画布取景定的，波瓣在立方体边界处往往还高于 iso，
    直接抽面会被边界切断；画布用双面渲染把断口盖住了，缩略图做了背面剔除
    就会"瓣尖缺一块、露出白底"（3d_z² 实测被切掉一个弧形缺口）。
    """
    import numpy as np

    from molstudio.core.atomic_orbital import orbital_by_id
    from molstudio.ui.electronic_library_view import _iso_surfaces

    for ident in ("3dz2", "4fz3", "sp3_1"):
        pos, neg = _iso_surfaces(orbital_by_id(ident))
        for surf in (pos, neg):
            if getattr(surf, "vertex_count", 0) == 0:
                continue
            tri = np.asarray(surf.indices).reshape(-1, 3)
            edges = np.sort(np.concatenate(
                [tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]), axis=1)
            _, cnt = np.unique(edges, axis=0, return_counts=True)
            assert int((cnt == 1).sum()) == 0, "%s 的等值面不闭合" % ident


def test_hybrid_lobe_axis_is_not_end_on():
    """杂化轨道的瓣轴不能正对相机，否则缩略图退化成一颗圆球。

    固定视角 R_y(25°)·R_x(−60°) 下，sp² (3/3) 与 sp³ (4/4) 的瓣轴与视线夹角
    只有 ~27° / ~16°，投影出来和 1s 一模一样 —— 学生会以为那两格坏了。
    纠偏只允许改转向，不能引入镜像（行列式必须仍是 +1）。
    """
    import numpy as np

    from molstudio.core.atomic_orbital import orbital_library
    from molstudio.ui.electronic_library_view import (
        _lobe_axis, _straighten, _view_matrix,
    )

    rot0 = _view_matrix()
    straightened = []
    for spec in orbital_library():
        axis = _lobe_axis(spec)
        if axis is None:
            continue
        raw = abs(float((rot0 @ axis)[2]))
        rot = _straighten(rot0, axis)
        got = abs(float((rot @ axis)[2]))
        assert got <= 0.80 + 1e-6, "%s 纠偏后瓣轴仍正对相机 (%.2f)" % (spec.id, got)
        assert np.linalg.det(rot) == pytest.approx(1.0, abs=1e-6)
        if raw > 0.80:
            straightened.append(spec.id)
            assert got == pytest.approx(0.40, abs=0.03)
    # 这两条就是实测退化成正圆的
    assert "sp3_4" in straightened and "sp2_3" in straightened


def test_icon_queue_fills_lazily(lib):
    """图标是排队补上的：先出条目，再逐帧填图，不能卡住页面打开。"""
    from PyQt5.QtCore import QSize

    view = lib.orbital_view
    view._refresh_list()          # 重建队列
    assert view._icon_queue, "刷新后应该有待补图标的排队"
    view._pump_icon_queue()
    assert len(view._icon_queue) == 27 - 1
    assert view.list_widget.item(0).icon().pixmap(
        QSize(150, 110)).size().width() > 0


def test_language_refresh_keeps_orbital_page(lib):
    tabs = lib.sub_tabs
    assert "电子结构" in tabs.tabText(2)
    lib.set_lang("en")
    _pump(30)
    assert "Orbitals" in tabs.tabText(2)
    assert "isosurface" in lib.btn_visualize.text().lower()
    assert "orbital" in lib.btn_export.text().lower()
    assert lib.orbital_view.cmb_group.itemText(5) == "Hybrid orbitals"
    assert lib.orbital_view.current_spec() is not None
    lib.set_lang("zh")
    _pump(30)
    assert "电子结构" in tabs.tabText(2)
    assert "等值面" in lib.btn_visualize.text()
    assert "轨道" in lib.btn_export.text()
