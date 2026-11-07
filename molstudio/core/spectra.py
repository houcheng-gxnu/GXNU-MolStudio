# -*- coding: utf-8 -*-
"""Gaussian -> Multiwfn molecular-spectrum workflow.

This module is deliberately Qt-independent so the whole workflow can also be
tested and scripted outside the desktop application.  It follows the input
requirements summarised in sobereva.com/224:

* IR: ``freq``
* Raman: ``freq=raman``
* VCD: ``freq=VCD``
* ROA: ``freq=ROA`` plus one or more incident wavelengths
* UV-Vis / ECD: a TD (or equivalent excited-state) Gaussian output
* Fluorescence: S1 optimisation, then the vertical S1 -> S0 emission data
* Phosphorescence: T1 optimisation, followed by a triplet TD calculation at
  the T1 geometry (normalised band; plain Gaussian TDDFT has no SOC intensity)

Multiwfn's main function 11 is driven through stdin.  We deliberately ask
Multiwfn to export its actual curve data and then render that data inside
MolStudio.  This avoids relying on Multiwfn's interactive image window and
still keeps the broadening, FWHM, frequency scaling and unit conventions in
Multiwfn.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass

from molstudio.core.fchk_orbital import ELEMENT_SYMBOLS
from molstudio.core.gaussian_run import run_gaussian

# 最近一次 matplotlib 渲染实际使用的横轴范围：
# (xmin, xmax, 跃迁线条数, 被裁掉的越界跃迁线条数)。供验证脚本/测试读取，
# 用来断言"MolStudio 图的横轴 == Multiwfn 导出曲线的横轴"。
_LAST_RENDER_LIMITS = None
# 最近一次渲染实际设置的横轴 (left, right)，含方向。振动谱应为 (4000, 0)。
_LAST_RENDER_XLIM = None


class SpectrumCancelled(RuntimeError):
    """Raised when a running spectrum workflow is stopped by the user."""


class SpectrumWorkflowError(RuntimeError):
    """Raised for a user-facing workflow failure."""


@dataclass(frozen=True)
class SpectrumKind:
    key: str
    name: str
    multiwfn_menu: str
    electronic: bool
    workflow: str = "absorption"
    frequency_keyword: str = ""
    x_unit: str = ""
    y_unit: str = ""


SPECTRUM_KINDS = {
    "uvvis": SpectrumKind(
        "uvvis", "UV-Vis", "3", True, "absorption",
        x_unit="nm", y_unit="L mol$^{-1}$ cm$^{-1}$"),
    "ecd": SpectrumKind(
        "ecd", "ECD", "4", True, "absorption",
        x_unit="nm", y_unit="arb."),
    "fluorescence": SpectrumKind(
        "fluorescence", "Fluorescence / 荧光", "3", True, "fluorescence",
        x_unit="nm", y_unit="arb."),
    "phosphorescence": SpectrumKind(
        "phosphorescence", "Phosphorescence / 磷光", "3", True,
        "phosphorescence", x_unit="nm", y_unit="normalised intensity"),
    "ir": SpectrumKind(
        "ir", "IR", "1", False, "absorption", "freq",
        x_unit="cm$^{-1}$", y_unit="L mol$^{-1}$ cm$^{-1}$"),
    "raman": SpectrumKind(
        "raman", "Raman", "2", False, "absorption", "freq=raman",
        x_unit="cm$^{-1}$", y_unit="Raman activity"),
    "vcd": SpectrumKind(
        "vcd", "VCD", "5", False, "absorption", "freq=VCD",
        x_unit="cm$^{-1}$", y_unit="arb."),
    "roa": SpectrumKind(
        "roa", "ROA", "6", False, "absorption", "freq=ROA",
        x_unit="cm$^{-1}$", y_unit="arb."),
}


def get_spectrum_kind(key):
    """Return a :class:`SpectrumKind` or raise a concise error."""
    try:
        return SPECTRUM_KINDS[str(key).lower()]
    except KeyError:
        raise ValueError("Unknown spectrum type: %r" % key)


def _safe_stem(name):
    stem = os.path.splitext(os.path.basename(name or ""))[0]
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", stem).strip(" .")
    return stem or "molecule"


def _new_run_directory(parent, source_name, kind_key):
    """Create a fresh run directory so a second calculation cannot overwrite."""
    os.makedirs(parent, exist_ok=True)
    stem = _safe_stem(source_name)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    candidate = os.path.join(parent, "%s_%s_%s" % (stem, kind_key, stamp))
    suffix = 2
    while os.path.exists(candidate):
        candidate = os.path.join(
            parent, "%s_%s_%s_%d" % (stem, kind_key, stamp, suffix))
        suffix += 1
    os.makedirs(candidate)
    return candidate


def _clean_theory(theory):
    theory = (theory or "").strip()
    theory = re.sub(r"^#+\s*[Pp]?\s*", "", theory).strip()
    if not theory:
        raise ValueError("请先填写 Gaussian 理论方法，例如 B3LYP/6-31G(d)")
    if any(ch in theory for ch in "\r\n"):
        raise ValueError("理论方法不能包含换行")
    return theory


def normalize_wavelengths(wavelengths):
    """Normalise ROA input wavelengths to Gaussian's ``532nm`` form."""
    if not wavelengths:
        return []
    if isinstance(wavelengths, str):
        tokens = re.split(r"[\s,;]+", wavelengths.strip())
    else:
        tokens = list(wavelengths)
    out = []
    for token in tokens:
        token = str(token).strip()
        if not token:
            continue
        match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*(?:nm)?", token,
                             flags=re.IGNORECASE)
        if not match:
            raise ValueError("入射波长应写成 532、532nm 或空格分隔的一组波长")
        out.append(match.group(1) + "nm")
    return out


def parse_roa_wavelengths(log_path):
    """Read the incident wavelengths (nm) actually present in a ROA output.

    Multiwfn *always* asks ``Load data for which frequency?`` when a ROA file
    is loaded, even if it contains only one wavelength.  The answer must be an
    index into the file's own wavelength list, not into the wavelengths typed
    into MolStudio's job builder (which only describes a future Gaussian job).
    Gaussian prints the list both as ``Alpha(-w;w) w= 532.0nm`` and as
    ``Incident light (cm**-1)``; prefer the former because its order is the
    one Multiwfn uses for the index.
    """
    alpha = re.compile(r"Alpha\(-w;w\)\s*w=\s*([0-9.]+)\s*nm", re.I)
    incident = re.compile(r"Incident light\s*\(cm\*\*-1\)\s*:\s*(.+)", re.I)
    found = []
    cm_values = []
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                match = alpha.search(line)
                if match:
                    value = float(match.group(1))
                    if value not in found:
                        found.append(value)
                    continue
                match = incident.search(line)
                if match:
                    for token in match.group(1).split():
                        try:
                            value = float(token)
                        except ValueError:
                            continue
                        if value > 0:
                            nm = 1.0e7 / value
                            if nm not in cm_values:
                                cm_values.append(nm)
    except OSError:
        return []
    return found or cm_values


def build_gaussian_route(kind_key, theory, job_kind="spectrum", nstates=20,
                         optimize=True, solvent=""):
    """Build the route section for one workflow step.

    ``job_kind`` is ``opt`` for the ground-state pre-optimisation step or
    ``spectrum`` for the step that writes the final output consumed by
    Multiwfn.
    """
    kind = get_spectrum_kind(kind_key)
    method = _clean_theory(theory)
    try:
        nstates = max(1, int(nstates))
    except (TypeError, ValueError):
        raise ValueError("激发态数量必须是正整数")
    solvent = (solvent or "").strip()
    solvent_part = ""
    if solvent:
        solvent_part = " SCRF=(Solvent=%s)" % solvent

    if kind.electronic:
        if kind.workflow == "fluorescence":
            if job_kind == "excited_opt":
                route = "%s TD=(NStates=%d,Root=1) Opt=(MaxCycles=100)%s" % (
                    method, nstates, solvent_part)
            else:
                route = "%s Opt=(MaxCycles=100)%s" % (method, solvent_part)
        elif kind.workflow == "phosphorescence":
            if job_kind == "triplet_td":
                route = "%s TD=(NStates=%d,Triplet)%s" % (
                    method, nstates, solvent_part)
            elif job_kind == "reference_stable":
                route = "%s Stable=Opt%s" % (method, solvent_part)
            else:
                route = "%s Opt=(MaxCycles=100)%s" % (method, solvent_part)
        elif job_kind == "opt":
            route = "%s Opt%s" % (method, solvent_part)
        else:
            route = "%s TD=(NStates=%d)%s" % (method, nstates, solvent_part)
    else:
        opt_part = "Opt " if optimize else ""
        route = "%s %s%s%s" % (
            method, opt_part, kind.frequency_keyword, solvent_part)
    return "#P " + re.sub(r"\s+", " ", route).strip()


def validate_atoms(atoms):
    if not atoms:
        raise ValueError("没有可计算的分子结构")
    for index, atom in enumerate(atoms, 1):
        if len(atom) < 4:
            raise ValueError("第 %d 个原子的数据格式不完整" % index)
        try:
            float(atom[3][0])
            float(atom[3][1])
            float(atom[3][2])
        except (TypeError, ValueError, IndexError):
            raise ValueError("第 %d 个原子的坐标无效" % index)
    return atoms


def parse_last_geometry(log_path):
    """Read the last complete Gaussian orientation table as atom tuples."""
    if not log_path or not os.path.isfile(log_path):
        return []
    with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()

    def read_orientation(start):
        header = -1
        for index in range(start + 1, min(start + 20, len(lines))):
            text = lines[index].strip()
            if "Center" in text and "Atomic" in text and "Coordinates" in text:
                header = index
                break
        if header < 0:
            return []
        rows = []
        in_rows = False
        for raw in lines[header + 1:]:
            text = raw.strip()
            if not text:
                if in_rows:
                    break
                continue
            if set(text) <= {"-"}:
                if in_rows:
                    break
                in_rows = True
                continue
            if not in_rows:
                continue
            fields = text.split()
            if len(fields) < 6:
                break
            try:
                atom_index = int(fields[0])
                atomic_number = int(fields[1])
                xyz = tuple(float(value) for value in fields[3:6])
            except (TypeError, ValueError):
                break
            rows.append((
                atom_index,
                ELEMENT_SYMBOLS.get(atomic_number, "X"),
                atomic_number,
                xyz,
            ))
        return rows

    result = []
    for index, line in enumerate(lines):
        if line.strip() in (
                "Standard orientation:",
                "Input orientation:",
                "Z-Matrix orientation:"):
            parsed = read_orientation(index)
            if parsed:
                result = parsed
    return result


def parse_first_excitation(log_path, triplet_only=False):
    """Return the last first-excitation energy/strength in a Gaussian log."""
    if not log_path or not os.path.isfile(log_path):
        return None
    with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    pattern = re.compile(
        r"Excited State\s+1:\s+([^\n]*?)\s+"
        r"(-?[0-9]+(?:\.[0-9]+)?)\s+eV\s+"
        r"(-?[0-9]+(?:\.[0-9]+)?)\s+nm\s+"
        r"f=\s*(-?[0-9]+(?:\.[0-9]+)?)"
        r"(?:\s+<S\*\*2>=\s*(-?[0-9]+(?:\.[0-9]+)?))?",
        re.IGNORECASE)
    matches = []
    for match in pattern.finditer(text):
        if triplet_only:
            spin_square = (float(match.group(5))
                           if match.group(5) is not None else 0.0)
            if ("triplet" not in match.group(1).lower()
                    and spin_square < 0.5):
                continue
        matches.append({
            "label": match.group(1).strip(),
            "ev": float(match.group(2)),
            "nm": float(match.group(3)),
            "oscillator_strength": float(match.group(4)),
        })
    return matches[-1] if matches else None


def write_transition_file(transitions, path):
    """Write Multiwfn's general energy/strength text input format.

    ``transitions`` is an iterable of ``(energy_eV, strength)`` pairs.
    """
    rows = [(float(energy), float(strength))
            for energy, strength in transitions]
    if not rows:
        raise ValueError("没有可写入的跃迁数据")
    rows.sort(key=lambda row: row[0])
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="ascii", newline="\n") as fh:
        fh.write("%d 1\n" % len(rows))
        for energy, strength in rows:
            fh.write("%16.10f %16.10f\n" % (energy, strength))
    return path


def gaussian_failure_summary(log_path):
    """Return the most useful terminal diagnostic from a Gaussian log."""
    if not log_path or not os.path.isfile(log_path):
        return ""
    try:
        with open(log_path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 20000))
            text = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    checks = (
        ("Number of steps exceeded", "几何优化达到最大循环数"),
        ("Out of guesses", "激发态求解器初猜数量不足"),
        ("Convergence failure", "SCF/电子结构未收敛"),
        ("Operation on file out of range", "Gaussian 文件读写失败"),
        ("Error termination", "Gaussian 异常终止"),
    )
    return "；".join(label for marker, label in checks if marker in text)


def write_gaussian_input(atoms, path, route, charge=0, multiplicity=1,
                         nprocshared=8, mem="8GB", chk_name=None,
                         include_geometry=True, extra_input=""):
    """Write one Gaussian input file and return its absolute path.

    ``include_geometry=False`` is used with ``Geom=Check`` after a ground-state
    optimisation; in that case Gaussian reads the molecular specification from
    the checkpoint file.
    """
    validate_atoms(atoms)
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    stem = _safe_stem(path)
    try:
        nprocshared = max(1, int(nprocshared))
    except (TypeError, ValueError):
        raise ValueError("CPU 核数必须是正整数")
    mem = (mem or "8GB").strip()
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?\s*(?:MB|GB|MW|GW)",
                        mem, flags=re.IGNORECASE):
        raise ValueError("内存应写成 8GB、4000MB 等形式")

    lines = [
        "%%nprocshared=%d" % nprocshared,
        "%%mem=%s" % mem,
        "%%chk=%s" % (chk_name or (stem + ".chk")),
        route,
        "",
        "MolStudio molecular spectrum workflow: %s" % stem,
        "",
        "%d %d" % (int(charge), int(multiplicity)),
    ]
    if include_geometry:
        for _idx, symbol, _atomic_number, xyz in atoms:
            symbol = str(symbol).strip()
            if not symbol or any(ch in symbol for ch in "\r\n "):
                raise ValueError("发现无效的元素符号：%r" % symbol)
            lines.append(" %-2s %16.10f %16.10f %16.10f" %
                         (symbol, float(xyz[0]), float(xyz[1]),
                          float(xyz[2])))
    # The molecule specification always ends with a blank line, including the
    # Geom=Check form where the coordinates themselves live in the checkpoint.
    lines.append("")
    if extra_input:
        lines.extend(str(extra_input).replace("\r\n", "\n").splitlines())
        lines.append("")
    with open(path, "w", encoding="ascii", errors="strict",
              newline="\n") as fh:
        # Gaussian distinguishes a terminated atom row from the blank line that
        # ends the molecule specification: the latter needs one additional
        # newline (otherwise Link 101 reports "End of file in ZSymb").
        fh.write("\n".join(lines) + "\n")
    return path


def prepare_spectrum_jobs(atoms, output_dir, source_name, kind_key, theory,
                          charge=0, multiplicity=1, nstates=20,
                          nprocshared=8, mem="8GB", optimize=True,
                          solvent="", wavelengths=""):
    """Prepare one or two Gaussian jobs for a spectrum workflow."""
    kind = get_spectrum_kind(kind_key)
    if kind.workflow in ("fluorescence", "phosphorescence"):
        raise ValueError(
            "荧光/磷光包含多步几何优化，请通过 run_spectrum_pipeline 运行")
    validate_atoms(atoms)
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    base = _safe_stem(source_name) + "_" + kind.key
    jobs = []

    if kind.electronic and optimize:
        opt_stem = base + "_opt"
        opt_chk = opt_stem + ".chk"
        opt_gjf = os.path.join(output_dir, opt_stem + ".gjf")
        write_gaussian_input(
            atoms, opt_gjf,
            build_gaussian_route(kind.key, theory, "opt", nstates,
                                 optimize=True, solvent=solvent),
            charge, multiplicity, nprocshared, mem, chk_name=opt_chk)
        jobs.append({
            "role": "opt",
            "label": "基态几何优化",
            "gjf": opt_gjf,
            "log": os.path.join(output_dir, opt_stem + ".log"),
            "chk": os.path.join(output_dir, opt_chk),
        })
        spectrum_gjf = os.path.join(output_dir, base + ".gjf")
        spectrum_route = build_gaussian_route(
            kind.key, theory, "spectrum", nstates,
            optimize=False, solvent=solvent) + " Geom=Check Guess=Read"
        write_gaussian_input(
            atoms, spectrum_gjf, spectrum_route, charge, multiplicity,
            nprocshared, mem, chk_name=opt_chk, include_geometry=False)
    else:
        spectrum_gjf = os.path.join(output_dir, base + ".gjf")
        extra = ""
        if kind.key == "roa":
            wave = normalize_wavelengths(wavelengths)
            if not wave:
                raise ValueError("ROA 计算至少需要一个入射波长，例如 532nm")
            extra = " ".join(wave)
        spectrum_route = build_gaussian_route(
            kind.key, theory, "spectrum", nstates,
            optimize=optimize, solvent=solvent)
        write_gaussian_input(
            atoms, spectrum_gjf, spectrum_route, charge, multiplicity,
            nprocshared, mem, extra_input=extra)

    spectrum_log = os.path.join(output_dir, base + ".log")
    jobs.append({
        "role": "spectrum",
        "label": "光谱计算",
        "gjf": spectrum_gjf,
        "log": spectrum_log,
        "chk": os.path.join(output_dir, base + ".chk"),
    })
    return jobs


def parse_spectrum_curve(path):
    """Read Multiwfn's ``spectrum_curve.txt`` as ``[(x, y), ...]``."""
    points = []
    if not path or not os.path.isfile(path):
        return points
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            fields = line.strip().replace("D", "E").replace("d", "e").split()
            if len(fields) < 2:
                continue
            try:
                x, y = float(fields[0]), float(fields[1])
            except ValueError:
                continue
            points.append((x, y))
    return points


def parse_spectrum_lines(path):
    """Read discrete transition bars from Multiwfn's ``spectrum_line.txt``.

    Multiwfn writes each bar as three points (zero, intensity, zero).  Grouping
    consecutive points at the same x keeps this stable across versions.
    """
    points = parse_spectrum_curve(path)
    bars = []
    for x, y in points:
        if bars and abs(bars[-1][0] - x) < 1e-9:
            if abs(y) > abs(bars[-1][1]):
                bars[-1] = (x, y)
        else:
            bars.append((x, y))
    return [point for point in bars if abs(point[1]) > 1e-14]


def multiwfn_plot_sequence(kind_key, fwhm=None, frequency_scale=1.0,
                           x_range="", ecd_representation="velocity",
                           roa_wavelengths="", roa_wavelength_index=1,
                           nstates=20, available_wavelengths=None):
    """Return the stdin sequence for Multiwfn main function 11.

    A leading blank line is required by recent Multiwfn builds when the input
    file is supplied as a command-line argument.  Without it, ``11`` is read by
    the startup screen and the batch workflow silently lands in the wrong menu.
    """
    kind = get_spectrum_kind(kind_key)
    seq = ["", "11", kind.multiwfn_menu]
    if kind.key == "ecd":
        seq.append("2" if ecd_representation != "length" else "1")
    elif kind.key == "roa":
        wave = normalize_wavelengths(roa_wavelengths)
        available = [float(v) for v in (available_wavelengths or [])]
        try:
            requested = max(1, int(roa_wavelength_index))
        except (TypeError, ValueError):
            requested = 1
        target = None
        if wave:
            chosen = wave[min(requested, len(wave)) - 1]
            try:
                target = float(chosen[:-2])   # "532nm" -> 532.0
            except ValueError:
                target = None
        if available and target is not None:
            index = min(range(len(available)),
                        key=lambda i: abs(available[i] - target)) + 1
        elif available:
            index = min(requested, len(available))
        elif len(wave) > 1:
            index = min(requested, len(wave))
        else:
            index = 1
        # Multiwfn asks "Load data for which frequency?" unconditionally,
        # even for a single wavelength.  Omitting this index shifts every
        # later command by one and ends in "end-of-file during read".
        seq.append(str(index))
        # Gaussian output contains SCP(180), SCP(90) and DCP(180); the
        # reference workflow (sobereva.com/224 sec. 5.6) uses ROA SCP(180).
        seq.append("2")
    elif kind.key == "fluorescence":
        # From the S1-optimisation output, retain only the S1 oscillator
        # strength.  Multiwfn's option 20 clears all higher excited states.
        try:
            count = max(1, int(nstates))
        except (TypeError, ValueError):
            raise ValueError("激发态数量必须是正整数")
        if count > 1:
            seq.extend(["20", "2-%d" % count if count > 2 else "2", "0"])
    if not kind.electronic:
        try:
            scale = float(frequency_scale)
        except (TypeError, ValueError):
            raise ValueError("频率校正因子必须是数字")
        if scale <= 0:
            raise ValueError("频率校正因子必须大于 0")
        if abs(scale - 1.0) > 1e-12:
            # 14 -> all modes (blank line) -> factor.
            seq.extend(["14", "", "%.10g" % scale])
    if fwhm not in (None, ""):
        try:
            fwhm_value = float(fwhm)
        except (TypeError, ValueError):
            raise ValueError("FWHM 必须是数字")
        if fwhm_value <= 0:
            raise ValueError("FWHM 必须大于 0")
        seq.extend(["8", "%.10g" % fwhm_value])
    if x_range:
        range_text = str(x_range).strip()
        parts = [part for part in re.split(r"[\s,]+", range_text) if part]
        if len(parts) != 3:
            raise ValueError("横轴范围应写成 起点,终点,步长")
        try:
            lower, upper, step = [float(part) for part in parts]
        except ValueError:
            raise ValueError("横轴范围应写成三个数字：起点,终点,步长")
        if step == 0 or lower == upper:
            raise ValueError("横轴范围的起点、终点和步长无效")
        seq.extend(["3", range_text])
    # Export curve and discrete-line data.  MolStudio renders the exported
    # curve so the preview remains deterministic even when Multiwfn is newer.
    seq.append("2")
    # Also ask Multiwfn itself to save its native plot.  Option 1 writes
    # dislin.png without opening the interactive image window.
    seq.append("1")
    return "\n".join(seq) + "\n"


def _kill_process_tree(proc):
    if proc is None or proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=20)
        else:
            proc.kill()
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def _ascii_existing_path(path):
    """Resolve a Windows 8.3 path when the user's folder contains non-ASCII."""
    if os.name != "nt" or not any(ord(ch) > 127 for ch in str(path)):
        return path
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(32768)
        length = ctypes.windll.kernel32.GetShortPathNameW(
            os.path.abspath(path), buf, len(buf))
        if length and os.path.isdir(buf.value):
            return buf.value
    except Exception:  # noqa: BLE001
        pass
    return path


def _run_multiwfn(exe, input_file, sequence, workdir, on_log=None,
                  cancel=None, timeout=600):
    """Run Multiwfn while streaming stdout and allowing cooperative cancel."""
    creationflags = 0
    if sys.platform == "win32":
        creationflags = (subprocess.CREATE_NO_WINDOW |
                         subprocess.CREATE_NEW_PROCESS_GROUP)
    proc = subprocess.Popen(
        [exe, os.path.basename(input_file)], cwd=workdir,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, universal_newlines=True,
        encoding="utf-8", errors="replace",
        creationflags=creationflags)
    output = []

    def reader():
        try:
            for line in proc.stdout:
                output.append(line)
                if on_log:
                    on_log(line.rstrip())
        except Exception:  # noqa: BLE001
            pass

    reader_thread = threading.Thread(target=reader, daemon=True)
    reader_thread.start()
    try:
        proc.stdin.write(sequence)
        proc.stdin.flush()
        proc.stdin.close()
    except (BrokenPipeError, OSError):
        pass
    started = time.time()
    try:
        while proc.poll() is None:
            if cancel is not None and cancel():
                _kill_process_tree(proc)
                raise SpectrumCancelled("已停止 Multiwfn")
            if timeout and time.time() - started > timeout:
                _kill_process_tree(proc)
                raise SpectrumWorkflowError("Multiwfn 运行超时")
            time.sleep(0.15)
    finally:
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            _kill_process_tree(proc)
        reader_thread.join(timeout=5)
    return "".join(output)


def _render_curve(curve, kind, output_path, transitions=None, title=""):
    """Render Multiwfn's exported curve with Matplotlib (Agg backend).

    The canvas is 16:9 so it fills the (now stretchable) preview area without
    leaving tall empty bands.  Styling stays flat: solid fills, light grid,
    dark-blue curve, amber transition sticks and a marked peak.
    """
    global _LAST_RENDER_LIMITS, _LAST_RENDER_XLIM
    try:
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
    except Exception as exc:  # noqa: BLE001
        raise SpectrumWorkflowError("无法加载 matplotlib：%s" % exc)
    if not curve:
        raise SpectrumWorkflowError("Multiwfn 没有导出可绘制的光谱曲线")

    xs = [p[0] for p in curve]
    ys = [p[1] for p in curve]
    if kind.workflow == "phosphorescence":
        max_abs = max((abs(value) for value in ys), default=0.0)
        if max_abs > 0:
            ys = [value / max_abs for value in ys]
    transitions = list(transitions or [])
    x_lo, x_hi = min(xs), max(xs)
    # 虚频（负波数）或横轴范围外的跃迁会把坐标轴撑大，必须过滤掉。
    kept_all = [(point[0], point[1]) for point in transitions
                if x_lo <= point[0] <= x_hi]
    # 有右侧跃迁强度轴时多留一点边距，避免 ylabel 被画布裁掉。
    right_margin = 0.90 if kept_all else 0.96

    fig = Figure(figsize=(10.4, 5.85), dpi=180, facecolor="white")
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    fig.subplots_adjust(left=0.095, right=right_margin,
                        top=0.87, bottom=0.14)
    ax.set_axisbelow(True)
    ax.set_facecolor("white")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#94A3B8")
        ax.spines[side].set_linewidth(1.1)
    ax.tick_params(axis="both", which="major", colors="#334155",
                   labelsize=11, length=5, width=1.0, direction="out")
    ax.grid(True, which="major", color="#E2E8F0", linewidth=0.9,
            linestyle="-", alpha=0.9)

    ax.plot(xs, ys, color="#1565C0", linewidth=2.4,
            solid_capstyle="round", label="Broadened spectrum", zorder=3)
    ax.fill_between(xs, ys, 0, color="#90CAF9", alpha=0.28,
                    linewidth=0, zorder=2)
    ax.axhline(0, color="#64748B", linewidth=0.9, alpha=0.7, zorder=2)

    x_unit = "nm" if kind.x_unit == "nm" else "cm$^{-1}$"
    if ys:
        peak = max(range(len(ys)), key=lambda i: abs(ys[i]))
        px, py = xs[peak], ys[peak]
        if abs(py) > 1e-12:
            ax.scatter([px], [py], s=46, color="#C62828",
                       edgecolors="white", linewidths=1.2, zorder=5)
            ax.annotate("peak  %.0f %s" % (px, x_unit),
                        xy=(px, py), xytext=(0, 15),
                        textcoords="offset points", ha="center",
                        va="bottom", fontsize=10.5, color="#0F172A",
                        bbox=dict(boxstyle="round,pad=0.35",
                                  facecolor="white",
                                  edgecolor="#CBD5E1", linewidth=0.8),
                        zorder=6)

    right = None
    if kept_all:
        tx = [point[0] for point in kept_all]
        ty = [point[1] for point in kept_all]
        right = ax.twinx()
        right.vlines(tx, 0, ty, color="#F59E0B", linewidth=1.2,
                     alpha=0.8, label="Discrete transitions", zorder=1)
        right.axhline(0, color="#94A3B8", linewidth=0.5, alpha=0.6)
        right.set_ylabel("Transition intensity", color="#B45309",
                         fontsize=12, labelpad=10)
        right.tick_params(axis="y", colors="#B45309", labelsize=10)
        right.spines["top"].set_visible(False)
        right.spines["left"].set_visible(False)
        for side in ("right", "bottom"):
            right.spines[side].set_color("#94A3B8")
            right.spines[side].set_linewidth(1.0)
        lo, hi = min(0.0, min(ty)), max(0.0, max(ty))
        pad = (hi - lo) * 0.08 or 1.0
        right.set_ylim(lo - pad, hi + pad)

    # 横轴范围与方向都跟随 Multiwfn 导出的曲线：振动谱是 4000 -> 0 cm^-1
    # （左高右低，红外/拉曼惯例），电子谱是升序 nm。强制 min->max 会把
    # 振动谱左右镜像，也会忽略用户在 Multiwfn 选项 3 里设定的反向范围。
    if xs[0] != xs[-1]:
        ax.set_xlim(xs[0], xs[-1])
    else:
        ax.set_xlim(min(xs), max(xs))
    _LAST_RENDER_XLIM = tuple(ax.get_xlim())
    _LAST_RENDER_LIMITS = (min(xs), max(xs), len(transitions),
                           len(transitions) - len(
                               [p for p in transitions
                                if min(xs) <= p[0] <= max(xs)]))
    ax.set_xlabel("Wavelength / nm" if kind.x_unit == "nm"
                  else "Wavenumber / cm$^{-1}$",
                  fontsize=13, color="#0F172A", labelpad=10)
    ax.set_ylabel(kind.y_unit, fontsize=13, color="#0F172A", labelpad=10)
    heading = title or ("%s spectrum" % kind.name)
    # DejaVu Sans (the Agg default) has no CJK glyphs; a Chinese spectrum
    # name would render as tofu boxes, so fall back to the ASCII kind key.
    if any(ord(ch) > 127 for ch in heading):
        heading = "%s spectrum" % kind.key.upper()
    ax.set_title(heading, fontsize=16, fontweight="bold",
                 color="#0F172A", pad=16)

    handles, labels = ax.get_legend_handles_labels()
    if right is not None:
        h2, l2 = right.get_legend_handles_labels()
        handles += h2
        labels += l2
    if handles:
        legend = ax.legend(handles, labels, loc="upper right",
                           fontsize=10.5, frameon=True, fancybox=True)
        legend.get_frame().set_facecolor("white")
        legend.get_frame().set_edgecolor("#E2E8F0")
        legend.get_frame().set_linewidth(0.9)
        for text in legend.get_texts():
            text.set_color("#334155")

    fig.savefig(output_path, facecolor="white", dpi=180)
    return output_path


def draw_multiwfn_spectrum(log_path, multiwfn_exe, work_dir, kind_key,
                           fwhm=None, frequency_scale=1.0, x_range="",
                           ecd_representation="velocity",
                           roa_wavelengths="", roa_wavelength_index=1,
                           nstates=20, on_log=None, cancel=None, timeout=600):
    """Ask Multiwfn to broaden/export a spectrum and render its curve."""
    kind = get_spectrum_kind(kind_key)
    log_path = os.path.abspath(log_path)
    work_dir = os.path.abspath(work_dir or os.path.dirname(log_path))
    if not os.path.isfile(log_path):
        raise SpectrumWorkflowError("找不到 Gaussian 输出文件：%s" % log_path)
    if not multiwfn_exe or not os.path.isfile(multiwfn_exe):
        raise SpectrumWorkflowError(
            "找不到 Multiwfn.exe，请先在 ⚙️ 路径设置中配置")
    os.makedirs(work_dir, exist_ok=True)

    curve_path = os.path.join(work_dir, "spectrum_curve.txt")
    line_path = os.path.join(work_dir, "spectrum_line.txt")
    for stale in (curve_path, line_path):
        try:
            os.remove(stale)
        except FileNotFoundError:
            pass

    available_wavelengths = (
        parse_roa_wavelengths(log_path) if kind.key == "roa" else [])
    sequence = multiwfn_plot_sequence(
        kind.key, fwhm=fwhm, frequency_scale=frequency_scale,
        x_range=x_range, ecd_representation=ecd_representation,
        roa_wavelengths=roa_wavelengths,
        roa_wavelength_index=roa_wavelength_index, nstates=nstates,
        available_wavelengths=available_wavelengths)
    if on_log:
        on_log("Multiwfn 菜单：11 → %s → 2（导出展宽光谱数据）" %
               kind.multiwfn_menu)
    # Recent Multiwfn builds still have trouble with non-ASCII file names.
    # Run from a short ASCII temp directory and copy the numerical/text
    # results back, while keeping the user-visible plot and logs in outdir.
    temp_root = _ascii_existing_path(tempfile.mkdtemp(
        prefix="molstudio_spectrum_"))
    local_name = ("input.txt" if kind.workflow == "phosphorescence"
                  else "input.log")
    local_log = os.path.join(temp_root, local_name)
    try:
        shutil.copy2(log_path, local_log)
        text = _run_multiwfn(
            multiwfn_exe, local_log, sequence, temp_root,
            on_log=on_log, cancel=cancel, timeout=timeout)
        for candidate in ("spectrum_curve.txt", "spectrum_line.txt"):
            src = os.path.join(temp_root, candidate)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(work_dir, candidate))
        native_src = os.path.join(temp_root, "dislin.png")
        native_plot = os.path.join(
            work_dir, "Multiwfn_%s_spectrum.png" % kind.key)
        if os.path.isfile(native_src):
            shutil.copy2(native_src, native_plot)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    mw_log = os.path.join(work_dir, "_multiwfn_spectrum.log")
    try:
        with open(mw_log, "w", encoding="utf-8", errors="replace") as fh:
            fh.write(text)
    except OSError:
        mw_log = ""

    curve = parse_spectrum_curve(curve_path)
    if not curve:
        hint = text[-1200:].strip() if text else "Multiwfn 无输出"
        raise SpectrumWorkflowError(
            "Multiwfn 未能导出光谱曲线。请确认输出文件包含该谱型所需数据。"
            "\n\n%s" % hint)
    plot_path = os.path.join(work_dir, "MolStudio_%s_spectrum.png" % kind.key)
    transitions = parse_spectrum_lines(
        os.path.join(work_dir, "spectrum_line.txt"))
    plot_title = ("Phosphorescence (non-SOC, normalised)"
                  if kind.workflow == "phosphorescence"
                  else ("Fluorescence" if kind.workflow == "fluorescence"
                        else ""))
    _render_curve(
        curve, kind, plot_path, transitions=transitions, title=plot_title)
    return {
        "kind": kind.key,
        "curve": curve,
        "transitions": transitions,
        "curve_path": curve_path,
        "line_path": line_path if os.path.isfile(line_path) else "",
        "plot_path": plot_path,
        "multiwfn_plot_path": (native_plot
                               if os.path.isfile(native_plot) else ""),
        "multiwfn_log": mw_log,
        "multiwfn_output": text,
        "sequence": sequence,
        "normalized": kind.workflow == "phosphorescence",
    }


def _run_emission_chain(atoms, source_name, output_dir, kind_key, theory,
                        gaussian_exe, charge, multiplicity, nstates,
                        nprocshared, mem, optimize, solvent, check_cancel,
                        emit_stage, emit_log, cancel):
    """Run the geometry stages required by fluorescence/phosphorescence."""
    kind = get_spectrum_kind(kind_key)
    base = _safe_stem(source_name) + "_" + kind.key
    current_atoms = validate_atoms(atoms)
    jobs = []
    total = (1 if optimize else 0) + (
        1 if kind.workflow == "fluorescence" else 3)
    sequence_index = 0

    def execute(suffix, label, route, job_charge, job_multiplicity,
                chk_name=None, include_geometry=True):
        nonlocal current_atoms, sequence_index
        check_cancel()
        sequence_index += 1
        stem = base + "_" + suffix
        gjf = os.path.join(output_dir, stem + ".gjf")
        log = os.path.join(output_dir, stem + ".log")
        chk = (os.path.abspath(chk_name) if chk_name
               else os.path.join(output_dir, stem + ".chk"))
        write_gaussian_input(
            current_atoms, gjf, route, job_charge, job_multiplicity,
            nprocshared, mem, chk_name=os.path.basename(chk),
            include_geometry=include_geometry)
        job = {
            "role": suffix,
            "label": label,
            "gjf": gjf,
            "log": log,
            "chk": chk,
        }
        jobs.append(job)
        lo = 8 + int(62 * (sequence_index - 1) / max(1, total))
        hi = 8 + int(62 * sequence_index / max(1, total))
        emit_stage(lo, "Gaussian：%s（%s）" %
                   (label, os.path.basename(gjf)))
        emit_log("=== %s：%s ===" % (label, os.path.basename(gjf)))
        result = run_gaussian(
            gjf, gaussian_exe, log_path=log, on_line=emit_log, cancel=cancel)
        if result.cancelled:
            raise SpectrumCancelled("已停止 Gaussian 计算")
        if not result.ok:
            hint = gaussian_failure_summary(result.log_path)
            raise SpectrumWorkflowError(
                "%s失败：%s%s\n日志：%s" %
                (label, result.error,
                 ("（%s）" % hint if hint else ""), result.log_path))
        updated_atoms = parse_last_geometry(result.log_path)
        if not updated_atoms:
            raise SpectrumWorkflowError(
                "%s完成，但未能从日志读取最终几何结构" % label)
        current_atoms = updated_atoms
        emit_stage(hi, "%s完成" % label)
        return os.path.abspath(result.log_path)

    if optimize:
        execute(
            "ground_opt", "基态几何优化",
            build_gaussian_route(
                kind.key, theory, "ground_opt", nstates=nstates,
                optimize=False, solvent=solvent),
            charge, multiplicity)

    if kind.workflow == "fluorescence":
        final_log = execute(
            "s1_opt", "S1 激发态几何优化",
            build_gaussian_route(
                kind.key, theory, "excited_opt", nstates=nstates,
                optimize=False, solvent=solvent),
            charge, multiplicity)
        excitation = parse_first_excitation(final_log)
        if not excitation:
            raise SpectrumWorkflowError(
                "S1 优化正常结束，但日志中没有找到第一激发态能量")
        if excitation["oscillator_strength"] <= 1e-8:
            emit_log("S1 振子强度为 0，荧光跃迁很弱；请在报告中说明这是暗态")
        else:
            emit_log("S1 垂直发射：%.6f eV（%.2f nm），f=%.6g" %
                     (excitation["ev"], excitation["nm"],
                      excitation["oscillator_strength"]))
        return final_log, jobs, excitation

    # T1 is a triplet state even when the S0 reference is a closed-shell
    # singlet.  The final TD calculation is then performed from a singlet
    # reference at the T1 geometry with TD=(...,Triplet).
    execute(
        "t1_opt", "T1 激发态几何优化",
        build_gaussian_route(
            kind.key, theory, "triplet_opt", nstates=nstates,
            optimize=False, solvent=solvent),
        charge, 3)
    execute(
        "t1_s0_ref", "T1 结构上的基态参考波函数",
        build_gaussian_route(
            kind.key, theory, "reference_stable", nstates=nstates,
            optimize=False, solvent=solvent),
        charge, 1)
    reference_chk = jobs[-1]["chk"]
    final_log = execute(
        "t1_td", "T1 位置三重态垂直发射",
        build_gaussian_route(
            kind.key, theory, "triplet_td", nstates=nstates,
            optimize=False, solvent=solvent) + " Geom=Check Guess=Read",
        charge, 1, chk_name=reference_chk, include_geometry=False)
    excitation = parse_first_excitation(final_log, triplet_only=True)
    if not excitation:
        raise SpectrumWorkflowError(
            "T1 垂直发射计算正常结束，但日志中没有找到三重态激发能")
    if excitation["ev"] <= 0 or excitation["nm"] <= 0:
        raise SpectrumWorkflowError(
            "三重态垂直发射能得到非正激发能；参考波函数可能不是基态。"
            "建议检查电荷/自旋多重度，并对 T1 结构做 stable=opt 后重算")
    emit_log("磷光垂直发射能：%.6f eV（%.2f nm）；普通 TDDFT 不含 SOC，"
             "曲线强度按归一化处理" %
             (excitation["ev"], excitation["nm"]))
    return final_log, jobs, excitation


def run_spectrum_pipeline(atoms, source_name, output_dir, kind_key, theory,
                          gaussian_exe, multiwfn_exe, charge=0,
                          multiplicity=1, nstates=20, nprocshared=8,
                          mem="8GB", optimize=True, solvent="",
                          wavelengths="", fwhm=None, frequency_scale=1.0,
                          x_range="", ecd_representation="velocity",
                          roa_wavelength_index=1, existing_log="",
                          on_stage=None, on_log=None, cancel=None,
                          timeout=1800):
    """Run Gaussian (optional) and Multiwfn as one spectrum workflow.

    ``existing_log`` skips the Gaussian stage and re-plots an existing output.
    The function is synchronous and intended for a QThread in the UI.
    """
    kind = get_spectrum_kind(kind_key)
    emit_stage = on_stage or (lambda _pct, _text: None)
    emit_log = on_log or (lambda _text: None)
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    def check_cancel():
        if cancel is not None and cancel():
            raise SpectrumCancelled("已停止光谱工作流")

    check_cancel()
    # Validate plotting inputs before launching an expensive Gaussian job.
    multiwfn_plot_sequence(
        kind.key, fwhm=fwhm, frequency_scale=frequency_scale,
        x_range=x_range, ecd_representation=ecd_representation,
        roa_wavelengths=wavelengths,
        roa_wavelength_index=roa_wavelength_index, nstates=nstates)
    final_log = os.path.abspath(existing_log) if existing_log else ""
    jobs = []
    emission_info = None
    if not final_log:
        if not gaussian_exe or not os.path.isfile(gaussian_exe):
            raise SpectrumWorkflowError(
                "找不到 g16.exe，请先在 ⚙️ 路径设置中配置 Gaussian")
        output_dir = _new_run_directory(output_dir, source_name, kind.key)
        emit_stage(4, "准备 Gaussian 输入")
        if kind.workflow in ("fluorescence", "phosphorescence"):
            final_log, jobs, emission_info = _run_emission_chain(
                atoms, source_name, output_dir, kind.key, theory,
                gaussian_exe, charge, multiplicity, nstates,
                nprocshared, mem, optimize, solvent, check_cancel,
                emit_stage, emit_log, cancel)
        else:
            jobs = prepare_spectrum_jobs(
                atoms, output_dir, source_name, kind.key, theory,
                charge=charge, multiplicity=multiplicity, nstates=nstates,
                nprocshared=nprocshared, mem=mem, optimize=optimize,
                solvent=solvent, wavelengths=wavelengths)
            for index, job in enumerate(jobs):
                check_cancel()
                lo = 8 + index * (62 // max(1, len(jobs)))
                hi = 8 + (index + 1) * (62 // max(1, len(jobs)))
                emit_stage(lo, "Gaussian：%s（%s）" %
                           (job["label"], os.path.basename(job["gjf"])))
                emit_log("=== %s：%s ===" %
                         (job["label"], os.path.basename(job["gjf"])))
                result = run_gaussian(
                    job["gjf"], gaussian_exe, log_path=job["log"],
                    on_line=emit_log, cancel=cancel)
                if result.cancelled:
                    raise SpectrumCancelled("已停止 Gaussian 计算")
                if not result.ok:
                    hint = gaussian_failure_summary(result.log_path)
                    raise SpectrumWorkflowError(
                        "%s失败：%s%s\n日志：%s" %
                        (job["label"], result.error,
                         ("（%s）" % hint if hint else ""),
                         result.log_path))
                final_log = os.path.abspath(result.log_path)
                emit_stage(hi, "%s完成" % job["label"])
    else:
        if not os.path.isfile(final_log):
            raise SpectrumWorkflowError("找不到已有 Gaussian 输出：%s" %
                                        final_log)
        output_dir = _new_run_directory(output_dir, source_name, kind.key)
        emit_stage(70, "复用已有 Gaussian 输出")
        emit_log("复用已有 Gaussian 输出：%s" % os.path.basename(final_log))
        if kind.workflow == "phosphorescence":
            emission_info = parse_first_excitation(
                final_log, triplet_only=True)
            if not emission_info:
                raise SpectrumWorkflowError(
                    "已有输出中没有找到三重态激发能；请提供 T1 位置 TD"
                    "(...,Triplet) 的正常 Gaussian 输出")
            emit_log("复用的磷光垂直发射能：%.6f eV（%.2f nm）" %
                     (emission_info["ev"], emission_info["nm"]))
        elif kind.workflow == "fluorescence":
            emission_info = parse_first_excitation(final_log)
            if not emission_info:
                raise SpectrumWorkflowError(
                    "已有输出中没有找到第一激发态能量；请提供 S1 几何优化或"
                    " S1 位置 TD 的正常 Gaussian 输出")
            emit_log("复用的 S1 垂直发射：%.6f eV（%.2f nm），f=%.6g" %
                     (emission_info["ev"], emission_info["nm"],
                      emission_info["oscillator_strength"]))

    check_cancel()
    emit_stage(74, "调用 Multiwfn：展宽并导出光谱")
    plot_input = final_log
    if kind.workflow == "phosphorescence":
        transition_path = os.path.join(
            output_dir, "phosphorescence_transitions.txt")
        write_transition_file(
            [(emission_info["ev"], 1.0)], transition_path)
        plot_input = transition_path
    drawn = draw_multiwfn_spectrum(
        plot_input, multiwfn_exe, output_dir, kind.key,
        fwhm=fwhm, frequency_scale=frequency_scale, x_range=x_range,
        ecd_representation=ecd_representation,
        roa_wavelengths=wavelengths,
        roa_wavelength_index=roa_wavelength_index,
        nstates=nstates, on_log=emit_log, cancel=cancel, timeout=timeout)
    emit_stage(100, "%s 光谱完成" % kind.name)
    drawn.update({
        "log_path": final_log,
        "output_dir": output_dir,
        "jobs": jobs,
        "emission": emission_info,
    })
    return drawn


__all__ = [
    "SPECTRUM_KINDS",
    "SpectrumKind",
    "SpectrumCancelled",
    "SpectrumWorkflowError",
    "get_spectrum_kind",
    "normalize_wavelengths",
    "parse_last_geometry",
    "parse_first_excitation",
    "write_transition_file",
    "gaussian_failure_summary",
    "build_gaussian_route",
    "write_gaussian_input",
    "prepare_spectrum_jobs",
    "parse_spectrum_curve",
    "parse_spectrum_lines",
    "multiwfn_plot_sequence",
    "draw_multiwfn_spectrum",
    "run_spectrum_pipeline",
]
