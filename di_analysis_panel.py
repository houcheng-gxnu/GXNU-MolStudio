# -*- coding: utf-8 -*-
"""
di_analysis_panel.py — Distortion-Interaction 能量分解分析面板（GXNU MolStudio 的一个 tab）

功能（整合自 D:\\traetest\\DI分析\\di_analysis_gui.py，适配 MolStudio 架构）：
  1. 5 个 Gaussian .log（frag1_opt / frag2_opt / frag1_def / frag2_def / ts）
     自动提取 SCF 能量，支持 ZPE / Gibbs 修正
  2. 计算 ΔE_strain、ΔE_int、ΔE#，表格红绿着色显示（Hartree + kcal/mol）
  3. matplotlib 双图嵌入：左侧 DI 能量阶梯箭头图 + 右侧分解柱状图
  4. 共享左侧 OpenGL 画布：任意结构的 log / fchk 可一键显示到画布
  5. 导出 HTML 报告 / 配置持久化

能量公式：
  ΔE_strain = (E_def1 − E_opt1) + (E_def2 − E_opt2)
  ΔE_int    = E_TS − E_def1 − E_def2
  ΔE‡       = ΔE_strain + ΔE_int
"""

import os
import re
import math
import configparser

import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QCheckBox, QMessageBox, QGroupBox, QFileDialog, QGridLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont

import matplotlib
matplotlib.use("Qt5Agg")
import matplotlib as _mpl
_mpl.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
_mpl.rcParams["axes.unicode_minus"] = False
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle, Patch

from file_dialogs import open_file, open_files, save_file, existing_directory
from fchk_orbital import ELEMENT_SYMBOLS

HARTREE_TO_KCAL = 627.509
BOHR_TO_ANGSTROM = 0.529177210903

# 原子半径（键判定用）
ATOM_RADII = {
    "H": 0.31, "He": 0.28, "Li": 1.28, "Be": 0.96, "B": 0.84,
    "C": 0.76, "N": 0.71, "O": 0.66, "F": 0.57, "Ne": 0.58,
    "Na": 1.66, "Mg": 1.41, "Al": 1.21, "Si": 1.11, "P": 1.07,
    "S": 1.05, "Cl": 1.02, "Ar": 1.06, "K": 2.03, "Ca": 1.76,
    "Fe": 1.32, "Co": 1.26, "Ni": 1.24, "Cu": 1.32, "Zn": 1.22,
    "Br": 1.2, "I": 1.39,
}

FILE_ROWS = [
    ("frag1_opt", "Fragment 1 基态"),
    ("frag2_opt", "Fragment 2 基态"),
    ("frag1_def", "Fragment 1 在 TS 几何下"),
    ("frag2_def", "Fragment 2 在 TS 几何下"),
    ("ts",        "过渡态复合物"),
]
FILE_KEYS = [k for k, _ in FILE_ROWS]


# ── Gaussian log 解析（纯函数，与 tkinter 原版一致） ─────────────

def parse_scf_energy(log_path):
    """提取最后一个 SCF Done 能量（hartree）；无则退回 E(...)= 通用模式。"""
    scf_pattern = re.compile(r"SCF Done:\s+E\([^)]+\)\s*=\s*([+-]?\d+\.\d+)")
    fallback_pattern = re.compile(r"\bE\(\S+\)\s*=\s*([+-]?\d+\.\d+)")
    last_e = None
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = scf_pattern.search(line)
                if m:
                    last_e = float(m.group(1))
                else:
                    m2 = fallback_pattern.search(line)
                    if m2:
                        last_e = float(m2.group(1))
    except Exception as e:
        raise ValueError("无法读取文件 %s：%s" % (os.path.basename(log_path), e))
    return last_e


def parse_thermal_correction(log_path):
    """零点能修正项（需要 Freq 步骤）。"""
    pat = re.compile(r"Thermal correction to Energy=\s*([+-]?\d+\.\d+)")
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = pat.search(line)
                if m:
                    return float(m.group(1))
    except Exception:
        pass
    return None


def parse_gibbs(log_path):
    """Gibbs 自由能修正项（含热修正 + 熵）。"""
    pat = re.compile(r"Thermal correction to Gibbs Free Energy=\s*([+-]?\d+\.\d+)")
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = pat.search(line)
                if m:
                    return float(m.group(1))
    except Exception:
        pass
    return None


def check_normal_termination(log_path):
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if "Normal termination" in line:
                    return True
    except Exception:
        pass
    return False


def get_atoms_from_log(log_path):
    """从 Gaussian log 解析最后一个 Standard/Input orientation 的几何（Å）。"""
    atoms = []
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return []
    # 找最后一个 orientation 块起点
    start = -1
    for i, ln in enumerate(lines):
        if "Standard orientation:" in ln or "Input orientation:" in ln:
            start = i
    if start < 0:
        return []
    # 跳过 4 行表头（分隔线/标题/表头/分隔线）
    for ln in lines[start + 5:]:
        if ln.strip().startswith("----"):
            break
        parts = ln.split()
        if len(parts) >= 6:
            try:
                an = int(parts[1])
                x, y, z = float(parts[3]), float(parts[4]), float(parts[5])
                sym = ELEMENT_SYMBOLS.get(an, "E%d" % an)
                atoms.append((int(parts[0]), sym, an, (x, y, z)))
            except ValueError:
                continue
    return atoms


def get_atoms_from_fchk(fchk_path):
    """从 fchk 解析原子（坐标 Bohr → Å）。"""
    atoms = []
    try:
        with open(fchk_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception:
        return []
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
        sym = ELEMENT_SYMBOLS.get(an, "E%d" % an)
        atoms.append((i + 1, sym, an,
                      (coords[i * 3] * BOHR_TO_ANGSTROM,
                       coords[i * 3 + 1] * BOHR_TO_ANGSTROM,
                       coords[i * 3 + 2] * BOHR_TO_ANGSTROM)))
    return atoms


def get_bonds_from_atoms(atoms):
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


class DiAnalysisPanel(QWidget):
    """DI 能量分解分析面板（右侧 tab；共享左侧 OpenGL 画布显示分子）。"""

    def __init__(self, glw=None, log_func=None, parent=None):
        super().__init__(parent)
        self.glw = glw
        self._log = log_func or (lambda m: None)
        self._last_results = None
        self._figure = None
        self._canvas = None
        self._file_edits = {}

        self._build_ui()
        self._load_settings()

    # ── UI ──
    def showEvent(self, event):
        super().showEvent(event)
        if self._last_results is not None:
            QTimer.singleShot(0, self._draw_plot)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        # ── 图表（上方，占主要空间） ──
        self.fig_holder = QWidget()
        self._canvas_layout = QVBoxLayout(self.fig_holder)
        self._canvas_layout.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.fig_holder, stretch=1)

        # ── 设置区（下方，浅色渐变圆角卡片） ──
        grp = QGroupBox("DI 能量分解分析")
        grp.setObjectName("DiSettingsBox")
        grp.setStyleSheet("""
            QGroupBox#DiSettingsBox {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0 #FFFFFF, stop:1 #F1F5FB);
                border: 1px solid #D5DEE9;
                border-radius: 12px;
                margin-top: 14px;
            }
            QGroupBox#DiSettingsBox::title {
                subcontrol-origin: margin;
                left: 14px;
                padding: 2px 10px;
                background-color: #1565C0;
                color: #FFFFFF;
                border-radius: 4px;
                font-weight: bold;
                font-size: 10pt;
            }
            QGroupBox#DiSettingsBox QLineEdit {
                background: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 3px 8px;
            }
            QGroupBox#DiSettingsBox QPushButton {
                background: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 4px 12px;
            }
            QGroupBox#DiSettingsBox QPushButton:hover {
                background: #E8F1EF;
                border-color: #3E8E7E;
            }
            QGroupBox#DiSettingsBox QTableWidget {
                background: #FFFFFF;
                border: 1px solid #D5DEE9;
                border-radius: 6px;
                gridline-color: #E2E8F0;
            }
        """)
        gl = QGridLayout(grp)
        gl.setContentsMargins(10, 8, 10, 10)
        gl.setHorizontalSpacing(8)
        gl.setVerticalSpacing(5)

        for i, (key, label) in enumerate(FILE_ROWS):
            gl.addWidget(QLabel(label + ":"), i, 0)
            edit = QLineEdit()
            edit.setPlaceholderText("选择 Gaussian .log 文件")
            edit.textChanged.connect(lambda _t, k=key: self._on_path_changed(k))
            self._file_edits[key] = edit
            gl.addWidget(edit, i, 1, 1, 3)
            btn_browse = QPushButton("浏览")
            btn_browse.clicked.connect(lambda _c, k=key: self._browse_file(k))
            gl.addWidget(btn_browse, i, 4)
            btn_canvas = QPushButton("画布")
            btn_canvas.setToolTip("把该结构显示到左侧画布（log 取最后一个 orientation）")
            btn_canvas.clicked.connect(lambda _c, k=key: self._show_structure(k))
            gl.addWidget(btn_canvas, i, 5)

        row_btn = QHBoxLayout()
        btn_batch = QPushButton("批量选择（按顺序）")
        btn_batch.clicked.connect(self._batch_select)
        row_btn.addWidget(btn_batch)
        btn_match = QPushButton("从文件夹自动匹配")
        btn_match.clicked.connect(self._auto_match)
        row_btn.addWidget(btn_match)
        hint = QLabel("命名含关键词：opt1 / opt2 / frag1_def / frag2_def / ts")
        hint.setStyleSheet("color:#64748B;font-size:9pt;")
        row_btn.addWidget(hint)
        row_btn.addStretch(1)
        gl.addLayout(row_btn, len(FILE_ROWS), 0, 1, 6)

        row_corr = QHBoxLayout()
        self.chk_zpe = QCheckBox("零点能修正 (E0 = E_elec + ZPE)")
        self.chk_zpe.toggled.connect(self._on_corr_changed)
        row_corr.addWidget(self.chk_zpe)
        self.chk_gibbs = QCheckBox("Gibbs 自由能修正（含热修正 + 熵）")
        self.chk_gibbs.toggled.connect(self._on_corr_changed)
        row_corr.addWidget(self.chk_gibbs)
        corr_hint = QLabel("[!] 需要 Freq 计算步骤")
        corr_hint.setStyleSheet("color:#64748B;font-size:9pt;")
        row_corr.addWidget(corr_hint)
        row_corr.addStretch(1)
        gl.addLayout(row_corr, len(FILE_ROWS) + 1, 0, 1, 6)

        row_calc = QHBoxLayout()
        btn_calc = QPushButton(">> 计算能量分解")
        btn_calc.setStyleSheet("""
            background:#1565C0;color:#FFFFFF;font-weight:bold;
            border:1px solid #1565C0;border-radius:6px;padding:5px 18px;
        """)
        btn_calc.clicked.connect(self._calculate)
        row_calc.addWidget(btn_calc)
        btn_clear = QPushButton("清空结果")
        btn_clear.clicked.connect(self._clear_results)
        row_calc.addWidget(btn_clear)
        self.btn_export = QPushButton("导出 HTML 报告")
        self.btn_export.clicked.connect(self._export_html)
        self.btn_export.setEnabled(False)
        row_calc.addWidget(self.btn_export)
        self.btn_export_png = QPushButton("导出图片")
        self.btn_export_png.setToolTip("把当前图表保存为 PNG 图片")
        self.btn_export_png.clicked.connect(self._export_png)
        self.btn_export_png.setEnabled(False)
        row_calc.addWidget(self.btn_export_png)
        btn_fchk = QPushButton("载入 fchk 显示到画布…")
        btn_fchk.setToolTip("任意 fchk 文件的结构显示到左侧画布")
        btn_fchk.clicked.connect(self._show_fchk_dialog)
        row_calc.addWidget(btn_fchk)
        row_calc.addStretch(1)
        gl.addLayout(row_calc, len(FILE_ROWS) + 2, 0, 1, 6)

        # ── 结果表格（可折叠隐藏，给上方的 DI 图表让出更多空间） ──
        self.btn_toggle_table = QPushButton("▾ 结果表格")
        self.btn_toggle_table.setCheckable(True)
        self.btn_toggle_table.setChecked(True)
        self.btn_toggle_table.setMaximumWidth(160)
        self.btn_toggle_table.setStyleSheet("""
            QPushButton {
                background:#EFF6FF; color:#1565C0; font-weight:bold;
                border:1px solid #BFDBFE; border-radius:6px;
                padding:3px 12px; text-align:left;
            }
            QPushButton:hover { background:#DBEAFE; }
        """)
        self.btn_toggle_table.clicked.connect(self._toggle_table)
        gl.addWidget(self.btn_toggle_table, len(FILE_ROWS) + 3, 0, 1, 6)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["项目", "能量 (Hartree)",
                                              "能量 (kcal/mol)", "说明"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.verticalHeader().setVisible(False)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setMinimumHeight(220)
        gl.addWidget(self.table, len(FILE_ROWS) + 4, 0, 1, 6)

        formula = QLabel(
            "  ΔE_strain = (E_def1 − E_opt1) + (E_def2 − E_opt2)   |   "
            "ΔE_int = E_TS − E_def1 − E_def2   |   "
            "ΔE‡ = ΔE_strain + ΔE_int   |   1 Hartree = 627.509 kcal/mol  ")
        formula.setStyleSheet("""
            background:#EFF6FF;color:#1565C0;border:1px solid #BFDBFE;
            border-radius:6px;padding:6px 10px;font-family:Consolas,monospace;
            font-size:9pt;
        """)
        gl.addWidget(formula, len(FILE_ROWS) + 5, 0, 1, 6)

        outer.addWidget(grp)
        self._init_table_rows()

    # ── 结果表格 ──
    def _init_table_rows(self):
        self.table.setRowCount(0)
        self._table_keys = {}
        rows = [
            ("E_frag1_opt", "Fragment 1 基态", "energy"),
            ("E_frag2_opt", "Fragment 2 基态", "energy"),
            ("E_frag1_def", "Fragment 1 变形", "energy"),
            ("E_frag2_def", "Fragment 2 变形", "energy"),
            ("E_TS",        "过渡态复合物", "energy"),
            ("sep1",        "─" * 48, "sep"),
            ("dE_strain1",  "Fragment 1 畸变能", "result"),
            ("dE_strain2",  "Fragment 2 畸变能", "result"),
            ("dE_strain",   "总畸变能 ΔE_strain", "result"),
            ("dE_int",      "相互作用能 ΔE_int", "result"),
            ("dE_total",    "总活化能 ΔE‡", "result"),
        ]
        for desc, _, tag in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            item = QTableWidgetItem(desc)
            if tag == "sep":
                item.setForeground(QColor("#CBD5E1"))
                item.setFont(QFont("Consolas", 8))
            elif tag == "result":
                f = QFont("Consolas", 9)
                f.setBold(True)
                item.setFont(f)
            else:
                item.setFont(QFont("Consolas", 9))
            self.table.setItem(r, 0, item)
            for c in (1, 2):
                it = QTableWidgetItem("—")
                it.setFont(QFont("Consolas", 9))
                self.table.setItem(r, c, it)
            it3 = QTableWidgetItem("")
            self.table.setItem(r, 3, it3)

    def _set_table_row(self, key, h_val, note="", tag="energy"):
        r = self._row_of(key)
        if r < 0:
            return
        self.table.item(r, 1).setText("%.8f" % h_val)
        self.table.item(r, 2).setText("%.1f" % (h_val * HARTREE_TO_KCAL))
        self.table.item(r, 3).setText(note)
        color = QColor("#1E293B")
        if tag == "positive":
            color = QColor("#DC2626")
        elif tag == "negative":
            color = QColor("#059669")
        for c in (1, 2):
            self.table.item(r, c).setForeground(color)

    def _row_of(self, key):
        # 按固定行序：0-4 能量, 6-10 结果
        mapping = {
            "E_frag1_opt": 0, "E_frag2_opt": 1, "E_frag1_def": 2,
            "E_frag2_def": 3, "E_TS": 4,
            "dE_strain1": 6, "dE_strain2": 7, "dE_strain": 8,
            "dE_int": 9, "dE_total": 10,
        }
        return mapping.get(key, -1)

    # ── 文件选择 ──
    def _on_path_changed(self, key):
        self._save_settings()

    def _browse_file(self, key):
        p, _ = open_file(self, "选择 %s 的 log 文件" % key, "",
                         "Gaussian log (*.log);;所有文件 (*.*)")
        if p:
            self._file_edits[key].setText(p)
            self._clear_results()

    def _batch_select(self):
        paths, _ = open_files(
            self, "按顺序选择 5 个文件：Frag1_opt, Frag2_opt, Frag1_def, Frag2_def, TS",
            "", "Gaussian log (*.log);;所有文件 (*.*)")
        for i, key in enumerate(FILE_KEYS):
            if i < len(paths):
                self._file_edits[key].setText(paths[i])
        if paths:
            self._clear_results()

    def _auto_match(self):
        d = existing_directory(self, "选择包含 log 文件的文件夹")
        if not d:
            return
        try:
            logs = [f for f in os.listdir(d) if f.lower().endswith(".log")]
        except Exception:
            logs = []
        matched = 0
        for f in logs:
            f_lower = f.lower()
            path = os.path.join(d, f)
            if any(k in f_lower for k in ["frag1_opt", "r1_opt", "reactant1"]) \
                    and "def" not in f_lower and "ts" not in f_lower:
                self._file_edits["frag1_opt"].setText(path); matched += 1
            elif any(k in f_lower for k in ["frag2_opt", "r2_opt", "reactant2"]) \
                    and "def" not in f_lower and "ts" not in f_lower:
                self._file_edits["frag2_opt"].setText(path); matched += 1
            elif any(k in f_lower for k in ["frag1_def", "frag1_at_ts", "f1_def"]) \
                    or ("frag1" in f_lower and "def" in f_lower):
                self._file_edits["frag1_def"].setText(path); matched += 1
            elif any(k in f_lower for k in ["frag2_def", "frag2_at_ts", "f2_def"]) \
                    or ("frag2" in f_lower and "def" in f_lower):
                self._file_edits["frag2_def"].setText(path); matched += 1
            elif any(k in f_lower for k in ["ts", "transition", "dimer_ts"]) \
                    and "frag" not in f_lower:
                self._file_edits["ts"].setText(path); matched += 1
        self._clear_results()
        self._log("DI: 自动匹配：%d 个 log 文件找到 %d 个匹配项"
                  % (len(logs), matched))

    # ── 能量与计算 ──
    def _get_energy(self, key):
        path = self._file_edits[key].text().strip()
        if not path or not os.path.exists(path):
            return None
        e_elec = parse_scf_energy(path)
        if e_elec is None:
            return None
        if self.chk_zpe.isChecked():
            zpe = parse_thermal_correction(path)
            if zpe is not None:
                e_elec += zpe
        if self.chk_gibbs.isChecked():
            gibbs_corr = parse_gibbs(path)
            if gibbs_corr is not None:
                e_elec = parse_scf_energy(path) + gibbs_corr
        return e_elec

    def _on_corr_changed(self, _checked):
        self._clear_results()

    def _calculate(self):
        paths = {}
        for k in FILE_KEYS:
            p = self._file_edits[k].text().strip()
            if not p:
                QMessageBox.critical(self, "缺少文件", "请先选择：%s" % k)
                return
            if not os.path.exists(p):
                QMessageBox.critical(self, "文件不存在", "文件不存在：%s" % p)
                return
            paths[k] = p

        bad = [os.path.basename(p) for p in paths.values()
               if not check_normal_termination(p)]
        if bad:
            ans = QMessageBox.question(
                self, "警告",
                "以下文件未正常结束（可能仍在运行或已崩溃）：\n%s\n\n是否继续计算？"
                % "\n".join(bad),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ans != QMessageBox.Yes:
                return

        try:
            e1_opt = self._get_energy("frag1_opt")
            e2_opt = self._get_energy("frag2_opt")
            e1_def = self._get_energy("frag1_def")
            e2_def = self._get_energy("frag2_def")
            e_ts = self._get_energy("ts")
        except Exception as e:
            QMessageBox.critical(self, "读取失败", str(e))
            return

        for name, val in [("Fragment 1 opt", e1_opt), ("Fragment 2 opt", e2_opt),
                          ("Fragment 1 def", e1_def), ("Fragment 2 def", e2_def),
                          ("TS", e_ts)]:
            if val is None:
                QMessageBox.critical(
                    self, "能量读取失败",
                    "无法从以下文件中读取 SCF 能量：\n%s\n\n"
                    "请确保 Gaussian 计算已完成并正常输出。" % name)
                return

        strain1 = e1_def - e1_opt
        strain2 = e2_def - e2_opt
        dE_strain = strain1 + strain2
        dE_int = e_ts - e1_def - e2_def
        dE_total = dE_strain + dE_int

        self._last_results = {
            "e1_opt": e1_opt, "e2_opt": e2_opt,
            "e1_def": e1_def, "e2_def": e2_def, "e_ts": e_ts,
            "strain1": strain1, "strain2": strain2,
            "dE_strain": dE_strain, "dE_int": dE_int, "dE_total": dE_total,
            "paths": paths,
        }

        self._update_table(e1_opt, e2_opt, e1_def, e2_def, e_ts,
                           strain1, strain2, dE_strain, dE_int, dE_total)

        corr_note = ""
        if self.chk_zpe.isChecked():
            corr_note += " [ZPE修正]"
        if self.chk_gibbs.isChecked():
            corr_note += " [Gibbs修正]"
        self._log(
            "DI: 计算完成%s | ΔE_strain = %.1f | ΔE_int = %.1f | ΔE‡ = %.1f kcal/mol"
            % (corr_note, dE_strain * HARTREE_TO_KCAL,
               dE_int * HARTREE_TO_KCAL, dE_total * HARTREE_TO_KCAL))

        self.btn_export.setEnabled(True)
        self.btn_export_png.setEnabled(True)
        self._draw_plot()
        self._save_settings()

    def _update_table(self, e1_opt, e2_opt, e1_def, e2_def, e_ts,
                      strain1, strain2, dE_strain, dE_int, dE_total):
        def _set(key, h_val, note="", tag="energy"):
            self._set_table_row(key, h_val, note, tag)

        _set("E_frag1_opt", e1_opt)
        _set("E_frag2_opt", e2_opt)
        _set("E_frag1_def", e1_def)
        _set("E_frag2_def", e2_def)
        _set("E_TS", e_ts)

        _set("dE_strain1", strain1,
             "+%.1f kcal/mol（不利）" % (strain1 * HARTREE_TO_KCAL)
             if strain1 > 0 else "%.1f kcal/mol" % (strain1 * HARTREE_TO_KCAL),
             "positive" if strain1 > 0 else "negative")
        _set("dE_strain2", strain2,
             "+%.1f kcal/mol（不利）" % (strain2 * HARTREE_TO_KCAL)
             if strain2 > 0 else "%.1f kcal/mol" % (strain2 * HARTREE_TO_KCAL),
             "positive" if strain2 > 0 else "negative")
        _set("dE_strain", dE_strain,
             "正值=形变代价不利，负值=形变释放能量",
             "positive" if dE_strain > 0 else "negative")
        _set("dE_int", dE_int,
             "负值=吸引有利，正值=排斥不利",
             "negative" if dE_int < 0 else "positive")
        _set("dE_total", dE_total,
             "ΔE‡ = %.1f kcal/mol" % (dE_total * HARTREE_TO_KCAL),
             "positive" if dE_total > 0 else "negative")

    def _clear_results(self):
        self._last_results = None
        self.btn_export.setEnabled(False)
        self.btn_export_png.setEnabled(False)
        self._init_table_rows()
        self._draw_empty_plot()

    def _toggle_table(self):
        """隐藏/展开结果表格，给上方的 DI 图表让出空间。"""
        show = self.btn_toggle_table.isChecked()
        self.table.setVisible(show)
        self.btn_toggle_table.setText("▾ 结果表格" if show else "▸ 结果表格")
        if self._last_results is not None:
            QTimer.singleShot(0, self._draw_plot)

    # ── 图表 ──
    def _figsize(self):
        w = max(self.width(), 200)
        h = max(self.height() - 480, 200)
        return (w / 100.0, h / 100.0)

    def _draw_plot(self):
        R = self._last_results
        if R is None:
            self._draw_empty_plot()
            return
        fig = Figure(figsize=self._figsize(), dpi=100, facecolor="white")
        gs = fig.add_gridspec(1, 2, width_ratios=[5, 3],
                              left=0.07, right=0.97, top=0.90, bottom=0.12,
                              wspace=0.28)
        self._draw_di_arrows(fig.add_subplot(gs[0, 0]), R)
        self._draw_decomposition(fig.add_subplot(gs[0, 1]), R)
        self._set_canvas(fig)

    def _draw_empty_plot(self):
        fig = Figure(figsize=self._figsize(), dpi=100, facecolor="white")
        ax = fig.add_subplot(111)
        ax.text(0.5, 0.5, "计算后显示 DI 能量分解图",
                ha="center", va="center", fontsize=12, color="#94A3B8")
        ax.set_xticks([])
        ax.set_yticks([])
        for s in ax.spines.values():
            s.set_visible(False)
        self._set_canvas(fig)

    def _set_canvas(self, fig):
        if self._canvas is None:
            self._canvas = FigureCanvas(fig)
            self._canvas_layout.addWidget(self._canvas)
        else:
            self._canvas_layout.removeWidget(self._canvas)
            try:
                self._canvas.close()
            except Exception:
                pass
            self._canvas = FigureCanvas(fig)
            self._canvas_layout.addWidget(self._canvas)
        self._canvas.draw()

    def _draw_di_arrows(self, ax, R):
        ax.set_facecolor("white")
        s1 = R["strain1"] * HARTREE_TO_KCAL
        s2 = R["strain2"] * HARTREE_TO_KCAL
        strain = R["dE_strain"] * HARTREE_TO_KCAL
        di_int = R["dE_int"] * HARTREE_TO_KCAL
        total = R["dE_total"] * HARTREE_TO_KCAL

        x_dist = 1.2
        x_comb = 2.6
        width = 0.6

        # Material 200 系淡色（参考 ESP 面板配色风格，描边加深更精致）
        color_s1 = "#EF9A9A"
        color_s2 = "#FFCC80"
        color_int = "#90CAF9"
        color_ea = "#A5D6A7"

        all_points = [0, s1, strain, total, strain + di_int]
        y_min = min(all_points) * 1.2
        y_max = max(all_points) * 1.2
        if (y_max - y_min) < 50:
            center = (y_max + y_min) / 2
            y_min, y_max = center - 25, center + 25

        ax.axhline(0, color="#666666", linestyle="--", alpha=0.7, linewidth=1)
        self._draw_rect(ax, x_dist, 0, s1, width, color_s1)
        self._draw_rect(ax, x_dist, s1, s2, width, color_s2)
        if di_int < 0:
            self._draw_rect(ax, x_comb, strain + di_int, -di_int, width, color_int)
        else:
            self._draw_rect(ax, x_comb, strain, di_int, width, color_int)
        if total > 0:
            self._draw_rect(ax, x_comb, 0, total, width, color_ea)
        else:
            self._draw_rect(ax, x_dist, total, -total, width, color_ea)

        ax.plot([x_dist + width / 2, x_comb - width / 2], [strain, strain],
                color="#666666", linewidth=0.8, linestyle="--", alpha=0.5)

        for (x, y, val) in [(x_dist, s1 / 2, s1), (x_dist, s1 + s2 / 2, s2),
                            (x_comb, strain + di_int / 2, di_int),
                            (x_comb if total > 0 else x_dist, total / 2, total)]:
            ax.text(x, y, "%.1f" % val, ha="center", va="center", fontsize=9,
                    fontweight="bold", color="#333333", fontname="Arial")

        legend_elements = [
            Patch(facecolor=color_s1, edgecolor="#333333", label="Distortion 1"),
            Patch(facecolor=color_s2, edgecolor="#333333", label="Distortion 2"),
            Patch(facecolor=color_int, edgecolor="#333333", label="Interaction"),
            Patch(facecolor=color_ea, edgecolor="#333333", label="Activation"),
        ]
        ax.legend(handles=legend_elements, loc="lower center",
                  bbox_to_anchor=(0.5, 1.05), ncol=4, fontsize=9, framealpha=0.9)
        ax.set_xlim(-0.5, 4.3)
        ax.set_ylim(y_min, y_max)
        ax.set_xticks([x_dist, x_comb])
        ax.set_xticklabels(["Distortion", "Interaction"],
                           fontname="Arial", fontsize=11)
        ax.set_ylabel("Energy (kcal/mol)", fontname="Arial", fontsize=12)
        for text in ax.get_yticklabels() + ax.get_xticklabels():
            text.set_fontname("Arial")

    def _draw_decomposition(self, ax, R):
        ax.set_facecolor("white")
        labels = ["ΔE_strain", "ΔE_int", "ΔE‡"]
        vals = [R["dE_strain"] * HARTREE_TO_KCAL,
                R["dE_int"] * HARTREE_TO_KCAL,
                R["dE_total"] * HARTREE_TO_KCAL]
        # ESP 风格 Material 色：正=红 600，负=绿 600，近零=灰
        colors = []
        for v in vals:
            if v > 0.01:
                colors.append("#E53935")
            elif v < -0.01:
                colors.append("#43A047")
            else:
                colors.append("#9E9E9E")
        bars = ax.bar(labels, vals, color=colors, width=0.55, alpha=0.92,
                      edgecolor="#333333", linewidth=0.8, zorder=3)
        ax.axhline(y=0, color="#666666", linestyle="--", alpha=0.7,
                   linewidth=1, zorder=2)
        ax.set_title("Energy Decomposition", fontsize=12, fontweight="bold",
                     pad=10, color="#1E293B")
        for bar, val in zip(bars, vals):
            h = bar.get_height()
            offset = max(abs(v) for v in vals) * 0.06 + 0.5
            y_pos = h + offset if h >= 0 else h - offset
            ax.text(bar.get_x() + bar.get_width() / 2, y_pos, "%+.1f" % val,
                    ha="center", va="bottom" if h >= 0 else "top",
                    fontsize=10, fontweight="bold", color="#333333",
                    fontname="Arial")
        ax.set_ylabel("Energy (kcal/mol)", fontname="Arial", fontsize=12)
        ax.tick_params(axis="both", labelsize=9)
        for text in ax.get_yticklabels() + ax.get_xticklabels():
            text.set_fontname("Arial")
        ymax = max(abs(v) for v in vals) * 1.4
        ax.set_ylim(bottom=-ymax, top=ymax)
        legend_patches = [
            Patch(facecolor="#E53935", edgecolor="#333333",
                  label="Unfavorable (+)"),
            Patch(facecolor="#43A047", edgecolor="#333333",
                  label="Favorable (-)"),
        ]
        ax.legend(handles=legend_patches, loc="upper right", fontsize=8,
                  framealpha=0.9, edgecolor="#E2E8F0")

    def _draw_rect(self, ax, x, y_base, height, width, color):
        rect = Rectangle((x - width / 2, y_base), width, height,
                         facecolor=color, edgecolor="#333333", linewidth=0.8)
        ax.add_patch(rect)

    # ── 画布显示 ──
    def _show_structure(self, key):
        if self.glw is None:
            self._log("DI: 画布不可用")
            return
        path = self._file_edits[key].text().strip()
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "提示", "请先选择 %s 的文件。" % key)
            return
        self._display_to_canvas(path)

    def _show_fchk_dialog(self):
        p, _ = open_file(self, "选择要显示的 fchk", "",
                         "fchk (*.fchk);;All (*.*)")
        if p:
            self._display_to_canvas(p)

    def _display_to_canvas(self, path):
        ext = os.path.splitext(path)[1].lower()
        if ext == ".fchk":
            atoms = get_atoms_from_fchk(path)
        else:
            atoms = get_atoms_from_log(path)
        if not atoms:
            self._log("DI: 结构解析失败: %s" % os.path.basename(path))
            QMessageBox.warning(self, "提示", "无法从文件中解析结构。")
            return
        bonds = get_bonds_from_atoms(atoms)
        try:
            self.glw.set_molecule(atoms, bonds)
            self._log("DI: 画布显示 %s（%d 原子）"
                      % (os.path.basename(path), len(atoms)))
        except Exception as e:
            self._log("DI: 画布显示失败: %s" % e)

    # ── 导出 ──
    def _export_png(self):
        R = self._last_results
        if R is None or self._canvas is None:
            QMessageBox.warning(self, "无结果", "请先进行计算")
            return
        path, _ = save_file(self, "保存图表图片", "", "PNG 图片 (*.png)")
        if not path:
            return
        try:
            self._canvas.figure.savefig(path, dpi=200, bbox_inches="tight",
                                        facecolor="white")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))
            return
        self._log("DI: 图表已保存：%s" % path)
        QMessageBox.information(self, "导出成功",
                                "图片已保存至：\n%s" % path)
        try:
            os.startfile(path)
        except Exception:
            pass

    def _export_html(self):
        R = self._last_results
        if R is None:
            QMessageBox.warning(self, "无结果", "请先进行计算")
            return
        path, _ = save_file(self, "保存 HTML 报告", "", "HTML 文件 (*.html)")
        if not path:
            return

        LIGHT_R = "#FEF2F2"
        LIGHT_G = "#ECFDF5"

        def _row(name, h, kcal, note="", bg="#FFFFFF"):
            return (
                '<tr style="background:%s">'
                '<td style="padding:8px 12px;text-align:left;">%s</td>'
                '<td style="padding:8px 12px;text-align:right;'
                'font-family:Consolas,monospace;">%.8f</td>'
                '<td style="padding:8px 12px;text-align:right;'
                'font-family:Consolas,monospace;">%.1f</td>'
                '<td style="padding:8px 12px;color:#64748B;font-size:12px;">%s</td>'
                "</tr>" % (bg, name, h, kcal, note))

        strain1_bg = LIGHT_R if R["strain1"] > 0 else LIGHT_G
        strain2_bg = LIGHT_R if R["strain2"] > 0 else LIGHT_G
        strain_bg = LIGHT_R if R["dE_strain"] > 0 else LIGHT_G
        int_bg = LIGHT_G if R["dE_int"] < 0 else LIGHT_R
        total_bg = LIGHT_R if R["dE_total"] > 0 else LIGHT_G

        html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>Distortion-Interaction 分析报告</title>
<style>
    body {{ font-family: "Microsoft YaHei", "Segoe UI", sans-serif; background:#F0F2F5; color:#1E293B; margin:0; padding:24px; }}
    h1 {{ color:#2563EB; border-bottom:2px solid #2563EB; padding-bottom:10px; font-size:20px; }}
    table {{ border-collapse:collapse; width:100%%; margin:16px 0; background:white; border-radius:8px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.08); }}
    th {{ background:#2563EB; color:white; padding:10px 12px; text-align:left; font-weight:500; }}
    td {{ border-bottom:1px solid #E2E8F0; }}
    .formula {{ background:#EFF6FF; padding:14px 18px; border-radius:8px; margin:12px 0; font-family:Consolas,monospace; color:#2563EB; font-size:13px; }}
    .files {{ background:#F8FAFC; padding:12px 16px; border-radius:8px; font-size:12px; color:#64748B; margin:12px 0; border:1px solid #E2E8F0; }}
</style>
</head>
<body>
<h1>Distortion-Interaction 能量分解分析报告</h1>

<div class="formula">
    ΔE_strain = (E_def1 − E_opt1) + (E_def2 − E_opt2) &nbsp;&nbsp;|&nbsp;&nbsp;
    ΔE_int = E_TS − E_def1 − E_def2 &nbsp;&nbsp;|&nbsp;&nbsp;
    ΔE‡ = ΔE_strain + ΔE_int
</div>

<div class="files">
    <strong>所用文件：</strong><br>
    Fragment 1 opt: %s<br>
    Fragment 2 opt: %s<br>
    Fragment 1 def: %s<br>
    Fragment 2 def: %s<br>
    TS complex: %s<br>
</div>

<table>
    <tr><th>项目</th><th>能量 (Hartree)</th><th>能量 (kcal/mol)</th><th>说明</th></tr>
    %s
    %s
    %s
    %s
    %s
    <tr><td colspan="4" style="padding:4px;background:#F0F2F5;"></td></tr>
    %s
    %s
    %s
    %s
    %s
</table>

<p style="color:#64748B;font-size:12px;margin-top:20px;">
    生成工具：GXNU MolStudio — Distortion-Interaction 能量分解分析 &nbsp;|&nbsp;
    1 Hartree = 627.509 kcal/mol
</p>
</body>
</html>""" % (
            os.path.basename(R["paths"]["frag1_opt"]),
            os.path.basename(R["paths"]["frag2_opt"]),
            os.path.basename(R["paths"]["frag1_def"]),
            os.path.basename(R["paths"]["frag2_def"]),
            os.path.basename(R["paths"]["ts"]),
            _row("Fragment 1 基态 E_opt1", R["e1_opt"],
                 R["e1_opt"] * HARTREE_TO_KCAL),
            _row("Fragment 2 基态 E_opt2", R["e2_opt"],
                 R["e2_opt"] * HARTREE_TO_KCAL),
            _row("Fragment 1 变形 E_def1", R["e1_def"],
                 R["e1_def"] * HARTREE_TO_KCAL),
            _row("Fragment 2 变形 E_def2", R["e2_def"],
                 R["e2_def"] * HARTREE_TO_KCAL),
            _row("过渡态复合物 E_TS", R["e_ts"],
                 R["e_ts"] * HARTREE_TO_KCAL),
            _row("Fragment 1 畸变能", R["strain1"],
                 R["strain1"] * HARTREE_TO_KCAL,
                 "+%.1f kcal/mol（不利）" % (R["strain1"] * HARTREE_TO_KCAL)
                 if R["strain1"] > 0
                 else "%.1f kcal/mol" % (R["strain1"] * HARTREE_TO_KCAL),
                 strain1_bg),
            _row("Fragment 2 畸变能", R["strain2"],
                 R["strain2"] * HARTREE_TO_KCAL,
                 "+%.1f kcal/mol（不利）" % (R["strain2"] * HARTREE_TO_KCAL)
                 if R["strain2"] > 0
                 else "%.1f kcal/mol" % (R["strain2"] * HARTREE_TO_KCAL),
                 strain2_bg),
            _row("<strong>总畸变能 ΔE_strain</strong>", R["dE_strain"],
                 R["dE_strain"] * HARTREE_TO_KCAL,
                 "正值=形变代价不利，负值=形变释放能量", strain_bg),
            _row("<strong>相互作用能 ΔE_int</strong>", R["dE_int"],
                 R["dE_int"] * HARTREE_TO_KCAL,
                 "负值=吸引有利，正值=排斥不利", int_bg),
            _row("<strong>总活化能 ΔE‡</strong>", R["dE_total"],
                 R["dE_total"] * HARTREE_TO_KCAL,
                 "ΔE‡ = %.1f kcal/mol" % (R["dE_total"] * HARTREE_TO_KCAL),
                 total_bg),
        )

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(html)
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))
            return
        self._log("DI: HTML 报告已保存：%s" % path)
        QMessageBox.information(self, "导出成功",
                                "HTML 报告已保存至：\n%s" % path)
        try:
            os.startfile(path)
        except Exception:
            pass

    # ── 配置持久化 ──
    def _settings_path(self):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "di_panel_settings.ini")

    def _load_settings(self):
        cfg = configparser.ConfigParser()
        try:
            if os.path.exists(self._settings_path()):
                cfg.read(self._settings_path(), encoding="utf-8")
                if "di" in cfg:
                    for k in FILE_KEYS:
                        v = cfg["di"].get(k, "")
                        if v:
                            self._file_edits[k].setText(v)
                    self.chk_zpe.setChecked(
                        cfg["di"].getboolean("zpe", False))
                    self.chk_gibbs.setChecked(
                        cfg["di"].getboolean("gibbs", False))
        except Exception:
            pass

    def _save_settings(self):
        cfg = configparser.ConfigParser()
        sec = {"zpe": "1" if self.chk_zpe.isChecked() else "0",
               "gibbs": "1" if self.chk_gibbs.isChecked() else "0"}
        for k in FILE_KEYS:
            sec[k] = self._file_edits[k].text().strip()
        cfg["di"] = sec
        try:
            with open(self._settings_path(), "w", encoding="utf-8") as f:
                cfg.write(f)
        except Exception:
            pass

    def shutdown(self):
        """关闭时清理（本面板无后台线程）。"""
        self._save_settings()
