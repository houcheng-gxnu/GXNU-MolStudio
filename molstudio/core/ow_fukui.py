# -*- coding: utf-8 -*-
"""Multiwfn 轨道权重福井函数 / 双描述符（OW-Fukui，主功能 22）——Qt-free 核心模块
================================================================================

本模块封装 Multiwfn 2026.x 的「主功能 22 → Conceptual DFT (CDFT) analysis」
里的**轨道权重（orbital-weighted, OW）福井函数 / 双描述符**功能，供 OW-Fukui
面板（PyQt UI）在后台线程里调用；除 ``multiwfn_exe`` / fchk 路径外不依赖任何
GUI 组件，可直接单测。

**本模块只有纯文本解析 + 子进程调用，import 时不加载 Qt。**

科学背景
--------
对闭壳层单行列式波函数，以化学势 μ=(ε_HOMO+ε_LUMO)/2 为中心、Δ 为宽度：

    w_i = exp(-((μ-ε_i)/Δ)^2) / Σ_j exp(-((μ-ε_j)/Δ)^2)

    f_w+ = Σ_{i≥LUMO} w_i |φ_i|²      （得电子 / 亲核进攻）
    f_w- = Σ_{i≤HOMO} w_i |φ_i|²      （失电子 / 亲电进攻）
    f_w0 = (f_w+ + f_w-)/2
    Δf_w = f_w+ - f_w-

四者全空间积分都为 1。Δ 默认 0.1 Hartree（JCC 2017 推荐），可调。它只适用于
**闭壳层单行列式**波函数，且输入必须含空轨道（.fch/.fchk/.mwfn）；用于（准）
简并前线轨道体系（C60、18 碳环等）预测反应位点才有意义，普通分子直接看普通
福井函数更直观。参考文章：http://sobereva.com/533 ；Multiwfn 手册 3.25.3 与
4.22.2 节。

对外 API
--------
``DELTA_DEFAULT`` / ``DELTA_MIN`` / ``DELTA_MAX`` / ``GRID_QUALITIES`` / ``FUNCTIONS``
    UI 下拉框 / 说明文字用的常量。``FUNCTIONS`` 的顺序即 UI 显示顺序，也是
    cube 导出顺序。
``DEFAULT_SETTINGS``
    默认分析设置；``delta`` 单位 Hartree，``grid_quality`` 为 1/2/3。
``build_sequence(settings)``
    拼出喂给 Multiwfn 的完整 stdin 序列（含主功能 22；只发送非默认项）。
``parse_ow_output(text)``
    纯文本解析 Multiwfn stdout：HOMO/LUMO/μ/Δ、f+/f- 轨道权重表、Hirshfeld
    简缩 OW f+/f-/f0/DD 表与 sum、网格信息、cube 导出计数。容忍进度条、重复
    打印的菜单、乱码与截断输出，绝不抛异常。
``run_ow_fukui(...)``
    完整流程：校验输入（**开壳层 / 无空轨道 / 不支持格式直接抛中文
    RuntimeError**）→ ASCII 临时工作目录 → 复制 sys.fchk → 跑 Multiwfn →
    解析 → 把 4 个 cube 复制成 ``<stem>_OW_f+.cub`` / ``_OW_f-.cub`` /
    ``_OW_f0.cub`` / ``_OW_DD.cub``，stdout 写 ``<stem>_OWFukui.log`` →
    清理临时目录。
``settings_summary(settings, lang="zh")``
    一行人类可读摘要（UI 状态栏 / 日志用）。
``suggest_iso(cube_path, fraction=0.05)``
    由 cube 数据反推适合做等值面的数值（默认 5% × max|data|，圆整到 1 位
    有效数字，如 0.0003 / 0.0008），供 UI 的「可视化」页当默认等值面。
    **注意 MO 页的 0.05 绝不能沿用**：OW 福井函数量级小两个数量级。
``export_condensed_csv(path, condensed, lang="zh")``
    把简缩值表导出为 CSV（UTF-8-sig，Excel 直接打开不乱码）。

Multiwfn 2026.4.10 交互要点（实测）
-----------------------------------
* 主菜单输入 ``22`` 进入 CDFT 菜单；菜单项见 ``build_sequence`` 注释。
* ``4`` 改 Δ（先提示 ``Input delta parameter, e.g. 0.015 (in Hartree)``，
  紧接输入数值，然后回到 CDFT 菜单）。
* ``5`` 打印 ε_HOMO / ε_LUMO / μ / Δ 与 f+、f- 各前 10 个轨道权重。
* ``6`` 打印 Hirshfeld 简缩 OW f+/f-/f0/DD 表 + 两个 sum。
* ``7`` 先问网格质量（子菜单 ``1`` 低 / ``2`` 中 / ``3`` 高），算完进入后处理
  菜单（``5``/``6``/``7``/``8`` 分别导出 f+/f-/f0/DD 为 cube，每次导出后
  打印 `` Exporting finished!`` 并重新显示后处理菜单）。
* **不要用后处理菜单的 1~4（图形预览）**：会弹 GUI 窗口，后台运行会卡死。
* CDFT 菜单里 ``q`` **不是**合法输入（Fortran list-directed I/O 会崩溃），
  只能 ``0`` 返回。完整退出序列固定为：后处理菜单 ``0`` → CDFT 菜单 ``0``
  → 主菜单 ``q``。
* 全部内容一次跑完的 stdin 序列（实测退出码 0、4 个 cube 全部生成）::

      "\\n22\\n5\\n6\\n7\\n<quality>\\n5\\n6\\n7\\n8\\n0\\n0\\nq\\n"

  非默认 Δ 时在 ``22`` 之后插 ``4\\n<delta>\\n``。

  **实测补充**：没发 ``7``（不需要导出 cube）时没有后处理菜单，结尾只能
  是 ``0\\nq\\n``；用 ``0\\n0\\nq\\n`` 会多按一次主菜单 ``0``（打开 GUI 轨道
  查看器）而卡死。``build_sequence`` 已按这个差异处理。
"""

from __future__ import annotations

import csv
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time


# ────────────────────────────── 常量 ──────────────────────────────

#: Δ（Hartree）默认值。JCC 2017 推荐 0.1，太大权重趋于均匀、太小退化为普通
#: 福井函数（只剩 HOMO/LUMO 两个轨道）。
DELTA_DEFAULT = 0.1

#: Δ 允许范围（Hartree）。UI 的 QDoubleSpinBox 也用这个范围。
DELTA_MIN, DELTA_MAX = 0.001, 2.0

#: 网格质量（Multiwfn 选项 7 之后的 ``1``/``2``/``3`` 子菜单）。
#: 低 ≈ 12.5 万格点、中 ≈ 51 万、高 ≈ 173 万。
GRID_QUALITIES = {
    1: {"zh": "低质量", "en": "Low"},
    2: {"zh": "中质量", "en": "Medium"},
    3: {"zh": "高质量", "en": "High"},
}

#: 四个 OW 函数。顺序即 UI 显示顺序，也是 cube 导出顺序。
#: ``multi``  = 后处理菜单里的导出编号；
#: ``cub``    = Multiwfn 在临时目录里生成的文件名；
#: ``suffix`` = 复制回输出目录时 ``<stem>_<suffix>.cub`` 的中间段。
FUNCTIONS = {
    "fplus": {
        "key": "fplus", "multi": 5, "cub": "OW_f+.cub", "suffix": "OW_f+",
        "label_zh": "轨道权重 f+", "label_en": "OW f+",
    },
    "fminus": {
        "key": "fminus", "multi": 6, "cub": "OW_f-.cub", "suffix": "OW_f-",
        "label_zh": "轨道权重 f-", "label_en": "OW f-",
    },
    "f0": {
        "key": "f0", "multi": 7, "cub": "OW_f0.cub", "suffix": "OW_f0",
        "label_zh": "轨道权重 f0", "label_en": "OW f0",
    },
    "dd": {
        "key": "dd", "multi": 8, "cub": "OW_DD.cub", "suffix": "OW_DD",
        "label_zh": "轨道权重双描述符", "label_en": "OW dual descriptor",
    },
}

#: 默认分析设置（与合同一致；不要在这里放可变对象以外的隐藏状态）。
DEFAULT_SETTINGS = {
    "delta": 0.1,          # Hartree
    "grid_quality": 2,     # 1/2/3；仅在需要导出 cube 时使用
    "weights": True,       # 选项 5：打印轨道权重表
    "condensed": True,     # 选项 6：打印 Hirshfeld 简缩 OW 值
    "export": ["fplus", "fminus", "f0", "dd"],   # 需要导出的函数键；[] 表示不跑 7
}

#: run_ow_fukui 默认超时（秒）——中/高质量网格 + 4 个函数对中等体系也可能较慢
DEFAULT_TIMEOUT = 7200

#: 允许的输入格式：必须含空轨道才能做 OW 计算。
ALLOWED_INPUT_EXTS = (".fch", ".fchk", ".mwfn")

#: Multiwfn 内建默认 Δ（不改就发送设置）。用于「只发送非默认设置」判断。
_MW_DEFAULT_DELTA = 0.1


# ────────────────────────────── 设置处理 ──────────────────────────────

def _fmt_delta(value) -> str:
    """Δ → Multiwfn 选项 4 能接受的紧凑文本（0.25 → ``"0.25"``）。"""
    text = ("%.6f" % float(value)).rstrip("0").rstrip(".")
    return text or "0"


def _merge_settings(settings=None) -> dict:
    """默认设置 + 用户覆盖 → 规整后的新 dict（不修改入参 / DEFAULT_SETTINGS）。

    非法值抛 ``ValueError``（中文信息）；``run_ow_fukui`` 会把它转成
    ``RuntimeError``，面板直接显示给用户。
    """
    s = dict(DEFAULT_SETTINGS)
    s["export"] = list(DEFAULT_SETTINGS["export"])
    if settings:
        if not isinstance(settings, dict):
            raise ValueError("settings 必须是 dict")
        s.update(settings)

    # Δ：必须是有限数字且在允许范围内
    try:
        delta = float(s.get("delta"))
    except (TypeError, ValueError):
        raise ValueError("delta（Δ）必须是数字，收到：%r" % (s.get("delta"),))
    if not math.isfinite(delta):
        raise ValueError("delta（Δ）必须是有限数字，收到：%r" % (s.get("delta"),))
    if not (DELTA_MIN - 1e-12 <= delta <= DELTA_MAX + 1e-12):
        raise ValueError("delta（Δ）超出允许范围 %g–%g a.u.，收到：%r"
                         % (DELTA_MIN, DELTA_MAX, s.get("delta")))
    s["delta"] = min(max(delta, DELTA_MIN), DELTA_MAX)

    # 网格质量：只允许 1/2/3（4~11、-10、100 等其它手段不支持）
    raw_q = s.get("grid_quality")
    try:
        q = int(raw_q)
    except (TypeError, ValueError):
        raise ValueError("grid_quality 必须是 1（低）/2（中）/3（高），收到：%r"
                         % (raw_q,))
    if q not in GRID_QUALITIES:
        raise ValueError("grid_quality 只能是 1（低）/2（中）/3（高），收到：%r"
                         % (raw_q,))
    s["grid_quality"] = q

    # 导出函数键：必须是 FUNCTIONS 里的键；按给定顺序去重
    export = s.get("export")
    if export is None:
        export = []
    elif isinstance(export, str):
        export = [export]
    elif not isinstance(export, (list, tuple, set)):
        raise ValueError("export 必须是函数键列表，收到：%r" % (export,))
    ordered = []
    for key in export:
        k = str(key).strip()
        if k not in FUNCTIONS:
            raise ValueError("未知的导出函数键：%r（可选：%s）"
                             % (key, ", ".join(FUNCTIONS)))
        if k not in ordered:
            ordered.append(k)
    s["export"] = ordered

    s["weights"] = bool(s.get("weights"))
    s["condensed"] = bool(s.get("condensed"))
    return s


# ────────────────────────────── stdin 序列 ──────────────────────────────

def build_sequence(settings=None) -> str:
    """拼出运行一次 Multiwfn 主功能 22（OW-Fukui）的完整 stdin 文本。

    顺序（与实测菜单一致）：:

        <空行> 22 [4 Δ] [5] [6] [7 <quality> [导出编号...]] 0 0 q

    * 开头空行用于吃掉没有 settings.ini 时的 ``Press ENTER button to
      continue``；
    * 只发送**非默认**项：Δ 与 0.1 不同才发 ``4``；``weights``/``condensed``
      为 False 时不发 ``5``/``6``；``export`` 为空时不发 ``7``；
    * 结尾的 ``0`` 数量取决于是否发过 ``7``：

      - 发过 ``7``（会进入 cube 后处理菜单）：``0\\n0\\nq\\n``，即
        后处理菜单 → CDFT 菜单 → 主菜单；
      - 没发 ``7``（没有后处理菜单）：``0\\nq\\n``，即 CDFT 菜单 → 主菜单。
        此时若多送一个 ``0`` 会被**主菜单**当成「0 Show molecular structure
        and view orbitals」打开 GUI 轨道查看器，后台运行会一直卡住（实测
        2026.4.10 会挂到超时），所以不能无条件发 ``0\\n0\\nq\\n``。

      CDFT 菜单里 ``q`` 不合法（forrtl 崩溃），最后退出主菜单只能用 ``q``。
    """
    s = _merge_settings(settings)
    parts = ["\n", "22\n"]

    if abs(s["delta"] - _MW_DEFAULT_DELTA) > 1e-9:
        parts.append("4\n%s\n" % _fmt_delta(s["delta"]))
    if s["weights"]:
        parts.append("5\n")
    if s["condensed"]:
        parts.append("6\n")
    if s["export"]:
        parts.append("7\n%d\n" % s["grid_quality"])
        for key in s["export"]:
            parts.append("%d\n" % FUNCTIONS[key]["multi"])
        # 有 7：后处理菜单 0 → CDFT 菜单 0 → 主菜单 q
        parts.extend(["0\n", "0\n", "q\n"])
    else:
        # 无 7：CDFT 菜单 0 → 主菜单 q（多一个 0 会打开轨道查看器卡死）
        parts.extend(["0\n", "q\n"])
    return "".join(parts)


# ────────────────────────────── stdout 解析正则 ──────────────────────────────

_NUM = r"(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"
_RE_HOMO = re.compile(r"HOMO\s+energy:\s*" + _NUM + r"\s*a\.u\.", re.I)
_RE_LUMO = re.compile(r"LUMO\s+energy:\s*" + _NUM + r"\s*a\.u\.", re.I)
_RE_MU = re.compile(r"Chemical\s+potential:\s*" + _NUM + r"\s*a\.u\.", re.I)
_RE_DELTA = re.compile(r"Delta\s+parameter:\s*" + _NUM + r"\s*a\.u\.", re.I)

#: "10 Highest weights in orbital-weighted f+" / "... f-" / "... f0" /
#: "... dual descriptor"
_RE_WEIGHT_HEAD = re.compile(
    r"Highest\s+weights\s+in\s+orbital-weighted\s+"
    r"(f\+|f-|f0|dual\s+descriptor)", re.I)
#: " Orbital    22 (LUMO  )   Weight:  48.68 %   E_diff:     3.925 eV"
_RE_WEIGHT_ROW = re.compile(
    r"Orbital\s+(\d+)\s*\(\s*([^)]*?)\s*\)\s+"
    r"Weight:\s*([\d.]+)\s*%\s+E_diff:\s*" + _NUM + r"\s*eV", re.I)
_RE_WEIGHT_TOTAL = re.compile(
    r"Total\s+weight\s+of\s+above\s+listed\s+orbitals:\s*([\d.]+)\s*%", re.I)

#: 表格 token → ``parse_ow_output["weights"]`` 的键（选项 5 目前只打印 f+/f-）
_WEIGHT_KEYS = {
    "f+": "fplus",
    "f-": "fminus",
    "f0": "f0",
    "dual descriptor": "dd",
}

#: Hirshfeld 简缩 OW 表头 / 数据行 / 两个 sum
_RE_COND_HEAD = re.compile(r"Atom\s+index\s+OW\s+f\+", re.I)
_RE_COND_ROW = re.compile(
    r"^\s*(\d+)\(\s*([A-Za-z]{1,3})\s*\)\s+"
    r"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+"
    r"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*$")
_RE_SUM_FPLUS = re.compile(
    r"Sum\s+of\s+orbital\s+weighted\s+f\+\s+" + _NUM, re.I)
_RE_SUM_FMINUS = re.compile(
    r"Sum\s+of\s+orbital\s+weighted\s+f-\s+" + _NUM, re.I)

#: 网格信息（选项 7 → 网格质量之后）
_RE_GRID_SPACING = re.compile(
    r"Grid\s+spacing\s+in\s+X,Y,Z\s+is\s+" + _NUM + r"\s+" + _NUM + r"\s+"
    + _NUM + r"\s+Bohr", re.I)
_RE_GRID_POINTS = re.compile(
    r"Number\s+of\s+points\s+in\s+X,Y,Z\s+is\s+(\d+)\s+(\d+)\s+(\d+)\s+"
    r"Total:\s+(\d+)", re.I)

#: 每次成功导出 cube 都会打印一行（导出本身不打印文件名，只能计数）
_RE_EXPORT_DONE = re.compile(r"Exporting\s+finished!", re.I)


# ────────────────────────────── 解析 ──────────────────────────────

def _empty_parsed() -> dict:
    """``parse_ow_output`` 的空结果骨架（保证键齐全）。"""
    return {
        "homo_energy": None,
        "lumo_energy": None,
        "chemical_potential": None,
        "delta": None,
        "weights": {"fplus": [], "fminus": []},
        "total_weight": {"fplus": None, "fminus": None},
        "condensed": [],
        "sums": {"fplus": None, "fminus": None},
        "grid": {"quality": None, "nx": 0, "ny": 0, "nz": 0,
                 "npoints": 0, "spacing_bohr": None},
        "exported": [],
        "warnings": [],
    }


def _first_float(regex, text):
    """取第一个匹配的浮点数；解析失败返回 None（绝不抛异常）。"""
    m = regex.search(text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except (TypeError, ValueError, IndexError):
        return None


def _infer_grid_quality(npoints):
    """由格点总数粗略反推网格质量（低/中/高约 12.5 万 / 51 万 / 173 万）。

    仅用于纯文本解析；``run_ow_fukui`` 会用用户设置值覆盖这个推断。
    体系特别大/特别小时 Multiwfn 也按这三个目标调整间距，所以仍然可用。
    """
    try:
        n = int(npoints)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    if n < 250000:
        return 1
    if n < 1000000:
        return 2
    return 3


def _parse_weights(text, out):
    """解析 f+/f- 两组「前 10 个轨道权重」表（含合计百分比）。"""
    heads = list(_RE_WEIGHT_HEAD.finditer(text))
    for i, m in enumerate(heads):
        token = " ".join((m.group(1) or "").lower().split())
        key = _WEIGHT_KEYS.get(token)
        if key not in ("fplus", "fminus"):
            continue                      # 选项 5 只打印 f+/f-，其它不处理
        if out["weights"][key]:
            continue                      # 同一张表重复打印时保留第一份
        seg_end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        seg = text[m.end():seg_end]

        # 有合计行时只解析合计行之前的部分，避免把后续重复段的行算进来
        tm = _RE_WEIGHT_TOTAL.search(seg)
        rows_text = seg[:tm.start()] if tm else seg
        rows = []
        for rm in _RE_WEIGHT_ROW.finditer(rows_text):
            try:
                rows.append({
                    "index": int(rm.group(1)),
                    "label": (rm.group(2) or "").strip(),
                    "weight": float(rm.group(3)),
                    "ediff_ev": float(rm.group(4)),
                })
            except (TypeError, ValueError):
                continue
        out["weights"][key] = rows
        if tm:
            try:
                out["total_weight"][key] = float(tm.group(1))
            except (TypeError, ValueError):
                out["total_weight"][key] = None
        if not rows:
            out["warnings"].append(
                "检测到 OW %s 权重表标题，但未解析到轨道行" % token)


def _parse_condensed(text, out):
    """解析 Hirshfeld 简缩 OW 表（原子号 + 元素 + 四个值），按原子号去重。"""
    rows = out["condensed"]
    seen = set()
    for head in _RE_COND_HEAD.finditer(text):
        found = 0
        for line in text[head.end():].splitlines():
            if not line.strip():
                if found:
                    break
                continue
            rm = _RE_COND_ROW.match(line)
            if rm:
                try:
                    idx = int(rm.group(1))
                    row = {
                        "index": idx,
                        "element": (rm.group(2) or "").strip(),
                        "fplus": float(rm.group(3)),
                        "fminus": float(rm.group(4)),
                        "f0": float(rm.group(5)),
                        "dd": float(rm.group(6)),
                    }
                except (TypeError, ValueError):
                    continue
                if idx not in seen:
                    seen.add(idx)
                    rows.append(row)
                found += 1
                continue
            if found:
                break                     # 表结束（Sum 行 / 下一段标题）
        if found:
            break                         # 只解析第一张简缩表

    out["sums"]["fplus"] = _first_float(_RE_SUM_FPLUS, text)
    out["sums"]["fminus"] = _first_float(_RE_SUM_FMINUS, text)


def _parse_grid(text, out):
    """解析选项 7 选完网格质量后的间距/格点数，并粗略推断质量档位。"""
    mg = _RE_GRID_POINTS.search(text)
    if mg:
        try:
            out["grid"]["nx"] = int(mg.group(1))
            out["grid"]["ny"] = int(mg.group(2))
            out["grid"]["nz"] = int(mg.group(3))
            out["grid"]["npoints"] = int(mg.group(4))
        except (TypeError, ValueError):
            pass
    ms = _RE_GRID_SPACING.search(text)
    if ms:
        try:
            out["grid"]["spacing_bohr"] = float(ms.group(1))
        except (TypeError, ValueError):
            out["grid"]["spacing_bohr"] = None
    out["grid"]["quality"] = _infer_grid_quality(out["grid"]["npoints"])


def _parse_exported(text, out):
    """由 ``Exporting finished!`` 行数推断导出的 cube 名单。

    Multiwfn 导出时**不打印文件名**，纯文本只能计数；由于后处理菜单的编号
    5→6→7→8 与 ``FUNCTIONS`` 的顺序一致，N 次导出就按前 N 个函数推断。
    ``run_ow_fukui`` 会用临时目录里实际存在的文件覆盖该字段（以文件为准）。
    """
    count = len(_RE_EXPORT_DONE.findall(text))
    out["exported"] = [FUNCTIONS[k]["cub"]
                       for k in FUNCTIONS][:max(0, min(count, len(FUNCTIONS)))]


def parse_ow_output(text: str) -> dict:
    """纯文本解析 Multiwfn 主功能 22 的 stdout，返回合同约定的字典。

    对进度条（``Progress: [####...] 53.0 % \\``）、重复打印的菜单、空行、
    非 ASCII 乱码、截断输出都保持容忍；解析不到的字段留 ``None``/空列表，
    并尽量在 ``warnings`` 里说明，绝不因奇怪输入抛异常。
    """
    out = _empty_parsed()
    if not text:
        out["warnings"].append(
            "输出为空，未检测到 Multiwfn 轨道权重福井函数结果")
        return out
    if not isinstance(text, str):
        try:
            text = str(text)
        except Exception:  # noqa: BLE001 - 极端情况下也不抛
            out["warnings"].append("输出内容无法作为文本解析")
            return out

    warnings = out["warnings"]

    # ── 能量三件套 + Δ ──────────────────────────────────────────
    out["homo_energy"] = _first_float(_RE_HOMO, text)
    out["lumo_energy"] = _first_float(_RE_LUMO, text)
    out["chemical_potential"] = _first_float(_RE_MU, text)
    out["delta"] = _first_float(_RE_DELTA, text)

    # ── 权重表 / 简缩表 / 网格 / 导出 ──────────────────────────
    _parse_weights(text, out)
    _parse_condensed(text, out)
    _parse_grid(text, out)
    _parse_exported(text, out)

    # ── 运行期错误与异常状态 ────────────────────────────────────
    low = text.lower()
    if "unrestricted single-determinant" in low:
        warnings.append("输出显示为开壳层（unrestricted）波函数；轨道权重福井"
                        "函数只适用于闭壳层单行列式，结果不可用")
    if "forrtl: severe" in low:
        warnings.append("Multiwfn 输出包含 Fortran 运行时错误（forrtl: severe），"
                        "结果可能不完整")
    if "forrtl: error" in low:
        warnings.append("Multiwfn 输出包含 Fortran 运行时错误（forrtl: error）")

    # 完全没有可解析内容时才提示，避免「只导 cube、不打印权重」的正常情况误报
    if not (out["weights"]["fplus"] or out["weights"]["fminus"]
            or out["condensed"] or out["exported"]
            or out["homo_energy"] is not None):
        warnings.append("输出中未检测到 OW 福井函数相关结果，"
                        "Multiwfn 可能未正确执行（请查看日志）")

    return out


# ────────────────────────────── 摘要 ──────────────────────────────

def settings_summary(settings: dict, lang: str = "zh") -> str:
    """一行人类可读的分析设置摘要（UI 状态栏 / 日志用）。"""
    s = _merge_settings(settings)
    zh = (lang or "zh").lower().startswith("zh")
    delta = _fmt_delta(s["delta"])
    if zh:
        parts = [
            "Δ = %s a.u." % delta,
            "格点%s" % GRID_QUALITIES[s["grid_quality"]]["zh"],
            "打印轨道权重" if s["weights"] else "不打印轨道权重",
            "Hirshfeld 简缩值" if s["condensed"] else "不算简缩值",
        ]
        if s["export"]:
            parts.append("导出 " + " / ".join(
                FUNCTIONS[k]["label_zh"] for k in s["export"]))
        else:
            parts.append("不导出 cube")
    else:
        parts = [
            "Δ = %s a.u." % delta,
            "%s grid" % GRID_QUALITIES[s["grid_quality"]]["en"],
            "orbital weights" if s["weights"] else "no orbital weights",
            "Hirshfeld condensed" if s["condensed"] else "no condensed values",
        ]
        if s["export"]:
            parts.append("export " + " / ".join(
                FUNCTIONS[k]["label_en"] for k in s["export"]))
        else:
            parts.append("no cube export")
    return " · ".join(parts)


# ────────────────────────────── 等值面建议值 ──────────────────────────────

def suggest_iso(cube_path, fraction: float = 0.05):
    """由 cube 数据给出适合的等值面数值（默认 5% × max|data|）。

    返回圆整到 **1 位有效数字** 的好读数值（如 0.0003、0.0008、0.008），
    读文件失败 / 数据全零时返回 ``None``。OW 福井函数的量级比 MO 小两个
    数量级，UI 默认等值面必须由这里推算，不能沿用 MO 的 0.05。

    cube 可能有上百万格点（4~7 MB 内存），读完立即释放 ``CubeData``，
    面板反复调用也不会堆积。
    """
    try:
        frac = float(fraction)
    except (TypeError, ValueError):
        frac = 0.05
    if not math.isfinite(frac) or frac <= 0:
        frac = 0.05

    cube = None
    try:
        from .marching_cubes import read_cube
        cube = read_cube(str(cube_path))
        data = getattr(cube, "data", None)
        if data is None or getattr(data, "size", 0) <= 0:
            return None
        import numpy as np
        peak = float(np.max(np.abs(data)))
    except Exception:  # noqa: BLE001 - 读失败一律返回 None（UI 显示默认值）
        return None
    finally:
        # 立刻断开对格点数组的引用，避免大 cube 常驻内存
        if cube is not None:
            try:
                cube.data = None
            except Exception:  # noqa: BLE001
                pass
            del cube

    if not math.isfinite(peak) or peak <= 0:
        return None
    try:
        value = float("%.0e" % (peak * frac))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


# ────────────────────────────── 简缩值 CSV ──────────────────────────────

def export_condensed_csv(path, condensed, lang: str = "zh") -> str:
    """把 Hirshfeld 简缩 OW 表写成 CSV（UTF-8-sig，Excel 打开不乱码）。

    Parameters
    ----------
    path : str
        输出 .csv 路径。
    condensed : list[dict]
        ``parse_ow_output`` 返回的简缩表（``index/element/fplus/fminus/f0/dd``）。
    lang : str
        ``"zh"`` 表头 ``原子,元素,OW f+,OW f-,OW f0,OW DD``；
        ``"en"`` 表头 ``Atom,Element,...``。

    Returns
    -------
    str
        实际写入的绝对路径。
    """
    zh = (lang or "zh").lower().startswith("zh")
    header = (["原子", "元素", "OW f+", "OW f-", "OW f0", "OW DD"] if zh
              else ["Atom", "Element", "OW f+", "OW f-", "OW f0", "OW DD"])

    def _fmt_num(value):
        try:
            v = float(value)
        except (TypeError, ValueError):
            return ""
        return "%.5f" % v if math.isfinite(v) else ""

    path = os.path.abspath(str(path))
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        for row in (condensed or []):
            if not isinstance(row, dict):
                continue
            writer.writerow([
                row.get("index", ""),
                row.get("element", "") or "",
                _fmt_num(row.get("fplus")),
                _fmt_num(row.get("fminus")),
                _fmt_num(row.get("f0")),
                _fmt_num(row.get("dd")),
            ])
    return path


# ────────────────────────────── 子进程 / 工作目录 ──────────────────────────────

def _is_ascii_path(path) -> bool:
    try:
        str(path).encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _safe_ascii_tmp_dir(prefix="molstudio_owf_", exe_dir=None):
    """创建 Multiwfn 能正常读写的纯 ASCII 临时工作目录。

    Multiwfn（Fortran）无法处理中文路径；系统临时目录在中文 Windows 上常含
    中文用户名，故回退到 Multiwfn 所在目录 / 盘符根目录。与
    ``multiwfn_lmo._safe_ascii_tmp_dir`` 同一思路（核心模块之间不互相 import
    私有 helper，保持各自可独立测试）。
    """
    def _mk(base=None):
        if base:
            return tempfile.mkdtemp(prefix=prefix, dir=base)
        return tempfile.mkdtemp(prefix=prefix)

    def _drop(path):
        """回退前清理已经建出来但不合用的目录（否则会残留）。"""
        try:
            shutil.rmtree(path, ignore_errors=True)
        except Exception:  # noqa: BLE001
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
        except Exception:  # noqa: BLE001
            pass
    try:
        cands.append(os.path.splitdrive(os.path.abspath(__file__))[0] + os.sep)
    except Exception:  # noqa: BLE001
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
    except Exception:  # noqa: BLE001 - 日志回调异常不能影响主流程
        pass


def _emit_stage(on_stage, pct, text):
    if on_stage is None:
        return
    try:
        on_stage(int(max(0, min(100, pct))), str(text))
    except Exception:  # noqa: BLE001
        pass


def _cancel_requested(cancel_check) -> bool:
    if cancel_check is None:
        return False
    try:
        return bool(cancel_check())
    except Exception:  # noqa: BLE001
        return False


def _decode(data) -> str:
    if data is None:
        return ""
    if isinstance(data, (bytes, bytearray)):
        return bytes(data).decode("utf-8", errors="replace")
    return str(data)


def _base_result(settings, work_dir="", seconds=0.0) -> dict:
    """构造返回值骨架（用于启动前取消等早退路径）。"""
    result = _empty_parsed()
    result.update({
        "ok": False,
        "error": "",
        "settings": settings,
        "raw": "",
        "log_path": "",
        "seconds": float(seconds),
        "work_dir": work_dir,
        "cubes": {key: "" for key in FUNCTIONS},
    })
    return result


# ────────────────────────────── 输入校验 ──────────────────────────────

def _validate_input_wavefunction(fchk_path) -> dict:
    """校验输入波函数：格式含空轨道、闭壳层单行列式。

    返回 ``parse_fchk_mo_info`` 的解析结果（解析失败时为空 dict，不阻断——
    例如 .mwfn 不是 fchk 格式，Multiwfn 自己会判断）。发现开壳层 / 无空轨道
    时抛中文 ``RuntimeError``。
    """
    ext = os.path.splitext(fchk_path)[1].lower()
    if ext not in ALLOWED_INPUT_EXTS:
        raise RuntimeError(
            "轨道权重福井函数需要含空轨道的波函数文件（.fch/.fchk/.mwfn），"
            "不支持该格式：%s" % os.path.basename(fchk_path))

    # 只有 fch/fchk 能用 fchk_parser 判开壳层；.mwfn 不是 fchk 格式，
    # 而且大文件整体读进来只为正则匹配不划算，交给 Multiwfn 自己判断
    # （运行后若 stdout 显示 unrestricted 会被 parse_ow_output 标成警告）。
    if ext not in (".fch", ".fchk"):
        return {}

    try:
        from .fchk_parser import parse_fchk_mo_info
        info = parse_fchk_mo_info(fchk_path)
    except Exception:  # noqa: BLE001 - 非 fchk / 解析失败交给 Multiwfn
        return {}

    if not isinstance(info, dict):
        return {}
    if info.get("is_open_shell"):
        raise RuntimeError(
            "轨道权重（OW）福井函数/双描述符只适用于闭壳层单行列式波函数，"
            "当前输入是开壳层（含 Beta 轨道）：%s" % fchk_path)

    try:
        n_basis = int(info.get("n_basis") or 0)
        n_alpha = int(info.get("n_alpha") or 0)
    except (TypeError, ValueError):
        n_basis = n_alpha = 0
    if n_basis and n_alpha and n_basis <= n_alpha:
        raise RuntimeError(
            "输入波函数没有空轨道（基函数 %d ≤ 占据轨道 %d），无法计算轨道"
            "权重福井函数；请提供含空轨道的 .fch/.fchk/.mwfn 文件：%s"
            % (n_basis, n_alpha, fchk_path))
    return info


# ────────────────────────────── 完整流程 ──────────────────────────────

def run_ow_fukui(fchk_path, multiwfn_exe, settings=None, out_dir=None,
                 on_log=None, on_stage=None, cancel_check=None,
                 proc_holder=None, timeout=DEFAULT_TIMEOUT) -> dict:
    """运行一次完整的 Multiwfn 轨道权重福井函数 / 双描述符流程并收集产物。

    Parameters
    ----------
    fchk_path : str
        输入波函数文件，必须是含空轨道的 .fch/.fchk/.mwfn，且为闭壳层单行列式。
    multiwfn_exe : str
        Multiwfn 可执行文件；为空时回退到 ``fchk_orbital.DEFAULT_MULTIWFN``。
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
        Multiwfn 超时秒数，超时会杀进程并抛中文 ``RuntimeError``。

    Returns
    -------
    dict
        ``parse_ow_output`` 的全部字段 + ``ok/error/settings/raw/log_path/
        seconds/work_dir/cubes``。``cubes`` 为 ``{"fplus": path, ...}``，
        没有生成/没有请求的函数对应空字符串。``grid["quality"]`` 已用用户
        设置值覆盖（文本推断只作参考）。
    """
    t0 = time.time()
    try:
        s = _merge_settings(settings)
    except ValueError as exc:
        raise RuntimeError("分析设置无效：%s" % exc) from exc

    # ── 输入校验（中文错误信息）──────────────────────────────────
    fchk_path = os.path.abspath(str(fchk_path)) if fchk_path else ""
    if not fchk_path or not os.path.isfile(fchk_path):
        raise RuntimeError("找不到波函数文件：%s"
                           % (fchk_path or "(空路径)"))

    if not multiwfn_exe:
        try:
            from .fchk_orbital import DEFAULT_MULTIWFN as multiwfn_exe
        except Exception:  # noqa: BLE001
            multiwfn_exe = ""
    multiwfn_exe = os.path.abspath(str(multiwfn_exe)) if multiwfn_exe else ""
    if not multiwfn_exe or not os.path.isfile(multiwfn_exe):
        raise RuntimeError("找不到 Multiwfn 可执行文件：%s"
                           % (multiwfn_exe or "(空路径)"))

    out_dir = (os.path.abspath(str(out_dir)) if out_dir
               else os.path.dirname(fchk_path))
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError as exc:
        raise RuntimeError("无法创建输出目录：%s（%s）" % (out_dir, exc)) from exc

    # 格式 / 开壳层 / 空轨道校验（不满足时在启动 Multiwfn 前就失败）
    _validate_input_wavefunction(fchk_path)

    stem = os.path.splitext(os.path.basename(fchk_path))[0]

    # ── 启动前取消 ──────────────────────────────────────────────
    if _cancel_requested(cancel_check):
        res = _base_result(s, seconds=time.time() - t0)
        res["error"] = "已取消"
        res["warnings"].append("已取消（未启动 Multiwfn）")
        _emit_log(on_log, "已取消：未启动 Multiwfn。")
        return res

    _emit_log(on_log, "开始轨道权重福井函数分析（Multiwfn 主功能 22，CDFT）")
    _emit_log(on_log, "输入文件：%s" % fchk_path)
    _emit_log(on_log, "分析设置：%s" % settings_summary(s))
    _emit_stage(on_stage, 5, "准备分析环境")

    # ── ASCII 工作目录 + sys.fchk ───────────────────────────────
    try:
        work_dir = _safe_ascii_tmp_dir("molstudio_owf_",
                                       exe_dir=os.path.dirname(multiwfn_exe))
    except OSError as exc:
        raise RuntimeError("无法创建 Multiwfn 临时工作目录：%s" % exc) from exc
    _emit_log(on_log, "Multiwfn 工作目录：%s" % work_dir)

    sequence = build_sequence(s)
    try:
        try:
            shutil.copy2(fchk_path, os.path.join(work_dir, "sys.fchk"))
        except OSError as exc:
            raise RuntimeError("复制波函数到临时工作目录失败：%s" % exc) from exc
        # 万一同名残留（理论上 mkdtemp 不会），先删掉以免把旧 cube 当新结果
        for spec in FUNCTIONS.values():
            try:
                os.remove(os.path.join(work_dir, spec["cub"]))
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
        # 用户可能在复制文件阶段就点了「停止」：进程一启动就终止，避免白跑
        if _cancel_requested(cancel_check):
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass
        try:
            try:
                raw_bytes, _ = proc.communicate(
                    input=sequence.encode("utf-8"), timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    proc.communicate(timeout=10)
                except Exception:  # noqa: BLE001
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
        parsed = parse_ow_output(raw)
        cancelled = _cancel_requested(cancel_check)
        if rc not in (0, None):
            parsed["warnings"].append(
                "Multiwfn 退出码非 0（%s），结果可能不完整，请查看日志" % rc)

        # ── 复制 cube / 写日志 ──────────────────────────────────
        _emit_stage(on_stage, 90, "复制分析产物")
        cubes = {key: "" for key in FUNCTIONS}
        produced = []                     # 临时目录里实际生成的 cube（Multiwfn 名）
        missing = []
        for key, spec in FUNCTIONS.items():
            src = os.path.join(work_dir, spec["cub"])
            try:
                exists = os.path.isfile(src) and os.path.getsize(src) > 0
            except OSError:
                exists = False
            if not exists:
                if key in s["export"]:
                    missing.append(spec["cub"])
                continue
            produced.append(spec["cub"])
            if cancelled or key not in s["export"]:
                continue                  # 取消 / 用户没请求：不复制到输出目录
            dst = os.path.join(out_dir, "%s_%s.cub" % (stem, spec["suffix"]))
            try:
                shutil.copy2(src, dst)
                cubes[key] = dst
            except OSError as exc:
                parsed["warnings"].append("复制 %s 失败：%s" % (spec["cub"], exc))

        # 纯文本的导出名单是「按次数推断」的，这里用实际生成的文件覆盖
        parsed["exported"] = produced
        if s["export"]:
            parsed["grid"]["quality"] = s["grid_quality"]
        if missing:
            parsed["warnings"].append(
                "未生成请求的 cube 文件：%s" % "、".join(missing))
        for warn in parsed["warnings"]:
            _emit_log(on_log, "警告：%s" % warn)

        log_path = os.path.join(out_dir, "%s_OWFukui.log" % stem)
        try:
            # newline=""：Multiwfn 的 stdout 已含 \r\n，避免文本模式再转一次
            with open(log_path, "w", encoding="utf-8", newline="") as fh:
                fh.write(raw)
        except OSError as exc:
            log_path = ""
            parsed["warnings"].append("写入日志失败：%s" % exc)

        # ── 成功判定 ────────────────────────────────────────────
        request_any = bool(s["export"]) or s["weights"] or s["condensed"]
        has_data = bool(parsed["weights"]["fplus"] or parsed["weights"]["fminus"]
                        or parsed["condensed"] or parsed["exported"]
                        or parsed["homo_energy"] is not None)
        # fchk 预检漏掉的开壳层（例如 .mwfn）由 Multiwfn 自己的输出兜底：
        # 这种结果在科学上是无意义的，不能当成功返回。
        open_shell_output = any("开壳层" in w for w in parsed["warnings"])
        if cancelled:
            error = "已取消"
        elif rc not in (0, None):
            error = "Multiwfn 退出码非 0（%s），结果可能不完整" % rc
        elif open_shell_output:
            error = ("Multiwfn 输出显示这是开壳层波函数；轨道权重福井函数"
                     "只适用于闭壳层单行列式，结果不可用")
        elif missing:
            error = "未生成请求的 cube 文件：%s" % "、".join(missing)
        elif request_any and not has_data:
            error = "Multiwfn 未产生可解析的分析结果，请查看日志"
        else:
            error = ""
        ok = not error

        if ok:
            _emit_log(on_log, "完成：f+ 权重 %d 条、简缩表 %d 个原子、cube %d 个"
                      % (len(parsed["weights"]["fplus"]),
                         len(parsed["condensed"]), len(produced)))
        else:
            _emit_log(on_log, "轨道权重福井函数分析失败/取消：%s" % error)
        for p in cubes.values():
            if p:
                _emit_log(on_log, "已生成 cube：%s" % p)
        if log_path:
            _emit_log(on_log, "完整 Multiwfn 输出：%s" % log_path)
        _emit_stage(on_stage, 100, "完成" if ok else "失败/取消")

        result = dict(parsed)
        result.update({
            "ok": ok,
            "error": error,
            "settings": s,
            "raw": raw,
            "log_path": log_path,
            "seconds": time.time() - t0,
            "work_dir": work_dir,
            "cubes": cubes,
        })
        return result
    finally:
        # 保证任何异常（超时/取消/复制失败）都不会残留临时目录或 Popen 引用
        if isinstance(proc_holder, dict):
            proc_holder.pop("proc", None)
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass


__all__ = [
    "DELTA_DEFAULT",
    "DELTA_MIN",
    "DELTA_MAX",
    "GRID_QUALITIES",
    "FUNCTIONS",
    "DEFAULT_SETTINGS",
    "DEFAULT_TIMEOUT",
    "ALLOWED_INPUT_EXTS",
    "build_sequence",
    "parse_ow_output",
    "run_ow_fukui",
    "settings_summary",
    "suggest_iso",
    "export_condensed_csv",
]
