#!/usr/bin/env python3
"""Pure Python Gaussian External interface for the xTB program.

The script can be called directly by Gaussian's External keyword:

    gau_xtb.py layer InputFile OutputFile MsgFile FChkFile MatElFile

It also provides small compatibility subcommands for the original helper
programs:

    gau_xtb.py genxyz InputFileOrMolTmp [mol.xyz]
    gau_xtb.py extderi OutputFile NAtoms Derivs [--workdir DIR]

本文件移植自 xTBridge（https://github.com/houcheng-gxnu/xTBridge，MIT
License, Copyright (c) 2026 houcheng-gxnu）的 ``xtbridge/src/xtbridge/gau_xtb.py``，
未改动协议实现，仅随 MolStudio 一起分发。它必须保持**独立可运行**：Gaussian
会用外部 python 直接启动它，因此这里不能 import 任何 molstudio 模块。

环境变量（由 MolStudio 的高斯页在运行时注入）::

    GAU_XTB_COMMAND   xtb.exe 路径
    GAU_XTB_METHOD    方法/数值参数（如 "--gfn 2 --alpb water"）
    GAU_XTB_GFN       兼容旧写法，只给 GFN 级别
    GAU_XTB_THREADS   并行线程数
    GAU_XTB_ARGS      额外 xtb 参数
    GAU_XTB_TIMEOUT   超时秒数
    GAU_XTB_TMPDIR    临时目录
    GAU_XTB_KEEP_WORKDIR  设为 1 保留工作目录
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


BOHR_TO_ANGSTROM = 0.529177249

PERIODIC_SYMBOLS = [
    "Bq",
    "H",
    "He",
    "Li",
    "Be",
    "B",
    "C",
    "N",
    "O",
    "F",
    "Ne",
    "Na",
    "Mg",
    "Al",
    "Si",
    "P",
    "S",
    "Cl",
    "Ar",
    "K",
    "Ca",
    "Sc",
    "Ti",
    "V",
    "Cr",
    "Mn",
    "Fe",
    "Co",
    "Ni",
    "Cu",
    "Zn",
    "Ga",
    "Ge",
    "As",
    "Se",
    "Br",
    "Kr",
    "Rb",
    "Sr",
    "Y",
    "Zr",
    "Nb",
    "Mo",
    "Tc",
    "Ru",
    "Rh",
    "Pd",
    "Ag",
    "Cd",
    "In",
    "Sn",
    "Sb",
    "Te",
    "I",
    "Xe",
    "Cs",
    "Ba",
    "La",
    "Ce",
    "Pr",
    "Nd",
    "Pm",
    "Sm",
    "Eu",
    "Gd",
    "Tb",
    "Dy",
    "Ho",
    "Er",
    "Tm",
    "Yb",
    "Lu",
    "Hf",
    "Ta",
    "W",
    "Re",
    "Os",
    "Ir",
    "Pt",
    "Au",
    "Hg",
    "Tl",
    "Pb",
    "Bi",
    "Po",
    "At",
    "Rn",
    "Fr",
    "Ra",
    "Ac",
    "Th",
    "Pa",
    "U",
    "Np",
    "Pu",
    "Am",
    "Cm",
    "Bk",
    "Cf",
    "Es",
    "Fm",
    "Md",
    "No",
    "Lr",
    "Rf",
    "Db",
    "Sg",
    "Bh",
    "Hs",
    "Mt",
    "Ds",
    "Rg",
    "Cn",
    "Nh",
    "Fl",
    "Mc",
    "Lv",
    "Ts",
    "Og",
]

FLOAT_RE = re.compile(
    r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"
)

GENERATED_FILES = [
    "charges",
    "energy",
    "xtbrestart",
    "gradient",
    "hessian",
    "xtbout",
    "mol.xyz",
    "tmpxx",
    "vibspectrum",
    "xtb_normalmodes",
    "g98_canmode.out",
    "g98.out",
    "wbo",
    "xtbhess.coord",
    ".tmpxtbmodef",
    ".engrad",
    "xtbtopo.mol",
    "xtbhess.xyz",
]


class GauXtbError(RuntimeError):
    """Raised for user-facing interface errors."""


@dataclass(frozen=True)
class Atom:
    atomic_number: int
    x_bohr: float
    y_bohr: float
    z_bohr: float

    @property
    def symbol(self) -> str:
        try:
            symbol = PERIODIC_SYMBOLS[self.atomic_number]
        except IndexError as exc:
            raise GauXtbError(
                f"Unsupported atomic number {self.atomic_number}"
            ) from exc
        if symbol == "Bq":
            raise GauXtbError("xTB cannot calculate Gaussian ghost atoms (atomic number 0)")
        return symbol


@dataclass(frozen=True)
class GaussianExternalInput:
    natoms: int
    derivs: int
    charge: int
    multiplicity: int
    atoms: list[Atom]

    @property
    def uhf(self) -> int:
        return self.multiplicity - 1


def parse_float(text: str) -> float:
    return float(text.replace("D", "E").replace("d", "e"))


def parse_gaussian_external_input(path: Path) -> GaussianExternalInput:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines:
        raise GauXtbError(f"Gaussian External input is empty: {path}")

    header = lines[0].split()
    if len(header) < 4:
        raise GauXtbError(
            f"First line must contain NAtoms, Derivs, Charge, Multiplicity: {path}"
        )
    try:
        natoms = int(header[0])
        derivs = int(header[1])
        charge = int(float(header[2]))
        multiplicity = int(float(header[3]))
    except ValueError as exc:
        raise GauXtbError(f"Invalid Gaussian External header in {path}") from exc

    if natoms < 1:
        raise GauXtbError(f"NAtoms must be positive in {path}")
    if derivs not in (0, 1, 2):
        raise GauXtbError(f"Unsupported derivative level {derivs}; expected 0, 1, or 2")
    if multiplicity < 1:
        raise GauXtbError(f"Multiplicity must be positive in {path}")
    if len(lines) < natoms + 1:
        raise GauXtbError(f"Expected {natoms} atom lines in {path}")

    atoms: list[Atom] = []
    for idx, line in enumerate(lines[1 : natoms + 1], start=1):
        fields = line.split()
        if len(fields) < 4:
            raise GauXtbError(f"Atom line {idx} has fewer than 4 fields in {path}")
        try:
            atomic_number = int(float(fields[0]))
            x_bohr = parse_float(fields[1])
            y_bohr = parse_float(fields[2])
            z_bohr = parse_float(fields[3])
        except ValueError as exc:
            raise GauXtbError(f"Invalid atom line {idx} in {path}: {line}") from exc
        atoms.append(Atom(atomic_number, x_bohr, y_bohr, z_bohr))

    return GaussianExternalInput(natoms, derivs, charge, multiplicity, atoms)


def parse_mol_tmp(path: Path) -> GaussianExternalInput:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines:
        raise GauXtbError(f"mol.tmp input is empty: {path}")
    try:
        natoms = int(lines[0].split()[0])
    except (IndexError, ValueError) as exc:
        raise GauXtbError(f"Invalid mol.tmp atom count in {path}") from exc
    if len(lines) < natoms + 2:
        raise GauXtbError(f"Expected {natoms} atom lines in mol.tmp file {path}")

    atoms: list[Atom] = []
    for idx, line in enumerate(lines[2 : natoms + 2], start=1):
        fields = line.split()
        if len(fields) < 4:
            raise GauXtbError(f"mol.tmp atom line {idx} has fewer than 4 fields")
        try:
            atoms.append(
                Atom(
                    int(float(fields[0])),
                    parse_float(fields[1]),
                    parse_float(fields[2]),
                    parse_float(fields[3]),
                )
            )
        except ValueError as exc:
            raise GauXtbError(f"Invalid mol.tmp atom line {idx}: {line}") from exc
    return GaussianExternalInput(natoms, 0, 0, 1, atoms)


def parse_genxyz_input(path: Path) -> GaussianExternalInput:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines:
        raise GauXtbError(f"genxyz input is empty: {path}")
    first = lines[0].split()
    if len(first) >= 4:
        return parse_gaussian_external_input(path)
    return parse_mol_tmp(path)


def write_xyz(data: GaussianExternalInput, path: Path) -> None:
    lines = [
        str(data.natoms),
        f"Generated by gau_xtb.py; charge={data.charge} mult={data.multiplicity}",
    ]
    for atom in data.atoms:
        x = atom.x_bohr * BOHR_TO_ANGSTROM
        y = atom.y_bohr * BOHR_TO_ANGSTROM
        z = atom.z_bohr * BOHR_TO_ANGSTROM
        lines.append(f"{atom.symbol:<2s} {x: .12f} {y: .12f} {z: .12f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_energy(xtbout: Path) -> float:
    if not xtbout.exists():
        raise GauXtbError(f"xTB output file does not exist: {xtbout}")
    matches: list[tuple[int, float]] = []
    for line_no, line in enumerate(
        xtbout.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
    ):
        if "total energy" not in line.lower():
            continue
        numbers = FLOAT_RE.findall(line)
        if not numbers:
            continue
        matches.append((line_no, parse_float(numbers[0])))
    if not matches:
        raise GauXtbError(f"Could not find total energy in {xtbout}")
    return matches[-1][1]


def parse_gradient(path: Path, natoms: int) -> list[tuple[float, float, float]]:
    if not path.exists():
        raise GauXtbError(f"xTB gradient file does not exist: {path}")
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) < 2 + 2 * natoms:
        raise GauXtbError(f"xTB gradient file is too short for {natoms} atoms: {path}")
    gradient_lines = lines[2 + natoms : 2 + 2 * natoms]
    gradient: list[tuple[float, float, float]] = []
    for idx, line in enumerate(gradient_lines, start=1):
        fields = line.split()
        if len(fields) < 3:
            raise GauXtbError(f"Gradient line {idx} has fewer than 3 fields in {path}")
        try:
            gradient.append(
                (parse_float(fields[0]), parse_float(fields[1]), parse_float(fields[2]))
            )
        except ValueError as exc:
            raise GauXtbError(f"Invalid gradient line {idx} in {path}: {line}") from exc
    return gradient


def parse_hessian(path: Path, natoms: int) -> list[list[float]]:
    if not path.exists():
        raise GauXtbError(f"xTB hessian file does not exist: {path}")
    dimension = 3 * natoms
    expected = dimension * dimension
    text = path.read_text(encoding="utf-8", errors="replace")
    values: list[float] = []
    for line in text.splitlines()[1:]:
        if line.lstrip().startswith("$"):
            break
        values.extend(parse_float(token) for token in FLOAT_RE.findall(line))
    if len(values) != expected:
        raise GauXtbError(
            f"Expected {expected} Hessian values for {natoms} atoms, found {len(values)}"
        )
    return [
        values[row * dimension : (row + 1) * dimension] for row in range(dimension)
    ]


def gaussian_float(value: float) -> str:
    return f"{value:20.12E}".replace("E", "D")


def write_values(handle, values: Iterable[float], per_line: int) -> None:
    row: list[float] = []
    for value in values:
        row.append(value)
        if len(row) == per_line:
            handle.write("".join(gaussian_float(item) for item in row) + "\n")
            row = []
    if row:
        handle.write("".join(gaussian_float(item) for item in row) + "\n")


def write_gaussian_external_output(
    output_path: Path,
    energy: float,
    gradient: Sequence[tuple[float, float, float]] | None = None,
    hessian: Sequence[Sequence[float]] | None = None,
) -> None:
    with output_path.open("w", encoding="ascii", newline="\n") as handle:
        write_values(handle, [energy, 0.0, 0.0, 0.0], per_line=4)
        if gradient is None:
            return
        for gx, gy, gz in gradient:
            write_values(handle, [gx, gy, gz], per_line=3)
        if hessian is None:
            return
        natoms = len(gradient)
        dimension = 3 * natoms
        write_values(handle, [0.0] * 6, per_line=3)
        write_values(handle, [0.0] * (9 * natoms), per_line=3)
        lower_triangle = (
            hessian[row][col] for row in range(dimension) for col in range(row + 1)
        )
        write_values(handle, lower_triangle, per_line=3)


def build_output_from_xtb(workdir: Path, output_path: Path, natoms: int, derivs: int) -> None:
    energy = parse_energy(workdir / "xtbout")
    if derivs == 0:
        write_gaussian_external_output(output_path, energy)
        return

    gradient = parse_gradient(workdir / "gradient", natoms)
    if derivs == 1:
        write_gaussian_external_output(output_path, energy, gradient=gradient)
        return

    hessian = parse_hessian(workdir / "hessian", natoms)
    write_gaussian_external_output(
        output_path, energy, gradient=gradient, hessian=hessian
    )


def split_command(command: str) -> list[str]:
    return shlex.split(command, posix=os.name != "nt")


def xtb_command_for(data: GaussianExternalInput) -> list[str]:
    command = split_command(os.environ.get("GAU_XTB_COMMAND", "xtb"))
    command.extend(["mol.xyz", "--chrg", str(data.charge), "--uhf", str(data.uhf)])

    # 方法/数值参数：优先 GAU_XTB_METHOD（如 "--gxtb"、"--gfn 2 --acc 0.5 --alpb water"），
    # 兼容旧的 GAU_XTB_GFN（只给数字，等价于 --gfn <N>）。
    method_args = os.environ.get("GAU_XTB_METHOD")
    if method_args:
        command.extend(split_command(method_args))
    else:
        gfn = os.environ.get("GAU_XTB_GFN")
        if gfn:
            command.extend(["--gfn", gfn])

    parallel = os.environ.get("GAU_XTB_THREADS")
    if parallel:
        command.extend(["--parallel", parallel])

    extra_args = os.environ.get("GAU_XTB_ARGS")
    if extra_args:
        command.extend(split_command(extra_args))

    if data.derivs == 0:
        command.append("--sp")
    elif data.derivs == 1:
        command.append("--grad")
    elif data.derivs == 2:
        command.extend(["--hess", "--grad"])
    else:
        raise GauXtbError(f"Unsupported derivative level {data.derivs}")
    return command


def xtb_environment() -> dict[str, str]:
    env = os.environ.copy()
    threads = os.environ.get("GAU_XTB_THREADS")
    if threads:
        env["OMP_NUM_THREADS"] = threads
        env["MKL_NUM_THREADS"] = threads
    return env


def run_xtb(data: GaussianExternalInput, workdir: Path) -> None:
    command = xtb_command_for(data)
    xtbout = workdir / "xtbout"
    timeout_text = os.environ.get("GAU_XTB_TIMEOUT")
    timeout = float(timeout_text) if timeout_text else None
    # Windows: 隐藏 xtb.exe 弹出的命令行窗口（高斯 opt 每步都调一次，否则狂闪）
    if os.name == "nt":
        popen_kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW}
    else:
        popen_kwargs = {}
    with xtbout.open("w", encoding="utf-8", errors="replace") as handle:
        try:
            subprocess.run(
                command,
                cwd=str(workdir),
                env=xtb_environment(),
                stdout=handle,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=timeout,
                **popen_kwargs,
            )
        except FileNotFoundError as exc:
            raise GauXtbError(
                f"Could not execute xTB command {command[0]!r}; set GAU_XTB_COMMAND"
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise GauXtbError(
                f"xTB failed with exit code {exc.returncode}; see {xtbout}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise GauXtbError(f"xTB timed out after {timeout} seconds; see {xtbout}") from exc


def cleanup_generated_files(workdir: Path) -> None:
    for name in GENERATED_FILES:
        path = workdir / name
        try:
            if path.is_file() or path.is_symlink():
                path.unlink()
        except FileNotFoundError:
            pass
    for pattern in ("*.engrad",):
        for path in workdir.glob(pattern):
            try:
                if path.is_file() or path.is_symlink():
                    path.unlink()
            except FileNotFoundError:
                pass


def keep_workdir_enabled() -> bool:
    return os.environ.get("GAU_XTB_KEEP_WORKDIR", "").lower() in {"1", "true", "yes", "on"}


def run_gaussian_external(argv: Sequence[str]) -> int:
    if len(argv) < 3:
        raise GauXtbError(
            "Gaussian External mode expects: layer InputFile OutputFile [MsgFile FChkFile MatElFile]"
        )
    input_path = Path(argv[1]).resolve()
    output_path = Path(argv[2]).resolve()
    # 先把"输入文件在不在"说清楚：文件不存在时若继续读，会抛一个让人看不懂的
    # FileNotFoundError（打包版还会弹出裸 traceback 对话框）。
    if not input_path.is_file():
        raise GauXtbError(
            f"Gaussian External 的输入文件不存在: {input_path}\n"
            f"        这一般意味着本次调用不是高斯发起的（例如把文件拖到了程序图标上），"
            f"或者作业目录/文件已经被移动、删除。"
        )
    data = parse_gaussian_external_input(input_path)

    keep_workdir = keep_workdir_enabled()
    temp_parent = os.environ.get("GAU_XTB_TMPDIR")
    with tempfile.TemporaryDirectory(prefix="gau_xtb_", dir=temp_parent) as temp_name:
        workdir = Path(temp_name)
        write_xyz(data, workdir / "mol.xyz")
        run_xtb(data, workdir)
        build_output_from_xtb(workdir, output_path, data.natoms, data.derivs)
        if keep_workdir:
            kept = shutil.copytree(workdir, Path(temp_name + "_kept"))
            print(f"gau_xtb.py kept workdir at {kept}", file=sys.stderr)
    return 0


def command_genxyz(args: argparse.Namespace) -> int:
    data = parse_genxyz_input(Path(args.input_file))
    write_xyz(data, Path(args.output_xyz))
    return 0


def command_extderi(args: argparse.Namespace) -> int:
    build_output_from_xtb(
        Path(args.workdir), Path(args.output_file), args.natoms, args.derivs
    )
    return 0


def command_run(args: argparse.Namespace) -> int:
    return run_gaussian_external(
        [args.layer, args.input_file, args.output_file]
        + list(args.gaussian_extra_files)
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Pure Python Gaussian External interface for xTB"
    )
    subparsers = parser.add_subparsers(dest="command")

    genxyz = subparsers.add_parser(
        "genxyz", help="convert Gaussian External input or mol.tmp to XYZ"
    )
    genxyz.add_argument("input_file")
    genxyz.add_argument("output_xyz", nargs="?", default="mol.xyz")
    genxyz.set_defaults(func=command_genxyz)

    extderi = subparsers.add_parser(
        "extderi", help="write Gaussian External output from xTB files"
    )
    extderi.add_argument("output_file")
    extderi.add_argument("natoms", type=int)
    extderi.add_argument("derivs", type=int, choices=(0, 1, 2))
    extderi.add_argument("--workdir", default=".")
    extderi.set_defaults(func=command_extderi)

    run = subparsers.add_parser("run", help="run the full Gaussian External bridge")
    run.add_argument("layer")
    run.add_argument("input_file")
    run.add_argument("output_file")
    run.add_argument("gaussian_extra_files", nargs="*")
    run.set_defaults(func=command_run)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in {"-h", "--help", "genxyz", "extderi", "run"}:
        return run_gaussian_external(argv)

    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GauXtbError as exc:
        print(f"gau_xtb.py: error: {exc}", file=sys.stderr)
        raise SystemExit(1)
