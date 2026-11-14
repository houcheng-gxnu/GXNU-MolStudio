# -*- coding: utf-8 -*-
"""``molstudio.core.ow_fukui`` 单元测试（纯文本解析 + 可选真实 Multiwfn 集成）。

前一部分是**纯文本 / 纯文件**测试：真实 Multiwfn 2026.4.10 输出（
``_dev/tmp/owf_probe``）已裁剪后内嵌为本文件的字符串常量，因此这些测试不依赖
``_dev`` 目录；另外有一个直接读取 ``owf_full_stdout.txt`` 的测试（文件缺失时
自动 skip）。最后一个 live 集成测试按显式 skipif 条件检查本机 Multiwfn /
苯样本是否存在，存在就**真跑**主功能 22 并校验 4 个 cube 与关键数值。

本文件必须保持 UTF-8 编码（含中文断言信息）。
"""

import os
import subprocess
import sys
import time

import pytest

from molstudio.core.ow_fukui import (
    DEFAULT_SETTINGS,
    DEFAULT_TIMEOUT,
    DELTA_DEFAULT,
    DELTA_MAX,
    DELTA_MIN,
    FUNCTIONS,
    GRID_QUALITIES,
    build_sequence,
    export_condensed_csv,
    parse_ow_output,
    run_ow_fukui,
    settings_summary,
    suggest_iso,
)


# ───────────────────────────── 本机素材路径 ─────────────────────────────

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MW_EXE = r"E:\Multiwfn_2026.4.10_bin_Win64\Multiwfn.exe"
_LIVE_FCHK = os.path.join(_REPO_ROOT, "_dev", "tmp", "owf_probe",
                          "benzene_LMO.fch")
_FULL_STDOUT = os.path.join(_REPO_ROOT, "_dev", "tmp", "owf_probe",
                            "owf_full_stdout.txt")


# ─────────────────── 内嵌真实输出（苯，Multiwfn 2026.4.10）───────────────────

#: 选项 5：HOMO/LUMO/μ/Δ + f+、f- 前 10 个轨道权重（实测原文）
WEIGHTS_TEXT = """\
 HOMO energy:   -0.284769 a.u.      -7.749 eV
 LUMO energy:    0.003691 a.u.       0.100 eV
 Chemical potential:   -0.140539 a.u.      -3.824 eV
 Delta parameter:       0.100000 a.u.       2.721 eV
 The "E_diff" in below output denotes difference between orbital energy with respect to chemical potential

 10 Highest weights in orbital-weighted f+
 Orbital    22 (LUMO  )   Weight:  48.68 %   E_diff:     3.925 eV
 Orbital    23 (LUMO+1)   Weight:  48.68 %   E_diff:     3.925 eV
 Orbital    24 (LUMO+2)   Weight:   2.28 %   E_diff:     6.170 eV
 Orbital    25 (LUMO+3)   Weight:   0.14 %   E_diff:     7.662 eV
 Orbital    26 (LUMO+4)   Weight:   0.14 %   E_diff:     7.662 eV
 Orbital    27 (LUMO+5)   Weight:   0.04 %   E_diff:     8.304 eV
 Orbital    28 (LUMO+6)   Weight:   0.01 %   E_diff:     8.717 eV
 Orbital    29 (LUMO+7)   Weight:   0.01 %   E_diff:     8.717 eV
 Orbital    30 (LUMO+8)   Weight:   0.01 %   E_diff:     8.904 eV
 Total weight of above listed orbitals: 100.00 %

 10 Highest weights in orbital-weighted f-
 Orbital    21 (HOMO  )   Weight:  33.33 %   E_diff:    -3.925 eV
 Orbital    20 (HOMO-1)   Weight:  33.33 %   E_diff:    -3.925 eV
 Orbital    19 (HOMO-2)   Weight:  33.33 %   E_diff:    -3.925 eV
 Orbital    18 (HOMO-3)   Weight:   0.00 %   E_diff:   -10.061 eV
 Orbital    17 (HOMO-4)   Weight:   0.00 %   E_diff:   -10.061 eV
 Orbital    16 (HOMO-5)   Weight:   0.00 %   E_diff:   -10.061 eV
 Orbital    15 (HOMO-6)   Weight:   0.00 %   E_diff:   -10.061 eV
 Orbital    14 (HOMO-7)   Weight:   0.00 %   E_diff:   -10.061 eV
 Orbital    13 (HOMO-8)   Weight:   0.00 %   E_diff:   -10.061 eV
 Orbital    12 (HOMO-9)   Weight:   0.00 %   E_diff:   -13.043 eV
 Total weight of above listed orbitals: 100.00 %
"""

#: 选项 6：Hirshfeld 简缩 OW f+/f-/f0/DD 表 + 两个 sum（实测原文）
CONDENSED_TEXT = """\
 Radial points:   30    Angular points:  302   Total:      9060 per center

  Atom index       OW f+          OW f-          OW f0          OW DD
     1(C )        0.14908        0.15657        0.15283       -0.00748
     2(C )        0.14909        0.15657        0.15283       -0.00748
     3(C )        0.14909        0.15656        0.15282       -0.00747
     4(C )        0.14908        0.15656        0.15282       -0.00748
     5(C )        0.14909        0.15656        0.15282       -0.00747
     6(C )        0.14909        0.15656        0.15282       -0.00747
     7(H )        0.01758        0.01010        0.01384        0.00747
     8(H )        0.01757        0.01010        0.01383        0.00747
     9(H )        0.01757        0.01010        0.01383        0.00747
    10(H )        0.01758        0.01010        0.01384        0.00747
    11(H )        0.01757        0.01010        0.01383        0.00747
    12(H )        0.01757        0.01010        0.01383        0.00747

 Sum of orbital weighted f+    0.999953
 Sum of orbital weighted f-    0.999965
"""

#: 选项 7 网格质量 1（低）之后的网格信息（实测原文）
GRID_TEXT = """\
 Please select a method to set up grid
 -10 Set extension distance of grid range for mode 1~4, current:  3.000 Bohr
 1 Low quality grid,    covering whole system, about 125000 points in total
 2 Medium quality grid, covering whole system, about 512000 points in total
 3 High quality grid,   covering whole system, about 1728000 points in total
 Coordinate of origin in X,Y,Z is      -7.082541   -7.714113   -3.000000 Bohr
 Coordinate of end point in X,Y,Z is    7.146385    7.609346    2.910477 Bohr
 Grid spacing in X,Y,Z is    0.218907    0.218907    0.218907 Bohr
 Number of points in X,Y,Z is   66   71   28   Total:      131208

 Calculating grid data of orbital-weighted f+...
 Note: All exponential functions exp(x) with x< -40.000 will be ignored 
 Unique GTFs have been constructed. Number of unique GTFs:     192
 Progress: [--------------------------------------------------]     0.0 %     -
 Progress: [#############################---------------------]    53.0 %     |
 Progress: [##################################################]   100.0 %     \
"""

#: cube 后处理菜单 + 4 次导出（实测原文裁剪；导出只打印 "Exporting finished!"）
EXPORT_TEXT = """\
 -1 Set the value multiplied to all grid data, current:    1.000000
 0 Return
 1 Visualize isosurface of orbital-weighted f+
 2 Visualize isosurface of orbital-weighted f-
 3 Visualize isosurface of orbital-weighted f0
 4 Visualize isosurface of orbital-weighted dual descriptor
 5 Export grid data of orbital-weighted f+ as OW_f+.cub
 6 Export grid data of orbital-weighted f- as OW_f-.cub
 7 Export grid data of orbital-weighted f0 as OW_f0.cub
 8 Export grid data of orbital-weighted dual descriptor as OW_DD.cub
 Exporting finished!

 -1 Set the value multiplied to all grid data, current:    1.000000
 0 Return
 5 Export grid data of orbital-weighted f+ as OW_f+.cub
 6 Export grid data of orbital-weighted f- as OW_f-.cub
 7 Export grid data of orbital-weighted f0 as OW_f0.cub
 8 Export grid data of orbital-weighted dual descriptor as OW_DD.cub
 Exporting finished!

 -1 Set the value multiplied to all grid data, current:    1.000000
 0 Return
 8 Export grid data of orbital-weighted dual descriptor as OW_DD.cub
 Exporting finished!

 -1 Set the value multiplied to all grid data, current:    1.000000
 0 Return
 Exporting finished!
"""

#: 重复打印的 CDFT 菜单（实测会随每次操作重新显示，解析必须忽略）
CDFT_MENU_TEXT = """\
 ---- Calculate various quantities in conceptual density functional theory ----
 -3 Set degree of FMO degeneracy, current: Nondegenerate
 -2 Choose the quantum chemistry program used in option 1, current: Gaussian
 -1 Toggle calculating electrophilicity index (w_cubic) and electrophilic descri
  ptor (epsilon) by option 2, current: No
 0 Return
 1 Generate .wfn files for N, N+1, N-1 electrons states
 2 Calculate various quantitative indices
 3 Calculate grid data of Fukui function, dual descriptor and related functions
 4 Set delta in orbital-weighted (OW) calculation, current: 0.1000 a.u.
 5 Print current orbital weights used in orbital-weighted (OW) calculation
 6 Calculate condensed OW Fukui function and OW dual descriptor
 7 Calculate grid data of OW Fukui function and OW dual descriptor
 8 Calculate nucleophilic and electrophilic superdelocalizabilities
 9 Calculate grid data of Fukui potential and dual descriptor potential
 10 Calculate bond dual descriptor (BDD)
"""


# ───────────────────────────── 内嵌文本解析 ─────────────────────────────

def test_parse_energies_and_delta():
    r = parse_ow_output(WEIGHTS_TEXT)

    assert r["homo_energy"] == pytest.approx(-0.284769)
    assert r["lumo_energy"] == pytest.approx(0.003691)
    # μ 就是 (HOMO+LUMO)/2（Multiwfn 打印值，允许末位误差）
    assert r["chemical_potential"] == pytest.approx(
        (r["homo_energy"] + r["lumo_energy"]) / 2.0, abs=1e-6)
    assert r["delta"] == DELTA_DEFAULT
    assert r["warnings"] == []


def test_parse_weights_fplus_fminus():
    r = parse_ow_output(WEIGHTS_TEXT)

    fp = r["weights"]["fplus"]
    # 实测 f+ 只列出 9 个轨道（第 10 个权重为 0 未打印）
    assert len(fp) == 9
    assert fp[0] == {"index": 22, "label": "LUMO",
                     "weight": pytest.approx(48.68),
                     "ediff_ev": pytest.approx(3.925)}
    assert fp[1]["index"] == 23 and fp[1]["label"] == "LUMO+1"
    assert fp[1]["weight"] == pytest.approx(48.68)
    assert fp[2]["index"] == 24 and fp[2]["label"] == "LUMO+2"
    assert fp[2]["weight"] == pytest.approx(2.28)
    assert fp[2]["ediff_ev"] == pytest.approx(6.170)

    fm = r["weights"]["fminus"]
    assert len(fm) == 10
    assert fm[0]["index"] == 21 and fm[0]["label"] == "HOMO"
    assert fm[0]["weight"] == pytest.approx(33.33)
    assert fm[0]["ediff_ev"] == pytest.approx(-3.925)
    assert fm[3]["label"] == "HOMO-3"
    assert fm[-1]["label"] == "HOMO-9"

    assert r["total_weight"]["fplus"] == pytest.approx(100.0)
    assert r["total_weight"]["fminus"] == pytest.approx(100.0)


def test_parse_condensed_table_and_sums():
    r = parse_ow_output(CONDENSED_TEXT)

    rows = r["condensed"]
    assert len(rows) == 12
    first = rows[0]
    assert first["index"] == 1 and first["element"] == "C"
    assert first["fplus"] == pytest.approx(0.14908)
    assert first["fminus"] == pytest.approx(0.15657)
    assert first["f0"] == pytest.approx(0.15283)
    assert first["dd"] == pytest.approx(-0.00748)
    assert rows[-1]["index"] == 12 and rows[-1]["element"] == "H"
    assert rows[-1]["fplus"] == pytest.approx(0.01757)

    # 简缩值全空间求和应 ≈ 1
    assert abs(sum(x["fplus"] for x in rows) - 1.0) < 2e-3
    assert abs(sum(x["fminus"] for x in rows) - 1.0) < 2e-3
    assert abs(sum(x["f0"] for x in rows) - 1.0) < 2e-3
    # Δf 全空间积分为 0
    assert abs(sum(x["dd"] for x in rows)) < 1e-3

    assert r["sums"]["fplus"] == pytest.approx(0.999953, abs=1e-9)
    assert r["sums"]["fminus"] == pytest.approx(0.999965, abs=1e-9)
    assert r["warnings"] == []


def test_parse_grid_info_and_quality_inference():
    r = parse_ow_output(GRID_TEXT)

    grid = r["grid"]
    assert grid["nx"] == 66 and grid["ny"] == 71 and grid["nz"] == 28
    assert grid["npoints"] == 131208
    assert grid["spacing_bohr"] == pytest.approx(0.218907)
    # 13.1 万格点 → 低质量（1）
    assert grid["quality"] == 1
    assert grid["npoints"] == grid["nx"] * grid["ny"] * grid["nz"]
    # 单独一段网格信息没有权重/简缩/导出内容，解析器会给出「无结果」提示；
    # 这里只确认没有开壳层 / Fortran 运行时错误之类的误报。
    assert not any("开壳层" in w or "Fortran" in w for w in r["warnings"])


def test_parse_exported_count():
    r = parse_ow_output(EXPORT_TEXT)
    assert r["exported"] == ["OW_f+.cub", "OW_f-.cub", "OW_f0.cub", "OW_DD.cub"]

    # 只导出 2 个时按后处理菜单顺序取前 2 个
    two = EXPORT_TEXT.split(" Exporting finished!")[0] + " Exporting finished!"
    two += EXPORT_TEXT.split(" Exporting finished!")[1] + " Exporting finished!"
    assert parse_ow_output(two)["exported"] == ["OW_f+.cub", "OW_f-.cub"]
    assert parse_ow_output("no exports here")["exported"] == []


def test_parse_tolerates_progress_repeated_menus_and_garbage():
    noisy = (CDFT_MENU_TEXT + WEIGHTS_TEXT + CDFT_MENU_TEXT + CONDENSED_TEXT
             + CDFT_MENU_TEXT + GRID_TEXT + EXPORT_TEXT
             + " \ufffd\ufffd garbage line \ufffd\n"
             + "Progress: [####...] 53.0 %\n")
    r = parse_ow_output(noisy)

    assert r["homo_energy"] == pytest.approx(-0.284769)
    assert len(r["weights"]["fplus"]) == 9
    assert len(r["weights"]["fminus"]) == 10
    assert len(r["condensed"]) == 12
    assert r["grid"]["npoints"] == 131208
    assert len(r["exported"]) == 4
    # 重复菜单 / 进度条 / 乱码都不应产生警告
    assert r["warnings"] == []


def test_parse_never_raises_on_empty_and_weird_input():
    for text in ("", "garbage line\nProgress: [###] 12.3 %\n",
                 "forrtl: severe (64): input conversion error, unit 10"):
        r = parse_ow_output(text)
        assert isinstance(r["warnings"], list)
        assert r["homo_energy"] is None
        assert r["condensed"] == []

    assert parse_ow_output("")["warnings"]
    warnings = parse_ow_output("forrtl: severe (64)")["warnings"]
    assert any("Fortran" in w for w in warnings)

    # 非字符串输入也不能抛
    assert isinstance(parse_ow_output(None), dict)
    assert isinstance(parse_ow_output(12345), dict)


def test_parse_open_shell_output_is_flagged():
    text = (" This is an unrestricted single-determinant wavefunction\n"
            + WEIGHTS_TEXT)
    warnings = parse_ow_output(text)["warnings"]
    assert any("开壳层" in w for w in warnings)
    assert any("闭壳层" in w for w in warnings)


@pytest.mark.skipif(not os.path.isfile(_FULL_STDOUT),
                    reason="真实 Multiwfn stdout 样本不可用")
def test_parse_real_full_stdout_file():
    with open(_FULL_STDOUT, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    r = parse_ow_output(text)

    assert r["homo_energy"] == pytest.approx(-0.284769)
    assert r["lumo_energy"] == pytest.approx(0.003691)
    assert r["delta"] == pytest.approx(0.1)
    assert len(r["weights"]["fplus"]) == 9
    assert len(r["weights"]["fminus"]) == 10
    assert r["total_weight"] == {"fplus": pytest.approx(100.0),
                                 "fminus": pytest.approx(100.0)}
    assert len(r["condensed"]) == 12
    assert r["sums"]["fplus"] == pytest.approx(0.999953, abs=1e-9)
    assert r["grid"]["quality"] == 1
    assert r["grid"]["npoints"] == 131208
    assert len(r["exported"]) == 4
    assert r["warnings"] == []


# ───────────────────────────── build_sequence ─────────────────────────────

def test_build_sequence_default_full_run():
    # 合同里的完整序列：22 → 5 → 6 → 7+质量 → 导出 5/6/7/8 → 0/0/q
    assert build_sequence(dict(DEFAULT_SETTINGS)) == \
        "\n22\n5\n6\n7\n2\n5\n6\n7\n8\n0\n0\nq\n"


def test_build_sequence_delta_inserted_after_22():
    seq = build_sequence({"delta": 0.25})
    assert seq.startswith("\n22\n4\n0.25\n")
    assert "4\n0.25\n5\n6\n7\n2\n" in seq

    # Δ 与默认值相同则不发送 4
    assert "4\n" not in build_sequence({"delta": DELTA_DEFAULT})
    # 0.05 也要写成 "0.05" 而不是 "5e-2"
    assert "4\n0.05\n" in build_sequence({"delta": 0.05})


def test_build_sequence_no_export_tail_has_single_zero():
    # 不发 7 时没有后处理菜单，结尾只能是 0/q（多一个 0 会打开轨道查看器卡死）
    seq = build_sequence({"export": []})
    assert seq == "\n22\n5\n6\n0\nq\n"
    assert seq.endswith("0\nq\n")

    # 什么都不做：22 → 0 → q
    assert build_sequence({"weights": False, "condensed": False,
                           "export": []}) == "\n22\n0\nq\n"


def test_build_sequence_export_subset_and_grid_quality():
    seq = build_sequence({"export": ["dd"], "grid_quality": 1})
    assert seq.endswith("7\n1\n8\n0\n0\nq\n")

    seq2 = build_sequence({"export": ["f0", "fplus"], "grid_quality": 3,
                           "weights": False, "condensed": False})
    # 导出顺序 = 用户给定顺序（f0 先于 fplus），且都带网格质量
    assert seq2 == "\n22\n7\n3\n7\n5\n0\n0\nq\n"


def test_build_sequence_rejects_invalid_settings():
    with pytest.raises(ValueError):
        build_sequence({"delta": 0})              # 低于 DELTA_MIN
    with pytest.raises(ValueError):
        build_sequence({"delta": 5})              # 高于 DELTA_MAX
    with pytest.raises(ValueError):
        build_sequence({"delta": "abc"})
    with pytest.raises(ValueError):
        build_sequence({"grid_quality": 4})       # 只有 1/2/3
    with pytest.raises(ValueError):
        build_sequence({"export": ["bogus"]})
    with pytest.raises(ValueError):
        build_sequence("not a dict")


def test_constants_contract():
    assert DELTA_DEFAULT == 0.1
    assert (DELTA_MIN, DELTA_MAX) == (0.001, 2.0)
    assert set(GRID_QUALITIES) == {1, 2, 3}
    assert list(FUNCTIONS) == ["fplus", "fminus", "f0", "dd"]
    assert [FUNCTIONS[k]["multi"] for k in FUNCTIONS] == [5, 6, 7, 8]
    assert FUNCTIONS["dd"]["cub"] == "OW_DD.cub"
    assert DEFAULT_TIMEOUT >= 600


def test_settings_summary_zh_en():
    zh = settings_summary(dict(DEFAULT_SETTINGS), lang="zh")
    assert "Δ = 0.1 a.u." in zh
    assert "中质量" in zh
    assert "轨道权重 f+" in zh and "双描述符" in zh

    en = settings_summary(dict(DEFAULT_SETTINGS), lang="en")
    assert "Δ = 0.1 a.u." in en
    assert "Medium grid" in en
    assert "OW f+" in en
    # 英文摘要不得出现中文
    assert not any("\u4e00" <= ch <= "\u9fff" for ch in en)

    empty = settings_summary({"export": []}, lang="zh")
    assert "不导出 cube" in empty


# ───────────────────────────── suggest_iso ─────────────────────────────

def _write_small_cube(path):
    """写一个 2×2×2 的 mini cube（max|data| = 0.006）。"""
    lines = [
        "cube from ow_fukui unit test",
        "OW f+ test data",
        "    1    0.000000    0.000000    0.000000",
        "    2    0.100000    0.000000    0.000000",
        "    2    0.000000    0.100000    0.000000",
        "    2    0.000000    0.000000    0.100000",
        "    6    6.000000    0.000000    0.000000    0.000000",
        "  0.00000  0.00100  0.00200 -0.00300",
        "  0.00400 -0.00600  0.00500  0.00000",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_suggest_iso_rounds_to_readable_value(tmp_path):
    cube = tmp_path / "mini.cub"
    _write_small_cube(cube)

    # 默认 5% × 0.006 = 0.0003 → 1 位有效数字 0.0003
    assert suggest_iso(str(cube)) == pytest.approx(0.0003, rel=1e-6)
    # fraction=0.2 → 0.0012 → 0.001
    assert suggest_iso(str(cube), fraction=0.2) == pytest.approx(0.001, rel=1e-6)
    # 非法 fraction 回退到 0.05
    assert suggest_iso(str(cube), fraction=0) == pytest.approx(0.0003, rel=1e-6)


def test_suggest_iso_failure_returns_none(tmp_path):
    assert suggest_iso(str(tmp_path / "missing.cub")) is None

    bad = tmp_path / "bad.cub"
    bad.write_text("not a cube file\n", encoding="utf-8")
    assert suggest_iso(str(bad)) is None

    # 全零数据无法给出有意义的等值面
    zero = tmp_path / "zero.cub"
    _write_small_cube(zero)
    zero_text = zero.read_text(encoding="utf-8")
    zero_text = zero_text.replace(
        "  0.00000  0.00100  0.00200 -0.00300", "  0.00000  0.00000  0.00000  0.00000")
    zero_text = zero_text.replace(
        "  0.00400 -0.00600  0.00500  0.00000", "  0.00000  0.00000  0.00000  0.00000")
    zero.write_text(zero_text, encoding="utf-8")
    assert suggest_iso(str(zero)) is None


# ───────────────────────────── 简缩值 CSV ─────────────────────────────

def test_export_condensed_csv_zh_and_en(tmp_path):
    rows = parse_ow_output(CONDENSED_TEXT)["condensed"]

    zh_path = tmp_path / "condensed_zh.csv"
    out = export_condensed_csv(str(zh_path), rows, lang="zh")
    assert os.path.abspath(out) == os.path.abspath(str(zh_path))
    raw = zh_path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")          # UTF-8 BOM（Excel 友好）
    lines = raw.decode("utf-8-sig").splitlines()
    assert lines[0] == "原子,元素,OW f+,OW f-,OW f0,OW DD"
    assert len(lines) == 1 + 12
    assert lines[1] == "1,C,0.14908,0.15657,0.15283,-0.00748"

    en_path = tmp_path / "condensed_en.csv"
    export_condensed_csv(str(en_path), rows, lang="en")
    en_lines = en_path.read_bytes().decode("utf-8-sig").splitlines()
    assert en_lines[0] == "Atom,Element,OW f+,OW f-,OW f0,OW DD"
    assert len(en_lines) == 1 + 12


# ───────────────────── run_ow_fukui 校验路径（不启动 Multiwfn）─────────────────────

def _write_fake_fchk(path, open_shell=False, virtuals=True):
    """写一个只有 MO 信息段的假 fchk，供输入校验测试用。"""
    n_basis = 10 if virtuals else 5
    alpha = ["-0.70", "-0.60", "-0.50", "-0.40", "-0.30"]
    if virtuals:
        alpha += ["0.10", "0.20", "0.30", "0.40", "0.50"]
    lines = [
        "fake fchk for ow_fukui unit test",
        "Number of alpha electrons                 I     5",
        "Number of beta electrons                  I     %d"
        % (4 if open_shell else 5),
        "Number of basis functions                 I     %d" % n_basis,
        "Alpha Orbital Energies                    R   N=          %d" % n_basis,
        "  " + " ".join(alpha),
    ]
    if open_shell:
        lines += [
            "Beta Orbital Energies                     R   N=          %d" % n_basis,
            "  " + " ".join(alpha),
        ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_run_missing_fchk_raises():
    with pytest.raises(RuntimeError, match="找不到波函数文件"):
        run_ow_fukui(os.path.join("no_such_dir", "x.fchk"), sys.executable)


def test_run_rejects_unsupported_format(tmp_path):
    wfn = tmp_path / "mol.wfn"
    wfn.write_text("dummy", encoding="utf-8")
    with pytest.raises(RuntimeError, match="空轨道"):
        run_ow_fukui(str(wfn), sys.executable)


def test_run_missing_exe_raises(tmp_path):
    fchk = tmp_path / "mol.fchk"
    _write_fake_fchk(fchk)
    with pytest.raises(RuntimeError, match="找不到 Multiwfn"):
        run_ow_fukui(str(fchk), str(tmp_path / "nope.exe"))


def test_run_rejects_open_shell_with_chinese_message(tmp_path):
    fchk = tmp_path / "radical.fchk"
    _write_fake_fchk(fchk, open_shell=True)
    with pytest.raises(RuntimeError) as excinfo:
        run_ow_fukui(str(fchk), sys.executable)
    msg = str(excinfo.value)
    assert "闭壳层单行列式" in msg
    assert "开壳层" in msg


def test_run_rejects_wavefunction_without_virtual_orbitals(tmp_path):
    fchk = tmp_path / "no_virtual.fchk"
    _write_fake_fchk(fchk, virtuals=False)
    with pytest.raises(RuntimeError, match="没有空轨道"):
        run_ow_fukui(str(fchk), sys.executable)


def test_run_invalid_settings_raise_chinese_runtime_error(tmp_path):
    fchk = tmp_path / "mol.fchk"
    _write_fake_fchk(fchk)
    with pytest.raises(RuntimeError, match="分析设置无效"):
        run_ow_fukui(str(fchk), sys.executable, {"grid_quality": 7})


def test_run_cancel_before_start_returns_not_ok(tmp_path):
    fchk = tmp_path / "mol.fchk"
    _write_fake_fchk(fchk)
    res = run_ow_fukui(str(fchk), sys.executable, {"export": []},
                       out_dir=str(tmp_path), cancel_check=lambda: True)

    assert res["ok"] is False
    assert res["error"] == "已取消"
    assert res["weights"] == {"fplus": [], "fminus": []}
    assert res["condensed"] == []
    assert res["cubes"] == {"fplus": "", "fminus": "", "f0": "", "dd": ""}
    assert res["log_path"] == ""


def test_module_import_does_not_load_qt():
    """核心模块必须 Qt-free：独立进程里 import 后不得出现任何 Qt 绑定。"""
    code = (
        "import sys\n"
        "import molstudio.core.ow_fukui\n"
        "qt = [m for m in sys.modules\n"
        "      if m.split('.')[0] in "
        "('PyQt5', 'PyQt6', 'PySide2', 'PySide6')]\n"
        "assert not qt, qt\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], cwd=_REPO_ROOT,
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")


# ───────────────────────────── live 集成测试 ─────────────────────────────

@pytest.mark.skipif(
    not os.path.exists(_MW_EXE) or not os.path.exists(_LIVE_FCHK),
    reason="本机 Multiwfn 或苯样本不可用")
def test_live_run_ow_fukui_benzene(tmp_path):
    """真实跑一遍 Multiwfn 主功能 22（低质量网格），校验 4 个 cube 与数值。"""
    t0 = time.time()
    result = run_ow_fukui(
        _LIVE_FCHK, _MW_EXE,
        {"delta": 0.1, "grid_quality": 1},
        out_dir=str(tmp_path), timeout=600)
    elapsed = time.time() - t0
    print("live OW-Fukui 总耗时 %.2f s（Multiwfn 进程 %.2f s）"
          % (elapsed, result.get("seconds", 0.0)))

    assert result["ok"], result["error"]
    assert result["seconds"] > 0

    # 产物：4 个 cube + 1 个日志，全部在 out_dir 下
    stem = "benzene_LMO"
    for key, suffix in (("fplus", "OW_f+"), ("fminus", "OW_f-"),
                        ("f0", "OW_f0"), ("dd", "OW_DD")):
        path = tmp_path / ("%s_%s.cub" % (stem, suffix))
        assert path.is_file(), "缺少 cube：%s" % path
        assert path.stat().st_size > 100000
        assert result["cubes"][key].endswith("%s_%s.cub" % (stem, suffix))
    log_path = tmp_path / (stem + "_OWFukui.log")
    assert log_path.is_file() and log_path.stat().st_size > 1000
    assert result["log_path"].endswith(stem + "_OWFukui.log")
    assert result["exported"] == ["OW_f+.cub", "OW_f-.cub",
                                  "OW_f0.cub", "OW_DD.cub"]

    # 能量：苯 B3LYP/6-31G* 实测值，μ ≈ (HOMO+LUMO)/2
    homo, lumo = result["homo_energy"], result["lumo_energy"]
    assert homo == pytest.approx(-0.284769, abs=1e-5)
    assert lumo == pytest.approx(0.003691, abs=1e-5)
    assert result["chemical_potential"] == pytest.approx(
        (homo + lumo) / 2.0, abs=1e-4)
    assert result["delta"] == pytest.approx(0.1)
    assert result["grid"]["quality"] == 1
    assert result["grid"]["npoints"] > 100000

    # 权重表：f+ 前两个是简并的 LUMO/LUMO+1，各 48.68%
    fp = result["weights"]["fplus"]
    assert fp[0]["index"] == 22 and fp[0]["label"] == "LUMO"
    assert fp[0]["weight"] == pytest.approx(48.68, abs=0.01)
    assert fp[0]["ediff_ev"] == pytest.approx(3.925, abs=0.01)
    assert fp[1]["index"] == 23 and fp[1]["weight"] == pytest.approx(48.68)
    fm = result["weights"]["fminus"]
    assert fm[0]["label"] == "HOMO"
    assert fm[0]["weight"] == pytest.approx(33.33, abs=0.01)
    assert result["total_weight"]["fplus"] == pytest.approx(100.0, abs=0.01)
    assert result["total_weight"]["fminus"] == pytest.approx(100.0, abs=0.01)

    # Hirshfeld 简缩值：12 个原子，f+/f-/f0 求和 ≈ 1，DD 求和 ≈ 0
    cond = result["condensed"]
    assert len(cond) == 12
    assert cond[0]["element"] == "C" and cond[6]["element"] == "H"
    assert cond[0]["fplus"] == pytest.approx(0.14908, abs=1e-4)
    assert cond[0]["fminus"] == pytest.approx(0.15657, abs=1e-4)
    assert cond[0]["f0"] == pytest.approx(0.15283, abs=1e-4)
    assert cond[0]["dd"] == pytest.approx(-0.00748, abs=1e-4)
    assert abs(sum(x["fplus"] for x in cond) - 1.0) < 2e-3
    assert abs(sum(x["fminus"] for x in cond) - 1.0) < 2e-3
    assert abs(sum(x["f0"] for x in cond) - 1.0) < 2e-3
    assert abs(sum(x["dd"] for x in cond)) < 2e-2
    assert result["sums"]["fplus"] == pytest.approx(0.999953, abs=1e-5)
    assert result["sums"]["fminus"] == pytest.approx(0.999965, abs=1e-5)

    # 等值面建议值：OW 量级小，必须在 (0, 0.05) 内且可读
    iso = suggest_iso(result["cubes"]["fplus"])
    assert iso is not None and 0 < iso < 0.05
    assert result["warnings"] == []
