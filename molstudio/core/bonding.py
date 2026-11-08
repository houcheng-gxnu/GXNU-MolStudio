# -*- coding: utf-8 -*-
"""Bond perception for periodic crystals (pure numpy, no Qt / GL deps).

Why this exists
---------------
The general-purpose canvas uses ``d <= 1.3 * (cov_i + cov_j)`` (Cordero 2008
covalent radii).  That works for molecules but badly over-bonds ionic and
metallic crystals: Na has a covalent radius of 1.66 A, so two Na atoms
4.32 A apart are still "bonded".  In a NaCl cell this draws spurious Na-Na
diagonals (3.99 A) on top of the genuine Na-Cl contacts (2.82 A), producing
the dense X-shaped mesh that makes a crystal unreadable.

A periodic crystal has no isolated molecule to compare against, so the
chemically meaningful criterion is the **first coordination shell**: for each
atom, find its nearest neighbour distance ``d_i`` and only draw contacts that
belong to that shell.  This is independent of element radii, adapts to large
cells (CsCl's Cs-Cl = 3.57 A still bonds) and never invents long diagonals.

    bond(i, j)  <=>  r_ij <= min(d_i, d_j) * CRYSTAL_NEIGHBOUR_FACTOR
               and   r_ij <= CRYSTAL_MAX_BOND_ANG

``min`` (not ``max``) keeps an atom with a short bond from lending its
generous cutoff to a partner that should not be bonded.  The absolute cap is
only a guard for very sparse/gas-like lattices; ordinary crystals never hit
it because the neighbour shell controls the threshold.

All coordinates are in Angstrom.  Returns 0-based ``(i, j)`` pairs, i < j.
"""
from __future__ import annotations

import numpy as np

#: Tolerance on the first coordination shell.  1.12 admits slightly
#: asymmetric shells (distorted perovskites) but rejects the second shell:
#: NaCl Na-Na / Na-Cl = 1.41, CsCl Cl-Cl / Cs-Cl = 1.15, diamond 1.64.
CRYSTAL_NEIGHBOUR_FACTOR = 1.12

#: Hard ceiling (A) for extremely sparse lattices.  Real crystals are
#: governed by the neighbour-shell term above.
CRYSTAL_MAX_BOND_ANG = 4.5

_MIN_CONTACT = 1e-6


def _iter_all_pairs(pos):
    """Yield ``(i, j, r_ij)`` for i < j; O(n^2) but streaming, low memory."""
    n = len(pos)
    for i in range(n - 1):
        d = np.linalg.norm(pos[i + 1:] - pos[i], axis=1)
        for k, r in enumerate(d):
            r = float(r)
            if r > _MIN_CONTACT:
                yield i, i + 1 + k, r


def _normalise_pairs(pos, pairs):
    """Accept ``[(i, j)]`` or ``[(i, j, r_ij)]`` and always yield triples."""
    for item in pairs:
        i, j = int(item[0]), int(item[1])
        if i == j or not (0 <= i < len(pos) and 0 <= j < len(pos)):
            continue
        if i > j:
            i, j = j, i
        r = (float(item[2]) if len(item) > 2
             else float(np.linalg.norm(pos[j] - pos[i])))
        if r > _MIN_CONTACT:
            yield i, j, r


def nearest_neighbour_distances(coords, pairs=None):
    """Per-atom distance to its closest neighbour (A); ``inf`` if isolated.

    ``pairs`` lets a caller reuse an already-computed spatial-bin candidate
    list (the OpenGL canvas has one), avoiding a second O(n^2) pass.
    """
    pos = np.asarray(coords, dtype=float)
    n = len(pos)
    out = np.full(n, np.inf, dtype=float)
    if n < 2:
        return out
    items = (_iter_all_pairs(pos) if pairs is None
             else _normalise_pairs(pos, pairs))
    for i, j, r in items:
        if r < out[i]:
            out[i] = r
        if r < out[j]:
            out[j] = r
    return out


def first_shell_pairs(pairs, n, *, factor=CRYSTAL_NEIGHBOUR_FACTOR,
                      max_dist=CRYSTAL_MAX_BOND_ANG):
    """Filter ``[(i, j, r)]`` down to first-shell bonds.

    ``r`` and ``max_dist`` must use the **same length unit** (the canvas works
    in Bohr and passes a Bohr cap; GLB export works in Angstrom).  This is the
    single numeric rule shared by both renderers, so they cannot drift apart.
    Returns a ``set`` of 0-based ``(i, j)`` with i < j.
    """
    items = list(pairs)
    dmin = np.full(int(n), np.inf, dtype=float)
    for i, j, r in items:
        if r < dmin[i]:
            dmin[i] = r
        if r < dmin[j]:
            dmin[j] = r
    factor = max(1.0, float(factor))
    max_dist = max(0.1, float(max_dist))
    out = set()
    for i, j, r in items:
        limit = min(dmin[i], dmin[j]) * factor
        if not np.isfinite(limit):
            continue
        limit = min(limit, max_dist)
        if r <= limit + 1e-9:
            out.add((i, j) if i < j else (j, i))
    return out


def crystal_bond_pairs(coords, *, factor=CRYSTAL_NEIGHBOUR_FACTOR,
                       max_dist=CRYSTAL_MAX_BOND_ANG, pairs=None):
    """First-shell bond list ``[(i, j)]`` (0-based, i < j) for a crystal.

    ``pairs`` is an optional pre-filtered candidate iterable; the canvas
    passes its binned candidates, GLB export can omit it.  Coordinates in A.
    """
    pos = np.asarray(coords, dtype=float)
    n = len(pos)
    if n < 2:
        return []
    items = (_iter_all_pairs(pos) if pairs is None
             else _normalise_pairs(pos, pairs))
    return sorted(first_shell_pairs(
        items, n, factor=factor, max_dist=max_dist))
