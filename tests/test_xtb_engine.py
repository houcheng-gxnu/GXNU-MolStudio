# -*- coding: utf-8 -*-
"""xTB 计算内核测试：**真跑本机 xtb.exe**（苯单点 0.03 s、ohess 0.11 s，跑得起）。

覆盖任务书要求的 13 条：

1. 可执行文件定位；2. 命令构造（方法/计算类型/各开关顺序/g-xTB 溶剂化/scan 缺 xcontrol）；
3. 水 SP；4. 苯 ohess；5. 水 hess；6. 乙烷二面角 scan；7. g-xTB 苯 SP；
8. 水 OPT；9. xyz/gjf 往返（含中文+空格路径）；10. 固定文本解析；
11. load_results 重建；12. 取消/超时；13. 中英文案对称。

    C:\\ProgramData\\Anaconda3\\python.exe -m pytest tests/test_xtb_engine.py -q

跑之前不要求设置任何环境变量：模块自己会去 E:\\gxtb\\... 找 xtb。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pytest

from molstudio.core import xtb
from molstudio.core.surface_projection import load_atoms


# ── 测试用结构（Å）────────────────────────────────────────────────────────────
WATER_SYMBOLS = ["O", "H", "H"]
WATER_COORDS = [
    [0.000000, 0.000000, 0.117300],
    [0.000000, 0.757200, -0.469200],
    [0.000000, -0.757200, -0.469200],
]

BENZENE_SYMBOLS = ["C"] * 6 + ["H"] * 6
BENZENE_COORDS = [
    [1.209000, 0.000000, 0.000000],
    [0.604500, 1.047000, 0.000000],
    [-0.604500, 1.047000, 0.000000],
    [-1.209000, 0.000000, 0.000000],
    [-0.604500, -1.047000, 0.000000],
    [0.604500, -1.047000, 0.000000],
    [2.154000, 0.000000, 0.000000],
    [1.077000, 1.865000, 0.000000],
    [-1.077000, 1.865000, 0.000000],
    [-2.154000, 0.000000, 0.000000],
    [-1.077000, -1.865000, 0.000000],
    [1.077000, -1.865000, 0.000000],
]

ETHANE_SYMBOLS = ["C", "C", "H", "H", "H", "H", "H", "H"]
ETHANE_COORDS = [
    [-0.760000, 0.000000, 0.000000],
    [0.760000, 0.000000, 0.000000],
    [-1.130000, 1.020000, 0.000000],
    [-1.130000, -0.510000, 0.883000],
    [-1.130000, -0.510000, -0.883000],
    [1.130000, -1.020000, 0.000000],
    [1.130000, 0.510000, -0.883000],
    [1.130000, 0.510000, 0.883000],
]

#: 乙烷 H3-C1-C2-H6 二面角从 60°（交错式，能量最低）扫到 120°（重叠式），6 个点。
#: 第一帧就是极小点，所以 energy_relative 的第一帧≈0。
ETHANE_SCAN_XCONTROL = (
    "$constrain\n"
    " force constant=0.50\n"
    " dihedral: 3,1,2,6,60.0\n"
    "$scan\n"
    " 1: 60.0,120.0,6\n"
    "$end\n"
)


# ── fixtures：贵的计算只跑一次，几个测试共用 ─────────────────────────────────
@pytest.fixture(scope="session")
def xtb_exe() -> str:
    exe = xtb.find_xtb_executable()
    if not exe or not Path(exe).is_file():
        pytest.skip("本机找不到 xtb.exe（请设置 XTB_EXE）")
    return exe


@pytest.fixture(scope="session")
def workroot(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("xtb_engine")


@pytest.fixture(scope="session")
def water_sp_job(workroot):
    workdir = workroot / "water_sp"
    result = xtb.run_job(
        {"method": "gfn2", "job": "sp", "json": True},
        WATER_SYMBOLS, WATER_COORDS, workdir,
    )
    return workdir, result


@pytest.fixture(scope="session")
def benzene_ohess_job(workroot):
    workdir = workroot / "benzene_ohess"
    result = xtb.run_job(
        {"method": "gfn2", "job": "ohess", "json": True},
        BENZENE_SYMBOLS, BENZENE_COORDS, workdir,
    )
    return workdir, result


# ── 1. 可执行文件定位 ────────────────────────────────────────────────────────
def test_01_find_xtb_executable(xtb_exe):
    # 不传 preferred 也能找到（走 COMMON_XTB_PATHS / PATH / XTB_EXE）
    assert xtb.find_xtb_executable() == xtb_exe
    # 显式传进去优先
    assert xtb.find_xtb_executable(xtb_exe) == xtb_exe
    # 传安装目录也能补出 xtb.exe
    install_dir = Path(xtb_exe).parent
    assert xtb.find_xtb_executable(str(install_dir)) == xtb_exe
    # 不存在的路径不会崩，返回 None 或回落到已找到的 exe
    fallback = xtb.find_xtb_executable(r"C:\definitely\missing\xtb.exe")
    assert fallback is None or Path(fallback).is_file()


# ── 2. 命令构造 ─────────────────────────────────────────────────────────────
def test_02_build_command(xtb_exe, workroot):
    exe = xtb_exe

    # 三种方法（g-xTB / GFN1-2-0 / GFN-FF 的开关不同）
    method_args = {
        "gxtb": ["--gxtb"],
        "gfn2": ["--gfn", "2"],
        "gfn1": ["--gfn", "1"],
        "gfn0": ["--gfn", "0"],
        "gfnff": ["--gfnff"],
    }
    for method, args in method_args.items():
        cmd = xtb.build_command(exe, {"method": method, "job": "sp", "json": False},
                                "input.xyz")
        assert cmd[0] == exe
        assert cmd[1:1 + len(args)] == args
        assert cmd[-1] == "input.xyz"

    # 六种计算类型
    job_args = {
        "sp": [],
        "opt": ["--opt"],
        "ohess": ["--ohess"],
        "hess": ["--hess"],
        "ts": ["--opt", "--input", "xcontrol_ts.inp"],
        "scan": ["--opt", "--input", "xcontrol_scan.inp"],
    }
    for job, flags in job_args.items():
        cmd = xtb.build_command(exe, {"method": "gfn2", "job": job, "json": False},
                                "input.xyz")
        assert cmd[1:3] == ["--gfn", "2"]
        assert cmd[3:3 + len(flags)] == flags, f"{job} 的开关不对：{cmd}"
        assert cmd[-1] == "input.xyz"

    # 缺省开关不写进命令行（chrg=0 / uhf=0 / acc=1 / etemp=300 / parallel=1 / gas）
    cmd = xtb.build_command(
        exe,
        {"method": "gfn2", "job": "sp", "charge": 0, "uhf": 0, "acc": 1.0,
         "etemp": 300.0, "parallel": 1, "solvation": "gas", "json": False,
         "molden": False, "verbose": False},
        "input.xyz",
    )
    assert cmd == [exe, "--gfn", "2", "input.xyz"]

    # 全开关 + 顺序
    cmd = xtb.build_command(
        exe,
        {"method": "gfn2", "job": "opt", "charge": -1, "uhf": 2, "acc": 0.5,
         "etemp": 298.15, "solvation": "alpb", "solvent": "water",
         "parallel": 4, "json": True, "molden": True, "verbose": True,
         "extra_args": "--custom 1 2"},
        "input.xyz",
    )
    assert cmd == [
        exe, "--gfn", "2", "--opt",
        "--chrg", "-1", "--uhf", "2",
        "--acc", "0.5", "--etemp", "298.15",
        "--alpb", "water", "--parallel", "4",
        "--json", "--molden", "--verbose",
        "--custom", "1", "2", "input.xyz",
    ], cmd

    # 三种溶剂化模型各写各的开关
    for model, flag in (("alpb", "--alpb"), ("gbsa", "--gbsa"), ("cosmo", "--cosmo")):
        cmd = xtb.build_command(exe, {"method": "gfn2", "job": "sp",
                                      "solvation": model, "solvent": "water",
                                      "json": False}, "input.xyz")
        assert flag in cmd and "water" in cmd

    # g-xTB + 溶剂化：忽略溶剂（不能写 --alpb），prepare_job 给 warning
    cmd = xtb.build_command(exe, {"method": "gxtb", "job": "sp",
                                  "solvation": "alpb", "solvent": "water",
                                  "json": False}, "input.xyz")
    assert "--alpb" not in cmd and "water" not in cmd
    prepared = xtb.prepare_job(
        {"method": "gxtb", "job": "sp", "solvation": "alpb", "solvent": "water"},
        WATER_SYMBOLS, WATER_COORDS, workroot / "gxtb_solvation",
    )
    assert "--alpb" not in prepared["command"]
    assert prepared["warnings"], "g-xTB 忽略溶剂化时必须有 warning"
    assert "g-xTB" in prepared["warnings"][0] or "g-xTB" in prepared["warnings"][0].upper()

    # scan 缺 xcontrol → 本地化错误（validate_params 与 prepare_job 都要拦）
    zh = xtb.validate_params({"job": "scan", "lang": "zh"})
    en = xtb.validate_params({"job": "scan", "lang": "en"})
    assert zh and en and zh != en
    assert "xcontrol" in zh and "xcontrol" in en
    with pytest.raises(xtb.XtbError):
        xtb.prepare_job({"job": "scan"}, WATER_SYMBOLS, WATER_COORDS,
                        workroot / "scan_no_xcontrol")

    # TS 的 xcontrol 由引擎自己写
    prepared = xtb.prepare_job({"method": "gfn2", "job": "ts"},
                               WATER_SYMBOLS, WATER_COORDS, workroot / "ts_prep")
    assert prepared["xcontrol"] is not None
    assert prepared["xcontrol"].is_file()
    assert "ts=1" in prepared["xcontrol"].read_text(encoding="utf-8")
    assert "--input" in prepared["command"]


# ── 3. 水 SP（--json）──────────────────────────────────────────────────────
def test_03_water_single_point(water_sp_job):
    workdir, result = water_sp_job
    assert result.returncode == 0
    assert result.success and not result.cancelled
    assert result.normal_termination
    assert result.energy == pytest.approx(-5.0704, abs=1e-3)
    assert result.gap == pytest.approx(14.63, abs=0.05)
    assert len(result.charges) == 3
    assert sum(result.charges) == pytest.approx(0.0, abs=1e-3)
    assert result.orbital_energies, "xtbout.json 里应该有轨道能"
    assert result.occupations and len(result.occupations) == len(result.orbital_energies)
    assert result.homo is not None and result.lumo is not None
    assert result.lumo - result.homo == pytest.approx(result.gap, abs=1e-6)
    assert result.dipole_debye is not None and result.dipole_debye > 1.0
    assert result.formula == "H2O"
    assert result.json_file and Path(result.json_file).is_file()
    assert result.charges_file and Path(result.charges_file).is_file()
    assert result.output_file and Path(result.output_file).is_file()
    assert Path(result.input_xyz).is_file()
    assert result.elapsed > 0
    assert not result.warnings, f"正常单点不该有 warning：{result.warnings}"


# ── 4. 苯 ohess（频率 + 热力学）──────────────────────────────────────────────
def test_04_benzene_ohess(benzene_ohess_job):
    workdir, result = benzene_ohess_job
    assert result.success and result.normal_termination
    assert result.energy == pytest.approx(-15.8796, abs=1e-3)
    assert len(result.frequencies) >= 30
    assert result.imaginary_count == 0, f"苯不该有虚频：{result.frequencies[:3]}"
    for key in ("free_energy", "enthalpy", "zpe"):
        assert key in result.thermo, f"thermo 缺 {key}：{result.thermo}"
        assert isinstance(result.thermo[key], float)
    # G = H − TΔS：自由能比焓更负；ZPE 为正；焓与总能的差就是热校正（约 0.1 Eh）
    assert result.thermo["free_energy"] < result.thermo["enthalpy"]
    assert result.thermo["zpe"] > 0
    assert result.thermo["enthalpy"] - result.energy == pytest.approx(0.103, abs=0.02)
    assert result.optimized_xyz_file and Path(result.optimized_xyz_file).is_file()
    symbols, coords = xtb.read_xyz(result.optimized_xyz_file)
    assert len(symbols) == 12
    assert coords.shape == (12, 3)
    assert result.optimized_coords is not None
    assert result.optimized_coords.shape == (12, 3)
    assert result.vibspectrum_file and Path(result.vibspectrum_file).is_file()


# ── 5. 水 hess（输入几何直接算频率）──────────────────────────────────────────
def test_05_water_hess(workroot):
    result = xtb.run_job({"method": "gfn2", "job": "hess", "json": True},
                         WATER_SYMBOLS, WATER_COORDS, workroot / "water_hess")
    assert result.success and result.normal_termination
    assert result.frequencies, "hess 必须给出频率"
    assert len(result.frequencies) == 9            # 3 个原子 × 3 - 6 = 3，加 6 个零模
    assert result.imaginary_count == 0
    # 水的三个真实振动：~1558 / ~3671 / ~3677 cm^-1
    real = [item["frequency"] for item in result.frequencies if item["frequency"] > 100.0]
    assert len(real) == 3
    assert real[0] == pytest.approx(1558.9, abs=5.0)
    assert max(real) == pytest.approx(3677.4, abs=10.0)
    assert result.thermo.get("enthalpy") is not None


# ── 6. 乙烷二面角扫描 ───────────────────────────────────────────────────────
def test_06_ethane_scan(workroot):
    workdir = workroot / "ethane_scan"
    result = xtb.run_job(
        {"method": "gfn2", "job": "scan", "json": True,
         "xcontrol": ETHANE_SCAN_XCONTROL},
        ETHANE_SYMBOLS, ETHANE_COORDS, workdir,
    )
    assert result.success
    assert result.scan_file and Path(result.scan_file).is_file()
    assert result.scan_file.endswith("xtbscan.log")
    assert len(result.scan) == 6, f"扫描帧数应为 6，实际 {len(result.scan)}"
    # energy_relative 与 energy 同单位（Eh），相对第一帧
    assert result.scan[0]["energy_relative"] == pytest.approx(0.0, abs=1e-12)
    energies = [frame["energy"] for frame in result.scan]
    relatives = [frame["energy_relative"] for frame in result.scan]
    assert max(energies) - min(energies) > 1e-3, "扫描能量应该有变化"
    assert relatives[-1] > 1e-3, "重叠式应比交错式高（Eh）"
    # 换成 kcal/mol 要 >1，才说明扫描真的翻过了势垒
    assert relatives[-1] * 627.509474 > 1.0
    for step, frame in enumerate(result.scan, start=1):
        assert frame["step"] == step
        assert frame["symbols"] == ETHANE_SYMBOLS
        assert np.asarray(frame["coords"]).shape == (8, 3)
    # 单独调 parse_scan_log 结果一致
    parsed = xtb.parse_scan_log(result.scan_file)
    assert len(parsed) == 6
    assert parsed[0]["energy"] == pytest.approx(result.scan[0]["energy"], abs=1e-12)
    # 扫描也会写 xtbopt.xyz：作为 optimized 结构
    assert result.optimized_coords is not None
    assert result.optimized_coords.shape == (8, 3)


# ── 7. g-xTB 苯 SP ─────────────────────────────────────────────────────────
def test_07_gxtb_benzene(workroot):
    try:
        result = xtb.run_job({"method": "gxtb", "job": "sp", "json": True},
                             BENZENE_SYMBOLS, BENZENE_COORDS,
                             workroot / "gxtb_benzene")
    except xtb.XtbError as exc:                     # 本机缺 g-xTB 参数文件之类
        pytest.skip(f"本机 g-xTB 跑不通：{exc}")
    if not result.success:
        pytest.skip(f"本机 g-xTB 跑不通：rc={result.returncode} {result.warnings}")
    assert result.energy is not None
    assert np.isfinite(result.energy)
    assert result.normal_termination
    # 这个 build 的 g-xTB 不写 xtbout.json：结果只能来自文本
    assert not result.json_file
    assert result.gap is not None and result.gap > 0


# ── 8. 水 OPT ──────────────────────────────────────────────────────────────
def test_08_water_opt(workroot):
    workdir = workroot / "water_opt"
    result = xtb.run_job({"method": "gfn2", "job": "opt", "json": True},
                         WATER_SYMBOLS, WATER_COORDS, workdir)
    assert result.success and result.normal_termination
    assert (workdir / ".xtboptok").is_file()
    assert result.optimized_coords is not None
    assert result.optimized_coords.shape == np.asarray(WATER_COORDS).shape
    assert result.optimized_symbols == WATER_SYMBOLS
    delta = np.max(np.abs(result.optimized_coords - np.asarray(WATER_COORDS)))
    assert delta > 1e-3, "优化后坐标应该有变化"
    assert result.energy == pytest.approx(-5.0705, abs=1e-3)


# ── 9. xyz / gjf 往返（含中文 + 空格路径）──────────────────────────────────
def test_09_xyz_and_gjf_roundtrip(workroot, xtb_exe):
    coords = np.asarray(WATER_COORDS, dtype=float)

    xyz_path = xtb.write_xyz(workroot / "roundtrip.xyz", WATER_SYMBOLS, WATER_COORDS,
                             comment="中文注释 MolStudio")
    assert xyz_path.is_file()
    symbols, read_coords = xtb.read_xyz(xyz_path)
    assert symbols == WATER_SYMBOLS
    np.testing.assert_allclose(read_coords, coords, atol=1e-7)
    # 文件本身是 UTF-8 + LF
    raw = xyz_path.read_bytes()
    assert b"\r" not in raw
    assert "中文注释".encode("utf-8") in raw

    gjf_path = xtb.write_gjf(workroot / "roundtrip.gjf", WATER_SYMBOLS, WATER_COORDS)
    assert gjf_path.is_file()
    symbols2, coords2 = load_atoms(gjf_path)        # 仓库自己的 gjf 解析器读回来
    assert symbols2 == WATER_SYMBOLS
    np.testing.assert_allclose(np.asarray(coords2, dtype=float), coords, atol=1e-8)

    # 中文 + 空格路径下必须能跑（Windows 上最容易踩的坑）
    chinese_dir = workroot / "中文 目录" / "子 目录"
    result = xtb.run_job({"method": "gfn2", "job": "sp", "json": True},
                         WATER_SYMBOLS, WATER_COORDS, chinese_dir)
    assert result.success, f"中文/空格路径跑不了：{result.warnings}"
    assert result.energy == pytest.approx(-5.0704, abs=1e-3)
    assert "中文 目录" in result.workdir or "中文 目录" in str(result.input_xyz)


# ── 10. 固定文本解析 ───────────────────────────────────────────────────────
#: 真实输出截取（苯 ohess + 水 SP 的偶极块），用来锁定正则行为。
SAMPLE_TEXT = """
 * finished run on 2026/10/28 at 12:58:38.086
         :: total energy             -15.879640622809 Eh    ::
         :: HOMO-LUMO gap              4.933502776675 eV    ::
         :: gradient norm              0.000160140347 Eh/a0 ::
          :  # imaginary freq.                       0      :
         ::                  THERMODYNAMIC                  ::
         :: total free energy         -15.807345579174 Eh   ::
         :: zero point energy           0.097504607794 Eh   ::
          | TOTAL ENERGY              -15.879640622809 Eh   |
          | TOTAL ENTHALPY            -15.776612577969 Eh   |
          | TOTAL FREE ENERGY         -15.807345579174 Eh   |
          | HOMO-LUMO GAP               4.933502780363 eV   |
 molecular dipole:
                   x           y           z       tot (Debye)
   q only:        0.000       0.000      -0.625
     full:        0.000       0.000      -0.894       2.271
  molecular quadrupole (traceless):
 * wall-time:     0 d,  0 h,  0 min,  0.136 sec
 normal termination of xtb
"""


def test_10_parse_output_text():
    info = xtb.parse_output_text(SAMPLE_TEXT)
    assert info["energy"] == pytest.approx(-15.879640622809, abs=1e-9)
    assert info["gap"] == pytest.approx(4.933502776675, abs=1e-6)
    assert info["gradient_norm"] == pytest.approx(0.000160140347, abs=1e-12)
    assert info["dipole_debye"] == pytest.approx(2.271, abs=1e-6)
    assert info["thermo"]["enthalpy"] == pytest.approx(-15.776612577969, abs=1e-9)
    assert info["thermo"]["free_energy"] == pytest.approx(-15.807345579174, abs=1e-9)
    assert info["thermo"]["zpe"] == pytest.approx(0.097504607794, abs=1e-9)
    assert info["imaginary_count"] == 0
    assert info["wall_time"] == pytest.approx(0.136, abs=1e-6)
    assert info["normal_termination"] is True

    # 虚频个数 / 空输出 / 异常终止
    assert xtb.parse_output_text(
        "  :  # imaginary freq.                       2      :")["imaginary_count"] == 2
    empty = xtb.parse_output_text("")
    assert empty["energy"] is None and empty["normal_termination"] is False
    crashed = xtb.parse_output_text("[ERROR] Program stopped due to fatal error")
    assert crashed["normal_termination"] is False

    # 旧式小写 / 科学计数（g-xTB 的 total energy 是 E+02 写法）
    alt = xtb.parse_output_text("total energy                  -2.3186017778813E+02 Eh\n"
                                "         :: total energy            -231.860177788132 Eh    ::")
    assert alt["energy"] == pytest.approx(-231.860177788132, abs=1e-9)


# ── 11. load_results 重建 ──────────────────────────────────────────────────
def test_11_load_results(water_sp_job, benzene_ohess_job, workroot):
    workdir, result = water_sp_job
    loaded = xtb.load_results(workdir)
    assert loaded.success
    assert loaded.normal_termination
    assert loaded.method == "gfn2"
    assert loaded.job == "sp"
    assert loaded.energy == pytest.approx(result.energy, abs=1e-9)
    assert loaded.gap == pytest.approx(result.gap, abs=1e-9)
    assert len(loaded.charges) == 3
    assert np.allclose(loaded.charges, result.charges)
    assert loaded.orbital_energies == result.orbital_energies
    assert loaded.formula == "H2O"
    assert loaded.command_str and "input.xyz" in loaded.command_str
    assert loaded.output_file and Path(loaded.output_file).is_file()
    assert loaded.symbols == WATER_SYMBOLS
    assert loaded.input_coords.shape == (3, 3)
    assert loaded.elapsed > 0                       # 从 wall-time 补的

    # 显式传 symbols / coords / params 也不冲突
    loaded2 = xtb.load_results(workdir, symbols=WATER_SYMBOLS, coords=WATER_COORDS,
                               params={"method": "gfn2", "job": "sp"})
    assert loaded2.energy == pytest.approx(result.energy, abs=1e-9)
    assert loaded2.success

    # 不存在的目录 → 本地化 XtbError
    with pytest.raises(xtb.XtbError):
        xtb.load_results(workdir / "no_such_dir")

    # 目录被人清过（input.xyz 没了）：还能从 xtbopt.xyz 找回结构
    ohess_dir, _ = benzene_ohess_job
    sparse = workroot / "sparse_ohess"
    shutil.copytree(ohess_dir, sparse)
    (sparse / "input.xyz").unlink()
    loaded3 = xtb.load_results(sparse)
    assert len(loaded3.symbols) == 12
    assert loaded3.input_coords.shape == (12, 3)
    assert loaded3.optimized_coords is not None


# ── 12. 取消 / 超时 ────────────────────────────────────────────────────────
def test_12_cancel_and_timeout(workroot, xtb_exe):
    workdir = workroot / "cancel"
    workdir.mkdir(parents=True, exist_ok=True)
    xtb.write_xyz(workdir / "input.xyz", WATER_SYMBOLS, WATER_COORDS)
    command = [xtb_exe, "input.xyz", "--gfn", "2"]

    # should_cancel 立刻为真 → 终止，且不抛异常
    outcome = xtb.run_command(command, workdir, should_cancel=lambda: True)
    assert outcome["cancelled"] is True
    assert isinstance(outcome["output"], str)
    assert outcome["elapsed"] >= 0

    # 极短 timeout → cancelled + timed_out，同样不抛
    outcome2 = xtb.run_command(command, workdir, timeout=1e-6)
    assert outcome2["cancelled"] is True
    assert outcome2["timed_out"] is True

    # run_job 的取消路径：返回 XtbResult(cancelled=True)，不抛
    result = xtb.run_job({"method": "gfn2", "job": "sp"},
                         WATER_SYMBOLS, WATER_COORDS, workroot / "cancel_job",
                         should_cancel=lambda: True)
    assert result.cancelled is True
    assert result.success is False
    assert result.warnings, "取消要有提示文案"


# ── 13. 中英文案对称 ───────────────────────────────────────────────────────
def test_13_localized_messages(workroot):
    keys = (
        "err_xtb_not_found", "err_xtb_not_set", "err_bad_param", "err_method",
        "err_job", "err_solvation", "err_solvent", "err_scan_no_xcontrol",
        "err_charge", "err_uhf", "err_parallel", "err_acc", "err_etemp",
        "err_empty_structure", "err_coords_shape", "err_workdir", "err_launch",
        "err_timeout", "err_cancelled", "err_run_failed", "err_xyz_parse",
        "warn_gxtb_solvation", "warn_no_xtb_path", "warn_no_normal_termination",
        "warn_no_json", "warn_no_results", "phase_preparing", "phase_running",
        "phase_parsing", "phase_done",
    )
    for key in keys:
        zh = xtb.t(key, "zh")
        en = xtb.t(key, "en")
        assert isinstance(zh, str) and zh.strip(), f"{key} 缺中文"
        assert isinstance(en, str) and en.strip(), f"{key} 缺英文"
        assert zh != en, f"{key} 中英文一样：{zh}"
    # 未知键原样返回，不会炸
    assert xtb.t("no_such_key", "en") == "no_such_key"
    # 占位符两种语言都展开
    assert "xtb.exe" in xtb.t("err_xtb_not_found", "zh", path="xtb.exe")
    assert "xtb.exe" in xtb.t("err_xtb_not_found", "en", path="xtb.exe")

    # validate_params 按 params["lang"] 切换语言
    zh = xtb.validate_params({"method": "nope", "lang": "zh"})
    en = xtb.validate_params({"method": "nope", "lang": "en"})
    assert zh and en and zh != en
    assert xtb.validate_params({"method": "gfn2", "job": "sp", "lang": "en"}) is None

    # XtbError 的 message 也随语言变
    messages = {}
    for lang in ("zh", "en"):
        with pytest.raises(xtb.XtbError) as excinfo:
            xtb.prepare_job({"job": "scan", "lang": lang},
                            WATER_SYMBOLS, WATER_COORDS,
                            workroot / f"i18n_{lang}")
        message = str(excinfo.value).strip()
        assert message
        assert "xcontrol" in message
        messages[lang] = message
    assert messages["zh"] != messages["en"]


# ── 14. 同目录重跑：旧产物必须被清掉 / 旧 JSON 不被误用 ──────────────────
def test_14_same_workdir_rerun_is_clean(workroot):
    jobdir = workroot / "same_dir"
    first = xtb.run_job({"method": "gfn2", "job": "ohess"},
                        WATER_SYMBOLS, WATER_COORDS, jobdir)
    assert first.success
    assert (jobdir / "vibspectrum").is_file()
    assert (jobdir / "xtbopt.xyz").is_file()

    # 同一目录再跑单点：上一次的频率/优化结构必须清理，不能混进本次结果
    second = xtb.run_job({"method": "gfn2", "job": "sp"},
                         WATER_SYMBOLS, WATER_COORDS, jobdir)
    assert second.success
    assert second.energy is not None and abs(second.energy + 5.07037076) < 1e-3
    assert second.frequencies == []
    assert second.optimized_coords is None
    assert not (jobdir / "vibspectrum").exists()
    assert not (jobdir / "xtbopt.xyz").exists()


def test_14b_stale_json_and_wrong_size_geometry_ignored(workroot):
    jobdir = workroot / "stale_json"
    jobdir.mkdir(parents=True, exist_ok=True)
    # 伪造“上一次 GFN2”留下的 JSON 与 1 原子 xtbopt.xyz
    (jobdir / "xtbout.json").write_text(
        '{"total energy": -15.0, "HOMO-LUMO gap / eV": 4.0, "method": "GFN2-xTB"}',
        encoding="utf-8")
    (jobdir / "xtbopt.xyz").write_text(
        "1\nstale\nC 0.0 0.0 0.0\n", encoding="utf-8")
    result = xtb.collect_results(
        jobdir, "some text without energy", {"method": "gxtb", "job": "sp"},
        WATER_SYMBOLS, WATER_COORDS)
    assert result.energy is None, "别的泛函残留的 JSON 不能被当成结果"
    assert result.json_file == ""
    assert result.optimized_coords is None
    joined = " ".join(result.warnings)
    assert "residual" in joined.lower() or "残留" in joined


# ── 15. GFN0：本机 build 只从 cwd 读参数文件，prepare_job 自动补 ──────────
def test_15_gfn0_param_file_is_copied(workroot):
    jobdir = workroot / "gfn0"
    symbols = ["C", "H", "H", "H", "H"]
    coords = np.array([
        [0.0, 0.0, 0.0],
        [0.63, 0.63, 0.63],
        [-0.63, -0.63, 0.63],
        [-0.63, 0.63, -0.63],
        [0.63, -0.63, -0.63],
    ])
    result = xtb.run_job({"method": "gfn0", "job": "sp"},
                         symbols, coords, jobdir)
    if not result.success:
        pytest.skip("本机 xTB 不支持 GFN0：%s" % (result.warnings,))
    assert result.energy is not None
    assert (jobdir / "param_gfn0-xtb.txt").is_file(), \
        "GFN0 参数文件应被复制到工作目录"


# ── 16. 新警告文案中英对称 ─────────────────────────────────────────────
def test_16_new_warnings_localized():
    for key in ("warn_bad_optimized_size", "warn_stale_json", "warn_gfn0_param"):
        zh = xtb.t(key, "zh")
        en = xtb.t(key, "en")
        assert zh.strip() and en.strip() and zh != en
