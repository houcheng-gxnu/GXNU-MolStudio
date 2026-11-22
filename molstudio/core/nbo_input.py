# -*- coding: utf-8 -*-
"""Build Gaussian inputs that produce directly usable NBO data.

The generator intentionally starts from the final geometry and the original
route of an existing calculation. NBO analysis is normally a single-point
follow-up, so optimization/frequency/population keywords are replaced by the
selected NBO output mode.
"""

from __future__ import annotations

import os
import re

from molstudio.core import gaussian_run as G
from molstudio.core.di_local import (
    fchk_route_hint,
    parse_charge_multiplicity,
    read_structure,
)

_CHARGE_RE = re.compile(r"^Charge\s+[A-Z]\s+([+-]?\d+)\s*$", re.MULTILINE)
_MULT_RE = re.compile(r"^Multiplicity\s+[A-Z]\s+([+-]?\d+)\s*$", re.MULTILINE)
_NPROC_RE = re.compile(
    r"^\s*%nprocshared\s*=\s*(\d+)", re.IGNORECASE | re.MULTILINE)
_MEM_RE = re.compile(
    r"^\s*%mem\s*=\s*(\d+)\s*GB", re.IGNORECASE | re.MULTILINE)

_DROP_EXACT = frozenset({
    "#", "p", "sp", "freq", "force", "stable", "restart", "allcheck",
    "job", "density",
})
_DROP_PREFIX = (
    "opt", "geom", "guess", "chk", "output", "pop", "irc", "td", "restart",
)


def _read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except OSError:
        return ""


def parse_route_for_reuse(log_file):
    """Read a Gaussian route from a .log or directly from a .gjf/.com.

    In log files Gaussian can split a keyword itself (for example
    ``int=ultrafin`` / ``e``) when printing the route; those 70-column chunks
    are concatenated. In input files continuation lines are separate route
    tokens and are joined with spaces.
    """
    lines = _read_text(log_file).splitlines()
    start = -1
    for index, line in enumerate(lines):
        if line.strip().startswith("#"):
            start = index
            break
    if start < 0:
        return ""

    extension = os.path.splitext(str(log_file))[1].lower()
    if extension in (".gjf", ".com"):
        parts = []
        for raw in lines[start:]:
            text = raw.strip()
            if not text:
                break
            parts.append(text)
        return " ".join(parts).lstrip("#").strip()

    chunks = []
    for raw in lines[start:]:
        stripped = raw.strip()
        if not stripped or (len(stripped) >= 3 and set(stripped) <= {"-"}):
            break
        chunk = raw.rstrip("\r\n")
        if chunk.startswith(" "):
            chunk = chunk[1:]
        chunks.append(chunk)
    route = "".join(chunks).strip()
    return route.lstrip("#").strip()


def _strip_job_keywords(route):
    kept = []
    for token in str(route or "").split():
        bare = token.lstrip("#")
        base = re.split(r"[=(]", bare.lower(), maxsplit=1)[0]
        if not bare or base in _DROP_EXACT:
            continue
        if base.startswith(_DROP_PREFIX):
            continue
        kept.append(bare)
    if not any("/" in token for token in kept):
        raise ValueError("原计算 route 中没有可识别的 方法/基组")
    return kept


def _charge_mult_from_fchk(fchk_file):
    text = _read_text(fchk_file)
    charge = _CHARGE_RE.search(text)
    mult = _MULT_RE.search(text)
    return (
        int(charge.group(1)) if charge else None,
        int(mult.group(1)) if mult else None,
    )


def inspect_nbo_source(log_file, fchk_file=None):
    """Collect geometry, route and run metadata for a reusable NBO job."""
    if not log_file or not os.path.isfile(log_file):
        raise ValueError("请先载入 Gaussian 输入或日志")
    atoms = read_structure(log_file)
    if not atoms:
        raise ValueError("源文件中没有可用的几何结构")

    raw_route = parse_route_for_reuse(log_file)
    if not raw_route and fchk_file:
        raw_route = fchk_route_hint(fchk_file)
    if not raw_route:
        raise ValueError("无法从日志或 fchk 提取方法/基组")

    extension = os.path.splitext(str(log_file))[1].lower()
    if extension in (".gjf", ".com"):
        charge_mult = G.read_gjf_charge_mult(log_file)
    else:
        charge_mult = parse_charge_multiplicity(log_file)
    if charge_mult is None and fchk_file:
        charge_mult = _charge_mult_from_fchk(fchk_file)
    if charge_mult is None:
        raise ValueError("无法确定电荷与多重度")

    log_text = _read_text(log_file)
    nproc_match = _NPROC_RE.search(log_text)
    mem_match = _MEM_RE.search(log_text)
    return {
        "symbols": [atom[1] for atom in atoms],
        "coords": [list(atom[3]) for atom in atoms],
        "charge": int(charge_mult[0]),
        "multiplicity": int(charge_mult[1]),
        "route": raw_route,
        "nproc": int(nproc_match.group(1)) if nproc_match else 8,
        "mem_gb": int(mem_match.group(1)) if mem_match else 8,
        "source": log_file,
    }


def build_nbo_input(log_file, fchk_file=None, output_stem=None,
                    mode="plot", title=None, nproc=None, mem_gb=None,
                    charge=None, multiplicity=None, route=None):
    """Return ``(gjf_text, metadata)`` for a ready-to-run NBO calculation.

    ``mode='plot'`` emits ``pop=nboread`` plus a ``$NBO plot file=... $END``
    data block. ``mode='saveNBO'`` instead asks Gaussian to store the NBOs in
    the checkpoint for later ``formchk`` conversion.
    """
    info = inspect_nbo_source(log_file, fchk_file)
    mode = str(mode or "plot").strip()
    if mode not in ("plot", "saveNBO"):
        raise ValueError("NBO 输出方式必须是 plot 或 saveNBO")

    stem = str(output_stem or "nbo_job")
    stem = os.path.splitext(os.path.basename(stem))[0] or "nbo_job"
    route_base = route if route is not None else info["route"]
    tokens = _strip_job_keywords(route_base)
    nbo_keyword = "pop=nboread" if mode == "plot" else "pop=saveNBO"
    job_route = "#p " + " ".join(tokens + [nbo_keyword])

    charge = info["charge"] if charge is None else int(charge)
    multiplicity = (
        info["multiplicity"] if multiplicity is None else int(multiplicity)
    )
    nproc = info["nproc"] if nproc is None else int(nproc)
    mem_gb = info["mem_gb"] if mem_gb is None else int(mem_gb)
    if title is None:
        # 标题跟着输出方式走：saveNBO 的输入不该自称 "NBO plot"
        suffix = " saveNBO" if mode == "saveNBO" else " NBO plot"
        title = stem + suffix

    text = G.build_gjf(
        info["symbols"], info["coords"], charge=charge, mult=multiplicity,
        route=job_route, title=title, nproc=nproc, mem_gb=mem_gb,
        chk_name=stem + ".chk")
    if mode == "plot":
        text += "$NBO plot file=%s $END\n" % stem
    return text, {
        "route": job_route,
        "mode": mode,
        "plot_base": stem if mode == "plot" else "",
        "chk": stem + ".chk",
        "charge": charge,
        "multiplicity": multiplicity,
        "nproc": nproc,
        "mem_gb": mem_gb,
        "symbols": info["symbols"],
    }


__all__ = [
    "build_nbo_input",
    "inspect_nbo_source",
    "parse_route_for_reuse",
]
