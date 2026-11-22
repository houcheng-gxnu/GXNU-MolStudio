# -*- coding: utf-8 -*-
"""
nbo_parser.py — Gaussian NBO 日志解析（移植自 NBOViewer）
==========================================================

解析 Gaussian ``pop=nbo`` / ``pop=nboread`` 输出里的：

  * ``Natural Bond Orbitals (Summary)`` 段 —— NBO 轨道列表
    （类型 BD/BD*/CR/LP/LV/RY*、占据数、能量、涉及的原子）；
  * ``Second Order Perturbation Theory Analysis of Fock Matrix in NBO Basis``
    段 —— 供体 → 受体的 E(2) 二阶微扰相互作用；
  * 优先使用 NBO plot ``.31/.37``，其次识别 ``pop=saveNBO`` 的显式重排表；
    普通 fchk 仅提供明确标注的 nearest-canonical-MO 提示。

纯文本解析，无 Qt 依赖。核心逻辑逐字移植自 NBOViewer 的 nbo_parser.py。
"""

import os
import re

from molstudio.render.molcanvas import ELEMENT_SYMBOLS

# NBO 轨道能量 -> MO 能量的兼容匹配容差（a.u.）。普通 fchk 不存 NBO；
# 这一路径只作为明确标注的 canonical-MO 近似预览保留。
_MO_MATCH_TOL = 0.5
_FCHK_MO_CACHE = {}
_FCHK_MO_CACHE_MAX = 20

NBO_PLOT_NAMES = {
    32: "PNAO",
    33: "NAO",
    34: "PNHO",
    35: "NHO",
    36: "PNBO",
    37: "NBO",
    38: "PNLMO",
    39: "NLMO",
    40: "MO",
}
NBO_PLOT_BASIS_EXT = 31

# NBO summary / E(2) rows share this leading descriptor. Besides the common
# Lewis types this also accepts 3-centre and lone-pair non-Lewis types.
_NBO_DESCRIPTOR_RE = re.compile(
    r"\s*(\d+)\.\s+(BD|CR|LP|RY|LV|3C)(\*?)\s*\(\s*(\d+)\s*\)\s*"
    r"([A-Z][a-z]?)\s+(\d+)"
    r"(?:\s*-\s*([A-Z][a-z]?)\s+(\d+))?"
    r"(?:\s*-\s*([A-Z][a-z]?)\s+(\d+))?"
)
_FLOAT_TOKEN = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"

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
    "LV*": "空位", "BD": "成键", "BD*": "反键", "RY": "Rydb",
    "RY*": "Rydb",
    "3C": "3c键", "3C*": "3c反键",
}


def atomic_num_to_symbol(num):
    return ELEMENT_SYMBOLS.get(num, f"X{num}")


def _as_float(token):
    return float(token.replace("D", "E").replace("d", "e"))


def _descriptor_parts(match):
    """Return (id, type, sub, atom_numbers, atom_symbols) for a matched row."""
    atom_numbers = [int(match.group(6))]
    atom_symbols = [match.group(5)]
    for elem_group, num_group in ((7, 8), (9, 10)):
        if match.group(elem_group) and match.group(num_group):
            atom_symbols.append(match.group(elem_group))
            atom_numbers.append(int(match.group(num_group)))
    nbo_type = match.group(2) + (match.group(3) or "")
    return (
        int(match.group(1)),
        nbo_type,
        int(match.group(4)),
        atom_numbers,
        atom_symbols,
    )


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
                # A linked job can contain several NBO passes. Only the final
                # pass describes the final wavefunction; retaining earlier rows
                # silently mixes positions from different geometries.
                nbo_dict = {}
                current_unit = ""
                in_nbo_section = True
                continue
            if not in_nbo_section:
                continue
            m_unit = re.match(r"Molecular unit\s+(\d+)\s+\((.*?)\)", line)
            if m_unit:
                current_unit = m_unit.group(2).strip()
                continue
            m_nbo = _NBO_DESCRIPTOR_RE.match(line)
            if m_nbo:
                nbo_id, nbo_type, nbo_sub, atoms, atom_elems = _descriptor_parts(
                    m_nbo)
                rest = line[m_nbo.end():]
                occ_match = re.search(
                    rf"({_FLOAT_TOKEN})\s+({_FLOAT_TOKEN})", rest)
                occupancy = _as_float(occ_match.group(1)) if occ_match else None
                energy = _as_float(occ_match.group(2)) if occ_match else None
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
    acceptor_unit = 1
    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if "Second Order Perturbation Theory Analysis" in line:
                # Keep only the final perturbation table when a log contains
                # several NBO passes.
                e2_list = []
                in_e2_section = True
                current_unit = 1
                acceptor_unit = 1
                continue
            if not in_e2_section:
                continue
            m_unit = re.match(r"\s*within\s+unit\s+(\d+)", line, re.IGNORECASE)
            if m_unit:
                current_unit = acceptor_unit = int(m_unit.group(1))
                continue
            m_unit = re.match(
                r"\s*from\s+unit\s+(\d+)\s+to\s+unit\s+(\d+)",
                line, re.IGNORECASE)
            if m_unit:
                current_unit = int(m_unit.group(1))
                acceptor_unit = int(m_unit.group(2))
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
            m_donor = _NBO_DESCRIPTOR_RE.match(donor_part)
            if not m_donor:
                continue
            (
                donor_id, donor_type_raw, donor_sub,
                donor_atoms, donor_atom_elems,
            ) = _descriptor_parts(m_donor)

            m_acceptor = _NBO_DESCRIPTOR_RE.match(acceptor_rest)
            if not m_acceptor:
                continue
            (
                acceptor_id, acceptor_type_raw, acceptor_sub,
                acceptor_atoms, acceptor_atom_elems,
            ) = _descriptor_parts(m_acceptor)

            rest = acceptor_rest[m_acceptor.end():]
            vals = re.findall(_FLOAT_TOKEN, rest)
            if len(vals) >= 3:
                e2 = _as_float(vals[0])
                delta_e = _as_float(vals[1])
                fij = _as_float(vals[2])
            else:
                e2 = delta_e = fij = None

            e2_list.append({
                "donor_id": donor_id,
                "donor_type_raw": donor_type_raw,
                "donor_sub": donor_sub,
                "donor_atoms": donor_atoms,
                "donor_atom_elems": donor_atom_elems,
                "donor_atom1": donor_atoms[0],
                "donor_atom1_elem": donor_atom_elems[0],
                "donor_atom2": donor_atoms[1] if len(donor_atoms) > 1 else None,
                "donor_atom2_elem": donor_atom_elems[1] if len(donor_atom_elems) > 1 else None,
                "acceptor_id": acceptor_id,
                "acceptor_type_raw": acceptor_type_raw,
                "acceptor_sub": acceptor_sub,
                "acceptor_atoms": acceptor_atoms,
                "acceptor_atom_elems": acceptor_atom_elems,
                "acceptor_atom1": acceptor_atoms[0],
                "acceptor_atom1_elem": acceptor_atom_elems[0],
                "acceptor_atom2": acceptor_atoms[1] if len(acceptor_atoms) > 1 else None,
                "acceptor_atom2_elem": acceptor_atom_elems[1] if len(acceptor_atom_elems) > 1 else None,
                "e2": e2, "delta_e": delta_e, "fij": fij,
                "unit": acceptor_unit,
                "donor_unit": current_unit,
                "acceptor_unit": acceptor_unit,
                "raw_line": line.rstrip(),
            })
    return e2_list


def parse_nbo_storage_order(log_file):
    """Parse Gaussian's ``Reordering of NBOs for storage`` permutation.

    Gaussian applies this permutation before writing ``pop=saveNBO`` orbitals
    into the checkpoint/fchk. Element 0 of the returned list corresponds to
    fchk orbital 1.
    """
    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    for i, line in enumerate(lines):
        if "Reordering of NBOs for storage" not in line:
            continue
        order = []
        j = i
        while j < len(lines):
            row = lines[j]
            if "Reordering of NBOs for storage" in row:
                tail = row.split(":", 1)[1] if ":" in row else ""
                order.extend(int(x) for x in re.findall(r"\b\d+\b", tail))
                j += 1
                continue
            if not row.strip():
                break
            if re.fullmatch(r"\s*\d+(?:\s+\d+)*\s*", row):
                order.extend(int(x) for x in re.findall(r"\b\d+\b", row))
                j += 1
                continue
            break
        if order:
            return order
    return []


def _log_requests_save_nbo(log_file):
    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if re.search(r"save\s*nbo\b", line, re.IGNORECASE):
                return True
    return False


def _log_requests_save_nlmo(log_file):
    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if re.search(r"save\s*nlmo\b", line, re.IGNORECASE):
                return True
    return False


def _plot_paths_from_selection(plot_file):
    """Return (basis .31 path, selected plot path, numeric plot type)."""
    if not plot_file:
        return None
    path = os.path.abspath(plot_file)
    try:
        ext = int(os.path.splitext(path)[1].lstrip("."))
    except ValueError:
        return None
    if ext not in NBO_PLOT_NAMES and ext != NBO_PLOT_BASIS_EXT:
        return None
    root = os.path.splitext(path)[0]
    basis = root + "." + str(NBO_PLOT_BASIS_EXT)
    selected = root + ".37"
    return basis, selected, 37


def find_nbo_plot_files(log_file, plot_file=None):
    """Locate the paired NBO plot files used for direct NBO visualization."""
    if plot_file:
        pair = _plot_paths_from_selection(plot_file)
        if pair:
            basis, selected, plot_type = pair
            if os.path.isfile(basis) and os.path.isfile(selected):
                return {
                    "basis": basis,
                    "selected": selected,
                    "plot_type": plot_type,
                    "plot_name": NBO_PLOT_NAMES[plot_type],
                }
        return None
    root = os.path.splitext(os.path.abspath(log_file))[0]
    pair = _plot_paths_from_selection(root + ".37")
    if pair:
        basis, selected, plot_type = pair
        if os.path.isfile(basis) and os.path.isfile(selected):
            return {
                "basis": basis,
                "selected": selected,
                "plot_type": plot_type,
                "plot_name": NBO_PLOT_NAMES[plot_type],
            }
    return None


def resolve_nbo_visual_source(log_file, fchk_file=None, plot_file=None):
    """Resolve the scientifically correct source for NBO cube generation.

    Priority follows the standard Gaussian/Multiwfn workflow:

    1. NBO plot pair (``.31`` + ``.37``) stores the actual NBOs;
    2. ``pop=saveNBO`` fchk uses the explicit storage permutation from the log;
    3. a normal fchk only offers a nearest-canonical-MO approximation.

    The last case is marked non-exact but remains renderable for backwards
    compatibility with the original viewer workflow.
    """
    plot = find_nbo_plot_files(log_file, plot_file)
    if plot:
        return {
            "kind": "plot",
            "direct": True,
            "basis": plot["basis"],
            "selected": plot["selected"],
            "plot_type": plot["plot_type"],
            "plot_name": plot["plot_name"],
            "label": (
                f"{plot['plot_name']} plot "
                f"({os.path.basename(plot['selected'])})"
            ),
        }

    has_fchk = bool(fchk_file and os.path.exists(fchk_file))
    order = parse_nbo_storage_order(log_file) if has_fchk else []
    save_nbo_requested = has_fchk and _log_requests_save_nbo(log_file)
    if save_nbo_requested and not order:
        # Older Gaussian/NBO outputs may not print the permutation banner.
        # saveNBO stores orbitals in increasing energy, so reproduce that
        # order from the final NBO summary as a compatibility fallback.
        summary = parse_nbo_summary(log_file)
        order = sorted(
            summary,
            key=lambda nid: (
                summary[nid].get("energy") is None,
                summary[nid].get("energy") or 0.0,
                nid,
            ),
        )
    if order and not _log_requests_save_nlmo(log_file):
        return {
            "kind": "saveNBO",
            "direct": True,
            "fchk": fchk_file,
            "storage_order": order,
            "storage_map": {
                nbo_id: i + 1 for i, nbo_id in enumerate(order)
            },
            "label": f"saveNBO fchk ({os.path.basename(fchk_file)})",
        }
    if has_fchk:
        return {
            "kind": "canonical",
            "direct": False,
            "fchk": fchk_file,
            "label": "canonical MO approximation",
        }
    return {
        "kind": "none",
        "direct": False,
        "label": "no NBO wavefunction source",
    }


def build_nbo_visual_ref(source, nbo_id, energy=None):
    """Build a UI/cube reference using the original energy-matching workflow."""
    kind = (source or {}).get("kind", "none")
    if kind == "plot":
        return {
            "kind": "plot",
            "direct": True,
            "renderable": True,
            "source": source["basis"],
            "selected": source["selected"],
            "plot_type": source["plot_type"],
            "orbital": str(nbo_id),
            "nbo_id": nbo_id,
            "display": f"NBO {nbo_id} (.{source['plot_type']})",
        }

    # Preserve the original viewer contract: every NBO row with an energy is
    # matched to the nearest alpha/beta orbital in the linked fchk. This also
    # covers saveNBO fchks whose storage permutation is incomplete or absent.
    fchk = source.get("fchk")
    if fchk and energy is not None:
        best, _ = _match_nbo_to_mo(
            energy, fchk, allow_nearest=True)
        if best:
            mo_type, mo = best
            orbital = (
                str(mo["mo_num"])
                if mo_type == "Alpha"
                else f"-{mo['mo_num']}"
            )
            return {
                "kind": "canonical",
                "direct": True,
                "renderable": True,
                "source": fchk,
                "orbital": orbital,
                "mo_type": mo_type,
                "mo_num": mo["mo_num"],
                "nbo_id": nbo_id,
                "display": f"{mo_type}#{mo['mo_num']}",
            }
    return None


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


def _match_nbo_to_mo(nbo_energy, fchk_file, allow_nearest=False):
    alpha_res, beta_res = get_nearest_mo(fchk_file, nbo_energy)
    top_alpha = [r for r in alpha_res[:3] if r["diff"] < _MO_MATCH_TOL]
    top_beta = [r for r in beta_res[:3] if r["diff"] < _MO_MATCH_TOL]
    all_matches = [("Alpha", r) for r in top_alpha] + [("Beta", r) for r in top_beta]
    if not all_matches and allow_nearest:
        candidates = []
        if alpha_res:
            candidates.append(("Alpha", alpha_res[0]))
        if beta_res:
            candidates.append(("Beta", beta_res[0]))
        all_matches = candidates
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


def run_analysis(log_file, atom1, atom2, min_e2, fchk_file=None,
                 locale=None, plot_file=None):
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
    visual_source = resolve_nbo_visual_source(
        log_file, fchk_file, plot_file)

    lines.append("\n" + "─" * 78)
    lines.append(
        "  " + _t("analysis_nbo_types", "NBO types: BD=Bond  BD*=Antibond  LP=Lone Pair  LV=Lone Vacancy  CR=Core  RY*=Rydberg  3C=3-Center")
    )
    lines.append("=" * 78)

    data_dict = {
        "nbo_dict": nbo_dict,
        "e2_list": e2_list,
        "fchk_file": fchk_file if has_fchk else None,
        "visual_source": visual_source,
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
            visual = build_nbo_visual_ref(
                visual_source, nbo_id, info.get("energy"))
            if visual:
                entry["visual"] = visual
                if visual.get("mo_num"):
                    entry["mo_type"] = visual.get("mo_type")
                    entry["mo_num"] = visual.get("mo_num")
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
            visual = build_nbo_visual_ref(
                visual_source, nbo_id, info.get("energy"))
            if visual:
                entry["visual"] = visual
                if visual.get("mo_num"):
                    entry["mo_type"] = visual.get("mo_type")
                    entry["mo_num"] = visual.get("mo_num")
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

        donor_visual = build_nbo_visual_ref(
            visual_source, e2["donor_id"],
            d_info.get("energy") if d_info else None)
        acceptor_visual = build_nbo_visual_ref(
            visual_source, e2["acceptor_id"],
            a_info.get("energy") if a_info else None)
        if donor_visual:
            detail["visual_donor"] = donor_visual
            if donor_visual.get("mo_num"):
                detail["mo1_type"] = donor_visual.get("mo_type")
                detail["mo1_num"] = donor_visual.get("mo_num")
        if acceptor_visual:
            detail["visual_acceptor"] = acceptor_visual
            if acceptor_visual.get("mo_num"):
                detail["mo2_type"] = acceptor_visual.get("mo_type")
                detail["mo2_num"] = acceptor_visual.get("mo_num")

        cross_e2_details.append(detail)

    data_dict["cross_e2_details"] = cross_e2_details
    lines.append(
        f"\n{_t('analysis_complete_dual', 'Done — ')} {total_nbos} {_t('analysis_nbo', 'NBOs')}, {len(cross_e2)} {_t('analysis_cross_e2', 'cross-atom E(2) listed in the table below.')}"
    )
    return "\n".join(lines), data_dict


def build_full_overview(log_file, fchk_file=None, plot_file=None):
    """返回所有 NBO 轨道的概览列表（用于载入 log 后的整体预览）。

    每条 entry 结构与 run_analysis 的 nbo_overview 一致（含 mo_type/mo_num）。
    """
    nbo_dict = parse_nbo_summary(log_file)
    has_fchk = bool(fchk_file and os.path.exists(fchk_file))
    if has_fchk:
        _load_fchk_mo_energies(fchk_file)
    visual_source = resolve_nbo_visual_source(
        log_file, fchk_file, plot_file)
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
        visual = build_nbo_visual_ref(
            visual_source, nbo_id, info.get("energy"))
        if visual:
            entry["visual"] = visual
            if visual.get("mo_num"):
                entry["mo_type"] = visual.get("mo_type")
                entry["mo_num"] = visual.get("mo_num")
        overview.append(entry)
    return overview
