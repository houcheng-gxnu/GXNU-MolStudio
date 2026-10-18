# -*- coding: utf-8 -*-
"""AICD 的 Gaussian 输入生成器：格式约定要卡住，跑不了的任务等于没生成。

重点守三件事（都是踩过的坑）：
  1. 路由里 ``nmr=csgt`` 与 ``iop(10/93=…)`` 必须同时出现；
  2. 张量文件名必须**在几何之后**（Gaussian 按位置读，放前面会被当坐标）；
  3. ``iop(10/93=2)`` 时轨道编号跟在张量名之后。
"""

from molstudio.panels.aicd_input import build_aicd_input, parse_structure_file
from molstudio.panels.aicd_input import parse_gjf_settings
from molstudio.panels.aicd_input import rewrite_with_orbitals
from molstudio.panels.aicd_input import parse_structure_file
from molstudio.core.multiwfn_pi import format_orbital_ranges, parse_pi_output
from molstudio.core.multiwfn_pi import parse_pi_projection
from molstudio.core import aicd as A

ATOMS = [("C", 0.0, 1.390788, 0.0),
         ("H", 0.0, 2.472882, 0.0)]


def _route(text):
    return [ln for ln in text.splitlines() if ln.startswith("#")][0]


def test_all_electron_route():
    route = _route(build_aicd_input(ATOMS))
    assert "nmr=csgt" in route
    assert "iop(10/93=1)" in route


def test_orbital_mode_route():
    route = _route(build_aicd_input(ATOMS, mode="orbs", orbitals="17,20,21"))
    assert "iop(10/93=2)" in route


def test_tensor_name_after_geometry():
    text = build_aicd_input(ATOMS, tensor_name="test.txt")
    lines = text.splitlines()
    last_coord = max(i for i, ln in enumerate(lines)
                     if ln[:1] in ("C", "H"))
    assert lines.index("test.txt") > last_coord


def test_orbitals_follow_tensor_name():
    text = build_aicd_input(ATOMS, mode="orbs", orbitals="1-16,18-19")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert lines[-1] == "1-16,18-19"
    assert lines[-2] == "test.txt"
    # 列表后必须有一个空行，否则 Gaussian 会漏读最后一个轨道
    assert text.endswith("\n\n")


def test_link0_lines_and_title():
    text = build_aicd_input(ATOMS, chk="benzene.chk", mem="4GB", nproc=8,
                            title="Benzene AICD")
    lines = text.splitlines()
    assert lines[0] == "%chk=benzene.chk"
    assert "%mem=4GB" in lines
    assert "%nprocshared=8" in lines
    assert "Benzene AICD" in lines
    assert "0 1" in lines


def test_xyz_parsing(tmp_path):
    path = tmp_path / "benzene.xyz"
    path.write_text("2\nbenzene\nC 0.0 1.390788 0.0\nH 0.0 2.472882 0.0\n",
                    encoding="utf-8")
    atoms = parse_structure_file(str(path))
    assert [a[0] for a in atoms] == ["C", "H"]
    assert abs(atoms[1][2] - 2.472882) < 1e-9


def test_gjf_parsing(tmp_path):
    gjf = ("%chk=x.chk\n# b3lyp/6-31g(d)\n\ntitle\n\n0 1\n"
           " C 0.0 1.390788 0.0\n H 0.0 2.472882 0.0\n\n")
    path = tmp_path / "x.gjf"
    path.write_text(gjf, encoding="utf-8")
    atoms = parse_structure_file(str(path))
    assert [a[0] for a in atoms] == ["C", "H"]


# ── Multiwfn 的 π 轨道检测输出（苯，真实输出截取） ────────────────────────
MW_PI_SNIPPET = """
 Choose current situation:
 -1: Orbitals are in localized form (e.g. LMO, NBO)
  0: Orbitals are in delocalized form (e.g. MO, natural orbital, NTO). The system must be exactly planar
 This system is expected to be in XY plane
 Expected pi orbitals, occupation numbers and orbital energies (eV):
    17      2.000000     -9.826988
    20      2.000000     -6.717998
    21      2.000000     -6.717998
    22      0.000000      0.135922
    23      0.000000      0.135922
 Total number of pi orbitals:    24
 Total number of electrons in pi orbitals:    6.000000
 Total number of inner-core electrons:    12
 Indices of occupied pi orbitals:
 17,20,21

 How to deal with these orbitals?
 0 Do nothing
"""


def test_parse_pi_output_basic():
    info = parse_pi_output(MW_PI_SNIPPET)
    assert info["plane_hint"] == "XY"
    assert info["n_pi_all"] == 24
    assert info["pi_occupied_str"] == "17,20,21"
    assert info["pi_all"][0] == (17, 2.0, -9.826988)


def test_parse_pi_output_sigma_is_complement_of_occupied():
    """σ = 占据轨道减去 π。没有 'Orbitals from 1 to 21 are occupied' 时就不给 σ。"""
    with_occ = (" Orbitals from 1 to    21 are occupied\n" + MW_PI_SNIPPET)
    info = parse_pi_output(with_occ)
    assert info["n_occupied"] == 21
    assert info["sigma_occupied_str"] == "1-16,18-19"
    # 拿不到占据数就不知道 σ 是什么，宁可不给（免得填错编号）
    assert parse_pi_output(MW_PI_SNIPPET)["sigma_occupied_str"] == ""


def test_format_orbital_ranges():
    assert format_orbital_ranges([1, 2, 3, 5, 6, 9]) == "1-3,5-6,9"
    assert format_orbital_ranges([7]) == "7"
    assert format_orbital_ranges([]) == ""


# ── 非平面体系：定域化 + π 型 LMO 投影（真实输出截取，苯） ────────────────
MW_PROJECTION_SNIPPET = """
 Input a file containing other set of orbitals, e.g. C:\\riko.fch
 Input threshold for printing (%), e.g. 85
 If pressing ENTER button directly, 50% will be employed as the threshold
 Orbital    17 (Occ= 2.00000)   pi composition: 100.000%
 Orbital    20 (Occ= 2.00000)   pi composition: 100.000%
 Orbital    21 (Occ= 2.00000)   pi composition: 100.000%
 Orbital    23 (Occ= 2.00000)   pi composition: 82.500%
 Orbital    24 (Occ= 0.00000)   pi composition: 95.000%

 Note: Current wavefunction corresponds to the file just loaded
 Orbitals from 1 to    21 are occupied
"""


def test_parse_pi_projection_keeps_occupied_above_threshold():
    parsed = parse_pi_projection(MW_PROJECTION_SNIPPET)
    comp = parsed["composition"]
    assert comp[17] == (2.0, 100.0)
    assert parsed["n_occupied"] == 21
    # 只有"占据 + π 成份过阈值"的才算 π 轨道（空轨道 24 与低成份的不算）
    occupied_pi = sorted(o for o, (occ, pct) in comp.items()
                         if occ > 0 and pct >= 80)
    assert occupied_pi == [17, 20, 21, 23]


def test_gjf_settings_roundtrip(tmp_path):
    """生成器写出的 gjf 必须能被自己读回来（载入 gjf → 预填 这条主流程靠它）。"""
    atoms = [("C", 0.0, 1.390788, 0.0), ("H", 0.0, 2.472882, 0.0)]
    text = build_aicd_input(atoms, chk="benzene_pi.chk", mem="4GB", nproc=4,
                            mode="orbs", orbitals="17,20,21",
                            title="Benzene AICD pi")
    path = tmp_path / "benzene_pi.gjf"
    path.write_text(text + "\n", encoding="utf-8")
    info = parse_gjf_settings(str(path))
    assert info["charge"] == 0 and info["mult"] == 1
    assert info["method"] == "b3lyp/6-31g(d)"
    assert info["mode"] == "orbs" and info["orbitals"] == "17,20,21"
    assert info["chk"] == "benzene_pi.chk" and info["mem"] == "4GB"
    assert info["nproc"] == 4 and info["tensor"] == "test.txt"
    assert len(info["atoms"]) == 2


def test_gjf_settings_reads_preset_and_keeps_extra(tmp_path):
    text = ("%chk=a.chk\n# wb97xd/def2-tzvp int(grid=ultrafine) nmr=csgt "
            "iop(10/93=1)\n\ntitle\n\n0 1\n C 0 0 0\n H 0 0 1.09\n\ntest.txt\n")
    path = tmp_path / "a.gjf"
    path.write_text(text, encoding="utf-8")
    info = parse_gjf_settings(str(path))
    assert info["method"] == "wb97xd/def2-tzvp"
    assert "int(grid=ultrafine)" in info["extra"]
    assert info["mode"] == "all"


# ── GaussView 的 geom=connectivity 输入（用户实测踩到的坑） ──────────────
GAUSSVIEW_GJF = """%chk=D:\\current\\py.chk
# b3lyp/6-31g** geom=connectivity

Title Card Required

0 1
 C                  1.14417939   -0.43181412    0.00019700
 C                  2.55105739   -0.43181412    0.00019700
 N                  0.40094339    0.69182388    0.00000000

 1 2 1.5 6 1.5 8 1.0
 2 3 1.5 9 1.0
 3
 4
"""


def test_connectivity_table_is_not_mistaken_for_atoms(tmp_path):
    """连通性表每行也是"≥4 字段 + 三个浮点"，不能按坐标读。

    踩过的坑：被当成原子读进去后，元素符号成了 "1"，生成出一份跑不了的输入
    （Gaussian 报 Wanted a floating point number as input），而且张量文件名
    那一行会被连通性表的残行顶掉，任务白跑。
    """
    path = tmp_path / "py.gjf"
    path.write_text(GAUSSVIEW_GJF, encoding="utf-8")
    info = parse_gjf_settings(str(path))
    assert [a[0] for a in info["atoms"]] == ["C", "C", "N"]
    assert len(info["connectivity"]) == 4
    assert info["extra"] == "geom=connectivity"
    assert parse_structure_file(str(path))[0][0] == "C"


def test_connectivity_block_written_before_tensor_name(tmp_path):
    path = tmp_path / "py.gjf"
    path.write_text(GAUSSVIEW_GJF, encoding="utf-8")
    info = parse_gjf_settings(str(path))
    out = build_aicd_input(info["atoms"], method=info["method"],
                           extra=info["extra"], charge=info["charge"],
                           mult=info["mult"], tensor_name="test.txt",
                           connectivity=info["connectivity"])
    assert "geom=connectivity" in out and "nmr=csgt" in out
    assert " 1 2 1.5 6 1.5 8 1.0" in out.replace("1 2 1.5", " 1 2 1.5")
    # 顺序：坐标 → 连通性表 → 张量文件名（张量名若排在连通性前面会被读掉）
    assert out.index("test.txt") > out.index("1 2 1.5 6 1.5 8 1.0")


def test_connectivity_keyword_dropped_when_block_missing():
    """路由里有 geom=connectivity 却没给表：宁可去掉这个关键词，也别交一份
    必然报错的输入（Gaussian 会把后面的段当连通性表读）。"""
    out = build_aicd_input([("C", 0.0, 0.0, 0.0)], extra="geom=connectivity")
    assert "geom=connectivity" not in out
    assert "nmr=csgt" in out


def test_rewrite_with_orbitals_keeps_connectivity_and_adds_blank():
    """π-only 第二遍：切到 iop(10/93=2)、末尾写轨道号 + 空行。

    真正会漏轨道的是**轨道列表后没有空行**（用户 ph-aicd / ph-acid2 实例：
    ``17,20,21`` 只算 17、20，π 等值面裂成六瓣）；连通性表本身无害，
    这里确认它仍被保留。
    """
    text = ("%chk=x.chk\n# b3lyp/6-31g** geom=connectivity nmr=csgt "
            "iop(10/93=1)\n\nt\n\n0 1\n C 0 0 0\n C 1.4 0 0\n N 2.1 0 0\n\n"
            " 1 2 1.5\n 2 3 1.5\n")
    out = rewrite_with_orbitals(text, "17,20,21")
    assert "iop(10/93=2)" in out
    assert "iop(10/93=1)" not in out
    assert "geom=connectivity" in out
    assert "1 2 1.5" in out
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert lines[-1] == "17,20,21"
    assert lines[-2] == "test.txt"
    assert out.endswith("\n\n")


def test_orbs_mode_keeps_connectivity_and_adds_blank():
    """iop(10/93=2) 也保留连通性表；末尾空行才是关键。"""
    out = build_aicd_input(
        ATOMS, extra="geom=connectivity", mode="orbs",
        orbitals="17,20,21", connectivity=["1 2 1.5 3 1.0", "2 3 1.5"])
    assert "geom=connectivity" in out
    assert "1 2 1.5" in out
    assert "iop(10/93=2)" in out
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert lines[-1] == "17,20,21"
    assert lines[-2] == "test.txt"
    assert out.endswith("\n\n")


# ── 张量文件定位：任务半路失败时绝不拿别的任务的 txt 凑数 ────────────────

def test_find_tensor_file_requires_the_log_marker(tmp_path):
    # 目录里有一个 AICD 格式的 txt（别的任务留下的），但这条日志没走到 NMR
    (tmp_path / "test.txt").write_text(" Gitterpunkte:\n 1 2 3\n",
                                       encoding="utf-8")
    log = tmp_path / "failed.log"
    log.write_text(" SCF Done\n No executable for file l801.exe.\n",
                   encoding="utf-8")
    assert A.find_tensor_file(str(log)) is None


def test_find_tensor_file_uses_recorded_name(tmp_path):
    (tmp_path / "azulene_aicd.txt").write_text(" Gitterpunkte:\n",
                                               encoding="utf-8")
    log = tmp_path / "azulene.log"
    log.write_text(' Writing AICD formatted file "azulene_aicd.txt"\n',
                   encoding="utf-8")
    assert A.find_tensor_file(str(log)) == str(tmp_path / "azulene_aicd.txt")
