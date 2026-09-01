# -*- coding: utf-8 -*-
"""
ovcanvas/_povray_render.py — 画布场景 → POV-Ray 光线追踪渲染

把 OpenGL 画布当前场景（原子球 / 化学键 / 等值面）转成 POV-Ray 场景
文件 (.pov)，调用 pvengine 渲染出 PNG。对齐画布观感（IboView Phong）：

  * 原子/键材质：ambient/diffuse/specular + phong 高光（POV-Ray 支持
    高光指数，弥补 Tachyon 0.99 的缺陷）
  * 等值面：smooth_triangle 带逐顶点法线；POV-Ray 三角形默认单面，
    半透明闭合曲面从外看只叠加正面 → 不会像 Tachyon 那样前后叠暗
  * 背景：background 直接支持（无需平面 hack）
  * 相机：orthographic 对齐画布正交投影；光源按画布强度分级
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

# 画布灯光强度分级（calc_base_color: I = 1.0, 0.6, 0.5, 0.4）
_LIGHT_INTENSITY = (1.0, 0.6, 0.5, 0.4)

# 大等值面抽稀阈值（三角形数超过后隔 N 取 1）
_SURF_MAX_TRI = 400000


def _norm(v):
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else np.array([0.0, 0.0, 1.0])


def _finish(amb, dif, spe):
    """POV-Ray finish 块（IboView Phong 映射）。"""
    return ("finish {{ ambient {a} diffuse {d} specular {s} "
            "roughness 0.05 phong {s} phong_size 60 }}").format(
        a=amb, d=dif, s=spe)


def glw_scene_to_pov(glw, out_w, out_h):
    """把画布场景转成 POV-Ray .pov 文本。"""
    L = []
    L.append("#version 3.7;")
    L.append("global_settings { assumed_gamma 1.0 }")

    # ── 相机：画布正交投影 ──
    R = np.asarray(_q2m(glw.cam.q), dtype=np.float64)
    viewdir = _norm(-R[2, :].copy())
    updir = _norm(R[1, :].copy())
    ctr = np.asarray(glw.cam.ctr, dtype=np.float64)
    hh = float(glw.cam.half_height())
    hw = hh * (float(out_w) / max(float(out_h), 1.0))
    aspect = float(out_w) / max(float(out_h), 1.0)
    # POV-Ray 正交相机：up 长度=画面高，right 长度=画面宽（⊥ up 与视线）
    loc = ctr - 80.0 * viewdir
    up_v = updir * (2.0 * hh)
    right_v = np.cross(viewdir, updir) * (2.0 * hw)
    L += ["camera {", "    orthographic",
          "    location <%f, %f, %f>" % tuple(loc),
          "    look_at  <%f, %f, %f>" % tuple(ctr),
          "    up       <%f, %f, %f>" % tuple(up_v),
          "    right    <%f, %f, %f>" % tuple(right_v),
          "}"]

    # ── 光源：画布视图空间方向 → 世界系（平行光，强度分级） ──
    ld = (getattr(glw, "_light_dirs", None)
          or getattr(glw, "_light_default_dirs", None)
          or [(0.5, 0.5, 0.70710678), (-0.4330127, -0.25, 0.8660254),
              (0.4330127, -0.25, 0.8660254), (0.0, 0.0, 1.0)])
    n_lights = int(getattr(glw, "_light_count", 3))
    for i in range(max(1, min(n_lights, 4))):
        d = np.asarray(ld[i] if i < len(ld) else (0.0, 0.0, 1.0),
                       dtype=np.float64)
        wdir = _norm(R.T @ d)
        pos = ctr + wdir * 100.0
        I = _LIGHT_INTENSITY[i] if i < len(_LIGHT_INTENSITY) else 0.4
        L.append("light_source { <%f, %f, %f> color rgb <%f, %f, %f> parallel }"
                 % (pos[0], pos[1], pos[2], I, I, I))

    # ── 背景 ──
    bg = getattr(glw, "_bg", (1.0, 1.0, 1.0, 1.0))
    L.append("background { color rgb <%f, %f, %f> }"
             % (bg[0], bg[1], bg[2]))

    # ── 材质 ──
    sp = getattr(glw, "_sp", None) or {}
    a_reg = sp.get("a_reg") or [0.8, 0.65, 0.4, -0.5]
    o_reg = sp.get("o_reg") or [0.8, 0.6, 1.0, 1.0]
    surf_op = max(0.05, min(1.0, float(sp.get("opacity", 0.85))))
    atom_amb, atom_dif, atom_spe = 0.15, float(a_reg[1]), min(float(a_reg[2]), 0.6)
    surf_amb, surf_dif, surf_spe = 0.10, float(o_reg[1]), min(float(o_reg[2]) * 0.35, 0.5)

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

        def _col(anum, k=None):
            if k is not None and (k + 1) in idx_ov:
                return tuple(float(c) for c in idx_ov[k + 1][:3])
            if anum in elem_ov:
                return tuple(float(c) for c in elem_ov[anum][:3])
            try:
                return tuple(float(c) for c in _IBO_ELEMENT_COLORS[anum])
            except (IndexError, TypeError):
                return (0.55, 0.55, 0.55)

        for k in range(n):
            anum = anums[k]
            if not glw._hydrogen_visible(k + 1, anum):
                continue
            r = _atom_base_radius(anum) * ATOM_DRAW_SCALE * atom_scale
            c = _col(anum, k)
            x, y, z = coords[k]
            L.append("sphere { <%f, %f, %f>, %f"
                     " pigment { color rgb <%f, %f, %f> } %s }"
                     % (x, y, z, r, c[0], c[1], c[2],
                        _finish(atom_amb, atom_dif, atom_spe)))

        # 化学键：IboView 几何启发式，半色键
        bf_tight = float(getattr(glw, "_bond_rf_tight", BOND_RADIUS_FACTOR))
        bf_loose = float(getattr(glw, "_bond_rf_loose", BOND_RADIUS_FACTOR))
        bond_r = max(BOND_DRAW_SCALE * 0.4 * bond_scale, 0.04 * bond_scale)
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
                mid = (p + q) / 2.0
                for (a1, a2, anum) in ((p, mid, zi), (mid, q, zj)):
                    c = _col(anum)
                    L.append("cylinder { <%f, %f, %f>, <%f, %f, %f>, %f"
                             " pigment { color rgb <%f, %f, %f> } %s }"
                             % (a1[0], a1[1], a1[2], a2[0], a2[1], a2[2],
                                bond_r, c[0], c[1], c[2],
                                _finish(atom_amb, atom_dif, atom_spe)))

    # ── 等值面（smooth_triangle 半透明） ──
    surf_vcolor = bool(getattr(glw, "_surf_vcolor", False))
    pc = tuple(float(c) for c in getattr(glw, "_pc", (0.1, 0.8, 0.1)))
    nc = tuple(float(c) for c in getattr(glw, "_nc", (0.9, 0.25, 0.25)))
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
        if len(idx) > _SURF_MAX_TRI:
            stride = int(np.ceil(len(idx) / float(_SURF_MAX_TRI)))
            idx = idx[::stride]
        t = 1.0 - surf_op   # rgbt 透明度（POV-Ray 三角形单面，无前后叠暗）
        for (a, b, c) in idx:
            v0 = verts[a]; v1 = verts[b]; v2 = verts[c]
            n0 = norms[a]; n1 = norms[b]; n2 = norms[c]
            # FlipSides：法线背离相机时翻转（对齐画布）
            fn = _norm(np.cross(v1 - v0, v2 - v0))
            if float(np.dot(fn, viewdir)) > 0.0:
                n0, n1, n2 = -n0, -n1, -n2
            if surf_vcolor and colors is not None and colors.shape[0] > max(a, b, c):
                rgb = colors[[a, b, c], :3].mean(axis=0)
            else:
                rgb = nc if is_neg else pc
            rgb = tuple(float(x) for x in rgb[:3])
            L.append(
                "smooth_triangle { <%f, %f, %f>, <%f, %f, %f>,"
                " <%f, %f, %f>, <%f, %f, %f>,"
                " <%f, %f, %f>, <%f, %f, %f>"
                " pigment { color rgbt <%f, %f, %f, %f> } %s }"
                % (v0[0], v0[1], v0[2], n0[0], n0[1], n0[2],
                   v1[0], v1[1], v1[2], n1[0], n1[1], n1[2],
                   v2[0], v2[1], v2[2], n2[0], n2[1], n2[2],
                   rgb[0], rgb[1], rgb[2], t,
                   _finish(surf_amb, surf_dif, surf_spe)))

    return "\n".join(L) + "\n"


def render_glw_to_png(glw, povray_exe, output_png=None, resolution=(2000, 1500),
                      quality=10, log=None):
    """把画布场景渲染为 PNG（POV-Ray，后台线程调用）。

    Args:
        glw: CubGLWidget 实例
        povray_exe: pvengine64.exe 路径
        output_png: 输出 PNG 路径
        resolution: (宽, 高)
        quality: POV-Ray +Q 质量 0-11
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

    if not povray_exe or not os.path.isfile(povray_exe):
        _log("POV-Ray 可执行文件不存在: %s" % povray_exe)
        return None

    tmp = tempfile.mkdtemp(prefix="pov_")
    try:
        if output_png is None:
            output_png = os.path.join(
                tempfile.gettempdir(),
                "molstudio_povray_%d.png" % os.getpid())
        pov = glw_scene_to_pov(glw, *resolution)
        pov_path = os.path.join(tmp, "scene.pov")
        with open(pov_path, "w", newline="\n", encoding="ascii") as f:
            f.write(pov)
        _log("POV-Ray 场景生成完毕（%.1f KB），开始光线追踪渲染…"
             % (len(pov) / 1024.0))
        # POV-Ray pvengine 的 +O 参数在 CreateProcess 下易解析失败；
        # 用默认输出（scene.pov → scene.png 同目录）再移动。
        args = [povray_exe, "/RENDER", pov_path,
                "+W%d" % int(resolution[0]), "+H%d" % int(resolution[1]),
                "+Q%d" % int(quality), "/EXIT"]
        result = subprocess.run(args, capture_output=True, text=True,
                                timeout=900, errors="replace")
        tmp_out = os.path.join(tmp, "scene.png")
        if not os.path.exists(tmp_out) or result.returncode != 0:
            _log("POV-Ray 渲染失败: %s"
                 % ((result.stdout or result.stderr or "")[:400]))
            return None
        shutil.copy2(tmp_out, output_png)
        _log("POV-Ray 渲染完成 → %s" % os.path.basename(output_png))
        return output_png
    except subprocess.TimeoutExpired:
        _log("POV-Ray 渲染超时")
        return None
    except Exception as e:
        _log("POV-Ray 渲染异常: %s" % e)
        return None
    finally:
        try:
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass
