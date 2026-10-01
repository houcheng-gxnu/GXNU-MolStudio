# -*- coding: utf-8 -*-
"""
asm_irc_panel.py — ASM 沿 IRC 扫描分析面板（GXNU MolStudio 的一个 tab）

把 IRC 上**每个点**都做一次 Distortion/Interaction 分解，绘制
ΔE_strain（形变能）、ΔE_int（相互作用能）、ΔE（总能量）随 IRC 点序的变化。

布局：左侧能量变化图（下方是默认收起的「图片设置」），右侧设置区
（宽度可拖动调节，双击分隔条复位）。
左侧自上而下 = 能量图 / 图片设置（可展开）。
右侧自上而下 = 参考态 / IRC 点列表 / 选项 / 操作按钮 / 结果表。

「图片设置」参考 ESP 面积分布图的图表设置：可编辑标题、X/Y 轴文字与
三条曲线的图例文字（默认英文，中文也可，随图走黑体渲染不乱码）、
三条曲线可各自设置散点形状、颜色与线型（实线/虚线/点划线/点线），
图例可在图上直接拖拽移动、
调整标题/轴标签/刻度/图例/峰值标注字号，开关网格线、图例、峰值标注，
峰值标注文字可自定（留空自动写「峰值 #n / 数值」），
以及导出 DPI 与自定义图幅；改动即时重绘并持久化到 ini。

设置内容：
    参考态  底物 A / 催化剂 B 各自优化好的结构（各 1 个 log）
    IRC 点  每个点 3 个 log —— 复合物 + 片段A + 片段B
            行可手动增删、路径可直接双击编辑；也可用「自动扫描」批量填充。

能量公式（与 di_analysis_panel 完全一致）：
    ΔE_strain(i) = [E_def_A(i) − E_opt_A] + [E_def_B(i) − E_opt_B]
    ΔE_int(i)    = E_complex(i) − E_def_A(i) − E_def_B(i)
    ΔE(i)        = ΔE_strain(i) + ΔE_int(i)
                 = E_complex(i) − E_opt_A − E_opt_B

注意：ΔE 是**两项之和**（不是差）。因 ΔE_int 通常为负，"和"在观感上
等价于"畸变能减去相互作用能的绝对值"。

能量口径三选一（默认纯电子能）：
    scf    最后一个 SCF Done 的电子能
    zpe    + Thermal correction to Energy=
    gibbs  + Thermal correction to Gibbs Free Energy=
"""

import os
import re
import csv
import configparser

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QCheckBox, QMessageBox, QFileDialog, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QSizePolicy,
    QSplitter, QSplitterHandle, QGroupBox, QFormLayout,
    QGridLayout, QSpinBox, QDoubleSpinBox, QColorDialog,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

import matplotlib
matplotlib.use("Qt5Agg")
import matplotlib as _mpl
_mpl.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
_mpl.rcParams["axes.unicode_minus"] = False
import matplotlib.colors as _mcolors
from matplotlib.lines import Line2D
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

# 图内文字字体（渲染/导出时经 rc_context 临时启用，不动全局 rcParams，
# 避免影响其它面板的图）：西文、数字 → Arial；中文 → 黑体(SimHei)，
# 缺字体时回退微软雅黑 / DejaVu Sans。
_PIC_FONT_RC = {
    "font.family": ["Arial", "SimHei", "Microsoft YaHei", "DejaVu Sans"],
    "axes.unicode_minus": False,
}


def _pic_rc():
    return _mpl.rc_context(_PIC_FONT_RC)

from molstudio.ui.file_dialogs import save_file
from molstudio.panels.di_analysis_panel import (parse_scf_energy, parse_thermal_correction,
                               parse_gibbs, HARTREE_TO_KCAL)

K = HARTREE_TO_KCAL

ENERGY_MODES = [
    ("scf",   "纯电子能 SCF"),
    ("zpe",   "ZPE 修正"),
    ("gibbs", "Gibbs 自由能"),
]

# 三条曲线的图例文字默认值（红=形变能、蓝=相互作用能、绿=总能量）。
# 编辑框留空或 ini 里为空时都回落到这里，保证默认就有英文图例。
_LEG_LABEL_DEFAULTS = ("ΔE_strain", "ΔE_int", "ΔE_total")

# 三条曲线的散点标记与颜色默认值（与旧观感一致：红圆/蓝方/绿三角）
_DEFAULT_MARKERS = ("o", "s", "^")
_DEFAULT_COLORS = ("#E57373", "#64B5F6", "#66BB6A")
_DEFAULT_LWS = (2.0, 2.0, 2.4)
_DEFAULT_MSS = (4.5, 4.5, 5.5)

# 点形状下拉：(matplotlib marker, 显示文本)。空串 = 不画点、只画连线
_MARKER_ITEMS = [
    ("o", "圆点"),
    ("s", "方块"),
    ("^", "上三角"),
    ("v", "下三角"),
    ("D", "菱形"),
    ("*", "星形"),
    ("x", "叉形"),
    ("", "无点(仅连线)"),
]

# 线型下拉：(matplotlib linestyle, 显示文本)，默认实线
_LINE_STYLE_ITEMS = [
    ("-", "实线"),
    ("--", "虚线"),
    ("-.", "点划线"),
    (":", "点线"),
]

# 颜色按钮样式：底色=当前曲线颜色
_COLOR_BTN_QSS = (
    "QPushButton { background-color: %s; border: 1px solid #6B7280;"
    " border-radius: 3px; }"
    " QPushButton:hover { border: 1px solid #111111; }"
)


def _peak_palette(total_color):
    """峰值标注配色：默认绿 → 保持旧的深绿系观感；自定义色 → 加深 0.55。"""
    if total_color.lower() == _DEFAULT_COLORS[2].lower():
        return "#2E7D32", "#66BB6A"
    try:
        r, g, b = _mcolors.to_rgb(total_color)
        dark = _mcolors.to_hex([max(0.0, min(1.0, c * 0.55))
                                for c in (r, g, b)])
        return dark, total_color
    except Exception:
        return "#2E7D32", total_color

# 点列表列号
C_NUM, C_COMPLEX, C_FRAG_A, C_FRAG_B = range(4)

# 右侧设置区初始宽度（px），也用于双击分隔条复位
_RIGHT_DEFAULT_W = 420

# IRC 点三件套。先匹配带 -A/-B 的片段，再看裸的复合物，避免误判。
_RE_FRAG_A = re.compile(r"^(?P<stem>.+?)-irc-(?P<num>\d+)-A\.log$", re.I)
_RE_FRAG_B = re.compile(r"^(?P<stem>.+?)-irc-(?P<num>\d+)-B\.log$", re.I)
_RE_COMPLEX = re.compile(r"^(?P<stem>.+?)-irc-(?P<num>\d+)\.log$", re.I)
_RE_OPT = re.compile(r"^opt.*-(?P<tag>A|B)\.log$", re.I)


class _SplitterHandle(QSplitterHandle):
    """分隔条：双击复位到默认栏宽。"""

    def mouseDoubleClickEvent(self, e):
        sp = self.splitter()
        fn = getattr(sp, "_reset_sizes", None)
        if callable(fn):
            fn()
        super().mouseDoubleClickEvent(e)


class _PanelSplitter(QSplitter):
    """可拖动调节栏宽的分隔条。

    Qt 默认 handle 约 4px **且透明**，用户根本看不出能拖 —— 这里加宽热区
    （8px）但只画一条 1px 细线：QSS 没法在控件内部居中画线，用渐变「硬停」
    在热区中间截出 1px 色带，悬停/按下加宽成 4px 主题蓝。
    与 main_window.BodySplitter 及 theme.LIGHT_QSS 同一套观感，避免主分隔条
    是细线、面板内分隔条却是一根粗药丸。
    """

    HANDLE_WIDTH = 8

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setHandleWidth(self.HANDLE_WIDTH)
        self._default_sizes = None
        self.setStyleSheet("""
            QSplitter::handle { background: transparent; }
            QSplitter::handle:horizontal {
                width: 8px;
                margin: 1px 0;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                            stop:0.4375 rgba(0,0,0,0),
                                            stop:0.4375 #DCE3EC,
                                            stop:0.5625 #DCE3EC,
                                            stop:0.5625 rgba(0,0,0,0));
            }
            QSplitter::handle:horizontal:hover,
            QSplitter::handle:horizontal:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                            stop:0.25 rgba(0,0,0,0),
                                            stop:0.25 #1E88E5,
                                            stop:0.75 #1E88E5,
                                            stop:0.75 rgba(0,0,0,0));
            }
            QSplitter::handle:vertical {
                height: 8px;
                margin: 0 1px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0.4375 rgba(0,0,0,0),
                                            stop:0.4375 #DCE3EC,
                                            stop:0.5625 #DCE3EC,
                                            stop:0.5625 rgba(0,0,0,0));
            }
            QSplitter::handle:vertical:hover,
            QSplitter::handle:vertical:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0.25 rgba(0,0,0,0),
                                            stop:0.25 #1E88E5,
                                            stop:0.75 #1E88E5,
                                            stop:0.75 rgba(0,0,0,0));
            }
        """)

    def set_default_sizes(self, sizes):
        """记录默认栏宽（setSizes 之后调用），供双击复位使用。"""
        self._default_sizes = list(sizes)

    def _reset_sizes(self):
        if self._default_sizes:
            self.setSizes(self._default_sizes)

    def createHandle(self):
        h = _SplitterHandle(self.orientation(), self)
        h.setToolTip("拖动调整宽度，双击复位")
        h.setCursor(Qt.SplitHCursor if self.orientation() == Qt.Horizontal
                    else Qt.SplitVCursor)
        return h


def scan_asm_directory(dirpath):
    """扫描目录，返回 (ref_a, ref_b, items)。

    items 为 [(num, path_complex, path_frag_a, path_frag_b), ...]，
    按点号升序；只保留三件套齐全的点。用于「自动扫描」快速填充。
    """
    if not dirpath or not os.path.isdir(dirpath):
        return None, None, []
    try:
        names = [f for f in os.listdir(dirpath)
                 if f.lower().endswith(".log")
                 and os.path.isfile(os.path.join(dirpath, f))]
    except OSError:
        return None, None, []

    ref_a = ref_b = None
    pts = {}
    for fn in names:
        full = os.path.join(dirpath, fn)
        m = _RE_OPT.match(fn)
        if m:
            if m.group("tag").upper() == "A":
                ref_a = full
            else:
                ref_b = full
            continue
        m = _RE_FRAG_A.match(fn)
        if m:
            pts.setdefault(int(m.group("num")), {})["a"] = full
            continue
        m = _RE_FRAG_B.match(fn)
        if m:
            pts.setdefault(int(m.group("num")), {})["b"] = full
            continue
        m = _RE_COMPLEX.match(fn)
        if m:
            pts.setdefault(int(m.group("num")), {})["c"] = full

    items = []
    for num in sorted(pts):
        d = pts[num]
        if d.get("c") and d.get("a") and d.get("b"):
            items.append((num, d["c"], d["a"], d["b"]))
    return ref_a, ref_b, items


def read_energy(path, mode):
    """按口径读取单个 log 的能量（hartree）；失败返回 None。"""
    if not path or not os.path.isfile(path):
        return None
    e = parse_scf_energy(path)
    if e is None:
        return None
    if mode == "zpe":
        c = parse_thermal_correction(path)
        if c is not None:
            e += c
    elif mode == "gibbs":
        c = parse_gibbs(path)
        if c is not None:
            e += c
    return e


def compute_asm_scan(ref_a, ref_b, items, mode):
    """逐点做 DI 分解。返回 dict(ok, msg, ref_a, ref_b, rows)。"""
    if not ref_a or not ref_b:
        return {"ok": False, "msg": "请先在右侧设置参考态 A / B", "rows": []}
    e_opt_a = read_energy(ref_a, mode)
    e_opt_b = read_energy(ref_b, mode)
    if e_opt_a is None or e_opt_b is None:
        return {"ok": False, "msg": "参考态能量读取失败，请检查文件", "rows": []}

    rows = []
    skipped = []
    for num, pc, pa, pb in items:
        ec = read_energy(pc, mode)
        ea = read_energy(pa, mode)
        eb = read_energy(pb, mode)
        if ec is None or ea is None or eb is None:
            skipped.append(num)
            continue
        s1 = ea - e_opt_a
        s2 = eb - e_opt_b
        strain = s1 + s2
        inter = ec - ea - eb
        rows.append({
            "num": num,
            "e_def_a": ea, "e_def_b": eb, "e_complex": ec,
            "strain1": s1, "strain2": s2,
            "strain": strain, "int": inter, "total": strain + inter,
            "paths": {"c": pc, "a": pa, "b": pb},
        })
    msg = ""
    if skipped:
        msg = "已跳过能量缺失的点：%s" % ", ".join(str(s) for s in skipped)
    return {"ok": bool(rows), "msg": msg, "ref_a": ref_a, "ref_b": ref_b,
            "e_opt_a": e_opt_a, "e_opt_b": e_opt_b, "rows": rows}


#: 中英文字对照（切语言时由 set_lang 整树套用，见 molstudio/ui/i18n_utils.py）
_LANG_EXTRA = {
    "数据目录:": "Data folder:",
    "选择 Gaussian .log 文件": "Select a Gaussian .log file",
    "底物 A:": "Substrate A:",
    "催化剂 B:": "Catalyst B:",
    "片段A": "Fragment A",
    "片段B": "Fragment B",
    "复合物": "Complex",
    "按 -A/-B 后缀自动配对复合物与片段，填充参考态和点列表":
        "Auto-pair complexes with fragments by the -A/-B suffix and fill the "
        "reference states and point list",
    "可选：指定后点「自动扫描」批量填充右侧":
        "Optional: pick a folder, then click Auto-scan to fill the list on the right",
    "自动扫描": "Auto-scan",
    "点号与三列路径均可双击直接编辑；也可点「自动扫描」批量填充":
        "The point number and the three paths are editable by double-clicking; "
        "Auto-scan can fill them in bulk",
    "列宽不足时可横向滚动查看": "Scroll horizontally when the columns are too narrow",
    "添加点": "Add point",
    "删除选中": "Delete selected",
    "设置参考态 A / B，再添加 IRC 点（或用「自动扫描」），然后点「计算」":
        "Set reference states A / B, add IRC points (or use Auto-scan), then click Compute",
    "能量口径:": "Energy reference:",
    "纯电子能 SCF": "Electronic energy (SCF)",
    "ZPE 修正": "ZPE correction",
    "Gibbs 自由能": "Gibbs free energy",
    "计算": "Compute",
    "ΔE 总": "ΔE total",
    "导出 CSV": "Export CSV",
    "导出用指定尺寸": "Use the specified size for export",
    "图宽 (inch):": "Figure width (inch):",
    "图高 (inch):": "Figure height (inch):",
    "保存 DPI:": "Save DPI:",
    "保存图片": "Save image",
    "勾选后「保存图片」按下方图宽/图高另渲染（否则按当前画面大小导出）":
        "When ticked, Save image re-renders at the width/height below "
        "(otherwise it exports the current view size)",
    "标题:": "Title:",
    "如：ASM 沿 IRC 扫描能量变化（留空不显示标题）":
        "e.g. ASM energy scan along the IRC (leave empty for no title)",
    "标题字号:": "Title size:",
    "X 轴:": "X axis:",
    "Y 轴:": "Y axis:",
    "轴标签字号:": "Axis label size:",
    "刻度字号:": "Tick size:",
    "图例": "Legend",
    "图例字号:": "Legend size:",
    "网格线": "Grid lines",
    "标注峰值": "Annotate peaks",
    "峰值文字:": "Peak text:",
    "峰值标注字号:": "Peak label size:",
    "峰值上方标注文字：可随意填写（支持中文）；\n"
    "留空则按默认自动生成「峰值 #序号 / 能量数值」":
        "Text annotated above the peaks: free-form (Chinese supported);\n"
        "leave empty to auto-generate “peak #n / energy”",
    "自定义峰值标注文字（可留空 = 自动写「峰值 #n / 数值」）":
        "Custom peak annotation text (empty = “peak #n / value”)",
    "英文或中文": "English or Chinese",
    "曲线 1（红=形变能(strain)）图例文字；留空恢复默认英文，中英文均支持。":
        "Legend text for curve 1 (red = strain energy); leave empty for the default. "
        "Chinese and English are both supported.",
    "曲线 2（蓝=相互作用能(int)）图例文字；留空恢复默认英文，中英文均支持。":
        "Legend text for curve 2 (blue = interaction energy); leave empty for the "
        "default. Chinese and English are both supported.",
    "曲线 3（绿=总能量(strain+int)）图例文字；留空恢复默认英文，中英文均支持。":
        "Legend text for curve 3 (green = total energy, strain+int); leave empty for "
        "the default. Chinese and English are both supported.",
    "曲线 1 线型（实线/虚线/点划线/点线）":
        "Curve 1 line style (solid / dashed / dash-dot / dotted)",
    "曲线 2 线型（实线/虚线/点划线/点线）":
        "Curve 2 line style (solid / dashed / dash-dot / dotted)",
    "曲线 3 线型（实线/虚线/点划线/点线）":
        "Curve 3 line style (solid / dashed / dash-dot / dotted)",
    "曲线 1 散点形状；选「无点(仅连线)」则只画连线":
        "Curve 1 marker shape; choose “No markers (line only)” to draw just the line",
    "曲线 2 散点形状；选「无点(仅连线)」则只画连线":
        "Curve 2 marker shape; choose “No markers (line only)” to draw just the line",
    "曲线 3 散点形状；选「无点(仅连线)」则只画连线":
        "Curve 3 marker shape; choose “No markers (line only)” to draw just the line",
    "实线": "Solid",
    "虚线": "Dashed",
    "点划线": "Dash-dot",
    "点线": "Dotted",
    "圆点": "Circle",
    "方块": "Square",
    "菱形": "Diamond",
    "上三角": "Upper triangle",
    "下三角": "Lower triangle",
    "叉形": "Cross",
    "星形": "Star",
    "无点(仅连线)": "No markers (line only)",
    "点": "Point",
    "点击选择曲线 1 颜色": "Click to pick curve 1 color",
    "点击选择曲线 2 颜色": "Click to pick curve 2 color",
    "点击选择曲线 3 颜色": "Click to pick curve 3 color",
    "拖动调整宽度，双击复位": "Drag to resize; double-click to reset",
    "勾选展开图表外观设置（图题/坐标轴文字/图例文字、字号、显示开关、导出参数）；\n"
    "取消勾选收起，避免挤占绘图高度":
        "Tick to expand the chart appearance settings (title / axis labels / legend "
        "text, font sizes, toggles, export options);\n"
        "untick to collapse them so the plot keeps its height",
    "浏览…": "Browse…",
}


class AsmIrcPanel(QWidget):
    """ASM 沿 IRC 扫描面板：左图，右侧设置（宽度可调）+ 结果表。"""

    def __init__(self, log_func=None, parent=None):
        super().__init__(parent)
        self._log = log_func or (lambda m: None)
        self._last = None
        self._canvas = None
        self._sizes_set = False
        self._loading = True
        self._build_ui()
        try:
            self._load_settings()
        finally:
            self._loading = False

    # ── UI ──
    def _build_ui(self):
        root = QVBoxLayout(self)
        # 全站统一：页面外边距 8px + 一级块间距 8px（基准 = AIM 面板，见
        # aim_panel._build_ui）。
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # 顶部：目录 + 自动扫描（便利入口，非必需）
        h_top = QHBoxLayout()
        h_top.addWidget(QLabel("数据目录:"))
        self.ed_dir = QLineEdit()
        self.ed_dir.setPlaceholderText("可选：指定后点「自动扫描」批量填充右侧")
        h_top.addWidget(self.ed_dir, 1)
        b_dir = QPushButton("浏览…")
        b_dir.clicked.connect(self._browse_dir)
        h_top.addWidget(b_dir)
        b_scan = QPushButton("自动扫描")
        b_scan.setToolTip("按 -A/-B 后缀自动配对复合物与片段，填充参考态和点列表")
        b_scan.clicked.connect(self._auto_scan)
        h_top.addWidget(b_scan)
        root.addLayout(h_top)

        sp = _PanelSplitter(Qt.Horizontal)
        sp.setChildrenCollapsible(False)

        # ───── 左：能量图 ─────
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self._canvas_host = QWidget()
        self._canvas_layout = QVBoxLayout(self._canvas_host)
        self._canvas_layout.setContentsMargins(0, 0, 0, 0)
        self._canvas_host.setSizePolicy(QSizePolicy.Expanding,
                                        QSizePolicy.Expanding)
        lv.addWidget(self._canvas_host, 1)

        # 图片设置（默认收起）→ 图下方
        self._build_picture_group(lv)
        sp.addWidget(left)

        # ───── 右：设置 + 结果表 ─────
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(6)

        # 参考态
        gb_ref = QGroupBox("参考态（各自优化好的结构）")
        gf = QFormLayout(gb_ref)
        gf.setLabelAlignment(Qt.AlignRight)
        self.ed_ref_a = QLineEdit()
        self.ed_ref_b = QLineEdit()
        gf.addRow("底物 A:", self._with_browse(self.ed_ref_a))
        gf.addRow("催化剂 B:", self._with_browse(self.ed_ref_b))
        rv.addWidget(gb_ref)

        # IRC 点列表
        gb_pts = QGroupBox("IRC 点（每行 = 复合物 + 片段A + 片段B）")
        gpv = QVBoxLayout(gb_pts)
        self.tw_pts = QTableWidget(0, 4)
        self.tw_pts.setHorizontalHeaderLabels(["点", "复合物", "片段A", "片段B"])
        self.tw_pts.setEditTriggers(QAbstractItemView.DoubleClicked
                                    | QAbstractItemView.EditKeyPressed)
        self.tw_pts.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tw_pts.verticalHeader().setVisible(False)
        ph = self.tw_pts.horizontalHeader()
        ph.setSectionResizeMode(C_NUM, QHeaderView.ResizeToContents)
        for c in (C_COMPLEX, C_FRAG_A, C_FRAG_B):
            ph.setSectionResizeMode(c, QHeaderView.Stretch)
        self.tw_pts.setToolTip(
            "点号与三列路径均可双击直接编辑；也可点「自动扫描」批量填充")
        gpv.addWidget(self.tw_pts, 1)
        hb = QHBoxLayout()
        b_add = QPushButton("添加点")
        b_add.clicked.connect(self._add_point)
        hb.addWidget(b_add)
        b_del = QPushButton("删除选中")
        b_del.clicked.connect(self._del_point)
        hb.addWidget(b_del)
        hb.addStretch(1)
        gpv.addLayout(hb)
        rv.addWidget(gb_pts, 2)

        # 选项
        gb_opt = QGroupBox("选项")
        gof = QFormLayout(gb_opt)
        gof.setLabelAlignment(Qt.AlignRight)
        self.cb_mode = QComboBox()
        for key, text in ENERGY_MODES:
            self.cb_mode.addItem(text, key)
        self.cb_mode.setCurrentIndex(0)          # 默认纯电子能 SCF
        self.cb_mode.currentIndexChanged.connect(self._on_mode_changed)
        gof.addRow("能量口径:", self.cb_mode)
        rv.addWidget(gb_opt)

        # 操作按钮
        self.btn_calc = QPushButton("计算")
        self.btn_calc.clicked.connect(self._calculate)
        rv.addWidget(self.btn_calc)
        h_exp = QHBoxLayout()
        self.btn_csv = QPushButton("导出 CSV")
        self.btn_csv.setEnabled(False)
        self.btn_csv.clicked.connect(self._export_csv)
        h_exp.addWidget(self.btn_csv)
        self.btn_png = QPushButton("保存图片")
        self.btn_png.setEnabled(False)
        self.btn_png.clicked.connect(self._save_png)
        h_exp.addWidget(self.btn_png)
        rv.addLayout(h_exp)

        # 结果表
        gb_res = QGroupBox("计算结果")
        gres = QVBoxLayout(gb_res)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["点", "E_def_A", "E_def_B", "E_complex",
             "ΔE_strain", "ΔE_int", "ΔE 总"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        self.table.setToolTip("列宽不足时可横向滚动查看")
        gres.addWidget(self.table)
        rv.addWidget(gb_res, 3)

        right.setMinimumWidth(360)
        sp.addWidget(right)
        sp.setStretchFactor(0, 1)
        sp.setStretchFactor(1, 0)
        self._splitter = sp
        root.addWidget(sp, 1)

        self.lbl_status = QLabel(
            "设置参考态 A / B，再添加 IRC 点（或用「自动扫描」），然后点「计算」")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet(
            "background:#F1F5F9;color:#475569;border:1px solid #E2E8F0;"
            "border-radius:4px;padding:5px 8px;")
        root.addWidget(self.lbl_status)

        self._draw_empty_plot()

    def showEvent(self, event):
        """首次显示时按比例分配左右栏宽（未 show 时 setSizes 无效）。"""
        super().showEvent(event)
        if self._sizes_set:
            return
        self._sizes_set = True
        sp = self._splitter
        total = sp.width()
        if total <= 0:
            return
        rw = min(_RIGHT_DEFAULT_W, max(total // 3, 360))
        sp.setSizes([total - rw, rw])
        sp.set_default_sizes(list(sp.sizes()))

    def _with_browse(self, edit):
        """给路径输入框配一个「…」浏览按钮。"""
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(3)
        h.addWidget(edit, 1)
        b = QPushButton("…")
        b.setFixedWidth(28)
        b.setToolTip("选择 Gaussian .log 文件")
        b.clicked.connect(
            lambda: self._pick_file(edit, "选择 Gaussian 输出", "Log (*.log)"))
        h.addWidget(b)
        return w

    # ── 交互 ──
    def _pick_file(self, edit, title, filt):
        p, _ = QFileDialog.getOpenFileName(
            self, title,
            os.path.dirname(edit.text().strip())
            if edit.text().strip() else "", filt)
        if p:
            edit.setText(p)

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(
            self, "选择 IRC 各点 log 所在目录",
            self.ed_dir.text().strip() or "")
        if d:
            self.ed_dir.setText(d)

    def _on_mode_changed(self, _idx):
        """切换能量口径后按新口径重算（已有结果时才自动算，避免空表弹窗）。"""
        if self._last is not None:
            self._calculate()

    def _auto_scan(self):
        """扫描目录 → 填充参考态与点列表。"""
        d = self.ed_dir.text().strip()
        ref_a, ref_b, items = scan_asm_directory(d)
        if not items:
            QMessageBox.information(
                self, "扫描结果",
                "未找到三件套齐全的 IRC 点。\n\n"
                "目录需含形如 xxx-irc-001.log / -A.log / -B.log 的文件组。")
            return
        if ref_a:
            self.ed_ref_a.setText(ref_a)
        if ref_b:
            self.ed_ref_b.setText(ref_b)
        self.tw_pts.setRowCount(0)
        for num, pc, pa, pb in items:
            self._append_row(num, pc, pa, pb)
        self.lbl_status.setText("已扫描到 %d 个点，点「计算」出图" % len(items))
        self._save_settings()

    def _append_row(self, num, pc, pa, pb):
        r = self.tw_pts.rowCount()
        self.tw_pts.insertRow(r)
        for c, v in ((C_NUM, str(num)), (C_COMPLEX, pc),
                     (C_FRAG_A, pa), (C_FRAG_B, pb)):
            it = QTableWidgetItem(v)
            it.setToolTip(v)
            self.tw_pts.setItem(r, c, it)

    def _add_point(self):
        """在末尾追加一个空点（点号自动顺延）。"""
        last = 0
        for r in range(self.tw_pts.rowCount()):
            it = self.tw_pts.item(r, C_NUM)
            if it:
                try:
                    last = max(last, int(it.text().strip()))
                except ValueError:
                    pass
        self._append_row(last + 1, "", "", "")
        self.tw_pts.scrollToBottom()

    def _del_point(self):
        for r in sorted({i.row() for i in self.tw_pts.selectedIndexes()},
                        reverse=True):
            self.tw_pts.removeRow(r)

    def _collect_items(self):
        """从点表格收集 (num, complex, frag_a, frag_b)；跳过信息不全的行。"""
        items = []
        for r in range(self.tw_pts.rowCount()):
            def txt(c):
                it = self.tw_pts.item(r, c)
                return it.text().strip() if it else ""
            try:
                num = int(txt(C_NUM))
            except ValueError:
                continue
            pc, pa, pb = txt(C_COMPLEX), txt(C_FRAG_A), txt(C_FRAG_B)
            if pc and pa and pb:
                items.append((num, pc, pa, pb))
        return items

    def _calculate(self):
        items = self._collect_items()
        if not items:
            QMessageBox.information(
                self, "无法计算",
                "请先在右侧添加至少一个信息完整的 IRC 点\n"
                "（点号 + 复合物 + 片段A + 片段B 都需填写）。")
            return
        ref_a = self.ed_ref_a.text().strip()
        ref_b = self.ed_ref_b.text().strip()
        mode = self.cb_mode.currentData() or "scf"
        R = compute_asm_scan(ref_a, ref_b, items, mode)
        self._last = R
        if not R["ok"]:
            self.lbl_status.setText(R["msg"] or "计算失败")
            self.table.setRowCount(0)
            self.btn_csv.setEnabled(False)
            self.btn_png.setEnabled(False)
            self._draw_empty_plot()
            return

        rows = R["rows"]
        peaks = max(rows, key=lambda r: r["total"])
        mode_text = dict(ENERGY_MODES).get(mode, mode)
        self.lbl_status.setText(
            "%d 个点 | 口径：%s | 能量最高点 = #%d（ΔE = %.1f kcal/mol）%s"
            % (len(rows), mode_text, peaks["num"], peaks["total"] * K,
               ("；" + R["msg"]) if R["msg"] else ""))
        self.btn_csv.setEnabled(True)
        self.btn_png.setEnabled(True)
        self._fill_table()
        self._replot()
        self._save_settings()

    # ── 结果表 ──
    def _fill_table(self):
        rows = self._last["rows"] if self._last else []
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = [
                str(r["num"]),
                "%.6f" % r["e_def_a"],
                "%.6f" % r["e_def_b"],
                "%.6f" % r["e_complex"],
                "%.2f" % (r["strain"] * K),
                "%.2f" % (r["int"] * K),
                "%.2f" % (r["total"] * K),
            ]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setTextAlignment(Qt.AlignCenter)
                # 后三列按正负着色：正=不利(红) 负=有利(蓝)
                if j in (4, 6):
                    it.setForeground(QColor("#C62828" if float(v) > 0
                                            else "#1565C0"))
                elif j == 5:
                    it.setForeground(QColor("#1565C0" if float(v) < 0
                                            else "#C62828"))
                self.table.setItem(i, j, it)

    # ── 图片设置 ──
    def _build_picture_group(self, host_layout):
        """在左侧图下方加「图片设置」分组（默认收起，可展开）。

        参考 ESP 面积分布图的图表设置：标题/X/Y 轴文字、各字号、
        网格线/图例/峰值标注开关、导出 DPI 与自定义图幅。
        """
        gb = QGroupBox("图片设置 ▸")
        gb.setCheckable(True)
        gb.setChecked(False)
        gb.setToolTip(
            "勾选展开图表外观设置（图题/坐标轴文字/图例文字、字号、显示开关、"
            "导出参数）；\n取消勾选收起，避免挤占绘图高度")

        body = QWidget()
        gl = QGridLayout(body)
        gl.setContentsMargins(2, 2, 2, 2)
        gl.setHorizontalSpacing(6)
        gl.setVerticalSpacing(2)
        for _c in range(3):
            gl.setColumnStretch(_c, 1)

        # 标签统一等宽（取最长标签），各列控件纵向对齐、行距紧凑
        fm = body.fontMetrics()
        lbl_w = fm.horizontalAdvance("峰值标注字号:") + 8

        def field(text, widget):
            """一格：等宽右对齐标签 + 控件（控件占满该格剩余宽度）"""
            cell = QWidget()
            h = QHBoxLayout(cell)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(5)
            lbl = QLabel(text)
            lbl.setFixedWidth(lbl_w)
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            h.addWidget(lbl)
            h.addWidget(widget, 1)
            return cell

        def chkcell(widget):
            """一格：复选框（自带文字，作为独立紧凑单元）"""
            cell = QWidget()
            h = QHBoxLayout(cell)
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(widget)
            return cell

        def spin(low, high, val, step=1, width=62):
            sb = QSpinBox()
            sb.setRange(low, high)
            sb.setValue(val)
            sb.setSingleStep(step)
            sb.setFixedWidth(width)
            return sb

        # 第 0 行：标题（独占整行）
        self.ed_pic_title = QLineEdit()
        self.ed_pic_title.setPlaceholderText("如：ASM 沿 IRC 扫描能量变化（留空不显示标题）")
        gl.addWidget(field("标题:", self.ed_pic_title), 0, 0, 1, 3)

        # ── 以下每行三个设置，紧凑排列 ──
        # 第 1 行：X/Y 轴文字 + 刻度字号
        self.ed_pic_x = QLineEdit("IRC 点序")
        self.ed_pic_y = QLineEdit("能量 (kcal/mol)")
        self.sp_pic_tick_fs = spin(6, 20, 9)
        gl.addWidget(field("X 轴:", self.ed_pic_x), 1, 0)
        gl.addWidget(field("Y 轴:", self.ed_pic_y), 1, 1)
        gl.addWidget(field("刻度字号:", self.sp_pic_tick_fs), 1, 2)

        # 第 2 行：轴标签 / 标题 / 图例 字号
        self.sp_pic_label_fs = spin(6, 20, 12)
        self.sp_pic_title_fs = spin(8, 24, 14)
        self.sp_pic_legend_fs = spin(6, 20, 9)
        gl.addWidget(field("轴标签字号:", self.sp_pic_label_fs), 2, 0)
        gl.addWidget(field("标题字号:", self.sp_pic_title_fs), 2, 1)
        gl.addWidget(field("图例字号:", self.sp_pic_legend_fs), 2, 2)

        # 第 3 行：每条曲线一格，内部纵向叠三小行 ——
        #   ① 图例文字（默认英文，直接输中文即可，随图走黑体渲染）
        #   ② 散点形状 + 颜色按钮
        #   ③ 线型（实线/虚线/点划线/点线）
        self.cb_pic_marker = []
        self.cb_pic_ls = []
        self.btn_pic_color = []
        for i in range(3):
            ed = QLineEdit(_LEG_LABEL_DEFAULTS[i])
            tip = ("红=形变能(strain)", "蓝=相互作用能(int)",
                   "绿=总能量(strain+int)")[i]
            ed.setToolTip("曲线 %d（%s）图例文字；留空恢复默认英文，"
                          "中英文均支持。" % (i + 1, tip))
            ed.setPlaceholderText("英文或中文")
            cell = QWidget()
            cv = QVBoxLayout(cell)
            cv.setContentsMargins(0, 0, 0, 0)
            cv.setSpacing(2)
            cv.addWidget(ed)

            # ② 散点形状 + 颜色
            hb2 = QHBoxLayout()
            hb2.setContentsMargins(0, 0, 0, 0)
            hb2.setSpacing(4)
            cb = QComboBox()
            for data, text in _MARKER_ITEMS:
                cb.addItem(text, data)
            cb.setCurrentIndex(next(
                (k for k, (_d, _t) in enumerate(_MARKER_ITEMS)
                 if _d == _DEFAULT_MARKERS[i]), 0))
            cb.setToolTip("曲线 %d 散点形状；选「无点(仅连线)」则只画连线"
                          % (i + 1))
            cb.currentIndexChanged.connect(self._on_plot_cfg)
            btn = QPushButton()
            btn.setFixedSize(56, 22)
            btn.setToolTip("点击选择曲线 %d 颜色" % (i + 1))
            btn.clicked.connect(lambda _x, k=i: self._pick_curve_color(k))
            hb2.addWidget(cb, 1)
            hb2.addWidget(btn, 0)
            cv.addLayout(hb2)

            # ③ 线型
            hb3 = QHBoxLayout()
            hb3.setContentsMargins(0, 0, 0, 0)
            hb3.setSpacing(4)
            cbls = QComboBox()
            for data, text in _LINE_STYLE_ITEMS:
                cbls.addItem(text, data)
            cbls.setToolTip("曲线 %d 线型（实线/虚线/点划线/点线）"
                            % (i + 1))
            cbls.currentIndexChanged.connect(self._on_plot_cfg)
            hb3.addWidget(cbls, 1)
            cv.addLayout(hb3)

            self.cb_pic_marker.append(cb)
            self.cb_pic_ls.append(cbls)
            self.btn_pic_color.append(btn)
            setattr(self, "ed_pic_leg%d" % (i + 1), ed)
            self._set_curve_color(i, _DEFAULT_COLORS[i])
            gl.addWidget(cell, 3, i)

        # 第 4 行：峰值标注字号 + 网格/图例开关
        self.sp_pic_annot_fs = spin(6, 20, 9)
        self.chk_pic_grid = QCheckBox("网格线")
        self.chk_pic_grid.setChecked(True)
        self.chk_pic_legend = QCheckBox("图例")
        self.chk_pic_legend.setChecked(True)
        gl.addWidget(field("峰值标注字号:", self.sp_pic_annot_fs), 4, 0)
        gl.addWidget(chkcell(self.chk_pic_grid), 4, 1)
        gl.addWidget(chkcell(self.chk_pic_legend), 4, 2)

        # 第 5 行：标注峰值 / 指定尺寸 开关 + 保存 DPI
        self.chk_pic_peak = QCheckBox("标注峰值")
        self.chk_pic_peak.setChecked(True)
        self.chk_pic_outsize = QCheckBox("导出用指定尺寸")
        self.chk_pic_outsize.setToolTip(
            "勾选后「保存图片」按下方图宽/图高另渲染（否则按当前画面大小导出）")
        self.sp_pic_dpi = spin(72, 1200, 200, step=50)
        gl.addWidget(chkcell(self.chk_pic_peak), 5, 0)
        gl.addWidget(chkcell(self.chk_pic_outsize), 5, 1)
        gl.addWidget(field("保存 DPI:", self.sp_pic_dpi), 5, 2)

        # 第 6 行：峰值标注文字（可自定、可留空；留空自动写「峰值 #n / 数值」）
        self.ed_pic_peak_text = QLineEdit()
        self.ed_pic_peak_text.setPlaceholderText(
            "自定义峰值标注文字（可留空 = 自动写「峰值 #n / 数值」）")
        self.ed_pic_peak_text.setToolTip(
            "峰值上方标注文字：可随意填写（支持中文）；\n"
            "留空则按默认自动生成「峰值 #序号 / 能量数值」")
        gl.addWidget(field("峰值文字:", self.ed_pic_peak_text), 6, 0, 1, 3)

        # 第 7 行：自定义图幅
        self.sp_pic_outw = QDoubleSpinBox()
        self.sp_pic_outw.setRange(3.0, 20.0)
        self.sp_pic_outw.setValue(8.0)
        self.sp_pic_outw.setSingleStep(0.5)
        self.sp_pic_outw.setDecimals(1)
        self.sp_pic_outw.setFixedWidth(70)
        self.sp_pic_outh = QDoubleSpinBox()
        self.sp_pic_outh.setRange(3.0, 20.0)
        self.sp_pic_outh.setValue(5.0)
        self.sp_pic_outh.setSingleStep(0.5)
        self.sp_pic_outh.setDecimals(1)
        self.sp_pic_outh.setFixedWidth(70)
        gl.addWidget(field("图宽 (inch):", self.sp_pic_outw), 7, 0)
        gl.addWidget(field("图高 (inch):", self.sp_pic_outh), 7, 1)

        gbox = QVBoxLayout(gb)
        gbox.setContentsMargins(4, 2, 4, 4)
        gbox.addWidget(body)
        self._pic_gb = gb
        self._pic_body = body

        def _sync_collapse(on):
            body.setVisible(on)
            gb.setTitle("图片设置 ▾" if on else "图片设置 ▸")

        gb.toggled.connect(_sync_collapse)
        gb.toggled.connect(lambda _s: self._on_plot_cfg())
        _sync_collapse(gb.isChecked())   # 初始（默认收起）即同步
        host_layout.addWidget(gb)

        # 任何改动 → 实时重绘（有数据时）并落盘
        self._pic_widgets = (self.ed_pic_title, self.ed_pic_x, self.ed_pic_y,
                             self.ed_pic_leg1, self.ed_pic_leg2,
                             self.ed_pic_leg3,
                             self.sp_pic_tick_fs, self.sp_pic_legend_fs,
                             self.sp_pic_title_fs, self.sp_pic_annot_fs,
                             self.sp_pic_label_fs, self.chk_pic_grid,
                             self.chk_pic_legend, self.chk_pic_peak,
                             self.ed_pic_peak_text,
                             self.chk_pic_outsize, self.sp_pic_dpi,
                             self.sp_pic_outw, self.sp_pic_outh)
        for w in self._pic_widgets:
            if isinstance(w, QCheckBox):
                w.stateChanged.connect(self._on_plot_cfg)
            elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
                w.valueChanged.connect(self._on_plot_cfg)
            else:
                w.textChanged.connect(self._on_plot_cfg)

    def _on_plot_cfg(self, *_a):
        """图片设置任一改动：有数据就即时重绘，并持久化。"""
        if getattr(self, "_loading", False):
            return
        if self._last is not None and self._canvas is not None:
            self._replot()
        self._save_settings()

    def _load_pic_settings(self, s):
        # setChecked 触发 toggled → 展开/收起与标题箭头自动同步
        self._pic_gb.setChecked(s.getboolean("pic_expanded", False))
        self.ed_pic_title.setText(s.get("pic_title", ""))
        self.ed_pic_x.setText(s.get("pic_xlabel", "IRC 点序"))
        self.ed_pic_y.setText(s.get("pic_ylabel", "能量 (kcal/mol)"))
        self.ed_pic_leg1.setText(s.get("pic_leg1", "").strip()
                                 or _LEG_LABEL_DEFAULTS[0])
        self.ed_pic_leg2.setText(s.get("pic_leg2", "").strip()
                                 or _LEG_LABEL_DEFAULTS[1])
        self.ed_pic_leg3.setText(s.get("pic_leg3", "").strip()
                                 or _LEG_LABEL_DEFAULTS[2])
        for i in range(3):
            self._set_curve_marker(i, s.get("pic_m%d" % (i + 1),
                                            _DEFAULT_MARKERS[i]))
            self._set_curve_color(i, s.get("pic_c%d" % (i + 1),
                                           _DEFAULT_COLORS[i]))
            self._set_curve_ls(i, s.get("pic_ls%d" % (i + 1), "-"))
        self.sp_pic_tick_fs.setValue(s.getint("pic_tick_fs", 9))
        self.sp_pic_legend_fs.setValue(s.getint("pic_legend_fs", 9))
        self.sp_pic_title_fs.setValue(s.getint("pic_title_fs", 14))
        self.sp_pic_annot_fs.setValue(s.getint("pic_annot_fs", 9))
        self.sp_pic_label_fs.setValue(s.getint("pic_label_fs", 12))
        self.chk_pic_grid.setChecked(s.getboolean("pic_grid", True))
        self.chk_pic_legend.setChecked(s.getboolean("pic_legend", True))
        self.chk_pic_peak.setChecked(s.getboolean("pic_peak", True))
        self.ed_pic_peak_text.setText(s.get("pic_peak_text", ""))
        self.chk_pic_outsize.setChecked(
            s.getboolean("pic_outsize", False))
        self.sp_pic_dpi.setValue(s.getint("pic_dpi", 200))
        self.sp_pic_outw.setValue(s.getfloat("pic_outw", 8.0))
        self.sp_pic_outh.setValue(s.getfloat("pic_outh", 5.0))

    # ── 曲线外观：散点形状 / 线型 / 颜色 ────────────────────
    def _curve_marker(self, i):
        cb = self.cb_pic_marker[i]
        return cb.itemData(cb.currentIndex()) or ""

    def _curve_ls(self, i):
        """曲线 i 当前线型（matplotlib linestyle 字符串，如 '--'）。"""
        cb = self.cb_pic_ls[i]
        return cb.itemData(cb.currentIndex()) or "-"

    def _curve_color(self, i):
        b = self.btn_pic_color[i]
        return getattr(b, "_ov_hex", _DEFAULT_COLORS[i])

    def _set_curve_ls(self, i, data):
        cb = self.cb_pic_ls[i]
        for k in range(cb.count()):
            if cb.itemData(k) == data:
                cb.setCurrentIndex(k)
                return
        cb.setCurrentIndex(0)   # 非法值兜底：实线

    def _set_curve_marker(self, i, data):
        cb = self.cb_pic_marker[i]
        for k in range(cb.count()):
            if cb.itemData(k) == data:
                cb.setCurrentIndex(k)
                return
        for k in range(cb.count()):      # 非法值兜底：回默认形状
            if cb.itemData(k) == _DEFAULT_MARKERS[i]:
                cb.setCurrentIndex(k)
                return

    def _set_curve_color(self, i, hex_c):
        try:
            qc = QColor(hex_c)
            hex_c = qc.name() if qc.isValid() else _DEFAULT_COLORS[i]
        except Exception:
            hex_c = _DEFAULT_COLORS[i]
        b = self.btn_pic_color[i]
        b._ov_hex = hex_c
        b.setStyleSheet(_COLOR_BTN_QSS % hex_c)

    def _pick_curve_color(self, i):
        c0 = QColor(self._curve_color(i))
        c = QColorDialog.getColor(c0, self, "选择曲线 %d 颜色" % (i + 1))
        if c.isValid():
            self._set_curve_color(i, c.name())
            self._on_plot_cfg()

    # ── 绘图 ──
    def _figsize(self):
        """按画布容器的实际尺寸出图，保证随分隔条拖动自适应。"""
        host = getattr(self, "_canvas_host", None)
        w = host.width() if host is not None else 0
        h = host.height() if host is not None else 0
        if w < 300:
            w = max(self.width() - _RIGHT_DEFAULT_W - 60, 300)
        if h < 200:
            h = max(self.height() - 220, 240)
        return (max(w - 12, 280) / 100.0, max(h - 12, 200) / 100.0)

    def _ordered(self):
        return list(self._last["rows"]) if self._last else []

    def _replot(self):
        rows = self._ordered()
        if not rows:
            self._draw_empty_plot()
            return
        self._set_canvas(self._render_fig(self._figsize(), dpi=100))

    def _render_fig(self, figsize, dpi=100):
        """按当前「图片设置」参数绘制能量图，返回 Figure（四边闭合黑框）。

        图内文字西文/数字用 Arial、中文回退黑体；rc_context 临时启用，
        不动全局 rcParams，避免影响其它面板的图。屏幕显示与「导出用指定
        尺寸」都走这里，保证所见即所得。
        """
        with _pic_rc():
            return self._fig_inner(figsize, dpi)

    def _fig_inner(self, figsize, dpi=100):
        """_render_fig 的实际绘制体：在字体 rc_context 内执行。"""
        rows = self._ordered()
        x = [r["num"] for r in rows]
        strain = [r["strain"] * K for r in rows]
        inter = [r["int"] * K for r in rows]
        total = [r["total"] * K for r in rows]

        fig = Figure(figsize=figsize, dpi=dpi, facecolor="white")
        ax = fig.add_subplot(111)
        eds = (self.ed_pic_leg1, self.ed_pic_leg2, self.ed_pic_leg3)
        proxies = []
        for ys, i in ((strain, 0), (inter, 1), (total, 2)):
            color = self._curve_color(i)
            ls = self._curve_ls(i)
            mk = self._curve_marker(i)
            lw = _DEFAULT_LWS[i]
            ms = _DEFAULT_MSS[i]
            fmt = (mk + ls) if mk else ls
            ax.plot(x, ys, fmt, color=color, lw=lw, ms=ms)
            # 图例统一用代理线，保证条目显示所选线型/散点/颜色
            proxies.append(Line2D(
                [], [], color=color, lw=lw, ls=ls,
                marker=mk or "None", ms=ms,
                label=eds[i].text().strip() or _LEG_LABEL_DEFAULTS[i]))
        ax.axhline(0, color="#9AA7B8", ls="--", lw=0.9)

        if self.chk_pic_peak.isChecked():
            ip = max(range(len(total)), key=lambda i: total[i])
            pk_dark, pk_base = _peak_palette(self._curve_color(2))
            peak_txt = self.ed_pic_peak_text.text().strip()
            if not peak_txt:
                peak_txt = "峰值 #%d\n%.1f" % (x[ip], total[ip])
            ax.annotate(peak_txt,
                        xy=(x[ip], total[ip]),
                        xytext=(0, 18), textcoords="offset points",
                        ha="center",
                        fontsize=self.sp_pic_annot_fs.value(),
                        color=pk_dark,
                        arrowprops=dict(arrowstyle="->", color=pk_base,
                                        lw=1.2))
            ax.plot([x[ip]], [total[ip]], "o", color=pk_dark, ms=9,
                    mfc="none", mew=1.8)

        label_fs = self.sp_pic_label_fs.value()
        ax.set_xlabel(self.ed_pic_x.text().strip() or "IRC 点序",
                      fontsize=label_fs)
        ax.set_ylabel(self.ed_pic_y.text().strip() or "能量 (kcal/mol)",
                      fontsize=label_fs)
        title = self.ed_pic_title.text().strip()
        if title:
            ax.set_title(title, fontsize=self.sp_pic_title_fs.value(),
                         pad=10)
        if self.chk_pic_grid.isChecked():
            ax.grid(alpha=0.28, ls=":")
        if self.chk_pic_legend.isChecked():
            if proxies:   # 标签留空会自动回落英文默认，此处仅防空列表
                ax.legend(handles=proxies,
                          fontsize=self.sp_pic_legend_fs.value(),
                          framealpha=0.9)
        # 四边边框默认全可见 → 与坐标轴围成闭合矩形
        ax.tick_params(labelsize=self.sp_pic_tick_fs.value())
        fig.tight_layout()
        return fig

    def _draw_empty_plot(self):
        fig = Figure(figsize=self._figsize(), dpi=100, facecolor="white")
        ax = fig.add_subplot(111)
        ax.text(0.5, 0.5, "设置完成后点「计算」显示 ASM 沿 IRC 曲线",
                ha="center", va="center", fontsize=12, color="#94A3B8")
        ax.set_xticks([])
        ax.set_yticks([])
        for s in ax.spines.values():
            s.set_visible(False)
        self._set_canvas(fig)

    def _set_canvas(self, fig):
        if self._canvas is not None:
            self._canvas_layout.removeWidget(self._canvas)
            try:
                self._canvas.close()
            except Exception:
                pass
        self._canvas = FigureCanvas(fig)
        self._canvas_layout.addWidget(self._canvas)
        with _pic_rc():
            self._canvas.draw()
        # 让图例可拖动（canvas 已就位；每次 fig 重建后重新挂一次）
        try:
            for _ax in fig.axes:
                _lg = _ax.get_legend()
                if _lg is not None:
                    _lg.set_draggable(True)
        except Exception:
            pass

    # ── 导出 ──
    def _export_csv(self):
        if not self._last or not self._last["rows"]:
            return
        p, _ = save_file(self, "导出 CSV", "asm_irc_scan.csv", "CSV (*.csv)")
        if not p:
            return
        try:
            with open(p, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["point", "E_def_A_hartree", "E_def_B_hartree",
                            "E_complex_hartree", "dE_strain_kcal",
                            "dE_int_kcal", "dE_total_kcal"])
                for r in self._last["rows"]:
                    w.writerow([r["num"], "%.8f" % r["e_def_a"],
                                "%.8f" % r["e_def_b"],
                                "%.8f" % r["e_complex"],
                                "%.4f" % (r["strain"] * K),
                                "%.4f" % (r["int"] * K),
                                "%.4f" % (r["total"] * K)])
            self._log("ASM-IRC: 已导出 %s" % os.path.basename(p))
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def _save_png(self):
        if self._canvas is None:
            return
        p, _ = save_file(self, "保存图片", "asm_irc_scan.png", "PNG (*.png)")
        if not p:
            return
        try:
            dpi = self.sp_pic_dpi.value()
            if self.chk_pic_outsize.isChecked():
                # 按指定图宽/图高另渲染一张同参数图片，所见即所得
                fig = self._render_fig(
                    (self.sp_pic_outw.value(), self.sp_pic_outh.value()),
                    dpi=dpi)
                with _pic_rc():
                    fig.savefig(p, dpi=dpi, bbox_inches="tight",
                                facecolor="white")
            else:
                with _pic_rc():
                    self._canvas.figure.savefig(p, dpi=dpi,
                                                bbox_inches="tight",
                                                facecolor="white")
            self._log("ASM-IRC: 已保存 %s (DPI=%d)" % (os.path.basename(p), dpi))
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))

    # ── 配置持久化 ──
    def _settings_path(self):
        # 与 fchk_orbital.ini 同级：源码运行放仓库根目录，打包后放 exe 同目录
        from molstudio.paths import config_file
        return config_file("asm_irc_panel_settings.ini")

    def _load_settings(self):
        cfg = configparser.ConfigParser()
        try:
            if not os.path.exists(self._settings_path()):
                return
            cfg.read(self._settings_path(), encoding="utf-8")
            if "asm_irc" not in cfg:
                return
            s = cfg["asm_irc"]
            self.ed_dir.setText(s.get("dir", ""))
            self.ed_ref_a.setText(s.get("ref_a", ""))
            self.ed_ref_b.setText(s.get("ref_b", ""))
            mode = s.get("mode", "scf")
            for i in range(self.cb_mode.count()):
                if self.cb_mode.itemData(i) == mode:
                    self.cb_mode.setCurrentIndex(i)
                    break
            self._load_pic_settings(s)
            for line in s.get("points", "").splitlines():
                parts = line.split("|")
                if len(parts) == 4:
                    try:
                        self._append_row(int(parts[0]), parts[1], parts[2],
                                         parts[3])
                    except ValueError:
                        pass
        except Exception:
            pass

    def _save_settings(self):
        cfg = configparser.ConfigParser()
        lines = []
        for r in range(self.tw_pts.rowCount()):
            def txt(c):
                it = self.tw_pts.item(r, c)
                return (it.text().strip() if it else "")
            lines.append("|".join((txt(C_NUM), txt(C_COMPLEX), txt(C_FRAG_A),
                                   txt(C_FRAG_B))))
        cfg["asm_irc"] = {
            "dir": self.ed_dir.text().strip(),
            "ref_a": self.ed_ref_a.text().strip(),
            "ref_b": self.ed_ref_b.text().strip(),
            "mode": self.cb_mode.currentData() or "scf",
            "pic_expanded": "1" if self._pic_gb.isChecked() else "0",
            "pic_title": self.ed_pic_title.text(),
            "pic_xlabel": self.ed_pic_x.text(),
            "pic_ylabel": self.ed_pic_y.text(),
            "pic_leg1": self.ed_pic_leg1.text(),
            "pic_leg2": self.ed_pic_leg2.text(),
            "pic_leg3": self.ed_pic_leg3.text(),
            "pic_m1": self._curve_marker(0),
            "pic_m2": self._curve_marker(1),
            "pic_m3": self._curve_marker(2),
            "pic_ls1": self._curve_ls(0),
            "pic_ls2": self._curve_ls(1),
            "pic_ls3": self._curve_ls(2),
            "pic_c1": self._curve_color(0),
            "pic_c2": self._curve_color(1),
            "pic_c3": self._curve_color(2),
            "pic_tick_fs": str(self.sp_pic_tick_fs.value()),
            "pic_legend_fs": str(self.sp_pic_legend_fs.value()),
            "pic_title_fs": str(self.sp_pic_title_fs.value()),
            "pic_annot_fs": str(self.sp_pic_annot_fs.value()),
            "pic_label_fs": str(self.sp_pic_label_fs.value()),
            "pic_grid": "1" if self.chk_pic_grid.isChecked() else "0",
            "pic_legend": "1" if self.chk_pic_legend.isChecked() else "0",
            "pic_peak": "1" if self.chk_pic_peak.isChecked() else "0",
            "pic_peak_text": self.ed_pic_peak_text.text(),
            "pic_outsize": "1" if self.chk_pic_outsize.isChecked() else "0",
            "pic_dpi": str(self.sp_pic_dpi.value()),
            "pic_outw": "%.1f" % self.sp_pic_outw.value(),
            "pic_outh": "%.1f" % self.sp_pic_outh.value(),
            "points": "\n".join(lines),
        }
        try:
            with open(self._settings_path(), "w", encoding="utf-8") as f:
                cfg.write(f)
        except Exception:
            pass

    def shutdown(self):
        """关闭时清理（本面板无后台线程）。"""
        self._save_settings()

    # ── i18n ──
    def set_lang(self, lang):
        """切换界面语言（中/英）。"""
        from molstudio.ui.i18n_utils import apply_text_map
        apply_text_map(self, _LANG_EXTRA, "zh" if lang == "zh" else "en")
