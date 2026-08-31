# -*- coding: utf-8 -*-
"""
ETSNOCVViewer — Sci-Fi Light Edition
Sidebar navigation + QPainter 3D molecular viewer.
Complete ETS-NOCV: Multiwfn → cube → VMD preview → Tachyon render → draw bonds.
"""

import os, sys, shutil, socket, time, threading, tempfile

from PyQt5.QtWidgets import (
    QMainWindow, QVBoxLayout, QHBoxLayout, QGridLayout,
    QWidget, QPushButton, QLabel, QLineEdit, QFileDialog,
    QComboBox, QTextEdit, QProgressBar, QMessageBox,
    QFrame, QApplication, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QCheckBox,
    QGroupBox, QStackedWidget, QDialog, QSlider,
    QRadioButton, QSplitter, QColorDialog, QButtonGroup,
)
from PyQt5.QtCore import Qt, QSettings, QTimer, QSize
from PyQt5.QtGui import QFont, QTextCursor, QPixmap, QPainter, QColor, QIcon, QDoubleValidator

from etsnocv._nav import NavButton
from etsnocv.config import NOCV_STYLES, LIGHT_QSS, DEFAULT_MULTIWFN, DEFAULT_VMD, DEFAULT_TACHYON
from etsnocv.fchk_parser import get_atoms_from_fchk, get_bonds_from_fchk
from etsnocv.runner import MultiwfnRunner, SetupWorker, CubeGenWorker
from etsnocv.molcanvas import MolCanvas, STYLE_PRESETS, get_atoms_from_any, get_bonds_from_fchk as calc_bonds
from etsnocv.nocv_analyzer import (
    parse_nocv_table, build_ets_nocv_input, build_nocv_setup, find_cub_files,
    read_fch_alpha_beta,
    preview_cub, render_current_view, render_cub_auto,
    _live_style_tcl, _style_tcl,
)
from etsnocv.locale import get_locale
from etsnocv.gaussian_generator import GjfGeneratorWidget


class SciFiGroupBox(QGroupBox):
    def __init__(self, title, parent=None):
        super().__init__(title, parent)


class RingConfigDialog(QDialog):
    def __init__(self, parent, canvas, L):
        super().__init__(parent)
        self.canvas = canvas
        self.L = L
        self.setWindowTitle(L["dialog_ring_title"])
        self.setFixedSize(400, 420)
        self.setStyleSheet(LIGHT_QSS)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        title = QLabel(L["dialog_ring_title"])
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        layout.addWidget(QFrame(objectName="Separator"))
        grid = QGridLayout()
        grid.setVerticalSpacing(8)
        grid.setHorizontalSpacing(10)
        self.sliders = {}
        ring_params = [
            ("ring_angle_a", canvas.ring_a_angle, 0, 360),
            ("ring_tilt_a", canvas.ring_a_tilt, 0, 180),
            ("ring_angle_b", canvas.ring_b_angle, 0, 360),
            ("ring_tilt_b", canvas.ring_b_tilt, 0, 180),
        ]
        for row, (key, init_val, vmin, vmax) in enumerate(ring_params):
            lbl = QLabel(L[key])
            lbl.setFixedWidth(120)
            grid.addWidget(lbl, row, 0)
            slider = QSlider(Qt.Horizontal)
            slider.setRange(vmin, vmax)
            slider.setValue(int(init_val))
            slider.setTracking(True)
            slider.valueChanged.connect(self._on_slider_changed)
            self.sliders[key] = slider
            grid.addWidget(slider, row, 1)
            val_lbl = QLabel(str(int(init_val)) + "\u00b0")
            val_lbl.setFixedWidth(45)
            val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.sliders[key + "_label"] = val_lbl
            grid.addWidget(val_lbl, row, 2)

        layout.addWidget(QFrame(objectName="Separator"))

        row = 4
        grid.addWidget(QLabel(L["bond_width"]), row, 0)
        bw_slider = QSlider(Qt.Horizontal)
        bw_slider.setRange(10, 100)
        bw_slider.setValue(int(canvas.bond_width * 10))
        bw_slider.setTracking(True)
        bw_slider.valueChanged.connect(self._on_slider_changed)
        self.sliders["bond_width"] = bw_slider
        grid.addWidget(bw_slider, row, 1)
        bw_val = QLabel("{:.1f}".format(canvas.bond_width))
        bw_val.setFixedWidth(45)
        bw_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.sliders["bond_width_label"] = bw_val
        grid.addWidget(bw_val, row, 2)

        row = 5
        grid.addWidget(QLabel(L["atom_size"]), row, 0)
        as_slider = QSlider(Qt.Horizontal)
        as_slider.setRange(10, 60)
        as_slider.setValue(int(canvas.atom_scale * 100))
        as_slider.setTracking(True)
        as_slider.valueChanged.connect(self._on_slider_changed)
        self.sliders["atom_scale"] = as_slider
        grid.addWidget(as_slider, row, 1)
        as_val = QLabel("{:.2f}".format(canvas.atom_scale))
        as_val.setFixedWidth(45)
        as_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.sliders["atom_scale_label"] = as_val
        grid.addWidget(as_val, row, 2)

        layout.addLayout(grid)
        layout.addStretch()
        btn_row = QWidget()
        brl = QHBoxLayout(btn_row)
        brl.setContentsMargins(0, 0, 0, 0)
        brl.addStretch()
        btn_close = QPushButton("OK")
        btn_close.setObjectName("PrimaryBtn")
        btn_close.clicked.connect(self.accept)
        brl.addWidget(btn_close)
        layout.addWidget(btn_row)

    def _on_slider_changed(self):
        self.canvas.ring_a_angle = self.sliders["ring_angle_a"].value()
        self.canvas.ring_a_tilt = self.sliders["ring_tilt_a"].value()
        self.canvas.ring_b_angle = self.sliders["ring_angle_b"].value()
        self.canvas.ring_b_tilt = self.sliders["ring_tilt_b"].value()
        self.canvas.bond_width = self.sliders["bond_width"].value() / 10.0
        self.canvas.atom_scale = self.sliders["atom_scale"].value() / 100.0
        self.canvas.update()
        for k in ["ring_angle_a", "ring_tilt_a", "ring_angle_b", "ring_tilt_b"]:
            self.sliders[k + "_label"].setText(str(self.sliders[k].value()) + "\u00b0")
        self.sliders["bond_width_label"].setText("{:.1f}".format(self.canvas.bond_width))
        self.sliders["atom_scale_label"].setText("{:.2f}".format(self.canvas.atom_scale))


class ETSNOCVViewer(QMainWindow):
    def __init__(self, lang="zh"):
        super().__init__()
        self._lang = lang
        self.L = get_locale(lang)
        self.setWindowTitle(self.L["title"])
        self.resize(1600, 900)
        self.setMinimumSize(1100, 700)

        self._settings = QSettings("ETSNOCV", "ETSNOCVViewer")
        self.multiwfn_path = self._settings.value("multiwfn_path", DEFAULT_MULTIWFN)
        self.vmd_path = self._settings.value("vmd_path", DEFAULT_VMD)
        self.tachyon_path = self._settings.value("tachyon_path", DEFAULT_TACHYON)
        last_dir = self._settings.value("last_dir", "")
        self._last_dir = last_dir if last_dir else os.path.expanduser("~")

        self.fchk_complex = ""
        self.fchk_frag1 = ""
        self.fchk_frag2 = ""
        self.frag1_open_shell = False
        self.frag2_open_shell = False
        self.current_atoms = []
        self.current_bonds = []
        self._runner = MultiwfnRunner()
        self._calculating = False
        self._calc_worker = None
        self._mwfn_session = None
        self._is_generating_cube = False
        self._cube_gen_worker = None
        self._tmp_dir = None
        self._grid_quality = 3
        self._progress_value = 0
        self._progress_timer = QTimer()
        self._progress_timer.timeout.connect(self._tick_progress)
        self._nocv_rows = []
        self._cub_files = {}
        self._ets_nocv_tmp = None
        self._vmd_port = None
        self._vmd_render_dir = None
        self._vmd_persist_sock = None
        self._vmd_proc = None
        self._vmd_dash_pairs = []  # list of (a1, a2) tuples currently in VMD
        self.current_iso = 0.003
        self.current_opacity = None
        self.iso_step = 0.005
        self.opacity_step = 0.05
        self._custom_pos_rgb = None
        self._custom_neg_rgb = None

        self._build_ui()
        self.setStyleSheet(LIGHT_QSS)

    def _save_paths(self):
        self._settings.setValue("multiwfn_path", self.multiwfn_path)
        self._settings.setValue("vmd_path", self.vmd_path)
        self._settings.setValue("tachyon_path", self.tachyon_path)
        if hasattr(self, '_last_dir'):
            self._settings.setValue("last_dir", self._last_dir)

    def _build_ui(self):
        L = self.L
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 8, 12, 10)
        main_layout.setSpacing(4)

        body_wrapper = QWidget()
        body_layout = QHBoxLayout(body_wrapper)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self._build_sidebar(body_layout, L)
        self._content_stack = QStackedWidget()
        body_layout.addWidget(self._content_stack, stretch=1)
        self._build_molecule_page(L)
        self._build_analysis_page(L)
        self._build_log_page(L)
        self._gen_widget = GjfGeneratorWidget(L, self._last_dir)
        self._gen_widget.last_dir_changed.connect(self._on_gen_dir_changed)
        self._content_stack.addWidget(self._gen_widget)
        self._build_settings_page(L)
        main_layout.addWidget(body_wrapper, stretch=1)

    def _build_sidebar(self, parent_layout, L):
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(210)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(8, 12, 8, 12)
        side_layout.setSpacing(0)
        nav_title = QLabel(L["nav_title"])
        nav_title.setObjectName("StatusLabel")
        side_layout.addWidget(nav_title)
        side_layout.addSpacing(6)

        self._nav_molecule = NavButton(L["nav_molecule"], "\u25C9")
        self._nav_molecule.set_active(True)
        self._nav_molecule.clicked.connect(lambda: self._switch_page(0))
        side_layout.addWidget(self._nav_molecule)
        side_layout.addSpacing(2)

        self._nav_analysis = NavButton(L["nav_analysis"], "\u2261")
        self._nav_analysis.clicked.connect(lambda: self._switch_page(1))
        side_layout.addWidget(self._nav_analysis)
        side_layout.addSpacing(2)

        self._nav_log = NavButton(L["nav_log"], "\u2630")
        self._nav_log.clicked.connect(lambda: self._switch_page(2))
        side_layout.addWidget(self._nav_log)
        side_layout.addSpacing(2)

        self._nav_generator = NavButton(L["nav_generator"], "+")
        self._nav_generator.clicked.connect(lambda: self._switch_page(3))
        side_layout.addWidget(self._nav_generator)
        side_layout.addSpacing(2)

        self._nav_settings = NavButton(L["nav_settings"], "\u2699")
        self._nav_settings.clicked.connect(lambda: self._switch_page(4))
        side_layout.addWidget(self._nav_settings)
        side_layout.addStretch()

        status_label = QLabel(L["sidebar_version"])
        status_label.setObjectName("StatusLabel")
        side_layout.addWidget(status_label)
        parent_layout.addWidget(sidebar)

    def _build_molecule_page(self, L):
        page = QWidget()
        page_layout = QHBoxLayout(page)
        page_layout.setContentsMargins(16, 12, 16, 12)
        page_layout.setSpacing(14)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        # Input Files
        input_card = SciFiGroupBox(L["card_input"])
        in_layout = QGridLayout(input_card)
        in_layout.setContentsMargins(12, 12, 12, 12)
        in_layout.setVerticalSpacing(5)
        in_layout.setHorizontalSpacing(6)

        fchk_items = [
            ("fchk_complex", L["lbl_complex"], L["placeholder_complex"], self._browse_complex),
            ("fchk_frag1", L["lbl_frag1"], L["placeholder_frag1"], self._browse_frag1),
            ("fchk_frag2", L["lbl_frag2"], L["placeholder_frag2"], self._browse_frag2),
        ]
        for row, (attr, label_text, placeholder, browse_fn) in enumerate(fchk_items):
            lbl = QLabel(label_text)
            lbl.setStyleSheet("font-weight: 600; font-size: 9pt;")
            in_layout.addWidget(lbl, row, 0)
            entry = QLineEdit()
            entry.setPlaceholderText(placeholder)
            entry.setReadOnly(True)
            setattr(self, f"txt_{attr}", entry)
            in_layout.addWidget(entry, row, 1)
            btn = QPushButton(L["btn_browse"])
            btn.clicked.connect(browse_fn)
            in_layout.addWidget(btn, row, 2)

        # Open-shell spin-flip toggles for fragments
        self.chk_flip_frag1 = QCheckBox(L.get("lbl_flip_spin_frag1", "Flip alpha/beta for Frag 1"))
        self.chk_flip_frag1.setVisible(False)
        self.chk_flip_frag2 = QCheckBox(L.get("lbl_flip_spin_frag2", "Flip alpha/beta for Frag 2"))
        self.chk_flip_frag2.setVisible(False)
        spin_hint = QLabel(L.get("hint_spin_flip", "Check if Multiwfn should swap alpha/beta orbitals for this fragment"))
        spin_hint.setObjectName("HintLabel")
        spin_hint.setWordWrap(True)
        spin_hint.setVisible(False)
        self._spin_hint_label = spin_hint
        in_layout.addWidget(self.chk_flip_frag1, 3, 0, 1, 3)
        in_layout.addWidget(self.chk_flip_frag2, 4, 0, 1, 3)
        in_layout.addWidget(spin_hint, 5, 0, 1, 3)

        self.btn_run = QPushButton(L["btn_run_calc"])
        self.btn_run.setObjectName("PrimaryBtn")
        self.btn_run.clicked.connect(self._run_analysis)
        in_layout.addWidget(self.btn_run, 6, 0, 1, 2)

        self.btn_stop = QPushButton(L["btn_stop"])
        self.btn_stop.setObjectName("DangerBtn")
        self.btn_stop.clicked.connect(self._stop_analysis)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setVisible(False)
        in_layout.addWidget(self.btn_stop, 6, 2, 1, 1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumHeight(6)
        self.progress_bar.setTextVisible(False)
        in_layout.addWidget(self.progress_bar, 7, 0, 1, 3)

        left_layout.addWidget(input_card)

        # 3D Viewer
        viewer_frame = QFrame()
        viewer_frame.setObjectName("ViewerFrame")
        viewer_layout = QVBoxLayout(viewer_frame)
        viewer_layout.setContentsMargins(2, 2, 2, 2)
        viewer_layout.setSpacing(0)
        self.mol_canvas = MolCanvas(viewer_frame)
        self.mol_canvas.atom_clicked.connect(self._on_atom_selected)
        # MolCanvas VMD preview callbacks (used by DashBondDialog only)
        self._vmd_dash_pairs = []
        viewer_layout.addWidget(self.mol_canvas)
        left_layout.addWidget(viewer_frame, stretch=1)

        # Toolbar
        toolbar_row = QWidget()
        tr_layout = QHBoxLayout(toolbar_row)
        tr_layout.setContentsMargins(4, 0, 4, 0)
        tr_layout.setSpacing(8)
        self.lbl_hint = QLabel(L["hint_default"])
        self.lbl_hint.setObjectName("HintLabel")
        tr_layout.addWidget(self.lbl_hint)
        tr_layout.addStretch()

        self.chk_shadows = QCheckBox(L["chk_shadows"])
        self.chk_shadows.setChecked(True)
        self.chk_shadows.toggled.connect(lambda v: setattr(self.mol_canvas, 'show_shadows', v) or self.mol_canvas.update())
        tr_layout.addWidget(self.chk_shadows)

        self.chk_gradient = QCheckBox(L["chk_gradient"])
        self.chk_gradient.setChecked(True)
        self.chk_gradient.toggled.connect(lambda v: setattr(self.mol_canvas, 'bg_gradient', v) or self.mol_canvas.update())
        tr_layout.addWidget(self.chk_gradient)

        self.chk_houk = QCheckBox(L["chk_houk"])
        self.chk_houk.setChecked(True)
        self.chk_houk.toggled.connect(lambda v: setattr(self.mol_canvas, 'show_crosshair', v) or self.mol_canvas.update())
        tr_layout.addWidget(self.chk_houk)

        tr_layout.addWidget(QLabel(L["lbl_label_mode"]))
        self.combo_label = QComboBox()
        self.combo_label.addItems([L["label_element"], L["label_index"], L["label_none"]])
        self.combo_label.setCurrentIndex(2)
        self.combo_label.currentIndexChanged.connect(lambda i: setattr(self.mol_canvas, 'label_mode', i) or self.mol_canvas.update())
        self.combo_label.setFixedWidth(75)
        tr_layout.addWidget(self.combo_label)

        tr_layout.addWidget(QLabel(L.get("lbl_style", "Style")))
        self.combo_style = QComboBox()
        style_keys = list(STYLE_PRESETS.keys())
        style_names = [STYLE_PRESETS[k]["name"] for k in style_keys]
        self.combo_style.addItems(style_names)
        self.combo_style.setCurrentIndex(style_keys.index("HoukMol") if "HoukMol" in style_keys else 0)
        self.combo_style.currentIndexChanged.connect(self._on_style_changed)
        self.combo_style.setFixedWidth(110)
        tr_layout.addWidget(self.combo_style)

        btn_reset = QPushButton(L["btn_reset"])
        btn_reset.clicked.connect(lambda: self.mol_canvas.auto_fit() or self.mol_canvas.update())
        tr_layout.addWidget(btn_reset)

        btn_ring = QPushButton(L["btn_ring_config"])
        btn_ring.clicked.connect(lambda: RingConfigDialog(self, self.mol_canvas, self.L).exec_())
        tr_layout.addWidget(btn_ring)

        btn_snap = QPushButton(L["btn_save_image"])
        btn_snap.clicked.connect(self._save_image)
        tr_layout.addWidget(btn_snap)

        left_layout.addWidget(toolbar_row)
        page_layout.addWidget(left_panel, stretch=3)

        self._content_stack.addWidget(page)

    def _build_log_page(self, L):
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(16, 12, 16, 12)
        page_layout.setSpacing(8)

        log_card = SciFiGroupBox(L["card_log_title"])
        lg_layout = QVBoxLayout(log_card)
        lg_layout.setContentsMargins(8, 8, 8, 8)
        lg_layout.setSpacing(4)
        self.txt_log = QTextEdit()
        lg_layout.addWidget(self.txt_log, stretch=1)
        btn_row = QWidget()
        brl = QHBoxLayout(btn_row)
        brl.setContentsMargins(0, 0, 0, 0)
        brl.setSpacing(4)
        btn_copy = QPushButton(L["btn_copy"])
        btn_copy.clicked.connect(self._copy_result)
        brl.addWidget(btn_copy)
        btn_clear = QPushButton(L["btn_clear"])
        btn_clear.clicked.connect(self._clear_log)
        brl.addWidget(btn_clear)
        lg_layout.addWidget(btn_row)
        page_layout.addWidget(log_card)

        self._content_stack.addWidget(page)

    def _build_analysis_page(self, L):
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(16, 12, 16, 12)
        page_layout.setSpacing(6)

        # ── Render Parameters group ──
        render_card = SciFiGroupBox(L["card_ets_params"])
        render_layout = QGridLayout(render_card)
        render_layout.setContentsMargins(12, 12, 12, 8)
        render_layout.setVerticalSpacing(3)
        render_layout.setHorizontalSpacing(6)

        # Row 0: Grid quality + Style + Color pickers
        render_layout.addWidget(QLabel(L["grid_quality"]), 0, 0)
        self.combo_grid = QComboBox()
        self.combo_grid.addItems([L["grid_1"], L["grid_2"], L["grid_3"], L["grid_4"]])
        self.combo_grid.setCurrentIndex(2)
        render_layout.addWidget(self.combo_grid, 0, 1)

        render_layout.addWidget(QLabel(L.get("style_name", "Style:")), 0, 2)
        self.combo_style = QComboBox()
        self.combo_style.setIconSize(QSize(30, 13))
        self.combo_style.setMaxVisibleItems(20)
        for name in NOCV_STYLES:
            icon = self._make_style_icon(NOCV_STYLES[name])
            self.combo_style.addItem(icon, name)
        self.combo_style.setCurrentText("blue-red")
        self.combo_style.currentTextChanged.connect(self._on_style_changed)
        render_layout.addWidget(self.combo_style, 0, 3)

        self.btn_pos_color = QPushButton("")
        self.btn_pos_color.setFixedSize(28, 28)
        self.btn_pos_color.setToolTip(L.get("pick_pos_color", "Pick positive isosurface color"))
        self.btn_pos_color.clicked.connect(lambda: self._pick_phase_color("pos"))
        self.btn_pos_color.setContextMenuPolicy(Qt.CustomContextMenu)
        self.btn_pos_color.customContextMenuRequested.connect(lambda: self._reset_phase_color("pos"))
        render_layout.addWidget(self.btn_pos_color, 0, 4)

        self.btn_neg_color = QPushButton("")
        self.btn_neg_color.setFixedSize(28, 28)
        self.btn_neg_color.setToolTip(L.get("pick_neg_color", "Pick negative isosurface color"))
        self.btn_neg_color.clicked.connect(lambda: self._pick_phase_color("neg"))
        self.btn_neg_color.setContextMenuPolicy(Qt.CustomContextMenu)
        self.btn_neg_color.customContextMenuRequested.connect(lambda: self._reset_phase_color("neg"))
        render_layout.addWidget(self.btn_neg_color, 0, 5)

        # Row 1: Resolution + Shading + Transparent + Threads
        render_layout.addWidget(QLabel(L.get("resolution", "Res:")), 1, 0)
        self.combo_res = QComboBox()
        self.combo_res.addItems(["2000x1500", "1200x900", "3000x2250"])
        self.combo_res.setCurrentIndex(0)
        render_layout.addWidget(self.combo_res, 1, 1)

        render_layout.addWidget(QLabel(L.get("shading", "Shade:")), 1, 2)
        shade_widget = QWidget()
        shade_layout = QHBoxLayout(shade_widget)
        shade_layout.setContentsMargins(0, 0, 0, 0)
        shade_layout.setSpacing(4)
        self.shade_group = QButtonGroup(self)
        self.rb_full = QRadioButton(L.get("shade_full", "Full"))
        self.rb_medium = QRadioButton(L.get("shade_medium", "Med"))
        self.shade_group.addButton(self.rb_full, 0)
        self.shade_group.addButton(self.rb_medium, 1)
        self.rb_full.setChecked(True)
        self.rb_full.setToolTip(L.get("shade_full", "Full shading"))
        self.rb_medium.setToolTip(L.get("shade_medium", "Medium shading"))
        self.shade_group.buttonClicked.connect(self._on_shade_changed)
        shade_layout.addWidget(self.rb_full)
        shade_layout.addWidget(self.rb_medium)
        render_layout.addWidget(shade_widget, 1, 3)

        self.chk_trans_raster = QCheckBox(L.get("trans_raster", "Trans"))
        self.chk_trans_raster.setChecked(True)
        self.chk_trans_raster.setToolTip(L.get("trans_raster_tip", "Transparent background for Tachyon"))
        render_layout.addWidget(self.chk_trans_raster, 1, 4)

        render_layout.addWidget(QLabel(L.get("threads", "Thr:")), 1, 5)
        self.txt_threads = QLineEdit("8")
        self.txt_threads.setMaximumWidth(50)
        self.txt_threads.setAlignment(Qt.AlignCenter)
        self.txt_threads.setToolTip(L.get("threads_tip", "Tachyon rendering threads"))
        render_layout.addWidget(self.txt_threads, 1, 6)

        # Row 2: Isovalue slider + Opacity slider (equal-length HBoxes)
        iso_widget = QWidget()
        iso_layout = QHBoxLayout(iso_widget)
        iso_layout.setContentsMargins(0, 0, 0, 0)
        iso_layout.setSpacing(4)
        iso_layout.addWidget(QLabel(L.get("isovalue", "Iso:")))
        self.iso_slider = QSlider(Qt.Horizontal)
        self.iso_slider.setRange(1, 500)
        self.iso_slider.setValue(3)
        self.iso_slider.setToolTip("Isovalue")
        self.iso_slider.valueChanged.connect(self._on_iso_slider_changed)
        iso_layout.addWidget(self.iso_slider, 1)
        self.txt_iso = QLineEdit("0.003")
        self.txt_iso.setFixedWidth(60)
        self.txt_iso.setAlignment(Qt.AlignCenter)
        self.txt_iso.setToolTip(L.get("txt_iso_tip", "Press Enter to apply"))
        self.txt_iso.returnPressed.connect(self._on_iso_text_changed)
        iso_layout.addWidget(self.txt_iso)

        opa_widget = QWidget()
        opa_layout = QHBoxLayout(opa_widget)
        opa_layout.setContentsMargins(0, 0, 0, 0)
        opa_layout.setSpacing(4)
        opa_layout.addWidget(QLabel(L.get("opacity", "Opa:")))
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(1, 500)
        self.opacity_slider.setValue(375)
        self.opacity_slider.setToolTip("Opacity")
        self.opacity_slider.valueChanged.connect(self._on_opacity_slider_changed)
        opa_layout.addWidget(self.opacity_slider, 1)
        self.txt_opacity = QLineEdit("0.75")
        self.txt_opacity.setFixedWidth(60)
        self.txt_opacity.setAlignment(Qt.AlignCenter)
        self.txt_opacity.setToolTip(L.get("txt_iso_tip", "Press Enter to apply"))
        self.txt_opacity.returnPressed.connect(self._on_opacity_text_changed)
        opa_layout.addWidget(self.txt_opacity)

        row2 = QHBoxLayout()
        row2.setSpacing(12)
        row2.addWidget(iso_widget, 1)
        row2.addWidget(opa_widget, 1)
        render_layout.addLayout(row2, 2, 0, 1, 9)
        page_layout.addWidget(render_card)

        # ── Action buttons ──
        btn_row = QWidget()
        br_layout = QHBoxLayout(btn_row)
        br_layout.setContentsMargins(0, 0, 0, 0)
        br_layout.setSpacing(6)

        self.btn_render = QPushButton(L.get("render_png", "Render PNG"))
        self.btn_render.clicked.connect(self._render_view)
        self.btn_render.setEnabled(False)
        br_layout.addWidget(self.btn_render)

        self.btn_preview_nocv = QPushButton(L.get("open_vmd", "Open VMD"))
        self.btn_preview_nocv.clicked.connect(self._vmd_nocv_pair)
        self.btn_preview_nocv.setEnabled(False)
        br_layout.addWidget(self.btn_preview_nocv)

        self.btn_export_table = QPushButton(L.get("export_table", "Export Table"))
        self.btn_export_table.clicked.connect(self._export_nocv_table)
        self.btn_export_table.setEnabled(False)
        br_layout.addWidget(self.btn_export_table)

        self.btn_close_vmd = QPushButton(L.get("btn_close_vmd", "Close VMD"))
        self.btn_close_vmd.clicked.connect(self._close_vmd)
        br_layout.addWidget(self.btn_close_vmd)

        self.btn_restart = QPushButton(L.get("btn_restart", "Restart"))
        self.btn_restart.clicked.connect(self._restart_software)
        br_layout.addWidget(self.btn_restart)

        self.btn_mol_canvas = QPushButton(L.get("btn_mol_canvas", "Mol Canvas"))
        self.btn_mol_canvas.clicked.connect(self._open_mol_canvas_dialog)
        self.btn_mol_canvas.setEnabled(False)
        br_layout.addWidget(self.btn_mol_canvas)

        br_layout.addStretch()
        page_layout.addWidget(btn_row)

        # ── Big NOCV results table ──
        hint_label = QLabel(L.get("table_nocv_dbl_click", "Double-click a row to preview in VMD"))
        hint_label.setObjectName("HintLabel")
        page_layout.addWidget(hint_label)

        self.table_nocv2 = QTableWidget()
        self.table_nocv2.setColumnCount(8)
        headers2 = [L["table_col_pair"], L["table_col_energy"],
                    L["table_col_orb_plus"], L["table_col_eigen_plus"], L["table_col_e_plus"],
                    L["table_col_orb_minus"], L["table_col_eigen_minus"], L["table_col_e_minus"]]
        self.table_nocv2.setHorizontalHeaderLabels(headers2)
        self.table_nocv2.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_nocv2.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_nocv2.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table_nocv2.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_nocv2.verticalHeader().setVisible(False)
        self.table_nocv2.doubleClicked.connect(self._vmd_nocv_pair)
        self.table_nocv2.itemSelectionChanged.connect(self._on_nocv2_row_selected)
        page_layout.addWidget(self.table_nocv2, stretch=1)

        self._content_stack.addWidget(page)
        self._update_color_buttons()

    def _on_gen_dir_changed(self, path):
        self._last_dir = path

    def _build_settings_page(self, L):
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(24, 24, 24, 24)
        page_layout.setSpacing(14)
        card = SciFiGroupBox(L["page_settings_title"])
        card_layout = QGridLayout(card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setVerticalSpacing(8)
        card_layout.setHorizontalSpacing(8)
        card_layout.setColumnStretch(0, 0)
        card_layout.setColumnStretch(1, 1)
        card_layout.setColumnStretch(2, 0)

        path_specs = [
            (L["lbl_multiwfn_path"], "txt_multiwfn2", self.multiwfn_path, L["multiwfn_placeholder"], self._browse_exe),
            (L["lbl_vmd_path"], "txt_vmd", self.vmd_path, L["vmd_placeholder"], self._browse_vmd),
            (L["lbl_tachyon_path"], "txt_tachyon", self.tachyon_path, L["tachyon_placeholder"], self._browse_tachyon),
        ]
        for r, (label_text, attr, default_val, placeholder, browse_fn) in enumerate(path_specs):
            lbl = QLabel(label_text)
            lbl.setStyleSheet("font-weight: 600; font-size: 10pt;")
            card_layout.addWidget(lbl, r, 0)
            entry = QLineEdit(default_val)
            entry.setPlaceholderText(placeholder)
            setattr(self, attr, entry)
            card_layout.addWidget(entry, r, 1)
            btn = QPushButton(L["btn_browse"])
            btn.clicked.connect(browse_fn)
            card_layout.addWidget(btn, r, 2)
        page_layout.addWidget(card)

        about_card = SciFiGroupBox(L["page_about_title"])
        about_layout = QVBoxLayout(about_card)
        about_layout.setContentsMargins(24, 20, 24, 20)
        about_layout.setSpacing(6)
        about_text = QLabel(L["about_text"])
        about_text.setObjectName("Subtitle")
        about_text.setWordWrap(True)
        about_layout.addWidget(about_text)
        page_layout.addWidget(about_card)
        self._content_stack.addWidget(page)

    def _switch_page(self, index):
        self._nav_molecule.set_active(index == 0)
        self._nav_analysis.set_active(index == 1)
        self._nav_log.set_active(index == 2)
        self._nav_generator.set_active(index == 3)
        self._nav_settings.set_active(index == 4)
        self._content_stack.setCurrentIndex(index)

    _LOG_COLORS = {"#ce9178": "#0067c0", "#f44336": "#E53935", "#4ec9b0": "#2E7D32",
                   "#dcdcaa": "#6D4C41", "#f39c12": "#E65100", "#888": "#90A4AE"}

    def _log(self, text, color=None):
        if color:
            color = self._LOG_COLORS.get(color, color)
            self.txt_log.append("<span style='color:" + color + "'>" + text + "</span>")
        else:
            self.txt_log.append(text)
        self.txt_log.moveCursor(QTextCursor.End)
        self.txt_log.ensureCursorVisible()
        if hasattr(self, 'task_log'):
            self.task_log.append(text)
            self.task_log.ensureCursorVisible()

    def _browse_exe(self):
        path, _ = QFileDialog.getOpenFileName(self, self.L["dialog_select_exe"], "", self.L["dialog_exe_filter"])
        if path:
            self.multiwfn_path = path
            if hasattr(self, 'txt_multiwfn'):
                self.txt_multiwfn.setText(path)
            if hasattr(self, 'txt_multiwfn2'):
                self.txt_multiwfn2.setText(path)
            self._save_paths()

    def _browse_vmd(self):
        path, _ = QFileDialog.getOpenFileName(self, self.L["dialog_select_vmd"], "", self.L["dialog_exe_filter"])
        if path:
            self.vmd_path = path
            if hasattr(self, 'txt_vmd'):
                self.txt_vmd.setText(path)
            self._save_paths()

    def _browse_tachyon(self):
        path, _ = QFileDialog.getOpenFileName(self, self.L["dialog_select_tachyon"], "", self.L["dialog_exe_filter"])
        if path:
            self.tachyon_path = path
            if hasattr(self, 'txt_tachyon'):
                self.txt_tachyon.setText(path)
            self._save_paths()

    def _save_config(self):
        self._save_paths()
        self._log(self.L["log_config_saved"], "#4ec9b0")

    def _browse_fchk_for(self, target_attr, txt_widget):
        path, _ = QFileDialog.getOpenFileName(self, self.L["dialog_open_fchk"], self._last_dir, self.L["dialog_file_filter"])
        if path:
            self._last_dir = os.path.dirname(path)
            self._save_paths()
            setattr(self, target_attr, path)
            txt_widget.setText(os.path.basename(path))
            if target_attr == "fchk_complex":
                self._load_molecule(path)
            # Auto-detect open-shell for fragments
            if target_attr in ("fchk_frag1", "fchk_frag2"):
                ab = read_fch_alpha_beta(path)
                is_open = ab is not None and ab[0] != ab[1]
                if target_attr == "fchk_frag1":
                    self.frag1_open_shell = is_open
                else:
                    self.frag2_open_shell = is_open
                self._update_spin_flip_ui()

    def _browse_complex(self):
        self._browse_fchk_for("fchk_complex", self.txt_fchk_complex)

    def _browse_frag1(self):
        self._browse_fchk_for("fchk_frag1", self.txt_fchk_frag1)

    def _browse_frag2(self):
        self._browse_fchk_for("fchk_frag2", self.txt_fchk_frag2)

    def _update_spin_flip_ui(self):
        """Show/hide spin-flip checkboxes based on whether any fragment is open-shell."""
        any_open = self.frag1_open_shell or self.frag2_open_shell
        self.chk_flip_frag1.setVisible(self.frag1_open_shell)
        self.chk_flip_frag2.setVisible(self.frag2_open_shell)
        self._spin_hint_label.setVisible(any_open)
        if self.frag1_open_shell:
            self.chk_flip_frag1.setChecked(False)
        if self.frag2_open_shell:
            self.chk_flip_frag2.setChecked(False)

    def _build_spin_answers(self):
        """Only include flip answers for fragments that are actually open-shell.
        Multiwfn only asks 'Do you want to flip spin?' for open-shell fragments.
        Sending extra answers for closed-shell fragments poisons the menu stream.
        """
        answers = []
        if self.frag1_open_shell:
            answers.append(self.chk_flip_frag1.isChecked())
        if self.frag2_open_shell:
            answers.append(self.chk_flip_frag2.isChecked())
        return answers if answers else None

    def _load_molecule(self, fchk_path):
        L = self.L
        try:
            atoms = get_atoms_from_fchk(fchk_path)
        except ValueError as e:
            self._log("Error: " + str(e) + "\n", "#f44336")
            QMessageBox.critical(self, L["err_title"], str(e))
            return
        if not atoms:
            return
        self.current_atoms = atoms
        bonds = get_bonds_from_fchk(atoms)
        self.current_bonds = bonds
        self.mol_canvas.selected_atom = None
        self.mol_canvas.set_data(atoms, bonds)
        self.mol_canvas.update()
        self.btn_mol_canvas.setEnabled(True)
        self._log("\n" + L["log_loaded"] + os.path.basename(fchk_path) + "\n", "#4ec9b0")
        self._log(L["log_atoms"] + str(len(atoms)) + L["log_bonds"] + str(len(bonds)) + "\n", "#4ec9b0")
        self.lbl_hint.setText(L["hint_default"])

    def _on_atom_selected(self, atom_idx):
        if not self.current_atoms:
            return
        for idx, sym, an, (x, y, z) in self.current_atoms:
            if idx == atom_idx:
                self._log(f"[{idx}] {sym} ({round(x,2)}, {round(y,2)}, {round(z,2)})", "#dcdcaa")
                break

    def _on_style_changed(self, idx):
        style_keys = list(STYLE_PRESETS.keys())
        if 0 <= idx < len(style_keys):
            self.mol_canvas.set_style(style_keys[idx])

    def _open_mol_canvas_dialog(self):
        if not self.mol_canvas.atoms:
            QMessageBox.warning(self, self.L["warn_title"], self.L.get("err_no_molecule", "No molecule loaded"))
            return
        dlg = DashBondDialog(self)
        dlg.exec_()

    def _parse_orbitals(self):
        text = self.txt_orbitals.text().strip() if hasattr(self, 'txt_orbitals') else "1-30"
        orbs = []
        for part in text.replace(",", " ").split():
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                try:
                    a, b = part.split("-", 1)
                    orbs.extend(range(int(a), int(b) + 1))
                except ValueError:
                    continue
            else:
                try:
                    orbs.append(int(part))
                except ValueError:
                    continue
        return sorted(set(orbs))

    def _stop_analysis(self):
        """Stop ongoing ETS-NOCV analysis: terminate Multiwfn, kill workers, reset UI."""
        L = self.L
        self._log(L["log_calc_stop"], "#ce9178")

        # 1. Kill Multiwfn runner (short-lived process)
        self._runner.kill()

        # 2. Stop SetupWorker and shut down its Multiwfn session
        old_calc = getattr(self, '_calc_worker', None)
        if old_calc is not None:
            try:
                old_calc.finished.disconnect()
            except (TypeError, RuntimeError):
                pass
            try:
                old_calc.log.disconnect()
            except (TypeError, RuntimeError):
                pass
            if hasattr(old_calc, 'stop'):
                old_calc.stop()
            if old_calc.isRunning():
                old_calc.wait(3000)
            if old_calc.isRunning():
                old_calc.terminate()
                old_calc.wait(1000)

        # 3. Shutdown persistent Multiwfn session
        if self._mwfn_session is not None:
            self._mwfn_session.shutdown()
            self._mwfn_session = None

        # 4. Stop CubeGenWorker — disconnect signals first to prevent stale callbacks
        old_cube = getattr(self, '_cube_gen_worker', None)
        if old_cube is not None:
            try:
                old_cube.finished.disconnect()
            except (TypeError, RuntimeError):
                pass
            try:
                old_cube.error.disconnect()
            except (TypeError, RuntimeError):
                pass
            try:
                old_cube.log.disconnect()
            except (TypeError, RuntimeError):
                pass
            if old_cube.isRunning():
                old_cube.wait(5000)
            if old_cube.isRunning():
                old_cube.terminate()
                old_cube.wait(1000)

        # 5. Kill old VMD process (prevents stale VMD windows)
        if self._vmd_proc is not None:
            try:
                self._vmd_proc.kill()
            except Exception:
                pass
            self._vmd_proc = None

        # 6. Reset VMD state + clear stale cube cache
        self._close_persist_sock()
        self._vmd_port = None
        self._vmd_render_dir = None
        self._cub_files = {}

        # 7. Reset UI state
        self._calculating = False
        self._is_generating_cube = False
        # Keep old worker refs to avoid QThread GC warnings; 
        # they will be replaced when new workers are created.
        self._progress_timer.stop()
        self.progress_bar.setVisible(False)
        self.btn_run.setEnabled(True)
        self.btn_run.setVisible(True)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setVisible(False)
        self.lbl_hint.setText(L.get("hint_default", ""))
        self._log(L.get("log_ready_short", "Ready.\n"), "#888")

    def _run_analysis(self):
        L = self.L
        if self._calculating:
            self._stop_analysis()
            # Brief pause to let processes die
            import time
            time.sleep(0.3)
        exe = self.multiwfn_path
        if not exe or not os.path.exists(exe):
            QMessageBox.critical(self, L["err_title"], L["err_invalid_exe"])
            return
        if not self.fchk_complex or not os.path.exists(self.fchk_complex):
            QMessageBox.critical(self, L["err_title"], L["err_no_complex"])
            return
        if not self.fchk_frag1 or not self.fchk_frag2:
            QMessageBox.critical(self, L["err_title"], L["err_no_frags"])
            return

        self._grid_quality = self.combo_grid.currentIndex() + 1
        work_dir = os.path.dirname(os.path.abspath(self.fchk_complex))
        # Use system temp directory to avoid path issues with special characters like ()
        import tempfile
        tmp_dir = tempfile.mkdtemp(prefix="ets_nocv_")
        self._tmp_dir = tmp_dir
        self._ets_nocv_tmp = work_dir
        os.makedirs(tmp_dir, exist_ok=True)

        # Copy fchk files into tmp_dir
        for src, dst_name in [
            (self.fchk_complex, os.path.basename(self.fchk_complex)),
            (self.fchk_frag1, os.path.basename(self.fchk_frag1)),
            (self.fchk_frag2, os.path.basename(self.fchk_frag2)),
        ]:
            dst = os.path.join(tmp_dir, dst_name)
            if not os.path.exists(dst):
                shutil.copy2(src, dst)

        # Shut down any existing session
        if self._mwfn_session is not None:
            self._mwfn_session.shutdown()
            self._mwfn_session = None

        # Disconnect old worker signals to prevent stale callbacks
        for attr in ('_calc_worker', '_cube_gen_worker'):
            old = getattr(self, attr, None)
            if old is not None:
                for sig_name in ('finished', 'error', 'log'):
                    sig = getattr(old, sig_name, None)
                    if sig is not None:
                        try:
                            sig.disconnect()
                        except (TypeError, RuntimeError):
                            pass

        spin_answers = self._build_spin_answers()

        # Use paths in tmp_dir (files were copied there)
        complex_in_tmp = os.path.join(tmp_dir, os.path.basename(self.fchk_complex))
        frag1_in_tmp = os.path.join(tmp_dir, os.path.basename(self.fchk_frag1))
        frag2_in_tmp = os.path.join(tmp_dir, os.path.basename(self.fchk_frag2))

        self._calculating = True
        self._progress_value = 0
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self._progress_timer.start(80)
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_stop.setVisible(True)
        self._log(L["log_calc_start"] + "\n", "#ce9178")
        self._log(f"Temp directory: {tmp_dir}\n", "#808080")
        self._log(L.get("log_setup_mode", "Persistent session mode (on-demand cube)\n"), "#dcdcaa")
        self.lbl_hint.setText(L["hint_calculating"])

        self._calc_worker = SetupWorker(
            exe, complex_in_tmp, frag1_in_tmp, frag2_in_tmp,
            spin_answers, tmp_dir, self
        )
        self._calc_worker.finished.connect(self._on_setup_done)
        self._calc_worker.log.connect(lambda msg: self._log(msg + "\n", "#808080"))
        self._calc_worker.start()

    def _on_setup_done(self, output, session, error):
        L = self.L
        self._progress_timer.stop()
        self.progress_bar.setValue(100)
        QTimer.singleShot(500, lambda: self.progress_bar.setVisible(False))
        self._calculating = False
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setVisible(False)
        self.btn_export_table.setEnabled(True)

        # Store persistent session for on-demand cube generation
        self._mwfn_session = session if session is not None and session.is_alive() else None

        if error or output is None:
            self._log(L["log_calc_failed"], "#f44336")
            if error:
                self._log(f"  {error}\n", "#f44336")
            self.lbl_hint.setText(L["hint_default"])
            return

        # Save full output log FIRST (before parsing, for debugging)
        log_path = os.path.join(self._ets_nocv_tmp, "ets_nocv_output.txt")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(output)
        self._log(L["log_done"] + f"  ({len(output):,} chars)\n", "#4ec9b0")
        self._log(f"  Output log saved: {log_path}\n", "#6a9955")

        # Parse NOCV table
        self._nocv_rows = []
        header, rows, table_str = parse_nocv_table(output)
        if rows:
            self._nocv_rows = rows
            self._log(L["log_pairs_found"] + str(len(rows)) + "\n", "#4ec9b0")
            self._populate_nocv_table(rows)
            self.btn_preview_nocv.setEnabled(True)
            self.btn_render.setEnabled(True)
            self.lbl_hint.setText(L["hint_done"])
        else:
            self._log(L["log_parse_failed"], "#f44336")
            # Show a snippet of output for diagnostics
            snippet = output[:500].replace("\n", "\\n")
            self._log(f"  Output starts with: {snippet}...\n", "#808080")
            self.lbl_hint.setText(L["hint_default"])

        # Auto-switch to analysis tab
        self._content_stack.setCurrentIndex(1)

    def _on_cube_ready(self, cub_path, pair_num, output_delta=""):
        """Cube generated on-demand — refresh running VMD via socket, or launch new one."""
        L = self.L
        # Ignore stale callbacks from old workers
        if not self._is_generating_cube:
            return
        self._is_generating_cube = False
        self.btn_preview_nocv.setEnabled(True)

        cub_name = os.path.basename(cub_path)
        self._log(L["log_cub_generated"] + cub_name + "\n", "#dcdcaa")

        # Always overwrite stale cube in work_dir with fresh one
        work_dir = getattr(self, '_ets_nocv_tmp', os.path.dirname(cub_path))
        dst_path = os.path.join(work_dir, cub_name)
        try:
            shutil.copy2(cub_path, dst_path)
        except (shutil.SameFileError, PermissionError):
            pass
        self._cub_files[cub_name] = dst_path

        # Append Multiwfn cube-generation output to combined log
        if output_delta:
            log_path = os.path.join(work_dir, "ets_nocv_output.txt")
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("\n" + "#" * 60 + "\n")
                f.write(f"# Cube generation output (pair {pair_num})\n")
                f.write("#" * 60 + "\n\n")
                f.write(output_delta)
            self._log(f"  Multiwfn output for cube ({len(output_delta):,} chars) appended to log\n", "#6a9955")

        try:
            # ── Try socket-based refresh (no VMD restart) ──
            if self._refresh_vmd_nocv(dst_path):
                self.current_iso = self._get_isovalue()
                self.current_opacity = 0.75
                self.iso_slider.blockSignals(True)
                self.iso_slider.setValue(int(self.current_iso * 1000))
                self.iso_slider.blockSignals(False)
                self.opacity_slider.blockSignals(True)
                self.opacity_slider.setValue(375)
                self.opacity_slider.blockSignals(False)
                self.txt_opacity.setText("0.75")
                self._log(L.get("log_vmd_refreshed", "VMD refreshed") + f" ({cub_name})\n", "#4ec9b0")
                # Replay existing canvas dashes (graphics top is preserved but replay for safety)
                self._vmd_dash_pairs.clear()
                for a1, a2, _ in self.mol_canvas.custom_dash_lines:
                    pair = (a1, a2)
                    if pair not in self._vmd_dash_pairs:
                        self._vmd_dash_pairs.append(pair)
                if self._vmd_dash_pairs:
                    self._send_vmd_cmd("graphics top delete all")
                    for a1, a2 in self._vmd_dash_pairs:
                        self._vmd_draw_one(a1, a2, log=False)
                return

            # ── Fall back: launch new VMD ──
            self._close_persist_sock()
            if self._vmd_proc is not None:
                try: self._vmd_proc.kill()
                except Exception: pass
                self._vmd_proc = None
            self._vmd_port, self._vmd_render_dir, self._vmd_proc = preview_cub(
                dst_path, self._get_isovalue(), self._get_style(), self.vmd_path, self._get_shade())
            self.current_iso = self._get_isovalue()
            self.current_opacity = 0.75
            self.iso_slider.blockSignals(True)
            self.iso_slider.setValue(int(self.current_iso * 1000))
            self.iso_slider.blockSignals(False)
            self.opacity_slider.blockSignals(True)
            self.opacity_slider.setValue(375)
            self.opacity_slider.blockSignals(False)
            self.txt_opacity.setText("0.75")
            # Replay existing canvas dashes
            self._vmd_dash_pairs.clear()
            for a1, a2, _ in self.mol_canvas.custom_dash_lines:
                pair = (a1, a2)
                if pair not in self._vmd_dash_pairs:
                    self._vmd_dash_pairs.append(pair)
            if self._vmd_dash_pairs:
                for a1, a2 in self._vmd_dash_pairs:
                    self._vmd_draw_one(a1, a2, log=False)
            self._log(L.get("log_vmd_launched", "VMD launched") + f" ({cub_name})\n", "#4ec9b0")
        except Exception as e:
            QMessageBox.critical(self, L["err_title"], str(e))

    def _on_cube_error(self, error_msg, pair_num):
        # Ignore stale callbacks from old workers
        if not self._is_generating_cube:
            return
        self._is_generating_cube = False
        self.btn_preview_nocv.setEnabled(True)
        QMessageBox.critical(self, self.L["err_title"], error_msg)
        self._log(f"[Cube Error] {error_msg}\n", "#f44336")

    def _cleanup_tmp(self, tmp_dir):
        if tmp_dir and os.path.isdir(tmp_dir):
            try:
                shutil.rmtree(tmp_dir)
            except OSError:
                pass

    def _refresh_cub_list(self):
        self.cub_list.clear()
        for fn in sorted(self._cub_files.keys()):
            self.cub_list.addItem(fn)

    def _populate_nocv_table(self, rows):
        L = self.L
        table = self.table_nocv2
        table.setRowCount(len(rows))
        has_spin = any(r.get('spin', 'Total') != 'Total' for r in rows)
        for r_idx, r in enumerate(rows):
            spin_tag = r.get('spin', 'Total')
            prefix = f"[{spin_tag[0]}] " if has_spin else ""
            items = [prefix + str(r['pair']), f"{r['pair_energy']:.2f}",
                     str(r['de_orbital']), f"{r['de_eigen']:.5f}", f"{r['de_energy']:.2f}",
                     str(r['dk_orbital']), f"{r['dk_eigen']:.5f}", f"{r['dk_energy']:.2f}"]
            for c_idx, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                table.setItem(r_idx, c_idx, item)

    def _export_nocv_table(self):
        """Export the NOCV results table to a CSV file."""
        L = self.L
        if not hasattr(self, '_nocv_rows') or not self._nocv_rows:
            QMessageBox.information(self, L["info_title"], L.get("info_no_data", "No data to export"))
            return
        save_path, _ = QFileDialog.getSaveFileName(
            self, L.get("export_table_title", "Export NOCV Table"),
            os.path.join(self._ets_nocv_tmp, "NOCV_table.csv") if getattr(self, '_ets_nocv_tmp', None) else "NOCV_table.csv",
            "CSV Files (*.csv);;All Files (*)")
        if not save_path:
            return
        try:
            import csv
            has_spin = any(r.get('spin', 'Total') != 'Total' for r in self._nocv_rows)
            # Build header
            cols = []
            if has_spin:
                cols.append("Spin")
            cols += [L["table_col_pair"], L["table_col_energy"],
                     L["table_col_orb_plus"], L["table_col_eigen_plus"], L["table_col_e_plus"],
                     L["table_col_orb_minus"], L["table_col_eigen_minus"], L["table_col_e_minus"]]
            with open(save_path, 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f)
                w.writerow(cols)
                for r in self._nocv_rows:
                    row = []
                    if has_spin:
                        row.append(r.get('spin', 'Total'))
                    row += [r['pair'], f"{r['pair_energy']:.2f}",
                            r['de_orbital'], f"{r['de_eigen']:.5f}", f"{r['de_energy']:.2f}",
                            r['dk_orbital'], f"{r['dk_eigen']:.5f}", f"{r['dk_energy']:.2f}"]
                    w.writerow(row)
            QMessageBox.information(self, L["info_title"],
                                    L.get("export_table_done", f"Table exported to {save_path}"))
            self._log(L.get("export_table_log", f"NOCV table exported: {save_path}"), "#4ec9b0")
        except Exception as e:
            QMessageBox.critical(self, L["err_title"],
                                 L.get("err_export_failed", f"Export failed: {e}"))

    def _close_vmd(self):
        """Kill the VMD process and reset VMD-related state."""
        L = self.L
        self._close_persist_sock()
        if self._vmd_proc is not None:
            try:
                self._vmd_proc.kill()
            except Exception:
                pass
            self._vmd_proc = None
        self._vmd_port = None
        self._vmd_render_dir = None
        self._log(L["log_vmd_closed"], "#4ec9b0")

    def _restart_software(self):
        """Full soft restart: kill VMD, shutdown Multiwfn, clear temp files, reset state."""
        L = self.L
        reply = QMessageBox.question(self, L["info_title"], L["confirm_restart"],
                                      QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        # 1. Kill VMD
        self._close_persist_sock()
        if self._vmd_proc is not None:
            try:
                self._vmd_proc.kill()
            except Exception:
                pass
            self._vmd_proc = None
        self._vmd_port = None
        self._vmd_render_dir = None

        # 2. Shutdown Multiwfn session
        if self._mwfn_session is not None:
            self._mwfn_session.shutdown()
            self._mwfn_session = None

        # 3. Stop any running workers
        old_calc = getattr(self, '_calc_worker', None)
        if old_calc is not None and old_calc.isRunning():
            old_calc.stop()
            old_calc.wait(3000)
        old_cube = getattr(self, '_cube_gen_worker', None)
        if old_cube is not None and old_cube.isRunning():
            old_cube.wait(3000)

        # 4. Clean up temp directory
        if self._tmp_dir and os.path.isdir(self._tmp_dir):
            try:
                shutil.rmtree(self._tmp_dir)
            except OSError:
                pass
            self._tmp_dir = None

        # 5. Reset all state
        self._cub_files = {}
        self._nocv_rows = []
        self._is_generating_cube = False
        self._calculating = False
        self._progress_timer.stop()
        self.progress_bar.setVisible(False)
        self.btn_run.setEnabled(True)
        self.btn_run.setVisible(True)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setVisible(False)
        self.table_nocv2.setRowCount(0)
        self.btn_preview_nocv.setEnabled(False)
        self.btn_render.setEnabled(False)
        self.btn_export_table.setEnabled(False)

        self._log(L["log_restarted"], "#4ec9b0")
        self._log(L.get("log_ready_short", "Ready.\n"), "#888")

    def _on_nocv2_row_selected(self):
        pass

    def _vmd_nocv_pair(self):
        """Double-click / button handler: generate cube on-demand from persistent Multiwfn, then launch VMD.
        
        Single selection: generate one cube per pair.
        Multiple selection: generate a single merged cube (density summation) for selected pairs.
        """
        L = self.L
        selected_rows = set()
        for idx in self.table_nocv2.selectionModel().selectedRows():
            selected_rows.add(idx.row())
        
        if not selected_rows:
            QMessageBox.information(self, L["info_title"], L.get("info_select_row", "Please select a row first"))
            return
        
        if self._is_generating_cube:
            QMessageBox.information(self, L["info_title"], L.get("info_cube_working", "Cube generation in progress..."))
            return

        if not hasattr(self, '_nocv_rows'):
            QMessageBox.information(self, L["info_title"], L.get("info_select_row", "Please select a row first"))
            return

        # Check session health
        session = getattr(self, '_mwfn_session', None)
        if session is None or not session.is_alive():
            QMessageBox.critical(self, L["err_title"],
                L.get("err_no_session", "No active Multiwfn session. Please re-run ETS-NOCV analysis."))
            return

        tmp_dir = getattr(self, '_tmp_dir', None)
        if not tmp_dir or not os.path.isdir(tmp_dir):
            QMessageBox.critical(self, L["err_title"],
                L.get("err_no_tmpdir", "Temporary directory not found. Please re-run ETS-NOCV analysis."))
            return

        # Collect pair numbers, sorted
        pair_nums = sorted(set(
            self._nocv_rows[r]['pair'] 
            for r in selected_rows 
            if r < len(self._nocv_rows)
        ))

        if not pair_nums:
            QMessageBox.information(self, L["info_title"], L.get("info_select_row", "Please select a row first"))
            return

        if len(pair_nums) == 1:
            # Single pair
            pair_selector = str(pair_nums[0])
            cub_name = f"NOCVpair_{pair_nums[0]}.cub"
            first_row = min(selected_rows)
            spin = self._nocv_rows[first_row].get('spin', 'Total')
            if spin == 'Alpha':
                cub_name = f"NOCVpair_A{pair_nums[0]}.cub"
            elif spin == 'Beta':
                cub_name = f"NOCVpair_B{pair_nums[0]}.cub"
        else:
            # Multiple pairs: build selector like "3-6" or "3-6,8,10-12"
            pair_selector = self._build_pair_selector(pair_nums)
            cub_name = f"NOCVpair_{pair_selector.replace(',','_').replace('-','to')}.cub"

        # Check if cube already exists (cached)
        cub = self._cub_files.get(cub_name)
        if cub and os.path.exists(cub):
            try:
                # ── Try socket-based refresh (no VMD restart) ──
                if self._refresh_vmd_nocv(cub):
                    self.current_iso = self._get_isovalue()
                    self.current_opacity = 0.75
                    self.iso_slider.blockSignals(True)
                    self.iso_slider.setValue(int(self.current_iso * 1000))
                    self.iso_slider.blockSignals(False)
                    self.opacity_slider.blockSignals(True)
                    self.opacity_slider.setValue(375)
                    self.opacity_slider.blockSignals(False)
                    self.txt_opacity.setText("0.75")
                    self._log(L.get("log_vmd_refreshed", "VMD refreshed") + f" ({cub_name})\n", "#4ec9b0")
                    # Replay existing canvas dashes
                    self._vmd_dash_pairs.clear()
                    for a1, a2, _ in self.mol_canvas.custom_dash_lines:
                        pair = (a1, a2)
                        if pair not in self._vmd_dash_pairs:
                            self._vmd_dash_pairs.append(pair)
                    if self._vmd_dash_pairs:
                        self._send_vmd_cmd("graphics top delete all")
                        for a1, a2 in self._vmd_dash_pairs:
                            self._vmd_draw_one(a1, a2, log=False)
                    return

                # ── Fall back: launch new VMD ──
                self._close_persist_sock()
                if self._vmd_proc is not None:
                    try: self._vmd_proc.kill()
                    except Exception: pass
                    self._vmd_proc = None
                self._vmd_port, self._vmd_render_dir, self._vmd_proc = preview_cub(
                    cub, self._get_isovalue(), self._get_style(), self.vmd_path, self._get_shade())
                self.current_iso = self._get_isovalue()
                self.current_opacity = 0.75
                self.iso_slider.blockSignals(True)
                self.iso_slider.setValue(int(self.current_iso * 1000))
                self.iso_slider.blockSignals(False)
                self.opacity_slider.blockSignals(True)
                self.opacity_slider.setValue(375)
                self.opacity_slider.blockSignals(False)
                self.txt_opacity.setText("0.75")
                # Replay existing canvas dashes
                self._vmd_dash_pairs.clear()
                for a1, a2, _ in self.mol_canvas.custom_dash_lines:
                    pair = (a1, a2)
                    if pair not in self._vmd_dash_pairs:
                        self._vmd_dash_pairs.append(pair)
                if self._vmd_dash_pairs:
                    for a1, a2 in self._vmd_dash_pairs:
                        self._vmd_draw_one(a1, a2, log=False)
                self._log(L.get("log_vmd_launched", "VMD launched") + f" ({cub_name})\n", "#4ec9b0")
                return
            except Exception as e:
                QMessageBox.critical(self, L["err_title"], str(e))
                return

        self._is_generating_cube = True
        self.btn_preview_nocv.setEnabled(False)
        desc = f"pair {pair_selector}" if len(pair_nums) == 1 else f"pairs {pair_selector} (sum)"
        self._log(L.get("log_gen_cube", f"Generating cube for NOCV {desc}..."), "#dcdcaa")

        need_grid = len(self._cub_files) == 0
        self._cube_gen_worker = CubeGenWorker(session, pair_selector, 
                                               self._grid_quality if need_grid else None, 
                                               cub_name, tmp_dir, self)
        self._cube_gen_worker.finished.connect(self._on_cube_ready)
        self._cube_gen_worker.error.connect(self._on_cube_error)
        self._cube_gen_worker.log.connect(lambda msg: self._log(msg + "\n", "#808080"))
        self._cube_gen_worker.start()

    @staticmethod
    def _build_pair_selector(pair_nums):
        """Build a Multiwfn-style pair selector string.
        e.g. [3,4,5,6] -> "3-6", [3,5,8,10,11,12] -> "3,5,8,10-12"
        """
        if not pair_nums:
            return ""
        if len(pair_nums) == 1:
            return str(pair_nums[0])
        
        parts = []
        start = pair_nums[0]
        end = pair_nums[0]
        
        for n in pair_nums[1:]:
            if n == end + 1:
                end = n
            else:
                if start == end:
                    parts.append(str(start))
                else:
                    parts.append(f"{start}-{end}")
                start = n
                end = n
        
        if start == end:
            parts.append(str(start))
        else:
            parts.append(f"{start}-{end}")
        
        return ",".join(parts)

    def _get_selected_cub(self):
        selected = self.cub_list.selectedItems()
        if selected:
            fn = selected[0].text()
            return self._cub_files.get(fn)
        if self._cub_files:
            return list(self._cub_files.values())[0]
        return None

    def _get_selected_cubs(self):
        if self._cub_files:
            return list(self._cub_files.values())
        return []

    def _get_isovalue(self):
        try:
            return float(self.txt_iso.text().strip())
        except ValueError:
            return 0.03

    def _get_resolution(self):
        try:
            w, h = self.combo_res.currentText().strip().lower().split("x")
            return int(w), int(h)
        except Exception:
            return 2000, 1500

    def _get_style(self):
        return self.combo_style.currentText()

    def _get_shade(self):
        return "full" if self.shade_group.checkedId() == 0 else "medium"

    def _make_style_icon(self, style_cfg):
        """Draw a dual-color mini icon for the style combo."""
        pix = QPixmap(30, 13)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        pc = style_cfg["pos_color"]
        nc = style_cfg["neg_color"]
        if len(pc) >= 4 and pc[1] is not None:
            pos_rgb = (int(pc[1]*255), int(pc[2]*255), int(pc[3]*255))
        else:
            pos_rgb = (0, 180, 0)
        if len(nc) >= 4 and nc[1] is not None:
            neg_rgb = (int(nc[1]*255), int(nc[2]*255), int(nc[3]*255))
        else:
            neg_rgb = (0, 80, 200)
        painter.fillRect(0, 0, 15, 13, QColor(*pos_rgb))
        painter.fillRect(15, 0, 15, 13, QColor(*neg_rgb))
        painter.end()
        return QIcon(pix)

    def _update_color_buttons(self):
        """Set color button backgrounds from current style/custom RGB."""
        s = NOCV_STYLES.get(self._get_style(), NOCV_STYLES["blue-red"])
        pc = s["pos_color"]
        nc = s["neg_color"]

        if self._custom_pos_rgb:
            r, g, b = self._custom_pos_rgb
        elif len(pc) >= 4 and pc[1] is not None:
            r, g, b = int(pc[1]*255), int(pc[2]*255), int(pc[3]*255)
        else:
            r, g, b = 0, 180, 0
        self.btn_pos_color.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); border: 2px solid #888; border-radius: 4px;")

        if self._custom_neg_rgb:
            r, g, b = self._custom_neg_rgb
        elif len(nc) >= 4 and nc[1] is not None:
            r, g, b = int(nc[1]*255), int(nc[2]*255), int(nc[3]*255)
        else:
            r, g, b = 0, 80, 200
        self.btn_neg_color.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); border: 2px solid #888; border-radius: 4px;")

    def _pick_phase_color(self, phase):
        """Open QColorDialog and set custom positive/negative color with live refresh."""
        s = NOCV_STYLES.get(self._get_style(), NOCV_STYLES["blue-red"])
        if phase == "pos":
            if self._custom_pos_rgb:
                init = QColor(*self._custom_pos_rgb)
            else:
                pc = s["pos_color"]
                if len(pc) >= 4 and pc[1] is not None:
                    init = QColor(int(pc[1]*255), int(pc[2]*255), int(pc[3]*255))
                else:
                    init = QColor(0, 180, 0)
        else:
            if self._custom_neg_rgb:
                init = QColor(*self._custom_neg_rgb)
            else:
                nc = s["neg_color"]
                if len(nc) >= 4 and nc[1] is not None:
                    init = QColor(int(nc[1]*255), int(nc[2]*255), int(nc[3]*255))
                else:
                    init = QColor(0, 80, 200)
        color = QColorDialog.getColor(init, self, f"Pick {'Positive' if phase == 'pos' else 'Negative'} Color")
        if not color.isValid():
            return
        rgb = (color.red(), color.green(), color.blue())
        if phase == "pos":
            self._custom_pos_rgb = rgb
        else:
            self._custom_neg_rgb = rgb
        self._update_color_buttons()
        self._apply_custom_colors()

    def _reset_phase_color(self, phase):
        """Right-click: reset custom color to style default."""
        if phase == "pos":
            self._custom_pos_rgb = None
        else:
            self._custom_neg_rgb = None
        self._update_color_buttons()
        self._apply_custom_colors()

    def _apply_custom_colors(self):
        """Send custom color TCL to running VMD using fixed ColorID 31/32 channels.
        Pattern from orbital_viewer_v53.py: redefine ColorID 31/32, then reassign rep."""
        if self._vmd_port is None:
            return
        pos_rgb = self._custom_pos_rgb
        neg_rgb = self._custom_neg_rgb

        # Both cleared → re-source the full live style to restore defaults
        if pos_rgb is None and neg_rgb is None:
            self._source_live_tcl(self._get_style(), self._get_shade())
            return

        if pos_rgb is not None:
            r, g, b = pos_rgb
            self._send_vmd_cmd(
                f"color change rgb 31 {r/255.0:.4f} {g/255.0:.4f} {b/255.0:.4f}")
            self._send_vmd_cmd("mol modcolor 1 top ColorID 31")
        if neg_rgb is not None:
            r, g, b = neg_rgb
            self._send_vmd_cmd(
                f"color change rgb 32 {r/255.0:.4f} {g/255.0:.4f} {b/255.0:.4f}")
            self._send_vmd_cmd("mol modcolor 2 top ColorID 32")

    def _on_style_changed(self, style_name):
        """Live style switch — generate TCL to temp file and source via VMD socket."""
        # Reset custom colors when style changes
        self._custom_pos_rgb = None
        self._custom_neg_rgb = None
        self._update_color_buttons()

        if self._vmd_port is None:
            return
        shade = self._get_shade()
        self._source_live_tcl(style_name, shade)
        self._log(f"[Style] {style_name} ({shade})\n", "#dcdcaa")

    def _on_shade_changed(self):
        """Shading mode changed — refresh live style in VMD."""
        style = self._get_style()
        shade = self._get_shade()
        if self._vmd_port is None:
            return
        self._source_live_tcl(style, shade)
        self._log(f"[Shade] {shade}\n", "#dcdcaa")

    def _source_live_tcl(self, style_name, shade):
        """Write live style TCL to VMD's render_dir and source it via cd + relative path."""
        render_dir = getattr(self, '_vmd_render_dir', None)
        if not render_dir:
            return
        iso = self._get_isovalue()
        custom_pos = getattr(self, '_custom_pos_rgb', None)
        custom_neg = getattr(self, '_custom_neg_rgb', None)
        tcl = _live_style_tcl(style_name, shade, isovalue=iso,
                              custom_pos_rgb=custom_pos, custom_neg_rgb=custom_neg)
        style_path = os.path.join(render_dir, "_live_style.tcl")
        with open(style_path, "w") as f:
            f.write(tcl)
        self._send_vmd_cmd(f"cd {{{render_dir}}}")
        resp = self._send_vmd_cmd("source _live_style.tcl")
        # Re-apply current opacity (overwritten by style defaults in _live_style.tcl)
        op = self.current_opacity or 0.75
        for mat in ["_nocv_pos", "_nocv_neg"]:
            self._send_vmd_cmd(f"material change opacity {mat} {op}")
        if resp is not None and "ERROR" not in resp:
            self._log(f"[Style] {style_name} ({shade})\n", "#dcdcaa")

    def _vmd_preview(self):
        L = self.L
        cub = self._get_selected_cub()
        if not cub or not os.path.exists(cub):
            QMessageBox.critical(self, L["err_title"], L["err_no_cub"])
            return
        try:
            self._close_persist_sock()
            if self._vmd_proc is not None:
                try: self._vmd_proc.kill()
                except Exception: pass
                self._vmd_proc = None
            self._vmd_port, self._vmd_render_dir, self._vmd_proc = preview_cub(
                cub, self._get_isovalue(), self._get_style(), self.vmd_path, self._get_shade())
            self.current_iso = self._get_isovalue()
            self.current_opacity = None
            self._log(L["log_vmd_started"].format(self._vmd_port), "#4ec9b0")
            self.btn_h_filter.setEnabled(True)
            self.iso_slider.setEnabled(True)
            self.btn_mol_canvas.setEnabled(True)
            self.iso_slider.blockSignals(True)
            self.iso_slider.setValue(int(self.current_iso * 1000))
            self.iso_slider.blockSignals(False)
            self.opacity_slider.setEnabled(True)
            if self.current_opacity is None:
                style = NOCV_STYLES.get(self._get_style(), NOCV_STYLES["blue-red"])
                self.current_opacity = style["surface_mat"][5]
            self.opacity_slider.blockSignals(True)
            self.opacity_slider.setValue(int(self.current_opacity * 500))
            self.opacity_slider.blockSignals(False)
            self.txt_opacity.setText(f"{self.current_opacity:.4g}")
            # Replay any existing canvas dashes into VMD
            self._vmd_dash_pairs.clear()
            for a1, a2, _ in self.mol_canvas.custom_dash_lines:
                pair = (a1, a2)
                if pair not in self._vmd_dash_pairs:
                    self._vmd_dash_pairs.append(pair)
            if self._vmd_dash_pairs:
                for a1, a2 in self._vmd_dash_pairs:
                    self._vmd_draw_one(a1, a2, log=False)
        except Exception as e:
            self._log(L["log_vmd_failed"].format(e), "#f44336")

    def _toggle_h_filter(self):
        L = self.L
        if self._vmd_port is None:
            return
        if self.btn_h_filter.text() in [L["hide_h"], "Hide All H"]:
            h_str = self.txt_h_indices.text().strip()
            if h_str:
                try:
                    keep_indices = [int(x.strip()) for x in h_str.split(",") if x.strip()]
                    keep_str = " ".join(map(str, keep_indices))
                    cmd = f'mol modselect 0 top "not element H or (element H and index {keep_str})"'
                except ValueError:
                    cmd = 'mol modselect 0 top "not element H"'
            else:
                cmd = 'mol modselect 0 top "not element H"'
            self.btn_h_filter.setText(L["show_h"])
            self._log(L["log_hide_h"].format(h_str if h_str else "all"), "#dcdcaa")
        else:
            cmd = 'mol modselect 0 top all'
            self.btn_h_filter.setText(L["hide_h"])
            self._log(L["log_show_h"], "#dcdcaa")
        self._send_vmd_cmd(cmd)

    def _vmd_draw_one(self, atoms, a1, a2, gap, radius, color_hex, mat, h_type, log=True):
        if self._vmd_port is None:
            return False
        a1_idx = int(a1) - 1
        a2_idx = int(a2) - 1
        if a1_idx >= len(atoms) or a2_idx >= len(atoms):
            return False
        pos1 = atoms[a1_idx][3]
        pos2 = atoms[a2_idx][3]
        x1, y1, z1 = pos1
        x2, y2, z2 = pos2

        vmd_color = self._hex_to_vmd_color(color_hex)
        h_resol = 6
        dx, dy, dz = x2 - x1, y2 - y1, z2 - z1
        length = (dx*dx + dy*dy + dz*dz) ** 0.5
        if length < 0.001:
            return False

        n_bars = max(1, int(length / gap))
        ratio = 0.7
        self._send_vmd_cmd(f"graphics top color {vmd_color}; graphics top material {mat}")

        if h_type == "dots":
            for i in range(n_bars):
                t = (i + 0.5) / n_bars
                cx, cy, cz = x1+dx*t, y1+dy*t, z1+dz*t
                self._send_vmd_cmd(f"graphics top sphere {{{cx} {cy} {cz}}} radius {radius} resolution 12")
        elif h_type == "pymol":
            seg_len = length / n_bars
            piece_len = seg_len * ratio
            for i in range(n_bars):
                t0 = i * seg_len / length
                t1 = t0 + piece_len / length
                self._send_vmd_cmd(f"graphics top cylinder {{{x1+dx*t0} {y1+dy*t0} {z1+dz*t0}}} {{{x1+dx*t1} {y1+dy*t1} {z1+dz*t1}}} radius {radius} resolution {h_resol}")
        elif h_type == "cylinder":
            seg_len = length / n_bars
            piece_len = seg_len * ratio
            for i in range(n_bars):
                t0 = i * seg_len / length
                t1 = t0 + piece_len / length
                self._send_vmd_cmd(f"graphics top cylinder {{{x1+dx*t0} {y1+dy*t0} {z1+dz*t0}}} {{{x1+dx*t1} {y1+dy*t1} {z1+dz*t1}}} radius {radius} resolution {h_resol}")
        elif h_type == "sphere":
            for i in range(n_bars):
                t = (i + 0.5) / n_bars
                cx, cy, cz = x1+dx*t, y1+dy*t, z1+dz*t
                self._send_vmd_cmd(f"graphics top sphere {{{cx} {cy} {cz}}} radius {radius} resolution 12")
        elif h_type == "cone":
            seg_len = length / n_bars
            piece_len = seg_len * ratio
            for i in range(n_bars):
                t0 = i * seg_len / length
                t1 = t0 + piece_len / length
                self._send_vmd_cmd(f"graphics top cone {{{x1+dx*t0} {y1+dy*t0} {z1+dz*t0}}} {{{x1+dx*t1} {y1+dy*t1} {z1+dz*t1}}} radius {radius} resolution {h_resol}")
        elif h_type == "line":
            seg_len = length / n_bars
            piece_len = seg_len * ratio
            for i in range(n_bars):
                t0 = i * seg_len / length
                t1 = t0 + piece_len / length
                self._send_vmd_cmd(f"graphics top line {{{x1+dx*t0} {y1+dy*t0} {z1+dz*t0}}} {{{x1+dx*t1} {y1+dy*t1} {z1+dz*t1}}}")

        if log:
            self._log(self.L.get("log_dash_synced", f"Dash synced: atom {a1} – {a2}"), "#a8d8a8")
        return True

    def _hex_to_vmd_color(self, hex_str):
        """将 #rrggbb 转为最接近的 VMD 内建颜色名。"""
        if not hex_str.startswith('#'):
            return hex_str
        r = int(hex_str[1:3], 16) / 255.0
        g = int(hex_str[3:5], 16) / 255.0
        b = int(hex_str[5:7], 16) / 255.0
        named = [
            (0.00, 0.00, 0.00, "black"), (1.00, 1.00, 1.00, "white"),
            (1.00, 0.00, 0.00, "red"),    (0.00, 1.00, 0.00, "green"),
            (0.00, 0.00, 1.00, "blue"),   (1.00, 1.00, 0.00, "yellow"),
            (0.00, 1.00, 1.00, "cyan"),   (1.00, 0.00, 1.00, "magenta"),
            (0.50, 0.50, 0.50, "gray"),   (1.00, 0.50, 0.00, "orange"),
        ]
        best, best_d = "black", 999.0
        for nr, ng, nb, name in named:
            d = (r - nr) ** 2 + (g - ng) ** 2 + (b - nb) ** 2
            if d < best_d:
                best, best_d = name, d
        return best

    def _render_view(self):
        L = self.L
        if self._vmd_port is None:
            QMessageBox.warning(self, L["warn_title"], L["err_no_vmd"])
            return
        resolution = self._get_resolution()
        cubs = self._get_selected_cubs()
        stem = os.path.splitext(os.path.basename(cubs[0]))[0] if cubs else "render"
        work_dir = os.path.dirname(cubs[0]) if cubs else "."
        output_png = os.path.join(work_dir, f"{stem}.png")
        trans_raster = self.chk_trans_raster.isChecked()
        try:
            threads = int(self.txt_threads.text())
        except ValueError:
            threads = 8
        self._log(L["log_render_view_start"], "#ce9178")

        def worker():
            png = render_current_view(self._vmd_port, self._vmd_render_dir, output_png,
                                      self.tachyon_path, resolution, self._get_style(),
                                      self._get_shade(),
                                      trans_raster=trans_raster, threads=threads)
            if png and os.path.exists(png):
                self._log(L["log_render_ok"] + png + "\n", "#4ec9b0")
                try:
                    os.startfile(png)
                except Exception:
                    pass
            else:
                self._log(L["log_render_fail"], "#f44336")
        threading.Thread(target=worker, daemon=True).start()

    def _auto_render_all(self):
        L = self.L
        cubs = self._get_selected_cubs()
        if not cubs:
            QMessageBox.warning(self, L["warn_title"], L["err_no_cub_for_render"])
            return
        iso = self._get_isovalue()
        resolution = self._get_resolution()
        style = self._get_style()
        shade = self._get_shade()
        vmd_exe = self.vmd_path
        tach_exe = self.tachyon_path
        trans_raster = self.chk_trans_raster.isChecked()
        try:
            threads = int(self.txt_threads.text())
        except ValueError:
            threads = 4

        show_h_texts = [L.get("show_h", "Show All H"), "Show All H", "显示所有H"]
        h_str = self.txt_h_indices.text().strip() if hasattr(self, 'txt_h_indices') else ""
        btn_text = self.btn_h_filter.text() if hasattr(self, 'btn_h_filter') else ""
        if btn_text in show_h_texts:
            if h_str:
                try:
                    keep_h_indices = [int(x.strip()) for x in h_str.split(",") if x.strip()]
                except ValueError:
                    keep_h_indices = []
            else:
                keep_h_indices = []
        else:
            keep_h_indices = None

        self._log(L["log_auto_render_start"].format(len(cubs)), "#ce9178")

        def worker():
            for i, cub in enumerate(cubs):
                stem = os.path.splitext(os.path.basename(cub))[0]
                output_png = os.path.splitext(cub)[0] + ".png"
                self._log(L["log_auto_render_item"].format(i + 1, len(cubs), os.path.basename(cub)), "#dcdcaa")
                try:
                    png = render_cub_auto(cub, output_png, iso, style, resolution,
                                          vmd_exe, tach_exe, shade,
                                          keep_h_indices=keep_h_indices,
                                          trans_raster=trans_raster, threads=threads)
                    if png:
                        self._log("    -> " + png + "\n", "#4ec9b0")
                    else:
                        self._log("    Failed\n", "#f44336")
                except Exception as e:
                    self._log(f"    Error: {e}\n", "#f44336")
            self._log(L["log_auto_render_done"], "#4ec9b0")
        threading.Thread(target=worker, daemon=True).start()

    def _send_vmd_cmd(self, cmd):
        if self._vmd_port is None:
            return None
        try:
            sock = getattr(self, '_vmd_persist_sock', None)
            if sock is None:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                sock.connect(("127.0.0.1", self._vmd_port))
                self._vmd_persist_sock = sock
            sock.sendall((cmd + "\n").encode("utf-8"))
            resp = b""
            try:
                sock.settimeout(0.5)
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    resp += chunk
                    if b"\n" in resp:
                        break
            except socket.timeout:
                pass
            sock.settimeout(5)
            return resp.decode("utf-8", errors="replace").strip()
        except Exception:
            self._close_persist_sock()
            return None

    def _close_persist_sock(self):
        sock = getattr(self, '_vmd_persist_sock', None)
        if sock:
            try:
                sock.close()
            except Exception:
                pass
            self._vmd_persist_sock = None

    def _refresh_vmd_nocv(self, cub_path):
        """Try to refresh running VMD by loading a new cube via socket, without restarting VMD.
        
        Deletes all existing molecules, copies new cube into VMD's render_dir,
        generates _refresh_nocv.tcl (same as initial scene, no socket server),
        and sources it. Returns True on success, False if caller should fall back to preview_cub.
        """
        if self._vmd_port is None:
            return False
        
        cub_name = os.path.basename(cub_path)
        render_dir = getattr(self, '_vmd_render_dir', None)
        if not render_dir or not os.path.isdir(render_dir):
            return False
        
        # Copy cube to render_dir for relative-path TCL sourcing
        try:
            dst_cube = os.path.join(render_dir, cub_name)
            shutil.copy2(cub_path, dst_cube)
        except (OSError, shutil.SameFileError):
            pass   # cube already in place, continue
        
        # Generate scene TCL (same as first launch, but without socket server & draw_bond helpers)
        style_tcl = _style_tcl(cub_name, self._get_isovalue(), self._get_style(), self._get_shade())
        refresh_path = os.path.join(render_dir, "_refresh_nocv.tcl")
        with open(refresh_path, "w") as f:
            f.write(style_tcl)
        
        # Delete old molecules, cd to render_dir, source new scene
        for step, cmd in [
            ("delete", "while {[molinfo num] > 0} {mol delete top}"),
            ("cd",     f"cd {{{render_dir}}}"),
            ("source", "source _refresh_nocv.tcl"),
            ("view",   "display resetview"),
        ]:
            resp = self._send_vmd_cmd(cmd)
            if resp is None or "ERROR" in resp.upper():
                if step == "delete":
                    continue   # "no molecules to delete" is benign
                self._log(f"[VMD Refresh] Failed at '{step}': {resp}\n", "#f44336")
                return False
        
        # Reset custom colour state — reps are recreated from scratch
        self._custom_pos_rgb = None
        self._custom_neg_rgb = None
        self._update_color_buttons()
        return True

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_PageUp:
            self.current_iso = round(self.current_iso + self.iso_step, 4)
            self._apply_iso_change()
        elif event.key() == Qt.Key_PageDown:
            self.current_iso = max(0.001, round(self.current_iso - self.iso_step, 4))
            self._apply_iso_change()
        elif event.key() == Qt.Key_Home:
            if self.current_opacity is None:
                self.current_opacity = 0.75
            else:
                self.current_opacity = min(1.0, round(self.current_opacity + self.opacity_step, 2))
            self._apply_opacity_change()
        elif event.key() == Qt.Key_End:
            if self.current_opacity is None:
                self.current_opacity = 0.50
            else:
                self.current_opacity = max(0.05, round(self.current_opacity - self.opacity_step, 2))
            self._apply_opacity_change()
        else:
            super().keyPressEvent(event)

    def _on_iso_slider_changed(self, val):
        iso = val / 1000.0
        self.current_iso = iso
        self.txt_iso.blockSignals(True)
        self.txt_iso.setText(f"{iso:.4g}")
        self.txt_iso.blockSignals(False)
        if self._vmd_port is not None:
            self._send_vmd_cmd(f"mol modstyle 1 top Isosurface {iso} 0 0 0 1 1")
            self._send_vmd_cmd(f"mol modstyle 2 top Isosurface -{iso} 0 0 0 1 1")

    def _on_iso_text_changed(self):
        """User pressed Enter in the isovalue input — sync slider and update VMD."""
        try:
            val = float(self.txt_iso.text().strip())
            val = max(0.001, min(0.500, val))
        except ValueError:
            val = self.current_iso
            self.txt_iso.setText(f"{val:.4g}")
        self.current_iso = val
        self.iso_slider.blockSignals(True)
        self.iso_slider.setValue(int(val * 1000))
        self.iso_slider.blockSignals(False)
        self.txt_iso.setText(f"{val:.4g}")
        if self._vmd_port is not None:
            self._send_vmd_cmd(f"mol modstyle 1 top Isosurface {val} 0 0 0 1 1")
            self._send_vmd_cmd(f"mol modstyle 2 top Isosurface -{val} 0 0 0 1 1")

    def _on_opacity_slider_changed(self, val):
        op = val / 500.0
        self.current_opacity = op
        self.txt_opacity.blockSignals(True)
        self.txt_opacity.setText(f"{op:.4g}")
        self.txt_opacity.blockSignals(False)
        if self._vmd_port is not None:
            for mat in ["_nocv_pos", "_nocv_neg"]:
                self._send_vmd_cmd(f"material change opacity {mat} {op}")

    def _on_opacity_text_changed(self):
        """User pressed Enter in the opacity input — sync slider and update VMD."""
        try:
            val = float(self.txt_opacity.text().strip())
            val = max(0.002, min(1.000, val))
        except ValueError:
            val = self.current_opacity or 0.75
            self.txt_opacity.setText(f"{val:.4g}")
        self.current_opacity = val
        self.opacity_slider.blockSignals(True)
        self.opacity_slider.setValue(int(val * 500))
        self.opacity_slider.blockSignals(False)
        self.txt_opacity.setText(f"{val:.4g}")
        if self._vmd_port is not None:
            for mat in ["_nocv_pos", "_nocv_neg"]:
                self._send_vmd_cmd(f"material change opacity {mat} {val}")

    def _apply_iso_change(self):
        iso = self.current_iso
        self.txt_iso.blockSignals(True)
        self.txt_iso.setText(f"{iso:.4g}")
        self.txt_iso.blockSignals(False)
        self.iso_slider.blockSignals(True)
        self.iso_slider.setValue(int(iso * 1000))
        self.iso_slider.blockSignals(False)
        self._send_vmd_cmd(f"mol modstyle 1 top Isosurface {iso} 0 0 0 1 1")
        self._send_vmd_cmd(f"mol modstyle 2 top Isosurface -{iso} 0 0 0 1 1")
        self._log(self.L["log_iso_changed"].format(self.current_iso), "#dcdcaa")

    def _apply_opacity_change(self):
        op = self.current_opacity
        self.opacity_slider.blockSignals(True)
        self.opacity_slider.setValue(int(op * 500))
        self.opacity_slider.blockSignals(False)
        self.txt_opacity.blockSignals(True)
        self.txt_opacity.setText(f"{op:.4g}")
        self.txt_opacity.blockSignals(False)
        for mat in ["_nocv_pos", "_nocv_neg"]:
            self._send_vmd_cmd(f"material change opacity {mat} {op}")
        self._log(self.L["log_opa_changed"].format(self.current_opacity), "#dcdcaa")

    def _tick_progress(self):
        if self._progress_value < 90:
            self._progress_value += max(1, int((90 - self._progress_value) * 0.08))
            self.progress_bar.setValue(self._progress_value)

    def _save_image(self):
        L = self.L
        pixmap = self.mol_canvas.grab()
        path, _ = QFileDialog.getSaveFileName(self, L["dialog_save_image"], "molecule.png", L["dialog_image_filter"])
        if not path:
            return
        pixmap.save(path)
        self._log(L["log_image_saved"] + os.path.basename(path) + "\n", "#4ec9b0")

    def _copy_result(self):
        text = self.txt_log.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self._log(self.L["log_copied"], "#888")

    def _clear_log(self):
        L = self.L
        self.txt_log.clear()
        self.table_nocv2.setRowCount(0)
        if hasattr(self, 'task_log'):
            self.task_log.clear()
        self._nocv_rows = []
        self._cub_files = {}
        self._refresh_cub_list()
        self._log(L["log_ready_short"], "#888")

    def closeEvent(self, event):
        self._stop_analysis()
        self._progress_timer.stop()
        self._runner.kill()
        # Disconnect and terminate any lingering workers
        for attr in ('_calc_worker', '_cube_gen_worker'):
            old = getattr(self, attr, None)
            if old is not None:
                for sig_name in ('finished', 'error', 'log'):
                    sig = getattr(old, sig_name, None)
                    if sig is not None:
                        try:
                            sig.disconnect()
                        except (TypeError, RuntimeError):
                            pass
                if old.isRunning():
                    old.wait(3000)
                if old.isRunning():
                    old.terminate()
                    old.wait(1000)
        if self._mwfn_session is not None:
            self._mwfn_session.shutdown()
            self._mwfn_session = None
        if self._tmp_dir and os.path.isdir(self._tmp_dir):
            self._cleanup_tmp(self._tmp_dir)
        self._close_persist_sock()
        self._save_paths()
        event.accept()


# ============================================================
#  DashBondDialog — popup molecule canvas with dash bond editor
# ============================================================

class DashBondDialog(QDialog):
    """弹出式分子画布，带虚线键编辑控件，可同步到 VMD。"""

    _BOND_COLOR_ITEMS = [
        ("black",  "Black",  "黑色",   "#000000"),
        ("gray",   "Gray",   "灰色",   "#808080"),
        ("cyan",   "Cyan",   "青色",   "#00FFFF"),
        ("yellow", "Yellow", "黄色",   "#FFFF00"),
        ("red",    "Red",    "红色",   "#FF0000"),
        ("blue",   "Blue",   "蓝色",   "#0000FF"),
        ("green",  "Green",  "绿色",   "#00FF00"),
        ("white",  "White",  "白色",   "#FFFFFF"),
    ]
    _BOND_TYPE_ITEMS = [
        ("dots",     "Dots",          "圆点"),
        ("pymol",    "Dashed(pymol)", "PyMOL虚线"),
        ("cylinder", "Cylinder",      "圆柱"),
        ("cone",     "Cone",          "锥形"),
        ("line",     "Line",          "线段"),
    ]
    _BOND_MAT_MAP = {
        "Opaque": "Opaque", "Transparent": "Transparent",
        "50%Transparent": "HalfTransparent"}

    def __init__(self, viewer, parent=None):
        super().__init__(parent or viewer)
        self._viewer = viewer
        self._lang = viewer._lang
        self.L = viewer.L
        self._vmd_dash_pairs = []  # local tracking for this dialog's dashes
        self.setWindowTitle(self.L.get("dialog_dash_bond", "Dash Bond Editor"))
        self.resize(900, 650)
        self._build_ui()
        self._load_atoms()

    def _build_ui(self):
        L = self.L
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ── Row 1: Dash controls ──
        ctrl_row1 = QHBoxLayout()
        ctrl_row1.setSpacing(6)

        self.chk_dash = QCheckBox(L.get("chk_dash_mode", "Dash"))
        self.chk_dash.toggled.connect(self._on_dash_toggled)
        ctrl_row1.addWidget(self.chk_dash)

        ctrl_row1.addWidget(QLabel(L.get("lbl_bond_color", "Color")))
        self.var_color = QComboBox()
        self.var_color.setFixedWidth(80)
        idx_l = 2 if self._lang == "zh" else 1
        for it in self._BOND_COLOR_ITEMS:
            self.var_color.addItem(it[idx_l])
        self.var_color.setCurrentIndex(0)
        self.var_color.currentIndexChanged.connect(self._on_param_changed)
        ctrl_row1.addWidget(self.var_color)

        ctrl_row1.addWidget(QLabel(L.get("lbl_bond_type", "Type")))
        self.var_type = QComboBox()
        self.var_type.setFixedWidth(100)
        for it in self._BOND_TYPE_ITEMS:
            self.var_type.addItem(it[idx_l])
        self.var_type.setCurrentIndex(1)
        self.var_type.currentIndexChanged.connect(lambda i: (
            setattr(self.mol_canvas, 'dash_style', self._BOND_TYPE_ITEMS[i][0]),
            self.mol_canvas.update(), self._on_param_changed()))
        ctrl_row1.addWidget(self.var_type)

        ctrl_row1.addWidget(QLabel(L.get("lbl_bond_mat", "Mat")))
        self.var_mat = QComboBox()
        self.var_mat.addItems(list(self._BOND_MAT_MAP.keys()))
        self.var_mat.setCurrentText("Opaque")
        self.var_mat.setFixedWidth(120)
        self.var_mat.currentIndexChanged.connect(self._on_param_changed)
        ctrl_row1.addWidget(self.var_mat)

        ctrl_row1.addStretch()
        layout.addLayout(ctrl_row1)

        # ── Row 2: Sliders + undo/clear ──
        ctrl_row2 = QHBoxLayout()
        ctrl_row2.setSpacing(6)

        ctrl_row2.addWidget(QLabel(L.get("lbl_segments", "Seg")))
        self.nbars_slider = QSlider(Qt.Horizontal)
        self.nbars_slider.setRange(5, 100)
        self.nbars_slider.setValue(20)
        self.nbars_slider.setFixedWidth(80)
        self.nbars_slider.valueChanged.connect(self._on_nbars_slider)
        ctrl_row2.addWidget(self.nbars_slider)
        self.nbars_edit = QLineEdit("0.20")
        self.nbars_edit.setValidator(QDoubleValidator(0.05, 1.00, 2))
        self.nbars_edit.setMaximumWidth(42)
        self.nbars_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.nbars_edit.editingFinished.connect(self._on_nbars_edit)
        ctrl_row2.addWidget(self.nbars_edit)

        ctrl_row2.addWidget(QLabel(L.get("lbl_radius", "Rad")))
        self.radius_slider = QSlider(Qt.Horizontal)
        self.radius_slider.setRange(1, 50)
        self.radius_slider.setValue(6)
        self.radius_slider.setFixedWidth(80)
        self.radius_slider.valueChanged.connect(self._on_radius_slider)
        ctrl_row2.addWidget(self.radius_slider)
        self.radius_edit = QLineEdit("0.06")
        self.radius_edit.setValidator(QDoubleValidator(0.01, 0.50, 2))
        self.radius_edit.setMaximumWidth(42)
        self.radius_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.radius_edit.editingFinished.connect(self._on_radius_edit)
        ctrl_row2.addWidget(self.radius_edit)

        ctrl_row2.addStretch()

        self.btn_undo = QPushButton(L.get("btn_undo_dash", "Undo"))
        self.btn_undo.clicked.connect(self._undo_bond)
        ctrl_row2.addWidget(self.btn_undo)

        self.btn_clear = QPushButton(L.get("btn_clear_dash", "Clear"))
        self.btn_clear.clicked.connect(self._clear_bond)
        ctrl_row2.addWidget(self.btn_clear)

        layout.addLayout(ctrl_row2)

        # ── Canvas ──
        self.mol_canvas = MolCanvas(self)
        self.mol_canvas.setMinimumSize(600, 350)
        self.mol_canvas.dash_style = "pymol"
        self.mol_canvas.on_dash_added = self._on_canvas_dash_drawn
        layout.addWidget(self.mol_canvas, stretch=1)

        # ── Canvas controls ──
        canvas_toolbar = QHBoxLayout()
        canvas_toolbar.setSpacing(8)

        self.chk_shadows = QCheckBox(L["chk_shadows"])
        self.chk_shadows.setChecked(True)
        self.chk_shadows.toggled.connect(lambda v: setattr(self.mol_canvas, 'show_shadows', v) or self.mol_canvas.update())
        canvas_toolbar.addWidget(self.chk_shadows)

        self.chk_gradient = QCheckBox(L["chk_gradient"])
        self.chk_gradient.setChecked(True)
        self.chk_gradient.toggled.connect(lambda v: setattr(self.mol_canvas, 'bg_gradient', v) or self.mol_canvas.update())
        canvas_toolbar.addWidget(self.chk_gradient)

        canvas_toolbar.addWidget(QLabel(L.get("lbl_style", "Style")))
        self.combo_style = QComboBox()
        style_keys = list(STYLE_PRESETS.keys())
        style_names = [STYLE_PRESETS[k]["name"] for k in style_keys]
        self.combo_style.addItems(style_names)
        self.combo_style.setCurrentIndex(style_keys.index("HoukMol") if "HoukMol" in style_keys else 0)
        self.combo_style.currentIndexChanged.connect(lambda i: self.mol_canvas.set_style(style_keys[i]))
        self.combo_style.setFixedWidth(110)
        canvas_toolbar.addWidget(self.combo_style)

        btn_reset = QPushButton(L["btn_reset"])
        btn_reset.clicked.connect(lambda: self.mol_canvas.auto_fit() or self.mol_canvas.update())
        canvas_toolbar.addWidget(btn_reset)

        canvas_toolbar.addStretch()
        layout.addLayout(canvas_toolbar)

    def _load_atoms(self):
        """从主画布复制原子和键数据到弹窗画布。"""
        src = self._viewer.mol_canvas
        if src.atoms:
            import copy
            self.mol_canvas.atoms = copy.deepcopy(src.atoms)
            self.mol_canvas.bonds = copy.deepcopy(src.bonds)
            self.mol_canvas.fragments = getattr(src, 'fragments', {})
            self.mol_canvas.ring_vertices = getattr(src, 'ring_vertices', [])
            self.mol_canvas.ring_config = getattr(src, 'ring_config', {})
            self.mol_canvas.auto_fit()
            self.mol_canvas.update()
            # Restore selection state
            self.mol_canvas.selected_atom_names = getattr(src, 'selected_atom_names', [])
            self.mol_canvas.box_select_rect = None

    # ── Internal helpers ──

    def _resolve_bond_key(self, label, is_color=False):
        items = self._BOND_COLOR_ITEMS if is_color else self._BOND_TYPE_ITEMS
        for it in items:
            if label in (it[1], it[2]):
                return it[0]
        return "black" if is_color else "dots"

    def _get_color_hex(self):
        label = self.var_color.currentText()
        for it in self._BOND_COLOR_ITEMS:
            if label in (it[1], it[2]):
                return it[3]
        return "#000000"

    def _get_params(self):
        gap = self.nbars_slider.value() / 100.0
        radius = self.radius_slider.value() / 100.0
        color_hex = self._get_color_hex()
        mat = self._BOND_MAT_MAP.get(self.var_mat.currentText(), "Opaque")
        h_type = self._resolve_bond_key(self.var_type.currentText(), is_color=False)
        return gap, radius, color_hex, mat, h_type

    def _reapply_vmd(self):
        """用当前参数重新绘制 VMD 中的全部虚线。"""
        if self._viewer._vmd_port is None or not self._vmd_dash_pairs:
            return
        self._viewer._send_vmd_cmd("graphics top delete all")
        gap, radius, color, mat, h_type = self._get_params()
        for a1, a2 in self._vmd_dash_pairs:
            self._viewer._vmd_draw_one(
                self.mol_canvas.atoms, a1, a2, gap, radius, color, mat, h_type, log=False)

    # ── Slider / edit handlers ──

    def _on_nbars_slider(self, val):
        gap = val / 100.0
        self.nbars_edit.blockSignals(True)
        self.nbars_edit.setText(f"{gap:.2f}")
        self.nbars_edit.blockSignals(False)
        self._sync_canvas_dash()
        self._reapply_vmd()

    def _on_nbars_edit(self):
        try:
            gap = float(self.nbars_edit.text())
            gap = max(0.05, min(1.00, gap))
        except ValueError:
            return
        val = int(round(gap * 100))
        self.nbars_slider.blockSignals(True)
        self.nbars_slider.setValue(val)
        self.nbars_slider.blockSignals(False)
        self.nbars_edit.setText(f"{val/100.0:.2f}")
        self._sync_canvas_dash()
        self._reapply_vmd()

    def _on_radius_slider(self, val):
        r = val / 100.0
        self.radius_edit.blockSignals(True)
        self.radius_edit.setText(f"{r:.2f}")
        self.radius_edit.blockSignals(False)
        self._sync_canvas_dash()
        self._reapply_vmd()

    def _on_radius_edit(self):
        try:
            r = float(self.radius_edit.text())
            r = max(0.01, min(0.50, r))
        except ValueError:
            return
        val = int(round(r * 100))
        self.radius_slider.blockSignals(True)
        self.radius_slider.setValue(val)
        self.radius_slider.blockSignals(False)
        self.radius_edit.setText(f"{val/100.0:.2f}")
        self._sync_canvas_dash()
        self._reapply_vmd()

    def _on_param_changed(self):
        """颜色/材质变更 → 重绘 VMD 所有虚线。"""
        self._reapply_vmd()

    def _sync_canvas_dash(self):
        """将虚线参数同步到画布渲染样式。"""
        gap = self.nbars_slider.value() / 100.0
        self.mol_canvas.dash_dot_count = max(2, int(3.0 / gap))
        self.mol_canvas.dash_dot_radius = max(1, self.radius_slider.value())
        self.mol_canvas.repaint()

    # ── Dash mode / actions ──

    def _on_dash_toggled(self, enabled):
        self.mol_canvas.set_dash_bond_mode(enabled)

    def _undo_bond(self):
        self._viewer._send_vmd_cmd("graphics top delete all")
        if self._vmd_dash_pairs:
            self._vmd_dash_pairs.pop()
        gap, radius, color, mat, h_type = self._get_params()
        for a1, a2 in self._vmd_dash_pairs:
            self._viewer._vmd_draw_one(
                self.mol_canvas.atoms, a1, a2, gap, radius, color, mat, h_type, log=False)
        self.mol_canvas.undo_last_dash_line()

    def _clear_bond(self):
        self._viewer._send_vmd_cmd("graphics top delete all")
        self._vmd_dash_pairs.clear()
        self.mol_canvas.clear_dash_lines()

    def _on_canvas_dash_drawn(self, a1, a2):
        """画布画好一根虚线 → 同步到 VMD。"""
        gap, radius, color, mat, h_type = self._get_params()
        if self._viewer._vmd_draw_one(
                self.mol_canvas.atoms, a1, a2, gap, radius, color, mat, h_type):
            pair = (int(a1), int(a2))
            if pair not in self._vmd_dash_pairs:
                self._vmd_dash_pairs.append(pair)
