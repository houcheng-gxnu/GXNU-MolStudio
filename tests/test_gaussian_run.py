# -*- coding: utf-8 -*-
"""本机 Gaussian 运行器：只测不依赖真实 Gaussian 的部分（环境准备与错误处理）。

真的跑一遍 g16 的那条链路（.log + 张量 txt 落盘、算完自动出图）属于集成验证，
在开发机上手跑，不进单元测试——CI 上没有许可证。
"""

import os

import pytest

from molstudio.core import gaussian_run as GR


# ── 环境 / 错误处理（原有） ──────────────────────────────────────────

def test_env_sets_gauss_exedir_and_scratch(tmp_path):
    exe = tmp_path / "g16w" / "g16.exe"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"")
    env = GR.gaussian_env(str(exe))
    # 缺 GAUSS_EXEDIR 时 g16 会报 "Search path GAUSS_EXEDIR is ''"（实测）
    assert env["GAUSS_EXEDIR"] == str(exe.parent)
    assert os.path.isdir(env["GAUSS_SCRDIR"])


def test_missing_exe_reports_error_not_crash(tmp_path):
    gjf = tmp_path / "a.gjf"
    gjf.write_text("# hf/sto-3g\n\nt\n\n0 1\n H 0 0 0\n\n", encoding="utf-8")
    res = GR.run_gaussian(str(gjf), str(tmp_path / "nope.exe"))
    assert res.ok is False
    assert "Gaussian" in res.error


def test_missing_input_reports_error(tmp_path):
    exe = tmp_path / "g16.exe"
    exe.write_bytes(b"")
    res = GR.run_gaussian(str(tmp_path / "nope.gjf"), str(exe))
    assert res.ok is False and res.error


def test_milestones_cover_the_workflow_markers():
    labels = " ".join(lbl for _, lbl in GR.MILESTONES)
    for key in ("启动", "SCF", "张量", "正常结束", "异常"):
        assert key in labels


# ── chk → fchk（Multiwfn 的 π 轨道分析需要格式化检查点） ─────────────────

def test_find_chk_file_reads_link0_line(tmp_path):
    chk = tmp_path / "py.chk"
    chk.write_bytes(b"x")
    log = tmp_path / "job.log"
    # 注意别用 % 格式化：%chk 里的 %c 会被当成格式符
    log.write_text(f" Gaussian 16\n %chk={chk}\n ...\n", encoding="utf-8")
    assert GR.find_chk_file(str(log)) == str(chk)


def test_find_chk_file_falls_back_to_same_stem(tmp_path):
    chk = tmp_path / "job.chk"
    chk.write_bytes(b"x")
    log = tmp_path / "job.log"
    log.write_text(" Gaussian 16 (no link0 echo here)\n", encoding="utf-8")
    assert GR.find_chk_file(str(log)) == str(chk)


def test_chk_to_fchk_missing_file_raises(tmp_path):
    with pytest.raises(RuntimeError):
        GR.chk_to_fchk(str(tmp_path / "nope.chk"))


def test_find_formchk_only_returns_existing_exe(tmp_path):
    # 不存在的安装目录 → 空串（界面据此提示"找不到 formchk"）
    assert GR.find_formchk(str(tmp_path / "g16.exe")) == ""


# ── 输入生成 / 日志解析（高斯页新增） ────────────────────────────────────

LOG = """
 Charge =  -1 Multiplicity = 2
 SCF Done:  E(RB3LYP) =  -76.4000000000     A.U. after   10 cycles
 Alpha  occ. eigenvalues --  -19.13000  -1.00000  -0.50000
 Alpha  occ. eigenvalues --   -0.40000  -0.20835
 Alpha virt. eigenvalues --    0.05000   0.10000
 Alpha virt. eigenvalues --    1.20000
 Frequencies --  -607.0403  100.0000  200.0000
 Frequencies --   300.0000
                         Standard orientation:
 ---------------------------------------------------------------------
 Center     Atomic      Atomic             Coordinates (Angstroms)
 Number     Number       Type             X           Y           Z
 ---------------------------------------------------------------------
      1          8           0        0.000000    0.000000    0.117300
      2          1           0        0.000000    0.757200   -0.469200
      3          1           0        0.000000   -0.757200   -0.469200
 ---------------------------------------------------------------------
 Stationary point found.
 Normal termination of Gaussian 16
"""


def test_build_route_normal():
    route = GR.build_route("B3LYP", "6-31G(d)", "opt_freq", "D3BJ", "water",
                           "smd", "TightSCF")
    assert route.startswith("#p B3LYP/6-31G(d)")
    assert "opt freq" in route
    assert "empiricaldispersion=d3bj" in route
    assert "scrf=(smd,solvent=water)" in route
    assert "TightSCF" in route


def test_build_route_sp_has_no_job_keyword():
    assert GR.build_route(task="sp").strip() == "#p B3LYP/6-31G(d)"


def test_build_route_bridge_has_no_method():
    route = GR.build_route(include_method=False, task="ts",
                           extra_keywords="calcfc")
    assert "B3LYP" not in route
    assert "/" not in route
    assert "opt=(ts,calcfc,noeigentest)" in route
    assert route.startswith("#p ")


def test_build_route_validation():
    with pytest.raises(ValueError):
        GR.build_route(task="nonsense")
    with pytest.raises(ValueError):
        GR.build_route(method="")


def test_build_gjf_structure():
    text = GR.build_gjf(["O", "H"], [[0, 0, 0], [1, 0, 0]], charge=-1, mult=2,
                        route="#p hf/sto-3g", title="water", nproc=4,
                        mem_gb=8, chk_name="w.chk")
    assert "%nprocshared=4" in text
    assert "%mem=8GB" in text
    assert "%chk=w.chk" in text
    assert "#p hf/sto-3g" in text
    assert "\nwater\n" in text
    assert "\n-1 2\n" in text
    assert "O " in text and "H " in text


def test_build_gjf_validation():
    with pytest.raises(ValueError):
        GR.build_gjf([], [])
    with pytest.raises(ValueError):
        GR.build_gjf(["C"], [])
    with pytest.raises(ValueError):
        GR.build_gjf(["C"], [[0, 0, 0]], charge="x")
    with pytest.raises(ValueError):
        GR.build_gjf(["C"], [[0, 0, 0]], mult=0)


def test_read_gjf_charge_mult(tmp_path):
    gjf = tmp_path / "anion.gjf"
    gjf.write_text("#p b3lyp/def2svp\n\nanion\n\n-1 2\nO 0 0 0\n\n",
                   encoding="utf-8")
    assert GR.read_gjf_charge_mult(str(gjf)) == (-1, 2)
    other = tmp_path / "w.xyz"
    other.write_text("1\nw\nH 0 0 0\n", encoding="utf-8")
    assert GR.read_gjf_charge_mult(str(other)) == (None, None)


def test_parse_output_energy_orbitals():
    parsed = GR.parse_output(LOG)
    assert parsed["final_energy"] == pytest.approx(-76.4)
    assert parsed["homo"] == pytest.approx(-0.20835)
    assert parsed["lumo"] == pytest.approx(0.05)
    assert parsed["homo_lumo_gap_ev"] == pytest.approx(
        (0.05 + 0.20835) * 27.211386245988, rel=1e-6)
    assert parsed["terminated_normally"] is True
    assert parsed["opt_converged"] is True
    assert parsed["charge"] == -1 and parsed["multiplicity"] == 2


def test_parse_output_frequencies_and_geometry():
    parsed = GR.parse_output(LOG)
    assert len(parsed["frequencies"]) == 4      # 607 的虚频也算一个频率
    assert parsed["imaginary"] == [pytest.approx(-607.0403)]
    assert parsed["symbols"] == ["O", "H", "H"]
    assert len(parsed["geometry"]) == 3
    assert parsed["geometry"][0][2] == pytest.approx(0.1173)


def test_parse_output_bridge_energies():
    text = ("Recovered energy= -5.0703707618\n"
            "Recovered energy= -5.0710000000\n"
            "Normal termination of Gaussian 16\n")
    parsed = GR.parse_output(text)
    assert parsed["bridge"] is True
    assert parsed["final_energy"] == pytest.approx(-5.071)
    assert parsed["steps"] == 2


def test_parse_output_empty():
    parsed = GR.parse_output("")
    assert parsed["final_energy"] is None
    assert parsed["terminated_normally"] is False
    assert parsed["frequencies"] == []
    assert parsed["symbols"] == []
