# -*- coding: utf-8 -*-
"""Hirshfeld 原子自旋布居分析（Multiwfn 主功能 15 → 1 → 5）。

自旋密度是三维实空间函数 ``rho_alpha(r) - rho_beta(r)``；本模块计算的是它
在 Hirshfeld 原子空间中的积分，也就是通常所说的原子自旋布居（单位：
α−β 电子数）。结果保留正负号，同时给出绝对值与占比，便于处理反铁磁
耦合、双自由基等既有 α 富集又有 β 富集区域的体系。

模块不依赖 Qt，供主窗口后台线程和单元测试直接调用。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time

from .multiwfn_lmo import (
    _cancel_requested,
    _decode,
    _emit_log,
    _emit_stage,
    _safe_ascii_tmp_dir,
)


DEFAULT_TIMEOUT = 1200
METHOD_NAME = "Hirshfeld*"


def build_spin_population_sequence():
    """返回 Multiwfn 固定 stdin 序列。

    主功能 15 → ``-1`` 选择原子空间划分 → ``3`` 选择内置原子密度的
    Hirshfeld* 方法 → ``1`` 在原子空间积分 → ``5`` 电子自旋密度。
    完成后依次返回主菜单并正常退出。
    """
    return "\n15\n-1\n3\n1\n5\n0\nq\n"


_FLOAT = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?"
_RE_ELECTRONS = re.compile(
    r"Total/Alpha/Beta electrons:\s+(%s)\s+(%s)\s+(%s)" % (
        _FLOAT, _FLOAT, _FLOAT), re.I)
_RE_TABLE_HEADER = re.compile(
    r"Atomic\s+space\s+Value\s+%\s+of\s+sum\s+%\s+of\s+sum\s+abs",
    re.I)
_RE_ROW = re.compile(
    r"^\s*(\d+)\s*\(\s*([A-Za-z]{1,3})\s*\)\s+"
    r"(%s)\s+(%s)\s+(%s)\s*$" % (_FLOAT, _FLOAT, _FLOAT),
    re.MULTILINE)
_RE_SUM = re.compile(
    r"Summing up above values\s*:\s*(%s)" % _FLOAT, re.I)
_RE_SUM_ABS = re.compile(
    r"Summing up absolute value of above values\s*:\s*(%s)" % _FLOAT,
    re.I)


def _as_float(text):
    try:
        return float(str(text).replace("D", "E").replace("d", "e"))
    except (TypeError, ValueError):
        return None


def parse_spin_population_output(text):
    """解析 Multiwfn 原子自旋布居表，任何异常输入都不抛异常。"""
    result = {
        "ok": False,
        "atoms": [],
        "sum": None,
        "sum_abs": None,
        "expected_spin_population": None,
        "alpha_electrons": None,
        "beta_electrons": None,
        "integration_error": None,
        "method": METHOD_NAME,
        "warnings": [],
    }
    if not text:
        result["warnings"].append("输出为空，未检测到原子自旋布居")
        return result
    if not isinstance(text, str):
        try:
            text = str(text)
        except Exception:
            result["warnings"].append("输出内容无法作为文本解析")
            return result

    electrons = _RE_ELECTRONS.search(text)
    if electrons:
        alpha = _as_float(electrons.group(2))
        beta = _as_float(electrons.group(3))
        result["alpha_electrons"] = alpha
        result["beta_electrons"] = beta
        if alpha is not None and beta is not None:
            result["expected_spin_population"] = alpha - beta

    headers = list(_RE_TABLE_HEADER.finditer(text))
    if not headers:
        result["warnings"].append(
            "未检测到 Atomic space 自旋布居表，Multiwfn 分析可能失败")
        return result

    # 取最后一处结果表（日志中若重复打印菜单或中间步骤，不会被前文误导）。
    start = headers[-1].end()
    tail = text[start:]
    sum_match = _RE_SUM.search(tail)
    table_text = tail[:sum_match.start()] if sum_match else tail
    atoms = []
    for match in _RE_ROW.finditer(table_text):
        value = _as_float(match.group(3))
        percent_sum = _as_float(match.group(4))
        percent_abs = _as_float(match.group(5))
        if value is None:
            continue
        atoms.append({
            "index": int(match.group(1)),
            "element": match.group(2),
            "value": value,
            "abs_value": abs(value),
            "percent_sum": percent_sum,
            "percent_abs": percent_abs,
        })
    result["atoms"] = sorted(atoms, key=lambda atom: atom["index"])
    if not result["atoms"]:
        result["warnings"].append("未解析到任何原子自旋布居行")
        return result

    sum_match = _RE_SUM.search(tail)
    sum_abs_match = _RE_SUM_ABS.search(tail)
    if sum_match:
        result["sum"] = _as_float(sum_match.group(1))
    if sum_abs_match:
        result["sum_abs"] = _as_float(sum_abs_match.group(1))
    if result["sum"] is None:
        result["sum"] = sum(atom["value"] for atom in result["atoms"])
    if result["sum_abs"] is None:
        result["sum_abs"] = sum(atom["abs_value"]
                                for atom in result["atoms"])

    expected = result["expected_spin_population"]
    if expected is not None and result["sum"] is not None:
        result["integration_error"] = result["sum"] - expected
        if abs(result["integration_error"]) > 0.02:
            result["warnings"].append(
                "原子自旋布居总和 %.6f 与 α−β 电子数 %.6f 相差 %.6f，"
                "请检查波函数、积分格点或 Multiwfn 日志"
                % (result["sum"], expected, result["integration_error"]))

    low = text.lower()
    if "forrtl: severe" in low or "forrtl: error" in low:
        result["warnings"].append(
            "Multiwfn 输出包含 Fortran 运行时错误，结果可能不完整")
    result["ok"] = True
    return result


def run_atomic_spin_population(fchk_path, multiwfn_exe, out_dir=None,
                               on_log=None, on_stage=None, cancel_check=None,
                               proc_holder=None, timeout=DEFAULT_TIMEOUT):
    """运行 Hirshfeld* 原子空间自旋密度积分并保存完整日志。"""
    t0 = time.time()
    fchk_path = os.path.abspath(str(fchk_path)) if fchk_path else ""
    if not fchk_path or not os.path.isfile(fchk_path):
        raise RuntimeError("找不到 fchk 文件：%s"
                           % (fchk_path or "(空路径)"))
    if not multiwfn_exe:
        try:
            from .fchk_orbital import DEFAULT_MULTIWFN as multiwfn_exe
        except Exception:
            multiwfn_exe = ""
    multiwfn_exe = os.path.abspath(str(multiwfn_exe)) if multiwfn_exe else ""
    if not multiwfn_exe or not os.path.isfile(multiwfn_exe):
        raise RuntimeError("找不到 Multiwfn 可执行文件：%s"
                           % (multiwfn_exe or "(空路径)"))

    out_dir = (os.path.abspath(str(out_dir)) if out_dir
               else os.path.dirname(fchk_path))
    os.makedirs(out_dir, exist_ok=True)

    if _cancel_requested(cancel_check):
        return {
            "ok": False, "error": "已取消", "atoms": [],
            "seconds": time.time() - t0, "warnings": ["已取消（未启动 Multiwfn）"],
        }

    _emit_log(on_log, "开始原子自旋布居分析（Hirshfeld* 原子空间积分）")
    _emit_log(on_log, "输入波函数：%s" % fchk_path)
    _emit_stage(on_stage, 8, "准备原子自旋布居分析")

    temp_dir = ""
    try:
        temp_dir = _safe_ascii_tmp_dir(
            "molstudio_spin_pop_", exe_dir=os.path.dirname(multiwfn_exe))
        shutil.copy2(fchk_path, os.path.join(temp_dir, "sys.fchk"))
        creationflags = 0
        if sys.platform == "win32":
            creationflags = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        _emit_stage(on_stage, 18, "启动 Multiwfn")
        started = time.time()
        proc = subprocess.Popen(
            [multiwfn_exe, "sys.fchk"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, cwd=temp_dir,
            creationflags=creationflags)
        if isinstance(proc_holder, dict):
            proc_holder["proc"] = proc
        if _cancel_requested(cancel_check):
            try:
                proc.terminate()
            except Exception:
                pass
        try:
            try:
                raw_bytes, _ = proc.communicate(
                    input=build_spin_population_sequence().encode("utf-8"),
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
                raise RuntimeError(
                    "原子自旋布居分析超时（%s 秒），已终止进程"
                    % timeout) from None
        finally:
            if isinstance(proc_holder, dict):
                proc_holder.pop("proc", None)

        raw = _decode(raw_bytes)
        rc = proc.returncode
        _emit_stage(on_stage, 82, "解析原子自旋布居")
        _emit_log(on_log, "Multiwfn 运行结束，用时 %.1f s，退出码 %s"
                  % (time.time() - started, rc))
        parsed = parse_spin_population_output(raw)
        if rc not in (0, None):
            parsed["warnings"].append(
                "Multiwfn 退出码非 0（%s），结果可能不完整" % rc)

        stem = os.path.splitext(os.path.basename(fchk_path))[0]
        log_path = os.path.join(out_dir, "%s_spin_population.log" % stem)
        try:
            with open(log_path, "w", encoding="utf-8", newline="") as handle:
                handle.write(raw)
        except OSError as exc:
            log_path = ""
            parsed["warnings"].append("写入自旋布居日志失败：%s" % exc)

        cancelled = _cancel_requested(cancel_check)
        ok = bool(parsed.get("atoms")) and not cancelled
        error = ""
        if cancelled:
            error = "已取消"
        elif not parsed.get("atoms"):
            error = "Multiwfn 未返回原子自旋布居，请检查日志"
        result = dict(parsed)
        result.update({
            "ok": ok,
            "error": error,
            "source_path": fchk_path,
            "raw": raw,
            "log_path": log_path,
            "seconds": time.time() - t0,
        })
        _emit_stage(on_stage, 100, "完成" if ok else "失败/取消")
        if ok:
            total = result.get("sum")
            _emit_log(on_log, "原子自旋布居完成：%d 个原子，总和 %s"
                      % (len(result["atoms"]),
                         ("%.6f" % total) if total is not None else "未给出"))
        else:
            _emit_log(on_log, "原子自旋布居失败/取消：%s" % error)
        for warning in result.get("warnings") or []:
            _emit_log(on_log, "警告：%s" % warning)
        return result
    finally:
        if isinstance(proc_holder, dict):
            proc_holder.pop("proc", None)
        if temp_dir:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass


__all__ = [
    "DEFAULT_TIMEOUT",
    "METHOD_NAME",
    "build_spin_population_sequence",
    "parse_spin_population_output",
    "run_atomic_spin_population",
]
