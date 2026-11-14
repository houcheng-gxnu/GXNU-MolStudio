# -*- coding: utf-8 -*-
"""ORCA 本机计算模块：输入生成、调用、输出解析与格式转换（独立模块）。

设计目标
--------
* 与现有 Gaussian 流程解耦：本模块只负责“把结构交给 ORCA、把结果读回来”；
* 供 :mod:`molstudio.panels.orca_local_dialog` 和后续“波函数分析适配层”使用；
* ORCA 6.x（本机 ``E:\\ORCA\\orca.exe``，msmpi 版）。注意 msmpi 安装通常
  **没有串行子程序**（``orca_guess.exe`` 等），必须写 ``%pal nprocs >= 2``，
  否则 ORCA 会报 "Access is denied" / 找不到子程序；本模块默认 nprocs=4。

Gaussian ↔ ORCA 对照（本模块用到的部分）
----------------------------------------
========================  =============================  ==========================
任务                       Gaussian                       ORCA
========================  =============================  ==========================
单点                      ``#p B3LYP/def2SVP``           ``! B3LYP def2-SVP``
几何优化                  ``opt``                        ``! Opt``
频率                      ``freq``                       ``! Freq``
优化+频率                 ``opt freq``                   ``! Opt Freq``
过渡态                    ``opt=(ts,calcfc,noeigentest)``  ``! OptTS`` + ``%geom Calc_Hess true``
过渡态+频率               ``opt=(ts,calcfc,noeigentest) freq`` ``! OptTS Freq``
IRC                       ``irc=(...)``                  ``! IRC``
溶剂（CPCM/SMD）          ``scrf=(cpcm,solvent=water)``  ``! CPCM(water)`` 或
                                                         ``%cpcm smd true smdsolvent "water" end``
色散校正                  ``empiricaldispersion=gd3bj``  ``! D3BJ``
并行                      ``%nprocshared=8``             ``%pal nprocs 8 end``
内存                      ``%mem=32GB``（总内存）         ``%maxcore 4000``（**每核** MB）
波函数                    ``.fchk``                      ``.gbw`` → ``orca_2mkl -molden``
========================  =============================  ==========================
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "JOB_TYPES", "GAUSSIAN_ORCA_MAP", "OrcaError", "OrcaPreparedJob",
    "OrcaResult", "find_orca_exe", "find_orca_2mkl", "build_input",
    "prepare_job", "run_job", "run_local", "parse_output",
    "parse_frequencies", "parse_geometry", "parse_orbitals",
    "parse_charges", "convert_gbw", "molden_to_fchk", "command_preview",
    "gbw_path_for", "read_structure_file",
]

#: 任务类型 → ORCA 简单关键字 / Gaussian 关键字 / 中文名
JOB_TYPES = {
    "sp": {"orca": "", "gaussian": "single point", "zh": "单点能",
           "en": "Single point"},
    "opt": {"orca": "Opt", "gaussian": "opt", "zh": "几何优化",
            "en": "Geometry optimization"},
    "freq": {"orca": "Freq", "gaussian": "freq", "zh": "频率",
             "en": "Frequencies"},
    "opt_freq": {"orca": "Opt Freq", "gaussian": "opt freq",
                 "zh": "优化 + 频率", "en": "Optimization + frequencies"},
    "ts": {"orca": "OptTS", "gaussian": "opt=(ts,calcfc,noeigentest)",
           "zh": "过渡态优化", "en": "Transition state optimization"},
    "ts_freq": {"orca": "OptTS Freq",
                "gaussian": "opt=(ts,calcfc,noeigentest) freq",
                "zh": "过渡态优化 + 频率",
                "en": "Transition state optimization + frequencies"},
    "irc": {"orca": "IRC", "gaussian": "irc=(...)",
            "zh": "IRC 反应路径", "en": "IRC path"},
    "td": {"orca": "TDDFT", "gaussian": "td=(nstates=N)",
           "zh": "TD-DFT 激发态", "en": "TD-DFT excitations"},
    "custom": {"orca": "", "gaussian": "自定义", "zh": "自定义",
               "en": "Custom"},
}

#: 表格式对照，供文档 / 面板提示复用
GAUSSIAN_ORCA_MAP = [
    ("单点能", "#p B3LYP/def2SVP", "! B3LYP def2-SVP"),
    ("几何优化", "opt", "! Opt"),
    ("频率", "freq", "! Freq"),
    ("优化 + 频率", "opt freq", "! Opt Freq"),
    ("过渡态", "opt=(ts,calcfc,noeigentest)",
     "! OptTS\n%geom\n Calc_Hess true\nend"),
    ("过渡态 + 频率", "opt=(ts,calcfc,noeigentest) freq",
     "! OptTS Freq\n%geom\n Calc_Hess true\nend"),
    ("IRC", "irc=(forward,stepsize=10)", "! IRC"),
    ("溶剂 CPCM", "scrf=(cpcm,solvent=water)", "! CPCM(water)"),
    ("溶剂 SMD", "scrf=(smd,solvent=water)",
     '%cpcm smd true smdsolvent "water" end'),
    ("色散校正", "empiricaldispersion=gd3bj", "! D3BJ"),
    ("并行", "%nprocshared=8", "%pal nprocs 8 end"),
    ("内存", "%mem=32GB（整机）", "%maxcore 4000（每核 MB）"),
    ("波函数", "formchk → .fchk", "orca_2mkl -molden → .molden.input"),
]

#: 常见安装位置
COMMON_ORCA_PATHS = (
    r"E:\ORCA\orca.exe",
    r"D:\ORCA\orca.exe",
    r"C:\ORCA\orca.exe",
    r"C:\Program Files\ORCA\orca.exe",
)

#: 常见 ORCA 泛函名（面板下拉提示；实际可任意填）
COMMON_METHODS = (
    "B3LYP", "B3LYP-D3BJ", "PBE0", "M06-2X", "M06L", "wB97X-D3",
    "wB97X-V", "r2SCAN-3c", "PBE", "TPSS", "HF", "MP2", "DLPNO-CCSD(T)",
)

#: 常见基组
COMMON_BASES = ("def2-SVP", "def2-TZVP", "def2-TZVPP", "def2-QZVP",
                "6-31G*", "6-311G**", "cc-pVDZ", "cc-pVTZ", "STO-3G")

#: 常见溶剂（ORCA 内置名称）
COMMON_SOLVENTS = ("water", "methanol", "ethanol", "acetonitrile",
                   "dichloromethane", "chloroform", "toluene", "THF",
                   "DMSO", "acetone", "benzene")

_FINAL_ENERGY_RE = re.compile(
    r"FINAL SINGLE POINT ENERGY\s+(-?\d+\.\d+)")
_FREQ_RE = re.compile(
    r"^\s*(\d+):\s+(-?\d+\.\d+)\s+cm\*\*-1")
_ORB_RE = re.compile(
    r"^\s*(\d+)\s+([0-9.]+)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s*$")
_CHARGE_RE = re.compile(r"^\s*(-?\d+)\s+([A-Za-z]{1,2})\s*:\s*(-?\d+\.\d+)")
_GEOM_HEADER = "CARTESIAN COORDINATES (ANGSTROEM)"


class OrcaError(RuntimeError):
    """ORCA 调用 / 输入 / 结果解析错误。"""


@dataclass
class OrcaPreparedJob:
    name: str
    workdir: str
    inp_path: str
    out_path: str
    command: list
    command_str: str
    input_text: str


@dataclass
class OrcaResult:
    prepared: OrcaPreparedJob
    returncode: int = 0
    elapsed: float = 0.0
    output_text: str = ""
    parsed: dict = field(default_factory=dict)
    gbw_path: str = ""
    error: str = ""


def _as_bool(value):
    return bool(value)


def find_orca_exe(path_hint="") -> str:
    """定位 orca.exe：参数 → ORCA_EXE / MOLSTUDIO_ORCA_EXE → PATH → 常见目录。"""
    candidates = []
    if path_hint:
        candidates.append(path_hint)
    for env_name in ("ORCA_EXE", "MOLSTUDIO_ORCA_EXE", "ORCA_PATH"):
        val = os.environ.get(env_name, "")
        if val:
            candidates.append(val)
    found = shutil.which("orca.exe") or shutil.which("orca")
    if found:
        candidates.append(found)
    candidates.extend(COMMON_ORCA_PATHS)
    for cand in candidates:
        try:
            p = Path(str(cand)).expanduser()
            if p.is_dir():
                p = p / "orca.exe"
            if p.is_file():
                return str(p)
        except OSError:
            continue
    return ""


def find_orca_2mkl(orca_exe="") -> str:
    """定位 orca_2mkl.exe（与 orca.exe 同目录）。"""
    exe = orca_exe or find_orca_exe()
    if exe:
        cand = Path(exe).with_name("orca_2mkl.exe")
        if cand.is_file():
            return str(cand)
    found = shutil.which("orca_2mkl.exe")
    return found or ""


def _validate_xyz(symbols, coords):
    symbols = [str(s).strip() for s in (symbols or [])]
    if not symbols:
        raise OrcaError("没有原子：请先载入结构")
    if len(symbols) != len(coords or []):
        raise OrcaError("原子符号与坐标数量不一致")
    rows = []
    for sym, xyz in zip(symbols, coords):
        if len(xyz) != 3:
            raise OrcaError("坐标必须是三维：%r" % (xyz,))
        rows.append((sym, float(xyz[0]), float(xyz[1]), float(xyz[2])))
    return rows


def _clean_line(text):
    return " ".join(str(text or "").split())


def build_input(symbols, coords, charge=0, mult=1, method="B3LYP",
                basis="def2-SVP", task="sp", nprocs=4, maxcore=2000,
                solvent="", solvent_model="cpcm", dispersion="",
                calc_hess=None, extra_keywords="", td_nroots=0,
                title=""):
    """生成 ORCA 输入文本。

    Parameters
    ----------
    task : str
        :data:`JOB_TYPES` 的键（``sp`` / ``opt`` / ``freq`` / ``opt_freq`` /
        ``ts`` / ``ts_freq`` / ``irc`` / ``td`` / ``custom``）。
    nprocs : int
        ORCA 并行进程数。msmpi 安装必须 >= 2（见模块 docstring）。
    maxcore : int
        每个进程的内存，单位 MB（ORCA 的 ``%maxcore`` 是**每核**）。
    solvent_model : str
        ``"cpcm"`` 或 ``"smd"``。
    dispersion : str
        ``""`` / ``"D3BJ"`` / ``"D4"`` 等，直接写入简单输入行。
    calc_hess : bool or None
        ``None`` 时 TS 任务自动加 ``Calc_Hess true``；显式 False 可关闭。
    """
    try:
        charge = int(charge)
        mult = int(mult)
        nprocs = int(nprocs)
        maxcore = int(maxcore)
    except (TypeError, ValueError) as exc:
        raise OrcaError("电荷/多重度/核数/内存必须是整数") from exc
    if charge < 0:
        raise OrcaError("电荷必须是整数（负电荷直接填负值）")
    if mult < 1:
        raise OrcaError("多重度至少为 1")
    if nprocs < 1:
        raise OrcaError("核数至少为 1")
    if maxcore < 100:
        raise OrcaError("每核内存至少 100 MB")
    rows = _validate_xyz(symbols, coords)
    task = str(task or "sp").lower()
    if task not in JOB_TYPES:
        raise OrcaError("未知任务类型：%s" % task)
    method = _clean_line(method)
    basis = _clean_line(basis)
    if not method:
        raise OrcaError("方法不能为空")

    simple = ["!"]
    simple.append(method)
    if basis:
        simple.append(basis)
    job_kw = JOB_TYPES[task]["orca"]
    if job_kw:
        simple.append(job_kw)
    if dispersion:
        simple.append(_clean_line(dispersion).upper())
    if solvent and str(solvent_model).lower() == "cpcm":
        simple.append("CPCM(%s)" % _clean_line(solvent).replace(" ", "-"))
    lines = [" ".join(simple), ""]

    if nprocs > 1:
        lines.append("%%pal nprocs %d end" % nprocs)
        lines.append("")
    lines.append("%%maxcore %d" % maxcore)
    lines.append("")

    if solvent and str(solvent_model).lower() == "smd":
        lines.append('%%cpcm smd true smdsolvent "%s" end'
                     % _clean_line(solvent))
        lines.append("")

    if task == "td" and int(td_nroots or 0) > 0:
        lines.append("%tddft")
        lines.append("  NRoots %d" % int(td_nroots))
        lines.append("end")
        lines.append("")

    use_hess = (task in ("ts", "ts_freq")) if calc_hess is None \
        else _as_bool(calc_hess)
    if use_hess:
        lines.append("%geom")
        lines.append("  Calc_Hess true")
        lines.append("end")
        lines.append("")

    extra = (extra_keywords or "").strip()
    if extra:
        lines.append(extra)
        lines.append("")

    lines.append("* xyz %d %d" % (charge, mult))
    for sym, x, y, z in rows:
        lines.append("%-3s %18.10f %18.10f %18.10f" % (sym, x, y, z))
    lines.append("*")
    return "\n".join(lines) + "\n"


def gbw_path_for(inp_path) -> str:
    return str(Path(inp_path).with_suffix(".gbw"))


def read_structure_file(path):
    """读取 xyz/gjf/fchk/log/out 的几何，返回 ``(symbols, coords)``。

    ``.fchk/.fch`` 走 :mod:`molstudio.core.di_local` 的解析（含 Bohr→Å）；
    其余走 :mod:`molstudio.core.surface_projection.load_atoms`（Gaussian 与
    ORCA 输出都支持）。
    """
    path = str(path)
    ext = Path(path).suffix.lower()
    if ext in (".fchk", ".fch"):
        from molstudio.core.di_local import read_structure
        atoms = read_structure(path)
        return [a[1] for a in atoms], [[float(v) for v in a[3]]
                                       for a in atoms]
    from molstudio.core.surface_projection import load_atoms
    symbols, coords = load_atoms(path)
    return [str(s) for s in symbols], [[float(v) for v in row]
                                       for row in coords]


def prepare_job(workdir, name, symbols, coords, **kwargs):
    """把输入写到 ``workdir/name.inp``，返回 :class:`OrcaPreparedJob`。

    ``workdir`` 不存在会自动创建；``name`` 非法字符会被替换。
    """
    workdir = str(Path(workdir).expanduser().resolve())
    os.makedirs(workdir, exist_ok=True)
    safe = re.sub(r'[<>:"/\\|?*\s]+', "_", str(name or "orca_job")).strip("_")
    safe = safe or "orca_job"
    inp_path = os.path.join(workdir, safe + ".inp")
    out_path = os.path.join(workdir, safe + ".out")
    exe = kwargs.pop("orca_exe", "")
    text = build_input(symbols, coords, **kwargs)
    with open(inp_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    exe = find_orca_exe(exe) or "orca.exe"
    command = [exe, os.path.basename(inp_path)]
    return OrcaPreparedJob(
        name=safe, workdir=workdir, inp_path=inp_path, out_path=out_path,
        command=command, command_str=command_preview(command), input_text=text,
    )


def command_preview(command) -> str:
    try:
        return subprocess.list2cmdline([str(c) for c in command])
    except Exception:                                    # noqa: BLE001
        return " ".join(str(c) for c in command)


def _exe_env(orca_exe):
    env = os.environ.copy()
    try:
        exe_dir = str(Path(orca_exe).resolve().parent)
    except OSError:
        exe_dir = str(Path(orca_exe).parent)
    parts = env.get("PATH", "").split(os.pathsep)
    if exe_dir not in parts:
        env["PATH"] = exe_dir + os.pathsep + env.get("PATH", "")
    return env


def run_job(prepared: OrcaPreparedJob, orca_exe="", on_log=None,
            cancel_check=None, timeout=0, write_out=True):
    """在本机运行 ORCA 并流式返回日志。

    ``on_log(line)`` 每收到一行输出调用一次；``cancel_check()`` 返回 True 时
    终止进程；``timeout`` 秒（0 = 不限）。返回 :class:`OrcaResult`。
    """
    exe = find_orca_exe(orca_exe or prepared.command[0])
    if not exe:
        raise OrcaError("找不到 orca.exe：请先设置 ORCA 路径")
    inp = prepared.inp_path
    if not os.path.isfile(inp):
        raise OrcaError("输入文件不存在：%s" % inp)
    cmd = [exe, os.path.basename(inp)]
    env = _exe_env(exe)
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    started = time.time()
    out_lines = []
    proc = None
    try:
        proc = subprocess.Popen(
            cmd, cwd=prepared.workdir, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors="replace", bufsize=1,
            creationflags=flags)
        stream = proc.stdout
        if stream is None:
            raise OrcaError("无法读取 ORCA 输出")
        last_check = 0.0
        while True:
            line = stream.readline()
            if not line:
                if proc.poll() is not None:
                    break
                time.sleep(0.02)
                continue
            out_lines.append(line)
            if on_log:
                try:
                    on_log(line.rstrip("\r\n"))
                except Exception:                        # noqa: BLE001
                    pass
            now = time.time()
            if cancel_check and now - last_check > 0.2:
                last_check = now
                if cancel_check():
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    out_lines.append("\n[ORCA] 用户终止\n")
                    break
            if timeout and now - started > timeout:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                out_lines.append("\n[ORCA] 超时终止\n")
                break
        proc.wait()
    except FileNotFoundError as exc:
        raise OrcaError("无法启动 ORCA：%s" % exe) from exc
    elapsed = time.time() - started
    text = "".join(out_lines)
    if write_out:
        try:
            with open(prepared.out_path, "w", encoding="utf-8",
                      newline="\n") as fh:
                fh.write(text)
        except OSError:
            pass
    parsed = parse_output(text)
    err = ""
    if proc is not None and proc.returncode not in (0, None):
        err = "ORCA 返回码 %s" % proc.returncode
    if not parsed.get("terminated_normally") and not err:
        err = "ORCA 未正常结束"
    gbw = gbw_path_for(prepared.inp_path)
    return OrcaResult(
        prepared=prepared,
        returncode=0 if proc is None else int(proc.returncode or 0),
        elapsed=elapsed, output_text=text, parsed=parsed,
        gbw_path=gbw if os.path.isfile(gbw) else "", error=err,
    )


def run_local(workdir, name, symbols, coords, orca_exe="", on_log=None,
              cancel_check=None, timeout=0, **kwargs):
    """``prepare_job`` + ``run_job`` 的便捷封装。"""
    prepared = prepare_job(workdir, name, symbols, coords,
                           orca_exe=orca_exe, **kwargs)
    return run_job(prepared, orca_exe=orca_exe, on_log=on_log,
                   cancel_check=cancel_check, timeout=timeout)


# ══════════════════════════════════════════════════════════════════════ #
#  输出解析
# ══════════════════════════════════════════════════════════════════════ #
def _last_match(regex, text, flags=re.MULTILINE):
    matches = list(re.finditer(regex, text, flags))
    return matches[-1] if matches else None


def parse_output(text) -> dict:
    """解析 ORCA 输出文本，返回常用结果字典（缺失项为空）。"""
    text = text or ""
    res = {
        "energies": [], "final_energy": None, "terminated_normally": False,
        "opt_converged": False, "frequencies": [], "imaginary": [],
        "geometry": [], "symbols": [], "orbital_energies": [],
        "homo": None, "lumo": None, "homo_lumo_gap_ev": None,
        "homo_lumo_gap_hartree": None, "charges": [], "charges_type": "",
        "run_time_text": "", "errors": [], "scf_converged": False,
        "job_done": False,
    }
    for m in re.finditer(r"FINAL SINGLE POINT ENERGY\s+(-?\d+\.\d+)", text):
        res["energies"].append(float(m.group(1)))
    if res["energies"]:
        res["final_energy"] = res["energies"][-1]
    res["terminated_normally"] = "ORCA TERMINATED NORMALLY" in text
    res["job_done"] = res["terminated_normally"]
    res["opt_converged"] = ("THE OPTIMIZATION HAS CONVERGED" in text
                            or "HURRAY" in text)
    res["scf_converged"] = "SCF CONVERGED AFTER" in text or \
        "SCF NOT CONVERGED" not in text and "SCF CONVERGED" in text

    freqs = parse_frequencies(text)
    res["all_frequencies"] = freqs
    # ORCA 会把 6 个平动/转动零频一起打印；统计真实振动时剔除
    res["frequencies"] = [f for f in freqs if abs(f) > 1e-6]
    res["imaginary"] = [f for f in freqs if f < -1e-6]
    geo = parse_geometry(text)
    if geo:
        res["symbols"], res["geometry"] = geo
    orbs = parse_orbitals(text)
    res["orbital_energies"] = orbs
    if orbs:
        occ = [row for row in orbs if row["occ"] >= 0.5]
        virt = [row for row in orbs if row["occ"] < 0.5]
        if occ:
            homo = max(occ, key=lambda r: r["energy_hartree"])
            res["homo"] = homo
        if virt:
            lumo = min(virt, key=lambda r: r["energy_hartree"])
            res["lumo"] = lumo
        if res["homo"] and res["lumo"]:
            res["homo_lumo_gap_hartree"] = round(
                res["lumo"]["energy_hartree"] - res["homo"]["energy_hartree"],
                10)
            res["homo_lumo_gap_ev"] = round(
                res["lumo"]["energy_ev"] - res["homo"]["energy_ev"], 6)
    chg = parse_charges(text)
    if chg:
        res["charges"], res["charges_type"] = chg
    m = _last_match(r"TOTAL RUN TIME:\s*([^\n]+)", text)
    if m:
        res["run_time_text"] = m.group(1).strip()
    for line in text.splitlines():
        if ("aborting the run" in line.lower()
                or "ORCA finished by error termination" in line
                or re.search(r"\bERROR\b", line)):
            res["errors"].append(line.strip())
    return res


def parse_frequencies(text):
    """解析 ``VIBRATIONAL FREQUENCIES`` 段，返回 cm^-1 列表（含虚频负值）。"""
    lines = (text or "").splitlines()
    start = None
    for i, line in enumerate(lines):
        if "VIBRATIONAL FREQUENCIES" in line:
            start = i
    if start is None:
        return []
    freqs = []
    for line in lines[start:]:
        if "NORMAL MODES" in line or "IR SPECTRUM" in line:
            break
        m = _FREQ_RE.match(line)
        if m:
            freqs.append(float(m.group(2)))
    return freqs


def parse_geometry(text):
    """取最后一个 ``CARTESIAN COORDINATES (ANGSTROEM)`` 块。"""
    lines = (text or "").splitlines()
    start = None
    for i, line in enumerate(lines):
        if _GEOM_HEADER in line.upper():
            start = i
    if start is None:
        return None
    symbols, coords = [], []
    for line in lines[start + 1:]:
        s = line.strip()
        if not s:
            if symbols:
                break
            continue
        if s.startswith("-"):
            continue
        fields = s.split()
        if len(fields) < 4:
            if symbols:
                break
            continue
        try:
            x, y, z = float(fields[1]), float(fields[2]), float(fields[3])
        except ValueError:
            break
        symbols.append(fields[0])
        coords.append([x, y, z])
    if symbols:
        return symbols, coords
    return None


def parse_orbitals(text):
    """解析 ``ORBITAL ENERGIES`` 表，返回 ``[{index,occ,energy_hartree,energy_ev}]``。"""
    lines = (text or "").splitlines()
    start = None
    for i, line in enumerate(lines):
        if "ORBITAL ENERGIES" in line:
            start = i
    if start is None:
        return []
    rows = []
    for line in lines[start + 1:]:
        s = line.strip()
        if not s:
            if rows:
                break
            continue
        if s.startswith("NO") or s.startswith("---"):
            continue
        m = _ORB_RE.match(line)
        if not m:
            if rows:
                break
            continue
        rows.append({
            "index": int(m.group(1)),
            "occ": float(m.group(2)),
            "energy_hartree": float(m.group(3)),
            "energy_ev": float(m.group(4)),
        })
    return rows


def parse_charges(text):
    """解析 Mulliken/Loewdin 原子电荷，返回 ``(charges, type)``。"""
    lines = (text or "").splitlines()
    start = None
    kind = ""
    for i, line in enumerate(lines):
        up = line.upper()
        if "MULLIKEN ATOMIC CHARGES" in up:
            start, kind = i, "Mulliken"
        elif "LOEWDIN ATOMIC CHARGES" in up:
            start, kind = i, "Loewdin"
    if start is None:
        return [], ""
    charges = []
    for line in lines[start + 1:]:
        s = line.strip()
        if not s:
            if charges:
                break
            continue
        if s.upper().startswith("SUM OF"):
            if charges:
                break
            continue
        m = _CHARGE_RE.match(line)
        if not m:
            if charges:
                break
            continue
        charges.append({
            "index": int(m.group(1)), "symbol": m.group(2),
            "charge": float(m.group(3)),
        })
    return charges, kind


def convert_gbw(gbw_path, orca_exe="", kind="molden", timeout=300):
    """``.gbw`` → ``.molden.input`` / ``.mkl``（给 Multiwfn 等波函数分析用）。

    Multiwfn 识别 ORCA 的 ``.molden.input``（内部会打印 "This file is
    recognized to be generated by ORCA"）；``.mkl`` 只是 Molekel 文本，不含
    波函数，Multiwfn 会当普通文本处理，因此默认用 ``molden``。
    """
    gbw = Path(str(gbw_path)).expanduser()
    if not gbw.is_file():
        raise OrcaError("找不到 .gbw 文件：%s" % gbw)
    tool = find_orca_2mkl(orca_exe)
    if not tool:
        raise OrcaError("找不到 orca_2mkl.exe（应与 orca.exe 同目录）")
    kind = str(kind or "molden").lower()
    flag = "-molden" if kind in ("molden", "molden.input") else "-mkl"
    stem = gbw.stem
    cmd = [tool, stem, flag]
    proc = subprocess.run(
        cmd, cwd=str(gbw.parent), stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, errors="replace",
        timeout=timeout)
    out = proc.stdout or ""
    if proc.returncode != 0:
        raise OrcaError("orca_2mkl 失败：%s" % out.strip()[-500:])
    if kind in ("molden", "molden.input"):
        target = gbw.with_name(stem + ".molden.input")
    else:
        target = gbw.with_name(stem + ".mkl")
    if not target.is_file():
        raise OrcaError("orca_2mkl 未生成目标文件：%s" % target)
    return str(target)


def molden_to_fchk(molden_path, multiwfn_exe="", out_fchk="", timeout=180):
    """把 ORCA 的 ``.molden.input`` 转成 Gaussian ``.fchk``（借用 Multiwfn）。

    Multiwfn 主功能 100 → 2（导出各种格式）→ 7（.fch）对当前波函数导出。
    这样 MolStudio 现有“只认 fchk”的轨道 / ESP / IGMH / AIM / DOS 等页面
    可以**零改动**地读取 ORCA 结果；转换后的文件含基组、MO 系数、轨道能量、
    密度矩阵，Multiwfn 也能继续使用。

    返回生成的 ``.fchk`` 路径；失败时抛 :class:`OrcaError`。
    """
    molden = Path(str(molden_path)).expanduser()
    if not molden.is_file():
        raise OrcaError("找不到 Molden 文件：%s" % molden)
    if multiwfn_exe:
        mw = str(Path(multiwfn_exe).expanduser())
    else:
        mw = shutil.which("Multiwfn.exe") or ""
        if not mw:
            for cand in (r"E:\Multiwfn_2026.4.10_bin_Win64\Multiwfn.exe",
                         r"E:\Multiwfn\Multiwfn.exe",
                         r"D:\Multiwfn\Multiwfn.exe"):
                if os.path.isfile(cand):
                    mw = cand
                    break
    if not mw or not os.path.isfile(mw):
        raise OrcaError("找不到 Multiwfn.exe：无法把 Molden 转成 fchk")
    if out_fchk:
        target = Path(out_fchk)
    else:
        name = molden.name
        if name.endswith(".molden.input"):
            name = name[:-len(".molden.input")]
        elif name.endswith(".molden"):
            name = name[:-len(".molden")]
        target = molden.with_name(name + ".fchk")
    if target.is_file() and target.stat().st_size > 1000:
        try:
            head = target.read_text(encoding="utf-8", errors="ignore")[:4000]
            if "Number of atoms" in head:
                return str(target)
        except OSError:
            pass
    target.parent.mkdir(parents=True, exist_ok=True)
    # 100 → 2 → 7 → 输出路径。末尾若继续等待输入，Multiwfn 会报 EOF；
    # 只要目标文件写出且格式正确，就认为转换成功。
    inputs = ("\n" + molden.name + "\n100\n2\n7\n" + str(target) + "\n")
    flags = 0
    if os.name == "nt":
        flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                 | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    try:
        proc = subprocess.run(
            [mw], input=inputs, cwd=str(molden.parent), timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, errors="replace", creationflags=flags)
    except subprocess.TimeoutExpired as exc:
        raise OrcaError("Multiwfn 转换超时（%s）" % mw) from exc
    except OSError as exc:
        raise OrcaError("无法启动 Multiwfn：%s" % exc) from exc
    if not target.is_file() or target.stat().st_size <= 1000:
        msg = ((proc.stdout or "") + (proc.stderr or "")).strip()[-800:]
        raise OrcaError("Multiwfn 未生成 fchk：%s" % msg)
    try:
        head = target.read_text(encoding="utf-8", errors="ignore")[:4000]
    except OSError as exc:
        raise OrcaError("无法读取生成的 fchk：%s" % exc) from exc
    if "Number of atoms" not in head:
        raise OrcaError("生成的 fchk 缺少 'Number of atoms'，格式异常")
    return str(target)

