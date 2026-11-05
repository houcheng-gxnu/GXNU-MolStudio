# -*- coding: utf-8 -*-
"""molstudio.core.steric（SambVca 官方算法纯计算包）回归测试。

覆盖 task-1 的 9 条验收项：单原子解析解、定向不变性、官方 nhc 算例、
.inp 往返、地图网格、auto_roles/validate、错误路径、导出、跨引擎交叉验证。

运行::

    C:\\ProgramData\\Anaconda3\\python.exe -m pytest tests/test_steric_engine.py -q

官方算例目录不存在时相关用例自动 skip（本仓库开发机上有该目录，会真跑）。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from molstudio.core.steric import (
    SambVcaJob,
    auto_roles,
    available_engines,
    compute,
    format_orientation_report,
    native_buried_volume,
    native_surfaces,
    orient_sambvca,
    parse_xyz,
    read_inp,
    result_to_json,
    radii_for_symbols,
    save_grid_csv,
    save_json,
    save_oriented_xyz,
    validate,
    write_inp,
)

EXAMPLES = Path(r"D:\steric map\sambvca_examples")
NHC_INP = EXAMPLES / "nhc.inp"
NHC_C210_INP = EXAMPLES / "nhc-C210.inp"

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


def _params_from_job(job: SambVcaJob) -> dict:
    """按官方 .inp 的 job 还原 compute 的 params 字典（面板 .inp 回填同一路径）。"""
    return {
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


def _random_rotation(seed: int = 12345) -> np.ndarray:
    """均匀随机的 3×3 **固有**旋转矩阵（det=+1，无反射）。"""
    rng = np.random.default_rng(seed)
    q, r = np.linalg.qr(rng.normal(size=(3, 3)))
    q = q * np.sign(np.diag(r))          # 让 QR 分解唯一 / 对角为正
    if np.linalg.det(q) < 0:
        q[:, -1] *= -1.0
    return q


def _synthetic_complex():
    """合成金属配合物：Fe 中心 + 两个 P + Cl + C + H。"""
    symbols = ["Fe", "P", "P", "Cl", "C", "C", "H", "H"]
    coords = np.array([
        [0.00, 0.00, 0.00],
        [2.20, 0.00, 0.00],     # 最近的配位原子
        [-1.00, 2.00, 0.00],
        [0.00, -2.10, 1.20],
        [1.50, 1.00, 1.80],
        [-1.60, -0.60, 1.70],
        [2.90, 0.40, 0.60],
        [-2.20, 2.40, 0.50],
    ], dtype=float)
    return symbols, coords


def _synthetic_params(symbols, coords, **overrides) -> dict:
    roles = auto_roles(symbols, coords)
    params = {
        **roles,
        "sphere_radius": 3.5,
        "map_radius": 3.5,
        "mesh": 0.1,
        "remove_h": True,
        "align_z": 0,
        "displacement": 0.0,
        "radii_set": "bondi-scaled",
    }
    params.update(overrides)
    return params


# ══════════════════════════════════════════════════════════════════
#  1. 单原子解析解
# ══════════════════════════════════════════════════════════════════
def test_single_atom_analytic_volume():
    """球心处单个 vdW 球（r=1.7，R=3.5）→ %VBur ≈ (r/R)³，四象限都应 > 0。"""
    atom_r = 1.7
    sphere_r = 3.5
    mesh = 0.05
    out = native_buried_volume(np.zeros((1, 3), dtype=float),
                               np.array([atom_r], dtype=float),
                               sphere_radius=sphere_r, mesh=mesh)
    analytic = (atom_r / sphere_r) ** 3 * 100.0
    assert abs(out["percent_buried"] - analytic) < 0.1, \
        f"{out['percent_buried']:.4f} vs {analytic:.4f}"
    assert len(out["quadrant_percent"]) == 4
    for name, value in out["quadrant_percent"].items():
        assert value > 0.0, f"quadrant {name} = {value}"
    # 球内没有其它原子 → 自由体积 + 埋藏体积 = 球内体素体积
    assert out["free_volume"] + out["buried_volume"] == pytest.approx(
        out["total_volume"], rel=1e-12)


# ══════════════════════════════════════════════════════════════════
#  2. 定向：轴落位 / 滚转锁定 / 旋转不变性
# ══════════════════════════════════════════════════════════════════
def test_orientation_axis_roll_and_rotation_invariance():
    """z 轴原子 → (0,0,−d)；xz 原子落在 xz 平面且 x>0；随机旋转输入结果一致。"""
    centre = np.array([1.0, 2.0, 3.0])
    coords = np.array([
        centre,
        centre + np.array([0.6, -0.4, 2.0]),      # z 轴原子（d=2.17…）
        centre + np.array([-2.4, 0.5, 0.7]),      # xz 原子（与 z 轴不平行）
        centre + np.array([1.1, 2.2, -0.9]),
    ], dtype=float)
    job = SambVcaJob(centre_atoms=[1], z_axis_atoms=[2], xz_plane_atoms=[3],
                     delete_atoms=[1], align_z=0, sphere_radius=3.5, mesh=0.1)

    oriented, info = orient_sambvca(coords, job)
    d = float(np.linalg.norm(coords[1] - centre))
    np.testing.assert_allclose(oriented[1], [0.0, 0.0, -d], atol=1e-12)
    assert oriented[2][1] == pytest.approx(0.0, abs=1e-12)
    assert oriented[2][0] > 0.0
    # 滚转被 xz 原子锁死后，xz 原子方向就是 +x
    assert math.degrees(math.atan2(oriented[2][1], oriented[2][0])) == pytest.approx(0.0, abs=1e-9)

    # 对输入坐标做随机固有旋转后，定向结果必须逐点一致。
    # （注意 roll_deg 是"对齐 z 轴之后、锁滚转之前"的中间量，依赖最短弧旋转的
    #  参考方向，本身不是旋转不变量；最终坐标与轴长/一致性才是。）
    for seed in (1, 2024, 777):
        q = _random_rotation(seed)
        rotated = coords @ q.T
        oriented_rot, info_rot = orient_sambvca(rotated, job)
        np.testing.assert_allclose(oriented_rot, oriented, atol=1e-9)
        assert info_rot.axis_length == pytest.approx(info.axis_length, abs=1e-12)
        assert info_rot.axis_consistency == pytest.approx(info.axis_consistency, abs=1e-12)


# ══════════════════════════════════════════════════════════════════
#  3. 官方 nhc 算例（%VBur 对照官方输出）
# ══════════════════════════════════════════════════════════════════
@pytest.mark.skipif(not NHC_INP.exists(), reason=f"官方算例不存在: {NHC_INP}")
def test_official_nhc_example():
    """D:\\steric map\\sambvca_examples\\nhc.inp → 官方 %VBur = 39.6。"""
    job, symbols, positions, _title = read_inp(NHC_INP)
    params = _params_from_job(job)
    result = compute(symbols, positions, params)
    assert abs(result.percent_buried - 39.5965) < 0.15
    assert abs(result.job["sphere_radius"] - 3.5) < 1e-12
    assert result.engine == "native"
    # 官方结果里三个 -z 八分区约 73–84%，+z 近 0——验证八分区投影没装反
    assert result.octant_percent["SW-z"] > 70.0
    assert result.octant_percent["NE+z"] < 5.0


@pytest.mark.skipif(not NHC_C210_INP.exists(), reason=f"官方算例不存在: {NHC_C210_INP}")
def test_official_nhc_c210_example():
    """nhc-C210.inp（含 Disp=2.1 与双原子 z 轴）→ 官方 %VBur = 34.3。"""
    job, symbols, positions, _title = read_inp(NHC_C210_INP)
    params = _params_from_job(job)
    result = compute(symbols, positions, params)
    assert abs(result.percent_buried - 34.2656) < 0.2
    assert job.displacement == pytest.approx(2.1)
    assert abs(result.orientation["displacement_shift"] + 2.1) < 1e-12


# ══════════════════════════════════════════════════════════════════
#  4. .inp 往返
# ══════════════════════════════════════════════════════════════════
@pytest.mark.skipif(not NHC_INP.exists(), reason=f"官方算例不存在: {NHC_INP}")
def test_inp_roundtrip(tmp_path):
    job, symbols, positions, _title = read_inp(NHC_INP)
    path = write_inp(tmp_path / "roundtrip.inp", job, symbols, positions,
                     title="SambVca roundtrip")
    assert path.exists() and path.stat().st_size > 0
    job2, symbols2, positions2, title2 = read_inp(path)
    assert title2 == "SambVca roundtrip"
    assert symbols2 == symbols
    np.testing.assert_allclose(positions2, positions, atol=1e-6, rtol=0)
    assert job2.delete_atoms == job.delete_atoms
    assert job2.centre_atoms == job.centre_atoms
    assert job2.z_axis_atoms == job.z_axis_atoms
    assert job2.xz_plane_atoms == job.xz_plane_atoms
    assert job2.sphere_radius == pytest.approx(job.sphere_radius)
    assert job2.displacement == pytest.approx(job.displacement, abs=1e-6)
    assert job2.mesh == pytest.approx(job.mesh)
    assert job2.remove_h == job.remove_h
    assert job2.align_z == job.align_z

    # 面板会把 result.job（dict）直接传给 write_inp —— 这条路径也必须通
    path2 = write_inp(tmp_path / "roundtrip_dict.inp", job.to_dict(), symbols,
                      positions, title="dict job")
    job3, _s3, _p3, _t3 = read_inp(path2)
    assert job3.delete_atoms == job.delete_atoms
    assert job3.centre_atoms == job.centre_atoms


# ══════════════════════════════════════════════════════════════════
#  5. 地图网格
# ══════════════════════════════════════════════════════════════════
@pytest.mark.skipif(not NHC_INP.exists(), reason=f"官方算例不存在: {NHC_INP}")
def test_map_grid_shape_nan_and_range():
    job, symbols, positions, _title = read_inp(NHC_INP)
    result = compute(symbols, positions, _params_from_job(job))
    grid = result.map
    assert grid.z.shape == (grid.y.size, grid.x.size)
    assert grid.z.shape == (71, 71)          # R=3.5, mesh=0.1 → 71×71
    assert np.all(np.diff(grid.x) > 0) and np.all(np.diff(grid.y) > 0)

    finite = grid.z[np.isfinite(grid.z)]
    assert finite.size > 0
    assert finite.min() >= -3.5 - 1e-9
    assert finite.max() <= 0.2
    assert result.color_range == pytest.approx((float(finite.min()), float(finite.max())))

    # NaN 只能出现在"该 (x,y) 上方没有 vdW 表面"的格：用 native_surfaces 的
    # ±2R 哨兵重建同一张网格，NaN 掩码必须逐格一致。
    selected = np.asarray(result.selected_atoms, dtype=int) - 1
    sel_pos = np.asarray(result.oriented_positions)[selected]
    sel_sym = [result.symbols[i] for i in selected]
    sel_radii, missing = radii_for_symbols(sel_sym, result.radii_set)
    assert not missing
    raw = native_surfaces(sel_pos, sel_radii, radius=result.map_radius, mesh=result.mesh)
    fx = np.asarray(raw["x"], dtype=float)
    fy = np.asarray(raw["y"], dtype=float)
    fz = np.asarray(raw["zmax"], dtype=float)
    xv, yv = np.unique(fx), np.unique(fy)
    rebuilt = np.full((yv.size, xv.size), np.nan, dtype=float)
    rebuilt[np.searchsorted(yv, fy), np.searchsorted(xv, fx)] = fz
    sentinel = np.abs(rebuilt) > result.map_radius + 1e-6
    np.testing.assert_array_equal(np.isnan(grid.z), sentinel)
    assert np.isnan(grid.z).sum() > 0
    assert np.isfinite(grid.z).sum() > 0


# ══════════════════════════════════════════════════════════════════
#  6. auto_roles + validate
# ══════════════════════════════════════════════════════════════════
def test_auto_roles_and_validate_on_metal_complex():
    symbols, coords = _synthetic_complex()
    roles = auto_roles(symbols, coords)
    assert set(roles) == {"centre", "z_axis", "xz", "delete"}
    assert roles["centre"] == "1"            # Fe 是第一个金属
    assert roles["delete"] == "1"            # delete 只含中心原子
    # z_axis 必须是离金属最近的非 H 原子（P1 在 2.20 Å）
    dists = np.linalg.norm(coords[1:] - coords[0], axis=1)
    non_h = [(d, i + 2) for i, (d, s) in enumerate(zip(dists, symbols[1:]))
             if s != "H"]
    nearest = min(non_h)[1]
    assert roles["z_axis"] == str(nearest)
    assert roles["xz"] and roles["xz"] != roles["z_axis"]

    err, parsed = validate(symbols, coords, _synthetic_params(symbols, coords))
    assert err is None and parsed is not None
    assert isinstance(parsed["job"], SambVcaJob)
    assert parsed["selected_atoms"] == [2, 3, 4, 5, 6]
    assert parsed["excluded_atoms"] == [1, 7, 8]

    result = compute(symbols, coords, _synthetic_params(symbols, coords))
    assert 0.0 <= result.percent_buried <= 100.0
    assert format_orientation_report(result)
    assert format_orientation_report(result, lang="en")


# ══════════════════════════════════════════════════════════════════
#  7. 错误路径
# ══════════════════════════════════════════════════════════════════
@pytest.mark.skipif(not NHC_INP.exists(), reason=f"官方算例不存在: {NHC_INP}")
def test_validate_error_paths_zh_and_en():
    _job, symbols, positions, _title = read_inp(NHC_INP)
    n = len(symbols)
    cases = {
        # 删除全部原子 → 没有原子参与计算
        "delete_all": _params(delete=f"1-{n}"),
        # 非法序号：超出范围 / 非数字
        "index_range": _params(centre="999"),
        "index_format": _params(centre="abc"),
        # 网格过密（R=3.5/mesh=0.001 → 7e9 体素）
        "grid_dense": _params(mesh=0.001),
    }
    for name, params in cases.items():
        msg_zh, parsed_zh = validate(symbols, positions, params, lang="zh")
        msg_en, parsed_en = validate(symbols, positions, params, lang="en")
        assert msg_zh and msg_zh.strip(), f"{name}: 缺少中文错误文案"
        assert msg_en and msg_en.strip(), f"{name}: 缺少英文错误文案"
        assert msg_zh != msg_en, f"{name}: zh/en 文案没有区分"
        assert parsed_zh is None and parsed_en is None
        with pytest.raises(Exception):
            compute(symbols, positions, params, lang="zh")


def test_compute_cancel_and_engine_errors():
    from molstudio.core.steric import StericCancelled, StericError

    symbols, coords = _synthetic_complex()
    params = _synthetic_params(symbols, coords)
    calls = {"n": 0}

    def should_cancel() -> bool:
        calls["n"] += 1
        return calls["n"] >= 2

    with pytest.raises(StericCancelled):
        compute(symbols, coords, params, should_cancel=should_cancel)
    with pytest.raises(StericError):
        compute(symbols, coords, params, engine="no-such-engine")


# ══════════════════════════════════════════════════════════════════
#  8. 导出
# ══════════════════════════════════════════════════════════════════
@pytest.mark.skipif(not NHC_INP.exists(), reason=f"官方算例不存在: {NHC_INP}")
def test_export_json_csv_xyz(tmp_path):
    job, symbols, positions, _title = read_inp(NHC_INP)
    result = compute(symbols, positions, _params_from_job(job))

    json_path = save_json(result, tmp_path / "result.json")
    assert json_path.exists() and json_path.stat().st_size > 0
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["percent_buried"] == pytest.approx(result.percent_buried)
    assert data["sambvca_job"]["centre_atoms"] == [22]
    assert data["map_shape"] == [71, 71]
    assert result_to_json(result)["engine"] == "native"

    csv_path = save_grid_csv(result, tmp_path / "map.csv")
    assert csv_path.exists() and csv_path.stat().st_size > 0
    csv_lines = csv_path.read_text(encoding="utf-8").splitlines()
    assert csv_lines[0] == "x,y,z"
    assert len(csv_lines) == 1 + result.map.z.size

    xyz_path = save_oriented_xyz(result, tmp_path / "oriented.xyz")
    assert xyz_path.exists() and xyz_path.stat().st_size > 0
    xyz_lines = xyz_path.read_text(encoding="utf-8").splitlines()
    assert int(xyz_lines[0]) == len(symbols)
    assert len(xyz_lines) == 2 + len(symbols)


def test_parse_xyz_roundtrip(tmp_path):
    symbols, coords = _synthetic_complex()
    path = tmp_path / "complex.xyz"
    lines = [str(len(symbols)), "synthetic"]
    for sym, (x, y, z) in zip(symbols, coords):
        lines.append(f"{sym} {x:.8f} {y:.8f} {z:.8f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    mol = parse_xyz(path)
    assert mol.symbols == symbols
    np.testing.assert_allclose(mol.positions, coords, atol=1e-8)


# ══════════════════════════════════════════════════════════════════
#  9. 跨引擎交叉验证（stericrender 可用时）
# ══════════════════════════════════════════════════════════════════
def test_cross_engine_agreement():
    if "stericrender" not in available_engines():
        pytest.skip("stericrender 不可用")
    symbols, coords = _synthetic_complex()
    params = _synthetic_params(symbols, coords)
    native = compute(symbols, coords, params, engine="native")
    other = compute(symbols, coords, params, engine="stericrender")
    assert native.engine == "native"
    assert other.engine == "stericrender"
    assert abs(native.percent_buried - other.percent_buried) < 0.1
    # 两个引擎的地图网格尺寸应一致（同一套官方网格轴）
    assert native.map.z.shape == other.map.z.shape

# ══════════════════════════════════════════════════════════════════
#  4b. .inp 半径集 / 数值精度保真（复核 P1-1 / P2-3 回归）
# ══════════════════════════════════════════════════════════════════
@pytest.mark.skipif(not NHC_INP.exists(), reason=f"官方算例不存在: {NHC_INP}")
def test_inp_radius_set_and_precision_roundtrip(tmp_path):
    """Bondi 半径集导出的 .inp 必须写 Bondi 表、且重读重算与屏幕结果一致。"""
    from dataclasses import replace

    job, symbols, positions, _title = read_inp(NHC_INP)

    # ① 半径集 bondi → 导出表是官方 Bondi 表（H 1.09 / C 1.70），不是 scaled
    job_bondi = replace(job, radii_set="bondi")
    path = write_inp(tmp_path / "bondi.inp", job_bondi, symbols, positions)
    table = {}
    for ln in path.read_text(encoding="utf-8").splitlines():
        parts = ln.split()
        if len(parts) == 2 and parts[0].isupper() and parts[0].isalpha():
            try:
                table[parts[0]] = float(parts[1])
            except ValueError:
                pass
    assert table.get("H") == pytest.approx(1.09, abs=0.001)
    assert table.get("C") == pytest.approx(1.70, abs=0.001)
    job2, symbols2, positions2, _ = read_inp(path)
    assert job2.radii_set == "bondi"
    direct = compute(symbols, positions, _params_from_job(job_bondi))
    reread = compute(symbols2, positions2, _params_from_job(job2))
    assert reread.percent_buried == pytest.approx(direct.percent_buried, abs=1e-6)

    # ② mesh / disp 不再被 .2f 量化（0.075、2.10 原样往返）
    job_prec = replace(job, mesh=0.075, displacement=2.10)
    path2 = write_inp(tmp_path / "prec.inp", job_prec, symbols, positions)
    job3, _s3, _p3, _t3 = read_inp(path2)
    assert job3.mesh == pytest.approx(0.075)
    assert job3.displacement == pytest.approx(2.10)
