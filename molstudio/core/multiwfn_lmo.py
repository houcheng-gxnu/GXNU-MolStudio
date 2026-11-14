# -*- coding: utf-8 -*-
"""Multiwfn 轨道定域化（LMO，主功能 19）——Qt-free 核心模块
================================================================

本模块封装 Multiwfn 2026.x 的「主功能 19 → Orbital localization analysis」，
供 LMO 面板（PyQt UI）在后台线程里调用；除 ``multiwfn_exe`` / fchk 路径外不
依赖任何 GUI 组件，可直接单测。

**本模块只有纯文本解析 + 子进程调用，import 时不加载 Qt。**

对外 API
--------
``LMO_METHODS`` / ``COMPOSITION_METHODS`` / ``DEFAULT_SETTINGS``
    下拉框用的方法表与默认分析设置（阈值为**分数**，0.85 = 85%）。
``build_sequence(settings)``
    拼出喂给 Multiwfn 的完整 stdin 序列（含主功能 19；只发送非默认设置）。
``parse_lmo_output(text)``
    纯文本解析 Multiwfn stdout：收敛过程、LMO 能量、LMO 特征（单中心/双中心/
    离域）、开壳层 alpha/beta 编号、核心轨道跳过、new.fch 导出/重载等。
``parse_lmocen(text)``
    解析 ``LMOcen.txt``（LMO 中心坐标，Bohr + Å）。
``run_localization(...)``
    完整流程：ASCII 临时工作目录 → 复制 sys.fchk → 跑 Multiwfn → 解析 →
    把 ``<stem>_LMO.fch`` / ``<stem>_LMOcen.txt`` / ``<stem>_LMOdip.txt`` /
    ``<stem>_LMO.log`` 复制回 ``out_dir``。
``gen_lmo_cube(...)``
    从定域化后的 fchk 生成指定 LMO 的 cube（复用
    ``molstudio.core.fchk_orbital.gen_cube``）。
``settings_summary(settings, lang="zh")``
    一行人类可读摘要（UI 状态栏 / 日志用，可选）。

Multiwfn 交互要点（2026.4.10 实测）
------------------------------------
* 主菜单先输入 ``19`` 进入定域化菜单。
* ``-6`` 方法（1/2/3/10）、``-4`` 能量（0/1/2，2 再问 Fock 文件路径）、
  ``-9`` 组成（0/1/2/3）、``-10`` 阈值（**分数**逗号分隔，如 ``0.9,0.85``）、
  ``-8`` 计算 LMO 中心/偶极、``-5`` 是否定域核心轨道、``-2`` 收敛判据、
  ``-1`` 最大轮数；最后 ``1``/``2`` 开始定域化。
* ``-8`` 开启后，定域化结束会问 ``Would you like to perform dipole moment
  analysis for occupied LMOs? (y/n)``，需要在 ``q`` 之前回答 y/n。
* 开壳层：alpha 轨道编号 1..N_alpha，beta 轨道编号全局为 N_alpha+1 起，
  但 beta 的 LMO 特征块内部编号**从 1 重新开始**，解析时要加 ``n_alpha_total``。
"""

from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time


#: Bohr → Å（CODATA 2018）
BOHR_TO_ANG = 0.529177210903

#: run_localization 默认超时（秒）——大体系定域化可能较慢
DEFAULT_TIMEOUT = 10800

#: 定域化方法（Multiwfn ``-6`` 子菜单代码）
LMO_METHODS = {
    "pm_mulliken": {"code": "1",
                    "name_zh": "Pipek-Mezey（Mulliken 布居）",
                    "name_en": "Pipek–Mezey (Mulliken)"},
    "pm_lowdin": {"code": "2",
                  "name_zh": "Pipek-Mezey（Löwdin 布居）",
                  "name_en": "Pipek–Mezey (Löwdin)"},
    "pm_becke": {"code": "3",
                 "name_zh": "Pipek-Mezey（Becke 布居）",
                 "name_en": "Pipek–Mezey (Becke)"},
    "foster_boys": {"code": "10",
                    "name_zh": "Foster-Boys",
                    "name_en": "Foster–Boys"},
}

#: 轨道组成计算方法（Multiwfn ``-9`` 子菜单代码）
COMPOSITION_METHODS = {
    "none": {"code": "0",
             "name_zh": "不计算轨道组成",
             "name_en": "Do not calculate orbital compositions"},
    "mulliken": {"code": "1",
                 "name_zh": "Mulliken（占据）/ SCPA（非占据）",
                 "name_en": "Mulliken (occupied) / SCPA (unoccupied)"},
    "hirshfeld": {"code": "2",
                  "name_zh": "Hirshfeld",
                  "name_en": "Hirshfeld"},
    "becke": {"code": "3",
              "name_zh": "Becke 布居",
              "name_en": "Becke population"},
}

#: 默认分析设置。阈值为分数（0.85 → 85%），与 Multiwfn 菜单的百分数对应。
DEFAULT_SETTINGS = {
    "method": "pm_mulliken",       # LMO_METHODS 的键
    "scope": "occupied",           # "occupied"（选项 1）| "both"（选项 2）
    "calc_energy": True,
    "energy_source": "mo",         # "mo"（子选项 1）| "file"（子选项 2）
    "fock_file": "",               # energy_source == "file" 时使用
    "composition": "hirshfeld",    # COMPOSITION_METHODS 的键
    "threshold_single": 0.85,      # 分数；0.85 → 85%
    "threshold_two": 0.80,
    "localize_core": True,         # False → 发送一次 -5
    "centers": False,              # True → 发送 -8，随后偶极问题答 n
    "dipole": False,               # 仅 centers=True 时有效；答 y/n
    "convergence": 1e-4,           # 与 Multiwfn 默认 1e-4 不同才发送
    "max_cycles": 80,              # 与 Multiwfn 默认 80 不同才发送
}

#: Multiwfn 内建默认值（用于「只发送非默认设置」判断）
_MW_DEFAULT_METHOD = "pm_mulliken"
_MW_DEFAULT_COMPOSITION = "hirshfeld"
_MW_DEFAULT_THRESHOLD_SINGLE = 0.85
_MW_DEFAULT_THRESHOLD_TWO = 0.80
_MW_DEFAULT_CONVERGENCE = 1e-4
_MW_DEFAULT_MAX_CYCLES = 80


# ────────────────────────────── 设置处理 ──────────────────────────────

def _norm_frac(value, default):
    """把阈值规整成 0..1 的分数（容忍误传百分数，如 85 → 0.85）。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(v):
        return default
    if v > 1.0:            # 传进来的是百分数
        v /= 100.0
    return min(max(v, 0.0), 1.0)


def _fmt_frac(value):
    """分数 → Multiwfn ``-10`` 需要的文本（0.85 → "0.85"）。"""
    text = ("%.6f" % _norm_frac(value, 0.85)).rstrip("0").rstrip(".")
    return text or "0"


def _fmt_num(value):
    """收敛判据等浮点数 → 紧凑文本（1e-4 → "0.0001"）。"""
    text = ("%.10f" % float(value)).rstrip("0").rstrip(".")
    return text or "0"


def _merge_settings(settings=None):
    """默认设置 + 用户覆盖 → 规整后的新 dict（不修改入参 / DEFAULT_SETTINGS）。

    未知方法键 / 非法数值会抛 ``ValueError``（run_localization 会转成中文
    RuntimeError）。
    """
    s = dict(DEFAULT_SETTINGS)
    if settings:
        if not isinstance(settings, dict):
            raise ValueError("settings 必须是 dict")
        s.update(settings)

    if s["method"] not in LMO_METHODS:
        raise ValueError("未知的定域化方法：%r（可选：%s）"
                         % (s["method"], ", ".join(LMO_METHODS)))
    if s["scope"] not in ("occupied", "both"):
        raise ValueError("scope 只能是 'occupied' 或 'both'，收到：%r"
                         % (s["scope"],))
    if s["composition"] not in COMPOSITION_METHODS:
        raise ValueError("未知的轨道组成方法：%r（可选：%s）"
                         % (s["composition"], ", ".join(COMPOSITION_METHODS)))
    if s["energy_source"] not in ("mo", "file"):
        raise ValueError("energy_source 只能是 'mo' 或 'file'，收到：%r"
                         % (s["energy_source"],))

    s["threshold_single"] = _norm_frac(
        s.get("threshold_single"), _MW_DEFAULT_THRESHOLD_SINGLE)
    s["threshold_two"] = _norm_frac(
        s.get("threshold_two"), _MW_DEFAULT_THRESHOLD_TWO)

    try:
        s["convergence"] = float(s.get("convergence"))
    except (TypeError, ValueError):
        raise ValueError("convergence 必须是数字")
    if not math.isfinite(s["convergence"]) or s["convergence"] <= 0:
        raise ValueError("convergence 必须为正数")

    try:
        s["max_cycles"] = int(float(s.get("max_cycles")))
    except (TypeError, ValueError):
        raise ValueError("max_cycles 必须是整数")
    if s["max_cycles"] <= 0:
        raise ValueError("max_cycles 必须为正整数")

    s["fock_file"] = str(s.get("fock_file") or "").strip()
    s["calc_energy"] = bool(s.get("calc_energy"))
    s["localize_core"] = bool(s.get("localize_core"))
    s["centers"] = bool(s.get("centers"))
    s["dipole"] = bool(s.get("dipole"))
    return s


# ────────────────────────────── stdin 序列 ──────────────────────────────

def build_sequence(settings: dict) -> str:
    """拼出运行一次 Multiwfn 主功能 19 的完整 stdin 文本。

    顺序与 Multiwfn 菜单一致：``-6`` → ``-4``(+子选项/文件路径) → ``-9`` →
    ``-10`` → ``-8`` → ``-5`` → ``-2`` → ``-1`` → ``1``/``2`` → (偶极 y/n)
    → ``q``；开头空行用于吃掉没有 settings.ini 时的 "Press ENTER button to
    continue"。

    只发送**非默认**设置，因此默认配置下序列很短，也不会覆盖用户
    settings.ini 里的其它选项。
    """
    s = _merge_settings(settings)
    parts = ["\n", "19\n"]

    # -6 定域化方法（Multiwfn 默认 Pipek-Mezey/Mulliken，非默认才发送）
    if s["method"] != _MW_DEFAULT_METHOD:
        parts.append("-6\n%s\n" % LMO_METHODS[s["method"]]["code"])

    # -4 是否计算 / 如何计算 LMO 能量（Multiwfn 默认不计算）
    if s["calc_energy"]:
        if s["energy_source"] == "file":
            if not s["fock_file"]:
                raise ValueError(
                    "energy_source='file' 但没有提供 Fock/KS 矩阵文件路径")
            parts.extend(["-4\n", "2\n", s["fock_file"] + "\n"])
        else:
            parts.extend(["-4\n", "1\n"])

    # -9 轨道组成方法（Multiwfn 默认 Hirshfeld）
    if s["composition"] != _MW_DEFAULT_COMPOSITION:
        parts.append("-9\n%s\n" % COMPOSITION_METHODS[s["composition"]]["code"])

    # -10 单中心/双中心阈值（Multiwfn 默认 85/80 %，此处传分数）
    if (abs(s["threshold_single"] - _MW_DEFAULT_THRESHOLD_SINGLE) > 1e-9
            or abs(s["threshold_two"] - _MW_DEFAULT_THRESHOLD_TWO) > 1e-9):
        parts.append("-10\n%s,%s\n"
                     % (_fmt_frac(s["threshold_single"]),
                        _fmt_frac(s["threshold_two"])))

    # -8 计算 LMO 中心（先切到 Yes；定域化结束会追问偶极）
    if s["centers"]:
        parts.append("-8\n")

    # -5 是否定域核心轨道（Multiwfn 默认 Yes，仅在关闭时发送）
    if not s["localize_core"]:
        parts.append("-5\n")

    # -2 收敛判据 / -1 最大轮数（与 Multiwfn 默认不同才发送）
    if abs(s["convergence"] - _MW_DEFAULT_CONVERGENCE) > 1e-12:
        parts.append("-2\n%s\n" % _fmt_num(s["convergence"]))
    if s["max_cycles"] != _MW_DEFAULT_MAX_CYCLES:
        parts.append("-1\n%d\n" % s["max_cycles"])

    # 1 = 只定域占据轨道；2 = 占据/非占据分别定域
    parts.append("2\n" if s["scope"] == "both" else "1\n")

    # 仅当开启了 -8 才会出现偶极分析的 y/n 追问
    if s["centers"]:
        parts.append("y\n" if s["dipole"] else "n\n")

    parts.append("q\n")
    return "".join(parts)


# ────────────────────────────── stdout 解析 ──────────────────────────────

_RE_OPEN_ALPHA = re.compile(
    r"Orbitals from\s+(\d+)\s+to\s+(\d+)\s+are alpha,\s*"
    r"from\s+(\d+)\s+to\s+(\d+)\s+are occupied", re.I)
_RE_OPEN_BETA = re.compile(
    r"Orbitals from\s+(\d+)\s+to\s+(\d+)\s+are beta,\s*"
    r"from\s+(\d+)\s+to\s+(\d+)\s+are occupied", re.I)
_RE_CLOSED_OCC = re.compile(
    r"Orbitals from\s+(\d+)\s+to\s+(\d+)\s+are occupied(?!\s*,)", re.I)
_RE_CORE = re.compile(
    r"Lowest\s+(\d+)\s+orbitals are regarded as core orbitals", re.I)
_RE_SECTION = re.compile(
    r"Localizing\s+(?:(alpha|beta)\s+)?(occupied|unoccupied)\s+orbitals\.\.\.",
    re.I)
_RE_CYCLE = re.compile(
    r"Cycle:\s*(\d+)\s+P:\s*(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s+"
    r"Delta P:\s*(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")
_RE_ENERGY = re.compile(
    r"^\s*(\d+)\s+Energy:\s*"
    r"(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*a\.u\.\s*"
    r"(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*eV\s*"
    r"Type:\s*(A\+B|A|B)\s*Occ:\s*([\d.]+)", re.M)
_RE_CHAR_BLOCK = re.compile(
    r"\*{3,}\s*Major character of\s+([^\n:]*?)\s*LMOs\s*:", re.I)
_RE_CHAR_SUB = re.compile(
    r"(Almost single center LMOs|Almost two-center LMOs|"
    r"More delocalized LMOs)\s*:\s*(?:\(([^)]*)\))?", re.I)
#: 一条 LMO 记录以 "编号:" 开头，后面跟 1~3 个 "原子号(元素) 百分比%"
#: （第二个及之后的原子**没有**再写 LMO 编号，所以不能只用一条正则抓全部）
_RE_CHAR_HEAD = re.compile(r"(\d+):\s+(?=\d+\()")
_RE_CHAR_ATOM = re.compile(r"(\d+)\(([A-Za-z]+)\s*\)\s*([\d.]+)%")
_RE_THRESHOLD = re.compile(r">\s*([\d.]+)\s*%")

_CHAR_KIND = {
    "almost single center lmos": "single",
    "almost two-center lmos": "two",
    "more delocalized lmos": "more",
}


def _empty_parsed():
    """parse_lmo_output 的空结果骨架（保证键齐全）。"""
    return {
        "converged": False,
        "sections": [],
        "energies": [],
        "character": {},
        "n_alpha_total": 0,
        "n_occupied": 0,
        "n_beta_occupied": 0,
        "core_skipped": False,
        "n_core": 0,
        "threshold_single": None,
        "threshold_two": None,
        "exported": False,
        "reloaded": False,
        "warnings": [],
    }


def parse_lmo_output(text: str) -> dict:
    """纯文本解析 Multiwfn 主功能 19 的 stdout，返回契约约定的字典。

    对重复打印的菜单、进度条、空行、非 ASCII 乱码都保持容忍；解析不到的
    字段留空/0/False，并尽量在 ``warnings`` 里说明，绝不因奇怪输入抛异常。
    """
    out = _empty_parsed()
    if not text:
        out["warnings"].append(
            "输出为空，未检测到轨道定域化过程（Localizing ... orbitals...）")
        return out
    if not isinstance(text, str):
        try:
            text = str(text)
        except Exception:
            out["warnings"].append("输出内容无法作为文本解析")
            return out

    warnings = out["warnings"]

    # ── 波函数信息（闭壳层/开壳层、占据数）──────────────────────────
    m_alpha = _RE_OPEN_ALPHA.search(text)
    m_beta = _RE_OPEN_BETA.search(text)
    is_open = bool(m_alpha) or ("unrestricted single-determinant" in text.lower())
    if m_alpha:
        out["n_alpha_total"] = int(m_alpha.group(2))
        out["n_occupied"] = int(m_alpha.group(4))
    if m_beta:
        beta_start = int(m_beta.group(3))
        beta_end = int(m_beta.group(4))
        out["n_beta_occupied"] = max(0, beta_end - beta_start + 1)
    if not is_open:
        m_closed = _RE_CLOSED_OCC.search(text)
        if m_closed:
            out["n_occupied"] = int(m_closed.group(2))
    elif out["n_alpha_total"] == 0:
        warnings.append("输出像开壳层波函数，但未解析到 alpha 轨道总数，"
                        "beta LMO 编号可能未做全局偏移")

    # ── 核心轨道跳过 ────────────────────────────────────────────
    m_core = _RE_CORE.search(text)
    if m_core:
        out["core_skipped"] = True
        out["n_core"] = int(m_core.group(1))

    # ── 定域化收敛过程（按出现顺序切段）─────────────────────────
    sec_matches = list(_RE_SECTION.finditer(text))
    if not sec_matches:
        warnings.append(
            "未检测到轨道定域化过程（Localizing ... orbitals...），"
            "Multiwfn 可能未真正开始定域化")
    for i, m in enumerate(sec_matches):
        spin = (m.group(1) or "").lower()
        scope = (m.group(2) or "").lower()
        if spin == "alpha":
            kind = "alpha"
        elif spin == "beta":
            kind = "beta"
        else:
            kind = "unoccupied" if scope == "unoccupied" else "occupied"
        seg_start = m.end()
        seg_end = sec_matches[i + 1].start() if i + 1 < len(sec_matches) else len(text)
        seg = text[seg_start:seg_end]
        cycles = [int(c.group(1)) for c in _RE_CYCLE.finditer(seg)]
        deltas = [float(c.group(3)) for c in _RE_CYCLE.finditer(seg)]
        converged = "successfully converged" in seg.lower()
        if not converged:
            if "failed to converge" in seg.lower():
                warnings.append("定域化未收敛（%s 轨道段报告 Failed to converge）" % kind)
            else:
                warnings.append(
                    "定域化收敛状态未知（%s 轨道段未见 Successfully converged!）" % kind)
        out["sections"].append({
            "kind": kind,
            "converged": converged,
            "cycles": (cycles[-1] if cycles else 0),
            "final_delta_p": (deltas[-1] if deltas else 0.0),
        })

    # 所有段落都成功收敛 → 整体 converged；没有任何段落 → False
    out["converged"] = bool(out["sections"]) and all(
        sec["converged"] for sec in out["sections"])

    # ── LMO 能量表 ──────────────────────────────────────────────
    for m in _RE_ENERGY.finditer(text):
        try:
            row = {
                "index": int(m.group(1)),
                "energy_au": float(m.group(2)),
                "energy_ev": float(m.group(3)),
                "spin": m.group(4),
                "occ": float(m.group(5)),
            }
        except (ValueError, IndexError):
            continue
        out["energies"].append(row)

    # ── LMO 特征块 ──────────────────────────────────────────────
    char_blocks = list(_RE_CHAR_BLOCK.finditer(text))
    for bi, bm in enumerate(char_blocks):
        block_name = (bm.group(1) or "").strip().lower()
        b_start = bm.end()
        b_end = char_blocks[bi + 1].start() if bi + 1 < len(char_blocks) else len(text)
        block = text[b_start:b_end]
        if "beta" in block_name:
            spin = "B"
            offset = out["n_alpha_total"]
        elif "alpha" in block_name:
            spin = "A"
            offset = 0
        else:
            spin = "A+B"
            offset = 0

        subs = list(_RE_CHAR_SUB.finditer(block))
        for si, sm in enumerate(subs):
            kind = _CHAR_KIND.get(sm.group(1).lower())
            if kind is None:
                continue
            sub_start = sm.end()
            sub_end = subs[si + 1].start() if si + 1 < len(subs) else len(block)
            sub_text = block[sub_start:sub_end]

            # 阈值只从带百分数的括号里取；单/双中心分别记录（分数）
            th = _RE_THRESHOLD.search(sm.group(2) or "")
            if th:
                try:
                    frac = float(th.group(1)) / 100.0
                except ValueError:
                    frac = None
                if frac is not None:
                    if kind == "single" and out["threshold_single"] is None:
                        out["threshold_single"] = frac
                    elif kind == "two" and out["threshold_two"] is None:
                        out["threshold_two"] = frac

            # 一条记录 = "LMO编号:" + 1~3 个 "原子号(元素) 百分比%"
            heads = list(_RE_CHAR_HEAD.finditer(sub_text))
            for hi, hm in enumerate(heads):
                try:
                    lmo_index = int(hm.group(1)) + offset
                except (TypeError, ValueError):
                    continue
                rec_end = (heads[hi + 1].start()
                           if hi + 1 < len(heads) else len(sub_text))
                record = sub_text[hm.end():rec_end]
                atoms = []
                for am in _RE_CHAR_ATOM.finditer(record):
                    try:
                        atoms.append({
                            "index": int(am.group(1)),
                            "element": am.group(2),
                            "percent": float(am.group(3)),
                        })
                    except (TypeError, ValueError):
                        continue
                if not atoms:
                    continue
                atoms = atoms[:3]      # Multiwfn 每轨最多打印 3 个主要原子
                entry = out["character"].get(lmo_index)
                if entry is None:
                    out["character"][lmo_index] = {
                        "kind": kind,
                        "spin": spin,
                        "atoms": atoms,
                    }
                else:
                    # 同一 LMO 理论上只出现在一个子块；容错时保留更具体者
                    entry["atoms"].extend(atoms)

    # ── 导出 / 重新载入 new.fch ─────────────────────────────────
    low = text.lower()
    out["exported"] = "exporting localized orbitals to new.fch" in low
    reload_started = "loading new.fch" in low
    reload_finished = "loading finished!" in low
    out["reloaded"] = reload_started and reload_finished
    if out["exported"] and not reload_started:
        warnings.append("已导出 new.fch，但输出中未见重新载入 new.fch 的过程")
    elif reload_started and not reload_finished:
        warnings.append("检测到开始载入 new.fch，但未见 Loading finished!（结果可能不完整）")
    elif out["reloaded"] and not out["exported"]:
        warnings.append("检测到 new.fch 载入，但未见导出信息")

    # ── 运行期错误 ──────────────────────────────────────────────
    if "forrtl: severe" in low:
        warnings.append("Multiwfn 输出包含 Fortran 运行时错误（forrtl: severe），"
                        "结果可能不完整")
    if "forrtl: error" in low:
        warnings.append("Multiwfn 输出包含 Fortran 运行时错误（forrtl: error）")

    return out


# ────────────────────────────── LMOcen.txt ──────────────────────────────

_RE_LMOCEN_CLOSED = re.compile(
    r"^\s*LMO\s+(\d+)\s+corresponds to Bq\s+(\d+)\s*,\s*"
    r"X\s*,\s*Y\s*,\s*Z\s*:\s*"
    r"(-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)\s+"
    r"(-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)\s+"
    r"(-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)\s+Bohr", re.I)
_RE_LMOCEN_OPEN = re.compile(
    r"^\s*(Alpha|Beta)\s+LMO\s+(\d+)\s*:\s*Bq\s+(\d+)\s*,\s*"
    r"X\s*,\s*Y\s*,\s*Z\s*:\s*"
    r"(-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)\s+"
    r"(-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)\s+"
    r"(-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)\s+Bohr", re.I)


def _lmo_center_entry(bq, x, y, z):
    xyz = (float(x), float(y), float(z))
    return {
        "bq": int(bq),
        "xyz_bohr": xyz,
        "xyz_ang": tuple(c * BOHR_TO_ANG for c in xyz),
    }


def parse_lmocen(text: str) -> dict:
    """解析 ``LMOcen.txt``（LMO 中心坐标）。

    返回 ``{"closed": {lmo: {...}}, "alpha": {...}, "beta": {...}}``：

    * ``closed``：闭壳层，键为打印的 LMO 全局编号；
    * ``alpha`` / ``beta``：开壳层，键为**每自旋**编号（Beta 行从 1 开始）；
    * 每项 ``{"bq": int, "xyz_bohr": (x, y, z), "xyz_ang": (x, y, z)}``。

    空输入 / 乱码输入返回三个空 dict，不抛异常。
    """
    out = {"closed": {}, "alpha": {}, "beta": {}}
    if not text or not isinstance(text, str):
        return out

    for line in text.splitlines():
        mc = _RE_LMOCEN_CLOSED.match(line)
        if mc:
            try:
                out["closed"][int(mc.group(1))] = _lmo_center_entry(
                    mc.group(2), mc.group(3), mc.group(4), mc.group(5))
            except (TypeError, ValueError):
                continue
            continue
        mo = _RE_LMOCEN_OPEN.match(line)
        if mo:
            spin = "alpha" if mo.group(1).lower() == "alpha" else "beta"
            try:
                out[spin][int(mo.group(2))] = _lmo_center_entry(
                    mo.group(3), mo.group(4), mo.group(5), mo.group(6))
            except (TypeError, ValueError):
                continue
    return out


# ────────────────────────────── 摘要 ──────────────────────────────

def settings_summary(settings: dict, lang: str = "zh") -> str:
    """一行人类可读的分析设置摘要（UI 状态栏 / 日志用）。"""
    s = _merge_settings(settings)
    zh = (lang or "zh").lower().startswith("zh")
    method = LMO_METHODS[s["method"]]["name_zh" if zh else "name_en"]
    comp = COMPOSITION_METHODS[s["composition"]]["name_zh" if zh
                                                  else "name_en"]
    parts = [method]
    if zh:
        parts.append("仅占据轨道" if s["scope"] == "occupied"
                     else "占据 + 非占据轨道")
        if s["calc_energy"]:
            parts.append("能量（Fock 矩阵由 MO 生成）"
                         if s["energy_source"] == "mo"
                         else "能量（Fock 文件：%s）" % s["fock_file"])
        else:
            parts.append("不计算能量")
        parts.append("组成 %s" % comp)
        parts.append("单中心 %d%% / 双中心 %d%%"
                     % (round(s["threshold_single"] * 100),
                        round(s["threshold_two"] * 100)))
        parts.append("定域核心轨道" if s["localize_core"] else "跳过核心轨道")
        if s["centers"]:
            parts.append("LMO 中心位置" + (" + 偶极分析" if s["dipole"] else ""))
        parts.append("最多 %d 轮 / 收敛 %s"
                     % (s["max_cycles"], _fmt_num(s["convergence"])))
    else:
        parts.append("occupied only" if s["scope"] == "occupied"
                     else "occupied + unoccupied")
        if s["calc_energy"]:
            parts.append("energies (Fock from MO)" if s["energy_source"] == "mo"
                         else "energies (Fock file: %s)" % s["fock_file"])
        else:
            parts.append("no energies")
        parts.append("composition %s" % comp)
        parts.append("1-center %d%% / 2-center %d%%"
                     % (round(s["threshold_single"] * 100),
                        round(s["threshold_two"] * 100)))
        parts.append("localize core" if s["localize_core"] else "skip core")
        if s["centers"]:
            parts.append("LMO centers" + (" + dipole" if s["dipole"] else ""))
        parts.append("max %d cycles / conv %s"
                     % (s["max_cycles"], _fmt_num(s["convergence"])))
    return " · ".join(parts)


# ────────────────────────────── 子进程 / 工作目录 ──────────────────────────────

def _is_ascii_path(path):
    try:
        str(path).encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _safe_ascii_tmp_dir(prefix="molstudio_lmo_", exe_dir=None):
    """创建 Multiwfn 能正常读写的纯 ASCII 临时工作目录。

    与 ``etsnocv_panel._safe_ascii_tmp_dir`` 同一思路：Multiwfn（Fortran）
    无法处理中文路径；系统临时目录在中文 Windows 上常含中文用户名，故回退到
    Multiwfn 所在目录 / 盘符根目录。
    """
    def _mk(base=None):
        if base:
            return tempfile.mkdtemp(prefix=prefix, dir=base)
        return tempfile.mkdtemp(prefix=prefix)

    def _drop(path):
        """回退前清理已经建出来但不合用的目录（否则会残留）。"""
        try:
            shutil.rmtree(path, ignore_errors=True)
        except Exception:
            pass

    try:
        d = _mk()
        if _is_ascii_path(d):
            return d
        _drop(d)
    except OSError:
        pass

    cands = []
    if exe_dir:
        cands.append(exe_dir)
    if getattr(sys, "frozen", False):
        try:
            cands.append(os.path.dirname(os.path.abspath(sys.executable)))
        except Exception:
            pass
    try:
        cands.append(os.path.splitdrive(os.path.abspath(__file__))[0] + os.sep)
    except Exception:
        pass
    for base in cands:
        try:
            d = _mk(base)
            if _is_ascii_path(d):
                return d
            _drop(d)
        except OSError:
            continue
    return _mk()


def _emit_log(on_log, message):
    if on_log is None:
        return
    try:
        on_log(str(message))
    except Exception:
        pass


def _emit_stage(on_stage, pct, text):
    if on_stage is None:
        return
    try:
        on_stage(int(max(0, min(100, pct))), str(text))
    except Exception:
        pass


def _cancel_requested(cancel_check):
    if cancel_check is None:
        return False
    try:
        return bool(cancel_check())
    except Exception:
        return False


def _decode(data):
    if data is None:
        return ""
    if isinstance(data, (bytes, bytearray)):
        return bytes(data).decode("utf-8", errors="replace")
    return str(data)


def _base_result(settings, work_dir="", seconds=0.0):
    """构造返回值骨架（用于启动前取消等早退路径）。"""
    result = _empty_parsed()
    result.update({
        "ok": False,
        "error": "",
        "settings": settings,
        "raw": "",
        "lmo_fch": "",
        "cen_txt": "",
        "dip_txt": "",
        "log_path": "",
        "seconds": float(seconds),
        "work_dir": work_dir,
        "lmo_centers": {"closed": {}, "alpha": {}, "beta": {}},
    })
    return result


# ────────────────────────────── 完整流程 ──────────────────────────────

def run_localization(fchk_path, multiwfn_exe, settings=None, out_dir=None,
                     on_log=None, on_stage=None, cancel_check=None,
                     proc_holder=None, timeout=DEFAULT_TIMEOUT) -> dict:
    """运行一次完整的 Multiwfn 轨道定域化流程并收集产物。

    Parameters
    ----------
    fchk_path : str
        输入 fchk/fch 文件。
    multiwfn_exe : str
        Multiwfn 可执行文件。
    settings : dict, optional
        覆盖 ``DEFAULT_SETTINGS`` 的设置（键同 DEFAULT_SETTINGS）。
    out_dir : str, optional
        产物输出目录，默认 fchk 所在目录。
    on_log : callable(str), optional
        人类可读进度日志（中文）。
    on_stage : callable(pct:int, text:str), optional
        阶段/百分比进度。
    cancel_check : callable() -> bool, optional
        返回 True 表示用户请求取消；启动前与进程结束后各检查一次。
    proc_holder : dict, optional
        若提供，运行期间 ``proc_holder["proc"]`` 指向 Popen，便于外部终止；
        结束后自动移除。
    timeout : float
        Multiwfn 超时秒数，超时会杀进程并抛 RuntimeError。

    Returns
    -------
    dict
        ``parse_lmo_output`` 的全部字段 + ``ok/error/settings/raw/lmo_fch/
        cen_txt/dip_txt/log_path/seconds/work_dir``；另附 ``lmo_centers``
        （``parse_lmocen`` 的结果）。
    """
    t0 = time.time()
    try:
        s = _merge_settings(settings)
    except ValueError as exc:
        raise RuntimeError("分析设置无效：%s" % exc) from exc

    # ── 输入校验（中文错误信息）──────────────────────────────────
    fchk_path = os.path.abspath(str(fchk_path)) if fchk_path else ""
    if not fchk_path or not os.path.isfile(fchk_path):
        raise RuntimeError("找不到 fchk 文件：%s" % (fchk_path or "(空路径)"))
    if not multiwfn_exe:
        try:
            from .fchk_orbital import DEFAULT_MULTIWFN as multiwfn_exe
        except Exception:
            multiwfn_exe = ""
    multiwfn_exe = os.path.abspath(str(multiwfn_exe)) if multiwfn_exe else ""
    if not multiwfn_exe or not os.path.isfile(multiwfn_exe):
        raise RuntimeError("找不到 Multiwfn 可执行文件：%s"
                           % (multiwfn_exe or "(空路径)"))

    out_dir = os.path.abspath(str(out_dir)) if out_dir else os.path.dirname(fchk_path)
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError as exc:
        raise RuntimeError("无法创建输出目录：%s（%s）" % (out_dir, exc)) from exc

    stem = os.path.splitext(os.path.basename(fchk_path))[0]

    if s["calc_energy"] and s["energy_source"] == "file":
        if not s["fock_file"]:
            raise RuntimeError(
                "能量来源选择了 Fock 矩阵文件（energy_source='file'），"
                "但未提供 fock_file 路径")
        if not os.path.isfile(s["fock_file"]):
            raise RuntimeError("Fock/KS 矩阵文件不存在：%s" % s["fock_file"])

    # ── 启动前取消 ──────────────────────────────────────────────
    if _cancel_requested(cancel_check):
        res = _base_result(s, seconds=time.time() - t0)
        res["error"] = "已取消"
        res["warnings"].append("已取消（未启动 Multiwfn）")
        _emit_log(on_log, "已取消：未启动 Multiwfn。")
        return res

    _emit_log(on_log, "开始轨道定域化分析（Multiwfn 主功能 19）")
    _emit_log(on_log, "输入文件：%s" % fchk_path)
    _emit_log(on_log, "分析设置：%s" % settings_summary(s))
    _emit_stage(on_stage, 5, "准备分析环境")

    # ── ASCII 工作目录 + sys.fchk ───────────────────────────────
    try:
        work_dir = _safe_ascii_tmp_dir("molstudio_lmo_",
                                       exe_dir=os.path.dirname(multiwfn_exe))
    except OSError as exc:
        raise RuntimeError("无法创建 Multiwfn 临时工作目录：%s" % exc) from exc
    _emit_log(on_log, "Multiwfn 工作目录：%s" % work_dir)

    sequence = build_sequence(s)
    result = None
    try:
        try:
            shutil.copy2(fchk_path, os.path.join(work_dir, "sys.fchk"))
        except OSError as exc:
            raise RuntimeError("复制 fchk 到临时工作目录失败：%s" % exc) from exc
        for stale in ("new.fch", "LMOcen.txt", "LMOdip.txt"):
            try:
                os.remove(os.path.join(work_dir, stale))
            except OSError:
                pass

        # ── 运行 Multiwfn ───────────────────────────────────────
        creationflags = 0
        if sys.platform == "win32":
            creationflags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                             | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        _emit_stage(on_stage, 15, "启动 Multiwfn")
        _emit_log(on_log, "正在运行 Multiwfn ...（超时 %s 秒）" % timeout)
        run_started = time.time()
        try:
            proc = subprocess.Popen(
                [multiwfn_exe, "sys.fchk"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, cwd=work_dir,
                creationflags=creationflags)
        except OSError as exc:
            raise RuntimeError("无法启动 Multiwfn：%s" % exc) from exc
        if isinstance(proc_holder, dict):
            proc_holder["proc"] = proc
        # 用户可能在 fchk 复制阶段就点了「停止」：进程一启动就立刻终止，
        # 避免整轮定域化白跑完再被标记为取消（2026-11 独立评审指出）。
        if _cancel_requested(cancel_check):
            try:
                proc.terminate()
            except Exception:
                pass
        try:
            try:
                raw_bytes, _ = proc.communicate(
                    input=sequence.encode("utf-8"), timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:
                    pass
                try:
                    proc.communicate(timeout=10)
                except Exception:
                    pass
                raise RuntimeError(
                    "Multiwfn 运行超时（%s 秒），已终止进程" % timeout) from None
        finally:
            if isinstance(proc_holder, dict):
                proc_holder.pop("proc", None)
        raw = _decode(raw_bytes)
        run_seconds = time.time() - run_started
        rc = proc.returncode
        _emit_stage(on_stage, 78, "解析 Multiwfn 输出")
        _emit_log(on_log, "Multiwfn 运行结束，用时 %.1f s，退出码 %s"
                  % (run_seconds, rc))
        if rc not in (0, None):
            _emit_log(on_log, "提示：Multiwfn 退出码非 0（%s），请检查日志。" % rc)

        # ── 解析 ────────────────────────────────────────────────
        parsed = parse_lmo_output(raw)
        cancelled = _cancel_requested(cancel_check)
        if rc not in (0, None):
            parsed["warnings"].append(
                "Multiwfn 退出码非 0（%s），结果可能不完整，请查看日志" % rc)
        _emit_log(on_log, "定域化%s；过程段 %d 个；LMO 能量 %d 条；LMO 特征 %d 条"
                  % ("已收敛" if parsed["converged"] else "未收敛/状态未知",
                     len(parsed["sections"]), len(parsed["energies"]),
                     len(parsed["character"])))
        for warn in parsed["warnings"]:
            _emit_log(on_log, "警告：%s" % warn)

        # ── 复制产物 ────────────────────────────────────────────
        _emit_stage(on_stage, 90, "复制分析产物")
        new_fch = os.path.join(work_dir, "new.fch")
        try:
            produced = (os.path.isfile(new_fch)
                        and os.path.getsize(new_fch) > 0)
        except OSError:
            produced = False
        lmo_fch = ""
        if produced and not cancelled:
            lmo_fch = os.path.join(out_dir, "%s_LMO.fch" % stem)
            try:
                shutil.copy2(new_fch, lmo_fch)
            except OSError as exc:
                lmo_fch = ""
                parsed["warnings"].append("复制 new.fch 失败：%s" % exc)

        def _copy_product(src_name, dst_name):
            src = os.path.join(work_dir, src_name)
            if not os.path.isfile(src):
                return ""
            dst = os.path.join(out_dir, dst_name)
            try:
                shutil.copy2(src, dst)
                return dst
            except OSError as exc:
                parsed["warnings"].append("复制 %s 失败：%s" % (src_name, exc))
                return ""

        if cancelled:
            # 已取消：不把半成品（LMOcen/LMOdip）复制到用户输出目录。
            cen_txt = ""
            dip_txt = ""
        else:
            cen_txt = _copy_product("LMOcen.txt", "%s_LMOcen.txt" % stem)
            dip_txt = _copy_product("LMOdip.txt", "%s_LMOdip.txt" % stem)

        log_path = os.path.join(out_dir, "%s_LMO.log" % stem)
        try:
            # newline=""：Multiwfn 的 stdout 已含 \r\n，避免 Windows 文本模式
            # 再转一次导致日志里出现双空行
            with open(log_path, "w", encoding="utf-8", newline="") as fh:
                fh.write(raw)
        except OSError as exc:
            log_path = ""
            parsed["warnings"].append("写入日志失败：%s" % exc)

        lmo_centers = {"closed": {}, "alpha": {}, "beta": {}}
        cen_src = os.path.join(work_dir, "LMOcen.txt")
        if os.path.isfile(cen_src):
            try:
                with open(cen_src, "r", encoding="utf-8", errors="replace") as fh:
                    lmo_centers = parse_lmocen(fh.read())
            except OSError as exc:
                parsed["warnings"].append("读取 LMOcen.txt 失败：%s" % exc)
            total_centers = sum(len(v) for v in lmo_centers.values())
            _emit_log(on_log, "LMO 中心：%d 个（LMOcen.txt）" % total_centers)

        ok = bool(produced) and bool(lmo_fch) and not cancelled
        error = ""
        if cancelled:
            error = "已取消"
        elif not produced:
            error = "Multiwfn 未生成 new.fch，定域化可能失败或被取消"
        elif not lmo_fch:
            error = "已生成 new.fch，但复制到输出目录失败（详见警告）"

        if lmo_fch:
            _emit_log(on_log, "已生成定域化 fch：%s" % lmo_fch)
        if log_path:
            _emit_log(on_log, "完整 Multiwfn 输出：%s" % log_path)
        _emit_stage(on_stage, 100, "完成" if ok else "失败/取消")

        result = dict(parsed)
        result.update({
            "ok": ok,
            "error": error,
            "settings": s,
            "raw": raw,
            "lmo_fch": lmo_fch,
            "cen_txt": cen_txt,
            "dip_txt": dip_txt,
            "log_path": log_path,
            "seconds": time.time() - t0,
            "work_dir": work_dir,
            "lmo_centers": lmo_centers,
        })
        if ok:
            _emit_log(on_log, "轨道定域化完成。")
        else:
            _emit_log(on_log, "轨道定域化失败/取消：%s" % error)
        return result
    finally:
        # 保证任何异常（超时/取消/复制失败）都不会残留临时目录或 Popen 引用
        if isinstance(proc_holder, dict):
            proc_holder.pop("proc", None)
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
        except Exception:
            pass


# ────────────────────────────── LMO cube ──────────────────────────────

#: Multiwfn 主功能 5 → 4（输出某轨道的格点数据）的按键序列。开头空行吃掉
#: 没有 settings.ini 时的 "Press ENTER button to continue"；末尾 2/0/q 回到
#: 主菜单并退出。与 fchk_orbital.gen_cube 使用的序列一致。
_CUBE_SEQUENCE = "\n5\n4\n{index}\n{grid}\n2\n0\nq\n"


def gen_lmo_cube(lmo_fch_path, orbital_index, grid_quality=2, multiwfn_exe=None,
                 work_dir=None, name_prefix=None, timeout=600,
                 cancel_check=None, proc_holder=None):
    """从定域化后的 fchk 生成单个 LMO 的 cube 文件。

    每次都在**独立的 ASCII 临时目录**里跑 Multiwfn 5→4，再把
    ``MOvalue.cub`` 移到 ``<prefix>_LMO<index>.cub``。这样既不受 LMO fchk /
    输出目录里中文或空格路径影响，也不会像共用 ``_multiwfn_tmp`` 那样在
    上一次运行残留 / 与「轨道」页的 cube 生成并发时拿到过期 cube
    （2026-11 独立评审发现的真实缺陷）。开始前会先删掉同名旧 cube。

    Multiwfn 对开壳层文件接受**全局轨道编号**（如 76 = 第一个 beta LMO，
    等价于 ``-1``），因此这里直接传 ``str(index)``。

    Parameters
    ----------
    cancel_check : callable() -> bool, optional
        返回 True 时终止 Multiwfn 并返回 None（关窗/取消用）。
    proc_holder : dict, optional
        运行期间 ``proc_holder["proc"]`` 指向 Popen，便于外部终止。

    Returns
    -------
    str | None
        cube 路径；失败/取消返回 None。
    """
    if not lmo_fch_path or not os.path.isfile(str(lmo_fch_path)):
        return None
    lmo_fch_path = os.path.abspath(str(lmo_fch_path))
    if work_dir is None:
        work_dir = os.path.dirname(lmo_fch_path)
    work_dir = os.path.abspath(str(work_dir))
    try:
        os.makedirs(work_dir, exist_ok=True)
    except OSError:
        return None

    try:
        index = int(orbital_index)
    except (TypeError, ValueError):
        return None
    if index <= 0:
        return None

    if not multiwfn_exe:
        try:
            from .fchk_orbital import DEFAULT_MULTIWFN as multiwfn_exe
        except Exception:
            multiwfn_exe = ""
    multiwfn_exe = os.path.abspath(str(multiwfn_exe)) if multiwfn_exe else ""
    if not multiwfn_exe or not os.path.isfile(multiwfn_exe):
        return None

    # 轨道编号不能超过该波函数的实际轨道数。Multiwfn 对越界编号不会报错退出，
    # 而是继续消费后面的按键、最后默默输出 1 号轨道的 cube；只看“cube 是否
    # 生成”会把这种错误产物当成成功（2026-11 独立评审指出）。
    try:
        from molstudio.core.fchk_parser import parse_fchk_mo_info
        info = parse_fchk_mo_info(lmo_fch_path)
        n_orb = (len(info.get("alpha_energies") or [])
                 + len(info.get("beta_energies") or []))
        if n_orb and index > n_orb:
            return None
    except Exception:  # noqa: BLE001 - 解析失败不阻断，交给 Multiwfn 判定
        pass

    stem = os.path.splitext(os.path.basename(lmo_fch_path))[0]
    if name_prefix:
        prefix = str(name_prefix)
    elif stem.endswith("_LMO"):
        prefix = stem[:-4]
    else:
        prefix = stem
    dst = os.path.join(work_dir, "%s_LMO%d.cub" % (prefix, index))
    # 任何失败都不能把上一次的同名 cube 当成这次的结果返回。
    try:
        os.remove(dst)
    except OSError:
        pass

    try:
        grid = int(grid_quality)
    except (TypeError, ValueError):
        grid = 2
    grid = max(1, min(5, grid))
    sequence = _CUBE_SEQUENCE.format(index=index, grid=grid)

    temp_dir = ""
    try:
        temp_dir = _safe_ascii_tmp_dir("molstudio_lmo_cube_",
                                       exe_dir=os.path.dirname(multiwfn_exe))
        shutil.copy2(lmo_fch_path, os.path.join(temp_dir, "sys.fchk"))
        creationflags = 0
        if sys.platform == "win32":
            creationflags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                             | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        proc = subprocess.Popen(
            [multiwfn_exe, "sys.fchk"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, cwd=temp_dir,
            creationflags=creationflags)
        if isinstance(proc_holder, dict):
            proc_holder["proc"] = proc
        try:
            # 启动前就可能已经点了取消（如关窗）：立刻杀掉，不再白跑
            if _cancel_requested(cancel_check):
                try:
                    proc.terminate()
                except Exception:
                    pass
            try:
                proc.communicate(input=sequence.encode("utf-8"),
                                 timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:
                    pass
                try:
                    proc.communicate(timeout=10)
                except Exception:
                    pass
                return None
        finally:
            if isinstance(proc_holder, dict):
                proc_holder.pop("proc", None)
        if _cancel_requested(cancel_check):
            return None
        cube = os.path.join(temp_dir, "MOvalue.cub")
        if not os.path.isfile(cube) or os.path.getsize(cube) <= 0:
            return None
        # 临时目录常在 C: 盘、用户输出目录可能在别的盘：os.replace 跨盘会
        # 抛 WinError 17，必须用 shutil.move（先复制再删除）。
        shutil.move(cube, dst)
        if not os.path.isfile(dst) or os.path.getsize(dst) <= 0:
            return None
        return dst
    except Exception:  # noqa: BLE001 - 生成失败统一返回 None
        return None
    finally:
        if isinstance(proc_holder, dict):
            proc_holder.pop("proc", None)
        if temp_dir:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:  # noqa: BLE001 - 清理失败不影响返回
                pass


__all__ = [
    "BOHR_TO_ANG",
    "DEFAULT_TIMEOUT",
    "LMO_METHODS",
    "COMPOSITION_METHODS",
    "DEFAULT_SETTINGS",
    "build_sequence",
    "parse_lmo_output",
    "parse_lmocen",
    "run_localization",
    "gen_lmo_cube",
    "settings_summary",
]
