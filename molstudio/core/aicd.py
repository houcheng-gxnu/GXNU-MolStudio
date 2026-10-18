"""
AICD — 感应电流密度各向异性（Anisotropy of the Induced Current Density）
=======================================================================

把 Gaussian 的 ``NMR=CSGT`` + ``IOp(10/93=1)`` 计算所输出的电流密度张量
网格，转换成一张可画的 AICD 图：张量各向异性标量场（等值面）+ 感应电流
矢量场（箭头）。

数据来源（Gaussian 在算完之后会写两个东西）：

* ``xxx.log``：常规输出。Gaussian 会打印一行
  ``Writing AICD formatted file "test.txt"``，以及标准取向下的分子几何。
* ``test.txt``：电流密度张量转储。按块重复，每块形如::

      Gitterpunkte:                 <- 格点序号 + x y z（Å，标准取向）
      Gewichtungsfaktoren:          <- 格点序号 + 权重
      Stromdichtetensor, II= 1      <- 格点序号 + 三个数
      Stromdichtetensor, II= 2
      Stromdichtetensor, II= 3

  **格点坐标的单位是 Bohr**（不是 Å）——这一点必须记住：把 1470 个数据块的
  中心聚类，会精确落在苯的 6 个碳（2.628 Bohr = 1.391 Å）和 6 个氢
  （4.673 Bohr = 2.473 Å）上。AICD 程序内部也统一用 Bohr，写出的 cube
  文件同样是 Bohr。模块对外统一转成 Å，写 cube 时再转回 Bohr。

  九个数是电流密度张量 :math:`j_{\\alpha\\beta} = \\partial J_\\alpha /
  \\partial B_\\beta`（a.u.），其中 ``II`` 是**磁场方向**下标 β，行内的三个数
  依次是 α = x, y, z 分量。这一点由程序包里的 Perl 提取器（AICD-extract.pl）
  和苯的对称性双向验证过：把 II 当作磁场下标时，九个分量在 σ_v 镜面下严格
  满足 j' = −M j M（误差 0.0e+00），且苯的环电流是抗磁的（m_z < 0）。

物理量（与 Herges 组 AICD 程序一致）：

* 电流矢量  ``J(r) = j(r) · B``
* 各向异性  ``Aniso = sqrt(0.5*[(jxx-jyy)² + (jyy-jzz)² + (jzz-jxx)²
  + 1.5*((jxy+jyx)² + (jyz+jzy)² + (jxz+jzx)²)])``
* 各向同性  ``Iso   = (jxx+jyy+jzz)/3``

把非均匀的 Gaussian 格点数据插值到规则笛卡尔网格上的做法也照搬 AICD-remap：
每个高斯格点贡献给它最近的 4 个笛卡尔格点，权重取 1/距离，然后加权平均。

参考文献：D. Geuenich, K. Hess, F. Köhler, R. Herges, *Chem. Rev.* **2005**,
105, 3758；R. Herges, D. Geuenich, *J. Phys. Chem. A* **2001**, 105, 3214。
"""

from __future__ import annotations

import os
import re

import numpy as np

__all__ = [
    "AICDData",
    "AICDVolume",
    "parse_tensor_dump",
    "read_standard_orientation",
    "guess_plane_normal",
    "guess_bonds",
    "element_number",
    "find_small_rings",
    "planar_rings",
    "current_density",
    "anisotropy",
    "isotropy",
    "full_anisotropy",
    "antisymmetric_anisotropy",
    "build_grid",
    "remap_to_grid",
    "remap_vectors_to_grid",
    "write_cube",
    "compute_aicd",
    "find_tensor_file",
    "surface_arrow_samples",
    "surface_arrow_geometry",
    "build_arrow_geometry",
    "ARROW_STYLE",
    "BOHR",
    "QUANTITIES",
]

#: 可画的标量场（对应 AICD 的 -i 选项）
QUANTITIES = ("Aniso", "FullAniso", "AntiSymmAniso", "Iso")

_BOHR = 0.529177210903          # Å

#: 公开别名（外部模块换算 Å ↔ Bohr 用同一份常数）
BOHR = _BOHR

#: 是否把张量转储里的坐标从 Bohr 换算成 Å（模块内部与对外接口统一用 Å）
_COORDS_IN_BOHR = True

#: 箭头几何比例，取自 AICD 源码：``AICD-smooth_isosurface.cpp`` 里发的是
#: ``cylinder { A, B, 0.0104 }`` 加 ``cone { B, 0.0208, C, 0 }``（锥尖半径 0，
#: 所以头是尖的），并且 AICD 把平均箭头长度归一化到 0.626 Bohr。注意 AICD 写
#: POV-Ray 时坐标乘了 0.529（Bohr→Å），但圆柱/锥的半径是直接写的 **Å** 数：
#: 均长 = 0.626 Bohr = 0.331 Å，所以杆半径/均长 = 0.0104/0.331 = 3.14%，
#: 锥底 = 6.28%。这里统一换算成"以平均箭头长度为 1"的比例，改 ``mean_length``
#: 只影响整体大小、不改比例。
ARROW_STYLE = {
    "mean_length": 0.626 * _BOHR,       # Å：平均箭头长度（AICD 固定 0.626 Bohr）
    "shaft_radius": 0.0104 / (0.626 * _BOHR),   # 杆半径 ≈ 平均长度的 3.14%
    "head_radius": 0.0208 / (0.626 * _BOHR),    # 锥底半径 ≈ 6.28%（杆的 2 倍）
    "head_length": 0.166666 / 0.626,    # 头长 ≈ 26.6%
}
_ELEMENT_SYMBOLS = (
    "", "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne", "Na", "Mg", "Al", "Si",
    "P", "S", "Cl", "Ar", "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni",
    "Cu", "Zn", "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr", "Nb", "Mo",
    "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn", "Sb", "Te", "I", "Xe", "Cs", "Ba",
    "La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb",
    "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi", "Po",
    "At", "Rn",
)


def element_symbol(atomic_number: int) -> str:
    """原子序数 -> 元素符号（未知元素返回 ``X``）。"""
    if 0 < atomic_number < len(_ELEMENT_SYMBOLS):
        return _ELEMENT_SYMBOLS[atomic_number]
    return "X"


# ── 数据容器 ───────────────────────────────────────────────────────────

class AICDData:
    """从 Gaussian 张量转储里读出来的原始数据。"""

    def __init__(self, points, tensors, weights=None, source=""):
        self.points = np.asarray(points, dtype=np.float64)      # (N,3) Å
        self.tensors = np.asarray(tensors, dtype=np.float64)    # (N,3,3) j[α][β]
        if weights is None:
            weights = np.ones(len(self.points))
        self.weights = np.asarray(weights, dtype=np.float64)
        self.source = source

    def __len__(self):
        return len(self.points)

    def __repr__(self):
        return f"AICDData(N={len(self)}, source={os.path.basename(self.source)!r})"


class AICDVolume:
    """算好的 AICD 标量场（规则网格），可以直接送给 cube 读写/等值面提取。"""

    def __init__(self, origin, spacing, field, atoms, quantity="Aniso",
                 vectors=None, metadata=None):
        self.origin = np.asarray(origin, dtype=np.float64)          # (3,) Å
        self.spacing = float(spacing)                               # Å
        self.field = np.asarray(field, dtype=np.float32)            # (nx,ny,nz)
        self.atoms = list(atoms)                                     # [(Z, x, y, z)]
        self.quantity = quantity
        self.vectors = vectors                                       # (nx,ny,nz,3) 或 None
        self.metadata = dict(metadata or {})

    @property
    def shape(self):
        return self.field.shape

    @property
    def value_range(self):
        return float(self.field.min()), float(self.field.max())


# ── 解析 ───────────────────────────────────────────────────────────────

_RE_GRID = re.compile(r"^\s*Gitterpunkte\s*:")
_RE_WEIGHT = re.compile(r"^\s*Gewichtungsfaktoren\s*:")
_RE_TENSOR = re.compile(r"^\s*Stromdichtetensor\s*,\s*II\s*=\s*(\d+)")
_RE_LOG_TENSORLINE = re.compile(
    r'Writing\s+AICD\s+(?:formatted\s+)?file\s+"?([^"\s]+)"?')


def parse_tensor_dump(path):
    """解析 Gaussian 写出的 AICD 张量转储。

    返回 :class:`AICDData`；**格点坐标已从 Bohr 换算成 Å**（Gaussian 这份文件
    是 Bohr，见模块文档），张量单位为 a.u.。
    每个块内的三行段按磁场下标 β = 1,2,3 组织，装进 ``tensors[:, α, β]``。
    """
    points, weights, tensors = [], [], []
    block_pts, block_wts = [], []
    block_sec = {}
    section = None

    def flush():
        n = len(block_pts)
        if not n:
            return
        secs = [block_sec.get(i, np.zeros((n, 3))) for i in (1, 2, 3)]
        for i in range(n):
            tens = np.empty((3, 3))
            for beta in range(3):
                tens[:, beta] = secs[beta][i]
            tensors.append(tens)
        points.extend(block_pts)
        if len(block_wts) == n:
            weights.extend(block_wts)
        else:
            weights.extend([0.0] * n)

    with open(path, "r", errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if not line.strip():
                continue
            if _RE_GRID.match(line):
                flush()
                block_pts, block_wts, block_sec = [], [], {}
                section = "points"
                continue
            if _RE_WEIGHT.match(line):
                section = "weights"
                continue
            m = _RE_TENSOR.match(line)
            if m:
                section = int(m.group(1))
                block_sec.setdefault(section, [])
                continue
            fields = line.replace("D", "E").split()
            try:
                values = [float(v) for v in fields[1:]]
            except ValueError:
                continue                                # 表头行（"1 2 3" 之外的杂项）
            if section == "points" and len(values) == 3:
                block_pts.append(values)
            elif section == "weights" and len(values) == 1:
                block_wts.append(values[0])
            elif isinstance(section, int) and len(values) == 3:
                block_sec[section].append(values)
    flush()

    if not points:
        raise ValueError(f"没有在 {path} 里找到任何 AICD 格点数据")
    points = np.asarray(points, dtype=np.float64)
    if _COORDS_IN_BOHR:
        points = points * _BOHR
    return AICDData(points, tensors, weights, source=str(path))


def find_tensor_file(log_path):
    """从 Gaussian 输出里找出它写出的 AICD 张量文件（返回绝对路径或 None）。

    优先用输出里记录的文件名（``Writing AICD formatted file "test.txt"``）。
    只有**日志确实写了这一行**（说明任务走到了 NMR 那一步）但文件名在目录里
    找不到时，才在同目录里找一个开头是 ``Gitterpunkte`` 的 txt（改过名之类）；
    任务半路失败、日志里根本没有这行时返回 None——绝不拿目录里别的任务的
    张量来凑数（真实踩过：一个失败的 job 静默用了另一个分子的 test.txt）。
    """
    name = None
    wrote_marker = False
    with open(log_path, "r", errors="replace") as fh:
        for line in fh:
            m = _RE_LOG_TENSORLINE.search(line)
            if m:
                name = m.group(1)
                wrote_marker = True
    folder = os.path.dirname(os.path.abspath(log_path))
    if name:
        cand = os.path.join(folder, name)
        if os.path.isfile(cand):
            return cand

    if not wrote_marker:
        return None

    hits = []
    try:
        for entry in sorted(os.listdir(folder)):
            if not entry.lower().endswith((".txt", ".dat")):
                continue
            path = os.path.join(folder, entry)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", errors="replace") as fh:
                    head = fh.readline()
            except OSError:
                continue
            if head.strip().startswith("Gitterpunkte"):
                hits.append(path)
    except OSError:
        return None
    return hits[0] if len(hits) == 1 else None


def read_standard_orientation(log_path):
    """读 Gaussian 输出里最后一个 Standard orientation 表的原子（返回 [(Z,x,y,z)]）。"""
    blocks = []
    current = None
    pending = False
    with open(log_path, "r", errors="replace") as fh:
        for line in fh:
            if "Standard orientation" in line:
                pending = True
                current = []
                continue
            if pending:
                if set(line.strip()) <= set("- "):
                    continue
                parts = line.split()
                if len(parts) >= 6 and parts[0].isdigit():
                    try:
                        z = int(parts[1])
                        x, y, zz = (float(parts[3]), float(parts[4]), float(parts[5]))
                    except ValueError:
                        continue
                    current.append((z, x, y, zz))
                elif current:
                    blocks.append(current)
                    current = None
                    pending = False
    if current:
        blocks.append(current)
    if not blocks:
        return []
    return blocks[-1]


# ── 物理量 ─────────────────────────────────────────────────────────────

def guess_plane_normal(atoms, planarity_tol=0.10):
    """从原子坐标猜分子平面的法向（给"磁场方向"预选默认值用）。

    为什么要猜：AICD 的磁场方向是相对**标准取向**说的，而标准取向不是用户在
    画布里看到的那个朝向（Gaussian 算之前会自己重排到惯性主轴系）。所以面板
    需要在分析前把"哪个轴垂直于分子平面"算出来，替用户把 ``-b`` 选好——
    芳香性要看的就是垂直环平面的环电流。

    做法：把坐标去心后做 SVD，最小奇异值对应的方向就是最佳拟合平面的法向；
    再取它在 x/y/z 里分量最大的那个轴（连同符号）。

    Parameters
    ----------
    atoms : sequence
        ``[(Z 或元素符号, x, y, z), ...]``，Å（标准取向）。
    planarity_tol : float
        判定"够平"的 RMS 偏离上限（Å），默认 0.10。

    Returns
    -------
    dict
        ``{"axis": 0|1|2, "sign": +1/-1, "vector": (x,y,z), "rms": float,
        "planar": bool, "max_dev": float}``；原子不足 3 个时 ``planar=False``、
        axis=2（回退到 +z）。
    """
    pts = np.array([[float(a[1]), float(a[2]), float(a[3])] for a in (atoms or [])],
                   dtype=np.float64)
    out = {"axis": 2, "sign": 1.0, "vector": (0.0, 0.0, 1.0), "rms": 0.0,
           "max_dev": 0.0, "planar": False}
    if len(pts) < 3:
        return out
    centred = pts - pts.mean(axis=0)
    try:
        _, _, vt = np.linalg.svd(centred, full_matrices=False)
    except np.linalg.LinAlgError:
        return out
    normal = vt[2]
    axis = int(np.argmax(np.abs(normal)))
    # 平面法向本身是 ± 两个**等价**方向，SVD 给出的符号没有物理意义（甚至随
    # BLAS/版本变化）。这里统一翻到该轴的正方向：结果可复现，而且与 sobereva
    # 文章里的写法一致（薁的垂直轴是 x，AICD 命令用 ``-b 1 0 0`` 而不是 -1 0 0）。
    # 想看反方向的图时，让用户在下拉里手动选 −x/−y/−z 即可（箭头整体反向）。
    if normal[axis] < 0:
        normal = -normal
    sign = 1.0
    dev = np.abs(centred @ normal)
    out.update({
        "axis": axis,
        "sign": sign,
        "vector": tuple(float(v) for v in normal),
        "rms": float(np.sqrt(np.mean(dev ** 2))),
        "max_dev": float(dev.max()),
    })
    out["planar"] = out["rms"] <= float(planarity_tol)
    return out


#: 成键判据用的共价半径（Å），只用于"找环"，不参与任何物理量计算
_COVALENT_RADII = {1: 0.31, 5: 0.84, 6: 0.76, 7: 0.71, 8: 0.66, 9: 0.57,
                   14: 1.11, 15: 1.07, 16: 1.05, 17: 1.02, 35: 1.20, 53: 1.39}


def _element_number(value):
    """元素符号或原子序数 → 原子序数（只认识常见元素，猜不到给 6）。"""
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().capitalize()
    for z, sym in enumerate(_ELEMENT_SYMBOLS):
        if sym == text:
            return z
    return 6


def element_number(value):
    """元素符号或原子序数 → 原子序数（公开版，供面板把结构送进画布）。"""
    return _element_number(value)


def guess_bonds(atoms, tolerance=0.45):
    """按距离猜成键（给"找环"用）。返回 ``[(i, j), ...]``（0-based）。

    判据：``d < r_i + r_j + tolerance``，半径取共价半径近似值。只用于几何层面
    的找环，宽容度给得比较松——宁可多连一根，也别把环断开。
    """
    import itertools
    coords = np.array([[float(a[1]), float(a[2]), float(a[3])] for a in atoms],
                      dtype=np.float64)
    radii = [_COVALENT_RADII.get(_element_number(a[0]), 0.77) for a in atoms]
    bonds = []
    for i, j in itertools.combinations(range(len(atoms)), 2):
        cut = radii[i] + radii[j] + float(tolerance)
        if float(np.linalg.norm(coords[i] - coords[j])) <= cut:
            bonds.append((i, j))
    return bonds


def find_small_rings(n_atoms, bonds, max_size=7, max_cycles=20000):
    """找出所有小环（长度 ≤ ``max_size``），按原子集合去重。返回原子索引列表。"""
    adj = [[] for _ in range(n_atoms)]
    for i, j in bonds:
        adj[i].append(j)
        adj[j].append(i)
    for lst in adj:
        lst.sort()
    found, seen, steps = [], set(), 0
    for start in range(n_atoms):
        stack = [(start, [start])]
        while stack:
            node, path = stack.pop()
            for nxt in adj[node]:
                steps += 1
                if steps > max_cycles * 8:
                    return found
                if nxt == start and len(path) >= 3:
                    if len(path) <= max_size:
                        key = frozenset(path)
                        if key not in seen:
                            seen.add(key)
                            found.append(sorted(path))
                    continue
                # 只走比起点大的结点：保证每个环只以"最小结点"为起点被枚举一次
                if nxt <= start or nxt in path or len(path) >= max_size:
                    continue
                stack.append((nxt, path + [nxt]))
    return found


def planar_rings(atoms, bonds=None, min_size=5, rms_tol=0.12, top=3,
                 max_size=7):
    """列出够平的小环，按平面度排序（配合物里"要考察哪个环"的默认判据）。

    Returns
    -------
    list of dict
        每项 ``{"atoms": [idx...], "size": n, "rms": Å, "max_dev": Å,
        "normal": (x,y,z), "axis": 0|1|2, "sign": ±1}``。
    """
    atoms = list(atoms or [])
    if len(atoms) < min_size:
        return []
    if bonds is None:
        bonds = guess_bonds(atoms)
    out = []
    for ring in find_small_rings(len(atoms), bonds, max_size=max_size):
        if len(ring) < min_size:
            continue
        info = guess_plane_normal([atoms[i] for i in ring], planarity_tol=rms_tol)
        if info["rms"] > rms_tol:
            continue
        out.append({"atoms": ring, "size": len(ring), "rms": info["rms"],
                    "max_dev": info["max_dev"], "normal": info["vector"],
                    "axis": info["axis"], "sign": info["sign"]})
    out.sort(key=lambda d: (d["rms"], -d["size"]))
    return out[:top] if top else out

def current_density(tensors, field=(0.0, 0.0, 1.0)):
    """感应电流矢量场 ``J = j · B``（``tensors`` 形状 (N,3,3)）。"""
    b = np.asarray(field, dtype=np.float64).reshape(3)
    return np.einsum("nab,b->na", np.asarray(tensors, dtype=np.float64), b)


def isotropy(tensors):
    """张量各向同性部分（迹/3）。"""
    t = np.asarray(tensors, dtype=np.float64)
    return np.einsum("naa->n", t) / 3.0


def anisotropy(tensors):
    """AICD 各向异性（对称部分），对应 AICD 的 ``Aniso``。"""
    t = np.asarray(tensors, dtype=np.float64)
    d = (0.5 * ((t[:, 0, 0] - t[:, 1, 1]) ** 2
                + (t[:, 1, 1] - t[:, 2, 2]) ** 2
                + (t[:, 2, 2] - t[:, 0, 0]) ** 2
                + 1.5 * ((t[:, 0, 1] + t[:, 1, 0]) ** 2
                         + (t[:, 1, 2] + t[:, 2, 1]) ** 2
                         + (t[:, 0, 2] + t[:, 2, 0]) ** 2)))
    return np.sqrt(np.maximum(d, 0.0))


def full_anisotropy(tensors):
    """完整各向异性（对称 + 反对称部分）。"""
    t = np.asarray(tensors, dtype=np.float64)
    d = np.abs(0.5 * ((t[:, 0, 0] - t[:, 1, 1]) ** 2
                      + (t[:, 1, 1] - t[:, 2, 2]) ** 2
                      + (t[:, 2, 2] - t[:, 0, 0]) ** 2
                      + 6.0 * (t[:, 0, 1] * t[:, 1, 0]
                               + t[:, 1, 2] * t[:, 2, 1]
                               + t[:, 0, 2] * t[:, 2, 0])))
    return np.sqrt(d)


def antisymmetric_anisotropy(tensors):
    """反对称部分各向异性。"""
    t = np.asarray(tensors, dtype=np.float64)
    d = np.abs(-0.75 * ((t[:, 0, 1] - t[:, 1, 0]) ** 2
                        + (t[:, 1, 2] - t[:, 2, 1]) ** 2
                        + (t[:, 0, 2] - t[:, 2, 0]) ** 2))
    return np.sqrt(d)


_SCALARS = {
    "Aniso": anisotropy,
    "FullAniso": full_anisotropy,
    "AntiSymmAniso": antisymmetric_anisotropy,
    "Iso": isotropy,
}


def scalar_field(tensors, quantity="Aniso"):
    """按名字取标量场。"""
    try:
        return _SCALARS[quantity](tensors)
    except KeyError:
        raise ValueError(f"未知的标量场 {quantity!r}，可选：{', '.join(QUANTITIES)}")


# ── 插值到规则网格 ─────────────────────────────────────────────────────

def _grid_axes(lo, hi, spacing, max_nodes):
    spacing = float(spacing)
    while True:
        n = np.maximum(np.ceil((hi - lo) / spacing).astype(int) + 1, 2)
        if int(np.prod(n.astype(np.int64))) <= max_nodes:
            break
        spacing *= 1.25
    return lo, spacing, tuple(int(v) for v in n)


def build_grid(points, spacing=0.25, padding=2.5, max_nodes=6_000_000, atoms=None):
    """给出规则网格的 (origin, spacing, shape)。

    网格范围以分子（``atoms``）为准并外扩 ``padding``；没有几何信息时退化为
    用点云里"有实质数值"的那部分点。Gaussian 的 AICD 格点会一直铺到离分子
    二十多 Å 的地方，直接用整片点云会把网格撑得又大又空。
    """
    pts = np.asarray(points, dtype=np.float64)
    if atoms:
        core = np.array([[x, y, z] for _, x, y, z in atoms], dtype=np.float64)
    else:
        core = pts
    lo = core.min(axis=0) - padding
    hi = core.max(axis=0) + padding
    return _grid_axes(lo, hi, spacing, max_nodes)


def _node_index(points, origin, spacing, shape):
    idx = np.rint((points - origin) / spacing).astype(np.int64)
    np.clip(idx[:, 0], 0, shape[0] - 1, out=idx[:, 0])
    np.clip(idx[:, 1], 0, shape[1] - 1, out=idx[:, 1])
    np.clip(idx[:, 2], 0, shape[2] - 1, out=idx[:, 2])
    return idx


def remap_to_grid(points, values, origin, spacing, shape, k=4):
    """把散点标量值插值到规则网格（AICD-remap 的做法：最近 k 个格点 + 1/d 加权）。

    ``values`` 可以是 (N,) 标量或 (N, m) 多通道。返回 (shape) 或 (shape..., m)。
    """
    points = np.asarray(points, dtype=np.float64)
    values = np.asarray(values, dtype=np.float64)
    multi = values.ndim > 1
    if not multi:
        values = values[:, None]
    shape = tuple(int(v) for v in shape)

    nodes = np.stack(np.meshgrid(
        origin[0] + spacing * np.arange(shape[0]),
        origin[1] + spacing * np.arange(shape[1]),
        origin[2] + spacing * np.arange(shape[2]),
        indexing="ij"), axis=-1).reshape(-1, 3)

    from scipy.spatial import cKDTree
    tree = cKDTree(nodes)
    d, idx = tree.query(points, k=min(k, len(nodes)))
    d = np.atleast_2d(d)
    idx = np.atleast_2d(idx)
    with np.errstate(divide="ignore"):
        w = 1.0 / np.maximum(d, 1e-8)
    n_nodes = len(nodes)
    acc = np.zeros((n_nodes, values.shape[1]))
    wsum = np.zeros(n_nodes)
    flat_idx = idx.ravel()
    np.add.at(acc, flat_idx, (values[:, None, :] * w[:, :, None]).reshape(-1, values.shape[1]))
    np.add.at(wsum, flat_idx, w.ravel())

    out = np.zeros_like(acc)
    good = wsum > 0
    out[good] = acc[good] / wsum[good, None]

    # 极少数没拿到数据的格点（离分子太远）：用最近高斯格点的值补上
    if not good.all():
        stree = cKDTree(points)
        _, nearest = stree.query(nodes[~good], k=1)
        out[~good] = values[nearest]

    out = out.reshape(shape + (values.shape[1],))
    return out if multi else out[..., 0]


def remap_vectors_to_grid(points, vectors, origin, spacing, shape, k=4):
    """把散点矢量场插值到规则网格，返回 (nx,ny,nz,3)。"""
    out = remap_to_grid(points, np.asarray(vectors, dtype=np.float64),
                        origin, spacing, shape, k=k)
    return out


# ── 输出 ───────────────────────────────────────────────────────────────

def surface_arrow_samples(volume, iso, shell=0.75, decimate=1,
                          magnitude_floor=0.0, length_range=None):
    """在等值面附近按**规则网格**取箭头采样点（AICD 就是这么干的）。

    AICD 的箭头不是随机撒在等值面上的，而是取自笛卡尔网格里"贴着等值面"
    的那些格点——所以画出来是一圈圈整齐排开的箭头，而不是一团红绿噪声。
    这里用 ``|f - iso| / |∇f|`` 估计每个格点到等值面的距离，保留距离在
    ``shell × 网格间距`` 以内的格点，再用 ``decimate`` 控制稀疏程度。

    Parameters
    ----------
    volume : AICDVolume
        需要带 ``vectors``（感应电流矢量场）。
    iso : float
        等值面数值，用于挑出贴近该面的格点。
    shell : float
        等值面壳层厚度，单位是网格间距（0.75 ≈ 一格）。
    decimate : int
        网格抽稀步长，>1 时箭头更稀疏（对应 AICD 的 ``-p`` 网格点数）。
    magnitude_floor : float
        丢掉 |J| 小于该值的箭头，避免在几乎无电流的地方画小箭头。
    length_range : (min, max), optional
        按归一化后的箭头长度过滤（对应 AICD 的 ``-minarrow`` / ``-maxarrow``）。

    Returns
    -------
    (positions, vectors) : (N,3) 箭头起点（Å）与对应的 J
    """
    if volume.vectors is None:
        raise ValueError("AICDVolume 里没有 vectors，先用 with_vectors=True 计算")
    f = np.asarray(volume.field, dtype=np.float64)
    spacing = float(volume.spacing)
    grads = np.gradient(f, spacing)
    gmag = np.sqrt(sum(g * g for g in grads))
    with np.errstate(divide="ignore", invalid="ignore"):
        dist = np.abs(f - iso) / np.maximum(gmag, 1e-9)
    mask = dist <= shell * spacing

    vectors = np.asarray(volume.vectors, dtype=np.float64)
    mag = np.linalg.norm(vectors, axis=-1)
    if magnitude_floor > 0:
        mask &= mag > magnitude_floor
    if length_range is not None:
        lo, hi = length_range
        mean = mag[mask].mean() if mask.any() else 0.0
        if mean > 0:
            norm_len = ARROW_STYLE["mean_length"] * mag / mean
            mask &= (norm_len >= lo) & (norm_len <= hi)

    idx = np.argwhere(mask)
    if decimate and decimate > 1:
        idx = idx[(idx[:, 0] % decimate == 0) & (idx[:, 1] % decimate == 0)
                  & (idx[:, 2] % decimate == 0)]
    origin = np.asarray(volume.origin, dtype=np.float64)
    positions = origin + idx * spacing
    return positions, vectors[idx[:, 0], idx[:, 1], idx[:, 2]]

def build_arrow_geometry(bases, vectors, style=None, segments=12,
                         min_length=0.0, max_length=None):
    """把感应电流矢量场转成真正的圆柱杆 + 圆锥头几何（尖端收成一点）。

    Parameters
    ----------
    bases : (N,3) 箭头起点（Å）
    vectors : (N,3) 感应电流密度 J（箭头方向即 J 的方向）
    style : dict, optional
        覆盖 :data:`ARROW_STYLE` 里的比例。
    segments : int
        绕轴的圆周分段数（12 足够顺滑）。
    min_length, max_length : float, optional
        丢弃过短/过长的箭头（对应 AICD 的 ``-minarrow`` / ``-maxarrow``）。

    Returns
    -------
    dict
        ``{"shaft": (verts, faces), "head": (verts, faces), "length": (N,)，
        "direction": (N,3), "keep": (N,) bool}``。
        两个 (verts, faces) 都是标准三角/四边形面片，可直接送 OpenGL 或
        matplotlib 的 Poly3DCollection。
    """
    st = dict(ARROW_STYLE)
    if style:
        st.update(style)
    bases = np.asarray(bases, dtype=np.float64).reshape(-1, 3)
    vectors = np.asarray(vectors, dtype=np.float64).reshape(-1, 3)
    mag = np.linalg.norm(vectors, axis=1)
    keep = mag > 1e-12
    if min_length > 0 or max_length is not None:
        mean = mag[keep].mean() if keep.any() else 0.0
        length_preview = st["mean_length"] * mag / max(mean, 1e-12)
        if min_length > 0:
            keep &= length_preview >= min_length
        if max_length is not None:
            keep &= length_preview <= max_length
    if not keep.any():
        return {"shaft": (np.zeros((0, 3)), np.zeros((0, 3), dtype=int)),
                "head": (np.zeros((0, 3)), np.zeros((0, 3), dtype=int)),
                "length": np.zeros(0), "direction": np.zeros((0, 3)),
                "keep": keep}

    mean = mag[keep].mean()
    length = st["mean_length"] * mag / mean          # 归一化：平均长度 = mean_length
    direction = vectors / np.maximum(mag, 1e-12)[:, None]
    r_shaft = st["shaft_radius"] * st["mean_length"]
    r_head = st["head_radius"] * st["mean_length"]
    head_len = np.minimum(st["head_length"] * st["mean_length"], 0.9 * length)

    sel = np.where(keep)[0]
    n = len(sel)
    ang = np.linspace(0.0, 2.0 * np.pi, segments, endpoint=False)
    ref = np.array([0.0, 0.0, 1.0])
    verts, shaft_faces, head_faces = [], [], []

    def ring(center, axis, radius):
        axis = axis / max(np.linalg.norm(axis), 1e-12)
        helper = ref if abs(np.dot(axis, ref)) < 0.9 else np.array([1.0, 0.0, 0.0])
        e1 = np.cross(axis, helper)
        e1 /= max(np.linalg.norm(e1), 1e-12)
        e2 = np.cross(axis, e1)
        return center + radius * (np.cos(ang)[:, None] * e1 + np.sin(ang)[:, None] * e2)

    def add_tube(base_start, base_end, radius, base_index):
        r0 = ring(base_start, base_end - base_start, radius)
        r1 = ring(base_end, base_end - base_start, radius)
        off = len(verts)
        verts.extend(r0)
        verts.extend(r1)
        for k in range(segments):
            a, b = off + k, off + (k + 1) % segments
            c, d = off + segments + k, off + segments + (k + 1) % segments
            shaft_faces.append([a, b, d])
            shaft_faces.append([a, d, c])

    def add_cone(apex, base_center, radius, axis):
        r0 = ring(base_center, axis, radius)
        off = len(verts)
        verts.extend(r0)
        apex_index = len(verts)
        verts.append(np.asarray(apex, dtype=np.float64))
        for k in range(segments):
            a, b = off + k, off + (k + 1) % segments
            head_faces.append([a, b, apex_index])

    for i in sel:
        p0 = bases[i]
        u = direction[i]
        tip = p0 + u * length[i]
        neck = tip - u * head_len[i]
        add_tube(p0, neck, r_shaft, len(verts))
        add_cone(tip, neck, r_head, tip - neck)

    verts = np.asarray(verts, dtype=np.float64)
    # 杆/锥头必须分别收集：面片是逐箭头写入的（2*segments 个杆面 + segments 个
    # 锥面），若按总数一刀切，切片会跨过箭头边界，把锥面分进"杆"、把杆面分进
    # 锥头，画出来就成了"绿尖红杆"（与 AICD 参考图相反）。
    shaft_faces = np.asarray(shaft_faces, dtype=np.int32)
    head_faces = np.asarray(head_faces, dtype=np.int32)
    return {
        "shaft": (verts, shaft_faces),
        "head": (verts, head_faces),
        "length": length,
        "direction": direction,
        "keep": keep,
        "vertices": verts,
        "faces_all": np.vstack([shaft_faces, head_faces]),
    }

def surface_arrow_geometry(volume, iso, shell=0.75, decimate=1,
                           magnitude_floor=0.0, mean_length=0.5,
                           max_arrow=0.0, min_arrow=0.0, offset=0.03,
                           segments=10, style=None, clip_plane=None):
    """把箭头**贴到等值面外侧**，再生成杆/锥几何（AICD 的取点方式）。

    为什么不能直接用 ``surface_arrow_samples`` 的格点当箭头起点：那些点落在
    等值面两侧约 ±0.75 个格距的壳层里，约一半在等值面**内部**。等值面在画布里
    是不透明的，切向箭头又贴着曲面走，结果大部分箭头被深度测试挡掉——画布上
    只剩轮廓处几根长刺，看起来比 AICD 图稀疏得多（而 matplotlib 图用
    ``FrontCollection`` 把箭头强行画在最前，掩盖了这个问题）。

    AICD 的 ``AICD-smooth_isosurface`` 做法是：把每个表面格点沿梯度**投影到
    等值面**；若 J 指向面内，则把箭杆放在面外、箭尖落在面上（``A=-J``，
    ``B=Origin``）；若 J 指向面外，则从面出发向外画。这样所有箭头都在面外，
    不透明表面不会把它们吞掉。本函数按同一规则返回几何。

    Parameters
    ----------
    volume : AICDVolume
        需要带 ``vectors``。
    iso : float
        等值面数值。
    shell, decimate, magnitude_floor
        与 :func:`surface_arrow_samples` 同名参数。
    mean_length : float
        归一化后的平均箭头长度（Å）。
    max_arrow, min_arrow : float
        按"平均长度的倍数"过滤（0 = 不过滤），对应 AICD 的
        ``-maxarrow`` / ``-minarrow``。
    offset : float
        箭头整体沿外法向抬起的距离（Å），避免和等值面 z-fighting。
    segments : int
        圆周分段数。
    style : dict, optional
        覆盖 :data:`ARROW_STYLE` 的比例。
    clip_plane : ((ox, oy, oz), (nx, ny, nz)), optional
        用"过 o 点、法向 n"的平面过滤箭头（保留 n 的负侧），对应
        :func:`render_aicd_montage` 的 ``clip_plane``。

    Returns
    -------
    dict or None
        与 :func:`build_arrow_geometry` 同形；没有采样点时返回 ``None``。
    """
    if volume.vectors is None:
        raise ValueError("AICDVolume 里没有 vectors，先用 with_vectors=True 计算")
    f = np.asarray(volume.field, dtype=np.float64)
    spacing = float(volume.spacing)
    grads = np.gradient(f, spacing)
    gmag = np.sqrt(sum(g * g for g in grads))
    with np.errstate(divide="ignore", invalid="ignore"):
        dist = np.abs(f - iso) / np.maximum(gmag, 1e-9)
    mask = dist <= float(shell) * spacing

    vectors = np.asarray(volume.vectors, dtype=np.float64)
    mag = np.linalg.norm(vectors, axis=-1)
    if magnitude_floor > 0:
        mask &= mag > float(magnitude_floor)
    idx = np.argwhere(mask)
    if decimate and decimate > 1:
        idx = idx[(idx[:, 0] % decimate == 0) & (idx[:, 1] % decimate == 0)
                  & (idx[:, 2] % decimate == 0)]
    if len(idx) == 0:
        return None

    ii, jj, kk = idx[:, 0], idx[:, 1], idx[:, 2]
    p = np.asarray(volume.origin, dtype=np.float64) + idx * spacing
    g = np.stack([grads[0][ii, jj, kk], grads[1][ii, jj, kk],
                  grads[2][ii, jj, kk]], axis=1)
    gm = np.linalg.norm(g, axis=1)
    good = gm > 1e-12
    if not good.all():
        idx, p, g, gm = idx[good], p[good], g[good], gm[good]
        ii, jj, kk = idx[:, 0], idx[:, 1], idx[:, 2]
        if len(idx) == 0:
            return None
    # 一阶投影到等值面：p_surf = p + (iso - f) * grad / |grad|²
    p_surf = p + ((float(iso) - f[ii, jj, kk]) / (gm * gm))[:, None] * g
    n_out = -g / gm[:, None]                 # 梯度指向面内，取反为外法向
    J = vectors[ii, jj, kk]
    jm = np.linalg.norm(J, axis=1)
    if clip_plane is not None:
        origin_pt = np.asarray(clip_plane[0], dtype=np.float64).reshape(3)
        normal = np.asarray(clip_plane[1], dtype=np.float64).reshape(3)
        normal = normal / max(np.linalg.norm(normal), 1e-12)
        keep = (p_surf - origin_pt) @ normal <= 0.0
        p_surf, n_out, J, jm = (p_surf[keep], n_out[keep], J[keep], jm[keep])
        if len(jm) == 0:
            return None
    good = jm > 1e-12
    if not good.all():
        p_surf, n_out, J, jm = (p_surf[good], n_out[good], J[good], jm[good])
        if len(jm) == 0:
            return None

    st = dict(ARROW_STYLE)
    if style:
        st.update(style)
    st["mean_length"] = float(mean_length)
    mean = jm.mean()
    length = st["mean_length"] * jm / mean
    keep = np.ones(len(jm), dtype=bool)
    if min_arrow and min_arrow > 0:
        keep &= length >= float(min_arrow) * st["mean_length"]
    if max_arrow and max_arrow > 0:
        keep &= length <= float(max_arrow) * st["mean_length"]
    if not keep.all():
        p_surf, n_out, J, jm = (p_surf[keep], n_out[keep], J[keep], jm[keep])
        if len(jm) == 0:
            return None
        mean = jm.mean()
        length = st["mean_length"] * jm / mean

    Jhat = J / jm[:, None]
    # AICD 规则：J 朝面外 -> 从面出发向外；J 朝面内 -> 箭尖落在面上、杆在面外。
    # 两种情况下箭头方向都保持 **J 本身**（AICD 的 Pfeil(A,B) 是从 A 指向 B，
    # 内指时 A=Origin-J、B=Origin，箭头仍沿 +J）。早期版本把内指箭头取反，
    # 画出来环电流方向会一半反、看起来像放射状，必须保持 +J。
    inward = np.einsum("ij,ij->i", Jhat, n_out) < 0.0
    base = p_surf + n_out * float(offset)
    if inward.any():
        base[inward] = (p_surf[inward] - Jhat[inward] * length[inward, None]
                        + n_out[inward] * float(offset))
    vec = J.copy()
    geo = build_arrow_geometry(base, vec, style=st, segments=segments,
                               min_length=0.0, max_length=None)
    geo["bases"] = base                 # 诊断/测试用：箭头起点（面外）
    geo["normals"] = n_out
    geo["inward"] = inward
    return geo


def write_cube(path, origin, spacing, field, atoms, comment="AICD"):
    """写 Gaussian cube 文件。

    坐标一律按标准 cube 约定写成 **Bohr**（MolStudio 的渲染内核、GaussView、
    Multiwfn 都按 Bohr 读），数据值保持 a.u.；因此调用方传进来的 Å 会乘
    ``ANGSTROM_TO_BOHR``。
    """
    field = np.asarray(field, dtype=np.float64)
    nx, ny, nz = field.shape
    atoms = list(atoms)
    a2b = 1.0 / _BOHR
    origin_b = np.asarray(origin, dtype=np.float64) * a2b
    spacing_b = float(spacing) * a2b
    with open(path, "w") as fh:
        fh.write(f"{comment}\n")
        fh.write("Generated by MolStudio (AICD module)\n")
        fh.write(f"{len(atoms):5d}{origin_b[0]:13.6f}{origin_b[1]:13.6f}{origin_b[2]:13.6f}\n")
        for axis, n in enumerate((nx, ny, nz)):
            step = np.zeros(3)
            step[axis] = spacing_b
            fh.write(f"{n:5d}{step[0]:13.6f}{step[1]:13.6f}{step[2]:13.6f}\n")
        for z, x, y, zz in atoms:
            fh.write(f"{int(z):5d}{float(z):13.6f}"
                     f"{x * a2b:13.6f}{y * a2b:13.6f}{zz * a2b:13.6f}\n")
        flat = field.ravel(order="C")
        for i in range(0, flat.size, 6):
            chunk = flat[i:i + 6]
            fh.write("".join(f"{v:13.5E}" for v in chunk) + "\n")
    return str(path)


# ── 一站式调用 ─────────────────────────────────────────────────────────

def compute_aicd(tensor_file, log_file=None, quantity="Aniso",
                 field=(0.0, 0.0, 1.0), spacing=0.25, padding=2.5,
                 with_vectors=False, max_nodes=6_000_000,
                 progress=None):
    """跑一遍 AICD 流程并返回 :class:`AICDVolume`。

    Parameters
    ----------
    tensor_file : str
        Gaussian 的 AICD 张量转储（``IOp(10/93=1)`` 那一步写出的 txt）。
    log_file : str, optional
        同一个任务的 Gaussian 输出，用来取分子几何（标准取向）。
    quantity : str
        ``Aniso`` / ``FullAniso`` / ``AntiSymmAniso`` / ``Iso``。
    field : tuple
        外磁场方向（只需方向，AICD 里用 ``-b`` 指定）。
    spacing : float
        规则网格间距（Å）。越小越细腻、越慢。
    padding : float
        网格在分子外留的余量（Å）。
    with_vectors : bool
        是否一并插值出感应电流矢量场（画箭头用）。
    """
    def report(msg):
        if progress:
            progress(msg)

    report("读取 AICD 张量数据…")
    data = parse_tensor_dump(tensor_file)
    report(f"  格点 {len(data)} 个")
    values = scalar_field(data.tensors, quantity)
    report(f"  标量场 {quantity}：最小 {values.min():.4f}，最大 {values.max():.4f}")

    atoms = read_standard_orientation(log_file) if log_file else []
    origin, spacing, shape = build_grid(data.points, spacing=spacing,
                                        padding=padding, max_nodes=max_nodes,
                                        atoms=atoms)
    report(f"  规则网格 {shape[0]}×{shape[1]}×{shape[2]}（间距 {spacing:.3f} Å）")

    # 只留下网格附近的散点参与插值（远处的格点数值本来就趋于 0）
    lo = origin - 1.5
    hi = origin + spacing * (np.asarray(shape) - 1) + 1.5
    keep = np.all((data.points >= lo) & (data.points <= hi), axis=1)
    report(f"  参与插值的格点 {int(keep.sum())} / {len(data)}")
    points = data.points[keep]
    values = values[keep]

    report("插值到规则网格…")
    field_grid = remap_to_grid(points, values, origin, spacing, shape)

    vectors = None
    if with_vectors:
        report("插值感应电流矢量场…")
        j = current_density(data.tensors[keep], field)
        vectors = remap_vectors_to_grid(points, j, origin, spacing, shape)

    meta = {
        "n_grid_points": int(len(data)),
        "source": os.path.basename(str(tensor_file)),
        "field": tuple(float(v) for v in np.asarray(field).reshape(3)),
        "spacing": float(spacing),
        "vmin": float(values.min()),
        "vmax": float(values.max()),
    }
    return AICDVolume(origin, spacing, np.nan_to_num(field_grid), atoms,
                      quantity=quantity, vectors=vectors, metadata=meta)
