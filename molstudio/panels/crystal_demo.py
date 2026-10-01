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

# 直接运行本文件时把仓库根目录加入 sys.path（包方式导入不需要）
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtCore import QPointF  # noqa: E402
from PyQt5.QtGui import QColor, QPainter, QPen, QSurfaceFormat  # noqa: E402
from PyQt5.QtWidgets import (QApplication, QCheckBox, QFileDialog,  # noqa: E402
                             QHBoxLayout, QLabel, QMainWindow, QPushButton,
                             QSpinBox, QVBoxLayout, QWidget)

# 与画布同一套 GL 设置（必须在 QApplication 之前设好）
_fmt = QSurfaceFormat()
_fmt.setSamples(0)
_fmt.setDepthBufferSize(24)
_fmt.setVersion(3, 3)
_fmt.setProfile(QSurfaceFormat.CoreProfile)
QSurfaceFormat.setDefaultFormat(_fmt)

from molstudio.render.ovcanvas import OVCanvas                      # noqa: E402
from molstudio.render.ovcanvas._glwidget import BOHR_TO_ANGSTROM, CubGLWidget  # noqa: E402

# ── 元素符号（1..103）─────────────────────────────────────────────────

# 解析 / 晶胞 / 晶胞框等纯逻辑在 crystal_lib 里（面板也用它）
from molstudio.core.crystal_lib import (Crystal, cell_matrix, element_symbol,   # noqa: E402
                           parse_cif, parse_poscar, install_cell_box)
class CrystalDemoWindow(QMainWindow):
    """画布 + 载入按钮 + 样式按钮的极简晶体查看器。"""

    # 一键样式：直通 MolStudio 画布自己的那几个按钮（保证与主程序一致）
    STYLES = (("MolStudio", "_apply_molstudio_style"),
              ("sob-art", "_apply_sobart_style"),
              ("IBOview", "_apply_iboview_style"),
              ("HoukMol", "_apply_houkmol_style"),
              ("CYLview", "_apply_cylview_style"),
              ("IQmol", "_apply_iqmol_style"))

    def __init__(self, path=None):
        super().__init__()
        self.setWindowTitle("MolStudio 晶体可视化 Demo — CIF / POSCAR")
        self.resize(1500, 900)
        self.crystal = None

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        # ── 顶栏：载入 / 超胞 / 晶胞框 / 样式 ──
        bar = QHBoxLayout()
        self.btn_open = QPushButton("载入 CIF / MOL2 / POSCAR…")
        self.btn_open.clicked.connect(self.open_file)
        bar.addWidget(self.btn_open)
        # 扩晶胞：a / b / c 三个方向分别扩（2×2×1 做板层、1×1×3 沿 c 拉长）
        bar.addWidget(QLabel("扩晶胞:"))
        self.sp_reps = []
        for axis in "abc":
            if axis != "a":
                bar.addWidget(QLabel("×"))
            sp = QSpinBox()
            sp.setRange(1, 6)
            sp.setValue(1)
            sp.setFixedWidth(52)
            sp.setToolTip("沿 %s 方向重复几个晶胞（1–6）" % axis)
            sp.valueChanged.connect(self._rebuild)
            bar.addWidget(sp)
            self.sp_reps.append(sp)
        self._applied_reps = (1, 1, 1)
        btn_super_reset = QPushButton("复位")
        btn_super_reset.setObjectName("SmallBtn")
        btn_super_reset.setToolTip("扩晶胞回到 1×1×1")
        btn_super_reset.clicked.connect(
            lambda: self._set_reps(1, 1, 1, rebuild=True))
        bar.addWidget(btn_super_reset)
        self.chk_box = QCheckBox("晶胞框")
        self.chk_box.setChecked(True)
        self.chk_box.toggled.connect(lambda _v: self.canvas.glw.update())
        bar.addWidget(self.chk_box)
        self.chk_boundary = QCheckBox("边界原子补齐")
        self.chk_boundary.setChecked(True)
        self.chk_boundary.setToolTip(
            "晶胞顶点 / 棱 / 面上的原子，在所有等价位置都画出来\n"
            "（bcc 铁 = 8 个顶点 + 体心，fcc = 8 顶点 + 6 面心）")
        self.chk_boundary.toggled.connect(lambda _v: self._rebuild())
        bar.addWidget(self.chk_boundary)
        self.chk_params = QCheckBox("参数面板")
        self.chk_params.toggled.connect(
            lambda on: self.canvas.show_params_panel(bool(on)))
        bar.addWidget(self.chk_params)
        btn_fit = QPushButton("重置视角")
        btn_fit.clicked.connect(self.fit_view)
        bar.addWidget(btn_fit)
        bar.addSpacing(12)
        bar.addWidget(QLabel("样式:"))
        for label, meth in self.STYLES:
            b = QPushButton(label)
            b.setObjectName("SmallBtn")
            b.clicked.connect(lambda _c=False, m=meth: self._apply_style(m))
            bar.addWidget(b)
        bar.addStretch(1)
        root.addLayout(bar)

        self.lbl_info = QLabel("未载入结构。可载入 .cif / POSCAR / CONTCAR / .vasp")
        self.lbl_info.setStyleSheet("color:#475569;")
        root.addWidget(self.lbl_info)

        # ── 画布：直接用 MolStudio 的 OVCanvas（球棍模型/一键样式/参数面板同源）──
        self.canvas = OVCanvas()
        root.addWidget(self.canvas, 1)
        self.canvas.show_params_panel(False)
        if self.canvas.glw is not None:
            install_cell_box(self.canvas.glw, self._box_corners)
            self.canvas.glw.set_background((1.0, 1.0, 1.0, 1.0))
            # 空场景下先套一次 MolStudio 观感：样式应用是多步 setter，每步都会
            # 重建原子/键网格，趁画布还空着套完最省时间（见 _apply_style）。
            self._apply_style("_apply_molstudio_style")

        if path:
            self.load(path)

    # ── 载入 ──
    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "载入晶体文件",
            "", "结构文件 (*.cif *.mol2 *.vasp POSCAR CONTCAR *.poscar);;所有文件 (*)")
        if path:
            self.load(path)

    def load(self, path):
        try:
            self.crystal = Crystal.from_file(path)
        except Exception as e:
            self.lbl_info.setText("载入失败：%s" % e)
            return
        # 新结构从 1×1×1 开始（否则上一个结构的扩晶胞倍数会套到新结构上，
        # 大晶胞直接撞 1500 原子上限、画面还停在旧结构）。
        self._set_reps(1, 1, 1, rebuild=False)
        self._applied_reps = (1, 1, 1)
        self._rebuild()

    def _reps(self):
        """当前扩晶胞倍数 (na, nb, nc)。"""
        return tuple(sp.value() for sp in self.sp_reps)

    def _set_reps(self, na, nb, nc, rebuild=True):
        """设置三个方向的倍数（不回环触发重建）。"""
        for sp, v in zip(self.sp_reps, (na, nb, nc)):
            sp.blockSignals(True)
            sp.setValue(int(v))
            sp.blockSignals(False)
        if rebuild:
            self._rebuild()

    def _rebuild(self):
        if self.crystal is None:
            return
        reps = self._reps()
        fill = self.chk_boundary.isChecked()
        atoms = self.crystal.supercell(reps[0], reps[1], reps[2], fill)
        # 画布的成键判定是 O(n²)（与主程序同一套），原子太多会卡住界面：
        # 这里给个体量上限，超了就提示改用小一点的超胞。
        if len(atoms) > 8000:
            self._set_reps(self._applied_reps[0], self._applied_reps[1],
                           self._applied_reps[2], rebuild=False)
            self.lbl_info.setText(
                "原胞 %d 原子 × %d×%d×%d = %d 原子，超出本 Demo 的实时渲染上限"
                "（8000），已退回上一次的 %d×%d×%d。"
                % (len(self.crystal.sites), reps[0], reps[1], reps[2],
                   len(atoms), self._applied_reps[0], self._applied_reps[1],
                   self._applied_reps[2]))
            return
        if self.canvas.glw is None:
            return
        self._applied_reps = reps
        self._atoms = atoms
        self.canvas.glw.set_molecule(atoms)
        self.fit_view()
        cell = self.crystal.cell
        cell_txt = ("" if not cell else
                    "  a=%.3f b=%.3f c=%.3f Å  α=%.1f β=%.1f γ=%.1f°"
                    % tuple(cell))
        self.lbl_info.setText(
            "%s — 原胞 %d 原子；当前 %d×%d×%d 超胞共 %d 原子（含边界补齐）%s"
            % (self.crystal.source, len(self.crystal.sites),
               reps[0], reps[1], reps[2], len(atoms), cell_txt))

    def _apply_style(self, meth_name):
        fn = getattr(self.canvas, meth_name, None)
        if not callable(fn):
            return
        glw = self.canvas.glw
        atoms = getattr(self, "_atoms", None)
        # 晶体动辄两三百个原子，而画布的样式应用是"多步 setter、每步重建一次
        # 网格"——直接套会把同一个分子重算十几遍（实测 268 原子 ≈ 11 s）。
        # 先摘掉分子（空场景重建≈0），套完样式再放回去，只重建一次。
        if glw is not None and atoms and len(atoms) > 60:
            glw.set_molecule([])
            try:
                fn()
            finally:
                glw.set_molecule(atoms)
        else:
            fn()

    # ── 相机 ──
    def fit_view(self):
        if self.crystal is None or self.canvas.glw is None:
            return
        reps = self._reps()
        atoms = self.crystal.supercell(reps[0], reps[1], reps[2],
                                       self.chk_boundary.isChecked())
        pts = np.array([a[3] for a in atoms], dtype=float)
        ctr = pts.mean(axis=0)
        rad = float(np.max(np.linalg.norm(pts - ctr, axis=1))) + 0.8
        glw = self.canvas.glw
        glw.cam.set_center_zoom(ctr / BOHR_TO_ANGSTROM, rad / BOHR_TO_ANGSTROM)
        glw.update()

    # ── 晶胞框顶点（Å；不显示时返回空）──
    def _box_corners(self):
        if self.crystal is None or not self.chk_box.isChecked():
            return None
        return self.crystal.cell_corners()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    path = sys.argv[1] if len(sys.argv) > 1 else None
    win = CrystalDemoWindow(path)
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
