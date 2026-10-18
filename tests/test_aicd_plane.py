# -*- coding: utf-8 -*-
"""分子平面判定：面板靠它把 AICD 的磁场方向（-b）预选成垂直环平面的轴。

背景：AICD 的磁场方向是相对 **Gaussian 标准取向**说的，用户在画布里怎么摆
都不影响计算，但也因此没法凭肉眼判断"哪个轴垂直于环"，所以必须自动判。
"""

import math

from molstudio.core.aicd import guess_plane_normal
from molstudio.core.aicd import guess_bonds, planar_rings

# 苯，标准取向（分子在 xy 平面）
BENZENE = [
    (6, 0.000000, 1.390788, 0.0), (6, 1.204458, 0.695394, 0.0),
    (6, 1.204458, -0.695394, 0.0), (6, 0.000000, -1.390788, 0.0),
    (6, -1.204458, -0.695394, 0.0), (6, -1.204458, 0.695394, 0.0),
    (1, 0.000000, 2.472882, 0.0), (1, 2.141579, 1.236441, 0.0),
    (1, 2.141579, -1.236441, 0.0), (1, 0.000000, -2.472882, 0.0),
    (1, -2.141579, -1.236441, 0.0), (1, -2.141579, 1.236441, 0.0),
]

# 同一个苯，但整体躺到 yz 平面（绕 y 轴转 90°）——法向应该变成 x
BENZENE_YZ = [(z, x, y, zz) for (z, x, y, zz) in
              [(a[0], a[3], a[2], -a[1]) for a in BENZENE]]


def test_benzene_normal_is_z():
    info = guess_plane_normal(BENZENE)
    assert info["planar"] is True
    assert info["axis"] == 2                 # z
    assert info["sign"] > 0
    assert info["rms"] < 1e-6


def test_benzene_rotated_into_yz_normal_is_x():
    info = guess_plane_normal(BENZENE_YZ)
    assert info["planar"] is True
    assert info["axis"] == 0                 # x


def test_tetrahedral_is_not_planar():
    ch4 = [("C", 0.0, 0.0, 0.0),
           ("H", 0.63, 0.63, 0.63), ("H", -0.63, -0.63, 0.63),
           ("H", -0.63, 0.63, -0.63), ("H", 0.63, -0.63, -0.63)]
    info = guess_plane_normal(ch4)
    assert info["planar"] is False
    assert info["rms"] > 0.3


def test_almost_planar_still_planar_and_too_few_atoms_falls_back():
    # 轻微褶皱（0.02 Å）仍算共平面
    ruffled = [(6, x, y, 0.02 if i % 2 else -0.02)
               for i, (x, y) in enumerate([(0.0, 1.39), (1.2, 0.695),
                                           (1.2, -0.695), (0.0, -1.39),
                                           (-1.2, -0.695), (-1.2, 0.695)])]
    assert guess_plane_normal(ruffled)["planar"] is True
    # 原子太少 → 认不出来，回退 +z 且标记非平面（面板据此提示用户）
    fallback = guess_plane_normal([("C", 0.0, 0.0, 0.0)])
    assert fallback["planar"] is False and fallback["axis"] == 2
    # 空输入也不能炸
    assert guess_plane_normal([])["planar"] is False


# ── 配合物：整体不共平面时改用"最平的环"定方向 ──────────────────────────

def _complex_with_ring():
    """苯环 + 环上方一个 Fe 与两个羰基（模拟含芳环的配合物，整体不共平面）。"""
    metal = [(26, 0.0, 0.0, 1.80), (6, 1.60, 0.0, 2.60), (8, 2.40, 0.0, 2.90)]
    return list(BENZENE) + metal


def test_complex_is_not_planar_but_ring_is_found():
    atoms = _complex_with_ring()
    assert guess_plane_normal(atoms)["planar"] is False
    rings = planar_rings(atoms)
    assert rings, "应当能找到苯环"
    ring = rings[0]
    assert ring["size"] == 6
    assert ring["atoms"] == [0, 1, 2, 3, 4, 5]        # 就是那六个碳
    assert ring["rms"] < 1e-6
    assert ring["axis"] == 2 and ring["sign"] > 0     # 法向 +z


def test_guess_bonds_finds_exactly_the_ring_and_sigma_bonds():
    bonds = guess_bonds(BENZENE)
    # 苯：6 根 C-C + 6 根 C-H
    assert len(bonds) == 12
    # 原子顺序是 C1..C6, H1..H6：C1 连着 C2、C6（环闭合）和 H1
    assert (0, 1) in bonds and (0, 5) in bonds
    assert (0, 6) in bonds                            # C1-H1
