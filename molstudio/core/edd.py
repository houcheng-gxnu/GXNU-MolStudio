# -*- coding: utf-8 -*-
"""Electron-density difference (EDD) workflow.

The implementation follows http://sobereva.com/113:

* fragment/structure calculations keep the exact Cartesian coordinates of the
  parent structure and always use ``nosymm``;
* the parent wavefunction is the first operand;
* every reference wavefunction is subtracted through Multiwfn's custom grid
  operation and the resulting electron-density grid is exported as a cube.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field

from molstudio.core.gaussian_run import (
    chk_to_fchk,
    find_chk_file,
    find_formchk,
    run_gaussian,
)
from molstudio.core.spectra import _ascii_existing_path, _run_multiwfn


class EDDCancelled(RuntimeError):
    """Raised when an EDD Gaussian or Multiwfn stage is cancelled."""


class EDDWorkflowError(RuntimeError):
    """A user-facing EDD workflow failure."""


@dataclass(frozen=True)
class EDDFragment:
    name: str
    atoms: tuple[int, ...]
    charge: int = 0
    multiplicity: int = 1


@dataclass
class EDDResult:
    complex_fch: str
    references: list[str]
    cube_path: str
    log_path: str
    grid_quality: int
    output: str
    archive_dir: str
    counts: dict = field(default_factory=dict)
    stats: dict = field(default_factory=dict)


def parse_atom_indices(text):
    """Parse ``1-3,7,10-12`` into a sorted tuple of one-based indices."""
    value = str(text or "").strip().replace("，", ",")
    if not value:
        return ()
    if not re.fullmatch(r"\d+(?:-\d+)?(?:\s*,\s*\d+(?:-\d+)?)*", value):
        raise ValueError("原子序号格式无效；请使用 1-3,7,10 这样的写法")
    result = set()
    for token in re.split(r"\s*,\s*", value):
        parts = token.split("-")
        start = int(parts[0])
        end = int(parts[-1])
        if start <= 0 or end <= 0 or start > end:
            raise ValueError("原子序号范围无效：%s" % token)
        result.update(range(start, end + 1))
    return tuple(sorted(result))


def validate_fragments(atoms, fragments, require_complete=True):
    """Validate disjoint fragment definitions against the parent geometry."""
    atoms_by_index = {int(atom[0]): atom for atom in (atoms or [])}
    if not atoms_by_index:
        raise EDDWorkflowError("没有可用的体系几何结构")
    if not fragments:
        raise EDDWorkflowError("请至少定义一个片段")
    used = set()
    for index, fragment in enumerate(fragments, 1):
        if not isinstance(fragment, EDDFragment):
            raise EDDWorkflowError("片段 %d 的数据格式无效" % index)
        ids = tuple(sorted(set(int(value) for value in fragment.atoms)))
        if not ids:
            raise EDDWorkflowError("片段“%s”没有分配原子" % fragment.name)
        overlap = used.intersection(ids)
        if overlap:
            raise EDDWorkflowError(
                "原子 %s 同时属于多个片段" % min(overlap))
        unknown = set(ids) - set(atoms_by_index)
        if unknown:
            raise EDDWorkflowError(
                "片段“%s”包含不存在的原子 %s" %
                (fragment.name, min(unknown)))
        if int(fragment.multiplicity) <= 0:
            raise EDDWorkflowError(
                "片段“%s”的自旋多重度必须大于 0" % fragment.name)
        used.update(ids)
    if require_complete:
        missing = set(atoms_by_index) - used
        if missing:
            raise EDDWorkflowError(
                "还有原子未分配到片段：%s" %
                _compact_indices(missing))
    return fragments


def _compact_indices(values):
    nums = sorted(set(int(value) for value in values))
    if not nums:
        return ""
    parts = []
    start = previous = nums[0]
    for value in nums[1:]:
        if value == previous + 1:
            previous = value
            continue
        parts.append(str(start) if start == previous
                     else "%d-%d" % (start, previous))
        start = previous = value
    parts.append(str(start) if start == previous
                 else "%d-%d" % (start, previous))
    return ",".join(parts)


def _route_line(method):
    method = str(method or "B3LYP/6-31G(d)").strip()
    method = re.sub(r"^#+\s*[Pp]?\s*", "", method).strip()
    if not method:
        raise EDDWorkflowError("请填写 Gaussian 方法/基组")
    if any(char in method for char in "\r\n"):
        raise EDDWorkflowError("方法/基组不能包含换行")
    if not re.search(r"(?<![A-Za-z])nosymm(?![A-Za-z])",
                     method, flags=re.IGNORECASE):
        method += " nosymm"
    return "#P " + re.sub(r"\s+", " ", method)


def read_charge_multiplicity(path, atoms=None):
    """Read parent charge/multiplicity from a formatted checkpoint."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read(12000)
    except OSError:
        return 0, 1
    match = re.search(
        r"^Number of electrons\s+I\s+(\d+)", text, re.MULTILINE)
    multiplicity = re.search(
        r"^Multiplicity\s+I\s+(\d+)", text, re.MULTILINE)
    charge = 0
    if match and atoms:
        nuclear_charge = sum(
            int(atom[2]) for atom in atoms
            if len(atom) >= 3 and str(atom[2]).lstrip("-").isdigit())
        charge = nuclear_charge - int(match.group(1))
    mult = int(multiplicity.group(1)) if multiplicity else 1
    return int(charge), max(1, mult)


def write_gaussian_input(atoms, path, method, charge, multiplicity,
                         nprocshared=8, mem="8GB"):
    """Write a Gaussian single-point input with unchanged coordinates."""
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    stem = os.path.splitext(os.path.basename(path))[0]
    try:
        nprocshared = max(1, int(nprocshared))
    except (TypeError, ValueError):
        raise EDDWorkflowError("Gaussian 核数必须是正整数")
    mem = str(mem or "8GB").strip()
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?\s*(?:MB|GB|MW|GW)",
                        mem, flags=re.IGNORECASE):
        raise EDDWorkflowError("内存应写成 8GB、4000MB 等形式")
    with open(path, "w", encoding="ascii", errors="strict",
              newline="\n") as handle:
        handle.write("%%nprocshared=%d\n" % nprocshared)
        handle.write("%%mem=%s\n" % mem)
        handle.write("%%chk=%s.chk\n" % stem)
        handle.write(_route_line(method) + "\n\n")
        handle.write("%s EDD parent/fragment calculation\n\n" % stem)
        handle.write("%d %d\n" % (int(charge), int(multiplicity)))
        for _index, symbol, _atomic_number, xyz in atoms:
            handle.write(
                " %-2s %16.10f %16.10f %16.10f\n" %
                (str(symbol), float(xyz[0]), float(xyz[1]), float(xyz[2])))
        handle.write("\n")
    return path


def prepare_fragment_jobs(
        atoms, fragments, output_dir, stem, method,
        nprocshared=8, mem="8GB", require_complete=True,
        include_complex=True, complex_charge=0, complex_multiplicity=1):
    """Create same-level Gaussian single-point jobs for parent and fragments."""
    validate_fragments(atoms, fragments, require_complete=require_complete)
    atoms_by_index = {int(atom[0]): atom for atom in atoms}
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    safe_stem = re.sub(
        r'[<>:"/\\|?*\x00-\x1f]+', "_", str(stem or "")).strip(" .")
    safe_stem = safe_stem or "molecule"
    jobs = []
    if include_complex:
        parent_atoms = sorted(atoms, key=lambda atom: int(atom[0]))
        parent_gjf = os.path.join(
            output_dir, "%s_EDD_parent.gjf" % safe_stem)
        write_gaussian_input(
            parent_atoms, parent_gjf, method, complex_charge,
            complex_multiplicity, nprocshared, mem)
        jobs.append({
            "role": "complex",
            "index": 0,
            "label": "Parent",
            "fragment": None,
            "atoms": parent_atoms,
            "gjf": parent_gjf,
            "log": os.path.splitext(parent_gjf)[0] + ".log",
            "chk": os.path.splitext(parent_gjf)[0] + ".chk",
            "fch": os.path.splitext(parent_gjf)[0] + ".fch",
        })
    for index, fragment in enumerate(fragments, 1):
        fragment_atoms = [
            atoms_by_index[atom_id]
            for atom_id in sorted(fragment.atoms)
        ]
        safe_name = re.sub(
            r'[<>:"/\\|?*\x00-\x1f]+', "_",
            fragment.name or ("Fragment%d" % index)).strip(" .")
        gjf = os.path.join(
            output_dir, "%s_EDD_fragment%d_%s.gjf" %
            (safe_stem, index, safe_name or "fragment"))
        write_gaussian_input(
            fragment_atoms, gjf, method, fragment.charge,
            fragment.multiplicity, nprocshared, mem)
        jobs.append({
            "role": "fragment%d" % index,
            "index": index,
            "label": fragment.name or ("Fragment%d" % index),
            "fragment": fragment,
            "atoms": fragment_atoms,
            "gjf": gjf,
            "log": os.path.splitext(gjf)[0] + ".log",
            "chk": os.path.splitext(gjf)[0] + ".chk",
            "fch": os.path.splitext(gjf)[0] + ".fch",
        })
    return jobs


def run_fragment_jobs(
        jobs, gaussian_exe, formchk_exe=None, on_log=None, on_progress=None,
        cancel=None):
    """Run parent/fragment jobs sequentially, then convert each to fch."""
    if not gaussian_exe or not os.path.isfile(gaussian_exe):
        raise EDDWorkflowError(
            "找不到 Gaussian，请先在主窗口 ⚙️ 路径设置中配置")
    converter = formchk_exe or find_formchk(gaussian_exe)
    if not converter or not os.path.isfile(converter):
        raise EDDWorkflowError(
            "找不到 formchk.exe（应与 g16.exe 位于同一目录）")
    log = on_log or (lambda _message: None)
    progress = on_progress or (lambda _done, _total, _label: None)
    cancel_check = cancel or (lambda: False)
    total = len(jobs)
    outputs = []
    for index, job in enumerate(jobs, 1):
        if cancel_check():
            raise EDDCancelled("已停止母体/片段计算")
        progress(index - 1, total, job["label"])
        log("=== [%d/%d] %s：%s ===" % (
            index, total, job["label"], os.path.basename(job["gjf"])))
        result = run_gaussian(
            job["gjf"], gaussian_exe, log_path=job["log"],
            on_line=log, cancel=cancel)
        if result.cancelled:
            raise EDDCancelled("已停止母体/片段计算")
        if not result.ok:
            raise EDDWorkflowError(
                "任务“%s”计算失败：%s\n日志：%s" %
                (job["label"], result.error, result.log_path))
        chk = find_chk_file(result.log_path) or job["chk"]
        if not os.path.isfile(chk):
            raise EDDWorkflowError(
                "任务“%s”正常结束，但找不到 chk 文件：%s" %
                (job["label"], chk))
        fch = chk_to_fchk(chk, converter, output_path=job["fch"])
        job["chk"] = chk
        job["fch"] = fch
        outputs.append(fch)
        progress(index, total, job["label"])
        log("[%d/%d] formchk 完成：%s" % (
            index, total, os.path.basename(fch)))
    return {
        "complex": next(
            (job["fch"] for job in jobs if job["role"] == "complex"), ""),
        "fragments": [
            job["fch"] for job in jobs if job["role"] != "complex"],
        "jobs": jobs,
    }


def build_difference_sequence(reference_names, grid_quality=3):
    """Return stdin for Multiwfn custom-electron-density cube export."""
    try:
        quality = int(grid_quality)
    except (TypeError, ValueError):
        raise EDDWorkflowError("格点精度必须是整数")
    if quality not in range(1, 6):
        raise EDDWorkflowError("格点精度应在 1～5 之间")
    refs = [str(name) for name in reference_names if str(name).strip()]
    if not refs:
        raise EDDWorkflowError("至少需要一个要减去的参考波函数")
    commands = ["", "5", "0", str(len(refs))]
    for name in refs:
        commands.append("-," + name)
    commands.extend(["1", str(quality), "2", "0", "q", ""])
    return "\n".join(commands) + "\n"


def _write_ascii_settings(multiwfn_exe, workdir):
    exe_dir = os.path.dirname(os.path.abspath(multiwfn_exe))
    source = os.path.join(exe_dir, "settings.ini")
    if os.path.isfile(source):
        with open(source, "r", encoding="utf-8",
                  errors="replace") as handle:
            text = handle.read()
        text = re.sub(
            r"(?im)^\s*isilent\s*=.*$", "  isilent= 1", text)
        if not re.search(r"(?im)^\s*isilent\s*=", text):
            text += "\n  isilent= 1\n"
    else:
        text = "  isilent= 1\n"
    with open(os.path.join(workdir, "settings.ini"), "w",
              encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _parse_grid_stats(output):
    text = str(output or "")
    number = r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)"
    patterns = {
        "minimum": r"The minimum is\s+" + number,
        "maximum": r"The maximum is\s+" + number,
        "integral": r"Summing up all value[^:]*:\s*" + number,
        "positive_integral": r"Summing up positive value[^:]*:\s*" + number,
        "negative_integral": r"Summing up negative value[^:]*:\s*" + number,
    }
    result = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            try:
                result[key] = float(match.group(1))
            except ValueError:
                pass
    return result


def generate_difference_cube(
        complex_fch, references, output_dir, output_name="electron_density_difference",
        grid_quality=3, multiwfn_exe="", on_log=None, cancel=None,
        timeout=1200):
    """Compute ``rho(complex) - sum(rho(reference))`` and export a cube."""
    complex_fch = os.path.abspath(str(complex_fch or ""))
    if not os.path.isfile(complex_fch):
        raise EDDWorkflowError("找不到体系波函数：%s" % complex_fch)
    if not multiwfn_exe or not os.path.isfile(multiwfn_exe):
        raise EDDWorkflowError("找不到 Multiwfn.exe，请先配置路径")
    references = [
        os.path.abspath(str(path)) for path in (references or [])
        if str(path).strip()]
    if not references:
        raise EDDWorkflowError("至少载入一个参考波函数")
    missing = [path for path in references if not os.path.isfile(path)]
    if missing:
        raise EDDWorkflowError("找不到参考波函数：%s" % missing[0])
    output_dir = os.path.abspath(str(output_dir or ""))
    os.makedirs(output_dir, exist_ok=True)
    safe_name = re.sub(
        r'[<>:"/\\|?*\x00-\x1f]+', "_",
        str(output_name or "electron_density_difference")).strip(" .")
    safe_name = safe_name or "electron_density_difference"
    if not safe_name.lower().endswith(".cub"):
        safe_name += ".cub"
    cube_target = os.path.join(output_dir, safe_name)
    log_target = os.path.join(
        output_dir, os.path.splitext(safe_name)[0] + "_multiwfn.log")
    temp_root = _ascii_existing_path(tempfile.mkdtemp(prefix="molstudio_edd_"))
    emit = on_log or (lambda _message: None)
    try:
        local_complex = os.path.join(temp_root, "complex.fchk")
        shutil.copy2(complex_fch, local_complex)
        local_refs = []
        for index, path in enumerate(references, 1):
            local_name = "ref_%03d%s" % (
                index, ".fchk" if path.lower().endswith(".fchk") else ".fch")
            shutil.copy2(path, os.path.join(temp_root, local_name))
            local_refs.append(local_name)
        _write_ascii_settings(multiwfn_exe, temp_root)
        sequence = build_difference_sequence(local_refs, grid_quality)
        emit("Multiwfn：电子密度自定义运算，减去 %d 个参考波函数" %
             len(local_refs))
        output = _run_multiwfn(
            os.path.abspath(multiwfn_exe), local_complex, sequence,
            temp_root, on_log=on_log, cancel=cancel, timeout=timeout)
        source_cube = os.path.join(temp_root, "density.cub")
        if not os.path.isfile(source_cube):
            tail = output[-2200:] if output else "Multiwfn 无输出"
            raise EDDWorkflowError(
                "Multiwfn 未生成密度差 cube。\n\n%s" % tail)
        shutil.copy2(source_cube, cube_target)
        with open(log_target, "w", encoding="utf-8",
                  errors="replace") as handle:
            handle.write(output)
        return EDDResult(
            complex_fch=complex_fch,
            references=references,
            cube_path=cube_target,
            log_path=log_target,
            grid_quality=int(grid_quality),
            output=output,
            archive_dir=output_dir,
            counts={
                "references": len(references),
                "cube_points": _cube_point_count(cube_target),
            },
            stats=_parse_grid_stats(output),
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def _cube_point_count(cube_path):
    try:
        with open(cube_path, "r", encoding="utf-8",
                  errors="replace") as handle:
            handle.readline()
            total_line = handle.readline()
            match = re.search(r"Totally\s+(\d+)\s+grid points",
                              total_line, flags=re.IGNORECASE)
            if match:
                return int(match.group(1))
            atom_line = handle.readline().split()
            x_line = handle.readline().split()
            y_line = handle.readline().split()
            z_line = handle.readline().split()
            if (len(atom_line) < 2 or len(x_line) < 2
                    or len(y_line) < 2 or len(z_line) < 2):
                return 0
            nx = abs(int(float(x_line[1])))
            ny = abs(int(float(y_line[2])))
            nz = abs(int(float(z_line[3])))
            return nx * ny * nz
    except (OSError, ValueError):
        return 0


__all__ = [
    "EDDCancelled",
    "EDDFragment",
    "EDDResult",
    "EDDWorkflowError",
    "build_difference_sequence",
    "generate_difference_cube",
    "parse_atom_indices",
    "prepare_fragment_jobs",
    "read_charge_multiplicity",
    "run_fragment_jobs",
    "validate_fragments",
    "write_gaussian_input",
]
