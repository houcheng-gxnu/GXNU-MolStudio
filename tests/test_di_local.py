# -*- coding: utf-8 -*-
"""DI 本机工作流核心（molstudio.core.di_local）的单元测试。

覆盖：route/电荷解析、fchk 提示、结构读取（fchk/log/xyz/gjf）、成键与连通
分量、碎片校验、范围串互转、碎片 route 生成、4 个 gjf 的写出，以及
monkeypatch 掉 run_gaussian 后的本机运行（成功/失败/取消/日志过滤）。

真实测试数据：
    D:\\test-est\\DA-5.fchk —— C4H6 + C2H4 的 TS 复合物（16 原子）
    D:\\test-est\\di_local_test\\ts_opt\\DA-5_TS.log —— 对应 TS 任务的 Gaussian 日志
"""

import os

import pytest

from molstudio.core import di_local
from molstudio.core.di_local import (
    BOHR_TO_ANGSTROM,
    DiLocalCancelled,
    build_fragment_route,
    connected_components,
    fchk_route_hint,
    format_ranges,
    get_bonds_from_atoms,
    parse_charge_multiplicity,
    parse_ranges,
    parse_route_section,
    prepare_di_jobs,
    read_structure,
    run_di_jobs,
    validate_fragments,
)
from molstudio.core.gaussian_run import GaussianJobResult

FCHK_PATH = r"D:\test-est\DA-5.fchk"
TS_LOG_PATH = r"D:\test-est\di_local_test\ts_opt\DA-5_TS.log"

_needs_fchk = pytest.mark.skipif(
    not os.path.isfile(FCHK_PATH),
    reason="缺少测试数据 %s" % FCHK_PATH)
_needs_ts_log = pytest.mark.skipif(
    not os.path.isfile(TS_LOG_PATH),
    reason="缺少测试数据 %s" % TS_LOG_PATH)

#: 真实的 TS route（不含 '#'，即 parse_route_section 的返回形态）
ROUTE = "p opt=(ts,calcfc,noeigentest) freq m06l/def2svp int=ultrafine"

#: 一个简单的 4 原子"分子"（C-H ... O-H）
ATOMS = [
    (1, "C", 6, (0.0, 0.0, 0.0)),
    (2, "H", 1, (1.0, 0.0, 0.0)),
    (3, "O", 8, (5.0, 0.0, 0.0)),
    (4, "H", 1, (6.0, 0.0, 0.0)),
]


# ── 测试辅助 ─────────────────────────────────────────────────────────

def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def _route_log(route_lines):
    """构造带 Gaussian 风格 route 横幅的日志文本。"""
    body = "".join(" " + line + "\n" for line in route_lines)
    return (
        " Entering Gaussian System\n"
        " %chk=job.chk\n"
        " --------------------------------------------------------------\n"
        + body +
        " --------------------------------------------------------------\n"
        " 1/5=1,10=4,11=1,18=20,26=4,38=1/1,3;\n"
        " 2/9=110,12=2,17=6,18=5,40=1/2;\n"
    )


def _log_orientation(kind, rows):
    """构造一个 Gaussian orientation 表（rows: center, atomic_number, x, y, z）。"""
    lines = [
        kind + ":",
        " ---------------------------------------------------------------------",
        " Center     Atomic      Atomic             Coordinates (Angstroms)",
        " Number     Number       Type             X           Y           Z",
        " ---------------------------------------------------------------------",
    ]
    for center, atomic_number, x, y, z in rows:
        lines.append(" %6d %6d %6d %14.6f %14.6f %14.6f" %
                     (center, atomic_number, 0, x, y, z))
    lines.append(" ---------------------------------------------------------------------")
    lines.append("")
    return "\n".join(lines)


def _minimal_fchk_text():
    """一个含 2 个原子（C、H）的最小 fchk 文本（坐标为 Bohr）。"""
    return (
        "synthetic fchk\n"
        "SP        RHF                                                          "
        "STO-3G             \n"
        "Atomic numbers                             I   N=           2\n"
        "           6           1\n"
        "Current cartesian coordinates              R   N=           6\n"
        "  0.00000000E+00  0.00000000E+00  0.00000000E+00  "
        "1.88972612E+00  0.00000000E+00  0.00000000E+00\n"
    )


def _fake_exe(tmp_path):
    exe = tmp_path / "g16.exe"
    exe.write_bytes(b"")
    return str(exe)


def _fake_jobs(tmp_path):
    return prepare_di_jobs(ATOMS, {1, 2}, {3, 4}, str(tmp_path), "sys", ROUTE)


# ── route / 电荷解析 ─────────────────────────────────────────────────

def test_parse_route_section_single_line(tmp_path):
    path = _write(tmp_path, "single.log", _route_log(
        ["#p opt=(ts,calcfc,noeigentest) freq m06l/def2svp int=ultrafine"]))
    assert parse_route_section(path) == ROUTE


def test_parse_route_section_joins_continuation_lines(tmp_path):
    path = _write(tmp_path, "multi.log", _route_log([
        "#p opt freq m06l/def2svp",
        "int=ultrafine",
        "scrf=(pcm,solvent=water)",
    ]))
    assert parse_route_section(path) == (
        "p opt freq m06l/def2svp int=ultrafine scrf=(pcm,solvent=water)")


def test_parse_route_section_stops_at_blank_line(tmp_path):
    path = _write(tmp_path, "blank.log",
                  " #p m06l/def2svp\n\n #p freq hf/sto-3g\n")
    assert parse_route_section(path) == "p m06l/def2svp"


def test_parse_route_section_absent_returns_empty(tmp_path):
    path = _write(tmp_path, "no_route.log",
                  " Entering Gaussian System\n Normal termination\n")
    assert parse_route_section(path) == ""


@_needs_ts_log
def test_parse_route_section_real_log():
    assert parse_route_section(TS_LOG_PATH) == ROUTE


def test_parse_charge_multiplicity_last_line_wins(tmp_path):
    path = _write(tmp_path, "charge.log",
                  " Charge =  0 Multiplicity = 1\n"
                  " SCF Done: E(RM06L) = -123.456\n"
                  " Charge = -1 Multiplicity = 3\n")
    assert parse_charge_multiplicity(path) == (-1, 3)


def test_parse_charge_multiplicity_absent(tmp_path):
    path = _write(tmp_path, "no_charge.log", " Gaussian 16\n Normal termination\n")
    assert parse_charge_multiplicity(path) is None


@_needs_ts_log
def test_parse_charge_multiplicity_real_log():
    assert parse_charge_multiplicity(TS_LOG_PATH) == (0, 1)


# ── fchk route 提示 ──────────────────────────────────────────────────

@_needs_fchk
def test_fchk_route_hint_real_file():
    # 实测 G16 formchk 输出的 method 字段更宽，基组在第 71 列起
    assert fchk_route_hint(FCHK_PATH) == "RM06L/def2SVP"


def test_fchk_route_hint_standard_columns(tmp_path):
    line2 = "%-10s%-30s%-30s" % ("SP", "B3LYP", "6-31G(d)")
    path = _write(tmp_path, "std.fchk", "title card\n" + line2 + "\n")
    assert fchk_route_hint(path) == "B3LYP/6-31G(d)"


def test_fchk_route_hint_missing_or_malformed(tmp_path):
    assert fchk_route_hint(str(tmp_path / "does_not_exist.fchk")) == ""
    assert fchk_route_hint(_write(tmp_path, "short.fchk", "only title\n")) == ""
    assert fchk_route_hint(_write(tmp_path, "blank2.fchk",
                                  "title\n\nAtomic numbers\n")) == ""


# ── 结构读取 ─────────────────────────────────────────────────────────

@_needs_fchk
def test_read_structure_real_fchk():
    atoms = read_structure(FCHK_PATH)
    assert len(atoms) == 16
    assert [atom[0] for atom in atoms] == list(range(1, 17))
    assert "".join(atom[1] for atom in atoms) == "CHHCHCHCHHCHHCHH"
    assert [atom[2] for atom in atoms] == [
        6, 1, 1, 6, 1, 6, 1, 6, 1, 1, 6, 1, 1, 6, 1, 1]
    # Bohr → Å 换算抽查（原始值 -8.27412264E-01 Bohr）
    x, y, z = atoms[0][3]
    assert x == pytest.approx(-0.827412264 * BOHR_TO_ANGSTROM, abs=1e-12)
    assert y == pytest.approx(-2.69302594 * BOHR_TO_ANGSTROM, abs=1e-12)
    assert z == pytest.approx(0.927570381 * BOHR_TO_ANGSTROM, abs=1e-12)


def test_read_structure_minimal_fchk_text(tmp_path):
    path = _write(tmp_path, "tiny.fchk", _minimal_fchk_text())
    atoms = read_structure(path)
    assert [atom[1] for atom in atoms] == ["C", "H"]
    assert [atom[2] for atom in atoms] == [6, 1]
    assert atoms[0][3] == (0.0, 0.0, 0.0)
    assert atoms[1][3][0] == pytest.approx(1.0, abs=1e-6)


def test_read_structure_fch_extension(tmp_path):
    path = _write(tmp_path, "tiny.fch", _minimal_fchk_text())
    assert len(read_structure(path)) == 2


def test_read_structure_log_uses_last_orientation(tmp_path):
    path = _write(tmp_path, "job.log",
                  _log_orientation("Standard orientation",
                                   [(1, 6, 0.0, 0.0, 0.0),
                                    (2, 1, 1.0, 0.0, 0.0)]) +
                  " Basis set exchange information\n" +
                  _log_orientation("Input orientation",
                                   [(1, 8, 9.0, 8.0, 7.0),
                                    (2, 1, 1.5, 2.5, 3.5)]))
    atoms = read_structure(path)
    assert [(atom[1], atom[3]) for atom in atoms] == [
        ("O", (9.0, 8.0, 7.0)), ("H", (1.5, 2.5, 3.5))]
    assert atoms[1][2] == 1


def test_read_structure_log_accepts_zmatrix_orientation(tmp_path):
    path = _write(tmp_path, "zmat.log",
                  _log_orientation("Z-Matrix orientation",
                                   [(1, 6, 4.0, 5.0, 6.0)]))
    atoms = read_structure(path)
    assert atoms[0][1] == "C" and atoms[0][3] == (4.0, 5.0, 6.0)


def test_read_structure_xyz_and_gjf(tmp_path):
    xyz = _write(tmp_path, "water.xyz",
                 "3\nwater\nO 0.0 0.0 0.0\nH 1.0 0.0 0.0\nH 0.0 1.0 0.0\n")
    atoms = read_structure(xyz)
    assert [atom[1] for atom in atoms] == ["O", "H", "H"]
    assert [atom[2] for atom in atoms] == [8, 1, 1]

    gjf = _write(tmp_path, "in.gjf",
                 "%chk=x.chk\n#p hf/sto-3g\n\ntitle\n\n0 1\n"
                 " C 0.0 0.0 0.0\n H 1.0 0.0 0.0\n\n")
    atoms = read_structure(gjf)
    assert [atom[1] for atom in atoms] == ["C", "H"]
    assert atoms[1][3] == (1.0, 0.0, 0.0)


def test_read_structure_falls_back_for_unknown_extension(tmp_path):
    path = _write(tmp_path, "mystery.txt",
                  _log_orientation("Standard orientation",
                                   [(1, 7, 0.0, 0.0, 0.0)]))
    assert read_structure(path)[0][1] == "N"


def test_read_structure_missing_file_raises_value_error(tmp_path):
    with pytest.raises(ValueError, match="找不到结构文件"):
        read_structure(str(tmp_path / "missing.log"))


def test_read_structure_without_coordinates_raises_value_error(tmp_path):
    path = _write(tmp_path, "plain.log", " Gaussian 16\n Normal termination\n")
    with pytest.raises(ValueError, match="解析出原子结构"):
        read_structure(path)


# ── 成键 / 连通分量 ──────────────────────────────────────────────────

def test_get_bonds_from_atoms_uses_radius_criterion():
    atoms = [
        (1, "H", 1, (0.0, 0.0, 0.0)),
        (2, "H", 1, (0.74, 0.0, 0.0)),
        (3, "O", 8, (5.0, 0.0, 0.0)),
    ]
    assert get_bonds_from_atoms(atoms) == [(1, 2)]


def test_connected_components_deterministic_and_isolated():
    assert connected_components(4, [(1, 2)]) == [{1, 2}, {3}, {4}]
    assert connected_components(0, []) == []
    # 非法边号被忽略
    assert connected_components(3, [(1, 9), (2, 2)]) == [{1}, {2}, {3}]


@_needs_fchk
def test_connected_components_real_fchk_splits_c4h6_and_c2h4():
    atoms = read_structure(FCHK_PATH)
    bonds = get_bonds_from_atoms(atoms)
    components = connected_components(len(atoms), bonds)

    butadiene = {1, 2, 3, 4, 5, 6, 7, 14, 15, 16}
    ethylene = {8, 9, 10, 11, 12, 13}
    assert len(components) == 2
    assert sorted(len(component) for component in components) == [6, 10]
    assert components[0] == butadiene          # 按最小原子序号排序
    assert components[1] == ethylene

    symbols = {atom[0]: atom[1] for atom in atoms}
    assert sorted(symbols[index] for index in butadiene) == ["C"] * 4 + ["H"] * 6
    assert sorted(symbols[index] for index in ethylene) == ["C"] * 2 + ["H"] * 4


# ── 碎片校验 ─────────────────────────────────────────────────────────

def test_validate_fragments_accepts_complete_partition():
    assert validate_fragments(4, {1, 2}, {3, 4}) is None
    assert validate_fragments(4, [3], [1, 2, 4]) is None


def test_validate_fragments_rejects_empty():
    with pytest.raises(ValueError, match="至少包含一个原子"):
        validate_fragments(4, set(), {1, 2, 3, 4})
    with pytest.raises(ValueError, match="至少包含一个原子"):
        validate_fragments(4, {1, 2, 3, 4}, set())


def test_validate_fragments_rejects_overlap():
    with pytest.raises(ValueError, match="同时被分配"):
        validate_fragments(4, {1, 2}, {2, 3, 4})


def test_validate_fragments_rejects_out_of_range():
    with pytest.raises(ValueError, match="超出范围"):
        validate_fragments(4, {1, 2}, {3, 5})


def test_validate_fragments_rejects_missing_atom_and_names_first():
    with pytest.raises(ValueError, match="原子 3 没有分配"):
        validate_fragments(5, {1, 2}, {4, 5})


# ── 范围串 ───────────────────────────────────────────────────────────

def test_format_ranges_compresses_runs():
    assert format_ranges({1, 2, 3, 5, 8, 9, 10}) == "1-3,5,8-10"
    assert format_ranges([10, 9, 8]) == "8-10"
    assert format_ranges([]) == ""


def test_parse_ranges_accepts_mixed_separators():
    assert parse_ranges("1-3,5,8-10") == {1, 2, 3, 5, 8, 9, 10}
    assert parse_ranges("1-3，5；8-10 12") == {1, 2, 3, 5, 8, 9, 10, 12}
    assert parse_ranges(" 1 - 3 ; 5 ") == {1, 2, 3, 5}
    assert parse_ranges("") == set()


def test_parse_ranges_roundtrip_with_format_ranges():
    values = {1, 2, 4, 7, 8, 9, 15}
    assert parse_ranges(format_ranges(values)) == values


@pytest.mark.parametrize("text", ["abc", "1-", "3-1", "1-2-3", "x-y", "1,,?"])
def test_parse_ranges_rejects_bad_input(text):
    with pytest.raises(ValueError):
        parse_ranges(text)


# ── route 生成 ───────────────────────────────────────────────────────

def test_build_fragment_route_sp():
    assert build_fragment_route(ROUTE, "sp") == (
        "#p m06l/def2svp int=ultrafine nosymm sp")


def test_build_fragment_route_opt():
    assert build_fragment_route(ROUTE, "opt") == (
        "#p m06l/def2svp int=ultrafine nosymm opt")


def test_build_fragment_route_without_nosymm():
    assert build_fragment_route(ROUTE, "sp", add_nosymm=False) == (
        "#p m06l/def2svp int=ultrafine sp")
    assert build_fragment_route(ROUTE, "opt", add_nosymm=False) == (
        "#p m06l/def2svp int=ultrafine opt")


def test_build_fragment_route_keeps_setup_and_drops_job_keywords():
    route = ("P opt=(ts,calcfc) freq geom=connectivity guess=read chk=foo.chk "
             "output=wfn restart force stable=opt sp allcheck job "
             "m06l/def2svp scf=(tight,maxcycle=200) int=ultrafine "
             "scrf=(pcm,solvent=water) empiricaldispersion=gd3bj nosymm")
    result = build_fragment_route(route, "opt")
    assert result.startswith("#p ")
    assert result.endswith(" nosymm opt")
    assert result.count("nosymm") == 1

    tokens = result.split()[1:]
    for dropped in ("p", "P", "opt=(ts,calcfc)", "freq", "geom=connectivity",
                    "guess=read", "chk=foo.chk", "output=wfn", "restart",
                    "force", "stable=opt", "sp", "allcheck", "job"):
        assert dropped not in tokens
    for kept in ("m06l/def2svp", "scf=(tight,maxcycle=200)", "int=ultrafine",
                 "scrf=(pcm,solvent=water)", "empiricaldispersion=gd3bj"):
        assert kept in tokens


def test_build_fragment_route_accepts_hash_prefix():
    assert build_fragment_route("#p m06l/def2svp", "sp") == (
        "#p m06l/def2svp nosymm sp")
    assert build_fragment_route("#P m06l/def2svp int=ultrafine", "opt") == (
        "#p m06l/def2svp int=ultrafine nosymm opt")


def test_build_fragment_route_rejects_unknown_job():
    with pytest.raises(ValueError):
        build_fragment_route(ROUTE, "ts")


def test_build_fragment_route_requires_level_of_theory():
    with pytest.raises(ValueError, match="理论水平"):
        build_fragment_route("p opt freq int=ultrafine", "sp")


# ── 4 个 gjf 的生成 ─────────────────────────────────────────────────

def test_prepare_di_jobs_writes_four_inputs_in_order(tmp_path):
    jobs = prepare_di_jobs(ATOMS, {1, 2}, {3, 4}, str(tmp_path), "sys", ROUTE)

    assert [job["role"] for job in jobs] == [
        "frag1_def", "frag2_def", "frag1_opt", "frag2_opt"]
    assert [job["kind"] for job in jobs] == ["sp", "sp", "opt", "opt"]
    assert [os.path.basename(job["gjf"]) for job in jobs] == [
        "sys_frag1_def.gjf", "sys_frag2_def.gjf",
        "sys_frag1_opt.gjf", "sys_frag2_opt.gjf"]
    assert len(list(tmp_path.glob("*.gjf"))) == 4
    assert len(list(tmp_path.iterdir())) == 4

    for job in jobs:
        base = os.path.splitext(job["gjf"])[0]
        assert os.path.isfile(job["gjf"])
        assert job["log"] == base + ".log"
        assert job["chk"] == base + ".chk"
        assert (job["charge"], job["multiplicity"]) == (0, 1)
    assert len({job["gjf"] for job in jobs}) == 4


def test_prepare_di_jobs_preserves_atom_order_and_coordinates(tmp_path):
    # 故意把碎片写成乱序集合：写出时必须按原文件顺序排列
    jobs = prepare_di_jobs(ATOMS, {2, 1}, {4, 3}, str(tmp_path), "sys", ROUTE)
    assert [atom[0] for atom in jobs[0]["atoms"]] == [1, 2]
    assert [atom[0] for atom in jobs[1]["atoms"]] == [3, 4]
    assert [atom[0] for atom in jobs[2]["atoms"]] == [1, 2]
    assert [atom[0] for atom in jobs[3]["atoms"]] == [3, 4]
    # 坐标原样照抄
    assert jobs[0]["atoms"] == ATOMS[:2]
    assert jobs[1]["atoms"] == ATOMS[2:]


def test_prepare_di_jobs_gjf_content(tmp_path):
    jobs = prepare_di_jobs(ATOMS, {1, 2}, {3, 4}, str(tmp_path), "sys", ROUTE)
    text = open(jobs[0]["gjf"], encoding="ascii").read()
    lines = text.splitlines()

    assert lines[0] == "%chk=sys_frag1_def.chk"
    assert lines[1] == "%mem=8GB"
    assert lines[2] == "%nprocshared=8"
    assert lines[3] == "#p m06l/def2svp int=ultrafine nosymm sp"
    assert lines[4] == ""
    assert lines[5]                       # 标题行
    assert lines[6] == ""
    assert lines[7] == "0 1"
    assert lines[8].split() == ["C", "0.00000000", "0.00000000", "0.00000000"]
    assert lines[9].split() == ["H", "1.00000000", "0.00000000", "0.00000000"]
    assert text.endswith("\n\n")          # 坐标块后留空行

    opt_text = open(jobs[2]["gjf"], encoding="ascii").read()
    assert "#p m06l/def2svp int=ultrafine nosymm opt" in opt_text
    assert [job["route"] for job in jobs] == [
        "#p m06l/def2svp int=ultrafine nosymm sp",
        "#p m06l/def2svp int=ultrafine nosymm sp",
        "#p m06l/def2svp int=ultrafine nosymm opt",
        "#p m06l/def2svp int=ultrafine nosymm opt"]


def test_prepare_di_jobs_custom_charges_mem_and_processors(tmp_path):
    jobs = prepare_di_jobs(
        ATOMS, {1, 2}, {3, 4}, str(tmp_path), "sys", ROUTE,
        frag_charges=((1, 2), (-1, 2)), mem="10GB", nprocshared=24)
    assert (jobs[0]["charge"], jobs[0]["multiplicity"]) == (1, 2)
    assert (jobs[1]["charge"], jobs[1]["multiplicity"]) == (-1, 2)

    lines = open(jobs[1]["gjf"], encoding="ascii").read().splitlines()
    assert lines[1] == "%mem=10GB"
    assert lines[2] == "%nprocshared=24"
    assert lines[7] == "-1 2"


def test_prepare_di_jobs_can_disable_nosymm(tmp_path):
    jobs = prepare_di_jobs(ATOMS, {1, 2}, {3, 4}, str(tmp_path), "sys", ROUTE,
                           add_nosymm=False)
    assert jobs[0]["route"] == "#p m06l/def2svp int=ultrafine sp"
    assert jobs[2]["route"] == "#p m06l/def2svp int=ultrafine opt"


def test_prepare_di_jobs_rejects_bad_fragments_before_writing(tmp_path):
    with pytest.raises(ValueError, match="同时被分配"):
        prepare_di_jobs(ATOMS, {1, 2}, {2, 3, 4}, str(tmp_path), "sys", ROUTE)
    assert list(tmp_path.iterdir()) == []


def test_prepare_di_jobs_rejects_bad_route_before_writing(tmp_path):
    with pytest.raises(ValueError, match="理论水平"):
        prepare_di_jobs(ATOMS, {1, 2}, {3, 4}, str(tmp_path), "sys",
                        "p opt freq")
    assert list(tmp_path.iterdir()) == []


# ── 本机运行 ─────────────────────────────────────────────────────────

def test_di_local_cancelled_is_runtime_error():
    assert issubclass(DiLocalCancelled, RuntimeError)


def test_run_di_jobs_runs_all_jobs_in_order(tmp_path, monkeypatch):
    jobs = _fake_jobs(tmp_path)
    exe = _fake_exe(tmp_path)
    calls = []
    emitted = []

    def fake_run(gjf, g16_exe, log_path=None, on_line=None, cancel=None):
        calls.append(os.path.basename(gjf))
        assert g16_exe == exe
        assert log_path == os.path.splitext(gjf)[0] + ".log"
        assert on_line is not None and callable(on_line)
        return GaussianJobResult(True, log_path, 0)

    monkeypatch.setattr(di_local, "run_gaussian", fake_run)
    result = run_di_jobs(jobs, exe, on_log=emitted.append)

    assert calls == ["sys_frag1_def.gjf", "sys_frag2_def.gjf",
                     "sys_frag1_opt.gjf", "sys_frag2_opt.gjf"]
    assert result == {"jobs": jobs}
    assert emitted[0] == "=== [1/4] 片段1 单点：sys_frag1_def.gjf ==="
    assert "=== [4/4] 片段2 优化：sys_frag2_opt.gjf ===" in emitted
    assert any(message.startswith("[1/4] 完成") for message in emitted)


def test_run_di_jobs_forwards_only_progress_lines(tmp_path, monkeypatch):
    jobs = _fake_jobs(tmp_path)[:1]
    exe = _fake_exe(tmp_path)
    emitted = []
    noisy = " This noisy SCF iteration line must not reach the panel"

    def fake_run(gjf, g16_exe, log_path=None, on_line=None, cancel=None):
        for line in (
                " SCF Done:  E(RM06L) =  -123.456789",
                " Step number   1",
                " RMS     Force            0.000123",
                " Maximum Force            0.000456",
                " Converged?  YES",
                " Normal termination of Gaussian 16",
                " Frequencies --  1234.5678 2345.6789",
                noisy):
            on_line(line)
        return GaussianJobResult(True, log_path, 0)

    monkeypatch.setattr(di_local, "run_gaussian", fake_run)
    run_di_jobs(jobs, exe, on_log=emitted.append)

    assert noisy not in emitted
    for marker in ("SCF Done", "Step number", "RMS     Force", "Maximum Force",
                   "Converged?", "Normal termination", "Frequencies --"):
        assert any(marker in message for message in emitted), marker


def test_run_di_jobs_raises_on_failed_job_and_stops(tmp_path, monkeypatch):
    jobs = _fake_jobs(tmp_path)
    exe = _fake_exe(tmp_path)
    calls = []

    def fake_run(gjf, g16_exe, log_path=None, on_line=None, cancel=None):
        calls.append(os.path.basename(gjf))
        return GaussianJobResult(False, log_path, 1, error="SCF 未收敛")

    monkeypatch.setattr(di_local, "run_gaussian", fake_run)
    with pytest.raises(RuntimeError, match="SCF 未收敛"):
        run_di_jobs(jobs, exe)
    assert calls == ["sys_frag1_def.gjf"]


def test_run_di_jobs_raises_cancelled_when_backend_cancels(tmp_path, monkeypatch):
    jobs = _fake_jobs(tmp_path)
    exe = _fake_exe(tmp_path)

    def fake_run(gjf, g16_exe, log_path=None, on_line=None, cancel=None):
        return GaussianJobResult(False, log_path, -1, cancelled=True)

    monkeypatch.setattr(di_local, "run_gaussian", fake_run)
    with pytest.raises(DiLocalCancelled):
        run_di_jobs(jobs, exe)


def test_run_di_jobs_cancel_before_first_job(tmp_path, monkeypatch):
    jobs = _fake_jobs(tmp_path)
    exe = _fake_exe(tmp_path)
    calls = []

    monkeypatch.setattr(di_local, "run_gaussian",
                        lambda *args, **kwargs: calls.append(args))

    with pytest.raises(DiLocalCancelled):
        run_di_jobs(jobs, exe, on_log=lambda _message: None,
                    cancel=lambda: True)
    assert calls == []


def test_run_di_jobs_validates_g16_executable(tmp_path):
    jobs = _fake_jobs(tmp_path)
    with pytest.raises(RuntimeError, match="g16"):
        run_di_jobs(jobs, str(tmp_path / "missing_g16.exe"))
    with pytest.raises(RuntimeError, match="g16"):
        run_di_jobs(jobs, "")
