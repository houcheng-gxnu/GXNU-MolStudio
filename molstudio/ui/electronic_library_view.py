# -*- coding: utf-8 -*-
"""「电子结构库」浏览页：原子轨道 / 杂化轨道的解析等值面。

和 CrystalLibraryView 一样是「左列表 + 右详情 + 顶部分类筛选」的结构，但
缩略图是**真实等值面的 3D 小渲染**（不写文件，直接在本页抽面 + 正交投影）：
哑铃、四叶草、八瓣、一头大一头小的杂化，和在画布上转出来的是同一份数据、
同一个视角。学生的直觉是"哑铃""花瓣"，所以不给 2D 截面图 —— 那个只有懂行的
人看得出来是 p_z 还是 d_z²。

本页只负责选择与参数，**不碰画布、不写文件**；载入动作通过
``visualizeRequested`` 与 ``on_visualize_orbital`` 交给主窗口。
"""
from __future__ import annotations

import math
import re

import numpy as np
from PyQt5.QtCore import QPointF, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import (
    QColor, QIcon, QPainter, QPixmap, QPolygonF,
)
from PyQt5.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QScrollArea, QSplitter,
    QVBoxLayout, QWidget,
)

from molstudio.core.atomic_orbital import (
    GROUP_LABELS, GROUP_ORDER, MIN_ISOVALUE, orbital_library,
)

_TEXT = {
    "zh": {
        "all": "全部分类",
        "search": "搜索轨道、角量子数或教学点…",
        "quality": "网格精度",
        "quality_low": "低（49³）",
        "quality_medium": "中（65³）",
        "quality_high": "高（81³）",
        "iso": "等值面 iso",
        "empty": "没有找到匹配的轨道",
        "quantum": "主量子数 n = {n}　角量子数 l = {l}",
        "model_hyd": "径向模型：类氢 R_nl(r)（含径向节点）",
        "model_sto": "径向模型：无节点 Slater 型（ζ = {zeta:g}）",
        "model_shell": "径向模型：同壳层 Slater 型（n = {n}，ζ = {zeta:g}）",
        "nodes": "节面：{value}",
        "note": "教学要点：{value}",
        "grid": "基准网格半边长：{extent:g} a₀　峰值：{peak:.4g} a.u.",
        "scale_note": "写入 cube 前场按峰值线性归一化到 ±1，形状与节点位置不变；"
                      "画布 iso 下限为 0.005，不归一化时 4f 等轨道会被整块钳掉。"
                      "iso 较小时立方体会按等值面自动外扩（f 轨道在 iso=0.005 时约"
                      " 1.9 倍），保证瓣尖不被截断。",
        "terms": "组成：{value}",
        "source": "解析波函数（实球谐 + 类氢 / STO 径向），非实验数据",
    },
    "en": {
        "all": "All groups",
        "search": "Search orbital, angular momentum or topic…",
        "quality": "Grid quality",
        "quality_low": "Low (49^3)",
        "quality_medium": "Medium (65^3)",
        "quality_high": "High (81^3)",
        "iso": "Isovalue",
        "empty": "No matching orbital",
        "quantum": "n = {n}   l = {l}",
        "model_hyd": "Radial model: hydrogenic R_nl(r), with radial nodes",
        "model_sto": "Radial model: nodeless Slater type (zeta = {zeta:g})",
        "model_shell": "Radial model: same-shell Slater type (n = {n}, zeta = {zeta:g})",
        "nodes": "Nodes: {value}",
        "note": "Teaching note: {value}",
        "grid": "Reference grid half-width: {extent:g} a0   peak: {peak:.4g} a.u.",
        "scale_note": "The field is linearly scaled to max|psi| = 1 before "
                      "writing the cube: shape and node positions are unchanged. "
                      "The canvas clamps iso at 0.005, which would hide 4f etc. "
                      "For small isovalues the cube expands automatically until "
                      "the isosurface closes (f orbitals need ~1.9x at iso = "
                      "0.005), so lobe tips are never cut off.",
        "terms": "Composition: {value}",
        "source": "Analytic wavefunction (real spherical harmonics + hydrogenic/STO radial)",
    },
}

# 正 / 负相位色（与经典蓝主题协调）
_POS_RGB = (43, 108, 176)     # #2B6CB0 蓝
_NEG_RGB = (224, 83, 59)      # #E0533B 橙

# 缩略图的光照方向（视图空间，指向光源）。与画布的四光源不同，这里只用一盏
# 左上前方的灯：小球面上够看出立体，又不会把相位色打亮成白点。
_LIGHT_DIR = np.array([-0.42, 0.55, 0.72], dtype=np.float64)
_LIGHT_DIR /= np.linalg.norm(_LIGHT_DIR)


def _view_matrix():
    """世界 → 视图的旋转矩阵，**与主画布同一套视角**。

    ``main_window._orbital_view_quat()`` 用的是 ``R_y(25°)·R_x(-60°)``；
    缩略图也照抄，列表里的哑铃 / 花瓣和在画布上转出来的形状就是同一个朝向，
    学生不用自己脑补。"沿 z 轴俯视"会把 p_z 的两瓣叠成一个圆，必须斜着看。
    """
    cx, sx = np.cos(np.radians(-60.0)), np.sin(np.radians(-60.0))
    cy, sy = np.cos(np.radians(25.0)), np.sin(np.radians(25.0))
    rx = np.array([[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]])
    ry = np.array([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]])
    return ry @ rx


_P_TERM_AXIS = {"px": (1.0, 0.0, 0.0), "py": (0.0, 1.0, 0.0), "pz": (0.0, 0.0, 1.0)}


def _lobe_axis(spec):
    """杂化轨道正瓣的朝向（单位向量）；纯轨道返回 None。

    杂化轨道的方向完全由 p 分量决定（s 分量是球对称的），系数即分量。
    纯 s 没有方向，纯 p / d / f 的瓣不止一对，也不该硬拧，所以只处理杂化。
    """
    if spec.group != "hybrid":
        return None
    v = np.zeros(3)
    for key, coef in spec.terms:
        axis = _P_TERM_AXIS.get(key)
        if axis is not None:
            v += np.asarray(axis) * float(coef)
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else None


def _straighten(rot, axis, max_axial=0.80, target_axial=0.40):
    """若瓣轴几乎正对相机（投影成圆球），把物体绕原点拧到屏幕平面里。

    缩略图用固定视角 R_y(25°)·R_x(−60°)。杂化轨道的瓣轴各不相同，总有一两条
    恰好与视线平行 —— sp² (3/3)、sp³ (4/4) 实测 |cos| ≈ 0.89 / 0.96，
    画出来就是一个蓝球，和 1s 完全分不开，学生会以为那两格坏了。

    修法不是给这几条换视角（列表里图标会变得东倒西歪），而是**只在退化时**
    沿最短弧旋转，把瓣轴与视线的夹角拧到 ~66°（|cos| = 0.40）：既露出
    一头大一头小的轮廓，又保留各自的朝向差异。
    """
    va = rot @ axis
    va = va / max(float(np.linalg.norm(va)), 1e-12)
    if abs(va[2]) <= max_axial:
        return rot
    sign = 1.0 if va[2] > 0 else -1.0
    radial = np.array([va[0], va[1], 0.0])
    nr = float(np.linalg.norm(radial))
    if nr < 1e-6:
        radial = np.array([1.0, 0.0, 0.0])     # 正对相机：随便挑一个屏幕内方向
    else:
        radial /= nr
    want = math.sqrt(max(1.0 - target_axial ** 2, 0.0)) * radial \
        + np.array([0.0, 0.0, sign * target_axial])
    want /= max(float(np.linalg.norm(want)), 1e-12)
    k = np.cross(va, want)
    nk = float(np.linalg.norm(k))
    if nk < 1e-9:
        return rot
    k /= nk
    ang = math.acos(float(np.clip(np.dot(va, want), -1.0, 1.0)))
    c, s = math.cos(ang), math.sin(ang)
    kx = np.array([[0.0, -k[2], k[1]], [k[2], 0.0, -k[0]], [-k[1], k[0], 0.0]])
    r_vs = c * np.eye(3) + s * kx + (1.0 - c) * np.outer(k, k)
    return r_vs @ rot


def _iso_surfaces(spec, n=None, iso=None):
    """等值面抽取的薄封装（实现已移到 :mod:`molstudio.core.atomic_orbital`）。

    画布、缩略图、PPT 3D 导出必须用**同一份**抽面规则：放大立方体直到等值面
    闭合，否则瓣尖会被边界切掉。核心函数返回 Bohr 坐标。
    """
    from molstudio.core.atomic_orbital import iso_surfaces
    return iso_surfaces(spec, n=n, iso=iso)


def default_view_matrix(spec=None):
    """世界 → 视图旋转：与画布 / 缩略图同一套斜视角，导出 .glb 时沿用。

    ``main_window._orbital_view_quat()`` 用的是 ``R_y(25°)·R_x(-60°)``；
    这里返回同一矩阵。杂化轨道的瓣轴若正对相机（sp² 3/3、sp³ 4/4 实测
    ``|cos| ≈ 0.89 / 0.96``），再按 :func:`_straighten` 拧进屏幕平面，
    否则导入 PowerPoint 的模型一开始看起来就是一颗圆球。
    """
    rot = _view_matrix()
    axis = _lobe_axis(spec) if spec is not None else None
    if axis is not None:
        rot = _straighten(rot, axis)
    return rot


def _rgb01(rgb):
    return np.array(rgb, dtype=np.float64) / 255.0


def orbital_thumbnail(spec, width=240, height=170, samples=None):
    """轨道缩略图 = **真实等值面的 3D 小渲染**（蓝 = ψ>0，橙 = ψ<0）。

    以前这里画的是 ``z = 0`` 平面上的波函数截面。物理上没问题，但只有懂行的
    人看得出那是 p_z / d_z²；学生的直觉是"哑铃""花瓣""一头大一头小"，截面图
    对不上这些印象。现在直接抽等值面：

    * 顶点乘上 :func:`_view_matrix` 转到视图空间，正交投影到 2D；杂化轨道再
      经 :func:`_straighten` 纠偏，避免瓣轴正对相机时缩略图退化成一颗圆球；
    * **背面剔除**：等值面是闭合的，朝后的三角形永远被前面挡住，剔掉能省一半
      三角形，也不会出现"内壁透出来变深色斑"的假象；
    * 剩下的按质心深度从远到近画（painter's algorithm）—— 波瓣是凸的，
      这个顺序足够正确，不必上 z-buffer；
    * 亮度 = 环境项 0.38 + 漫反射 0.62·max(0, N·L)，背面不额外压暗 ——
      压暗会让远端的瓣发黑，看起来像脏了。

    内部按 2 倍分辨率渲染再平滑缩小，等于免费抗锯齿（不开 QPainter 的
    Antialiasing 是为了避免相邻三角形之间出现发丝一样的亮缝）。
    """
    pos, neg = _iso_surfaces(spec, samples)

    rot = default_view_matrix(spec)
    parts = []
    allv = []
    for surf, rgb in ((pos, _POS_RGB), (neg, _NEG_RGB)):
        if surf is None or getattr(surf, "vertex_count", 0) == 0:
            continue
        verts = np.asarray(surf.vertices, dtype=np.float64) @ rot.T
        norms = np.asarray(surf.normals, dtype=np.float64) @ rot.T
        norm_len = np.linalg.norm(norms, axis=1, keepdims=True)
        norms = norms / np.maximum(norm_len, 1e-12)
        tri = np.asarray(surf.indices, dtype=np.int64).reshape(-1, 3)
        # 面法线 = 三个顶点法线的平均；z ≤ 0 的三角形背对相机，直接丢掉。
        face_n = norms[tri].sum(axis=1)
        tri = tri[face_n[:, 2] > 0.0]
        if tri.size == 0:
            continue
        parts.append((verts, norms, tri, _rgb01(rgb)))
        allv.append(verts)
    if not allv:
        return QIcon()

    # 2 倍超采样 + 按包围盒等比缩放（切到画布时物体铺满画面，缩略图同理）
    ss = 2
    side = int(max(width, height)) * ss
    pts = np.concatenate(allv, axis=0)
    lo, hi = pts[:, :2].min(axis=0), pts[:, :2].max(axis=0)
    span = float(max(hi[0] - lo[0], hi[1] - lo[1])) or 1.0
    scale = (side - 10) / span
    mid = (lo + hi) * 0.5

    img = QPixmap(side, side)
    img.fill(QColor("#FFFFFF"))
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing, False)
    painter.setPen(Qt.NoPen)

    tri_list = []
    for verts, norms, tri, rgb in parts:
        if tri.size == 0:
            continue
        sx = (verts[:, 0] - mid[0]) * scale + side * 0.5
        sy = side * 0.5 - (verts[:, 1] - mid[1]) * scale
        depth = verts[:, 2]
        vx, vy = sx[tri], sy[tri]
        tri_depth = depth[tri].mean(axis=1)
        # 面法线 = 三个顶点法线求平均，做平面着色（缩略图只有一百多像素，
        # 逐像素光照看不出来，平面着色反而更"实"）
        nx = norms[tri].mean(axis=1)
        lam = np.clip(nx @ _LIGHT_DIR, 0.0, 1.0)
        shade = 0.38 + 0.62 * lam
        colors = np.clip(rgb[None, :] * shade[:, None] * 255.0, 0, 255)
        tri_list.append((tri_depth, vx, vy, colors.astype(np.uint8)))

    # 全部三角形合并后统一按深度排序：远（视空间 z 小）先画。
    depth = np.concatenate([t[0] for t in tri_list])
    vx = np.concatenate([t[1] for t in tri_list])
    vy = np.concatenate([t[2] for t in tri_list])
    cols = np.concatenate([t[3] for t in tri_list])
    order = np.argsort(depth)
    cache = {}
    poly = QPolygonF()
    for i in order:
        key = int(cols[i, 0]) << 16 | int(cols[i, 1]) << 8 | int(cols[i, 2])
        brush = cache.get(key)
        if brush is None:
            brush = QColor(int(cols[i, 0]), int(cols[i, 1]), int(cols[i, 2]))
            cache[key] = brush
        painter.setBrush(brush)
        poly.clear()
        poly.append(QPointF(float(vx[i, 0]), float(vy[i, 0])))
        poly.append(QPointF(float(vx[i, 1]), float(vy[i, 1])))
        poly.append(QPointF(float(vx[i, 2]), float(vy[i, 2])))
        painter.drawPolygon(poly)
    painter.end()

    pix = QPixmap(width, height)
    pix.fill(QColor("#FFFFFF"))
    out = QPainter(pix)
    out.setRenderHint(QPainter.SmoothPixmapTransform, True)
    box = min(width, height)
    out.drawPixmap((width - box) // 2, (height - box) // 2, box, box,
                   img, 0, 0, side, side)
    out.end()
    return QIcon(pix)


class ElectronicLibraryView(QWidget):
    """原子轨道 / 杂化轨道浏览器。"""

    visualizeRequested = pyqtSignal()
    currentEntryChanged = pyqtSignal(object)

    def __init__(self, parent=None, lang="zh"):
        super().__init__(parent)
        self.lang = "zh" if str(lang).lower().startswith("zh") else "en"
        self._specs = orbital_library()
        self._by_id = {s.id: s for s in self._specs}
        self._icons = {}
        self._items = {}
        self._icon_queue = []
        self._icon_timer = None
        self._peak_cache = {}
        self._build_ui()
        self.set_language(self.lang)

    def _t(self, key, **fmt):
        table = _TEXT.get(self.lang) or _TEXT["zh"]
        text = table.get(key, _TEXT["zh"].get(key, key))
        return text.format(**fmt) if fmt else text

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(6)

        filters = QHBoxLayout()
        self.cmb_group = QComboBox()
        self.cmb_group.addItem("", "all")
        for key in GROUP_ORDER:
            self.cmb_group.addItem("", key)
        self.cmb_group.currentIndexChanged.connect(self._refresh_list)
        filters.addWidget(self.cmb_group)
        self.edit_search = QLineEdit()
        self.edit_search.setClearButtonEnabled(True)
        self.edit_search.textChanged.connect(self._refresh_list)
        filters.addWidget(self.edit_search, 1)
        root.addLayout(filters)

        body = QSplitter(Qt.Horizontal)
        body.setChildrenCollapsible(False)
        self.list_widget = QListWidget()
        self.list_widget.setViewMode(QListWidget.IconMode)
        self.list_widget.setResizeMode(QListWidget.Adjust)
        self.list_widget.setMovement(QListWidget.Static)
        self.list_widget.setIconSize(QSize(150, 110))
        self.list_widget.setGridSize(QSize(180, 150))
        self.list_widget.setSpacing(5)
        self.list_widget.setWordWrap(True)
        self.list_widget.currentItemChanged.connect(self._on_current_changed)
        self.list_widget.itemDoubleClicked.connect(
            lambda _item: self.visualizeRequested.emit())
        body.addWidget(self.list_widget)
        body.setStretchFactor(0, 3)
        body.setStretchFactor(1, 2)

        detail = QFrame()
        detail.setObjectName("ElectronicLibraryDetail")
        detail.setStyleSheet(
            "QFrame#ElectronicLibraryDetail{background:#F8FAFC;"
            "border:1px solid #D8E1EC;border-radius:10px;}")
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(10, 10, 10, 10)
        dl.setSpacing(6)
        self.lbl_preview = QLabel()
        self.lbl_preview.setAlignment(Qt.AlignCenter)
        # 预览图宽度必须让着右栏：结构库这一页只有 ~320px 可用，原来
        # 300×210 的 pixmap 把详情框的最小宽度顶到 320 以上，整块被挤出
        # 窗口右边界（实测文字与缩略图都被裁掉）。
        self.lbl_preview.setMinimumHeight(130)
        self.lbl_preview.setStyleSheet(
            "background:white;border:1px solid #E2E8F0;border-radius:8px;")
        dl.addWidget(self.lbl_preview, 1)

        self.lbl_name = QLabel()
        self.lbl_name.setWordWrap(True)
        self.lbl_name.setStyleSheet(
            "font-size:16px;font-weight:700;color:#0F172A;")
        dl.addWidget(self.lbl_name)

        self.lbl_details = QLabel()
        self.lbl_details.setWordWrap(True)
        self.lbl_details.setStyleSheet("color:#475569;")
        dl.addWidget(self.lbl_details, 2)

        # 等值面 / 精度控件排成 **2×2** 而不是一行：一行时这四个控件的最小宽度
        # 是 518px，正好等于详情框的全部可用宽度，于是 QSplitter 把详情框
        # 顶出窗口右边界（实测缩略图与详情文字都被裁掉）。拆成两行后最小
        # 宽度降到 ~240px，右栏怎么压都不溢出。
        opts = QGridLayout()
        opts.setContentsMargins(0, 0, 0, 0)
        opts.setHorizontalSpacing(6)
        opts.setVerticalSpacing(4)
        self.lbl_iso = QLabel()
        opts.addWidget(self.lbl_iso, 0, 0)
        self.spin_iso = QDoubleSpinBox()
        self.spin_iso.setRange(MIN_ISOVALUE, 0.30)
        self.spin_iso.setSingleStep(0.005)
        self.spin_iso.setDecimals(3)
        self.spin_iso.setValue(0.08)
        self.spin_iso.setFixedWidth(90)
        opts.addWidget(self.spin_iso, 0, 1)
        self.lbl_quality = QLabel()
        opts.addWidget(self.lbl_quality, 1, 0)
        self.cmb_quality = QComboBox()
        for key in ("low", "medium", "high"):
            self.cmb_quality.addItem("", key)
        self.cmb_quality.setCurrentIndex(1)
        opts.addWidget(self.cmb_quality, 1, 1)
        opts.setColumnStretch(2, 1)
        dl.addLayout(opts)

        self.lbl_scale = QLabel()
        self.lbl_scale.setWordWrap(True)
        self.lbl_scale.setStyleSheet(
            "color:#1E40AF;background:#EFF6FF;border:1px solid #BFDBFE;"
            "border-radius:6px;padding:6px;font-size:11px;")
        dl.addWidget(self.lbl_scale, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(detail, 1)
        scroll.setWidget(holder)
        body.addWidget(scroll)
        body.setStretchFactor(0, 3)
        body.setStretchFactor(1, 2)
        body.setSizes([620, 400])
        root.addWidget(body, 1)

    # ── 语言 ──
    def set_language(self, lang):
        self.lang = "zh" if str(lang).lower().startswith("zh") else "en"
        self.edit_search.setPlaceholderText(self._t("search"))
        self.cmb_group.setItemText(0, self._t("all"))
        for i, key in enumerate(GROUP_ORDER, start=1):
            zh, en = GROUP_LABELS[key]
            self.cmb_group.setItemText(i, en if self.lang == "en" else zh)
        for i, key in enumerate(("low", "medium", "high")):
            self.cmb_quality.setItemText(i, self._t("quality_" + key))
        self.lbl_iso.setText(self._t("iso"))
        self.lbl_iso.setToolTip(self._t("scale_note"))
        self.spin_iso.setToolTip(self._t("scale_note"))
        self.lbl_quality.setText(self._t("quality"))
        self.lbl_scale.setText(self._t("scale_note"))
        self.lbl_scale.setToolTip(self._t("scale_note"))
        self.lbl_scale.setVisible(self.lang == "zh")
        self._refresh_list()

    # ── 数据 ──
    def _icon(self, spec):
        if spec.id not in self._icons:
            self._icons[spec.id] = orbital_thumbnail(spec)
        return self._icons[spec.id]

    def _peak(self, spec):
        """网格峰值（a.u.），缓存；用于详情里说明归一化前的量级。"""
        if spec.id not in self._peak_cache:
            from molstudio.core.atomic_orbital import generate_field
            _f, _o, _s, peak = generate_field(spec, "low")
            self._peak_cache[spec.id] = peak
        return self._peak_cache[spec.id]

    def _matches(self, spec, text):
        if not text:
            return True
        q = text.strip().lower()
        hay = " ".join((spec.id, spec.label_zh, spec.label_en,
                        spec.group, spec.group_label("zh"),
                        spec.group_label("en"), spec.nodes_zh, spec.nodes_en,
                        spec.note_zh, spec.note_en)).lower()
        return q in hay

    def _refresh_list(self, *_args):
        current = self.current_spec()
        group = self.cmb_group.currentData() or "all"
        text = self.edit_search.text()
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        self._items = {}
        choose = None
        for spec in self._specs:
            if group != "all" and spec.group != group:
                continue
            if not self._matches(spec, text):
                continue
            # 图标先留空，之后再逐个填 —— 一张 3D 缩略图要 10~60ms，
            # 27 张一次算完会让「电子结构」页第一次打开卡住近一秒。
            item = QListWidgetItem(spec.display_name(self.lang))
            item.setData(Qt.UserRole, spec.id)
            item.setToolTip("%s · %s" % (spec.id, spec.group_label(self.lang)))
            item.setSizeHint(QSize(176, 144))
            self.list_widget.addItem(item)
            self._items[spec.id] = item
            if current is not None and current.id == spec.id:
                choose = item
        self.list_widget.blockSignals(False)
        if choose is None and self.list_widget.count():
            choose = self.list_widget.item(0)
        if choose is not None:
            self.list_widget.setCurrentItem(choose)
        self._on_current_changed(self.list_widget.currentItem(), None)
        # 列表已经能看了，图标排队补上（每帧一张，单帧最多 60ms）
        self._icon_queue = [str(self.list_widget.item(i).data(Qt.UserRole))
                            for i in range(self.list_widget.count())]
        if self.isVisible():
            self._start_icon_queue()

    def _start_icon_queue(self):
        if not self._icon_queue:
            return
        if self._icon_timer is None:
            self._icon_timer = QTimer(self)
            self._icon_timer.setInterval(0)
            self._icon_timer.timeout.connect(self._pump_icon_queue)
        if not self._icon_timer.isActive():
            self._icon_timer.start()

    def _pump_icon_queue(self):
        """一次补一张图标。选择顺序 = 列表顺序，所以上面的先出现。"""
        while self._icon_queue:
            ident = self._icon_queue.pop(0)
            spec = self._by_id.get(ident)
            item = self._items.get(ident)
            if spec is None or item is None:
                continue
            item.setIcon(self._icon(spec))
            break
        if not self._icon_queue and self._icon_timer is not None:
            self._icon_timer.stop()

    def showEvent(self, event):
        """第一次真正显示时才去算缩略图（3D 抽面 + 投影，每张十几毫秒）。"""
        super().showEvent(event)
        self._start_icon_queue()

    def hideEvent(self, event):
        if self._icon_timer is not None:
            self._icon_timer.stop()
        super().hideEvent(event)

    def current_spec(self):
        item = self.list_widget.currentItem()
        if item is None:
            return None
        return self._by_id.get(str(item.data(Qt.UserRole)))

    def iso(self):
        return float(self.spin_iso.value())

    def quality(self):
        return str(self.cmb_quality.currentData() or "medium")

    def current_source(self):
        return self._t("source")

    def _on_current_changed(self, current, _previous):
        spec = self._by_id.get(str(current.data(Qt.UserRole))) \
            if current else None
        if spec is None:
            self.lbl_preview.clear()
            self.lbl_name.setText(self._t("empty"))
            self.lbl_details.clear()
            self.currentEntryChanged.emit(None)
            return

        icon = self._icon(spec)
        self.lbl_preview.setPixmap(
            icon.pixmap(QSize(208, 146)))
        self.lbl_name.setText(spec.display_name(self.lang))

        n_text = ("—" if spec.n is None else str(spec.n))
        if spec.radial == "hydrogenic":
            model_line = self._t("model_hyd")
        elif spec.radial == "sto_shell":
            model_line = self._t("model_shell", n=spec.n, zeta=spec.zeta)
        else:
            model_line = self._t("model_sto", zeta=spec.zeta)
        lines = [
            self._t("quantum", n=n_text, l=spec.l),
            model_line,
            self._t("nodes", value=spec.nodes(self.lang)),
            self._t("note", value=spec.note(self.lang)),
        ]
        if len(spec.terms) > 1:
            comp = "  ".join("%+.3f %s" % (c, k)
                             for k, c in spec.terms)
            lines.append(self._t("terms", value=comp))
        lines.append(self._t("grid", extent=spec.extent,
                             peak=self._peak(spec)))
        self.lbl_details.setText("\n".join(line for line in lines if line))

        # 每条轨道带自己的建议 iso（2s/3s 外瓣弱，需要更小的值）
        self.spin_iso.blockSignals(True)
        self.spin_iso.setValue(float(spec.iso_hint))
        self.spin_iso.blockSignals(False)
        self.currentEntryChanged.emit(spec)
