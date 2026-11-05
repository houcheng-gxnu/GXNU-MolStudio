# -*- coding: utf-8 -*-
"""Simplified MolStudio TDOS / PDOS / OPDOS panel."""

from __future__ import annotations

import os

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QPixmap
from PyQt5.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QSplitter, QSplitterHandle, QVBoxLayout,
    QWidget,
)

from molstudio.core.dos import (
    DOSCancelled,
    DOSFragment,
    DOSWorkflowError,
    detect_open_shell,
    export_dos_csv,
    normalize_unit,
    render_saved_dos,
    run_dos_pipeline,
    suggest_dos_range,
    validate_dos_source,
)
from molstudio.panels.etsnocv.molcanvas import get_atoms_from_any
from molstudio.render.molcanvas import get_atoms_from_fchk


COLORS = (
    "#d62728", "#2146f3", "#cf2bc9", "#f28e2b", "#9467bd",
    "#17becf", "#8c564b", "#bcbd22", "#e377c2", "#7f7f7f",
)

ELEMENT_NAMES = {
    "H": "Hydrogen", "B": "Boron", "C": "Carbon", "N": "Nitrogen",
    "O": "Oxygen", "F": "Fluorine", "Si": "Silicon", "P": "Phosphorus",
    "S": "Sulfur", "Cl": "Chlorine", "Br": "Bromine", "I": "Iodine",
    "Fe": "Iron", "Co": "Cobalt", "Ni": "Nickel", "Cu": "Copper",
    "Zn": "Zinc", "Ru": "Ruthenium", "Rh": "Rhodium", "Pd": "Palladium",
    "Ag": "Silver", "Ir": "Iridium", "Pt": "Platinum", "Au": "Gold",
}


TEXT = {
    "zh": {
        "title": "态密度",
        "intro": (
            "输入文件跟随主程序，结果自动写回输入文件所在目录。"
            "选择绘图内容和 PDOS 轨道后即可出图。"
            "<a href=\"http://sobereva.com/482\">Multiwfn DOS 教程</a>"
        ),
        "source": "当前波函数",
        "splitter_tip": "拖动调整参数面板宽度，双击复位",
        "source_none": "请先在主界面载入 .fch / .fchk 文件。",
        "source_ready": "{name}\n{atoms} · {shell} · 输出到当前目录",
        "closed": "闭壳层",
        "open": "开壳层",
        "draw": "绘图内容",
        "colors": "每条 DOS 曲线颜色",
        "reset_colors": "恢复默认颜色",
        "fill_curves": "曲线下方同色透明填充",
        "tdos": "总态密度 TDOS",
        "pdos": "分态密度 PDOS",
        "opdos": "重叠布居 OPDOS",
        "opdos_tip": "至少定义两个 Mulliken/SCPA 片段后才可用",
        "fragments": "PDOS 轨道片段",
        "fragments_hint": (
            "按元素和轨道类型添加。例如 Fe：全部轨道；C：Pz；"
            "C：S+Px+Py。前两个片段用于计算 OPDOS。"),
        "element": "元素",
        "orbital": "轨道",
        "add": "添加片段",
        "canvas_selection": "用画布选中原子",
        "remove": "删除",
        "up": "上移",
        "down": "下移",
        "empty": "尚未选择 PDOS 片段",
        "count": "{n} 个片段",
        "orbital_all": "全部轨道",
        "orbital_s": "s",
        "orbital_p": "p",
        "orbital_d": "d",
        "orbital_pz": "Pz",
        "orbital_px": "Px",
        "orbital_py": "Py",
        "orbital_sxyz": "S+Px+Py",
        "advanced": "高级设置",
        "advanced_show": "展开高级设置",
        "advanced_hide": "收起高级设置",
        "fwhm": "展宽 FWHM",
        "curve_scale": "曲线比例",
        "unit": "能量单位",
        "broadening": "展宽函数",
        "spin": "自旋",
        "method": "轨道成分方法",
        "custom_range": "自定义能量范围",
        "lower": "下限",
        "upper": "上限",
        "step": "刻度",
        "levels": "显示轨道竖线",
        "centers": "显示 PDOS / D 带中心",
        "centers_tip": (
            "Multiwfn 的 PDOS 中心按当前能量范围计算；"
            "相对值 = PDOS 中心 − HOMO。"),
        "shift": "以 HOMO 为零点",
        "center_values": "PDOS 中心（相对 HOMO）",
        "run_group": "操作",
        "run": "生成 DOS 图",
        "stop": "停止",
        "open": "打开所在目录",
        "ready": "就绪：载入波函数，选择片段后点击生成。",
        "working": "正在计算并绘图…",
        "done": "绘图完成",
        "failed": "DOS 计算失败",
        "cancel": "正在停止…",
        "preview": "DOS 图",
        "preview_empty": "结果图会显示在这里",
        "redraw": "重新绘图",
        "save_image": "导出图片…",
        "save_csv": "导出数据 CSV…",
        "warning": "提示",
        "need_source": "请先在主界面载入 DOS 输入文件。",
        "need_mw": "请先在主界面路径设置中配置 Multiwfn。",
        "need_content": "请至少选择 TDOS 或 PDOS。",
        "need_fragments": "已选择 PDOS，请先添加至少一个轨道片段。",
        "need_selection": "请先在主画布中选择原子。",
        "max": "最多支持 10 个片段。",
        "out": "输出：{path}",
        "all_spins": "全部（上下镜像）",
        "alpha": "Alpha",
        "beta": "Beta",
        "mulliken": "Mulliken",
        "scpa": "SCPA",
        "hirshfeld": "Hirshfeld",
        "becke": "Becke",
        "gaussian": "Gaussian",
        "lorentzian": "Lorentzian",
        "pseudo": "Pseudo-Voigt",
        "image_filter": "PNG (*.png);;PDF (*.pdf);;SVG (*.svg)",
        "csv_filter": "CSV (*.csv)",
        "selection_name": "画布选中原子",
        "selected_n": "选中 {n} 个原子",
        "basis_only": "Hirshfeld/Becke 只能使用“全部轨道”的原子片段。",
    },
    "en": {
        "title": "Density of states",
        "intro": (
            "The input follows the main program and output returns to the input "
            "folder. Choose the plot contents and PDOS orbitals, then generate."
            " <a href=\"http://sobereva.com/482\">Multiwfn DOS tutorial</a>"
        ),
        "source": "Current wavefunction",
        "splitter_tip": "Drag to resize the settings panel; double-click to reset",
        "source_none": "Load a .fch / .fchk file in the main window first.",
        "source_ready": "{name}\n{atoms} · {shell} · output in current folder",
        "closed": "closed shell",
        "open": "open shell",
        "draw": "Plot contents",
        "colors": "Colors for each DOS curve",
        "reset_colors": "Reset default colors",
        "fill_curves": "Same-hue transparent fill",
        "tdos": "Total DOS",
        "pdos": "Partial DOS",
        "opdos": "Overlap-population DOS",
        "opdos_tip": "Requires at least two Mulliken/SCPA fragments",
        "fragments": "PDOS orbital fragments",
        "fragments_hint": (
            "Add by element and orbital type, e.g. Fe: all; C: Pz; "
            "C: S+Px+Py. The first two fragments generate OPDOS."),
        "element": "Element",
        "orbital": "Orbital",
        "add": "Add fragment",
        "canvas_selection": "Use canvas selection",
        "remove": "Remove",
        "up": "Up",
        "down": "Down",
        "empty": "No PDOS fragments selected",
        "count": "{n} fragments",
        "orbital_all": "All orbitals",
        "orbital_s": "s",
        "orbital_p": "p",
        "orbital_d": "d",
        "orbital_pz": "Pz",
        "orbital_px": "Px",
        "orbital_py": "Py",
        "orbital_sxyz": "S+Px+Py",
        "advanced": "Advanced",
        "advanced_show": "Show advanced settings",
        "advanced_hide": "Hide advanced settings",
        "fwhm": "FWHM",
        "curve_scale": "Curve scale",
        "unit": "Energy unit",
        "broadening": "Broadening",
        "spin": "Spin",
        "method": "Orbital composition",
        "custom_range": "Custom energy range",
        "lower": "lower",
        "upper": "upper",
        "step": "tick",
        "levels": "Show orbital levels",
        "centers": "Show DOS centers",
        "centers_tip": (
            "Multiwfn computes the PDOS center over the current energy "
            "window; relative value = PDOS center − HOMO."),
        "shift": "Set HOMO to zero",
        "center_values": "PDOS centers (relative to HOMO)",
        "run_group": "Run",
        "run": "Generate DOS plot",
        "stop": "Stop",
        "open": "Open folder",
        "ready": "Ready: load a wavefunction, choose fragments and generate.",
        "working": "Calculating and plotting…",
        "done": "Plot complete",
        "failed": "DOS calculation failed",
        "cancel": "Stopping…",
        "preview": "DOS plot",
        "preview_empty": "The DOS plot appears here",
        "redraw": "Redraw",
        "save_image": "Export image…",
        "save_csv": "Export data CSV…",
        "warning": "Notice",
        "need_source": "Load a DOS input file in the main window first.",
        "need_mw": "Configure Multiwfn in the main-window Path Settings.",
        "need_content": "Select TDOS or PDOS.",
        "need_fragments": "PDOS is selected; add at least one orbital fragment.",
        "need_selection": "Select atoms on the main canvas first.",
        "max": "Up to 10 fragments are supported.",
        "out": "Output: {path}",
        "all_spins": "All (mirrored)",
        "alpha": "Alpha",
        "beta": "Beta",
        "mulliken": "Mulliken",
        "scpa": "SCPA",
        "hirshfeld": "Hirshfeld",
        "becke": "Becke",
        "gaussian": "Gaussian",
        "lorentzian": "Lorentzian",
        "pseudo": "Pseudo-Voigt",
        "image_filter": "PNG (*.png);;PDF (*.pdf);;SVG (*.svg)",
        "csv_filter": "CSV (*.csv)",
        "selection_name": "Canvas selection",
        "selected_n": "{n} selected atoms",
        "basis_only": "Hirshfeld/Becke require atom fragments using all orbitals.",
    },
}


class _DOSplitterHandle(QSplitterHandle):
    def mouseDoubleClickEvent(self, event):
        splitter = self.splitter()
        reset = getattr(splitter, "_reset_sizes", None)
        if callable(reset):
            reset()
        super().mouseDoubleClickEvent(event)


class _DOSplitter(QSplitter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setHandleWidth(8)
        self._default_sizes = None

    def set_default_sizes(self, sizes):
        self._default_sizes = list(sizes)

    def _reset_sizes(self):
        if self._default_sizes:
            self.setSizes(self._default_sizes)

    def createHandle(self):
        handle = _DOSplitterHandle(self.orientation(), self)
        handle.setToolTip("拖动调整参数面板宽度，双击复位")
        handle.setCursor(
            Qt.SplitHCursor if self.orientation() == Qt.Horizontal
            else Qt.SplitVCursor)
        return handle


class AspectPixmapLabel(QLabel):
    """Preview label that always scales the complete image to fit."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source_pixmap = QPixmap()
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_source_pixmap(self, pixmap):
        self._source_pixmap = QPixmap(pixmap)
        self._fit_pixmap()

    def clear_source(self):
        self._source_pixmap = QPixmap()
        self.clear()

    def _fit_pixmap(self):
        if self._source_pixmap.isNull():
            return
        target = self.contentsRect().size()
        if target.width() <= 2 or target.height() <= 2:
            return
        self.setPixmap(
            self._source_pixmap.scaled(
                target, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_pixmap()


class DOSWorker(QThread):
    stage = pyqtSignal(int, str)
    log = pyqtSignal(str)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, kwargs, parent=None):
        super().__init__(parent)
        self.kwargs = kwargs
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True

    def run(self):
        try:
            result = run_dos_pipeline(
                on_stage=lambda pct, text: self.stage.emit(int(pct), text),
                on_log=self.log.emit,
                cancel=lambda: self._stop_requested,
                **self.kwargs)
            self.completed.emit(result)
        except DOSCancelled as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class DOSPanel(QWidget):
    """Main-program-driven DOS workflow with minimal visible controls."""

    def __init__(self, get_input_path=None, get_multiwfn=None,
                 get_selected_atoms=None, log_func=None, parent=None):
        super().__init__(parent)
        self._get_input_path = get_input_path or (lambda: "")
        self._get_multiwfn = get_multiwfn or (lambda: "")
        self._get_selected_atoms = get_selected_atoms or (lambda: [])
        self._log_func = log_func or (lambda _text: None)
        self._source_path = ""
        self._atoms = []
        self._element_indices = {}
        self._fragments = []
        self._curve_colors = {}
        self._color_buttons = {}
        self._worker = None
        self._last_result = None
        self._lang = "zh"
        self._unit = "a.u."
        self._is_open_shell = False
        self._sizes_initialized = False
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._build_ui()
        self._apply_lang()
        self.set_source_from_main(self._get_input_path())

    def _t(self, key):
        return TEXT[self._lang].get(key, key)

    @staticmethod
    def _element_symbol(atom):
        try:
            return str(atom[1]).strip().capitalize()
        except (IndexError, TypeError):
            return ""

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(0)
        splitter = _DOSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        self._splitter = splitter
        controls_content = QWidget()
        root = QVBoxLayout(controls_content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        controls = QScrollArea()
        controls.setWidgetResizable(True)
        controls.setFrameShape(QFrame.NoFrame)
        controls.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        controls.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        controls.setMinimumWidth(300)
        controls.setWidget(controls_content)
        self.controls_panel = controls

        self.lbl_title = QLabel()
        self.lbl_title.setStyleSheet(
            "font-size:18px;font-weight:700;color:#0D47A1;")
        root.addWidget(self.lbl_title)
        self.lbl_intro = QLabel()
        self.lbl_intro.setWordWrap(True)
        self.lbl_intro.setOpenExternalLinks(True)
        self.lbl_intro.setStyleSheet("color:#475569;")
        root.addWidget(self.lbl_intro)

        self.grp_source = QGroupBox()
        source_l = QVBoxLayout(self.grp_source)
        source_l.setContentsMargins(10, 12, 10, 10)
        self.lbl_source = QLabel()
        self.lbl_source.setWordWrap(True)
        self.lbl_source.setStyleSheet(
            "padding:8px;background:#F4F8FC;border:1px solid #D9E4EF;"
            "border-radius:6px;color:#24445F;")
        source_l.addWidget(self.lbl_source)
        root.addWidget(self.grp_source)

        self.grp_draw = QGroupBox()
        draw_l = QVBoxLayout(self.grp_draw)
        draw_l.setContentsMargins(10, 12, 10, 10)
        draw_l.setSpacing(7)
        types = QHBoxLayout()
        self.chk_tdos = QCheckBox()
        self.chk_tdos.setChecked(True)
        self.chk_tdos.toggled.connect(self._refresh_color_rows)
        self.chk_pdos = QCheckBox()
        self.chk_pdos.setChecked(False)
        self.chk_pdos.toggled.connect(self._on_pdos_toggled)
        self.chk_opdos = QCheckBox()
        self.chk_opdos.setChecked(True)
        self.chk_opdos.setEnabled(False)
        self.chk_opdos.toggled.connect(self._refresh_color_rows)
        types.addWidget(self.chk_tdos)
        types.addWidget(self.chk_pdos)
        types.addWidget(self.chk_opdos)
        types.addStretch(1)
        draw_l.addLayout(types)
        self.chk_fill = QCheckBox()
        self.chk_fill.setChecked(True)
        draw_l.addWidget(self.chk_fill)

        self.lbl_fragments = QLabel()
        self.lbl_fragments.setStyleSheet(
            "font-weight:600;color:#24445F;margin-top:4px;")
        draw_l.addWidget(self.lbl_fragments)
        self.lbl_fragments_hint = QLabel()
        self.lbl_fragments_hint.setWordWrap(True)
        self.lbl_fragments_hint.setStyleSheet(
            "font-size:12px;color:#64748B;")
        draw_l.addWidget(self.lbl_fragments_hint)

        self.list_fragments = QListWidget()
        self.list_fragments.setMinimumHeight(76)
        self.list_fragments.setMaximumHeight(150)
        draw_l.addWidget(self.list_fragments)

        add = QGridLayout()
        add.setHorizontalSpacing(6)
        self.lbl_element = QLabel()
        self.cmb_element = QComboBox()
        self.lbl_orbital = QLabel()
        self.cmb_orbital = QComboBox()
        self.btn_add = QPushButton()
        self.btn_add.clicked.connect(self._add_fragment)
        add.addWidget(self.lbl_element, 0, 0)
        add.addWidget(self.cmb_element, 0, 1)
        add.addWidget(self.lbl_orbital, 0, 2)
        add.addWidget(self.cmb_orbital, 0, 3)
        add.addWidget(self.btn_add, 0, 4)
        add.setColumnStretch(1, 1)
        add.setColumnStretch(3, 1)
        draw_l.addLayout(add)

        actions = QHBoxLayout()
        self.btn_canvas_selection = QPushButton()
        self.btn_canvas_selection.clicked.connect(self._add_canvas_selection)
        self.btn_remove = QPushButton()
        self.btn_remove.clicked.connect(self._remove_fragment)
        self.btn_up = QPushButton()
        self.btn_up.clicked.connect(lambda: self._move_fragment(-1))
        self.btn_down = QPushButton()
        self.btn_down.clicked.connect(lambda: self._move_fragment(1))
        actions.addWidget(self.btn_canvas_selection)
        actions.addWidget(self.btn_remove)
        actions.addWidget(self.btn_up)
        actions.addWidget(self.btn_down)
        actions.addStretch(1)
        draw_l.addLayout(actions)
        root.addWidget(self.grp_draw)

        self.grp_colors = QGroupBox()
        colors_l = QVBoxLayout(self.grp_colors)
        colors_l.setContentsMargins(10, 12, 10, 10)
        self._color_grid = QGridLayout()
        self._color_grid.setHorizontalSpacing(8)
        self._color_grid.setVerticalSpacing(5)
        colors_l.addLayout(self._color_grid)
        self.btn_reset_colors = QPushButton()
        self.btn_reset_colors.clicked.connect(self._reset_curve_colors)
        colors_l.addWidget(self.btn_reset_colors)
        root.addWidget(self.grp_colors)

        self.grp_advanced = QGroupBox()
        advanced_l = QVBoxLayout(self.grp_advanced)
        advanced_l.setContentsMargins(10, 12, 10, 10)
        self.btn_advanced = QPushButton()
        self.btn_advanced.setCheckable(True)
        self.btn_advanced.toggled.connect(self._toggle_advanced)
        advanced_l.addWidget(self.btn_advanced)
        self.advanced_body = QWidget()
        form = QFormLayout(self.advanced_body)
        form.setContentsMargins(0, 4, 0, 0)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)

        self.lbl_fwhm = QLabel()
        self.spin_fwhm = QDoubleSpinBox()
        self.spin_fwhm.setRange(0.00001, 1000.0)
        self.spin_fwhm.setDecimals(5)
        self.spin_fwhm.setSingleStep(0.005)
        self.spin_fwhm.setValue(0.03)
        form.addRow(self.lbl_fwhm, self.spin_fwhm)

        self.lbl_curve_scale = QLabel()
        self.spin_curve_scale = QDoubleSpinBox()
        self.spin_curve_scale.setRange(0.00001, 1000.0)
        self.spin_curve_scale.setDecimals(5)
        self.spin_curve_scale.setSingleStep(0.01)
        self.spin_curve_scale.setValue(0.05)
        form.addRow(self.lbl_curve_scale, self.spin_curve_scale)

        self.lbl_unit = QLabel()
        self.cmb_unit = QComboBox()
        self.cmb_unit.addItem("a.u.", "a.u.")
        self.cmb_unit.addItem("eV", "eV")
        self.cmb_unit.currentIndexChanged.connect(self._on_unit_changed)
        form.addRow(self.lbl_unit, self.cmb_unit)

        self.lbl_broadening = QLabel()
        self.cmb_broadening = QComboBox()
        self.cmb_broadening.addItem("", "gaussian")
        self.cmb_broadening.addItem("", "lorentzian")
        self.cmb_broadening.addItem("", "pseudo_voigt")
        form.addRow(self.lbl_broadening, self.cmb_broadening)

        self.lbl_spin = QLabel()
        self.cmb_spin = QComboBox()
        self.cmb_spin.addItem("", "all")
        self.cmb_spin.addItem("", "alpha")
        self.cmb_spin.addItem("", "beta")
        self.cmb_spin.currentIndexChanged.connect(self._refresh_color_rows)
        form.addRow(self.lbl_spin, self.cmb_spin)

        self.lbl_method = QLabel()
        self.cmb_method = QComboBox()
        self.cmb_method.addItem("", "mulliken")
        self.cmb_method.addItem("", "scpa")
        self.cmb_method.addItem("", "hirshfeld")
        self.cmb_method.addItem("", "becke")
        self.cmb_method.currentIndexChanged.connect(self._on_method_changed)
        form.addRow(self.lbl_method, self.cmb_method)

        self.chk_custom_range = QCheckBox()
        self.chk_custom_range.toggled.connect(self._update_range_controls)
        form.addRow("", self.chk_custom_range)
        range_row = QWidget()
        range_l = QHBoxLayout(range_row)
        range_l.setContentsMargins(0, 0, 0, 0)
        self.edit_lower = QLineEdit()
        self.edit_upper = QLineEdit()
        self.edit_step = QLineEdit()
        self.edit_lower.setPlaceholderText("-0.60")
        self.edit_upper.setPlaceholderText("0.11")
        self.edit_step.setPlaceholderText("0.07")
        self.lbl_lower = QLabel()
        self.lbl_upper = QLabel()
        self.lbl_step = QLabel()
        range_l.addWidget(self.lbl_lower)
        range_l.addWidget(self.edit_lower)
        range_l.addWidget(self.lbl_upper)
        range_l.addWidget(self.edit_upper)
        range_l.addWidget(self.lbl_step)
        range_l.addWidget(self.edit_step)
        form.addRow("", range_row)

        self.chk_levels = QCheckBox()
        self.chk_levels.setChecked(True)
        self.chk_centers = QCheckBox()
        self.chk_centers.setChecked(True)
        self.chk_shift = QCheckBox()
        self.chk_shift.setChecked(False)
        form.addRow("", self.chk_levels)
        form.addRow("", self.chk_centers)
        form.addRow("", self.chk_shift)
        advanced_l.addWidget(self.advanced_body)
        self.advanced_body.hide()
        root.addWidget(self.grp_advanced)

        self.grp_run = QGroupBox()
        run_l = QVBoxLayout(self.grp_run)
        run_l.setContentsMargins(10, 12, 10, 10)
        buttons = QHBoxLayout()
        self.btn_run = QPushButton()
        self.btn_run.setObjectName("PrimaryBtn")
        self.btn_run.setMinimumHeight(42)
        self.btn_run.clicked.connect(self._start)
        self.btn_stop = QPushButton()
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop)
        self.btn_open = QPushButton()
        self.btn_open.setEnabled(False)
        self.btn_open.clicked.connect(self._open_output)
        buttons.addWidget(self.btn_run, 2)
        buttons.addWidget(self.btn_stop)
        buttons.addWidget(self.btn_open)
        run_l.addLayout(buttons)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        run_l.addWidget(self.progress)
        self.lbl_status = QLabel()
        self.lbl_status.setWordWrap(True)
        run_l.addWidget(self.lbl_status)
        self.lbl_centers = QLabel()
        self.lbl_centers.setWordWrap(True)
        self.lbl_centers.setStyleSheet(
            "color:#14532D;background:#F0FDF4;border:1px solid #BBF7D0;"
            "border-radius:4px;padding:4px 7px;")
        self.lbl_centers.hide()
        run_l.addWidget(self.lbl_centers)
        root.addWidget(self.grp_run)

        self.grp_preview = QGroupBox()
        preview_l = QVBoxLayout(self.grp_preview)
        preview_l.setContentsMargins(10, 12, 10, 10)
        self.lbl_preview = AspectPixmapLabel()
        self.lbl_preview.setMinimumHeight(300)
        self.lbl_preview.setStyleSheet(
            "background:white;border:1px solid #DDE5EC;border-radius:6px;"
            "color:#64748B;")
        preview_l.addWidget(self.lbl_preview, 1)
        export_row = QHBoxLayout()
        self.btn_redraw = QPushButton()
        self.btn_redraw.setEnabled(False)
        self.btn_redraw.clicked.connect(self._redraw)
        self.btn_save_image = QPushButton()
        self.btn_save_image.setEnabled(False)
        self.btn_save_image.clicked.connect(self._save_image)
        self.btn_save_csv = QPushButton()
        self.btn_save_csv.setEnabled(False)
        self.btn_save_csv.clicked.connect(self._save_csv)
        export_row.addWidget(self.btn_redraw)
        export_row.addWidget(self.btn_save_image)
        export_row.addWidget(self.btn_save_csv)
        export_row.addStretch(1)
        preview_l.addLayout(export_row)
        for checkbox in (
                self.chk_fill, self.chk_levels,
                self.chk_centers, self.chk_shift):
            checkbox.toggled.connect(self._refresh_preview_if_ready)
        root.addStretch(1)
        splitter.addWidget(self.grp_preview)
        splitter.addWidget(controls)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        outer.addWidget(splitter, 1)
        self._update_range_controls(False)

    def showEvent(self, event):
        super().showEvent(event)
        if self._sizes_initialized:
            return
        self._sizes_initialized = True
        total = self._splitter.width()
        if total <= 0:
            return
        right_width = min(440, max(320, int(total * 0.36)))
        self._splitter.setSizes(
            [max(280, total - right_width), right_width])
        self._splitter.set_default_sizes(self._splitter.sizes())

    def _apply_lang(self):
        t = self._t
        self.lbl_title.setText(t("title"))
        for index in range(self._splitter.count()):
            self._splitter.handle(index).setToolTip(t("splitter_tip"))
        self.lbl_intro.setText(t("intro"))
        self.grp_source.setTitle(t("source"))
        self.grp_draw.setTitle(t("draw"))
        self.chk_tdos.setText(t("tdos"))
        self.chk_pdos.setText(t("pdos"))
        self.chk_opdos.setText(t("opdos"))
        self.chk_opdos.setToolTip(t("opdos_tip"))
        self.lbl_fragments.setText(t("fragments"))
        self.lbl_fragments_hint.setText(t("fragments_hint"))
        self.lbl_element.setText(t("element"))
        self.lbl_orbital.setText(t("orbital"))
        self.btn_add.setText(t("add"))
        self.btn_canvas_selection.setText(t("canvas_selection"))
        self.btn_remove.setText(t("remove"))
        self.btn_up.setText(t("up"))
        self.btn_down.setText(t("down"))
        self._refresh_orbitals()
        self.grp_colors.setTitle(t("colors"))
        self.btn_reset_colors.setText(t("reset_colors"))
        self.grp_advanced.setTitle(t("advanced"))
        self.btn_advanced.setText(
            t("advanced_hide") if self.btn_advanced.isChecked()
            else t("advanced_show"))
        self.lbl_fwhm.setText(t("fwhm"))
        self.lbl_curve_scale.setText(t("curve_scale"))
        self.lbl_unit.setText(t("unit"))
        self.lbl_broadening.setText(t("broadening"))
        self.lbl_spin.setText(t("spin"))
        self.lbl_method.setText(t("method"))
        self.chk_custom_range.setText(t("custom_range"))
        self.lbl_lower.setText(t("lower"))
        self.lbl_upper.setText(t("upper"))
        self.lbl_step.setText(t("step"))
        self.chk_levels.setText(t("levels"))
        self.chk_fill.setText(t("fill_curves"))
        self.chk_centers.setText(t("centers"))
        self.chk_centers.setToolTip(t("centers_tip"))
        self.chk_shift.setText(t("shift"))
        self.cmb_broadening.setItemText(0, t("gaussian"))
        self.cmb_broadening.setItemText(1, t("lorentzian"))
        self.cmb_broadening.setItemText(2, t("pseudo"))
        self.cmb_spin.setItemText(0, t("all_spins"))
        self.cmb_spin.setItemText(1, t("alpha"))
        self.cmb_spin.setItemText(2, t("beta"))
        self.cmb_method.setItemText(0, t("mulliken"))
        self.cmb_method.setItemText(1, t("scpa"))
        self.cmb_method.setItemText(2, t("hirshfeld"))
        self.cmb_method.setItemText(3, t("becke"))
        self.grp_run.setTitle(t("run_group"))
        self.btn_run.setText(t("run"))
        self.btn_stop.setText(t("stop"))
        self.btn_open.setText(t("open"))
        self.grp_preview.setTitle(t("preview"))
        self.btn_redraw.setText(t("redraw"))
        self.btn_save_image.setText(t("save_image"))
        self.btn_save_csv.setText(t("save_csv"))
        if not self._last_result:
            self.lbl_preview.setText(t("preview_empty"))
        self._refresh_source()
        self._refresh_fragments()
        self._refresh_color_rows()
        self._on_method_changed()

    def set_lang(self, lang):
        self._lang = "en" if lang == "en" else "zh"
        self._apply_lang()

    def _refresh_orbitals(self):
        current = self.cmb_orbital.currentData() or "all"
        self.cmb_orbital.blockSignals(True)
        self.cmb_orbital.clear()
        options = (
            ("all", "orbital_all"), ("s", "orbital_s"),
            ("p", "orbital_p"), ("d", "orbital_d"),
            ("pz", "orbital_pz"), ("px", "orbital_px"),
            ("py", "orbital_py"), ("s,px,py", "orbital_sxyz"),
        )
        for value, key in options:
            self.cmb_orbital.addItem(self._t(key), value)
        index = self.cmb_orbital.findData(current)
        self.cmb_orbital.setCurrentIndex(max(0, index))
        self.cmb_orbital.blockSignals(False)

    def _curve_specs(self):
        keys = []
        fragments = list(self._fragments)
        mirrored = (
            self._is_open_shell
            and self.cmb_spin.currentData() == "all")
        if not self.chk_pdos.isChecked() or not fragments:
            if self.chk_tdos.isChecked():
                keys.append("TDOS")
            return keys
        if mirrored:
            if self.chk_tdos.isChecked():
                keys.append("α TDOS")
            keys.extend("α " + fragment.name for fragment in fragments)
            if self.chk_tdos.isChecked():
                keys.append("β TDOS")
            keys.extend("β " + fragment.name for fragment in fragments)
        else:
            if self.chk_tdos.isChecked():
                keys.append("TDOS")
            keys.extend(fragment.name for fragment in fragments)
            if self.chk_opdos.isChecked() and len(fragments) >= 2:
                keys.append("OPDOS")
        return keys

    def _default_curve_color(self, key, index=0):
        regular = [
            "#d62728", "#2146f3", "#cf2bc9", "#f28e2b",
            "#9467bd", "#17becf", "#8c564b", "#bcbd22",
        ]
        alpha = ["#d62728", "#8e44ad", "#d68910", "#17a589"]
        beta = ["#2146f3", "#7d3c98", "#e67e22", "#16a085"]
        if key in ("TDOS", "α TDOS"):
            return "#171717"
        if key in ("OPDOS", "β TDOS"):
            return "#18a84b"
        names = [fragment.name for fragment in self._fragments]
        if key.startswith("α "):
            name = key[2:]
            position = names.index(name) if name in names else 0
            return alpha[position % len(alpha)]
        if key.startswith("β "):
            name = key[2:]
            position = names.index(name) if name in names else 0
            return beta[position % len(beta)]
        position = names.index(key) if key in names else 0
        return regular[position % len(regular)]

    def _set_color_button_style(self, button, color):
        qcolor = QColor(color)
        foreground = "#FFFFFF" if qcolor.lightness() < 135 else "#111111"
        button.setText(color.upper())
        button.setStyleSheet(
            "QPushButton{background:%s;color:%s;border:1px solid #94A3B8;"
            "border-radius:4px;padding:3px 7px;font-weight:600;}"
            % (color, foreground))

    def _choose_curve_color(self, key):
        current = QColor(
            self._curve_colors.get(key, self._default_curve_color(key, 0)))
        color = QColorDialog.getColor(current, self, self._t("colors"))
        if not color.isValid():
            return
        value = color.name()
        self._curve_colors[key] = value
        button = self._color_buttons.get(key)
        if button is not None:
            self._set_color_button_style(button, value)
        self._refresh_preview_if_ready()

    def _reset_curve_colors(self):
        self._curve_colors.clear()
        self._refresh_color_rows()
        self._refresh_preview_if_ready()

    def _refresh_color_rows(self, *_args):
        grid = getattr(self, "_color_grid", None)
        if grid is None:
            return
        while grid.count():
            item = grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._color_buttons = {}
        specs = self._curve_specs()
        for index, key in enumerate(specs):
            if key not in self._curve_colors:
                self._curve_colors[key] = self._default_curve_color(key, index)
            label = QLabel(key)
            label.setStyleSheet("color:#334155;")
            button = QPushButton()
            button.setMinimumWidth(92)
            button.clicked.connect(
                lambda _checked=False, color_key=key:
                self._choose_curve_color(color_key))
            self._set_color_button_style(button, self._curve_colors[key])
            self._color_buttons[key] = button
            grid.addWidget(label, index, 0)
            grid.addWidget(button, index, 1)
        grid.setColumnStretch(0, 1)

    def _refresh_source(self):
        if not self._source_path:
            self.lbl_source.setText(self._t("source_none"))
            self.lbl_status.setText(self._t("need_source"))
            return
        shell = self._t("open") if self._is_open_shell else self._t("closed")
        self.lbl_source.setText(self._t("source_ready").format(
            name=os.path.basename(self._source_path),
            atoms=len(self._atoms), shell=shell))
        self.lbl_status.setText(self._t("ready"))

    def set_source_from_main(self, path):
        """Synchronise the panel when the main input changes."""
        path = str(path or "").strip()
        if not path:
            self._source_path = ""
            self._atoms = []
            self._element_indices = {}
            self._fragments = []
            self._refresh_elements()
            self._refresh_fragments()
            self._refresh_source()
            return
        try:
            path = validate_dos_source(path)
        except Exception:
            self._source_path = ""
            self._atoms = []
            self._element_indices = {}
            self._fragments = []
            self._refresh_elements()
            self._refresh_fragments()
            self._refresh_source()
            return
        changed = os.path.normcase(path) != os.path.normcase(self._source_path)
        self._source_path = path
        try:
            self._atoms = (get_atoms_from_fchk(path)
                           if path.lower().endswith((".fch", ".fchk"))
                           else get_atoms_from_any(path))
        except Exception:
            self._atoms = []
        self._element_indices = {}
        for atom in self._atoms:
            symbol = self._element_symbol(atom)
            try:
                index = int(atom[0])
            except (IndexError, TypeError, ValueError):
                continue
            self._element_indices.setdefault(symbol, []).append(index)
        if changed:
            self._fragments = []
        self._is_open_shell = detect_open_shell(path)
        self._refresh_elements()
        self._refresh_fragments()
        self._refresh_source()
        if self.chk_custom_range.isChecked():
            self.edit_lower.clear()
            self.edit_upper.clear()
            self.edit_step.clear()
            self._update_range_controls(True)

    def _refresh_elements(self):
        current = self.cmb_element.currentData()
        self.cmb_element.clear()
        for symbol in self._element_indices:
            self.cmb_element.addItem(symbol, symbol)
        index = self.cmb_element.findData(current)
        if index >= 0:
            self.cmb_element.setCurrentIndex(index)

    @staticmethod
    def _collapse_indices(indices):
        values = sorted(set(int(value) for value in indices))
        if not values:
            return ""
        parts = []
        start = previous = values[0]
        for value in values[1:]:
            if value == previous + 1:
                previous = value
                continue
            parts.append(str(start) if start == previous
                         else "%d-%d" % (start, previous))
            start = previous = value
        parts.append(str(start) if start == previous
                     else "%d-%d" % (start, previous))
        return ",".join(parts)

    def _fragment_name(self, element, orbital):
        if orbital == "all":
            return element
        if element == "C":
            element = "Carbon"
        elif element == "H":
            element = "Hydrogen"
        else:
            element = ELEMENT_NAMES.get(element, element)
        pretty = {
            "pz": "Pz", "px": "Px", "py": "Py", "s": "S",
            "p": "P", "d": "D", "s,px,py": "S,Px,Py",
        }.get(orbital, orbital)
        return "%s %s" % (element, pretty)

    def _add_fragment(self):
        if len(self._fragments) >= 10:
            QMessageBox.warning(self, self._t("warning"), self._t("max"))
            return
        element = self.cmb_element.currentData()
        if not element or element not in self._element_indices:
            QMessageBox.warning(self, self._t("warning"), self._t("need_source"))
            return
        atoms = self._collapse_indices(self._element_indices[element])
        orbital = self.cmb_orbital.currentData() or "all"
        method = self.cmb_method.currentData()
        if method in ("hirshfeld", "becke") and orbital != "all":
            QMessageBox.warning(self, self._t("warning"), self._t("basis_only"))
            return
        fragment = DOSFragment(
            name=self._fragment_name(element, orbital),
            atoms=atoms,
            scope="atoms" if orbital == "all" else "atom_basis",
            angular_momentum="" if orbital == "all" else orbital)
        self._fragments.append(fragment)
        self.chk_pdos.setChecked(True)
        self._refresh_fragments()

    def _add_canvas_selection(self):
        try:
            indices = sorted(set(int(value) for value in
                                 (self._get_selected_atoms() or [])))
        except Exception:
            indices = []
        if not indices:
            QMessageBox.warning(
                self, self._t("warning"), self._t("need_selection"))
            return
        if len(self._fragments) >= 10:
            QMessageBox.warning(self, self._t("warning"), self._t("max"))
            return
        orbital = self.cmb_orbital.currentData() or "all"
        name = self._t("selection_name")
        if orbital != "all":
            name += " " + self.cmb_orbital.currentText()
        fragment = DOSFragment(
            name=name, atoms=self._collapse_indices(indices),
            scope="atoms" if orbital == "all" else "atom_basis",
            angular_momentum="" if orbital == "all" else orbital)
        self._fragments.append(fragment)
        self.chk_pdos.setChecked(True)
        self._refresh_fragments()

    def _remove_fragment(self):
        row = self.list_fragments.currentRow()
        if 0 <= row < len(self._fragments):
            del self._fragments[row]
            self._refresh_fragments()

    def _move_fragment(self, delta):
        row = self.list_fragments.currentRow()
        target = row + delta
        if row < 0 or target < 0 or target >= len(self._fragments):
            return
        self._fragments[row], self._fragments[target] = (
            self._fragments[target], self._fragments[row])
        self._refresh_fragments()
        self.list_fragments.setCurrentRow(target)

    def _refresh_fragments(self):
        current = self.list_fragments.currentRow()
        self.list_fragments.clear()
        for index, fragment in enumerate(self._fragments):
            orbital = (" · " + fragment.angular_momentum.upper()
                       if fragment.angular_momentum else "")
            item = QListWidgetItem(
                "%d.  %s%s  [%s]" % (
                    index + 1, fragment.name, orbital, fragment.atoms))
            item.setForeground(QColor(COLORS[index % len(COLORS)]))
            self.list_fragments.addItem(item)
        if self._fragments:
            self.list_fragments.setCurrentRow(
                max(0, min(current, len(self._fragments) - 1)))
        else:
            self.chk_pdos.setChecked(False)
        method = self.cmb_method.currentData()
        opdos_ok = method in ("mulliken", "scpa") and len(self._fragments) >= 2
        self.chk_opdos.setEnabled(opdos_ok)
        if not opdos_ok:
            self.chk_opdos.setChecked(False)
        elif len(self._fragments) >= 2:
            self.chk_opdos.setChecked(True)
        self.list_fragments.setToolTip(
            self._t("count").format(n=len(self._fragments))
            if self._fragments else self._t("empty"))
        self._refresh_color_rows()

    def _on_pdos_toggled(self, checked):
        if not checked:
            self.chk_opdos.setChecked(False)
        elif len(self._fragments) >= 2:
            self.chk_opdos.setChecked(True)
        self._refresh_color_rows()

    def _on_method_changed(self, *_args):
        atom_only = self.cmb_method.currentData() in ("hirshfeld", "becke")
        model = self.cmb_orbital.model()
        for index in range(1, self.cmb_orbital.count()):
            item = model.item(index)
            if item is not None:
                item.setEnabled(not atom_only)
        if atom_only and self.cmb_orbital.currentIndex() != 0:
            self.cmb_orbital.setCurrentIndex(0)
        self._refresh_fragments()

    def _toggle_advanced(self, checked):
        self.advanced_body.setVisible(bool(checked))
        self.btn_advanced.setText(
            self._t("advanced_hide") if checked else self._t("advanced_show"))

    def _update_range_controls(self, checked):
        enabled = bool(checked)
        for widget in (self.edit_lower, self.edit_upper, self.edit_step):
            widget.setEnabled(enabled)
        if enabled and self._source_path:
            try:
                lower, upper, step = suggest_dos_range(
                    self._source_path, unit=self._unit)
            except Exception:
                return
            if not self.edit_lower.text().strip():
                self.edit_lower.setText("%.3f" % lower)
            if not self.edit_upper.text().strip():
                self.edit_upper.setText("%.3f" % upper)
            if not self.edit_step.text().strip():
                self.edit_step.setText("%.3f" % step)

    def _on_unit_changed(self, *_args):
        new_unit = normalize_unit(self.cmb_unit.currentData())
        if new_unit != self._unit:
            value = self.spin_fwhm.value()
            scale = self.spin_curve_scale.value()
            if self._unit == "a.u." and new_unit == "eV":
                value *= 27.211386245988
                scale *= 27.211386245988
            elif self._unit == "eV" and new_unit == "a.u.":
                value /= 27.211386245988
                scale /= 27.211386245988
            self.spin_fwhm.blockSignals(True)
            self.spin_fwhm.setValue(value)
            self.spin_fwhm.blockSignals(False)
            self.spin_curve_scale.blockSignals(True)
            self.spin_curve_scale.setValue(scale)
            self.spin_curve_scale.blockSignals(False)
            self._unit = new_unit
        self.spin_fwhm.setSuffix(" " + new_unit)

    def _parse_range(self):
        if not self.chk_custom_range.isChecked():
            return None, None, None
        try:
            lower = float(self.edit_lower.text().strip())
            upper = float(self.edit_upper.text().strip())
            step = float(self.edit_step.text().strip())
        except ValueError:
            raise DOSWorkflowError(self._t("warning"))
        if lower >= upper or step <= 0:
            raise DOSWorkflowError(self._t("warning"))
        return lower, upper, step

    def _start(self):
        if self._worker is not None and self._worker.isRunning():
            return
        if not self.chk_tdos.isChecked() and not self.chk_pdos.isChecked():
            QMessageBox.warning(
                self, self._t("warning"), self._t("need_content"))
            return
        if self.chk_pdos.isChecked() and not self._fragments:
            QMessageBox.warning(
                self, self._t("warning"), self._t("need_fragments"))
            return
        try:
            source = validate_dos_source(
                self._source_path, self._fragments
                if self.chk_pdos.isChecked() else [])
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, self._t("warning"), str(exc))
            return
        multiwfn = str(self._get_multiwfn() or "").strip()
        if not multiwfn or not os.path.isfile(multiwfn):
            QMessageBox.warning(self, self._t("warning"), self._t("need_mw"))
            return
        try:
            emin, emax, step = self._parse_range()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, self._t("warning"), str(exc))
            return
        fragments = list(self._fragments) if self.chk_pdos.isChecked() else []
        kwargs = {
            "source_path": source,
            "output_parent": os.path.dirname(source),
            "multiwfn_exe": multiwfn,
            "fwhm": self.spin_fwhm.value(),
            "curve_scale": self.spin_curve_scale.value(),
            "unit": normalize_unit(self.cmb_unit.currentData()),
            "broadening": self.cmb_broadening.currentData(),
            "spin": self.cmb_spin.currentData(),
            "fragments": fragments,
            "method": self.cmb_method.currentData(),
            "emin": emin, "emax": emax, "step": step,
            "show_levels": self.chk_levels.isChecked(),
            "show_centers": self.chk_centers.isChecked(),
            "fill_curves": self.chk_fill.isChecked(),
            "show_tdos": self.chk_tdos.isChecked(),
            "show_pdos": self.chk_pdos.isChecked(),
            "show_opdos": self.chk_opdos.isChecked(),
            "curve_colors": dict(self._curve_colors),
            "show_title": False,
            "flat_output": True,
        }
        self._worker = DOSWorker(kwargs, self)
        self._worker.stage.connect(self._on_stage)
        self._worker.log.connect(self._log_func)
        self._worker.completed.connect(self._on_completed)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_finished)
        self._set_running(True)
        self.progress.setValue(0)
        self.lbl_status.setText(self._t("working"))
        self._worker.start()

    def _set_running(self, running):
        for widget in (
                self.btn_run, self.btn_add, self.btn_canvas_selection,
                self.btn_remove, self.btn_up, self.btn_down,
                self.grp_draw, self.grp_advanced):
            widget.setEnabled(not running)
        self.btn_stop.setEnabled(running)

    def _stop(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.stop()
            self.lbl_status.setText(self._t("cancel"))

    def _on_stage(self, pct, text):
        self.progress.setValue(max(0, min(100, int(pct))))
        self.lbl_status.setText(text)

    def _on_completed(self, result):
        self._last_result = result
        self._redraw()
        self.progress.setValue(100)
        self.lbl_status.setText(
            "%s\n%s" % (
                self._t("done"),
                self._t("out").format(path=result.output_dir)))
        self.btn_open.setEnabled(True)
        self.btn_redraw.setEnabled(True)
        self.btn_save_image.setEnabled(True)
        self.btn_save_csv.setEnabled(True)
        if result.d_band_centers:
            rows = []
            for center in result.d_band_centers:
                spin = center.get("spin")
                prefix = (
                    ("α " if spin == "alpha" else "β ")
                    if spin in ("alpha", "beta") else "")
                center_text = "%.4f %s" % (
                    center["center"], result.unit)
                relative = center.get("relative")
                if relative is not None:
                    center_text += "  →  %.4f %s" % (
                        relative, result.unit)
                rows.append("%s%s: %s" % (
                    prefix, center["name"], center_text))
            self.lbl_centers.setText(
                self._t("center_values") + "\n" + "\n".join(rows))
            self.lbl_centers.show()
        else:
            self.lbl_centers.hide()
        self._log_func("[DOS] %s" % result.plot_path)

    def _on_failed(self, message):
        self.progress.setValue(0)
        self.lbl_status.setText(self._t("failed"))
        QMessageBox.warning(self, self._t("failed"), message)
        self._log_func("[DOS] %s" % message)

    def _on_finished(self):
        self._set_running(False)
        self._worker = None

    def _plot_options(self):
        return {
            "shift_homo": self.chk_shift.isChecked(),
            "show_levels": self.chk_levels.isChecked(),
            "show_centers": self.chk_centers.isChecked(),
            "show_title": False,
        }

    def _refresh_preview_if_ready(self, *_args):
        if self._last_result is not None:
            self._redraw()

    def _redraw(self):
        if self._last_result is None:
            return
        try:
            self._last_result.fill_curves = self.chk_fill.isChecked()
            self._last_result.curve_colors = dict(self._curve_colors)
            render_saved_dos(
                self._last_result, self._last_result.plot_path,
                **self._plot_options())
            pix = QPixmap(self._last_result.plot_path)
            if not pix.isNull():
                self.lbl_preview.set_source_pixmap(pix)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, self._t("failed"), str(exc))

    def _save_image(self):
        if self._last_result is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, self._t("save_image"), self._last_result.plot_path,
            self._t("image_filter"))
        if not path:
            return
        try:
            self._last_result.fill_curves = self.chk_fill.isChecked()
            self._last_result.curve_colors = dict(self._curve_colors)
            render_saved_dos(
                self._last_result, path, **self._plot_options())
            self._log_func("[DOS] 图片已保存：%s" % path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, self._t("failed"), str(exc))

    def _save_csv(self):
        if self._last_result is None:
            return
        stem = os.path.splitext(os.path.basename(self._last_result.plot_path))[0]
        path, _ = QFileDialog.getSaveFileName(
            self, self._t("save_csv"),
            os.path.join(self._last_result.output_dir, stem + ".csv"),
            self._t("csv_filter"))
        if not path:
            return
        try:
            export_dos_csv(
                self._last_result, path,
                shift_homo=self.chk_shift.isChecked())
            self._log_func("[DOS] CSV 已保存：%s" % path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, self._t("failed"), str(exc))

    def _open_output(self):
        path = (self._last_result.output_dir if self._last_result
                else os.path.dirname(self._source_path))
        if path and os.path.isdir(path):
            os.startfile(path)

    def shutdown(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(5000)


__all__ = ["DOSPanel", "DOSWorker"]
