# -*- coding: utf-8 -*-
"""原子轨道 / 杂化轨道的解析波函数与 Gaussian cube 生成
==========================================================

给「电子结构库」提供可复现、可数值验证的轨道等值面数据源。全部在**原子单位**
（Bohr、Hartree、Z=1）下求值，不依赖 Multiwfn / Gaussian / fchk，纯解析。

数学约定
--------

波函数写成径向 × 角向：::

    psi(r) = R(r) * Y_lm^real(theta, phi)

角向部分用**实球谐**（real spherical harmonics），由连带 Legendre 多项式
构造并去掉 Condon-Shortley 相位，使得 ``p_x ∝ +x``、``d_xy ∝ +xy``，
与化学教材的轨道记号一致；每个 ``Y_lm^real`` 都归一化到 ``∫|Y|² dΩ = 1``。

径向部分有两套模型：

* ``hydrogenic`` —— **完整类氢原子径向函数** R_nl(r)，带广义 Laguerre
  多项式，因此 2s / 3s 会真实出现径向节点::

      rho = 2Zr/n
      R_nl = sqrt((2Z/n)^3 (n-l-1)! / (2n (n+l)!))
             * exp(-rho/2) * rho^l * L^{2l+1}_{n-l-1}(rho)

* ``sto`` —— **无节点 Slater 型径向**，按角动量给指数::

      R_l = sqrt((2 zeta)^(2l+3) / (2l+2)!) * r^l * exp(-zeta*r)

  当 ``zeta = 1/(l+1)`` 时它与类氢 ``n = l+1`` 轨道**完全等价**，所以
  1s / 2p / 3d / 4f 本身就是教科书里那些无径向节点的标准形状。

* ``sto_shell`` —— **同一主壳层的 Slater 型径向**，杂化轨道专用::

      R_n = sqrt((2 zeta)^(2n+1) / (2n)!) * r^(n-1) * exp(-zeta*r)

  sp / sp² / sp³ 是同一壳层（n = 2）的 s 与 p 混合，两者的径向因子必须
  同形（``r·exp(-zeta r)``）。若给 s 用 ``r^0``、给 p 用 ``r^1``，s 通道
  在核附近权重过大，杂化出来的反相小瓣会长到正瓣的七成，与教科书
  "一头大一头小"的形状不符（改为此模型后振幅比正好 1/2）。
  杂化要求 s 与 p 共用同一个 ``zeta``（这里取 0.5），否则线性组合出来的
  葫芦形状同样会走样。

归一化 ∫|psi|² d³r = 1 可在 ``tests/test_atomic_orbital.py`` 里用数值积分验证。

显示约定
--------

写进 cube 之前把场按 ``max|psi|`` 缩放到 ±1 —— **只做线性缩放，形状与节点
位置完全不变**。原因是画布 ``set_isovalue`` 把 iso 下限钳在 0.005，而 4f
的真实峰值只有 1e-4 量级，直接写原始值会导致等值面被整块钳掉。真实的
``psi_max`` 会一并返回，UI 上标明"峰值已归一化，形状不变"。有径向节点的
2s / 3s 外瓣比内瓣弱得多，用更小的 iso（见 ``OrbitalSpec.iso_hint``）才能
同时看到内外两瓣。

坐标单位
--------

Gaussian cube 的 origin / step / 原子坐标一律写 **Bohr**（与
``molstudio.core.marching_cubes.read_cube`` 及 OpenGL 画布一致），数据为
无量纲的显示场。网格索引顺序 ``[ix, iy, iz]`` 对应 ``(x, y, z)``。
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Sequence, Tuple

import numpy as np
from scipy.special import lpmv

__all__ = [
    "OrbitalSpec", "GROUP_ORDER", "GROUP_LABELS", "QUALITY_LEVELS",
    "MIN_ISOVALUE",
    "orbital_library", "orbital_by_id", "angular_key", "real_harmonic",
    "radial_hydrogenic", "radial_sto", "radial_sto_shell", "evaluate_orbital",
    "generate_field", "iso_surfaces", "write_orbital_cube", "build_orbital_cube",
]


# ── 角向记号 → (l, m)；m>0 为 cos(mφ) 分量，m<0 为 sin(|m|φ) 分量 ──────
ANGULAR: Dict[str, Tuple[int, int]] = {
    "s":       (0, 0),
    "px":      (1, 1),
    "py":      (1, -1),
    "pz":      (1, 0),
    "dz2":     (2, 0),
    "dxz":     (2, 1),
    "dyz":     (2, -1),
    "dx2y2":   (2, 2),
    "dxy":     (2, -2),
    "fz3":     (3, 0),
    "fxz2":    (3, 1),
    "fyz2":    (3, -1),
    "fzx2y2":  (3, 2),
    "fxyz":    (3, -2),
    "fx3y2":   (3, 3),
    "fy3x2":   (3, -3),
}

GROUP_ORDER = ("s", "p", "d", "f", "hybrid")
GROUP_LABELS = {
    "s":      ("s 轨道", "s orbitals"),
    "p":      ("p 轨道", "p orbitals"),
    "d":      ("d 轨道", "d orbitals"),
    "f":      ("f 轨道", "f orbitals"),
    "hybrid": ("杂化轨道", "Hybrid orbitals"),
}

#: 网格点数（每轴）。**一律取奇数**，保证网格正中有 r = 0 的采样点：
#: 偶数格会把 1s / 2s 的核处峰值漏掉（48³ 时 1s 峰值被测成 0.420 而非
#: 解析值 0.564），杂化轨道在核附近的相位也会采样偏。
QUALITY_LEVELS = {"low": 49, "medium": 65, "high": 81}

#: 画布 / 面板允许的最小 iso（``CubCanvasPanel.set_isovalue`` 与电子结构库
#: 的 spin 下限）。画布 cube 按这个最坏情况预留外扩量，用户之后在画布上
#: 继续把 iso 调小也不会把瓣尖切掉。
MIN_ISOVALUE = 0.005

_BOHR_TO_ANGSTROM = 0.529177210903


def angular_key(key: str) -> Tuple[int, int]:
    """把化学记号映射成 ``(l, m)``。"""
    try:
        return ANGULAR[key]
    except KeyError:
        raise KeyError("未知的轨道角向记号: %r" % key) from None


def real_harmonic(l: int, m: int, cos_theta, phi):
    """归一化实球谐 Y_lm^real(θ, φ)，``∫|Y|² dΩ = 1``。

    去掉 ``scipy.special.lpmv`` 自带的 Condon-Shortley 相位 ``(-1)^m``，
    保证 ``p_x ∝ +x / r``、``d_xz ∝ +xz / r²`` 等化学约定；``m > 0`` 取
    ``cos(mφ)`` 分量，``m < 0`` 取 ``sin(|m|φ)`` 分量。
    """
    am = abs(m)
    if am > l:
        raise ValueError("|m| 不能大于 l: l=%d m=%d" % (l, m))
    norm = math.sqrt((2 * l + 1) / (4.0 * math.pi)
                     * math.factorial(l - am) / math.factorial(l + am))
    # (-1)**am 抵消 lpmv 的 Condon-Shortley 相位
    legendre = lpmv(am, l, cos_theta) * ((-1) ** am)
    if m == 0:
        return norm * legendre
    amp = math.sqrt(2.0) * norm * legendre
    return amp * (np.cos(am * phi) if m > 0 else np.sin(am * phi))


def _genlaguerre(k: int, alpha: int, x):
    """广义 Laguerre 多项式 L_k^alpha(x)，三项递推（k ≤ n-l-1，很小）。"""
    if k == 0:
        return np.ones_like(x, dtype=np.float64)
    lm1 = np.ones_like(x, dtype=np.float64)     # L_0
    l0 = (1.0 + alpha - x)                     # L_1
    if k == 1:
        return l0
    for j in range(1, k):
        l1 = ((2 * j + 1 + alpha - x) * l0 - (j + alpha) * lm1) / (j + 1)
        lm1, l0 = l0, l1
    return l0


def radial_hydrogenic(n: int, l: int, r, Z: float = 1.0):
    """完整类氢径向函数 R_nl(r)（原子单位，含径向节点）。"""
    if not (n >= 1 and 0 <= l < n):
        raise ValueError("非法量子数 n=%d l=%d" % (n, l))
    rho = 2.0 * Z * np.asarray(r, dtype=np.float64) / n
    k = n - l - 1
    pref = math.sqrt((2.0 * Z / n) ** 3
                     * math.factorial(k) / (2.0 * n * math.factorial(n + l)))
    return pref * np.exp(-rho / 2.0) * np.power(rho, l) \
        * _genlaguerre(k, 2 * l + 1, rho)


def radial_sto(l: int, r, zeta: float):
    """无节点 Slater 型径向 R_l(r) = N r^l exp(-ζr)，归一化到 ∫|R|²r²dr = 1。"""
    if zeta <= 0:
        raise ValueError("zeta 必须为正")
    norm = math.sqrt((2.0 * zeta) ** (2 * l + 3)
                     / math.factorial(2 * l + 2))
    return norm * np.power(np.asarray(r, dtype=np.float64), l) \
        * np.exp(-zeta * np.asarray(r, dtype=np.float64))


def radial_sto_shell(n: int, r, zeta: float):
    """同一主壳层的 Slater 型径向 R_n(r) = N r^(n-1) exp(-ζr)。

    与 :func:`radial_sto` 只差指数：后者用 ``r^l``（等价于类氢 ``n = l+1``），
    这里用 Slater 轨道的原始定义 ``r^(n-1)``。归一化
    ``N = sqrt((2ζ)^(2n+1) / (2n)!)``，满足 ``∫|R|²r²dr = 1``。

    **杂化轨道必须用这个模型。** sp³ 是同一壳层 2s 与 2p 的混合，两者的
    径向因子都应是 ``r·exp(-ζr)``。若给 s 用 ``r^0``、给 p 用 ``r^1``，
    s 通道在核附近的权重远大于 p，杂化出来的反相小瓣会长到正瓣的七成
    （实测 sp³ 两瓣几乎一样大，与教科书的"一头大一头小"不符）；
    改成本函数后小瓣/大瓣振幅比正好 1/2。
    """
    if zeta <= 0:
        raise ValueError("zeta 必须为正")
    k = max(int(n), 1)
    norm = math.sqrt((2.0 * zeta) ** (2 * k + 1)
                     / math.factorial(2 * k))
    r = np.asarray(r, dtype=np.float64)
    return norm * np.power(r, k - 1) * np.exp(-zeta * r)


@dataclass(frozen=True)
class OrbitalSpec:
    """一条轨道的元信息 + 求值配方。

    ``terms`` 是 ``((角向记号, 系数), ...)``；纯轨道只有一项，杂化轨道是
    多个 AO 的正交归一线性组合。所有项共用 ``radial`` / ``zeta`` / ``n``。
    """
    id: str
    group: str
    label_zh: str
    label_en: str
    terms: Tuple[Tuple[str, float], ...]
    radial: str                    # "hydrogenic" | "sto"
    n: Optional[int] = None        # hydrogenic 用
    zeta: float = 0.5              # sto 用
    extent: float = 12.0           # 网格半边长 / Bohr
    iso_hint: float = 0.08         # 建议等值面（场已按峰值归一化到 ±1）
    nodes_zh: str = ""
    nodes_en: str = ""
    note_zh: str = ""
    note_en: str = ""

    @property
    def l(self) -> int:
        return max(angular_key(k)[0] for k, _c in self.terms)

    @property
    def angular_momenta(self) -> Tuple[int, ...]:
        return tuple(sorted({angular_key(k)[0] for k, _c in self.terms}))

    def display_name(self, lang: str = "zh") -> str:
        return self.label_en if str(lang).lower().startswith("en") \
            else self.label_zh

    def nodes(self, lang: str = "zh") -> str:
        return self.nodes_en if str(lang).lower().startswith("en") \
            else self.nodes_zh

    def note(self, lang: str = "zh") -> str:
        return self.note_en if str(lang).lower().startswith("en") \
            else self.note_zh

    def group_label(self, lang: str = "zh") -> str:
        zh, en = GROUP_LABELS[self.group]
        return en if str(lang).lower().startswith("en") else zh


def _sp(label_zh, label_en, ident, terms, group, *, radial=None,
        n=None, zeta=0.5, extent=12.0, iso_hint=0.08,
        nodes_zh="", nodes_en="", note_zh="", note_en=""):
    # 给了主量子数就是完整类氢轨道（带真实径向节点）；没给就是杂化轨道，
    # 走"同一壳层"的 Slater 径向（所有 s / p 分量共用 r·exp(-ζr)）。
    # 不能用类氢 2s：它的径向节点会把杂化瓣切碎；也不能给 s 用 r^0 的
    # STO：那样反相小瓣会长得和正瓣一样大（见 radial_sto_shell）。
    if radial is None:
        if n is not None:
            radial = "hydrogenic"
        else:
            radial, n = "sto_shell", 2
    return OrbitalSpec(ident, group, label_zh, label_en,
                       tuple(terms), radial, n, zeta, extent, iso_hint,
                       nodes_zh, nodes_en, note_zh, note_en)


def _atomic_specs() -> Tuple[OrbitalSpec, ...]:
    """s / p / d / f 各角动量通道的无径向节点标准形状 + 2s/3s 径向节点。"""
    out = []

    # ── s ──
    out.append(_sp(
        "1s", "1s", "1s", (("s", 1.0),), "s", n=1, extent=6.0,
        nodes_zh="无节面；球对称", nodes_en="No node; spherical",
        note_zh="基态氢原子轨道，psi(0) 最大，随 r 指数衰减。",
        note_en="Hydrogen ground state; maximum at the nucleus, exponential decay."))
    out.append(_sp(
        "2s", "2s", "2s", (("s", 1.0),), "s", n=2, extent=16.0,
        iso_hint=0.025,
        nodes_zh="1 个径向节面（r = 2 a₀）", nodes_en="1 radial node (r = 2 a0)",
        note_zh="外壳相位与 1s 相反（橙），径向节面埋在 r = 2 a₀ 处。"
                "等值面是**嵌套**的，外壳把内层小球整个包住，画布上只看到外壳 —— "
                "这一点与 GaussView 等程序一致。",
        note_en="The outer shell has the opposite phase to 1s (orange); the radial "
                "node sits inside at r = 2 a0. The isosurfaces are **nested**, so "
                "the outer shell hides the inner lobe (same as GaussView)."))
    out.append(_sp(
        "3s", "3s", "3s", (("s", 1.0),), "s", n=3, extent=26.0,
        iso_hint=0.015,
        nodes_zh="2 个径向节面", nodes_en="2 radial nodes",
        note_zh="三层同心球壳，相邻壳层相位交替；外壳把内两层包住，"
                "所以画布上只看到最外层（与 1s 同色，相位相同）。",
        note_en="Three concentric shells with alternating phase; the outermost hides "
                "the two inner ones, so only the outer shell is visible."))

    # ── p ──
    # 名称一律用纯文本：QListWidgetItem 不解析 HTML，写 <sub> 会原样显示成
    # 字面标签（实测截图里就是 "2p<sub>x</sub>"）。
    p_defs = (
        ("2p_x", "2p_x", "2px", "px", "x", "x"),
        ("2p_y", "2p_y", "2py", "py", "y", "y"),
        ("2p_z", "2p_z", "2pz", "pz", "z", "z"),
    )
    for zh, en, ident, key, axis_zh, axis_en in p_defs:
        out.append(_sp(
            zh, en, ident, ((key, 1.0),), "p", n=2, extent=13.0,
            nodes_zh="1 个角节面（%s = 0 平面）" % axis_zh,
            nodes_en="1 angular nodal plane (%s = 0)" % axis_en,
            note_zh="沿 %s 轴的两瓣哑铃，两瓣相位相反。" % axis_zh,
            note_en="Two lobes along the %s axis with opposite phase." % axis_en))

    # ── d ──
    d_defs = (
        ("3d_z²", "3d_z2", "3dz2", "dz2",
         "2 个锥形角节面", "2 conical angular nodes",
         "沿 z 轴两瓣 + xy 平面圆环，环与两瓣相位相反。",
         "Two lobes along z plus a torus in the xy plane (opposite phase)."),
        ("3d_xz", "3d_xz", "3dxz", "dxz",
         "2 个角节面（xy、yz 平面）", "2 angular nodal planes (xy, yz)",
         "四叶草形，叶瓣位于 xz 平面。", "Four lobes in the xz plane."),
        ("3d_yz", "3d_yz", "3dyz", "dyz",
         "2 个角节面（xy、xz 平面）", "2 angular nodal planes (xy, xz)",
         "四叶草形，叶瓣位于 yz 平面。", "Four lobes in the yz plane."),
        ("3d_xy", "3d_xy", "3dxy", "dxy",
         "2 个角节面（xz、yz 平面）", "2 angular nodal planes (xz, yz)",
         "四叶草形，叶瓣指向 xy 平面的象限对角线。",
         "Four lobes between the x and y axes."),
        ("3d_x²−y²", "3d_x2-y2", "3dx2y2", "dx2y2",
         "2 个角节面（x = ±y）", "2 angular nodal planes (x = ±y)",
         "四叶草形，叶瓣沿 x、y 轴。", "Four lobes along the x and y axes."),
    )
    for zh, en, ident, key, nz, ne, tz, te in d_defs:
        out.append(_sp(zh, en, ident, ((key, 1.0),), "d", n=3,
                       extent=19.0, nodes_zh=nz, nodes_en=ne,
                       note_zh=tz, note_en=te))

    # ── f ──
    f_defs = (
        ("4f_z³", "4f_z3", "4fz3", "fz3",
         "z 轴两瓣 + 两个锥环", "Two z lobes plus two toroidal rings"),
        ("4f_xz²", "4f_xz2", "4fxz2", "fxz2",
         "6 瓣", "6 lobes"),
        ("4f_yz²", "4f_yz2", "4fyz2", "fyz2",
         "6 瓣", "6 lobes"),
        ("4f_z(x²−y²)", "4f_z(x2-y2)", "4fzx2y2", "fzx2y2",
         "8 瓣", "8 lobes"),
        ("4f_xyz", "4f_xyz", "4fxyz", "fxyz",
         "8 瓣，指向立方体顶点方向", "8 lobes toward cube corners"),
        ("4f_x(x²−3y²)", "4f_x(x2-3y2)", "4fx3y2", "fx3y2",
         "6 瓣", "6 lobes"),
        ("4f_y(3x²−y²)", "4f_y(3x2-y2)", "4fy3x2", "fy3x2",
         "6 瓣", "6 lobes"),
    )
    for zh, en, ident, key, nz, ne in f_defs:
        out.append(_sp(
            zh, en, ident, ((key, 1.0),), "f", n=4, extent=27.0,
            iso_hint=0.06,
            nodes_zh="3 个角节面（%s）" % nz,
            nodes_en="3 angular nodes (%s)" % ne,
            note_zh="l = 3，共 7 个简并轨道；立方型 f 轨道常用这一组实组合。",
            note_en="l = 3: seven degenerate orbitals in the cubic real basis."))
    return tuple(out)


def _hybrid_specs() -> Tuple[OrbitalSpec, ...]:
    """sp / sp² / sp³ 的每一瓣都是一条独立的正交归一的杂化轨道。

    s 与 p 共用 zeta = 0.5（氢原子 2p 的径向衰减），并用同一壳层的
    Slater 径向（见 :func:`radial_sto_shell`），线性组合才得到教材里那种
    一头大一头小的"葫芦"，而不是被 2s 径向节点切碎。

    ``iso_hint`` 比纯轨道大一档（0.18 对 0.06），原因不是笔误：杂化的径向
    衰减慢（zeta = 0.5），等值面阈值取得太低时，正瓣在**各个方向**都能
    达到阈值，画出来接近圆球。按峰值百分比算，iso/peak = 0.10 时长宽比
    只有 1.6，0.18~0.20 时升到 2.2 —— 才是课本里那个水滴形。
    """
    r2 = math.sqrt(2.0)
    r3 = math.sqrt(3.0)
    r6 = math.sqrt(6.0)
    specs = []

    sp = (
        ("sp (1/2)", "sp (1/2)", "sp_1",
         (("s", 1.0 / r2), ("pz", 1.0 / r2)), "+z"),
        ("sp (2/2)", "sp (2/2)", "sp_2",
         (("s", 1.0 / r2), ("pz", -1.0 / r2)), "−z"),
    )
    for zh, en, ident, terms, direction in sp:
        specs.append(_sp(
            zh, en, ident, terms, "hybrid", zeta=0.5, extent=11.0,
            iso_hint=0.18,
            nodes_zh="直线型，两瓣夹角 180°（指向 %s）" % direction,
            nodes_en="Linear, 180 deg apart (towards %s)" % direction,
            note_zh="s:p = 1:1；BeCl₂、CO₂、炔烃碳的中心原子。",
            note_en="s:p = 1:1; BeCl2, CO2, alkyne carbons."))

    sp2 = (
        ("sp² (1/3)", "sp2 (1/3)", "sp2_1",
         (("s", 1.0 / r3), ("px", r2 / r3))),
        ("sp² (2/3)", "sp2 (2/3)", "sp2_2",
         (("s", 1.0 / r3), ("px", -1.0 / r6), ("py", 1.0 / r2))),
        ("sp² (3/3)", "sp2 (3/3)", "sp2_3",
         (("s", 1.0 / r3), ("px", -1.0 / r6), ("py", -1.0 / r2))),
    )
    for zh, en, ident, terms in sp2:
        specs.append(_sp(
            zh, en, ident, terms, "hybrid", zeta=0.5, extent=11.0,
            iso_hint=0.18,
            nodes_zh="平面三角形，三瓣共面且夹角 120°",
            nodes_en="Trigonal planar, three coplanar lobes 120 deg apart",
            note_zh="s:p = 1:2；BF₃、乙烯碳、羰基碳；剩余 p 轨道形成 π 键。",
            note_en="s:p = 1:2; BF3, alkene and carbonyl carbons; the leftover p forms pi bonds."))

    sp3 = (
        ("sp³ (1/4)", "sp3 (1/4)", "sp3_1",
         (("s", 0.5), ("px", 0.5), ("py", 0.5), ("pz", 0.5))),
        ("sp³ (2/4)", "sp3 (2/4)", "sp3_2",
         (("s", 0.5), ("px", 0.5), ("py", -0.5), ("pz", -0.5))),
        ("sp³ (3/4)", "sp3 (3/4)", "sp3_3",
         (("s", 0.5), ("px", -0.5), ("py", 0.5), ("pz", -0.5))),
        ("sp³ (4/4)", "sp3 (4/4)", "sp3_4",
         (("s", 0.5), ("px", -0.5), ("py", -0.5), ("pz", 0.5))),
    )
    for zh, en, ident, terms in sp3:
        specs.append(_sp(
            zh, en, ident, terms, "hybrid", zeta=0.5, extent=11.0,
            iso_hint=0.18,
            nodes_zh="正四面体，四瓣夹角 109.47°",
            nodes_en="Tetrahedral, four lobes 109.47 deg apart",
            note_zh="s:p = 1:3；CH₄、NH₃、H₂O 的中心原子（孤对电子也占一条）。",
            note_en="s:p = 1:3; CH4, NH3, H2O (lone pairs occupy hybrid orbitals too)."))
    return tuple(specs)


_SPECS: Tuple[OrbitalSpec, ...] = _atomic_specs() + _hybrid_specs()
_BY_ID: Dict[str, OrbitalSpec] = {s.id: s for s in _SPECS}
# 组内按**定义顺序**排，不能按 id 字典序：否则 "sp2_1" 会排在 "sp_1"
# 前面（'2' < '_'），教学顺序 sp → sp² → sp³ 就乱了。
_SPEC_INDEX: Dict[str, int] = {s.id: i for i, s in enumerate(_SPECS)}


def orbital_library() -> Tuple[OrbitalSpec, ...]:
    """全部轨道（s / p / d / f / 杂化），按 GROUP_ORDER + 组内定义顺序。"""
    return tuple(sorted(_SPECS, key=lambda s: (
        GROUP_ORDER.index(s.group), _SPEC_INDEX[s.id])))


def orbital_by_id(ident: str) -> OrbitalSpec:
    try:
        return _BY_ID[ident]
    except KeyError:
        raise KeyError("电子结构库里没有轨道 %r" % ident) from None


def evaluate_orbital(spec: OrbitalSpec, x, y, z, Z: float = 1.0):
    """在任意网格点上求 psi（真实 a.u.，未做显示归一化）。

    ``x/y/z`` 为 Bohr 单位的 broadcastable 数组。返回的场满足
    ``∫|psi|² d³r = 1``（Z=1 时）。
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    z = np.asarray(z, dtype=np.float64)
    r = np.sqrt(x * x + y * y + z * z)
    # r = 0 处极角无定义；取 cos(theta)=1，此时 l>0 的径向因子必为 0，
    # 只有 s 通道非零且角向为常数，所以取什么方向都不影响结果。
    ct = np.divide(z, r, out=np.ones_like(r), where=r > 0)
    np.clip(ct, -1.0, 1.0, out=ct)
    phi = np.arctan2(y, x)

    psi = None
    for key, coeff in spec.terms:
        l, m = angular_key(key)
        if spec.radial == "hydrogenic":
            radial = radial_hydrogenic(int(spec.n), l, r, Z)
        elif spec.radial == "sto":
            radial = radial_sto(l, r, spec.zeta)
        elif spec.radial == "sto_shell":
            radial = radial_sto_shell(int(spec.n), r, spec.zeta)
        else:
            raise ValueError("未知径向模型: %r" % spec.radial)
        term = coeff * radial * real_harmonic(l, m, ct, phi)
        psi = term if psi is None else psi + term
    if psi is None:
        raise ValueError("轨道 %s 没有定义任何角向分量" % spec.id)
    return psi


def _fibonacci_directions(count: int) -> np.ndarray:
    """单位球面上近似均匀的 ``count`` 个方向（确定性，无随机）。"""
    idx = np.arange(count, dtype=np.float64) + 0.5
    cos_theta = 1.0 - 2.0 * idx / count
    sin_theta = np.sqrt(np.clip(1.0 - cos_theta * cos_theta, 0.0, 1.0))
    phi = math.pi * (1.0 + 5.0 ** 0.5) * idx
    return np.column_stack((sin_theta * np.cos(phi),
                            sin_theta * np.sin(phi),
                            cos_theta))


def _outer_radius(spec: OrbitalSpec, iso: float, max_radius: float,
                  *, Z: float = 1.0, directions: int = 384,
                  steps: int = 320) -> float:
    """沿球面方向找 ``|psi| >= iso`` 的最外层半径（Bohr）。

    只做一维径向扫描（约 5~10 ms），比反复求整张三维网格便宜得多。返回
    ``0`` 表示在 ``max_radius`` 内始终低于 iso。
    """
    if iso <= 0.0 or max_radius <= 0.0:
        return 0.0
    dirs = _fibonacci_directions(int(directions))
    radii = np.linspace(1e-3, float(max_radius), int(steps))
    points = radii[:, None, None] * dirs[None, :, :]
    psi = evaluate_orbital(spec, points[..., 0], points[..., 1],
                           points[..., 2], Z)
    peak = float(np.max(np.abs(psi)))
    if not (peak > 0.0) or not math.isfinite(peak):
        return 0.0
    hits = np.abs(psi / peak) >= float(iso)
    if not hits.any():
        return 0.0
    return float(radii[np.any(hits, axis=1)].max())


def generate_field(spec: OrbitalSpec, quality: str = "medium",
                   Z: float = 1.0, iso: Optional[float] = None):
    """生成规则网格上的显示场。

    ``iso`` 给出时，立方体会**先按该等值面自动外扩**（最多到基准
    ``spec.extent`` 的 4 倍），并在返回前检查六个边界面：只要边界上仍
    ``|psi| >= iso`` 就继续按 1.15 倍放大重来。这样画布 / VMD 在小 iso 下
    看到的也是闭合等值面，而不是被立方体边界切掉瓣尖（f 轨道在 iso = 0.005
    时约需 1.9 倍基准边长）。``iso=None`` 时保持原行为。

    返回 ``(field, origin, spacing, psi_max)``：

    * ``field``   —— ``(N,N,N) float64``，已按 ``max|psi|`` 归一化到 ±1；
    * ``origin``  —— ``(3,) float64``，网格左下角，**Bohr**；
    * ``spacing`` —— 标量，各轴步长，**Bohr**；
    * ``psi_max`` —— 归一化前的真实峰值（a.u.），供 UI 显示。
    """
    if quality not in QUALITY_LEVELS:
        raise ValueError("网格精度必须是 low / medium / high")
    n_grid = QUALITY_LEVELS[quality]
    ext = float(spec.extent)
    level = None
    if iso is not None:
        try:
            level = float(iso)
        except (TypeError, ValueError):
            level = None
        if level is not None and (not math.isfinite(level) or level <= 0.0):
            level = None
    max_ext = ext * 4.0
    if level is not None:
        outer = _outer_radius(spec, level, max_ext, Z=Z)
        if outer > 0.0:
            # 10% 余量：球面方向是有限采样，立方体边界必须落在最外层等值面
            # 之外；离散网格的边界检查还会再兜一次底。
            ext = max(ext, min(max_ext, outer * 1.10))
    field = psi_max = None
    for _attempt in range(4):
        axis = np.linspace(-ext, ext, n_grid, dtype=np.float64)
        X, Y, Zc = np.meshgrid(axis, axis, axis, indexing="ij")
        psi = evaluate_orbital(spec, X, Y, Zc, Z)
        psi_max = float(np.max(np.abs(psi)))
        if not (psi_max > 0) or not math.isfinite(psi_max):
            raise ValueError("轨道 %s 的数值场异常" % spec.id)
        field = psi / psi_max
        if level is None:
            break
        edge = max(float(np.max(np.abs(field[0]))),
                   float(np.max(np.abs(field[-1]))),
                   float(np.max(np.abs(field[:, 0]))),
                   float(np.max(np.abs(field[:, -1]))),
                   float(np.max(np.abs(field[:, :, 0]))),
                   float(np.max(np.abs(field[:, :, -1]))))
        if edge < level * 0.98 or ext >= max_ext - 1e-9:
            break
        ext = min(max_ext, ext * 1.15)
    spacing = 2.0 * ext / (n_grid - 1)
    origin = np.array([-ext, -ext, -ext], dtype=np.float64)
    return field, origin, spacing, psi_max


def iso_surfaces(spec: OrbitalSpec, n: Optional[int] = None,
                 iso: Optional[float] = None):
    """在网格上求值并抽等值面，返回 ``(正相位面, 负相位面)``（**Bohr**）。

    ``n`` 为每轴网格点数（缺省按 ``spec.extent`` 自适应），``iso`` 缺省取
    ``spec.iso_hint``。两条约束必须同时满足，否则抽出来的面会"瓣尖缺一块"：

    **网格立方体要放大。** ``spec.extent`` 是按默认 iso 估的，iso 调小后波瓣
    会伸出立方体，抽出来的面被边界切断、不闭合。画布上双面渲染会把断口盖住
    看不出来，但缩略图的背面剔除会立刻露出白洞，导出的 .glb 在 PowerPoint
    里也会看到破口（实测 3d_z² 顶瓣被切掉一个弧形缺口）。这里先按 1.35 倍开
    立方体，若边界上 |ψ| 仍高于 iso（4f 的轴向长瓣就是这种），继续放大重试。

    **网格点数按尺度自适应。** 小的 1s（extent 6）用 34³ 就够，3s / 4f 的壳只
    有一两个体素厚，点数太少同样会抽出面片残缺。

    返回的 :class:`~molstudio.core.marching_cubes.IsoSurface` 顶点与 cube /
    画布使用同一套 Bohr 坐标；法线朝外、三角形为逆时针正面。
    """
    from molstudio.core.marching_cubes import CubeData, marching_cubes

    ext = float(spec.extent)
    level = float(spec.iso_hint if iso is None else iso)
    if not math.isfinite(level) or level <= 0.0:
        raise ValueError("等值面 iso 必须是正数")
    if n is None:
        n = int(min(54, max(38, round(ext * 1.8))))
    n = max(int(n), 8)
    half = ext * 1.35
    psi = None
    for _ in range(4):
        grid = np.linspace(-half, half, n)
        xx, yy, zz = np.meshgrid(grid, grid, grid, indexing="ij")
        psi = evaluate_orbital(spec, xx, yy, zz)
        peak = float(np.max(np.abs(psi))) or 1.0
        psi = psi / peak        # 与写 cube 时同一套归一化
        # 六个边界面上最大的 |ψ| 还高于 iso 说明面被切断，得继续放大
        edge = max(float(np.max(np.abs(psi[0]))),
                   float(np.max(np.abs(psi[-1]))),
                   float(np.max(np.abs(psi[:, 0]))),
                   float(np.max(np.abs(psi[:, -1]))),
                   float(np.max(np.abs(psi[:, :, 0]))),
                   float(np.max(np.abs(psi[:, :, -1]))))
        if edge < level * 0.98:
            break
        half *= 1.35

    cube = CubeData()
    cube.nx = cube.ny = cube.nz = n
    cube.origin = np.array([-half, -half, -half], dtype=np.float32)
    step = 2.0 * half / max(n - 1, 1)
    cube.dx = (step, 0.0, 0.0)
    cube.dy = (0.0, step, 0.0)
    cube.dz = (0.0, 0.0, step)
    cube.data = psi

    return (marching_cubes(cube, level, False),
            marching_cubes(cube, -level, True))


def write_orbital_cube(path, field, origin, spacing,
                       comment: str = "MolStudio atomic orbital",
                       atoms: Optional[Iterable[Sequence[float]]] = None):
    """把标量场写成标准 Gaussian cube（**Bohr** / C 序 / 每行 6 个数）。

    **默认不写原子（NATOMS = 0）**，这不是省事，而是必须：

    ``marching_cubes.compute_bounding_sphere()`` 在 ``cube.atoms`` 非空时
    只用**原子坐标**算包围球。轨道 cube 若放一个位于原点的虚拟原子，包围
    球半径会被算成 1.0 Bohr，画布相机随之把视野缩到 1 Bohr —— 2p / 3d / 4f
    的等值面全部撑出画面，看起来"只有一个灰球"。NATOMS = 0 时该函数改按
    网格八个角点算，半径正好覆盖整个立方体，视野才对。

    ``atoms`` 仍可显式传入 ``[(Z, charge, x, y, z), ...]``（Bohr），用于需要
    在轨道里标出真实原子核的场合。
    """
    field = np.asarray(field, dtype=np.float64)
    if field.ndim != 3:
        raise ValueError("场必须是三维 (nx, ny, nz)")
    nx, ny, nz = field.shape
    ox, oy, oz = (float(v) for v in origin)
    step = float(spacing)
    ats = [tuple(float(v) for v in a) for a in (atoms or ())]

    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="ascii", newline="\n") as fh:
        fh.write("%s\n" % comment)
        fh.write("MolStudio electronic-structure library | analytic orbital | "
                 "field scaled to max|psi|=1\n")
        fh.write("%5d%13.6f%13.6f%13.6f\n" % (len(ats), ox, oy, oz))
        fh.write("%5d%13.6f%13.6f%13.6f\n" % (nx, step, 0.0, 0.0))
        fh.write("%5d%13.6f%13.6f%13.6f\n" % (ny, 0.0, step, 0.0))
        fh.write("%5d%13.6f%13.6f%13.6f\n" % (nz, 0.0, 0.0, step))
        for z_num, charge, ax, ay, az in ats:
            fh.write("%5d%13.6f%13.6f%13.6f%13.6f\n"
                     % (int(z_num), float(charge), ax, ay, az))
        flat = field.ravel(order="C")
        for i in range(0, flat.size, 6):
            fh.write("".join("%13.5E" % v for v in flat[i:i + 6]) + "\n")
    return str(path)


def build_orbital_cube(path, spec: OrbitalSpec, quality: str = "medium",
                       Z: float = 1.0, iso_hint: bool = False,
                       iso: Optional[float] = None):
    """一步到位：求值 → 归一化 → 写 cube。

    ``iso`` 不为空时，cube 立方体会按该等值面自动外扩（见
    :func:`generate_field`），保证画布上抽出的等值面是闭合的；返回的
    ``extent`` 是**实际**半边长，``base_extent`` 是 ``spec.extent``。

    返回 ``dict(path, psi_max, spacing, extent, base_extent, quality,
    n_grid, iso_hint)``。
    """
    field, origin, spacing, psi_max = generate_field(
        spec, quality, Z, iso=iso)
    comment = "MolStudio %s | %s | Z=%g | q=%s" % (
        spec.id, spec.radial, Z, quality)
    write_orbital_cube(path, field, origin, spacing, comment=comment)
    n_grid = QUALITY_LEVELS[quality]
    info = {
        "path": str(path),
        "psi_max": psi_max,
        "spacing": spacing,
        # spacing = 2*extent/(n-1)，反解出实际半边长
        "extent": 0.5 * spacing * (n_grid - 1),
        "base_extent": float(spec.extent),
        "quality": quality,
        "n_grid": n_grid,
    }
    if iso_hint:
        info["iso_hint"] = float(spec.iso_hint)
    return info
