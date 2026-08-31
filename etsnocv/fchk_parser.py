# -*- coding: utf-8 -*-
"""
fchk parser — extract atoms, bonds from Gaussian formatted checkpoint files.
"""

import re
import math

from etsnocv.config import ATOM_RADII, ELEMENT_SYMBOLS

BOHR_TO_ANGSTROM = 0.52917720859


def get_atoms_from_fchk(fchk_path):
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
