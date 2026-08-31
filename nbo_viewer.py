# -*- coding: utf-8 -*-
"""
nbo_viewer.py — NBO 分析面板（整合自 NBOViewer）
=================================================

读取 Gaussian ``pop=nbo`` 日志里的 NBO 轨道与 E(2) 二阶微扰相互作用，配合
``.fchk`` 把 NBO 轨道能量匹配到分子轨道（MO）编号，并可直接在左侧 OpenGL
画布中生成/显示对应 MO 的等值面。

NboPanel 是作为主窗口右侧 QTabWidget 的一个页签使用的面板：

    from nbo_viewer import NboPanel
    panel = NboPanel(glw=app.cub_canvas.glw,
                     multiwfn_path=app.paths["multiwfn"],
                     get_fchk=lambda: app._current_fchk)

本模块解析逻辑移植自 NBOViewer (nbo_parser.py)。
"""

import os
import traceback

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFileDialog, QMessageBox, QFrame, QGroupBox, QInputDialog,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer

from nbo_parser import run_analysis, build_full_overview
from fchk_orbital import gen_cube
from file_dialogs import open_file


# ═══════════════════════════════════════════════════════════════
# 后台线程
# ═══════════════════════════════════════════════════════════════

class NboAnalysisWorker(QThread):
    """后台跑 NBO 分析，完成后发射 (data_dict, text_report)。

    atom1=None 且 atom2=None 时执行「全量概览」（列出所有 NBO 轨道）。
    """
    finished = pyqtSignal(object, object)

    def __init__(self, log_file, atom1, atom2, min_e2, fchk_file):
        super().__init__()
        self.log_file = log_file
        self.atom1 = atom1
        self.atom2 = atom2
        self.min_e2 = min_e2
        self.fchk_file = fchk_file

    def run(self):
        try:
            if self.atom1 is None:
                overview = build_full_overview(self.log_file, self.fchk_file)
                data = {
                    "nbo_overview": overview,
                    "cross_e2_details": [],
                    "single_atom_mode": False,
                    "full_mode": True,
                    "atom1": None,
                    "atom2": None,
                }
                self.finished.emit(data, "")
                return
            text, data = run_analysis(
                self.log_file, self.atom1, self.atom2, self.min_e2,
                self.fchk_file)
            self.finished.emit(data, text)
        except Exception:
            traceback.print_exc()
            self.finished.emit(None, "")


class NboCubeWorker(QThread):
    """后台生成单个 MO 的 cube（调 Multiwfn）。"""
    finished = pyqtSignal(object, int, str)  # (cube_path, mo_num, mo_type)
    error = pyqtSignal(str)

    def __init__(self, fchk, orbital, mo_num, mo_type, multiwfn_exe, work_dir=None):
        super().__init__()
        self.fchk = fchk
        self.orbital = orbital
        self.mo_num = mo_num
        self.mo_type = mo_type
        self.multiwfn_exe = multiwfn_exe
        self.work_dir = work_dir

    def run(self):
        try:
            cube = gen_cube(self.fchk, orbital=self.orbital, grid_quality=2,
                            multiwfn_exe=self.multiwfn_exe, work_dir=self.work_dir)
            if cube:
                self.finished.emit(cube, self.mo_num, self.mo_type)
            else:
                self.error.emit(f"MO #{self.mo_num} cube generation failed")
        except Exception as e:
            self.error.emit(str(e))


# ═══════════════════════════════════════════════════════════════
# NBO 分析面板
# ═══════════════════════════════════════════════════════════════

_NBO_TR = {
    "zh": {
        "open_log": "打开 NBO log…",
        "open_fchk": "打开 fchk…",
        "lbl_log": "NBO log:",
        "placeholder_log": "选择 Gaussian .log/.out 文件…",
        "analyze": "分析",
        "e2_threshold": "E(2) 阈值:",
        "reset_view": "重置视角",
        "clear": "清空",
        "multiwfn": "Multiwfn:",
        "browse": "浏览",
        "nbo_table": "NBO 轨道概览",
        "e2_table": "跨原子 E(2) 相互作用",
        "status_ready": "就绪 — 打开 NBO log，点「分析」看全部 NBO；或左画布选 1/2 个原子查指定原子",
        "no_log": "请先打开 Gaussian NBO 日志文件 (.log/.out)",
        "no_fchk": "未关联 fchk，将无法匹配 MO / 可视化轨道",
        "no_exe": "Multiwfn.exe 不存在，请先在主界面 ⚙️ 路径设置中配置",
        "analyzing": "正在分析…",
        "done_full": "全部 {n} 个 NBO 轨道（选 1/2 个原子可筛选）",
        "done_single": "原子 #{a}: {n} 个 NBO 轨道",
        "done_dual": "原子 #{a} 与 #{b}: {n} 个 NBO + {m} 个跨原子 E(2)",
        "no_nbo": "该选择下没有 NBO 轨道",
        "sel_one_or_two": "请选择 1 个原子查 NBO，或 2 个原子查跨原子 E(2)",
        "double_click": "双击表格行可视化对应 MO",
        "gen_mo": "生成 {mo_type} MO #{mo_num} cube…",
        "loaded_mo": "{mo_type} MO #{mo_num} 已加载到画布",
        "dual_loaded": "{n} 个轨道已叠加到画布",
        "no_mo": "该行没有匹配到 MO（能量容差 0.5 a.u.）",
        "flip_phase": "翻转相位",
        "flip_choose": "选择要翻转的轨道:",
        "flip_all": "翻转全部",
        "flip_none": "画布上还没有轨道，先双击表格行可视化",
        "flip_done_one": "画布轨道 {label} 相位已翻转",
        "flip_done_all": "画布 {n} 个轨道相位已翻转",
        "col_nbo_id": "NBO",
        "col_type": "类型",
        "col_atoms": "原子",
        "col_occ": "占据",
        "col_energy": "能量",
        "col_mo": "MO",
        "col_idx": "#",
        "col_e2": "E(2)",
        "col_stars": "强度",
        "col_donor": "供体",
        "col_acceptor": "受体",
    },
    "en": {
        "open_log": "Open NBO log…",
        "open_fchk": "Open fchk…",
        "lbl_log": "NBO log:",
        "placeholder_log": "Choose a Gaussian .log/.out file…",
        "analyze": "Analyze",
        "e2_threshold": "E(2) threshold:",
        "reset_view": "Reset View",
        "clear": "Clear",
        "multiwfn": "Multiwfn:",
        "browse": "Browse",
        "nbo_table": "NBO ORBITAL OVERVIEW",
        "e2_table": "CROSS-ATOM E(2) INTERACTIONS",
        "status_ready": "Ready — open NBO log, click Analyze for all NBOs, or pick 1/2 atoms to filter",
        "no_log": "Please open a Gaussian NBO log first (.log/.out)",
        "no_fchk": "No fchk linked; MO matching / visualization disabled",
        "no_exe": "Multiwfn.exe not found, configure it in ⚙️ Path Settings first",
        "analyzing": "Analyzing…",
        "done_full": "All {n} NBO orbitals (pick 1/2 atoms to filter)",
        "done_single": "Atom #{a}: {n} NBO orbitals",
        "done_dual": "Atom #{a} & #{b}: {n} NBOs + {m} cross-atom E(2)",
        "no_nbo": "No NBO orbitals for this selection",
        "sel_one_or_two": "Pick 1 atom for NBOs, or 2 atoms for cross-atom E(2)",
        "double_click": "Double-click a row to visualize its MO",
        "gen_mo": "Generating {mo_type} MO #{mo_num} cube…",
        "loaded_mo": "{mo_type} MO #{mo_num} loaded to canvas",
        "dual_loaded": "{n} orbitals overlaid on canvas",
        "no_mo": "No MO matched for this row (0.5 a.u. tolerance)",
        "col_nbo_id": "NBO",
        "col_type": "Type",
        "col_atoms": "Atoms",
        "col_occ": "Occ.",
        "col_energy": "Energy",
        "col_mo": "MO",
        "col_idx": "#",
        "col_e2": "E(2)",
        "col_stars": "Str",
        "col_donor": "Donor",
        "col_acceptor": "Acceptor",
        "flip_phase": "Flip Phase",
        "flip_choose": "Select orbital to flip:",
        "flip_all": "Flip All",
        "flip_none": "No orbitals on canvas — double-click a row to visualize first",
        "flip_done_one": "Canvas orbital {label} phase flipped",
        "flip_done_all": "Flipped {n} canvas orbitals",
    },
}


class NboPanel(QWidget):
    """NBO 分析面板：读 log + 画布选原子 → NBO/E(2) 表，双击可视化 MO。"""

    def __init__(self, glw=None, multiwfn_path="", get_fchk=None, get_style=None,
                 parent=None, get_multiwfn=None, log_func=None):
        super().__init__(parent)
        self.lang = "zh"
        self.glw = glw
        self.multiwfn_path = multiwfn_path or ""
        self._get_fchk = get_fchk or (lambda: None)
        self._get_style = get_style or (lambda: "sob-art")
        # Multiwfn 路径统一走主窗口 ⚙️ 路径设置（实时读取）
        self._get_mw = (get_multiwfn if callable(get_multiwfn)
                        else (lambda: multiwfn_path or ""))
        # 运行输出转发到主窗口「运行日志」
        self._log_func = log_func if callable(log_func) else (lambda msg: None)
        self.log_file = None
        self.fchk_file = None    # 面板内手动/自动关联的 fchk（优先于主窗口 _current_fchk）
        self._analysis_worker = None
        self._cube_worker = None
        self._nbo_data = None      # 最近一次 data_dict
        self._e2_details = []      # cross_e2_details
        self._pending_selection = None
        self._dual_queue = []      # 双轨道可视化：待生成 cube 的 [(mo_type, mo_num), ...]
        self._dual_cubes = []      # 已生成的 cube 路径
        self._dual_entries = []    # 双轨道原始条目（保留标签供翻转选择）
        self._dual_color_pairs = []
        self._canvas_orbitals = [] # 画布当前轨道标签 [(label, cube_path), ...]（翻转选择用）

        self._build_ui()
        self._apply_lang()

        # 画布选中原子 -> 防抖后自动分析
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(300)
        self._debounce.timeout.connect(self._on_selection_settled)
        if self.glw is not None:
            self.glw.add_atom_pick_callback(self._on_canvas_atom_picked)

    # ── 语言 ──
    def _t(self, key, **fmt):
        s = _NBO_TR.get(self.lang, _NBO_TR["zh"]).get(key, key)
        return s.format(**fmt) if fmt else s

    def _apply_lang(self):
        self.btn_open_log.setText(self._t("open_log"))
        self.btn_open_fchk.setText(self._t("open_fchk"))
        self.lbl_log.setText(self._t("lbl_log"))
        self.edit_log.setPlaceholderText(self._t("placeholder_log"))
        self.btn_browse_log.setText(self._t("browse"))
        self.btn_analyze.setText(self._t("analyze"))
        self.lbl_e2.setText(self._t("e2_threshold"))
        self.btn_reset.setText(self._t("reset_view"))
        self.btn_clear.setText(self._t("clear"))
        self.btn_flip.setText(self._t("flip_phase"))
        self.grp_nbo.setTitle(self._t("nbo_table"))
        self.grp_e2.setTitle(self._t("e2_table"))
        self.table_nbo.setHorizontalHeaderLabels([
            self._t("col_nbo_id"), self._t("col_type"), self._t("col_atoms"),
            self._t("col_occ"), self._t("col_energy"), self._t("col_mo")])
        self.table_e2.setHorizontalHeaderLabels([
            self._t("col_idx"), self._t("col_e2"), self._t("col_stars"),
            self._t("col_donor"), self._t("col_acceptor"), self._t("col_mo")])

    def set_lang(self, lang):
        self.lang = "zh" if lang == "zh" else "en"
        self._apply_lang()

    # ── UI ──
    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        # 工具条（一行：载入 + 分析 + E(2) 阈值 + 视图）
        bar = QFrame()
        bar.setStyleSheet(
            "QFrame { background:#FFFFFF; border:1px solid #CBD5E1; border-radius:4px; }"
            "QLabel { color:#4A5568; font-size:9pt; }")
        bv = QHBoxLayout(bar)
        bv.setContentsMargins(8, 4, 8, 4)
        bv.setSpacing(6)

        self.btn_open_log = QPushButton()
        self.btn_open_log.clicked.connect(self._browse_log)
        bv.addWidget(self.btn_open_log)

        self.btn_open_fchk = QPushButton()
        self.btn_open_fchk.clicked.connect(self._browse_fchk)
        bv.addWidget(self.btn_open_fchk)

        self.btn_analyze = QPushButton()
        self.btn_analyze.setStyleSheet("font-weight:bold;")
        self.btn_analyze.clicked.connect(self._on_analyze_clicked)
        bv.addWidget(self.btn_analyze)

        self.lbl_e2 = QLabel()
        bv.addWidget(self.lbl_e2)
        self.edit_min_e2 = QLineEdit("0.5")
        self.edit_min_e2.setMaximumWidth(52)
        bv.addWidget(self.edit_min_e2)

        self.btn_reset = QPushButton()
        self.btn_reset.clicked.connect(self._reset_view)
        bv.addWidget(self.btn_reset)

        self.btn_clear = QPushButton()
        self.btn_clear.clicked.connect(self._clear_selection)
        bv.addWidget(self.btn_clear)

        # 画布翻转相位（支持按轨道选择）
        self.btn_flip = QPushButton()
        self.btn_flip.clicked.connect(self._on_flip_clicked)
        bv.addWidget(self.btn_flip)
        bv.addStretch()

        v.addWidget(bar)

        # NBO log 载入框（对齐主界面共用的 fchk 载入框）
        log_row = QWidget()
        lh = QHBoxLayout(log_row)
        lh.setContentsMargins(0, 0, 0, 0)
        lh.setSpacing(6)
        self.lbl_log = QLabel()
        lh.addWidget(self.lbl_log)
        self.edit_log = QLineEdit()
        self.edit_log.setPlaceholderText("")
        lh.addWidget(self.edit_log, stretch=1)
        self.btn_browse_log = QPushButton()
        self.btn_browse_log.clicked.connect(self._browse_log)
        lh.addWidget(self.btn_browse_log)
        v.addWidget(log_row)

        # NBO 表
        self.grp_nbo = QGroupBox()
        gl = QVBoxLayout(self.grp_nbo)
        gl.setContentsMargins(4, 4, 4, 4)
        self.table_nbo = self._make_table(6)
        self.table_nbo.cellDoubleClicked.connect(self._on_nbo_double_click)
        gl.addWidget(self.table_nbo)
        v.addWidget(self.grp_nbo, stretch=1)

        # E(2) 表
        self.grp_e2 = QGroupBox()
        el = QVBoxLayout(self.grp_e2)
        el.setContentsMargins(4, 4, 4, 4)
        self.table_e2 = self._make_table(6)
        self.table_e2.cellDoubleClicked.connect(self._on_e2_double_click)
        el.addWidget(self.table_e2)
        v.addWidget(self.grp_e2, stretch=1)

    @staticmethod
    def _make_table(ncols):
        t = QTableWidget(0, ncols)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        t.horizontalHeader().setStretchLastSection(True)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSelectionMode(QAbstractItemView.SingleSelection)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.verticalHeader().setVisible(False)
        return t

    # ── 状态/日志 ──
    def _set_status(self, msg):
        """状态消息并入主窗口运行日志（原底部状态栏已移除）。"""
        self._log(msg)

    def _log(self, msg):
        """运行输出转发到主窗口「运行日志」。"""
        if self._log_func is not None:
            self._log_func(str(msg))

    # ── 浏览 ──
    def _browse_log(self):
        p, _ = open_file(
            self, "选择 Gaussian NBO 日志", "",
            "Gaussian 日志 (*.log *.out);;所有文件 (*)")
        if p:
            self._load_log(p)

    def _load_log(self, p):
        """载入 NBO log：回填载入框、自动关联同名 fchk、跑全量分析。"""
        self.edit_log.setText(p)
        self.log_file = p
        self._log("NBO log: " + os.path.basename(p))
        # 自动检测同目录下的同名 .fchk（用于 MO 匹配 + 可视化）
        if not self.fchk_file:
            stem = os.path.splitext(p)[0]
            candidate = stem + ".fchk"
            if os.path.exists(candidate):
                self.fchk_file = candidate
                self._log("自动关联 fchk: " + os.path.basename(candidate))
                self._load_molecule_to_canvas(candidate)
        # 载入后立即做全量概览，让表格有内容
        self._on_analyze_clicked()

    def _browse_fchk(self):
        p, _ = open_file(
            self, "选择 fchk 文件", "",
            "Formatted Checkpoint (*.fchk);;所有文件 (*)")
        if p:
            self.fchk_file = p
            self._log("fchk: " + os.path.basename(p))
            self._load_molecule_to_canvas(p)
            self._on_analyze_clicked()

    def _load_molecule_to_canvas(self, fchk):
        """把 fchk 的分子结构加载到左侧画布（供选原子 + 定位）。"""
        if self.glw is None:
            return
        try:
            from molcanvas import get_atoms_from_fchk, get_bonds_from_fchk
            atoms = get_atoms_from_fchk(fchk)
            bonds = get_bonds_from_fchk(atoms)
            self.glw.set_molecule(atoms, bonds)
            self.glw.frame_to_molecule()
            self._log("分子已加载: {} 个原子".format(len(atoms)))
        except Exception as e:
            self._log("载入分子失败: " + str(e))

    def _resolve_fchk(self):
        """返回用于 MO 匹配 / 可视化的 fchk 路径（面板内 > 主窗口当前）。"""
        f = (self.fchk_file or "").strip()
        if f and os.path.exists(f):
            return f
        f2 = (self._get_fchk() or "").strip()
        return f2 if f2 and os.path.exists(f2) else ""

    # ── 画布选择 → 分析 ──
    def _on_canvas_atom_picked(self, idx_1based):
        if not self.log_file:
            return
        self._debounce.start()

    def _on_selection_settled(self):
        self._on_analyze_clicked()

    def _on_analyze_clicked(self):
        """按当前画布选择跑分析：0 个=全部 NBO，1 个=单原子，2 个=双原子 E(2)。"""
        if not self.log_file:
            self._set_status(self._t("no_log"))
            return
        sel = sorted(self.glw._selected_atoms) if self.glw is not None else []
        if len(sel) == 0:
            self._run_analysis(None, None)
        elif len(sel) == 1:
            self._run_analysis(sel[0] + 1, None)
        elif len(sel) == 2:
            self._run_analysis(sel[0] + 1, sel[1] + 1)
        else:
            self._set_status(self._t("sel_one_or_two"))

    def _run_analysis(self, atom1, atom2):
        fchk = self._resolve_fchk() or None
        try:
            min_e2 = float(self.edit_min_e2.text().strip())
        except ValueError:
            min_e2 = 0.5
        self._set_status(self._t("analyzing"))
        self._analysis_worker = NboAnalysisWorker(
            self.log_file, atom1, atom2, min_e2, fchk)
        self._analysis_worker.finished.connect(self._on_analysis_done)
        self._analysis_worker.start()

    def _on_analysis_done(self, data, text):
        if data is None:
            self._set_status(self._t("no_nbo"))
            return
        self._nbo_data = data
        self._render_nbo_table(data)
        self._render_e2_table(data)

        if data.get("full_mode"):
            n = len(data.get("nbo_overview", []))
            self._set_status(self._t("done_full", n=n))
        elif data.get("single_atom_mode"):
            n = len(data.get("nbo_overview", []))
            self._set_status(self._t("done_single", a=data["atom1"], n=n))
        else:
            n = len(data.get("nbo_overview", []))
            m = len(data.get("cross_e2_details", []))
            self._set_status(self._t(
                "done_dual", a=data["atom1"], b=data["atom2"], n=n, m=m))
        self._log(self._t("double_click"))

    # ── 渲染表格 ──
    def _render_nbo_table(self, data):
        overview = data.get("nbo_overview", [])
        self.table_nbo.setRowCount(0)
        self.table_nbo.setRowCount(len(overview))
        for i, e in enumerate(overview):
            mo = f"{e.get('mo_type','')}#{e.get('mo_num')}" if e.get("mo_num") else "—"
            cells = [
                str(e["nbo_id"]),
                e.get("type_label", e["type"]),
                e.get("atoms_str", ""),
                f"{e['occupancy']:.5f}" if e.get("occupancy") is not None else "—",
                f"{e['energy']:.5f}" if e.get("energy") is not None else "—",
                mo,
            ]
            for j, txt in enumerate(cells):
                item = QTableWidgetItem(txt)
                item.setTextAlignment(Qt.AlignCenter)
                if j == 5 and e.get("mo_num"):
                    item.setData(Qt.UserRole, (e.get("mo_type"), e.get("mo_num")))
                self.table_nbo.setItem(i, j, item)

    def _render_e2_table(self, data):
        details = data.get("cross_e2_details", [])
        self._e2_details = details
        self.table_e2.setRowCount(0)
        self.table_e2.setRowCount(len(details))
        for i, d in enumerate(details):
            mo = []
            if d.get("mo1_num"):
                mo.append(f"{d.get('mo1_type','')}#{d.get('mo1_num')}")
            if d.get("mo2_num"):
                mo.append(f"{d.get('mo2_type','')}#{d.get('mo2_num')}")
            mo_str = " + ".join(mo) if mo else "—"
            cells = [
                str(d["idx"]),
                f"{d['e2']:.2f}",
                d.get("stars", ""),
                d.get("donor_label", ""),
                d.get("acceptor_label", ""),
                mo_str,
            ]
            for j, txt in enumerate(cells):
                item = QTableWidgetItem(txt)
                if j in (1, 2, 5):
                    item.setTextAlignment(Qt.AlignCenter)
                if j == 5 and d.get("mo1_num"):
                    mo_entries = []
                    if d.get("mo1_num"):
                        mo_entries.append((d.get("mo1_type"), d.get("mo1_num")))
                    if d.get("mo2_num"):
                        mo_entries.append((d.get("mo2_type"), d.get("mo2_num")))
                    item.setData(Qt.UserRole, mo_entries)
                self.table_e2.setItem(i, j, item)

    # ── 双击可视化 MO ──
    def _on_nbo_double_click(self, row, _col):
        item = self.table_nbo.item(row, 5)
        if item is None:
            return
        data = item.data(Qt.UserRole)
        if not data:
            self._set_status(self._t("no_mo"))
            return
        mo_type, mo_num = data
        self._visualize_mo(mo_type, mo_num)

    def _on_e2_double_click(self, row, _col):
        item = self.table_e2.item(row, 5)
        if item is None:
            return
        data = item.data(Qt.UserRole)
        if not data:
            self._set_status(self._t("no_mo"))
            return
        # E(2) 双轨道：donor + acceptor 同时可视化
        entries = list(data)
        self._visualize_dual(entries)

    def _apply_style(self):
        """把当前界面样式应用到画布（轨道配色 + 材质）。"""
        if self.glw is None:
            return
        style = self._get_style() or "sob-art"
        self.glw.set_style(style)

    def _visualize_mo(self, mo_type, mo_num):
        fchk = self._resolve_fchk()
        if not fchk or not os.path.exists(fchk):
            self._set_status(self._t("no_fchk"))
            return
        mw = (self._get_mw() or "").strip()
        if not mw or not os.path.exists(mw):
            self._set_status(self._t("no_exe"))
            return
        orbital = str(mo_num) if mo_type == "Alpha" else "-" + str(mo_num)
        self._log(self._t("gen_mo", mo_type=mo_type, mo_num=mo_num))
        self._cube_worker = NboCubeWorker(
            fchk, orbital, mo_num, mo_type, mw)
        self._cube_worker.finished.connect(self._on_cube_done)
        self._cube_worker.error.connect(lambda e: self._set_status(str(e)))
        self._cube_worker.start()

    def _on_cube_done(self, cube_path, mo_num, mo_type):
        if self.glw is not None:
            self._apply_style()          # 单轨道：应用界面样式配色
            self.glw.load(cube_path, 0.05)
            label = f"#{mo_num} ({mo_type})"
            self._canvas_orbitals = [(label, cube_path)]
            # 登记 VMD 同步场景（画布当前 MO）
            self.glw.set_vmd_scene(
                [{"type": "orbital", "vol": cube_path, "iso": 0.05,
                  "label": label}])
        self._log(self._t("loaded_mo", mo_type=mo_type, mo_num=mo_num))

    # ── E(2) 双轨道叠加 ──
    def _visualize_dual(self, entries):
        """donor + acceptor 两个 MO 同时可视化。

        配色：供体用界面样式的正/负相位色，受体用同一对色交换相位，既都跟随
        样式配色，又能区分两个轨道。
        """
        fchk = self._resolve_fchk()
        if not fchk or not os.path.exists(fchk):
            self._set_status(self._t("no_fchk"))
            return
        if not entries:
            return
        entries = entries[:2]
        self._apply_style()
        if self.glw is not None:
            pc = tuple(int(c * 255) for c in self.glw._pc)
            nc = tuple(int(c * 255) for c in self.glw._nc)
            pairs = [(pc, nc)]
            if len(entries) > 1:
                pairs.append((nc, pc))  # 受体：相位色互换
            self._dual_color_pairs = pairs
        else:
            self._dual_color_pairs = []

        self._dual_queue = list(entries)
        self._dual_entries = list(entries)   # 保存标签（队列生成 cube 时会被消费）
        self._dual_cubes = []
        self._set_status(self._t("analyzing"))
        self._log("E(2) 双轨道叠加: " + ", ".join(
            f"{t}#{n}" for t, n in entries))
        self._gen_next_dual_cube()

    def _gen_next_dual_cube(self):
        if not self._dual_queue:
            self._load_dual_cubes()
            return
        mo_type, mo_num = self._dual_queue.pop(0)
        fchk = (self._get_fchk() or "").strip()
        mw = (self._get_mw() or "").strip()
        if not mw or not os.path.exists(mw):
            self._set_status(self._t("no_exe"))
            self._dual_queue.clear()
            return
        orbital = str(mo_num) if mo_type == "Alpha" else "-" + str(mo_num)
        self._log(self._t("gen_mo", mo_type=mo_type, mo_num=mo_num))
        self._cube_worker = NboCubeWorker(
            fchk, orbital, mo_num, mo_type, mw)
        self._cube_worker.finished.connect(self._on_dual_cube_done)
        self._cube_worker.error.connect(lambda e: self._set_status(str(e)))
        self._cube_worker.start()

    def _on_dual_cube_done(self, cube_path, mo_num, mo_type):
        self._dual_cubes.append(cube_path)
        self._gen_next_dual_cube()

    def _load_dual_cubes(self):
        if not self._dual_cubes:
            self._set_status(self._t("no_mo"))
            return
        if self.glw is not None:
            self.glw.load_orbitals(self._dual_cubes, 0.05, self._dual_color_pairs)
            # 登记 VMD 同步场景（E(2) 双轨道叠加；label 供「翻转相位」选择轨道）
            self._canvas_orbitals = [
                (f"#{n} ({t})", c)
                for c, (t, n) in zip(self._dual_cubes, self._dual_entries)]
            self.glw.set_vmd_scene(
                [{"type": "orbital", "vol": c, "iso": 0.05,
                  "label": f"#{n} ({t})"}
                 for c, (t, n) in zip(self._dual_cubes, self._dual_entries)])
        self._log(self._t("dual_loaded", n=len(self._dual_cubes)))

    # ── 画布翻转相位（支持按轨道选择） ──
    def _on_flip_clicked(self):
        """翻转画布轨道相位：单轨道直接翻；多轨道弹出选择（翻转所选 / 翻转全部）。"""
        if self.glw is None:
            return
        labels = [lab for lab, _c in self._canvas_orbitals]
        if not labels:
            self._set_status(self._t("flip_none"))
            return
        if len(labels) == 1:
            ok = self.glw.flip_orbital(0)
            if ok:
                self._log(self._t("flip_done_one", label=labels[0]))
            return
        # 多轨道：弹出选择（轨道列表 + 翻转全部）
        items = labels + [self._t("flip_all")]
        item, ok = QInputDialog.getItem(
            self, self._t("flip_phase"), self._t("flip_choose"),
            items, 0, False)
        if not ok:
            return
        if item == self._t("flip_all"):
            if self.glw.flip_all_orbitals():
                self._log(self._t("flip_done_all", n=len(labels)))
        else:
            try:
                i = labels.index(item)
            except ValueError:
                return
            if self.glw.flip_orbital(i):
                self._log(self._t("flip_done_one", label=item))

    # ── 视角 / 清空 ──
    def _reset_view(self):
        if self.glw is not None:
            self.glw.frame_to_molecule()

    def _clear_selection(self):
        if self.glw is not None:
            self.glw._selected_atoms = []
            self.glw._regenerate_atoms()
            self.glw.update()
        self.table_nbo.setRowCount(0)
        self.table_e2.setRowCount(0)
        self._e2_details = []
        self._set_status(self._t("sel_one_or_two"))

    def reset_view_state(self):
        """新分子载入时清空 NBO 状态（由主窗口调用）。"""
        self.log_file = None
        self._nbo_data = None
        self._e2_details = []
        self._clear_selection()
        if hasattr(self, "edit_log"):
            self.edit_log.clear()
        if self.glw is not None:
            self.glw.set_vmd_scene(None)   # 清除 VMD 同步场景登记

    def shutdown(self):
        for w in (self._analysis_worker, self._cube_worker):
            if w is not None and w.isRunning():
                w.wait(2000)
