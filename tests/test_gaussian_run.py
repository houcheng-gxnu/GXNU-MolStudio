# -*- coding: utf-8 -*-
"""本机 Gaussian 运行器：只测不依赖真实 Gaussian 的部分（环境准备与错误处理）。

真的跑一遍 g16 的那条链路（.log + 张量 txt 落盘、算完自动出图）属于集成验证，
在开发机上手跑，不进单元测试——CI 上没有许可证。
"""

import os

from molstudio.core import gaussian_run as GR


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
    import pytest
    with pytest.raises(RuntimeError):
        GR.chk_to_fchk(str(tmp_path / "nope.chk"))


def test_find_formchk_only_returns_existing_exe(tmp_path):
    # 不存在的安装目录 → 空串（界面据此提示"找不到 formchk"）
    assert GR.find_formchk(str(tmp_path / "g16.exe")) == ""
