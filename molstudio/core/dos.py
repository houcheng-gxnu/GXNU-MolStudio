# -*- coding: utf-8 -*-
"""Density-of-states (DOS) workflow for MolStudio.

The workflow follows Multiwfn main function 10 as described in
http://sobereva.com/482.  TDOS is broadened from the exported orbital levels;
PDOS/OPDOS are obtained from Multiwfn's exported curve data.  No Multiwfn
plotting window is opened: a temporary ``settings.ini`` with ``isilent=1``
lets the batch menu continue to the data-export step.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

import numpy as np

from molstudio.core.fchk_parser import parse_fchk_mo_info
from molstudio.core.spectra import (
    _ascii_existing_path,
    _run_multiwfn,
)


AU_TO_EV = 27.211386245988

BROADENING_FUNCTIONS = {
    "gaussian": 1,
    "lorentzian": 2,
    "pseudo_voigt": 3,
}

PDOS_METHODS = {
    "mulliken": 1,
    "scpa": 2,
    "hirshfeld": 3,
    "becke": 4,
}

SPIN_MODES = {
    "all": 3,
    "alpha": 1,
    "beta": 2,
}

DOS_EXTENSIONS = {
    ".fchk", ".fch", ".molden", ".molden.input", ".gms", ".log", ".out",
}

PDOS_EXTENSIONS = {".fchk", ".fch", ".molden", ".gms"}

ANGULAR_TOKENS = {
    "s", "p", "d", "x", "y", "z", "px", "py", "pz", "all",
}


class DOSWorkflowError(RuntimeError):
    """A user-facing DOS workflow failure."""


class DOSCancelled(RuntimeError):
    """Raised when the user stops a running DOS workflow."""


def _dos_extension(path):
    lower = str(path or "").lower()
    if lower.endswith(".molden.input"):
        return ".molden.input"
    return os.path.splitext(lower)[1]


@dataclass(frozen=True)
class DOSFragment:
    """One Multiwfn PDOS/OPDOS fragment definition.

    ``scope`` is one of ``atoms``, ``all_basis`` or ``atom_basis``.
    ``atoms`` accepts Multiwfn index syntax such as ``1-3,7,10-12``.
    """

    name: str
    atoms: str = ""
    scope: str = "atoms"
    angular_momentum: str = ""


@dataclass(frozen=True)
class OrbitalLevel:
    energy: float
    occupation: float
    strength: float = 1.0
    fwhm: float = 0.0
    spin: str = ""


@dataclass
class DOSResult:
    source_path: str
    output_dir: str
    unit: str
    fwhm: float
    broadening: str
    spin: str
    method: str
    fragments: list[str]
    energies: list[float]
    curves: dict[str, list[float]]
    line_energies: list[float] = field(default_factory=list)
    line_heights: list[float] = field(default_factory=list)
    component_lines: dict = field(default_factory=dict)
    homo: float | None = None
    lumo: float | None = None
    energy_range: tuple[float, float, float] | None = None
    centers: list[tuple[str, float]] = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)
    curve_path: str = ""
    line_path: str = ""
    plot_path: str = ""
    log_path: str = ""
    multiwfn_output: str = ""
    sequence: str = ""
    has_opdos: bool = False
    show_tdos: bool = True
    show_pdos: bool = True
    show_opdos: bool = True
    fill_curves: bool = True
    spin_series: dict = field(default_factory=dict)
    d_band_centers: list[dict] = field(default_factory=list)
    curve_colors: dict = field(default_factory=dict)

    @property
    def title(self):
        if self.has_opdos:
            return "TDOS + PDOS + OPDOS"
        if self.curves and len(self.curves) > 1:
            return "TDOS + PDOS"
        return "TDOS"


def validate_dos_source(path, fragments: Sequence[DOSFragment] = ()):
    path = os.path.abspath(str(path or ""))
    if not os.path.isfile(path):
        raise DOSWorkflowError("找不到 DOS 输入文件：%s" % path)
    ext = _dos_extension(path)
    if ext not in DOS_EXTENSIONS:
        raise DOSWorkflowError(
            "DOS 输入应为 .fchk/.fch、.molden、.gms 或 Gaussian .log/.out")
    if fragments and ext not in PDOS_EXTENSIONS:
        raise DOSWorkflowError(
            "Gaussian .log/.out 只能导出 TDOS；PDOS/OPDOS 请使用 "
            ".fchk/.fch、.molden 或 .gms 文件")
    return path


def validate_fragment(fragment: DOSFragment):
    if not isinstance(fragment, DOSFragment):
        raise DOSWorkflowError("无效的 DOS 片段定义")
    if not str(fragment.name or "").strip():
        raise DOSWorkflowError("片段名称不能为空")
    if fragment.scope not in ("atoms", "all_basis", "atom_basis"):
        raise DOSWorkflowError("未知的 DOS 片段类型：%s" % fragment.scope)
    angular = _angular_tokens(fragment.angular_momentum)
    if fragment.scope == "all_basis" and not angular:
        raise DOSWorkflowError("按角动量定义片段时，请选择 s、p、d 或 px/py/pz")
    if fragment.scope in ("atoms", "atom_basis"):
        _validate_atom_selection(fragment.atoms)
    if fragment.scope == "atom_basis" and not angular:
        raise DOSWorkflowError("指定原子的角动量片段必须选择 s、p、d 或 px/py/pz")


def _angular_tokens(value):
    if isinstance(value, (list, tuple)):
        raw = value
    else:
        raw = re.split(r"[\s,+;/|]+", str(value or "").strip().lower())
    out = []
    for token in raw:
        token = str(token or "").strip().lower()
        if not token:
            continue
        # Multiwfn's ``cond`` menu uses X/Y/Z for Px/Py/Pz.
        if token.startswith("p") and token[1:] in ("x", "y", "z"):
            token = token[1:]
        if token not in ANGULAR_TOKENS:
            raise DOSWorkflowError("未知的轨道类型：%s" % token)
        if token not in out:
            out.append(token)
    return out


def _validate_atom_selection(text):
    value = str(text or "").strip()
    if not value:
        raise DOSWorkflowError("请填写原子序号，例如 1-3,7,10")
    if not re.fullmatch(r"\d+(?:-\d+)?(?:\s*,\s*\d+(?:-\d+)?)*", value):
        raise DOSWorkflowError(
            "原子序号格式无效；请使用 1-3,7,10 这样的写法")
    for token in re.split(r"\s*,\s*", value):
        parts = token.split("-")
        if len(parts) == 2 and int(parts[0]) > int(parts[1]):
            raise DOSWorkflowError("原子序号范围必须从小到大：%s" % token)
        if any(int(part) <= 0 for part in parts):
            raise DOSWorkflowError("原子序号必须从 1 开始")
    return value


def _method_code(method):
    key = str(method or "mulliken").strip().lower()
    if key not in PDOS_METHODS:
        raise DOSWorkflowError("未知的轨道成分方法：%s" % method)
    return PDOS_METHODS[key]


def _broadening_code(broadening):
    key = str(broadening or "gaussian").strip().lower()
    if key not in BROADENING_FUNCTIONS:
        raise DOSWorkflowError("未知的展宽函数：%s" % broadening)
    return BROADENING_FUNCTIONS[key]


def _spin_code(spin):
    key = str(spin or "all").strip().lower()
    if key not in SPIN_MODES:
        raise DOSWorkflowError("未知的自旋选项：%s" % spin)
    return SPIN_MODES[key]


def normalize_unit(unit):
    key = str(unit or "a.u.").strip().lower()
    if key in ("au", "a.u", "a.u.", "hartree"):
        return "a.u."
    if key in ("ev", "electronvolt", "electron-volt"):
        return "eV"
    raise DOSWorkflowError("能量单位必须是 a.u. 或 eV")


def _positive_number(value, label):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise DOSWorkflowError("%s 必须是数字" % label)
    if not math.isfinite(number) or number <= 0:
        raise DOSWorkflowError("%s 必须大于 0" % label)
    return number


def normalize_energy_range(emin=None, emax=None, step=None):
    if emin in (None, "") and emax in (None, "") and step in (None, ""):
        return None
    if emin in (None, "") or emax in (None, ""):
        raise DOSWorkflowError("自定义能量范围时必须同时填写下限和上限")
    try:
        lower = float(emin)
        upper = float(emax)
    except (TypeError, ValueError):
        raise DOSWorkflowError("能量范围必须是数字")
    if not math.isfinite(lower) or not math.isfinite(upper):
        raise DOSWorkflowError("能量范围必须是有限数字")
    if lower >= upper:
        raise DOSWorkflowError("能量下限必须小于上限")
    if step in (None, ""):
        gap = upper - lower
        step_value = gap / 10.0
    else:
        step_value = _positive_number(step, "能量步长")
        if step_value > upper - lower:
            raise DOSWorkflowError("能量步长不能大于横轴总范围")
    return lower, upper, step_value


def parse_orginfo(path):
    """Parse Multiwfn ``orginfo.txt`` (energy, occupation, strength, FWHM)."""
    if not path or not os.path.isfile(path):
        return []
    levels = []
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.replace("D", "E").replace("d", "e").strip()
            if not line:
                continue
            fields = line.split()
            if len(fields) < 4:
                continue
            try:
                energy, occupation, strength, fwhm = [
                    float(fields[index]) for index in range(4)]
            except ValueError:
                continue
            levels.append(OrbitalLevel(
                energy=energy,
                occupation=occupation,
                strength=strength,
                fwhm=fwhm,
            ))
    return levels


def parse_numeric_table(path):
    """Read a headerless whitespace table, accepting Fortran D exponents."""
    rows = []
    if not path or not os.path.isfile(path):
        return rows
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            fields = raw.replace("D", "E").replace("d", "e").split()
            if len(fields) < 2:
                continue
            try:
                rows.append([float(value) for value in fields])
            except ValueError:
                continue
    if not rows:
        return []
    width = max(len(row) for row in rows)
    return [row for row in rows if len(row) == width]


def parse_multiwfn_diagnostics(text):
    """Extract useful DOS diagnostics from Multiwfn's text output."""
    text = str(text or "")
    info = {
        "open_shell": bool(re.search(
            r"unrestricted|open[- ]shell", text, flags=re.IGNORECASE)),
        "formula": "",
        "total_electrons": None,
        "alpha_electrons": None,
        "beta_electrons": None,
        "homo_values": [],
        "centers": [],
        "has_opdos": False,
    }
    match = re.search(r"Formula:\s*([^\r\n]+)", text, flags=re.IGNORECASE)
    if match:
        info["formula"] = match.group(1).strip()
    match = re.search(
        r"Total/Alpha/Beta electrons:\s*"
        r"([-+0-9.]+)\s+([-+0-9.]+)\s+([-+0-9.]+)",
        text, flags=re.IGNORECASE)
    if match:
        try:
            info["total_electrons"] = float(match.group(1))
            info["alpha_electrons"] = float(match.group(2))
            info["beta_electrons"] = float(match.group(3))
        except ValueError:
            pass

    number = r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)"
    for match in re.finditer(
            r"Center of\s+(.+?)\s*:\s*" + number,
            text, flags=re.IGNORECASE):
        try:
            info["centers"].append((
                re.sub(r"\s+", " ", match.group(1)).strip(),
                float(match.group(2)),
            ))
        except ValueError:
            pass

    for match in re.finditer(
            r"vertical dash line corresponds to HOMO level at\s+" + number,
            text, flags=re.IGNORECASE):
        prefix = text[max(0, match.start() - 120):match.start()].lower()
        spin = "beta" if "beta" in prefix else (
            "alpha" if "alpha" in prefix else "")
        try:
            info["homo_values"].append((spin, float(match.group(1))))
        except ValueError:
            pass

    info["has_opdos"] = bool(re.search(
        r"Column\s+3\s*:\s*OPDOS|Toggle showing OPDOS", text,
        flags=re.IGNORECASE))
    return info


def detect_open_shell(path):
    """Best-effort open-shell detection used to avoid closed-shell menu 6."""
    ext = _dos_extension(path)
    if ext in (".fchk", ".fch"):
        try:
            info = parse_fchk_mo_info(path)
            return bool(info.get("beta_energies"))
        except Exception:  # noqa: BLE001
            pass
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read(200000)
    except OSError:
        return False
    if re.search(r"Beta Orbital Energies|\[Beta\]|beta electrons",
                 text, flags=re.IGNORECASE):
        match = re.search(
            r"Number of alpha electrons\s+I\s+(\d+).*?"
            r"Number of beta electrons\s+I\s+(\d+)",
            text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return int(match.group(1)) != int(match.group(2))
        return True
    return bool(re.search(r"unrestricted|open[- ]shell|Alpha Orbitals.*Beta Orbitals",
                          text, flags=re.IGNORECASE | re.DOTALL))


def build_multiwfn_dos_sequence(
        fragments: Sequence[DOSFragment] = (), method="mulliken",
        fwhm=0.05, unit="a.u.", broadening="gaussian", spin="all",
        curve_scale=None, emin=None, emax=None, step=None,
        open_shell=False):
    """Return the stdin menu sequence for a headless Multiwfn DOS export."""
    fragments = list(fragments or [])
    if len(fragments) > 10:
        raise DOSWorkflowError("Multiwfn 最多支持 10 个 PDOS 片段")
    for fragment in fragments:
        validate_fragment(fragment)
    method_code = _method_code(method)
    broadening_code = _broadening_code(broadening)
    spin_code = _spin_code(spin)
    unit = normalize_unit(unit)
    fwhm = _positive_number(fwhm, "FWHM")
    if curve_scale not in (None, ""):
        curve_scale = _positive_number(curve_scale, "DOS curve scale")
    energy_range = normalize_energy_range(emin, emax, step)

    if fragments and method_code in (3, 4):
        incompatible = [
            fragment.name for fragment in fragments
            if fragment.scope != "atoms"]
        if incompatible:
            raise DOSWorkflowError(
                "Hirshfeld/Becke 只能按原子定义片段；请把 %s 改为“原子片段”"
                % "、".join(incompatible))

    commands = ["", "10"]
    if fragments:
        commands.extend(["7", str(method_code)])
        commands.append("-1")
        for index, fragment in enumerate(fragments, 1):
            commands.append(str(index))
            if method_code in (3, 4):
                commands.append(_validate_atom_selection(fragment.atoms))
            elif fragment.scope == "atoms":
                commands.append("a " + _validate_atom_selection(fragment.atoms))
            elif fragment.scope == "all_basis":
                commands.append(
                    "l " + ",".join(_angular_tokens(fragment.angular_momentum)))
            else:
                for angular in _angular_tokens(fragment.angular_momentum):
                    commands.extend([
                        "cond",
                        _validate_atom_selection(fragment.atoms),
                        "a",
                        angular.upper(),
                    ])
            # Atom-based Hirshfeld/Becke selections are saved immediately.
            # Mulliken/SCPA enter a basis-function submenu which needs ``q``.
            if method_code in (1, 2):
                commands.append("q")
        commands.append("0")

    if broadening_code != 1:
        commands.extend(["1", str(broadening_code)])
    if unit == "eV":
        commands.append("8")
    if energy_range is not None:
        lower, upper, step_value = energy_range
        commands.extend([
            "2",
            "%s,%s,%s" % (
                _fmt_number(lower), _fmt_number(upper),
                _fmt_number(step_value)),
        ])
    commands.extend(["3", _fmt_number(fwhm)])
    if curve_scale not in (None, ""):
        commands.extend(["4", _fmt_number(curve_scale)])
    if open_shell:
        commands.extend(["6", str(spin_code)])

    # Draw, export DOS_curve.txt/DOS_line.txt, then leave all menus.
    # The post-processing menu accepts ``0`` (not ``q``) for Return.
    commands.extend(["0", "3", "0", "-10", "q", ""])
    return "\n".join(commands) + "\n"


def _fmt_number(value):
    return "%.12g" % float(value)


def gaussian_broaden(energies, strengths, emin, emax, fwhm, npts=3000):
    energies = np.asarray(energies, dtype=float)
    strengths = np.asarray(strengths, dtype=float)
    sigma = float(fwhm) / (2.0 * math.sqrt(2.0 * math.log(2.0)))
    grid = np.linspace(float(emin), float(emax), max(2, int(npts)))
    dos = np.zeros_like(grid)
    if sigma > 0 and energies.size:
        diff = grid[:, None] - energies[None, :]
        dos = np.exp(-0.5 * (diff / sigma) ** 2).dot(strengths)
        dos /= sigma * math.sqrt(2.0 * math.pi)
    return grid, dos


def lorentzian_broaden(energies, strengths, emin, emax, fwhm, npts=3000):
    energies = np.asarray(energies, dtype=float)
    strengths = np.asarray(strengths, dtype=float)
    gamma = float(fwhm) / 2.0
    grid = np.linspace(float(emin), float(emax), max(2, int(npts)))
    dos = np.zeros_like(grid)
    if gamma > 0 and energies.size:
        diff = grid[:, None] - energies[None, :]
        dos = ((gamma / math.pi) / (diff ** 2 + gamma ** 2)).dot(strengths)
    return grid, dos


def pseudo_voigt_broaden(
        energies, strengths, emin, emax, fwhm, npts=3000, eta=0.5):
    grid, gaussian = gaussian_broaden(
        energies, strengths, emin, emax, fwhm, npts)
    _grid, lorentzian = lorentzian_broaden(
        energies, strengths, emin, emax, fwhm, npts)
    return grid, (1.0 - float(eta)) * gaussian + float(eta) * lorentzian


_BROADENERS = {
    "gaussian": gaussian_broaden,
    "lorentzian": lorentzian_broaden,
    "pseudo_voigt": pseudo_voigt_broaden,
}


def broaden_levels(levels, emin, emax, fwhm, broadening="gaussian", npts=3000):
    key = str(broadening or "gaussian").strip().lower()
    if key not in _BROADENERS:
        raise DOSWorkflowError("未知的展宽函数：%s" % broadening)
    levels = list(levels)
    if not levels:
        raise DOSWorkflowError("没有可用于展宽的轨道能级")
    energies = [level.energy for level in levels]
    strengths = [level.strength for level in levels]
    return _BROADENERS[key](
        energies, strengths, emin, emax, fwhm, npts=npts)


def _fchk_levels(path, spin):
    info = parse_fchk_mo_info(path)
    alpha = [float(value) for value in (info.get("alpha_energies") or [])]
    beta = [float(value) for value in (info.get("beta_energies") or [])]
    n_alpha = int(info.get("n_alpha") or 0)
    n_beta = int(info.get("n_beta") or 0)
    if not alpha:
        return [], info
    levels = []
    for index, energy in enumerate(alpha):
        levels.append(OrbitalLevel(
            energy, 1.0 if index < n_alpha else 0.0, spin="alpha"))
    if beta:
        for index, energy in enumerate(beta):
            levels.append(OrbitalLevel(
                energy, 1.0 if index < n_beta else 0.0, spin="beta"))
    else:
        levels = [
            OrbitalLevel(level.energy, 2.0 if level.occupation else 0.0,
                         level.strength, level.fwhm, "restricted")
            for level in levels
        ]
    key = str(spin or "all").lower()
    if key == "alpha":
        levels = [level for level in levels if level.spin in ("alpha", "restricted")]
    elif key == "beta":
        if not beta:
            raise DOSWorkflowError("该体系是闭壳层，没有 beta 轨道")
        levels = [level for level in levels if level.spin == "beta"]
    return levels, info


def _orginfo_levels(path, spin, open_shell=False):
    levels = parse_orginfo(path)
    if not levels:
        return []
    if not open_shell:
        return levels
    split = len(levels) // 2
    if split <= 0:
        return levels
    for index, level in enumerate(levels):
        levels[index] = OrbitalLevel(
            level.energy, level.occupation, level.strength, level.fwhm,
            "alpha" if index < split else "beta")
    key = str(spin or "all").lower()
    if key == "alpha":
        return levels[:split]
    if key == "beta":
        return levels[split:]
    return levels


def _selected_homo(levels):
    occupied = [level for level in levels if level.occupation > 0.1]
    return max((level.energy for level in occupied), default=None)


def _selected_lumo(levels):
    empty = [level for level in levels if level.occupation <= 0.1]
    return min((level.energy for level in empty), default=None)


def suggest_dos_range(path, unit="a.u.", spin="all"):
    """Return a HOMO/LUMO-focused ``(lower, upper, step)`` window.

    The default window leaves 0.45 a.u. below the HOMO and 0.15 a.u. above
    the LUMO.  For the Ferrocene tutorial this gives approximately
    ``-0.60 .. 0.11 a.u.`` with a 0.07 a.u. tick step.
    """
    unit = normalize_unit(unit)
    factor = AU_TO_EV if unit == "eV" else 1.0
    try:
        levels, _info = _fchk_levels(path, spin)
    except Exception:  # noqa: BLE001
        levels = []
    homo = _selected_homo(levels)
    lumo = _selected_lumo(levels)
    if homo is None:
        lower, upper = (-20.0, 5.0) if unit == "eV" else (-0.8, 0.2)
    else:
        left_margin = 12.25 if unit == "eV" else 0.45
        right_margin = 4.08 if unit == "eV" else 0.15
        lower = homo * factor - left_margin
        if lumo is not None:
            upper = lumo * factor + right_margin
        else:
            upper = homo * factor + right_margin
        if unit == "a.u.":
            lower = math.ceil(lower * 100.0) / 100.0
            upper = math.floor(upper * 100.0) / 100.0
        else:
            lower = math.ceil(lower * 10.0) / 10.0
            upper = math.floor(upper * 10.0) / 10.0
        if upper <= lower:
            lower, upper = (-20.0, 5.0) if unit == "eV" else (-0.8, 0.2)
    step = (upper - lower) / 10.0
    return lower, upper, step


def _diagnostic_homo(text, unit, spin):
    diagnostics = parse_multiwfn_diagnostics(text)
    values = diagnostics.get("homo_values") or []
    if spin in ("alpha", "beta"):
        matching = [
            value for label, value in values
            if not label or label == spin]
        if matching:
            return max(matching)
    if values:
        return max(value for _label, value in values)
    return None


def _prepare_multiwfn_dir(source_path, output_dir, sequence):
    source_path = os.path.abspath(source_path)
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    temp_root = _ascii_existing_path(tempfile.mkdtemp(
        prefix="molstudio_dos_"))
    ext = _dos_extension(source_path)
    if ext == ".molden.input":
        ext = ".molden"
    local_input = os.path.join(temp_root, "input" + ext)
    shutil.copy2(source_path, local_input)

    exe_dir = os.path.dirname(os.path.abspath(sequence["exe"]))
    settings_source = os.path.join(exe_dir, "settings.ini")
    if os.path.isfile(settings_source):
        with open(settings_source, "r", encoding="utf-8",
                  errors="replace") as handle:
            text = handle.read()
        text = re.sub(
            r"(?im)^\s*isilent\s*=.*$", "  isilent= 1", text)
        if not re.search(r"(?im)^\s*isilent\s*=", text):
            text += "\n  isilent= 1\n"
    else:
        text = "  isilent= 1\n"
    with open(os.path.join(temp_root, "settings.ini"), "w",
              encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return temp_root, local_input


def _run_export(source_path, output_dir, exe, sequence_text, callbacks,
                cancel, timeout, output_names=None):
    temp_root = ""
    try:
        temp_root, local_input = _prepare_multiwfn_dir(
            source_path, output_dir, {"exe": exe})
        text = _run_multiwfn(
            exe, local_input, sequence_text, temp_root,
            on_log=callbacks.get("on_log"), cancel=cancel, timeout=timeout)
        copied = {}
        output_names = output_names or {}
        for name in ("orginfo.txt", "DOS_curve.txt", "DOS_line.txt"):
            source = os.path.join(temp_root, name)
            target = os.path.join(output_dir, output_names.get(name, name))
            if os.path.isfile(source):
                shutil.copy2(source, target)
                copied[name] = target
        return copied, text
    finally:
        if temp_root:
            shutil.rmtree(temp_root, ignore_errors=True)


def _curve_from_columns(table):
    if not table:
        return [], {}
    xs = [row[0] for row in table]
    width = min(len(row) for row in table)
    columns = {}
    if width >= 2:
        columns["TDOS"] = [row[1] for row in table]
    return xs, columns


def _line_from_table(table):
    xs, ys = [], []
    for row in table:
        if len(row) < 2:
            continue
        if abs(row[1]) > 1e-14:
            xs.append(row[0])
            ys.append(row[1])
    return xs, ys


def _line_column(table, column):
    xs, ys = [], []
    for row in table:
        if column >= len(row) or abs(row[column]) <= 1e-14:
            continue
        xs.append(row[0])
        ys.append(row[column])
    return xs, ys


def _write_own_tdos(energies, tdos, levels, output_dir, prefix=""):
    artifact_prefix = prefix or "DOS_"
    curve_path = os.path.join(output_dir, artifact_prefix + "curve.txt")
    line_path = os.path.join(output_dir, artifact_prefix + "line.txt")
    np.savetxt(
        curve_path, np.column_stack([energies, tdos]),
        fmt="%.8f", delimiter="    ", header="Energy  TDOS",
        comments="")
    np.savetxt(
        line_path,
        np.column_stack([
            [level.energy for level in levels],
            [level.strength for level in levels],
        ]),
        fmt="%.8f", delimiter="    ", header="Energy  Strength",
        comments="")
    return curve_path, line_path


def _npoints_for_range(emin, emax, step):
    if step:
        count = int(round((emax - emin) / float(step))) + 1
        return max(200, min(10000, count))
    return 3000


def _display_fragment_label(label):
    return str(label or "").strip()


def _render_mirrored_dos(result: DOSResult, path, shift_homo=False,
                         show_levels=True, show_centers=True,
                         show_title=False):
    try:
        import matplotlib
        matplotlib.rcParams["font.sans-serif"] = [
            "Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
        matplotlib.rcParams["axes.unicode_minus"] = False
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
        from matplotlib.ticker import FixedLocator, FormatStrFormatter
    except Exception as exc:  # noqa: BLE001
        raise DOSWorkflowError("无法加载 matplotlib：%s" % exc)

    alpha = result.spin_series["alpha"]
    beta = result.spin_series["beta"]
    shift_alpha = float(alpha.homo or 0.0) if shift_homo else 0.0
    shift_beta = float(beta.homo or 0.0) if shift_homo else 0.0
    xs_alpha = np.asarray(alpha.energies, dtype=float) - shift_alpha
    xs_beta = np.asarray(beta.energies, dtype=float) - shift_beta

    fig = Figure(figsize=(7.4, 4.8), dpi=170, facecolor="white")
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    ax.set_facecolor("white")
    alpha_colors = ["#d62728", "#8e44ad", "#d68910", "#17a589"]
    beta_colors = ["#2146f3", "#7d3c98", "#e67e22", "#16a085"]
    colors = result.curve_colors or {}
    alpha_tdos_color = colors.get("α TDOS", "#111111")
    beta_tdos_color = colors.get("β TDOS", "#18a84b")

    alpha_tdos = np.asarray(alpha.curves["TDOS"], dtype=float)
    beta_tdos = -np.asarray(beta.curves["TDOS"], dtype=float)
    if result.fill_curves:
        if result.show_tdos:
            ax.fill_between(
                xs_alpha, 0, alpha_tdos, color=alpha_tdos_color, alpha=0.16,
                zorder=1)
            ax.fill_between(
                xs_beta, 0, beta_tdos, color=beta_tdos_color, alpha=0.16,
                zorder=1)
        if result.show_pdos:
            for index, name in enumerate(alpha.fragments):
                ax.fill_between(
                    xs_alpha, 0, alpha.curves[name],
                    color=colors.get(
                        "α " + name,
                        alpha_colors[index % len(alpha_colors)]),
                    alpha=0.08, zorder=1)
                ax.fill_between(
                    xs_beta, 0, [-value for value in beta.curves[name]],
                    color=colors.get(
                        "β " + name,
                        beta_colors[index % len(beta_colors)]),
                    alpha=0.08, zorder=1)
    if result.show_tdos:
        ax.plot(
            xs_alpha, alpha_tdos, color=alpha_tdos_color,
            linewidth=0.95, label="α TDOS", zorder=4)
        ax.plot(
            xs_beta, beta_tdos,
            color=beta_tdos_color, linewidth=0.95, label="β TDOS", zorder=4)
    if result.show_pdos:
        for index, name in enumerate(alpha.fragments):
            ax.plot(
                xs_alpha, alpha.curves[name],
                color=colors.get(
                    "α " + name,
                    alpha_colors[index % len(alpha_colors)]),
                linewidth=0.85, label="α " + name, zorder=3)
            ax.plot(
                xs_beta, [-value for value in beta.curves[name]],
                color=colors.get(
                    "β " + name,
                    beta_colors[index % len(beta_colors)]),
                linewidth=0.85, label="β " + name, zorder=3)

    ax.axhline(0, color="#555555", linewidth=0.75, zorder=1)
    if show_levels:
        for label, (level_x, level_y) in result.component_lines.items():
            x_values = np.asarray(level_x, dtype=float)
            y_values = np.asarray(level_y, dtype=float)
            if label.startswith("α "):
                x_values -= shift_alpha
                color = colors.get(
                    label, "#111111" if label == "α TDOS"
                    else alpha_colors[0])
            else:
                x_values -= shift_beta
                color = colors.get(
                    label, "#18a84b" if label == "β TDOS"
                    else beta_colors[0])
            ax.vlines(
                x_values, 0, y_values, colors=color,
                linewidths=0.55, alpha=0.72, zorder=2)

    alpha_homo = float(alpha.homo) - shift_alpha if alpha.homo is not None else None
    beta_homo = float(beta.homo) - shift_beta if beta.homo is not None else None
    if alpha_homo is not None:
        ax.axvline(
            alpha_homo, color="#111111", linewidth=0.8,
            linestyle=(0, (2, 3)), alpha=0.9)
        ax.text(
            alpha_homo, 0.96, "α HOMO", transform=ax.get_xaxis_transform(),
            fontsize=9.5, ha="center", va="bottom")
    if beta_homo is not None:
        ax.axvline(
            beta_homo, color="#111111", linewidth=0.8,
            linestyle=(0, (2, 3)), alpha=0.9)
        ax.text(
            beta_homo, 0.18, "β HOMO", transform=ax.get_xaxis_transform(),
            fontsize=9.5, ha="center", va="bottom")

    if show_centers and result.d_band_centers:
        center_lines = []
        for index, center in enumerate(result.d_band_centers):
            spin = center.get("spin", "alpha")
            shift_value = shift_alpha if spin == "alpha" else shift_beta
            center_value = float(center["center"]) - shift_value
            relative = center.get("relative")
            color = (alpha_colors if spin == "alpha" else beta_colors)[
                index % 4]
            ax.axvline(
                center_value, color=color, linestyle=":",
                linewidth=0.9, alpha=0.82)
            if relative is not None:
                prefix = "εd" if center.get("is_d_band") else "center−HOMO"
                center_lines.append("%s %s = %.3f %s" % (
                    "α" if spin == "alpha" else "β", prefix,
                    relative, result.unit))
        if center_lines:
            ax.text(
                0.018, 0.975, "\n".join(center_lines),
                transform=ax.transAxes, fontsize=7.2, color="#263238",
                ha="left", va="top", clip_on=True,
                bbox={
                    "boxstyle": "round,pad=0.35,rounding_size=0.35",
                    "facecolor": "white", "edgecolor": "#B8C2CC",
                    "linewidth": 0.7, "alpha": 0.96,
                })

    positive = max(
        [0.0] + [float(np.max(values)) for label, values
                 in result.curves.items() if label.startswith("α ")])
    negative = min(
        [0.0] + [float(np.min(values)) for label, values
                 in result.curves.items() if label.startswith("β ")])
    headroom = 1.24 if show_centers and result.d_band_centers else 1.14
    top = max(positive * headroom, 0.05)
    bottom = min(negative * headroom, -0.05)
    ax.set_ylim(bottom, top)
    ax.set_xlim(float(xs_alpha[0]), float(xs_alpha[-1]))
    if result.energy_range and result.energy_range[2] > 0:
        lower = float(xs_alpha[0])
        upper = float(xs_alpha[-1])
        step = float(result.energy_range[2])
        ax.xaxis.set_major_locator(
            FixedLocator(np.arange(lower, upper + step * 0.5, step)))
        ax.xaxis.set_major_formatter(FormatStrFormatter("%.2f"))

    ax.set_xlabel(
        "E - E(HOMO) (%s)" % result.unit if shift_homo
        else "Energy(%s)" % result.unit, fontsize=10)
    ax.set_ylabel("Density-of-states", fontsize=10)
    if show_title:
        ax.set_title("Alpha / Beta density of states", fontsize=12)
    ax.tick_params(
        axis="both", which="major", direction="out", top=True, right=True,
        length=4, width=0.8, labelsize=8.5)
    ax.spines["top"].set_visible(True)
    ax.spines["right"].set_visible(True)
    for spine in ax.spines.values():
        spine.set_color("#111111")
        spine.set_linewidth(0.8)
    ax.legend(
        loc="center left", fontsize=8, frameon=False,
        handlelength=2.4, borderaxespad=0.7)
    fig.tight_layout(pad=1.1)
    fig.savefig(path, facecolor="white")
    return path


def _render_dos(result: DOSResult, path, shift_homo=False,
                show_levels=True, show_centers=False, show_title=False):
    try:
        import matplotlib
        matplotlib.rcParams["font.sans-serif"] = [
            "Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
        matplotlib.rcParams["axes.unicode_minus"] = False
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
        from matplotlib.ticker import FixedLocator, FormatStrFormatter
    except Exception as exc:  # noqa: BLE001
        raise DOSWorkflowError("无法加载 matplotlib：%s" % exc)
    if not result.energies or not result.curves:
        raise DOSWorkflowError("没有可绘制的 DOS 曲线")
    if result.spin_series:
        return _render_mirrored_dos(
            result, path, shift_homo=shift_homo,
            show_levels=show_levels, show_centers=show_centers,
            show_title=show_title)

    shift = float(result.homo or 0.0) if shift_homo else 0.0
    xs = np.asarray(result.energies, dtype=float) - shift
    fig = Figure(figsize=(7.4, 4.8), dpi=170, facecolor="white")
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    ax.set_facecolor("#FCFDFE")

    palette = [
        "#d62728", "#2146f3", "#cf2bc9", "#f28e2b", "#9467bd",
        "#17becf", "#bcbd22", "#8c564b", "#e377c2", "#7f7f7f",
    ]
    colors = result.curve_colors or {}
    tdos_color = colors.get("TDOS", "#171717")
    tdos = np.asarray(result.curves.get("TDOS", []), dtype=float)
    if result.show_tdos and tdos.size == xs.size:
        if result.fill_curves:
            ax.fill_between(
                xs, 0, tdos, color=tdos_color, alpha=0.16, zorder=1)
        ax.plot(xs, tdos, color=tdos_color, linewidth=1.3,
                label="TDOS", zorder=4)

    pdos_index = 0
    opdos_ax = None
    for label, values in result.curves.items():
        if label == "TDOS":
            continue
        ys = np.asarray(values, dtype=float)
        if ys.size != xs.size:
            continue
        if label == "OPDOS":
            if not result.show_opdos:
                continue
            # OPDOS has its own sign and scale; Multiwfn uses a separate
            # right-hand axis for it, so it must not compress TDOS/PDOS.
            opdos_ax = ax.twinx()
            opdos_color = colors.get("OPDOS", "#18a84b")
            opdos_ax.plot(
                xs, ys, color=opdos_color, linewidth=0.95,
                label="OPDOS", zorder=5)
            opdos_ax.axhline(
                0, color="#64748B", linewidth=0.65, alpha=0.55)
            opdos_ax.tick_params(
                axis="y", colors="#111111", labelsize=8, direction="out")
            opdos_ax.spines["top"].set_visible(False)
        else:
            if not result.show_pdos:
                continue
            color = colors.get(
                label, palette[pdos_index % len(palette)])
            if result.fill_curves:
                ax.fill_between(
                    xs, 0, ys, color=color, alpha=0.08, zorder=1)
            ax.plot(
                xs, ys, color=color,
                linewidth=0.95, label=_display_fragment_label(label),
                zorder=3)
            pdos_index += 1

    if show_levels:
        component_lines = result.component_lines or {}
        if not component_lines and result.line_energies:
            component_lines = {
                "TDOS": (result.line_energies, result.line_heights)}
        for label, (level_energies, level_heights) in component_lines.items():
            if label == "OPDOS" and not result.show_opdos:
                continue
            if label == "TDOS" and not result.show_tdos:
                continue
            if label not in ("TDOS", "OPDOS") and not result.show_pdos:
                continue
            level_x = np.asarray(level_energies, dtype=float) - shift
            level_y = np.asarray(level_heights, dtype=float)
            if level_y.size != level_x.size or not level_x.size:
                continue
            if label == "TDOS":
                color = colors.get("TDOS", "#6f6f6f")
            elif label == "OPDOS":
                color = colors.get("OPDOS", "#18a84b")
            else:
                try:
                    index = result.fragments.index(label)
                except ValueError:
                    index = 0
                color = colors.get(
                    label, palette[index % len(palette)])
            ax.vlines(
                level_x, 0, level_y, colors=color,
                linewidths=0.55, alpha=0.72, zorder=2)

    if result.homo is not None:
        homo_x = float(result.homo) - shift
        ax.text(
            homo_x, 0.965, "HOMO", transform=ax.get_xaxis_transform(),
            color="#202020", fontsize=8.5, fontweight="bold",
            ha="center", va="bottom")
    if result.lumo is not None:
        lumo_x = float(result.lumo) - shift
        ax.text(
            lumo_x, 0.12, "LUMO", transform=ax.get_xaxis_transform(),
            color="#202020", fontsize=8.5, fontweight="bold",
            ha="center", va="bottom")

    if show_centers and (result.d_band_centers or result.centers):
        center_rows = result.d_band_centers or [
            {"name": label, "center": value, "relative": (
                value - result.homo if result.homo is not None else None)}
            for label, value in result.centers]
        for index, center in enumerate(center_rows):
            value_x = float(center["center"]) - shift
            color = palette[index % len(palette)]
            ax.axvline(
                value_x, color=color, linestyle=":", linewidth=1.0,
                alpha=0.78)
        info_lines = []
        for center in center_rows:
            relative = center.get("relative")
            if relative is None:
                continue
            prefix = "εd" if center.get("is_d_band") else "center−HOMO"
            info_lines.append("%s: %s = %.3f %s" % (
                center.get("name", "PDOS"), prefix,
                float(relative), result.unit))
        if info_lines:
            ax.text(
                0.018, 0.975, "\n".join(info_lines),
                transform=ax.transAxes, fontsize=7.0, color="#263238",
                ha="left", va="top", clip_on=True,
                bbox={
                    "boxstyle": "round,pad=0.35,rounding_size=0.35",
                    "facecolor": "white", "edgecolor": "#B8C2CC",
                    "linewidth": 0.7, "alpha": 0.96,
                })

    xlabel = ("E - E(HOMO) (%s)" % result.unit if shift_homo
              else "Energy(%s)" % result.unit)
    ax.set_xlabel(xlabel, fontsize=10)
    ax.set_ylabel("Density-of-states", fontsize=10)
    if show_title:
        ax.set_title(
            "%s  |  FWHM = %s %s" % (
                result.title, _fmt_number(result.fwhm), result.unit),
            fontsize=12.5, fontweight="bold", color="#0D47A1")
    ax.set_xlim(float(xs[0]), float(xs[-1]))
    if result.energy_range and result.energy_range[2] > 0:
        lower = float(xs[0])
        upper = float(xs[-1])
        step = float(result.energy_range[2])
        ticks = np.arange(lower, upper + step * 0.5, step)
        ax.xaxis.set_major_locator(FixedLocator(ticks))
        ax.xaxis.set_major_formatter(FormatStrFormatter("%.2f"))
    visible_curves = [
        np.asarray(values, dtype=float)
        for label, values in result.curves.items()
        if (label == "TDOS" and result.show_tdos)
        or (label not in ("TDOS", "OPDOS") and result.show_pdos)
    ]
    if visible_curves:
        upper = max(float(np.max(values)) for values in visible_curves
                    if values.size)
        headroom = 1.22 if show_centers and result.d_band_centers else 1.08
        ax.set_ylim(
            min(-0.18 * upper, -0.5) if result.show_opdos else 0.0,
            max(headroom * upper, 0.05))
        if opdos_ax is not None and result.curves.get("OPDOS"):
            left_bottom, left_top = ax.get_ylim()
            zero_fraction = (0.0 - left_bottom) / (left_top - left_bottom)
            opdos_values = np.asarray(result.curves["OPDOS"], dtype=float)
            right_bottom = min(
                float(np.min(opdos_values)) * 1.1 - 0.05, -0.1)
            right_top = max(
                -right_bottom * (1.0 / max(zero_fraction, 0.05) - 1.0),
                float(np.max(opdos_values)) * 1.08,
                0.5)
            opdos_ax.set_ylim(right_bottom, right_top)
    ax.grid(False)
    ax.tick_params(
        axis="both", which="major", direction="out", top=True, right=True,
        length=4, width=0.8, labelsize=8.5)
    ax.spines["top"].set_visible(True)
    ax.spines["right"].set_visible(True)
    for spine in ax.spines.values():
        spine.set_color("#111111")
        spine.set_linewidth(0.8)
    ax.margins(x=0)
    handles, labels = ax.get_legend_handles_labels()
    if opdos_ax is not None:
        right_handles, right_labels = opdos_ax.get_legend_handles_labels()
        handles.extend(right_handles)
        labels.extend(right_labels)
    ax.legend(handles, labels, loc="upper right", fontsize=7.5,
              frameon=False, handlelength=2.4, borderaxespad=0.7)
    fig.tight_layout(pad=1.2)
    fig.savefig(path, facecolor="white")
    return path


def export_dos_csv(result: DOSResult, path, shift_homo=False):
    if not result.energies:
        raise DOSWorkflowError("没有可导出的 DOS 数据")
    shift = float(result.homo or 0.0) if shift_homo else 0.0
    header = ["Energy_%s" % result.unit.replace(".", "")]
    header.extend(result.curves.keys())
    rows = []
    for index, energy in enumerate(result.energies):
        row = [energy - shift]
        for values in result.curves.values():
            row.append(values[index] if index < len(values) else "")
        rows.append(row)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    np.savetxt(
        path, np.asarray(rows, dtype=float), delimiter=",",
        header=",".join(header), comments="", encoding="utf-8")
    return path


def render_saved_dos(result: DOSResult, path, shift_homo=False,
                     show_levels=True, show_centers=False,
                     show_title=False):
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return _render_dos(
        result, path, shift_homo=shift_homo, show_levels=show_levels,
        show_centers=show_centers, show_title=show_title)


def _run_mirrored_spins(
        source_path, output_parent, multiwfn_exe, fwhm, unit, broadening,
        fragments, method, curve_scale, emin, emax, step, show_levels,
        show_centers, show_tdos, show_pdos, fill_curves, show_title,
        flat_output, output_stem, curve_colors, on_stage, on_log, cancel,
        timeout):
    """Run Alpha and Beta separately and combine them as a mirrored plot."""
    temp_root = tempfile.mkdtemp(prefix="molstudio_dos_spins_")

    def child_stage(prefix, lo, hi):
        return lambda pct, text: on_stage(
            lo + int((hi - lo) * max(0, min(100, pct)) / 100.0),
            "%s：%s" % (prefix, text))

    def child_log(prefix):
        return lambda text: on_log("[%s] %s" % (prefix, text))

    common = {
        "source_path": source_path,
        "output_parent": temp_root,
        "multiwfn_exe": multiwfn_exe,
        "fwhm": fwhm,
        "unit": unit,
        "broadening": broadening,
        "fragments": fragments,
        "method": method,
        "curve_scale": curve_scale,
        "emin": emin,
        "emax": emax,
        "step": step,
        "show_levels": show_levels,
        "show_centers": False,
        "show_tdos": show_tdos,
        "show_pdos": show_pdos,
        "show_opdos": False,
        "fill_curves": fill_curves,
        "show_title": False,
        "flat_output": False,
        "timeout": timeout,
    }
    curve_colors = dict(curve_colors or {})
    alpha_curve_colors = {
        key.split(" ", 1)[1]: value
        for key, value in curve_colors.items() if key.startswith("α ")
    }
    beta_curve_colors = {
        key.split(" ", 1)[1]: value
        for key, value in curve_colors.items() if key.startswith("β ")
    }
    try:
        alpha = run_dos_pipeline(
            spin="alpha", cancel=cancel,
            on_stage=child_stage("Alpha", 8, 44),
            on_log=child_log("Alpha"),
            curve_colors=alpha_curve_colors, **common)
        if cancel():
            raise DOSCancelled("已停止 DOS 计算")
        beta = run_dos_pipeline(
            spin="beta", cancel=cancel,
            on_stage=child_stage("Beta", 45, 82),
            on_log=child_log("Beta"),
            curve_colors=beta_curve_colors, **common)
        if cancel():
            raise DOSCancelled("已停止 DOS 计算")

        on_stage(88, "合并 Alpha / Beta 镜像 DOS")
        energies = list(alpha.energies)
        if len(beta.energies) != len(energies):
            raise DOSWorkflowError("Alpha/Beta 的 DOS 网格长度不一致")
        curves = {}
        if show_tdos:
            curves["α TDOS"] = list(alpha.curves["TDOS"])
        if show_pdos:
            for name in alpha.fragments:
                curves["α " + name] = list(alpha.curves[name])
        if show_tdos:
            curves["β TDOS"] = [-value for value in beta.curves["TDOS"]]
        if show_pdos:
            for name in alpha.fragments:
                curves["β " + name] = [-value for value in beta.curves[name]]

        component_lines = {}
        if show_tdos:
            a_x, a_y = alpha.component_lines.get(
                "TDOS", (alpha.line_energies, alpha.line_heights))
            b_x, b_y = beta.component_lines.get(
                "TDOS", (beta.line_energies, beta.line_heights))
            component_lines["α TDOS"] = (a_x, a_y)
            component_lines["β TDOS"] = (b_x, [-value for value in b_y])
        if show_pdos:
            for name in alpha.fragments:
                a_x, a_y = alpha.component_lines.get(name, ([], []))
                b_x, b_y = beta.component_lines.get(name, ([], []))
                component_lines["α " + name] = (a_x, a_y)
                component_lines["β " + name] = (
                    b_x, [-value for value in b_y])

        source_dir = os.path.dirname(source_path)
        output_parent = os.path.abspath(output_parent or source_dir)
        stem = re.sub(
            r'[<>:"/\\|?*\x00-\x1f]+', "_",
            os.path.splitext(os.path.basename(source_path))[0]).strip(" .")
        if flat_output:
            output_dir = source_dir
            prefix = re.sub(
                r'[<>:"/\\|?*\x00-\x1f]+', "_",
                str(output_stem or "").strip()).strip(" .") or (
                    (stem or "molecule") + "_DOS")
        else:
            os.makedirs(output_parent, exist_ok=True)
            output_dir = os.path.join(
                output_parent, "%s_DOS_%s" % (
                    stem or "molecule",
                    __import__("time").strftime("%Y%m%d_%H%M%S")))
            suffix = 2
            while os.path.exists(output_dir):
                output_dir = os.path.join(
                    output_parent, "%s_DOS_%s_%d" % (
                        stem or "molecule",
                        __import__("time").strftime("%Y%m%d_%H%M%S"),
                        suffix))
                suffix += 1
            os.makedirs(output_dir)
            prefix = ""
        artifact_prefix = prefix or "MolStudio_DOS_mirrored"
        result = DOSResult(
            source_path=source_path,
            output_dir=output_dir,
            unit=unit,
            fwhm=fwhm,
            broadening=str(broadening).lower(),
            spin="all",
            method=str(method).lower(),
            fragments=list(alpha.fragments),
            energies=energies,
            curves=curves,
            component_lines=component_lines,
            homo=alpha.homo,
            lumo=alpha.lumo,
            energy_range=alpha.energy_range,
            diagnostics={
                "mirrored_spins": True,
                "alpha_homo": alpha.homo,
                "beta_homo": beta.homo,
            },
            show_tdos=show_tdos,
            show_pdos=show_pdos,
            show_opdos=False,
            fill_curves=fill_curves,
            spin_series={"alpha": alpha, "beta": beta},
            curve_colors=curve_colors,
            d_band_centers=[
                dict(center, spin=spin)
                for spin, series in (("alpha", alpha), ("beta", beta))
                for center in series.d_band_centers
            ],
        )
        result.log_path = os.path.join(output_dir, artifact_prefix + ".log")
        with open(result.log_path, "w", encoding="utf-8",
                  errors="replace") as handle:
            handle.write("===== ALPHA =====\n")
            handle.write(alpha.multiwfn_output)
            handle.write("\n===== BETA =====\n")
            handle.write(beta.multiwfn_output)
        result.plot_path = os.path.join(output_dir, artifact_prefix + ".png")

        curve_path = os.path.join(
            output_dir, artifact_prefix + "_curve.txt")
        columns = [energies]
        columns.extend(curves.values())
        np.savetxt(
            curve_path, np.asarray(columns, dtype=float).T,
            fmt="%.8f", delimiter="    ",
            header="Energy  " + "  ".join(curves.keys()), comments="",
            encoding="utf-8")
        result.curve_path = curve_path
        result.line_path = os.path.join(
            output_dir, artifact_prefix + "_line.txt")
        with open(result.line_path, "w", encoding="utf-8",
                  newline="\n") as handle:
            for label, (level_x, level_y) in component_lines.items():
                handle.write("# %s\n" % label)
                for x_value, y_value in zip(level_x, level_y):
                    handle.write(
                        "%.8f  %.8f\n" % (float(x_value), float(y_value)))
        _render_dos(
            result, result.plot_path, show_levels=show_levels,
            show_centers=show_centers, show_title=show_title)
        on_stage(100, "Alpha / Beta 镜像 DOS 绘图完成")
        return result
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def run_dos_pipeline(
        source_path, output_parent, multiwfn_exe, fwhm=0.05, unit="a.u.",
        broadening="gaussian", spin="all", fragments: Iterable[DOSFragment] = (),
        method="mulliken", curve_scale=None, emin=None, emax=None, step=None,
        show_levels=True, show_centers=False,
        show_tdos=True, show_pdos=True, show_opdos=True,
        fill_curves=True, curve_colors=None, show_title=False, flat_output=False,
        output_stem="",
        on_stage: Callable[[int, str], None] = None,
        on_log: Callable[[str], None] = None,
        cancel: Callable[[], bool] = None,
        timeout: int = 900):
    """Run Multiwfn DOS export and render a MolStudio plot.

    The function is synchronous and intended for a worker thread.
    """
    callbacks = {
        "on_stage": on_stage or (lambda _pct, _text: None),
        "on_log": on_log or (lambda _text: None),
    }
    cancel_check = cancel or (lambda: False)

    def stage(pct, text):
        if cancel_check():
            raise DOSCancelled("已停止 DOS 计算")
        callbacks["on_stage"](int(max(0, min(100, pct))), text)

    source_path = validate_dos_source(source_path, fragments)
    multiwfn_exe = os.path.abspath(str(multiwfn_exe or ""))
    if not os.path.isfile(multiwfn_exe):
        raise DOSWorkflowError("找不到 Multiwfn.exe，请先在路径设置中配置")
    unit = normalize_unit(unit)
    fwhm = _positive_number(fwhm, "FWHM")
    if curve_scale not in (None, ""):
        curve_scale = _positive_number(curve_scale, "DOS curve scale")
    fragments = list(fragments or [])
    for fragment in fragments:
        validate_fragment(fragment)
    if len(fragments) > 10:
        raise DOSWorkflowError("Multiwfn 最多支持 10 个 PDOS 片段")
    energy_range = normalize_energy_range(emin, emax, step) or suggest_dos_range(
        source_path, unit=unit, spin=spin)
    method_code = _method_code(method)
    if fragments and method_code in (3, 4):
        incompatible = [
            fragment.name for fragment in fragments
            if fragment.scope != "atoms"]
        if incompatible:
            raise DOSWorkflowError(
                "Hirshfeld/Becke 只能按原子定义片段；请修改：%s"
                % "、".join(incompatible))

    is_open = detect_open_shell(source_path)
    if str(spin).lower() == "all" and is_open:
        return _run_mirrored_spins(
            source_path=source_path,
            output_parent=output_parent,
            multiwfn_exe=multiwfn_exe,
            fwhm=fwhm,
            unit=unit,
            broadening=broadening,
            fragments=fragments,
            method=method,
            curve_scale=curve_scale,
            emin=emin,
            emax=emax,
            step=step,
            show_levels=show_levels,
            show_centers=show_centers,
            show_tdos=show_tdos,
            show_pdos=show_pdos,
            fill_curves=fill_curves,
            show_title=show_title,
            flat_output=flat_output,
            output_stem=output_stem,
            curve_colors=curve_colors,
            on_stage=callbacks["on_stage"],
            on_log=callbacks["on_log"],
            cancel=cancel_check,
            timeout=timeout,
        )

    source_dir = os.path.dirname(source_path)
    output_parent = os.path.abspath(str(output_parent or source_dir))
    os.makedirs(output_parent, exist_ok=True)
    stem = re.sub(
        r'[<>:"/\\|?*\x00-\x1f]+', "_",
        os.path.splitext(os.path.basename(source_path))[0]).strip(" .")
    if flat_output:
        output_dir = source_dir
        output_prefix = re.sub(
            r'[<>:"/\\|?*\x00-\x1f]+', "_",
            str(output_stem or "").strip()).strip(" .") or (
                (stem or "molecule") + "_DOS")
        output_names = {
            "orginfo.txt": output_prefix + "_orginfo.txt",
            "DOS_curve.txt": output_prefix + "_curve.txt",
            "DOS_line.txt": output_prefix + "_line.txt",
        }
    else:
        output_dir = os.path.join(
            output_parent, "%s_DOS_%s" % (
                stem or "molecule",
                __import__("time").strftime("%Y%m%d_%H%M%S")))
        suffix = 2
        while os.path.exists(output_dir):
            output_dir = os.path.join(
                output_parent, "%s_DOS_%s_%d" % (
                    stem or "molecule",
                    __import__("time").strftime("%Y%m%d_%H%M%S"), suffix))
            suffix += 1
        os.makedirs(output_dir)
        output_prefix = ""
        output_names = {}

    if str(spin).lower() in ("alpha", "beta") and not is_open:
        raise DOSWorkflowError("闭壳层体系不能单独选择 alpha 或 beta")

    sequence = build_multiwfn_dos_sequence(
        fragments, method=method, fwhm=fwhm, unit=unit,
        broadening=broadening, spin=spin, curve_scale=curve_scale,
        emin=energy_range[0], emax=energy_range[1],
        step=energy_range[2], open_shell=is_open)
    sequence_export = "" if fragments else (
        "\n10\n-3\nq\nq\n")
    stage(8, "Multiwfn 正在读取波函数…")
    callbacks["on_log"](
        "Multiwfn DOS：主功能 10 → %s" %
        ("PDOS/OPDOS 导出" if fragments else "轨道能级导出"))

    if fragments:
        stage(20, "Multiwfn 正在计算片段轨道成分并导出 DOS…")
        copied, multiwfn_output = _run_export(
            source_path, output_dir, multiwfn_exe, sequence,
            callbacks, cancel_check, timeout, output_names)
        curve_path = copied.get("DOS_curve.txt", "")
        line_path = copied.get("DOS_line.txt", "")
        if not curve_path or not os.path.isfile(curve_path):
            tail = (multiwfn_output or "Multiwfn 无输出")[-2200:]
            raise DOSWorkflowError(
                "Multiwfn 未能导出 DOS_curve.txt。\n\n%s" % tail)
        table = parse_numeric_table(curve_path)
        energies, curves = _curve_from_columns(table)
        if not energies:
            raise DOSWorkflowError("DOS 曲线数据为空或格式无法识别")
        diagnostics = parse_multiwfn_diagnostics(multiwfn_output)
        has_opdos = bool(
            diagnostics.get("has_opdos") and len(fragments) >= 2
            and method_code in (1, 2))
        ordered = {"TDOS": curves.get("TDOS", [0.0] * len(energies))}
        pdos_start = 3 if has_opdos else 2
        for index, fragment in enumerate(fragments):
            column = pdos_start + index
            values = (
                [row[column] for row in table]
                if table and column < min(len(row) for row in table)
                else [0.0] * len(energies))
            ordered[fragment.name] = values
        if has_opdos and len(table[0]) > 2:
            ordered["OPDOS"] = [row[2] for row in table]
        curves = ordered

        line_table = parse_numeric_table(line_path)
        line_x, line_y = _line_from_table(line_table)
        component_lines = {"TDOS": _line_column(line_table, 1)}
        line_pdos_start = 3 if has_opdos else 2
        for index, fragment in enumerate(fragments):
            component_lines[fragment.name] = _line_column(
                line_table, line_pdos_start + index)
        if has_opdos:
            component_lines["OPDOS"] = _line_column(line_table, 2)
        homo = _diagnostic_homo(multiwfn_output, unit, spin)
        lumo = None
        try:
            fchk_levels, _info = _fchk_levels(source_path, spin)
            if homo is None:
                homo = _selected_homo(fchk_levels)
            lumo = _selected_lumo(fchk_levels)
            if unit == "eV":
                if homo is not None:
                    homo *= AU_TO_EV
                if lumo is not None:
                    lumo *= AU_TO_EV
        except Exception:  # noqa: BLE001
            pass
    else:
        stage(20, "Multiwfn 正在导出轨道能级…")
        copied, multiwfn_output = _run_export(
            source_path, output_dir, multiwfn_exe, sequence_export,
            callbacks, cancel_check, timeout, output_names)
        orginfo = copied.get("orginfo.txt", "")
        if not orginfo:
            tail = (multiwfn_output or "Multiwfn 无输出")[-2200:]
            raise DOSWorkflowError(
                "Multiwfn 未能导出 orginfo.txt。\n\n%s" % tail)
        diagnostics = parse_multiwfn_diagnostics(multiwfn_output)
        if _dos_extension(source_path) in (".fchk", ".fch"):
            levels, _info = _fchk_levels(source_path, spin)
        else:
            levels = _orginfo_levels(
                orginfo, spin, diagnostics.get("open_shell", is_open))
        if not levels:
            raise DOSWorkflowError("没有找到所选自旋的轨道能级")
        factor = AU_TO_EV if unit == "eV" else 1.0
        display_levels = [
            OrbitalLevel(
                level.energy * factor, level.occupation,
                level.strength, level.fwhm * factor, level.spin)
            for level in levels
        ]
        lower, upper, step_value = energy_range
        npts = _npoints_for_range(lower, upper, step_value)
        grid, tdos = broaden_levels(
            display_levels, lower, upper, fwhm,
            broadening=broadening, npts=npts)
        energies = [float(value) for value in grid]
        curves = {"TDOS": [float(value) for value in tdos]}
        line_x = [level.energy for level in display_levels]
        line_y = [level.strength for level in display_levels]
        component_lines = {"TDOS": (line_x, line_y)}
        homo = _selected_homo(display_levels)
        lumo = _selected_lumo(display_levels)
        curve_path, line_path = _write_own_tdos(
            energies, tdos, display_levels, output_dir, output_prefix)
        diagnostics.update({
            "open_shell": is_open,
            "n_levels": len(display_levels),
            "range": [lower, upper],
        })

    centers = []
    for index, (label, value) in enumerate(diagnostics.get("centers", [])):
        display_label = label
        match = re.fullmatch(r"PDOS\s+(\d+)", label, flags=re.IGNORECASE)
        if match:
            fragment_index = int(match.group(1)) - 1
            if 0 <= fragment_index < len(fragments):
                display_label = "%s center" % fragments[fragment_index].name
        centers.append((display_label, float(value)))
    d_band_centers = []
    for label, value in centers:
        if label == "TDOS":
            continue
        name = label[:-7] if label.lower().endswith(" center") else label
        fragment = next(
            (item for item in fragments if item.name == name), None)
        angular = _angular_tokens(
            fragment.angular_momentum) if fragment is not None else []
        is_d_band = (
            fragment is not None and fragment.scope in (
                "all_basis", "atom_basis") and angular == ["d"])
        d_band_centers.append({
            "name": name,
            "center": float(value),
            "relative": (
                float(value) - float(homo) if homo is not None else None),
            "is_d_band": is_d_band,
        })
    result = DOSResult(
        source_path=source_path,
        output_dir=output_dir,
        unit=unit,
        fwhm=fwhm,
        broadening=str(broadening).lower(),
        spin=str(spin).lower(),
        method=str(method).lower(),
        fragments=[fragment.name for fragment in fragments],
        energies=energies,
        curves=curves,
        line_energies=line_x,
        line_heights=line_y,
        component_lines=component_lines,
        homo=homo,
        lumo=lumo,
        energy_range=tuple(energy_range),
        centers=centers,
        diagnostics=diagnostics,
        curve_path=curve_path,
        line_path=line_path,
        multiwfn_output=multiwfn_output,
        sequence=sequence,
        has_opdos=curves.get("OPDOS") is not None,
        show_tdos=bool(show_tdos),
        show_pdos=bool(show_pdos),
        show_opdos=bool(show_opdos),
        fill_curves=bool(fill_curves),
        curve_colors=dict(curve_colors or {}),
        d_band_centers=d_band_centers,
    )
    stage(82, "正在绘制 MolStudio DOS 图…")
    result.log_path = os.path.join(
        output_dir,
        output_prefix + ".log" if output_prefix else "_multiwfn_dos.log")
    with open(result.log_path, "w", encoding="utf-8",
              errors="replace") as handle:
        handle.write(multiwfn_output)
    result.plot_path = os.path.join(
        output_dir,
        output_prefix + ".png" if output_prefix else "MolStudio_DOS.png")
    _render_dos(
        result, result.plot_path, show_levels=show_levels,
        show_centers=show_centers, show_title=show_title)
    stage(100, "DOS 绘图完成")
    return result


__all__ = [
    "AU_TO_EV",
    "BROADENING_FUNCTIONS",
    "DOSCancelled",
    "DOSFragment",
    "DOSResult",
    "DOSWorkflowError",
    "PDOS_METHODS",
    "build_multiwfn_dos_sequence",
    "detect_open_shell",
    "export_dos_csv",
    "gaussian_broaden",
    "lorentzian_broaden",
    "parse_multiwfn_diagnostics",
    "parse_numeric_table",
    "parse_orginfo",
    "pseudo_voigt_broaden",
    "render_saved_dos",
    "run_dos_pipeline",
    "suggest_dos_range",
    "validate_dos_source",
    "validate_fragment",
]
