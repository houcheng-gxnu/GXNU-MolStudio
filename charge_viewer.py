# -*- coding: utf-8 -*-
"""
charge_viewer.py — 原子电荷读取与分析（整合自 ChargeViewer）
=============================================================

将 ChargeViewer 的「电荷读取」功能整合进 OrbitalViewer：

  * 读取 Multiwfn 的 `.chg` 文件（格式：元素 x y z 电荷，坐标 Å）；
  * 读取 `.fchk` 拿分子结构，后台调用 Multiwfn 计算 6 种原子电荷
    （ADCH / Hirshfeld / Mulliken / CM5 / SCPA / VDD），解析其输出；
  * 3D 可视化复用主窗口左侧的 OpenGL 画布 (ovcanvas.CubGLWidget)：
    通过 glw.set_molecule / glw.set_atom_colors 显示分子并「按电荷着色」
    （蓝-白-红 发散色标）；
  * 电荷表格 + CSV 导出。

ChargePanel 是作为主窗口右侧 QTabWidget 的一个页签使用的面板：

    from charge_viewer import ChargePanel
    panel = ChargePanel(glw=app.cub_canvas.glw,
                        multiwfn_path=app.paths["multiwfn"],
                        get_fchk=lambda: app._current_fchk)

本模块部分解析逻辑与 Multiwfn 调用序列移植自 ChargeViewer
(https://cnb.cool/chem311/ChargeViewer)。
Multiwfn 见: Tian Lu, J. Comput. Chem., 2012, 33, 580-592.
"""

import os
import re
import subprocess
import traceback

import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QTextEdit, QFileDialog, QMessageBox, QFrame,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from file_dialogs import open_file, save_file

from molcanvas import get_bonds_from_fchk, ELEMENT_SYMBOLS

# 元素符号 -> 原子序数（.chg 文件解析用）
SYMBOL_TO_Z = {sym: z for z, sym in ELEMENT_SYMBOLS.items()}

# ═══════════════════════════════════════════════════════════════
# 电荷类型配置（移植自 ChargeViewer config.py）
# input_seq 为 Multiwfn 菜单按键序列（版本相关；以本机 Multiwfn 菜单为准）。
# ═══════════════════════════════════════════════════════════════
CHARGE_TYPES = {
    "ADCH": {
        "desc": "Atomic Dipole Moment Corrected Hirshfeld Charge (Recommended)",
        "input_seq": "\n7\n11\n1\ny\n0\nq\n",
        "menu_path": "7 -> 11 -> 1",
        "marker": ["Final atomic charges:"],
    },
    "Hirshfeld": {
        "desc": "Hirshfeld Atomic Charge (Stockholder Partitioning)",
        "input_seq": "\n7\n1\n1\ny\n0\nq\n",
        "menu_path": "7 -> 1 -> 1",
        "marker": ["Final atomic charges:"],
    },
    "Mulliken": {
        "desc": "Mulliken Population Analysis (Classic Method)",
        "input_seq": "\n7\n5\n1\ny\n0\nq\n",
        "menu_path": "7 -> 5 -> 1",
        "marker": ["Net charge:"],
    },
    "CM5": {
        "desc": "CM5 Charge (Mapped to Hirshfeld)",
        "input_seq": "\n7\n16\n1\ny\n0\nq\n",
        "menu_path": "7 -> 16 -> 1",
        "marker": ["CM5 charges:", "Charge Model 5 charges:"],
    },
    "SCPA": {
        "desc": "Modified Mulliken (Ros & Schuit, SCPA)",
        "input_seq": "\n7\n7\ny\n0\nq\n",
        "menu_path": "7 -> 7",
        "marker": ["Atomic charge:"],
    },
    "VDD": {
        "desc": "Voronoi Deformation Density Charge",
        "input_seq": "\n7\n2\n1\ny\n0\nq\n",
        "menu_path": "7 -> 2 -> 1",
        "marker": ["Final atomic charges:"],
    },
}

# Mayer 键级分析的 Multiwfn 菜单序列（移植自 ChargeViewer）：9 -> 1（Mayer）-> n -> 0 -> q
BO_INPUT_SEQ = "\n9\n1\nn\n0\nq\n"


# ═══════════════════════════════════════════════════════════════
# 解析函数（纯文本，无 Qt 依赖）
# ═══════════════════════════════════════════════════════════════

def parse_chg_file(path):
    """解析 Multiwfn `.chg` 文件。

    每行格式：`元素  x  y  z  电荷`（坐标 Å，电荷在最后一列）。
    返回 (atoms, charges)：
        atoms   = [(idx, symbol, anum, (x, y, z)), ...]   # 与 MolCanvas 一致
        charges = {idx: float, ...}                        # 1-based 索引
    """
    atoms = []
    charges = {}
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            parts = line.split()
            if len(parts) < 5:
                continue
            sym = parts[0]
            try:
                x, y, z, q = (float(parts[1]), float(parts[2]),
                              float(parts[3]), float(parts[4]))
            except ValueError:
                continue
            anum = SYMBOL_TO_Z.get(sym, 0)
            idx = len(atoms) + 1
            atoms.append((idx, sym, anum, (x, y, z)))
            charges[idx] = q
    return atoms, charges


def parse_multiwfn_charges(output_text, charge_type="ADCH"):
    """解析 Multiwfn 电荷输出，返回 [(idx, elem, charge), ...]。

    移植自 ChargeViewer 的 parse_atomic_charges（正则按 marker 定位）。
    """
    results = []
    if not output_text or charge_type not in CHARGE_TYPES:
        return results

    markers = CHARGE_TYPES[charge_type]["marker"]
    pattern_standard = re.compile(r"Atom\s+(\d+)\(([^)]+?)\s*\):\s+([-\d.]+)")
    pattern_mulliken = re.compile(
        r"Atom\s+(\d+)\((\w+)\s*\)\s+Population:\s+[-\d.]+\s+Net charge:\s+([-\d.]+)")
    pattern_scpa = re.compile(
        r"Atom\s+(\d+)\(([^)]+?)\s*\)\s+Population:\s+[-\d.]+\s+Atomic charge:\s+([-\d.]+)")

    if charge_type == "SCPA":
        for line in output_text.splitlines():
            m = pattern_scpa.search(line)
            if m:
                results.append((int(m.group(1)), m.group(2).strip(), float(m.group(3))))
        return results

    in_final = False
    for line in output_text.splitlines():
        for marker in markers:
            if marker in line:
                in_final = True
                continue
        if in_final:
            m = pattern_standard.search(line)
            if not m:
                m = pattern_mulliken.search(line)
            if m:
                results.append((int(m.group(1)), m.group(2).strip(), float(m.group(3))))
            if "----------" in line and results:
                break
            elif "Total net charge" in line and results:
                break
            elif "Calculation took" in line and results:
                break
            elif "If outputting" in line and results:
                break
            elif in_final and not line.strip() and results:
                break
    return results


def parse_mayer_bond_orders(output_text):
    """解析 Multiwfn Mayer 键级输出，返回 (bond_orders, valences)。

    bond_orders = {(min(i,j), max(i,j)): 键级}，键为 1-based 原子索引；
    valences    = {atom_idx: (symbol, total_valence)}。
    移植自 ChargeViewer 的 parse_mayer_bond_orders。
    """
    bond_orders = {}
    valences = {}
    pattern_bo = re.compile(
        r"#\s+\d+:\s+(\d+)\(([^)]*?)\s*\)\s+(\d+)\(([^)]*?)\s*\)\s+([-\d.]+)")
    pattern_val = re.compile(
        r"Atom\s+(\d+)\(([^)]*?)\s*\)\s*:\s+([-\d.]+)\s+([-\d.]+)")

    in_bo = False
    in_val = False
    for line in output_text.splitlines():
        if "Bond orders with absolute value" in line:
            in_bo = True
            in_val = False
            continue
        if "Total valences and free valences" in line:
            in_bo = False
            in_val = True
            continue

        if in_bo:
            m = pattern_bo.search(line)
            if m:
                a1 = int(m.group(1))
                a2 = int(m.group(3))
                bo = float(m.group(5))
                bond_orders[(min(a1, a2), max(a1, a2))] = bo
        elif in_val:
            m = pattern_val.search(line)
            if m:
                a1 = int(m.group(1))
                s1 = m.group(2).strip()
                tv = float(m.group(3))
                valences[a1] = (s1, tv)

    return bond_orders, valences


def charge_to_rgb(charge, vmax):
    """把电荷映射到蓝-白-红发散色标，返回 (r, g, b) 浮点 0..1。

    负电荷=蓝，0=白，正电荷=红。
    """
    t = -1.0 if vmax <= 0 else max(-1.0, min(1.0, charge / vmax))
    tn = (t + 1.0) / 2.0  # 0..1
    if tn <= 0.5:
        f = tn / 0.5
        r, g, b = f, f, 1.0
    else:
        f = (tn - 0.5) / 0.5
        r, g, b = 1.0, 1.0 - f, 1.0 - f
    return (r, g, b)


# ═══════════════════════════════════════════════════════════════
# Multiwfn 子进程调用（后台线程）
# ═══════════════════════════════════════════════════════════════

class MultiwfnRunner:
    """封装 Multiwfn 子进程调用（stdin 喂菜单序列，读 stdout）。"""

    def __init__(self):
        self._proc = None

    def run(self, exe_path, fchk_path, input_seq, timeout=300):
        try:
            self._proc = subprocess.Popen(
                [exe_path, fchk_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="ignore",
            )
            stdout, _ = self._proc.communicate(input=input_seq, timeout=timeout)
            return stdout
        except subprocess.TimeoutExpired:
            self.kill()
            return None
        except Exception:
            traceback.print_exc()
            return None
        finally:
            self._proc = None

    def kill(self):
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None


class ChargeCalcWorker(QThread):
    """后台计算电荷的线程，完成后发射 (output, charge_type)。"""
    finished = pyqtSignal(object, str)

    def __init__(self, runner, exe, fchk, input_seq, charge_type):
        super().__init__()
        self.runner = runner
        self.exe = exe
        self.fchk = fchk
        self.input_seq = input_seq
        self.charge_type = charge_type

    def run(self):
        output = self.runner.run(self.exe, self.fchk, self.input_seq)
        self.finished.emit(output, self.charge_type)


# ═══════════════════════════════════════════════════════════════
# 电荷分析面板（作为主窗口右侧的一个 Tab）
# ═══════════════════════════════════════════════════════════════

_TR = {
    "zh": {
        "open_chg": "打开 .chg…",
        "charge_type": "电荷类型:",
        "calc": "计算电荷",
        "color_by_charge": "按电荷着色",
        "reset_view": "重置视角",
        "multiwfn": "Multiwfn:",
        "browse": "浏览",
        "export_csv": "导出 CSV",
        "clear_log": "清空日志",
        "col_idx": "原子",
        "col_elem": "元素",
        "col_charge": "电荷",
        "status_ready": "就绪 — 在主窗口载入 fchk 后点「计算电荷」，或直接「打开 .chg」",
        "no_fchk": "请先在主窗口载入 .fchk 文件",
        "no_chg": "请先选择 .chg 文件",
        "no_exe": "Multiwfn.exe 不存在，请先在主界面⛒️ 路径设置中配置",
        "no_table": "电荷表为空",
        "parse_fail": "解析电荷输出失败，请确认 Multiwfn 菜单序列与本机版本一致",
        "loaded_chg": "已读取: {name}  |  {n} 个原子 (含电荷)",
        "calculating": "正在计算 {fchk} 的 {t} 电荷 …",
        "done": "完成: {n} 个原子的 {t} 电荷",
        "click_hint": "在左侧画布查看分子；勾选「按电荷着色」可把电荷映射为蓝-白-红",
    },
    "en": {
        "open_chg": "Open .chg…",
        "charge_type": "Charge type:",
        "calc": "Calculate",
        "color_by_charge": "Color by charge",
        "reset_view": "Reset View",
        "multiwfn": "Multiwfn:",
        "browse": "Browse",
        "export_csv": "Export CSV",
        "clear_log": "Clear Log",
        "col_idx": "Atom",
        "col_elem": "Elem",
        "col_charge": "Charge",
        "status_ready": "Ready — load .fchk in main window then Calculate, or Open .chg directly",
        "no_fchk": "Please load an .fchk file in the main window first",
        "no_chg": "Please select a .chg file first",
        "no_exe": "Multiwfn.exe not found, configure it in ⛒️ Path Settings first",
        "no_table": "Charge table is empty",
        "parse_fail": "Failed to parse charge output; check the Multiwfn menu sequence matches your version",
        "loaded_chg": "Read: {name}  |  {n} atoms (with charges)",
        "calculating": "Calculating {t} charges for {fchk} …",
        "done": "Done: {n} atoms {t} charges",
        "click_hint": "View the molecule in the left canvas; check Color-by-charge to map charges to blue-white-red",
    },
}


class ChargePanel(QWidget):
    """原子电荷读取/分析面板，3D 可视化复用左侧 OpenGL 画布 (glw)。"""

    def __init__(self, glw=None, multiwfn_path="", get_fchk=None, parent=None,
                 get_multiwfn=None, log_func=None):
        super().__init__(parent)
        self.lang = "zh"
        self.glw = glw                  # CubGLWidget（左侧 OpenGL 画布）
        self.multiwfn_path = multiwfn_path or ""
        self._get_fchk = get_fchk or (lambda: None)
        # Multiwfn 路径统一走主窗口 ⚙️ 路径设置（实时读取），不再在面板里单独设置
        self._get_mw = (get_multiwfn if callable(get_multiwfn)
                        else (lambda: multiwfn_path or ""))
        # 运行输出转发到主窗口「运行日志」
        self._log_func = log_func if callable(log_func) else (lambda msg: None)
        self.charge_type = "ADCH"
        self._charge_cache = {}   # {charge_type: {idx: (elem, charge)}}
        self._runner = MultiwfnRunner()
        self._worker = None
        self._color_by_charge = False

        # 画布选中原子 -> 高亮电荷表对应行
        if self.glw is not None:
            self.glw.add_atom_pick_callback(self._on_canvas_atom_picked)

        self._build_ui()
        self._apply_lang()

    # ── 语言 ──
    def _t(self, key, **fmt):
        s = _TR.get(self.lang, _TR["zh"]).get(key, key)
        return s.format(**fmt) if fmt else s

    def _apply_lang(self):
        self.btn_open_chg.setText(self._t("open_chg"))
        self.lbl_charge_type.setText(self._t("charge_type"))
        self.btn_calc.setText(self._t("calc"))
        self.chk_color.setText(self._t("color_by_charge"))
        self.btn_reset.setText(self._t("reset_view"))
        self.btn_export.setText(self._t("export_csv"))
        self.table.setHorizontalHeaderLabels(
            [self._t("col_idx"), self._t("col_elem"), self._t("col_charge")])
        self._set_status(self._t("status_ready"))

    def set_lang(self, lang):
        """跟随主窗口语言切换（主窗口在 _apply_lang_ui 中调用）。"""
        self.lang = "zh" if lang == "zh" else "en"
        self._apply_lang()

    # ── UI ──
    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        # 工具条：单行（去掉外层圆角矩形框）
        bar = QWidget()
        bv = QHBoxLayout(bar)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(6)

        self.btn_open_chg = QPushButton()
        self.btn_open_chg.clicked.connect(self._browse_chg)
        bv.addWidget(self.btn_open_chg)

        self.lbl_charge_type = QLabel()
        bv.addWidget(self.lbl_charge_type)
        self.combo_charge = QComboBox()
        self.combo_charge.addItems(list(CHARGE_TYPES.keys()))
        self.combo_charge.setCurrentText("ADCH")
        self.combo_charge.currentTextChanged.connect(self._on_charge_type)
        bv.addWidget(self.combo_charge)

        self.btn_calc = QPushButton()
        self.btn_calc.setStyleSheet("font-weight:bold;")
        self.btn_calc.clicked.connect(self._calculate_charges)
        bv.addWidget(self.btn_calc)

        self.chk_color = QCheckBox()
        self.chk_color.toggled.connect(self._on_color_toggle)
        bv.addWidget(self.chk_color)

        self.btn_reset = QPushButton()
        self.btn_reset.clicked.connect(self._reset_view)
        bv.addWidget(self.btn_reset)
        bv.addStretch()

        v.addWidget(bar)

        # 电荷表
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [self._t("col_idx"), self._t("col_elem"), self._t("col_charge")])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        v.addWidget(self.table, stretch=1)

        # 底部按钮（运行输出已整合到主窗口「运行日志」，不再面板内输出）
        btn_row = QHBoxLayout()
        self.btn_export = QPushButton()
        self.btn_export.clicked.connect(self._export_csv)
        btn_row.addWidget(self.btn_export)
        btn_row.addStretch()
        v.addLayout(btn_row)

        # 状态
        self._status = QLabel()
        self._status.setStyleSheet(
            "color:#5C6BC0; font-size:8.5pt; background:#EEF2FF;"
            "border-top:1px solid #C5CAE9; padding:4px 10px;")
        v.addWidget(self._status)

    # ── 状态 / 日志 ──
    def _set_status(self, msg):
        self._status.setText(str(msg))

    def _log(self, msg):
        """运行输出转发到主窗口「运行日志」。"""
        if self._log_func is not None:
            self._log_func(str(msg))

    # ── 浏览 ──
    def _browse_chg(self):
        p, _ = open_file(
            self, "选择 .chg 电荷文件", "", "Multiwfn 电荷文件 (*.chg);;所有文件 (*)")
        if p:
            self._load_chg(p)

    # ── 加载 .chg ──
    def _load_chg(self, path):
        try:
            atoms, charges = parse_chg_file(path)
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))
            return
        if not atoms:
            QMessageBox.warning(self, "提示", self._t("no_chg"))
            return

        bonds = get_bonds_from_fchk(atoms)
        self._charge_cache["CHG"] = {i: (atoms[i - 1][1], charges[i])
                                     for i in charges}
        self.charge_type = "CHG"

        # 推送到左侧 OpenGL 画布并居中
        if self.glw is not None:
            self.glw.set_molecule(atoms, bonds)
            self.glw.frame_to_molecule()

        self._populate_table([(i, atoms[i - 1][1], charges[i]) for i in charges],
                             "CHG")
        self._apply_charge_coloring()
        self._log(self._t("loaded_chg", name=os.path.basename(path), n=len(atoms)))
        self._log(self._t("click_hint"))

    # ── 电荷计算 ──
    def _on_charge_type(self, text):
        self.charge_type = text

    def _calculate_charges(self):
        if self._worker is not None and self._worker.isRunning():
            return
        exe = (self._get_mw() or "").strip()
        fchk = (self._get_fchk() or "").strip()
        if not exe or not os.path.exists(exe):
            QMessageBox.critical(self, "错误", self._t("no_exe"))
            return
        if not fchk or not os.path.exists(fchk):
            QMessageBox.critical(self, "错误", self._t("no_fchk"))
            return

        charge_type = self.combo_charge.currentText()
        if charge_type not in CHARGE_TYPES:
            return
        cfg = CHARGE_TYPES[charge_type]
        self._log(self._t("calculating", t=charge_type,
                          fchk=os.path.basename(fchk)))
        self.btn_calc.setEnabled(False)

        self._worker = ChargeCalcWorker(
            self._runner, exe, fchk, cfg["input_seq"], charge_type)
        self._worker.finished.connect(self._on_calc_done)
        self._worker.start()

    def _on_calc_done(self, output, charge_type):
        self.btn_calc.setEnabled(True)
        if output is None:
            self._log(self._t("parse_fail"))
            return
        charges = parse_multiwfn_charges(output, charge_type)
        if not charges:
            self._log(self._t("parse_fail"))
            return
        self._charge_cache[charge_type] = {
            idx: (elem, charge) for idx, elem, charge in charges}
        self._populate_table(charges, charge_type)
        self._apply_charge_coloring()
        self._log(self._t("done", n=len(charges), t=charge_type))

    # ── 表格 ──
    def _clear_table(self):
        self.table.setRowCount(0)
        self.table.setHorizontalHeaderLabels(
            [self._t("col_idx"), self._t("col_elem"), self._t("col_charge")])

    def _populate_table(self, charges, charge_type):
        self.table.setRowCount(0)
        self.table.setHorizontalHeaderLabels(
            [self._t("col_idx"), self._t("col_elem"), charge_type])
        self.table.setRowCount(len(charges))
        for row, (idx, elem, charge) in enumerate(charges):
            it_idx = QTableWidgetItem(str(idx))
            it_idx.setTextAlignment(Qt.AlignCenter)
            it_elem = QTableWidgetItem(elem)
            it_elem.setTextAlignment(Qt.AlignCenter)
            it_chg = QTableWidgetItem("{:.6f}".format(charge))
            it_chg.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 0, it_idx)
            self.table.setItem(row, 1, it_elem)
            self.table.setItem(row, 2, it_chg)
        self.table.clearSelection()

    def _on_canvas_atom_picked(self, idx):
        """画布中选中原子(idx, 1-based)时，高亮并滚动到电荷表对应行。"""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and str(item.text()) == str(idx):
                self.table.selectRow(row)
                self.table.scrollToItem(item, QAbstractItemView.PositionAtCenter)
                break

    # ── 按电荷着色（作用于左侧 OpenGL 画布） ──
    def _on_color_toggle(self, checked):
        self._color_by_charge = bool(checked)
        self._apply_charge_coloring()

    def _current_charges(self):
        """返回当前 {idx: charge}。"""
        ctype = "CHG" if self.charge_type == "CHG" else self.combo_charge.currentText()
        cache = self._charge_cache.get(ctype, {})
        return {idx: c[1] for idx, c in cache.items()}

    def _apply_charge_coloring(self):
        if self.glw is None:
            return
        if not self._color_by_charge:
            self.glw.set_atom_colors({})
            return
        charges = self._current_charges()
        if not charges:
            self.glw.set_atom_colors({})
            return
        vmax = max(abs(q) for q in charges.values()) or 1.0
        overrides = {idx: charge_to_rgb(q, vmax) for idx, q in charges.items()}
        self.glw.set_atom_colors(overrides)

    def reset_charge_view(self):
        """新分子载入时清空电荷状态与着色（由主窗口调用）。"""
        self._charge_cache.clear()
        self._clear_table()
        if self.glw is not None:
            self.glw.set_atom_colors({})

    # ── 视角 ──
    def _reset_view(self):
        if self.glw is not None:
            self.glw.frame_to_molecule()

    # ── 导出 CSV ──
    def _export_csv(self):
        if self.table.rowCount() == 0:
            QMessageBox.information(self, "提示", self._t("no_table"))
            return
        path, _ = save_file(
            self, "导出电荷 CSV", "charges.csv", "CSV 文件 (*.csv);;所有文件 (*)")
        if not path:
            return
        import csv
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            headers = [self.table.horizontalHeaderItem(c).text()
                       for c in range(self.table.columnCount())]
            w.writerow(headers)
            for r in range(self.table.rowCount()):
                w.writerow([self.table.item(r, c).text()
                            for c in range(self.table.columnCount())])
        self._log("CSV -> {}".format(path))

    # ── 关闭/退出时停掉后台线程 ──
    def shutdown(self):
        if self._worker is not None and self._worker.isRunning():
            self._runner.kill()
            self._worker.wait(2000)


# ═══════════════════════════════════════════════════════════════
# Mayer 键级分析面板（移植自 ChargeViewer 的 Bond Order 功能）
# ═══════════════════════════════════════════════════════════════

_BO_TR = {
    "zh": {
        "calc": "计算键级",
        "reset_view": "重置视角",
        "multiwfn": "Multiwfn:",
        "browse": "浏览",
        "col_pair": "原子对",
        "col_elem": "元素",
        "col_bo": "键级",
        "clear": "清空",
        "status_ready": "就绪 — 载入 fchk 后点「计算键级」，再在左侧画布选两个原子查询",
        "no_fchk": "请先在主窗口载入 .fchk 文件",
        "no_exe": "Multiwfn.exe 不存在，请先在主界面⛒️ 路径设置中配置",
        "calculating": "正在计算 Mayer 键级 …",
        "done": "完成: {n} 对原子键级",
        "parse_fail": "解析键级输出失败，请确认 Multiwfn 菜单序列与本机版本一致",
        "sel_two": "请在左侧画布选择两个原子查询键级",
        "bo_result": "[{a}] {sa} — [{b}] {sb}  键级: {bo:.6f}",
        "bo_none": "[{a}] {sa} — [{b}] {sb}  无键级数据",
    },
    "en": {
        "calc": "Calc BO",
        "reset_view": "Reset View",
        "multiwfn": "Multiwfn:",
        "browse": "Browse",
        "col_pair": "Pair",
        "col_elem": "Elem",
        "col_bo": "Bond Order",
        "clear": "Clear",
        "status_ready": "Ready — load .fchk, click Calc BO, then pick two atoms in the left canvas",
        "no_fchk": "Please load an .fchk file in the main window first",
        "no_exe": "Multiwfn.exe not found, configure it in ⛒️ Path Settings first",
        "calculating": "Calculating Mayer bond orders …",
        "done": "Done: {n} bond order pairs",
        "parse_fail": "Failed to parse bond order output; check the Multiwfn menu sequence matches your version",
        "sel_two": "Pick two atoms in the left canvas to query bond order",
        "bo_result": "[{a}] {sa} — [{b}] {sb}  BO: {bo:.6f}",
        "bo_none": "[{a}] {sa} — [{b}] {sb}  No bond order",
    },
}


class BondOrderPanel(QWidget):
    """Mayer 键级分析面板：后台调 Multiwfn 算键级，左侧画布选两原子查询。"""

    def __init__(self, glw=None, multiwfn_path="", get_fchk=None, parent=None,
                 get_multiwfn=None, log_func=None):
        super().__init__(parent)
        self.lang = "zh"
        self.glw = glw
        self.multiwfn_path = multiwfn_path or ""
        self._get_fchk = get_fchk or (lambda: None)
        # Multiwfn 路径统一走主窗口 ⚙️ 路径设置（实时读取）
        self._get_mw = (get_multiwfn if callable(get_multiwfn)
                        else (lambda: multiwfn_path or ""))
        # 运行输出转发到主窗口「运行日志」
        self._log_func = log_func if callable(log_func) else (lambda msg: None)
        self._bond_orders = {}
        self._runner = MultiwfnRunner()
        self._worker = None

        self._build_ui()
        self._apply_lang()

        # 画布选中原子 -> 若恰好两个则查询键级
        if self.glw is not None:
            self.glw.add_atom_pick_callback(self._on_canvas_atom_picked)

    # ── 语言 ──
    def _t(self, key, **fmt):
        s = _BO_TR.get(self.lang, _BO_TR["zh"]).get(key, key)
        return s.format(**fmt) if fmt else s

    def _apply_lang(self):
        self.btn_calc.setText(self._t("calc"))
        self.btn_reset.setText(self._t("reset_view"))
        self.btn_clear.setText(self._t("clear"))
        self.table.setHorizontalHeaderLabels(
            [self._t("col_pair"), self._t("col_elem"), self._t("col_bo")])
        self._set_status(self._t("status_ready"))

    def set_lang(self, lang):
        """跟随主窗口语言切换（主窗口在 _apply_lang_ui 中调用）。"""
        self.lang = "zh" if lang == "zh" else "en"
        self._apply_lang()

    # ── UI ──
    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        # 工具条：单行（去掉外层圆角矩形框）
        bar = QWidget()
        bv = QHBoxLayout(bar)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(6)

        self.btn_calc = QPushButton()
        self.btn_calc.setStyleSheet("font-weight:bold;")
        self.btn_calc.clicked.connect(self._calculate_bond_order)
        bv.addWidget(self.btn_calc)

        self.btn_reset = QPushButton()
        self.btn_reset.clicked.connect(self._reset_view)
        bv.addWidget(self.btn_reset)

        self.btn_clear = QPushButton()
        self.btn_clear.clicked.connect(self._clear_selection)
        bv.addWidget(self.btn_clear)
        bv.addStretch()

        v.addWidget(bar)

        # 键级表
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [self._t("col_pair"), self._t("col_elem"), self._t("col_bo")])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.cellClicked.connect(self._on_table_row_clicked)
        v.addWidget(self.table, stretch=1)

        self._status = QLabel()
        self._status.setStyleSheet(
            "color:#5C6BC0; font-size:8.5pt; background:#EEF2FF;"
            "border-top:1px solid #C5CAE9; padding:4px 10px;")
        v.addWidget(self._status)

    # ── 状态 ──
    def _set_status(self, msg):
        self._status.setText(str(msg))

    def _log(self, msg):
        """运行输出转发到主窗口「运行日志」。"""
        if self._log_func is not None:
            self._log_func(str(msg))

    # ── 计算键级 ──
    def _calculate_bond_order(self):
        if self._worker is not None and self._worker.isRunning():
            return
        exe = (self._get_mw() or "").strip()
        fchk = (self._get_fchk() or "").strip()
        if not exe or not os.path.exists(exe):
            QMessageBox.critical(self, "错误", self._t("no_exe"))
            return
        if not fchk or not os.path.exists(fchk):
            QMessageBox.critical(self, "错误", self._t("no_fchk"))
            return

        self._log(self._t("calculating"))
        self.btn_calc.setEnabled(False)
        self._worker = ChargeCalcWorker(self._runner, exe, fchk, BO_INPUT_SEQ, "Mayer BO")
        self._worker.finished.connect(self._on_calc_done)
        self._worker.start()

    def _on_calc_done(self, output, _tag):
        self.btn_calc.setEnabled(True)
        if output is None:
            self._log(self._t("parse_fail"))
            return
        bond_orders, valences = parse_mayer_bond_orders(output)
        if not bond_orders:
            self._log(self._t("parse_fail"))
            return
        self._bond_orders = bond_orders
        self._populate_table(bond_orders)
        self._log(self._t("done", n=len(bond_orders)))

    def _populate_table(self, bond_orders):
        self.table.setRowCount(0)
        self.table.setRowCount(len(bond_orders))
        atoms = {a[0]: a[1] for a in self._current_atoms()}
        for row, ((a, b), bo) in enumerate(sorted(bond_orders.items())):
            it_pair = QTableWidgetItem("{}-{}".format(a, b))
            it_pair.setTextAlignment(Qt.AlignCenter)
            it_pair.setData(Qt.UserRole, (a, b))
            it_elem = QTableWidgetItem("{} - {}".format(atoms.get(a, "?"), atoms.get(b, "?")))
            it_elem.setTextAlignment(Qt.AlignCenter)
            it_bo = QTableWidgetItem("{:.6f}".format(bo))
            it_bo.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 0, it_pair)
            self.table.setItem(row, 1, it_elem)
            self.table.setItem(row, 2, it_bo)
        self.table.clearSelection()

    def _current_atoms(self):
        """从画布拿当前原子列表，返回 [(idx_1based, symbol), ...]。"""
        if self.glw is None:
            return []
        atoms = self.glw._atom_list()
        from molcanvas import ELEMENT_SYMBOLS as _ES
        return [(i + 1, _ES.get(anum, "E{}".format(anum))) for i, (anum, _) in enumerate(atoms)]

    # ── 画布选两原子 → 查询键级 ──
    def _on_canvas_atom_picked(self, idx_1based):
        if self.glw is None:
            return
        sel = sorted(self.glw._selected_atoms)  # 0-based
        if len(sel) != 2:
            self._set_status(self._t("sel_two"))
            return
        a, b = sel[0] + 1, sel[1] + 1
        self._query_pair(a, b)

    def _query_pair(self, a, b):
        key = (min(a, b), max(a, b))
        bo = self._bond_orders.get(key, None)
        atoms = dict(self._current_atoms())
        sa, sb = atoms.get(a, "?"), atoms.get(b, "?")
        if bo is not None:
            self._set_status(self._t("bo_result", a=a, sa=sa, b=b, sb=sb, bo=bo))
            self._log(self._t("bo_result", a=a, sa=sa, b=b, sb=sb, bo=bo))
        else:
            self._set_status(self._t("bo_none", a=a, sa=sa, b=b, sb=sb))
        self._highlight_table_row(key)

    def _highlight_table_row(self, key):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.UserRole) == key:
                self.table.selectRow(row)
                self.table.scrollToItem(item, QAbstractItemView.PositionAtCenter)
                break

    # ── 表格行点击 → 在画布选中这两个原子 ──
    def _on_table_row_clicked(self, row, _col):
        item = self.table.item(row, 0)
        if item is None:
            return
        data = item.data(Qt.UserRole)
        if not data:
            return
        a, b = data
        if self.glw is not None:
            self.glw._selected_atoms = [a - 1, b - 1]
            self.glw._regenerate_atoms()
            self.glw.update()
        self._query_pair(a, b)

    # ── 视角 / 清空 ──
    def _reset_view(self):
        if self.glw is not None:
            self.glw.frame_to_molecule()

    def _clear_selection(self):
        if self.glw is not None:
            self.glw._selected_atoms = []
            self.glw._regenerate_atoms()
            self.glw.update()
        self.table.clearSelection()
        self._set_status(self._t("sel_two"))

    def reset_view_state(self):
        """新分子载入时清空键级数据与选中（由主窗口调用）。"""
        self._bond_orders = {}
        self.table.setRowCount(0)
        self._clear_selection()

    def shutdown(self):
        if self._worker is not None and self._worker.isRunning():
            self._runner.kill()
            self._worker.wait(2000)


# ═══════════════════════════════════════════════════════════════
# 独立运行（便于调试：左 OpenGL 画布 + 右电荷面板）
# ═══════════════════════════════════════════════════════════════

def main(argv=None):
    import sys
    from PyQt5.QtWidgets import QApplication, QMainWindow, QSplitter
    from PyQt5.QtGui import QSurfaceFormat
    _fmt = QSurfaceFormat()
    _fmt.setSamples(0)
    _fmt.setDepthBufferSize(24)
    _fmt.setVersion(3, 3)
    _fmt.setProfile(QSurfaceFormat.CoreProfile)
    QSurfaceFormat.setDefaultFormat(_fmt)
    app = QApplication(sys.argv if argv is None else argv)

    from ovcanvas._glwidget import CubGLWidget
    win = QMainWindow()
    win.resize(1100, 700)
    split = QSplitter(Qt.Horizontal)
    glw = CubGLWidget()
    split.addWidget(glw)
    panel = ChargePanel(glw=glw)
    split.addWidget(panel)
    split.setSizes([600, 480])
    win.setCentralWidget(split)
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
