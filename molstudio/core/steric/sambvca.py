# -*- coding: utf-8 -*-
# Ported from StericMapAnalyzer (GPLv3) — SambVca 2.1 official algorithm replica.
# 来源：StericMapAnalyzer v3.5（同作者仓库，GPL-3.0-only）的 sambvca.py。
# License: GPL-3.0-only (inherited from StericMapAnalyzer).
# MolStudio 移植版：官方 103 元素半径表、三步定向算法与 .inp 读写逐字保留；
# 仅新增中英文诊断文案（format_diag 的 lang 参数）与 write_inp 的 dict 兼容，
# 不改变任何数值算法。请勿"顺手修正"算法。
"""SambVca 兼容内核：参数模型 / 定向算法 / .inp 读写 / 自检。

严格对应官方 SambVca 2.0–2.1 的输入规范。官方 .inp 字段顺序（自由格式）：

    nAtomDel  → IndDel
    nAtomGC   → IndGC          球心原子（算术平均）
    nAtom_z   → IndAxis        z 轴原子（算术平均）
    nAtom_xz  → Indxz          xz 平面原子（算术平均）
    Radius  Disp  BinSize  RemoveH  AlignZ  DoMap
    nTypes    → (Name Radius) × nTypes
    每帧: natoms, Title, (Name x y z) × natoms

定向算法（与 sambvca21.f 一致的三步刚体变换）::

    ① 球心 = mean(IndGC 坐标)；全体平移，使球心到原点
    ② 轴向量 = mean(IndAxis 坐标) − 球心；刚体旋转把它对齐到 (0,0,∓1)
       AlignZ=0 → −z（官方默认，配体在 −z 侧）；AlignZ=1 → +z
    ③ xz 向量 = mean(Indxz 坐标) − 球心；取其水平投影，绕 z 旋转使其指向 +x
    ④ Disp：整体沿 z 平移 ±Disp（等价于把球心从配位点沿配位轴外移 Disp）

本模块只依赖 numpy，不依赖 stericrender，便于随 GUI 一起打包。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict, fields
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

# ══════════════════════════════════════════════════════════════════
#  官方原子半径表（Bondi）
#  来源：SambVca 2.0/2.1 网页 "Atoms Radius" 面板 Bondi 列（103 种元素）
#  官方 scaled-Bondi = round(Bondi × 1.17, 2)，本模块按此推导并自检
#
#  注：官方分发包的 .inp 半径表里门捷列夫元素写作 "M"（应为 "MD"），属官方笔误；
#      网页表格给出的是 "Md 2.88"。本模块采用正确的 "Md"，与网站一致。
# ══════════════════════════════════════════════════════════════════
BONDI_RADII: dict[str, float] = {
    "H": 1.09, "He": 1.40, "Li": 1.82, "Be": 1.53, "B": 1.92,
    "C": 1.70, "N": 1.55, "O": 1.52, "F": 1.47, "Ne": 1.54,
    "Na": 2.27, "Mg": 1.73, "Al": 1.84, "Si": 2.10, "P": 1.80,
    "S": 1.80, "Cl": 1.75, "Ar": 1.88, "K": 2.75, "Ca": 2.31,
    "Sc": 2.15, "Ti": 2.11, "V": 2.07, "Cr": 2.06, "Mn": 2.05,
    "Fe": 2.04, "Co": 2.00, "Ni": 1.63, "Cu": 1.40, "Zn": 1.39,
    "Ga": 1.87, "Ge": 2.11, "As": 1.85, "Se": 1.90, "Br": 1.85,
    "Kr": 2.02, "Rb": 3.03, "Sr": 2.49, "Y": 2.32, "Zr": 2.23,
    "Nb": 2.18, "Mo": 2.17, "Tc": 2.16, "Ru": 2.13, "Rh": 2.10,
    "Pd": 1.63, "Ag": 1.72, "Cd": 1.58, "In": 1.93, "Sn": 2.17,
    "Sb": 2.06, "Te": 2.06, "I": 1.98, "Xe": 2.16, "Cs": 3.43,
    "Ba": 2.68, "La": 2.43, "Ce": 2.42, "Pr": 2.40, "Nd": 2.39,
    "Pm": 2.38, "Sm": 2.36, "Eu": 2.35, "Gd": 2.34, "Tb": 2.33,
    "Dy": 2.31, "Ho": 2.30, "Er": 2.29, "Tm": 2.27, "Yb": 2.26,
    "Lu": 2.24, "Hf": 2.23, "Ta": 2.22, "W": 2.18, "Re": 2.16,
    "Os": 2.16, "Ir": 2.13, "Pt": 1.72, "Au": 1.66, "Hg": 1.55,
    "Tl": 1.96, "Pb": 2.02, "Bi": 2.07, "Po": 1.97, "At": 2.02,
    "Rn": 2.20, "Fr": 3.48, "Ra": 2.83, "Ac": 2.47, "Th": 2.45,
    "Pa": 2.43, "U": 1.86, "Np": 2.39, "Pu": 2.43, "Am": 2.44,
    "Cm": 2.45, "Bk": 2.44, "Cf": 2.45, "Es": 2.45, "Fm": 2.45,
    "Md": 2.46, "No": 2.46, "Lr": 2.46,
}

# 官方 scaled-Bondi 表中的 H 与推导值一致（1.09×1.17=1.2753→1.28）
RADII_SCALE = 1.17


def _scaled(r: float) -> float:
    return round(r * RADII_SCALE, 2)


BONDI_SCALED_RADII: dict[str, float] = {k: _scaled(v) for k, v in BONDI_RADII.items()}

# 官方 .inp 里 HE 之外还有一个 "GG"（2.1 版用作 dummy 原子类型，半径 1.28）
DUMMY_TYPE_NAME = "GG"
DUMMY_TYPE_RADIUS = 1.28

RADII_SETS = ("bondi", "bondi-scaled")


def radii_for_symbols(symbols: Sequence[str], radii_set: str = "bondi-scaled"):
    """按官方半径表取半径。

    返回 (半径数组, 缺失元素集合)。官方表未收录的元素按 Bondi 默认 2.00 Å 兜底，
    与官方程序未匹配到元素时的行为不同，因此把缺失元素回传给调用方提示用户。
    """
    if radii_set not in RADII_SETS:
        raise ValueError(f"未知半径集: {radii_set!r}（可选 {RADII_SETS}）")
    table = BONDI_SCALED_RADII if radii_set == "bondi-scaled" else BONDI_RADII
    out, missing = [], set()
    for sym in symbols:
        key = sym.strip().capitalize()
        if key in table:
            out.append(table[key])
        else:
            missing.add(key)
            out.append(_scaled(2.00) if radii_set == "bondi-scaled" else 2.00)
    return np.array(out, dtype=float), missing


# ══════════════════════════════════════════════════════════════════
#  参数模型（字段与官方 .inp 一一对应）
# ══════════════════════════════════════════════════════════════════
@dataclass
class SambVcaJob:
    """与官方 .inp 同义的参数集合。原子序号一律 1-based。"""

    delete_atoms: list[int] = field(default_factory=list)      # IndDel
    centre_atoms: list[int] = field(default_factory=lambda: [1])  # IndGC
    z_axis_atoms: list[int] = field(default_factory=list)      # IndAxis
    xz_plane_atoms: list[int] = field(default_factory=list)    # Indxz

    sphere_radius: float = 3.5      # Radius（官方负数= cube 模式，本实现不支持，仅解析保留）
    displacement: float = 0.0       # Disp：配位点到球心距离，沿 z 轴
    mesh: float = 0.10              # BinSize（官方默认 0.10，不是 0.05）
    remove_h: int = 1               # RemoveH  0/1
    align_z: int = 0                # AlignZ   0=配体在 −z（官方默认）；1=+z
    write_surfaces: int = 1         # DoMap

    radii_set: str = "bondi-scaled"     # 官方默认 Bondi×1.17
    map_radius: float | None = None
    include_origin: bool = False        # ⚠️ 与官方语义相反：官方要求球心原子出现在 delete_atoms

    # ── 官方 .inp 里的原始字段，仅用于无损往返 ──
    raw_radius_negative: bool = False
    raw_n_types: int = 0
    raw_radius_table: dict = field(default_factory=dict)

    # ── 兼容旧接口 ──
    @classmethod
    def from_legacy(cls, origin_0based: int, toward_0based: Iterable[int],
                    include_h: bool = False, radii_set: str = "bondi-scaled",
                    sphere_radius: float = 3.5, map_radius: float | None = None,
                    mesh: float = 0.10, include_origin: bool = False) -> "SambVcaJob":
        """由旧版（单球心 + 朝向原子）参数构造，行为与旧版一致。

        旧版把球心原子自动排除出体积计算，这里用 delete_atoms 表达同一语义，
        因此 align_z=1（旧版把配体朝 +z）。
        """
        return cls(
            delete_atoms=[] if include_origin else [origin_0based + 1],
            centre_atoms=[origin_0based + 1],
            z_axis_atoms=[i + 1 for i in toward_0based],
            xz_plane_atoms=[],
            sphere_radius=sphere_radius,
            displacement=0.0,
            mesh=mesh,
            remove_h=0 if include_h else 1,
            align_z=1,          # 旧版把配体朝 +z，等价于官方 AlignZ=1
            write_surfaces=1,
            radii_set=radii_set,
            map_radius=map_radius,
            include_origin=include_origin,
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("raw_radius_table", None)
        return d


# ══════════════════════════════════════════════════════════════════
#  序号解析（1-based，支持 "1,3-5"）
# ══════════════════════════════════════════════════════════════════
def parse_index_spec(spec: str | None, n_atoms: int) -> list[int]:
    """解析 1-based 序号表达式，返回排序去重的 1-based 序号列表。

    容忍中文全角逗号/空格/分号；非法片段抛 ValueError（附原始片段）。
    """
    if spec is None:
        return []
    text = str(spec).replace("，", ",").replace("、", ",").replace(";", ",").replace("；", ",")
    text = text.replace(" ", "").replace("\t", "")
    if not text:
        return []
    out: set[int] = set()
    for part in text.split(","):
        if not part:
            continue
        if "-" in part[1:]:                      # 支持 "3-5"，避免把负号当区间
            a, _, b = part.partition("-")
            try:
                start, end = int(a), int(b)
            except ValueError:
                raise ValueError(f"非法序号片段: {part!r}")
            if start > end:
                raise ValueError(f"区间起止颠倒: {part!r}")
            values = range(start, end + 1)
        else:
            try:
                values = [int(part)]
            except ValueError:
                raise ValueError(f"非法序号片段: {part!r}")
        for v in values:
            if v < 1 or v > n_atoms:
                raise ValueError(f"原子序号 {v} 超出范围 1–{n_atoms}")
            out.add(v)
    return sorted(out)


# ══════════════════════════════════════════════════════════════════
#  定向算法
# ══════════════════════════════════════════════════════════════════
def _rotation_between(v: np.ndarray, t: np.ndarray) -> np.ndarray:
    """把向量 v 旋转到 t 的 3×3 旋转矩阵（Rodrigues，含反平行特例）。"""
    vn = float(np.linalg.norm(v))
    tn = float(np.linalg.norm(t))
    if vn < 1e-12 or tn < 1e-12:
        return np.eye(3)
    v = v / vn
    t = t / tn
    c = float(np.dot(v, t))
    axis = np.cross(v, t)
    s = float(np.linalg.norm(axis))
    if s < 1e-12:
        if c > 0:
            return np.eye(3)
        # 反平行：绕任一垂直轴转 180°
        ref = np.array([1.0, 0.0, 0.0]) if abs(v[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        axis = np.cross(v, ref)
        axis = axis / float(np.linalg.norm(axis))
        s, c = 0.0, -1.0
    else:
        axis = axis / s
    K = np.array([[0.0, -axis[2], axis[1]],
                  [axis[2], 0.0, -axis[0]],
                  [-axis[1], axis[0], 0.0]])
    return np.eye(3) + s * K + (1.0 - c) * (K @ K)


def _rot_z(theta: float) -> np.ndarray:
    c, s = math.cos(theta), math.sin(theta)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


@dataclass
class OrientationInfo:
    """定向过程的诊断信息，用于 UI 反馈、metadata 与自检。"""

    centre: np.ndarray
    axis_vector: np.ndarray          # 原始坐标系里 球心 → z 轴原子平均
    axis_length: float
    xz_vector: np.ndarray            # 原始坐标系里 球心 → xz 原子平均
    xz_length: float
    angle_axis_xz_deg: float         # 两向量夹角（不要求垂直）
    roll_deg: float                  # 绕 z 的实际滚转角
    xz_projection: float             # 定向后 xz 原子方向的水平投影长度
    axis_consistency: float          # |平均值| / 平均模长：1=同向叠加，→0=相消（脆弱）
    xz_projection_fraction: float    # 水平投影 / xz 向量长度（=sin(与z轴夹角)），→0=滚转不可靠
    rotation_matrix: np.ndarray      # R：oriented = (P − centre) @ R.T + z 平移
    displacement_shift: float        # 实际施加的 z 平移（带符号）
    warnings: list[tuple] = field(default_factory=list)   # [(code, params), ...]
    notes: list[tuple] = field(default_factory=list)      # 仅提示，不影响可用性


def orient_sambvca(positions: np.ndarray, job: SambVcaJob,
                   n_atoms: int | None = None):
    """按官方流程定向。返回 (oriented_positions, OrientationInfo)。"""
    P = np.asarray(positions, dtype=float)
    if P.ndim != 2 or P.shape[1] != 3:
        raise ValueError("positions 形状必须为 (n_atoms, 3)")
    n = int(P.shape[0]) if n_atoms is None else int(n_atoms)

    if not job.centre_atoms:
        raise ValueError("必须指定至少一个球心原子（官方 nAtomGC ≥ 1）")
    for name, idxs in (("球心", job.centre_atoms), ("z 轴", job.z_axis_atoms),
                       ("xz 平面", job.xz_plane_atoms)):
        for i in idxs:
            if i < 1 or i > n:
                raise ValueError(f"{name}原子序号 {i} 超出范围 1–{n}")

    warn: list[tuple] = []
    note: list[tuple] = []

    # ① 球心 = 算术平均，全体平移
    centre = P[[i - 1 for i in job.centre_atoms]].mean(axis=0)
    O = P - centre

    # ② z 轴
    if not job.z_axis_atoms:
        raise ValueError("必须指定至少一个 z 轴原子（官方 nAtom_z ≥ 1）")
    v_atoms = O[[i - 1 for i in job.z_axis_atoms]]
    z_vec = v_atoms.mean(axis=0)
    axis_length = float(np.linalg.norm(z_vec))
    mean_norm = float(np.mean([float(np.linalg.norm(v)) for v in v_atoms]))
    # 一致性：所选原子方向接近相消时（如球心两侧的对称原子），轴向由微小不对称决定
    axis_consistency = float(axis_length / mean_norm) if mean_norm > 1e-12 else 0.0
    if axis_length < 1e-8:
        raise ValueError("轴向量退化：z 轴原子的几何平均与球心重合，无法定义 z 轴")
    target = np.array([0.0, 0.0, -1.0 if job.align_z == 0 else 1.0])
    R1 = _rotation_between(z_vec, target)
    O = O @ R1.T

    # ③ xz 平面 → 锁定绕 z 的滚转
    roll_deg = 0.0
    xz_projection = float("nan")
    xz_projection_fraction = float("nan")
    xz_vec = np.zeros(3)
    xz_length = 0.0
    R2 = np.eye(3)
    if job.xz_plane_atoms:
        xz_vec = O[[i - 1 for i in job.xz_plane_atoms]].mean(axis=0)
        xz_length = float(np.linalg.norm(xz_vec))
        proj = np.array([xz_vec[0], xz_vec[1], 0.0])
        roll_deg = math.degrees(math.atan2(proj[1], proj[0]))
        R2 = _rot_z(-math.radians(roll_deg))
        O = O @ R2.T
        xz_projection = float(np.linalg.norm(proj))
        xz_projection_fraction = (xz_projection / xz_length) if xz_length > 1e-12 else 0.0
    else:
        warn.append(("no_xz", {}))

    # ④ Disp：整体沿 z 平移
    shift = -float(job.displacement) if job.align_z == 0 else float(job.displacement)
    if shift:
        O = O.copy()
        O[:, 2] += shift

    # 原始坐标系里 xz 向量的方向（供 UI 显示）
    xz_vec_raw = (P[[i - 1 for i in job.xz_plane_atoms]].mean(axis=0) - centre
                  if job.xz_plane_atoms else np.zeros(3))
    xz_len_raw = float(np.linalg.norm(xz_vec_raw))
    if axis_length and xz_len_raw:
        cosv = float(np.dot(z_vec, xz_vec_raw) / (axis_length * xz_len_raw))
        angle = math.degrees(math.acos(max(-1.0, min(1.0, cosv))))
    else:
        angle = float("nan")

    # ── 自检 ──
    # 轴向：用尺度无关的"一致性"判据。官方 nhc-C210 示例的轴长仅 0.789 Å 却完全可用
    # （两个对称 N 同向叠加，一致性 0.58），因此不能用绝对长度设卡。
    if axis_consistency < 0.25:
        warn.append(("axis_cancel", {"ratio": axis_consistency, "len": axis_length}))
    elif axis_length < 1.0:
        note.append(("axis_short_ok", {"len": axis_length, "ratio": axis_consistency}))
    if job.xz_plane_atoms and xz_projection_fraction < 0.30:
        warn.append(("xz_parallel", {"proj": xz_projection,
                                     "frac": xz_projection_fraction,
                                     "angle": angle}))
    if not job.delete_atoms:
        warn.append(("empty_delete", {}))
    centre_set = set(job.centre_atoms)
    if centre_set and not (centre_set & set(job.delete_atoms)) and not job.include_origin:
        warn.append(("centre_not_deleted", {"ids": ",".join(str(i) for i in job.centre_atoms)}))
    if abs(job.sphere_radius - 3.5) > 1e-9:
        warn.append(("radius_nonstandard", {"r": job.sphere_radius}))

    R = R2 @ R1
    info = OrientationInfo(
        centre=centre, axis_vector=z_vec, axis_length=axis_length,
        xz_vector=xz_vec_raw, xz_length=xz_len_raw, angle_axis_xz_deg=angle,
        roll_deg=roll_deg, xz_projection=xz_projection,
        axis_consistency=axis_consistency,
        xz_projection_fraction=xz_projection_fraction,
        rotation_matrix=R, displacement_shift=shift,
        warnings=warn, notes=note,
    )
    return O, info


# ══════════════════════════════════════════════════════════════════
#  自检信息的本地化文案（GUI 可传入自己的 tr 覆盖）
# ══════════════════════════════════════════════════════════════════
WARNING_TEXT_ZH = {
    "axis_cancel": "所选 z 轴原子相对球心的方向接近相互抵消（一致性 {ratio:.2f}，轴向长度 {len:.3f} Å）："
                   "轴向由微小不对称决定，建议改选其他原子",
    "xz_parallel": "xz 原子方向几乎与 z 轴平行（水平投影 {proj:.3f} Å，仅为向量长度的 {frac:.0%}，"
                   "夹角 {angle:.1f}°）：滚转角不可靠，请改选其他原子",
    "no_xz": "未指定 xz 平面原子：绕 z 轴的滚转未被锁定，不同次计算的地图/象限朝向可能不一致",
    "empty_delete": "删除列表为空：配合物中其它配体、反离子、溶剂都会计入体积"
                    "（官方要求把不属于目标配体的原子全部删除）",
    "centre_not_deleted": "球心原子（{ids} 号）未在删除列表中：官方要求把它一并删除；"
                          "当前结果仍会把它计入体积（与官方 SambVca 行为一致），"
                          "如需严格对照文献请把它加入删除列表",
    "radius_nonstandard": "球半径 R = {r:g} Å 不是官方推荐的 3.5 Å，与文献 %VBur 不可直接比较",
}
NOTE_TEXT_ZH = {
    "axis_short_ok": "轴向量较短（{len:.3f} Å），但方向稳健（一致性 {ratio:.2f}），可以使用",
}

# English counterparts (MolStudio addition). The original StericMapAnalyzer module
# only shipped Chinese text; numerics/behaviour are untouched.
WARNING_TEXT_EN = {
    "axis_cancel": "The selected z-axis atoms nearly cancel out about the sphere centre "
                   "(consistency {ratio:.2f}, axis length {len:.3f} Å): the axis is set by a "
                   "tiny asymmetry; choose different atoms",
    "xz_parallel": "The xz atom direction is almost parallel to the z axis (horizontal "
                   "projection {proj:.3f} Å, only {frac:.0%} of the vector length, angle "
                   "{angle:.1f}°): the roll angle is unreliable; choose different atoms",
    "no_xz": "No xz-plane atoms given: the roll about the z axis is unlocked, so map/quadrant "
             "orientation may differ between runs",
    "empty_delete": "The delete list is empty: other ligands, counter-ions and solvent will all "
                    "be counted in the volume (SambVca requires deleting every atom not in "
                    "the target ligand)",
    "centre_not_deleted": "Sphere-centre atom(s) {ids} are not in the delete list: SambVca "
                          "requires deleting them too; the current result still counts them "
                          "in the volume (official SambVca behaviour). Add them to the delete "
                          "list for strict comparison with the literature",
    "radius_nonstandard": "Sphere radius R = {r:g} Å is not the recommended 3.5 Å; %VBur is not "
                          "directly comparable with the literature",
}
NOTE_TEXT_EN = {
    "axis_short_ok": "The axis vector is short ({len:.3f} Å) but its direction is robust "
                     "(consistency {ratio:.2f}); usable",
}


def _pick_text(code: str, params, tr, lang: str) -> str:
    """内置 zh/en 文案查表 + 可选 GUI 翻译函数覆盖（tr 优先）。"""
    is_warning = code in WARNING_TEXT_ZH
    table = (WARNING_TEXT_ZH, WARNING_TEXT_EN) if is_warning else (NOTE_TEXT_ZH, NOTE_TEXT_EN)
    key = f"warn_{code}" if is_warning else f"note_{code}"
    text = None
    if tr is not None:
        try:
            cand = tr(key)
            text = cand if cand and cand != key else None
        except Exception:
            text = None
    if text is None:
        use_en = str(lang or "zh").lower().startswith("en")
        text = table[1 if use_en else 0].get(code) or table[0].get(code) or code
    try:
        return text.format(**params) if params else text
    except (KeyError, IndexError, ValueError):
        return text


def format_diag(item, tr=None, lang: str = "zh") -> str:
    """把 (code, params) 诊断项格式化为本地化文本。

    * ``tr``：可选的 GUI 翻译函数，键为 ``warn_<code>`` / ``note_<code>``；
      返回 None / 空串 / 原 key 时回落到内置表（与源实现一致）。
    * ``lang``：``"zh"``（默认）或 ``"en"``，仅在无 tr 覆盖时决定内置文案。
    """
    if isinstance(item, (tuple, list)) and len(item) == 2:
        code, params = item
    else:
        code, params = item, {}
    params = params or {}
    return _pick_text(str(code), params, tr, lang)


# ══════════════════════════════════════════════════════════════════
#  参与体积计算的原子筛选
# ══════════════════════════════════════════════════════════════════
def select_atoms(symbols: Sequence[str], job: SambVcaJob) -> tuple[list[int], list[int]]:
    """返回 (参与计算的 0-based 序号, 被排除的 1-based 序号)。

    规则与官方一致：先按删除列表剔除，再按 RemoveH 剔除氢。
    球心原子不自动豁免（若未列入删除列表则照旧计入）——与官方行为一致。
    """
    n = len(symbols)
    deleted = set(job.delete_atoms)
    keep = []
    for i in range(1, n + 1):
        if i in deleted:
            continue
        if job.remove_h and symbols[i - 1].strip().upper() == "H":
            continue
        keep.append(i - 1)
    excluded = sorted(set(range(1, n + 1)) - {i + 1 for i in keep})
    return keep, excluded


# ══════════════════════════════════════════════════════════════════
#  .inp 读写（与官方格式互操作）
# ══════════════════════════════════════════════════════════════════
_INP_COMMENTS = (
    "! How many atoms to delete. If > 0, one line below to specify ID of atoms to be deleted",
    "! Id of atoms to be deleted",
    "! How many atoms define the sphere center. If > 1, then middle point of coordinates",
    "! Id of atoms defining the sphere center",
    "! How many atoms define the z-axis. If > 1, then middle point of coordinates",
    "! Id of atoms for z-axis",
    "! How many atoms define the xz-plane. If > 1, then middle point of coordinates",
    "! Id of atoms for xz-plane",
    "! Sphere radius",
    "! Displacement of oriented molecule from sphere center",
    "! Mesh size for numerical integration",
    "! 0/1 = Do not remove/remove H atoms from Vbur calculation",
    "! 0/1 = molecule oriented along negative/positive Z-axis",
    "! 0/1 = Do not write/write files for top and bottom surfaces",
)


def as_job(job) -> SambVcaJob:
    """把 ``SambVcaJob`` 或等价的 dict（如 ``StericResult.job``）统一成 SambVcaJob。

    未知键会被忽略（``raw_radius_table`` 等内部字段可安全往返），方便面板直接
    ``write_inp(path, result.job, symbols, positions)``。
    """
    if isinstance(job, SambVcaJob):
        return job
    if isinstance(job, dict):
        names = {f.name for f in fields(SambVcaJob)}
        return SambVcaJob(**{k: v for k, v in job.items() if k in names})
    raise TypeError(f"job 必须是 SambVcaJob 或 dict，收到 {type(job).__name__}")


def _table_matches_builtin(table: dict, builtin: dict) -> bool:
    """判断 .inp 里的半径表是否等价于某套内置表（至少 20 个元素逐个吻合）。"""
    hits = 0
    for sym, val in builtin.items():
        got = table.get(str(sym).upper())
        if got is None:
            continue
        try:
            if abs(float(got) - float(val)) > 0.011:
                return False
        except (TypeError, ValueError):
            return False
        hits += 1
    return hits >= 20


def write_inp(path: str | Path, job: SambVcaJob | dict, symbols: Sequence[str],
              positions: np.ndarray, title: str = "Steric Map Analyzer") -> Path:
    """写出官方可读的 .inp（半径表与本次计算所用半径集一致）。

    ``job`` 同时接受 :class:`SambVcaJob` 与等价的 dict（例如 ``result.job``）。
    半径集为 ``bondi`` 时写官方 Bondi 表、``bondi-scaled``（默认）时写官方
    scaled-Bondi 表，这样导出的 .inp 重新载入/交给官方 SambVca 都能复现同一
    数值；若 job 里带了一份与两套内置表都不同的原始半径表（从自定义 .inp
    读入），则原样写回，保证往返不丢信息。
    """
    job = as_job(job)
    P = np.asarray(positions, dtype=float)
    raw_table = dict(getattr(job, "raw_radius_table", None) or {})
    if raw_table and not _table_matches_builtin(raw_table, BONDI_RADII) \
            and not _table_matches_builtin(raw_table, BONDI_SCALED_RADII):
        radii_table = {str(k).strip().upper(): float(v)
                       for k, v in raw_table.items()}
    elif job.radii_set == "bondi":
        radii_table = {k: float(v) for k, v in BONDI_RADII.items()}
    else:
        radii_table = {k: float(v) for k, v in BONDI_SCALED_RADII.items()}
    lines: list[str] = []
    lines.append(f"{len(job.delete_atoms):<18}{_INP_COMMENTS[0]}")
    if job.delete_atoms:
        lines.append(f"{' '.join(str(i) for i in job.delete_atoms):<18}{_INP_COMMENTS[1]}")
    lines.append(f"{len(job.centre_atoms):<18}{_INP_COMMENTS[2]}")
    lines.append(f"{' '.join(str(i) for i in job.centre_atoms):<18}{_INP_COMMENTS[3]}")
    lines.append(f"{len(job.z_axis_atoms):<18}{_INP_COMMENTS[4]}")
    lines.append(f"{' '.join(str(i) for i in job.z_axis_atoms):<18}{_INP_COMMENTS[5]}")
    lines.append(f"{len(job.xz_plane_atoms):<18}{_INP_COMMENTS[6]}")
    if job.xz_plane_atoms:
        lines.append(f"{' '.join(str(i) for i in job.xz_plane_atoms):<18}{_INP_COMMENTS[7]}")
    lines.append(f"{job.sphere_radius:<18g}{_INP_COMMENTS[8]}")
    lines.append(f"{job.displacement:<18g}{_INP_COMMENTS[9]}")
    lines.append(f"{job.mesh:<18g}{_INP_COMMENTS[10]}")
    lines.append(f"{job.remove_h:<18d}{_INP_COMMENTS[11]}")
    lines.append(f"{job.align_z:<18d}{_INP_COMMENTS[12]}")
    lines.append(f"{job.write_surfaces:<18d}{_INP_COMMENTS[13]}")
    lines.append(f"{len(radii_table)}\t          ! number of radii to be read in "
                 f"the following, then radii. All radii are uppercase.")
    for name, r in radii_table.items():
        lines.append(f"{name.upper():<8}{float(r):.2f}")
    lines.append(str(len(symbols)))
    lines.append(title)
    for sym, (x, y, z) in zip(symbols, P):
        lines.append(f"{sym:<4}{x:14.8f}{y:14.8f}{z:14.8f}")
    p = Path(path)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def read_inp(path: str | Path) -> tuple[SambVcaJob, list[str], np.ndarray, str]:
    """读取官方 .inp（或本模块写出的 .inp），返回 (job, symbols, positions, title)。

    半径集按文件里的半径表内容判定（Bondi / scaled-Bondi），因此 Bondi 模式
    导出的 .inp 重读后能复现同一结果。注意：计算本身只用内置的两套半径集
    （官方 .inp 的表都与内置 scaled-Bondi 等价）；若 .inp 带完全自定义的半径
    表，``raw_radius_table`` 会被原样保留以便无损往返，但体积计算不会使用它。
    """
    raw = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    lines: list[str] = []
    for ln in raw:
        ln = ln.split("!")[0].strip()
        if ln:
            lines.append(ln)

    def tok(i: int) -> str:
        return lines[i]

    i = 0
    n_del = int(tok(i)); i += 1
    del_atoms = [int(x) for x in tok(i).split()] if n_del > 0 else []
    if n_del > 0:
        i += 1
    n_gc = int(tok(i)); i += 1
    gc = [int(x) for x in tok(i).split()] if n_gc > 0 else []
    if n_gc > 0:
        i += 1
    n_z = int(tok(i)); i += 1
    z_atoms = [int(x) for x in tok(i).split()] if n_z > 0 else []
    if n_z > 0:
        i += 1
    n_xz = int(tok(i)); i += 1
    xz_atoms = [int(x) for x in tok(i).split()] if n_xz > 0 else []
    if n_xz > 0:
        i += 1
    radius = float(tok(i)); i += 1
    disp = float(tok(i)); i += 1
    bin_size = float(tok(i)); i += 1
    remove_h = int(tok(i)); i += 1
    align_z = int(tok(i)); i += 1
    do_map = int(tok(i)); i += 1
    n_types = int(tok(i)); i += 1
    table: dict[str, float] = {}
    for _ in range(n_types):
        parts = tok(i).split()
        table[parts[0].upper()] = float(parts[1])
        i += 1
    n_atoms = int(tok(i)); i += 1
    title = tok(i); i += 1
    syms, xyz = [], []
    for _ in range(n_atoms):
        parts = tok(i).split()
        syms.append(parts[0])
        xyz.append([float(parts[1]), float(parts[2]), float(parts[3])])
        i += 1

    # 半径集：老版官方 .inp 以 Radius 正负表示 scaled / raw Bondi；本模块写出的
    # .inp 还会带上真实半径表，因此优先按表内容判定（否则从 Bondi 模式导出的
    # 文件回读时会被误当成 scaled，重算结果与屏幕不一致）。
    if _table_matches_builtin(table, BONDI_RADII):
        radii_set = "bondi"
    elif _table_matches_builtin(table, BONDI_SCALED_RADII):
        radii_set = "bondi-scaled"
    else:
        radii_set = "bondi-scaled" if radius > 0 else "bondi"
    job = SambVcaJob(
        delete_atoms=del_atoms, centre_atoms=gc, z_axis_atoms=z_atoms,
        xz_plane_atoms=xz_atoms, sphere_radius=abs(radius), displacement=disp,
        mesh=bin_size, remove_h=remove_h, align_z=align_z, write_surfaces=do_map,
        radii_set=radii_set,
        raw_radius_negative=radius < 0, raw_n_types=n_types, raw_radius_table=table,
    )
    return job, syms, np.array(xyz, dtype=float), title


__all__ = [
    "BONDI_RADII", "BONDI_SCALED_RADII", "RADII_SETS", "RADII_SCALE",
    "DUMMY_TYPE_NAME", "DUMMY_TYPE_RADIUS",
    "SambVcaJob", "OrientationInfo", "orient_sambvca", "select_atoms",
    "radii_for_symbols", "parse_index_spec", "write_inp", "read_inp", "as_job",
    "WARNING_TEXT_ZH", "NOTE_TEXT_ZH", "WARNING_TEXT_EN", "NOTE_TEXT_EN",
    "format_diag",
]
