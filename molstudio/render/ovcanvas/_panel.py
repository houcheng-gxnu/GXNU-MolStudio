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

────────────────────────────────────────────────────────────
授权声明（GPLv3 §5(a)(b)）
────────────────────────────────────────────────────────────
本文件是 MolStudio 的一部分，依 GNU GPLv3 发布。本文件中的若干默认值与
交互语义（等值面相对阈值 IsoThreshold、相位配色 scheme、FlipPhase、
光泽预设、景深雾化 Fade、「三光」光照通道等）参照 IboView 复刻：

    Based on IboView (Copyright (c) 2015 Gerald Knizia), GPLv3 — modified.

逐项来源与重写进度见 docs/iboview_transplant_audit.md。
注：IboView 为 GPLv3-only，本作品在仍含其代码时不得改称 "GPLv3 or later"。
────────────────────────────────────────────────────────────
"""

import os
import math
import json
import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QPushButton, QSlider, QGroupBox, QFileDialog, QMessageBox,
    QGridLayout, QCheckBox, QSizePolicy, QToolButton, QFrame, QColorDialog,
    QListView, QDialog, QSpinBox, QDoubleSpinBox, QGraphicsDropShadowEffect,
    QApplication, QLayout,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QPointF, QRectF, QRect, QSize, QPoint
from PyQt5.QtGui import (
    QDoubleValidator, QIntValidator, QColor, QRadialGradient,
    QPainter, QPen, QBrush, QPainterPath, QRegion,
)

from ._glwidget import (
    CubGLWidget, STYLE_NAMES, STYLE_DISPLAY, _RENDER_DEFAULTS,
    MOL_STYLE_NAMES, MOL_STYLE_DISPLAY, _ensure_pyopengl,
    _GLOSS_DEFAULT, _CPK_COLORS, GlMesh, _MATCAP_NAMES,
    # VESTA 元素配色表（_glwidget 里已带"取不到就退化成空表"的兜底，
    # 见 vesta_colors.py；一键样式 VESTA 要靠它写元素覆盖色）
    _VESTA_COLORS as _VESTA_ELEM_COLORS,
    # 导出图片格式支持（PNG / JPG / TIFF / SVG）
    EXPORT_FORMATS, export_dialog_filter, export_ext_for,
    export_ext_from_path, export_ext_from_filter, export_ensure_suffix,
    export_format_supports_alpha,
)
from molstudio.ui.file_dialogs import open_file, save_file
from molstudio.core.marching_cubes import read_cube, relative_iso_threshold, IsoSurface
from ._colorwheel import ColorWheelWidget
from ._looks import (LOOK_ITEMS, LOOK_ORDER, LOOK_PRESETS, look_items,
                     look_state, look_tip)
import molstudio.core.i18n as i18n

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
    "镜面模型:": "Spec model:",
    "GGX 微表面": "GGX microsurface",
    "Blinn-Phong 经典": "Blinn-Phong classic",
    "Clear-coat 清漆": "Clear-coat",
    "Matcap 材质球": "Matcap",
    "材质球预设:": "Matcap preset:",
    "柔和影棚": "Soft studio",
    "亮面塑料": "Glossy plastic",
    "哑光陶瓷": "Matte ceramic",
    "金属": "Metal",
    "次表面散射:": "SSS:",
    "半球环境光:": "Hemisphere:",
    "天顶/地面色:": "Sky/ground:",
    "天顶色": "Sky",
    "地面色": "Ground",
    "天顶色:": "Sky:",
    "地面色:": "Ground:",
    "明暗柔和度:": "Soft terminator:",
    "背面调暗:": "Back dim:",
    "粗糙度:": "Roughness:",
    "清漆粗糙度:": "Coat roughness:",
    "清漆强度:": "Coat strength:",
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
    "包裹": "Wrap",
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
    # 化学键样式对话框：多重键（双/三键）/ 离域键
    "多重键（双键 / 三键 / 离域键）":
        "Multiple bonds (double / triple / delocalized)",
    "先用左键选中两个原子 → 画布右键 → 「设为双键 / 设为三键 / 设为离域键」":
        "Select two atoms with the left button, then right-click the canvas "
        "→ \"Set as double / triple / delocalized bond\"",
    "子键粗细:": "Sub-bond width:",
    "线间距:": "Line spacing:",
    # 成键模式（两类）
    "成键模式:": "Bonding mode:",
    "一律单键": "All single bonds",
    "按键长自动判定键型": "Auto bond order from length",
    # 虚线样式
    "虚线样式": "Dashed-bond style",
    "小圆球点阵（细点，读作部分键）": "Dot string (fine dots, reads as a partial bond)",
    "短圆柱段（一段段排开，真虚线）":
        "Short cylinders (row of dashes, a true dashed line)",
    "「虚线大小」在点阵样式下缩放点的半径、在短圆柱段样式下缩放段的粗细":
        "\"Dash size\" scales the dot radius (dots style) or the segment "
        "thickness (short-cylinder style)",
    "启用": "Enable",
    "描边粗细:": "Outline width:",
    "背景色:": "Background:",
    "选择…": "Pick…",
    "景深雾化": "Depth fade",
    "后处理抗锯齿": "Post AA",
    "线性空间光照": "Linear light",
    "边缘暗化:": "Edge darken:",
    "阴影宽度:": "Shadow width:",
    "环境光遮蔽:": "Ambient occlusion:",
    "色调映射:": "Tone mapping:",
    "暗角:": "Vignette:",
    "AO 半径:": "AO radius:",
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
    # 参数区顶部固定条
    "全部展开": "Expand all",
    "全部折叠": "Collapse all",
    # 参数区分节标题
    "等值面": "Isosurface",
    "相位与配色": "Phases & colors",
    "光照与材质": "Lighting & material",
    "原子与键": "Atoms & bonds",
    "背景与后处理": "Background & post",
    "vdW 外壳": "vdW shell",
    # 测量（距离 / 键角 / 二面角）
    "测量": "Measure",
    "距离": "Distance",
    "键角": "Angle",
    "二面角": "Dihedral",
    # 导出图片格式下拉（下拉条目本身是 PNG/JPG/TIFF/SVG，中英一致，无需翻译）
}

# 「导出图片」格式下拉项：(扩展名, 下拉里显示的短名)
# 短名放下拉框里（选框窄、一眼看清选的是哪种），四种格式的差异走下拉框 tooltip。
_EXPORT_MENU_ITEMS = (
    ("png", "PNG"),
    ("jpg", "JPG"),
    ("tif", "TIFF"),
    ("svg", "SVG"),
)


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

# 每个"一键样式"字典都是一份**全量状态**（等价于一次 get_style_state() 导出），
# 所以统一带上下面这几项 —— 它们的含义是"本样式不指定"，套用时会把上一套样式
# 留在画布上的对应状态**清掉**：
#   · element_colors：元素级覆盖色。apply_style_state() 对缺失键是"保持当前
#     值"，而这个键是**字典**，不显式写空就会黏住 —— 实测"先点 VESTA 再点
#     MolStudio"，原子会继续用 VESTA 配色，看着像按钮失灵。
#   · bond_color / bond_gloss / bond_diffuse：统一键色三件套。VESTA 的键是
#     "按元素分双色"是各样式的默认，显式写 None 才能把上一套可能设过的统一
#     键色清掉（用户可以在「化学键」对话框里把键设成单一颜色）。
# 各预设用 `{**_STYLE_NEUTRAL, ...}` 展开，避免 7 份字典各抄一遍。
_STYLE_NEUTRAL = {
    "element_colors": {},
    "bond_color": None,
    "bond_gloss": None,
    "bond_diffuse": 0.8,
}

# sob-art 一键样式：光照信息（导出自 light_style3.json，4 灯）
# sob-art 的光照（仅灯光：方向 / 数量 / 光晕）。IQmol 一键样式复用它。
_SOBART_LIGHT = {
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

# 默认样式「sob-art」（导出自 sob-art.json 的**全量**状态，2026-09 更新）：
# SobArt 原子配色 / 四灯（glow 0.1）/ Blinn-Phong 镜面模型 / 光泽 0.77 /
# 次表面散射 0.3 / 等值面透明度 0.7（orb_opacity 0.30）/ 原子描边 0.35 /
# 白底 / 关景深雾化。改这里的数值即改「一键样式 → sob-art」的效果。
_SOBART_STYLE = {**_STYLE_NEUTRAL,
    "mol_style":       'SobArt',
    "gradient":        '',
    "gloss":           0.77,
    "light_count":     4,
    "light_dirs":      [[0.373134328358209, 0.5373134328358209, 0.7563498184668613],
                        [-0.2835820895522388, -0.6865671641791045, 0.6694824325971882],
                        [0.05970149253731343, -0.014925373134328358, 0.9981046864059993],
                        [-0.5522388059701493, 0.5373134328358209, 0.6374375075839588]],
    "light_glow":      0.1,
    "light_glows":     [0.88, 0.88, 0.88, 0.1],
    "atom_scale":      1.5,
    "bond_scale":      2.0,
    "multi_bond":      [1.0, 3.0],
    "dash_style":      'dots',
    "bond_mode":       'single',
    "atom_outline":    [True, [0.0, 0.0, 0.0], 0.35],
    "orb_outline":     [False, [0.0, 0.0, 0.0], 0.2],
    "orb_opacity":     0.30,
    "phase_pos":       [0.6, 0.9, 0.5],
    "phase_neg":       [0.0, 0.7, 0.9],
    "bg":              [1.0, 1.0, 1.0, 1.0],
    "crosshair":       False,
    "fade":            False,
    "fog_strength":    0.6,
    "shader_regs":     {'atom': [0.85, 0.7, 0.77, -0.5],
                        'orb': [0.85, 0.6, 0.385, 1.0]},
    "style_regs":      None,
    "post":            [True, 1.5, 0.0, 2.0, 0.0, 0.0, 0.0, 8.0, 0.03],
    "carbon":          None,
    "hydrogen":        None,
    "hide_hydrogens":  False,
    "keep_h_atoms":    [],
    "atom_labels":     2,
    "spec_model":      0,
    "matcap":          'studio',
    "roughness":       0.45,
    "coat_roughness":  0.1,
    "coat_strength":   0.8,
    "sss_strength":    0.3,
    "soft_term":       0.0,
    "hemi_enabled":    True,
    "hemi_top":        [0.18, 0.18, 0.18],
    "hemi_bottom":     [0.035, 0.035, 0.035],
    "hemi_intensity":  0.25,
    "bg_grad":         None,
}

# 默认样式「HoukMol」（导出自 HoukMol.json，单光 gau_default，默认不显示十字圆环）
_HOUKMOL_STYLE = {**_STYLE_NEUTRAL,
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
_IQMOL_STYLE = {**_STYLE_NEUTRAL,
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
    "fade": False,
    "carbon": None,
    "hydrogen": None,
}

# 一键样式「IBOview」（2026-09-05 同步自 IBOview.json：CPK / 三光 Phong /
# 白底 / 相位紫-蓝 / **Blinn-Phong** 镜面模型）。
# 全量状态（get_style_state 导出），含相位色、灯光方向与全部材质参数。
# 2026-09-20 按反馈调整：光泽 0.1（面板 10%）、等值面透明度 50%；
# 并补上样式自带的着色寄存器基准（见下方 style_regs 注释）。
_IBOVIEW_STYLE = {**_STYLE_NEUTRAL,
    "mol_style": "CPK",
    "gradient": "",
    # 光泽 0.1（面板 10%）。IBOview 是"自带寄存器基准"的样式，滑块在这个
    # 基准上做倍率（k = gloss / 0.06），故 0.1 ≈ 原版高光的 1.67 倍 ——
    # 观感接近 IboView 原版高光（基准 0.118 时是 1.97 倍）。
    "gloss": 0.1,
    # 必须是 iboview-purple-blue 的 gl_regs：处理器里先 set_style() 建立
    # 这个基准，再把状态套上去。这里**显式写下来**，否则一旦从别的等值面
    # 样式切过来（或走"载入样式"），基准会被当成"该样式没有自带基准"而清掉，
    # 光泽落到通用映射上，等值面会变得又平又白（实测差 5556 px）。
    "style_regs": {"atom": [0.8, 0.7, 0.4, -0.5],
                   "orb": [0.8, 0.7, 0.7, -0.5]},
    "light_count": 3,
    "light_dirs": [
        [0.5, 0.5, 0.7071],
        [-0.4, -0.35, 0.847],
        [0.45, -0.3, 0.841],
        [0.0, 0.0, 1.0],
    ],
    "light_glow": 1.0,
    "light_glows": [1.0, 1.0, 1.0, 1.0],
    "atom_scale": 1.5,
    "bond_scale": 2.0,
    "atom_outline": [False, [0.0, 0.0, 0.0], 0.35],
    "orb_outline": [False, [0.0, 0.0, 0.0], 0.2],
    "orb_opacity": 0.5,      # 等值面透明度 50%（面板滑块值）
    "phase_pos": [0.6745098039215687, 0.4, 1.0],
    "phase_neg": [0.4, 0.6235294117647059, 1.0],
    "bg": [1.0, 1.0, 1.0, 1.0],
    "crosshair": False,
    "fade": False,
    "carbon": None,
    "hydrogen": None,
    "hide_hydrogens": False,
    "keep_h_atoms": [],
    "atom_labels": 2,
    # ── 材质参数（2026-09-05 同步自 IBOview.json，原先缺失）──
    "spec_model": 0,          # Blinn-Phong（非 GGX）
    "matcap": "studio",
    "roughness": 0.45,
    "coat_roughness": 0.1,
    "coat_strength": 0.8,
    "sss_strength": 0.0,
    "soft_term": 0.0,
    "hemi_enabled": True,
    "hemi_top": [0.18, 0.18, 0.18],
    "hemi_bottom": [0.035, 0.035, 0.035],
    "hemi_intensity": 0.25,
    "bg_grad": None,
}

# 一键样式「MolStudio」（导出自 MolStudio.json，2026-09-05）。
# 这是用当前 get_style_state() **全量导出**的完整状态，因此除传统项外还含
# 镜面模型、粗糙度/清漆、次表面、明暗柔和度、半球环境光等全部材质参数。
# 观感：GaussView 原子配色 / 单光源 / 白底 / 原子描边 0.35（黑）/
#       等值面完全不透明 / 相位白-绿。
_MOLSTUDIO_STYLE = {**_STYLE_NEUTRAL,
    "mol_style": "GaussView",
    "gradient": "",
    "gloss": 0.13,
    "light_count": 1,
    "light_dirs": [
        [0.0, -0.04477611940298507, 0.9989970466078514],
        [-0.2835820895522388, -0.6865671641791045, 0.6694824325971882],
        [0.05970149253731343, -0.014925373134328358, 0.9981046864059993],
        [-0.5522388059701493, 0.5373134328358209, 0.6374375075839588],
    ],
    "light_glow": 0.1,
    "light_glows": [0.79, 0.88, 0.88, 0.1],
    "atom_scale": 1.5,
    "bond_scale": 2.0,
    "atom_outline": [False, [0.0, 0.0, 0.0], 0.35],
    "orb_outline": [False, [0.0, 0.0, 0.0], 0.2],
    "orb_opacity": 1,
    # 等值面 alpha 不被光照调制（0）：本样式默认就是"完全不透明"，
    # 透明度滑块因此全程线性 —— 0% 全实、50% 半透、100% 全透。
    # 若取 1（IboView 调制），滑块一离开 0% 就会从全实跳到 0.6~0.8 的
    # 半透明，中间没有过渡（用户 2026-09 反馈的"突然变透明"）。
    "orb_alpha_mod": 0,
    "phase_pos": [0.95, 0.95, 0.95],
    "phase_neg": [0.5, 0.9, 0.1],
    "bg": [1.0, 1.0, 1.0, 1.0],
    "crosshair": False,
    "fade": False,
    "carbon": None,
    "hydrogen": None,
    "hide_hydrogens": False,
    "keep_h_atoms": [],
    "atom_labels": 2,
    "spec_model": 1,
    "matcap": "studio",
    "roughness": 0.45,
    "coat_roughness": 0.1,
    "coat_strength": 0.8,
    "sss_strength": 0.0,
    "soft_term": 0.0,
    "hemi_enabled": True,
    "hemi_top": [0.18, 0.18, 0.18],
    "hemi_bottom": [0.035, 0.035, 0.035],
    "hemi_intensity": 0.25,
    "bg_grad": None,
}

# 一键样式「VESTA」（2026-09-25）。
# 基底就是上面的 MolStudio（同一套几何/光照/材质），**只换配色**：
#   · 原子球：原子配色轴切到 "VESTA" —— 逐元素用 VESTA 自己的 elements.ini
#     配色（95 个元素，见 vesta_colors.py；数值直接从 VESTA 安装目录取）
#   · 化学键：**不做任何特殊处理** —— VESTA 默认画法是它手册里的
#     "Bicolor cylinder"（一根键用两端原子各自的颜色，各占一半），
#     和 MolStudio 一样，所以这里 bond_color 保持 _STYLE_NEUTRAL 的 None。
#     （style.ini 的 BONDP 里那三个 127 是"Unicolor cylinder / Color line"
#      那几种画法用的颜色，默认画法用不到 —— 这条一开始判断错了，
#      是用户指出来的，已按实际画法改正。）
#   · 背景：白 —— VESTA 默认 BKGRC = 255,255,255，MolStudio 本来就是白底
# 刻意不动几何：VESTA 的球偏小（默认 24%）、键偏细（0.25 Å），而本样式按
# 需求"基于 MolStudio 那个一键样式"，所以半径/粗细沿用 MolStudio。
_VESTA_STYLE = dict(_MOLSTUDIO_STYLE)
_VESTA_STYLE.update({
    # ① 原子配色轴切成 VESTA：这是"派生"配色，换回别的样式自动跟着换，
    #    而且画布下方的「原子配色」下拉会显示 VESTA，可以单独选它。
    "mol_style": "VESTA",
    # ② 同时把 95 个元素的色**显式**写成覆盖表。两份数据同源（都取自
    #    vesta_colors.py），看似重复，但「同步到VMD」那条链路只认
    #    _element_color_overrides，不认 mol_style —— 不写这一步，
    #    画布是 VESTA 配色、VMD 里还是 GaussView 配色，两边对不上。
    "element_colors": {str(int(z)): [float(c) for c in rgb]
                       for z, rgb in _VESTA_ELEM_COLORS.items()},
    # ③ 光照/材质：用户在成品里调出来的一版，导出的样式状态见
    #    C:\Users\Administrator\Desktop\xtb-test\VESTA.json（2026-09-25）。
    #    相对 MolStudio 基底只动了下面 6 处 —— 其余键他没改，
    #    导出里那些多的键是"完整状态"自带的默认值，不并进来（保持与其它
    #    一键样式同一套写法，也免得把用户的 vdW / 元素半径设置一并清掉）。
    "light_glows": [3.0, 0.88, 0.88, 0.1],   # 灯 0 光晕 0.79 → 3.0（拉满）
    "spec_model": 2,                           # 镜面模型 1 → 2
    "roughness": 0.55,                         # 0.45 → 0.55
    "coat_roughness": 0.15,                    # 0.10 → 0.15
    "coat_strength": 1.78,                     # 0.80 → 1.78（清漆加强）
    # 景深雾化：他导出的 VESTA.json 里是**开着**的（fade=true），但本项目有一条
    # 明文规则 —— 「一键样式一律不打开景深雾化」（见 _glwidget.reset_molviewer_style
    # 的注释；_oneclick_style_probe.py 会强制检查"点任何一键样式后雾化必须是关的"）。
    # 所以这里按规则压回关闭，fog_strength 仍记他那个值（0.6，也是渲染默认值）。
    # 想恢复成"VESTA 带雾化"，把 fade 改 True 即可，同时得松掉那条规则的判定。
    "fade": False,
    "fog_strength": 0.6,
    # 键收腰 0.70（BOND_THINNING_DEFAULT）→ 1.00：直圆柱不收腰，与 VESTA 的
    # 键一致（VESTA 的 stick 就是等径圆柱）
    "bond_thinning": 1.0,
    # 着色寄存器：取他导出里的显式值（原子那组与 MolStudio 相同，等值面那组
    # 不同）。**必须配一条 style_regs: None** —— 按 apply_style_state() 的规则，
    # 声明了 shader_regs（dict）就不会自动清 _style_regs，不显式写空会让上一个
    # IboView 样式留下的基准继续参与 gloss 换算（_SOBART_STYLE 也是这么写的）。
    # 等值面寄存器：漫反射强度 0.12 → 0.70（2026-09-27）。
    #   0.12 这组来自用户导出的 VESTA.json，是**配合旧的 alpha 公式**用的：
    #   旧公式里 alpha ∝ 漫反射强度（alpha = Σ intensity·DiffStr·pow(NdotL,·)），
    #   把 DiffStr 压到 0.12 就等于"让等值面更透"，代价是颜色也被同步压暗。
    #   现在本样式的 alpha 由透明度滑块线性决定（orb_alpha_mod=0），DiffStr 只剩
    #   "颜色亮度"一个作用 —— 继续用 0.12 会把正黄/负蓝渲染成暗橄榄/暗藏青
    #   （实测中位色 #737347 / #333360），与 VESTA 里那种明亮的浅黄/浅蓝不符。
    #   抬到 0.70 后实测 黄 #FFFF47 / 蓝 #3838FF（p90 亮度 215 / 198），
    #   与 VESTA 官方插图取样（黄 #C7C640 受光 #E6E69E、蓝 #0F53FF 受光 #17A5FF）
    #   观感一致；镜面/锐度两项保持用户导出值不动。
    "shader_regs": {"atom": [0.85, 0.7, 0.13, -0.5],
                    "orb": [0.85, 0.70, 0.065, 0.82]},
    "style_regs": None,
    # ④ 等值面配色 / 光照 / 透明合成：**整组取自用户导出的 VESTA.json**
    #    （C:\Users\Administrator\Desktop\DEMO\VESTA.json，2026-09-27），
    #    不再用本项目先前那套"照手册推"的值。逐项对应：
    #      · style_name    "ultra-glass"（等值面材质风格，也是面板默认）
    #      · phase_pos     [0,1,1] 青  = 正相位
    #      · phase_neg     [1,1,0] 黄  = 负相位
    #      · orb_opacity   0.2（80% 透明，VESTA 里那种很浅的面）
    #      · orb_alpha_mod 0 → 透明度滑块线性控制 alpha（不叠光照调制）
    #      · transparency_mode "oit" + oit_falloff 11.9：WBOIT 加权混合
    #        与其深度前倾系数（导出时用户正用这套，半透明面观感与它绑定）
    #    注：VESTA 手册（Objects → Properties → Isosurfaces）写的是
    #    "Yellow and blue surfaces show positive and negative values"，
    #    即黄=正、蓝=负；用户这份导出是"青=正、黄=负"。本样式照导出值设置，
    #    需要按手册口径对调时，把 phase_pos / phase_neg 互换即可（一行）。
    "style_name": "ultra-glass",
    "phase_pos": [0.0, 1.0, 1.0],      # 正相位：青
    "phase_neg": [1.0, 1.0, 0.0],      # 负相位：黄
    "orb_opacity": 0.2,
    "transparency_mode": "oit",
    "oit_falloff": 11.9,
})

# 一键样式「CYLview」（MolStudio 的变体，2026-09-20）。
# 与 MolStudio 完全同源，按 CYLview 观感改这几处：
#   · 景深雾化关闭（fade=False → u_FogWidth=0，物体不向背景淡出）
#   · 原子描边关闭（atom_outline on=False）
#   · 原子半径 1.8（MolStudio 为 1.5）
#   · 化学键半径 3.79（MolStudio 为 2.0）
#   · 氢原子球半径跟随键半径（h_bond_radius=True）→ H 与键一样粗
#   · 单光源方向与光晕按 light_style.json（光晕 0.5；MolStudio 为 0.1）
#   · 等值面：正相位蓝 / 负相位黄（纯色），材质与透明合成按用户导出的
#     CYLVIEW.json（2026-09-27）—— 详见下方 ④ 段注释
_CYLVVIEW_STYLE = {**_STYLE_NEUTRAL,
    "mol_style": "GaussView",
    "gradient": "",
    "gloss": 0.13,
    "light_count": 1,
    "light_dirs": [
        [-0.26865671641791045, 0.26865671641791045, 0.925011966110219],
        [-0.2835820895522388, -0.6865671641791045, 0.6694824325971882],
        [0.05970149253731343, -0.014925373134328358, 0.9981046864059993],
        [-0.5522388059701493, 0.5373134328358209, 0.6374375075839588],
    ],
    "light_glow": 0.5,
    "light_glows": [0.5, 0.5, 0.5, 0.5],
    "atom_scale": 1.8,
    "bond_scale": 3.79,
    "h_bond_radius": True,
    "atom_outline": [False, [0.0, 0.0, 0.0], 0.35],
    "orb_outline": [False, [0.0, 0.0, 0.0], 0.2],
    "orb_opacity": 1,
    # ── 等值面配色 / 材质 / 透明合成：取自用户导出的 CYLVIEW.json ──
    #    （C:\Users\Administrator\Desktop\NBO\CYLVIEW.json，2026-09-27）
    #    · phase_pos [0,0,1] 纯蓝 = 正相位；phase_neg [1,1,0] 纯黄 = 负相位
    #      （此前用 MolStudio 的"近白 / 绿"，现按用户为 CYLview 定的配色；
    #       与 VESTA 样式是同一套"纯蓝 + 纯黄"观感，但 VESTA 那边正相位用青）
    #    · orb_opacity 1 + orb_alpha_mod 0：默认全不透明，透明度滑块线性
    #    · style_name "ultra-glass" + shader_regs（orb 漫反射 0.70）：
    #      必须同时写 style_regs: None —— 声明了 shader_regs 却不显式清基准，
    #      上一个 IboView 样式留下的基准会继续参与 gloss 换算
    #    · transparency_mode "oit" + oit_falloff 11.9：WBOIT 加权混合与其深度
    #      前倾系数（导出时用户正用这套，半透明面观感与它绑定）
    "orb_alpha_mod": 0,
    "style_name": "ultra-glass",
    "shader_regs": {"atom": [0.85, 0.7, 0.13, -0.5],
                    "orb": [0.85, 0.70, 0.065, 0.82]},
    "style_regs": None,
    "phase_pos": [0.0, 0.0, 1.0],      # 正相位：蓝
    "phase_neg": [1.0, 1.0, 0.0],      # 负相位：黄
    "transparency_mode": "oit",
    "oit_falloff": 11.9,
    # 键不收腰（直圆柱，默认 0.70 → 1.0）。导出里还有 post / back_dim /
    # fog_strength / multi_bond / dash_style / bond_mode 六项，值与项目默认
    # 完全相同（MolStudio 字典也不写），照旧走默认、不进字典，免得样式字典里
    # 堆一堆"等于默认值"的重复项。
    "bond_thinning": 1.0,
    "bg": [1.0, 1.0, 1.0, 1.0],
    "crosshair": False,
    "fade": False,
    "carbon": None,
    "hydrogen": None,
    "hide_hydrogens": False,
    "keep_h_atoms": [],
    "atom_labels": 2,
    "spec_model": 1,
    "matcap": "studio",
    "roughness": 0.45,
    "coat_roughness": 0.1,
    "coat_strength": 0.8,
    "sss_strength": 0.0,
    "soft_term": 0.0,
    "hemi_enabled": True,
    "hemi_top": [0.18, 0.18, 0.18],
    "hemi_bottom": [0.035, 0.035, 0.035],
    "hemi_intensity": 0.25,
    "bg_grad": None,
}

# 一键样式「HoukMol3d」（导出自 HoukMol-3d.json，2026-09-05）。
# 全量状态（get_style_state 导出）。与旧「HoukMol」是两套独立样式：
# 本套用 Clear-coat 镜面模型（清漆粗糙度 0.97）+ 次表面散射 0.32，
# 等值面半透明 0.48、四光源、相位白-绿。
# 观感：HoukMol 原子配色 / 白底 / 原子描边 0.35（黑）。
# 注：不套 _HOUKMOL_RING —— 圆环不在 get_style_state 的导出范围内，
# 按「还原 JSON 描述的状态」原则，保持用户当前圆环设置不变。
_HOUKMOL3D_STYLE = {**_STYLE_NEUTRAL,
    "mol_style": "HoukMol",
    "gradient": "",
    "gloss": 0.17,
    "light_count": 4,
    "light_dirs": [
        [0.34328358208955223, 0.3283582089552239, 0.8799643565960403],
        [-0.5373134328358209, -0.3582089552238806, 0.7635316753688753],
        [0.3582089552238806, -0.3283582089552239, 0.8739949834004389],
        [-0.5223880597014925, 0.2835820895522388, 0.8041715697327878],
    ],
    "light_glow": 0.1,
    "light_glows": [0.88, 0.88, 0.88, 0.1],
    "atom_scale": 1.5,
    "bond_scale": 2.0,
    "atom_outline": [False, [0.0, 0.0, 0.0], 0.35],
    "orb_outline": [False, [0.0, 0.0, 0.0], 0.2],
    "orb_opacity": 0.48,
    "phase_pos": [0.95, 0.95, 0.95],
    "phase_neg": [0.5, 0.9, 0.1],
    "bg": [1.0, 1.0, 1.0, 1.0],
    "crosshair": False,
    "fade": False,
    "carbon": None,
    "hydrogen": None,
    "hide_hydrogens": False,
    "keep_h_atoms": [],
    "atom_labels": 2,
    "spec_model": 2,          # Clear-coat 清漆
    "matcap": "studio",
    "roughness": 0.45,
    "coat_roughness": 0.97,
    "coat_strength": 0.8,
    "sss_strength": 0.32,     # 次表面散射
    "soft_term": 0.0,
    "hemi_enabled": True,
    "hemi_top": [0.18, 0.18, 0.18],
    "hemi_bottom": [0.035, 0.035, 0.035],
    "hemi_intensity": 0.25,
    "bg_grad": None,
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


class ElementRadiiDialog(QDialog):
    """按元素调节原子球半径倍率（0.2–4.0），实时生效。

    作用于 glw 的按元素倍率表（_elem_r_mult）：
        显示半径 = 默认表半径 × ATOM_DRAW_SCALE × 全局原子半径 × 倍率
    只影响画布中该元素原子球的显示大小；坐标为 Bohr 不变，键长/键型判定
    不受影响。元素清单来自当前载入结构（分子或 cube 头）。
    """

    def __init__(self, glw, parent=None):
        super().__init__(parent)
        self._glw = glw
        self._spins = {}
        self.setWindowTitle("元素半径调节")
        self.setModal(True)

        lay = QVBoxLayout(self)
        tip = QLabel("原子球显示半径 = 默认表半径 × 全局原子半径 × 倍率。\n"
                     "倍率只改变该元素原子球的大小，不改坐标与键判定；设为 1.00 恢复默认。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#666;")
        lay.addWidget(tip)

        els = glw.present_elements() if glw is not None else []
        if not els:
            lay.addWidget(QLabel("当前未载入含原子的结构（fchk / xyz / cube）。"))
        else:
            grid = QGridLayout()
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(4)
            for row, z in enumerate(els):
                sym = _ELEM_SYMBOLS.get(z, "?")
                cname = _ELEM_NAMES.get(z, "")
                lab = QLabel(f"{sym}  {cname}  (Z={z})" if cname
                             else f"{sym}  (Z={z})")
                grid.addWidget(lab, row, 0)
                sp = QDoubleSpinBox()
                sp.setRange(0.2, 4.0)
                sp.setSingleStep(0.05)
                sp.setDecimals(2)
                sp.setValue(glw.element_radius(z))
                sp.setToolTip(f"Z={z}（{sym}）原子球半径倍率，1.00 = 默认")
                sp.valueChanged.connect(
                    lambda v, zz=z: self._glw.set_element_radius(zz, v))
                grid.addWidget(sp, row, 1)
                self._spins[z] = sp
            lay.addLayout(grid)
            # 样式把氢原子球锁成"与键一样粗"时，氢的倍率栏其实不生效 ——
            # 说清楚，免得调了没反应（显式改动氢的倍率会覆盖该样式规则）。
            try:
                h_locked = bool(glw.hydrogen_bond_radius()) and 1 in self._spins
            except Exception:
                h_locked = False
            if h_locked:
                note = QLabel("注：当前样式下氢原子球半径跟随化学键半径（H 与键一样粗），"
                              "氢的倍率暂不生效；在这里改动氢的倍率即覆盖该样式规则。")
                note.setWordWrap(True)
                note.setStyleSheet("color:#8a6d3b;")
                lay.addWidget(note)

        btns = QHBoxLayout()
        reset_btn = QPushButton("全部恢复默认")
        reset_btn.setObjectName("SmallBtn")
        reset_btn.clicked.connect(self._on_reset_all)
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("SmallBtn")
        close_btn.clicked.connect(self.accept)
        btns.addWidget(reset_btn)
        btns.addStretch(1)
        btns.addWidget(close_btn)
        lay.addLayout(btns)

    def _on_reset_all(self):
        if self._glw is not None:
            self._glw.reset_element_radii()
        for z, sp in self._spins.items():
            sp.blockSignals(True)
            sp.setValue(1.0)
            sp.blockSignals(False)


class BondStyleDialog(QDialog):
    """调节化学键颜色与材质（光泽 / 面亮度）+ 多重键几何，实时生效。

    颜色写入 glw._bond_color（几何顶点色，重建分子模型）；
    光泽 / 面亮度是渲染期 uniform（键重绘趟），即改即见。
    多重键（双键/三键）由画布右键菜单逐键指定，这里只调它的几何参数
    （子键粗细、线间距），改完立即重建分子网格。
    """

    def __init__(self, glw, parent=None):
        super().__init__(parent)
        self._glw = glw
        self._custom_rgb = (0.35, 0.35, 0.85)
        self.setWindowTitle("化学键样式")
        self.setModal(True)
        lay = QVBoxLayout(self)

        # ── 颜色 ──
        cg = QGroupBox("颜色")
        cv = QVBoxLayout(cg)
        self._color_cb = QComboBox()
        self._color_cb.addItem("跟随分子风格（两端半元素色）", None)
        self._color_cb.addItem("统一黑色", (0.0, 0.0, 0.0))
        self._color_cb.addItem("统一白色", (1.0, 1.0, 1.0))
        self._color_cb.addItem("统一灰色", (0.5, 0.5, 0.5))
        self._color_cb.addItem("自定义颜色…", "custom")
        self._color_cb.currentIndexChanged.connect(self._on_color_mode)
        cv.addWidget(self._color_cb)
        self._color_btn = QPushButton()
        self._color_btn.setFixedSize(40, 22)
        self._color_btn.setEnabled(False)
        self._color_btn.clicked.connect(self._pick_custom_color)
        cv.addWidget(self._color_btn, alignment=Qt.AlignLeft)
        lay.addWidget(cg)

        # ── 材质 ──
        mg = QGroupBox("材质")
        mv = QVBoxLayout(mg)
        self._follow_chk = QCheckBox("光泽跟随全局光泽滑块")
        self._follow_chk.toggled.connect(self._on_follow_toggled)
        mv.addWidget(self._follow_chk)
        g_row = QHBoxLayout()
        g_row.addWidget(QLabel("光泽:"))
        self._gloss_sld = QSlider(Qt.Horizontal)
        self._gloss_sld.setRange(0, 100)
        self._gloss_sld.setValue(50)
        self._gloss_sld.valueChanged.connect(self._on_gloss)
        g_row.addWidget(self._gloss_sld, 1)
        self._gloss_val = QLabel("0.50")
        self._gloss_val.setMinimumWidth(36)
        g_row.addWidget(self._gloss_val)
        mv.addLayout(g_row)
        d_row = QHBoxLayout()
        d_row.addWidget(QLabel("面亮度:"))
        self._diffuse_sld = QSlider(Qt.Horizontal)
        self._diffuse_sld.setRange(20, 160)     # 0.20 .. 1.60
        self._diffuse_sld.setValue(80)          # 默认 0.80
        self._diffuse_sld.valueChanged.connect(self._on_diffuse)
        d_row.addWidget(self._diffuse_sld, 1)
        self._diffuse_val = QLabel("0.80")
        self._diffuse_val.setMinimumWidth(36)
        d_row.addWidget(self._diffuse_val)
        mv.addLayout(d_row)
        lay.addWidget(mg)

        # ── 虚线样式：点阵（小圆球）/ 短圆柱段（真虚线）──
        dsg = QGroupBox(_cv("虚线样式"))
        dsv = QVBoxLayout(dsg)
        self._dash_style_cb = QComboBox()
        self._dash_style_cb.addItem(_cv("小圆球点阵（细点，读作部分键）"),
                                    "dots")
        self._dash_style_cb.addItem(_cv("短圆柱段（一段段排开，真虚线）"),
                                    "dashes")
        self._dash_style_cb.setToolTip(
            "虚线键的画法，同时作用于离域键里的那根虚线；\n"
            "大小与间距用画布面板的「虚线大小 / 虚线间隔」调节")
        self._dash_style_cb.currentIndexChanged.connect(self._on_dash_style)
        dsv.addWidget(self._dash_style_cb)
        self._ds_tip = QLabel()
        self._ds_tip.setText(_cv("「虚线大小」在点阵样式下缩放点的半径、"
                                 "在短圆柱段样式下缩放段的粗细"))
        self._ds_tip.setStyleSheet("color:#64748B; font-size:9pt;")
        self._ds_tip.setWordWrap(True)
        dsv.addWidget(self._ds_tip)
        lay.addWidget(dsg)

        # ── 多重键（双键 / 三键 / 离域键）：逐键由画布右键菜单指定，
        #    这里调几何参数 ──
        mbg = QGroupBox(_cv("多重键（双键 / 三键 / 离域键）"))
        mbv = QVBoxLayout(mbg)
        self._mb_tip = QLabel()
        self._mb_tip.setText(_cv("先用左键选中两个原子 → 画布右键 → "
                                 "「设为双键 / 设为三键 / 设为离域键」"))
        self._mb_tip.setStyleSheet("color:#64748B; font-size:9pt;")
        self._mb_tip.setWordWrap(True)
        mbv.addWidget(self._mb_tip)

        mb_r_row = QHBoxLayout()
        self._mb_r_lbl = QLabel()
        self._mb_r_lbl.setText(_cv("子键粗细:"))
        mb_r_row.addWidget(self._mb_r_lbl)
        self._mb_r_sld = QSlider(Qt.Horizontal)
        self._mb_r_sld.setRange(20, 100)        # 0.20 .. 1.00
        self._mb_r_sld.setValue(100)            # 默认 1.00 = 与单键等粗
        self._mb_r_sld.setToolTip(
            "每根子键的半径 / 普通单键半径（默认 1.00 = 与单键等粗；"
            "调小则双键/三键的线更细）")
        self._mb_r_sld.valueChanged.connect(self._on_multi_bond)
        mb_r_row.addWidget(self._mb_r_sld, 1)
        self._mb_r_val = QLabel("1.00")
        self._mb_r_val.setMinimumWidth(36)
        mb_r_row.addWidget(self._mb_r_val)
        mbv.addLayout(mb_r_row)

        mb_g_row = QHBoxLayout()
        self._mb_g_lbl = QLabel()
        self._mb_g_lbl.setText(_cv("线间距:"))
        mb_g_row.addWidget(self._mb_g_lbl)
        self._mb_g_sld = QSlider(Qt.Horizontal)
        self._mb_g_sld.setRange(150, 500)       # 1.50 .. 5.00
        self._mb_g_sld.setValue(300)            # 默认 3.00
        self._mb_g_sld.setToolTip(
            "相邻子键中心距 / 子键半径（默认 3.00，即两线之间留出半条线宽；"
            "须大于 2.0，否则两根等粗的子键会粘连成一根粗线）")
        self._mb_g_sld.valueChanged.connect(self._on_multi_bond)
        mb_g_row.addWidget(self._mb_g_sld, 1)
        self._mb_g_val = QLabel("3.00")
        self._mb_g_val.setMinimumWidth(36)
        mb_g_row.addWidget(self._mb_g_val)
        mbv.addLayout(mb_g_row)
        lay.addWidget(mbg)

        btns = QHBoxLayout()
        reset_btn = QPushButton("恢复默认")
        reset_btn.setObjectName("SmallBtn")
        reset_btn.clicked.connect(self._on_reset)
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("SmallBtn")
        close_btn.clicked.connect(self.accept)
        btns.addWidget(reset_btn)
        btns.addStretch(1)
        btns.addWidget(close_btn)
        lay.addLayout(btns)

        self._reload()

    # ── 状态同步 ──
    def _reload(self):
        glw = self._glw
        self._color_cb.blockSignals(True)
        bc = glw._bond_color
        if bc is None:
            idx = 0
        elif tuple(bc) in ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (0.5, 0.5, 0.5)):
            idx = self._color_cb.findData(tuple(bc))
        else:
            self._custom_rgb = tuple(bc)
            idx = self._color_cb.findData("custom")
        self._color_cb.setCurrentIndex(max(idx, 0))
        self._color_cb.blockSignals(False)
        custom = self._color_cb.currentData() == "custom"
        self._color_btn.setEnabled(custom)
        if custom:
            self._paint_swatch(self._custom_rgb)

        bg = glw._bond_gloss
        g0 = bg if bg is not None else float(getattr(glw, "_gloss", 0.5) or 0.5)
        self._follow_chk.blockSignals(True)
        self._follow_chk.setChecked(bg is None)
        self._follow_chk.blockSignals(False)
        self._gloss_sld.blockSignals(True)
        self._gloss_sld.setValue(int(round(g0 * 100)))
        self._gloss_sld.blockSignals(False)
        self._gloss_sld.setEnabled(bg is not None)
        self._gloss_val.setText(f"{g0:.2f}")

        bd = glw._bond_diffuse
        self._diffuse_sld.blockSignals(True)
        self._diffuse_sld.setValue(int(round(bd * 100)))
        self._diffuse_sld.blockSignals(False)
        self._diffuse_val.setText(f"{bd:.2f}")

        # 多重键几何参数（子键粗细 / 线间距）
        try:
            mr, mgap = glw.multi_bond_params()
        except Exception:
            mr, mgap = 1.00, 3.00
        self._mb_r_sld.blockSignals(True)
        self._mb_r_sld.setValue(int(round(mr * 100)))
        self._mb_r_sld.blockSignals(False)
        self._mb_r_val.setText(f"{mr:.2f}")
        self._mb_g_sld.blockSignals(True)
        self._mb_g_sld.setValue(int(round(mgap * 100)))
        self._mb_g_sld.blockSignals(False)
        self._mb_g_val.setText(f"{mgap:.2f}")

        # 虚线样式
        try:
            ds = glw.dash_style()
        except Exception:
            ds = "dots"
        idx = self._dash_style_cb.findData(ds)
        self._dash_style_cb.blockSignals(True)
        self._dash_style_cb.setCurrentIndex(max(idx, 0))
        self._dash_style_cb.blockSignals(False)

    def _paint_swatch(self, rgb):
        r, g, b = (int(c * 255) for c in rgb)
        self._color_btn.setStyleSheet(
            f"background:rgb({r},{g},{b}); border:1px solid #666;")

    # ── 回调 ──
    def _on_color_mode(self, idx):
        data = self._color_cb.itemData(idx)
        custom = (data == "custom")
        self._color_btn.setEnabled(custom)
        if custom:
            self._paint_swatch(self._custom_rgb)
            self._glw.set_bond_color(self._custom_rgb)
        else:
            self._glw.set_bond_color(data)

    def _pick_custom_color(self):
        r0, g0, b0 = (int(c * 255) for c in self._custom_rgb)
        col = QColorDialog.getColor(QColor(r0, g0, b0), self, "键颜色")
        if not col.isValid():
            return
        self._custom_rgb = (col.red() / 255.0, col.green() / 255.0,
                            col.blue() / 255.0)
        self._paint_swatch(self._custom_rgb)
        self._glw.set_bond_color(self._custom_rgb)

    def _on_follow_toggled(self, on):
        self._gloss_sld.setEnabled(not on)
        if on:
            self._glw.set_bond_gloss(None)
        else:
            self._glw.set_bond_gloss(self._gloss_sld.value() / 100.0)

    def _on_gloss(self, v):
        self._gloss_val.setText(f"{v / 100.0:.2f}")
        if not self._follow_chk.isChecked():
            self._glw.set_bond_gloss(v / 100.0)

    def _on_diffuse(self, v):
        self._diffuse_val.setText(f"{v / 100.0:.2f}")
        self._glw.set_bond_diffuse(v / 100.0)

    def _on_multi_bond(self, _v=None):
        """多重键几何参数（子键粗细 / 线间距）实时应用到画布。"""
        r = self._mb_r_sld.value() / 100.0
        g = self._mb_g_sld.value() / 100.0
        self._mb_r_val.setText(f"{r:.2f}")
        self._mb_g_val.setText(f"{g:.2f}")
        if self._glw is not None:
            self._glw.set_multi_bond_params(r, g)

    def _on_dash_style(self, _idx=None):
        """虚线样式（点阵 / 短圆柱段）实时应用到画布。"""
        if self._glw is None:
            return
        style = self._dash_style_cb.currentData() or "dots"
        try:
            self._glw.set_dash_style(style)
        except Exception:
            pass

    def _on_reset(self):
        if self._glw is not None:
            self._glw.reset_bond_style()
        self._reload()


class ElementColorDialog(QDialog):
    """自定义每种元素的原子颜色（覆盖默认 CPK 配色）。"""

    def __init__(self, parent, glw):
        super().__init__(parent)
        self._glw = glw
        self.setWindowTitle(_cv("元素原子颜色"))
        self.setMinimumWidth(420)

        # 收集元素：只显示当前分子实际存在的元素（按原子序数排序）；
        # 未检测到分子时兜底常用元素，避免空对话框
        present = set()
        atoms = getattr(glw, "_molecule", None)
        if not atoms and getattr(glw, "_cube", None) is not None:
            atoms = getattr(glw._cube, "atoms", None)
        if atoms:
            try:
                present = {int(a[0]) for a in atoms}
            except (TypeError, ValueError, IndexError):
                present = set()
        if present:
            self._elems = sorted(present)
        else:
            self._elems = [1, 6, 7, 8, 9, 15, 16, 17, 35, 53]

        # 当前颜色：已有元素覆盖优先，否则默认 CPK 表（_CPK_COLORS）
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
            return tuple(_CPK_COLORS[anum])
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

/* 工具条上的小按钮，压扁一点以免占高 */QWidget#CubToolBar QPushButton,
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

# ═══════════════════════════════════════════════════════════════
# 参数区（右侧「可视化」tab 里那张设置表单）自己的样式表
# ═══════════════════════════════════════════════════════════════
# 为什么不能并进 _CANVAS_QSS：主窗口会把参数面板**从画布面板里摘出来**
# （main_window: `canvas_params.setParent(None)` 再 addWidget 到右侧 tab），
# 摘出去之后它就不再是 CubCanvasPanel 的后代，画布那份样式表**再也作用不到它**。
# 实测：把规则留在 _CANVAS_QSS 里时，`#CubParamCard` 的圆角/白底一个像素都没画，
# 收紧内边距的规则也没生效（QLineEdit 的 minimumSizeHint 仍是 39px）。
# 所以这份表直接 setStyleSheet 到参数面板自己身上，随它去哪都跟着。
_PARAMS_QSS = """
QFrame#CubParams {
    background-color: #F5F6FA;
    border-top: 1px solid #CBD5E1;
}

/* 参数区里的输入框/下拉/按钮收紧内边距。
   全局主题给 QLineEdit / QPushButton 的 minimumSizeHint 是 39px（硬下限），
   而参数区是一行一个参数的设置表单：39px 行高既浪费纵向空间、又让
   "只有滑块+标签"的行（27px）和"带输入框"的行（39px）高度参差。
   收紧后各类控件的自然高度落到 ~31-33px，整个参数区才能统一到同一个行高
   （行高由 _finalize_param_grid 按实测自然高度算，见 _refit_param_metrics）。 */
QFrame#CubParams QLineEdit,
QFrame#CubParams QComboBox,
QFrame#CubParams QPushButton,
QFrame#CubParams QSpinBox {
    padding: 2px 8px;
    min-height: 18px;
}

/* 参数区顶部固定条：样式 I/O + 视图复位，不随长列表滚走 */
QWidget#CubParamTopBar {
    background-color: #FFFFFF;
    border: 1px solid #D8E0EA;
    border-radius: 8px;
}

/* 条首标题：与分节标题同色同字重，让这条读起来像"面板的头"而不是
   一块漂在顶上的白条；贴字宽度（不像表单标签列那样被撑到 129px）。 */
QLabel#CubParamTopLbl {
    color: #1565C0;
    font-weight: bold;
    font-size: 9.5pt;
    padding: 0px 1px;
}

/* 分组竖线：1×16px 的浅灰短线，只分隔不抢眼 */
QFrame#CubParamTopSep {
    background-color: #E2E8F0;
    border: none;
}

/* 「全部展开 / 全部折叠」是开关按钮：选中态必须看得出来，
   否则点下去只有文字变化、底色不动，像没生效 */
QFrame#CubParams QPushButton#SmallBtn:checked {
    background-color: #E3F2FD;
    border: 1px solid #1E88E5;
    color: #1565C0;
}

/* 分节：一张圆角矩形卡片把**标题栏和内容**一起包住
   （标题在卡片顶部，不再是卡片外面一个悬空按钮）。 */
QWidget#CubParamCard {
    background-color: #FFFFFF;
    border: 1px solid #D8E0EA;
    border-radius: 8px;
}

/* 卡片顶部的折叠标题栏：无边框透明底，只留文字与悬停底色 */
QWidget#CubParamCard QToolButton {
    background-color: transparent;
    border: none;
    border-radius: 0px;
    color: #1565C0;
    font-weight: bold;
    text-align: left;
    padding: 3px 10px;
    font-size: 9.5pt;
}
QWidget#CubParamCard QToolButton:hover {
    background-color: #F2F7FD;
    color: #0D47A1;
}
/* 展开时标题栏与内容之间给一条细分隔线（收起时不留线，免得像张空卡） */
QWidget#CubParamCard QToolButton:checked {
    border-bottom: 1px solid #EDF1F7;
}

/* 卡片内的内容区：只负责内边距，背景/边框由卡片提供 */
QWidget#CubParamSection {
    background-color: transparent;
    border: none;
}
"""


class FlowLayout(QLayout):
    """自动换行的横向布局：放不下就换行，而不是把控件压窄。

    为什么需要它 —— 画布面板在默认 1400px 窗口下只有 557px 宽，而「一键样式」
    卡片四行内容的固有宽度实测是 276 / 928 / 682 / 702px。QHBoxLayout 遇到
    装不下时会把每个控件压到 minimumSizeHint 以下，QPushButton 又不会用省略号
    截断，于是文字被直接裁掉：实测 1400px 下 **17 个控件**文字不全
    （"同步到VMD" 需要 124px 只给了 60px），1920px 下仍有 8 个一键样式按钮被裁。
    改用本布局后，各控件永远保持自己的 sizeHint（文字完整），多出来的换到下一行。

    用法同 QHBoxLayout：``lay = FlowLayout(); lay.addWidget(w)``。不要再用
    ``addStretch()`` —— 换行布局本身就左对齐，stretch 项会变成一个零宽空位。
    """

    def __init__(self, parent=None, margin=0, spacing=6):
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    # ── QLayout 必需接口 ──
    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    # ── 高度随宽度变化：换行后行数变了，卡片自然变高 ──
    def hasHeightForWidth(self):
        return True

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        """最窄也要能完整放下**最宽的那一个**控件（换行兜底）。"""
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _rows(self, avail):
        """按可用宽度贪心分行，返回 ``[[item, ...], ...]``。"""
        sp = self.spacing()
        rows, cur, used = [], [], 0
        for item in self._items:
            w = item.sizeHint().width()
            need = used + (sp if cur else 0) + w
            if cur and need > avail:
                rows.append(cur)
                cur, used = [item], w
            else:
                cur.append(item)
                used = need
        if cur:
            rows.append(cur)
        return rows

    def _layout(self, rect, test_only):
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        sp = self.spacing()
        rows = self._rows(max(1, eff.width()))
        y = eff.y()
        for r, row in enumerate(rows):
            # 行高取本行最高控件；其余控件**垂直居中**。
            # 顶端对齐是不行的：同一行里 QLabel(≈20px)、QCheckBox(≈22px)、
            # QPushButton(≈30px) 高度不同，顶对齐会让标签的文字比按钮文字高出
            # 半行，看着就是"标签和后面的内容没对齐/不在一条线上"。
            row_h = max(it.sizeHint().height() for it in row)
            x = eff.x()
            for it in row:
                hint = it.sizeHint()
                if not test_only:
                    it.setGeometry(QRect(
                        QPoint(x, y + (row_h - hint.height()) // 2), hint))
                x += hint.width() + sp
            y += row_h + (sp if r < len(rows) - 1 else 0)
        return y - rect.y() + m.bottom()

    def heightForWidth(self, width):
        m = self.contentsMargins()
        rows = self._rows(max(1, width - m.left() - m.right()))
        if not rows:
            return m.top() + m.bottom()
        h = sum(max(it.sizeHint().height() for it in row) for row in rows)
        return h + self.spacing() * (len(rows) - 1) + m.top() + m.bottom()


def _hgroup(*widgets, spacing=4):
    """把「标签 + 输入框」这类必须同行的控件打包成一个整体。

    换行布局按 item 换行，若"DPI:"与紧跟的输入框是两个独立 item，窄宽度下
    可能被拆到两行。包一层 QWidget 后它们永远同进同退。
    """
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for wd in widgets:
        lay.addWidget(wd)
    return box


def _enable_height_for_width(widget):
    """让 widget 参与「高度随宽度变化」的协商。

    换行布局的行数取决于拿到多少宽度，所以从卡片到画布面板这条链上的每个
    控件都必须在 sizePolicy 里声明 ``hasHeightForWidth``。少声明一环，父布局
    就按"只有一行"的 sizeHint 分配高度，换行出来的最后几行会被裁掉。
    """
    sp = widget.sizePolicy()
    sp.setHeightForWidth(True)
    widget.setSizePolicy(sp)
    return widget


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
        # 「一键样式」卡片的当前锁定高度（换行布局用，见 _sync_style_card_height）
        self._style_card_h = -1
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
        # 测量状态变化（模式开关 / 类型）→ 回填本样式条上的测量控件。
        # 晶体页信息条里还有一套同样的控件，两处都靠这个信号保持一致。
        self.glw.measureStateChanged.connect(self._sync_measure_ui)
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
        # 这条链上的每一环都要声明 hasHeightForWidth，否则换行后的行数
        # 不会反映到分配的高度上（详见 _enable_height_for_width）
        _enable_height_for_width(self._style_wrap)
        _enable_height_for_width(self)

        # 圆角矩形投影
        _sw_shadow = QGraphicsDropShadowEffect(self._style_wrap)
        _sw_shadow.setBlurRadius(12)
        _sw_shadow.setOffset(0, 2)
        _sw_shadow.setColor(QColor(15, 23, 42, 40))
        self._style_wrap.setGraphicsEffect(_sw_shadow)

        self._params = self._build_params()
        # 注意顺序：_build_params() 造出来的 QFrame 还没有父控件，
        # 此时调用 setVisible(True) 会被 Qt 当成「独立顶层窗口」立刻显示出来
        # ——启动瞬间闪过的那个小矩形窗口就是它。先挂进布局（获得父控件）
        # 再置为可见，就不会有任何多余窗口。
        root.addWidget(self._params)
        self._params.setVisible(True)

        self._status_lbl = QLabel("渲染器初始化中…")
        self._status_lbl.setObjectName("CubStatus")
        self._status_lbl.hide()
        root.addWidget(self._status_lbl)

        # 画布给一个很矮的高度下限：换行卡片在窄宽度下会变高，没有下限的话
        # 垂直空间不够时 canvas 会被压到 0 高（见 _sync_style_card_height）。
        self._canvas_frame.setMinimumHeight(120)
        QTimer.singleShot(0, self._sync_style_card_height)

    # ── 换行卡片的高度同步 ────────────────────────────────────────
    def resizeEvent(self, event):
        """面板尺寸变化 → 宽度变了 → 换行行数变了 → 重新锁定卡片高度。"""
        super().resizeEvent(event)
        self._sync_style_card_height()

    def _sync_style_card_height(self):
        """按当前宽度把「一键样式」卡片高度锁定为换行后的**实际**高度。

        为什么非锁不可：换行行数随宽度变化，而外层 QVBoxLayout 在垂直空间不够时
        会一路压到 minimumSizeHint（换行布局的最小高度只有"最宽的那个控件"），
        于是后几行会互相**重叠** —— 实测 1100x680（窗口最小尺寸）下重叠 11 处。
        这里用外层 QVBoxLayout 的 totalHeightForWidth() 直接算出该宽度下的真实
        高度，再 setFixedHeight 固定，布局就没有自行发挥的余地了。
        """
        wrap = getattr(self, "_style_wrap", None)
        if wrap is None:
            return
        sw = wrap.layout()
        if sw is None or sw.count() == 0:
            return
        bar = sw.itemAt(0).widget()
        lay = bar.layout() if bar is not None else None
        if lay is None:
            return
        m1 = sw.contentsMargins()
        # 传**卡片外框宽度**而不是内容宽度：QLayout.totalHeightForWidth() 自己会
        # 扣掉自己的 contentsMargins，重复扣一次会算多一行（实测 1920px 下卡片
        # 多出 43px 空白）。
        outer = self.width() - (m1.left() + m1.right())
        if outer <= 0:
            return
        try:
            h = int(lay.totalHeightForWidth(outer))
        except (AttributeError, TypeError):
            return
        if h > 0 and self._style_card_h != h:
            self._style_card_h = h
            bar.setFixedHeight(h)

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
        # 测量类型下拉的条目文字（QComboBox 的条目走不了 _cv_reg 的 setText 机制）
        cb = getattr(self, "_measure_kind_cb", None)
        if cb is not None:
            for i, zh in enumerate(("距离", "键角", "二面角")):
                if i < cb.count():
                    cb.setItemText(i, _cv(zh))
        # 换行卡片的高度取决于各行标签/按钮文字宽度，切语言后要重算
        self._style_card_h = -1
        QTimer.singleShot(0, self._sync_style_card_height)
        # 参数区标签列宽同样依赖文字宽度
        QTimer.singleShot(0, self._refit_param_metrics)
        # 选中标记下拉：整体重填并保持选中项
        if getattr(self, "_sel_marker_cb", None) is not None:
            idx = self._sel_marker_cb.currentIndex()
            self._sel_marker_cb.blockSignals(True)
            self._sel_marker_cb.clear()
            self._sel_marker_cb.addItems(
                [_cv(t) for t in ("包裹", "透明球", "圆环", "光晕")])
            self._sel_marker_cb.setCurrentIndex(idx)
            self._sel_marker_cb.blockSignals(False)
        # 成键模式下拉（一律单键 / 按键长自动判定键型）
        if getattr(self, "_bond_mode_cb", None) is not None:
            idx = self._bond_mode_cb.currentIndex()
            self._bond_mode_cb.blockSignals(True)
            self._bond_mode_cb.clear()
            self._bond_mode_cb.addItem(_cv("一律单键"), "single")
            self._bond_mode_cb.addItem(_cv("按键长自动判定键型"), "auto")
            self._bond_mode_cb.setCurrentIndex(idx)
            self._bond_mode_cb.blockSignals(False)
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
        # 出图观感下拉（_on_look 按 index 取 key，重填安全）
        if getattr(self, "_look_cb", None) is not None:
            idx = self._look_cb.currentIndex()
            self._look_cb.blockSignals(True)
            self._look_cb.clear()
            self._look_cb.addItems([d for d, _ in look_items(i18n._CURRENT_LANG)])
            self._look_cb.setCurrentIndex(idx)
            self._look_cb.blockSignals(False)
        # 折叠组标题（▸/▾ 状态保留）
        for btn, title in getattr(self, "_fold_titles", []):
            sym = "▾" if btn.isChecked() else "▸"
            btn.setText(f"{sym} {_cv(title)}")
        # 「参数 ▴/▾」折叠按钮
        if getattr(self, "_more_btn", None) is not None:
            sym = "▴" if self._more_btn.isChecked() else "▾"
            self._more_btn.setText(f"{_cv('参数')} {sym}")
        # 参数区顶部条的「全部展开 / 全部折叠」：文字随勾选状态切
        if getattr(self, "_param_all_btn", None) is not None:
            self._param_all_btn.setText(
                _cv("全部折叠" if self._param_all_btn.isChecked() else "全部展开"))

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
        # 卡片内容用换行布局，高度随宽度变 → 必须参与 heightForWidth 协商
        _enable_height_for_width(bar)
        sh = QGraphicsDropShadowEffect(bar)
        sh.setBlurRadius(14)
        sh.setOffset(0, 2)
        sh.setColor(QColor(30, 50, 80, 40))
        bar.setGraphicsEffect(sh)
        v = QVBoxLayout(bar)
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(8)

        # ── 「出图观感」预设（布光 + 材质 + 后处理 + 雾化 + 背景 一起换）──
        # 单点旋钮大多是"同一通道上的系数"，实测差异 < 2.5/255；打包成一整套
        # 观感才能给出肉眼可辨的台阶（详见 ovcanvas/_looks.py 顶部说明）。
        # 位置：与「分子显示」**同在一行**（第 2 行），所以这里只建控件、
        # 不建独立行 —— 稍后把这两个控件 addWidget 进 h2。
        # 四行统一用 FlowLayout：见类文档，QHBoxLayout 在 1400px 下会把
        # 17 个控件的文字压没了。
        lbl_look = QLabel()
        lbl_look.setText(self._cv_bind(lbl_look, "出图观感:"))
        self._look_cb = LimitedPopupComboBox(max_popup_height=220)
        self._look_cb.addItems([disp for disp, _ in look_items(i18n._CURRENT_LANG)])
        self._look_cb.setMinimumWidth(150)
        tips = "\n".join(f"· {LOOK_PRESETS[k]['display']} — {look_tip(k)}"
                         for k in LOOK_ORDER)
        self._look_cb.setToolTip(
            "一键切换整套出图观感（布光 + 材质 + 后处理 + 景深雾化 + 背景）：\n"
            + tips +
            "\n\n只改观感相关参数，不动等值面配色/原子配色/分子尺寸。")
        # 两条信号都接：currentIndexChanged 覆盖"索引变了"（含程序化设置，
        # 如脚本/探针），activated 覆盖"重新选同一项"（改乱参数后想回到
        # 预设原位）。同一次用户操作会触发两次，套用是幂等的，代价可忽略。
        self._look_cb.currentIndexChanged.connect(self._on_look)
        self._look_cb.activated.connect(self._on_look)
        # 两个控件稍后并入「分子显示」那一行（见 h2 末尾）

        h = FlowLayout(spacing=6)
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
        self._style_ibo_btn.setToolTip("一键应用默认样式 IBOview（CPK/三光/白底 + 相位紫-蓝，内嵌 gxnu_style-IBOVIEW 预设）")
        self._style_ibo_btn.clicked.connect(self._apply_iboview_style)
        h.addWidget(self._style_ibo_btn)
        self._style_hm_btn = QPushButton("HoukMol")
        self._style_hm_btn.setObjectName("SmallBtn")
        self._style_hm_btn.setToolTip("一键应用默认样式 HoukMol（单光渐变 + 十字圆环）")
        self._style_hm_btn.clicked.connect(self._apply_houkmol_style)
        h.addWidget(self._style_hm_btn)
        self._style_hm3d_btn = QPushButton("HoukMol3d")
        self._style_hm3d_btn.setObjectName("SmallBtn")
        self._style_hm3d_btn.setToolTip(
            "一键应用默认样式 HoukMol3d（四光 / Clear-coat 清漆 / 次表面散射 0.32 /\n"
            "等值面半透明 0.48 / 相位白-绿 / 原子描边 0.35）")
        self._style_hm3d_btn.clicked.connect(self._apply_houkmol3d_style)
        h.addWidget(self._style_hm3d_btn)
        self._style_iq_btn = QPushButton("IQmol")
        self._style_iq_btn.setObjectName("SmallBtn")
        self._style_iq_btn.setToolTip("一键应用默认样式 IQmol（CPK 双光 + 每灯独立光晕 + 红蓝相位 + 原子配色 GaussView）")
        self._style_iq_btn.clicked.connect(self._apply_iqmol_style)
        h.addWidget(self._style_iq_btn)
        self._style_ms_btn = QPushButton("MolStudio")
        self._style_ms_btn.setObjectName("SmallBtn")
        self._style_ms_btn.setToolTip(
            "一键应用默认样式 MolStudio（GaussView 配色 / 单光 / 白底 /\n"
            "原子描边 0.35 / 等值面不透明 / 相位白-绿，含全部材质参数）")
        self._style_ms_btn.clicked.connect(self._apply_molstudio_style)
        h.addWidget(self._style_ms_btn)
        self._style_cv_btn = QPushButton("CYLview")
        self._style_cv_btn.setObjectName("SmallBtn")
        self._style_cv_btn.setToolTip(
            "一键应用默认样式 CYLview（同 MolStudio，但关闭景深雾化与原子描边，\n"
            "原子半径 1.8 / 化学键半径 3.79 / 氢原子与键一样粗，\n"
            "单光源按 light_style.json，光晕 0.5）")
        self._style_cv_btn.clicked.connect(self._apply_cylview_style)
        h.addWidget(self._style_cv_btn)
        self._style_vesta_btn = QPushButton("VESTA")
        self._style_vesta_btn.setObjectName("SmallBtn")
        self._style_vesta_btn.setToolTip(
            "一键应用样式 VESTA（几何/光照同 MolStudio，配色换成 VESTA 的：\n"
            "原子球按 VESTA 的 elements.ini 逐元素配色，\n"
            "化学键与 VESTA 默认画法一致 —— 用两端原子各自的颜色各占一半，\n"
            "背景白；等值面按你导出的 VESTA.json：正相位青 (0,255,255) /\n"
            "负相位黄 (255,255,0)，不透明度 0.2，透明合成用 WBOIT\n"
            "（深度衰减 11.9）—— 即 VESTA 里那种很浅的半透明面）")
        self._style_vesta_btn.clicked.connect(self._apply_vesta_style)
        h.addWidget(self._style_vesta_btn)
        self._clear_analysis_btn = QPushButton()
        self._clear_analysis_btn.setText(self._cv_bind(self._clear_analysis_btn, "清空样式"))
        self._clear_analysis_btn.setObjectName("SmallBtn")
        self._clear_analysis_btn.setToolTip(
            "清空画布上的等值面、临界点、极值点等全部分析效果（保留分子与渲染样式）")
        self._clear_analysis_btn.clicked.connect(self._on_clear_analysis_clicked)
        h.addWidget(self._clear_analysis_btn)
        v.addLayout(h)

        # ── 第 2 行：分子显示 + 出图观感（合并成一行） ──
        h2 = FlowLayout(spacing=10)
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
        self._keep_h_edit = QLineEdit("")
        self._keep_h_edit.setPlaceholderText(
            self._cv_bind(self._keep_h_edit, "如 1,3,5-8", "setPlaceholderText"))
        self._keep_h_edit.setMaximumWidth(90)
        self._keep_h_edit.setToolTip("隐藏氢时仍显示的 H 原子编号（1-based，逗号/连字符范围）")
        self._keep_h_edit.editingFinished.connect(self._on_keep_h_edited)
        # 「保留H编号:」与它后面的输入框打包成一行整体，换行时不会被拆开
        h2.addWidget(_hgroup(lbl_keep, self._keep_h_edit, spacing=4))
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
        # 「出图观感」并入本行。标签与下拉框用 _hgroup 打包成一个整体 ——
        # 不打包的话换行会正好落在两者之间（实测「出图观感:」留在第二行末尾、
        # 下拉框被甩到第三行独自一行）。
        h2.addWidget(_hgroup(lbl_look, self._look_cb, spacing=6))
        v.addLayout(h2)

        # ── 第 3 行：同步到 VMD + 导出图片 ──
        h3 = FlowLayout(spacing=6)
        self._sync_vmd_btn = QPushButton()
        self._sync_vmd_btn.setText(self._cv_bind(self._sync_vmd_btn, "同步到VMD"))
        self._sync_vmd_btn.setObjectName("SmallBtn")
        self._sync_vmd_btn.setCursor(Qt.PointingHandCursor)
        self._sync_vmd_btn.setToolTip("把当前画布场景同步到 VMD，并弹出 VMD 控制台窗口")
        self._sync_vmd_btn.clicked.connect(self._on_sync_vmd_clicked)
        h3.addWidget(self._sync_vmd_btn)
        # ── 导出图片（DPI + 透明背景） ──
        self._dpi_edit = QLineEdit("600")
        self._dpi_edit.setValidator(QDoubleValidator(50, 2400, 0))
        # 宽度要放得下 4 位有效值（上限 2400）：全局 QLineEdit 内边距是 5px 10px，
        # 56px 总宽只剩 ~34px 文字区，输满 4 位就被裁掉。78px 留足余量。
        self._dpi_edit.setFixedWidth(78)
        # 「DPI:」+ 输入框打包同行
        h3.addWidget(_hgroup(QLabel("DPI:"), self._dpi_edit, spacing=4))
        self._transparent_chk = QCheckBox()
        self._transparent_chk.setText(self._cv_bind(self._transparent_chk, "透明背景"))
        self._transparent_chk.setToolTip(
            "导出时背景透明（背景 alpha=0，参照 IboView）。\n"
            "对 PNG / TIFF / SVG 有效；JPG 无 alpha 通道，会合成到画布底色。")
        h3.addWidget(self._transparent_chk)
        btn_sc = QPushButton(self._cv_bind(QPushButton(), "截图"))
        btn_sc.setObjectName("SmallBtn")
        btn_sc.clicked.connect(self._screenshot)
        h3.addWidget(btn_sc)
        # ── 导出图片：格式下拉（PNG / JPG / TIFF / SVG）+ 导出按钮 ──
        # 原先是一个挂 QMenu 的按钮：菜单沿用 Qt 默认的灰底方角样式，和这张
        # 圆角卡片不搭。改为 LimitedPopupComboBox —— 与上方「出图观感」同款
        # 下拉，走全局主题（白底圆角 + 悬停高亮），格式一眼可见、不再有突兀的
        # 弹出菜单。
        self._export_fmt = "png"
        self._export_cb = LimitedPopupComboBox(max_popup_height=180)
        for ext, short in _EXPORT_MENU_ITEMS:
            self._export_cb.addItem(short, ext)
        self._export_cb.setFixedWidth(78)
        self._cv_bind(
            self._export_cb,
            "导出图片格式：\n"
            "  PNG  无损，支持透明背景\n"
            "  JPG  有损压缩，体积小（不支持透明，会合成到画布底色）\n"
            "  TIFF 无损，支持透明背景（存档 / 投稿）\n"
            "  SVG  矢量容器（内嵌满分辨率位图，排版软件可直接用）\n"
            "也可以在保存对话框里临时改格式。",
            "setToolTip")
        btn_ex = QPushButton(self._cv_bind(QPushButton(), "导出图片"))
        btn_ex.setObjectName("SmallBtn")
        btn_ex.setCursor(Qt.PointingHandCursor)
        self._cv_bind(btn_ex, "导出高分辨率图片（格式见左侧下拉）", "setToolTip")
        btn_ex.clicked.connect(
            lambda: self._export_image(self._export_cb.currentData() or "png"))
        # 下拉与按钮打包成一个整体：换行时「选格式 → 点导出」不会被拆到两行
        h3.addWidget(_hgroup(self._export_cb, btn_ex, spacing=6))
        # ── 测量（距离 / 键角 / 二面角）──
        # 类型下拉 + 「测量」开关打包成一个整体，换行时不被拆开。
        self._measure_kind_cb = LimitedPopupComboBox(max_popup_height=160)
        for _k, _zh in (("dist", "距离"), ("angle", "键角"),
                        ("dihedral", "二面角")):
            self._measure_kind_cb.addItem(_cv(_zh), _k)
        self._measure_kind_cb.setFixedWidth(84)
        self._cv_bind(
            self._measure_kind_cb,
            "测量类型：\n"
            "  距离    点 2 个原子\n"
            "  键角    点 3 个原子（第 2 个是顶点）\n"
            "  二面角  点 4 个原子\n"
            "选好后点右侧「测量」，再到画布上依次点击原子",
            "setToolTip")
        self._measure_kind_cb.currentIndexChanged.connect(self._on_measure_kind)
        self._measure_btn = QPushButton()
        self._measure_btn.setText(self._cv_bind(self._measure_btn, "测量"))
        self._measure_btn.setObjectName("SmallBtn")
        self._measure_btn.setCheckable(True)
        self._measure_btn.setCursor(Qt.PointingHandCursor)
        self._cv_bind(self._measure_btn,
                      "在画布上依次点击原子标注几何量（类型见左侧下拉）；"
                      "数值标签可拖动，右键点标签可旋转 / 调字体颜色",
                      "setToolTip")
        self._measure_btn.toggled.connect(self._on_measure_mode)
        h3.addWidget(_hgroup(self._measure_kind_cb, self._measure_btn, spacing=6))
        self._measure_clear_btn = QPushButton()
        self._measure_clear_btn.setText(self._cv_bind(self._measure_clear_btn, "清除"))
        self._measure_clear_btn.setObjectName("SmallBtn")
        self._measure_clear_btn.setToolTip("清除全部测量标注")
        self._measure_clear_btn.clicked.connect(self._on_measure_clear)
        h3.addWidget(self._measure_clear_btn)
        v.addLayout(h3)

        return bar

    def _on_sync_vmd_clicked(self):
        """「同步到VMD」按钮：转发给主窗口注入的回调。"""
        if callable(self.on_sync_vmd):
            try:
                self.on_sync_vmd()
            except Exception:
                pass

    # ══════════════════════════════════════════════════════════════
    #  参数区：6 分节 + 统一栅格
    # ══════════════════════════════════════════════════════════════
    #  设计见 docs/viz_tab_redesign.md。改动前的实测问题：
    #    · 「显示 / 等值面」24 行一口气平铺，光照/材质/等值面/相位/样式 I/O
    #      全混在一起，没有二级分节，找「粗糙度」要滚过 10 行光照参数；
    #    · 同一个面板里**三套标签列宽**（110 / 152 / 129）、**四种控件起点**
    #      （118 / 154 / 177 / 206）——没有同一条基准线，这是"看着乱"的主因；
    #    · 行高 5 种（39/37/32/27/26）、滑块宽度 7 种、数值框 3 种；
    #    · 6 处「一行塞两组参数」把栅格撕开。
    #
    #  做法：控件创建与信号连接**一行都不改**，等它们建完之后按分节归位，
    #  再统一标签列 / 控件列 / 数值框 / 行高。要回退只需回退这一段。

    #: 分节：(key, 中文标题)。列表顺序 = 显示顺序。
    _PARAM_SECTIONS = (
        ("iso", "等值面"),
        ("phase", "相位与配色"),
        ("light", "光照与材质"),
        ("atoms", "原子与键"),
        ("post", "背景与后处理"),
        ("vdw", "vdW 外壳"),
    )

    _FOLD_BTN_QSS = (
        "QToolButton { border:none; color:#1565C0; font-weight:bold;"
        " text-align:left; padding:1px 4px; font-size:9.5pt; }"
        "QToolButton:hover { color:#0D47A1; }")

    # ── 栅格常量 ──
    _ROW_GAP = 6      # 行间距
    _COL_GAP = 8      # 行内控件间距
    _NUM_W = 64       # 数值框/色块等行尾控件的统一宽度

    def _param_lbl(self, text, tip=None):
        """行首标签：登记 i18n、右对齐，宽度在 _finalize_param_grid 里统一。

        关键：用 setFixedWidth（不是 setMinimumWidth）——后者允许长标签自己撑宽，
        正是同一组里标签右边缘出现 110/118/122/133 四种取值的原因。
        """
        lb = QLabel()
        lb.setText(self._cv_bind(lb, text))
        lb.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if tip:
            lb.setToolTip(tip)
        self._param_labels.append(lb)
        return lb

    def _param_row(self, *items):
        """标准行容器。元素语义与原先的 ``_row`` 完全一致：

        * 控件 —— 按 sizeHint 排布；
        * ``(控件, stretch)`` —— 参与拉伸（滑块、下拉都走这个）；
        * ``None`` —— 弹性空白；
        * ``int`` —— 固定间距。
        """
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(self._COL_GAP)
        has_stretch = False
        for it in items:
            if it is None:
                h.addStretch(1)
                has_stretch = True
            elif isinstance(it, int):
                h.addSpacing(it)
            elif isinstance(it, tuple):
                h.addWidget(it[0], it[1])
                if it[1] > 0:
                    has_stretch = True
                self._note_row_widget(it[0])
            else:
                h.addWidget(it)
                self._note_row_widget(it)
        # 行内没有任何拉伸项时，补一个行尾弹性空白。
        # 否则 QHBoxLayout 会把"没人吸收的多余宽度"摊到**控件之间的间距**上：
        # 实测「剥离层数: [4]」这类行（控件有 maximumWidth 上限、把剩余宽度顶回来）
        # 行首标签被推到 x=140、控件被推到 x=405，竖线全断。补了行尾 stretch 后，
        # 多余宽度一律落到最右端，控件保持自然宽度并贴着标签列。
        if not has_stretch:
            h.addStretch(1)
        return w

    def _note_row_widget(self, wd):
        """登记行内控件，供 _finalize_param_grid 统一高度。"""
        if wd is None:
            return
        if wd.minimumWidth() == wd.maximumWidth() == 26:
            return                      # 26×26 色块：固定尺寸，不参与行高统一
        if isinstance(wd, ColorWheelWidget):
            return
        self._param_controls.append(wd)

    def _promote_chk(self, chk):
        """把「复选框当行标签」改成标准开关行：文字挪到行首标签，复选框留空。

        不改文案（同一个字符串仍然只显示一次），只是把它从左对齐的复选框文本
        挪到右对齐的标签列，竖线才连得上。i18n 登记同步搬家（否则切语言时
        _apply_lang 会把文字又写回复选框）。
        """
        text = chk.text()
        self._cv_reg = [e for e in self._cv_reg if e[0] is not chk]
        chk.setText("")
        return self._param_lbl(text)

    # ── 分节容器 ──
    def _init_param_sections(self, outer):
        """每个分节 = 一张圆角矩形卡片，标题栏与内容都在卡片**里面**。

        先前标题是卡片外面一个悬空按钮、内容才是白卡片，两者不成整体
        （标题像游离在卡片上方）。现在合成一张卡：
             ┌──────────────────────────┐
             │ ▾ 等值面                  │  ← 折叠按钮（卡片顶部）
             ├──────────────────────────┤
             │  等值面配色:  [ … ]       │
             └──────────────────────────┘
        收起时只剩标题那一条，仍是一张圆角小卡。
        """
        self._sec = {}
        self._fold_titles = []
        for key, title in self._PARAM_SECTIONS:
            # 卡片外壳：圆角 + 白底 + 细边框（样式见 _CANVAS_QSS 的 #CubParamCard）
            card = QWidget()
            card.setObjectName("CubParamCard")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(0)
            btn = QToolButton()
            btn.setCheckable(True)
            btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
            btn.setCursor(Qt.PointingHandCursor)
            # 样式走面板级 QSS（#CubParamCard QToolButton），不在这里 setStyleSheet：
            # 内联样式优先级更高，会把卡片的圆角/悬停底色一起盖掉。
            cl.addWidget(btn)
            # 内容区只是一个透明容器，负责撑开内边距；卡片背景由 card 提供。
            # 不用 QGroupBox：它的空标题仍会让出标题区与边框内缩，实测每节白吃 48px。
            body = QWidget()
            body.setObjectName("CubParamSection")
            v = QVBoxLayout(body)
            v.setContentsMargins(10, 5, 10, 6)
            v.setSpacing(self._ROW_GAP)
            cl.addWidget(body)
            outer.addWidget(card, stretch=0)

            def _tog(on, k=key):
                self._sec[k]["body"].setVisible(on)
                self._sec[k]["btn"].setText(
                    f"{'▾' if on else '▸'} {_cv(dict(self._PARAM_SECTIONS)[k])}")
                self.paramsChanged.emit()
                self._save_section_state()
                self._sync_all_btn()

            btn.toggled.connect(_tog)
            self._sec[key] = {"col": card, "btn": btn, "body": body, "v": v}
            self._fold_titles.append((btn, title))

    def _sec_vbox(self, key):
        """取分节的纵向行布局（行直接 addWidget 进去）。"""
        return self._sec[key]["v"]

    def _sec_grid(self, key):
        """在分节里开一个统一规格的网格（原球棍组 / vdW 组用）。

        网格与行布局共用同一套 间距/标签列/控件列，所以两者混排时竖线仍然对齐。
        """
        g = QGridLayout()
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(self._COL_GAP)
        g.setVerticalSpacing(self._ROW_GAP)
        g.setColumnStretch(1, 1)          # 第 1 列（滑块/下拉）吃满剩余宽度
        self._sec[key]["v"].addLayout(g)
        return g

    # ── 分节展开状态持久化 ──
    def _section_state_path(self):
        import configparser  # noqa: F401  (仅在读写时用到)
        try:
            from molstudio.core.fchk_orbital import CONFIG_FILE
            return CONFIG_FILE
        except Exception:
            return None

    def _save_section_state(self):
        """把各分节的展开状态写进 fchk_orbital.ini（沿用 file_dialogs 的写法）。"""
        path = self._section_state_path()
        if not path or not getattr(self, "_sec", None):
            return
        try:
            import configparser
            cfg = configparser.ConfigParser()
            if os.path.exists(path):
                cfg.read(path, encoding="utf-8")
            if "param_sections" not in cfg:
                cfg["param_sections"] = {}
            for key, _title in self._PARAM_SECTIONS:
                cfg["param_sections"][key] = \
                    "1" if self._sec[key]["btn"].isChecked() else "0"
            with open(path, "w", encoding="utf-8") as f:
                cfg.write(f)
        except Exception:
            pass

    def _restore_section_state(self):
        """读回展开状态；没有记录时只展开第一节（首屏免滚动）。

        默认只展开第一节的理由：全展开是 2300px，而右栏视口只有 ~681px，
        用户一进这个 tab 就得先滚 3 屏才能看到下面的小节标题。
        """
        state = {}
        path = self._section_state_path()
        if path and os.path.exists(path):
            try:
                import configparser
                cfg = configparser.ConfigParser()
                cfg.read(path, encoding="utf-8")
                if cfg.has_section("param_sections"):
                    state = {k: v.strip() == "1"
                             for k, v in cfg.items("param_sections")}
            except Exception:
                state = {}
        first = self._PARAM_SECTIONS[0][0]
        for key, _title in self._PARAM_SECTIONS:
            on = state.get(key, key == first)
            btn = self._sec[key]["btn"]
            btn.setChecked(on)
            # setChecked 不触发 toggled（值没变时），这里显式同步一次
            self._sec[key]["body"].setVisible(on)
            btn.setText(
                f"{'▾' if on else '▸'} {_cv(dict(self._PARAM_SECTIONS)[key])}")
        self._sync_all_btn()

    def _sync_all_btn(self):
        """让顶部「全部展开 / 折叠」按钮的勾选态跟实际展开情况一致。

        用户逐个点开分节时，这个按钮也要跟着变成"全部折叠"——
        否则状态与按钮文字会各说各话。
        """
        btn = getattr(self, "_param_all_btn", None)
        if btn is None or not getattr(self, "_sec", None):
            return
        allon = all(self._sec[k]["btn"].isChecked()
                    for k, _t in self._PARAM_SECTIONS)
        btn.blockSignals(True)
        btn.setChecked(allon)
        btn.blockSignals(False)
        btn.setText(_cv("全部折叠" if allon else "全部展开"))

    def show_param_sections(self, keys):
        """展开指定分节、收起其余（供主窗口/脚本调用）。"""
        keys = set(keys)
        for key, _title in self._PARAM_SECTIONS:
            self._sec[key]["btn"].setChecked(key in keys)
        self._sync_all_btn()
        self._save_section_state()

    # ── 栅格收尾：统一标签列 / 行高 / 数值框 ──
    def _refit_param_metrics(self):
        """按**当前**字体与样式度量，重算并钉死标签列宽与行高。

        必须能在 show 之后再跑一次 —— 控件刚建好、还没 polish 时量到的
        sizeHint 偏小/偏大都不作数：
          · 标签：'WBOIT 衰减:' 建时 117、显示后需要 122，只按建时宽度
            setFixedWidth 会把字裁掉；
          · 行内控件：样式表（收紧内边距那几条）要 polish 之后才反映到
            sizeHint 上，行高按建时的值定就会与控件实际需要的高度对不上。
        """
        # ── 标签列 ──
        if getattr(self, "_param_labels", None):
            # 先松开固定宽度再量：setFixedWidth 会把 sizeHint 也钳到该宽度，
            # 不松开的话切回中文时列宽只会增不会减（英文撑到 199 就回不去）。
            for lb in self._param_labels:
                try:
                    lb.setMinimumWidth(0)
                    lb.setMaximumWidth(16777215)
                except RuntimeError:
                    pass
            w = 0
            for lb in self._param_labels:
                try:
                    w = max(w, lb.sizeHint().width())
                except RuntimeError:
                    continue
            self._param_lbl_w = max(96, w)
            for lb in self._param_labels:
                try:
                    lb.setFixedWidth(self._param_lbl_w)
                except RuntimeError:
                    pass
            # 网格第 0 列也要钉住（否则某行的长标签会把整列撑宽）
            for key, _t in self._PARAM_SECTIONS:
                try:
                    body = self._sec[key]["body"]
                except (KeyError, RuntimeError):
                    continue        # 面板建到一半就失败时保护一下
                for g in body.findChildren(QGridLayout):
                    g.setColumnMinimumWidth(0, self._param_lbl_w)

        # ── 行高：取行内**交互控件**的自然高度上限，再统一压成同一高度 ──
        if getattr(self, "_param_controls", None):
            for c in self._param_controls:
                try:
                    c.setMinimumHeight(0)
                    c.setMaximumHeight(16777215)
                except RuntimeError:
                    pass
            h = 0
            for c in self._param_controls:
                # QLabel 不参与测量：它只是文字，钉到多高都不会裁字，不该反过来
                # 决定整行高度（实测它的 sizeHint 会被样式抬到 30~35px）。
                # QSpinBox 也不参与：Fusion 给它 39px 是**微调按钮**的度量，
                # 不是文字需要的（文字约 17px + padding 4px），让一个数字框
                # 决定整个表单的行高本末倒置；它随后会被统一钉到 ROW_H。
                if isinstance(c, (QLabel, QSpinBox)):
                    continue
                try:
                    h = max(h, c.sizeHint().height())
                except RuntimeError:
                    continue
            self._param_row_h = max(28, h)
            for c in self._param_controls:
                try:
                    c.setFixedHeight(self._param_row_h)
                except RuntimeError:
                    pass
        # 度量变了 → 本面板的固有高度也变了 → 通知外层。
        # 主窗口的 PagedScrollArea 只在自身 resize / 切页时重算栈高，
        # 不通知的话（比如切语言后行高从 39 变 33）新高度不会被采纳，
        # 底部内容会落在滚动范围之外。
        self.paramsChanged.emit()

    def showEvent(self, event):
        """首次显示后再校一次度量（此时样式表与字体度量才是最终值）。"""
        super().showEvent(event)
        if not getattr(self, "_param_refit_done", False):
            self._param_refit_done = True
            QTimer.singleShot(0, self._refit_param_metrics)

    def _finalize_param_grid(self):
        """把标签列、行高、行尾数值框统一到同一套尺寸。

        标签列取**实测最长标签**（切语言后文字宽度会变，所以要能重算）。
        """
        # 0) 网格里的第 0 列标签是早期用裸 QLabel 建的：补登记 + 右对齐，
        #    并把这些网格里的控件也收进统一高度的名单。
        seen = {id(lb) for lb in self._param_labels}
        for key, _t in self._PARAM_SECTIONS:
            body = self._sec[key]["body"]
            for g in body.findChildren(QGridLayout):
                for i in range(g.count()):
                    it = g.itemAt(i)
                    c = it.widget()
                    if c is None:
                        continue
                    _r, col, _rs, _cs = g.getItemPosition(i)
                    if col == 0 and isinstance(c, QLabel):
                        c.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                        if id(c) not in seen:
                            seen.add(id(c))
                            self._param_labels.append(c)
                    self._note_row_widget(c)

        # 1) 标签列宽 + 行高：都按实测自然尺寸钉死。
        #    量之前必须先把样式解析掉（ensurePolished）：QSS 的内边距只有 polish
        #    之后才反映到 sizeHint 上，否则量到的是全局主题给输入框的 39px 下限，
        #    行高会随"这次量得早还是晚"在 33/39 之间跳（实测同一份代码两次运行
        #    默认高度 673 / 723 不同）。
        pbox = getattr(self, "_params_box", None)
        if pbox is not None:
            for _c in (pbox,) + tuple(pbox.findChildren(QWidget)):
                try:
                    _c.ensurePolished()
                except RuntimeError:
                    pass
        self._refit_param_metrics()
        self._refit_param_metrics()

        # 2) 滑块放开宽度（原先有的写死 190/200，有的同时又要拉伸）
        for c in self._param_controls:
            if isinstance(c, QSlider):
                c.setMinimumWidth(0)
                c.setMaximumWidth(16777215)

        # 4) 行尾数值框/数值标签统一宽度：
        #    · 行布局里：紧跟滑块之后、且不参与拉伸的那些；
        #    · 网格里：第 2 列的输入框/数值标签。
        for key, _t in self._PARAM_SECTIONS:
            sec = self._sec[key]
            v = sec["v"]
            for i in range(v.count()):
                row = v.itemAt(i).widget()
                if row is None or row.layout() is None:
                    continue
                rl = row.layout()
                seen_slider = False
                for j in range(rl.count()):
                    it = rl.itemAt(j)
                    c = it.widget()
                    if c is None:
                        continue
                    if isinstance(c, QSlider):
                        seen_slider = True
                        continue
                    if seen_slider and rl.stretch(j) == 0 and \
                            isinstance(c, (QLineEdit, QSpinBox, QLabel)):
                        c.setFixedWidth(self._NUM_W)
            for g in sec["body"].findChildren(QGridLayout):
                for i in range(g.count()):
                    c = g.itemAt(i).widget()
                    if c is None:
                        continue
                    _r, col, _rs, _cs = g.getItemPosition(i)
                    if col == 2 and isinstance(
                            c, (QLineEdit, QSpinBox, QLabel)):
                        c.setFixedWidth(self._NUM_W)

    def _build_param_topbar(self, outer):
        """参数区顶部固定条：样式 I/O、视图复位、全部展开/折叠。

        原先「保存…/载入…」在长列表第 ~1150 行、「重置视角」在最底部，
        要滚 1.7 屏才够得着；钉在顶上后随时可点。
        """
        bar = QWidget()
        bar.setObjectName("CubParamTopBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(10, 2, 10, 2)
        h.setSpacing(6)
        # 行首标签**不能**用 _param_lbl：它会被统一成表单标签列的宽度
        # （实测 129px）而且右对齐，于是"样式:"被推到框的最右边，前面拖出
        # 一大片空白 —— 这条看着别扭主要就是它。改成一个贴字的蓝色小标题。
        self._param_top_lbl = QLabel()
        self._param_top_lbl.setObjectName("CubParamTopLbl")
        self._param_top_lbl.setText(
            self._cv_bind(self._param_top_lbl, "样式:"))
        h.addWidget(self._param_top_lbl)
        h.addWidget(self._style_save_btn)
        h.addWidget(self._style_load_btn)
        # 分组竖线：样式 I/O │ 视图 │ 展开，免得四个按钮连成一片分不清是一组
        h.addWidget(self._param_top_sep())
        h.addWidget(self._btn_reset_view)
        h.addStretch(1)
        self._param_all_btn = QPushButton()
        self._param_all_btn.setObjectName("SmallBtn")
        self._param_all_btn.setCheckable(True)
        self._param_all_btn.setCursor(Qt.PointingHandCursor)
        self._param_all_btn.setText(_cv("全部展开"))
        self._param_all_btn.setToolTip(
            "一次展开/折叠全部设置分节（状态会记住，下次打开这个界面沿用）")
        # 文字随勾选状态在两个词之间切，所以不进 _cv_reg（那会被覆盖成固定值），
        # 由 _apply_lang 按当前状态重设。
        self._param_all_btn.toggled.connect(self._on_all_sections_toggled)
        h.addWidget(self._param_all_btn)
        outer.insertWidget(0, bar)

    @staticmethod
    def _param_top_sep():
        """顶部条里的分组竖线（1×16px，纯装饰）。"""
        ln = QFrame()
        ln.setObjectName("CubParamTopSep")
        ln.setFixedWidth(1)
        ln.setFixedHeight(16)
        return ln

    def _on_all_sections_toggled(self, on):
        for key, _title in self._PARAM_SECTIONS:
            self._sec[key]["btn"].setChecked(bool(on))
        # 按钮文字是"点一下会做什么"：已全展开时显示"全部折叠"
        self._param_all_btn.setText(_cv("全部折叠" if on else "全部展开"))
        self._save_section_state()

    def _build_params(self):
        box = QFrame()
        box.setObjectName("CubParams")
        self._params_box = box          # 供 _finalize_param_grid 强制 polish 用
        # 参数面板会被主窗口摘出画布面板挂到右侧 tab，所以样式表要挂在它自己身上
        box.setStyleSheet(_PARAMS_QSS)
        outer = QVBoxLayout(box)
        outer.setContentsMargins(6, 4, 6, 6)
        # 卡片之间的间距。压到 4px 是为了让"只展开第一节"的默认视图正好装进
        # 右栏视口（681px）而不用滚动 —— 卡片自带 1px 边框，视觉间隔约 6px，
        # 不至于显挤。
        outer.setSpacing(4)

        # 当前背景色 (r,g,b,a)；默认不透明白底
        if not hasattr(self, "_bg_rgba"):
            self._bg_rgba = (1.0, 1.0, 1.0, 1.0)

        # ── 分节骨架 + 顶部固定条（先建，后面的行按节归位）──
        self._param_labels = []      # 行首标签：收尾时统一 setFixedWidth
        self._param_controls = []    # 行内控件：收尾时统一 setFixedHeight
        self._init_param_sections(outer)

        # 行 / 标签一律走面板级 helper（分节、球棍组、vdW 组共用同一套，
        # 这正是原先三套布局各自为政、三条标签列并存的根因）
        _lbl = self._param_lbl
        _row = self._param_row

        # ── 滑块右侧的精确数值输入框 ──
        # 每条滑块都配一个，宽度统一 NUM_EDIT_W（与「等值面大小 / 透明度」
        # 两行既有的输入框同宽）：拖滑块时框内数值跟着走；框里直接输数字
        #（回车/失焦）反算滑块刻度，越界夹取、显示自动归一化。
        NUM_EDIT_W = 64
        self._num_edits = []      # [(滑块, 输入框, 格式化函数)]，供 _refresh_num_edits 用

        def _num_edit(sld, scale=100.0, decimals=2, tip=None):
            """给滑块配一个双向同步的数值输入框。

            scale：滑块整数刻度 → 真实值的除数（刻度 25 / 100 = 0.25）。
            """
            ed = QLineEdit()
            ed.setFixedWidth(NUM_EDIT_W)
            lo, hi = sld.minimum() / scale, sld.maximum() / scale
            ed.setValidator(QDoubleValidator(lo, hi, decimals, ed))
            ed.setAlignment(Qt.AlignRight)
            ed.setToolTip(tip or
                          f"精确输入（{lo:.{decimals}f} – {hi:.{decimals}f}），"
                          "回车生效；与左侧滑块双向同步")

            def _fmt(v):
                return f"{v / scale:.{decimals}f}"

            def _sync(v):
                # 正在框里打字时不回写，免得把用户刚敲的内容顶掉
                if not ed.hasFocus():
                    ed.setText(_fmt(v))

            def _commit():
                try:
                    v = float(ed.text())
                except ValueError:
                    ed.setText(_fmt(sld.value()))
                    return
                iv = int(round(v * scale))
                iv = max(sld.minimum(), min(sld.maximum(), iv))
                ed.setText(_fmt(iv))            # 归一化显示（0.5 → 0.50）
                if iv != sld.value():
                    sld.setValue(iv)            # 触发真正的应用逻辑

            sld.valueChanged.connect(_sync)
            ed.returnPressed.connect(_commit)
            ed.editingFinished.connect(_commit)
            ed.setText(_fmt(sld.value()))
            self._num_edits.append((sld, ed, _fmt))
            return ed

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

        self._shiny_slider = QSlider(Qt.Horizontal)
        self._shiny_slider.setRange(0, 100)
        self._shiny_slider.setValue(int(_GLOSS_DEFAULT * 100))
        self._shiny_slider.setMinimumWidth(120)
        self._shiny_slider.setToolTip("光泽（镜面高光强度）")

        self._spec_model_cb = LimitedPopupComboBox(max_popup_height=160)
        self._spec_model_cb.addItems(
            [_cv("GGX 微表面"), _cv("Blinn-Phong 经典"),
             _cv("Clear-coat 清漆"), _cv("Matcap 材质球")])
        self._spec_model_cb.setToolTip(
            "镜面/光照模型（原子与等值面统一生效）：\n"
            "· GGX 微表面 — 现代，散射尾宽、边缘有菲涅尔提亮（玻璃/珠光感）\n"
            "· Blinn-Phong 经典 — 双瓣高光（宽高光 + 中心亮点）\n"
            "· Clear-coat 清漆 — 柔和底层 + 尖锐清漆层，上釉/湿面感\n"
            "· Matcap 材质球 — 法线查材质球贴图，观感由预设贴图决定")

        self._sss_slider = QSlider(Qt.Horizontal)
        self._sss_slider.setRange(0, 100)            # 0.00 .. 1.00
        self._sss_slider.setValue(0)                 # 默认 0.00（关闭）
        self._sss_slider.setMinimumWidth(120)
        self._sss_slider.setToolTip(
            "次表面散射强度（0=关闭，走标准 Lambert）：\n"
            "·  softening —— 明暗交界向背光侧推移，过渡拉长，玉/蜡般的柔和\n"
            "·  背光透射 —— 逆光时边缘透光发亮，掠射处更明显\n"
            "对所有多灯模型生效；Matcap 材质球替代了光照，故对其无效")

        self._soft_term_sld = QSlider(Qt.Horizontal)
        self._soft_term_sld.setRange(0, 100)         # 0.00 .. 1.00
        self._soft_term_sld.setValue(0)              # 默认 0（标准 Lambert）
        self._soft_term_sld.setMinimumWidth(120)
        self._soft_term_sld.setToolTip(
            "明暗交界线柔化（0..1）：\n"
            "· 0（默认）— 标准 Lambert，与原本完全一致，明暗交界较锐利\n"
            "· 1 — Half-Lambert，背光侧也受光，交界最柔和\n"
            "单光源斜射时等值面的硬边就是 terminator，拖大它可柔化。\n"
            "只影响漫反射，高光位置/形状不变。")

        self._backdim_sld = QSlider(Qt.Horizontal)
        self._backdim_sld.setRange(10, 100)            # 0.10 .. 1.00
        self._backdim_sld.setValue(80)                 # 默认 0.80
        self._backdim_sld.setMinimumWidth(120)
        self._backdim_sld.setToolTip(
            "等值面背面调暗（0.10 – 1.00）：\n"
            "· 1.00 — 关闭，正反面同亮（旧画面）\n"
            "· 0.80（默认）— 背面比正面暗 20%，半透明波瓣读出厚度/体积感\n"
            "只影响双面渲染的轨道等值面；原子球/键为单面材质，不受影响。")

        self._hemi_chk = QCheckBox()
        self._hemi_chk.setToolTip(
            "半球环境光（Hemisphere Lighting）：按世界空间法线的朝上/朝下程度，\n"
            "在「天顶色」与「地面色」之间插值，作为廉价的环境漫反射补光。\n"
            "只叠加到 RGB，不参与 GGX 镜面项，也不改变透明度（兼容 WBOIT）。")
        self._hemi_sld = QSlider(Qt.Horizontal)
        self._hemi_sld.setRange(0, 100)              # 0.00 .. 1.00
        self._hemi_sld.setValue(25)                  # 默认 0.25
        self._hemi_sld.setMinimumWidth(120)
        self._hemi_sld.setToolTip("半球环境光强度（0..1，越大补光越亮）")
        # 天顶色 / 地面色：与正/负相位、描边颜色同款无文字圆角色块（26×26），
        # 色块前用行内次要标签点名，不再用带文字的宽按钮（否则两种配色入口
        # 观感不一致，且宽按钮的底色会被读成「一行设置」而不是「一个色块」）
        self._hemi_top_btn = QPushButton()
        self._hemi_top_btn.setObjectName("SmallBtn")
        self._hemi_top_btn.setFixedSize(26, 26)
        self._hemi_top_btn.setCursor(Qt.PointingHandCursor)
        self._hemi_top_btn.setToolTip("半球环境光的天顶色（法线朝上时取此色）")
        self._hemi_top_btn.clicked.connect(self._on_hemi_top_color)
        self._hemi_bot_btn = QPushButton()
        self._hemi_bot_btn.setObjectName("SmallBtn")
        self._hemi_bot_btn.setFixedSize(26, 26)
        self._hemi_bot_btn.setCursor(Qt.PointingHandCursor)
        self._hemi_bot_btn.setToolTip("半球环境光的地面色（法线朝下时取此色）")
        self._hemi_bot_btn.clicked.connect(self._on_hemi_bottom_color)
        # 建完即上色：色块无文字，不上色就是一个空白按钮（_sync_hemi_swatches
        # 此前只在换样式/选色后调用，初始化漏了这一下）
        self._sync_hemi_swatches()

        self._rough_slider = QSlider(Qt.Horizontal)
        self._rough_slider.setRange(3, 100)          # 0.03 .. 1.00
        self._rough_slider.setValue(45)              # 默认 0.45
        self._rough_slider.setMinimumWidth(120)
        self._rough_slider.setToolTip(
            "粗糙度（底层高光斑点大小）：越小越镜面、光点越集中。"
            "对 GGX 微表面与 Clear-coat 清漆生效")

        self._coat_rough_slider = QSlider(Qt.Horizontal)
        self._coat_rough_slider.setRange(3, 100)     # 0.03 .. 1.00
        self._coat_rough_slider.setValue(10)         # 默认 0.10（锐）
        self._coat_rough_slider.setMinimumWidth(120)
        self._coat_rough_slider.setToolTip(
            "清漆层粗糙度：越小清漆高光越锐。仅对 Clear-coat 清漆生效")

        self._coat_strength_slider = QSlider(Qt.Horizontal)
        self._coat_strength_slider.setRange(0, 200)  # 0.0 .. 2.0
        self._coat_strength_slider.setValue(80)      # 默认 0.80
        self._coat_strength_slider.setMinimumWidth(120)
        self._coat_strength_slider.setToolTip(
            "清漆层强度：越大清漆高光越亮。仅对 Clear-coat 清漆生效")

        self._matcap_cb = LimitedPopupComboBox(max_popup_height=140)
        self._matcap_cb.addItems(
            [_cv(_MATCAP_NAMES[n]) for n in ("studio", "glossy", "matte", "metal")])
        self._matcap_cb.setToolTip(
            "Matcap 材质球预设（仅 Matcap 材质球模型生效）：\n"
            "· 柔和影棚 — 柔和漫反射 + 轻微高光\n"
            "· 亮面塑料 — 强烈锐利高光\n"
            "· 哑光陶瓷 — 无高光的柔和哑光\n"
            "· 金属 — 高对比 + 边缘反光")

        # ── 第 5 行：选中标记 ──
        self._sel_marker_cb = QComboBox()
        self._sel_marker_cb.addItems(
            [_cv(t) for t in ("包裹", "透明球", "圆环", "光晕")])
        self._sel_marker_cb.setToolTip(
            "选中原子时的标记形状：\n"
            "· 包裹（默认）— 贴合原子表面的一层半透明高亮壳，配合原子本体染色。\n"
            "· 透明球 — 更大的半透明球。\n"
            "· 圆环 — 环绕原子的环。\n"
            "· 光晕 — 内壳 + 大范围外壳。\n"
            "（早期版本的「二十面体」已移除：离原子太远、边角生硬。）")

        self._sel_pulse_chk = QCheckBox()
        self._sel_pulse_chk.setToolTip("选中标记半径 ±12% 正弦呼吸动画")
        self._sel_pulse_chk.toggled.connect(self._on_sel_pulse)

        self._btn_reset_view = QPushButton(
            self._cv_bind(QPushButton(), "重置视角"))
        self._btn_reset_view.setObjectName("SmallBtn")
        self._btn_reset_view.setToolTip("重置相机视角（居中并铺满分子/等值面）")
        self._btn_reset_view.clicked.connect(self._reset_view)

        # 每个下拉独占一行、占满整行宽度，避免文案被压缩截断
        self._sec_vbox("iso").addWidget(_row(_lbl("等值面配色:"), (self._style_cb, 1)))
        # ── 第 2 行：光照 ──
        self._sec_vbox("light").addWidget(_row(_lbl("光照:"), (self._light_cb, 1)))
        # ── 第 2.1 行：半球环境光（开关 + 强度 + 数值）──
        self._hemi_edit = _num_edit(self._hemi_sld,
                                    tip="半球环境光强度（0.00 – 1.00，越大补光越亮）")
        self._sec_vbox("light").addWidget(_row(_lbl("半球环境光:"), self._hemi_chk,
                          (self._hemi_sld, 1), self._hemi_edit))
        # ── 第 2.2 行：天顶色 / 地面色 ──
        # 原先挤成一行「天顶/地面色: 天顶色:■ …… 地面色:■」，两个行内标签把
        # 标签列撕成 4 段（实测 x = 0/126/459/539）。拆成两行标准「标签 + 色块」。
        self._sec_vbox("light").addWidget(
            _row(_lbl("天顶色:"), self._hemi_top_btn))
        self._sec_vbox("light").addWidget(
            _row(_lbl("地面色:"), self._hemi_bot_btn))
        # ── 第 3 行：原子配色 ──
        self._btn_elem_color = QPushButton(
            self._cv_bind(QPushButton(), "元素颜色…"))
        self._btn_elem_color.setObjectName("SmallBtn")
        self._btn_elem_color.setToolTip("自定义每种元素的原子颜色（覆盖默认 CPK 配色）")
        self._btn_elem_color.clicked.connect(self._open_element_color_dialog)
        self._sec_vbox("atoms").addWidget(_row(_lbl("原子配色:"), (self._mol_style_cb, 1),
                          self._btn_elem_color))
        # ── 第 4 行：光泽 ──
        self._shiny_edit = _num_edit(self._shiny_slider,
                                     tip="光泽 / 镜面高光强度（0.00 – 1.00）")
        self._sec_vbox("light").addWidget(_row(_lbl("光泽:"), (self._shiny_slider, 1),
                          self._shiny_edit))
        # ── 第 4.5 行：镜面模型 ──
        self._sec_vbox("light").addWidget(_row(_lbl("镜面模型:"), (self._spec_model_cb, 1)))
        # ── 第 4.55 行：次表面散射（对所有多灯模型生效，Matcap 除外）──
        self._sss_edit = _num_edit(self._sss_slider,
                                   tip="次表面散射强度（0.00 – 1.00，0 = 关闭）")
        self._sec_vbox("light").addWidget(_row(_lbl("次表面散射:"), (self._sss_slider, 1),
                          self._sss_edit))
        # ── 第 4.56 行：明暗柔和度（Half-Lambert 混合，柔化 terminator）──
        self._soft_term_edit = _num_edit(
            self._soft_term_sld,
            tip="明暗交界线柔化（0.00 – 1.00，0 = 标准 Lambert）")
        self._sec_vbox("light").addWidget(_row(_lbl("明暗柔和度:"), (self._soft_term_sld, 1),
                          self._soft_term_edit))
        # ── 第 4.57 行：等值面背面调暗（双面渲染的内壁压暗，增体积感）──
        self._backdim_edit = _num_edit(self._backdim_sld,
                                       tip="等值面背面调暗（0.10 – 1.00，1.00 = 关闭）")
        self._sec_vbox("light").addWidget(_row(_lbl("背面调暗:"), (self._backdim_sld, 1),
                          self._backdim_edit))
        # ── 第 4.6 行：粗糙度（GGX / Clear-coat 底层高光斑点大小）──
        self._rough_edit = _num_edit(self._rough_slider,
                                     tip="粗糙度（0.03 – 1.00，越小越镜面）")
        self._sec_vbox("light").addWidget(_row(_lbl("粗糙度:"), (self._rough_slider, 1),
                          self._rough_edit))
        # ── 第 4.7 行：清漆粗糙度 / 强度（仅 Clear-coat）──
        self._coat_rough_edit = _num_edit(
            self._coat_rough_slider,
            tip="清漆层粗糙度（0.03 – 1.00，越小清漆高光越锐）")
        self._sec_vbox("light").addWidget(_row(_lbl("清漆粗糙度:"), (self._coat_rough_slider, 1),
                          self._coat_rough_edit))
        self._coat_strength_edit = _num_edit(
            self._coat_strength_slider,
            tip="清漆层强度（0.00 – 2.00，越大清漆高光越亮）")
        self._sec_vbox("light").addWidget(_row(_lbl("清漆强度:"), (self._coat_strength_slider, 1),
                          self._coat_strength_edit))
        # ── 第 4.8 行：材质球预设（仅 Matcap）──
        self._sec_vbox("light").addWidget(_row(_lbl("材质球预设:"), (self._matcap_cb, 1)))
        # ── 第 5 行：选中标记（下拉占满整行）──
        self._sec_vbox("atoms").addWidget(_row(_lbl("选中标记:"), (self._sel_marker_cb, 1)))
        # ── 第 6 行：呼吸 ──
        # 原先「呼吸」复选框与「重置视角」按钮被一段弹性空白顶成一行两端，
        # 两者功能毫无关系。重置视角移到顶部固定条。
        self._sec_vbox("atoms").addWidget(
            _row(_lbl("呼吸:"), self._sel_pulse_chk))

        # 先创建全部控件再连接信号，避免初始化 addItems 触发回调时
        # 访问尚未创建的控件（如 _on_style 会读取 _mol_style_cb）
        self._style_cb.currentIndexChanged.connect(self._on_style)
        self._light_cb.currentIndexChanged.connect(self._on_lighting)
        self._mol_style_cb.currentIndexChanged.connect(self._on_mol_style)
        self._shiny_slider.valueChanged.connect(self._on_gloss)
        self._spec_model_cb.currentIndexChanged.connect(self._on_spec_model)
        self._sss_slider.valueChanged.connect(self._on_sss)
        self._soft_term_sld.valueChanged.connect(self._on_soft_term)
        self._backdim_sld.valueChanged.connect(self._on_back_dim)
        self._hemi_chk.toggled.connect(self._on_hemi)
        self._hemi_sld.valueChanged.connect(self._on_hemi_intensity)
        self._rough_slider.valueChanged.connect(self._on_roughness)
        self._coat_rough_slider.valueChanged.connect(self._on_coat_roughness)
        self._coat_strength_slider.valueChanged.connect(self._on_coat_strength)
        self._matcap_cb.currentIndexChanged.connect(self._on_matcap)
        self._sel_marker_cb.currentIndexChanged.connect(self._on_sel_marker)
        # 初始应用一次默认（ultra-glass / IboView 三光 / CPK / 默认光泽 / GGX）
        self._on_style(self._style_cb.currentIndex())
        self._on_lighting(self._light_cb.currentIndex())
        self._on_mol_style(self._mol_style_cb.currentIndex())
        self._on_gloss(self._shiny_slider.value())
        # 镜面模型 + 各材质/补光参数初始同步（取画布当前值）
        self._sync_material_ui()
        self._on_sel_marker(self._sel_marker_cb.currentIndex())

        # ── IboView 相对阈值：界面不展示，但逻辑与实例都保留 ──
        # 这几个控件不加入任何布局，只挂到「等值面」分节的容器上作为父对象
        # （否则没有 parent 的控件会变成游离的顶层窗口）。
        # 此前是先进布局再 hide()，白占着网格行号、让行序难以阅读。
        _iso_host = self._sec["iso"]["body"]
        self._rel_chk = QCheckBox(
            f"相对阈值 ({_RENDER_DEFAULTS['IsoThreshold']:.0f}%)", _iso_host)
        self._rel_chk.setToolTip(
            "勾选后按 IboView IsoThreshold 语义取等值面：\n"
            "选取使 |data| 累积权重达到指定百分比的等值面。\n"
            "取消勾选则使用下方的绝对 isovalue（cube 文件原始单位）。")
        self._rel_chk.toggled.connect(self._on_rel_mode)
        self._rel_chk.hide()

        self._rel_pct_lbl = QLabel("百分比:", _iso_host)
        self._rel_pct_lbl.hide()

        self._rel_sld = QSlider(Qt.Horizontal, _iso_host)
        self._rel_sld.setRange(50, 99)
        self._rel_sld.setValue(int(_RENDER_DEFAULTS['IsoThreshold']))
        self._rel_sld.setEnabled(False)
        self._rel_sld.valueChanged.connect(self._on_rel_slider)
        self._rel_sld.hide()

        self._rel_lbl = QLabel(f"{_RENDER_DEFAULTS['IsoThreshold']:.0f}%", _iso_host)
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
        self._iso_edit.setFixedWidth(NUM_EDIT_W)   # 与其余滑块输入框同宽
        self._iso_edit.editingFinished.connect(self._on_iso_edit)

        # ── 第 8 行：透明度（滑块 + 精确输入框，与等值面行上下对齐）──
        self._op_sld = QSlider(Qt.Horizontal)
        self._op_sld.setRange(0, 100)
        # 滑块值直接表示“透明度(%)”，与 opacity 互补：opacity = 1 - 值/100
        self._op_sld.setValue(int((1.0 - _RENDER_DEFAULTS['OrbitalOpacity']) * 100))
        self._op_sld.setMinimumWidth(200)
        self._op_sld.setToolTip(
            "等值面透明度：0% = 完全不透明，100% = 完全透明。\n"
            "VESTA / CYLview / MolStudio 三个样式为线性（滑块值即表面 alpha）；\n"
            "其余样式的半透明观感沿用 IboView 的光照调制（亮处实、暗处虚）。")
        self._op_sld.valueChanged.connect(self._on_op)
        # 初值取滑块当前值：此前写死 "20"，而滑块按默认不透明度算出来是 21，
        # 一进界面框里就比滑块少 1（拖动一次后才对上）
        self._op_edit = QLineEdit(str(self._op_sld.value()))
        self._op_edit.setValidator(QIntValidator(0, 100))
        self._op_edit.setFixedWidth(NUM_EDIT_W)    # 与其余滑块输入框同宽
        self._op_edit.setToolTip("透明度 0-100%（精确输入）")
        self._op_edit.editingFinished.connect(self._on_op_edit)

        self._sec_vbox("iso").addWidget(_row(_lbl("等值面大小:"), (self._iso_sld, 1),
                          self._iso_edit))
        self._sec_vbox("iso").addWidget(_row(_lbl("透明度:"), (self._op_sld, 1),
                          self._op_edit))

        # 透明合成算法：WBOIT（自研）/ 深度剥离（独立实现，Everitt 2001）/ 排序混合
        self._transp_cb = QComboBox()
        self._transp_cb.addItem("WBOIT（加权混合，单趟）", "oit")
        self._transp_cb.addItem("深度剥离（多趟）", "peel")
        self._transp_cb.addItem("排序混合（画家算法）", "sorted")
        self._transp_cb.setToolTip(
            "透明等值面的合成方式：\n"
            "· WBOIT — 单趟渲染，按深度与不透明度加权累加（McGuire & Bavoil 2013），"
            "本项目自研路径，开销恒定。\n"
            "· 深度剥离 — 多趟逐层剥离（Everitt 2001，本项目独立实现），"
            "合成最精确，开销随层数线性增长。\n"
            "· 排序混合 — 按三角形深度从远到近绘制，最省资源，复杂轨道可能出现穿插错误。\n"
            "所选模式不可用时自动回退到另一种。")
        self._transp_cb.currentIndexChanged.connect(self._on_transparency_mode)
        # 条目的中文名很长（「WBOIT（加权混合，单趟）」），QComboBox 的
        # minimumSizeHint 按最长条目算到 229px，同行再放网格精度 + 剥离层数就
        # 顶破栏宽。改成「按最小内容长度」调尺寸：宽度下限压到 ~10 个字符，
        # 实际宽度仍由拉伸决定，常规窗口下照常铺开（不会被压窄）。
        self._transp_cb.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLength)
        self._transp_cb.setMinimumContentsLength(10)

        # WBOIT 深度衰减：0 = 前后等权（偏暗），越大越"前层主导"（越通透）
        self._oit_falloff_sld = QSlider(Qt.Horizontal)
        self._oit_falloff_sld.setRange(0, 120)      # 0.0 .. 12.0
        self._oit_falloff_sld.setValue(40)          # 默认 4.0
        # 不再限宽（原先 110px 是与「剥离层数」并排时的紧凑写法；现独占一行，
        # 放开使其与其余滑块行一样铺满整行，调节也更细）
        self._oit_falloff_sld.setToolTip(
            "WBOIT 深度衰减强度：\n"
            "· 数值越大 → 越靠前的等值面占比越高，越通透。\n"
            "· 数值越小 → 前后等权，后层（经雾化的偏亮片元）掺得越多，整体偏暗。\n"
            "默认 4.0。")
        self._oit_falloff_sld.valueChanged.connect(self._on_oit_falloff)

        # 深度剥离趟数：仅 peel 模式有效（1..8 趟）
        self._peel_layers_spin = QSpinBox()
        self._peel_layers_spin.setRange(1, 8)
        self._peel_layers_spin.setValue(4)
        self._peel_layers_spin.setFixedWidth(self._NUM_W)   # 与其余数值框同宽
        self._peel_layers_spin.setToolTip(
            "深度剥离趟数上限（1-8，默认 4）：\n"
            "越多层交叠越精确，开销随趟数线性增长。")
        self._peel_layers_spin.setEnabled(False)
        self._peel_layers_spin.valueChanged.connect(self._on_peel_layers)

        # ── 第 9 行：网格精度 ──
        self._grid_quality_cb = QComboBox()
        self._grid_quality_cb.addItems(
            [_cv(t) for t in ("低 (1)", "中 (2)", "高 (3)")])
        self._grid_quality_cb.setCurrentIndex(1)
        self._grid_quality_cb.setToolTip("生成轨道 cube 的网格密度：1=稀疏，2=中等，3=精细")
        # 不再限宽：原先 100px 上限是与「透明合成」「剥离层数」并排时的紧凑写法。
        # 独占一行后若还留着上限，QHBoxLayout 会把"没控件能吸收的多余宽度"
        # 摊到控件之间的间距上，行首标签被推离标签列（实测被推到 x=120）。

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
        # 上限收到 190px：给右侧新增的数值输入框腾出位置，整行仍在栏宽内
        self._orb_outline_sld.setMaximumWidth(190)
        self._orb_outline_sld.valueChanged.connect(self._on_orb_outline_width)
        # 粗细数值：原为只读 QLabel，改成与其余滑块一致的可编辑输入框
        self._orb_outline_val = _num_edit(
            self._orb_outline_sld,
            tip="等值面描边粗细（0.01 – 0.99，窄带阈值宽度）")
        # 描边颜色（默认黑色），按钮色块显示当前颜色
        self._orb_outline_color = (0.0, 0.0, 0.0)
        # 描边颜色：无文字色块，与相位行色块同款圆角矩形
        self._orb_outline_color_btn = QPushButton()
        self._orb_outline_color_btn.setObjectName("SmallBtn")
        self._orb_outline_color_btn.setFixedSize(26, 26)
        self._orb_outline_color_btn.setToolTip("设置等值面描边颜色（默认黑色）")
        self._orb_outline_color_btn.clicked.connect(self._on_orb_outline_color)
        self._style_swatch(self._orb_outline_color_btn, self._orb_outline_color)

        # 透明合成 / 网格精度 / 剥离层数：原先三组参数挤在一行（实测三段的
        # 起点是 x = 118/248/457），拆成三行标准行 —— 每行一个参数，扫视成本
        # 最低，标签列也不再被行内标签撕开。
        self._sec_vbox("iso").addWidget(
            _row(_lbl("透明合成:"), (self._transp_cb, 1)))
        self._sec_vbox("iso").addWidget(
            _row(_lbl("网格精度:"), (self._grid_quality_cb, 1)))
        self._sec_vbox("iso").addWidget(
            _row(_lbl("剥离层数:"), self._peel_layers_spin))
        # WBOIT 衰减单独一行（仅 oit 模式生效）：原先与剥离层数并排，两个模式各自
        # 的参数挤在一行，容易看错哪个归哪个；分开后各占一行，置灰关系也更清楚
        # （见 _on_transparency_mode / _sync_style_ui）。
        self._oit_falloff_edit = _num_edit(
            self._oit_falloff_sld, scale=10.0, decimals=1,
            tip="WBOIT 深度衰减（0.0 – 12.0，越大越通透）")
        self._sec_vbox("iso").addWidget(_row(_lbl("WBOIT 衰减:"), (self._oit_falloff_sld, 1),
                          self._oit_falloff_edit))
        # 默认透明合成 = 深度剥离（与 glw 默认一致），对应参数控件启用
        self._transp_cb.blockSignals(True)
        self._transp_cb.setCurrentIndex(self._transp_cb.findData("peel"))
        self._transp_cb.blockSignals(False)
        self._oit_falloff_sld.setEnabled(False)
        self._oit_falloff_edit.setEnabled(False)
        self._peel_layers_spin.setEnabled(True)
        # 等值面描边：原先一行塞了 6 个元素（复选框当标签 + 行内「粗细:」+
        # 被限宽到 190px 的滑块 + 数值框 + 行内「描边颜色:」+ 色块），拆成
        # 三行标准行。复选框的文字挪到行首标签列（_promote_chk），
        # 这样「等值面描边 / 描边粗细 / 描边颜色」三行的竖线才对齐。
        self._sec_vbox("iso").addWidget(
            _row(self._promote_chk(self._orb_outline_chk),
                 self._orb_outline_chk))
        self._sec_vbox("iso").addWidget(
            _row(_lbl("粗细:"), (self._orb_outline_sld, 1),
                 self._orb_outline_val))
        self._sec_vbox("iso").addWidget(
            _row(_lbl("描边颜色:"), self._orb_outline_color_btn))

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
        # 色轮组：原先四种东西挤一行（启用勾选 + 84px 色轮 + 行内「相位配色:」
        # + 下拉 + 重置），拆成三行 —— 启用勾选、相位配色+重置、色轮（独占一行居中）。
        self._sec_vbox("phase").addWidget(
            _row(self._promote_chk(self._wheel_en_chk), self._wheel_en_chk))
        self._sec_vbox("phase").addWidget(
            _row(_lbl("相位配色:"), (self._phase_scheme_cmb, 1),
                 self._wheel_btn))
        self._sec_vbox("phase").addWidget(
            _row(None, self._color_wheel, None))
        # 翻转相位 / 正相位 / 负相位：原先靠两段弹性空白把三组均匀铺开
        # （实测 x = 0/209/459），拆成三行标准行。
        self._sec_vbox("phase").addWidget(
            _row(_lbl(""), self._flip_phase_btn))
        self._sec_vbox("phase").addWidget(
            _row(_lbl("正相位:"), self._phase_pos_btn))
        self._sec_vbox("phase").addWidget(
            _row(_lbl("负相位:"), self._phase_neg_btn))
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

        # 原先「灯光: 光源设置… …… 样式: 保存… 载入…」是一行两件事，
        # 现在光源设置留在「光照与材质」节，样式 I/O 移到顶部固定条。
        self._sec_vbox("light").addWidget(_row(_lbl("灯光:"), self._light_btn))

        # ── 球棍模型：统一规格网格，直接挂到「原子与键」分节 ──
        gi_a = self._sec_grid("atoms")

        self._lbl_atom_r = QLabel()
        self._lbl_atom_r.setText(self._cv_bind(self._lbl_atom_r, "原子半径:"))
        gi_a.addWidget(self._lbl_atom_r, 0, 0)
        self._atom_scale_sld = QSlider(Qt.Horizontal)
        self._atom_scale_sld.setRange(20, 400)
        self._atom_scale_sld.setValue(168)
        self._atom_scale_sld.setMinimumWidth(200)
        self._atom_scale_sld.valueChanged.connect(self._on_atom_scale_sld)
        gi_a.addWidget(self._atom_scale_sld, 0, 1)
        self._atom_scale_edit = QLineEdit("1.68")
        self._atom_scale_edit.setValidator(QDoubleValidator(0.20, 4.00, 2))
        self._atom_scale_edit.setMaximumWidth(64)
        self._atom_scale_edit.editingFinished.connect(self._on_atom_scale_edit)
        gi_a.addWidget(self._atom_scale_edit, 0, 2)
        # 行尾：按元素单独调节原子球半径
        self._btn_elem_r = QPushButton("元素半径")
        self._btn_elem_r.setObjectName("SmallBtn")
        self._btn_elem_r.setToolTip(
            "单独调节当前结构里每个元素原子球的半径倍率（0.2–4.0）\n"
            "只改变显示球径，不改坐标与键长判定")
        self._btn_elem_r.clicked.connect(self._open_element_radii_dialog)
        gi_a.addWidget(self._btn_elem_r, 0, 3)

        self._outline_color = (0.0, 0.0, 0.0)   # 默认黑边

        self._lbl_bond = QLabel()
        self._lbl_bond.setText(self._cv_bind(self._lbl_bond, "化学键:"))
        gi_a.addWidget(self._lbl_bond, 1, 0)
        self._bond_scale_sld = QSlider(Qt.Horizontal)
        self._bond_scale_sld.setRange(20, 400)
        self._bond_scale_sld.setValue(200)
        self._bond_scale_sld.setMinimumWidth(200)
        self._bond_scale_sld.valueChanged.connect(self._on_bond_scale_sld)
        gi_a.addWidget(self._bond_scale_sld, 1, 1)
        self._bond_scale_edit = QLineEdit("2.00")
        self._bond_scale_edit.setValidator(QDoubleValidator(0.20, 4.00, 2))
        self._bond_scale_edit.setMaximumWidth(64)
        self._bond_scale_edit.editingFinished.connect(self._on_bond_scale_edit)
        gi_a.addWidget(self._bond_scale_edit, 1, 2)
        # 行尾：化学键颜色 / 材质
        self._btn_bond_style = QPushButton("键样式")
        self._btn_bond_style.setObjectName("SmallBtn")
        self._btn_bond_style.setToolTip(
            "调节化学键颜色与材质（光泽 / 面亮度）")
        self._btn_bond_style.clicked.connect(self._open_bond_style_dialog)
        gi_a.addWidget(self._btn_bond_style, 1, 3)

        # ── 键收腰 ──
        self._lbl_thinning = QLabel()
        self._lbl_thinning.setText(self._cv_bind(self._lbl_thinning, "键收腰:"))
        gi_a.addWidget(self._lbl_thinning, 2, 0)
        self._thinning_sld = QSlider(Qt.Horizontal)
        self._thinning_sld.setRange(20, 100)   # 0.20 .. 1.00 (1.0 = 不收腰)
        self._thinning_sld.setValue(72)
        self._thinning_sld.setMinimumWidth(200)
        self._thinning_sld.valueChanged.connect(self._on_thinning_sld)
        gi_a.addWidget(self._thinning_sld, 2, 1)
        self._thinning_edit = QLineEdit("0.72")
        self._thinning_edit.setValidator(QDoubleValidator(0.20, 1.00, 2))
        self._thinning_edit.setMaximumWidth(64)
        self._thinning_edit.editingFinished.connect(self._on_thinning_edit)
        gi_a.addWidget(self._thinning_edit, 2, 2)

        # ── vdW 外壳：独立分节，统一规格网格 ──
        # 列约定：0 = 标签、1 = 滑块/输入（吃满余量）、2 = 数值框、3 = 行尾按钮。
        gi_v = self._sec_grid("vdw")

        # 开关行（四个复选框一行）
        self._vdw_mode_chk = QCheckBox()
        self._vdw_mode_chk.setText(self._cv_bind(self._vdw_mode_chk, "范德华半径"))
        self._vdw_mode_chk.setToolTip(
            "开启后原子直接以范德华半径（Bondi 1964 表）显示，而非默认绘制半径")
        self._vdw_mode_chk.stateChanged.connect(self._on_vdw_mode)

        self._vdw_shell_chk = QCheckBox()
        self._vdw_shell_chk.setText(self._cv_bind(self._vdw_shell_chk, "vdW 外壳"))
        self._vdw_shell_chk.setToolTip(
            "在正常球棍模型之上叠加半透明范德华半径球壳（元素色，体现空间包围）")
        self._vdw_shell_chk.stateChanged.connect(self._on_vdw_shell)

        self._vdw_outline_chk = QCheckBox()
        self._vdw_outline_chk.setText(self._cv_bind(self._vdw_outline_chk, "外壳描边"))
        self._vdw_outline_chk.setToolTip("vdW 球面剪影描边（独立于原子描边，单独控制）")
        self._vdw_outline_chk.stateChanged.connect(self._on_vdw_outline)

        # 「仅选中片段」子开关：外壳只覆盖框选/点选的原子片段
        self._vdw_sel_only_chk = QCheckBox()
        self._vdw_sel_only_chk.setText(self._cv_bind(self._vdw_sel_only_chk, "仅选中片段"))
        self._vdw_sel_only_chk.setToolTip(
            "IGMH 片段式：Shift+左键拖框框选原子归入片段（增量），"
            "vdW 外壳只画片段内的原子。片段集合持久保留——清除画布选中、"
            "取消高亮都不影响已加的壳；右键菜单或「清除」按钮可清空片段")
        self._vdw_sel_only_chk.setEnabled(False)   # 外壳未开启时不可用
        self._vdw_sel_only_chk.stateChanged.connect(self._on_vdw_sel_only)
        # 外壳开关联动「仅选中片段」可用性
        self._vdw_shell_chk.toggled.connect(self._vdw_sel_only_chk.setEnabled)

        # 四个开关原先是横向挤在一行（文字当标签、左对齐），与其余各行的
        # 标签列不在一条竖线上。改成四行标准开关行：文字进标签列，复选框留空。
        # 行号用 0..3，滑块行整体后移到 4..7（见下）。
        for _i, _chk in enumerate((self._vdw_mode_chk, self._vdw_shell_chk,
                                   self._vdw_outline_chk,
                                   self._vdw_sel_only_chk)):
            gi_v.addWidget(self._promote_chk(_chk), _i, 0)
            gi_v.addWidget(_chk, _i, 1)

        # vdW 半径比例
        self._lbl_vdw_r = QLabel()
        self._lbl_vdw_r.setText(self._cv_bind(self._lbl_vdw_r, "vdW 半径:"))
        self._lbl_vdw_r.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        gi_v.addWidget(self._lbl_vdw_r, 4, 0)
        self._vdw_scale_sld = QSlider(Qt.Horizontal)
        self._vdw_scale_sld.setRange(50, 200)    # 0.50x ~ 2.00x（Bondi 表值 × 比例）
        self._vdw_scale_sld.setValue(100)        # 默认 1.00x（真实 vdW 半径）
        self._vdw_scale_sld.setMinimumWidth(220)
        self._vdw_scale_sld.setToolTip("缩放范德华半径（Bondi 表值 × 比例），对原子与外壳同时生效")
        self._vdw_scale_sld.valueChanged.connect(self._on_vdw_scale)
        gi_v.addWidget(self._vdw_scale_sld, 4, 1)
        self._vdw_scale_edit = QLineEdit("1.00")
        self._vdw_scale_edit.setValidator(QDoubleValidator(0.50, 2.00, 2))
        self._vdw_scale_edit.setMaximumWidth(64)
        self._vdw_scale_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._vdw_scale_edit.editingFinished.connect(self._on_vdw_scale_edit)
        gi_v.addWidget(self._vdw_scale_edit, 4, 2)

        # 外壳透明度（vdW 外壳勾选后生效）
        self._lbl_vdw_alpha = QLabel()
        self._lbl_vdw_alpha.setText(self._cv_bind(self._lbl_vdw_alpha, "外壳透明度:"))
        self._lbl_vdw_alpha.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        gi_v.addWidget(self._lbl_vdw_alpha, 5, 0)
        self._vdw_alpha_sld = QSlider(Qt.Horizontal)
        self._vdw_alpha_sld.setRange(2, 80)     # 0.02 ~ 0.80
        self._vdw_alpha_sld.setValue(20)
        self._vdw_alpha_sld.setMinimumWidth(220)
        self._vdw_alpha_sld.setToolTip("vdW 外壳不透明度（0.02 ~ 0.80，越小越透明）")
        self._vdw_alpha_sld.valueChanged.connect(self._on_vdw_alpha)
        gi_v.addWidget(self._vdw_alpha_sld, 5, 1)
        self._vdw_alpha_edit = QLineEdit("0.20")
        self._vdw_alpha_edit.setValidator(QDoubleValidator(0.02, 0.80, 2))
        self._vdw_alpha_edit.setMaximumWidth(64)
        self._vdw_alpha_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._vdw_alpha_edit.setToolTip("直接输入不透明度（0.02 ~ 0.80，回车生效）")
        self._vdw_alpha_edit.editingFinished.connect(self._on_vdw_alpha_edit)
        gi_v.addWidget(self._vdw_alpha_edit, 5, 2)

        # 外壳描边粗细（勾选「外壳描边」后生效；0.01 ~ 0.60 剪影带厚度）
        self._lbl_vdw_ow = QLabel()
        self._lbl_vdw_ow.setText(self._cv_bind(self._lbl_vdw_ow, "外壳描边粗细:"))
        self._lbl_vdw_ow.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        gi_v.addWidget(self._lbl_vdw_ow, 6, 0)
        self._vdw_ow_sld = QSlider(Qt.Horizontal)
        self._vdw_ow_sld.setRange(1, 60)        # 0.01 .. 0.60
        self._vdw_ow_sld.setValue(40)           # 默认 0.40
        self._vdw_ow_sld.setMinimumWidth(220)
        self._vdw_ow_sld.setToolTip("vdW 外壳描边粗细（0.01 ~ 0.60 剪影带厚度，越大越粗）")
        self._vdw_ow_sld.valueChanged.connect(self._on_vdw_outline_width)
        gi_v.addWidget(self._vdw_ow_sld, 6, 1)
        self._vdw_ow_edit = QLineEdit("0.40")
        self._vdw_ow_edit.setValidator(QDoubleValidator(0.01, 0.60, 2))
        self._vdw_ow_edit.setMaximumWidth(64)
        self._vdw_ow_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._vdw_ow_edit.setToolTip("直接输入描边带厚度（0.01 ~ 0.60，回车生效）")
        self._vdw_ow_edit.editingFinished.connect(self._on_vdw_outline_width_edit)
        gi_v.addWidget(self._vdw_ow_edit, 6, 2)

        # 片段原子编号输入行（IGMH 式）：输入 1-12,15 这类编号 → 点「vdW」
        # 按钮，这些原子加 vdW 外壳（与框选归入同一片段集合）
        self._lbl_vdw_frag = QLabel()
        self._lbl_vdw_frag.setText(self._cv_bind(self._lbl_vdw_frag, "片段:"))
        gi_v.addWidget(self._lbl_vdw_frag, 7, 0)
        self._vdw_frag_edit = QLineEdit()
        self._vdw_frag_edit.setPlaceholderText(
            self._cv_bind(self._vdw_frag_edit, "原子编号, 如 1-12,15",
                          "setPlaceholderText"))
        self._vdw_frag_edit.setToolTip(
            "输入要加 vdW 外壳的原子编号（1-based），支持逗号分隔与范围，"
            "如 1-12,15；点「vdW」按钮应用到画布。与 Shift+框选归入的是"
            "同一个片段集合")
        self._vdw_frag_edit.returnPressed.connect(self._on_vdw_frag_apply)
        gi_v.addWidget(self._vdw_frag_edit, 7, 1)
        self._vdw_frag_btn = QPushButton("vdW")
        self._vdw_frag_btn.setObjectName("SmallBtn")
        self._vdw_frag_btn.setToolTip("把输入框里的原子加入 vdW 片段并显示外壳")
        self._vdw_frag_btn.clicked.connect(self._on_vdw_frag_apply)
        gi_v.addWidget(self._vdw_frag_btn, 7, 2)
        # 清除 vdW 片段（IGMH 式片段集合的显式清空入口）
        self._vdw_frag_clear_btn = QPushButton()
        self._vdw_frag_clear_btn.setText(self._cv_bind(self._vdw_frag_clear_btn, "清除"))
        self._vdw_frag_clear_btn.setObjectName("SmallBtn")
        self._vdw_frag_clear_btn.setToolTip(
            "清空 vdW 片段原子集合；「仅选中片段」模式下外壳随之消失，"
            "可重新输入或框选添加")
        self._vdw_frag_clear_btn.clicked.connect(self._on_vdw_frag_clear)
        gi_v.addWidget(self._vdw_frag_clear_btn, 7, 3)

        # ── 成键阈值（已隐藏：使用 cub_viewer 中的默认值 1.0 / 1.3 / 0.4） ──
        # 保留底层回调（_on_brf_tight_edit / _on_brf_loose_edit / _on_dash_w_edit）
        # 与默认值，仅不显示控件。如需恢复，取消下方注释即可。
        # gi_a.addWidget(QLabel("成键阈值:"), 3, 0)

        # ── 成键模式（两类）：一律单键 / 按键长自动判定键型 ──
        self._lbl_bond_mode = QLabel()
        self._lbl_bond_mode.setText(self._cv_bind(self._lbl_bond_mode, "成键模式:"))
        self._lbl_bond_mode.setToolTip(
            "「一律单键」：检测到的键全部画成实线单键；\n"
            "「按键长自动判定」：用键长与单键共价半径和的比值推出\n"
            "单键 / 离域键(1.5) / 双键 / 三键（只对 C/N/O 之间的键生效）。\n"
            "右键逐键指定的键型优先于本模式")
        gi_a.addWidget(self._lbl_bond_mode, 3, 0)
        self._bond_mode_cb = QComboBox()
        self._bond_mode_cb.addItem("一律单键", "single")
        self._bond_mode_cb.addItem("按键长自动判定键型", "auto")
        self._bond_mode_cb.setMinimumWidth(150)
        self._bond_mode_cb.setToolTip(
            "见左侧说明；自动判定把 C=C / C=O / C≡C / 芳香环等按几何画成"
            "双键 / 三键 / 离域键")
        self._bond_mode_cb.currentIndexChanged.connect(self._on_bond_mode)
        gi_a.addWidget(self._bond_mode_cb, 3, 1, 1, 2)

        # ── 原子十字圆环（两条贴球大圆带，GL 着色器绘制；主控开关 + 控制面板） ──
        self._lbl_rings = QLabel()
        self._lbl_rings.setText(self._cv_bind(self._lbl_rings, "十字圆环:"))
        gi_a.addWidget(self._lbl_rings, 4, 0)
        self._crosshair_chk = QCheckBox()
        self._crosshair_chk.setText(self._cv_bind(self._crosshair_chk, "显示"))
        self._crosshair_chk.setChecked(False)
        self._crosshair_chk.setToolTip(
            "勾选后在每个原子球面画两条交叉的大圆环（十字效果）；"
            "未勾选则完全不显示")
        self._crosshair_chk.toggled.connect(self._on_crosshair)
        gi_a.addWidget(self._crosshair_chk, 4, 1)
        self._ring_btn = QPushButton()
        self._ring_btn.setText(self._cv_bind(self._ring_btn, "圆环设置…"))
        self._ring_btn.setObjectName("SmallBtn")
        self._ring_btn.setMaximumWidth(120)
        self._ring_btn.setToolTip(
            "弹出圆环控制面板：调两条环的方位角/俯仰角；勾选锁定后分子怎么转圆环都不转")
        self._ring_btn.clicked.connect(self._open_ring_dialog)
        gi_a.addWidget(self._ring_btn, 4, 2)
        # gi_a.addWidget(QLabel("实线"), 3, 1)
        # self._brf_tight_edit = QLineEdit("1.00")
        # self._brf_tight_edit.setValidator(QDoubleValidator(0.50, 2.00, 2))
        # self._brf_tight_edit.setMaximumWidth(54)
        # self._brf_tight_edit.editingFinished.connect(self._on_brf_tight_edit)
        # gi_a.addWidget(self._brf_tight_edit, 3, 2)
        # gi_a.addWidget(QLabel("虚线"), 3, 3)
        # self._brf_loose_edit = QLineEdit("1.30")
        # self._brf_loose_edit.setValidator(QDoubleValidator(0.50, 3.00, 2))
        # self._brf_loose_edit.setMaximumWidth(54)
        # self._brf_loose_edit.editingFinished.connect(self._on_brf_loose_edit)
        # gi_a.addWidget(self._brf_loose_edit, 3, 4)
        # gi_a.addWidget(QLabel("虚密"), 3, 5)
        # self._dash_w_edit = QLineEdit("0.40")
        # self._dash_w_edit.setValidator(QDoubleValidator(0.05, 1.00, 2))
        # self._dash_w_edit.setMaximumWidth(54)
        # self._dash_w_edit.editingFinished.connect(self._on_dash_w_edit)
        # gi_a.addWidget(self._dash_w_edit, 3, 6)

        # ── 虚线小圆球：大小 / 间隔 ──
        self._lbl_dot_size = QLabel()
        self._lbl_dot_size.setText(self._cv_bind(self._lbl_dot_size, "虚线大小:"))
        gi_a.addWidget(self._lbl_dot_size, 5, 0)
        self._dot_size_sld = QSlider(Qt.Horizontal)
        self._dot_size_sld.setRange(20, 400)    # ×0.2 .. ×4.0
        self._dot_size_sld.setValue(100)        # ×1.0
        self._dot_size_sld.setMinimumWidth(200)
        self._dot_size_sld.valueChanged.connect(self._on_dot_size_sld)
        gi_a.addWidget(self._dot_size_sld, 5, 1)
        self._dot_size_edit = QLineEdit("1.00")
        self._dot_size_edit.setValidator(QDoubleValidator(0.20, 4.00, 2))
        self._dot_size_edit.setMaximumWidth(64)
        self._dot_size_edit.editingFinished.connect(self._on_dot_size_edit)
        gi_a.addWidget(self._dot_size_edit, 5, 2)

        self._lbl_dot_spacing = QLabel()
        self._lbl_dot_spacing.setText(self._cv_bind(self._lbl_dot_spacing, "虚线间隔:"))
        gi_a.addWidget(self._lbl_dot_spacing, 6, 0)
        self._dot_spacing_sld = QSlider(Qt.Horizontal)
        self._dot_spacing_sld.setRange(30, 400)  # ×0.3 .. ×4.0
        self._dot_spacing_sld.setValue(100)      # ×1.0
        self._dot_spacing_sld.setMinimumWidth(200)
        self._dot_spacing_sld.valueChanged.connect(self._on_dot_spacing_sld)
        gi_a.addWidget(self._dot_spacing_sld, 6, 1)
        self._dot_spacing_edit = QLineEdit("1.00")
        self._dot_spacing_edit.setValidator(QDoubleValidator(0.30, 4.00, 2))
        self._dot_spacing_edit.setMaximumWidth(64)
        self._dot_spacing_edit.editingFinished.connect(self._on_dot_spacing_edit)
        gi_a.addWidget(self._dot_spacing_edit, 6, 2)

        # ── 原子描边 ──
        self._lbl_outline = QLabel()
        self._lbl_outline.setText(self._cv_bind(self._lbl_outline, "原子描边:"))
        gi_a.addWidget(self._lbl_outline, 7, 0)
        self._outline_chk = QCheckBox()
        self._outline_chk.setText(self._cv_bind(self._outline_chk, "启用"))
        self._outline_chk.setChecked(False)
        self._outline_chk.toggled.connect(self._on_outline_toggle)
        gi_a.addWidget(self._outline_chk, 7, 1)
        self._outline_color_btn = QPushButton()
        self._outline_color_btn.setText(self._cv_bind(self._outline_color_btn, "颜色"))
        self._outline_color_btn.setObjectName("SmallBtn")
        self._outline_color_btn.clicked.connect(self._on_outline_color)
        gi_a.addWidget(self._outline_color_btn, 7, 2)

        self._lbl_outline_w = QLabel()
        self._lbl_outline_w.setText(self._cv_bind(self._lbl_outline_w, "描边粗细:"))
        gi_a.addWidget(self._lbl_outline_w, 8, 0)
        self._outline_w_sld = QSlider(Qt.Horizontal)
        self._outline_w_sld.setRange(1, 600)
        self._outline_w_sld.setValue(400)   # 0.4：细档（窄带公式下 ≈1px 细线）
        self._outline_w_sld.setMinimumWidth(200)
        self._outline_w_sld.valueChanged.connect(self._on_outline_width)
        gi_a.addWidget(self._outline_w_sld, 8, 1)
        self._outline_w_lbl = QLabel("0.400")
        self._outline_w_lbl.setMaximumWidth(64)
        gi_a.addWidget(self._outline_w_lbl, 8, 2)

        # ── 背景色（导出/预览用）；导出图片/DPI/透明背景已移到画布下方一键样式行 ──
        # 以下归「背景与后处理」分节 —— 单独一个网格
        gi_p = self._sec_grid("post")
        self._lbl_bg = QLabel()
        self._lbl_bg.setText(self._cv_bind(self._lbl_bg, "背景色:"))
        gi_p.addWidget(self._lbl_bg, 9, 0)
        self._bg_color_btn = QPushButton()
        self._bg_color_btn.setText(self._cv_bind(self._bg_color_btn, "选择…"))
        self._bg_color_btn.setObjectName("SmallBtn")
        self._bg_color_btn.setToolTip("设置导出/预览的背景颜色")
        self._bg_color_btn.clicked.connect(self._on_bg_color)
        gi_p.addWidget(self._bg_color_btn, 9, 1)

        # 景深雾化（IboView Fade：远处蒙白雾）
        self._fade_chk = QCheckBox()
        self._fade_chk.setText(self._cv_bind(self._fade_chk, "景深雾化"))
        self._fade_chk.setChecked(True)
        self._fade_chk.setToolTip("关闭后远处原子/轨道不再因景深变淡发白")
        self._fade_chk.toggled.connect(self._on_fade_toggle)
        # 复选框文字挪到行首标签列（原先是"复选框当标签"、左对齐在 x=21，
        # 与其余右对齐标签不在同一条竖线上）。
        # ★ 注意 _promote_chk() 只返回"标签"，**复选框本体要自己再放进布局** ——
        #   漏了这一步复选框就整个不在界面上（程序里还在，isChecked() 照样能读，
        #   所以只会表现为"小方块不见了"这种肉眼可见、探针却测不到的回归）。
        gi_p.addWidget(self._promote_chk(self._fade_chk), 10, 0)
        # 雾化强度：场景最远处向白渐变的幅度（0..1）。
        # 分子/轨道的可见深度范围通常不大，弱档看不出差别，故给一个可调滑块。
        self._fade_sld = QSlider(Qt.Horizontal)
        # 0..200 → 雾化强度 0.0..2.0（1.0 = 最深处完全融入背景，>1 更强）
        self._fade_sld.setRange(0, 200)
        self._fade_sld.setValue(int(_RENDER_DEFAULTS.get('FogWidth', 0.3) * 100))
        self._fade_sld.setToolTip(
            "景深雾化强度（远处向背景色淡出）：\n"
            "0.6 = 场景最深处融入背景 60%，1.0 = 完全融入，最大 2.0（更强的空气透视）")
        self._fade_sld.valueChanged.connect(self._on_fade_strength)
        # 「标签 | 复选框 + 滑块」同一行：用横向容器把复选框和滑块打包放进
        # 控件列（跨 1~2 列），这样既保住标签列的竖线对齐，复选框也不会丢。
        _fog_h = QHBoxLayout()
        _fog_h.setContentsMargins(0, 0, 0, 0)
        _fog_h.setSpacing(self._COL_GAP)
        _fog_h.addWidget(self._fade_chk)
        _fog_h.addWidget(self._fade_sld, 1)
        gi_p.addLayout(_fog_h, 10, 1, 1, 2)

        # ── 后处理：超采样抗锯齿 + 边缘暗化 ──
        # 实时渲染的 QSurfaceFormat 是 samples=0（无 MSAA），轨道剪影与瓣间
        # 交界全靠这里消除锯齿；MSAA 又对透明层无效（不写深度），故用 SSAA。
        self._post_chk = QCheckBox()
        self._post_chk.setText(self._cv_bind(self._post_chk, "后处理抗锯齿"))
        self._post_chk.setChecked(True)
        self._post_chk.setToolTip(
            "整帧先按倍率放大离屏渲染再降采样（超采样抗锯齿）。\n"
            "实时画布没有 MSAA，且 MSAA 对半透明等值面无效，故用这种方式；\n"
            "开销按倍率平方增长，卡顿时降到 1.0× 或关闭。")
        self._post_chk.toggled.connect(self._on_post_toggle)
        # 同「景深雾化」：_promote_chk 只给标签，复选框本体必须自己放回去
        gi_p.addWidget(self._promote_chk(self._post_chk), 11, 0)

        self._post_scale_cb = QComboBox()
        self._post_scale_cb.addItems(["1.0×", "1.5×", "2.0×"])
        self._post_scale_cb.setCurrentIndex(1)
        self._post_scale_cb.setToolTip("超采样倍率（1.0× = 不做超采样）")
        self._post_scale_cb.currentIndexChanged.connect(self._on_post_scale)
        _aa_h = QHBoxLayout()
        _aa_h.setContentsMargins(0, 0, 0, 0)
        _aa_h.setSpacing(self._COL_GAP)
        _aa_h.addWidget(self._post_chk)
        _aa_h.addWidget(self._post_scale_cb, 1)
        gi_p.addLayout(_aa_h, 11, 1)

        # 色彩空间（B 方案）：光照与透明混合改在线性域进行，后处理转回 sRGB。
        # 默认关（与旧版观感逐位一致）。
        self._linear_chk = QCheckBox()
        self._linear_chk.setText(self._cv_bind(self._linear_chk, "线性空间光照"))
        self._linear_chk.setChecked(False)
        self._linear_chk.setToolTip(
            "线性空间光照（B 方案）：\n"
            "· 颜色先转线性再计算光照，透明混合（等值面叠加/雾化/描边）\n"
            "  全程线性域，最后统一转回 sRGB 显示\n"
            "· 半透明等值面的叠加不再发灰/发奶，正负瓣交界更饱和\n"
            "· 中间调整体会略微变亮（gamma 响应变化，属正常现象）\n"
            "· 关闭 = sRGB 直通，与旧版观感完全一致")
        self._linear_chk.toggled.connect(self._on_linear_space)
        # 原先与「后处理抗锯齿」挤在网格同一行（x=381 的第二列），两件事互不相关；
        # 拆成自己的标准开关行（行号后移一位，见下面的批量 +1）。
        gi_p.addWidget(self._promote_chk(self._linear_chk), 12, 0)
        # 同「景深雾化」：_promote_chk 只给标签，复选框本体必须自己放回去
        gi_p.addWidget(self._linear_chk, 12, 1)

        # 边缘暗化（IboView FakeAA 思路）：可见边界压暗，读作接触阴影
        self._lbl_post_edge = QLabel()
        self._lbl_post_edge.setText(
            self._cv_bind(self._lbl_post_edge, "边缘暗化:"))
        gi_p.addWidget(self._lbl_post_edge, 13, 0)
        self._post_edge_sld = QSlider(Qt.Horizontal)
        self._post_edge_sld.setRange(0, 80)
        self._post_edge_sld.setValue(0)      # 默认关：它是"变脏"感的来源
        self._post_edge_sld.setMinimumWidth(160)
        self._post_edge_sld.setToolTip("按可见边界（瓣与瓣、等值面与原子）压暗的强度")
        self._post_edge_sld.valueChanged.connect(self._on_post_edge)
        gi_p.addWidget(self._post_edge_sld, 13, 1)
        self._post_edge_val = QLabel("0.00")
        self._post_edge_val.setMaximumWidth(64)
        gi_p.addWidget(self._post_edge_val, 13, 2)

        # 暗化宽度：1px 细轮廓线 ↔ 4px 柔和接触阴影
        self._lbl_post_r = QLabel()
        self._lbl_post_r.setText(self._cv_bind(self._lbl_post_r, "阴影宽度:"))
        gi_p.addWidget(self._lbl_post_r, 14, 0)
        self._post_r_sld = QSlider(Qt.Horizontal)
        self._post_r_sld.setRange(10, 50)
        self._post_r_sld.setValue(20)
        self._post_r_sld.setMinimumWidth(160)
        self._post_r_sld.setToolTip("暗化向物体内侧铺开的宽度（像素）：小=细轮廓，大=柔和阴影")
        self._post_r_sld.valueChanged.connect(self._on_post_radius)
        gi_p.addWidget(self._post_r_sld, 14, 1)
        self._post_r_val = QLabel("2.0")
        self._post_r_val.setMaximumWidth(64)
        gi_p.addWidget(self._post_r_val, 14, 2)

        # 环境光遮蔽（SSAO）：需要后处理开启（深度预通道 + AO 都挂在后处理流程里）
        self._lbl_ao = QLabel()
        self._lbl_ao.setText(self._cv_bind(self._lbl_ao, "环境光遮蔽:"))
        self._lbl_ao.setToolTip("屏幕空间遮蔽：凹槽、原子与等值面接触处变暗，立体感的主要来源")
        gi_p.addWidget(self._lbl_ao, 15, 0)
        self._ao_sld = QSlider(Qt.Horizontal)
        self._ao_sld.setRange(0, 100)
        self._ao_sld.setValue(0)      # 默认关：凸面上本就无 AO
        self._ao_sld.setMinimumWidth(160)
        self._ao_sld.setToolTip("环境光遮蔽强度（0 = 关闭，同时省掉深度预通道）")
        self._ao_sld.valueChanged.connect(self._on_ao)
        gi_p.addWidget(self._ao_sld, 15, 1)
        self._ao_val = QLabel("0.00")
        self._ao_val.setMaximumWidth(64)
        gi_p.addWidget(self._ao_val, 15, 2)

        # 色调映射（ACES filmic）+ 暗角：出图"成品感"
        self._lbl_tone = QLabel()
        self._lbl_tone.setText(self._cv_bind(self._lbl_tone, "色调映射:"))
        self._lbl_tone.setToolTip("ACES 胶片曲线：高光滚降不再死白，中间调轻微提亮")
        gi_p.addWidget(self._lbl_tone, 16, 0)
        self._tone_sld = QSlider(Qt.Horizontal)
        self._tone_sld.setRange(0, 100)
        self._tone_sld.setValue(0)       # 默认关：LDR 上做只会降对比、发灰
        self._tone_sld.setMinimumWidth(160)
        self._tone_sld.valueChanged.connect(self._on_tone)
        gi_p.addWidget(self._tone_sld, 16, 1)
        self._tone_val = QLabel("0.00")
        self._tone_val.setMaximumWidth(64)
        gi_p.addWidget(self._tone_val, 16, 2)

        self._lbl_vig = QLabel()
        self._lbl_vig.setText(self._cv_bind(self._lbl_vig, "暗角:"))
        self._lbl_vig.setToolTip("画面四角轻微压暗，视线收拢到中心")
        gi_p.addWidget(self._lbl_vig, 17, 0)
        self._vig_sld = QSlider(Qt.Horizontal)
        self._vig_sld.setRange(0, 50)
        self._vig_sld.setValue(0)        # 默认关：只压背景四角，对分子无益
        self._vig_sld.setMinimumWidth(160)
        self._vig_sld.valueChanged.connect(self._on_vig)
        gi_p.addWidget(self._vig_sld, 17, 1)
        self._vig_val = QLabel("0.00")
        self._vig_val.setMaximumWidth(64)
        gi_p.addWidget(self._vig_val, 17, 2)

        # AO 采样半径（像素）：小 = 只在紧贴的接触处出阴影，大 = 整体发灰
        self._lbl_ao_r = QLabel()
        self._lbl_ao_r.setText(self._cv_bind(self._lbl_ao_r, "AO 半径:"))
        self._lbl_ao_r.setToolTip("采样环半径（屏幕像素）。分子越密集、想要越宽的接触阴影就调大")
        gi_p.addWidget(self._lbl_ao_r, 18, 0)
        self._ao_r_sld = QSlider(Qt.Horizontal)
        self._ao_r_sld.setRange(40, 320)
        self._ao_r_sld.setValue(80)
        self._ao_r_sld.setMinimumWidth(160)
        self._ao_r_sld.setToolTip("AO 采样半径（像素，4 – 32）")
        self._ao_r_sld.valueChanged.connect(self._on_ao_radius)
        gi_p.addWidget(self._ao_r_sld, 18, 1)
        self._ao_r_val = QLabel("8.0")
        self._ao_r_val.setMaximumWidth(64)
        gi_p.addWidget(self._ao_r_val, 18, 2)

        # ── 收尾：顶部固定条 → 统一标签列/行高 → 恢复展开状态 ──
        # 顶部固定条放在最后建：样式保存/载入与「重置视角」的按钮要到上面
        # 才创建出来；insertWidget(0) 把它钉在参数区最顶端，不随长列表滚走。
        self._build_param_topbar(outer)
        self._finalize_param_grid()
        self._restore_section_state()

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

    def _refresh_num_edits(self):
        """把所有「滑块 → 数值输入框」按滑块当前值刷一遍文字。

        `_sync_material_ui` / `_sync_style_ui` 里为了避免重复触发应用逻辑，
        给滑块 setValue 时都 blockSignals(True)，于是输入框收不到
        valueChanged —— 样式载入后必须显式补这一次刷新，否则滑块已经跳到
        新值而框里还是旧数字。
        """
        for sld, ed, fmt in getattr(self, "_num_edits", []):
            if not ed.hasFocus():
                ed.setText(fmt(sld.value()))

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

    def load_cube(self, path, iso=None, style_name=None, keep_style=False):
        """在画布中加载并渲染一个 cube 文件。

        keep_style=True：调用方已先套好样式（如一键样式 HoukMol3d），本方法
        不再用面板「等值面配色」下拉覆盖它。必须如此是因为等值面网格在后台
        线程算、颜色在**发起计算的那一刻**就烘焙进顶点色（见
        ``_compute_orbitals_meshes``），载入后再套样式只能改到旧表面，新算
        出来的仍是下拉默认的配色（实测表现：双击轨道出来是灰透色）。
        """
        if self.glw is None or not path or not os.path.isfile(path):
            return False

        # 记录路径（顶部下拉框已移除，仅维护列表）
        if path not in self._cube_paths:
            self._cube_paths.append(path)

        if style_name:
            self.set_style_name(style_name)
        elif not keep_style:
            self.glw.set_style(STYLE_NAMES[self._style_cb.currentIndex()])

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
        """设置渲染质量: 'low' / 'medium' / 'high'。

        low 档关闭现代 OIT（退化到排序混合，最省资源）；其余档用深度剥离
        （默认，Everitt 2001；不可用时自动回退 WBOIT/排序混合）。
        """
        if self.glw is not None:
            self.glw.set_transparency_mode("sorted" if level == "low" else "peel")

    def set_mol_style_name(self, name):
        """设置分子风格（球棍 / 飘带 / 仅球 等），接受显示名或原名。"""
        self._set_mol_style_by_name(name)

    def set_shininess_name(self, name):
        """设置光泽（兼容历史预设名）。"""
        if self.glw is not None:
            self.glw.set_shininess(name)

    def set_background_color(self, color):
        """设置背景颜色，接受 '#rrggbb' 或 (r,g,b) 0-255。"""
        if self.glw is not None:
            self.glw.set_background(_parse_color(color))

    def set_fade_enabled(self, enabled):
        """景深雾化（IboView Fade：远处蒙白雾）开关。默认开启以保留原貌。"""
        if self.glw is not None:
            self.glw.set_fade_enabled(bool(enabled))
        if hasattr(self, "_fade_chk"):
            self._fade_chk.blockSignals(True)
            self._fade_chk.setChecked(bool(enabled))
            self._fade_chk.blockSignals(False)
        if hasattr(self, "_fade_sld"):
            self._fade_sld.setEnabled(bool(enabled))

    def set_fog_strength(self, value):
        """景深雾化强度 0..1（场景最远处蒙白的幅度）。"""
        if self.glw is not None:
            self.glw.set_fog_strength(float(value))
        if hasattr(self, "_fade_sld"):
            self._fade_sld.blockSignals(True)
            self._fade_sld.setValue(int(round(float(value) * 100)))
            self._fade_sld.blockSignals(False)

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
            # 样式自带的 GL 观感（IboView 系列 = 双瓣 Blinn + 原版寄存器/
            # 布光）会改写镜面模型与材质基准，面板控件必须跟着刷新，
            # 否则滑块显示旧值而画面已经变了。
            if hasattr(self, "_spec_model_cb"):
                self._sync_material_ui()

    # ── 出图观感预设（布光+材质+后处理+雾化+背景 打包切换）──────────
    def _on_look(self, idx):
        if self.glw is None or not (0 <= idx < len(LOOK_ITEMS)):
            return
        _disp, key = LOOK_ITEMS[idx]
        if not key:
            return
        st = look_state(key)
        if not st:
            return
        self.glw.apply_style_state(st)
        self._sync_after_look()
        self._set_status(f"已应用出图观感：{LOOK_PRESETS[key]['display']}")

    def _sync_after_look(self):
        """观感预设应用后把所有相关控件拉回画布当前值。

        `apply_style_state` 一次性改了布光/材质/后处理/雾化/背景，面板上对应
        的控件必须全部刷新，否则滑块显示旧值而画面已经变了。
        """
        if self.glw is None:
            return
        self._sync_style_ui()       # 光照/原子配色/光泽/尺寸/后处理/描边/透明度/相位
        self._sync_material_ui()    # 镜面模型/粗糙度/清漆/次表面/明暗柔和/半球
        self._sync_hemi_swatches()
        # 背景色（_sync_style_ui 未覆盖）——同步给颜色选择对话框的初值
        try:
            self._bg_rgba = tuple(float(x) for x in self.glw._bg[:4])
        except Exception:
            pass
        # 景深雾化：开关 + 强度
        if hasattr(self, "_fade_chk"):
            on = bool(getattr(self.glw, "_fade_enabled", True))
            self._fade_chk.blockSignals(True)
            self._fade_chk.setChecked(on)
            self._fade_chk.blockSignals(False)
            self._fade_sld.setEnabled(on)
        if hasattr(self, "_fade_sld"):
            self._fade_sld.blockSignals(True)
            self._fade_sld.setValue(int(round(float(self.glw.fog_strength()) * 100)))
            self._fade_sld.blockSignals(False)
        self._refresh_num_edits()

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

    def _on_gloss(self, value):
        if self.glw is not None:
            self.glw.set_gloss(value / 100.0)

    def _on_spec_model(self, index):
        """镜面/光照模型切换：0=GGX，1=Blinn-Phong，2=Clear-coat，3=Matcap。"""
        mode = {0: 1, 1: 0, 2: 2, 3: 3}.get(index, 1)
        if self.glw is not None:
            self.glw.set_spec_model(mode)
        self._rough_slider.setEnabled(mode in (1, 2))
        self._coat_rough_slider.setEnabled(mode == 2)
        self._coat_strength_slider.setEnabled(mode == 2)
        # 次表面散射 / 明暗柔和度都走多灯光照路径，Matcap 完全替代了光照 → 对其无效
        self._sss_slider.setEnabled(mode != 3)
        self._soft_term_sld.setEnabled(mode != 3)
        self._matcap_cb.setEnabled(mode == 3)

    def _on_sss(self, value):
        """次表面散射强度 0.0..1.0（0 = 关闭，走标准 Lambert）。"""
        if self.glw is not None:
            self.glw.set_sss_strength(value / 100.0)

    def _on_soft_term(self, value):
        """明暗交界线柔化 0.0..1.0（0 = 标准 Lambert，1 = Half-Lambert）。"""
        if self.glw is not None:
            self.glw.set_soft_term(value / 100.0)

    def _on_back_dim(self, value):
        """等值面背面调暗 0.10..1.00（1.00 = 关闭，0.80 = 默认体积感）。"""
        if self.glw is not None:
            self.glw.set_back_dim(value / 100.0)

    # ── 半球环境光（Hemisphere Lighting）──
    def _on_hemi(self, on):
        """半球环境光开关。"""
        self._hemi_sld.setEnabled(on)
        self._hemi_edit.setEnabled(on)
        self._hemi_top_btn.setEnabled(on)
        self._hemi_bot_btn.setEnabled(on)
        if self.glw is not None:
            self.glw.set_hemisphere(enabled=on)

    def _on_hemi_intensity(self, value):
        """半球环境光强度 0.0..1.0。"""
        if self.glw is not None:
            self.glw.set_hemisphere(intensity=value / 100.0)

    def _on_hemi_top_color(self):
        """选择天顶色（法线朝上时取的补光色）。"""
        cur = getattr(self, "_hemi_top_rgb", (0.18, 0.18, 0.18))
        col = QColorDialog.getColor(
            QColor(*(int(round(c * 255)) for c in cur)), self, "天顶色")
        if not col.isValid():
            return
        self._hemi_top_rgb = (col.redF(), col.greenF(), col.blueF())
        self._sync_hemi_swatches()
        if self.glw is not None:
            self.glw.set_hemisphere(top=self._hemi_top_rgb)

    def _on_hemi_bottom_color(self):
        """选择地面色（法线朝下时取的补光色）。"""
        cur = getattr(self, "_hemi_bottom_rgb", (0.035, 0.035, 0.035))
        col = QColorDialog.getColor(
            QColor(*(int(round(c * 255)) for c in cur)), self, "地面色")
        if not col.isValid():
            return
        self._hemi_bottom_rgb = (col.redF(), col.greenF(), col.blueF())
        self._sync_hemi_swatches()
        if self.glw is not None:
            self.glw.set_hemisphere(bottom=self._hemi_bottom_rgb)

    def _sync_hemi_swatches(self):
        """把天顶/地面色色块同步为当前颜色（与正/负相位色块同一画法）。"""
        if not hasattr(self, "_hemi_top_btn"):
            return
        self._style_swatch(
            self._hemi_top_btn,
            getattr(self, "_hemi_top_rgb", (0.18, 0.18, 0.18)))
        self._style_swatch(
            self._hemi_bot_btn,
            getattr(self, "_hemi_bottom_rgb", (0.035, 0.035, 0.035)))

    def _on_roughness(self, value):
        """GGX / Clear-coat 底层粗糙度（高光斑点大小）0.03..1.0。"""
        if self.glw is not None:
            self.glw.set_roughness(value / 100.0)

    def _on_coat_roughness(self, value):
        """Clear-coat 清漆层粗糙度 0.03..1.0。"""
        if self.glw is not None:
            self.glw.set_coat_roughness(value / 100.0)

    def _on_coat_strength(self, value):
        """Clear-coat 清漆层强度 0.0..2.0。"""
        if self.glw is not None:
            self.glw.set_coat_strength(value / 100.0)

    def _on_matcap(self, index):
        """Matcap 材质球预设切换。"""
        names = ("studio", "glossy", "matte", "metal")
        if self.glw is not None and 0 <= index < len(names):
            self.glw.set_matcap(names[index])

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

    def _open_element_radii_dialog(self):
        """弹出「元素半径」对话框：按当前结构中的元素单独调原子球半径倍率。"""
        if self.glw is None:
            return
        dlg = ElementRadiiDialog(self.glw, self)
        dlg.exec_()

    def _open_bond_style_dialog(self):
        """弹出「键样式」对话框：化学键颜色/材质（光泽、面亮度）、虚线样式
        （小圆球点阵 / 短圆柱段）、多重键几何（子键粗细、线间距；双/三键/
        离域键本身由画布右键菜单逐键指定）。"""
        if self.glw is None:
            return
        dlg = BondStyleDialog(self.glw, self)
        dlg.exec_()

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
        """sob-art 默认：等值面风格 sob-art + 内嵌 sob-art.json 的全量状态
        （SobArt 原子配色 / 四灯 / Blinn 镜面 / 光泽 0.77 / 次表面 0.3 /
        原子描边 / 白底 / 关雾化）。

        顺序与 IBOview/MolStudio 一致：先 reset 清掉 MolViewer 残留，再
        set_style 建立等值面材质与配色基线，最后整体套用 JSON 状态覆盖。
        """
        if self.glw is None:
            return
        self.glw.reset_molviewer_style()
        self.glw.set_style("sob-art")
        self.glw.apply_style_state(dict(_SOBART_STYLE))
        self._sync_style_ui()
        self._set_status("已应用默认样式 sob-art")

    def _apply_iboview_style(self):
        """一键应用默认样式 IBOview（内嵌自 gxnu_style-IBOVIEW.json）：
        CPK / 三光 Phong / 白底 / 相位紫-蓝 / **光泽 10%** / **等值面透明度 50%**
        / 无描边。

        等值面材质基线用 STYLES['iboview-purple-blue']（漫反射 0.48、
        镜面 1.0）而不是 ultra-glass：后者是"超透玻璃"风，surface_mat 漫
        反射只有 0.12，等值面主体几乎无色、只剩高光，叠淡相位色 + 白底会
        整体发白发淡。随后用 apply_style_state 套 JSON 状态覆盖（相位色、
        透明度、灯光方向等以导出值为准）。

        这里 set_style() 建立的着色寄存器基准，字典里的 style_regs 会再写
        一遍 —— 两者必须一致（都是 iboview-purple-blue 的 gl_regs）。
        """
        if self.glw is None:
            return
        self.glw.reset_molviewer_style()
        self.glw.set_style("iboview-purple-blue")
        self.glw.apply_style_state(dict(_IBOVIEW_STYLE))
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
        self._apply_light_state(_SOBART_LIGHT)
        self._sync_style_ui()
        self._set_status("已应用默认样式 IQmol（原子配色 GaussView）")

    def _apply_molstudio_style(self):
        """一键应用默认样式 MolStudio（内嵌自 MolStudio.json）。

        该字典是 get_style_state() 的**全量导出**，故除传统项外还包含镜面模型、
        粗糙度/清漆、次表面散射、明暗柔和度、半球环境光等全部材质参数。
        先 reset_molviewer_style() 清掉 MolViewer 预设残留，再整体套用 ——
        顺序不能反，否则 reset 会把存档值重新覆盖掉。
        """
        if self.glw is None:
            return
        self.glw.reset_molviewer_style()
        self.glw.apply_style_state(dict(_MOLSTUDIO_STYLE))
        self._sync_style_ui()
        self._set_status("已应用默认样式 MolStudio")

    def _apply_cylview_style(self):
        """一键应用默认样式 CYLview。

        与 MolStudio 同源（GaussView 配色 / 单光 / 白底 / 相位白-绿 / 全套材质），
        按 CYLview 观感改这几处：关闭景深雾化（fade=False）、关闭原子描边、
        原子半径 1.8、化学键半径 3.79、**氢原子球半径跟随键半径**（H 与键
        一样粗）、单光源方向与光晕按 light_style.json（光晕 0.5）。
        先 reset_molviewer_style() 清掉 MolViewer 预设残留，再整体套用 ——
        顺序不能反，否则 reset 会把存档值重新覆盖掉。
        """
        if self.glw is None:
            return
        self.glw.reset_molviewer_style()
        self.glw.apply_style_state(dict(_CYLVVIEW_STYLE))
        self._sync_style_ui()
        self._set_status(
            "已应用默认样式 CYLview（无雾化 / 无描边 / 原子 1.8 / 键 3.79 / "
            "氢与键一样粗）")

    def _apply_vesta_style(self):
        """一键应用样式 VESTA：MolStudio 的几何/光照 + VESTA 的配色。

        配色数据直接从 VESTA 安装目录的 elements.ini 取（见 vesta_colors.py）：
        95 个元素逐个覆盖成 VESTA 的原子色；化学键**不设统一键色**，即两端
        原子各占一半（VESTA 默认的 "Bicolor cylinder"，与 MolStudio 相同）。
        几何参数沿用 _MOLSTUDIO_STYLE，不跟随 VESTA 的球/键粗细。

        先 reset_molviewer_style() 清掉 MolViewer 预设残留（它同时会把统一键色
        清空），再整体套用 —— 顺序不能反，否则 reset 会把存档值重新覆盖掉。
        """
        if self.glw is None:
            return
        self.glw.reset_molviewer_style()
        self.glw.apply_style_state(dict(_VESTA_STYLE))
        self._sync_style_ui()
        self._set_status("已应用样式 VESTA（原子配色 = VESTA elements.ini，"
                         "化学键两端分色，同 VESTA 默认画法；等值面 = 正青 / 负黄，"
                         "不透明度 0.2，WBOIT 合成）")

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
        """测量开关：转发给画布（类型取左侧下拉；退出保留标注，可继续调整）。"""
        if self.glw is not None:
            self.glw.set_measure_mode(
                on, self._measure_kind_cb.currentData() or "dist")

    def _on_measure_kind(self, _idx=0):
        """测量类型（距离/键角/二面角）切换。"""
        if self.glw is not None:
            self.glw.set_measure_kind(
                self._measure_kind_cb.currentData() or "dist")

    def _sync_measure_ui(self, on, kind):
        """按 glw 的测量状态回填控件（晶体信息条那边改状态时也走这里）。"""
        cb = getattr(self, "_measure_kind_cb", None)
        if cb is not None:
            cb.blockSignals(True)
            try:
                idx = cb.findData(kind)
                if idx >= 0:
                    cb.setCurrentIndex(idx)
            finally:
                cb.blockSignals(False)
        btn = getattr(self, "_measure_btn", None)
        if btn is not None:
            btn.blockSignals(True)
            try:
                btn.setChecked(bool(on))
            finally:
                btn.blockSignals(False)

    def _on_measure_clear(self):
        """清除全部测量标注。"""
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

    def _apply_houkmol3d_style(self):
        """一键应用默认样式 HoukMol3d（内嵌自 HoukMol-3d.json）。

        与旧「HoukMol」是两套独立样式：本套为四光源 + Clear-coat 清漆
        （清漆粗糙度 0.97）+ 次表面散射 0.32 + 等值面半透明 0.48。
        字典是 get_style_state() 的全量导出，故不再额外 set_style /
        apply_ring_state —— 严格还原 JSON 描述的状态（圆环不在导出范围内，
        保持用户当前设置）。

        顺序：先 reset_molviewer_style() 清掉 MolViewer 预设残留，再整体
        套用；反过来 reset 会把存档值重新覆盖掉。
        """
        if self.glw is None:
            return
        self.glw.reset_molviewer_style()
        self.glw.apply_style_state(dict(_HOUKMOL3D_STYLE))
        self._sync_style_ui()
        self._set_status("已应用默认样式 HoukMol3d")

    def _save_style(self):
        if self.glw is None:
            return
        p, _ = save_file(self, "保存样式", "gxnu_style.json",
                         "JSON (*.json)")
        if not p:
            return
        try:
            st = self.glw.get_style_state()
            # 补上"画布状态之外、只存在于面板控件上"的那几项（见 _panel_style_state）
            st.update(self._panel_style_state())
            with open(p, "w", encoding="utf-8") as f:
                json.dump(st, f, ensure_ascii=False, indent=2)
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
            self._apply_panel_style_state(st)
            self._sync_style_ui()
            self._set_status(f"样式已载入: {os.path.basename(p)}")
        except Exception as e:
            QMessageBox.warning(self, "载入失败", str(e))

    # ── 面板侧样式状态（画布状态之外的那几项）──────────────────
    def _panel_style_state(self):
        """色轮/相位方案这类"只活在面板控件上"的样式状态。

        正/负相位**颜色**由 glw 存（`phase_pos` / `phase_neg`），但决定这些颜色
        的那几个控件（配色方案、翻转相位、启用色轮、色轮角度）在面板上。
        不一起存的话，载入后面面是对的、控件却显示旧状态 —— 用户再碰一下
        就会把画面跳回旧配色。
        """
        st = {}
        try:
            st["panel_phase_scheme"] = int(self._phase_scheme_cmb.currentIndex())
            st["panel_phase_flipped"] = bool(self._flip_phase_btn.isChecked())
            st["panel_wheel_enabled"] = bool(self._wheel_en_chk.isChecked())
            st["panel_wheel_hue"] = float(self._color_wheel.hue())
        except (AttributeError, RuntimeError):
            pass
        return st

    def _apply_panel_style_state(self, st):
        """把上面存的面板状态回填到控件上。

        全部 blockSignals：glw 的相位颜色已经由 `apply_style_state` 按保存值
        装好了，这里只是让控件与之一致，**不能**再触发一次"按色轮重算颜色"，
        否则会把载入的颜色又算没了。
        """
        if not isinstance(st, dict):
            return
        try:
            if "panel_phase_scheme" in st:
                cb = self._phase_scheme_cmb
                cb.blockSignals(True)
                cb.setCurrentIndex(int(st["panel_phase_scheme"]))
                cb.blockSignals(False)
                self._phase_scheme = int(st["panel_phase_scheme"])
            if "panel_phase_flipped" in st and \
                    bool(st["panel_phase_flipped"]) != \
                    bool(self._flip_phase_btn.isChecked()):
                # 翻转相位是"作用一次交换颜色"的按钮：保存时画面状态已含翻转，
                # 载入时若控件状态不一致，只同步控件与文字，**不再交换一次颜色**
                self._phase_flipped = bool(st["panel_phase_flipped"])
                b = self._flip_phase_btn
                b.blockSignals(True)
                b.setChecked(self._phase_flipped)
                b.blockSignals(False)
                b.setText("相位已翻 ✓" if self._phase_flipped else "翻转相位")
            if "panel_wheel_hue" in st:
                # set_hue 不发信号 → 只改色轮外观，不重算相位色
                self._color_wheel.set_hue(float(st["panel_wheel_hue"]))
            if "panel_wheel_enabled" in st:
                chk = self._wheel_en_chk
                chk.blockSignals(True)
                chk.setChecked(bool(st["panel_wheel_enabled"]))
                chk.blockSignals(False)
                self._wheel_enabled = bool(st["panel_wheel_enabled"])
                self._color_wheel.setEnabled(self._wheel_enabled)
            self._sync_phase_swatches()
        except (AttributeError, RuntimeError):
            pass

    def _sync_material_ui(self):
        """把「镜面模型」相关的全部控件同步为画布当前值。

        初始化与「载入样式」共用：载入样式时画布状态被整体替换，面板控件
        必须重新读取，否则滑块显示旧值而画面已经变了。
        """
        if self.glw is None:
            return
        _mode = int(getattr(self.glw, "_spec_model", 1))
        self._spec_model_cb.blockSignals(True)
        self._spec_model_cb.setCurrentIndex(
            {1: 0, 0: 1, 2: 2, 3: 3}.get(_mode, 0))
        self._spec_model_cb.blockSignals(False)
        try:
            _r = float(self.glw._sp.get('roughness', 0.45))
            _cr = float(self.glw._sp.get('coat_roughness', 0.10))
            _cs = float(self.glw._sp.get('coat_strength', 0.80))
            _ss = float(self.glw._sp.get('sss_strength', 0.0))
            _bd = float(self.glw._sp.get('back_dim', 0.8))
        except Exception:
            _r, _cr, _cs, _ss, _bd = 0.45, 0.10, 0.80, 0.0, 0.8
        for sld, v in ((self._rough_slider, _r),
                       (self._coat_rough_slider, _cr),
                       (self._coat_strength_slider, _cs),
                       (self._sss_slider, _ss),
                       (self._backdim_sld, _bd)):
            sld.blockSignals(True)
            sld.setValue(int(round(v * 100)))
            sld.blockSignals(False)
        # 明暗柔和度
        self._soft_term_sld.blockSignals(True)
        self._soft_term_sld.setValue(
            int(round(float(getattr(self.glw, "_soft_term", 0.0)) * 100)))
        self._soft_term_sld.blockSignals(False)
        # 半球环境光
        _he, _ht, _hb, _hi = self.glw.hemisphere()
        self._hemi_chk.blockSignals(True)
        self._hemi_chk.setChecked(bool(_he))
        self._hemi_chk.blockSignals(False)
        self._hemi_sld.blockSignals(True)
        self._hemi_sld.setValue(int(round(_hi * 100)))
        self._hemi_sld.blockSignals(False)
        self._hemi_top_rgb = tuple(_ht)
        self._hemi_bottom_rgb = tuple(_hb)
        self._sync_hemi_swatches()
        self._hemi_sld.setEnabled(bool(_he))
        self._hemi_edit.setEnabled(bool(_he))
        self._hemi_top_btn.setEnabled(bool(_he))
        self._hemi_bot_btn.setEnabled(bool(_he))
        # Matcap 预设
        try:
            _mn = self.glw.matcap()
        except Exception:
            _mn = "studio"
        self._matcap_cb.blockSignals(True)
        self._matcap_cb.setCurrentIndex(
            {"studio": 0, "glossy": 1, "matte": 2, "metal": 3}.get(_mn, 0))
        self._matcap_cb.blockSignals(False)
        # 启用状态按当前镜面模型设置。次表面散射与明暗柔和度都走多灯
        # 光照路径，Matcap 完全替代了光照 → 对它们无效。
        self._rough_slider.setEnabled(_mode in (1, 2))
        self._coat_rough_slider.setEnabled(_mode == 2)
        self._coat_strength_slider.setEnabled(_mode == 2)
        self._sss_slider.setEnabled(_mode != 3)
        self._soft_term_sld.setEnabled(_mode != 3)
        self._backdim_sld.setEnabled(_mode != 3)
        self._matcap_cb.setEnabled(_mode == 3)
        # 输入框跟随各自滑块的可用性（上面 setValue 都被 blockSignals 挡掉了
        # valueChanged，故末尾统一按滑块当前值刷一次文字）
        self._rough_edit.setEnabled(_mode in (1, 2))
        self._coat_rough_edit.setEnabled(_mode == 2)
        self._coat_strength_edit.setEnabled(_mode == 2)
        self._sss_edit.setEnabled(_mode != 3)
        self._soft_term_edit.setEnabled(_mode != 3)
        self._backdim_edit.setEnabled(_mode != 3)
        self._refresh_num_edits()

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
        self._shiny_slider.blockSignals(True)
        self._shiny_slider.setValue(int(getattr(self.glw, "_gloss", _GLOSS_DEFAULT) * 100))
        self._shiny_slider.blockSignals(False)
        # 原子/键 半径
        self._atom_scale_sld.blockSignals(True)
        self._atom_scale_sld.setValue(int(self.glw._atom_scale * 100))
        self._atom_scale_sld.blockSignals(False)
        self._atom_scale_edit.setText(f"{self.glw._atom_scale:.2f}")
        self._bond_scale_sld.blockSignals(True)
        self._bond_scale_sld.setValue(int(self.glw._bond_scale * 100))
        self._bond_scale_sld.blockSignals(False)
        self._bond_scale_edit.setText(f"{self.glw._bond_scale:.2f}")
        # 后处理（超采样抗锯齿 / 边缘暗化）
        self._sync_post_ui()
        # 成键模式（一律单键 / 按键长自动判定键型）
        try:
            bmode = self.glw.bond_mode()
        except Exception:
            bmode = "single"
        bm_idx = self._bond_mode_cb.findData(bmode)
        self._bond_mode_cb.blockSignals(True)
        self._bond_mode_cb.setCurrentIndex(max(bm_idx, 0))
        self._bond_mode_cb.blockSignals(False)
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
        # 透明合成：模式下拉 + 各模式参数（WBOIT 衰减 / 剥离层数）
        mode = getattr(self.glw, "_transparency_mode", "oit")
        idx = self._transp_cb.findData(mode)
        self._transp_cb.blockSignals(True)
        self._transp_cb.setCurrentIndex(idx if idx >= 0 else 0)
        self._transp_cb.blockSignals(False)
        fo = float(getattr(self.glw, "_oit_falloff", 4.0) or 4.0)
        self._oit_falloff_sld.blockSignals(True)
        self._oit_falloff_sld.setValue(int(round(fo * 10.0)))
        self._oit_falloff_sld.blockSignals(False)
        self._oit_falloff_sld.setEnabled(mode == "oit")
        self._oit_falloff_edit.setEnabled(mode == "oit")
        pl = int(getattr(self.glw, "_peel_layers", 4) or 4)
        self._peel_layers_spin.blockSignals(True)
        self._peel_layers_spin.setValue(max(1, min(8, pl)))
        self._peel_layers_spin.blockSignals(False)
        self._peel_layers_spin.setEnabled(mode == "peel")
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
        # 镜面模型 / 粗糙度 / 清漆 / 次表面 / 明暗柔和度 / 半球环境光
        # （放最后：这些都读 canvas 的 _sp，须等样式应用完再取）
        # 景深雾化：开关 + 强度。样式里 fade=False 时必须同步勾选框，
        # 否则界面显示"已开启"而画面已经关掉（CYLview 就是这种情况）。
        if hasattr(self, "_fade_chk"):
            on = bool(getattr(self.glw, "_fade_enabled", True))
            self._fade_chk.blockSignals(True)
            self._fade_chk.setChecked(on)
            self._fade_chk.blockSignals(False)
            self._fade_sld.setEnabled(on)
        if hasattr(self, "_fade_sld"):
            self._fade_sld.blockSignals(True)
            self._fade_sld.setValue(int(round(float(self.glw.fog_strength()) * 100)))
            self._fade_sld.blockSignals(False)
        # ── 以下控件原先漏同步：画布状态被 apply_style_state 换掉了，
        #    但界面还停在载入前的值（用户一看"没生效"，再碰一下就跳变）。
        #    逐控件往返审计 _style_roundtrip_probe.py 抓出来的。
        def _blk(wd):
            wd.blockSignals(True)
            return wd

        def _unblk(wd):
            wd.blockSignals(False)

        # 等值面配色
        sn = getattr(self.glw, "_style_name", None)
        if sn in STYLE_NAMES:
            cb = _blk(self._style_cb)
            cb.setCurrentIndex(STYLE_NAMES.index(sn))
            _unblk(cb)
        # 键收腰
        th = float(getattr(self.glw, "_bond_thinning", 1.0))
        s = _blk(self._thinning_sld)
        s.setValue(int(round(th * 100)))
        _unblk(s)
        self._thinning_edit.setText(f"{th:.2f}")
        # 虚线大小 / 间隔
        ds = float(getattr(self.glw, "_dot_size_scale", 1.0))
        s = _blk(self._dot_size_sld)
        s.setValue(int(round(ds * 100)))
        _unblk(s)
        self._dot_size_edit.setText(f"{ds:.2f}")
        dp = float(getattr(self.glw, "_dot_spacing_scale", 1.0))
        s = _blk(self._dot_spacing_sld)
        s.setValue(int(round(dp * 100)))
        _unblk(s)
        self._dot_spacing_edit.setText(f"{dp:.2f}")
        # 选中标记 + 呼吸
        shape = getattr(self.glw, "_sel_marker_shape", "wrap")
        if shape in self._SEL_MARKER_SHAPES:
            cb = _blk(self._sel_marker_cb)
            cb.setCurrentIndex(self._SEL_MARKER_SHAPES.index(shape))
            _unblk(cb)
        c = _blk(self._sel_pulse_chk)
        c.setChecked(bool(getattr(self.glw, "_sel_pulse_on", False)))
        _unblk(c)
        # vdW 六项（"仅选中片段"不属样式，但界面也要跟画布一致）
        c = _blk(self._vdw_mode_chk)
        c.setChecked(bool(getattr(self.glw, "_vdw_mode", False)))
        _unblk(c)
        c = _blk(self._vdw_shell_chk)
        c.setChecked(bool(getattr(self.glw, "_vdw_shell", False)))
        _unblk(c)
        c = _blk(self._vdw_sel_only_chk)
        c.setChecked(bool(getattr(self.glw, "_vdw_sel_only", False)))
        _unblk(c)
        c = _blk(self._vdw_outline_chk)
        c.setChecked(bool(getattr(self.glw, "_vdw_outline", False)))
        _unblk(c)
        vs = float(getattr(self.glw, "_vdw_scale", 1.0))
        s = _blk(self._vdw_scale_sld)
        s.setValue(int(round(vs * 100)))
        _unblk(s)
        self._vdw_scale_edit.setText(f"{vs:.2f}")
        va = float(getattr(self.glw, "_vdw_shell_alpha", 0.2))
        s = _blk(self._vdw_alpha_sld)
        s.setValue(int(round(va * 100)))
        _unblk(s)
        self._vdw_alpha_edit.setText(f"{va:.2f}")
        vw = float(getattr(self.glw, "_vdw_outline_width", 0.4))
        s = _blk(self._vdw_ow_sld)
        s.setValue(int(round(vw * 100)))
        _unblk(s)
        self._vdw_ow_edit.setText(f"{vw:.2f}")
        self._sync_material_ui()

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

    # 与 _sel_marker_cb 的条目顺序一一对应
    _SEL_MARKER_SHAPES = ("wrap", "sphere", "torus", "glow")

    def _on_sel_marker(self, idx):
        if self.glw is None:
            return
        shapes = self._SEL_MARKER_SHAPES
        name = shapes[idx] if 0 <= idx < len(shapes) else "wrap"
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

    def _on_oit_falloff(self, raw):
        k = raw / 10.0
        if self.glw is not None:
            self.glw.set_oit_falloff(k)

    def _on_peel_layers(self, n):
        """深度剥离趟数（1..8）；仅 peel 模式生效。"""
        if self.glw is not None:
            self.glw.set_peel_layers(n)

    def _on_transparency_mode(self, idx):
        """切换透明合成算法；只启用当前模式的参数控件。"""
        mode = self._transp_cb.itemData(idx) or "oit"
        self._oit_falloff_sld.setEnabled(mode == "oit")
        self._oit_falloff_edit.setEnabled(mode == "oit")
        self._peel_layers_spin.setEnabled(mode == "peel")
        if self.glw is not None:
            self.glw.set_transparency_mode(mode)
            if mode == "peel":
                self.glw.set_peel_layers(self._peel_layers_spin.value())

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
        from molstudio.panels.igmh_panel import compress_ranges
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
        from molstudio.panels.igmh_panel import parse_ranges
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
        a = val / 100.0
        self._vdw_alpha_edit.blockSignals(True)
        self._vdw_alpha_edit.setText(f"{a:.2f}")
        self._vdw_alpha_edit.blockSignals(False)
        if self.glw is not None and self._vdw_shell_chk.isChecked():
            self.glw.set_vdw_shell(True, a)

    def _on_vdw_alpha_edit(self):
        """外壳透明度输入框：解析 → 钳制 → 回写滑块（滑块信号已屏蔽，避免回环）。"""
        try:
            a = float(self._vdw_alpha_edit.text())
        except ValueError:
            a = self._vdw_alpha_sld.value() / 100.0
        a = max(0.02, min(0.80, a))
        self._vdw_alpha_sld.blockSignals(True)
        self._vdw_alpha_sld.setValue(int(round(a * 100)))
        self._vdw_alpha_sld.blockSignals(False)
        self._vdw_alpha_edit.setText(f"{a:.2f}")
        if self.glw is not None and self._vdw_shell_chk.isChecked():
            self.glw.set_vdw_shell(True, a)

    def _on_vdw_outline(self, state):
        if self.glw is not None:
            self.glw.set_vdw_outline(
                state == Qt.Checked,
                width=self._vdw_ow_sld.value() / 100.0)

    def _on_vdw_outline_width(self, val):
        w = val / 100.0
        self._vdw_ow_edit.blockSignals(True)
        self._vdw_ow_edit.setText(f"{w:.2f}")
        self._vdw_ow_edit.blockSignals(False)
        if self.glw is not None:
            self.glw.set_vdw_outline(self._vdw_outline_chk.isChecked(), width=w)

    def _on_vdw_outline_width_edit(self):
        """外壳描边粗细输入框：解析 → 钳制 → 回写滑块（屏蔽信号避免回环）。"""
        try:
            w = float(self._vdw_ow_edit.text())
        except ValueError:
            w = self._vdw_ow_sld.value() / 100.0
        w = max(0.01, min(0.60, w))
        self._vdw_ow_sld.blockSignals(True)
        self._vdw_ow_sld.setValue(int(round(w * 100)))
        self._vdw_ow_sld.blockSignals(False)
        self._vdw_ow_edit.setText(f"{w:.2f}")
        if self.glw is not None:
            self.glw.set_vdw_outline(self._vdw_outline_chk.isChecked(), width=w)

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

    # ── 成键模式（两类）──
    def _on_bond_mode(self, _idx=None):
        """一律单键 / 按键长自动判定键型。"""
        if self.glw is None:
            return
        mode = self._bond_mode_cb.currentData() or "single"
        try:
            self.glw.set_bond_mode(mode)
        except Exception:
            return
        if mode == "auto":
            self._set_status("成键模式：按键长自动判定键型"
                             "（只对 C/N/O 之间的键生效，右键可逐键修正）")
        else:
            self._set_status("成键模式：一律单键")

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
        if hasattr(self, "_fade_sld"):
            self._fade_sld.setEnabled(bool(on))

    def _on_fade_strength(self, value):
        """景深雾化强度 0..1（场景最远处向白渐变的幅度）。"""
        if self.glw is not None:
            self.glw.set_fog_strength(value / 100.0)

    # ── 后处理（超采样抗锯齿 / 边缘暗化）回调 ──
    def _on_post_toggle(self, on):
        self._post_scale_cb.setEnabled(bool(on))
        self._post_edge_sld.setEnabled(bool(on))
        if self.glw is not None:
            self.glw.set_postprocess(enabled=bool(on))

    def _on_linear_space(self, on):
        """色彩空间（B 方案）：sRGB 直通 ↔ 线性空间光照。"""
        if self.glw is not None:
            self.glw.set_linear_space(bool(on))

    def _on_post_scale(self, i):
        if self.glw is not None:
            self.glw.set_postprocess(scale=(1.0, 1.5, 2.0)[i])

    def _on_post_edge(self, v):
        e = v / 100.0
        self._post_edge_val.setText(f"{e:.2f}")
        if self.glw is not None:
            self.glw.set_postprocess(edge=e)

    def _on_post_radius(self, v):
        r = v / 10.0
        self._post_r_val.setText(f"{r:.1f}")
        if self.glw is not None:
            self.glw.set_postprocess(radius=r)

    def _on_ao(self, v):
        e = v / 100.0
        self._ao_val.setText(f"{e:.2f}")
        if self.glw is not None:
            self.glw.set_postprocess(ao=e)

    def _on_ao_radius(self, v):
        r = v / 10.0
        self._ao_r_val.setText(f"{r:.1f}")
        if self.glw is not None:
            self.glw.set_postprocess(ao_radius=r)

    def _on_tone(self, v):
        e = v / 100.0
        self._tone_val.setText(f"{e:.2f}")
        if self.glw is not None:
            self.glw.set_postprocess(tone=e)

    def _on_vig(self, v):
        e = v / 100.0
        self._vig_val.setText(f"{e:.2f}")
        if self.glw is not None:
            self.glw.set_postprocess(vig=e)

    def _sync_post_ui(self):
        """从画布取回后处理设置（切换样式 / 载入存档后调用）。"""
        if self.glw is None:
            return
        # 色彩空间（B 方案）
        self._linear_chk.blockSignals(True)
        self._linear_chk.setChecked(bool(self.glw.linear_space()))
        self._linear_chk.blockSignals(False)
        st = self.glw.get_postprocess()
        self._post_r_sld.blockSignals(True)
        self._post_r_sld.setValue(int(round(float(st.get("radius", 2.0)) * 10)))
        self._post_r_sld.blockSignals(False)
        self._post_r_val.setText(f"{float(st.get('radius', 2.0)):.1f}")
        for sld, val, key, dflt, n, k in (
                (self._ao_sld, self._ao_val, "ao", 0.0, 2, 100.0),
                (self._tone_sld, self._tone_val, "tone", 0.0, 2, 100.0),
                (self._vig_sld, self._vig_val, "vig", 0.0, 2, 100.0),
                (self._ao_r_sld, self._ao_r_val, "ao_radius", 8.0, 1, 10.0)):
            v = float(st.get(key, dflt))
            sld.blockSignals(True)
            sld.setValue(int(round(v * k)))
            sld.blockSignals(False)
            val.setText(f"{v:.{n}f}")
        self._post_chk.blockSignals(True)
        self._post_chk.setChecked(bool(st["enabled"]))
        self._post_chk.blockSignals(False)
        self._post_scale_cb.blockSignals(True)
        self._post_scale_cb.setCurrentIndex(
            {1.0: 0, 1.5: 1, 2.0: 2}.get(round(float(st["scale"]), 2), 1))
        self._post_scale_cb.blockSignals(False)
        self._post_edge_sld.blockSignals(True)
        self._post_edge_sld.setValue(int(round(float(st["edge"]) * 100)))
        self._post_edge_sld.blockSignals(False)
        self._post_edge_val.setText(f"{float(st['edge']):.2f}")
        en = bool(st["enabled"])
        self._post_scale_cb.setEnabled(en)
        self._post_edge_sld.setEnabled(en)

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

    # ── 启动预热：触发所有 shader 首次编译（消除首操作卡顿） ──
    def warmup_gl(self):
        """在启动画面期间渲染一帧极小场景，让 GPU 驱动完成所有着色器
        管线的首次编译（原子/键/等值面/深度剥离），避免用户首次
        载入/拖动/缩放时出现 1-3 秒卡顿。"""
        glw = self.glw
        if glw is None or not getattr(glw, "_gl_ok", False):
            return
        try:
            saved = (glw._molecule, glw._cube,
                     glw._pos_surf, glw._neg_surf,
                     getattr(glw, "_orbital_recs", None))
            # 极小场景：2 原子 + 1 键 + 1 个等值面三角
            glw._molecule = [(6, 0.0, 0.0, 0.0, 0.0),
                             (1, 0.0, 2.0, 0.0, 0.0)]
            glw._cube = None
            surf = IsoSurface()
            surf.vertices = np.array(
                [[0, 0, 0], [2, 0, 0], [1, 1, 0]], dtype=np.float32)
            surf.normals = np.array(
                [[0, 0, 1], [0, 0, 1], [0, 0, 1]], dtype=np.float32)
            surf.indices = np.array([0, 1, 2], dtype=np.uint32)
            surf.colors = None
            glw._pos_surf = surf
            glw._neg_surf = None
            glw._orbital_recs = None
            glw._gen_atoms()
            glw._needs_upload = True
            glw.update()
            # 等 warmup 帧渲染完再恢复（恢复后重绘为空场景）
            QTimer.singleShot(
                300, lambda: self._restore_after_warmup(saved))
        except Exception:
            pass

    def _restore_after_warmup(self, saved):
        glw = self.glw
        if glw is None:
            return
        try:
            # 显式销毁全部网格缓冲（等值面 ×2 + 原子 + 键），不依赖
            # _gen_atoms 的清空分支——深度剥离按 mesh.count 判断绘制，
            # 任何残留（含原子网格）都会显示在画布上
            for mi in (0, 1, 2):
                try:
                    glw._meshes[mi].destroy()
                except Exception:
                    pass
                glw._meshes[mi] = GlMesh()
            try:
                glw._bond_mesh.destroy()
            except Exception:
                pass
            glw._bond_mesh = GlMesh()
            glw._bond_surf = None
            glw._atom_surf = None    # 关键：_upload 用 _atom_surf 填 mesh2
            glw._molecule, glw._cube, glw._pos_surf, glw._neg_surf, \
                glw._orbital_recs = saved
            # 若恢复后确有分子（非启动场景），重建原子网格
            if (glw._molecule is not None
                    or (glw._cube is not None
                        and getattr(glw._cube, "atoms", None))):
                glw._gen_atoms()
            glw._needs_upload = True
            glw.update()
        except Exception:
            pass

    def _export_image(self, fmt=None):
        """导出高分辨率图片。

        fmt 为扩展名（png/jpg/tif/svg，来自「导出图片」左侧的格式下拉框）。
        实际格式的判定优先级：**路径里明确写出的已知扩展名** > **保存对话框
        选中的过滤器** > **下拉框里选的格式**。这样用户既可以直接按下拉框
        导出，也可以在对话框里临时改过滤器、或干脆手打 "图.tiff"。
        """
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

        # 菜单点的格式（默认上次用过的）→ 该格式在过滤器里排最前
        want = export_ext_for(fmt, getattr(self, "_export_fmt", "png"))
        p, sel = save_file(self, "导出高分辨率图片",
                           f"{base}.{want}",
                           export_dialog_filter(preferred=want))
        if not p:
            return

        # 判定最终格式：路径扩展名 > 对话框选中的过滤器 > 下拉框选的格式
        ext = export_ext_from_path(p, default="")
        if ext not in ("png", "jpg", "tif", "svg"):
            ext = export_ext_from_filter(sel, default=want)
        p = export_ensure_suffix(p, ext)
        self._export_fmt = ext
        # 若最终格式与下拉框当前项不一致（用户在保存对话框里改了过滤器、
        # 或手打了别的扩展名），把下拉框同步过来，下次点导出即沿用该格式。
        _cb = getattr(self, "_export_cb", None)
        if _cb is not None:
            _idx = _cb.findData(ext)
            if _idx >= 0 and _idx != _cb.currentIndex():
                _cb.blockSignals(True)
                _cb.setCurrentIndex(_idx)
                _cb.blockSignals(False)

        try:
            dpi = float(self._dpi_edit.text())
        except ValueError:
            dpi = 600.0
        dpi = max(50.0, min(dpi, 2400.0))

        # 透明背景：直接把勾选状态传给 export_image（内部清屏 alpha=0 并修正 alpha）
        transparent = self._transparent_chk.isChecked()
        alpha_ok = export_format_supports_alpha(ext)
        # JPG 没有 alpha 通道：勾了透明也按「画布底色」出图（否则半透明区会被
        # 压到黑底上发黑）。出图后给一句说明，免得用户以为透明失效了。
        note = ""
        if transparent and not alpha_ok:
            note = "（JPG 不支持透明背景，已合成到画布底色；需透明请选 PNG / TIFF / SVG）"

        ok = self.glw.export_image(p, dpi=dpi,
                                   transparent=transparent and alpha_ok)
        # 失败原因由 glw.export_image 自己写进状态栏（含编码器报错原文），
        # 这里只在成功且需要补充说明时追加一句。
        if ok and note:
            self._set_status(f"已导出 {os.path.basename(p)} — {note}")

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
