# -*- coding: utf-8 -*-
"""电子结构库数值内核精度回归：归一化、正交性、相位、cube 往返。"""
import math
import os

import numpy as np
import pytest

from molstudio.core.atomic_orbital import (
    GROUP_ORDER, QUALITY_LEVELS, build_orbital_cube, evaluate_orbital,
    generate_field, orbital_by_id, orbital_library, radial_hydrogenic,
    radial_sto, real_harmonic,
)
from molstudio.core.marching_cubes import marching_cubes, read_cube

_trapz = getattr(np, "trapezoid", None) or getattr(np, "trapz")


def _grid(extent, n):
    axis = np.linspace(-extent, extent, n)
    return np.meshgrid(axis, axis, axis, indexing="ij")


# ── 库完整性 ────────────────────────────────────────────────────────────
def test_library_integrity():
    specs = orbital_library()
    assert len(specs) == 27
    assert len({s.id for s in specs}) == len(specs)
    counts = {g: sum(1 for s in specs if s.group == g) for g in GROUP_ORDER}
    assert counts == {"s": 3, "p": 3, "d": 5, "f": 7, "hybrid": 9}
    # 组内顺序必须符合教学顺序，不能被 id 字典序搅乱
    hybrids = [s.id for s in specs if s.group == "hybrid"]
    assert hybrids == ["sp_1", "sp_2", "sp2_1", "sp2_2", "sp2_3",
                       "sp3_1", "sp3_2", "sp3_3", "sp3_4"]
    # 奇数网格保证原点有采样点
    assert all(n % 2 == 1 for n in QUALITY_LEVELS.values())
    for s in specs:
        assert s.terms and s.extent > 0 and 0 < s.iso_hint <= 0.3
        for key, _coeff in s.terms:
            assert orbital_by_id(s.id) is s
            assert key  # 角向记号非空，求值时会做真正的查表


# ── 解析值与归一化 ──────────────────────────────────────────────────────
def test_1s_matches_analytic_value():
    psi = evaluate_orbital(orbital_by_id("1s"), 0.0, 0.0, 0.0)
    assert psi == pytest.approx(1.0 / math.sqrt(math.pi), rel=1e-12)
    # 指数衰减
    p1 = evaluate_orbital(orbital_by_id("1s"), 1.0, 0.0, 0.0)
    assert p1 == pytest.approx(math.exp(-1.0) / math.sqrt(math.pi), rel=1e-12)


def test_radial_functions_normalized_and_orthogonal():
    r = np.linspace(0.0, 80.0, 200001)
    weight = r * r
    r10 = radial_hydrogenic(1, 0, r)
    r20 = radial_hydrogenic(2, 0, r)
    r21 = radial_hydrogenic(2, 1, r)
    r30 = radial_hydrogenic(3, 0, r)
    assert _trapz(r10 * r10 * weight, r) == pytest.approx(1.0, abs=2e-6)
    assert _trapz(r20 * r20 * weight, r) == pytest.approx(1.0, abs=2e-6)
    assert _trapz(r21 * r21 * weight, r) == pytest.approx(1.0, abs=2e-6)
    assert _trapz(r30 * r30 * weight, r) == pytest.approx(1.0, abs=2e-6)
    assert abs(_trapz(r10 * r20 * weight, r)) < 1e-8
    assert abs(_trapz(r10 * r30 * weight, r)) < 1e-8


def test_sto_equals_hydrogenic_for_n_eq_l_plus_1():
    """zeta = 1/(l+1) 的 STO 必须与类氢 n=l+1 径向完全一致。"""
    r = np.linspace(0.0, 30.0, 5001)
    for l, n in ((0, 1), (1, 2), (2, 3), (3, 4)):
        a = radial_hydrogenic(n, l, r)
        b = radial_sto(l, r, 1.0 / (l + 1))
        assert np.max(np.abs(a - b)) < 1e-12


def test_real_harmonics_normalized_on_sphere():
    """实球谐在球面上 ∫|Y|² dΩ = 1；不同 (l,m) 彼此正交。"""
    theta = np.linspace(0.0, math.pi, 241)
    phi = np.linspace(0.0, 2 * math.pi, 481)
    T, P = np.meshgrid(theta, phi, indexing="ij")
    ct, ph = np.cos(T), P
    weight = np.sin(T)
    for l, m in ((0, 0), (1, 0), (1, 1), (1, -1),
                 (2, 0), (2, 1), (2, -2), (3, 0), (3, 3), (3, -3)):
        y = real_harmonic(l, m, ct, ph)
        integral = _trapz(_trapz(y * y * weight, theta, axis=0), phi)
        assert integral == pytest.approx(1.0, abs=2e-3), (l, m, integral)
    y20 = real_harmonic(2, 0, ct, ph)
    y10 = real_harmonic(1, 0, ct, ph)
    cross = _trapz(_trapz(y20 * y10 * weight, theta, axis=0), phi)
    assert abs(cross) < 1e-3


@pytest.mark.parametrize("ident", [
    "1s", "2s", "2px", "3dz2", "3dxy", "4fxyz", "4fz3",
    "sp_1", "sp2_2", "sp3_1",
])
def test_full_wavefunction_normalized_3d(ident):
    spec = orbital_by_id(ident)
    e = max(spec.extent * 1.6, 20.0)
    X, Y, Z = _grid(e, 90)
    psi = evaluate_orbital(spec, X, Y, Z)
    dv = (2.0 * e / 89) ** 3
    assert float(np.sum(psi * psi) * dv) == pytest.approx(1.0, abs=4e-3)


def test_angular_orthogonality_3d():
    e, n = 22.0, 80
    X, Y, Z = _grid(e, n)
    dv = (2.0 * e / (n - 1)) ** 3
    def vec(i):
        return evaluate_orbital(orbital_by_id(i), X, Y, Z).ravel()
    for a, b in (("2px", "2py"), ("3dz2", "3dxy"),
                 ("4fz3", "4fxyz"), ("3dxz", "3dyz")):
        assert abs(float(np.dot(vec(a), vec(b)) * dv)) < 1e-4


def test_hybrid_coefficients_orthonormal():
    ao = ("s", "px", "py", "pz")
    for keys in (("sp_1", "sp_2"),
                 ("sp2_1", "sp2_2", "sp2_3"),
                 ("sp3_1", "sp3_2", "sp3_3", "sp3_4")):
        m = np.array([[dict(orbital_by_id(k).terms).get(q, 0.0) for q in ao]
                      for k in keys])
        assert np.allclose(m @ m.T, np.eye(len(keys)), atol=1e-14)
        for s in (orbital_by_id(k) for k in keys):
            # 杂化走"同一壳层"的 Slater 径向：s 与 p 分量共用 r·exp(-ζr)，
            # 否则反相小瓣会长到正瓣的七成（见 radial_sto_shell）。
            assert s.radial == "sto_shell" and s.n == 2


def test_hybrid_back_lobe_is_smaller():
    """杂化轨道的反相小瓣必须明显小于正瓣（教科书"一头大一头小"）。

    这条锁死 ``radial_sto_shell`` 的选型：若给 s 分量用 ``r^0`` 的 STO，
    sp³ 的反相瓣会长到正瓣的 0.72 —— 画出来两瓣几乎一样大，是错的。
    """
    axis = np.linspace(-25.0, 25.0, 200001)

    sp3 = orbital_by_id("sp3_1")            # 正瓣沿 (1,1,1)/√3
    u = 1.0 / math.sqrt(3.0)
    psi = evaluate_orbital(sp3, u * axis, u * axis, u * axis)
    assert -psi.min() / psi.max() == pytest.approx(0.5, abs=0.02)

    sp2 = orbital_by_id("sp2_1")            # 正瓣沿 +x
    psi = evaluate_orbital(sp2, axis, 0 * axis, 0 * axis)
    assert -psi.min() / psi.max() == pytest.approx(0.42, abs=0.03)

    sp = orbital_by_id("sp_1")              # 正瓣沿 +z
    psi = evaluate_orbital(sp, 0 * axis, 0 * axis, axis)
    assert -psi.min() / psi.max() == pytest.approx(0.27, abs=0.04)


# ── 相位与形状 ──────────────────────────────────────────────────────────
def test_phase_and_shape_conventions():
    pz = orbital_by_id("2pz")
    assert evaluate_orbital(pz, 0, 0, 1.0) > 0
    assert evaluate_orbital(pz, 0, 0, -1.0) < 0
    assert abs(evaluate_orbital(pz, 0, 0, 0.0)) < 1e-15  # 核处节点

    dz2 = orbital_by_id("3dz2")
    assert evaluate_orbital(dz2, 0, 0, 2.0) > 0
    assert evaluate_orbital(dz2, 2.0, 0, 0) < 0          # xy 圆环反相

    dxy = orbital_by_id("3dxy")
    assert evaluate_orbital(dxy, 1.0, 1.0, 0) > 0
    assert evaluate_orbital(dxy, 1.0, -1.0, 0) < 0

    # 2s 在原点为正，跨过 r = 2 a0 的径向节点后变负
    s2 = orbital_by_id("2s")
    assert evaluate_orbital(s2, 0, 0, 0) > 0
    assert evaluate_orbital(s2, 0, 0, 4.0) < 0


def test_generate_field_is_peak_normalized_and_odd_grid():
    spec = orbital_by_id("1s")
    for quality in QUALITY_LEVELS:
        field, origin, spacing, peak = generate_field(spec, quality)
        n = QUALITY_LEVELS[quality]
        assert field.shape == (n, n, n) and n % 2 == 1
        assert np.allclose(origin, -spec.extent)
        assert spacing == pytest.approx(2 * spec.extent / (n - 1))
        assert float(np.max(np.abs(field))) == pytest.approx(1.0, abs=1e-12)
        # 奇数网格正中就是 r=0，1s 峰值应精确等于解析值
        assert peak == pytest.approx(1.0 / math.sqrt(math.pi), rel=1e-12)


# ── cube 往返 + 等值面 ──────────────────────────────────────────────────
@pytest.mark.parametrize("ident", [
    "1s", "2s", "2pz", "3dz2", "4fxyz", "sp3_1",
])
def test_cube_roundtrip_and_isosurface(tmp_path, ident):
    spec = orbital_by_id(ident)
    path = str(tmp_path / (ident + ".cub"))
    info = build_orbital_cube(path, spec, "low", iso_hint=True)
    assert os.path.isfile(path) and os.path.getsize(path) > 100_000
    assert info["n_grid"] == QUALITY_LEVELS["low"]
    assert 0 < info["iso_hint"] <= 0.3

    cube = read_cube(path)
    n = info["n_grid"]
    assert cube.data.shape == (n, n, n)
    # 轨道 cube 必须 NATOMS=0：否则画布按原子坐标算包围球（半径 1 Bohr），
    # 相机把视野缩到 1 Bohr，2p/3d/4f 的等值面会被整个推出画面。
    assert cube.atoms == []
    assert np.allclose(cube.origin, -spec.extent)
    assert abs(cube.dx[0] - info["spacing"]) < 1e-5

    axis = np.linspace(-spec.extent, spec.extent, n)
    X, Y, Z = np.meshgrid(axis, axis, axis, indexing="ij")
    ref = evaluate_orbital(spec, X, Y, Z) / info["psi_max"]
    assert float(np.max(np.abs(cube.data - ref))) < 2e-5

    pos = marching_cubes(cube, 0.08, False)
    neg = marching_cubes(cube, -0.08, True)
    assert pos.vertex_count > 0
    if ident in ("1s", "2s", "3s"):
        pass  # s 轨道的正瓣为主，负瓣可有可无
    else:
        assert neg.vertex_count > 0, "非 s 轨道必须有反相瓣"


@pytest.mark.parametrize("ident", ["1s", "2pz", "3dz2", "4fz3", "sp3_1"])
def test_small_isovalue_cube_expands_until_surface_closes(tmp_path, ident):
    """iso 很小时立方体必须外扩，否则画布上 f / d 的瓣尖会被边界切掉。

    画布 cube 之前固定用 ``spec.extent``，而 4f 在 iso=0.005 时最外层等值面
    半径约 1.87 倍 —— 画布上看到的就是被切平的瓣尖。现在 ``build_orbital_cube``
    接受 iso，先把立方体扩到边界 |ψ| < iso 再写盘。
    """
    spec = orbital_by_id(ident)
    iso = 0.005
    path = str(tmp_path / (ident + "_small.cub"))
    info = build_orbital_cube(path, spec, "low", iso=iso)
    cube = read_cube(path)

    field = np.abs(cube.data)
    edge = max(field[0].max(), field[-1].max(),
               field[:, 0].max(), field[:, -1].max(),
               field[:, :, 0].max(), field[:, :, -1].max())
    assert edge < iso, "%s 在 iso=%.3f 时边界仍有 %.4g" % (ident, iso, edge)
    assert info["extent"] >= info["base_extent"]
    assert info["extent"] == pytest.approx(0.5 * info["spacing"]
                                           * (info["n_grid"] - 1))
    if ident.startswith(("4f", "3d", "sp")):
        # 这些轨道在 0.005 时伸得比基准立方体远，必须真的外扩
        assert info["extent"] > info["base_extent"] * 1.2
    if ident == "1s":
        assert info["extent"] == pytest.approx(info["base_extent"])

    # 立方体外扩后等值面必须闭合：每条边只能被两个三角形共用
    pos = marching_cubes(cube, iso, False)
    tri = np.asarray(pos.indices).reshape(-1, 3)
    edges = np.sort(np.concatenate(
        [tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]), axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    assert int((counts == 1).sum()) == 0
