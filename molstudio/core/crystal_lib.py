#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GXNU MolStudio 晶体可视化 Demo —— CIF / POSCAR → 球棍模型。

球棍模型直接用 MolStudio 的 OpenGL 画布（`ovcanvas.OVCanvas`）：同一套
IboView 移植渲染管线、同一套一键样式（sob-art / IBOview / MolStudio /
HoukMol / CYLview / IQmol…），所以观感与主程序完全一致。

本文件只做晶体相关的三件事：
  ① 解析 CIF（含对称操作展开）与 VASP POSCAR，得到晶胞 + 分数坐标；
  ② 按需复制成超胞（晶胞边界上的键才不会断）；并把**落在晶胞边界上的原子
     在所有等价位置补齐**（bcc 铁 = 8 个顶点 + 体心，fcc = 8 顶点 + 6 面心），
     这是晶体学的习惯画法；同时给出晶胞框的 8 个顶点；
  ③ 把原子塞进画布 + 用 QPainter 叠加画出晶胞框。

用法::

    python crystal_demo.py                 # 打开窗口，点「载入 CIF / POSCAR…」
    python crystal_demo.py 结构.cif        # 启动即载入
    python crystal_demo.py POSCAR
"""

import math
import os
import re
import sys
import types

import numpy as np

# 直接运行调用方脚本时把仓库根目录加入 sys.path（包方式导入不需要）
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtCore import QPointF  # noqa: E402
from PyQt5.QtGui import QColor, QPainter, QPen, QSurfaceFormat  # noqa: E402
from PyQt5.QtWidgets import QWidget                # noqa: E402

from molstudio.render.ovcanvas._glwidget import (  # noqa: E402
    BOHR_TO_ANGSTROM, CubGLWidget, _COV_RADII_BOHR)

# 说明：本模块只放"纯逻辑"（解析 / 晶胞 / 晶胞框叠加），不设置 GL 默认格式、
# 不建 QApplication —— 那些是 demo（crystal_demo.py）或主程序自己的事。

# ── 元素符号（1..103）─────────────────────────────────────────────────
ELEMENTS = (
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co "
    "Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb "
    "Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re "
    "Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es "
    "Fm Md No Lr").split()
Z_OF = {s: i + 1 for i, s in enumerate(ELEMENTS)}


def element_symbol(txt):
    """从 'C1' / 'Cu2+' / 'OW' 之类的标签里取元素符号。"""
    m = re.match(r"([A-Za-z]{1,2})", str(txt).strip())
    if not m:
        return "X"
    s = m.group(1)
    for cand in (s.capitalize(), s[0].upper()):
        if cand in Z_OF:
            return cand
    return s.capitalize()


def _num(tok, default=0.0):
    """CIF 数值：去掉不确定度括号（18.5498(14) → 18.5498）。

    CIF 里未知值写作 `?`（无法确定）或 `.`（不适用）—— 这类值**不能**当 0 用
    （会把原子搬到原点），所以返回 None 交给调用方处理。
    """
    s = str(tok).strip().strip("'\"")
    if s in ("?", ".", ""):
        return None
    try:
        return float(re.sub(r"\(.*?\)", "", s))
    except (TypeError, ValueError):
        return default


# ── ① CIF ────────────────────────────────────────────────────────────

def _cif_split_row(s):
    """按 CIF 规则切一行：单引号/双引号里的内容算一个字段。"""
    out, i, n = [], 0, len(s)
    while i < n:
        while i < n and s[i].isspace():
            i += 1
        if i >= n:
            break
        if s[i] in "'\"":
            q = s[i]
            j = s.find(q, i + 1)
            j = n if j < 0 else j
            out.append(s[i + 1:j])
            i = j + 1
        else:
            j = i
            while j < n and not s[j].isspace():
                j += 1
            out.append(s[i:j])
            i = j
    return out


def _cif_records(text):
    """把 CIF 拆成 ("item", tag, value) 与 ("loop", headers, rows)。"""
    lines = [ln.split("#", 1)[0].rstrip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln.strip()]
    i, n = 0, len(lines)
    while i < n:
        s = lines[i].strip()
        if s.lower() == "loop_":
            i += 1
            headers = []
            while i < n and lines[i].strip().startswith("_"):
                headers.append(lines[i].strip())
                i += 1
            rows, cur = [], []
            while i < n:
                t = lines[i].strip()
                if (t.startswith("_") or t.lower() == "loop_"
                        or t.lower().startswith("data_")):
                    break
                cur += _cif_split_row(t)
                while headers and len(cur) >= len(headers):
                    rows.append(cur[:len(headers)])
                    cur = cur[len(headers):]
                i += 1
            if headers:
                yield ("loop", headers, rows)
        elif s.startswith("_"):
            parts = s.split(None, 1)
            if len(parts) > 1:
                i += 1
                yield ("item", parts[0], parts[1].strip())
            else:                       # 值在下一行
                val = lines[i + 1].strip() if i + 1 < n else ""
                i += 2
                yield ("item", parts[0], val)
        else:
            i += 1


def _symop_component(comp, xyz):
    """算对称操作的一个分量，例如 '1/2-x' / '+y' / '2/3+z'。"""
    total = 0.0
    for term in re.findall(r"[+-]?[^+-]+", comp.replace(" ", "")):
        if not term:
            continue
        sign = 1.0
        if term[0] == "+":
            term = term[1:]
        elif term[0] == "-":
            sign, term = -1.0, term[1:]
        low = term.lower()
        if low in ("x", "y", "z"):
            total += sign * xyz[low]
        elif "/" in term:
            a, b = term.split("/", 1)
            try:
                total += sign * float(a) / float(b)
            except (ValueError, ZeroDivisionError):
                pass
        elif term:
            total += sign * _num(term)
    return total


def _apply_symop(op, frac):
    comps = [c for c in str(op).split(",")][:3]
    while len(comps) < 3:
        comps.append("0")
    xyz = {"x": frac[0], "y": frac[1], "z": frac[2]}
    return tuple(_symop_component(c, xyz) % 1.0 for c in comps)


def _parse_cif_block(text):
    """解析单个 data_ 块 → (cell, sites)；缺晶胞或缺原子时返回 (None, [])。"""
    cell, symops, sites, cart_sites = {}, [], [], []
    for rec in _cif_records(text):
        if rec[0] == "item":
            tag, val = rec[1].lower(), rec[2]
            key = {"_cell_length_a": "a", "_cell_length_b": "b",
                   "_cell_length_c": "c", "_cell_angle_alpha": "alpha",
                   "_cell_angle_beta": "beta", "_cell_angle_gamma": "gamma"}.get(tag)
            if key:
                v = _num(val)
                if v is not None:
                    cell[key] = v
            elif tag in ("_symmetry_equiv_pos_as_xyz",
                         "_space_group_symop_operation_xyz"):
                symops.append(val.strip("'\""))
        else:
            heads = [h.lower() for h in rec[1]]
            rows = rec[2]
            if any(h.startswith("_space_group_symop") or
                   h == "_symmetry_equiv_pos_as_xyz" for h in heads):
                idx = 0
                for h in heads:
                    if h.startswith("_space_group_symop") or \
                            h == "_symmetry_equiv_pos_as_xyz":
                        break
                    idx += 1
                symops += [r[idx].strip("'\"") for r in rows if len(r) > idx]
            elif any(h.startswith("_atom_site_") for h in heads):
                col = {h: k for k, h in enumerate(heads)}
                for r in rows:
                    def get(*names):
                        for nm in names:
                            k = col.get(nm)
                            if k is not None and k < len(r):
                                return r[k]
                        return None
                    sym = get("_atom_site_type_symbol", "_atom_site_label")
                    fx = get("_atom_site_fract_x")
                    fy = get("_atom_site_fract_y")
                    fz = get("_atom_site_fract_z")
                    if fx is not None:
                        f = (_num(fx), _num(fy), _num(fz))
                        if None in f:          # 坐标是 ?/. （未定）→ 跳过该位点
                            continue
                        sites.append((element_symbol(sym), f))
                    else:
                        cx = get("_atom_site_cartn_x")
                        if cx is not None:
                            c = (_num(cx), _num(get("_atom_site_cartn_y")),
                                 _num(get("_atom_site_cartn_z")))
                            if None in c:
                                continue
                            cart_sites.append((element_symbol(sym), c))
    a = cell.get("a", 0.0)
    b = cell.get("b", a)
    c = cell.get("c", a)
    al = cell.get("alpha", 90.0)
    be = cell.get("beta", 90.0)
    ga = cell.get("gamma", 90.0)
    if a <= 0 or not (sites or cart_sites):
        return None, []

    if cart_sites:                       # 只有笛卡尔坐标时转成分数坐标
        M = cell_matrix(a, b, c, al, be, ga)
        Minv = np.linalg.inv(M)
        for sym, xyz in cart_sites:
            fr = Minv @ np.asarray(xyz, dtype=float)
            sites.append((sym, tuple(fr % 1.0)))

    if not sites:
        return None, []

    if not symops:                       # 没写对称操作 → 按 P1 处理
        symops = ["x,y,z"]
    out, seen = [], set()
    for sym, frac in sites:
        for op in symops:
            f = _apply_symop(op, frac)
            key = (sym,) + tuple(round(v, 3) % 1.0 for v in f)
            if key in seen:
                continue
            seen.add(key)
            out.append((sym, f))
    return (a, b, c, al, be, ga), out


def parse_cif(text):
    """→ (cell=(a,b,c,α,β,γ), [(符号, (fx,fy,fz)), ...])（已按对称操作展开）。

    CIF 可能含多个 `data_` 块（补充材料里很常见）——逐块试，取**第一个
    既有晶胞参数又有原子坐标**的块，避免把几套结构的参数和原子混在一起。
    """
    blocks, cur = [], []
    for ln in text.splitlines():
        if ln.lstrip().lower().startswith("data_") and cur:
            blocks.append("\n".join(cur))
            cur = []
        cur.append(ln)
    if cur:
        blocks.append("\n".join(cur))
    err = None
    for blk in (blocks or [text]):
        try:
            cell, sites = _parse_cif_block(blk)
        except Exception as e:               # 单块解析失败不影响其它块
            err = e
            continue
        if cell and sites:
            return cell, sites
    # 报错要说清"缺什么"，否则用户不知道是文件不对还是解析器不支持
    low = text.lower()
    missing = []
    if "_cell_length_a" not in low:
        missing.append("晶胞参数 _cell_length_a/b/c + _cell_angle_*")
    if "_atom_site_fract_" not in low and "_atom_site_cartn_" not in low:
        missing.append("原子坐标 _atom_site_fract_x/y/z（或 _atom_site_Cartn_*）")
    if not missing:
        missing.append("可用的原子坐标（坐标可能全是 ?/. 未定值）")
    raise ValueError(
        "这个 .cif 里没读到结构：缺 " + "、".join(missing)
        + "。若文件本身是价键参数/仪器参数之类的表（不含原子坐标），"
          "请改用结构 CIF；也支持 VASP 的 POSCAR / CONTCAR。"
        + ("　[%s]" % err if err else ""))


# ── ② VASP POSCAR / CONTCAR ──────────────────────────────────────────

def parse_poscar(text):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 8:
        raise ValueError("POSCAR 内容不完整")
    scale = _num(lines[1].split()[0], 1.0)
    vecs = np.array([[_num(x) for x in lines[2 + i].split()[:3]]
                     for i in range(3)], dtype=float)
    if scale < 0:                        # 负数 = 目标体积
        vol = abs(scale)
        scale = (vol / max(abs(np.linalg.det(vecs)), 1e-12)) ** (1.0 / 3.0)
    vecs *= scale
    i = 5
    head = lines[i].split()
    if all(re.fullmatch(r"[A-Za-z]{1,2}", t) for t in head):
        syms, i = [element_symbol(t) for t in head], i + 1
    else:
        syms = []
    counts = [int(float(t)) for t in lines[i].split()]
    i += 1
    if lines[i].strip().lower().startswith("s"):     # Selective dynamics
        i += 1
    mode = lines[i].strip().lower()
    i += 1
    if not syms:                         # VASP4 没有元素名行 → 没法上色/判键
        raise ValueError("POSCAR 缺少元素符号行（VASP 4 格式）。请改用 VASP 5 "
                         "格式（第 6 行写元素名），或在 CONTCAR 里补这一行。")
    expand = []
    for s, c in zip(syms, counts):
        expand += [s] * c
    coords = []
    for k in range(sum(counts)):
        if i + k >= len(lines):
            break
        coords.append([_num(x) for x in lines[i + k].split()[:3]])
    cart = mode.startswith(("c", "k"))
    if cart:
        fr = np.asarray(coords, dtype=float) @ np.linalg.inv(vecs)
    else:
        fr = np.asarray(coords, dtype=float)
    sites = [(s, tuple(f % 1.0)) for s, f in zip(expand, fr)]
    return vecs, sites


# ── ③ 晶胞矩阵 / 笛卡尔坐标 / 超胞 ───────────────────────────────────

# ── MOL2（Tripos）────────────────────────────────────────────────────

def parse_mol2(text):
    """解析 Tripos MOL2 的 @<TRIPOS>ATOM 块 → [(元素, (x, y, z)[Å]), ...]。

    MOL2 是**分子**结构（没有晶胞），原子行形如：
        1  C1  1.2079  2.1200  0.0000  C.3  1  LIG  0.0338
    元素判定顺序：type 段（"C.3"→C、"Cl"→Cl、"N.pl3"→N、"S.o"→S）→ name 段
    （"CL1"→Cl）。两个都认不出时按碳处理，避免渲染成空球。
    """
    atoms = []
    in_atom = False
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("@<TRIPOS>"):
            in_atom = s.upper().startswith("@<TRIPOS>ATOM")
            continue
        if not in_atom or not s:
            continue
        p = s.split()
        if len(p) < 6:
            continue
        try:
            xyz = (float(p[2]), float(p[3]), float(p[4]))
        except ValueError:
            continue
        sym = element_symbol(p[5])
        if sym not in Z_OF:
            sym = element_symbol(p[1])
        if sym not in Z_OF:
            sym = "C"
        atoms.append((sym, xyz))
    if not atoms:
        raise ValueError("这个 .mol2 里没读到 @<TRIPOS>ATOM 原子块"
                         "（也可能是用 -c 之类的选项导出的空文件）")
    return atoms


def cell_matrix(a, b, c, al, be, ga):
    """标准晶体学取向：a 沿 x，b 在 xy 面内。行 = 晶格矢量（Å）。"""
    al, be, ga = math.radians(al), math.radians(be), math.radians(ga)
    ca, cb, cg = math.cos(al), math.cos(be), math.cos(ga)
    sg = math.sin(ga)
    cx = c * cb
    cy = c * (ca - cb * cg) / sg if abs(sg) > 1e-9 else 0.0
    cz = math.sqrt(max(c * c - cx * cx - cy * cy, 0.0))
    return np.array([[a, 0.0, 0.0],
                     [b * cg, b * sg, 0.0],
                     [cx, cy, cz]], dtype=float)


class Crystal:
    """晶体（晶胞 + 分数坐标，可展开成超胞）**或**分子（MOL2，笛卡尔坐标）。

    分子走同一套接口：`is_molecule=True`、`cart` 存 (元素, (x,y,z))，
    `supercell()` 直接返回它本身（不复制），`cell_corners()` 返回空（没晶胞框）。
    """

    def __init__(self, vecs=None, sites=None, source="", cell=None, cart=None):
        self.is_molecule = cart is not None
        self.cart = list(cart) if cart is not None else []
        self.vecs = (None if self.is_molecule
                     else np.asarray(vecs, dtype=float))
        if self.is_molecule:
            sites = [(s, (0.0, 0.0, 0.0)) for s, _ in self.cart]
        self.sites = list(sites)
        self.source = source
        self.cell = cell

    @classmethod
    def from_file(cls, path):
        text = open(path, encoding="utf-8", errors="replace").read()
        name = os.path.basename(path)
        head = os.path.basename(path).lower()
        if head.endswith(".mol2"):
            return cls(cart=parse_mol2(text), source=name)
        if head.endswith(".cif"):
            cell, sites = parse_cif(text)
            a, b, c, al, be, ga = cell
            return cls(cell_matrix(a, b, c, al, be, ga), sites, name, cell)
        if head.endswith((".vasp", ".poscar")) or head in ("poscar", "contcar"):
            vecs, sites = parse_poscar(text)
            return cls(vecs, sites, name)
        # 其它扩展名：先按 CIF 试，再按 POSCAR 试
        for fn in (parse_cif, parse_poscar):
            try:
                out = fn(text)
            except Exception:
                continue
            if fn is parse_cif:
                cell, sites = out
                a, b, c, al, be, ga = cell
                return cls(cell_matrix(a, b, c, al, be, ga), sites, name, cell)
            return cls(out[0], out[1], name)
        raise ValueError("无法识别的晶体文件：%s" % name)

    @staticmethod
    def _boundary_images(f, tol=1e-3):
        """分数坐标落在晶胞边界（0/1）上时，补出所有等价位置的图像。

        晶体学的习惯画法：边界上的原子要在**每个等价位置**都出现，
        否则一个晶胞看着缺角。例如
          (0,0,0)        → 8 个顶点全画出来（bcc 的铁就是这样）
          (0.5,0.5,0)    → 上、下两个面的面心都画出来（fcc）
          (0.3,0.5,0.7)  → 不在边界，只有它自己
        判据按分数坐标 1e-3 容差（CIF 里常写 0.0000 / 1.0000）。
        """
        opts = []
        for v in f:
            v = float(v) % 1.0
            if v < tol or v > 1.0 - tol:
                opts.append((0.0, 1.0))
            else:
                opts.append((v,))
        return [(x, y, z) for x in opts[0] for y in opts[1] for z in opts[2]]

    # 超胞：offsets 取 -k..k，使原胞位于正中
    def supercell(self, na=1, nb=1, nc=1, fill_boundary=True):
        """→ [(idx, 元素, 原子序数, (x,y,z)[Å]), ...]

        fill_boundary=True 时把晶胞边界上的原子在等价位置补齐（见
        `_boundary_images`），并按坐标去重——超胞里相邻胞的原子会正好落在
        同一位置，不去重会出现"两个原子重叠"。
        """
        def offs(n):
            lo = -(n // 2)
            return list(range(lo, lo + n))
        if self.is_molecule:          # 分子（MOL2）：没有晶胞，原样返回
            return [(i + 1, s, Z_OF.get(s, 0), tuple(float(v) for v in xyz))
                    for i, (s, xyz) in enumerate(self.cart)]
        atoms, seen, idx = [], set(), 0
        M = self.vecs
        for ia in offs(na):
            for ib in offs(nb):
                for ic in offs(nc):
                    shift = ia * M[0] + ib * M[1] + ic * M[2]
                    for sym, f in self.sites:
                        images = (self._boundary_images(f) if fill_boundary
                                  else (tuple(float(v) for v in f),))
                        for ff in images:
                            cart = np.asarray(ff, dtype=float) @ M + shift
                            key = (sym, round(cart[0], 3), round(cart[1], 3),
                                   round(cart[2], 3))
                            if key in seen:
                                continue
                            seen.add(key)
                            idx += 1
                            atoms.append((idx, sym, Z_OF.get(sym, 0),
                                          tuple(float(v) for v in cart)))
        return atoms

    def cell_corners(self):
        """原胞 8 个顶点（Å），行 = A/B/C 的组合。"""
        if self.is_molecule:
            return []
        return [i * self.vecs[0] + j * self.vecs[1] + k * self.vecs[2]
                for i in (0, 1) for j in (0, 1) for k in (0, 1)]

    @staticmethod
    def cell_edges():
        """8 顶点（i,j,k 二进制的顺序）之间的 12 条棱。"""
        e = []
        for p in range(8):
            for q in range(p + 1, 8):
                d = bin(p ^ q).count("1")
                if d == 1:
                    e.append((p, q))
        return e


# ── ④ 晶胞框叠加（画在 GL 场景之上）───────────────────────────────────

def install_cell_box(glw, corners_provider, color=(70, 80, 95, 165)):
    """给画布挂一个 2D 叠加：把晶胞 12 条棱投影后画成线。

    做法与画布自己的 `_draw_mol_overlay` 一致（QPainter 叠加），只是换了
    绘制内容；坐标要换算成画布内部使用的 Bohr。

    ★ 整段绘制包在 try/except 里：这是在 QOpenGLWidget 的 paintGL 回调链上
      跑，**任何** Python 异常抛回去都会被 PyQt 判为致命并直接 abort 进程
      （实测：主程序里切到晶体页后一帧内整进程消失，无 traceback）。
      叠加层画不出来最多是"没框"，绝不该拖垮程序，所以这里只提示一次。
    """
    edges = Crystal.cell_edges()
    warned = []

    def wrapper(self, p=None, w0=None, h0=None):
        # 先用类方法画原本的叠加层（不捕获变量：避免万一被重复包装时自我递归）
        CubGLWidget._draw_mol_overlay(self, p, w0, h0)
        try:
            pts = corners_provider()
            if not pts:
                return
            own = p is None
            q = p if p is not None else QPainter(self)
            try:
                q.setRenderHint(QPainter.Antialiasing)
                q.setPen(QPen(QColor(*color), 1.2))
                w = w0 if w0 else max(1, self.width())
                h = h0 if h0 else max(1, self.height())
                scr = []
                for c in pts:
                    c = np.asarray(c, dtype=float) / BOHR_TO_ANGSTROM
                    scr.append(self._world_to_screen(float(c[0]), float(c[1]),
                                                     float(c[2]), w, h))
                for i, j in edges:
                    if scr[i][2] or scr[j][2]:
                        q.drawLine(QPointF(scr[i][0], scr[i][1]),
                                   QPointF(scr[j][0], scr[j][1]))
            finally:
                if own:
                    q.end()
        except Exception as e:      # 绝不把异常抛回 Qt 的绘制回调
            if not warned:
                warned.append(True)
                print("[crystal] 晶胞框绘制失败（已忽略）: %s" % e)

    glw._draw_mol_overlay = types.MethodType(wrapper, glw)


# ── ⑤ 配位多面体 ─────────────────────────────────────────────────────
#: 同时显示的多面体上限（超大超胞里中心原子可能上千个；超过就只画前 N 个）
MAX_POLYHEDRA = 600


def _planar_faces(verts):
    """共面配位的兜底三角化（平面四方 / 三角平面等）。

    做法与画布"平面填充"一致：SVD 求最佳拟合平面 → 投影到平面内 2D → 凸包 →
    围绕质心扇形三角化。返回 (顶点数组, 三角形列表)，不共面/退化时返回 None。
    """
    try:
        from scipy.spatial import ConvexHull
    except Exception:
        return None
    ctr = verts.mean(axis=0)
    rel = verts - ctr
    try:
        _u, _s, vt = np.linalg.svd(rel, full_matrices=False)
        p2 = np.stack([rel @ vt[0], rel @ vt[1]], axis=1)
        hull = ConvexHull(p2)
        order = [int(i) for i in hull.vertices]      # 逆时针一圈
    except Exception:
        return None
    if len(order) < 3:
        return None
    hull3 = np.asarray([verts[i] for i in order], dtype=np.float64)
    fan = np.vstack([[ctr], hull3])
    tris = []
    m = len(hull3)
    for k in range(1, m):
        tris.append((0, k, k + 1))
    tris.append((0, m, 1))
    return fan, tris


def coordination_polyhedra(atoms, center_z, rf=1.3, max_dist=3.5,
                           min_nbrs=3, max_nbrs=16, limit=MAX_POLYHEDRA):
    """找 `center_z` 元素原子的配位多面体（配位原子的凸包）。

    atoms:    `Crystal.supercell()` 的返回值 [(idx, 元素符号, 原子序数, (x,y,z) Å)]，
              要传**渲染用的那一份**（已按扩胞/边界补齐生成），质心与配位才与
              屏幕上看到的结构一致；否则晶胞边界上的多面体会缺角。
    rf:       配位判据系数：距离上限 = rf × (共价半径_c + 共价半径_n)。
              默认 1.3 —— 与画布"虚线键"阈值一致（Cordero 2008 共价半径）。
    max_dist: 绝对上限（Å），防止两个重原子半径和过大时误配。
    min/max_nbrs: 配位数范围；小于 3 不成面，大于 max_nbrs 视为异常（如中心选错）。
    limit:    最多返回多少个（按原子序号顺序）。

    返回 [{"center": i, "nbrs": [j...], "vertices": (N,3) float Å,
           "triangles": [(a,b,c), ...]}]（都是 Å；画布那侧换算成 Bohr）。

    注：① 与中心同种元素的近邻**不计入**配位（氧化物 MO6 不该把 O–O 算进去；
    金属团簇里 M–M 键因此不参与多面体）。② 三维配位用 scipy.spatial.ConvexHull
    做凸包；配位原子共面（平面四方 / 三角平面）时自动退回平面三角化
    （见 `_planar_faces`），共线或无 scipy 时该中心跳过。
    """
    if not atoms:
        return []
    try:
        from scipy.spatial import ConvexHull
    except Exception:           # 没 scipy 就不显示多面体（不报错）
        return []
    cov = [float(r) * BOHR_TO_ANGSTROM for r in _COV_RADII_BOHR]   # Bohr → Å

    def _r(z):
        z = int(z)
        return cov[z] if 0 <= z < len(cov) else 0.7

    zc = int(center_z)
    pos = np.asarray([a[3] for a in atoms], dtype=np.float64)
    anum = np.asarray([int(a[2]) for a in atoms], dtype=np.int64)
    centers = np.where(anum == zc)[0]
    if not len(centers):
        return []
    rc = _r(zc)
    rn = np.asarray([_r(z) for z in anum], dtype=np.float64)
    cut = np.minimum(rf * (rc + rn), float(max_dist))   # 与中心元素无关，只算一次
    out = []
    for i in centers:
        if len(out) >= int(limit):
            break
        d = np.linalg.norm(pos - pos[i], axis=1)
        sel = np.where((d > 1e-6) & (d <= cut))[0]
        nbrs = [int(j) for j in sel if anum[j] != zc]
        if not (min_nbrs <= len(nbrs) <= max_nbrs):
            continue
        verts = pos[nbrs]
        vout, tris = verts, None
        try:
            hull = ConvexHull(verts)
            tris = [tuple(int(k) for k in s) for s in hull.simplices]
        except Exception:
            # 共面（平面四方、三角平面……）或点数不足 → 用平面兜底
            planar = _planar_faces(verts)
            if planar is not None:
                vout, tris = planar
        if not tris:
            continue
        out.append({"center": int(i), "nbrs": nbrs, "vertices": vout,
                    "triangles": tris})
    return out


# ── ⑥ 主窗口 ────────────────────────────────────────────────────────

