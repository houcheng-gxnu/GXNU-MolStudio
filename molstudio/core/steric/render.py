# -*- coding: utf-8 -*-
# 配色与版式参考 StericRender（MIT）与 SambVca 2.1 官方出图脚本 plot_map.py。
# -----------------------------------------------------------------------------
# 来源说明 / Attribution
#   * 调色板 ``PALETTES['sambvca']``（11 个停靠色）、``steric_map_figure`` 的版式
#     （平滑 imshow + 黑色等高线 + 实线圆框 + 虚线十字 + 四象限标签 + 横向色标，
#     默认 ``color_range=(-R, +R)``）参考 StericRender：
#         stericrender/visual.py, stericrender/plot.py
#         Copyright (c) 2025 James O'Brien
#         https://github.com/JamesOBrien2/StericRender
#         MIT License — 见下；MIT 与 GPL-3.0-only 兼容。
#   * “固定 ±R 色阶 + 每阶黑色等高线”的官方观感参考 SambVca 2.1 的
#         sambvca_official/Sambvca21/plot_map.py（学术用途，仅参考思路）。
#
#   MIT License (StericRender):
#     Permission is hereby granted, free of charge, to any person obtaining a copy
#     of this software and associated documentation files (the "Software"), to deal
#     in the Software without restriction, including without limitation the rights
#     to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#     copies of the Software, and to permit persons to whom the Software is
#     furnished to do so, subject to the following conditions:
#     The above copyright notice and this permission notice shall be included in
#     all copies or substantial portions of the Software.
#     THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#     IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#     FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#     AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#     LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
#     FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
#     IN THE SOFTWARE.
# -----------------------------------------------------------------------------
# 本文件是 MolStudio 的自写实现：**运行时不再 import stericrender**，只复用其
# MIT 授权的配色表与版式算法；整体随 MolStudio 按 GPL-3.0-only 分发。
"""位阻地图出图（matplotlib）：对齐 StericRender / 官方 SambVca 的观感。

设计要点（用户抱怨“图和 StericRender 不像”的根因都在这里）：

1. **色标固定 ±R**（默认 ``(-result.map_radius, +result.map_radius)``），不是
   数据 min/max —— 官方 SambVca 与 StericRender 都这么做，用数据极值会把整张
   图拉满、颜色完全变样。
2. **圆形裁剪**：``sqrt(x²+y²) > map_radius`` 的格点掩成 NaN，NaN 处显白
   （不是灰底），与 StericRender 的圆盘观感一致。
3. **sambvca 11 停靠色**（StericRender 的 ``PALETTES['sambvca']``），而不是 jet。
4. 黑色等高线、实线黑圆框、虚线十字、NE/NW/SW/SE 四象限标签、横向色标。
5. 可选“结构在后方”的叠加：半透明地形色块覆盖在球棍分子上，而不是把
   元素点线画在地图前景；主画布可提供同一相机下的球棍快照，纯 matplotlib
   路径也有按深度排序的内置球棍背景。球心/z 轴/xz 标记与左下角轴指示保留，
   让“朝向”一眼可读。

公开接口::

    PALETTES / PALETTE_LABELS / MAP_STYLES / MAP_STYLE_LABELS
    colormap(palette)              -> matplotlib LinearSegmentedColormap
    bonds(symbols, positions, selected=None) -> [(i, j), ...]   # 0-based
    draw_map(fig, result, ...)     -> matplotlib.axes.Axes        # 2D 地图
    draw_terrain_3d(fig, result, ...) -> matplotlib.axes.Axes     # 3D 地形

模块只依赖 numpy + matplotlib（matplotlib 在函数内部惰性 import，便于纯计算
环境导入本模块）；**不 import stericrender / PyQt / OpenGL**。

``draw_map`` 会在返回的 Axes 上挂几个只读元数据属性，便于面板/测试复用：
``ax.steric_color_range``（实际色标范围）、``ax.steric_radius``、
``ax.steric_grid``（圆形裁剪后的 (x, y, z)）、``ax.steric_artist``（色标 mappable）。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

__all__ = [
    "PALETTES", "PALETTE_LABELS", "MAP_STYLES", "MAP_STYLE_LABELS",
    "ELEMENT_COLORS", "COVALENT_RADII",
    "DEFAULT_MAP_OPACITY", "colormap", "bonds", "draw_map", "draw_terrain_3d",
]

# ══════════════════════════════════════════════════════════════════
#  调色板（StericRender PALETTES，MIT；见文件头版权声明）
# ══════════════════════════════════════════════════════════════════
PALETTES: Dict[str, List[Tuple[int, int, int]]] = {
    # ── 官方/ StericRender 主用配色（11 停靠色）──
    "sambvca": [
        (49, 48, 124),
        (45, 83, 164),
        (63, 143, 194),
        (70, 196, 221),
        (120, 197, 157),
        (188, 220, 54),
        (254, 235, 39),
        (251, 166, 38),
        (239, 66, 45),
        (177, 31, 43),
        (94, 18, 27),
    ],
    "terrain": [
        (43, 95, 127),
        (84, 158, 179),
        (242, 228, 166),
        (215, 132, 72),
        (142, 52, 47),
    ],
    # ── 感知均匀配色 ──
    "viridis": [
        (68, 1, 84), (72, 35, 116), (64, 67, 135), (52, 94, 141), (41, 120, 142),
        (32, 144, 140), (34, 167, 132), (68, 190, 112), (121, 209, 81),
        (189, 222, 38), (253, 231, 37),
    ],
    "plasma": [
        (13, 8, 135), (75, 3, 158), (125, 3, 168), (168, 34, 150), (203, 71, 120),
        (229, 110, 87), (248, 149, 56), (254, 188, 34), (240, 227, 28),
        (238, 248, 33), (240, 249, 33),
    ],
    "inferno": [
        (0, 0, 4), (16, 11, 54), (55, 9, 99), (105, 6, 110), (155, 33, 97),
        (198, 69, 68), (230, 110, 37), (248, 154, 10), (253, 200, 48),
        (252, 243, 98), (252, 255, 164),
    ],
    "magma": [
        (0, 0, 4), (22, 11, 55), (67, 8, 100), (120, 11, 119), (172, 47, 107),
        (212, 82, 76), (237, 118, 46), (251, 157, 19), (252, 198, 45),
        (248, 241, 97), (252, 253, 191),
    ],
    "cividis": [
        (0, 32, 77), (11, 54, 93), (26, 75, 104), (45, 97, 108), (66, 118, 103),
        (89, 140, 90), (115, 162, 70), (148, 183, 44), (192, 204, 29),
        (234, 221, 28), (255, 234, 62),
    ],
    # ── 发散 / 科研常用 ──
    "coolwarm": [
        (59, 76, 192), (82, 110, 216), (117, 148, 229), (158, 182, 235),
        (199, 209, 233), (225, 220, 220), (233, 196, 189), (233, 154, 145),
        (222, 108, 104), (196, 62, 62), (158, 19, 25),
    ],
    "RdBu": [
        (33, 102, 172), (67, 147, 195), (146, 197, 222), (209, 229, 240),
        (247, 247, 247), (253, 219, 199), (244, 165, 130), (214, 96, 77),
        (178, 24, 43), (140, 0, 0),
    ],
    "Spectral": [
        (158, 1, 66), (213, 62, 79), (244, 109, 67), (253, 174, 97),
        (254, 224, 139), (255, 255, 191), (230, 245, 152), (171, 221, 164),
        (102, 194, 165), (50, 136, 189), (94, 79, 162),
    ],
    "RdYlBu": [
        (165, 0, 38), (215, 48, 39), (244, 109, 67), (253, 174, 97),
        (254, 224, 144), (255, 255, 191), (224, 243, 248), (171, 217, 233),
        (116, 173, 209), (69, 117, 180), (49, 54, 149),
    ],
    # ── 灰度 / 单色 ──
    "greys": [
        (0, 0, 0), (26, 26, 26), (51, 51, 51), (77, 77, 77), (102, 102, 102),
        (128, 128, 128), (153, 153, 153), (179, 179, 179), (204, 204, 204),
        (230, 230, 230), (255, 255, 255),
    ],
    "blues": [
        (247, 251, 255), (222, 235, 247), (198, 219, 239), (158, 202, 225),
        (107, 174, 214), (66, 146, 198), (33, 113, 181), (8, 81, 156),
        (8, 48, 107), (3, 19, 43),
    ],
    "reds": [
        (255, 245, 240), (254, 224, 210), (252, 187, 161), (252, 146, 114),
        (251, 106, 74), (239, 59, 44), (203, 24, 29), (165, 15, 21),
        (103, 0, 13), (43, 0, 0),
    ],
    "greens": [
        (247, 252, 245), (229, 245, 224), (199, 233, 192), (161, 217, 155),
        (116, 196, 118), (65, 171, 93), (35, 139, 69), (0, 109, 44),
        (0, 68, 27), (0, 27, 10),
    ],
    # ── turbo（jet 的感知线性替代）/ jet（经典彩虹，便于老用户对照）──
    "turbo": [
        (48, 18, 59), (50, 67, 205), (38, 114, 231), (23, 158, 221),
        (16, 198, 191), (33, 229, 148), (89, 247, 94), (165, 249, 44),
        (224, 231, 24), (250, 185, 12), (234, 109, 5), (188, 44, 13),
        (122, 4, 1),
    ],
    "jet": [
        (0, 0, 127), (0, 0, 255), (0, 127, 255), (0, 255, 255),
        (127, 255, 127), (255, 255, 0), (255, 127, 0), (255, 0, 0), (127, 0, 0),
    ],
    # ── 色盲友好（Scientific Colour Maps）──
    "batlow": [
        (8, 26, 87), (28, 46, 114), (49, 66, 137), (71, 87, 153), (93, 108, 164),
        (116, 130, 170), (139, 152, 171), (162, 173, 168), (185, 194, 163),
        (208, 215, 157), (232, 238, 153),
    ],
}

#: 配色显示名（zh, en）；面板下拉框可直接用。
PALETTE_LABELS: Dict[str, Tuple[str, str]] = {
    "sambvca": ("SambVca（StericRender 11 色）", "SambVca (StericRender 11-color)"),
    "terrain": ("地形", "Terrain"),
    "viridis": ("Viridis（感知均匀）", "Viridis (perceptually uniform)"),
    "plasma": ("Plasma（感知均匀）", "Plasma (perceptually uniform)"),
    "inferno": ("Inferno（感知均匀）", "Inferno (perceptually uniform)"),
    "magma": ("Magma（感知均匀）", "Magma (perceptually uniform)"),
    "cividis": ("Cividis（色盲友好）", "Cividis (colorblind-friendly)"),
    "coolwarm": ("冷暖发散", "Cool–warm diverging"),
    "RdBu": ("红蓝发散", "Red–blue diverging"),
    "Spectral": ("光谱发散", "Spectral diverging"),
    "RdYlBu": ("红黄蓝发散", "Red–yellow–blue diverging"),
    "greys": ("灰度", "Greyscale"),
    "blues": ("蓝色渐变", "Blues"),
    "reds": ("红色渐变", "Reds"),
    "greens": ("绿色渐变", "Greens"),
    "turbo": ("Turbo（jet 替代）", "Turbo (jet replacement)"),
    "jet": ("Jet（经典彩虹）", "Jet (classic rainbow)"),
    "batlow": ("Batlow（色盲友好）", "Batlow (colorblind-friendly)"),
}

#: 出图风格：``stericrender`` 平滑色块；``sambvca`` 官方离散色阶 + 每阶黑线。
MAP_STYLES: Tuple[str, ...] = ("stericrender", "sambvca")

#: 风格显示名（zh, en）。
MAP_STYLE_LABELS: Dict[str, Tuple[str, str]] = {
    "stericrender": ("StericRender（平滑连续）", "StericRender (smooth)"),
    "sambvca": ("SambVca 官方（离散色阶）", "SambVca official (banded)"),
}

DEFAULT_PALETTE = "sambvca"
DEFAULT_STYLE = "stericrender"
#: StericRender 叠图默认不透明度；低于 1 才能让后方球棍结构透出来。
DEFAULT_MAP_OPACITY = 0.72

# ══════════════════════════════════════════════════════════════════
#  元素配色 / 共价半径（自带的轻量表，不依赖外部化学库）
# ══════════════════════════════════════════════════════════════════
#: CPK 风格元素配色（2D 骨架用）。
ELEMENT_COLORS: Dict[str, str] = {
    "H": "#f2f2f2", "C": "#3d3d3d", "N": "#3050f8", "O": "#ff0d0d",
    "F": "#90e050", "P": "#ff8000", "S": "#d8c800", "Cl": "#1ff01f",
    "Br": "#a62929", "I": "#940094", "B": "#ffb5b5", "Si": "#c8a078",
    "Se": "#ffa100", "Te": "#d47a00", "As": "#bd80e3", "Li": "#cc80ff",
    "Na": "#ab5cf2", "K": "#8f40d4", "Mg": "#8aff00", "Ca": "#3dff00",
    "Al": "#bfa6a6", "Fe": "#e06633", "Co": "#f090a0", "Ni": "#50d050",
    "Cu": "#c88033", "Zn": "#7d80b0", "Mn": "#9c7ac7", "Cr": "#8a99c7",
    "V": "#a6a6ab", "Ti": "#bfc2c7", "Sc": "#e6e6e6", "Ga": "#c28f8f",
    "Ge": "#668f8f", "Sn": "#668080", "Pb": "#575961", "Sb": "#9e63b5",
    "Ru": "#248f8f", "Rh": "#0a7d8c", "Pd": "#006985", "Ag": "#c0c0c0",
    "Cd": "#ffd98f", "Os": "#266696", "Ir": "#175487", "Pt": "#c8c8e0",
    "Au": "#ffd123", "Hg": "#b8b8d0", "Mo": "#54b5b5", "W": "#2194d6",
    "Re": "#267dab", "Ta": "#4da6ff", "Nb": "#73c2c9", "Zr": "#94e0e0",
}

#: 常见元素共价半径（Å，Cordero 2008 量级）；未收录元素用 0.76 Å 兜底。
COVALENT_RADII: Dict[str, float] = {
    "H": 0.31, "He": 0.28, "Li": 1.28, "Be": 0.96, "B": 0.84, "C": 0.76,
    "N": 0.71, "O": 0.66, "F": 0.57, "Ne": 0.58, "Na": 1.66, "Mg": 1.41,
    "Al": 1.21, "Si": 1.11, "P": 1.07, "S": 1.05, "Cl": 1.02, "Ar": 1.06,
    "K": 2.03, "Ca": 1.76, "Sc": 1.70, "Ti": 1.60, "V": 1.53, "Cr": 1.39,
    "Mn": 1.39, "Fe": 1.32, "Co": 1.26, "Ni": 1.24, "Cu": 1.32, "Zn": 1.22,
    "Ga": 1.22, "Ge": 1.20, "As": 1.19, "Se": 1.20, "Br": 1.20, "Kr": 1.16,
    "Rb": 2.20, "Sr": 1.95, "Y": 1.90, "Zr": 1.75, "Nb": 1.64, "Mo": 1.54,
    "Tc": 1.47, "Ru": 1.46, "Rh": 1.42, "Pd": 1.39, "Ag": 1.45, "Cd": 1.44,
    "In": 1.42, "Sn": 1.39, "Sb": 1.39, "Te": 1.38, "I": 1.39, "Xe": 1.40,
    "Cs": 2.44, "Ba": 2.15, "La": 2.07, "Ce": 2.04, "Nd": 2.01, "Hf": 1.75,
    "Ta": 1.70, "W": 1.62, "Re": 1.51, "Os": 1.44, "Ir": 1.41, "Pt": 1.36,
    "Au": 1.36, "Hg": 1.32, "Tl": 1.45, "Pb": 1.46, "Bi": 1.48,
}

_DEFAULT_COVALENT_RADIUS = 0.76
_DEFAULT_ELEMENT_COLOR = "#9aa4b2"

# 骨架/标记线条颜色（深灰，与 StericRender 的深色骨架一致，但比等高线更深）
_SKELETON_BOND_COLOR = "#4a4a4a"
_FRAME_COLOR = "#1a1a1a"
_CROSS_COLOR = "#1a1a1a"
_CONTOUR_COLOR = "#333333"
_QUADRANT_COLOR = "#333333"
_TRIAD_COLOR = "#1f2937"
_NAN_COLOR = "#ffffff"


# ══════════════════════════════════════════════════════════════════
#  小工具
# ══════════════════════════════════════════════════════════════════
def _mpl():
    """惰性 import matplotlib（模块导入本文件时不需要 matplotlib）。"""
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.patches import Circle
    return LinearSegmentedColormap, Circle


def _resolve_palette(palette: Any) -> str:
    """大小写不敏感地解析调色板名（返回 ``PALETTES`` 的键）。"""
    name = str(palette or DEFAULT_PALETTE).strip()
    if name in PALETTES:
        return name
    low = name.lower()
    for key in PALETTES:
        if key.lower() == low:
            return key
    raise KeyError(
        f"未知调色板: {palette!r}（可选: {', '.join(PALETTES)}）")


def colormap(palette: str = DEFAULT_PALETTE):
    """按 ``PALETTES`` 建 256 级 ``LinearSegmentedColormap``。

    ``palette`` 不在内置表里时，回退到 matplotlib 自带的同名 colormap（方便面板
    沿用旧的 mpl 配色名）；两者都没有则抛 ``KeyError``。
    """
    LinearSegmentedColormap, _Circle = _mpl()
    try:
        name = _resolve_palette(palette)
    except KeyError:
        from matplotlib import colormaps
        raw = str(palette or "").strip()
        if raw in colormaps:
            cmap = colormaps[raw].copy()
            cmap.name = f"molstudio_{raw}"
            return cmap
        raise
    stops = np.asarray(PALETTES[name], dtype=float) / 255.0
    cmap = LinearSegmentedColormap.from_list(f"molstudio_{name}", stops, N=256)
    return cmap


def _symbol(sym: Any) -> str:
    return str(sym).strip().capitalize()


def _element_color(sym: Any) -> str:
    s = _symbol(sym)
    return ELEMENT_COLORS.get(s, _DEFAULT_ELEMENT_COLOR)


def _grid_arrays(result) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """取 ``result.map`` 的 (x, y, z)，并兼容 z 被转置存放的情况。"""
    grid = getattr(result, "map", None)
    if grid is None:
        raise ValueError("result 缺少位阻地图（map）")
    x = np.asarray(getattr(grid, "x", []), dtype=float).ravel()
    y = np.asarray(getattr(grid, "y", []), dtype=float).ravel()
    z = np.asarray(getattr(grid, "z", []), dtype=float)
    if x.size == 0 or y.size == 0 or z.ndim != 2:
        raise ValueError("位阻地图网格为空或维度非法")
    if z.shape != (y.size, x.size) and z.shape == (x.size, y.size):
        z = z.T
    if z.shape != (y.size, x.size):
        raise ValueError(f"map.z 形状 {z.shape} 与网格 ({y.size}, {x.size}) 不符")
    return x, y, z


def _map_radius(result, x: np.ndarray, y: np.ndarray) -> float:
    """地图半径（Å）：优先 ``result.map_radius``，否则按网格范围推断。"""
    try:
        radius = float(getattr(result, "map_radius", 0.0) or 0.0)
    except (TypeError, ValueError):
        radius = 0.0
    if not math.isfinite(radius) or radius <= 0.0:
        radius = float(max(np.max(np.abs(x)), np.max(np.abs(y))))
    if not math.isfinite(radius) or radius <= 0.0:
        radius = 1.0
    return radius


def _color_limits(result, color_range, radius: float) -> Tuple[float, float]:
    """色标范围：默认 **固定 ±R**（官方/ StericRender 的默认），不用数据 min/max。"""
    vmin: Optional[float] = None
    vmax: Optional[float] = None
    if color_range is not None:
        try:
            vmin, vmax = float(color_range[0]), float(color_range[1])
        except (TypeError, ValueError, IndexError):
            vmin = vmax = None
    if vmin is None or vmax is None:
        vmin, vmax = -radius, radius
    if not (math.isfinite(vmin) and math.isfinite(vmax)):
        vmin, vmax = -radius, radius
    if vmax <= vmin:
        vmax = vmin + 1e-6
    return float(vmin), float(vmax)


def _circle_clip(x: np.ndarray, y: np.ndarray, z: np.ndarray,
                 radius: float) -> np.ndarray:
    """把圆外格点与非有限值掩成 NaN（严格“圆外显白”）。"""
    zz = np.array(z, dtype=float, copy=True)
    zz[~np.isfinite(zz)] = np.nan
    if x.size and y.size:
        xx = x[np.newaxis, :]
        yy = y[:, np.newaxis]
        outside = (xx * xx + yy * yy) > (float(radius) ** 2 + 1e-9)
        zz[outside] = np.nan
    return zz


def _extent(x: np.ndarray, y: np.ndarray) -> Tuple[float, float, float, float]:
    """imshow 的 extent（格点按格心处理，向外扩半格）。"""
    dx = float(x[1] - x[0]) if x.size > 1 else 0.1
    dy = float(y[1] - y[0]) if y.size > 1 else 0.1
    return (float(x[0]) - dx / 2.0, float(x[-1]) + dx / 2.0,
            float(y[0]) - dy / 2.0, float(y[-1]) + dy / 2.0)


# ══════════════════════════════════════════════════════════════════
#  成键判定（2D 骨架用）
# ══════════════════════════════════════════════════════════════════
def bonds(symbols: Sequence[str], positions, selected=None,
          *, tolerance: float = 1.25) -> List[Tuple[int, int]]:
    """按共价半径判据给出键表，返回 0-based 的 ``[(i, j), ...]``（i < j）。

    参数
    ----
    symbols : 元素符号序列（长度 n）。
    positions : (n, 3) 坐标（Å）——通常传 ``result.oriented_positions``。
    selected : 只在这些 **0-based** 原子序号之间成键；``None`` = 全部原子。
    tolerance : 判据系数，``d < (r_i + r_j) * tolerance`` 视为成键（默认 1.25）。

    说明：只用距离 + 共价半径，不做价键/键级判断；目的只是给位阻地图叠一层
    轻量骨架，不用于任何数值计算。坐标必须与 ``symbols`` 同序。
    """
    syms = [_symbol(s) for s in symbols]
    P = np.asarray(positions, dtype=float)
    n = len(syms)
    if n == 0 or P.ndim != 2 or P.shape[1] != 3 or P.shape[0] != n:
        return []
    if selected is None:
        idx = np.arange(n, dtype=int)
    else:
        keep = []
        for item in selected:
            try:
                i = int(item)
            except (TypeError, ValueError):
                continue
            if 0 <= i < n:
                keep.append(i)
        idx = np.unique(np.asarray(keep, dtype=int)) if keep else np.empty(0, int)
    if idx.size < 2:
        return []
    radii = np.asarray(
        [COVALENT_RADII.get(syms[int(i)], _DEFAULT_COVALENT_RADIUS) for i in idx],
        dtype=float)
    coeff = float(tolerance)
    out: List[Tuple[int, int]] = []
    for a in range(idx.size - 1):
        i = int(idx[a])
        delta = P[idx[a + 1:]] - P[i]
        dist = np.linalg.norm(delta, axis=1)
        cut = (radii[a] + radii[a + 1:]) * coeff
        hits = np.nonzero((dist > 1e-6) & (dist <= cut))[0]
        for b in hits:
            j = int(idx[a + 1 + int(b)])
            out.append((min(i, j), max(i, j)))
    return out


# ══════════════════════════════════════════════════════════════════
#  叠加层：骨架、四象限、轴指示
# ══════════════════════════════════════════════════════════════════
def _selected_indices(result) -> Optional[np.ndarray]:
    """``result.selected_atoms``（1-based）→ 0-based；为空表示“全部原子”。"""
    raw = getattr(result, "selected_atoms", None) or []
    out: List[int] = []
    for item in raw:
        try:
            out.append(int(item) - 1)
        except (TypeError, ValueError):
            continue
    n = len(getattr(result, "symbols", None) or [])
    out = [i for i in out if 0 <= i < n]
    if not out:
        return None
    return np.asarray(sorted(set(out)), dtype=int)


def _draw_ring_marker(ax, px: float, py: float, radius: float, label: str,
                      *, color: str = "#111827", fontsize: float = 6.5,
                      with_cross: bool = False) -> None:
    """圆内标记：⊕（球心）/ 带 z 的圈 / 带 xz 的圈（数据坐标，随 R 缩放）。"""
    from matplotlib.patches import Circle

    ring_r = radius * (0.055 if len(label) <= 1 else 0.075)
    ax.add_patch(Circle((px, py), ring_r, fill=False, edgecolor=color,
                        linewidth=1.15, zorder=9, clip_on=True))
    if with_cross:
        d = ring_r * 0.72
        ax.plot([px - d, px + d], [py, py], color=color, lw=1.0, zorder=9,
                solid_capstyle="butt", clip_on=True)
        ax.plot([px, px], [py - d, py + d], color=color, lw=1.0, zorder=9,
                solid_capstyle="butt", clip_on=True)
    if label:
        ax.text(px, py, label, ha="center", va="center", fontsize=fontsize,
                fontweight="bold", color=color, zorder=10, clip_on=True)


def _draw_role_markers(ax, result, radius: float) -> None:
    """在叠加层顶部标出球心 / z 轴原子，便于核对方向。"""
    positions = getattr(result, "oriented_positions", None)
    symbols = list(getattr(result, "symbols", None) or [])
    if positions is None or not symbols:
        return
    P = np.asarray(positions, dtype=float)
    if P.ndim != 2 or P.shape[1] != 3 or P.shape[0] != len(symbols):
        return
    job = getattr(result, "job", None) or {}
    limit = radius + 1e-9
    # The xz-plane atoms are an orientation input, not a useful visual label:
    # printing "xz" on the map adds clutter and obscures the actual surface.
    role_sizes = (("centre_atoms", "", True, 7.5),
                  ("z_axis_atoms", "z", False, 7.0))
    for key, label, with_cross, fontsize in role_sizes:
        for idx in job.get(key) or []:
            try:
                i = int(idx) - 1
            except (TypeError, ValueError):
                continue
            if not (0 <= i < len(symbols)):
                continue
            px, py = float(P[i, 0]), float(P[i, 1])
            if math.hypot(px, py) > limit:
                continue
            _draw_ring_marker(ax, px, py, radius, label, fontsize=fontsize,
                              with_cross=with_cross)


def _draw_skeleton(ax, result, radius: float, *, lang: str = "zh",
                   clip_to_sphere: bool = True) -> int:
    """在图层底部画伪三维球棍结构；返回画出的原子数。

    地图由调用方以半透明层盖在其上。``clip_to_sphere=False`` 对齐
    StericRender 的整分子显示模式：保留圆盘外的配体并扩大绘图范围。
    原子和键按定向坐标的屏幕深度（z）从远到近绘制；元素色、暗描边和高光让结构与 StericRender 的后方球棍
    观感一致，同时仍只用 matplotlib，不引入 xyzrender 依赖。
    """
    positions = getattr(result, "oriented_positions", None)
    symbols = list(getattr(result, "symbols", None) or [])
    if positions is None or not symbols:
        return 0
    P = np.asarray(positions, dtype=float)
    if P.ndim != 2 or P.shape[1] != 3 or P.shape[0] != len(symbols):
        return 0

    sel = _selected_indices(result)
    if sel is None:
        sel = np.arange(len(symbols), dtype=int)
    if sel.size == 0:
        return 0

    # 默认只画在圆盘内（StericRender 的 disk clip）。整分子模式不裁切，
    # 由调用方扩大坐标轴范围。
    clip_patch = None
    try:
        from matplotlib.patches import Circle as _MplCircle
        if clip_to_sphere and radius > 0:
            clip_patch = _MplCircle((0.0, 0.0), float(radius),
                                    transform=ax.transData)
    except Exception:                                              # noqa: BLE001
        clip_patch = None

    def _clip(artist):
        if clip_patch is not None:
            try:
                artist.set_clip_path(clip_patch)
            except Exception:                                      # noqa: BLE001
                pass
        return artist

    # ① 键：暗描边 + 元素色内芯，从后往前画。做成半键而不是一整条，
    #    两端可以分别带原子配色，观感更接近球棍模型。
    from matplotlib.colors import to_rgba

    bond_list = bonds(symbols, P, sel)
    bond_items = []
    for i, j in bond_list:
        depth = 0.5 * (float(P[i, 2]) + float(P[j, 2]))
        bond_items.append((depth, i, j))
    for _depth, i, j in sorted(bond_items, key=lambda row: row[0]):
        mid = 0.5 * (P[i, :2] + P[j, :2])
        width = 6.0 + 0.8 * min(radius, 4.0)
        for a, b in ((i, j), (j, i)):
            end = mid
            outline, = ax.plot(
                [P[a, 0], end[0]], [P[a, 1], end[1]],
                color="#2b2b31", lw=width, solid_capstyle="round",
                zorder=0.21, clip_on=True, alpha=0.92)
            _clip(outline)
            inner_rgb = to_rgba(_element_color(symbols[int(a)]))
            inner = tuple(0.66 * c + 0.34 for c in inner_rgb[:3])
            fill, = ax.plot(
                [P[a, 0], end[0]], [P[a, 1], end[1]],
                color=inner, lw=max(1.2, width - 3.1),
                solid_capstyle="round", zorder=0.22, clip_on=True)
            _clip(fill)

    # ② 原子：从远到近排序；球径只轻微随深度变化（正交投影），
    #    暗描边 + 偏左上的高光叠出立体感。
    depths = P[sel, 2]
    order = np.argsort(depths, kind="stable")
    colors = [_element_color(symbols[int(i)]) for i in sel]
    for pos in order:
        i = int(sel[int(pos)])
        sym = _symbol(symbols[i])
        r_cov = COVALENT_RADII.get(sym, _DEFAULT_COVALENT_RADIUS)
        size = 205.0 * (r_cov / 0.76) ** 2
        size = max(58.0, min(size, 390.0))
        base = ax.scatter(
            [P[i, 0]], [P[i, 1]], s=size * 1.18, c=["#282830"],
            edgecolors="none", zorder=0.29, clip_on=True)
        _clip(base)
        sphere = ax.scatter(
            [P[i, 0]], [P[i, 1]], s=size, c=[colors[int(pos)]],
            edgecolors="#3b3b44", linewidths=max(0.35, size ** 0.5 / 30.0),
            zorder=0.30, clip_on=True)
        _clip(sphere)
        dx = 0.035 * radius * (0.35 + min(r_cov, 1.2) / 1.6)
        highlight = ax.scatter(
            [P[i, 0] - dx], [P[i, 1] + dx], s=max(5.0, size * 0.10),
            c=["#ffffff"], edgecolors="none", alpha=0.62,
            zorder=0.31, clip_on=True)
        _clip(highlight)

    # ③ 角色标记：球心 ⊕、z 轴圈（存在且在圆内时）
    _draw_role_markers(ax, result, radius)
    return int(sel.size)


def _draw_quadrants(ax, radius: float) -> None:
    """虚线十字 + 四角的 NE/NW/SW/SE 标签（StericRender 版式）。

    标签放在圆外的边角空白处（±0.84R）；左下角再往里收一点，给轴指示留位置。
    """
    ax.axhline(0.0, color=_CROSS_COLOR, lw=0.8, ls=(0, (5, 4)), zorder=2)
    ax.axvline(0.0, color=_CROSS_COLOR, lw=0.8, ls=(0, (5, 4)), zorder=2)
    pad = radius * 0.16
    kw = dict(fontsize=10, fontweight="bold", color=_QUADRANT_COLOR,
              ha="center", va="center", zorder=5)
    ax.text(radius - pad, radius - pad, "NE", **kw)
    ax.text(-radius + pad, radius - pad, "NW", **kw)
    ax.text(-radius + pad, -radius + pad, "SW", **kw)
    ax.text(radius - pad, -radius + pad, "SE", **kw)


def _draw_axes_triad(ax) -> None:
    """左下角 +x/+y 箭头与 +z（⊙ 指向观察者）小指示，让朝向一眼可读。

    画在坐标轴左下角（圆盘外的空白角落，避开 SW 象限标签）。
    """
    color = _TRIAD_COLOR
    ox, oy = 0.030, 0.030
    ax_len = 0.058
    arrow = dict(arrowstyle="->", color=color, lw=1.0, shrinkA=0, shrinkB=0)
    ax.annotate("", xy=(ox + ax_len, oy), xytext=(ox, oy),
                xycoords="axes fraction", arrowprops=arrow, zorder=12)
    ax.text(ox + ax_len + 0.008, oy, "x", transform=ax.transAxes, fontsize=8,
            color=color, va="center", ha="left", zorder=12)
    ax.annotate("", xy=(ox, oy + ax_len), xytext=(ox, oy),
                xycoords="axes fraction", arrowprops=arrow, zorder=12)
    ax.text(ox, oy + ax_len + 0.008, "y", transform=ax.transAxes, fontsize=8,
            color=color, va="bottom", ha="center", zorder=12)
    # +z 指向观察者（出屏）→ ⊙
    ax.plot([ox], [oy], transform=ax.transAxes, marker="o", markersize=7.0,
            markerfacecolor="none", markeredgecolor=color, markeredgewidth=0.9,
            linestyle="none", zorder=12, clip_on=False)
    ax.plot([ox], [oy], transform=ax.transAxes, marker=".",
            markersize=3.0, color=color, linestyle="none", zorder=12,
            clip_on=False)
    ax.text(ox - 0.010, oy, "z", transform=ax.transAxes, fontsize=8,
            color=color, va="center", ha="right", zorder=12)


def _draw_circle_frame(ax, radius: float) -> None:
    """实线黑圆框（StericRender 的圆盘边界）。"""
    from matplotlib.patches import Circle
    ax.add_patch(Circle((0.0, 0.0), radius, fill=False, edgecolor=_FRAME_COLOR,
                        linewidth=1.7, zorder=5))


def _finish_axes(ax, radius: float, title: Optional[str],
                 *, view_radius: Optional[float] = None) -> None:
    """坐标轴：等比例；整分子模式可扩大到分子边界。"""
    lim = float(view_radius if view_radius is not None else radius) * 1.06
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_aspect("equal")
    ax.set_xlabel("x (Å)", fontsize=9)
    ax.set_ylabel("y (Å)", fontsize=9)
    ax.tick_params(labelsize=8)
    if title:
        ax.set_title(str(title), fontsize=10, fontweight="bold", loc="left",
                     color="#1f2937", pad=6)


def _add_colorbar(fig, mappable, ax):
    """横向色标条（StericRender 版式：fraction≈0.05, pad≈0.10）。"""
    cbar = fig.colorbar(mappable, ax=ax, orientation="horizontal",
                        fraction=0.05, pad=0.10)
    cbar.set_label("z (Å)", fontsize=9)
    cbar.ax.tick_params(labelsize=8)
    return cbar


def _molecule_view_radius(result, radius: float, clip_to_sphere: bool) -> float:
    """Return the symmetric x/y plotting radius needed for the chosen mode."""
    if clip_to_sphere:
        return float(radius)
    positions = getattr(result, "oriented_positions", None)
    if positions is None:
        return float(radius)
    try:
        P = np.asarray(positions, dtype=float)
        if P.ndim != 2 or P.shape[1] != 3 or not P.size:
            return float(radius)
        symbols = list(getattr(result, "symbols", None) or [])
        selected = _selected_indices(result)
        if selected is None:
            selected = np.arange(min(P.shape[0], len(symbols)), dtype=int)
        selected = selected[(selected >= 0) & (selected < P.shape[0])]
        if selected.size == 0:
            return float(radius)
        xy = P[selected, :2]
        finite = np.isfinite(xy)
        if not finite.any():
            return float(radius)
        extent = float(np.nanmax(np.abs(xy[finite])))
        atom_pad = 0.45
        if symbols:
            atom_pad = max(
                0.45,
                max(COVALENT_RADII.get(_symbol(symbols[int(i)]),
                                       _DEFAULT_COVALENT_RADIUS)
                    for i in selected) * 1.25)
        return max(float(radius), extent + atom_pad)
    except Exception:                                      # noqa: BLE001
        return float(radius)


# ══════════════════════════════════════════════════════════════════
#  2D 位阻地图
# ══════════════════════════════════════════════════════════════════
def draw_map(fig, result, *, palette: str = DEFAULT_PALETTE,
             style: str = DEFAULT_STYLE, color_range=None,
             show_contours: bool = True, contour_levels: int = 15,
             show_skeleton: bool = True, clip_skeleton: bool = True,
             show_quadrants: bool = True,
             show_colorbar: bool = True, show_axes_triad: bool = True,
             map_opacity: float = DEFAULT_MAP_OPACITY,
             background_image=None, background_extent=None,
             lang: str = "zh", title: Optional[str] = None):
    """在给定 ``Figure`` 上重画 2D 位阻地图（先 ``fig.clear()``），返回主 Axes。

    参数
    ----
    fig : matplotlib Figure（面板的 Qt 画布 figure，或 ``plt.figure()``）。
    result : :class:`~molstudio.core.steric.engine.StericResult`
        只用 ``result.map`` / ``map_radius`` / ``oriented_positions`` /
        ``symbols`` / ``selected_atoms`` / ``job``，不修改 result。
    palette : ``PALETTES`` 的键（默认 ``"sambvca"``，StericRender 11 色）。
    style : ``"stericrender"``（平滑 imshow）或 ``"sambvca"``（离散 contourf，
        ±R 内每 0.2 Å 一档 + 每档黑线，同官方
        ``plot_map.py $JOB-TopSurface.dat 0.2``）。未知值按 ``"stericrender"`` 处理。
    color_range : ``(vmin, vmax)``；``None``（默认）= **固定 ±map_radius**，
        与官方 SambVca / StericRender 一致（不是数据 min/max）。
    show_contours : 叠加黑色等高线（``style="sambvca"`` 时是每阶黑线开关）。
    contour_levels : 等高线条数（``style="stericrender"`` 默认 15）。
    show_skeleton : 在地图**后方**画球棍分子（含球心/z 轴标记）。
    clip_skeleton : ``True``（默认）把分子裁切到地图圆盘内，对齐 StericRender
        的球内视图；``False`` 保留完整分子并自动扩大绘图范围。只影响显示。
    map_opacity : 地形色块不透明度，默认 0.72（StericRender 叠层观感）。
    background_image : 可选 ``(H,W,3/4)`` RGB(A) 快照。主界面会传入与地图
        同一相机下的画布快照，从而保留用户当前渲染风格；``None`` 时使用本
        模块的轻量球棍背景。快照只作为显示层，不参与任何数值计算。
    background_extent : 快照对应的 ``(x0,x1,y0,y1)`` 数据范围；``None`` 时
        自动覆盖地图坐标轴。传入快照时建议显式给出。
    show_quadrants : 虚线十字 + NE/NW/SW/SE 标签。
    show_colorbar : 横向色标条（label ``z (Å)``）。
    show_axes_triad : 左下角 +x/+y/+z 轴指示。
    lang : ``"zh"`` / ``"en"``（本模块内轴标签为中英通用符号，保留参数以统一接口）。
    title : 非空时画在图的左上/顶部。

    返回
    ----
    matplotlib.axes.Axes
        并附带 ``steric_color_range`` / ``steric_radius`` / ``steric_grid`` /
        ``steric_artist`` 只读属性（色标范围、半径、裁剪后的网格、色标 mappable）。
    """
    style_name = str(style or DEFAULT_STYLE).strip().lower()
    if style_name not in MAP_STYLES:
        style_name = DEFAULT_STYLE

    x, y, z = _grid_arrays(result)
    radius = _map_radius(result, x, y)
    vmin, vmax = _color_limits(result, color_range, radius)
    zz = _circle_clip(x, y, z, radius)
    zm = np.ma.masked_invalid(zz)
    try:
        opacity = float(map_opacity)
    except (TypeError, ValueError):
        opacity = DEFAULT_MAP_OPACITY
    opacity = max(0.05, min(1.0, opacity))

    cmap = colormap(palette)
    # RGB 仍是白色；alpha=0 让无表面区域透出后方球棍结构。
    cmap.set_bad((1.0, 1.0, 1.0, 0.0))

    fig.clear()
    ax = fig.add_subplot(111)
    ax.set_aspect("equal")
    ax.set_facecolor(_NAN_COLOR)
    try:
        fig.patch.set_facecolor("#ffffff")
    except Exception:                              # noqa: BLE001 - 极端后端兼容
        pass

    view_radius = _molecule_view_radius(result, radius, bool(clip_skeleton))
    lim = view_radius * 1.06
    bg_artist = None
    if show_skeleton and clip_skeleton and background_image is not None:
        try:
            from matplotlib.patches import Circle
            bg_arr = np.asarray(background_image)
            if bg_arr.ndim == 3 and bg_arr.shape[2] in (3, 4) and bg_arr.size:
                ext = background_extent or (-lim, lim, -lim, lim)
                bg_artist = ax.imshow(
                    bg_arr, origin="upper", extent=ext,
                    interpolation="bilinear", zorder=0.10,
                    clip_on=True, aspect="equal")
                bg_artist.set_clip_path(Circle((0.0, 0.0), radius,
                                               transform=ax.transData))
        except Exception:                              # noqa: BLE001
            bg_artist = None
    if show_skeleton and bg_artist is None:
        _draw_skeleton(ax, result, radius, lang=lang,
                       clip_to_sphere=bool(clip_skeleton))

    # 没有后方结构时不把地图冲淡；有结构时按用户设置使用半透明层。
    map_alpha = opacity if show_skeleton else 1.0
    mappable = None
    if style_name == "sambvca":
        # 官方 SambVca 观感：固定 ±R 的离散色阶，间距 0.2 Å
        # （= 官方 Examples/runall 里的 `plot_map.py $JOB-TopSurface.dat 0.2`），
        # 每阶一条黑色**实线**等高线；colorbar 由 matplotlib 自动抽稀刻度
        # （官方 nhc-TopSurface.png 就是这种 ~9 个标签的样子）。
        step = 0.2
        n_bands = (vmax - vmin) / step if step > 0 else 0.0
        if not (6.0 <= n_bands <= 80.0):
            # 半径特别大/特别小时退化为 36 阶，保持官方量级的密度
            step = max(abs(vmax - vmin), 1e-9) / 36.0
        levels = np.arange(vmin, vmax + step * 1e-6, step)
        if levels.size < 2:
            levels = np.linspace(vmin, vmax, 36)
        else:
            levels = np.clip(levels, vmin, vmax)
            if levels[-1] < vmax - 1e-9:
                levels = np.append(levels, vmax)
        mappable = ax.contourf(x, y, zm, levels=levels, cmap=cmap,
                               vmin=vmin, vmax=vmax, alpha=map_alpha, zorder=1)
        if show_contours:
            ax.contour(x, y, zm, levels=levels, colors="k", linewidths=0.8,
                       linestyles="solid", alpha=min(1.0, opacity + 0.18),
                       zorder=3)
    else:
        # StericRender 观感：平滑 imshow + 黑色实线等高线
        mappable = ax.imshow(zm, origin="lower", extent=_extent(x, y),
                             cmap=cmap, vmin=vmin, vmax=vmax,
                             interpolation="bilinear", alpha=map_alpha, zorder=1)
        if show_contours:
            n = max(int(contour_levels or 0), 2)
            levels = np.linspace(vmin, vmax, n + 2)[1:-1]
            ax.contour(x, y, zm, levels=levels, colors=_CONTOUR_COLOR,
                       linewidths=0.6, linestyles="solid",
                       alpha=min(1.0, opacity + 0.18), zorder=3)

    _draw_circle_frame(ax, radius)
    if show_quadrants:
        _draw_quadrants(ax, radius)
    if show_skeleton and bg_artist is not None:
        _draw_role_markers(ax, result, radius)
    if show_axes_triad:
        _draw_axes_triad(ax)
    if show_colorbar and mappable is not None:
        _add_colorbar(fig, mappable, ax)
    _finish_axes(ax, radius, title, view_radius=view_radius)

    # 只读元数据（面板/测试复用；不改原始 result）
    ax.steric_color_range = (float(vmin), float(vmax))
    ax.steric_radius = float(radius)
    ax.steric_grid = (np.array(x, copy=True), np.array(y, copy=True),
                      np.array(zz, copy=True))
    ax.steric_artist = mappable
    ax.steric_style = style_name
    ax.steric_map_opacity = float(map_alpha)
    ax.steric_molecule_clip = bool(clip_skeleton)
    ax.steric_view_radius = float(view_radius)
    ax.steric_background_artist = bg_artist
    try:
        ax.steric_palette = _resolve_palette(palette)
    except KeyError:
        ax.steric_palette = str(palette)
    return ax


# ══════════════════════════════════════════════════════════════════
#  3D 地形
# ══════════════════════════════════════════════════════════════════
def draw_terrain_3d(fig, result, *, palette: str = DEFAULT_PALETTE,
                    color_range=None, show_contours: bool = False,
                    lang: str = "zh", title: Optional[str] = None):
    """在给定 ``Figure`` 上画 3D 位阻地形（``plot_surface``），返回 3D Axes。

    配色、色标范围（默认固定 ±R）与 2D 完全一致；``show_contours=True`` 时
    在底部投影等高线，便于看“地形起伏”。视角 elev≈32°、azim≈-58°。
    """
    x, y, z = _grid_arrays(result)
    radius = _map_radius(result, x, y)
    vmin, vmax = _color_limits(result, color_range, radius)
    zz = _circle_clip(x, y, z, radius)

    finite = zz[np.isfinite(zz)]
    if finite.size:
        zlo, zhi = float(finite.min()), float(finite.max())
    else:
        zlo, zhi = -radius, 0.0
    span = zhi - zlo
    pad = 0.06 * span if span > 1e-9 else 0.1

    cmap = colormap(palette)
    cmap.set_bad(_NAN_COLOR)

    fig.clear()
    ax = fig.add_subplot(111, projection="3d")
    X, Y = np.meshgrid(x, y)
    surf = ax.plot_surface(X, Y, zz, cmap=cmap, vmin=vmin, vmax=vmax,
                           linewidth=0, antialiased=False, rstride=1,
                           cstride=1)
    if show_contours:
        try:
            ax.contour(X, Y, zz, levels=np.linspace(vmin, vmax, 17),
                       zdir="z", offset=zlo - pad, colors=_CONTOUR_COLOR,
                       linewidths=0.45)
        except Exception:                          # noqa: BLE001 - 3D 等高线非关键
            pass

    ax.set_xlim(-radius, radius)
    ax.set_ylim(-radius, radius)
    ax.set_zlim(zlo - pad, zhi + pad)
    ax.set_xlabel("x (Å)", fontsize=9, labelpad=6)
    ax.set_ylabel("y (Å)", fontsize=9, labelpad=6)
    ax.set_zlabel("z (Å)", fontsize=9, labelpad=6)
    ax.tick_params(labelsize=7)
    ax.view_init(elev=32, azim=-58)
    try:
        ax.set_box_aspect((1.0, 1.0, 0.55))
    except Exception:                              # noqa: BLE001
        pass
    cbar = fig.colorbar(surf, ax=ax, orientation="horizontal",
                        fraction=0.05, pad=0.10)
    cbar.set_label("z (Å)", fontsize=9)
    cbar.ax.tick_params(labelsize=8)
    if title:
        ax.set_title(str(title), fontsize=10, fontweight="bold",
                     color="#1f2937", pad=4)

    ax.steric_color_range = (float(vmin), float(vmax))
    ax.steric_radius = float(radius)
    ax.steric_grid = (np.array(x, copy=True), np.array(y, copy=True),
                      np.array(zz, copy=True))
    ax.steric_artist = surf
    return ax
