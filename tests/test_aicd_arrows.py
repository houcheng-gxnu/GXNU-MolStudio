# -*- coding: utf-8 -*-
"""AICD 箭头贴面几何：起点必须在等值面外侧，方向必须保持 J。

画布（OpenGL）和 matplotlib 效果图现在共用 ``aicd.surface_arrow_geometry``。
这里用解析球面（f = R - r）做单元测试，防止再出现「箭头一半埋在面里」或
「内指箭头方向被取反」这两类回归。
"""

import numpy as np

from molstudio.core import aicd as A
from molstudio.render.aicd_figure import _rotation_to_z


def _sphere_volume(radial=False):
    """f = 1 - r 的球面；radial=False 用绕 z 的切向电流，True 用径向电流。"""
    n = 41
    spacing = 0.1
    origin = np.array([-2.0, -2.0, -2.0])
    ax = origin[0] + spacing * np.arange(n)
    X, Y, Z = np.meshgrid(ax, ax, ax, indexing="ij")
    r = np.sqrt(X * X + Y * Y + Z * Z)
    field = 1.0 - r
    if radial:
        vectors = np.stack([X, Y, Z], axis=-1) / np.maximum(r[..., None], 1e-9)
    else:
        vectors = np.stack([-Y, X, np.zeros_like(Z)], axis=-1)
    vol = A.AICDVolume(origin, spacing, field, [], vectors=vectors)
    return vol, field


def _field_at(field, vol, points):
    idx = np.rint((np.asarray(points) - vol.origin) / vol.spacing).astype(int)
    idx = np.clip(idx, 0, np.array(field.shape) - 1)
    return field[idx[:, 0], idx[:, 1], idx[:, 2]]


def test_arrow_bases_are_outside_the_isosurface():
    vol, field = _sphere_volume(radial=False)
    geo = A.surface_arrow_geometry(
        vol, 0.0, decimate=1, magnitude_floor=0.0, mean_length=0.2,
        max_arrow=0.0, offset=0.05)
    assert geo is not None
    assert int(geo["keep"].sum()) > 50
    bases = geo["bases"]
    # 最近格点判定：箭头起点应在 f <= 0（面外）一侧
    fb = _field_at(field, vol, bases)
    assert np.mean(fb <= 1e-6) > 0.90, np.mean(fb <= 1e-6)


def test_inward_arrows_keep_the_current_direction():
    vol, field = _sphere_volume(radial=True)
    vol.vectors = -vol.vectors          # 全部指向球心（面内）
    geo = A.surface_arrow_geometry(
        vol, 0.0, decimate=1, magnitude_floor=0.0, mean_length=0.2,
        max_arrow=0.0, offset=0.05)
    assert geo is not None
    assert np.mean(geo["inward"]) > 0.90, np.mean(geo["inward"])

    bases = geo["bases"]
    direction = geo["direction"]
    # 箭头方向必须与 J（指向球心）同向，而不是被取反成向外
    radial = bases - np.array([0.0, 0.0, 0.0])
    radial /= np.maximum(np.linalg.norm(radial, axis=1), 1e-9)[:, None]
    assert np.mean(np.einsum("ij,ij->i", direction, -radial)) > 0.90

    # 内指箭头的箭尖应回到等值面附近（半个格距以内），整根箭杆在面外
    tips = bases + direction * geo["length"][:, None]
    ft = _field_at(field, vol, tips)
    assert np.median(np.abs(ft)) < 1.5 * vol.spacing


def test_rotation_maps_field_axis_to_z():
    """六视图旋转：任意 B 都要转到 +z，且是正交、det=+1 的右手旋转。"""
    for b in ((1, 0, 0), (0, 1, 0), (0, 0, 1), (-1, 0, 0),
              (0, -1, 0), (0, 0, -1)):
        R = _rotation_to_z(b)
        assert np.allclose(R @ np.asarray(b, float), [0.0, 0.0, 1.0])
        assert np.allclose(R @ R.T, np.eye(3), atol=1e-12)
        assert abs(np.linalg.det(R) - 1.0) < 1e-12
