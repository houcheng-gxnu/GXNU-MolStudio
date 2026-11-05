# -*- coding: utf-8 -*-
# Ported from StericMapAnalyzer (GPLv3) — SambVca 2.1 official algorithm replica.
# 来源：StericMapAnalyzer v3.5（同作者仓库，GPL-3.0-only）的 sambvca_native.py。
# License: GPL-3.0-only (inherited from StericMapAnalyzer).
# MolStudio 移植版：算法、常量、Fortran 行号注释与全部数值细节逐字保留，
# 只去掉了对原 GUI 工程的依赖（本文件仅依赖 numpy）。请勿"顺手修正"算法。
"""SambVca 2.1 官方 Fortran 体素算法的纯 numpy 复刻（逐位对齐官方 13 个算例）。

本模块只依赖 numpy，Python 3.9+。所有实现细节均照抄
``sambvca_official/Sambvca21/sambvca21.f``，注释里标注对应 Fortran 行号。
**不修正**官方源码里任何"看起来可疑"的写法（例如把距离平方与长度相比的
0.5 权重判据），因为验证目标是逐位复现，而不是重新定义一个更"正确"的算法。

算法概览（Fortran 行 485-546）::

    NumPoints = int(2*Radius/BinSize + 1)                 ! 行 491
    x = -Radius + (i-1)*BinSize   i = 1..NumPoints        ! 行 493-494（外层）
    y = -Radius + (j-1)*BinSize   j = 1..NumPoints        ! 行 495-496（中层）
    z = -Radius + (k-1)*BinSize   k = 1..NumPoints        ! 行 499-500（内层）
    dist2 = x²+y²+z²
    if dist2 <= Radius2:                                   ! 行 503
        NumInside += 1                                     ! 行 504
        Wgth = 1.0; 若 |dist2-Radius2| < 0.01*BinSize → 0.5 ! 行 505-506
        若存在 l 使 |体素中心-原子|² < AtomRadius2(l) → 掩埋   ! 行 507-513
        Vburf/Vburo/VburTot += BinSize³*Wgth               ! 行 518/525/530

其中 ``Radius2 = Radius*Radius + 0.0001*BinSize*BinSize``（行 451）。

对外接口::

    native_buried_volume(positions, radii, sphere_radius=3.5, mesh=0.10, cube=False)
    native_surfaces(positions, radii, radius=3.5, mesh=0.10)

``positions`` 只包含**参与计算**的原子（调用方已按删除列表与 RemoveH 规则筛过，
例如用 ``sambvca.select_atoms()``），``radii`` 是同一批原子的范德华半径（Å，
即 .inp 半径表里的数值，官方默认 scaled-Bondi）。
"""
from __future__ import annotations

import numpy as np

# ══════════════════════════════════════════════════════════════════════════
#  常量（与 Fortran 完全一致）
# ══════════════════════════════════════════════════════════════════════════

# Fortran 行 44：Real*8, parameter :: PI = 3.1415926535（只有 10 位有效数字）
PI_FORTRAN = 3.1415926535

# 官方 Quadrant 标签与索引顺序（OutputQua4，行 1343-1358）：
#   index 1=SW, 2=NW, 3=NE, 4=SE；对应 .dat 表头 '-- -+ ++ +-'（行 562）
QUADRANT_LABELS = ("SW", "NW", "NE", "SE")

# 官方 Octant 标签与索引顺序（OutputQua8，行 1388-1419）：
#   index 1..8 = SW-z, NW-z, NE-z, SE-z, SW+z, NW+z, NE+z, SE+z
#   对应 .dat 表头 '--- -+- ++- +-- --+ -++ +++ +-+'（行 576-577 / 1421-1422）
OCTANT_LABELS = ("SW-z", "NW-z", "NE-z", "SE-z", "SW+z", "NW+z", "NE+z", "SE+z")


# ══════════════════════════════════════════════════════════════════════════
#  Proj4 / Proj8：体素 → 象限 / 八分区的加权投影
# ══════════════════════════════════════════════════════════════════════════
def _accum4(x, y, w, cut, bs3, out):
    """复刻 subroutine Proj4（行 1042-1086），向量化。

    Fortran 原文是一串互斥的 ``if ... return`` 分支，本函数用 ``done`` 掩码
    保证"首个命中的分支生效"，语义完全一致。Cut = 0.25*BS（行 1047）。

    索引顺序（行 1081-1084）：1=(x<0,y<0)=SW, 2=(x<0,y>0)=NW,
                             3=(x>0,y>0)=NE, 4=(x>0,y<0)=SE。
    """
    done = np.zeros(x.shape, dtype=bool)
    ax_is, ay_is = np.abs(x) < cut, np.abs(y) < cut

    def step(mask, quads, frac):
        m = mask & ~done
        if m.any():
            contrib = float((w[m] * bs3 * frac).sum())
            for q in quads:
                out[q - 1] += contrib
            done[m] = True

    step(ax_is & ay_is, (1, 2, 3, 4), 0.25)   # 行 1049-1055：原点方块，4 向各 1/4
    step(ax_is & (y < 0), (1, 4), 0.5)        # 行 1057-1061：x 轴向条带
    step(ax_is & (y > 0), (2, 3), 0.5)        # 行 1063-1067
    step((x < 0) & ay_is, (1, 2), 0.5)        # 行 1069-1073：y 轴向条带
    step((x > 0) & ay_is, (3, 4), 0.5)        # 行 1075-1079
    step((x < 0) & (y < 0), (1,), 1.0)        # 行 1081-1084：四个开象限
    step((x < 0) & (y > 0), (2,), 1.0)
    step((x > 0) & (y > 0), (3,), 1.0)
    step((x > 0) & (y < 0), (4,), 1.0)
    return done


def _accum8(x, y, z, w, cut, bs3, out):
    """复刻 subroutine Proj8（行 1091-1258），向量化。

    与 Proj4 同样是"首个命中的分支生效"。索引顺序（行 1249-1256）：
      1=(x<0,y<=0,z<0)=SW-z, 2=(x<0,y>0,z<0)=NW-z,
      3=(x>=0,y>=0,z<0)=NE-z, 4=(x>=0,y<0,z<0)=SE-z,
      5=(x<0,y<=0,z>=0)=SW+z, 6=(x<0,y>0,z>=0)=NW+z,
      7=(x>=0,y>=0,z>=0)=NE+z, 8=(x>=0,y<0,z>=0)=SE+z。
    注意 x 用严格 ``<0``/``>=0``、y 用 ``<=0``/``>0``、z 用 ``<0``/``>=0``，
    这种不对称是官方原样（行 1249-1256），照抄不修正。
    """
    done = np.zeros(x.shape, dtype=bool)
    ax_is, ay_is, az_is = np.abs(x) < cut, np.abs(y) < cut, np.abs(z) < cut

    def step(mask, octs, frac):
        m = mask & ~done
        if m.any():
            contrib = float((w[m] * bs3 * frac).sum())
            for o in octs:
                out[o - 1] += contrib
            done[m] = True

    step(ax_is & ay_is & az_is, (1, 2, 3, 4, 5, 6, 7, 8), 0.125)  # 行 1099-1109 原点
    step((x < -cut) & ay_is & az_is, (1, 2, 5, 6), 0.25)          # 行 1112-1118 -x 轴
    step((x > +cut) & ay_is & az_is, (3, 4, 7, 8), 0.25)          # 行 1121-1127 +x 轴
    step(ax_is & (y < -cut) & az_is, (1, 4, 5, 8), 0.25)          # 行 1130-1136 -y 轴
    step(ax_is & (y > +cut) & az_is, (2, 3, 6, 7), 0.25)          # 行 1139-1145 +y 轴
    step(ax_is & ay_is & (z < -cut), (1, 2, 3, 4), 0.25)          # 行 1148-1154 -z 轴
    step(ax_is & ay_is & (z > +cut), (5, 6, 7, 8), 0.25)          # 行 1157-1163 +z 轴
    step((x < -cut) & (y < -cut) & az_is, (1, 5), 0.5)            # 行 1166-1170 -x-y 面
    step((x < -cut) & (y > +cut) & az_is, (2, 6), 0.5)            # 行 1173-1177 -x+y 面
    step((x > +cut) & (y < -cut) & az_is, (4, 8), 0.5)            # 行 1180-1184 +x-y 面
    step((x > +cut) & (y > +cut) & az_is, (3, 7), 0.5)            # 行 1187-1191 +x+y 面
    step((x < -cut) & ay_is & (z < -cut), (1, 2), 0.5)            # 行 1194-1198 -x-z 面
    step((x < -cut) & ay_is & (z > +cut), (5, 6), 0.5)            # 行 1201-1205 -x+z 面
    step((x > +cut) & ay_is & (z < -cut), (3, 4), 0.5)            # 行 1208-1212 +x-z 面
    step((x > +cut) & ay_is & (z > +cut), (7, 8), 0.5)            # 行 1215-1219 +x+z 面
    step(ax_is & (y < -cut) & (z < -cut), (1, 4), 0.5)            # 行 1222-1226 -y-z 面
    step(ax_is & (y < -cut) & (z > +cut), (5, 8), 0.5)            # 行 1229-1233 -y+z 面
    step(ax_is & (y > +cut) & (z < -cut), (2, 3), 0.5)            # 行 1236-1240 +y-z 面
    step(ax_is & (y > +cut) & (z > +cut), (6, 7), 0.5)            # 行 1243-1247 +y+z 面
    # 行 1249-1256：剩余体素（三个坐标都离轴足够远），y 的不对称判据原样保留
    step((x < 0) & (y <= 0) & (z < 0), (1,), 1.0)
    step((x < 0) & (y <= 0) & (z >= 0), (5,), 1.0)
    step((x < 0) & (y > 0) & (z < 0), (2,), 1.0)
    step((x < 0) & (y > 0) & (z >= 0), (6,), 1.0)
    step((x >= 0) & (y >= 0) & (z < 0), (3,), 1.0)
    step((x >= 0) & (y >= 0) & (z >= 0), (7,), 1.0)
    step((x >= 0) & (y < 0) & (z < 0), (4,), 1.0)
    step((x >= 0) & (y < 0) & (z >= 0), (8,), 1.0)
    return done


# ══════════════════════════════════════════════════════════════════════════
#  体素网格与体积循环
# ══════════════════════════════════════════════════════════════════════════
def _grid_axis(radius, mesh):
    """官方网格轴构造（行 491-500）。

    ``NumPoints = int(2.0*Radius/BinSize + 1.0)``；Fortran 的 ``int()`` 向零截断，
    Python 的 ``int()`` 行为相同，且两者都是 IEEE double，故运算顺序照抄：
    先 ``2.0*Radius``，再 ``/BinSize``，再 ``+1.0``。
    R=3.5/BS=0.10 → 71（官方 "N of voxels examined = 179579" 正对应 71³ 网格）；
    R=3.5/BS=0.05 → 141（官方 1436385）。
    """
    n = int(2.0 * radius / mesh + 1.0)
    if n <= 0:
        raise ValueError(
            "体素网格数为 %d（Radius=%r, BinSize=%r）：官方 sambvca21.f 没有 cube 模式，"
            "Radius<=0 时行 491 会得到非正的 NumPoints，主线循环体一次都不执行。"
            % (n, radius, mesh)
        )
    # 行 494/496/500：coord = -Radius + Real(idx-1)*BinSize
    return -radius + np.arange(n, dtype=float) * mesh


def _overlap_grid(P, radii, ax, radius, mesh):
    """体素–原子范德华重叠判据（行 507-513），返回 bool 数组 ov[i,j,k]。

    判据：``(x-px)² + (y-py)² + (z-pz)² < AtomRadius2``，严格小于，使用**体素中心**。
    向量化方式：逐原子在其 AABB 内做子块比较（不是逐体素 Python 循环），
    先取足够宽的整数窗口，再用精确的 d² < r² 判定，结果与逐体素完全一致。
    """
    n = ax.size
    ov = np.zeros((n, n, n), dtype=bool)
    for p, rr in zip(P, radii):
        r2 = rr * rr
        # 子块索引窗口（含端点，宁宽勿窄；精确性由下面的 d² 判据保证）
        lo = np.floor((p - rr + radius) / mesh).astype(np.int64)
        hi = np.ceil((p + rr + radius) / mesh).astype(np.int64)
        i0, j0, k0 = np.maximum(lo, 0)
        i1, j1, k1 = np.minimum(hi, n - 1)
        if i0 > i1 or j0 > j1 or k0 > k1:
            continue
        sx = ax[i0:i1 + 1] - p[0]
        sy = ax[j0:j1 + 1] - p[1]
        sz = ax[k0:k1 + 1] - p[2]
        d2 = (sx * sx)[:, None, None] + (sy * sy)[None, :, None] + (sz * sz)[None, None, :]
        ov[i0:i1 + 1, j0:j1 + 1, k0:k1 + 1] |= d2 < r2
    return ov


def _voxel_scan(positions, radii, radius, mesh, want_quadrants=True, want_surfaces=False):
    """官方体素循环（行 485-546）的向量化实现，返回原始累加量。"""
    if radius <= 0:
        raise ValueError("sphere_radius 必须为正（官方 Radius<=0 会退化为空网格，无 cube 模式）")
    if mesh <= 0:
        raise ValueError("mesh 必须为正")

    P = np.asarray(positions, dtype=float)
    r = np.asarray(radii, dtype=float).reshape(-1)
    if P.ndim != 2 or P.shape[1] != 3:
        raise ValueError("positions 形状必须为 (n_atoms, 3)")
    if P.shape[0] != r.size:
        raise ValueError("positions 与 radii 的原子数不一致：%d vs %d" % (P.shape[0], r.size))

    # 行 410-414：Cutoff = (数据库中最大半径 + Radius + 1.0)²；行 420-432 剔除远处原子。
    # 这里用传入半径的最大值代替"数据库最大半径"：两者都只会剔除无法与球重叠的原子，
    # 对 Vbur/象限/表面结果完全等价（远处原子的范德华球伸不到 R 球内）。
    if P.shape[0]:
        cutoff = (float(r.max()) + radius + 1.0) ** 2
        keep = np.einsum("ij,ij->i", P, P) <= cutoff
        P, r = P[keep], r[keep]

    ax = _grid_axis(radius, mesh)
    n = ax.size
    mesh = float(mesh)
    radius2 = radius * radius + 0.0001 * mesh * mesh     # 行 451
    bs2 = mesh * mesh                                    # 行 452
    bs3 = bs2 * mesh                                     # 行 453
    surf_tol = 0.01 * mesh                               # 行 506 的 0.01*BinSize

    ov = _overlap_grid(P, r, ax, radius, mesh) if P.shape[0] else np.zeros((n, n, n), bool)

    vburf = 0.0          # 行 518：无重叠体素的加权体积和
    vburo = 0.0          # 行 525：有重叠体素的加权体积和
    vbur_tot = 0.0       # 行 530：球内全部体素的加权体积和
    num_inside = 0       # 行 504
    num_buried = 0
    v4f = np.zeros(4)
    v4o = np.zeros(4)
    v8f = np.zeros(8)
    v8o = np.zeros(8)

    if want_surfaces:
        # 行 497-498：每个 (x,y) 列的哨兵初值；只有重叠体素才更新（行 534-537）
        zmax_grid = np.full((n, n), -radius * 2.0, dtype=float)
        zmin_grid = np.full((n, n), radius * 2.0, dtype=float)

    cut = 0.25 * mesh                                     # 行 1047 / 1096

    # 按 x 平面分块（Fortran 外层循环是 x，行 493；分块只为限制内存，不改变数值）
    chunk = max(1, min(n, int(1_000_000 // max(1, n * n)) or 1))
    yy = ax[None, :, None]
    zz = ax[None, None, :]
    yy2 = yy * yy
    zz2 = zz * zz
    for c0 in range(0, n, chunk):
        c1 = min(c0 + chunk, n)
        xs = ax[c0:c1]
        xx = xs[:, None, None]
        d2 = xx * xx + yy2 + zz2                          # 行 502
        inside = d2 <= radius2                            # 行 503
        n_in = int(np.count_nonzero(inside))
        if n_in == 0:
            continue
        num_inside += n_in
        # 行 505-506：Wgth=1.0，若 |dist2-Radius2| < 0.01*BinSize 则为 0.5。
        # 注意这里把"距离平方"与"长度"相比，是官方原样的量纲混用，照抄不修正。
        w = np.where(np.abs(d2 - radius2) < surf_tol, 0.5, 1.0)
        ovc = ov[c0:c1]
        free = inside & ~ovc                              # 行 517-521
        bur = inside & ovc                                # 行 524-528
        vburf += bs3 * float(w[free].sum())
        vburo += bs3 * float(w[bur].sum())
        vbur_tot += bs3 * float(w[inside].sum())
        num_buried += int(np.count_nonzero(bur))

        if want_quadrants:
            ci, yi, zi = np.nonzero(inside)
            xv = xs[ci]
            yv = ax[yi]
            zv = ax[zi]
            wv = w[inside]
            burv = bur[inside]
            if free.any():
                _accum4(xv[~burv], yv[~burv], wv[~burv], cut, bs3, v4f)   # 行 519
                _accum8(xv[~burv], yv[~burv], zv[~burv], wv[~burv], cut, bs3, v8f)  # 行 520
            if bur.any():
                _accum4(xv[burv], yv[burv], wv[burv], cut, bs3, v4o)      # 行 526
                _accum8(xv[burv], yv[burv], zv[burv], wv[burv], cut, bs3, v8o)      # 行 527

        if want_surfaces:
            zb = np.broadcast_to(zz, bur.shape)
            col_max = np.where(bur, zb, -np.inf).max(axis=2)   # 行 535
            col_min = np.where(bur, zb, np.inf).min(axis=2)    # 行 536
            zmax_grid[c0:c1] = np.maximum(zmax_grid[c0:c1], col_max)
            zmin_grid[c0:c1] = np.minimum(zmin_grid[c0:c1], col_min)

    out = {
        "radius": float(radius),
        "mesh": mesh,
        "radius2": radius2,
        "voxel_volume": bs3,
        "num_points": n,
        "grid_axis": ax,
        "num_inside": num_inside,
        "num_buried": num_buried,
        "vburf": vburf,
        "vburo": vburo,
        "vbur_tot": vbur_tot,
        "vbur4f": v4f,
        "vbur4o": v4o,
        "vbur8f": v8f,
        "vbur8o": v8o,
    }
    if want_surfaces:
        # 行 541-542：write(208,'(3f8.2)')x,y,zmax —— x 外层、y 内层，逐列一行
        out["x"] = np.repeat(ax, n)
        out["y"] = np.tile(ax, n)
        out["zmax"] = zmax_grid.reshape(-1)
        out["zmin"] = zmin_grid.reshape(-1)
    return out


# ══════════════════════════════════════════════════════════════════════════
#  对外接口
# ══════════════════════════════════════════════════════════════════════════
def native_buried_volume(positions, radii, sphere_radius=3.5, mesh=0.10, cube=False):
    """纯 numpy 复刻官方 %VBur（统计量对应 .out 的 "Results : Volumes" 段）。

    参数
    ----
    positions : (n, 3) float 数组
        只含**参与计算**的原子，且必须已经是官方定向后的坐标系
        （即 ``<name>-rotated.xyz`` 里的坐标，或调用 ``orient_sambvca()`` 的结果）。
        调用方需自行按删除列表与 RemoveH 规则筛过（例如 ``select_atoms()``）。
    radii : (n,) float 数组
        与 positions 一一对应的范德华半径（.inp 半径表的数值，官方 scaled-Bondi）。
    sphere_radius : float
        官方 ``Radius``（行 246），默认 3.5 Å。
    mesh : float
        官方 ``BinSize``（行 252），默认 0.10 Å。
    cube : bool
        官方 sambvca21.f（2.1 发行版）**没有** cube/盒子模式：全文没有对 Radius
        符号的分支，行 491 的 ``int(2R/BS+1)`` 在 Radius<0 时给出非正数，主线
        体素循环一次都不执行（VburTot=0 → 0/0）。因此这里显式拒绝 cube=True。

    返回
    ----
    dict，键包括：``percent_buried``（= 行 550/1312 的 %V Bur）、``buried_volume``、
    ``free_volume``、``sphere_volume``（行 548 的 V Exact，用官方 10 位 π）、
    ``voxel_volume``、``total_voxels``（行 504 的 NumInside，即 "N of voxels
    examined"）、``buried_voxels``（有重叠的体素计数）、``quadrant_percent``
    （键序 SW/NW/NE/SE，即 OutputQua4 的索引 1..4）、``octant_percent``
    （键序 SW-z…SE+z，即 OutputQua8 的索引 1..8），另附
    ``percent_free``、``total_volume``、``percent_total_vs_exact``、
    ``quadrant_volume``、``octant_volume``、``num_points``、``radius2``。
    """
    if cube:
        raise NotImplementedError(
            "官方 sambvca21.f（SambVca 2.1 发行版）没有 cube 模式：源码里没有对 "
            "Radius 符号的任何分支，Radius<0 只会让行 491 的 NumPoints<=0、体素循环"
            "空转。本模块照抄官方算法，故不提供 cube。"
        )
    scan = _voxel_scan(positions, radii, sphere_radius, mesh,
                       want_quadrants=True, want_surfaces=False)

    vbur_tot = scan["vbur_tot"]
    percent_buried = 100.0 * scan["vburo"] / vbur_tot if vbur_tot > 0 else float("nan")
    # 行 548：Volume = Radius*Radius2*pi*4/3（用的是被加了 1e-6 的 Radius2）
    volume = scan["radius"] * scan["radius2"] * PI_FORTRAN * 4.0 / 3.0

    v4o, v4f = scan["vbur4o"], scan["vbur4f"]
    v8o, v8f = scan["vbur8o"], scan["vbur8f"]
    q_pct, q_vol = {}, {}
    for i, lab in enumerate(QUADRANT_LABELS):
        tot = v4f[i] + v4o[i]
        # 行 1343-1358：%V b = 100*Vbur4o(i)/(Vbur4f(i)+Vbur4o(i))
        q_pct[lab] = 100.0 * v4o[i] / tot if tot > 0 else float("nan")
        q_vol[lab] = (float(v4f[i]), float(v4o[i]))
    o_pct, o_vol = {}, {}
    for i, lab in enumerate(OCTANT_LABELS):
        tot = v8f[i] + v8o[i]
        o_pct[lab] = 100.0 * v8o[i] / tot if tot > 0 else float("nan")
        o_vol[lab] = (float(v8f[i]), float(v8o[i]))

    return {
        "percent_buried": percent_buried,                       # %V Buried
        "percent_free": 100.0 * scan["vburf"] / vbur_tot if vbur_tot > 0 else float("nan"),
        "percent_total_vs_exact": 100.0 * vbur_tot / volume if volume > 0 else float("nan"),
        "buried_volume": scan["vburo"],
        "free_volume": scan["vburf"],
        "total_volume": vbur_tot,
        "sphere_volume": volume,
        "voxel_volume": scan["voxel_volume"],
        "total_voxels": scan["num_inside"],
        "buried_voxels": scan["num_buried"],
        "quadrant_percent": q_pct,
        "quadrant_volume": q_vol,
        "octant_percent": o_pct,
        "octant_volume": o_vol,
        "num_points": scan["num_points"],
        "radius2": scan["radius2"],
    }


def native_surfaces(positions, radii, radius=3.5, mesh=0.10):
    """复刻官方 TopSurface/BotSurface 扫描（行 497-498、533-543）。

    对网格的**每个** (x,y) 列，沿 z 从 -Radius 向 +Radius 扫描（行 499-500 的
    k 递增顺序），只统计"球内且与任一原子范德华球重叠"的体素：
      * zmax 初值哨兵 = -2*Radius（行 498），只增不减（行 535）
      * zmin 初值哨兵 = +2*Radius（行 497），只减不增（行 536）
      * 空列保持哨兵 ±2*Radius，官方 .dat 里就是 ±7.00（R=3.5）这类值
      * 写出顺序为 x 外层、y 内层（行 541-542），每列一行

    注意：Fortran 里 ``if(IfOverlap.eq.1)`` 在球判据之外，但 ``IfOverlap`` 在
    每个 k 迭代开头都重置为 0（行 501），所以实际只有球内重叠体素会更新极值。

    返回 ``{'x','y','zmax','zmin'}``，四个长度 N² 的一维数组，行序与官方
    ``<name>-TopSurface.dat`` / ``-BotSurface.dat`` 完全一致。
    """
    scan = _voxel_scan(positions, radii, radius, mesh,
                       want_quadrants=False, want_surfaces=True)
    return {"x": scan["x"], "y": scan["y"],
            "zmax": scan["zmax"], "zmin": scan["zmin"]}


__all__ = [
    "PI_FORTRAN", "QUADRANT_LABELS", "OCTANT_LABELS",
    "native_buried_volume", "native_surfaces",
]
