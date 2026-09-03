"""
esp_viewer.py — 基于 cub_viewer 引擎的 ESP 等值面可视化
======================================================

思路（与 ESPViewer/esv_surface_gui.py 一致）：
    * 用「电子密度 cube」(density.cub) 定义几何表面 —— 取 rho = isolevel
      (默认 0.001, 即 vdW 表面) 的等值面；
    * 用「静电势 cube」(ESP.cub) 在表面顶点处三线性采样，做**逐顶点连续
      着色**（默认 RWB 红-白-蓝色标，符合化学惯例：红=负电势=富电子,
      蓝=正电势=缺电子）；
    * 复用 cub_viewer.CubGLWidget 的 OpenGL 渲染管线（depth peeling + Phong）。

与 cub_viewer 默认「单场 + 正/负双色」不同，这里实现标准的 ESP 表面：
几何来自密度场、颜色来自 ESP 场，颜色是连续的而非整面单色。

依赖：PyQt5, PyOpenGL, PyMCubes, numpy

用法：
    python esp_viewer.py --density density.cub --esp ESP.cub
    python esp_viewer.py -d density.cub -e ESP.cub --isolevel 0.001 --vmin -0.03 --vmax 0.03
也可不带参数直接运行，在界面里选择文件。
"""

import os
import sys
import traceback
import argparse

import numpy as np

try:
    import mcubes
    _HAS_MCUBES = True
except ImportError:
    _HAS_MCUBES = False

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSlider, QGroupBox, QFileDialog,
    QGridLayout, QCheckBox, QFrame,
)
from PyQt5.QtCore import Qt, QTimer
from file_dialogs import open_file
from PyQt5.QtGui import QDoubleValidator as _QDV

# ── 复用 ovcanvas 引擎组件 ──
from ovcanvas import (
    CubGLWidget, _ensure_pyopengl, IBOVIEW_DEFAULTS,
)
from marching_cubes import read_cube, compute_bounding_sphere, marching_cubes
try:                              # 仅用于保持与引擎的依赖一致；缺失也不影响 ESP 渲染
    from fchk_orbital import ELEMENT_SYMBOLS  # noqa: F401
except Exception:                # noqa
    ELEMENT_SYMBOLS = None


# ── 常量 ──
AU_TO_KCAL = 627.509  # Hartree -> kcal/mol (Gaussian cube ESP 场默认 a.u.)
DEFAULT_ISOLEVEL = 0.001  # 密度等值面 (vdW 表面)
# ESP 色标范围，单位与 ESP 场原始单位一致（Multiwfn/高斯 cube 默认 a.u.）。
# extract_esp_surface 默认 au=1.0（不换算），调用方应确保 vmin/vmax 与 esp_cube 同单位。
DEFAULT_VMIN, DEFAULT_VMAX = -0.03, 0.03  # ESP 色标范围 (a.u.)


# ════════════════════════════════════════════════════════════════
# 1. 几何提取：密度场定面 + ESP 场顶点着色
# ════════════════════════════════════════════════════════════════

def _trilinear(field, idx0, idx1, frac):
    """三线性采样 field（与 marching_cubes._trilinear 一致）。"""
    x0, y0, z0 = idx0[:, 0], idx0[:, 1], idx0[:, 2]
    x1, y1, z1 = idx1[:, 0], idx1[:, 1], idx1[:, 2]
    fx, fy, fz = frac[:, 0], frac[:, 1], frac[:, 2]
    gx_, gy_, gz_ = 1.0 - fx, 1.0 - fy, 1.0 - fz
    return (field[x0, y0, z0] * gx_ * gy_ * gz_ +
            field[x1, y0, z0] * fx * gy_ * gz_ +
            field[x0, y1, z0] * gx_ * fy * gz_ +
            field[x1, y1, z0] * fx * fy * gz_ +
            field[x0, y0, z1] * gx_ * gy_ * fz +
            field[x1, y0, z1] * fx * gy_ * fz +
            field[x0, y1, z1] * gx_ * fy * fz +
            field[x1, y1, z1] * fx * fy * fz)


# ── ESP 配色方案 ──
# 名称 -> (matplotlib cmap 名 / None=程序内置, 是否发散型)
# 发散型（diverging）色标以 0 为中心，适合带符号的 ESP。
# 化学惯例：静电势图红色=富电子（负电势），蓝色=缺电子（正电势），
# 因此默认用 RWB（红-白-蓝，低值红=负、高值蓝=正）。
# 顺序型（sequential）色标从低到高单向渐变（如 viridis/jet）。
# 注：matplotlib 的 jet/rainbow/hsv 为经典彩虹，但过渡生硬（感知不均匀、
# 两端与中段有突兀色块）；turbo 是 Google 设计的 jet 现代替代，感知均匀、
# 颜色连续丰富，作为"彩虹"主推。nipy_spectral / gist_ncar 为更丰富的彩虹变体。
ESP_CMAPS = {
    "RWB (红-白-蓝)":    ("bwr_r", True),
    "BWR (蓝-白-红)":    ("bwr", True),
    "Coolwarm":          ("coolwarm", True),
    "Seismic":           ("seismic", True),
    "RdBu":              ("RdBu", True),
    "彩虹 Turbo":         ("turbo", False),
    "彩虹 NipySpectral":  ("nipy_spectral", False),
    "彩虹 NCAR":          ("gist_ncar", False),
    "彩虹 HSV":           ("hsv", False),
    "彩虹 Jet":           ("jet", False),
    "Viridis":           ("viridis", False),
    "Plasma":            ("plasma", False),
    "Cividis":           ("cividis", False),
    "冰火 IceFire":      ("RdYlBu_r", True),
}

# 内部纯函数实现的色标（不依赖 matplotlib，作为兜底）
def _bwr(t):
    """Blue-White-Red 色标: t in [0,1] -> RGB (0,0,1)->(1,1,1)->(1,0,0)。"""
    t = np.clip(t, 0.0, 1.0)
    rgb = np.empty((len(t), 3), dtype=np.float32)
    white = t >= 0.5
    blue = ~white
    tt = t[blue] / 0.5
    rgb[blue] = np.stack([tt, tt, np.ones_like(tt)], axis=1)
    tt = (t[white] - 0.5) / 0.5
    rgb[white] = np.stack([np.ones_like(tt), 1.0 - tt, 1.0 - tt], axis=1)
    return rgb


def _rwb(t):
    """Red-White-Blue 色标: t in [0,1] -> RGB (1,0,0)->(1,1,1)->(0,0,1)
    （RWB 兜底实现，低值红=富电子/负电势）。"""
    arr = np.atleast_1d(np.asarray(t, dtype=np.float64))
    out = _bwr(1.0 - arr)
    return out[0] if np.ndim(t) == 0 else out


_MPL_CMAP_CACHE = {}


def _mpl_cmap(name):
    """懒加载 matplotlib colormap（缓存）。失败返回 None。"""
    if name in _MPL_CMAP_CACHE:
        return _MPL_CMAP_CACHE[name]
    try:
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib import cm
        cmap = cm.get_cmap(name) if hasattr(cm, "get_cmap") else \
            __import__("matplotlib.cm", fromlist=["get_cmap"]).get_cmap(name)
    except Exception:  # noqa
        cmap = None
    _MPL_CMAP_CACHE[name] = cmap
    return cmap


def _apply_colormap(t, cmap_name="RWB (红-白-蓝)", invert=False):
    """t in [0,1] -> RGB float32 (N,3)。优先用 matplotlib colormap，
    兜底用内置 _bwr/_rwb（仅对 BWR/RWB 类有效）。

    invert=True 时把配色方向翻转（低值↔高值互换）。
    """
    t = np.clip(t, 0.0, 1.0)
    spec = ESP_CMAPS.get(cmap_name, ("bwr_r", True))
    mpl_name = spec[0]
    inverted = bool(invert)
    if inverted:
        mpl_name = mpl_name[:-2] if mpl_name.endswith("_r") else mpl_name + "_r"
    cmap = _mpl_cmap(mpl_name) if mpl_name else None
    if cmap is not None:
        rgba = cmap(t)
        return rgba[:, :3].astype(np.float32)
    # 兜底（仅 BWR/RWB 类有内置实现）：低值端是红还是蓝，
    # 由原配色方向与 invert 共同决定（RWB/RdBu 默认低值=红）
    up = (cmap_name or "").upper()
    red_low = ("RWB" in up) or ("RDBU" in up)
    if inverted:
        red_low = not red_low
    return _rwb(t) if red_low else _bwr(t)


def extract_esp_surface(density_cube, esp_cube, isolevel=DEFAULT_ISOLEVEL,
                        vmin=DEFAULT_VMIN, vmax=DEFAULT_VMAX, au=1.0,
                        cmap="RWB (红-白-蓝)", auto_range=False, invert=False):
    """用密度场定几何、ESP 场定顶点颜色，返回 (IsoSurface, CubeData)。

    几何（顶点 + 法线）复用引擎的 marching_cubes 从密度场提取（世界坐标）；
    ESP 值在该几何顶点处对 ESP 场做三线性采样，按 cmap 配色方案生成逐顶点连续色。

    Args:
        density_cube: CubeData，电子密度场（定义等值面几何）。
        esp_cube:     CubeData，静电势场（用于顶点着色，单位 a.u.）。
        isolevel:     密度等值面阈值（默认 0.001 = vdW 表面）。
        vmin/vmax:    ESP 色标范围，单位需与 esp_cube 一致（默认 a.u.）。
        au:           ESP 场换算系数，默认 1.0（保持原始单位，
                     与默认 a.u. 色标范围 ±0.03 自洽）。仅在你需要把
                     ESP 场显式换算到 kcal/mol 并把 vmin/vmax 也设为
                     kcal/mol 量级时，才传入 AU_TO_KCAL（=627.509）。
        cmap:         ESP 配色方案名（见 ESP_CMAPS 的键），默认 RWB
                      （红-白-蓝：低值红=富电子/负电势，高值蓝=缺电子/正电势）。
        auto_range:   True 时忽略 vmin/vmax，按 ESP 实际分布自适应设范围
                     （发散型色标用 ±max(|值|)，顺序型用 [min,max] 的 2~98 分位），
                     让颜色铺满整个色标、过渡更自然丰富。
        invert:       True 时翻转配色方向（低值端↔高值端互换），
                     对任意配色方案通用。

    Returns:
        (surf, density_cube) —— surf 含世界坐标顶点、梯度法线、cmap 顶点色。
    """
    if not _HAS_MCUBES:
        raise RuntimeError("PyMCubes 缺失。请运行: pip install PyMCubes")

    # 1) 几何 + 法线来自密度场（引擎已处理好世界坐标与朝外法线）
    surf = marching_cubes(density_cube, float(isolevel), flip_normal=False)
    if surf.vertex_count == 0:
        return surf, density_cube

    world = surf.vertices.astype(np.float64)  # 世界坐标顶点

    # 2) 在 ESP 场上于世界坐标顶点处采样: world -> ESP 索引空间
    ebasis = np.array([esp_cube.dx, esp_cube.dy, esp_cube.dz], dtype=np.float64)
    try:
        inv_eb = np.linalg.inv(ebasis)
    except np.linalg.LinAlgError:
        inv_eb = np.eye(3)
    eidx = (world - esp_cube.origin.astype(np.float64)) @ inv_eb

    edims = np.array([esp_cube.nx, esp_cube.ny, esp_cube.nz], dtype=np.int64)
    e0 = np.floor(eidx).astype(np.int64)
    np.clip(e0, 0, edims - 1, out=e0)
    e1 = np.minimum(e0 + 1, edims - 1)
    ef = eidx - e0

    esp_vals = _trilinear(esp_cube.data.astype(np.float64), e0, e1, ef)
    esp_vals = esp_vals * au  # a.u. (Hartree) -> kcal/mol

    # 3) 顶点着色（按 cmap 配色方案）
    if auto_range:
        # 自适应范围：让颜色铺满整个色标，过渡更自然丰富
        is_div = ESP_CMAPS.get(cmap, (None, True))[1]
        if is_div:
            m = float(np.max(np.abs(esp_vals))) or 1e-6
            vmin, vmax = -m, m
        else:
            lo, hi = np.percentile(esp_vals, [2, 98])
            if hi - lo < 1e-9:
                lo, hi = float(esp_vals.min()), float(esp_vals.max())
            if hi - lo < 1e-9:
                lo, hi = lo - 1e-3, hi + 1e-3
            vmin, vmax = float(lo), float(hi)
    t = (esp_vals - vmin) / (vmax - vmin)
    rgb = _apply_colormap(t, cmap_name=cmap, invert=invert)
    colors = np.column_stack([rgb, np.ones(len(rgb), dtype=np.float32)]).astype(np.float32)
    surf.colors = colors
    return surf, density_cube


# ════════════════════════════════════════════════════════════════
# 2. GUI：复用 CubGLWidget 渲染管线
# ════════════════════════════════════════════════════════════════

_QSS = """
QWidget#ESPRoot { background-color: #E4EAF2; }
QWidget#ESPToolBar { background-color: #FFFFFF; border-bottom: 1px solid #CBD5E1; }
QWidget#ESPToolBar QLabel { color: #4A5568; font-size: 9pt; padding: 0 2px; }
QLabel#ESPStatus { color: #5C6BC0; font-size: 8.5pt; background-color: #EEF2FF;
    border-top: 1px solid #C5CAE9; padding: 4px 10px; }
QFrame#ESPParams { background-color: #F5F6FA; border-top: 1px solid #CBD5E1; }
QFrame#ESPParams QGroupBox { margin-top: 14px; padding: 14px 10px 8px 10px; }
QPushButton { padding: 5px 12px; font-size: 9pt; }
"""


class ESPViewer(QMainWindow):
    """ESP 表面可视化主窗口。"""

    def __init__(self, density_path=None, esp_path=None,
                 isolevel=DEFAULT_ISOLEVEL, vmin=DEFAULT_VMIN, vmax=DEFAULT_VMAX,
                 auto_range=False):
        super().__init__()
        self.setWindowTitle("ESP 表面可视化 (cub_viewer 引擎)")
        self.resize(1000, 720)

        self._density_path = density_path
        self._esp_path = esp_path
        self._isolevel = isolevel
        self._vmin, self._vmax = vmin, vmax
        self._auto_range = auto_range

        self.setObjectName("ESPRoot")
        self.setStyleSheet(_QSS)

        root = QWidget()
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # 工具条
        lay.addWidget(self._build_toolbar())

        # GL 画布
        self.glw = CubGLWidget(self)
        self.glw.set_status_callback(self._set_status)
        self.glw.setSizePolicy(
            QWidget().sizePolicy().Expanding, QWidget().sizePolicy().Expanding)
        self.glw.setStyleSheet("border:none; background:transparent;")
        lay.addWidget(self.glw, stretch=1)

        # 参数区
        self._params = self._build_params()
        lay.addWidget(self._params)

        # 状态
        self._status = QLabel("就绪 — 请选择 density.cub 与 ESP.cub")
        self._status.setObjectName("ESPStatus")
        lay.addWidget(self._status)

        # 若命令行已给文件，自动加载
        if density_path and esp_path:
            QTimer.singleShot(0, self._auto_load)

    def _build_toolbar(self):
        bar = QWidget()
        bar.setObjectName("ESPToolBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(6, 4, 6, 4)
        h.setSpacing(6)

        btn_d = QPushButton("密度 cube…")
        btn_d.setToolTip("电子密度场 cube (density.cub)")
        btn_d.clicked.connect(lambda: self._pick("density"))
        h.addWidget(btn_d)

        self._d_lbl = QLabel("未选择")
        self._d_lbl.setMinimumWidth(120)
        h.addWidget(self._d_lbl, stretch=1)

        btn_e = QPushButton("ESP cube…")
        btn_e.setToolTip("静电势场 cube (ESP.cub)")
        btn_e.clicked.connect(lambda: self._pick("esp"))
        h.addWidget(btn_e)

        self._e_lbl = QLabel("未选择")
        self._e_lbl.setMinimumWidth(120)
        h.addWidget(self._e_lbl, stretch=1)

        btn_render = QPushButton("渲染 ESP 表面")
        btn_render.setStyleSheet("font-weight:bold;")
        btn_render.clicked.connect(self.render_esp)
        h.addWidget(btn_render)

        btn_reset = QPushButton("重置视角")
        btn_reset.clicked.connect(lambda: self.glw.reset_view())
        h.addWidget(btn_reset)

        return bar

    def _build_params(self):
        box = QFrame()
        box.setObjectName("ESPParams")
        outer = QHBoxLayout(box)
        outer.setContentsMargins(6, 4, 6, 6)
        outer.setSpacing(8)

        g = QGroupBox("表面 / 色标参数")
        gl = QGridLayout(g)
        gl.setContentsMargins(8, 6, 8, 6)
        gl.setSpacing(4)

        gl.addWidget(QLabel("密度等值面:"), 0, 0)
        self._iso_edit = QLineEdit(f"{self._isolevel:.4f}")
        self._iso_edit.setValidator(_QDV(0.0001, 0.5, 4))
        self._iso_edit.setMaximumWidth(72)
        gl.addWidget(self._iso_edit, 0, 1)

        gl.addWidget(QLabel("色标下限 (vmin):"), 1, 0)
        self._vmin_edit = QLineEdit(f"{self._vmin:.3f}")
        self._vmin_edit.setValidator(_QDV(-5, 5, 3))
        self._vmin_edit.setMaximumWidth(72)
        gl.addWidget(self._vmin_edit, 1, 1)

        gl.addWidget(QLabel("色标上限 (vmax):"), 2, 0)
        self._vmax_edit = QLineEdit(f"{self._vmax:.3f}")
        self._vmax_edit.setValidator(_QDV(-5, 5, 3))
        self._vmax_edit.setMaximumWidth(72)
        gl.addWidget(self._vmax_edit, 2, 1)

        gl.addWidget(QLabel("红=负(富电子), 白=0, 蓝=正(缺电子) (kcal/mol)"), 0, 2, 3, 1)
        outer.addWidget(g, stretch=1)

        # 显示
        gb = QGroupBox("显示")
        bl = QGridLayout(gb)
        bl.setContentsMargins(8, 6, 8, 6)
        bl.setSpacing(4)
        bl.addWidget(QLabel("不透明:"), 0, 0)
        self._op_sld = QSlider(Qt.Horizontal)
        self._op_sld.setRange(5, 100)
        self._op_sld.setValue(100)
        self._op_sld.valueChanged.connect(self._on_op)
        bl.addWidget(self._op_sld, 0, 1)
        self._dp_chk = QCheckBox(
            f"Depth peeling ({IBOVIEW_DEFAULTS['DepthPeelingLayers']} 层)")
        self._dp_chk.setChecked(True)
        self._dp_chk.toggled.connect(lambda on: self.glw.set_depth_peeling(on))
        bl.addWidget(self._dp_chk, 1, 0, 1, 2)
        outer.addWidget(gb, stretch=1)
        return box

    # ── 交互 ──
    def _pick(self, which):
        p, _ = open_file(
            self, "选择 cube 文件", "", "Cube Files (*.cub *.cube);;All (*)")
        if not p:
            return
        if which == "density":
            self._density_path = p
            self._d_lbl.setText(os.path.basename(p))
        else:
            self._esp_path = p
            self._e_lbl.setText(os.path.basename(p))

    def _auto_load(self):
        self._d_lbl.setText(os.path.basename(self._density_path))
        self._e_lbl.setText(os.path.basename(self._esp_path))
        self.render_esp()

    def _set_status(self, msg):
        self._status.setText(str(msg))

    def _on_op(self, v):
        self.glw.set_opacity(max(0.05, v / 100.0))

    # ── 核心渲染 ──
    def render_esp(self):
        if not self._density_path or not self._esp_path:
            self._set_status("请先选择 density.cub 与 ESP.cub")
            return
        try:
            self._isolevel = float(self._iso_edit.text())
            self._vmin = float(self._vmin_edit.text())
            self._vmax = float(self._vmax_edit.text())
        except ValueError:
            self._set_status("参数解析失败，使用默认值")
        if abs(self._vmax - self._vmin) < 1e-6:
            self._set_status("色标上限不能等于下限")
            return

        self._set_status("读取 density.cub …")
        try:
            density_cube = read_cube(self._density_path)
            esp_cube = read_cube(self._esp_path)
        except Exception as e:
            self._set_status(f"读取失败: {e}")
            traceback.print_exc()
            return

        self._set_status("提取 ESP 表面 …")
        try:
            surf, _ = extract_esp_surface(
                density_cube, esp_cube,
                isolevel=self._isolevel, vmin=self._vmin, vmax=self._vmax,
                auto_range=self._auto_range)
        except Exception as e:
            self._set_status(f"提取失败: {e}")
            traceback.print_exc()
            return

        if surf.vertex_count == 0:
            self._set_status("密度等值面为空（isolevel 可能不合适）")
            return

        # 把 ESP 表面交给 CubGLWidget 的渲染槽位（复用其原子模型与着色器）
        # __init__ 已初始化 _sp/_pc/_nc/_atom_scale/_bond_scale/_dp_layers。
        self.glw._cube = density_cube           # 供球棍模型/包围球使用
        self.glw._pos_surf = surf
        self.glw._neg_surf = None
        ctr, r = compute_bounding_sphere(density_cube)
        self.glw._scene_r = r
        self.glw.cam.set_center_zoom(ctr, r)
        self.glw._gen_atoms()
        self.glw._needs_upload = True
        self.glw.update()

        self._set_status(f"就绪: {surf.vertex_count} 顶点, "
                         f"色标 [{self._vmin}, {self._vmax}] kcal/mol")


def QTimer_singleshot(fn):
    """延迟到事件循环启动后执行（避免 GL 上下文未就绪）。"""
    QTimer.singleShot(0, fn)


# ════════════════════════════════════════════════════════════════
# 3. 命令行入口 / 离屏渲染
# ════════════════════════════════════════════════════════════════

def render_to_file(density_path, esp_path, out_png, isolevel=DEFAULT_ISOLEVEL,
                   vmin=DEFAULT_VMIN, vmax=DEFAULT_VMAX, dpi=600,
                   cmap="RWB (红-白-蓝)", auto_range=False):
    """离屏渲染 ESP 表面并保存 PNG（复用 CubGLWidget.export_image）。"""
    if not _ensure_pyopengl():
        raise RuntimeError("PyOpenGL 不可用")
    from PyQt5.QtCore import QTimer
    app = QApplication.instance() or QApplication(sys.argv)
    w = ESPViewer(density_path, esp_path, isolevel, vmin, vmax,
                  auto_range=auto_range)
    w.show()
    # 触发 paintGL 完成 GL 初始化与 surface 上传
    app.processEvents()

    done = {}

    def _shoot():
        try:
            w.glw.export_image(out_png, dpi=dpi)
            done["ok"] = True
        except Exception as e:  # noqa
            import traceback as _tb
            _tb.print_exc()
            done["ok"] = False
        finally:
            QApplication.instance().quit()

    QTimer.singleShot(300, _shoot)  # 等待 GL 完全就绪后离屏导出
    app.exec_()
    if not done.get("ok"):
        raise RuntimeError("离屏渲染失败，详见上方 traceback")
    return out_png


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="基于 cub_viewer 引擎的 ESP 等值面可视化")
    ap.add_argument("-d", "--density", required=False,
                    help="电子密度 cube 文件 (density.cub)")
    ap.add_argument("-e", "--esp", required=False,
                    help="静电势 cube 文件 (ESP.cub)")
    ap.add_argument("--isolevel", type=float, default=DEFAULT_ISOLEVEL,
                    help="密度等值面阈值 (默认 0.001, vdW 表面)")
    ap.add_argument("--vmin", type=float, default=DEFAULT_VMIN,
                    help="ESP 色标下限 kcal/mol (默认 -0.03)")
    ap.add_argument("--vmax", type=float, default=DEFAULT_VMAX,
                    help="ESP 色标上限 kcal/mol (默认 0.03)")
    ap.add_argument("-o", "--output", default=None,
                    help="离屏渲染输出 PNG（无此参数则打开交互窗口）")
    ap.add_argument("--dpi", type=float, default=600, help="输出 DPI (默认 600)")
    _cmap_names = "|".join(ESP_CMAPS.keys())
    ap.add_argument("--cmap", default="RWB (红-白-蓝)",
                    help=f"ESP 配色方案: {_cmap_names}")
    ap.add_argument("--auto-range", action="store_true",
                    help="按 ESP 实际分布自适应色标范围（颜色铺满、过渡更自然）")
    args = ap.parse_args(argv)

    if args.output:
        if not args.density or not args.esp:
            ap.error("离屏渲染需要同时提供 --density 与 --esp")
        out = render_to_file(args.density, args.esp, args.output,
                            args.isolevel, args.vmin, args.vmax, args.dpi,
                            cmap=args.cmap, auto_range=args.auto_range)
        print(f"已保存: {out}")
        return

    if not _ensure_pyopengl():
        print("错误: 未安装 PyOpenGL。请运行 pip install PyOpenGL PyOpenGL-accelerate")
        return
    app = QApplication(sys.argv)
    w = ESPViewer(args.density, args.esp, args.isolevel, args.vmin, args.vmax,
                  cmap=args.cmap)
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
