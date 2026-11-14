# -*- coding: utf-8 -*-
"""
di_local.py — Distortion–Interaction（DI）本机 Gaussian 工作流核心（纯 Python）
================================================================================

DI 面板的「一键本机计算」流程：载入 TS 复合物的 Gaussian log / fchk，手工把
原子拆成两个碎片，然后生成 4 个 Gaussian 输入文件并依次在本机跑：

* ``{stem}_frag1_def.gjf`` / ``{stem}_frag2_def.gjf``
  —— 在 TS 几何下对两个碎片做单点（sp），得到 E_def；
* ``{stem}_frag1_opt.gjf`` / ``{stem}_frag2_opt.gjf``
  —— 两个碎片在同样理论水平下做几何优化（opt），得到 E_opt。

方法、基组与 SCF/积分网格等设置全部从 TS 任务的 route 行抄过来（去掉
``opt``/``freq``/``geom``/``chk`` 等与"单点/优化"冲突的关键字），坐标原样
照抄、不重新定向、不改变原子顺序——DI 的形变能必须在同一坐标系下比较。

本模块刻意不依赖 Qt / matplotlib，只用到标准库；``ELEMENT_SYMBOLS`` 复用
:mod:`molstudio.core.fchk_orbital` 的元素表，跑任务复用
:func:`molstudio.core.gaussian_run.run_gaussian`（模块级导入，测试里可
monkeypatch ``di_local.run_gaussian``）。界面层（di_analysis_panel）只负责
调用这里的纯函数，方便单元测试。
"""

from __future__ import annotations

import math
import os
import re

from molstudio.core.fchk_orbital import ELEMENT_SYMBOLS
from molstudio.core.gaussian_run import run_gaussian

#: fchk 坐标单位：Bohr → Å
BOHR_TO_ANGSTROM = 0.529177210903

#: 成键判据的距离容差（Å）：d < r1 + r2 + 容差
BOND_TOLERANCE = 0.45

#: 周期表共价半径（Å，与 di_analysis_panel 的 ATOM_RADII 保持一致）
ATOM_RADII = {
    "H": 0.31, "He": 0.28, "Li": 1.28, "Be": 0.96, "B": 0.84,
    "C": 0.76, "N": 0.71, "O": 0.66, "F": 0.57, "Ne": 0.58,
    "Na": 1.66, "Mg": 1.41, "Al": 1.21, "Si": 1.11, "P": 1.07,
    "S": 1.05, "Cl": 1.02, "Ar": 1.06, "K": 2.03, "Ca": 1.76,
    "Fe": 1.32, "Co": 1.26, "Ni": 1.24, "Cu": 1.32, "Zn": 1.22,
    "Br": 1.2, "I": 1.39,
}

#: 符号 → 原子序数（从 ELEMENT_SYMBOLS 反查，供 .xyz/.gjf 解析使用）
_SYMBOL_TO_NUMBER = {sym: number for number, sym in ELEMENT_SYMBOLS.items()}

#: Gaussian orientation 表头（取文件中最后一处完整表）
_ORIENTATION_HEADERS = (
    "Standard orientation:",
    "Input orientation:",
    "Z-Matrix orientation:",
)

#: route 中必须丢弃的"任务类型/几何/检查点"关键字（完整匹配）
_ROUTE_DROP_EXACT = frozenset(
    {"freq", "force", "stable", "sp", "allcheck", "job", "p"})

#: route 中必须丢弃的关键字前缀（opt=… / geom=… / guess=… / chk=… 等）
_ROUTE_DROP_PREFIX = ("opt", "geom", "guess", "chk", "output", "restart")

#: 4 个 DI 任务的角色顺序（前两个单点、后两个优化）
_ROLE_LABELS = {
    "frag1_def": "片段1 单点",
    "frag2_def": "片段2 单点",
    "frag1_opt": "片段1 优化",
    "frag2_opt": "片段2 优化",
}

#: 本机运行时转发给界面的 Gaussian 日志行标记（优化日志太大，只挑里程碑）。
#: 比较前会把行内连续空白压成一个空格，因此这里统一用单空格书写。
_PROGRESS_MARKERS = (
    "scf done",
    "normal termination",
    "error termination",
    "optimization completed",
    "stationary point found",
    "step number",
    "maximum force",
    "rms force",
    "converged?",
    "frequencies --",
    "imaginary frequencies",
)

__all__ = [
    "BOHR_TO_ANGSTROM",
    "BOND_TOLERANCE",
    "ATOM_RADII",
    "DiLocalCancelled",
    "parse_route_section",
    "parse_charge_multiplicity",
    "fchk_route_hint",
    "read_structure",
    "get_bonds_from_atoms",
    "connected_components",
    "validate_fragments",
    "format_ranges",
    "parse_ranges",
    "build_fragment_route",
    "prepare_di_jobs",
    "run_di_jobs",
]


class DiLocalCancelled(RuntimeError):
    """用户中止本机 DI 计算序列时抛出（面板据此静默收尾）。"""


# ── 基础工具 ─────────────────────────────────────────────────────────

def _read_text_lines(path):
    """按行读取文本文件；读不了时抛中文 ``ValueError``。"""
    path = str(path)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.readlines()
    except OSError as exc:
        raise ValueError("无法读取文件 %s：%s" % (os.path.basename(path), exc))


def _is_dashes(text):
    """判断一行是否全是连字符（Gaussian 的分隔横幅）。"""
    return len(text) >= 3 and set(text) <= {"-"}


def _symbol_and_number(token):
    """把 ``"C"`` 或 ``"6"`` 这样的原子标记转成 ``(符号, 原子序数)``。"""
    token = str(token).strip()
    try:
        number = int(token)
    except ValueError:
        symbol = token.capitalize()
        return symbol, _SYMBOL_TO_NUMBER.get(symbol, 0)
    return ELEMENT_SYMBOLS.get(number, "E%d" % number), number


# ── Gaussian log / fchk 元信息 ───────────────────────────────────────

def parse_route_section(log_path):
    """从 Gaussian .log 中提取 route 段（**不含**开头的 ``#``）。

    route 横幅形如::

         --------------------------------------------------------------
         #p opt=(ts,calcfc,noeigentest) freq m06l/def2svp int=ultrafine
         --------------------------------------------------------------

    长 route 在日志里可能折成多行（续行不以 ``#`` 开头），因此从 ``#``
    行开始一直收集到"全连字符行"或空行为止，多行之间用空格拼接。
    找不到 route 时返回空串。
    """
    lines = _read_text_lines(log_path)
    start = -1
    for index, raw in enumerate(lines):
        if raw.strip().startswith("#"):
            start = index
            break
    if start < 0:
        return ""

    parts = []
    for raw in lines[start:]:
        text = raw.strip()
        if not text or _is_dashes(text):
            break
        parts.append(text)
    route = " ".join(parts).strip()
    if route.startswith("#"):
        route = route[1:].strip()
    return route


#: " Charge =  0 Multiplicity = 1"（也兼容负电荷/多位数）
_CHARGE_MULT_RE = re.compile(
    r"Charge\s*=\s*([+-]?\d+)\s+Multiplicity\s*=\s*([+-]?\d+)")


def parse_charge_multiplicity(log_path):
    """提取 log 中最后一个 ``Charge = ... Multiplicity = ...``；无则 ``None``。"""
    lines = _read_text_lines(log_path)
    found = None
    for raw in lines:
        match = _CHARGE_MULT_RE.search(raw)
        if match:
            found = (int(match.group(1)), int(match.group(2)))
    return found


def fchk_route_hint(fchk_path):
    """从 fchk 第 2 行提取 ``方法/基组`` 提示串，例如 ``"RM06L/def2SVP"``。

    Gaussian 的固定列布局为：任务类型 ``[0:10]``、方法 ``[10:40]``、
    基组 ``[40:70]``。但实测（G16 rev A.03 的 formchk 输出）方法字段实际
    宽 60 列、基组从第 71 列开始，所以 ``[40:70]`` 为空时回退到
    ``[10:70]`` / ``[70:]``。方法保留 R/U 前缀原样（它们是合法 route
    关键字）。解析失败返回空串，不抛异常。
    """
    try:
        with open(str(fchk_path), "r", encoding="utf-8", errors="replace") as fh:
            fh.readline()               # 第 1 行：标题
            line = fh.readline()        # 第 2 行：任务类型/方法/基组
    except OSError:
        return ""
    line = line.rstrip("\r\n")
    if not line.strip():
        return ""

    method = line[10:40].strip()
    basis = line[40:70].strip()
    if not basis:
        # formchk 实测布局：方法 60 列、基组 20 列
        method = line[10:70].strip() or method
        basis = line[70:].strip()
    if not method or not basis:
        return ""
    return "%s/%s" % (method, basis)


# ── 结构解析（fchk / log / xyz / gjf，返回统一 atom 元组） ─────────────

def _fchk_field_header(lines, label):
    """找 fchk 字段头 ``<label>  <类型>  N= <个数>``，返回 ``(行号, 个数)``。"""
    pattern = re.compile(
        r"^\s*" + re.escape(label) + r"\s+[A-Za-z]\s+N=\s*(\d+)")
    for index, raw in enumerate(lines):
        match = pattern.match(raw)
        if match:
            return index, int(match.group(1))
    return -1, 0


def _fchk_collect_numbers(lines, header, count, caster):
    """从字段头之后逐行收集数值，凑满 ``count`` 个为止。"""
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


def _read_fchk_structure(path):
    """解析 .fchk/.fch：Atomic numbers + Current cartesian coordinates（Bohr）。"""
    lines = _read_text_lines(path)
    header, count = _fchk_field_header(lines, "Atomic numbers")
    numbers = (_fchk_collect_numbers(lines, header, count, int)
               if header >= 0 else [])
    if not numbers:
        # 少数文件只给 Nuclear charges（浮点），退而求其次
        header, count = _fchk_field_header(lines, "Nuclear charges")
        numbers = ([int(round(value)) for value in
                    _fchk_collect_numbers(lines, header, count, float)]
                   if header >= 0 else [])
    header, count = _fchk_field_header(lines, "Current cartesian coordinates")
    coord_values = (_fchk_collect_numbers(lines, header, count, float)
                    if header >= 0 else [])
    if not numbers or len(coord_values) < len(numbers) * 3:
        return []

    atoms = []
    for index, number in enumerate(numbers):
        symbol = ELEMENT_SYMBOLS.get(number, "E%d" % number)
        xyz = tuple(coord_values[index * 3 + axis] * BOHR_TO_ANGSTROM
                    for axis in range(3))
        atoms.append((index + 1, symbol, number, xyz))
    return atoms


def _parse_orientation_block(lines, start):
    """解析 ``start`` 处的 orientation 表；不完整/非法时返回空列表。"""
    header = -1
    for index in range(start + 1, min(start + 16, len(lines))):
        text = lines[index].strip()
        if "Center" in text and "Atomic" in text and "Coordinates" in text:
            header = index
            break
    if header < 0:
        return []

    atoms = []
    in_rows = False
    for raw in lines[header + 1:]:
        text = raw.strip()
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
        if len(parts) < 6 or not parts[0].isdigit() or not parts[1].isdigit():
            break
        try:
            center = int(parts[0])
            number = int(parts[1])
            xyz = (float(parts[3]), float(parts[4]), float(parts[5]))
        except (ValueError, IndexError):
            break
        atoms.append((center, ELEMENT_SYMBOLS.get(number, "E%d" % number),
                      number, xyz))
    return atoms


def _read_log_structure(path):
    """解析 .log/.out：取文件中最后一处完整的 orientation 表（坐标已是 Å）。"""
    lines = _read_text_lines(path)
    last = []
    for index, raw in enumerate(lines):
        if raw.strip() in _ORIENTATION_HEADERS:
            atoms = _parse_orientation_block(lines, index)
            if atoms:
                last = atoms
    return last


def _read_xyz_structure(path):
    """解析 .xyz（第 2 行注释，其后 ``符号 x y z``）。"""
    lines = _read_text_lines(path)
    if len(lines) < 2:
        return []
    try:
        expected = int(lines[0].split()[0])
    except (IndexError, ValueError):
        return []
    atoms = []
    for raw in lines[2:]:
        parts = raw.split()
        if len(parts) < 4:
            break
        try:
            xyz = (float(parts[1]), float(parts[2]), float(parts[3]))
        except ValueError:
            break
        symbol, number = _symbol_and_number(parts[0])
        atoms.append((len(atoms) + 1, symbol, number, xyz))
        if len(atoms) >= expected:
            break
    return atoms


def _read_gjf_structure(path):
    """解析 .gjf/.com 的直角坐标段（只取第一段，即第一个 ``电荷 多重度`` 行）。"""
    lines = _read_text_lines(path)
    start = -1
    for index, raw in enumerate(lines):
        parts = raw.split()
        if (len(parts) >= 2
                and all(part.lstrip("+-").isdigit() for part in parts[:2])):
            start = index
            break
    if start < 0:
        return []
    atoms = []
    for raw in lines[start + 1:]:
        text = raw.strip()
        if not text or text.startswith("--"):
            break
        parts = text.split()
        if len(parts) < 4:
            break
        try:
            xyz = (float(parts[1]), float(parts[2]), float(parts[3]))
        except ValueError:
            break
        symbol, number = _symbol_and_number(parts[0])
        atoms.append((len(atoms) + 1, symbol, number, xyz))
    return atoms


def read_structure(path):
    """读取结构文件，返回 ``[(1-based 序号, 符号, 原子序数, (x, y, z) Å), ...]``。

    支持 ``.fchk``/``.fch``（Bohr → Å）、``.log``/``.out``（最后一个
    orientation 表）、``.xyz``、``.gjf``/``.com``；未知扩展名按上述顺序
    逐个尝试。找不到结构时抛中文 ``ValueError``。
    """
    path = str(path)
    if not os.path.isfile(path):
        raise ValueError("找不到结构文件：%s" % os.path.basename(path))
    extension = os.path.splitext(path)[1].lower()

    if extension in (".fchk", ".fch"):
        atoms = _read_fchk_structure(path)
    elif extension in (".log", ".out"):
        atoms = _read_log_structure(path)
    elif extension == ".xyz":
        atoms = _read_xyz_structure(path)
    elif extension in (".gjf", ".com"):
        atoms = _read_gjf_structure(path)
    else:
        atoms = (_read_fchk_structure(path) or _read_log_structure(path)
                 or _read_xyz_structure(path) or _read_gjf_structure(path))

    if not atoms:
        raise ValueError("无法从文件 %s 解析出原子结构（未找到坐标块）"
                         % os.path.basename(path))
    return atoms


# ── 碎片划分 ─────────────────────────────────────────────────────────

def get_bonds_from_atoms(atoms):
    """按共价半径判键：``d < r1 + r2 + 0.45 Å``，返回 1-based ``(i, j)`` 列表。"""
    bonds = []
    for i in range(len(atoms)):
        idx1, symbol1, _number1, (x1, y1, z1) = atoms[i]
        radius1 = ATOM_RADII.get(symbol1, 1.5)
        for j in range(i + 1, len(atoms)):
            idx2, symbol2, _number2, (x2, y2, z2) = atoms[j]
            radius2 = ATOM_RADII.get(symbol2, 1.5)
            distance = math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2
                                 + (z1 - z2) ** 2)
            if distance < radius1 + radius2 + BOND_TOLERANCE:
                first, second = int(idx1), int(idx2)
                bonds.append((min(first, second), max(first, second)))
    return bonds


def connected_components(natoms, bonds):
    """按键连关系求连通分量，1-based，按每块最小原子序号排序。"""
    total = int(natoms)
    if total <= 0:
        return []

    parent = list(range(total + 1))

    def find(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for pair in bonds:
        try:
            left, right = int(pair[0]), int(pair[1])
        except (TypeError, ValueError, IndexError):
            continue
        if not (1 <= left <= total and 1 <= right <= total) or left == right:
            continue
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[max(root_left, root_right)] = min(root_left, root_right)

    groups = {}
    for node in range(1, total + 1):
        groups.setdefault(find(node), set()).add(node)
    return sorted(groups.values(), key=min)


def validate_fragments(natoms, frag1, frag2):
    """校验两个碎片：非空、索引合法、互不重叠、并集覆盖全部原子。"""
    total = int(natoms)
    try:
        set1 = {int(value) for value in frag1}
        set2 = {int(value) for value in frag2}
    except (TypeError, ValueError):
        raise ValueError("碎片原子序号必须是整数")
    if not set1 or not set2:
        raise ValueError("两个碎片都必须至少包含一个原子")

    for fragment, name in ((set1, "碎片 1"), (set2, "碎片 2")):
        bad = sorted(value for value in fragment
                     if value < 1 or value > total)
        if bad:
            raise ValueError("%s 的原子序号超出范围：%d（共 %d 个原子）"
                             % (name, bad[0], total))

    overlap = set1 & set2
    if overlap:
        raise ValueError("原子 %d 同时被分配到了两个碎片" % min(overlap))

    missing = sorted(set(range(1, total + 1)) - set1 - set2)
    if missing:
        raise ValueError("原子 %d 没有分配到任何碎片" % missing[0])
    return None


def format_ranges(indices):
    """把原子序号集合格式化成 ``"1-3,5,8-10"``（连续段用 ``a-b`` 表示）。"""
    values = sorted({int(value) for value in indices})
    if not values:
        return ""
    parts = []
    start = previous = values[0]
    for value in values[1:]:
        if value == previous + 1:
            previous = value
            continue
        parts.append(str(start) if start == previous
                     else "%d-%d" % (start, previous))
        start = previous = value
    parts.append(str(start) if start == previous
                 else "%d-%d" % (start, previous))
    return ",".join(parts)


#: 范围串的分隔符：英文/中文逗号、中英文分号、空白
_RANGE_SEPARATORS = re.compile(r"[,，;；\s]+")


def parse_ranges(text):
    """把 ``"1-3,5,8-10"`` 解析成 ``{1,2,3,5,8,9,10}``。

    兼容中文逗号/分号与任意空白；空串返回空集合；无法解析时抛 ``ValueError``。
    """
    result = set()
    if text is None:
        return result
    text = str(text).strip()
    if not text:
        return result

    # "1 - 3" 先压成 "1-3"，避免把 '-' 当成独立的分隔符
    normalized = re.sub(r"\s*-\s*", "-", text)
    for token in _RANGE_SEPARATORS.split(normalized):
        if not token:
            continue
        if "-" in token:
            pieces = token.split("-")
            if len(pieces) != 2:
                raise ValueError("无法解析的原子范围：%s" % token)
            try:
                start, end = int(pieces[0]), int(pieces[1])
            except ValueError:
                raise ValueError("无法解析的原子范围：%s" % token)
            if start < 1 or end < start:
                raise ValueError("无法解析的原子范围：%s" % token)
            result.update(range(start, end + 1))
        else:
            try:
                value = int(token)
            except ValueError:
                raise ValueError("无法解析的原子序号：%s" % token)
            if value < 1:
                raise ValueError("原子序号必须从 1 开始：%s" % token)
            result.add(value)
    return result


# ── Gaussian 输入生成 ────────────────────────────────────────────────

def _route_keyword(token):
    """取 route 关键字的"基名"：``opt=(ts,...)`` → ``opt``。"""
    return re.split(r"[=(]", token.lower(), 1)[0]


def build_fragment_route(route, job, add_nosymm=True):
    """把 TS 的 route 改写成"碎片单点/优化"的完整 route 行。

    丢弃与当前任务冲突的关键字（``opt*``、``freq``、``geom*``、``guess*``、
    ``chk*``、``output*``、``restart``、``force``、``stable``、``sp``、
    ``allcheck``、``job`` 以及裸的 ``p``/``P``），保留方法/基组与
    ``scf``/``int``/``scrf``/``empiricaldispersion`` 等设置关键字；必要时
    补 ``nosymm``，最后追加 ``sp`` 或 ``opt``，返回以 ``#p `` 开头的整行。
    """
    kind = str(job or "").strip().lower()
    if kind not in ("sp", "opt"):
        raise ValueError("job 参数必须是 'sp' 或 'opt'，收到：%r" % (job,))

    tokens = str(route or "").replace("\n", " ").split()
    if tokens and tokens[0].startswith("#"):
        # 允许直接传 "#p ..." 形式的 route 行
        tokens[0] = tokens[0].lstrip("#")
        if not tokens[0]:
            tokens.pop(0)

    kept = []
    for token in tokens:
        base = _route_keyword(token)
        if base in _ROUTE_DROP_EXACT:
            continue
        if base.startswith(_ROUTE_DROP_PREFIX):
            continue
        kept.append(token)

    if not any("/" in token for token in kept):
        raise ValueError("route 中没有找到理论水平关键字（method/basis，"
                         "例如 m06l/def2svp）")

    if add_nosymm and not any(token.lower() == "nosymm" for token in kept):
        kept.append("nosymm")
    kept.append(kind)
    return "#p " + " ".join(kept)


def _write_di_gjf(path, chk_path, route, title, charge, multiplicity,
                  atoms, mem, nprocshared):
    """写一个 DI 用的 .gjf（纯 ASCII，坐标系/原子顺序原样保留）。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="ascii", errors="strict",
              newline="\n") as fh:
        fh.write("%%chk=%s\n" % os.path.basename(chk_path))
        fh.write("%%mem=%s\n" % mem)
        fh.write("%%nprocshared=%s\n" % nprocshared)
        fh.write(route + "\n\n")
        fh.write(title + "\n\n")
        fh.write("%d %d\n" % (int(charge), int(multiplicity)))
        for _idx, symbol, _number, (x, y, z) in atoms:
            fh.write(" %s  %14.8f %14.8f %14.8f\n" % (symbol, x, y, z))
        fh.write("\n")
    return path


def _ascii_text(text):
    """把可能含中文的标题压成 ASCII（Gaussian 输入文件按 ASCII 写出）。"""
    cleaned = re.sub(r"[^\x20-\x7e]+", "_", str(text)).strip(" _")
    return cleaned or "molstudio"


def _ordered_fragment(atoms, indices):
    """按原文件顺序取出碎片原子（坐标保持不变，不做任何平移/旋转）。"""
    wanted = {int(value) for value in indices}
    ordered = [atom for atom in atoms if int(atom[0]) in wanted]
    if len(ordered) != len(wanted):
        known = {int(atom[0]) for atom in atoms}
        missing = sorted(wanted - known)
        raise ValueError("原子 %d 不在结构中" % missing[0])
    return ordered


def prepare_di_jobs(atoms, frag1, frag2, out_dir, stem, ts_route,
                    frag_charges=((0, 1), (0, 1)), mem="8GB",
                    nprocshared=8, add_nosymm=True):
    """生成 4 个 Gaussian 输入并返回任务描述列表。

    运行顺序固定为 ``frag1_def``（sp）、``frag2_def``（sp）、
    ``frag1_opt``（opt）、``frag2_opt``（opt）。返回的每个 dict 含
    ``role/kind/gjf/log/chk/atoms/charge/multiplicity/route``，其中
    ``atoms`` 是按原文件顺序排列的碎片原子子集，坐标不做任何修改。
    """
    atoms = list(atoms)
    validate_fragments(len(atoms), frag1, frag2)

    try:
        charges = [(int(pair[0]), int(pair[1])) for pair in frag_charges]
    except (TypeError, ValueError, IndexError):
        raise ValueError("frag_charges 必须是 ((电荷, 多重度), (电荷, 多重度))")
    if len(charges) != 2:
        raise ValueError("frag_charges 必须正好两个（每个碎片一对 电荷/多重度）")

    ordered1 = _ordered_fragment(atoms, frag1)
    ordered2 = _ordered_fragment(atoms, frag2)
    # 先构造两条 route：route 非法时在写任何文件之前就报错
    route_sp = build_fragment_route(ts_route, "sp", add_nosymm=add_nosymm)
    route_opt = build_fragment_route(ts_route, "opt", add_nosymm=add_nosymm)

    safe_stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_",
                       str(stem)).strip(" .") or "molecule"
    out_dir = str(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    title_stem = _ascii_text(safe_stem)

    specs = (
        ("frag1_def", "sp", ordered1, charges[0], route_sp),
        ("frag2_def", "sp", ordered2, charges[1], route_sp),
        ("frag1_opt", "opt", ordered1, charges[0], route_opt),
        ("frag2_opt", "opt", ordered2, charges[1], route_opt),
    )
    jobs = []
    for role, kind, subset, (charge, multiplicity), route in specs:
        gjf = os.path.join(out_dir, "%s_%s.gjf" % (safe_stem, role))
        base = os.path.splitext(gjf)[0]
        log = base + ".log"
        chk = base + ".chk"
        _write_di_gjf(gjf, chk, route, "%s %s" % (title_stem, role),
                      charge, multiplicity, subset, mem, nprocshared)
        jobs.append({
            "role": role,
            "kind": kind,
            "gjf": gjf,
            "log": log,
            "chk": chk,
            "atoms": subset,
            "charge": charge,
            "multiplicity": multiplicity,
            "route": route,
        })
    return jobs


# ── 本机运行 ─────────────────────────────────────────────────────────

def _is_progress_line(line):
    """判断一行 Gaussian 日志是否值得转发到界面（只看里程碑）。"""
    flattened = " ".join(str(line).lower().split())
    if not flattened:
        return False
    return any(marker in flattened for marker in _PROGRESS_MARKERS)


def run_di_jobs(jobs, g16_exe, on_log=None, cancel=None):
    """依次在本机跑完 4 个 DI 任务。

    通过模块级的 :func:`molstudio.core.gaussian_run.run_gaussian` 执行（测试
    里可 monkeypatch ``di_local.run_gaussian``）。每个任务开始/结束时用
    ``on_log`` 发一条中文进度；Gaussian 原始日志只转发里程碑行（优化日志
    太长，不能整份喷到界面上）。用户取消抛 :class:`DiLocalCancelled`，
    任务失败抛 ``RuntimeError``。
    """
    if not g16_exe or not os.path.isfile(str(g16_exe)):
        raise RuntimeError("找不到 g16.exe，请先在路径设置中配置本机 Gaussian")

    emit = on_log or (lambda _message: None)
    total = len(jobs)
    for index, job in enumerate(jobs, 1):
        if cancel is not None and cancel():
            raise DiLocalCancelled("本机计算已停止")

        label = _ROLE_LABELS.get(job.get("role"), str(job.get("role", "")))
        emit("=== [%d/%d] %s：%s ===" %
             (index, total, label, os.path.basename(job["gjf"])))

        def _forward(line):
            if _is_progress_line(line):
                emit(str(line).rstrip())

        result = run_gaussian(job["gjf"], g16_exe, log_path=job["log"],
                              on_line=_forward, cancel=cancel)
        if result.cancelled:
            raise DiLocalCancelled("本机计算已停止")
        if not result.ok:
            raise RuntimeError("%s Gaussian 计算失败：%s\n日志：%s" %
                               (label, result.error, result.log_path))
        emit("[%d/%d] 完成：%s" %
             (index, total, os.path.basename(result.log_path or job["log"])))
    return {"jobs": jobs}
