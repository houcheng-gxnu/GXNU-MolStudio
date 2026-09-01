"""
cub_viewer.py — 独立 .cub 文件可视化工具
==========================================
独立运行: python cubviewer.py（项目根目录）
或拖放 .cub 文件到窗口。

基于 IboView 渲染管线: depth peeling 透明度 + 三向 Phong 光照

本文件部分 shader 代码、原子半径/颜色/共价半径表与默认渲染参数
逐字移植自 IboView (Copyright (c) 2015 Gerald Knizia, GPLv3)。
本项目作为 IboView 的衍生作品，依 GNU GPLv3 发布。
"""

import ctypes
import math
import os
import sys
import numpy as np
import traceback

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QComboBox, QPushButton, QSlider,
    QGroupBox, QFileDialog, QMessageBox, QGridLayout, QCheckBox, QListView,
)
from PyQt5.QtCore import Qt, QPoint, QTimer, QRectF, QPointF
from PyQt5.QtGui import (
    QDoubleValidator, QSurfaceFormat, QImage,
    QPainter, QColor, QPen, QBrush, QLinearGradient,
    QRadialGradient, QFont, QFontMetrics, QPainterPath,
)

# ── OpenGL imports ──
try:
    from OpenGL.GL import *
    from OpenGL.GLU import *
    _HAS_GL = True
except ImportError:
    _HAS_GL = False

from PyQt5.QtWidgets import QOpenGLWidget

from file_dialogs import open_file, save_file

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
IBO_DEFAULT_O = [0.8, 0.7, 0.7, -0.5]   # default orbital (used by style_params)

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

# ── 金属原子球缩放 ────────────────────────────────────────
# IboView 的 AtomicRadii 是 vdW 类经验半径，金属普遍偏大（Cs 4.86、K 3.69），
# 球棍模型里显得过于臃肿。金属按 _METAL_RADIUS_FACTOR 缩小，并用
# _METAL_MIN_RADIUS 兜底：保证金属球仍大于常见非金属（Cl 1.97 / S 2.04 /
# P 2.08 / Si 2.11），不破坏「金属 ≥ 非金属」的直觉。
_METAL_RADIUS_FACTOR = 2.0 / 3.0
_METAL_MIN_RADIUS = 2.15

# 金属元素（碱/碱土/过渡/后过渡/镧系/锕系）。类金属 B/Si/Ge/As/Se/Sb/Te
# 不参与缩放，保持 IboView 原值。
_METAL_SET = frozenset(
    {3, 4, 11, 12, 13,                     # Li Be Na Mg Al
     19, 20,                               # K Ca
     21, 22, 23, 24, 25, 26, 27, 28, 29, 30,      # Sc → Zn
     31,                                   # Ga
     37, 38,                               # Rb Sr
     39, 40, 41, 42, 43, 44, 45, 46, 47, 48,      # Y → Cd
     49, 50,                               # In Sn
     55, 56,                               # Cs Ba
     } | set(range(57, 72))                # La → Lu（镧系）
      | set(range(72, 81))                 # Hf → Hg
      | {81, 82, 83, 84}                   # Tl Pb Bi Po
      | {87, 88}                           # Fr Ra
      | set(range(89, 104))                # Ac → Lr（锕系）
)


def _atom_base_radius(anum):
    """原子绘制基础半径：金属缩小 1/3 并设下限，非金属用 IboView 原值。

    金属：max(原值 × 2/3, 2.15) —— 碱金属/碱土/镧系等大金属真正缩到 1/3，
    过渡金属受下限约束（缩 10%~25%），但都保证大于常见非金属。
    越界元素回退到 0.4。
    """
    if 0 <= anum < len(_ATOM_DRAW_RADII):
        r = _ATOM_DRAW_RADII[anum]
        if anum in _METAL_SET:
            return max(r * _METAL_RADIUS_FACTOR, _METAL_MIN_RADIUS)
        return r
    return 0.4


def _ring_normal(az_deg, tilt_deg):
    """由 MolCanvas 的环定义（azimuth/tilt）算环面单位法线（世界系）。

    u = (-sin az, cos az, 0); v = (-cos az·sin tilt, -sin az·sin tilt, cos tilt)
    n = u × v
    """
    az = math.radians(az_deg)
    ti = math.radians(tilt_deg)
    ux = -math.sin(az); uy = math.cos(az); uz = 0.0
    vx = -math.cos(az) * math.sin(ti)
    vy = -math.sin(az) * math.sin(ti)
    vz = math.cos(ti)
    n = np.array([uy * vz - uz * vy,
                  uz * vx - ux * vz,
                  ux * vy - uy * vx], dtype=np.float64)
    n = n / (np.linalg.norm(n) + 1e-12)
    return n


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

# 画布右键菜单统一样式：白底黑字（覆盖全局主题对 QMenu 的继承，
# 保证浅色/深色系统下都可读）。_show_context_menu 与 _measure_label_menu 共用。
_QMENU_QSS = """
    QMenu {
        background-color: #FFFFFF;
        color: #000000;
        border: 1px solid #C9CED6;
        padding: 4px 0px;
    }
    QMenu::item {
        background: transparent;
        color: #000000;
        padding: 6px 28px 6px 14px;
    }
    QMenu::item:selected {
        background-color: #E3EBF4;
        color: #000000;
    }
    QMenu::item:disabled {
        color: #9AA3AD;
    }
    QMenu::separator {
        height: 1px;
        background: #E1E5EA;
        margin: 4px 8px;
    }
"""

# 字体/颜色对话框（非原生）统一样式：白底黑字。与 _QMENU_QSS 同理念。
_QDIALOG_QSS = """
    QColorDialog, QFontDialog {
        background-color: #FFFFFF;
        color: #000000;
    }
    QColorDialog QLabel, QFontDialog QLabel {
        background: transparent;
        color: #000000;
    }
    QColorDialog QLineEdit, QFontDialog QLineEdit,
    QColorDialog QComboBox, QFontDialog QComboBox,
    QColorDialog QFontComboBox, QFontDialog QFontComboBox,
    QColorDialog QSpinBox, QFontDialog QSpinBox {
        background-color: #FFFFFF;
        color: #000000;
        border: 1px solid #C9CED6;
    }
    QColorDialog QListWidget, QFontDialog QListWidget {
        background-color: #FFFFFF;
        color: #000000;
    }
    QColorDialog QCheckBox, QFontDialog QCheckBox,
    QColorDialog QRadioButton, QFontDialog QRadioButton {
        background: transparent;
        color: #000000;
    }
    QColorDialog QPushButton, QFontDialog QPushButton {
        background-color: #F8FAFE;
        color: #000000;
        border: 1px solid #C9CED6;
        padding: 4px 14px;
    }
    QColorDialog QPushButton:hover, QFontDialog QPushButton:hover {
        background-color: #E3EBF4;
    }
"""
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

# Van-der-Waals radii — standard Bondi (1964) single-bond table, in **Å**.
# Index = atomic number (entry 0 is a dummy). Values are the widely-used
# Bondi numbers (H 1.20, C 1.70, N 1.55, O 1.52, F/Cl 1.47/1.75, P/S 1.80,
# Br 1.85, I 1.98, …). Beyond the table we fall back to a generic 1.8 Å.
_VDW_RADII_A = [
    0.00, 1.20, 1.40, 1.82, 1.53, 1.92, 1.70, 1.55, 1.52, 1.47,  # 0-9
    1.54, 2.27, 1.73, 2.10, 1.80, 1.80, 1.75, 1.88, 1.88, 2.75,  # 10-19
    2.75, 2.64, 2.40, 2.30, 2.15, 2.05, 2.05, 2.00, 2.00, 2.10,  # 20-29
    2.05, 2.00, 2.00, 2.00, 2.05, 2.10, 2.05, 2.42, 2.15, 2.00,  # 30-39
    2.00, 2.00, 2.00, 2.10, 2.10, 2.05, 2.05, 2.05, 2.05, 2.10,  # 40-49
    2.05, 2.10, 2.10, 2.15, 2.10, 2.15, 2.10, 2.05, 2.20, 2.10,  # 50-59
    2.15, 2.15, 2.10, 2.10, 2.05, 2.05, 2.10, 2.20, 2.15, 2.20,  # 60-69
    2.20, 2.25, 2.25, 2.25, 2.25, 2.30, 2.25, 2.20, 2.20, 2.25,  # 70-79
    2.30, 2.30, 2.30, 2.35, 2.35, 2.35, 2.35, 2.35, 2.35, 2.40,  # 80-89
    2.40, 2.40, 2.40, 2.45, 2.45, 2.45, 2.45, 2.45, 2.45, 2.50,  # 90-99
    2.50, 2.50, 2.50, 2.50, 2.50, 2.50, 2.50, 2.50, 2.50, 2.50,  # 100-109
]
_VDW_RADII = [r / BOHR_TO_ANGSTROM for r in _VDW_RADII_A[:110]]  # store in Bohr (matches coords' frame)


def _vdw_radius(anum):
    """Van-der-Waals radius (Bondi 1964) in Bohr; falls back to 1.8 Å."""
    if 0 <= anum < len(_VDW_RADII):
        return _VDW_RADII[anum]
    return 1.8 / BOHR_TO_ANGSTROM


# 片元着色器里多球布尔差集一次性上传的原子球数上限。
# 必须与 FRAG_ATOM 里的 `#define VDW_MAX` 保持一致。
# 上限设 128：`vec3[128] + float[128]` = 384 + 128 = 512 个片元 uniform 分量，
# 加上其余光照/描边/圆环 uniform 仍远低于 GL 3.3 的片元 uniform 下限（1024）。
# 原 256 会达到 1024 分量，再加其它 uniform 就会在 Intel 核显等严格实现上
# 直接链接失败（uniform components exceeded）→ 整个原子着色器失效 → 分子消失。
VDW_MAX_ATOMS = 128

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

# ── Style catalogue ──
# All style definitions now live in fchk_orbital.STYLES (single source of truth).
STYLE_NAMES = list(STYLES.keys())
STYLE_DISPLAY = [f"{k}  — {v['desc']}" for k, v in STYLES.items()]

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
MOL_STYLE_NAMES = ["CPK", "VMD single", "Mono white", "Jmol", "Gray pub", "Neon", "GaussView", "HoukMol", "SobArt", "Vcube"]
MOL_STYLE_DISPLAY = ["CPK (按元素)", "VMD (碳金色)", "单色白", "Jmol", "灰度出版", "霓虹", "GaussView", "HoukMol", "SobArt (Chem311)", "Vcube (VMD 风格)"]

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

# HoukMol 原子配色：氢白色、碳浅灰（比 GaussView 碳 #8E8E8E 更浅），
# 其余元素沿用 GaussView 配色。
_HOUKMOL_COLORS = {
    1: (1.000, 1.000, 1.000),    # H  #FFFFFF 白色
    6: (0.667, 0.667, 0.667),    # C  #AAAAAA 浅灰
}

# SobArt / Chem311 palette — 逐字移植自 MolCanvas 的 SOB_ART_CPK
# （sobereva 推荐的 Chem3D 风格：棕碳、红氧、蓝氮……）
# 按用户要求：氢为纯白，碳调亮一档。
_SOB_ART_COLORS = {
    1: (1.000, 1.000, 1.000),    # H  #FFFFFF 白色
    6: (0.878, 0.769, 0.580),    # C  #E0C494 更明亮的暖沙色碳
    7: (0.188, 0.314, 0.973),    # N  #3050F8
    8: (1.000, 0.125, 0.063),    # O  #FF2010
    16: (1.000, 0.784, 0.196),   # S  #FFC832
    15: (1.000, 0.502, 0.125),   # P  #FF8020
    9: (0.478, 0.878, 0.376),    # F  #7AE060
    17: (0.188, 0.753, 0.251),   # Cl #30C040
    35: (0.502, 0.125, 0.125),   # Br #802020
    53: (0.384, 0.000, 0.384),   # I  #620062
}


# ═══════════════════════════════════════════════════════════════
# GLSL Shaders (inline)
# ═══════════════════════════════════════════════════════════════

VERT = """
#version 330 core
layout(location=0) in vec3 in_Pos;
layout(location=1) in vec3 in_Normal;
layout(location=2) in vec4 in_Color;
layout(location=3) in float in_BallId;   // 范德华外壳：所属原子序号（其余几何填 0 不剔除）
out vec3 v_Normal;
out vec4 v_Color;
out vec3 v_ModelPos;   // 未变换的模型坐标，供片元做球内剔除
out float v_BallId;
uniform mat4 u_ModelView;
uniform mat3 u_NormalMatrix;
uniform mat4 u_Projection;
void main() {
    gl_Position = u_Projection * (u_ModelView * vec4(in_Pos, 1.0));
    v_Normal = u_NormalMatrix * in_Normal;
    v_Color = in_Color;
    v_ModelPos = in_Pos;
    v_BallId = in_BallId;
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
uniform float u_Ambient;    // emissive / ambient term (0..~2); 0 = IboView default
uniform vec4  u_SpecColor;  // specular tint (RGB; default white)
uniform float u_SpecMul;    // specular strength multiplier (default 1)
uniform int   u_Fx;         // orbital material FX: 0=none, 1=neon rim, 2=pearl, 3=metal
uniform float u_FxStrength; // FX intensity (0..1)
uniform vec3  u_FxColor;    // FX auxiliary colour (rim / secondary sheen)
// 自定义光源方向（最多 4 盏；u_UseCustomLights=0 用 IboView 默认）
uniform vec3  u_L0, u_L1, u_L2, u_L3;
uniform float u_UseCustomLights;
uniform int   u_LightCount;   // 生效光源数（1..4）
uniform float u_Glow;         // 光晕大小（整体，1.0 = 默认；>1 更大更散）
uniform vec4  u_Glows;        // 每盏灯的光晕大小（u_Glows[i] 对应第 i 盏）

const vec3 D_L0 = vec3(0.5, 0.5, 0.70710678);
const vec3 D_L1 = vec3(-0.4330127, -0.25, 0.8660254);
const vec3 D_L2 = vec3(0.4330127, -0.25, 0.8660254);

// IboView: cDiffuse  = ShaderReg1 * pow(cos, ShaderReg0) * DiffuseColor
//          cSpecular = ShaderReg2 * (ShaderReg3*pow(cos,16) + 1.2*pow(cos,64))
vec4 light_term(vec3 N, vec3 L, float I, float glow) {
    float d = clamp(dot(N, L), 0.0, 1.0);
    vec4 diff = ShaderReg1 * pow(d, ShaderReg0) * DiffuseColor;
    // glow 缩放高光指数：越大光晕越散
    vec4 spec = ShaderReg2 * (ShaderReg3 * pow(d, 16.0 * glow) + 1.2 * pow(d, 64.0 * glow))
                * u_SpecColor * u_SpecMul;
    return I * (v_Color * diff + spec);
}

// IboView calc_base_color(FlipSides): if the fragment is back-facing and
// FlipSides is set (orbitals), the normal is inverted so the inside of the
// lobe is lit like a proper surface.
vec4 calc_base_color(bool FlipSides) {
    vec3 N = normalize(v_Normal);
    if (FlipSides && !gl_FrontFacing)
        N = -N;
    vec4 color = vec4(0.0);
    for (int i = 0; i < 4; i++) {
        if (i >= u_LightCount) break;
        vec3 L = (i == 0) ? u_L0 : (i == 1) ? u_L1 : (i == 2) ? u_L2 : u_L3;
        if (u_UseCustomLights < 0.5)
            L = (i == 0) ? D_L0 : (i == 1) ? D_L1 : (i == 2) ? D_L2 : vec3(0.0, 0.0, 1.0);
        float I = (i == 0) ? 1.0 : (i == 1) ? 0.6 : (i == 2) ? 0.5 : 0.4;
        float glow = (i == 0) ? u_Glows.x : (i == 1) ? u_Glows.y
                     : (i == 2) ? u_Glows.z : u_Glows.w;
        color += light_term(N, L, I, glow);
    }

    // IboView: only alpha is boosted at grazing angles.
    color[3] /= clamp(abs(N.z), 0.1, 1.0);

    // IboView FadeType=1: 按窗口深度（远处）淡出到白，形成景深雾化。
    float rz = clamp(FadeWidth * (gl_FragCoord.z - 0.5) + FadeBias, 0.0, 1.0);
    color.rgb = mix(color.rgb, vec3(1.0), rz);

    // Emissive glow (added after the fog so the lobe keeps its hue in depth).
    color.rgb += u_Ambient * v_Color.rgb;

    // Orbital-only material FX (rim glow / iridescent sheen / fresnel metal).
    if (FlipSides && u_Fx > 0) {
        // Rim = grazing-angle factor: 0 when the surface faces the camera
        // (|N.z| ~ 1), 1 at the silhouette (|N.z| ~ 0). Using |N.z| keeps it
        // symmetric for back faces (FlipSides already points them at the camera).
        float facing = clamp(abs(N.z), 0.0, 1.0);
        float rim = pow(1.0 - facing, 2.0);
        if (u_Fx == 1) {
            // Neon tube: a coloured glow hugging the silhouette.
            color.rgb += u_FxColor * rim * u_FxStrength;
        } else if (u_Fx == 2) {
            // Pearl / holographic: base hue slides toward u_FxColor near the rim.
            color.rgb = mix(color.rgb, u_FxColor, rim * u_FxStrength);
        } else if (u_Fx == 3) {
            // Metal: extra fresnel brightening of the (already tinted) specular.
            color.rgb += u_FxColor * rim * u_FxStrength * 0.6;
        }
    }

    return color;
}
"""

# ── MolViewer (MolCanvas) 球体径向渐变停靠点 ────────────────────
# 逐字换算自 molcanvas._make_sphere_gradient 的 QRadialGradient 停靠曲线。
# 每项 (t, mult, add) 表示 color = clamp(base*mult + add, 0, 1)，其中
# t = 片元到高光中心（左上偏移 0.3R）的距离 / R，与 MolCanvas 的
# QRadialGradient(center=highlight, radius=R) 一一对应。
_MV_GRAD_STOPS = {
    1: [(0.00, 1.00, 0.137), (0.06, 0.25, 0.75), (0.40, 0.95, 0.05),
        (0.65, 1.00, 0.00), (1.00, 0.75, 0.00)],                        # full (Houk)
    2: [(0.00, 1.00, 0.216), (0.25, 1.00, 0.00), (0.82, 0.82, 0.00),
        (1.00, 0.62, 0.00)],                                           # soft_matte
    3: [(0.00, 1.00, 0.137), (0.12, 0.60, 0.40), (0.40, 1.00, 0.00),
        (0.80, 0.85, 0.00), (1.00, 0.72, 0.00)],                       # subtle
    4: [(0.00, 1.00, 0.00), (1.00, 1.00, 0.00)],                        # flat
    5: [(0.00, 1.00, 0.373), (0.06, 0.10, 0.90), (0.14, 1.00, 0.00),
        (0.40, 1.00, 0.00), (0.68, 0.80, 0.00), (1.00, 0.55, 0.00)],   # sob_art
    6: [(0.00, 1.00, 0.333), (0.08, 1.00, 0.216), (0.30, 1.00, 0.00),
        (0.70, 0.95, 0.00), (1.00, 0.75, 0.00)],                       # apple_liquid
    7: [(0.00, 0.38, 0.62), (0.18, 0.74, 0.26), (0.56, 1.00, 0.00),
        (0.86, 0.90, 0.00), (1.00, 0.78, 0.00)],                       # paper_matte
    8: [(0.00, 1.00, 0.227), (0.05, 0.22, 0.78), (0.20, 0.66, 0.34),
        (0.52, 1.00, 0.00), (0.82, 0.84, 0.00), (1.00, 0.68, 0.00)],   # premium_full
    9: [(0.00, 0.58, 0.42), (0.20, 0.88, 0.12), (0.62, 1.00, 0.00),
        (0.84, 0.88, 0.00), (1.00, 0.70, 0.00)],                       # clay_matte
    10: [(0.00, 1.00, 0.431), (0.07, 0.08, 0.92), (0.24, 0.68, 0.32),
         (0.58, 1.00, 0.00), (0.82, 1.08, 0.00), (1.00, 0.66, 0.00)],  # glass_plus
    11: [(0.00, 1.00, 0.471), (0.10, 1.00, 0.282), (0.34, 1.00, 0.00),
         (0.70, 0.72, 0.00), (1.00, 0.42, 0.00)],                       # neon_glow
    12: [(0.00, 1.00, 0.00), (1.00, 1.00, 0.00)],                        # ink_flat
    13: [(0.00, 0.50, 0.50), (0.15, 0.80, 0.20), (0.50, 1.00, 0.00),
         (0.85, 0.714, 0.00), (1.00, 0.556, 0.00)],                     # gau_default
}
_MV_GRAD_IDS = {
    "full": 1, "soft_matte": 2, "subtle": 3, "flat": 4, "sob_art": 5,
    "apple_liquid": 6, "paper_matte": 7, "premium_full": 8, "clay_matte": 9,
    "glass_plus": 10, "neon_glow": 11, "ink_flat": 12, "gau_default": 13,
    "two_light": 14,   # 双光源：主光左上 + 辅光右下
    "four_light": 15,  # 四光源：主左上 + 辅右下 + 左 + 右
}
_MV_GRAD_BY_ID = {v: k for k, v in _MV_GRAD_IDS.items()}


def _gen_mv_ramp_glsl():
    """把 _MV_GRAD_STOPS 编译成 GLSL 的 mv_ramp(g, base, t) 分段线性插值函数。

    注意：各渐变分支必须用 else-if 链（不能是独立 if 块），否则末尾的兜底
    else 会挂到最后一个 if 上，把已赋值的 m/a 覆盖回基色（所有渐变变平）。
    """
    lines = [
        "uniform int u_MvGrad;   // 0 = IboView Phong; >0 = MolViewer radial-gradient id",
        "vec3 mv_ramp(int g, vec3 base, float t) {",
        "    vec3 m; vec3 a;",
    ]
    ids = sorted(_MV_GRAD_STOPS)
    for k, gid in enumerate(ids):
        stops = _MV_GRAD_STOPS[gid]
        cond = "if" if k == 0 else "else if"
        lines.append(f"    {cond} (g == {gid}) {{")
        for i in range(len(stops) - 1):
            t0, m0, a0 = stops[i]
            t1, m1, a1 = stops[i + 1]
            inner_cond = "if" if i == 0 else "else if"
            f = f"(t - {t0:.4g}) / {t1 - t0:.4g}"
            lines.append(
                f"        {inner_cond} (t <= {t1:.4g}) {{ "
                f"m = mix(vec3({m0:.4g}), vec3({m1:.4g}), {f}); "
                f"a = mix(vec3({a0:.4g}), vec3({a1:.4g}), {f}); }}")
        t_last, m_last, a_last = stops[-1]
        lines.append(f"        else {{ m = vec3({m_last:.4g}); a = vec3({a_last:.4g}); }}")
        lines.append("    }")
    lines.append("    else { m = vec3(1.0); a = vec3(0.0); }  // 兜底：基色")
    lines.append("    return clamp(base * m + a, 0.0, 1.0);")
    lines.append("}")
    return "\n".join(lines)


_MV_RAMP_GLSL = _gen_mv_ramp_glsl()

# 等值面单光点光照：固定左上光源 L，t = pow(1 - dot(N,L), 0.7)，复用 mv_ramp。
# （等值面是任意曲面，不能像原子那样用 N.xy 屏幕空间渐变，改用光源方向。）
# orb_outline：等值面剪影描边（与原子 u_Outline 同法，|N.z| 朝边沿处混入描边色）。
_MV_ORB_GLSL = """
uniform float u_OrbOutline;      // 0 = off, 1 = on
uniform vec3  u_OrbOutlineColor; // edge stroke colour
uniform float u_OrbOutlineWidth; // 0..1, thin silhouette band half-width

vec4 mv_orb_color(vec3 baseColor, float baseAlpha) {
    vec3 N = normalize(v_Normal);
    if (!gl_FrontFacing) N = -N;
    // 多光循环：方向/数量/光晕由 u_L0-3 + u_LightCount + u_Glows 控制
    vec3 col = vec3(0.0);
    float tot = 0.0;
    for (int i = 0; i < 4; i++) {
        if (i >= u_LightCount) break;
        vec3 L = (i == 0) ? u_L0 : (i == 1) ? u_L1 : (i == 2) ? u_L2 : u_L3;
        L = normalize(L);
        float d = clamp(dot(N, L), 0.0, 1.0);
        float glow = (i == 0) ? u_Glows.x : (i == 1) ? u_Glows.y : (i == 2) ? u_Glows.z : u_Glows.w;
        float t = pow(1.0 - d, 0.7 / glow);
        float w = (i == 0) ? 1.0 : 0.5;
        col += w * mv_ramp((u_LightCount > 1) ? 1 : u_MvGrad, baseColor, t);
        tot += w;
    }
    col /= max(tot, 1e-4);
    // 透明度：乘 DiffuseColor.a（等值面不透明度来自 _sp['opacity']）
    vec4 c = vec4(col, baseAlpha * DiffuseColor.a);
    float fade = clamp(FadeWidth * (gl_FragCoord.z - 0.5) + FadeBias, 0.0, 1.0);
    fade *= step(0.0001, FadeWidth);
    c.rgb *= mix(1.0, 0.55, fade);
    return c;
}

vec4 orb_outline(vec4 c) {
    if (u_OrbOutline > 0.5) {
        vec3 N = normalize(v_Normal);
        if (!gl_FrontFacing) N = -N;
        // 窄带剪影描边：只有 |N.z| 接近 0（屏幕边缘）才混入描边色，
        // 带宽由 u_OrbOutlineWidth 控制（0.03~0.2 为清晰细描边）。
        float facing = clamp(abs(N.z), 0.0, 1.0);
        float rim = 1.0 - step(u_OrbOutlineWidth, facing);
        c.rgb = mix(c.rgb, u_OrbOutlineColor, rim);
    }
    return c;
}
"""

# Orbital fragment shader — direct (no depth peeling) variant.
# 支持两种光照：u_MvGrad=0 → IboView 三灯 Phong；u_MvGrad>0 → MolViewer
# 单光点（固定左上光源，复用球体渐变停靠曲线）。
FRAG_ORB = """
#version 330 core
""" + _GLSL_COMMON + _MV_RAMP_GLSL + _MV_ORB_GLSL + """
layout(location=0) out vec4 out_Color;
void main() {
    vec4 c;
    if (u_MvGrad > 0) {
        c = mv_orb_color(v_Color.rgb, v_Color.a);
    } else {
        c = calc_base_color(true);
    }
    out_Color = orb_outline(c);
}
"""

# Orbital fragment shader — depth-peeling variant, mirrors pixel5_orb_dp.glsl:
# only keep fragments strictly in front of the previously peeled layer.
FRAG_ORB_DP = """
#version 330 core
""" + _GLSL_COMMON + _MV_RAMP_GLSL + _MV_ORB_GLSL + """
layout(location=0) out vec4 out_Color;
uniform sampler2D Depth1;
void main() {
    ivec2 iCoord2d = ivec2(gl_FragCoord.xy);
    float fDepth0 = texelFetch(Depth1, iCoord2d, 0).r;
    if (gl_FragCoord.z < fDepth0) {
        vec4 c;
        if (u_MvGrad > 0) {
            c = mv_orb_color(v_Color.rgb, v_Color.a);
        } else {
            c = calc_base_color(true);
        }
        out_Color = orb_outline(c);
    } else {
        discard;
    }
}
"""

# Opaque (atom) fragment shader — FlipSides=false, alpha from vertex colour.
# 支持两种光照：u_MvGrad=0 → IboView 三灯 Phong；u_MvGrad>0 → MolViewer
# 屏幕空间径向渐变（MolCanvas 逐字停靠曲线）。
# An optional silhouette outline (rim term) can be enabled via u_Outline so
# atoms get a clean edge stroke without any post-processing pass.
FRAG_ATOM = """
#version 330 core
""" + _GLSL_COMMON + """
layout(location=0) out vec4 out_Color;
uniform float u_Outline;       // 0 = off, 1 = on
uniform vec3  u_OutlineColor;  // edge stroke colour
uniform float u_OutlineWidth;  // 0..1, thickness of the silhouette band
uniform float u_Rings;         // 0 = off, 1 = on（十字圆环）
uniform vec3  u_RingColor;     // 圆环颜色
uniform float u_RingWidth;     // 环带半宽（法线夹角阈值，0.03~0.15）
uniform vec3  u_RingN1, u_RingN2;  // 两条环面法线（视图系）
// ── 范德华外壳：多球布尔差集（重叠区挖空）──
#define VDW_MAX 128   // 多球剔除的原子数上限（与 Python 侧 VDW_MAX_ATOMS 一致）
uniform float u_VdwEnable;            // 1 = 仅 vdW 外壳绘制时开启剔除
uniform int   u_VdwCount;            // 原子球数（≤ VDW_MAX）
uniform vec3  u_VdwCenter[VDW_MAX];   // 各原子球心（模型坐标）
uniform float u_VdwRadius[VDW_MAX];   // 各原子 vdW 半径
// ── vdW 外壳专属描边（独立于原子 u_Outline*，单独控制）──
uniform float u_VdwOutline;          // 0 = off, 1 = on
uniform vec3  u_VdwOutlineColor;     // 描边颜色
uniform float u_VdwOutlineWidth;     // 0..1 描边带宽
in vec3  v_ModelPos;   // 未变换的模型坐标（与 VERT 的 out v_ModelPos 配对）
in float v_BallId;     // 所属原子序号（与 VERT 的 out v_BallId 配对）
""" + _MV_RAMP_GLSL + """
void main() {
    // 范德华外壳：若该片元落在「其他」原子 vdW 球内，则挖掉（重叠区不显示）。
    // v_ModelPos 是顶点在球面、片元在三角面弦上的线性插值；直接用弦点做
    // 球内判定会让两球交线沿低模三角面呈波浪。这里把插值点沿径向投影回
    // 所属球面（truePos），交线即为两球面的真交线——一个平滑的圆。
    if (u_VdwEnable > 0.5) {
        int myId = int(v_BallId + 0.5);
        vec3 myC = u_VdwCenter[myId];
        vec3 truePos = myC + normalize(v_ModelPos - myC) * u_VdwRadius[myId];
        for (int j = 0; j < VDW_MAX; j++) {
            if (j >= u_VdwCount) break;
            if (j == myId) continue;  // 跳过自身
            if (distance(truePos, u_VdwCenter[j]) < u_VdwRadius[j]) {
                discard;
            }
        }
    }
    vec4 c;
    if (u_MvGrad > 0) {
        // MolViewer 径向渐变（光源方向/数量/光晕由 u_L0-3 + u_LightCount + u_Glows 控制）
        vec3 N = normalize(v_Normal);
        // vdW 外壳参考轨道等值面（mv_orb_color）：背面法线翻转，双面都正确受光
        if (u_VdwEnable > 0.5 && !gl_FrontFacing) N = -N;
        vec3 col = vec3(0.0);
        float tot = 0.0;
        for (int i = 0; i < 4; i++) {
            if (i >= u_LightCount) break;
            vec3 L = (i == 0) ? u_L0 : (i == 1) ? u_L1 : (i == 2) ? u_L2 : u_L3;
            L = normalize(L);
            // 高光中心 = 光方向投影到视图平面的 0.3 倍偏移
            float lm = max(length(L.xy), 1e-4);
            vec2 off = -0.3 * L.xy / lm;
            float glow = (i == 0) ? u_Glows.x : (i == 1) ? u_Glows.y : (i == 2) ? u_Glows.z : u_Glows.w;
            float t = length(N.xy + off) / glow;
            float w = (i == 0) ? 1.0 : 0.5;
            col += w * mv_ramp((u_LightCount > 1) ? 1 : u_MvGrad, v_Color.rgb, t);
            tot += w;
        }
        col /= max(tot, 1e-4);
        c = vec4(col, v_Color.a);
        // MolCanvas depth_factor: distant atoms darken (FadeWidth = 0 when off)
        float fade = clamp(FadeWidth * (gl_FragCoord.z - 0.5) + FadeBias, 0.0, 1.0);
        fade *= step(0.0001, FadeWidth);
        c.rgb *= mix(1.0, 0.55, fade);
    } else {
        // 原子走 calc_base_color(false)；vdW 外壳参考轨道等值面走
        // calc_base_color(true)：背面法线翻转 + 启用 FX（neon/pearl/metal）
        // + u_Ambient 自发光 + 高光染色，与轨道等值面材质一致。
        c = calc_base_color(u_VdwEnable > 0.5);
    }
    // 描边：原子用 u_Outline*，vdW 外壳用独立的 u_VdwOutline*（单独控制）。
    // v_Normal is in view space; the camera looks along -Z, so facing
    // fragments have |N.z| ~ 1 and silhouette fragments have |N.z| ~ 0.
    // 窄带剪影描边（与等值面 orb_outline 一致）：只有 |N.z| 接近 0
    // （屏幕边缘）才混入描边色；描边带宽越大描边越粗。
    float outlineOn = (u_VdwEnable > 0.5) ? u_VdwOutline : u_Outline;
    if (outlineOn > 0.5) {
        vec3  oc = (u_VdwEnable > 0.5) ? u_VdwOutlineColor : u_OutlineColor;
        float ow = (u_VdwEnable > 0.5) ? u_VdwOutlineWidth : u_OutlineWidth;
        float facing = abs(normalize(v_Normal).z);
        float rim = 1.0 - step(ow, facing);
        c.rgb = mix(c.rgb, oc, rim);
    }
    // 十字圆环：两条大圆带，直接用球面法线 N 与环面法线（视图系）的夹角判定。
    // 与原子描边同款技术——圆环就是球面几何的一部分，必然贴在球上；
    // 背面半环被球体自身深度遮挡，随分子旋转。
    if (u_Rings > 0.5) {
        vec3 RN = normalize(v_Normal);
        float r1 = abs(dot(RN, u_RingN1));
        float r2 = abs(dot(RN, u_RingN2));
        float r = min(r1, r2);
        float band = 1.0 - smoothstep(u_RingWidth * 0.7, u_RingWidth, r);
        c.rgb = mix(c.rgb, u_RingColor, band);
    }
    c.a = v_Color.a;
    out_Color = c;
}
"""

# Bond repaint ("二次上色") shader — identical lighting to FRAG_ATOM but
# WITHOUT the vdW carve-out / outline / ring machinery. Bonds are redrawn
# with this dedicated program at the end of each frame, so their colour is
# guaranteed independent of the vdW-shell state.
FRAG_BOND = """
#version 330 core
""" + _GLSL_COMMON + """
layout(location=0) out vec4 out_Color;
""" + _MV_RAMP_GLSL + """
void main() {
    vec4 c;
    if (u_MvGrad > 0) {
        // MolViewer 径向渐变（与 FRAG_ATOM 同款，键也随分子样式渐变）
        vec3 N = normalize(v_Normal);
        vec3 col = vec3(0.0);
        float tot = 0.0;
        for (int i = 0; i < 4; i++) {
            if (i >= u_LightCount) break;
            vec3 L = (i == 0) ? u_L0 : (i == 1) ? u_L1 : (i == 2) ? u_L2 : u_L3;
            L = normalize(L);
            float lm = max(length(L.xy), 1e-4);
            vec2 off = -0.3 * L.xy / lm;
            float glow = (i == 0) ? u_Glows.x : (i == 1) ? u_Glows.y : (i == 2) ? u_Glows.z : u_Glows.w;
            float t = length(N.xy + off) / glow;
            float w = (i == 0) ? 1.0 : 0.5;
            col += w * mv_ramp((u_LightCount > 1) ? 1 : u_MvGrad, v_Color.rgb, t);
            tot += w;
        }
        col /= max(tot, 1e-4);
        c = vec4(col, v_Color.a);
        float fade = clamp(FadeWidth * (gl_FragCoord.z - 0.5) + FadeBias, 0.0, 1.0);
        fade *= step(0.0001, FadeWidth);
        c.rgb *= mix(1.0, 0.55, fade);
    } else {
        c = calc_base_color(false);
    }
    c.a = v_Color.a;
    out_Color = c;
}
"""

# Minimal bond vertex shader (attributes 0-2 only; no vdW ball id).
VERT_BOND = """
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

# Fullscreen-quad pass used to composite one peeled layer, mirrors
# pixel5_combine_dp.glsl.
VERT_QUAD = """
#version 330 core
const vec2 kVerts[4] = vec2[4](
    vec2(-1.0,-1.0), vec2(1.0,-1.0), vec2(-1.0, 1.0), vec2(1.0, 1.0));
void main() { gl_Position = vec4(kVerts[gl_VertexID], 0.0, 1.0); }
"""

# Fullscreen-quad vertical 3-stop background gradient (MolViewer style).
VERT_BG = """
#version 330 core
const vec2 kVerts[4] = vec2[4](
    vec2(-1.0,-1.0), vec2(1.0,-1.0), vec2(-1.0, 1.0), vec2(1.0, 1.0));
const vec2 kUvs[4] = vec2[4](
    vec2(0.0,0.0), vec2(1.0,0.0), vec2(0.0,1.0), vec2(1.0,1.0));
out vec2 vUv;
void main() { vUv = kUvs[gl_VertexID]; gl_Position = vec4(kVerts[gl_VertexID], 0.0, 1.0); }
"""

FRAG_BG = """
#version 330 core
in vec2 vUv;
uniform vec3 uTop;
uniform vec3 uMid;
uniform vec3 uBot;
out vec4 out_Color;
void main() {
    vec3 c = (vUv.y < 0.5)
        ? mix(uMid, uTop, vUv.y * 2.0)
        : mix(uBot, uMid, (vUv.y - 0.5) * 2.0);
    out_Color = vec4(c, 1.0);
}
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

# ── 实时接触阴影 / 环境光遮蔽（屏幕空间，深度差版） ──
# 输入：场景颜色 + 场景深度（正交投影、线性 [0,1]，1.0=背景无几何）。
# 对每个几何像素统计周围各方向"样本更深"的占比 → 遮蔽因子（凹陷/缝隙
# 变暗，平滑面不变）；再沿主光方向找更近几何 → 方向光接触阴影。
# 深度梯度法线对平滑分子无效（深度变化≈0），故采用纯深度差判据。
FRAG_SSAO = """
#version 330 core
uniform sampler2D u_Color;
uniform sampler2D u_Depth;
uniform float u_Strength;   // AO 强度（0=关）
uniform float u_RadiusPx;   // 采样半径（像素，自适应）
uniform float u_Bias;       // 深度偏置（防自遮蔽）
uniform vec2 u_LightDir;    // 主光屏幕方向（归一化，指向光源）
out vec4 out_Color;

const int K = 24;   // 12 方向 × 2 半径层
const vec2 kDirs[12] = vec2[12](
    vec2( 1.0, 0.0), vec2(-1.0, 0.0), vec2(0.0, 1.0), vec2(0.0,-1.0),
    vec2( 0.7071, 0.7071), vec2(-0.7071, 0.7071),
    vec2( 0.7071,-0.7071), vec2(-0.7071,-0.7071),
    vec2( 0.9239, 0.3827), vec2(-0.9239, 0.3827),
    vec2( 0.9239,-0.3827), vec2(-0.9239,-0.3827));
const float kRadii[2] = float[2](0.5, 1.0);

void main() {
    ivec2 pc = ivec2(gl_FragCoord.xy);
    float d0 = texelFetch(u_Depth, pc, 0).r;
    vec3 col = texelFetch(u_Color, pc, 0).rgb;
    if (d0 >= 1.0 || u_Strength <= 0.0) {
        out_Color = vec4(col, 1.0);
        return;
    }
    float occ = 0.0;
    float wsum = 0.0;
    for (int i = 0; i < K; i++) {
        int dir = i / 2;
        int rad = i % 2;
        vec2 off = kDirs[dir] * u_RadiusPx * kRadii[rad];
        float ds = texelFetch(u_Depth, pc + ivec2(off), 0).r;
        if (ds >= 1.0) continue;                 // 样本在背景 → 不统计
        float w = 1.0 - length(off) / (u_RadiusPx + 1e-4);
        wsum += w;
        if (ds > d0 + u_Bias) occ += w;          // 样本更深（凹陷/缝隙）
    }
    float ao = 1.0 - u_Strength * (occ / max(wsum, 1e-4));
    // 方向光接触阴影：沿 -光方向（投影方向）找更近的几何 → 阴影
    float shadow = 0.0;
    if (length(u_LightDir) > 0.01) {
        for (int t = 1; t <= 4; t++) {
            ivec2 sp = pc + ivec2(u_LightDir * u_RadiusPx * float(t) * 0.6);
            float ds = texelFetch(u_Depth, sp, 0).r;
            if (ds >= 1.0) break;
            if (ds < d0 - u_Bias) { shadow = 1.0 - float(t) * 0.18; break; }
        }
    }
    ao = clamp(ao - shadow * 0.55, 0.0, 1.0);
    out_Color = vec4(col * ao, 1.0);
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


# 原始正二十面体（不细分）的 12 顶点 + 20 三角面，取自 IboView IvMesh.cpp
# 的 fIcosahedronCoordinates / iIcosahedronTriangles（MakeIcosahedron 用）。
_ICOSA_COORDS = np.array([
    [0.85065080835203999, 0.0, 0.52573111211913359],
    [0.85065080835203999, 0.0, -0.52573111211913359],
    [-0.85065080835203999, 0.0, 0.52573111211913359],
    [-0.85065080835203999, 0.0, -0.52573111211913359],
    [0.0, 0.52573111211913359, 0.85065080835203999],
    [0.0, -0.52573111211913359, 0.85065080835203999],
    [0.0, 0.52573111211913359, -0.85065080835203999],
    [0.0, -0.52573111211913359, -0.85065080835203999],
    [0.52573111211913359, 0.85065080835203999, 0.0],
    [-0.52573111211913359, 0.85065080835203999, 0.0],
    [0.52573111211913359, -0.85065080835203999, 0.0],
    [-0.52573111211913359, -0.85065080835203999, 0.0],
], dtype=np.float64)

_ICOSA_TRIS = np.array([
    [0, 1, 8], [0, 4, 5], [0, 5, 10], [0, 8, 4], [0, 10, 1],
    [1, 6, 8], [1, 7, 6], [1, 10, 7], [2, 3, 11], [2, 4, 9],
    [2, 5, 4], [2, 9, 3], [2, 11, 5], [3, 6, 7], [3, 7, 11],
    [3, 9, 6], [4, 8, 9], [5, 11, 10], [6, 9, 8], [7, 10, 11],
], dtype=np.int32)


def make_icosahedron(radius=1.0):
    """Generate a raw (unsubdivided) icosahedron with flat face normals.

    Returns (positions[N,3], normals[N,3], indices[M]) with N=M=60: three
    duplicated vertices per face for faceted (flat) shading, exactly like
    IboView's ``MakeIcosahedron`` selection marker.
    """
    pos = []
    nrm = []
    idx = []
    for t in _ICOSA_TRIS:
        v0 = _ICOSA_COORDS[t[0]] * radius
        v1 = _ICOSA_COORDS[t[1]] * radius
        v2 = _ICOSA_COORDS[t[2]] * radius
        fn = np.cross(v1 - v0, v2 - v0)
        fn /= (np.linalg.norm(fn) or 1.0)
        base = len(pos)
        pos.extend([v0, v1, v2])
        nrm.extend([fn, fn, fn])
        idx.extend([base, base + 1, base + 2])
    return (np.array(pos, dtype=np.float32),
            np.array(nrm, dtype=np.float32),
            np.array(idx, dtype=np.uint32))


def make_torus(radius=1.0, tube=0.34, n_major=48, n_minor=16):
    """参数化圆环（选中标记用）——环带半径 radius、管径 tube。

    返回 (positions[N,3], normals[N,3], indices[M])，光滑法线、共享顶点。
    """
    a = np.linspace(0.0, 2.0 * np.pi, n_major, endpoint=False)
    b = np.linspace(0.0, 2.0 * np.pi, n_minor, endpoint=False)
    verts = np.empty((n_major, n_minor, 3), dtype=np.float64)
    norms = np.empty_like(verts)
    for i in range(n_major):
        ca, sa = np.cos(a[i]), np.sin(a[i])
        for j in range(n_minor):
            cb, sb = np.cos(b[j]), np.sin(b[j])
            verts[i, j] = ((radius + tube * cb) * ca,
                           (radius + tube * cb) * sa,
                           tube * sb)
            norms[i, j] = (ca * cb, sa * cb, sb)
    idx = []
    for i in range(n_major):
        i2 = (i + 1) % n_major
        for j in range(n_minor):
            j2 = (j + 1) % n_minor
            v00 = i * n_minor + j
            v10 = i2 * n_minor + j
            v11 = i2 * n_minor + j2
            v01 = i * n_minor + j2
            idx.extend([v00, v10, v11, v00, v11, v01])
    return (verts.reshape(-1, 3).astype(np.float32),
            norms.reshape(-1, 3).astype(np.float32),
            np.array(idx, dtype=np.uint32))


def merge_iso_surfaces(chunks):
    """把多个 IsoSurface 合并成一个（顶点/法线/颜色/索引拼接）。

    用于多轨道叠加：每个轨道各自的等值面顶点已带各自颜色，这里按顺序拼接
    成单张 pos / neg 网格，交给不变的渲染管线绘制。
    """
    chunks = [c for c in chunks if c is not None and c.vertex_count > 0]
    if not chunks:
        return None
    out = IsoSurface()
    all_v, all_n, all_c, all_i = [], [], [], []
    voff = 0
    for c in chunks:
        all_v.append(c.vertices)
        all_n.append(c.normals)
        if c.colors is not None:
            all_c.append(c.colors)
        else:
            all_c.append(np.zeros((c.vertex_count, 4), dtype=np.float32))
        all_i.append(c.indices + voff)
        voff += c.vertex_count
    out.vertices = np.vstack(all_v).astype(np.float32)
    out.normals = np.vstack(all_n).astype(np.float32)
    out.colors = np.vstack(all_c).astype(np.float32)
    out.indices = np.concatenate(all_i).astype(np.uint32)
    return out


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


# Orbital material FX modes selectable per-style via the ``fx`` key.
_FX_MODES = {'neon': 1, 'pearl': 2, 'metal': 3}


def style_params(surface_mat, style=None):
    """Translate a vcube-style surface_mat into IboView shader registers plus
    the extended material uniforms (emissive ambient, tinted specular, orbital
    FX). IboView computes lighting as:
        cDiffuse = ShaderReg1 * pow(cos, ShaderReg0) * DiffuseColor
        cSpecular = ShaderReg2 * pow(cosS, ShaderReg3) * SpecularColor
    so we map diffuse->ShaderReg1, specular->ShaderReg2,
    shininess->ShaderReg0 (exponent) and ShaderReg3 (specular balance).

    ``style`` is the optional STYLES entry; it may carry extra keys to unlock
    the new material channels (all default to IboView's original look):
        fx:           'neon' | 'pearl' | 'metal' | None
        ambient:      emissive strength (0..~2)
        spec_color:   (r, g, b) specular tint (default white)
        spec_mul:     specular strength multiplier (default 1; 0 = matte)
        fx_strength:  0..1 intensity of the FX
        fx_color:     (r, g, b) rim / secondary sheen colour
    """
    amb, diff, spec, shin, mir, opac = surface_mat[:6]
    o = [IBO_DEFAULT_O[0], diff, max(spec, 0.0), shin]
    a = [IBO_DEFAULT_A[0], 0.65, 0.4, -0.5]
    sp = {
        'o_reg': o, 'a_reg': a,
        'FadeBias': IBOVIEW_DEFAULTS['FadeBias'],
        'FadeWidth': IBOVIEW_DEFAULTS['FadeWidth'],
        'opacity': opac,
        # Extended material uniforms — defaults reproduce IboView exactly.
        'ambient': 0.0,
        'spec_color': (1.0, 1.0, 1.0),
        'spec_mul': 1.0,
        'fx': 0,
        'fx_strength': 0.0,
        'fx_color': (1.0, 1.0, 1.0),
    }
    if style:
        fx = style.get('fx')
        if fx:
            sp['fx'] = _FX_MODES.get(fx, 0)
        if style.get('ambient') is not None:
            sp['ambient'] = float(style['ambient'])
        sc = style.get('spec_color')
        if sc and len(sc) >= 3:
            sp['spec_color'] = (float(sc[0]), float(sc[1]), float(sc[2]))
        if style.get('spec_mul') is not None:
            sp['spec_mul'] = float(style['spec_mul'])
        if style.get('fx_strength') is not None:
            sp['fx_strength'] = float(style['fx_strength'])
        fc = style.get('fx_color')
        if fc and len(fc) >= 3:
            sp['fx_color'] = (float(fc[0]), float(fc[1]), float(fc[2]))
    return sp

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
        self.vao = self.vbo_p = self.vbo_n = self.vbo_c = self.vbo_id = self.ebo = 0
        self.n_idx = self.n_vtx = 0
        self._chunks = []       # list of (first_index, index_count, centroid)
        self._gen = 0           # 上传代际：每次 upload() 递增，供外部缓存失效

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
        ids = getattr(surf, "ids", None)
        if ids is not None:
            self.vbo_id = glGenBuffers(1)
            glBindBuffer(GL_ARRAY_BUFFER, self.vbo_id)
            glBufferData(GL_ARRAY_BUFFER, ids.nbytes, ids, GL_STATIC_DRAW)
            glVertexAttribPointer(3, 1, GL_FLOAT, GL_FALSE, 0, None)
            glEnableVertexAttribArray(3)
        if self.n_idx > 0:
            self.ebo = glGenBuffers(1)
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.ebo)
            glBufferData(GL_ELEMENT_ARRAY_BUFFER, surf.indices.nbytes, surf.indices, GL_STATIC_DRAW)
        glBindVertexArray(0)
        self._gen += 1

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

    def draw_order(self, indices):
        """按给定的三角形索引顺序绘制（画家算法：每帧按视图深度重排）。

        使用独立的临时 EBO，画完恢复原 EBO 绑定，不影响 draw()。
        """
        if self.vao == 0 or self.n_idx == 0 or len(indices) == 0:
            return
        if not getattr(self, "_scratch_ebo", 0):
            self._scratch_ebo = glGenBuffers(1)
        glBindVertexArray(self.vao)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self._scratch_ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices,
                     GL_DYNAMIC_DRAW)
        glDrawElements(GL_TRIANGLES, len(indices), GL_UNSIGNED_INT, None)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.ebo)   # 还原 VAO 的 EBO 绑定
        glBindVertexArray(0)

    def upload_order(self, indices):
        """只上传重排后的索引到临时 EBO（不绘制），供 draw_order_range 分段用。"""
        if self.vao == 0 or len(indices) == 0:
            return
        if not getattr(self, "_scratch_ebo", 0):
            self._scratch_ebo = glGenBuffers(1)
        glBindVertexArray(self.vao)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self._scratch_ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices,
                     GL_DYNAMIC_DRAW)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.ebo)
        glBindVertexArray(0)

    def draw_order_range(self, first_tri, tri_count):
        """绘制临时 EBO 中第 first_tri 个三角形起的 tri_count 个三角形。"""
        if self.vao == 0 or tri_count <= 0:
            return
        glBindVertexArray(self.vao)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self._scratch_ebo)
        glDrawElements(GL_TRIANGLES, tri_count * 3, GL_UNSIGNED_INT,
                       ctypes.c_void_p(int(first_tri) * 3 * 4))
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.ebo)
        glBindVertexArray(0)

    def draw_points(self, point_size=3.0):
        """把已上传的顶点渲染成彩色点云（ESP PT 模式）。

        复用同一 VAO（位置 + 逐顶点颜色），glDrawArrays(GL_POINTS)。
        """
        if self.vao == 0 or self.n_vtx == 0:
            return
        glBindVertexArray(self.vao)
        glEnable(GL_PROGRAM_POINT_SIZE)
        glPointSize(float(point_size))
        glDrawArrays(GL_POINTS, 0, self.n_vtx)
        glBindVertexArray(0)

    def destroy(self):
        self._chunks = []
        ids = [x for x in (self.vao, self.vbo_p, self.vbo_n, self.vbo_c, self.vbo_id, self.ebo) if x]
        if ids:
            glDeleteVertexArrays(1, [self.vao]) if self.vao else None
            glDeleteBuffers(len(ids) - (1 if self.vao else 0), ids[1:] if self.vao else ids)
        scr = getattr(self, "_scratch_ebo", 0)
        if scr:
            glDeleteBuffers(1, [scr])
            self._scratch_ebo = 0
        self.vao = self.vbo_p = self.vbo_n = self.vbo_c = self.vbo_id = self.ebo = 0


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
        self._sel_mesh = GlMesh()   # selection marker (icosahedron around selected atoms)
        self._vdw_mesh = GlMesh()   # van-der-Waals radius shells (semi-transparent)
        # 选中原子平面填充（苯环等环系半透明涂色，诉求：选 ≥3 原子自动生成；
        # 多个环可并存，每条独立颜色/可删除）
        self._fill_mesh = GlMesh()
        self._fill_items = []      # [{"surf","sel","rgba"}] 每个环一条
        self._fill_surf = None     # 全部条目拼接的合并网格（_upload 用）
        self._fill_rgba = (0.20, 0.55, 1.00, 0.35)   # 新填充的默认色
        self._bond_mesh = GlMesh()  # 化学键独立网格（供"二次上色"重绘 pass 使用）
        self._bond_surf = None
        self._bg = (1.0, 1.0, 1.0, 1.0)

        # Van-der-Waals visualization state
        self._vdw_mode = False      # True: draw atoms at vdW radius (instead of draw radius)
        self._vdw_shell = False     # True: overlay semi-transparent vdW shells on ball-stick
        self._vdw_shell_alpha = 0.2  # shell opacity (0..1)
        # 「仅选中片段」模式：外壳跟随独立的片段原子集合（IGMH 式：
        # 集合持久存在，框选/点选归入，清除画布选中不影响集合）
        self._vdw_sel_atoms = set()
        self._vdw_sel_only = False  # True: 外壳仅画 _vdw_sel_atoms 内的原子
        self._vdw_frag_cbs = []     # 片段集合变化通知: cb(sorted_idx_1based)
        self._vdw_scale = 1.0       # vdW 半径比例（Bondi 表值 × scale，可调）
        # vdW 外壳描边（独立于原子描边，单独控制）
        self._vdw_outline = False
        self._vdw_outline_color = (0.0, 0.0, 0.0)
        self._vdw_outline_width = 0.4

        # Style
        self._sp = style_params([0.1, 0.6, 1.0, 1.0, 0.0, 0.75, 0.0, 0.0, 1.0])
        self._pc = (0.1, 0.8, 0.1)
        self._nc = (0.9, 0.25, 0.25)

        # Init state
        self._gl_ok = False
        self._prog_orb = self._prog_atom = 0
        self._prog_bond = 0   # 二次上色：独立的键着色器程序

        # Depth peeling (IboView prop_FView3d.cpp.inl: DepthPeelingLayers = 4)
        self._dp_layers = int(IBOVIEW_DEFAULTS['DepthPeelingLayers'])
        self._dp_ok = False
        self._prog_orb_dp = self._prog_combine = 0
        self._vao_quad = 0
        self._peel = []

        # 实时接触阴影 / AO（屏幕空间后处理）
        self._ao_ok = False
        self._ao_enabled = True       # 总开关（可被 set_ao_enabled 关闭）
        self._ao_strength = 1.2       # AO 强度
        self._ao_radius_px = 24.0     # 采样半径（像素，世界半径随缩放换算）
        self._ao_bias = 0.0004        # 深度偏置（防自遮蔽）
        self._prog_ssao = 0
        self._ao_scene = None         # 场景 FBO（color+depth）

        # Data state — deferred loading pattern
        self._cube = None
        # 独立分子数据（载入 fchk/xyz 时设置，单位 Bohr），不依赖 cube 文件
        self._molecule = None
        self._pos_surf = None
        self._neg_surf = None
        # 按轨道独立数据（NBO 多轨道叠加用）：[(cube, pos, neg, pc, nc)]，
        # pc/nc 为 0..1 元组；_orbital_flipped 记录各轨道是否已翻转相位
        self._orbital_recs = []
        self._orbital_flipped = []
        # ESP 表面标志：True 表示 _pos_surf 携带 ESP 顶点连续着色（esp_panel
        # 写入）。此时 set_style / set_phase_colors / flip_phase 不得用相位色
        # 平铺 colors，reset_molviewer_style 也不得动 opacity。
        self._surf_vcolor = False
        self._atom_surf = None
        self._sel_surf = None
        self._vdw_surf = None      # vdW 外壳网格（_upload 前必须已初始化，避免空场景 AttributeError）
        self._vdw_balls = []       # 与 vdW 外壳同序的 (cx,cy,cz,r) 列表
        self._sel_marker_shape = "icosahedron"   # 选中标记形状
        self._sel_pulse = 0.0        # 呼吸动画相位
        self._sel_pulse_on = False   # 呼吸动画开关
        self._sel_pulse_timer = None
        self._isovalue = 0.05
        self._needs_upload = False
        self._status_cb = None
        self._atom_pick_cbs = []    # 原子点击回调列表：cb(atom_idx_1based)
        # 键长测量模式：依次点击两个原子，标签显示距离（Å）。标注可拖放/
        # 旋转/调字体颜色（右键点标签），退出模式不清除（clear_measure_items 清）。
        self._measure_mode = False
        self._measure_pair = []     # 当前正在选择的原子（0-based，最多 2 个）
        self._measure_items = []    # 已完成测量 [{"p0","p1","text","offx","offy",
        #                              "rot","pt","family","color"}]，Bohr
        self._mlabel_drag = None    # (idx, grab_dx, grab_dy) 标签拖动状态
        # Shift+左键框选（IGMH 分片段等用）
        self._box_selecting = False
        self._box_start = None
        self._box_current = None
        self._box_cb = None         # cb([atom_idx_1based, ...])
        # Ball-and-stick display scales (user-adjustable via sliders)
        self._atom_scale = 1.68   # atom sphere radius scale (default 1.68)
        self._bond_scale = 2.0   # bond cylinder radius scale (default 2.0)
        self._bond_thinning = BOND_THINNING_DEFAULT  # midpoint narrowing factor (1.0 = no waist)

        # 景深雾化（IboView Fade：远处蒙白雾）开关，默认开启保留原貌
        self._fade_enabled = True
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
        self._vcube_c_rgb = (0.6, 0.6, 0.6)       # Vcube 风格的碳色（vcube 预设指定）
        self._carbon_rgb = None                   # 通用碳色覆盖（任意分子风格，预设 c_color）
        self._hydrogen_rgb = None                 # 通用氢色覆盖（预设 h_color）
        self._light_default_dirs = [               # 当前光照模式的默认灯方向（视图空间）
            (0.5, 0.5, 0.70710678), (-0.4330127, -0.25, 0.8660254),
            (0.4330127, -0.25, 0.8660254), (0.0, 0.0, 1.0)]
        self._light_dirs = [list(d) for d in self._light_default_dirs]  # 当前（含方位/俯仰）
        self._light_az = 0.0                      # 方位角偏移（度，绕视图轴）
        self._light_el = 0.0                      # 俯仰角偏移（度，>0 向上）
        self._light_count = 3                     # 生效光源数（1..4）
        self._light_glow = 1.0                    # 光晕大小（1=默认；>1 更大更散）
        self._light_glows = [1.0, 1.0, 1.0, 1.0]  # 每盏灯独立光晕（u_Glows）
        self._style_name = None                  # last isosurface style name
        # IboView "shiny" preset (overrides a_reg/o_reg after style build)
        self._shininess = SHININESS_DEFAULT

        # ── MolViewer 样式（MolCanvas 预设）扩展 ──
        self._bg_grad = None         # None=纯色；否则 (top, mid, bot) 0..1 三段竖向渐变
        self._bond_color = None      # None=按元素/分子风格；否则 (r,g,b) 0..1 统一键色
        self._atom_labels = 2        # 0=元素符号 1=原子序号 2=关闭
        self._shadows = False        # 每原子软阴影（QPainter 叠加）
        self._crosshair = False      # 原子十字环（GL 球面大圆带）
        # 隐藏氢原子：True=不画 H（保留编号集合中的除外）
        self._hide_hydrogens = False
        self._keep_h_atoms = set()   # 1-based 原子序号集合，隐藏 H 时仍显示
        self._ring_color = (0.05, 0.05, 0.05)   # 圆环颜色（近黑）
        self._ring_width = 0.07      # 环带半宽（法线夹角阈值）
        self._ring_az1 = 90.0        # 环 A 方位角（度）
        self._ring_tilt1 = 71.0      # 环 A 俯仰角（度）
        self._ring_az2 = 205.0       # 环 B 方位角（度）
        self._ring_tilt2 = 0.0       # 环 B 俯仰角（度）
        self._ring_locked = False    # True=锁定：环固定在屏幕系，分子旋转时圆环不转
        self._ring_frozen = None     # 锁定瞬间冻结的视图系环法线（锁定当前角度）
        self._mv_grad = 0            # 0=IboView Phong；>0=MolViewer 径向渐变类型 id
        self._orb_outline = False    # 等值面剪影描边
        self._orb_outline_color = (0.0, 0.0, 0.0)
        self._orb_outline_width = 0.3
        self._prog_bg = 0
        self._vao_bg = 0

        # Interactive atom/bond picking & override system (IboView context-menu)
        self._bond_overrides = {}   # {(i,j): 'solid'|'dashed'|'none'}
        self._selected_atoms = []   # indices of currently selected atoms
        self._drag_start = None     # (x, y) of mouse press for click-vs-drag
        self._was_drag = False      # True if mouse moved enough to be a drag
        # 按原子索引(1-based)覆盖球棍模型颜色（电荷分析等视图用）
        self._atom_color_overrides = {}
        # 按元素(原子序数)覆盖球棍模型颜色（元素原子颜色设置，用户自定义）
        self._element_color_overrides = {}

        # ── ESP 扩展（整合自 ESPViewer） ──
        self._extrema_pts = []       # [(x, y, z, kind)] 世界帧 Bohr；kind=max/min
        self._extrema_radius = 0.25  # 极值点小球半径 (Å)
        self._extrema_vals = []      # 与 _extrema_pts 对齐的数值（显示单位，标签用）
        self._extrema_labels = False # 是否绘制极值点数值标签
        self._extrema_label_font = 9
        self._extrema_label_dist = 12
        self._extrema_label_border = True
        self._esp_point_mode = False  # PT 模式：把等值面顶点渲染成点云
        self._esp_point_size = 3.0
        # ── AIM 拓扑分析覆盖层（临界点 + 梯度路径点云） ──
        # cps:       [(x, y, z, (r,g,b), serial, cp_type), ...] 世界帧 Bohr
        # path_pts:  [(x, y, z), ...] 世界帧 Bohr（灰色小点，不可拾取）
        self._aim_cps = []
        self._aim_path_pts = []
        self._aim_cp_radius = 0.30   # 临界点球半径 (Å)
        self._aim_path_radius = 0.05  # 梯度路径点球半径 (Å)
        self._aim_pick_cb = None     # cb(serial, cp_type)
        # ── VMD 同步场景登记（「同步到 VMD」按钮读取） ──
        # 由各面板在把内容画进画布时登记：surfaces = [
        #   {"type":"orbital","vol":cube,"iso":v} |
        #   {"type":"bgr","vol":geo_cube,"color_vol":map_cube,"iso":v,"cmin":..,"cmax":..} ]
        self._vmd_scene = None
        # 画布内色标条
        self._cs_low = -0.03
        self._cs_high = 0.03
        self._cs_unit = "ESP (a.u.)"
        self._cs_show = False
        self._cs_cmap = None
        self._cs_ticks = 5          # 色标轴刻度段数
        self._cs_orient = "vertical"  # vertical / horizontal
        self._cs_len = 0.55         # 色标条长度（画布高/宽的比例）
        self._cs_geom = None        # (x0, y0, bw, bh, orient) 当前色标条几何
        self._cs_offx = 0           # 拖动水平偏移（相对默认位置，px）
        self._cs_offy = 0           # 拖动垂直偏移
        self._cs_drag_mode = None   # None | "move"
        self._cs_drag_anchor = None # (mx, my, offx, offy)
        self._cs_press_pos = None   # 右键按下位置（区分点击与拖动）
        # 色标条字体（刻度数字 + 单位），右键菜单可改
        self._cs_font_family = "Arial"
        self._cs_font_pt = 10

    def set_status_callback(self, cb):
        self._status_cb = cb

    def set_atom_pick_callback(self, cb):
        """设置原子点击回调（替换为单个）：cb(atom_idx_1based)。"""
        self._atom_pick_cbs = [cb] if cb else []

    def add_atom_pick_callback(self, cb):
        """追加一个原子点击回调：cb(atom_idx_1based)。"""
        if cb:
            self._atom_pick_cbs.append(cb)

    def set_box_select_callback(self, cb):
        """设置框选回调：cb([atom_idx_1based, ...])，Shift+左键拖框选中原子后触发。"""
        self._box_cb = cb

    # ── 键长标注 ────────────────────────────────────────────────
    def set_measure_mode(self, enabled):
        """开/关键长标注模式。开启后依次点击两个原子即测一次键长，
        可连续测多段；退出模式标注保留（可拖放/右键调属性），
        用 clear_measure_items() 清除。"""
        self._measure_mode = bool(enabled)
        self._measure_pair = []
        self._mlabel_drag = None
        self.setCursor(Qt.CrossCursor if self._measure_mode else Qt.ArrowCursor)
        self._status("键长标注：依次点击两个原子（再点两个原子可继续标注下一键）"
                     if self._measure_mode else
                     "已退出键长标注（标注保留：拖动可移位，右键点标签可旋转/"
                     "调字体颜色，「清除」按钮删除标注）")
        self.update()

    def clear_measure_items(self):
        """清除全部键长测量标注（不改变测量模式开关状态）。"""
        self._measure_items = []
        self._measure_pair = []
        self._mlabel_drag = None
        self.update()

    def _measure_click(self, x, y):
        """测量模式下点击：拾取原子，凑满两个即测一次键长。"""
        hit, _ = self._pick_atom(x, y)
        if hit < 0:
            return
        if hit in self._measure_pair:
            return
        atoms = self._atom_list()
        if not atoms or hit >= len(atoms):
            return
        self._measure_pair.append(hit)
        if len(self._measure_pair) < 2:
            self._status(f"标注：已选原子 {hit + 1}，再点击另一个原子")
            self.update()
            return
        i, j = self._measure_pair
        self._measure_pair = []
        p0 = np.asarray(atoms[i][1], dtype=np.float64)
        p1 = np.asarray(atoms[j][1], dtype=np.float64)
        d_ang = float(np.linalg.norm(p1 - p0) * BOHR_TO_ANGSTROM)
        self._measure_items.append({
            "p0": tuple(p0), "p1": tuple(p1),
            "text": f"{d_ang:.2f}",       # 只显示数值，不带单位（论文用）
            "offx": 0.0, "offy": 0.0,     # 相对键中点的屏幕拖放偏移（px）
            "rot": 0.0,                   # 标签旋转角度（度，顺时针）
            "pt": 10,                     # 字号
            "family": "Arial",            # 论文常用字体
            "color": (0, 0, 0),           # 黑色文字
        })
        self._status(f"键长 {i + 1}-{j + 1} = {d_ang:.2f}"
                     f"（标签可拖动；右键点标签旋转/调字体颜色）")
        self.update()

    def _measure_label_rect(self, it, w0=None, h0=None):
        """标签屏幕几何：返回 ((cx, cy, visible), (tw, th))（未旋转包围盒，
        cx/cy 已含拖放偏移）。"""
        if w0 is None or h0 is None:
            w0, h0 = max(1, self.width()), max(1, self.height())
        mx = (it["p0"][0] + it["p1"][0]) / 2.0
        my = (it["p0"][1] + it["p1"][1]) / 2.0
        mz = (it["p0"][2] + it["p1"][2]) / 2.0
        sx, sy, vis = self._world_to_screen(mx, my, mz, w0, h0)
        f = QFont(it["family"]) if it["family"] else QFont()
        f.setPointSize(max(4, it["pt"]))
        f.setBold(True)
        fm = QFontMetrics(f)
        tw = fm.horizontalAdvance(it["text"]) + 10
        th = fm.height() + 4
        return (sx + it["offx"], sy + it["offy"], vis), (tw, th)

    def _hit_measure_label(self, x, y):
        """返回命中的测量标签索引（最上层优先），未命中返回 None。"""
        for i in range(len(self._measure_items) - 1, -1, -1):
            (cx, cy, vis), (tw, th) = self._measure_label_rect(
                self._measure_items[i])
            if vis and (abs(x - cx) <= tw / 2 + 3
                        and abs(y - cy) <= th / 2 + 3):
                return i
        return None

    @staticmethod
    def _localize_dialog_buttons(dlg):
        """把对话框里的 OK/Cancel 等标准按钮改成中文。"""
        from PyQt5.QtWidgets import QPushButton
        names = {"OK": "确定", "Cancel": "取消", "Close": "关闭",
                 "Open": "打开", "Save": "保存", "Yes": "是", "No": "否",
                 "Pick Screen Color": "屏幕取色",
                 "Add to Custom Colors": "添加到自定义颜色"}
        for b in dlg.findChildren(QPushButton):
            t = b.text().replace("&", "")
            if t in names:
                b.setText(names[t])

    def _measure_label_menu(self, idx, global_pos):
        """右键测量标签：旋转 / 字号 / Arial / 字体 / 颜色 / 删除。"""
        from PyQt5.QtWidgets import QMenu, QFontDialog, QColorDialog
        it = self._measure_items[idx]
        menu = QMenu(self)
        menu.setStyleSheet(_QMENU_QSS)   # 白底黑字，与画布右键菜单一致
        act_rplus = menu.addAction("旋转 +15°")
        act_rminus = menu.addAction("旋转 -15°")
        act_rreset = menu.addAction("复位旋转")
        menu.addSeparator()
        act_bigger = menu.addAction("字号 +1")
        act_smaller = menu.addAction("字号 -1")
        act_arial = menu.addAction("论文字体 (Arial)")
        act_font = menu.addAction("字体…")
        act_color = menu.addAction("颜色…")
        menu.addSeparator()
        act_del = menu.addAction("删除此测量")
        act_clear = menu.addAction("清除全部测量")
        act = menu.exec_(global_pos)
        if act is None:
            return
        if act is act_rplus:
            it["rot"] = (it["rot"] + 15.0) % 360.0
        elif act is act_rminus:
            it["rot"] = (it["rot"] - 15.0) % 360.0
        elif act is act_rreset:
            it["rot"] = 0.0
        elif act is act_bigger:
            it["pt"] = min(48, it["pt"] + 1)
        elif act is act_smaller:
            it["pt"] = max(6, it["pt"] - 1)
        elif act is act_arial:
            it["family"] = "Arial"
        elif act is act_font:
            f0 = QFont(it["family"]) if it["family"] else QFont()
            f0.setPointSize(it["pt"])
            # 非原生 Qt 对话框：可加白底黑字样式 + 按钮中文化
            dlg = QFontDialog(self)
            dlg.setWindowTitle("测量标签字体")
            dlg.setCurrentFont(f0)
            dlg.setOption(QFontDialog.DontUseNativeDialog)
            dlg.setStyleSheet(_QDIALOG_QSS)
            self._localize_dialog_buttons(dlg)
            if dlg.exec_():
                f = dlg.selectedFont()
                it["family"] = f.family()
                it["pt"] = f.pointSize() or it["pt"]
        elif act is act_color:
            # 非原生颜色对话框（原生对话框不受 QSS 控制）
            dlg = QColorDialog(QColor(*it["color"]), self)
            dlg.setWindowTitle("测量标签颜色")
            dlg.setOption(QColorDialog.DontUseNativeDialog)
            dlg.setStyleSheet(_QDIALOG_QSS)
            self._localize_dialog_buttons(dlg)
            if dlg.exec_():
                c = dlg.selectedColor()
                if c.isValid():
                    it["color"] = (c.red(), c.green(), c.blue())
        elif act is act_del:
            del self._measure_items[idx]
        elif act is act_clear:
            self._measure_items = []
        self.update()

    def _draw_measure_labels(self):
        """键长测量标注：不画连线，标签 = 投影键中点 + 拖放偏移，
        支持每条独立的旋转/字号/字体/颜色。"""
        if not self._measure_items and not self._measure_pair:
            return
        w0, h0 = max(1, self.width()), max(1, self.height())
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing)
            p.setRenderHint(QPainter.TextAntialiasing)
            # 正在选择的原子：青色圆圈标记
            atoms = self._atom_list()
            for idx in self._measure_pair:
                if idx >= len(atoms):
                    continue
                ax, ay, az = atoms[idx][1]
                sx, sy, vis = self._world_to_screen(ax, ay, az, w0, h0)
                if not vis:
                    continue
                p.setPen(QPen(QColor(0, 190, 255), 2))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QPointF(sx, sy), 9.0, 9.0)
            # 已完成测量：仅标签（无连线）
            for it in self._measure_items:
                (cx, cy, vis), (tw, th) = self._measure_label_rect(it, w0, h0)
                if not vis:
                    continue
                f = QFont(it["family"]) if it["family"] else QFont()
                f.setPointSize(max(4, it["pt"]))
                f.setBold(True)
                p.setFont(f)
                p.save()
                p.translate(cx, cy)
                p.rotate(it["rot"])
                rect = QRectF(-tw / 2.0, -th / 2.0, tw, th)
                # 无边框：只画半透明白底圆角衬底，保证可读
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(255, 255, 255, 215))
                p.drawRoundedRect(rect, 4, 4)
                p.setPen(QColor(*it["color"]))
                p.drawText(rect, Qt.AlignCenter, it["text"])
                p.restore()
        finally:
            p.end()

    # ── VMD 同步场景登记 ───────────────────────────────────────
    def set_vmd_scene(self, surfaces):
        """登记当前画布场景，供主窗口「同步到 VMD」按钮读取。

        surfaces: [dict, ...] 或 None（清除登记）。
          {"type":"orbital", "vol": cube 路径, "iso": 等值面值}
          {"type":"bgr",     "vol": 几何 cube 路径, "color_vol": 着色 cube 路径,
                             "iso": 等值面值, "cmin": 色标下限, "cmax": 色标上限}
        """
        if surfaces:
            self._vmd_scene = {"surfaces": list(surfaces)}
        else:
            self._vmd_scene = None

    def vmd_scene(self):
        return self._vmd_scene

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
            # 载入 cube 即丢弃上一场景的 AIM 覆盖层（避免跨 tab 残留）
            self._aim_cps = []
            self._aim_path_pts = []

            self._status("提取等值面...")
            self._pos_surf = marching_cubes(cube, isovalue, False)
            self._neg_surf = marching_cubes(cube, -isovalue, True)

            # Colors
            pc = np.array([*self._pc, 1.0], dtype=np.float32)
            nc = np.array([*self._nc, 1.0], dtype=np.float32)
            self._pos_surf.colors = np.tile(pc, (self._pos_surf.vertex_count, 1))
            self._neg_surf.colors = np.tile(nc, (self._neg_surf.vertex_count, 1))
            self._surf_vcolor = False   # 相位色平铺表面，非 ESP 顶点色
            # 记录单轨道数据（支持按轨道翻转相位）
            self._orbital_recs = [(cube, self._pos_surf, self._neg_surf,
                                   tuple(float(c) for c in self._pc),
                                   tuple(float(c) for c in self._nc))]
            self._orbital_flipped = [False]

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

    def load_orbitals(self, cube_paths, isovalue=0.05, color_pairs=None):
        """同时加载多个轨道 cube 并叠加显示（供 NBO E(2) 双轨道用）。

        color_pairs: [(pos_rgb, neg_rgb), ...]，每项为 0-255 元组，与
        cube_paths 一一对应；None / 不足时按轨道序号自动分配色相。
        每个轨道各自的等值面顶点带各自颜色，合并成单张 pos/neg 网格渲染。
        """
        if not _HAS_GL or not cube_paths:
            return False
        try:
            recs = []
            for i, path in enumerate(cube_paths):
                if not os.path.exists(path):
                    continue
                cube = read_cube(path)
                pos = marching_cubes(cube, isovalue, False)
                neg = marching_cubes(cube, -isovalue, True)
                if color_pairs and i < len(color_pairs) and color_pairs[i]:
                    pc = tuple(float(c) / 255.0 for c in color_pairs[i][0])
                    nc = tuple(float(c) / 255.0 for c in color_pairs[i][1])
                else:
                    pc = self._auto_orbital_color(i, True)
                    nc = self._auto_orbital_color(i, False)
                recs.append((cube, pos, neg, pc, nc))

            if not recs:
                return False

            pos_chunks, neg_chunks = [], []
            for cube, pos, neg, pc, nc in recs:
                pa = np.array([*pc, 1.0], dtype=np.float32)
                na = np.array([*nc, 1.0], dtype=np.float32)
                if pos.vertex_count > 0:
                    pos.colors = np.tile(pa, (pos.vertex_count, 1))
                    pos_chunks.append(pos)
                if neg.vertex_count > 0:
                    neg.colors = np.tile(na, (neg.vertex_count, 1))
                    neg_chunks.append(neg)

            self._pos_surf = merge_iso_surfaces(pos_chunks)
            self._neg_surf = merge_iso_surfaces(neg_chunks)
            self._cube = recs[0][0]
            self._isovalue = isovalue
            self._pc, self._nc = recs[0][3], recs[0][4]
            self._surf_vcolor = False   # 相位色平铺表面，非 ESP 顶点色
            # 保留每轨道独立数据（支持按轨道翻转相位）
            self._orbital_recs = recs
            self._orbital_flipped = [False] * len(recs)

            ctr, r = compute_bounding_sphere(self._cube)
            self._scene_r = r
            self.cam.set_center_zoom(ctr, r)
            self._gen_atoms()
            self._needs_upload = True
            self._status(f"就绪: {len(recs)} 个轨道叠加")
            self.update()
            return True
        except Exception as e:
            self._status(f"加载失败: {e}")
            traceback.print_exc()
            return False

    @staticmethod
    def _auto_orbital_color(idx, positive=True):
        """多轨道叠加时按序号分配可区分色相。"""
        palette = [
            ((0.85, 0.20, 0.20), (0.20, 0.45, 0.95)),   # 红 / 蓝
            ((0.20, 0.75, 0.30), (0.95, 0.55, 0.15)),   # 绿 / 橙
            ((0.75, 0.20, 0.85), (0.95, 0.82, 0.20)),   # 紫 / 黄
            ((0.15, 0.80, 0.85), (0.95, 0.30, 0.55)),   # 青 / 粉
        ]
        pos, neg = palette[idx % len(palette)]
        return pos if positive else neg

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
            self._surf_vcolor = False   # 重算表面即相位色，非 ESP 顶点色
            self._needs_upload = True
            self.update()
        except Exception as e:
            self._status(f"等值面更新失败: {e}")

    def set_style(self, name):
        s = STYLES.get(name)
        if not s:
            return
        self._style_name = name
        sm = s.get('surface_mat')
        if sm:
            # ESP 顶点色表面在场时：样式材质照常替换，但不透明度保留
            # 用户在 ESP 面板设置的值（不跟样式 surface_mat 走）
            keep_op = (self._sp.get('opacity')
                       if self._surf_vcolor else None)
            self._sp = style_params(sm, s)
            if keep_op is not None:
                self._sp['opacity'] = keep_op
        pc = style_rgb(s.get('pos_color', []))
        nc = style_rgb(s.get('neg_color', []))
        if pc:
            self._pc = pc
        if nc:
            self._nc = nc
        # _surf_vcolor（ESP 表面）的 colors 是顶点连续着色，
        # 不能被相位单色平铺覆盖
        if self._pos_surf and pc and not self._surf_vcolor:
            c = np.array([*pc, 1.0], dtype=np.float32)
            self._pos_surf.colors = np.tile(c, (self._pos_surf.vertex_count, 1))
        if self._neg_surf and nc and not self._surf_vcolor:
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
        if (self._pos_surf is not None and pos_rgb is not None
                and not self._surf_vcolor):
            c = np.array([*self._pc, 1.0], dtype=np.float32)
            self._pos_surf.colors = np.tile(c, (self._pos_surf.vertex_count, 1))
        if (self._neg_surf is not None and neg_rgb is not None
                and not self._surf_vcolor):
            c = np.array([*self._nc, 1.0], dtype=np.float32)
            self._neg_surf.colors = np.tile(c, (self._neg_surf.vertex_count, 1))
        self._needs_upload = True
        self.update()

    def flip_phase(self):
        """翻转相位：交换正/负相位颜色（等价 IboView chkBox_FlipPhase 的
        std::swap(cIsoMinus, cIsoPlus)）。多轨道（_orbital_recs）时等价于
        翻转全部；单轨道时直接作用于当前配色。几何不变，延迟上传。"""
        if getattr(self, "_orbital_recs", None):
            self.flip_all_orbitals()
            return
        self._pc, self._nc = self._nc, self._pc
        if self._pos_surf is not None and not self._surf_vcolor:
            c = np.array([*self._pc, 1.0], dtype=np.float32)
            self._pos_surf.colors = np.tile(c, (self._pos_surf.vertex_count, 1))
        if self._neg_surf is not None and not self._surf_vcolor:
            c = np.array([*self._nc, 1.0], dtype=np.float32)
            self._neg_surf.colors = np.tile(c, (self._neg_surf.vertex_count, 1))
        self._needs_upload = True
        self.update()

    def _rebuild_orbital_meshes(self):
        """按各轨道当前翻转状态重建合并的 pos/neg 表面网格（画布）。"""
        recs = getattr(self, "_orbital_recs", None) or []
        if not recs:
            return
        flips = getattr(self, "_orbital_flipped", []) or []
        pos_chunks, neg_chunks = [], []
        for i, (cube, pos, neg, pc, nc) in enumerate(recs):
            flipped = bool(flips[i]) if i < len(flips) else False
            pcol = (nc if flipped else pc)
            ncol = (pc if flipped else nc)
            pa = np.array([*pcol, 1.0], dtype=np.float32)
            na = np.array([*ncol, 1.0], dtype=np.float32)
            if pos is not None and pos.vertex_count > 0:
                pos.colors = np.tile(pa, (pos.vertex_count, 1))
                pos_chunks.append(pos)
            if neg is not None and neg.vertex_count > 0:
                neg.colors = np.tile(na, (neg.vertex_count, 1))
                neg_chunks.append(neg)
        if pos_chunks:
            self._pos_surf = merge_iso_surfaces(pos_chunks)
        if neg_chunks:
            self._neg_surf = merge_iso_surfaces(neg_chunks)
        # 基准相位色（未翻转时的正/负色）保持第一个轨道
        self._pc = recs[0][3]
        self._nc = recs[0][4]
        self._needs_upload = True
        self.update()

    def flip_orbital(self, i):
        """翻转画布上第 i 个轨道的相位（按轨道独立，其它轨道不受影响）。"""
        recs = getattr(self, "_orbital_recs", None) or []
        if not recs or not (0 <= i < len(recs)):
            return False
        flips = self._orbital_flipped
        while len(flips) <= i:
            flips.append(False)
        flips[i] = not flips[i]
        self._rebuild_orbital_meshes()
        return True

    def flip_all_orbitals(self):
        """翻转画布上全部轨道的相位。"""
        recs = getattr(self, "_orbital_recs", None) or []
        if not recs:
            return False
        self._orbital_flipped = [
            not (self._orbital_flipped[i] if i < len(self._orbital_flipped) else False)
            for i in range(len(recs))]
        self._rebuild_orbital_meshes()
        return True

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
            s = STYLES.get(self._style_name)
            if isinstance(s, dict):
                rgb = s.get('c_rgb')
                if rgb:
                    try:
                        self._mol_single_rgb = tuple(float(x) for x in rgb.split())
                    except Exception:
                        pass
        if self._molecule is not None or self._cube is not None:
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
        self._bg_grad = None
        self.update()

    def set_background_gradient(self, top, mid, bot):
        """三段竖向背景渐变（MolViewer 风格）。每个参数为 0..1 的 (r,g,b)。"""
        t = tuple(float(x) for x in top[:3])
        m = tuple(float(x) for x in mid[:3])
        b = tuple(float(x) for x in bot[:3])
        self._bg_grad = (t, m, b)
        self._bg = (m[0], m[1], m[2], 1.0)   # glClear 底色取中段
        self.update()

    def set_bond_color(self, color):
        """统一键色。color 为 hex 字符串或 0..1 (r,g,b) 元组；None 回退按元素配色。"""
        if color is None:
            self._bond_color = None
        elif isinstance(color, str):
            h = color.lstrip("#")
            if len(h) == 6:
                self._bond_color = (int(h[0:2], 16) / 255.0,
                                    int(h[2:4], 16) / 255.0,
                                    int(h[4:6], 16) / 255.0)
        else:
            self._bond_color = tuple(float(x) for x in color[:3])
        if self._molecule is not None or self._cube is not None:
            self._gen_atoms()
            self._needs_upload = True
        self.update()

    def set_atom_labels(self, mode):
        """原子标签：0=元素符号、1=原子序号、2=关闭。"""
        self._atom_labels = 0 if mode == 0 else (1 if mode == 1 else 2)
        self.update()

    def set_hide_hydrogens(self, on, keep=None):
        """隐藏氢原子（除保留编号外）。

        on   : True=隐藏 H（球体/键/标签均不显示）
        keep : 可选，1-based 原子序号的可迭代集合；这些 H 仍显示。
               传 None 表示用当前的保留集合。
        """
        self._hide_hydrogens = bool(on)
        if keep is not None:
            self._keep_h_atoms = set(int(x) for x in keep if int(x) > 0)
        if self._molecule is not None or self._cube is not None:
            self._gen_atoms()
            self._needs_upload = True
        self.update()

    def _hydrogen_visible(self, idx_1based, anum):
        """原子序号 idx_1based（1-based）的原子是否应显示。"""
        if anum == 1 and self._hide_hydrogens:
            return idx_1based in self._keep_h_atoms
        return True

    def set_shadows(self, on):
        """每原子软阴影（MolViewer 风格偏移椭圆，QPainter 叠加）。"""
        self._shadows = bool(on)
        self.update()

    def set_crosshair(self, on):
        """原子十字环（两条大圆带，GL 着色器直接在球面上绘制）。"""
        self._crosshair = bool(on)
        self.update()

    def set_ring_style(self, color=None, width=None):
        """圆环颜色（0..1 元组）与环带半宽（0.02~0.2）。"""
        if color is not None:
            self._ring_color = tuple(float(x) for x in color[:3])
        if width is not None:
            self._ring_width = max(0.02, min(0.2, float(width)))
        self.update()

    def set_ring_orientation(self, az1=None, tilt1=None, az2=None, tilt2=None, locked=None):
        """设置两条圆环的方位角/俯仰角（度）与锁定状态。

        locked=True：把**当前**视图系环方向冻结（锁定当前角度），此后分子怎么
        旋转圆环都不再改变；locked=False：圆环随分子旋转（世界系固定）。
        """
        if az1 is not None:
            self._ring_az1 = float(az1) % 360.0
        if tilt1 is not None:
            self._ring_tilt1 = max(0.0, min(90.0, float(tilt1)))
        if az2 is not None:
            self._ring_az2 = float(az2) % 360.0
        if tilt2 is not None:
            self._ring_tilt2 = max(0.0, min(90.0, float(tilt2)))
        if locked is not None:
            self._ring_locked = bool(locked)
        self._refresh_ring_frozen()
        self.update()

    def _refresh_ring_frozen(self):
        """锁定时把当前视图系的环法线冻结（即锁定当前角度）；解锁时清除。"""
        if self._ring_locked:
            R = self.cam.view()[:3, :3]
            nA = _ring_normal(self._ring_az1, self._ring_tilt1)
            nB = _ring_normal(self._ring_az2, self._ring_tilt2)
            self._ring_frozen = (R @ nA, R @ nB)
        else:
            self._ring_frozen = None

    def get_ring_state(self):
        """导出十字圆环设置（JSON 可序列化）。"""
        return {
            "on": self._crosshair,
            "az1": self._ring_az1,
            "tilt1": self._ring_tilt1,
            "az2": self._ring_az2,
            "tilt2": self._ring_tilt2,
            "locked": self._ring_locked,
            "width": self._ring_width,
            "color": list(self._ring_color),
        }

    def apply_ring_state(self, st):
        """应用十字圆环设置（与 RingControlDialog 的保存/载入一致）。"""
        if not isinstance(st, dict):
            return
        self.set_crosshair(bool(st.get("on", self._crosshair)))
        self.set_ring_orientation(
            az1=st.get("az1"), tilt1=st.get("tilt1"),
            az2=st.get("az2"), tilt2=st.get("tilt2"),
            locked=st.get("locked"))
        self.set_ring_style(color=st.get("color"), width=st.get("width"))

    def set_mv_gradient(self, name):
        """设置 MolViewer 球体径向渐变类型（如 'full'/'glass_plus'/'flat'）。

        name 为空或 None → 回退 IboView 三灯 Phong（u_MvGrad=0）。
        同时按模式设定默认灯方向与数量（单光/双光/四光/三光）。
        """
        if not name:
            self._mv_grad = 0
            self._light_default_dirs = [
                (0.5, 0.5, 0.70710678), (-0.4330127, -0.25, 0.8660254),
                (0.4330127, -0.25, 0.8660254), (0.0, 0.0, 1.0)]
            self._light_count = 3
        else:
            self._mv_grad = _MV_GRAD_IDS.get(name, 0)
            if name == "two_light":
                self._light_default_dirs = [
                    (-0.30, 0.30, 0.90), (0.30, -0.30, 0.90),
                    (0.0, 0.0, 1.0), (0.0, 0.0, 1.0)]
                self._light_count = 2
            elif name == "four_light":
                self._light_default_dirs = [
                    (-0.30, 0.30, 0.90), (0.30, -0.30, 0.90),
                    (-0.60, 0.00, 0.80), (0.60, 0.00, 0.80)]
                self._light_count = 4
            else:  # 单光
                self._light_default_dirs = [
                    (-0.577, 0.577, 0.577), (0.0, 0.0, 1.0),
                    (0.0, 0.0, 1.0), (0.0, 0.0, 1.0)]
                self._light_count = 1
        self._light_az = 0.0
        self._light_el = 0.0
        self._recompute_lights()
        self.update()

    def set_orb_outline(self, on, color=None, width=None):
        """等值面剪影描边。color 为 0..1 (r,g,b)；width 为 0..1 剪影带厚度。"""
        self._orb_outline = bool(on)
        if color is not None:
            self._orb_outline_color = tuple(float(x) for x in color[:3])
        if width is not None:
            self._orb_outline_width = max(0.01, min(0.99, float(width)))
        self.update()

    def set_vcube_carbon(self, rgb):
        """设置 Vcube 分子风格的碳原子颜色（0..1 元组）。"""
        self._vcube_c_rgb = tuple(float(x) for x in rgb[:3])
        if self._molecule is not None or self._cube is not None:
            self._gen_atoms()
            self._needs_upload = True
        self.update()

    def set_carbon_color(self, rgb):
        """通用碳色覆盖（0..1 元组；None 清除，回到分子风格默认碳色）。"""
        if rgb is None:
            self._carbon_rgb = None
        else:
            self._carbon_rgb = tuple(float(x) for x in rgb[:3])
        if self._molecule is not None or self._cube is not None:
            self._gen_atoms()
            self._needs_upload = True
        self.update()

    def set_hydrogen_color(self, rgb):
        """通用氢色覆盖（0..1 元组；None 清除，回到分子风格默认氢色）。"""
        if rgb is None:
            self._hydrogen_rgb = None
        else:
            self._hydrogen_rgb = tuple(float(x) for x in rgb[:3])
        if self._molecule is not None or self._cube is not None:
            self._gen_atoms()
            self._needs_upload = True
        self.update()

    def set_surface_material(self, ambient=None, spec_mul=None):
        """设置等值面材质（vcube/VMD 材质的近似映射）。

        ambient:  自发光/环境项（VMD ambient，0..1+）
        spec_mul: 高光强度倍率（VMD specular，0..1+）
        """
        if ambient is not None:
            self._sp['ambient'] = max(0.0, float(ambient))
        if spec_mul is not None:
            self._sp['spec_mul'] = max(0.0, float(spec_mul))
        self.update()

    def set_light_dirs(self, dirs):
        """自定义光源方向（视图空间方向，3 个 (x,y,z)，用于 IboView 三光等）。

        同时记录为当前模式的默认方向并清零方位/俯仰偏移；None 保持不变。
        """
        if dirs is None:
            return
        self._light_default_dirs = [tuple(float(x) for x in d[:3]) for d in dirs[:3]]
        while len(self._light_default_dirs) < 4:
            self._light_default_dirs.append((0.0, 0.0, 1.0))
        self._light_count = 3
        self._light_az = 0.0
        self._light_el = 0.0
        self._recompute_lights()

    def adjust_light_azimuth(self, deg):
        """手动微调：所有灯绕视图轴整体旋转（方位角，度）。"""
        self._light_az = float(deg)
        self._recompute_lights()

    def adjust_light_elevation(self, deg):
        """手动微调：所有灯整体俯仰（度，>0 灯光上倾）。"""
        self._light_el = float(deg)
        self._recompute_lights()

    def set_light_count(self, n):
        """设置生效光源数量（1..4）。"""
        self._light_count = max(1, min(4, int(n)))
        self.update()

    def set_light_dir(self, i, dir):
        """手动摆放第 i 盏灯的方向（视图空间单位方向）。

        同时写入该模式的默认方向并清零方位/俯仰（手动摆放优先于整体旋转）。
        """
        i = max(0, min(3, int(i)))
        d = tuple(float(x) for x in dir[:3])
        while len(self._light_default_dirs) < 4:
            self._light_default_dirs.append((0.0, 0.0, 1.0))
        self._light_default_dirs[i] = d
        self._light_dirs = [list(x) for x in self._light_default_dirs]
        self._light_az = 0.0
        self._light_el = 0.0
        self.update()

    def set_light_glow(self, g):
        """设置光晕大小（0.1..3.0；1.0=默认），同时作用于全部灯。"""
        g = max(0.1, min(3.0, float(g)))
        self._light_glow = g
        self._light_glows = [g] * 4
        self.update()

    def set_light_glow_i(self, i, g):
        """单独设置第 i 盏灯的光晕大小（0.1..3.0；1.0=默认）。

        同时把整体值 _light_glow 同步为刚编辑的这盏灯的值，避免保存样式时
        light_glow 字段携带过期值（与每灯光晕矛盾）。
        """
        i = max(0, min(3, int(i)))
        g = max(0.1, min(3.0, float(g)))
        while len(self._light_glows) < 4:
            self._light_glows.append(self._light_glow)
        self._light_glows[i] = g
        self._light_glow = g
        self.update()

    def reset_light_adjust(self):
        """清除方位/俯仰偏移，回到当前模式的默认灯方向。"""
        self._light_az = 0.0
        self._light_el = 0.0
        self._recompute_lights()

    def reset_light_config(self):
        """光源全部复位：数量/光晕/方位/俯仰回到当前光照模式的默认。"""
        if self._mv_grad == 14:
            self._light_count = 2
        elif self._mv_grad == 15:
            self._light_count = 4
        elif self._mv_grad == 0:
            self._light_count = 3
        else:
            self._light_count = 1
        self._light_glow = 1.0
        self._light_glows = [1.0, 1.0, 1.0, 1.0]
        self._light_az = 0.0
        self._light_el = 0.0
        self._recompute_lights()

    def _recompute_lights(self):
        """由默认灯方向 + 方位/俯仰偏移算出当前生效方向（4 盏）。"""
        az = math.radians(self._light_az)
        el = math.radians(self._light_el)
        ca, sa = math.cos(az), math.sin(az)
        ce, se = math.cos(el), math.sin(el)
        out = []
        for (x, y, z) in self._light_default_dirs:
            # 方位：绕视图轴（z）旋转
            xr = x * ca - y * sa
            yr = x * sa + y * ca
            # 俯仰：绕 x 轴旋转（>0 向上）
            y2 = yr * ce + z * se
            z2 = -yr * se + z * ce
            out.append((xr, y2, z2))
        self._light_dirs = out
        self.update()

    def reset_molviewer_style(self):
        """清除 MolViewer 预设效果，恢复默认 IboView 球棍观感。

        不触碰等值面风格（STYLE_NAMES）与相位配色。
        """
        self._mv_grad = 0
        self._bg_grad = None
        self._bg = (1.0, 1.0, 1.0, 1.0)
        self._bond_color = None
        self.set_mol_style("CPK")
        self.set_shininess(SHININESS_DEFAULT)
        self.set_atom_scale(1.68)
        self.set_bond_scale(2.0)
        self.set_atom_outline(False)
        self.set_shadows(False)
        self.set_crosshair(False)
        self.set_ring_style((0.05, 0.05, 0.05), 0.07)
        self.set_ring_orientation(90, 71, 205, 0, locked=False)
        self.set_atom_labels(2)
        self.set_orb_outline(False)
        self.set_fade_enabled(True)
        # 等值面不透明度回到默认（ESP 顶点色表面除外：不透明度归 ESP 面板管）
        if not self._surf_vcolor:
            self._sp['opacity'] = float(IBOVIEW_DEFAULTS.get('OrbitalOpacity', 1.0))
        # 灯光复位：数量 3、光晕 1、方位/俯仰归零、恢复默认三光方向
        self._light_count = 3
        self._light_glow = 1.0
        self._light_glows = [1.0, 1.0, 1.0, 1.0]
        self._light_az = 0.0
        self._light_el = 0.0
        self.set_mv_gradient("")
        self.set_carbon_color(None)
        self.set_hydrogen_color(None)
        self.update()

    def apply_molviewer_preset(self, name):
        """应用一个 MolViewer（MolCanvas）样式预设；见 _molviewer_style.py。"""
        from ._molviewer_style import apply_molviewer_preset as _apply
        return _apply(self, name)

    # ── 样式保存/载入 ──
    def _mv_grad_name(self):
        """当前 u_MvGrad → 渐变类型名（"" = IboView 三光）。"""
        return _MV_GRAD_BY_ID.get(self._mv_grad, "")

    def get_style_state(self):
        """导出当前样式状态（JSON 可序列化），供「保存样式」使用。"""
        return {
            "mol_style": self._mol_style,
            "gradient": self._mv_grad_name(),
            "shininess": self._shininess,
            "light_count": self._light_count,
            "light_dirs": [list(d) for d in self._light_dirs],
            "light_glow": self._light_glow,
            "light_glows": list(self._light_glows),
            "atom_scale": self._atom_scale,
            "bond_scale": self._bond_scale,
            "atom_outline": [self._atom_outline,
                             list(self._atom_outline_color),
                             self._atom_outline_width],
            "orb_outline": [self._orb_outline,
                            list(self._orb_outline_color),
                            self._orb_outline_width],
            "orb_opacity": self._sp.get('opacity', 1.0),
            "phase_pos": list(self._pc),
            "phase_neg": list(self._nc),
            "bg": list(self._bg),
            "crosshair": self._crosshair,
            "fade": self._fade_enabled,
            "depth_peeling": self._dp_layers > 0,
            "carbon": list(self._carbon_rgb) if self._carbon_rgb else None,
            "hydrogen": list(self._hydrogen_rgb) if self._hydrogen_rgb else None,
            "hide_hydrogens": self._hide_hydrogens,
            "keep_h_atoms": sorted(self._keep_h_atoms),
            "atom_labels": self._atom_labels,
        }

    def apply_style_state(self, st):
        """应用导出的样式状态（「载入样式」）。"""
        if not isinstance(st, dict):
            return
        ms = st.get("mol_style")
        if ms in MOL_STYLE_NAMES:
            self.set_mol_style(ms)
        self.set_mv_gradient(st.get("gradient", ""))
        # 灯光（渐变已重置默认，这里覆盖为保存值）
        if "light_count" in st:
            self._light_count = max(1, min(4, int(st["light_count"])))
        if st.get("light_dirs"):
            self._light_default_dirs = [tuple(float(x) for x in d[:3])
                                        for d in st["light_dirs"][:4]]
            while len(self._light_default_dirs) < 4:
                self._light_default_dirs.append((0.0, 0.0, 1.0))
            self._light_dirs = [list(x) for x in self._light_default_dirs]
            # 与 set_mv_gradient / LightControlDialog._load 一致：方向整体
            # 替换后清掉旧偏移，避免残留方位/俯仰在微调时突然叠加生效
            self._light_az = 0.0
            self._light_el = 0.0
        if "light_glow" in st:
            self._light_glow = max(0.1, min(3.0, float(st["light_glow"])))
        if st.get("light_glows"):
            glows = [max(0.1, min(3.0, float(x))) for x in st["light_glows"][:4]]
            while len(glows) < 4:
                glows.append(self._light_glow)
            self._light_glows = glows
        elif "light_glow" in st:
            # 旧格式（仅 light_glow）：整体值应用到全部灯
            self._light_glows = [self._light_glow] * 4
        if st.get("shininess") in SHININESS_PRESETS:
            self.set_shininess(st["shininess"])
        if "atom_scale" in st:
            self.set_atom_scale(st["atom_scale"])
        if "bond_scale" in st:
            self.set_bond_scale(st["bond_scale"])
        if st.get("atom_outline"):
            on, col, w = st["atom_outline"]
            self.set_atom_outline(bool(on), tuple(float(x) for x in col), float(w))
        if st.get("orb_outline"):
            on, col, w = st["orb_outline"]
            self.set_orb_outline(bool(on), tuple(float(x) for x in col), float(w))
        if "orb_opacity" in st:
            self.set_opacity(max(0.0, min(1.0, float(st["orb_opacity"]))))
        if st.get("phase_pos") and st.get("phase_neg"):
            self.set_phase_colors(
                pos_rgb=tuple(int(c * 255) for c in st["phase_pos"]),
                neg_rgb=tuple(int(c * 255) for c in st["phase_neg"]))
        if st.get("bg"):
            self._bg = tuple(float(x) for x in st["bg"][:4])
            self._bg_grad = None
        if "crosshair" in st:
            self._crosshair = bool(st["crosshair"])
        if "fade" in st:
            self._fade_enabled = bool(st["fade"])
        if "depth_peeling" in st:
            self.set_depth_peeling(bool(st["depth_peeling"]))
        if "carbon" in st:
            self.set_carbon_color(tuple(float(x) for x in st["carbon"])
                                  if st["carbon"] else None)
        if "hydrogen" in st:
            self.set_hydrogen_color(tuple(float(x) for x in st["hydrogen"])
                                    if st["hydrogen"] else None)
        if "hide_hydrogens" in st:
            keep = st.get("keep_h_atoms") or []
            self.set_hide_hydrogens(bool(st["hide_hydrogens"]),
                                    [int(x) for x in keep])
        if "atom_labels" in st:
            self.set_atom_labels(int(st["atom_labels"]))
        self._needs_upload = True
        self.update()

    def set_depth_peeling(self, on, layers=None):
        """Enable/disable depth peeling; disabling uses the sorted fallback.

        layers: 手动指定剥离层数（1..8，越界自动钳制）；None 用默认（4）。
        层数越多，复杂轨道的深处显示越完整，代价是每层多一遍渲染。
        """
        n = int(layers) if layers else int(IBOVIEW_DEFAULTS['DepthPeelingLayers'])
        n = max(1, min(8, n))
        self._dp_layers = n if on else 0
        self.update()

    def set_fade_enabled(self, enabled):
        """景深雾化（IboView Fade：远处蒙白雾）开关。默认开启以保留 IboView 原貌。"""
        self._fade_enabled = bool(enabled)
        self.update()

    def reset_view(self):
        self.cam.reset()
        if self._cube:
            ctr, r = compute_bounding_sphere(self._cube)
            self.cam.set_center_zoom(ctr, r)
        self.update()

    def frame_to_molecule(self):
        """把相机对准当前球棍模型（分子），使整个分子居中并铺满视野。"""
        if self._molecule is not None:
            pts = np.array([[m[2], m[3], m[4]] for m in self._molecule], dtype=np.float64)
        elif self._cube is not None and self._cube.atoms:
            pts = np.array([[a[2], a[3], a[4]] for a in self._cube.atoms], dtype=np.float64)
        else:
            return
        ctr = pts.mean(axis=0)
        r = float(np.max(np.linalg.norm(pts - ctr, axis=1))) or 1.0
        self.cam.set_center_zoom(ctr, max(r, 0.3) * 1.25)
        self.update()

    def screenshot(self, path, scale: float = 2.0):
        w = max(1, int(round(self.width() * scale)))
        h = max(1, int(round(self.height() * scale)))
        img = self.grabFramebuffer()
        img = img.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        img.save(path)
        self._status(f"截图已保存: {os.path.basename(path)}")

    def export_image(self, path, dpi: float = 600.0, transparent: bool = False):
        """高分辨率导出（参照 IboView 的导出思路）。

        IboView 的 ExportPicture 不是把低分辨率位图拉伸缩放（那样会模糊），
        而是以目标分辨率真正重新渲染场景再把像素读回。这里用分块(tile)离屏
        渲染实现：

          * 目标像素 = 当前控件尺寸 x (dpi / 96)   （96 = 屏幕基准 DPI）
          * 把整图切成若干小瓦片，每片用一个小离屏 FBO 真高分重绘
            （避免一次性分配超大 FBO 撑爆显存导致 GPU context lost / 闪退）
          * 每块 glReadPixels 读回，拼成完整 RGBA 数组，再写 QImage
          * 通过 setDotsPerMeterX/Y 把 600 DPI 写入 PNG 元数据

        transparent=True 时清屏 alpha=0，导出背景透明的 PNG。

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

        # 透明背景：清屏色 alpha=0（保留 RGB 与画布一致）
        clear_col = list(self._bg[:4])
        if transparent:
            clear_col[3] = 0.0

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
                        glClearColor(*clear_col)
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

    def _world_to_screen(self, x, y, z, w=None, h=None):
        """把世界坐标投影到屏幕像素，返回 (sx, sy, visible)。"""
        if w is None or h is None:
            w, h = max(1, self.width()), max(1, self.height())
        view, proj, _, _ = self._view_proj_matrices()
        p = proj @ (view @ np.array([x, y, z, 1.0], dtype=np.float64))
        if abs(p[3]) < 1e-9:
            return 0.0, 0.0, False
        ndc = p[:3] / p[3]
        sx = (ndc[0] * 0.5 + 0.5) * w
        sy = (1.0 - (ndc[1] * 0.5 + 0.5)) * h
        visible = (-1.0 <= ndc[0] <= 1.0 and -1.0 <= ndc[1] <= 1.0
                   and -1.0 <= ndc[2] <= 1.0)
        return float(sx), float(sy), bool(visible)

    def _box_select_atoms(self):
        """返回当前拖拽矩形框内的原子索引列表（1-based）。"""
        if not self._box_start or not self._box_current:
            return []
        x1, y1 = self._box_start
        x2, y2 = self._box_current
        x_min, y_min = min(x1, x2), min(y1, y2)
        x_max, y_max = max(x1, x2), max(y1, y2)
        selected = []
        for i, (_anum, (ax, ay, az)) in enumerate(self._atom_list()):
            sx, sy, visible = self._world_to_screen(ax, ay, az)
            if visible and x_min <= sx <= x_max and y_min <= sy <= y_max:
                selected.append(i + 1)
        return selected

    def _atom_list(self):
        """返回 [(anum, (x, y, z)), ...]，坐标 Bohr。优先分子，其次 cube。

        分子(_molecule)与 cube(_cube.atoms) 都存成 (anum, charge, x, y, z)，
        因此这里统一提取 anum 与坐标，供拾取使用。
        """
        if self._molecule is not None:
            return [(int(m[0]), (m[2], m[3], m[4])) for m in self._molecule]
        if self._cube is not None and self._cube.atoms:
            return [(int(a[0]), (a[2], a[3], a[4])) for a in self._cube.atoms]
        return []

    def _pick_atom(self, x, y):
        """Ray-sphere intersection: find nearest atom at screen (x,y).
        Returns (atom_index_0based, hit_distance) or (-1, inf)."""
        atoms = self._atom_list()
        if not atoms:
            return -1, float('inf')
        ro, rd = self._screen_to_world(x, y)
        best_idx, best_dist = -1, float('inf')
        for i, (anum, ctr) in enumerate(atoms):
            atom_r = self._atom_draw_radius(anum)
            oc = np.asarray(ctr, dtype=np.float64) - ro
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
        atoms = self._atom_list()
        if not atoms:
            return (-1, -1), float('inf')
        ro, rd = self._screen_to_world(x, y)
        coords = np.array([c for _, c in atoms], dtype=np.float64)
        anums = [a for a, _ in atoms]
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
        # Shift+左键 → 框选模式（优先于相机旋转）
        if e.button() == Qt.LeftButton and (e.modifiers() & Qt.ShiftModifier):
            self._box_selecting = True
            self._box_start = (e.x(), e.y())
            self._box_current = (e.x(), e.y())
            self.setCursor(Qt.CrossCursor)
            self.update()
            return
        # 左键按在键长测量标签上 → 拖动标签（优先于选原子/相机）
        if e.button() == Qt.LeftButton:
            hit = self._hit_measure_label(e.x(), e.y())
            if hit is not None:
                (cx, cy, _vis), _sz = self._measure_label_rect(
                    self._measure_items[hit])
                self._mlabel_drag = (hit, e.x() - cx, e.y() - cy)
                self.setCursor(Qt.ClosedHandCursor)
                return
        # 右键在色标条上按下 → 拖动移动色标条（优先于相机旋转）；
        # 松开时若几乎没位移 → 视为右键点击，弹出色标设置菜单
        if e.button() == Qt.RightButton and self._cs_hit_test(e.x(), e.y()) is not None:
            self._cs_drag_mode = "move"
            self._cs_drag_anchor = (e.x(), e.y(), self._cs_offx, self._cs_offy)
            self._cs_press_pos = (e.x(), e.y())
            self.setCursor(Qt.ClosedHandCursor)
            return
        # Camera always gets a chance to start; if no drag happens, the
        # release handler converts it to a pick.
        if e.button() in (Qt.LeftButton, Qt.MiddleButton, Qt.RightButton):
            self.cam.start(e.x(), e.y(), self.width(), self.height(), e.button())

    def mouseMoveEvent(self, e):
        # ── 拖动键长测量标签：标签中心 = 鼠标 - 抓取点在标签内的偏移 ──
        if self._mlabel_drag is not None:
            idx, dx0, dy0 = self._mlabel_drag
            if idx < len(self._measure_items):
                it = self._measure_items[idx]
                mx = (it["p0"][0] + it["p1"][0]) / 2.0
                my = (it["p0"][1] + it["p1"][1]) / 2.0
                mz = (it["p0"][2] + it["p1"][2]) / 2.0
                sx, sy, _vis = self._world_to_screen(mx, my, mz)
                it["offx"] = float(e.x() - dx0 - sx)
                it["offy"] = float(e.y() - dy0 - sy)
                self.update()
            return
        if self._box_selecting:
            self._box_current = (e.x(), e.y())
            self.update()
            return
        # ── 拖动色标条到新位置（右键按住） ──
        if self._cs_drag_mode == "move" and self._cs_drag_anchor is not None:
            ax, ay, aoffx, aoffy = self._cs_drag_anchor
            g = self._cs_geom
            if g is None:
                self._cs_drag_mode = None
                self._cs_drag_anchor = None
                return
            x0, y0, bw, bh, orient = g
            nox = aoffx + (e.x() - ax)
            noy = aoffy + (e.y() - ay)
            w0, h0 = self.width(), self.height()
            # 默认锚点（与 _draw_color_scale 一致），并限制在画布内
            if orient == "vertical":
                bx, by = w0 - 44, (h0 - bh) // 2
            else:
                bx, by = (w0 - bw) // 2, h0 - 52
            nox = max(-bx, min(w0 - (bx + bw), nox))
            noy = max(-by, min(h0 - (by + bh), noy))
            self._cs_offx, self._cs_offy = int(nox), int(noy)
            self.update()
            return
        # ── 悬停在色标条上时光标提示 ──
        if self.cam._btn is None and getattr(self, "_cs_show", False):
            if self._cs_hit_test(e.x(), e.y()) is not None:
                self.setCursor(Qt.OpenHandCursor)
            else:
                self.unsetCursor()
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
        if self._mlabel_drag is not None:
            self._mlabel_drag = None
            self.unsetCursor()
            return
        if self._cs_drag_mode is not None:
            moved = True
            if getattr(self, "_cs_press_pos", None) is not None:
                px, py = self._cs_press_pos
                moved = (abs(e.x() - px) > 4 or abs(e.y() - py) > 4)
            self._cs_drag_mode = None
            self._cs_drag_anchor = None
            self._cs_press_pos = None
            self.unsetCursor()
            if not moved:
                # 原地右键点击色标条 → 设置菜单（字体等）
                self._cs_context_menu(e.globalPos())
            return
        if self._box_selecting:
            self._box_selecting = False
            self.unsetCursor()
            selected = self._box_select_atoms()
            self._box_start = None
            self._box_current = None
            if selected:
                # 框选结果并入内部选中集（0-based）：驱动选中标记高亮
                merged = sorted(set(self._selected_atoms)
                                | {i - 1 for i in selected})
                added = len(merged) - len(self._selected_atoms)
                if merged != list(self._selected_atoms):
                    self._selected_atoms[:] = merged
                    self._regenerate_atoms()
                # IGMH 片段式：框选原子始终归入 vdW 片段集合（增量、持久，
                # 清除画布选中不影响），同时经通知回调自动回填片段输入框；
                # 壳是否只画片段由「仅选中片段」开关决定
                self.add_vdw_selection(selected)
                frag_n = len(self._vdw_sel_atoms)
                self.update()
                self._status(
                    f"框选 {len(selected)} 个原子（新增 {added}），"
                    f"片段共 {frag_n} 个原子")
            else:
                self.update()
            if selected and self._box_cb is not None:
                self._box_cb(selected)
            return
        btn = self.cam._btn
        self.cam.stop()
        if btn == Qt.LeftButton and not self._was_drag:
            # AIM 临界点优先拾取：命中则触发查询回调，不切换原子选中。
            cp_hit = self._pick_aim_cp(e.x(), e.y())
            if cp_hit is not None:
                if self._aim_pick_cb is not None:
                    self._aim_pick_cb(cp_hit[0], cp_hit[1])
                return
            # 键长测量模式：点击只选测量原子，不切换原子选中。
            if self._measure_mode:
                self._measure_click(e.x(), e.y())
                return
            # 左键点击（无拖拽）→ 切换原子选中：点一下选中，再点同一原子取消；
            # 点在空白处（未命中任何原子）→ 取消全部选中。
            hit_idx, _ = self._pick_atom(e.x(), e.y())
            if hit_idx < 0:
                if self._selected_atoms:
                    self._clear_selection()
                return
            if hit_idx >= 0:
                if hit_idx in self._selected_atoms:
                    self._selected_atoms.remove(hit_idx)
                    removed = True
                else:
                    self._selected_atoms.append(hit_idx)
                    removed = False
                self._regenerate_atoms()
                # IGMH 片段式：点选的原子归入 vdW 片段集合（增量、持久）
                if getattr(self, "_vdw_sel_only", False):
                    self.add_vdw_selection([hit_idx + 1])
                self.update()
                # 通知外部（如电荷表联动高亮 / 键级查询）点击到的原子，1-based 索引
                for cb in self._atom_pick_cbs:
                    cb(hit_idx + 1)
                n_sel = len(self._selected_atoms)
                if n_sel == 2:
                    i, j = self._selected_atoms[0], self._selected_atoms[1]
                    self._status(f"已选中原子对 {i}-{j}，右键可选择 成键/断键/虚线")
                elif n_sel > 2:
                    self._status(f"已选中 {n_sel} 个原子")
                elif n_sel == 1:
                    self._status(f"选中原子 {hit_idx}")
                else:
                    self._status(f"已取消选中原子 {hit_idx}")
        elif btn == Qt.RightButton and not self._was_drag:
            # 右键点在键长测量标签上 → 标签属性菜单（旋转/字体/颜色/删除）
            hit = self._hit_measure_label(e.x(), e.y())
            if hit is not None:
                self._measure_label_menu(hit, e.globalPos())
                return
            # Right click (no drag) → show context menu at mouse position
            self._show_context_menu(e.globalPos())

    # ── Context menu (called from mouseReleaseEvent, not contextMenuEvent) ──
    def _show_context_menu(self, pos):
        """Build and show right-click context menu.

        Uses a closure-dispatch pattern instead of lambdas to avoid
        late-binding issues with signal-slot connections."""
        from PyQt5.QtWidgets import QMenu, QAction
        menu = QMenu(self)
        # 白底黑字（覆盖主题默认样式，保证右键菜单可读）
        menu.setStyleSheet(_QMENU_QSS)

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

        # ── 选中原子平面填充（苯环等环系半透明涂色，多环并存）──
        # 操作逻辑：选原子 → 右键「填充选中原子平面」显式生成；
        # 之后再右键可针对该条改色/删除，或清除全部。
        cur = frozenset(self._selected_atoms)
        cur_idx = next((i for i, it in enumerate(self._fill_items)
                        if it["sel"] == cur), None) if cur else None
        if n_sel >= 3 and cur_idx is None:
            menu.addSeparator()
            a = QAction(f"填充平面颜色…（{n_sel} 个原子）", self)
            a.triggered.connect(self._fill_selected_plane_action)
            menu.addAction(a)
        if self._fill_items:
            menu.addSeparator()
            if cur_idx is not None:
                a = QAction(f"平面填充 #{cur_idx + 1} 颜色…", self)
                a.triggered.connect(
                    lambda _=False, i=cur_idx: self._pick_fill_color(i))
                menu.addAction(a)
                a2 = QAction(f"删除平面填充 #{cur_idx + 1}", self)
                a2.triggered.connect(
                    lambda _=False, i=cur_idx: self._remove_fill_item(i))
                menu.addAction(a2)
            a3 = QAction(f"清除全部平面填充（共 {len(self._fill_items)} 条）",
                         self)
            a3.triggered.connect(self.clear_plane_fills)
            menu.addAction(a3)

        # ── vdW 片段集合（IGMH 式持久片段）管理 ──
        if getattr(self, "_vdw_sel_atoms", None):
            menu.addSeparator()
            a = QAction(
                f"清除 vdW 片段（当前 {len(self._vdw_sel_atoms)} 个原子）", self)
            a.triggered.connect(lambda: self.clear_vdw_selection())
            menu.addAction(a)

        # ── Reset all overrides ──
        if self._bond_overrides:
            menu.addSeparator()
            a = QAction("重置所有键为自动检测", self)
            a.triggered.connect(self.reset_bond_overrides)
            menu.addAction(a)

        menu.popup(pos)   # non-blocking: handler → update → main event loop → paintGL

    def _fill_selected_plane_action(self):
        """右键菜单：选颜色（含透明度）→ 确定后填充当前选中的原子平面。"""
        from PyQt5.QtWidgets import QColorDialog
        r, g, b, a = self._fill_rgba
        dlg = QColorDialog(QColor(int(r * 255), int(g * 255), int(b * 255),
                                  int(a * 255)), self)
        dlg.setWindowTitle("平面填充颜色")
        dlg.setOption(QColorDialog.DontUseNativeDialog)
        dlg.setOption(QColorDialog.ShowAlphaChannel)
        dlg.setStyleSheet(_QDIALOG_QSS)
        self._localize_dialog_buttons(dlg)
        if dlg.exec_():
            c = dlg.selectedColor()
            if c.isValid():
                rgba = (c.red() / 255.0, c.green() / 255.0,
                        c.blue() / 255.0, c.alpha() / 255.0)
                self._fill_rgba = rgba   # 后续填充沿用本次颜色
                self._fill_selected_plane(rgba)

    def _pick_fill_color(self, idx):
        """右键菜单：改指定条平面填充颜色/透明度（非原生对话框，白底黑字）。"""
        from PyQt5.QtWidgets import QColorDialog
        if not (0 <= idx < len(self._fill_items)):
            return
        r, g, b, a = self._fill_items[idx]["rgba"]
        dlg = QColorDialog(QColor(int(r * 255), int(g * 255), int(b * 255)),
                           self)
        dlg.setWindowTitle("平面填充颜色")
        dlg.setOption(QColorDialog.DontUseNativeDialog)
        dlg.setStyleSheet(_QDIALOG_QSS)
        self._localize_dialog_buttons(dlg)
        if dlg.exec_():
            c = dlg.selectedColor()
            if c.isValid():
                # 颜色对话框不带 alpha 滑块时保留原透明度
                self.set_fill_item_color(
                    idx, (c.red() / 255.0, c.green() / 255.0,
                          c.blue() / 255.0, self._fill_items[idx]["rgba"][3]))

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
        # 恢复原子自身元素色：清掉外部的颜色覆盖（如 IGMH 片段红/青着色）。
        # vdW 片段集合独立持久（IGMH 式），不受此影响——壳保留。
        if self._atom_color_overrides:
            self._atom_color_overrides = {}
        # 只清画布选中状态；vdW 片段集合持久保留（IGMH 式，壳不丢）。
        # 如需同时清除片段，用 clear_vdw_selection()。
        if self._molecule is not None or self._cube is not None:
            self._gen_atoms()
            self._needs_upload = True
            self.update()
        # 平面填充持久保留（右键菜单「清除平面填充」删除）
        self._status("已清除原子选中（平面填充保留）")

    def _regenerate_atoms(self):
        """Regenerate atom mesh (respects bond overrides). Does NOT upload."""
        if self._molecule is not None or self._cube is not None:
            self._gen_atoms()
            self._needs_upload = True

    # ── 选中原子平面填充 ────────────────────────────────────────
    @staticmethod
    def _convex_hull_2d(pts):
        """Andrew monotone chain 凸包（避免引入 scipy）。输入 (x, y) 元组列表，
        返回逆时针凸包顶点。"""
        pts = sorted(set(pts))
        if len(pts) <= 2:
            return pts

        def cross(o, a, b):
            return ((a[0] - o[0]) * (b[1] - o[1])
                    - (a[1] - o[1]) * (b[0] - o[0]))

        lower = []
        for p in pts:
            while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
                lower.pop()
            lower.append(p)
        upper = []
        for p in reversed(pts):
            while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
                upper.pop()
            upper.append(p)
        return lower[:-1] + upper[:-1]

    def _fill_selected_plane(self, rgba=None):
        """右键菜单动作：把当前选中的 ≥3 个原子填充为半透明平面。

        rgba：本次填充的颜色/透明度（0..1）；None 时用 `_fill_rgba`。
        支持多个环并存：每条填充持久存于 `_fill_items`（同一组原子不会
        重复生成），清除选中后保留，右键菜单可改色/删除/全部清除。
        几何：Newell 法求最佳拟合平面法线 → 原子投影到平面 → 凸包 →
        围绕质心扇形三角化。原子近似共线时不生成。
        """
        atoms = self._atom_list()
        sel = [i for i in self._selected_atoms if 0 <= i < len(atoms)]
        if len(sel) < 3:
            return   # 保留现有填充（持久），仅不重新生成
        key = frozenset(sel)
        if any(it["sel"] == key for it in self._fill_items):
            return   # 同一组原子已有填充，不重复生成
        pts = np.array([atoms[i][1] for i in sel], dtype=np.float64)
        # Newell 方法：对有序/无序点集都稳健地给出拟合平面法线
        n = np.zeros(3)
        for k in range(len(pts)):
            a, b = pts[k], pts[(k + 1) % len(pts)]
            n[0] += (a[1] - b[1]) * (a[2] + b[2])
            n[1] += (a[2] - b[2]) * (a[0] + b[0])
            n[2] += (a[0] - b[0]) * (a[1] + b[1])
        ln = np.linalg.norm(n)
        if ln < 1e-6:          # 原子近似共线 → 无法定义平面
            return
        n /= ln
        ctr = pts.mean(axis=0)
        # 平面内正交基
        u1 = pts[0] - ctr
        u1 -= np.dot(u1, n) * n
        lu = np.linalg.norm(u1)
        if lu < 1e-6:
            return
        u1 /= lu
        u2 = np.cross(n, u1)
        # 投影到平面内 2D 坐标 → 凸包
        rel = pts - ctr
        p2 = np.stack([rel @ u1, rel @ u2], axis=1)
        hull = self._convex_hull_2d([tuple(p) for p in p2])
        if len(hull) < 3:
            return
        hull3 = np.array([ctr + h[0] * u1 + h[1] * u2 for h in hull])
        # 扇形三角化：质心 + 凸包相邻顶点
        fan_v = np.vstack([[ctr], hull3])
        m = len(hull3)
        tris = []
        for k in range(1, m):
            tris.append([0, k, k + 1])
        tris.append([0, m, 1])
        surf = IsoSurface()
        surf.vertices = fan_v.astype(np.float32)
        surf.normals = np.tile(n.astype(np.float32), (len(fan_v), 1))
        r, g, b, a = rgba if rgba is not None else self._fill_rgba
        surf.colors = np.tile(
            np.array([r, g, b, a], dtype=np.float32), (len(fan_v), 1))
        surf.indices = np.concatenate(tris).astype(np.uint32)
        self._fill_items.append({"surf": surf, "sel": key,
                                 "rgba": (r, g, b, a)})
        self._rebuild_fill_mesh()
        self._status(f"已生成平面填充 #{len(self._fill_items)}"
                     f"（共 {len(self._fill_items)} 条；右键可改颜色/删除）")

    def _rebuild_fill_mesh(self):
        """把所有平面填充条目拼接成合并网格（一次 upload/draw）。"""
        if not self._fill_items:
            self._fill_surf = None
            self._needs_upload = True
            self.update()
            return
        verts, norms, cols, idxs = [], [], [], []
        off = 0
        for it in self._fill_items:
            s = it["surf"]
            verts.append(s.vertices)
            norms.append(s.normals)
            cols.append(s.colors)
            idxs.append(s.indices + off)
            off += s.vertex_count
        comb = IsoSurface()
        comb.vertices = np.vstack(verts).astype(np.float32)
        comb.normals = np.vstack(norms).astype(np.float32)
        comb.colors = np.vstack(cols).astype(np.float32)
        comb.indices = np.concatenate(idxs).astype(np.uint32)
        self._fill_surf = comb
        self._needs_upload = True
        self.update()

    def set_fill_item_color(self, idx, rgba):
        """设置第 idx 条平面填充的颜色/透明度（0..1 RGBA）。"""
        if not (0 <= idx < len(self._fill_items)):
            return
        rgba = tuple(float(v) for v in rgba[:4])
        self._fill_items[idx]["rgba"] = rgba
        self._fill_rgba = rgba   # 后续新填充沿用最近一次使用的颜色
        s = self._fill_items[idx]["surf"]
        s.colors = np.tile(
            np.array([*rgba], dtype=np.float32), (s.vertex_count, 1))
        self._rebuild_fill_mesh()

    def clear_plane_fills(self):
        """清除全部平面填充。"""
        self._fill_items = []
        self._rebuild_fill_mesh()

    def _remove_fill_item(self, idx):
        """删除第 idx 条平面填充。"""
        if 0 <= idx < len(self._fill_items):
            del self._fill_items[idx]
            self._rebuild_fill_mesh()

    def render_plane_fill(self, view, nm, proj):
        """半透明平面填充：深度测试开、不写深度、alpha 混合、双面渲染。"""
        if getattr(self, "_fill_mesh", None) is None \
                or self._fill_mesh.count == 0:
            return
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LEQUAL)
        glDepthMask(GL_FALSE)
        glDisable(GL_CULL_FACE)        # 平面正反两面都可见
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glUseProgram(self._prog_atom)
        self._set_xforms(self._prog_atom, view, nm, proj)
        # 关键：unlit 纯色（reg 漫反射/高光全 0 + ambient=1 直接叠加顶点色）。
        # 若走 Phong，斜视角 cos→0 时填充面几乎全黑，看起来像"没有填充"。
        self.set_iboview_uniforms(
            self._prog_atom, [1.0, 0.0, 0.0, 1.0],
            diffuse=(1.0, 1.0, 1.0, 1.0), ambient=1.0)
        self._set_atom_mv_uniforms(False)
        self._set_atom_ring_uniforms(False)
        self._fill_mesh.draw()
        glDisable(GL_BLEND)
        glDepthMask(GL_TRUE)

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

            # 二次上色：独立的键着色器（与原子同光照，但无 vdW/描边/圆环机制）。
            # 失败不致命：仅退化为不做键最终重绘。
            try:
                vsk = compile_shader(VERT_BOND, GL_VERTEX_SHADER)
                self._prog_bond = link_program(
                    vsk, compile_shader(FRAG_BOND, GL_FRAGMENT_SHADER))
            except Exception as e:
                self._prog_bond = 0
                print(f"[bond repaint] shader init failed: {e}")

            # 背景渐变（MolViewer 三段竖向渐变）
            vb = compile_shader(VERT_BG, GL_VERTEX_SHADER)
            self._prog_bg = link_program(vb, compile_shader(FRAG_BG, GL_FRAGMENT_SHADER))
            self._vao_bg = glGenVertexArrays(1)

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

            # 实时接触阴影 / AO（可选：失败仅禁用该特效，不影响渲染）
            try:
                self._prog_ssao = link_program(
                    compile_shader(VERT_QUAD, GL_VERTEX_SHADER),
                    compile_shader(FRAG_SSAO, GL_FRAGMENT_SHADER))
                if self._vao_quad == 0:
                    self._vao_quad = glGenVertexArrays(1)
                self._ao_scene = PeelTarget()
                self._ao_ok = True
            except Exception as e:
                self._ao_ok = False
                self._prog_ssao = 0
                print(f"[ssao] 初始化失败，接触阴影禁用: {e}")
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

    def _ensure_ao_targets(self, w, h):
        """(Re)create the AO scene FBO when the drawable size changed."""
        if not self._ao_ok or self._ao_scene is None:
            return False
        try:
            t = self._ao_scene
            if t.fbo == 0 or t.w != w or t.h != h:
                t.create(w, h)
            return True
        except Exception as e:
            self._ao_ok = False
            self._status(f"接触阴影 FBO 创建失败，已禁用: {e}")
            return False

    def set_ao_enabled(self, on):
        """开/关实时接触阴影 / AO 特效。"""
        self._ao_enabled = bool(on)
        self.update()

    def set_ao_strength(self, v):
        self._ao_strength = max(0.0, min(3.0, float(v)))
        self.update()

    def set_ao_radius(self, px):
        self._ao_radius_px = max(1.0, min(40.0, float(px)))
        self.update()

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

        # ── ESP 色标条叠加（2D，QPainter） ──
        if getattr(self, "_cs_show", False):
            self._draw_color_scale()

        # ── ESP 极值点数值标签叠加 ──
        self._draw_extrema_labels()

        # ── 键长测量标注叠加（连线中点距离标签） ──
        self._draw_measure_labels()

        # ── MolViewer 球棍样式叠加（阴影 / 十字 / 原子标签） ──
        self._draw_mol_overlay()

        # ── Shift+左键框选橡皮筋 ──
        if getattr(self, "_box_selecting", False):
            self._draw_box_rect()

    def _draw_box_rect(self):
        """拖拽框选时绘制半透明橡皮筋矩形（QPainter 叠加）。"""
        if not self._box_start or not self._box_current:
            return
        x1, y1 = self._box_start
        x2, y2 = self._box_current
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing, False)
            r = QRectF(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))
            p.fillRect(r, QColor(80, 140, 255, 40))
            pen = QPen(QColor(60, 120, 255), 1.0, Qt.DashLine)
            p.setPen(pen)
            p.drawRect(r)
        finally:
            p.end()

    # ── Internal ──

    def _atom_color(self, anum):
        """Return the (r,g,b) ball colour for an atom under the current style."""
        # 通用碳色覆盖优先（预设 c_color 指定，任意分子风格生效）
        if anum == 6 and self._carbon_rgb is not None:
            return self._carbon_rgb
        # 通用氢色覆盖优先（预设 h_color 指定）
        if anum == 1 and self._hydrogen_rgb is not None:
            return self._hydrogen_rgb
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
            # HoukMol：氢白色、碳浅灰，其余元素用 GaussView 配色
            if anum in _HOUKMOL_COLORS:
                return _HOUKMOL_COLORS[anum]
            return _GVIEW_COLORS.get(anum, (0.78, 0.78, 0.78))
        if self._mol_style == "SobArt":
            # Chem311：元素用 SobArt 表（氢白、碳亮沙、氮蓝、氧红……），
            # 未列出的元素退回 GaussView 配色
            if anum in _SOB_ART_COLORS:
                return _SOB_ART_COLORS[anum]
            return _GVIEW_COLORS.get(anum, (0.78, 0.78, 0.78))
        if self._mol_style == "Vcube":
            # VMD 风格：碳色由 vcube 预设指定（灰/棕/青），其余元素用 GaussView 配色
            if anum == 6:
                return self._vcube_c_rgb
            return _GVIEW_COLORS.get(anum, (0.78, 0.78, 0.78))
        # CPK (IboView ElementColors)
        return _IBO_ELEMENT_COLORS[anum] if 0 <= anum < len(_IBO_ELEMENT_COLORS) \
            else (0.5, 0.5, 0.5)

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
                old = self._meshes[2]
                if old is not None:
                    try:
                        old.destroy()
                    except Exception:
                        pass
                self._meshes[2] = GlMesh()
                self._bond_surf = None
                self._bond_mesh = GlMesh()
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
        # 原子配色统一走 _atom_color()（内部已处理 VMD single / Vcube / HoukMol 等分支）
        for k in range(n):
            anum = anums[k]
            # 隐藏氢原子：除保留编号外，H 球体不生成
            if not self._hydrogen_visible(k + 1, anum):
                continue
            ax, ay, az = coords[k]
            # 范德华模式：原子球直接以 vdW 半径绘制（诉求 1，比例可调）
            if self._vdw_mode:
                r = _vdw_radius(anum) * self._vdw_scale
            else:
                r = _atom_base_radius(anum) * ATOM_DRAW_SCALE * self._atom_scale
            # 选中标记改用半透明二十面体包裹（见 _gen_selection_marker），
            # 原子本体保持元素色/电荷覆盖色，不再染绿。
            if (k + 1) in self._atom_color_overrides:
                col = self._atom_color_overrides[k + 1]
            elif anum in self._element_color_overrides:
                col = self._element_color_overrides[anum]
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

        # 键几何单独收集：除常规 opaque 网格外，再建一份键专属网格，
        # 供每帧末尾"二次上色"重绘 pass 使用（键色与 vdW 外壳彻底解耦）。
        bond_v = []; bond_n = []; bond_c = []; bond_i = []; bond_off = 0

        for i in range(n):
            for j in range(i + 1, n):
                # 隐藏氢原子：任一端 H 被隐藏 → 该键不画
                if not (self._hydrogen_visible(i + 1, anums[i])
                        and self._hydrogen_visible(j + 1, anums[j])):
                    continue
                p = coords[i]; q = coords[j]
                rij = float(np.linalg.norm(q - p))
                if rij < 1e-4:
                    continue
                zi = anums[i]; zj = anums[j]
                # Use the Bohr-valued covalent radii (g_CovalentRadii) so the
                # threshold is compared in the same Bohr frame as the coords.
                ci = _COVALENT_RADII_BOHR[zi] if 0 <= zi < len(_COVALENT_RADII_BOHR) else 0.7
                cj = _COVALENT_RADII_BOHR[zj] if 0 <= zj < len(_COVALENT_RADII_BOHR) else 0.7
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
                if self._bond_color is not None:
                    bc = self._bond_color
                    col_i = col_j = np.array([bc[0], bc[1], bc[2], 1.0], dtype=np.float32)
                elif self._mol_style == "HoukMol":
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
                        bond_v.append(dv.astype(np.float32))
                        bond_n.append(dn.astype(np.float32))
                        bond_c.append(dc.astype(np.float32))
                        bond_i.append(di.astype(np.uint32) + bond_off)
                        bond_off += len(dv)
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
                        bond_v.append(tv.astype(np.float32))
                        bond_n.append(tn.astype(np.float32))
                        bond_c.append(tc.astype(np.float32))
                        bond_i.append(ci_ + bond_off); bond_off += len(tv)

        # ── ESP 极值点标记（金=极大值，浅蓝=极小值；半径 Å→Bohr） ──
        if self._extrema_pts:
            er = max(float(self._extrema_radius) * ANGSTROM_TO_BOHR,
                     0.02 * ANGSTROM_TO_BOHR)
            col_max = np.array([0.95, 0.78, 0.10, 1.0], dtype=np.float32)
            col_min = np.array([0.68, 0.85, 0.95, 1.0], dtype=np.float32)
            ev, en, ei = make_sphere(er, 2)
            for (ex, ey, ez, ekind) in self._extrema_pts:
                is_max = str(ekind).lower() in ("max", "pos")
                col = col_max if is_max else col_min
                vv = ev + np.array([ex, ey, ez], dtype=np.float32)
                cc = np.tile(col, (len(vv), 1))
                all_v.append(vv)
                all_n.append(en)
                all_c.append(cc)
                all_i.append(ei + off)
                off += len(vv)

        # ── AIM 临界点（按类型着色）与梯度路径点云（灰色） ──
        if self._aim_cps:
            cpr = max(float(self._aim_cp_radius) * ANGSTROM_TO_BOHR,
                      0.03 * ANGSTROM_TO_BOHR)
            cpv, cpn, cpi = make_sphere(cpr, 2)
            for (cx, cy, cz, col, _serial, _cp_type) in self._aim_cps:
                vv = cpv + np.array([cx, cy, cz], dtype=np.float32)
                cc = np.tile(np.array([*col, 1.0], dtype=np.float32), (len(vv), 1))
                all_v.append(vv)
                all_n.append(cpn)
                all_c.append(cc)
                all_i.append(cpi + off)
                off += len(vv)
        if self._aim_path_pts:
            ppr = max(float(self._aim_path_radius) * ANGSTROM_TO_BOHR,
                      0.01 * ANGSTROM_TO_BOHR)
            pv, pn, pi = make_sphere(ppr, 1)
            grey = np.array([0.45, 0.45, 0.48, 1.0], dtype=np.float32)
            for (px, py, pz) in self._aim_path_pts:
                vv = pv + np.array([px, py, pz], dtype=np.float32)
                cc = np.tile(grey, (len(vv), 1))
                all_v.append(vv)
                all_n.append(pn)
                all_c.append(cc)
                all_i.append(pi + off)
                off += len(vv)

        if all_v:
            surf = IsoSurface()
            surf.vertices = np.vstack(all_v).astype(np.float32)
            surf.normals = np.vstack(all_n).astype(np.float32)
            surf.colors = np.vstack(all_c).astype(np.float32)
            surf.indices = np.concatenate(all_i).astype(np.uint32)
            self._atom_surf = surf
        else:
            self._atom_surf = None
        # 键专属网格（二次上色重绘 pass 用；与主网格中键几何完全一致）
        if bond_v:
            bsurf = IsoSurface()
            bsurf.vertices = np.vstack(bond_v).astype(np.float32)
            bsurf.normals = np.vstack(bond_n).astype(np.float32)
            bsurf.colors = np.vstack(bond_c).astype(np.float32)
            bsurf.indices = np.concatenate(bond_i).astype(np.uint32)
            self._bond_surf = bsurf
        else:
            self._bond_surf = None
        # GPU upload is deferred to _upload() (called from paintGL with the
        # GL context already current) so atoms are not lost when load() runs
        # before the context is bound.
        self._gen_selection_marker()
        self._gen_vdw_shells()

    def _gen_vdw_shells(self):
        """为每个原子生成范德华半径的半透明外壳（诉求 2）。

        在正常球棍模型（共价半径小球 + 键）之上叠加一层 vdW 半径的实心
        半透明球，元素色 + 半透明 α，双面渲染以体现"包围感"。外壳网格在
        render_vdw_shells() 中于透明通道叠加绘制（深度测试开、不写深度）。
        每个球顶点携带所属原子序号（ids），供片元着色器做多球布尔差集——
        凡落入「其他」原子 vdW 球内的片元被 discard，重叠区即被挖空
        （空间填充 / CPK 效果）。
        """
        atoms = self._atom_list()
        if not atoms or not self._vdw_shell:
            self._vdw_surf = None
            self._vdw_balls = []
            return
        # 「仅选中片段」模式：只给片段集合里的原子（0-based）生成外壳。
        # 集合独立于画布瞬时选中状态（IGMH 片段式），清除选择不丢壳。
        frag_set = None
        if getattr(self, "_vdw_sel_only", False) \
                and getattr(self, "_vdw_sel_atoms", None):
            frag_set = self._vdw_sel_atoms
        verts, norms, cols, idxs, ids = [], [], [], [], []
        ball_centers = []   # 与外壳同序：第 bid 个球 → (cx,cy,cz,r)
        off = 0
        bid = 0
        for k in range(len(atoms)):
            # 球数上限：多球布尔差集在片元着色器里一次性接收的球数有限，
            # 超过 VDW_MAX_ATOMS 的原子不再生成外壳（避免 uniform 越界）。
            if bid >= VDW_MAX_ATOMS:
                break
            anum, (x, y, z) = atoms[k]
            # 仅片段模式：集合非空时只画片段内的原子
            if frag_set is not None and k not in frag_set:
                continue
            # 隐藏氢原子时，其外壳也不画（与原子球一致）
            if not self._hydrogen_visible(k + 1, anum):
                continue
            r = _vdw_radius(anum) * self._vdw_scale
            ctr = np.array([x, y, z], dtype=np.float32)
            # sub=3（1280 三角面/球）：比 sub=2 更圆滑，配合片元着色器的球面
            # 重建，让两个 vdW 球相交处的交线呈平滑圆形而非波浪线。
            v, nrm, idx = make_sphere(r, 3)
            v = v + ctr
            # 沿用原子元素色，半透明（诉求：沿用元素色半透明）
            ac = self._atom_color(anum)
            c = np.tile(np.array([*ac, self._vdw_shell_alpha], dtype=np.float32),
                        (len(v), 1))
            verts.append(v); norms.append(nrm); cols.append(c)
            ids.append(np.full((len(v), 1), bid, dtype=np.float32))
            idxs.append(idx + off); off += len(v)
            ball_centers.append((float(x), float(y), float(z), float(r)))
            bid += 1
        if not verts:
            self._vdw_surf = None
            self._vdw_balls = []
            return
        surf = IsoSurface()
        surf.vertices = np.vstack(verts).astype(np.float32)
        surf.normals = np.vstack(norms).astype(np.float32)
        surf.colors = np.vstack(cols).astype(np.float32)
        surf.indices = np.concatenate(idxs).astype(np.uint32)
        surf.ids = np.vstack(ids).astype(np.float32)   # location=3 球序号
        self._vdw_surf = surf
        self._vdw_balls = ball_centers

    def _gen_selection_marker(self):
        """为每个选中的原子生成半透明选中标记（IboView 移植，可换形状）。

        IboView 在 IvView3D.cpp 中对选中的原子额外画一个半径 = 1.8 × 原子
        绘制半径的正二十面体（MakeIcosahedron(1.8)），颜色 = 0.4*原子色 +
        0.6*白、alpha=0.5，在透明通道里叠加。这里把所有选中原子的标记
        烘焙进一个网格（顶点颜色含 alpha），统一在透明通道绘制。

        形状可选：icosahedron（二十面体）/ sphere（光滑透明球）/
        torus（圆环）/ glow（光晕：内壳 + 大透明外壳）。
        """
        atoms = self._atom_list()
        selected = self._selected_atoms
        if not atoms or not selected:
            self._sel_surf = None
            return

        shape = getattr(self, "_sel_marker_shape", "icosahedron")
        if shape == "sphere":
            base_v, base_n, base_i = make_sphere(1.0, 3)
        elif shape == "torus":
            base_v, base_n, base_i = make_torus(1.0, tube=0.34)
        elif shape == "glow":
            base_v, base_n, base_i = make_sphere(1.0, 2)
        else:
            base_v, base_n, base_i = make_icosahedron(1.0)

        # 呼吸动画：半径 ±12% 正弦
        pulse = 1.0 + 0.12 * math.sin(getattr(self, "_sel_pulse", 0.0)) \
            if getattr(self, "_sel_pulse_on", False) else 1.0

        verts, norms, cols, idxs = [], [], [], []
        off = 0
        for k in selected:
            if not (0 <= k < len(atoms)):
                continue
            anum, (x, y, z) = atoms[k]
            r = _atom_base_radius(anum) * ATOM_DRAW_SCALE * self._atom_scale
            s = 1.8 * r * pulse
            ctr = np.array([x, y, z], dtype=np.float32)
            # 0.4*原子色 + 0.6*白（IboView 的选中标记颜色），alpha=0.5
            ac = self._atom_color(anum)
            light = (0.4 * ac[0] + 0.6, 0.4 * ac[1] + 0.6, 0.4 * ac[2] + 0.6)

            if shape == "glow":
                # 内壳（主体）+ 大透明外壳（光晕）
                for (scale, alpha) in ((1.0, 0.45), (1.62, 0.12)):
                    v = base_v * (s * scale) + ctr
                    c = np.tile(np.array([*light, alpha], dtype=np.float32),
                                (len(v), 1))
                    verts.append(v)
                    norms.append(base_n)
                    cols.append(c)
                    idxs.append(base_i + off)
                    off += len(v)
            else:
                v = base_v * s + ctr
                c = np.tile(np.array([*light, 0.5], dtype=np.float32), (len(v), 1))
                verts.append(v)
                norms.append(base_n)
                cols.append(c)
                idxs.append(base_i + off)
                off += len(v)

        if not verts:
            self._sel_surf = None
            return
        surf = IsoSurface()
        surf.vertices = np.vstack(verts).astype(np.float32)
        surf.normals = np.vstack(norms).astype(np.float32)
        surf.colors = np.vstack(cols).astype(np.float32)
        surf.indices = np.concatenate(idxs).astype(np.uint32)
        self._sel_surf = surf

    def set_selection_marker_shape(self, name):
        """切换选中原子标记形状：icosahedron / sphere / torus / glow。"""
        if name not in ("icosahedron", "sphere", "torus", "glow"):
            return
        self._sel_marker_shape = name
        if self._selected_atoms:
            self._gen_selection_marker()
            self._needs_upload = True
            self.update()

    def set_selection_marker_pulse(self, on):
        """选中标记呼吸动画开关（半径 ±12% 正弦呼吸）。"""
        self._sel_pulse_on = bool(on)
        if self._sel_pulse_on:
            if self._sel_pulse_timer is None:
                self._sel_pulse_timer = QTimer(self)
                self._sel_pulse_timer.timeout.connect(self._on_sel_pulse_tick)
            self._sel_pulse_timer.start(60)
        else:
            if self._sel_pulse_timer is not None:
                self._sel_pulse_timer.stop()
            self._sel_pulse = 0.0
            if self._selected_atoms:
                self._gen_selection_marker()
                self._needs_upload = True
            self.update()

    def _on_sel_pulse_tick(self):
        self._sel_pulse += 0.1
        if self._selected_atoms:
            self._gen_selection_marker()
            # 只重传选中标记，避免每帧全量重传整个等值面网格（大网格卡顿）
            try:
                self._sel_mesh.upload(self._sel_surf)
            except Exception:
                self._needs_upload = True
        self.update()

    def _upload(self):
        for i, s in enumerate([self._pos_surf, self._neg_surf]):
            self._meshes[i].upload(s)
        self._meshes[2].upload(self._atom_surf)
        self._sel_mesh.upload(self._sel_surf)
        self._vdw_mesh.upload(self._vdw_surf)
        self._fill_mesh.upload(getattr(self, "_fill_surf", None))
        self._bond_mesh.upload(getattr(self, "_bond_surf", None))

    # ── Ball-and-stick scale controls ──

    def set_molecule(self, atoms, bonds=None):
        """载入 fchk/xyz 时设置独立分子数据（坐标单位 Angstrom，与 MolCanvas 一致）。

        内部转换为 Bohr 存储到 self._molecule；之后即使尚未加载轨道 cube，
        画布也会显示分子球棍模型，满足「先显示分子，双击轨道再看」的需求。
        atoms 格式：[(idx, symbol, anum, (x, y, z)), ...]
        """
        # 载入新分子即丢弃上一场景的 AIM 覆盖层（避免跨 tab 残留）
        self._aim_cps = []
        self._aim_path_pts = []
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
        self._orbital_recs = []
        self._orbital_flipped = []
        self._surf_vcolor = False   # 表面已清除
        # 平面填充随旧原子坐标一并失效（全部清除）
        self._fill_items = []
        self._fill_surf = None
        # 新分子坐标变了，旧测量标注位置失效，一并清除
        self._measure_items = []
        self._measure_pair = []
        self._mlabel_drag = None
        self._vmd_scene = None   # 新分子：清空 VMD 同步场景登记
        conv = ANGSTROM_TO_BOHR
        self._molecule = [
            (a[2], 0.0, a[3][0] * conv, a[3][1] * conv, a[3][2] * conv)
            for a in atoms
        ]
        self._gen_atoms()
        self._needs_upload = True
        self.update()

    def set_atom_colors(self, overrides):
        """按原子索引(1-based)覆盖球棍模型的原子颜色。

        overrides: dict {atom_idx: (r,g,b)}，颜色分量 0..1；传 None 或空 dict
        清除覆盖，恢复到按元素/分子风格配色。
        """
        self._atom_color_overrides = dict(overrides) if overrides else {}
        if self._molecule is not None or self._cube is not None:
            self._gen_atoms()
            self._needs_upload = True
            self.update()

    def set_element_colors(self, overrides):
        """按元素(原子序数)覆盖球棍模型的原子颜色（元素原子颜色设置）。

        overrides: dict {atomic_number: (r,g,b)}，颜色分量 0..1；传 None/空 dict
        清除覆盖，恢复按分子风格配色。
        优先级：原子索引覆盖 > 元素覆盖 > 分子风格默认色（CPK 等）。
        """
        self._element_color_overrides = dict(overrides) if overrides else {}
        if self._molecule is not None or self._cube is not None:
            self._gen_atoms()
            self._needs_upload = True
            self.update()

    def clear_element_colors(self):
        self.set_element_colors(None)

    def element_colors(self):
        return dict(self._element_color_overrides)

    # ── ESP 扩展（整合自 ESPViewer） ──

    def set_extrema(self, points, radius=None, values=None):
        """设置 ESP 极值点标记（金=极大值，浅蓝=极小值）。

        points: [(x, y, z, kind), ...]，坐标在世界帧（Bohr），kind 为
        "max"/"min"（也接受 "pos"/"neg" 别名）。标记颜色按 kind 区分，
        不按 ESP 数值正负（极大值也可能是负的局部峰）。
        radius: 小球半径（Å）。
        values: 与 points 对齐的数值（显示单位），用于标签显示。
        """
        norm = []
        for pt in points:
            x, y, z = float(pt[0]), float(pt[1]), float(pt[2])
            kind = str(pt[3]).lower() if len(pt) > 3 else "max"
            norm.append((x, y, z, kind))
        self._extrema_pts = norm
        if values is not None:
            self._extrema_vals = [float(v) for v in values]
        else:
            self._extrema_vals = [0.0] * len(norm)
        if radius is not None:
            self._extrema_radius = float(radius)
        self._gen_atoms()
        self._needs_upload = True
        self.update()

    def clear_extrema(self):
        """清除所有 ESP 极值点标记。"""
        self._extrema_pts = []
        self._gen_atoms()
        self._needs_upload = True
        self.update()

    # ── AIM 拓扑分析覆盖层（临界点 + 梯度路径点云） ──

    def set_aim_overlay(self, cps, path_pts, cp_radius=None, path_radius=None):
        """设置 AIM 临界点与梯度路径点云。

        cps:       [(x, y, z, (r,g,b), serial, cp_type), ...]，坐标 Å；
                   颜色分量 0..1，serial 为 CP 编号（点击查询用），
                   cp_type 为类型字母 C/N/O/F。
        path_pts:  [(x, y, z), ...] 坐标 Å（梯度路径采样点，灰色小球）。
        cp_radius / path_radius: 球半径（Å）。
        """
        conv = ANGSTROM_TO_BOHR
        self._aim_cps = []
        for cp in cps:
            x, y, z = float(cp[0]), float(cp[1]), float(cp[2])
            col = tuple(float(c) for c in cp[3][:3])
            serial = cp[4] if len(cp) > 4 else 0
            cp_type = cp[5] if len(cp) > 5 else '?'
            self._aim_cps.append((x * conv, y * conv, z * conv, col, serial, cp_type))
        self._aim_path_pts = [
            (float(p[0]) * conv, float(p[1]) * conv, float(p[2]) * conv)
            for p in path_pts
        ]
        if cp_radius is not None:
            self._aim_cp_radius = float(cp_radius)
        if path_radius is not None:
            self._aim_path_radius = float(path_radius)
        self._gen_atoms()
        self._needs_upload = True
        self.update()

    def clear_aim_overlay(self):
        """清除 AIM 临界点/路径覆盖层。"""
        self._aim_cps = []
        self._aim_path_pts = []
        self._gen_atoms()
        self._needs_upload = True
        self.update()

    def clear_analysis(self):
        """清空画布上所有分析效果：等值面、ESP 极值点、AIM 临界点/键径、
        平面填充、键长标注、色标条、ESP 点云模式与 VMD 同步场景登记。
        保留分子结构与渲染样式设置（配色/光照/视角等不变）。
        """
        self._cube = None
        self._pos_surf = None
        self._neg_surf = None
        self._orbital_recs = []
        self._orbital_flipped = []
        self._surf_vcolor = False
        self._extrema_pts = []
        self._extrema_vals = []
        self._extrema_labels = False
        self._aim_cps = []
        self._aim_path_pts = []
        self._fill_items = []
        self._fill_surf = None
        self._measure_items = []
        self._measure_pair = []
        self._mlabel_drag = None
        self._esp_point_mode = False
        self._cs_show = False
        self._vmd_scene = None
        self._gen_atoms()
        self._needs_upload = True
        self.update()

    def set_aim_pick_callback(self, cb):
        """设置临界点点击回调：cb(serial, cp_type)。"""
        self._aim_pick_cb = cb

    def _pick_aim_cp(self, x, y):
        """Ray-sphere 拾取最近的 AIM 临界点，返回 (serial, cp_type) 或 None。"""
        if not self._aim_cps:
            return None
        ro, rd = self._screen_to_world(x, y)
        best_dist = float('inf')
        best = None
        er = max(float(self._aim_cp_radius) * ANGSTROM_TO_BOHR,
                 0.03 * ANGSTROM_TO_BOHR) * 1.15
        for (cx, cy, cz, _col, serial, cp_type) in self._aim_cps:
            oc = np.array([cx, cy, cz], dtype=np.float64) - ro
            t_ca = np.dot(oc, rd)
            if t_ca < 0:
                continue
            d2 = np.dot(oc, oc) - t_ca * t_ca
            if d2 < er * er:
                t_hc = np.sqrt(er * er - d2)
                t = t_ca - t_hc
                if t < best_dist:
                    best_dist = t
                    best = (serial, cp_type)
        return best

    def set_esp_point_mode(self, enabled, point_size=3.0):
        """PT 点云模式：把 ESP 等值面顶点渲染成彩色点（跳过三角面）。"""
        self._esp_point_mode = bool(enabled)
        try:
            self._esp_point_size = float(point_size)
        except (TypeError, ValueError):
            self._esp_point_size = 3.0
        self.update()

    def set_color_scale(self, low, high, unit=None, show=None):
        """设置画布内色标条的范围/单位，可选控制显示。"""
        try:
            self._cs_low = float(low)
            self._cs_high = float(high)
        except (TypeError, ValueError):
            return
        if unit is not None:
            self._cs_unit = str(unit)
        if show is not None:
            self._cs_show = bool(show)
        self.update()

    def set_show_color_scale(self, show):
        self._cs_show = bool(show)
        self.update()

    def set_color_scale_cmap(self, cmap_name):
        """设置色标条使用的配色（与 ESP 表面配色一致）。"""
        self._cs_cmap = self._resolve_cmap(cmap_name)
        self.update()

    def set_color_scale_ticks(self, n):
        """设置画布内色标轴的刻度段数（2~20）。"""
        try:
            self._cs_ticks = max(2, min(20, int(n)))
        except (TypeError, ValueError):
            self._cs_ticks = 5
        self.update()

    def set_color_scale_orient(self, orient):
        """设置画布内色标轴方位："vertical"（竖直）或 "horizontal"（水平）。"""
        self._cs_orient = "horizontal" if orient == "horizontal" else "vertical"
        self.update()

    def set_color_scale_len(self, frac):
        """设置画布内色标条长度（占画布高/宽的比例，0.15~0.95）。"""
        try:
            self._cs_len = max(0.15, min(0.95, float(frac)))
        except (TypeError, ValueError):
            self._cs_len = 0.55
        self.update()

    def _cs_hit_test(self, mx, my):
        """命中检测：返回色标条几何 (x0,y0,bw,bh,orient)，未命中返回 None。"""
        if not getattr(self, "_cs_show", False) or self._cs_geom is None:
            return None
        x0, y0, bw, bh, orient = self._cs_geom
        if x0 - 10 <= mx <= x0 + bw + 10 and y0 - 10 <= my <= y0 + bh + 10:
            return (x0, y0, bw, bh, orient)
        return None

    # ── ESP 极值点数值标签 ──────────────────────────────────────
    def set_extrema_labels(self, show=None, font_size=None, dist=None,
                           border=None):
        """控制极值点数值标签（QPainter 叠加）。参数为 None 表示保持当前值。"""
        if show is not None:
            self._extrema_labels = bool(show)
        if font_size is not None:
            try:
                self._extrema_label_font = max(6, min(40, int(font_size)))
            except (TypeError, ValueError):
                pass
        if dist is not None:
            try:
                self._extrema_label_dist = max(0, min(120, int(dist)))
            except (TypeError, ValueError):
                pass
        if border is not None:
            self._extrema_label_border = bool(border)
        self.update()

    def set_extrema_radius(self, radius_angstrom):
        """实时调整极值点小球半径（Å）。"""
        try:
            self._extrema_radius = max(0.01, float(radius_angstrom))
        except (TypeError, ValueError):
            return
        if self._extrema_pts:
            self._gen_atoms()
        self.update()

    def _draw_extrema_labels(self):
        """在画布上为每个极值点叠加 ESP 数值标签。"""
        if not self._extrema_pts or not self._extrema_labels:
            return
        w0, h0 = max(1, self.width()), max(1, self.height())
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing)
            p.setRenderHint(QPainter.TextAntialiasing)
            fs = int(self._extrema_label_font)
            f = p.font()
            f.setPointSize(max(6, fs))
            p.setFont(f)
            dist = int(self._extrema_label_dist)
            border = bool(self._extrema_label_border)
            for i, (ex, ey, ez, ekind) in enumerate(self._extrema_pts):
                sx, sy, visible = self._world_to_screen(ex, ey, ez, w0, h0)
                if not visible:
                    continue
                val = self._extrema_vals[i] if i < len(self._extrema_vals) else None
                txt = f"{val:.2f}" if val is not None else ""
                is_max = str(ekind).lower() in ("max", "pos")
                color = QColor(190, 140, 0) if is_max else QColor(20, 90, 160)
                tw = p.fontMetrics().horizontalAdvance(txt) + 8
                th = p.fontMetrics().height() + 4
                tx = sx - tw / 2.0
                ty = sy - dist - th if is_max else sy + dist
                rect = QRectF(tx, ty, tw, th)
                if border:
                    p.fillRect(rect, QColor(255, 255, 255, 200))
                    p.setPen(QPen(QColor(120, 120, 120)))
                    p.drawRect(rect)
                p.setPen(color)
                p.drawText(rect, Qt.AlignCenter, txt)
        finally:
            p.end()

    # ── MolViewer 球棍样式叠加（阴影 / 十字 / 原子标签） ──
    def _atom_screen_geo(self, w=None, h=None):
        """返回 [(anum, x, y, z, sx, sy, sr, visible), ...]。

        x/y/z 为世界坐标（Bohr，供 3D 圆环投影用）；sx/sy 为屏幕像素；
        sr 为屏幕半径。
        """
        if w is None or h is None:
            w, h = max(1, self.width()), max(1, self.height())
        ox, oy, _ = self._world_to_screen(0.0, 0.0, 0.0, w, h)
        px, py, _ = self._world_to_screen(1.0, 0.0, 0.0, w, h)
        per_bohr = math.hypot(px - ox, py - oy) or 1.0
        out = []
        for i, (anum, (ax, ay, az)) in enumerate(self._atom_list()):
            # 隐藏氢原子：被隐藏的 H 不参与标签/阴影/十字叠加
            if not self._hydrogen_visible(i + 1, anum):
                continue
            sx, sy, vis = self._world_to_screen(ax, ay, az, w, h)
            r = _atom_base_radius(anum) * ATOM_DRAW_SCALE * self._atom_scale
            out.append((anum, i + 1, ax, ay, az, sx, sy, r * per_bohr, vis))
        return out

    def _draw_mol_overlay(self):
        """把 MolViewer（MolCanvas）的 2D 叠加效果画到画布：阴影→十字→原子标签。

        十字与 molcanvas.py 逐字一致：两条**世界空间**圆环
        (azimuth=90°, tilt=71°) 与 (azimuth=205°, tilt=0°)，环半径
        = 0.92×原子世界半径，随分子一起旋转；只画视图 z ≥ 原子中心 z 的
        前向弧，背面不显示（看不到圆球背后的圆环）。
        """
        if not (self._shadows or self._crosshair or self._atom_labels != 2):
            return
        if not self._molecule and not (self._cube and self._cube.atoms):
            return
        geo = self._atom_screen_geo()
        if not geo:
            return
        dark = (sum(self._bg[:3]) / 3.0) < 0.5
        view, proj, w, h = self._view_proj_matrices()
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing)
            for anum, aidx, ax, ay, az, sx, sy, sr, vis in geo:
                if not vis or sr < 1.0:
                    continue
                # ── 软阴影（MolViewer 偏移椭圆） ──
                if self._shadows:
                    p.save()
                    p.setOpacity(0.10)
                    p.setPen(Qt.NoPen)
                    p.setBrush(QBrush(QColor(0, 0, 0)))
                    p.drawEllipse(QPointF(sx + sr * 0.3, sy + sr * 0.55),
                                  sr * 1.25, max(1.0, sr * 0.32))
                    p.restore()
                # （十字圆环已改为 GL 着色器绘制：FRAG_ATOM 的 u_Rings 球面大圆带，
                #   必然贴在球面上，此处不再用 QPainter 叠加）
                # ── 原子标签 ──
                if self._atom_labels != 2:
                    if self._atom_labels == 0:
                        label = ELEMENT_SYMBOLS.get(anum, str(anum))
                    else:
                        # 原子序号：分子内 1-based 编号（与拾取/保留编号一致）
                        label = str(aidx)
                    f = QFont(p.font())
                    f.setPointSize(max(7, int(sr * 0.7)))
                    f.setBold(True)
                    p.setFont(f)
                    p.setPen(QPen(QColor(220, 220, 230) if dark else Qt.black))
                    fm = p.fontMetrics()
                    tw = fm.horizontalAdvance(label)
                    p.drawText(QPointF(sx - tw / 2.0, sy + fm.height() / 3.0), label)
        finally:
            p.end()

    @staticmethod
    def _bwr_rgb(t):
        """Blue→White→Red 传递函数（t∈[0,1]）。"""
        t = max(0.0, min(1.0, t))
        if t < 0.5:
            k = t / 0.5
            return (k, k, 0.6 + 0.4 * k)
        k = (t - 0.5) / 0.5
        return (0.6 + 0.4 * (1.0 - k), 1.0 - k, 1.0 - k)

    def _resolve_cmap(self, cmap_name):
        """把 ESP_CMAPS 配色名解析成 matplotlib Colormap；失败返回 None（回退 BWR）。"""
        try:
            from esp_viewer import ESP_CMAPS
            mpl_name = ESP_CMAPS.get(cmap_name, ("bwr", True))[0] if ESP_CMAPS else "bwr"
            from matplotlib import cm as _mcm
            try:
                return _mcm.get_cmap(mpl_name)
            except Exception:
                return None
        except Exception:
            return None

    def _cs_cmap_rgb(self, t):
        """当前配色在 t∈[0,1] 处的 RGB（0..1）。"""
        if getattr(self, "_cs_cmap", None) is not None:
            try:
                rgba = self._cs_cmap(float(t))
                return (rgba[0], rgba[1], rgba[2])
            except Exception:
                pass
        return self._bwr_rgb(t)

    @staticmethod
    def _fmt_tick(v):
        a = abs(v)
        if a == 0:
            return "0"
        if a >= 100 or a < 0.01:
            return f"{v:.2g}"
        if a >= 10:
            return f"{v:.1f}"
        return f"{v:.2f}"

    def set_color_scale_font(self, family, pt):
        """设置色标条（刻度数字 + 单位）字体。"""
        self._cs_font_family = family
        self._cs_font_pt = max(6, int(pt))
        self.update()

    def _cs_context_menu(self, global_pos):
        """右键点色标条：设置字体 / 恢复默认。"""
        from PyQt5.QtWidgets import QMenu, QFontDialog
        menu = QMenu(self)
        menu.setStyleSheet(_QMENU_QSS)
        a_font = menu.addAction("色标字体…")
        a_reset = menu.addAction("恢复默认字体 (Arial)")
        act = menu.exec_(global_pos)
        if act is None:
            return
        if act is a_font:
            f0 = QFont(self._cs_font_family, self._cs_font_pt)
            dlg = QFontDialog(self)
            dlg.setWindowTitle("色标字体")
            dlg.setCurrentFont(f0)
            dlg.setOption(QFontDialog.DontUseNativeDialog)
            dlg.setStyleSheet(_QDIALOG_QSS)
            self._localize_dialog_buttons(dlg)
            if dlg.exec_():
                f = dlg.selectedFont()
                self.set_color_scale_font(f.family(),
                                          f.pointSize() or self._cs_font_pt)
        elif act is a_reset:
            self.set_color_scale_font("Arial", 10)

    def _draw_color_scale(self):
        """叠加 ESP 色标条（QPainter，渐变 + 刻度 + 单位）。

        长度按 _cs_len（画布高/宽比例）计算、位置可被右键拖动（_cs_offx/y），
        支持竖直/水平两种方位与可调刻度段数；几何写入 _cs_geom 供命中检测。
        字体（刻度数字 + 单位）默认 Arial，右键色标条可设置。
        """
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing)
            p.setRenderHint(QPainter.TextAntialiasing)
            p.setFont(QFont(self._cs_font_family or "Arial",
                            max(6, int(self._cs_font_pt))))
            fm = p.fontMetrics()
            w0, h0 = self.width(), self.height()
            n_ticks = int(getattr(self, "_cs_ticks", 5))
            orient = getattr(self, "_cs_orient", "vertical")

            def _grad(rect, horizontal):
                # 注意：PyQt5 的 QLinearGradient 没有 QRectF 构造重载，必须用浮点坐标
                # 语义统一：水平条 左=低值(负)，右=高值(正)；
                #           竖直条 上=高值(正)，下=低值(负)。
                # _cs_cmap_rgb(t) 的 t=0 是低值端（蓝），t=1 是高值端（红）。
                if horizontal:
                    grad = QLinearGradient(rect.x(), rect.y(),
                                           rect.x() + rect.width(), rect.y())
                else:
                    grad = QLinearGradient(rect.x(), rect.y(),
                                           rect.x(), rect.y() + rect.height())
                n = 32
                for i in range(n + 1):
                    t = i / n
                    r, g, b = self._cs_cmap_rgb(t if horizontal else 1.0 - t)
                    grad.setColorAt(t, QColor(int(r * 255), int(g * 255), int(b * 255)))
                return grad

            if orient == "horizontal":
                # 水平条：底部居中，长度可调
                bar_w = max(60, int(w0 * float(getattr(self, "_cs_len", 0.6))))
                bar_h = 16
                x0 = (w0 - bar_w) // 2 + int(getattr(self, "_cs_offx", 0))
                y0 = h0 - 52 + int(getattr(self, "_cs_offy", 0))
                if y0 < 30:
                    return
                rect = QRectF(x0, y0, bar_w, bar_h)
                p.fillRect(rect, QBrush(_grad(rect, True)))
                p.setPen(QPen(QColor(120, 120, 120)))
                p.drawRect(rect)
                # 刻度：左=low，右=high，中段均匀
                p.setPen(QColor(40, 40, 40))
                labels = self._tick_values(n_ticks)
                for i, (val, t) in enumerate(labels):
                    tx = x0 + bar_w * (1.0 - t)
                    p.drawLine(QPointF(tx, y0 - 3), QPointF(tx, y0 + bar_h + 3))
                    align = Qt.AlignHCenter | Qt.AlignTop
                    if i == 0:
                        align = Qt.AlignRight | Qt.AlignTop
                    elif i == len(labels) - 1:
                        align = Qt.AlignLeft | Qt.AlignTop
                    p.drawText(QRectF(tx - 40, y0 + bar_h + 4, 80,
                                      fm.height() + 4),
                               align, self._fmt_tick(val))
                # 单位文字：按字体度量开框（宽防截断、高防裁行）
                ubox_w = max(80, fm.horizontalAdvance(self._cs_unit) + 6)
                ubox_h = fm.height() + 4
                ubox_x = max(4, x0 + bar_w - ubox_w)
                ubox_y = y0 - 6 - ubox_h
                p.drawText(QRectF(ubox_x, ubox_y, ubox_w, ubox_h),
                           Qt.AlignRight | Qt.AlignVCenter, self._cs_unit)
                self._cs_geom = (x0, y0, bar_w, bar_h, "horizontal")
                # 两端拖拽小手柄（提示可拖动）
                p.setBrush(QColor(255, 255, 255))
                p.setPen(QPen(QColor(40, 40, 40)))
                p.drawEllipse(QRectF(x0 - 4, y0 + bar_h // 2 - 4, 8, 8))
                p.drawEllipse(QRectF(x0 + bar_w - 4, y0 + bar_h // 2 - 4, 8, 8))
            else:
                # 竖直条：右侧居中，长度可调
                bar_w = 16
                bar_h = max(40, int(h0 * float(getattr(self, "_cs_len", 0.55))))
                x0 = w0 - 44 + int(getattr(self, "_cs_offx", 0))
                y0 = (h0 - bar_h) // 2 + int(getattr(self, "_cs_offy", 0))
                if y0 < 30 or x0 < 60:
                    return
                rect = QRectF(x0, y0, bar_w, bar_h)
                p.fillRect(rect, QBrush(_grad(rect, False)))
                p.setPen(QPen(QColor(120, 120, 120)))
                p.drawRect(rect)
                p.setPen(QColor(40, 40, 40))
                labels = self._tick_values(n_ticks)
                for i, (val, t) in enumerate(labels):
                    # t=0 是 hi（正值）→ 顶部；t=1 是 lo（负值）→ 底部
                    # （渐变位置 0 也在顶部且取高值端色，颜色与数字一致）
                    ty = y0 + bar_h * t
                    p.drawLine(QPointF(x0 - 3, ty), QPointF(x0 + bar_w + 3, ty))
                    p.drawText(QRectF(x0 - 50, ty - 10, 44, 20),
                               Qt.AlignRight | Qt.AlignVCenter, self._fmt_tick(val))
                # 单位文字：按字体度量开框（宽防截断、高防裁行），
                # 画到条上方（顶部刻度值之上）、水平居中于色标条；
                # 贴近画布顶部放不下时回退到条下方
                ubox_w = max(44, fm.horizontalAdvance(self._cs_unit) + 6)
                ubox_h = fm.height() + 4
                ubox_x = x0 + bar_w / 2.0 - ubox_w / 2.0
                ubox_x = max(4, min(ubox_x, w0 - 4 - ubox_w))
                ubox_y = y0 - 5 - ubox_h
                if ubox_y < 2:
                    ubox_y = y0 + bar_h + 5
                    if ubox_y + ubox_h > h0 - 2:
                        ubox_y = h0 - 2 - ubox_h
                p.drawText(QRectF(ubox_x, ubox_y, ubox_w, ubox_h),
                           Qt.AlignHCenter | Qt.AlignVCenter, self._cs_unit)
                self._cs_geom = (x0, y0, bar_w, bar_h, "vertical")
                # 两端拖拽小手柄
                p.setBrush(QColor(255, 255, 255))
                p.setPen(QPen(QColor(40, 40, 40)))
                p.drawEllipse(QRectF(x0 + bar_w // 2 - 4, y0 + bar_h - 4, 8, 8))
                p.drawEllipse(QRectF(x0 + bar_w // 2 - 4, y0 - 4, 8, 8))
        finally:
            p.end()

    def _tick_values(self, n):
        """返回 [(值, t), ...]，从高到低共 n+1 个等距刻度。"""
        lo, hi = self._cs_low, self._cs_high
        out = []
        for i in range(n + 1):
            t = i / n
            out.append((hi + (lo - hi) * t, t))
        return out

    def set_atom_scale(self, scale):
        """Set atom ball radius multiplier and regenerate the molecule model."""
        self._atom_scale = float(scale)
        if self._molecule is not None or self._cube is not None:
            self._gen_atoms()
            self._needs_upload = True
            self.update()

    # ── Van-der-Waals visualization (诉求 1 & 2) ──────────────────────────
    def set_vdw_mode(self, on):
        """诉求 1：原子球直接以范德华半径绘制（而非绘制半径/共价半径）。

        注意：vdW 半径远大于共价半径，开启后等价于"原子显示为 vdW 大小"。
        """
        self._vdw_mode = bool(on)
        if self._molecule is not None or self._cube is not None:
            self._gen_atoms()
            self._needs_upload = True
            self.update()

    def set_vdw_shell(self, on, alpha=None):
        """诉求 2：在正常球棍模型之上叠加半透明范德华外壳。

        on: 是否显示外壳; alpha: 外壳不透明度 (0..1)，默认 0.2。
        """
        self._vdw_shell = bool(on)
        if alpha is not None:
            self._vdw_shell_alpha = float(alpha)
        if self._molecule is not None or self._cube is not None:
            self._gen_vdw_shells()
            self._needs_upload = True
            self.update()

    def set_vdw_shell_selection_only(self, on):
        """vdW 外壳仅覆盖片段原子集合（IGMH 片段式，与画布选中状态独立）。

        on=True 时外壳只画 _vdw_sel_atoms 里的原子；集合为空时等价于
        全无外壳；on=False 恢复全分子外壳。
        """
        self._vdw_sel_only = bool(on)
        self._regen_vdw_shells_if_needed()

    def add_vdw_fragment_changed_cb(self, cb):
        """订阅 vdW 片段集合变化：cb([atom_idx_1based, ...])（排序后）。"""
        if cb:
            self._vdw_frag_cbs.append(cb)

    def _notify_vdw_frag_changed(self):
        idxs = sorted(i + 1 for i in self._vdw_sel_atoms)
        for cb in self._vdw_frag_cbs:
            try:
                cb(idxs)
            except Exception:
                pass

    def add_vdw_selection(self, indices_1based):
        """框选/点选的原子归入 vdW 片段集合（增量，不清除已有成员）。"""
        for i in indices_1based:
            self._vdw_sel_atoms.add(int(i) - 1)
        self._notify_vdw_frag_changed()
        self._regen_vdw_shells_if_needed()

    def clear_vdw_selection(self, regenerate=True):
        """清空 vdW 片段集合（仅清集合，不动画布选中状态）。"""
        self._vdw_sel_atoms.clear()
        self._notify_vdw_frag_changed()
        if regenerate:
            self._regen_vdw_shells_if_needed()

    def _regen_vdw_shells_if_needed(self):
        """片段状态变化后按需重生成 vdW 外壳。"""
        if (getattr(self, "_vdw_shell", False)
                and (self._molecule is not None or self._cube is not None)):
            self._gen_vdw_shells()
            self._needs_upload = True
            self.update()

    def set_vdw_scale(self, scale):
        """诉求：调整 vdW 半径比例（Bondi 表值 × scale，默认 1.0）。

        同时作用于「范德华半径」原子显示与「vdW 外壳」两种模式。
        """
        self._vdw_scale = float(scale)
        if self._molecule is not None or self._cube is not None:
            if self._vdw_mode:
                self._gen_atoms()       # 原子以 vdW 半径显示 → 重生成原子 + 外壳
            elif self._vdw_shell:
                self._gen_vdw_shells()  # 仅外壳 → 只重生成外壳
            self._needs_upload = True
            self.update()

    def set_vdw_outline(self, on, color=None, width=None):
        """vdW 外壳描边（独立于原子描边单独控制）。

        on: 是否描边; color: 0..1 (r,g,b); width: 0..1 剪影带厚度。
        """
        self._vdw_outline = bool(on)
        if color is not None:
            self._vdw_outline_color = tuple(float(x) for x in color[:3])
        if width is not None:
            self._vdw_outline_width = max(0.01, min(0.99, float(width)))
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

        # ── 实时接触阴影 / AO：场景先渲染进 AO 场景 FBO（color+depth），
        #    末尾屏幕空间后处理输出 color×ao。离屏 tile 导出（vp）不加。 ──
        prev_fbo = glGetIntegerv(GL_FRAMEBUFFER_BINDING)
        use_ao = (self._ao_enabled and self._ao_ok and vp is None
                  and self._prog_ssao and self._ao_scene is not None)
        if use_ao:
            if not self._ensure_ao_targets(w, h):
                use_ao = False
            else:
                glBindFramebuffer(GL_FRAMEBUFFER, self._ao_scene.fbo)

        glViewport(0, 0, w, h)
        glClearColor(*self._bg)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        # ── MolViewer 三段竖向背景渐变（先于所有 3D 几何） ──
        if getattr(self, "_bg_grad", None) is not None and self._prog_bg:
            glDisable(GL_DEPTH_TEST); glDepthMask(GL_FALSE)
            glDisable(GL_BLEND)
            glUseProgram(self._prog_bg)
            t, m, b = self._bg_grad
            glUniform3f(glGetUniformLocation(self._prog_bg, 'uTop'), t[0], t[1], t[2])
            glUniform3f(glGetUniformLocation(self._prog_bg, 'uMid'), m[0], m[1], m[2])
            glUniform3f(glGetUniformLocation(self._prog_bg, 'uBot'), b[0], b[1], b[2])
            glBindVertexArray(self._vao_bg)
            glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
            glBindVertexArray(0)
            glEnable(GL_DEPTH_TEST); glDepthMask(GL_TRUE)

        # 范德华外壳先画（画在背景之上、原子/键之下）：外壳不写深度，
        # 之后的不透明原子+键会盖在其上，键保持样式键色、不被外壳盖住变黑。
        self.render_vdw_shells(view, nm, proj)

        # 选中原子平面填充（半透明，画在原子/键之前会被其正确遮挡）
        self.render_plane_fill(view, nm, proj)

        self.render_opaque(view, nm, proj)

        # 原子+键兜底重绘 / 键二次上色（盖住 vdW 外壳，保持样式键色）。
        # 必须放在透明等值面之前：若放在等值面之后，键会被重绘到等值面
        # 之上，等值面后面的键就会"透视"出来（应被等值面遮挡/压暗）。
        if self._vdw_shell and getattr(self, "_vdw_surf", None) is not None:
            self.render_opaque(view, nm, proj, depth_func=GL_LEQUAL)
        self.render_bonds(view, nm, proj)

        used_dp = False
        if self._dp_ok and self._dp_layers > 0:
            try:
                used_dp = self.render_transparent_depth_peeling(view, nm, proj, w, h)
            except Exception as e:
                self._dp_ok = False
                self._status(f"depth peeling 失败，回退排序混合: {e}")
                used_dp = False
                # DP 中途异常可能残留自定义 FBO/混合状态，先复位再走回退
                glBindFramebuffer(GL_FRAMEBUFFER, 0)
                glViewport(0, 0, w, h)
                glEnable(GL_DEPTH_TEST)
                glDepthFunc(GL_LESS)
                glDepthMask(GL_TRUE)
                glDisable(GL_BLEND)
        if not used_dp:
            self.render_transparent_sorted_fallback(view, nm, proj)

        # 选中原子标记（半透明二十面体）最后叠加，确保始终可见
        self.render_selection_markers(view, nm, proj)

        glDisable(GL_BLEND)
        glDepthMask(GL_TRUE)

        # ── SSAO 后处理：场景 color+depth → color×ao，输出到原 FBO ──
        if use_ao:
            try:
                glBindFramebuffer(GL_FRAMEBUFFER, prev_fbo)
                glViewport(0, 0, w, h)
                glDisable(GL_DEPTH_TEST)
                glDepthMask(GL_FALSE)
                glDisable(GL_BLEND)
                glUseProgram(self._prog_ssao)
                glActiveTexture(GL_TEXTURE0)
                glBindTexture(GL_TEXTURE_2D, self._ao_scene.tex_color)
                glUniform1i(glGetUniformLocation(self._prog_ssao, 'u_Color'), 0)
                glActiveTexture(GL_TEXTURE1)
                glBindTexture(GL_TEXTURE_2D, self._ao_scene.tex_depth)
                glUniform1i(glGetUniformLocation(self._prog_ssao, 'u_Depth'), 1)
                glUniform1f(glGetUniformLocation(self._prog_ssao, 'u_Strength'),
                            float(self._ao_strength))
                # 采样半径自适应：画面短边的 ~3%（随缩放自动覆盖原子表面）
                _rpx = max(4.0, 0.03 * min(w, h))
                glUniform1f(glGetUniformLocation(self._prog_ssao, 'u_RadiusPx'),
                            _rpx)
                glUniform1f(glGetUniformLocation(self._prog_ssao, 'u_Bias'),
                            float(self._ao_bias))
                # 主光屏幕方向（视图空间 _light_dirs[0] 的 xy，正交投影下
                # 屏幕方向即其 x/y 分量；指向光源）
                ld0 = (getattr(self, "_light_dirs", None)
                       or getattr(self, "_light_default_dirs", None)
                       or [(0.5, 0.5, 0.70710678)])
                lx = float(ld0[0][0]) if ld0 else 0.5
                ly = float(ld0[0][1]) if ld0 else 0.5
                ln = math.hypot(lx, ly)
                if ln > 1e-6:
                    glUniform2f(glGetUniformLocation(self._prog_ssao,
                                                     'u_LightDir'),
                                lx / ln, ly / ln)
                else:
                    glUniform2f(glGetUniformLocation(self._prog_ssao,
                                                     'u_LightDir'), 0.0, 0.0)
                glBindVertexArray(self._vao_quad)
                glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
                glBindVertexArray(0)
                glActiveTexture(GL_TEXTURE1)
                glBindTexture(GL_TEXTURE_2D, 0)
                glActiveTexture(GL_TEXTURE0)
                glBindTexture(GL_TEXTURE_2D, 0)
                glEnable(GL_DEPTH_TEST)
                glDepthMask(GL_TRUE)
            except Exception as e:
                self._ao_ok = False
                print(f"[ssao] pass 失败，接触阴影禁用: {e}")

    def render_opaque(self, view, nm, proj, depth_func=GL_LESS):
        """Opaque geometry (atoms): depth test + depth write, no blending.

        depth_func：默认 GL_LESS；在 vdW 外壳之后重绘原子+键时用 GL_LEQUAL，
        保证与原有深度相等的片元也能通过（避免同深度被 LESS 淘汰而画不上）。
        """
        glEnable(GL_DEPTH_TEST); glDepthFunc(depth_func); glDepthMask(GL_TRUE)
        glDisable(GL_BLEND)
        glUseProgram(self._prog_atom)
        self._set_xforms(self._prog_atom, view, nm, proj)
        self.set_iboview_uniforms(self._prog_atom, self._sp['a_reg'],
                                  diffuse=(0.8, 0.8, 0.8, 1.0))
        self._set_atom_outline_uniforms()
        self._set_atom_mv_uniforms(True)
        self._set_atom_ring_uniforms(True)
        self._meshes[2].draw()

        # PT (点云) 模式：把 ESP 等值面顶点渲染成彩色点（不透明），
        # 下方透明通道会跳过三角面。
        if self._esp_point_mode:
            glUseProgram(self._prog_orb)
            self._set_xforms(self._prog_orb, view, nm, proj)
            self.set_iboview_uniforms(self._prog_orb, self._sp['o_reg'],
                                      diffuse=(1.0, 1.0, 1.0, 1.0))
            self._set_mv_grad_uniform(self._prog_orb, self._mv_grad)
            # 点云也走完整轨道 uniform 推送，保证描边/渐变设置即时生效
            self._set_orbital_uniforms(self._prog_orb)
            for mi in (0, 1):
                self._meshes[mi].draw_points(self._esp_point_size)

    def render_bonds(self, view, nm, proj, depth_func=GL_LEQUAL):
        """二次上色：每帧末尾用独立的键着色器把化学键按样式顶点色重绘一遍。

        该 pass 不携带任何 vdW 挖孔/描边/圆环状态，键的最终颜色只取决于
        几何生成时的样式配色（_gen_atoms），与 vdW 外壳等中间状态彻底解耦。
        """
        if getattr(self, "_prog_bond", 0) == 0 or self._bond_mesh.count == 0:
            return
        was_cull = bool(glIsEnabled(GL_CULL_FACE))
        glDisable(GL_CULL_FACE)   # 与全局约定一致：键圆柱双面渲染
        glEnable(GL_DEPTH_TEST); glDepthFunc(depth_func); glDepthMask(GL_TRUE)
        glDisable(GL_BLEND)
        glUseProgram(self._prog_bond)
        self._set_xforms(self._prog_bond, view, nm, proj)
        self.set_iboview_uniforms(self._prog_bond, self._sp['a_reg'],
                                  diffuse=(0.8, 0.8, 0.8, 1.0))
        self._set_mv_grad_uniform(self._prog_bond, self._mv_grad)
        self._bond_mesh.draw()
        if was_cull:
            glEnable(GL_CULL_FACE)

    def render_selection_markers(self, view, nm, proj):
        """Draw semi-transparent icosahedron markers around selected atoms.

        移植自 IboView 的选中标记：半透明正二十面体包裹所选原子，深度测试
        但**不写深度**，用标准 alpha 混合叠加在不透明几何之上。
        """
        if self._sel_mesh.count == 0:
            return
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LEQUAL)
        glDepthMask(GL_FALSE)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glUseProgram(self._prog_atom)
        self._set_xforms(self._prog_atom, view, nm, proj)
        self.set_iboview_uniforms(self._prog_atom, self._sp['a_reg'],
                                  diffuse=(1.0, 1.0, 1.0, 1.0))
        self._set_atom_outline_uniforms()
        self._set_atom_mv_uniforms(False)
        self._set_atom_ring_uniforms(False)
        self._sel_mesh.draw()
        glDisable(GL_BLEND)
        glDepthMask(GL_TRUE)

    def render_vdw_shells(self, view, nm, proj):
        """Draw semi-transparent van-der-Waals radius shells around atoms (诉求 2).

        在正常球棍模型之上叠加每个原子的 vdW 半径实心半透明球（沿用原子元素色），
        深度测试开启但不写深度，标准 alpha 混合，关闭背面剔除以体现"包围感"。
        """
        if getattr(self, "_vdw_mesh", None) is None or self._vdw_mesh.count == 0:
            return
        balls = getattr(self, "_vdw_balls", None) or []
        n_balls = min(len(balls), VDW_MAX_ATOMS)
        if n_balls == 0:
            return
        # 记录进入时的剔除状态，退出时恢复（而不是想当然地重新开启）
        self._cull_before_shells = bool(glIsEnabled(GL_CULL_FACE))
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LEQUAL)
        glDepthMask(GL_FALSE)
        glDisable(GL_CULL_FACE)        # 双面渲染：球壳正反都画，包围感更明显
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glUseProgram(self._prog_atom)
        self._set_xforms(self._prog_atom, view, nm, proj)
        # ── 材质/光照参考「轨道等值面」：用 o_reg + ambient/spec/FX 通道，
        #    与一键样式（sob-art / IBOVIEW / HoukMol / IQmol）的等值面观感一致，
        #    而非原子球的固定 a_reg。──
        sp = self._sp
        self.set_iboview_uniforms(
            self._prog_atom, sp['o_reg'],
            diffuse=(1.0, 1.0, 1.0, 1.0),
            ambient=sp.get('ambient', 0.0),
            spec_color=sp.get('spec_color', (1.0, 1.0, 1.0)),
            spec_mul=sp.get('spec_mul', 1.0),
            fx=sp.get('fx', 0),
            fx_strength=sp.get('fx_strength', 0.0),
            fx_color=sp.get('fx_color', (1.0, 1.0, 1.0)),
        )
        self._set_vdw_outline_uniforms()   # 独立描边（不跟原子描边联动）
        # u_MvGrad>0 走 MolViewer 径向渐变（如 HoukMol 的 gau_default），
        # u_MvGrad=0 走 IboView 多灯 Phong（含 FX），随当前样式变化。
        self._set_atom_mv_uniforms(True)
        self._set_atom_ring_uniforms(False)
        # ── 多球布尔差集：把所有原子 vdW 球心/半径交给片元着色器 ──
        p = self._prog_atom
        glUniform1f(glGetUniformLocation(p, 'u_VdwEnable'), 1.0)
        glUniform1i(glGetUniformLocation(p, 'u_VdwCount'), n_balls)
        centers = np.array([b[:3] for b in balls], dtype=np.float32).ravel()
        radii = np.array([b[3] for b in balls], dtype=np.float32)
        glUniform3fv(glGetUniformLocation(p, 'u_VdwCenter'), n_balls, centers)
        glUniform1fv(glGetUniformLocation(p, 'u_VdwRadius'), n_balls, radii)
        self._vdw_mesh.draw()
        # 关闭剔除，避免影响后续（选中标记等）用同一 program 的绘制
        glUniform1f(glGetUniformLocation(p, 'u_VdwEnable'), 0.0)
        glDisable(GL_BLEND)
        glDepthMask(GL_TRUE)
        # 恢复进入本 pass 前的剔除状态。本渲染器在 initializeGL 中全局
        # 关闭了 CULL_FACE（等值面/键圆柱双面渲染依赖此状态），若此处无条件
        # 重新开启，壳开启后键圆柱会因三角形环绕方向不一致而只露出法线背向
        # 相机的远侧面 → 漫反射为 0 → 化学键整体变黑（黑键 bug 根因）。
        if not self._cull_before_shells:
            glDisable(GL_CULL_FACE)
        else:
            glEnable(GL_CULL_FACE)

    def render_transparent_depth_peeling(self, view, nm, proj, w, h):
        """Front-to-back depth peeling, following IboView's FView3d::RenderScene.

        Pass i renders only the fragments strictly nearer than the depth
        recorded in pass i-1 (shader FRAG_ORB_DP), and each resulting layer is
        composited over the main framebuffer with regular
        `GL_SRC_ALPHA / GL_ONE_MINUS_SRC_ALPHA` blending.  Because the layers
        arrive in exact front-to-back order the result is order independent.
        """
        if self._esp_point_mode:
            return True  # PT 点云模式：不渲染透明三角面（点已在 render_opaque 画完）
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
        self._set_atom_mv_uniforms(True)
        self._set_atom_ring_uniforms(True)
        self._meshes[2].draw()

        glActiveTexture(GL_TEXTURE0)
        prog = self._prog_orb_dp
        glUseProgram(prog)
        self._set_xforms(prog, view, nm, proj)
        self._set_orbital_uniforms(prog)
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
        """等值面透明回退（Depth peeling 关闭时）：逐三角形画家算法。

        按视图深度从远到近绘制（远的先画、近的盖上来）——与 Depth peeling
        （IboView 移植）的合成方向一致，近处表面占主导：透明度越高越接近
        Depth peeling 的观感，不会出现"后方的等值面反客为主透到前面"。

        性能：三角形世界系中心缓存（表面不变不重算）；相机不变时跳过
        排序与索引上传，仅保留两次绘制，旋转时才做 CPU 排序。
        """
        if self._esp_point_mode:
            return  # PT 点云模式：不渲染透明三角面
        glEnable(GL_DEPTH_TEST); glDepthFunc(GL_LESS)
        glDepthMask(GL_FALSE)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glUseProgram(self._prog_orb)
        self._set_xforms(self._prog_orb, view, nm, proj)
        self._set_orbital_uniforms(self._prog_orb)

        # 世界系三角形中心缓存：仅当表面或网格代际变化时重算。
        # 网格每次 upload() 代际 +1（含颜色/风格变化触发的重传），
        # 保证重传后必重建缓存并重传排序索引，避免画到已删除的缓冲。
        mesh_key = (id(self._pos_surf), self._meshes[0]._gen,
                    id(self._neg_surf), self._meshes[1]._gen)
        if getattr(self, "_fb_mesh_key", None) != mesh_key:
            self._fb_mesh_key = mesh_key
            self._fb_parts = []
            # 表面/网格重建后 scratch EBO 已删，必须强制重传排序索引
            self._fb_view_key = None
            self._fb_orders = []
            for mi in (0, 1):
                surf = self._pos_surf if mi == 0 else self._neg_surf
                mesh = self._meshes[mi]
                if mesh.count == 0 or surf is None:
                    continue
                idx = getattr(surf, "indices", None)
                verts = getattr(surf, "vertices", None)
                if idx is None or verts is None or len(idx) == 0 or len(verts) == 0:
                    continue
                idx = np.asarray(idx, dtype=np.uint32)
                tri = idx[:len(idx) // 3 * 3].reshape(-1, 3)
                ctr = np.asarray(verts, dtype=np.float32)[tri].mean(axis=1)
                self._fb_parts.append((mesh, tri, ctr))

        # 视图变化时才排序 + 上传索引；不变时直接绘制上一帧的排序结果
        try:
            view_key = view.tobytes()
        except Exception:
            view_key = None
        if view_key is not None and getattr(self, "_fb_view_key", None) != view_key:
            new_orders = []
            v = np.asarray(view, dtype=np.float32)
            m3 = v[:3, :3].T            # 旋转矩阵转置（行向量投影用）
            t3 = v[:3, 3]
            try:
                for mesh, tri, ctr in self._fb_parts:
                    z = ctr @ m3[:, 2] + t3[2]          # 视图深度（远 = 更负）
                    order = np.argsort(z, kind='stable')  # 远 → 近（远的先画）
                    ordered = np.ascontiguousarray(tri[order].ravel(), dtype=np.uint32)
                    mesh.upload_order(ordered)
                    new_orders.append((mesh, order.size))
            except Exception:
                # 排序/上传失败：不更新 key，保持上一帧完整排序结果可绘制
                pass
            else:
                self._fb_view_key = view_key
                self._fb_orders = new_orders
        for mesh, n_tri in getattr(self, "_fb_orders", ()):
            mesh.draw_order_range(0, n_tri)
        glDepthMask(GL_TRUE)

    def _set_xforms(self, prog, view, nm, proj):
        glUniformMatrix4fv(glGetUniformLocation(prog, 'u_ModelView'), 1, GL_TRUE, view)
        glUniformMatrix3fv(glGetUniformLocation(prog, 'u_NormalMatrix'), 1, GL_TRUE, nm)
        glUniformMatrix4fv(glGetUniformLocation(prog, 'u_Projection'), 1, GL_TRUE, proj)

    def _set_regs(self, prog, regs):
        loc = [glGetUniformLocation(prog, f'ShaderReg{i}') for i in range(4)]
        for i in range(4):
            glUniform1f(loc[i], regs[i])

    def set_iboview_uniforms(self, prog, regs, diffuse,
                             ambient=0.0, spec_color=(1.0, 1.0, 1.0),
                             spec_mul=1.0, fx=0, fx_strength=0.0,
                             fx_color=(1.0, 1.0, 1.0)):
        """Upload the IboView shader registers, fade parameters, DiffuseColor
        and the extended material uniforms (emissive ambient / tinted specular /
        orbital FX).

        DiffuseColor is kept white for orbitals so that v_Color (the green/red
        phase colour) alone determines the hue, exactly as in IboView where the
        per-vertex colour carries the phase and DiffuseColor.a is the opacity.
        """
        self._set_regs(prog, regs)
        glUniform1f(glGetUniformLocation(prog, 'FadeBias'), self._sp['FadeBias'])
        # 景深雾化开关：关闭时 FadeWidth=0（无任何雾化），开启时用 IboView 默认值
        fade_w = self._sp['FadeWidth'] if self._fade_enabled else 0.0
        glUniform1f(glGetUniformLocation(prog, 'FadeWidth'), fade_w)
        glUniform4f(glGetUniformLocation(prog, 'DiffuseColor'), *diffuse)
        glUniform1f(glGetUniformLocation(prog, 'u_Ambient'), ambient)
        glUniform4f(glGetUniformLocation(prog, 'u_SpecColor'),
                    spec_color[0], spec_color[1], spec_color[2], 0.0)
        glUniform1f(glGetUniformLocation(prog, 'u_SpecMul'), spec_mul)
        glUniform1i(glGetUniformLocation(prog, 'u_Fx'), fx)
        glUniform1f(glGetUniformLocation(prog, 'u_FxStrength'), fx_strength)
        glUniform3f(glGetUniformLocation(prog, 'u_FxColor'),
                    fx_color[0], fx_color[1], fx_color[2])
        # 光源：方向（4 盏）+ 数量 + 光晕（u_MvGrad=0 时 calc_base_color 用前 3 盏）
        ld = getattr(self, "_light_dirs", None) or getattr(self, "_light_default_dirs", None) or [
            (0.5, 0.5, 0.70710678), (-0.4330127, -0.25, 0.8660254),
            (0.4330127, -0.25, 0.8660254), (0.0, 0.0, 1.0)]
        glUniform1f(glGetUniformLocation(prog, 'u_UseCustomLights'), 1.0)
        for i in range(4):
            d = ld[i] if i < len(ld) else (0.0, 0.0, 1.0)
            glUniform3f(glGetUniformLocation(prog, f'u_L{i}'), d[0], d[1], d[2])
        glUniform1i(glGetUniformLocation(prog, 'u_LightCount'),
                    getattr(self, "_light_count", 3))
        glUniform1f(glGetUniformLocation(prog, 'u_Glow'),
                    getattr(self, "_light_glow", 1.0))
        glows = getattr(self, "_light_glows", None) or [1.0] * 4
        while len(glows) < 4:
            glows = list(glows) + [1.0]
        glUniform4f(glGetUniformLocation(prog, 'u_Glows'),
                    glows[0], glows[1], glows[2], glows[3])

    def _set_orbital_uniforms(self, prog):
        """Upload orbital material uniforms (registers + extended FX channels)."""
        sp = self._sp
        self.set_iboview_uniforms(
            prog, sp['o_reg'],
            diffuse=(1.0, 1.0, 1.0, sp['opacity']),
            ambient=sp.get('ambient', 0.0),
            spec_color=sp.get('spec_color', (1.0, 1.0, 1.0)),
            spec_mul=sp.get('spec_mul', 1.0),
            fx=sp.get('fx', 0),
            fx_strength=sp.get('fx_strength', 0.0),
            fx_color=sp.get('fx_color', (1.0, 1.0, 1.0)),
        )
        # MolViewer 单光点（u_MvGrad>0 时等值面也走 mv_orb_color）
        self._set_mv_grad_uniform(prog, self._mv_grad)
        # 等值面剪影描边
        self._set_orb_outline_uniforms(prog)

    def _set_atom_outline_uniforms(self):
        """Push the current atom-outline state into the atom shader program."""
        p = self._prog_atom
        glUniform1f(glGetUniformLocation(p, 'u_Outline'),
                    1.0 if self._atom_outline else 0.0)
        oc = self._atom_outline_color
        glUniform3f(glGetUniformLocation(p, 'u_OutlineColor'), oc[0], oc[1], oc[2])
        glUniform1f(glGetUniformLocation(p, 'u_OutlineWidth'), self._atom_outline_width)

    def _set_vdw_outline_uniforms(self):
        """Push the vdW-shell outline state (independent of atom outline)."""
        p = self._prog_atom
        glUniform1f(glGetUniformLocation(p, 'u_VdwOutline'),
                    1.0 if self._vdw_outline else 0.0)
        oc = self._vdw_outline_color
        glUniform3f(glGetUniformLocation(p, 'u_VdwOutlineColor'), oc[0], oc[1], oc[2])
        glUniform1f(glGetUniformLocation(p, 'u_VdwOutlineWidth'), self._vdw_outline_width)

    def _set_atom_mv_uniforms(self, on=True):
        """把 MolViewer 径向渐变类型写入原子着色器。

        on=False 时强制 u_MvGrad=0（选中标记等非球棍几何仍用 IboView Phong）。
        """
        self._set_mv_grad_uniform(self._prog_atom, self._mv_grad if on else 0)

    def _set_atom_ring_uniforms(self, on=True):
        """把十字圆环状态（开关/颜色/带宽 + 两条环面法线）写入原子着色器。

        法线：locked=False（默认）→ 世界系环法线随相机旋转（环随分子转）；
        locked=True → 直接用视图系法线（环固定在屏幕，分子旋转圆环不动）。
        """
        p = self._prog_atom
        glUniform1f(glGetUniformLocation(p, 'u_Rings'),
                    1.0 if (self._crosshair and on) else 0.0)
        rc = self._ring_color
        glUniform3f(glGetUniformLocation(p, 'u_RingColor'), rc[0], rc[1], rc[2])
        glUniform1f(glGetUniformLocation(p, 'u_RingWidth'), self._ring_width)
        nA = _ring_normal(self._ring_az1, self._ring_tilt1)
        nB = _ring_normal(self._ring_az2, self._ring_tilt2)
        if self._ring_locked:
            # 锁定：用冻结的当前角度（分子旋转不变）
            if getattr(self, "_ring_frozen", None) is None:
                self._refresh_ring_frozen()
            nAv, nBv = self._ring_frozen
        else:
            R = self.cam.view()[:3, :3]  # 世界系 → 视图系：环随分子转
            nAv = R @ nA
            nBv = R @ nB
        for i, nv in enumerate((nAv, nBv)):
            nv = nv / (np.linalg.norm(nv) + 1e-12)
            glUniform3f(glGetUniformLocation(p, 'u_RingN%d' % (i + 1)),
                        nv[0], nv[1], nv[2])

    def _set_mv_grad_uniform(self, prog, grad_id):
        """把一个程序的 u_MvGrad uniform 设为渐变类型 id（0=IboView 三灯）。"""
        if prog:
            glUniform1i(glGetUniformLocation(prog, 'u_MvGrad'), int(grad_id))

    def _set_orb_outline_uniforms(self, prog):
        """把等值面描边状态写入轨道着色器程序。"""
        if not prog:
            return
        glUniform1f(glGetUniformLocation(prog, 'u_OrbOutline'),
                    1.0 if self._orb_outline else 0.0)
        oc = self._orb_outline_color
        glUniform3f(glGetUniformLocation(prog, 'u_OrbOutlineColor'), oc[0], oc[1], oc[2])
        glUniform1f(glGetUniformLocation(prog, 'u_OrbOutlineWidth'),
                    self._orb_outline_width)

    # ── Mouse ──

    def wheelEvent(self, e): self.cam.zoom(e.angleDelta().y()); self.update()
    def keyPressEvent(self, e):
        if e.key() == Qt.Key_R: self.reset_view()
        elif e.key() == Qt.Key_S and self._cube:
            p, _ = save_file(self, "Save", "screenshot.png", "PNG (*.png)")
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
            QPushButton#LoadBtn { background: #1a6fc4; border-color: #1a6fc4; color: #ffffff; font-size: 14px; padding: 8px; }
            QPushButton#LoadBtn:hover { background: #2080e0; }
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
        p, _ = open_file(self, "选择 Cube 文件", "",
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
        p, _ = save_file(self, "Save", "cub_view.png", "PNG (*.png)")
        if p: self.glw.screenshot(p)

    def _export_image(self):
        p, _ = save_file(self, "Export", "cub_view.png", "PNG (*.png)")
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

# 独立启动入口已移至项目根目录的 cubviewer.py。
# 请用: python cubviewer.py
if __name__ == "__main__":
    print("请运行项目根目录下的 cubviewer.py", file=sys.stderr)
    sys.exit(1)
