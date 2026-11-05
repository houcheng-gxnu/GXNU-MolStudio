# -*- coding: utf-8 -*-
"""
xTB 独立计算内核（无 Qt / 无界面依赖）
=========================================

给 MolStudio 的「xTB 计算」页签提供全部**计算**能力：拼命令行、写输入文件、
起子进程流式读输出、解析产物、重建结果对象。UI 只负责收集参数、显示日志和结果。

设计要点
--------
* 纯 Python（stdlib + numpy），**不 import PyQt / matplotlib**，可单独在脚本或测试里跑；
* Windows 下子进程用 ``CREATE_NO_WINDOW``，stdout/stderr 合并成一条流逐行回调；
* 支持取消（``should_cancel`` 回调）与超时（``timeout``），两者都不抛异常，
  而是把 ``cancelled=True`` 返回给调用方；
* 结果解析以 ``xtbout.json`` 为主、控制台文本正则兜底；
* 每次运行必须在**独立工作目录**里（xTB 会覆盖同目录的 xtbout.json / charges /
  vibspectrum 等产物），本模块的 ``run_job`` 默认使用调用方给的目录。

来源说明
--------
命令构造与输出解析的思路移植自 **xTBridge**（MIT，同作者）以及其配套的
``gxtb_gui.py``：

* ``xtbridge/src/xtbridge/main_window.py::_build_xtb_command`` —— 独立 xTB 页签的
  命令行拼装顺序（方法开关 → 计算类型 → 电荷/自旋 → 精度/温度 → 溶剂化 → 选项）；
* ``xtbridge/src/xtbridge/workers.py::XtbWorker`` —— 子进程 stdout/stderr 合并、
  逐行喂给界面、支持中断；
* ``xtbridge/src/xtbridge/file_parser.py`` —— ``xtbscan.log`` 与 ``vibspectrum`` 解析；
* ``xtbridge/src/xtbridge/scan_utils.py`` —— 方法开关与溶剂列表；
* ``gxtb_gui.py::_extract_results`` —— TOTAL ENERGY / HOMO-LUMO GAP 等文本正则。

本模块**运行期不依赖** xTBridge 源码，只需要本机的 ``xtb.exe``。

关于本机这个 build（xtb 6.7.1 gxtb）实测的差异（写解析器时踩过）：

* 没有 ``--freq`` 选项，频率要用 ``--hess``（输入几何）或 ``--ohess``（先优化再 Hessian）；
* ``--gxtb``（tblite 实现）**不写** ``xtbout.json``，也不支持溶剂化，
  结果只能从控制台文本读；
* ``xtbout.json`` 里的 ``total enthalpy`` / ``total free energy`` 是**热校正项**
  （相对总能），不是绝对焓/自由能；绝对值和文本输出的 ``TOTAL ENTHALPY`` 一致；
* ``vibspectrum`` 前 6 个平动转动模式打印成 ``-0.00``，不能当成虚频。
"""

from __future__ import annotations

import json
import os
import queue
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

import numpy as np

__all__ = [
    "METHODS", "JOB_TYPES", "SOLVATION_MODELS",
    "ALPB_SOLVENTS", "GBSA_SOLVENTS", "COSMO_SOLVENTS", "COMMON_XTB_PATHS",
    "XtbError", "XtbResult", "t",
    "find_xtb_executable", "validate_params", "build_command", "prepare_job",
    "run_command", "run_job",
    "parse_output_text", "parse_xtbout_json", "parse_charges",
    "parse_vibspectrum", "parse_scan_log",
    "read_xyz", "write_xyz", "write_gjf",
    "collect_results", "load_results", "formula_of",
]


# ─────────────────────────────────────────────────────────────────────────────
# 常量：方法 / 计算类型 / 溶剂化
# ─────────────────────────────────────────────────────────────────────────────

#: 方法键 → 显示名与传给 xtb 的开关。
#: 注意 g-xTB 是 ``--gxtb``（写成 ``--gfn 2`` 会悄悄变成 GFN2）；
#: GFN-FF 是 ``--gfnff``（不能写 ``--gfn -1``，那个会被当成默认 GFN0/GFN2 静默算错）。
METHODS: dict = {
    "gxtb": {"zh": "g-xTB", "en": "g-xTB", "args": ["--gxtb"]},
    "gfn2": {"zh": "GFN2-xTB", "en": "GFN2-xTB", "args": ["--gfn", "2"]},
    "gfn1": {"zh": "GFN1-xTB", "en": "GFN1-xTB", "args": ["--gfn", "1"]},
    "gfn0": {"zh": "GFN0-xTB", "en": "GFN0-xTB", "args": ["--gfn", "0"]},
    "gfnff": {"zh": "GFN-FF", "en": "GFN-FF", "args": ["--gfnff"]},
}

#: 计算类型键 → 显示名。命令行行为在 :func:`build_command` 里映射。
JOB_TYPES: dict = {
    "sp": {"zh": "单点能", "en": "Single point"},
    "opt": {"zh": "几何优化", "en": "Geometry optimization"},
    "ohess": {"zh": "优化 + Hessian（频率）", "en": "Optimize + Hessian (frequencies)"},
    "hess": {"zh": "Hessian（频率）", "en": "Hessian (frequencies)"},
    "ts": {"zh": "过渡态优化", "en": "Transition-state optimization"},
    "scan": {"zh": "刚性/弛豫扫描", "en": "Relaxed scan"},
}

#: 溶剂化模型键 → 显示名。
SOLVATION_MODELS: dict = {
    "gas": {"zh": "气相（无溶剂）", "en": "Gas phase"},
    "alpb": {"zh": "ALPB", "en": "ALPB"},
    "gbsa": {"zh": "GBSA", "en": "GBSA"},
    "cosmo": {"zh": "ddCOSMO", "en": "ddCOSMO"},
}

# 溶剂名与本机 xtb 6.7.1 的 `--help` 一致（大小写不敏感）。顺序只是下拉框顺序。
ALPB_SOLVENTS: tuple = (
    "water", "methanol", "ethanol", "acetone", "acetonitrile", "aniline",
    "benzaldehyde", "benzene", "ch2cl2", "chcl3", "cs2", "dioxane", "dmf",
    "dmso", "ether", "ethylacetate", "furane", "hexadecane", "hexane",
    "nitromethane", "octanol", "woctanol", "phenol", "thf", "toluene",
)

#: GBSA 的溶剂集合比 ALPB 小得多（官方 help 里明确只有这些）。
#: ``water`` / ``hexane`` 是 ``h2o`` / ``n-hexane`` 的等价写法，两个都收。
GBSA_SOLVENTS: tuple = (
    "water", "h2o", "methanol", "acetone", "acetonitrile", "benzene",
    "ch2cl2", "chcl3", "cs2", "dmf", "dmso", "ether", "hexane", "n-hexane",
    "thf", "toluene",
)

#: ddCOSMO 与 ALPB 用同一套溶剂参数。
COSMO_SOLVENTS: tuple = ALPB_SOLVENTS

#: 常见安装位置（找不到就靠 XTB_EXE 环境变量 / PATH / 面板手动指定）。
COMMON_XTB_PATHS: tuple = (
    r"E:\gxtb\xtb-6.7.1-gxtb-210426-windows-x86_64\bin\xtb.exe",
    r"C:\gxtb\xtb-6.7.1-gxtb-210426-windows-x86_64\bin\xtb.exe",
    r"D:\gxtb\xtb-6.7.1-gxtb-210426-windows-x86_64\bin\xtb.exe",
    r"D:\xtb-6.7.1-gxtb-210426-windows-x86_64\bin\xtb.exe",
    r"C:\xtb\bin\xtb.exe",
    r"D:\xtb\bin\xtb.exe",
    r"C:\Program Files\xtb\bin\xtb.exe",
)

#: 各溶剂化模型允许的溶剂；gas 不检查。
SOLVENT_TABLE: dict = {
    "gas": (),
    "alpb": ALPB_SOLVENTS,
    "gbsa": GBSA_SOLVENTS,
    "cosmo": COSMO_SOLVENTS,
}

# ── 内部常量（不是配置项，别改）───────────────────────────────────────────────
_INPUT_NAME = "input.xyz"
_OUTPUT_NAME = "xtb.out"
_XCONTROL_TS_NAME = "xcontrol_ts.inp"
_XCONTROL_SCAN_NAME = "xcontrol_scan.inp"
_TS_XCONTROL_TEXT = "$opt\n   ts=1\n$end\n"

#: 上一次运行可能留下的产物。``prepare_job`` 在开跑前清掉它们，避免用户在
#: 同一工作目录重跑（或换分子/换方法）时把旧频率、旧优化结构、旧 JSON 当成
#: 本次结果 —— xTB 每次只写自己产出的文件，不会自动清理目录。
_STALE_ARTIFACTS = (
    _OUTPUT_NAME,
    "xtbout.json",
    "charges",
    "vibspectrum",
    "hessian",
    "g98.out",
    "wbo",
    "xtbrestart",
    "xtbopt.xyz",
    "xtbopt.log",
    ".xtboptok",
    "xtbscan.log",
    "molden.input",
    "xtbtopo.mol",
    "gfnff_charges",
    "gfnff_lists.json",
    "gfnff_topo",
    "gfnff_restart",
)
_AU_TO_DEBYE = 2.5417462           # 1 a.u. 偶极 = 2.5417462 Debye
_IMAG_THRESHOLD = -1.0             # cm^-1；比这更负才算虚频（前 6 个模式是 -0.00）
_MAX_CHARGE = 20
_MAX_UHF = 20
_MIN_ACC = 1.0e-3
_MAX_ACC = 10.0
_SOLVATION_UNSUPPORTED = frozenset({"gxtb"})   # tblite 的 g-xTB 不支持溶剂化

#: 元素符号表（xyz / gjf 里出现原子序数时的兜底）
_ELEMENT_SYMBOLS = (
    "", "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne",
    "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar", "K", "Ca",
    "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
    "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr",
    "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn",
    "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd",
    "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb",
    "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
    "Tl", "Pb", "Bi", "Po", "At", "Rn", "Fr", "Ra", "Ac", "Th",
)


# ─────────────────────────────────────────────────────────────────────────────
# 本地化文案（zh / en 严格对称）
# ─────────────────────────────────────────────────────────────────────────────

#: 键 → (中文, 英文)。用 MappingProxyType 防止运行期被意外改写。
_TEXT = MappingProxyType({
    # 错误
    "err_xtb_not_found": (
        "找不到 xTB 可执行文件：{path}",
        "xTB executable not found: {path}",
    ),
    "err_xtb_not_set": (
        "尚未设置 xTB 可执行文件路径",
        "xTB executable path is not set",
    ),
    "err_bad_param": (
        "参数不合法：{detail}",
        "Invalid parameter: {detail}",
    ),
    "err_method": (
        "未知的计算方法：{method}",
        "Unknown method: {method}",
    ),
    "err_job": (
        "未知的计算类型：{job}",
        "Unknown job type: {job}",
    ),
    "err_solvation": (
        "未知的溶剂化模型：{solvation}",
        "Unknown solvation model: {solvation}",
    ),
    "err_solvent": (
        "溶剂 “{solvent}” 不适用于 {model}",
        "Solvent \"{solvent}\" is not available for {model}",
    ),
    "err_scan_no_xcontrol": (
        "扫描（scan）任务必须提供非空的 xcontrol 文本",
        "A scan job requires non-empty xcontrol text",
    ),
    "err_charge": (
        "电荷必须是 {min} 到 {max} 之间的整数（当前：{charge}）",
        "Charge must be an integer in [{min}, {max}] (got {charge})",
    ),
    "err_uhf": (
        "未成对电子数必须是 {min} 到 {max} 之间的整数（当前：{uhf}）",
        "Number of unpaired electrons must be an integer in [{min}, {max}] (got {uhf})",
    ),
    "err_parallel": (
        "并行线程数必须是 ≥1 的整数（当前：{parallel}）",
        "Parallel threads must be an integer >= 1 (got {parallel})",
    ),
    "err_acc": (
        "SCF 精度 acc 必须是 {min} 到 {max} 之间的数（当前：{acc}）",
        "SCF accuracy acc must be a number in [{min}, {max}] (got {acc})",
    ),
    "err_etemp": (
        "电子温度 etemp 必须是 ≥0 的数（当前：{etemp}）",
        "Electronic temperature etemp must be >= 0 (got {etemp})",
    ),
    "err_empty_structure": (
        "结构为空：没有可计算的原子",
        "Empty structure: no atoms to compute",
    ),
    "err_coords_shape": (
        "坐标数组形状与原子数不匹配（应为 N×3）",
        "Coordinate array does not match the number of atoms (expected N x 3)",
    ),
    "err_workdir": (
        "工作目录不可用或不可写：{path}（{detail}）",
        "Working directory is not usable or not writable: {path} ({detail})",
    ),
    "err_launch": (
        "无法启动 xTB：{detail}",
        "Failed to launch xTB: {detail}",
    ),
    "err_timeout": (
        "xTB 运行超时（{timeout} s），已终止",
        "xTB run timed out after {timeout} s and was terminated",
    ),
    "err_cancelled": (
        "计算已被用户取消",
        "Calculation was cancelled by the user",
    ),
    "err_run_failed": (
        "xTB 异常结束（返回码 {returncode}）",
        "xTB terminated abnormally (return code {returncode})",
    ),
    "err_xyz_parse": (
        "无法解析结构文件：{path}",
        "Could not parse structure file: {path}",
    ),
    "err_no_geometry": (
        "缺少几何结构：symbols / coords 均为空",
        "Missing geometry: both symbols and coords are empty",
    ),
    # 警告（不中断流程）
    "warn_gxtb_solvation": (
        "g-xTB（tblite）不支持溶剂化：已忽略溶剂设置",
        "g-xTB (tblite) does not support solvation: solvent settings were ignored",
    ),
    "warn_no_xtb_path": (
        "尚未定位 xtb.exe：命令行仅作预览",
        "xtb.exe has not been located yet: the command line is preview only",
    ),
    "warn_no_normal_termination": (
        "输出里没有 “normal termination of xtb”，结果可能不完整",
        "No \"normal termination of xtb\" in the output; results may be incomplete",
    ),
    "warn_no_json": (
        "未找到 xtbout.json：结果仅来自控制台文本",
        "xtbout.json was not found: results come from the console text only",
    ),
    "warn_no_results": (
        "没有解析到任何能量结果",
        "No energy results could be parsed",
    ),
    "warn_bad_optimized_xyz": (
        "xtbopt.xyz 解析失败，已忽略优化结构",
        "Failed to parse xtbopt.xyz; optimized geometry was skipped",
    ),
    "warn_bad_optimized_size": (
        "xtbopt.xyz 的原子数与本次结构不符，已忽略该结构（可能是上一次运行残留）",
        "xtbopt.xyz has a different atom count than this structure; it was "
        "skipped (probably left over from a previous run)",
    ),
    "warn_stale_json": (
        "xtbout.json 的方法与本次不一致，已忽略该文件（可能是上一次运行残留）",
        "xtbout.json belongs to a different method and was ignored (probably "
        "left over from a previous run)",
    ),
    "warn_gfn0_param": (
        "GFN0-xTB 需要 param_gfn0-xtb.txt：未能在 xtb 安装目录找到，"
        "该版本可能无法运行 GFN0（其余方法不受影响）",
        "GFN0-xTB needs param_gfn0-xtb.txt, which was not found in the xTB "
        "installation; this build may not support GFN0 (other methods are "
        "unaffected)",
    ),
    # 阶段文字（on_progress）
    "phase_preparing": ("准备输入文件…", "Preparing input files..."),
    "phase_running": ("xTB 计算中…", "Running xTB..."),
    "phase_parsing": ("解析结果…", "Parsing results..."),
    "phase_done": ("计算结束", "Calculation finished"),
})


def _norm_lang(lang) -> str:
    """把 lang 归一到 "zh" / "en"；非 en 一律中文。"""
    text = str(lang or "zh").strip().lower()
    return "en" if text.startswith("en") else "zh"


def t(key: str, lang: str = "zh", **fmt) -> str:
    """取本地化引擎文案（zh/en 对称）；未知键原样返回，便于发现漏翻译。"""
    entry = _TEXT.get(str(key))
    if entry is None:
        return str(key)
    text = entry[1] if _norm_lang(lang) == "en" else entry[0]
    if fmt:
        try:
            return text.format(**fmt)
        except (KeyError, IndexError, ValueError):
            return text
    return text


# ─────────────────────────────────────────────────────────────────────────────
# 异常与结果对象
# ─────────────────────────────────────────────────────────────────────────────


class XtbError(RuntimeError):
    """无法继续时的错误（参数不合法、找不到可执行文件、启动失败、目录不可写…）。

    能继续的情况（进程非零退出、超时、用户取消、产物缺失）不抛异常，
    而是写进 :class:`XtbResult` 的 ``warnings`` / ``cancelled`` 字段。
    """

    def __init__(self, message: str, key: str = ""):
        super().__init__(message)
        self.key = str(key or "")


@dataclass
class XtbResult:
    """一次 xTB 计算（或一个已有结果目录）的完整结果。面板按这些字段显示。"""

    # 输入
    symbols: list = field(default_factory=list)
    input_coords: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    input_xyz: str = ""
    # 任务信息
    method: str = "gfn2"
    method_label: str = ""
    job: str = "sp"
    job_label: str = ""
    params: dict = field(default_factory=dict)
    command: list = field(default_factory=list)
    command_str: str = ""
    workdir: str = ""
    output_file: str = ""
    # 运行状态
    returncode: int = 0
    success: bool = False
    normal_termination: bool = False
    cancelled: bool = False
    elapsed: float = 0.0
    output_text: str = ""
    # 电子结构
    energy: float | None = None
    electronic_energy: float | None = None
    gap: float | None = None
    homo: float | None = None
    lumo: float | None = None
    dipole_debye: float | None = None
    gradient_norm: float | None = None
    charges: list = field(default_factory=list)
    orbital_energies: list = field(default_factory=list)
    occupations: list = field(default_factory=list)
    formula: str = ""
    # 优化/频率
    optimized_symbols: list = field(default_factory=list)
    optimized_coords: np.ndarray | None = None
    optimized_xyz_file: str = ""
    frequencies: list = field(default_factory=list)
    imaginary_count: int | None = None
    thermo: dict = field(default_factory=dict)
    # 扫描
    scan: list = field(default_factory=list)
    scan_file: str = ""
    # 产物文件
    json_file: str = ""
    charges_file: str = ""
    vibspectrum_file: str = ""
    # 提示
    warnings: list = field(default_factory=list)

    def __repr__(self) -> str:  # pragma: no cover - 只用于调试输出
        return (
            f"XtbResult(method={self.method!r}, job={self.job!r}, "
            f"energy={self.energy!r}, gap={self.gap!r}, "
            f"success={self.success!r}, rc={self.returncode!r}, "
            f"n_atoms={len(self.symbols)}, n_freq={len(self.frequencies)}, "
            f"n_scan={len(self.scan)})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 小工具：数值、符号、命令字符串
# ─────────────────────────────────────────────────────────────────────────────

_RE_NUM = r"[-+]?\d+(?:\.\d+)?(?:[EeDd][-+]?\d+)?"


def _to_float(value):
    """尽力转 float；失败返回 None（fortran 的 D 指数也认）。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip().replace("D", "E").replace("d", "e"))
    except (TypeError, ValueError):
        return None


def _coerce_int(value, default):
    """宽松转 int：3、"3"、3.0 都算 3；失败返回 default。"""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    num = _to_float(value)
    if num is None or num != int(num):
        return default
    return int(num)


def _coerce_float(value, default):
    num = _to_float(value)
    return default if num is None else num


def _fmt_num(value) -> str:
    """命令行里的数字：整数不带小数点，其余用 %g 去掉多余零。"""
    num = _to_float(value)
    if num is None:
        return str(value)
    if abs(num - round(num)) < 1e-12:
        return str(int(round(num)))
    return "%g" % num


def _normalize_symbol(symbol) -> str:
    """元素符号归一：CL → Cl，o → O，8 → O（数字按原子序数兜底）。"""
    text = str(symbol or "").strip()
    if not text:
        return ""
    if text.isdigit():
        idx = int(text)
        return _ELEMENT_SYMBOLS[idx] if 0 < idx < len(_ELEMENT_SYMBOLS) else ""
    return text[0].upper() + text[1:].lower()


def _clean_symbols(symbols) -> list:
    if symbols is None:
        return []
    if isinstance(symbols, str):
        return [_normalize_symbol(s) for s in symbols.split() if s.strip()]
    out = []
    for item in symbols:
        sym = _normalize_symbol(item)
        if sym:
            out.append(sym)
    return out


def _as_coords(coords, n_symbols: int = 0, lang: str = "zh") -> np.ndarray:
    """把任意坐标输入规范成 (N, 3) float 数组，并核对原子数。"""
    if coords is None:
        arr = np.zeros((0, 3), dtype=float)
    else:
        try:
            arr = np.asarray(coords, dtype=float)
        except (TypeError, ValueError) as exc:
            raise XtbError(t("err_coords_shape", lang)) from exc
        if arr.size == 0:
            arr = np.zeros((0, 3), dtype=float)
        else:
            if arr.ndim == 1 and arr.size == 3:
                arr = arr.reshape(1, 3)
            if arr.ndim != 2 or arr.shape[1] != 3:
                raise XtbError(t("err_coords_shape", lang))
            arr = np.array(arr, dtype=float, copy=True)
    if n_symbols and arr.shape[0] != n_symbols:
        raise XtbError(t("err_coords_shape", lang))
    return arr


def _command_str(command) -> str:
    """命令行 → 一行可读字符串（Windows 用 list2cmdline，其它平台 shlex）。"""
    parts = [str(item) for item in (command or [])]
    if not parts:
        return ""
    if os.name == "nt":
        return subprocess.list2cmdline(parts)
    return shlex.join(parts)


def _split_command_text(text: str) -> list:
    """把一行命令行拆回列表（仅用于从日志重建，不保证 100% 还原引号）。"""
    text = str(text or "").strip()
    if not text:
        return []
    try:
        if os.name == "nt":
            parts = shlex.split(text, posix=False)
            return [p[1:-1] if len(p) >= 2 and p[0] == p[-1] == '"' else p for p in parts]
        return shlex.split(text)
    except ValueError:
        return text.split()


def formula_of(symbols) -> str:
    """Hill 式分子式：C、H 在前，其余按字母序；计数为 1 时不写数字。"""
    counts: dict = {}
    for sym in _clean_symbols(symbols):
        counts[sym] = counts.get(sym, 0) + 1
    if not counts:
        return ""
    head = [key for key in ("C", "H") if key in counts]
    tail = sorted(key for key in counts if key not in ("C", "H"))
    parts = []
    for key in head + tail:
        count = counts[key]
        parts.append(key if count == 1 else f"{key}{count}")
    return "".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# 可执行文件定位
# ─────────────────────────────────────────────────────────────────────────────


def _exe_from_candidate(candidate) -> str | None:
    """候选路径 → 真正的 xtb 可执行文件；目录会自动补 xtb.exe / xtb。"""
    if not candidate:
        return None
    try:
        path = Path(str(candidate)).expanduser()
        if path.is_file():
            return str(path)
        if path.is_dir():
            for name in ("xtb.exe", "xtb"):
                inside = path / name
                if inside.is_file():
                    return str(inside)
    except OSError:
        return None
    return None


def _candidate_paths(preferred: str):
    """按约定顺序给出候选：preferred → XTB_EXE → PATH → 常见安装位置。"""
    for item in (preferred, os.environ.get("XTB_EXE", "")):
        if item:
            yield item
    for name in ("xtb", "xtb.exe"):
        found = shutil.which(name)
        if found:
            yield found
    for item in COMMON_XTB_PATHS:
        yield item
    # conda 风格的安装（xtb 也常通过 conda-forge 装进当前环境）
    for suffix in (("Scripts", "xtb.exe"), ("Scripts", "xtb"),
                   ("Library", "bin", "xtb.exe"), ("bin", "xtb")):
        yield str(Path(sys.prefix).joinpath(*suffix))


def find_xtb_executable(preferred: str = "") -> str | None:
    """找本机 xtb 可执行文件，找不到返回 None（不抛异常，面板用来提示）。"""
    seen = set()
    for candidate in _candidate_paths(preferred):
        key = os.path.normcase(str(candidate))
        if key in seen:
            continue
        seen.add(key)
        hit = _exe_from_candidate(candidate)
        if hit:
            return hit
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 参数规范化与校验
# ─────────────────────────────────────────────────────────────────────────────


def _normalize_params(params) -> dict:
    """把面板传来的 dict 补全成完整参数（不修改入参，返回新 dict）。"""
    raw = params if isinstance(params, dict) else {}
    timeout_raw = raw.get("timeout")
    timeout = _to_float(timeout_raw)
    if timeout is not None and timeout <= 0:
        timeout = None
    return {
        "method": str(raw.get("method") or "gfn2").strip().lower(),
        "job": str(raw.get("job") or "sp").strip().lower(),
        "charge": _coerce_int(raw.get("charge", 0), 0),
        "uhf": _coerce_int(raw.get("uhf", 0), 0),
        "acc": _coerce_float(raw.get("acc", 1.0), 1.0),
        "etemp": _coerce_float(raw.get("etemp", 300.0), 300.0),
        "solvation": str(raw.get("solvation") or "gas").strip().lower(),
        "solvent": str(raw.get("solvent") or "water").strip().lower(),
        "parallel": _coerce_int(raw.get("parallel", 1), 1),
        "json": bool(raw.get("json", True)),
        "molden": bool(raw.get("molden", False)),
        "verbose": bool(raw.get("verbose", False)),
        "extra_args": str(raw.get("extra_args") or "").strip(),
        "xcontrol": str(raw.get("xcontrol") or ""),
        "timeout": timeout,
        "xtb_exe": str(raw.get("xtb_exe") or raw.get("xtb_path") or "").strip(),
        "lang": _norm_lang(raw.get("lang", "zh")),
    }


def _method_supports_solvation(method: str) -> bool:
    return str(method).strip().lower() not in _SOLVATION_UNSUPPORTED


def validate_params(params: dict, symbols=None) -> str | None:
    """校验参数，返回**本地化**错误文案；没问题返回 None。

    语言取自 ``params["lang"]``（默认中文）——本函数签名里没有 lang 参数，
    面板把它一起放进 params 即可。
    只做「明显不可能算」的检查：可执行文件存在性留给面板 / run_job。
    """
    p = params if isinstance(params, dict) else {}
    lang = _norm_lang(p.get("lang", "zh"))

    method = str(p.get("method") or "gfn2").strip().lower()
    if method not in METHODS:
        return t("err_method", lang, method=method)

    job = str(p.get("job") or "sp").strip().lower()
    if job not in JOB_TYPES:
        return t("err_job", lang, job=job)

    solvation = str(p.get("solvation") or "gas").strip().lower()
    if solvation not in SOLVATION_MODELS:
        return t("err_solvation", lang, solvation=solvation)

    charge_raw = p.get("charge", 0)
    charge = _coerce_int(charge_raw, None)
    if charge is None or not (-_MAX_CHARGE <= charge <= _MAX_CHARGE):
        return t("err_charge", lang, min=-_MAX_CHARGE, max=_MAX_CHARGE,
                 charge=charge_raw)

    uhf_raw = p.get("uhf", 0)
    uhf = _coerce_int(uhf_raw, None)
    if uhf is None or not (0 <= uhf <= _MAX_UHF):
        return t("err_uhf", lang, min=0, max=_MAX_UHF, uhf=uhf_raw)

    parallel_raw = p.get("parallel", 1)
    parallel = _coerce_int(parallel_raw, None)
    if parallel is None or parallel < 1:
        return t("err_parallel", lang, parallel=parallel_raw)

    acc_raw = p.get("acc", 1.0)
    acc = _to_float(acc_raw)
    if acc is None or not (_MIN_ACC <= acc <= _MAX_ACC):
        return t("err_acc", lang, min=_MIN_ACC, max=_MAX_ACC, acc=acc_raw)

    etemp_raw = p.get("etemp", 300.0)
    etemp = _to_float(etemp_raw)
    if etemp is None or etemp < 0:
        return t("err_etemp", lang, etemp=etemp_raw)

    # 溶剂名只在真正会用到的模型下检查（g-xTB 会忽略溶剂，不必为难用户）
    if solvation != "gas" and _method_supports_solvation(method):
        solvent = str(p.get("solvent") or "").strip().lower()
        allowed = SOLVENT_TABLE.get(solvation, ())
        if allowed and solvent not in allowed:
            model_label = SOLVATION_MODELS.get(solvation, {}).get(lang, solvation)
            return t("err_solvent", lang, solvent=solvent, model=model_label)

    if job == "scan" and not str(p.get("xcontrol") or "").strip():
        return t("err_scan_no_xcontrol", lang)

    if symbols is not None:
        try:
            n_atoms = len(symbols)
        except TypeError:
            n_atoms = 0
        if n_atoms == 0:
            return t("err_empty_structure", lang)

    return None


# ─────────────────────────────────────────────────────────────────────────────
# 命令行构造
# ─────────────────────────────────────────────────────────────────────────────


def _job_args(job: str) -> list:
    """计算类型 → 命令行开关。TS / scan 的 xcontrol 文件名是固定约定。"""
    if job == "opt":
        return ["--opt"]
    if job == "ohess":
        return ["--ohess"]
    if job == "hess":
        return ["--hess"]
    if job == "ts":
        return ["--opt", "--input", _XCONTROL_TS_NAME]
    if job == "scan":
        return ["--opt", "--input", _XCONTROL_SCAN_NAME]
    return []


def build_command(xtb_exe: str, params: dict, input_name: str,
                  workdir=None) -> list[str]:
    """拼 xTB 命令行。顺序固定：

    exe → 方法 → 计算类型 → --chrg/--uhf → --acc/--etemp → 溶剂化 →
    --parallel → --json/--molden/--verbose → extra_args → 输入文件名（最后）。

    ``workdir`` 只影响 xcontrol 文件名相对化，目前不参与拼接（xTB 在 cwd 里找
    ``--input`` 指定的文件，输入名也放在最后，所以保持简单）。
    """
    p = _normalize_params(params)
    cmd: list = [str(xtb_exe)]

    method = p["method"] if p["method"] in METHODS else "gfn2"
    cmd.extend(METHODS[method]["args"])

    job = p["job"] if p["job"] in JOB_TYPES else "sp"
    cmd.extend(_job_args(job))

    if p["charge"]:
        cmd.extend(["--chrg", str(int(p["charge"]))])
    if p["uhf"]:
        cmd.extend(["--uhf", str(int(p["uhf"]))])
    if abs(p["acc"] - 1.0) > 1e-9:
        cmd.extend(["--acc", _fmt_num(p["acc"])])
    if abs(p["etemp"] - 300.0) > 1e-9:
        cmd.extend(["--etemp", _fmt_num(p["etemp"])])

    solvation = p["solvation"] if p["solvation"] in SOLVATION_MODELS else "gas"
    if solvation != "gas" and _method_supports_solvation(method):
        solvent = p["solvent"] or "water"
        cmd.extend([f"--{solvation}", solvent])

    if p["parallel"] > 1:
        cmd.extend(["--parallel", str(int(p["parallel"]))])
    if p["json"]:
        cmd.append("--json")
    if p["molden"]:
        cmd.append("--molden")
    if p["verbose"]:
        cmd.append("--verbose")

    extra = p["extra_args"]
    if extra:
        try:
            cmd.extend(shlex.split(extra, posix=True))
        except ValueError:
            cmd.extend(extra.split())

    cmd.append(str(input_name))
    return cmd


def _resolve_executable(params: dict) -> tuple:
    """(可执行文件路径, 是否真的找到了)。找不到时给个占位符，让预览也能显示。"""
    preferred = str(params.get("xtb_exe") or "")
    found = find_xtb_executable(preferred)
    if found:
        return found, True
    return (preferred or "xtb"), False


def _find_gfn0_parameter(xtb_exe) -> Path | None:
    """在 xtb 安装目录里找 ``param_gfn0-xtb.txt``（GFN0 只从 cwd 读参数文件）。"""
    exe = Path(str(xtb_exe)).expanduser()
    candidates = []
    for parent in (exe.parent.parent, exe.parent):
        candidates.append(parent / "share" / "xtb" / "param_gfn0-xtb.txt")
        candidates.append(parent / "param_gfn0-xtb.txt")
    for cand in candidates:
        try:
            if cand.is_file():
                return cand
        except OSError:
            continue
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 输入文件准备
# ─────────────────────────────────────────────────────────────────────────────


def _write_text(path: Path, text: str) -> Path:
    """UTF-8 + LF 写文本（中文路径 / 空格都没问题）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path


def prepare_job(params: dict, symbols, coords, workdir, *,
                lang: str = "zh") -> dict:
    """为一次任务准备独立工作目录与输入文件。

    返回 ``{"workdir", "input_name", "input_xyz", "command", "command_str",
    "xcontrol", "warnings"}``。job=ts/scan 时会额外写 xcontrol 文件。
    """
    lang = _norm_lang(lang)
    raw = dict(params) if isinstance(params, dict) else {}
    raw.setdefault("lang", lang)
    p = _normalize_params(raw)

    sym = _clean_symbols(symbols)
    if not sym:
        raise XtbError(t("err_empty_structure", lang), key="err_empty_structure")
    arr = _as_coords(coords, len(sym), lang)

    err = validate_params(raw, sym)
    if err:
        raise XtbError(err)

    wd = Path(workdir).expanduser()
    try:
        wd.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise XtbError(t("err_workdir", lang, path=str(wd), detail=str(exc)),
                       key="err_workdir") from exc
    if not wd.is_dir():
        raise XtbError(t("err_workdir", lang, path=str(wd),
                         detail="not a directory"), key="err_workdir")
    probe = wd / ".molstudio_write_test"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise XtbError(t("err_workdir", lang, path=str(wd), detail=str(exc)),
                       key="err_workdir") from exc

    warnings: list = []
    # 清掉上一次运行留在同一目录里的产物（频率/优化结构/JSON），
    # 否则同目录重跑、换分子或换方法时会静默把旧数据当成本次结果。
    for stale_name in _STALE_ARTIFACTS:
        try:
            (wd / stale_name).unlink()
        except FileNotFoundError:
            continue
        except OSError:
            continue

    input_xyz = write_xyz(wd / _INPUT_NAME, sym, arr,
                          comment=f"MolStudio xTB {METHODS[p['method']]['en']}")
    p["input_xyz"] = str(input_xyz)

    xcontrol_path = None
    job = p["job"]
    if job == "scan":
        text = str(p.get("xcontrol") or "").strip()
        if not text:
            raise XtbError(t("err_scan_no_xcontrol", lang),
                           key="err_scan_no_xcontrol")
        xcontrol_path = _write_text(wd / _XCONTROL_SCAN_NAME, text + "\n")
    elif job == "ts":
        xcontrol_path = _write_text(wd / _XCONTROL_TS_NAME, _TS_XCONTROL_TEXT)

    if p["method"] in _SOLVATION_UNSUPPORTED and p["solvation"] != "gas":
        warnings.append(t("warn_gxtb_solvation", lang))

    xtb_exe, found = _resolve_executable(p)
    if not found:
        warnings.append(t("warn_no_xtb_path", lang))

    # 本机这个 build 的 GFN0 参数文件只从 cwd 找（XTBPATH 等无效）：
    # 把安装目录里的 param_gfn0-xtb.txt 复制到工作目录即可正常运行。
    if p["method"] == "gfn0":
        param = _find_gfn0_parameter(xtb_exe)
        if param is None:
            warnings.append(t("warn_gfn0_param", lang))
        else:
            try:
                shutil.copy2(param, wd / param.name)
            except OSError:
                warnings.append(t("warn_gfn0_param", lang))

    command = build_command(xtb_exe, p, _INPUT_NAME, wd)
    return {
        "workdir": wd,
        "input_name": _INPUT_NAME,
        "input_xyz": input_xyz,
        "command": command,
        "command_str": _command_str(command),
        "xcontrol": xcontrol_path,
        "warnings": warnings,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 子进程执行（流式 + 取消 + 超时）
# ─────────────────────────────────────────────────────────────────────────────

def _terminate_process(proc) -> None:
    try:
        if proc.poll() is None:
            proc.terminate()
    except OSError:
        pass


def _kill_process(proc) -> None:
    try:
        if proc.poll() is None:
            proc.kill()
    except OSError:
        pass


def run_command(command, workdir, *, on_line=None, should_cancel=None,
                env=None, timeout=None, lang: str = "zh") -> dict:
    """跑一个子进程，stdout/stderr 合并逐行回调，支持取消与超时。

    返回 ``{"returncode", "output", "cancelled", "elapsed", "timed_out"}``。
    取消 / 超时都**不抛异常**，只把 ``cancelled=True`` 带回来；启动失败才抛
    :class:`XtbError`（那时没法继续）。
    """
    lang = _norm_lang(lang)
    argv = [str(item) for item in (command or [])]
    if not argv:
        raise XtbError(t("err_launch", lang, detail="empty command"),
                       key="err_launch")

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    start = time.perf_counter()
    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(workdir) if workdir else None,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
    except (FileNotFoundError, PermissionError, OSError) as exc:
        raise XtbError(t("err_launch", lang, detail=str(exc)),
                       key="err_launch") from exc

    chunks: list = []
    line_queue: "queue.Queue" = queue.Queue()

    def _pump():                                    # 后台线程：把 stdout 推进队列
        stream = proc.stdout
        if stream is None:
            line_queue.put(None)
            return
        try:
            for raw in stream:
                line_queue.put(raw)
        except (OSError, ValueError):
            pass
        finally:
            line_queue.put(None)

    reader = threading.Thread(target=_pump, name="xtb-stream", daemon=True)
    reader.start()

    cancelled = False
    timed_out = False
    timeout_value = _to_float(timeout)
    timeout_cap = timeout_value if (timeout_value is not None and timeout_value > 0) else None

    while True:
        # 每一行都检查取消 / 超时：xtb 输出很快，等队列空下来再检查会来不及
        if should_cancel is not None:
            try:
                stop = bool(should_cancel())
            except Exception:
                stop = False
            if stop:
                cancelled = True
                _terminate_process(proc)
                break
        if timeout_cap is not None and (time.perf_counter() - start) > timeout_cap:
            # 超时也归到“被中止”：调用方按 cancelled 处理即可（timed_out 细化原因）
            timed_out = True
            cancelled = True
            _terminate_process(proc)
            break
        try:
            item = line_queue.get(timeout=0.05)
        except queue.Empty:
            continue
        if item is None:
            break
        text_line = str(item)
        chunks.append(text_line)
        if on_line is not None:
            try:
                on_line(text_line.rstrip("\r\n"))
            except Exception:                       # 界面回调出错不能中断计算
                pass

    # 收尾：把队列里剩下的行尽量捞回来（最多等 2 秒）
    deadline = time.perf_counter() + 2.0
    while time.perf_counter() < deadline:
        try:
            leftover = line_queue.get(timeout=0.05)
        except queue.Empty:
            continue
        if leftover is None:
            break
        text_line = str(leftover)
        chunks.append(text_line)
        if on_line is not None:
            try:
                on_line(text_line.rstrip("\r\n"))
            except Exception:
                pass

    try:
        proc.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        _kill_process(proc)
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            pass
    finally:
        try:
            if proc.stdout is not None:
                proc.stdout.close()
        except OSError:
            pass

    elapsed = time.perf_counter() - start
    returncode = proc.returncode
    if returncode is None:
        returncode = -9
    return {
        "returncode": int(returncode),
        "output": "".join(chunks),
        "cancelled": bool(cancelled),
        "elapsed": float(elapsed),
        "timed_out": bool(timed_out),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 文本输出解析
# ─────────────────────────────────────────────────────────────────────────────

_RE_TOTAL_ENERGY = re.compile(rf"TOTAL ENERGY\s+({_RE_NUM})\s+Eh", re.I)
_RE_TOTAL_ENERGY_COLON = re.compile(rf"total energy\s*:\s*({_RE_NUM})\s*Eh", re.I)
_RE_GAP = re.compile(rf"HOMO-LUMO GAP\s+({_RE_NUM})\s+eV", re.I)
_RE_GAP_COLON = re.compile(rf"HOMO-LUMO gap\s*:\s*({_RE_NUM})\s*eV", re.I)
_RE_GRADIENT = re.compile(rf"GRADIENT NORM\s+({_RE_NUM})\s+Eh", re.I)
_RE_ENTHALPY = re.compile(rf"TOTAL ENTHALPY\s+({_RE_NUM})\s+Eh", re.I)
_RE_FREE_ENERGY = re.compile(rf"TOTAL FREE ENERGY\s+({_RE_NUM})\s+Eh", re.I)
_RE_ZPE = re.compile(rf"zero[\s-]+point[\s-]+energy\s+({_RE_NUM})\s+Eh", re.I)
_RE_IMAG_COUNT = re.compile(r"#\s*imaginary freq\.?\s+(\d+)", re.I)
_RE_EIGVAL = re.compile(r"^\s*eigval\s*:\s*(.*)$", re.M)
_RE_WALL_TIME = re.compile(
    r"wall-time:\s*(\d+)\s*d,\s*(\d+)\s*h,\s*(\d+)\s*min,\s*([\d.]+)\s*sec", re.I)
_RE_NORMAL = re.compile(r"normal termination of xtb|finished run on", re.I)
_RE_ABNORMAL = re.compile(r"abnormal termination|Error termination|\[ERROR\]", re.I)


def _last_match_float(regex, text):
    """取最后一次匹配的浮点数（优化任务取最终能量）。"""
    value = None
    for match in regex.finditer(text or ""):
        value = _to_float(match.group(1))
    return value


def _dipole_from_text(text: str):
    """从 ``molecular dipole:`` 块取 ``full:`` 行的总偶极（Debye，第 4 列）。"""
    if not text:
        return None
    lowered = text.lower()
    start = lowered.find("molecular dipole")
    if start < 0:
        return None
    block = text[start:start + 4000]
    end = block.lower().find("molecular quadrupole")
    if end > 0:
        block = block[:end]
    for line in block.splitlines():
        if "full:" not in line.lower():
            continue
        numbers = [_to_float(tok) for tok in re.findall(_RE_NUM, line)]
        numbers = [num for num in numbers if num is not None]
        if len(numbers) >= 4:
            return numbers[3]
        if len(numbers) == 3:                       # 只有 x y z（a.u.），再找 Debye 行
            break
    match = re.search(rf"\|total\|\s+{_RE_NUM}\s+{_RE_NUM}\s+({_RE_NUM})\s+Debye",
                      block, re.I)
    if match:
        return _to_float(match.group(1))
    return None


def _wall_time_seconds(text: str):
    """取总 wall-time（“finished run” 之后的第一个 wall-time 才是整次运行）。"""
    if not text:
        return None
    matches = list(_RE_WALL_TIME.finditer(text))
    if not matches:
        return None
    finished = _RE_NORMAL.search(text)
    chosen = matches[0]
    if finished:
        later = [m for m in matches if m.start() > finished.start()]
        if later:
            chosen = later[0]
    days, hours, minutes, seconds = chosen.groups()
    return (int(days) * 86400 + int(hours) * 3600 + int(minutes) * 60
            + (_to_float(seconds) or 0.0))


def _imaginary_count_from_text(text: str):
    """虚频个数：优先 xTB 自己打印的 ``# imaginary freq.``，否则数 eigval。"""
    if not text:
        return None
    matches = list(_RE_IMAG_COUNT.finditer(text))
    if matches:
        return int(matches[-1].group(1))
    values: list = []
    for block in _RE_EIGVAL.findall(text):
        for token in block.split():
            num = _to_float(token)
            if num is not None:
                values.append(num)
    if values:
        return sum(1 for num in values if num < _IMAG_THRESHOLD)
    return None


def parse_output_text(text: str) -> dict:
    """解析 xTB 控制台输出文本（xtbout.json 缺失时的兜底来源）。"""
    text = text or ""
    thermo = {
        "free_energy": _last_match_float(_RE_FREE_ENERGY, text),
        "enthalpy": _last_match_float(_RE_ENTHALPY, text),
        "zpe": _last_match_float(_RE_ZPE, text),
    }
    energy = _last_match_float(_RE_TOTAL_ENERGY, text)
    if energy is None:
        energy = _last_match_float(_RE_TOTAL_ENERGY_COLON, text)
    gap = _last_match_float(_RE_GAP, text)
    if gap is None:
        gap = _last_match_float(_RE_GAP_COLON, text)
    return {
        "energy": energy,
        "gap": gap,
        "gradient_norm": _last_match_float(_RE_GRADIENT, text),
        "dipole_debye": _dipole_from_text(text),
        "thermo": thermo,
        "imaginary_count": _imaginary_count_from_text(text),
        "wall_time": _wall_time_seconds(text),
        "normal_termination": bool(_RE_NORMAL.search(text)),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 产物文件解析
# ─────────────────────────────────────────────────────────────────────────────


#: 这个 build 把 Windows 路径原样写进 "program call"：`\g` `\x` 之类不是合法 JSON
#: 转义，严格的 json.loads 会整份失败。三级兜底：先原样、再剔掉这个字段、最后修转义。
_RE_PROGRAM_CALL_FIELD = re.compile(
    r'"program\s*call"\s*:\s*"(?:[^"\\]|\\.)*"', re.S)
_RE_BAD_JSON_ESCAPE = re.compile(r'\\(?!["\\/bfnrtu])')
_RE_BAD_JSON_UNICODE = re.compile(r'\\u(?![0-9a-fA-F]{4})')


def _loads_lenient(text: str) -> dict:
    """尽力把 xtbout.json 解析出来；真不行返回 ``{}``（调用方退到文本解析）。"""
    for candidate in (
        text,
        _RE_PROGRAM_CALL_FIELD.sub('"program call": ""', text),
        _RE_BAD_JSON_ESCAPE.sub(r"\\\\", text),
        _RE_BAD_JSON_UNICODE.sub(r"\\\\u",
                                 _RE_BAD_JSON_ESCAPE.sub(r"\\\\", text)),
    ):
        try:
            data = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict):
            return data
    return {}


def parse_xtbout_json(path) -> dict:
    """读 ``xtbout.json``；文件缺失 / 不是合法 JSON 时返回 ``{}``。

    本机 xtb 6.7.1 写出的 ``"program call"`` 字段里是未转义的 Windows 路径
    （``E:\\gxtb\\...``），严格 ``json.loads`` 会直接报 Invalid \\escape。
    这里按 ``原样 → 剔掉 program call → 补非法转义`` 三级兜底解析，
    保证能量 / 电荷 / 轨道这些真正有用的字段一个都不丢。
    """
    try:
        text = Path(str(path)).read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return {}
    return _loads_lenient(text)


def _json_lookup(data: dict, *names):
    """按 key 名取 xtbout.json 的字段（容忍空格 / 斜杠 / 大小写差异）。"""
    if not isinstance(data, dict):
        return None
    normalized = {str(key).strip().lower(): value for key, value in data.items()}
    for name in names:
        key = str(name).strip().lower()
        if key in normalized:
            return normalized[key]
    loose = {re.sub(r"[\s/]+", "", str(key).lower()): value
             for key, value in data.items()}
    for name in names:
        key = re.sub(r"[\s/]+", "", str(name).lower())
        if key in loose:
            return loose[key]
    return None


def _json_float(data: dict, *names):
    return _to_float(_json_lookup(data, *names))


def _json_float_list(data: dict, *names) -> list:
    value = _json_lookup(data, *names)
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            num = _to_float(item)
            if num is not None:
                out.append(num)
        return out
    return []


def _json_dipole_debye(data: dict):
    """json 里的偶极是 a.u.，按 2.5417462 换成 Debye。"""
    value = _json_lookup(data, "dipole / a.u.", "dipole")
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        vector = [_to_float(item) for item in value[:3]]
        if all(item is not None for item in vector):
            norm = float(np.linalg.norm(np.asarray(vector, dtype=float)))
            return norm * _AU_TO_DEBYE
    single = _to_float(value)
    return None if single is None else abs(single) * _AU_TO_DEBYE


def parse_charges(path) -> list:
    """读 ``charges`` 文件（每行一个 partial charge）→ list[float]。"""
    try:
        text = Path(str(path)).read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return []
    charges = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for token in stripped.split():
            num = _to_float(token)
            if num is not None:
                charges.append(num)
    return charges


def parse_vibspectrum(path) -> list:
    """解析 ``vibspectrum`` → ``[{"mode","frequency","ir","symmetry"}]``。

    行格式：``mode  [symmetry]  wave number  IR intensity  [selection]``。
    负波数即虚频（前 6 个平动转动模式是 ``-0.00``，别当成虚频）。
    """
    try:
        text = Path(str(path)).read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return []
    modes = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "$")):
            continue
        parts = stripped.split()
        if not parts or not parts[0].isdigit():
            continue
        rest = parts[1:]
        symmetry = ""
        if rest:
            head = rest[0]
            num = _to_float(head)
            if num is None and head.lower() not in ("-", "yes", "no", "ir", "raman"):
                symmetry = head
                rest = rest[1:]
        if len(rest) < 2:
            continue
        frequency = _to_float(rest[0])
        intensity = _to_float(rest[1])
        if frequency is None or intensity is None:
            continue
        modes.append({
            "mode": int(parts[0]),
            "frequency": float(frequency),
            "ir": float(intensity),
            "symmetry": symmetry,
        })
    return modes


def read_xyz(path) -> tuple:
    """读 xyz（含 xtbopt.xyz 那种 comment 带 energy 的）→ (symbols, coords)。"""
    path = Path(str(path))
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError) as exc:
        raise XtbError(t("err_xyz_parse", "zh", path=str(path)),
                       key="err_xyz_parse") from exc
    lines = text.splitlines()
    if len(lines) < 2:
        raise XtbError(t("err_xyz_parse", "zh", path=str(path)),
                       key="err_xyz_parse")
    try:
        n_atoms = int(lines[0].split()[0])
    except (ValueError, IndexError) as exc:
        raise XtbError(t("err_xyz_parse", "zh", path=str(path)),
                       key="err_xyz_parse") from exc
    symbols = []
    coords = []
    for line in lines[2:2 + n_atoms]:
        parts = line.split()
        if len(parts) < 4:
            continue
        x, y, z = _to_float(parts[1]), _to_float(parts[2]), _to_float(parts[3])
        if x is None or y is None or z is None:
            continue
        symbols.append(_normalize_symbol(parts[0]))
        coords.append((x, y, z))
    if not symbols:
        raise XtbError(t("err_xyz_parse", "zh", path=str(path)),
                       key="err_xyz_parse")
    return symbols, np.asarray(coords, dtype=float)


def write_xyz(path, symbols, coords, comment: str = "MolStudio xTB") -> Path:
    """写标准 xyz（UTF-8、LF、无多余空行）。返回路径。"""
    path = Path(str(path))
    sym = _clean_symbols(symbols)
    arr = _as_coords(coords, len(sym), "zh")
    if not sym:
        raise XtbError(t("err_empty_structure", "zh"), key="err_empty_structure")
    lines = [str(len(sym)), str(comment or "").replace("\n", " ")]
    for symbol, (x, y, z) in zip(sym, arr):
        lines.append(f"{symbol:<2s} {x:>15.8f} {y:>15.8f} {z:>15.8f}")
    return _write_text(path, "\n".join(lines) + "\n")


_RE_SCAN_ENERGY = re.compile(rf"energy:\s*({_RE_NUM})", re.I)
_RE_SCAN_SCF_DONE = re.compile(rf"SCF done.*?E\s*=\s*({_RE_NUM})", re.I)
_RE_SCAN_E_EQUALS = re.compile(rf"\bE\s*=\s*({_RE_NUM})", re.I)


def _scan_energy_from_comment(line: str):
    """扫描帧的 comment 行取能量：新格式 ``energy: ... xtb: ...``，旧格式 ``SCF done``。"""
    for regex in (_RE_SCAN_ENERGY, _RE_SCAN_SCF_DONE, _RE_SCAN_E_EQUALS):
        match = regex.search(line or "")
        if match:
            return _to_float(match.group(1))
    return None


def parse_scan_log(path) -> list:
    """解析 ``xtbscan.log``（XMol 多帧）→ ``[{"step","energy","energy_relative",
    "symbols","coords"}]``。

    ``energy`` 是每帧总能（Eh）；``energy_relative`` 是相对**第一帧**的 ΔE，
    **单位同样是 Eh**（与 ``energy`` 自洽，画图时面板自行换 eV / kcal/mol）。
    扫描图通常以起点为零，所以第一帧的 relative 恒为 0。
    能量行兼容 ``energy: -7.33... xtb: 6.7.1`` 与旧版 ``SCF done`` 两种写法。
    """
    try:
        text = Path(str(path)).read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return []
    lines = text.splitlines()
    frames: list = []
    index = 0
    total = len(lines)
    while index < total:
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            continue
        try:
            n_atoms = int(stripped.split()[0])
        except (ValueError, IndexError):
            index += 1
            continue
        if n_atoms <= 0 or index + 1 >= total:
            index += 1
            continue
        energy = _scan_energy_from_comment(lines[index + 1])
        cursor = index + 2
        symbols: list = []
        coords: list = []
        for _ in range(n_atoms):
            if cursor >= total:
                break
            parts = lines[cursor].split()
            if len(parts) >= 4 and _to_float(parts[1]) is not None:
                symbols.append(_normalize_symbol(parts[0]))
                coords.append((_to_float(parts[1]), _to_float(parts[2]),
                               _to_float(parts[3])))
            cursor += 1
        if energy is not None and len(symbols) == n_atoms:
            frames.append({
                "step": len(frames) + 1,
                "energy": float(energy),
                "energy_relative": 0.0,
                "symbols": symbols,
                "coords": np.asarray(coords, dtype=float),
            })
        index = max(cursor, index + 1)

    if frames:
        reference = frames[0]["energy"]
        for frame in frames:
            frame["energy_relative"] = frame["energy"] - reference
    return frames


# ─────────────────────────────────────────────────────────────────────────────
# 结果组装
# ─────────────────────────────────────────────────────────────────────────────


def _add_warning(result: XtbResult, message: str) -> None:
    if message and message not in result.warnings:
        result.warnings.append(message)


def _homo_lumo(orbital_energies, occupations) -> tuple:
    """由轨道能 + 占据数推 HOMO / LUMO（xTB 文本不直接给这两个数）。"""
    orbitals = [value for value in (orbital_energies or [])]
    occs = [value for value in (occupations or [])]
    if not orbitals or len(occs) != len(orbitals):
        return None, None
    occupied = [e for e, occ in zip(orbitals, occs) if occ > 1e-3]
    virtual = [e for e, occ in zip(orbitals, occs) if occ <= 1e-3]
    homo = max(occupied) if occupied else None
    lumo = min(virtual) if virtual else None
    return homo, lumo


def _frequencies_from_json(data: dict) -> list:
    """vibspectrum 文件缺失时，从 xtbout.json 的 ``vibrational frequencies`` 重建。"""
    freqs = _json_float_list(data, "vibrational frequencies / rcm",
                             "vibrational frequencies")
    intensities = _json_float_list(data, "IR intensities / km/mol",
                                   "IR intensities")
    out = []
    for idx, value in enumerate(freqs):
        out.append({
            "mode": idx + 1,
            "frequency": float(value),
            "ir": float(intensities[idx]) if idx < len(intensities) else 0.0,
            "symmetry": "",
        })
    return out


def _populate_result(result: XtbResult, workdir: Path, lang: str) -> dict:
    """把工作目录里的产物灌进结果对象（json 为主，文本兜底）。返回文本解析结果。"""
    info = parse_output_text(result.output_text)
    result.normal_termination = bool(info.get("normal_termination"))
    data = parse_xtbout_json(workdir / "xtbout.json")
    if data:
        json_method = str(data.get("method") or "").strip()
        expected = str(METHODS[result.method].get("en", ""))
        if json_method and expected and json_method.lower() != expected.lower():
            # 目录里残留了上一次（别的泛函）的 JSON：忽略，避免静默错数。
            _add_warning(result, t("warn_stale_json", lang))
            data = {}
        else:
            result.json_file = str(workdir / "xtbout.json")

    energy = _json_float(data, "total energy")
    if energy is None:
        energy = info.get("energy")
    result.energy = energy
    result.electronic_energy = _json_float(data, "electronic energy")

    gap = _json_float(data, "HOMO-LUMO gap / eV", "HOMO-LUMO gap")
    if gap is None:
        gap = info.get("gap")
    result.gap = gap
    result.gradient_norm = info.get("gradient_norm")

    dipole = _json_dipole_debye(data)
    if dipole is None:
        dipole = info.get("dipole_debye")
    result.dipole_debye = dipole

    charges = _json_float_list(data, "partial charges")
    charges_path = workdir / "charges"
    if charges_path.is_file():
        result.charges_file = str(charges_path)
        if not charges:
            charges = parse_charges(charges_path)
    result.charges = charges

    result.orbital_energies = _json_float_list(data, "orbital energies / eV",
                                               "orbital energies")
    result.occupations = _json_float_list(data, "fractional occupation",
                                          "fractional occupations")
    result.homo, result.lumo = _homo_lumo(result.orbital_energies,
                                          result.occupations)

    # 热力学：文本是绝对值；json 里是热校正项，加回总能才是绝对值
    thermo = {}
    for key, value in (info.get("thermo") or {}).items():
        if value is not None:
            thermo[key] = float(value)
    if energy is not None:
        enthalpy_corr = _json_float(data, "total enthalpy")
        free_corr = _json_float(data, "total free energy")
        if "enthalpy" not in thermo and enthalpy_corr is not None:
            thermo["enthalpy"] = energy + enthalpy_corr
        if "free_energy" not in thermo and free_corr is not None:
            thermo["free_energy"] = energy + free_corr
    result.thermo = thermo

    vib_path = workdir / "vibspectrum"
    frequencies: list = []
    if vib_path.is_file():
        result.vibspectrum_file = str(vib_path)
        frequencies = parse_vibspectrum(vib_path)
    if not frequencies:
        frequencies = _frequencies_from_json(data)
    result.frequencies = frequencies

    imaginary = info.get("imaginary_count")
    if imaginary is not None:
        result.imaginary_count = int(imaginary)
    elif frequencies:
        result.imaginary_count = sum(
            1 for item in frequencies
            if _to_float(item.get("frequency")) is not None
            and _to_float(item.get("frequency")) < _IMAG_THRESHOLD)

    if result.job == "scan":
        scan_path = workdir / "xtbscan.log"
        if scan_path.is_file():
            result.scan_file = str(scan_path)
            result.scan = parse_scan_log(scan_path)

    optimized_path = workdir / "xtbopt.xyz"
    if optimized_path.is_file():
        try:
            symbols, coords = read_xyz(optimized_path)
            if len(symbols) != len(result.symbols):
                _add_warning(result, t("warn_bad_optimized_size", lang))
            else:
                result.optimized_symbols = symbols
                result.optimized_coords = coords
                result.optimized_xyz_file = str(optimized_path)
        except XtbError:
            _add_warning(result, t("warn_bad_optimized_xyz", lang))
    elif result.job == "scan" and result.scan:
        final = result.scan[-1]
        if len(final["symbols"]) == len(result.symbols):
            result.optimized_symbols = list(final["symbols"])
            result.optimized_coords = np.asarray(final["coords"], dtype=float)
            result.optimized_xyz_file = result.scan_file
        else:
            _add_warning(result, t("warn_bad_optimized_size", lang))

    if not result.elapsed and info.get("wall_time"):
        result.elapsed = float(info["wall_time"])
    return info


def _make_result(workdir: Path, output_text: str, params: dict, symbols: list,
                 coords: np.ndarray, *, returncode: int, cancelled: bool,
                 elapsed: float, command, command_str: str, lang: str) -> XtbResult:
    """构造 XtbResult 骨架（collect_results / load_results 共用）。"""
    method = params["method"] if params["method"] in METHODS else "gfn2"
    job = params["job"] if params["job"] in JOB_TYPES else "sp"
    output_path = workdir / _OUTPUT_NAME
    input_path = workdir / _INPUT_NAME
    return XtbResult(
        symbols=list(symbols),
        input_coords=coords,
        input_xyz=str(input_path) if input_path.is_file() else "",
        method=method,
        method_label=METHODS[method].get(lang, METHODS[method]["zh"]),
        job=job,
        job_label=JOB_TYPES[job].get(lang, JOB_TYPES[job]["zh"]),
        params=dict(params),
        command=[str(item) for item in (command or [])],
        command_str=str(command_str or ""),
        workdir=str(workdir),
        output_file=str(output_path) if output_path.is_file() else "",
        returncode=int(returncode),
        normal_termination=False,
        cancelled=bool(cancelled),
        elapsed=float(elapsed or 0.0),
        output_text=output_text or "",
        formula=formula_of(symbols),
    )


def _finalize_result(result: XtbResult, params: dict, lang: str) -> None:
    """判定 success 并汇总 warnings（失败信息不抛异常，交给面板显示）。"""
    if not result.command_str and result.command:
        result.command_str = _command_str(result.command)
    has_json = bool(result.json_file)
    result.success = bool(
        result.returncode == 0
        and not result.cancelled
        and (result.normal_termination or has_json)
    )

    if result.cancelled:
        timed_out = bool(params.get("timed_out"))
        if timed_out:
            _add_warning(result, t("err_timeout", lang,
                                   timeout=params.get("timeout", "?")))
        else:
            _add_warning(result, t("err_cancelled", lang))
    elif result.returncode != 0:
        _add_warning(result, t("err_run_failed", lang,
                               returncode=result.returncode))

    if not result.normal_termination and not result.cancelled:
        _add_warning(result, t("warn_no_normal_termination", lang))
    if params.get("method") in _SOLVATION_UNSUPPORTED and params.get("solvation", "gas") != "gas":
        _add_warning(result, t("warn_gxtb_solvation", lang))
    if result.energy is None and not result.cancelled:
        _add_warning(result, t("warn_no_results", lang))
    if (params.get("json") and not has_json and result.returncode == 0
            and params.get("method") not in _SOLVATION_UNSUPPORTED):
        _add_warning(result, t("warn_no_json", lang))


def collect_results(workdir, output_text, params, symbols, coords, *,
                    returncode: int = 0, cancelled: bool = False,
                    elapsed: float = 0.0, command=None, lang: str = "zh") -> XtbResult:
    """把一次运行的工作目录 + 输出文本整理成 :class:`XtbResult`。"""
    lang = _norm_lang(lang)
    wd = Path(str(workdir)).expanduser()
    p = _normalize_params(params)
    p["lang"] = lang
    raw = params if isinstance(params, dict) else {}
    p["timed_out"] = bool(raw.get("timed_out"))
    sym = _clean_symbols(symbols)
    arr = _as_coords(coords, len(sym), lang)
    result = _make_result(
        wd, output_text or "", p, sym, arr,
        returncode=returncode, cancelled=cancelled, elapsed=elapsed,
        command=command, command_str=_command_str(command), lang=lang,
    )
    _populate_result(result, wd, lang)
    _finalize_result(result, p, lang)
    return result


def _infer_params(workdir: Path, text: str, data: dict) -> dict:
    """从输出 / 产物反推参数（load_results 用）。

    只看 ``xtb.out`` 的头尾：头部有 ``# command:``（本模块写的），尾部有最终结果。
    """
    text = text or ""
    if len(text) > 12000:
        probe = text[:4000] + "\n" + text[-8000:]
    else:
        probe = text
    method = "gfn2"
    label = str(_json_lookup(data, "method") or "").strip().lower()
    label_map = {
        "g-xtb": "gxtb", "gxtb": "gxtb",
        "gfn2-xtb": "gfn2", "gfn1-xtb": "gfn1", "gfn0-xtb": "gfn0",
        "gfn-ff": "gfnff", "gfnff": "gfnff",
    }
    if label in label_map:
        method = label_map[label]
    elif re.search(r"--gxtb\b", probe):
        method = "gxtb"
    elif re.search(r"--gfnff\b", probe):
        method = "gfnff"
    else:
        match = re.search(r"--gfn\s+([012])\b", probe)
        if match:
            method = f"gfn{match.group(1)}"

    if (workdir / "xtbscan.log").is_file():
        job = "scan"
    elif re.search(r"--ohess\b", probe):
        job = "ohess"
    elif re.search(r"--hess\b", probe):
        job = "hess"
    elif re.search(r"--input\s+\S*xcontrol_ts", probe):
        job = "ts"
    elif re.search(r"--opt\b", probe):
        job = "opt"
    else:
        job = "sp"

    charge_match = re.search(r"--chrg\s+(-?\d+)", probe)
    uhf_match = re.search(r"--uhf\s+(-?\d+)", probe)
    parallel_match = re.search(r"--parallel\s+(\d+)", probe)
    solvation = "gas"
    solvent = "water"
    for model in ("alpb", "gbsa", "cosmo"):
        match = re.search(rf"--{model}\s+([A-Za-z0-9_-]+)", probe)
        if match:
            solvation = model
            solvent = match.group(1).lower()
            break

    return _normalize_params({
        "method": method,
        "job": job,
        "charge": int(charge_match.group(1)) if charge_match else 0,
        "uhf": int(uhf_match.group(1)) if uhf_match else 0,
        "parallel": int(parallel_match.group(1)) if parallel_match else 1,
        "solvation": solvation,
        "solvent": solvent,
        "json": bool(data),
        "lang": "zh",
    })


def _command_from_log(text: str) -> str:
    """从 xtb.out 头部的 ``# command: ...`` 行取回命令行（load_results 用）。"""
    match = re.search(r"^#\s*command:\s*(.+)$", text or "", re.M)
    return match.group(1).strip() if match else ""


def load_results(workdir, *, symbols=None, coords=None, params=None,
                 lang: str = "zh") -> XtbResult:
    """从已有工作目录重建 :class:`XtbResult`（面板「载入结果目录」用）。

    参数缺省时会从 ``xtb.out``（若有）、``xtbout.json``、产物文件名反推；
    传了 ``symbols`` / ``coords`` / ``params`` 就以传入的为准（补缺）。
    """
    lang = _norm_lang(lang)
    wd = Path(str(workdir)).expanduser()
    if not wd.is_dir():
        raise XtbError(t("err_workdir", lang, path=str(wd),
                         detail="not a directory"), key="err_workdir")

    text = ""
    output_path = wd / _OUTPUT_NAME
    if output_path.is_file():
        try:
            text = output_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
    data = parse_xtbout_json(wd / "xtbout.json")

    merged = _infer_params(wd, text, data)
    if isinstance(params, dict):
        for key, value in params.items():
            if value is not None:
                merged[key] = value
    merged["lang"] = lang
    p = _normalize_params(merged)

    command_str = _command_from_log(text)
    if not command_str:
        command_str = str(_json_lookup(data, "program call") or "").strip()
        # 上面那个 json 字段可能被 xtb 的非法转义搞出控制字符（\b 被当成退格），去掉
        command_str = re.sub(r"[\x00-\x1f\x7f]", "", command_str)
    command = _split_command_text(command_str)

    sym = _clean_symbols(symbols) if symbols is not None else []
    arr = None
    if coords is not None:
        arr = _as_coords(coords, len(sym) if sym else 0, lang)
    if not sym or arr is None or arr.shape[0] == 0:
        input_path = wd / _INPUT_NAME
        if input_path.is_file():
            try:
                file_sym, file_arr = read_xyz(input_path)
            except XtbError:
                file_sym, file_arr = [], None
            if not sym:
                sym = file_sym
            if arr is None or arr.shape[0] == 0:
                arr = file_arr if file_arr is not None else np.zeros((0, 3))
    if not sym:
        # input.xyz 被删了：退到优化结构 / 扫描最后一帧，至少能显示原子
        for fallback in (wd / "xtbopt.xyz", wd / "xtbscan.log"):
            if not fallback.is_file():
                continue
            try:
                if fallback.suffix == ".log":
                    frames = parse_scan_log(fallback)
                    if not frames:
                        continue
                    sym = list(frames[-1]["symbols"])
                    arr = np.asarray(frames[-1]["coords"], dtype=float)
                else:
                    sym, arr = read_xyz(fallback)
            except XtbError:
                sym, arr = [], None
            if sym:
                break
    if arr is None:
        arr = np.zeros((0, 3))
    if sym and arr.shape[0] != len(sym):
        if arr.shape[0] == 0:
            # 只有原子符号没有坐标（产物里也没有 input.xyz）：给零坐标占位，
            # 至少保证 symbols / input_coords 长度一致，面板不会拿到错位数据。
            arr = np.zeros((len(sym), 3), dtype=float)
        else:
            raise XtbError(t("err_coords_shape", lang), key="err_coords_shape")

    info = parse_output_text(text)
    if info.get("normal_termination"):
        returncode = 0
    elif data:
        returncode = 0
    elif _RE_ABNORMAL.search(text or ""):
        returncode = 1
    else:
        returncode = 0

    result = _make_result(
        wd, text, p, sym, arr,
        returncode=returncode, cancelled=False, elapsed=0.0,
        command=command, command_str=command_str, lang=lang,
    )
    _populate_result(result, wd, lang)
    _finalize_result(result, p, lang)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 一次完整任务
# ─────────────────────────────────────────────────────────────────────────────

_OUTPUT_HEADER = "# " + "=" * 72


def _write_output_log(path: Path, command_str: str, workdir, text: str,
                      lang: str = "zh") -> Path:
    """把命令行 + 完整输出写进 ``xtb.out``（命令、输出都留在日志里）。"""
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    header = [
        _OUTPUT_HEADER,
        f"# MolStudio xTB  {stamp}",
        f"# workdir: {workdir}",
        f"# command: {command_str}",
        _OUTPUT_HEADER,
        "",
    ]
    return _write_text(path, "\n".join(header) + (text or ""))


def run_job(params: dict, symbols, coords, workdir, *, on_line=None,
            on_progress=None, should_cancel=None, lang: str = "zh") -> XtbResult:
    """跑一次完整的 xTB 任务：先准备输入，再执行，最后把结果写进 xtb.out 并解析。

    ``on_progress`` 会收到 ``(step, 本地化文字)``，step 依次是
    ``"preparing"`` / ``"running"`` / ``"parsing"`` / ``"done"``
    （只接受一个位置参数的回调也兼容，此时只传文字）。
    参数不合法、找不到可执行文件、工作目录不可写、启动失败都会抛
    :class:`XtbError`；进程非零退出 / 超时 / 取消不抛异常，结果里体现。
    """
    lang = _norm_lang(lang)

    def _progress(step: str) -> None:
        if on_progress is None:
            return
        text = t(f"phase_{step}", lang)
        try:
            on_progress(step, text)          # 面板约定：on_progress(step, 文字)
            return
        except TypeError:
            pass
        except Exception:
            return
        try:
            on_progress(text)                # 兼容只收一个参数的回调
        except Exception:
            pass

    _progress("preparing")
    raw = dict(params) if isinstance(params, dict) else {}
    raw.setdefault("lang", lang)
    prepared = prepare_job(raw, symbols, coords, workdir, lang=lang)

    command = prepared["command"]
    executable = command[0] if command else ""
    if not executable or not Path(executable).is_file():
        raise XtbError(t("err_xtb_not_found", lang, path=str(executable or "xtb")),
                       key="err_xtb_not_found")

    p = _normalize_params(raw)
    _progress("running")
    outcome = run_command(
        command,
        prepared["workdir"],
        on_line=on_line,
        should_cancel=should_cancel,
        timeout=p.get("timeout"),
        lang=lang,
    )

    _progress("parsing")
    output_path = Path(prepared["workdir"]) / _OUTPUT_NAME
    try:
        _write_output_log(output_path, prepared["command_str"],
                          prepared["workdir"], outcome["output"], lang=lang)
    except OSError as exc:
        # 日志写不了不至于让结果丢失，但要让用户知道
        prepared["warnings"].append(t("err_workdir", lang,
                                      path=str(output_path), detail=str(exc)))

    collect_params = dict(p)
    collect_params["timed_out"] = bool(outcome.get("timed_out"))
    result = collect_results(
        prepared["workdir"], outcome["output"], collect_params,
        symbols, coords,
        returncode=outcome["returncode"], cancelled=outcome["cancelled"],
        elapsed=outcome["elapsed"], command=command, lang=lang,
    )
    for warning in prepared["warnings"]:
        _add_warning(result, warning)
    _progress("done")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 结构导出（给 Gaussian 等程序）
# ─────────────────────────────────────────────────────────────────────────────


def write_gjf(path, symbols, coords, *,
              route: str = "#p opt freq b3lyp/6-31g(d)",
              charge: int = 0, mult: int = 1,
              title: str = "MolStudio xTB structure") -> Path:
    """把结构写成 Gaussian .gjf（能被 surface_projection.load_atoms 原样读回）。"""
    path = Path(str(path))
    sym = _clean_symbols(symbols)
    arr = _as_coords(coords, len(sym), "zh")
    if not sym:
        raise XtbError(t("err_empty_structure", "zh"), key="err_empty_structure")
    lines = [
        str(route or "").strip() or "#p opt freq b3lyp/6-31g(d)",
        "",
        str(title or "").replace("\n", " "),
        "",
        f"{int(charge)} {max(1, int(mult))}",
    ]
    for symbol, (x, y, z) in zip(sym, arr):
        lines.append(f"{symbol:<2s} {x:>16.10f} {y:>16.10f} {z:>16.10f}")
    lines.append("")
    return _write_text(path, "\n".join(lines))
