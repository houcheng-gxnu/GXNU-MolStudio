# -*- coding: utf-8 -*-
"""位阻地图出图（``molstudio.core.steric.render``）与引擎 view 定向的回归测试。

覆盖 task-6 的 7 条验收项：

1. ``draw_map`` 在 700×700 画布上对官方 nhc 算例出图（两种 style × 两种 palette），
   savefig > 10 KB。
2. 默认色标 = **固定 ±map_radius**（不是数据 min/max）。
3. 圆形裁剪：圆外格点被掩成 NaN，NaN 处显白。
4. 骨架/键：``bonds()`` 判据正确、``draw_map(show_skeleton=True)`` 真的画出线/点。
5. **朝向硬回归**：引擎 nhc 地图与官方 ``nhc-TopSurface.dat`` 逐点一致（as-is），
   证明朝向/坐标没有被翻转。
6. view 定向：随机旋转 R（det=+1）→ ``orientation['mode']=='view'``、%VBur 与
   sambvca 模式不同但合理、R=I 与“球心平移不旋转”的手工结果一致。
7. ``validate`` 的 view 模式错误路径（缺 R / 非法 R，zh/en 文案对称），
   且 sambvca 模式行为不变。

运行::

    C:\\ProgramData\\Anaconda3\\python.exe -m pytest tests/test_steric_render.py -q

官方算例 / 官方 .dat 不存在时相关用例自动 skip。
"""
from __future__ import annotations

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")                       # 必须早于 pyplot：离屏出图

import matplotlib.pyplot as plt             # noqa: E402
import numpy as np                          # noqa: E402
import pytest                               # noqa: E402

from molstudio.core.steric import (         # noqa: E402
    StericError,
    compute,
    format_orientation_report,
    native_buried_volume,
    radii_for_symbols,
    read_inp,
    validate,
)
from molstudio.core.steric.render import (  # noqa: E402
    MAP_STYLES,
    MAP_STYLE_LABELS,
    PALETTES,
    PALETTE_LABELS,
    bonds,
    colormap,
    draw_map,
    draw_terrain_3d,
)

EXAMPLES = Path(r"D:\steric map\sambvca_examples")
NHC_INP = EXAMPLES / "nhc.inp"
OFFICIAL_NHC = Path(r"D:\steric map\sambvca_official\Sambvca21\Examples\nhc")
NHC_DAT = OFFICIAL_NHC / "nhc-TopSurface.dat"

BASE_PARAMS = {
    "centre": "22",
    "z_axis": "5",
    "xz": "1",
    "delete": "22",
    "sphere_radius": 3.5,
    "map_radius": 3.5,
    "mesh": 0.1,
    "remove_h": True,
    "align_z": 0,
    "displacement": 0.0,
    "radii_set": "bondi-scaled",
}


def _params(**overrides) -> dict:
    params = dict(BASE_PARAMS)
    params.update(overrides)
    return params


def _view_params(**overrides) -> dict:
    params = _params(orient_mode="view", **overrides)
    return params


def _random_rotation(seed: int = 20241028) -> np.ndarray:
    """均匀随机的 3×3 固有旋转矩阵（det = +1）。"""
    rng = np.random.default_rng(seed)
    q, r = np.linalg.qr(rng.normal(size=(3, 3)))
    q = q * np.sign(np.diag(r))
    if np.linalg.det(q) < 0:
        q[:, -1] *= -1.0
    return q


def _benzene():
    """合成算例：苯环（6 C + 6 H），用于成键判据测试。"""
    ang = np.arange(6, dtype=float) * math.pi / 3.0
    carbon = np.stack([1.39 * np.cos(ang), 1.39 * np.sin(ang),
                       np.zeros(6)], axis=1)
    hydrogen = np.stack([2.48 * np.cos(ang), 2.48 * np.sin(ang),
                         np.zeros(6)], axis=1)
    return ["C"] * 6 + ["H"] * 6, np.vstack([carbon, hydrogen])


# ══════════════════════════════════════════════════════════════════
#  fixtures：官方 nhc 只算一次
# ══════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def nhc_example():
    if not NHC_INP.exists():
        pytest.skip(f"官方算例不存在: {NHC_INP}")
    job, symbols, positions, _title = read_inp(NHC_INP)
    params = {
        "centre": ",".join(str(i) for i in job.centre_atoms),
        "z_axis": ",".join(str(i) for i in job.z_axis_atoms),
        "xz": ",".join(str(i) for i in job.xz_plane_atoms),
        "delete": ",".join(str(i) for i in job.delete_atoms),
        "sphere_radius": job.sphere_radius,
        "map_radius": job.map_radius if job.map_radius is not None else job.sphere_radius,
        "mesh": job.mesh,
        "remove_h": bool(job.remove_h),
        "align_z": job.align_z,
        "displacement": job.displacement,
        "radii_set": job.radii_set,
    }
    return symbols, positions, params


@pytest.fixture(scope="module")
def nhc_result(nhc_example):
    symbols, positions, params = nhc_example
    return compute(symbols, positions, params)


# ══════════════════════════════════════════════════════════════════
#  1. 出图：两种 style × 两种 palette，700×700，savefig > 10 KB
# ══════════════════════════════════════════════════════════════════
def test_draw_map_styles_palettes_700x700(nhc_result, tmp_path):
    for style in MAP_STYLES:
        for palette in ("sambvca", "turbo"):
            fig = plt.figure(figsize=(7.0, 7.0), dpi=100)   # 700×700 px
            try:
                ax = draw_map(fig, nhc_result, palette=palette, style=style,
                              title=f"{style}/{palette}")
                assert ax is not None
                assert ax.get_xlim() == pytest.approx((-3.71, 3.71), abs=1e-9)
                assert ax.get_ylim() == pytest.approx((-3.71, 3.71), abs=1e-9)
                out = tmp_path / f"map_{style}_{palette}.png"
                fig.savefig(out, dpi=100)
            finally:
                plt.close(fig)
            assert out.exists() and out.stat().st_size > 10_000, \
                f"{style}/{palette} 出图过小: {out.stat().st_size} B"
            assert ax.steric_style == style
            assert ax.steric_palette == palette


def test_draw_map_options_can_be_disabled(nhc_result):
    """关掉叠加层时不应画出骨架/等高线/色标。"""
    fig = plt.figure(figsize=(5.0, 5.0))
    try:
        ax = draw_map(fig, nhc_result, style="stericrender", show_contours=False,
                      show_skeleton=False, show_quadrants=False,
                      show_colorbar=False, show_axes_triad=False)
        assert len(ax.lines) == 0           # 无十字/无键/无轴指示
        assert len(ax.collections) == 0     # 无等高线、无 scatter
        assert len(fig.axes) == 1           # 无色标轴
    finally:
        plt.close(fig)


# ══════════════════════════════════════════════════════════════════
#  2. 默认色标 = 固定 ±map_radius（不是数据 min/max）
# ══════════════════════════════════════════════════════════════════
def test_default_color_range_is_fixed_plus_minus_radius(nhc_result):
    radius = float(nhc_result.map_radius)
    z = np.asarray(nhc_result.map.z, dtype=float)
    finite = z[np.isfinite(z)]
    # 数据本身明显窄于 ±R：这条断言保证下面的 clim 断言确实在验证“固定 ±R”
    assert finite.min() > -radius + 0.1
    assert finite.max() < radius - 0.1

    fig = plt.figure(figsize=(6.0, 6.0))
    try:
        ax = draw_map(fig, nhc_result, style="stericrender")
        clim = ax.images[0].get_clim()
        assert clim == pytest.approx((-radius, radius), abs=1e-12)
        assert ax.steric_color_range == pytest.approx((-radius, radius))
    finally:
        plt.close(fig)

    fig = plt.figure(figsize=(6.0, 6.0))
    try:
        ax = draw_map(fig, nhc_result, style="sambvca")
        levels = np.asarray(ax.steric_artist.levels, dtype=float)
        assert levels[0] == pytest.approx(-radius, abs=1e-9)
        assert levels[-1] == pytest.approx(radius, abs=1e-9)
        assert levels.size == 36            # 官方 0.2 Å 间距（±3.5 → 36 个边界）
        assert np.allclose(np.diff(levels), 0.2, atol=1e-9)
        # 官方风格每条等值线都是实线（matplotlib 默认把负 level 画成虚线）
        from matplotlib.contour import ContourSet
        checked = 0
        for coll in ax.collections:
            if not isinstance(coll, ContourSet) or getattr(coll, "filled", False):
                continue                       # 只看等高线（不看 contourf 填充）
            # matplotlib 默认会把负 level 画成虚线；必须显式 solid
            assert str(coll.linestyles).lower() == "solid", coll.linestyles
            checked += 1
        assert checked > 0
    finally:
        plt.close(fig)

    # 显式 color_range 必须被尊重
    fig = plt.figure(figsize=(6.0, 6.0))
    try:
        ax = draw_map(fig, nhc_result, color_range=(-1.0, 0.5))
        assert ax.images[0].get_clim() == pytest.approx((-1.0, 0.5))
    finally:
        plt.close(fig)


# ══════════════════════════════════════════════════════════════════
#  3. 圆形裁剪：圆外 NaN、NaN 显白
# ══════════════════════════════════════════════════════════════════
def test_circle_clip_masks_outside_radius(nhc_result):
    fig = plt.figure(figsize=(6.0, 6.0))
    try:
        ax = draw_map(fig, nhc_result, style="stericrender")
        x, y, zz = ax.steric_grid
        xx = x[np.newaxis, :]
        yy = y[:, np.newaxis]
        radius = float(ax.steric_radius)
        outside = (xx * xx + yy * yy) > radius ** 2 + 1e-9
        assert outside.sum() > 0
        assert np.all(np.isnan(zz[outside])), "圆外格点没有被掩成 NaN"
        original = np.asarray(nhc_result.map.z, dtype=float)
        assert np.all(np.isnan(zz[np.isnan(original)])), "原始 NaN 被填掉了"
        inside = ~outside
        assert np.isnan(zz).sum() == outside.sum() + np.isnan(original[inside]).sum()
        assert np.isfinite(zz).sum() > 0

        # imshow 的 masked 比例与裁剪后的 NaN 数一致
        arr = ax.images[0].get_array()
        assert np.ma.isMaskedArray(arr)
        assert int(np.ma.getmaskarray(arr).sum()) == int(np.isnan(zz).sum())
        # NaN 用白色（不是灰底）
        bad_rgba = ax.images[0].cmap.get_bad()
        assert np.allclose(np.asarray(bad_rgba)[:3], 1.0, atol=1e-6)
    finally:
        plt.close(fig)


# ══════════════════════════════════════════════════════════════════
#  4. 骨架 / 成键
# ══════════════════════════════════════════════════════════════════
def test_bonds_synthetic_benzene():
    symbols, coords = _benzene()
    ring = bonds(symbols, coords, selected=range(6))
    assert len(ring) == 6, f"苯环应有 6 根 C-C 键，实际 {ring}"
    for i, j in ring:
        assert 0 <= i < j < len(symbols)
        assert j < 6, "selected 之外的原子不应成键"

    heavy = [b for b in bonds(symbols, coords)]
    assert len(heavy) >= 6
    assert all(0 <= i < j < len(symbols) for i, j in heavy)

    # 退化输入：空 / 形状错 / 越界 selected 都不应崩
    assert bonds([], np.zeros((0, 3))) == []
    assert bonds(symbols, np.zeros((3, 3))) == []
    assert bonds(symbols, coords, selected=[999, -5]) == []


def test_draw_map_skeleton_artists(nhc_result):
    kwargs = dict(style="stericrender", show_contours=False, show_quadrants=False,
                  show_colorbar=False, show_axes_triad=False)
    fig = plt.figure(figsize=(5.0, 5.0))
    try:
        ax_on = draw_map(fig, nhc_result, show_skeleton=True, **kwargs)
        n_lines_on = len(ax_on.lines)
        n_coll_on = len(ax_on.collections)
        n_patch_on = len(ax_on.patches)
    finally:
        plt.close(fig)

    fig = plt.figure(figsize=(5.0, 5.0))
    try:
        ax_off = draw_map(fig, nhc_result, show_skeleton=False, **kwargs)
        assert len(ax_off.lines) == 0
        assert len(ax_off.collections) == 0
    finally:
        plt.close(fig)

    assert n_lines_on > 0, "骨架键没有画出来"
    assert n_coll_on > 0, "骨架原子 scatter 没有画出来"
    assert n_patch_on > 0, "圆框 / 角色标记没有画出来"


def test_draw_map_hides_xz_role_text_and_supports_full_molecule(nhc_result):
    """显示模式对齐 StericRender：默认球形裁切，可切换为完整分子。"""
    fig = plt.figure(figsize=(5.0, 5.0))
    try:
        ax = draw_map(fig, nhc_result, style="stericrender",
                      show_quadrants=False, show_colorbar=False,
                      show_axes_triad=False, clip_skeleton=True)
        assert "xz" not in [text.get_text() for text in ax.texts]
        assert ax.steric_molecule_clip is True
        radius = float(ax.steric_radius)
        assert ax.steric_view_radius == pytest.approx(radius)
        assert ax.get_xlim() == pytest.approx((-radius * 1.06, radius * 1.06))
    finally:
        plt.close(fig)

    fig = plt.figure(figsize=(5.0, 5.0))
    try:
        ax = draw_map(fig, nhc_result, style="stericrender",
                      show_quadrants=False, show_colorbar=False,
                      show_axes_triad=False, clip_skeleton=False)
        assert ax.steric_molecule_clip is False
        assert ax.steric_view_radius >= ax.steric_radius
        assert ax.get_xlim()[1] == pytest.approx(
            ax.steric_view_radius * 1.06)
        # 圆外原子不再统一套用圆盘 clip path。
        clipped = [
            coll for coll in ax.collections
            if getattr(coll, "get_clip_path", lambda: None)()
        ]
        assert clipped == []
    finally:
        plt.close(fig)


def test_draw_map_molecule_is_behind_translucent_surface(nhc_result, tmp_path):
    """后向球棍快照必须先于地图绘制，地图按设定透明度覆盖它。"""
    h, w = 96, 120
    yy, xx = np.mgrid[0:h, 0:w]
    bg = np.zeros((h, w, 4), dtype=np.uint8)
    bg[..., 0] = np.linspace(25, 240, w, dtype=np.uint8)[None, :]
    bg[..., 1] = np.linspace(40, 210, h, dtype=np.uint8)[:, None]
    bg[..., 2] = 80
    bg[..., 3] = np.where(((xx - w / 2) ** 2 + (yy - h / 2) ** 2)
                          < (min(h, w) * 0.42) ** 2, 255, 0).astype(np.uint8)

    fig = plt.figure(figsize=(6.0, 6.0), dpi=100)
    try:
        ax = draw_map(
            fig, nhc_result, style="stericrender", palette="sambvca",
            show_skeleton=True, show_contours=False, show_quadrants=False,
            show_colorbar=False, show_axes_triad=False, map_opacity=0.61,
            background_image=bg,
            background_extent=(-3.6, 3.6, -3.6, 3.6),
        )
        bg_artist = ax.steric_background_artist
        assert bg_artist is ax.images[0]
        assert ax.images[1] is ax.steric_artist
        assert bg_artist.get_zorder() < ax.steric_artist.get_zorder()
        assert ax.steric_map_opacity == pytest.approx(0.61)
        assert ax.steric_artist.get_alpha() == pytest.approx(0.61)
        # NaN 区透明，而不是把后方结构盖成一片白底
        bad = np.asarray(ax.steric_artist.cmap.get_bad())
        assert bad[3] == pytest.approx(0.0)

        out = tmp_path / "molecule_behind_map.png"
        fig.savefig(out, dpi=100)
        assert out.exists() and out.stat().st_size > 10_000
    finally:
        plt.close(fig)

    # 不显示结构时地图保持实色，避免单独地图被无缘无故冲淡
    fig = plt.figure(figsize=(5.0, 5.0), dpi=100)
    try:
        ax = draw_map(fig, nhc_result, show_skeleton=False, map_opacity=0.61,
                      show_contours=False, show_colorbar=False)
        assert ax.steric_map_opacity == pytest.approx(1.0)
        assert ax.steric_artist.get_alpha() == pytest.approx(1.0)
    finally:
        plt.close(fig)


# ══════════════════════════════════════════════════════════════════
#  5. 朝向硬回归：官方 nhc-TopSurface.dat 逐点一致（as-is，不翻转）
# ══════════════════════════════════════════════════════════════════
@pytest.mark.skipif(not NHC_DAT.exists(), reason=f"官方 .dat 不存在: {NHC_DAT}")
def test_official_topsurface_grid_matches_as_is(nhc_result):
    """官方 .dat 的 x 外层、y 内层写盘顺序 ⇒ reshape(d, d).T 后与引擎网格逐点一致。

    只要朝向/坐标被翻转（x↔y 或 y 取反），这里必然失败。
    """
    data = np.loadtxt(NHC_DAT)
    assert data.ndim == 2 and data.shape[1] == 3
    d = int(round(math.sqrt(data.shape[0])))
    assert d * d == data.shape[0]
    radius = float(nhc_result.map_radius)

    # 官方网格轴（x 外层、y 内层）与引擎网格轴必须完全一致
    np.testing.assert_allclose(data[::d, 0], nhc_result.map.x, atol=1e-9)
    np.testing.assert_allclose(data[:d, 1], nhc_result.map.y, atol=1e-9)
    assert data[::d, 0].min() == pytest.approx(-radius)
    assert data[::d, 0].max() == pytest.approx(radius)

    raw = data[:, 2].reshape(d, d)                  # 官方写法 z[x_idx, y_idx]
    sentinel = np.abs(raw) > radius + 1e-6          # ±2R = 无表面的哨兵
    official = np.where(sentinel, np.nan, raw).T    # → (ny, nx)，与引擎同序

    engine = np.asarray(nhc_result.map.z, dtype=float)
    assert official.shape == engine.shape == (d, d)
    np.testing.assert_array_equal(np.isnan(official), np.isnan(engine),
                                  err_msg="NaN 掩膜不一致：朝向/坐标被改动过")
    both = np.isfinite(official) & np.isfinite(engine)
    assert both.sum() > 1000
    assert np.max(np.abs(official[both] - engine[both])) < 1e-6


# ══════════════════════════════════════════════════════════════════
#  6. view 定向（按画布视角）
# ══════════════════════════════════════════════════════════════════
def test_view_orientation_random_rotation(nhc_example, nhc_result):
    symbols, positions, _ = nhc_example
    R = _random_rotation(20241028)
    assert np.linalg.det(R) == pytest.approx(1.0, abs=1e-9)
    result = compute(symbols, positions, _view_params(), view_rotation=R)

    assert result.orient_mode == "view"
    assert result.orientation["mode"] == "view"
    np.testing.assert_allclose(result.orientation["rotation_matrix"], R,
                               atol=1e-12)
    tilt = math.degrees(math.acos(max(-1.0, min(1.0, float(R[2, 2])))))
    assert result.orientation["view_tilt_deg"] == pytest.approx(tilt, abs=1e-9)
    assert result.orientation["notes"] == [["orient_view", {}]]
    assert result.orientation["warnings"] == []
    assert result.job["orient_mode"] == "view"

    # 定向后坐标 = (P - 球心) @ R.T（跳过官方三步定向、忽略 z/xz 原子）
    centre = positions[[21]].mean(axis=0)          # 官方 nhc：球心 = 22 号原子
    np.testing.assert_allclose(result.oriented_positions,
                               (positions - centre) @ R.T, atol=1e-12)

    # %VBur 与 sambvca 模式不同，但仍是合理的百分比
    assert 0.0 < result.percent_buried < 100.0
    assert abs(result.percent_buried - nhc_result.percent_buried) > 1e-6

    # 报告文案 zh/en 都提到“画布视角 / canvas view”
    report_zh = format_orientation_report(result, "zh")
    report_en = format_orientation_report(result, "en")
    assert "画布视角" in report_zh and "倾角" in report_zh
    assert "canvas view" in report_en and "view tilt" in report_en
    assert report_zh != report_en


def test_view_orientation_identity_matches_manual(nhc_example):
    """R = I 时 %VBur 必须等于“球心平移、不旋转”的手工计算结果。"""
    symbols, positions, params_nhc = nhc_example
    result = compute(symbols, positions, _view_params(), view_rotation=np.eye(3))
    centre = positions[[21]]                      # 官方 nhc：球心 = 22 号原子

    selected = np.asarray(result.selected_atoms, dtype=int) - 1
    selected_symbols = [symbols[i] for i in selected]
    radii, missing = radii_for_symbols(selected_symbols, result.radii_set)
    assert not missing
    manual = native_buried_volume(
        positions[selected] - centre, radii,
        sphere_radius=float(params_nhc["sphere_radius"]),
        mesh=float(params_nhc["mesh"]))
    assert result.percent_buried == pytest.approx(
        float(manual["percent_buried"]), abs=1e-9)
    # R = I ⇒ 顶视角倾角 0°
    assert result.orientation["view_tilt_deg"] == pytest.approx(0.0, abs=1e-12)


def test_view_mode_ignores_z_axis_and_xz(nhc_example):
    """view 模式不要求 z 轴 / xz 原子；给了也不报错、不参与定向。"""
    symbols, positions, _ = nhc_example
    params = _view_params(z_axis="", xz="")
    result = compute(symbols, positions, params, view_rotation=np.eye(3))
    assert result.orient_mode == "view"
    assert result.job["z_axis_atoms"] == []
    assert result.job["xz_plane_atoms"] == []


# ══════════════════════════════════════════════════════════════════
#  7. validate：view 模式错误路径 + sambvca 回归
# ══════════════════════════════════════════════════════════════════
def test_validate_view_mode_requires_rotation(nhc_example):
    symbols, positions, _ = nhc_example
    params = _view_params()
    msg_zh, parsed_zh = validate(symbols, positions, params, lang="zh")
    msg_en, parsed_en = validate(symbols, positions, params, lang="en")
    assert parsed_zh is None and parsed_en is None
    assert msg_zh and msg_zh.strip() and msg_en and msg_en.strip()
    assert msg_zh != msg_en
    with pytest.raises(StericError):
        compute(symbols, positions, params)                  # 缺 R


@pytest.mark.parametrize("bad", [
    np.zeros((3, 3)),                          # 行列式 = 0
    np.eye(2),                                 # 形状错
    np.full((3, 3), np.nan),                   # 非有限
    np.ones((3, 4)),                           # 形状错
])
def test_validate_view_mode_rejects_invalid_rotation(nhc_example, bad):
    symbols, positions, _ = nhc_example
    params = _view_params()
    msg_zh, parsed_zh = validate(symbols, positions, params, lang="zh",
                                 view_rotation=bad)
    msg_en, parsed_en = validate(symbols, positions, params, lang="en",
                                 view_rotation=bad)
    assert parsed_zh is None and parsed_en is None
    assert msg_zh and msg_en and msg_zh != msg_en
    assert "旋转矩阵" in msg_zh
    with pytest.raises(StericError):
        compute(symbols, positions, params, view_rotation=bad)


def test_validate_view_mode_does_not_require_z_axis(nhc_example):
    symbols, positions, _ = nhc_example
    err, parsed = validate(symbols, positions, _view_params(z_axis=""),
                           view_rotation=np.eye(3))
    assert err is None and parsed is not None
    assert parsed["orient_mode"] == "view"
    np.testing.assert_allclose(parsed["view_rotation"], np.eye(3))


def test_validate_unknown_orient_mode(nhc_example):
    symbols, positions, _ = nhc_example
    msg_zh, parsed = validate(symbols, positions,
                              _params(orient_mode="bogus"), lang="zh")
    msg_en, _ = validate(symbols, positions, _params(orient_mode="bogus"),
                         lang="en")
    assert parsed is None
    assert msg_zh and msg_en and msg_zh != msg_en


def test_validate_sambvca_mode_unchanged(nhc_example, nhc_result):
    """sambvca 模式仍要求 z 轴；orientation 增加 mode='sambvca'，其余字段不变。"""
    symbols, positions, params_nhc = nhc_example
    err, parsed = validate(symbols, positions, _params(z_axis=""), lang="zh")
    assert parsed is None and err and "z 轴" in err

    result = compute(symbols, positions, params_nhc)
    assert result.orient_mode == "sambvca"
    assert result.orientation["mode"] == "sambvca"
    assert result.job["orient_mode"] == "sambvca"
    for key in ("centre", "axis_vector", "axis_length", "axis_consistency",
                "xz_vector", "xz_length", "angle_axis_xz_deg", "roll_deg",
                "xz_projection", "xz_projection_fraction",
                "displacement_shift", "rotation_matrix", "warnings", "notes"):
        assert key in result.orientation, key
    assert result.percent_buried == pytest.approx(nhc_result.percent_buried)
    report = format_orientation_report(result, "zh")
    assert "SambVca 定向诊断" in report


# ══════════════════════════════════════════════════════════════════
#  8. 调色板 / 3D 地形（附加冒烟测试）
# ══════════════════════════════════════════════════════════════════
def test_palettes_and_colormap_api():
    assert set(MAP_STYLES) == {"stericrender", "sambvca"}
    assert "sambvca" in PALETTES and len(PALETTES["sambvca"]) == 11
    for key in PALETTES:
        assert key in PALETTE_LABELS, f"{key} 缺少 zh/en 显示名"
        zh, en = PALETTE_LABELS[key]
        assert zh.strip() and en.strip()
    for key in MAP_STYLES:
        zh, en = MAP_STYLE_LABELS[key]
        assert zh.strip() and en.strip()

    cmap = colormap("sambvca")
    assert cmap.N == 256
    assert np.allclose(cmap(0.0)[:3], np.asarray(PALETTES["sambvca"][0]) / 255.0,
                       atol=1e-6)
    assert np.allclose(cmap(1.0)[:3], np.asarray(PALETTES["sambvca"][-1]) / 255.0,
                       atol=1e-6)
    assert colormap("SambVca").N == cmap.N          # 大小写不敏感
    with pytest.raises(KeyError):
        colormap("definitely-not-a-palette")


def test_draw_terrain_3d_smoke(nhc_result, tmp_path):
    fig = plt.figure(figsize=(7.0, 7.0), dpi=100)
    try:
        ax = draw_terrain_3d(fig, nhc_result, palette="sambvca",
                             show_contours=True, title="3D")
        assert ax.name == "3d"
        assert ax.steric_color_range == pytest.approx(
            (-float(nhc_result.map_radius), float(nhc_result.map_radius)))
        out = tmp_path / "terrain3d.png"
        fig.savefig(out, dpi=100)
    finally:
        plt.close(fig)
    assert out.exists() and out.stat().st_size > 10_000
