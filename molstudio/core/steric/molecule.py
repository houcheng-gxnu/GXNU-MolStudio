# -*- coding: utf-8 -*-
# Ported from StericMapAnalyzer (GPLv3) — SambVca 2.1 official algorithm replica.
# 来源：StericMapAnalyzer v3.5（同作者仓库，GPL-3.0-only）的 molecule.py。
# License: GPL-3.0-only (inherited from StericMapAnalyzer).
# MolStudio 移植版：删除对原工程 config.py 的依赖（共价半径表内联），
# 错误文案改为 zh/en 双语，坐标统一用 float64；解析逻辑保持原样。
"""分子数据模型与 XYZ / Gaussian log 解析（纯计算，无 GUI 依赖）。

公开接口：:class:`Atom`、:class:`Molecule`、:func:`parse_xyz`、
:func:`parse_gaussian_log`、:func:`from_symbols_coords`。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import numpy as np

# 共价半径（Å），与 StericMapAnalyzer config.COVALENT_RADII 一致（Cordero 等）。
COVALENT_RADII: dict[str, float] = {
    'H': 0.31, 'He': 0.28, 'Li': 1.28, 'Be': 0.96, 'B': 0.84, 'C': 0.76,
    'N': 0.71, 'O': 0.66, 'F': 0.57, 'Ne': 0.58, 'Na': 1.66, 'Mg': 1.41,
    'Al': 1.21, 'Si': 1.11, 'P': 1.07, 'S': 1.05, 'Cl': 1.02, 'Ar': 1.06,
    'K': 2.03, 'Ca': 1.76, 'Sc': 1.70, 'Ti': 1.60, 'V': 1.53, 'Cr': 1.39,
    'Mn': 1.39, 'Fe': 1.32, 'Co': 1.26, 'Ni': 1.24, 'Cu': 1.32, 'Zn': 1.22,
    'Ga': 1.22, 'Ge': 1.20, 'As': 1.19, 'Se': 1.20, 'Br': 1.20, 'Kr': 1.16,
    'Rb': 2.20, 'Sr': 1.95, 'Y': 1.90, 'Zr': 1.75, 'Nb': 1.64, 'Mo': 1.54,
    'Tc': 1.47, 'Ru': 1.46, 'Rh': 1.42, 'Pd': 1.39, 'Ag': 1.45, 'Cd': 1.44,
    'In': 1.42, 'Sn': 1.39, 'Sb': 1.39, 'Te': 1.38, 'I': 1.39, 'Xe': 1.40,
    'Cs': 2.44, 'Ba': 2.15, 'La': 2.07, 'Hf': 1.75, 'Ta': 1.70, 'W': 1.62,
    'Re': 1.51, 'Os': 1.44, 'Ir': 1.41, 'Pt': 1.36, 'Au': 1.36, 'Hg': 1.32,
    'Tl': 1.45, 'Pb': 1.46, 'Bi': 1.48,
}
_DEFAULT_COVALENT_RADIUS = 0.76

#: 元素序号 → 符号（1-118），用于 Gaussian log 解析。
ELEMENT_SYMBOLS: dict[int, str] = {
    1: 'H', 2: 'He', 3: 'Li', 4: 'Be', 5: 'B', 6: 'C', 7: 'N', 8: 'O', 9: 'F', 10: 'Ne',
    11: 'Na', 12: 'Mg', 13: 'Al', 14: 'Si', 15: 'P', 16: 'S', 17: 'Cl', 18: 'Ar',
    19: 'K', 20: 'Ca', 21: 'Sc', 22: 'Ti', 23: 'V', 24: 'Cr', 25: 'Mn', 26: 'Fe',
    27: 'Co', 28: 'Ni', 29: 'Cu', 30: 'Zn', 31: 'Ga', 32: 'Ge', 33: 'As', 34: 'Se',
    35: 'Br', 36: 'Kr', 37: 'Rb', 38: 'Sr', 39: 'Y', 40: 'Zr', 41: 'Nb', 42: 'Mo',
    43: 'Tc', 44: 'Ru', 45: 'Rh', 46: 'Pd', 47: 'Ag', 48: 'Cd', 49: 'In', 50: 'Sn',
    51: 'Sb', 52: 'Te', 53: 'I', 54: 'Xe', 55: 'Cs', 56: 'Ba', 57: 'La', 58: 'Ce',
    59: 'Pr', 60: 'Nd', 61: 'Pm', 62: 'Sm', 63: 'Eu', 64: 'Gd', 65: 'Tb', 66: 'Dy',
    67: 'Ho', 68: 'Er', 69: 'Tm', 70: 'Yb', 71: 'Lu', 72: 'Hf', 73: 'Ta', 74: 'W',
    75: 'Re', 76: 'Os', 77: 'Ir', 78: 'Pt', 79: 'Au', 80: 'Hg', 81: 'Tl', 82: 'Pb',
    83: 'Bi', 84: 'Po', 85: 'At', 86: 'Rn', 87: 'Fr', 88: 'Ra', 89: 'Ac', 90: 'Th',
    91: 'Pa', 92: 'U', 93: 'Np', 94: 'Pu', 95: 'Am', 96: 'Cm', 97: 'Bk', 98: 'Cf',
    99: 'Es', 100: 'Fm', 101: 'Md', 102: 'No', 103: 'Lr', 104: 'Rf', 105: 'Db',
    106: 'Sg', 107: 'Bh', 108: 'Hs', 109: 'Mt', 110: 'Ds', 111: 'Rg', 112: 'Cn',
    113: 'Nh', 114: 'Fl', 115: 'Mc', 116: 'Lv', 117: 'Ts', 118: 'Og',
}

# 解析错误文案（zh / en）。源工程通过 GUI 的 tr() 覆盖，这里自带双语兜底。
_TEXT: dict[str, tuple[str, str]] = {
    "mol_empty_file": ("文件为空", "empty file"),
    "mol_bad_count": ("首行原子数非法：{line!r}", "invalid atom count on line 1: {line!r}"),
    "mol_too_few_lines": ("行数不足：需要 {need} 行，实际 {have} 行",
                          "not enough lines: need {need}, got {have}"),
    "mol_bad_line": ("第 {n} 行格式非法：{line!r}", "malformed line {n}: {line!r}"),
    "mol_bad_coords": ("第 {n} 行坐标非法：{line!r}", "invalid coordinates on line {n}: {line!r}"),
    "mol_read_failed": ("读取文件失败：{err}", "failed to read file: {err}"),
    "mol_no_coords": ("找不到 Standard/Input orientation 坐标块",
                      "no Standard/Input orientation block found"),
    "mol_parse_failed": ("解析失败：{err}", "parse failed: {err}"),
}


def _msg(key: str, tr=None, lang: str = "zh", **kw) -> str:
    """取本地化文案；tr 优先（GUI 翻译钩子），否则用内置 zh/en 表。"""
    if tr is not None:
        try:
            tpl = tr(key)
            if tpl and tpl != key:
                return tpl.format(**kw) if kw else tpl
        except Exception:  # noqa: BLE001 - 翻译函数不可靠时回落
            pass
    zh, en = _TEXT.get(key, (key, key))
    tpl = en if str(lang or "zh").lower().startswith("en") else zh
    try:
        return tpl.format(**kw)
    except (KeyError, IndexError, ValueError):
        return tpl


@dataclass
class Atom:
    """单个原子（``index`` 为 1-based 序号）。"""

    index: int
    symbol: str
    x: float
    y: float
    z: float

    @property
    def position_tuple(self) -> Tuple[float, float, float]:
        return (self.x, self.y, self.z)

    @property
    def position_array(self) -> np.ndarray:
        return np.array([self.x, self.y, self.z], dtype=float)

    def pos(self) -> Tuple[float, float, float]:
        return (self.x, self.y, self.z)


def _estimate_bonds(atoms: Sequence[Atom]) -> List[Tuple[int, int]]:
    """按共价半径之和 ×1.2 估算化学键（与源工程 parse_xyz 一致）。"""
    bonds: List[Tuple[int, int]] = []
    for i in range(len(atoms)):
        a1 = atoms[i]
        r1 = COVALENT_RADII.get(a1.symbol, _DEFAULT_COVALENT_RADIUS)
        for j in range(i + 1, len(atoms)):
            a2 = atoms[j]
            r2 = COVALENT_RADII.get(a2.symbol, _DEFAULT_COVALENT_RADIUS)
            dx, dy, dz = a1.x - a2.x, a1.y - a2.y, a1.z - a2.z
            if math.sqrt(dx * dx + dy * dy + dz * dz) < (r1 + r2) * 1.2:
                bonds.append((a1.index, a2.index))
    return bonds


@dataclass
class Molecule:
    """分子数据模型（原子按 1-based 序号排序）。"""

    atoms: List[Atom] = field(default_factory=list)
    bonds: List[Tuple[int, int]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.atoms.sort(key=lambda a: a.index)
        if self.bonds is None:
            self.bonds = []

    @property
    def symbols(self) -> List[str]:
        return [atom.symbol for atom in self.atoms]

    @property
    def positions(self) -> np.ndarray:
        """(N, 3) float64 坐标数组。"""
        if not self.atoms:
            return np.empty((0, 3), dtype=float)
        return np.array([atom.position_tuple for atom in self.atoms], dtype=float)

    @property
    def atom_count(self) -> int:
        return len(self.atoms)

    @property
    def bond_count(self) -> int:
        return len(self.bonds)

    def get_atom(self, index: int) -> Optional[Atom]:
        """按 1-based 序号取原子。"""
        for atom in self.atoms:
            if atom.index == index:
                return atom
        return None

    def find_center_atom(self, center_symbol: Optional[str] = None) -> Optional[Atom]:
        if not self.atoms:
            return None
        if center_symbol:
            for atom in self.atoms:
                if atom.symbol == center_symbol:
                    return atom
        return self.atoms[0]

    def delete_atoms(self, indices: Sequence[int]) -> "Molecule":
        """删除指定 1-based 序号原子，返回新分子（坐标与键随之重编号）。"""
        if not indices:
            return self
        drop = set(int(i) for i in indices)
        new_atoms: List[Atom] = []
        old_to_new: dict[int, int] = {}
        for atom in self.atoms:
            if atom.index in drop:
                continue
            new_idx = len(new_atoms) + 1
            new_atoms.append(Atom(new_idx, atom.symbol, atom.x, atom.y, atom.z))
            old_to_new[atom.index] = new_idx
        new_bonds = [(old_to_new[a], old_to_new[b]) for a, b in self.bonds
                     if a in old_to_new and b in old_to_new]
        return Molecule(atoms=new_atoms, bonds=new_bonds)

    def center_molecule(self) -> None:
        """把分子平移到质心。"""
        if not self.atoms:
            return
        centroid = np.mean(self.positions, axis=0)
        for atom in self.atoms:
            atom.x -= float(centroid[0])
            atom.y -= float(centroid[1])
            atom.z -= float(centroid[2])

    def get_bounding_box(self) -> Tuple[float, float, float, float, float, float]:
        if not self.atoms:
            return (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        pos = self.positions
        xmin, ymin, zmin = np.min(pos, axis=0)
        xmax, ymax, zmax = np.max(pos, axis=0)
        return (float(xmin), float(xmax), float(ymin), float(ymax),
                float(zmin), float(zmax))

    def to_xyz_string(self) -> str:
        lines = [str(len(self.atoms)), ""]
        for atom in self.atoms:
            lines.append(f"{atom.symbol:<3} {atom.x:15.8f} {atom.y:15.8f} {atom.z:15.8f}")
        return "\n".join(lines)


def from_symbols_coords(symbols: Sequence[str], coords) -> Molecule:
    """由符号列表与 (n,3) 坐标直接构造 :class:`Molecule`（坐标单位 Å）。"""
    P = np.asarray(coords, dtype=float)
    if P.ndim != 2 or P.shape[1] != 3:
        raise ValueError("coords 形状必须为 (n, 3) / coords must have shape (n, 3)")
    if len(symbols) != P.shape[0]:
        raise ValueError(
            f"符号数 {len(symbols)} 与坐标数 {P.shape[0]} 不一致 / "
            f"symbol count {len(symbols)} != coordinate count {P.shape[0]}")
    atoms = [Atom(i + 1, str(sym), float(P[i, 0]), float(P[i, 1]), float(P[i, 2]))
             for i, sym in enumerate(symbols)]
    return Molecule(atoms=atoms, bonds=_estimate_bonds(atoms))


def parse_xyz(file_path, tr=None, lang: str = "zh") -> Molecule:
    """解析标准 XYZ 文件（支持 UTF-8 BOM；第 2 行作为标题忽略）。"""
    try:
        with open(file_path, 'r', encoding='utf-8-sig') as fh:
            lines = fh.readlines()
    except OSError as exc:
        raise ValueError(_msg("mol_read_failed", tr, lang, err=exc)) from exc

    if not lines:
        raise ValueError(_msg("mol_empty_file", tr, lang))
    try:
        n_atoms = int(lines[0].strip())
    except ValueError as exc:
        raise ValueError(_msg("mol_bad_count", tr, lang, line=lines[0].strip())) from exc
    if n_atoms < 0:
        raise ValueError(_msg("mol_bad_count", tr, lang, line=lines[0].strip()))
    if len(lines) < 2 + n_atoms:
        raise ValueError(_msg("mol_too_few_lines", tr, lang,
                              need=2 + n_atoms, have=len(lines)))

    atoms: List[Atom] = []
    for i in range(n_atoms):
        line = lines[2 + i].strip()
        parts = line.split()
        if len(parts) < 4:
            raise ValueError(_msg("mol_bad_line", tr, lang, n=3 + i, line=line))
        try:
            x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
        except ValueError as exc:
            raise ValueError(_msg("mol_bad_coords", tr, lang, n=3 + i, line=line)) from exc
        atoms.append(Atom(i + 1, parts[0], x, y, z))
    return Molecule(atoms=atoms, bonds=_estimate_bonds(atoms))


def parse_gaussian_log(file_path, tr=None, lang: str = "zh") -> Molecule:
    """从 Gaussian .log 取**最后一次** ``Standard orientation`` 块（回退 Input）。

    优化任务的 log 里每个优化步都有一个 orientation 块，只有最后一个才是最终构型；
    因此扫描全文后取末块，仅当没有任何完整块时才退回被截断的末尾块。
    """
    try:
        with open(file_path, 'r', encoding='utf-8-sig', errors='ignore') as fh:
            text = fh.read()
    except OSError as exc:
        raise ValueError(_msg("mol_read_failed", tr, lang, err=exc)) from exc

    lines = text.splitlines()

    def extract_coords(orient_label: str) -> list:
        blocks: list = []
        coords: list = []
        in_block = False
        header_seen = 0
        for line in lines:
            if orient_label in line:
                in_block = True
                header_seen = 0
                continue
            if not in_block:
                continue
            if "----" in line:
                header_seen += 1
                if header_seen == 2:
                    coords = []
                elif header_seen >= 3:
                    if coords:
                        blocks.append(coords)
                    in_block = False
                    coords = []
                continue
            if header_seen != 2:
                continue
            parts = line.split()
            if len(parts) < 6:
                continue
            try:
                center = int(parts[0])
                atomic_num = int(parts[1])
                x, y, z = float(parts[3]), float(parts[4]), float(parts[5])
                coords.append((center, atomic_num, x, y, z))
            except (ValueError, IndexError):
                continue
        if coords and not blocks:
            blocks.append(coords)
        return blocks[-1] if blocks else []

    coords = extract_coords("Standard orientation")
    if not coords:
        coords = extract_coords("Input orientation")
    if not coords:
        raise ValueError(_msg("mol_no_coords", tr, lang))

    atoms = [Atom(i, ELEMENT_SYMBOLS.get(int(num), "X"), x, y, z)
             for i, (_c, num, x, y, z) in enumerate(coords, start=1)]
    return Molecule(atoms=atoms, bonds=_estimate_bonds(atoms))


# 兼容旧接口
Molecule.from_xyz = staticmethod(parse_xyz)  # type: ignore[attr-defined]

__all__ = [
    "Atom", "Molecule", "COVALENT_RADII", "ELEMENT_SYMBOLS",
    "parse_xyz", "parse_gaussian_log", "from_symbols_coords",
]
