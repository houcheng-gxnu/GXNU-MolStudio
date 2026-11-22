# -*- coding: utf-8 -*-
"""高斯 × xTB 联用逻辑（路由整理 / external 注入 / 环境变量 / 客户端 bat）。"""

import os

import pytest

from molstudio.core import xtb_bridge as B

GJF = ("#p opt b3lyp/6-31g(d)\n\nwater\n\n0 1\n"
       "O  0.000000  0.000000  0.117300\n"
       "H  0.000000  0.757200 -0.469200\n"
       "H  0.000000 -0.757200 -0.469200\n\n")


def test_prepare_route_drops_method_keeps_basis():
    route, notes = B.prepare_bridge_route("#p opt freq b3lyp/def2svp", max_z=6)
    assert "b3lyp" not in route.lower()
    assert "def2svp" in route
    assert "opt freq" in route
    assert notes and "方法" in notes[0]


def test_prepare_route_adds_heavy_basis():
    route, notes = B.prepare_bridge_route("#p opt", max_z=77)
    assert route.endswith(B.DEFAULT_HEAVY_BASIS)
    assert notes
    # 已经给了覆盖重元素的基组就不再动
    route2, notes2 = B.prepare_bridge_route("#p opt def2tzvp", max_z=77)
    assert "def2tzvp" in route2 and "sdd" not in route2
    assert notes2 == []
    # 轻元素体系不补基组
    route3, _ = B.prepare_bridge_route("#p opt", max_z=8)
    assert "sdd" not in route3


def test_external_route_normalises_prefix():
    assert B.external_route("#p opt", "C:/a/g.bat") == \
        "#P opt external='C:/a/g.bat'"
    assert B.external_route("#P opt freq", "C:/a/g.bat") == \
        "#P opt freq external='C:/a/g.bat'"


def test_inject_external_appends_then_replaces():
    out = B.inject_external(GJF, r"C:\x\g.bat")
    assert "external='C:\\x\\g.bat'" in out
    out2 = B.inject_external(out, r"C:\y\g2.bat")
    assert "g2.bat" in out2
    assert out2.count("external=") == 1


def test_inject_external_route_override():
    out = B.inject_external(GJF, "C:/x/g.bat", route_override="opt")
    assert out.startswith("#P opt external='C:/x/g.bat'")
    assert "b3lyp" not in out.lower()


def test_inject_external_without_route_returns_none():
    assert B.inject_external("no route here", "C:/x/g.bat") is None


def test_build_bridge_env_prefers_method_args():
    env = B.build_bridge_env({}, r"E:\xtb.exe", method_args="--gfn 2 --alpb water",
                             gfn="1", threads=8, extra_args="--verbose")
    assert env["GAU_XTB_METHOD"] == "--gfn 2 --alpb water"
    assert "GAU_XTB_GFN" not in env
    assert env["GAU_XTB_COMMAND"] == r"E:\xtb.exe"
    assert env["GAU_XTB_THREADS"] == "8"
    assert env["GAU_XTB_ARGS"] == "--verbose"

    env2 = B.build_bridge_env({}, r"E:\xtb.exe", gfn="1")
    assert env2["GAU_XTB_GFN"] == "1"
    assert "GAU_XTB_METHOD" not in env2

    env3 = B.build_bridge_env({}, r"E:\xtb.exe")
    assert "GAU_XTB_METHOD" not in env3 and "GAU_XTB_GFN" not in env3


def test_xtb_bridge_argv_matches_protocol():
    argv = B.xtb_bridge_argv("xtb.exe", -1, 1, "--gfn 2", 4, derivs=2)
    assert argv[:3] == ["xtb.exe", "mol.xyz", "--chrg"]
    assert "--uhf" in argv and "1" in argv
    assert "--hess" in argv and "--grad" in argv
    assert B.xtb_bridge_argv("x", 0, 0, "2", 0, derivs=0)[-1] == "--sp"


def test_write_client_bat_calls_the_script(tmp_path):
    path = B.write_client_bat(tmp_path)
    assert os.path.isfile(path)
    content = open(path, encoding="ascii").read()
    assert "gau_xtb.py" in content
    assert "%*" in content
    assert content.lower().startswith("@echo off")


def test_script_is_shipped():
    script = B.gau_xtb_script_path()
    assert os.path.isfile(script)
    text = open(script, encoding="utf-8").read()
    assert "Gaussian External" in text
    assert "GAU_XTB_METHOD" in text


def test_short_path_keeps_existing_path():
    path = os.path.abspath(".")
    assert B.short_path(path)
