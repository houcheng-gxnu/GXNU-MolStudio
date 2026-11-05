# -*- coding: utf-8 -*-
"""Locally prepare and run the three ETS-NOCV Gaussian jobs.

The workflow intentionally keeps the fragment coordinates exactly as they
appear in the complex.  The complex input is written as Fragment 1 followed by
Fragment 2, so each fragment occupies one uninterrupted coordinate block.
"""

import os
import re

from molstudio.core.gaussian_run import (
    chk_to_fchk,
    find_chk_file,
    find_formchk,
    run_gaussian,
)


class LocalETSCancelled(RuntimeError):
    """Raised when the user stops the local Gaussian/formchk workflow."""


def _ordered_fragment(atoms_by_index, atom_ids):
    try:
        ids = sorted({int(v) for v in atom_ids})
    except (TypeError, ValueError):
        raise ValueError("Fragment atom indices must be integers")
    missing = [v for v in ids if v not in atoms_by_index]
    if missing:
        raise ValueError("Unknown fragment atom index: %s" % missing[0])
    return [atoms_by_index[v] for v in ids]


def build_fragment_geometries(atoms, fragments):
    """Return ``(complex_atoms, [frag1_atoms, frag2_atoms])``.

    Both fragments must be non-empty, disjoint and together cover every atom.
    Coordinates are copied from the loaded structure without translation,
    centering or reorientation.  The returned complex is ordered as Fragment 1
    followed by Fragment 2 to guarantee continuous coordinate blocks.
    """
    if len(fragments) != 2:
        raise ValueError("ETS-NOCV requires exactly two fragments")
    atoms_by_index = {int(atom[0]): atom for atom in atoms}
    if not atoms_by_index:
        raise ValueError("No atoms were loaded")

    ids1 = set()
    ids2 = set()
    for atom_id in fragments[0].get("atoms", set()):
        try:
            ids1.add(int(atom_id))
        except (TypeError, ValueError):
            raise ValueError("Fragment atom indices must be integers")
    for atom_id in fragments[1].get("atoms", set()):
        try:
            ids2.add(int(atom_id))
        except (TypeError, ValueError):
            raise ValueError("Fragment atom indices must be integers")

    if not ids1 or not ids2:
        raise ValueError("Both fragments must contain at least one atom")
    overlap = ids1 & ids2
    if overlap:
        raise ValueError("Atom %s is assigned to both fragments" % min(overlap))
    missing = set(atoms_by_index) - ids1 - ids2
    if missing:
        raise ValueError("Atom %s is not assigned to either fragment" % min(missing))
    unknown = (ids1 | ids2) - set(atoms_by_index)
    if unknown:
        raise ValueError("Unknown fragment atom index: %s" % min(unknown))

    frag1 = _ordered_fragment(atoms_by_index, ids1)
    frag2 = _ordered_fragment(atoms_by_index, ids2)
    return frag1 + frag2, [frag1, frag2]


def _route_line(method):
    method = (method or "M06L/def2SVP").strip()
    if not re.search(r"(?<![A-Za-z])nosymm(?![A-Za-z])", method, re.IGNORECASE):
        method += " nosymm"
    return "#P " + method


def write_gaussian_input(atoms, path, method, charge, multiplicity,
                         nprocshared=24, mem="10GB"):
    """Write one Gaussian input while preserving every atomic coordinate."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    chk_name = os.path.splitext(os.path.basename(path))[0] + ".chk"
    with open(path, "w", encoding="ascii", errors="strict", newline="\n") as fh:
        fh.write("%%nprocshared=%s\n" % nprocshared)
        fh.write("%%mem=%s\n" % mem)
        fh.write("%%chk=%s\n" % chk_name)
        fh.write(_route_line(method) + "\n\n")
        fh.write(os.path.splitext(os.path.basename(path))[0] + "\n\n")
        fh.write("%s %s\n" % (charge, multiplicity))
        for _idx, symbol, _atomic_number, (x, y, z) in atoms:
            fh.write(" %-2s %14.8f %14.8f %14.8f\n" % (symbol, x, y, z))
        fh.write("\n")
    return path


def prepare_ets_jobs(atoms, fragments, output_dir, stem, method,
                     complex_charge, complex_multiplicity,
                     nprocshared=24, mem="10GB"):
    """Write complex, Fragment 1 and Fragment 2 Gaussian inputs."""
    complex_atoms, fragment_atoms = build_fragment_geometries(atoms, fragments)
    os.makedirs(output_dir, exist_ok=True)
    safe_stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", stem).strip(" .")
    safe_stem = safe_stem or "molecule"

    jobs = [
        {
            "role": "complex",
            "gjf": os.path.join(output_dir, safe_stem + "_complex.gjf"),
            "atoms": complex_atoms,
            "charge": str(complex_charge),
            "multiplicity": str(complex_multiplicity),
        },
        {
            "role": "fragment1",
            "gjf": os.path.join(output_dir, safe_stem + "_fragment1.gjf"),
            "atoms": fragment_atoms[0],
            "charge": str(fragments[0].get("charge", 0)),
            "multiplicity": str(fragments[0].get("multiplicity", 1)),
        },
        {
            "role": "fragment2",
            "gjf": os.path.join(output_dir, safe_stem + "_fragment2.gjf"),
            "atoms": fragment_atoms[1],
            "charge": str(fragments[1].get("charge", 0)),
            "multiplicity": str(fragments[1].get("multiplicity", 1)),
        },
    ]
    for job in jobs:
        write_gaussian_input(
            job["atoms"], job["gjf"], method, job["charge"],
            job["multiplicity"], nprocshared=nprocshared, mem=mem)
        job["log"] = os.path.splitext(job["gjf"])[0] + ".log"
        job["chk"] = os.path.splitext(job["gjf"])[0] + ".chk"
        # ``.fch`` is the extension Gaussian/Multiwfn commonly use for a
        # formatted checkpoint; MolStudio's parser treats .fch and .fchk alike.
        job["fch"] = os.path.splitext(job["gjf"])[0] + ".fch"
    return jobs


def run_ets_jobs(jobs, g16_exe, formchk_exe=None, on_log=None, cancel=None):
    """Run all three jobs sequentially, then convert each chk to fch.

    Returns a mapping with ``complex``, ``frag1``, ``frag2`` and ``jobs`` keys.
    Any Gaussian/formchk failure stops the chain immediately.
    """
    if not g16_exe or not os.path.isfile(g16_exe):
        raise RuntimeError("找不到 g16.exe，请先在路径设置中配置 Gaussian")
    converter = formchk_exe or find_formchk(g16_exe)
    if not converter or not os.path.isfile(converter):
        raise RuntimeError("找不到 formchk.exe（应与 g16.exe 位于同一目录）")

    emit = on_log or (lambda _msg: None)
    for index, job in enumerate(jobs, 1):
        if cancel is not None and cancel():
            raise LocalETSCancelled("本机计算已停止")
        label = {"complex": "复合物", "fragment1": "碎片 1",
                 "fragment2": "碎片 2"}.get(job["role"], job["role"])
        emit("=== [%d/3] %s：%s ===" %
             (index, label, os.path.basename(job["gjf"])))
        result = run_gaussian(
            job["gjf"], g16_exe, log_path=job["log"],
            on_line=emit, cancel=cancel)
        if result.cancelled:
            raise LocalETSCancelled("本机计算已停止")
        if not result.ok:
            raise RuntimeError("%s Gaussian 计算失败：%s\n日志：%s" %
                               (label, result.error, result.log_path))

        chk = find_chk_file(result.log_path) or job["chk"]
        if not os.path.isfile(chk):
            raise RuntimeError("%s 计算正常结束，但找不到 chk 文件：%s" %
                               (label, chk))
        emit("[%d/3] formchk：%s → %s" %
             (index, os.path.basename(chk), os.path.basename(job["fch"])))
        fch = chk_to_fchk(chk, converter, output_path=job["fch"])
        job["chk"] = chk
        job["fch"] = fch
        emit("[%d/3] 完成：%s" % (index, os.path.basename(fch)))

    by_role = {job["role"]: job for job in jobs}
    return {
        "complex": by_role["complex"]["fch"],
        "frag1": by_role["fragment1"]["fch"],
        "frag2": by_role["fragment2"]["fch"],
        "jobs": jobs,
    }
