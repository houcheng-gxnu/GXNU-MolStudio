"""
cub_viewer.py — 独立 .cub 文件可视化工具
==========================================
直接运行: python cub_viewer.py
或拖放 .cub 文件到窗口。

基于 IboView 渲染管线: depth peeling 透明度 + 三向 Phong 光照

本文件部分 shader 代码、原子半径/颜色/共价半径表与默认渲染参数
逐字移植自 IboView (Copyright (c) 2015 Gerald Knizia, GPLv3)。
本项目作为 IboView 的衍生作品，依 GNU GPLv3 发布。
"""

import ctypes
import os
import sys
import numpy as np
import traceback

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QComboBox, QPushButton, QSlider,
    QGroupBox, QFileDialog, QMessageBox, QGridLayout, QCheckBox, QListView,
)
from PyQt5.QtCore import Qt, QPoint, QTimer
from PyQt5.QtGui import QDoubleValidator, QSurfaceFormat, QImage

# ── OpenGL imports ──
try:
    from OpenGL.GL import *
    from OpenGL.GLU import *
    _HAS_GL = True
except ImportError:
    _HAS_GL = False

from PyQt5.QtWidgets import QOpenGLWidget

# ── Cube file + marching cubes ──
from marching_cubes import (
    read_cube, marching_cubes, IsoSurface, CubeData, compute_bounding_sphere,
    relative_iso_threshold,
)

# ── Styles ──
from fchk_orbital import STYLES, ELEMENT_SYMBOLS

STYLE_NAMES = list(STYLES.keys())
STYLE_DISPLAY = [f"{k}  — {STYLES[k]['desc']}" for k in STYLES.keys()]

# ═══════════════════════════════════════════════════════════════
# IboView shader registers — transplanted verbatim from
#   D:\iboview-test\ibo-view.20211019-RevA\resources\preset_*.js
# and the IboView default (prop_FView3d.cpp.inl):
#   a* = atoms   (m_FShaderReg 0..3 for opaque objects)
#   o* = orbitals(m_FShaderReg 0..3 for orbital meshes)
# FadeWidth/FadeBias are the IboView defaults (FadeType=1).
# ═══════════════════════════════════════════════════════════════
IBO_DEFAULT_A = [0.8, 0.7, 0.4, -0.5]   # default opaque (atoms)
IBO_DEFAULT_O = [0.8, 0.7, 0.7, -0.5]   # default orbital

# IboView "shiny" presets — each sets the three-light Phong ShaderReg0..3 for
# the opaque (a*) and orbital (o*) render paths. Transcribed from the preset_*.js
# scripts shipped with IboView (resources/preset_*.js):
#   a_reg = [a0, a1, a2, a3]  (atoms/bonds)
#   o_reg = [o0, o1, o2, o3]  (isosurfaces)
# a0/a1 = diffuse exponent/strength, a2 = specular strength, a3 = specular balance.
SHININESS_PRESETS = {
    "not very shiny":      ([0.7, 0.7, 0.25, -0.5], [0.7, 0.7, 0.25, -0.5]),
    "reasonably shiny":    ([0.8, 0.7, 0.40, -0.5], [0.8, 0.7, 0.70, -0.5]),
    "extra shiny":        ([0.9, 0.7, 1.00, -0.5], [0.9, 0.7, 1.00, -0.5]),
    "sooooo shiny":       ([1.0, 0.7, 2.00, -0.5], [1.0, 0.7, 2.00, -0.5]),
    "cgk's shiny chic '21": ([0.7, 0.7, 0.90, -0.5], [0.7, 0.7, 0.90, -0.5]),
}
SHININESS_DEFAULT = "reasonably shiny"

# ── IboView atomic/molecular geometry data (transplanted verbatim from IboView) ──
# These tables are copied 1:1 from src/IboView/IvDataOptions.cpp so that the
# molecule (ball-and-stick) appearance matches IboView's own rendering.

# Atom draw radii — IboView's "AtomicRadii" table (length 104, index = element Z;
# entry 0 is a dummy for element 0). These are the radii IboView actually uses to
# draw atom spheres (src/IboView/IvDataOptions.cpp, GetAtomDrawRadius()).
_ATOM_DRAW_RADII = [
    0, 0.87, 1.60, 2.52, 2.03, 1.58, 1.43, 1.32, 1.29, 1.26,  # 0-9
    1.74, 2.91, 2.69, 2.35, 2.11, 2.08, 2.04, 1.97, 1.95, 3.69,  # 10-19
    3.33, 2.86, 2.67, 2.65, 2.54, 2.61, 2.52, 2.35, 2.20, 2.46,  # 20-29
    2.25, 2.38, 2.26, 2.29, 2.25, 2.25, 2.17, 4.27, 3.88, 3.21,  # 30-39
    2.96, 2.78, 2.80, 2.50, 2.79, 2.52, 2.53, 2.62, 2.65, 2.76,  # 40-49
    2.64, 2.66, 2.62, 2.61, 2.39, 4.86, 4.30, 3.67, 3.48, 3.44,  # 50-59
    3.43, 3.40, 3.36, 3.35, 3.28, 3.27, 3.23, 3.20, 3.16, 3.14,  # 60-69
    3.09, 3.16, 3.04, 2.86, 2.88, 2.59, 2.59, 2.59, 2.58, 2.38,  # 70-79
    2.53, 2.87, 2.76, 2.86, 2.83, 2.92, 2.68, 5.44, 4.75, 3.75,  # 80-89
    3.25, 3.23, 3.18, 3.15, 3.13, 3.14, 3.40, 3.33, 3.31, 3.26,  # 90-99
    3.24, 3.19, 3.17, 3.21,  # 100-103
]

# 金属原子序数集合（碱金属、碱土、过渡金属、贫金属/后过渡）。
# 金属原子绘制半径整体减小三分之一（×2/3），避免球棍模型里偏大。
_METAL_SET = frozenset([
    3, 4, 11, 12, 13, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 37, 38,
    39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 55, 56, 57, 58, 59, 60, 61,
    62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80,
    81, 82, 83, 84, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101,
    102, 103, 104, 105, 106, 107, 108, 109, 110, 113, 114, 115, 116, 117, 118,
])
_METAL_RADIUS_FACTOR = 2.0 / 3.0  # 减小三分之一


def _atom_base_radius(anum):
    """原子绘制基础半径（已含金属缩放）。越界元素回退到 0.4。"""
    if 0 <= anum < len(_ATOM_DRAW_RADII):
        base = _ATOM_DRAW_RADII[anum]
    else:
        base = 0.4
    if anum in _METAL_SET:
        base *= _METAL_RADIUS_FACTOR
    return base


# Element colours — IboView's "ElementColors" table (length 110, Rasmol CPK-new
# palette per the Jmol homepage). Carbon was replaced by 0x999999 (grey) and a
# dummy entry for element 0 was inserted (src/IboView/IvDataOptions.cpp,
# ElementColors[110]). Stored as 0xRRGGBB; converted to (r,g,b) in 0..1 below.
_IBO_ELEMENT_COLORS_HEX = [
    0x404040, 0xffffff, 0xffc0cb, 0xb22121, 0xff1493, 0x00ff00, 0x999999, 0x87cee6,
    0xff0000, 0xdaa520, 0xff1493, 0x0000ff, 0x228b22, 0x696969, 0xdaa520, 0xffaa00,
    0xffff00, 0x00ff00, 0xff1493, 0xff1493, 0x696969, 0xff1493, 0x696969, 0xff1493,
    0x696969, 0x696969, 0xffaa00, 0xff1493, 0x802828, 0x802828, 0x802828, 0xff1493,
    0xff1493, 0xff1493, 0xff1493, 0x802828, 0xff1493, 0xff1493, 0xff1493, 0xff1493,
    0xff1493, 0xff1493, 0xff1493, 0xff1493, 0xff1493, 0xff1493, 0x696969, 0xff1493,
    0xff1493, 0xff1493, 0xff1493, 0xff1493, 0xa020f0, 0xff1493, 0xff1493, 0xffaa00,
    0xff1493, 0xff1493, 0xff1493, 0xff1493, 0xff1493, 0xff1493, 0xff1493, 0xff1493,
    0xff1493, 0xff1493, 0xff1493, 0xff1493, 0xff1493, 0xff1493, 0xff1493, 0xff1493,
    0xff1493, 0xff1493, 0xff1493, 0xff1493, 0xff1493, 0xdaa520, 0xff1493, 0xff1493,
    0xff1493, 0xff1493, 0xff1493, 0xff1493, 0xff1493, 0xff1493, 0xff1493, 0xff1493,
    0xff1493, 0xff1493, 0xff1493, 0xff1493, 0xff1493, 0xff1493, 0xff1493, 0xff1493,
    0xff1493, 0xff1493, 0xff1493,
]
def _ibo_hex_to_rgb(c):
    return ((c >> 16) & 0xff) / 255.0, ((c >> 8) & 0xff) / 255.0, (c & 0xff) / 255.0
_IBO_ELEMENT_COLORS = [_ibo_hex_to_rgb(c) for c in _IBO_ELEMENT_COLORS_HEX]

# Covalent radii — IboView's g_CovalentRadii table (src/Common/CxAtomData.cpp),
# in **Bohr** (IboView's internal unit). .cub coordinates are in **Angstrom**, so
# we convert with BOHR_TO_ANGSTROM (0.529177) to use the same values in the
# GenerateBonds() geometric heuristic:
#   r_ij <= 0.5 * (bf_i + bf_j) * (cov_i + cov_j)  ⇒  bond
# where BondRadiusFactor (bf) defaults to 1.3 in IboView.
BOHR_TO_ANGSTROM = 0.529177
ANGSTROM_TO_BOHR = 1.0 / BOHR_TO_ANGSTROM
_COVALENT_RADII_BOHR = [
    0.0,    0.7181, 0.6047, 2.5322, 1.7008, 1.5496, 1.4551, 1.4173, 1.3795, 1.3417,
    1.3039, 2.9102, 2.4566, 2.2299, 2.0976, 2.0031, 1.9275, 1.8708, 1.8330, 3.7039,
    3.2881, 2.7212, 2.5700, 2.3622, 2.4000, 2.6267, 2.3622, 2.3811, 2.2866, 2.6078,
    2.4755, 2.3811, 2.3055, 2.2488, 2.1921, 2.1543, 2.0787, 3.9873, 3.6283, 3.0614,
    2.7968, 2.5889, 2.7401, 2.9480, 2.3811, 2.5511, 2.4755, 2.8913, 2.7968, 2.7212,
    2.6645, 2.6078, 2.5511, 2.5133, 2.4566, 4.2519, 3.7417, 3.1936, 3.4355, 3.4469,
    3.4280, 3.4658, 3.4091, 3.4091, 3.4091, 3.3505, 3.3656, 3.3297, 3.3278, 3.3240,
    3.3259, 3.0236, 2.8346, 2.6078, 2.7590, 3.0047, 2.7188, 2.5889, 2.7188, 2.7212,
    2.8157, 2.7968, 2.7779, 2.7590, 2.8300, 2.9200, 2.7401, 5.4400, 4.7500, 3.7500,
    3.3826, 3.0803, 2.9480, 2.9291, 3.0047, 3.2692, 3.2881, 3.2125, 3.5149, 3.5149,
    3.2400, 3.1900, 3.1700, 3.2100, 3.2000, 3.2000, 3.2000, 3.2000, 3.2000, 3.2000,
]
_COVALENT_RADII = [r * BOHR_TO_ANGSTROM for r in _COVALENT_RADII_BOHR[:110]]

# IboView drawing scales. IboView's AtomicRadii table uses the same internal
# units as its covalent radii; we normalize to Angstrom-like units with these
# factors so the ball-and-stick proportions match IboView's on-screen look.
ATOM_DRAW_SCALE = 0.225    # sphere radius = ATOM_DRAW_SCALE * _ATOM_DRAW_RADII[z]
BOND_DRAW_SCALE = 0.18     # bond radius   = BOND_DRAW_SCALE * fBondScaleOuter-equivalent
BOND_RADIUS_FACTOR = 1.3   # IboView default BondRadiusFactor (prop_FElementOptions.cpp.inl)
# Absolute upper bound for bond detection (in Angstrom). Distances up to this
# value are still treated as solid bonds even if they exceed the covalent
# radius heuristic, so longer contacts show a bond. Kept modest (1.8 Å) to
# avoid over-bonding distant contacts.
BOND_MAX_DIST_ANG = 1.8
# Tighter absolute cap for bonds involving hydrogen (H only bonds to its
# nearest heavy atom, C-H ≈ 1.09 Å), preventing distant H…X contacts.
BOND_MAX_DIST_H_ANG = 1.3
BOND_THINNING_DEFAULT = 0.72   # IboView default m_BondThinning (IvDataOptions.cpp): bond
                               # narrows to 72% of its radius at the midpoint (runtime-adjustable)

# IboView default view properties, from
#   D:\iboview-test\ibo-view.20211019-RevA\src\IboView\prop_FView3d.cpp.inl
IBOVIEW_DEFAULTS = {
    'IsoResolution': 12.0,
    'IsoThreshold': 80.0,       # *relative* threshold, in percent (see below)
    'FadeType': 1,
    'FadeWidth': 9.0,
    'FadeBias': 0.0,
    'DepthPeelingLayers': 4,
    'RenderBacksides': False,
    'SuperSample': True,
    'FakeAntiAliasing': True,
    'OrbitalOpacity': 0.8,      # IboView orbitals are semi-transparent
}

# Each entry mirrors one IboView preset_*.js, with the orbital (o*) registers.
IBO_SHINY = {
    "sooooo_shiny": [0.2, 0.5, 2.92, 2.9],   # preset_sooooo_shiny.js
    "shiny_chic_21": [0.0, 1.0, 2.5, 0.0],    # preset_shiny_chic_21.js
    "extra_shiny":   [0.5, 0.5, 2.0, 0.0],    # preset_extra_shiny.js
    "medium_shiny":  [0.6, 0.5, 1.0, 0.0],    # preset_medium_shiny.js
    "not_very_shiny":[0.8, 0.5, 0.5, 0.0],    # preset_not_very_shiny.js
}

# Extra selectable IboView styles merged into the style combo box.
# (desc, pos_color[rgb], neg_color[rgb], o-registers)
# Color palettes for the positive / negative lobe (RGB 0..1).  Each glowing
# style below reuses one of these palettes so the user gets several distinct
# color combinations to pick from instead of a single green/red look.
_POS_NEG_PALETTES = {
    "green-red":    ((0.20, 0.85, 0.20), (0.85, 0.25, 0.25)),   # IboView classic
    "blue-orange":  ((0.20, 0.55, 0.95), (0.95, 0.55, 0.15)),   # blue+ / orange-
    "purple-yellow":((0.60, 0.35, 0.90), (0.95, 0.85, 0.20)),   # purple+ / yellow-
    "cyan-magenta": ((0.15, 0.85, 0.85), (0.90, 0.25, 0.75)),   # cyan+ / magenta-
    "orange-blue":  ((0.95, 0.55, 0.15), (0.20, 0.55, 0.95)),   # orange+ / blue-
    "red-green":    ((0.90, 0.25, 0.30), (0.25, 0.80, 0.35)),   # red+ / green-
    "teal-rose":    ((0.20, 0.80, 0.70), (0.95, 0.45, 0.55)),   # teal+ / rose-
    "mono-cyan":    ((0.30, 0.85, 0.95), (0.10, 0.45, 0.55)),   # two-tone cyan
}

IBO_STYLES = {
    # IboView's own out-of-the-box look (prop_FView3d.cpp.inl defaults).
    "IboView default":       ("IboView 默认外观 (o* = 0.8/0.7/0.7/-0.5)",
                              *_POS_NEG_PALETTES["green-red"], IBO_DEFAULT_O),
    "IboView sooooo shiny":  ("柔和 (绿/红)",
                              *_POS_NEG_PALETTES["green-red"], IBO_SHINY["not_very_shiny"]),
    "IboView shiny chic":    ("柔和 (绿/红)",
                              *_POS_NEG_PALETTES["green-red"], IBO_SHINY["not_very_shiny"]),
    "IboView extra shiny":   ("柔和 (绿/红)",
                              *_POS_NEG_PALETTES["green-red"], IBO_SHINY["not_very_shiny"]),
    "IboView medium shiny":  ("柔和 (绿/红)",
                              *_POS_NEG_PALETTES["green-red"], IBO_SHINY["not_very_shiny"]),
    "IboView not very shiny":("柔和 (绿/红)",
                              *_POS_NEG_PALETTES["green-red"], IBO_SHINY["not_very_shiny"]),
    # Additional color combinations (soft, not very shiny).
    "Blue/Orange shiny":     ("柔和 (蓝/橙)",
                              *_POS_NEG_PALETTES["blue-orange"], IBO_SHINY["not_very_shiny"]),
    "Purple/Yellow shiny":   ("柔和 (紫/黄)",
                              *_POS_NEG_PALETTES["purple-yellow"], IBO_SHINY["not_very_shiny"]),
    "Cyan/Magenta shiny":    ("柔和 (青/品红)",
                              *_POS_NEG_PALETTES["cyan-magenta"], IBO_SHINY["not_very_shiny"]),
    "Orange/Blue shiny":     ("柔和 (橙/蓝)",
                              *_POS_NEG_PALETTES["orange-blue"], IBO_SHINY["not_very_shiny"]),
    "Red/Green shiny":       ("柔和 (红/绿)",
                              *_POS_NEG_PALETTES["red-green"], IBO_SHINY["not_very_shiny"]),
    "Teal/Rose shiny":       ("柔和 (青绿/玫红)",
                              *_POS_NEG_PALETTES["teal-rose"], IBO_SHINY["not_very_shiny"]),
    "Mono Cyan shiny":       ("柔和 (单色青)",
                              *_POS_NEG_PALETTES["mono-cyan"], IBO_SHINY["not_very_shiny"]),
}
# Put the glowing styles first so they are easy to pick; default = sooooo shiny.
MERGED_STYLES = {}
for _k, _v in IBO_STYLES.items():
    MERGED_STYLES[_k] = _v
for _k in STYLE_NAMES:
    MERGED_STYLES[_k] = STYLES[_k]
STYLE_NAMES = list(MERGED_STYLES.keys())
STYLE_DISPLAY = []
for _k in STYLE_NAMES:
    _v = MERGED_STYLES[_k]
    if isinstance(_v, tuple):   # IboView style
        STYLE_DISPLAY.append(f"{_k}  — {_v[0]}")
    else:
        STYLE_DISPLAY.append(f"{_k}  — {_v['desc']}")

# ── Molecule (ball-and-stick) style ──
# Two independent style systems: the isosurface style (above) controls the
# orbital lobes, while the molecule style controls the ball-and-stick model.
#   "CPK"        : per-element CPK colouring (default, matches VMD default)
#   "VMD single" : carbon uses the current isosurface style's VMD c_rgb (gold),
#                  all other elements keep their CPK colour
#   "Mono white" : every atom white, bonds black (minimalist schematic look)
#   "Jmol"       : Jmol's element palette (brighter, distinct hues)
#   "Gray pub"   : light-gray atoms, black bonds (grayscale publication style)
#   "Neon"       : saturated per-element neon palette for high contrast
#   "GaussView"  : Tian Lu's GaussView colour scheme (gview_color.tcl); bonds light grey
#   "HoukMol"    : same GaussView atoms, but bonds drawn pure black
MOL_STYLE_NAMES = ["CPK", "VMD single", "Mono white", "Jmol", "Gray pub", "Neon", "GaussView", "HoukMol"]
MOL_STYLE_DISPLAY = ["CPK (按元素)", "VMD (碳金色)", "单色白", "Jmol", "灰度出版", "霓虹", "GaussView", "HoukMol"]

# GaussView element colour palette, transcribed from gview_color.tcl
# (color change rgb 100+Z r g b; created by Tian Lu, sobereva@sina.com).
_GVIEW_COLORS = {
    1: (0.8000, 0.8000, 0.8000), 2: (0.8471, 1.0000, 1.0000), 3: (0.8000, 0.4863, 1.0000),
    4: (0.8000, 1.0000, 0.0000), 5: (1.0000, 0.7098, 0.7098), 6: (0.5569, 0.5569, 0.5569),
    7: (0.0980, 0.0980, 0.8980), 8: (0.8980, 0.0000, 0.0000), 9: (0.6980, 1.0000, 1.0000),
    10: (0.6863, 0.8863, 0.9569), 11: (0.6667, 0.3569, 0.9490), 12: (0.6980, 0.8000, 0.0000),
    13: (0.8196, 0.6471, 0.6471), 14: (0.4980, 0.6000, 0.6000), 15: (1.0000, 0.4980, 0.0000),
    16: (1.0000, 0.7765, 0.1569), 17: (0.0980, 0.9373, 0.0980), 18: (0.4980, 0.8196, 0.8863),
    19: (0.5569, 0.2471, 0.8275), 20: (0.6000, 0.6000, 0.0000), 21: (0.8980, 0.8980, 0.8863),
    22: (0.7490, 0.7569, 0.7765), 23: (0.6471, 0.6471, 0.6667), 24: (0.5373, 0.6000, 0.7765),
    25: (0.6078, 0.4784, 0.7765), 26: (0.4980, 0.4784, 0.7765), 27: (0.3569, 0.4275, 1.0000),
    28: (0.3569, 0.4784, 0.7569), 29: (1.0000, 0.4784, 0.3765), 30: (0.4863, 0.4980, 0.6863),
    31: (0.7569, 0.5569, 0.5569), 32: (0.4000, 0.5569, 0.5569), 33: (0.7373, 0.4980, 0.8863),
    34: (1.0000, 0.6275, 0.0000), 35: (0.6471, 0.1294, 0.1294), 36: (0.3569, 0.7294, 0.8196),
    37: (0.4392, 0.1765, 0.6863), 38: (0.4980, 0.4000, 0.0000), 39: (0.5765, 0.9882, 1.0000),
    40: (0.5765, 0.8784, 0.8784), 41: (0.4471, 0.7569, 0.7882), 42: (0.3294, 0.7098, 0.7098),
    43: (0.2275, 0.6196, 0.6588), 44: (0.1373, 0.5569, 0.5882), 45: (0.0392, 0.4863, 0.5490),
    46: (0.0000, 0.4078, 0.5176), 47: (0.6000, 0.7765, 1.0000), 48: (1.0000, 0.8471, 0.5569),
    49: (0.6471, 0.4588, 0.4471), 50: (0.4000, 0.4980, 0.4980), 51: (0.6196, 0.3882, 0.7098),
    52: (0.8275, 0.4784, 0.0000), 53: (0.5765, 0.0000, 0.5765), 54: (0.2588, 0.6196, 0.6863),
    55: (0.3373, 0.0863, 0.5569), 56: (0.4000, 0.2000, 0.0000), 57: (0.4392, 0.8667, 1.0000),
    58: (1.0000, 1.0000, 0.7765), 59: (0.8471, 1.0000, 0.7765), 60: (0.7765, 1.0000, 0.7765),
    61: (0.6392, 1.0000, 0.7765), 62: (0.5569, 1.0000, 0.7765), 63: (0.3765, 1.0000, 0.7765),
    64: (0.2667, 1.0000, 0.7765), 65: (0.1882, 1.0000, 0.7765), 66: (0.1176, 1.0000, 0.7098),
    67: (0.0000, 1.0000, 0.7098), 68: (0.0000, 0.8980, 0.4588), 69: (0.0000, 0.8275, 0.3176),
    70: (0.0000, 0.7490, 0.2196), 71: (0.0000, 0.6667, 0.1373), 72: (0.2980, 0.7569, 1.0000),
    73: (0.2980, 0.6471, 1.0000), 74: (0.1490, 0.5765, 0.8392), 75: (0.1490, 0.4863, 0.6667),
    76: (0.1490, 0.4000, 0.5882), 77: (0.0863, 0.3294, 0.5294), 78: (0.0863, 0.3569, 0.5569),
    79: (1.0000, 0.8196, 0.1373), 80: (0.7098, 0.7098, 0.7569), 81: (0.6471, 0.3294, 0.2980),
    82: (0.3373, 0.3490, 0.3765), 83: (0.6196, 0.3098, 0.7098), 84: (0.6667, 0.3569, 0.0000),
    85: (0.4588, 0.3098, 0.2667), 86: (0.2588, 0.5098, 0.5882), 87: (0.2588, 0.0000, 0.4000),
    88: (0.2980, 0.0980, 0.0000), 89: (0.4392, 0.6667, 0.9765), 90: (0.0000, 0.7294, 1.0000),
    91: (0.0000, 0.6275, 1.0000), 92: (0.0000, 0.5569, 1.0000), 93: (0.0000, 0.4980, 0.9490),
    94: (0.0000, 0.4196, 0.9490), 95: (0.3294, 0.3569, 0.9490), 96: (0.4667, 0.3569, 0.8863),
    97: (0.5373, 0.3686, 0.8863), 98: (0.6275, 0.2078, 0.8275), 99: (0.6588, 0.1686, 0.7765),
    100: (0.6980, 0.1176, 0.7294), 101: (0.6980, 0.0471, 0.6471), 102: (0.7373, 0.0471, 0.5294),
    103: (0.7765, 0.0000, 0.4000), 104: (1.0000, 0.4980, 0.4980), 105: (0.8980, 0.4000, 0.4000),
    106: (0.8000, 0.2980, 0.2980), 107: (0.6980, 0.2000, 0.2000), 108: (0.6000, 0.0980, 0.0980),
    109: (0.5490, 0.0000, 0.0000), 110: (0.4980, 0.0000, 0.0000), 111: (0.4471, 0.0000, 0.0000),
}

# Jmol element colour palette (0xRRGGBB) for common atomic numbers.
_JMOL_COLORS_HEX = {
    1: 0xffffff, 2: 0xd9ffff, 3: 0xcc80ff, 4: 0xc2ff00, 5: 0xffb5b5, 6: 0x909090,
    7: 0x3050f8, 8: 0xff0d0d, 9: 0x90e050, 10: 0xb3e3f5, 11: 0xab5cf2, 12: 0x8aff00,
    13: 0xbfa6a6, 14: 0xf0c8a0, 15: 0xff8000, 16: 0xffff30, 17: 0x1ff01f, 18: 0x80d1e3,
    19: 0x8f40d4, 20: 0x3dff00, 26: 0xe06633, 30: 0x7d80b0, 35: 0xa62929, 53: 0x940094,
}
_JMOL_COLORS = {z: _ibo_hex_to_rgb(c) for z, c in _JMOL_COLORS_HEX.items()}

# Neon palette: vivid, high-saturation per-element tints (visualisation only).
_NEON_COLORS = {
    1: (0.85, 0.95, 1.00), 6: (0.15, 1.00, 0.95), 7: (0.30, 0.50, 1.00),
    8: (1.00, 0.25, 0.55), 9: (0.45, 1.00, 0.35), 15: (1.00, 0.65, 0.10),
    16: (1.00, 0.95, 0.20), 17: (0.35, 1.00, 0.45),
}


# ═══════════════════════════════════════════════════════════════
# GLSL Shaders (inline)
# ═══════════════════════════════════════════════════════════════

VERT = """
#version 330 core
layout(location=0) in vec3 in_Pos;
layout(location=1) in vec3 in_Normal;
layout(location=2) in vec4 in_Color;
out vec3 v_Normal;
out vec4 v_Color;
uniform mat4 u_ModelView;
uniform mat3 u_NormalMatrix;
uniform mat4 u_Projection;
void main() {
    gl_Position = u_Projection * (u_ModelView * vec4(in_Pos, 1.0));
    v_Normal = u_NormalMatrix * in_Normal;
    v_Color = in_Color;
}
"""

# ── IboView pixel_common.glsl, transplanted verbatim ────────────
# The three light directions, the diffuse/specular register semantics and
# the `color[3] /= clamp(abs(vNorm.z), .1, 1.)` edge-opacity boost are taken
# 1:1 from D:\iboview-test\ibo-view.20211019-RevA\shader\pixel_common.glsl.
# NOTE: IboView divides only the *alpha* channel by abs(N.z) (making
# silhouettes more opaque); it never divides RGB.
_GLSL_COMMON = """
in vec3 v_Normal;
in vec4 v_Color;
uniform float ShaderReg0, ShaderReg1, ShaderReg2, ShaderReg3;
uniform float FadeBias, FadeWidth;
uniform vec4 DiffuseColor;

const vec3 L0 = vec3(0.5, 0.5, 0.70710678);
const vec3 L1 = vec3(-0.4330127, -0.25, 0.8660254);
const vec3 L2 = vec3(0.4330127, -0.25, 0.8660254);

// IboView: cDiffuse  = ShaderReg1 * pow(cos, ShaderReg0) * DiffuseColor
//          cSpecular = ShaderReg2 * (ShaderReg3*pow(cos,16) + 1.2*pow(cos,64))
vec4 light_term(vec3 N, vec3 L, float I) {
    float d = clamp(dot(N, L), 0.0, 1.0);
    vec4 diff = ShaderReg1 * pow(d, ShaderReg0) * DiffuseColor;
    vec4 spec = ShaderReg2 * (ShaderReg3 * pow(d, 16.0) + 1.2 * pow(d, 64.0))
                * vec4(1.0, 1.0, 1.0, 0.0);
    return I * (v_Color * diff + spec);
}

// IboView calc_base_color(FlipSides): if the fragment is back-facing and
// FlipSides is set (orbitals), the normal is inverted so the inside of the
// lobe is lit like a proper surface.
vec4 calc_base_color(bool FlipSides) {
    vec3 N = normalize(v_Normal);
    if (FlipSides && !gl_FrontFacing)
        N = -N;
    vec4 color = light_term(N, L0, 1.0)
               + light_term(N, L1, 0.6)
               + light_term(N, L2, 0.5);

    // IboView: only alpha is boosted at grazing angles.
    color[3] /= clamp(abs(N.z), 0.1, 1.0);

    // IboView FadeType=1: fade towards white with window depth.
    float rz = clamp(FadeWidth * (gl_FragCoord.z - 0.5) + FadeBias, 0.0, 1.0);
    color.rgb = mix(color.rgb, vec3(1.0), rz);
    return color;
}
"""

# Orbital fragment shader — direct (no depth peeling) variant.
FRAG_ORB = """
#version 330 core
""" + _GLSL_COMMON + """
layout(location=0) out vec4 out_Color;
void main() {
    out_Color = calc_base_color(true);
}
"""

# Orbital fragment shader — depth-peeling variant, mirrors pixel5_orb_dp.glsl:
# only keep fragments strictly in front of the previously peeled layer.
FRAG_ORB_DP = """
#version 330 core
""" + _GLSL_COMMON + """
layout(location=0) out vec4 out_Color;
uniform sampler2D Depth1;
void main() {
    ivec2 iCoord2d = ivec2(gl_FragCoord.xy);
    float fDepth0 = texelFetch(Depth1, iCoord2d, 0).r;
    if (gl_FragCoord.z < fDepth0) {
        out_Color = calc_base_color(true);
    } else {
        discard;
    }
}
"""

# Opaque (atom) fragment shader — FlipSides=false, alpha from vertex colour.
# An optional silhouette outline (rim term) can be enabled via u_Outline so
# atoms get a clean edge stroke without any post-processing pass.
FRAG_ATOM = """
#version 330 core
""" + _GLSL_COMMON + """
layout(location=0) out vec4 out_Color;
uniform float u_Outline;       // 0 = off, 1 = on
uniform vec3  u_OutlineColor;  // edge stroke colour
uniform float u_OutlineWidth;  // 0..1, thickness of the silhouette band
void main() {
    vec4 c = calc_base_color(false);
    if (u_Outline > 0.5) {
        // v_Normal is in view space; the camera looks along -Z, so facing
        // fragments have |N.z| ~ 1 and silhouette fragments have |N.z| ~ 0.
        float facing = abs(normalize(v_Normal).z);
        // Thin, hard edge: u_OutlineWidth is the angular band half-width near
        // the silhouette (smaller = thinner). The transition occupies only the
        // outer 30% of the band so the stroke stays crisp even at minimum width.
        float inner = 1.0 - u_OutlineWidth;
        float outer = 1.0 - u_OutlineWidth * 0.7;
        float rim = 1.0 - smoothstep(inner, outer, facing);
        c.rgb = mix(c.rgb, u_OutlineColor, rim);
    }
    c.a = v_Color.a;
    out_Color = c;
}
"""

# Fullscreen-quad pass used to composite one peeled layer, mirrors
# pixel5_combine_dp.glsl.
VERT_QUAD = """
#version 330 core
const vec2 kVerts[4] = vec2[4](
    vec2(-1.0,-1.0), vec2(1.0,-1.0), vec2(-1.0, 1.0), vec2(1.0, 1.0));
void main() { gl_Position = vec4(kVerts[gl_VertexID], 0.0, 1.0); }
"""

FRAG_COMBINE_DP = """
#version 330 core
uniform sampler2D LayerColor;
out vec4 color;
void main() {
    ivec2 iCoord2d = ivec2(gl_FragCoord.xy);
    vec4 vLayerColor = texelFetch(LayerColor, iCoord2d, 0);
    if (abs(vLayerColor.w) < 1e-2) {
        discard;
    } else {
        color = vLayerColor;
    }
}
"""

# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def compile_shader(src, typ):
    s = glCreateShader(typ)
    glShaderSource(s, src)
    glCompileShader(s)
    if not glGetShaderiv(s, GL_COMPILE_STATUS):
        raise RuntimeError(glGetShaderInfoLog(s).decode(errors='replace'))
    return s

def link_program(*shaders):
    p = glCreateProgram()
    for s in shaders:
        glAttachShader(p, s)
    glLinkProgram(p)
    ok = glGetProgramiv(p, GL_LINK_STATUS)
    for s in shaders:
        glDetachShader(p, s); glDeleteShader(s)
    if not ok:
        raise RuntimeError(glGetProgramInfoLog(p).decode(errors='replace'))
    return p

def make_sphere(radius=1.0, sub=2):
    t = (1.0 + 5**0.5) / 2.0
    verts = np.array([
        [-1,t,0],[1,t,0],[-1,-t,0],[1,-t,0],
        [0,-1,t],[0,1,t],[0,-1,-t],[0,1,-t],
        [t,0,-1],[t,0,1],[-t,0,-1],[-t,0,1]], dtype=np.float64)
    faces = np.array([
        [0,11,5],[0,5,1],[0,1,7],[0,7,10],[0,10,11],
        [1,5,9],[5,11,4],[11,10,2],[10,7,6],[7,1,8],
        [3,9,4],[3,4,2],[3,2,6],[3,6,8],[3,8,9],
        [4,9,5],[2,4,11],[6,2,10],[8,6,7],[9,8,1]], dtype=np.int32)
    for _ in range(sub):
        nf = []; em = {}
        for f in faces:
            mids = []
            for a,b in [(f[0],f[1]),(f[1],f[2]),(f[2],f[0])]:
                k = (min(a,b), max(a,b))
                if k not in em:
                    mid = verts[a] + verts[b]
                    mid /= np.linalg.norm(mid)
                    em[k] = len(verts)
                    verts = np.vstack([verts, mid])
                mids.append(em[k])
            nf.extend([[f[0],mids[0],mids[2]],[f[1],mids[1],mids[0]],
                       [f[2],mids[2],mids[1]],[mids[0],mids[1],mids[2]]])
        faces = np.array(nf, dtype=np.int32)
    verts = verts / np.linalg.norm(verts, axis=1, keepdims=True) * radius
    return (verts.astype(np.float32),
            (verts / radius).astype(np.float32),
            faces.astype(np.uint32).flatten())


def make_cylinder(radius=1.0, height=1.0, seg=16):
    """Unit cylinder along +Y axis, base at y=0, top at y=height.

    Normals point radially outward (Y component zero). Used to draw chemical
    bonds as in IboView's ball-and-stick model (IboView renders bonds as grey
    cylinders via the same opaque shader as atoms)."""
    return make_tapered_cylinder(radius, radius, height, seg)


def make_tapered_cylinder(r0=1.0, r1=1.0, height=1.0, seg=16):
    """Cylinder along +Y axis, base (y=0) radius r0, top (y=height) radius r1.

    The radius varies linearly along the axis so the two half-bonds meet at a
    smooth, continuous profile (no mid-bond step). Normals point radially
    outward and are tilted to follow the taper."""
    ang = [2.0 * np.pi * i / seg for i in range(seg)]
    # base ring (y=0, r0) and top ring (y=height, r1)
    ring0 = [(np.cos(a) * r0, 0.0, np.sin(a) * r0) for a in ang]
    ring1 = [(np.cos(a) * r1, float(height), np.sin(a) * r1) for a in ang]
    # radial normal direction at each angle (z component accounts for taper)
    if abs(r1 - r0) < 1e-6:
        nrm_dir = [(np.cos(a), 0.0, np.sin(a)) for a in ang]
    else:
        slant = (r0 - r1) / height  # dr/dy (negative if tapering inward)
        inv = 1.0 / np.sqrt(1.0 + slant * slant)
        nrm_dir = [(np.cos(a) * inv, slant * inv, np.sin(a) * inv) for a in ang]
    pos, nrm, idx = [], [], []
    for i in range(seg):
        pos.append(ring0[i]); nrm.append(nrm_dir[i])
        pos.append(ring1[i]); nrm.append(nrm_dir[i])
    for i in range(seg):
        b = (i + 1) % seg
        i0, i1 = 2 * i, 2 * i + 1
        j0, j1 = 2 * b, 2 * b + 1
        idx += [i0, j0, i1, i1, j0, j1]
    pos = np.array(pos, dtype=np.float32)
    nrm = np.array(nrm, dtype=np.float32)
    idx = np.array(idx, dtype=np.uint32)
    return pos, nrm, idx.flatten()


def make_dashed_bond_geometry(p, q, bond_r, n_segments=0, dash_weight=0.4,
                               dot_size=1.0, dot_spacing=1.0, seg=12):
    """Generate a dotted bond as a string of small black spheres along p→q.

    Replaces the old segmented-cylinder dashes with a row of small spheres
    (dotted style), which reads more clearly as a "dashed" (partial) bond.
    dot_size   : multiplier on each sphere's radius.
    dot_spacing: multiplier on the gap between spheres (>1 → sparser).
    Returns (verts, normals, indices) so the caller can glDrawElements it.
    """
    d = q - p
    length = float(np.linalg.norm(d))
    if length < 1e-4:
        return (np.zeros((0, 3), dtype=np.float32),
                np.zeros((0, 3), dtype=np.float32),
                np.zeros((0,), dtype=np.uint32))

    # Spacing scale changes how many dots are placed (larger → sparser).
    if n_segments <= 0:
        n_segments = max(3, int(np.floor(1.0 + length / (0.45 * max(0.3, dot_spacing)))))

    # Small-sphere radius: a fraction of the bond radius, with a mild
    # dependence on dash_weight (more "dotted" → slightly smaller spheres),
    # then scaled by the user's dot_size slider.
    dot_weight = 1.0 - (1.0 - dash_weight) ** 2
    dot_r = bond_r * (0.55 - 0.15 * dot_weight) * dot_size
    dot_r = max(dot_r, 0.02)

    sphere_v, sphere_n, sphere_i = make_sphere(radius=dot_r, sub=2)

    seg_v = d / length
    verts_list, norms_list, idx_list = [], [], []
    offset = 0
    # Place dots between the two endpoints, leaving a small margin at each end
    # so they don't overlap the atom spheres.
    margin = bond_r * 1.2
    usable = length - 2.0 * margin
    if usable <= 0:
        usable = length * 0.6
        margin = (length - usable) * 0.5
    for k in range(n_segments):
        if n_segments == 1:
            t = 0.5
        else:
            t = margin / length + (usable / length) * (k / (n_segments - 1))
        center = p + seg_v * (t * length)
        cv = sphere_v + center
        verts_list.append(cv)
        norms_list.append(sphere_n)
        idx_list.append(sphere_i + offset)
        offset += cv.shape[0]

    if not verts_list:
        return (np.zeros((0, 3), dtype=np.float32),
                np.zeros((0, 3), dtype=np.float32),
                np.zeros((0,), dtype=np.uint32))
    return (np.vstack(verts_list).astype(np.float32),
            np.vstack(norms_list).astype(np.float32),
            np.concatenate(idx_list).astype(np.uint32))
    verts_list = []
    norms_list = []
    idx_list = []

    for i in range(n_segments):
        t = (i / (n_segments - 0.5)) if n_segments > 1 else 0.0
        start_t = max(0.0, t - seg_len / length * 0.5)
        # make_cylinder 返回三元组 (pos, nrm, idx)，必须完整解包
        cv, cn, ci = make_cylinder(radius=1.0, height=1.0, seg=seg)
        S = np.diag([bond_r, seg_len, bond_r])
        T = R @ S
        seg_start = p + seg_v * (start_t * length)
        cv = cv @ T.T + seg_start
        cn = cn @ R.T
        base = len(verts_list) * 0  # 每段顶点数已由 ci 给出，下面用偏移累加
        verts_list.append(cv)
        norms_list.append(cn)
        idx_list.append(ci + i * cv.shape[0])

    if not verts_list:
        return np.zeros((0, 3)), np.zeros((0, 3)), np.zeros((0,), dtype=np.uint32)
    V = np.vstack(verts_list)
    N = np.vstack(norms_list)
    I = np.concatenate(idx_list).astype(np.uint32)
    return V, N, I


def style_params(surface_mat):
    """Translate a vcube-style surface_mat into IboView shader registers.
    IboView computes lighting as:
        cDiffuse = ShaderReg1 * pow(cos, ShaderReg0) * DiffuseColor
        cSpecular = ShaderReg2 * pow(cosS, ShaderReg3) * SpecularColor
    so we map diffuse->ShaderReg1, specular->ShaderReg2,
    shininess->ShaderReg0 (exponent) and ShaderReg3 (specular balance)."""
    amb, diff, spec, shin, mir, opac = surface_mat[:6]
    o = [IBO_DEFAULT_O[0], diff, max(spec, 0.0), shin]
    a = [IBO_DEFAULT_A[0], 0.65, 0.4, -0.5]
    return {
        'o_reg': o, 'a_reg': a,
        'FadeBias': IBOVIEW_DEFAULTS['FadeBias'],
        'FadeWidth': IBOVIEW_DEFAULTS['FadeWidth'],
        'opacity': opac,
    }

def iboview_params(o_regs):
    """Build params directly from IboView orbital (o*) registers."""
    return {
        'o_reg': list(o_regs),
        'a_reg': list(IBO_DEFAULT_A),
        'FadeBias': IBOVIEW_DEFAULTS['FadeBias'],
        'FadeWidth': IBOVIEW_DEFAULTS['FadeWidth'],
        'opacity': IBOVIEW_DEFAULTS['OrbitalOpacity'],
    }

# VMD ColorID -> RGB fallback (used when a style only carries a ColorID and
# no explicit RGB, e.g. sob-art's pos/neg = [12, None, None] / [22, None, None]).
_COLORID_RGB = {
    12: (0.600, 0.900, 0.500),  # ColorID 12 = green  (sob-art positive lobe, ~ao-chalky)
    22: (0.000, 0.700, 0.900),  # ColorID 22 = blue   (sob-art negative lobe, ~ao-chalky)
}

def style_rgb(color_entry):
    if len(color_entry) >= 4 and color_entry[1] is not None:
        return (color_entry[1], color_entry[2], color_entry[3])
    # ColorID-only entry (no explicit RGB): fall back to a known palette so
    # the canvas shows the right lobe colors instead of keeping the old ones.
    if color_entry and color_entry[0] in _COLORID_RGB:
        return _COLORID_RGB[color_entry[0]]
    return None


# ═══════════════════════════════════════════════════════════════
# Depth-peeling framebuffers
# ═══════════════════════════════════════════════════════════════

class PeelTarget:
    """One colour+depth render target used by the depth-peeling passes.

    IboView keeps two depth buffers and ping-pongs between them (see
    FView3d::RenderScene in IvView3D.cpp): each pass renders only fragments
    that lie strictly in front of the depth recorded by the previous pass.
    """

    def __init__(self):
        self.fbo = 0
        self.tex_color = 0
        self.tex_depth = 0
        self.w = self.h = 0

    def create(self, w, h):
        self.destroy()
        self.w, self.h = max(1, int(w)), max(1, int(h))

        self.tex_color = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, self.tex_color)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, self.w, self.h, 0,
                     GL_RGBA, GL_UNSIGNED_BYTE, None)
        for p, v in ((GL_TEXTURE_MIN_FILTER, GL_NEAREST),
                     (GL_TEXTURE_MAG_FILTER, GL_NEAREST),
                     (GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE),
                     (GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)):
            glTexParameteri(GL_TEXTURE_2D, p, v)

        self.tex_depth = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, self.tex_depth)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_DEPTH_COMPONENT32F, self.w, self.h, 0,
                     GL_DEPTH_COMPONENT, GL_FLOAT, None)
        for p, v in ((GL_TEXTURE_MIN_FILTER, GL_NEAREST),
                     (GL_TEXTURE_MAG_FILTER, GL_NEAREST),
                     (GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE),
                     (GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE),
                     (GL_TEXTURE_COMPARE_MODE, GL_NONE)):
            glTexParameteri(GL_TEXTURE_2D, p, v)
        glBindTexture(GL_TEXTURE_2D, 0)

        self.fbo = glGenFramebuffers(1)
        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                               GL_TEXTURE_2D, self.tex_color, 0)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
                               GL_TEXTURE_2D, self.tex_depth, 0)
        status = glCheckFramebufferStatus(GL_FRAMEBUFFER)
        glBindFramebuffer(GL_FRAMEBUFFER, 0)
        if status != GL_FRAMEBUFFER_COMPLETE:
            self.destroy()
            raise RuntimeError(f"FBO incomplete (status 0x{int(status):04X})")

    def destroy(self):
        if self.fbo:
            glDeleteFramebuffers(1, [self.fbo])
        if self.tex_color:
            glDeleteTextures([self.tex_color])
        if self.tex_depth:
            glDeleteTextures([self.tex_depth])
        self.fbo = self.tex_color = self.tex_depth = 0
        self.w = self.h = 0


# ═══════════════════════════════════════════════════════════════
# GlMesh
# ═══════════════════════════════════════════════════════════════

class GlMesh:
    # Number of triangles per chunk used by the sorted-blending fallback.
    CHUNK_TRIS = 512

    def __init__(self):
        self.vao = self.vbo_p = self.vbo_n = self.vbo_c = self.ebo = 0
        self.n_idx = self.n_vtx = 0
        self._chunks = []       # list of (first_index, index_count, centroid)

    @property
    def count(self):
        """Number of indices (0 when nothing is uploaded)."""
        return self.n_idx

    def chunks(self):
        """Yield (first_index, index_count, world_centroid) triples.

        Used to approximate back-to-front ordering without re-sorting every
        individual triangle each frame.
        """
        return self._chunks

    def _build_chunks(self, surf):
        """Group triangles into spatially coherent chunks with centroids."""
        self._chunks = []
        idx = np.asarray(surf.indices, dtype=np.uint32)
        n_tri = len(idx) // 3
        if n_tri == 0:
            return
        verts = np.asarray(surf.vertices, dtype=np.float32)
        tris = idx[:n_tri * 3].reshape(-1, 3)
        # Triangle centroids, then sort triangles by Morton-ish spatial key so
        # each chunk stays local and its centroid is meaningful.
        tri_ctr = verts[tris].mean(axis=1)
        step = self.CHUNK_TRIS
        if n_tri > step:
            lo = tri_ctr.min(axis=0)
            rng = np.maximum(tri_ctr.max(axis=0) - lo, 1e-6)
            g = np.clip(((tri_ctr - lo) / rng * 255).astype(np.int64), 0, 255)
            key = (g[:, 0] << 16) | (g[:, 1] << 8) | g[:, 2]
            order = np.argsort(key, kind='stable')
            tris = tris[order]
            tri_ctr = tri_ctr[order]
            surf.indices = np.ascontiguousarray(tris.ravel(), dtype=np.uint32)
        for t0 in range(0, n_tri, step):
            t1 = min(t0 + step, n_tri)
            self._chunks.append((t0 * 3, (t1 - t0) * 3,
                                 tri_ctr[t0:t1].mean(axis=0)))

    def upload(self, surf):
        self.destroy()
        if surf is None or surf.vertex_count == 0:
            return
        self._build_chunks(surf)
        self.n_vtx = surf.vertex_count
        self.n_idx = len(surf.indices)
        self.vao = glGenVertexArrays(1)
        glBindVertexArray(self.vao)
        self.vbo_p = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo_p)
        glBufferData(GL_ARRAY_BUFFER, surf.vertices.nbytes, surf.vertices, GL_STATIC_DRAW)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 0, None)
        glEnableVertexAttribArray(0)
        if surf.normals is not None:
            self.vbo_n = glGenBuffers(1)
            glBindBuffer(GL_ARRAY_BUFFER, self.vbo_n)
            glBufferData(GL_ARRAY_BUFFER, surf.normals.nbytes, surf.normals, GL_STATIC_DRAW)
            glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, 0, None)
            glEnableVertexAttribArray(1)
        if surf.colors is not None:
            self.vbo_c = glGenBuffers(1)
            glBindBuffer(GL_ARRAY_BUFFER, self.vbo_c)
            glBufferData(GL_ARRAY_BUFFER, surf.colors.nbytes, surf.colors, GL_STATIC_DRAW)
            glVertexAttribPointer(2, 4, GL_FLOAT, GL_FALSE, 0, None)
            glEnableVertexAttribArray(2)
        if self.n_idx > 0:
            self.ebo = glGenBuffers(1)
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.ebo)
            glBufferData(GL_ELEMENT_ARRAY_BUFFER, surf.indices.nbytes, surf.indices, GL_STATIC_DRAW)
        glBindVertexArray(0)

    def draw(self):
        if self.vao == 0 or self.n_idx == 0:
            return
        glBindVertexArray(self.vao)
        glDrawElements(GL_TRIANGLES, self.n_idx, GL_UNSIGNED_INT, None)
        glBindVertexArray(0)

    def draw_range(self, first_index, index_count):
        """Draw a sub-range of the index buffer (one chunk)."""
        if self.vao == 0 or index_count <= 0:
            return
        glBindVertexArray(self.vao)
        glDrawElements(GL_TRIANGLES, index_count, GL_UNSIGNED_INT,
                       ctypes.c_void_p(int(first_index) * 4))
        glBindVertexArray(0)

    def destroy(self):
        self._chunks = []
        ids = [x for x in (self.vao, self.vbo_p, self.vbo_n, self.vbo_c, self.ebo) if x]
        if ids:
            glDeleteVertexArrays(1, [self.vao]) if self.vao else None
            glDeleteBuffers(len(ids) - (1 if self.vao else 0), ids[1:] if self.vao else ids)
        self.vao = self.vbo_p = self.vbo_n = self.vbo_c = self.ebo = 0


# ═══════════════════════════════════════════════════════════════
# Arcball Camera
# ═══════════════════════════════════════════════════════════════

class Camera:
    """Arcball camera using an IboView-style orthographic projection.

    IboView (FView3d::ResetProjectionAndZoom) keeps the eye at a fixed
    distance `CAM_DIST` along -Z and controls the visible extent purely via
    the orthographic half-height (`8.0 / zoom_factor` in IboView units).
    We mirror that: `self.z` is the zoom factor, `half_height()` gives the
    ortho half-height and the view matrix only translates by -CAM_DIST.
    """

    CAM_DIST = 100.0        # IboView fCameraDist
    BASE_EXTENT = 8.0       # IboView base ortho half-height

    def __init__(self):
        self.q = np.array([0.,0.,0.,1.])  # rotation quat
        self.t = np.array([0.,0.,0.])
        self.z = 1.0
        self.ctr = np.array([0.,0.,0.])
        self._btn = None
        self._last = None
        self._dsph = None

    def start(self, x, y, w, h, btn):
        self._last = (x, y)
        v = np.array([(2*x-w)/w, (h-2*y)/h, 0.])
        d = np.linalg.norm(v)
        v[2] = np.sqrt(1-d*d) if d < 1 else 0
        self._dsph = v / (np.linalg.norm(v) or 1)
        self._btn = btn

    def move(self, x, y, w, h):
        if self._btn is None: return
        dx, dy = x - self._last[0], y - self._last[1]
        self._last = (x, y)
        if self._btn == Qt.MiddleButton or self._btn == Qt.RightButton:
            # Pan in world units: one pixel maps to (2*half_height / h).
            k = 2.0 * self.half_height() / max(h, 1)
            self.t[0] += dx * k
            self.t[1] -= dy * k
        else:
            v = np.array([(2*x-w)/w, (h-2*y)/h, 0.])
            d = np.linalg.norm(v)
            v[2] = np.sqrt(1-d*d) if d < 1 else 0
            v = v / (np.linalg.norm(v) or 1)
            cross = np.cross(self._dsph, v)
            dot = np.dot(self._dsph, v)
            dq = np.array([*cross, 1+dot])
            dq /= np.linalg.norm(dq)
            self.q = _qmul(dq, self.q)
            self._dsph = v

    def stop(self): self._btn = None; self._last = None

    def zoom(self, d):
        self.z *= 1 + d * 0.001
        self.z = max(0.01, min(self.z, 1000.0))

    def half_height(self):
        """Orthographic half-height, IboView: 8.0 / fZoomFactor."""
        return self.BASE_EXTENT / max(self.z, 1e-6)

    def view(self):
        """View matrix: centre -> pan -> rotate -> push back by CAM_DIST."""
        m = np.eye(4, dtype=np.float32)
        m[:3, :3] = _q2m(self.q)
        m[0, 3], m[1, 3] = self.t[0], self.t[1]
        # Under an orthographic projection the eye distance does not change
        # the apparent size; it only positions the scene inside the near/far
        # slab, exactly like IboView's fixed fCameraDist.
        m[2, 3] = self.t[2] - self.CAM_DIST
        tm = np.eye(4, dtype=np.float32)
        tm[0, 3], tm[1, 3], tm[2, 3] = -self.ctr
        return m @ tm

    def normal(self):
        v = self.view()
        return np.linalg.inv(v[:3,:3]).T.astype(np.float32)

    def reset(self):
        self.q = np.array([0.,0.,0.,1.])
        self.t = np.zeros(3); self.z = 1.0

    def set_center_zoom(self, ctr, r):
        """Frame a bounding sphere of radius r: half-height ~= 1.15*r."""
        self.ctr = np.asarray(ctr, dtype=np.float64)
        self.z = self.BASE_EXTENT / max(1.15 * r, 1e-3)


def _qmul(a, b):
    x1,y1,z1,w1 = a; x2,y2,z2,w2 = b
    return np.array([w1*x2+x1*w2+y1*z2-z1*y2,
                     w1*y2-x1*z2+y1*w2+z1*x2,
                     w1*z2+x1*y2-y1*x2+z1*w2,
                     w1*w2-x1*x2-y1*y2-z1*z2])

def _q2m(q):
    x,y,z,w = q; xx,yy,zz,xy,xz,yz,wx,wy,wz = x*x,y*y,z*z,x*y,x*z,y*z,w*x,w*y,w*z
    return np.array([
        [1-2*(yy+zz), 2*(xy-wz),   2*(xz+wy)],
        [2*(xy+wz),   1-2*(xx+zz), 2*(yz-wx)],
        [2*(xz-wy),   2*(yz+wx),   1-2*(xx+yy)]], dtype=np.float32)

def perspective(fov, asp, n, f):
    t = 1.0 / np.tan(np.radians(fov)/2)
    m = np.zeros((4,4), dtype=np.float32)
    m[0,0] = t/asp; m[1,1] = t
    m[2,2] = (f+n)/(n-f); m[2,3] = 2*f*n/(n-f)
    m[3,2] = -1
    return m


def ortho(left, right, bottom, top, near, far):
    """Standard glOrtho matrix (row-major, as used by _set_xforms with GL_TRUE).

    IboView's FView3d::ResetProjectionAndZoom builds exactly this kind of
    orthographic frustum; it never uses a perspective projection.
    """
    m = np.zeros((4, 4), dtype=np.float32)
    m[0, 0] = 2.0 / (right - left)
    m[1, 1] = 2.0 / (top - bottom)
    m[2, 2] = -2.0 / (far - near)
    m[0, 3] = -(right + left) / (right - left)
    m[1, 3] = -(top + bottom) / (top - bottom)
    m[2, 3] = -(far + near) / (far - near)
    m[3, 3] = 1.0
    return m


# ═══════════════════════════════════════════════════════════════
# GL Widget
# ═══════════════════════════════════════════════════════════════

class CubGLWidget(QOpenGLWidget):
    """OpenGL widget with deferred initialization."""

    DEPTH_PEEL_LAYERS = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        fmt = QSurfaceFormat()
        fmt.setSamples(0)
        fmt.setDepthBufferSize(24)
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.CoreProfile)
        self.setFormat(fmt)
        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)

        self.cam = Camera()
        self._meshes = [GlMesh(), GlMesh(), GlMesh()]  # pos, neg, atoms
        self._bg = (1.0, 1.0, 1.0, 1.0)

        # Style
        self._sp = style_params([0.1, 0.6, 1.0, 1.0, 0.0, 0.75, 0.0, 0.0, 1.0])
        self._pc = (0.1, 0.8, 0.1)
        self._nc = (0.9, 0.25, 0.25)

        # Init state
        self._gl_ok = False
        self._prog_orb = self._prog_atom = 0

        # Depth peeling (IboView prop_FView3d.cpp.inl: DepthPeelingLayers = 4)
        self._dp_layers = int(IBOVIEW_DEFAULTS['DepthPeelingLayers'])
        self._dp_ok = False
        self._prog_orb_dp = self._prog_combine = 0
        self._vao_quad = 0
        self._peel = []

        # Data state — deferred loading pattern
        self._cube = None
        # 独立分子数据（载入 fchk/xyz 时设置，单位 Bohr），不依赖 cube 文件
        self._molecule = None
        self._pos_surf = None
        self._neg_surf = None
        self._atom_surf = None
        self._isovalue = 0.05
        self._needs_upload = False
        self._status_cb = None
        # Ball-and-stick display scales (user-adjustable via sliders)
        self._atom_scale = 2.0   # multiplies atom sphere radius (default 2.0×)
        self._bond_scale = 1.8   # multiplies bond cylinder radius (default 1.8×)
        self._bond_thinning = BOND_THINNING_DEFAULT  # midpoint narrowing factor (1.0 = no waist)
        # Bond radius factor — dual-threshold for solid / dashed / no-bond
        self._bond_rf_tight = 1.0   # ≤ this → solid bond
        self._bond_rf_loose = 1.3   # ≤ this → dashed bond; > this → no bond
        self._dash_weight = 0.4     # fill ratio for dashed bonds (0..1)
        self._dot_size_scale = 1.0      # 虚线小圆球大小倍率
        self._dot_spacing_scale = 1.0   # 虚线小圆球间距倍率 (>1 更稀疏)
        # Molecule style: "CPK" (per-element) or "VMD single" (uniform tint)
        self._mol_style = "CPK"
        # Atom silhouette outline (rim stroke)
        self._atom_outline = False
        self._atom_outline_color = (0.0, 0.0, 0.0)   # black edge
        self._atom_outline_width = 0.35              # silhouette band thickness
        self._mol_single_rgb = (0.7, 0.56, 0.36)  # VMD "tan" carbon (most styles)
        self._style_name = None                  # last isosurface style name
        # IboView "shiny" preset (overrides a_reg/o_reg after style build)
        self._shininess = SHININESS_DEFAULT

        # Interactive atom/bond picking & override system (IboView context-menu)
        self._bond_overrides = {}   # {(i,j): 'solid'|'dashed'|'none'}
        self._selected_atoms = []   # indices of currently selected atoms
        self._drag_start = None     # (x, y) of mouse press for click-vs-drag
        self._was_drag = False      # True if mouse moved enough to be a drag

    def set_status_callback(self, cb):
        self._status_cb = cb

    def _status(self, msg):
        if self._status_cb:
            self._status_cb(msg)

    # ── Public API ──

    def load(self, cube_path, isovalue=0.05):
        """Load cube file (data only, upload deferred to paintGL)."""
        if not _HAS_GL or not os.path.exists(cube_path):
            return False
        try:
            self._status(f"读取 {os.path.basename(cube_path)}...")
            cube = read_cube(cube_path)
            self._cube = cube
            self._isovalue = isovalue

            self._status("提取等值面...")
            self._pos_surf = marching_cubes(cube, isovalue, False)
            self._neg_surf = marching_cubes(cube, -isovalue, True)

            # Colors
            pc = np.array([*self._pc, 1.0], dtype=np.float32)
            nc = np.array([*self._nc, 1.0], dtype=np.float32)
            self._pos_surf.colors = np.tile(pc, (self._pos_surf.vertex_count, 1))
            self._neg_surf.colors = np.tile(nc, (self._neg_surf.vertex_count, 1))

            # Camera
            ctr, r = compute_bounding_sphere(cube)
            self._scene_r = r
            self.cam.set_center_zoom(ctr, r)

            # Atom mesh (CPU-side generation)
            self._gen_atoms()

            self._needs_upload = True
            self._status(f"就绪: {self._pos_surf.vertex_count}+{self._neg_surf.vertex_count} 顶点")
            self.update()
            return True
        except Exception as e:
            self._status(f"加载失败: {e}")
            traceback.print_exc()
            return False

    def set_isovalue(self, v):
        if self._cube is None or abs(self._isovalue - v) < 1e-6:
            return
        self._isovalue = v
        try:
            self._pos_surf = marching_cubes(self._cube, v, False)
            self._neg_surf = marching_cubes(self._cube, -v, True)
            pc = np.array([*self._pc, 1.0], dtype=np.float32)
            nc = np.array([*self._nc, 1.0], dtype=np.float32)
            self._pos_surf.colors = np.tile(pc, (self._pos_surf.vertex_count, 1))
            self._neg_surf.colors = np.tile(nc, (self._neg_surf.vertex_count, 1))
            self._needs_upload = True
            self.update()
        except Exception as e:
            self._status(f"等值面更新失败: {e}")

    def set_style(self, name):
        s = MERGED_STYLES.get(name)
        if not s:
            return
        self._style_name = name
        if isinstance(s, tuple):
            # IboView style: (desc, pos_rgb, neg_rgb, o_registers)
            _desc, pc, nc, oreg = s
            self._sp = iboview_params(oreg)
        else:
            sm = s.get('surface_mat')
            if sm:
                self._sp = style_params(sm)
            pc = style_rgb(s.get('pos_color', []))
            nc = style_rgb(s.get('neg_color', []))
        if pc:
            self._pc = pc
        if nc:
            self._nc = nc
        if self._pos_surf and pc:
            c = np.array([*pc, 1.0], dtype=np.float32)
            self._pos_surf.colors = np.tile(c, (self._pos_surf.vertex_count, 1))
        if self._neg_surf and nc:
            c = np.array([*nc, 1.0], dtype=np.float32)
            self._neg_surf.colors = np.tile(c, (self._neg_surf.vertex_count, 1))
        self._apply_shininess()
        self._needs_upload = True
        self.update()

    def set_phase_colors(self, pos_rgb=None, neg_rgb=None):
        """逐相位（正/负）覆盖等值面配色，供色轮使用。

        颜色以 0-255 元组传入（None 表示保持当前色）。仅更新 CPU 端
        颜色并标记 _needs_upload，由 paintGL 在有效 GL 上下文内重新上传，
        避免在信号回调中直接 makeCurrent 触发原生崩溃。这正是 IboView
        延迟上传（deferred upload）模式。
        """
        if pos_rgb is not None:
            self._pc = tuple(float(c) / 255.0 for c in pos_rgb)
        if neg_rgb is not None:
            self._nc = tuple(float(c) / 255.0 for c in neg_rgb)
        if self._pos_surf is not None and pos_rgb is not None:
            c = np.array([*self._pc, 1.0], dtype=np.float32)
            self._pos_surf.colors = np.tile(c, (self._pos_surf.vertex_count, 1))
        if self._neg_surf is not None and neg_rgb is not None:
            c = np.array([*self._nc, 1.0], dtype=np.float32)
            self._neg_surf.colors = np.tile(c, (self._neg_surf.vertex_count, 1))
        self._needs_upload = True
        self.update()

    def flip_phase(self):
        """翻转相位：交换正/负相位颜色（等价 IboView chkBox_FlipPhase 的
        std::swap(cIsoMinus, cIsoPlus)）。直接作用于当前配色（样式或色轮均可），
        几何不变。延迟上传，安全可在信号回调调用。"""
        self._pc, self._nc = self._nc, self._pc
        if self._pos_surf is not None:
            c = np.array([*self._pc, 1.0], dtype=np.float32)
            self._pos_surf.colors = np.tile(c, (self._pos_surf.vertex_count, 1))
        if self._neg_surf is not None:
            c = np.array([*self._nc, 1.0], dtype=np.float32)
            self._neg_surf.colors = np.tile(c, (self._neg_surf.vertex_count, 1))
        self._needs_upload = True
        self.update()

    def set_mol_style(self, name, single_rgb=None):
        """Set the ball-and-stick molecule style independently of the
        isosurface style.

        name: "CPK"        -> every element coloured by its CPK tint
              "VMD single" -> carbon uses the current isosurface style's
                             VMD c_rgb (gold for most styles); all other
                             elements keep their CPK colour.
        single_rgb: optional (r,g,b) override for the carbon tint; if None,
                    take c_rgb from the current isosurface style.
        """
        if name not in MOL_STYLE_NAMES:
            return
        self._mol_style = name
        if single_rgb is not None:
            self._mol_single_rgb = tuple(float(x) for x in single_rgb[:3])
        if name == "VMD single":
            # keep carbon tint in sync with the current isosurface style
            s = MERGED_STYLES.get(self._style_name)
            if isinstance(s, dict):
                rgb = s.get('c_rgb')
                if rgb:
                    try:
                        self._mol_single_rgb = tuple(float(x) for x in rgb.split())
                    except Exception:
                        pass
        if self._cube:
            self._gen_atoms()
            self._needs_upload = True
            self.update()

    def _apply_shininess(self):
        """Override a_reg (atoms) and o_reg (orbitals) from the active shiny
        preset, so the gloss survives style/molecule-style changes."""
        if self._style_name is None and not self._sp:
            return
        preset = SHININESS_PRESETS.get(self._shininess)
        if preset is None:
            return
        a_reg, o_reg = preset
        self._sp['a_reg'] = list(a_reg)
        self._sp['o_reg'] = list(o_reg)

    def set_shininess(self, name):
        """Apply an IboView "shiny" preset by name (see SHININESS_PRESETS)."""
        if name not in SHININESS_PRESETS:
            return
        self._shininess = name
        self._apply_shininess()
        self._needs_upload = True
        self.update()

    def set_opacity(self, v):
        self._sp['opacity'] = max(0, min(1, v))
        self.update()

    @property
    def cube(self):
        """The currently loaded CubeData (or None)."""
        return self._cube

    def set_background(self, color):
        """Set the canvas clear/background color as an (r,g,b) or (r,g,b,a) tuple."""
        c = tuple(float(x) for x in color)
        if len(c) == 3:
            c = c + (1.0,)
        self._bg = c[:4]
        self.update()

    def set_depth_peeling(self, on):
        """Enable/disable depth peeling; disabling uses the sorted fallback."""
        self._dp_layers = int(IBOVIEW_DEFAULTS['DepthPeelingLayers']) if on else 0
        self.update()

    def reset_view(self):
        self.cam.reset()
        if self._cube:
            ctr, r = compute_bounding_sphere(self._cube)
            self.cam.set_center_zoom(ctr, r)
        self.update()

    def screenshot(self, path, scale: float = 2.0):
        w = max(1, int(round(self.width() * scale)))
        h = max(1, int(round(self.height() * scale)))
        img = self.grabFramebuffer()
        img = img.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        img.save(path)
        self._status(f"截图已保存: {os.path.basename(path)}")

    def export_image(self, path, dpi: float = 600.0):
        """高分辨率导出（参照 IboView 的导出思路）。

        IboView 的 ExportPicture 不是把低分辨率位图拉伸缩放（那样会模糊），
        而是以目标分辨率真正重新渲染场景再把像素读回。这里用分块(tile)离屏
        渲染实现：

          * 目标像素 = 当前控件尺寸 x (dpi / 96)   （96 = 屏幕基准 DPI）
          * 把整图切成若干小瓦片，每片用一个小离屏 FBO 真高分重绘
            （避免一次性分配超大 FBO 撑爆显存导致 GPU context lost / 闪退）
          * 每块 glReadPixels 读回，拼成完整 RGBA 数组，再写 QImage
          * 通过 setDotsPerMeterX/Y 把 600 DPI 写入 PNG 元数据

        若 OpenGL 不可用则回退到 grabFramebuffer 缩放。
        """
        if not self._gl_ok:
            self.screenshot(path, scale=float(dpi) / 96.0)
            return True

        w0 = max(1, self.width())
        h0 = max(1, self.height())
        scale = float(dpi) / 96.0
        ew = max(1, int(round(w0 * scale)))
        eh = max(1, int(round(h0 * scale)))

        # Tile size: keep each offscreen FBO modest (<= one screen worth) so we
        # never allocate a single gigantic framebuffer at 600 DPI.
        tile = max(512, w0)
        tx = min(ew, tile)
        ty = min(eh, tile)
        nx = (ew + tx - 1) // tx
        ny = (eh + ty - 1) // ty

        full = np.zeros((eh, ew, 4), dtype=np.uint8)

        self.makeCurrent()
        try:
            fbo = PeelTarget()
            try:
                fbo.create(tx, ty)
            except Exception as e:
                self.doneCurrent()
                self._status(f"导出 FBO 创建失败，回退截图: {e}")
                self.screenshot(path, scale=scale)
                return True

            prev_fbo = glGetIntegerv(GL_FRAMEBUFFER_BINDING)
            try:
                for jy in range(ny):
                    for jx in range(nx):
                        ox = jx * tx                      # from bottom-left
                        oy = jy * ty
                        tw = min(tx, ew - ox)
                        th = min(ty, eh - oy)
                        if tw <= 0 or th <= 0:
                            continue
                        # depth peeling needs matching-size buffers; cheap since
                        # the tile is small
                        if self._dp_ok:
                            try:
                                self._ensure_peel_targets(tw, th)
                            except Exception:
                                self._dp_ok = False

                        glBindFramebuffer(GL_FRAMEBUFFER, fbo.fbo)
                        glViewport(0, 0, tw, th)
                        glClearColor(*self._bg)
                        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
                        glEnable(GL_DEPTH_TEST)
                        glDepthFunc(GL_LEQUAL)
                        self._render(tw, th, vp=(ox, oy, tw, th, ew, eh))
                        glFlush()

                        buf = glReadPixels(0, 0, tw, th, GL_RGBA, GL_UNSIGNED_BYTE)
                        tile_arr = np.frombuffer(buf, np.uint8).reshape(th, tw, 4)
                        tile_arr = np.flipud(tile_arr)      # GL origin bottom-left
                        r0 = eh - oy - th                   # QImage row 0 = top
                        full[r0:r0 + th, ox:ox + tw] = tile_arr
            finally:
                glBindFramebuffer(GL_FRAMEBUFFER, prev_fbo)
        finally:
            self.doneCurrent()

        img = QImage(full.data, ew, eh, ew * 4, QImage.Format_RGBA8888)
        img = img.copy()                                   # detach from numpy

        # write DPI metadata (1 inch = 0.0254 m)
        dpm = int(round(dpi / 0.0254))
        img.setDotsPerMeterX(dpm)
        img.setDotsPerMeterY(dpm)

        ok = img.save(path)
        if ok:
            self._status(
                f"已导出 {ew}x{eh} @ {dpi} DPI (分 {nx}x{ny} 块): "
                f"{os.path.basename(path)}")
        else:
            self._status(f"导出保存失败: {os.path.basename(path)}")
        return ok

    # ── Bond override API ──────────────────────────────────────────
    def reset_bond_overrides(self):
        """Clear all manual bond overrides — revert to automatic detection."""
        self._bond_overrides.clear()
        self._selected_atoms.clear()
        if self._molecule is not None or self._cube is not None:
            self._gen_atoms()
            self._needs_upload = True
            self.update()
        self._status("已重置所有键为自动检测")

    def set_bond_flag(self, i, j, state):
        """Set a manual bond override.  state ∈ {'solid','dashed','none'}."""
        key = (min(i, j), max(i, j))
        if state == 'reset':
            self._bond_overrides.pop(key, None)
        else:
            self._bond_overrides[key] = state

    # ── Atom / bond picking ────────────────────────────────────────
    def _view_proj_matrices(self):
        """Return view and projection matrices for the current frame."""
        w, h = max(1, self.width()), max(1, self.height())
        proj = self._projection(w, h)
        view = self.cam.view()
        return view, proj, w, h

    def _screen_to_world(self, x, y, w=None, h=None):
        """Unproject screen (x, y) to a ray origin + direction in world space.

        For the orthographic projection used by IboView / CubGLWidget, the
        ray direction is always along the camera's -Z (look) axis.
        """
        if w is None or h is None:
            w, h = max(1, self.width()), max(1, self.height())
        view, proj, _, _ = self._view_proj_matrices()

        # NDC
        ndc_x = 2.0 * x / w - 1.0
        ndc_y = 1.0 - 2.0 * y / h

        # In clip space (ortho): point at near plane = (ndc_x, ndc_y, -1, 1)
        # point at far plane  = (ndc_x, ndc_y, +1, 1)
        p_near = np.array([ndc_x, ndc_y, -1.0, 1.0], dtype=np.float64)
        p_far  = np.array([ndc_x, ndc_y,  1.0, 1.0], dtype=np.float64)

        # Inverse MVP
        inv_vp = np.linalg.inv(proj @ view)
        world_near = inv_vp @ p_near
        world_near /= world_near[3]
        world_far = inv_vp @ p_far
        world_far /= world_far[3]

        origin = world_near[:3]
        d = world_far[:3] - world_near[:3]
        if np.linalg.norm(d) < 1e-9:
            return origin, np.array([0.0, 0.0, 1.0])
        return origin, d / np.linalg.norm(d)

    def _pick_atom(self, x, y):
        """Ray-sphere intersection: find nearest atom at screen (x,y).
        Returns (atom_index, hit_distance) or (-1, inf)."""
        if self._cube is None or not self._cube.atoms:
            return -1, float('inf')
        ro, rd = self._screen_to_world(x, y)
        best_idx, best_dist = -1, float('inf')
        coords = np.array([[a[2], a[3], a[4]] for a in self._cube.atoms], dtype=np.float64)
        anums = [int(a[0]) for a in self._cube.atoms]
        for i, ctr in enumerate(coords):
            atom_r = self._atom_draw_radius(anums[i])
            oc = ctr - ro
            t_ca = np.dot(oc, rd)
            if t_ca < 0:
                continue
            d2 = np.dot(oc, oc) - t_ca * t_ca
            r2 = atom_r * atom_r
            if d2 < r2:
                t_hc = np.sqrt(r2 - d2)
                t = t_ca - t_hc
                if t < best_dist:
                    best_dist = t
                    best_idx = i
        return best_idx, best_dist

    def _pick_bond(self, x, y):
        """Ray-cylinder (approximate) intersection: find nearest bond at (x,y).
        Returns ((i, j), distance) or (( -1, -1), inf)."""
        if self._cube is None or not self._cube.atoms:
            return (-1, -1), float('inf')
        ro, rd = self._screen_to_world(x, y)
        coords = np.array([[a[2], a[3], a[4]] for a in self._cube.atoms], dtype=np.float64)
        anums = [int(a[0]) for a in self._cube.atoms]
        n = len(coords)
        best_key, best_dist = (-1, -1), float('inf')
        bond_r = max(BOND_DRAW_SCALE * 0.4 * self._bond_scale, 0.04 * self._bond_scale) * 3.0
        for i in range(n):
            for j in range(i + 1, n):
                p, q = coords[i], coords[j]
                pq = q - p; l2 = np.dot(pq, pq)
                if l2 < 1e-6:
                    continue
                # Ray-line segment distance
                ro_p = ro - p
                t_l = np.dot(ro_p, pq) / l2  # projection onto segment
                t_l = max(0.0, min(1.0, t_l))
                closest = p + t_l * pq
                # Ray-line closest point distance
                oc = closest - ro
                t_r = np.dot(oc, rd)
                closest_r = ro + max(0.0, t_r) * rd
                d = np.linalg.norm(closest - closest_r)
                if d < bond_r and t_r < best_dist:
                    best_dist = t_r
                    best_key = (i, j)
        return best_key, best_dist

    def _atom_draw_radius(self, anum=None):
        """Picking tolerance radius for an atom.

        Must match the radius actually drawn in _gen_atoms
        (ATOM_DRAW_SCALE * _ATOM_DRAW_RADII[z] * _atom_scale), otherwise the
        ray-sphere pick test can never hit the (much larger) visible spheres.
        Enlarged by 1.15× so clicking near an atom still selects it.
        """
        if anum is None:
            return 0.5 * ATOM_DRAW_SCALE * self._atom_scale * 1.15
        return _atom_base_radius(anum) * ATOM_DRAW_SCALE * self._atom_scale * 1.15

    # ── Mouse event overrides: click → pick, drag → rotate/pan ────
    CLICK_THRESHOLD = 4   # pixels of movement before it counts as a drag

    def mousePressEvent(self, e):
        self.setFocus()
        self._drag_start = (e.x(), e.y())
        self._was_drag = False
        # Camera always gets a chance to start; if no drag happens, the
        # release handler converts it to a pick.
        if e.button() in (Qt.LeftButton, Qt.MiddleButton, Qt.RightButton):
            self.cam.start(e.x(), e.y(), self.width(), self.height(), e.button())

    def mouseMoveEvent(self, e):
        b = self.cam._btn
        if b is not None:
            dx = e.x() - self._drag_start[0] if self._drag_start else 0
            dy = e.y() - self._drag_start[1] if self._drag_start else 0
            if abs(dx) > self.CLICK_THRESHOLD or abs(dy) > self.CLICK_THRESHOLD:
                self._was_drag = True
            self.cam.move(e.x(), e.y(), self.width(), self.height())
            self.update()
            self._drag_start = (e.x(), e.y())

    def mouseReleaseEvent(self, e):
        btn = self.cam._btn
        self.cam.stop()
        if btn == Qt.LeftButton and not self._was_drag:
            # Left click (no drag) → pick atom.
            # 方案 (A)：左键选两个原子组成一对。点第一个高亮，点第二个凑成
            # 一对并保持；再点别的原子则替换第二个，始终只维持最近选中的两个。
            hit_idx, _ = self._pick_atom(e.x(), e.y())
            if hit_idx >= 0:
                mods = e.modifiers()
                if mods & Qt.ControlModifier:
                    # Ctrl+click: toggle the first-selected atom (keep pair logic)
                    if hit_idx in self._selected_atoms:
                        self._selected_atoms.remove(hit_idx)
                    else:
                        if len(self._selected_atoms) >= 2:
                            # 已有满一对时，清空后把该原子作为新的第一个
                            self._selected_atoms = [hit_idx]
                        else:
                            self._selected_atoms.insert(0, hit_idx)
                else:
                    # Plain click：维护“最近两个”的原子对。
                    if hit_idx in self._selected_atoms:
                        # 重复点击已选原子：若只有一个则取消选中
                        if len(self._selected_atoms) == 1:
                            self._selected_atoms.clear()
                        # 若已是一对中的成员，则不重复加入
                    else:
                        if len(self._selected_atoms) >= 2:
                            # 已有一对，把第二个替换为新点的原子（保留第一个）
                            self._selected_atoms = [self._selected_atoms[0], hit_idx]
                        else:
                            self._selected_atoms.append(hit_idx)
                self._regenerate_atoms()
                self.update()
                n_sel = len(self._selected_atoms)
                if n_sel == 2:
                    i, j = self._selected_atoms[0], self._selected_atoms[1]
                    self._status(f"已选中原子对 {i}-{j}，右键可选择 成键/断键/虚线")
                else:
                    self._status(f"选中原子 {hit_idx}"
                                 + (f" (共 {len(self._selected_atoms)} 个)" if len(self._selected_atoms) > 1 else ""))
        elif btn == Qt.RightButton and not self._was_drag:
            # Right click (no drag) → show context menu at mouse position
            self._show_context_menu(e.globalPos())

    # ── Context menu (called from mouseReleaseEvent, not contextMenuEvent) ──
    def _show_context_menu(self, pos):
        """Build and show right-click context menu.

        Uses a closure-dispatch pattern instead of lambdas to avoid
        late-binding issues with signal-slot connections."""
        from PyQt5.QtWidgets import QMenu, QAction
        menu = QMenu(self)

        n_sel = len(self._selected_atoms)

        # 右键菜单只针对“选中的原子对”提供三操作：断 / 成(实线) / 虚线 + 重置。
        if n_sel == 2:
            i, j = self._selected_atoms[0], self._selected_atoms[1]
            sel_key = (min(i, j), max(i, j))
            cur = self._bond_overrides.get(sel_key, 'auto')
            actions = [
                ("连接成键 (实线)", sel_key, 'solid'),
                ("设为虚线键",        sel_key, 'dashed'),
                ("断开键",            sel_key, 'none'),
            ]
            # 若当前已对这条键做过手动覆盖，提供恢复自动检测
            if cur != 'auto':
                actions.append(("---", None, None))
                actions.append(("重置为自动检测", sel_key, 'reset'))

            for label, key, state in actions:
                if label == "---":
                    menu.addSeparator()
                else:
                    act = QAction(label, self)
                    act.triggered.connect(self._make_bond_handler(key, state))
                    menu.addAction(act)
        else:
            # 未选中恰好两个原子：给出提示，引导用户先用左键选两个
            tip = QAction(f"请先用左键选中两个原子（当前已选 {n_sel} 个）", self)
            tip.setEnabled(False)
            menu.addAction(tip)

        # ── Clear selection ──
        if n_sel > 0:
            menu.addSeparator()
            a = QAction("清除选中", self)
            a.triggered.connect(self._clear_selection)
            menu.addAction(a)

        # ── Reset all overrides ──
        if self._bond_overrides:
            menu.addSeparator()
            a = QAction("重置所有键为自动检测", self)
            a.triggered.connect(self.reset_bond_overrides)
            menu.addAction(a)

        menu.popup(pos)   # non-blocking: handler → update → main event loop → paintGL

    def _make_bond_handler(self, key, state):
        """Return a callable that applies a bond override (closure with
        captured key/state values)."""
        def handler():
            try:
                if state == 'reset':
                    self._bond_overrides.pop(key, None)
                    self._status(f"键 ({key[0]}-{key[1]}) 已重置为自动检测")
                else:
                    self._bond_overrides[key] = state
                    names = {'solid': '实线连接', 'dashed': '虚线键', 'none': '断开'}
                    self._status(f"键 ({key[0]}-{key[1]}) → {names.get(state, state)}")
                self._regenerate_atoms()
                self.update()
            except Exception as ex:
                import traceback
                traceback.print_exc()
                self._status(f"操作失败: {ex}")
        return handler

    def _clear_selection(self):
        self._selected_atoms.clear()
        if self._molecule is not None or self._cube is not None:
            self._gen_atoms()
            self._needs_upload = True
            self.update()
        self._status("已清除原子选中")

    def _regenerate_atoms(self):
        """Regenerate atom mesh (respects bond overrides). Does NOT upload."""
        if self._molecule is not None or self._cube is not None:
            self._gen_atoms()
            self._needs_upload = True

    # ── OpenGL lifecycle ──

    def initializeGL(self):
        if not _HAS_GL:
            return
        try:
            glClearColor(*self._bg)
            glEnable(GL_DEPTH_TEST)
            # IboView RenderBacksides = false, but orbital lobes are open
            # surfaces whose insides must stay visible, so culling is disabled
            # and the inside is lit via calc_base_color(true) instead.
            glDisable(GL_CULL_FACE)

            vs = compile_shader(VERT, GL_VERTEX_SHADER)
            self._prog_orb = link_program(vs, compile_shader(FRAG_ORB, GL_FRAGMENT_SHADER))
            vs2 = compile_shader(VERT, GL_VERTEX_SHADER)
            self._prog_atom = link_program(vs2, compile_shader(FRAG_ATOM, GL_FRAGMENT_SHADER))

            self._gl_ok = True

            # Depth-peeling resources are optional: if anything fails we fall
            # back to sorted alpha blending.
            try:
                vs3 = compile_shader(VERT, GL_VERTEX_SHADER)
                self._prog_orb_dp = link_program(
                    vs3, compile_shader(FRAG_ORB_DP, GL_FRAGMENT_SHADER))
                vq = compile_shader(VERT_QUAD, GL_VERTEX_SHADER)
                self._prog_combine = link_program(
                    vq, compile_shader(FRAG_COMBINE_DP, GL_FRAGMENT_SHADER))
                self._vao_quad = glGenVertexArrays(1)
                self._peel = [PeelTarget(), PeelTarget()]
                self._dp_ok = True
                self._status(
                    f"就绪 — 渲染器已就绪 (depth peeling ×{self._dp_layers})，"
                    f"双击轨道列表即可在此渲染，也可拖放 .cub 文件到画布")
            except Exception as e:
                self._dp_ok = False
                self._status(f"OpenGL 就绪；depth peeling 不可用，回退排序混合: {e}")
        except Exception as e:
            self._status(f"OpenGL 初始化失败: {e}")
            traceback.print_exc()

    def resizeGL(self, w, h):
        glViewport(0, 0, max(1, w), max(1, h))
        # Peel targets are rebuilt lazily in _ensure_peel_targets().

    def _ensure_peel_targets(self, w, h):
        """(Re)create the peeling FBOs when the drawable size changed."""
        if not self._dp_ok:
            return False
        try:
            for t in self._peel:
                if t.fbo == 0 or t.w != w or t.h != h:
                    t.create(w, h)
            return True
        except Exception as e:
            self._dp_ok = False
            self._status(f"FBO 创建失败，回退排序混合: {e}")
            return False

    def paintGL(self):
        if not self._gl_ok:
            glClearColor(0.2, 0.2, 0.2, 1); glClear(GL_COLOR_BUFFER_BIT); return

        # Deferred upload (Qt already made the context current before paintGL)
        if self._needs_upload:
            try:
                self._upload()
                self._needs_upload = False
            except Exception as e:
                self._status(f"上传失败: {e}")
                traceback.print_exc()

        self._render()

    # ── Internal ──

    def _atom_color(self, anum):
        """Return the (r,g,b) ball colour for an atom under the current style."""
        if self._mol_style == "VMD single" and anum == 6:
            # Brighter, lighter, more vivid gold than the style's base c_rgb.
            g = self._mol_single_rgb
            return (min(1.0, g[0] * 1.15 + 0.22),
                    min(1.0, g[1] * 1.20 + 0.16),
                    min(1.0, g[2] * 1.10 + 0.02))
        if self._mol_style == "Mono white":
            return (1.0, 1.0, 1.0)
        if self._mol_style == "Gray pub":
            return (0.82, 0.82, 0.82)
        if self._mol_style == "Jmol":
            return _JMOL_COLORS.get(anum, (0.78, 0.78, 0.78))
        if self._mol_style == "Neon":
            return _NEON_COLORS.get(anum, (0.80, 0.80, 0.85))
        if self._mol_style == "GaussView":
            return _GVIEW_COLORS.get(anum, (0.78, 0.78, 0.78))
        if self._mol_style == "HoukMol":
            return _GVIEW_COLORS.get(anum, (0.78, 0.78, 0.78))
        # CPK (IboView ElementColors)
        return _IBO_ELEMENT_COLORS[anum] if anum < len(_IBO_ELEMENT_COLORS) else (0.5, 0.5, 0.5)

    def _gen_atoms(self):
        """Generate the opaque molecule model (atoms + bonds).

        Atom spheres use IboView's AtomicRadii table (scaled by ATOM_DRAW_SCALE);
        bonds are generated with IboView's GenerateBonds() geometric heuristic:
            r_ij <= 0.5 * (bf_i + bf_j) * (cov_i + cov_j)  ⇒  a bond
        Bonds are drawn as grey cylinders (IboView default DiffuseColor
        (0.2,0.2,0.2,1)) using the same opaque shader as the atoms.
        """
        if not self._cube or not self._cube.atoms:
            if not self._molecule:
                self._meshes[2] = GlMesh()
                return
            atoms = self._molecule  # 独立分子数据（载入 fchk/xyz 时设置，单位 Bohr）
        else:
            atoms = self._cube.atoms
        n = len(atoms)
        # Gaussian cube files store atomic coordinates in Bohr, and the orbital
        # isosurface is generated in that same Bohr frame.  The ball-and-stick
        # model must therefore stay in Bohr too: atom centres and bond vectors use
        # the raw coords, and bond-length thresholds use the covalent radii in
        # Bohr (g_CovalentRadii, BOHR units) so the comparison is unit-consistent.
        coords = np.array([[a[2], a[3], a[4]] for a in atoms], dtype=np.float64)
        anums = [int(a[0]) for a in atoms]

        all_v = []; all_n = []; all_c = []; all_i = []; off = 0
        # ── atom spheres ──
        # Colours come from IboView's ElementColors table (Rasmol CPK-new),
        # indexed by atomic number. Two molecule styles:
        # "CPK"        : every element coloured by its CPK tint
        # "VMD single" : CPK for all non-carbon atoms, carbon uses the
        #                current isosurface style's VMD c_rgb (gold for most)
        use_vmd = (self._mol_style == "VMD single")
        carbon_rgb = self._mol_single_rgb
        for k in range(n):
            anum = anums[k]
            ax, ay, az = coords[k]
            r = _atom_base_radius(anum) * ATOM_DRAW_SCALE * self._atom_scale
            if k in self._selected_atoms:
                # 选中的原子高亮为亮绿色，便于确认左键已选中
                col = (0.2, 1.0, 0.2)
            else:
                col = self._atom_color(anum)
            v, nrm, idx = make_sphere(r, 3)
            v = v + np.array([ax, ay, az])
            c = np.tile(np.array([*col, 1.], dtype=np.float32), (len(v), 1))
            all_v.append(v); all_n.append(nrm); all_c.append(c)
            all_i.append(idx + off); off += len(v)

        # ── bonds (IboView GenerateBonds geometric heuristic, dual-threshold) ──
        # Solid bonds: rij <= rf_tight * cov_sum   (tapered cylinders)
        # Dashed bonds: rf_tight < rij <= rf_loose  (segmented cylinders)
        bond_r = max(BOND_DRAW_SCALE * 0.4 * self._bond_scale, 0.04 * self._bond_scale)
        # IboView renders a solid bond as two tapered half-cylinders joined at midpoint.
        cyl_a = make_tapered_cylinder(1.0, self._bond_thinning, 1.0, 12)   # atom side (thick → thin)
        cyl_b = make_tapered_cylinder(self._bond_thinning, 1.0, 1.0, 12)   # centre side (thin → thick)
        bf_tight = self._bond_rf_tight
        bf_loose = self._bond_rf_loose
        dash_w = self._dash_weight

        for i in range(n):
            for j in range(i + 1, n):
                p = coords[i]; q = coords[j]
                rij = float(np.linalg.norm(q - p))
                if rij < 1e-4:
                    continue
                zi = anums[i]; zj = anums[j]
                # Use the Bohr-valued covalent radii (g_CovalentRadii) so the
                # threshold is compared in the same Bohr frame as the coords.
                ci = _COVALENT_RADII_BOHR[zi] if zi < len(_COVALENT_RADII_BOHR) else 0.7
                cj = _COVALENT_RADII_BOHR[zj] if zj < len(_COVALENT_RADII_BOHR) else 0.7
                cov_sum = ci + cj

                # Check manual bond override first (user context-menu action)
                key = (i, j)
                override = self._bond_overrides.get(key)
                if override is not None:
                    if override == 'none':
                        continue           # forced no bond
                    elif override == 'dashed':
                        is_dashed = True   # forced dashed
                    else:  # 'solid'
                        is_dashed = False  # forced solid
                else:
                    # Auto-detection: any contact within the thresholds is drawn
                    # as a SOLID bond. No automatic dashed bonds.
                    is_dashed = False
                    # Hydrogen handling: H–H never bonds (e.g. the three H on a
                    # methyl group stay separate), and any bond involving H uses
                    # a tighter absolute cap because H only bonds to its nearest
                    # heavy atom (C–H ≈ 1.09 Å).
                    has_H = (zi == 1 or zj == 1)
                    if has_H and zi == 1 and zj == 1:
                        continue           # H–H: never a bond
                    if has_H:
                        cap = BOND_MAX_DIST_H_ANG / BOHR_TO_ANGSTROM
                    else:
                        cap = BOND_MAX_DIST_ANG / BOHR_TO_ANGSTROM
                    if (rij <= bf_tight * cov_sum
                            or rij <= bf_loose * cov_sum
                            or rij <= cap):
                        pass               # solid bond
                    else:
                        continue           # no bond

                # Determine bond colour per the molecule style
                if self._mol_style == "HoukMol":
                    # HoukMol: 整条键统一黑色（从中间分界但两端同色）
                    col_i = col_j = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
                else:
                    # GaussView / 默认: 键从中点分隔，两端各用两端原子的元素色（半色键）
                    col_i = np.array([*self._atom_color(zi), 1.0], dtype=np.float32)
                    col_j = np.array([*self._atom_color(zj), 1.0], dtype=np.float32)

                if is_dashed:
                    # Dashed bond: a string of small black spheres along p→q
                    dv, dn, di = make_dashed_bond_geometry(
                        p, q, bond_r, n_segments=0, dash_weight=dash_w,
                        dot_size=self._dot_size_scale,
                        dot_spacing=self._dot_spacing_scale, seg=12)
                    if len(dv) > 0:
                        # 虚线键固定为黑色小圆球，不随原子/分子配色变化
                        dc = np.tile(np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32),
                                     (len(dv), 1))
                        all_v.append(dv.astype(np.float32))
                        all_n.append(dn.astype(np.float32))
                        all_c.append(dc.astype(np.float32))
                        all_i.append(di.astype(np.uint32) + off)
                        off += len(dv)
                else:
                    # Solid bond: two tapered half-cylinders
                    mid = (p + q) * 0.5
                    for src, end in ((p, mid), (mid, q)):
                        d = (end - src); hl = float(np.linalg.norm(d)); d /= hl
                        up = np.array([0.0, 1.0, 0.0])
                        v = np.cross(up, d)
                        c = float(np.dot(up, d))
                        if np.linalg.norm(v) < 1e-6:
                            R = np.eye(3) if c > 0 else -np.eye(3)
                        else:
                            vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
                            R = np.eye(3) + vx + vx @ vx * (1.0 / (1.0 + c))
                        S = np.diag([bond_r, hl, bond_r])
                        T = R @ S
                        cv, cn, ci_ = cyl_a if src is p else cyl_b
                        tv = cv @ T.T + src
                        tn = cn @ R.T
                        half_col = col_i if src is p else col_j
                        tc = np.tile(half_col, (len(tv), 1))
                        all_v.append(tv.astype(np.float32)); all_n.append(tn.astype(np.float32)); all_c.append(tc.astype(np.float32))
                        all_i.append(ci_ + off); off += len(tv)

        if all_v:
            surf = IsoSurface()
            surf.vertices = np.vstack(all_v).astype(np.float32)
            surf.normals = np.vstack(all_n).astype(np.float32)
            surf.colors = np.vstack(all_c).astype(np.float32)
            surf.indices = np.concatenate(all_i).astype(np.uint32)
            self._atom_surf = surf
        else:
            self._atom_surf = None
        # GPU upload is deferred to _upload() (called from paintGL with the
        # GL context already current) so atoms are not lost when load() runs
        # before the context is bound.

    def _upload(self):
        for i, s in enumerate([self._pos_surf, self._neg_surf]):
            self._meshes[i].upload(s)
        self._meshes[2].upload(self._atom_surf)

    # ── Ball-and-stick scale controls ──

    def set_molecule(self, atoms, bonds=None):
        """载入 fchk/xyz 时设置独立分子数据（坐标单位 Angstrom，与 MolCanvas 一致）。

        内部转换为 Bohr 存储到 self._molecule；之后即使尚未加载轨道 cube，
        画布也会显示分子球棍模型，满足「先显示分子，双击轨道再看」的需求。
        atoms 格式：[(idx, symbol, anum, (x, y, z)), ...]
        """
        if not atoms:
            self._molecule = None
            self._gen_atoms()
            self._needs_upload = True
            self.update()
            return
        # 载入新分子时清除旧轨道残留（若有），保证只显示分子结构
        self._cube = None
        self._pos_surf = None
        self._neg_surf = None
        conv = ANGSTROM_TO_BOHR
        self._molecule = [
            (a[2], 0.0, a[3][0] * conv, a[3][1] * conv, a[3][2] * conv)
            for a in atoms
        ]
        self._gen_atoms()
        self._needs_upload = True
        self.update()

    def set_atom_scale(self, scale):
        """Set atom ball radius multiplier and regenerate the molecule model."""
        self._atom_scale = float(scale)
        if self._molecule is not None or self._cube is not None:
            self._gen_atoms()
            self._needs_upload = True
            self.update()

    def set_bond_scale(self, scale):
        """Set bond cylinder radius multiplier and regenerate the molecule model."""
        self._bond_scale = float(scale)
        if self._molecule is not None or self._cube is not None:
            self._gen_atoms()
            self._needs_upload = True
            self.update()

    def set_bond_thinning(self, t):
        """Set the bond waist factor (1.0 = uniform cylinder, lower = thinner
        at the midpoint). Regenerates the molecule model."""
        self._bond_thinning = max(0.2, min(1.0, float(t)))
        if self._molecule is not None or self._cube is not None:
            self._gen_atoms()
            self._needs_upload = True
            self.update()

    def set_bond_rf_tight(self, value):
        """Set tight bond radius factor — bonds within this threshold are solid."""
        self._bond_rf_tight = max(0.5, min(3.0, float(value)))
        if self._molecule is not None or self._cube is not None:
            self._gen_atoms()
            self._needs_upload = True
            self.update()

    def set_bond_rf_loose(self, value):
        """Set loose bond radius factor — bonds beyond tight but within this
        are dashed; beyond this are not drawn at all."""
        self._bond_rf_loose = max(0.5, min(3.0, float(value)))
        if self._bond_rf_loose < self._bond_rf_tight:
            self._bond_rf_loose = self._bond_rf_tight + 0.05
        if self._molecule is not None or self._cube is not None:
            self._gen_atoms()
            self._needs_upload = True
            self.update()

    def set_dash_weight(self, value):
        """Set dashed bond fill ratio (0..1). 0.4 = IboView default."""
        self._dash_weight = max(0.05, min(1.0, float(value)))
        if self._molecule is not None or self._cube is not None:
            self._gen_atoms()
            self._needs_upload = True
            self.update()

    def set_dot_size(self, value):
        """Set the size scale of the small spheres used for dashed bonds."""
        self._dot_size_scale = max(0.2, min(4.0, float(value)))
        if self._molecule is not None or self._cube is not None:
            self._gen_atoms()
            self._needs_upload = True
            self.update()

    def set_dot_spacing(self, value):
        """Set the spacing scale between dashed-bond dots (>1 → sparser)."""
        self._dot_spacing_scale = max(0.3, min(4.0, float(value)))
        if self._molecule is not None or self._cube is not None:
            self._gen_atoms()
            self._needs_upload = True
            self.update()

    def set_atom_outline(self, on, color=None, width=None):
        """Toggle a silhouette outline on the atom (ball-and-stick) spheres.

        on:    True/False
        color: optional (r,g,b) edge colour (0..1)
        width: optional 0..1 silhouette band thickness"""
        self._atom_outline = bool(on)
        if color is not None:
            self._atom_outline_color = tuple(float(x) for x in color[:3])
        if width is not None:
            self._atom_outline_width = float(width)
        self.update()

    # ── Projection (IboView style) ──

    def _projection(self, w, h, vp=None):
        """IboView-style orthographic projection.

        Mirrors FView3d::ResetProjectionAndZoom: the visible half-height is
        `BASE_EXTENT / zoom`, the camera sits at a fixed distance and the
        near/far planes bracket it generously so rotation never clips.
        """
        hh = self.cam.half_height()
        if vp is not None:
            ox, oy, tw, th, ew, eh = vp
            asp = ew / eh if eh > 0 else 1.0
            hw = hh * asp
            # world range covered by the full image, then the tile sub-range
            lx = -hw + (ox / ew) * (2.0 * hw)
            ux = -hw + ((ox + tw) / ew) * (2.0 * hw)
            ly = -hh + (oy / eh) * (2.0 * hh)
            uy = -hh + ((oy + th) / eh) * (2.0 * hh)
            d = self.cam.CAM_DIST
            near = 0.02 * d
            far = 2.0 * d
            return ortho(lx, ux, ly, uy, near, far)
        asp = w / h if h > 0 else 1.0
        hw = hh * asp
        d = self.cam.CAM_DIST
        near = 0.02 * d
        far = 2.0 * d
        return ortho(-hw, hw, -hh, hh, near, far)

    def _render(self, w=None, h=None, vp=None):
        # QOpenGLWidget's framebuffer is already scaled by devicePixelRatio,
        # so use the widget size directly for the viewport.  `w`/`h` may be
        # overridden for offscreen high-resolution (supersampled) export.  `vp`
        # is an optional (ox, oy, tw, th, ew, eh) tile window (see _projection).
        if w is None or h is None:
            w = max(1, self.width()); h = max(1, self.height())
        proj = self._projection(w, h, vp)
        view = self.cam.view()
        nm = self.cam.normal()

        glViewport(0, 0, w, h)
        glClearColor(*self._bg)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        self.render_opaque(view, nm, proj)

        used_dp = False
        if self._dp_ok and self._dp_layers > 0:
            try:
                used_dp = self.render_transparent_depth_peeling(view, nm, proj, w, h)
            except Exception as e:
                self._dp_ok = False
                self._status(f"depth peeling 失败，回退排序混合: {e}")
                used_dp = False
        if not used_dp:
            self.render_transparent_sorted_fallback(view, nm, proj)

        glDisable(GL_BLEND)
        glDepthMask(GL_TRUE)

    def render_opaque(self, view, nm, proj):
        """Opaque geometry (atoms): depth test + depth write, no blending."""
        glEnable(GL_DEPTH_TEST); glDepthFunc(GL_LESS); glDepthMask(GL_TRUE)
        glDisable(GL_BLEND)
        glUseProgram(self._prog_atom)
        self._set_xforms(self._prog_atom, view, nm, proj)
        self.set_iboview_uniforms(self._prog_atom, self._sp['a_reg'],
                                  diffuse=(0.8, 0.8, 0.8, 1.0))
        self._set_atom_outline_uniforms()
        self._meshes[2].draw()

    def render_transparent_depth_peeling(self, view, nm, proj, w, h):
        """Front-to-back depth peeling, following IboView's FView3d::RenderScene.

        Pass i renders only the fragments strictly nearer than the depth
        recorded in pass i-1 (shader FRAG_ORB_DP), and each resulting layer is
        composited over the main framebuffer with regular
        `GL_SRC_ALPHA / GL_ONE_MINUS_SRC_ALPHA` blending.  Because the layers
        arrive in exact front-to-back order the result is order independent.
        """
        if not self._ensure_peel_targets(w, h):
            return False
        if self._meshes[0].count == 0 and self._meshes[1].count == 0:
            return True

        main_fbo = glGetIntegerv(GL_FRAMEBUFFER_BINDING)
        # Depth of the already-rendered opaque geometry: orbital fragments
        # behind it must never appear, so seed the peel buffers with it.
        opaque_depth = self._peel[1]

        glBindFramebuffer(GL_FRAMEBUFFER, opaque_depth.fbo)
        glViewport(0, 0, w, h)
        glClearColor(0, 0, 0, 0)
        glClearDepth(1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glEnable(GL_DEPTH_TEST); glDepthFunc(GL_LESS); glDepthMask(GL_TRUE)
        glDisable(GL_BLEND)
        glUseProgram(self._prog_atom)
        self._set_xforms(self._prog_atom, view, nm, proj)
        self.set_iboview_uniforms(self._prog_atom, self._sp['a_reg'],
                                  diffuse=(0.8, 0.8, 0.8, 1.0))
        self._set_atom_outline_uniforms()
        self._meshes[2].draw()

        glActiveTexture(GL_TEXTURE0)
        prog = self._prog_orb_dp
        glUseProgram(prog)
        self._set_xforms(prog, view, nm, proj)
        self.set_iboview_uniforms(prog, self._sp['o_reg'],
                                  diffuse=(1.0, 1.0, 1.0, self._sp['opacity']))
        glUniform1i(glGetUniformLocation(prog, 'Depth1'), 0)

        for layer in range(self._dp_layers):
            src = self._peel[(layer + 1) % 2]   # depth written by previous pass
            dst = self._peel[layer % 2]

            # ── Peel one layer into `dst` ──
            glBindFramebuffer(GL_FRAMEBUFFER, dst.fbo)
            glViewport(0, 0, w, h)
            glClearColor(0, 0, 0, 0)
            glClearDepth(1.0)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            glEnable(GL_DEPTH_TEST); glDepthFunc(GL_LESS); glDepthMask(GL_TRUE)
            glDisable(GL_BLEND)

            glUseProgram(prog)
            glActiveTexture(GL_TEXTURE0)
            glBindTexture(GL_TEXTURE_2D, src.tex_depth)
            self._meshes[0].draw()
            self._meshes[1].draw()

            # ── Composite this layer over the main framebuffer ──
            glBindFramebuffer(GL_FRAMEBUFFER, main_fbo)
            glViewport(0, 0, w, h)
            glDisable(GL_DEPTH_TEST)
            glDepthMask(GL_FALSE)
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            glUseProgram(self._prog_combine)
            glActiveTexture(GL_TEXTURE0)
            glBindTexture(GL_TEXTURE_2D, dst.tex_color)
            glUniform1i(glGetUniformLocation(self._prog_combine, 'LayerColor'), 0)
            glBindVertexArray(self._vao_quad)
            glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
            glBindVertexArray(0)

        glBindTexture(GL_TEXTURE_2D, 0)
        glBindFramebuffer(GL_FRAMEBUFFER, main_fbo)
        glViewport(0, 0, w, h)
        glEnable(GL_DEPTH_TEST)
        glDepthMask(GL_TRUE)
        return True

    def render_transparent_sorted_fallback(self, view, nm, proj):
        """Back-to-front sorted alpha blending (used when peeling is off).

        Instead of blindly drawing the positive lobe before the negative one,
        both meshes are split into chunks whose view-space depth is known and
        the chunks are drawn far-to-near, which removes most of the obvious
        layer-ordering artefacts.
        """
        glEnable(GL_DEPTH_TEST); glDepthFunc(GL_LESS)
        glDepthMask(GL_FALSE)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glUseProgram(self._prog_orb)
        self._set_xforms(self._prog_orb, view, nm, proj)
        self.set_iboview_uniforms(self._prog_orb, self._sp['o_reg'],
                                  diffuse=(1.0, 1.0, 1.0, self._sp['opacity']))

        # View-space z of each mesh's chunks; more negative == farther away.
        draws = []
        for mi in (0, 1):
            mesh = self._meshes[mi]
            if mesh.count == 0:
                continue
            for c0, c1, ctr in mesh.chunks():
                p = view @ np.array([ctr[0], ctr[1], ctr[2], 1.0])
                draws.append((float(p[2]), mesh, c0, c1))
        draws.sort(key=lambda d: d[0])          # farthest (most negative z) first
        for _z, mesh, c0, c1 in draws:
            mesh.draw_range(c0, c1)

    def _set_xforms(self, prog, view, nm, proj):
        glUniformMatrix4fv(glGetUniformLocation(prog, 'u_ModelView'), 1, GL_TRUE, view)
        glUniformMatrix3fv(glGetUniformLocation(prog, 'u_NormalMatrix'), 1, GL_TRUE, nm)
        glUniformMatrix4fv(glGetUniformLocation(prog, 'u_Projection'), 1, GL_TRUE, proj)

    def _set_regs(self, prog, regs):
        loc = [glGetUniformLocation(prog, f'ShaderReg{i}') for i in range(4)]
        for i in range(4):
            glUniform1f(loc[i], regs[i])

    def set_iboview_uniforms(self, prog, regs, diffuse):
        """Upload the IboView shader registers, fade parameters and DiffuseColor.

        DiffuseColor is kept white for orbitals so that v_Color (the green/red
        phase colour) alone determines the hue, exactly as in IboView where the
        per-vertex colour carries the phase and DiffuseColor.a is the opacity.
        """
        self._set_regs(prog, regs)
        glUniform1f(glGetUniformLocation(prog, 'FadeBias'), self._sp['FadeBias'])
        glUniform1f(glGetUniformLocation(prog, 'FadeWidth'), self._sp['FadeWidth'])
        glUniform4f(glGetUniformLocation(prog, 'DiffuseColor'), *diffuse)

    def _set_atom_outline_uniforms(self):
        """Push the current atom-outline state into the atom shader program."""
        p = self._prog_atom
        glUniform1f(glGetUniformLocation(p, 'u_Outline'),
                    1.0 if self._atom_outline else 0.0)
        oc = self._atom_outline_color
        glUniform3f(glGetUniformLocation(p, 'u_OutlineColor'), oc[0], oc[1], oc[2])
        glUniform1f(glGetUniformLocation(p, 'u_OutlineWidth'), self._atom_outline_width)

    # ── Mouse ──

    def wheelEvent(self, e): self.cam.zoom(e.angleDelta().y()); self.update()
    def keyPressEvent(self, e):
        if e.key() == Qt.Key_R: self.reset_view()
        elif e.key() == Qt.Key_S and self._cube:
            p, _ = QFileDialog.getSaveFileName(self, "Save", "screenshot.png", "PNG (*.png)")
            if p: self.screenshot(p)
        else: super().keyPressEvent(e)


# ═══════════════════════════════════════════════════════════════
# Main Window
# ═══════════════════════════════════════════════════════════════

def _ensure_pyopengl():
    """Check and auto-install PyOpenGL if missing."""
    try:
        import OpenGL.GL
        import OpenGL.GLU
        return True
    except ImportError:
        pass

    # Try to install
    import subprocess
    py_exe = sys.executable
    info = f"Python: {py_exe}\nPython 版本: {sys.version.split()[0]}"
    detail = f"{info}\n\n检测到 PyOpenGL 未安装。\n是否自动安装？"

    from PyQt5.QtWidgets import QMessageBox
    btn = QMessageBox.question(
        None, "PyOpenGL 未安装", detail,
        QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
    if btn != QMessageBox.Yes:
        return False

    try:
        subprocess.check_call(
            [py_exe, "-m", "pip", "install", "PyOpenGL", "PyOpenGL-accelerate"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        QMessageBox.information(None, "完成",
            "PyOpenGL 安装成功!\n请重新启动程序。")
    except Exception as e:
        QMessageBox.critical(None, "安装失败",
            f"pip install 失败:\n{e}\n\n请手动运行:\npip install PyOpenGL")
    return False


class CubViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Cube Viewer — OpenGL 实时渲染")
        self.resize(1200, 750)
        self.setMinimumSize(800, 500)

        # Runtime PyOpenGL check (not module-level)
        if not _ensure_pyopengl():
            QTimer.singleShot(0, self.close)
            return

        cw = QWidget(); self.setCentralWidget(cw)
        hl = QHBoxLayout(cw); hl.setContentsMargins(6,6,6,6); hl.setSpacing(6)

        # GL
        self.glw = CubGLWidget(self)
        self.glw.set_status_callback(self._set_status)
        hl.addWidget(self.glw, stretch=3)

        # Panel
        pn = QWidget(); pn.setMaximumWidth(300)
        pn.setStyleSheet("""
            QWidget {
                background: #ffffff; color: #111111;
                font-family: "Microsoft YaHei", "微软雅黑", sans-serif;
            }
            QGroupBox {
                background: #ffffff; color: #111111;
                border: 1px solid #bbbbbb; border-radius: 4px;
                margin-top: 8px; padding-top: 12px; font-weight: bold;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QLineEdit { background: #ffffff; color: #111111; border: 1px solid #aaaaaa; border-radius: 3px; padding: 3px; }
            QComboBox { background: #ffffff; color: #111111; border: 1px solid #aaaaaa; border-radius: 3px; padding: 3px; }
            QComboBox QAbstractItemView {
                background: #ffffff; color: #111111; selection-background-color: #2a7fff;
                selection-color: #ffffff; border: 1px solid #aaaaaa; outline: 0;
                max-height: 220px;
            }
            QPushButton { background: #f0f0f0; color: #111111; border: 1px solid #aaaaaa; border-radius: 3px; padding: 5px 12px; font-weight: bold; }
            QPushButton:hover { background: #e2e2e2; }
            QPushButton#LoadBtntn { background: #1a6fc4; border-color: #1a6fc4; color: #ffffff; font-size: 14px; padding: 8px; }
            QPushButton#LoadBtntn:hover { background: #2080e0; }
        """)
        pl = QVBoxLayout(pn); pl.setContentsMargins(4,4,4,4); pl.setSpacing(8)

        # File
        gf = QGroupBox("文件")
        fl = QVBoxLayout(gf)
        fh = QHBoxLayout()
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText("选择 .cub 文件或拖放到窗口...")
        fh.addWidget(self._path_edit)
        btn_b = QPushButton("..."); btn_b.setMaximumWidth(30)
        btn_b.clicked.connect(self._browse); fh.addWidget(btn_b)
        fl.addLayout(fh)
        btn_l = QPushButton("加载并显示"); btn_l.clicked.connect(self._do_load)
        btn_l.setObjectName("LoadBtn")
        fl.addWidget(btn_l)
        pl.addWidget(gf)

        # Style
        gs = QGroupBox("风格")
        sl = QVBoxLayout(gs)
        self._style_cb = QComboBox()
        self._style_cb.addItems(STYLE_DISPLAY)
        self._style_cb.currentIndexChanged.connect(self._on_style)
        # 参考 VMD：下拉列表一次只显示有限条目，超出部分用滚动条浏览，
        # 避免风格很多时弹出菜单过长。
        self._style_cb.setMaxVisibleItems(10)
        _cb_view = QListView()
        _cb_view.setUniformItemSizes(True)
        _cb_view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)  # type: ignore[attr-defined]
        _cb_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # type: ignore[attr-defined]
        self._style_cb.setView(_cb_view)
        sl.addWidget(self._style_cb)
        pl.addWidget(gs)

        # Isovalue
        # NOTE: the "值" field below is an ABSOLUTE isovalue in cube-file units.
        # This is NOT the same as IboView's `IsoThreshold` (default 80.0),
        # which is a *relative* threshold: the iso surface enclosing 80 % of
        # the total |data| weight.  Tick "IboView 相对阈值" to use that mode.
        gi = QGroupBox("等值面")
        il = QGridLayout(gi)

        self._rel_chk = QCheckBox(
            f"IboView 相对阈值 ({IBOVIEW_DEFAULTS['IsoThreshold']:.0f}%)")
        self._rel_chk.setToolTip(
            "勾选后按 IboView IsoThreshold 语义取等值面：\n"
            "选取使 |data| 累积权重达到指定百分比的等值面。\n"
            "取消勾选则使用下方的绝对 isovalue（cube 文件原始单位）。")
        self._rel_chk.toggled.connect(self._on_rel_mode)
        il.addWidget(self._rel_chk, 0, 0, 1, 3)

        self._rel_sld = QSlider(Qt.Horizontal)
        self._rel_sld.setRange(50, 99)
        self._rel_sld.setValue(int(IBOVIEW_DEFAULTS['IsoThreshold']))
        self._rel_sld.valueChanged.connect(self._on_rel_slider)
        self._rel_sld.setEnabled(False)
        il.addWidget(QLabel("百分比:"), 1, 0)
        il.addWidget(self._rel_sld, 1, 1)
        self._rel_lbl = QLabel(f"{IBOVIEW_DEFAULTS['IsoThreshold']:.0f}%")
        self._rel_lbl.setMinimumWidth(50)
        il.addWidget(self._rel_lbl, 1, 2)

        il.addWidget(QLabel("值:"), 2, 0)
        self._iso_sld = QSlider(Qt.Horizontal)
        self._iso_sld.setRange(1, 500); self._iso_sld.setValue(50)
        self._iso_sld.valueChanged.connect(self._on_iso_slider)
        il.addWidget(self._iso_sld, 2, 1)
        self._iso_edit = QLineEdit("0.050")
        self._iso_edit.setValidator(QDoubleValidator(0.005, 0.5, 4))
        self._iso_edit.setMaximumWidth(70)
        self._iso_edit.editingFinished.connect(self._on_iso_edit)
        il.addWidget(self._iso_edit, 2, 2)

        il.addWidget(QLabel("不透明:"), 3, 0)
        self._op_sld = QSlider(Qt.Horizontal)
        op0 = int(IBOVIEW_DEFAULTS['OrbitalOpacity'] * 100)
        self._op_sld.setRange(5, 100); self._op_sld.setValue(op0)
        self._op_sld.valueChanged.connect(self._on_op)
        il.addWidget(self._op_sld, 3, 1)
        self._op_edit = QLineEdit(f"{IBOVIEW_DEFAULTS['OrbitalOpacity']:.2f}")
        self._op_edit.setValidator(QDoubleValidator(0.05, 1, 2))
        self._op_edit.setMaximumWidth(70)
        self._op_edit.editingFinished.connect(self._on_op_edit)
        il.addWidget(self._op_edit, 3, 2)

        self._dp_chk = QCheckBox(
            f"Depth peeling ({IBOVIEW_DEFAULTS['DepthPeelingLayers']} 层)")
        self._dp_chk.setChecked(True)
        self._dp_chk.setToolTip("关闭后回退到按 chunk 深度排序的 alpha 混合")
        self._dp_chk.toggled.connect(self._on_dp_toggle)
        il.addWidget(self._dp_chk, 4, 0, 1, 3)
        pl.addWidget(gi)

        # Ball-and-stick control
        gb = QGroupBox("球棍模型")
        bl = QGridLayout(gb)
        bl.addWidget(QLabel("原子半径:"), 0, 0)
        self._atom_scale_sld = QSlider(Qt.Horizontal)
        self._atom_scale_sld.setRange(20, 300)   # ×0.2 .. ×3.0
        self._atom_scale_sld.setValue(100)        # ×1.0
        self._atom_scale_sld.valueChanged.connect(self._on_atom_scale_sld)
        bl.addWidget(self._atom_scale_sld, 0, 1)
        self._atom_scale_edit = QLineEdit("1.00")
        self._atom_scale_edit.setValidator(QDoubleValidator(0.20, 3.00, 2))
        self._atom_scale_edit.setMaximumWidth(70)
        self._atom_scale_edit.editingFinished.connect(self._on_atom_scale_edit)
        bl.addWidget(self._atom_scale_edit, 0, 2)

        bl.addWidget(QLabel("化学键:"), 1, 0)
        self._bond_scale_sld = QSlider(Qt.Horizontal)
        self._bond_scale_sld.setRange(20, 300)    # ×0.2 .. ×3.0
        self._bond_scale_sld.setValue(100)        # ×1.0
        self._bond_scale_sld.valueChanged.connect(self._on_bond_scale_sld)
        bl.addWidget(self._bond_scale_sld, 1, 1)
        self._bond_scale_edit = QLineEdit("1.00")
        self._bond_scale_edit.setValidator(QDoubleValidator(0.20, 3.00, 2))
        self._bond_scale_edit.setMaximumWidth(70)
        self._bond_scale_edit.editingFinished.connect(self._on_bond_scale_edit)
        bl.addWidget(self._bond_scale_edit, 1, 2)
        pl.addWidget(gb)

        # Bond detection thresholds (IboView BondRadiusFactor dual-threshold)
        gbrf = QGroupBox("成键阈值")
        brfl = QGridLayout(gbrf)
        brfl.addWidget(QLabel("实线键:"), 0, 0)
        self._brf_tight_sld = QSlider(Qt.Horizontal)
        self._brf_tight_sld.setRange(50, 200)   # ×0.50 .. ×2.00
        self._brf_tight_sld.setValue(100)         # ×1.00 (default)
        self._brf_tight_sld.valueChanged.connect(self._on_brf_tight)
        brfl.addWidget(self._brf_tight_sld, 0, 1)
        self._brf_tight_edit = QLineEdit("1.00")
        self._brf_tight_edit.setValidator(QDoubleValidator(0.50, 2.00, 2))
        self._brf_tight_edit.setMaximumWidth(70)
        self._brf_tight_edit.editingFinished.connect(self._on_brf_tight_edit)
        brfl.addWidget(self._brf_tight_edit, 0, 2)

        brfl.addWidget(QLabel("虚线键:"), 1, 0)
        self._brf_loose_sld = QSlider(Qt.Horizontal)
        self._brf_loose_sld.setRange(50, 300)   # ×0.50 .. ×3.00
        self._brf_loose_sld.setValue(130)         # ×1.30 (IboView default)
        self._brf_loose_sld.valueChanged.connect(self._on_brf_loose)
        brfl.addWidget(self._brf_loose_sld, 1, 1)
        self._brf_loose_edit = QLineEdit("1.30")
        self._brf_loose_edit.setValidator(QDoubleValidator(0.50, 3.00, 2))
        self._brf_loose_edit.setMaximumWidth(70)
        self._brf_loose_edit.editingFinished.connect(self._on_brf_loose_edit)
        brfl.addWidget(self._brf_loose_edit, 1, 2)

        brfl.addWidget(QLabel("虚线密度:"), 2, 0)
        self._dash_w_sld = QSlider(Qt.Horizontal)
        self._dash_w_sld.setRange(5, 100)    # 0.05 .. 1.00
        self._dash_w_sld.setValue(40)         # 0.40 (IboView default)
        self._dash_w_sld.valueChanged.connect(self._on_dash_w)
        brfl.addWidget(self._dash_w_sld, 2, 1)
        self._dash_w_edit = QLineEdit("0.40")
        self._dash_w_edit.setValidator(QDoubleValidator(0.05, 1.00, 2))
        self._dash_w_edit.setMaximumWidth(70)
        self._dash_w_edit.editingFinished.connect(self._on_dash_w_edit)
        brfl.addWidget(self._dash_w_edit, 2, 2)

        brfl.addWidget(QLabel("虚线大小:"), 3, 0)
        self._dot_size_sld = QSlider(Qt.Horizontal)
        self._dot_size_sld.setRange(20, 400)   # ×0.2 .. ×4.0
        self._dot_size_sld.setValue(100)         # ×1.0
        self._dot_size_sld.valueChanged.connect(self._on_dot_size_sld)
        brfl.addWidget(self._dot_size_sld, 3, 1)
        self._dot_size_lbl = QLabel("1.00")
        self._dot_size_lbl.setMaximumWidth(70)
        brfl.addWidget(self._dot_size_lbl, 3, 2)

        brfl.addWidget(QLabel("虚线间隔:"), 4, 0)
        self._dot_spacing_sld = QSlider(Qt.Horizontal)
        self._dot_spacing_sld.setRange(30, 400)  # ×0.3 .. ×4.0
        self._dot_spacing_sld.setValue(100)       # ×1.0
        self._dot_spacing_sld.valueChanged.connect(self._on_dot_spacing_sld)
        brfl.addWidget(self._dot_spacing_sld, 4, 1)
        self._dot_spacing_lbl = QLabel("1.00")
        self._dot_spacing_lbl.setMaximumWidth(70)
        brfl.addWidget(self._dot_spacing_lbl, 4, 2)
        pl.addWidget(gbrf)

        # Buttons
        ga = QGroupBox("操作")
        al = QVBoxLayout(ga)
        btn_r = QPushButton("重置视角 (R)"); btn_r.clicked.connect(self.glw.reset_view)
        al.addWidget(btn_r)
        btn_sc = QPushButton("截图 (S)"); btn_sc.clicked.connect(self._screenshot)
        al.addWidget(btn_sc)

        # High-resolution export (IboView-style offscreen render)
        ex = QHBoxLayout()
        ex.addWidget(QLabel("DPI:"))
        self._dpi_edit = QLineEdit("600")
        self._dpi_edit.setValidator(QDoubleValidator(50, 2400, 0))
        self._dpi_edit.setMaximumWidth(60)
        ex.addWidget(self._dpi_edit)
        btn_ex = QPushButton("导出图片")
        btn_ex.clicked.connect(self._export_image)
        ex.addWidget(btn_ex)
        al.addLayout(ex)
        pl.addWidget(ga)

        # Status
        self._status_lbl = QLabel("就绪 — 选择 .cub 文件开始")
        self._status_lbl.setStyleSheet("color:#888; font-size:12px;")
        pl.addWidget(self._status_lbl)
        pl.addStretch()

        hl.addWidget(pn)

        # Drag-drop
        self.setAcceptDrops(True)

        # Style
        self.setStyleSheet("""
            QMainWindow { background: #2b2b2b; }
            QWidget { color: #ddd; font-size: 13px; }
            QGroupBox { border: 1px solid #555; border-radius: 4px; margin-top: 8px; padding-top: 12px; font-weight: bold; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QLineEdit { background: #3a3a3a; border: 1px solid #555; border-radius: 3px; padding: 3px; color: #eee; }
            QComboBox { background: #3a3a3a; color: #eee; border: 1px solid #555; border-radius: 3px; padding: 3px; }
            QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 18px; border: none; }
            QComboBox QAbstractItemView {
                background: #3a3a3a; color: #eee; selection-background-color: #1a6fc4;
                selection-color: #fff; border: 1px solid #555; outline: 0;
            }
            QPushButton { background: #444; color: #eee; border: 1px solid #666; border-radius: 3px; padding: 5px 12px; font-weight: bold; }
            QPushButton:hover { background: #555; }
            QPushButton#LoadBtn { background: #1a6fc4; border-color: #1a6fc4; color: white; font-size: 14px; padding: 8px; }
            QPushButton#LoadBtn:hover { background: #2080e0; }
            QSlider::groove:horizontal { height: 6px; background: #3a3a3a; border-radius: 3px; }
            QSlider::handle:horizontal { width: 14px; height: 14px; margin: -5px 0; background: #1a6fc4; border-radius: 7px; }
        """)

        # Arg or timer
        if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]) and sys.argv[1].endswith('.cub'):
            self._path_edit.setText(os.path.abspath(sys.argv[1]))
            QTimer.singleShot(200, self._do_load)
        else:
            self._path_edit.setText(os.path.abspath(r"..\COCr-NBO_MOh.cub")
                                   if os.path.exists(r"..\COCr-NBO_MOh.cub") else "")

    def _set_status(self, msg):
        self._status_lbl.setText(msg)

    def _browse(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择 Cube 文件", "",
            "Cube Files (*.cub *.cube);;All (*)")
        if p:
            self._path_edit.setText(p)
            QTimer.singleShot(100, self._do_load)

    def _do_load(self):
        p = self._path_edit.text().strip()
        if not p or not os.path.isfile(p):
            QMessageBox.warning(self, "提示", "请选择有效的 .cub 文件")
            return
        iso = float(self._iso_edit.text() or "0.05")
        sname = STYLE_NAMES[self._style_cb.currentIndex()]
        self.glw.set_style(sname)

        note = ""
        if self._rel_chk.isChecked():
            # IboView-like relative threshold: derive an absolute isovalue that
            # encloses `percent` % of the total |data| weight.
            try:
                cd = read_cube(p)
                pct = float(self._rel_sld.value())
                iso = relative_iso_threshold(cd, pct)
                self._iso_edit.blockSignals(True)
                self._iso_edit.setText(f"{iso:.4f}")
                self._iso_edit.blockSignals(False)
                note = f"  (相对阈值 {pct:.0f}% -> iso={iso:.4f})"
            except Exception as e:
                QMessageBox.warning(self, "提示", f"相对阈值计算失败，改用绝对值: {e}")

        if self.glw.load(p, iso):
            self._status_lbl.setText(f"已加载: {os.path.basename(p)}{note}")
        else:
            QMessageBox.warning(self, "错误", f"加载失败: {p}\n请查看控制台输出。")

    def _on_style(self, idx):
        self.glw.set_style(STYLE_NAMES[idx])

    def _on_rel_mode(self, on):
        self._rel_sld.setEnabled(bool(on))
        self._iso_sld.setEnabled(not on)
        self._iso_edit.setEnabled(not on)
        if on:
            self._status_lbl.setText("相对阈值模式：点击“加载”后按百分比重新取面")

    def _on_rel_slider(self, v):
        self._rel_lbl.setText(f"{v}%")
        if self._rel_chk.isChecked() and self.glw.cube is not None:
            try:
                iso = relative_iso_threshold(self.glw.cube, float(v))
            except Exception:
                return
            self._iso_edit.blockSignals(True)
            self._iso_edit.setText(f"{iso:.4f}")
            self._iso_edit.blockSignals(False)
            self.glw.set_isovalue(iso)

    def _on_dp_toggle(self, on):
        self.glw.set_depth_peeling(bool(on))

    def _on_iso_slider(self, v):
        iso = v / 1000.0
        self._iso_edit.blockSignals(True)
        self._iso_edit.setText(f"{iso:.3f}")
        self._iso_edit.blockSignals(False)
        self.glw.set_isovalue(iso)

    def _on_iso_edit(self):
        try:
            iso = float(self._iso_edit.text())
        except ValueError:
            return
        iso = max(0.005, min(iso, 0.5))
        self._iso_sld.blockSignals(True)
        self._iso_sld.setValue(int(iso * 1000))
        self._iso_sld.blockSignals(False)
        self.glw.set_isovalue(iso)

    def _on_op(self, v):
        op = v / 100.0; self._op_edit.setText(f"{op:.2f}"); self.glw.set_opacity(op)

    def _on_op_edit(self):
        try: op = float(self._op_edit.text())
        except: return
        op = max(0.05, min(op, 1))
        self._op_sld.blockSignals(True); self._op_sld.setValue(int(op*100)); self._op_sld.blockSignals(False)
        self.glw.set_opacity(op)

    def _on_atom_scale_sld(self, val):
        s = val / 100.0
        self._atom_scale_edit.blockSignals(True)
        self._atom_scale_edit.setText(f"{s:.2f}")
        self._atom_scale_edit.blockSignals(False)
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
        self.glw.set_atom_scale(s)

    def _on_bond_scale_sld(self, val):
        s = val / 100.0
        self._bond_scale_edit.blockSignals(True)
        self._bond_scale_edit.setText(f"{s:.2f}")
        self._bond_scale_edit.blockSignals(False)
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
        self.glw.set_bond_scale(s)

    def _on_brf_tight(self, val):
        v = val / 100.0
        self._brf_tight_edit.blockSignals(True)
        self._brf_tight_edit.setText(f"{v:.2f}")
        self._brf_tight_edit.blockSignals(False)
        self.glw.set_bond_rf_tight(v)

    def _on_brf_tight_edit(self):
        try:
            v = float(self._brf_tight_edit.text())
        except ValueError:
            return
        v = max(0.50, min(v, 2.00))
        self._brf_tight_sld.blockSignals(True)
        self._brf_tight_sld.setValue(int(v * 100))
        self._brf_tight_sld.blockSignals(False)
        self.glw.set_bond_rf_tight(v)

    def _on_brf_loose(self, val):
        v = val / 100.0
        self._brf_loose_edit.blockSignals(True)
        self._brf_loose_edit.setText(f"{v:.2f}")
        self._brf_loose_edit.blockSignals(False)
        self.glw.set_bond_rf_loose(v)

    def _on_brf_loose_edit(self):
        try:
            v = float(self._brf_loose_edit.text())
        except ValueError:
            return
        v = max(0.50, min(v, 3.00))
        self._brf_loose_sld.blockSignals(True)
        self._brf_loose_sld.setValue(int(v * 100))
        self._brf_loose_sld.blockSignals(False)
        self.glw.set_bond_rf_loose(v)

    def _on_dash_w(self, val):
        v = val / 100.0
        self._dash_w_edit.blockSignals(True)
        self._dash_w_edit.setText(f"{v:.2f}")
        self._dash_w_edit.blockSignals(False)
        self.glw.set_dash_weight(v)

    def _on_dash_w_edit(self):
        try:
            v = float(self._dash_w_edit.text())
        except ValueError:
            return
        v = max(0.05, min(v, 1.00))
        self._dash_w_sld.blockSignals(True)
        self._dash_w_sld.setValue(int(v * 100))
        self._dash_w_sld.blockSignals(False)
        self.glw.set_dash_weight(v)

    def _on_dot_size_sld(self, val):
        v = val / 100.0
        self._dot_size_lbl.setText(f"{v:.2f}")
        self.glw.set_dot_size(v)

    def _on_dot_spacing_sld(self, val):
        v = val / 100.0
        self._dot_spacing_lbl.setText(f"{v:.2f}")
        self.glw.set_dot_spacing(v)

    def _screenshot(self):
        p, _ = QFileDialog.getSaveFileName(self, "Save", "cub_view.png", "PNG (*.png)")
        if p: self.glw.screenshot(p)

    def _export_image(self):
        p, _ = QFileDialog.getSaveFileName(self, "Export", "cub_view.png", "PNG (*.png)")
        if not p:
            return
        try:
            dpi = float(self._dpi_edit.text())
        except ValueError:
            dpi = 600.0
        dpi = max(50.0, min(dpi, 2400.0))
        self.glw.export_image(p, dpi=dpi)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls(): e.accept()
    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if p.lower().endswith(('.cub', '.cube')):
                self._path_edit.setText(p)
                QTimer.singleShot(100, self._do_load)
                return

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape: self.close()
        else: super().keyPressEvent(e)


# ═══════════════════════════════════════════════════════════════
# Entry
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = CubViewer()
    w.show()
    sys.exit(app.exec_())
