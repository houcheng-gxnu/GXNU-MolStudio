# -*- coding: utf-8 -*-
"""wgpu_viewer.py — 独立的 WebGPU( wgpu-py ) 分子可视化小程序。

**与主程序完全解耦**：不 import 也不改动 ovcanvas/ 里的任何渲染代码，
只可选地借用 molcanvas 的坐标解析（只读）。删掉本文件不影响主程序。

用法
────
    python wgpu_viewer.py                       # 内置示例分子（苯，带成键）
    python wgpu_viewer.py mol.fchk              # 读 .fchk / .cube / .xyz
    python wgpu_viewer.py --headless 3          # 不开窗口，离屏渲 3 帧存 PNG（自检用）
    python wgpu_viewer.py --backend d3d12       # 指定后端（vulkan/d3d12/opengl/cpu）

操作：左键拖拽旋转 / 滚轮缩放 / 右键或中键拖拽平移 / 双击复位 / R 复位
右侧面板实时改材质参数（镜面模型、光泽、粗糙度、清漆、次表面、半球光、灯光数），
全部是直接改 uniform —— 用来比较 WebGPU 与 OpenGL 版的手感与观感。

着色器是 `ovcanvas/_glwidget.py::_GLSL_COMMON` 的 WGSL 直译（多灯权重 1.0/0.58/0.48
+ 能量归一、GGX+Schlick、Clear-coat、SSS wrap/背光透射、Half-Lambert、半球环境光、
掠射 alpha 增强、深度雾化、two_sided 法线翻转）。
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time

import numpy as np
import wgpu


# ══════════════════════════════════════════════════════════════════════
# 1. 分子读取
# ══════════════════════════════════════════════════════════════════════

# 显示用原子半径（Å，CPK 风格观感）与颜色
_ATOM_R = {"H": 0.30, "C": 0.62, "N": 0.58, "O": 0.56, "F": 0.52, "P": 0.80,
           "S": 0.78, "Cl": 0.70, "Br": 0.78, "I": 0.88, "B": 0.62, "Si": 0.78}
_ATOM_C = {"H": (0.94, 0.94, 0.94), "C": (0.35, 0.35, 0.35), "N": (0.15, 0.25, 0.90),
           "O": (0.85, 0.12, 0.12), "F": (0.35, 0.85, 0.35), "P": (0.95, 0.55, 0.15),
           "S": (0.90, 0.80, 0.20), "Cl": (0.25, 0.80, 0.25), "Br": (0.65, 0.30, 0.15),
           "I": (0.55, 0.20, 0.70), "B": (0.90, 0.60, 0.45), "Si": (0.80, 0.65, 0.45)}
_COV_R = {"H": 0.31, "C": 0.76, "N": 0.71, "O": 0.66, "F": 0.57, "P": 1.07,
          "S": 1.05, "Cl": 1.02, "Br": 1.20, "I": 1.39, "B": 0.84, "Si": 1.11}
_BOND_R = 0.16          # 键圆柱半径（Å）
_BOND_C = (0.70, 0.70, 0.70)


def _demo_molecule():
    """内置示例：苯（12 原子 / 12 键），没有输入文件时用。"""
    r = 1.397
    atoms = []
    for i in range(6):                       # 碳环
        a = math.pi * 2 * i / 6
        atoms.append(("C", (r * math.cos(a), r * math.sin(a), 0.0)))
    for i in range(6):                       # 氢
        a = math.pi * 2 * i / 6
        atoms.append(("H", (2.48 * math.cos(a), 2.48 * math.sin(a), 0.0)))
    bonds = [(i, (i + 1) % 6) for i in range(6)] + [(i, i + 6) for i in range(6)]
    return atoms, bonds


def _guess_bonds(atoms):
    """按共价半径判键（.xyz 用；与主程序 molcanvas 的启发式同思路）。"""
    bonds = []
    pos = [a[1] for a in atoms]
    for i in range(len(atoms)):
        for j in range(i + 1, len(atoms)):
            ri = _COV_R.get(atoms[i][0], 0.8)
            rj = _COV_R.get(atoms[j][0], 0.8)
            d = math.dist(pos[i], pos[j])
            if 0.4 < d < (ri + rj) * 1.25:
                bonds.append((i, j))
    return bonds


def _parse_xyz(path):
    atoms = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.read().splitlines()
    for ln in lines[2:]:
        p = ln.split()
        if len(p) >= 4:
            try:
                atoms.append((p[0], (float(p[1]), float(p[2]), float(p[3]))))
            except ValueError:
                break
    return atoms


def load_cube_scene(path, isovalue=0.05,
                    pos_color=(0.10, 0.80, 0.10),
                    neg_color=(0.90, 0.25, 0.25)):
    """读 .cub/.cube → (atoms, bonds, cube, pos_surf, neg_surf)。

    等值面走主程序同一套 `marching_cubes`（PyMCubes + Sobel 梯度法线 +
    IboView 的 FixVolumeDataNormals 翻绕序）：正瓣 flip_normal=False、负瓣 True。
    坐标单位沿用 cube 文件原样（Gaussian 默认 Bohr），原子与等值面同源故一致。
    """
    from molstudio.core.marching_cubes import read_cube, marching_cubes
    from molstudio.render.molcanvas import ELEMENT_SYMBOLS

    cube = read_cube(path)
    t0 = time.perf_counter()
    pos = marching_cubes(cube, isovalue, flip_normal=False)
    neg = marching_cubes(cube, -isovalue, flip_normal=True)
    ms = (time.perf_counter() - t0) * 1000
    for surf, rgb in ((pos, pos_color), (neg, neg_color)):
        n = 0 if surf.vertices is None else len(surf.vertices)
        if n:
            surf.colors = np.tile(np.array([*rgb, 1.0], np.float32), (n, 1))
    atoms = [(ELEMENT_SYMBOLS.get(int(an), "C"), (x, y, z))
             for an, _q, x, y, z in cube.atoms]
    bonds = _guess_bonds(atoms)
    print(f"[i] 网格 {cube.nx}×{cube.ny}×{cube.nz}，等值面 {isovalue:.4f} → "
          f"正瓣 {pos.triangle_count} / 负瓣 {neg.triangle_count} 三角（{ms:.0f} ms）")
    return atoms, bonds, cube, pos, neg


def scene_bounds(atoms, iso=None):
    """相机定中心/半径：原子 + 等值面顶点一起算（有的 cub 不带原子）。"""
    pts = np.zeros((0, 3), np.float64)
    if atoms:
        pts = np.asarray([p for _s, p in atoms], dtype=np.float64).reshape(-1, 3)
    for s in (iso or ()):
        v = getattr(s, "vertices", None)
        if v is not None and len(v):
            pts = (v.astype(np.float64) if pts.size == 0
                   else np.vstack([pts, v.astype(np.float64)]))
    if pts.size == 0:
        return np.zeros(3), 5.0
    ctr = pts.mean(axis=0)
    return ctr, float(np.max(np.linalg.norm(pts - ctr, axis=1))) + 1.0


def load_molecule(path):
    """返回 (atoms, bonds)：atoms=[(元素符号, (x,y,z))]，bonds=[(i,j)] 0-based。"""
    if not path:
        print("[i] 未指定文件 → 使用内置示例分子（苯）")
        return _demo_molecule()
    ext = os.path.splitext(path)[1].lower()
    if ext in (".fchk", ".fch"):
        from molstudio.render.molcanvas import get_atoms_from_fchk, get_bonds_from_fchk
        raw = get_atoms_from_fchk(path)
        bl = get_bonds_from_fchk(raw)
    elif ext in (".cub", ".cube"):
        from molstudio.render.molcanvas import get_atoms_from_cube, get_bonds_from_cube
        raw = get_atoms_from_cube(path)
        bl = get_bonds_from_cube(raw)
    elif ext == ".xyz":
        atoms = _parse_xyz(path)
        return atoms, _guess_bonds(atoms)
    else:
        raise SystemExit(f"不认识的扩展名: {ext}（支持 .fchk/.cube/.xyz）")
    atoms = [(sym, tuple(pos)) for (_i, sym, _an, pos) in raw]
    bonds = [(i - 1, j - 1) for (i, j) in bl]
    print(f"[i] 读入 {os.path.basename(path)}：{len(atoms)} 原子 / {len(bonds)} 键")
    return atoms, bonds


# ══════════════════════════════════════════════════════════════════════
# 2. 几何：球 / 圆柱（都是单位尺寸，靠实例矩阵摆放）
# ══════════════════════════════════════════════════════════════════════

def sphere_mesh(lat=28, lon=40):
    verts = []
    for i in range(lat + 1):
        phi = math.pi * i / lat
        for j in range(lon + 1):
            th = 2.0 * math.pi * j / lon
            p = (math.sin(phi) * math.cos(th), math.cos(phi),
                 math.sin(phi) * math.sin(th))
            verts += [p, p]                     # 位置 + 法线（单位球同值）
    idx = []
    for i in range(lat):
        for j in range(lon):
            a = i * (lon + 1) + j
            b, c, d = a + 1, a + lon + 1, a + lon + 2
            idx += [a, b, c, b, d, c]           # 逆时针 = 正面
    return (np.asarray(verts, np.float32).reshape(-1, 6),
            np.asarray(idx, np.uint32))


def cylinder_mesh(seg=28):
    """单位圆柱：半径 1、z∈[0,1]，含两侧端盖。"""
    verts, idx = [], []
    for j in range(seg + 1):                    # 侧面
        th = 2.0 * math.pi * j / seg
        n = (math.cos(th), math.sin(th), 0.0)
        verts += [(n[0], n[1], 0.0), n, (n[0], n[1], 1.0), n]
    for j in range(seg):
        a = j * 2
        idx += [a, a + 2, a + 1, a + 1, a + 2, a + 3]
    base = len(verts)
    for th, z in ((0, 0.0), (0, 1.0)):          # 端盖中心
        verts += [(0.0, 0.0, z), (0.0, 0.0, -1.0 if z == 0 else 1.0)]
    c0, c1 = base, base + 1
    ring0 = len(verts)
    for j in range(seg + 1):
        th = 2.0 * math.pi * j / seg
        verts += [(math.cos(th), math.sin(th), 0.0), (0.0, 0.0, -1.0)]
    r0 = ring0
    for j in range(seg + 1):
        th = 2.0 * math.pi * j / seg
        verts += [(math.cos(th), math.sin(th), 1.0), (0.0, 0.0, 1.0)]
    r1 = r0 + seg + 1
    for j in range(seg):
        idx += [c0, r0 + j, r0 + j + 1]
        idx += [c1, r1 + j + 1, r1 + j]
    return (np.asarray(verts, np.float32).reshape(-1, 6),
            np.asarray(idx, np.uint32))


def _rot_z_to(d):
    """把 +Z 旋到单位向量 d 的 3×3 旋转（Rodrigues）。"""
    d = np.asarray(d, np.float64)
    n = np.linalg.norm(d)
    if n < 1e-12:
        return np.eye(3)
    d = d / n
    z = np.array([0.0, 0.0, 1.0])
    c = float(np.dot(z, d))
    if c > 1.0 - 1e-9:
        return np.eye(3)
    if c < -1.0 + 1e-9:                        # 反向：绕 X 转 180°
        return np.diag([1.0, -1.0, -1.0])
    v = np.cross(z, d)
    s = float(np.linalg.norm(v))
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * ((1.0 - c) / (s * s))


def _inst_from(rot, scale, trans, color):
    """组装实例数据：mat4（行主序拆 4 个 vec4）+ color。"""
    m = np.eye(4)
    m[:3, :3] = np.asarray(rot, np.float64) * np.asarray(scale, np.float64)
    m[:3, 3] = trans
    # 16（mat4，**列主序**：WGSL 的 mat4x4(m0,m1,m2,m3) 是按列构造的，
    # 按行展平会得到转置矩阵 → 平移落到最后一行，w 变成 t·p+1，画面直接炸掉）
    # + 4（rgba，alpha 恒 1）
    return np.concatenate([m.astype(np.float32).flatten(order="F"),
                           np.asarray(color, np.float32), [1.0]])


def build_instances(atoms, bonds):
    atom_inst = []
    for sym, pos in atoms:
        atom_inst.append(_inst_from(np.eye(3), _ATOM_R.get(sym, 0.60), pos,
                                    _ATOM_C.get(sym, (0.7, 0.7, 0.7))))
    bond_inst = []
    for i, j in bonds:
        pi = np.asarray(atoms[i][1], np.float64)
        pj = np.asarray(atoms[j][1], np.float64)
        d = pj - pi
        L = float(np.linalg.norm(d))
        if L < 1e-6:
            continue
        bond_inst.append(_inst_from(_rot_z_to(d), (_BOND_R, _BOND_R, L), pi,
                                    _BOND_C))
    return (np.asarray(atom_inst, np.float32).reshape(-1, 20) if atom_inst
            else np.zeros((0, 20), np.float32),
            np.asarray(bond_inst, np.float32).reshape(-1, 20) if bond_inst
            else np.zeros((0, 20), np.float32))


# ══════════════════════════════════════════════════════════════════════
# 3. 相机（正交，与主程序同约定：视线朝 +Z）
# ══════════════════════════════════════════════════════════════════════

class Camera:
    def __init__(self, center, radius):
        self.center = np.asarray(center, np.float64)
        self.radius = float(radius)
        self.yaw = -25.0
        self.pitch = 18.0
        self.zoom = 1.0
        self.pan = np.zeros(2)

    def reset(self):
        self.yaw, self.pitch, self.zoom = -25.0, 18.0, 1.0
        self.pan[:] = 0.0

    def fit(self, center, radius):
        """换了分子/等值面后重新取景。"""
        self.center = np.asarray(center, np.float64)
        self.radius = float(radius)
        self.reset()

    def rotation(self):
        """视图旋转（世界 → 视图）。与主程序一致：光源在**视图空间**固定，
        法线必须也先转到视图空间再打光，否则转分子时会出现「一面黑一面白」。"""
        ry, rx = math.radians(self.yaw), math.radians(self.pitch)
        Ry = np.array([[math.cos(ry), 0, math.sin(ry)],
                       [0, 1, 0],
                       [-math.sin(ry), 0, math.cos(ry)]])
        Rx = np.array([[1, 0, 0],
                       [0, math.cos(rx), -math.sin(rx)],
                       [0, math.sin(rx), math.cos(rx)]])
        return Rx @ Ry

    def mvp(self, aspect):
        R = self.rotation()
        view = np.eye(4)
        view[:3, :3] = R
        view[:3, 3] = -R @ self.center
        h = max(self.radius * 1.25 / max(self.zoom, 0.05), 0.5)
        w = h * aspect
        P = np.zeros((4, 4))
        P[0, 0] = 1.0 / w
        P[1, 1] = 1.0 / h
        P[2, 2] = 0.5 / (self.radius * 4.0)
        P[2, 3] = 0.5
        P[3, 3] = 1.0
        shift = np.eye(4)
        shift[0, 3] = self.pan[0] * w
        shift[1, 3] = self.pan[1] * h
        return shift @ P @ view


# ══════════════════════════════════════════════════════════════════════
# 4. WGSL（_GLSL_COMMON 的直译）
# ══════════════════════════════════════════════════════════════════════

_WGSL = """
struct Globals {
  DiffusePow:    f32, DiffuseStr:   f32, SpecStr:      f32, SpecSharp:    f32,
  Roughness:     f32, CoatRoughness:f32, CoatStrength: f32, SpecModel:    f32,
  SssStrength:   f32, SoftTerm:     f32, HemiEnabled:  f32, FogBias:      f32,
  FogWidth:      f32, Ambient:      f32, SpecMul:      f32, LightCount:   f32,
  LightNorm:     f32, Glow:         f32, OitZMin:      f32, OitZSpan:     f32,
  OitFalloff:    f32, _p0:          f32, _p1:          f32, _p2:          f32,
  // 与主程序同名同义：RGB 是「固有色乘子」（原子恒 0.8 灰、轨道恒白），
  // **.a = 等值面不透明度**。色相由逐顶点 v_Color 决定，两者不要混用。
  DiffuseColor: vec4<f32>,
  HemiTop:    vec4<f32>,
  HemiBottom: vec4<f32>,
  SpecColor:  vec4<f32>,
  N2W0: vec4<f32>, N2W1: vec4<f32>, N2W2: vec4<f32>,
  L0: vec4<f32>, L1: vec4<f32>, L2: vec4<f32>, L3: vec4<f32>,
  MVP: mat4x4<f32>,
};
@group(0) @binding(0) var<uniform> G: Globals;
// WBOIT 的两张累积图（合成趟用；等值面累积趟不读它们）
@group(0) @binding(1) var accum_tex: texture_2d<f32>;
@group(0) @binding(2) var reveal_tex: texture_2d<f32>;

const SILHOUETTE_ALPHA_FLOOR: f32 = 0.12;
const PI_: f32 = 3.14159265358979;
const F0: f32 = 0.04;
const F0_RIM: f32 = 0.85;

fn spec_ggx(N: vec3<f32>, L: vec3<f32>, V: vec3<f32>, rough: f32) -> vec3<f32> {
  let H = normalize(L + V);
  let NdotL = max(dot(N, L), 0.0);
  let NdotV = max(dot(N, V), 1e-4);
  let NdotH = max(dot(N, H), 0.0);
  let VdotH = max(dot(V, H), 0.0);
  let a  = max(rough * rough, 1e-4);
  let a2 = a * a;
  let dnm = NdotH * NdotH * (a2 - 1.0) + 1.0;
  let D = a2 / (PI_ * dnm * dnm);
  let F = vec3<f32>(F0) + (vec3<f32>(F0_RIM) - vec3<f32>(F0)) * pow(1.0 - VdotH, 5.0);
  let k = a * 0.5;
  let G1 = NdotL / (NdotL * (1.0 - k) + k);
  let G2 = NdotV / (NdotV * (1.0 - k) + k);
  return (D * F * (G1 * G2)) / max(4.0 * NdotV * NdotL, 1e-4);
}

fn sss_translucency(N: vec3<f32>, L: vec3<f32>) -> vec3<f32> {
  let V = vec3<f32>(0.0, 0.0, 1.0);
  let Hb = normalize(-L - N * 0.3);
  let back = pow(clamp(dot(V, Hb), 0.0, 1.0), 4.0);
  let thin = pow(1.0 - abs(N.z), 2.0);
  return vec3<f32>(back * thin);
}

fn light_contrib(N: vec3<f32>, L: vec3<f32>, intensity: f32, glow: f32,
                 base: vec4<f32>) -> vec4<f32> {
  let ndl_raw = dot(N, L);
  let ndl = clamp(ndl_raw, 0.0, 1.0);
  let ndl_half = ndl_raw * 0.5 + 0.5;
  var diffuse: vec4<f32>;
  var sss = vec3<f32>(0.0);
  if (G.SssStrength > 0.0) {
    let ndl_wrap = clamp((ndl_raw + G.SssStrength) / (1.0 + G.SssStrength), 0.0, 1.0);
    let nd = mix(ndl_wrap, ndl_half, G.SoftTerm);
    diffuse = G.DiffuseStr * pow(nd, G.DiffusePow) * G.DiffuseColor;
    sss = G.SssStrength * sss_translucency(N, L) * G.DiffuseColor.rgb;
  } else {
    let nd = mix(ndl, ndl_half, G.SoftTerm);
    diffuse = G.DiffuseStr * pow(nd, G.DiffusePow) * G.DiffuseColor;
  }
  var spec = vec3<f32>(0.0);
  if (G.SpecModel > 0.5 && G.SpecModel < 1.5) {
    let rough = clamp(G.Roughness * max(glow, 0.05), 0.03, 1.0);
    spec = G.SpecStr * spec_ggx(N, L, vec3<f32>(0.0, 0.0, 1.0), rough)
         * G.SpecColor.rgb * G.SpecMul;
  } else if (G.SpecModel > 1.5) {
    let br = clamp(G.Roughness * max(glow, 0.05), 0.03, 1.0);
    let cr = clamp(G.CoatRoughness * max(glow, 0.05), 0.03, 1.0);
    let b = G.SpecStr * spec_ggx(N, L, vec3<f32>(0.0, 0.0, 1.0), br);
    let c = G.CoatStrength * spec_ggx(N, L, vec3<f32>(0.0, 0.0, 1.0), cr);
    spec = (b + c) * G.SpecColor.rgb * G.SpecMul;
  } else {
    spec = G.SpecStr
         * (G.SpecSharp * pow(ndl, 16.0 * glow) + 1.2 * pow(ndl, 64.0 * glow))
         * G.SpecColor.rgb * G.SpecMul;
  }
  return intensity * (base * diffuse + vec4<f32>(spec, 0.0)
                      + vec4<f32>(base.rgb * sss, 0.0));
}

struct VSOut {
  @builtin(position) pos: vec4<f32>,
  @location(0) normal: vec3<f32>,
  @location(1) color: vec4<f32>,
};

@vertex
fn vs_main(@location(0) p: vec3<f32>, @location(1) n: vec3<f32>,
           @location(2) m0: vec4<f32>, @location(3) m1: vec4<f32>,
           @location(4) m2: vec4<f32>, @location(5) m3: vec4<f32>,
           @location(6) icol: vec4<f32>) -> VSOut {
  let model = mat4x4<f32>(m0, m1, m2, m3);
  var o: VSOut;
  o.pos = G.MVP * (model * vec4<f32>(p, 1.0));
  // 法线必须先转到**视图空间**：光源方向（L0..L3）与主程序一样是视图空间常量
  // （转分子时光跟着视角走），用世界法线打光会得到「翻个面一半黑一半白」。
  // 注意 mat3x3(a,b,c) 按列构造：CPU 端存的是 Rᵀ 的行 → 这里得到 R（世界→视图），
  // 所以打光用 N2W 本体、半球光转回世界才用 transpose(N2W)。
  let n_world = normalize((model * vec4<f32>(n, 0.0)).xyz);
  let N2W = mat3x3<f32>(G.N2W0.xyz, G.N2W1.xyz, G.N2W2.xyz);
  o.normal = normalize(N2W * n_world);
  o.color = icol;
  return o;
}

// 不透明与透明两条路径共用的着色结果（含 alpha；alpha 自 DiffuseColor.a 来）
fn shade_all(N: vec3<f32>, base: vec4<f32>, z: f32) -> vec4<f32> {
  var color = vec4<f32>(0.0);
  let dirs = array<vec3<f32>, 4>(G.L0.xyz, G.L1.xyz, G.L2.xyz, G.L3.xyz);
  let glows = array<f32, 4>(G.L0.w, G.L1.w, G.L2.w, G.L3.w);
  let iw = array<f32, 4>(1.0, 0.58, 0.48, 0.38);
  for (var i: i32 = 0; i < 4; i = i + 1) {
    if (f32(i) >= G.LightCount) { break; }
    color = color + light_contrib(N, dirs[i], iw[i] * G.LightNorm, glows[i], base);
  }
  if (G.HemiEnabled > 0.5) {
    // 半球环境光要世界法线：transpose(N2W) = Rᵀ（视图 → 世界）
    let N2Wt = transpose(mat3x3<f32>(G.N2W0.xyz, G.N2W1.xyz, G.N2W2.xyz));
    let Nw = normalize(N2Wt * N);
    let h = clamp(Nw.y * 0.5 + 0.5, 0.0, 1.0);
    let hemi = mix(G.HemiBottom.rgb, G.HemiTop.rgb, h) * vec3<f32>(0.25);
    color = vec4<f32>(color.rgb + hemi * base.rgb, color.a);
  }
  // 掠射角 alpha 增强：透明面剪影更不透明，避免边缘被背景洗白
  color = vec4<f32>(color.rgb, color.a / clamp(abs(N.z), SILHOUETTE_ALPHA_FLOOR, 1.0));
  let fog = clamp(G.FogWidth * (z - 0.5) + G.FogBias, 0.0, 1.0);
  color = vec4<f32>(mix(color.rgb, vec3<f32>(1.0), fog), color.a);
  color = vec4<f32>(color.rgb + G.Ambient * base.rgb, color.a);
  return color;
}

@fragment
fn fs_main(in: VSOut, @builtin(front_facing) front: bool)
           -> @location(0) vec4<f32> {
  var N = normalize(in.normal);
  if (!front) { N = -N; }
  return shade_all(N, in.color, in.pos.z);
}

// ── 等值面：逐顶点 pos/normal/color（无实例矩阵）──
@vertex
fn vs_iso(@location(0) p: vec3<f32>, @location(1) n: vec3<f32>,
          @location(2) c: vec4<f32>) -> VSOut {
  var o: VSOut;
  o.pos = G.MVP * vec4<f32>(p, 1.0);
  let N2W = mat3x3<f32>(G.N2W0.xyz, G.N2W1.xyz, G.N2W2.xyz);
  o.normal = normalize(N2W * n);
  o.color = c;
  return o;
}

// ── WBOIT 累积趟（McGuire & Bavoil）──────────────────────────────
// out0 accum: Σ (c.rgb·a, a)·w   —— 混合 ONE / ONE
// out1 reveal: Π (1 - a)         —— 混合 ZERO / ONE_MINUS_SRC
struct OitOut {
  @location(0) accum: vec4<f32>,
  @location(1) reveal: vec4<f32>,
};

@fragment
fn fs_iso_oit(in: VSOut, @builtin(front_facing) front: bool) -> OitOut {
  var N = normalize(in.normal);
  if (!front) { N = -N; }              // 双面：开口瓣内壁同样受光
  let c = shade_all(N, in.color, in.pos.z);
  let a = clamp(c.a, 0.0, 1.0);
  if (a < 1.0 / 255.0) { discard; }
  // 不透明度权重（论文去掉了 1e8 常数）
  let wa = pow(min(1.0, a * 10.0) + 0.01, 3.0);
  // 深度权重：正交投影下必须按**场景自身深度跨度**归一化后指数衰减，
  // 照搬论文 1e8·(1-0.9z)³ 会顶满 3e3 上限失效（主程序同款改法）
  let t = clamp((in.pos.z - G.OitZMin) / max(G.OitZSpan, 1e-6), 0.0, 1.0);
  let wd = exp(-max(G.OitFalloff, 0.0) * t);
  let w = clamp(wa * wd * 100.0, 1e-2, 3e3);
  var o: OitOut;
  o.accum = vec4<f32>(c.rgb * a, a) * w;
  o.reveal = vec4<f32>(a);
  return o;
}

// ── 合成趟：全屏三角，average = accum.rgb / accum.a ──
struct QuadOut {
  @builtin(position) pos: vec4<f32>,
};

@vertex
fn vs_quad(@builtin(vertex_index) vi: u32) -> QuadOut {
  var p = array<vec2<f32>, 3>(vec2<f32>(-1.0, -1.0), vec2<f32>(3.0, -1.0),
                              vec2<f32>(-1.0, 3.0));
  var o: QuadOut;
  o.pos = vec4<f32>(p[vi], 0.0, 1.0);
  return o;
}

@fragment
fn fs_composite(in: QuadOut) -> @location(0) vec4<f32> {
  let p = vec2<i32>(in.pos.xy);
  let acc = textureLoad(accum_tex, p, 0);
  let rev = clamp(textureLoad(reveal_tex, p, 0).r, 0.0, 1.0);
  let avg = acc.rgb / max(acc.a, 1e-5);
  // 输出 alpha = revealage，配合 (1-src.a, src.a) 混合即
  // final = average·(1-reveal) + background·reveal
  return vec4<f32>(avg, rev);
}
"""

_LIGHTS = ((0.50, 0.50, 0.7071), (-0.40, -0.35, 0.8470),
           (0.45, -0.30, 0.8410), (0.0, 0.0, 1.0))


def pack_globals(params, mvp, rot):
    """按 Globals 布局打包（84 个 f32 = 336 字节；vec4 成员须 16 字节对齐）。

    ``rot`` 是视图旋转（世界 → 视图）。这里存它的**转置** N2W（视图 → 世界）：
    主程序里法线是视图空间的，半球环境光要拿世界法线算上/下半球，靠的就是
    ``view[:3,:3].T``（见 _glwidget._set_xforms）。
    """
    g = np.zeros(84, np.float32)
    g[0:24] = [
        params["diffuse_pow"], params["diffuse_str"], params["spec_str"],
        params["spec_sharp"], params["roughness"], params["coat_rough"],
        params["coat_str"], params["spec_model"], params["sss"],
        params["soft_term"], 1.0 if params["hemi"] else 0.0, 0.0,
        params["fog_width"], 0.0, 1.0, params["light_count"],
        1.0, 1.0,
        params["oit_zmin"], params["oit_zspan"], params["oit_falloff"],
        0.0, 0.0, 0.0,
    ]
    g[24:28] = params["diffuse_color"]          # rgb 固有色乘子 + a 不透明度
    g[28:32] = (*params["hemi_top"], 0.0)
    g[32:36] = (*params["hemi_bottom"], 0.0)
    g[36:40] = (1.0, 1.0, 1.0, 0.0)
    n2w = np.asarray(rot, np.float64).T
    g[40:44] = (n2w[0, 0], n2w[0, 1], n2w[0, 2], 0.0)
    g[44:48] = (n2w[1, 0], n2w[1, 1], n2w[1, 2], 0.0)
    g[48:52] = (n2w[2, 0], n2w[2, 1], n2w[2, 2], 0.0)
    for i, d in enumerate(_LIGHTS):
        g[52 + i * 4: 56 + i * 4] = (d[0], d[1], d[2], 1.0)
    g[68:84] = np.asarray(mvp, np.float32).flatten(order="F")
    return g.tobytes()


# ══════════════════════════════════════════════════════════════════════
# 5. 渲染器（画布与离屏共用）
# ══════════════════════════════════════════════════════════════════════

class Renderer:
    #: 4× MSAA —— 边缘锯齿是「难看」的主因，WebGPU 一行 multisample 就解决
    SAMPLES = 4

    def __init__(self, device, atoms, bonds, color_format):
        self.device = device
        self.color_format = color_format
        # 默认值对齐主程序：_REG_DEFAULT_A = [0.85, 0.70, 0.50, -0.50]、
        # roughness 0.30 / coat_roughness 0.10 / coat_strength 0.80；
        # DiffuseColor 原子恒 (0.8,0.8,0.8,1)（元素色走逐顶点 v_Color）。
        self.params = {
            "diffuse_pow": 0.85, "diffuse_str": 0.70, "spec_str": 0.50,
            "spec_sharp": -0.50, "roughness": 0.30, "coat_rough": 0.10,
            "coat_str": 0.80, "spec_model": 1.0, "sss": 0.0, "soft_term": 0.0,
            "hemi": True, "hemi_top": (0.18, 0.18, 0.18),
            "hemi_bottom": (0.035, 0.035, 0.035), "light_count": 3.0,
            "fog_width": 0.0,
            "diffuse_color": (0.8, 0.8, 0.8, 1.0),
            "oit_zmin": 0.375, "oit_zspan": 0.25, "oit_falloff": 4.0,
        }
        # 两条 pass 各用一份 DiffuseColor（与主程序两个 program 同义）：
        # 原子 0.8 灰、轨道纯白 + alpha=不透明度
        self.diffuse_atom = (0.8, 0.8, 0.8, 1.0)
        self.diffuse_iso = (1.0, 1.0, 1.0, 0.78)
        self.clear = (1.0, 1.0, 1.0, 1.0)
        self._size = None
        self._depth = None
        self._msaa = None
        self._acc = self._acc_res = None
        self._rev = self._rev_res = None
        self.iso = []          # [(vbuf, ibuf, count)]，正瓣 + 负瓣
        self.iso_tris = 0

        sv, si = sphere_mesh()
        cv, ci = cylinder_mesh()
        self._meshes = [(sv, si), (cv, ci)]

        usage = wgpu.BufferUsage.VERTEX | wgpu.BufferUsage.INDEX
        self.vbuf = [device.create_buffer_with_data(data=v.astype(np.float32).tobytes(),
                                                    usage=wgpu.BufferUsage.VERTEX)
                     for v, _ in self._meshes]
        self.ibuf = [device.create_buffer_with_data(data=i.tobytes(), usage=usage)
                     for _, i in self._meshes]
        self.set_mol(atoms, bonds)

        self.ubo = device.create_buffer_with_data(
            data=pack_globals(self.params, np.eye(4), np.eye(3)),
            usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST)
        # 两套 bind group layout：
        #  · plain  —— 只含 uniform（原子/键/等值面累积趟）
        #  · comp   —— uniform + 两张累积图（合成趟要 texelFetch）
        #  必须分开：累积趟里 accum/reveal 是 **resolve 目标**（COLOR_TARGET），
        #  同一 pass 内再当纹理绑定（RESOURCE）会触发 "conflicting usages"。
        uni = {"binding": 0,
               "visibility": wgpu.ShaderStage.VERTEX | wgpu.ShaderStage.FRAGMENT,
               "buffer": {"type": wgpu.BufferBindingType.uniform}}
        tex = lambda b: {"binding": b, "visibility": wgpu.ShaderStage.FRAGMENT,
                         "texture": {"sample_type": wgpu.TextureSampleType.float,
                                     "view_dimension": wgpu.TextureViewDimension.d2}}
        self.bgl_plain = device.create_bind_group_layout(entries=[uni])
        self.bgl_comp = device.create_bind_group_layout(
            entries=[uni, tex(1), tex(2)])
        self.bg_plain = device.create_bind_group(
            layout=self.bgl_plain, entries=[
                {"binding": 0, "resource": {"buffer": self.ubo, "offset": 0,
                                            "size": self.ubo.size}}])
        self.bg_comp = None     # 尺寸定了才有累积图，那时再建
        self.layout = device.create_pipeline_layout(
            bind_group_layouts=[self.bgl_plain])
        self.layout_comp = device.create_pipeline_layout(
            bind_group_layouts=[self.bgl_comp])

        self.mod = device.create_shader_module(code=_WGSL)
        t0 = time.perf_counter()
        self._make_pipelines()
        self.pipe_ms = (time.perf_counter() - t0) * 1000

    def _make_pipelines(self):
        """建/重建几何管线（sample_count 烘焙在管线里，改抗锯齿档位要重建）。"""
        device, mod = self.device, self.mod
        color_format = self.color_format
        self.pipe = device.create_render_pipeline(
            layout=self.layout,
            vertex={
                "module": mod, "entry_point": "vs_main",
                "buffers": [
                    {"array_stride": 24, "step_mode": wgpu.VertexStepMode.vertex,
                     "attributes": [
                         {"shader_location": 0, "offset": 0,
                          "format": wgpu.VertexFormat.float32x3},
                         {"shader_location": 1, "offset": 12,
                          "format": wgpu.VertexFormat.float32x3}]},
                    {"array_stride": 80, "step_mode": wgpu.VertexStepMode.instance,
                     "attributes": [
                         {"shader_location": 2, "offset": 0,
                          "format": wgpu.VertexFormat.float32x4},
                         {"shader_location": 3, "offset": 16,
                          "format": wgpu.VertexFormat.float32x4},
                         {"shader_location": 4, "offset": 32,
                          "format": wgpu.VertexFormat.float32x4},
                         {"shader_location": 5, "offset": 48,
                          "format": wgpu.VertexFormat.float32x4},
                         {"shader_location": 6, "offset": 64,
                          "format": wgpu.VertexFormat.float32x4}]},
                ]},
            fragment={"module": mod, "entry_point": "fs_main",
                      "targets": [{"format": color_format}]},
            primitive={"topology": wgpu.PrimitiveTopology.triangle_list,
                       "cull_mode": wgpu.CullMode.none},
            depth_stencil={"format": wgpu.TextureFormat.depth32float,
                           "depth_write_enabled": True,
                           "depth_compare": wgpu.CompareFunction.less_equal},
            multisample={"count": self.SAMPLES})

        # ── 等值面：逐顶点 pos/normal/color，走 WBOIT 双附件 ──
        _add = {"src_factor": wgpu.BlendFactor.one,
                "dst_factor": wgpu.BlendFactor.one,
                "operation": wgpu.BlendOperation.add}
        _mul = {"src_factor": wgpu.BlendFactor.zero,
                "dst_factor": wgpu.BlendFactor.one_minus_src,
                "operation": wgpu.BlendOperation.add}
        self.pipe_iso = device.create_render_pipeline(
            layout=self.layout,
            vertex={
                "module": mod, "entry_point": "vs_iso",
                "buffers": [
                    {"array_stride": 40, "step_mode": wgpu.VertexStepMode.vertex,
                     "attributes": [
                         {"shader_location": 0, "offset": 0,
                          "format": wgpu.VertexFormat.float32x3},
                         {"shader_location": 1, "offset": 12,
                          "format": wgpu.VertexFormat.float32x3},
                         {"shader_location": 2, "offset": 24,
                          "format": wgpu.VertexFormat.float32x4}]},
                ]},
            fragment={"module": mod, "entry_point": "fs_iso_oit",
                      "targets": [
                          # accum: dst += src（ONE/ONE）
                          {"format": wgpu.TextureFormat.rgba16float,
                           "blend": {"color": _add, "alpha": _add}},
                          # reveal: dst *= (1 - src)（ZERO/ONE_MINUS_SRC）
                          {"format": wgpu.TextureFormat.r16float,
                           "blend": {"color": _mul, "alpha": _mul}}]},
            primitive={"topology": wgpu.PrimitiveTopology.triangle_list,
                       "cull_mode": wgpu.CullMode.none},
            # 深度：只做遮挡测试、不写（原子/键已在上一趟写好）
            depth_stencil={"format": wgpu.TextureFormat.depth32float,
                           "depth_write_enabled": False,
                           "depth_compare": wgpu.CompareFunction.less},
            multisample={"count": self.SAMPLES})

        # ── 合成：全屏三角，单采样（直接画进已 resolve 好的画布）──
        self.pipe_comp = device.create_render_pipeline(
            layout=self.layout_comp,
            vertex={"module": mod, "entry_point": "vs_quad"},
            fragment={"module": mod, "entry_point": "fs_composite",
                      "targets": [{"format": color_format,
                                   "blend": {
                                       "color": {
                                           "src_factor":
                                               wgpu.BlendFactor.one_minus_src_alpha,
                                           "dst_factor": wgpu.BlendFactor.src_alpha,
                                           "operation": wgpu.BlendOperation.add},
                                       "alpha": {
                                           "src_factor": wgpu.BlendFactor.one,
                                           "dst_factor": wgpu.BlendFactor.one,
                                           "operation": wgpu.BlendOperation.add}}}]},
            primitive={"topology": wgpu.PrimitiveTopology.triangle_list})

    def set_samples(self, n):
        """切抗锯齿档位。只能用 1 或 4：WebGPU 对 rgba8unorm 只保证这两个
        采样数（2×/8× 要 TEXTURE_ADAPTER_SPECIFIC_FORMAT_FEATURES）。
        采样数烘焙在管线里，故改档要重建管线。"""
        n = int(max(1, min(4, n)))
        if n == self.SAMPLES:
            return
        self.SAMPLES = n
        self._make_pipelines()
        self._size = None          # 强制按新采样数重建颜色/深度/累积缓冲

    # ── 几何数据 ──
    def set_mol(self, atoms, bonds):
        """换分子：只重建逐实例缓冲（球/圆柱网格与管线不变）。"""
        ai, bi = build_instances(atoms, bonds)
        self.counts = [len(ai), len(bi)]
        self.inst = []
        for arr in (ai, bi):
            self.inst.append(None if len(arr) == 0 else
                             self.device.create_buffer_with_data(
                                 data=arr.tobytes(), usage=wgpu.BufferUsage.VERTEX))

    def set_iso(self, surfaces):
        """surfaces: marching_cubes 的 IsoSurface 列表（正瓣 / 负瓣）。

        顶点交错成 (pos3, normal3, color4) = 40 字节；颜色为 None 时填白。
        """
        self.iso = []
        self.iso_tris = 0
        for s in (surfaces or ()):
            n = 0 if s.vertices is None else len(s.vertices)
            if n == 0 or s.indices is None or len(s.indices) == 0:
                continue
            cols = s.colors
            if cols is None or len(cols) != n:
                cols = np.ones((n, 4), np.float32)
            inter = np.empty((n, 10), np.float32)
            inter[:, 0:3] = s.vertices
            inter[:, 3:6] = s.normals
            inter[:, 6:10] = cols
            self.iso.append((
                self.device.create_buffer_with_data(
                    data=inter.tobytes(), usage=wgpu.BufferUsage.VERTEX),
                self.device.create_buffer_with_data(
                    data=np.ascontiguousarray(s.indices, np.uint32).tobytes(),
                    usage=wgpu.BufferUsage.INDEX),
                int(s.indices.size)))
            self.iso_tris += int(s.indices.size) // 3

    # ── 每帧 ──
    def ensure_targets(self, w, h):
        """按当前尺寸建/重建 MSAA 颜色缓冲、深度缓冲与 WBOIT 两张累积图。"""
        if self._size == (w, h) and self._depth is not None:
            return
        self._size = (w, h)
        w, h = max(1, w), max(1, h)
        d = self.device
        s = self.SAMPLES
        self._depth = d.create_texture(
            size=(w, h, 1), format=wgpu.TextureFormat.depth32float,
            usage=wgpu.TextureUsage.RENDER_ATTACHMENT, sample_count=s)
        # accum / reveal 也跟着开 MSAA（等值面边缘同样要抗锯齿），各自配一张
        # 单采样的副本给合成趟 texelFetch。关抗锯齿（s==1）时没有 resolve 这一
        # 步（resolve 源必须是多重采样），副本直接指向本体。
        if s > 1:
            self._msaa = d.create_texture(
                size=(w, h, 1), format=self.color_format,
                usage=wgpu.TextureUsage.RENDER_ATTACHMENT, sample_count=s)
            self._acc = d.create_texture(
                size=(w, h, 1), format=wgpu.TextureFormat.rgba16float,
                usage=wgpu.TextureUsage.RENDER_ATTACHMENT, sample_count=s)
            self._acc_res = d.create_texture(
                size=(w, h, 1), format=wgpu.TextureFormat.rgba16float,
                usage=wgpu.TextureUsage.RENDER_ATTACHMENT
                | wgpu.TextureUsage.TEXTURE_BINDING)
            self._rev = d.create_texture(
                size=(w, h, 1), format=wgpu.TextureFormat.r16float,
                usage=wgpu.TextureUsage.RENDER_ATTACHMENT, sample_count=s)
            self._rev_res = d.create_texture(
                size=(w, h, 1), format=wgpu.TextureFormat.r16float,
                usage=wgpu.TextureUsage.RENDER_ATTACHMENT
                | wgpu.TextureUsage.TEXTURE_BINDING)
        else:
            self._msaa = None
            self._acc = self._acc_res = d.create_texture(
                size=(w, h, 1), format=wgpu.TextureFormat.rgba16float,
                usage=wgpu.TextureUsage.RENDER_ATTACHMENT
                | wgpu.TextureUsage.TEXTURE_BINDING)
            self._rev = self._rev_res = d.create_texture(
                size=(w, h, 1), format=wgpu.TextureFormat.r16float,
                usage=wgpu.TextureUsage.RENDER_ATTACHMENT
                | wgpu.TextureUsage.TEXTURE_BINDING)
        self.bg_comp = d.create_bind_group(layout=self.bgl_comp, entries=[
            {"binding": 0, "resource": {"buffer": self.ubo, "offset": 0,
                                        "size": self.ubo.size}},
            {"binding": 1, "resource": self._acc_res.create_view()},
            {"binding": 2, "resource": self._rev_res.create_view()}])

    def _write_uniforms(self, mvp, rot):
        self.device.queue.write_buffer(
            self.ubo, 0, pack_globals(self.params, mvp, rot))

    def encode(self, encoder, color_view, mvp, rot, w, h):
        # ① 不透明（原子 + 键）：画到 MSAA 缓冲再 resolve 到目标
        #    DiffuseColor 与主程序一致：原子恒 (0.8,0.8,0.8)，元素色走逐顶点 v_Color
        self.params["diffuse_color"] = self.diffuse_atom
        self._write_uniforms(mvp, rot)
        if self._msaa is not None:
            ca0 = {"view": self._msaa.create_view(),
                   "resolve_target": color_view,
                   "load_op": wgpu.LoadOp.clear,
                   "store_op": wgpu.StoreOp.store,
                   "clear_value": self.clear}
        else:                                   # 关抗锯齿：直接画到目标
            ca0 = {"view": color_view, "load_op": wgpu.LoadOp.clear,
                   "store_op": wgpu.StoreOp.store, "clear_value": self.clear}
        rp = encoder.begin_render_pass(
            color_attachments=[ca0],
            depth_stencil_attachment={
                "view": self._depth.create_view(),
                "depth_load_op": wgpu.LoadOp.clear,
                "depth_store_op": wgpu.StoreOp.store, "depth_clear_value": 1.0})
        rp.set_pipeline(self.pipe)
        rp.set_bind_group(0, self.bg_plain)
        for mi in (0, 1):
            if self.inst[mi] is None or self.counts[mi] == 0:
                continue
            rp.set_vertex_buffer(0, self.vbuf[mi])
            rp.set_vertex_buffer(1, self.inst[mi])
            rp.set_index_buffer(self.ibuf[mi], wgpu.IndexFormat.uint32)
            rp.draw_indexed(self._meshes[mi][1].size, self.counts[mi], 0, 0, 0)
        rp.end()

        if not self.iso:
            return

        # 等值面：RGB 恒白（色相全靠相位色），**.a = 不透明度**
        self.params["diffuse_color"] = self.diffuse_iso
        self._write_uniforms(mvp, rot)
        # ② 等值面累积（WBOIT）：accum 清 0、reveal 清 1，深度只测不写
        def _ca(tex, res, clear):
            d = {"view": tex.create_view(), "load_op": wgpu.LoadOp.clear,
                 "store_op": wgpu.StoreOp.store, "clear_value": clear}
            if self._msaa is not None:
                d["resolve_target"] = res.create_view()
            return d

        rp = encoder.begin_render_pass(
            color_attachments=[
                _ca(self._acc, self._acc_res, (0.0, 0.0, 0.0, 0.0)),
                _ca(self._rev, self._rev_res, (1.0, 1.0, 1.0, 1.0))],
            depth_stencil_attachment={
                "view": self._depth.create_view(),
                "depth_load_op": wgpu.LoadOp.load,
                "depth_store_op": wgpu.StoreOp.store})
        rp.set_pipeline(self.pipe_iso)
        rp.set_bind_group(0, self.bg_plain)
        for vbuf, ibuf, cnt in self.iso:
            rp.set_vertex_buffer(0, vbuf)
            rp.set_index_buffer(ibuf, wgpu.IndexFormat.uint32)
            rp.draw_indexed(cnt, 1, 0, 0, 0)
        rp.end()

        # ③ 合成到目标（目标里已有不透明结果 → load 而非 clear）
        rp = encoder.begin_render_pass(
            color_attachments=[{"view": color_view,
                                "load_op": wgpu.LoadOp.load,
                                "store_op": wgpu.StoreOp.store}])
        rp.set_pipeline(self.pipe_comp)
        rp.set_bind_group(0, self.bg_comp)
        rp.draw(3, 1, 0, 0)
        rp.end()


# ══════════════════════════════════════════════════════════════════════
# 6. 设备
# ══════════════════════════════════════════════════════════════════════

def open_device(want_backend=None):
    adapters = wgpu.gpu.enumerate_adapters_sync()
    for i, ad in enumerate(adapters):
        d = dict(ad.info)
        print(f"  [{i}] {d.get('backend_type')} | {d.get('device')} | "
              f"{d.get('adapter_type')}")
    adapter = None
    if want_backend:
        key = want_backend.lower()
        for ad in adapters:
            if str(dict(ad.info).get("backend_type", "")).lower() == key:
                adapter = ad
                break
        if adapter is None:
            print(f"[!] 没找到 {want_backend} 后端，改用高性能自动选择")
    if adapter is None:
        adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
    device = adapter.request_device_sync()
    print(f"[i] 使用后端: {dict(adapter.info).get('backend_type')} | "
          f"{dict(adapter.info).get('device')}")
    return adapter, device


# ══════════════════════════════════════════════════════════════════════
# 7. 离屏自检（无窗口）
# ══════════════════════════════════════════════════════════════════════

def run_headless(device, atoms, bonds, iso, frames, out_png):
    W, H = 640, 480
    r = Renderer(device, atoms, bonds, wgpu.TextureFormat.rgba8unorm)
    r.set_iso(iso)
    ctr, rad = scene_bounds(atoms, iso)
    cam = Camera(ctr, rad)
    color = device.create_texture(
        size=(W, H, 1), format=wgpu.TextureFormat.rgba8unorm,
        usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC)
    r.ensure_targets(W, H)
    t0 = time.perf_counter()
    t_first = 0.0
    for i in range(max(1, frames)):
        cam.yaw += 4.0
        enc = device.create_command_encoder()
        r.encode(enc, color.create_view(), cam.mvp(W / H), cam.rotation(), W, H)
        device.queue.submit([enc.finish()])
        if i == 0:
            t_first = (time.perf_counter() - t0) * 1000
    dt = (time.perf_counter() - t0) * 1000
    bpr = (W * 4 + 255) // 256 * 256
    raw = np.frombuffer(device.queue.read_texture(
        {"texture": color, "origin": (0, 0, 0)},
        {"offset": 0, "bytes_per_row": bpr, "rows_per_image": H}, (W, H, 1)),
        np.uint8).reshape(H, bpr)[:, :W * 4].reshape(H, W, 4).copy()
    from PyQt5.QtGui import QImage
    QImage(raw.tobytes(), W, H, W * 4, QImage.Format_RGBA8888).save(out_png)
    print(f"[i] 管线创建 {r.pipe_ms:.0f} ms | 首帧 {t_first:.0f} ms | "
          f"{frames} 帧共 {dt:.0f} ms（{dt / max(1, frames):.2f} ms/帧）"
          + (f" | 等值面 {r.iso_tris} 三角" if r.iso else ""))
    print(f"[i] 已写出 {out_png}")


# ══════════════════════════════════════════════════════════════════════
# 8. GUI（PyQt5 + rendercanvas.pyqt5）
# ══════════════════════════════════════════════════════════════════════

def run_gui(device, adapter, atoms, bonds, cube=None, iso=None, cube_path=None,
            auto_close=0.0):
    from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                                 QHBoxLayout, QLabel, QSlider, QComboBox,
                                 QCheckBox, QGroupBox, QFormLayout, QPushButton,
                                 QColorDialog, QFileDialog)
    from PyQt5.QtGui import QColor, QFont
    from PyQt5.QtCore import Qt, QTimer
    from rendercanvas.pyqt5 import RenderCanvas

    app = QApplication.instance() or QApplication(sys.argv)
    try:
        import molstudio.ui.theme
        app.setStyleSheet(theme.LIGHT_QSS)
    except Exception:
        pass
    # 全局字号压一档：这套 QSS 是主程序（大窗口）用的，这里整体调小更协调
    app.setFont(QFont("Microsoft YaHei UI", 9))

    win = QMainWindow()
    win.setWindowTitle("wgpu 画布（独立程序 · 不影响主程序）")
    central = QWidget()
    root = QVBoxLayout(central)
    root.setContentsMargins(6, 6, 6, 6)
    root.setSpacing(6)

    # ── 顶栏：载入文件 ──
    top = QWidget()
    tl = QHBoxLayout(top)
    tl.setContentsMargins(0, 0, 0, 0)
    tl.setSpacing(6)
    btn_open = QPushButton("载入文件…")
    btn_open.setObjectName("SmallBtn")
    btn_open.setFixedHeight(24)
    btn_open.setStyleSheet("QPushButton{font-size:11px; padding:1px 10px;}")
    btn_open.setToolTip("支持 .cub/.cube（轨道等值面）、.fchk、.xyz")
    lbl_file = QLabel("（未载入）")
    lbl_file.setStyleSheet("color:#6B7280; font-size:11px;")
    tl.addWidget(btn_open)
    tl.addWidget(lbl_file, 1)
    root.addWidget(top)

    h = QHBoxLayout()
    h.setSpacing(6)

    # max_fps 默认是 **30**（rendercanvas 的默认值），不显式调高就会一直卡在
    # 29 FPS——旋转的「不跟手」就是它，不是渲染开销。这里给到 120，再由 vsync
    # 收敛到显示器刷新率。
    canvas = RenderCanvas(parent=central, size=(620, 560), max_fps=120)
    h.addWidget(canvas, 1)

    # 画布 → wgpu 上下文 → 优选格式 → 配置；之后才能建管线（要格式）
    # 呈现由 rendercanvas 在每帧 draw 回调后自动完成（内部调 context.present），
    # 所以这里不要自己再 present 一次。
    context = canvas.get_context("wgpu")
    fmt = context.get_preferred_format(adapter)
    context.configure(device=device, format=fmt, alpha_mode="opaque")
    renderer = Renderer(device, atoms, bonds, fmt)
    renderer.set_iso(iso)
    print(f"[i] 画布格式 {fmt}")

    center, radius = scene_bounds(atoms, iso)
    cam = Camera(center, radius)

    # ── 右侧参数面板 ──
    side = QWidget()
    sl = QVBoxLayout(side)
    sl.setContentsMargins(0, 0, 0, 0)
    sl.setSpacing(6)
    # 主题 QSS 是给主程序大窗口写的，这里整体压一档（字号 + 分组留白）
    side.setStyleSheet(
        "QGroupBox{font-size:11px; margin-top:6px; padding-top:10px;}"
        "QLabel{font-size:11px;}"
        "QComboBox,QCheckBox,QPushButton{font-size:11px;}"
        "QGroupBox::title{subcontrol-origin:margin; left:6px;}")

    def slider(parent, lo, hi, val, step=1, fmt_="%.2f"):
        s = QSlider(Qt.Horizontal)
        s.setFixedHeight(14)
        s.setRange(int(lo / step), int(hi / step))
        s.setValue(int(round(val / step)))
        lbl = QLabel(fmt_ % val)
        lbl.setMinimumWidth(34)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(s, 1)
        row.addWidget(lbl)
        w = QWidget()
        w.setLayout(row)
        return w, s, lbl, step, fmt_

    grp_mat = QGroupBox("材质（实时改 uniform）")
    fm = QFormLayout(grp_mat)
    fm.setSpacing(4)
    fm.setContentsMargins(8, 4, 8, 6)
    cb_model = QComboBox()
    cb_model.addItems(["Blinn-Phong 双瓣", "GGX 微表面", "Clear-coat 清漆"])
    cb_model.setCurrentIndex(1)
    fm.addRow("镜面模型", cb_model)
    w_spec, s_spec, l_spec, st1, f1 = slider(grp_mat, 0.0, 2.0, 0.50, step=0.01)
    fm.addRow("光泽(镜面强度)", w_spec)
    w_rough, s_rough, l_rough, st2, f2 = slider(grp_mat, 0.03, 1.0, 0.30, step=0.01)
    fm.addRow("粗糙度", w_rough)
    w_coat, s_coat, l_coat, st3, f3 = slider(grp_mat, 0.03, 1.0, 0.10, step=0.01)
    fm.addRow("清漆粗糙度", w_coat)
    w_cstr, s_cstr, l_cstr, st4, f4 = slider(grp_mat, 0.0, 2.0, 0.80, step=0.01)
    fm.addRow("清漆强度", w_cstr)
    w_soft, s_soft, l_soft, st5, f5 = slider(grp_mat, 0.0, 1.0, 0.0, step=0.01)
    fm.addRow("明暗柔和度", w_soft)
    w_sss, s_sss, l_sss, st6, f6 = slider(grp_mat, 0.0, 1.0, 0.0, step=0.01)
    fm.addRow("次表面散射", w_sss)
    sl.addWidget(grp_mat)

    grp_light = QGroupBox("光照 / 背景")
    fl = QFormLayout(grp_light)
    fl.setSpacing(4)
    fl.setContentsMargins(8, 4, 8, 6)
    w_ln, s_ln, l_ln, st7, f7 = slider(grp_light, 1, 4, 3, step=1, fmt_="%d")
    fl.addRow("灯数", w_ln)
    chk_hemi = QCheckBox("半球环境光")
    chk_hemi.setChecked(True)
    fl.addRow("", chk_hemi)
    cb_bg = QComboBox()
    cb_bg.addItems(["白", "浅灰", "深灰"])
    fl.addRow("背景", cb_bg)
    # 只给 4× / 关闭两档：WebGPU 对 rgba8unorm **只保证 1 和 4 采样**，
    # 2× 在没有 TEXTURE_ADAPTER_SPECIFIC_FORMAT_FEATURES 时会直接校验失败
    cb_aa = QComboBox()
    cb_aa.addItems(["4× MSAA", "关闭"])
    cb_aa.setCurrentIndex(0)
    cb_aa.setToolTip("大网格 + WBOIT 吃的是带宽；卡顿时关掉抗锯齿")
    fl.addRow("抗锯齿", cb_aa)
    w_fog, s_fog, l_fog, st8, f8 = slider(grp_light, 0.0, 12.0, 0.0, step=0.05,
                                          fmt_="%.2f")
    fl.addRow("雾化宽度", w_fog)
    sl.addWidget(grp_light)

    # ── 等值面：控件一直建着，非 cub 场景时整组隐藏（载入 cub 后再显示）──
    state = {"cube": cube, "path": cube_path}
    grp_iso = QGroupBox("轨道等值面（WBOIT）")
    fl2 = QFormLayout(grp_iso)
    fl2.setSpacing(4)
    fl2.setContentsMargins(8, 4, 8, 6)
    w_iso, s_iso, l_iso, st_iso, f_iso = slider(grp_iso, 0.005, 0.30, 0.05,
                                                step=0.005, fmt_="%.3f")
    fl2.addRow("等值面数值", w_iso)
    w_op, s_op, l_op, st_op, f_op = slider(grp_iso, 0.05, 1.0, 0.78, step=0.01)
    fl2.addRow("不透明度", w_op)
    w_fo, s_fo, l_fo, st_fo, f_fo = slider(grp_iso, 0.0, 12.0, 4.0, step=0.05)
    fl2.addRow("深度衰减", w_fo)

    phase = {"pos": (0.10, 0.80, 0.10), "neg": (0.90, 0.25, 0.25)}

    def _swatch_qss(rgb):
        r, g, b = (int(round(c * 255)) for c in rgb)
        return (f"QPushButton {{background-color: rgb({r},{g},{b});"
                f" border: 1px solid #9AA7B8; border-radius: 13px;}}")

    btn_pos = QPushButton()
    btn_pos.setFixedSize(22, 22)
    btn_pos.setStyleSheet(_swatch_qss(phase["pos"]))
    btn_neg = QPushButton()
    btn_neg.setFixedSize(22, 22)
    btn_neg.setStyleSheet(_swatch_qss(phase["neg"]))
    row_ph = QHBoxLayout()
    row_ph.addWidget(QLabel("正相位"))
    row_ph.addWidget(btn_pos)
    row_ph.addSpacing(10)
    row_ph.addWidget(QLabel("负相位"))
    row_ph.addWidget(btn_neg)
    row_ph.addStretch(1)
    w_ph = QWidget()
    w_ph.setLayout(row_ph)
    fl2.addRow("相位色", w_ph)

    btn_flip = QPushButton("翻转相位")
    lbl_tris = QLabel("—")
    row_bt = QHBoxLayout()
    row_bt.addWidget(btn_flip)
    row_bt.addWidget(lbl_tris)
    w_bt = QWidget()
    w_bt.setLayout(row_bt)
    fl2.addRow("", w_bt)
    sl.addWidget(grp_iso)
    grp_iso.setVisible(state["cube"] is not None)

    cur = {"pos": None, "neg": None}

    def _tile(surf, rgb):
        if surf is None:
            return
        n = 0 if surf.vertices is None else len(surf.vertices)
        if n:
            surf.colors = np.tile(np.array([*rgb, 1.0], np.float32), (n, 1))

    def _upload():
        renderer.set_iso([cur["pos"], cur["neg"]])
        lbl_tris.setText(f"{renderer.iso_tris} 三角")
        canvas.request_draw()

    def _rebuild_iso():
        """重跑 marching cubes（几十到几百毫秒，故放在防抖之后）。"""
        cb = state["cube"]
        if cb is None:
            return
        from molstudio.core.marching_cubes import marching_cubes as _mc
        val = max(1e-4, s_iso.value() * st_iso)
        t0 = time.perf_counter()
        cur["pos"] = _mc(cb, val, flip_normal=False)
        cur["neg"] = _mc(cb, -val, flip_normal=True)
        _tile(cur["pos"], phase["pos"])
        _tile(cur["neg"], phase["neg"])
        _upload()
        print(f"[i] iso={val:.4f} → {renderer.iso_tris} 三角 "
              f"（{(time.perf_counter() - t0) * 1000:.0f} ms）")

    debounce = QTimer()
    debounce.setSingleShot(True)
    debounce.setInterval(280)
    debounce.timeout.connect(_rebuild_iso)

    def _pick(kind):
        rgb = phase[kind]
        c = QColorDialog.getColor(
            QColor(*[int(round(v * 255)) for v in rgb]), win, "选择相位色")
        if not c.isValid():
            return
        phase[kind] = (c.redF(), c.greenF(), c.blueF())
        (btn_pos if kind == "pos" else btn_neg).setStyleSheet(
            _swatch_qss(phase[kind]))
        _tile(cur[kind], phase[kind])
        _upload()

    def _flip():
        phase["pos"], phase["neg"] = phase["neg"], phase["pos"]
        btn_pos.setStyleSheet(_swatch_qss(phase["pos"]))
        btn_neg.setStyleSheet(_swatch_qss(phase["neg"]))
        _tile(cur["pos"], phase["pos"])
        _tile(cur["neg"], phase["neg"])
        _upload()

    btn_pos.clicked.connect(lambda: _pick("pos"))
    btn_neg.clicked.connect(lambda: _pick("neg"))
    btn_flip.clicked.connect(_flip)

    def _on_iso_changed(*_):
        l_iso.setText(f_iso % (s_iso.value() * st_iso))
        debounce.start()

    s_iso.valueChanged.connect(_on_iso_changed)
    s_op.valueChanged.connect(lambda *_: apply_params())
    s_fo.valueChanged.connect(lambda *_: apply_params())
    # 首帧前把已算好的两片装进去（main 里已算过一次，这里复用）
    cur["pos"], cur["neg"] = (iso or (None, None))
    lbl_tris.setText(f"{renderer.iso_tris} 三角")

    lbl_fps = QLabel("—")
    lbl_fps.setObjectName("ProgressLabel")
    info = QLabel(f"后端 {dict(adapter.info).get('backend_type')}\n"
                  f"原子 {len(atoms)} / 键 {len(bonds)}\n"
                  f"管线创建 {renderer.pipe_ms:.0f} ms")
    info.setWordWrap(True)
    info.setStyleSheet("color:#6B7280; font-size:11px;")
    sl.addWidget(lbl_fps)
    sl.addWidget(info)
    sl.addStretch(1)
    side.setFixedWidth(206)
    h.addWidget(side)
    root.addLayout(h, 1)
    win.setCentralWidget(central)
    if cube_path:
        lbl_file.setText(os.path.basename(cube_path))

    def _load(path=None):
        """载入 .cub/.cube（轨道）或 .fchk/.xyz（分子）。"""
        if not path:
            d = os.path.dirname(state["path"] or "") or os.getcwd()
            path, _f = QFileDialog.getOpenFileName(
                win, "载入轨道 / 分子文件", d,
                "轨道/分子 (*.cub *.cube *.fchk *.fch *.xyz);;所有文件 (*.*)")
            if not path:
                return
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext in (".cub", ".cube"):
                a2, b2, cb, pos, neg = load_cube_scene(
                    path, max(1e-4, s_iso.value() * st_iso),
                    phase["pos"], phase["neg"])
                state["cube"], state["path"] = cb, path
                cur["pos"], cur["neg"] = pos, neg
                _upload()
                grp_iso.setVisible(True)
                surfs = [pos, neg]
            else:
                a2, b2 = load_molecule(path)
                state["cube"], state["path"] = None, path
                cur["pos"] = cur["neg"] = None
                renderer.set_iso([])
                grp_iso.setVisible(False)
                surfs = None
        except Exception as exc:                       # 解析/网格失败不能把窗口带崩
            lbl_file.setText(f"载入失败：{exc}")
            print(f"[!] 载入失败：{exc!r}")
            return
        renderer.set_mol(a2, b2)
        cam.fit(*scene_bounds(a2, surfs))
        info.setText(f"后端 {dict(adapter.info).get('backend_type')}\n"
                     f"原子 {len(a2)} / 键 {len(b2)}\n"
                     f"管线创建 {renderer.pipe_ms:.0f} ms")
        lbl_file.setText(os.path.basename(path))
        canvas.request_draw()

    btn_open.clicked.connect(lambda: _load())

    def apply_params():
        p = renderer.params
        p["spec_model"] = float(cb_model.currentIndex())
        p["spec_str"] = s_spec.value() * st1
        p["roughness"] = s_rough.value() * st2
        p["coat_rough"] = s_coat.value() * st3
        p["coat_str"] = s_cstr.value() * st4
        p["soft_term"] = s_soft.value() * st5
        p["sss"] = s_sss.value() * st6
        p["light_count"] = float(s_ln.value())
        p["hemi"] = chk_hemi.isChecked()
        p["fog_width"] = s_fog.value() * st8
        for s, lbl, st, fx in ((s_spec, l_spec, st1, f1), (s_rough, l_rough, st2, f2),
                               (s_coat, l_coat, st3, f3), (s_cstr, l_cstr, st4, f4),
                               (s_soft, l_soft, st5, f5), (s_sss, l_sss, st6, f6),
                               (s_ln, l_ln, st7, f7), (s_fog, l_fog, st8, f8)):
            lbl.setText(fx % (s.value() * st))
        renderer.clear = ((1.0, 1.0, 1.0, 1.0), (0.93, 0.94, 0.96, 1.0),
                          (0.16, 0.18, 0.22, 1.0))[cb_bg.currentIndex()]
        if grp_iso is not None:
            # 轨道的 DiffuseColor：RGB 恒白，**.a = 不透明度**
            renderer.diffuse_iso = (1.0, 1.0, 1.0,
                                    max(0.0, min(1.0, s_op.value() * st_op)))
            p["oit_falloff"] = s_fo.value() * st_fo
            l_op.setText(f_op % (s_op.value() * st_op))
            l_fo.setText(f_fo % (s_fo.value() * st_fo))

    for w, s, lbl, st, fx in ((w_spec, s_spec, l_spec, st1, f1),
                              (w_rough, s_rough, l_rough, st2, f2),
                              (w_coat, s_coat, l_coat, st3, f3),
                              (w_cstr, s_cstr, l_cstr, st4, f4),
                              (w_soft, s_soft, l_soft, st5, f5),
                              (w_sss, s_sss, l_sss, st6, f6),
                              (w_ln, s_ln, l_ln, st7, f7),
                              (w_fog, s_fog, l_fog, st8, f8)):
        s.valueChanged.connect(lambda *_: apply_params())
    cb_model.currentIndexChanged.connect(lambda *_: apply_params())
    chk_hemi.toggled.connect(lambda *_: apply_params())
    cb_bg.currentIndexChanged.connect(lambda *_: apply_params())

    def _on_aa(i):
        # 采样数烘焙在管线里 → 重建管线 + 目标（约百来毫秒，仅在切换时）
        renderer.set_samples((4, 1)[i])
        canvas.request_draw()

    cb_aa.currentIndexChanged.connect(_on_aa)
    apply_params()

    # ── 交互 ──
    st = {"drag": None, "x": 0.0, "y": 0.0}

    def on_down(ev):
        st["drag"] = ev.get("button", 1)
        st["x"], st["y"] = ev["x"], ev["y"]

    def on_up(ev):
        st["drag"] = None

    def on_move(ev):
        if st["drag"] is None:
            return
        dx, dy = ev["x"] - st["x"], ev["y"] - st["y"]
        st["x"], st["y"] = ev["x"], ev["y"]
        if st["drag"] == 1:
            cam.yaw += dx * 0.45
            cam.pitch = max(-89.0, min(89.0, cam.pitch + dy * 0.45))
        else:
            cam.pan[0] += dx / 400.0
            cam.pan[1] -= dy / 400.0
        canvas.request_draw()

    def on_wheel(ev):
        cam.zoom *= math.pow(1.0015, ev.get("dy", 0))
        cam.zoom = max(0.15, min(8.0, cam.zoom))
        canvas.request_draw()

    def on_dbl(ev):
        cam.reset()
        canvas.request_draw()

    def on_key(ev):
        if str(ev.get("key", "")).lower() == "r":
            cam.reset()
            canvas.request_draw()

    canvas.add_event_handler(on_down, "pointer_down")
    canvas.add_event_handler(on_up, "pointer_up")
    canvas.add_event_handler(on_move, "pointer_move")
    canvas.add_event_handler(on_wheel, "wheel")
    canvas.add_event_handler(on_dbl, "double_click")
    canvas.add_event_handler(on_key, "key_down")

    # ── 每帧 ──
    fps = {"t": time.perf_counter(), "n": 0}

    def on_draw():
        w, hh = canvas.get_physical_size()
        renderer.ensure_targets(w, hh)
        tex = context.get_current_texture()
        enc = device.create_command_encoder()
        renderer.encode(enc, tex.create_view(), cam.mvp(w / max(1, hh)),
                        cam.rotation(), w, hh)
        device.queue.submit([enc.finish()])
        fps["n"] += 1
        now = time.perf_counter()
        if now - fps["t"] >= 0.5:
            lbl_fps.setText(f"{fps['n'] / (now - fps['t']):.0f} FPS  "
                            f"{w}×{hh}")
            fps["t"], fps["n"] = now, 0

    canvas.set_update_mode("continuous", max_fps=120)
    canvas.request_draw(on_draw)
    win.resize(900, 620)
    win.show()
    print("[i] 窗口已打开：左键旋转 / 滚轮缩放 / 右键平移 / 双击或 R 复位")
    if auto_close > 0:
        QTimer.singleShot(int(auto_close * 1000), app.quit)
    app.exec_()
    if auto_close > 0:
        print(f"[i] 自检结束（自动关闭）：{lbl_fps.text()}")


# ══════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description="独立 wgpu 分子查看器")
    ap.add_argument("file", nargs="?", default=None,
                    help=".cub/.cube（轨道等值面）/ .fchk / .xyz（省略则用内置苯分子）")
    ap.add_argument("--backend", default=None,
                    help="vulkan / d3d12 / opengl / cpu（默认高性能自动）")
    ap.add_argument("--iso", type=float, default=0.05,
                    help="cub 的等值面数值（默认 0.05）")
    ap.add_argument("--headless", type=int, default=0, metavar="N",
                    help="不开窗口，离屏渲 N 帧存 PNG（自检）")
    ap.add_argument("--self-test", type=float, default=0.0, metavar="SEC",
                    help="开窗自动关闭（跑 SEC 秒，用于确认画布可用）")
    args = ap.parse_args()

    print("[i] 适配器：")
    adapter, device = open_device(args.backend)
    cube = None
    iso = None
    ext = os.path.splitext(args.file or "")[1].lower()
    if ext in (".cub", ".cube"):
        atoms, bonds, cube, pos, neg = load_cube_scene(args.file, args.iso)
        iso = [pos, neg]
    else:
        atoms, bonds = load_molecule(args.file)
    if args.headless:
        run_headless(device, atoms, bonds, iso, args.headless, "_wgpu_view_out.png")
    else:
        run_gui(device, adapter, atoms, bonds, cube=cube, iso=iso,
                cube_path=args.file if cube is not None else None,
                auto_close=args.self_test)


if __name__ == "__main__":
    main()
