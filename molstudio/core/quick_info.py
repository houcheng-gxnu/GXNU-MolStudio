# -*- coding: utf-8 -*-
"""
quick_info.py — 文件「快速属性」解析（纯 Python，无 Qt）
=======================================================

给右侧检查器顶部的 ``PropertyCard`` 用的轻量解析器：只读文件、不做任何
计算，返回一个固定键集合的 dict，供界面显示分子式/分子量/能量/轨道/方法/
电荷/自旋/状态等信息。

支持的格式：

* ``.fchk`` / ``.fch`` —— 方法/基组、Total Energy、Alpha 轨道能量
  （按 ``Number of alpha electrons`` 切占据/空轨道）、电荷/多重度、
  Atomic numbers / Real atomic weights；
* ``.log`` / ``.out`` —— 最后一次 ``SCF Done`` 能量、最后一组
  ``Alpha occ./virt. eigenvalues``（homo/lumo）、电荷/多重度、route 里的
  方法/基组、热化学修正（ZPE / Gibbs）、Normal termination 状态；
  另外顺带从最后一个 orientation 表取分子式/分子量（有则填，无则 None）；
* ``.gjf`` / ``.com`` —— route 方法、电荷/多重度、直角坐标段 → 分子式/分子量；
* ``.xyz`` —— 原子数 + 元素 → 分子式/分子量。

所有键在缺数据时一律为 ``None``；文件读不了时也**不抛异常**，只返回
``path`` 与其余 None。分子式按 Hill 顺序（C、H，再按字母），分子量用标准
原子量（H 1.008、C 12.011…）；标准表中没有的元素才回退到 fchk 的
``Real atomic weights``，再没有就按 0.0 计。
"""

from __future__ import annotations

import os
import re
import time

from molstudio.core.fchk_orbital import ELEMENT_SYMBOLS

#: quick_info 返回的键（顺序固定，缺数据为 None）
INFO_KEYS = (
    "path", "formula", "mol_weight", "n_atoms", "energy", "zpe",
    "gibbs_corr", "homo", "lumo", "gap", "method", "charge",
    "multiplicity", "state", "task_time",
)

#: 符号 → 原子序数（供 .gjf/.xyz 解析）
_SYMBOL_TO_NUMBER = {symbol: number for number, symbol in ELEMENT_SYMBOLS.items()}

#: 标准原子量（IUPAC 常用值；H–Xe + 若干常见重元素）
STANDARD_ATOMIC_WEIGHTS = {
    1: 1.008, 2: 4.002602, 3: 6.94, 4: 9.0121831, 5: 10.81, 6: 12.011,
    7: 14.007, 8: 15.999, 9: 18.998403163, 10: 20.1797,
    11: 22.98976928, 12: 24.305, 13: 26.9815385, 14: 28.085,
    15: 30.973761998, 16: 32.06, 17: 35.45, 18: 39.948,
    19: 39.0983, 20: 40.078, 21: 44.955908, 22: 47.867, 23: 50.9415,
    24: 51.9961, 25: 54.938044, 26: 55.845, 27: 58.933194, 28: 58.6934,
    29: 63.546, 30: 65.38, 31: 69.723, 32: 72.630, 33: 74.921595,
    34: 78.971, 35: 79.904, 36: 83.798,
    37: 85.4678, 38: 87.62, 39: 88.90584, 40: 91.224, 41: 92.90637,
    42: 95.95, 43: 98.0, 44: 101.07, 45: 102.90550, 46: 106.42,
    47: 107.8682, 48: 112.414, 49: 114.818, 50: 118.710, 51: 121.760,
    52: 127.60, 53: 126.90447, 54: 131.293,
    55: 132.90545196, 56: 137.327, 57: 138.90547, 58: 140.116,
    59: 140.90766, 60: 144.242, 62: 150.36, 63: 151.964, 64: 157.25,
    65: 158.92535, 66: 162.500, 67: 164.93033, 68: 167.259,
    69: 168.93422, 70: 173.045, 71: 174.9668, 72: 178.49,
    73: 180.94788, 74: 183.84, 75: 186.207, 76: 190.23, 77: 192.217,
    78: 195.084, 79: 196.966569, 80: 200.592, 81: 204.38, 82: 207.2,
    83: 208.98040, 90: 232.0377, 92: 238.02891,
}

#: Gaussian orientation 表头（取最后一处完整表）
_ORIENTATION_HEADERS = (
    "Standard orientation:",
    "Input orientation:",
    "Z-Matrix orientation:",
)

#: "SCF Done:  E(RM06L) =  -234.335136146     A.U."
_SCF_DONE_RE = re.compile(
    r"SCF Done:\s+E\([^)]*\)\s*=\s*([+-]?(?:\d+\.\d*|\.\d+))")

#: 占据/空轨道能量块（Gaussian 每行都重复前缀）
_OCC_ORBITALS_RE = re.compile(r"^Alpha\s+occ\.\s+eigenvalues\s+--")
_VIRT_ORBITALS_RE = re.compile(r"^Alpha\s+virt\.\s+eigenvalues\s+--")

#: log 里的 "Charge =  0 Multiplicity = 1"
_CHARGE_MULT_RE = re.compile(
    r"Charge\s*=\s*([+-]?\d+)\s+Multiplicity\s*=\s*([+-]?\d+)")


__all__ = ["INFO_KEYS", "STANDARD_ATOMIC_WEIGHTS", "quick_info"]


# ── 小工具 ───────────────────────────────────────────────────────────

def _empty_info(path):
    """固定键集合的空结果（path 保留，其余 None）。"""
    info = {key: None for key in INFO_KEYS}
    info["path"] = None if path is None else str(path)
    return info


def _is_int_text(token):
    return token.lstrip("+-").isdigit()


def _is_dashes(text):
    return len(text) >= 3 and set(text) <= {"-"}


def _read_lines(path):
    """读文件所有行；失败返回 None（调用方不抛异常）。"""
    try:
        with open(str(path), "r", encoding="utf-8", errors="replace") as fh:
            return fh.readlines()
    except (OSError, TypeError, ValueError):
        return None


def _number_from_token(token):
    """``"C"`` / ``"6"`` → 原子序数（未知符号返回 0）。"""
    token = str(token).strip()
    if _is_int_text(token):
        return int(token)
    return _SYMBOL_TO_NUMBER.get(token.capitalize(), 0)


def _formula(numbers):
    """按 Hill 顺序生成分子式（C、H 优先，其余按字母序）。"""
    counts = {}
    for number in numbers:
        symbol = ELEMENT_SYMBOLS.get(number)
        if not symbol:
            symbol = "X%d" % number
        counts[symbol] = counts.get(symbol, 0) + 1
    if not counts:
        return None
    if "C" in counts:
        order = ["C"]
        if "H" in counts:
            order.append("H")
        order.extend(sorted(symbol for symbol in counts
                            if symbol not in ("C", "H")))
    else:
        order = sorted(counts)
    parts = []
    for symbol in order:
        count = counts[symbol]
        parts.append(symbol if count == 1 else "%s%d" % (symbol, count))
    return "".join(parts)


def _molecular_weight(numbers, real_weights=None):
    """分子量：标准原子量优先，未知元素回退 fchk 的 Real atomic weights。"""
    total = 0.0
    for index, number in enumerate(numbers):
        weight = STANDARD_ATOMIC_WEIGHTS.get(number)
        if weight is None and real_weights and index < len(real_weights):
            weight = real_weights[index]
        if weight is not None:
            total += float(weight)
    return total


def _apply_composition(info, numbers, real_weights=None):
    """统一填 formula / mol_weight / n_atoms。"""
    numbers = [int(number) for number in numbers if number is not None]
    if not numbers:
        return
    info["n_atoms"] = len(numbers)
    info["formula"] = _formula(numbers)
    info["mol_weight"] = _molecular_weight(numbers, real_weights)


# ── fchk 字段读取 ────────────────────────────────────────────────────

def _fchk_field_header(lines, label):
    """找 ``<label>  <类型>  N= <个数>`` 字段头，返回 ``(行号, 个数)``。"""
    pattern = re.compile(
        r"^\s*" + re.escape(label) + r"\s+[A-Za-z]\s+N=\s*(\d+)")
    for index, raw in enumerate(lines):
        match = pattern.match(raw)
        if match:
            return index, int(match.group(1))
    return -1, 0


def _collect_numbers(lines, header, count, caster):
    """从字段头之后收满 ``count`` 个数值为止。"""
    values = []
    for raw in lines[header + 1:]:
        tokens = raw.split()
        if not tokens:
            continue
        row = []
        for token in tokens:
            try:
                row.append(caster(token))
            except ValueError:
                return values[:count]
        values.extend(row)
        if len(values) >= count:
            break
    return values[:count]


def _line_scalar(lines, label, caster):
    """取以 ``label`` 开头的行里的第一个可转换 token（最后一个匹配行胜出）。

    Gaussian/fchk 的行格式并不统一，例如::

        Total Energy                               R     -2.343351361447706E+02
        Zero-point correction=                           0.138611 (Hartree/Particle)
         Thermal correction to Energy=                    0.145258

    因此先跳过 ``R``/``I`` 之类的类型列，再逐个 token 尝试转换（跳过
    ``(Hartree/Particle)`` 这类单位列）。热化学行前面还有一个空格，按
    lstrip 后的文本比较。
    """
    value = None
    for raw in lines:
        text = raw.lstrip()
        if not text.startswith(label):
            continue
        for token in text[len(label):].split():
            try:
                value = caster(token)
            except (TypeError, ValueError):
                continue
            break
    return value


def _fchk_method(lines):
    """fchk 第 2 行固定列 → ``方法/基组``（保留 R/U 前缀）。"""
    if len(lines) < 2:
        return None
    line = lines[1].rstrip("\r\n")
    if not line.strip():
        return None
    method = line[10:40].strip()
    basis = line[40:70].strip()
    if not basis:
        # 实测 G16 formchk：方法字段宽 60 列，基组从第 71 列起
        method = line[10:70].strip() or method
        basis = line[70:].strip()
    if not method or not basis:
        return None
    return "%s/%s" % (method, basis)


def _parse_fchk(lines, info):
    info["method"] = _fchk_method(lines)
    info["energy"] = _line_scalar(lines, "Total Energy", float)
    info["charge"] = _line_scalar(lines, "Charge", int)
    info["multiplicity"] = _line_scalar(lines, "Multiplicity", int)

    header, count = _fchk_field_header(lines, "Atomic numbers")
    numbers = (_collect_numbers(lines, header, count, int)
               if header >= 0 else [])
    if not numbers:
        header, count = _fchk_field_header(lines, "Nuclear charges")
        numbers = ([int(round(value)) for value in
                    _collect_numbers(lines, header, count, float)]
                   if header >= 0 else [])
    header, count = _fchk_field_header(lines, "Real atomic weights")
    real_weights = (_collect_numbers(lines, header, count, float)
                    if header >= 0 else [])
    _apply_composition(info, numbers, real_weights)

    header, count = _fchk_field_header(lines, "Alpha Orbital Energies")
    orbitals = (_collect_numbers(lines, header, count, float)
                if header >= 0 else [])
    if orbitals:
        n_alpha = _line_scalar(lines, "Number of alpha electrons", int)
        if n_alpha is None:
            n_electrons = _line_scalar(lines, "Number of electrons", int)
            if n_electrons:
                n_alpha = n_electrons // 2
        if n_alpha is not None and 0 < n_alpha <= len(orbitals):
            info["homo"] = orbitals[n_alpha - 1]
            if n_alpha < len(orbitals):
                info["lumo"] = orbitals[n_alpha]
    if info["homo"] is not None and info["lumo"] is not None:
        info["gap"] = info["lumo"] - info["homo"]
    info["state"] = "已载入"


# ── log 解析 ─────────────────────────────────────────────────────────

def _orbitals_from_log(lines):
    """解析最后一组 Alpha occ./virt. 能量块，返回 ``(homo, lumo)``。"""
    occ_blocks = []
    virt_blocks = []
    current = None
    kind = None
    for raw in lines:
        text = raw.strip()
        if _OCC_ORBITALS_RE.match(text):
            if kind != "occ":
                current = []
                occ_blocks.append(current)
            kind = "occ"
        elif _VIRT_ORBITALS_RE.match(text):
            if kind != "virt":
                current = []
                virt_blocks.append(current)
            kind = "virt"
        elif text:
            kind = None
            continue
        else:
            continue
        payload = text.split("--", 1)[1] if "--" in text else ""
        for token in payload.split():
            try:
                current.append(float(token))
            except ValueError:
                pass
    homo = occ_blocks[-1][-1] if occ_blocks and occ_blocks[-1] else None
    lumo = virt_blocks[-1][0] if virt_blocks and virt_blocks[-1] else None
    return homo, lumo


def _route_tokens(lines):
    """取出 route 段（第一个 ``#`` 行起的横幅块）的 token 列表。"""
    start = -1
    for index, raw in enumerate(lines):
        if raw.strip().startswith("#"):
            start = index
            break
    if start < 0:
        return []
    parts = []
    for raw in lines[start:]:
        text = raw.strip()
        if not text or _is_dashes(text):
            break
        parts.append(text)
    route = " ".join(parts).strip()
    if route.startswith("#"):
        route = route[1:].strip()
    return route.split()


def _method_from_route(lines):
    """route 中第一个含 ``/`` 的 token 即 ``方法/基组``。"""
    for token in _route_tokens(lines):
        if "/" in token:
            return token
    return None


def _orientation_atomic_numbers(lines):
    """取最后一个完整 orientation 表的原子序数列表（供 log 的分子式）。"""
    last_numbers = []
    for index, raw in enumerate(lines):
        if raw.strip() not in _ORIENTATION_HEADERS:
            continue
        header = -1
        for probe in range(index + 1, min(index + 16, len(lines))):
            text = lines[probe].strip()
            if "Center" in text and "Atomic" in text and "Coordinates" in text:
                header = probe
                break
        if header < 0:
            continue
        numbers = []
        in_rows = False
        for body in lines[header + 1:]:
            text = body.strip()
            if not text:
                if in_rows:
                    break
                continue
            if _is_dashes(text):
                if in_rows:
                    break
                in_rows = True
                continue
            if not in_rows:
                continue
            parts = text.split()
            if len(parts) < 6 or not parts[1].isdigit():
                break
            try:
                float(parts[3]), float(parts[4]), float(parts[5])
            except (ValueError, IndexError):
                break
            numbers.append(int(parts[1]))
        if numbers:
            last_numbers = numbers
    return last_numbers


def _parse_log(lines, info):
    info["method"] = _method_from_route(lines)

    energy = None
    for raw in lines:
        match = _SCF_DONE_RE.search(raw)
        if match:
            try:
                energy = float(match.group(1))
            except ValueError:
                continue
    info["energy"] = energy

    charge = multiplicity = None
    for raw in lines:
        match = _CHARGE_MULT_RE.search(raw)
        if match:
            charge, multiplicity = int(match.group(1)), int(match.group(2))
    info["charge"] = charge
    info["multiplicity"] = multiplicity

    homo, lumo = _orbitals_from_log(lines)
    info["homo"] = homo
    info["lumo"] = lumo
    if homo is not None and lumo is not None:
        info["gap"] = lumo - homo

    zero_point = _line_scalar(lines, "Zero-point correction=", float)
    thermal_energy = _line_scalar(lines, "Thermal correction to Energy=", float)
    info["zpe"] = thermal_energy if thermal_energy is not None else zero_point
    info["gibbs_corr"] = _line_scalar(
        lines, "Thermal correction to Gibbs Free Energy=", float)

    _apply_composition(info, _orientation_atomic_numbers(lines))
    info["state"] = ("已完成" if any("Normal termination" in raw
                                    for raw in lines) else "未完成")


# ── gjf / xyz 解析 ───────────────────────────────────────────────────

def _parse_gjf(lines, info):
    info["method"] = _method_from_route(lines)
    charge_line = -1
    charge = multiplicity = None
    route_seen = False
    for index, raw in enumerate(lines):
        text = raw.strip()
        if not text:
            continue
        if text.startswith("#"):
            route_seen = True
            continue
        if not route_seen:
            continue
        parts = text.split()
        if (len(parts) >= 2 and _is_int_text(parts[0])
                and _is_int_text(parts[1])):
            charge, multiplicity = int(parts[0]), int(parts[1])
            charge_line = index
            break
    info["charge"] = charge
    info["multiplicity"] = multiplicity

    numbers = []
    if charge_line >= 0:
        for raw in lines[charge_line + 1:]:
            text = raw.strip()
            if not text or text.startswith("--"):
                break
            parts = text.split()
            if len(parts) < 4:
                break
            try:
                float(parts[1]), float(parts[2]), float(parts[3])
            except ValueError:
                break
            numbers.append(_number_from_token(parts[0]))
    _apply_composition(info, numbers)
    info["state"] = "已载入"


def _parse_xyz(lines, info):
    expected = None
    if lines:
        tokens = lines[0].split()
        if tokens and _is_int_text(tokens[0]):
            expected = int(tokens[0])
    numbers = []
    for raw in lines[2:]:
        parts = raw.split()
        if len(parts) < 4:
            break
        try:
            float(parts[1]), float(parts[2]), float(parts[3])
        except ValueError:
            break
        numbers.append(_number_from_token(parts[0]))
    if expected is not None:
        numbers = numbers[:expected]
    _apply_composition(info, numbers)
    info["state"] = "已载入"


# ── 对外入口 ─────────────────────────────────────────────────────────

def quick_info(path):
    """读取 ``path`` 并返回属性摘要 dict（固定键，读不了也不抛异常）。

    返回值键见 :data:`INFO_KEYS`；文件不存在/读不了/格式不支持时，除
    ``path`` 外全部为 ``None``。
    """
    info = _empty_info(path)
    lines = _read_lines(path)
    if lines is None:
        return info

    try:
        modified = os.path.getmtime(str(path))
    except (OSError, TypeError, ValueError):
        modified = None
    if modified is not None:
        info["task_time"] = time.strftime("%Y-%m-%d %H:%M:%S",
                                          time.localtime(modified))

    extension = os.path.splitext(str(path))[1].lower()
    if extension in (".fchk", ".fch"):
        _parse_fchk(lines, info)
    elif extension in (".log", ".out"):
        _parse_log(lines, info)
    elif extension in (".gjf", ".com"):
        _parse_gjf(lines, info)
    elif extension == ".xyz":
        _parse_xyz(lines, info)
    return info
