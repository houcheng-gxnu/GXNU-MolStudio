# -*- coding: utf-8 -*-
"""
MolCanvas — Pure PyQt5 QWidget 3D molecule renderer using QPainter.
Features: quaternion arcball rotation, 17 visual style presets, unified depth sorting,
dash bond mode, sphere gradients, dark rim, Houk crosshair, background gradient,
click-to-select, box-select (Shift+drag), rotation, panning, and zoom.

Merged from OrbitalViewer 5.3 + ETS-NOCV fragment/signal support.
"""

import os
import re
import math

from PyQt5.QtWidgets import QWidget, QApplication
from PyQt5.QtCore import Qt, QPoint, QPointF, QTimer, pyqtSignal, QRectF
from PyQt5.QtGui import (
    QFont, QPainter, QPen, QBrush, QColor,
    QRadialGradient, QLinearGradient, QPainterPath,
)


# ── Config ───────────────────────────────────────────
BOHR_TO_ANGSTROM = 0.52917720859

ATOM_RADII = {
    'H': 0.50, 'He': 0.28, 'Li': 1.28, 'Be': 0.96, 'B': 0.84,
    'C': 0.76, 'N': 0.71, 'O': 0.66, 'F': 0.57, 'Ne': 0.58,
    'Na': 1.66, 'Mg': 1.41, 'Al': 1.21, 'Si': 1.11, 'P': 1.07,
    'S': 1.05, 'Cl': 1.02, 'Ar': 1.06, 'K': 2.03, 'Ca': 1.76,
    'Sc': 1.7, 'Ti': 1.6, 'V': 1.53, 'Cr': 1.39, 'Mn': 1.39,
    'Fe': 1.32, 'Co': 1.26, 'Ni': 1.24, 'Cu': 1.32, 'Zn': 1.22,
    'Ga': 1.22, 'Ge': 1.2, 'As': 1.19, 'Se': 1.2, 'Br': 1.2,
    'Kr': 1.16, 'Rb': 2.2, 'Sr': 1.95, 'Y': 1.9, 'Zr': 1.75,
    'Nb': 1.64, 'Mo': 1.54, 'Tc': 1.47, 'Ru': 1.46, 'Rh': 1.42,
    'Pd': 1.39, 'Ag': 1.45, 'Cd': 1.44, 'In': 1.42, 'Sn': 1.39,
    'Sb': 1.39, 'Te': 1.38, 'I': 1.39, 'Xe': 1.4, 'Cs': 2.44,
    'Ba': 2.15, 'La': 2.07, 'Ce': 2.04, 'Pr': 2.03, 'Nd': 2.01,
    'Pm': 1.99, 'Sm': 1.98, 'Eu': 1.98, 'Gd': 1.96, 'Tb': 1.94,
    'Dy': 1.92, 'Ho': 1.92, 'Er': 1.89, 'Tm': 1.9, 'Yb': 1.87,
    'Lu': 1.87, 'Hf': 1.75, 'Ta': 1.7, 'W': 1.62, 'Re': 1.51,
    'Os': 1.44, 'Ir': 1.41, 'Pt': 1.36, 'Au': 1.36, 'Hg': 1.32,
    'Tl': 1.45, 'Pb': 1.46, 'Bi': 1.48, 'Po': 1.4, 'At': 1.5,
    'Rn': 1.5, 'Fr': 2.6, 'Ra': 2.21, 'Ac': 2.15, 'Th': 2.06,
    'Pa': 2.0, 'U': 1.96, 'Np': 1.9, 'Pu': 1.87, 'Am': 1.8,
    'Cm': 1.69, 'Bk': 2.0, 'Cf': 2.0, 'Es': 2.0, 'Fm': 2.0,
    'Md': 2.0, 'No': 2.0, 'Lr': 2.0,
}

ATOM_COLORS = {
    'H': '#CCCCCC', 'He': '#D8FFFF', 'Li': '#CC7CFF', 'Be': '#CCFF00',
    'B': '#FFB4B4', 'C': '#8E8E8E', 'N': '#1818E4', 'O': '#E40000',
    'F': '#B1FFFF', 'Ne': '#AFE2F4', 'Na': '#AA5BF1', 'Mg': '#B1CC00',
    'Al': '#D0A5A5', 'Si': '#7E9999', 'P': '#FF7E00', 'S': '#FFC628',
    'Cl': '#18EF18', 'Ar': '#7ED0E2', 'K': '#8E3FD3', 'Ca': '#999900',
    'Sc': '#E4E4E2', 'Ti': '#BEC1C6', 'V': '#A5A5AA', 'Cr': '#8999C6',
    'Mn': '#9A79C6', 'Fe': '#7E79C6', 'Co': '#5B6DFF', 'Ni': '#5B79C1',
    'Cu': '#FF7960', 'Zn': '#7C7EAF', 'Ga': '#C18E8E', 'Ge': '#668E8E',
    'As': '#BC7EE2', 'Se': '#FFA000', 'Br': '#A52020', 'Kr': '#5BB9D0',
    'Rb': '#6F2DAF', 'Sr': '#7E6600', 'Y': '#93FBFF', 'Zr': '#93DFDF',
    'Nb': '#72C1C8', 'Mo': '#53B4B4', 'Tc': '#3A9DA7', 'Ru': '#238E95',
    'Rh': '#097C8B', 'Pd': '#006783', 'Ag': '#99C6FF', 'Cd': '#FFD88E',
    'In': '#A57472', 'Sn': '#667E7E', 'Sb': '#9D62B4', 'Te': '#D37900',
    'I': '#930093', 'Xe': '#419DAF', 'Cs': '#56168E', 'Ba': '#663300',
    'La': '#6FDDFF', 'Ce': '#FFFFC6', 'Pr': '#D8FFC6', 'Nd': '#C6FFC6',
    'Pm': '#A2FFC6', 'Sm': '#8EFFC6', 'Eu': '#60FFC6', 'Gd': '#44FFC6',
    'Tb': '#2FFFC6', 'Dy': '#1DFFB4', 'Ho': '#00FFB4', 'Er': '#00E474',
    'Tm': '#00D350', 'Yb': '#00BE37', 'Lu': '#00AA23', 'Hf': '#4BC1FF',
    'Ta': '#4BA5FF', 'W': '#2593D5', 'Re': '#257CAA', 'Os': '#256695',
    'Ir': '#165386', 'Pt': '#165B8E', 'Au': '#FFD023', 'Hg': '#B4B4C1',
    'Tl': '#A5534B', 'Pb': '#565860', 'Bi': '#9D4EB4', 'Po': '#AA5B00',
    'At': '#744E44', 'Rn': '#418195', 'Fr': '#410066', 'Ra': '#4B1800',
    'Ac': '#6FAAF9', 'Th': '#00B9FF', 'Pa': '#00A0FF', 'U': '#008EFF',
    'Np': '#007EF1', 'Pu': '#006AF1', 'Am': '#535BF1', 'Cm': '#775BE2',
    'Bk': '#895DE2', 'Cf': '#A034D3', 'Es': '#A72AC6', 'Fm': '#B11DB9',
    'Md': '#B10CA5', 'No': '#BC0C86', 'Lr': '#C60066', 'Rf': '#FF7E7E',
    'Db': '#E46666', 'Sg': '#CC4B4B', 'Bh': '#B13333', 'Hs': '#991818',
    'Mt': '#8B0000', 'Ds': '#7E0000', 'Rg': '#720000',
}


# ═════════════════════════════════════════════════════
#  视觉风格预设 (移植自 xTBridge / OrbitalViewer 5.3)
# ═════════════════════════════════════════════════════

STYLE_PRESETS = {
    "Houk": {
        "name": "Houk 经典",
        "bg_gradient": True,
        "bg_colors": ("#E8EDF5", "#F5F7FB", "#FFFFFF"),
        "bond_color": "#000000",
        "atom_scale": 0.32,
        "bond_width": 3.0,
        "shadows": True,
        "crosshair": True,
        "rim": True,
        "gradient": "full",
        "label_mode": 2,
    },
    "Academic": {
        "name": "学术论文",
        "bg_gradient": False,
        "bg_colors": ("#FFFFFF", "#FFFFFF", "#FFFFFF"),
        "bond_color": "#B0B8C4",
        "atom_scale": 0.32,
        "bond_width": 3.0,
        "shadows": True,
        "crosshair": False,
        "rim": False,
        "gradient": "soft_matte",
        "label_mode": 2,
    },
    "Publication": {
        "name": "期刊插图",
        "bg_gradient": False,
        "bg_colors": ("#FAFBFD", "#FAFBFD", "#FAFBFD"),
        "bond_color": "#7A8694",
        "atom_scale": 0.32,
        "bond_width": 3.0,
        "shadows": True,
        "crosshair": False,
        "rim": False,
        "gradient": "subtle",
        "label_mode": 2,
    },
    "CYLView": {
        "name": "CYLView",
        "bg_gradient": False,
        "bg_colors": ("#FFFFFF", "#FFFFFF", "#FFFFFF"),
        "bond_color": "#505050",
        "atom_scale": 0.32,
        "bond_width": 3.0,
        "shadows": False,
        "crosshair": True,
        "rim": True,
        "gradient": "flat",
        "label_mode": 2,
    },
    "AppleGlass": {
        "name": "Apple Glass",
        "bg_gradient": True,
        "bg_colors": ("#F3F7FB", "#FFFFFF", "#F8FAFC"),
        "bond_color": "#C0C7D1",
        "atom_scale": 0.32,
        "bond_width": 3.0,
        "shadows": True,
        "crosshair": False,
        "rim": False,
        "gradient": "soft_matte",
        "label_mode": 2,
    },
    "DarkPro": {
        "name": "深色专业",
        "bg_gradient": False,
        "bg_colors": ("#121417", "#121417", "#121417"),
        "bond_color": "#707780",
        "atom_scale": 0.32,
        "bond_width": 3.0,
        "shadows": False,
        "crosshair": False,
        "rim": False,
        "gradient": "soft_matte",
        "label_mode": 2,
    },
    "SobArt": {
        "name": "Chem311",
        "bg_gradient": False,
        "bg_colors": ("#FFFFFF", "#FFFFFF", "#FFFFFF"),
        "bond_color": "#FFFFFF",
        "atom_scale": 0.30,
        "bond_width": 3.5,
        "shadows": False,
        "crosshair": False,
        "rim": True,
        "gradient": "sob_art",
        "label_mode": 2,
    },
    "AppleLiquid": {
        "name": "Apple Liquid Glass",
        "bg_gradient": True,
        "bg_colors": ("#EEF4FF", "#F8FBFF", "#FFFFFF"),
        "bond_color": "#C7D2E0",
        "atom_scale": 0.19,
        "bond_width": 3.2,
        "shadows": True,
        "crosshair": False,
        "rim": False,
        "gradient": "apple_liquid",
        "label_mode": 2,
    },
    "ModernPaper": {
        "name": "Modern Paper",
        "bg_gradient": True,
        "bg_colors": ("#F8FAFC", "#FFFFFF", "#F1F5F9"),
        "bond_color": "#D6DEE8",
        "atom_scale": 0.30,
        "bond_width": 2.6,
        "shadows": True,
        "crosshair": False,
        "rim": True,
        "gradient": "paper_matte",
        "label_mode": 2,
    },
    "HoukPremium": {
        "name": "Houk Premium",
        "bg_gradient": True,
        "bg_colors": ("#EAF0F8", "#F8FBFF", "#FFFFFF"),
        "bond_color": "#28323D",
        "atom_scale": 0.31,
        "bond_width": 2.8,
        "shadows": True,
        "crosshair": True,
        "rim": True,
        "gradient": "premium_full",
        "label_mode": 2,
    },
    "SoftClay": {
        "name": "Soft Clay",
        "bg_gradient": True,
        "bg_colors": ("#F6F7F4", "#FFFFFF", "#EEF1ED"),
        "bond_color": "#BBC5C0",
        "atom_scale": 0.33,
        "bond_width": 3.1,
        "shadows": True,
        "crosshair": False,
        "rim": True,
        "gradient": "clay_matte",
        "label_mode": 2,
    },
    "GlassPlus": {
        "name": "Glass Plus",
        "bg_gradient": True,
        "bg_colors": ("#EEF6FF", "#FFFFFF", "#F6FAFF"),
        "bond_color": "#D3DEEA",
        "atom_scale": 0.24,
        "bond_width": 3.0,
        "shadows": True,
        "crosshair": False,
        "rim": True,
        "gradient": "glass_plus",
        "label_mode": 2,
    },
    "DarkNeon": {
        "name": "Dark Neon",
        "bg_gradient": True,
        "bg_colors": ("#10151D", "#161D27", "#0B0F14"),
        "bond_color": "#65758A",
        "atom_scale": 0.30,
        "bond_width": 3.0,
        "shadows": False,
        "crosshair": False,
        "rim": True,
        "gradient": "neon_glow",
        "label_mode": 2,
    },
    "InkMinimal": {
        "name": "Ink Minimal",
        "bg_gradient": False,
        "bg_colors": ("#FFFFFF", "#FFFFFF", "#FFFFFF"),
        "bond_color": "#222222",
        "atom_scale": 0.25,
        "bond_width": 1.8,
        "shadows": False,
        "crosshair": False,
        "rim": True,
        "gradient": "ink_flat",
        "label_mode": 2,
    },
    "VMD": {
        "name": "VMD 默认",
        "bg_gradient": False,
        "bg_colors": ("#202020", "#202020", "#202020"),
        "bond_color": "#FFFFFF",
        "atom_scale": 0.30,
        "bond_width": 3.2,
        "shadows": False,
        "crosshair": False,
        "rim": True,
        "gradient": "flat",
        "label_mode": 2,
    },
    "HoukMol": {
        "name": "HoukMol",
        "bg_gradient": True,
        "bg_colors": ("#E8EDF5", "#F5F7FB", "#FFFFFF"),
        "bond_color": "#000000",
        "atom_scale": 0.30,
        "bond_width": 10,
        "shadows": True,
        "crosshair": False,
        "rim": False,
        "gradient": "gau_default",
        "label_mode": 2,
    },
}

SOB_ART_CPK = {
    'H': '#F0F0F0', 'C': '#B38F5C', 'N': '#3050F8', 'O': '#FF2010',
    'S': '#FFC832', 'P': '#FF8020', 'F': '#7AE060',
    'Cl': '#30C040', 'Br': '#802020', 'I': '#620062',
}

APPLE_CPK = {
    'H': '#F7F8FA', 'C': '#A8B4C3', 'N': '#6F9EFF', 'O': '#FF7B8A',
    'S': '#FFD166', 'P': '#FFB366', 'F': '#81D8D0', 'Cl': '#78D67A',
}

PAPER_CPK = {
    'H': '#F8FAFC', 'C': '#A5B0BC', 'N': '#5B7FE8', 'O': '#EF5B5B',
    'S': '#E6B94A', 'P': '#E58A4A', 'F': '#78D7C6',
    'Cl': '#74C476', 'Br': '#A06A5E', 'I': '#8C6DB3',
}

CLAY_CPK = {
    'H': '#F2F0EA', 'C': '#9C9285', 'N': '#6278B8', 'O': '#C96E64',
    'S': '#D6B85C', 'P': '#C98655', 'F': '#80BFA8',
    'Cl': '#86B878', 'Br': '#8E5D55', 'I': '#75608E',
}


ELEMENT_SYMBOLS = {
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
    106: 'Sg', 107: 'Bh', 108: 'Hs', 109: 'Mt', 110: 'Ds', 111: 'Rg',
}


# ── fchk Parser ──────────────────────────────────────

def get_atoms_from_fchk(fchk_path):
    """Parse atomic coordinates from fchk file (Bohr -> Angstrom)."""
    atoms = []
    with open(fchk_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    m_nums = re.search(r"Atomic numbers\s+I\s+N=\s+(\d+)\s*\n([\s\S]+?)(?=\n\w|\Z)", content)
    if not m_nums:
        raise ValueError("Could not find 'Atomic numbers' section in fchk file")

    atomic_nums = list(map(int, m_nums.group(2).split()))

    m_coords = re.search(r"Current cartesian coordinates\s+R\s+N=\s+(\d+)\s*\n([\s\S]+?)(?=\n\w|\Z)", content)
    if not m_coords:
        raise ValueError("Could not find 'Current cartesian coordinates' section in fchk file")

    coords_raw = list(map(float, m_coords.group(2).split()))
    expected = len(atomic_nums) * 3
    if len(coords_raw) < expected:
        raise ValueError(
            f"Coordinate count mismatch: got {len(coords_raw)}, expected {expected}"
        )

    for i, an in enumerate(atomic_nums):
        x = coords_raw[i * 3] * BOHR_TO_ANGSTROM
        y = coords_raw[i * 3 + 1] * BOHR_TO_ANGSTROM
        z = coords_raw[i * 3 + 2] * BOHR_TO_ANGSTROM
        symbol = ELEMENT_SYMBOLS.get(an, "E" + str(an))
        atoms.append((i + 1, symbol, an, (x, y, z)))

    return atoms


def get_bonds_from_fchk(atoms):
    """Detect bonds via atom radii overlap."""
    bonds = []
    for i in range(len(atoms)):
        idx1, sym1, an1, (x1, y1, z1) = atoms[i]
        r1 = ATOM_RADII.get(sym1, 1.5)
        for j in range(i + 1, len(atoms)):
            idx2, sym2, an2, (x2, y2, z2) = atoms[j]
            r2 = ATOM_RADII.get(sym2, 1.5)
            d = math.sqrt((x1 - x2)**2 + (y1 - y2)**2 + (z1 - z2)**2)
            if d < r1 + r2 + 0.45:
                bonds.append((idx1, idx2))
    return bonds


# ── Cube Parser ──────────────────────────────────────

def get_atoms_from_cube(cube_path):
    """Parse atomic coordinates from Gaussian .cube file (Bohr -> Angstrom)."""
    atoms = []
    with open(cube_path, "r", encoding="utf-8", errors="ignore") as f:
        f.readline()  # comment 1
        f.readline()  # comment 2
        header3 = f.readline().split()
        if len(header3) < 4:
            raise ValueError("Invalid cube file: missing atom count header")
        natom = int(header3[0])
        f.readline()
        f.readline()
        f.readline()
        for i in range(natom):
            parts = f.readline().split()
            if len(parts) < 5:
                raise ValueError(f"Invalid cube file: insufficient data for atom {i+1}")
            an = int(parts[0])
            x = float(parts[2]) * BOHR_TO_ANGSTROM
            y = float(parts[3]) * BOHR_TO_ANGSTROM
            z = float(parts[4]) * BOHR_TO_ANGSTROM
            symbol = ELEMENT_SYMBOLS.get(an, "E" + str(an))
            atoms.append((i + 1, symbol, an, (x, y, z)))
    return atoms

get_bonds_from_cube = get_bonds_from_fchk


# ── Backward-compatible aliases ──────────────────────
parse_fchk_atoms = get_atoms_from_fchk
calculate_bonds = get_bonds_from_fchk


# ── xyz / gjf / log parsers ──────────────────────────

def parse_xyz_file(filepath):
    """Parse atomic coordinates from .xyz file (Angstrom)."""
    atoms = []
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    if not lines:
        return atoms
    n_atoms = int(lines[0].strip())
    for i in range(2, 2 + n_atoms):
        if i >= len(lines):
            break
        parts = lines[i].strip().split()
        if len(parts) >= 4:
            sym = parts[0].capitalize()
            x = float(parts[1])
            y = float(parts[2])
            z = float(parts[3])
            idx = i - 1
            atoms.append((idx, sym, 0, (x, y, z)))
    return atoms


def parse_gjf_file(filepath):
    """Parse atomic coordinates from Gaussian .gjf/.com input file."""
    atoms = []
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    lines = content.split('\n')
    start_idx = None
    for i, line in enumerate(lines):
        ls = line.strip()
        if ls and not ls.startswith('#') and not ls.startswith('%') and not ls.startswith('--'):
            if start_idx is None:
                parts = ls.split()
                if len(parts) == 2:
                    try:
                        int(parts[0])
                        int(parts[1])
                        start_idx = i + 1
                    except ValueError:
                        pass
    if start_idx is not None:
        idx = 0
        for line in lines[start_idx:]:
            parts = line.strip().split()
            if not parts or parts[0].startswith('--'):
                continue
            if len(parts) >= 4:
                sym = parts[0].capitalize()
                x = float(parts[1])
                y = float(parts[2])
                z = float(parts[3])
                idx += 1
                atoms.append((idx, sym, 0, (x, y, z)))
    return atoms


def parse_log_file(filepath):
    """Parse the last frame from a Gaussian .log output file."""
    atoms = []
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    patterns = [
        r"Standard orientation:\s*\n[\s\S]*?\n\s*Center\s+Atomic\s+Atomic\s+Coordinates \(Angstroms\)\s*\n[\s\S]*?(?=\n\s*$|\n\n)",
        r"Input orientation:\s*\n[\s\S]*?\n\s*Center\s+Atomic\s+Atomic\s+Coordinates \(Angstroms\)\s*\n[\s\S]*?(?=\n\s*$|\n\n)",
    ]
    coords_text = None
    for pattern in patterns:
        match = re.search(pattern, content)
        if match:
            coords_text = match.group()
            break
    if coords_text:
        for line in coords_text.split('\n'):
            parts = line.split()
            if len(parts) >= 6 and parts[0].isdigit():
                idx = int(parts[0])
                an = int(parts[1])
                sym = ELEMENT_SYMBOLS.get(an, 'X')
                x = float(parts[3])
                y = float(parts[4])
                z = float(parts[5])
                atoms.append((idx, sym, an, (x, y, z)))
    return atoms


def get_atoms_from_any(filepath):
    """Auto-detect file type and parse atoms."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == '.xyz':
        return parse_xyz_file(filepath)
    elif ext in ('.gjf', '.com'):
        return parse_gjf_file(filepath)
    elif ext == '.log':
        return parse_log_file(filepath)
    else:
        atoms = parse_xyz_file(filepath)
        if not atoms:
            atoms = parse_gjf_file(filepath)
        if not atoms:
            atoms = parse_log_file(filepath)
        return atoms


# ── MolCanvas ────────────────────────────────────────

class MolCanvas(QWidget):
    """Pure PyQt5 QWidget 3D molecule renderer using QPainter.
    Quaternion arcball rotation, 17 visual styles, dash bonds, box-select."""

    atom_clicked = pyqtSignal(int)
    box_selected = pyqtSignal(list)

    _NON_METALS = {
        'H', 'He', 'B', 'C', 'N', 'O', 'F', 'Ne',
        'Si', 'P', 'S', 'Cl', 'Ar',
        'Ge', 'As', 'Se', 'Br', 'Kr',
        'Sb', 'Te', 'I', 'Xe', 'Rn', 'At',
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.atoms = []
        self.bonds = []
        # ── Quaternion-based rotation (no gimbal lock) ──
        self._rot_q = self._euler_to_quat(30.0, -45.0, 0.0)
        self._drag_q = None
        self.arcball_speed = 2.0
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.scale = 80.0
        self.border_radius = 8
        self.selected_atom = None
        # ── ETS-NOCV additions ──
        self.selected_atom2 = None      # second selection for dash mode (cyan ring)
        self.selected_atoms = set()     # box-select multi-selection
        self.fragment_atoms = {}        # {frag_idx: {atom_idx, ...}}
        self.fragment_colors = ['#FF6B6B', '#4ECDC4', '#FFE66D', '#95E1D3', '#DDA0DD',
                                '#F39C12', '#8E44AD', '#1ABC9C', '#E74C3C', '#3498DB']
        self.on_atom_click = None       # callback (legacy), prefer atom_clicked signal

        # 风格属性（默认 HoukMol）
        self._current_style = "HoukMol"
        self.bg_gradient = True
        self.bg_colors = ("#E8EDF5", "#F5F7FB", "#FFFFFF")
        self.bond_color_hex = "#000000"
        self.atom_scale = 0.30
        self.bond_width = 10
        self.show_shadows = True
        self.show_crosshair = False
        self.rim_visible = False
        self.gradient_type = "gau_default"
        self.label_mode = 2

        # 环线十字准星角度
        self.ring_a_angle = 90
        self.ring_a_tilt = 71
        self.ring_b_angle = 205
        self.ring_b_tilt = 0

        self._drag_start = None
        self._drag_pan = None
        self._click_pos = None
        self._projected = []

        # ── Box select (ETS-NOCV) ──
        self._box_selecting = False
        self._box_start = None
        self._box_current = None

        # ── Dash bond mode ──
        self.custom_dash_lines = []
        self._removed_bonds = []
        self._dash_bond_mode = False
        self._dash_bond_atom1 = None
        self.dash_color_hex = '#000000'
        self.dash_style = 'dash'
        self.dash_dot_radius = 3.0
        self.dash_dot_spacing = 8.0
        self.dash_dot_count = 0
        self.on_dash_added = None
        self.on_dash_undone = None
        self.on_dash_cleared = None

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(400, 300)

    def set_data(self, atoms, bonds):
        """Load atoms and bonds data, resetting selection state."""
        self.atoms = atoms
        self.bonds = bonds
        self.selected_atom = None
        self.selected_atom2 = None
        self.selected_atoms = set()
        self.fragment_atoms = {}
        self.auto_fit()
        self.repaint()

    def set_style(self, style_key):
        """应用一个风格预设。"""
        if style_key not in STYLE_PRESETS:
            return
        p = STYLE_PRESETS[style_key]
        self._current_style = style_key
        self.bg_gradient = p["bg_gradient"]
        self.bg_colors = p["bg_colors"]
        self.bond_color_hex = p["bond_color"]
        self.atom_scale = p["atom_scale"]
        self.bond_width = p["bond_width"]
        self.show_shadows = p["shadows"]
        self.show_crosshair = p["crosshair"]
        self.rim_visible = p["rim"]
        self.gradient_type = p["gradient"]
        self.label_mode = p["label_mode"]
        self.update()

    # ── Quaternion math (no gimbal lock) ──

    @staticmethod
    def _quat_mul(a, b):
        aw, ax, ay, az = a
        bw, bx, by, bz = b
        return [
            aw*bw - ax*bx - ay*by - az*bz,
            aw*bx + ax*bw + ay*bz - az*by,
            aw*by - ax*bz + ay*bw + az*bx,
            aw*bz + ax*by - ay*bx + az*bw,
        ]

    @staticmethod
    def _quat_normalize(q):
        w, x, y, z = q
        n = math.sqrt(w*w + x*x + y*y + z*z)
        if n < 1e-12:
            return [1.0, 0.0, 0.0, 0.0]
        return [w/n, x/n, y/n, z/n]

    @staticmethod
    def _quat_rotate(q, x, y, z):
        qw, qx, qy, qz = q
        t0 = -qx*x - qy*y - qz*z
        t1 = qw*x + qy*z - qz*y
        t2 = qw*y - qx*z + qz*x
        t3 = qw*z + qx*y - qy*x
        r1 = -t0*qx + t1*qw - t2*qz + t3*qy
        r2 = -t0*qy + t1*qz + t2*qw - t3*qx
        r3 = -t0*qz - t1*qy + t2*qx + t3*qw
        return r1, r2, r3

    @staticmethod
    def _euler_to_quat(rx_deg, ry_deg, rz_deg):
        rx, ry, rz = math.radians(rx_deg), math.radians(ry_deg), math.radians(rz_deg)
        cx, sx = math.cos(rx*0.5), math.sin(rx*0.5)
        cy, sy = math.cos(ry*0.5), math.sin(ry*0.5)
        cz, sz = math.cos(rz*0.5), math.sin(rz*0.5)
        qw = cz*cy*cx + sz*sy*sx
        qx = cz*cy*sx - sz*sy*cx
        qy = cz*sy*cx + sz*cy*sx
        qz = sz*cy*cx - cz*sy*sx
        return [qw, qx, qy, qz]

    @staticmethod
    def _quat_to_euler_zyx(q, deg=False):
        qw, qx, qy, qz = q
        r20 = 2*(qx*qz - qw*qy)
        r21 = 2*(qy*qz + qw*qx)
        r22 = 1 - 2*(qx*qx + qy*qy)
        r10 = 2*(qx*qy + qw*qz)
        r00 = 1 - 2*(qy*qy + qz*qz)
        ry_rad = math.atan2(-r20, math.sqrt(r21*r21 + r22*r22))
        rx_rad = math.atan2(r21, r22)
        rz_rad = math.atan2(r10, r00)
        if deg:
            return math.degrees(rx_rad), math.degrees(ry_rad), math.degrees(rz_rad)
        return rx_rad, ry_rad, rz_rad

    # ── Read-only Euler-angle properties (backward compat) ──
    @property
    def rot_x(self):
        return self._quat_to_euler_zyx(self._rot_q, deg=True)[0]
    @property
    def rot_y(self):
        return self._quat_to_euler_zyx(self._rot_q, deg=True)[1]
    @property
    def rot_z(self):
        return self._quat_to_euler_zyx(self._rot_q, deg=True)[2]

    def _arcball_point(self, screen_x, screen_y, w, h):
        nx = (2.0 * screen_x / w) - 1.0
        ny = 1.0 - (2.0 * screen_y / h)
        d2 = nx*nx + ny*ny
        if d2 <= 1.0:
            return (nx, ny, math.sqrt(1.0 - d2))
        else:
            d = math.sqrt(d2)
            return (nx/d, ny/d, 0.0)

    def _apply_arcball_rotation(self, x0, y0, x1, y1, base_q):
        w, h = self.width(), self.height()
        if w < 2 or h < 2:
            return base_q
        p0 = self._arcball_point(x0, y0, w, h)
        p1 = self._arcball_point(x1, y1, w, h)
        ax = p0[1]*p1[2] - p0[2]*p1[1]
        ay = p0[2]*p1[0] - p0[0]*p1[2]
        az = p0[0]*p1[1] - p0[1]*p1[0]
        dot = p0[0]*p1[0] + p0[1]*p1[1] + p0[2]*p1[2]
        dot = max(-1.0, min(1.0, dot))
        angle = math.acos(dot) * self.arcball_speed
        if angle < 0.0005:
            return base_q
        norm = math.sqrt(ax*ax + ay*ay + az*az)
        if norm < 1e-12:
            return base_q
        ax, ay, az = ax/norm, ay/norm, az/norm
        c = math.cos(angle * 0.5)
        s = math.sin(angle * 0.5)
        dq = [c, s*ax, s*ay, s*az]
        return self._quat_normalize(self._quat_mul(dq, base_q))

    def _rotate(self, x, y, z):
        return self._quat_rotate(self._rot_q, x, y, z)

    def _project(self, x, y, z):
        cw = self.width()
        ch = self.height()
        px, py, pz = self._rotate(x, y, z)
        s = self.scale * self.zoom
        return cw / 2 + px * s + self.pan_x, ch / 2 - py * s + self.pan_y, pz

    def _atom_screen_radius(self, sym):
        r = ATOM_RADII.get(sym, 0.7) * self.scale * self.zoom * self.atom_scale
        if sym == 'H':
            r *= 1.125
        elif sym in self._NON_METALS:
            r *= 1.15
        else:
            r *= 0.85
        return max(r, 3)

    def _depth_factor(self, z_val):
        return max(0.3, min(1.0, 0.5 + 0.5 * ((z_val + 10) / 20)))

    @staticmethod
    def _hex_to_rgb(hex_color):
        return (
            int(hex_color[1:3], 16),
            int(hex_color[3:5], 16),
            int(hex_color[5:7], 16),
        )

    @staticmethod
    def _brighten(hex_color, factor=0.25):
        r, g, b = MolCanvas._hex_to_rgb(hex_color)
        r = min(255, int(r + (255 - r) * factor))
        g = min(255, int(g + (255 - g) * factor))
        b = min(255, int(b + (255 - b) * factor))
        return f"#{r:02X}{g:02X}{b:02X}"

    @staticmethod
    def _brighten_color(c, f=0.25):
        return QColor(
            min(255, int(c.red() + (255 - c.red()) * f)),
            min(255, int(c.green() + (255 - c.green()) * f)),
            min(255, int(c.blue() + (255 - c.blue()) * f)),
        )

    @classmethod
    def _mix_hex(cls, hex_color, target="#FFFFFF", amount=0.5):
        r, g, b = cls._hex_to_rgb(hex_color)
        rt, gt, bt = cls._hex_to_rgb(target)
        r = int(r * (1 - amount) + rt * amount)
        g = int(g * (1 - amount) + gt * amount)
        b = int(b * (1 - amount) + bt * amount)
        return f"#{r:02X}{g:02X}{b:02X}"

    def _get_atom_color(self, sym, idx=None):
        """根据当前风格返回原子颜色，支持 fragment 覆盖。"""
        # Fragment override — check fragment_atoms first
        if idx is not None:
            for f_idx, f_atoms in self.fragment_atoms.items():
                if idx in f_atoms:
                    return self.fragment_colors[f_idx % len(self.fragment_colors)]

        style = self._current_style
        if style == "VMD":
            return ATOM_COLORS.get(sym, '#AAAAAA')
        if style == "SobArt":
            return SOB_ART_CPK.get(sym, '#AAAAAA')
        if style == "HoukMol":
            return ATOM_COLORS.get(sym, '#B8B8B8')
        if style in ("AppleLiquid", "GlassPlus"):
            return APPLE_CPK.get(sym, '#AEB8C4')
        if style in ("ModernPaper", "HoukPremium"):
            return PAPER_CPK.get(sym, self._brighten(ATOM_COLORS.get(sym, '#AAAAAA'), 0.18))
        if style == "SoftClay":
            return CLAY_CPK.get(sym, self._mix_hex(ATOM_COLORS.get(sym, '#AAAAAA'), "#D8D0C2", 0.32))
        if style == "InkMinimal":
            return self._mix_hex(PAPER_CPK.get(sym, ATOM_COLORS.get(sym, '#AAAAAA')), "#FFFFFF", 0.34)
        return self._brighten(ATOM_COLORS.get(sym, '#AAAAAA'))

    @staticmethod
    def _clamp_color(rv, gv, bv, df):
        return QColor(
            max(0, min(255, int(rv * df))),
            max(0, min(255, int(gv * df))),
            max(0, min(255, int(bv * df))),
        )

    def _make_sphere_gradient(self, hex_color, r, sx, sy, depth_factor):
        r0, g0, b0 = self._hex_to_rgb(hex_color)
        df = depth_factor
        ho = r * 0.3
        grad = QRadialGradient(QPointF(sx - ho, sy - ho), r)
        gt = self.gradient_type

        def c(rv, gv, bv):
            return self._clamp_color(rv, gv, bv, df)

        if gt == "flat":
            grad.setColorAt(0.0, c(r0, g0, b0))
            grad.setColorAt(1.0, c(r0, g0, b0))
            return grad

        if gt == "ink_flat":
            grad.setColorAt(0.0, QColor(hex_color))
            grad.setColorAt(1.0, QColor(hex_color))
            return grad

        if gt == "gau_default":
            base = QColor(hex_color)
            ho2 = r * 0.25
            grad2 = QRadialGradient(QPointF(sx - ho2, sy - ho2), r)
            grad2.setColorAt(0.0, self._brighten_color(base, 0.5))
            grad2.setColorAt(0.15, self._brighten_color(base, 0.2))
            grad2.setColorAt(0.5, base)
            grad2.setColorAt(0.85, base.darker(140))
            grad2.setColorAt(1.0, base.darker(180))
            return grad2

        if gt == "sob_art":
            grad.setColorAt(0.00, c(min(255, r0 + 95), min(255, g0 + 95), min(255, b0 + 95)))
            grad.setColorAt(0.06, c(r0 + (255 - r0) * 0.90, g0 + (255 - g0) * 0.90, b0 + (255 - b0) * 0.90))
            grad.setColorAt(0.14, c(r0, g0, b0))
            grad.setColorAt(0.40, c(r0, g0, b0))
            grad.setColorAt(0.68, c(int(r0 * 0.80), int(g0 * 0.80), int(b0 * 0.80)))
            grad.setColorAt(1.00, c(int(r0 * 0.55), int(g0 * 0.55), int(b0 * 0.55)))
            return grad

        if gt == "apple_liquid":
            grad.setColorAt(0.00, c(min(255, r0 + 85), min(255, g0 + 85), min(255, b0 + 85)))
            grad.setColorAt(0.08, c(min(255, r0 + 55), min(255, g0 + 55), min(255, b0 + 55)))
            grad.setColorAt(0.30, c(r0, g0, b0))
            grad.setColorAt(0.70, c(int(r0 * 0.95), int(g0 * 0.95), int(b0 * 0.95)))
            grad.setColorAt(1.00, c(int(r0 * 0.75), int(g0 * 0.75), int(b0 * 0.75)))
            return grad

        if gt == "paper_matte":
            grad.setColorAt(0.00, c(r0 + (255 - r0) * 0.62, g0 + (255 - g0) * 0.62, b0 + (255 - b0) * 0.62))
            grad.setColorAt(0.18, c(r0 + (255 - r0) * 0.26, g0 + (255 - g0) * 0.26, b0 + (255 - b0) * 0.26))
            grad.setColorAt(0.56, c(r0, g0, b0))
            grad.setColorAt(0.86, c(int(r0 * 0.90), int(g0 * 0.90), int(b0 * 0.90)))
            grad.setColorAt(1.00, c(int(r0 * 0.78), int(g0 * 0.78), int(b0 * 0.78)))
            return grad

        if gt == "premium_full":
            grad.setColorAt(0.00, c(min(255, r0 + 58), min(255, g0 + 58), min(255, b0 + 58)))
            grad.setColorAt(0.05, c(r0 + (255 - r0) * 0.78, g0 + (255 - g0) * 0.78, b0 + (255 - b0) * 0.78))
            grad.setColorAt(0.20, c(r0 + (255 - r0) * 0.34, g0 + (255 - g0) * 0.34, b0 + (255 - b0) * 0.34))
            grad.setColorAt(0.52, c(r0, g0, b0))
            grad.setColorAt(0.82, c(int(r0 * 0.84), int(g0 * 0.84), int(b0 * 0.84)))
            grad.setColorAt(1.00, c(int(r0 * 0.68), int(g0 * 0.68), int(b0 * 0.68)))
            return grad

        if gt == "clay_matte":
            grad.setColorAt(0.00, c(r0 + (255 - r0) * 0.42, g0 + (255 - g0) * 0.42, b0 + (255 - b0) * 0.42))
            grad.setColorAt(0.20, c(r0 + (255 - r0) * 0.12, g0 + (255 - g0) * 0.12, b0 + (255 - b0) * 0.12))
            grad.setColorAt(0.62, c(r0, g0, b0))
            grad.setColorAt(0.84, c(int(r0 * 0.88), int(g0 * 0.88), int(b0 * 0.88)))
            grad.setColorAt(1.00, c(int(r0 * 0.70), int(g0 * 0.70), int(b0 * 0.70)))
            return grad

        if gt == "glass_plus":
            grad.setColorAt(0.00, c(min(255, r0 + 110), min(255, g0 + 110), min(255, b0 + 110)))
            grad.setColorAt(0.07, c(r0 + (255 - r0) * 0.92, g0 + (255 - g0) * 0.92, b0 + (255 - b0) * 0.92))
            grad.setColorAt(0.24, c(r0 + (255 - r0) * 0.32, g0 + (255 - g0) * 0.32, b0 + (255 - b0) * 0.32))
            grad.setColorAt(0.58, c(r0, g0, b0))
            grad.setColorAt(0.82, c(int(r0 * 1.08), int(g0 * 1.08), int(b0 * 1.08)))
            grad.setColorAt(1.00, c(int(r0 * 0.66), int(g0 * 0.66), int(b0 * 0.66)))
            return grad

        if gt == "neon_glow":
            grad.setColorAt(0.00, c(min(255, r0 + 120), min(255, g0 + 120), min(255, b0 + 120)))
            grad.setColorAt(0.10, c(min(255, r0 + 72), min(255, g0 + 72), min(255, b0 + 72)))
            grad.setColorAt(0.34, c(r0, g0, b0))
            grad.setColorAt(0.70, c(int(r0 * 0.72), int(g0 * 0.72), int(b0 * 0.72)))
            grad.setColorAt(1.00, c(int(r0 * 0.42), int(g0 * 0.42), int(b0 * 0.42)))
            return grad

        if gt == "subtle":
            grad.setColorAt(0.00, c(min(255, r0 + 35), min(255, g0 + 35), min(255, b0 + 35)))
            grad.setColorAt(0.12, c(r0 + (255 - r0) * 0.40, g0 + (255 - g0) * 0.40, b0 + (255 - b0) * 0.40))
            grad.setColorAt(0.40, c(r0, g0, b0))
            grad.setColorAt(0.80, c(int(r0 * 0.85), int(g0 * 0.85), int(b0 * 0.85)))
            grad.setColorAt(1.00, c(int(r0 * 0.72), int(g0 * 0.72), int(b0 * 0.72)))
            return grad

        if gt == "soft_matte":
            grad.setColorAt(0.00, c(min(255, r0 + 55), min(255, g0 + 55), min(255, b0 + 55)))
            grad.setColorAt(0.08, c(r0 + (255 - r0) * 0.15, g0 + (255 - g0) * 0.15, b0 + (255 - b0) * 0.15))
            grad.setColorAt(0.25, c(r0, g0, b0))
            grad.setColorAt(0.60, c(r0, g0, b0))
            grad.setColorAt(0.82, c(int(r0 * 0.82), int(g0 * 0.82), int(b0 * 0.82)))
            grad.setColorAt(1.00, c(int(r0 * 0.62), int(g0 * 0.62), int(b0 * 0.62)))
            return grad

        # fallback "full"
        grad.setColorAt(0.00, c(min(255, r0 + 35), min(255, g0 + 35), min(255, b0 + 35)))
        grad.setColorAt(0.06, c(r0 + (255 - r0) * 0.75, g0 + (255 - g0) * 0.75, b0 + (255 - b0) * 0.75))
        grad.setColorAt(0.18, c(r0 + (255 - r0) * 0.30, g0 + (255 - g0) * 0.30, b0 + (255 - b0) * 0.30))
        grad.setColorAt(0.40, c(r0 + (255 - r0) * 0.05, g0 + (255 - g0) * 0.05, b0 + (255 - b0) * 0.05))
        grad.setColorAt(0.65, c(r0, g0, b0))
        grad.setColorAt(0.85, c(int(r0 * 0.86), int(g0 * 0.86), int(b0 * 0.86)))
        grad.setColorAt(1.00, c(int(r0 * 0.75), int(g0 * 0.75), int(b0 * 0.75)))
        return grad

    def _find_nearest_atom(self, mx, my):
        best, best_dist = None, float('inf')
        for i, (sx, sy, sz, r) in enumerate(self._projected):
            d = math.sqrt((mx - sx)**2 + (my - sy)**2)
            if d < max(r, 10) and d < best_dist:
                best, best_dist = i + 1, d
        return best

    def auto_fit(self):
        if not self.atoms:
            return
        max_extent = 0.0
        for _, _, _, (x, y, z) in self.atoms:
            max_extent = max(max_extent, abs(x), abs(y), abs(z))
        self._rot_q = self._euler_to_quat(30.0, -45.0, 0.0)
        self.zoom = 1.0
        self.pan_x, self.pan_y = 0.0, 0.0
        dim = min(self.width(), self.height())
        if dim <= 1:
            dim = 400
        self.scale = dim / (max_extent * 2.8 + 1)

    def showEvent(self, event):
        super().showEvent(event)
        if self.atoms:
            self.auto_fit()
            self.repaint()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.atoms:
            self.auto_fit()

    # ── Box select helpers ──

    def _box_select_atoms(self):
        """Collect atom indices whose screen projection falls inside the box."""
        if not self._box_start or not self._box_current:
            return []
        x1, y1 = self._box_start
        x2, y2 = self._box_current
        x_min, x_max = min(x1, x2), max(x1, x2)
        y_min, y_max = min(y1, y2), max(y1, y2)
        selected = []
        for i, (sx, sy, sz, r) in enumerate(self._projected):
            if x_min <= sx <= x_max and y_min <= sy <= y_max:
                selected.append(self.atoms[i][0])
        return selected

    # ── Mouse Events ──

    def mousePressEvent(self, event):
        shift = bool(QApplication.keyboardModifiers() & Qt.ShiftModifier)
        if event.button() == Qt.LeftButton and shift:
            self._box_selecting = True
            self._box_start = (event.x(), event.y())
            self._box_current = (event.x(), event.y())
            self.update()
            return
        if event.button() == Qt.LeftButton:
            self._drag_start = (event.x(), event.y())
            self._drag_q = list(self._rot_q)
            self._drag_pan = (self.pan_x, self.pan_y)
            self._click_pos = (event.x(), event.y())
        elif event.button() == Qt.RightButton:
            self._drag_start = (event.x(), event.y())
            self._drag_pan = (self.pan_x, self.pan_y)
            self._click_pos = None

    def mouseMoveEvent(self, event):
        if self._box_selecting:
            self._box_current = (event.x(), event.y())
            self.update()
            return
        if self._drag_start is None:
            return
        if event.buttons() & Qt.LeftButton:
            self._rot_q = self._apply_arcball_rotation(
                self._drag_start[0], self._drag_start[1],
                event.x(), event.y(), self._drag_q)
            self.repaint()
        elif event.buttons() & Qt.RightButton:
            dx = event.x() - self._drag_start[0]
            dy = event.y() - self._drag_start[1]
            self.pan_x = self._drag_pan[0] + dx
            self.pan_y = self._drag_pan[1] + dy
            self.repaint()

    def mouseReleaseEvent(self, event):
        # ── 框选结束 ──
        if self._box_selecting:
            self._box_selecting = False
            selected = self._box_select_atoms()
            self._box_start = None
            self._box_current = None
            if selected:
                self.selected_atoms = set(selected)
                QTimer.singleShot(0, lambda s=selected: self.box_selected.emit(s))
            self.update()
            return

        # ── 虚线模式：选中两个原子画虚线 ──
        if self._dash_bond_mode and self._click_pos:
            dx = event.x() - self._click_pos[0]
            dy = event.y() - self._click_pos[1]
            if abs(dx) < 5 and abs(dy) < 5:
                atom_idx = self._find_nearest_atom(event.x(), event.y())
                if atom_idx is not None:
                    if self._dash_bond_atom1 is None:
                        self._dash_bond_atom1 = atom_idx
                        self.selected_atom = atom_idx
                        self.selected_atom2 = None
                    else:
                        if atom_idx != self._dash_bond_atom1:
                            a1, a2 = self._dash_bond_atom1, atom_idx
                            self.custom_dash_lines.append((a1, a2, self.dash_color_hex))
                            removed = self._remove_bond(a1, a2)
                            self._removed_bonds.append(removed)
                            self._dash_bond_atom1 = None
                            self.selected_atom = None
                            self.selected_atom2 = None
                            self.repaint()
                            a1_fix, a2_fix = min(a1, a2), max(a1, a2)
                            if self.on_dash_added:
                                self.on_dash_added(a1_fix, a2_fix)
                        else:
                            self._dash_bond_atom1 = None
                            self.selected_atom = None
                            self.selected_atom2 = None
                            self.repaint()
                self._drag_start, self._click_pos = None, None
                return

        # ── 普通点击：emit atom_clicked signal + callback ──
        if self._click_pos and event.button() == Qt.LeftButton:
            dx = event.x() - self._click_pos[0]
            dy = event.y() - self._click_pos[1]
            if abs(dx) < 5 and abs(dy) < 5:
                atom_idx = self._find_nearest_atom(event.x(), event.y())
                if atom_idx is not None:
                    self.selected_atom = atom_idx
                    self.repaint()
                    QTimer.singleShot(0, lambda a=atom_idx: self.atom_clicked.emit(a))
                    if self.on_atom_click:
                        self.on_atom_click(atom_idx)
                else:
                    self.selected_atom = None
                    self.repaint()
        self._drag_start, self._click_pos = None, None

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        self.zoom = max(0.1, min(20.0, self.zoom * (1.1 if delta > 0 else 0.9)))
        self.repaint()

    # ── Dash bond methods ──

    def _remove_bond(self, a1, a2):
        """移除 a1 和 a2 之间的键（若存在），返回被移除的键或 None。"""
        pair = (min(a1, a2), max(a1, a2))
        for i, (b1, b2) in enumerate(self.bonds):
            if (min(b1, b2), max(b1, b2)) == pair:
                return self.bonds.pop(i)
        return None

    def set_dash_bond_mode(self, enabled):
        """开启/关闭虚线模式。"""
        self._dash_bond_mode = enabled
        if not enabled:
            self._dash_bond_atom1 = None
            self.selected_atom = None
            self.selected_atom2 = None
            self.repaint()

    def clear_dash_lines(self):
        """清除所有虚线并恢复被移除的键。"""
        for removed in self._removed_bonds:
            if removed:
                self.bonds.append(removed)
        self.custom_dash_lines.clear()
        self._removed_bonds.clear()
        self._dash_bond_atom1 = None
        self.selected_atom = None
        self.selected_atom2 = None
        self.repaint()
        if self.on_dash_cleared:
            self.on_dash_cleared()

    def undo_last_dash_line(self):
        """撤销最后一条虚线并恢复对应键。"""
        if self.custom_dash_lines:
            self.custom_dash_lines.pop()
            removed = self._removed_bonds.pop() if self._removed_bonds else None
            if removed:
                self.bonds.append(removed)
            self.repaint()
            if self.on_dash_undone:
                self.on_dash_undone()

    # ── Paint ──

    def paintEvent(self, event):
        bg0, bg1, bg2 = self.bg_colors
        is_dark = self._current_style in ("DarkPro", "DarkNeon", "VMD")
        is_gau = self._current_style == "HoukMol"

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # 裁剪圆角，防止内容溢出边框
        if self.border_radius > 0:
            path = QPainterPath()
            r = QRectF(self.rect())
            path.addRoundedRect(r, self.border_radius, self.border_radius)
            painter.setClipPath(path)

        # 背景
        if self.bg_gradient:
            bg = QLinearGradient(0, 0, 0, self.height())
            bg.setColorAt(0.0, QColor(bg0))
            bg.setColorAt(0.5, QColor(bg1))
            bg.setColorAt(1.0, QColor(bg2))
            painter.fillRect(self.rect(), QBrush(bg))
        else:
            painter.fillRect(self.rect(), Qt.black if is_dark else Qt.white)

        if not self.atoms:
            painter.setPen(QColor('#94A3B8') if not is_dark else QColor('#586E8A'))
            painter.drawText(self.rect(), Qt.AlignCenter, "Load a file to display molecular structure")
            # Box select overlay can still be drawn on empty canvas
            if self._box_selecting and self._box_start and self._box_current:
                x1, y1 = self._box_start
                x2, y2 = self._box_current
                x_min, x_max = min(x1, x2), max(x1, x2)
                y_min, y_max = min(y1, y2), max(y1, y2)
                painter.setPen(QPen(QColor(0, 255, 0), 1.5, style=Qt.DashLine))
                painter.setBrush(QColor(0, 255, 0, 30))
                painter.drawRect(x_min, y_min, x_max - x_min, y_max - y_min)
            painter.end()
            return

        # 投影
        self._projected = []
        for idx, sym, an, (x, y, z) in self.atoms:
            try:
                sx, sy, sz = self._project(x, y, z)
            except Exception:
                continue
            r = self._atom_screen_radius(sym)
            self._projected.append((sx, sy, sz, r))
        if not self._projected:
            painter.end()
            return

        # ── 统一深度排序队列（键+原子混合排序，解决穿透问题）──
        draw_queue = []  # (z, type, data)

        for a1_idx, a2_idx in self.bonds:
            i1, i2 = a1_idx - 1, a2_idx - 1
            if 0 <= i1 < len(self._projected) and 0 <= i2 < len(self._projected):
                p1, p2 = self._projected[i1], self._projected[i2]
                sx1, sy1, sr1 = p1[0], p1[1], p1[3]
                sx2, sy2, sr2 = p2[0], p2[1], p2[3]
                dx, dy = sx2 - sx1, sy2 - sy1
                length = math.sqrt(dx * dx + dy * dy)
                if length < 1:
                    continue
                avg_z = (p1[2] + p2[2]) / 2
                df = self._depth_factor(avg_z)
                w = max(1.5, self.bond_width * self.zoom * df)
                cut1, cut2 = sr1 * 0.85, sr2 * 0.85
                r1 = cut1 / length
                r2 = cut2 / length
                x1 = sx1 + dx * r1; y1 = sy1 + dy * r1
                x2 = sx2 - dx * r2; y2 = sy2 - dy * r2
                nx = -dy / length; ny = dx / length
                hw = w * 0.5
                cx1, cy1 = x1 + nx * hw, y1 + ny * hw
                cx2, cy2 = x1 - nx * hw, y1 - ny * hw
                cx3, cy3 = x2 - nx * hw, y2 - ny * hw
                cx4, cy4 = x2 + nx * hw, y2 + ny * hw
                mid_x, mid_y = (x1 + x2) / 2, (y1 + y2) / 2
                draw_queue.append((avg_z, 'bond', {
                    'i1': i1, 'i2': i2, 'df': df, 'w': w,
                    'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2,
                    'nx': nx, 'ny': ny, 'hw': hw,
                    'cx1': cx1, 'cy1': cy1, 'cx2': cx2, 'cy2': cy2,
                    'cx3': cx3, 'cy3': cy3, 'cx4': cx4, 'cy4': cy4,
                    'mid_x': mid_x, 'mid_y': mid_y,
                }))

        # dash bonds
        if self.custom_dash_lines:
            for a1, a2, color_hex in self.custom_dash_lines:
                if a1 <= len(self._projected) and a2 <= len(self._projected):
                    p1 = self._projected[a1 - 1]
                    p2 = self._projected[a2 - 1]
                    avg_z = (p1[2] + p2[2]) / 2
                    draw_queue.append((avg_z, 'dash', {
                        'a1': a1, 'a2': a2, 'color_hex': color_hex,
                        'p1': p1, 'p2': p2,
                    }))

        # atoms
        for i, (sx, sy, sz, r) in enumerate(self._projected):
            draw_queue.append((sz, 'atom', {
                'i': i, 'sx': sx, 'sy': sy, 'r': r,
            }))

        draw_queue.sort(key=lambda x: x[0])

        is_sob_art = self._current_style == "SobArt"
        is_vmd = self._current_style == "VMD"
        is_neon = self._current_style == "DarkNeon"
        is_ink = self._current_style == "InkMinimal"
        is_glass = self._current_style in ("AppleLiquid", "GlassPlus")

        # ── 遍历绘制 ──
        for z_val, dtype, data in draw_queue:
            if dtype == 'bond':
                d = data
                ai, aj = d['i1'], d['i2']
                df, w = d['df'], d['w']
                x1, y1 = d['x1'], d['y1']; x2, y2 = d['x2'], d['y2']
                nx, ny = d['nx'], d['ny']; hw = d['hw']
                cx1, cy1 = d['cx1'], d['cy1']; cx2, cy2 = d['cx2'], d['cy2']
                cx3, cy3 = d['cx3'], d['cy3']; cx4, cy4 = d['cx4'], d['cy4']
                mid_x, mid_y = d['mid_x'], d['mid_y']

                if is_ink:
                    painter.save()
                    painter.setPen(QPen(QColor(self.bond_color_hex), max(1, int(w)), cap=Qt.RoundCap))
                    painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
                    painter.restore()
                    continue

                if is_gau:
                    bw = self.bond_width * self.zoom * (self.scale / 80)
                    painter.save()
                    painter.setPen(QPen(QColor(self.bond_color_hex), bw, Qt.SolidLine, Qt.RoundCap))
                    painter.setBrush(Qt.NoBrush)
                    painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
                    painter.restore()
                    continue

                elif is_sob_art or is_vmd:
                    sym1 = self.atoms[ai][1]; sym2 = self.atoms[aj][1]
                    col1 = ATOM_COLORS.get(sym1, '#AAAAAA') if is_vmd else SOB_ART_CPK.get(sym1, '#AAAAAA')
                    col2 = ATOM_COLORS.get(sym2, '#AAAAAA') if is_vmd else SOB_ART_CPK.get(sym2, '#AAAAAA')
                    mcx1, mcy1 = (cx1 + cx4) / 2, (cy1 + cy4) / 2
                    mcx2, mcy2 = (cx2 + cx3) / 2, (cy2 + cy3) / 2
                    for half, col_hex in [(0, col1), (1, col2)]:
                        if half == 0:
                            ax1,ay1,ax2,ay2,ax3,ay3,ax4,ay4 = cx1,cy1,cx2,cy2,mcx2,mcy2,mcx1,mcy1
                        else:
                            ax1,ay1,ax2,ay2,ax3,ay3,ax4,ay4 = mcx1,mcy1,mcx2,mcy2,cx3,cy3,cx4,cy4
                        r_b, g_b, b_b = self._hex_to_rgb(col_hex)
                        gmid_x = (ax1 + ax4) / 2; gmid_y = (ay1 + ay4) / 2
                        knx = ax2 - ax1; kny = ay2 - ay1
                        klen = max(1, math.sqrt(knx * knx + kny * kny))
                        knx, kny = knx / klen, kny / klen
                        ks = QLinearGradient(gmid_x - knx * hw, gmid_y - kny * hw,
                                             gmid_x + knx * hw, gmid_y + kny * hw)
                        for t, f in [(0.00,0.62),(0.15,0.80),(0.30,0.96),(0.44,1.15),
                                     (0.56,1.10),(0.70,0.92),(0.85,0.70),(1.00,0.55)]:
                            ks.setColorAt(t, QColor(max(0,min(255,int(r_b*df*f))),
                                                   max(0,min(255,int(g_b*df*f))),
                                                   max(0,min(255,int(b_b*df*f)))))
                        path = QPainterPath()
                        path.moveTo(ax1, ay1); path.lineTo(ax4, ay4)
                        path.lineTo(ax3, ay3); path.lineTo(ax2, ay2); path.closeSubpath()
                        painter.setPen(Qt.NoPen); painter.setBrush(QBrush(ks)); painter.drawPath(path)
                else:
                    bond_rgb = self._hex_to_rgb(self.bond_color_hex)
                    r_b, g_b, b_b = bond_rgb
                    ks = QLinearGradient(mid_x - nx * hw, mid_y - ny * hw,
                                         mid_x + nx * hw, mid_y + ny * hw)
                    def bc(factor):
                        return QColor(max(0,min(255,int(r_b*df*factor))),
                                     max(0,min(255,int(g_b*df*factor))),
                                     max(0,min(255,int(b_b*df*factor))))
                    for t, f in [(0.00,0.42),(0.15,0.60),(0.30,0.88),(0.44,1.07),
                                 (0.56,1.03),(0.70,0.80),(0.85,0.52),(1.00,0.38)]:
                        ks.setColorAt(t, bc(f))
                    path = QPainterPath()
                    path.moveTo(cx1, cy1); path.lineTo(cx4, cy4)
                    path.lineTo(cx3, cy3); path.lineTo(cx2, cy2); path.closeSubpath()
                    if is_neon:
                        painter.save(); painter.setOpacity(0.14)
                        painter.setPen(QPen(QColor("#8FB8FF"), max(2, int(w * 2.8)), cap=Qt.RoundCap))
                        painter.drawLine(QPointF(x1, y1), QPointF(x2, y2)); painter.restore()
                    painter.setPen(Qt.NoPen); painter.setBrush(QBrush(ks)); painter.drawPath(path)

            elif dtype == 'dash':
                d = data
                p1, p2 = d['p1'], d['p2']
                sx1, sy1, sr1 = p1[0], p1[1], p1[3]
                sx2, sy2, sr2 = p2[0], p2[1], p2[3]
                dx, dy = sx2 - sx1, sy2 - sy1
                length = math.sqrt(dx * dx + dy * dy)
                if length < 1:
                    continue
                df = max(0.3, min(1.0, 0.5 + 0.5 * ((z_val + 10) / 20)))
                cut1, cut2 = sr1 * 0.85, sr2 * 0.85
                ux, uy = dx / length, dy / length
                lx1, ly1 = sx1 + ux * cut1, sy1 + uy * cut1
                lx2, ly2 = sx2 - ux * cut2, sy2 - uy * cut2
                line_len = length - cut1 - cut2
                clr = QColor(self.dash_color_hex)
                clr.setAlpha(int(255 * df))
                if self.dash_style == 'dots':
                    dr = self.dash_dot_radius
                    spacing = max(4.0, self.dash_dot_spacing)
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QBrush(clr))
                    pos = dr
                    while pos < line_len - dr:
                        cx = lx1 + ux * pos; cy = ly1 + uy * pos
                        painter.drawEllipse(QPointF(cx, cy), dr, dr)
                        pos += spacing
                else:
                    lw = max(1.5, self.dash_dot_radius * 2)
                    if self.dash_dot_count > 1:
                        cycle = max(1.0, line_len / self.dash_dot_count)
                        dash_len = cycle * 0.35; gap = cycle * 0.65
                    else:
                        cycle = max(1.0, self.dash_dot_spacing)
                        dash_len = cycle * 0.4; gap = cycle * 0.6
                    dash_len = max(0.5, dash_len); gap = max(0.5, gap)
                    pen = QPen(clr, lw, cap=Qt.RoundCap)
                    pen.setDashPattern([dash_len / lw, gap / lw])
                    painter.setPen(pen)
                    painter.drawLine(QPointF(lx1, ly1), QPointF(lx2, ly2))

            elif dtype == 'atom':
                d = data
                i, sx, sy, r = d['i'], d['sx'], d['sy'], d['r']
                idx, sym, an, (ax, ay, az) = self.atoms[i]
                color = self._get_atom_color(sym, idx)
                df = self._depth_factor(z_val)
                cx, cy = int(sx), int(sy)
                ir = int(r)

                # 阴影
                if self.show_shadows and r >= 5:
                    opacity = 0.06 + 0.12 * df
                    shx, shy = int(sx + r * 0.3), int(sy + r * 0.55)
                    shrx, shry = int(r * 1.25), max(1, int(r * 0.32))
                    painter.save(); painter.setOpacity(opacity); painter.setPen(Qt.NoPen)
                    painter.setBrush(QBrush(QColor(0, 0, 0)))
                    painter.drawEllipse(QPoint(shx, shy), shrx, shry)
                    painter.restore()

                # DarkNeon glow
                if is_neon and ir > 4:
                    glow = QColor(color)
                    painter.save(); painter.setPen(Qt.NoPen)
                    for k, alpha in enumerate((34, 22, 12)):
                        glow.setAlpha(alpha); painter.setBrush(QBrush(glow))
                        painter.drawEllipse(QPoint(cx, cy), ir + 4 + k * 5, ir + 4 + k * 5)
                    painter.restore()

                # 球体
                sphere_grad = self._make_sphere_gradient(color, r, sx, sy, df)
                if is_gau:
                    painter.setPen(QPen(QColor("#000000"), 0.8))
                else:
                    painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(sphere_grad))
                painter.drawEllipse(QPoint(cx, cy), ir, ir)

                # Glass highlights
                if is_glass and ir > 4:
                    painter.save(); painter.setPen(Qt.NoPen)
                    painter.setBrush(QColor(255, 255, 255, 105 if self._current_style == "GlassPlus" else 90))
                    painter.drawEllipse(int(cx - ir * 0.42), int(cy - ir * 0.42), int(ir * 0.60), int(ir * 0.45))
                    painter.restore()
                if is_glass and ir > 4:
                    painter.save()
                    for k in range(4):
                        painter.setOpacity(0.055 - k * 0.010 if self._current_style == "GlassPlus" else 0.04 - k * 0.008)
                        painter.setPen(Qt.NoPen); painter.setBrush(QColor(255, 255, 255))
                        painter.drawEllipse(QPoint(cx, cy), ir + k * 2, ir + k * 2)
                    painter.restore()
                if is_glass and ir > 6:
                    painter.save()
                    painter.setOpacity(0.22 if self._current_style == "GlassPlus" else 0.15)
                    painter.setPen(Qt.NoPen); painter.setBrush(QColor(255, 255, 255))
                    path = QPainterPath()
                    path.moveTo(cx - ir * 0.6, cy - ir * 0.15)
                    path.quadTo(cx, cy - ir * 0.55, cx + ir * 0.55, cy - ir * 0.05)
                    path.quadTo(cx + ir * 0.38, cy - ir * 0.22, cx - ir * 0.5, cy - ir * 0.22)
                    path.closeSubpath()
                    painter.drawPath(path); painter.restore()

                # 轮廓线
                if ir > 6 and self.rim_visible:
                    gt = self.gradient_type
                    if gt == "sob_art":
                        rim = QColor(0, 0, 0, 200); rim_w = max(1, int(ir * 0.10))
                    elif gt == "flat":
                        rim = QColor(20, 20, 20); rim_w = max(1, int(ir * 0.12))
                    elif gt == "ink_flat":
                        rim = QColor(25, 25, 25, 210); rim_w = max(1, int(ir * 0.10))
                    elif gt == "glass_plus":
                        rim = QColor(255, 255, 255, 140); rim_w = max(1, int(ir * 0.06))
                    elif gt == "paper_matte":
                        rim = QColor(92, 111, 132, 90); rim_w = max(1, int(ir * 0.045))
                    elif gt == "clay_matte":
                        rim = QColor(92, 80, 70, 90); rim_w = max(1, int(ir * 0.055))
                    elif gt == "premium_full":
                        rim = QColor(24, 34, 46, 145); rim_w = max(1, int(ir * 0.055))
                    elif gt == "neon_glow":
                        rim = QColor(color); rim.setAlpha(210); rim_w = max(1, int(ir * 0.07))
                    elif gt == "soft_matte":
                        base_r = int(color[1:3],16); base_g = int(color[3:5],16); base_b = int(color[5:7],16)
                        rim = QColor(int(base_r*0.55+100*0.45), int(base_g*0.55+115*0.45),
                                     int(base_b*0.55+130*0.45), 110); rim_w = max(1, int(ir * 0.05))
                    elif is_dark:
                        rim = QColor(min(255, int(int(color[1:3],16)*df*0.50)),
                                     min(255, int(int(color[3:5],16)*df*0.50)),
                                     min(255, int(int(color[5:7],16)*df*0.50)))
                        rim_w = max(1, int(ir * 0.06))
                    else:
                        rim = QColor(int(int(color[1:3],16)*df*0.25),
                                     int(int(color[3:5],16)*df*0.25),
                                     int(int(color[5:7],16)*df*0.25))
                        rim_w = max(1, int(ir * 0.08))
                    painter.setPen(QPen(rim, rim_w)); painter.setBrush(Qt.NoBrush)
                    painter.drawEllipse(QPoint(cx, cy), ir, ir)

                # 选中
                is_selected = idx in self.selected_atoms
                if self.selected_atom == idx:
                    hw_sel = max(2, int(ir * 0.2))
                    painter.setPen(QPen(QColor('#FFD700'), hw_sel)); painter.setBrush(Qt.NoBrush)
                    painter.drawEllipse(QPoint(cx, cy), ir, ir)
                elif self.selected_atom2 == idx:
                    hw_sel = max(2, int(ir * 0.2))
                    painter.setPen(QPen(QColor('#00BCD4'), hw_sel)); painter.setBrush(Qt.NoBrush)
                    painter.drawEllipse(QPoint(cx, cy), ir, ir)
                elif is_selected:
                    hw_sel = max(2, int(ir * 0.2))
                    painter.setPen(QPen(QColor('#FFD700'), hw_sel)); painter.setBrush(Qt.NoBrush)
                    painter.drawEllipse(QPoint(cx, cy), ir, ir)

                # 环线十字准星
                if self.show_crosshair and ir > 4:
                    n_pts = 60; pen_w = max(1, int(ir * 0.06))
                    painter.save()
                    xhair_color = QColor(200, 210, 230, 180) if is_dark else QColor(0, 0, 0, 130)
                    painter.setPen(QPen(xhair_color, pen_w, cap=Qt.RoundCap))
                    _, _, cz = self._project(ax, ay, az)
                    rr = ir / self.scale / self.zoom * 0.92
                    def _draw_front_arc(ring_points):
                        path_arc = QPainterPath(); started = False
                        for px, py, pz in ring_points:
                            if pz >= cz:
                                if not started: path_arc.moveTo(px, py); started = True
                                else: path_arc.lineTo(px, py)
                            else: started = False
                        painter.drawPath(path_arc)
                    def _ring(azimuth, tilt):
                        az_r, ti_r = math.radians(azimuth), math.radians(tilt)
                        ux = -math.sin(az_r); uy = math.cos(az_r); uz = 0.0
                        vx = -math.cos(az_r)*math.sin(ti_r); vy = -math.sin(az_r)*math.sin(ti_r)
                        vz = math.cos(ti_r)
                        pts = []
                        for k in range(n_pts + 1):
                            t = 2*math.pi*k/n_pts; ct, st = math.cos(t), math.sin(t)
                            wx = ax + rr*(ux*ct + vx*st)
                            wy = ay + rr*(uy*ct + vy*st)
                            wz = az + rr*(uz*ct + vz*st)
                            pts.append(self._project(wx, wy, wz))
                        _draw_front_arc(pts)
                    _ring(self.ring_a_angle, self.ring_a_tilt)
                    _ring(self.ring_b_angle, self.ring_b_tilt)
                    painter.restore()

                # 标签
                if ir >= 6 and self.label_mode != 2:
                    label_color = QColor(220, 220, 230) if is_dark else Qt.black
                    painter.setPen(QPen(label_color))
                    fm = painter.fontMetrics()
                    label = sym if self.label_mode == 0 else str(idx)
                    tw = fm.horizontalAdvance(label); th = fm.height()
                    fs = max(7, int(ir * 0.7))
                    font = painter.font(); font.setPointSize(fs); font.setBold(True)
                    painter.setFont(font)
                    painter.drawText(int(sx - tw / 2), int(sy + th / 3), label)

        # Box select rectangle
        if self._box_selecting and self._box_start and self._box_current:
            x1, y1 = self._box_start
            x2, y2 = self._box_current
            x_min, x_max = min(x1, x2), max(x1, x2)
            y_min, y_max = min(y1, y2), max(y1, y2)
            painter.setPen(QPen(QColor(0, 255, 0), 1.5, style=Qt.DashLine))
            painter.setBrush(QColor(0, 255, 0, 30))
            painter.drawRect(x_min, y_min, x_max - x_min, y_max - y_min)

        painter.end()