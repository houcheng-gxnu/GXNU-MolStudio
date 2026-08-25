# -*- coding: utf-8 -*-
"""
igmh_panel.py — IGMH/IRI 分析面板（整合自 IGMH_Toolbox V4）
=============================================================

从 `.fchk` 出发：
  1. 定义分子片段（片段 1 / 片段 2，左画布 Shift+左键框选原子归属）；
  2. 后台调 Multiwfn（IGMH: 20→11→2→片段→网格→2→3；IRI: 20→4→…），
     产出 dg_inter.cub / dg_intra.cub / dg.cub / sl2r.cub；
  3. 用 dg_inter 定几何等值面、sl2r（sign(λ₂)ρ）按 BGR 色标
     （蓝=吸引、绿=弱、红=排斥）逐顶点着色，加载到左侧 OpenGL 画布；
  4. IGM Map 散点图（sign(λ₂)ρ vs δg）。

本模块 Multiwfn 命令序列、BGR 着色与复合场移植自 IGMH_Toolbox V4
(igmh_analysis.py / igmh_viewer_demo.py / igmh_scatter.py)。
IGMH 方法: Tian Lu, Qinxue Chen, J. Comput. Chem. 2022, 43, 539-553.
"""

import os
import subprocess
import traceback

import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QCheckBox, QSlider, QRadioButton, QGroupBox,
    QTextEdit, QFileDialog, QMessageBox, QFrame, QDialog, QSizePolicy,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from file_dialogs import open_file, save_file

from marching_cubes import read_cube, marching_cubes, compute_bounding_sphere, _trilinear


# ═══════════════════════════════════════════════════════════════
# BGR 着色 + 复合场（移植自 IGMH_Toolbox igmh_viewer_demo.py）
# ═══════════════════════════════════════════════════════════════

def _grid_index(cube, world_xyz):
    """世界坐标 → cube 分数索引（三线性采样用）。"""
    basis = np.array([cube.dx, cube.dy, cube.dz], dtype=np.float64)
    try:
        inv = np.linalg.inv(basis)
    except np.linalg.LinAlgError:
        inv = np.eye(3)
    rel = world_xyz - cube.origin.astype(np.float64)
    return rel @ inv


def sample_volume(cube, world_xyz):
    """在 world_xyz 处对 cube.data 做三线性采样，返回 (N,) 标量。"""
    idx = _grid_index(cube, np.asarray(world_xyz, dtype=np.float64))
    dims = np.array([cube.nx, cube.ny, cube.nz], dtype=np.int64)
    idx0 = np.floor(idx).astype(np.int64)
    np.clip(idx0, 0, dims - 1, out=idx0)
    idx1 = np.minimum(idx0 + 1, dims - 1)
    frac = idx - idx0
    return _trilinear(cube.data.astype(np.float32), idx0, idx1, frac)


def bgr_color(scalars, cmin, cmax, mid=0.5, strength_alpha=False,
              base_alpha=0.25, full_alpha=None):
    """复刻 VMD "BGR" 色标: 蓝(负)=吸引, 绿(中)=弱, 红(正)=排斥。

    strength_alpha=True 时 alpha 随 |sign(λ₂)ρ| 增强（NCIPLOT 风格）。
    """
    s = np.asarray(scalars, dtype=np.float64)
    span = (cmax - cmin) or 1e-9
    u = np.clip((s - cmin) / span, 0.0, 1.0)
    rgb = np.empty((len(s), 3), dtype=np.float32)
    lo = u < mid
    hi = ~lo
    f = np.clip(u[lo] / mid, 0.0, 1.0) if mid > 0 else 0.0
    rgb[lo, 0] = 0.0
    rgb[lo, 1] = f
    rgb[lo, 2] = 1.0 - f
    f = np.clip((u[hi] - mid) / (1.0 - mid), 0.0, 1.0) if mid < 1 else 0.0
    rgb[hi, 0] = f
    rgb[hi, 1] = 1.0 - f
    rgb[hi, 2] = 0.0

    if strength_alpha:
        ref = max(abs(cmin), abs(cmax)) or 1e-9
        t = np.clip(np.abs(s) / ref, 0.0, 1.0)
        fa = 1.0 if full_alpha is None else full_alpha
        a = np.clip(base_alpha + (fa - base_alpha) * t, 0.0, 1.0)
    else:
        a = np.ones(len(s), dtype=np.float64)
    return rgb, a.astype(np.float32)


class IGMHCompositeField:
    """复合面：一个 cube 定几何（正等值面），另一个 cube 定顶点颜色（BGR）。"""

    def __init__(self, glw):
        self.glw = glw
        self.geo_cube = None
        self.map_cube = None
        self.iso = 0.02
        self.cmin = -0.05
        self.cmax = 0.05
        self.mid = 0.5
        self.enabled = True
        self.use_strength_alpha = True
        self._surf = None

    def load(self, geo_path, map_path, iso):
        self.geo_cube = read_cube(geo_path)
        self.map_cube = read_cube(map_path)
        self.iso = iso
        self._rebuild()

    def set_iso(self, iso):
        if self.geo_cube is None:
            return
        self.iso = iso
        self._rebuild()
        self.push()

    def set_crange(self, cmin, cmax):
        self.cmin, self.cmax = cmin, cmax
        if self._surf is not None and self._surf.vertex_count > 0:
            self._recolor()
            self.push()

    def set_strength_alpha(self, on):
        if self.use_strength_alpha == on:
            return
        self.use_strength_alpha = on
        if self._surf is not None and self._surf.vertex_count > 0:
            self._recolor()
            self.push()

    def _rebuild(self):
        if self.geo_cube is None:
            self._surf = None
            return
        surf = marching_cubes(self.geo_cube, self.iso, flip_normal=False)
        if surf.vertex_count == 0:
            self._surf = surf
            return
        vals = sample_volume(self.map_cube, surf.vertices)
        rgb, a = bgr_color(vals, self.cmin, self.cmax, self.mid,
                           strength_alpha=self.use_strength_alpha)
        surf.colors = np.column_stack([rgb, a]).astype(np.float32)
        self._surf = surf

    def _recolor(self):
        if self._surf is None or self._surf.vertex_count == 0:
            return
        vals = sample_volume(self.map_cube, self._surf.vertices)
        rgb, a = bgr_color(vals, self.cmin, self.cmax, self.mid,
                           strength_alpha=self.use_strength_alpha)
        self._surf.colors = np.column_stack([rgb, a]).astype(np.float32)

    def push(self):
        self.glw._pos_surf = self._surf if self.enabled else None
        self.glw._neg_surf = None
        self.glw._needs_upload = True
        self.glw.update()

    def vertex_count(self):
        return self._surf.vertex_count if self._surf else 0


# ═══════════════════════════════════════════════════════════════
# 片段范围字符串
# ═══════════════════════════════════════════════════════════════

def compress_ranges(indices):
    """把原子索引列表压成 '1-5,10-12' 形式的范围字符串。"""
    indices = sorted(set(int(i) for i in indices if int(i) > 0))
    if not indices:
        return ""
    parts = []
    start = prev = indices[0]
    for i in indices[1:]:
        if i == prev + 1:
            prev = i
        else:
            parts.append(str(start) if start == prev else f"{start}-{prev}")
            start = prev = i
    parts.append(str(start) if start == prev else f"{start}-{prev}")
    return ",".join(parts)


def parse_ranges(text):
    """把 '1-5,10-12' 形式的范围字符串解析成原子索引集合。"""
    result = set()
    if not text:
        return result
    for part in str(text).replace(" ", "").split(","):
        if not part:
            continue
        try:
            if "-" in part:
                a, b = part.split("-", 1)
                result.update(range(int(a), int(b) + 1))
            else:
                result.add(int(part))
        except ValueError:
            continue
    return result


# ═══════════════════════════════════════════════════════════════
# IGMH 分析 worker
# ═══════════════════════════════════════════════════════════════

class IgmhWorker(QThread):
    finished = pyqtSignal(object)   # dict: out_dir / files / is_iri
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, fchk, mw_exe, frag1, frag2, grid_q, out_dir, is_iri=False):
        super().__init__()
        self.fchk = fchk
        self.mw_exe = mw_exe
        self.frag1 = frag1
        self.frag2 = frag2
        self.grid_q = grid_q
        self.out_dir = out_dir
        self.is_iri = is_iri
        self._proc = None

    def kill(self):
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.kill()
            except Exception:
                pass

    def run(self):
        try:
            os.makedirs(self.out_dir, exist_ok=True)
            if self.is_iri:
                input_lines = ["20", "4", str(self.grid_q), "3", "0", "0", "q"]
                expected = ["func1.cub", "func2.cub", "output.txt"]
            else:
                input_lines = ["20", "11", "2", self.frag1 or "1-3",
                               self.frag2 or "c", str(self.grid_q),
                               "2", "3", "0", "0", "q"]
                expected = ["dg_inter.cub", "dg_intra.cub", "dg.cub",
                            "sl2r.cub", "output.txt"]
            input_seq = "\n".join(input_lines) + "\n"

            script_file = os.path.join(self.out_dir, "multiwfn_input.txt")
            with open(script_file, "w", encoding="utf-8", newline="\n") as f:
                f.write(input_seq)

            env = os.environ.copy()
            if "Multiwfnpath" not in env:
                env["Multiwfnpath"] = os.path.dirname(self.mw_exe)

            self.progress.emit("运行 Multiwfn IGMH 分析 …")
            self._proc = subprocess.Popen(
                [self.mw_exe, self.fchk],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="ignore",
                cwd=self.out_dir, env=env)
            try:
                stdout, _ = self._proc.communicate(input=input_seq, timeout=1800)
            except subprocess.TimeoutExpired:
                try:
                    self._proc.kill()
                except Exception:
                    pass
                self._proc.communicate()
                raise RuntimeError("Multiwfn 运行超时（30 分钟）")
            out_lines = []
            for line in (stdout or "").splitlines():
                out_lines.append(line)
                stripped = line.rstrip()
                if len(stripped) > 100:
                    stripped = stripped[:97] + "..."
                self.progress.emit(stripped)

            files = {}
            for fn in expected:
                fp = os.path.join(self.out_dir, fn)
                if os.path.exists(fp):
                    files[fn] = fp
                    self.progress.emit(f"[OK] {fn} ({os.path.getsize(fp)} bytes)")
                else:
                    self.progress.emit(f"[Missing] {fn}")

            # Multiwfn 无任何产物（命令失败/输入错误）→ 走 error，避免 UI 误报“完成”。
            # 注意 settings.ini 的 IGMvdwscl≠0 时 dg_intra/dg 本就不导出，属正常，
            # 因此只对“一个文件都没有”判失败。
            if not files:
                raise RuntimeError(
                    "Multiwfn 未生成任何输出文件（可能输入错误或计算失败），"
                    "请检查上方日志输出")
            self.finished.emit({"out_dir": self.out_dir, "files": files,
                                "is_iri": self.is_iri})
        except Exception as e:
            traceback.print_exc()
            self.error.emit(str(e))


# ═══════════════════════════════════════════════════════════════
# IGM 散点图对话框（移植自 igmh_scatter.py，简化版）
# ═══════════════════════════════════════════════════════════════

class IgmScatterDialog(QDialog):
    """sign(λ₂)ρ vs δg 散点图（matplotlib 嵌入）。"""

    def __init__(self, data_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("IGM Map 散点图")
        self.resize(760, 820)
        self.data_path = data_path
        self._fig = None

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        top = QHBoxLayout()
        top.addWidget(QLabel("δg 列:"))
        self.combo_col = QComboBox()
        self.combo_col.addItems(["δg_inter (列0)", "δg_intra (列1)", "δg (列2)"])
        top.addWidget(self.combo_col)
        self.btn_draw = QPushButton("绘制")
        self.btn_draw.setStyleSheet("font-weight:bold;")
        self.btn_draw.clicked.connect(self._draw)
        top.addWidget(self.btn_draw)
        self.btn_save = QPushButton("保存 PNG")
        self.btn_save.clicked.connect(self._save)
        top.addWidget(self.btn_save)
        top.addStretch()
        v.addLayout(top)

        self.container = QWidget()
        self.container.setStyleSheet("background:#FFFFFF; border:1px solid #CBD5E1;")
        self.container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        v.addWidget(self.container, stretch=1)

        self._draw()

    def _build_figure(self, dg, sl2r, dg_col):
        import matplotlib
        matplotlib.use("Qt5Agg")
        from matplotlib.figure import Figure
        from matplotlib.colors import LinearSegmentedColormap
        from mpl_toolkits.axes_grid1 import make_axes_locatable

        fig = Figure(figsize=(7, 7), dpi=100)
        fig.patch.set_facecolor('white')
        ax = fig.add_subplot(111)
        ax.set_facecolor('#FFFFFF')
        cmap_bgr = LinearSegmentedColormap.from_list(
            'bgr', ['#0000FF', '#00FF00', '#FF0000'])
        ax.set_xlim(-0.05, 0.05)
        ax.set_ylim(0, 0.08)
        ax.set_xticks(np.linspace(-0.05, 0.05, 11))
        ax.set_yticks(np.linspace(0, 0.08, 9))
        ax.set_xlabel(r'$\mathrm{sign}\left(\lambda_2\right)\rho$ (a.u.)', fontsize=10)
        col_names = ['inter', 'intra', '']
        ax.set_ylabel(rf'$\delta g_{{{col_names[dg_col]}}}$ (a.u.)', fontsize=10)
        ax.tick_params(axis='both', labelsize=8)
        sc = ax.scatter(sl2r, dg, c=sl2r, s=1, vmin=-0.05, vmax=0.05, cmap=cmap_bgr)
        divider = make_axes_locatable(ax)
        cax = divider.append_axes("right", size="5%", pad=0.05)
        cbar = fig.colorbar(sc, cax=cax)
        cbar.set_ticks(np.linspace(-0.05, 0.05, 11))
        cbar.ax.tick_params(labelsize=8)
        fig.tight_layout()
        return fig

    def _draw(self):
        try:
            data = np.loadtxt(self.data_path, usecols=(self.combo_col.currentIndex(), 3))
            if data.ndim == 1:
                data = data.reshape(1, -1)
            self._fig = self._build_figure(data[:, 0], data[:, 1],
                                           self.combo_col.currentIndex())
            from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
            # 清空旧画布
            if self.container.layout() is None:
                lay = QVBoxLayout(self.container)
                lay.setContentsMargins(4, 4, 4, 4)
            lay = self.container.layout()
            while lay.count():
                item = lay.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            canvas = FigureCanvas(self._fig)
            lay.addWidget(canvas)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"散点图绘制失败: {e}")

    def _save(self):
        if self._fig is None:
            QMessageBox.warning(self, "提示", "请先绘制")
            return
        path, _ = save_file(self, "保存散点图", "IGMmap.png",
                            "PNG (*.png);;所有文件 (*)")
        if path:
            self._fig.savefig(path, dpi=150, facecolor='white')


# ═══════════════════════════════════════════════════════════════
# IGMH 面板
# ═══════════════════════════════════════════════════════════════

_IGMH_TR = {
    "zh": {
        "open_fchk": "打开 fchk…",
        "generate": "IGMH 分析",
        "iri_analyze": "IRI 分析",
        "scatter": "📊 IGM 散点图",
        "visualize": "可视化",
        "reset_view": "重置视角",
        "clear": "清空",
        "multiwfn": "Multiwfn:",
        "browse": "浏览",
        "fragments": "分子片段定义",
        "frag1": "片段 1:",
        "frag2": "片段 2:",
        "box_frag1": "框选→片段1",
        "box_frag2": "框选→片段2",
        "clear_frag": "清空片段",
        "grid": "网格质量:",
        "iri_mode": "IRI 模式（无需片段）",
        "display": "显示",
        "field": "显示场:",
        "iso": "等值面:",
        "cmin": "色标下限:",
        "cmax": "色标上限:",
        "strength_alpha": "按强度调透明度",
        "opacity": "不透明度:",
        "status_ready": "就绪 — 打开 fchk，Shift+左键在画布框选原子归入片段，再生成分析",
        "no_fchk": "请先打开 .fchk 文件",
        "no_exe": "Multiwfn.exe 不存在，请先在主界面⛒️ 路径设置中配置",
        "running": "正在运行 Multiwfn IGMH 分析（需数分钟）…",
        "done": "IGMH 分析完成，点击「可视化」显示等值面",
        "vis_done": "已加载 {field} 等值面（{n} 顶点）",
        "need_analysis": "请先生成 IGMH 分析",
        "box_hint": "Shift+左键拖框选中原子；点「框选→片段1/2」把选中原子归入对应片段",
        "box_assigned": "框选 {n} 个原子 → 片段 {f}",
        "no_data": "未找到 output.txt（散点图数据）",
    },
    "en": {
        "open_fchk": "Open fchk…",
        "generate": "IGMH Analyze",
        "iri_analyze": "IRI Analyze",
        "scatter": "📊 IGM Scatter",
        "visualize": "Visualize",
        "reset_view": "Reset View",
        "clear": "Clear",
        "multiwfn": "Multiwfn:",
        "browse": "Browse",
        "fragments": "Fragment Definition",
        "frag1": "Fragment 1:",
        "frag2": "Fragment 2:",
        "box_frag1": "Box→Frag 1",
        "box_frag2": "Box→Frag 2",
        "clear_frag": "Clear Fragments",
        "grid": "Grid quality:",
        "iri_mode": "IRI mode (no fragments)",
        "display": "Display",
        "field": "Field:",
        "iso": "Isovalue:",
        "cmin": "Color min:",
        "cmax": "Color max:",
        "strength_alpha": "Strength-based alpha",
        "opacity": "Opacity:",
        "status_ready": "Ready — open fchk, Shift+drag on canvas to assign fragments, then run",
        "no_fchk": "Please open an .fchk file first",
        "no_exe": "Multiwfn.exe not found, configure it in ⛒️ Path Settings first",
        "running": "Running Multiwfn IGMH analysis (takes minutes)…",
        "done": "IGMH done — click Visualize to show the isosurface",
        "vis_done": "Loaded {field} isosurface ({n} vertices)",
        "need_analysis": "Please run the IGMH analysis first",
        "box_hint": "Shift+left-drag to box-select atoms; click Box→Frag 1/2 to assign them",
        "box_assigned": "Box-selected {n} atoms → fragment {f}",
        "no_data": "output.txt not found (scatter data)",
    },
}


class IgmhPanel(QWidget):
    """IGMH/IRI 分析面板：分片段 + Multiwfn + BGR 等值面 + 散点图。"""

    def __init__(self, glw=None, multiwfn_path="", get_fchk=None, parent=None,
                 get_multiwfn=None, log_func=None, iso_slider=None):
        super().__init__(parent)
        self.lang = "zh"
        self.glw = glw
        self.multiwfn_path = multiwfn_path or ""
        self._get_fchk = get_fchk or (lambda: None)
        # Multiwfn 路径统一走主窗口 ⚙️ 路径设置（实时读取）
        self._get_mw = (get_multiwfn if callable(get_multiwfn)
                        else (lambda: multiwfn_path or ""))
        self._log_func = log_func if callable(log_func) else None
        self.iso_slider = iso_slider if iso_slider is not None else None
        self.fchk_file = None
        self._worker = None
        self._frag1 = set()
        self._frag2 = set()
        self._target_frag = 1
        self._files = {}        # 分析产物 {fn: path}
        self._out_dir = ""
        self._is_iri = False
        self._field = IGMHCompositeField(glw) if glw is not None else None

        self._build_ui()
        self._apply_lang()

        # 与画布等值面滑块双向同步（画布侧变化 → 更新本面板滑块）
        if self.iso_slider is not None:
            self.iso_slider.valueChanged.connect(self._sync_iso_from_canvas)

        if self.glw is not None:
            self.glw.set_box_select_callback(self._on_box_select)

    # ── 语言 ──
    def _t(self, key, **fmt):
        s = _IGMH_TR.get(self.lang, _IGMH_TR["zh"]).get(key, key)
        return s.format(**fmt) if fmt else s

    def _apply_lang(self):
        self.btn_generate.setText(self._t("generate"))
        self.btn_iri.setText(self._t("iri_analyze"))
        self.btn_scatter.setText(self._t("scatter"))
        self.btn_visualize.setText(self._t("visualize"))
        self.btn_reset.setText(self._t("reset_view"))
        self.btn_clear.setText(self._t("clear"))
        self.grp_frag.setTitle(self._t("fragments"))
        self.lbl_frag1.setText(self._t("frag1"))
        self.lbl_frag2.setText(self._t("frag2"))
        self.btn_box1.setText(self._t("box_frag1"))
        self.btn_box2.setText(self._t("box_frag2"))
        self.btn_clear_frag.setText(self._t("clear_frag"))
        self.lbl_grid.setText(self._t("grid"))
        self.chk_iri.setText(self._t("iri_mode"))
        self.grp_disp.setTitle(self._t("display"))
        self.lbl_field.setText(self._t("field"))
        self.lbl_iso.setText(self._t("iso"))
        self.lbl_cmin.setText(self._t("cmin"))
        self.lbl_cmax.setText(self._t("cmax"))
        self.chk_strength.setText(self._t("strength_alpha"))
        self.lbl_op.setText(self._t("opacity"))
        self._set_status(self._t("status_ready"))

    def set_lang(self, lang):
        self.lang = "zh" if lang == "zh" else "en"
        self._apply_lang()

    # ── UI ──
    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)

        # 主操作按钮（创建，布局放在片段定义下方一行）
        self.btn_generate = QPushButton()
        self.btn_generate.setStyleSheet("font-weight:bold;")
        self.btn_generate.clicked.connect(self._generate)
        self.btn_iri = QPushButton()
        self.btn_iri.clicked.connect(self._on_iri_analysis)
        self.btn_visualize = QPushButton()
        self.btn_visualize.clicked.connect(self._visualize)
        self.btn_scatter = QPushButton()
        self.btn_scatter.clicked.connect(self._open_scatter)
        self.btn_reset = QPushButton()
        self.btn_reset.clicked.connect(self._reset_view)
        self.btn_clear = QPushButton()
        self.btn_clear.clicked.connect(self._clear_canvas)

        # 网格质量 + IRI 模式（并入按钮行）
        self.lbl_grid = QLabel()
        self.combo_grid = QComboBox()
        self.combo_grid.addItems(["低 (1)", "中 (2)", "高 (3)"])
        self.combo_grid.setCurrentIndex(1)
        self.chk_iri = QCheckBox()

        # 片段定义
        self.grp_frag = QGroupBox()
        fg = QGridLayout(self.grp_frag)
        fg.setContentsMargins(4, 2, 4, 2)
        fg.setSpacing(3)
        self.lbl_frag1 = QLabel()
        fg.addWidget(self.lbl_frag1, 0, 0)
        self.edit_frag1 = QLineEdit()
        fg.addWidget(self.edit_frag1, 0, 1)
        self.btn_box1 = QPushButton()
        self.btn_box1.clicked.connect(lambda: self._set_target(1))
        fg.addWidget(self.btn_box1, 0, 2)
        self.lbl_frag2 = QLabel()
        fg.addWidget(self.lbl_frag2, 1, 0)
        self.edit_frag2 = QLineEdit()
        fg.addWidget(self.edit_frag2, 1, 1)
        self.btn_box2 = QPushButton()
        self.btn_box2.clicked.connect(lambda: self._set_target(2))
        fg.addWidget(self.btn_box2, 1, 2)
        self.btn_clear_frag = QPushButton()
        self.btn_clear_frag.clicked.connect(self._clear_fragments)
        fg.addWidget(self.btn_clear_frag, 2, 0, 1, 3)
        fg.setColumnStretch(1, 1)
        v.addWidget(self.grp_frag)

        # 操作一行（挨着片段定义，无圆角框）：
        # IGMH 分析 / IRI 分析 / 可视化 / IGM 散点图 / 重置视角 / 清空 /
        # 网格质量 / IRI 模式
        op_row = QWidget()
        orh = QHBoxLayout(op_row)
        orh.setContentsMargins(0, 0, 0, 0)
        orh.setSpacing(6)
        orh.addWidget(self.btn_generate)
        orh.addWidget(self.btn_iri)
        orh.addWidget(self.btn_visualize)
        orh.addWidget(self.btn_scatter)
        orh.addWidget(self.btn_reset)
        orh.addWidget(self.btn_clear)
        orh.addWidget(self.lbl_grid)
        orh.addWidget(self.combo_grid)
        orh.addWidget(self.chk_iri)
        orh.addStretch()
        v.addWidget(op_row)

        # 显示参数
        self.grp_disp = QGroupBox()
        dg = QGridLayout(self.grp_disp)
        dg.setContentsMargins(4, 2, 4, 2)
        dg.setSpacing(3)
        self.lbl_field = QLabel()
        dg.addWidget(self.lbl_field, 0, 0)
        self.combo_field = QComboBox()
        self.combo_field.addItems(["dg_inter", "dg_intra", "dg", "func2 (IRI)"])
        dg.addWidget(self.combo_field, 0, 1)
        self.lbl_iso = QLabel()
        dg.addWidget(self.lbl_iso, 0, 2)
        self.sld_iso = QSlider(Qt.Horizontal)
        self.sld_iso.setRange(5, 2000)              # iso = 值/1000（0.005..2.0，含 IRI 默认 1.0）
        self.sld_iso.setValue(20)                   # 默认 0.02
        self.sld_iso.valueChanged.connect(self._on_iso_slider)
        dg.addWidget(self.sld_iso, 0, 3)
        self.lbl_iso_val = QLabel("0.02")
        self.lbl_iso_val.setMinimumWidth(38)
        dg.addWidget(self.lbl_iso_val, 0, 4)
        # 等值面精确输入框（a.u.）
        self.edit_iso = QLineEdit("0.020")
        self.edit_iso.setMaximumWidth(58)
        self.edit_iso.setToolTip("精确输入等值面大小（a.u.，0.005–2.0），回车生效")
        self.edit_iso.editingFinished.connect(self._on_iso_edit)
        dg.addWidget(self.edit_iso, 0, 5)
        self._iso_val = 0.02
        self.lbl_cmin = QLabel()
        dg.addWidget(self.lbl_cmin, 1, 0)
        self.edit_cmin = QLineEdit("-0.05")
        self.edit_cmin.setMaximumWidth(60)
        dg.addWidget(self.edit_cmin, 1, 1)
        self.lbl_cmax = QLabel()
        dg.addWidget(self.lbl_cmax, 1, 2)
        self.edit_cmax = QLineEdit("0.05")
        self.edit_cmax.setMaximumWidth(60)
        dg.addWidget(self.edit_cmax, 1, 3)
        self.chk_strength = QCheckBox()
        self.chk_strength.setChecked(True)
        self.chk_strength.toggled.connect(self._on_strength)
        dg.addWidget(self.chk_strength, 2, 0, 1, 2)
        self.lbl_op = QLabel()
        dg.addWidget(self.lbl_op, 2, 2)
        self.sld_op = QSlider(Qt.Horizontal)
        self.sld_op.setRange(5, 100)
        self.sld_op.setValue(100)
        self.sld_op.valueChanged.connect(self._on_opacity)
        dg.addWidget(self.sld_op, 2, 3)
        # 透明度精确输入框（不透明度 %，与滑块语义一致）
        self.edit_op = QLineEdit("100")
        self.edit_op.setMaximumWidth(58)
        self.edit_op.setToolTip("精确输入不透明度（5–100 %），回车生效")
        self.edit_op.editingFinished.connect(self._on_op_edit)
        dg.addWidget(self.edit_op, 2, 5)
        v.addWidget(self.grp_disp)
        # 吸收拉伸面板的多余空间，各区块保持紧凑（挨着，不再被拉高）
        v.addStretch(1)

    # ── 状态/日志 ──
    def _set_status(self, msg):
        # 状态区已移除：状态消息并入运行日志
        self._log(str(msg))

    def _log(self, msg):
        # 输出已整合到主窗口左侧运行日志（若已挂接 log_func）
        if self._log_func is not None:
            self._log_func(str(msg))

    # ── 浏览 ──
    def _browse_fchk(self):
        p, _ = open_file(
            self, "选择 fchk 文件", "",
            "Formatted Checkpoint (*.fchk *.fch);;所有文件 (*)")
        if p:
            self.fchk_file = p
            self._log("fchk: " + os.path.basename(p))
            self._load_molecule_to_canvas(p)

    def _load_molecule_to_canvas(self, fchk):
        if self.glw is None:
            return
        try:
            from molcanvas import get_atoms_from_fchk, get_bonds_from_fchk
            atoms = get_atoms_from_fchk(fchk)
            bonds = get_bonds_from_fchk(atoms)
            self.glw.set_molecule(atoms, bonds)
            self.glw.frame_to_molecule()
        except Exception as e:
            self._log("载入分子失败: " + str(e))

    def _resolve_fchk(self):
        f = (self.fchk_file or "").strip()
        if f and os.path.exists(f):
            return f
        f2 = (self._get_fchk() or "").strip()
        return f2 if f2 and os.path.exists(f2) else ""

    # ── 片段管理 ──
    def _set_target(self, frag):
        self._target_frag = frag
        self._set_status(self._t("box_hint"))

    def _on_box_select(self, indices):
        """画布 Shift+框选原子 → 归入当前目标片段。"""
        if not indices:
            return
        frag = getattr(self, "_target_frag", 1)
        if frag == 1:
            self._frag1.update(indices)
            self._frag2.difference_update(indices)
        else:
            self._frag2.update(indices)
            self._frag1.difference_update(indices)
        self.edit_frag1.setText(compress_ranges(self._frag1))
        self.edit_frag2.setText(compress_ranges(self._frag2))
        self._apply_fragment_colors()
        self._set_status(self._t("box_assigned", n=len(indices), f=frag))
        self._log(self._t("box_assigned", n=len(indices), f=frag))

    def _clear_fragments(self):
        self._frag1.clear()
        self._frag2.clear()
        self.edit_frag1.clear()
        self.edit_frag2.clear()
        self._apply_fragment_colors()
        self._set_status(self._t("box_hint"))

    def _apply_fragment_colors(self):
        if self.glw is None:
            return
        overrides = {}
        for idx in self._frag1:
            overrides[idx] = (1.0, 0.25, 0.25)   # 片段 1：红
        for idx in self._frag2:
            overrides[idx] = (0.25, 0.75, 1.0)   # 片段 2：青
        self.glw.set_atom_colors(overrides)

    def _frag_text(self, edit, fallback=""):
        t = edit.text().strip()
        return t if t else fallback

    # ── 分析 ──
    def _on_iri_analysis(self):
        """IRI 分析：勾选 IRI 模式后直接生成（相当于 IRI 模式）。"""
        self.chk_iri.blockSignals(True)
        self.chk_iri.setChecked(True)
        self.chk_iri.blockSignals(False)
        self._generate()

    def _generate(self):
        if self._worker is not None and self._worker.isRunning():
            return
        fchk = self._resolve_fchk()
        mw = (self._get_mw() or "").strip()
        if not fchk or not os.path.exists(fchk):
            QMessageBox.critical(self, "错误", self._t("no_fchk"))
            return
        if not mw or not os.path.exists(mw):
            QMessageBox.critical(self, "错误", self._t("no_exe"))
            return
        is_iri = self.chk_iri.isChecked()
        stem = os.path.splitext(os.path.basename(fchk))[0]
        out_dir = os.path.join(os.path.dirname(os.path.abspath(fchk)),
                               f"{stem}_IGMH")
        self._is_iri = is_iri
        self._out_dir = out_dir

        frag1 = self._frag_text(self.edit_frag1) or compress_ranges(self._frag1)
        frag2 = self._frag_text(self.edit_frag2) or compress_ranges(self._frag2) or "c"

        self.btn_generate.setEnabled(False)
        self._set_status(self._t("running"))
        self._log(f"IGMH 分析（{'IRI' if is_iri else 'IGMH'}）: "
                  f"frag1={frag1} frag2={frag2} -> {out_dir}")
        self._worker = IgmhWorker(fchk, mw, frag1, frag2,
                                  self.combo_grid.currentIndex() + 1,
                                  out_dir, is_iri)
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.progress.connect(self._log)
        self._worker.start()

    def _on_done(self, result):
        self.btn_generate.setEnabled(True)
        self._files = result.get("files", {})
        self._out_dir = result.get("out_dir", self._out_dir)
        self._is_iri = result.get("is_iri", self._is_iri)
        # 更新显示场下拉：只列出实际生成的场
        # （Multiwfn settings.ini 中 IGMvdwscl≠0 时不导出 dg_intra/dg）
        if self._is_iri:
            self.combo_field.clear()
            if "func2.cub" in self._files:
                self.combo_field.addItem("func2 (IRI)")
            self._iso_val = 1.0
            self.lbl_iso_val.setText("1.00")
            self.sld_iso.blockSignals(True)
            self.sld_iso.setValue(1000)             # 1.0 在滑块范围内可表示
            self.sld_iso.blockSignals(False)
            self.edit_iso.blockSignals(True)
            self.edit_iso.setText("1.000")
            self.edit_iso.blockSignals(False)
            self.edit_cmin.setText("-0.04")
            self.edit_cmax.setText("0.02")
        else:
            fields = [("dg_inter.cub", "dg_inter"),
                      ("dg_intra.cub", "dg_intra"),
                      ("dg.cub", "dg")]
            self.combo_field.clear()
            for fn, label in fields:
                if fn in self._files:
                    self.combo_field.addItem(label)
            # IGMH（非 IRI）运行完成：清掉 IRI 遗留的 iso/颜色范围状态，
            # 否则会拿 IRI 的 iso=1.0 / cmin=-0.04 去可视化 dg_inter（空面）。
            if getattr(self, "_iso_val", 0.02) > 0.5:
                self._iso_val = 0.02
                self.lbl_iso_val.setText("0.020")
                self.sld_iso.blockSignals(True)
                self.sld_iso.setValue(20)
                self.sld_iso.blockSignals(False)
                self.edit_iso.blockSignals(True)
                self.edit_iso.setText("0.020")
                self.edit_iso.blockSignals(False)
                self.edit_cmin.setText("-0.05")
                self.edit_cmax.setText("0.05")
        self._set_status(self._t("done"))

    def _on_error(self, msg):
        self.btn_generate.setEnabled(True)
        self._set_status("错误: " + str(msg))
        self._log("错误: " + str(msg))

    # ── 可视化 ──
    def _geo_map_pair(self):
        field = self.combo_field.currentText()
        if self._is_iri or field.startswith("func2"):
            return (self._files.get("func2.cub"), self._files.get("func1.cub"), "func2")
        if field == "dg":
            return (self._files.get("dg.cub"), self._files.get("sl2r.cub"), "dg")
        if field == "dg_intra":
            return (self._files.get("dg_intra.cub"), self._files.get("sl2r.cub"), "dg_intra")
        return (self._files.get("dg_inter.cub"), self._files.get("sl2r.cub"), "dg_inter")

    def _visualize(self):
        geo, mapf, name = self._geo_map_pair()
        if not geo or not mapf:
            self._set_status(self._t("need_analysis"))
            return
        try:
            iso = self._iso_val
            cmin = float(self.edit_cmin.text().strip())
            cmax = float(self.edit_cmax.text().strip())
        except ValueError:
            iso, cmin, cmax = 0.02, -0.05, 0.05
        if self._field is None or self.glw is None:
            return
        try:
            self._field.load(geo, mapf, iso)
            self._field.set_crange(cmin, cmax)
            self._field.set_strength_alpha(self.chk_strength.isChecked())
            # 挂几何 cube（含分子原子）+ 相机
            self.glw._cube = self._field.geo_cube
            ctr, r = compute_bounding_sphere(self._field.geo_cube)
            self.glw._scene_r = r
            self.glw.cam.set_center_zoom(ctr, r)
            self.glw._gen_atoms()
            # 不显示色彩刻度条（范围仍记录，供 BGR 着色使用）
            self.glw.set_color_scale(cmin, cmax, unit="sign(λ₂)ρ (a.u.)", show=False)
            self._field.push()
            # 登记 VMD 同步场景（几何 cube + BGR 着色 cube）
            self.glw.set_vmd_scene([{"type": "bgr", "vol": geo, "color_vol": mapf,
                                     "iso": iso, "cmin": cmin, "cmax": cmax}])
            self._set_status(self._t("vis_done", field=name,
                                     n=self._field.vertex_count()))
        except Exception as e:
            self._set_status("可视化失败: " + str(e))
            self._log("可视化失败: " + str(e))

    def _on_strength(self, on):
        if self._field is not None:
            self._field.set_strength_alpha(bool(on))

    def _on_iso_slider(self, v):
        """IGMH 等值面滑块：iso = 值/1000，重建场等值面（保持 BGR 着色）。"""
        iso = v / 1000.0
        self._iso_val = iso
        self.lbl_iso_val.setText(f"{iso:.3f}")
        # 同步精确输入框
        self.edit_iso.blockSignals(True)
        self.edit_iso.setText(f"{iso:.3f}")
        self.edit_iso.blockSignals(False)
        if self._field is not None and self._field.geo_cube is not None:
            # 保持着色：用已加载的几何/着色 cube 重建等值面
            self._field.set_iso(iso)
        elif self.glw is not None:
            self.glw.set_isovalue(iso)
        if self.iso_slider is not None:
            # 不 blockSignals：让画布侧自己的回调也执行（更新其数值框）
            self.iso_slider.setValue(v)

    def _sync_iso_from_canvas(self, v):
        """画布等值面滑块变化 → 同步 IGMH 滑块，并恢复 BGR 着色。

        仅当画布当前显示的正是本面板的 IGMH/IRI 场景（glw._cube 就是我们的
        几何 cube）时才重建等值面；用户在看普通轨道/分子时只同步滑块数值，
        不再把旧 IGMH 面重新推到画布上覆盖当前视图。
        """
        self.sld_iso.blockSignals(True)
        self.sld_iso.setValue(v)
        self.sld_iso.blockSignals(False)
        self._iso_val = v / 1000.0
        self.lbl_iso_val.setText(f"{self._iso_val:.3f}")
        self.edit_iso.blockSignals(True)
        self.edit_iso.setText(f"{self._iso_val:.3f}")
        self.edit_iso.blockSignals(False)
        if self._field is not None and self._field.geo_cube is not None and \
                self.glw is not None and \
                getattr(self.glw, "_cube", None) is self._field.geo_cube:
            # 画布侧 set_isovalue 会重置为相位色，这里用场重建恢复 BGR 着色
            self._field.set_iso(self._iso_val)

    def _on_opacity(self, v):
        if self.glw is not None:
            self.glw.set_opacity(max(0.05, v / 100.0))
        # 同步精确输入框
        self.edit_op.blockSignals(True)
        self.edit_op.setText(str(v))
        self.edit_op.blockSignals(False)

    def _on_op_edit(self):
        """不透明度精确输入：5–100 %，回车生效并同步滑块。"""
        try:
            v = float(self.edit_op.text().strip())
        except ValueError:
            self.edit_op.setText(str(self.sld_op.value()))
            return
        v = max(5, min(100, int(round(v))))
        self.edit_op.setText(str(v))
        self.sld_op.blockSignals(True)
        self.sld_op.setValue(v)
        self.sld_op.blockSignals(False)
        self._on_opacity(v)

    def _on_iso_edit(self):
        """等值面精确输入（a.u.）：0.005–2.0，回车生效并同步滑块。"""
        try:
            iso = float(self.edit_iso.text().strip())
        except ValueError:
            self.edit_iso.setText(f"{self._iso_val:.3f}")
            return
        iso = max(0.005, min(2.0, iso))
        v = int(round(iso * 1000))
        # 与滑块同路径（保持 BGR 着色 + 画布联动）
        self.sld_iso.blockSignals(True)
        self.sld_iso.setValue(v)
        self.sld_iso.blockSignals(False)
        self._on_iso_slider(v)

    # ── 散点图 ──
    def _open_scatter(self):
        txt = self._files.get("output.txt") or (
            os.path.join(self._out_dir, "output.txt") if self._out_dir else "")
        if not txt or not os.path.exists(txt):
            QMessageBox.information(self, "提示", self._t("no_data"))
            return
        dlg = IgmScatterDialog(txt, self)
        dlg.exec_()

    # ── 视图 ──
    def _reset_view(self):
        if self.glw is not None:
            if self.glw._cube is not None:
                ctr, r = compute_bounding_sphere(self.glw._cube)
                self.glw.cam.set_center_zoom(ctr, r)
                self.glw.update()
            else:
                self.glw.frame_to_molecule()

    def _clear_canvas(self):
        if self.glw is not None:
            self.glw._pos_surf = None
            self.glw._neg_surf = None
            self.glw._cube = None
            self.glw.set_show_color_scale(False)
            self.glw.set_vmd_scene(None)   # 清除 VMD 同步场景登记
            self.glw._needs_upload = True
            self.glw.update()

    def reset_view_state(self):
        """新分子载入时清空状态（由主窗口调用）。"""
        self.fchk_file = None
        self._frag1.clear()
        self._frag2.clear()
        self.edit_frag1.clear()
        self.edit_frag2.clear()
        self._files = {}
        self._out_dir = ""
        self._apply_fragment_colors()   # 清除片段着色
        self._clear_canvas()            # 移除旧 IGMH 等值面

    def shutdown(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.kill()
            self._worker.wait(3000)
