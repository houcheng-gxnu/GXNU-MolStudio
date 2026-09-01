"""
cub_canvas.py — 可嵌入的 Cube 可视化画布组件
=================================================
把 cub_viewer.py 的 OpenGL 渲染管线 (CubGLWidget) 封装成一个普通
QWidget，可以直接放进主程序 (main_window.py) 的左侧面板作为画布使用。

与 cub_viewer.CubViewer 的区别：
  * 继承 QWidget 而非 QMainWindow —— 可被任意布局/Splitter 收纳；
  * 控制项收拢成一条紧凑工具条 + 可折叠的参数区，节省左侧空间；
  * 提供 load_cube() / set_cube_list() 等公开接口供主窗口调用；
  * 不含 sys.argv 解析与独立窗口样式。

渲染内核 100% 复用 cub_viewer，任何渲染改动自动同步。
"""

import os
import math
import json

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QPushButton, QSlider, QGroupBox, QFileDialog, QMessageBox,
    QGridLayout, QCheckBox, QSizePolicy, QToolButton, QFrame, QColorDialog,
    QListView, QDialog, QSpinBox, QGraphicsDropShadowEffect, QApplication,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QPointF, QRectF
from PyQt5.QtGui import (
    QDoubleValidator, QIntValidator, QColor, QRadialGradient,
    QPainter, QPen, QBrush, QPainterPath, QRegion,
)

from ._glwidget import (
    CubGLWidget, STYLE_NAMES, STYLE_DISPLAY, IBOVIEW_DEFAULTS,
    MOL_STYLE_NAMES, MOL_STYLE_DISPLAY, _ensure_pyopengl,
    SHININESS_PRESETS, SHININESS_DEFAULT, _IBO_ELEMENT_COLORS,
)
from file_dialogs import open_file, save_file
from marching_cubes import read_cube, relative_iso_threshold
from ._colorwheel import ColorWheelWidget
import i18n

# ── 元素符号 / 名称表（元素原子颜色设置用） ──
_ELEM_SYMBOLS = {
    1: "H", 2: "He", 3: "Li", 4: "Be", 5: "B", 6: "C", 7: "N", 8: "O",
    9: "F", 10: "Ne", 11: "Na", 12: "Mg", 13: "Al", 14: "Si", 15: "P",
    16: "S", 17: "Cl", 18: "Ar", 19: "K", 20: "Ca", 21: "Sc", 22: "Ti",
    23: "V", 24: "Cr", 25: "Mn", 26: "Fe", 27: "Co", 28: "Ni", 29: "Cu",
    30: "Zn", 31: "Ga", 32: "Ge", 33: "As", 34: "Se", 35: "Br", 36: "Kr",
    37: "Rb", 38: "Sr", 39: "Y", 40: "Zr", 41: "Nb", 42: "Mo", 43: "Tc",
    44: "Ru", 45: "Rh", 46: "Pd", 47: "Ag", 48: "Cd", 49: "In", 50: "Sn",
    51: "Sb", 52: "Te", 53: "I", 54: "Xe", 55: "Cs", 56: "Ba", 72: "Hf",
    73: "Ta", 74: "W", 75: "Re", 76: "Os", 77: "Ir", 78: "Pt", 79: "Au",
    80: "Hg", 81: "Tl", 82: "Pb", 83: "Bi", 92: "U",
}
_ELEM_NAMES = {
    1: "氢", 5: "硼", 6: "碳", 7: "氮", 8: "氧", 9: "氟", 11: "钠",
    12: "镁", 13: "铝", 14: "硅", 15: "磷", 16: "硫", 17: "氯", 19: "钾",
    20: "钙", 22: "钛", 24: "铬", 25: "锰", 26: "铁", 27: "钴", 28: "镍",
    29: "铜", 30: "锌", 35: "溴", 47: "银", 53: "碘", 56: "钡",
    74: "钨", 78: "铂", 79: "金", 82: "铅", 92: "铀",
}

# ── 画布参数区 i18n ──
# key = 中文原文（构造处直接传原文，zh 模式原样显示），value = 英文。
_CV_EN = {
    # 一键样式 / 分子显示 / 导出行
    "一键样式:": "Styles:",
    "分子显示:": "Display:",
    "隐藏氢原子": "Hide hydrogens",
    "保留H编号:": "Keep H:",
    "如 1,3,5-8": "e.g. 1,3,5-8",
    "显示原子编号": "Show atom index",
    "显示元素符号": "Show element symbols",
    "键长标注": "Bond Labels",
    "清除": "Clear",
    "清空样式": "Clear analysis",
    "同步到VMD": "Sync to VMD",
    "透明背景": "Transparent BG",
    "截图": "Snapshot",
    "导出图片": "Export Image",
    "重置视角": "Reset View",
    "参数": "Parameters",
    # 参数区行标签
    "等值面配色:": "Iso color:",
    "光照:": "Lighting:",
    "原子配色:": "Atom colors:",
    "元素颜色…": "Element colors…",
    "元素原子颜色": "Element Atom Colors",
    "点击色块选择颜色；点「恢复」还原该元素默认色":
        "Click a swatch to pick a color; \"Reset\" restores the default",
    "恢复": "Reset",
    "全部恢复默认": "Reset All",
    "取消": "Cancel",
    "确定": "OK",
    "光泽:": "Shininess:",
    "选中标记:": "Sel. marker:",
    "呼吸:": "Pulse:",
    "等值面大小:": "Isovalue:",
    "透明度:": "Transparency:",
    "层数:": "Layers:",
    "网格精度:": "Grid:",
    "粗细:": "Width:",
    "色轮:": "Wheel:",
    "相位配色:": "Phase scheme:",
    "正相位:": "Pos:",
    "负相位:": "Neg:",
    "灯光:": "Lights:",
    "样式:": "Preset:",
    # 等值面组控件
    "等值面描边": "Isosurface outline",
    "描边颜色:": "Outline color:",
    "颜色": "Color",
    "重置": "Reset",
    "启用色轮配色": "Wheel drives colors",
    "翻转相位": "Flip Phase",
    "光源设置…": "Lights…",
    "保存…": "Save…",
    "载入…": "Load…",
    "二十面体": "Icosahedron",
    "透明球": "Ghost sphere",
    "圆环": "Ring",
    "光晕": "Glow",
    "低 (1)": "Low (1)",
    "中 (2)": "Med (2)",
    "高 (3)": "High (3)",
    # 光照下拉显示名（_LIGHTING_OPTIONS）
    "IboView 三光": "IboView 3-light",
    "单光 · Houk": "1-light · Houk",
    "单光 · 柔和": "1-light · Soft matte",
    "单光 · 微妙": "1-light · Subtle",
    "单光 · 平面": "1-light · Flat",
    "单光 · Chem311": "1-light · Chem311",
    "单光 · 苹果液态": "1-light · Apple liquid",
    "单光 · 纸感": "1-light · Paper matte",
    "单光 · 高级": "1-light · Premium",
    "单光 · 粘土": "1-light · Clay",
    "单光 · 玻璃": "1-light · Glass",
    "单光 · 霓虹": "1-light · Neon",
    "单光 · 墨线": "1-light · Ink flat",
    "单光 · GaussView": "1-light · GaussView",
    "双光源": "Two lights",
    "四光源": "Four lights",
    # 原子配色下拉显示名（MOL_STYLE_DISPLAY）
    "CPK (按元素)": "CPK (by element)",
    "VMD (碳金色)": "VMD (gold carbon)",
    "单色白": "Monochrome white",
    "灰度出版": "Grayscale (print)",
    "霓虹": "Neon",
    "GaussView": "GaussView",
    "HoukMol": "HoukMol",
    "SobArt (Chem311)": "SobArt (Chem311)",
    "Vcube (VMD 风格)": "Vcube (VMD style)",
    "相近色 (±25°)": "Analogous (±25°)",
    "同色相·不同饱和": "Same hue, diff. sat.",
    "互补色 (180°)": "Complementary (180°)",
    " 层": " layers",
    # 折叠组标题
    "显示 / 等值面": "Display / Isosurface",
    "球棍模型": "Ball & Stick",
    # 球棍模型组
    "原子半径:": "Atom radius:",
    "范德华半径": "vdW radii",
    "vdW 外壳": "vdW shell",
    "仅选中片段": "Selected frags only",
    "外壳描边": "Shell outline",
    "片段:": "Frags:",
    "原子编号, 如 1-12,15": "atom indices, e.g. 1-12,15",
    "外壳透明度:": "Shell opacity:",
    "外壳描边粗细:": "Shell outline w:",
    "vdW 半径:": "vdW radius:",
    "化学键:": "Bonds:",
    "键收腰:": "Bond waist:",
    "十字圆环:": "Cross rings:",
    "显示": "Show",
    "圆环设置…": "Ring settings…",
    "虚线大小:": "Dash size:",
    "虚线间隔:": "Dash spacing:",
    "原子描边:": "Atom outline:",
    "启用": "Enable",
    "描边粗细:": "Outline width:",
    "背景色:": "Background:",
    "选择…": "Pick…",
    "景深雾化": "Depth fade",
    "未安装 PyOpenGL，画布不可用。\n请运行: pip install PyOpenGL PyOpenGL-accelerate":
        "PyOpenGL not installed — canvas unavailable.\nRun: pip install PyOpenGL PyOpenGL-accelerate",
    "渲染器初始化中…": "Renderer initializing…",
    # RingControlDialog
    "十字圆环控制": "Cross Ring Control",
    "环 A 方位角:": "Ring A azimuth:",
    "环 A 俯仰角:": "Ring A elevation:",
    "环 B 方位角:": "Ring B azimuth:",
    "环 B 俯仰角:": "Ring B elevation:",
    "锁定方位（锁定当前角度，分子旋转时圆环不变）":
        "Lock orientation (rings keep angle while molecule rotates)",
    "环带粗细:": "Ring band width:",
    "重置默认": "Reset defaults",
    "关闭": "Close",
    "灯%d": "Light %d",
    # LightControlDialog
    "光源控制": "Light Control",
    "光源数量:": "Light count:",
    "方位角:": "Azimuth:",
    "俯仰角:": "Elevation:",
    "光晕(整体):": "Glow (global):",
    "各灯光晕:": "Per-light glow:",
    "保存设置…": "Save…",
    "载入设置…": "Load…",
}


def _cv(text):
    """画布参数区文本翻译：zh 原样返回，en 查 _CV_EN（无条目返回原文）。"""
    if i18n._CURRENT_LANG == "zh":
        return text
    return _CV_EN.get(text, text)


# 光照/渲染效果轴（与「原子配色」轴正交）：
# 显示名 → 渐变类型名（"" = IboView 三光，即 u_MvGrad=0；光泽由「光泽」下拉框独立控制）
_LIGHTING_OPTIONS = [
    ("IboView 三光", ""),
    ("单光 · Houk", "full"),
    ("单光 · 柔和", "soft_matte"),
    ("单光 · 微妙", "subtle"),
    ("单光 · 平面", "flat"),
    ("单光 · Chem311", "sob_art"),
    ("单光 · 苹果液态", "apple_liquid"),
    ("单光 · 纸感", "paper_matte"),
    ("单光 · 高级", "premium_full"),
    ("单光 · 粘土", "clay_matte"),
    ("单光 · 玻璃", "glass_plus"),
    ("单光 · 霓虹", "neon_glow"),
    ("单光 · 墨线", "ink_flat"),
    ("单光 · GaussView", "gau_default"),
    ("双光源", "two_light"),
    ("四光源", "four_light"),
]

# sob-art 一键样式：光照信息（导出自 light_style3.json，4 灯）
_SOBART_STYLE = {
    "light_count": 4,
    "light_dirs": [
        [0.373134328358209, 0.5373134328358209, 0.7563498184668613],
        [-0.2835820895522388, -0.6865671641791045, 0.6694824325971882],
        [0.05970149253731343, -0.014925373134328358, 0.9981046864059993],
        [-0.5522388059701493, 0.5373134328358209, 0.6374375075839588],
    ],
    "light_glow": 0.51,
    "light_glows": [0.88, 0.88, 0.88, 0.1],
}

# 默认样式「HoukMol」（导出自 HoukMol.json，单光 gau_default，默认不显示十字圆环）
_HOUKMOL_STYLE = {
    "mol_style": "HoukMol",
    "gradient": "gau_default",
    "shininess": "reasonably shiny",
    "light_count": 1,
    "light_dirs": [
        [-0.577, 0.577, 0.577],
        [0.0, 0.0, 1.0],
        [0.0, 0.0, 1.0],
        [0.0, 0.0, 1.0],
    ],
    "light_glow": 1.25,
    "atom_scale": 1.68,
    "bond_scale": 2.0,
    "atom_outline": [True, [0.0, 0.0, 0.0], 0.35],
    "orb_outline": [True, [0.0, 0.0, 0.0], 0.2],
    "orb_opacity": 0.3,
    "phase_pos": [0.6666666666666666, 1.0, 0.4980392156862745],
    "phase_neg": [0.0, 0.6666666666666666, 1.0],
    "bg": [1.0, 1.0, 1.0, 1.0],
    "crosshair": False,
    "fade": False,
    "carbon": None,
    "hydrogen": None,
}

# HoukMol 一键样式的默认圆环方位（导出自 ring_style.json，随分子转；默认不显示）
_HOUKMOL_RING = {
    "on": False,
    "az1": 90.0,
    "tilt1": 79.0,
    "az2": 19.0,
    "tilt2": 11.0,
    "locked": False,
    "width": 0.04,
    "color": [0.05, 0.05, 0.05],
}

# 默认样式「IQmol」（导出自 IQMOL.json：CPK 原子、双光、每灯独立光晕、红/蓝相位）
_IQMOL_STYLE = {
    "mol_style": "CPK",
    "gradient": "",
    "shininess": "reasonably shiny",
    "light_count": 2,
    "light_dirs": [
        [0.40298507462686567, 0.7761194029850746, 0.4850172181872215],
        [0.1791044776119403, 0.04477611940298507, 0.9828106049644375],
        [0.4330127, -0.25, 0.8660254],
        [0.0, 0.0, 1.0],
    ],
    "light_glow": 1.0,
    "light_glows": [0.1, 0.29, 1.0, 1.0],
    "atom_scale": 1.68,
    "bond_scale": 2.0,
    "atom_outline": [False, [0.0, 0.0, 0.0], 0.35],
    "orb_outline": [False, [0.0, 0.0, 0.0], 0.3],
    "orb_opacity": 0.95,
    "phase_pos": [0.8862745098039215, 0.1450980392156863, 0.30980392156862746],
    "phase_neg": [0.0, 0.3843137254901961, 1.0],
    "bg": [1.0, 1.0, 1.0, 1.0],
    "crosshair": False,
    "fade": True,
    "carbon": None,
    "hydrogen": None,
    "depth_peeling": False,
}


def _parse_color(color):
    """把颜色统一成 (r,g,b) 0-255 元组。

    接受 '#rrggbb' / '#rgb' 字符串，或 (r,g,b) / [r,g,b]（0-255）序列。
    """
    if isinstance(color, str):
        c = color.lstrip("#")
        if len(c) == 3:
            c = "".join(ch * 2 for ch in c)
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    return tuple(int(round(float(v))) for v in color[:3])


class ElementColorDialog(QDialog):
    """自定义每种元素的原子颜色（覆盖默认 CPK 配色）。"""

    def __init__(self, parent, glw):
        super().__init__(parent)
        self._glw = glw
        self.setWindowTitle(_cv("元素原子颜色"))
        self.setMinimumWidth(420)

        # 收集元素：当前分子中存在的 + 常用元素
        present = set()
        atoms = getattr(glw, "_molecule", None)
        if not atoms and getattr(glw, "_cube", None) is not None:
            atoms = getattr(glw._cube, "atoms", None)
        if atoms:
            try:
                present = {int(a[0]) for a in atoms}
            except (TypeError, ValueError, IndexError):
                present = set()
        common = [6, 1, 7, 8, 9, 15, 16, 17, 35, 53, 5, 14, 3, 11, 12, 13,
                  19, 20, 22, 26, 29, 30, 47, 79]
        self._elems = list(dict.fromkeys(common + sorted(present)))

        # 当前颜色：已有元素覆盖优先，否则默认 CPK 表（_IBO_ELEMENT_COLORS）
        try:
            self._cur = dict(getattr(glw, "element_colors", lambda: {})())
        except Exception:
            self._cur = {}

        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        tip = QLabel(_cv("点击色块选择颜色；点「恢复」还原该元素默认色"))
        tip.setStyleSheet("color:#64748B; font-size:9pt;")
        lay.addWidget(tip)

        self._swatches = {}   # anum -> QPushButton
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        for i, anum in enumerate(self._elems):
            sym = _ELEM_SYMBOLS.get(anum, str(anum))
            name = _ELEM_NAMES.get(anum, "")
            col = self._cur.get(anum) or self._default_color(anum)
            self._cur[anum] = col
            btn = QPushButton()
            btn.setFixedSize(34, 22)
            btn.setCursor(Qt.PointingHandCursor)
            self._set_swatch(btn, col)
            btn.clicked.connect(lambda _=False, a=anum: self._pick(a))
            self._swatches[anum] = btn
            grid.addWidget(btn, i, 0)
            lbl = QLabel(f"{sym}  {name}".strip())
            lbl.setMinimumWidth(70)
            grid.addWidget(lbl, i, 1)
            hex_lbl = QLabel(self._hex_str(col))
            hex_lbl.setStyleSheet("color:#64748B; font-size:9pt;")
            grid.addWidget(hex_lbl, i, 2)
            b_reset = QPushButton(_cv("恢复"))
            b_reset.setObjectName("SmallBtn")
            b_reset.setFixedWidth(52)
            b_reset.clicked.connect(lambda _=False, a=anum: self._reset_one(a))
            grid.addWidget(b_reset, i, 3)
        lay.addLayout(grid)

        btn_row = QHBoxLayout()
        b_all = QPushButton(_cv("全部恢复默认"))
        b_all.setObjectName("SmallBtn")
        b_all.clicked.connect(self._reset_all)
        btn_row.addWidget(b_all)
        btn_row.addStretch(1)
        b_cancel = QPushButton(_cv("取消"))
        b_cancel.clicked.connect(self.reject)
        btn_row.addWidget(b_cancel)
        b_ok = QPushButton(_cv("确定"))
        b_ok.setObjectName("PrimaryBtn")
        b_ok.clicked.connect(self.accept)
        btn_row.addWidget(b_ok)
        lay.addLayout(btn_row)

    def _default_color(self, anum):
        try:
            return tuple(_IBO_ELEMENT_COLORS[anum])
        except (IndexError, TypeError):
            return (0.55, 0.55, 0.55)

    def _hex_str(self, rgb01):
        r, g, b = (int(round(c * 255)) for c in rgb01)
        return "#%02X%02X%02X" % (r, g, b)

    def _set_swatch(self, btn, rgb01):
        r, g, b = (int(round(c * 255)) for c in rgb01)
        btn.setStyleSheet(
            f"background:#{r:02X}{g:02X}{b:02X}; border:1px solid #94A3B8;"
            " border-radius:4px;")

    def _pick(self, anum):
        cur = self._cur.get(anum, self._default_color(anum))
        col = QColorDialog.getColor(
            QColor(*(int(round(c * 255)) for c in cur)), self, "选择颜色")
        if col.isValid():
            rgb = (col.red() / 255.0, col.green() / 255.0, col.blue() / 255.0)
            self._cur[anum] = rgb
            self._set_swatch(self._swatches[anum], rgb)
            # 同步 hex 标签（第 3 列）
            idx = self._elems.index(anum)
            item = self.layout().itemAt(0)   # tip
            grid = self.layout().itemAt(1).layout()
            lbl = grid.itemAtPosition(idx, 2).widget()
            lbl.setText(self._hex_str(rgb))

    def _reset_one(self, anum):
        rgb = self._default_color(anum)
        self._cur[anum] = rgb
        self._set_swatch(self._swatches[anum], rgb)
        idx = self._elems.index(anum)
        grid = self.layout().itemAt(1).layout()
        lbl = grid.itemAtPosition(idx, 2).widget()
        lbl.setText(self._hex_str(rgb))

    def _reset_all(self):
        for anum in self._elems:
            self._cur[anum] = self._default_color(anum)
            self._set_swatch(self._swatches[anum], self._cur[anum])
            idx = self._elems.index(anum)
            grid = self.layout().itemAt(1).layout()
            lbl = grid.itemAtPosition(idx, 2).widget()
            lbl.setText(self._hex_str(self._cur[anum]))

    def result_overrides(self):
        """返回 {atomic_number: (r,g,b) 0..1}，仅含用户改过的元素。"""
        out = {}
        defaults = {}
        for anum in self._elems:
            defaults[anum] = self._default_color(anum)
        for anum, rgb in self._cur.items():
            if tuple(round(float(c), 4) for c in rgb) != \
                    tuple(round(float(c), 4) for c in defaults.get(anum, (0, 0, 0))):
                out[anum] = tuple(float(c) for c in rgb)
        return out


class RingControlDialog(QDialog):
    """十字圆环控制面板：两条环的方位角/俯仰角 + 锁定开关。

    锁定后圆环固定在屏幕系（分子怎么旋转圆环都不转）；未锁定时圆环随分子旋转。
    """

    def __init__(self, glw, parent=None):
        super().__init__(parent)
        self.glw = glw
        self.setWindowTitle(_cv("十字圆环控制"))
        self.setMinimumWidth(360)
        f = QGridLayout(self)
        f.setVerticalSpacing(8)

        f.addWidget(QLabel(_cv("环 A 方位角:")), 0, 0)
        self.sl_az1 = QSlider(Qt.Horizontal)
        self.sl_az1.setRange(0, 360)
        self.sl_az1.setValue(90)
        self.sl_az1.valueChanged.connect(self._apply)
        f.addWidget(self.sl_az1, 0, 1)

        f.addWidget(QLabel(_cv("环 A 俯仰角:")), 1, 0)
        self.sl_tilt1 = QSlider(Qt.Horizontal)
        self.sl_tilt1.setRange(0, 90)
        self.sl_tilt1.setValue(71)
        self.sl_tilt1.valueChanged.connect(self._apply)
        f.addWidget(self.sl_tilt1, 1, 1)

        f.addWidget(QLabel(_cv("环 B 方位角:")), 2, 0)
        self.sl_az2 = QSlider(Qt.Horizontal)
        self.sl_az2.setRange(0, 360)
        self.sl_az2.setValue(205)
        self.sl_az2.valueChanged.connect(self._apply)
        f.addWidget(self.sl_az2, 2, 1)

        f.addWidget(QLabel(_cv("环 B 俯仰角:")), 3, 0)
        self.sl_tilt2 = QSlider(Qt.Horizontal)
        self.sl_tilt2.setRange(0, 90)
        self.sl_tilt2.setValue(0)
        self.sl_tilt2.valueChanged.connect(self._apply)
        f.addWidget(self.sl_tilt2, 3, 1)

        self.chk_lock = QCheckBox(_cv("锁定方位（锁定当前角度，分子旋转时圆环不变）"))
        self.chk_lock.setChecked(False)
        self.chk_lock.setToolTip("勾选后把当前圆环角度冻结；分子怎么旋转圆环都不再改变")
        self.chk_lock.toggled.connect(self._apply)
        f.addWidget(self.chk_lock, 4, 0, 1, 2)

        f.addWidget(QLabel(_cv("环带粗细:")), 5, 0)
        self.sl_w = QSlider(Qt.Horizontal)
        self.sl_w.setRange(2, 20)          # 0.02 .. 0.20 环带半宽
        self.sl_w.setValue(7)              # 默认 0.07
        self.sl_w.valueChanged.connect(self._apply)
        f.addWidget(self.sl_w, 5, 1)
        self._w_lbl = QLabel("0.07")
        self._w_lbl.setMinimumWidth(34)
        f.addWidget(self._w_lbl, 5, 2)

        btns = QHBoxLayout()
        b_reset = QPushButton(_cv("重置默认"))
        b_reset.clicked.connect(self._reset)
        b_save = QPushButton(_cv("保存…"))
        b_save.clicked.connect(self._save)
        b_load = QPushButton(_cv("载入…"))
        b_load.clicked.connect(self._load)
        b_close = QPushButton(_cv("关闭"))
        b_close.clicked.connect(self.accept)
        btns.addWidget(b_reset)
        btns.addWidget(b_save)
        btns.addWidget(b_load)
        btns.addStretch(1)
        btns.addWidget(b_close)
        f.addLayout(btns, 6, 0, 1, 2)
        self.sync_from_glw()

    def sync_from_glw(self):
        """从画布当前圆环状态同步滑块。"""
        if self.glw is None:
            return
        self.sl_az1.blockSignals(True)
        self.sl_az1.setValue(int(getattr(self.glw, "_ring_az1", 90) % 360))
        self.sl_az1.blockSignals(False)
        self.sl_tilt1.blockSignals(True)
        self.sl_tilt1.setValue(int(getattr(self.glw, "_ring_tilt1", 71)))
        self.sl_tilt1.blockSignals(False)
        self.sl_az2.blockSignals(True)
        self.sl_az2.setValue(int(getattr(self.glw, "_ring_az2", 205) % 360))
        self.sl_az2.blockSignals(False)
        self.sl_tilt2.blockSignals(True)
        self.sl_tilt2.setValue(int(getattr(self.glw, "_ring_tilt2", 0)))
        self.sl_tilt2.blockSignals(False)
        self.chk_lock.blockSignals(True)
        self.chk_lock.setChecked(bool(getattr(self.glw, "_ring_locked", False)))
        self.chk_lock.blockSignals(False)
        self.sl_w.blockSignals(True)
        self.sl_w.setValue(int(getattr(self.glw, "_ring_width", 0.07) * 100))
        self.sl_w.blockSignals(False)
        self._w_lbl.setText(f"{getattr(self.glw, '_ring_width', 0.07):.2f}")

    def _save(self):
        if self.glw is None:
            return
        p, _ = save_file(self, "保存圆环设置", "ring_style.json",
                         "JSON (*.json)")
        if not p:
            return
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(self.glw.get_ring_state(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))

    def _load(self):
        if self.glw is None:
            return
        p, _ = open_file(self, "载入圆环设置", "", "JSON (*.json)")
        if not p:
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                st = json.load(f)
            self.glw.apply_ring_state(st)
            self.sync_from_glw()
            # 同步主面板「十字圆环」复选框
            par = self.parent()
            if hasattr(par, "_crosshair_chk"):
                par._crosshair_chk.blockSignals(True)
                par._crosshair_chk.setChecked(bool(self.glw._crosshair))
                par._crosshair_chk.blockSignals(False)
        except Exception as e:
            QMessageBox.warning(self, "载入失败", str(e))

    def _apply(self):
        if self.glw is None:
            return
        w = self.sl_w.value() / 100.0
        self._w_lbl.setText(f"{w:.2f}")
        self.glw.set_ring_style(width=w)
        self.glw.set_ring_orientation(
            az1=self.sl_az1.value(), tilt1=self.sl_tilt1.value(),
            az2=self.sl_az2.value(), tilt2=self.sl_tilt2.value(),
            locked=self.chk_lock.isChecked())

    def _reset(self):
        for sl, v in ((self.sl_az1, 90), (self.sl_tilt1, 71),
                      (self.sl_az2, 205), (self.sl_tilt2, 0),
                      (self.sl_w, 7)):
            sl.blockSignals(True)
            sl.setValue(v)
            sl.blockSignals(False)
        self._w_lbl.setText("0.07")
        self.chk_lock.blockSignals(True)
        self.chk_lock.setChecked(False)
        self.chk_lock.blockSignals(False)
        self._apply()


class LightSphereWidget(QWidget):
    """光源球体预览：画一个渐变球，把当前各光源方向投影成光点。

    支持鼠标拖拽光点手动摆放光源方向（dirsChanged 信号通知对话框同步）。
    """
    dirsChanged = pyqtSignal()

    def __init__(self, glw, parent=None):
        super().__init__(parent)
        self.glw = glw
        self.setFixedSize(150, 150)
        self.setToolTip("拖动光点可手动摆放光源方向（球面明暗渐变跟随主光源）")
        self._drag_idx = None

    def _center_r(self):
        w, h = self.width(), self.height()
        return w / 2.0, h / 2.0, min(w, h) / 2.0 - 8

    def _light_pos(self, d):
        cx, cy, r = self._center_r()
        m = math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]) or 1.0
        return cx + (d[0] / m) * r, cy - (d[1] / m) * r

    def _dir_from_pos(self, mx, my):
        cx, cy, r = self._center_r()
        rx = (mx - cx) / r
        ry = (cy - my) / r
        l2 = rx * rx + ry * ry
        if l2 > 1.0:
            inv = 1.0 / math.sqrt(l2)
            return (rx * inv, ry * inv, 0.0)
        return (rx, ry, math.sqrt(max(0.0, 1.0 - l2)))

    def _apply_pos(self, idx, mx, my):
        if self.glw is None:
            return
        self.glw.set_light_dir(idx, self._dir_from_pos(mx, my))
        self.update()
        self.dirsChanged.emit()

    def mousePressEvent(self, e):
        dirs = getattr(self.glw, "_light_dirs", None) or []
        count = getattr(self.glw, "_light_count", 0)
        best, best_d = None, 14.0
        for i in range(min(count, len(dirs))):
            px, py = self._light_pos(dirs[i])
            d = math.hypot(e.x() - px, e.y() - py)
            if d < best_d:
                best, best_d = i, d
        self._drag_idx = best
        if best is not None:
            self._apply_pos(best, e.x(), e.y())

    def mouseMoveEvent(self, e):
        if self._drag_idx is not None:
            self._apply_pos(self._drag_idx, e.x(), e.y())

    def mouseReleaseEvent(self, e):
        self._drag_idx = None

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy, r = self._center_r()
        dirs = getattr(self.glw, "_light_dirs", None) or []
        # 球体底：高光中心跟随主光源（第 0 盏）方向，方向可控。
        # 无光源时退回默认左上（0.35 偏移）。偏移限制在 0.6R 内，保证球面
        # 始终有明暗层次；光源越偏向屏幕中央（z 越大）高光越靠近球心。
        hx, hy = cx - r * 0.35, cy - r * 0.35
        if dirs:
            d0 = dirs[0]
            m = math.sqrt(d0[0] * d0[0] + d0[1] * d0[1] + d0[2] * d0[2]) or 1.0
            hx = cx + (d0[0] / m) * r * 0.6
            hy = cy - (d0[1] / m) * r * 0.6
        grad = QRadialGradient(hx, hy, r)
        grad.setColorAt(0.0, QColor(255, 255, 255))
        grad.setColorAt(0.25, QColor(215, 225, 240))
        grad.setColorAt(0.7, QColor(120, 140, 170))
        grad.setColorAt(1.0, QColor(55, 70, 95))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        p.drawEllipse(QPointF(cx, cy), r, r)
        # 光点：光方向在视图平面的投影
        dirs = getattr(self.glw, "_light_dirs", None) or []
        count = getattr(self.glw, "_light_count", 0)
        for i in range(min(count, len(dirs))):
            px, py = self._light_pos(dirs[i])
            col = QColor(255, 220, 60) if i == 0 else QColor(255, 150, 60)
            p.setPen(QPen(QColor(255, 255, 255), 1.5))
            p.setBrush(QBrush(col))
            p.drawEllipse(QPointF(px, py), 7.0, 7.0)
            p.setPen(QPen(QColor(20, 30, 45), 1.0))
            p.drawText(int(px - 8), int(py - 11), str(i + 1))
        p.end()


class LightControlDialog(QDialog):
    """光源控制面板：左侧球体实时预览光点，右侧数量/方向/光晕滑块。"""

    def __init__(self, glw, parent=None):
        super().__init__(parent)
        self.glw = glw
        self.setWindowTitle(_cv("光源控制"))
        self.setMinimumWidth(430)
        lay = QHBoxLayout(self)
        self.sphere = LightSphereWidget(glw)
        self.sphere.dirsChanged.connect(self._on_sphere_dirs_changed)
        lay.addWidget(self.sphere)
        right = QVBoxLayout()
        right.setSpacing(4)

        right.addWidget(QLabel(_cv("光源数量:")))
        self.sl_cnt = QSlider(Qt.Horizontal)
        self.sl_cnt.setRange(1, 4)
        self.sl_cnt.valueChanged.connect(self._apply)
        right.addWidget(self.sl_cnt)
        self._cnt_lbl = QLabel("3")
        right.addWidget(self._cnt_lbl)

        right.addWidget(QLabel(_cv("方位角:")))
        self.sl_az = QSlider(Qt.Horizontal)
        self.sl_az.setRange(-180, 180)
        self.sl_az.valueChanged.connect(self._apply)
        right.addWidget(self.sl_az)

        right.addWidget(QLabel(_cv("俯仰角:")))
        self.sl_el = QSlider(Qt.Horizontal)
        self.sl_el.setRange(-90, 90)
        self.sl_el.valueChanged.connect(self._apply)
        right.addWidget(self.sl_el)

        right.addWidget(QLabel(_cv("光晕(整体):")))
        self.sl_glow = QSlider(Qt.Horizontal)
        self.sl_glow.setRange(10, 300)          # 0.1 .. 3.0
        self.sl_glow.valueChanged.connect(self._apply)
        right.addWidget(self.sl_glow)
        self._glow_lbl = QLabel("1.00")
        right.addWidget(self._glow_lbl)

        # 每盏灯独立光晕（仅显示当前生效的灯；数量改变时自动显隐）
        right.addWidget(QLabel(_cv("各灯光晕:")))
        glow_grid = QGridLayout()
        glow_grid.setContentsMargins(0, 0, 0, 0)
        glow_grid.setSpacing(4)
        self._glow_i_lbls, self._glow_i_sliders, self._glow_i_vals = [], [], []
        for i in range(4):
            lbl = QLabel(_cv("灯%d") % (i + 1))
            lbl.setAlignment(Qt.AlignHCenter)
            glow_grid.addWidget(lbl, 0, i)
            sl = QSlider(Qt.Horizontal)
            sl.setRange(10, 300)                # 0.1 .. 3.0
            sl.setMinimumWidth(52)
            sl.valueChanged.connect(self._apply)
            glow_grid.addWidget(sl, 1, i)
            v = QLabel("1.00")
            v.setAlignment(Qt.AlignHCenter)
            glow_grid.addWidget(v, 2, i)
            self._glow_i_lbls.append(lbl)
            self._glow_i_sliders.append(sl)
            self._glow_i_vals.append(v)
        right.addLayout(glow_grid)

        btns = QHBoxLayout()
        b_reset = QPushButton(_cv("重置"))
        b_reset.clicked.connect(self._reset)
        b_save = QPushButton(_cv("保存设置…"))
        b_save.setToolTip("把当前光源设置（数量/方向/光晕）保存为 JSON 文件")
        b_save.clicked.connect(self._save)
        b_load = QPushButton(_cv("载入设置…"))
        b_load.setToolTip("从 JSON 文件载入光源设置并应用")
        b_load.clicked.connect(self._load)
        b_close = QPushButton(_cv("关闭"))
        b_close.clicked.connect(self.accept)
        btns.addWidget(b_reset)
        btns.addWidget(b_save)
        btns.addWidget(b_load)
        btns.addStretch(1)
        btns.addWidget(b_close)
        right.addLayout(btns)
        lay.addLayout(right, 1)
        self.sync_from_glw()

    def _save(self):
        """保存光源设置（数量/方向/每灯光晕）到 JSON。"""
        if self.glw is None:
            return
        p, _ = save_file(self, "保存光源设置", "light_style.json",
                         "JSON (*.json)")
        if not p:
            return
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump({
                    "light_count": self.glw._light_count,
                    "light_dirs": [list(d) for d in self.glw._light_dirs],
                    "light_glow": self.glw._light_glow,
                    "light_glows": list(self.glw._light_glows),
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))

    def _load(self):
        """从 JSON 载入光源设置并应用（只动光源，不动光照模式/配色）。"""
        if self.glw is None:
            return
        p, _ = open_file(self, "载入光源设置", "", "JSON (*.json)")
        if not p:
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                st = json.load(f)
            if "light_count" in st:
                self.glw.set_light_count(int(st["light_count"]))
            if st.get("light_dirs"):
                self.glw._light_default_dirs = [
                    tuple(float(x) for x in d[:3]) for d in st["light_dirs"][:4]]
                while len(self.glw._light_default_dirs) < 4:
                    self.glw._light_default_dirs.append((0.0, 0.0, 1.0))
                self.glw._light_dirs = [list(x) for x in self.glw._light_default_dirs]
                self.glw._light_az = 0.0
                self.glw._light_el = 0.0
            if "light_glow" in st:
                self.glw.set_light_glow(float(st["light_glow"]))
            if st.get("light_glows"):
                for i, g in enumerate(st["light_glows"][:4]):
                    self.glw.set_light_glow_i(i, g)
            self.glw.update()
            self.sync_from_glw()
        except Exception as e:
            QMessageBox.warning(self, "载入失败", str(e))

    def sync_from_glw(self):
        """从画布当前光源状态同步滑块与球体预览。"""
        if self.glw is None:
            return
        self.sl_cnt.blockSignals(True)
        self.sl_cnt.setValue(getattr(self.glw, "_light_count", 3))
        self.sl_cnt.blockSignals(False)
        self._cnt_lbl.setText(str(getattr(self.glw, "_light_count", 3)))
        self.sl_az.blockSignals(True)
        self.sl_az.setValue(int(getattr(self.glw, "_light_az", 0)))
        self.sl_az.blockSignals(False)
        self.sl_el.blockSignals(True)
        self.sl_el.setValue(int(getattr(self.glw, "_light_el", 0)))
        self.sl_el.blockSignals(False)
        self.sl_glow.blockSignals(True)
        self.sl_glow.setValue(int(getattr(self.glw, "_light_glow", 1.0) * 100))
        self.sl_glow.blockSignals(False)
        self._glow_lbl.setText(f"{getattr(self.glw, '_light_glow', 1.0):.2f}")
        glows = list(getattr(self.glw, "_light_glows", None) or [1.0] * 4)
        while len(glows) < 4:
            glows.append(1.0)
        for i in range(4):
            self._glow_i_sliders[i].blockSignals(True)
            self._glow_i_sliders[i].setValue(int(glows[i] * 100))
            self._glow_i_sliders[i].blockSignals(False)
            self._glow_i_vals[i].setText(f"{glows[i]:.2f}")
        self._sync_glow_visibility()
        self.sphere.update()

    def _sync_glow_visibility(self):
        """按当前灯数显示/隐藏各灯光晕滑块。"""
        cnt = self.sl_cnt.value()
        for i in range(4):
            vis = i < cnt
            self._glow_i_lbls[i].setVisible(vis)
            self._glow_i_sliders[i].setVisible(vis)
            self._glow_i_vals[i].setVisible(vis)

    def _apply(self):
        if self.glw is None:
            return
        self.glw.set_light_count(self.sl_cnt.value())
        self._cnt_lbl.setText(str(self.sl_cnt.value()))
        self.glw.adjust_light_azimuth(self.sl_az.value())
        self.glw.adjust_light_elevation(self.sl_el.value())
        if self.sender() is self.sl_glow:
            # 整体光晕 → 全部灯统一
            glow = self.sl_glow.value() / 100.0
            self.glw.set_light_glow(glow)
            self._glow_lbl.setText(f"{glow:.2f}")
            for i in range(4):
                self._glow_i_sliders[i].blockSignals(True)
                self._glow_i_sliders[i].setValue(int(glow * 100))
                self._glow_i_sliders[i].blockSignals(False)
                self._glow_i_vals[i].setText(f"{glow:.2f}")
        elif self.sender() in self._glow_i_sliders:
            # 各灯独立光晕（仅由某盏灯自己的滑块触发；数量/方位/俯仰滑块
            # 变化不应重写每灯光晕）
            n = max(1, min(4, self.sl_cnt.value()))
            vals = []
            for i in range(4):
                v = self._glow_i_sliders[i].value() / 100.0
                self.glw.set_light_glow_i(i, v)
                self._glow_i_vals[i].setText(f"{v:.2f}")
                if i < n:
                    vals.append(v)
            # 仅统计当前生效的灯（灯数之外隐藏的滑块不参与联动判定）
            if vals and len(set(round(x, 2) for x in vals)) == 1:
                self.sl_glow.blockSignals(True)
                self.sl_glow.setValue(int(vals[0] * 100))
                self.sl_glow.blockSignals(False)
                self._glow_lbl.setText(f"{vals[0]:.2f}")
        self._sync_glow_visibility()
        self.sphere.update()

    def _on_sphere_dirs_changed(self):
        """手动拖拽摆放光点后：方位/俯仰滑块归零（手动摆放优先于整体旋转）。"""
        self.sl_az.blockSignals(True)
        self.sl_az.setValue(0)
        self.sl_az.blockSignals(False)
        self.sl_el.blockSignals(True)
        self.sl_el.setValue(0)
        self.sl_el.blockSignals(False)

    def _reset(self):
        if self.glw is not None:
            self.glw.reset_light_config()
        self.sync_from_glw()


class LimitedPopupComboBox(QComboBox):
    """下拉弹出窗口限高、且严格贴合选框的 QComboBox。

    与原生 QComboBox 相比解决了两个问题：

    1. **限高**：条目过多时弹出窗口最多 ``max_popup_height`` 像素高，其余
       靠滚动条浏览；条目不足时保持内容高度，不在下方拖出一片空白。
    2. **贴合选框**：Qt 是在 ``showPopup()`` 内部按「弹出窗口当时的高度」
       把它对齐到选框下沿的。因此若在 ``super().showPopup()`` 之后再改
       尺寸，Qt **不会**重新定位——向上弹出时高度一缩小，弹出窗口底边与
       选框顶边之间就会裂开一条缝；高度被撑大时则反过来压住选框。所以
       必须在改完尺寸后按**最终高度**重新对齐一次（上下方向也一并自行
       判断，详见 :meth:`_popup_pos`）。

    参数:
        max_popup_height: 弹出窗口最大高度（像素）。
        max_visible_items: >0 时同时设置一次可见条目数。
        scroll_bar_always_on: True 时垂直滚动条常显（条目很多时更直观）。
    """

    def __init__(self, max_popup_height=220, max_visible_items=0,
                 scroll_bar_always_on=False, parent=None):
        super().__init__(parent)
        self._popup_height = int(max_popup_height)
        view = QListView(self)
        view.setUniformItemSizes(True)
        view.setVerticalScrollBarPolicy(
            Qt.ScrollBarAlwaysOn if scroll_bar_always_on
            else Qt.ScrollBarAsNeeded)  # type: ignore[attr-defined]
        view.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff)  # type: ignore[attr-defined]
        self.setView(view)
        if max_visible_items:
            self.setMaxVisibleItems(int(max_visible_items))

    def showPopup(self):
        super().showPopup()
        popup = self.view().window()      # QComboBoxPrivateContainer

        # 尺寸：矮内容贴合内容高度，高内容限高滚动。
        h = min(popup.height(), self._popup_height)
        # 宽度至少等于选框宽度：Qt 默认会把弹出收缩到内容文字宽度，
        # 导致弹出列表比选框窄、看起来错位。
        w = max(popup.width(), self.width())

        anchor = self.mapToGlobal(self.rect().topLeft())
        x, y = self._popup_pos(anchor, w, h)
        popup.setGeometry(x, y, w, h)

    def _popup_pos(self, anchor, w, h):
        """按最终尺寸算出弹出窗口左上角坐标，使其紧贴选框边缘。

        优先向下弹（顶边贴选框底边）；下方放不下则向上弹（底边贴选框
        顶边）；两边都放不下时贴住空间较大的一侧并钳进可用区域。

        这里不沿用 Qt 的上下判断：实测短列表在贴近屏幕底部时，Qt 会把
        弹出窗口放在选框下方并溢出屏幕外，再简单钳制回来就会压住选框。
        """
        x = anchor.x()
        y = anchor.y() + self.height()          # 向下弹：顶边贴选框底边
        avail = self._available_geometry(anchor)
        if avail is None:
            return x, y

        if y + h > avail.bottom():              # 下方放不下
            upward = anchor.y() - h             # 向上弹：底边贴选框顶边
            if upward >= avail.top():
                y = upward
            elif (avail.bottom() - y) >= (anchor.y() - avail.top()):
                y = max(avail.top(), avail.bottom() - h)
            else:
                y = avail.top()

        # 水平方向同样钳进屏幕，避免多屏/贴右边界时越界
        x = max(avail.left(), min(x, avail.right() - w))
        return x, y

    @staticmethod
    def _available_geometry(pos):
        """取 pos 所在屏幕的可用区域（不含任务栏）；取不到时返回 None。"""
        try:
            scr = QApplication.screenAt(pos) or QApplication.primaryScreen()
            return scr.availableGeometry() if scr is not None else None
        except Exception:
            return None


# 旧名保留，便于既有代码/外部脚本继续引用
_LimitedStyleCombo = LimitedPopupComboBox


# 画布区配色 —— 与 theme.LIGHT_QSS 浅色科技风保持一致。
# 只补充 LIGHT_QSS 中没有覆盖到的部分（工具条容器、GL 外框、状态栏），
# 其余控件（QPushButton / QComboBox / QSlider ...）直接继承全局主题，
# 这样主题一改，画布自动跟随。
_CANVAS_QSS = """
QWidget#CubCanvasRoot {
    background-color: #E4EAF2;
}

/* 顶部工具条：白底 + 底部细分隔线，呼应 QGroupBox 的白色卡片 */
QWidget#CubToolBar {
    background-color: #FFFFFF;
    border-bottom: 1px solid #CBD5E1;
}

QWidget#CubToolBar QLabel {
    color: #4A5568;
    font-size: 9pt;
    padding: 0px 2px;
}

/* 参数区：淡灰底，和主窗口背景同色系 */
QFrame#CubParams {
    background-color: #F5F6FA;
    border-top: 1px solid #CBD5E1;
}

/* 状态栏文字 */
QLabel#CubStatus {
    color: #5C6BC0;
    font-size: 8.5pt;
    background-color: #EEF2FF;
    border-top: 1px solid #C5CAE9;
    padding: 4px 10px;
}

/* 工具条上的小按钮，压扁一点以免占高 */
QWidget#CubToolBar QPushButton,
QWidget#CubToolBar QToolButton {
    padding: 5px 12px;
    font-size: 9pt;
}

QToolButton {
    background-color: #F8FAFE;
    border: 1px solid #CBD5E1;
    border-radius: 5px;
    color: #2C3E50;
    font-weight: bold;
}

QToolButton:hover {
    background-color: #E3F2FD;
    border: 1px solid #1E88E5;
    color: #1565C0;
}

QToolButton:checked {
    background-color: #BBDEFB;
    border: 1px solid #1565C0;
    color: #0D47A1;
}

/* 参数区里的分组框收紧内边距，避免左侧面板太挤
   （标题已移到折叠按钮，margin-top 保持小值避免留空） */
QFrame#CubParams QGroupBox {
    margin-top: 6px;
    padding: 10px 10px 8px 10px;
}

/* GL 画布容器：背景白；圆角形状由 setMask 提供 */
QFrame#CubCanvasFrame {
    background: #FFFFFF;
}

/* 一键样式 + 分子显示：外层圆角矩形卡片（浅色渐变 + 细边框 + 投影） */
QWidget#CubStyleWrap {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #FFFFFF, stop:1 #F1F5FB);
    border: 1px solid #D5DEE9;
    border-radius: 12px;
}

/* 一键样式 + 分子显示：圆角卡片，浅色渐变底纹 + 细边框 */
QWidget#CubStyleBar {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #FFFFFF, stop:1 #F1F5FB);
    border: 1px solid #D5DEE9;
    border-radius: 10px;
}

QWidget#CubStyleBar QLabel {
    color: #4A5568;
    font-size: 9pt;
    padding: 0px 2px;
}

QWidget#CubStyleBar QPushButton {
    padding: 5px 12px;
    font-size: 9pt;
}
"""


class CubCanvasPanel(QWidget):
    """可嵌入主窗口的 cube 画布。

    信号:
        statusChanged(str)  渲染/加载状态文本，方便主窗口写进日志或状态栏。
    """

    statusChanged = pyqtSignal(str)
    paramsChanged = pyqtSignal()   # 参数区某个折叠组展开/收起时发出（主窗口据此对齐底部横带）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CubCanvasRoot")
        self.setStyleSheet(_CANVAS_QSS)
        self.setAcceptDrops(True)

        # i18n：登记 (widget, 中文原文, 方法名)，切语言时逐个刷新
        self._cv_reg = []
        self._gl_ok = _ensure_pyopengl()
        self._cube_paths = []
        self._loaded_path = None
        # 「同步到VMD」回调（由主窗口注入；None=画布独立使用时无动作）
        self.on_sync_vmd = None
        # 「清空样式」回调（由主窗口注入联动各分析面板；None=仅清画布）
        self.on_clear_analysis = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        if not self._gl_ok:
            tip = QLabel(_cv("未安装 PyOpenGL，画布不可用。\n"
                             "请运行: pip install PyOpenGL PyOpenGL-accelerate"))
            tip.setAlignment(Qt.AlignCenter)
            tip.setStyleSheet("color:#94A3B8; font-size:10pt; background:#F5F6FA;")
            root.addWidget(tip)
            self.glw = None
            return

        root.addWidget(self._build_toolbar())

        # GL 画布：包进圆角矩形容器（CubCanvasFrame）。
        # 圆角通过对「容器 frame」做 setMask 实现（而非对 glw 做 mask）。
        # 关键：mask 只裁掉 frame 窗口形状，内部 glw（native 子窗口）在矩形
        # 区域内仍可正常接收鼠标事件，因此拖动旋转不受影响。
        self._canvas_frame = QFrame(self)
        self._canvas_frame.setObjectName("CubCanvasFrame")
        self._canvas_frame.setFrameShape(QFrame.NoFrame)
        cf_lay = QVBoxLayout(self._canvas_frame)
        cf_lay.setContentsMargins(0, 0, 0, 0)
        cf_lay.setSpacing(0)

        self.glw = CubGLWidget(self._canvas_frame)
        self.glw.set_status_callback(self._set_status)
        # vdW 片段集合变化（框选/点选归入、清除）→ 自动回填片段输入框
        self.glw.add_vdw_fragment_changed_cb(self._on_vdw_frag_set_changed)
        self.glw.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.glw.setMinimumSize(320, 240)
        self.glw.setStyleSheet("border: none; background: transparent;")
        cf_lay.addWidget(self.glw, stretch=1)

        # 容器尺寸变化时同步圆角遮罩
        self._canvas_frame.resizeEvent = self._on_canvas_frame_resize

        root.addWidget(self._canvas_frame, stretch=1)

        # 首次布局完成后应用圆角遮罩（确保初始即圆角）
        QTimer.singleShot(0, self._apply_canvas_mask)

        # 一键样式 + 分子显示：圆角矩形卡片（置于画布正下方）
        self._style_wrap = QWidget()
        self._style_wrap.setObjectName("CubStyleWrap")
        sw = QHBoxLayout(self._style_wrap)
        sw.setContentsMargins(10, 8, 10, 8)
        sw.setSpacing(0)
        sw.addWidget(self._build_style_bar())
        root.addWidget(self._style_wrap)

        # 圆角矩形投影
        _sw_shadow = QGraphicsDropShadowEffect(self._style_wrap)
        _sw_shadow.setBlurRadius(12)
        _sw_shadow.setOffset(0, 2)
        _sw_shadow.setColor(QColor(15, 23, 42, 40))
        self._style_wrap.setGraphicsEffect(_sw_shadow)

        self._params = self._build_params()
        self._params.setVisible(True)
        root.addWidget(self._params)

        self._status_lbl = QLabel("渲染器初始化中…")
        self._status_lbl.setObjectName("CubStatus")
        self._status_lbl.hide()
        root.addWidget(self._status_lbl)

    def _apply_canvas_mask(self):
        """对画布容器做圆角遮罩（裁掉四角；内部 glw 仍可正常接收鼠标）。"""
        r = self._canvas_frame.contentsRect()
        radius = 14
        path = QPainterPath()
        path.addRoundedRect(QRectF(r), radius, radius)
        region = QRegion(path.toFillPolygon().toPolygon())
        self._canvas_frame.setMask(region)

    def _on_canvas_frame_resize(self, event):
        """容器尺寸变化时同步圆角遮罩。"""
        QFrame.resizeEvent(self._canvas_frame, event)
        self._apply_canvas_mask()

    # ── UI 构建 ────────────────────────────────────────────────
    # ── i18n ──
    def _cv_bind(self, widget, text, method="setText"):
        """登记控件文本（中文原文），切语言时按 _CV_EN 刷新并返回译文。"""
        self._cv_reg.append((widget, text, method))
        return _cv(text)

    def set_lang(self, lang):
        """主窗口切换语言时调用（i18n._CURRENT_LANG 已更新）。"""
        self._apply_lang()

    def _apply_lang(self):
        for w, text, method in self._cv_reg:
            try:
                getattr(w, method)(_cv(text))
            except RuntimeError:
                pass   # 控件已被销毁
        # 选中标记下拉：整体重填并保持选中项
        if getattr(self, "_sel_marker_cb", None) is not None:
            idx = self._sel_marker_cb.currentIndex()
            self._sel_marker_cb.blockSignals(True)
            self._sel_marker_cb.clear()
            self._sel_marker_cb.addItems(
                [_cv(t) for t in ("二十面体", "透明球", "圆环", "光晕")])
            self._sel_marker_cb.setCurrentIndex(idx)
            self._sel_marker_cb.blockSignals(False)
        # 网格精度下拉
        if getattr(self, "_grid_quality_cb", None) is not None:
            idx = self._grid_quality_cb.currentIndex()
            self._grid_quality_cb.blockSignals(True)
            self._grid_quality_cb.clear()
            self._grid_quality_cb.addItems(
                [_cv(t) for t in ("低 (1)", "中 (2)", "高 (3)")])
            self._grid_quality_cb.setCurrentIndex(idx)
            self._grid_quality_cb.blockSignals(False)
        # 相位配色方案下拉
        if getattr(self, "_phase_scheme_cmb", None) is not None:
            idx = self._phase_scheme_cmb.currentIndex()
            self._phase_scheme_cmb.blockSignals(True)
            self._phase_scheme_cmb.clear()
            self._phase_scheme_cmb.addItems(
                [_cv(t) for t in ("相近色 (±25°)", "同色相·不同饱和",
                                  "互补色 (180°)")])
            self._phase_scheme_cmb.setCurrentIndex(idx)
            self._phase_scheme_cmb.blockSignals(False)
        # 深度剥离层数后缀
        if getattr(self, "_dp_layers_spin", None) is not None:
            self._dp_layers_spin.setSuffix(_cv(" 层"))
        # 光照下拉（_on_lighting 按 index 取值，重填安全）
        if getattr(self, "_light_cb", None) is not None:
            idx = self._light_cb.currentIndex()
            self._light_cb.blockSignals(True)
            self._light_cb.clear()
            self._light_cb.addItems(
                [_cv(name) for name, _ in _LIGHTING_OPTIONS])
            self._light_cb.setCurrentIndex(idx)
            self._light_cb.blockSignals(False)
        # 原子配色下拉（_on_mol_style 按 index 取值，重填安全）
        if getattr(self, "_mol_style_cb", None) is not None:
            idx = self._mol_style_cb.currentIndex()
            self._mol_style_cb.blockSignals(True)
            self._mol_style_cb.clear()
            self._mol_style_cb.addItems([_cv(t) for t in MOL_STYLE_DISPLAY])
            self._mol_style_cb.setCurrentIndex(idx)
            self._mol_style_cb.blockSignals(False)
        # 折叠组标题（▸/▾ 状态保留）
        for btn, title in getattr(self, "_fold_titles", []):
            sym = "▾" if btn.isChecked() else "▸"
            btn.setText(f"{sym} {_cv(title)}")
        # 「参数 ▴/▾」折叠按钮
        if getattr(self, "_more_btn", None) is not None:
            sym = "▴" if self._more_btn.isChecked() else "▾"
            self._more_btn.setText(f"{_cv('参数')} {sym}")

    def _build_toolbar(self):
        bar = QWidget()
        bar.setObjectName("CubToolBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(6, 4, 6, 4)
        h.setSpacing(6)

        # 轨道 cube 下拉框与"打开…"按钮已移除：轨道预览由双击轨道表格自动触发。
        # 内部仍维护 _cube_paths / _loaded_path，供 load_cube 正常渲染。
        # 风格/分子/光泽/重置视角已移到画布下方参数区「显示」组（_build_params）。

        h.addStretch()
        self._more_btn = QToolButton()
        self._more_btn.setText(f"{_cv('参数')} ▴")
        self._more_btn.setCheckable(True)
        self._more_btn.setChecked(True)
        self._more_btn.setToolTip("展开等值面 / 显示 / 球棍 / 导出参数")
        self._more_btn.toggled.connect(self._on_toggle_params)
        h.addWidget(self._more_btn)

        return bar

    def _build_style_bar(self):
        """一键样式 + 分子显示：圆角卡片（画布正下方）。

        卡片观感：浅色渐变底纹 + 圆角 + 细边框 + 柔和投影。
        """
        bar = QWidget()
        bar.setObjectName("CubStyleBar")
        sh = QGraphicsDropShadowEffect(bar)
        sh.setBlurRadius(14)
        sh.setOffset(0, 2)
        sh.setColor(QColor(30, 50, 80, 40))
        bar.setGraphicsEffect(sh)
        v = QVBoxLayout(bar)
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(8)

        h = QHBoxLayout()
        h.setSpacing(6)
        self._lbl_styles = QLabel()
        self._lbl_styles.setText(self._cv_bind(self._lbl_styles, "一键样式:"))
        h.addWidget(self._lbl_styles)
        self._style_sob_btn = QPushButton("sob-art")
        self._style_sob_btn.setObjectName("SmallBtn")
        self._style_sob_btn.setToolTip("一键应用默认样式 sob-art（含手动摆放的光源方向）")
        self._style_sob_btn.clicked.connect(self._apply_sobart_style)
        h.addWidget(self._style_sob_btn)
        self._style_ibo_btn = QPushButton("IBOview")
        self._style_ibo_btn.setObjectName("SmallBtn")
        self._style_ibo_btn.setToolTip("一键回到默认 IboView 观感（CPK/三光/白底，等值面配色 ultra-glass）")
        self._style_ibo_btn.clicked.connect(self._apply_iboview_style)
        h.addWidget(self._style_ibo_btn)
        self._style_hm_btn = QPushButton("HoukMol")
        self._style_hm_btn.setObjectName("SmallBtn")
        self._style_hm_btn.setToolTip("一键应用默认样式 HoukMol（单光渐变 + 十字圆环）")
        self._style_hm_btn.clicked.connect(self._apply_houkmol_style)
        h.addWidget(self._style_hm_btn)
        self._style_iq_btn = QPushButton("IQmol")
        self._style_iq_btn.setObjectName("SmallBtn")
        self._style_iq_btn.setToolTip("一键应用默认样式 IQmol（CPK 双光 + 每灯独立光晕 + 红蓝相位 + 原子配色 GaussView）")
        self._style_iq_btn.clicked.connect(self._apply_iqmol_style)
        h.addWidget(self._style_iq_btn)
        self._clear_analysis_btn = QPushButton()
        self._clear_analysis_btn.setText(self._cv_bind(self._clear_analysis_btn, "清空样式"))
        self._clear_analysis_btn.setObjectName("SmallBtn")
        self._clear_analysis_btn.setToolTip(
            "清空画布上的等值面、临界点、极值点等全部分析效果（保留分子与渲染样式）")
        self._clear_analysis_btn.clicked.connect(self._on_clear_analysis_clicked)
        h.addWidget(self._clear_analysis_btn)
        h.addStretch()
        # 键长标注（从第二行移入第一行行尾）
        self._measure_btn = QPushButton()
        self._measure_btn.setText(self._cv_bind(self._measure_btn, "键长标注"))
        self._measure_btn.setObjectName("SmallBtn")
        self._measure_btn.setCheckable(True)
        self._measure_btn.setCursor(Qt.PointingHandCursor)
        self._measure_btn.setToolTip(
            "键长标注：开启后依次点击两个原子，键长（Å，两位小数）显示在两点"
            "连线中点；可连续标注多条。再次点击本按钮退出，标注保留。")
        self._measure_btn.toggled.connect(self._on_measure_mode)
        h.addWidget(self._measure_btn)
        self._measure_clear_btn = QPushButton()
        self._measure_clear_btn.setText(self._cv_bind(self._measure_clear_btn, "清除"))
        self._measure_clear_btn.setObjectName("SmallBtn")
        self._measure_clear_btn.setToolTip("清除全部键长标注")
        self._measure_clear_btn.clicked.connect(self._on_measure_clear)
        h.addWidget(self._measure_clear_btn)
        v.addLayout(h)

        # ── 分子显示辅助行（第二行） ──
        h2 = QHBoxLayout()
        h2.setSpacing(10)
        lbl_disp = QLabel()
        lbl_disp.setText(self._cv_bind(lbl_disp, "分子显示:"))
        h2.addWidget(lbl_disp)
        self._hide_h_chk = QCheckBox()
        self._hide_h_chk.setText(self._cv_bind(self._hide_h_chk, "隐藏氢原子"))
        self._hide_h_chk.setToolTip("隐藏所有氢原子（球体/键/标签均不显示）")
        self._hide_h_chk.toggled.connect(self._on_hide_hydrogens)
        h2.addWidget(self._hide_h_chk)
        lbl_keep = QLabel()
        lbl_keep.setText(self._cv_bind(lbl_keep, "保留H编号:"))
        h2.addWidget(lbl_keep)
        self._keep_h_edit = QLineEdit("")
        self._keep_h_edit.setPlaceholderText(
            self._cv_bind(self._keep_h_edit, "如 1,3,5-8", "setPlaceholderText"))
        self._keep_h_edit.setMaximumWidth(90)
        self._keep_h_edit.setToolTip("隐藏氢时仍显示的 H 原子编号（1-based，逗号/连字符范围）")
        self._keep_h_edit.editingFinished.connect(self._on_keep_h_edited)
        h2.addWidget(self._keep_h_edit)
        self._lbl_idx_chk = QCheckBox()
        self._lbl_idx_chk.setText(self._cv_bind(self._lbl_idx_chk, "显示原子编号"))
        self._lbl_idx_chk.setToolTip("在每个原子旁显示分子内编号（1, 2, 3 …）")
        self._lbl_idx_chk.toggled.connect(self._on_atom_label_idx)
        h2.addWidget(self._lbl_idx_chk)
        self._lbl_sym_chk = QCheckBox()
        self._lbl_sym_chk.setText(self._cv_bind(self._lbl_sym_chk, "显示元素符号"))
        self._lbl_sym_chk.setToolTip("在每个原子旁显示元素符号（H, C, N, O …）")
        self._lbl_sym_chk.toggled.connect(self._on_atom_label_sym)
        h2.addWidget(self._lbl_sym_chk)
        h2.addStretch()
        v.addLayout(h2)

        # ── 同步到 VMD + 导出图片（第三行） ──
        h3 = QHBoxLayout()
        h3.setSpacing(6)
        self._sync_vmd_btn = QPushButton()
        self._sync_vmd_btn.setText(self._cv_bind(self._sync_vmd_btn, "同步到VMD"))
        self._sync_vmd_btn.setObjectName("SmallBtn")
        self._sync_vmd_btn.setCursor(Qt.PointingHandCursor)
        self._sync_vmd_btn.setToolTip("把当前画布场景同步到 VMD，并弹出 VMD 控制台窗口")
        self._sync_vmd_btn.clicked.connect(self._on_sync_vmd_clicked)
        h3.addWidget(self._sync_vmd_btn)
        h3.addSpacing(12)
        # ── 导出图片（DPI + 透明背景） ──
        h3.addWidget(QLabel("DPI:"))
        self._dpi_edit = QLineEdit("600")
        self._dpi_edit.setValidator(QDoubleValidator(50, 2400, 0))
        self._dpi_edit.setMaximumWidth(56)
        h3.addWidget(self._dpi_edit)
        self._transparent_chk = QCheckBox()
        self._transparent_chk.setText(self._cv_bind(self._transparent_chk, "透明背景"))
        self._transparent_chk.setToolTip("导出 PNG 时背景透明（背景 alpha=0，参照 IboView）")
        h3.addWidget(self._transparent_chk)
        btn_sc = QPushButton(self._cv_bind(QPushButton(), "截图"))
        btn_sc.setObjectName("SmallBtn")
        btn_sc.clicked.connect(self._screenshot)
        h3.addWidget(btn_sc)
        btn_ex = QPushButton(self._cv_bind(QPushButton(), "导出图片"))
        btn_ex.setObjectName("SmallBtn")
        btn_ex.clicked.connect(self._export_image)
        h3.addWidget(btn_ex)
        h3.addStretch()
        v.addLayout(h3)

        return bar

    def _on_sync_vmd_clicked(self):
        """「同步到VMD」按钮：转发给主窗口注入的回调。"""
        if callable(self.on_sync_vmd):
            try:
                self.on_sync_vmd()
            except Exception:
                pass

    def _build_params(self):
        box = QFrame()
        box.setObjectName("CubParams")
        outer = QHBoxLayout(box)
        outer.setContentsMargins(6, 4, 6, 6)
        outer.setSpacing(8)

        # 当前背景色 (r,g,b,a)；默认不透明白底
        if not hasattr(self, "_bg_rgba"):
            self._bg_rgba = (1.0, 1.0, 1.0, 1.0)

        # 显示 / 等值面（原「显示」与「等值面」两组合并为一组；标题移到折叠按钮）
        #
        # 布局方式：纵向堆叠「行容器」。原先用的是 6 列 QGridLayout，各行
        # 跨越的列数不一致（3 列 / 6 列混用），且标签列宽取决于该列最长的
        # 文案，导致各行控件的左边缘和行宽都对不齐（实测行宽有 434 与 638
        # 两种，「呼吸」复选框比它的标签低 7px）。改成「每行一个 HBox +
        # 行首标签统一宽度」后，各行左右边缘自然对齐成两条直线。
        gi = QGroupBox("")
        gl = QVBoxLayout(gi)
        gl.setContentsMargins(8, 6, 8, 6)
        gl.setSpacing(8)

        # 行首标签统一宽度，保证各行控件左边缘成一条线。
        # 取最长标签「等值面大小:」的实测宽度，短标签靠右对齐补空。
        LBL_W = 110

        def _lbl(text, tip=None):
            """行首标签：等宽、右对齐。"""
            lb = QLabel(_cv(text))
            self._cv_reg.append((lb, text, "setText"))
            lb.setMinimumWidth(LBL_W)
            lb.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if tip:
                lb.setToolTip(tip)
            return lb

        def _slbl(text, tip=None):
            """行内次要标签：不占固定宽度，紧贴所修饰的控件。"""
            lb = QLabel(_cv(text))
            self._cv_reg.append((lb, text, "setText"))
            lb.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if tip:
                lb.setToolTip(tip)
            return lb

        def _row(*items):
            """生成一行。元素可以是：

            * 控件 —— 按自身 sizeHint 排布；
            * ``(控件, stretch)`` —— 参与拉伸，同行多个拉伸控件按因子平分
              剩余宽度（用于让并排的下拉框等宽、右边缘对齐）；
            * ``None`` —— 弹性空白，把后面的控件推到行尾；
            * ``int`` —— 固定间距（像素）。
            """
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)
            for it in items:
                if it is None:
                    h.addStretch(1)
                elif isinstance(it, int):
                    h.addSpacing(it)
                elif isinstance(it, tuple):
                    h.addWidget(it[0], it[1])
                else:
                    h.addWidget(it)
            return w

        # ── 第 1 行：等值面配色 ──
        self._style_cb = LimitedPopupComboBox(max_popup_height=220)
        self._style_cb.addItems(STYLE_DISPLAY)
        self._style_cb.setMinimumWidth(170)

        self._light_cb = LimitedPopupComboBox(max_popup_height=220)
        self._light_cb.addItems(
            [_cv(name) for name, _ in _LIGHTING_OPTIONS])
        self._light_cb.setMinimumWidth(140)
        self._light_cb.setToolTip(
            "光照/渲染效果（独立于原子配色）：IboView 三光 / MolViewer 单光 / 双光 / 四光")

        # ── 第 3 行：原子配色 ──
        self._mol_style_cb = LimitedPopupComboBox(max_popup_height=200)
        self._mol_style_cb.addItems([_cv(t) for t in MOL_STYLE_DISPLAY])
        self._mol_style_cb.setMinimumWidth(120)
        self._mol_style_cb.setToolTip("原子按元素配色方案（独立于光照），只改颜色不改材质")

        self._shiny_cb = QComboBox()
        self._shiny_cb.addItems(list(SHININESS_PRESETS.keys()))
        self._shiny_cb.setMinimumWidth(120)
        self._shiny_cb.setCurrentText(SHININESS_DEFAULT)
        self._shiny_cb.setToolTip("IboView 光泽预设：调节原子与等值面的 Phong 高光")

        # ── 第 5 行：选中标记 ──
        self._sel_marker_cb = QComboBox()
        self._sel_marker_cb.addItems(
            [_cv(t) for t in ("二十面体", "透明球", "圆环", "光晕")])
        self._sel_marker_cb.setToolTip("选中原子时的标记形状：二十面体 / 透明球 / 圆环 / 光晕")

        self._sel_pulse_chk = QCheckBox()
        self._sel_pulse_chk.setToolTip("选中标记半径 ±12% 正弦呼吸动画")
        self._sel_pulse_chk.toggled.connect(self._on_sel_pulse)

        self._btn_reset_view = QPushButton(
            self._cv_bind(QPushButton(), "重置视角"))
        self._btn_reset_view.setObjectName("SmallBtn")
        self._btn_reset_view.setToolTip("重置相机视角（居中并铺满分子/等值面）")
        self._btn_reset_view.clicked.connect(self._reset_view)

        # 每个下拉独占一行、占满整行宽度，避免文案被压缩截断
        gl.addWidget(_row(_lbl("等值面配色:"), (self._style_cb, 1)))
        # ── 第 2 行：光照 ──
        gl.addWidget(_row(_lbl("光照:"), (self._light_cb, 1)))
        # ── 第 3 行：原子配色 ──
        self._btn_elem_color = QPushButton(
            self._cv_bind(QPushButton(), "元素颜色…"))
        self._btn_elem_color.setObjectName("SmallBtn")
        self._btn_elem_color.setToolTip("自定义每种元素的原子颜色（覆盖默认 CPK 配色）")
        self._btn_elem_color.clicked.connect(self._open_element_color_dialog)
        gl.addWidget(_row(_lbl("原子配色:"), (self._mol_style_cb, 1),
                          self._btn_elem_color))
        # ── 第 4 行：光泽 ──
        gl.addWidget(_row(_lbl("光泽:"), (self._shiny_cb, 1)))
        # ── 第 5 行：选中标记（下拉占满整行）──
        gl.addWidget(_row(_lbl("选中标记:"), (self._sel_marker_cb, 1)))
        # ── 第 6 行：呼吸 / 重置视角（按钮留足宽度）──
        gl.addWidget(_row(_lbl("呼吸:"), self._sel_pulse_chk, None,
                          self._btn_reset_view))

        # 先创建全部控件再连接信号，避免初始化 addItems 触发回调时
        # 访问尚未创建的控件（如 _on_style 会读取 _mol_style_cb）
        self._style_cb.currentIndexChanged.connect(self._on_style)
        self._light_cb.currentIndexChanged.connect(self._on_lighting)
        self._mol_style_cb.currentIndexChanged.connect(self._on_mol_style)
        self._shiny_cb.currentIndexChanged.connect(self._on_shiny)
        self._sel_marker_cb.currentIndexChanged.connect(self._on_sel_marker)
        # 初始应用一次默认（ultra-glass / IboView 三光 / CPK / reasonably shiny）
        self._on_style(self._style_cb.currentIndex())
        self._on_lighting(self._light_cb.currentIndex())
        self._on_mol_style(self._mol_style_cb.currentIndex())
        self._on_shiny(self._shiny_cb.currentIndex())
        self._on_sel_marker(self._sel_marker_cb.currentIndex())

        # ── IboView 相对阈值：界面不展示，但逻辑与实例都保留 ──
        # 这几个控件不加入任何布局，只挂到 gi 上作为父对象（否则没有 parent
        # 的控件会变成游离的顶层窗口）。此前是先进布局再 hide()，白占着网格
        # 行号、让行序难以阅读；现在行号与可见行一一对应。
        self._rel_chk = QCheckBox(
            f"IboView 相对阈值 ({IBOVIEW_DEFAULTS['IsoThreshold']:.0f}%)", gi)
        self._rel_chk.setToolTip(
            "勾选后按 IboView IsoThreshold 语义取等值面：\n"
            "选取使 |data| 累积权重达到指定百分比的等值面。\n"
            "取消勾选则使用下方的绝对 isovalue（cube 文件原始单位）。")
        self._rel_chk.toggled.connect(self._on_rel_mode)
        self._rel_chk.hide()

        self._rel_pct_lbl = QLabel("百分比:", gi)
        self._rel_pct_lbl.hide()

        self._rel_sld = QSlider(Qt.Horizontal, gi)
        self._rel_sld.setRange(50, 99)
        self._rel_sld.setValue(int(IBOVIEW_DEFAULTS['IsoThreshold']))
        self._rel_sld.setEnabled(False)
        self._rel_sld.valueChanged.connect(self._on_rel_slider)
        self._rel_sld.hide()

        self._rel_lbl = QLabel(f"{IBOVIEW_DEFAULTS['IsoThreshold']:.0f}%", gi)
        self._rel_lbl.setMinimumWidth(44)
        self._rel_lbl.hide()

        # ── 第 7 行：等值面大小（滑块 + 数值输入框）──
        self._iso_sld = QSlider(Qt.Horizontal)
        self._iso_sld.setRange(1, 2000)         # iso = 值/1000（0.001..2.0，含 IGMH 的 0.004 与 IRI 的 1.0）
        self._iso_sld.setValue(50)
        self._iso_sld.setMinimumWidth(200)
        self._iso_sld.valueChanged.connect(self._on_iso_slider)
        self._iso_edit = QLineEdit("0.050")
        self._iso_edit.setValidator(QDoubleValidator(0.001, 2.0, 4))
        self._iso_edit.setMaximumWidth(64)
        self._iso_edit.editingFinished.connect(self._on_iso_edit)

        # ── 第 8 行：透明度（滑块 + 精确输入框，与等值面行上下对齐）──
        self._op_sld = QSlider(Qt.Horizontal)
        self._op_sld.setRange(0, 100)
        # 滑块值直接表示“透明度(%)”，与 opacity 互补：opacity = 1 - 值/100
        self._op_sld.setValue(int((1.0 - IBOVIEW_DEFAULTS['OrbitalOpacity']) * 100))
        self._op_sld.setMinimumWidth(200)
        self._op_sld.valueChanged.connect(self._on_op)
        self._op_edit = QLineEdit("20")
        self._op_edit.setValidator(QIntValidator(0, 100))
        self._op_edit.setMaximumWidth(64)
        self._op_edit.setToolTip("透明度 0-100%（精确输入）")
        self._op_edit.editingFinished.connect(self._on_op_edit)

        gl.addWidget(_row(_lbl("等值面大小:"), (self._iso_sld, 1),
                          self._iso_edit))
        gl.addWidget(_row(_lbl("透明度:"), (self._op_sld, 1),
                          self._op_edit))

        self._dp_chk = QCheckBox("Depth peeling")
        self._dp_chk.setChecked(True)
        self._dp_chk.setToolTip(
            "深度剥离：逐像素按深度分层渲染透明等值面（顺序正确）；"
            "关闭后回退到按 chunk 排序的 alpha 混合（无层数限制但有破洞风险）")
        self._dp_chk.toggled.connect(self._on_dp_toggle)
        self._dp_layers_spin = QSpinBox()
        self._dp_layers_spin.setRange(0, 8)
        self._dp_layers_spin.setValue(int(IBOVIEW_DEFAULTS['DepthPeelingLayers']))
        self._dp_layers_spin.setSuffix(" 层")
        self._dp_layers_spin.setToolTip(
            "深度剥离层数：0 = 关闭；层数越多，复杂轨道（折叠/交叠的等值面）"
            "显示越完整，代价是每层多一遍渲染、速度变慢")
        self._dp_layers_spin.valueChanged.connect(self._on_dp_layers)

        # ── 第 9 行：Depth peeling / 网格精度 ──
        self._grid_quality_cb = QComboBox()
        self._grid_quality_cb.addItems(
            [_cv(t) for t in ("低 (1)", "中 (2)", "高 (3)")])
        self._grid_quality_cb.setCurrentIndex(1)
        self._grid_quality_cb.setToolTip("生成轨道 cube 的网格密度：1=稀疏，2=中等，3=精细")
        self._grid_quality_cb.setMaximumWidth(110)

        # ── 第 10 行：等值面剪影描边（独立开关 + 粗细滑块；
        #    MolViewer 带 rim 的预设会自动勾选）──
        self._orb_outline_chk = QCheckBox()
        self._orb_outline_chk.setText(self._cv_bind(self._orb_outline_chk, "等值面描边"))
        self._orb_outline_chk.setToolTip(
            "在等值面剪影边缘叠加细描边（颜色由 MolViewer 预设或默认深色决定）")
        self._orb_outline_chk.toggled.connect(self._on_orb_outline)
        self._orb_outline_lbl = QLabel()
        self._orb_outline_lbl.setText(self._cv_bind(self._orb_outline_lbl, "粗细:"))
        self._orb_outline_sld = QSlider(Qt.Horizontal)
        self._orb_outline_sld.setRange(1, 99)          # 0.01 .. 0.99（glw 侧 clamp 上限）
        self._orb_outline_sld.setValue(8)              # 默认 0.08
        self._orb_outline_sld.setMaximumWidth(220)
        self._orb_outline_sld.valueChanged.connect(self._on_orb_outline_width)
        self._orb_outline_val = QLabel("0.08")
        self._orb_outline_val.setMinimumWidth(34)
        # 描边颜色（默认黑色），按钮色块显示当前颜色
        self._orb_outline_color = (0.0, 0.0, 0.0)
        # 描边颜色：无文字色块，与相位行色块同款圆角矩形
        self._orb_outline_color_btn = QPushButton()
        self._orb_outline_color_btn.setObjectName("SmallBtn")
        self._orb_outline_color_btn.setFixedSize(26, 26)
        self._orb_outline_color_btn.setToolTip("设置等值面描边颜色（默认黑色）")
        self._orb_outline_color_btn.clicked.connect(self._on_orb_outline_color)
        self._style_swatch(self._orb_outline_color_btn, self._orb_outline_color)

        gl.addWidget(_row(self._dp_chk, _slbl("层数:"), self._dp_layers_spin, 16,
                          _lbl("网格精度:"), (self._grid_quality_cb, 1)))
        # 描边行：紧凑排列，去掉行尾弹性空白（色块变小，无需推右对齐）
        gl.addWidget(_row(self._orb_outline_chk, _slbl("粗细:"),
                          self._orb_outline_sld, self._orb_outline_val,
                          _slbl("描边颜色:"), self._orb_outline_color_btn))

        # ── 第 11 行：色轮 / 重置 / 启用色轮配色 ──
        # 相位配色方案另起一行（见下），本行只留色轮、重置、启用勾选，
        # 弹性空白把勾选推到行尾，不再挤占文字空间。
        self._color_wheel = ColorWheelWidget(size=84)
        self._color_wheel.setToolTip("拖动旋转色轮：转一圈循环改变等值面配色")
        self._color_wheel.hueChanged.connect(self._on_wheel_hue)

        self._wheel_btn = QPushButton()
        self._wheel_btn.setText(self._cv_bind(self._wheel_btn, "重置"))
        self._wheel_btn.setObjectName("SmallBtn")
        self._wheel_btn.setMaximumWidth(54)
        self._wheel_btn.setToolTip("恢复样式默认配色")
        self._wheel_btn.clicked.connect(self._on_wheel_reset)

        # 启用色轮：默认关闭，避免覆盖样式（style）里的正/负相位配色
        self._wheel_enabled = False
        self._wheel_en_chk = QCheckBox()
        self._wheel_en_chk.setText(self._cv_bind(self._wheel_en_chk, "启用色轮配色"))
        self._wheel_en_chk.setToolTip("勾选后由色轮控制正/负相位颜色；否则沿用样式默认配色")
        self._wheel_en_chk.toggled.connect(self._on_wheel_toggle)
        self._color_wheel.setEnabled(False)

        # 相位配色方案（移植自 IboView 全套）：
        #   0 相近色（scheme0）：正/负相位 = Hue ± 25°，S=0.6 V=1.0（IboView 默认）
        #   1 同色相·不同饱和（scheme1）：正 S=0.6，负 S=0.35，同 Hue
        #   2 互补色（scheme2）：负相位 = Hue + 180°
        self._phase_scheme_cmb = QComboBox()
        self._phase_scheme_cmb.setObjectName("SmallCombo")
        self._phase_scheme_cmb.addItems(
            [_cv(t) for t in ("相近色 (±25°)", "同色相·不同饱和",
                              "互补色 (180°)")])
        self._phase_scheme_cmb.setCurrentIndex(2)  # 默认互补色，保持原行为
        self._phase_scheme_cmb.setToolTip(
            "选择等值面正/负相位配色方案（移植自 IboView）")
        self._phase_scheme_cmb.currentIndexChanged.connect(self._on_phase_scheme_changed)
        self._phase_scheme = self._phase_scheme_cmb.currentIndex()

        # ── 第 13 行：翻转相位 + 正/负相位色块选色 ──
        self._phase_flipped = False
        self._flip_phase_btn = QPushButton()
        self._flip_phase_btn.setText(self._cv_bind(self._flip_phase_btn, "翻转相位"))
        self._flip_phase_btn.setObjectName("SmallBtn")
        self._flip_phase_btn.setToolTip("交换正/负相位颜色（等价 IboView 翻转相位，几何不变）")
        self._flip_phase_btn.clicked.connect(self._on_flip_phase)

        # 正/负相位选色按钮：去掉「色块」文字，固定为圆形色块
        self._phase_pos_btn = QPushButton()
        self._phase_pos_btn.setObjectName("SmallBtn")
        self._phase_pos_btn.setFixedSize(26, 26)
        self._phase_pos_btn.setToolTip("点击选择正相位等值面颜色")
        self._phase_pos_btn.clicked.connect(lambda: self._on_pick_phase_color("pos"))
        self._phase_neg_btn = QPushButton()
        self._phase_neg_btn.setObjectName("SmallBtn")
        self._phase_neg_btn.setFixedSize(26, 26)
        self._phase_neg_btn.setToolTip("点击选择负相位等值面颜色")
        self._phase_neg_btn.clicked.connect(lambda: self._on_pick_phase_color("neg"))

        # ── 第 14 行：灯光（光源控制面板）──
        self._light_btn = QPushButton()
        self._light_btn.setText(self._cv_bind(self._light_btn, "光源设置…"))
        self._light_btn.setObjectName("SmallBtn")
        # 最小宽度保证「光源设置…」完整显示，不被行布局压缩成省略号
        # （9pt 下文字宽约 85px + 左右 padding 24 + 边框 2 ≈ 111，留 25px 余量）
        self._light_btn.setMinimumWidth(136)
        self._light_btn.setToolTip(
            "弹出光源控制面板：左侧球体实时预览光点，右侧调整数量/方向/光晕")
        self._light_btn.clicked.connect(self._open_light_dialog)

        # 相位行用两段弹性空白把「翻转相位 / 正相位 / 负相位」均匀铺开，
        # 右边缘同样与其余各行对齐
        # 色轮行（单行布局）：启用色轮配色 + 色轮 + 相位配色下拉 + 重置
        # 下拉占中间弹性宽度，「重置」按钮固定在行尾
        gl.addWidget(_row(self._wheel_en_chk, self._color_wheel,
                          _slbl("相位配色:"), (self._phase_scheme_cmb, 1),
                          self._wheel_btn))
        # 三组（翻转相位 / 正相位 / 负相位）用等量弹性空白均匀铺开，
        # 标签用行内次要标签紧凑贴着色块，避免 110px 行首标签带来的错位
        gl.addWidget(_row(self._flip_phase_btn, None,
                          _slbl("正相位:"), self._phase_pos_btn, None,
                          _slbl("负相位:"), self._phase_neg_btn))
        self._sync_phase_swatches()
        # ── 第 14 行（续）：灯光 + 样式保存 / 载入 ──
        # （一键样式 sob-art/IBOVIEW/HoukMol 已移至画布下方常驻行）
        self._style_save_btn = QPushButton()
        self._style_save_btn.setText(self._cv_bind(self._style_save_btn, "保存…"))
        self._style_save_btn.setObjectName("SmallBtn")
        # 最小宽度保证「保存…」完整显示（留余量，与「光源设置…」视觉一致）
        self._style_save_btn.setMinimumWidth(92)
        self._style_save_btn.setToolTip("把当前样式（配色/光照/描边/透明度/相位色等）保存为 JSON 文件")
        self._style_save_btn.clicked.connect(self._save_style)
        self._style_load_btn = QPushButton()
        self._style_load_btn.setText(self._cv_bind(self._style_load_btn, "载入…"))
        self._style_load_btn.setObjectName("SmallBtn")
        # 最小宽度保证「载入…」完整显示（留余量，与「光源设置…」视觉一致）
        self._style_load_btn.setMinimumWidth(92)
        self._style_load_btn.setToolTip("从 JSON 文件载入样式并应用")
        self._style_load_btn.clicked.connect(self._load_style)

        # 「灯光」靠左、「样式」靠右，中间弹性空白分隔
        gl.addWidget(_row(_lbl("灯光:"), self._light_btn, None,
                          _lbl("样式:"), self._style_save_btn,
                          self._style_load_btn))

        # ── 折叠容器：按钮控制组展开/收起（默认收起） ──
        def _collapsible_col(title):
            col = QWidget()
            cl = QVBoxLayout(col)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(2)
            btn = QToolButton()
            btn.setText(f"▸ {title}")
            btn.setCheckable(True)
            btn.setChecked(False)
            btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                "QToolButton { border:none; color:#1565C0; font-weight:bold;"
                " text-align:left; padding:2px 4px; font-size:10pt; }"
                "QToolButton:hover { color:#0D47A1; }")
            cl.addWidget(btn)
            return col, btn, cl

        def _wire_toggle(btn, group, title):
            def _tog(on):
                group.setVisible(on)
                btn.setText(f"{'▾' if on else '▸'} {_cv(title)}")
                self.paramsChanged.emit()
            btn.toggled.connect(_tog)

        col_iso, self._btn_toggle_iso, cl_iso = _collapsible_col(
            _cv("显示 / 等值面"))
        cl_iso.addWidget(gi, 1)
        _wire_toggle(self._btn_toggle_iso, gi, "显示 / 等值面")
        self._fold_titles = [(self._btn_toggle_iso, "显示 / 等值面")]
        gi.setVisible(False)   # 默认收起
        # 横向 Ignored：忽略内容固有宽度，与球棍模型列严格等宽（各占一半）
        col_iso.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        outer.addWidget(col_iso, stretch=1)

        # 球棍模型（标题移到折叠按钮）
        gb = QGroupBox("")
        bl = QGridLayout(gb)
        bl.setContentsMargins(8, 6, 8, 6)
        bl.setSpacing(4)
        # 与等值面组一致：滑块所在列（第1列）横向拉伸
        bl.setColumnStretch(1, 1)

        self._lbl_atom_r = QLabel()
        self._lbl_atom_r.setText(self._cv_bind(self._lbl_atom_r, "原子半径:"))
        bl.addWidget(self._lbl_atom_r, 0, 0)
        self._atom_scale_sld = QSlider(Qt.Horizontal)
        self._atom_scale_sld.setRange(20, 400)
        self._atom_scale_sld.setValue(168)
        self._atom_scale_sld.setMinimumWidth(200)
        self._atom_scale_sld.valueChanged.connect(self._on_atom_scale_sld)
        bl.addWidget(self._atom_scale_sld, 0, 1)
        self._atom_scale_edit = QLineEdit("1.68")
        self._atom_scale_edit.setValidator(QDoubleValidator(0.20, 4.00, 2))
        self._atom_scale_edit.setMaximumWidth(64)
        self._atom_scale_edit.editingFinished.connect(self._on_atom_scale_edit)
        bl.addWidget(self._atom_scale_edit, 0, 2)

        self._outline_color = (0.0, 0.0, 0.0)   # 默认黑边

        self._lbl_bond = QLabel()
        self._lbl_bond.setText(self._cv_bind(self._lbl_bond, "化学键:"))
        bl.addWidget(self._lbl_bond, 1, 0)
        self._bond_scale_sld = QSlider(Qt.Horizontal)
        self._bond_scale_sld.setRange(20, 400)
        self._bond_scale_sld.setValue(200)
        self._bond_scale_sld.setMinimumWidth(200)
        self._bond_scale_sld.valueChanged.connect(self._on_bond_scale_sld)
        bl.addWidget(self._bond_scale_sld, 1, 1)
        self._bond_scale_edit = QLineEdit("2.00")
        self._bond_scale_edit.setValidator(QDoubleValidator(0.20, 4.00, 2))
        self._bond_scale_edit.setMaximumWidth(64)
        self._bond_scale_edit.editingFinished.connect(self._on_bond_scale_edit)
        bl.addWidget(self._bond_scale_edit, 1, 2)

        # ── 键收腰 ──
        self._lbl_thinning = QLabel()
        self._lbl_thinning.setText(self._cv_bind(self._lbl_thinning, "键收腰:"))
        bl.addWidget(self._lbl_thinning, 2, 0)
        self._thinning_sld = QSlider(Qt.Horizontal)
        self._thinning_sld.setRange(20, 100)   # 0.20 .. 1.00 (1.0 = 不收腰)
        self._thinning_sld.setValue(72)
        self._thinning_sld.setMinimumWidth(200)
        self._thinning_sld.valueChanged.connect(self._on_thinning_sld)
        bl.addWidget(self._thinning_sld, 2, 1)
        self._thinning_edit = QLineEdit("0.72")
        self._thinning_edit.setValidator(QDoubleValidator(0.20, 1.00, 2))
        self._thinning_edit.setMaximumWidth(64)
        self._thinning_edit.editingFinished.connect(self._on_thinning_edit)
        bl.addWidget(self._thinning_edit, 2, 2)

        # ── vdW 外壳子分组：把所有 vdW 相关控件集中、整齐排列（放网格下方） ──
        vdw_grp = QGroupBox(_cv("vdW 外壳"))
        vl = QGridLayout(vdw_grp)
        vl.setContentsMargins(8, 6, 8, 6)
        vl.setSpacing(4)
        vl.setColumnStretch(1, 1)

        # 开关行（四个复选框一行）
        self._vdw_mode_chk = QCheckBox()
        self._vdw_mode_chk.setText(self._cv_bind(self._vdw_mode_chk, "范德华半径"))
        self._vdw_mode_chk.setToolTip(
            "开启后原子直接以范德华半径（Bondi 1964 表）显示，而非默认绘制半径")
        self._vdw_mode_chk.stateChanged.connect(self._on_vdw_mode)
        vl.addWidget(self._vdw_mode_chk, 0, 0)

        self._vdw_shell_chk = QCheckBox()
        self._vdw_shell_chk.setText(self._cv_bind(self._vdw_shell_chk, "vdW 外壳"))
        self._vdw_shell_chk.setToolTip(
            "在正常球棍模型之上叠加半透明范德华半径球壳（元素色，体现空间包围）")
        self._vdw_shell_chk.stateChanged.connect(self._on_vdw_shell)
        vl.addWidget(self._vdw_shell_chk, 0, 1)

        self._vdw_outline_chk = QCheckBox()
        self._vdw_outline_chk.setText(self._cv_bind(self._vdw_outline_chk, "外壳描边"))
        self._vdw_outline_chk.setToolTip("vdW 球面剪影描边（独立于原子描边，单独控制）")
        self._vdw_outline_chk.stateChanged.connect(self._on_vdw_outline)
        vl.addWidget(self._vdw_outline_chk, 0, 2)

        # 「仅选中片段」子开关：外壳只覆盖框选/点选的原子片段
        self._vdw_sel_only_chk = QCheckBox()
        self._vdw_sel_only_chk.setText(self._cv_bind(self._vdw_sel_only_chk, "仅选中片段"))
        self._vdw_sel_only_chk.setToolTip(
            "IGMH 片段式：Shift+左键拖框框选原子归入片段（增量），"
            "vdW 外壳只画片段内的原子。片段集合持久保留——清除画布选中、"
            "取消高亮都不影响已加的壳；右键菜单或「清除」按钮可清空片段")
        self._vdw_sel_only_chk.setEnabled(False)   # 外壳未开启时不可用
        self._vdw_sel_only_chk.stateChanged.connect(self._on_vdw_sel_only)
        vl.addWidget(self._vdw_sel_only_chk, 0, 3)
        # 外壳开关联动「仅选中片段」可用性
        self._vdw_shell_chk.toggled.connect(self._vdw_sel_only_chk.setEnabled)

        # vdW 半径比例
        self._lbl_vdw_r = QLabel()
        self._lbl_vdw_r.setText(self._cv_bind(self._lbl_vdw_r, "vdW 半径:"))
        vl.addWidget(self._lbl_vdw_r, 1, 0)
        self._vdw_scale_sld = QSlider(Qt.Horizontal)
        self._vdw_scale_sld.setRange(50, 200)    # 0.50x ~ 2.00x（Bondi 表值 × 比例）
        self._vdw_scale_sld.setValue(100)        # 默认 1.00x（真实 vdW 半径）
        self._vdw_scale_sld.setMinimumWidth(200)
        self._vdw_scale_sld.setToolTip("缩放范德华半径（Bondi 表值 × 比例），对原子与外壳同时生效")
        self._vdw_scale_sld.valueChanged.connect(self._on_vdw_scale)
        vl.addWidget(self._vdw_scale_sld, 1, 1)
        self._vdw_scale_edit = QLineEdit("1.00")
        self._vdw_scale_edit.setValidator(QDoubleValidator(0.50, 2.00, 2))
        self._vdw_scale_edit.setMaximumWidth(64)
        self._vdw_scale_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._vdw_scale_edit.editingFinished.connect(self._on_vdw_scale_edit)
        vl.addWidget(self._vdw_scale_edit, 1, 2)

        # 外壳透明度（vdW 外壳勾选后生效）
        self._lbl_vdw_alpha = QLabel()
        self._lbl_vdw_alpha.setText(self._cv_bind(self._lbl_vdw_alpha, "外壳透明度:"))
        self._lbl_vdw_alpha.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        vl.addWidget(self._lbl_vdw_alpha, 2, 0)
        self._vdw_alpha_sld = QSlider(Qt.Horizontal)
        self._vdw_alpha_sld.setRange(2, 80)     # 0.02 ~ 0.80
        self._vdw_alpha_sld.setValue(20)
        self._vdw_alpha_sld.setMinimumWidth(200)
        self._vdw_alpha_sld.setToolTip("vdW 外壳不透明度（0.02 ~ 0.80，越小越透明）")
        self._vdw_alpha_sld.valueChanged.connect(self._on_vdw_alpha)
        vl.addWidget(self._vdw_alpha_sld, 2, 1)

        # 外壳描边粗细（勾选「外壳描边」后生效；0.01 ~ 0.99 剪影带厚度）
        self._lbl_vdw_ow = QLabel()
        self._lbl_vdw_ow.setText(self._cv_bind(self._lbl_vdw_ow, "外壳描边粗细:"))
        self._lbl_vdw_ow.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        vl.addWidget(self._lbl_vdw_ow, 3, 0)
        self._vdw_ow_sld = QSlider(Qt.Horizontal)
        self._vdw_ow_sld.setRange(1, 60)        # 0.01 .. 0.60
        self._vdw_ow_sld.setValue(40)           # 默认 0.40
        self._vdw_ow_sld.setToolTip("vdW 外壳描边粗细（0.01 ~ 0.60 剪影带厚度，越大越粗）")
        self._vdw_ow_sld.valueChanged.connect(self._on_vdw_outline_width)
        vl.addWidget(self._vdw_ow_sld, 3, 1)

        # 片段原子编号输入行（IGMH 式）：输入 1-12,15 这类编号 → 点「vdW」
        # 按钮，这些原子加 vdW 外壳（与框选归入同一片段集合）
        self._lbl_vdw_frag = QLabel()
        self._lbl_vdw_frag.setText(self._cv_bind(self._lbl_vdw_frag, "片段:"))
        vl.addWidget(self._lbl_vdw_frag, 4, 0)
        self._vdw_frag_edit = QLineEdit()
        self._vdw_frag_edit.setPlaceholderText(
            self._cv_bind(self._vdw_frag_edit, "原子编号, 如 1-12,15",
                          "setPlaceholderText"))
        self._vdw_frag_edit.setToolTip(
            "输入要加 vdW 外壳的原子编号（1-based），支持逗号分隔与范围，"
            "如 1-12,15；点「vdW」按钮应用到画布。与 Shift+框选归入的是"
            "同一个片段集合")
        self._vdw_frag_edit.returnPressed.connect(self._on_vdw_frag_apply)
        vl.addWidget(self._vdw_frag_edit, 4, 1)
        self._vdw_frag_btn = QPushButton("vdW")
        self._vdw_frag_btn.setObjectName("SmallBtn")
        self._vdw_frag_btn.setToolTip("把输入框里的原子加入 vdW 片段并显示外壳")
        self._vdw_frag_btn.clicked.connect(self._on_vdw_frag_apply)
        vl.addWidget(self._vdw_frag_btn, 4, 2)
        # 清除 vdW 片段（IGMH 式片段集合的显式清空入口）
        self._vdw_frag_clear_btn = QPushButton()
        self._vdw_frag_clear_btn.setText(self._cv_bind(self._vdw_frag_clear_btn, "清除"))
        self._vdw_frag_clear_btn.setObjectName("SmallBtn")
        self._vdw_frag_clear_btn.setToolTip(
            "清空 vdW 片段原子集合；「仅选中片段」模式下外壳随之消失，"
            "可重新输入或框选添加")
        self._vdw_frag_clear_btn.clicked.connect(self._on_vdw_frag_clear)
        vl.addWidget(self._vdw_frag_clear_btn, 4, 3)

        # ── 成键阈值（已隐藏：使用 cub_viewer 中的默认值 1.0 / 1.3 / 0.4） ──
        # 保留底层回调（_on_brf_tight_edit / _on_brf_loose_edit / _on_dash_w_edit）
        # 与默认值，仅不显示控件。如需恢复，取消下方注释即可。
        # bl.addWidget(QLabel("成键阈值:"), 3, 0)

        # ── 原子十字圆环（两条贴球大圆带，GL 着色器绘制；主控开关 + 控制面板） ──
        self._lbl_rings = QLabel()
        self._lbl_rings.setText(self._cv_bind(self._lbl_rings, "十字圆环:"))
        bl.addWidget(self._lbl_rings, 3, 0)
        self._crosshair_chk = QCheckBox()
        self._crosshair_chk.setText(self._cv_bind(self._crosshair_chk, "显示"))
        self._crosshair_chk.setChecked(False)
        self._crosshair_chk.setToolTip(
            "勾选后在每个原子球面画两条交叉的大圆环（十字效果）；"
            "未勾选则完全不显示")
        self._crosshair_chk.toggled.connect(self._on_crosshair)
        bl.addWidget(self._crosshair_chk, 3, 1)
        self._ring_btn = QPushButton()
        self._ring_btn.setText(self._cv_bind(self._ring_btn, "圆环设置…"))
        self._ring_btn.setObjectName("SmallBtn")
        self._ring_btn.setMaximumWidth(120)
        self._ring_btn.setToolTip(
            "弹出圆环控制面板：调两条环的方位角/俯仰角；勾选锁定后分子怎么转圆环都不转")
        self._ring_btn.clicked.connect(self._open_ring_dialog)
        bl.addWidget(self._ring_btn, 3, 2)
        # bl.addWidget(QLabel("实线"), 3, 1)
        # self._brf_tight_edit = QLineEdit("1.00")
        # self._brf_tight_edit.setValidator(QDoubleValidator(0.50, 2.00, 2))
        # self._brf_tight_edit.setMaximumWidth(54)
        # self._brf_tight_edit.editingFinished.connect(self._on_brf_tight_edit)
        # bl.addWidget(self._brf_tight_edit, 3, 2)
        # bl.addWidget(QLabel("虚线"), 3, 3)
        # self._brf_loose_edit = QLineEdit("1.30")
        # self._brf_loose_edit.setValidator(QDoubleValidator(0.50, 3.00, 2))
        # self._brf_loose_edit.setMaximumWidth(54)
        # self._brf_loose_edit.editingFinished.connect(self._on_brf_loose_edit)
        # bl.addWidget(self._brf_loose_edit, 3, 4)
        # bl.addWidget(QLabel("虚密"), 3, 5)
        # self._dash_w_edit = QLineEdit("0.40")
        # self._dash_w_edit.setValidator(QDoubleValidator(0.05, 1.00, 2))
        # self._dash_w_edit.setMaximumWidth(54)
        # self._dash_w_edit.editingFinished.connect(self._on_dash_w_edit)
        # bl.addWidget(self._dash_w_edit, 3, 6)

        # ── 虚线小圆球：大小 / 间隔 ──
        self._lbl_dot_size = QLabel()
        self._lbl_dot_size.setText(self._cv_bind(self._lbl_dot_size, "虚线大小:"))
        bl.addWidget(self._lbl_dot_size, 4, 0)
        self._dot_size_sld = QSlider(Qt.Horizontal)
        self._dot_size_sld.setRange(20, 400)    # ×0.2 .. ×4.0
        self._dot_size_sld.setValue(100)        # ×1.0
        self._dot_size_sld.setMinimumWidth(200)
        self._dot_size_sld.valueChanged.connect(self._on_dot_size_sld)
        bl.addWidget(self._dot_size_sld, 4, 1)
        self._dot_size_edit = QLineEdit("1.00")
        self._dot_size_edit.setValidator(QDoubleValidator(0.20, 4.00, 2))
        self._dot_size_edit.setMaximumWidth(64)
        self._dot_size_edit.editingFinished.connect(self._on_dot_size_edit)
        bl.addWidget(self._dot_size_edit, 4, 2)

        self._lbl_dot_spacing = QLabel()
        self._lbl_dot_spacing.setText(self._cv_bind(self._lbl_dot_spacing, "虚线间隔:"))
        bl.addWidget(self._lbl_dot_spacing, 5, 0)
        self._dot_spacing_sld = QSlider(Qt.Horizontal)
        self._dot_spacing_sld.setRange(30, 400)  # ×0.3 .. ×4.0
        self._dot_spacing_sld.setValue(100)      # ×1.0
        self._dot_spacing_sld.setMinimumWidth(200)
        self._dot_spacing_sld.valueChanged.connect(self._on_dot_spacing_sld)
        bl.addWidget(self._dot_spacing_sld, 5, 1)
        self._dot_spacing_edit = QLineEdit("1.00")
        self._dot_spacing_edit.setValidator(QDoubleValidator(0.30, 4.00, 2))
        self._dot_spacing_edit.setMaximumWidth(64)
        self._dot_spacing_edit.editingFinished.connect(self._on_dot_spacing_edit)
        bl.addWidget(self._dot_spacing_edit, 5, 2)

        # ── 原子描边 ──
        self._lbl_outline = QLabel()
        self._lbl_outline.setText(self._cv_bind(self._lbl_outline, "原子描边:"))
        bl.addWidget(self._lbl_outline, 6, 0)
        self._outline_chk = QCheckBox()
        self._outline_chk.setText(self._cv_bind(self._outline_chk, "启用"))
        self._outline_chk.setChecked(False)
        self._outline_chk.toggled.connect(self._on_outline_toggle)
        bl.addWidget(self._outline_chk, 6, 1)
        self._outline_color_btn = QPushButton()
        self._outline_color_btn.setText(self._cv_bind(self._outline_color_btn, "颜色"))
        self._outline_color_btn.setObjectName("SmallBtn")
        self._outline_color_btn.clicked.connect(self._on_outline_color)
        bl.addWidget(self._outline_color_btn, 6, 2)

        self._lbl_outline_w = QLabel()
        self._lbl_outline_w.setText(self._cv_bind(self._lbl_outline_w, "描边粗细:"))
        bl.addWidget(self._lbl_outline_w, 7, 0)
        self._outline_w_sld = QSlider(Qt.Horizontal)
        self._outline_w_sld.setRange(1, 600)
        self._outline_w_sld.setValue(400)   # 0.4：细档（窄带公式下 ≈1px 细线）
        self._outline_w_sld.setMinimumWidth(200)
        self._outline_w_sld.valueChanged.connect(self._on_outline_width)
        bl.addWidget(self._outline_w_sld, 7, 1)
        self._outline_w_lbl = QLabel("0.400")
        self._outline_w_lbl.setMaximumWidth(64)
        bl.addWidget(self._outline_w_lbl, 7, 2)

        # ── 背景色（导出/预览用）；导出图片/DPI/透明背景已移到画布下方一键样式行 ──
        self._lbl_bg = QLabel()
        self._lbl_bg.setText(self._cv_bind(self._lbl_bg, "背景色:"))
        bl.addWidget(self._lbl_bg, 8, 0)
        self._bg_color_btn = QPushButton()
        self._bg_color_btn.setText(self._cv_bind(self._bg_color_btn, "选择…"))
        self._bg_color_btn.setObjectName("SmallBtn")
        self._bg_color_btn.setToolTip("设置导出/预览的背景颜色")
        self._bg_color_btn.clicked.connect(self._on_bg_color)
        bl.addWidget(self._bg_color_btn, 8, 1)

        # 景深雾化（IboView Fade：远处蒙白雾）
        self._fade_chk = QCheckBox()
        self._fade_chk.setText(self._cv_bind(self._fade_chk, "景深雾化"))
        self._fade_chk.setChecked(True)
        self._fade_chk.setToolTip("关闭后远处原子/轨道不再因景深变淡发白")
        self._fade_chk.toggled.connect(self._on_fade_toggle)
        bl.addWidget(self._fade_chk, 9, 0, 1, 3)

        col_ball, self._btn_toggle_ball, cl_ball = _collapsible_col(
            _cv("球棍模型"))
        # 球棍网格 + vdW 子分组上下并列，折叠按钮一起控制
        ball_holder = QWidget()
        bh = QVBoxLayout(ball_holder)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.setSpacing(6)
        bh.addWidget(gb)
        bh.addWidget(vdw_grp)
        bh.addStretch(1)
        cl_ball.addWidget(ball_holder, 1)
        _wire_toggle(self._btn_toggle_ball, ball_holder, "球棍模型")
        self._fold_titles.append((self._btn_toggle_ball, "球棍模型"))
        ball_holder.setVisible(False)   # 默认收起
        # 横向 Ignored：忽略内容固有宽度，与显示/等值面列严格等宽（各占一半）
        col_ball.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        outer.addWidget(col_ball, stretch=1)

        return box

    # ── 公开接口 ───────────────────────────────────────────────
    def is_available(self) -> bool:
        """OpenGL 画布是否可用。"""
        return self.glw is not None

    def grid_quality(self) -> str:
        """返回网格精度档位（'1'/'2'/'3'），供 cube 生成使用。"""
        if not hasattr(self, "_grid_quality_cb"):
            return "2"
        return str(self._grid_quality_cb.currentIndex() + 1)

    # ── 色轮（IboView 风格配色） ─────────────────────────
    def _on_wheel_toggle(self, checked):
        """启用/禁用色轮配色：禁用时恢复样式默认配色，避免与样式冲突。"""
        self._wheel_enabled = bool(checked)
        self._color_wheel.setEnabled(self._wheel_enabled)
        if not self.glw:
            return
        if self._wheel_enabled:
            # 启用后立即按当前色相应用一次
            self._on_wheel_hue(self._color_wheel.hue())
        else:
            # 恢复样式（style）默认正/负相位配色
            style_name = getattr(self.glw, "_style_name", None)
            if style_name:
                self.glw.set_style(style_name)
            self._sync_phase_swatches()

    def _on_wheel_hue(self, hue):
        """旋转色轮：按当前配色方案（移植自 IboView）计算正/负相位颜色。

        方案 0 相近色（scheme0, IboView 默认）：正 = Hue+25°, 负 = Hue-25°, S=0.6 V=1.0
        方案 1 同色相不同饱和（scheme1）：正 S=0.6, 负 S=0.35, 同 Hue, V=1.0
        方案 2 互补色（scheme2）：负相位 = Hue + 180°, S=0.6 V=1.0

        与 IboView 一致：透明度由 orb_opacity 控制，此处只决定 RGB。
        仅当色轮已启用（_wheel_enabled）时生效，否则沿用样式配色。
        """
        if not self._wheel_enabled or self.glw is None:
            return
        h = hue % 1.0
        S, V = 0.6, 1.0
        if self._phase_scheme == 1:       # 同色相·不同饱和
            pos = ColorWheelWidget.hue_to_rgb(h, 0.6, V)
            neg = ColorWheelWidget.hue_to_rgb(h, 0.35, V)
        elif self._phase_scheme == 2:     # 互补色
            pos = ColorWheelWidget.hue_to_rgb(h, S, V)
            neg = ColorWheelWidget.hue_to_rgb((h + 0.5) % 1.0, S, V)
        else:                              # 相近色（IboView 默认 scheme0）
            pos = ColorWheelWidget.hue_to_rgb((h + 25.0 / 360.0) % 1.0, S, V)
            neg = ColorWheelWidget.hue_to_rgb((h - 25.0 / 360.0) % 1.0, S, V)
        if self._phase_flipped:
            pos, neg = neg, pos
        self.glw.set_phase_colors(pos_rgb=pos, neg_rgb=neg)
        self._sync_phase_swatches()

    def _on_phase_scheme_changed(self, idx):
        """切换配色方案，立即按当前色相重渲染（等价 IboView 切换 scheme）。"""
        self._phase_scheme = idx
        if self._wheel_enabled:
            self._on_wheel_hue(self._color_wheel.hue())

    def _on_flip_phase(self):
        """翻转相位：交换正/负相位颜色（等价 IboView chkBox_FlipPhase）。

        直接作用于 glw 当前配色（样式或色轮均可），与色轮启用与否无关，
        几何不变。已翻转时再次点击即翻转回来。
        """
        if self.glw is None:
            return
        self.glw.flip_phase()
        self._phase_flipped = not self._phase_flipped
        self._flip_phase_btn.setText("相位已翻 ✓" if self._phase_flipped else "翻转相位")
        self._sync_phase_swatches()

    def _on_wheel_reset(self):
        """恢复当前样式默认配色（等价于取消色轮配色）。"""
        if not self._wheel_enabled or self.glw is None:
            return
        style_name = getattr(self.glw, "_style_name", None)
        if style_name:
            self.glw.set_style(style_name)  # 重新解析默认正/负相位色
        self._color_wheel.set_hue(0.33)
        self._sync_phase_swatches()

    # ── 正/负相位色块选色 ──
    @staticmethod
    def _style_swatch(btn, rgb01):
        """把按钮渲染成当前相位颜色圆点（无文字）。rgb01 为 0..1 元组。"""
        r, g, b = (int(c * 255) for c in rgb01[:3])
        btn.setStyleSheet(
            "QPushButton { background-color: rgb(%d,%d,%d);"
            " border: 1px solid #9AA7B8; border-radius: 13px; }" % (r, g, b))

    def _sync_phase_swatches(self):
        """把正/负相位色块按钮同步为 glw 当前相位配色。"""
        if not hasattr(self, "_phase_pos_btn") or self.glw is None:
            return
        self._style_swatch(self._phase_pos_btn, getattr(self.glw, "_pc", (0.1, 0.8, 0.1)))
        self._style_swatch(self._phase_neg_btn, getattr(self.glw, "_nc", (0.9, 0.25, 0.25)))

    def _on_pick_phase_color(self, which):
        """点击正/负相位色块选色（0-255），直接应用到等值面。"""
        if self.glw is None:
            return
        cur = self.glw._pc if which == "pos" else self.glw._nc
        col = QColorDialog.getColor(
            QColor(int(cur[0] * 255), int(cur[1] * 255), int(cur[2] * 255)),
            self, "正相位颜色" if which == "pos" else "负相位颜色")
        if not col.isValid():
            return
        rgb = (col.red(), col.green(), col.blue())   # 0-255
        if which == "pos":
            self.glw.set_phase_colors(pos_rgb=rgb)
        else:
            self.glw.set_phase_colors(neg_rgb=rgb)
        self._sync_phase_swatches()

    def set_cube_list(self, paths, auto_load=True):
        """记录一批 cube 文件路径；auto_load 时自动渲染第一个。
        顶部下拉框已移除，这里仅维护 _cube_paths 并触发渲染。"""
        if self.glw is None:
            return
        self._cube_paths = [p for p in (paths or []) if os.path.isfile(p)]
        if self._cube_paths and auto_load:
            self.load_cube(self._cube_paths[0])

    def load_cube(self, path, iso=None, style_name=None):
        """在画布中加载并渲染一个 cube 文件。"""
        if self.glw is None or not path or not os.path.isfile(path):
            return False

        # 记录路径（顶部下拉框已移除，仅维护列表）
        if path not in self._cube_paths:
            self._cube_paths.append(path)

        if style_name:
            self.set_style_name(style_name)

        if iso is not None:
            try:
                self.set_isovalue(float(iso))
            except (TypeError, ValueError):
                pass

        try:
            iso_val = float(self._iso_edit.text() or "0.05")
        except ValueError:
            iso_val = 0.05

        note = ""
        if self._rel_chk.isChecked():
            try:
                cd = read_cube(path)
                pct = float(self._rel_sld.value())
                iso_val = relative_iso_threshold(cd, pct)
                self._iso_edit.blockSignals(True)
                self._iso_edit.setText(f"{iso_val:.4f}")
                self._iso_edit.blockSignals(False)
                note = f"  (相对阈值 {pct:.0f}% -> iso={iso_val:.4f})"
            except Exception as e:
                self._set_status(f"相对阈值计算失败，改用绝对值: {e}")

        self.glw.set_style(STYLE_NAMES[self._style_cb.currentIndex()])
        ok = self.glw.load(path, iso_val)
        if ok:
            self._loaded_path = path
            self._set_status(f"已加载: {os.path.basename(path)}{note}")
        else:
            self._set_status(f"加载失败: {os.path.basename(path)}")
        return ok

    def set_style_name(self, name):
        """按风格名切换（与 fchk_orbital.STYLES 的 key 一致）。"""
        if self.glw is None or name not in STYLE_NAMES:
            return
        idx = STYLE_NAMES.index(name)
        if self._style_cb.currentIndex() != idx:
            self._style_cb.setCurrentIndex(idx)
        else:
            self.glw.set_style(name)

    def set_isovalue(self, iso):
        """同步 isovalue 到画布与控件。"""
        if self.glw is None:
            return
        iso = max(0.005, min(float(iso), 0.5))
        self._iso_edit.blockSignals(True)
        self._iso_edit.setText(f"{iso:.4f}")
        self._iso_edit.blockSignals(False)
        self._iso_sld.blockSignals(True)
        self._iso_sld.setValue(int(round(iso * 1000)))
        self._iso_sld.blockSignals(False)
        self.glw.set_isovalue(iso)

    def clear(self):
        """清空下拉列表（不销毁 GL 上下文）。"""
        if self.glw is None:
            return
        self._cube_paths = []
        self._loaded_path = None

    def current_cube(self):
        return self._loaded_path

    def set_molecule(self, atoms, bonds=None):
        """载入 fchk/xyz 后把分子结构推到 GL 画布，使其立即显示球棍模型。
        载入文件后的初始样式默认用 HoukMol。"""
        if self.glw is not None:
            self.glw.set_molecule(atoms, bonds)
            if atoms:
                self._apply_houkmol_style()

    # ── 库便捷 API（桥接到内部 CubGLWidget，供外部直接调用） ──
    def load_cube_files(self, paths):
        """加载 .cub 文件列表（1 个=正负同色，2 个=[正,负] 分离配色）。"""
        self.set_cube_list(paths, auto_load=True)

    def set_iso(self, value):
        """设置等值面绝对阈值（a.u.）。"""
        self.set_isovalue(value)

    def get_iso(self):
        """返回当前等值面绝对阈值。"""
        if self.glw is not None:
            return self.glw._isovalue
        return None

    def set_positive_color(self, color):
        """设置正相位颜色，接受 '#rrggbb' 或 (r,g,b) 0-255。"""
        self._apply_phase(pos_rgb=_parse_color(color))

    def set_negative_color(self, color):
        """设置负相位颜色，接受 '#rrggbb' 或 (r,g,b) 0-255。"""
        self._apply_phase(neg_rgb=_parse_color(color))

    def set_transparency(self, value):
        """设置等值面透明度 value（0=不透明, 1=全透）。"""
        if self.glw is not None:
            self.glw.set_opacity(1.0 - float(value))

    def set_render_quality(self, level):
        """设置渲染质量: 'low' / 'medium' / 'high'。"""
        if self.glw is not None:
            self.glw.set_depth_peeling(level != "low")

    def set_mol_style_name(self, name):
        """设置分子风格（球棍 / 飘带 / 仅球 等），接受显示名或原名。"""
        self._set_mol_style_by_name(name)

    def set_shininess_name(self, name):
        """设置光泽预设名。"""
        self.set_shininess(name)

    def set_background_color(self, color):
        """设置背景颜色，接受 '#rrggbb' 或 (r,g,b) 0-255。"""
        if self.glw is not None:
            self.glw.set_background(_parse_color(color))

    def set_fade_enabled(self, enabled):
        """景深雾化（IboView Fade：远处蒙白雾）开关。默认开启以保留原貌。"""
        if self.glw is not None:
            self.glw.set_fade_enabled(bool(enabled))

    def reset_view(self):
        """重置相机视角。"""
        if self.glw is not None:
            self.glw.reset_view()

    def export_image(self, path, dpi=600.0):
        """离屏渲染导出图像。"""
        if self.glw is not None:
            return self.glw.export_image(path, dpi)
        return False

    def _apply_phase(self, pos_rgb=None, neg_rgb=None):
        """更新相位配色（pos/neg 可单独提供，未提供则沿用当前值）。"""
        if self.glw is None:
            return
        p = pos_rgb if pos_rgb is not None else self.glw._pc
        n = neg_rgb if neg_rgb is not None else self.glw._nc
        self.glw.set_phase_colors(pos_rgb=p, neg_rgb=n)

    def _set_mol_style_by_name(self, name):
        """按名称（显示名或原名）切换分子风格下拉框。"""
        idx = self._mol_style_cb.findText(name)
        if idx < 0:
            for i in range(self._mol_style_cb.count()):
                if self._mol_style_cb.itemText(i).split("—")[0].strip() == name:
                    idx = i
                    break
        if idx >= 0:
            self._mol_style_cb.setCurrentIndex(idx)

    # ── 内部回调 ───────────────────────────────────────────────
    def _set_status(self, msg):
        if hasattr(self, "_status_lbl"):
            self._status_lbl.setText(str(msg))
        self.statusChanged.emit(str(msg))

    def _on_toggle_params(self, on):
        self._params.setVisible(bool(on))
        self._more_btn.setText(f"{_cv('参数')} {'▴' if on else '▾'}")

    def show_params_panel(self, visible):
        """外部控制画布参数区是否显示在画布下方。"""
        self._params.setVisible(bool(visible))
        self._more_btn.setChecked(bool(visible))
        self._more_btn.setText(f"{_cv('参数')} {'▴' if visible else '▾'}")

    def _on_cube_pick(self, idx):
        if 0 <= idx < len(self._cube_paths):
            self.load_cube(self._cube_paths[idx])

    def _browse(self):
        p, _ = open_file(
            self, "选择 Cube 文件", "", "Cube Files (*.cub *.cube);;All (*)")
        if p:
            self.load_cube(p)

    def _reset_view(self):
        if self.glw is not None:
            self.glw.reset_view()

    def _on_style(self, idx):
        if self.glw is not None and 0 <= idx < len(STYLE_NAMES):
            self.glw.set_style(STYLE_NAMES[idx])
            # 若分子样式为 VMD 单色，跟随等值面风格切换碳色
            if self.glw is not None and self._mol_style_cb.currentIndex() == 1:
                self.glw.set_mol_style("VMD single")
            self._sync_phase_swatches()
            # 风格切换会重建 _sp（透明度等），同步透明度滑块/标签；
            # _build_params 早期会先触发一次 _on_style，此时控件未建全，
            # 用 hasattr 跳过（与 _sync_phase_swatches 的守卫一致）
            if hasattr(self, "_op_sld"):
                self._sync_style_ui()

    def _on_lighting(self, idx):
        """光照/渲染效果轴：只改 u_MvGrad（三光/单光/双光/四光），不碰配色/背景/描边。"""
        if self.glw is None or not (0 <= idx < len(_LIGHTING_OPTIONS)):
            return
        grad = _LIGHTING_OPTIONS[idx][1]
        self.glw.set_mv_gradient(grad)   # "" → IboView 三光

    def _on_mol_style(self, idx):
        """原子配色轴：只改原子元素配色方案，不触碰光照/材质/背景/描边。"""
        if self.glw is None or not (0 <= idx < len(MOL_STYLE_NAMES)):
            return
        name = MOL_STYLE_NAMES[idx]
        # widget 内部会按当前等值面风格的 c_rgb 取碳色（VMD single 时）
        self.glw.set_mol_style(name)

    def _open_element_color_dialog(self):
        """元素原子颜色设置：自定义每种元素的颜色（覆盖默认 CPK 配色）。"""
        if self.glw is None:
            return
        dlg = ElementColorDialog(self, self.glw)
        if dlg.exec_() == QDialog.Accepted:
            self.glw.set_element_colors(dlg.result_overrides())
            if hasattr(self, "on_vmd_refresh") and self.on_vmd_refresh:
                try:
                    self.on_vmd_refresh()
                except Exception:
                    pass

    def _on_shiny(self, idx):
        if self.glw is None or not (0 <= idx < len(SHININESS_PRESETS)):
            return
        name = list(SHININESS_PRESETS.keys())[idx]
        self.glw.set_shininess(name)

    def _on_orb_outline(self, on):
        """等值面描边开关（保持当前描边颜色/宽度）。"""
        if self.glw is not None:
            self.glw.set_orb_outline(bool(on))

    def _on_crosshair(self, on):
        """原子十字圆环开关（主控：勾选显示，不勾不显示）。"""
        if self.glw is not None:
            self.glw.set_crosshair(bool(on))

    def _open_ring_dialog(self):
        """弹出十字圆环控制面板（方位/俯仰 + 锁定）。"""
        if self.glw is None:
            return
        if getattr(self, "_ring_dialog", None) is None:
            self._ring_dialog = RingControlDialog(self.glw, self)
        self._ring_dialog.show()
        self._ring_dialog.raise_()
        self._ring_dialog.activateWindow()

    def _open_light_dialog(self):
        """弹出光源控制面板（左侧球体预览 + 右侧数量/方向/光晕滑块）。"""
        if self.glw is None:
            return
        if getattr(self, "_light_dialog", None) is None:
            self._light_dialog = LightControlDialog(self.glw, self)
        self._light_dialog.sync_from_glw()
        self._light_dialog.show()
        self._light_dialog.raise_()
        self._light_dialog.activateWindow()

    # ── 样式保存 / 载入 ──
    def _apply_light_state(self, style):
        """应用样式字典中的光源部分（方向/数量/光晕），不影响光照模式。"""
        if self.glw is None:
            return
        if style.get("light_dirs"):
            self.glw._light_default_dirs = [
                tuple(float(x) for x in d[:3]) for d in style["light_dirs"][:4]]
            while len(self.glw._light_default_dirs) < 4:
                self.glw._light_default_dirs.append((0.0, 0.0, 1.0))
            self.glw._light_dirs = [list(x) for x in self.glw._light_default_dirs]
            # 方向整体替换后清掉旧偏移，避免光源对话框残留的方位/俯仰
            # 在用户微调时突然叠加生效（与 LightControlDialog._load 一致）
            self.glw._light_az = 0.0
            self.glw._light_el = 0.0
        if "light_count" in style:
            self.glw._light_count = max(1, min(4, int(style["light_count"])))
        if "light_glow" in style:
            self.glw.set_light_glow(float(style["light_glow"]))
        if style.get("light_glows"):
            for i, g in enumerate(style["light_glows"][:4]):
                self.glw.set_light_glow_i(i, g)
        self.glw.update()

    def _apply_sobart_style(self):
        """sob-art 默认：IBOVIEW 等值面绘制方法 + 等值面风格 sob-art +
        SobArt 原子配色 + 原子描边 0.35 + sob-art.json 光照。"""
        if self.glw is None:
            return
        self.glw.reset_molviewer_style()
        self.glw.set_style("sob-art")
        self.glw.set_mol_style("SobArt")
        self.glw.set_atom_scale(1.5)
        self.glw.set_atom_outline(True, (0.0, 0.0, 0.0), 0.35)
        self._apply_light_state(_SOBART_STYLE)
        self._sync_style_ui()
        self._set_status("已应用默认样式 sob-art")

    def _apply_iboview_style(self):
        """一键回到默认 IboView 观感：CPK / 三光 / 白底 / 无描边，
        等值面配色（相位色）用风格 ultra-glass。"""
        if self.glw is None:
            return
        self.glw.reset_molviewer_style()
        self.glw.set_style("ultra-glass")
        self.glw.set_atom_scale(1.5)
        self._sync_style_ui()
        self._set_status("已应用默认样式 IBOview")

    def _apply_iqmol_style(self):
        """IQmol 默认：IBOVIEW 等值面绘制方法 + 当前等值面风格 +
        相位色 #e2254f / #0062ff + 原子配色 GaussView + 光照角度与 sob-art 一致。"""
        if self.glw is None:
            return
        self.glw.reset_molviewer_style()
        sn = getattr(self.glw, "_style_name", None)
        if sn:
            self.glw.set_style(sn)
        # 原子配色：GaussView（Tian Lu 的 gview_color.tcl 调色板，
        # 与 HoukMol/SobArt 等样式同一套，便于横向对比）
        self.glw.set_mol_style("GaussView")
        # 轨道相位颜色：#e2254f（正相位）/ #0062ff（负相位）
        self.glw.set_phase_colors(pos_rgb=(0xE2, 0x25, 0x4F),
                                  neg_rgb=(0x00, 0x62, 0xFF))
        self.glw.set_atom_scale(1.5)
        # 光照角度与 sob-art 一致
        self._apply_light_state(_SOBART_STYLE)
        self._sync_style_ui()
        self._set_status("已应用默认样式 IQmol（原子配色 GaussView）")

    # ── 分子显示辅助：隐藏氢 / 保留编号 / 原子标签 ──

    def _parse_keep_h(self):
        """解析「保留H编号」输入框 → 1-based 序号集合。

        支持 "1,3,5-8" / "1 3 5-8" / "1;3" 等形式；非法输入返回空集。
        """
        txt = self._keep_h_edit.text().strip()
        if not txt:
            return set()
        out = set()
        for part in txt.replace(";", ",").replace(" ", ",").split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                try:
                    a, b = part.split("-", 1)
                    lo, hi = int(a), int(b)
                    if lo > hi:
                        lo, hi = hi, lo
                    out.update(range(lo, hi + 1))
                except ValueError:
                    continue
            else:
                try:
                    out.add(int(part))
                except ValueError:
                    continue
        return {x for x in out if x > 0}

    def _on_hide_hydrogens(self, on):
        if self.glw is not None:
            keep = self._parse_keep_h()
            self.glw.set_hide_hydrogens(bool(on), keep)

    def _on_keep_h_edited(self):
        if self.glw is not None and self._hide_h_chk.isChecked():
            keep = self._parse_keep_h()
            self.glw.set_hide_hydrogens(True, keep)
            self._set_status(f"保留 H 编号: {sorted(keep) or '无'}")

    def _on_atom_label_idx(self, on):
        if self.glw is None:
            return
        # 原子编号与元素符号互斥：开编号关符号，反之亦然
        if on:
            self._lbl_sym_chk.blockSignals(True)
            self._lbl_sym_chk.setChecked(False)
            self._lbl_sym_chk.blockSignals(False)
            self.glw.set_atom_labels(1)
        else:
            if not self._lbl_sym_chk.isChecked():
                self.glw.set_atom_labels(2)

    def _on_atom_label_sym(self, on):
        if self.glw is None:
            return
        if on:
            self._lbl_idx_chk.blockSignals(True)
            self._lbl_idx_chk.setChecked(False)
            self._lbl_idx_chk.blockSignals(False)
            self.glw.set_atom_labels(0)
        else:
            if not self._lbl_idx_chk.isChecked():
                self.glw.set_atom_labels(2)

    def _on_measure_mode(self, on):
        """测键长开关：转发给画布（开启选点；退出保留标注，可继续调整）。"""
        if self.glw is not None:
            self.glw.set_measure_mode(on)

    def _on_measure_clear(self):
        """清除全部键长测量标注。"""
        if self.glw is not None:
            self.glw.clear_measure_items()

    def _on_clear_analysis_clicked(self):
        """「清空样式」：清空画布上全部等值面/临界点/极值点等分析效果。
        优先走主窗口注入的 on_clear_analysis（联动 ESP/IGMH/AIM 面板），
        无注入时只清画布自身。"""
        if callable(self.on_clear_analysis):
            try:
                self.on_clear_analysis()
                return
            except Exception:
                pass
        if self.glw is not None:
            self.glw.clear_analysis()

    def _apply_houkmol_style(self):
        """一键应用默认样式 HoukMol（内嵌，单光渐变 + 默认圆环方位），
        等值面配色（相位色）用风格 mango-lime。"""
        if self.glw is None:
            return
        # 先定等值面风格（相位色取自 mango-lime），再套 HoukMol 材质/光照/
        # 透明度覆盖，避免 set_style 重建 _sp 时把 dict 里的 orb_opacity
        # 等字段静默冲掉。
        self.glw.set_style("mango-lime")
        st = dict(_HOUKMOL_STYLE)
        st.pop("phase_pos", None)   # 相位色保持 mango-lime，不覆盖
        st.pop("phase_neg", None)
        self.glw.apply_style_state(st)
        self.glw.set_atom_scale(1.5)
        self.glw.apply_ring_state(_HOUKMOL_RING)
        self._sync_style_ui()
        self._set_status("已应用默认样式 HoukMol")

    def _save_style(self):
        if self.glw is None:
            return
        p, _ = save_file(self, "保存样式", "gxnu_style.json",
                         "JSON (*.json)")
        if not p:
            return
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(self.glw.get_style_state(), f, ensure_ascii=False, indent=2)
            self._set_status(f"样式已保存: {os.path.basename(p)}")
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))

    def _load_style(self):
        if self.glw is None:
            return
        p, _ = open_file(self, "载入样式", "", "JSON (*.json)")
        if not p:
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                st = json.load(f)
            self.glw.apply_style_state(st)
            self._sync_style_ui()
            self._set_status(f"样式已载入: {os.path.basename(p)}")
        except Exception as e:
            QMessageBox.warning(self, "载入失败", str(e))

    def _sync_style_ui(self):
        """载入样式后把面板控件同步为当前画布状态。"""
        if self.glw is None:
            return
        # 光照下拉框
        gname = self.glw._mv_grad_name()
        for i, (name, grad) in enumerate(_LIGHTING_OPTIONS):
            if grad == gname:
                self._light_cb.blockSignals(True)
                self._light_cb.setCurrentIndex(i)
                self._light_cb.blockSignals(False)
                break
        # 原子配色
        if self.glw._mol_style in MOL_STYLE_NAMES:
            self._mol_style_cb.blockSignals(True)
            self._mol_style_cb.setCurrentIndex(MOL_STYLE_NAMES.index(self.glw._mol_style))
            self._mol_style_cb.blockSignals(False)
        # 光泽
        if self.glw._shininess in SHININESS_PRESETS:
            self._shiny_cb.blockSignals(True)
            self._shiny_cb.setCurrentIndex(list(SHININESS_PRESETS.keys()).index(self.glw._shininess))
            self._shiny_cb.blockSignals(False)
        # 原子/键 半径
        self._atom_scale_sld.blockSignals(True)
        self._atom_scale_sld.setValue(int(self.glw._atom_scale * 100))
        self._atom_scale_sld.blockSignals(False)
        self._atom_scale_edit.setText(f"{self.glw._atom_scale:.2f}")
        self._bond_scale_sld.blockSignals(True)
        self._bond_scale_sld.setValue(int(self.glw._bond_scale * 100))
        self._bond_scale_sld.blockSignals(False)
        self._bond_scale_edit.setText(f"{self.glw._bond_scale:.2f}")
        # 原子描边
        self._outline_chk.blockSignals(True)
        self._outline_chk.setChecked(bool(self.glw._atom_outline))
        self._outline_chk.blockSignals(False)
        self._outline_w_sld.blockSignals(True)
        self._outline_w_sld.setValue(int(self.glw._atom_outline_width * 1000))
        self._outline_w_sld.blockSignals(False)
        self._outline_w_lbl.setText(f"{self.glw._atom_outline_width:.3f}")
        # 等值面描边 + 透明度
        self._orb_outline_chk.blockSignals(True)
        self._orb_outline_chk.setChecked(bool(self.glw._orb_outline))
        self._orb_outline_chk.blockSignals(False)
        self._orb_outline_sld.blockSignals(True)
        self._orb_outline_sld.setValue(int(self.glw._orb_outline_width * 100))
        self._orb_outline_sld.blockSignals(False)
        self._orb_outline_val.setText(f"{self.glw._orb_outline_width:.2f}")
        op = self.glw._sp.get('opacity', 1.0)
        self._op_sld.blockSignals(True)
        self._op_sld.setValue(int((1.0 - op) * 100))
        self._op_sld.blockSignals(False)
        self._op_edit.blockSignals(True)
        self._op_edit.setText(f"{(1.0 - op) * 100:.0f}")
        self._op_edit.blockSignals(False)
        # 十字圆环 + 相位色
        self._crosshair_chk.blockSignals(True)
        self._crosshair_chk.setChecked(bool(self.glw._crosshair))
        self._crosshair_chk.blockSignals(False)
        self._sync_phase_swatches()
        # Depth peeling：复选框 + 层数
        dp = getattr(self.glw, "_dp_layers", 0)
        self._dp_chk.blockSignals(True)
        self._dp_chk.setChecked(dp > 0)
        self._dp_chk.blockSignals(False)
        if dp > 0:
            self._dp_layers_spin.blockSignals(True)
            self._dp_layers_spin.setValue(dp)
            self._dp_layers_spin.blockSignals(False)
        self._dp_layers_spin.setEnabled(dp > 0)
        # 分子显示辅助：隐藏氢 / 保留 H 编号 / 原子标签
        if hasattr(self, "_hide_h_chk"):
            hid = bool(getattr(self.glw, "_hide_hydrogens", False))
            self._hide_h_chk.blockSignals(True)
            self._hide_h_chk.setChecked(hid)
            self._hide_h_chk.blockSignals(False)
            keep = getattr(self.glw, "_keep_h_atoms", set())
            self._keep_h_edit.blockSignals(True)
            self._keep_h_edit.setText(",".join(str(x) for x in sorted(keep)))
            self._keep_h_edit.blockSignals(False)
            mode = int(getattr(self.glw, "_atom_labels", 2))
            self._lbl_idx_chk.blockSignals(True)
            self._lbl_idx_chk.setChecked(mode == 1)
            self._lbl_idx_chk.blockSignals(False)
            self._lbl_sym_chk.blockSignals(True)
            self._lbl_sym_chk.setChecked(mode == 0)
            self._lbl_sym_chk.blockSignals(False)
        if getattr(self, "_light_dialog", None) is not None:
            self._light_dialog.sync_from_glw()
        if getattr(self, "_ring_dialog", None) is not None:
            self._ring_dialog.sync_from_glw()

    def _on_orb_outline_width(self, v):
        """等值面描边粗细（窄带阈值 0.01..0.99；未勾选时也记住宽度）。"""
        w = v / 100.0
        self._orb_outline_val.setText(f"{w:.2f}")
        if self.glw is not None:
            self.glw.set_orb_outline(self._orb_outline_chk.isChecked(), width=w)

    def _on_orb_outline_color(self):
        """等值面描边颜色（默认黑色）。"""
        cur = self._orb_outline_color
        col = QColorDialog.getColor(QColor(int(cur[0] * 255), int(cur[1] * 255),
                                           int(cur[2] * 255)), self, "等值面描边颜色")
        if not col.isValid():
            return
        self._orb_outline_color = (col.redF(), col.greenF(), col.blueF())
        if self.glw is not None:
            self.glw.set_orb_outline(self._orb_outline_chk.isChecked(),
                                     color=self._orb_outline_color)
        self._apply_orb_outline_swatch()

    def _apply_orb_outline_swatch(self):
        """把描边颜色按钮同步为当前颜色圆点（无文字）。"""
        self._style_swatch(self._orb_outline_color_btn, self._orb_outline_color)

    def _on_sel_marker(self, idx):
        if self.glw is None:
            return
        name = ["icosahedron", "sphere", "torus", "glow"][idx] if 0 <= idx < 4 \
            else "icosahedron"
        self.glw.set_selection_marker_shape(name)

    def _on_sel_pulse(self, on):
        if self.glw is not None:
            self.glw.set_selection_marker_pulse(bool(on))

    def _on_rel_mode(self, on):
        self._rel_sld.setEnabled(bool(on))
        self._iso_sld.setEnabled(not on)
        self._iso_edit.setEnabled(not on)
        if on and self._loaded_path:
            self._on_rel_slider(self._rel_sld.value())

    def _on_rel_slider(self, v):
        self._rel_lbl.setText(f"{v}%")
        if not self._rel_chk.isChecked() or self.glw is None:
            return
        if self.glw.cube is None:
            return
        try:
            iso = relative_iso_threshold(self.glw.cube, float(v))
        except Exception:
            return
        self._iso_edit.blockSignals(True)
        self._iso_edit.setText(f"{iso:.4f}")
        self._iso_edit.blockSignals(False)
        self.glw.set_isovalue(iso)

    def _on_dp_toggle(self, on):
        if self.glw is not None:
            layers = self._dp_layers_spin.value()
            if on and layers <= 0:
                # 勾选时 spin 仍为 0（“关闭”占位）→ 落到引擎默认层数，
                # 并回填 spin，避免“显示 0 层、实际默认 4 层”的不一致。
                layers = int(IBOVIEW_DEFAULTS['DepthPeelingLayers'])
                self._dp_layers_spin.blockSignals(True)
                self._dp_layers_spin.setValue(layers)
                self._dp_layers_spin.blockSignals(False)
            self.glw.set_depth_peeling(bool(on), layers if layers > 0 else None)
            self._dp_layers_spin.setEnabled(bool(on))

    def _on_dp_layers(self, value):
        if self.glw is None:
            return
        if value <= 0:
            # 层数设为 0 = 关闭
            self.glw.set_depth_peeling(False)
            self._dp_chk.blockSignals(True)
            self._dp_chk.setChecked(False)
            self._dp_chk.blockSignals(False)
            self._dp_layers_spin.setEnabled(False)
        else:
            self.glw.set_depth_peeling(True, value)
            self._dp_chk.blockSignals(True)
            self._dp_chk.setChecked(True)
            self._dp_chk.blockSignals(False)
            self._dp_layers_spin.setEnabled(True)

    def _on_iso_slider(self, v):
        iso = v / 1000.0
        self._iso_edit.blockSignals(True)
        self._iso_edit.setText(f"{iso:.3f}")
        self._iso_edit.blockSignals(False)
        if self.glw is not None:
            self.glw.set_isovalue(iso)

    def _on_iso_edit(self):
        try:
            iso = float(self._iso_edit.text())
        except ValueError:
            return
        self.set_isovalue(iso)

    def _on_op(self, v):
        # 滑块值 = 透明度(%)；opacity = 1 - 透明度
        transparency = v / 100.0
        op = 1.0 - transparency
        self._op_edit.blockSignals(True)
        self._op_edit.setText(str(v))
        self._op_edit.blockSignals(False)
        if self.glw is not None:
            self.glw.set_opacity(op)

    def _on_op_edit(self):
        """透明度精确输入（0-100%）：同步滑块与画布。"""
        try:
            v = int(self._op_edit.text())
        except ValueError:
            return
        v = max(0, min(100, v))
        self._op_edit.setText(str(v))
        self._op_sld.blockSignals(True)
        self._op_sld.setValue(v)
        self._op_sld.blockSignals(False)
        self._on_op(v)

    def _on_atom_scale_sld(self, val):
        s = val / 100.0
        self._atom_scale_edit.blockSignals(True)
        self._atom_scale_edit.setText(f"{s:.2f}")
        self._atom_scale_edit.blockSignals(False)
        if self.glw is not None:
            self.glw.set_atom_scale(s)

    def _on_atom_scale_edit(self):
        try:
            s = float(self._atom_scale_edit.text())
        except ValueError:
            return
        s = max(0.20, min(s, 3.00))
        self._atom_scale_sld.blockSignals(True)
        self._atom_scale_sld.setValue(int(s * 100))
        self._atom_scale_sld.blockSignals(False)
        if self.glw is not None:
            self.glw.set_atom_scale(s)

    # ── 范德华半径可视化（诉求 1 & 2）──
    def _on_vdw_mode(self, state):
        if self.glw is not None:
            self.glw.set_vdw_mode(state == Qt.Checked)

    def _on_vdw_shell(self, state):
        if self.glw is not None:
            alpha = self._vdw_alpha_sld.value() / 100.0
            self.glw.set_vdw_shell(state == Qt.Checked, alpha)
            # 子开关状态同步到 GL（外壳关闭时子开关禁用，但状态仍保留）
            self.glw.set_vdw_shell_selection_only(
                self._vdw_sel_only_chk.isChecked())

    def _on_vdw_sel_only(self, state):
        if self.glw is not None:
            self.glw.set_vdw_shell_selection_only(state == Qt.Checked)

    def _on_vdw_frag_clear(self):
        if self.glw is not None:
            self.glw.clear_vdw_selection()

    def _on_vdw_frag_set_changed(self, indices_1based):
        """片段集合变化（框选/点选/清除）→ 把编号压成范围串回填输入框。"""
        if not hasattr(self, "_vdw_frag_edit"):
            return
        from igmh_panel import compress_ranges
        text = compress_ranges(indices_1based)
        self._vdw_frag_edit.setText(text)
        if not text:
            return
        # 输入框内容与片段集合已一致，清掉可能的"手动改过"状态即可，
        # 这里仅同步显示，不触发应用

    def _on_vdw_frag_apply(self):
        """把输入框里的原子编号（如 1-12,15）归入 vdW 片段并显示外壳。"""
        if self.glw is None:
            return
        text = self._vdw_frag_edit.text().strip()
        if not text:
            return
        from igmh_panel import parse_ranges
        indices = sorted(i for i in parse_ranges(text) if i > 0)
        # 越界编号过滤（按当前原子总数截断）
        atoms = self.glw._atom_list()
        n_atoms = len(atoms)
        valid = [i for i in indices if i <= n_atoms] if n_atoms else []
        invalid = len(indices) - len(valid)
        if not valid:
            return
        self.glw.set_vdw_shell(True, self._vdw_alpha_sld.value() / 100.0)
        self._vdw_shell_chk.setChecked(True)
        self.glw.set_vdw_shell_selection_only(True)
        self._vdw_sel_only_chk.setChecked(True)
        self.glw.add_vdw_selection(valid)
        msg = f"片段: 已为 {len(valid)} 个原子加 vdW 外壳"
        if invalid:
            msg += f"（{invalid} 个编号越界已忽略，共 {n_atoms} 个原子）"
        self.glw._status(msg)

    def _on_vdw_alpha(self, val):
        if self.glw is not None and self._vdw_shell_chk.isChecked():
            self.glw.set_vdw_shell(True, val / 100.0)

    def _on_vdw_outline(self, state):
        if self.glw is not None:
            self.glw.set_vdw_outline(state == Qt.Checked)

    def _on_vdw_outline_width(self, val):
        if self.glw is not None:
            self.glw.set_vdw_outline(
                self._vdw_outline_chk.isChecked(),
                width=val / 100.0)

    def _on_vdw_scale(self, val):
        s = val / 100.0
        self._vdw_scale_edit.blockSignals(True)
        self._vdw_scale_edit.setText(f"{s:.2f}")
        self._vdw_scale_edit.blockSignals(False)
        if self.glw is not None:
            self.glw.set_vdw_scale(s)

    def _on_vdw_scale_edit(self):
        try:
            s = float(self._vdw_scale_edit.text())
        except ValueError:
            s = 1.0
        s = max(0.50, min(2.00, s))
        self._vdw_scale_sld.blockSignals(True)
        self._vdw_scale_sld.setValue(int(round(s * 100)))
        self._vdw_scale_sld.blockSignals(False)
        self._vdw_scale_edit.setText(f"{s:.2f}")
        if self.glw is not None:
            self.glw.set_vdw_scale(s)

    def _on_bond_scale_sld(self, val):
        s = val / 100.0
        self._bond_scale_edit.blockSignals(True)
        self._bond_scale_edit.setText(f"{s:.2f}")
        self._bond_scale_edit.blockSignals(False)
        if self.glw is not None:
            self.glw.set_bond_scale(s)

    def _on_bond_scale_edit(self):
        try:
            s = float(self._bond_scale_edit.text())
        except ValueError:
            return
        s = max(0.20, min(s, 3.00))
        self._bond_scale_sld.blockSignals(True)
        self._bond_scale_sld.setValue(int(s * 100))
        self._bond_scale_sld.blockSignals(False)
        if self.glw is not None:
            self.glw.set_bond_scale(s)

    def _on_thinning_sld(self, v):
        t = v / 100.0
        self._thinning_edit.blockSignals(True)
        self._thinning_edit.setText(f"{t:.2f}")
        self._thinning_edit.blockSignals(False)
        if self.glw is not None:
            self.glw.set_bond_thinning(t)

    def _on_thinning_edit(self):
        try:
            t = float(self._thinning_edit.text())
        except ValueError:
            return
        t = max(0.20, min(t, 1.00))
        self._thinning_sld.blockSignals(True)
        self._thinning_sld.setValue(int(t * 100))
        self._thinning_sld.blockSignals(False)
        if self.glw is not None:
            self.glw.set_bond_thinning(t)

    # ── 成键阈值控制（控件已隐藏，方法保留但仅当属性存在时生效） ──
    def _on_brf_tight_edit(self):
        if not hasattr(self, '_brf_tight_edit'):
            return
        try:
            v = float(self._brf_tight_edit.text())
        except ValueError:
            return
        v = max(0.50, min(v, 2.00))
        self._brf_tight_edit.blockSignals(True)
        self._brf_tight_edit.setText(f"{v:.2f}")
        self._brf_tight_edit.blockSignals(False)
        if self.glw is not None:
            self.glw.set_bond_rf_tight(v)

    def _on_brf_loose_edit(self):
        if not hasattr(self, '_brf_loose_edit'):
            return
        try:
            v = float(self._brf_loose_edit.text())
        except ValueError:
            return
        v = max(0.50, min(v, 3.00))
        self._brf_loose_edit.blockSignals(True)
        self._brf_loose_edit.setText(f"{v:.2f}")
        self._brf_loose_edit.blockSignals(False)
        if self.glw is not None:
            self.glw.set_bond_rf_loose(v)

    def _on_dash_w_edit(self):
        if not hasattr(self, '_dash_w_edit'):
            return
        try:
            v = float(self._dash_w_edit.text())
        except ValueError:
            return
        v = max(0.05, min(v, 1.00))
        self._dash_w_edit.blockSignals(True)
        self._dash_w_edit.setText(f"{v:.2f}")
        self._dash_w_edit.blockSignals(False)
        if self.glw is not None:
            self.glw.set_dash_weight(v)

    def _on_dot_size_sld(self, val):
        v = val / 100.0   # ×0.2 .. ×4.0
        self._dot_size_edit.blockSignals(True)
        self._dot_size_edit.setText(f"{v:.2f}")
        self._dot_size_edit.blockSignals(False)
        if self.glw is not None:
            self.glw.set_dot_size(v)

    def _on_dot_size_edit(self):
        try:
            v = float(self._dot_size_edit.text())
        except ValueError:
            return
        v = max(0.20, min(v, 4.00))
        self._dot_size_sld.blockSignals(True)
        self._dot_size_sld.setValue(int(v * 100))
        self._dot_size_sld.blockSignals(False)
        if self.glw is not None:
            self.glw.set_dot_size(v)

    def _on_dot_spacing_sld(self, val):
        v = val / 100.0   # ×0.3 .. ×4.0
        self._dot_spacing_edit.blockSignals(True)
        self._dot_spacing_edit.setText(f"{v:.2f}")
        self._dot_spacing_edit.blockSignals(False)
        if self.glw is not None:
            self.glw.set_dot_spacing(v)

    def _on_dot_spacing_edit(self):
        try:
            v = float(self._dot_spacing_edit.text())
        except ValueError:
            return
        v = max(0.30, min(v, 4.00))
        self._dot_spacing_sld.blockSignals(True)
        self._dot_spacing_sld.setValue(int(v * 100))
        self._dot_spacing_sld.blockSignals(False)
        if self.glw is not None:
            self.glw.set_dot_spacing(v)

    # ── 原子描边控制 ──
    def _on_outline_toggle(self, on):
        if self.glw is None:
            return
        self.glw.set_atom_outline(on)

    def _on_outline_color(self):
        cur = self._outline_color
        col = QColorDialog.getColor(QColor(int(cur[0] * 255), int(cur[1] * 255),
                                           int(cur[2] * 255)), self, "描边颜色")
        if not col.isValid():
            return
        self._outline_color = (col.redF(), col.greenF(), col.blueF())
        if self.glw is not None:
            self.glw.set_atom_outline(self._outline_chk.isChecked(), color=self._outline_color)

    def _on_bg_color(self):
        cur = self._bg_rgba
        col = QColorDialog.getColor(
            QColor(int(cur[0] * 255), int(cur[1] * 255), int(cur[2] * 255)),
            self, "背景颜色")
        if not col.isValid():
            return
        self._bg_rgba = (col.redF(), col.greenF(), col.blueF(), 1.0)
        if self.glw is not None:
            self.glw.set_background(self._bg_rgba)

    # ── 景深雾化（IboView Fade）回调 ──
    def _on_fade_toggle(self, on):
        if self.glw is not None:
            self.glw.set_fade_enabled(bool(on))

    def _on_outline_width(self, v):
        w = v / 1000.0
        self._outline_w_lbl.setText(f"{w:.3f}")
        if self.glw is not None:
            self.glw.set_atom_outline(self._outline_chk.isChecked(), width=w)

    def _screenshot(self):
        if self.glw is None:
            return
        base = os.path.splitext(os.path.basename(self._loaded_path or "cub_view"))[0]
        p, _ = save_file(self, "保存截图", base + ".png", "PNG (*.png)")
        if p:
            self.glw.screenshot(p)

    def _export_image(self):
        if self.glw is None:
            return
        # 画布里有内容（cube 等值面或独立分子）即可导出，不强制要求 cube 文件
        has_content = (
            self._loaded_path is not None
            or getattr(self.glw, "_molecule", None) is not None
            or getattr(self.glw, "_atom_surf", None) is not None
            or getattr(self.glw, "_pos_surf", None) is not None
            or getattr(self.glw, "_cube", None) is not None)
        if not has_content:
            QMessageBox.information(self, "提示", "画布为空，请先加载文件或分子。")
            return
        base = (os.path.splitext(os.path.basename(self._loaded_path))[0]
                if self._loaded_path else "mol_view")
        p, _ = save_file(self, "导出高分辨率图片",
                         base + ".png", "PNG (*.png)")
        if not p:
            return
        try:
            dpi = float(self._dpi_edit.text())
        except ValueError:
            dpi = 600.0
        dpi = max(50.0, min(dpi, 2400.0))
        # 透明背景：导出时临时把背景 alpha 设为 0，导出后恢复（参照 IboView）
        restore_bg = None
        if self._transparent_chk.isChecked() and self.glw is not None:
            r, g, b, _ = self._bg_rgba
            restore_bg = self._bg_rgba
            self.glw.set_background((r, g, b, 0.0))
        try:
            self.glw.export_image(p, dpi=dpi)
        finally:
            if restore_bg is not None and self.glw is not None:
                self.glw.set_background(restore_bg)

    # ── 拖放 ───────────────────────────────────────────────────
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            for u in e.mimeData().urls():
                if u.toLocalFile().lower().endswith(('.cub', '.cube')):
                    e.acceptProposedAction()
                    return
        e.ignore()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if p.lower().endswith(('.cub', '.cube')):
                QTimer.singleShot(0, lambda path=p: self.load_cube(path))
                e.acceptProposedAction()
                return
