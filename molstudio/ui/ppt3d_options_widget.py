# -*- coding: utf-8 -*-
"""Reusable PowerPoint 3D export settings (shared by the library tab and the
top-toolbar export dialog)."""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from molstudio.core.ppt3d_options import Ppt3dOptions

_TEXT = {
    "zh": {
        "mesh": "网格与材质",
        "geometry": "几何与视角",
        "cell": "晶胞（晶体专用）",
        "high_detail": "高细节球面",
        "atom_outline": "原子描边",
        "bake_ao": "接触阴影 AO",
        "ao_rays": "AO 采样",
        "native_pbr": "原生 PBR 顶点色",
        "unlit": "无光照平涂",
        "atom_scale": "原子比例",
        "bond_scale": "键比例",
        "hide_hydrogens": "不显示氢",
        "keep_view": "保留当前视角",
        "include_surfaces": "包含画布等值面",
        "show_cell_box": "导出晶胞边框",
        "cell_line_width": "边框线宽 (Å)",
        "cell_color": "边框颜色",
        "pick": "选择…",
        "supercell": "扩晶胞",
        "fill_boundary": "边界原子补齐",
        "title": "PowerPoint 3D 导出设置",
        "ok": "开始导出",
        "cancel": "取消",
        "crystal_only": "选中晶体后可用",
    },
    "en": {
        "mesh": "Mesh & material",
        "geometry": "Geometry & view",
        "cell": "Unit cell (crystals)",
        "high_detail": "High-detail spheres",
        "atom_outline": "Atom outlines",
        "bake_ao": "Contact AO",
        "ao_rays": "AO rays",
        "native_pbr": "Native PBR vertex colours",
        "unlit": "Unlit flat shading",
        "atom_scale": "Atom scale",
        "bond_scale": "Bond scale",
        "hide_hydrogens": "Hide hydrogens",
        "keep_view": "Keep current view",
        "include_surfaces": "Include canvas surfaces",
        "show_cell_box": "Export unit-cell frame",
        "cell_line_width": "Frame width (Å)",
        "cell_color": "Frame colour",
        "pick": "Pick…",
        "supercell": "Supercell",
        "fill_boundary": "Fill boundary atoms",
        "title": "PowerPoint 3D export settings",
        "ok": "Export",
        "cancel": "Cancel",
        "crystal_only": "Available for crystals",
    },
}


class Ppt3dOptionsWidget(QWidget):
    """All tunable .glb parameters; ``options()`` returns a Ppt3dOptions."""

    def __init__(self, parent=None, lang="zh"):
        super().__init__(parent)
        self.lang = "zh" if str(lang).lower().startswith("zh") else "en"
        self._cell_color = "#46505F"
        self._build_ui()
        self.set_language(self.lang)
        # Qt checkboxes start unchecked; seed the widget from the data-class
        # defaults so the library page and the dialog agree out of the box.
        self.set_options(Ppt3dOptions())

    def _t(self, key):
        return (_TEXT.get(self.lang) or _TEXT["zh"]).get(
            key, _TEXT["zh"].get(key, key))

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(8)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        mesh = QGroupBox()
        mesh_l = QGridLayout(mesh)
        mesh_l.setSpacing(6)
        self.chk_high_detail = QCheckBox()
        self.chk_outline = QCheckBox()
        self.chk_ao = QCheckBox()
        self.chk_native = QCheckBox()
        self.chk_unlit = QCheckBox()
        self.spin_ao = QSpinBox()
        self.spin_ao.setRange(4, 32)
        self.spin_ao.setValue(8)
        self.spin_ao.setFixedWidth(64)
        for row, widget in enumerate((self.chk_high_detail, self.chk_outline,
                                      self.chk_ao, self.chk_native,
                                      self.chk_unlit)):
            mesh_l.addWidget(widget, row, 0, 1, 2)
        mesh_l.addWidget(self.spin_ao, 2, 2)
        lay.addWidget(mesh)
        self.grp_mesh = mesh

        geom = QGroupBox()
        g_l = QGridLayout(geom)
        g_l.setSpacing(6)
        self.spin_atom_scale = QDoubleSpinBox()
        self.spin_bond_scale = QDoubleSpinBox()
        for spin in (self.spin_atom_scale, self.spin_bond_scale):
            spin.setRange(0.4, 2.5)
            spin.setSingleStep(0.05)
            spin.setDecimals(2)
            spin.setValue(1.0)
            spin.setFixedWidth(80)
        self.chk_hide_h = QCheckBox()
        self.chk_keep_view = QCheckBox()
        self.chk_surfaces = QCheckBox()
        pairs = [
            (self._t("atom_scale"), self.spin_atom_scale),
            (self._t("bond_scale"), self.spin_bond_scale),
        ]
        for row, (label, spin) in enumerate(pairs):
            g_l.addWidget(QLabel(label), row, 0)
            g_l.addWidget(spin, row, 1)
        for row, widget in enumerate((self.chk_hide_h, self.chk_keep_view,
                                      self.chk_surfaces), start=2):
            g_l.addWidget(widget, row, 0, 1, 2)
        g_l.setRowStretch(5, 1)
        lay.addWidget(geom)
        self.grp_geom = geom

        cell = QGroupBox()
        c_l = QGridLayout(cell)
        c_l.setSpacing(6)
        self.chk_cell_box = QCheckBox()
        self.spin_cell_width = QDoubleSpinBox()
        self.spin_cell_width.setRange(0.01, 0.5)
        self.spin_cell_width.setDecimals(3)
        self.spin_cell_width.setSingleStep(0.01)
        self.spin_cell_width.setValue(0.055)
        self.spin_cell_width.setFixedWidth(80)
        self.btn_cell_color = QPushButton()
        self.btn_cell_color.setFixedWidth(96)
        self.btn_cell_color.clicked.connect(self._pick_cell_color)
        self.spin_reps = []
        reps_row = QHBoxLayout()
        for _ in range(3):
            sp = QSpinBox()
            sp.setRange(1, 3)
            sp.setValue(1)
            sp.setFixedWidth(52)
            self.spin_reps.append(sp)
            reps_row.addWidget(sp)
        reps_row.addStretch(1)
        reps_widget = QWidget()
        reps_widget.setLayout(reps_row)
        self.chk_boundary = QCheckBox()
        c_l.addWidget(self.chk_cell_box, 0, 0, 1, 2)
        c_l.addWidget(QLabel(self._t("cell_line_width")), 1, 0)
        c_l.addWidget(self.spin_cell_width, 1, 1)
        c_l.addWidget(QLabel(self._t("cell_color")), 2, 0)
        c_l.addWidget(self.btn_cell_color, 2, 1)
        c_l.addWidget(QLabel(self._t("supercell")), 3, 0)
        c_l.addWidget(reps_widget, 3, 1)
        c_l.addWidget(self.chk_boundary, 4, 0, 1, 2)
        c_l.setRowStretch(5, 1)
        lay.addWidget(cell)
        self.grp_cell = cell
        lay.addStretch(1)

        self._labels = [
            (mesh_l, 2, 2, "ao_rays"),
        ]

    def set_language(self, lang):
        self.lang = "zh" if str(lang).lower().startswith("zh") else "en"
        self.grp_mesh.setTitle(self._t("mesh"))
        self.grp_geom.setTitle(self._t("geometry"))
        self.grp_cell.setTitle(self._t("cell"))
        for widget, key in (
                (self.chk_high_detail, "high_detail"),
                (self.chk_outline, "atom_outline"),
                (self.chk_ao, "bake_ao"),
                (self.chk_native, "native_pbr"),
                (self.chk_unlit, "unlit"),
                (self.chk_hide_h, "hide_hydrogens"),
                (self.chk_keep_view, "keep_view"),
                (self.chk_surfaces, "include_surfaces"),
                (self.chk_cell_box, "show_cell_box"),
                (self.chk_boundary, "fill_boundary")):
            widget.setText(self._t(key))
        self.btn_cell_color.setText(self._t("pick"))
        self._paint_color_button()
        # Labels created in _build_ui keep their original text; refresh them.
        for layout, row, col, key in self._labels:
            item = layout.itemAtPosition(row, col)
            # AO rays label is embedded in the checkbox row; nothing to do.
        self.grp_geom.layout().itemAtPosition(0, 0).widget().setText(
            self._t("atom_scale"))
        self.grp_geom.layout().itemAtPosition(1, 0).widget().setText(
            self._t("bond_scale"))
        self.grp_cell.layout().itemAtPosition(1, 0).widget().setText(
            self._t("cell_line_width"))
        self.grp_cell.layout().itemAtPosition(2, 0).widget().setText(
            self._t("cell_color"))
        self.grp_cell.layout().itemAtPosition(3, 0).widget().setText(
            self._t("supercell"))
        # The "crystals only" hint is set by set_crystal_mode(); refresh it so
        # switching language never leaves a stale Chinese tooltip behind.
        self.grp_cell.setToolTip(
            "" if self.grp_cell.isEnabled() else self._t("crystal_only"))

    def _paint_color_button(self):
        self.btn_cell_color.setStyleSheet(
            "QPushButton{background:%s;border:1px solid #94A3B8;"
            "border-radius:4px;color:white;}" % self._cell_color)

    def _pick_cell_color(self):
        colour = QColorDialog.getColor(QColor(self._cell_color), self,
                                       self._t("cell_color"))
        if colour.isValid():
            self._cell_color = colour.name()
            self._paint_color_button()

    def set_options(self, options):
        opt = options if isinstance(options, Ppt3dOptions) else \
            Ppt3dOptions.from_dict(options)
        self.chk_high_detail.setChecked(bool(opt.high_detail))
        self.chk_outline.setChecked(bool(opt.atom_outline))
        self.chk_ao.setChecked(bool(opt.bake_ao))
        self.spin_ao.setValue(int(opt.ao_rays))
        self.chk_native.setChecked(bool(opt.native_pbr))
        self.chk_unlit.setChecked(bool(opt.unlit))
        self.spin_atom_scale.setValue(float(opt.atom_scale))
        self.spin_bond_scale.setValue(float(opt.bond_scale))
        self.chk_hide_h.setChecked(bool(opt.hide_hydrogens))
        self.chk_keep_view.setChecked(bool(opt.keep_view))
        self.chk_surfaces.setChecked(bool(opt.include_surfaces))
        self.chk_cell_box.setChecked(bool(opt.show_cell_box))
        self.spin_cell_width.setValue(float(opt.cell_line_width))
        self._cell_color = str(opt.cell_color or "#46505F")
        self._paint_color_button()
        for spin, value in zip(self.spin_reps, opt.reps()):
            spin.setValue(int(value))
        self.chk_boundary.setChecked(bool(opt.fill_boundary))

    def options(self) -> Ppt3dOptions:
        return Ppt3dOptions(
            high_detail=self.chk_high_detail.isChecked(),
            atom_outline=self.chk_outline.isChecked(),
            bake_ao=self.chk_ao.isChecked(),
            ao_rays=self.spin_ao.value(),
            native_pbr=self.chk_native.isChecked(),
            unlit=self.chk_unlit.isChecked(),
            atom_scale=self.spin_atom_scale.value(),
            bond_scale=self.spin_bond_scale.value(),
            hide_hydrogens=self.chk_hide_h.isChecked(),
            keep_view=self.chk_keep_view.isChecked(),
            include_surfaces=self.chk_surfaces.isChecked(),
            show_cell_box=self.chk_cell_box.isChecked(),
            cell_line_width=self.spin_cell_width.value(),
            cell_color=self._cell_color,
            supercell=tuple(sp.value() for sp in self.spin_reps),
            fill_boundary=self.chk_boundary.isChecked(),
        )

    def set_crystal_mode(self, enabled: bool):
        """Only crystals have a unit cell; grey the group out for molecules."""
        self.grp_cell.setEnabled(bool(enabled))
        self.grp_cell.setToolTip("" if enabled else self._t("crystal_only"))


class Ppt3dExportDialog(QDialog):
    """Toolbar 'PPT 3D' export: confirm the settings before choosing a file."""

    def __init__(self, parent=None, lang="zh", options=None,
                 crystal=False):
        super().__init__(parent)
        self.lang = "zh" if str(lang).lower().startswith("zh") else "en"
        self.setWindowTitle(self._t("title"))
        # 晶体模式多一组「晶胞（晶体专用）」。程序有全局样式表，三组加起来
        # 实测需要 ~850px；默认 520/760px 会把这一组挤到滚动区下面，用户会
        # 以为没有「导出晶胞边框」选项。按模式给足高度，同时不让小屏幕溢出。
        height = 920 if crystal else 700
        screen = QApplication.primaryScreen()
        if screen is not None:
            height = min(height,
                         max(700, screen.availableGeometry().height() - 60))
        self.resize(430, height)
        lay = QVBoxLayout(self)
        self.widget = Ppt3dOptionsWidget(self, self.lang)
        self.widget.set_options(options or Ppt3dOptions())
        self.widget.set_crystal_mode(crystal)
        lay.addWidget(self.widget, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok |
                                   QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(self._t("ok"))
        buttons.button(QDialogButtonBox.Cancel).setText(self._t("cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _t(self, key):
        return (_TEXT.get(self.lang) or _TEXT["zh"]).get(
            key, _TEXT["zh"].get(key, key))

    def options(self) -> Ppt3dOptions:
        return self.widget.options()

    @staticmethod
    def get_options(parent=None, lang="zh", options=None, crystal=False):
        dialog = Ppt3dExportDialog(parent, lang, options, crystal)
        if dialog.exec_() != QDialog.Accepted:
            return None
        return dialog.options()
