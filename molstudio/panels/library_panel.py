# -*- coding: utf-8 -*-
"""Left-nav 'Structure library' page: four sibling tabs on ONE row.

    [🧪 分子结构库] [💎 晶体结构库] [⚙ 导出设置] [📖 引文]

There is no nested tab group and no cramped right-hand sidebar: the export
settings and the citation each get a full page, so every control is readable
without scrolling.  The molecule half reuses :class:`MoleculeLibraryDialog`
as an embedded widget (its own header/buttons are hidden); the crystal half
browses the bundled offline CIF set.  All actions are handed to the main
window through callbacks, so this panel never touches the canvas or writes
files itself.
"""
from __future__ import annotations

import re

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QScrollArea, QSplitter, QTabWidget,
    QTextBrowser, QVBoxLayout, QWidget,
)

from molstudio.core.crystal_library import (
    CATEGORY_LABELS, CATEGORY_ORDER, LEVEL_LABELS,
    crystal_preview, filter_crystals, load_crystal_library,
)
from molstudio.core.molecule_library import molecule_path
from molstudio.core.ppt3d_options import Ppt3dOptions
from molstudio.ui.molecule_library_dialog import MoleculeLibraryDialog
from molstudio.ui.ppt3d_options_widget import Ppt3dOptionsWidget

_TEXT = {
    "zh": {
        "title": "结构库 · 分子与晶体",
        "subtitle": "一行四个页签：分子结构库 / 晶体结构库 / 导出设置 / 引文",
        "tabs": ("🧪 分子结构库", "💎 晶体结构库",
                 "⚙ 导出设置", "📖 引文"),
        "settings_hint": "四个页签共用这一组参数。切到「晶体结构库」并选中晶体后，"
                         "晶胞（晶体专用）中的边框、线宽、颜色与扩晶胞才会写进 .glb。",
        "citation_hint": "当前选中结构",
        "active": "当前页签：{name}",
        "current": "当前选中：{name} · {source}",
        "model_source": "MolStudio 教学简化模型（非实验结构）",
        "molecule_source": "MolStudio 内置教学分子坐标",
        "no_selection": "尚未选择结构",
        "citation_html": (
            "<h3>数据来源与致谢</h3>"
            "<p>晶体 CIF 主要来自 <a href='https://github.com/openchemistry/crystals'>"
            "Avogadro2 crystals 数据插件</a>（Geoffrey Hutchison 等，Open Chemistry，"
            "public domain）。原始结构来自 "
            "<a href='http://www.crystallography.net/'>Crystallography Open Database"
            "（COD）</a>、American Mineralogist Crystal Structure Database（AMCSD）"
            "与 International Zeolite Association（IZA）。每个 CIF 都保留了原始文件头"
            "里的文献与数据库编号，在此向 COD、AMCSD 及原结构测定者致谢。</p>"
            "<h3>教学模型说明</h3>"
            "<p><code>po-simple-cubic.cif</code>（简单立方钋）、"
            "<code>dry-ice.cif</code>（干冰）与 "
            "<code>white-phosphorus.cif</code>（白磷 P₄）是 MolStudio 为教学补写的"
            "<b>简化模型，不是实验结构</b>：干冰把 4 个 CO₂ 分子按面心立方排布并统一"
            "取向（真实 Pa3 结构分子取向交错），白磷只放了一个 P₄ 四面体分子。"
            "课堂上请说明这一点。</p>"
            "<p>冰 Ih、α-石英、CaTiO₃ 等是实测结构，与教材里的理想化模型"
            "（例如理想立方钙钛矿、P6₃/mmc 冰）可能略有差别；库里另收 "
            "<code>SrTiO3-Tausonite.cif</code> 作为理想立方钙钛矿模型。</p>"
            "<h3>分子结构</h3>"
            "<p>分子结构库内的 XYZ 坐标为 MolStudio 内置教学模型，用于中学"
            "分子空间构型演示，不作为实验测定坐标引用。</p>"
        ),
        "search": "搜索名称、化学式、空间群或教学点…",
        "all": "全部分类",
        "all_levels": "全部层级",
        "visualize": "载入并可视化",
        "export": "导出 PowerPoint 3D",
        "crystal_tab": "打开晶体 tab 调整",
        "no_preview": "暂无预览图",
        "source": "来源：{source}",
        "space_group": "空间群：{value}",
        "cell": "晶胞：{value}",
        "structure": "结构型：{value}",
        "coordination": "配位数：{value}",
        "contents": "晶胞内容：{value}",
        "point": "考点：{value}",
        "level": "层级：{value}",
        "model_warn": "教学模型（非实验结构）",
        "empty": "没有找到匹配的结构",
    },
    "en": {
        "title": "Structure library · molecules & crystals",
        "subtitle": "Four sibling tabs: Molecules / Crystals / Export settings / Citation",
        "tabs": ("🧪 Molecules", "💎 Crystals",
                 "⚙ Export settings", "📖 Citation"),
        "settings_hint": "All four tabs share these options. The unit-cell frame, "
                         "width, colour and supercell are written to the .glb only "
                         "when a crystal is selected in the Crystals tab.",
        "citation_hint": "Selected structure",
        "active": "Current tab: {name}",
        "current": "Selected: {name} · {source}",
        "model_source": "MolStudio teaching model (not experimental)",
        "molecule_source": "MolStudio built-in teaching coordinates",
        "no_selection": "No structure selected",
        "citation_html": (
            "<h3>Data sources & acknowledgements</h3>"
            "<p>Crystal CIFs come mostly from the "
            "<a href='https://github.com/openchemistry/crystals'>Avogadro2 "
            "crystals data plugin</a> (Geoffrey Hutchison et al., Open Chemistry, "
            "public domain). Original structures are from the "
            "<a href='http://www.crystallography.net/'>Crystallography Open "
            "Database (COD)</a>, the American Mineralogist Crystal Structure "
            "Database (AMCSD) and the International Zeolite Association (IZA). "
            "Every CIF keeps the citation and database ID from its original "
            "header; we thank COD, AMCSD and the original structure authors.</p>"
            "<h3>Teaching models</h3>"
            "<p><code>po-simple-cubic.cif</code>, <code>dry-ice.cif</code> and "
            "<code>white-phosphorus.cif</code> are simplified MolStudio teaching "
            "models, <b>not experimental structures</b>. Dry ice places four CO2 "
            "molecules on an fcc lattice with a single orientation (real Pa3 dry "
            "ice alternates orientations); white phosphorus contains one P4 "
            "tetrahedron. Please note this in class.</p>"
            "<p>Ice Ih, alpha-quartz and CaTiO3 are measured structures and may "
            "differ slightly from the idealised textbook cells; "
            "<code>SrTiO3-Tausonite.cif</code> is included as an ideal cubic "
            "perovskite model.</p>"
            "<h3>Molecules</h3>"
            "<p>The XYZ coordinates in the molecule library are built-in teaching "
            "models for school geometry demonstrations, not experimental "
            "coordinates.</p>"
        ),
        "search": "Search name, formula, space group or topic…",
        "all": "All categories",
        "all_levels": "All levels",
        "visualize": "Load and visualize",
        "export": "Export PowerPoint 3D",
        "crystal_tab": "Open crystal tab",
        "no_preview": "No preview",
        "source": "Source: {source}",
        "space_group": "Space group: {value}",
        "cell": "Cell: {value}",
        "structure": "Structure type: {value}",
        "coordination": "Coordination: {value}",
        "contents": "Cell contents: {value}",
        "point": "Teaching point: {value}",
        "level": "Level: {value}",
        "model_warn": "Teaching model (not experimental)",
        "empty": "No matching structure",
    },
}


_CJK = re.compile(r"[\u4e00-\u9fff]")

TAB_MOLECULES = 0
TAB_CRYSTALS = 1
TAB_SETTINGS = 2
TAB_CITATION = 3


def _placeholder_icon(text, width=240, height=170):
    pixmap = QPixmap(width, height)
    pixmap.fill(QColor("#F1F5F9"))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QColor("#64748B"))
    font = QFont()
    font.setPointSize(11)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, text)
    painter.end()
    return QIcon(pixmap)


class CrystalLibraryView(QWidget):
    """Browser for the bundled CIF library (with Avogadro2 PNG previews)."""

    currentEntryChanged = pyqtSignal(object)
    visualizeRequested = pyqtSignal()

    def __init__(self, parent=None, lang="zh"):
        super().__init__(parent)
        self.lang = "zh" if str(lang).lower().startswith("zh") else "en"
        self._entries = load_crystal_library()
        self._by_id = {entry.id: entry for entry in self._entries}
        self._icons = {}
        self._build_ui()
        self.set_language(self.lang)
        self._refresh_list()

    def _t(self, key, **fmt):
        table = _TEXT.get(self.lang) or _TEXT["zh"]
        text = table.get(key, _TEXT["zh"].get(key, key))
        return text.format(**fmt) if fmt else text

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(6)

        filters = QHBoxLayout()
        self.cmb_category = QComboBox()
        self.cmb_category.addItem("", "all")
        for key in CATEGORY_ORDER:
            self.cmb_category.addItem("", key)
        self.cmb_category.currentIndexChanged.connect(self._refresh_list)
        filters.addWidget(self.cmb_category)
        self.cmb_level = QComboBox()
        self.cmb_level.addItem("", 0)
        for value in sorted(LEVEL_LABELS):
            self.cmb_level.addItem("", value)
        self.cmb_level.currentIndexChanged.connect(self._refresh_list)
        filters.addWidget(self.cmb_level)
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
        self.list_widget.setGridSize(QSize(180, 158))
        self.list_widget.setSpacing(5)
        self.list_widget.setWordWrap(True)
        self.list_widget.currentItemChanged.connect(self._on_current_changed)
        self.list_widget.itemDoubleClicked.connect(
            lambda _item: self.visualizeRequested.emit())
        body.addWidget(self.list_widget)

        detail = QFrame()
        detail.setObjectName("CrystalLibraryDetail")
        detail.setStyleSheet(
            "QFrame#CrystalLibraryDetail{background:#F8FAFC;"
            "border:1px solid #D8E1EC;border-radius:10px;}")
        detail_l = QVBoxLayout(detail)
        detail_l.setContentsMargins(10, 10, 10, 10)
        detail_l.setSpacing(5)
        self.lbl_preview = QLabel()
        self.lbl_preview.setAlignment(Qt.AlignCenter)
        self.lbl_preview.setMinimumHeight(180)
        self.lbl_preview.setStyleSheet(
            "background:white;border:1px solid #E2E8F0;border-radius:8px;")
        detail_l.addWidget(self.lbl_preview, 1)
        self.lbl_name = QLabel()
        self.lbl_name.setStyleSheet(
            "font-size:16px;font-weight:700;color:#0F172A;")
        self.lbl_name.setWordWrap(True)
        detail_l.addWidget(self.lbl_name)
        self.lbl_details = QLabel()
        self.lbl_details.setWordWrap(True)
        self.lbl_details.setStyleSheet("color:#475569;")
        detail_l.addWidget(self.lbl_details, 2)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        holder = QWidget()
        holder_l = QVBoxLayout(holder)
        holder_l.setContentsMargins(0, 0, 0, 0)
        holder_l.addWidget(detail, 1)
        scroll.setWidget(holder)
        body.addWidget(scroll)
        body.setStretchFactor(0, 3)
        body.setStretchFactor(1, 2)
        body.setSizes([620, 400])
        root.addWidget(body, 1)

    def set_language(self, lang):
        self.lang = "zh" if str(lang).lower().startswith("zh") else "en"
        self.edit_search.setPlaceholderText(self._t("search"))
        self.cmb_category.setItemText(0, self._t("all"))
        for i, key in enumerate(CATEGORY_ORDER, start=1):
            labels = CATEGORY_LABELS[key]
            self.cmb_category.setItemText(
                i, labels[0 if self.lang == "zh" else 1])
        self.cmb_level.setItemText(0, self._t("all_levels"))
        for i, value in enumerate(sorted(LEVEL_LABELS), start=1):
            labels = LEVEL_LABELS[value]
            self.cmb_level.setItemText(
                i, labels[0 if self.lang == "zh" else 1])

    def _icon(self, entry):
        if entry.id in self._icons:
            return self._icons[entry.id]
        path = crystal_preview(entry)
        if path is not None:
            icon = QIcon(str(path))
        else:
            icon = _placeholder_icon(entry.formula or entry.id)
        self._icons[entry.id] = icon
        return icon

    def _refresh_list(self, *_args):
        current = self.current_entry()
        category = self.cmb_category.currentData() or "all"
        level = int(self.cmb_level.currentData() or 0)
        entries = filter_crystals(self._entries, category,
                                  self.edit_search.text(), level)
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        choose = None
        for entry in entries:
            item = QListWidgetItem(self._icon(entry),
                                   entry.display_name(self.lang))
            item.setData(Qt.UserRole, entry.id)
            # structure_type / teaching_point are Chinese teaching metadata;
            # in English mode keep the tooltip purely translatable.
            tip = ("%s · %s" % (entry.formula, entry.structure_type)
                   if self.lang == "zh" else entry.formula)
            item.setToolTip(tip)
            item.setSizeHint(QSize(176, 150))
            self.list_widget.addItem(item)
            if current is not None and current.id == entry.id:
                choose = item
        self.list_widget.blockSignals(False)
        if choose is None and self.list_widget.count():
            choose = self.list_widget.item(0)
        if choose is not None:
            self.list_widget.setCurrentItem(choose)
        else:
            self.lbl_preview.clear()
            self.lbl_name.setText(self._t("empty"))
            self.lbl_details.clear()
            self.currentEntryChanged.emit(None)

    def current_entry(self):
        item = self.list_widget.currentItem()
        if item is None:
            return None
        return self._by_id.get(str(item.data(Qt.UserRole)))

    def _on_current_changed(self, current, _previous):
        entry = self._by_id.get(str(current.data(Qt.UserRole))) \
            if current else None
        if entry is None:
            self.lbl_preview.clear()
            self.lbl_name.setText(self._t("empty"))
            self.lbl_details.clear()
            self.currentEntryChanged.emit(None)
            return
        path = crystal_preview(entry)
        if path is not None:
            pixmap = QPixmap(str(path))
            self.lbl_preview.setPixmap(
                pixmap.scaled(self.lbl_preview.width() or 320, 210,
                              Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.lbl_preview.setText(self._t("no_preview"))
        lines = [
            "%s　%s" % (entry.formula, entry.category_label(self.lang)),
            self._t("level", value=entry.level_label(self.lang)),
            self._t("structure", value=entry.structure_type),
            self._t("space_group", value=entry.space_group or "—"),
            self._t("cell", value=entry.cell or "—"),
            self._t("coordination", value=entry.coordination or "—"),
            self._t("contents", value=entry.cell_contents or "—"),
            self._t("point", value=entry.teaching_point or "—"),
            entry.description(self.lang),
            self._t("source", source=entry.source),
        ]
        if entry.generated:
            lines.append("⚠ " + self._t("model_warn"))
        if self.lang != "zh":
            # Only the Chinese edition carries the free-text teaching notes;
            # drop untranslatable CJK lines instead of showing them in EN UI.
            lines = [line for line in lines if not _CJK.search(line)]
        self.lbl_name.setText(entry.display_name(self.lang))
        self.lbl_details.setText("\n".join(line for line in lines if line))
        self.currentEntryChanged.emit(entry)


class LibraryPanel(QWidget):
    """Structure library: four sibling tabs on a single row, no nesting."""

    def __init__(self, parent=None, lang="zh", on_visualize_molecule=None,
                 on_export_molecule=None, on_visualize_crystal=None,
                 on_export_crystal=None, on_open_crystal_tab=None):
        super().__init__(parent)
        self.lang = "zh" if str(lang).lower().startswith("zh") else "en"
        self._on_visualize_molecule = on_visualize_molecule
        self._on_export_molecule = on_export_molecule
        self._on_visualize_crystal = on_visualize_crystal
        self._on_export_crystal = on_export_crystal
        self._on_open_crystal_tab = on_open_crystal_tab
        self._build_ui()
        self.set_language(self.lang)

    def _t(self, key, **fmt):
        table = _TEXT.get(self.lang) or _TEXT["zh"]
        text = table.get(key, _TEXT["zh"].get(key, key))
        return text.format(**fmt) if fmt else text

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)
        self.lbl_title = QLabel()
        self.lbl_title.setStyleSheet(
            "font-size:18px;font-weight:700;color:#0D47A1;")
        root.addWidget(self.lbl_title)
        self.lbl_subtitle = QLabel()
        self.lbl_subtitle.setStyleSheet("color:#64748B;")
        root.addWidget(self.lbl_subtitle)

        # ── the single tab bar: four siblings, forced onto ONE row ──
        self.sub_tabs = QTabWidget()
        self.sub_tabs.setDocumentMode(True)
        self.sub_tabs.setUsesScrollButtons(True)
        self.sub_tabs.tabBar().setElideMode(Qt.ElideNone)
        self.sub_tabs.setStyleSheet(
            "QTabBar::tab{min-width:150px;padding:7px 14px;"
            "font-size:13px;}"
            "QTabBar::tab:selected{font-weight:700;color:#0D47A1;}")
        root.addWidget(self.sub_tabs, 1)

        # ── tab 0: molecules ──
        self.molecule_view = MoleculeLibraryDialog(
            parent=self.sub_tabs, lang=self.lang,
            on_visualize=self._visualize_molecule)
        mv = self.molecule_view
        mv.setWindowFlags(Qt.Widget)
        mv.setMinimumSize(0, 0)
        for widget in (mv.lbl_title, mv.lbl_subtitle, mv.lbl_ppt_tip,
                       mv.btn_visualize, mv.btn_export_ppt):
            widget.hide()
        try:
            mv.list_widget.itemDoubleClicked.disconnect()
        except TypeError:
            pass
        mv.list_widget.itemDoubleClicked.connect(
            lambda _item: self._visualize_molecule_current())
        mv.list_widget.currentItemChanged.connect(
            lambda *_args: self._refresh_current_source())
        self.sub_tabs.addTab(mv, "")

        # ── tab 1: crystals ──
        self.crystal_view = CrystalLibraryView(self.sub_tabs, self.lang)
        self.crystal_view.visualizeRequested.connect(
            self._visualize_crystal_current)
        self.crystal_view.currentEntryChanged.connect(
            lambda _entry: self._refresh_current_source())
        self.sub_tabs.addTab(self.crystal_view, "")

        # ── tab 2: export settings (full page, no sidebar) ──
        settings_page = QWidget()
        set_l = QVBoxLayout(settings_page)
        set_l.setContentsMargins(12, 12, 12, 12)
        set_l.setSpacing(8)
        self.lbl_settings_hint = QLabel()
        self.lbl_settings_hint.setWordWrap(True)
        self.lbl_settings_hint.setStyleSheet(
            "color:#1E40AF;background:#EFF6FF;border:1px solid #BFDBFE;"
            "border-radius:6px;padding:8px;")
        set_l.addWidget(self.lbl_settings_hint, 0)
        self.options_widget = Ppt3dOptionsWidget(settings_page, self.lang)
        self.options_widget.set_crystal_mode(True)   # crystals always available
        set_l.addWidget(self.options_widget, 1)
        self.sub_tabs.addTab(settings_page, "")

        # ── tab 3: citation (full page) ──
        citation_page = QWidget()
        cite_l = QVBoxLayout(citation_page)
        cite_l.setContentsMargins(12, 12, 12, 12)
        cite_l.setSpacing(8)
        self.txt_citation = QTextBrowser()
        self.txt_citation.setOpenExternalLinks(True)
        self.txt_citation.setStyleSheet(
            "QTextBrowser{background:#FFFFFF;border:1px solid #E2E8F0;"
            "border-radius:8px;color:#334155;font-size:13px;padding:10px;}")
        cite_l.addWidget(self.txt_citation, 1)
        self.lbl_citation_hint = QLabel()
        self.lbl_citation_hint.setStyleSheet(
            "font-weight:700;color:#0F172A;")
        cite_l.addWidget(self.lbl_citation_hint, 0)
        self.lbl_current_source = QLabel()
        self.lbl_current_source.setWordWrap(True)
        self.lbl_current_source.setStyleSheet(
            "color:#0F766E;background:#F0FDFA;border-radius:6px;padding:8px;")
        cite_l.addWidget(self.lbl_current_source, 0)
        self.sub_tabs.addTab(citation_page, "")

        # ── shared action bar (enabled per tab) ──
        buttons = QHBoxLayout()
        self.btn_visualize = QPushButton()
        self.btn_visualize.setMinimumHeight(36)
        self.btn_visualize.clicked.connect(self._visualize_current)
        buttons.addWidget(self.btn_visualize)
        self.btn_export = QPushButton()
        self.btn_export.setMinimumHeight(36)
        self.btn_export.clicked.connect(self._export_current)
        buttons.addWidget(self.btn_export)
        self.btn_crystal_tab = QPushButton()
        self.btn_crystal_tab.setMinimumHeight(36)
        self.btn_crystal_tab.clicked.connect(self._open_crystal_tab)
        buttons.addWidget(self.btn_crystal_tab)
        buttons.addStretch(1)
        self.lbl_active = QLabel()
        self.lbl_active.setStyleSheet("color:#64748B;")
        buttons.addWidget(self.lbl_active)
        root.addLayout(buttons)

        self.sub_tabs.currentChanged.connect(self._on_tab_changed)
        self._on_tab_changed(self.sub_tabs.currentIndex())

    def set_lang(self, lang):
        """Alias used by the main window's language refresh loop."""
        self.set_language(lang)

    def set_language(self, lang):
        self.lang = "zh" if str(lang).lower().startswith("zh") else "en"
        self.lbl_title.setText(self._t("title"))
        self.lbl_subtitle.setText(self._t("subtitle"))
        for i, label in enumerate(self._t("tabs")):
            self.sub_tabs.setTabText(i, label)
        self.lbl_settings_hint.setText(self._t("settings_hint"))
        self.lbl_citation_hint.setText(self._t("citation_hint"))
        self.txt_citation.setHtml(self._t("citation_html"))
        self.btn_visualize.setText(self._t("visualize"))
        self.btn_export.setText(self._t("export"))
        self.btn_crystal_tab.setText(self._t("crystal_tab"))
        self.options_widget.set_language(self.lang)
        self.molecule_view.lang = self.lang
        self.molecule_view._retranslate()
        # Detail labels are filled by currentItemChanged, not _retranslate;
        # rebuild both lists so names AND details follow the new language.
        self.molecule_view._refresh_list()
        self.crystal_view.set_language(self.lang)
        self.crystal_view._refresh_list()
        self._refresh_active_label()
        self._refresh_current_source()

    def _on_tab_changed(self, index):
        browser = index in (TAB_MOLECULES, TAB_CRYSTALS)
        self.btn_visualize.setEnabled(browser)
        self.btn_export.setEnabled(browser)
        self.btn_crystal_tab.setEnabled(index == TAB_CRYSTALS)
        self._refresh_active_label()
        self._refresh_current_source()

    def _refresh_active_label(self):
        index = self.sub_tabs.currentIndex()
        self.lbl_active.setText(self._t("active", name=self._t("tabs")[index]))

    def is_crystal_page(self):
        return self.sub_tabs.currentIndex() == TAB_CRYSTALS

    def _refresh_current_source(self):
        if self.is_crystal_page():
            entry = self.crystal_view.current_entry()
            if entry is None:
                self.lbl_current_source.setText(self._t("no_selection"))
                return
            source = entry.source
            if self.lang != "zh" and (not source or _CJK.search(source)):
                source = self._t("model_source")
        else:
            entry = self.molecule_view._selected_entry()
            if entry is None:
                self.lbl_current_source.setText(self._t("no_selection"))
                return
            source = self._t("molecule_source")
        self.lbl_current_source.setText(
            self._t("current", name=entry.display_name(self.lang),
                    source=source))

    def current_entry(self):
        return (self.crystal_view.current_entry() if self.is_crystal_page()
                else self.molecule_view._selected_entry())

    def options(self) -> Ppt3dOptions:
        return self.options_widget.options()

    def set_options(self, options):
        self.options_widget.set_options(options or Ppt3dOptions())

    def set_active(self, kind):
        """Compatibility helper: jump to the molecule or crystal tab."""
        self.sub_tabs.setCurrentIndex(
            TAB_CRYSTALS if kind == "crystal" else TAB_MOLECULES)

    # ── actions ──

    def _visualize_molecule(self, path, entry):
        if callable(self._on_visualize_molecule):
            self._on_visualize_molecule(path, entry)

    def _visualize_molecule_current(self):
        entry = self.molecule_view._selected_entry()
        if entry is not None:
            self._visualize_molecule(str(molecule_path(entry)), entry)

    def _visualize_crystal_current(self):
        entry = self.crystal_view.current_entry()
        if entry is not None and callable(self._on_visualize_crystal):
            self._on_visualize_crystal(entry, self.options())

    def _visualize_current(self):
        if self.is_crystal_page():
            self._visualize_crystal_current()
        else:
            self._visualize_molecule_current()

    def _export_current(self):
        entry = self.current_entry()
        if entry is None:
            return
        if self.is_crystal_page():
            if callable(self._on_export_crystal):
                self._on_export_crystal(entry, self.options())
        elif callable(self._on_export_molecule):
            self._on_export_molecule(entry, self.options())

    def _open_crystal_tab(self):
        if callable(self._on_open_crystal_tab):
            self._on_open_crystal_tab()

    def switch_to_crystals(self, text=""):
        """Jump straight to a searched crystal."""
        if text:
            self.crystal_view.edit_search.setText(text)
        self.sub_tabs.setCurrentIndex(TAB_CRYSTALS)
