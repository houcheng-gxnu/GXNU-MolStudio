# -*- coding: utf-8 -*-
"""
表面距离投影图（surface distance projection map）的计算与绘图核心。

功能对应卢天老师文章 http://sobereva.com/589 介绍的
Multiwfn 主功能 300 → 子功能 8。

分工要明确：**定量结果完全由 Multiwfn 计算**。本模块只做三件事：

  1. 把界面上的设置翻译成 Multiwfn 的命令序列，按 stdin 喂给它的进程；
  2. 解析它导出的 ``distmap.txt``（三列 X Y 值）；
  3. 把数据画成图（可选叠加原子投影）。

本模块刻意**不导入 matplotlib.pyplot**，由调用方决定后端：
面板里用 Qt5Agg 嵌进窗口，独立脚本里用 Agg 存文件。

关于 ``void``（轮廓外留白）：Multiwfn 对每个 (x,y) 从 Z_start 沿 -Z 扫描，
命中电子密度等值面才记下 Z'。若一路扫到 Z_end 仍未命中（该点落在分子轮廓
之外），它记下 Z_end，于是该点数值 = Z_end − Z_start，正好是全图最小值，
在 jet 色标里是最深的蓝。这不是"很深的表面"，而是"此处没有表面"，
所以默认把这些点留白（``void="bg"``）。
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

import numpy as np


# ─────────────────────────────────────────────────────────────────────────────
# 元素与结构文件读取
# ─────────────────────────────────────────────────────────────────────────────

#: 原子序数 → 元素符号（Multiwfn / Gaussian 日志里给的是原子序数）
ELEMENT_SYMBOLS = (
    "", "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne",
    "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar", "K", "Ca",
    "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
    "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr",
    "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn",
    "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd",
    "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb",
    "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
    "Tl", "Pb", "Bi", "Po", "At", "Rn", "Fr", "Ra", "Ac", "Th",
)


def element_symbol(z: int) -> str:
    """原子序数 → 元素符号；超出表范围时给出 X<序数>。"""
    return ELEMENT_SYMBOLS[z] if 0 < z < len(ELEMENT_SYMBOLS) else f"X{z}"


_ATOM_RE = re.compile(
    r"^\s*([A-Za-z]{1,3})\s+(-?\d+\.?\d*(?:[eEdD][-+]?\d+)?)"
    r"\s+(-?\d+\.?\d*(?:[eEdD][-+]?\d+)?)\s+(-?\d+\.?\d*(?:[eEdD][-+]?\d+)?)\s*$"
)
_CM_RE = re.compile(r"^\s*[+-]?\d+\s+[+-]?\d+\s*$")


def parse_gaussian_orientation(text: str):
    """取 Gaussian log/out 里最后一个 Standard/Input orientation 坐标表。

    返回 ``(symbols, coords)`` 或 ``None``。规则与 ``fchk_orbital.parse_log``
    一致：跳过表头前的分隔线，读到第三条分隔线为止（优化任务取最终结构）。
    """
    lines = text.splitlines()
    for i in range(len(lines) - 1, -1, -1):
        if ("Standard orientation:" not in lines[i]
                and "Input orientation:" not in lines[i]):
            continue
        symbols, coords = [], []
        dashes = 0
        j = i + 1
        while j < len(lines):
            line = lines[j]
            if line.strip().startswith("-----"):
                dashes += 1
                if dashes >= 3:
                    break
                j += 1
                continue
            if dashes == 2:
                parts = line.split()
                if len(parts) >= 6:
                    try:
                        znum = int(parts[1])
                        x, y, z = float(parts[3]), float(parts[4]), float(parts[5])
                    except (ValueError, IndexError):
                        j += 1
                        continue
                    symbols.append(element_symbol(znum))
                    coords.append((x, y, z))
            j += 1
        if symbols:
            return symbols, coords
    return None


def parse_orca_cartesian(text: str):
    """取 ORCA 输出里最后一个 CARTESIAN COORDINATES (ANGSTROEM) 块。"""
    lines = text.splitlines()
    for i in range(len(lines) - 1, -1, -1):
        if "CARTESIAN COORDINATES (ANGSTROEM)" not in lines[i].upper():
            continue
        symbols, coords = [], []
        for line in lines[i + 1:]:
            s = line.strip()
            if not s:
                if symbols:
                    break
                continue
            if s.startswith("-"):
                continue
            fields = s.split()
            if len(fields) >= 4 and fields[0][0].isalpha():
                try:
                    x, y, z = float(fields[1]), float(fields[2]), float(fields[3])
                except ValueError:
                    break
                symbols.append(fields[0])
                coords.append((x, y, z))
            elif symbols:
                break
        if symbols:
            return symbols, coords
    return None


def load_atoms(path):
    """读取 xyz / Gaussian gjf·com·log·out / ORCA out 的几何。

    返回 ``(symbols, coords)``（Å）。Gaussian 的 log/out 会被抽成几何 ——
    Multiwfn 读不了 log，喂给它之前必须先转成坐标文件。
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="ignore")
    suffix = path.suffix.lower()

    if suffix == ".xyz":
        lines = text.splitlines()
        n = int(lines[0].split()[0])
        symbols, coords = [], []
        for line in lines[2:2 + n]:
            p = line.split()
            symbols.append(p[0])
            coords.append([float(x) for x in p[1:4]])
        return symbols, np.asarray(coords, dtype=float)

    if suffix in (".gjf", ".com"):
        lines = text.splitlines()
        start = None
        for i, line in enumerate(lines):
            if _CM_RE.match(line):
                start = i + 1
                break
        if start is None:
            raise ValueError("gjf 里没找到电荷/多重度行，无法定位原子块")
        symbols, coords = [], []
        for line in lines[start:]:
            m = _ATOM_RE.match(line)
            if not m:
                break
            symbols.append(m.group(1))
            coords.append([float(m.group(2)), float(m.group(3)), float(m.group(4))])
        if not symbols:
            raise ValueError("gjf 原子块是空的")
        return symbols, np.asarray(coords, dtype=float)

    if suffix in (".log", ".out"):
        res = parse_gaussian_orientation(text) or parse_orca_cartesian(text)
        if res is None:
            raise ValueError(
                "在 log/out 里没找到坐标块（支持 Gaussian 的 Standard/Input "
                "orientation 与 ORCA 的 CARTESIAN COORDINATES）")
        symbols, coords = res
        return symbols, np.asarray(coords, dtype=float)

    raise ValueError(f"暂不支持的结构格式：{suffix}")


def write_xyz(path, symbols, coords, comment="MolStudio"):
    """把几何写成 xyz（Multiwfn 认，且能承接 log 抽出来的坐标）。"""
    coords = np.asarray(coords, dtype=float)
    lines = [str(len(symbols)), comment]
    for sym, (x, y, z) in zip(symbols, coords):
        lines.append(f"{sym:<4s}{x:>16.8f}{y:>16.8f}{z:>16.8f}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


# ─────────────────────────────────────────────────────────────────────────────
# 朝向
# ─────────────────────────────────────────────────────────────────────────────

def apply_orientation(coords, R):
    """把朝向 R 烘焙进坐标（绕质心转，避免转出扫描范围）。"""
    coords = np.asarray(coords, dtype=float)
    center = coords.mean(axis=0)
    return (coords - center) @ np.asarray(R, dtype=float).T + center


def rotation_matrix(ax_deg, ay_deg, az_deg):
    """Rx→Ry→Rz 复合旋转矩阵（度）。与界面显示的 --rot 角一致。"""
    ax, ay, az = np.radians([ax_deg, ay_deg, az_deg])
    cx, sx = np.cos(ax), np.sin(ax)
    cy, sy = np.cos(ay), np.sin(ay)
    cz, sz = np.cos(az), np.sin(az)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return rz @ ry @ rx


def euler_zyx_from_matrix(R):
    """把 R = Rz(g)·Ry(b)·Rx(a) 反解成 (a, b, g)（度），便于记录/复现朝向。"""
    R = np.asarray(R, dtype=float)
    b = np.arcsin(np.clip(-R[2, 0], -1.0, 1.0))
    a = np.arctan2(R[2, 1], R[2, 2])
    g = np.arctan2(R[1, 0], R[0, 0])
    return np.degrees([a, b, g])


def camera_rotation(glw):
    """读出 MolStudio 画布当前的朝向（世界 → 屏幕 的 3×3 旋转）。

    画布用的是 arcball 相机（``ovcanvas._glwidget.Camera``）：
    ``view()[:3,:3] = _q2m(q)``，正交投影且 +Z 指向观察者，
    因此屏幕平面就是投影面、屏幕法线就是 Multiwfn 的扫描方向。
    返回 ``None`` 表示拿不到朝向。
    """
    cam = getattr(glw, "cam", None)
    if cam is None:
        return None
    try:
        return np.asarray(cam.view(), dtype=float)[:3, :3]
    except Exception:                                             # noqa: BLE001
        return None


def atoms_from_canvas(glw):
    """从 MolStudio 画布读出当前显示的分子，返回 (symbols, coords/Å)。

    画布内部把坐标存成 Bohr（``self._molecule`` 每条为
    ``(原子序数, 电荷, x, y, z)``），这里换回 Å。
    直接读画布的好处：面板显示的一定和用户正在看的那个结构一致。
    """
    mol = getattr(glw, "_molecule", None)
    if not mol:
        return None
    ang = 1.0 / 1.8897261254578281          # Bohr → Å
    symbols, coords = [], []
    for rec in mol:
        symbols.append(element_symbol(int(rec[0])))
        coords.append((rec[2] * ang, rec[3] * ang, rec[4] * ang))
    return symbols, np.asarray(coords, dtype=float)


# ─────────────────────────────────────────────────────────────────────────────
# 驱动 Multiwfn
# ─────────────────────────────────────────────────────────────────────────────

def build_commands(surface="promol", iso=0.05, zstart=None, zend=None,
                   xrange=None, yrange=None, nx=None, ny=None,
                   zstep=None, ncontour=None, export_data=True):
    """把设置翻译成 Multiwfn 的 stdin 命令序列。

    菜单层级：主菜单 → 300（Other functions Part 3）→ 8（绘制距离投影图）
    →[设置]→ 0（开始计算）→ 后处理菜单 → -2（导出 distmap.txt）→ 逐层退出。
    ``zstart`` 可以是数字，也可以是 Multiwfn 支持的 ``"a 5"``（用 5 号原子的 Z）。
    """
    cmds = ["300", "8"]
    if surface:
        cmds.append("1")                     # Set definition of system surface
        if surface == "promol":              # 准分子密度等值面（推荐）
            cmds += ["1", f"{iso:g}"]
        elif surface == "wfn":               # 真实波函数密度等值面
            cmds += ["2", f"{iso:g}"]
        elif surface == "vdw":               # 原子范德华球叠加（iso 作半径系数）
            cmds += ["3", f"{iso:g}"]
        else:
            raise ValueError(f"未知的 surface 类型: {surface}")
    if xrange:
        cmds += ["2", f"{xrange[0]:g},{xrange[1]:g}"]
    if yrange:
        cmds += ["3", f"{yrange[0]:g},{yrange[1]:g}"]
    if nx:
        cmds += ["4", f"{int(nx)}"]
    if ny:
        cmds += ["5", f"{int(ny)}"]
    if zstep:
        cmds += ["6", f"{zstep:g}"]
    if zstart is not None:
        cmds += ["7", f"{zstart}" if isinstance(zstart, str) else f"{zstart:g}"]
    if zend is not None:
        cmds += ["8", f"{zend:g}"]
    if ncontour:
        cmds += ["9", f"{int(ncontour)}"]
    cmds.append("0")                         # Start calculation
    if export_data:
        cmds.append("-2")                    # Export plane data as distmap.txt
    cmds += ["-1", "-1", "0", "q"]           # 逐层退出并结束进程
    return cmds


_RANGE_X_RE = re.compile(
    r"range of X axis, current:\s*(-?\d+(?:\.\d+)?)\s+to\s+(-?\d+(?:\.\d+)?)")
_RANGE_Y_RE = re.compile(
    r"range of Y axis, current:\s*(-?\d+(?:\.\d+)?)\s+to\s+(-?\d+(?:\.\d+)?)")
_ZSTART_RE = re.compile(
    r"Z position of starting detection, current:\s*(-?\d+(?:\.\d+)?)")
_ZEND_RE = re.compile(
    r"Z position of ending detection, current:\s*(-?\d+(?:\.\d+)?)")


def run_multiwfn(mw_exe, input_path, cmds, workdir, timeout=1800.0):
    """在 ``workdir`` 里把命令序列喂给 Multiwfn，返回结果字典。

    返回键：``stdout``、``distmap``（路径）、``x_range``、``y_range``、
    ``z_range``、``elapsed``。任何一步失败都抛异常 —— 数据只能来自
    Multiwfn，拿不到就报错，绝不自己编一个。
    """
    import subprocess

    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    script = "\n".join(cmds) + "\n"
    (workdir / "mwfn_commands.txt").write_text(script, encoding="utf-8",
                                               newline="\n")

    env = os.environ.copy()
    env["Multiwfnpath"] = os.path.dirname(os.path.abspath(mw_exe))

    t0 = time.time()
    proc = subprocess.run(
        [mw_exe, Path(input_path).name],
        input=script, cwd=str(workdir),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="ignore",
        timeout=timeout, env=env,
    )
    elapsed = time.time() - t0
    out = proc.stdout or ""
    (workdir / "mwfn_log.txt").write_text(out, encoding="utf-8", newline="\n")

    distmap = workdir / "distmap.txt"
    if not distmap.is_file():
        raise RuntimeError(
            "Multiwfn 没有产出 distmap.txt，分析未完成。\n"
            f"命令行：{' '.join(cmds)}\n"
            f"日志见：{workdir / 'mwfn_log.txt'}\n"
            "--- 日志结尾 ---\n" + out[-1500:])

    def _last(rx, default):
        hits = re.findall(rx.pattern, out)
        if not hits:
            return default
        last = hits[-1]
        vals = last if isinstance(last, tuple) else (last,)
        return tuple(float(v) for v in vals)

    return {
        "stdout": out,
        "distmap": distmap,
        "x_range": _last(_RANGE_X_RE, (0.0, 0.0)),
        "y_range": _last(_RANGE_Y_RE, (0.0, 0.0)),
        "z_range": (_last(_ZSTART_RE, (0.0,))[0], _last(_ZEND_RE, (0.0,))[0]),
        "elapsed": elapsed,
    }


def parse_distmap(path):
    """解析 distmap.txt（三列 X Y 值，X 外层 / Y 内层），返回 xs, ys, V。"""
    data = np.loadtxt(path, comments="#")
    if data.ndim != 2 or data.shape[1] < 3:
        raise ValueError("distmap.txt 格式不是预期的三列")
    xs = np.unique(np.round(data[:, 0], 6))
    ys = np.unique(np.round(data[:, 1], 6))
    v = data[:, 2]
    if xs.size * ys.size != v.size:
        raise ValueError("distmap.txt 不是规则网格")
    return xs, ys, v.reshape(xs.size, ys.size)


def project(symbols, coords, R, workdir, mw_exe, *, surface="promol",
            iso=0.05, zstart_raise=0.0, nx=300, ny=300, ncontour=25,
            timeout=1800.0, on_log=None):
    """完整跑一遍：朝向烘焙 → 写 xyz → 驱动 Multiwfn → 解析。

    返回 ``(xs, ys, V, info)``；info 含 x/y/z 区间、用时、朝向后的坐标等。
    """
    log = on_log or (lambda _s: None)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    coords_oriented = apply_orientation(coords, R)
    zstart = float(coords_oriented[:, 2].max()) + float(zstart_raise)
    input_xyz = workdir / "oriented.xyz"
    write_xyz(input_xyz, symbols, coords_oriented, comment="MolStudio oriented")
    log(f"扫描起点 Z_start = {zstart:.4f} Å"
        f"（最高原子 {coords_oriented[:, 2].max():.4f} + {zstart_raise:g}）")

    cmds = build_commands(surface=surface, iso=iso, zstart=zstart,
                          nx=nx, ny=ny, ncontour=ncontour)
    res = run_multiwfn(mw_exe, input_xyz, cmds, workdir, timeout=timeout)
    xs, ys, V = parse_distmap(res["distmap"])

    z_start_used, z_end_used = res["z_range"]
    info = {
        "elapsed": res["elapsed"],
        "x_range": res["x_range"],
        "y_range": res["y_range"],
        "zstart": z_start_used,
        "zend": z_end_used,
        "floor": z_end_used - z_start_used,
        "vmin": float(V.min()),
        "vmax": float(V.max()),
        "nx": int(xs.size),
        "ny": int(ys.size),
        "coords_oriented": coords_oriented,
        "distmap": str(res["distmap"]),
    }
    return xs, ys, V, info


# ─────────────────────────────────────────────────────────────────────────────
# 绘图（画到调用方给的 Figure 上）
# ─────────────────────────────────────────────────────────────────────────────

_COV = {
    "H": 0.31, "B": 0.84, "C": 0.76, "N": 0.71, "O": 0.66, "F": 0.57,
    "Si": 1.11, "P": 1.07, "S": 1.05, "Cl": 1.02, "Br": 1.20, "I": 1.39,
    "Cu": 1.32, "Zn": 1.22, "Ru": 1.46, "Rh": 1.42, "Pd": 1.39, "Ag": 1.45,
    "Fe": 1.32, "Co": 1.26, "Ni": 1.24, "Mn": 1.39, "Cr": 1.39, "Mo": 1.54,
    "Pt": 1.36, "Au": 1.36, "Hg": 1.32, "Pb": 1.46, "Se": 1.20, "As": 1.19,
}

ATOM_COLORS = {
    "H": "#e8e8e8", "C": "#404040", "N": "#3355dd", "O": "#dd3333",
    "F": "#33cc33", "S": "#ddcc33", "P": "#dd8833", "Cl": "#33dd66",
    "Br": "#a0522d", "I": "#8b2fd0", "Cu": "#c88033", "Ru": "#3fbfbf",
}


def luminance(color) -> float:
    """颜色的相对亮度（0 黑 1 白），用来决定前景用深色还是浅色。"""
    try:
        import matplotlib.colors as mcolors
        r, g, b = mcolors.to_rgb(color)[:3]
    except Exception:                                             # noqa: BLE001
        return 1.0
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def void_mask(V, floor):
    """返回"扫到底也没命中表面"的布尔掩码；判断不了时返回 None。

    菜单里的 Z 只印到 4 位小数，直接比较会因舍入误差一个都匹配不上，
    所以用数据自身的最小值作精确落底值。
    """
    if floor is None:
        return None
    v_min = float(np.min(V))
    if abs(v_min - float(floor)) >= 5e-3:
        return None                       # 没有这类点，或与预期不符
    mask = np.asarray(V) <= v_min + 1e-6
    return mask if 0 < int(mask.sum()) < mask.size else None


def _make_cax_locator(parent_ax, size_frac=0.045, pad_frac=0.16):
    """把色标轴贴到绘图区右侧，高度**严格等于**绘图区高度。

    不用 make_axes_locatable：它在 ``set_aspect("equal")``（adjustable='box'）
    下是按调整**前**的位置摆色标的，结果色标会比绘图区高/矮一截。
    自定义 locator 每次绘制都读绘图区的当前位置，因此永远对齐。
    """
    def locator(_cax, _renderer):
        p = parent_ax.get_position()
        return [p.x1 + p.width * pad_frac, p.y0, p.width * size_frac, p.height]
    return locator


def draw_map(fig, xs, ys, V, *, title="", atoms=None, x_offset=0.0,
             y_offset=0.0, ncontour=25, bg="white", floor=None, void="bg",
             cmap="jet"):
    """把投影图画到 ``fig`` 上（会先清空该 Figure）。

    ``atoms`` 必须与 ``V`` **同一朝向**，否则原子会整体错位 ——
    这是接入时最容易犯的错。``cmap`` 是色带/等高线图的 matplotlib 配色名。

    数值约定与 Multiwfn 原文一致：每个格点的值就是 ``Z' - Z_start``（≤ 0），
    色标从 ``Z_end - Z_start``（最负、最深的蓝）到 ``0``（纯红，表面正好在
    参考面上），所以色标刻度是 0、−1、−2、−3 这样递减。
    返回 ``(被留白的格点数, 实际使用的色标下限)``；下限是带符号的负值
    （例如 −7.75），与 Multiwfn 的数值约定一致。
    """
    transparent = str(bg).lower() in ("none", "transparent")
    face = "none" if transparent else bg
    fg = "black" if (transparent or luminance(bg) > 0.55) else "white"

    fig.clear()
    fig.patch.set_facecolor(face)
    ax = fig.add_subplot(111)
    ax.set_facecolor(face)

    value = np.asarray(V, dtype=float)      # Z' - Z_start，<= 0，(Nx, Ny)
    n_void = 0
    if void == "bg":
        m = void_mask(V, floor)
        if m is not None:
            n_void = int(m.sum())
            value = np.ma.masked_where(m, value)

    # V 是 (Nx, Ny)（X 外层 / Y 内层，见 parse_distmap）；而 imshow 和带一维
    # x/y 的 contour 都要求 (Ny, Nx)。这里转置一次，否则图的横竖会颠倒、
    # 等高线和分子结构对不上。
    value = value.T

    xs_abs = np.asarray(xs, dtype=float) + x_offset
    ys_abs = np.asarray(ys, dtype=float) + y_offset
    x0, x1 = float(xs_abs.min()), float(xs_abs.max())
    y0, y1 = float(ys_abs.min()), float(ys_abs.max())

    # 色标上限固定为 0（纯红 = 表面就在参考面上），下限取实际数据的最负值
    v_lo = float(min(np.asarray(value.min()), -1e-6))

    # Multiwfn 给的是规则网格；直接 pcolormesh 会看到一格一格的台阶。
    # 这里用双三次插值把颜色画光滑（只影响显示，数据本身不变）。
    # imshow 的 extent 是"像素边界"，而 xs/ys 是"像素中心"；各向外扩半格，
    # 像素中心才正好落在 xs/ys 上，颜色/等值线/原子才会对齐。
    dx = (x1 - x0) / (xs_abs.size - 1) if xs_abs.size > 1 else 0.0
    dy = (y1 - y0) / (ys_abs.size - 1) if ys_abs.size > 1 else 0.0
    plot_value = (np.ma.filled(value, v_lo) if np.ma.isMaskedArray(value)
                  else np.asarray(value, dtype=float))
    pcm = ax.imshow(plot_value, origin="lower",
                    extent=(x0 - dx / 2, x1 + dx / 2,
                            y0 - dy / 2, y1 + dy / 2),
                    cmap=cmap, vmin=v_lo, vmax=0.0,
                    interpolation="bicubic", aspect="auto",
                    rasterized=True)

    # 等值线也放到 2–3 倍的三次插值网格上算，否则会沿原始格子走出阶梯。
    # 网格很大时降到 2 倍，控制内存/耗时。
    from scipy.ndimage import binary_dilation, gaussian_filter, zoom
    factor = 2 if max(xs_abs.size, ys_abs.size) > 500 else 3
    base = np.ma.filled(value, v_lo) if np.ma.isMaskedArray(value) \
        else np.asarray(value, dtype=float)
    zf = zoom(base, factor, order=3, grid_mode=True, mode="grid-constant")
    if np.ma.isMaskedArray(value):
        m0 = np.ma.getmaskarray(value)
        mf = zoom(m0.astype(float), factor, order=1, grid_mode=True,
                  mode="grid-constant") > 0.5
        zf = np.ma.masked_where(mf, zf)
        # 轮廓外留白：把掩码稍微高斯平滑后再按 0.5 等值线填背景色。
        # 直接按原始格点掩码画，边界会沿格子走出一圈小台阶；平滑后是
        # 一条光滑的轮廓线（只影响显示，不改数据）。
        if m0.any() and not m0.all() and face != "none":
            ms = zoom(gaussian_filter(m0.astype(float), 2.5), factor,
                      order=1, grid_mode=True, mode="grid-constant")
            ax.contourf(np.linspace(x0, x1, ms.shape[1]),
                        np.linspace(y0, y1, ms.shape[0]), ms,
                        levels=[0.5, 1.5], colors=[face], zorder=2,
                        antialiased=True)
        # 等值线再离开留白边界：否则最低几条贴着边界，画出一圈灰点线。
        zf = np.ma.masked_where(binary_dilation(mf, iterations=12), zf)
    xf = np.linspace(x0, x1, zf.shape[1])
    yf = np.linspace(y0, y1, zf.shape[0])
    levels = np.linspace(v_lo, 0.0, int(ncontour))
    # 最靠近 v_lo 的等值线贴着留白边界，跳过最低两条。
    clines = levels[2:-1] if levels.size > 4 else levels[1:-1]
    ax.contour(xf, yf, zf, levels=clines,
               colors=fg, linewidths=0.35, alpha=0.45,
               antialiased=True, zorder=2.2)

    if atoms is not None:
        syms, xyz = atoms
        xyz = np.asarray(xyz, dtype=float)
        px, py = xyz[:, 0], xyz[:, 1]
        inside = ((px >= xs_abs.min() - 0.6) & (px <= xs_abs.max() + 0.6) &
                  (py >= ys_abs.min() - 0.6) & (py <= ys_abs.max() + 0.6))
        for i in range(len(syms)):
            if not inside[i]:
                continue
            ri = _COV.get(str(syms[i]).capitalize(), 0.0)
            for j in range(i + 1, len(syms)):
                if not inside[j]:
                    continue
                rj = _COV.get(str(syms[j]).capitalize(), 0.0)
                if ri <= 0 or rj <= 0:
                    continue
                if float(np.linalg.norm(xyz[i] - xyz[j])) < (ri + rj) * 1.25:
                    ax.plot([px[i], px[j]], [py[i], py[j]],
                            "-", color=fg, lw=0.8, alpha=0.55, zorder=4)
        for i in range(len(syms)):
            if not inside[i]:
                continue
            ax.plot(px[i], py[i], "o", ms=7.5, mec="k", mew=0.6, zorder=5,
                    color=ATOM_COLORS.get(str(syms[i]).capitalize(), "#aaaaaa"))
            ax.annotate(str(syms[i]), (px[i], py[i]), xytext=(9, 6),
                        textcoords="offset points", fontsize=7.5,
                        zorder=6, color=fg)

    ax.set_aspect("equal")
    ax.set_xlabel("X (Angstrom)", color=fg)
    ax.set_ylabel("Y (Angstrom)", color=fg)
    ax.set_title(title, fontsize=10, color=fg)
    ax.tick_params(colors=fg, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(fg)

    fig.subplots_adjust(left=0.13, right=0.88, top=0.92, bottom=0.14)

    # 色标：自定义 locator，高度严格等于绘图区（见 _make_cax_locator）
    cax = fig.add_axes([0.90, 0.14, 0.02, 0.7])
    cax.set_axes_locator(_make_cax_locator(ax))
    cb = fig.colorbar(pcm, cax=cax)
    cb.set_label("value = Z' - Z_start (Angstrom)", fontsize=8, color=fg)
    cb.ax.tick_params(colors=fg, labelsize=8)
    cb.outline.set_edgecolor(fg)
    return n_void, v_lo
