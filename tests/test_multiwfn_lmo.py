# -*- coding: utf-8 -*-
"""``molstudio.core.multiwfn_lmo`` 单元测试（纯文本，无 Qt / 无网络）。

真实 Multiwfn 2026.4.10 输出（``_dev/tmp/lmo_probe``）已裁剪后内嵌为本文件
的字符串常量，因此这些测试不依赖 ``_dev`` 目录；只有最后一个 live 集成测试
按显式 skipif 条件检查本机 Multiwfn / 样本是否存在。
"""

import os
import sys

import pytest

from molstudio.core.multiwfn_lmo import (
    BOHR_TO_ANG,
    COMPOSITION_METHODS,
    DEFAULT_SETTINGS,
    LMO_METHODS,
    LOBA_DEFAULT_SETTINGS,
    build_sequence,
    build_loba_sequence,
    gen_lmo_cube,
    parse_fchk_atoms,
    parse_fragment_spec,
    parse_lmocen,
    parse_loba_output,
    parse_lmo_output,
    run_localization,
    run_loba,
    settings_summary,
)

_MW_EXE = r"E:\Multiwfn_2026.4.10_bin_Win64\Multiwfn.exe"
_LIVE_FCHK = (r"D:\OrbitalViewer 5.3\_dev\tmp\lmo_probe"
              r"\butadiene_ish.fchk")


# ───────────────────────── 内嵌真实输出（已裁剪）─────────────────────────

CLOSED_ENERGY_TEXT = """\
 This is a restricted single-determinant wavefunction
 Orbitals from 1 to    11 are occupied
 Title line of this file: B3LYP/6-31G* opted

 Localizing occupied orbitals...
 Cycle:    1  P:      7.72454010  Delta P:      7.72454010
 Cycle:    2  P:      7.84552017  Delta P:      0.12098007
 Cycle:    3  P:      7.84693685  Delta P:      0.00141667
 Cycle:    4  P:      7.84693984  Delta P:      0.00000299
  Successfully converged!

  Orbital localization took up wall clock time         0 s
  Evaluating orbital energies...

  Energies of localized orbitals:
      1   Energy:  -18.6511197 a.u.    -507.5228 eV   Type: A+B   Occ: 2.0
      2   Energy:  -10.3071249 a.u.    -280.4711 eV   Type: A+B   Occ: 2.0
      3   Energy:   -6.6766996 a.u.    -181.6822 eV   Type: A+B   Occ: 2.0
      4   Energy:   -1.4477802 a.u.     -39.3961 eV   Type: A+B   Occ: 2.0
      5   Energy:   -0.9615636 a.u.     -26.1655 eV   Type: A+B   Occ: 2.0
      6   Energy:   -0.6380324 a.u.     -17.3617 eV   Type: A+B   Occ: 2.0
      7   Energy:   -0.4980917 a.u.     -13.5538 eV   Type: A+B   Occ: 2.0
      8   Energy:   -0.4980865 a.u.     -13.5536 eV   Type: A+B   Occ: 2.0
      9   Energy:   -0.3972686 a.u.     -10.8102 eV   Type: A+B   Occ: 2.0
     10   Energy:   -0.3971912 a.u.     -10.8081 eV   Type: A+B   Occ: 2.0
     11   Energy:   -0.3971912 a.u.     -10.8081 eV   Type: A+B   Occ: 2.0
  Energies of unoccupied orbitals are not updated since they were not localized
  Calculating orbital compositions...

  **** Major character of occupied LMOs:
  Almost single center LMOs: (An atom has contribution > 85.0%)
     1:   2(O ) 99.6%        2:   1(C ) 98.9%        3:   3(B ) 98.3%
     4:   2(O ) 96.2%

  Almost two-center LMOs: (Sum of two largest contributions > 80.0%)
     5:   2(O ) 63.1%   1(C ) 35.5%         6:   1(C ) 66.5%   3(B ) 26.6%
     7:   2(O ) 69.3%   1(C ) 28.7%         8:   2(O ) 69.3%   1(C ) 28.7%
     9:   4(H ) 45.9%   3(B ) 41.8%        10:   5(H ) 45.9%   3(B ) 41.8%
    11:   6(H ) 45.9%   3(B ) 41.8%

  Exporting localized orbitals to new.fch in current folder...
  Exporting .fch file finished! The "Total SCF Density" field in this file corresponds to density matrix at current level
  Loading new.fch...
  Loading finished!
"""

CORE_SKIPPED_TEXT = """\
 This is a restricted single-determinant wavefunction
 Orbitals from 1 to    11 are occupied
 Note: Lowest    3 orbitals are regarded as core orbitals and will not be localized

 Localizing occupied orbitals...
 Cycle:    1  P:      4.63761629  Delta P:      4.63761629
 Cycle:    2  P:      4.72072011  Delta P:      0.08310381
 Cycle:    3  P:      4.73592775  Delta P:      0.01520765
 Cycle:    4  P:      4.73840587  Delta P:      0.00247812
 Cycle:    5  P:      4.73923450  Delta P:      0.00082863
 Cycle:    6  P:      4.73944498  Delta P:      0.00021048
 Cycle:    7  P:      4.73948190  Delta P:      0.00003692
  Successfully converged!

  Energies of localized orbitals:
      4   Energy:   -0.7073191 a.u.     -19.2471 eV   Type: A+B   Occ: 2.0
      5   Energy:   -0.7062141 a.u.     -19.2171 eV   Type: A+B   Occ: 2.0
      6   Energy:   -0.7061848 a.u.     -19.2163 eV   Type: A+B   Occ: 2.0
      7   Energy:   -0.6497515 a.u.     -17.6806 eV   Type: A+B   Occ: 2.0
      8   Energy:   -0.5705768 a.u.     -15.5262 eV   Type: A+B   Occ: 2.0
      9   Energy:   -0.3865959 a.u.     -10.5198 eV   Type: A+B   Occ: 2.0
     10   Energy:   -0.3865151 a.u.     -10.5176 eV   Type: A+B   Occ: 2.0
     11   Energy:   -0.3865151 a.u.     -10.5176 eV   Type: A+B   Occ: 2.0
  Energies of core orbitals are not updated since they were not localized
  Energies of unoccupied orbitals are not updated since they were not localized

  **** Major character of occupied LMOs:
  Almost single center LMOs: (An atom has contribution > 90.0%)
     7:   2(O ) 94.1%

  Almost two-center LMOs: (Sum of two largest contributions > 85.0%)
     4:   2(O ) 67.5%   1(C ) 31.0%         5:   2(O ) 67.5%   1(C ) 31.0%
     6:   2(O ) 67.5%   1(C ) 31.0%         8:   1(C ) 65.2%   3(B ) 27.1%
     9:   4(H ) 46.0%   3(B ) 41.8%        10:   5(H ) 46.0%   3(B ) 41.8%
    11:   6(H ) 46.0%   3(B ) 41.8%

  Exporting localized orbitals to new.fch in current folder...
  Loading new.fch...
  Loading finished!
"""

OCCVIR_TEXT = """\
 This is a restricted single-determinant wavefunction
 Orbitals from 1 to    11 are occupied

 Localizing occupied orbitals...
 Cycle:    1  P:      7.72454010  Delta P:      7.72454010
 Cycle:    4  P:      7.84693984  Delta P:      0.00000299
  Successfully converged!

  Calculating intermediate matrix, please wait...

 Localizing unoccupied orbitals...
 Cycle:    1  P:     61.19757038  Delta P:     61.19757038
 Cycle:    5  P:     70.17618430  Delta P:      0.00004203
  Successfully converged!

  Energies of localized orbitals:
      1   Energy:  -18.6511197 a.u.    -507.5228 eV   Type: A+B   Occ: 2.0
      2   Energy:  -10.3071249 a.u.    -280.4711 eV   Type: A+B   Occ: 2.0
      3   Energy:   -6.6766996 a.u.    -181.6822 eV   Type: A+B   Occ: 2.0
     12   Energy:    0.1599528 a.u.       4.3525 eV   Type: A+B   Occ: 0.0
     13   Energy:    0.1599639 a.u.       4.3528 eV   Type: A+B   Occ: 0.0

  **** Major character of occupied LMOs:
  Almost single center LMOs: (An atom has contribution > 85.0%)
     1:   2(O ) 99.6%        2:   1(C ) 98.9%        3:   3(B ) 98.3%

  Almost two-center LMOs: (Sum of two largest contributions > 80.0%)
     5:   2(O ) 63.1%   1(C ) 35.5%         6:   1(C ) 66.5%   3(B ) 26.6%

  **** Major character of unoccupied LMOs:
  Almost single center LMOs: (An atom has contribution > 85.0%)
    29:   2(O ) 89.6%       30:   2(O ) 89.6%

  Almost two-center LMOs: (Sum of two largest contributions > 80.0%)
    12:   1(C ) 59.4%   2(O ) 28.6%        13:   1(C ) 59.4%   2(O ) 28.6%

  More delocalized LMOs: (Three largest contributions are printed)
    14:    3(B ) 55.0%    4(H ) 13.8%    6(H ) 12.4%

  Exporting localized orbitals to new.fch in current folder...
  Loading new.fch...
  Loading finished!
"""

OPEN_SHELL_TEXT = """\
 This is an unrestricted single-determinant wavefunction
 Orbitals from      1 to    75 are alpha, from     1 to    14 are occupied
 Orbitals from     76 to   150 are beta,  from    76 to    87 are occupied

 Localizing alpha occupied orbitals...
 Cycle:    1  P:     10.62874524  Delta P:     10.62874524
 Cycle:    5  P:     11.48764491  Delta P:      0.00000036
  Successfully converged!

 Localizing beta occupied orbitals...
 Cycle:    1  P:      7.83412495  Delta P:      7.83412495
 Cycle:    4  P:      8.30241177  Delta P:      0.00000704
  Successfully converged!

  Energies of localized orbitals:
      1   Energy:  -18.7379327 a.u.    -509.8851 eV   Type: A     Occ: 1.0
      2   Energy:  -10.2248760 a.u.    -278.2330 eV   Type: A     Occ: 1.0
      3   Energy:  -10.1400424 a.u.    -275.9246 eV   Type: A     Occ: 1.0
      4   Energy:   -1.2562554 a.u.     -34.1844 eV   Type: A     Occ: 1.0
      5   Energy:   -0.6356289 a.u.     -17.2963 eV   Type: A     Occ: 1.0
      6   Energy:   -0.6266281 a.u.     -17.0514 eV   Type: A     Occ: 1.0
      7   Energy:   -0.5629224 a.u.     -15.3179 eV   Type: A     Occ: 1.0
      8   Energy:   -0.5422017 a.u.     -14.7541 eV   Type: A     Occ: 1.0
      9   Energy:   -0.5421902 a.u.     -14.7537 eV   Type: A     Occ: 1.0
     10   Energy:   -0.5034660 a.u.     -13.7000 eV   Type: A     Occ: 1.0
     11   Energy:   -0.5032818 a.u.     -13.6950 eV   Type: A     Occ: 1.0
     12   Energy:   -0.5032803 a.u.     -13.6950 eV   Type: A     Occ: 1.0
     13   Energy:   -0.4742380 a.u.     -12.9047 eV   Type: A     Occ: 1.0
     14   Energy:   -0.2747297 a.u.      -7.4758 eV   Type: A     Occ: 1.0
     76   Energy:  -18.9043275 a.u.    -514.4129 eV   Type: B     Occ: 1.0
     77   Energy:  -10.2181106 a.u.    -278.0489 eV   Type: B     Occ: 1.0
     78   Energy:  -10.1413306 a.u.    -275.9596 eV   Type: B     Occ: 1.0
     79   Energy:   -1.0410384 a.u.     -28.3281 eV   Type: B     Occ: 1.0
     80   Energy:   -0.6990892 a.u.     -19.0232 eV   Type: B     Occ: 1.0
     81   Energy:   -0.6870090 a.u.     -18.6945 eV   Type: B     Occ: 1.0
     82   Energy:   -0.5619878 a.u.     -15.2925 eV   Type: B     Occ: 1.0
     83   Energy:   -0.5437949 a.u.     -14.7974 eV   Type: B     Occ: 1.0
     84   Energy:   -0.5437924 a.u.     -14.7973 eV   Type: B     Occ: 1.0
     85   Energy:   -0.5045907 a.u.     -13.7306 eV   Type: B     Occ: 1.0
     86   Energy:   -0.5015839 a.u.     -13.6488 eV   Type: B     Occ: 1.0
     87   Energy:   -0.5015803 a.u.     -13.6487 eV   Type: B     Occ: 1.0
  Energies of unoccupied orbitals are not updated since they were not localized

  **** Major character of alpha occupied LMOs:
  Almost single center LMOs: (An atom has contribution > 85.0%)
     1:   8(O ) 99.6%        2:   5(C ) 98.9%        3:   1(C ) 98.8%
    13:   8(O ) 88.2%

  Almost two-center LMOs: (Sum of two largest contributions > 80.0%)
     4:   8(O ) 84.4%   9(H )  8.9%         5:   8(O ) 84.8%   9(H )  7.3%
     6:   8(O ) 63.2%   5(C ) 26.6%         7:   5(C ) 45.0%   1(C ) 42.8%
     8:   5(C ) 51.4%   6(H ) 39.8%         9:   5(C ) 51.4%   7(H ) 39.8%
    10:   1(C ) 50.6%   4(H ) 40.6%        11:   1(C ) 51.1%   3(H ) 40.0%
    12:   1(C ) 51.1%   2(H ) 40.0%

  More delocalized LMOs: (Three largest contributions are printed)
    14:    9(H ) 53.0%    8(O ) 20.7%    5(C ) 13.9%

  **** Major character of beta occupied LMOs:
  Almost single center LMOs: (An atom has contribution > 85.0%)
     1:   8(O ) 99.7%        2:   5(C ) 98.9%        3:   1(C ) 98.9%
     4:   8(O ) 93.2%

  Almost two-center LMOs: (Sum of two largest contributions > 80.0%)
     5:   8(O ) 70.3%   9(H ) 25.3%         6:   8(O ) 62.5%   5(C ) 30.3%
     7:   5(C ) 44.5%   1(C ) 43.3%         8:   5(C ) 49.2%   7(H ) 34.5%
     9:   5(C ) 49.2%   6(H ) 34.5%        10:   1(C ) 51.2%   4(H ) 39.6%
    11:   1(C ) 51.1%   3(H ) 39.7%        12:   1(C ) 51.1%   2(H ) 39.7%

  Exporting localized orbitals to new.fch in current folder...
  Exporting .fch file finished! The "Total SCF Density" and "Spin SCF Density" fields in this file correspond to total density matrix and difference between alpha and beta density matrices at current level, respectively
  Loading new.fch...
  Loading finished!
"""

NO_ENERGY_TEXT = """\
 This is a restricted single-determinant wavefunction
 Orbitals from 1 to    11 are occupied

 Localizing occupied orbitals...
 Cycle:    1  P:      7.72454010  Delta P:      7.72454010
 Cycle:    4  P:      7.84693984  Delta P:      0.00000299
  Successfully converged!

  **** Major character of occupied LMOs:
  Almost single center LMOs: (An atom has contribution > 85.0%)
     1:   2(O ) 99.6%        2:   1(C ) 98.9%

  Almost two-center LMOs: (Sum of two largest contributions > 80.0%)
     5:   2(O ) 63.1%   1(C ) 35.5%

  Exporting localized orbitals to new.fch in current folder...
  Loading new.fch...
  Loading finished!
"""

FAILED_TEXT = """\
 This is a restricted single-determinant wavefunction
 Orbitals from 1 to    11 are occupied

 Localizing occupied orbitals...
 Cycle:    1  P:      7.72454010  Delta P:      7.72454010
 Cycle:    2  P:      7.70000000  Delta P:      0.02454010
  Failed to converge in 80 cycles!
"""

CLOSED_LMOCEN_TEXT = """\
 LMO     1 corresponds to Bq     7, X,Y,Z:   -0.0034    2.5088   -0.0000 Bohr
 LMO     2 corresponds to Bq     8, X,Y,Z:   -0.0000    0.3479   -0.0000 Bohr
 LMO    11 corresponds to Bq    17, X,Y,Z:    0.7896   -2.8080    1.3616 Bohr
"""

OPEN_LMOCEN_TEXT = """\
 Alpha LMO     1: Bq    10, X,Y,Z:   -2.2651   -0.4105    0.0000 Bohr
 Alpha LMO    14: Bq    23, X,Y,Z:   -3.1733    1.1029   -0.0000 Bohr
 Beta LMO      1: Bq    24, X,Y,Z:   -2.2653   -0.4069    0.0000 Bohr
 Beta LMO     12: Bq    35, X,Y,Z:    2.1468   -1.5702    1.1197 Bohr
"""

LOBA_TEXT = """\
 Input percentage threshold to determine oxidation states (50 is commonly used)
 Input "m" will determine oxidation states by assigning electron(s) in each orbital to the atom of maximal contribution, which corresponds to modified LOBA (mLOBA)
 Input -1 can define fragment, current: Undefined
 Input 0 can exit
 Oxidation state of atom   1(Fe):  3
 Oxidation state of atom   2(C ) :  2
 Oxidation state of atom   3(C ) :  2
 Oxidation state of atom   4(N ) : -3
 Oxidation state of atom   5(N ) : -3
 The sum of oxidation states:  -3
 Input percentage threshold to determine oxidation states (50 is commonly used)
 Oxidation state of the fragment:  -1
"""


# ───────────────────────────── 闭壳层：能量 + 特征 ─────────────────────────────

def test_closed_shell_energy_and_character():
    r = parse_lmo_output(CLOSED_ENERGY_TEXT)

    assert r["converged"] is True
    assert len(r["sections"]) == 1
    sec = r["sections"][0]
    assert sec["kind"] == "occupied"
    assert sec["converged"] is True
    assert sec["cycles"] == 4
    assert sec["final_delta_p"] == pytest.approx(2.99e-6, rel=1e-3)

    assert r["n_occupied"] == 11
    assert r["n_alpha_total"] == 0
    assert r["n_beta_occupied"] == 0
    assert r["core_skipped"] is False and r["n_core"] == 0

    assert r["threshold_single"] == pytest.approx(0.85)
    assert r["threshold_two"] == pytest.approx(0.80)

    assert len(r["energies"]) == 11
    e1 = r["energies"][0]
    assert e1["index"] == 1
    assert e1["energy_au"] == pytest.approx(-18.6511197)
    assert e1["energy_ev"] == pytest.approx(-507.5228)
    assert e1["spin"] == "A+B"
    assert e1["occ"] == pytest.approx(2.0)

    assert len(r["character"]) == 11
    assert r["character"][1] == {
        "kind": "single", "spin": "A+B",
        "atoms": [{"index": 2, "element": "O", "percent": 99.6}],
    }
    ch5 = r["character"][5]
    assert ch5["kind"] == "two" and ch5["spin"] == "A+B"
    assert [a["index"] for a in ch5["atoms"]] == [2, 1]
    assert [a["percent"] for a in ch5["atoms"]] == pytest.approx([63.1, 35.5])
    ch11 = r["character"][11]
    assert ch11["kind"] == "two"
    assert [a["element"] for a in ch11["atoms"]] == ["H", "B"]

    assert r["exported"] is True
    assert r["reloaded"] is True
    assert r["warnings"] == []


# ───────────────────────── 核心轨道跳过：能量从 4 开始 ─────────────────────────

def test_core_skipped_energies_start_at_four():
    r = parse_lmo_output(CORE_SKIPPED_TEXT)

    assert r["converged"] is True
    assert r["core_skipped"] is True
    assert r["n_core"] == 3
    assert r["n_occupied"] == 11
    assert len(r["energies"]) == 8
    assert [e["index"] for e in r["energies"]] == list(range(4, 12))
    assert r["energies"][0]["energy_au"] == pytest.approx(-0.7073191)
    assert r["energies"][0]["energy_ev"] == pytest.approx(-19.2471)
    assert r["threshold_single"] == pytest.approx(0.90)
    assert r["threshold_two"] == pytest.approx(0.85)
    assert len(r["character"]) == 8
    assert 1 not in r["character"] and 3 not in r["character"]
    assert r["character"][7]["kind"] == "single"
    assert r["character"][7]["atoms"][0]["percent"] == pytest.approx(94.1)
    assert r["character"][4]["kind"] == "two"
    assert [a["percent"] for a in r["character"][4]["atoms"]] == pytest.approx(
        [67.5, 31.0])
    assert r["warnings"] == []


# ───────────────────── 占据 + 非占据：两个 section ─────────────────────

def test_occupied_and_unoccupied_sections_and_character():
    r = parse_lmo_output(OCCVIR_TEXT)

    assert r["converged"] is True
    assert [s["kind"] for s in r["sections"]] == ["occupied", "unoccupied"]
    assert [s["cycles"] for s in r["sections"]] == [4, 5]
    assert all(s["converged"] for s in r["sections"])

    assert [e["index"] for e in r["energies"]] == [1, 2, 3, 12, 13]
    assert r["energies"][3]["occ"] == pytest.approx(0.0)
    assert r["energies"][3]["spin"] == "A+B"

    # 非占据 LMO 的特征用全局编号
    assert r["character"][12]["kind"] == "two"
    assert r["character"][12]["spin"] == "A+B"
    assert [a["element"] for a in r["character"][12]["atoms"]] == ["C", "O"]
    assert r["character"][14]["kind"] == "more"
    assert len(r["character"][14]["atoms"]) == 3
    assert r["character"][29]["kind"] == "single"
    assert r["character"][29]["atoms"][0]["percent"] == pytest.approx(89.6)
    assert r["character"][5]["kind"] == "two"


# ───────────── 开壳层：beta 能量全局编号 + beta 特征每自旋偏移 ─────────────

def test_open_shell_global_beta_energies_and_per_spin_character():
    r = parse_lmo_output(OPEN_SHELL_TEXT)

    assert r["converged"] is True
    assert [s["kind"] for s in r["sections"]] == ["alpha", "beta"]
    assert [s["cycles"] for s in r["sections"]] == [5, 4]
    assert r["n_alpha_total"] == 75
    assert r["n_occupied"] == 14
    assert r["n_beta_occupied"] == 12

    # 能量表里 beta 已是全局编号 76..87
    assert len(r["energies"]) == 26
    beta = [e for e in r["energies"] if e["spin"] == "B"]
    assert [e["index"] for e in beta] == list(range(76, 88))
    assert r["energies"][14]["index"] == 76
    assert r["energies"][14]["energy_au"] == pytest.approx(-18.9043275)
    assert r["energies"][0]["spin"] == "A"

    # 特征块里 beta 从 1 重新开始 → 解析后加 75
    assert len(r["character"]) == 26
    assert 75 not in r["character"]
    assert r["character"][76]["spin"] == "B"
    assert r["character"][76]["kind"] == "single"
    assert r["character"][76]["atoms"][0] == {
        "index": 8, "element": "O", "percent": 99.7}
    assert r["character"][87]["kind"] == "two"
    assert [a["percent"] for a in r["character"][87]["atoms"]] == pytest.approx(
        [51.1, 39.7])
    assert r["character"][1]["spin"] == "A"
    assert r["character"][14]["kind"] == "more"
    assert [a["element"] for a in r["character"][14]["atoms"]] == ["H", "O", "C"]


# ───────────────────────────── 无能量段 / 失败段 ─────────────────────────────

def test_no_energy_section_is_allowed():
    r = parse_lmo_output(NO_ENERGY_TEXT)
    assert r["converged"] is True
    assert r["energies"] == []
    assert r["sections"][0]["kind"] == "occupied"
    assert len(r["character"]) == 3
    assert r["exported"] is True and r["reloaded"] is True


def test_failed_convergence_is_reported_with_warning():
    r = parse_lmo_output(FAILED_TEXT)
    assert r["converged"] is False
    assert len(r["sections"]) == 1
    assert r["sections"][0]["converged"] is False
    assert r["sections"][0]["cycles"] == 2
    assert any("未收敛" in w for w in r["warnings"])


def test_parser_never_raises_on_weird_input():
    for text in ("", "garbage line\nProgress: [###] 12.3 %\n",
                 "forrtl: severe (64): input conversion error, unit 10"):
        r = parse_lmo_output(text)
        assert r["converged"] is False
        assert r["energies"] == []
        assert isinstance(r["warnings"], list)
    assert parse_lmo_output("")["warnings"]
    assert any("forrtl" in w or "Fortran" in w
               for w in parse_lmo_output("forrtl: severe (64)")["warnings"])


# ───────────────────────────── LMOcen.txt 解析 ─────────────────────────────

def test_parse_lmocen_closed_shell():
    r = parse_lmocen(CLOSED_LMOCEN_TEXT)
    assert set(r) == {"closed", "alpha", "beta"}
    assert r["alpha"] == {} and r["beta"] == {}
    assert set(r["closed"]) == {1, 2, 11}
    c1 = r["closed"][1]
    assert c1["bq"] == 7
    assert c1["xyz_bohr"] == pytest.approx((-0.0034, 2.5088, 0.0))
    assert c1["xyz_ang"][0] == pytest.approx(-0.0034 * BOHR_TO_ANG)
    assert c1["xyz_ang"][1] == pytest.approx(2.5088 * BOHR_TO_ANG, rel=1e-12)
    assert r["closed"][11]["bq"] == 17


def test_parse_lmocen_open_shell_is_per_spin():
    r = parse_lmocen(OPEN_LMOCEN_TEXT)
    assert set(r["alpha"]) == {1, 14}
    assert set(r["beta"]) == {1, 12}
    assert r["alpha"][1]["bq"] == 10
    assert r["beta"][1]["bq"] == 24
    assert r["beta"][12]["bq"] == 35
    # Beta 的键是每自旋编号，不是全局 76/87
    assert 76 not in r["beta"] and 87 not in r["beta"]
    assert r["beta"][1]["xyz_bohr"] == pytest.approx((-2.2653, -0.4069, 0.0))


def test_parse_lmocen_empty_and_garbage():
    assert parse_lmocen("") == {"closed": {}, "alpha": {}, "beta": {}}
    assert parse_lmocen("not a lmo center line\n") == {
        "closed": {}, "alpha": {}, "beta": {}}


# ───────────────────────────── build_sequence ─────────────────────────────

def test_build_sequence_default():
    seq = build_sequence(dict(DEFAULT_SETTINGS))
    assert seq == "\n19\n-4\n1\n1\nq\n"
    # 默认设置不发送 -6 / -9 / -10 / -8 / -5 / -2 / -1
    for token in ("-6\n", "-9\n", "-10\n", "-8\n", "-5\n", "-2\n", "-1\n"):
        assert token not in seq


def test_build_sequence_all_non_default():
    seq = build_sequence({
        "method": "foster_boys",
        "scope": "both",
        "calc_energy": True,
        "energy_source": "file",
        "fock_file": r"C:\tmp\fock.out",
        "composition": "becke",
        "threshold_single": 0.90,
        "threshold_two": 0.85,
        "localize_core": False,
        "centers": True,
        "dipole": True,
        "convergence": 2e-4,
        "max_cycles": 120,
    })
    assert seq == ("\n19\n-6\n10\n-4\n2\nC:\\tmp\\fock.out\n-9\n3\n"
                   "-10\n0.9,0.85\n-8\n-5\n-2\n0.0002\n-1\n120\n2\ny\nq\n")


def test_build_sequence_energy_from_file_includes_path():
    seq = build_sequence({"energy_source": "file",
                          "fock_file": r"D:\data\fock_ks.mwfn"})
    assert "-4\n2\nD:\\data\\fock_ks.mwfn\n" in seq
    # MO 方式则不应出现文件路径子选项
    seq_mo = build_sequence({"energy_source": "mo"})
    assert "-4\n1\n" in seq_mo and "-4\n2\n" not in seq_mo


def test_build_sequence_centers_and_dipole_y_n_ordering():
    seq_y = build_sequence({"centers": True, "dipole": True})
    assert "-8\n" in seq_y
    assert seq_y.endswith("1\ny\nq\n")

    seq_n = build_sequence({"centers": True, "dipole": False})
    assert seq_n.endswith("1\nn\nq\n")

    # centers 关闭时即使 dipole=True 也不能发 y/n（否则被主菜单吃掉）
    seq_off = build_sequence({"centers": False, "dipole": True})
    assert "-8\n" not in seq_off
    assert "y\n" not in seq_off
    assert seq_off.endswith("1\nq\n")


def test_build_sequence_core_toggle_and_energy_off():
    seq_core_off = build_sequence({"localize_core": False})
    assert "-5\n" in seq_core_off
    assert "-5\n" not in build_sequence({"localize_core": True})

    seq_no_energy = build_sequence({"calc_energy": False})
    assert "-4\n" not in seq_no_energy
    assert seq_no_energy == "\n19\n1\nq\n"


def test_build_sequence_scope_and_method_defaults():
    assert "\n-6\n" not in build_sequence({"method": "pm_mulliken"})
    assert "-6\n10\n" in build_sequence({"method": "foster_boys"})
    assert build_sequence({"scope": "both"}).endswith("2\nq\n")
    assert build_sequence({"scope": "occupied"}).endswith("1\nq\n")
    # 阈值误传百分数也能规整成 Multiwfn 要的分数
    assert "-10\n0.9,0.85\n" in build_sequence(
        {"threshold_single": 90, "threshold_two": 85})


def test_build_sequence_rejects_unknown_settings():
    with pytest.raises(ValueError):
        build_sequence({"method": "nope"})
    with pytest.raises(ValueError):
        build_sequence({"scope": "virial"})


def test_settings_summary_zh_en():
    zh = settings_summary(dict(DEFAULT_SETTINGS))
    assert "Pipek" in zh and "85" in zh and "80" in zh and "Hirshfeld" in zh
    en = settings_summary({"method": "foster_boys"}, lang="en")
    assert "Foster" in en and "occupied only" in en


# ───────────────────────────── LOBA / mLOBA ─────────────────────────────

def test_loba_parse_atoms_sum_and_fragment():
    result = parse_loba_output(LOBA_TEXT)
    assert [atom["index"] for atom in result["atoms"]] == [1, 2, 3, 4, 5]
    assert result["atoms"][0] == {
        "index": 1, "element": "Fe", "oxidation_state": 3.0}
    assert result["atoms"][3]["oxidation_state"] == -3.0
    assert result["sum"] == -3.0
    assert result["fragment_oxidation_state"] == -1.0
    assert result["warnings"] == []


def test_loba_parse_empty_or_weird_never_raises():
    for text in ("", "not LOBA output\n", "forrtl: severe (59)"):
        result = parse_loba_output(text)
        assert result["atoms"] == []
        assert isinstance(result["warnings"], list)
        assert result["warnings"]


def test_loba_sequence_loba_mloba_and_fragment():
    assert build_loba_sequence(LOBA_DEFAULT_SETTINGS) == (
        "\n8\n100\n50\n0\n-10\nq\n")
    assert build_loba_sequence({
        "method": "loba", "threshold": 70, "fragment": "1-3,5"
    }) == "\n8\n100\n-1\n1-3,5\n70\n0\n-10\nq\n"
    assert build_loba_sequence({"method": "mloba"}) == (
        "\n8\n100\nm\n0\n-10\nq\n")
    assert build_loba_sequence({
        "method": "mloba", "fragment": "1-3"
    }) == "\n8\n100\n-1\n1-3\nm\n0\n-10\nq\n"


def test_parse_fragment_spec_normalizes_and_validates():
    assert parse_fragment_spec("1, 3-5, 4, 9") == "1,3-5,9"
    assert parse_fragment_spec("1，3–5") == "1,3-5"
    assert parse_fragment_spec("") == ""
    assert parse_fragment_spec("1-3", n_atoms=3) == "1-3"
    with pytest.raises(ValueError, match="从 1"):
        parse_fragment_spec("0-2")
    with pytest.raises(ValueError, match="起点"):
        parse_fragment_spec("5-2")
    with pytest.raises(ValueError, match="超出"):
        parse_fragment_spec("1-4", n_atoms=3)


def test_parse_fchk_atoms_and_charge(tmp_path):
    path = tmp_path / "sample.fch"
    path.write_text(
        "Number of atoms                            I                6\n"
        "Charge                                     I               -2\n"
        "Atomic numbers                             I   N=           6\n"
        "           6           8           5           1           1           1\n",
        encoding="utf-8")
    info = parse_fchk_atoms(str(path))
    assert info["n_atoms"] == 6
    assert info["charge"] == -2
    assert info["atomic_numbers"] == [6, 8, 5, 1, 1, 1]
    assert info["elements"] == ["C", "O", "B", "H", "H", "H"]


# ───────────────────────── run_localization 校验路径 ─────────────────────────

def test_run_localization_missing_fchk_raises():
    with pytest.raises(RuntimeError, match="找不到 fchk"):
        run_localization(str(os.path.join("no_such_dir", "x.fchk")),
                         sys.executable)


def test_run_localization_missing_exe_raises(tmp_path):
    fchk = tmp_path / "mol.fchk"
    fchk.write_text("dummy", encoding="utf-8")
    with pytest.raises(RuntimeError, match="找不到 Multiwfn"):
        run_localization(str(fchk), str(tmp_path / "nope.exe"))


def test_run_localization_energy_file_without_path_raises(tmp_path):
    fchk = tmp_path / "mol.fchk"
    fchk.write_text("dummy", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Fock"):
        run_localization(str(fchk), sys.executable,
                         {"energy_source": "file", "fock_file": ""})


def test_run_localization_cancel_before_start_returns_not_ok(tmp_path):
    fchk = tmp_path / "mol.fchk"
    fchk.write_text("dummy", encoding="utf-8")
    res = run_localization(str(fchk), sys.executable,
                           {"calc_energy": False}, out_dir=str(tmp_path),
                           cancel_check=lambda: True)
    assert res["ok"] is False
    assert res["error"] == "已取消"
    assert res["energies"] == []


# ───────────────────────── run_loba 校验路径 ─────────────────────────

def test_run_loba_missing_fchk_raises():
    with pytest.raises(RuntimeError, match="找不到 LMO"):
        run_loba(str(os.path.join("no_such_dir", "x_LMO.fch")),
                 sys.executable)


def test_run_loba_missing_exe_raises(tmp_path):
    fchk = tmp_path / "mol_LMO.fch"
    fchk.write_text(
        "Number of atoms                            I                1\n"
        "Charge                                     I                0\n"
        "Atomic numbers                             I   N=           1\n"
        "           6\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="找不到 Multiwfn"):
        run_loba(str(fchk), str(tmp_path / "nope.exe"))


def test_run_loba_validates_fragment_against_atom_count(tmp_path):
    fchk = tmp_path / "mol_LMO.fch"
    fchk.write_text(
        "Number of atoms                            I                1\n"
        "Charge                                     I                0\n"
        "Atomic numbers                             I   N=           1\n"
        "           6\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="片段"):
        run_loba(str(fchk), sys.executable,
                 {"fragment": "1-2"})


# ───────────────────────────── live 集成测试（可选）─────────────────────────

@pytest.mark.skipif(
    not os.path.exists(_MW_EXE) or not os.path.exists(_LIVE_FCHK),
    reason="Multiwfn/sample unavailable")
def test_live_run_localization_occupied_with_energies(tmp_path):
    result = run_localization(
        _LIVE_FCHK, _MW_EXE,
        {"scope": "occupied", "calc_energy": True, "centers": False},
        out_dir=str(tmp_path), timeout=300)

    assert result["ok"], result["error"]
    assert result["converged"] is True
    assert len(result["energies"]) >= 1
    assert result["sections"][0]["kind"] == "occupied"
    assert (tmp_path / "butadiene_ish_LMO.fch").is_file()
    assert (tmp_path / "butadiene_ish_LMO.log").is_file()
    assert result["lmo_fch"].endswith("butadiene_ish_LMO.fch")


_LIVE_LOBA_FCH = (r"D:\OrbitalViewer 5.3\_dev\tmp\lmo_probe\new.fch")


@pytest.mark.skipif(
    not os.path.exists(_MW_EXE) or not os.path.exists(_LIVE_LOBA_FCH),
    reason="Multiwfn/localized sample unavailable")
def test_live_run_loba_with_fragment(tmp_path):
    result = run_loba(
        _LIVE_LOBA_FCH, _MW_EXE,
        {"method": "loba", "threshold": 50, "fragment": "1-3"},
        out_dir=str(tmp_path), timeout=120)

    assert result["ok"], result["error"]
    assert len(result["atoms"]) == 6
    assert result["sum"] == pytest.approx(8.0)
    assert result["fragment_oxidation_state"] == pytest.approx(-3.0)
    assert result["net_charge"] == 0
    assert (tmp_path / "new_LOBA.log").is_file()


# gen_lmo_cube 的输入校验不需要真的跑 Multiwfn
def test_gen_lmo_cube_returns_none_for_missing_input(tmp_path):
    assert gen_lmo_cube(str(tmp_path / "missing.fch"), 1) is None
    assert gen_lmo_cube(str(tmp_path / "missing.fch"), 0) is None


def test_build_sequence_energy_from_file_without_path_raises():
    """energy_source='file' 却没给 Fock 文件时不能悄悄退回 MO 方式。"""
    with pytest.raises(ValueError, match="energy_source"):
        build_sequence({"energy_source": "file", "fock_file": ""})


def test_gen_lmo_cube_failure_never_returns_stale_cube(tmp_path):
    """生成失败时必须返回 None，且不能留下/返回上一次的同名 cube。

    回归：旧实现复用 ``fchk_orbital.gen_cube`` 的固定 ``_multiwfn_tmp``
    目录，失败时会拿到残留的 MOvalue.cub 并改名成新 LMO 的 cube。
    """
    fchk = tmp_path / "Mol_LMO.fch"
    fchk.write_text("not a real fchk", encoding="utf-8")
    stale = tmp_path / "Mol_LMO5.cub"
    stale.write_bytes(b"STALE_CUBE_MARKER" * 8)

    cube = gen_lmo_cube(str(fchk), 5, multiwfn_exe=sys.executable,
                        work_dir=str(tmp_path), timeout=20)

    assert cube is None
    assert not stale.exists(), "失败后陈旧 cube 必须被清理，不能冒充本次产物"


def test_gen_lmo_cube_requires_existing_exe(tmp_path):
    fchk = tmp_path / "Mol_LMO.fch"
    fchk.write_text("dummy", encoding="utf-8")
    assert gen_lmo_cube(str(fchk), 5, multiwfn_exe=str(tmp_path / "no.exe"),
                        work_dir=str(tmp_path)) is None

