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
    QScrollArea, QGridLayout,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal

import matplotlib
matplotlib.use("Qt5Agg")
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from file_dialogs import existing_directory, save_file, open_file
from fchk_orbital import ELEMENT_SYMBOLS

HARTREE_TO_EV = 27.2114
HARTREE_TO_KCAL = 627.509
BOHR_TO_ANGSTROM = 0.529177210903

BOND_COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
               "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]

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
        self.all_bond_data = []        # {"name","values","color"}
        self.is_flipped = False
        self._irc_figure = None
        self._irc_canvas = None
        self.cache_dir = os.path.join(os.getcwd(), "_mayer_cache")
        self._bond_worker = None

        self._build_ui()
        self._load_settings()

    # ── UI ──
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
                padding: 0 6px;
                color: #0F766E;
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
        gl.addWidget(self.combo_unit, 1, 1)
        self.chk_relative = QCheckBox("相对能量（减最低点）")
        self.chk_relative.setChecked(True)
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
        self.all_bond_data.append({
            "name": "%s-%s" % (a1, a2),
            "values": values,
            "color": BOND_COLORS[(len(self.all_bond_data))
                                 % len(BOND_COLORS)],
        })
        self._update_plot()

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
        fig = Figure(figsize=(7.5, 5.0), dpi=110)
        ax1 = fig.add_subplot(111)
        ax2 = ax1.twinx()
        ax1.set_zorder(ax2.get_zorder() + 1)
        ax1.patch.set_visible(False)

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
        if self.is_flipped:
            plot_energy = plot_energy[::-1]
            bond_src = [dict(b, values=list(reversed(b["values"])))
                        for b in self.all_bond_data]
        else:
            bond_src = self.all_bond_data

        # 键级（左轴）
        has_bond = False
        for bd in bond_src:
            vv = [v for v in bd["values"] if v is not None]
            xx = [x for x, v in zip(x_idx, bd["values"]) if v is not None]
            if vv:
                has_bond = True
                ax1.plot(xx, vv, linestyle="-", marker="o",
                         color=bd.get("color", "blue"), linewidth=2,
                         markersize=5, alpha=0.9, label=bd["name"])
        if has_bond:
            ax1.set_ylabel("键级 (Mayer)", fontsize=10, fontweight="bold",
                           color="#2C3E50")
            ax1.legend(loc="upper left", fontsize=8, framealpha=0.85)

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
        ax2.scatter(x_idx, plot_energy, c=colors, edgecolors="#6B7280",
                    linewidth=0.5, s=40, alpha=0.85, zorder=5)
        ax2.plot(xs, ys, color="#374151", linewidth=2.0, alpha=0.85, zorder=4)
        ax2.set_ylabel("能量 (%s)" % unit, fontsize=10, fontweight="bold")

        ax1.set_title("IRC Reaction Profile", fontsize=12, fontweight="bold",
                      pad=10)
        ax1.set_xlabel("IRC Point", fontsize=10)
        ax1.tick_params(labelsize=8)
        ax2.tick_params(labelsize=8)
        ax1.grid(True, which="major", linestyle="--", linewidth=0.5,
                 color="#CCCCCC", alpha=0.7)
        fig.tight_layout()

        canvas = FigureCanvas(fig)
        self._canvas_layout.addWidget(canvas)
        self._irc_figure = fig
        self._irc_canvas = canvas

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
                for bd in self.all_bond_data:
                    headers.append("Bond Order %s" % bd["name"])
                w.writerow(headers)
                for i in range(len(self.energy_values)):
                    row = [i + 1, self.energy_values[i]]
                    for bd in self.all_bond_data:
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
        if self._bond_worker is not None:
            try:
                self._bond_worker.stop()
                self._bond_worker.wait(2000)
            except Exception:
                pass
