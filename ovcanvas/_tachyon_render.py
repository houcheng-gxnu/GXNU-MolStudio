# -*- coding: utf-8 -*-
"""
ovcanvas/_tachyon_render.py — 画布场景 → Tachyon 离线光线追踪渲染

把 OpenGL 画布当前场景（原子球 / 化学键 / 等值面）转成 Tachyon 场景
文件 (.dat)，调用 tachyon.exe 渲染出 PNG。不依赖 VMD。

Tachyon 0.99 关键语法（实测验证）：
  * 场景文件必须 LF 行尾（CRLF 解析失败）
  * 相机用关键字多行格式：Camera ... End_Camera（支持 Projection ORTHOGRAPHIC）
  * 对象用关键字格式 + TEXTURE AMBIENT/DIFFUSE/SPECULAR/OPACITY/COLOR/TEXFUNC
  * 正交相机标定：Zoom=1.0 ↔ 画面高度 4.2334 世界单位（本机 tachyon_WIN32.exe）
"""

import os
import subprocess
import tempfile
import shutil

import numpy as np

from ._glwidget import (
    _q2m, _atom_base_radius, _IBO_ELEMENT_COLORS, _COVALENT_RADII_BOHR,
    ATOM_DRAW_SCALE, BOND_DRAW_SCALE, BOND_RADIUS_FACTOR,
    BOND_MAX_DIST_ANG, BOND_MAX_DIST_H_ANG,
)

# 正交相机标定值：Zoom=1.0 时画面显示的世界高度（单位同场景坐标，Bohr）
_TACH_ZOOM_CAL = 4.2334

# 大等值面抽稀阈值（三角形数超过后隔 N 取 1，避免 .dat 过大/渲染过慢）
_SURF_MAX_TRI = 400000


def _tex(amb, dif, spe, op, rgb):
    """Tachyon 内联纹理行。rgb: (r,g,b) 0..1。"""
    r, g, b = (max(0.0, min(1.0, float(c))) for c in rgb)
    return ("TEXTURE AMBIENT {a} DIFFUSE {d} SPECULAR {s} OPACITY {o} "
            "COLOR {r} {g} {b} TEXFUNC 0").format(
        a=amb, d=dif, s=spe, o=op, r=r, g=g, b=b)


def _normalize(v):
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else np.array([0.0, 0.0, 1.0])


def glw_scene_to_dat(glw, out_w, out_h):
    """把画布场景转成 Tachyon .dat 文本。

    Args:
        glw: CubGLWidget 实例
        out_w, out_h: 输出分辨率
    Returns:
        str: Tachyon 场景文本（LF 行尾）
    """
    L = []
    L.append("Begin_Scene")
    L.append("Resolution %d %d" % (int(out_w), int(out_h)))

    # ── 相机：画布正交投影（IboView 风格） ──
    R = np.asarray(_q2m(glw.cam.q), dtype=np.float64)
    viewdir = _normalize(-R[2, :].copy())   # 观察方向（世界系）
    updir = _normalize(R[1, :].copy())      # 图像上方（世界系）
    ctr = np.asarray(glw.cam.ctr, dtype=np.float64)
    hh = float(glw.cam.half_height())
    zoom = _TACH_ZOOM_CAL / max(2.0 * hh, 1e-6)
    aspect = float(out_w) / max(float(out_h), 1.0)
    cen = ctr - 80.0 * viewdir   # 相机在场景沿 -Viewdir 的远处
    L += ["Camera", "Projection ORTHOGRAPHIC", "Zoom %.6f" % zoom,
          "Aspectratio %.6f" % aspect, "Antialiasing 32", "Raydepth 8",
          "Center %.4f %.4f %.4f" % tuple(cen),
          "Viewdir %.6f %.6f %.6f" % tuple(viewdir),
          "Updir %.6f %.6f %.6f" % tuple(updir),
          "End_Camera"]

    # ── 光源：画布视图空间方向 → 世界系（方向光） ──
    ld = (getattr(glw, "_light_dirs", None)
          or getattr(glw, "_light_default_dirs", None)
          or [(0.5, 0.5, 0.70710678), (-0.4330127, -0.25, 0.8660254),
              (0.4330127, -0.25, 0.8660254), (0.0, 0.0, 1.0)])
    n_lights = int(getattr(glw, "_light_count", 3))
    for i in range(max(1, min(n_lights, 4))):
        d = np.asarray(ld[i] if i < len(ld) else (0.0, 0.0, 1.0),
                       dtype=np.float64)
        wdir = _normalize(R.T @ d)
        L.append("DIRECTIONAL_LIGHT DIRECTION %.6f %.6f %.6f COLOR 1.0 1.0 1.0"
                 % tuple(wdir))

    # ── 原子 + 键 ──
    if getattr(glw, "_molecule", None):
        atoms = glw._molecule
    elif glw._cube is not None and getattr(glw._cube, "atoms", None):
        atoms = glw._cube.atoms
    else:
        atoms = None

    if atoms:
        anums = [int(a[0]) for a in atoms]
        coords = np.array([[float(a[2]), float(a[3]), float(a[4])]
                           for a in atoms], dtype=np.float64)
        n = len(anums)
        atom_scale = float(getattr(glw, "_atom_scale", 1.0))
        bond_scale = float(getattr(glw, "_bond_scale", 2.0))
        elem_ov = getattr(glw, "_element_color_overrides", None) or {}
        idx_ov = getattr(glw, "_atom_color_overrides", None) or {}
        at_mat = (0.30, 0.70, 0.30, 1.0)   # ambient/diffuse/specular/opacity

        # 原子球
        for k in range(n):
            anum = anums[k]
            if not glw._hydrogen_visible(k + 1, anum):
                continue
            if (k + 1) in idx_ov:
                col = tuple(float(c) for c in idx_ov[k + 1][:3])
            elif anum in elem_ov:
                col = tuple(float(c) for c in elem_ov[anum][:3])
            else:
                try:
                    col = tuple(float(c) for c in _IBO_ELEMENT_COLORS[anum])
                except (IndexError, TypeError):
                    col = (0.55, 0.55, 0.55)
            r = _atom_base_radius(anum) * ATOM_DRAW_SCALE * atom_scale
            cx, cy, cz = coords[k]
            L.append("SPHERE CENTER %.4f %.4f %.4f RAD %.4f %s"
                     % (cx, cy, cz, r, _tex(*at_mat, col)))

        # 化学键：IboView 几何启发式（同 _gen_atoms），半色键（两端元素色）
        bf_tight = float(getattr(glw, "_bond_rf_tight", BOND_RADIUS_FACTOR))
        bf_loose = float(getattr(glw, "_bond_rf_loose", BOND_RADIUS_FACTOR))
        bond_r = max(BOND_DRAW_SCALE * 0.4 * bond_scale,
                     0.04 * bond_scale)
        bd_mat = (0.25, 0.70, 0.35, 1.0)
        for i in range(n):
            for j in range(i + 1, n):
                if not (glw._hydrogen_visible(i + 1, anums[i])
                        and glw._hydrogen_visible(j + 1, anums[j])):
                    continue
                p = coords[i]; q = coords[j]
                rij = float(np.linalg.norm(q - p))
                if rij < 1e-4:
                    continue
                zi, zj = anums[i], anums[j]
                ci = (_COVALENT_RADII_BOHR[zi]
                      if 0 <= zi < len(_COVALENT_RADII_BOHR) else 0.7)
                cj = (_COVALENT_RADII_BOHR[zj]
                      if 0 <= zj < len(_COVALENT_RADII_BOHR) else 0.7)
                cov_sum = ci + cj
                has_H = (zi == 1 or zj == 1)
                if has_H and zi == 1 and zj == 1:
                    continue
                cap = (BOND_MAX_DIST_H_ANG if has_H
                       else BOND_MAX_DIST_ANG) / 0.529177
                if not (rij <= bf_tight * cov_sum
                        or rij <= bf_loose * cov_sum or rij <= cap):
                    continue
                # 半色键：p→中点 i 色，中点→q j 色
                mid = (p + q) / 2.0
                for (a1, a2, anum) in ((p, mid, zi), (mid, q, zj)):
                    try:
                        col = tuple(float(c)
                                    for c in _IBO_ELEMENT_COLORS[anum])
                    except (IndexError, TypeError):
                        col = (0.55, 0.55, 0.55)
                    v = a2 - a1
                    L.append("CYLINDER CENTER %.4f %.4f %.4f "
                             "AXIS %.4f %.4f %.4f RAD %.4f %s"
                             % (a1[0], a1[1], a1[2],
                                v[0], v[1], v[2], bond_r,
                                _tex(*bd_mat, col)))

    # ── 等值面（正/负，STRI 光滑三角带法线） ──
    sp = getattr(glw, "_sp", None) or {}
    surf_op = max(0.05, min(1.0, float(sp.get("opacity", 0.85))))
    surf_vcolor = bool(getattr(glw, "_surf_vcolor", False))
    pc = tuple(float(c) for c in getattr(glw, "_pc", (0.1, 0.8, 0.1)))
    nc = tuple(float(c) for c in getattr(glw, "_nc", (0.9, 0.25, 0.25)))
    surf_mat = (0.15, 0.80, 0.25, surf_op)
    for surf, is_neg in ((getattr(glw, "_pos_surf", None), False),
                         (getattr(glw, "_neg_surf", None), True)):
        if surf is None or getattr(surf, "vertices", None) is None:
            continue
        verts = np.asarray(surf.vertices, dtype=np.float64)
        norms = np.asarray(surf.normals, dtype=np.float64)
        idx = np.asarray(surf.indices, dtype=np.int64).reshape(-1, 3)
        colors = getattr(surf, "colors", None)
        if colors is not None:
            colors = np.asarray(colors, dtype=np.float64)
        # 抽稀：超大网格隔 N 取 1
        if len(idx) > _SURF_MAX_TRI:
            stride = int(np.ceil(len(idx) / float(_SURF_MAX_TRI)))
            idx = idx[::stride]
        for (a, b, c) in idx:
            v0 = verts[a]; v1 = verts[b]; v2 = verts[c]
            n0 = norms[a]; n1 = norms[b]; n2 = norms[c]
            if surf_vcolor and colors is not None and colors.shape[0] > max(a, b, c):
                rgb = colors[[a, b, c], :3].mean(axis=0)
            else:
                rgb = nc if is_neg else pc
            rgb = tuple(float(x) for x in rgb[:3])
            L.append("STRI V0 %.4f %.4f %.4f V1 %.4f %.4f %.4f V2 %.4f %.4f %.4f "
                     "N0 %.4f %.4f %.4f N1 %.4f %.4f %.4f N2 %.4f %.4f %.4f %s"
                     % (v0[0], v0[1], v0[2], v1[0], v1[1], v1[2],
                        v2[0], v2[1], v2[2],
                        n0[0], n0[1], n0[2], n1[0], n1[1], n1[2],
                        n2[0], n2[1], n2[2], _tex(*surf_mat, rgb)))

    L.append("End_Scene")
    return "\n".join(L) + "\n"


def render_glw_to_png(glw, tachyon_exe, output_png=None, resolution=(2000, 1500),
                      threads=8, aasamples=24, log=None):
    """把画布场景渲染为 PNG（后台线程调用）。

    Args:
        glw: CubGLWidget 实例
        tachyon_exe: tachyon 可执行文件路径
        output_png: 输出 PNG 路径（None 时输出到系统临时目录）
        resolution: (宽, 高)
        threads: Tachyon 渲染线程数
        aasamples: 抗锯齿采样数
        log: 可选日志回调 log(str)
    Returns:
        str|None: PNG 路径
    """
    def _log(msg):
        if log:
            try:
                log(msg)
            except Exception:
                pass

    if not tachyon_exe or not os.path.isfile(tachyon_exe):
        _log("Tachyon 可执行文件不存在: %s" % tachyon_exe)
        return None

    tmp = tempfile.mkdtemp(prefix="tach_")
    try:
        if output_png is None:
            output_png = os.path.join(
                tempfile.gettempdir(),
                "molstudio_tachyon_%d.png" % os.getpid())
        dat = glw_scene_to_dat(glw, *resolution)
        with open(os.path.join(tmp, "scene.dat"), "w", newline="\n",
                  encoding="ascii") as f:
            f.write(dat)
        _log("Tachyon 场景生成完毕（%.1f KB），开始光线追踪渲染…"
             % (len(dat) / 1024.0))
        args = [tachyon_exe, "scene.dat",
                "-format", "TARGA", "-o", "out.tga",
                "-res", str(int(resolution[0])), str(int(resolution[1])),
                "-numthreads", str(int(threads)),
                "-aasamples", str(int(aasamples)), "-fullshade"]
        result = subprocess.run(args, cwd=tmp, capture_output=True,
                                timeout=900, encoding="utf-8", errors="replace")
        tga = os.path.join(tmp, "out.tga")
        if not os.path.exists(tga) or result.returncode != 0:
            _log("Tachyon 渲染失败: %s" % ((result.stdout or result.stderr
                                            or "")[:400]))
            return None
        from PIL import Image
        img = Image.open(tga)
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        img.save(output_png, "PNG")
        _log("Tachyon 渲染完成 → %s" % os.path.basename(output_png))
        return output_png
    except subprocess.TimeoutExpired:
        _log("Tachyon 渲染超时")
        return None
    except Exception as e:
        _log("Tachyon 渲染异常: %s" % e)
        return None
    finally:
        try:
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass
