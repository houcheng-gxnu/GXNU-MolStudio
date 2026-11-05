# -*- coding: utf-8 -*-
"""Bundled teaching-molecule browser and PowerPoint 3D exporter."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSplitter,
    QVBoxLayout, QWidget,
)

from molstudio.core.molecule_export import (
    ATOM_RADII, ELEMENT_COLOURS, export_glb,
)
from molstudio.core.molecule_library import (
    CATEGORY_LABELS, CATEGORY_ORDER, filter_molecules, load_library,
    load_molecule, molecule_path,
)
from molstudio.ui.file_dialogs import save_file


_TEXT = {
    "zh": {
        "title": "分子结构库",
        "subtitle": "初中、高中常用分子的三维球棍结构",
        "search": "搜索名称、化学式或别名…",
        "all": "全部分类",
        "visualize": "载入并可视化",
        "export_ppt": "导出 PowerPoint 3D",
        "formula": "化学式：{formula}",
        "category": "分类：{category}",
        "atoms": "{n} 个原子",
        "empty": "没有找到匹配的分子",
        "missing": "内置结构库为空，请检查安装文件。",
        "ppt_tip": "PowerPoint 365：插入 → 3D 模型 → 此设备，选择导出的 .glb 文件。"
                   "插入后可直接拖动旋转；支持的放映版本中也可在幻灯片里旋转。",
        "export_title": "导出 PowerPoint 3D 模型",
        "export_filter": "PowerPoint 3D 模型 (*.glb)",
        "export_ok": "已导出 {name}：\n{path}\n\n"
                     "在 PowerPoint 365 中选择“插入 → 3D 模型 → 此设备”即可加入并旋转。",
        "export_fail": "导出失败：{err}",
    },
    "en": {
        "title": "Molecule library",
        "subtitle": "Common school molecules as interactive 3D ball-and-stick models",
        "search": "Search name, formula or alias…",
        "all": "All categories",
        "visualize": "Load and visualize",
        "export_ppt": "Export PowerPoint 3D",
        "formula": "Formula: {formula}",
        "category": "Category: {category}",
        "atoms": "{n} atoms",
        "empty": "No matching molecules",
        "missing": "The bundled molecule library is empty. Check the installation.",
        "ppt_tip": "PowerPoint 365: Insert → 3D Models → This Device, then choose the "
                   "exported .glb. Drag the model to rotate it; supported slideshow "
                   "versions also allow rotation during a presentation.",
        "export_title": "Export PowerPoint 3D model",
        "export_filter": "PowerPoint 3D model (*.glb)",
        "export_ok": "Exported {name}:\n{path}\n\n"
                     "In PowerPoint 365, use Insert → 3D Models → This Device.",
        "export_fail": "Export failed: {err}",
    },
}


class MoleculeLibraryDialog(QDialog):
    """Browse built-in XYZ structures and send them to the main canvas."""

    def __init__(self, parent=None, lang="zh", on_visualize=None,
                 on_export_ppt=None):
        super().__init__(parent)
        self.lang = "zh" if str(lang).lower().startswith("zh") else "en"
        self._on_visualize = on_visualize
        self._on_export_ppt = on_export_ppt
        self._entries = load_library()
        self._by_id = {entry.id: entry for entry in self._entries}
        self._icons = {}
        self._previews = {}
        self.resize(900, 620)
        self.setMinimumSize(720, 500)
        self._build_ui()
        self._retranslate()
        self._refresh_list()

    def _t(self, key, **fmt):
        table = _TEXT.get(self.lang) or _TEXT["zh"]
        text = table.get(key, _TEXT["zh"].get(key, key))
        return text.format(**fmt) if fmt else text

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        self.lbl_title = QLabel()
        self.lbl_title.setStyleSheet(
            "font-size:18px;font-weight:700;color:#0D47A1;")
        root.addWidget(self.lbl_title)
        self.lbl_subtitle = QLabel()
        self.lbl_subtitle.setStyleSheet("color:#64748B;")
        root.addWidget(self.lbl_subtitle)

        filters = QHBoxLayout()
        self.cmb_category = QComboBox()
        for key in CATEGORY_ORDER:
            self.cmb_category.addItem("", key)
        self.cmb_category.insertItem(0, "", "all")
        self.cmb_category.setCurrentIndex(0)
        self.cmb_category.currentIndexChanged.connect(self._refresh_list)
        filters.addWidget(self.cmb_category)
        self.edit_search = QLineEdit()
        self.edit_search.setClearButtonEnabled(True)
        self.edit_search.textChanged.connect(self._refresh_list)
        filters.addWidget(self.edit_search, 1)
        root.addLayout(filters)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)

        self.list_widget = QListWidget()
        self.list_widget.setViewMode(QListWidget.IconMode)
        self.list_widget.setResizeMode(QListWidget.Adjust)
        self.list_widget.setMovement(QListWidget.Static)
        self.list_widget.setIconSize(QSize(120, 92))
        self.list_widget.setGridSize(QSize(154, 136))
        self.list_widget.setSpacing(5)
        self.list_widget.setWordWrap(True)
        self.list_widget.currentItemChanged.connect(self._on_current_changed)
        self.list_widget.itemDoubleClicked.connect(
            lambda _item: self._visualize_selected())
        splitter.addWidget(self.list_widget)

        detail = QFrame()
        detail.setObjectName("MoleculeLibraryDetail")
        detail.setStyleSheet(
            "QFrame#MoleculeLibraryDetail{background:#F8FAFC;"
            "border:1px solid #D8E1EC;border-radius:10px;}")
        detail_l = QVBoxLayout(detail)
        detail_l.setContentsMargins(12, 12, 12, 12)
        detail_l.setSpacing(7)
        self.lbl_preview = QLabel()
        self.lbl_preview.setAlignment(Qt.AlignCenter)
        self.lbl_preview.setMinimumSize(260, 210)
        self.lbl_preview.setStyleSheet(
            "background:white;border:1px solid #E2E8F0;border-radius:8px;")
        detail_l.addWidget(self.lbl_preview, 1)
        self.lbl_name = QLabel()
        self.lbl_name.setStyleSheet(
            "font-size:16px;font-weight:700;color:#0F172A;")
        detail_l.addWidget(self.lbl_name)
        self.lbl_formula = QLabel()
        detail_l.addWidget(self.lbl_formula)
        self.lbl_category = QLabel()
        detail_l.addWidget(self.lbl_category)
        self.lbl_description = QLabel()
        self.lbl_description.setWordWrap(True)
        self.lbl_description.setStyleSheet("color:#475569;")
        detail_l.addWidget(self.lbl_description)
        self.lbl_ppt_tip = QLabel()
        self.lbl_ppt_tip.setWordWrap(True)
        self.lbl_ppt_tip.setStyleSheet(
            "background:#EFF6FF;color:#1E40AF;border:1px solid #BFDBFE;"
            "border-radius:6px;padding:7px;")
        detail_l.addWidget(self.lbl_ppt_tip)
        self.btn_visualize = QPushButton()
        self.btn_visualize.setMinimumHeight(36)
        self.btn_visualize.clicked.connect(self._visualize_selected)
        detail_l.addWidget(self.btn_visualize)
        self.btn_export_ppt = QPushButton()
        self.btn_export_ppt.clicked.connect(self._export_selected_ppt)
        detail_l.addWidget(self.btn_export_ppt)
        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([520, 330])
        root.addWidget(splitter, 1)

    def _retranslate(self):
        self.setWindowTitle(self._t("title"))
        self.lbl_title.setText(self._t("title"))
        self.lbl_subtitle.setText(self._t("subtitle"))
        self.edit_search.setPlaceholderText(self._t("search"))
        self.cmb_category.setItemText(0, self._t("all"))
        for i, key in enumerate(CATEGORY_ORDER, start=1):
            self.cmb_category.setItemText(
                i, CATEGORY_LABELS[key][0 if self.lang == "zh" else 1])
        self.btn_visualize.setText(self._t("visualize"))
        self.btn_export_ppt.setText(self._t("export_ppt"))
        self.lbl_ppt_tip.setText(self._t("ppt_tip"))

    def _refresh_list(self, *_args):
        current = self._selected_entry()
        category = self.cmb_category.currentData() or "all"
        entries = filter_molecules(
            self._entries, category, self.edit_search.text())
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        choose = None
        for entry in entries:
            mol = load_molecule(entry)
            item = QListWidgetItem(self._molecule_icon(
                mol, 320, 230, cache_key=entry.id,
                bond_orders=entry.bond_orders),
                                   entry.display_name(self.lang))
            item.setData(Qt.UserRole, entry.id)
            item.setToolTip("%s  %s" % (entry.formula, entry.display_name(self.lang)))
            item.setSizeHint(QSize(150, 128))
            self.list_widget.addItem(item)
            if current is not None and current.id == entry.id:
                choose = item
        self.list_widget.blockSignals(False)
        if choose is None and self.list_widget.count():
            choose = self.list_widget.item(0)
        if choose is not None:
            self.list_widget.setCurrentItem(choose)
        else:
            self._clear_details(self._t("empty"))

    def _molecule_icon(self, mol, width=320, height=230, *,
                       cache_key=None, bond_orders=None):
        # Never key artwork by id(mol): the temporary Molecule object can be
        # garbage-collected and Python may reuse the same id for a different
        # library entry, producing visibly mismatched thumbnails.
        key = (cache_key or (
            tuple(mol.symbols),
            tuple(np.round(np.asarray(mol.positions), 6).reshape(-1)),
        ), width, height)
        if key in self._icons:
            return self._icons[key]
        pixmap = QPixmap(width, height)
        pixmap.fill(QColor("#FFFFFF"))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        coords = np.asarray(mol.positions, dtype=float)
        if coords.size:
            centered = coords - coords.mean(axis=0)
            try:
                _, _, vt = np.linalg.svd(centered, full_matrices=False)
                xy = centered @ vt[:2].T
            except Exception:                                # noqa: BLE001
                xy = centered[:, :2]
            xmin, ymin = np.min(xy, axis=0)
            xmax, ymax = np.max(xy, axis=0)
            span = max(float(xmax - xmin), float(ymax - ymin), 1.0)
            scale = min(width, height) * 0.76 / span
            cx, cy = width / 2.0, height / 2.0
            screen = np.column_stack((
                cx + (xy[:, 0] - (xmin + xmax) / 2.0) * scale,
                cy - (xy[:, 1] - (ymin + ymax) / 2.0) * scale,
            ))
            bond_pen = QPen(QColor("#5F6978"), 3.0)
            bond_pen.setCapStyle(Qt.RoundCap)
            painter.setPen(bond_pen)
            bonds = bond_orders or [
                (int(a), int(b), 1) for a, b in mol.bonds
            ]
            for a, b, order in bonds:
                ia, ib = int(a) - 1, int(b) - 1
                if not (0 <= ia < len(screen) and 0 <= ib < len(screen)):
                    continue
                p0 = screen[ia]
                p1 = screen[ib]
                delta = p1 - p0
                length = float(np.linalg.norm(delta))
                if length <= 1e-9:
                    continue
                normal = np.array((-delta[1], delta[0])) / length
                count = max(1, min(int(order), 3))
                offsets = {
                    1: (0.0,),
                    2: (-1.8, 1.8),
                    3: (-3.0, 0.0, 3.0),
                }[count]
                for shift in offsets:
                    q0 = p0 + normal * shift
                    q1 = p1 + normal * shift
                    painter.drawLine(
                        int(q0[0]), int(q0[1]), int(q1[0]), int(q1[1]))
            order = np.argsort(coords[:, 2]) if coords.shape[1] >= 3 else range(len(coords))
            for index in order:
                sym = str(mol.symbols[int(index)])
                radius = ATOM_RADII.get(sym, 0.42)
                r = max(8.0, min(24.0, 22.0 * radius / 0.4))
                colour = QColor(ELEMENT_COLOURS.get(sym, "#9AA4B2"))
                x, y = float(screen[int(index), 0]), float(screen[int(index), 1])
                painter.setPen(QPen(QColor("#3B4450"), 1.5))
                painter.setBrush(colour)
                painter.drawEllipse(int(x - r), int(y - r), int(2 * r), int(2 * r))
        painter.end()
        icon = QIcon(pixmap)
        self._icons[key] = icon
        return icon

    def _selected_entry(self):
        item = self.list_widget.currentItem()
        if item is None:
            return None
        return self._by_id.get(str(item.data(Qt.UserRole)))

    def _on_current_changed(self, current, _previous):
        entry = self._by_id.get(str(current.data(Qt.UserRole))) if current else None
        if entry is None:
            self._clear_details(self._t("empty"))
            return
        mol = load_molecule(entry)
        self.lbl_preview.setPixmap(self._molecule_preview(
            mol, 330, 230, cache_key=entry.id,
            bond_orders=entry.bond_orders))
        self.lbl_name.setText(entry.display_name(self.lang))
        self.lbl_formula.setText(self._t("formula", formula=entry.formula))
        category = CATEGORY_LABELS.get(entry.category, (entry.category, entry.category))
        self.lbl_category.setText(self._t(
            "category", category=category[0 if self.lang == "zh" else 1]))
        desc = entry.description(self.lang) or self._t("atoms", n=mol.atom_count)
        self.lbl_description.setText(desc)
        self.btn_visualize.setEnabled(True)
        self.btn_export_ppt.setEnabled(True)

    def _molecule_preview(self, mol, width, height, *, cache_key=None,
                          bond_orders=None):
        icon = self._molecule_icon(
            mol, width, height, cache_key=cache_key,
            bond_orders=bond_orders)
        pixmap = QPixmap(width, height)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        icon.paint(painter, 0, 0, width, height)
        painter.end()
        return pixmap

    def _clear_details(self, message):
        self.lbl_preview.clear()
        self.lbl_name.setText(message)
        self.lbl_formula.clear()
        self.lbl_category.clear()
        self.lbl_description.clear()
        self.btn_visualize.setEnabled(False)
        self.btn_export_ppt.setEnabled(False)

    def _visualize_selected(self):
        entry = self._selected_entry()
        if entry is None:
            return
        if callable(self._on_visualize):
            self._on_visualize(str(molecule_path(entry)), entry)
        self.accept()

    def _export_selected_ppt(self):
        entry = self._selected_entry()
        if entry is None:
            return
        default = str(Path.home() / "Desktop" / f"{entry.id}_ppt3d.glb")
        path, _filter = save_file(
            self, self._t("export_title"), default, self._t("export_filter"))
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() != ".glb":
            target = target.with_suffix(".glb")
        try:
            if callable(self._on_export_ppt):
                self._on_export_ppt(target, entry)
            else:
                mol = load_molecule(entry)
                export_glb(target, mol.symbols, mol.positions, bonds=mol.bonds,
                           title=entry.display_name(self.lang))
        except Exception as exc:                             # noqa: BLE001
            QMessageBox.warning(self, self._t("export_title"),
                                self._t("export_fail", err=exc))
            return
        QMessageBox.information(
            self, self._t("export_title"),
            self._t("export_ok", name=entry.display_name(self.lang), path=target))


__all__ = ["MoleculeLibraryDialog"]
