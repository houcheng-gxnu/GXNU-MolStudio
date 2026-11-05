# -*- coding: utf-8 -*-
# Ported from StericMapAnalyzer (GPLv3) — SambVca 2.1 official algorithm replica.
# 来源：StericMapAnalyzer v3.5（同作者仓库，GPL-3.0-only）的 export.py / map_annotate.py
# 中的元数据结构。MolStudio 移植版只保留纯计算侧的 JSON / CSV / XYZ 导出，
# 不依赖 GUI、matplotlib 或 stericrender。
# License: GPL-3.0-only (inherited from StericMapAnalyzer).
"""StericResult 的纯数据导出（JSON / 地图 CSV / 定向 XYZ）。

* :func:`result_to_json` —— 可复现性元数据（SambVca 参数、定向诊断、%VBur 等）。
* :func:`save_json` —— 写出 ``result_to_json(result)``。
* :func:`save_grid_csv` —— 位阻地图长表 ``x,y,z``（无表面处写 ``nan``）。
* :func:`save_oriented_xyz` —— 定向后的标准 XYZ。

所有 ``save_*`` 的签名是 ``(result, path)``，返回 ``pathlib.Path``；为容错也接受
颠倒的 ``(path, result)`` 顺序（内部按类型识别）。
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np

__all__ = ["result_to_json", "save_json", "save_grid_csv", "save_oriented_xyz"]


def _json_safe(value):
    """把 numpy 标量/数组、NaN/inf、元组等转成标准 JSON 可序列化对象。"""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, np.ndarray):
        return _json_safe(value.tolist())
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Path):
        return str(value)
    return value


def result_to_json(result, include_map: bool = False) -> dict:
    """把 :class:`StericResult` 转成 dict（JSON 安全，NaN/inf → None）。

    ``include_map=True`` 时附带完整地图网格（``map.x/y/z``，无表面格为 None）；
    默认不附带，避免大半径/细网格时 JSON 体积失控（需要网格请用 CSV）。
    """
    data = {
        "percent_buried": result.percent_buried,
        "buried_volume": result.buried_volume,
        "free_volume": result.free_volume,
        "sphere_volume": result.sphere_volume,
        "quadrant_percent": dict(result.quadrant_percent),
        "octant_percent": dict(result.octant_percent),
        "sphere_radius": result.sphere_radius,
        "map_radius": result.map_radius,
        "mesh": result.mesh,
        "color_range": list(result.color_range),
        "engine": result.engine,
        "radii_set": result.radii_set,
        "include_h": result.include_h,
        "n_atoms": len(result.symbols),
        "selected_atoms": list(result.selected_atoms),
        "excluded_atoms": list(result.excluded_atoms),
        "map_shape": [int(result.map.z.shape[0]), int(result.map.z.shape[1])],
        "sambvca_job": result.job,
        "orientation": result.orientation,
        "warnings": [[code, params] for code, params in result.warnings],
        "elapsed": dict(result.elapsed),
    }
    if include_map:
        data["map"] = {
            "x": np.asarray(result.map.x, dtype=float),
            "y": np.asarray(result.map.y, dtype=float),
            "z": np.asarray(result.map.z, dtype=float),
        }
    return _json_safe(data)


def _resolve(result, path):
    """兼容 ``(result, path)`` 与颠倒的 ``(path, result)``。"""
    if isinstance(result, (str, os.PathLike)) and path is not None \
            and not isinstance(path, (str, os.PathLike)):
        result, path = path, result
    if path is None:
        raise TypeError("save_*() 需要 (result, path) 两个参数")
    return result, Path(path)


def save_json(result, path) -> Path:
    """写出完整 JSON（``result_to_json``）；返回写出的路径。"""
    result, p = _resolve(result, path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(result_to_json(result), indent=2, ensure_ascii=False,
                            allow_nan=False) + "\n", encoding="utf-8")
    return p


def save_grid_csv(result, path) -> Path:
    """写出位阻地图长表 CSV：表头 ``x,y,z``，无表面格写 ``nan``。

    纯 numpy 向量化 + ``np.savetxt``：地图上限 2e7 格时，逐格 Python 循环会
    让界面卡十几秒；这样输出同样内容但快两个数量级。
    """
    result, p = _resolve(result, path)
    grid = result.map
    xs = np.asarray(grid.x, dtype=float)
    ys = np.asarray(grid.y, dtype=float)
    zs = np.asarray(grid.z, dtype=float)
    p.parent.mkdir(parents=True, exist_ok=True)
    # 行序与旧版一致：外层 y、内层 x（x 变化最快），zs.reshape(-1) 正是 C 序
    xg = np.tile(xs, ys.size)
    yg = np.repeat(ys, xs.size)
    zg = zs.reshape(-1)
    data = np.column_stack([xg, yg, zg])
    np.savetxt(p, data, fmt="%.6f", delimiter=",", header="x,y,z", comments="")
    return p


def save_oriented_xyz(result, path) -> Path:
    """写出定向后的标准 XYZ；返回写出的路径。"""
    result, p = _resolve(result, path)
    P = np.asarray(result.oriented_positions, dtype=float)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        str(len(result.symbols)),
        (f"StericMapAnalyzer oriented | engine={result.engine} "
         f"| %VBur={result.percent_buried:.4f} | R={result.sphere_radius:g} "
         f"mesh={result.mesh:g}"),
    ]
    for sym, (x, y, z) in zip(result.symbols, P):
        lines.append(f"{str(sym):<4}{x:16.10f}{y:16.10f}{z:16.10f}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p
