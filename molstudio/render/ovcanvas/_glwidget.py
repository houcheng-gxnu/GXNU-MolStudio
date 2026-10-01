"""
cub_viewer.py — 独立 .cub 文件可视化工具
==========================================
独立运行: python cubviewer.py（项目根目录）
或拖放 .cub 文件到窗口。

MolStudio 的 OpenGL 渲染内核：
depth-peeling 顺序无关透明 + 多灯 Phong 光照 + 景深雾化。

──────────────────────────────────────────────────────────────────
来源与授权声明（GPLv3 §5(a)(b)(c)）
──────────────────────────────────────────────────────────────────
本文件是 IboView 的衍生作品（derivative work），依 GNU GPLv3 发布：

    Based on IboView (Copyright (c) 2015 Gerald Knizia), GPLv3 — modified.

取自 IboView（其源文件均为 GPLv3）的内容，逐项标注见各表/各着色器上方注释：
  * _GLSL_COMMON 光照/雾化着色器与材质/光泽参数 — 已语义化重写（命名/结构/数值全部自定）
  * 成键判定 GenerateBonds 启发式   — 公式移植自 IboView（实现自写）

已移除/替换为独立实现（历史，供追溯）：
  * 原子/共价半径表            → Cordero 2008 共价半径（2026-09-03）
  * IboView 移植的 depth-peeling 路径（FRAG_ORB_DP / FRAG_COMBINE_DP）
                             → 2026-09-03 整条删除，透明合成先由自研 WBOIT
                               （McGuire & Bavoil 2013）承担；此后又以**独立实现**
                               的 depth peeling（Everitt 2001，见 FRAG_PEEL_ORB /
                               PeelTargets 注释）重新加入为可选路径，与 IboView 表达无关。

本项目独立来源、与 IboView 无关的内容：
  * _VDW_RADII_A 范德华半径            — Bondi (1964) 公开数据
  * _CPK_COLORS / _GVIEW_COLORS 等配色 — Jmol/CPK、GaussView、MolCanvas（课题组自研）
  * 几何生成、渲染主循环、分块高分导出、MolViewer 球体渐变等

移植前原版完整保留在 ovcanvas/_glwidget_iboview.py（含原始版权头）。
各来源的逐项判定与重写进度见 docs/iboview_transplant_audit.md。

This file is part of MolStudio and is distributed under the terms of the
GNU General Public License version 3 (GPLv3). Note: IboView is GPLv3-only
(its headers say "version 3", not "or later"), so this work must not be
re-declared as "GPLv3 or later" while it still contains IboView code.
──────────────────────────────────────────────────────────────────
"""

import ctypes
import math
import os
import sys
import threading
import time
import types
import numpy as np
import traceback

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QComboBox, QPushButton, QSlider,
    QGroupBox, QFileDialog, QMessageBox, QGridLayout, QCheckBox, QListView,
)
from PyQt5.QtCore import (
    Qt, QPoint, QTimer, QRectF, QPointF, QSize, QRect, pyqtSignal,
    QBuffer, QIODevice, QByteArray,
)
from PyQt5.QtGui import (
    QDoubleValidator, QSurfaceFormat, QImage, QImageWriter,
    QPainter, QColor, QPen, QBrush, QLinearGradient,
    QRadialGradient, QFont, QFontMetrics, QFontMetricsF, QPainterPath,
)

# ── OpenGL imports ──
try:
    from OpenGL.GL import *
    from OpenGL.GLU import *
    _HAS_GL = True
except ImportError:
    _HAS_GL = False

# WBOIT 需要"逐绘制缓冲的混合函数"（per-draw-buffer blend）。
# glBlendFunci 是 GL 4.0 核心，但在 3.3 上下文里通常通过
# GL_ARB_draw_buffers_blend 提供；两者都不可用时 WBOIT 自动停用。
try:
    from OpenGL.GL import glBlendFunci as _glBlendFunci
except ImportError:
    try:
        from OpenGL.GL.ARB.draw_buffers_blend import (
            glBlendFunciARB as _glBlendFunci)
    except ImportError:
        _glBlendFunci = None

from PyQt5.QtWidgets import QOpenGLWidget

from molstudio.ui.file_dialogs import open_file, save_file

# ── Cube file + marching cubes ──
from molstudio.core.marching_cubes import (
    read_cube, marching_cubes, IsoSurface, CubeData, compute_bounding_sphere,
    relative_iso_threshold,
)

# ── Styles ──
from molstudio.core.fchk_orbital import STYLES, ELEMENT_SYMBOLS

STYLE_NAMES = list(STYLES.keys())
STYLE_DISPLAY = [f"{k}  — {STYLES[k]['desc']}" for k in STYLES.keys()]

# ═══════════════════════════════════════════════════════════════
# 多点光照（GGX 微表面 + Schlick 菲涅尔）的材质默认值与光泽预设。
#
# 渲染器通过每条渲染路径的 4 个标量材质参数驱动光照
# （a* = 不透明原子/键，o* = 等值面）：
#   [0] = 漫反射指数 u_DiffusePow，[1] = 漫反射强度 u_DiffuseStr，
#   [2] = 镜面强度 u_SpecStr，[3] = 镜面锐度 u_SpecSharp（GGX 下不再使用，保留兼容）。
#
# 数值为本项目自定：漫反射指数 0.85（比 Lambert 稍柔和的阴影过渡）、
# 漫反射强度 0.70；镜面由 gloss 经 _apply_gloss 写入 [2]，高光形状由
# 独立 uniform u_Roughness（GGX 粗糙度，默认见 style_params）决定。
# ═══════════════════════════════════════════════════════════════
_REG_DEFAULT_A = [0.85, 0.70, 0.50, -0.50]   # default opaque (atoms)
_REG_DEFAULT_O = [0.85, 0.70, 0.80, -0.50]   # default orbital (used by style_params)

# 经典三点布光（视图空间单位向量）：一盏主光从右上前打来，两盏补光分居下方
# 两侧形成立体感。方向为项目自定的通用摄影布光布局。
_PHONG_LIGHT_DIRS = (
    (0.50, 0.50, 0.7071),      # 主光 key：右上前 45°
    (-0.40, -0.35, 0.8470),    # 补光 fill：左前下
    (0.45, -0.30, 0.8410),     # 轮廓光 rim：右下
    (0.0, 0.0, 1.0),           # 第 4 盏备用：正对
)

# 各灯的固定强度权重。**必须与 `_GLSL_COMMON` 里 light_contrib 调用的
# intensity 表达式保持一致**（那边是硬编码的 1.0/0.58/0.48/0.38，因为
# GLSL 里的 `{` 是块语法、不能用 f-string 插值），改一处就要改另一处。
#
# 能量归一化：历史上各灯贡献是简单累加且不做归一，于是「灯数越多越亮」
# （1/2/3/4 灯总强度 = 1.00/1.58/2.06/2.44），减灯数会连带整体变暗。
# 现在把总能量折算到一个固定基准，让增减灯数只改变布光层次。
# 基准取默认 3 灯（2.06）→ 默认观感零变化，只有改灯数时才重新分配。
_LIGHT_WEIGHTS = (1.0, 0.58, 0.48, 0.38)
_LIGHT_NORM_REF = float(sum(_LIGHT_WEIGHTS[:3]))    # 2.06 = 默认 3 灯基准


def _light_norm_factor(count):
    """把 count 盏灯的总能量折算回 _LIGHT_NORM_REF 所需的系数。"""
    n = max(1, min(4, int(count)))
    w = float(sum(_LIGHT_WEIGHTS[:n]))
    return _LIGHT_NORM_REF / w if w > 0.0 else 1.0

# 光泽（gloss）连续值：0..1 → 镜面强度 0.30（下限，原 "not very shiny"）
# ～ 2.00（上限，原 "sooooo shiny"）。等值面与原子统一，不再额外放大。
_GLOSS_DEFAULT = 0.06    # 默认光泽（原 "reasonably shiny" 档；见 _GLOSS_SPEC_MAX）

# gloss(0..1) → 镜面强度槽的直接映射：0 = 纯哑光，1 = 明显高光。
# 历史映射是 0.30..2.00 的仿射（哑光端仍留着 0.30 的基础镜面），与新的
# SPEC_ENERGY 增益叠加后默认观感会明显偏亮；改成从 0 起算的线性映射后，
# 默认 gloss 对应的实际高光强度与旧版基本一致，而滑块上端能给出清晰高光。
_GLOSS_SPEC_MAX = 1.0

# ── SSAO 质量参数 ───────────────────────────────────────────────
# AO 图分辨率低于输出分辨率时，上采样会把"每像素随机旋转采样"的噪声放大成
# 可见的方块（实测哑光观感下折痕残差 1.4%，关掉 AO 只有 0.05%）。三处缓解：
#   _AO_SAMPLES        每个 AO 像素的采样数（越大噪声越小）
#   _AO_BLUR_SPACING   后处理去噪的采样间距（AO 纹素，>1 = 更宽的模糊）
#   _AO_RES_SCALE      AO 缓冲分辨率 / 超采样渲染分辨率（0.5 = 原行为）
_AO_SAMPLES = 32
_AO_BLUR_SPACING = 1.0
_AO_RES_SCALE = 0.5
_AO_GAIN = 8.0           # 归一化增益（切平面判据已滤掉假遮挡，故比早前更大）
_AO_TANGENT_BIAS = 0.35  # 切平面判据阈值（越大越严格，越不容易出假遮挡）

# 样式可用的镜面模型名 → u_SpecModel 取值（STYLES 里用 'gl_model' 指定）
_SPEC_MODEL_BY_NAME = {
    "blinn": 0,       # IboView 原版双瓣高光
    "ggx": 1,         # 现代微表面（默认）
    "clearcoat": 2,   # 双层清漆
    "matcap": 3,      # 材质球
}

# 历史光泽预设名 → gloss 值（旧样式文件兼容）。
_LEGACY_SHININESS_TO_GLOSS = {
    "not very shiny": 0.0,       # 镜面 0.30
    "reasonably shiny": 0.118,   # 镜面 0.50
    "extra shiny": 0.44,         # 镜面 1.05
    "sooooo shiny": 1.0,         # 镜面 2.00
    "soft satin": 0.353,         # 镜面 0.90
    "cgk's shiny chic '21": 0.353,
}

# ── Atomic/molecular drawing data ────────────────────────────────
# Empirical sphere draw-radii (length 104, index = element Z, entry 0 dummy).
#
# SOURCE: IboView — src/IboView/IvDataOptions.cpp :: AtomicRadii[104]
#         (Copyright (c) 2015 Gerald Knizia, GPLv3).
#         All 104 values are identical to the IboView table. This table is
#         NOT the Bondi 1964 / Alvarez / Batsanov / Cordero compilation —
#         replacing it with an independent source is tracked as item 1.3 in
#         docs/iboview_transplant_audit.md and is NOT yet done.
#
# These are vdW-type empirical radii; the metal-specific shrink applied on
# top of them is this project's own (see _atom_base_radius()).

# `_DRAW_RADII` 不再逐字抄表，改由 Cordero 共价半径表 × COV_TO_DRAW 导出，
# 定义位置在 _COV_RADII_BOHR 之后（依赖它）。见那里的完整说明。

# ── 金属原子球缩放 ────────────────────────────────────────
# 按 vdW 比例绘制时金属球普遍过大（Cs、K 等），球棍模型里显得臃肿。
# 金属按 _METAL_RADIUS_FACTOR 缩小，并用 _METAL_MIN_RADIUS 兜底，
# 保证金属球仍大于常见非金属，不破坏「金属 ≥ 非金属」的直觉。
#
# 下限 2.15 仍沿用原值：现在常见非金属的绘制半径最大约 1.83（I，
# 2.15 Å × 0.85），金属统一落在下限上，既满足上述不变量，又使金属球
# 的**实际绘制尺寸与改动前完全一致**（旧表也是全部顶到该下限）。
_METAL_RADIUS_FACTOR = 2.0 / 3.0
_METAL_MIN_RADIUS = 2.15

# 金属元素（碱/碱土/过渡/后过渡/镧系/锕系）。类金属 B/Si/Ge/As/Se/Sb/Te
# 不参与缩放，保持原值。
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
    """原子绘制基础半径：金属缩小 1/3 并设下限，非金属用原值。

    输入 _DRAW_RADII 现由 Cordero 共价半径 × COV_TO_DRAW 导出（见该处说明）。
    金属：max(原值 × 2/3, 2.15) —— 绝大多数金属实际落在下限上。
    越界元素回退到 0.4。
    """
    if 0 <= anum < len(_DRAW_RADII):
        r = _DRAW_RADII[anum]
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


def _hex_to_rgb(c):
    return ((c >> 16) & 0xff) / 255.0, ((c >> 8) & 0xff) / 255.0, (c & 0xff) / 255.0


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
# ══════════════════════════════════════════════════════════════════
# 单键共价半径（Cordero et al., Dalton Trans. 2008, 2832–2838），单位 **Bohr**
# ──────────────────────────────────────────────────────────────────
# 早期版本逐字沿用 IboView 的 g_CovalentRadii：110 项中 108 项数值全等，
# 且该表并非 Cordero / Pyykkö 的公开汇编，而是 IboView 自用的经验值。
#
# 现改用 Cordero 2008 的单键共价半径（文献表，Å），换算为 Bohr 后按 Z 索引。
# 数据来源：本仓库 etsnocv/config.py 的 ATOM_RADII（课题组已有的 Cordero
# 副本）。为避免 ovcanvas 反向依赖顶层模块，此处按 Z 固化一份；生成时用
# ELEMENT_SYMBOLS 前 54 号做过顺序交叉校验，103 项无缺失。
#
# 与旧表的差异（Å）：H 0.380→0.310、F 0.710→0.570、O 0.730→0.660、
# N 0.750→0.710，其余多在 ±8% 内。H/F 变小会减少含氢/氟的假键，
# 属 Literature 标准值带来的改进。Z ≥ 104 用 3.2 Bohr 兜底。
#
# `.cub` 坐标为 Å，故这些 Bohr 值直接用于成键判定：
#   r_ij <= 0.5 * (bf_i + bf_j) * (cov_i + cov_j)  ⇒  bond
# （bf 默认 1.32；判据本身是通用化学启发式，数据表现为 Cordero 2008。）
# ══════════════════════════════════════════════════════════════════
_COV_RADII_BOHR = [
    0.0,                                                            # 0
    0.5858, 0.5291, 2.4188, 1.8141, 1.5874, 1.4362, 1.3417, 1.2472, 1.0771, 1.0960,  # 1-10
    3.1369, 2.6645, 2.2866, 2.0976, 2.0220, 1.9842, 1.9275, 2.0031, 3.8361, 3.3259,  # 11-20
    3.2125, 3.0236, 2.8913, 2.6267, 2.6267, 2.4944, 2.3811, 2.3433, 2.4944, 2.3055,  # 21-30
    2.3055, 2.2677, 2.2488, 2.2677, 2.2677, 2.1921, 4.1574, 3.6850, 3.5905, 3.3070,  # 31-40
    3.0992, 2.9102, 2.7779, 2.7590, 2.6834, 2.6267, 2.7401, 2.7212, 2.6834, 2.6267,  # 41-50
    2.6267, 2.6078, 2.6267, 2.6456, 4.6109, 4.0629, 3.9117, 3.8550, 3.8361, 3.7983,  # 51-60
    3.7606, 3.7417, 3.7417, 3.7039, 3.6661, 3.6283, 3.6283, 3.5716, 3.5905, 3.5338,  # 61-70
    3.5338, 3.3070, 3.2125, 3.0614, 2.8535, 2.7212, 2.6645, 2.5700, 2.5700, 2.4944,  # 71-80
    2.7401, 2.7590, 2.7968, 2.6456, 2.8346, 2.8346, 4.9133, 4.1763, 4.0629, 3.8928,  # 81-90
    3.7795, 3.7039, 3.5905, 3.5338, 3.4015, 3.1936, 3.7795, 3.7795, 3.7795, 3.7795,  # 91-100
    3.7795, 3.7795, 3.7795,                                         # 101-103
    3.2, 3.2, 3.2, 3.2, 3.2, 3.2,                                   # 104-109 兜底
]
_COV_RADII = [r * BOHR_TO_ANGSTROM for r in _COV_RADII_BOHR[:110]]

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

# ══════════════════════════════════════════════════════════════════
# 绘制半径（本项目自定）：由上面的 Cordero 共价半径表导出
# ──────────────────────────────────────────────────────────────────
# 早期版本逐字沿用 IboView 的 AtomicRadii[104]（104/104 全等）。该表是
# IboView 自己的经验取值——既非 vdW 也非共价半径的常数倍，无法从任何公开
# 表推出，只能照抄。
#
# 现改为：绘制半径 = Cordero(2008) 共价半径 × COV_TO_DRAW
#   · 唯一的人为数值是 COV_TO_DRAW 这一个系数，属本项目自定；
#   · 元素数据全部来自已在本文定义的公开 Cordero 表；
#   · 共价半径本身随 Z 的化学变化（Cs 2.44、I 1.39、C 0.76、H 0.31）合理，
#     球大小因此具有化学意义，而不像 vdW 方案那样把重元素压成同一档。
#
# 系数按"碳落回旧表的 1.43"标定，故整体球大小与改动前一致，ATOM_DRAW_SCALE
# 无需调整。相对碳的半径比例与旧表的偏差（实测）：
#   C/N/O/P/S/Cl/Br/I 及多数金属  ±5% 以内
#   F  -15%    H  -33%（H 画得更小；共价半径本就如此，多数分子查看器亦然）
#
# 曾试过 Bondi vdW 方案，但仓库内 _VDW_RADII_A 对重元素被压缩（Cs 仅 2.15 Å，
# Bondi 原值 3.43），导致 P/S/Cl/Br/I 与碱金属缩小 20%~63%，已弃用。
# ══════════════════════════════════════════════════════════════════
COV_TO_DRAW = 1.43 / _COV_RADII_BOHR[6]     # 以碳为基准标定（碳 → 1.43）
_DRAW_RADII = [0.0] + [r * COV_TO_DRAW for r in _COV_RADII_BOHR[1:104]]

# 氢原子球放大（本项目自定的**显示**系数，只改绘制半径表这一项）。
# Cordero 的 H 单键共价半径只有 0.31 Å，按共价比例画出的 H 球相对碳仅 0.41，
# 球棍模型里几乎看不见。这里给 H 单独 ×1.5（H/C ≈ 0.61，绝对值 0.875 与
# 改动前旧表的 0.87 基本一致）。
# 注意：成键判定走的是 _COV_RADII_BOHR，本系数不参与，故不会多判出假键；
# 范德华半径走 _VDW_RADII_A，同样不受影响。
HYDROGEN_DRAW_SCALE = 1.5
_DRAW_RADII[1] *= HYDROGEN_DRAW_SCALE


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

# Drawing scales: the empirical draw-radii table above and the covalent
# radii share the same internal (Bohr-like) units; we normalize to
# Angstrom-like units with these factors so the ball-and-stick proportions
# look right.
ATOM_DRAW_SCALE = 0.22     # sphere radius = ATOM_DRAW_SCALE * _DRAW_RADII[z]
BOND_DRAW_SCALE = 0.185    # bond radius   = BOND_DRAW_SCALE * fBondScaleOuter-equivalent
BOND_RADIUS_FACTOR = 1.32  # bond heuristic scale factor (MolStudio default)
# Absolute upper bound for bond detection (in Angstrom). Distances up to this
# value are still treated as solid bonds even if they exceed the covalent
# radius heuristic, so longer contacts show a bond. Kept modest (1.8 Å) to
# avoid over-bonding distant contacts.
BOND_MAX_DIST_ANG = 1.8
# Tighter absolute cap for bonds involving hydrogen (H only bonds to its
# nearest heavy atom, C-H ≈ 1.09 Å), preventing distant H…X contacts.
BOND_MAX_DIST_H_ANG = 1.3
BOND_THINNING_DEFAULT = 0.70   # bond narrows to 70% of its radius at the midpoint
                               # (runtime-adjustable; MolStudio default)
# ── 多重键（双键/三键/离域键）几何参数 ──────────────────────────────
# 由右键菜单逐键指定（'double' / 'triple' / 'deloc'），不参与自动判定。
#   MULTI_BOND_RADIUS_DEFAULT：每根子键的半径 = 该系数 × 单键半径。
#     默认 1.0 —— **子键与普通单键等粗**：双键读起来就是"两根一样粗的键
#     并排"，与化学制图习惯一致（早期默认 0.58 偏细，已按诉求调整）。
#   MULTI_BOND_GAP_DEFAULT：相邻子键中心距 = 该系数 × 子键半径。
#     子键等粗后必须同步放大中心距，否则两根线会贴成一根粗线：
#     净空 = (gap − 2) × 子键半径，默认 3.0 时净空 = 1 倍子键半径
#     （= 半条线宽），两根线清晰可分且不散。
MULTI_BOND_RADIUS_DEFAULT = 1.00
MULTI_BOND_GAP_DEFAULT = 3.00
# 键圆柱的分段数（环向边数）。**唯一来源**：改这里就等于改所有键几何的
# 顶点数，`_multibond_probe.py` 也从它推导期望值 —— 免得两边各写一个魔法数、
# 调整分段时探针假失败。
# 曾用 12；因放大与高清导出时圆柱轮廓/反光亮带的棱可见，提到 24。
# 顶点数公式：一段锥形/端盖圆柱 = 2 * BOND_CYL_SEG（锥形，两圈）、
#             4 * BOND_CYL_SEG + 2（带两端盖）；单键 = 两段。
BOND_CYL_SEG = 24
# 多重键子键端点相对键长的内缩比例（避免细圆柱戳进两端原子球）。
# 实际取 min(MULTI_BOND_INSET_FRAC * 键长, MULTI_BOND_INSET_R × 子键半径)。
MULTI_BOND_INSET_FRAC = 0.16
MULTI_BOND_INSET_R = 2.20
# 离域键（1.5 键 / 芳香键）：实线 + 虚线并列，两条线都与单键等粗。
# 与双键共用 MULTI_BOND_RADIUS/GAP 参数，只是其中一根线画成点阵虚线。
DELOC_BOND_ORDER = 1.5
# 离域键那根虚线（点阵）的点半径 / 子键半径。
# 普通虚线键的点很小（0.45 × 键半径，读作"残缺/部分键"）；与等粗实线并排时
# 会显得一粗一细，故离域键的点放大到 0.70 × 子键半径——两条线观感等重，
# 又留出足够间隙仍读得出是虚线。用户仍可用面板「虚线大小」整体微调。
DELOC_DASH_DOT_R = 0.70
# ── 虚线样式 ────────────────────────────────────────────────────────
#   'dots'   小圆球点阵（细点，读作"部分键/配位键"，本项目既有画法，默认）
#   'dashes' 短圆柱段（真正的虚线：与实线等粗、一段一段排开，像二维结构式）
# 普通虚线键与离域键的那根虚线共用这个设置。
DASH_STYLE_DOTS = 'dots'
DASH_STYLE_DASHES = 'dashes'
DASH_STYLE_NAMES = (DASH_STYLE_DOTS, DASH_STYLE_DASHES)
DASH_STYLE_DEFAULT = DASH_STYLE_DOTS
# ── 成键模式（两类）────────────────────────────────────────────────
#   'single' 一律单键：检测到的键全部画成实线单键（本项目既有行为，默认）
#   'auto'   按键长自动判定键型：用键长相对"单键共价半径和"的比例 q 分档，
#            推出 单键 / 离域键(1.5) / 双键 / 三键。右键逐键指定的键型优先，
#            不受模式影响。
BOND_MODE_SINGLE = 'single'
BOND_MODE_AUTO = 'auto'
BOND_MODE_NAMES = (BOND_MODE_SINGLE, BOND_MODE_AUTO)
BOND_MODE_DEFAULT = BOND_MODE_SINGLE

# 自动判定分档阈值（q = 键长 / (r_i + r_j)，Cordero 单键共价半径）：
#   q ≥ 0.96           单键     （C–C 1.01、C–O 1.01、C–N 1.00）
#   0.90 ≤ q < 0.96   离域键 1.5（苯 C–C 0.914、酰胺 C–N 0.918）
#   0.80 ≤ q < 0.90    双键     （C=C 0.882、C=O 0.866、C=N 0.871、N=O 0.883、
#                                CO2 0.817——故三键档必须压到 0.80 以下）
#   q < 0.80           三键     （C≡C 0.789、C≡N 0.789、N≡N 0.775）
BOND_Q_SINGLE = 0.96
BOND_Q_DELOC = 0.90
BOND_Q_DOUBLE = 0.80
# 自动判定只对这几个元素的成键生效：C/N/O 的"键长-键级"关系标定得最稳。
# S/P/金属常有 d 轨道或配位效应（S=O 比值 0.918、P=O 0.855，都会被误判成
# 双键/三键），含 H 的键本来就只能是单键，卤素/硼等也缺少可靠标定，
# 故这些一律按单键处理（用户仍可用右键逐键指定）。
BOND_AUTO_ELEMENTS = (6, 7, 8)

# MolStudio renderer default properties (view / isosurface / fog).
#
# 取值均为本项目自定默认值；景深雾化用语义化的 FogWidth/FogBias（斜率/偏移）。
#   · IsoResolution / IsoThreshold —— 等值面相对阈值语义（见下方说明）
#   · FogWidth / FogBias —— 景深雾化斜率与偏移
#   · OrbitalOpacity 等 —— 本项目自定默认值
_RENDER_DEFAULTS = {
    'IsoResolution': 12.0,
    'IsoThreshold': 80.0,       # *relative* threshold, in percent (see below)
    # 景深雾化：物体**最后面**向背景色淡出的比例，0..2。
    #   0.6 = 最深处融入背景 60%（默认，明显可见的空气透视）
    #   1.0 = 最深处完全融入背景；>1 让雾在更浅的深度就饱和（更强）
    # 旧值是窗口深度坐标系下的斜率（8.0），在正交投影下等于无效；IboView
    # 原版 FadeWidth=9 约合本坐标系的 0.35（想要原版那种淡雾可调到 0.35）。
    'FogWidth': 0.60,
    'FogBias': 0.0,
    'OrbitalOpacity': 0.78,     # orbitals are semi-transparent by default
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
MOL_STYLE_NAMES = ["CPK", "VMD single", "Mono white", "Jmol", "Gray pub", "Neon", "GaussView", "HoukMol", "SobArt", "Vcube", "VESTA"]
MOL_STYLE_DISPLAY = ["CPK (按元素)", "VMD (碳金色)", "单色白", "Jmol", "灰度出版", "霓虹", "GaussView", "HoukMol", "SobArt (Chem311)", "Vcube (VMD 风格)", "VESTA (VESTA 配色)"]

# GaussView element colour palette, transcribed from gview_color.tcl
# (color change rgb 100+Z r g b; created by Tian Lu, sobereva@sina.com).
# VESTA 的元素配色（VESTA 自带 elements.ini 的原值）。
# 单独放 vesta_colors.py 是为了可追溯/可重新生成（见 _gen_vesta_table.py），
# 这里只是把它读进来当"原子配色轴"的一个选项，和 Jmol / GaussView 同级。
# 取不到时退化成空表 → 该样式下未命中元素回退 GaussView 灰。
try:
    from molstudio.render.vesta_colors import VESTA_COLORS as _VESTA_COLORS
except Exception:                      # pragma: no cover
    _VESTA_COLORS = {}

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
_JMOL_COLORS = {z: _hex_to_rgb(c) for z, c in _JMOL_COLORS_HEX.items()}

# 默认 CPK 配色：公开 Rasmol CPK-new 全元素表（Jmol homepage 标准配色，
# 经 Tian Lu 的 gview_color.tcl 转写为 0..1 浮点，覆盖元素 1–111）。
# (Full per-element CPK palette; only a few hues differ from the classic
# Rasmol CPK-new table.)
_CPK_COLORS = list(_GVIEW_COLORS.get(z, (0.5, 0.5, 0.5)) for z in range(112))

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
uniform int   u_Linear;    // 色彩空间：0 = sRGB 直通（默认，与旧版逐位一致）；1 = 线性空间光照
uniform mat4 u_ModelView;
uniform mat3 u_NormalMatrix;
uniform mat4 u_Projection;
void main() {
    gl_Position = u_Projection * (u_ModelView * vec4(in_Pos, 1.0));
    v_Normal = u_NormalMatrix * in_Normal;
    v_Color = in_Color;
    // 线性空间（可选）：顶点色（元素色/相位色，sRGB 语义）pow(2.2) 转线性，
    // 光照与透明混合全程线性域，后处理 pass 统一转回 sRGB。u_Linear=0 时直通。
    if (u_Linear > 0)
        v_Color.rgb = pow(max(v_Color.rgb, 0.0), vec3(2.2));
    v_ModelPos = in_Pos;
    v_BallId = in_BallId;
}
"""

# ── 共享 GLSL 光照/雾化脚手架 ─────────────────────────────────────
# 本项目自定的三灯 Phong + 深度雾化光照模型（教科书级 Blinn-Phong 变体）：
# 材质参数语义化命名（漫反射指数/强度、镜面强度/锐度），雾化参数独立命名，
# 掠射角 alpha 增强下限提取为具名常量。三灯方向由 Python 侧 `_light_default_dirs`
# 统一提供（见 set_shader_uniforms），着色器内不硬编码默认方向。
_GLSL_COMMON = """
in vec3 v_Normal;
in vec4 v_Color;
uniform int u_Linear;   // 0 = sRGB 直通（默认）；1 = 线性空间光照
// 线性空间下把 sRGB 语义的颜色 uniform（雾色/补光色/描边色）转线性参与混合。
// u_Linear=0 时原值直通（与旧版逐位一致）。
vec3 lp_lin3(vec3 c) {
    return (u_Linear > 0) ? pow(max(c, 0.0), vec3(2.2)) : c;
}
// ── 材质光照参数（语义化）──
uniform float u_DiffusePow;    // 漫反射指数（越大高光越集中）
uniform float u_DiffuseStr;    // 漫反射强度
uniform float u_SpecStr;       // 镜面强度
uniform float u_SpecSharp;     // 镜面锐度（Blinn-Phong 双瓣高光权重；GGX 下不使用）
uniform float u_Roughness;     // GGX 微表面粗糙度（0.03..1，越小越镜面）
uniform float u_CoatRoughness; // Clear-coat 清漆层粗糙度（0.03..1，通常很锐）
uniform float u_CoatStrength;  // Clear-coat 清漆层强度（0..~2）
uniform int   u_SpecModel;     // 镜面模型：0=Blinn-Phong，1=GGX，2=Clear-coat，3=Matcap
uniform sampler2D u_Matcap;    // Matcap 材质球（灰度 shading LUT，u_SpecModel==3 时用）
uniform float u_SssStrength;   // 次表面散射强度：0=关闭（标准 Lambert），1=最强
uniform float u_SoftTerm;      // 明暗交界线柔化：0=标准 Lambert，1=Half-Lambert
uniform float u_BackDim;       // 双面材质（轨道等值面）背面调暗系数：1.0=关，越小内壁越暗
// 半球环境光（Hemisphere Lighting）—— 世界空间上/下半球的廉价环境漫反射补光。
// 只叠加进 RGB 漫反射，不参与任何镜面项，也不触碰 alpha（故不影响 WBOIT）。
uniform int   u_HemiEnabled;    // 开关
uniform vec3  u_HemiTop;        // 天顶色（N_world 朝上）
uniform vec3  u_HemiBottom;     // 地面色（N_world 朝下）
uniform float u_HemiIntensity;  // 强度
uniform mat3  u_NormalToWorld;  // 视图空间法线 → 世界空间法线（视图旋转的转置）
uniform float u_FogBias;       // 深度雾化偏移
uniform float u_FogWidth;      // 深度雾化强度（0 = 关闭雾化）
uniform vec3  u_FogColor;      // 雾化终色（= 背景色，深色背景下不会变白）
// 视图空间线性深度换算：viewDist = u_FogDepth.x + gl_FragCoord.z * u_FogDepth.y
// （正交投影下窗口深度与视图深度是线性关系，故不必额外传 varying）
uniform vec2  u_FogDepth;      // (near, far - near)
uniform vec2  u_FogRange;      // (相机到场景中心的距离, 场景深度跨度)
uniform vec4 DiffuseColor;
uniform float u_Ambient;    // emissive / ambient term (0..~2)
uniform vec4  u_SpecColor;  // specular tint (RGB; default white)
uniform float u_SpecMul;    // specular strength multiplier (default 1)
uniform float u_AlphaMod;   // 等值面 alpha 是否被光照调制：1=调制（默认），0=直接用滑块值
uniform int   u_Fx;         // orbital material FX: 0=none, 1=neon rim, 2=pearl, 3=metal
uniform float u_FxStrength; // FX intensity (0..1)
uniform vec3  u_FxColor;    // FX auxiliary colour (rim / secondary sheen)
// 灯光方向（至多 4 盏；由 Python 侧上传）
uniform vec3  u_L0, u_L1, u_L2, u_L3;
uniform int   u_LightCount;   // active lights (1..4)
uniform float u_LightNorm;    // 灯光能量归一化系数（默认 3 灯基准下 = 1.0）
uniform float u_Glow;         // overall glow size (1.0 = default; >1 wider/softer)
uniform vec4  u_Glows;        // per-light glow sizes (u_Glows[i] for light i)

// 掠射角 alpha 增强下限：透明面剪影（|N.z|≈0）若不增强会被背景洗白，
// 该下限夹住除数、限制边缘不透明度的最大增幅。
const float SILHOUETTE_ALPHA_FLOOR = 0.12;

// 镜面能量标定系数（艺术化增益）。
// Cook-Torrance/GGX 的物理量级由 F0（电介质约 0.04）决定，算出来的高光
// 峰值只有 ~2% 亮度——"光泽/粗糙度/清漆"这几个滑块在画面上几乎测不出变化。
// 这里乘一个固定增益，把镜面通道拉到与 Blinn-Phong 双瓣高光同一量级
// （两者在同一镜面强度下观感可比），使上述滑块在完整范围内都有可见反应。
// 只作用于镜面项，不动漫反射/环境光，故不影响整体明暗。
const float SPEC_ENERGY = 8.0;

// 雾化强度：0 = 场景近端（相机与中心之间），1 = 场景远端。
// 用视图空间线性深度而不是原始窗口深度——后者的有效范围随投影 near/far
// 变化极大，在正交投影下几乎被压扁，滑块因此完全失效。
float fog_factor() {
    float viewDist = u_FogDepth.x + gl_FragCoord.z * u_FogDepth.y;
    // t：-1 = 包围球最前面，+1 = 最后面
    float t = (viewDist - u_FogRange.x) / max(u_FogRange.y, 1e-3);
    // 重映射到 0..1 铺满**整个物体深度**：前面不雾化，最后面按 u_FogWidth
    // 完全融入背景。旧写法直接用 t（在物体中心就归零），深度跨度小/可见面
    // 都在中心之前的场景里几乎看不出雾化，滑块也因此显得没力气。
    t = clamp(0.5 * (t + 1.0), 0.0, 1.0);
    return clamp(u_FogBias + u_FogWidth * t, 0.0, 1.0);
}

// 单灯贡献（GGX 微表面 + Schlick 菲涅尔，Cook-Torrance 简化）：
//   diffuse  = u_DiffuseStr * pow(NdotL, u_DiffusePow) * DiffuseColor
//   specular = u_SpecStr * (D·F·G)/(4·NdotV·NdotL) * u_SpecColor * u_SpecMul
// D = GGX/Trowbridge-Reitz 法线分布（α = roughness²）；
// F = Schlick 菲涅尔（固定电介质 F0=_F0，掠射角自然提亮到白 → 玻璃边）；
// G = Smith-Schlick 几何遮蔽近似。
// 半角向量 H = normalize(L+V)；正交投影下视图方向恒为 +Z（V=(0,0,1)）。
// `glow` 摊到有效粗糙度：光晕越大高光越宽（与 ramp 路径同向）。
const float _PI = 3.14159265358979;
const float _F0 = 0.04;          // 电介质基础反射率（越小中心高光越柔，可调）
const float _F0_RIM = 0.85;      // 掠射角菲涅尔上限（<1 让边缘不纯白，避免生硬）
vec3 spec_ggx(vec3 N, vec3 L, vec3 V, float rough) {
    vec3 H = normalize(L + V);
    float NdotL = max(dot(N, L), 0.0);
    float NdotV = max(dot(N, V), 1e-4);
    float NdotH = max(dot(N, H), 0.0);
    float VdotH = max(dot(V, H), 0.0);
    float a = max(rough * rough, 1e-4);
    float a2 = a * a;
    float dnm = NdotH * NdotH * (a2 - 1.0) + 1.0;
    float D = a2 / (_PI * dnm * dnm);
    vec3 F = vec3(_F0) + (vec3(_F0_RIM) - vec3(_F0)) * pow(1.0 - VdotH, 5.0);
    float k = a * 0.5;
    float G1 = NdotL / (NdotL * (1.0 - k) + k);
    float G2 = NdotV / (NdotV * (1.0 - k) + k);
    return (D * F * (G1 * G2)) / max(4.0 * NdotV * NdotL, 1e-4);
}

// 次表面散射近似（DICE/Frostbite "Fast Subsurface Scattering" 思路）：
//   ① Wrap lighting —— 把 NdotL 从 (−w..1) 重映射到 (0..1)，明暗交界向背光侧
//      推移、过渡拉长，这是次表面散射最典型的视觉特征（玉/蜡的柔和过渡）。
//   ② 背光透射 —— 光穿过物体后沿 −H 前进，与视线越一致越亮；掠射处（|N.z| 小）
//      视为「薄」，透射更强 → 逆光时边缘透光发亮。
// 正交投影下视线恒为 V=(0,0,1)，故 N.z 即 NdotV。
vec3 sss_translucency(vec3 N, vec3 L) {
    vec3 V = vec3(0.0, 0.0, 1.0);
    vec3 Hb = normalize(-L - N * 0.3);          // 扭曲后的透射方向
    float back = pow(clamp(dot(V, Hb), 0.0, 1.0), 4.0);
    float thin = pow(1.0 - abs(N.z), 2.0);      // 掠射 = 薄 = 透光多
    return vec3(back * thin);
}

vec4 light_contrib(vec3 N, vec3 L, float intensity, float glow) {
    float ndl_raw = dot(N, L);
    float ndl = clamp(ndl_raw, 0.0, 1.0);
    // 明暗交界线柔化（Half-Lambert，Valve 提出）：把 [-1,1] 重映射到 [0,1]，
    // 背光侧同样受光，且曲线在交界处斜率趋近 0 → 消除锐利的 terminator。
    // 只作用于漫反射，高光仍用原始 ndl（故不影响高光位置/形状）。
    // 默认 u_SoftTerm = 0 → 与改动前逐位一致。
    float ndl_half = ndl_raw * 0.5 + 0.5;
    vec4 diffuse;
    vec3 sss = vec3(0.0);
    if (u_SssStrength > 0.0) {
        // ① Wrap lighting：w 越大明暗过渡越长、越「通透」
        float ndl_wrap = clamp((ndl_raw + u_SssStrength)
                               / (1.0 + u_SssStrength), 0.0, 1.0);
        float nd = mix(ndl_wrap, ndl_half, u_SoftTerm);
        diffuse = u_DiffuseStr * pow(nd, u_DiffusePow) * DiffuseColor;
        // ② 背光透射：按物体固有色染色，alpha 恒为 0（同镜面项，否则会把
        //    等值面的透明度「顶满」导致「透明度」滑块失效）。
        sss = u_SssStrength * sss_translucency(N, L) * DiffuseColor.rgb;
    } else {
        float nd = mix(ndl, ndl_half, u_SoftTerm);
        diffuse = u_DiffuseStr * pow(nd, u_DiffusePow) * DiffuseColor;
    }
    vec3 spec;
    if (u_SpecModel == 1) {
        // GGX 微表面 + Schlick 菲涅尔（现代，散射尾宽 + 边缘菲涅尔提亮）
        float rough = clamp(u_Roughness * max(glow, 0.05), 0.03, 1.0);
        spec = SPEC_ENERGY * u_SpecStr * spec_ggx(N, L, vec3(0.0, 0.0, 1.0), rough)
             * u_SpecColor.rgb * u_SpecMul;
    } else if (u_SpecModel == 2) {
        // Clear-coat 真双层：清漆是独立电介质界面（F0=_F0），先按清漆层菲涅尔
        // 反射掉一部分能量，剩下的 (1 - coatF·strength) 才进入底层镜面 →
        // 掠射角处清漆高光自然压过底层，出现"釉质层"层次。旧版两层直接相加、
        // 底层不衰减，是 Clear-coat 与 GGX 观感几乎一样的根因。
        float base_rough = clamp(u_Roughness * max(glow, 0.05), 0.03, 1.0);
        float coat_rough = clamp(u_CoatRoughness * max(glow, 0.05), 0.03, 1.0);
        // 清漆层菲涅尔（Schlick，F0/_F0_RIM 与 spec_ggx 内部一致）兼作底层衰减因子
        vec3 Hc = normalize(L + vec3(0.0, 0.0, 1.0));
        float cVdotH = max(dot(vec3(0.0, 0.0, 1.0), Hc), 0.0);
        float coatF = _F0 + (_F0_RIM - _F0) * pow(1.0 - cVdotH, 5.0);
        float att = 1.0 - coatF * clamp(u_CoatStrength, 0.0, 1.0);
        vec3 base = SPEC_ENERGY * u_SpecStr * spec_ggx(N, L, vec3(0.0, 0.0, 1.0), base_rough);
        vec3 coat = SPEC_ENERGY * u_CoatStrength * spec_ggx(N, L, vec3(0.0, 0.0, 1.0), coat_rough);
        spec = (base * att + coat) * u_SpecColor.rgb * u_SpecMul;
    } else {
        // 经典双瓣 Blinn-Phong：宽高光（16·glow 低次项）+ 锐高光（64·glow 高次项）
        spec = u_SpecStr
             * (u_SpecSharp * pow(ndl, 16.0 * glow) + 1.2 * pow(ndl, 64.0 * glow))
             * u_SpecColor.rgb * u_SpecMul;
    }
    // 注意：镜面 alpha 必须为 0（u_SpecColor 的 w=0），否则高光会把等值面
    // 的透明度「顶满」，导致「透明度」滑块失效。次表面透射项同理。
    return intensity * (v_Color * diffuse + vec4(spec, 0.0)
                        + vec4(v_Color.rgb * sss, 0.0));
}

// 单表面基色。two_sided 时（轨道等值面）背向片元法线翻转，使波瓣内/外受光一致。
vec4 shade_base_color(bool two_sided) {
    vec3 N = normalize(v_Normal);
    if (two_sided && !gl_FrontFacing)
        N = -N;
    // Matcap：法线 → 材质球贴图，完全替代多灯光照
    //   R 通道 = 乘性环境明暗（乘固有色，做金属染色/塑料本体）
    //   G 通道 = 加性白色反射（高光/柔光箱反光条），使它亮过固有色 —— 金属
    //   的"反光"必须走加性通道，单通道灰度 LUT 在数学上做不到。
    if (u_SpecModel == 3) {
        vec2 uv = N.xy * 0.5 + 0.5;
        vec2 shade = texture(u_Matcap, uv).rg;
        vec4 mc = vec4(v_Color.rgb * shade.r + vec3(shade.g),
                       v_Color.a * DiffuseColor.a);
        // 掠射角 alpha 增强（与多灯路径一致，透明面剪影更不透明）
        mc[3] /= clamp(abs(N.z), SILHOUETTE_ALPHA_FLOOR, 1.0);
        // 深度雾化
        float fog = fog_factor();
        mc.rgb = mix(mc.rgb, lp_lin3(u_FogColor), fog);
        // 自发光/环境项
        mc.rgb += u_Ambient * v_Color.rgb;
        return mc;
    }
    vec4 color = vec4(0.0);
    for (int i = 0; i < 4; i++) {
        if (i >= u_LightCount) break;
        vec3 L = (i == 0) ? u_L0 : (i == 1) ? u_L1 : (i == 2) ? u_L2 : u_L3;
        // 各灯权重 × 能量归一化系数：灯数增减只重新分配布光层次，
        // 总能量恒等于 3 灯基准（详见 Python 侧 _LIGHT_WEIGHTS / _LIGHT_NORM_REF）。
        float intensity = ((i == 0) ? 1.0 : (i == 1) ? 0.58
                           : (i == 2) ? 0.48 : 0.38) * u_LightNorm;
        float glow = (i == 0) ? u_Glows.x : (i == 1) ? u_Glows.y
                     : (i == 2) ? u_Glows.z : u_Glows.w;
        color += light_contrib(N, L, intensity, glow);
    }

    // 背面调暗：双面材质（轨道等值面）的背向片元整体压暗，内壁比外壁暗 →
    // 半透明波瓣读出厚度/体积感。u_BackDim=1.0 时关闭（逐位等价旧画面）。
    // 放在雾化之前：雾化仍把背面混向背景色，不产生色偏；也不触碰 alpha，
    // 故 WBOIT 的 accum/reveal 权重完全不受影响。
    if (two_sided && !gl_FrontFacing)
        color.rgb *= u_BackDim;

    // ── 半球环境光（Hemisphere Lighting）──────────────────────────────
    // 世界空间上/下半球的廉价环境漫反射补光，位于「直接光之后、雾化之前」：
    //   final = 直接光漫反射 + 半球环境补光 + GGX 镜面 + 现有 FX
    // 仅写 color.rgb：① 不参与 GGX/镜面项（hemi 只加进漫反射通道）；
    // ② 不触碰 alpha，因此 WBOIT 的 accum/reveal 权重、深度剥离趟与混合方程
    //    完全不受影响；③ 乘 v_Color.rgb（固有色）以保持元素色/相位色色相，
    //    避免中性灰补光把画面冲淡。
    if (u_HemiEnabled != 0) {
        vec3 Nw = normalize(u_NormalToWorld * N);
        float h = clamp(Nw.y * 0.5 + 0.5, 0.0, 1.0);
        vec3 hemi = lp_lin3(mix(u_HemiBottom, u_HemiTop, h)) * u_HemiIntensity;
        color.rgb += hemi * v_Color.rgb;
    }

    // ── 等值面不透明度：滑块值（DiffuseColor.a）与光照调制的关系 ──
    //
    // color.a 到这里是"漫反射调制后的 alpha"：调制是 IboView 半透明观感的
    // 来源（亮处实、暗处虚），但它把 alpha 压到 Σ intensity·DiffStr·
    // pow(NdotL, DiffPow) ≈ 0.6~0.8（暗侧更低）。u_AlphaMod 决定这个调制
    // 参与多少：
    //   u_AlphaMod = 1 → 完全按调制结果（sob-art / HoukMol / IQmol 等
    //                    半透明样式，观感与改动前逐位一致）；
    //   u_AlphaMod = 0 → alpha 就直接等于滑块值（MolStudio / CYLview / VESTA
    //                    这类"默认全不透明"的样式：0% = 全实、50% = 半透、
    //                    100% = 全透，滑块全程平滑）。
    // u_AlphaMod 由样式字典的 orb_alpha_mod 提供，见 _panel.py 的各样式定义。
    color.a = mix(color.a, DiffuseColor.a, 1.0 - u_AlphaMod);

    // 完全不透明端点：DiffuseColor.a = 1（滑块拉到 0% 透明度；原子与化学键
    // 也恒走这条路）时 alpha 必须是 1，否则球棍模型会被调制变透。
    //
    // ★ 这里必须**连续**。早期写法是
    //     if (DiffuseColor.a >= 0.999) color.a = 1.0;
    //   于是透明度滑块只要从 0% 挪开一档（opacity 1.00 → 0.99），alpha 就从
    //   1.0 一步掉到 0.6~0.8：画面上"一下子从不透明变成透明"、中间没有过渡
    //   （一键样式 MolStudio / CYLview / VESTA 的 orb_opacity 都是 1，所以最先
    //   在这几个样式上被看出来；_opacity_sweep_probe.py 实测该档亮度差 ≈146，
    //   而其后相邻档只有 ≈4，跳变 35 倍）。
    //
    //   现在：拉满仍是全实（原子/键的 alpha 也照旧为 1）；u_AlphaMod=1 的样式
    //   在 0.95~1.0 之间用 smoothstep 平滑过渡到全实，断崖消失，0.95 以下与
    //   原先完全一致 —— 于是所有半透明样式的默认档位（sob-art 0.30 /
    //   HoukMol 0.30 / HoukMol3d 0.48 / IBOview 0.5 / IQmol 0.95）渲染结果
    //   逐位不变。u_AlphaMod=0 的样式本来就是线性的，不需要过渡带。
    if (DiffuseColor.a >= 0.999) {
        color.a = 1.0;
    } else if (u_AlphaMod > 0.5) {
        color.a = mix(color.a, 1.0, smoothstep(0.95, 1.0, DiffuseColor.a));
    }

    // 掠射角 alpha 增强：透明面剪影更不透明，避免边缘被背景洗白。
    color[3] /= clamp(abs(N.z), SILHOUETTE_ALPHA_FLOOR, 1.0);

    // 深度雾化（远处片元向背景色渐变），由 u_FogWidth/u_FogBias 控制。
    float fog = fog_factor();
    color.rgb = mix(color.rgb, lp_lin3(u_FogColor), fog);

    // 自发光/环境项（雾化后叠加，保留色相）。
    color.rgb += u_Ambient * v_Color.rgb;

    // 轨道专属材质 FX（边缘光晕 / 珠光 / 金属 fresnel）。
    if (two_sided && u_Fx > 0) {
        float facing = clamp(abs(N.z), 0.0, 1.0);
        float rim = pow(1.0 - facing, 2.0);
        if (u_Fx == 1) {
            // 霓虹管：贴剪影的彩色光晕。
            color.rgb += u_FxColor * rim * u_FxStrength;
        } else if (u_Fx == 2) {
            // 珠光/全息：基色向 u_FxColor 在边缘滑动。
            color.rgb = mix(color.rgb, u_FxColor, rim * u_FxStrength);
        } else if (u_Fx == 3) {
            // 金属：染色镜面的额外 fresnel 提亮。
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
        "uniform int u_MvGrad;   // 0 = three-light Phong; >0 = MolViewer radial-gradient id",
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
    lines.append("    // 线性空间（可选）：停靠曲线是 sRGB 域的观感校准曲线——采样时把")
    lines.append("    // 基色转回 sRGB 域、输出 pow(2.2) 落回线性域 → 曲线形状逐档不变，")
    lines.append("    // 透明混合改到线性域（根治半透明叠加发灰/发奶）。u_Linear=0 直通。")
    lines.append("    vec3 bs = (u_Linear > 0) ? pow(max(base, 0.0), vec3(1.0 / 2.2)) : base;")
    lines.append("    vec3 y = clamp(bs * m + a, 0.0, 1.0);")
    lines.append("    return (u_Linear > 0) ? pow(y, vec3(2.2)) : y;")
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
    // 背面调暗：与 shade_base_color(two_sided) 同口径，内壁压暗读出体积感
    if (!gl_FrontFacing) col *= u_BackDim;
    // 透明度：乘 DiffuseColor.a（等值面不透明度来自 _sp['opacity']）
    vec4 c = vec4(col, baseAlpha * DiffuseColor.a);
    float fade = fog_factor();
    fade *= step(0.0001, u_FogWidth);
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
        c.rgb = mix(c.rgb, lp_lin3(u_OrbOutlineColor), rim);
    }
    return c;
}
"""

# Orbital fragment shader — direct (no depth peeling) variant.
# 支持两种光照：u_MvGrad=0 → 三灯 Phong；u_MvGrad>0 → MolViewer
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
        c = shade_base_color(true);
    }
    out_Color = orb_outline(c);
}
"""

# Opaque (atom) fragment shader — single-sided shading, alpha from vertex colour.
# 支持两种光照：u_MvGrad=0 → 三灯 Phong；u_MvGrad>0 → MolViewer
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
        // MolCanvas depth_factor: distant atoms darken (u_FogWidth = 0 when off)
        float fade = fog_factor();
        fade *= step(0.0001, u_FogWidth);
        c.rgb *= mix(1.0, 0.55, fade);
    } else {
        // 原子走 shade_base_color(false)；vdW 外壳参考轨道等值面走
        // shade_base_color(true)：背面法线翻转 + 启用 FX（neon/pearl/metal）
        // + u_Ambient 自发光 + 高光染色，与轨道等值面材质一致。
        c = shade_base_color(u_VdwEnable > 0.5);
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
        c.rgb = mix(c.rgb, lp_lin3(oc), rim);
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
        float fade = fog_factor();
        fade *= step(0.0001, u_FogWidth);
        c.rgb *= mix(1.0, 0.55, fade);
    } else {
        c = shade_base_color(false);
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
uniform int   u_Linear;    // 色彩空间：0 = sRGB 直通（默认，与旧版逐位一致）；1 = 线性空间光照
uniform mat4 u_ModelView;
uniform mat3 u_NormalMatrix;
uniform mat4 u_Projection;
void main() {
    gl_Position = u_Projection * (u_ModelView * vec4(in_Pos, 1.0));
    v_Normal = u_NormalMatrix * in_Normal;
    v_Color = in_Color;
    // 线性空间（可选）：顶点色（元素色/相位色，sRGB 语义）pow(2.2) 转线性，
    // 光照与透明混合全程线性域，后处理 pass 统一转回 sRGB。u_Linear=0 时直通。
    if (u_Linear > 0)
        v_Color.rgb = pow(max(v_Color.rgb, 0.0), vec3(2.2));
}
"""

# Fullscreen-quad pass used to composite one peeled layer onto the
# main framebuffer (standard order-independent transparency step).
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
uniform int u_Linear;   // 0 = sRGB 直通；1 = 背景与场景同域（线性）写入场景目标
uniform vec3 uTop;
uniform vec3 uMid;
uniform vec3 uBot;
out vec4 out_Color;
void main() {
    vec3 c = (vUv.y < 0.5)
        ? mix(uMid, uTop, vUv.y * 2.0)
        : mix(uBot, uMid, (vUv.y - 0.5) * 2.0);
    if (u_Linear > 0)
        c = pow(max(c, 0.0), vec3(2.2));
    out_Color = vec4(c, 1.0);
}
"""

# ══════════════════════════════════════════════════════════════════════
# 实时后处理：超采样降采样(抗锯齿) + 边缘暗化
# ──────────────────────────────────────────────────────────────────────
# 实时渲染的 QSurfaceFormat 是 samples=0（无 MSAA），轨道等值面的剪影与
# 瓣间交界会有明显锯齿。这里把整帧先渲到一张放大的离屏目标，再用一个全屏
# pass 做盒式降采样 —— 即 SSAA。选 SSAA 而不是 MSAA/FXAA 的原因：
#   * 场景主体是**透明**等值面（深度剥离 / WBOIT），MSAA 对它无效
#     （透明片元不写深度、且合成是全屏混合），FXAA 又会把高光抹糊；
#   * SSAA 对错切、透明层、描边一视同仁，且只需一个 pass、不依赖扩展。
# 边缘暗化：用亮度梯度的**暗侧**找出可见边界（瓣与瓣、等值面与原子、原子与
# 背景）并压暗，读作接触阴影。只压暗物体一侧、背景侧不动，否则会变成黑晕。
# 之所以用**亮度**而非深度做检测：透明等值面不写深度，深度图里只有原子/键。
# ══════════════════════════════════════════════════════════════════════
FRAG_POST = """
#version 330 core
in vec2 vUv;
uniform int u_Linear;   // 0 = sRGB 直通；1 = 场景为线性域，输出前转回 sRGB
uniform sampler2D uScene;
uniform vec2  uTexel;     // 1 / 离屏(超采样)分辨率
uniform float uScale;     // 超采样倍率（1.0 = 只做边缘暗化）
uniform float uEdge;      // 边缘暗化强度（0 = 关）
uniform float uEdgeSoft;  // 边缘阈值（小于此亮度差不算边）
uniform float uEdgeRadius;// 采样半径（目标像素数）：1=细轮廓线，3~4=柔和接触阴影
uniform float uTone;      // 色调映射强度 0..1（0 = 关）
uniform float uVig;       // 暗角强度 0..0.5（0 = 关）
uniform float uAo;        // SSAO 强度 0..1（0 = 关）
uniform sampler2D uAoTex; // SSAO 结果（半分辨率，R 通道 = 遮蔽 0..1）
uniform float uAoTexel;   // 1 / AO 分辨率
uniform float uAoBlur;    // AO 去噪采样间距（AO 纹素）
out vec4 out_Color;

float luma(vec3 c) { return dot(c, vec3(0.299, 0.587, 0.114)); }

vec4 fetch(vec2 uv) { return texture(uScene, uv); }

void main() {
    // ── 1. 降采样：倍率 >1 时按 3×3 盒式平均还原出 1× 像素 ──
    vec4 c;
    if (uScale > 1.01) {
        vec2 t = uTexel * 0.5 * uScale;      // 覆盖源像素的足迹半径
        vec4 s = vec4(0.0);
        s += fetch(vUv + vec2(-t.x, -t.y));
        s += fetch(vUv + vec2( 0.0, -t.y));
        s += fetch(vUv + vec2( t.x, -t.y));
        s += fetch(vUv + vec2(-t.x,  0.0));
        s += fetch(vUv);
        s += fetch(vUv + vec2( t.x,  0.0));
        s += fetch(vUv + vec2(-t.x,  t.y));
        s += fetch(vUv + vec2( 0.0,  t.y));
        s += fetch(vUv + vec2( t.x,  t.y));
        c = s / 9.0;
    } else {
        c = fetch(vUv);
    }

    // ── 2. 边缘暗化：只在边界的**物体一侧**压暗，读作接触阴影 ──
    // 两个关键修正（第一版"边缘发黑模糊"的根因）：
    //  ① 3×3 Sobel 的响应跨 2~3 px 且**关于边界对称**，直接乘会把暗带抹进
    //     背景，看上去就是黑晕 + 糊边。改成 1px 四邻域梯度（窄）。
    //  ② 只有"本像素比邻域暗"时才压暗 —— 即边界的物体一侧；背景一侧
    //     （比邻域亮）完全不动，背景保持干净，轮廓才利落。
    //     （深色背景下物体比背景亮，判定会反过来变成外发光；此时把强度调 0
    //      即可，或改用 orb_outline 的窄带描边。）
    if (uEdge > 0.0) {
        // 采样半径：太小则只在边界 1px 内响应（成硬黑线），太大则内部平滑
        // 着色也被当成边。默认 2 目标像素 → 阴影向物体内侧铺开约 3px。
        vec2 t = uTexel * uScale * max(1.0, uEdgeRadius);
        float lc = luma(c.rgb);
        float lx0 = luma(fetch(vUv - vec2(t.x, 0.0)).rgb);
        float lx1 = luma(fetch(vUv + vec2(t.x, 0.0)).rgb);
        float ly0 = luma(fetch(vUv - vec2(0.0, t.y)).rgb);
        float ly1 = luma(fetch(vUv + vec2(0.0, t.y)).rgb);
        float gx = lx1 - lx0;
        float gy = ly1 - ly0;
        float g = sqrt(gx * gx + gy * gy);
        // 暗侧权重：邻域比本像素亮 → 本像素在边界的物体一侧，才压暗；
        // 越往物体内部 (s-lc) 越小，阴影自然渐隐。
        float s = 0.25 * (lx0 + lx1 + ly0 + ly1);
        float inside = clamp((s - lc) * 1.6, 0.0, 1.0);
        float e = smoothstep(uEdgeSoft, uEdgeSoft + 0.10, g) * inside;
        c.rgb *= (1.0 - clamp(e * uEdge, 0.0, 0.6));
    }

    // ── 3. SSAO：按遮蔽因子压暗 ──
    // AO 图是半分辨率（约 0.75× 输出分辨率）且用每像素旋转的采样盘（噪点），
    // 直接双线性放大会在等值面表面显出块状斑（实测"折痕残差>1"占比 3.8%，
    // 而不开 AO 只有 0.07%）。这里做一次 3×3（9 抽）盒式模糊再乘：平滑尺度
    // 约 ±1 个 AO 纹素，刚好把块状斑抹平，又不会糊掉接触阴影。
    if (uAo > 0.0) {
        // 采样间距按 AO 纹素 × uAoBlurSpacing 取：AO 分辨率低于输出时，
        // 只按 1 个 AO 纹素模糊不足以抹平上采样方块，需要一个更宽的核。
        float occ = 0.0;                           // 1 = 完全被遮
        for (int j = -1; j <= 1; j++)
            for (int i = -1; i <= 1; i++)
                occ += texture(uAoTex, vUv + vec2(float(i), float(j))
                               * uAoTexel * uAoBlur).r;
        occ /= 9.0;
        c.rgb *= (1.0 - clamp(occ * uAo, 0.0, 0.85));
    }

    // ── 4. 色调映射（ACES filmic 近似，Narkowicz 2015）──
    // 结果按 ACES 对纯白（1.0）的响应做归一，使**白色背景仍是纯白**：
    // 未经归一时画面整体会被压到 0.80（灰），用户读数就是"一开就发灰、
    // 分子没变化"；归一后只有物体自身的中间调/高光走胶片曲线（中间调抬升、
    // 高光滚降），背景保持干净。
    // 注：场景目标仍是 RGBA8，真正的高光滚降需要 RGBA16F（后续再做）。
    if (uTone > 0.0) {
        vec3 x = c.rgb;
        vec3 tm = clamp((x * (2.51 * x + 0.03))
                        / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0);
        tm = clamp(tm / 0.803, 0.0, 1.0);      // ACES(1.0) ≈ 0.803 → 白仍为白
        c.rgb = mix(c.rgb, tm, uTone);
    }

    // ── 5. 暗角（vignette）：画面四角轻微压暗，视线收拢到中心 ──
    if (uVig > 0.0) {
        float r = length(vUv - 0.5) * 1.4142;       // 0=中心, 1=角
        c.rgb *= 1.0 - uVig * smoothstep(0.45, 1.0, r);
    }

    // 线性空间：ACES（上面第 4 步）已按线性域走，这里统一转回 sRGB 输出。
    if (u_Linear > 0)
        c.rgb = pow(max(c.rgb, 0.0), vec3(1.0 / 2.2));
    out_Color = c;
}
"""

# ══════════════════════════════════════════════════════════════════════
# SSAO（更准确说是 screen-space obscurance）
# ──────────────────────────────────────────────────────────────────────
# 难点：主帧缓冲的深度里**只有原子/键**（透明等值面不写深度），直接拿它算 AO
# 就完全没有等值面的遮蔽。所以先跑一趟"只写深度"的预通道：把原子、键、以及
# 等值面一起画进一张半分辨率深度图（等值面只取最前一层，AO 用的正是最前层）。
#
# 算法：把本像素深度与**邻域平均深度**比较 —— 比周围深（处在凹陷里、或躲在
# 另一片几何后面）就压暗。选它而不是常见的"切平面/法线"判据，是因为这里的
# 深度来自半分辨率深度图 + MC 三角面，梯度噪声大，估切平面会把凸面也判成
# 遮蔽（实测整体均匀变暗 96% 覆盖）。均值比较对噪声稳健：
#   * 凸面：d0 ≈ 邻域均值 → 不遮蔽；
#   * 剪影外侧：邻域混进背景(1.0)，均值反而更大 → 钳到 0，不会有暗晕；
#   * 凹角 / 被前一层挡住的表面：d0 更深 → 出接触阴影。
# 深度差按 uRadius（世界单位）归一，缩放时观感一致。
# 正交投影下窗口 z 对视图深度线性，深度差可直接换算成世界单位。
# ══════════════════════════════════════════════════════════════════════
FRAG_DEPTH_ONLY = """
#version 330 core
out vec4 out_Color;
void main() { out_Color = vec4(1.0); }
"""

_FRAG_AO_TEMPLATE = """
#version 330 core
in vec2 vUv;
uniform sampler2D uDepth;
uniform vec2  uTexel;      // 1 / AO 分辨率
uniform vec3  uPixToView;  // (每像素的视图宽度, 每像素高度, 每单位窗口z的视图深度)
uniform float uRadiusPx;   // 采样环半径（**像素**，屏幕空间，与缩放无关）
uniform float uDepthScale; // 相对采样半径的深度偏置（避开自遮挡）
uniform float uIntensity;
uniform vec2  uTexSize;    // AO 缓冲分辨率（像素）
uniform float uTangentBias; // 切平面判据阈值（剔除同面/凸面剪影的假遮挡）
uniform float uGain;        // 归一化增益（把缝隙里的遮蔽推到 1）
out vec4 out_Color;

float depthAt(vec2 uv) { return texture(uDepth, uv).r; }

// 由深度纹理重建视图空间位置。正交投影下是线性的：
//   x = (像素x - 半宽) * 每像素视图宽度
//   z = -窗口深度 * 每单位窗口z的视图深度
// （z 只用于比较差值，整体平移不影响结果，故不必知道 near）。
vec3 viewPos(vec2 uv, float d) {
    vec2 px = uv * uTexSize;
    vec3 p;
    p.xy = (px - 0.5 * uTexSize) * uPixToView.xy;
    p.z  = -d * uPixToView.z;
    return p;
}

void main() {
    float d0 = depthAt(vUv);
    // 背景像素不参与遮蔽，也不产生暗边
    if (d0 >= 0.9999) { out_Color = vec4(0.0, 0.0, 0.0, 1.0); return; }

    vec3 P = viewPos(vUv, d0);

    // ── 剪影/深度断崖处不做 AO ──
    // 凸面剪影邻域里"更近"的采样点并不是遮挡物（那是同一片表面向观察者弯曲），
    // 但深度差分判据会把它们算成遮蔽，在物体边缘留下一圈假暗环（实测哑光观感
    // 环上峰值 37/255，而内部为 0）。这里先看四邻域有没有深度断崖：有就直接
    // 输出 0。缝隙里的接触阴影在**断崖旁边的表面**上，仍然照常生成。
    float dL = depthAt(vUv - vec2(uTexel.x, 0.0));
    float dR = depthAt(vUv + vec2(uTexel.x, 0.0));
    float dD = depthAt(vUv - vec2(0.0, uTexel.y));
    float dU = depthAt(vUv + vec2(0.0, uTexel.y));
    float stepView = max(max(abs(dL - d0), abs(dR - d0)),
                         max(abs(dD - d0), abs(dU - d0))) * uPixToView.z;
    if (stepView > max(uRadiusPx * uPixToView.x, 1e-6)) {
        out_Color = vec4(0.0, 0.0, 0.0, 1.0);
        return;
    }

    // 采样半径：像素 → 视图单位；偏置取半径的一个小比例，避开平面自遮挡
    float radius = max(uRadiusPx * uPixToView.x, 1e-6);
    float bias = max(uDepthScale, 1e-4) * radius;

    // ── 法线：屏幕空间中心差分重建（仅用于排除背向样本）──
    // 邻居落在背景上时用中心深度顶替（否则边缘处法线会炸开，剪影一圈假阴影）。
    float dx = depthAt(vUv + vec2(uTexel.x, 0.0));
    float dy = depthAt(vUv + vec2(0.0, uTexel.y));
    if (dx >= 0.9999) dx = d0;
    if (dy >= 0.9999) dy = d0;
    vec3 N = cross(viewPos(vUv + vec2(uTexel.x, 0.0), dx) - P,
                   viewPos(vUv + vec2(0.0, uTexel.y), dy) - P);
    bool hasN = dot(N, N) > 1e-12;
    if (hasN) {
        N = normalize(N);
        if (N.z < 0.0) N = -N;      // 屏幕空间法线统一朝相机（+z）
    }

    // Vogel 盘 + 每像素旋转（把规则采样转换成噪点，交给后处理里的 5 抽模糊）
    float ang = fract(sin(dot(gl_FragCoord.xy, vec2(12.9898, 78.233)))
                      * 43758.5453) * 6.2831853;
    const int N_SAMPLES = @AO_SAMPLES@;
    float occ = 0.0;
    for (int i = 0; i < N_SAMPLES; i++) {
        float fi = (float(i) + 0.5) / float(N_SAMPLES);
        float r = sqrt(fi) * radius;
        float th = ang + fi * 2.39996323 * float(N_SAMPLES);  // 黄金角
        // 视图空间偏移 → uv 偏移（除以每像素的视图尺寸）
        vec2 off = vec2(cos(th), sin(th)) * r;
        vec2 uv2 = vUv + off / (uTexSize * uPixToView.xy);
        float ds = depthAt(uv2);
        // 天空样本不参与遮蔽：它既不是遮挡物，采样到它还会把平均值拉远
        // （旧实现正是因此恒为 0）。
        if (ds >= 0.9999) continue;
        // 深度差（视图单位）：>0 = 采样点比本像素更靠近相机，即它是遮挡物。
        // 用"深度范围检测"而不是半球点积：分子表面多为光滑凸面/平面，
        // 点积判据在这种几何上几乎恒为 0（实测放大 100 倍灵敏度仍全 0），
        // 而缝隙两侧的深度突变是稳定且强的信号。
        float dv = (d0 - ds) * uPixToView.z;
        if (dv <= bias) continue;
        // 切平面判据（法线可信时）：只统计**位于切平面上方**的样本。
        // 这一条不能省：凸面（球、波瓣）剪影附近的邻域采样点虽然"更近"，
        // 却位于切平面**下方**；把它们算作遮挡会在凸面边缘糊出一圈大尺度
        // 暗环（实测哑光观感下 58% 的主体像素被整体压暗，看上去就是"一块
        // 一块"）。真正的缝隙里对面表面朝向本点，dot(N,V) 明显为正，照旧计入。
        if (hasN) {
            vec3 S = viewPos(uv2, ds);
            vec3 Vv = S - P;
            float dl = length(Vv);
            if (dl < 1e-6) continue;
            if (dot(N, Vv / dl) <= uTangentBias) continue;
        }
        // 横向衰减（越靠近本像素权重越大）+ 深度差归一（到采样半径封顶）
        float lat = 1.0 - r / radius;
        float depthTerm = clamp((dv - bias) / radius, 0.0, 1.0);
        occ += depthTerm * lat;
    }
    // 归一化：Vogel 盘的平均横向衰减 = 1 - E[sqrt(fi)] = 1/3，故乘 uGain
    // （默认 3）把"整圈都被遮挡"的缝隙推到 ≈1（凸面/空处仍为 0）。
    occ = clamp(occ / float(N_SAMPLES) * uGain, 0.0, 1.0);
    out_Color = vec4(clamp(occ * uIntensity, 0.0, 1.0), 0.0, 0.0, 1.0);
}
"""


def _ao_shader_source():
    """AO 着色器源码：采样数在**编译期**注入（动态循环上限在部分驱动上明显变慢）。

    做成按需构造而不是模块导入时固化，便于标定脚本扫描采样数。
    """
    return _FRAG_AO_TEMPLATE.replace("@AO_SAMPLES@", str(int(_AO_SAMPLES)))


FRAG_AO = _ao_shader_source()

# ══════════════════════════════════════════════════════════════════════
# Weighted Blended Order-Independent Transparency (WBOIT)
# ──────────────────────────────────────────────────────────────────────
# 本项目的**自研**透明合成路径，与 IboView 无关。
#
# SOURCE: 算法出自公开论文
#   Morgan McGuire, Louis Bavoil,
#   "Weighted Blended Order-Independent Transparency",
#   Journal of Computer Graphics Techniques (JCGT) 2(2):122-141, 2013.
#
# 与 depth peeling（多趟剥离 + FBO ping-pong）不同，WBOIT 只需**单趟**
# 几何渲染：把每个片元按其深度与不透明度加权累加到两张缓冲，最后一次性
# 合成。无需求出正确的前后顺序，因此天然顺序无关；代价是排序精度由权重
# 函数近似，而非精确排序 —— 对分子等值面这类"层内颜色接近、主要看整体
# 通透感"的场景，观感与 depth peeling 基本一致而实现量约为其三分之一。
#
# 该算法为公开发表的方法，以下 GLSL 为本项目按论文公式自行实现。
# ══════════════════════════════════════════════════════════════════════

# MRT 累积通道。
#   输出 0 (accum)  : Σ color.rgb * alpha * weight,  Σ alpha * weight
#   输出 1 (reveal) : Π (1 - alpha)
FRAG_ORB_OIT = """
#version 330 core
""" + _GLSL_COMMON + _MV_RAMP_GLSL + _MV_ORB_GLSL + """
layout(location=0) out vec4 out_Accum;
layout(location=1) out vec4 out_Reveal;

// 权重函数。
//
// 注意：论文 eq.10 的形式
//     w = clamp(pow(min(1,a*10)+0.01, 3) * 1e8 * pow(1 - z*0.9, 3), 1e-2, 3e3)
// 其中的 1e8 是为**透视**投影标定的（透视下 gl_FragCoord.z 高度非线性，
// 远处迅速趋近 1，pow(1-0.9z,3) 因此是个小数，需要 1e8 放大）。
// 本项目用的是**正交**投影：相机固定在 CAM_DIST，near/far 只夹住场景，
// 于是所有片元的 z 都挤在一个很窄的区间（典型 ~0.5），pow(1-0.9z,3) 反而是
// 个 0.1 量级的"大"数，乘 1e8 后**无一例外地顶到 3e3 上限**——深度权重
// 彻底失效，WBOIT 退化成不透明度加权平均，前层不再占优，观感偏暗。
//
// 因此这里改为：先把 z 归一化到**场景自身的深度跨度**（0 = 最前，1 = 最后），
// 再施加指数衰减。u_OitFalloff 越大越"前倾"（越接近 depth peeling 的
// 前层主导），默认 4.0。
uniform float u_OitZMin;      // 场景最近处的 gl_FragCoord.z
uniform float u_OitZSpan;     // 场景深度跨度（z 单位）
uniform float u_OitFalloff;   // 深度衰减强度

void main() {
    vec4 c;
    if (u_MvGrad > 0) {
        c = mv_orb_color(v_Color.rgb, v_Color.a);
    } else {
        c = shade_base_color(true);
    }
    c = orb_outline(c);

    float a = clamp(c.a, 0.0, 1.0);
    if (a < 1.0 / 255.0) discard;

    // ── 不透明度项：越不透明权重越大（沿用论文思路，但去掉会溢出的 1e8）──
    float wa = pow(min(1.0, a * 10.0) + 0.01, 3.0);

    // ── 深度项：归一化到场景跨度后指数衰减 ──
    float t = clamp((gl_FragCoord.z - u_OitZMin) / max(u_OitZSpan, 1e-6),
                    0.0, 1.0);
    float wd = exp(-max(u_OitFalloff, 0.0) * t);

    // ×100 是为了把权重抬到 fp16 累积缓冲的舒适区间，避免小值损失精度。
    float w = clamp(wa * wd * 100.0, 1e-2, 3e3);

    out_Accum = vec4(c.rgb * a, a) * w;
    out_Reveal = vec4(a);
}
"""

# 合成：累积缓冲除以权重和得到加权平均色，显现缓冲给出"还剩多少背景透过"。
# 混合方式按论文：片元 alpha 输出 revealage，用
#   glBlendFunc(GL_ONE_MINUS_SRC_ALPHA, GL_SRC_ALPHA)
# 即 final = average * (1 - reveal) + background * reveal。
FRAG_COMBINE_OIT = """
#version 330 core
uniform sampler2D Accum;
uniform sampler2D Reveal;
out vec4 out_Color;
void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    vec4 accum = texelFetch(Accum, p, 0);
    float reveal = clamp(texelFetch(Reveal, p, 0).r, 0.0, 1.0);

    // accum 可能整体为零（该像素没有透明片元），此时平均色无意义，
    // 直接输出 reveal=1 → 完全保留背景。
    vec3 average = accum.rgb / max(accum.a, 1e-5);
    out_Color = vec4(average, reveal);
}
"""

# ══════════════════════════════════════════════════════════════════════
# Depth peeling —— 多趟顺序无关透明（本项目独立实现）
# ──────────────────────────────────────────────────────────────────────
# 与 WBOIT 互补的 OIT 路径：只需一块 RGBA8 颜色纹理 + 深度纹理 + 常规
# 混合，不需要浮点渲染目标，也不需要 glBlendFunci —— GL 3.3 核心即可，
# 适合老显卡回退（WBOIT 不可用时的首选降级）。
#
# SOURCE: 算法出自公开白皮书
#   Cass Everitt, "Interactive Order-Independent Transparency",
#   NVIDIA, 2001。
# 方法本身是 front-to-back 逐层剥离：第 1 趟用普通深度测试画出最近一层；
# 之后每趟把"上一趟剥出层的深度"作为纹理采样，在片元着色器里剔除仍在
# 该深度之前的片元，再用硬件深度测试从剩余片元中挑出下一层。GLSL 文本、
# 缓冲组织与合成逻辑均为本项目自行编写（未参考任何现有实现的源码）。
#
# 本实现的组织方式：
#   * 剥离趟内**不混合**：每趟把当前层（直通色+alpha）写进草稿纹理
#     （深度写入 ping-pong 深度纹理，供下一趟做层间剔除）；
#   * 每趟之后用一块全屏"垫底"着色器（FRAG_PEEL_ACCUM）把草稿层以
#       glBlendFuncSeparate(ONE_MINUS_DST_ALPHA, ONE,
#                           ONE_MINUS_DST_ALPHA, ONE)
#     垫到累积纹理之下 —— front-to-back "under" 累积，与按 近→远 做标准
#     over 合成等价。注意混合必须发生在"草稿→累积"的全屏趟，而不是剥离
#     几何趟内：趟内开混合会让先画的较远片元先混入，近层后画时反而被
#     垫到远处之下（不透明度越高越明显，远层透到近层前）—— 这是深度剥离
#     实现里最容易踩的坑。
#   * 两块 DEPTH_COMPONENT32F 深度纹理 ping-pong（见 PeelTargets）：
#     当前趟写入本趟剥出层的深度，下一趟采样它做层间剔除。
#   * 不透明几何（原子/键）的深度每帧播种进独立的 tex_opaque，**每一趟**
#     都在片元着色器里采样做遮挡剔除（丢弃 z ≥ opaqueZ 的片元）—— 不能
#     只靠首趟的硬件深度，否则"原子背后且该像素另有近层"的远层片段会在
#     后续趟漏过、叠到原子前面。
# ══════════════════════════════════════════════════════════════════════

# 剥离趟片元着色器：着色逻辑与 FRAG_ORB 完全一致（双面光照 / MolViewer
# 渐变 / 剪影描边），只多两道剔除；输出**直通**色（本趟画进草稿纹理时
# 混合关闭，见上方说明）。alpha 经掠射角增强后可能 >1，先夹回 [0,1]。
FRAG_PEEL_ORB = """
#version 330 core
""" + _GLSL_COMMON + _MV_RAMP_GLSL + _MV_ORB_GLSL + """
uniform sampler2D u_OpaqueDepth; // 不透明几何深度（每帧播种一次，所有趟采样）
uniform sampler2D u_PrevDepth;   // 上一趟剥出层的深度（首趟不采样）
uniform int      u_UsePrev;      // 0 = 首趟（没有更近的层需要剔除）
layout(location=0) out vec4 out_Color;

void main() {
    vec4 c;
    if (u_MvGrad > 0) {
        c = mv_orb_color(v_Color.rgb, v_Color.a);
    } else {
        c = shade_base_color(true);
    }
    c = orb_outline(c);

    float a = clamp(c.a, 0.0, 1.0);
    if (a < 1.0 / 255.0) discard;

    // 遮挡剔除：在不透明几何之后（含原子/键）的片元一律丢弃 —— 每一趟
    // 都要做，不能只靠首趟的硬件深度（后面几趟的工作深度是清空的）。
    // 无不透明几何的像素上 tex_opaque 清成 1.0，此判断自然放行。
    float opaqueZ = texelFetch(u_OpaqueDepth, ivec2(gl_FragCoord.xy), 0).r;
    if (gl_FragCoord.z >= opaqueZ) discard;

    // Everitt 2001：第 k≥2 趟还要丢弃比"上一趟已剥出的层"更近/同深的
    // 片元；之后硬件深度测试（LESS，本趟深度已清 1.0）再从剩余片元里
    // 挑出最近的一层 —— 两步合起来即"剥出下一层"。
    if (u_UsePrev == 1) {
        float prevZ = texelFetch(u_PrevDepth, ivec2(gl_FragCoord.xy), 0).r;
        if (gl_FragCoord.z <= prevZ) discard;
    }

    // 直通色输出（本趟无混合）；预乘由 FRAG_PEEL_ACCUM 完成。
    out_Color = vec4(c.rgb, a);
}
"""

# 垫底趟：把草稿层（直通色）转成预乘 alpha 输出，由
#   glBlendFuncSeparate(ONE_MINUS_DST_ALPHA, ONE, ONE_MINUS_DST_ALPHA, ONE)
# 垫入累积纹理（front-to-back "under" 累积）。
FRAG_PEEL_ACCUM = """
#version 330 core
uniform sampler2D Layer;         // 本趟剥出层（直通色 + alpha）
out vec4 out_Color;
void main() {
    vec4 s = texelFetch(Layer, ivec2(gl_FragCoord.xy), 0);
    float a = clamp(s.a, 0.0, 1.0);
    out_Color = vec4(s.rgb * a, a);
}
"""

# 合成趟：把预乘累积色以 (ONE, ONE_MINUS_SRC_ALPHA) 压到已画好的主帧上。
FRAG_PEEL_COMBINE = """
#version 330 core
uniform sampler2D Accum;         // 预乘累积色 + 累积不透明度
out vec4 out_Color;
void main() {
    out_Color = texelFetch(Accum, ivec2(gl_FragCoord.xy), 0);
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

def make_sphere(radius=1.0, sub=2, out_dtype=np.float32):
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
    return (verts.astype(out_dtype),
            (verts / radius).astype(np.float32),
            faces.astype(np.uint32).flatten())


# ── 共享单位球缓存：原子球不再逐个细分 ──────────────────────────────
# 旧实现每个原子都调一次 make_sphere(r, 3)：内部是 Python 循环 + 每加一个
# 顶点就 np.vstack 一次，单个球要几千次小 numpy 调用。1000 个原子实测建网格
# 4.4 s（且占满 GUI 线程 → 界面冻结）。现在只按细分档位缓存一个**半径 1 的
# 单位球**，每个原子只做「×半径 + 平移到球心」，几何与旧实现逐位一致
# （仍用 float64 乘完再转 float32，避免舍入差异）。
_SPHERE_CACHE = {}
# 投影半径小于这个值（屏幕像素）就用 sub=2 的球（320 三角形，是 sub=3 的 1/4）。
# 晶体里原子球往往只有 10 来个像素，肉眼分辨不出差异，却省掉 3/4 的三角形。
# 想要"始终最高细分"（与旧版逐位一致）可设环境变量 OV_SPHERE_LOD_PX=0。
try:
    SPHERE_LOD_PX = float(os.environ.get("OV_SPHERE_LOD_PX", "8.0"))
except ValueError:
    SPHERE_LOD_PX = 8.0


# ── 异步建网格：把「几何生成」搬到后台线程 ─────────────────────────────
# 原子数 ≥ 该阈值时，`_gen_atoms` 派发到后台线程（纯 numpy/Python，不碰
# GL/Qt），算完再回 GUI 线程装回网格 —— 大晶体（几千原子）建网格要 0.3–1 s，
# 同步做就是界面卡一下；后台做则完全不冻。
# 小分子仍走同步（< 1 ms），保持"调用完即生效"的既有语义（导出、各种探针都
# 依赖这一点）。OV_MESH_ASYNC_MIN=0 → 全部异步；设成很大的数 → 全部同步。
try:
    MESH_ASYNC_MIN_ATOMS = int(os.environ.get("OV_MESH_ASYNC_MIN", "400"))
except ValueError:
    MESH_ASYNC_MIN_ATOMS = 400

# 上传时是否顺带构建"透明排序分块"（GlMesh._build_chunks）。
# 当前**没有渲染路径用它**（透明回退自带逐三角形排序），而它对大网格要花
# 0.16 s（2000 原子级），比 GL 传输本身还贵一个量级 → 默认关闭。
# 保留开关，将来真有基于 chunk 的绘制路径再接回来。
GLMESH_BUILD_CHUNKS = False

# `_gen_atoms` 及其调用链需要的状态（由调用链扫描得出，见 _mesh_async_scan.py）。
# 漏了任何一项，影子对象会抛 AttributeError → 自动回退同步重建，功能不受影响。
_MESH_SHADOW_ATTRS = (
    "_aim_cp_radius", "_aim_cps", "_aim_path_pts", "_aim_path_radius",
    "_atom_color_overrides", "_atom_scale", "_bond_auto_orders", "_bond_color",
    "_bond_mode", "_bond_overrides", "_bond_rf_loose", "_bond_rf_tight",
    "_bond_scale", "_bond_thinning", "_carbon_rgb", "_cube", "_dash_style",
    "_dash_weight", "_dot_size_scale", "_dot_spacing_scale", "_elem_r_mult",
    "_element_color_overrides", "_extrema_pts", "_extrema_radius",
    "_h_bond_radius", "_hide_hydrogens", "_hydrogen_rgb", "_keep_h_atoms",
    "_mol_single_rgb", "_mol_style", "_molecule", "_multi_bond_gap",
    "_multi_bond_radius", "_sel_marker_shape", "_sel_pulse", "_sel_pulse_on",
    "_sel_tint", "_sel_wrap_alpha", "_selected_atoms", "_vcube_c_rgb",
    "_vdw_balls", "_vdw_mode", "_vdw_scale", "_vdw_sel_atoms", "_vdw_sel_only",
    "_vdw_shell", "_vdw_shell_alpha", "_vdw_surf", "_sel_surf", "_atom_surf",
    "_bond_surf",
)
# 影子对象上要绑定的**纯计算**方法（绑定到影子，不是绑定到窗口！）
_MESH_SHADOW_METHODS = (
    "_gen_atoms_sync", "_gen_selection_marker", "_gen_vdw_shells",
    "_atom_color", "_atom_list", "_ball_radius", "_bond_candidate_pairs",
    "_bond_radius", "_hydrogen_visible", "_near_far", "_projection",
    "_view_proj_matrices", "_world_to_screen",
)


class _MeshShadow:
    """后台建网格用的影子对象：只承载状态，绝不碰 Qt / GL 对象。

    属性在派发那一刻快照（容器做浅拷贝），所以后台算的时候用户在界面上
    改设置也不会算错——那些改动会触发新一轮请求，旧结果按代际作废。
    """

    def __getattr__(self, name):
        raise AttributeError(
            "异步建网格缺少状态快照 %r（请把它加进 _MESH_SHADOW_ATTRS）" % name)


def stack_chunked(parts, dtype=None, chunk=192):
    """等价于 `np.vstack(parts)`，但**分块拼接并让出 GIL**。

    为什么不用 np.vstack：大网格最后要把几千个小数组拼成几张大数组（几十 MB
    的拷贝），单次调用会在 C 里一直持有 GIL —— 后台线程算网格时 GUI 就被堵住
    （实测最长 450 ms 的空档）。分块拼接、每块之间 `time.sleep(0)` 让出 GIL，
    界面全程跟手；总耗时基本不变（多几次小拷贝而已）。
    """
    if not parts:
        return np.zeros((0,), dtype=dtype or np.float32)
    if len(parts) == 1:
        return parts[0].astype(dtype, copy=False) if dtype else parts[0]
    total = sum(len(p) for p in parts)
    out = np.empty((total,) + tuple(parts[0].shape[1:]),
                   dtype=dtype or parts[0].dtype)
    i = 0
    for k in range(0, len(parts), chunk):
        blk = parts[k:k + chunk]
        n = sum(len(p) for p in blk)
        out[i:i + n] = blk[0] if len(blk) == 1 else np.concatenate(blk, axis=0)
        i += n
        time.sleep(0)          # 让出 GIL：GUI 线程得以处理事件/重绘
    return out


def unit_sphere(sub):
    """取（并缓存）半径 1 的单位球 → (verts_float64, normals, indices)。

    顶点保留 float64：旧路径是 `make_sphere(r)` 内部用 float64 算 `单位球×r`、
    再转 float32，这里照抄同样的中间精度，保证与优化前**逐位一致**
    （只差在不再逐原子重复细分）。
    """
    ent = _SPHERE_CACHE.get(sub)
    if ent is None:
        v, n, i = make_sphere(1.0, sub, out_dtype=np.float64)
        ent = (np.ascontiguousarray(v, dtype=np.float64),
               np.ascontiguousarray(n, dtype=np.float32),
               np.ascontiguousarray(i, dtype=np.uint32))
        _SPHERE_CACHE[sub] = ent
    return ent


# ══════════════════════════════════════════════════════════════════
# 选中原子高亮（本项目自定）
# ──────────────────────────────────────────────────────────────────
# 早期版本沿用 IboView 的选中标记：半径 1.8–1.9 × 原子绘制半径的二十面体，
# 颜色 0.4×原子色 + 0.6×白、alpha 0.5（见 IvView3D.cpp）。该做法有两个问题：
# 一是多边形壳离原子很远，不像"选中"更像"套了个盒子"；二是那几个常数是
# IboView 的调参结果。
#
# 现改为本项目自定方案：**原子本体染上高亮色 + 一层贴合的半透明包裹壳**。
# 包裹壳只比原子大一点点，视觉上是"这颗原子被点亮了"，而不是外面多一个物体。
# 下列常数均为本项目自行选取，与 IboView 无关。
# ══════════════════════════════════════════════════════════════════

# 高亮色（琥珀）。琥珀对 CPK/GaussView 常见配色（灰碳、红氧、蓝氮、白氢）
# 都有足够区分度，又不会像纯红那样与氧混淆、像纯蓝那样与氮混淆。
SEL_TINT_DEFAULT = (1.0, 0.72, 0.18)
# 原子本体向高亮色混合的比例：0 = 保持元素色，1 = 完全变高亮色。
# 取 0.5 左右——既能一眼看出选中，又保留元素身份。
SEL_TINT_MIX = 0.5
# 包裹壳半径相对原子绘制半径的倍数。1.10 = 刚好浮在球面外一层，
# 既不会 z-fighting，也不会显得是个独立物体。
SEL_WRAP_SCALE = 1.10
# 包裹壳不透明度。
SEL_WRAP_ALPHA = 0.38


def _mix_toward(base, target, t):
    """把颜色 base 按 t∈[0,1] 向 target 混合（线性插值，各通道独立）。"""
    t = max(0.0, min(1.0, float(t)))
    return (base[0] + (target[0] - base[0]) * t,
            base[1] + (target[1] - base[1]) * t,
            base[2] + (target[2] - base[2]) * t)


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
    bonds for the ball-and-stick model (bonds are rendered as cylinders via
    the same opaque shader as the atoms)."""
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
                               dot_size=1.0, dot_spacing=1.0, seg=12,
                               dot_radius=None):
    """Generate a dotted bond as a string of small black spheres along p→q.

    Replaces the old segmented-cylinder dashes with a row of small spheres
    (dotted style), which reads more clearly as a "dashed" (partial) bond.
    dot_size   : multiplier on each sphere's radius.
    dot_spacing: multiplier on the gap between spheres (>1 → sparser).
    dot_radius : explicit sphere radius (Bohr). When given it overrides the
                 bond_r/dash_weight/dot_size formula — used by the delocalized
                 bond, whose dashed line must match the thickness of the solid
                 line next to it.
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
    # `dot_radius` 显式给定点半径（Bohr）时直接采用：离域键的虚线点要按
    # 子键半径放大，才能与同排的等粗实线观感匹配。
    if dot_radius is not None:
        dot_r = max(float(dot_radius), 0.02)
    else:
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


def make_capped_cylinder(radius=1.0, height=1.0, seg=24):
    """沿 +Y 的圆柱（y ∈ [0, height]），**两端带平端盖**，返回 (pos, nrm, idx)。

    键的渲染趟关闭了背面剔除（双面渲染），所以没有端盖的短圆柱从侧面看会
    直接看进管子内部、显得是空心环。端盖让每一小段看起来是实心小圆柱。

    顶点排布：底环 0..seg-1，顶环 seg..2seg-1，然后是底盖中心+环、顶盖中心+环。
    注意**索引必须按这个排布写**：`make_tapered_cylinder` 用的是"底/顶交错"
    排布（2i 为底环 i、2i+1 为顶环 i），照抄它的索引会连错顶点、把网格拧成
    一团（投影出来又小又扁，包围盒却正常）。
    """
    ang = [2.0 * np.pi * i / seg for i in range(seg)]
    pos, nrm, idx = [], [], []
    for a in ang:                       # 底环
        pos.append((np.cos(a) * radius, 0.0, np.sin(a) * radius))
        nrm.append((np.cos(a), 0.0, np.sin(a)))
    for a in ang:                       # 顶环
        pos.append((np.cos(a) * radius, float(height), np.sin(a) * radius))
        nrm.append((np.cos(a), 0.0, np.sin(a)))
    for i in range(seg):                # 侧壁：(底 i, 底 i+1, 顶 i) ×2
        b = (i + 1) % seg
        idx += [i, b, seg + i, seg + i, b, seg + b]
    # 底盖（法线 -Y）
    c0 = len(pos); pos.append((0.0, 0.0, 0.0)); nrm.append((0.0, -1.0, 0.0))
    base = len(pos)
    for a in ang:
        pos.append((np.cos(a) * radius, 0.0, np.sin(a) * radius))
        nrm.append((0.0, -1.0, 0.0))
    for i in range(seg):
        idx += [c0, base + (i + 1) % seg, base + i]
    # 顶盖（法线 +Y）
    c1 = len(pos); pos.append((0.0, float(height), 0.0)); nrm.append((0.0, 1.0, 0.0))
    top = len(pos)
    for a in ang:
        pos.append((np.cos(a) * radius, float(height), np.sin(a) * radius))
        nrm.append((0.0, 1.0, 0.0))
    for i in range(seg):
        idx += [c1, top + i, top + (i + 1) % seg]
    return (np.array(pos, dtype=np.float32), np.array(nrm, dtype=np.float32),
            np.array(idx, dtype=np.uint32).flatten())


def make_dash_segment_geometry(p, q, bond_r, n_segments=0, dash_weight=0.4,
                               dot_spacing=1.0, seg=12, radius=None):
    """虚线键的**短圆柱段**画法：沿 p→q 排开一串带端盖的小圆柱。

    与 `make_dashed_bond_geometry`（小圆球点阵）是同一件事的两种样式：
      · 点阵    —— 细点，读作"部分键/配位键"，是既有默认；
      · 短圆柱段 —— 真正的虚线：段与实线同粗、一段一段排开，像二维结构式。

    段数/间距沿用点阵版的口径（同一个「虚线间隔」滑块）；每段的轴向长度 =
    `dash_weight` × 段间距，故 dash_weight 越大段越长、缝隙越小。
    `radius` 给出段半径（Bohr），None 时取 bond_r ——即与单键等粗。
    """
    d = q - p
    length = float(np.linalg.norm(d))
    if length < 1e-4:
        return (np.zeros((0, 3), dtype=np.float32),
                np.zeros((0, 3), dtype=np.float32),
                np.zeros((0,), dtype=np.uint32))

    if n_segments <= 0:
        n_segments = max(3, int(np.floor(1.0 + length / (0.45 * max(0.3, dot_spacing)))))

    r = max(bond_r if radius is None else float(radius), 0.02)
    seg_v = d / length
    # 段中心位置（与点阵版一致：两端留白，避免插进原子球）
    if n_segments == 1:
        centers_t = [length * 0.5]
        period = length
    else:
        margin = r * 1.2
        usable = length - 2.0 * margin
        if usable <= 0:
            usable = length * 0.6
            margin = (length - usable) * 0.5
        period = usable / (n_segments - 1)
        centers_t = [margin + period * k for k in range(n_segments)]
    half = 0.5 * max(0.15, min(0.95, float(dash_weight))) * period

    # 局部模板（沿 +Y、高 1）→ 旋转到键轴、缩放成段长/半径
    up = np.array([0.0, 1.0, 0.0])
    v = np.cross(up, seg_v)
    c = float(np.dot(up, seg_v))
    if float(np.linalg.norm(v)) < 1e-6:
        R = np.eye(3) if c > 0 else -np.eye(3)
    else:
        vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
        R = np.eye(3) + vx + vx @ vx * (1.0 / (1.0 + c))
    S = np.diag([r, 2.0 * half, r])
    T = R @ S
    base_v, base_n, base_i = make_capped_cylinder(1.0, 1.0, seg)

    verts_list, norms_list, idx_list = [], [], []
    off = 0
    for t in centers_t:
        start = p + seg_v * (t - half)          # 局部 y=0 落在段起点
        tv = base_v @ T.T + start
        tn = base_n @ R.T
        verts_list.append(tv)
        norms_list.append(tn)
        idx_list.append(base_i + off)
        off += len(tv)
    return (np.vstack(verts_list).astype(np.float32),
            np.vstack(norms_list).astype(np.float32),
            np.concatenate(idx_list).astype(np.uint32))


def auto_bond_order(za, zb, rij, cov_a, cov_b):
    """按键长推键型，返回 (order, q)：

        order ∈ {1, 1.5, 2, 3}（1.5 = 离域键 / 芳香键）
        q     = 键长 / (单键共价半径之和)，判据比值，供界面显示

    分档见 BOND_Q_SINGLE / BOND_Q_DELOC / BOND_Q_DOUBLE 的注释。

    只在 C/N/O 之间启用（BOND_AUTO_ELEMENTS）：S=O、P=O、金属配位等键长
    与键级关系不符合这一标定（S=O 比值 0.918 会被判成离域键、P=O 0.855 会被
    判成双键），含 H 的键也只能是单键，故这些元素一律返回单键。
    """
    if za not in BOND_AUTO_ELEMENTS or zb not in BOND_AUTO_ELEMENTS:
        return 1, float('inf')
    denom = float(cov_a) + float(cov_b)
    if denom <= 1e-9 or rij <= 1e-9:
        return 1, float('inf')
    q = float(rij) / denom
    if q >= BOND_Q_SINGLE:
        return 1, q
    if q >= BOND_Q_DELOC:
        return DELOC_BOND_ORDER, q
    if q >= BOND_Q_DOUBLE:
        return 2, q
    return 3, q


def _atom_signature(atoms):
    """把原子列表压成「原子序数序列」签名，用于判断是否还是同一个分子。

    逐键覆盖按原子下标 (i, j) 存储，跨分子会串味：给分子 A 的 5-6 号原子标了
    双键，再载入分子 B 时若下标恰好相同就会错标。签名一致 = 同一分子换几何
    （IRC 逐帧、优化步、同一分子重载），逐键标注应保留。

    兼容两种原子元组格式：
      (idx, symbol, anum, (x, y, z))  —— ovcanvas / fchk 解析侧
      (anum, charge, x, y, z)         —— cube 解析侧
    """
    sig = []
    for a in atoms:
        try:
            if isinstance(a[3], (tuple, list)):
                sig.append(int(a[2]))
            else:
                sig.append(int(a[0]))
        except (TypeError, ValueError, IndexError):
            sig.append(0)
    return tuple(sig)


def multi_bond_offset_axis(p, q, ref_dirs=()):
    """求多重键（双/三键）子键的平行偏移方向（单位向量），失败返回 None。

    化学制图的约定是：双键/三键的多根线**落在该键所在的成键平面内**——sp²
    碳上就是分子平面（乙烯、苯环、羰基都是平面型），而不是垂直于平面。

    对平面型体系这一点尤其关键：若把线偏到平面外，从最自然的"俯视分子
    平面"角度看过去两根线会完全重叠，反而看不出重数。

    所以这里取「相邻键方向在垂直于键轴方向上的分量」：

        u = normalize(ref − (ref·axis)·axis)

    （早期实现写成 `axis × ref`，那是成键平面的**法线**，正好把线偏到平面
    外，已修正。）

    `ref_dirs` 按优先级给出一串候选参考方向（调用方传入两端邻居的方向）。
    选与键轴**夹角最大**（sinθ 最大）的那个，因为越不共线，垂直分量的数值
    越稳定；若全部近似共线（终端原子、直线型 sp 原子），退回世界轴的垂直
    方向兜底（此时体系沿键轴旋转对称，任何垂直方向等价）。

    注意：方向由 (p→q) 与 ref 唯一确定，故同一根键的朝向在重绘之间稳定；
    键几何使用 0 基 i < j 的规范顺序，swap 不会让双键"翻面"。
    """
    d = np.asarray(q, dtype=np.float64) - np.asarray(p, dtype=np.float64)
    L = float(np.linalg.norm(d))
    if L < 1e-9:
        return None
    ax = d / L
    best_u, best_s = None, 0.12          # sinθ > 0.12 才算可用参考
    for ref in ref_dirs:
        r = np.asarray(ref, dtype=np.float64)
        rn = float(np.linalg.norm(r))
        if rn < 1e-9:
            continue
        r = r / rn
        s = float(np.linalg.norm(np.cross(ax, r)))   # = sin(夹角)
        if s <= best_s:
            continue
        # 面内垂直方向 = 参考方向扣掉沿键轴的分量；仍在成键平面内
        u = r - float(np.dot(r, ax)) * ax
        un = float(np.linalg.norm(u))
        if un < 1e-9:
            continue
        best_u, best_s = u / un, s
    if best_u is not None:
        return best_u
    # 兜底：挑一个与键轴垂直的世界系固定方向（不随相机变化，
    # 避免转视角时双键自己翻转）。
    for w in ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0)):
        u = np.cross(ax, np.array(w, dtype=np.float64))
        un = float(np.linalg.norm(u))
        if un > 1e-6:
            return u / un
    return None


# Orbital material FX modes selectable per-style via the ``fx`` key.
_FX_MODES = {'neon': 1, 'pearl': 2, 'metal': 3}


# ═══════════════════════════════════════════════════════════════
# Matcap（材质球）程序化生成 —— 灰度 shading LUT：法线 → 亮度
# 中心 = 正对相机（最亮），边缘 = 掠射（最暗）。着色时 base_color × shade，
# 完全替代多灯光照，观感由贴图决定。
# ═══════════════════════════════════════════════════════════════
def _make_matcap_image(size=256, light=(0.30, 0.40, 0.86), ambient=0.32,
                       spec_strength=0.7, spec_sharp=40.0, rim=0.15,
                       add_white=0.0, env=None, streaks=None):
    """生成 matcap 材质球图（size×size、uint8、**双通道**）。

    像素 (x,y) 对应视空间法线 N = (2x-1, 2y-1, sqrt(1-|xy|²))；圆外 = 0。

    通道 R（乘性·环境明暗）：`ambient + (1-ambient)*漫反射`，再叠加
    `(1-add_white)` 份高光——它乘在物体固有色上，所以**永远亮不过固有色**。
    通道 G（加性·白色反射）：`add_white` 份高光与掠射项，直接加到颜色上。

    为什么需要两个通道：金属的观感来自"暗底 + 比固有色更亮的白色反光"，
    单通道灰度 LUT 在数学上就做不出后半句（最亮只能等于固有色），所以旧的
    金属材质球永远像塑料。把高光拆成加性白色通道后才可能出现镜面反光。

    env:     (下暗端, 上亮端, 地平线亮带强度) —— 竖直环境反射（金属用）。
    streaks: [(方向, 强度, 锐度), ...] —— 多道柔光箱反光条（金属用）。
    """
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    nx = (xx + 0.5) / size * 2.0 - 1.0
    ny = (yy + 0.5) / size * 2.0 - 1.0
    r2 = nx * nx + ny * ny
    nz = np.sqrt(np.maximum(1.0 - r2, 0.0))
    inside = r2 <= 1.0

    L = np.array(light, dtype=np.float32)
    L = L / (np.linalg.norm(L) or 1.0)
    V = np.array([0.0, 0.0, 1.0], dtype=np.float32)
    H = L + V
    H = H / (np.linalg.norm(H) or 1.0)

    ndl = np.clip(nx * L[0] + ny * L[1] + nz * L[2], 0.0, 1.0)
    ndh = np.clip(nx * H[0] + ny * H[1] + nz * H[2], 0.0, 1.0)

    # 环境反射（金属）：竖直渐变（下暗上亮）+ 地平线亮带
    if env is not None:
        lo, hi, horizon = env
        g = np.clip(ny * 0.5 + 0.5, 0.0, 1.0)
        ndl = lo + (hi - lo) * g
        if horizon:
            ndl = ndl + horizon * np.exp(-np.square((ny - 0.02) / 0.10))
        ndl = np.clip(ndl, 0.0, 1.0)

    spec = spec_strength * np.power(ndh, spec_sharp)
    if streaks:
        spec = spec * 0.0
        for sdir, samp, ssh in streaks:
            S = np.array(sdir, dtype=np.float32)
            S = S / (np.linalg.norm(S) or 1.0)
            Hs = S + V
            Hs = Hs / (np.linalg.norm(Hs) or 1.0)
            ndhs = np.clip(nx * Hs[0] + ny * Hs[1] + nz * Hs[2], 0.0, 1.0)
            spec = spec + samp * np.power(ndhs, ssh)
    if rim > 0.0:
        spec = spec + rim * np.power(1.0 - nz, 2.0)

    mul = ambient + (1.0 - ambient) * ndl + (1.0 - add_white) * spec
    add = add_white * spec
    mul = np.where(inside, mul, 0.0)
    add = np.where(inside, add, 0.0)
    out = np.stack([np.clip(mul, 0.0, 1.0), np.clip(add, 0.0, 1.0)], axis=-1)
    return (out * 255.0).astype(np.uint8)


# Matcap 预设：name -> 生成参数
_MATCAP_PRESETS = {
    "studio": dict(ambient=0.32, spec_strength=0.7, spec_sharp=40.0, rim=0.15,
                   light=(0.30, 0.40, 0.86)),
    "glossy": dict(ambient=0.12, spec_strength=1.1, spec_sharp=90.0, rim=0.05,
                   light=(0.25, 0.35, 0.90)),
    "matte":  dict(ambient=0.55, spec_strength=0.15, spec_sharp=16.0, rim=0.0,
                   light=(0.40, 0.50, 0.77)),
    # 金属：暗底 + 竖直环境反射（下暗上亮 + 地平线亮带）+ 两道柔光箱反光条，
    # 高光全部走加性白色通道（add_white=1），所以能亮过固有色、真的"反光"。
    # 参数经实测标定：用户要"更亮更平"（磨砂铝），所以把竖直环境梯度的
    # 暗端抬到 0.62（本体亮、明暗差小），反光条只剩 0.10 的极弱宽条，
    # 无边缘反光。实测最大通道均值 156–181、锐闪点 0%、std 25–41
    # （塑料/哑光 17–28，早前的亮铬版 std 59 / 闪点 5%）。
    "metal":  dict(ambient=0.10, spec_strength=0.0, spec_sharp=1.0,
                   rim=0.0, add_white=1.0,
                   env=(0.62, 1.00, 0.0),
                   streaks=[((0.08, 0.45, 0.89), 0.10, 60.0)]),
}
_MATCAP_NAMES = {
    "studio": "柔和影棚", "glossy": "亮面塑料", "matte": "哑光陶瓷", "metal": "金属",
}


def style_params(surface_mat, style=None):
    """Translate a vcube-style surface_mat into the renderer's semantic material
    uniforms plus the extended material channels (emissive ambient, tinted
    specular, orbital FX). Lighting is:
        diffuse  = u_DiffuseStr * pow(NdotL, u_DiffusePow) * DiffuseColor
        specular = u_SpecStr * (D·F·G)/(4·NdotV·NdotL)   # GGX + Schlick
    so we map diffuse->u_DiffuseStr, specular->u_SpecStr; the highlight shape
    is driven by u_Roughness (GGX 微表面粗糙度，独立于这 4 个 reg)。surface_mat
    里的 shininess（[3]）历史上映射到 u_SpecSharp，GGX 下已不再使用。

    ``style`` is the optional STYLES entry; it may carry extra keys to unlock
    the new material channels (defaults keep the classic look):
        fx:           'neon' | 'pearl' | 'metal' | None
        ambient:      emissive strength (0..~2)
        spec_color:   (r, g, b) specular tint (default white)
        spec_mul:     specular strength multiplier (default 1; 0 = matte)
        roughness:    GGX 微表面粗糙度 0.03..1（越小越镜面）
        fx_strength:  0..1 intensity of the FX
        fx_color:     (r, g, b) rim / secondary sheen colour
    """
    amb, diff, spec, shin, mir, opac = surface_mat[:6]
    o = [_REG_DEFAULT_O[0], diff, max(spec, 0.0), shin]
    a = list(_REG_DEFAULT_A)
    sp = {
        'o_reg': o, 'a_reg': a,
        'FogBias': _RENDER_DEFAULTS['FogBias'],
        'FogWidth': _RENDER_DEFAULTS['FogWidth'],
        'opacity': opac,
        # Extended material uniforms (defaults keep the classic look).
        'ambient': 0.0,
        'spec_color': (1.0, 1.0, 1.0),
        'spec_mul': 1.0,
        'roughness': 0.45,   # GGX 微表面粗糙度（0.03..1，越小越镜面）
        'coat_roughness': 0.10,   # Clear-coat 清漆层粗糙度（尖锐）
        'coat_strength': 0.80,    # Clear-coat 清漆层强度
        'sss_strength': 0.0,      # 次表面散射强度（0=关闭，走标准 Lambert）
        'back_dim': 0.8,          # 等值面背面调暗系数（1.0=关，内壁更暗→体积感）
        'fx': 0,
        'fx_strength': 0.0,
        'fx_color': (1.0, 1.0, 1.0),
    }
    if style:
        # 样式自带的 IboView 原版着色寄存器（STYLES[...]['gl_regs']）：
        # 直接作为该样式的材质基准，格式与 a_reg/o_reg 相同
        # [漫反射指数, 漫反射强度, 镜面强度, 双瓣平衡]。
        gr = style.get('gl_regs')
        if gr:
            if gr.get('atom'):
                sp['a_reg'] = [float(x) for x in gr['atom'][:4]]
            if gr.get('orb'):
                sp['o_reg'] = [float(x) for x in gr['orb'][:4]]
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
        if style.get('roughness') is not None:
            sp['roughness'] = max(0.03, min(1.0, float(style['roughness'])))
        if style.get('coat_roughness') is not None:
            sp['coat_roughness'] = max(0.03, min(1.0, float(style['coat_roughness'])))
        if style.get('coat_strength') is not None:
            sp['coat_strength'] = max(0.0, min(2.0, float(style['coat_strength'])))
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

    Two depth buffers are ping-ponged between peel passes: each pass renders
    only fragments lying strictly in front of the depth recorded by the
    previous pass (standard order-independent-transparency technique).
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


class SceneTarget:
    """整帧离屏目标：RGBA8 颜色（可线性采样）+ DEPTH_COMPONENT32F 深度。

    给实时后处理（超采样抗锯齿 / 边缘暗化）用——整帧先渲到这里，再由全屏
    pass 降采样并描边输出到屏幕。颜色用 LINEAR 是降采样盒式滤波的前提。
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
        for p, v in ((GL_TEXTURE_MIN_FILTER, GL_LINEAR),
                     (GL_TEXTURE_MAG_FILTER, GL_LINEAR),
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
            raise RuntimeError(f"后处理 FBO incomplete (status 0x{int(status):04X})")

    def destroy(self):
        if self.fbo:
            glDeleteFramebuffers(1, [self.fbo])
        for t in (self.tex_color, self.tex_depth):
            if t:
                glDeleteTextures([t])
        self.fbo = self.tex_color = self.tex_depth = 0
        self.w = self.h = 0


class AoTarget:
    """SSAO 用的一对半分辨率目标：只写深度的 FBO + 输出遮蔽度的 R8 FBO。"""

    def __init__(self):
        self.fbo_depth = 0
        self.tex_depth = 0
        self.fbo_ao = 0
        self.tex_ao = 0
        self.w = self.h = 0

    def create(self, w, h):
        self.destroy()
        self.w, self.h = max(1, int(w)), max(1, int(h))

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

        self.tex_ao = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, self.tex_ao)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_R8, self.w, self.h, 0,
                     GL_RED, GL_UNSIGNED_BYTE, None)
        for p, v in ((GL_TEXTURE_MIN_FILTER, GL_LINEAR),   # 合成时放大要平滑
                     (GL_TEXTURE_MAG_FILTER, GL_LINEAR),
                     (GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE),
                     (GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)):
            glTexParameteri(GL_TEXTURE_2D, p, v)
        glBindTexture(GL_TEXTURE_2D, 0)

        # 深度目标：无颜色附件（glDrawBuffer(GL_NONE)，与 peel 的播种目标同法）
        self.fbo_depth = glGenFramebuffers(1)
        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo_depth)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
                               GL_TEXTURE_2D, self.tex_depth, 0)
        st = glCheckFramebufferStatus(GL_FRAMEBUFFER)
        glBindFramebuffer(GL_FRAMEBUFFER, 0)
        if st != GL_FRAMEBUFFER_COMPLETE:
            self.destroy()
            raise RuntimeError(f"AO 深度 FBO incomplete (0x{int(st):04X})")

        self.fbo_ao = glGenFramebuffers(1)
        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo_ao)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                               GL_TEXTURE_2D, self.tex_ao, 0)
        st = glCheckFramebufferStatus(GL_FRAMEBUFFER)
        glBindFramebuffer(GL_FRAMEBUFFER, 0)
        if st != GL_FRAMEBUFFER_COMPLETE:
            self.destroy()
            raise RuntimeError(f"AO 输出 FBO incomplete (0x{int(st):04X})")

    def destroy(self):
        for f in (self.fbo_depth, self.fbo_ao):
            if f:
                glDeleteFramebuffers(1, [f])
        for t in (self.tex_depth, self.tex_ao):
            if t:
                glDeleteTextures([t])
        self.fbo_depth = self.fbo_ao = 0
        self.tex_depth = self.tex_ao = 0
        self.w = self.h = 0


class OitTarget:
    """WBOIT 的 MRT 渲染目标：累积缓冲 + 显现缓冲 + 深度。

    Weighted Blended OIT (McGuire & Bavoil, JCGT 2013) 只需要单趟几何：
      * 颜色附件 0 (accum, RGBA16F)
            以 (GL_ONE, GL_ONE) 累加   Σ (color.rgb * a, a) * w
      * 颜色附件 1 (reveal, R16F)
            以 (GL_ZERO, GL_ONE_MINUS_SRC_COLOR) 累乘   Π (1 - a)
      * 深度附件：用于与已绘制的不透明几何做深度测试（不写深度）

    浮点缓冲不可渲染时（缺 GL_ARB_color_buffer_float / EXT_color_buffer_float）
    自动放弃：create() 抛异常，调用方回退到 depth peeling 或排序混合。
    """

    def __init__(self):
        self.fbo = 0
        self.tex_accum = 0
        self.tex_reveal = 0
        self.tex_depth = 0
        self.w = self.h = 0
        # glDrawBuffers / glClearBufferfv 需要真正的数组，用 numpy 固定类型
        # 比临时元组更稳；缓存起来避免每帧重新分配。
        self._bufs = np.array([GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1],
                              dtype=np.uint32)
        self._clr_accum = np.zeros(4, dtype=np.float32)
        self._clr_reveal = np.ones(4, dtype=np.float32)
        self._clr_depth = np.ones(1, dtype=np.float32)

    @staticmethod
    def _make_tex(internal, fmt, dtype, w, h):
        t = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, t)
        glTexImage2D(GL_TEXTURE_2D, 0, internal, w, h, 0, fmt, dtype, None)
        for p, v in ((GL_TEXTURE_MIN_FILTER, GL_NEAREST),
                     (GL_TEXTURE_MAG_FILTER, GL_NEAREST),
                     (GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE),
                     (GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)):
            glTexParameteri(GL_TEXTURE_2D, p, v)
        glBindTexture(GL_TEXTURE_2D, 0)
        return t

    def create(self, w, h):
        self.destroy()
        self.w, self.h = max(1, int(w)), max(1, int(h))

        # 浮点格式优先；若 FBO 不完整（多半是不能渲染到浮点纹理），
        # 逐级降级，最后放弃。
        attempts = [
            (GL_RGBA16F, GL_HALF_FLOAT, GL_R16F, GL_HALF_FLOAT),
            (GL_RGBA16F, GL_HALF_FLOAT, GL_R8, GL_UNSIGNED_BYTE),
        ]
        last_err = "no attempt"
        for acc_i, acc_t, rev_i, rev_t in attempts:
            try:
                self.tex_accum = self._make_tex(
                    acc_i, GL_RGBA, acc_t, self.w, self.h)
                self.tex_reveal = self._make_tex(
                    rev_i, GL_RED, rev_t, self.w, self.h)
                self.tex_depth = self._make_tex(
                    GL_DEPTH_COMPONENT32F, GL_DEPTH_COMPONENT, GL_FLOAT,
                    self.w, self.h)

                self.fbo = glGenFramebuffers(1)
                glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)
                glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                                       GL_TEXTURE_2D, self.tex_accum, 0)
                glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT1,
                                       GL_TEXTURE_2D, self.tex_reveal, 0)
                glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
                                       GL_TEXTURE_2D, self.tex_depth, 0)
                status = glCheckFramebufferStatus(GL_FRAMEBUFFER)
                glBindFramebuffer(GL_FRAMEBUFFER, 0)
                if status == GL_FRAMEBUFFER_COMPLETE:
                    return
                last_err = f"FBO incomplete (status 0x{int(status):04X})"
            except Exception as e:
                last_err = str(e)
            self.destroy()

        raise RuntimeError(f"WBOIT 目标不可用: {last_err}")

    def destroy(self):
        if self.fbo:
            glDeleteFramebuffers(1, [self.fbo])
        for t in (self.tex_accum, self.tex_reveal, self.tex_depth):
            if t:
                glDeleteTextures([t])
        self.fbo = self.tex_accum = self.tex_reveal = self.tex_depth = 0
        self.w = self.h = 0

    def bind(self, w, h):
        """绑定为绘制目标，并把累积/显现缓冲清到初始值。"""
        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)
        glViewport(0, 0, w, h)
        glDrawBuffers(2, self._bufs)
        # accum 清 0；reveal 清 1（"还没有任何东西挡住背景"）。
        glClearBufferfv(GL_COLOR, 0, self._clr_accum)
        glClearBufferfv(GL_COLOR, 1, self._clr_reveal)
        # 深度附件是 GL_DEPTH_COMPONENT32F（无模板位），因此只能用
        # glClearBufferfv(GL_DEPTH, ...)；glClearBufferfi 要求 depth-stencil 格式。
        glClearBufferfv(GL_DEPTH, 0, self._clr_depth)


class PeelTargets:
    """深度剥离（Everitt 2001）的 FBO 组。

    组织（关键：剥离趟内**不混合**，用草稿纹理隔离"当前层"）：

      * tex_scratch（RGBA8）—— 当前趟剥出层（直通色+alpha，每趟清零重写）；
      * tex_acc   （RGBA8）—— front-to-back 累积结果（预乘 alpha，跨趟保留）；
      * tex_opaque（DEPTH_COMPONENT32F）—— 不透明几何（原子/键）深度，
        每帧播种一次，所有剥离趟在片元着色器里采样它做遮挡剔除；
      * tex_depth[2]（DEPTH_COMPONENT32F）—— ping-pong 上一趟/本趟深度。

    每趟：几何**关混合**画进 fbo_scratch[i]（深度写入 tex_depth[i]）。
    片元着色器统一做两道剔除：① 在不透明几何之后（z ≥ 不透明深度）→ 丢；
    ② 第 k≥2 趟还要剔除 z ≤ 上一趟剥出层深度的片元（u_PrevDepth）。
    之后硬件深度测试（LESS，本趟深度清 1.0）从剩余片元里挑出本层，再
    用全屏趟把 tex_scratch 以 "under" 混合（glBlendFuncSeparate
    ONE_MINUS_DST_ALPHA/ONE…）垫入 tex_acc。

    这样同一趟内先画的较远片元不会污染累积（那是"趟内开混合"的经典
    错误：远的会盖住近的）；且每趟都保有原子遮挡（不能只靠首趟的硬件
    深度，否则"原子背后 + 该像素另有近层"的远层片段会漏过）。

    整组只依赖 GL 3.3 核心（无需浮点渲染目标 / glBlendFunci），是比
    WBOIT 门槛更低的 OIT 路径。
    """

    def __init__(self):
        self.fbo_scratch = [0, 0]
        self.fbo_acc = 0
        self.fbo_opaque = 0
        self.tex_scratch = 0
        self.tex_acc = 0
        self.tex_opaque = 0
        self.tex_depth = [0, 0]
        self.w = self.h = 0
        # glClearBufferfv 需要真正的数组（惯例同 OitTarget：numpy 固定类型）
        self._clr_zero = np.zeros(4, dtype=np.float32)
        self._clr_one = np.ones(1, dtype=np.float32)

    @staticmethod
    def _make_tex(internal, fmt, dtype, w, h):
        t = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, t)
        glTexImage2D(GL_TEXTURE_2D, 0, internal, w, h, 0, fmt, dtype, None)
        for p, v in ((GL_TEXTURE_MIN_FILTER, GL_NEAREST),
                     (GL_TEXTURE_MAG_FILTER, GL_NEAREST),
                     (GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE),
                     (GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)):
            glTexParameteri(GL_TEXTURE_2D, p, v)
        glBindTexture(GL_TEXTURE_2D, 0)
        return t

    def create(self, w, h):
        self.destroy()
        self.w, self.h = max(1, int(w)), max(1, int(h))
        self.tex_scratch = self._make_tex(GL_RGBA8, GL_RGBA, GL_UNSIGNED_BYTE,
                                          self.w, self.h)
        self.tex_acc = self._make_tex(GL_RGBA8, GL_RGBA, GL_UNSIGNED_BYTE,
                                      self.w, self.h)
        for i in (0, 1):
            t = self._make_tex(GL_DEPTH_COMPONENT32F, GL_DEPTH_COMPONENT,
                               GL_FLOAT, self.w, self.h)
            glBindTexture(GL_TEXTURE_2D, t)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_COMPARE_MODE, GL_NONE)
            glBindTexture(GL_TEXTURE_2D, 0)
            self.tex_depth[i] = t

        # 不透明深度纹理 + 专用播种目标（只挂深度，无颜色附件）。
        self.tex_opaque = self._make_tex(GL_DEPTH_COMPONENT32F,
                                         GL_DEPTH_COMPONENT, GL_FLOAT,
                                         self.w, self.h)
        glBindTexture(GL_TEXTURE_2D, self.tex_opaque)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_COMPARE_MODE, GL_NONE)
        glBindTexture(GL_TEXTURE_2D, 0)
        self.fbo_opaque = glGenFramebuffers(1)
        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo_opaque)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
                               GL_TEXTURE_2D, self.tex_opaque, 0)
        status = glCheckFramebufferStatus(GL_FRAMEBUFFER)
        glBindFramebuffer(GL_FRAMEBUFFER, 0)
        if status != GL_FRAMEBUFFER_COMPLETE:
            err = f"peel opaque FBO incomplete (status 0x{int(status):04X})"
            self.destroy()
            raise RuntimeError(err)

        # 累积目标：只挂颜色（全屏垫底趟无深度测试）。
        self.fbo_acc = glGenFramebuffers(1)
        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo_acc)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                               GL_TEXTURE_2D, self.tex_acc, 0)
        status = glCheckFramebufferStatus(GL_FRAMEBUFFER)
        glBindFramebuffer(GL_FRAMEBUFFER, 0)
        if status != GL_FRAMEBUFFER_COMPLETE:
            err = f"peel acc FBO incomplete (status 0x{int(status):04X})"
            self.destroy()
            raise RuntimeError(err)

        # 两块剥离草稿目标：共享 tex_scratch，各自带一块工作深度。
        for i in (0, 1):
            self.fbo_scratch[i] = glGenFramebuffers(1)
            glBindFramebuffer(GL_FRAMEBUFFER, self.fbo_scratch[i])
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                                   GL_TEXTURE_2D, self.tex_scratch, 0)
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
                                   GL_TEXTURE_2D, self.tex_depth[i], 0)
            status = glCheckFramebufferStatus(GL_FRAMEBUFFER)
            if status != GL_FRAMEBUFFER_COMPLETE:
                err = f"peel scratch FBO {i} incomplete (status 0x{int(status):04X})"
                glBindFramebuffer(GL_FRAMEBUFFER, 0)
                self.destroy()
                raise RuntimeError(err)
        glBindFramebuffer(GL_FRAMEBUFFER, 0)

    def destroy(self):
        for f in self.fbo_scratch:
            if f:
                glDeleteFramebuffers(1, [f])
        if self.fbo_acc:
            glDeleteFramebuffers(1, [self.fbo_acc])
        if self.fbo_opaque:
            glDeleteFramebuffers(1, [self.fbo_opaque])
        for t in self.tex_depth:
            if t:
                glDeleteTextures([t])
        for t in (self.tex_scratch, self.tex_acc, self.tex_opaque):
            if t:
                glDeleteTextures([t])
        self.fbo_scratch = [0, 0]
        self.fbo_acc = 0
        self.fbo_opaque = 0
        self.tex_scratch = 0
        self.tex_acc = 0
        self.tex_opaque = 0
        self.tex_depth = [0, 0]
        self.w = self.h = 0

    def bind_scratch(self, i, w, h):
        """绑定剥离草稿目标 fbo_scratch[i]（写 tex_scratch + 深度 tex_depth[i]）。"""
        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo_scratch[i])
        glViewport(0, 0, w, h)

    def clear_scratch(self, w, h):
        """清空草稿颜色与工作深度（每趟开始时调用）。"""
        glClearBufferfv(GL_COLOR, 0, self._clr_zero)
        glClearBufferfv(GL_DEPTH, 0, self._clr_one)

    def bind_opaque(self, w, h):
        """绑定不透明深度播种目标（写 tex_opaque，无颜色附件）。"""
        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo_opaque)
        glDrawBuffer(GL_NONE)      # 该 FBO 无颜色附件：显式关闭颜色写出
        glViewport(0, 0, w, h)

    def clear_opaque_depth(self):
        """播种前把不透明深度清 1.0（无不透明处 = 无穷远）。"""
        glClearBufferfv(GL_DEPTH, 0, self._clr_one)

    def bind_acc(self, w, h):
        """绑定累积目标（写 tex_acc，无深度附件）。"""
        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo_acc)
        glViewport(0, 0, w, h)

    def clear_acc(self, w, h):
        """首趟前清零累积颜色（此后跨趟保留）。"""
        glClearBufferfv(GL_COLOR, 0, self._clr_zero)


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

    def _upload_buf(self, target, attr, data):
        """把 data 传到 self.<attr> 缓冲（不存在则创建）。

        ★ 试过"留 25% 余量 + glBufferSubData 复用"的写法：像素级 A/B 抓出
        3.2% 的像素差异（最大 247/255，显然是读到了没写满的存储）——**已回退**。
        保持"每次按实际大小 glBufferData"，但**复用缓冲名字**（不删除重建）。
        """
        buf = getattr(self, attr, 0)
        if not buf:
            buf = glGenBuffers(1)
            setattr(self, attr, buf)
        glBindBuffer(target, buf)
        glBufferData(target, data.nbytes, data, GL_STATIC_DRAW)
        return buf

    def _upload_attr(self, loc, attr, data, ncomp):
        """上传（或在 data 为 None 时停用）一个可选顶点属性。"""
        if data is None:
            if getattr(self, attr, 0):
                glDisableVertexAttribArray(loc)
            return
        self._upload_buf(GL_ARRAY_BUFFER, attr, data)
        glVertexAttribPointer(loc, ncomp, GL_FLOAT, GL_FALSE, 0, None)
        glEnableVertexAttribArray(loc)

    def upload(self, surf):
        """把网格数据传到 GPU。

        ★ 复用已有的 VAO/VBO，只重发数据，不再"删除旧缓冲 → 重建"。
          旧写法每次上传都 destroy() 再 glGenBuffers+glBufferData：删掉的缓冲
          GPU 可能还在用，驱动必须等它用完才能回收 —— 画布里实测一次上传要
          **140 ms**，而同一份数据在空闲上下文里只要 18 ms（差 8 倍），表现就是
          "切换超胞/载入大分子时顿一下"。复用缓冲后 glBufferData 走驱动标准的
          "孤儿化"路径（换一块新存储、旧的留给 GPU 慢慢用完），不再同步等待。

        ★ `_build_chunks` 当前**没有任何渲染路径在用**（透明回退自带逐三角形
          深度排序），而它对大网格要花 0.16 s（三角形中心 + Morton 排序），
          所以默认关闭；需要时把 GLMESH_BUILD_CHUNKS 设回 True。
        """
        if surf is None or surf.vertex_count == 0:
            self.destroy()
            self.n_vtx = 0
            self.n_idx = 0
            self._gen += 1
            return
        if GLMESH_BUILD_CHUNKS:
            self._build_chunks(surf)
        self.n_vtx = surf.vertex_count
        self.n_idx = len(surf.indices)
        if self.vao == 0:
            self.vao = glGenVertexArrays(1)
        glBindVertexArray(self.vao)
        self._upload_buf(GL_ARRAY_BUFFER, "vbo_p", surf.vertices)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 0, None)
        glEnableVertexAttribArray(0)
        self._upload_attr(1, "vbo_n", surf.normals, 3)
        self._upload_attr(2, "vbo_c", surf.colors, 4)
        self._upload_attr(3, "vbo_id", getattr(surf, "ids", None), 1)
        if self.n_idx > 0:
            self._upload_buf(GL_ELEMENT_ARRAY_BUFFER, "ebo", surf.indices)
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
    """Arcball camera with an orthographic projection.

    The eye stays at a fixed distance `CAM_DIST` along -Z and the visible
    extent is controlled purely via the orthographic half-height
    (`BASE_EXTENT / zoom_factor`). `self.z` is the zoom factor,
    `half_height()` gives the ortho half-height, and the view matrix only
    translates by -CAM_DIST.
    """

    CAM_DIST = 105.0        # fixed eye distance (ortho projection)
    BASE_EXTENT = 7.8       # base ortho half-height

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
        """Orthographic half-height: BASE_EXTENT / zoom_factor."""
        return self.BASE_EXTENT / max(self.z, 1e-6)

    def view(self):
        """View matrix: centre -> pan -> rotate -> push back by CAM_DIST."""
        m = np.eye(4, dtype=np.float32)
        m[:3, :3] = _q2m(self.q)
        m[0, 3], m[1, 3] = self.t[0], self.t[1]
        # Under an orthographic projection the eye distance does not change
        # the apparent size; it only positions the scene inside the near/far
        # slab (fixed eye distance under orthographic projection).
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

    The orthographic frustum is built exactly this way:
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
# 导出图片格式（PNG / JPG / TIF / SVG）
# ═══════════════════════════════════════════════════════════════
#
# 背景说明：3D 场景是 OpenGL 光栅化的结果，**本质是位图**。所以：
#   · PNG  —— 无损，支持 8 位 alpha（透明背景就靠它）
#   · JPG  —— 有损，**不支持 alpha**；选透明背景时会先压到背景色上再编码
#   · TIF  —— 无损，支持 alpha，存档/投稿常用
#   · SVG  —— 矢量容器，内部以 base64 PNG 嵌入渲染结果。文件是标准 SVG
#             （Inkscape / Illustrator / 浏览器 / LaTeX 均可直接排版，缩放不
#             会变糊），但像素内容仍是光栅图：把几百万个着色三角形真正矢量
#             化需要另写一套 2D 矢量渲染器，不在本功能范围内。
#
# 格式选择规则（优先级从高到低）：
#   1. 路径里明确写出的已知扩展名（用户手打 "图.tiff" / Windows 对话框自动补的后缀）
#   2. 保存对话框里选中的过滤器
#   3. 调用方传入的期望格式（画布/ESP 面板的格式菜单）
#   4. 都没有 → PNG
# 各面板的 _export_image() 按同样顺序调用下面这几个判定函数。

#: 显示名 → (规范扩展名, 对话框通配符)
EXPORT_FORMATS = (
    ("PNG",  "png", "*.png"),
    ("JPG",  "jpg", "*.jpg *.jpeg"),
    ("TIFF", "tif", "*.tif *.tiff"),
    ("SVG",  "svg", "*.svg"),
)

#: 别名扩展名 → 规范扩展名
_EXPORT_ALIAS = {
    "png": "png", "jpg": "jpg", "jpeg": "jpg", "jpe": "jpg",
    "tif": "tif", "tiff": "tif", "svg": "svg", "svgz": "svg",
}


def export_dialog_filter(preferred=None):
    """保存对话框的过滤器串（显示名 + 通配符 + 所有文件）。

    ``preferred`` 传扩展名时，该格式对应的过滤器排到最前 —— Qt 会把它作为
    对话框的**默认选中项**，于是"点 JPG 菜单 → 对话框已是 JPG"。
    """
    ordered = list(EXPORT_FORMATS)
    pref = export_ext_from_path("x." + str(preferred), default=None) \
        if preferred else None
    if pref:
        ordered.sort(key=lambda t: 0 if t[1] == pref else 1)   # 稳定排序
    parts = []
    for name, _ext, pat in ordered:
        label = "JPEG" if name == "JPG" else name
        parts.append(f"{label} ({pat})")
    parts.append("所有文件 (*)")
    return ";;".join(parts)


def export_ext_for(name, default="png"):
    """显示名（"TIFF"）**或**扩展名（"tif" / ".TIFF"）→ 规范扩展名（"tif"）。

    两种写法都要认：菜单项通过 ``action.setData()`` 传的是扩展名，而
    ``EXPORT_FORMATS`` 里存的是显示名，只匹配其一会让 TIFF 这类
    "显示名 ≠ 扩展名"的格式静默回退到上一个格式。
    """
    key = str(name).strip().lower().lstrip(".")
    if key in _EXPORT_ALIAS:
        return _EXPORT_ALIAS[key]
    for disp, ext, _pat in EXPORT_FORMATS:
        if disp.lower() == key:
            return ext
    return default


def export_ext_from_path(path, default="png"):
    """按扩展名判断目标格式；未知扩展名时返回 default。

    这样"用户手打 .jpeg / .TIFF"也能落到正确分支。
    """
    ext = os.path.splitext(str(path))[1].lower().lstrip(".")
    return _EXPORT_ALIAS.get(ext, default)


def export_ext_from_filter(selected_filter, default="png"):
    """按保存对话框**选中的过滤器**判断目标格式。

    Qt 返回的过滤器串形如 ``"JPEG (*.jpg *.jpeg)"``，取其中的第一个
    通配符来判格式；解析不出来时返回 default。
    """
    s = str(selected_filter or "")
    lo = s.lower()
    for disp, ext, pat in EXPORT_FORMATS:
        # 先看显示名是否出现在过滤器串里（"TIFF" / "JPEG" / "PNG" / "SVG"）
        names = {disp.lower(), "jpeg" if ext == "jpg" else disp.lower()}
        if any(n and n in lo for n in names):
            return ext
        if pat.replace("*", "").split()[0] in lo:
            return ext
    return default


def export_format_supports_alpha(ext):
    """该格式是否支持 alpha 通道（决定"透明背景"是否有意义）。

    目前只有 JPG 不支持；PNG / TIFF / SVG 都能带透明背景。
    """
    return export_ext_for(ext, default="png") != "jpg"


def export_ensure_suffix(path, ext):
    """路径带已知图片扩展名则原样返回，否则补上 ``.ext``。

    避免用户在对话框里只打 "out"、结果存出一个没有后缀的文件。
    """
    have = os.path.splitext(str(path))[1].lower().lstrip(".")
    if have in _EXPORT_ALIAS:
        return path
    return f"{path}.{ext}"


def _set_dpi_metadata(img, dpi):
    """把 DPI 写进位图的物理分辨率元数据（1 inch = 0.0254 m）。"""
    dpm = int(round(max(1.0, float(dpi)) / 0.0254))
    img.setDotsPerMeterX(dpm)
    img.setDotsPerMeterY(dpm)


def _write_svg(img, path, dpi):
    """把渲染结果写成标准 SVG（内部 base64 嵌入 PNG）。

    物理尺寸按 DPI 换算成毫米写进 width/height，viewBox 用像素，
    于是 SVG 在排版软件里"1:1 按 600 DPI 尺寸"落版，放大也不会有
    插值模糊（像素是满分辨率的）。
    """
    w = max(1, img.width())
    h = max(1, img.height())
    dpi = max(1.0, float(dpi))

    # ── 首选：Qt 自带 SVG 生成器（输出经 Qt 自身校验的标准 SVG）──
    try:
        from PyQt5.QtSvg import QSvgGenerator
        gen = QSvgGenerator()
        gen.setFileName(str(path))
        gen.setSize(QSize(w, h))
        gen.setViewBox(QRect(0, 0, w, h))
        gen.setTitle("MolStudio export")
        gen.setDescription(
            f"MolStudio canvas export — {w}x{h} px rendered at {dpi:g} DPI "
            f"(raster embedded in SVG)")
        gen.setResolution(int(round(dpi)))
        painter = QPainter()
        if not painter.begin(gen):
            return False, "SVG 生成器无法打开输出文件"
        try:
            painter.drawImage(0, 0, img)
        finally:
            painter.end()
        return True, ""
    except ImportError:
        pass
    except Exception as e:
        return False, f"SVG 写入失败: {e}"

    # ── 回退：手工拼 SVG（QtSvg 缺失时，例如裁剪过的打包环境）──
    import base64
    try:
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        try:
            if not img.save(buf, "PNG"):
                return False, "SVG 内嵌位图编码失败"
        finally:
            buf.close()
        b64 = bytes(ba.toBase64()).decode("ascii")
        mm_w = w / dpi * 25.4
        mm_h = h / dpi * 25.4
        xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'xmlns:xlink="http://www.w3.org/1999/xlink" '
            'version="1.1"\n'
            f'     width="{mm_w:.4f}mm" height="{mm_h:.4f}mm" '
            f'viewBox="0 0 {w} {h}">\n'
            '  <title>MolStudio export</title>\n'
            f'  <image x="0" y="0" width="{w}" height="{h}" '
            'preserveAspectRatio="none"\n'
            f'         xlink:href="data:image/png;base64,{b64}"/>\n'
            '</svg>\n')
        with open(path, "w", encoding="utf-8") as f:
            f.write(xml)
        return True, ""
    except Exception as e:
        return False, f"SVG 写入失败: {e}"


def save_export_image(img, path, dpi=600.0, background=None, quality=-1):
    """把渲染好的 QImage 按目标扩展名写到磁盘。

    参数
    ----
    img        : QImage（RGBA8888 / ARGB32 均可）
    path       : 目标路径；扩展名决定格式（png/jpg/tif/svg，含别名）
    dpi        : 写进文件元数据的物理分辨率
    background : QColor 或 (r,g,b) —— **不支持 alpha 的格式**（JPG）用它
                 压平半透明像素；None 时用白色
    quality    : JPG 质量 1..100（-1 = Qt 默认）

    返回 ``(ok, message, real_path)``：``real_path`` 是补过后缀后的实际路径。
    """
    ext = export_ext_from_path(path)
    real_path = export_ensure_suffix(path, ext)
    dpi = max(1.0, float(dpi))

    # 取背景色（用于 JPG 压平）。接受三种写法：
    #   QColor / (r,g,b) 0..255 整数 / (r,g,b) 0..1 浮点（画布 _bg 就是这种）
    if isinstance(background, QColor):
        bg = background
    elif background is not None:
        try:
            rgb = [float(v) for v in list(background)[:3]]
            if max(rgb) <= 1.0:                 # 0..1 浮点 → 0..255
                rgb = [v * 255.0 for v in rgb]
            bg = QColor(int(round(rgb[0])), int(round(rgb[1])),
                        int(round(rgb[2])))
        except Exception:
            bg = QColor(255, 255, 255)
    else:
        bg = QColor(255, 255, 255)

    if ext == "svg":
        ok, msg = _write_svg(img, real_path, dpi)
        return ok, msg, real_path

    out = img
    if ext == "jpg":
        # JPEG 无 alpha 通道：先合成到不透明底，再交给编码器。
        # 背景是透明 alpha=0 时，RGB 仍是画布底色，直接取用观感最接近屏幕。
        if out.hasAlphaChannel():
            flat = QImage(out.width(), out.height(), QImage.Format_RGB32)
            flat.fill(bg)
            p = QPainter(flat)
            p.drawImage(0, 0, out)
            p.end()
            out = flat
    _set_dpi_metadata(out, dpi)

    writer = QImageWriter(str(real_path))
    fmt = {"jpg": "JPEG", "tif": "TIFF", "png": "PNG"}.get(ext)
    if fmt:
        writer.setFormat(fmt.encode("ascii"))
    if ext == "jpg":
        writer.setQuality(int(quality) if 1 <= int(quality) <= 100 else 92)
    try:
        ok = writer.write(out)
    except Exception as e:
        return False, f"写入失败: {e}", real_path
    if not ok:
        return False, f"写入失败: {writer.errorString()}", real_path
    return True, "", real_path


# ═══════════════════════════════════════════════════════════════
# GL Widget
# ═══════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════
# 画布测量：距离 / 键角 / 二面角
# ══════════════════════════════════════════════════════════════════
#: 测量类型 → 需要依次点击的原子数。新增类型只需在这里加一行，
#: 控件（画布样式条 / 晶体信息条）与 glw 都按这张表走。
MEASURE_NEED = {"dist": 2, "angle": 3, "dihedral": 4}
#: 类型 → 中文名（仅用于状态栏提示；UI 文案另有 i18n）
MEASURE_NAME = {"dist": "键长", "angle": "键角", "dihedral": "二面角"}


def _angle_deg(a, b, c):
    """∠abc（b 为顶点），单位度，0..180。"""
    v1 = np.asarray(a, dtype=np.float64) - np.asarray(b, dtype=np.float64)
    v2 = np.asarray(c, dtype=np.float64) - np.asarray(b, dtype=np.float64)
    n1 = float(np.linalg.norm(v1))
    n2 = float(np.linalg.norm(v2))
    if n1 < 1e-9 or n2 < 1e-9:
        return 0.0
    cos = float(np.dot(v1, v2)) / (n1 * n2)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


def _dihedral_deg(p0, p1, p2, p3):
    """二面角 p0-p1-p2-p3（度，-180..180），符号按 IUPAC 约定。"""
    b0 = np.asarray(p0, dtype=np.float64) - np.asarray(p1, dtype=np.float64)
    b1 = np.asarray(p2, dtype=np.float64) - np.asarray(p1, dtype=np.float64)
    b2 = np.asarray(p3, dtype=np.float64) - np.asarray(p2, dtype=np.float64)
    n1 = float(np.linalg.norm(b1))
    if n1 < 1e-9:
        return 0.0
    b1 = b1 / n1
    v = b0 - np.dot(b0, b1) * b1
    w = b2 - np.dot(b2, b1) * b1
    x = float(np.dot(v, w))
    y = float(np.dot(np.cross(b1, v), w))
    return math.degrees(math.atan2(y, x))


class CubGLWidget(QOpenGLWidget):
    """OpenGL widget with deferred initialization."""

    # 后台建网格完成信号（参数 = 代际号；<0 表示后台失败，需回退同步）
    _meshBuilt = pyqtSignal(int)
    # 测量状态变化（模式开关, 测量类型）：画布样式条与晶体信息条两处控件靠它同步
    measureStateChanged = pyqtSignal(bool, str)

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
        # 异步建网格状态（见 module 顶部 MESH_ASYNC_MIN_ATOMS 说明）
        self._mesh_async_on = True
        self._mesh_build_id = 0          # 代际号：变了说明有更新的请求
        self._mesh_busy = False          # 后台是否正在算
        self._mesh_pending = False       # 算的过程中又被要求重建（合并成一次）
        self._mesh_thread = None
        self._mesh_shadow_out = None     # 后台算好的影子对象
        self._mesh_async_warned = False
        try:
            self._meshBuilt.connect(self._on_mesh_built)
        except Exception:
            self._mesh_async_on = False
        self._sel_mesh = GlMesh()   # 选中原子包裹壳
        self._vdw_mesh = GlMesh()   # van-der-Waals radius shells (semi-transparent)
        # 选中原子平面填充（苯环等环系半透明涂色，诉求：选 ≥3 原子自动生成；
        # 多个环可并存，每条独立颜色/可删除）
        self._fill_mesh = GlMesh()
        self._fill_items = []      # [{"surf","sel","rgba"}] 每个环一条
        self._fill_surf = None     # 全部条目拼接的合并网格（_upload 用）
        self._fill_rgba = (0.20, 0.55, 1.00, 0.35)   # 新填充的默认色
        # 配位多面体（晶体页）：与"平面填充"共用同一套半透明绘制管线与合并网格，
        # 但单独存放 —— 用户改多面体设置时不该动到他自己的平面填充。
        self._poly_items = []      # [{"surf"}] 每个多面体一条
        self._poly_rgba = (0.71, 0.71, 0.71, 0.45)   # VESTA 多面体灰
        self._bond_mesh = GlMesh()  # 化学键独立网格（供"二次上色"重绘 pass 使用）
        self._bond_surf = None
        self._bg = (1.0, 1.0, 1.0, 1.0)
        # 场景包围球半径（Bohr）：载入 cube / 框选分子时更新，供景深雾化
        # 换算"场景深度跨度"用（见 fog_factor / set_shader_uniforms）。
        self._scene_r = 5.0

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

        self._vao_quad = 0

        # ── 顺序无关透明（OIT）──
        # _transparency_mode: "peel" | "oit" | "sorted"
        #   peel   = Depth peeling（多趟，Everitt 2001，本项目独立实现）—— 默认
        #   oit    = WBOIT（单趟，McGuire & Bavoil 2013，本项目自研）
        #   sorted = 画家算法排序混合（最省资源）
        # 三者任一在运行时不可用/失败时自动逐级回退。
        self._transparency_mode = "peel"
        self._oit = OitTarget()
        self._oit_ok = False
        self._prog_orb_oit = self._prog_combine_oit = 0
        # WBOIT 深度衰减强度：越大越"前层主导"（越接近 depth peeling）；
        # 0 = 完全不区分前后（退化为等权平均，观感偏暗）。
        self._oit_falloff = 4.0
        # ── Depth peeling（Everitt 2001，本项目独立实现，可选路径）──
        # 与 WBOIT 互补：GL 3.3 核心即可（无需浮点 MRT / glBlendFunci），
        # 老显卡上 WBOIT 不可用时可优先回退到这里。
        self._peel = PeelTargets()
        self._peel_ok = False
        self._prog_orb_peel = self._prog_accum_peel = self._prog_combine_peel = 0
        self._peel_layers = 4        # 剥离趟数上限（1..8，默认 4）

        # Data state — deferred loading pattern
        self._cube = None
        # 独立分子数据（载入 fchk/xyz 时设置，单位 Bohr），不依赖 cube 文件
        self._molecule = None
        self._pos_surf = None
        self._neg_surf = None
        # 按轨道独立数据（NBO 多轨道叠加用）：[(cube, pos, neg, pc, nc)]，
        # pc/nc 为 0..1 元组；_orbital_flipped 记录各轨道是否已翻转相位。
        # _orbital_pair_mode 记录该轨道的配色"来源"，决定换配色后怎么跟：
        #   "base"    = 载入时用的就是当前正/负基准色（跟随基准）
        #   "swapped" = 载入时用的是基准色的**交换**版（NBO E(2) 受体的相位互换）
        #   "fixed"   = 该轨道有自己的独立配色（自动分配色相的兜底路径），不跟基准
        # 没有这张表时（历史数据）一律按 "base" 处理。见 _sync_rec_colors()。
        self._orbital_recs = []
        self._orbital_flipped = []
        self._orbital_pair_mode = []
        # 异步等值面重算（多轨道叠加页签的等值滑块用）：marching cubes 挪到工作
        # 线程跑，拖动全程不阻塞 GUI；工作线程只做纯 numpy/mcubes，不碰 GL。
        self._orbital_gen = 0          # 每次重建轨道记录（load/reset）自增，
                                       # 过期异步结果按代号丢弃，防止串到新场景
        self._mc_busy = False          # 有 job 在队列/正在计算
        self._mc_pending = None        # 计算期间的最新请求（只保留最后一次）
        self._mc_results = []          # 线程计算结果队列 [(gen, iso, ok, pos, neg)]
        self._mc_queue = None          # job: (gen, iso, cubes 快照)
        self._mc_thread = None         # daemon 工作线程
        self._mc_poll = QTimer(self)   # 主线程轮询结果并上传 GL
        self._mc_poll.setInterval(16)
        self._mc_poll.setSingleShot(True)
        self._mc_poll.timeout.connect(self._on_mc_poll)
        # ESP 表面标志：True 表示 _pos_surf 携带 ESP 顶点连续着色（esp_panel
        # 写入）。此时 set_style / set_phase_colors / flip_phase 不得用相位色
        # 平铺 colors，reset_molviewer_style 也不得动 opacity。
        self._surf_vcolor = False
        self._atom_surf = None
        self._sel_surf = None
        self._vdw_surf = None      # vdW 外壳网格（_upload 前必须已初始化，避免空场景 AttributeError）
        self._vdw_balls = []       # 与 vdW 外壳同序的 (cx,cy,cz,r) 列表
        self._sel_marker_shape = "wrap"      # 选中标记形状（贴合包裹壳）
        self._sel_pulse = 0.0        # 呼吸动画相位
        self._sel_pulse_on = False   # 呼吸动画开关
        self._sel_pulse_timer = None
        # 选中高亮：色调与包裹壳不透明度（本项目自定，见 SEL_TINT_* 常量）
        self._sel_tint = tuple(SEL_TINT_DEFAULT)
        self._sel_wrap_alpha = float(SEL_WRAP_ALPHA)
        self._isovalue = 0.05
        self._needs_upload = False
        self._status_cb = None
        self._atom_pick_cbs = []    # 原子点击回调列表：cb(atom_idx_1based)
        # 测量模式：按类型依次点击 2/3/4 个原子，标签显示数值（距离 Å / 角度 °）。
        # 标注可拖放/旋转/调字体颜色（右键点标签），退出模式不清除
        # （clear_measure_items 清）。
        self._measure_mode = False
        self._measure_kind = "dist"    # dist 距离 / angle 键角 / dihedral 二面角
        self._measure_pair = []     # 当前正在选择的原子（0-based，最多 MEASURE_NEED 个）
        self._measure_items = []    # 已完成测量 [{"p0","p1","text","offx","offy",
        #                              "rot","pt","family","color", "kind","pts","segs"}]，Bohr
        self._mlabel_drag = None    # (idx, grab_dx, grab_dy) 标签拖动状态
        # Shift+左键框选（IGMH 分片段等用）
        self._box_selecting = False
        self._box_start = None
        self._box_current = None
        self._box_cb = None         # cb([atom_idx_1based, ...])
        # Ball-and-stick display scales (user-adjustable via sliders)
        self._atom_scale = 1.68   # atom sphere radius scale (default 1.68)
        self._bond_scale = 2.0   # bond cylinder radius scale (default 2.0)
        # 按元素单独调节原子球半径的倍率表（Z → 倍率，1.0 = 默认）。
        # 与全局 _atom_scale 相乘；只影响显示球径，不改坐标/键判定。
        self._elem_r_mult = {}
        # 氢原子球半径跟随化学键圆柱半径（CYLview 观感：H 与键一样粗）。
        # 是样式属性而非手动调节：换分子/换文件后依然生效，见 _ball_radius。
        self._h_bond_radius = False
        self._bond_thinning = BOND_THINNING_DEFAULT  # midpoint narrowing factor (1.0 = no waist)

        # 景深雾化（远处蒙白雾）开关，默认开启
        self._fade_enabled = True
        # Bond radius factor — dual-threshold for solid / dashed / no-bond
        self._bond_rf_tight = 1.0   # ≤ this → solid bond
        self._bond_rf_loose = 1.3   # ≤ this → dashed bond; > this → no bond
        self._dash_weight = 0.4     # fill ratio for dashed bonds (0..1)
        self._dot_size_scale = 1.0      # 虚线大小倍率（点阵：点半径；短段：段粗细）
        self._dot_spacing_scale = 1.0   # 虚线间距倍率 (>1 更稀疏)
        # 虚线样式：'dots' = 小圆球点阵（既有默认）；'dashes' = 短圆柱段（真虚线）
        self._dash_style = DASH_STYLE_DEFAULT
        # 成键模式：'single' 一律单键；'auto' 按键长自动判定键型
        self._bond_mode = BOND_MODE_DEFAULT
        self._bond_auto_orders = {}   # {(i,j): (order, q)} 最近一次自动判定结果
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
        self._light_default_dirs = list(_PHONG_LIGHT_DIRS)  # 当前光照模式的默认灯方向（视图空间）
        self._light_dirs = [list(d) for d in self._light_default_dirs]  # 当前（含方位/俯仰）
        self._light_az = 0.0                      # 方位角偏移（度，绕视图轴）
        self._light_el = 0.0                      # 俯仰角偏移（度，>0 向上）
        self._light_count = 3                     # 生效光源数（1..4）
        self._light_glow = 1.0                    # 光晕大小（1=默认；>1 更大更散）
        self._light_glows = [1.0, 1.0, 1.0, 1.0]  # 每盏灯独立光晕（u_Glows）
        self._style_name = None                  # last isosurface style name
        # Gloss preset (overrides a_reg/o_reg after style build)
        self._gloss = _GLOSS_DEFAULT
        # 镜面高光模型：0 = Blinn-Phong 双瓣（经典），1 = GGX 微表面（默认）
        self._spec_model = 1
        # 用户手动设置的表面材质（set_surface_material）：与样式自带值分开存，
        # 因为样式值只作用于等值面，而用户滑块应同时影响原子/键。
        self._user_ambient = 0.0
        self._user_spec_mul = 1.0
        # 样式自带的着色寄存器基准（STYLES[...]['gl_regs']；None = 用 gloss 映射）
        self._style_regs = None
        # Matcap 材质球（u_SpecModel==3 时用）
        self._matcap_tex = 0
        self._matcap_name = "studio"
        self._matcap_dirty = True
        # 半球环境光（Hemisphere Lighting）—— 世界空间环境漫反射弱补光
        self._hemi_enabled = True
        self._hemi_top = (0.18, 0.18, 0.18)
        self._hemi_bottom = (0.035, 0.035, 0.035)
        self._hemi_intensity = 0.25
        # 明暗交界线柔化（Half-Lambert 混合）：0 = 标准 Lambert（保持原观感）
        self._soft_term = 0.0

        # ── MolViewer 样式（MolCanvas 预设）扩展 ──
        self._bg_grad = None         # None=纯色；否则 (top, mid, bot) 0..1 三段竖向渐变
        self._bond_color = None      # None=按元素/分子风格；否则 (r,g,b) 0..1 统一键色
        # 键材质（独立于原子的两个旋钮）：
        self._bond_gloss = None      # None=跟随全局光泽（a_reg）；否则 0..1 独立键光泽
        self._bond_diffuse = 0.8     # 键面漫反射亮度系数（0.2..1.6；1.0 = 按原色）
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
        self._mv_grad = 0            # 0=三灯 Phong；>0=MolViewer 径向渐变类型 id
        self._orb_outline = False    # 等值面剪影描边
        self._orb_outline_color = (0.0, 0.0, 0.0)
        self._orb_outline_width = 0.3
        # 等值面 alpha 是否被光照调制：1 = 调制（原 IboView 半透明观感，默认），
        # 0 = 透明度滑块直接线性控制（MolStudio / CYLview / VESTA 用）。
        self._orb_alpha_mod = 1.0
        self._prog_bg = 0
        self._vao_bg = 0

        # ── 实时后处理：超采样抗锯齿 + 边缘暗化 ──
        # 实时 QSurfaceFormat 是 samples=0（无 MSAA），轨道剪影/瓣交界全是锯齿，
        # 故整帧先渲到放大的离屏目标再降采样。默认开；老机器可在面板关掉。
        self._post_on = True
        self._post_scale = 1.5     # 1.0 / 1.5 / 2.0（1.0 时只做边缘暗化）
        # 默认只留抗锯齿。暗角/色调映射是**全局**效果（压背景、降对比），
        # 用户反馈"画布变灰、分子没变化"，故一律默认关；想用再开。
        self._post_edge = 0.0      # 边缘暗化强度（0 = 关）
        self._post_edge_soft = 0.06  # 亮度差阈值：小于它不算边界
        self._post_edge_r = 2.0    # 采样半径（目标像素）：1=细线，3~4=柔和阴影
        self._post_tone = 0.0      # 色调映射强度（0 = 关）
        self._post_vig = 0.0       # 暗角强度（0 = 关）
        self._post_ao = 0.0        # SSAO 强度（0 = 关；关掉即跳过深度预通道）
        self._post_ao_r = 8.0      # 采样环半径（像素，屏幕空间）
        self._post_ao_d = 0.03     # 深度偏置（相对采样半径的比例，避开平面自遮挡）
        self._post = SceneTarget()
        self._post_ok = True
        self._prog_post = 0

        # ── 色彩空间（2026-09-21，B 方案）：0/False = sRGB 直通（默认，与旧版
        # 逐位一致）；True = 线性空间光照——顶点色/颜色 uniform 转线性、光照
        # 与透明混合（WBOIT 累积、雾化、描边）全程线性域、后处理 pass 在 ACES
        # 之后统一 pow(1/2.2) 转回 sRGB。渐变停靠曲线做 sRGB 域保形映射（曲线
        # 形状逐档不变，混合改到线性域）。已知代价：SceneTarget 为 RGBA8，线性
        # 值存 8bit 暗部会有轻微量化条纹（正式解决需换 RGBA16F）。──
        self._linear_space = False
        # SSAO（半分辨率：深度预通道 + 遮蔽图 + 全屏 AO pass）
        self._ao = AoTarget()
        self._ao_ok = True
        self._prog_depth = 0
        self._prog_ao = 0

        # Interactive atom/bond picking & override system (context menu)
        # 逐键覆盖：(i,j) 为 0 基且 `i < j`；值 ∈
        #   'solid'  实线单键
        #   'dashed' 虚线单键（小圆球点阵）
        #   'double' 双键（两根平行圆柱，与单键等粗）
        #   'triple' 三键（三根平行圆柱，与单键等粗）
        #   'deloc'  离域键 / 芳香键（实线 + 虚线并列，等价于"双键里
        #            其中一根画成虚线"）
        #   'none'   强制不画键
        self._bond_overrides = {}
        # 多重键几何参数（BondStyleDialog 可调）
        self._multi_bond_radius = MULTI_BOND_RADIUS_DEFAULT   # 子键半径 / 单键半径
        self._multi_bond_gap = MULTI_BOND_GAP_DEFAULT         # 子键中心距 / 子键半径
        # 原子序数签名：set_molecule 载入的是否仍是同一个分子。
        # 同一个分子换几何（IRC 逐帧、优化步）时逐键覆盖要保留，换分子才清。
        self._mol_sig = None
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
        # 极值点数值标签的离屏超采样缓存（见 _extrema_label_image）
        self._extrema_img_cache = {}
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
        self._cs_cmap_name = ""      # 当前配色名（fallback 方向判断用）
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
        # 色标条叠加层的超采样缓存（见 _build_cs_overlay）
        self._cs_img = None
        self._cs_img_key = None
        # 键长标注的超采样缓存（见 _measure_label_image）
        self._measure_img_cache = {}

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

    # ── 测量标注（距离 / 键角 / 二面角）──────────────────────────
    def set_measure_mode(self, enabled, kind=None):
        """开/关测量模式。

        kind: "dist" 距离（点 2 个原子）/ "angle" 键角（点 3 个）/
        "dihedral" 二面角（点 4 个）；None = 沿用当前类型。
        开启后按类型依次点击原子即测一次，可连续测多组；退出模式标注保留
        （可拖放/右键调属性），用 clear_measure_items() 清除。
        """
        if kind in MEASURE_NEED:
            self._measure_kind = kind
        self._measure_mode = bool(enabled)
        self._measure_pair = []
        self._mlabel_drag = None
        self.setCursor(Qt.CrossCursor if self._measure_mode else Qt.ArrowCursor)
        self._status(self._measure_hint(self._measure_mode))
        self.measureStateChanged.emit(self._measure_mode, self._measure_kind)
        self.update()

    def set_measure_kind(self, kind):
        """切换测量类型（距离 / 键角 / 二面角）；进行中的选择作废重来。"""
        if kind not in MEASURE_NEED or kind == self._measure_kind:
            return
        self._measure_kind = kind
        self._measure_pair = []
        if self._measure_mode:
            self._status(self._measure_hint(True))
        self.measureStateChanged.emit(self._measure_mode, self._measure_kind)
        self.update()

    def measure_state(self):
        """返回 (模式开关, 测量类型)，供 UI 初始化时对齐。"""
        return bool(self._measure_mode), self._measure_kind

    def _measure_hint(self, on):
        """状态栏提示文案（按当前测量类型生成）。"""
        kind = self._measure_kind
        need = MEASURE_NEED.get(kind, 2)
        name = MEASURE_NAME.get(kind, "键长")
        if on:
            return (f"{name}测量：依次点击 {need} 个原子即可标注"
                    f"（可连续测多组；再点一次按钮退出）")
        return (f"已退出{name}测量（标注保留：拖动可移位，右键点标签可旋转/"
                f"调字体颜色，「清除」按钮删除标注）")

    def clear_measure_items(self):
        """清除全部键长测量标注（不改变测量模式开关状态）。"""
        self._measure_items = []
        self._measure_pair = []
        self._mlabel_drag = None
        self.update()

    def _measure_click(self, x, y):
        """测量模式下点击：拾取原子，凑满所需个数（距 2 / 角 3 / 二面角 4）即测一次。"""
        hit, _ = self._pick_atom(x, y)
        if hit < 0:
            return
        if hit in self._measure_pair:
            return
        atoms = self._atom_list()
        if not atoms or hit >= len(atoms):
            return
        kind = self._measure_kind
        need = MEASURE_NEED.get(kind, 2)
        self._measure_pair.append(hit)
        if len(self._measure_pair) < need:
            picked = ", ".join(str(i + 1) for i in self._measure_pair)
            self._status(f"已选原子 {picked}（{len(self._measure_pair)}/{need}），"
                         f"继续点击")
            self.update()
            return
        idx = self._measure_pair
        self._measure_pair = []
        pts = [np.asarray(atoms[i][1], dtype=np.float64) for i in idx]
        # 标签锚点仍用 p0/p1 的中点（_measure_label_rect 按它投影）：
        # 距离取两端中点；键角取两条键之间；二面角落在中间那根键上。
        if kind == "dist":
            val = float(np.linalg.norm(pts[1] - pts[0]) * BOHR_TO_ANGSTROM)
            anchor, segs, unit = (pts[0], pts[1]), [(0, 1)], "Å"
        elif kind == "angle":
            val = _angle_deg(pts[0], pts[1], pts[2])
            anchor, segs, unit = (pts[0], pts[2]), [(1, 0), (1, 2)], "°"
        else:
            val = _dihedral_deg(pts[0], pts[1], pts[2], pts[3])
            anchor, segs, unit = (pts[1], pts[2]), [(0, 1), (1, 2), (2, 3)], "°"
        self._measure_items.append({
            "p0": tuple(anchor[0]), "p1": tuple(anchor[1]),
            "pts": [tuple(p) for p in pts],   # 参与测量的全部原子位置（Bohr）
            "segs": segs,                     # 需要画的虚线连线（pts 的下标对）
            "kind": kind,
            "text": f"{val:.2f}",       # 只显示数值，不带单位（论文用）
            "offx": 0.0, "offy": 0.0,     # 相对锚点的屏幕拖放偏移（px）
            "rot": 0.0,                   # 标签旋转角度（度，顺时针）
            "pt": 12,                     # 字号（默认 12pt：画布缩放后仍看得清）
            "family": "Arial",            # 论文常用字体
            "color": (0, 0, 0),           # 黑色文字
        })
        self._status(f"{MEASURE_NAME.get(kind, '键长')} "
                     f"{'-'.join(str(i + 1) for i in idx)} = {val:.2f}{unit}"
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
        # 字号最小 7pt（与原子标签一致）；字体设置与 _measure_label_image
        # 完全同一套（含 hinting），否则命中框会和看到的框差一两个像素
        f = self._measure_label_font(it)
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

    @staticmethod
    def _measure_label_font(it):
        """标注字体（与 _measure_label_rect 用完全同一套设置）。"""
        f = QFont(it["family"]) if it["family"] else QFont()
        f.setPointSize(max(7, int(it["pt"])))
        f.setBold(True)
        # 小字号必须显式要求完整字形微调：不开时笔画被摊成半灰，看着就是"糊"
        f.setHintingPreference(QFont.PreferFullHinting)
        return f

    @staticmethod
    def _paint_measure_item(p, it, f, tw, th):
        """在当前坐标系（已平移到标签中心、已旋转）画一条标注：衬底 + 文字。

        文字走 QPainterPath 矢量填充，**不用 drawText**：drawText 在 GL 画布
        上经字库缓存栅格化，小字号 + 半透明衬底叠加时笔画会粘连缺笔——
        用户描述为"字烂了"。路径填充只求字形轮廓，与字库缓存无关。
        """
        rect = QRectF(-tw / 2.0, -th / 2.0, tw, th)
        # 无边框：只画半透明白底圆角衬底（压在深色球/键上时字口更清楚）
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 244))
        p.drawRoundedRect(rect, 4, 4)
        fmf = QFontMetricsF(f)
        x0 = rect.center().x() - fmf.horizontalAdvance(it["text"]) / 2.0
        y0 = rect.center().y() + (fmf.ascent() - fmf.descent()) / 2.0
        path = QPainterPath()
        path.addText(QPointF(x0, y0), f, it["text"])
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(*it["color"]))
        p.drawPath(path)

    def _measure_label_image(self, it):
        """把一条键长标注（衬底 + 文字）渲染成放大的离屏 QImage。

        返回 (img, 逻辑宽, 逻辑高)；img 按整数倍超采样，逻辑宽高是贴回画布时
        应占的尺寸（**已含旋转后的外接框**，否则旋转标签的四角会被切掉）。

        为什么要离屏：屏幕上的标签只有十几个设备像素高，直接在 GL 画布上画
        只有 1× 采样，笔画发虚发毛；导出图是 6 倍分辨率渲染再缩小显示，同一
        个标签反而更锐利。给画布上这一小块补上同样的超采样，屏幕与导出观感
        才一致（与色标条 _build_cs_overlay 同一对策）。

        离屏图只跟（文字/字体/字号/颜色/旋转）有关，与位置无关，因此按内容
        缓存：拖动标签时每帧只做一次 drawImage，开销可忽略。
        """
        f = self._measure_label_font(it)
        text = str(it["text"])
        fm = QFontMetrics(f)
        tw = fm.horizontalAdvance(text) + 10     # 与 _measure_label_rect 一致
        th = fm.height() + 4
        rot = float(it["rot"])
        key = (text, it["family"], int(it["pt"]), tuple(it["color"]),
               round(rot, 3))
        hit = self._measure_img_cache.get(key)
        if hit is not None:
            return hit
        # 旋转后的外接框，取整成偶数：贴图落在整像素网格上，不会被二次采样
        rad = math.radians(rot)
        ca, sa = abs(math.cos(rad)), abs(math.sin(rad))
        bw = int(math.ceil(tw * ca + th * sa)) + 4
        bh = int(math.ceil(tw * sa + th * ca)) + 4
        bw += bw % 2
        bh += bh % 2
        # 超采样倍率：目标"相对逻辑尺寸约 3× 的采样"，高分屏上相应减小
        # （画布本身已按 devicePixelRatio 渲染，再叠 3× 只是徒增开销）
        dpr = max(1.0, float(self.devicePixelRatioF() or 1.0))
        ss = max(1, int(round(3.0 / dpr)))
        img = QImage(max(1, bw * ss), max(1, bh * ss),
                     QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        qp = QPainter(img)
        try:
            qp.setRenderHint(QPainter.Antialiasing)
            qp.setRenderHint(QPainter.TextAntialiasing)
            qp.scale(ss, ss)
            qp.translate(bw / 2.0, bh / 2.0)
            qp.rotate(rot)
            self._paint_measure_item(qp, it, f, tw, th)
        finally:
            qp.end()
        if len(self._measure_img_cache) > 64:
            self._measure_img_cache.clear()
        self._measure_img_cache[key] = (img, bw, bh)
        return img, bw, bh

    def _draw_measure_labels(self, p=None, w=None, h=None):
        """测量标注：标签 = 投影锚点 + 拖放偏移，支持每条独立的旋转/字号/字体/颜色。

        距离标注**不画连线**（键本身就画着，加线反而糊）；键角/二面角画虚线
        连线，否则光看一个数字分不清是哪几个原子。正在选择的原子用青色圆点
        标出并按顺序连线。

        p 为 None → 屏幕绘制（走 _measure_label_image 的离屏超采样贴图）；
        否则 p 是导出用的 QPainter（已按导出比例缩放），此时直接矢量填充——
        导出图本来分辨率就高，不需要再超采样。
        """
        if not self._measure_items and not self._measure_pair:
            return
        own = p is None
        if own:
            p = QPainter(self)
        w0 = max(1, w if w is not None else self.width())
        h0 = max(1, h if h is not None else self.height())
        try:
            p.setRenderHint(QPainter.Antialiasing)
            p.setRenderHint(QPainter.TextAntialiasing)
            # 正在选择的原子：青色圆圈标记 + 按顺序连线（键角/二面角时
            # 一眼看出已经点了哪几个）
            atoms = self._atom_list()
            picked_scr = []
            for idx in self._measure_pair:
                if idx >= len(atoms):
                    continue
                ax, ay, az = atoms[idx][1]
                sx, sy, vis = self._world_to_screen(ax, ay, az, w0, h0)
                if not vis:
                    picked_scr.append(None)
                    continue
                picked_scr.append((sx, sy))
                p.setPen(QPen(QColor(0, 190, 255), 2))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QPointF(sx, sy), 9.0, 9.0)
            if len(picked_scr) > 1:
                p.setPen(QPen(QColor(0, 190, 255), 1.6))
                for a, b in zip(picked_scr, picked_scr[1:]):
                    if a and b:
                        p.drawLine(QPointF(*a), QPointF(*b))
            # 键角 / 二面角：虚线连线（颜色随该条标注，改色时线也跟着变）
            for it in self._measure_items:
                segs = it.get("segs") or []
                pts = it.get("pts") or []
                if len(segs) < 2 or len(pts) < 3:
                    continue            # 距离标注不画线
                col = QColor(*it["color"])
                col.setAlpha(150)
                p.setPen(QPen(col, 1.2, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                for ia, ib in segs:
                    if ia >= len(pts) or ib >= len(pts):
                        continue
                    x1, y1, v1 = self._world_to_screen(*pts[ia], w0, h0)
                    x2, y2, v2 = self._world_to_screen(*pts[ib], w0, h0)
                    if not (v1 or v2):
                        continue        # 两端都在背面才不画
                    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            # 已完成测量：标签
            if own:
                p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            for it in self._measure_items:
                (cx, cy, vis), (tw, th) = self._measure_label_rect(it, w0, h0)
                if not vis:
                    continue
                if own:
                    img, bw, bh = self._measure_label_image(it)
                    # 整数像素落点：整块贴图取整，避免被二次插值采样
                    p.drawImage(QRectF(round(cx - bw / 2.0),
                                       round(cy - bh / 2.0), bw, bh), img)
                else:
                    f = self._measure_label_font(it)
                    p.save()
                    p.translate(cx, cy)
                    p.rotate(it["rot"])
                    self._paint_measure_item(p, it, f, tw, th)
                    p.restore()
        finally:
            if own:
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
            self._orbital_pair_mode = ["base"]
            self._orbital_gen += 1   # 轨道数据已重建：旧异步结果作废

            # Camera
            ctr, r = compute_bounding_sphere(cube)
            self._scene_r = r
            self.cam.set_center_zoom(ctr, r)

            # 新结构：按元素半径倍率恢复默认（不跨文件携带）
            self._elem_r_mult.clear()

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
            modes = []
            # 载入时的基准相位色（调用方一般先 set_phase_colors / 套样式再调用）
            base_pc = tuple(float(c) for c in self._pc)
            base_nc = tuple(float(c) for c in self._nc)
            for i, path in enumerate(cube_paths):
                if not os.path.exists(path):
                    continue
                cube = read_cube(path)
                pos = marching_cubes(cube, isovalue, False)
                neg = marching_cubes(cube, -isovalue, True)
                if color_pairs and i < len(color_pairs) and color_pairs[i]:
                    pc = tuple(float(c) / 255.0 for c in color_pairs[i][0])
                    nc = tuple(float(c) / 255.0 for c in color_pairs[i][1])
                    # 与基准同向 → 跟随基准；与基准正好反相 → 跟随基准的交换版；
                    # 其它（每轨道独立配色）→ 固定用自己这套，不跟基准变。
                    if pc == base_nc and nc == base_pc:
                        mode = "swapped"
                    elif pc == base_pc and nc == base_nc:
                        mode = "base"
                    else:
                        mode = "fixed"
                else:
                    pc = self._auto_orbital_color(i, True)
                    nc = self._auto_orbital_color(i, False)
                    mode = "fixed"
                recs.append((cube, pos, neg, pc, nc))
                modes.append(mode)

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
            self._orbital_pair_mode = modes
            self._orbital_gen += 1   # 轨道数据已重建：旧异步结果作废

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

    def set_orbitals_isovalue(self, v):
        """多轨道叠加时实时调整全局等值面（供 CUB 叠加面板等值滑块拖动用）。

        不复读文件、不改每轨道配色与翻转状态。marching cubes（全分辨率）在工作
        线程执行，主线程只负责把结果上传 GL，因此滑块拖动全程不阻塞界面；高频
        拖动时只保留最后一次请求，天然合帧。无轨道记录时退化为单 cube 的
        set_isovalue。
        """
        recs = getattr(self, "_orbital_recs", None)
        if not recs:
            self.set_isovalue(v)
            return
        if abs(self._isovalue - v) < 1e-6:
            return
        self._isovalue = v
        # 快照各轨道 cube 引用 + 配色 + 翻转状态（只读，可安全跨线程）
        flips = getattr(self, "_orbital_flipped", []) or []
        cubes = []
        for i, (cube, _old_pos, _old_neg, pc, nc) in enumerate(recs):
            if cube is None:
                continue
            flipped = bool(flips[i]) if i < len(flips) else False
            cubes.append((cube, pc, nc, flipped))
        job = (self._orbital_gen, float(v), cubes)
        if self._mc_busy:
            self._mc_pending = job    # 合并：只记最后一次请求
            return
        self._launch_mc_job(job)

    def _launch_mc_job(self, job):
        """把 job 交给工作线程（首次调用时懒启动线程与轮询计时器）。

        队列与结果列表随线程一并创建并绑定给该线程，取消/重建时整体换新，
        旧线程只会把结果写进它自己的旧列表，不会污染新批次。
        """
        if self._mc_queue is None:
            import queue as _queue
            q = _queue.Queue()
            results = []
            self._mc_queue = q
            self._mc_results = results
            self._mc_thread = threading.Thread(
                target=self._mc_runner, args=(q, results),
                daemon=True, name="ov-iso-mc")
            self._mc_thread.start()
        self._mc_busy = True
        self._mc_queue.put(job)
        self._mc_poll.start()   # 单发，处理完结果自动停止

    @staticmethod
    def _mc_runner(q, results):
        """工作线程主循环：串行执行 marching cubes，结果放入本线程的结果列表。"""
        while True:
            job = q.get()
            if job is None:
                break
            gen, iso, cubes = job
            try:
                pos, neg = CubGLWidget._compute_orbitals_meshes(cubes, iso)
                res = (gen, iso, True, pos, neg)
            except Exception:
                res = (gen, iso, False, None, None)
            results.append(res)

    @staticmethod
    def _compute_orbitals_meshes(cubes, iso):
        """全分辨率 marching cubes：每轨道提取正/负等值面，按各自颜色平铺后合并。

        纯 numpy/mcubes 计算，无任何 Qt/GL 调用，可安全跑在工作线程。
        """
        pos_chunks, neg_chunks = [], []
        for cube, pc, nc, flipped in cubes:
            pcol = (nc if flipped else pc)   # 沿用当前翻转状态
            ncol = (pc if flipped else nc)
            pos = marching_cubes(cube, iso, False)
            neg = marching_cubes(cube, -iso, True)
            pa = np.array([*pcol, 1.0], dtype=np.float32)
            na = np.array([*ncol, 1.0], dtype=np.float32)
            if pos.vertex_count > 0:
                pos.colors = np.tile(pa, (pos.vertex_count, 1))
                pos_chunks.append(pos)
            if neg.vertex_count > 0:
                neg.colors = np.tile(na, (neg.vertex_count, 1))
                neg_chunks.append(neg)
        return merge_iso_surfaces(pos_chunks), merge_iso_surfaces(neg_chunks)

    def _on_mc_poll(self):
        """主线程轮询：把已完成的网格换入表面并上传；有积压请求则续跑。"""
        had_results = bool(self._mc_results)
        if had_results:
            applied = False
            while self._mc_results:
                gen, iso, ok, pos, neg = self._mc_results.pop(0)
                if ok and gen == self._orbital_gen:
                    # 过期（期间发生了 load/reset）结果直接丢弃
                    self._pos_surf = pos
                    self._neg_surf = neg
                    self._surf_vcolor = False   # 相位色平铺表面，非 ESP 顶点色
                    applied = True
            if applied:
                self._needs_upload = True
                self.update()
        if self._mc_pending is not None:
            job, self._mc_pending = self._mc_pending, None
            self._launch_mc_job(job)
        elif had_results:
            # 本轮消化了最后一笔结果且无积压请求 → 空闲停表
            self._mc_busy = False
            self._mc_poll.stop()
        elif self._mc_busy:
            # job 还在计算中、结果未出：继续保持轮询
            self._mc_poll.start()

    def _cancel_mc(self):
        """场景重建时调用：让工作线程尽快结束，丢弃积压结果。"""
        self._mc_pending = None
        # 直接换新的结果列表/句柄：正在收尾的旧线程只写它持有的旧队列旧列表，
        # 不会污染重启后的新批次
        self._mc_results = []
        q = self._mc_queue
        self._mc_queue = None
        self._mc_thread = None
        if q is not None:
            try:
                q.put_nowait(None)   # 终止哨兵
            except Exception:
                pass
        self._mc_poll.stop()
        self._mc_busy = False

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
            # 粗糙度是全局用户偏好（GGX 高光斑点大小），切样式时不重置
            keep_rough = self._sp.get('roughness')
            # 次表面散射同为全局用户偏好（不随一键样式走），切样式时同样保留
            keep_sss = self._sp.get('sss_strength')
            # 景深雾化强度同为用户偏好（不随样式走）
            keep_fog = self._sp.get('FogWidth')
            # 背面调暗同为全局用户偏好（不随一键样式走）
            keep_back_dim = self._sp.get('back_dim')
            self._sp = style_params(sm, s)
            if keep_op is not None:
                self._sp['opacity'] = keep_op
            if keep_rough is not None:
                self._sp['roughness'] = keep_rough
            if keep_sss is not None:
                self._sp['sss_strength'] = keep_sss
            if keep_fog is not None:
                self._sp['FogWidth'] = keep_fog
            if keep_back_dim is not None:
                self._sp['back_dim'] = keep_back_dim
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
        # ESP 体着色样式（sob-esp0/1）：自带 volume_color 声明时，把色彩刻度轴
        # 设成它要求的配色与范围（vcube 的 color_scale=BWR / map_scale_value=
        # {-0.03 0.03}）。只在"当前确实有 ESP 体着色表面"时才动刻度轴，
        # 免得手上没有 ESP 数据却把用户自己调好的色标改掉。
        # 注意：表面顶点色本身不在这里重算 —— 它由 ESP 面板的 _apply_surface
        # 生成，且上面的 _surf_vcolor 判断已保证不会被相位单色平铺覆盖。
        vc = s.get('volume_color')
        if vc and self._surf_vcolor:
            self.set_color_scale_cmap(vc.get('cmap', 'BWR'))
            self.set_color_scale(vc.get('cmin', -0.03), vc.get('cmax', 0.03),
                                 unit='ESP (a.u.)')
        # 样式自带的 GL 观感：镜面模型（IboView 双瓣 Blinn / GGX / 清漆 / 材质球）
        gm = s.get('gl_model')
        # 未声明 gl_model 的样式回到默认 GGX：否则从 IboView 样式切走后会
        # 残留 Blinn，导致别的样式观感也跟着变（样式应各自可复现）。
        self._spec_model = _SPEC_MODEL_BY_NAME.get(str(gm).lower(), 1)
        # 该样式的寄存器基准（有则光泽滑块在它上面做倍率，见 _apply_gloss）
        self._style_regs = s.get('gl_regs') or None
        # 样式自带的布光（IboView 用的是 Mayavi 标准三点布光，方向/强度
        # 与画布默认的"自定"布光略有差异，观感会差在高光位置上）
        gl_lights = s.get('gl_lights')
        if gl_lights:
            dirs = gl_lights.get('dirs')
            if dirs:
                self.set_light_dirs([tuple(float(x) for x in d[:3])
                                     for d in dirs])
            n = gl_lights.get('count')
            if n:
                self.set_light_count(int(n))
        self._apply_gloss()
        self._needs_upload = True
        self.update()

    def set_phase_colors(self, pos_rgb=None, neg_rgb=None):
        """逐相位（正/负）覆盖等值面配色，供色轮使用。

        颜色以 0-255 元组传入（None 表示保持当前色）。仅更新 CPU 端
        颜色并标记 _needs_upload，由 paintGL 在有效 GL 上下文内重新上传，
        避免在信号回调中直接 makeCurrent 触发原生崩溃。这是常见的延迟上传（deferred upload）模式。

        多轨道（NBO E(2) 叠加）时：把各轨道的记录色**同步到新的基准色**，
        并保持"该轨道是否与基准反相"的关系，然后按轨道重新平铺+合并 ——
        这样换配色后各轨道仍然彼此可区分，而且后续「翻转相位」翻的是
        **当前**这套颜色（此前记录色停留在载入那一刻，翻转会把配色拽回旧值，
        表现为"一翻转就变色"，2026-09-27 修）。
        """
        if pos_rgb is not None:
            self._pc = tuple(float(c) / 255.0 for c in pos_rgb)
        if neg_rgb is not None:
            self._nc = tuple(float(c) / 255.0 for c in neg_rgb)
        recs = getattr(self, "_orbital_recs", None)
        if recs and not self._surf_vcolor:
            modes = getattr(self, "_orbital_pair_mode", []) or []
            single_base = (len(recs) == 1
                           and (modes[0] if modes else "base") == "base")
            if single_base:
                # 单轨道快路径：直接把新配色平铺到合并表面上（不必重新合并
                # 网格）；记录里的"未翻转基准色"同步成新值，这样下一句
                # flip_orbital() 翻的就是当前这套色。翻转状态照旧生效。
                cube, pos, neg, _pc0, _nc0 = recs[0]
                self._orbital_recs = [(cube, pos, neg, self._pc, self._nc)]
                flip = bool(self._orbital_flipped[0]) if self._orbital_flipped else False
                p = self._nc if flip else self._pc
                n = self._pc if flip else self._nc
                if self._pos_surf is not None and pos_rgb is not None:
                    c = np.array([*p, 1.0], dtype=np.float32)
                    self._pos_surf.colors = np.tile(
                        c, (self._pos_surf.vertex_count, 1))
                if self._neg_surf is not None and neg_rgb is not None:
                    c = np.array([*n, 1.0], dtype=np.float32)
                    self._neg_surf.colors = np.tile(
                        c, (self._neg_surf.vertex_count, 1))
                self._needs_upload = True
                self.update()
                return
            # 多轨道：同步每轨道的记录色后按轨道重铺（保留"反相轨道"关系）
            self._sync_rec_colors()
            self._rebuild_orbital_meshes()
            return
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

    def _sync_rec_colors(self):
        """把各轨道记录里的相位色对齐到**当前**基准色。

        只改记录里的颜色，不动几何（pos/neg 网格对象），因此很轻。
        mode = "fixed" 的轨道保留自己的独立配色。
        """
        recs = getattr(self, "_orbital_recs", None) or []
        if not recs:
            return
        modes = getattr(self, "_orbital_pair_mode", []) or []
        out = []
        for i, (cube, pos, neg, pc, nc) in enumerate(recs):
            mode = modes[i] if i < len(modes) else "base"
            if mode == "base":
                pc, nc = self._pc, self._nc
            elif mode == "swapped":
                pc, nc = self._nc, self._pc
            out.append((cube, pos, neg, pc, nc))
        self._orbital_recs = out

    def flip_phase(self):
        """翻转相位：交换正/负相位颜色（等价于交换正负色的 swap 操作）。多轨道（_orbital_recs）时等价于
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
        # 注意：**不要**在这里用 recs[0] 的颜色回写 self._pc/self._nc。
        # 基准色是"用户当前选的正/负色"（样式或色轮给的），记录里的颜色只是
        # 按基准推出来的每轨道值（可能是交换版或独立配色）。回写会把基准带偏：
        # 例如 E(2) 双轨道里第 0 个是"反相"轨道时，基准会被改成反过来的一对，
        # 之后换配色/翻转就都跟着错。
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

    def _apply_gloss(self):
        """把当前 gloss 值写入 a_reg/o_reg 的镜面强度槽，使光泽在样式/
        分子风格切换后仍保留。"""
        if self._style_name is None and not self._sp:
            return
        sr = getattr(self, "_style_regs", None)
        if sr:
            # 样式自带 IboView 寄存器：滑块在**样式基准**上做倍率
            # （默认档 = 1.0 → 与 IboView 原版一致；0 = 哑光；>1 = 更亮）
            k = float(self._gloss) / max(_GLOSS_DEFAULT, 1e-6)
            if sr.get('atom'):
                self._sp['a_reg'][2] = float(sr['atom'][2]) * k
            if sr.get('orb'):
                self._sp['o_reg'][2] = float(sr['orb'][2]) * k
            return
        # 原子镜面 0.30～2.00；等值面减半——半透明面多层叠加会累积高光，
        # 同一镜面值下等值面显得比原子更亮，故单独压暗。
        spec_atom = _GLOSS_SPEC_MAX * self._gloss
        self._sp['a_reg'][2] = spec_atom
        self._sp['o_reg'][2] = spec_atom * 0.5

    def set_gloss(self, value):
        """动态调节光泽（镜面高光强度）。value ∈ [0, 1]。"""
        self._gloss = max(0.0, min(1.0, float(value)))
        self._apply_gloss()
        self._needs_upload = True
        self.update()

    def set_roughness(self, value):
        """设置 GGX 微表面粗糙度（0.03..1，越小越镜面、高光越集中）。"""
        self._sp['roughness'] = max(0.03, min(1.0, float(value)))
        self.update()

    def set_coat_roughness(self, value):
        """设置 Clear-coat 清漆层粗糙度（0.03..1，通常很锐）。"""
        self._sp['coat_roughness'] = max(0.03, min(1.0, float(value)))
        self.update()

    def set_coat_strength(self, value):
        """设置 Clear-coat 清漆层强度（0..2）。"""
        self._sp['coat_strength'] = max(0.0, min(2.0, float(value)))
        self.update()

    def set_sss_strength(self, value):
        """设置次表面散射强度（0..1，0=关闭走标准 Lambert）。

        仅对多灯 Phong 路径生效；Matcap（u_SpecModel==3）完全替代光照，不受影响。
        """
        self._sp['sss_strength'] = max(0.0, min(1.0, float(value)))
        self.update()

    # ── 半球环境光（Hemisphere Lighting）──
    # 各参数为 None 时保持原值，便于只改其中一项。
    def set_hemisphere(self, enabled=None, top=None, bottom=None,
                       intensity=None):
        """配置半球环境光。

        enabled   开关（None=不变）
        top       天顶色 (r,g,b) 0..1
        bottom    地面色 (r,g,b) 0..1
        intensity 强度 0..1

        仅作为环境漫反射补光叠加进 RGB，不参与镜面项、不改 alpha。
        """
        if enabled is not None:
            self._hemi_enabled = bool(enabled)
        if top is not None:
            self._hemi_top = tuple(max(0.0, min(1.0, float(c))) for c in top[:3])
        if bottom is not None:
            self._hemi_bottom = tuple(
                max(0.0, min(1.0, float(c))) for c in bottom[:3])
        if intensity is not None:
            self._hemi_intensity = max(0.0, min(1.0, float(intensity)))
        self.update()

    def set_soft_term(self, value):
        """设置明暗交界线柔化强度（0..1）。

        0 = 标准 Lambert（原始观感，terminator 较锐利）；
        1 = Half-Lambert（背光侧也受光，交界极柔和）。
        只影响漫反射，高光不受影响。
        """
        self._soft_term = max(0.0, min(1.0, float(value)))
        self.update()

    def set_back_dim(self, value):
        """设置等值面背面调暗系数（0.1..1.0）。

        只对双面渲染的轨道等值面生效（shade_base_color(two_sided) 与
        mv_orb_color 两条路径）；原子球/键为单面材质，不受影响。
        1.0 = 关闭（画面与旧版逐位一致）；0.8 左右可让半透明波瓣读出厚度感。
        """
        self._sp['back_dim'] = max(0.1, min(1.0, float(value)))
        self.update()

    def back_dim(self):
        """查询当前背面调暗系数（默认 0.8）。"""
        return float(self._sp.get('back_dim', 0.8))

    def hemisphere(self):
        """查询半球环境光配置 (enabled, top, bottom, intensity)。"""
        return (bool(getattr(self, '_hemi_enabled', False)),
                tuple(getattr(self, '_hemi_top', (0.18, 0.18, 0.18))),
                tuple(getattr(self, '_hemi_bottom', (0.035, 0.035, 0.035))),
                float(getattr(self, '_hemi_intensity', 0.25)))

    def set_spec_model(self, mode):
        """切换镜面高光模型：0=Blinn-Phong，1=GGX，2=Clear-coat，3=Matcap。"""
        m = int(mode)
        self._spec_model = m if m in (0, 1, 2, 3) else 1
        self.update()

    def set_matcap(self, name):
        """切换 Matcap 材质球预设（'studio'/'glossy'/'matte'/'metal'）。"""
        if name not in _MATCAP_PRESETS:
            return
        self._matcap_name = name
        self._matcap_dirty = True
        self.update()

    def matcap(self):
        """查询当前 Matcap 预设名。"""
        return getattr(self, "_matcap_name", "studio")

    def _upload_matcap(self):
        """把当前预设的 matcap 图上传为 GL 纹理（R=乘性环境，G=加性白色反射）。"""
        img = _make_matcap_image(**_MATCAP_PRESETS[self._matcap_name])
        if not self._matcap_tex:
            self._matcap_tex = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, self._matcap_tex)
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RG8, img.shape[1], img.shape[0], 0,
                     GL_RG, GL_UNSIGNED_BYTE, img.tobytes())
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glBindTexture(GL_TEXTURE_2D, 0)

    def spec_model(self):
        """查询当前镜面高光模型（0/1/2）。"""
        return int(getattr(self, "_spec_model", 1))

    def set_shininess(self, name):
        """兼容历史光泽预设名；新代码请用 set_gloss(value)。"""
        g = _LEGACY_SHININESS_TO_GLOSS.get(name)
        if g is None:
            return
        self.set_gloss(g)

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

    def set_bond_gloss(self, value):
        """独立调节化学键的镜面光泽（0..1）；None = 跟随全局光泽滑块。

        只影响键的镜面高光强度（键重绘趟的寄存器），不改原子。
        """
        if value is None:
            self._bond_gloss = None
        else:
            self._bond_gloss = max(0.0, min(1.0, float(value)))
        self.update()

    def set_bond_diffuse(self, k):
        """化学键面亮度系数（0.2..1.6；1.0 = 满漫反射原色，默认 0.8）。"""
        self._bond_diffuse = max(0.2, min(1.6, float(k)))
        self.update()

    def reset_bond_style(self):
        """化学键样式恢复默认：跟随分子风格配色、跟随全局光泽、默认亮度。

        多重键几何参数（子键半径 / 线间距）一并回到默认值。
        """
        changed = (self._bond_color is not None or self._bond_gloss is not None
                   or abs(self._bond_diffuse - 0.8) > 1e-6
                   or abs(self._multi_bond_radius - MULTI_BOND_RADIUS_DEFAULT) > 1e-6
                   or abs(self._multi_bond_gap - MULTI_BOND_GAP_DEFAULT) > 1e-6)
        self._bond_color = None
        self._bond_gloss = None
        self._bond_diffuse = 0.8
        self._multi_bond_radius = MULTI_BOND_RADIUS_DEFAULT
        self._multi_bond_gap = MULTI_BOND_GAP_DEFAULT
        if changed and (self._molecule is not None or self._cube is not None):
            self._gen_atoms()
            self._needs_upload = True
        self.update()

    def set_multi_bond_params(self, sub_radius=None, gap=None):
        """多重键（双键/三键/离域键）几何参数。

        sub_radius：子键半径 / 单键半径（0.20 ~ 1.00；默认 1.00 = 与单键等粗）
        gap       ：相邻子键中心距 / 子键半径（1.50 ~ 5.00；默认 3.00）
                    净空 = (gap − 2) × 子键半径；子键等粗时 gap 必须 > 2.0
                    两根线才不粘连，默认 3.00 留出 1 倍子键半径（半条线宽）
                    的净空，两根线清晰可分。
        None = 保持当前值。改完立即重建分子网格（多重键几何变了）。
        """
        changed = False
        if sub_radius is not None:
            v = max(0.20, min(1.00, float(sub_radius)))
            changed |= abs(v - self._multi_bond_radius) > 1e-9
            self._multi_bond_radius = v
        if gap is not None:
            v = max(1.50, min(5.00, float(gap)))
            changed |= abs(v - self._multi_bond_gap) > 1e-9
            self._multi_bond_gap = v
        if changed and (self._molecule is not None or self._cube is not None):
            self._gen_atoms()
            self._needs_upload = True
        self.update()
        return (self._multi_bond_radius, self._multi_bond_gap)

    def multi_bond_params(self):
        """当前多重键几何参数 (子键半径系数, 线间距系数)。"""
        return (self._multi_bond_radius, self._multi_bond_gap)

    def bond_gloss(self):
        return self._bond_gloss

    def bond_diffuse(self):
        return self._bond_diffuse

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

        name 为空或 None → 回退三灯 Phong（u_MvGrad=0）。
        同时按模式设定默认灯方向与数量（单光/双光/四光/三光）。
        """
        if not name:
            self._mv_grad = 0
            self._light_default_dirs = list(_PHONG_LIGHT_DIRS)
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

    def set_orb_alpha_mod(self, v):
        """等值面 alpha 的光照调制强度（1 = 调制，0 = 由透明度滑块线性控制）。

        1 是 IboView 的原始观感：亮处实、暗处虚，代价是 alpha 被压到
        0.6~0.8，滑块在接近全不透明处变化很陡（见 shade_base_color 的注释）。
        MolStudio / CYLview / VESTA 这类"默认全不透明"的样式取 0，让滑块全程
        线性（等值面，含 ESP / IGMH 属性着色表面）；其余样式保持 1，观感不变。
        """
        self._orb_alpha_mod = 0.0 if float(v) <= 0.0 else 1.0
        self.update()

    def orb_alpha_mod(self):
        return float(getattr(self, "_orb_alpha_mod", 1.0))

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
        """设置表面材质（vcube/VMD 材质的近似映射），等值面与原子/键统一生效。

        ambient:  自发光/环境项（VMD ambient，0..1+）
        spec_mul: 高光强度倍率（VMD specular，0..1+）

        注：样式（STYLES）自带的 ambient/spec_mul 仍只作用于等值面，避免切换
        一键样式时改变球棍模型观感；这里记录的是**用户手动值**，对原子/键也
        生效，否则面板上的滑块对球棍模型完全无反应（旧实现即如此）。
        """
        if ambient is not None:
            self._sp['ambient'] = max(0.0, float(ambient))
            self._user_ambient = max(0.0, float(ambient))
        if spec_mul is not None:
            self._sp['spec_mul'] = max(0.0, float(spec_mul))
            self._user_spec_mul = max(0.0, float(spec_mul))
        self.update()

    def set_light_dirs(self, dirs):
        """自定义光源方向（视图空间方向，3 个 (x,y,z)，用于三光等照明）。

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
        """清除 MolViewer 预设效果，恢复默认球棍观感。

        不触碰等值面风格（STYLE_NAMES）与相位配色。
        """
        self._mv_grad = 0
        self._bg_grad = None
        self._bg = (1.0, 1.0, 1.0, 1.0)
        self._bond_color = None
        self._bond_gloss = None
        self._bond_diffuse = 0.8
        self.set_mol_style("CPK")
        self.set_gloss(_GLOSS_DEFAULT)
        self.set_atom_scale(1.68)
        self.set_bond_scale(2.0)
        # 氢跟随键半径是样式规则，换样式时一并复位（CYLview 会在套用时重新打开）
        self._h_bond_radius = False
        self.set_atom_outline(False)
        self.set_shadows(False)
        self.set_crosshair(False)
        self.set_ring_style((0.05, 0.05, 0.05), 0.07)
        self.set_ring_orientation(90, 71, 205, 0, locked=False)
        self.set_atom_labels(2)
        self.set_orb_outline(False)
        # 等值面 alpha 回到"受光照调制"的默认观感（半透明样式的基准）
        self.set_orb_alpha_mod(1.0)
        # 景深雾化：一键样式一律**默认不打开**（要雾化用面板滑块自己开）。
        # 放在这里而不是每个样式字典里，是为了让没有自带 fade 字段的样式
        # 按钮（如 IQmol 走的是逐步设置而非整字典套用）也不会残留上一个
        # 样式的雾化状态。
        self.set_fade_enabled(False)
        # 等值面不透明度回到默认（ESP 顶点色表面除外：不透明度归 ESP 面板管）
        if not self._surf_vcolor:
            self._sp['opacity'] = float(_RENDER_DEFAULTS.get('OrbitalOpacity', 1.0))
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
        """当前 u_MvGrad → 渐变类型名（"" = 三光 Phong）。"""
        return _MV_GRAD_BY_ID.get(self._mv_grad, "")

    def get_style_state(self):
        """导出当前样式状态（JSON 可序列化），供「保存样式」使用。"""
        return {
            "mol_style": self._mol_style,
            "gradient": self._mv_grad_name(),
            "gloss": self._gloss,
            "light_count": self._light_count,
            "light_dirs": [list(d) for d in self._light_dirs],
            "light_glow": self._light_glow,
            "light_glows": list(self._light_glows),
            "atom_scale": self._atom_scale,
            "bond_scale": self._bond_scale,
            # 氢原子球半径是否跟随键半径（CYLview：H 与键一样粗）
            "h_bond_radius": self._h_bond_radius,
            # 多重键几何（子键半径系数、线间距系数）；逐键的双/三键指定
            # 属于场景内容而非样式，不入样式文件（见 _bond_overrides 注释）
            "multi_bond": [self._multi_bond_radius, self._multi_bond_gap],
            # 虚线样式（'dots' 点阵 / 'dashes' 短圆柱段）
            "dash_style": self._dash_style,
            # 成键模式（'single' 一律单键 / 'auto' 按键长自动判定键型）
            "bond_mode": self._bond_mode,
            "atom_outline": [self._atom_outline,
                             list(self._atom_outline_color),
                             self._atom_outline_width],
            "orb_outline": [self._orb_outline,
                            list(self._orb_outline_color),
                            self._orb_outline_width],
            "orb_opacity": self._sp.get('opacity', 1.0),
            # 等值面 alpha 是否被光照调制（0 = 透明度滑块线性控制，见
            # shade_base_color 与各一键样式字典的 orb_alpha_mod）
            "orb_alpha_mod": float(getattr(self, "_orb_alpha_mod", 1.0)),
            "phase_pos": list(self._pc),
            "phase_neg": list(self._nc),
            "bg": list(self._bg),
            "crosshair": self._crosshair,
            "fade": self._fade_enabled,
            "fog_strength": float(self._sp.get('FogWidth', 0.0)),
            # 着色寄存器（含样式自带的 IboView 基准）：保存样式时一并存下，
            # 载入后才能复现同一套高光形态（否则只剩 gloss 推导值）
            "shader_regs": {"atom": list(self._sp.get('a_reg', [])),
                            "orb": list(self._sp.get('o_reg', []))},
            "style_regs": ({k: list(v) for k, v in self._style_regs.items()}
                           if self._style_regs else None),
            "post": [self._post_on, self._post_scale, self._post_edge,
                     self._post_edge_r, self._post_tone, self._post_vig,
                     self._post_ao, self._post_ao_r, self._post_ao_d],
            "carbon": list(self._carbon_rgb) if self._carbon_rgb else None,
            "hydrogen": list(self._hydrogen_rgb) if self._hydrogen_rgb else None,
            "hide_hydrogens": self._hide_hydrogens,
            "keep_h_atoms": sorted(self._keep_h_atoms),
            "atom_labels": self._atom_labels,
            # ── 光照 / 材质（原先未存档，切换样式会丢）──
            "spec_model": int(getattr(self, "_spec_model", 1)),
            "matcap": self.matcap(),
            "roughness": float(self._sp.get('roughness', 0.45)),
            "coat_roughness": float(self._sp.get('coat_roughness', 0.10)),
            "coat_strength": float(self._sp.get('coat_strength', 0.80)),
            "sss_strength": float(self._sp.get('sss_strength', 0.0)),
            "soft_term": float(getattr(self, "_soft_term", 0.0)),
            "back_dim": float(self._sp.get('back_dim', 0.8)),
            # 色彩空间（B 方案）：False = sRGB 直通（默认）
            "linear_space": bool(getattr(self, "_linear_space", False)),
            # 半球环境光
            "hemi_enabled": bool(getattr(self, "_hemi_enabled", False)),
            "hemi_top": list(getattr(self, "_hemi_top", (0.18, 0.18, 0.18))),
            "hemi_bottom": list(getattr(self, "_hemi_bottom",
                                        (0.035, 0.035, 0.035))),
            "hemi_intensity": float(getattr(self, "_hemi_intensity", 0.25)),
            # 背景三段渐变（None = 纯色背景）
            "bg_grad": ([list(float(x) for x in c) for c in self._bg_grad]
                        if getattr(self, "_bg_grad", None) else None),
            # ── 以下原先漏存，导致「保存样式 → 载入」回来参数对不上 ──
            # （逐控件往返审计 _style_roundtrip_probe.py 抓出来的，实测
            #   79 个可调控件里有 30 个没能往返。）
            # 等值面配色（等值面观感的主开关）
            "style_name": self._style_name,
            # 透明合成三件套
            "transparency_mode": self._transparency_mode,
            "oit_falloff": float(self._oit_falloff),
            "peel_layers": int(self._peel_layers),
            # 键的形态
            "bond_thinning": float(self._bond_thinning),
            "dot_size": float(self._dot_size_scale),
            "dot_spacing": float(self._dot_spacing_scale),
            # 选中标记
            "sel_marker": getattr(self, "_sel_marker_shape", "wrap"),
            "sel_pulse": bool(getattr(self, "_sel_pulse_on", False)),
            # vdW 外壳（六项一起；不含"仅选中片段"——那是场景内容）
            "vdw": [bool(self._vdw_mode), bool(self._vdw_shell),
                    float(self._vdw_shell_alpha), float(self._vdw_scale),
                    bool(self._vdw_outline),
                    list(self._vdw_outline_color),
                    float(self._vdw_outline_width)],
            # 元素级覆盖（元素颜色对话框 / 元素半径对话框）
            # 键转成字符串：JSON 的对象键只能是字符串，读回时再转 int
            "element_colors": {str(int(k)): [float(c) for c in v]
                               for k, v in
                               getattr(self, "_element_color_overrides",
                                       {}).items()},
            "element_radii": {str(int(k)): float(v)
                              for k, v in
                              getattr(self, "_elem_r_mult", {}).items()},
            # 化学键样式三件套（原先漏存：设过「统一键色」后保存样式再载入会丢）
            "bond_color": (list(self._bond_color)
                           if self._bond_color is not None else None),
            "bond_gloss": (float(self._bond_gloss)
                           if self._bond_gloss is not None else None),
            "bond_diffuse": float(getattr(self, "_bond_diffuse", 0.8)),
            # 十字圆环（方位角/俯仰角/宽度/颜色/锁定）
            "ring": [float(self._ring_az1), float(self._ring_tilt1),
                     float(self._ring_az2), float(self._ring_tilt2),
                     float(self._ring_width), list(self._ring_color),
                     bool(self._ring_locked)],
        }

    def apply_style_state(self, st):
        """应用导出的样式状态（「载入样式」）。"""
        if not isinstance(st, dict):
            return
        ms = st.get("mol_style")
        if ms in MOL_STYLE_NAMES:
            self.set_mol_style(ms)
        self.set_mv_gradient(st.get("gradient", ""))
        # 等值面配色：必须放在**材质块之前** —— set_style() 会整体重建 _sp
        # （style_params），放后面会把文件里显式存的粗糙度/清漆/次表面等覆盖掉。
        # 放在这里则与 set_mol_style / set_mv_gradient 同级，后面的材质值最后生效。
        if st.get("style_name"):
            self.set_style(str(st["style_name"]))
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
        # 着色寄存器基准：必须**先于** gloss 确定 —— _apply_gloss() 要用基准把
        # gloss 换算成镜面槽 a_reg[2]/o_reg[2]。
        #   · 声明了 style_regs 的样式（IboView 系）：用样式自带基准；
        #   · 半量字典（一键样式 MolStudio/CYLview 等，既无 style_regs 也无
        #     shader_regs）：视为"无基准"，必须清掉 _style_regs —— 否则上一个
        #     IboView 样式留下的 gl_regs 会把 gloss 换算到错误量级，
        #     同一个样式按钮在不同前置状态下出图不一致（观感不可复现）。
        # 用 `in` 判空：JSON 里 style_regs=None 表示"该样式没有自带基准"，
        # 必须显式清掉，否则会残留上一个样式的基准。
        if "style_regs" in st:
            sr0 = st["style_regs"]
            self._style_regs = ({k: [float(x) for x in v]
                                 for k, v in sr0.items()} if sr0 else None)
        elif not isinstance(st.get("shader_regs"), dict):
            self._style_regs = None
        if "gloss" in st:
            self.set_gloss(st["gloss"])
        elif st.get("shininess") is not None:
            self.set_shininess(st["shininess"])   # 旧格式兼容
        if "atom_scale" in st:
            self.set_atom_scale(st["atom_scale"])
        if "bond_scale" in st:
            self.set_bond_scale(st["bond_scale"])
        # 氢原子球半径跟随键半径（CYLview：H 与键一样粗）。必须在 bond_scale
        # 之后 —— 规则取的是"当前键半径"，先设键粗细再开规则才不会错位。
        if "h_bond_radius" in st:
            self.set_hydrogen_bond_radius(bool(st["h_bond_radius"]))
        if st.get("multi_bond"):
            mb = list(st["multi_bond"]) + [None, None]
            self.set_multi_bond_params(mb[0], mb[1])
        if st.get("dash_style") in DASH_STYLE_NAMES:
            self.set_dash_style(st["dash_style"])
        if st.get("bond_mode") in BOND_MODE_NAMES:
            self.set_bond_mode(st["bond_mode"])
        if st.get("atom_outline"):
            on, col, w = st["atom_outline"]
            self.set_atom_outline(bool(on), tuple(float(x) for x in col), float(w))
        if st.get("orb_outline"):
            on, col, w = st["orb_outline"]
            self.set_orb_outline(bool(on), tuple(float(x) for x in col), float(w))
        if "orb_opacity" in st:
            self.set_opacity(max(0.0, min(1.0, float(st["orb_opacity"]))))
        # 等值面 alpha 的调制开关：样式字典没写就回到 1（调制），避免上一个
        # 「线性」样式（MolStudio / CYLview / VESTA）把状态黏给后面的样式。
        self.set_orb_alpha_mod(float(st.get("orb_alpha_mod", 1.0)))
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
        if st.get("fog_strength") is not None:
            self.set_fog_strength(float(st["fog_strength"]))
        sr = st.get("shader_regs")
        if isinstance(sr, dict):
            if sr.get("atom"):
                self._sp['a_reg'] = [float(x) for x in sr["atom"][:4]]
            if sr.get("orb"):
                self._sp['o_reg'] = [float(x) for x in sr["orb"][:4]]
        if st.get("post"):
            p = list(st["post"])

            def _at(i, dflt):
                return float(p[i]) if len(p) > i else dflt

            self.set_postprocess(bool(p[0]), _at(1, 1.5), _at(2, 0.0),
                                 _at(3, 2.0), _at(4, 0.0), _at(5, 0.0),
                                 _at(6, 0.0), _at(7, 8.0), _at(8, 0.15))
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
        # ── 光照 / 材质：放在最后恢复 ──
        # set_mol_style / set_mv_gradient 等可能重建 _sp，靠后设置才不被覆盖。
        # 一律用 `in st` 判空：旧样式文件没有这些字段时保持用户当前值，不重置。
        if "spec_model" in st:
            self.set_spec_model(int(st["spec_model"]))
        if st.get("matcap"):
            self.set_matcap(str(st["matcap"]))
        if "roughness" in st:
            self.set_roughness(float(st["roughness"]))
        if "coat_roughness" in st:
            self.set_coat_roughness(float(st["coat_roughness"]))
        if "coat_strength" in st:
            self.set_coat_strength(float(st["coat_strength"]))
        if "sss_strength" in st:
            self.set_sss_strength(float(st["sss_strength"]))
        if "soft_term" in st:
            self.set_soft_term(float(st["soft_term"]))
        if "back_dim" in st:
            self.set_back_dim(float(st["back_dim"]))
        if "linear_space" in st:
            self.set_linear_space(bool(st["linear_space"]))
        # 半球环境光：字段缺失时各参数为 None = 保持原值，故可无条件调用
        self.set_hemisphere(
            enabled=st.get("hemi_enabled"),
            top=(tuple(float(x) for x in st["hemi_top"][:3])
                 if st.get("hemi_top") else None),
            bottom=(tuple(float(x) for x in st["hemi_bottom"][:3])
                    if st.get("hemi_bottom") else None),
            intensity=st.get("hemi_intensity"))
        # 背景三段渐变：必须在 "bg" 之后恢复（bg 会把 _bg_grad 置 None）
        if st.get("bg_grad"):
            _g = st["bg_grad"]
            if len(_g) >= 3:
                self._bg_grad = tuple(
                    tuple(float(x) for x in c[:3]) for c in _g[:3])

        # ── 原先漏掉的项 ──（一律用 `in st` 判空：旧样式文件没有这些字段时
        #    保持用户当前值，不重置）
        # 元素级覆盖放在最前面清空再设：与元素半径同理，保存的字典是权威值
        if "element_colors" in st:
            ec = st["element_colors"] or {}
            self.set_element_colors(
                {int(k): tuple(float(c) for c in v) for k, v in ec.items()})
        if "element_radii" in st:
            self.reset_element_radii()
            for k, v in (st["element_radii"] or {}).items():
                self.set_element_radius(int(k), float(v))
        # 化学键样式三件套：`in st` 判空 —— 旧样式文件没有这些键时保持用户当前值。
        # 一键样式（reset_molviewer_style 会先把它们清干净）走的是显式写入，
        # 所以"点了 VESTA 再点别的样式"不会把灰键色带过去。
        if "bond_color" in st:
            _bc = st["bond_color"]
            self.set_bond_color(tuple(float(x) for x in _bc[:3])
                                if _bc else None)
        if "bond_gloss" in st:
            _bg = st["bond_gloss"]
            self.set_bond_gloss(float(_bg) if _bg is not None else None)
        if st.get("bond_diffuse") is not None:
            self.set_bond_diffuse(float(st["bond_diffuse"]))
        if st.get("ring"):
            r = list(st["ring"]) + [None] * 7
            self.set_ring_style(color=(tuple(float(x) for x in r[5][:3])
                                       if r[5] else None),
                                width=(float(r[4]) if r[4] is not None else None))
            self.set_ring_orientation(
                az1=(float(r[0]) if r[0] is not None else None),
                tilt1=(float(r[1]) if r[1] is not None else None),
                az2=(float(r[2]) if r[2] is not None else None),
                tilt2=(float(r[3]) if r[3] is not None else None),
                locked=(bool(r[6]) if r[6] is not None else None))
        if st.get("vdw"):
            v = list(st["vdw"]) + [None] * 7
            self.set_vdw_mode(bool(v[0]))
            self.set_vdw_shell(bool(v[1]),
                               alpha=(float(v[2]) if v[2] is not None else None))
            self.set_vdw_scale(float(v[3]) if v[3] is not None else 1.0)
            self.set_vdw_outline(
                bool(v[4]),
                color=(tuple(float(x) for x in v[5][:3]) if v[5] else None),
                width=(float(v[6]) if v[6] is not None else None))
        if st.get("transparency_mode"):
            self.set_transparency_mode(str(st["transparency_mode"]))
        if "oit_falloff" in st:
            self.set_oit_falloff(float(st["oit_falloff"]))
        if "peel_layers" in st:
            self.set_peel_layers(int(st["peel_layers"]))
        if "bond_thinning" in st:
            self.set_bond_thinning(float(st["bond_thinning"]))
        if "dot_size" in st:
            self.set_dot_size(float(st["dot_size"]))
        if "dot_spacing" in st:
            self.set_dot_spacing(float(st["dot_spacing"]))
        if st.get("sel_marker"):
            self.set_selection_marker_shape(str(st["sel_marker"]))
        if "sel_pulse" in st:
            self.set_selection_marker_pulse(bool(st["sel_pulse"]))
        self._needs_upload = True
        self.update()

    def set_transparency_mode(self, mode):
        """选择透明合成算法。

        mode:
          "oit"    — Weighted Blended OIT（单趟，McGuire & Bavoil 2013）
          "peel"   — Depth peeling（多趟，Everitt 2001，本项目独立实现）
          "sorted" — 画家算法排序混合（最省资源，观感最差）

        未知值按 "oit" 处理。所选算法不可用时，渲染分派会逐级回退到
        其余可用算法（见 _render_transparency）。
        """
        m = str(mode or "oit").lower()
        if m not in ("oit", "peel", "sorted"):
            m = "oit"
        if m != self._transparency_mode:
            self._transparency_mode = m
            self.update()
        return self._transparency_mode

    def get_transparency_mode(self):
        return self._transparency_mode

    def set_oit_falloff(self, k):
        """WBOIT 深度衰减强度。

        k 越大，越靠前的等值面在加权平均中占比越高，观感越接近
        depth peeling（前层主导、通透）；k=0 则前后等权，整体会偏暗。
        默认 4.0。
        """
        try:
            k = float(k)
        except (TypeError, ValueError):
            return self._oit_falloff
        k = max(0.0, min(12.0, k))
        if k != self._oit_falloff:
            self._oit_falloff = k
            self.update()
        return self._oit_falloff

    def get_oit_falloff(self):
        return self._oit_falloff

    def set_peel_layers(self, n):
        """深度剥离趟数上限（1..8）。

        趟数越多，多层交叠的等值面越精确，但开销按趟数线性增长。
        默认 4；分子等值面通常只有 1-3 层交叠。
        """
        try:
            n = int(n)
        except (TypeError, ValueError):
            return self._peel_layers
        n = max(1, min(8, n))
        if n != self._peel_layers:
            self._peel_layers = n
            self.update()
        return self._peel_layers

    def get_peel_layers(self):
        return self._peel_layers

    def set_fade_enabled(self, enabled):
        """景深雾化（远处蒙白雾）开关。默认开启。"""
        self._fade_enabled = bool(enabled)
        self.update()

    def set_fog_strength(self, value):
        """景深雾化强度 0..2：场景**最深处**向背景色渐变的幅度。

        雾化按视图空间线性深度计算（见 _GLSL_COMMON.fog_factor）：
        0 = 关闭；0.6 = 最深处 60% 融入背景；1.0 = 最深处完全融入背景；
        >1（最高 2.0）让雾在更浅的深度就饱和，空气透视感更强。
        分子/轨道可见深度范围通常不大，想让景深明显可见请调高本值。
        """
        self._sp['FogWidth'] = max(0.0, min(2.0, float(value)))
        self.update()

    def fog_strength(self):
        """当前景深雾化强度（0..1）。"""
        return float(self._sp.get('FogWidth', 0.0))

    # ── 实时后处理（超采样抗锯齿 + 边缘暗化）──────────────────────────
    def set_postprocess(self, enabled=None, scale=None, edge=None, radius=None,
                        tone=None, vig=None, ao=None, ao_radius=None,
                        ao_depth=None):
        """实时后处理开关与参数（任一为 None 表示不改）。

        enabled:   总开关（关 = 与改动前逐位一致的直出路径，零开销）
        scale:     超采样倍率 1.0 / 1.5 / 2.0
        edge:      边缘暗化强度 0..0.8（0 = 关）
        radius:    暗化采样半径（目标像素）1..5：1 = 细轮廓线，3~4 = 柔和阴影
        tone:      色调映射强度 0..1（ACES filmic；0 = 关）
        vig:       暗角强度 0..0.5（0 = 关）
        ao:        SSAO 强度 0..1（0 = 关；关掉即跳过深度预通道与 AO pass）
        ao_radius: 采样环半径（像素，屏幕空间）4..32
        ao_depth:  深度凹陷达到多少世界单位算"完全遮蔽"（越小越敏感）0.01..1.0
        """
        if enabled is not None:
            self._post_on = bool(enabled)
        if scale is not None:
            self._post_scale = max(1.0, min(2.0, float(scale)))
        if edge is not None:
            self._post_edge = max(0.0, min(0.8, float(edge)))
        if radius is not None:
            self._post_edge_r = max(1.0, min(5.0, float(radius)))
        if tone is not None:
            self._post_tone = max(0.0, min(1.0, float(tone)))
        if vig is not None:
            self._post_vig = max(0.0, min(0.5, float(vig)))
        if ao is not None:
            self._post_ao = max(0.0, min(1.0, float(ao)))
        if ao_radius is not None:
            self._post_ao_r = max(4.0, min(32.0, float(ao_radius)))
        if ao_depth is not None:
            self._post_ao_d = max(0.01, min(1.0, float(ao_depth)))
        self.update()

    def get_postprocess(self):
        return {"enabled": self._post_on, "scale": self._post_scale,
                "edge": self._post_edge, "radius": self._post_edge_r,
                "tone": self._post_tone, "vig": self._post_vig,
                "ao": self._post_ao, "ao_radius": self._post_ao_r,
                "ao_depth": self._post_ao_d}

    # ── 色彩空间（B 方案）──────────────────────────────────────────────
    def set_linear_space(self, on):
        """切换色彩空间：False = sRGB 直通（默认，与旧版逐位一致）；
        True = 线性空间光照（光照/透明混合全程线性域，后处理转回 sRGB）。"""
        self._linear_space = bool(on)
        self.update()

    def linear_space(self):
        """当前色彩空间（False = sRGB，True = 线性）。"""
        return bool(getattr(self, "_linear_space", False))

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
        self._scene_r = max(r, 0.3)      # 雾化参考尺度（见 fog_factor）
        self.update()

    def screenshot(self, path, scale: float = 2.0):
        w = max(1, int(round(self.width() * scale)))
        h = max(1, int(round(self.height() * scale)))
        img = self.grabFramebuffer()
        img = img.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        ok, msg, real_path = save_export_image(
            img, path, dpi=96.0 * float(scale), background=self._bg[:3])
        if not ok:
            self._status(f"截图保存失败: {os.path.basename(real_path)} {msg}")
            return
        self._status(f"截图已保存: {os.path.basename(real_path)}")

    def export_image(self, path, dpi: float = 600.0, transparent: bool = False,
                     quality: int = -1):
        """高分辨率导出（实时重渲染而非位图拉伸）。

        不把低分辨率位图拉伸缩放（那样会模糊），
        而是以目标分辨率真正重新渲染场景再把像素读回。这里用分块(tile)离屏
        渲染实现：

          * 目标像素 = 当前控件尺寸 x (dpi / 96)   （96 = 屏幕基准 DPI）
          * 把整图切成若干小瓦片，每片用一个小离屏 FBO 真高分重绘
            （避免一次性分配超大 FBO 撑爆显存导致 GPU context lost / 闪退）
          * 每块 glReadPixels 读回，拼成完整 RGBA 数组，再写 QImage
          * 通过 setDotsPerMeterX/Y 把 600 DPI 写入 PNG 元数据

        渲染走与实时预览**同一条后处理合成路径**（_compose_post）：后处理开启时，
        超采样抗锯齿、SSAO、边缘暗化、色调映射、暗角都会作用到导出图；只有在
        后处理目标不可用时才退回旧的直出瓦片渲染。

        transparent=True 时清屏 alpha=0，导出背景透明的图（PNG / TIF / SVG 有效；
        JPG 无 alpha 通道，会压平到当前画布背景色上）。

        输出格式由 ``path`` 的扩展名决定，支持 PNG / JPG / TIF / SVG：前三个经
        QImageWriter 编码（JPG 走 ``quality``），SVG 用 Qt SVG 生成器把满分辨率
        位图以 base64 内嵌成标准 SVG。扩展名缺失或未知时按 PNG 存。

        若 OpenGL 不可用则回退到 grabFramebuffer 缩放。
        """
        if not self._gl_ok:
            self.screenshot(path, scale=float(dpi) / 96.0)
            return True

        # 后台建网格还没回来的话先等它——导出必须用最新几何
        self._flush_mesh_build()
        w0 = max(1, self.width())
        h0 = max(1, self.height())
        scale = float(dpi) / 96.0
        ew = max(1, int(round(w0 * scale)))
        # 由 ew 反推 eh，严格保持画布宽高比，避免宽/高各自四舍五入导致
        # 导出图与画布比例不一致、边缘出现未渲染的黑边。
        eh = max(1, int(round(ew * h0 / w0)))

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
            # 先补上延迟上传：paintGL 里才做的网格/matcap 上传在这里必须补做，
            # 否则导出用的是**上一次屏幕绘制时**的网格或材质球纹理（实测：
            # 切到 Matcap「金属」后直接导出，出来的还是上一个材质球）。
            if self._needs_upload:
                try:
                    self._upload()
                    self._needs_upload = False
                except Exception as e:
                    self._status(f"导出前网格上传失败: {e}")
            if getattr(self, "_matcap_dirty", False):
                try:
                    self._upload_matcap()
                    self._matcap_dirty = False
                except Exception as e:
                    self._status(f"导出前 matcap 上传失败: {e}")
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
                        tile_vp = (ox, oy, tw, th, ew, eh)
                        # ── 首选：与实时预览同一条后处理合成路径 ──
                        # 超采样抗锯齿 / SSAO / 边缘暗化 / 色调映射 / 暗角全部
                        # 随导出一起生效（旧实现直接 _render()，这些一律没有）。
                        done = False
                        if self._post_on and self._post_ok and self._prog_post:
                            s = max(1.0, float(self._post_scale))
                            sw = max(1, int(round(tw * s)))
                            sh = max(1, int(round(th * s)))
                            # 放大后的瓦片窗口：_projection 只用到这些量的
                            # 比例关系，整体乘 s 即得到同一块子视锥。
                            vp_s = tuple(float(v) * s for v in tile_vp)
                            done = self._compose_post(
                                fbo.fbo, 0, 0, tw, th, sw, sh,
                                vp=vp_s, bg=clear_col)
                        if not done:
                            # ── 回退：直出路径（后处理目标不可用时）──
                            # 先按本瓦片尺寸重建透明目标（WBOIT / 深度剥离），再绑定
                            # 导出 FBO。若在 _render 内部由 _ensure_* 因尺寸变化重建，
                            # create() 会把帧缓冲绑定切到 0，导致其后合成趟与
                            # glReadPixels 全部落到屏幕帧缓冲上——首尾瓦片读出黑块。
                            if self._peel_ok:
                                try:
                                    self._ensure_peel_targets(tw, th)
                                except Exception:
                                    self._peel_ok = False
                            if self._oit_ok:
                                try:
                                    self._ensure_oit_target(tw, th)
                                except Exception:
                                    self._oit_ok = False
                            glBindFramebuffer(GL_FRAMEBUFFER, fbo.fbo)
                            glViewport(0, 0, tw, th)
                            glClearColor(*clear_col)
                            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
                            glEnable(GL_DEPTH_TEST)
                            glDepthFunc(GL_LEQUAL)
                            self._render(tw, th, vp=tile_vp, bg=clear_col)
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

        # WBOIT 合成会把 revealage（1 - 表面透明度）写进 alpha 通道：非透明导出若
        # 保留该 alpha，看图器把半透明区叠到黑底上就"发黑"。屏幕默认帧缓冲忽略 alpha，
        # 所以预览正常。因此：
        #   · 非透明导出 → 全部 alpha=255（与屏幕观感一致）
        #   · 透明导出   → 背景 alpha=0 保持透明，其余（原子/等值面）强制不透明
        if transparent:
            full[:, :, 3] = np.where(full[:, :, 3] > 0, 255, 0)
        else:
            full[:, :, 3] = 255

        # 诊断：若左右边缘仍偏黑，打印边缘平均亮度，便于定位黑边来源。
        _e = max(1, ew // 40)
        _l = float(full[:, :_e, :3].mean())
        _r = float(full[:, ew - _e:, :3].mean())
        if _l < 20.0 or _r < 20.0:
            self._status(f"[诊断] 导出左右边缘偏黑 左={_l:.0f} 右={_r:.0f} "
                         f"(画布 {w0}x{h0}, 导出 {ew}x{eh}, 正常应≥200)")

        img = QImage(full.data, ew, eh, ew * 4, QImage.Format_RGBA8888)
        img = img.copy()                                   # detach from numpy

        # 叠加 2D QPainter 覆盖层（ESP 色标条 / 极值点数值标签）。它们只在屏幕
        # paintGL 绘制，离屏瓦片重渲染不含这些，故按导出分辨率重画一遍。
        self._composite_overlays(img, ew, eh)

        # write DPI metadata + encode by extension (png / jpg / tif / svg)
        ok, msg, real_path = save_export_image(
            img, path, dpi=dpi, background=self._bg[:3], quality=quality)
        if ok:
            self._status(
                f"已导出 {ew}x{eh} @ {dpi} DPI {os.path.splitext(real_path)[1][1:].upper()} "
                f"(分 {nx}x{ny} 块): {os.path.basename(real_path)}")
        else:
            self._status(f"导出保存失败: {os.path.basename(real_path)} {msg}")
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
        """Set a manual bond override.  state ∈ {'solid','dashed','double',
        'triple','deloc','none','reset'}；'double'/'triple' 为多重键（与单键
        等粗的平行圆柱），'deloc' 为离域键（实线 + 虚线并列）。"""
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

        For the orthographic projection used by CubGLWidget, the
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
        bond_r = self._bond_radius() * 3.0
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
        (ATOM_DRAW_SCALE * _DRAW_RADII[z] * _atom_scale), otherwise the
        ray-sphere pick test can never hit the (much larger) visible spheres.
        Enlarged by 1.15× so clicking near an atom still selects it.
        """
        if anum is None:
            return 0.5 * ATOM_DRAW_SCALE * self._atom_scale * 1.15
        return self._ball_radius(anum) * 1.15

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

        # 右键菜单只针对“选中的原子对”提供操作：断 / 成(实线) / 虚线 +
        # 双键 / 三键 + 重置。多重键为手动指定，不做自动判定。
        if n_sel == 2:
            i, j = self._selected_atoms[0], self._selected_atoms[1]
            sel_key = (min(i, j), max(i, j))
            cur = self._bond_overrides.get(sel_key, 'auto')
            actions = [
                ("连接成键 (单键实线)", sel_key, 'solid'),
                ("设为双键",           sel_key, 'double'),
                ("设为三键",           sel_key, 'triple'),
                ("设为离域键 (实线+虚线)", sel_key, 'deloc'),
                ("设为虚线键",         sel_key, 'dashed'),
                ("断开键",             sel_key, 'none'),
            ]
            # 自动判定模式下：把这对原子的判定结果与判据显示出来（禁用项，
            # 只作信息展示——用户能看出为什么画成双键/三键，必要时再手动改）
            if self._bond_mode == BOND_MODE_AUTO and cur == 'auto':
                a_order, a_q = self.auto_order_for(i, j)
                if a_order is not None:
                    _on = {1: '单键', DELOC_BOND_ORDER: '离域键(1.5)',
                           2: '双键', 3: '三键'}
                    info = QAction(
                        f"按键长自动判定：{_on.get(a_order, a_order)}"
                        f"（键长比 {a_q:.3f}）", self)
                    info.setEnabled(False)
                    menu.addAction(info)
                    menu.addSeparator()

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
                    names = {'solid': '实线单键', 'dashed': '虚线键',
                             'double': '双键', 'triple': '三键',
                             'deloc': '离域键（实线+虚线）',
                             'none': '断开'}
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
        """把平面填充 + 配位多面体条目一起拼接成合并网格（一次 upload/draw）。"""
        items = self._fill_items + self._poly_items
        if not items:
            self._fill_surf = None
            self._needs_upload = True
            self.update()
            return
        verts, norms, cols, idxs = [], [], [], []
        off = 0
        for it in items:
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

    # ── 配位多面体（晶体页）──────────────────────────────────────
    # 绘制完全复用上面的平面填充管线（render_plane_fill：深度测试开、不写
    # 深度、alpha 混合、双面、unlit 纯色），所以外观与"半透明平面填充"一致，
    # 且天然被原子/键正确遮挡。
    def set_polyhedra(self, polys, rgba=None):
        """设置配位多面体（覆盖上一次的，不影响用户的平面填充）。

        polys: [{"vertices": (N,3) 数组（**Å**）, "triangles": [(a,b,c), ...]}]
        rgba:  0..1 四元组；None 时沿用上次用过的颜色/透明度。
        顶点按面拆开（每面独立法线，朝外），以便将来要算光照时也是平面着色。
        """
        self._poly_items = []
        if rgba is not None:
            self._poly_rgba = tuple(float(v) for v in rgba[:4])
        # 全部多面体合成一份网格：它们共用同一颜色/透明度，逐个建 IsoSurface 在
        # 几百个中心时开销明显（每个都要单独 upload）。
        vv, nn, ii = [], [], []
        for p in (polys or []):
            v = np.asarray(p.get("vertices"), dtype=np.float64)
            tris = p.get("triangles") or []
            if v.ndim != 2 or v.shape[0] < 3 or not len(tris):
                continue
            v = v / BOHR_TO_ANGSTROM            # Å → Bohr（画布内部坐标）
            ctr = v.mean(axis=0)
            for tri in tris:
                a, b, c = v[tri[0]], v[tri[1]], v[tri[2]]
                nrm = np.cross(b - a, c - a)
                ln = float(np.linalg.norm(nrm))
                if ln < 1e-9:                   # 退化三角形
                    continue
                nrm /= ln
                if float(np.dot(nrm, (a + b + c) / 3.0 - ctr)) < 0:
                    nrm = -nrm                  # 法线朝外（多面体质心为内）
                off = len(vv)
                vv.extend((a, b, c))
                nn.extend((nrm, nrm, nrm))
                ii.extend((off, off + 1, off + 2))
        if ii:
            surf = IsoSurface()
            surf.vertices = np.asarray(vv, dtype=np.float32)
            surf.normals = np.asarray(nn, dtype=np.float32)
            surf.colors = np.tile(
                np.asarray(self._poly_rgba, dtype=np.float32), (len(vv), 1))
            surf.indices = np.asarray(ii, dtype=np.uint32)
            self._poly_items.append({"surf": surf})
        self._rebuild_fill_mesh()

    def set_polyhedron_alpha(self, rgba):
        """只改多面体的颜色/透明度（不重算几何，拖动滑块时用）。"""
        self._poly_rgba = tuple(float(v) for v in rgba[:4])
        if not self._poly_items:
            return
        for it in self._poly_items:
            s = it["surf"]
            s.colors = np.tile(
                np.asarray(self._poly_rgba, dtype=np.float32),
                (s.vertex_count, 1))
        self._rebuild_fill_mesh()

    def clear_polyhedra(self):
        """清除全部配位多面体（不动用户的平面填充）。"""
        if not self._poly_items:
            return
        self._poly_items = []
        self._rebuild_fill_mesh()

    def polyhedron_count(self):
        """当前显示的多面体个数。"""
        return len(self._poly_items)

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
        self.set_shader_uniforms(
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
            glClearColor(*(tuple(x ** 2.2 if i < 3 else x for i, x in
                                 enumerate(tuple(self._bg)))
                          if getattr(self, '_linear_space', False)
                          else self._bg))
            glEnable(GL_DEPTH_TEST)
            # RenderBacksides is off, but orbital lobes are open
            # surfaces whose insides must stay visible, so culling is disabled
            # and the inside is lit via shade_base_color(true) instead.
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

            # 后处理（超采样降采样 + 边缘暗化）。失败只关后处理，不能拖垮画布。
            # 注意：link_program 链接完会 glDeleteShader，顶点着色器必须现编译，
            # 不能复用上面已链入 _prog_bg 的 vb（否则 attach 的是已删除对象）。
            try:
                self._prog_post = link_program(
                    compile_shader(VERT_BG, GL_VERTEX_SHADER),
                    compile_shader(FRAG_POST, GL_FRAGMENT_SHADER))
            except Exception as e:
                self._prog_post = 0
                self._post_ok = False
                self._status(f"后处理着色器编译失败，已关闭后处理: {e}")

            # SSAO：深度预通道（只写深度）+ 全屏 AO。失败只关 AO。
            try:
                self._prog_depth = link_program(
                    compile_shader(VERT, GL_VERTEX_SHADER),
                    compile_shader(FRAG_DEPTH_ONLY, GL_FRAGMENT_SHADER))
                self._prog_ao = link_program(
                    compile_shader(VERT_BG, GL_VERTEX_SHADER),
                    compile_shader(_ao_shader_source(), GL_FRAGMENT_SHADER))
            except Exception as e:
                self._prog_depth = self._prog_ao = 0
                self._ao_ok = False
                self._status(f"SSAO 着色器编译失败，已关闭 AO: {e}")

            self._gl_ok = True

            # 全屏四边形 VAO：WBOIT / 深度剥离的合成趟绘制回主帧时共用。
            # （旧 IboView 移植的 depth-peeling 双缓冲路径已于 2026-09-03
            # 整条删除；深度剥离现为独立实现，见 FRAG_PEEL_ORB / PeelTargets。）
            self._vao_quad = glGenVertexArrays(1)

            # WBOIT 同样是可选能力：着色器编译通过只是第一步，
            # 真正的门槛是能否渲染到浮点纹理（在 create() 里判定）。
            try:
                if _glBlendFunci is None:
                    raise RuntimeError(
                        "缺少 glBlendFunci（GL 4.0 / ARB_draw_buffers_blend）")
                vs4 = compile_shader(VERT, GL_VERTEX_SHADER)
                self._prog_orb_oit = link_program(
                    vs4, compile_shader(FRAG_ORB_OIT, GL_FRAGMENT_SHADER))
                vq2 = compile_shader(VERT_QUAD, GL_VERTEX_SHADER)
                self._prog_combine_oit = link_program(
                    vq2, compile_shader(FRAG_COMBINE_OIT, GL_FRAGMENT_SHADER))
                self._oit_ok = True
            except Exception as e:
                self._oit_ok = False
                self._prog_orb_oit = self._prog_combine_oit = 0
                self._status(f"WBOIT 不可用，将回退其它透明模式: {e}")

            # Depth peeling（Everitt 2001，本项目独立实现）同为可选能力：
            # 门槛比 WBOIT 低（无需浮点 MRT / glBlendFunci），编译失败则
            # 透明模式回退 oit / sorted。
            try:
                vsp = compile_shader(VERT, GL_VERTEX_SHADER)
                self._prog_orb_peel = link_program(
                    vsp, compile_shader(FRAG_PEEL_ORB, GL_FRAGMENT_SHADER))
                vqa = compile_shader(VERT_QUAD, GL_VERTEX_SHADER)
                self._prog_accum_peel = link_program(
                    vqa, compile_shader(FRAG_PEEL_ACCUM, GL_FRAGMENT_SHADER))
                vqp = compile_shader(VERT_QUAD, GL_VERTEX_SHADER)
                self._prog_combine_peel = link_program(
                    vqp, compile_shader(FRAG_PEEL_COMBINE, GL_FRAGMENT_SHADER))
                self._peel_ok = True
            except Exception as e:
                self._peel_ok = False
                self._prog_orb_peel = self._prog_accum_peel = 0
                self._prog_combine_peel = 0
                self._status(f"深度剥离不可用，将回退其它透明模式: {e}")

            modes = []
            if self._oit_ok:
                modes.append("WBOIT")
            if self._peel_ok:
                modes.append("深度剥离")
            modes.append("排序混合")
            self._status(
                f"就绪 — 渲染器已就绪（透明：{' / '.join(modes)}），"
                f"双击轨道列表即可在此渲染，也可拖放 .cub 文件到画布")
        except Exception as e:
            self._status(f"OpenGL 初始化失败: {e}")
            traceback.print_exc()

    def resizeGL(self, w, h):
        glViewport(0, 0, max(1, w), max(1, h))

    def _ensure_oit_target(self, w, h):
        """(重新)创建 WBOIT 的 MRT 目标。成功返回 True。"""
        if not self._oit_ok:
            return False
        try:
            if self._oit.fbo == 0 or self._oit.w != w or self._oit.h != h:
                self._oit.create(w, h)
            return True
        except Exception as e:
            self._oit_ok = False
            self._status(f"WBOIT 目标创建失败，回退其它透明模式: {e}")
            return False

    def _ensure_peel_targets(self, w, h):
        """(重新)创建深度剥离的 FBO 组。成功返回 True。"""
        if not self._peel_ok:
            return False
        try:
            if self._peel.fbo_acc == 0 or self._peel.w != w or self._peel.h != h:
                self._peel.create(w, h)
            return True
        except Exception as e:
            self._peel_ok = False
            self._status(f"深度剥离目标创建失败，回退其它透明模式: {e}")
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

        # Matcap 材质球纹理延迟上传（切换预设时置 dirty）
        if self._matcap_dirty:
            try:
                self._upload_matcap()
                self._matcap_dirty = False
            except Exception as e:
                self._status(f"matcap 上传失败: {e}")

        if self._post_on and self._post_ok and self._prog_post:
            self._render_post()
        else:
            self._render()

        # ── ESP 色标条叠加（2D，QPainter；走离屏超采样，屏幕上刻度字更清晰）──
        if getattr(self, "_cs_show", False):
            self._draw_color_scale_overlay(max(1, self.width()),
                                           max(1, self.height()))

        # ── ESP 极值点数值标签叠加 ──
        self._draw_extrema_labels()

        # ── MolViewer 球棍样式叠加（阴影 / 十字 / 原子标签） ──
        self._draw_mol_overlay()

        # ── 键长测量标注叠加（连线中点距离标签） ──
        # 放在最后：用户自己摆的标注是最上层，不被软阴影/原子标签压住
        self._draw_measure_labels()

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
        if self._mol_style == "VESTA":
            # VESTA：整表 95 个元素都用 VESTA 自己的配色（见 vesta_colors.py）。
            # 与"元素原子颜色"对话框的关系不变：对话框里手动指定的元素色
            # 优先级更高（那是用户显式覆盖），这里只提供样式默认值。
            return _VESTA_COLORS.get(anum, (0.78, 0.78, 0.78))
        # 默认 CPK：公开 Rasmol CPK-new 全元素配色（见 _CPK_COLORS 定义注释）
        return _CPK_COLORS[anum] if 0 <= anum < len(_CPK_COLORS) \
            else (0.5, 0.5, 0.5)

    def _bond_candidate_pairs(self, coords, anums):
        """可能成键的原子对 [(i, j)]（i<j），用空间分箱预筛。

        成键判据是 `rij <= rf_loose × (cov_i + cov_j)` 或 `rij <= 绝对上限`，
        所以只需检查距离不超过**最大可能成键距离**的对。旧写法对全部
        n(n-1)/2 对都算一次 np.linalg.norm —— 2168 原子实测调用了 236 万次、
        耗时 4.7 s（占建网格总时间的约八成）。分箱后候选对通常只剩百分之几。

        手工指定的键（`_bond_overrides`）可能超出自动判据，必须原样保留。
        """
        n = len(coords)
        if n < 2:
            return []
        max_cov = 0.0
        for z in set(int(x) for x in anums):
            if 0 <= z < len(_COV_RADII_BOHR):
                max_cov = max(max_cov, _COV_RADII_BOHR[z])
        cap = (max(BOND_MAX_DIST_ANG, BOND_MAX_DIST_H_ANG) / BOHR_TO_ANGSTROM)
        cutoff = max(2.0 * max_cov * self._bond_rf_loose, cap, 1e-6)
        keys = np.floor(coords / cutoff).astype(np.int64)
        buckets = {}
        for i in range(n):
            buckets.setdefault((int(keys[i, 0]), int(keys[i, 1]),
                                int(keys[i, 2])), []).append(i)
        pairs = set()
        cut2 = cutoff * cutoff
        for i in range(n):
            kx, ky, kz = int(keys[i, 0]), int(keys[i, 1]), int(keys[i, 2])
            cand = []
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        lst = buckets.get((kx + dx, ky + dy, kz + dz))
                        if lst:
                            cand.extend(lst)
            if len(cand) < 2:
                continue
            c = np.asarray(cand, dtype=np.int64)
            c = c[c > i]
            if c.size == 0:
                continue
            dv = coords[c] - coords[i]
            r2 = np.einsum("ij,ij->i", dv, dv)
            for j in c[r2 <= cut2]:
                pairs.add((i, int(j)))
        for (a, b) in self._bond_overrides:      # 手工键：可能超出自动判据
            a, b = int(a), int(b)
            if a != b and 0 <= a < n and 0 <= b < n:
                pairs.add((a, b) if a < b else (b, a))
        return sorted(pairs)

    def _gen_atoms(self):
        """（重新）生成原子/键网格。

        大分子（≥ MESH_ASYNC_MIN_ATOMS）自动改走后台线程 —— 几何生成是纯
        numpy/Python 计算，放后台不碰 GL，算完由 `_meshBuilt` 信号回 GUI 线程
        装回网格；期间界面照常响应。小分子仍同步执行，保证 export / 探针里
        "调用完即生效"的既有语义不变。
        """
        if (self._mesh_async_on and MESH_ASYNC_MIN_ATOMS >= 0
                and self._mesh_atom_count() >= MESH_ASYNC_MIN_ATOMS):
            self._request_mesh_build()
            return
        self._gen_atoms_sync()

    def _mesh_atom_count(self):
        try:
            return len(self._atom_list())
        except Exception:
            return 0

    def _make_mesh_shadow(self):
        """把 `_gen_atoms` 需要的状态快照到一个影子对象上（派发时执行）。"""
        sh = _MeshShadow()
        for name in _MESH_SHADOW_ATTRS:
            try:
                v = getattr(self, name)
            except AttributeError:
                continue
            if isinstance(v, dict):
                v = dict(v)
            elif isinstance(v, set):
                v = set(v)
            elif isinstance(v, list):
                v = list(v)
            setattr(sh, name, v)
        sh.cam = self.cam                 # 只读用；与 GUI 线程共用同一个相机对象
        sh._meshes = [None, None, None]   # 影子不碰真网格（空分子分支会被跳过）
        w0, h0 = max(1, self.width()), max(1, self.height())
        sh.width = lambda: w0             # 后台不读 Qt，直接用快照尺寸
        sh.height = lambda: h0
        for nm in _MESH_SHADOW_METHODS:
            fn = getattr(CubGLWidget, nm, None)
            if callable(fn):
                setattr(sh, nm, types.MethodType(fn, sh))
        return sh

    def _request_mesh_build(self):
        """派发（或合并）一次后台建网格。"""
        self._mesh_build_id += 1
        if self._mesh_busy:               # 已经在算：只记一笔，算完再补一次
            self._mesh_pending = True
            return
        try:
            sh = self._make_mesh_shadow()
        except Exception:
            self._gen_atoms_sync()
            return
        self._mesh_busy = True
        self._mesh_pending = False
        bid = self._mesh_build_id

        def _work():
            try:
                sh._gen_atoms_sync()
            except Exception:
                self._mesh_shadow_out = None
                if not self._mesh_async_warned:
                    self._mesh_async_warned = True
                    traceback.print_exc()
                self._meshBuilt.emit(-1)      # 回退：GUI 线程同步重算
                return
            self._mesh_shadow_out = sh
            self._meshBuilt.emit(bid)

        t = threading.Thread(target=_work, name="ov-mesh-build", daemon=True)
        self._mesh_thread = t
        t.start()

    def _apply_mesh_shadow(self, bid):
        """把后台算好的网格装回本控件（只能在 GUI 线程调用）。"""
        if bid != self._mesh_build_id or self._mesh_shadow_out is None:
            return False
        sh = self._mesh_shadow_out
        self._mesh_shadow_out = None
        self._atom_surf = sh._atom_surf
        self._bond_surf = sh._bond_surf
        self._sel_surf = getattr(sh, "_sel_surf", None)
        self._vdw_surf = getattr(sh, "_vdw_surf", None)
        self._vdw_balls = getattr(sh, "_vdw_balls", None)
        self._bond_auto_orders = getattr(sh, "_bond_auto_orders", {}) or {}
        self._needs_upload = True
        self.update()
        return True

    def _on_mesh_built(self, bid):
        """后台建网格完成（GUI 线程槽）。"""
        self._mesh_busy = False
        self._mesh_thread = None
        if bid < 0:                       # 后台失败 → 同步重算，保证画面对
            self._mesh_shadow_out = None
            self._gen_atoms_sync()
        else:
            self._apply_mesh_shadow(bid)
        if self._mesh_pending:
            self._mesh_pending = False
            self._request_mesh_build()

    def _flush_mesh_build(self, timeout=60.0):
        """等后台建网格结束并装回（导出/取图前调用，保证几何是最新的）。"""
        for _ in range(2):                # 合并队列里可能还排着一次
            t = self._mesh_thread
            if t is None or not t.is_alive():
                break
            t.join(timeout)
        if self._mesh_pending:
            self._mesh_pending = False
            self._request_mesh_build()
            t = self._mesh_thread
            if t is not None and t.is_alive():
                t.join(timeout)
        self._mesh_busy = False
        if not self._apply_mesh_shadow(self._mesh_build_id):
            # 没有可用的后台结果（失败 / 被更新的请求取代）→ 同步算一遍
            self._gen_atoms_sync()

    def _gen_atoms_sync(self):
        """Generate the opaque molecule model (atoms + bonds).

        Atom spheres use the empirical draw-radii table (scaled by
        ATOM_DRAW_SCALE); bonds are detected by the covalent-radius sum
        heuristic:
            r_ij <= 0.5 * (bf_i + bf_j) * (cov_i + cov_j)  ⇒  a bond
        Bonds are drawn as grey cylinders (default DiffuseColor
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
                self._atom_surf = None    # 清空分子时缓存网格一并失效
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
        # Bohr (_COV_RADII_BOHR) so the comparison is unit-consistent.
        coords = np.array([[a[2], a[3], a[4]] for a in atoms], dtype=np.float64)
        anums = [int(a[0]) for a in atoms]

        # `_selected_atoms` 存的是 **0 基**索引（_pick_atom 返回的即 0 基，
        # _gen_selection_marker 也直接拿它当 atoms 的下标）。这里预先转成集合，
        # 一是避免行内 list 查找退化成 O(n²)，二是把基准统一在循环外表达清楚。
        sel_idx = set()
        for _i in self._selected_atoms:
            try:
                sel_idx.add(int(_i))
            except (TypeError, ValueError):
                continue

        # 屏幕尺度（像素 / 玻尔）：给原子球选细分档用（见 unit_sphere / SPHERE_LOD_PX）。
        # 只算一次，和 _atom_screen_geo 用的是同一套投影。
        try:
            _w = max(1, self.width()); _h = max(1, self.height())
            _o = self._world_to_screen(0.0, 0.0, 0.0, _w, _h)
            _x = self._world_to_screen(1.0, 0.0, 0.0, _w, _h)
            px_per_bohr = math.hypot(_x[0] - _o[0], _x[1] - _o[1])
        except Exception:
            px_per_bohr = 0.0

        all_v = []; all_n = []; all_c = []; all_i = []; off = 0
        # ── atom spheres ──
        # Colours come from the public CPK palette (_CPK_COLORS, Rasmol CPK-new),
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
            _f = self._elem_r_mult.get(int(anum), 1.0)
            if self._vdw_mode:
                r = _vdw_radius(anum) * self._vdw_scale * _f
            else:
                r = self._ball_radius(anum)
            if (k + 1) in self._atom_color_overrides:
                col = self._atom_color_overrides[k + 1]
            elif anum in self._element_color_overrides:
                col = self._element_color_overrides[anum]
            else:
                col = self._atom_color(anum)
            # 选中的原子本体染上高亮色（半混合，保留元素身份）。
            # 早期版本只在外部套二十面体、本体不着色；改为本体着色 + 贴合
            # 包裹壳后，选中态一眼可辨（见 SEL_TINT_* 常量说明）。
            # 注意用 0 基的 k —— 与 _selected_atoms 的基准一致。
            if k in sel_idx:
                col = _mix_toward(col, self._sel_tint, SEL_TINT_MIX)
            # 共享单位球 + 屏幕尺度选细分档（LOD）：
            #   球投到屏幕上很小（晶体里常见）→ sub=2，三角形数只有原来的 1/4；
            #   球够大 → 沿用原来的 sub=3，观感与改前一致。
            _sub = 2 if 0.0 < r * px_per_bohr < SPHERE_LOD_PX else 3
            sv, nrm, idx = unit_sphere(_sub)
            # 与旧路径同精度：先 float64 算「单位球×半径」→ 转 float32 →
            # 再加球心（末尾 np.vstack 时统一转 float32）。逐位一致。
            v = ((sv * float(r)).astype(np.float32)
                 + np.array([ax, ay, az], dtype=np.float64))
            c = np.tile(np.array([*col, 1.], dtype=np.float32), (len(v), 1))
            all_v.append(v); all_n.append(nrm); all_c.append(c)
            all_i.append(idx + off); off += len(v)

        # ── bonds (covalent-radius-sum heuristic, dual-threshold) ──
        # Solid bonds: rij <= rf_tight * cov_sum   (tapered cylinders)
        # Dashed bonds: rf_tight < rij <= rf_loose  (segmented cylinders)
        bond_r = self._bond_radius()
        # A solid bond is two tapered half-cylinders joined at the midpoint.
        # seg=24（旧 12）：键圆柱轮廓/反光亮带的棱在放大与高清导出下可见
        cyl_a = make_tapered_cylinder(1.0, self._bond_thinning, 1.0, BOND_CYL_SEG)   # atom side (thick → thin)
        cyl_b = make_tapered_cylinder(self._bond_thinning, 1.0, 1.0, BOND_CYL_SEG)   # centre side (thin → thick)
        # 多重键子键复用同一套锥形模板（腰身比例一致，观感统一）；单独持有
        # 一份是为了将来可给子键不同的削腰比例。
        sub_a = make_tapered_cylinder(1.0, self._bond_thinning, 1.0, BOND_CYL_SEG)
        sub_b = make_tapered_cylinder(self._bond_thinning, 1.0, 1.0, BOND_CYL_SEG)
        bf_tight = self._bond_rf_tight
        bf_loose = self._bond_rf_loose
        dash_w = self._dash_weight

        # 键几何单独收集：除常规 opaque 网格外，再建一份键专属网格，
        # 供每帧末尾"二次上色"重绘 pass 使用（键色与 vdW 外壳彻底解耦）。
        bond_v = []; bond_n = []; bond_c = []; bond_i = []; bond_off = 0
        # 自动判定结果留档（每次重建都刷新，避免拿到上一分子的陈旧判据）
        self._bond_auto_orders = {}

        def emit_solid(pa, pb, cp, cq, radius, temp_a=cyl_a, temp_b=cyl_b):
            """把一条实线键（pa→pb 的两段锥形圆柱）追加进 all_* / bond_*。

            `radius` 为圆柱半径。多重键只是换成更小的半径 + 平移后的端点，
            **共用同一套模板网格与旋转/缩放变换**，因此三角形环绕方向、法线
            朝向与 vdW 挖孔、双面渲染的既有约定完全一致（不会引入新的黑面）。
            """
            nonlocal off, bond_off
            mid = (pa + pb) * 0.5
            for src, end in ((pa, mid), (mid, pb)):
                d = (end - src); hl = float(np.linalg.norm(d)); d /= hl
                up = np.array([0.0, 1.0, 0.0])
                v = np.cross(up, d)
                c = float(np.dot(up, d))
                if np.linalg.norm(v) < 1e-6:
                    R = np.eye(3) if c > 0 else -np.eye(3)
                else:
                    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
                    R = np.eye(3) + vx + vx @ vx * (1.0 / (1.0 + c))
                S = np.diag([radius, hl, radius])
                T = R @ S
                cv, cn, ci_ = temp_a if src is pa else temp_b
                tv = cv @ T.T + src
                tn = cn @ R.T
                half_col = cp if src is pa else cq
                tc = np.tile(half_col, (len(tv), 1))
                all_v.append(tv.astype(np.float32)); all_n.append(tn.astype(np.float32)); all_c.append(tc.astype(np.float32))
                all_i.append(ci_ + off); off += len(tv)
                bond_v.append(tv.astype(np.float32))
                bond_n.append(tn.astype(np.float32))
                bond_c.append(tc.astype(np.float32))
                bond_i.append(ci_ + bond_off); bond_off += len(tv)

        def emit_dashed(pa, pb, radius=None, dot_radius=None):
            """虚线键：按 `_dash_style` 出两种画法（固定黑色，不随配色变化）。

            'dots'   小圆球点阵 —— 细点，读作"部分键"（既有默认）。
            'dashes' 短圆柱段   —— 真正的虚线：段与实线等粗、一段一段排开。

            `radius` 为等效单键半径（决定段粗细/点阵基准大小），默认取当前键半径。
            `dot_radius` 只在点阵样式下有意义：离域键的虚线用它把点放大到与
            同排实线匹配的粗细；短圆柱段样式下段粗细直接取 `radius`（= 与实线等粗）。
            """
            nonlocal off, bond_off
            base_r = bond_r if radius is None else radius
            if self._dash_style == DASH_STYLE_DASHES:
                dv, dn, di = make_dash_segment_geometry(
                    pa, pb, base_r, n_segments=0, dash_weight=dash_w,
                    dot_spacing=self._dot_spacing_scale, seg=BOND_CYL_SEG,
                    radius=base_r * self._dot_size_scale)
            else:
                dv, dn, di = make_dashed_bond_geometry(
                    pa, pb, base_r, n_segments=0, dash_weight=dash_w,
                    dot_size=self._dot_size_scale,
                    dot_spacing=self._dot_spacing_scale, seg=BOND_CYL_SEG,
                    dot_radius=dot_radius)
            if len(dv) == 0:
                return
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

        def neighbor_dirs(idx, skip):
            """idx 指向其全部邻居的单位方向列表（多重键偏移面的参考）。

            这里**故意不按可见性过滤**：参考方向只用来确定"偏移落在哪个
            平面"，取全部邻居（含被隐藏的 H）时该平面即分子局部平面，勾选/
            取消「隐藏氢原子」时双键朝向不会跳变。若只取可见邻居，隐藏 H 后
            参考方向会换一个，同一条键的双键线会现场转 90°，观感上是 bug。
            """
            out = []
            o = coords[idx]
            for k in range(n):
                if k == idx or k == skip:
                    continue
                dv = coords[k] - o
                dl = float(np.linalg.norm(dv))
                if dl > 1e-6:
                    out.append(dv / dl)
            return out

        def emit_multi(pa, pb, cp, cq, order, idx_a, idx_b):
            """多重键：平移出若干根平行子键（与单键等粗），可混合实线/虚线。

            order = 2   双键：2 根实线
                    3   三键：3 根实线
                    1.5 离域键（芳香键）：1 根实线 + 1 根虚线并列，
                        等价于"双键里其中一根画成虚线"

            偏移方向取「相邻键方向垂直键轴的分量」（见 multi_bond_offset_axis），
            使多根线**落在成键平面内**——sp² 碳上就是分子平面（乙烯、苯环、
            羰基），符合化学制图习惯，也让俯视平面时能看清重数。两端都取不到
            参考方向（直线型 sp / 孤立原子对）时才退回世界轴的垂直方向。
            子键端点按 MULTI_BOND_INSET_* 内缩，避免圆柱戳进原子球。
            """
            axis_u = multi_bond_offset_axis(
                pa, pb, neighbor_dirs(idx_a, idx_b) + neighbor_dirs(idx_b, idx_a))
            if axis_u is None:
                emit_solid(pa, pb, cp, cq, bond_r)
                return
            leng = float(np.linalg.norm(pb - pa))
            sr = bond_r * self._multi_bond_radius
            # 子键中心距：随子键半径缩放，并夹取到键长的 22% 以内，
            # 免得极短键上两根线宽过键长本身。
            d_off = min(sr * self._multi_bond_gap, 0.22 * leng)
            inset = min(MULTI_BOND_INSET_FRAC * leng, MULTI_BOND_INSET_R * sr)
            ax_u = (pb - pa) / max(leng, 1e-9)
            pa_in = pa + ax_u * inset
            pb_in = pb - ax_u * inset
            # (相对键轴的偏移量, 线型)；离域键 = 实线 + 虚线并列
            if order == 3:
                spec = ((-d_off, 'solid'), (0.0, 'solid'), (d_off, 'solid'))
            elif order == 2:
                spec = ((-0.5 * d_off, 'solid'), (0.5 * d_off, 'solid'))
            else:
                spec = ((-0.5 * d_off, 'solid'), (0.5 * d_off, 'dashed'))
            for o, kind in spec:
                sh = axis_u * o
                if kind == 'dashed':
                    # 点半径按子键半径放大（DELOC_DASH_DOT_R），与等粗实线匹配
                    emit_dashed(pa_in + sh, pb_in + sh, sr,
                                dot_radius=sr * DELOC_DASH_DOT_R)
                else:
                    emit_solid(pa_in + sh, pb_in + sh, cp, cq, sr, sub_a, sub_b)

        # 只遍历"可能成键"的对（空间分箱预筛，见 _bond_candidate_pairs）：
        # 判据本身一个字没改，只是不再对全部两两组合算距离。
        _bond_cand = {}
        for _i, _j in self._bond_candidate_pairs(coords, anums):
            _bond_cand.setdefault(_i, []).append(_j)
        for i in range(n):
            for j in _bond_cand.get(i, ()):
                # 隐藏氢原子：任一端 H 被隐藏 → 该键不画
                if not (self._hydrogen_visible(i + 1, anums[i])
                        and self._hydrogen_visible(j + 1, anums[j])):
                    continue
                p = coords[i]; q = coords[j]
                rij = float(np.linalg.norm(q - p))
                if rij < 1e-4:
                    continue
                zi = anums[i]; zj = anums[j]
                # Use the Bohr-valued covalent radii (_COV_RADII_BOHR) so the
                # threshold is compared in the same Bohr frame as the coords.
                ci = _COV_RADII_BOHR[zi] if 0 <= zi < len(_COV_RADII_BOHR) else 0.7
                cj = _COV_RADII_BOHR[zj] if 0 <= zj < len(_COV_RADII_BOHR) else 0.7
                cov_sum = ci + cj

                # Check manual bond override first (user context-menu action)
                key = (i, j)
                override = self._bond_overrides.get(key)
                if override is not None:
                    if override == 'none':
                        continue           # forced no bond
                    elif override == 'dashed':
                        is_dashed = True   # forced dashed
                    else:
                        # 'solid' / 'double' / 'triple'：一律强制成键，跳过自动判定
                        is_dashed = False
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

                # 多重键（逐键手动指定）：双键 2 根、三键 3 根、离域键
                # 实线+虚线各 1 根；子键与单键等粗。手动指定优先于成键模式。
                if override in ('double', 'triple', 'deloc'):
                    order = {'double': 2, 'triple': 3,
                             'deloc': DELOC_BOND_ORDER}[override]
                    emit_multi(p, q, col_i, col_j, order, i, j)
                elif is_dashed:
                    # Dashed bond: a string of small black spheres along p→q
                    emit_dashed(p, q)
                else:
                    # 成键模式 'auto'：按键长推键型（结果留档供界面显示判据）
                    order = 1
                    if self._bond_mode == BOND_MODE_AUTO:
                        order, q_ratio = auto_bond_order(zi, zj, rij, ci, cj)
                        self._bond_auto_orders[key] = (order, q_ratio)
                    if order == 1:
                        # Solid bond: two tapered half-cylinders
                        emit_solid(p, q, col_i, col_j, bond_r)
                    else:
                        emit_multi(p, q, col_i, col_j, order, i, j)

        # ── ESP 极值点标记（金=极大值，浅蓝=极小值；半径 Å→Bohr） ──
        if self._extrema_pts:
            er = max(float(self._extrema_radius) * ANGSTROM_TO_BOHR,
                     0.02 * ANGSTROM_TO_BOHR)
            col_max = np.array([0.95, 0.78, 0.10, 1.0], dtype=np.float32)
            col_min = np.array([0.68, 0.85, 0.95, 1.0], dtype=np.float32)
            ev, en, ei = make_sphere(er, 3)
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
            cpv, cpn, cpi = make_sphere(cpr, 3)
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
            pv, pn, pi = make_sphere(ppr, 2)
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
            # 分块拼接：单次 np.vstack 会在 C 里长时间持有 GIL，把后台建网格
            # 期间的 GUI 堵住（详见 stack_chunked 的说明）。
            surf.vertices = stack_chunked(all_v, np.float32)
            surf.normals = stack_chunked(all_n, np.float32)
            surf.colors = stack_chunked(all_c, np.float32)
            surf.indices = stack_chunked(all_i, np.uint32, chunk=512)
            self._atom_surf = surf
        else:
            self._atom_surf = None
        # 键专属网格（二次上色重绘 pass 用；与主网格中键几何完全一致）
        if bond_v:
            bsurf = IsoSurface()
            bsurf.vertices = stack_chunked(bond_v, np.float32)
            bsurf.normals = stack_chunked(bond_n, np.float32)
            bsurf.colors = stack_chunked(bond_c, np.float32)
            bsurf.indices = stack_chunked(bond_i, np.uint32, chunk=512)
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
        """为选中的原子生成半透明包裹壳（形状可换）。

        默认 **wrap**：一层只比原子大 10% 的光滑球壳，用高亮色半透明绘制，
        配合 `_gen_atoms` 里对选中原子本体的染色，整体观感是"这颗原子被
        点亮了"，而不是外面多套了一个物体。

        早期版本沿用 IboView 的做法：1.9× 原子半径的**二十面体**外壳，
        本体不着色。那个方案离原子太远、边角生硬，且几个常数取自
        IvView3D.cpp，已废弃。

        形状可选：wrap（贴合包裹壳，默认）/ sphere（更大的透明球）/
        torus（圆环）/ glow（光晕：内壳 + 大范围外壳）。
        """
        atoms = self._atom_list()
        selected = self._selected_atoms
        if not atoms or not selected:
            self._sel_surf = None
            return

        shape = getattr(self, "_sel_marker_shape", "wrap")
        if shape in ("wrap", "sphere"):
            base_v, base_n, base_i = make_sphere(1.0, 3)
        elif shape == "torus":
            base_v, base_n, base_i = make_torus(1.0, tube=0.34)
        else:                                    # glow
            base_v, base_n, base_i = make_sphere(1.0, 2)

        # 呼吸动画：半径 ±12% 正弦
        pulse = 1.0 + 0.12 * math.sin(getattr(self, "_sel_pulse", 0.0)) \
            if getattr(self, "_sel_pulse_on", False) else 1.0

        # 各形状相对"原子绘制半径"的尺度。wrap 刻意只放大一点点。
        shape_scale = {"wrap": SEL_WRAP_SCALE, "sphere": 1.9,
                       "torus": 1.55, "glow": 1.9}.get(shape, SEL_WRAP_SCALE)
        alpha = getattr(self, "_sel_wrap_alpha", SEL_WRAP_ALPHA)
        tint = getattr(self, "_sel_tint", SEL_TINT_DEFAULT)

        verts, norms, cols, idxs = [], [], [], []
        off = 0
        for k in selected:
            if not (0 <= k < len(atoms)):
                continue
            anum, (x, y, z) = atoms[k]
            r = self._ball_radius(anum)
            s = shape_scale * r * pulse
            ctr = np.array([x, y, z], dtype=np.float32)

            if shape == "glow":
                # 内壳（主体）+ 大透明外壳（光晕）
                layers = ((1.0, alpha), (1.62, alpha * 0.3))
            else:
                layers = ((1.0, alpha),)

            for (scale, a) in layers:
                v = base_v * (s * scale) + ctr
                c = np.tile(np.array([*tint, a], dtype=np.float32),
                            (len(v), 1))
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
        """切换选中原子标记形状：wrap（默认）/ sphere / torus / glow。

        IboView 风格的二十面体（icosahedron）已移除。
        """
        if name not in ("wrap", "sphere", "torus", "glow"):
            return
        self._sel_marker_shape = name
        if self._selected_atoms:
            self._gen_selection_marker()
            self._needs_upload = True
            self.update()

    def set_selection_tint(self, rgb):
        """设置选中高亮色（0..1 的 RGB 三元组）。"""
        try:
            r, g, b = (float(v) for v in rgb)
        except Exception:
            return self._sel_tint
        self._sel_tint = (max(0.0, min(1.0, r)),
                          max(0.0, min(1.0, g)),
                          max(0.0, min(1.0, b)))
        self._refresh_selection()
        return self._sel_tint

    def get_selection_tint(self):
        return self._sel_tint

    def set_selection_wrap_alpha(self, a):
        """设置选中包裹壳的不透明度（0..1）。"""
        try:
            a = float(a)
        except (TypeError, ValueError):
            return self._sel_wrap_alpha
        self._sel_wrap_alpha = max(0.0, min(1.0, a))
        self._refresh_selection()
        return self._sel_wrap_alpha

    def _refresh_selection(self):
        """选中属性变化后重建标记并重算原子几何（本体染色随之更新）。"""
        if self._selected_atoms:
            self._gen_selection_marker()
            self._regenerate_atoms()
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

        逐键覆盖（实/虚/双/三/断）按**原子序数签名**判定是否保留：
        同一分子换几何（IRC 逐帧、优化步）时签名不变 → 用户的逐键标注保留；
        载入另一个分子时签名变了 → 清空，避免同一组原子下标把上一分子的
        双键标注带到新分子上。
        """
        # 载入新分子即丢弃上一场景的 AIM 覆盖层（避免跨 tab 残留）
        self._aim_cps = []
        self._aim_path_pts = []
        if not atoms:
            self._molecule = None
            self._mol_sig = None
            self._bond_overrides.clear()
            self._gen_atoms()
            self._needs_upload = True
            self.update()
            return
        # 逐键覆盖：换分子才清（签名 = 原子序数序列）。
        # 原子格式兼容两种：ovcanvas 侧 (idx, symbol, anum, (x,y,z)) 与
        # 立方体侧 (anum, charge, x, y, z)。
        sig = _atom_signature(atoms)
        if sig != self._mol_sig:
            self._bond_overrides.clear()
            self._mol_sig = sig
        # 载入新分子时清除旧轨道残留（若有），保证只显示分子结构
        self._cube = None
        self._pos_surf = None
        self._neg_surf = None
        self._orbital_recs = []
        self._orbital_flipped = []
        self._orbital_pair_mode = []
        self._surf_vcolor = False   # 表面已清除
        self._orbital_gen += 1      # 轨道数据已清空：旧异步结果作废
        self._cancel_mc()
        # 平面填充 / 配位多面体随旧原子坐标一并失效（全部清除）
        self._fill_items = []
        self._poly_items = []
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
        # 新结构：按元素半径倍率恢复默认（不跨文件携带）
        self._elem_r_mult.clear()
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
        self._orbital_pair_mode = []
        self._surf_vcolor = False
        self._extrema_pts = []
        self._extrema_vals = []
        self._extrema_labels = False
        self._aim_cps = []
        self._aim_path_pts = []
        self._fill_items = []
        self._poly_items = []
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

    def set_color_scale_cmap(self, cmap_name, invert=False):
        """设置色标条使用的配色（与 ESP 表面配色一致）。

        invert=True 时翻转方向（低值端↔高值端互换），对任意配色通用。
        """
        self._cs_cmap = self._resolve_cmap(cmap_name, invert=invert)
        self._cs_cmap_name = cmap_name or ""
        self._cs_invert = bool(invert)
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

    def _draw_extrema_labels(self, p=None, w=None, h=None):
        """在画布上为每个极值点叠加 ESP 数值标签。

        导出时传入 p（已按导出比例缩放的 QPainter）与画布逻辑尺寸 w/h，
        把同一套标签画到导出图上；p 为 None 时走屏幕绘制。
        """
        if not self._extrema_pts or not self._extrema_labels:
            return
        own = p is None
        if own:
            p = QPainter(self)
        w0 = max(1, w if w is not None else self.width())
        h0 = max(1, h if h is not None else self.height())
        try:
            p.setRenderHint(QPainter.Antialiasing)
            p.setRenderHint(QPainter.TextAntialiasing)
            fs = int(self._extrema_label_font)
            dist = int(self._extrema_label_dist)
            border = bool(self._extrema_label_border)
            if own:
                # 屏幕：走离屏超采样贴图（与色标条 / 键长标注同一对策）。
                # 直接在 GL 画布上 drawText，笔画会被摊成半透明灰、缺笔，
                # 看上去就是"字烂了"（实测整块标签没有一个实心像素）。
                p.setRenderHint(QPainter.SmoothPixmapTransform, True)
                for i, (ex, ey, ez, ekind) in enumerate(self._extrema_pts):
                    sx, sy, visible = self._world_to_screen(ex, ey, ez, w0, h0)
                    if not visible:
                        continue
                    val = (self._extrema_vals[i]
                           if i < len(self._extrema_vals) else None)
                    txt = f"{val:.2f}" if val is not None else ""
                    is_max = str(ekind).lower() in ("max", "pos")
                    color = (QColor(190, 140, 0) if is_max
                             else QColor(20, 90, 160))
                    img, bw, bh = self._extrema_label_image(txt, fs, color,
                                                            border)
                    # 保持原来的锚点：max 标签底边 = 点上方 dist；min 顶边 = 下方
                    ty = sy - dist - (bh - 1.0) if is_max else sy + dist - 1.0
                    p.drawImage(QRectF(round(sx - bw / 2.0), round(ty),
                                       bw, bh), img)
                return
            f = p.font()
            f.setPointSize(max(6, fs))
            p.setFont(f)
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
            if own:
                p.end()

    def _extrema_label_image(self, txt, fs, color, border):
        """一个极值点数值标签的离屏超采样贴图，返回 (img, 逻辑宽, 逻辑高)。

        贴图四周各留 1px，好把 1px 的边框线包进来；文字用 QPainterPath
        矢量填充（不用 drawText），与键长标注 / 色标条同一套做法。
        同样内容按 (文字, 字号, 字体, 颜色, 边框) 缓存，每帧只做 drawImage。
        """
        f = QFont(self.font())
        f.setPointSize(max(6, int(fs)))
        f.setHintingPreference(QFont.PreferFullHinting)
        fm = QFontMetrics(f)
        tw = fm.horizontalAdvance(txt) + 8       # 与原来直接画的框完全一致
        th = fm.height() + 4
        key = (txt, int(fs), f.family(), color.rgb(), bool(border))
        hit = self._extrema_img_cache.get(key)
        if hit is not None:
            return hit
        bw = (tw + 2) + (tw + 2) % 2             # 取偶数：贴图落在整像素网格
        bh = (th + 2) + (th + 2) % 2
        dpr = max(1.0, float(self.devicePixelRatioF() or 1.0))
        ss = max(1, int(round(3.0 / dpr)))
        img = QImage(max(1, bw * ss), max(1, bh * ss),
                     QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        qp = QPainter(img)
        try:
            qp.setRenderHint(QPainter.Antialiasing)
            qp.setRenderHint(QPainter.TextAntialiasing)
            qp.scale(ss, ss)
            rect = QRectF(1.0, 1.0, tw, th)
            if border:
                qp.fillRect(rect, QColor(255, 255, 255, 200))
                qp.setBrush(Qt.NoBrush)
                qp.setPen(QPen(QColor(120, 120, 120)))
                qp.drawRect(rect)
            fmf = QFontMetricsF(f)
            x0 = rect.center().x() - fmf.horizontalAdvance(txt) / 2.0
            y0 = rect.center().y() + (fmf.ascent() - fmf.descent()) / 2.0
            path = QPainterPath()
            path.addText(QPointF(round(x0), round(y0)), f, txt)
            qp.setPen(Qt.NoPen)
            qp.setBrush(color)
            qp.drawPath(path)
        finally:
            qp.end()
        if len(self._extrema_img_cache) > 400:
            self._extrema_img_cache.clear()
        self._extrema_img_cache[key] = (img, bw, bh)
        return img, bw, bh

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
            r = self._ball_radius(anum)
            out.append((anum, i + 1, ax, ay, az, sx, sy, r * per_bohr, vis))
        return out

    def _draw_mol_overlay(self, p=None, w0=None, h0=None):
        """把 MolViewer（MolCanvas）的 2D 叠加效果画到画布：阴影→十字→原子标签。

        十字与 molcanvas.py 逐字一致：两条**世界空间**圆环
        (azimuth=90°, tilt=71°) 与 (azimuth=205°, tilt=0°)，环半径
        = 0.92×原子世界半径，随分子一起旋转；只画视图 z ≥ 原子中心 z 的
        前向弧，背面不显示（看不到圆球背后的圆环）。

        p/w0/h0：外部 painter 与逻辑尺寸（导出时复用同一套绘制，
        painter 已按 ew/w0、eh/h0 缩放）；None = 直接画到画布上。
        """
        if not (self._shadows or self._crosshair or self._atom_labels != 2):
            return
        if not self._molecule and not (self._cube and self._cube.atoms):
            return
        if w0 is None or h0 is None:
            w0, h0 = max(1, self.width()), max(1, self.height())
        geo = self._atom_screen_geo(w0, h0)
        if not geo:
            return
        own = p is None
        if own:
            p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing)
            p.setRenderHint(QPainter.TextAntialiasing)
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
            self._draw_atom_labels(p, geo)
        finally:
            if own:
                p.end()

    def _draw_atom_labels(self, p, geo):
        """画原子标签（元素符号 / 原子序号）。

        三点保证"看得清"：
          ① 整数像素落点 —— 亚像素定位会把字形插值成半灰，笔画发虚甚至断开；
          ② 完整字形微调（hinting）—— 小字号下不开微调笔画容易被摊薄；
          ③ 反色细描边 —— 黑字压在深色球上、浅字压在浅色球上都还能读出来，
             同时给字形一圈硬边，不再是纯抗锯齿的柔边。
        """
        if self._atom_labels == 2:
            return
        dark = (sum(self._bg[:3]) / 3.0) < 0.5
        fill = QColor(232, 232, 240) if dark else QColor(0, 0, 0)
        halo = QColor(16, 16, 16, 205) if dark else QColor(255, 255, 255, 220)
        base_font = p.font()
        for anum, aidx, ax, ay, az, sx, sy, sr, vis in geo:
            if not vis or sr < 1.0:
                continue
            if self._atom_labels == 0:
                label = ELEMENT_SYMBOLS.get(anum, str(anum))
            else:
                # 原子序号：分子内 1-based 编号（与拾取/保留编号一致）
                label = str(aidx)
            f = QFont(base_font)
            f.setPointSize(max(7, int(sr * 0.7)))
            f.setBold(True)
            f.setHintingPreference(QFont.PreferFullHinting)
            fm = QFontMetrics(f)
            x = int(round(sx - fm.horizontalAdvance(label) / 2.0))
            y = int(round(sy + fm.height() / 3.0))
            path = QPainterPath()
            path.addText(QPointF(x, y), f, label)
            # 描边宽度 1.4px（笔宽居中在字形轮廓上 → 向外的实际halo约 0.7px）：
            # 再细了盖不住断笔，再粗了小字号会糊成一团。
            pen = QPen(halo, 1.4)
            pen.setJoinStyle(Qt.RoundJoin)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            p.setPen(Qt.NoPen)
            p.setBrush(fill)
            p.drawPath(path)

    @staticmethod
    def _bwr_rgb(t):
        """Blue→White→Red 传递函数（t∈[0,1]）。"""
        t = max(0.0, min(1.0, t))
        if t < 0.5:
            k = t / 0.5
            return (k, k, 0.6 + 0.4 * k)
        k = (t - 0.5) / 0.5
        return (0.6 + 0.4 * (1.0 - k), 1.0 - k, 1.0 - k)

    def _resolve_cmap(self, cmap_name, invert=False):
        """把 ESP_CMAPS 配色名解析成 matplotlib Colormap；失败返回 None。

        invert=True 时翻转方向（mpl 名加/去 _r 后缀）。

        统一委托给 esp_viewer._mpl_cmap：那里还负责**构造本程序自造的色标**
        （RWG/BWG 在 matplotlib 里没有同名项，是用 from_list 现搭的）。
        自己再 get_cmap 一次会漏掉这两个，表现为"色彩刻度轴拿不到配色"。
        """
        try:
            from molstudio.panels.esp_viewer import ESP_CMAPS, _mpl_cmap
            mpl_name = (ESP_CMAPS.get(cmap_name, ("bwr_r", True))[0]
                        if ESP_CMAPS else "bwr_r")
            if invert:
                mpl_name = (mpl_name[:-2] if mpl_name.endswith("_r")
                            else mpl_name + "_r")
            return _mpl_cmap(mpl_name)
        except Exception:
            return None

    def _cs_cmap_rgb(self, t):
        """当前配色在 t∈[0,1] 处的 RGB（0..1）。

        注意 _bwr_rgb(u) 是 蓝→白→红（u=0 蓝, u=1 红）。
        需要低值端=红时取 _bwr_rgb(1-t)（即红→白→蓝）。
        """
        if getattr(self, "_cs_cmap", None) is not None:
            try:
                rgba = self._cs_cmap(float(t))
                return (rgba[0], rgba[1], rgba[2])
            except Exception:
                pass
        # 兜底：matplotlib 不可用时，按当前配色方向取红-白-蓝或蓝-白-红
        name = (getattr(self, "_cs_cmap_name", "") or "").upper()
        inverted = bool(getattr(self, "_cs_invert", False))
        # 低值端是否为红：RWB/RdBu 名字默认低值红；BWR 默认低值蓝
        red_low = ("RWB" in name) or ("RDBU" in name)
        if inverted:
            red_low = not red_low
        if red_low:
            return self._bwr_rgb(1.0 - t)   # 红→白→蓝
        return self._bwr_rgb(t)             # 蓝→白→红

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

    def _draw_color_scale(self, p=None, w=None, h=None):
        """叠加 ESP 色标条（QPainter，渐变 + 刻度 + 单位）。

        长度按 _cs_len（画布高/宽比例）计算、位置可被右键拖动（_cs_offx/y），
        支持竖直/水平两种方位与可调刻度段数；几何写入 _cs_geom 供命中检测。
        字体（刻度数字 + 单位）默认 Arial，右键色标条可设置。
        导出时传入 p（已按导出比例缩放的 QPainter）与画布逻辑尺寸 w/h。
        """
        own = p is None
        if own:
            p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing)
            p.setRenderHint(QPainter.TextAntialiasing)
            f = QFont(self._cs_font_family or "Arial",
                      max(6, int(self._cs_font_pt)))
            # 小字号下明确要求完整字形微调（hinting）：不开时笔画容易发糊
            f.setHintingPreference(QFont.PreferFullHinting)
            p.setFont(f)
            fm = p.fontMetrics()
            w0 = w if w is not None else self.width()
            h0 = h if h is not None else self.height()
            n_ticks = int(getattr(self, "_cs_ticks", 5))
            orient = getattr(self, "_cs_orient", "vertical")

            def _grad(rect, horizontal):
                # 注意：PyQt5 的 QLinearGradient 没有 QRectF 构造重载，必须用浮点坐标
                # 语义统一：水平条 左=低值(负)，右=高值(正)；
                #           竖直条 上=高值(正)，下=低值(负)。
                # _cs_cmap_rgb(t) 的 t=0 是低值端（默认 RWB：红），
                # t=1 是高值端（蓝）。
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
                _tw = max([fm.horizontalAdvance(self._fmt_tick(v))
                           for v, _t in labels] or [30])
                lab_w = max(80, _tw + 16)
                for i, (val, t) in enumerate(labels):
                    tx = x0 + bar_w * (1.0 - t)
                    p.drawLine(QPointF(tx, y0 - 3), QPointF(tx, y0 + bar_h + 3))
                    align = Qt.AlignHCenter | Qt.AlignTop
                    if i == 0:
                        align = Qt.AlignRight | Qt.AlignTop
                    elif i == len(labels) - 1:
                        align = Qt.AlignLeft | Qt.AlignTop
                    # TextSingleLine：不让长数字在窄框里换行（换行会被裁掉一半）
                    p.drawText(QRectF(tx - lab_w / 2.0, y0 + bar_h + 4,
                                      lab_w, fm.height() + 6),
                               align | Qt.TextSingleLine, self._fmt_tick(val))
                # 单位文字：按字体度量开框（宽防截断、高防裁行），**单行**绘制
                ubox_w = max(80, fm.horizontalAdvance(self._cs_unit) + 16)
                ubox_h = fm.height() + 4
                ubox_x = max(4, x0 + bar_w - ubox_w)
                ubox_y = y0 - 6 - ubox_h
                p.drawText(QRectF(ubox_x, ubox_y, ubox_w, ubox_h),
                           Qt.AlignRight | Qt.AlignVCenter | Qt.TextSingleLine,
                           self._cs_unit)
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
                _tw = max([fm.horizontalAdvance(self._fmt_tick(v))
                           for v, _t in labels] or [30])
                lab_w = max(44, _tw + 12)
                for i, (val, t) in enumerate(labels):
                    # t=0 是 hi（正值）→ 顶部；t=1 是 lo（负值）→ 底部
                    # （渐变位置 0 也在顶部且取高值端色，颜色与数字一致）
                    ty = y0 + bar_h * t
                    p.drawLine(QPointF(x0 - 3, ty), QPointF(x0 + bar_w + 3, ty))
                    p.drawText(QRectF(x0 - 8 - lab_w,
                                      ty - fm.height() / 2.0 - 2,
                                      lab_w, fm.height() + 4),
                               Qt.AlignRight | Qt.AlignVCenter | Qt.TextSingleLine,
                               self._fmt_tick(val))
                # 单位文字：按字体度量开框（宽防截断、高防裁行），
                # 画到条上方（顶部刻度值之上）、水平居中于色标条；
                # 贴近画布顶部放不下时回退到条下方
                ubox_w = max(48, fm.horizontalAdvance(self._cs_unit) + 16)
                ubox_h = fm.height() + 4
                ubox_x = x0 + bar_w / 2.0 - ubox_w / 2.0
                ubox_x = max(4, min(ubox_x, w0 - 4 - ubox_w))
                ubox_y = y0 - 5 - ubox_h
                if ubox_y < 2:
                    ubox_y = y0 + bar_h + 5
                    if ubox_y + ubox_h > h0 - 2:
                        ubox_y = h0 - 2 - ubox_h
                p.drawText(QRectF(ubox_x, ubox_y, ubox_w, ubox_h),
                           Qt.AlignHCenter | Qt.AlignVCenter | Qt.TextSingleLine,
                           self._cs_unit)
                self._cs_geom = (x0, y0, bar_w, bar_h, "vertical")
                # 两端拖拽小手柄
                p.setBrush(QColor(255, 255, 255))
                p.setPen(QPen(QColor(40, 40, 40)))
                p.drawEllipse(QRectF(x0 + bar_w // 2 - 4, y0 + bar_h - 4, 8, 8))
                p.drawEllipse(QRectF(x0 + bar_w // 2 - 4, y0 - 4, 8, 8))
        finally:
            if own:
                p.end()

    def _tick_values(self, n):
        """返回 [(值, t), ...]，从高到低共 n+1 个等距刻度。"""
        lo, hi = self._cs_low, self._cs_high
        out = []
        for i in range(n + 1):
            t = i / n
            out.append((hi + (lo - hi) * t, t))
        return out

    # ── 色标条叠加层：离屏超采样后贴回（屏幕上文字更清晰）────────────
    def _invalidate_cs_overlay(self):
        self._cs_img = None
        self._cs_img_key = None

    def _build_cs_overlay(self, w0, h0):
        """把色标条渲染到放大 S 倍的离屏图，再缩放贴回画布（等价于叠加层 SSAA）。

        为什么需要：屏幕上的刻度数字只有十几个**设备像素**高，抗锯齿之后看着发虚；
        而导出图是 6 倍分辨率渲染再缩小显示，所以同一个标签显得更锐利。给画布上
        这一小块补上同样的超采样，两者观感就一致了。只覆盖色标条所在的矩形，
        开销可忽略（并且带缓存，只在参数/尺寸变化时重建）。
        """
        geom = getattr(self, "_cs_geom", None)
        if not geom:
            return None
        x0, y0, bw, bh, orient = geom
        if orient == "horizontal":
            # 留足余量：单位文字是按字体度量开的框（"ESP (kcal/mol)" 约 140px），
            # 贴图框若比它窄，两端会被裁掉——上一版就是这么把单位切掉的。
            box = QRectF(x0 - 90, y0 - 46, bw + 180, bh + 92)
        else:
            box = QRectF(x0 - 130, y0 - 46, bw + 210, bh + 92)
        box = box.intersected(QRectF(0, 0, w0, h0))
        if box.width() < 8 or box.height() < 8:
            return None
        # 超采样倍率：目标是"相对逻辑尺寸约 3× 的采样"，因此高分屏上相应减小
        # （画布本身已经按 devicePixelRatio 渲染，再叠 3× 只是徒增开销）。
        s = max(1.0, 3.0 / max(1.0, float(self.devicePixelRatioF() or 1.0)))
        while s > 1.1 and box.width() * box.height() * s * s > 3.0e6:
            s -= 0.5
        img = QImage(max(1, int(round(box.width() * s))),
                     max(1, int(round(box.height() * s))),
                     QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        try:
            p.setRenderHint(QPainter.Antialiasing)
            p.setRenderHint(QPainter.TextAntialiasing)
            p.scale(s, s)
            p.translate(-box.x(), -box.y())
            self._draw_color_scale(p, w0, h0)
        finally:
            p.end()
        return img, box

    def _draw_color_scale_overlay(self, w0, h0):
        """画布上的色标条：优先用超采样缓存贴回，取不到几何时退回直接绘制。"""
        key = (w0, h0, float(getattr(self, "_cs_len", 0.55)),
               getattr(self, "_cs_orient", "vertical"),
               int(getattr(self, "_cs_ticks", 5)),
               int(getattr(self, "_cs_offx", 0)), int(getattr(self, "_cs_offy", 0)),
               self._cs_font_family, int(self._cs_font_pt),
               round(float(getattr(self, "_cs_low", 0.0)), 6),
               round(float(getattr(self, "_cs_high", 0.0)), 6),
               str(getattr(self, "_cs_unit", "")))
        if self._cs_img is None or self._cs_img_key != key:
            built = self._build_cs_overlay(w0, h0)
            if built is None:
                # 首帧还没有 _cs_geom：直接画一遍，下一帧即可走超采样路径
                self._draw_color_scale()
                return
            self._cs_img, self._cs_box = built
            self._cs_img_key = key
        qp = QPainter(self)
        try:
            qp.setRenderHint(QPainter.Antialiasing)
            qp.setRenderHint(QPainter.SmoothPixmapTransform)
            qp.drawImage(self._cs_box, self._cs_img)
        finally:
            qp.end()

    def _composite_overlays(self, img, ew, eh):
        """把 2D QPainter 覆盖层（色标条 / 极值点数值）合成到导出图。

        export_image 的分块离屏只重画 GL 场景（_render），色标条与极值点标签
        是 QPainter 叠加、只在屏幕 paintGL 绘制；这里用同一套绘制函数在导出
        分辨率下重画一遍。绘制坐标沿用画布逻辑尺寸（w0×h0），靠 painter 缩放
        映射到导出像素（x/y 缩放因子分别取 ew/w0、eh/h0，规避宽高四舍五入偏差）。
        """
        w0 = max(1, self.width())
        h0 = max(1, self.height())
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.scale(ew / w0, eh / h0)
        try:
            if getattr(self, "_cs_show", False):
                self._draw_color_scale(p, w0, h0)
            self._draw_extrema_labels(p, w0, h0)
            # 每原子软阴影与原子符号/编号标签同为 QPainter 叠加，屏幕上有、
            # 导出图里也必须有（否则"导出 ≠ 所见"）。
            self._draw_mol_overlay(p, w0, h0)
            # 键长标注也是 QPainter 叠加，导出图里同样要有（否则"导出 ≠ 所见"）；
            # 顺序与屏幕一致：标注压在最上层。
            self._draw_measure_labels(p, w0, h0)
        finally:
            p.end()

    def set_atom_scale(self, scale):
        """Set atom ball radius multiplier and regenerate the molecule model."""
        self._atom_scale = float(scale)
        if self._molecule is not None or self._cube is not None:
            self._gen_atoms()
            self._needs_upload = True
            self.update()

    # ── 按元素调节原子球半径 ──────────────────────────────────────────
    def _ball_radius(self, anum):
        """某元素原子球的显示半径。

        默认表半径 × ATOM_DRAW_SCALE × 全局 _atom_scale × 该元素倍率
        （_elem_r_mult，见 set_element_radius）。凡画原子球的地方都必须走
        这里（_gen_atoms / 拾取容差 / 选中标记 / 屏幕叠加标签），保证
        "所见即所点"。

        两个特例（优先级：手动倍率 > 样式规则 > 默认）：
          · 用户用「元素半径」对话框显式调过该元素 → 以手动倍率为准；
          · 样式打开了 _h_bond_radius（CYLview）→ 氢原子球半径直接取
            化学键圆柱半径，于是 H 球和键一样粗。取"当前键半径"而非写死
            数值，改键粗细时氢原子会跟着走，观感始终一致。
        """
        z = int(anum)
        if z not in self._elem_r_mult:
            if self._h_bond_radius and z == 1:
                return self._bond_radius()
            f = 1.0
        else:
            f = self._elem_r_mult[z]
        return _atom_base_radius(anum) * ATOM_DRAW_SCALE * self._atom_scale * f

    def _bond_radius(self):
        """化学键圆柱的半径（与 _gen_atoms 里建键时用的完全同一算式）。

        单独成一个函数是为了让"氢原子 = 键一样粗"这类规则能取到**同一个**
        数值，避免两处算式各改一半。
        """
        return max(BOND_DRAW_SCALE * 0.4 * self._bond_scale,
                   0.04 * self._bond_scale)

    def set_hydrogen_bond_radius(self, enabled):
        """氢原子球半径是否跟随化学键半径（CYLview 观感：H 与键一样粗）。

        属于样式属性（随样式文件保存/载入、换分子后仍生效），不是手动微调；
        用户若在「元素半径」里显式调过氢，则以手动值为准。
        """
        on = bool(enabled)
        if on == self._h_bond_radius:
            return
        self._h_bond_radius = on
        if self._molecule is not None or self._cube is not None:
            self._gen_atoms()
            self._needs_upload = True
            self.update()

    def hydrogen_bond_radius(self):
        """氢原子球半径是否跟随化学键半径。"""
        return bool(self._h_bond_radius)

    def set_element_radius(self, anum, mult):
        """单独调节某元素（原子序数）原子球的半径倍率（0.2..4.0）。

        倍率只影响该元素原子球的显示大小，不改坐标、不改键长/键型判定。
        设为 1.0 即恢复该元素默认。修改后自动重建分子模型。
        """
        z = int(anum)
        m = max(0.2, min(4.0, float(mult)))
        before = self._elem_r_mult.get(z, 1.0)
        if abs(m - 1.0) < 1e-4:
            self._elem_r_mult.pop(z, None)
        else:
            self._elem_r_mult[z] = m
        after = self._elem_r_mult.get(z, 1.0)
        if after != before and (self._molecule is not None or self._cube is not None):
            self._gen_atoms()
            self._needs_upload = True
            self.update()

    def element_radius(self, anum):
        """查询某元素当前半径倍率（默认 1.0）。"""
        return self._elem_r_mult.get(int(anum), 1.0)

    def reset_element_radii(self):
        """清空全部按元素倍率（恢复 1.0）并重建分子模型。"""
        if not self._elem_r_mult:
            return
        self._elem_r_mult.clear()
        if self._molecule is not None or self._cube is not None:
            self._gen_atoms()
            self._needs_upload = True
            self.update()

    def present_elements(self):
        """当前载入结构（分子或 cube 头）里出现过的元素（原子序数，升序）。"""
        atoms = self._molecule
        if not atoms and self._cube is not None:
            atoms = getattr(self._cube, "atoms", None)
        els = set()
        for a in (atoms or []):
            try:
                els.add(int(a[0]))
            except (TypeError, ValueError):
                continue
        return sorted(els)

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
        """Set dashed bond fill ratio (0..1). 0.4 = default."""
        self._dash_weight = max(0.05, min(1.0, float(value)))
        if self._molecule is not None or self._cube is not None:
            self._gen_atoms()
            self._needs_upload = True
            self.update()

    def set_dot_size(self, value):
        """虚线大小倍率（0.2 ~ 4.0）。

        点阵样式下缩放点的半径；短圆柱段样式下缩放段的粗细
        （默认 1.0 = 段与单键等粗）。
        """
        self._dot_size_scale = max(0.2, min(4.0, float(value)))
        if self._molecule is not None or self._cube is not None:
            self._gen_atoms()
            self._needs_upload = True
            self.update()

    def set_dot_spacing(self, value):
        """虚线间距倍率（0.3 ~ 4.0；>1 更稀疏）。两种样式通用。"""
        self._dot_spacing_scale = max(0.3, min(4.0, float(value)))
        if self._molecule is not None or self._cube is not None:
            self._gen_atoms()
            self._needs_upload = True
            self.update()

    def set_dash_style(self, style):
        """虚线样式：'dots' 小圆球点阵（默认）/ 'dashes' 短圆柱段（真虚线）。

        影响普通虚线键与离域键的那根虚线。改完立即重建分子网格。
        """
        s = str(style).lower()
        if s not in DASH_STYLE_NAMES:
            raise ValueError(f"未知虚线样式: {style!r}（可选 {DASH_STYLE_NAMES}）")
        if s != self._dash_style:
            self._dash_style = s
            if self._molecule is not None or self._cube is not None:
                self._gen_atoms()
                self._needs_upload = True
            self.update()
        return self._dash_style

    def dash_style(self):
        """当前虚线样式（'dots' / 'dashes'）。"""
        return self._dash_style

    def set_bond_mode(self, mode):
        """成键模式（两类）：

        'single' 一律单键 —— 检测到的键全部画成实线单键（本项目既有行为）。
        'auto'   按键长自动判定键型 —— 用键长与单键共价半径和的比值 q 推出
                 单键 / 离域键(1.5) / 双键 / 三键；只对 C/N/O 之间的键生效。
        右键逐键指定的键型优先于本模式。改完立即重建分子网格。
        """
        m = str(mode).lower()
        if m not in BOND_MODE_NAMES:
            raise ValueError(f"未知成键模式: {mode!r}（可选 {BOND_MODE_NAMES}）")
        if m != self._bond_mode:
            self._bond_mode = m
            if self._molecule is not None or self._cube is not None:
                self._gen_atoms()
                self._needs_upload = True
            self.update()
        return self._bond_mode

    def bond_mode(self):
        """当前成键模式（'single' / 'auto'）。"""
        return self._bond_mode

    def bond_auto_orders(self):
        """最近一次自动判定结果：{(i,j) 0 基: (order, q)}。

        仅 'auto' 模式下有内容；order ∈ {1, 1.5, 2, 3}，q 为判据比值。
        """
        return dict(self._bond_auto_orders)

    def auto_order_for(self, i, j):
        """查询某一对原子的自动判定结果，返回 (order, q)；无内容返回 (None, None)。"""
        return self._bond_auto_orders.get((min(i, j), max(i, j)), (None, None))

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

    # ── Projection ──

    def _projection(self, w, h, vp=None):
        """Orthographic projection.

        The visible half-height is `BASE_EXTENT / zoom`, the camera sits at a
        fixed distance, and the near/far planes bracket it generously so
        rotation never clips.
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
            near, far = self._near_far()
            return ortho(lx, ux, ly, uy, near, far)
        asp = w / h if h > 0 else 1.0
        hw = hh * asp
        near, far = self._near_far()
        return ortho(-hw, hw, -hh, hh, near, far)

    def _near_far(self):
        """正交投影的近/远裁剪面：以相机距离为基准的宽松范围。

        近裁剪面取相机距离的 10%、远裁剪面取 3 倍距离（自定系数），
        保证分子在任意旋转角度下都不会被裁剪，同时维持合理的深度精度。
        """
        d = self.cam.CAM_DIST
        return 0.1 * d, 3.0 * d

    def _render(self, w=None, h=None, vp=None, bg=None):
        # QOpenGLWidget's framebuffer is already scaled by devicePixelRatio,
        # so use the widget size directly for the viewport.  `w`/`h` may be
        # overridden for offscreen high-resolution (supersampled) export.  `vp`
        # is an optional (ox, oy, tw, th, ew, eh) tile window (see _projection).
        # `bg` overrides the clear colour (used by transparent export so the
        # offscreen tiles clear to alpha=0 instead of the opaque self._bg).
        if w is None or h is None:
            w = max(1, self.width()); h = max(1, self.height())
        proj = self._projection(w, h, vp)
        view = self.cam.view()
        nm = self.cam.normal()

        glViewport(0, 0, w, h)
        # 背景写进场景目标，须与场景同色彩域（线性模式下线性化，否则后处理
        # 转回 sRGB 时背景会被 pow 抬亮）。
        _bg_eff = (bg if bg is not None else self._bg)
        if self._linear_space:
            _bg_eff = tuple(x ** 2.2 if i < 3 else x
                            for i, x in enumerate(tuple(_bg_eff)))
        glClearColor(*_bg_eff)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        # ── MolViewer 三段竖向背景渐变（先于所有 3D 几何） ──
        if getattr(self, "_bg_grad", None) is not None and self._prog_bg:
            glDisable(GL_DEPTH_TEST); glDepthMask(GL_FALSE)
            glDisable(GL_BLEND)
            glUseProgram(self._prog_bg)
            t, m, b = self._bg_grad
            if self._linear_space:
                t = tuple(x ** 2.2 for x in t)
                m = tuple(x ** 2.2 for x in m)
                b = tuple(x ** 2.2 for x in b)
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

        if not self._render_transparency(view, nm, proj, w, h):
            self.render_transparent_sorted_fallback(view, nm, proj)

        # 选中原子标记（半透明二十面体）最后叠加，确保始终可见
        self.render_selection_markers(view, nm, proj)

        glDisable(GL_BLEND)
        glDepthMask(GL_TRUE)

    def _render_post(self):
        """整帧离屏（放大 _post_scale 倍）→ 全屏 pass 降采样 + 边缘暗化 → 屏幕。

        走这条路时 `_render` 的目标尺寸是放大后的，透明合成用的 peel/OIT
        目标也会按同样的尺寸建立，所以透明层同样吃到超采样。任何一步失败
        都自动退回原来的直出路径，不会白屏。
        """
        w = max(1, self.width())
        h = max(1, self.height())
        s = float(self._post_scale)
        sw, sh = max(1, int(round(w * s))), max(1, int(round(h * s)))
        # 在合成前捕获主帧缓冲：create() 会把绑定切到 0（同 _ensure_oit）
        prev_fbo = glGetIntegerv(GL_FRAMEBUFFER_BINDING)
        if not self._compose_post(prev_fbo, 0, 0, w, h, sw, sh):
            # 后处理目标不可用：退回直出路径（不白屏）
            glBindFramebuffer(GL_FRAMEBUFFER, prev_fbo)
            self._render()

    def _compose_post(self, dst_fbo, dx, dy, dw, dh, sw, sh, vp=None, bg=None):
        """场景先渲染到 sw×sh 离屏目标，再经后处理合成到 dst_fbo 的 (dx,dy,dw,dh)。

        **实时预览与高分辨率导出共用同一条合成路径**：超采样抗锯齿、SSAO、
        边缘暗化、色调映射、暗角都在这里生效。旧实现里导出直接走 _render()，
        整条后处理被跳过，导致"屏幕上调好的效果一导出就没了"。

        dst_fbo: 目标帧缓冲（屏幕 / 导出瓦片 FBO）
        dx..dh:  目标区域（GL 视口，左下角原点）
        sw, sh:  离屏渲染分辨率（= 目标尺寸 × 超采样倍率）
        vp:      None = 整幅；否则 (ox, oy, tw, th, ew, eh) 瓦片子窗口，
                 坐标需与 sw/sh 处于同一缩放（见 _projection）
        bg:      清屏色；None = 当前背景色（透明导出传 alpha=0）
        返回 True = 已合成；False = 不可用，调用方应回退直出路径。
        """
        s = sw / max(dw, 1)
        try:
            if self._post.fbo == 0 or self._post.w != sw or self._post.h != sh:
                self._post.create(sw, sh)
        except Exception as e:
            self._post_ok = False
            self._status(f"后处理目标创建失败，已关闭后处理: {e}")
            return False
        # 透明合成目标要在绑定离屏目标之前建好：create() 会把绑定切到 0
        try:
            if self._peel_ok:
                self._ensure_peel_targets(sw, sh)
            if self._oit_ok:
                self._ensure_oit_target(sw, sh)
        except Exception:
            pass

        glBindFramebuffer(GL_FRAMEBUFFER, self._post.fbo)
        self._render(sw, sh, vp=vp, bg=bg)

        # SSAO：半分辨率深度预通道 → AO 图（后处理 pass 里乘进去）
        if self._post_ao > 0.0 and self._ao_ok and self._prog_ao:
            proj = self._projection(sw, sh, vp)
            self._render_ao(self.cam.view(), self.cam.normal(), proj, sw, sh)

        glBindFramebuffer(GL_FRAMEBUFFER, dst_fbo)
        glViewport(dx, dy, dw, dh)
        glDisable(GL_DEPTH_TEST)
        glDepthMask(GL_FALSE)
        glDisable(GL_BLEND)
        glUseProgram(self._prog_post)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self._post.tex_color)
        glUniform1i(glGetUniformLocation(self._prog_post, "uScene"), 0)
        glUniform2f(glGetUniformLocation(self._prog_post, "uTexel"),
                    1.0 / sw, 1.0 / sh)
        glUniform1f(glGetUniformLocation(self._prog_post, "uScale"), s)
        glUniform1f(glGetUniformLocation(self._prog_post, "uEdge"),
                    float(self._post_edge))
        glUniform1f(glGetUniformLocation(self._prog_post, "uEdgeSoft"),
                    float(self._post_edge_soft))
        glUniform1f(glGetUniformLocation(self._prog_post, "uEdgeRadius"),
                    float(self._post_edge_r))
        glUniform1f(glGetUniformLocation(self._prog_post, "uTone"),
                    float(self._post_tone))
        glUniform1f(glGetUniformLocation(self._prog_post, "uVig"),
                    float(self._post_vig))
        # SSAO：没启用时绑一张 1×1 的全 0 图（占位，避免采样未绑定纹理）
        glUniform1f(glGetUniformLocation(self._prog_post, "uAo"),
                    float(self._post_ao) if self._ao_ok else 0.0)
        glActiveTexture(GL_TEXTURE1)
        if self._ao_ok and self._ao.tex_ao:
            glBindTexture(GL_TEXTURE_2D, self._ao.tex_ao)
        else:
            glBindTexture(GL_TEXTURE_2D, 0)      # uAo=0，不会真的采样
        glUniform1i(glGetUniformLocation(self._prog_post, "uAoTex"), 1)
        # AO 图分辨率（供后处理里的 5 抽去噪）
        glUniform1f(glGetUniformLocation(self._prog_post, "uAoTexel"),
                    1.0 / max(1, getattr(self._ao, "w", 1)))
        glUniform1f(glGetUniformLocation(self._prog_post, "uAoBlur"),
                    float(_AO_BLUR_SPACING))
        # 色彩空间：后处理负责把线性场景转回 sRGB 输出（u_Linear=0 时直通）
        glUniform1i(glGetUniformLocation(self._prog_post, "u_Linear"),
                    1 if getattr(self, '_linear_space', False) else 0)
        glActiveTexture(GL_TEXTURE0)
        glBindVertexArray(self._vao_bg)
        glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
        glBindVertexArray(0)
        glBindTexture(GL_TEXTURE_2D, 0)
        glDepthMask(GL_TRUE)
        return True

    def _render_ao(self, view, nm, proj, w, h):
        """SSAO：①半分辨率深度预通道（原子/键/等值面最前层）②全屏 AO。

        之所以要单独的深度预通道：透明等值面不写主帧缓冲的深度，直接拿主深度
        算 AO 就完全没有等值面的遮蔽。这里等值面只取最前一层 —— AO 正是用最
        前层深度估算的（标准 SSAO 的固有近似）。
        """
        _k = max(0.25, min(1.0, float(_AO_RES_SCALE)))
        aw, ah = max(1, int(w * _k)), max(1, int(h * _k))
        try:
            if self._ao.fbo_ao == 0 or self._ao.w != aw or self._ao.h != ah:
                self._ao.create(aw, ah)
        except Exception as e:
            self._ao_ok = False
            self._status(f"SSAO 目标创建失败，已关闭 AO: {e}")
            return

        prev = glGetIntegerv(GL_FRAMEBUFFER_BINDING)
        # ── ① 深度预通道（无颜色附件）──
        glBindFramebuffer(GL_FRAMEBUFFER, self._ao.fbo_depth)
        glDrawBuffer(GL_NONE)
        glViewport(0, 0, aw, ah)
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LESS)
        glDepthMask(GL_TRUE)
        glDisable(GL_BLEND)
        glClear(GL_DEPTH_BUFFER_BIT)
        glUseProgram(self._prog_depth)
        self._set_xforms(self._prog_depth, view, nm, proj)
        # 原子 + 键 + 正/负相位等值面（只写深度，颜色无关紧要）
        self._meshes[2].draw()
        try:
            self._bond_mesh.draw()
        except Exception:
            pass
        for i in (0, 1):
            if self._meshes[i].count:
                self._meshes[i].draw()
        glDrawBuffer(GL_COLOR_ATTACHMENT0)

        # ── ② 全屏 AO ──
        glBindFramebuffer(GL_FRAMEBUFFER, self._ao.fbo_ao)
        glViewport(0, 0, aw, ah)
        glDisable(GL_DEPTH_TEST)
        glDepthMask(GL_FALSE)
        glDisable(GL_BLEND)
        glUseProgram(self._prog_ao)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self._ao.tex_depth)
        glUniform1i(glGetUniformLocation(self._prog_ao, "uDepth"), 0)
        glUniform2f(glGetUniformLocation(self._prog_ao, "uTexel"), 1.0 / aw, 1.0 / ah)
        # 正交投影：视图空间尺寸 / 像素 与 / 单位窗口 z
        sx = 2.0 / (proj[0][0] * aw) if abs(proj[0][0]) > 1e-12 else 1.0
        sy = 2.0 / (proj[1][1] * ah) if abs(proj[1][1]) > 1e-12 else 1.0
        sz = 2.0 / proj[2][2] if abs(proj[2][2]) > 1e-12 else 1.0
        glUniform3f(glGetUniformLocation(self._prog_ao, "uPixToView"),
                    abs(sx), abs(sy), abs(sz))
        # 采样环用**像素**（屏幕空间，缩放无关）：AO 着色器内部再换算成视图
        # 单位；uDepthScale 是相对半径的深度偏置（避开平面自遮挡）。
        glUniform1f(glGetUniformLocation(self._prog_ao, "uRadiusPx"),
                    float(self._post_ao_r))
        glUniform1f(glGetUniformLocation(self._prog_ao, "uDepthScale"),
                    float(self._post_ao_d))
        glUniform1f(glGetUniformLocation(self._prog_ao, "uIntensity"), 1.0)
        glUniform2f(glGetUniformLocation(self._prog_ao, "uTexSize"),
                    float(aw), float(ah))
        # 切平面判据阈值：0.08 足以剔除同面/凸面剪影的假遮挡，又不会漏掉
        # 缝隙里朝向本点的那一侧表面
        glUniform1f(glGetUniformLocation(self._prog_ao, "uTangentBias"),
                    float(_AO_TANGENT_BIAS))
        glUniform1f(glGetUniformLocation(self._prog_ao, "uGain"), float(_AO_GAIN))
        glBindVertexArray(self._vao_bg)
        glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
        glBindVertexArray(0)
        glBindFramebuffer(GL_FRAMEBUFFER, prev)
        glDepthMask(GL_TRUE)

    def render_opaque(self, view, nm, proj, depth_func=GL_LESS):
        """Opaque geometry (atoms): depth test + depth write, no blending.

        depth_func：默认 GL_LESS；在 vdW 外壳之后重绘原子+键时用 GL_LEQUAL，
        保证与原有深度相等的片元也能通过（避免同深度被 LESS 淘汰而画不上）。
        """
        glEnable(GL_DEPTH_TEST); glDepthFunc(depth_func); glDepthMask(GL_TRUE)
        glDisable(GL_BLEND)
        glUseProgram(self._prog_atom)
        self._set_xforms(self._prog_atom, view, nm, proj)
        self.set_shader_uniforms(self._prog_atom, self._sp['a_reg'],
                                  diffuse=(0.8, 0.8, 0.8, 1.0),
                                  ambient=self._user_ambient,
                                  spec_mul=self._user_spec_mul,
                                  spec_color=self._sp.get('spec_color',
                                                          (1.0, 1.0, 1.0)))
        self._set_atom_outline_uniforms()
        self._set_atom_mv_uniforms(True)
        self._set_atom_ring_uniforms(True)
        self._meshes[2].draw()

        # PT (点云) 模式：把 ESP 等值面顶点渲染成彩色点（不透明），
        # 下方透明通道会跳过三角面。
        if self._esp_point_mode:
            glUseProgram(self._prog_orb)
            self._set_xforms(self._prog_orb, view, nm, proj)
            self.set_shader_uniforms(self._prog_orb, self._sp['o_reg'],
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
        # 键材质：默认跟随原子寄存器；设置了独立键光泽则只覆盖镜面强度槽
        regs = self._sp['a_reg']
        bgl = self._bond_gloss
        if bgl is not None:
            regs = list(regs)
            regs[2] = _GLOSS_SPEC_MAX * max(0.0, min(1.0, bgl))
        k = float(getattr(self, "_bond_diffuse", 0.8))
        self.set_shader_uniforms(self._prog_bond, regs,
                                 diffuse=(k, k, k, 1.0),
                                 ambient=self._user_ambient,
                                 spec_mul=self._user_spec_mul,
                                 spec_color=self._sp.get('spec_color',
                                                         (1.0, 1.0, 1.0)))
        self._set_mv_grad_uniform(self._prog_bond, self._mv_grad)
        self._bond_mesh.draw()
        if was_cull:
            glEnable(GL_CULL_FACE)

    def render_selection_markers(self, view, nm, proj):
        """绘制选中原子的半透明包裹壳。

        深度测试但**不写深度**，用标准 alpha 混合叠加在不透明几何之上。
        与 `_gen_atoms` 里对选中原子本体的染色配合，构成完整的高亮效果。
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
        self.set_shader_uniforms(self._prog_atom, self._sp['a_reg'],
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
        self.set_shader_uniforms(
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
        # u_MvGrad=0 走多灯 Phong（含 FX），随当前样式变化。
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

    def _render_transparency(self, view, nm, proj, w, h):
        """按 self._transparency_mode 分派透明合成，失败逐级回退。

        返回 True 表示已绘制（调用方就不必再走排序混合兜底）。
        """
        main_fbo = glGetIntegerv(GL_FRAMEBUFFER_BINDING)
        mode = self._transparency_mode

        # 透明模式分派顺序：用户选择的模式优先，失败后先试另一种现代 OIT
        # （peel / oit 互备），最后落到排序混合。
        order = {
            "oit": ("oit", "peel", "sorted"),
            "peel": ("peel", "oit", "sorted"),
            "sorted": (),
        }.get(mode, ("oit", "peel", "sorted"))

        for m in order:
            if m == "oit" and not (self._oit_ok and self._prog_orb_oit):
                continue
            if m == "peel" and not (self._peel_ok and self._prog_orb_peel):
                continue
            try:
                if m == "peel":
                    ok = self.render_transparent_peel(view, nm, proj, w, h)
                else:
                    ok = self.render_transparent_oit(view, nm, proj, w, h)
                if ok:
                    return True
            except Exception as e:
                if m == "peel":
                    self._peel_ok = False
                else:
                    self._oit_ok = False
                self._status(f"{m} 失败，尝试下一种透明模式: {e}")
                # 中途异常可能残留自定义 FBO / 逐缓冲混合状态：
                # 复位到进入本函数时的 FBO（分块导出时不是 0）。
                glBindFramebuffer(GL_FRAMEBUFFER, main_fbo)
                glViewport(0, 0, w, h)
                glEnable(GL_DEPTH_TEST)
                glDepthFunc(GL_LESS)
                glDepthMask(GL_TRUE)
                glDisable(GL_BLEND)
        return False

    def render_transparent_oit(self, view, nm, proj, w, h):
        """Weighted Blended OIT —— 单趟顺序无关透明（本项目自研路径）。

        算法：McGuire & Bavoil, "Weighted Blended Order-Independent
        Transparency", JCGT 2(2):122-141, 2013。

        流程：
          1. 把不透明几何（原子/键）的深度重绘进 OIT 目标的深度附件，
             使透明等值面被正确遮挡（不写颜色）。
          2. 单趟绘制透明等值面，MRT 输出 (accum, reveal)，
             逐缓冲混合：accum 加性、reveal 乘法。深度测试开、深度写关。
          3. 全屏合成：平均色 = accum.rgb / accum.a，
             以 revealage 作为"背景透过率"混合到主帧缓冲。
        """
        if self._esp_point_mode:
            return True  # PT 点云模式：点已在 render_opaque 画完
        # 在 _ensure 之前捕获主帧缓冲：_ensure 因尺寸变化重建目标时 create()
        # 会把绑定切到 0，若之后才取 main_fbo 会拿到 0，合成/读回就落到屏幕。
        main_fbo = glGetIntegerv(GL_FRAMEBUFFER_BINDING)
        if not self._ensure_oit_target(w, h):
            return False
        if self._meshes[0].count == 0 and self._meshes[1].count == 0:
            glBindFramebuffer(GL_FRAMEBUFFER, main_fbo)   # 重建后可能残留 FB 0
            return True

        # ── 1. 深度播种：只写深度，不写颜色 ──
        self._oit.bind(w, h)
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LESS)
        glDepthMask(GL_TRUE)
        glDisable(GL_BLEND)
        glColorMask(GL_FALSE, GL_FALSE, GL_FALSE, GL_FALSE)
        glUseProgram(self._prog_atom)
        self._set_xforms(self._prog_atom, view, nm, proj)
        self.set_shader_uniforms(self._prog_atom, self._sp['a_reg'],
                                 diffuse=(0.8, 0.8, 0.8, 1.0),
                                 ambient=self._user_ambient,
                                 spec_mul=self._user_spec_mul,
                                 spec_color=self._sp.get('spec_color',
                                                         (1.0, 1.0, 1.0)))
        self._set_atom_outline_uniforms()
        self._set_atom_mv_uniforms(True)
        self._set_atom_ring_uniforms(True)
        self._meshes[2].draw()

        # 键也要参与遮挡，否则等值面里的键会"透视"出来。
        # render_bonds 默认用 GL_LEQUAL，这里显式传 GL_LESS 与上面的原子保持一致。
        try:
            self.render_bonds(view, nm, proj, depth_func=GL_LESS)
        except Exception:
            pass
        glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE)

        # ── 2. 单趟累积透明片元 ──
        prog = self._prog_orb_oit
        glUseProgram(prog)
        self._set_xforms(prog, view, nm, proj)
        self._set_orbital_uniforms(prog)

        # 权重的深度项需要"场景自身的深度跨度"，而不是整个裁剪范围：
        # 正交投影下分子只占 [near, far] 里极小一段，直接用会把权重压成常数。
        # 包围球直径与旋转无关，是最稳的跨度估计。
        near, far = self._near_far()
        span_world = 2.0 * self.cam.half_height() / 1.15   # = 包围球直径
        span_z = span_world / max(far - near, 1e-6)
        z_mid = (self.cam.CAM_DIST - near) / max(far - near, 1e-6)
        glUniform1f(glGetUniformLocation(prog, 'u_OitZMin'), z_mid - 0.5 * span_z)
        glUniform1f(glGetUniformLocation(prog, 'u_OitZSpan'), span_z)
        glUniform1f(glGetUniformLocation(prog, 'u_OitFalloff'),
                    float(getattr(self, '_oit_falloff', 4.0)))

        glEnable(GL_BLEND)
        # accum: dst += src        reveal: dst *= (1 - src.a)
        _glBlendFunci(0, GL_ONE, GL_ONE)
        _glBlendFunci(1, GL_ZERO, GL_ONE_MINUS_SRC_COLOR)
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LESS)
        glDepthMask(GL_FALSE)

        self._meshes[0].draw()
        self._meshes[1].draw()

        # ── 3. 合成到主帧缓冲 ──
        glBindFramebuffer(GL_FRAMEBUFFER, main_fbo)
        glViewport(0, 0, w, h)
        glDisable(GL_DEPTH_TEST)
        glDepthMask(GL_FALSE)
        glEnable(GL_BLEND)
        # 恢复为全局（非逐缓冲）混合函数，避免污染后续绘制
        glBlendFunc(GL_ONE_MINUS_SRC_ALPHA, GL_SRC_ALPHA)

        glUseProgram(self._prog_combine_oit)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self._oit.tex_accum)
        glUniform1i(glGetUniformLocation(self._prog_combine_oit, 'Accum'), 0)
        glActiveTexture(GL_TEXTURE1)
        glBindTexture(GL_TEXTURE_2D, self._oit.tex_reveal)
        glUniform1i(glGetUniformLocation(self._prog_combine_oit, 'Reveal'), 1)
        glBindVertexArray(self._vao_quad)
        glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
        glBindVertexArray(0)

        glActiveTexture(GL_TEXTURE1)
        glBindTexture(GL_TEXTURE_2D, 0)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, 0)
        glBindFramebuffer(GL_FRAMEBUFFER, main_fbo)
        glViewport(0, 0, w, h)
        glEnable(GL_DEPTH_TEST)
        glDepthMask(GL_TRUE)
        return True

    def render_transparent_peel(self, view, nm, proj, w, h):
        """Depth peeling（Everitt 2001）—— 多趟顺序无关透明（本项目独立实现）。

        流程（front-to-back，由近及远逐层剥离）：
          0. 把不透明几何（原子/键）深度播种进 tex_opaque（每帧一次）；
          1. 每趟：草稿目标清零后**关混合**重画全部透明几何 —— 片元着色器
             先丢弃"在不透明几何之后"（z ≥ tex_opaque）与"比上一趟剥出层
             更近/同深"（第 k≥2 趟）的片元，硬件深度测试（LESS，深度已清
             1.0）再从剩余片元里挑出本层，直通色写进草稿纹理；
          2. 每趟几何之后：全屏"垫底"趟把草稿层以
               glBlendFuncSeparate(ONE_MINUS_DST_ALPHA, ONE, …)
             垫入累积纹理（front-to-back "under" 累积，与按 近→远 做标准
             over 合成等价）。混合只发生在这步的全屏趟 —— 剥离几何趟内
             绝不混合，否则先画的较远片元会先混入、近层反被垫到其下，
             高不透明度时远层会透到近层前面；
          3. 全部趟完成后：把预乘累积色以 (ONE, ONE_MINUS_SRC_ALPHA)
             合成到主帧（已画好的不透明场景之上）。

        趟数上限 self._peel_layers（默认 4）；超过上限的多层交叠会被截断
        （分子等值面通常只有 1-3 层交叠，肉眼不可见）。
        """
        if self._esp_point_mode:
            return True  # PT 点云模式：点已在 render_opaque 画完
        # 在 _ensure 之前捕获主帧缓冲（原因同 WBOIT 路径：_ensure 重建会切到 0）。
        main_fbo = glGetIntegerv(GL_FRAMEBUFFER_BINDING)
        if not self._ensure_peel_targets(w, h):
            return False
        if self._meshes[0].count == 0 and self._meshes[1].count == 0:
            glBindFramebuffer(GL_FRAMEBUFFER, main_fbo)   # 重建后可能残留 FB 0
            return True
        n_layers = max(1, min(8, int(getattr(self, "_peel_layers", 4) or 4)))

        prog = self._prog_orb_peel
        loc_use = glGetUniformLocation(prog, 'u_UsePrev')
        loc_prev = glGetUniformLocation(prog, 'u_PrevDepth')
        loc_opaque = glGetUniformLocation(prog, 'u_OpaqueDepth')
        prog_acc = self._prog_accum_peel
        loc_layer = glGetUniformLocation(prog_acc, 'Layer')
        peel = self._peel

        # ── 0. 播种不透明几何深度（原子/键，不写颜色），所有趟共享 ──
        peel.bind_opaque(w, h)
        peel.clear_opaque_depth()
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LESS)
        glDepthMask(GL_TRUE)
        glDisable(GL_BLEND)
        glColorMask(GL_FALSE, GL_FALSE, GL_FALSE, GL_FALSE)
        glUseProgram(self._prog_atom)
        self._set_xforms(self._prog_atom, view, nm, proj)
        self.set_shader_uniforms(self._prog_atom, self._sp['a_reg'],
                                 diffuse=(0.8, 0.8, 0.8, 1.0),
                                 ambient=self._user_ambient,
                                 spec_mul=self._user_spec_mul,
                                 spec_color=self._sp.get('spec_color',
                                                         (1.0, 1.0, 1.0)))
        self._set_atom_outline_uniforms()
        self._set_atom_mv_uniforms(True)
        self._set_atom_ring_uniforms(True)
        self._meshes[2].draw()
        try:
            self.render_bonds(view, nm, proj, depth_func=GL_LESS)
        except Exception:
            pass
        glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE)

        # 累积纹理清零
        peel.bind_acc(w, h)
        peel.clear_acc(w, h)

        # ── 逐层剥离：每趟 = 几何关混合画草稿 → 全屏趟垫入累积 ──
        for k in range(1, n_layers + 1):
            i = (k - 1) % 2        # 本趟写 tex_depth[i]
            prev_i = (k - 2) % 2 if k > 1 else -1

            # ① 几何趟 → 草稿纹理（不混合；遮挡与层剔除都在着色器里）
            peel.bind_scratch(i, w, h)
            peel.clear_scratch(w, h)
            glEnable(GL_DEPTH_TEST)
            glDepthFunc(GL_LESS)
            glDepthMask(GL_TRUE)
            glDisable(GL_BLEND)

            glUseProgram(prog)
            self._set_xforms(prog, view, nm, proj)
            self._set_orbital_uniforms(prog)
            glUniform1i(loc_use, 1 if k > 1 else 0)
            # 不透明深度恒绑定在纹理单元 1
            glActiveTexture(GL_TEXTURE1)
            glBindTexture(GL_TEXTURE_2D, peel.tex_opaque)
            glUniform1i(loc_opaque, 1)
            if k > 1:
                # 上一趟剥出层的深度在纹理单元 0
                glActiveTexture(GL_TEXTURE0)
                glBindTexture(GL_TEXTURE_2D, peel.tex_depth[prev_i])
                glUniform1i(loc_prev, 0)
            self._meshes[0].draw()
            self._meshes[1].draw()
            glActiveTexture(GL_TEXTURE1)
            glBindTexture(GL_TEXTURE_2D, 0)
            glActiveTexture(GL_TEXTURE0)
            glBindTexture(GL_TEXTURE_2D, 0)

            # ② 全屏"垫底"趟：草稿层（直通色）→ 预乘 → under 混入累积
            peel.bind_acc(w, h)
            glDisable(GL_DEPTH_TEST)
            glDepthMask(GL_FALSE)
            glEnable(GL_BLEND)
            glBlendFuncSeparate(GL_ONE_MINUS_DST_ALPHA, GL_ONE,
                                GL_ONE_MINUS_DST_ALPHA, GL_ONE)
            glUseProgram(prog_acc)
            glActiveTexture(GL_TEXTURE0)
            glBindTexture(GL_TEXTURE_2D, peel.tex_scratch)
            glUniform1i(loc_layer, 0)
            glBindVertexArray(self._vao_quad)
            glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
            glBindVertexArray(0)
            glActiveTexture(GL_TEXTURE0)
            glBindTexture(GL_TEXTURE_2D, 0)
            glDisable(GL_BLEND)

        # ── 3. 合成到主帧缓冲（预乘累积色 over 已画好的不透明场景）──
        glBindFramebuffer(GL_FRAMEBUFFER, main_fbo)
        glViewport(0, 0, w, h)
        glDisable(GL_DEPTH_TEST)
        glDepthMask(GL_FALSE)
        glEnable(GL_BLEND)
        glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA)
        glUseProgram(self._prog_combine_peel)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, peel.tex_acc)
        glUniform1i(glGetUniformLocation(self._prog_combine_peel, 'Accum'), 0)
        glBindVertexArray(self._vao_quad)
        glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
        glBindVertexArray(0)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, 0)

        # 恢复通用状态（后续绘制各自设置混合/深度，这里给安全默认值）
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glDisable(GL_BLEND)
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LESS)
        glDepthMask(GL_TRUE)
        glBindFramebuffer(GL_FRAMEBUFFER, main_fbo)
        glViewport(0, 0, w, h)
        return True

    def render_transparent_sorted_fallback(self, view, nm, proj):
        """等值面透明回退（Depth peeling 关闭时）：逐三角形画家算法。

        按视图深度从远到近绘制（远的先画、近的盖上来）——与 Depth peeling
        的合成方向一致，近处表面占主导：透明度越高越接近
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
        # 半球环境光：视图空间法线 → 世界空间法线。view 的旋转部分由四元数
        # 生成（正交矩阵），故其转置即逆，不必再求逆矩阵，开销可忽略。
        # 本函数被所有渲染 pass（含 WBOIT / 深度剥离）调用，故一次改动全生效。
        n2w = np.ascontiguousarray(view[:3, :3].T, dtype=np.float32)
        glUniformMatrix3fv(glGetUniformLocation(prog, 'u_NormalToWorld'), 1, GL_TRUE, n2w)

    def _set_regs(self, prog, regs):
        # regs 顺序：[漫反射指数, 漫反射强度, 镜面强度, 镜面锐度]
        names = ('u_DiffusePow', 'u_DiffuseStr', 'u_SpecStr', 'u_SpecSharp')
        for name, val in zip(names, regs):
            glUniform1f(glGetUniformLocation(prog, name), val)

    def set_shader_uniforms(self, prog, regs, diffuse,
                             ambient=0.0, spec_color=(1.0, 1.0, 1.0),
                             spec_mul=1.0, fx=0, fx_strength=0.0,
                             fx_color=(1.0, 1.0, 1.0)):
        """Upload the shader registers, fade parameters, DiffuseColor and the
        extended material uniforms (emissive ambient / tinted specular / orbital
        FX).

        DiffuseColor is kept white for orbitals so that v_Color (the green/red
        phase colour) alone determines the hue; the per-vertex colour carries
        the phase and DiffuseColor.a is the opacity.
        """
        self._set_regs(prog, regs)
        glUniform1f(glGetUniformLocation(prog, 'u_FogBias'), self._sp['FogBias'])
        # 景深雾化开关：关闭时 u_FogWidth=0（无任何雾化），开启时用默认值。
        # FogWidth 表示"场景最深处（包围球远端）的雾化强度"，可用范围 0..2：
        # 1.0 = 最深处完全融入背景；>1 让雾在更浅的深度就饱和（更强）。
        # 上限夹取同时兼容旧样式文件里存的 8.0 之类斜率值。
        fog_w = (max(0.0, min(2.0, float(self._sp['FogWidth'])))
                 if self._fade_enabled else 0.0)
        glUniform1f(glGetUniformLocation(prog, 'u_FogWidth'), fog_w)
        # 雾化终色 = 背景色：白底时与旧观感逐像素一致；深色/彩色背景下
        # 不再"越远越白"（旧实现固定混白）。
        bgc = tuple(self._bg[:3])
        glUniform3f(glGetUniformLocation(prog, 'u_FogColor'),
                    float(bgc[0]), float(bgc[1]), float(bgc[2]))
        # 视图空间深度：正交投影下 window z 与视图深度线性相关
        # （见 _GLSL_COMMON 的 fog_factor）。
        near, far = self._near_far()
        glUniform2f(glGetUniformLocation(prog, 'u_FogDepth'),
                    float(near), float(far - near))
        half_h = float(self.cam.half_height())
        # 场景在视图空间的半径取实际包围球（_scene_r，载入时算出）；没有场景
        # 时退回按取景框估算（half_height / 1.15，见 set_center_zoom）。
        # 中心位于相机距离 CAM_DIST 处，故 t ∈ [-1, 1] 覆盖整个物体深度。
        scene_r = float(getattr(self, "_scene_r", 0.0) or 0.0)
        if scene_r <= 1e-6:
            scene_r = half_h / 1.15
        glUniform2f(glGetUniformLocation(prog, 'u_FogRange'),
                    float(self.cam.CAM_DIST),
                    max(scene_r, 1e-3))
        glUniform4f(glGetUniformLocation(prog, 'DiffuseColor'), *diffuse)
        glUniform1f(glGetUniformLocation(prog, 'u_Ambient'), ambient)
        glUniform4f(glGetUniformLocation(prog, 'u_SpecColor'),
                    spec_color[0], spec_color[1], spec_color[2], 0.0)
        glUniform1f(glGetUniformLocation(prog, 'u_SpecMul'), spec_mul)
        # 等值面 alpha 的光照调制开关。默认 1（调制，与改动前一致）；只有
        # 「默认全不透明」的样式（MolStudio / CYLview / VESTA，见各样式字典的
        # orb_alpha_mod）才把它置 0，让透明度滑块直接线性控制 alpha。
        # 原子/键/范德华外壳也共用本函数，它们始终取 1 —— 它们的 alpha 由
        # DiffuseColor.a 直接给定（原子恒为 1），不受影响。
        glUniform1f(glGetUniformLocation(prog, 'u_AlphaMod'), 1.0)
        glUniform1f(glGetUniformLocation(prog, 'u_Roughness'),
                    float(self._sp.get('roughness', 0.30)))
        glUniform1f(glGetUniformLocation(prog, 'u_CoatRoughness'),
                    float(self._sp.get('coat_roughness', 0.10)))
        glUniform1f(glGetUniformLocation(prog, 'u_CoatStrength'),
                    float(self._sp.get('coat_strength', 0.80)))
        glUniform1i(glGetUniformLocation(prog, 'u_SpecModel'),
                    int(getattr(self, '_spec_model', 1)))
        # 次表面散射：默认 0（标准 Lambert），样式预设未定义时同样为 0
        glUniform1f(glGetUniformLocation(prog, 'u_SssStrength'),
                    float(self._sp.get('sss_strength', 0.0)))
        # 明暗交界线柔化：默认 0（标准 Lambert，与改动前一致）
        glUniform1f(glGetUniformLocation(prog, 'u_SoftTerm'),
                    float(getattr(self, '_soft_term', 0.0)))
        # 等值面背面调暗：默认 0.8（1.0 = 关闭）
        glUniform1f(glGetUniformLocation(prog, 'u_BackDim'),
                    float(self._sp.get('back_dim', 0.8)))
        # 半球环境光（Hemisphere Lighting）
        glUniform1i(glGetUniformLocation(prog, 'u_HemiEnabled'),
                    1 if getattr(self, '_hemi_enabled', False) else 0)
        glUniform3f(glGetUniformLocation(prog, 'u_HemiTop'),
                    *getattr(self, '_hemi_top', (0.18, 0.18, 0.18)))
        glUniform3f(glGetUniformLocation(prog, 'u_HemiBottom'),
                    *getattr(self, '_hemi_bottom', (0.035, 0.035, 0.035)))
        glUniform1f(glGetUniformLocation(prog, 'u_HemiIntensity'),
                    float(getattr(self, '_hemi_intensity', 0.25)))
        # Matcap 材质球纹理（固定纹理单元 2，避开 OIT/peel 的 0/1）
        glActiveTexture(GL_TEXTURE2)
        glBindTexture(GL_TEXTURE_2D, getattr(self, "_matcap_tex", 0))
        glUniform1i(glGetUniformLocation(prog, 'u_Matcap'), 2)
        glActiveTexture(GL_TEXTURE0)
        glUniform1i(glGetUniformLocation(prog, 'u_Fx'), fx)
        glUniform1f(glGetUniformLocation(prog, 'u_FxStrength'), fx_strength)
        glUniform3f(glGetUniformLocation(prog, 'u_FxColor'),
                    fx_color[0], fx_color[1], fx_color[2])
        # 光源：方向（4 盏）+ 数量 + 光晕（u_MvGrad=0 时 shade_base_color 用前 3 盏）
        ld = getattr(self, "_light_dirs", None) or getattr(self, "_light_default_dirs", None) \
            or list(_PHONG_LIGHT_DIRS)
        for i in range(4):
            d = ld[i] if i < len(ld) else (0.0, 0.0, 1.0)
            glUniform3f(glGetUniformLocation(prog, f'u_L{i}'), d[0], d[1], d[2])
        _lc = max(1, min(4, int(getattr(self, "_light_count", 3))))
        glUniform1i(glGetUniformLocation(prog, 'u_LightCount'), _lc)
        # 灯光能量归一化：把 _lc 盏灯的总能量折算回 3 灯基准，
        # 于是增减灯数只改变布光层次，不再整体变亮/变暗。
        glUniform1f(glGetUniformLocation(prog, 'u_LightNorm'),
                    _light_norm_factor(_lc))
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
        self.set_shader_uniforms(
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
        # 等值面 alpha 的调制强度：由样式决定（见 _panel.py 各一键样式字典）。
        # MolStudio / CYLview / VESTA 取 0 → 透明度滑块线性控制等值面（无论是
        # 轨道/相位色表面，还是 ESP / IGMH 这类属性着色表面）；其余样式取 1 →
        # 保持原来的"亮处实、暗处虚"调制观感。
        glUniform1f(glGetUniformLocation(prog, 'u_AlphaMod'),
                    float(getattr(self, '_orb_alpha_mod', 1.0)))
        # 色彩空间（u_Linear：顶点着色器与各 FRAG 共享；0 = sRGB 直通）
        glUniform1i(glGetUniformLocation(prog, 'u_Linear'),
                    1 if getattr(self, '_linear_space', False) else 0)

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

        on=False 时强制 u_MvGrad=0（选中标记等非球棍几何仍用三灯 Phong）。
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
        """把一个程序的 u_MvGrad uniform 设为渐变类型 id（0=三灯 Phong）。"""
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
        # This is NOT the same as the *relative* threshold mode (default
        # 80 %): a relative threshold picks the iso surface enclosing 80 % of
        # the total |data| weight.  Tick "相对阈值" to use that mode.
        gi = QGroupBox("等值面")
        il = QGridLayout(gi)

        self._rel_chk = QCheckBox(
            f"相对阈值 ({_RENDER_DEFAULTS['IsoThreshold']:.0f}%)")
        self._rel_chk.setToolTip(
            "勾选后按相对阈值语义取等值面：\n"
            "选取使 |data| 累积权重达到指定百分比的等值面。\n"
            "取消勾选则使用下方的绝对 isovalue（cube 文件原始单位）。")
        self._rel_chk.toggled.connect(self._on_rel_mode)
        il.addWidget(self._rel_chk, 0, 0, 1, 3)

        self._rel_sld = QSlider(Qt.Horizontal)
        self._rel_sld.setRange(50, 99)
        self._rel_sld.setValue(int(_RENDER_DEFAULTS['IsoThreshold']))
        self._rel_sld.valueChanged.connect(self._on_rel_slider)
        self._rel_sld.setEnabled(False)
        il.addWidget(QLabel("百分比:"), 1, 0)
        il.addWidget(self._rel_sld, 1, 1)
        self._rel_lbl = QLabel(f"{_RENDER_DEFAULTS['IsoThreshold']:.0f}%")
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
        op0 = int(_RENDER_DEFAULTS['OrbitalOpacity'] * 100)
        self._op_sld.setRange(5, 100); self._op_sld.setValue(op0)
        self._op_sld.valueChanged.connect(self._on_op)
        il.addWidget(self._op_sld, 3, 1)
        self._op_edit = QLineEdit(f"{_RENDER_DEFAULTS['OrbitalOpacity']:.2f}")
        self._op_edit.setValidator(QDoubleValidator(0.05, 1, 2))
        self._op_edit.setMaximumWidth(70)
        self._op_edit.editingFinished.connect(self._on_op_edit)
        il.addWidget(self._op_edit, 3, 2)

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

        # Bond detection thresholds (covalent-radius-sum dual-threshold)
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
        self._brf_loose_sld.setValue(130)         # ×1.30 (default)
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
        self._dash_w_sld.setValue(40)         # 0.40 (default)
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

        # High-resolution export (offscreen re-render)
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
            # Relative-threshold mode: derive an absolute isovalue that
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
        p, sel = save_file(self, "Export", "cub_view.png",
                           export_dialog_filter(preferred="png"))
        if not p:
            return
        # 路径扩名 > 对话框过滤器 > PNG
        ext = export_ext_from_path(p, default="")
        if ext not in ("png", "jpg", "tif", "svg"):
            ext = export_ext_from_filter(sel, default="png")
        p = export_ensure_suffix(p, ext)
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
