"""
AICD 参考效果图渲染
====================

把 :mod:`molstudio.core.aicd` 算出的 :class:`~molstudio.core.aicd.AICDVolume`
渲染成 keinsci 论坛 thread-1270 那种经典 AICD 效果图：

* 亮黄色各向异性等值面（Lambert 着色，AICD 程序的 ``#f5e04a``）
* 贴着等值面的感应电流箭头地毯（绿杆 + 红尖锥，几何比例来自 AICD 源码）
* 球棍分子（灰碳 / 白氢）
* 垂直穿过分子平面的绿色外磁场箭头（顶视图里画成绿点 = B 指向纸面外）

matplotlib 的 mplot3d 没有真正的遮挡处理，等值面和箭头都是
:class:`~mpl_toolkits.mplot3d.art3d.Poly3DCollection`。这里用一个
``FrontCollection`` 把箭头集合强制排在最后绘制（视觉上等于"贴在等值面
外侧"），这与 AICD 官方渲染的观感一致。

用法::

    from molstudio.core import aicd
    from molstudio.render.aicd_figure import render_aicd_montage

    vol = aicd.compute_aicd("test.txt", "benzene.log",
                            with_vectors=True)
    render_aicd_montage(vol, "benzene_aicd.png")
"""

from __future__ import annotations

import os

import numpy as np
# 注意：**不要**在这里调 matplotlib.use("Agg")。本模块会被 GUI 面板导入，
# 而主界面里 asm_irc / di / energy_span 等面板在导入时把后端设成 Qt5Agg；
# 谁最后导入谁说话，全局切换后端会把别人的画布搞坏。这里只用 Figure +
# Agg 画布显式出图，完全不碰全局后端，也不导入 pyplot。
from matplotlib.backends.backend_agg import FigureCanvasAgg       # noqa: E402
from matplotlib.figure import Figure                              # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection          # noqa: E402

from molstudio.core.aicd import (BOHR, build_arrow_geometry,
                                 surface_arrow_geometry)

__all__ = ["render_aicd_montage", "build_arrow_surface", "ArrowSurface",
           "AICD_FIGURE_STYLE"]

#: AICD 程序自己的配色（AICD-smooth_isosurface.cpp / RenderMich-*.pov）
AICD_FIGURE_STYLE = {
    "surface": (0.961, 0.878, 0.290),     # 等值面 #f5e04a
    "shaft": (0.0, 1.0, 0.0),             # 箭头杆（纯绿，AICD 的 Green）
    "head": (1.0, 0.0, 0.0),              # 箭头锥头（纯红，AICD 的 Red）
    "b_field": (0.0, 0.75, 0.0),          # 磁场箭头（整体绿）
    "carbon": "#3c3c3c",
    "hydrogen": "#fafafa",
    "bond": "#222222",
}

_LIGHT = np.array([0.35, -0.50, 0.79])
_LIGHT /= np.linalg.norm(_LIGHT)

#: 排序权重：mplot3d 对集合按 do_3d_projection() 返回值 reverse 排序，
#: key 越小越后画（越靠前）。取 -1e9 让箭头永远画在等值面之上。
_FRONT_KEY = -1e9


class ArrowSurface:
    """AICD 箭头三角网格（鸭子类型，等价于 ovcanvas 的 ``IsoSurface``）。

    ``GlMesh.upload()`` 只用到 ``vertices / normals / colors / indices /
    vertex_count`` 这几项，所以这里不依赖 OpenGL 模块，注册表以外的渲染
    后端也能直接吃这份数据。
    """

    def __init__(self, vertices, normals, colors, indices, n_arrows=0):
        self.vertices = np.ascontiguousarray(vertices, dtype=np.float32)
        self.normals = np.ascontiguousarray(normals, dtype=np.float32)
        self.colors = np.ascontiguousarray(colors, dtype=np.float32)
        self.indices = np.ascontiguousarray(indices, dtype=np.uint32)
        self.vertex_count = len(self.vertices)
        self.n_arrows = int(n_arrows)

    @property
    def triangle_count(self):
        return len(self.indices) // 3


def build_arrow_surface(volume, iso, decimate=2, magnitude_floor=0.02,
                        arrow_mean_length=0.50, max_arrow=2.0, min_arrow=0.0,
                        smooth_sigma=0.0, segments=10, to_bohr=True,
                        style=None,
                        shaft_rgb=(0.0, 1.0, 0.0),
                        head_rgb=(1.0, 0.0, 0.0)):
    """把 AICD 箭头做成可直接送进 OpenGL 画布的 :class:`ArrowSurface`。

    与 :func:`render_aicd_montage` 用**同一套贴面几何**
    （:func:`molstudio.core.aicd.surface_arrow_geometry`：先投影到等值面，
    再按 J 的内/外方向把箭杆放到面外），逐顶点着色——杆绿、锥头红。
    这样画布的不透明等值面不会把切向箭头整根挡掉，疏密和效果图一致。

    Parameters
    ----------
    volume : molstudio.core.aicd.AICDVolume
        需要带 ``vectors``。
    iso : float
        等值面数值（箭头贴着这张面取）。
    decimate, magnitude_floor, arrow_mean_length, max_arrow, min_arrow
        与 :func:`render_aicd_montage` 同名参数含义一致。
    smooth_sigma : float
        与 :func:`render_aicd_montage` 同一个场平滑值；画布箭头和效果图
        必须用同一份平滑场取样，否则两边箭头数量/位置会差几个百分点。
    to_bohr : bool
        画布内部用 Bohr，默认把 Å 换算过去（``False`` 则原样返回，便于测试）。

    Returns
    -------
    ArrowSurface or None
        没有任何箭头时返回 ``None``。
    """
    vol = volume
    if smooth_sigma and smooth_sigma > 0:
        from scipy.ndimage import gaussian_filter
        field = gaussian_filter(np.asarray(volume.field, dtype=np.float64),
                                sigma=float(smooth_sigma))
        vol = type(volume)(volume.origin, volume.spacing, field, volume.atoms,
                           quantity=volume.quantity, vectors=volume.vectors)
    geo = surface_arrow_geometry(
        vol, iso, shell=0.75, decimate=decimate,
        magnitude_floor=magnitude_floor,
        mean_length=float(arrow_mean_length),
        max_arrow=float(max_arrow), min_arrow=float(min_arrow),
        segments=segments, style=style)
    if geo is None:
        return None
    shaft_faces = geo["shaft"][1]
    head_faces = geo["head"][1]
    if len(shaft_faces) == 0:
        return None
    faces = (np.vstack([shaft_faces, head_faces]) if len(head_faces)
             else shaft_faces)
    verts = np.asarray(geo["vertices"], dtype=np.float64)

    # 平滑法线：按面积加权累加面法线（未归一化的叉积即 2×面积）
    tri = verts[faces]
    face_n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    normals = np.zeros_like(verts)
    for k in range(3):
        np.add.at(normals, faces[:, k], face_n)
    length = np.linalg.norm(normals, axis=1)
    length[length == 0.0] = 1.0
    normals /= length[:, None]

    colors = np.tile(np.array([*head_rgb, 1.0], dtype=np.float64),
                     (len(verts), 1))
    colors[np.unique(shaft_faces)] = [*shaft_rgb, 1.0]   # 杆的顶点染绿

    if to_bohr:
        verts = verts / BOHR
    return ArrowSurface(verts, normals, colors, faces.ravel(),
                        n_arrows=int(geo["keep"].sum()))


class _FrontCollection(Poly3DCollection):
    """强制画在最前面的面片集合（模拟箭头贴在等值面外侧）。"""

    def do_3d_projection(self, renderer=None):
        super().do_3d_projection()
        return _FRONT_KEY


def _face_shading(tri_pts, base_rgb, ambient=0.40):
    """逐三角形 Lambert（双面）着色，返回 (n_faces, 3) 颜色表。"""
    tri_pts = np.asarray(tri_pts, dtype=np.float64)
    n = np.cross(tri_pts[:, 1] - tri_pts[:, 0], tri_pts[:, 2] - tri_pts[:, 0])
    norm = np.linalg.norm(n, axis=1)
    norm[norm == 0] = 1.0
    lam = np.abs((n / norm[:, None]) @ _LIGHT)
    f = ambient + (1.0 - ambient) * lam
    return np.clip(np.outer(f, np.asarray(base_rgb, dtype=np.float64)), 0, 1)


def _add_molecule(ax, atoms, style, lw=2.8, c_size=170, h_size=76):
    pts = np.array([[x, y, z] for _, x, y, z in atoms], dtype=np.float64)
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            if np.linalg.norm(pts[i] - pts[j]) < 1.75:
                ax.plot(*np.vstack([pts[i], pts[j]]).T, color=style["bond"],
                        lw=lw, solid_capstyle="round")
    for (z, x, y, zz) in atoms:
        ax.scatter([x], [y], [zz], s=c_size if z == 6 else h_size,
                   c=style["carbon"] if z == 6 else style["hydrogen"],
                   edgecolors="black", linewidths=0.5, depthshade=False)


def _add_mesh(ax, verts, faces, base_rgb, front=False, alpha=None, ambient=0.40):
    cls = _FrontCollection if front else Poly3DCollection
    coll = cls(verts[faces], linewidths=0, edgecolor="none")
    coll.set_facecolor(_face_shading(verts[faces], base_rgb, ambient=ambient))
    if alpha is not None:
        coll.set_alpha(alpha)
    ax.add_collection3d(coll)
    return coll


def _add_b_arrow(ax, field_axis, style, half=2.3):
    """绿色磁场箭头：沿 ``field_axis`` 穿过分子，锥头指向 **+B**（与 AICD 一致）。"""
    axis = np.asarray(field_axis, dtype=np.float64).reshape(3)
    axis /= max(np.linalg.norm(axis), 1e-12)
    bases = (-axis * (half + 0.2))[None, :]
    vecs = axis[None, :]
    geo = build_arrow_geometry(
        bases, vecs,
        style={"mean_length": 2 * half + 0.4,
               "shaft_radius": 0.014, "head_radius": 0.038, "head_length": 0.14},
        segments=14)
    sv, sf = geo["shaft"]
    hv, hf = geo["head"]
    _add_mesh(ax, sv, sf, style["b_field"], front=True)
    _add_mesh(ax, hv, hf, style["b_field"], front=True)
    ax.scatter([0], [0], [0], s=90, color=style["b_field"], depthshade=False)


def _rotation_to_z(axis):
    """把磁场方向 ``axis`` 旋到 +z 的旋转矩阵（右手、det=+1）。

    默认六视图（沿 ±x/±y/±z）是按 B=+z 设计的；不旋转的话，像薁这种
    B=+x 的体系，"top" 面板实际是侧视，π 环会被看成一根断开的竖条。
    """
    b = np.asarray(axis, dtype=np.float64).reshape(3)
    n = np.linalg.norm(b)
    if n < 1e-12:
        return np.eye(3)
    b = b / n
    z = np.array([0.0, 0.0, 1.0])
    c = float(np.dot(b, z))
    if c > 1.0 - 1e-12:
        return np.eye(3)
    if c < -1.0 + 1e-12:
        # 180° 绕 x：z→-z、y→-y
        return np.array([[1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, -1.0]])
    v = np.cross(b, z)
    s = float(np.linalg.norm(v))
    K = np.array([[0.0, -v[2], v[1]],
                  [v[2], 0.0, -v[0]],
                  [-v[1], v[0], 0.0]])
    return np.eye(3) + K + (K @ K) * ((1.0 - c) / (s * s))


def _isosurface_mesh(volume, iso, smooth_sigma):
    """提取等值面三角网格（世界坐标，Å）。"""
    try:
        import mcubes
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("AICD 等值面提取需要 PyMCubes：pip install PyMCubes") from exc
    field = np.asarray(volume.field, dtype=np.float64)
    if smooth_sigma and smooth_sigma > 0:
        from scipy.ndimage import gaussian_filter
        field = gaussian_filter(field, sigma=float(smooth_sigma))
    verts, tris = mcubes.marching_cubes(field, float(iso))
    world = np.asarray(volume.origin, dtype=np.float64) + verts * float(volume.spacing)
    return world, tris, field


#: 默认的 2×3 视图布局（参考 thread-1270 效果图的排布）
DEFAULT_VIEWS = (
    # (行, 列, kind, elev, azim)  kind: structure / structure_top / surface
    (0, 0, "structure", 0.0, -90.0),
    (0, 1, "surface", 1.0, -90.0),
    (0, 2, "surface", 90.0, -90.0),
    (1, 0, "structure_top", 88.0, -90.0),
    (1, 1, "surface", 24.0, -55.0),
    (1, 2, "surface", 90.0, -30.0),
)


def render_aicd_montage(volume, out_png, iso=0.05, field_axis=(0.0, 0.0, 1.0),
                        views=DEFAULT_VIEWS, rows=2, cols=3,
                        decimate=2, magnitude_floor=0.02,
                        arrow_mean_length=0.50, smooth_sigma=1.2,
                        max_arrow=2.0, min_arrow=0.0,
                        clip_plane=None,
                        lim=None, figsize=(16.2, 10.6), dpi=130,
                        surface_alpha=0.90, style=None, progress=None,
                        stats=None):
    """渲染参考图风格的 AICD 效果图。

    视图约定：函数内部先把整个场景旋转到 **B=+z**（``_rotation_to_z``），
    再套默认六视图；所以磁场沿 x/y 时，top 面板仍是真正的环平面，
    不会像旧版那样把 π 环看成一根侧视竖条。

    与 AICD 程序的选项对应关系（见 sobereva.com/147）：

    ====================  ==================================================
    AICD 选项             本函数参数
    ====================  ==================================================
    ``-l xxx``（默认 0.05）``iso``
    ``-p N``（格点数）     ``volume`` 的 ``spacing``（网格越密 ≈ -p 越大）
    ``-b x y z``           ``field_axis``（另外也要传给 compute_aicd）
    ``-m 4``（视角数）     ``views`` / ``rows`` / ``cols``
    ``-rot a b c``         每个 view 的 ``elev`` / ``azim``
    ``-s``（平滑等值面）   ``smooth_sigma``（高斯预平滑，机制不同、目的一致）
    ``-maxarrow length``   ``max_arrow``（归一化倍数，默认 2.0）
    ``-plane o n``         ``clip_plane``
    ``-nc``                不写 cube（本函数不产生 cube）
    ====================  ==================================================

    轨道分解（只画 π 电子 / σ 电子）不是绘图参数，要在 Gaussian 输入文件里做
    ：``IOp(10/93=2)`` + 文件末尾写轨道编号（苯的 π 轨道是 ``17 17`` /
    ``20 21``，σ 是 ``1 16`` / ``18 19``），算出来的 test.txt 再喂给
    :func:`~molstudio.core.aicd.compute_aicd`。

    Parameters
    ----------
    volume : molstudio.core.aicd.AICDVolume
        ``compute_aicd(..., with_vectors=True)`` 的返回值；没有 ``vectors``
        时只画等值面、不画箭头。
    out_png : str
        输出 PNG 路径。
    iso : float
        等值面数值（AICD 默认 0.05）。
    field_axis : tuple
        外磁场方向（与 ``compute_aicd`` 的 ``field`` 一致）。
    views : sequence
        ``(row, col, kind, elev, azim)`` 面板布局。
    rows, cols : int
        面板网格。
    decimate : int
        箭头网格抽稀步长（2 ≈ 每 0.3 Å 一支，对应参考图密度）。
    magnitude_floor : float
        丢弃 |J| 小于该值的箭头。
    arrow_mean_length : float
        平均箭头长度（Å），AICD 固定 0.626 Bohr ≈ 0.33 Å，这里默认放大到 0.5。
    max_arrow, min_arrow : float
        对应 AICD 的 ``-maxarrow`` / ``-minarrow``，按"平均箭头长度的倍数"计。
        Sobereva 建议 ``-maxarrow 2.0``：数值噪声偶尔会产生格外长的箭头
        （σ 电子图里尤其常见），超出的直接丢弃。0 表示不过滤。
    clip_plane : ((ox, oy, oz), (nx, ny, nz)), optional
        对应 AICD 的 ``-plane``：用"过 o 点、法向 n"的平面把等值面截断，
        只保留平面背向 n 的一侧（n 指向的那一半被切掉）。用来看内部结构。
    smooth_sigma : float
        等值面前对场做高斯平滑的 sigma（网格数）；AICD 输出的等值面本身就是
        平滑过的（AICD-smooth_isosurface），0 关闭。
    lim : float, optional
        坐标半宽（Å）；默认按等值面范围自适应。
    surface_alpha : float
        等值面不透明度；<1 时分子会隐隐透出来（参考图侧视即如此）。
    style : dict, optional
        覆盖 :data:`AICD_FIGURE_STYLE` 颜色。
    stats : dict, optional
        传进来就顺手填一些统计量（``n_triangles`` / ``n_arrows``），供调用方
        在界面上显示；不改返回值，老调用方不受影响。

    Returns
    -------
    str
        ``out_png`` 的绝对路径。
    """
    def report(msg):
        if progress:
            progress(msg)

    st = dict(AICD_FIGURE_STYLE)
    if style:
        st.update(style)

    report("提取等值面…")
    world, tris, field_smooth = _isosurface_mesh(volume, iso, smooth_sigma)
    tri_pts = world[tris]
    report(f"  {len(tris)} 个三角形，范围 "
           f"{np.round(world.min(0), 2)} .. {np.round(world.max(0), 2)}")
    if stats is not None:
        stats["n_triangles"] = int(len(tris))

    # -plane：用平面切掉一半等值面（含箭头），方便看内部
    if clip_plane is not None:
        origin_pt = np.asarray(clip_plane[0], dtype=np.float64).reshape(3)
        normal = np.asarray(clip_plane[1], dtype=np.float64).reshape(3)
        normal = normal / max(np.linalg.norm(normal), 1e-12)
        keep_tri = (tri_pts.mean(axis=1) - origin_pt) @ normal <= 0.0
        tri_pts = tri_pts[keep_tri]
        report(f"  -plane 截断后剩 {len(tri_pts)} 个三角形")

    geo = None
    if volume.vectors is not None:
        report("贴到等值面取箭头…")
        smooth_vol = type(volume)(volume.origin, volume.spacing, field_smooth,
                                  volume.atoms, quantity=volume.quantity,
                                  vectors=volume.vectors)
        geo = surface_arrow_geometry(
            smooth_vol, iso, shell=0.75, decimate=decimate,
            magnitude_floor=magnitude_floor,
            mean_length=float(arrow_mean_length),
            max_arrow=float(max_arrow), min_arrow=float(min_arrow),
            segments=10, clip_plane=clip_plane)
        n_arrow = int(geo["keep"].sum()) if geo is not None else 0
        report(f"  {n_arrow} 支箭头")
        if stats is not None:
            stats["n_arrows"] = n_arrow

    # 把整个场景旋到 B=+z：默认六视图（±x/±y/±z）是按这个约定排的。
    # 这样薁（B=+x）、任意方向的磁场也能在 "top" 面板看到环平面/π 骨架。
    R = _rotation_to_z(field_axis)
    if not np.allclose(R, np.eye(3)):
        world = world @ R.T
        tri_pts = tri_pts @ R.T
        if geo is not None:
            gv = geo["vertices"] @ R.T
            geo["vertices"] = gv
            geo["shaft"] = (gv, geo["shaft"][1])
            geo["head"] = (gv, geo["head"][1])
            for key in ("bases", "normals", "direction"):
                if key in geo:
                    geo[key] = geo[key] @ R.T
        atoms_plot = [(z, *(np.array([x, y, zz]) @ R.T))
                      for (z, x, y, zz) in volume.atoms]
        field_axis = (0.0, 0.0, 1.0)
    else:
        atoms_plot = list(volume.atoms)

    if lim is None:
        lim = 1.15 * float(np.abs(np.stack([world.min(0), world.max(0)])).max())

    fig = Figure(figsize=figsize, dpi=dpi)
    FigureCanvasAgg(fig)          # 离线出图用 Agg 画布，不依赖全局后端
    for row, col, kind, elev, azim in views:
        ax = fig.add_subplot(rows, cols, row * cols + col + 1, projection="3d")
        if kind in ("structure", "structure_top"):
            if kind == "structure":
                _add_b_arrow(ax, field_axis, st)
            else:
                ax.scatter([0], [0], [0], s=130, color=st["b_field"], depthshade=False)
            _add_molecule(ax, atoms_plot, st)
        else:
            _add_molecule(ax, atoms_plot, st, lw=2.2, c_size=140, h_size=60)
            _add_mesh(ax, tri_pts, np.arange(len(tri_pts)), st["surface"],
                      alpha=surface_alpha)
            if geo is not None:
                sv, sf = geo["shaft"]
                hv, hf = geo["head"]
                _add_mesh(ax, sv, sf, st["shaft"], front=True)
                _add_mesh(ax, hv, hf, st["head"], front=True)
        ax.set_xlim(-lim, lim)
        ax.set_ylim(-lim, lim)
        ax.set_zlim(-lim, lim)
        ax.set_box_aspect((1, 1, 1))
        ax.set_axis_off()
        ax.view_init(elev=elev, azim=azim)

    fig.subplots_adjust(left=0.0, right=1.0, bottom=0.0, top=1.0,
                        wspace=0.0, hspace=0.0)
    fig.savefig(out_png, facecolor="white")
    return os.path.abspath(out_png)
