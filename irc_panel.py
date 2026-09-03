# -*- coding: utf-8 -*-
"""
irc_panel.py — IRC 整合分析面板（GXNU MolStudio 的一个 tab）

功能（整合自 D:\\IRC\\IRC_Integrated_Qt.py，适配 MolStudio 架构）：
  1. 批量读取 IRC 的 fchk 文件 → 提取 Total Energy（hartree）
  2. 调用 Multiwfn 逐点计算 Mayer 键级（带缓存，按 fchk 路径 MD5）
  3. matplotlib 双轴绘图：左轴=键级曲线，右轴=能量曲线
  4. 共享左侧 OpenGL 画布：任意 fchk 的结构可一键显示到画布
  5. 导出 CSV / 保存 PNG / 清除缓存 / 配置持久化

Multiwfn 键级调用（实测 2026.4.10）：
  ENTER → fchk → 9(键级) → 1(Mayer) → n(不输出 bndmat) → 0(返回) → q
输出表格式：  #    1:         1(C )    2(O )    2.24690074
"""

import os
import re
import json
import csv
import math
import hashlib
import subprocess

import numpy as np
from scipy.signal import savgol_filter
from scipy.interpolate import make_interp_spline

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QCheckBox, QFileDialog, QMessageBox, QGroupBox, QFrame,
    QScrollArea, QGridLayout, QListWidget, QListWidgetItem, QDialog,
    QAbstractItemView,
)
from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QColor

import matplotlib
matplotlib.use("Qt5Agg")
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from file_dialogs import existing_directory, save_file, open_file
from fchk_orbital import ELEMENT_SYMBOLS
from charge_viewer import CHARGE_TYPES, parse_multiwfn_charges

HARTREE_TO_EV = 27.2114
HARTREE_TO_KCAL = 627.509
BOHR_TO_ANGSTROM = 0.529177210903

BOND_COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
               "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]

COLOR_NAMES = {
    "#1f77b4": "蓝色 (Blue)", "#ff7f0e": "橙色 (Orange)",
    "#2ca02c": "绿色 (Green)", "#d62728": "红色 (Red)",
    "#9467bd": "紫色 (Purple)", "#8c564b": "棕色 (Brown)",
    "#e377c2": "粉色 (Pink)", "#7f7f7f": "灰色 (Gray)",
    "#bcbd22": "黄色 (Yellow)", "#17becf": "青色 (Cyan)",
}

# 原子半径（键判定用）
ATOM_RADII = {
    "H": 0.31, "He": 0.28, "Li": 1.28, "Be": 0.96, "B": 0.84,
    "C": 0.76, "N": 0.71, "O": 0.66, "F": 0.57, "Ne": 0.58,
    "Na": 1.66, "Mg": 1.41, "Al": 1.21, "Si": 1.11, "P": 1.07,
    "S": 1.05, "Cl": 1.02, "Ar": 1.06, "K": 2.03, "Ca": 1.76,
    "Fe": 1.32, "Co": 1.26, "Ni": 1.24, "Cu": 1.32, "Zn": 1.22,
    "Br": 1.2, "I": 1.39,
}


# ── fchk 解析（复用 Qt 版逻辑） ───────────────────────────────

def get_atoms_from_fchk(fchk_path):
    """从 fchk 解析原子（坐标 Bohr → Å）。"""
    atoms = []
    with open(fchk_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    m_nums = re.search(
        r"Atomic numbers\s+I\s+N=\s+(\d+)\s*\n([\s\S]+?)(?=\n\w|\Z)", content)
    m_coords = re.search(
        r"Current cartesian coordinates\s+R\s+N=\s+(\d+)\s*\n"
        r"([\s\S]+?)(?=\n\w|\Z)", content)
    if not m_nums or not m_coords:
        return []
    atomic_nums = list(map(int, m_nums.group(2).split()))
    coords = list(map(float, m_coords.group(2).split()))
    for i, an in enumerate(atomic_nums):
        x = coords[i * 3] * BOHR_TO_ANGSTROM
        y = coords[i * 3 + 1] * BOHR_TO_ANGSTROM
        z = coords[i * 3 + 2] * BOHR_TO_ANGSTROM
        sym = ELEMENT_SYMBOLS.get(an, "E" + str(an))
        atoms.append((i + 1, sym, an, (x, y, z)))
    return atoms


def get_bonds_from_fchk(atoms):
    """原子半径判断键连。"""
    bonds = []
    for i in range(len(atoms)):
        idx1, sym1, _, (x1, y1, z1) = atoms[i]
        r1 = ATOM_RADII.get(sym1, 1.5)
        for j in range(i + 1, len(atoms)):
            idx2, sym2, _, (x2, y2, z2) = atoms[j]
            r2 = ATOM_RADII.get(sym2, 1.5)
            d = math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2 + (z1 - z2) ** 2)
            if d < r1 + r2 + 0.45:
                bonds.append((idx1, idx2))
    return bonds


def extract_energy_from_fchk(file_path):
    """提取 Total Energy（hartree）。"""
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        m = re.search(r"Total Energy\s+R\s+([-+]?\d+\.?\d*[Ee]?[-+]?\d*)",
                      content)
        if m:
            return float(m.group(1))
    except Exception:
        pass
    return None


def extract_bond_from_output(output, atom1, atom2):
    """从 Multiwfn 输出提取指定原子对的 Mayer 键级（按序号匹配）。"""
    try:
        a1, a2 = int(atom1), int(atom2)
        pat = (r"#\s+\d+:\s+" + str(a1) + r"\([^)]*\)\s+"
               + str(a2) + r"\([^)]*\)\s+([-+]?\d+\.?\d*)")
        m = re.search(pat, output)
        if m:
            return float(m.group(1))
        pat2 = (r"#\s+\d+:\s+" + str(a2) + r"\([^)]*\)\s+"
                + str(a1) + r"\([^)]*\)\s+([-+]?\d+\.?\d*)")
        m = re.search(pat2, output)
        if m:
            return float(m.group(1))
    except Exception:
        pass
    return None


def calculate_mayer_bond_order(fchk_path, multiwfn_path, cache_dir):
    """调用 Multiwfn 计算全部 Mayer 键级（带缓存），返回输出文本或 None。"""
    fchk_hash = hashlib.md5(fchk_path.encode()).hexdigest()[:8]
    cache_file = os.path.join(cache_dir, "mayer_%s.txt" % fchk_hash)
    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        if len(content) >= 100:
            return content
    if not multiwfn_path or not os.path.isfile(multiwfn_path):
        return None
    try:
        fchk_dir = os.path.dirname(os.path.abspath(fchk_path))
        fchk_name = os.path.basename(fchk_path)
        inputs = "\n" + fchk_name + "\n9\n1\nn\n0\nq\n"
        result = subprocess.run(
            [multiwfn_path], input=inputs, capture_output=True, text=True,
            encoding="utf-8", errors="replace", cwd=fchk_dir, timeout=300)
        output = result.stdout or ""
        if len(output) >= 100 and "Bond orders" in output:
            try:
                os.makedirs(cache_dir, exist_ok=True)
                with open(cache_file, "w", encoding="utf-8") as f:
                    f.write(output)
            except Exception:
                pass
            return output
    except Exception:
        pass
    return None


def calculate_atomic_charge(fchk_path, multiwfn_path, cache_dir, charge_type,
                            atom_idx):
    """调用 Multiwfn 计算指定类型电荷（带缓存），返回该原子电荷或 None。"""
    fchk_hash = hashlib.md5(fchk_path.encode()).hexdigest()[:8]
    cache_file = os.path.join(cache_dir, "charge_%s_%s.txt"
                              % (fchk_hash, charge_type))
    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        if len(content) >= 100:
            return _extract_charge(content, charge_type, atom_idx)
    cfg = CHARGE_TYPES.get(charge_type)
    if not cfg or not multiwfn_path or not os.path.isfile(multiwfn_path):
        return None
    try:
        result = subprocess.run(
            [multiwfn_path, fchk_path], input=cfg["input_seq"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=300)
        output = result.stdout or ""
        if len(output) >= 100:
            try:
                os.makedirs(cache_dir, exist_ok=True)
                with open(cache_file, "w", encoding="utf-8") as f:
                    f.write(output)
            except Exception:
                pass
            return _extract_charge(output, charge_type, atom_idx)
    except Exception:
        pass
    return None


def _extract_charge(output, charge_type, atom_idx):
    """从电荷输出中提取指定原子的电荷。"""
    try:
        results = parse_multiwfn_charges(output, charge_type)
        for idx, _elem, chg in results:
            if idx == int(atom_idx):
                return float(chg)
    except Exception:
        pass
    return None


# ── 后台线程：批量键级计算 ────────────────────────────────────

class IrcBondWorker(QThread):
    """逐 fchk 计算指定原子对 Mayer 键级。"""
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)   # (当前, 总数)
    finished_signal = pyqtSignal(list)        # bond_values
    error_signal = pyqtSignal(str)

    def __init__(self, fchk_list, multiwfn_path, cache_dir, atom1, atom2,
                 parent=None):
        super().__init__(parent)
        self.fchk_list = fchk_list
        self.multiwfn_path = multiwfn_path
        self.cache_dir = cache_dir
        self.atom1 = atom1
        self.atom2 = atom2
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        values = []
        total = len(self.fchk_list)
        for i, fp in enumerate(self.fchk_list, 1):
            if not self._running:
                break
            self.progress_signal.emit(i, total)
            self.log_signal.emit(
                "  [%d/%d] %s" % (i, total, os.path.basename(fp)))
            out = calculate_mayer_bond_order(
                fp, self.multiwfn_path, self.cache_dir)
            if out:
                bo = extract_bond_from_output(out, self.atom1, self.atom2)
                if bo is not None:
                    values.append(bo)
                    self.log_signal.emit("    键级 = %.4f" % bo)
                    continue
                self.log_signal.emit("    键级解析失败")
            else:
                self.log_signal.emit("    计算失败")
            values.append(None)
        self.finished_signal.emit(values)


class IrcChargeWorker(QThread):
    """逐 fchk 计算指定原子的某类型电荷。"""
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)   # (当前, 总数)
    finished_signal = pyqtSignal(list)        # charge_values

    def __init__(self, fchk_list, multiwfn_path, cache_dir, charge_type,
                 atom_idx, parent=None):
        super().__init__(parent)
        self.fchk_list = fchk_list
        self.multiwfn_path = multiwfn_path
        self.cache_dir = cache_dir
        self.charge_type = charge_type
        self.atom_idx = atom_idx
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        values = []
        total = len(self.fchk_list)
        for i, fp in enumerate(self.fchk_list, 1):
            if not self._running:
                break
            self.progress_signal.emit(i, total)
            self.log_signal.emit(
                "  [%d/%d] %s" % (i, total, os.path.basename(fp)))
            chg = calculate_atomic_charge(
                fp, self.multiwfn_path, self.cache_dir,
                self.charge_type, self.atom_idx)
            if chg is not None:
                values.append(chg)
                self.log_signal.emit("    电荷 = %.4f" % chg)
            else:
                values.append(None)
                self.log_signal.emit("    失败")
        self.finished_signal.emit(values)


# ── 面板 ─────────────────────────────────────────────────────

class IrcPanel(QWidget):
    """IRC 整合分析面板（右侧 tab；共享左侧 OpenGL 画布显示分子）。"""

    def __init__(self, glw=None, multiwfn_path="", log_func=None, parent=None):
        super().__init__(parent)
        self.glw = glw
        self.multiwfn_path = multiwfn_path
        self._log = log_func or (lambda m: None)

        self.energy_values = []        # hartree
        self.fchk_files_fullpath = []
        self.all_bond_data = []        # {"name","values","color",...} 键级曲线
        self.all_charge_data = []      # 电荷曲线（与键级互斥，二选一）
        self._charge_type = "Mulliken"
        self.is_flipped = False
        self._selected_pt = None       # 当前选中的 IRC 点（原 fchk 索引）
        self._irc_figure = None
        self._irc_canvas = None
        self._legend = None            # 图例（可拖拽）
        self._legend_cids = []
        self._ldrag = False
        self._ldrag_start = (0, 0)
        self._ldrag_orig = (0, 0)
        self.cache_dir = os.path.join(os.getcwd(), "_mayer_cache")
        self._bond_worker = None

        self._build_ui()
        self._load_settings()

    # ── UI ──
    def showEvent(self, event):
        """切到本 tab 时按实际宽度重绘（隐藏时 width() 不准确）。"""
        super().showEvent(event)
        if self.energy_values:
            QTimer.singleShot(0, self._update_plot)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        # ── 图表（上方，占主要空间） ──
        self.fig_holder = QWidget()
        self._canvas_layout = QVBoxLayout(self.fig_holder)
        self._canvas_layout.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.fig_holder, stretch=1)

        # ── IRC 分析设置（下方，浅色渐变圆角卡片，对齐左侧画布下方面板） ──
        grp = QGroupBox("IRC 分析设置")
        grp.setObjectName("IrcSettingsBox")
        grp.setStyleSheet("""
            QGroupBox#IrcSettingsBox {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0 #FFFFFF, stop:1 #F1F5FB);
                border: 1px solid #D5DEE9;
                border-radius: 12px;
                margin-top: 14px;
            }
            QGroupBox#IrcSettingsBox::title {
                subcontrol-origin: margin;
                left: 14px;
                padding: 2px 10px;
                background-color: #1565C0;
                color: #FFFFFF;
                border-radius: 4px;
                font-weight: bold;
                font-size: 10pt;
            }
            QGroupBox#IrcSettingsBox QLineEdit {
                background: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 4px 8px;
            }
            QGroupBox#IrcSettingsBox QPushButton {
                background: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 4px 12px;
            }
            QGroupBox#IrcSettingsBox QPushButton:hover {
                background: #E8F1EF;
                border-color: #3E8E7E;
            }
        """)
        gl = QGridLayout(grp)
        gl.setContentsMargins(10, 8, 10, 10)
        gl.setHorizontalSpacing(8)
        gl.setVerticalSpacing(6)

        gl.addWidget(QLabel("fchk 目录:"), 0, 0)
        self.txt_dir = QLineEdit()
        self.txt_dir.setPlaceholderText("选择含 IRC 各步 fchk 的目录")
        gl.addWidget(self.txt_dir, 0, 1, 1, 2)
        btn_browse = QPushButton("浏览")
        btn_browse.clicked.connect(self._browse_dir)
        gl.addWidget(btn_browse, 0, 3)
        btn_read = QPushButton("读取能量")
        btn_read.clicked.connect(self._process_files)
        gl.addWidget(btn_read, 0, 4)

        gl.addWidget(QLabel("能量单位:"), 1, 0)
        self.combo_unit = QComboBox()
        self.combo_unit.addItems(["hartree", "eV", "kcal/mol"])
        self.combo_unit.currentIndexChanged.connect(self._on_display_changed)
        gl.addWidget(self.combo_unit, 1, 1)
        self.chk_relative = QCheckBox("相对能量（减最低点）")
        self.chk_relative.setChecked(True)
        self.chk_relative.toggled.connect(self._on_display_changed)
        gl.addWidget(self.chk_relative, 1, 2)
        self.btn_flip = QPushButton("翻转")
        self.btn_flip.setToolTip("镜像翻转能量/键级曲线（正/反方向 IRC）")
        self.btn_flip.clicked.connect(self._flip_data)
        gl.addWidget(self.btn_flip, 1, 3)

        gl.addWidget(QLabel("键级原子对:"), 2, 0)
        self.txt_atom1 = QLineEdit()
        self.txt_atom1.setPlaceholderText("原子1")
        self.txt_atom1.setMaximumWidth(70)
        gl.addWidget(self.txt_atom1, 2, 1)
        self.txt_atom2 = QLineEdit()
        self.txt_atom2.setPlaceholderText("原子2")
        self.txt_atom2.setMaximumWidth(70)
        gl.addWidget(self.txt_atom2, 2, 2)
        self.btn_add_bond = QPushButton("添加键级曲线")
        self.btn_add_bond.clicked.connect(self._add_bond)
        gl.addWidget(self.btn_add_bond, 2, 3, 1, 2)

        gl.addWidget(QLabel("结构显示:"), 3, 0)
        self.btn_show_mol = QPushButton("显示到画布…")
        self.btn_show_mol.clicked.connect(self._show_molecule)
        gl.addWidget(self.btn_show_mol, 3, 1)
        self.btn_export = QPushButton("导出 CSV")
        self.btn_export.clicked.connect(self._export_data)
        gl.addWidget(self.btn_export, 3, 2)
        self.btn_save_plot = QPushButton("保存图")
        self.btn_save_plot.clicked.connect(self._save_plot)
        gl.addWidget(self.btn_save_plot, 3, 3)
        self.btn_clear_cache = QPushButton("清缓存")
        self.btn_clear_cache.clicked.connect(self._clear_cache)
        gl.addWidget(self.btn_clear_cache, 3, 4)

        # ── 电荷曲线列表（管理/编辑/删除） ──
        gl.addWidget(QLabel("键级曲线:"), 4, 0)
        self.list_bonds = QListWidget()
        self.list_bonds.setFixedHeight(76)
        self.list_bonds.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list_bonds.itemDoubleClicked.connect(self._open_bond_settings)
        gl.addWidget(self.list_bonds, 4, 1, 1, 2)
        btn_edit = QPushButton("编辑…")
        btn_edit.clicked.connect(self._open_bond_settings)
        gl.addWidget(btn_edit, 4, 3)
        btn_del = QPushButton("删除")
        btn_del.clicked.connect(self._delete_bond)
        gl.addWidget(btn_del, 4, 4)

        # ── 电荷分析（与键级互斥：添加电荷时清空键级曲线） ──
        gl.addWidget(QLabel("电荷分析:"), 5, 0)
        self.combo_charge_type = QComboBox()
        for name, cfg in CHARGE_TYPES.items():
            self.combo_charge_type.addItem("%s (%s)" % (name, cfg["menu_path"]), name)
        self.combo_charge_type.setCurrentIndex(
            list(CHARGE_TYPES.keys()).index("Mulliken"))
        gl.addWidget(self.combo_charge_type, 5, 1)
        self.txt_charge_atom = QLineEdit()
        self.txt_charge_atom.setPlaceholderText("原子序号")
        self.txt_charge_atom.setMaximumWidth(70)
        gl.addWidget(self.txt_charge_atom, 5, 2)
        self.btn_add_charge = QPushButton("添加电荷曲线")
        self.btn_add_charge.clicked.connect(self._add_charge)
        gl.addWidget(self.btn_add_charge, 5, 3, 1, 2)

        # ── 图表设置（两行紧凑布局） ──
        row_chart1 = QWidget()
        rc1 = QHBoxLayout(row_chart1)
        rc1.setContentsMargins(0, 0, 0, 0)
        rc1.setSpacing(6)
        rc1.addWidget(QLabel("标题:"))
        self.txt_title = QLineEdit("IRC Reaction Profile")
        self.txt_title.textChanged.connect(self._on_display_changed)
        self.txt_title.returnPressed.connect(self._on_display_changed)
        rc1.addWidget(self.txt_title, 1)
        rc1.addWidget(QLabel("X 轴:"))
        self.txt_xlabel = QLineEdit("IRC Point")
        self.txt_xlabel.textChanged.connect(self._on_display_changed)
        self.txt_xlabel.returnPressed.connect(self._on_display_changed)
        rc1.addWidget(self.txt_xlabel, 1)
        gl.addWidget(row_chart1, 6, 0, 1, 5)

        row_chart2 = QWidget()
        rc2 = QHBoxLayout(row_chart2)
        rc2.setContentsMargins(0, 0, 0, 0)
        rc2.setSpacing(6)
        rc2.addWidget(QLabel("左 Y 轴:"))
        self.txt_ylabel_left = QLineEdit("Bond Order")
        self.txt_ylabel_left.textChanged.connect(self._on_display_changed)
        self.txt_ylabel_left.returnPressed.connect(self._on_display_changed)
        rc2.addWidget(self.txt_ylabel_left, 1)
        rc2.addWidget(QLabel("右 Y 轴:"))
        self.txt_ylabel_right = QLineEdit("Energy")
        self.txt_ylabel_right.textChanged.connect(self._on_display_changed)
        self.txt_ylabel_right.returnPressed.connect(self._on_display_changed)
        rc2.addWidget(self.txt_ylabel_right, 1)
        gl.addWidget(row_chart2, 7, 0, 1, 5)

        row_chart3 = QWidget()
        rc3 = QHBoxLayout(row_chart3)
        rc3.setContentsMargins(0, 0, 0, 0)
        rc3.setSpacing(6)
        self.chk_grid = QCheckBox("显示网格")
        self.chk_grid.setChecked(True)
        self.chk_grid.toggled.connect(self._on_display_changed)
        rc3.addWidget(self.chk_grid)
        self.chk_fill = QCheckBox("能量填充")
        self.chk_fill.setChecked(True)
        self.chk_fill.toggled.connect(self._on_display_changed)
        rc3.addWidget(self.chk_fill)
        rc3.addStretch(1)
        gl.addWidget(row_chart3, 8, 0, 1, 5)
        outer.addWidget(grp)

    # ── 配置持久化 ──
    def _settings_path(self):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "irc_panel_settings.ini")

    def _load_settings(self):
        import configparser
        cfg = configparser.ConfigParser()
        try:
            if os.path.exists(self._settings_path()):
                cfg.read(self._settings_path(), encoding="utf-8")
                if "irc" in cfg:
                    self.txt_dir.setText(cfg["irc"].get("dir", ""))
                    unit = cfg["irc"].get("unit", "hartree")
                    idx = self.combo_unit.findText(unit)
                    if idx >= 0:
                        self.combo_unit.setCurrentIndex(idx)
                    self.chk_relative.setChecked(
                        cfg["irc"].getboolean("relative", True))
        except Exception:
            pass

    def _save_settings(self):
        import configparser
        cfg = configparser.ConfigParser()
        cfg["irc"] = {
            "dir": self.txt_dir.text().strip(),
            "unit": self.combo_unit.currentText(),
            "relative": "1" if self.chk_relative.isChecked() else "0",
        }
        try:
            with open(self._settings_path(), "w", encoding="utf-8") as f:
                cfg.write(f)
        except Exception:
            pass

    # ── 能量批量提取 ──
    def _browse_dir(self):
        d = existing_directory(self, "选择 IRC fchk 目录", self.txt_dir.text())
        if d:
            self.txt_dir.setText(d)

    def _process_files(self):
        fchk_dir = self.txt_dir.text().strip()
        if not os.path.isdir(fchk_dir):
            QMessageBox.critical(self, "错误", "fchk 目录不存在!")
            return
        files = sorted([f for f in os.listdir(fchk_dir) if f.endswith(".fchk")])
        if not files:
            QMessageBox.critical(self, "错误", "目录中没有 .fchk 文件!")
            return
        self._log("IRC: 找到 %d 个 fchk 文件" % len(files))
        self.energy_values = []
        self.fchk_files_fullpath = []
        self._selected_pt = None   # 新数据：旧选中点失效
        self.all_bond_data = []    # 新数据：旧曲线失效
        self.all_charge_data = []
        for i, fn in enumerate(files, 1):
            fp = os.path.join(fchk_dir, fn)
            e = extract_energy_from_fchk(fp)
            if e is None:
                self._log("  警告: %s 能量提取失败，跳过" % fn)
                continue
            self.fchk_files_fullpath.append(fp)
            self.energy_values.append(e)
        self._log("IRC: 成功提取 %d 个能量数据点" % len(self.energy_values))
        self._save_settings()
        if self.fchk_files_fullpath:
            self._show_fchk_on_canvas(self.fchk_files_fullpath[0])
        self._update_plot()

    # ── 画布显示 ──
    def _show_fchk_on_canvas(self, path):
        if self.glw is None:
            return
        try:
            atoms = get_atoms_from_fchk(path)
            if not atoms:
                self._log("  结构解析失败: %s" % os.path.basename(path))
                return
            bonds = get_bonds_from_fchk(atoms)
            self.glw.set_molecule(atoms, bonds)
            self._log("画布显示: %s（%d 原子）"
                      % (os.path.basename(path), len(atoms)))
        except Exception as e:
            self._log("画布显示失败: %s" % e)

    def _show_molecule(self):
        if not self.fchk_files_fullpath:
            QMessageBox.warning(self, "提示", "请先读取目录中的能量数据。")
            return
        p, _ = open_file(self, "选择要显示的 fchk", "",
                         "fchk (*.fchk);;All (*.*)")
        if p:
            self._show_fchk_on_canvas(p)

    # ── 键级计算 ──
    def _add_bond(self):
        if not self.energy_values or not self.fchk_files_fullpath:
            QMessageBox.warning(self, "警告", "请先读取能量数据!")
            return
        a1 = self.txt_atom1.text().strip()
        a2 = self.txt_atom2.text().strip()
        if not a1 or not a2:
            QMessageBox.critical(self, "错误", "请输入两个原子标号!")
            return
        if self._bond_worker is not None and self._bond_worker.isRunning():
            QMessageBox.information(self, "提示", "键级计算正在进行，请稍候。")
            return
        self._log("IRC: 计算键级 %s-%s" % (a1, a2))
        self.btn_add_bond.setEnabled(False)
        self._bond_worker = IrcBondWorker(
            self.fchk_files_fullpath, self.multiwfn_path, self.cache_dir,
            a1, a2, parent=self)
        self._bond_worker.log_signal.connect(self._log)
        self._bond_worker.finished_signal.connect(
            lambda vals, a1=a1, a2=a2: self._on_bond_done(vals, a1, a2))
        self._bond_worker.error_signal.connect(
            lambda m: (self._log("IRC: " + str(m)),
                       setattr(self.btn_add_bond, "setEnabled", True)))
        self._bond_worker.start()

    def _on_bond_done(self, values, a1, a2):
        self.btn_add_bond.setEnabled(True)
        ok = sum(1 for v in values if v is not None)
        self._log("IRC: 键级 %s-%s 完成：%d/%d 成功"
                  % (a1, a2, ok, len(values)))
        # 互斥：添加键级时清空电荷曲线
        self.all_charge_data = []
        self.all_bond_data = []
        self.all_bond_data.append({
            "name": "%s-%s" % (a1, a2),
            "values": values,
            "color": BOND_COLORS[0],
            "linestyle": "-",
            "marker": "o",
        })
        self._update_bond_list()
        self._update_plot()

    # ── 电荷分析（与键级互斥） ─────────────────────────
    def _add_charge(self):
        if not self.energy_values or not self.fchk_files_fullpath:
            QMessageBox.warning(self, "警告", "请先读取能量数据!")
            return
        atom = self.txt_charge_atom.text().strip()
        if not atom:
            QMessageBox.critical(self, "错误", "请输入原子标号!")
            return
        ctype = self.combo_charge_type.currentData() or "Mulliken"
        if self._bond_worker is not None and self._bond_worker.isRunning():
            QMessageBox.information(self, "提示", "分析正在进行，请稍候。")
            return
        self._log("IRC: 计算电荷 %s（原子 %s）" % (ctype, atom))
        self.btn_add_charge.setEnabled(False)
        self._charge_worker = IrcChargeWorker(
            self.fchk_files_fullpath, self.multiwfn_path, self.cache_dir,
            ctype, atom, parent=self)
        self._charge_worker.log_signal.connect(self._log)
        self._charge_worker.finished_signal.connect(
            lambda vals: self._on_charge_done(vals, ctype, atom))
        self._charge_worker.start()

    def _on_charge_done(self, values, ctype, atom):
        self.btn_add_charge.setEnabled(True)
        ok = sum(1 for v in values if v is not None)
        self._log("IRC: 电荷 %s 原子 %s 完成：%d/%d 成功"
                  % (ctype, atom, ok, len(values)))
        # 与键级互斥（清键级），但电荷曲线可叠加多条
        self.all_bond_data = []
        self.all_charge_data.append({
            "name": "%s(原子%s)" % (ctype, atom),
            "values": values,
            "color": BOND_COLORS[(len(self.all_charge_data))
                                 % len(BOND_COLORS)],
            "linestyle": "-",
            "marker": "s",
            "charge_type": ctype,
        })
        self._update_bond_list()
        self._update_plot()

    # ── 键级列表管理（电荷/键级共用，互斥显示） ─────────
    def _current_data(self):
        """当前模式的数据列表（有电荷曲线显示电荷，否则键级）。"""
        if self.all_charge_data:
            return self.all_charge_data
        return self.all_bond_data

    def _update_bond_list(self):
        self.list_bonds.clear()
        data = self._current_data()
        for i, bd in enumerate(data):
            color = bd.get("color", "blue")
            valid = sum(1 for v in bd["values"] if v is not None)
            total = len(bd["values"])
            status = "\u2713" if valid == total else "!"
            item = QListWidgetItem("%s #%d %s (%d/%d)"
                                   % (status, i + 1, bd["name"],
                                      valid, total))
            item.setForeground(QColor(color))
            self.list_bonds.addItem(item)

    def _delete_bond(self):
        sel = self.list_bonds.currentRow()
        data = self._current_data()
        if sel < 0 or sel >= len(data):
            QMessageBox.warning(self, "提示", "请先选择要删除的曲线")
            return
        removed = data.pop(sel)
        self._update_bond_list()
        self._update_plot()
        self._log("IRC: 已删除 %s" % removed["name"])

    def _open_bond_settings(self, item=None):
        idx = self.list_bonds.currentRow()
        data = self._current_data()
        if idx < 0 or idx >= len(data):
            QMessageBox.warning(self, "提示", "请先选择要设置的曲线")
            return
        bd = data[idx]
        dlg = QDialog(self)
        dlg.setWindowTitle("设置曲线: %s" % bd["name"])
        dlg.setFixedSize(320, 280)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(10)

        r0 = QHBoxLayout()
        r0.addWidget(QLabel("名称:"))
        name_edit = QLineEdit(bd.get("name", ""))
        r0.addWidget(name_edit)
        lay.addLayout(r0)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("颜色:"))
        color_combo = QComboBox()
        for c in BOND_COLORS:
            color_combo.addItem("%s [%s]" % (COLOR_NAMES.get(c, c), c), c)
        cur = bd.get("color", BOND_COLORS[0])
        for i in range(color_combo.count()):
            if color_combo.itemData(i) == cur:
                color_combo.setCurrentIndex(i)
                break
        r1.addWidget(color_combo)
        lay.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("线型:"))
        ls_combo = QComboBox()
        ls_combo.addItems(["-", "--", "-.", ":"])
        ls_combo.setCurrentText(bd.get("linestyle", "-"))
        r2.addWidget(ls_combo)
        lay.addLayout(r2)

        r3 = QHBoxLayout()
        r3.addWidget(QLabel("点型:"))
        mk_combo = QComboBox()
        mk_combo.addItems(["o", "s", "^", "D", "None"])
        mk_combo.setCurrentText(bd.get("marker", "o"))
        r3.addWidget(mk_combo)
        lay.addLayout(r3)

        def apply():
            data[idx]["name"] = name_edit.text().strip() or bd["name"]
            data[idx]["color"] = color_combo.currentData()
            data[idx]["linestyle"] = ls_combo.currentText()
            data[idx]["marker"] = mk_combo.currentText()
            self._update_bond_list()
            self._update_plot()
            self._log("IRC: 已更新 %s" % data[idx]["name"])
            dlg.accept()

        btn = QPushButton("应用")
        btn.setStyleSheet("background:#1565C0; color:#FFFFFF;"
                          " border:none; border-radius:6px;"
                          " padding:6px 0; font-weight:bold;")
        btn.clicked.connect(apply)
        lay.addWidget(btn)
        dlg.exec_()

    # ── 图例拖拽（绕过 twinx 下失效的 pick，直接改 legend bbox） ──
    def _setup_legend_drag(self):
        if self._legend is None or self._irc_canvas is None:
            return
        for cid in getattr(self, "_legend_cids", []):
            try:
                self._irc_canvas.mpl_disconnect(cid)
            except Exception:
                pass
        self._legend_cids = []
        legend = self._legend
        canvas = self._irc_canvas
        fig = legend.figure

        def on_press(event):
            if event.button != 1:
                return
            try:
                bb = legend.get_window_extent(canvas.get_renderer())
                if bb.contains(event.x, event.y):
                    self._ldrag = True
                    self._ldrag_start = (event.x, event.y)
                    w, h = fig.get_size_inches() * fig.dpi
                    self._ldrag_orig = (bb.x0 / w, bb.y1 / h)
            except Exception:
                pass

        def on_motion(event):
            if not getattr(self, "_ldrag", False):
                return
            try:
                sx, sy = self._ldrag_start
                ox, oy = self._ldrag_orig
                w, h = fig.get_size_inches() * fig.dpi
                fx = ox + (event.x - sx) / w
                fy = oy + (event.y - sy) / h
                legend.set_bbox_to_anchor((fx, fy), transform=fig.transFigure)
                canvas.draw_idle()
            except Exception:
                pass

        def on_release(event):
            self._ldrag = False

        self._legend_cids.append(
            canvas.mpl_connect("button_press_event", on_press))
        self._legend_cids.append(
            canvas.mpl_connect("motion_notify_event", on_motion))
        self._legend_cids.append(
            canvas.mpl_connect("button_release_event", on_release))

    # ── 绘图 ──
    def _flip_data(self):
        self.is_flipped = not self.is_flipped
        self._update_plot()

    def _update_plot(self):
        if not self.energy_values:
            return
        try:
            while self._canvas_layout.count():
                item = self._canvas_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self._draw_plot()
        except Exception as e:
            self._log("IRC 绘图错误: %s" % e)
            import traceback
            self._log(traceback.format_exc())

    def _draw_plot(self):
        # 动态尺寸：匹配面板可用宽度（避免固定 825px 被缩放挤压导致轴标签被裁）
        avail_w = max(420, self.width() - 24)
        avail_h = max(300, self.height() - 260)
        dpi = 100.0
        fig = Figure(figsize=(avail_w / dpi, avail_h / dpi), dpi=dpi)
        ax1 = fig.add_subplot(111)
        ax2 = ax1.twinx()
        ax1.set_zorder(ax2.get_zorder() + 1)
        ax1.patch.set_visible(False)

        title = self.txt_title.text().strip() or "IRC Reaction Profile"
        xlabel = self.txt_xlabel.text().strip() or "IRC Point"
        ylabel_left = self.txt_ylabel_left.text().strip() or "Bond Order"
        ylabel_right = self.txt_ylabel_right.text().strip() or "Energy"

        unit = self.combo_unit.currentText()
        show_relative = self.chk_relative.isChecked()
        min_e = min(self.energy_values) if self.energy_values else 0
        plot_energy = []
        for e in self.energy_values:
            er = e - min_e if show_relative else e
            if unit == "eV":
                er *= HARTREE_TO_EV
            elif unit == "kcal/mol":
                er *= HARTREE_TO_KCAL
            plot_energy.append(er)

        x_idx = list(range(1, len(self.energy_values) + 1))
        # 数据源：有电荷曲线显示电荷，否则键级（互斥）
        if self.all_charge_data:
            curve_src = self.all_charge_data
            is_charge = True
            if self.txt_ylabel_left.text().strip() == "Bond Order":
                ylabel_left = "Charge (%s)" % self.all_charge_data[0].get(
                    "charge_type", self._charge_type)
        else:
            curve_src = self.all_bond_data
            is_charge = False
        if self.is_flipped:
            plot_energy = plot_energy[::-1]
            curve_plot = [dict(b, values=list(reversed(b["values"])))
                          for b in curve_src]
        else:
            curve_plot = curve_src

        # 键级/电荷曲线（左轴）
        has_curve = False
        for bd in curve_plot:
            vv = [v for v in bd["values"] if v is not None]
            xx = [x for x, v in zip(x_idx, bd["values"]) if v is not None]
            if vv:
                has_curve = True
                ax1.plot(xx, vv,
                         linestyle=bd.get("linestyle", "-"),
                         marker=bd.get("marker", "o"),
                         color=bd.get("color", "blue"), linewidth=2,
                         markersize=5, alpha=0.9, label=bd["name"])
        self._legend = None
        # 左轴标签：始终显示（电荷/键级按模式）
        ax1.set_ylabel(ylabel_left, fontsize=10, fontweight="bold",
                       color="#2C3E50")
        if has_curve:
            self._legend = ax1.legend(loc="upper left", fontsize=8,
                                      framealpha=0.85)

        # 能量（右轴）
        x_arr = np.array(x_idx, dtype=float)
        y_arr = np.array(plot_energy, dtype=float)
        if len(y_arr) >= 4:
            xs = np.linspace(x_arr.min(), x_arr.max(), len(x_arr) * 12)
            try:
                spl = make_interp_spline(x_arr, y_arr,
                                         k=min(3, len(x_arr) - 1))
                ys = spl(xs)
            except Exception:
                xs, ys = x_arr, y_arr
        else:
            xs, ys = x_arr, y_arr
        norm = __import__("matplotlib").pyplot.Normalize(
            y_arr.min(), y_arr.max())
        colors = __import__("matplotlib").pyplot.cm.RdYlBu_r(norm(y_arr))
        # 能量散点：可点击（picker），点击切换到对应 fchk 结构
        self._scatter = ax2.scatter(
            x_idx, plot_energy, c=colors, edgecolors="#6B7280",
            linewidth=0.5, s=50, alpha=0.85, zorder=5, picker=18)
        self._energy_xs = xs   # 平滑线 x 采样（线 pick 用）
        self._energy_line = ax2.plot(
            xs, ys, color="#374151", linewidth=2.0, alpha=0.85, zorder=4,
            picker=12)[0]
        if self.chk_fill.isChecked():
            y_base = float(np.min(ys))
            ax2.fill_between(xs, ys, y_base, alpha=0.08, color="#2563EB",
                             zorder=2)
        ax2.set_ylabel("%s (%s)" % (ylabel_right, unit),
                       fontsize=10, fontweight="bold")

        # 高亮当前选中的点（原 fchk 索引 → 图上位置，翻转时映射）
        if self._selected_pt is not None and 0 <= self._selected_pt \
                < len(self.energy_values):
            if self.is_flipped:
                plot_sel = len(self.energy_values) - 1 - self._selected_pt
            else:
                plot_sel = self._selected_pt
            sel_x = plot_sel + 1
            sel_y = plot_energy[plot_sel]
            ax2.scatter([sel_x], [sel_y], s=180, facecolors="none",
                        edgecolors="#E11D48", linewidths=2.0, zorder=6)
            ax2.annotate("%d" % (self._selected_pt + 1), (sel_x, sel_y),
                         textcoords="offset points", xytext=(0, 10),
                         ha="center", fontsize=9, color="#E11D48",
                         fontweight="bold")

        ax1.set_title(title, fontsize=12, fontweight="bold", pad=10)
        ax1.set_xlabel(xlabel, fontsize=10)
        ax1.tick_params(labelsize=8)
        ax2.tick_params(labelsize=8)
        # 网格开关：grid(False) 不能带样式参数，否则会被强制启用
        if self.chk_grid.isChecked():
            ax1.grid(True, which="major", linestyle="--", linewidth=0.5,
                     color="#CCCCCC", alpha=0.7)
        else:
            ax1.grid(False)
        # 边距：左/右给双轴标签留空间，避免标题/轴名被裁切
        fig.tight_layout(pad=1.2, w_pad=0.6, h_pad=0.8)

        canvas = FigureCanvas(fig)
        self._canvas_layout.addWidget(canvas)
        self._irc_figure = fig
        self._irc_canvas = canvas
        # matplotlib 3.10 移除了自动 pick 机制：用 button_press_event +
        # 手动 contains 检测（scatter / 能量线）实现点选
        fig.canvas.mpl_connect("button_press_event", self._on_canvas_click)
        # 图例拖拽（有键级曲线时才有效）
        self._setup_legend_drag()

    # ── 显示设置变化（单位/相对能量）即时重绘 ──
    def _on_display_changed(self):
        self._update_plot()

    # ── 点击 IRC 点 → 画布切换结构（手动 contains 检测） ──
    def _on_canvas_click(self, event):
        if event.button != 1:
            return   # 仅左键
        if not self.fchk_files_fullpath or event.inaxes is None:
            return
        try:
            n = len(self.energy_values)
            # 先检测能量散点（优先），再检测能量平滑线
            for artist, kind in ((self._scatter, "scatter"),
                                 (getattr(self, "_energy_line", None), "line")):
                if artist is None:
                    continue
                cont, ind = artist.contains(event)
                if not cont or not ind or not len(ind.get("ind", [])):
                    continue
                if kind == "scatter":
                    idx = int(ind["ind"][0])
                    orig = (n - 1 - idx) if self.is_flipped else idx
                else:
                    xs = getattr(self, "_energy_xs", None)
                    if xs is None or len(xs) == 0:
                        return
                    xv = float(xs[int(ind["ind"][0])])
                    orig = int(round(xv)) - 1
                    orig = max(0, min(n - 1, orig))
                if 0 <= orig < n:
                    self._selected_pt = orig
                    self._show_fchk_on_canvas(self.fchk_files_fullpath[orig])
                    self._log("IRC: 已切换到第 %d 个点 → %s"
                              % (orig + 1, os.path.basename(
                                  self.fchk_files_fullpath[orig])))
                    self._update_plot()          # 重绘高亮选中点
                return
        except Exception as e:
            self._log("IRC 点选失败: %s" % e)

    # ── 导出 / 保存 ──
    def _export_data(self):
        if not self.energy_values:
            QMessageBox.warning(self, "警告", "没有数据可导出!")
            return
        p, _ = save_file(self, "导出 IRC 数据", "irc_data.csv",
                         "CSV (*.csv)")
        if not p:
            return
        try:
            with open(p, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                headers = ["IRC Point", "Energy (hartree)"]
                data = self._current_data()
                for bd in data:
                    headers.append(bd["name"])
                w.writerow(headers)
                for i in range(len(self.energy_values)):
                    row = [i + 1, self.energy_values[i]]
                    for bd in data:
                        row.append(bd["values"][i])
                    w.writerow(row)
            self._log("IRC: 数据已导出 %s" % p)
        except Exception as e:
            self._log("导出失败: %s" % e)

    def _save_plot(self):
        if self._irc_figure is None:
            QMessageBox.warning(self, "警告", "没有图表可保存!")
            return
        p, _ = save_file(self, "保存 IRC 图表", "IRC_plot.png",
                         "PNG (*.png);;JPG (*.jpg);;TIF (*.tif)")
        if not p:
            return
        try:
            self._irc_figure.savefig(p, dpi=300, bbox_inches="tight")
            self._log("IRC: 图表已保存 %s" % p)
        except Exception as e:
            self._log("保存图表失败: %s" % e)

    def _clear_cache(self):
        import glob
        files = glob.glob(os.path.join(self.cache_dir, "mayer_*.txt"))
        for f in files:
            try:
                os.remove(f)
            except Exception:
                pass
        self._log("IRC: 已清除 %d 个键级缓存" % len(files))

    def shutdown(self):
        """关闭时停止后台线程。"""
        for w in (getattr(self, "_bond_worker", None),
                  getattr(self, "_charge_worker", None)):
            if w is not None:
                try:
                    w.stop()
                    w.wait(2000)
                except Exception:
                    pass
