# -*- coding: utf-8 -*-
"""Electron-density difference panel for MolStudio."""

from __future__ import annotations

import os
import tempfile

from PyQt5.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QDoubleValidator
from PyQt5.QtWidgets import (
    QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QFileDialog,
    QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QProgressBar,
    QPushButton, QSlider, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from molstudio.core.edd import (
    EDDCancelled,
    EDDFragment,
    EDDWorkflowError,
    generate_difference_cube,
    parse_atom_indices,
    prepare_fragment_jobs,
    read_charge_multiplicity,
    run_fragment_jobs,
)
from molstudio.core.gaussian_run import find_formchk, find_gaussian
from molstudio.panels.etsnocv.fchk_parser import get_atoms_from_fchk


TEXT = {
    "zh": {
        "title": "电子密度差 · EDD",
        "intro": (
            "电子密度差 = 当前体系密度 − 各参考片段/状态密度。"
            "母体与所有片段必须在同一理论水平下计算，"
            "保持母体坐标并强制 nosymm。"
            "<a href=\"http://sobereva.com/113\">查看 Sob EDD 教程</a>"
        ),
        "source": "1  母体波函数",
        "source_path": "波函数",
        "browse": "浏览…",
        "use_current": "使用当前文件",
        "source_none": "请先在主界面载入母体 .fch/.fchk。",
        "source_loaded": "{name}  |  {n} 原子",
        "fragments": "2  片段与输入文件",
        "fragments_hint": (
            "在主画布框选/点选原子，或直接输入原子序号。"
            "片段必须互不重叠，生成任务时默认要求覆盖全部原子。"),
        "atom_ids": "原子序号",
        "selection": "用画布选中原子",
        "selection_empty": "请先在左侧画布选择原子。",
        "add_fragment": "添加片段",
        "auto_complete": "自动补齐剩余原子",
        "remove_fragment": "删除片段",
        "col_name": "片段",
        "col_atoms": "原子序号",
        "col_charge": "电荷",
        "col_mult": "多重度",
        "parent_charge": "母体电荷",
        "parent_mult": "母体多重度",
        "method": "方法 / 基组",
        "nproc": "核数",
        "mem": "内存",
        "generate": "生成母体 + 片段输入",
        "run_fragments": "计算母体与全部片段",
        "fragment_empty": "尚未定义片段",
        "references": "3  参考波函数（依次减去）",
        "refs_hint": (
            "手工载入多个 .fch/.fchk，或由上面的片段任务生成。"
            "母体始终作为被减数。"),
        "add_refs": "添加结果文件…",
        "remove_ref": "移除选中",
        "clear_refs": "清空",
        "analysis": "4  计算密度差",
        "grid": "格点精度",
        "run": "生成密度差并显示",
        "stop": "停止",
        "open": "打开输出目录",
        "ready": "就绪：载入母体，定义片段或参考波函数。",
        "working": "电子密度差计算中…",
        "done": "密度差 cube 已生成并显示到画布",
        "failed": "电子密度差计算失败",
        "cancel": "正在停止…",
        "visual": "5  等值面显示",
        "iso": "等值面",
        "opacity": "不透明度",
        "pos": "密度增加",
        "neg": "密度减少",
        "refresh": "应用到画布",
        "warning": "提示",
        "need_source": "请先选择母体 fch/fchk。",
        "need_mw": "请先在主窗口路径设置中配置 Multiwfn。",
        "need_g16": "请先在主窗口路径设置中配置 Gaussian。",
        "need_refs": "请至少添加一个参考波函数。",
        "no_atoms": "母体文件中没有原子信息。",
        "invalid_id": "原子序号格式无效。",
        "overlap": "原子 {atoms} 已在其他片段中。",
        "complete": "片段已覆盖全部原子。",
        "missing": "仍有未分配原子：{atoms}",
        "fragment_added": "已添加片段 {name}：{atoms}",
        "inputs_done": "已生成母体和 {n} 个片段输入文件。",
        "refs_count": "参考波函数：{n} 个",
        "stats": "参考数 {n}  |  格点 {points}  |  Δρ(min/max) = {lo:.3e} / {hi:.3e}",
        "out": "输出：{path}",
        "cube_saved": "Cube：{path}",
        "status_frag": "[{done}/{total}] {label}",
        "fill": "正负相位颜色",
        "auto_run": "片段任务完成后自动计算密度差",
        "dialog_refs": "选择参考波函数",
        "filter_wave": "格式化 Checkpoint (*.fchk *.fch);;所有文件 (*.*)",
    },
    "en": {
        "title": "Electron density difference · EDD",
        "intro": (
            "EDD = density(current system) − sum(density(references)). "
            "Parent and fragments must use the same theoretical level, "
            "preserve coordinates and force nosymm. "
            "<a href=\"http://sobereva.com/113\">Open the Sob EDD tutorial</a>"
        ),
        "source": "1  Parent wavefunction",
        "source_path": "Wavefunction",
        "browse": "Browse…",
        "use_current": "Use current file",
        "source_none": "Load the parent .fch/.fchk in the main window first.",
        "source_loaded": "{name}  |  {n} atoms",
        "fragments": "2  Fragments and input jobs",
        "fragments_hint": (
            "Select atoms on the main canvas or enter their indices. "
            "Fragments must be disjoint and normally cover every atom."),
        "atom_ids": "Atom indices",
        "selection": "Use canvas selection",
        "selection_empty": "Select atoms on the left canvas first.",
        "add_fragment": "Add fragment",
        "auto_complete": "Assign remaining atoms",
        "remove_fragment": "Remove fragment",
        "col_name": "Fragment",
        "col_atoms": "Atoms",
        "col_charge": "Charge",
        "col_mult": "Mult.",
        "parent_charge": "Parent charge",
        "parent_mult": "Parent mult.",
        "method": "Method / basis",
        "nproc": "Cores",
        "mem": "Memory",
        "generate": "Generate parent + fragment inputs",
        "run_fragments": "Calculate parent and all fragments",
        "fragment_empty": "No fragments defined",
        "references": "3  Reference wavefunctions (subtracted)",
        "refs_hint": (
            "Load one or more .fch/.fchk files manually, or create them with "
            "the fragment workflow. The parent is always the minuend."),
        "add_refs": "Add result files…",
        "remove_ref": "Remove selected",
        "clear_refs": "Clear",
        "analysis": "4  Difference calculation",
        "grid": "Grid quality",
        "run": "Generate difference and display",
        "stop": "Stop",
        "open": "Open output folder",
        "ready": "Ready: load a parent and define fragments or references.",
        "working": "Calculating electron density difference…",
        "done": "Difference cube generated and shown on the canvas",
        "failed": "Electron density difference failed",
        "cancel": "Stopping…",
        "visual": "5  Isosurface display",
        "iso": "Isosurface",
        "opacity": "Opacity",
        "pos": "Density increase",
        "neg": "Density decrease",
        "refresh": "Apply to canvas",
        "warning": "Notice",
        "need_source": "Select a parent fch/fchk first.",
        "need_mw": "Configure Multiwfn in the main-window Path Settings.",
        "need_g16": "Configure Gaussian in the main-window Path Settings.",
        "need_refs": "Add at least one reference wavefunction.",
        "no_atoms": "No atoms were found in the parent file.",
        "invalid_id": "Invalid atom index syntax.",
        "overlap": "Atom {atoms} already belongs to another fragment.",
        "complete": "Fragments cover every atom.",
        "missing": "Unassigned atoms remain: {atoms}",
        "fragment_added": "Added fragment {name}: {atoms}",
        "inputs_done": "Generated parent and {n} fragment input files.",
        "refs_count": "Reference wavefunctions: {n}",
        "stats": "References {n}  |  points {points}  |  Δρ(min/max) = {lo:.3e} / {hi:.3e}",
        "out": "Output: {path}",
        "cube_saved": "Cube: {path}",
        "status_frag": "[{done}/{total}] {label}",
        "fill": "Positive / negative colors",
        "auto_run": "Run EDD automatically after fragment jobs",
        "dialog_refs": "Select reference wavefunctions",
        "filter_wave": "Formatted checkpoint (*.fchk *.fch);;All files (*.*)",
    },
}


class FragmentJobsWorker(QThread):
    log = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, jobs, gaussian_exe, parent=None):
        super().__init__(parent)
        self.jobs = jobs
        self.gaussian_exe = gaussian_exe
        self._cancel = False

    def stop(self):
        self._cancel = True

    def run(self):
        try:
            result = run_fragment_jobs(
                self.jobs, self.gaussian_exe,
                formchk_exe=find_formchk(self.gaussian_exe),
                on_log=self.log.emit,
                on_progress=lambda done, total, label:
                self.progress.emit(done, total, label),
                cancel=lambda: self._cancel)
            self.completed.emit(result)
        except EDDCancelled as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class DifferenceWorker(QThread):
    log = pyqtSignal(str)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, kwargs, parent=None):
        super().__init__(parent)
        self.kwargs = kwargs
        self._cancel = False

    def stop(self):
        self._cancel = True

    def run(self):
        try:
            result = generate_difference_cube(
                on_log=self.log.emit, cancel=lambda: self._cancel,
                **self.kwargs)
            self.completed.emit(result)
        except EDDCancelled as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class EDDPanel(QWidget):
    """Parent-minus-references density difference workflow."""

    def __init__(self, glw=None, get_fchk=None, get_multiwfn=None,
                 get_g16=None, get_selected_atoms=None, log_func=None,
                 parent=None):
        super().__init__(parent)
        self.lang = "zh"
        self.glw = glw
        self._get_fchk = get_fchk or (lambda: "")
        self._get_multiwfn = get_multiwfn or (lambda: "")
        self._get_g16 = get_g16 or (lambda: "")
        self._get_selected_atoms = get_selected_atoms or (lambda: [])
        self._log_func = log_func or (lambda _message: None)
        self._complex_path = ""
        self._atoms = []
        self._jobs = []
        self._archive_dir = ""
        self._last_result = None
        self._fragment_worker = None
        self._difference_worker = None
        self._iso = 0.001
        self._opacity = 0.75
        self._pos_rgb = (52, 112, 235)
        self._neg_rgb = (225, 67, 67)
        self._build_ui()
        self._apply_lang()
        self.set_complex_from_main(self._get_fchk())

    def _t(self, key, **fmt):
        text = TEXT[self.lang].get(key, key)
        return text.format(**fmt) if fmt else text

    def set_lang(self, lang):
        self.lang = "en" if lang == "en" else "zh"
        self._apply_lang()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)
        self.lbl_title = QLabel()
        self.lbl_title.setStyleSheet(
            "font-size:18px;font-weight:700;color:#0D47A1;")
        root.addWidget(self.lbl_title)
        self.lbl_intro = QLabel()
        self.lbl_intro.setOpenExternalLinks(True)
        self.lbl_intro.setWordWrap(True)
        root.addWidget(self.lbl_intro)

        self.grp_source = QGroupBox()
        source_l = QGridLayout(self.grp_source)
        self.lbl_source_path = QLabel()
        self.edit_complex = QLineEdit()
        self.edit_complex.setReadOnly(True)
        self.btn_browse_complex = QPushButton()
        self.btn_browse_complex.clicked.connect(self._browse_complex)
        self.btn_current = QPushButton()
        self.btn_current.clicked.connect(
            lambda: self.set_complex_from_main(self._get_fchk()))
        source_l.addWidget(self.lbl_source_path, 0, 0)
        source_l.addWidget(self.edit_complex, 0, 1)
        source_l.addWidget(self.btn_browse_complex, 0, 2)
        source_l.addWidget(self.btn_current, 0, 3)
        self.lbl_source = QLabel()
        self.lbl_source.setWordWrap(True)
        source_l.addWidget(self.lbl_source, 1, 1, 1, 3)
        root.addWidget(self.grp_source)

        self.grp_fragments = QGroupBox()
        frag_l = QVBoxLayout(self.grp_fragments)
        self.lbl_fragments_hint = QLabel()
        self.lbl_fragments_hint.setWordWrap(True)
        frag_l.addWidget(self.lbl_fragments_hint)
        self.table_fragments = QTableWidget(0, 4)
        self.table_fragments.setEditTriggers(
            QAbstractItemView.DoubleClicked |
            QAbstractItemView.EditKeyPressed)
        self.table_fragments.setSelectionBehavior(
            QAbstractItemView.SelectRows)
        self.table_fragments.verticalHeader().setVisible(False)
        self.table_fragments.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        self.table_fragments.setMinimumHeight(130)
        frag_l.addWidget(self.table_fragments)
        add_row = QHBoxLayout()
        self.lbl_atom_ids = QLabel()
        self.edit_fragment_atoms = QLineEdit()
        self.btn_canvas_selection = QPushButton()
        self.btn_canvas_selection.clicked.connect(
            self._fill_from_canvas_selection)
        self.spin_fragment_charge = QSpinBox()
        self.spin_fragment_charge.setRange(-20, 20)
        self.spin_fragment_mult = QSpinBox()
        self.spin_fragment_mult.setRange(1, 12)
        self.btn_add_fragment = QPushButton()
        self.btn_add_fragment.clicked.connect(self._add_fragment)
        add_row.addWidget(self.lbl_atom_ids)
        add_row.addWidget(self.edit_fragment_atoms, 1)
        add_row.addWidget(self.btn_canvas_selection)
        add_row.addWidget(QLabel("q"))
        add_row.addWidget(self.spin_fragment_charge)
        add_row.addWidget(QLabel("2S+1"))
        add_row.addWidget(self.spin_fragment_mult)
        add_row.addWidget(self.btn_add_fragment)
        frag_l.addLayout(add_row)
        fragment_actions = QHBoxLayout()
        self.btn_auto_complete = QPushButton()
        self.btn_auto_complete.clicked.connect(self._auto_complete)
        self.btn_remove_fragment = QPushButton()
        self.btn_remove_fragment.clicked.connect(self._remove_fragment)
        fragment_actions.addWidget(self.btn_auto_complete)
        fragment_actions.addWidget(self.btn_remove_fragment)
        fragment_actions.addStretch(1)
        frag_l.addLayout(fragment_actions)

        calc = QGridLayout()
        self.lbl_method = QLabel()
        self.edit_method = QLineEdit("B3LYP/6-311G(d,p)")
        self.lbl_nproc = QLabel()
        self.spin_nproc = QSpinBox()
        self.spin_nproc.setRange(1, 256)
        self.spin_nproc.setValue(8)
        self.lbl_mem = QLabel()
        self.edit_mem = QLineEdit("8GB")
        self.lbl_parent_charge = QLabel()
        self.spin_parent_charge = QSpinBox()
        self.spin_parent_charge.setRange(-20, 20)
        self.lbl_parent_mult = QLabel()
        self.spin_parent_mult = QSpinBox()
        self.spin_parent_mult.setRange(1, 12)
        calc.addWidget(self.lbl_method, 0, 0)
        calc.addWidget(self.edit_method, 0, 1, 1, 3)
        calc.addWidget(self.lbl_nproc, 1, 0)
        calc.addWidget(self.spin_nproc, 1, 1)
        calc.addWidget(self.lbl_mem, 1, 2)
        calc.addWidget(self.edit_mem, 1, 3)
        calc.addWidget(self.lbl_parent_charge, 2, 0)
        calc.addWidget(self.spin_parent_charge, 2, 1)
        calc.addWidget(self.lbl_parent_mult, 2, 2)
        calc.addWidget(self.spin_parent_mult, 2, 3)
        frag_l.addLayout(calc)
        self.btn_generate = QPushButton()
        self.btn_generate.clicked.connect(self._generate_fragment_inputs)
        self.btn_run_fragments = QPushButton()
        self.btn_run_fragments.setObjectName("PrimaryBtn")
        self.btn_run_fragments.clicked.connect(self._run_fragment_jobs)
        action = QHBoxLayout()
        action.addWidget(self.btn_generate)
        action.addWidget(self.btn_run_fragments, 1)
        frag_l.addLayout(action)
        root.addWidget(self.grp_fragments)

        self.grp_refs = QGroupBox()
        refs_l = QVBoxLayout(self.grp_refs)
        self.lbl_refs_hint = QLabel()
        self.lbl_refs_hint.setWordWrap(True)
        refs_l.addWidget(self.lbl_refs_hint)
        self.list_refs = QListWidget()
        self.list_refs.setMinimumHeight(90)
        refs_l.addWidget(self.list_refs)
        refs_actions = QHBoxLayout()
        self.btn_add_refs = QPushButton()
        self.btn_add_refs.clicked.connect(self._add_reference_files)
        self.btn_remove_ref = QPushButton()
        self.btn_remove_ref.clicked.connect(self._remove_reference)
        self.btn_clear_refs = QPushButton()
        self.btn_clear_refs.clicked.connect(self.list_refs.clear)
        refs_actions.addWidget(self.btn_add_refs)
        refs_actions.addWidget(self.btn_remove_ref)
        refs_actions.addWidget(self.btn_clear_refs)
        refs_actions.addStretch(1)
        refs_l.addLayout(refs_actions)
        self.lbl_refs_count = QLabel()
        refs_l.addWidget(self.lbl_refs_count)
        self.list_refs.model().rowsInserted.connect(
            lambda *_args: self._refresh_ref_count())
        self.list_refs.model().rowsRemoved.connect(
            lambda *_args: self._refresh_ref_count())
        root.addWidget(self.grp_refs)

        self.grp_analysis = QGroupBox()
        analysis_l = QVBoxLayout(self.grp_analysis)
        run_row = QHBoxLayout()
        self.lbl_grid = QLabel()
        self.combo_grid = QComboBox()
        for index in range(1, 6):
            self.combo_grid.addItem(str(index))
        self.combo_grid.setCurrentIndex(2)
        self.btn_run = QPushButton()
        self.btn_run.setMinimumHeight(38)
        self.btn_run.setObjectName("PrimaryBtn")
        self.btn_run.clicked.connect(self._run_difference)
        self.btn_stop = QPushButton()
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_all)
        self.btn_open = QPushButton()
        self.btn_open.setEnabled(False)
        self.btn_open.clicked.connect(self._open_output)
        run_row.addWidget(self.lbl_grid)
        run_row.addWidget(self.combo_grid)
        run_row.addWidget(self.btn_run, 1)
        run_row.addWidget(self.btn_stop)
        run_row.addWidget(self.btn_open)
        analysis_l.addLayout(run_row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.hide()
        analysis_l.addWidget(self.progress)
        self.lbl_status = QLabel()
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet(
            "background:#F8FAFC;border:1px solid #DDE5EC;"
            "border-radius:5px;padding:5px 8px;color:#475569;")
        analysis_l.addWidget(self.lbl_status)
        root.addWidget(self.grp_analysis)

        self.grp_visual = QGroupBox()
        visual_l = QGridLayout(self.grp_visual)
        self.lbl_iso = QLabel()
        self.sld_iso = QSlider(Qt.Horizontal)
        self.sld_iso.setRange(1, 100)
        self.sld_iso.setValue(1)
        self.sld_iso.valueChanged.connect(self._on_iso_slider)
        self.edit_iso = QLineEdit("0.001")
        self.edit_iso.setValidator(QDoubleValidator(0.000001, 1.0, 6))
        self.edit_iso.returnPressed.connect(self._on_iso_edit)
        self.lbl_opacity = QLabel()
        self.sld_opacity = QSlider(Qt.Horizontal)
        self.sld_opacity.setRange(5, 100)
        self.sld_opacity.setValue(75)
        self.sld_opacity.valueChanged.connect(self._on_opacity_slider)
        self.lbl_opacity_value = QLabel("0.75")
        self.lbl_phase = QLabel()
        self.btn_pos = QPushButton()
        self.btn_neg = QPushButton()
        self.btn_pos.clicked.connect(lambda: self._pick_color("pos"))
        self.btn_neg.clicked.connect(lambda: self._pick_color("neg"))
        self.btn_refresh = QPushButton()
        self.btn_refresh.clicked.connect(self._apply_visual)
        visual_l.addWidget(self.lbl_iso, 0, 0)
        visual_l.addWidget(self.sld_iso, 0, 1)
        visual_l.addWidget(self.edit_iso, 0, 2)
        visual_l.addWidget(self.lbl_opacity, 1, 0)
        visual_l.addWidget(self.sld_opacity, 1, 1)
        visual_l.addWidget(self.lbl_opacity_value, 1, 2)
        visual_l.addWidget(self.lbl_phase, 2, 0)
        visual_l.addWidget(self.btn_pos, 2, 1)
        visual_l.addWidget(self.btn_neg, 2, 2)
        visual_l.addWidget(self.btn_refresh, 2, 3)
        root.addWidget(self.grp_visual)
        root.addStretch(1)
        self._update_color_buttons()

    def _apply_lang(self):
        t = self._t
        self.lbl_title.setText(t("title"))
        self.lbl_intro.setText(t("intro"))
        self.grp_source.setTitle(t("source"))
        self.lbl_source_path.setText(t("source_path"))
        self.btn_browse_complex.setText(t("browse"))
        self.btn_current.setText(t("use_current"))
        self.grp_fragments.setTitle(t("fragments"))
        self.lbl_fragments_hint.setText(t("fragments_hint"))
        self.lbl_atom_ids.setText(t("atom_ids"))
        self.btn_canvas_selection.setText(t("selection"))
        self.btn_add_fragment.setText(t("add_fragment"))
        self.btn_auto_complete.setText(t("auto_complete"))
        self.btn_remove_fragment.setText(t("remove_fragment"))
        self.table_fragments.setHorizontalHeaderLabels([
            t("col_name"), t("col_atoms"), t("col_charge"), t("col_mult")])
        self.lbl_method.setText(t("method"))
        self.lbl_nproc.setText(t("nproc"))
        self.lbl_mem.setText(t("mem"))
        self.lbl_parent_charge.setText(t("parent_charge"))
        self.lbl_parent_mult.setText(t("parent_mult"))
        self.btn_generate.setText(t("generate"))
        self.btn_run_fragments.setText(t("run_fragments"))
        self.grp_refs.setTitle(t("references"))
        self.lbl_refs_hint.setText(t("refs_hint"))
        self.btn_add_refs.setText(t("add_refs"))
        self.btn_remove_ref.setText(t("remove_ref"))
        self.btn_clear_refs.setText(t("clear_refs"))
        self.grp_analysis.setTitle(t("analysis"))
        self.lbl_grid.setText(t("grid"))
        self.btn_run.setText(t("run"))
        self.btn_stop.setText(t("stop"))
        self.btn_open.setText(t("open"))
        self.grp_visual.setTitle(t("visual"))
        self.lbl_iso.setText(t("iso"))
        self.lbl_opacity.setText(t("opacity"))
        self.lbl_phase.setText(t("fill"))
        self.btn_pos.setToolTip(t("pos"))
        self.btn_neg.setToolTip(t("neg"))
        self.btn_refresh.setText(t("refresh"))
        self._refresh_source()
        self._refresh_ref_count()

    def _refresh_source(self):
        if not self._complex_path:
            self.edit_complex.clear()
            self.lbl_source.setText(self._t("source_none"))
            return
        self.edit_complex.setText(self._complex_path)
        self.lbl_source.setText(self._t("source_loaded").format(
            name=os.path.basename(self._complex_path),
            n=len(self._atoms)))

    def _refresh_ref_count(self):
        self.lbl_refs_count.setText(
            self._t("refs_count").format(n=self.list_refs.count()))

    def _append_log(self, message):
        try:
            self._log_func(message)
        except Exception:
            pass

    def set_complex_from_main(self, path):
        path = str(path or "").strip()
        if (not path or not os.path.isfile(path)
                or os.path.splitext(path)[1].lower()
                not in (".fch", ".fchk")):
            self._complex_path = ""
            self._atoms = []
            self._archive_dir = ""
            self.table_fragments.setRowCount(0)
            self._refresh_source()
            self.btn_open.setEnabled(False)
            return
        try:
            atoms = get_atoms_from_fchk(path)
        except Exception as exc:  # noqa: BLE001
            self._append_log("[EDD] 结构解析失败：%s" % exc)
            return
        if not atoms:
            return
        self._complex_path = os.path.abspath(path)
        self._atoms = atoms
        charge, multiplicity = read_charge_multiplicity(
            self._complex_path, atoms)
        self.spin_parent_charge.setValue(charge)
        self.spin_parent_mult.setValue(multiplicity)
        stem = os.path.splitext(os.path.basename(path))[0]
        self._archive_dir = os.path.join(
            os.path.dirname(path), stem + "_EDD")
        self.table_fragments.setRowCount(0)
        self._refresh_source()
        self.btn_open.setEnabled(True)
        if self.glw is not None:
            try:
                self.glw.set_molecule(atoms)
                self.glw.frame_to_molecule()
            except Exception:
                pass

    def showEvent(self, event):
        super().showEvent(event)
        cur = self._get_fchk()
        if cur and not self._complex_path:
            self.set_complex_from_main(cur)

    def _browse_complex(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self._t("source_path"), "", self._t("filter_wave"))
        if path:
            self.set_complex_from_main(path)

    def _fill_from_canvas_selection(self):
        try:
            values = sorted(set(int(value)
                                for value in self._get_selected_atoms()))
        except Exception:
            values = []
        if values:
            self.edit_fragment_atoms.setText(_compact(values))
        else:
            QMessageBox.information(
                self, self._t("warning"), self._t("selection_empty"))

    def _fragment_rows(self):
        fragments = []
        for row in range(self.table_fragments.rowCount()):
            name_item = self.table_fragments.item(row, 0)
            atoms_item = self.table_fragments.item(row, 1)
            charge_item = self.table_fragments.item(row, 2)
            mult_item = self.table_fragments.item(row, 3)
            name = name_item.text().strip() if name_item else (
                "Fragment%d" % (row + 1))
            atom_text = atoms_item.text().strip() if atoms_item else ""
            ids = parse_atom_indices(atom_text)
            charge = int(charge_item.text()) if charge_item else 0
            mult = int(mult_item.text()) if mult_item else 1
            fragments.append(EDDFragment(name, ids, charge, mult))
        return fragments

    def _add_fragment(self):
        try:
            ids = parse_atom_indices(self.edit_fragment_atoms.text())
        except ValueError as exc:
            QMessageBox.warning(self, self._t("warning"), str(exc))
            return
        if not ids:
            QMessageBox.warning(
                self, self._t("warning"), self._t("invalid_id"))
            return
        used = set()
        for fragment in self._fragment_rows():
            used.update(fragment.atoms)
        overlap = used.intersection(ids)
        if overlap:
            QMessageBox.warning(
                self, self._t("warning"),
                self._t("overlap", atoms=_compact(overlap)))
            return
        row = self.table_fragments.rowCount()
        self.table_fragments.insertRow(row)
        values = [
            "Fragment%d" % (row + 1), _compact(ids),
            str(self.spin_fragment_charge.value()),
            str(self.spin_fragment_mult.value()),
        ]
        for column, value in enumerate(values):
            self.table_fragments.setItem(
                row, column, QTableWidgetItem(value))
        self.table_fragments.setCurrentCell(row, 0)
        self.edit_fragment_atoms.clear()
        self._append_log(self._t(
            "fragment_added", name=values[0], atoms=values[1]))

    def _remove_fragment(self):
        rows = sorted({
            index.row() for index in self.table_fragments.selectedIndexes()
        }, reverse=True)
        for row in rows:
            self.table_fragments.removeRow(row)

    def _auto_complete(self):
        try:
            fragments = self._fragment_rows()
        except ValueError as exc:
            QMessageBox.warning(self, self._t("warning"), str(exc))
            return
        used = set()
        for fragment in fragments:
            used.update(fragment.atoms)
        missing = set(int(atom[0]) for atom in self._atoms) - used
        if not missing:
            QMessageBox.information(
                self, self._t("warning"), self._t("complete"))
            return
        self.edit_fragment_atoms.setText(_compact(missing))
        self._add_fragment()

    def _prepare_jobs(self):
        if not self._complex_path or not self._atoms:
            raise EDDWorkflowError(self._t("need_source"))
        fragments = self._fragment_rows()
        if not fragments:
            raise EDDWorkflowError(self._t("fragment_empty"))
        output_dir = self._archive_dir or os.path.join(
            os.path.dirname(self._complex_path), "EDD_jobs")
        stem = os.path.splitext(os.path.basename(self._complex_path))[0]
        jobs = prepare_fragment_jobs(
            self._atoms, fragments, output_dir, stem,
            self.edit_method.text().strip() or "B3LYP/6-311G(d,p)",
            self.spin_nproc.value(), self.edit_mem.text().strip() or "8GB",
            require_complete=True,
            include_complex=True,
            complex_charge=self.spin_parent_charge.value(),
            complex_multiplicity=self.spin_parent_mult.value())
        self._jobs = jobs
        return jobs

    def _generate_fragment_inputs(self):
        try:
            jobs = self._prepare_jobs()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, self._t("warning"), str(exc))
            return
        self.lbl_status.setText(self._t("inputs_done", n=max(0, len(jobs) - 1)))
        self.btn_open.setEnabled(True)
        for job in jobs:
            self._append_log("[EDD] %s" % job["gjf"])

    def _run_fragment_jobs(self):
        if self._fragment_worker is not None and self._fragment_worker.isRunning():
            return
        g16 = str(self._get_g16() or find_gaussian() or "").strip()
        if not g16 or not os.path.isfile(g16):
            QMessageBox.warning(
                self, self._t("warning"), self._t("need_g16"))
            return
        try:
            jobs = self._prepare_jobs()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, self._t("warning"), str(exc))
            return
        self.progress.setRange(0, len(jobs))
        self.progress.setValue(0)
        self.progress.show()
        self._fragment_worker = FragmentJobsWorker(jobs, g16, self)
        self._fragment_worker.log.connect(self._append_log)
        self._fragment_worker.progress.connect(
            lambda done, total, label: self._on_fragment_progress(
                done, total, label))
        self._fragment_worker.completed.connect(self._on_fragments_done)
        self._fragment_worker.failed.connect(self._on_failed)
        self._set_running(True)
        self.lbl_status.setText(self._t("working"))
        self._fragment_worker.start()

    def _on_fragment_progress(self, done, total, label):
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.lbl_status.setText(self._t(
            "status_frag", done=done, total=total, label=label))

    def _on_fragments_done(self, result):
        self._set_running(False)
        self.progress.hide()
        parent_fch = result.get("complex", "")
        if not parent_fch or not os.path.isfile(parent_fch):
            self._on_failed("母体计算完成，但没有生成母体 fch。")
            return
        try:
            parent_atoms = get_atoms_from_fchk(parent_fch)
        except Exception as exc:  # noqa: BLE001
            self._on_failed("母体 fch 解析失败：%s" % exc)
            return
        self._complex_path = os.path.abspath(parent_fch)
        self._atoms = parent_atoms
        self.edit_complex.setText(self._complex_path)
        self._refresh_source()
        charge, multiplicity = read_charge_multiplicity(
            self._complex_path, parent_atoms)
        self.spin_parent_charge.setValue(charge)
        self.spin_parent_mult.setValue(multiplicity)
        if self.glw is not None:
            try:
                self.glw.set_molecule(parent_atoms)
                self.glw.frame_to_molecule()
            except Exception:
                pass
        self.list_refs.clear()
        for path in result.get("fragments", []):
            self._append_ref(path)
        self.lbl_status.setText(self._t(
            "refs_count", n=self.list_refs.count()))
        self._append_log("[EDD] 母体与全部片段任务、formchk 已完成")
        QTimer.singleShot(0, self._run_difference)

    def _add_reference_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, self._t("dialog_refs"), "", self._t("filter_wave"))
        for path in paths:
            self._append_ref(path)

    def _append_ref(self, path):
        path = os.path.abspath(path)
        existing = {
            self.list_refs.item(i).data(Qt.UserRole)
            for i in range(self.list_refs.count())
        }
        if path in existing:
            return
        item = QListWidgetItem(os.path.basename(path))
        item.setToolTip(path)
        item.setData(Qt.UserRole, path)
        self.list_refs.addItem(item)

    def _remove_reference(self):
        for item in self.list_refs.selectedItems():
            self.list_refs.takeItem(self.list_refs.row(item))

    def _reference_paths(self):
        return [
            self.list_refs.item(index).data(Qt.UserRole)
            for index in range(self.list_refs.count())
        ]

    def _run_difference(self):
        if self._difference_worker is not None and self._difference_worker.isRunning():
            return
        exe = str(self._get_multiwfn() or "").strip()
        if not exe or not os.path.isfile(exe):
            QMessageBox.warning(
                self, self._t("warning"), self._t("need_mw"))
            return
        references = self._reference_paths()
        if not references:
            QMessageBox.warning(
                self, self._t("warning"), self._t("need_refs"))
            return
        output_dir = self._archive_dir or os.path.dirname(self._complex_path)
        kwargs = {
            "complex_fch": self._complex_path,
            "references": references,
            "output_dir": output_dir,
            "output_name": "electron_density_difference.cub",
            "grid_quality": self.combo_grid.currentIndex() + 1,
            "multiwfn_exe": exe,
        }
        self._difference_worker = DifferenceWorker(kwargs, self)
        self._difference_worker.log.connect(self._append_log)
        self._difference_worker.completed.connect(self._on_difference_done)
        self._difference_worker.failed.connect(self._on_failed)
        self.progress.setRange(0, 0)
        self.progress.show()
        self._set_running(True)
        self.lbl_status.setText(self._t("working"))
        self._difference_worker.start()

    def _on_difference_done(self, result):
        self._last_result = result
        self._set_running(False)
        self.progress.hide()
        self.btn_open.setEnabled(True)
        stats = result.stats
        self.lbl_status.setText(
            self._t("done") + "\n" +
            self._t("stats").format(
                n=result.counts.get("references", len(result.references)),
                points=result.counts.get("cube_points", 0),
                lo=stats.get("minimum", 0.0),
                hi=stats.get("maximum", 0.0)) + "\n" +
            self._t("out", path=result.archive_dir))
        self._append_log("[EDD] " + self._t("cube_saved", path=result.cube_path))
        self._apply_visual()

    def _on_failed(self, message):
        self._set_running(False)
        self.progress.hide()
        self.lbl_status.setText(self._t("failed"))
        QMessageBox.warning(self, self._t("failed"), message)
        self._append_log("[EDD] %s" % message)

    def _set_running(self, running):
        self.grp_fragments.setEnabled(not running)
        self.grp_refs.setEnabled(not running)
        for widget in (
                self.btn_run, self.btn_run_fragments,
                self.btn_generate, self.btn_browse_complex,
                self.btn_current, self.btn_add_refs,
                self.btn_remove_ref, self.btn_clear_refs,
                self.table_fragments):
            widget.setEnabled(not running)
        self.btn_stop.setEnabled(running)

    def _stop_all(self):
        for worker in (self._fragment_worker, self._difference_worker):
            if worker is not None and worker.isRunning():
                worker.stop()
        self.lbl_status.setText(self._t("cancel"))

    def _open_output(self):
        path = self._archive_dir or (
            self._last_result.archive_dir if self._last_result else "")
        if path and os.path.isdir(path):
            os.startfile(path)

    def _on_iso_slider(self, value):
        self._iso = max(0.000001, value / 1000.0)
        self.edit_iso.setText("%.4f" % self._iso)
        self._apply_visual()

    def _on_iso_edit(self):
        try:
            value = float(self.edit_iso.text().strip())
        except ValueError:
            return
        if value <= 0:
            return
        self._iso = value
        self.sld_iso.blockSignals(True)
        self.sld_iso.setValue(max(1, int(round(value * 1000))))
        self.sld_iso.blockSignals(False)
        self._apply_visual()

    def _on_opacity_slider(self, value):
        self._opacity = value / 100.0
        self.lbl_opacity_value.setText("%.2f" % self._opacity)
        self._apply_visual()

    def _pick_color(self, phase):
        current = QColor(*(self._pos_rgb if phase == "pos"
                           else self._neg_rgb))
        color = QColorDialog.getColor(current, self)
        if not color.isValid():
            return
        rgb = (color.red(), color.green(), color.blue())
        if phase == "pos":
            self._pos_rgb = rgb
        else:
            self._neg_rgb = rgb
        self._update_color_buttons()
        self._apply_visual()

    def _update_color_buttons(self):
        self.btn_pos.setStyleSheet(
            "background:rgb(%d,%d,%d);border:1px solid #555;"
            "border-radius:10px;" % self._pos_rgb)
        self.btn_neg.setStyleSheet(
            "background:rgb(%d,%d,%d);border:1px solid #555;"
            "border-radius:10px;" % self._neg_rgb)

    def _apply_visual(self):
        if self.glw is None or self._last_result is None:
            return
        try:
            if self._atoms:
                self.glw.set_molecule(self._atoms)
            self.glw.set_phase_colors(self._pos_rgb, self._neg_rgb)
            self.glw.load(self._last_result.cube_path, self._iso)
            self.glw.set_opacity(self._opacity)
            self.glw.set_vmd_scene([{
                "type": "orbital",
                "vol": self._last_result.cube_path,
                "iso": self._iso,
            }])
        except Exception as exc:  # noqa: BLE001
            self._append_log("[EDD] 画布更新失败：%s" % exc)

    def shutdown(self):
        for worker in (self._fragment_worker, self._difference_worker):
            if worker is not None and worker.isRunning():
                worker.stop()
                worker.wait(5000)


def _compact(values):
    nums = sorted(set(int(value) for value in values))
    if not nums:
        return ""
    parts = []
    start = previous = nums[0]
    for value in nums[1:]:
        if value == previous + 1:
            previous = value
            continue
        parts.append(str(start) if start == previous
                     else "%d-%d" % (start, previous))
        start = previous = value
    parts.append(str(start) if start == previous
                 else "%d-%d" % (start, previous))
    return ",".join(parts)


__all__ = [
    "EDDPanel",
    "DifferenceWorker",
    "FragmentJobsWorker",
]
