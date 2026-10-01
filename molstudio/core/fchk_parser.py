"""
fchk_parser: 从 fchk 文件解析分子轨道信息。
"""

import re


def parse_fchk_mo_info(fchk_path):
    """
    从 fchk 文件解析轨道信息。
    Returns: dict with n_alpha, n_beta, n_basis, is_open_shell,
             alpha_energies, beta_energies, homo_idx, lumo_idx
    """
    with open(fchk_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    def _read_int(label):
        m = re.search(rf"^{label}\s+I\s+(\d+)", content, re.MULTILINE)
        return int(m.group(1)) if m else None

    def _read_float_array(label):
        m = re.search(
            rf"^{label}\s+R\s+N=\s+(\d+)\s*\n([\s\S]+?)(?=\n\w|\Z)",
            content, re.MULTILINE)
        if not m:
            return []
        return [float(x) for x in m.group(2).split()]

    n_alpha = _read_int("Number of alpha electrons") or 0
    n_beta = _read_int("Number of beta electrons") or 0
    n_basis = _read_int("Number of basis functions") or 0
    alpha_e = _read_float_array("Alpha Orbital Energies")
    beta_e = _read_float_array("Beta Orbital Energies")
    is_open = bool(beta_e)
    homo_idx = n_alpha
    lumo_idx = n_alpha + 1 if n_basis > n_alpha else None

    return {
        "n_alpha": n_alpha, "n_beta": n_beta, "n_basis": n_basis,
        "is_open_shell": is_open,
        "alpha_energies": alpha_e,
        "beta_energies": beta_e if is_open else None,
        "homo_idx": homo_idx, "lumo_idx": lumo_idx,
    }
