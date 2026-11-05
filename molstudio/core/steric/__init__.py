# -*- coding: utf-8 -*-
# Ported from StericMapAnalyzer (GPLv3) — SambVca 2.1 official algorithm replica.
# 来源：StericMapAnalyzer v3.5（同作者仓库，GPL-3.0-only）。
# MolStudio 移植版：计算内核只依赖 numpy；出图模块 render.py 在函数内部惰性
# import matplotlib（import 本包本身不需要 matplotlib），二者都不 import
# PyQt5 / OpenGL。
# License: GPL-3.0-only（继承自上游工程）。
"""MolStudio 位阻计算包：SambVca 官方算法（%VBur + 位阻地图）。

典型用法::

    from molstudio.core.steric import read_inp, compute

    job, symbols, positions, title = read_inp("nhc.inp")
    result = compute(symbols, positions, {
        "centre": "22", "z_axis": "5", "xz": "1", "delete": "22",
        "sphere_radius": 3.5, "map_radius": 3.5, "mesh": 0.1,
        "remove_h": True, "align_z": 0, "displacement": 0.0,
        "radii_set": "bondi-scaled",
    })
    print(result.percent_buried, result.quadrant_percent, result.map.z.shape)

公开 API 与 task-1 冻结契约一致；计算内核逐字移植自上游 ``sambvca.py`` /
``sambvca_native.py``（官方 sambvca21.f 的 numpy 复刻）。

出图接口（``draw_map`` / ``draw_terrain_3d`` / ``colormap`` / ``PALETTES``）
在 :mod:`molstudio.core.steric.render`，对齐 StericRender / 官方 SambVca 观感
（固定 ±R 色标、sambvca 配色、黑色等高线、圆框与四象限标签）。
"""
from __future__ import annotations

from .engine import (
    DEFAULT_ENGINE,
    DEFAULT_ORIENT_MODE,
    ENGINES,
    MAX_MAP_POINTS,
    MAX_VOXEL_POINTS,
    ORIENT_MODES,
    MapGrid,
    StericCancelled,
    StericError,
    StericResult,
    auto_roles,
    available_engines,
    compute,
    format_orientation_report,
    validate,
)
from .export import result_to_json, save_grid_csv, save_json, save_oriented_xyz
from .molecule import Molecule, from_symbols_coords, parse_gaussian_log, parse_xyz
from .native import native_buried_volume, native_surfaces
from .render import (
    MAP_STYLES,
    MAP_STYLE_LABELS,
    PALETTES,
    PALETTE_LABELS,
    bonds,
    colormap,
    draw_map,
    draw_terrain_3d,
)
from .sambvca import (
    BONDI_RADII,
    BONDI_SCALED_RADII,
    RADII_SCALE,
    RADII_SETS,
    OrientationInfo,
    SambVcaJob,
    format_diag,
    orient_sambvca,
    parse_index_spec,
    radii_for_symbols,
    read_inp,
    select_atoms,
    write_inp,
)

__all__ = [
    # 分子与解析
    "Molecule", "parse_xyz", "parse_gaussian_log", "from_symbols_coords",
    # SambVca 官方参数 / 定向 / 半径 / .inp / 诊断
    "SambVcaJob", "orient_sambvca", "select_atoms", "radii_for_symbols",
    "parse_index_spec", "write_inp", "read_inp", "format_diag", "RADII_SETS",
    # 原生算法内核
    "native_buried_volume", "native_surfaces",
    # 结果模型与错误
    "StericResult", "MapGrid", "StericError", "StericCancelled",
    # 引擎入口
    "ENGINES", "DEFAULT_ENGINE", "available_engines", "auto_roles",
    "ORIENT_MODES", "DEFAULT_ORIENT_MODE",
    "validate", "compute", "format_orientation_report",
    # 出图（matplotlib；惰性依赖，import 本包不需要 matplotlib）
    "PALETTES", "PALETTE_LABELS", "MAP_STYLES", "MAP_STYLE_LABELS",
    "colormap", "bonds", "draw_map", "draw_terrain_3d",
    # 导出
    "save_json", "save_grid_csv", "save_oriented_xyz", "result_to_json",
    # 额外常量（面板/测试可用）
    "OrientationInfo", "BONDI_RADII", "BONDI_SCALED_RADII", "RADII_SCALE",
    "MAX_VOXEL_POINTS", "MAX_MAP_POINTS",
]
