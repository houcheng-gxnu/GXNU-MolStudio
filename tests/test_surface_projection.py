# -*- coding: utf-8 -*-
"""表面距离投影图的绘图：双三次插值 + 轮廓外留白不能画崩。"""

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from molstudio.core import surface_projection as sp


def _grid(n=40):
    xs = np.linspace(-3.0, 3.0, n)
    ys = np.linspace(-2.0, 2.0, n)
    xg, yg = np.meshgrid(xs, ys, indexing="ij")
    v = -(xg ** 2 + yg ** 2)            # 平滑的 <=0 场，模拟 distmap
    v[0, 0] = v.min()                   # 一个"扫到底"的点，触发 void 掩码
    return xs, ys, v


def test_draw_map_bicubic_with_void(tmp_path):
    xs, ys, v = _grid()
    fig = Figure(figsize=(4.0, 3.0), dpi=80)
    FigureCanvasAgg(fig)
    n_void, v_lo = sp.draw_map(fig, xs, ys, v, void="bg",
                               floor=float(v.min()))
    assert v_lo < 0
    assert n_void >= 1
    out = tmp_path / "map.png"
    fig.savefig(out, dpi=100)
    assert out.stat().st_size > 1000


def test_draw_map_color_mode(tmp_path):
    xs, ys, v = _grid()
    fig = Figure(figsize=(4.0, 3.0), dpi=80)
    FigureCanvasAgg(fig)
    n_void, v_lo = sp.draw_map(fig, xs, ys, v, void="color",
                               cmap="viridis", atoms=None)
    assert n_void == 0 and v_lo <= 0
    out = tmp_path / "map_color.png"
    fig.savefig(out, dpi=100)
    assert out.stat().st_size > 1000


def test_draw_map_non_square_grid(tmp_path):
    """X/Y 点数不同时也不能横竖颠倒（distmap 是 X 外层 / Y 内层）。

    imshow 和带一维 x/y 的 contour 都要求 (Ny, Nx)；如果直接拿 (Nx, Ny)
    去画，非方网格会直接报形状错误，方网格则会静默转置。
    """
    xs = np.linspace(-3.0, 3.0, 30)
    ys = np.linspace(-2.0, 2.0, 20)
    xg, yg = np.meshgrid(xs, ys, indexing="ij")
    v = -(xg ** 2 + yg ** 2)            # shape (30, 20)
    fig = Figure(figsize=(4.0, 3.0), dpi=80)
    FigureCanvasAgg(fig)
    sp.draw_map(fig, xs, ys, v, void="color")
    out = tmp_path / "map_nonsquare.png"
    fig.savefig(out, dpi=100)
    assert out.stat().st_size > 1000
