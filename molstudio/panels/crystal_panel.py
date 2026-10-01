#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""晶体可视化面板（CIF / POSCAR）—— 主程序右侧的一个 tab，共享左侧 GL 画布。

球棍模型直接用主程序的 OpenGL 画布渲染（同一套引擎与样式），本面板只负责：
  ① 解析 CIF（含对称操作展开、多 data_ 块）与 VASP POSCAR/CONTCAR；
  ② 扩晶胞（a/b/c 三个方向分别 1–6 倍）与"边界原子补齐"；
  ③ 在画布上叠加画晶胞框（QPainter，跟随分子一起显示）。

解析/晶胞逻辑与 `crystal_demo.py` 同源，一起放在 `crystal_lib.py` 里。
"""

import os

import numpy as np

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout,
                             QLabel, QMenu, QPushButton, QSlider, QSpinBox,
                             QTableWidget, QTableWidgetItem, QToolButton,
                             QVBoxLayout, QWidget)

from molstudio.core.crystal_lib import Crystal, coordination_polyhedra, install_cell_box
from molstudio.render.ovcanvas._glwidget import BOHR_TO_ANGSTROM
from molstudio.render.vesta_colors import VESTA_STYLE_COLORS

# 实时渲染上限：画布的成键判定是 O(n²)（已做空间分箱），但再大就该劝用户
# 缩小超胞了 —— 8000 原子实测建网格约 1 s、每帧 ~5 ms。
MAX_ATOMS = 8000


#: 中英文字对照（切语言时由 set_lang 整树套用，见 molstudio/ui/i18n_utils.py）
_LANG_EXTRA = {
    "载入 CIF / MOL2 / POSCAR…": "Load CIF / MOL2 / POSCAR…",
    "支持 .cif、POSCAR、CONTCAR、.vasp": "Supports .cif, POSCAR, CONTCAR, .vasp",
    "显示": "Show",
    "晶胞框": "Cell box",
    "边界原子补齐": "Complete boundary atoms",
    "画原胞的 12 条棱（扩晶胞时仍只框住原始晶胞）":
        "Draw the 12 edges of the original cell (the box still frames the original "
        "cell when the supercell is expanded)",
    "晶胞顶点 / 棱 / 面上的原子在所有等价位置都画出来\n"
    "（bcc 铁 = 8 个顶点 + 体心，fcc = 8 顶点 + 6 面心）":
        "Draw atoms on cell vertices / edges / faces at every equivalent position\n"
        "(bcc Fe = 8 vertices + body center, fcc = 8 vertices + 6 face centers)",
    "扩晶胞:": "Supercell:",
    "扩晶胞回到 1×1×1": "Reset the supercell to 1×1×1",
    "沿 a 方向重复几个晶胞（1–6）": "Number of cells along a (1–6)",
    "沿 b 方向重复几个晶胞（1–6）": "Number of cells along b (1–6)",
    "沿 c 方向重复几个晶胞（1–6）": "Number of cells along c (1–6)",
    "配位多面体:": "Coordination polyhedron:",
    "以哪种元素为中心画配位多面体（列的是当前结构里有的元素）":
        "Element used as the center of the coordination polyhedron (only elements "
        "present in the current structure are listed)",
    "把中心原子的配位原子连成半透明多面体（配位判据与画布成键阈值一致：\n"
    "1.3 × 共价半径和，Cordero 2008）。\n"
    "提示：勾上「边界原子补齐」后晶胞边界上的多面体才是完整的。":
        "Connect the coordinating atoms of the center into a translucent polyhedron "
        "(same criterion as the canvas bonding threshold:\n"
        "1.3 × sum of covalent radii, Cordero 2008).\n"
        "Note: tick 「Complete boundary atoms」 to make polyhedra on the cell boundary complete.",
    "不透明度:": "Opacity:",
    "未载入结构。可载入 .cif / POSCAR / CONTCAR / .vasp":
        "No structure loaded. You can load .cif / POSCAR / CONTCAR / .vasp",
    "提示：画布样式仍用左侧「一键样式」；晶胞框与扩晶胞只影响当前结构。":
        "Note: canvas styling still uses the one-click styles on the left; the cell box "
        "and supercell only affect the current structure.",
    # ── 画布下方信息条 ──
    "原子表 ▾": "Atom table ▾",
    "展开/收起原胞（已展开对称操作）的原子坐标表":
        "Expand/collapse the atom table of the original cell (symmetry operations applied)",
    "导出图片": "Export image",
    "把当前画布视图导出为图片（含晶胞框）":
        "Export the current canvas view as an image (including the cell box)",
    "SVG 矢量": "SVG vector",
    "复位": "Reset",
    "重置视角": "Reset view",
    "测量": "Measure",
    "距离": "Distance",
    "键角": "Angle",
    "二面角": "Dihedral",
    "测量类型：距离（点 2 个原子）/ 键角（点 3 个，第 2 个是顶点）/ 二面角（点 4 个）":
        "Measurement type: distance (2 atoms) / angle (3 atoms, the 2nd is the vertex) / "
        "dihedral (4 atoms)",
    "开启后到左侧画布上依次点击原子；数值会标在几何量旁边":
        "When on, click the atoms in order on the left canvas; the value is annotated "
        "next to the geometry",
    "清除标注": "Clear annotations",
    "删除画布上全部测量标注": "Remove all measurement annotations from the canvas",
    "未载入结构（右侧「晶体」页可载入 CIF / MOL2 / POSCAR）":
        "No structure loaded (the Crystal panel on the right can load CIF / MOL2 / POSCAR)",
    "元素": "Element",
    "分数坐标 (a, b, c)": "Fractional coords (a, b, c)",
}


class CrystalPanel(QWidget):
    """载入晶体文件 → 在共享画布上显示球棍模型 + 晶胞框。"""

    structureChanged = pyqtSignal()      # 结构载入/重建完成（画布下方信息条据此刷新）

    def __init__(self, glw=None, log_func=None, parent=None):
        super().__init__(parent)
        self.glw = glw
        self._log = log_func or (lambda m: None)
        self.crystal = None
        self._atoms = None
        self._applied_reps = (1, 1, 1)
        self._active = False
        self._overlay_installed = False
        self._build_ui()
        self._install_overlay()

    # ── UI ──
    def _build_ui(self):
        root = QVBoxLayout(self)
        # 页面级的 8px 内缩由承载它的 _crystal_tab（main_window）统一提供，
        # 这里留 0，否则两层叠加会变成 16px，与其余页面不一致。
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        row1 = QHBoxLayout()
        self.btn_open = QPushButton("载入 CIF / MOL2 / POSCAR…")
        self.btn_open.setToolTip("支持 .cif、POSCAR、CONTCAR、.vasp")
        self.btn_open.clicked.connect(self.open_file)
        row1.addWidget(self.btn_open)
        btn_fit = QPushButton("重置视角")
        btn_fit.clicked.connect(self.fit_view)
        row1.addWidget(btn_fit)
        row1.addStretch(1)
        root.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("扩晶胞:"))
        self.sp_reps = []
        for axis in "abc":
            if axis != "a":
                row2.addWidget(QLabel("×"))
            sp = QSpinBox()
            sp.setRange(1, 6)
            sp.setValue(1)
            sp.setFixedWidth(56)
            sp.setToolTip("沿 %s 方向重复几个晶胞（1–6）" % axis)
            sp.valueChanged.connect(self._rebuild)
            row2.addWidget(sp)
            self.sp_reps.append(sp)
        btn_reset = QPushButton("复位")
        btn_reset.setToolTip("扩晶胞回到 1×1×1")
        btn_reset.clicked.connect(lambda: self._set_reps(1, 1, 1, rebuild=True))
        row2.addWidget(btn_reset)
        row2.addSpacing(12)
        self.chk_boundary = QCheckBox("边界原子补齐")
        self.chk_boundary.setChecked(True)
        self.chk_boundary.setToolTip(
            "晶胞顶点 / 棱 / 面上的原子在所有等价位置都画出来\n"
            "（bcc 铁 = 8 个顶点 + 体心，fcc = 8 顶点 + 6 面心）")
        self.chk_boundary.toggled.connect(lambda _v: self._rebuild())
        row2.addWidget(self.chk_boundary)
        self.chk_box = QCheckBox("晶胞框")
        self.chk_box.setChecked(True)
        self.chk_box.setToolTip("画原胞的 12 条棱（扩晶胞时仍只框住原始晶胞）")
        self.chk_box.toggled.connect(lambda _v: self._refresh_canvas())
        row2.addWidget(self.chk_box)
        row2.addStretch(1)
        root.addLayout(row2)

        # ── 配位多面体（VESTA 风格的半透明多面体；画布侧复用平面填充管线）──
        row3 = QHBoxLayout()
        row3.setSpacing(6)
        row3.addWidget(QLabel("配位多面体:"))
        self.cb_poly = QComboBox()
        self.cb_poly.setMinimumWidth(96)
        self.cb_poly.setToolTip("以哪种元素为中心画配位多面体（列的是当前结构里有的元素）")
        self.cb_poly.currentIndexChanged.connect(self._apply_polyhedra)
        row3.addWidget(self.cb_poly)
        self.chk_poly = QCheckBox("显示")
        self.chk_poly.setToolTip(
            "把中心原子的配位原子连成半透明多面体（配位判据与画布成键阈值一致：\n"
            "1.3 × 共价半径和，Cordero 2008）。\n"
            "提示：勾上「边界原子补齐」后晶胞边界上的多面体才是完整的。")
        self.chk_poly.toggled.connect(self._apply_polyhedra)
        row3.addWidget(self.chk_poly)
        row3.addWidget(QLabel("不透明度:"))
        self.sld_poly = QSlider(Qt.Horizontal)
        self.sld_poly.setRange(10, 90)
        self.sld_poly.setValue(45)
        self.sld_poly.setMinimumWidth(80)
        self.sld_poly.valueChanged.connect(self._on_poly_alpha)
        row3.addWidget(self.sld_poly, 1)
        self.lbl_poly_alpha = QLabel("0.45")
        self.lbl_poly_alpha.setMinimumWidth(34)
        row3.addWidget(self.lbl_poly_alpha)
        root.addLayout(row3)

        self.lbl_info = QLabel("未载入结构。可载入 .cif / POSCAR / CONTCAR / .vasp")
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setStyleSheet("color:#475569;")
        root.addWidget(self.lbl_info)

        tip = QLabel("提示：画布样式仍用左侧「一键样式」；晶胞框与扩晶胞只影响当前结构。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#94A3B8;")
        root.addWidget(tip)
        root.addStretch(1)

    # ── 载入 / 重建 ──
    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "载入晶体文件", "",
            "结构文件 (*.cif *.mol2 *.vasp POSCAR CONTCAR *.poscar);;所有文件 (*)")
        if path:
            self.load(path)

    def load(self, path):
        try:
            self.crystal = Crystal.from_file(path)
        except Exception as e:
            self.lbl_info.setText("载入失败：%s" % e)
            self._log("晶体载入失败：%s" % e)
            return False
        self._set_reps(1, 1, 1, rebuild=False)
        self._applied_reps = (1, 1, 1)
        self._rebuild()
        self._log("晶体已载入：%s（原胞 %d 原子）"
                  % (os.path.basename(path), len(self.crystal.sites)))
        return True

    def _set_cell_only_enabled(self, on):
        """分子（MOL2）没有晶胞：把只对晶体有意义的控件灰掉。"""
        for w in (list(self.sp_reps)
                  + [self.chk_boundary, self.chk_box,
                     self.cb_poly, self.chk_poly, self.sld_poly]):
            w.setEnabled(bool(on))

    def _reps(self):
        return tuple(sp.value() for sp in self.sp_reps)

    def _set_reps(self, a, b, c, rebuild=True):
        for sp, v in zip(self.sp_reps, (a, b, c)):
            sp.blockSignals(True)
            sp.setValue(int(v))
            sp.blockSignals(False)
        if rebuild:
            self._rebuild()

    def _rebuild(self):
        if self.crystal is None or self.glw is None:
            return
        reps = self._reps()
        fill = self.chk_boundary.isChecked()
        atoms = self.crystal.supercell(reps[0], reps[1], reps[2], fill)
        if len(atoms) > MAX_ATOMS:
            self._set_reps(self._applied_reps[0], self._applied_reps[1],
                           self._applied_reps[2], rebuild=False)
            self.lbl_info.setText(
                "原胞 %d 原子 × %d×%d×%d = %d 原子，超出实时渲染上限（%d），"
                "已退回上一次的 %d×%d×%d。"
                % (len(self.crystal.sites), reps[0], reps[1], reps[2],
                   len(atoms), MAX_ATOMS, self._applied_reps[0],
                   self._applied_reps[1], self._applied_reps[2]))
            return
        self._applied_reps = reps
        self._atoms = atoms
        self._set_cell_only_enabled(not self.crystal.is_molecule)
        self.glw.set_molecule(atoms)
        self.fit_view()
        cell = self.crystal.cell
        if self.crystal.is_molecule:
            self.lbl_info.setText(
                "%s — 分子结构（MOL2，无晶胞）共 %d 原子；扩晶胞/边界补齐/晶胞框"
                "已停用" % (self.crystal.source, len(atoms)))
        else:
            cell_txt = ("" if not cell else
                        "　a=%.3f b=%.3f c=%.3f Å　α=%.1f β=%.1f γ=%.1f°"
                        % tuple(cell))
            self.lbl_info.setText(
                "%s — 原胞 %d 原子；当前 %d×%d×%d 超胞共 %d 原子（含边界补齐）%s"
                % (self.crystal.source, len(self.crystal.sites),
                   reps[0], reps[1], reps[2], len(atoms), cell_txt))
        self._refresh_canvas()
        # set_molecule 会清掉画布上的配位多面体（坐标变了），这里重挂一次
        self._fill_poly_elements()
        self._apply_polyhedra()
        self.structureChanged.emit()

    def fit_view(self):
        """把相机框到当前结构（画布内部坐标是 Bohr）。"""
        if not self._atoms or self.glw is None:
            return
        pts = np.array([a[3] for a in self._atoms], dtype=float)
        ctr = pts.mean(axis=0)
        rad = float(np.max(np.linalg.norm(pts - ctr, axis=1))) + 0.8
        self.glw.cam.set_center_zoom(ctr / BOHR_TO_ANGSTROM,
                                     rad / BOHR_TO_ANGSTROM)
        self._refresh_canvas()

    def _refresh_canvas(self):
        if self.glw is not None:
            self.glw.update()

    # ── 晶胞框叠加（只在"本面板可见 + 画布上是我们的结构"时画）──
    def _box_corners(self):
        if (self.crystal is None or not self._active
                or not self.chk_box.isChecked() or self._atoms is None):
            return None
        # 画布上的分子被别的面板换掉了（原子数不一致）→ 不画框，免得框错结构
        cur = self.glw._molecule if self.glw is not None else None
        if cur is None or len(cur) != len(self._atoms):
            return None
        return self.crystal.cell_corners()

    def _install_overlay(self):
        if self.glw is None or self._overlay_installed:
            return
        try:
            self._overlay_orig = self.glw._draw_mol_overlay   # 记住原方法，退出时还原
            install_cell_box(self.glw, self._box_corners)
            self._overlay_installed = True
        except Exception as e:
            self._log("晶胞框叠加安装失败：%s" % e)

    # ── 配位多面体 ──
    def _poly_rgba(self):
        """多面体颜色/透明度：颜色取 VESTA 的 POLYP 灰，透明度由滑块给。"""
        r, g, b = VESTA_STYLE_COLORS["polyhedron"]
        return (r / 255.0, g / 255.0, b / 255.0, self.sld_poly.value() / 100.0)

    def _fill_poly_elements(self):
        """按当前结构里实际存在的元素刷新「配位多面体」中心元素下拉。

        尽量保留用户原来的选择；没有历史选择时默认选**最重**的元素 —— 氧化物/
        卤化物/配合物里通常就是金属中心。
        """
        if not self._atoms:
            return
        seen = {}
        for _idx, sym, z, _p in self._atoms:
            seen[int(z)] = sym
        if not seen:
            return
        keep = self.cb_poly.currentData()
        order = sorted(seen)                      # 按原子序数排
        self.cb_poly.blockSignals(True)
        self.cb_poly.clear()
        for z in order:
            self.cb_poly.addItem("%s (%d)" % (seen[z], z), z)
        idx = self.cb_poly.findData(keep) if keep is not None else -1
        if idx < 0:
            idx = len(order) - 1
        self.cb_poly.setCurrentIndex(max(0, idx))
        self.cb_poly.blockSignals(False)

    def _apply_polyhedra(self, *_a):
        """按当前设置重算并显示配位多面体；不满足条件时清掉已有的。"""
        glw = self.glw
        if glw is None:
            return
        z = self.cb_poly.currentData()
        if (not self.chk_poly.isChecked() or self.crystal is None
                or self.crystal.is_molecule or not self._atoms or z is None):
            glw.clear_polyhedra()
            return
        try:
            polys = coordination_polyhedra(self._atoms, int(z))
        except Exception as e:
            self._log("配位多面体计算失败：%s" % e)
            glw.clear_polyhedra()
            return
        glw.set_polyhedra(polys, self._poly_rgba())
        sym = self.cb_poly.currentText()
        if polys:
            self._log("配位多面体：%s 共 %d 个" % (sym, len(polys)))
        else:
            self._log("配位多面体：%s 没有满足条件的多面体"
                      "（配位数需 3–16 且配位原子不共面）" % sym)

    def _on_poly_alpha(self, _v=None):
        """不透明度滑块：只改颜色 alpha，不重算几何（拖动时即时可见）。"""
        self.lbl_poly_alpha.setText("%.2f" % (self.sld_poly.value() / 100.0))
        if self.glw is not None and self.chk_poly.isChecked():
            self.glw.set_polyhedron_alpha(self._poly_rgba())

    # ── 生命周期 ──
    def showEvent(self, e):
        super().showEvent(e)
        self._active = True
        self._apply_polyhedra()      # 回到本页时重挂多面体（切走时被清掉了）
        self._refresh_canvas()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._active = False
        # 与晶胞框一致：离开晶体页就不显示多面体，免得在别的页面里碍眼
        if self.glw is not None:
            self.glw.clear_polyhedra()
        self._refresh_canvas()

    def shutdown(self):
        """退出时把画布上的叠加钩子摘掉。"""
        self._active = False
        if self.glw is None or not self._overlay_installed:
            return
        try:
            orig = getattr(self, "_overlay_orig", None)
            if orig is not None:
                self.glw._draw_mol_overlay = orig
        except Exception:
            pass
        self._overlay_installed = False

    # ── i18n ──
    def set_lang(self, lang):
        """切换界面语言（中/英）。"""
        from molstudio.ui.i18n_utils import apply_text_map
        apply_text_map(self, _LANG_EXTRA, "zh" if lang == "zh" else "en")


class CrystalInfoBar(QWidget):
    """画布下方的晶体信息条：导出图片 + 晶胞参数 + 原子表（可展开）。

    只读地显示 `CrystalPanel` 当前载入的结构；导出直接复用画布面板自己的
    `_export_image()`（PNG / JPG / TIFF / SVG，含透明背景与 600 DPI 那套逻辑），
    所以导出图里连晶胞框都在（它属于画布叠加层）。
    """

    FORMATS = (("PNG", "png"), ("JPG", "jpg"), ("TIFF", "tif"),
               ("SVG 矢量", "svg"))

    def __init__(self, canvas_panel=None, crystal_panel=None, parent=None):
        super().__init__(parent)
        self.canvas = canvas_panel
        self.panel = crystal_panel
        root = QVBoxLayout(self)
        # 同 CrystalPanel：页面级 8px 内缩由外层 _crystal_tab 提供，这里留 0。
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        row = QHBoxLayout()
        self.btn_export = QToolButton()
        self.btn_export.setText("导出图片")
        self.btn_export.setPopupMode(QToolButton.InstantPopup)
        self.btn_export.setToolTip("把当前画布视图导出为图片（含晶胞框）")
        menu = QMenu(self.btn_export)
        for label, ext in self.FORMATS:
            menu.addAction(label, lambda e=ext: self._export(e))
        self.btn_export.setMenu(menu)
        row.addWidget(self.btn_export)
        self.btn_table = QPushButton("原子表 ▾")
        self.btn_table.setCheckable(True)
        self.btn_table.setToolTip("展开/收起原胞（已展开对称操作）的原子坐标表")
        self.btn_table.toggled.connect(self._on_table_toggled)
        row.addWidget(self.btn_table)
        self.lbl_cell = QLabel("未载入晶体")
        self.lbl_cell.setStyleSheet("color:#475569;")
        row.addWidget(self.lbl_cell, 1)
        root.addLayout(row)

        # ── 几何测量行：距离 / 键角 / 二面角（与画布样式条那套是同一份状态）──
        mrow = QHBoxLayout()
        mrow.setSpacing(6)
        self.cb_measure = QComboBox()
        for _key, _label in (("dist", "距离"), ("angle", "键角"),
                             ("dihedral", "二面角")):
            self.cb_measure.addItem(_label, _key)
        self.cb_measure.setFixedWidth(88)
        self.cb_measure.setToolTip(
            "测量类型：距离（点 2 个原子）/ 键角（点 3 个，第 2 个是顶点）/ "
            "二面角（点 4 个）")
        self.cb_measure.currentIndexChanged.connect(self._on_measure_kind)
        mrow.addWidget(self.cb_measure)
        self.btn_measure = QPushButton("测量")
        self.btn_measure.setCheckable(True)
        self.btn_measure.setCursor(Qt.PointingHandCursor)
        self.btn_measure.setToolTip("开启后到左侧画布上依次点击原子；数值会标在几何量旁边")
        self.btn_measure.toggled.connect(self._on_measure_mode)
        mrow.addWidget(self.btn_measure)
        self.btn_measure_clear = QPushButton("清除标注")
        self.btn_measure_clear.setToolTip("删除画布上全部测量标注")
        self.btn_measure_clear.clicked.connect(self._on_measure_clear)
        mrow.addWidget(self.btn_measure_clear)
        mrow.addStretch(1)
        root.addLayout(mrow)
        # 与画布上的测量状态双向同步（画布样式条里也有一套同样的控件）
        _glw = self._glw()
        if _glw is not None:
            _glw.measureStateChanged.connect(self._sync_measure_ui)
            self._sync_measure_ui(*_glw.measure_state())

        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(
            ["#"] + (["Element", "Fractional coords (a, b, c)"]
                     if getattr(self, "_lang", "zh") == "en"
                     else ["元素", "分数坐标 (a, b, c)"]))
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setMaximumHeight(170)
        self.table.setVisible(False)
        root.addWidget(self.table)
        if self.panel is not None:
            self.panel.structureChanged.connect(self.refresh)
        self.refresh()

    # ── 导出 ──
    def _glw(self):
        """本信息条要驱动的画布 glw（画布不可用时返回 None）。"""
        return getattr(self.canvas, "glw", None) if self.canvas is not None \
            else None

    def _on_measure_kind(self, _idx=0):
        """测量类型切换 → 转发给画布。"""
        glw = self._glw()
        if glw is not None:
            glw.set_measure_kind(self.cb_measure.currentData() or "dist")

    def _on_measure_mode(self, on):
        """测量开关 → 转发给画布（类型取左侧下拉）。"""
        glw = self._glw()
        if glw is not None:
            glw.set_measure_mode(on, self.cb_measure.currentData() or "dist")

    def _on_measure_clear(self):
        """清除画布上全部测量标注。"""
        glw = self._glw()
        if glw is not None:
            glw.clear_measure_items()

    def _sync_measure_ui(self, on, kind):
        """画布侧（含画布样式条上的同类控件）改了测量状态 → 回填本行。"""
        self.cb_measure.blockSignals(True)
        try:
            i = self.cb_measure.findData(kind)
            if i >= 0:
                self.cb_measure.setCurrentIndex(i)
        finally:
            self.cb_measure.blockSignals(False)
        self.btn_measure.blockSignals(True)
        try:
            self.btn_measure.setChecked(bool(on))
        finally:
            self.btn_measure.blockSignals(False)

    def _export(self, ext):
        if self.canvas is None:
            return
        try:
            self.canvas._export_image(ext)
        except Exception as e:
            self.lbl_cell.setText("导出失败：%s" % e)

    def _on_table_toggled(self, on):
        self.table.setVisible(bool(on))
        self.btn_table.setText("原子表 ▴" if on else "原子表 ▾")
        if on:
            self.refresh()

    # ── 刷新 ──
    # ── i18n ──
    def set_lang(self, lang):
        """切换界面语言（中/英）：先按语言重建表格，再整树替换文字。"""
        self._lang = "zh" if lang == "zh" else "en"
        try:
            self.refresh()
        except Exception:
            pass
        from molstudio.ui.i18n_utils import apply_text_map
        apply_text_map(self, _LANG_EXTRA, self._lang)

    def refresh(self):
        cr = getattr(self.panel, "crystal", None) if self.panel is not None else None
        if cr is None:
            self.lbl_cell.setText("未载入结构（右侧「晶体」页可载入 CIF / MOL2 / POSCAR）")
            self.table.setRowCount(0)
            return
        if getattr(cr, "is_molecule", False):
            self.lbl_cell.setText("分子结构（MOL2）：共 %d 原子，无晶胞"
                                  % len(cr.cart))
            if self.table.isVisible():
                self._fill_table(cr)
            return
        cell = cr.cell
        vol = abs(float(np.linalg.det(cr.vecs)))
        if cell:
            self.lbl_cell.setText(
                "a=%.4f  b=%.4f  c=%.4f Å   α=%.3f  β=%.3f  γ=%.3f°   V=%.2f Å³"
                % (cell[0], cell[1], cell[2], cell[3], cell[4], cell[5], vol))
        else:
            self.lbl_cell.setText("晶胞 V=%.2f Å³" % vol)
        if self.table.isVisible():
            self._fill_table(cr)

    def _fill_table(self, cr):
        if getattr(cr, "is_molecule", False):     # 分子：直接给笛卡尔坐标
            self.table.setHorizontalHeaderLabels(
                ["#"] + (["Element", "Cartesian coords (Å)"]
                         if getattr(self, "_lang", "zh") == "en"
                         else ["元素", "笛卡尔坐标 (Å)"]))
            self.table.setRowCount(len(cr.cart))
            for r, (sym, xyz) in enumerate(cr.cart):
                for c, txt in enumerate((str(r + 1), sym,
                                         "%.4f, %.4f, %.4f" % tuple(xyz))):
                    item = QTableWidgetItem(txt)
                    if c == 0:
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    self.table.setItem(r, c, item)
            self.table.resizeColumnsToContents()
            return
        self.table.setHorizontalHeaderLabels(
            ["#"] + (["Element", "Fractional coords (a, b, c)"]
                     if getattr(self, "_lang", "zh") == "en"
                     else ["元素", "分数坐标 (a, b, c)"]))
        sites = list(cr.sites)
        self.table.setRowCount(len(sites))
        for r, (sym, f) in enumerate(sites):
            cart = np.asarray(f, dtype=float) @ cr.vecs
            for c, txt in enumerate((str(r + 1), sym,
                                     "%.4f, %.4f, %.4f" % (f[0], f[1], f[2]))):
                item = QTableWidgetItem(txt)
                if c == 0:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                item.setToolTip("笛卡尔坐标 (Å)：%.4f, %.4f, %.4f"
                                % (cart[0], cart[1], cart[2]))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
