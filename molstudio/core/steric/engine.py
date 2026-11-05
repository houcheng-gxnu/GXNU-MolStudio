# -*- coding: utf-8 -*-
# Ported from StericMapAnalyzer (GPLv3) — SambVca 2.1 official algorithm replica.
# 来源：StericMapAnalyzer v3.5（同作者仓库，GPL-3.0-only）的 compute.py
# （validate_job / run_job 的计算流程）与 export.py 的元数据结构。
# License: GPL-3.0-only (inherited from StericMapAnalyzer).
# MolStudio 移植版：去掉 GUI 线程、全局引擎开关与 stericrender 硬依赖；
# 引擎作为参数传入、纯 numpy 实现，可安全并发调用。
"""SambVca 位阻地图与 %VBur 纯计算引擎。

计算流程与官方 / 源工程 ``run_job`` 完全一致::

    ① 定向（三步刚体变换，见 sambvca.orient_sambvca）
    ② 按删除表 + RemoveH 筛选参与体积计算的原子
    ③ 体素法埋藏体积（%VBur、四象限、八分区）
    ④ 位阻地图（官方 TopSurface，重建为 (ny, nx) 网格，空列为 NaN）

定向方式（MolStudio 扩展，默认 ``sambvca`` 与官方逐位一致）：

* ``'sambvca'``：官方三步刚体变换（球心 → z 轴 → xz 锁滚转）。
* ``'view'``：按画布视角定向 —— ``params['orient_mode']='view'`` 且
  ``compute(..., view_rotation=R)``，其中 ``R`` 是 world → screen 的 3×3 旋转
  矩阵（+z 指向观察者，面板用 ``surface_projection.camera_rotation(glw)`` 取）。
  此时 ``oriented = (positions - centre) @ R.T``，跳过 ``orient_sambvca``，
  忽略 z 轴 / xz 原子（不报错）。

公开接口：:class:`MapGrid`、:class:`StericResult`、:class:`StericError`、
:class:`StericCancelled`、``ENGINES`` / ``DEFAULT_ENGINE`` /
``ORIENT_MODES`` / ``DEFAULT_ORIENT_MODE``、
:func:`available_engines`、:func:`auto_roles`、:func:`validate`、
:func:`compute`、:func:`format_orientation_report`。

本模块只依赖 numpy（stdlib 允许），不 import PyQt5 / matplotlib / OpenGL；
没有模块级可变引擎状态。
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .molecule import ELEMENT_SYMBOLS
from .native import native_buried_volume, native_surfaces
from .sambvca import (
    RADII_SETS,
    SambVcaJob,
    format_diag,
    orient_sambvca,
    parse_index_spec,
    radii_for_symbols,
    select_atoms,
)

__all__ = [
    "MAX_VOXEL_POINTS", "MAX_MAP_POINTS", "ENGINES", "DEFAULT_ENGINE",
    "ORIENT_MODES", "DEFAULT_ORIENT_MODE",
    "MapGrid", "StericResult", "StericError", "StericCancelled",
    "available_engines", "auto_roles", "validate", "compute",
    "format_orientation_report",
]

# ── 网格规模保护（与源工程 compute.py 同一套上限） ──────────────────
# 位阻体积用体素化，峰值内存 ≈ 60 * n³ 字节；R=3.5/mesh=0.01 约需 7.7 GB，
# 因此在校验阶段就按估算点数设卡。
MAX_VOXEL_POINTS = 5.0e7      # 体素网格 (3D) 上限，约 3 GB 峰值
MAX_MAP_POINTS = 2.0e7        # 位阻地图网格 (2D) 上限

ENGINES: Tuple[str, ...] = ("native", "stericrender")
DEFAULT_ENGINE: str = "native"

#: 定向方式：``sambvca``（官方三步刚体变换，默认）/ ``view``（按画布视角）。
ORIENT_MODES: Tuple[str, ...] = ("sambvca", "view")
DEFAULT_ORIENT_MODE: str = "sambvca"

# 元素符号 → 原子序数（1-118），用于 auto_roles 选中心原子。
_ATOMIC_NUMBER: Dict[str, int] = {
    sym: num for num, sym in ELEMENT_SYMBOLS.items()
}
# 过渡金属 / 镧系 / 锕系（auto_roles 的中心原子优先候选）
_METAL_Z: Tuple[int, ...] = (
    tuple(range(21, 31)) + tuple(range(39, 49)) + tuple(range(72, 81))
    + tuple(range(57, 72)) + tuple(range(89, 104))
)


# ══════════════════════════════════════════════════════════════════
#  本地化文案（zh / en）
# ══════════════════════════════════════════════════════════════════
_TEXT: Dict[str, Tuple[str, str]] = {
    # ── 校验错误 ──
    "err_no_molecule": ("未提供分子：原子列表为空", "no molecule: the atom list is empty"),
    "err_bad_coords": ("坐标数组形状必须为 (n, 3) 且与原子数一致",
                       "coordinates must have shape (n, 3) and match the atom list"),
    "err_index_format": ("原子序号表达式非法：{detail}",
                         "invalid atom-index expression: {detail}"),
    "err_no_centre": ("必须指定至少一个球心原子（官方 nAtomGC ≥ 1）",
                      "at least one sphere-centre atom is required (official nAtomGC >= 1)"),
    "err_no_zaxis": ("必须指定至少一个 z 轴原子（官方 nAtom_z ≥ 1）",
                     "at least one z-axis atom is required (official nAtom_z >= 1)"),
    "err_zaxis_degenerate": ("z 轴原子的几何平均与球心重合，无法定义 z 轴；请改选 z 轴原子",
                             "the z-axis atoms average to the sphere centre; the z axis is "
                             "undefined, choose different z-axis atoms"),
    "err_sphere_range": ("球半径必须在 (0, 100] Å 之间", "sphere radius must be in (0, 100] Å"),
    "err_sphere_format": ("球半径不是合法数字", "sphere radius is not a valid number"),
    "err_map_range": ("地图半径必须在 (0, 100] Å 之间", "map radius must be in (0, 100] Å"),
    "err_map_format": ("地图半径不是合法数字", "map radius is not a valid number"),
    "err_mesh_range": ("网格间距必须在 (0.005, 1.0] Å 之间",
                       "mesh size must be in (0.005, 1.0] Å"),
    "err_mesh_format": ("网格间距不是合法数字", "mesh size is not a valid number"),
    "err_disp_range": ("位移量绝对值不能超过 20 Å", "|displacement| must not exceed 20 Å"),
    "err_disp_format": ("位移量不是合法数字", "displacement is not a valid number"),
    "err_alignz_range": ("AlignZ 只能取 0（配体朝 −z）或 1（配体朝 +z）",
                         "AlignZ must be 0 (ligand toward -z) or 1 (ligand toward +z)"),
    "err_radii_set": ("未知半径集：{values}（可选 {sets}）",
                      "unknown radii set: {values} (choose from {sets})"),
    "err_grid_too_dense": ("体素网格过密（球半径 {r:g} Å、间距 {mesh:g} Å 约 {n:.3g} 个体素，"
                           "峰值内存约 {gb:.1f} GB）；建议网格间距 ≥ {suggest:.3f} Å",
                           "voxel grid too dense (R={r:g} Å, mesh={mesh:g} Å gives about {n:.3g} "
                           "voxels, ~{gb:.1f} GB peak); use mesh >= {suggest:.3f} Å"),
    "err_map_too_dense": ("位阻地图网格过密（半径 {m:g} Å、间距 {mesh:g} Å 约 {n:.3g} 个格点）；"
                          "建议网格间距 ≥ {suggest:.3f} Å",
                          "steric-map grid too dense (radius {m:g} Å, mesh={mesh:g} Å gives about "
                          "{n:.3g} points); use mesh >= {suggest:.3f} Å"),
    "err_no_atoms_selected": ("删除/去氢后没有原子参与体积计算；请检查删除列表与 RemoveH 设置",
                              "no atoms left for the volume calculation after deletion/RemoveH; "
                              "check the delete list and the RemoveH setting"),
    "err_engine_unknown": ("未知计算引擎：{engine}（可用：{engines}）",
                           "unknown engine: {engine} (available: {engines})"),
    "err_engine_unavailable": ("计算引擎 {engine} 不可用（未安装 stericrender）",
                               "engine {engine} is unavailable (stericrender is not installed)"),
    "err_orient": ("定向失败：{detail}", "orientation failed: {detail}"),
    # ── 定向方式 / 画布视角 ──
    "err_orient_mode": ("未知定向方式：{mode}（可选 sambvca / view）",
                        "unknown orientation mode: {mode} (choose sambvca or view)"),
    "err_view_rotation_missing": ("画布视角定向需要提供 3×3 旋转矩阵（view_rotation）",
                                  "canvas-view orientation requires a 3×3 rotation matrix "
                                  "(view_rotation)"),
    "err_view_rotation_invalid": ("画布视角旋转矩阵非法：必须是有限的 3×3 矩阵且可逆（行列式非 0）",
                                  "invalid canvas-view rotation matrix: must be a finite, "
                                  "invertible 3×3 matrix (non-zero determinant)"),
    "log_orient_view": ("定向方式：画布视角（视图倾角 {tilt:.2f}°，忽略 z 轴/xz 原子）",
                        "orientation: canvas view (view tilt {tilt:.2f}°, z-axis/xz atoms "
                        "ignored)"),
    "rep_title_view": ("定向诊断（画布视角）", "orientation diagnostics (canvas view)"),
    "rep_mode_view": ("定向方式：画布视角，视图倾角 {tilt:.1f}°，忽略 z 轴/xz 原子",
                      "orientation: canvas view, view tilt {tilt:.1f}°, z-axis/xz atoms ignored"),
    "rep_view_rotation": ("旋转矩阵（world→screen，行优先）：{rows}",
                          "rotation matrix (world→screen, row-major): {rows}"),
    "note_orient_view": ("已按画布视角定向：世界 → 屏幕旋转矩阵来自当前画布相机",
                         "oriented from the canvas view: the world → screen rotation matrix "
                         "comes from the current canvas camera"),
    "err_cancelled": ("计算已取消", "calculation cancelled"),
    "err_compute": ("计算失败：{detail}", "calculation failed: {detail}"),
    # ── 日志 / 进度 ──
    "log_engine_native": ("计算引擎：SambVca 官方算法·原生（逐位对齐官方 Fortran）",
                          "engine: SambVca official algorithm, native (bit-exact Fortran "
                          "replica)"),
    "log_engine_stericrender": ("计算引擎：StericRender",
                                "engine: StericRender"),
    "log_engine_fallback": ("引擎 {engine} 不可用，已回退到 native 引擎",
                            "engine {engine} is unavailable; falling back to the native engine"),
    "log_params": ("参数：R={r:g} Å，地图半径={m:g} Å，网格间距={mesh:g} Å",
                   "parameters: R={r:g} Å, map radius={m:g} Å, mesh={mesh:g} Å"),
    "log_n_atoms": ("参与计算的原子数：{n}", "atoms used in the calculation: {n}"),
    "log_excluded": ("被排除的原子（1-based）：{ids}",
                     "excluded atoms (1-based): {ids}"),
    "log_none": ("无", "none"),
    "log_radii_missing": ("以下元素不在官方半径表中，按默认 2.00 Å 兜底：{syms}",
                          "elements missing from the official radii table (2.00 Å fallback "
                          "used): {syms}"),
    "log_volume_start": ("正在计算埋藏体积…", "computing buried volume…"),
    "log_volume_done": ("埋藏体积完成：%VBur = {pct:.4f}%，埋藏体积 {v:.3f} Å³，用时 {t:.3f} s",
                        "buried volume done: %VBur = {pct:.4f}%, buried {v:.3f} Å³, {t:.3f} s"),
    "log_map_start": ("正在生成位阻地图…", "generating steric map…"),
    "log_map_done": ("位阻地图完成：{nz} 个有效格点，用时 {t:.3f} s",
                     "steric map done: {nz} valid grid points, {t:.3f} s"),
    "log_done": ("计算完成：%VBur = {pct:.4f}%，总用时 {t:.3f} s",
                 "done: %VBur = {pct:.4f}%, total {t:.3f} s"),
    "log_warn": ("⚠ {text}", "⚠ {text}"),
    "log_note": ("· {text}", "· {text}"),
    "step_orient": ("定向分子…", "orienting molecule…"),
    "step_select": ("筛选参与计算的原子…", "selecting atoms…"),
    "step_volume": ("计算埋藏体积…", "computing buried volume…"),
    "step_map": ("生成位阻地图…", "generating steric map…"),
    "step_done": ("计算完成", "done"),
    # ── 定向诊断报告 ──
    "rep_title": ("SambVca 定向诊断", "SambVca orientation diagnostics"),
    "rep_centre": ("球心（原始坐标，Å）：({x:.4f}, {y:.4f}, {z:.4f})",
                   "sphere centre (original coords, Å): ({x:.4f}, {y:.4f}, {z:.4f})"),
    "rep_axis": ("轴向长度 = {len:.4f} Å，一致性 = {cons:.2f}，与 xz 夹角 = {angle:.1f}°",
                 "axis length = {len:.4f} Å, consistency = {cons:.2f}, angle to xz = {angle:.1f}°"),
    "rep_roll": ("滚转角 = {roll:.2f}°，xz 水平投影占比 = {frac:.2f}",
                 "roll = {roll:.2f}°, xz horizontal-projection fraction = {frac:.2f}"),
    "rep_disp": ("沿 z 位移 = {shift:.3f} Å，定向目标：{target}",
                 "z displacement = {shift:.3f} Å, orientation target: {target}"),
    "rep_target_neg": ("配体朝 −z（AlignZ=0）", "ligand toward -z (AlignZ=0)"),
    "rep_target_pos": ("配体朝 +z（AlignZ=1）", "ligand toward +z (AlignZ=1)"),
    "rep_warn": ("警告：", "warnings:"),
    "rep_note": ("提示：", "notes:"),
    "rep_none": ("（无）", "(none)"),
}


def _lang(lang: Any) -> str:
    return "en" if str(lang or "zh").lower().startswith("en") else "zh"


def _t(key: str, lang: Any = "zh", **kw: Any) -> str:
    zh, en = _TEXT.get(key, (key, key))
    tpl = en if _lang(lang) == "en" else zh
    try:
        return tpl.format(**kw)
    except (KeyError, IndexError, ValueError):
        return tpl


# ══════════════════════════════════════════════════════════════════
#  错误类型与结果模型
# ══════════════════════════════════════════════════════════════════
class StericError(RuntimeError):
    """参数校验失败 / 计算不可执行（消息已本地化）。"""


class StericCancelled(RuntimeError):
    """计算被 should_cancel() 取消。"""

    def __init__(self, message: str = ""):
        super().__init__(message or "calculation cancelled / 计算已取消")


@dataclass
class MapGrid:
    """位阻地图网格。

    ``x`` 长度 nx，``y`` 长度 ny，``z`` 形状 (ny, nx)；``NaN`` = 该格上方
    没有任何 vdW 表面（官方 .dat 里的 ±2R 哨兵已剔除）。
    """

    x: np.ndarray
    y: np.ndarray
    z: np.ndarray

    def __post_init__(self) -> None:
        self.x = np.asarray(self.x, dtype=float).ravel()
        self.y = np.asarray(self.y, dtype=float).ravel()
        self.z = np.asarray(self.z, dtype=float)
        if self.z.shape != (self.y.size, self.x.size):
            raise ValueError(
                f"map.z 形状必须为 (ny, nx) = ({self.y.size}, {self.x.size})，"
                f"实际 {self.z.shape} / map.z must be (ny, nx)")


@dataclass
class StericResult:
    """一次 SambVca 计算的完整结果（面板/导出只读）。"""

    symbols: List[str]
    positions: np.ndarray                 # (n,3) 原始坐标（Å）
    oriented_positions: np.ndarray        # (n,3) 定向后坐标（Å）
    map: MapGrid
    percent_buried: float
    buried_volume: float
    free_volume: float
    sphere_volume: float
    quadrant_percent: Dict[str, float]    # 'NE','NW','SW','SE'
    octant_percent: Dict[str, float]      # 如 'NE+z'
    selected_atoms: List[int]             # 1-based
    excluded_atoms: List[int]             # 1-based
    job: Dict[str, Any]                   # SambVcaJob.to_dict()
    engine: str
    radii_set: str
    include_h: bool
    sphere_radius: float
    map_radius: float
    mesh: float
    orientation: Dict[str, Any]
    warnings: List[Tuple[str, dict]]
    log: List[Tuple[str, str]]
    elapsed: Dict[str, float]
    color_range: Tuple[float, float]
    #: 定向方式：``"sambvca"``（官方三步刚体变换）或 ``"view"``（按画布视角）。
    orient_mode: str = DEFAULT_ORIENT_MODE


# ══════════════════════════════════════════════════════════════════
#  引擎可用性 / 体积与地图适配
# ══════════════════════════════════════════════════════════════════
def _stericrender_modules():
    """返回 (compute_buried_volume, compute_steric_map)，不可用时返回 None。

    不缓存模块状态、不设置全局引擎开关；import 失败即视为不可用。
    """
    try:  # pragma: no cover - 取决于环境是否安装 stericrender
        from stericrender.maps import compute_steric_map
        from stericrender.volume import compute_buried_volume
        return compute_buried_volume, compute_steric_map
    except Exception:  # noqa: BLE001 - 任何 import 错误都当作不可用
        return None


def available_engines() -> Tuple[str, ...]:
    """只列出真正可用的引擎；``"native"`` 永远可用。"""
    engines = ["native"]
    if _stericrender_modules() is not None:
        engines.append("stericrender")
    return tuple(engines)


_QUADRANT_KEYS = ("NE", "NW", "SW", "SE")


def _native_volume(pos: np.ndarray, radii: np.ndarray, sphere_radius: float,
                   mesh: float) -> Dict[str, Any]:
    d = native_buried_volume(pos, radii, sphere_radius=sphere_radius, mesh=mesh)
    q = d["quadrant_percent"]
    return {
        "percent_buried": float(d["percent_buried"]),
        "buried_volume": float(d["buried_volume"]),
        "free_volume": float(d["free_volume"]),
        "sphere_volume": float(d["sphere_volume"]),
        "quadrant_percent": {k: float(q.get(k, float("nan"))) for k in _QUADRANT_KEYS},
        "octant_percent": {k: float(v) for k, v in d["octant_percent"].items()},
    }


def _stericrender_volume(pos: np.ndarray, radii: np.ndarray, sphere_radius: float,
                         mesh: float) -> Dict[str, Any]:
    mods = _stericrender_modules()
    if mods is None:  # pragma: no cover
        raise StericError(_t("err_engine_unavailable", engine="stericrender"))
    res = mods[0](pos, radii, sphere_radius=sphere_radius, mesh=mesh)
    q = getattr(res, "quadrant_percent", {}) or {}
    return {
        "percent_buried": float(res.percent_buried),
        "buried_volume": float(res.buried_volume),
        "free_volume": float(res.free_volume),
        "sphere_volume": float(res.sphere_volume),
        "quadrant_percent": {k: float(q.get(k, float("nan"))) for k in _QUADRANT_KEYS},
        # stericrender 只有半球分解，没有八分区；保持为空表示"该引擎不提供"
        "octant_percent": {},
    }


def _native_map(pos: np.ndarray, radii: np.ndarray, radius: float,
                mesh: float) -> MapGrid:
    """按源 compute.py 把逐行 (x, y, zmax) 重建成 (ny, nx)，并清理 ±2R 哨兵。"""
    s = native_surfaces(pos, radii, radius=radius, mesh=mesh)
    fx = np.asarray(s["x"], dtype=float).ravel()
    fy = np.asarray(s["y"], dtype=float).ravel()
    fz = np.asarray(s["zmax"], dtype=float).ravel()
    xv, yv = np.unique(fx), np.unique(fy)
    grid = np.full((yv.size, xv.size), np.nan, dtype=float)
    grid[np.searchsorted(yv, fy), np.searchsorted(xv, fx)] = fz
    grid[np.abs(grid) > radius + 1e-6] = np.nan       # 空列哨兵（±2R）→ NaN
    return MapGrid(x=xv, y=yv, z=grid)


def _stericrender_map(pos: np.ndarray, radii: np.ndarray, radius: float,
                      mesh: float) -> MapGrid:
    mods = _stericrender_modules()
    if mods is None:  # pragma: no cover
        raise StericError(_t("err_engine_unavailable", engine="stericrender"))
    res = mods[1](pos, radii, sphere_radius=radius, mesh=mesh)
    return MapGrid(
        x=np.asarray(res.x, dtype=float).ravel(),
        y=np.asarray(res.y, dtype=float).ravel(),
        z=np.asarray(res.z, dtype=float),
    )


# ══════════════════════════════════════════════════════════════════
#  auto_roles：从几何猜官方 .inp 的三个角色
# ══════════════════════════════════════════════════════════════════
def _symbol_of(sym: Any) -> str:
    return str(sym).strip().capitalize()


def auto_roles(symbols: Sequence[str], coords) -> Dict[str, str]:
    """按几何自动猜测官方 SambVca 角色（全部 1-based 字符串）。

    规则（与 task-1 契约一致）：

    * ``centre``：第一个过渡金属/镧系/锕系原子；没有金属时取原子序数最大的原子。
    * ``z_axis``：离球心最近的非 H 原子。
    * ``xz``：离球心最近、且与 z 轴夹角 > 15° 的非 H 原子（没有则 ``""``）。
    * ``delete``：只含中心原子（官方语义还要求手动删掉非目标配体原子）。
    """
    syms = [_symbol_of(s) for s in symbols]
    P = np.asarray(coords, dtype=float)
    n = len(syms)
    if n == 0 or P.ndim != 2 or P.shape[0] != n:
        return {"centre": "", "z_axis": "", "xz": "", "delete": ""}

    z_numbers = [_ATOMIC_NUMBER.get(s, 0) for s in syms]
    metal_set = set(_METAL_Z)
    centre_idx: Optional[int] = None
    for i, znum in enumerate(z_numbers):
        if znum in metal_set:
            centre_idx = i
            break
    if centre_idx is None:
        centre_idx = int(np.argmax(z_numbers)) if z_numbers else 0

    centre_1 = centre_idx + 1
    C = P[centre_idx]
    candidates = [(i, float(np.linalg.norm(P[i] - C)))
                  for i in range(n)
                  if i != centre_idx and syms[i] != "H"]
    candidates.sort(key=lambda item: (item[1], item[0]))
    if not candidates:
        return {"centre": str(centre_1), "z_axis": "", "xz": "", "delete": str(centre_1)}

    z_idx = candidates[0][0]
    z_vec = P[z_idx] - C
    z_len = float(np.linalg.norm(z_vec))
    xz_idx: Optional[int] = None
    if z_len > 1e-12:
        zhat = z_vec / z_len
        for i, _dist in candidates[1:]:
            v = P[i] - C
            v_len = float(np.linalg.norm(v))
            if v_len <= 1e-12:
                continue
            cosang = float(np.dot(v, zhat) / v_len)
            angle = math.degrees(math.acos(max(-1.0, min(1.0, cosang))))
            if angle > 15.0:
                xz_idx = i
                break
    return {
        "centre": str(centre_1),
        "z_axis": str(z_idx + 1),
        "xz": str(xz_idx + 1) if xz_idx is not None else "",
        "delete": str(centre_1),
    }


# ══════════════════════════════════════════════════════════════════
#  参数校验
# ══════════════════════════════════════════════════════════════════
def _index_text(value: Any) -> str:
    """把面板传来的序号参数统一成 parse_index_spec 能吃的字符串。"""
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ",".join(str(v) for v in value)
    return str(value)


def _param(params: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in params and params[key] is not None and params[key] != "":
            return params[key]
    return default


def _to_float(value: Any) -> float:
    if isinstance(value, str):
        return float(value.strip())
    return float(value)


def _to_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on", "y", "是", "去除"):
        return True
    if text in ("0", "false", "no", "off", "n", "否"):
        return False
    return default


# ── 定向方式（sambvca / view）───────────────────────────────────────
def _orient_mode(params: Dict[str, Any]) -> str:
    """从 params 取定向方式并规范化；未给 = ``sambvca``（官方默认）。"""
    raw = _param(params, "orient_mode", default=DEFAULT_ORIENT_MODE)
    return str(raw if raw is not None else DEFAULT_ORIENT_MODE).strip().lower()


def _coerce_view_rotation(value: Any) -> Optional[np.ndarray]:
    """把 ``view_rotation`` 规范成 (3,3) float 数组；非法返回 ``None``。

    非法 = 形状不是 3×3、含 NaN/inf、或行列式≈0（不可逆）。不要求它是纯旋转
    （行列式 +1），因为面板相机矩阵偶尔带数值缩放，只要可逆就能定向。
    """
    if value is None:
        return None
    try:
        R = np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        return None
    if R.shape != (3, 3) or not np.all(np.isfinite(R)):
        return None
    try:
        det = float(np.linalg.det(R))
    except np.linalg.LinAlgError:  # pragma: no cover - 极端数值问题
        return None
    if not math.isfinite(det) or abs(det) < 1e-8:
        return None
    return np.array(R, dtype=float, copy=True)


def validate(symbols: Sequence[str], coords, params: Dict[str, Any],
             lang: str = "zh", *,
             view_rotation=None) -> Tuple[Optional[str], Optional[dict]]:
    """校验 SambVca 同义参数；失败返回 ``(本地化错误文案, None)``。

    ``params['orient_mode']`` 为 ``'view'``（画布视角定向）时必须额外传入
    ``view_rotation``（world → screen 的 3×3 旋转矩阵），且不要求 z 轴原子；
    其余参数与 ``'sambvca'``（默认）完全共用同一套校验。

    成功返回 ``(None, parsed)``，``parsed`` 至少包含::

        {'job': SambVcaJob, 'sphere_radius': float, 'map_radius': float,
         'mesh': float, 'selected_atoms': list[int], 'excluded_atoms': list[int],
         'orient_mode': str, 'view_rotation': np.ndarray | None}
    """
    params = dict(params or {})
    try:
        syms = [_symbol_of(s) for s in symbols]
    except TypeError:
        syms = []
    try:
        P = np.asarray(coords, dtype=float)
    except (TypeError, ValueError):
        return _t("err_bad_coords", lang), None
    if not syms or P.ndim != 2 or P.shape[1] != 3 or P.shape[0] != len(syms):
        return _t("err_no_molecule" if not syms else "err_bad_coords", lang), None
    n = len(syms)

    try:
        delete_atoms = parse_index_spec(_index_text(params.get("delete")), n)
        centre_atoms = parse_index_spec(_index_text(params.get("centre")), n)
        z_axis_atoms = parse_index_spec(_index_text(params.get("z_axis")), n)
        xz_plane_atoms = parse_index_spec(_index_text(params.get("xz")), n)
    except ValueError as exc:
        return _t("err_index_format", lang, detail=exc), None

    # ── 定向方式（默认 sambvca，与官方逐位一致；view = 按画布视角）──
    orient_mode = _orient_mode(params)
    if orient_mode not in ORIENT_MODES:
        return _t("err_orient_mode", lang, mode=orient_mode), None
    rotation: Optional[np.ndarray] = None
    if orient_mode == "view":
        if view_rotation is None:
            return _t("err_view_rotation_missing", lang), None
        rotation = _coerce_view_rotation(view_rotation)
        if rotation is None:
            return _t("err_view_rotation_invalid", lang), None
    elif view_rotation is not None:
        # sambvca 模式忽略 view_rotation（不改变官方行为），静默接受即可
        rotation = None

    if not centre_atoms:
        return _t("err_no_centre", lang), None
    if orient_mode == "sambvca" and not z_axis_atoms:
        return _t("err_no_zaxis", lang), None

    # 半径 / 间距 / 位移 / 朝向（缺省值与官方 .inp 一致）
    try:
        sphere_radius = _to_float(_param(params, "sphere_radius", "sphere_r", default=3.5))
    except (TypeError, ValueError):
        return _t("err_sphere_format", lang), None
    if not (0.0 < sphere_radius <= 100.0):
        return _t("err_sphere_range", lang), None

    try:
        map_radius_raw = _param(params, "map_radius", "map_r", default=None)
        map_radius = sphere_radius if map_radius_raw is None else _to_float(map_radius_raw)
    except (TypeError, ValueError):
        return _t("err_map_format", lang), None
    if not (0.0 < map_radius <= 100.0):
        return _t("err_map_range", lang), None

    try:
        mesh = _to_float(_param(params, "mesh", default=0.10))
    except (TypeError, ValueError):
        return _t("err_mesh_format", lang), None
    if not (0.005 < mesh <= 1.0):
        return _t("err_mesh_range", lang), None

    try:
        displacement = _to_float(_param(params, "displacement", "disp", default=0.0))
    except (TypeError, ValueError):
        return _t("err_disp_format", lang), None
    if abs(displacement) > 20.0:
        return _t("err_disp_range", lang), None

    try:
        align_z = int(_param(params, "align_z", default=0))
    except (TypeError, ValueError):
        return _t("err_alignz_range", lang), None
    if align_z not in (0, 1):
        return _t("err_alignz_range", lang), None

    radii_set = str(_param(params, "radii_set", default="bondi-scaled") or "bondi-scaled")
    if radii_set not in RADII_SETS:
        return _t("err_radii_set", lang, values=radii_set, sets=", ".join(RADII_SETS)), None

    remove_h = _to_bool(_param(params, "remove_h", default=1), default=True)
    # 契约里的 remove_h 是"是否删除氢"（True=删）；官方 .inp 的 RemoveH 同义。
    job_remove_h = 1 if remove_h else 0

    # ── 网格规模保护（与源工程同一套上限） ──
    n_side = 2.0 * sphere_radius / mesh
    if n_side ** 3 > MAX_VOXEL_POINTS:
        suggest = 2.0 * sphere_radius / (MAX_VOXEL_POINTS ** (1.0 / 3.0))
        return _t("err_grid_too_dense", lang, r=sphere_radius, mesh=mesh,
                  n=n_side ** 3, gb=n_side ** 3 * 60.0 / 1024 ** 3,
                  suggest=suggest), None
    n_map = 2.0 * map_radius / mesh
    if n_map ** 2 > MAX_MAP_POINTS:
        suggest_map = 2.0 * map_radius / (MAX_MAP_POINTS ** 0.5)
        return _t("err_map_too_dense", lang, m=map_radius, mesh=mesh,
                  n=n_map ** 2, suggest=suggest_map), None

    # 轴向量退化会让 orient 抛 ValueError；这里提前给出可本地化的错误。
    # （view 模式不使用 z 轴，跳过这项检查。）
    if orient_mode == "sambvca":
        try:
            centre = P[[i - 1 for i in centre_atoms]].mean(axis=0)
            z_vec = P[[i - 1 for i in z_axis_atoms]].mean(axis=0) - centre
        except IndexError:  # pragma: no cover - parse_index_spec 已做范围检查
            return _t("err_index_format", lang, detail="index out of range"), None
        if float(np.linalg.norm(z_vec)) < 1e-8:
            return _t("err_zaxis_degenerate", lang), None

    job = SambVcaJob(
        delete_atoms=delete_atoms,
        centre_atoms=centre_atoms,
        z_axis_atoms=z_axis_atoms,
        xz_plane_atoms=xz_plane_atoms,
        sphere_radius=sphere_radius,
        displacement=displacement,
        mesh=mesh,
        remove_h=job_remove_h,
        align_z=align_z,
        write_surfaces=1,
        radii_set=radii_set,
        map_radius=map_radius,
    )
    keep, excluded = select_atoms(syms, job)
    if not keep:
        return _t("err_no_atoms_selected", lang), None

    return None, {
        "job": job,
        "sphere_radius": sphere_radius,
        "map_radius": map_radius,
        "mesh": mesh,
        "selected_atoms": [i + 1 for i in keep],
        "excluded_atoms": list(excluded),
        "orient_mode": orient_mode,
        "view_rotation": rotation,
    }


# ══════════════════════════════════════════════════════════════════
#  定向诊断
# ══════════════════════════════════════════════════════════════════
def _orientation_dict(info) -> Dict[str, Any]:
    """OrientationInfo → JSON 安全 dict（warning/note 用 [code, params] 列表）。"""
    centre = np.asarray(info.centre, dtype=float)
    return {
        "centre": [float(v) for v in centre],
        "axis_vector": [float(v) for v in np.asarray(info.axis_vector, dtype=float)],
        "axis_length": float(info.axis_length),
        "axis_consistency": float(info.axis_consistency),
        "xz_vector": [float(v) for v in np.asarray(info.xz_vector, dtype=float)],
        "xz_length": float(info.xz_length),
        "angle_axis_xz_deg": float(info.angle_axis_xz_deg),
        "roll_deg": float(info.roll_deg),
        "xz_projection": float(info.xz_projection),
        "xz_projection_fraction": float(info.xz_projection_fraction),
        "displacement_shift": float(info.displacement_shift),
        "rotation_matrix": [[float(x) for x in row]
                            for row in np.asarray(info.rotation_matrix, dtype=float)],
        "warnings": [[code, dict(prm)] for code, prm in info.warnings],
        "notes": [[code, dict(prm)] for code, prm in info.notes],
    }


def _format_view_report(result: "StericResult", o: Dict[str, Any], lang: str) -> str:
    """``format_orientation_report`` 的 view 模式分支（画布视角定向）。"""
    lines: List[str] = [_t("rep_title_view", lang)]
    try:
        tilt = float(o.get("view_tilt_deg", float("nan")))
    except (TypeError, ValueError):
        tilt = float("nan")
    lines.append(_t("rep_mode_view", lang, tilt=tilt))

    centre = o.get("centre") or [0.0, 0.0, 0.0]
    try:
        cx, cy, cz = (float(centre[0]), float(centre[1]), float(centre[2]))
        lines.append(_t("rep_centre", lang, x=cx, y=cy, z=cz))
    except (TypeError, ValueError, IndexError):
        pass

    rows = o.get("rotation_matrix")
    if rows is not None:
        try:
            R = np.asarray(rows, dtype=float)
            if R.shape == (3, 3):
                text = "[" + ", ".join(
                    "[" + ", ".join(f"{float(v):+.3f}" for v in row) + "]"
                    for row in R) + "]"
                lines.append(_t("rep_view_rotation", lang, rows=text))
        except (TypeError, ValueError):
            pass

    warnings = list(getattr(result, "warnings", None) or [])
    if not warnings:
        warnings = [(item[0], item[1]) for item in (o.get("warnings") or [])
                    if isinstance(item, (list, tuple)) and len(item) == 2]
    if warnings:
        lines.append(_t("rep_warn", lang))
        lines.extend("  ⚠ " + format_diag(item, None, lang) for item in warnings)
    else:
        lines.append(_t("rep_warn", lang) + " " + _t("rep_none", lang))

    notes = [(item[0], item[1]) for item in (o.get("notes") or [])
             if isinstance(item, (list, tuple)) and len(item) == 2]
    if notes:
        lines.append(_t("rep_note", lang))
        for code, params in notes:
            if str(code) == "orient_view":
                text = _t("note_orient_view", lang)
            else:
                text = format_diag((code, params), None, lang)
            lines.append("  · " + text)
    return "\n".join(lines)


def format_orientation_report(result: StericResult, lang: str = "zh") -> str:
    """把 ``result.orientation`` 与定向自检项格式化成多行诊断文本。

    自适应定向方式：``'sambvca'`` 走官方三步刚体变换的诊断；``'view'`` 输出
    “定向方式：画布视角，视图倾角 x°，忽略 z 轴/xz 原子”。
    """
    o = dict(getattr(result, "orientation", None) or {})
    mode = str(o.get("mode") or getattr(result, "orient_mode", DEFAULT_ORIENT_MODE)
               or "").strip().lower()
    if mode == "view":
        return _format_view_report(result, o, lang)

    lines: List[str] = [_t("rep_title", lang)]
    centre = o.get("centre") or [0.0, 0.0, 0.0]
    try:
        cx, cy, cz = (float(centre[0]), float(centre[1]), float(centre[2]))
        lines.append(_t("rep_centre", lang, x=cx, y=cy, z=cz))
    except (TypeError, ValueError, IndexError):
        pass
    try:
        lines.append(_t("rep_axis", lang,
                        len=float(o.get("axis_length", float("nan"))),
                        cons=float(o.get("axis_consistency", float("nan"))),
                        angle=float(o.get("angle_axis_xz_deg", float("nan")))))
    except (TypeError, ValueError):
        pass
    try:
        lines.append(_t("rep_roll", lang,
                        roll=float(o.get("roll_deg", float("nan"))),
                        frac=float(o.get("xz_projection_fraction", float("nan")))))
    except (TypeError, ValueError):
        pass
    try:
        shift = float(o.get("displacement_shift", 0.0))
        target = _t("rep_target_neg" if shift <= 0 else "rep_target_pos", lang)
        lines.append(_t("rep_disp", lang, shift=shift, target=target))
    except (TypeError, ValueError):
        pass

    warnings = list(getattr(result, "warnings", None) or [])
    orientation_warns = o.get("warnings") or []
    if not warnings:
        warnings = [(item[0], item[1]) for item in orientation_warns
                    if isinstance(item, (list, tuple)) and len(item) == 2]
    if warnings:
        lines.append(_t("rep_warn", lang))
        lines.extend("  ⚠ " + format_diag(item, None, lang) for item in warnings)
    else:
        lines.append(_t("rep_warn", lang) + " " + _t("rep_none", lang))

    notes = [(item[0], item[1]) for item in (o.get("notes") or [])
             if isinstance(item, (list, tuple)) and len(item) == 2]
    if notes:
        lines.append(_t("rep_note", lang))
        lines.extend("  · " + format_diag(item, None, lang) for item in notes)
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
#  主计算入口
# ══════════════════════════════════════════════════════════════════
def compute(symbols: Sequence[str], coords, params: Dict[str, Any], *,
            engine: str = DEFAULT_ENGINE, lang: str = "zh",
            on_log: Optional[Callable[[str], None]] = None,
            on_progress: Optional[Callable[[str, str], None]] = None,
            should_cancel: Optional[Callable[[], bool]] = None,
            view_rotation=None) -> StericResult:
    """按 SambVca 参数计算 %VBur 与位阻地图。

    参数
    ----
    symbols, coords : 原子符号列表与 (n,3) 坐标（Å，任意取向，内部定向）。
    params : 冻结契约字典（1-based 字符串序号 + 数值参数），见 task-1。
        可选键 ``orient_mode``：``"sambvca"``（默认，与官方逐位一致）或
        ``"view"``（按画布视角定向）。
    engine : ``"native"``（默认，必须永远可用）或 ``"stericrender"``。
    lang : ``"zh"`` / ``"en"``，控制错误与日志文案。
    on_log(text) / on_progress(step, text) : 可选进度回调；step 依次为
        ``orient / select / volume / map / done``。
    should_cancel() : 可选取消钩子，返回真时抛 :class:`StericCancelled`。
    view_rotation : 仅 ``params['orient_mode'] == 'view'`` 时需要 ——
        world → screen 的 3×3 旋转矩阵（+z 指向观察者；面板用
        ``surface_projection.camera_rotation(glw)`` 取得）。定向为
        ``oriented = (positions - centre) @ R.T``，跳过官方三步刚体变换，
        忽略 z 轴 / xz 原子（不报错）。

    校验失败抛 :class:`StericError`（本地化消息）。
    """
    t_start = time.perf_counter()
    log: List[Tuple[str, str]] = []

    def emit(text: str, color: str = "#888") -> None:
        log.append((text, color))
        if on_log is not None:
            try:
                on_log(text)
            except Exception:  # noqa: BLE001 - GUI 回调异常不影响计算
                pass

    def progress(step: str, text: str) -> None:
        if on_progress is not None:
            try:
                on_progress(step, text)
            except Exception:  # noqa: BLE001
                pass

    def check_cancel() -> None:
        if should_cancel is None:
            return
        try:
            cancelled = bool(should_cancel())
        except Exception:  # noqa: BLE001 - 取消钩子异常按"未取消"处理
            cancelled = False
        if cancelled:
            raise StericCancelled(_t("err_cancelled", lang))

    # ① 校验（与面板 validate() 共用同一实现）
    err, parsed = validate(symbols, coords, params, lang=lang,
                           view_rotation=view_rotation)
    if err is not None or parsed is None:
        raise StericError(err or _t("err_compute", lang, detail="invalid parameters"))
    job: SambVcaJob = parsed["job"]
    sphere_radius = float(parsed["sphere_radius"])
    map_radius = float(parsed["map_radius"])
    mesh = float(parsed["mesh"])
    orient_mode = str(parsed.get("orient_mode") or DEFAULT_ORIENT_MODE)

    # ② 引擎解析（engine 是参数，不是全局状态）
    requested = str(engine or DEFAULT_ENGINE).strip().lower()
    if requested not in ENGINES:
        raise StericError(_t("err_engine_unknown", lang, engine=engine,
                             engines=", ".join(available_engines())))
    actual_engine = requested
    if actual_engine == "stericrender" and _stericrender_modules() is None:
        emit(_t("log_engine_fallback", lang, engine="stericrender"), "#e67e22")
        actual_engine = "native"
    emit(_t("log_engine_native" if actual_engine == "native"
            else "log_engine_stericrender", lang), "#1565C0")

    check_cancel()
    progress("orient", _t("step_orient", lang))
    positions = np.array(coords, dtype=float)
    syms = [_symbol_of(s) for s in symbols]
    warnings: List[Tuple[str, dict]] = []
    if orient_mode == "view":
        # 画布视角定向：只做球心平移 + 世界→屏幕旋转；官方三步刚体变换跳过。
        R = np.asarray(parsed["view_rotation"], dtype=float)
        centre = positions[[i - 1 for i in job.centre_atoms]].mean(axis=0)
        oriented = (positions - centre) @ R.T
        view_tilt = math.degrees(math.acos(
            max(-1.0, min(1.0, float(R[2, 2])))))
        orientation: Dict[str, Any] = {
            "mode": "view",
            "rotation_matrix": [[float(v) for v in row] for row in R],
            "view_tilt_deg": float(view_tilt),
            "centre": [float(v) for v in centre],
            "warnings": [],
            "notes": [["orient_view", {}]],
        }
        emit(_t("log_orient_view", lang, tilt=view_tilt), "#888")
    else:
        try:
            oriented, info = orient_sambvca(positions, job)
        except ValueError as exc:
            raise StericError(_t("err_orient", lang, detail=exc)) from exc
        for item in info.warnings:
            emit(_t("log_warn", lang, text=format_diag(item, None, lang)), "#e67e22")
        for item in info.notes:
            emit(_t("log_note", lang, text=format_diag(item, None, lang)), "#888")
        warnings = list(info.warnings)
        orientation = _orientation_dict(info)
        orientation["mode"] = "sambvca"

    check_cancel()
    # ③ 选原子（删除表 → RemoveH）
    progress("select", _t("step_select", lang))
    keep, excluded = select_atoms(syms, job)
    if not keep:
        raise StericError(_t("err_no_atoms_selected", lang))
    selected_symbols = [syms[i] for i in keep]
    selected_radii, missing = radii_for_symbols(selected_symbols, job.radii_set)
    if missing:
        emit(_t("log_radii_missing", lang, syms=", ".join(sorted(missing))), "#e67e22")
    selected_positions = oriented[keep]
    emit(_t("log_params", lang, r=sphere_radius, m=map_radius, mesh=mesh), "#888")
    emit(_t("log_n_atoms", lang, n=len(selected_symbols)), "#888")
    excluded_text = ",".join(str(i) for i in excluded[:20]) + ("…" if len(excluded) > 20 else "")
    emit(_t("log_excluded", lang, ids=excluded_text or _t("log_none", lang)), "#888")

    # ④ 埋藏体积
    check_cancel()
    progress("volume", _t("step_volume", lang))
    emit(_t("log_volume_start", lang), "#4ec9b0")
    t_vol0 = time.perf_counter()
    try:
        if actual_engine == "native":
            vol = _native_volume(selected_positions, selected_radii, sphere_radius, mesh)
        else:  # pragma: no cover - 需安装 stericrender
            vol = _stericrender_volume(selected_positions, selected_radii,
                                       sphere_radius, mesh)
    except StericError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise StericError(_t("err_compute", lang, detail=exc)) from exc
    elapsed_volume = time.perf_counter() - t_vol0
    check_cancel()

    # ⑤ 位阻地图（官方 TopSurface；空列哨兵 → NaN）
    progress("map", _t("step_map", lang))
    emit(_t("log_map_start", lang), "#4ec9b0")
    t_map0 = time.perf_counter()
    try:
        if actual_engine == "native":
            grid = _native_map(selected_positions, selected_radii, map_radius, mesh)
        else:  # pragma: no cover - 需安装 stericrender
            grid = _stericrender_map(selected_positions, selected_radii, map_radius, mesh)
    except StericError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise StericError(_t("err_compute", lang, detail=exc)) from exc
    elapsed_map = time.perf_counter() - t_map0
    check_cancel()

    finite = grid.z[np.isfinite(grid.z)]
    if finite.size:
        color_range = (float(finite.min()), float(finite.max()))
    else:  # 极端情况：没有表面，给一个对称的默认色标
        color_range = (-float(map_radius), float(map_radius))

    emit(_t("log_volume_done", lang, pct=vol["percent_buried"],
            v=vol["buried_volume"], t=elapsed_volume), "#888")
    emit(_t("log_map_done", lang, nz=int(finite.size), t=elapsed_map), "#888")
    elapsed_total = time.perf_counter() - t_start
    emit(_t("log_done", lang, pct=vol["percent_buried"], t=elapsed_total), "#4ec9b0")
    progress("done", _t("step_done", lang))

    job_dict = job.to_dict()
    job_dict["orient_mode"] = orient_mode      # JSON 导出的定向方式记录

    return StericResult(
        symbols=list(syms),
        positions=positions,
        oriented_positions=np.asarray(oriented, dtype=float),
        map=grid,
        percent_buried=float(vol["percent_buried"]),
        buried_volume=float(vol["buried_volume"]),
        free_volume=float(vol["free_volume"]),
        sphere_volume=float(vol["sphere_volume"]),
        quadrant_percent={k: float(v) for k, v in vol["quadrant_percent"].items()},
        octant_percent={k: float(v) for k, v in vol["octant_percent"].items()},
        selected_atoms=[i + 1 for i in keep],
        excluded_atoms=list(excluded),
        job=job_dict,
        engine=actual_engine,
        radii_set=job.radii_set,
        include_h=not bool(job.remove_h),
        sphere_radius=sphere_radius,
        map_radius=map_radius,
        mesh=mesh,
        orientation=orientation,
        warnings=warnings,
        log=log,
        elapsed={"volume": float(elapsed_volume), "map": float(elapsed_map),
                 "total": float(elapsed_total)},
        color_range=color_range,
        orient_mode=orient_mode,
    )
