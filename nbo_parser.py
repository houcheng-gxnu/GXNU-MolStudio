# -*- coding: utf-8 -*-
"""
nbo_parser.py — Gaussian NBO 日志解析（移植自 NBOViewer）
==========================================================

解析 Gaussian ``pop=nbo`` / ``pop=nboread`` 输出里的：

  * ``Natural Bond Orbitals (Summary)`` 段 —— NBO 轨道列表
    （类型 BD/BD*/CR/LP/LV/RY*、占据数、能量、涉及的原子）；
  * ``Second Order Perturbation Theory Analysis of Fock Matrix in NBO Basis``
    段 —— 供体 → 受体的 E(2) 二阶微扰相互作用；
  * 配合 ``.fchk`` 把 NBO 轨道能量匹配到最近的分子轨道（MO）编号。

纯文本解析，无 Qt 依赖。核心逻辑逐字移植自 NBOViewer 的 nbo_parser.py。
"""

import os
import re

from molcanvas import ELEMENT_SYMBOLS

# NBO 轨道能量 -> MO 能量的匹配容差（a.u.）
_MO_MATCH_TOL = 0.5
_FCHK_MO_CACHE = {}
_FCHK_MO_CACHE_MAX = 20

NBO_TYPE_DESC = {
    "CR": "核芯轨道 (Core)",
    "LP": "孤对电子 (Lone Pair)",
    "LV": "孤对空位 (Lone Vacancy)",
    "LP*": "孤对空位 (≡LV)",
    "BD": "成键轨道 (Bond)",
    "BD*": "反键轨道 (Antibond)",
    "RY*": "Rydberg 轨道",
    "3C": "三中心键 (3-Center)",
    "3C*": "三中心反键 (3C-Antibond)",
}

NBO_TYPE_SHORT = {
    "CR": "核芯", "LP": "孤对", "LV": "空位", "LP*": "空位",
    "BD": "成键", "BD*": "反键", "RY*": "Rydb",
    "3C": "3c键", "3C*": "3c反键",
}


def atomic_num_to_symbol(num):
    return ELEMENT_SYMBOLS.get(num, f"X{num}")


def parse_nbo_summary(log_file):
    """解析 Gaussian 日志的 NBO Summary 段，返回 {nbo_id: info}。

    info 包含: type, sub, atoms, atom_elems, occupancy, energy, unit。
    """
    nbo_dict = {}
    in_nbo_section = False
    current_unit = ""
    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if "Natural Bond Orbitals (Summary)" in line:
                in_nbo_section = True
                continue
            if not in_nbo_section:
                continue
            m_unit = re.match(r"Molecular unit\s+(\d+)\s+\((.*?)\)", line)
            if m_unit:
                current_unit = m_unit.group(2).strip()
                continue
            m_nbo = re.match(
                r"\s*(\d+)\.\s+(BD|CR|LP|RY|LV)(\*?)\s*\(\s*(\d+)\)\s*([A-Z][a-z]?)\s+(\d+)"
                r"(?:\s*-\s*([A-Z][a-z]?)\s+(\d+))?",
                line,
            )
            if m_nbo:
                nbo_id = int(m_nbo.group(1))
                nbo_type = m_nbo.group(2) + (m_nbo.group(3) or "")
                nbo_sub = int(m_nbo.group(4))
                atom1_elem = m_nbo.group(5)
                atom1_num = int(m_nbo.group(6))
                atom2_elem = m_nbo.group(7) if m_nbo.group(7) else None
                atom2_num = int(m_nbo.group(8)) if m_nbo.group(8) else None
                rest = line[m_nbo.end():]
                occ_match = re.search(r"([\d\.]+)\s+([\-\d\.]+)", rest)
                occupancy = float(occ_match.group(1)) if occ_match else None
                energy = float(occ_match.group(2)) if occ_match else None
                atoms = [atom1_num]
                atom_elems = [atom1_elem]
                if atom2_num:
                    atoms.append(atom2_num)
                    atom_elems.append(atom2_elem)
                nbo_dict[nbo_id] = {
                    "type": nbo_type,
                    "sub": nbo_sub,
                    "atoms": atoms,
                    "atom_elems": atom_elems,
                    "occupancy": occupancy,
                    "energy": energy,
                    "unit": current_unit,
                }
                continue
            if any(kw in line for kw in [
                "Natural Population", "NBO Search", "Second Order",
            ]):
                in_nbo_section = False
    return nbo_dict


def parse_e2_section(log_file):
    """解析 Second Order Perturbation Theory 段，返回 E(2) 相互作用列表。

    每项包含 donor/acceptor 的 NBO id、类型、涉及的原子，以及
    e2 (kcal/mol)、delta_e、fij。
    """
    e2_list = []
    in_e2_section = False
    current_unit = 1
    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if "Second Order Perturbation Theory Analysis" in line:
                in_e2_section = True
                continue
            if not in_e2_section:
                continue
            m_unit = re.match(r"within unit\s+(\d+)", line)
            if m_unit:
                current_unit = int(m_unit.group(1))
                continue
            stripped = line.strip()
            if stripped and stripped[0].isupper() and len(stripped) > 15:
                if any(kw in stripped for kw in [
                    "Natural Bond", "Natural Population",
                    "NBO Search", "Job cpu time", "Total cpu time",
                ]):
                    in_e2_section = False
                    continue
            if "Donor NBO" in line or "Threshold" in line or \
               ("E(2)" in line and "kcal" in line):
                continue
            slash_idx = line.find("/")
            if slash_idx < 0:
                continue
            donor_part = line[:slash_idx].rstrip()
            acceptor_rest = line[slash_idx + 1:].lstrip()
            m_donor = re.match(
                r"\s*(\d+)\.\s+(BD|CR|LP|RY|LV)(\*?)\s*\(\s*(\d+)\)\s*([A-Z][a-z]?)\s+(\d+)"
                r"(?:\s*-\s*([A-Z][a-z]?)\s+(\d+))?",
                donor_part,
            )
            if not m_donor:
                continue
            donor_id = int(m_donor.group(1))
            donor_type_raw = m_donor.group(2) + (m_donor.group(3) if m_donor.group(3) else "")
            donor_sub = int(m_donor.group(4))
            donor_atom1_elem = m_donor.group(5)
            donor_atom1 = int(m_donor.group(6))
            donor_atom2_elem = m_donor.group(7) if m_donor.group(7) else None
            donor_atom2 = int(m_donor.group(8)) if m_donor.group(8) else None

            m_acceptor = re.match(
                r"(\d+)\.\s+(BD|CR|LP|RY|LV)(\*?)\s*\(\s*(\d+)\)\s*([A-Z][a-z]?)\s+(\d+)"
                r"(?:\s*-\s*([A-Z][a-z]?)\s+(\d+))?",
                acceptor_rest,
            )
            if not m_acceptor:
                continue
            acceptor_id = int(m_acceptor.group(1))
            acceptor_type_raw = m_acceptor.group(2) + (m_acceptor.group(3) if m_acceptor.group(3) else "")
            acceptor_sub = int(m_acceptor.group(4))
            acceptor_atom1_elem = m_acceptor.group(5)
            acceptor_atom1 = int(m_acceptor.group(6))
            acceptor_atom2_elem = m_acceptor.group(7) if m_acceptor.group(7) else None
            acceptor_atom2 = int(m_acceptor.group(8)) if m_acceptor.group(8) else None

            rest = acceptor_rest[m_acceptor.end():]
            vals = re.findall(r"([\d\.]+)", rest)
            if len(vals) >= 3:
                e2 = float(vals[0])
                delta_e = float(vals[1])
                fij = float(vals[2])
            else:
                e2 = delta_e = fij = None

            e2_list.append({
                "donor_id": donor_id,
                "donor_type_raw": donor_type_raw,
                "donor_sub": donor_sub,
                "donor_atom1": donor_atom1,
                "donor_atom1_elem": donor_atom1_elem,
                "donor_atom2": donor_atom2,
                "donor_atom2_elem": donor_atom2_elem,
                "acceptor_id": acceptor_id,
                "acceptor_type_raw": acceptor_type_raw,
                "acceptor_sub": acceptor_sub,
                "acceptor_atom1": acceptor_atom1,
                "acceptor_atom1_elem": acceptor_atom1_elem,
                "acceptor_atom2": acceptor_atom2,
                "acceptor_atom2_elem": acceptor_atom2_elem,
                "e2": e2, "delta_e": delta_e, "fij": fij,
                "unit": current_unit,
                "raw_line": line.rstrip(),
            })
    return e2_list


def _load_fchk_mo_energies(fchk_file):
    if fchk_file in _FCHK_MO_CACHE:
        return _FCHK_MO_CACHE[fchk_file]
    alpha_energies = []
    beta_energies = []
    with open(fchk_file, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    sections = re.findall(
        r"(Alpha|Beta) Orbital Energies\s+R\s+N=\s*(\d+)(.*?)(?=(?:Alpha|Beta) Orbital|\Z)",
        content, re.DOTALL,
    )
    for sec_type, n_orb, data_block in sections:
        n_orb = int(n_orb)
        raw_vals = []
        for token in data_block.split():
            try:
                raw_vals.append(float(token))
            except ValueError:
                pass
        vals = raw_vals[:n_orb]
        if sec_type == "Alpha":
            alpha_energies = vals
        elif sec_type == "Beta":
            beta_energies = vals
    if len(_FCHK_MO_CACHE) >= _FCHK_MO_CACHE_MAX:
        _FCHK_MO_CACHE.clear()
    _FCHK_MO_CACHE[fchk_file] = (alpha_energies, beta_energies)
    return alpha_energies, beta_energies


def get_nearest_mo(fchk_file, target_energy):
    alpha_energies, beta_energies = _load_fchk_mo_energies(fchk_file)
    alpha_sorted = sorted(
        [(i + 1, e, abs(e - target_energy)) for i, e in enumerate(alpha_energies)],
        key=lambda x: x[2],
    )
    beta_sorted = sorted(
        [(i + 1, e, abs(e - target_energy)) for i, e in enumerate(beta_energies)],
        key=lambda x: x[2],
    )
    alpha_res = [{"mo_num": m, "energy": e, "diff": d} for m, e, d in alpha_sorted]
    beta_res = [{"mo_num": m, "energy": e, "diff": d} for m, e, d in beta_sorted]
    return alpha_res, beta_res


def get_atom_nbos(nbo_dict, atom):
    result = []
    for nbo_id, info in nbo_dict.items():
        if atom in info["atoms"]:
            result.append((nbo_id, info))
    return result


def get_nbos_grouped(nbo_dict, atom1, atom2):
    a_nbos = get_atom_nbos(nbo_dict, atom1)
    b_nbos = get_atom_nbos(nbo_dict, atom2)
    a_ids = set(n[0] for n in a_nbos)
    b_ids = set(n[0] for n in b_nbos)
    shared_ids = a_ids & b_ids
    a_only = [(nid, info) for nid, info in a_nbos if nid not in shared_ids]
    b_only = [(nid, info) for nid, info in b_nbos if nid not in shared_ids]
    shared = [(nid, info) for nid, info in a_nbos if nid in shared_ids]
    return {
        "atom1": atom1,
        "atom1_only": sorted(a_only, key=lambda x: x[0]),
        "atom2": atom2,
        "atom2_only": sorted(b_only, key=lambda x: x[0]),
        "shared": sorted(shared, key=lambda x: x[0]),
    }


def get_cross_atom_e2(e2_list, nbos_grouped, nbo_dict, min_e2):
    atom1 = nbos_grouped["atom1"]
    atom2 = nbos_grouped["atom2"]
    atom1_ids = set(n[0] for n in nbos_grouped["atom1_only"] + nbos_grouped["shared"])
    atom2_ids = set(n[0] for n in nbos_grouped["atom2_only"] + nbos_grouped["shared"])
    shared_nbo_ids = set(nid for nid, _ in nbos_grouped["shared"])
    shared_bond_ids = set(
        nid for nid, info in nbos_grouped["shared"]
        if info.get("type") in ("BD", "BD*")
    )
    result = []
    for e2 in e2_list:
        if e2["e2"] is None or e2["e2"] < min_e2:
            continue
        don_a = e2["donor_id"] in atom1_ids
        don_b = e2["donor_id"] in atom2_ids
        acc_a = e2["acceptor_id"] in atom1_ids
        acc_b = e2["acceptor_id"] in atom2_ids
        strict_cross = (don_a and acc_b) or (don_b and acc_a)
        shared_donor = e2["donor_id"] in shared_nbo_ids
        shared_acceptor = e2["acceptor_id"] in shared_nbo_ids
        shared_involved = shared_donor or shared_acceptor
        if not (strict_cross or shared_involved):
            continue
        bond_donor = e2["donor_id"] in shared_bond_ids
        bond_acceptor = e2["acceptor_id"] in shared_bond_ids
        if bond_donor or bond_acceptor:
            cat = 1
        elif shared_involved:
            cat = 2
        else:
            cat = 3
        result.append((cat, e2))
    result.sort(key=lambda x: (x[0], -x[1]["e2"]))
    return [e2 for _, e2 in result]


def _match_nbo_to_mo(nbo_energy, fchk_file):
    alpha_res, beta_res = get_nearest_mo(fchk_file, nbo_energy)
    top_alpha = [r for r in alpha_res[:3] if r["diff"] < _MO_MATCH_TOL]
    top_beta = [r for r in beta_res[:3] if r["diff"] < _MO_MATCH_TOL]
    all_matches = [("Alpha", r) for r in top_alpha] + [("Beta", r) for r in top_beta]
    all_matches.sort(key=lambda x: x[1]["diff"])
    best = all_matches[0] if all_matches else None
    return best, all_matches


def _nbo_type_label(raw_type):
    label = NBO_TYPE_SHORT.get(raw_type, "")
    return f"{raw_type}({label})" if label else raw_type


def tag_shared(nbo_info):
    if not nbo_info:
        return ""
    t = nbo_info.get("type", "")
    s = nbo_info.get("sub", "")
    return f"{t}({s})"


def run_analysis(log_file, atom1, atom2, min_e2, fchk_file=None, locale=None):
    """执行 NBO 分析，返回 (文本报告, data_dict)。

    data_dict 关键字段：
      single_atom_mode=True 时: 'nbo_overview' = [{nbo_id, type, sub,
        atoms_str, occupancy, energy, type_label, group, group_label,
        mo_type?, mo_num?}, ...]
      single_atom_mode=False 时: 'nbo_overview'（三组：shared / 仅A / 仅B）
        和 'cross_e2_details' = [{idx, cat, e2, stars, donor_str,
        donor_label, acceptor_str, acceptor_label, mo1_type?, mo1_num?,
        mo2_type?, mo2_num?, shared_tag, ...}, ...]
    """
    lines = []
    single_atom_mode = (atom2 is None or str(atom2).strip() == "")

    L = locale or {}

    def _t(key, fallback=""):
        return L.get(key, fallback)

    if single_atom_mode:
        lines.append(_t("analysis_parsing_log", "Parsing log file: ") + os.path.basename(log_file))
        lines.append(_t("analysis_query_single", "Querying atom #") + str(atom1) + _t("analysis_query_nbos", "'s NBO orbitals and E(2) interactions"))
        lines.append(_t("analysis_e2_threshold", "E(2) threshold: ") + str(min_e2) + " kcal/mol")
    else:
        lines.append(_t("analysis_parsing_log", "Parsing log file: ") + os.path.basename(log_file))
        lines.append(_t("analysis_query_dual", "Querying atoms #") + str(atom1) + _t("analysis_and", " and #") + str(atom2) + _t("analysis_query_nbos_dual", "'s NBO orbitals and cross-atom E(2) interactions"))
        lines.append(_t("analysis_e2_threshold", "E(2) threshold: ") + str(min_e2) + " kcal/mol")
    lines.append("=" * 78)

    nbo_dict = parse_nbo_summary(log_file)
    lines.append(f"  {_t('analysis_found_nbo', 'Found')} {len(nbo_dict)} {_t('analysis_nbo_count', 'NBO orbitals')}")

    e2_list = parse_e2_section(log_file)
    lines.append(f"  {_t('analysis_found_e2', 'Found')} {len(e2_list)} {_t('analysis_e2_count', 'E(2) interactions')}")

    has_fchk = bool(fchk_file and os.path.exists(fchk_file))
    if has_fchk:
        _load_fchk_mo_energies(fchk_file)

    lines.append("\n" + "─" * 78)
    lines.append(
        "  " + _t("analysis_nbo_types", "NBO types: BD=Bond  BD*=Antibond  LP=Lone Pair  LV=Lone Vacancy  CR=Core  RY*=Rydberg  3C=3-Center")
    )
    lines.append("=" * 78)

    data_dict = {
        "nbo_dict": nbo_dict,
        "e2_list": e2_list,
        "fchk_file": fchk_file if has_fchk else None,
        "single_atom_mode": single_atom_mode,
        "atom1": atom1,
        "atom2": atom2,
    }

    if single_atom_mode:
        nbos = sorted(get_atom_nbos(nbo_dict, atom1), key=lambda x: x[0])
        data_dict["nbos"] = nbos

        if not nbos:
            lines.append(f"\n>>> {_t('analysis_no_nbo_found', 'No NBO orbitals found involving atom #')}{atom1}")
            lines.append(_t("analysis_done", "Done."))
            return "\n".join(lines), data_dict

        single_nbo_overview = []
        for nbo_id, info in nbos:
            entry = {
                "nbo_id": nbo_id,
                "type": info["type"],
                "sub": info["sub"],
                "atoms_str": "-".join(
                    f"{e}{a}" for e, a in zip(info["atom_elems"], info["atoms"])
                ),
                "occupancy": info["occupancy"],
                "energy": info["energy"],
                "type_label": _nbo_type_label(info["type"]),
                "group": "single",
                "group_label": f"#{atom1}",
            }
            if has_fchk and info["energy"] is not None:
                best, _ = _match_nbo_to_mo(info["energy"], fchk_file)
                if best:
                    entry["mo_type"] = best[0]
                    entry["mo_num"] = best[1]["mo_num"]
            single_nbo_overview.append(entry)
        data_dict["nbo_overview"] = single_nbo_overview
        lines.append(f"\n{_t('analysis_complete_single', 'Done — ')} {len(nbos)} {_t('analysis_nbo_listed', 'NBO orbitals listed in the table below.')}")
        return "\n".join(lines), data_dict

    grouped = get_nbos_grouped(nbo_dict, atom1, atom2)
    cross_e2 = get_cross_atom_e2(e2_list, grouped, nbo_dict, min_e2)
    data_dict["grouped"] = grouped
    data_dict["cross_e2"] = cross_e2

    total_nbos = (
        len(grouped["atom1_only"]) +
        len(grouped["atom2_only"]) +
        len(grouped["shared"])
    )

    if total_nbos == 0:
        lines.append(f"\n>>> {_t('analysis_no_nbo_dual', 'No NBO orbitals found involving atoms #')}{atom1} {_t('analysis_or', ' or #')}{atom2}")
        lines.append(_t("analysis_done", "Done."))
        return "\n".join(lines), data_dict

    nbo_overview = []
    for group_key, group_label in [
        ("shared", f"#{atom1}↔#{atom2}"),
        ("atom1_only", f"仅#{atom1}"),
        ("atom2_only", f"仅#{atom2}"),
    ]:
        grp_nbos = grouped[group_key]
        if not grp_nbos:
            continue
        for nbo_id, info in grp_nbos:
            entry = {
                "nbo_id": nbo_id,
                "type": info["type"],
                "sub": info["sub"],
                "atoms_str": "-".join(
                    f"{e}{a}" for e, a in zip(info["atom_elems"], info["atoms"])
                ),
                "occupancy": info["occupancy"],
                "energy": info["energy"],
                "type_label": _nbo_type_label(info["type"]),
                "group": group_key,
                "group_label": group_label,
            }
            if has_fchk and info["energy"] is not None:
                best, _ = _match_nbo_to_mo(info["energy"], fchk_file)
                if best:
                    entry["mo_type"] = best[0]
                    entry["mo_num"] = best[1]["mo_num"]
            nbo_overview.append(entry)
    data_dict["nbo_overview"] = nbo_overview

    shared_nbo_ids = set(nid for nid, _ in grouped.get("shared", []))
    shared_info_map = {nid: info for nid, info in grouped.get("shared", [])}
    shared_bond_ids = set(
        nid for nid, info in grouped.get("shared", [])
        if info.get("type") in ("BD", "BD*")
    )

    cross_e2_details = []
    for global_idx, e2 in enumerate(cross_e2, 1):
        d_info = nbo_dict.get(e2["donor_id"])
        a_info = nbo_dict.get(e2["acceptor_id"])

        if d_info:
            d_atoms = "-".join(f"{e}{a}" for e, a in zip(d_info["atom_elems"], d_info["atoms"]))
            d_str = f"#{e2['donor_id']} {d_info['type']}({d_info['sub']}){d_atoms}"
            d_label = f"{d_info['type']}({d_info['sub']}){d_atoms}"
        else:
            d_str = f"#{e2['donor_id']} {e2['donor_type_raw']}"
            d_label = e2['donor_type_raw']

        if a_info:
            a_atoms = "-".join(f"{e}{a}" for e, a in zip(a_info["atom_elems"], a_info["atoms"]))
            a_str = f"#{e2['acceptor_id']} {a_info['type']}({a_info['sub']}){a_atoms}"
            a_label = f"{a_info['type']}({a_info['sub']}){a_atoms}"
        else:
            a_str = f"#{e2['acceptor_id']} {e2['acceptor_type_raw']}"
            a_label = e2['acceptor_type_raw']

        bd = e2["donor_id"] in shared_bond_ids
        ba = e2["acceptor_id"] in shared_bond_ids
        sd = e2["donor_id"] in shared_nbo_ids
        sa = e2["acceptor_id"] in shared_nbo_ids
        if bd or ba:
            cat = 1
        elif sd or sa:
            cat = 2
        else:
            cat = 3

        stars = (
            "★★★" if e2["e2"] >= 10 else
            ("★★" if e2["e2"] >= 2 else ("★" if e2["e2"] >= 0.5 else "  "))
        )
        don_is_shared = e2["donor_id"] in shared_nbo_ids
        acc_is_shared = e2["acceptor_id"] in shared_nbo_ids
        shared_tag = ""
        if don_is_shared and acc_is_shared:
            s_don = shared_info_map.get(e2["donor_id"], {})
            s_acc = shared_info_map.get(e2["acceptor_id"], {})
            shared_tag = f" [共{tag_shared(s_don)}{tag_shared(s_acc)}]"
        elif don_is_shared:
            s_don = shared_info_map.get(e2["donor_id"], {})
            shared_tag = f" [共{tag_shared(s_don)}供体]"
        elif acc_is_shared:
            s_acc = shared_info_map.get(e2["acceptor_id"], {})
            shared_tag = f" [共{tag_shared(s_acc)}受体]"

        detail = {
            "idx": global_idx,
            "cat": cat,
            "e2": e2["e2"],
            "stars": stars,
            "donor_id": e2["donor_id"],
            "donor_str": d_str,
            "donor_label": d_label,
            "acceptor_id": e2["acceptor_id"],
            "acceptor_str": a_str,
            "acceptor_label": a_label,
            "d_info": d_info,
            "a_info": a_info,
            "shared_tag": shared_tag,
            "don_is_shared": don_is_shared,
            "acc_is_shared": acc_is_shared,
        }

        if has_fchk:
            d_matches = (
                _match_nbo_to_mo(d_info["energy"], fchk_file)
                if (d_info and d_info.get("energy") is not None) else (None, [])
            )
            a_matches = (
                _match_nbo_to_mo(a_info["energy"], fchk_file)
                if (a_info and a_info.get("energy") is not None) else (None, [])
            )
            d_best = d_matches[0] if d_matches[0] else None
            a_best = a_matches[0] if a_matches[0] else None
            if d_best and a_best:
                detail["mo1_type"] = d_best[0]
                detail["mo1_num"] = d_best[1]["mo_num"]
                detail["mo2_type"] = a_best[0]
                detail["mo2_num"] = a_best[1]["mo_num"]
            elif d_best:
                detail["mo1_type"] = d_best[0]
                detail["mo1_num"] = d_best[1]["mo_num"]
            elif a_best:
                detail["mo1_type"] = a_best[0]
                detail["mo1_num"] = a_best[1]["mo_num"]

        cross_e2_details.append(detail)

    data_dict["cross_e2_details"] = cross_e2_details
    lines.append(
        f"\n{_t('analysis_complete_dual', 'Done — ')} {total_nbos} {_t('analysis_nbo', 'NBOs')}, {len(cross_e2)} {_t('analysis_cross_e2', 'cross-atom E(2) listed in the table below.')}"
    )
    return "\n".join(lines), data_dict


def build_full_overview(log_file, fchk_file=None):
    """返回所有 NBO 轨道的概览列表（用于载入 log 后的整体预览）。

    每条 entry 结构与 run_analysis 的 nbo_overview 一致（含 mo_type/mo_num）。
    """
    nbo_dict = parse_nbo_summary(log_file)
    has_fchk = bool(fchk_file and os.path.exists(fchk_file))
    if has_fchk:
        _load_fchk_mo_energies(fchk_file)
    overview = []
    for nbo_id, info in sorted(nbo_dict.items()):
        entry = {
            "nbo_id": nbo_id,
            "type": info["type"],
            "sub": info["sub"],
            "atoms_str": "-".join(
                f"{e}{a}" for e, a in zip(info["atom_elems"], info["atoms"])),
            "occupancy": info["occupancy"],
            "energy": info["energy"],
            "type_label": _nbo_type_label(info["type"]),
            "group": "all",
            "group_label": "全部",
        }
        if has_fchk and info["energy"] is not None:
            best, _ = _match_nbo_to_mo(info["energy"], fchk_file)
            if best:
                entry["mo_type"] = best[0]
                entry["mo_num"] = best[1]["mo_num"]
        overview.append(entry)
    return overview
