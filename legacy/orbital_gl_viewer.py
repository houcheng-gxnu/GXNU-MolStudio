"""
OpenGL Orbital Viewer Window
=============================
Standalone window wrapping OrbitalGLWidget with full style/isovalue controls.
Acts as a drop-in alternative to the VMD preview.
"""

import os

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QComboBox, QPushButton, QSlider, QGroupBox,
    QMessageBox, QFileDialog,
)
from PyQt5.QtCore import Qt
from file_dialogs import open_file, save_file
from PyQt5.QtGui import QDoubleValidator

try:
    from OpenGL.GL import *
    _HAS_OPENGL = True
except ImportError:
    _HAS_OPENGL = False

if _HAS_OPENGL:
    from orbital_gl_widget import OrbitalGLWidget
    from glsl_shaders import style_to_shader_params, parse_style_rgb

from fchk_orbital import STYLES

# Style name list for combobox
STYLE_NAMES = list(STYLES.keys())
STYLE_DISPLAY = [f"{k}  — {STYLES[k]['desc']}" for k in STYLES.keys()]


class OrbitalGLViewer(QMainWindow):
    """Standalone OpenGL orbital viewer window with controls."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GXNU MolStudio — OpenGL 实时渲染")
        self.resize(1200, 800)
        self.setMinimumSize(800, 500)

        self._current_cube_path = None
        self._gl_ready = _HAS_OPENGL

        self._setup_ui()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # ── Left: OpenGL viewport ──
        if self._gl_ready:
            self.gl_widget = OrbitalGLWidget(self)
            layout.addWidget(self.gl_widget, stretch=3)
        else:
            label = QLabel("PyOpenGL 未安装。请运行: pip install PyOpenGL")
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet("font-size: 18px; color: #999;")
            layout.addWidget(label, stretch=3)

        # ── Right: Control panel ──
        panel = QWidget()
        panel.setMaximumWidth(320)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(4, 4, 4, 4)
        panel_layout.setSpacing(8)

        # File loading
        grp_file = QGroupBox("文件")
        fl = QVBoxLayout(grp_file)
        hl = QHBoxLayout()
        self.var_cube_path = QLineEdit()
        self.var_cube_path.setPlaceholderText("选择 .cub 文件...")
        hl.addWidget(self.var_cube_path, stretch=1)
        btn_browse = QPushButton("...")
        btn_browse.setMaximumWidth(36)
        btn_browse.clicked.connect(self._browse_cube)
        hl.addWidget(btn_browse)
        fl.addLayout(hl)
        self.btn_load = QPushButton("加载并显示")
        self.btn_load.clicked.connect(self._load_cube)
        fl.addWidget(self.btn_load)
        panel_layout.addWidget(grp_file)

        # Style selection
        grp_style = QGroupBox("渲染风格")
        sl = QVBoxLayout(grp_style)
        self.var_style = QComboBox()
        self.var_style.addItems(STYLE_DISPLAY)
        self.var_style.setCurrentIndex(0)
        self.var_style.currentIndexChanged.connect(self._on_style_changed)
        sl.addWidget(self.var_style)
        panel_layout.addWidget(grp_style)

        # Isovalue control
        grp_iso = QGroupBox("等值面")
        il = QGridLayout(grp_iso)
        il.addWidget(QLabel("等值面:"), 0, 0)
        self.iso_slider = QSlider(Qt.Horizontal)
        self.iso_slider.setRange(1, 500)
        self.iso_slider.setValue(50)
        self.iso_slider.valueChanged.connect(self._on_iso_changed)
        il.addWidget(self.iso_slider, 0, 1)
        self.iso_edit = QLineEdit("0.050")
        self.iso_edit.setValidator(QDoubleValidator(0.005, 0.500, 4))
        self.iso_edit.setMaximumWidth(70)
        self.iso_edit.editingFinished.connect(self._on_iso_edit)
        il.addWidget(self.iso_edit, 0, 2)

        il.addWidget(QLabel("不透明度:"), 1, 0)
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(5, 100)
        self.opacity_slider.setValue(75)
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        il.addWidget(self.opacity_slider, 1, 1)
        self.opacity_edit = QLineEdit("0.75")
        self.opacity_edit.setValidator(QDoubleValidator(0.05, 1.00, 2))
        self.opacity_edit.setMaximumWidth(70)
        self.opacity_edit.editingFinished.connect(self._on_opacity_edit)
        il.addWidget(self.opacity_edit, 1, 2)
        panel_layout.addWidget(grp_iso)

        # Ball-and-stick control
        grp_bs = QGroupBox("球棍模型")
        bl = QGridLayout(grp_bs)
        bl.addWidget(QLabel("原子半径:"), 0, 0)
        self.atom_scale_slider = QSlider(Qt.Horizontal)
        self.atom_scale_slider.setRange(20, 300)   # ×0.2 .. ×3.0
        self.atom_scale_slider.setValue(100)        # ×1.0
        self.atom_scale_slider.valueChanged.connect(self._on_atom_scale_changed)
        bl.addWidget(self.atom_scale_slider, 0, 1)
        self.atom_scale_edit = QLineEdit("1.00")
        self.atom_scale_edit.setValidator(QDoubleValidator(0.20, 3.00, 2))
        self.atom_scale_edit.setMaximumWidth(70)
        self.atom_scale_edit.editingFinished.connect(self._on_atom_scale_edit)
        bl.addWidget(self.atom_scale_edit, 0, 2)

        bl.addWidget(QLabel("化学键:"), 1, 0)
        self.bond_scale_slider = QSlider(Qt.Horizontal)
        self.bond_scale_slider.setRange(20, 300)    # ×0.2 .. ×3.0
        self.bond_scale_slider.setValue(100)        # ×1.0
        self.bond_scale_slider.valueChanged.connect(self._on_bond_scale_changed)
        bl.addWidget(self.bond_scale_slider, 1, 1)
        self.bond_scale_edit = QLineEdit("1.00")
        self.bond_scale_edit.setValidator(QDoubleValidator(0.20, 3.00, 2))
        self.bond_scale_edit.setMaximumWidth(70)
        self.bond_scale_edit.editingFinished.connect(self._on_bond_scale_edit)
        bl.addWidget(self.bond_scale_edit, 1, 2)
        panel_layout.addWidget(grp_bs)

        # Bond detection thresholds (ported from IboView BondRadiusFactor)
        grp_brf = QGroupBox("成键阈值")
        brfl = QGridLayout(grp_brf)
        brfl.addWidget(QLabel("实线键:"), 0, 0)
        self.brf_tight_slider = QSlider(Qt.Horizontal)
        self.brf_tight_slider.setRange(50, 200)   # ×0.50 .. ×2.00
        self.brf_tight_slider.setValue(100)         # ×1.00 (default)
        self.brf_tight_slider.valueChanged.connect(self._on_brf_tight_changed)
        brfl.addWidget(self.brf_tight_slider, 0, 1)
        self.brf_tight_edit = QLineEdit("1.00")
        self.brf_tight_edit.setValidator(QDoubleValidator(0.50, 2.00, 2))
        self.brf_tight_edit.setMaximumWidth(70)
        self.brf_tight_edit.editingFinished.connect(self._on_brf_tight_edit)
        brfl.addWidget(self.brf_tight_edit, 0, 2)

        brfl.addWidget(QLabel("虚线键:"), 1, 0)
        self.brf_loose_slider = QSlider(Qt.Horizontal)
        self.brf_loose_slider.setRange(50, 300)   # ×0.50 .. ×3.00
        self.brf_loose_slider.setValue(130)         # ×1.30 (IboView default)
        self.brf_loose_slider.valueChanged.connect(self._on_brf_loose_changed)
        brfl.addWidget(self.brf_loose_slider, 1, 1)
        self.brf_loose_edit = QLineEdit("1.30")
        self.brf_loose_edit.setValidator(QDoubleValidator(0.50, 3.00, 2))
        self.brf_loose_edit.setMaximumWidth(70)
        self.brf_loose_edit.editingFinished.connect(self._on_brf_loose_edit)
        brfl.addWidget(self.brf_loose_edit, 1, 2)

        brfl.addWidget(QLabel("虚线密度:"), 2, 0)
        self.dash_weight_slider = QSlider(Qt.Horizontal)
        self.dash_weight_slider.setRange(5, 100)    # 0.05 .. 1.00
        self.dash_weight_slider.setValue(40)         # 0.40 (IboView default)
        self.dash_weight_slider.valueChanged.connect(self._on_dash_weight_changed)
        brfl.addWidget(self.dash_weight_slider, 2, 1)
        self.dash_weight_edit = QLineEdit("0.40")
        self.dash_weight_edit.setValidator(QDoubleValidator(0.05, 1.00, 2))
        self.dash_weight_edit.setMaximumWidth(70)
        self.dash_weight_edit.editingFinished.connect(self._on_dash_weight_edit)
        brfl.addWidget(self.dash_weight_edit, 2, 2)
        panel_layout.addWidget(grp_brf)

        # Peeling layers
        grp_dp = QGroupBox("透明层数")
        dpl = QHBoxLayout(grp_dp)
        self.var_dp_layers = QComboBox()
        self.var_dp_layers.addItems(["2", "3", "4", "5", "6"])
        self.var_dp_layers.setCurrentIndex(2)  # 4 layers default
        self.var_dp_layers.currentIndexChanged.connect(self._on_dp_layers_changed)
        dpl.addWidget(QLabel("Depth Peeling:"))
        dpl.addWidget(self.var_dp_layers)
        dpl.addStretch()
        panel_layout.addWidget(grp_dp)

        # Screenshot
        grp_export = QGroupBox("导出")
        el = QVBoxLayout(grp_export)
        self.btn_screenshot = QPushButton("截取高清截图 (2x)")
        self.btn_screenshot.clicked.connect(self._screenshot)
        el.addWidget(self.btn_screenshot)
        panel_layout.addWidget(grp_export)

        # Quick actions
        grp_actions = QGroupBox("操作")
        al = QVBoxLayout(grp_actions)
        btn_reset = QPushButton("重置视角 (R)")
        btn_reset.clicked.connect(self._reset_view)
        al.addWidget(btn_reset)
        btn_fit = QPushButton("适配视图 (F)")
        btn_fit.clicked.connect(self._fit_view)
        al.addWidget(btn_fit)
        panel_layout.addWidget(grp_actions)

        panel_layout.addStretch()

        # Status
        self.status_label = QLabel("就绪 — 加载 .cub 文件开始")
        self.status_label.setStyleSheet("color: #888; font-size: 12px;")
        panel_layout.addWidget(self.status_label)

        layout.addWidget(panel)

    # ── Actions ────────────────────────────────────

    def load_cube_file(self, cube_path, isovalue=None, style_name=None):
        """Programmatic load: load cube file with optional settings."""
        if not self._gl_ready:
            return False

        if not os.path.exists(cube_path):
            QMessageBox.warning(self, "错误", f"文件不存在: {cube_path}")
            return False

        self._current_cube_path = cube_path
        self.var_cube_path.setText(cube_path)

        # Apply style
        if style_name and style_name in STYLES:
            idx = STYLE_NAMES.index(style_name)
            self.var_style.blockSignals(True)
            self.var_style.setCurrentIndex(idx)
            self.var_style.blockSignals(False)
        else:
            style_name = STYLE_NAMES[self.var_style.currentIndex()]

        # Apply isovalue
        if isovalue is not None:
            iso = max(0.005, min(isovalue, 0.500))
            self.iso_slider.blockSignals(True)
            self.iso_edit.blockSignals(True)
            self.iso_slider.setValue(int(iso * 1000))
            self.iso_edit.setText(f"{iso:.3f}")
            self.iso_slider.blockSignals(False)
            self.iso_edit.blockSignals(False)

        # Load into GL widget
        self.gl_widget.set_style(style_name)
        self.gl_widget.load_cube_file(cube_path, isovalue or 0.05)

        basename = os.path.basename(cube_path)
        self.status_label.setText(f"已加载: {basename} | 风格: {style_name}")
        return True

    def _browse_cube(self):
        path, _ = open_file(
            self, "选择 Cube 文件", "",
            "Cube Files (*.cub *.cube);;All Files (*)")
        if path:
            self.var_cube_path.setText(path)

    def _load_cube(self):
        path = self.var_cube_path.text().strip()
        if not path:
            QMessageBox.warning(self, "提示", "请选择 .cub 文件")
            return
        iso = float(self.iso_edit.text() or "0.05")
        style_name = STYLE_NAMES[self.var_style.currentIndex()]
        self.load_cube_file(path, iso, style_name)

    def _on_style_changed(self, idx):
        if not self._gl_ready or self._current_cube_path is None:
            return
        style_name = STYLE_NAMES[idx]
        self.gl_widget.set_style(style_name)

    def _on_iso_changed(self, val):
        if not self._gl_ready or self._current_cube_path is None:
            return
        iso = val / 1000.0
        self.iso_edit.blockSignals(True)
        self.iso_edit.setText(f"{iso:.3f}")
        self.iso_edit.blockSignals(False)
        self.gl_widget.set_isovalue(iso)

    def _on_iso_edit(self):
        if not self._gl_ready or self._current_cube_path is None:
            return
        try:
            iso = float(self.iso_edit.text())
        except ValueError:
            return
        iso = max(0.005, min(iso, 0.500))
        self.iso_slider.blockSignals(True)
        self.iso_slider.setValue(int(iso * 1000))
        self.iso_slider.blockSignals(False)
        self.gl_widget.set_isovalue(iso)

    def _on_opacity_changed(self, val):
        if not self._gl_ready or self._current_cube_path is None:
            return
        op = val / 100.0
        self.opacity_edit.blockSignals(True)
        self.opacity_edit.setText(f"{op:.2f}")
        self.opacity_edit.blockSignals(False)
        self.gl_widget.set_opacity(op)

    def _on_opacity_edit(self):
        if not self._gl_ready or self._current_cube_path is None:
            return
        try:
            op = float(self.opacity_edit.text())
        except ValueError:
            return
        op = max(0.05, min(op, 1.0))
        self.opacity_slider.blockSignals(True)
        self.opacity_slider.setValue(int(op * 100))
        self.opacity_slider.blockSignals(False)
        self.gl_widget.set_opacity(op)

    def _on_atom_scale_changed(self, val):
        if not self._gl_ready or self._current_cube_path is None:
            return
        s = val / 100.0
        self.atom_scale_edit.blockSignals(True)
        self.atom_scale_edit.setText(f"{s:.2f}")
        self.atom_scale_edit.blockSignals(False)
        self.gl_widget.set_atom_scale(s)

    def _on_atom_scale_edit(self):
        if not self._gl_ready or self._current_cube_path is None:
            return
        try:
            s = float(self.atom_scale_edit.text())
        except ValueError:
            return
        s = max(0.20, min(s, 3.00))
        self.atom_scale_slider.blockSignals(True)
        self.atom_scale_slider.setValue(int(s * 100))
        self.atom_scale_slider.blockSignals(False)
        self.gl_widget.set_atom_scale(s)

    def _on_bond_scale_changed(self, val):
        if not self._gl_ready or self._current_cube_path is None:
            return
        s = val / 100.0
        self.bond_scale_edit.blockSignals(True)
        self.bond_scale_edit.setText(f"{s:.2f}")
        self.bond_scale_edit.blockSignals(False)
        self.gl_widget.set_bond_scale(s)

    def _on_bond_scale_edit(self):
        if not self._gl_ready or self._current_cube_path is None:
            return
        try:
            s = float(self.bond_scale_edit.text())
        except ValueError:
            return
        s = max(0.20, min(s, 3.00))
        self.bond_scale_slider.blockSignals(True)
        self.bond_scale_slider.setValue(int(s * 100))
        self.bond_scale_slider.blockSignals(False)
        self.gl_widget.set_bond_scale(s)

    def _on_brf_tight_changed(self, val):
        if not self._gl_ready or self._current_cube_path is None:
            return
        v = val / 100.0
        self.brf_tight_edit.blockSignals(True)
        self.brf_tight_edit.setText(f"{v:.2f}")
        self.brf_tight_edit.blockSignals(False)
        self.gl_widget.set_bond_rf_tight(v)

    def _on_brf_tight_edit(self):
        if not self._gl_ready or self._current_cube_path is None:
            return
        try:
            v = float(self.brf_tight_edit.text())
        except ValueError:
            return
        v = max(0.50, min(v, 2.00))
        self.brf_tight_slider.blockSignals(True)
        self.brf_tight_slider.setValue(int(v * 100))
        self.brf_tight_slider.blockSignals(False)
        self.gl_widget.set_bond_rf_tight(v)

    def _on_brf_loose_changed(self, val):
        if not self._gl_ready or self._current_cube_path is None:
            return
        v = val / 100.0
        self.brf_loose_edit.blockSignals(True)
        self.brf_loose_edit.setText(f"{v:.2f}")
        self.brf_loose_edit.blockSignals(False)
        self.gl_widget.set_bond_rf_loose(v)

    def _on_brf_loose_edit(self):
        if not self._gl_ready or self._current_cube_path is None:
            return
        try:
            v = float(self.brf_loose_edit.text())
        except ValueError:
            return
        v = max(0.50, min(v, 3.00))
        self.brf_loose_slider.blockSignals(True)
        self.brf_loose_slider.setValue(int(v * 100))
        self.brf_loose_slider.blockSignals(False)
        self.gl_widget.set_bond_rf_loose(v)

    def _on_dash_weight_changed(self, val):
        if not self._gl_ready or self._current_cube_path is None:
            return
        v = val / 100.0
        self.dash_weight_edit.blockSignals(True)
        self.dash_weight_edit.setText(f"{v:.2f}")
        self.dash_weight_edit.blockSignals(False)
        self.gl_widget.set_dash_weight(v)

    def _on_dash_weight_edit(self):
        if not self._gl_ready or self._current_cube_path is None:
            return
        try:
            v = float(self.dash_weight_edit.text())
        except ValueError:
            return
        v = max(0.05, min(v, 1.00))
        self.dash_weight_slider.blockSignals(True)
        self.dash_weight_slider.setValue(int(v * 100))
        self.dash_weight_slider.blockSignals(False)
        self.gl_widget.set_dash_weight(v)

    def _on_dp_layers_changed(self, idx):
        if self._gl_ready:
            self.gl_widget.DEPTH_PEEL_LAYERS = int(self.var_dp_layers.currentText())
            self.gl_widget.update()

    def _reset_view(self):
        if self._gl_ready:
            self.gl_widget.reset_view()

    def _fit_view(self):
        if self._gl_ready:
            self.gl_widget.reset_view()

    def _screenshot(self):
        if not self._gl_ready or self._current_cube_path is None:
            return
        path, _ = save_file(
            self, "保存截图", "orbital_view.png",
            "PNG Images (*.png);;All Files (*)")
        if not path:
            return
        img = self.gl_widget.grab_image(
            self.gl_widget.width() * 2,
            self.gl_widget.height() * 2)
        img.save(path)
        self.status_label.setText(f"截图已保存: {os.path.basename(path)}")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)
