# -*- coding: utf-8 -*-
"""位阻地图 / 包埋体积面板的离屏测试。

    python -m pytest tests/test_steric_panel.py -q

所有用例都在 ``QT_QPA_PLATFORM=offscreen`` 下跑：建面板、自动推荐、真跑引擎
``compute``、出图、2D/3D 切换、.inp 回填、非法参数与导出。
"""

import os
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtGui import QColor, QImage, QSurfaceFormat  # noqa: E402
from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

_fmt = QSurfaceFormat()
_fmt.setSamples(0)
_fmt.setDepthBufferSize(24)
_fmt.setVersion(3, 3)
_fmt.setProfile(QSurfaceFormat.CoreProfile)
QSurfaceFormat.setDefaultFormat(_fmt)
QApplication.setAttribute(Qt.AA_DisableWindowContextHelpButton, True)

_APP = None


def _app():
    """QApplication 单例（offscreen）。

    注意：**不要**在已有 QApplication 上再次 setStyle()。全量跑 pytest 时，
    前面的界面冒烟测试已经建过窗口（含 offscreen 下拿不到 GL 上下文的
    QOpenGLWidget）；此时再 setStyle 会触发所有已存在控件的 re-polish，
    在本机 PyQt5 offscreen 下会直接段错误（0xC0000005）。只有在本模块自己
    创建 QApplication 时才设样式。
    """
    global _APP
    inst = QApplication.instance()
    if inst is None:
        inst = QApplication([])
        inst.setStyle("Fusion")
    _APP = inst
    return _APP


def _pump(ms=60):
    app = _app()
    t0 = time.time()
    while (time.time() - t0) * 1000.0 < ms:
        app.processEvents()
        time.sleep(0.005)


def _wait_compute(panel, timeout=240.0):
    """等后台 QThread 跑完并派发 done 信号（阻塞式 pump 事件循环）。"""
    app = _app()
    t0 = time.time()
    while panel._worker is not None and time.time() - t0 < timeout:
        app.processEvents()
        time.sleep(0.01)
    # 再 pump 几轮，确保 _on_worker_done 已执行
    for _ in range(10):
        app.processEvents()
        time.sleep(0.01)
    return panel._worker is None


def synthetic_complex():
    """合成金属配合物：Ru + 4 P + 12 C，所有配体原子在 −z 一侧且非共线。"""
    symbols = ["Ru"]
    coords = [[0.0, 0.0, 0.0]]
    pdirs = []
    for k in range(4):
        ang = np.pi / 2.0 * k + np.pi / 4.0
        u = np.array([np.cos(ang), np.sin(ang), -1.0])
        u = u / np.linalg.norm(u)
        pdirs.append(u)
        coords.append(u * 2.75)
        symbols.append("P")
    for u in pdirs:
        a = np.array([0.0, 0.0, 1.0])
        if abs(np.dot(a, u)) > 0.9:
            a = np.array([1.0, 0.0, 0.0])
        e1 = np.cross(u, a)
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(u, e1)
        for j in range(3):
            phi = 2.0 * np.pi * j / 3.0 + 0.4
            v = np.cos(phi) * e1 + np.sin(phi) * e2
            coords.append(u * 2.75 + 1.75 * (0.55 * u + v))
            symbols.append("C")
    return symbols, np.array(coords, dtype=float)


SYMBOLS, COORDS = synthetic_complex()


@pytest.fixture(scope="module")
def app():
    return _app()


def _make_panel(get_structure=None, log_func=None, glw=None):
    from molstudio.panels.steric_panel import StericPanel

    if get_structure is None:
        get_structure = lambda: (SYMBOLS, COORDS)      # noqa: E731
    panel = StericPanel(get_structure=get_structure, log_func=log_func, glw=glw)
    panel.resize(700, 1400)
    panel.setAttribute(Qt.WA_DontShowOnScreen, True)
    panel.show()
    _pump(120)
    return panel


@pytest.fixture()
def panel(app):
    p = _make_panel()
    try:
        yield p
    finally:
        p.shutdown()
        p.hide()


def _compute_or_fail(panel):
    assert panel._symbols, "合成分子应当已被面板读到"
    panel.btn_auto.click()                 # 自动推荐回填球心 / z 轴 / xz
    _pump(30)
    panel.start()
    assert _wait_compute(panel), "后台计算超时"
    assert not panel._status_error, "计算失败：%s" % panel.lbl_status.text()
    assert panel._result is not None, "计算完成却没有结果：%s" % panel.lbl_status.text()
    return panel._result


def test_canvas_background_snapshot_is_cropped_in_map_coordinates(panel):
    """主画布快照只在相机一致时使用，并按 ±1.06R 裁成地图背景。"""
    image = QImage(200, 200, QImage.Format_ARGB32)
    image.fill(QColor(12, 34, 56, 255))

    class _Cam:
        @staticmethod
        def view():
            return np.eye(4, dtype=float)

        @staticmethod
        def half_height():
            # 7.8 Bohr 恰好是画布默认半高
            return 7.8

    glw = SimpleNamespace(
        width=lambda: 200, height=lambda: 200, cam=_Cam(),
        grabFramebuffer=lambda: image,
        _world_to_screen=lambda *_xyz: (100.0, 100.0, True),
    )
    res = SimpleNamespace(
        map_radius=3.5,
        map=SimpleNamespace(x=np.array([-3.5, 3.5])),
        orientation={"rotation_matrix": np.eye(3), "centre": [0, 0, 0]},
    )
    panel.glw = glw
    rgba, extent = panel._canvas_map_background(res)
    assert rgba is not None
    assert rgba.shape[0] == rgba.shape[1]
    assert rgba.shape[0] == 180             # round(1.06*3.5*24.23)*2
    assert rgba[0, 0].tolist() == [12, 34, 56, 255]
    assert extent == pytest.approx((-3.71, 3.71, -3.71, 3.71))

    # 画布改过朝向：不能用旧快照硬贴到新地图
    mirrored = np.diag([-1.0, 1.0, -1.0])
    res.orientation["rotation_matrix"] = mirrored
    rgba2, extent2 = panel._canvas_map_background(res)
    assert rgba2 is None and extent2 is None


# ── ① 构建 + 双语 ────────────────────────────────────────────────────────
def test_build_and_language_switch(panel):
    assert panel._tabs.count() == 2
    assert panel._plot_tab is panel._tabs.widget(0)
    assert panel._settings_tab is panel._tabs.widget(1)
    assert panel.grp_view.title()
    assert panel.grp_result.title()
    assert panel.grp_params.title()
    assert panel.cmb_engine.count() >= 1

    zh_run = panel.btn_run.text()
    zh_view = panel.cmb_view.itemText(1)
    zh_save = panel.btn_save_img.text()

    panel.set_lang("en")
    _pump(40)
    en_run = panel.btn_run.text()
    assert en_run != zh_run
    assert "Compute" in en_run
    assert panel.grp_view.title() != zh_view
    assert "3D" in panel.cmb_view.itemText(1)
    assert panel.btn_save_img.text() != zh_save

    panel.set_lang("zh")
    _pump(40)
    assert panel.btn_run.text() == zh_run
    assert panel.cmb_view.itemText(1) == zh_view


# ── ② 真跑引擎：%VBur / 象限 / 八分区 / 体积 ─────────────────────────────
def test_auto_roles_and_compute(panel):
    from molstudio.core.steric import auto_roles

    roles = auto_roles(SYMBOLS, COORDS)
    assert roles["centre"] == "1"          # 第一个过渡金属 Ru
    assert roles["z_axis"]
    assert roles["delete"]

    result = _compute_or_fail(panel)

    assert 0.0 <= float(result.percent_buried) <= 100.0
    text = panel.lbl_vbur.text()
    assert text.startswith("%VBur")
    assert text.count("%") >= 2            # "%VBur" 与末尾单位 %
    assert "%.2f" % float(result.percent_buried) in text

    # 四象限：4 个标签都带数值；几何顺序 NW/NE/SW/SE
    from molstudio.panels.steric_panel import QUADRANT_GRID

    assert len(panel.quad_labels) == 4
    for row in QUADRANT_GRID:
        for key in row:
            lab = panel.quad_labels[key]
            assert key in lab.text()
            assert "%" in lab.text()
            assert "—" not in lab.text()
    assert set(result.quadrant_percent) >= {"NE", "NW", "SW", "SE"}

    # 八分区：8 个标签都带 "+z"/"-z" 与数值
    assert len(panel.oct_labels) == 8
    for key, lab in panel.oct_labels.items():
        assert key in lab.text()
        assert "%" in lab.text()
        assert "—" not in lab.text()
    assert len(result.octant_percent) == 8

    # 体积：一位小数 + Å³
    for lab, value in ((panel.lbl_vol_buried, result.buried_volume),
                       (panel.lbl_vol_free, result.free_volume),
                       (panel.lbl_vol_sphere, result.sphere_volume)):
        assert "Å³" in lab.text()
        assert "%.1f" % float(value) in lab.text()

    # 原子统计 / 定向诊断
    assert str(len(result.selected_atoms)) in panel.lbl_atoms_sel.text()
    assert str(len(result.excluded_atoms)) in panel.lbl_atoms_del.text()
    assert "Å" in panel.lbl_diag_axis.text()
    assert "%" in panel.lbl_diag_xz.text()

    # 状态行（完成）与导出按钮可用
    assert "完成" in panel.lbl_status.text()
    assert panel.btn_save_img.isEnabled()
    assert panel.btn_export_data.isEnabled()
    assert panel.btn_export_inp.isEnabled()
    assert panel.btn_export_xyz.isEnabled()
    assert panel.figure.axes, "出图区应当有 axes"

    # 完成状态在切语言后也应重译
    panel.set_lang("en")
    _pump(40)
    assert "Done" in panel.lbl_status.text()
    panel.set_lang("zh")
    _pump(40)


# ── ③ figure 有 axes 且能保存 ────────────────────────────────────────────
def test_figure_savefig(panel, tmp_path):
    _compute_or_fail(panel)
    assert len(panel.figure.axes) >= 1
    out = tmp_path / "steric_map.png"
    panel.figure.savefig(str(out), dpi=300, facecolor="white")
    assert out.exists()
    assert out.stat().st_size > 1000


# ── ④ 2D / 3D 视图切换 ──────────────────────────────────────────────────
def test_view_switch_2d_3d(panel):
    _compute_or_fail(panel)
    assert int(panel.cmb_view.currentData() or 0) == 0
    assert panel.figure.axes[0].name != "3d"

    panel.cmb_view.setCurrentIndex(1)
    _pump(80)
    assert int(panel.cmb_view.currentData()) == 1
    assert panel.figure.axes[0].name == "3d"

    panel.cmb_view.setCurrentIndex(0)
    _pump(80)
    assert panel.figure.axes[0].name != "3d"

    # 显示选项也只重画、不重算：结果对象必须是同一个
    before = panel._result
    panel.chk_quad.setChecked(False)
    panel.chk_atoms.setChecked(False)
    _pump(60)
    assert panel._result is before
    panel.chk_quad.setChecked(True)
    panel.chk_atoms.setChecked(True)
    _pump(60)


# ── ⑤ 打开 .inp 回填官方参数 ─────────────────────────────────────────────
def test_open_inp_backfills_params(panel, tmp_path):
    from molstudio.core.steric import SambVcaJob, read_inp, write_inp

    job = SambVcaJob(
        delete_atoms=[1], centre_atoms=[1], z_axis_atoms=[3], xz_plane_atoms=[5],
        sphere_radius=3.20, displacement=0.25, mesh=0.12,
        remove_h=0, align_z=1, write_surfaces=1, radii_set="bondi",
        map_radius=None,
    )
    inp = tmp_path / "job.inp"
    write_inp(inp, job, SYMBOLS, COORDS, title="pytest steric job")
    assert inp.exists()

    assert panel.load_file(str(inp)) is True
    _pump(60)

    assert panel.edit_centre.text() == "1"
    assert panel.edit_zaxis.text() == "3"
    assert panel.edit_xz.text() == "5"
    assert panel.edit_del.text() == "1"
    assert panel.spn_R.value() == pytest.approx(3.20, abs=1e-6)
    # 官方 .inp 没有独立 map radius → 跟随球半径
    assert panel.spn_mapR.value() == pytest.approx(3.20, abs=1e-6)
    assert panel.spn_mesh.value() == pytest.approx(0.12, abs=1e-6)
    assert panel.spn_disp.value() == pytest.approx(0.25, abs=1e-6)
    assert panel.chk_remove_h.isChecked() is False
    assert panel.cmb_align.currentIndex() == 1
    assert panel.lbl_source.text().startswith("文件：")
    assert len(panel._symbols) == len(SYMBOLS)

    # 回填的 job 与源文件一致
    job2, symbols2, positions2, title2 = read_inp(inp)
    assert symbols2 == SYMBOLS
    np.testing.assert_allclose(np.asarray(positions2, float), COORDS, atol=1e-6)
    assert title2 == "pytest steric job"
    assert job2.sphere_radius == pytest.approx(3.20)


# ── ⑥ 非法参数：走 validate 错误提示，不弹阻塞对话框 ─────────────────────
def test_invalid_params_show_error_without_dialog(panel, monkeypatch):
    calls = []

    def _fake_warning(parent, title, text, *args, **kwargs):
        calls.append((title, text))
        return QMessageBox.Ok

    monkeypatch.setattr(QMessageBox, "warning", _fake_warning)

    panel.edit_centre.setText("")
    panel.start()
    _pump(60)

    assert panel._worker is None, "参数非法时不应启动计算线程"
    assert panel._status_error is True
    assert panel.lbl_status.text().strip()
    assert calls, "应当通过 QMessageBox 报告校验错误"
    assert panel._result is None

    # 序号越界同样应被 validate 拦下
    calls.clear()
    panel.edit_centre.setText("999")
    panel.start()
    _pump(60)
    assert panel._worker is None
    assert panel._status_error is True
    assert calls


# ── 无结构时给出提示而不是异常 ───────────────────────────────────────────
def test_no_structure_is_handled(app, monkeypatch):
    calls = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: calls.append(a) or QMessageBox.Ok)
    panel = _make_panel(get_structure=lambda: None)
    try:
        assert panel.lbl_source.text()
        assert panel._symbols == []
        panel.start()
        _pump(30)
        assert panel._worker is None
        assert calls
    finally:
        panel.shutdown()
        panel.hide()


# ── 导出（对话框 monkeypatch）─────────────────────────────────────────────
def test_exports_write_files(panel, tmp_path, monkeypatch):
    from PyQt5.QtWidgets import QFileDialog

    _compute_or_fail(panel)

    targets = {}

    def _fake_save(parent, title, default, filters):
        suffix = default.rsplit(".", 1)[-1]
        path = str(tmp_path / ("export." + suffix))
        targets[suffix] = path
        return path, filters

    monkeypatch.setattr(QFileDialog, "getSaveFileName", _fake_save)

    panel._save_image()
    _pump(30)
    assert os.path.isfile(targets["png"])
    assert os.path.getsize(targets["png"]) > 1000
    assert "已保存" in panel.lbl_status.text()

    panel._export_data()                      # 默认 .csv → save_grid_csv
    _pump(20)
    assert os.path.isfile(targets["csv"])
    header = open(targets["csv"], encoding="utf-8").readline()
    assert header.strip().startswith("x,y,z")

    panel._export_inp()
    _pump(20)
    assert os.path.isfile(targets["inp"])
    inp_text = open(targets["inp"], encoding="utf-8").read()
    assert len(inp_text.splitlines()) > 20
    for sym in ("Ru", "P", "C"):
        assert sym in inp_text

    panel._export_oriented_xyz()
    _pump(20)
    lines = open(targets["xyz"], encoding="utf-8").read().splitlines()
    assert int(lines[0]) == len(SYMBOLS)

    # JSON 分支
    panel._export_data()                      # 仍返回 csv 路径，直接测 save_json
    from molstudio.core.steric import save_json

    jpath = tmp_path / "result.json"
    save_json(panel._result, jpath)
    assert jpath.stat().st_size > 100


# ── 右栏宽度：面板最小宽度必须能塞进约 680px 的右栏 ──────────────────────
def test_minimum_width_fits_right_column(panel):
    _compute_or_fail(panel)
    width_2d = panel.minimumSizeHint().width()
    assert width_2d < 660, "2D 视图最小宽度 %d px 会横向溢出右栏" % width_2d

    panel._tabs.setCurrentIndex(1)
    _pump(60)
    scroll = panel._settings_scroll
    # 两列参数表单在约 370px 的窄视口内不应把控件横向裁掉。
    assert scroll.widget().width() <= scroll.viewport().width() + 4

    panel.cmb_view.setCurrentIndex(1)
    _pump(80)
    width_3d = panel.minimumSizeHint().width()
    assert width_3d < 660, "3D 视图最小宽度 %d px 会横向溢出右栏" % width_3d

    panel.cmb_view.setCurrentIndex(0)
    _pump(40)

# ── 切页自动同步画布结构（showEvent） ────────────────────────────────────
def test_show_event_syncs_canvas_structure(app):
    """用户「打开分子 → 切到位阻页」时应自动取到画布结构，无需手点刷新。"""
    state = {"symbols": ["C"], "coords": np.array([[0.0, 0.0, 0.0]])}
    p = _make_panel(get_structure=lambda: (state["symbols"], state["coords"]))
    try:
        assert p._symbols == ["C"]
        state["symbols"] = ["C", "C"]
        state["coords"] = np.array([[0.0, 0.0, 0.0], [1.4, 0.0, 0.0]])
        p.hide()
        p.show()
        _pump(80)
        assert p._symbols == ["C", "C"]
        # 显式打开文件后，切页不再被画布覆盖（文件优先）
        p._set_structure(["Ru"], np.array([[0.0, 0.0, 0.0]]),
                         kind="file", path="demo.xyz")
        p.hide()
        p.show()
        _pump(80)
        assert p._symbols == ["Ru"]
    finally:
        p.shutdown()
        p.hide()

# ── 换分子后角色序号必须刷新（复核 P0-1 回归） ──────────────────────────
def test_structure_change_resets_atom_roles(app):
    """换一份结构后，球心 / z / xz / 删除序号不能沿用上一个分子的值。"""
    state = {"symbols": list(SYMBOLS), "coords": COORDS}
    p = _make_panel(get_structure=lambda: (state["symbols"], state["coords"]))
    try:
        _pump(50)
        assert p.edit_centre.text() == "1"          # 合成配合物：Ru 是 1 号
        # 换成一个完全不同的分子（C, C, O）→ 角色应重新推荐为 O（3 号）
        state["symbols"] = ["C", "C", "O"]
        state["coords"] = np.array([[0.0, 0.0, 0.0],
                                    [1.4, 0.0, 0.0],
                                    [2.4, 0.0, 0.0]])
        p.hide()
        p.show()
        _pump(80)
        assert p._symbols == ["C", "C", "O"]
        assert p.edit_centre.text() == "3", p.edit_centre.text()
        assert p.edit_zaxis.text() in ("1", "2")
    finally:
        p.shutdown()
        p.hide()


# ══════════════════════════════════════════════════════════════════════════
#  v2：画布点选原子 / 删除原子 + 出图样式 / 定向方式
# ══════════════════════════════════════════════════════════════════════════
class _FakeCam:
    """画布相机替身：``view()`` 返回 4×4，前 3×3 即 world → screen 旋转。"""

    def __init__(self, matrix=None):
        self._matrix = np.eye(4) if matrix is None else np.asarray(matrix, float)

    def view(self):
        return self._matrix


class FakeGLW:
    """离屏画布替身：只实现面板用到的属性/方法，不需要 GL 上下文。"""

    def __init__(self, view_matrix=None):
        self._selected_atoms = []
        self._regen_calls = 0
        self._clear_calls = 0
        self.callbacks = []
        self.cam = _FakeCam(view_matrix)

    def add_atom_pick_callback(self, cb):
        self.callbacks.append(cb)

    def _regenerate_atoms(self):
        self._regen_calls += 1

    def _clear_selection(self):
        self._selected_atoms = []
        self._clear_calls += 1

    def pick(self, idx_1based):
        """模拟画布左键点击：先 toggle 选中集，再逐个触发回调（真实 API 顺序）。"""
        i = int(idx_1based) - 1
        sel = set(self._selected_atoms)
        if i in sel:
            sel.discard(i)
        else:
            sel.add(i)
        self._selected_atoms = sorted(sel)
        for cb in list(self.callbacks):
            cb(int(idx_1based))
        return self._selected_atoms


@pytest.fixture()
def glw_panel(app):
    glw = FakeGLW()
    p = _make_panel(glw=glw)
    try:
        yield p, glw
    finally:
        p.shutdown()
        p.hide()


def _set_pick(panel, mode):
    idx = panel.cmb_pick.findData(mode)
    assert idx >= 0, "点选目标下拉里没有 %r" % mode
    panel.cmb_pick.setCurrentIndex(idx)
    _pump(25)


def _engine_supports_view_rotation():
    import inspect

    from molstudio.core.steric import compute

    try:
        sig = inspect.signature(compute)
    except (TypeError, ValueError):                                # pragma: no cover
        return True
    if "view_rotation" in sig.parameters:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD
               for p in sig.parameters.values())


# ── ① 点选「设球心 / 设 z 轴 / 设 xz」 ──────────────────────────────────
def test_canvas_pick_centre_zaxis_xz(glw_panel):
    panel, glw = glw_panel
    assert len(glw.callbacks) == 1, "面板应把点选回调注册到画布"

    _set_pick(panel, "centre")
    glw.pick(3)
    assert panel.edit_centre.text() == "3"
    assert glw._selected_atoms == [2], "球心原子应在画布上被高亮"

    _set_pick(panel, "z_axis")
    panel.edit_zaxis.clear()
    glw.pick(3)
    assert panel.edit_zaxis.text() == "3"
    glw.pick(5)
    assert panel.edit_zaxis.text() == "3,5"
    glw.pick(3)                                   # 再点一次 = 移出列表
    assert panel.edit_zaxis.text() == "5"
    assert glw._selected_atoms == [4]

    _set_pick(panel, "xz")
    panel.edit_xz.clear()
    glw.pick(7)
    assert panel.edit_xz.text() == "7"
    glw.pick(9)
    assert panel.edit_xz.text() == "7,9"
    assert glw._selected_atoms == [6, 8]


# ── ② 点选删除 / 恢复原子（用户诉求的核心） ─────────────────────────────
def test_canvas_pick_delete_and_restore(glw_panel):
    panel, glw = glw_panel
    panel.edit_del.clear()
    glw._selected_atoms = []
    _set_pick(panel, "delete")

    glw.pick(3)                                   # 画布多选 3 号
    assert panel.edit_del.text() == "3"
    glw.pick(5)
    assert panel.edit_del.text() == "3,5"
    glw.pick(3)                                   # 取消 3 号
    assert panel.edit_del.text() == "5"

    # 画布上已有选中集存在时，再点 7 → 删除列表同步为整个选中集
    glw._selected_atoms = [2]                     # 3 号
    glw.pick(7)
    assert panel.edit_del.text() == "3,7"

    _set_pick(panel, "restore")
    glw.pick(3)                                   # 从删除列表恢复 3 号
    assert panel.edit_del.text() == "7"
    assert glw._selected_atoms == [6]


# ── ③ 高亮同步 ──────────────────────────────────────────────────────────
def test_canvas_pick_syncs_highlight(glw_panel):
    panel, glw = glw_panel
    panel.edit_centre.clear()
    _set_pick(panel, "centre")
    glw.pick(4)
    assert glw._selected_atoms == [3]
    assert glw._regen_calls >= 1, "改完选中集必须调用 _regenerate_atoms 刷新高亮"

    panel.edit_zaxis.clear()
    _set_pick(panel, "z_axis")
    glw.pick(2)
    glw.pick(4)
    assert panel.edit_zaxis.text() == "2,4"
    assert glw._selected_atoms == [1, 3]

    # 进入「删除原子」时，画布高亮切到删除列表，便于继续增删
    panel.edit_del.setText("1,2")
    _set_pick(panel, "delete")
    assert glw._selected_atoms == [0, 1]


# ── ④ 点选按钮 + 离开页面自动关闭 ───────────────────────────────────────
def test_canvas_pick_buttons_and_hide_event(glw_panel):
    panel, glw = glw_panel
    glw._selected_atoms = [0, 2, 4]
    panel._use_canvas_selection_as_delete()
    assert panel.edit_del.text() == "1,3,5"

    panel._clear_delete_list()
    assert panel.edit_del.text() == ""

    glw._selected_atoms = [1, 3]
    panel._clear_canvas_selection()
    assert glw._selected_atoms == []
    assert glw._clear_calls >= 1

    # 打开点选后离开本页 → 自动关闭 + 清画布选中，不再抢点击
    _set_pick(panel, "delete")
    glw._selected_atoms = [2]
    panel.hide()
    _pump(40)
    assert panel._pick_mode == "off"
    assert panel.cmb_pick.currentData() == "off"
    assert glw._selected_atoms == []
    before = panel.edit_del.text()
    glw.pick(9)                                   # 关闭后回调不应再改字段
    assert panel.edit_del.text() == before


# ── ⑤ 出图控件默认值 / 切换后只重画不重算 ──────────────────────────────
def test_render_style_controls(panel):
    from molstudio.panels.steric_panel import _render_api

    # 默认值：StericRender 平滑风格 + SambVca 官方配色 + 固定 ±R 色标
    assert panel.cmb_style.currentData() == "stericrender"
    assert panel.cmb_cmap.currentData() == "sambvca"
    assert panel.chk_contours.isChecked() is True
    assert panel.chk_skeleton.isChecked() is True
    assert panel.spn_map_opacity.value() == pytest.approx(0.72)
    assert panel.chk_quad.isChecked() is True
    assert panel.chk_axes.isChecked() is True
    assert panel.cmb_molecule_scope.count() == 2
    assert panel.cmb_molecule_scope.currentData() is True
    assert panel.chk_auto_color.isChecked() is False
    assert panel.spn_cmin.isEnabled() is False
    assert panel.spn_cmax.isEnabled() is False
    assert panel._color_range() is None
    # 「显示原子投影」已并入「显示分子骨架」（旧属性保留为同一个控件）
    assert panel.chk_atoms is panel.chk_skeleton
    assert panel.chk_skeleton.isChecked() is True
    assert "sambvca" in [panel.cmb_cmap.itemData(i)
                         for i in range(panel.cmb_cmap.count())]

    _compute_or_fail(panel)
    assert panel.figure.axes, "出图区应当有 axes"
    lo, hi = panel._fixed_range()
    assert lo == pytest.approx(-3.5, abs=1e-6)
    assert hi == pytest.approx(3.5, abs=1e-6)
    assert panel._color_range() is None, "默认色标应为固定 ±R，不按数据范围"

    # 切换风格 / 配色 / 等高线 / 骨架：只重画，结果对象不变
    before = panel._result
    for combos in (panel.cmb_style, panel.cmb_cmap):
        for idx in (1, 2, 0):
            combos.setCurrentIndex(idx % combos.count())
            _pump(40)
            assert panel.figure.axes
            assert panel._result is before
    for chk in (panel.chk_contours, panel.chk_skeleton,
                panel.chk_quad, panel.chk_axes):
        chk.setChecked(False)
        _pump(30)
        assert panel.figure.axes
        chk.setChecked(True)
        _pump(30)
        assert panel.figure.axes

    # 3D 视图共用同一份 result.map
    panel.cmb_view.setCurrentIndex(1)
    _pump(80)
    assert panel.figure.axes
    assert panel._result is before
    assert any(ax.name == "3d" for ax in panel.figure.axes)
    # 3D 的 z 轴标题必须清空（否则压在 0.0/−0.5… 刻度上，色标已标 z）
    for ax in panel.figure.axes:
        if ax.name == "3d":
            assert ax.get_zlabel() == ""
    panel.cmb_view.setCurrentIndex(0)
    _pump(60)

    # 勾选「按数据范围」→ min/max 可编辑，色标用数据范围
    panel.chk_auto_color.setChecked(True)
    _pump(40)
    assert panel.spn_cmin.isEnabled() is True
    assert panel.spn_cmax.isEnabled() is True
    rng = panel._color_range()
    assert rng is not None and rng[1] > rng[0]
    assert panel.figure.axes
    panel.chk_auto_color.setChecked(False)
    _pump(30)
    assert panel._color_range() is None

    if _render_api() is not None:
        # 出图模块已落地：palette/style 直接交给它，不应退回旧路径
        assert panel._map_style() in ("stericrender", "sambvca")
        ax = panel.figure.axes[0]
        assert "xz" not in [text.get_text() for text in ax.texts]
        panel.cmb_molecule_scope.setCurrentIndex(1)
        _pump(50)
        assert panel.figure.axes[0].steric_molecule_clip is False
        assert panel._result is before
        panel.cmb_molecule_scope.setCurrentIndex(0)
        _pump(30)


# ── ⑥ 定向方式：原子 / 画布视角（含无相机时的本地化报错） ──────────────
def test_orientation_mode_ui(panel, monkeypatch):
    # 没有画布（单独使用/测试）→ 默认退回官方原子定向
    assert panel.cmb_orient.currentData() == "sambvca"
    assert panel._params()["orient_mode"] == "sambvca"
    assert panel.edit_zaxis.isEnabled() and panel.edit_xz.isEnabled()
    assert panel.cmb_align.isEnabled()
    assert panel.lbl_orient_hint.text(), "定向方式下面应一直有说明文字"
    assert "文献" in panel.lbl_orient_hint.text()

    panel.cmb_orient.setCurrentIndex(panel.cmb_orient.findData("view"))
    _pump(30)
    assert panel._params()["orient_mode"] == "view"
    assert panel.edit_zaxis.isEnabled() is False
    assert panel.edit_xz.isEnabled() is False
    assert panel.cmb_align.isEnabled() is False
    # 视图定向不使用 Disp（SambVca 沿 z 的平移），引擎会忽略 → 一并置灰
    assert panel.spn_disp.isEnabled() is False
    assert panel.lbl_orient_hint.text(), "选择画布视角后应显示提示文字"

    # 没有 glw → 取不到朝向：本地化报错，不崩、不启动线程
    calls = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: calls.append(a) or QMessageBox.Ok)
    panel.btn_auto.click()
    _pump(20)
    panel.start()
    _pump(60)
    assert panel._worker is None
    assert panel._status_error is True
    assert calls, "取不到画布朝向时应弹出本地化错误提示"
    assert panel.lbl_status.text().strip()

    panel.cmb_orient.setCurrentIndex(0)
    _pump(20)
    assert panel.edit_zaxis.isEnabled() is True
    assert panel.spn_disp.isEnabled() is True
    assert panel._params()["orient_mode"] == "sambvca"


def test_view_result_disables_inp_export(glw_panel):
    """视图定向结果不能导出官方 .inp（官方格式只支持 SambVca 原子定向）。"""
    if not _engine_supports_view_rotation():
        pytest.skip("steric 引擎尚未提供 view_rotation")
    panel, glw = glw_panel
    panel.cmb_orient.setCurrentIndex(1)
    _pump(20)
    panel.start()
    assert _wait_compute(panel), "后台计算超时"
    _pump(80)
    assert panel._result is not None
    assert str(getattr(panel._result, "orient_mode", "")) == "view"
    assert panel.btn_export_inp.isEnabled() is False
    assert panel.btn_export_data.isEnabled() is True
    before = panel.lbl_status.text()
    panel._export_inp()                 # 兜底：即使被调用也不应弹文件对话框
    _pump(20)
    assert panel.lbl_status.text() != before


def test_view_orientation_compute(glw_panel):
    if not _engine_supports_view_rotation():
        pytest.skip("steric 引擎尚未提供 view_rotation（由核心侧同步开发）")
    panel, glw = glw_panel
    panel.cmb_orient.setCurrentIndex(1)
    _pump(20)

    R = panel._view_rotation()
    assert R is not None and R.shape == (3, 3)
    np.testing.assert_allclose(R, np.eye(3), atol=1e-9)

    panel.btn_auto.click()
    _pump(30)
    panel.start()
    assert _wait_compute(panel), "后台计算超时"
    assert not panel._status_error, panel.lbl_status.text()
    res = panel._result
    assert res is not None
    assert getattr(res, "orient_mode", None) == "view"
    assert panel.lbl_diag_orient.text()
    assert panel._t("orient_short_view") in panel.lbl_diag_orient.text()
    assert panel.lbl_diag_view.text()
    assert "0.0" in panel.lbl_diag_view.text()          # identity → 视图倾角 0°
    assert panel.figure.axes
    assert panel.btn_save_img.isEnabled()


# ── ⑦ i18n：中英键对称 + 新控件切换后无中文残留 ────────────────────────
def test_i18n_new_controls(panel):
    import re

    from molstudio.panels.steric_panel import _TR

    assert set(_TR["zh"]) == set(_TR["en"]), "zh / en 的键必须一一对应"
    for key in ("lbl_pick", "pick_delete", "btn_pick_delete",
                "lbl_style", "chk_contours", "chk_skeleton", "chk_axes",
                "lbl_orient", "orient_view", "diag_orient", "diag_view_tilt"):
        assert key in _TR["zh"] and key in _TR["en"], key

    panel.set_lang("en")
    _pump(50)
    cjk = re.compile(r"[\u4e00-\u9fff]")
    widgets = (panel.lbl_pick, panel.lbl_style, panel.lbl_orient,
               panel.btn_pick_delete, panel.btn_pick_clear_del,
               panel.btn_pick_clear_sel, panel.chk_contours,
               panel.chk_skeleton, panel.chk_quad, panel.chk_axes,
               panel.lbl_pick_hint)
    for w in widgets:
        assert w.text().strip(), "英文文案不应为空"
        assert not cjk.search(w.text()), w.text()
    for combo in (panel.cmb_pick, panel.cmb_orient, panel.cmb_style):
        assert combo.count() >= 2
        for i in range(combo.count()):
            assert combo.itemText(i).strip()
            assert not cjk.search(combo.itemText(i)), combo.itemText(i)
    for w in (panel.cmb_pick, panel.btn_pick_delete, panel.chk_contours,
              panel.chk_skeleton, panel.chk_axes, panel.cmb_orient):
        assert w.toolTip().strip()
        assert not cjk.search(w.toolTip()), w.toolTip()

    panel.set_lang("zh")
    _pump(30)
    assert "画布点选" in panel.lbl_pick.text()


# ── ⑦ 默认跟随画布视角 + 「同步画布朝向」 ────────────────────────────────
def _q2m(q):
    x, y, z, w = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ], dtype=float)


def test_default_orientation_follows_canvas_when_available(glw_panel):
    """有画布时默认「按当前画布视角」；没有画布时退回官方原子定向。"""
    panel, glw = glw_panel
    assert panel.cmb_orient.currentData() == "view"
    assert panel._params()["orient_mode"] == "view"
    assert panel.edit_zaxis.isEnabled() is False
    assert panel.lbl_orient_hint.text()


def test_sync_canvas_orientation(glw_panel):
    """官方定向算完后，按钮应能把画布相机设成与地图相同朝向并把球心居中。"""
    if not _engine_supports_view_rotation():
        pytest.skip("steric 引擎尚未提供 view_rotation")
    panel, glw = glw_panel
    panel.cmb_orient.setCurrentIndex(panel.cmb_orient.findData("sambvca"))
    _pump(30)
    panel.start()
    assert _wait_compute(panel), "后台计算超时"
    _pump(60)
    res = panel._result
    assert res is not None
    R_expected = np.asarray(res.orientation["rotation_matrix"], dtype=float)

    panel._sync_canvas_orientation()
    _pump(30)
    q = np.asarray(glw.cam.q, dtype=float)
    assert q.shape == (4,)
    assert abs(np.linalg.norm(q) - 1.0) < 1e-6
    np.testing.assert_allclose(_q2m(q), R_expected, atol=1e-6)
    t = np.asarray(glw.cam.t, dtype=float)
    assert t.shape == (3,)
    assert panel.btn_sync_canvas.isEnabled()
    assert "画布" in panel.lbl_status.text()

