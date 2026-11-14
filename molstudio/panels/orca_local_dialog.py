# -*- coding: utf-8 -*-
"""ORCA 本机计算弹窗（独立模块，先不并入现有分析页）。

功能：载入结构 → 选任务/方法/基组/溶剂 → 生成 ORCA 输入 → 本机运行 →
实时日志 → 解析能量/轨道/频率/几何 → 自动把 .gbw 转成 .molden.input
（给 Multiwfn 做轨道 / ESP / IGMH / AIM 等波函数分析）。
"""

from __future__ import annotations

import os
import re
import time

from PyQt5.QtCore import QSettings, QThread, QTimer, QUrl, Qt, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QScrollArea,
    QTabWidget, QVBoxLayout, QWidget,
)

from molstudio.core import orca_run as ORCA

TEXT = {
    "zh": {
        "title": "ORCA 本机计算",
        "subtitle": "独立模块：生成输入 → 本机运行 → 解析结果 → 转 Molden / "
                    "FCHK（现有轨道 / ESP / IGMH / AIM 页可直接读 fchk）",
        "grp_setup": "计算设置",
        "structure": "结构文件",
        "browse": "浏览…",
        "use_current": "使用主窗口结构",
        "method": "方法",
        "basis": "基组",
        "task": "任务",
        "charge": "电荷",
        "mult": "多重度",
        "nprocs": "核数",
        "maxcore": "每核内存 (MB)",
        "solvent": "溶剂",
        "solvent_none": "无（气相）",
        "solvent_model": "溶剂模型",
        "dispersion": "色散校正",
        "disp_none": "无",
        "nroots": "TD-DFT 激发态数",
        "extra": "附加关键字",
        "workdir": "工作目录",
        "job_name": "任务名",
        "tab_input": "输入预览",
        "tab_log": "运行日志",
        "tab_result": "结果摘要",
        "gen": "生成输入",
        "save_inp": "保存 .inp",
        "run": "开始计算",
        "stop": "停止",
        "molden": "转 Molden/FCHK",
        "open_out": "打开 .out",
        "open_dir": "打开目录",
        "load_struct": "载入结构到主窗口",
        "copy_cmd": "复制命令",
        "close": "关闭",
        "cmd": "命令",
        "hint_no_struct": "请先载入结构文件（xyz / gjf / fchk / log / out）。",
        "hint_ready": "输入已生成，可直接开始计算。",
        "hint_msmpi": "本机 ORCA 为 msmpi 版：核数必须 ≥ 2，否则会报"
                      "找不到串行子程序。",
        "need_struct": "请先载入结构文件",
        "need_method": "请填写方法",
        "running": "正在运行 ORCA…",
        "done": "计算完成",
        "failed": "计算失败",
        "stopped": "已停止",
        "converting": "正在把 .gbw 转成 Molden / fchk…",
        "converted": "已生成 Molden / fchk",
        "convert_fail": "Molden / fchk 转换失败",
        "result_none": "运行结束后在这里显示能量、HOMO/LUMO、频率等结果。",
        "energy": "最终能量 (Hartree)",
        "homo": "HOMO",
        "lumo": "LUMO",
        "gap": "HOMO–LUMO 能隙",
        "freq": "频率",
        "imag": "虚频",
        "opt": "优化收敛",
        "normal": "正常结束",
        "runtime": "运行时间",
        "gbw": ".gbw 文件",
        "molden_path": "Molden 文件",
        "fchk_path": "FCHK 文件",
        "load_fchk": "载入 fchk 到主窗口",
        "load_fchk_done": "已载入 fchk：%s",
        "load_fchk_fail": "载入 fchk 失败：%s",
        "no_main": "当前没有可载入的主窗口。",
        "yes": "是",
        "no": "否",
        "none": "—",
        "log_placeholder": "运行日志会显示在这里…",
        "browse_struct": "选择结构文件",
        "browse_dir": "选择工作目录",
        "no_parent": "当前没有可载入结构的主窗口。",
        "load_fail": "结构载入失败",
        "save_fail": "保存失败",
        "copied": "命令已复制到剪贴板",
        "confirm_run": "将用 ORCA 本机运行该任务，是否继续？",
        "task_labels": {k: v["zh"] for k, v in ORCA.JOB_TYPES.items()},
    },
    "en": {
        "title": "Local ORCA calculation",
        "subtitle": "Standalone module: build input → run locally → parse "
                    "results → convert to Molden / FCHK (existing orbital / "
                    "ESP / IGMH / AIM pages can read the fchk directly)",
        "grp_setup": "Calculation settings",
        "structure": "Structure",
        "browse": "Browse…",
        "use_current": "Use main-window structure",
        "method": "Method",
        "basis": "Basis set",
        "task": "Task",
        "charge": "Charge",
        "mult": "Multiplicity",
        "nprocs": "Cores",
        "maxcore": "Memory / core (MB)",
        "solvent": "Solvent",
        "solvent_none": "None (gas phase)",
        "solvent_model": "Solvent model",
        "dispersion": "Dispersion",
        "disp_none": "None",
        "nroots": "TD-DFT roots",
        "extra": "Extra keywords",
        "workdir": "Working directory",
        "job_name": "Job name",
        "tab_input": "Input preview",
        "tab_log": "Run log",
        "tab_result": "Results",
        "gen": "Build input",
        "save_inp": "Save .inp",
        "run": "Run ORCA",
        "stop": "Stop",
        "molden": "Convert Molden/FCHK",
        "open_out": "Open .out",
        "open_dir": "Open folder",
        "load_struct": "Load structure into main window",
        "copy_cmd": "Copy command",
        "close": "Close",
        "cmd": "Command",
        "hint_no_struct": "Load a structure first (xyz / gjf / fchk / log / out).",
        "hint_ready": "Input is ready. You can start the calculation.",
        "hint_msmpi": "This ORCA build is msmpi: cores must be ≥ 2, otherwise "
                      "the missing serial child programs cause an error.",
        "need_struct": "Load a structure first",
        "need_method": "Method is empty",
        "running": "Running ORCA…",
        "done": "Calculation finished",
        "failed": "Calculation failed",
        "stopped": "Stopped",
        "converting": "Converting .gbw to Molden / fchk…",
        "converted": "Molden / fchk files created",
        "convert_fail": "Molden / fchk conversion failed",
        "result_none": "Energy, HOMO/LUMO, frequencies… will appear here "
                       "after the run.",
        "energy": "Final energy (Hartree)",
        "homo": "HOMO",
        "lumo": "LUMO",
        "gap": "HOMO–LUMO gap",
        "freq": "Frequencies",
        "imag": "Imaginary",
        "opt": "Optimization converged",
        "normal": "Normal termination",
        "runtime": "Run time",
        "gbw": ".gbw file",
        "molden_path": "Molden file",
        "fchk_path": "FCHK file",
        "load_fchk": "Load fchk into main window",
        "load_fchk_done": "fchk loaded: %s",
        "load_fchk_fail": "Could not load fchk: %s",
        "no_main": "No main window is available.",
        "yes": "yes",
        "no": "no",
        "none": "—",
        "log_placeholder": "ORCA output will appear here…",
        "browse_struct": "Choose structure file",
        "browse_dir": "Choose working directory",
        "no_parent": "No main window is available to load the structure.",
        "load_fail": "Could not load structure",
        "save_fail": "Could not save",
        "copied": "Command copied to clipboard",
        "confirm_run": "Run this job with local ORCA?",
        "task_labels": {k: v["en"] for k, v in ORCA.JOB_TYPES.items()},
    },
}


def _read_structure(path):
    """xyz/gjf/fchk/log/out → (symbols, coords)。"""
    path = str(path)
    ext = os.path.splitext(path)[1].lower()
    if ext in (".fchk", ".fch"):
        from molstudio.core.di_local import read_structure
        atoms = read_structure(path)
        return [a[1] for a in atoms], [[float(v) for v in a[3]] for a in atoms]
    from molstudio.core.surface_projection import load_atoms
    symbols, coords = load_atoms(path)
    return [str(s) for s in symbols], [[float(v) for v in row] for row in coords]


class OrcaWorker(QThread):
    """后台生成输入 + 运行 ORCA + 自动转 Molden。"""
    log_line = pyqtSignal(str)
    stage = pyqtSignal(str)
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = dict(config)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        cfg = self.config
        try:
            prepared = ORCA.prepare_job(
                cfg["workdir"], cfg["name"], cfg["symbols"], cfg["coords"],
                charge=cfg["charge"], mult=cfg["mult"], method=cfg["method"],
                basis=cfg["basis"], task=cfg["task"], nprocs=cfg["nprocs"],
                maxcore=cfg["maxcore"], solvent=cfg["solvent"],
                solvent_model=cfg["solvent_model"],
                dispersion=cfg["dispersion"],
                extra_keywords=cfg["extra"], td_nroots=cfg["nroots"],
                orca_exe=cfg["orca_exe"])
            self.stage.emit("输入：%s" % prepared.inp_path)
            self.log_line.emit("[MolStudio] 命令：%s" % prepared.command_str)
            result = ORCA.run_job(
                prepared, orca_exe=cfg["orca_exe"],
                on_log=self.log_line.emit,
                cancel_check=lambda: self._cancel,
                timeout=cfg.get("timeout", 0))
            if self._cancel:
                self.failed.emit("__cancelled__")
                return
            molden = ""
            fchk = ""
            if result.gbw_path and os.path.isfile(result.gbw_path):
                try:
                    self.stage.emit("Molden 转换中…")
                    molden = ORCA.convert_gbw(result.gbw_path, cfg["orca_exe"])
                    result.parsed["molden_path"] = molden
                    self.log_line.emit("[MolStudio] Molden：%s" % molden)
                except Exception as exc:                 # noqa: BLE001
                    self.log_line.emit("[MolStudio] Molden 转换失败：%s" % exc)
            if molden:
                try:
                    self.stage.emit("fchk 转换中（Multiwfn）…")
                    fchk = ORCA.molden_to_fchk(
                        molden, cfg.get("multiwfn_exe", ""))
                    result.parsed["fchk_path"] = fchk
                    self.log_line.emit("[MolStudio] FCHK：%s" % fchk)
                except Exception as exc:                 # noqa: BLE001
                    self.log_line.emit("[MolStudio] FCHK 转换失败：%s" % exc)
            if result.error and not result.parsed.get("terminated_normally"):
                self.failed.emit(result.error)
            else:
                self.finished_ok.emit(result)
        except Exception as exc:                         # noqa: BLE001
            self.failed.emit(str(exc))


class OrcaLocalDialog(QDialog):
    """ORCA 本机计算弹窗。"""

    def __init__(self, parent=None, lang="zh", initial_path="",
                 get_structure=None, orca_exe=""):
        super().__init__(parent)
        self.lang = "en" if str(lang).lower().startswith("en") else "zh"
        self._symbols = []
        self._coords = []
        self._get_structure = get_structure
        self._worker = None
        self._result = None
        self._prepared = None
        self._struct_path = ""
        self._active_task = "sp"
        self._settings = QSettings("MolStudio", "OrcaLocal")
        self._orb_exe = orca_exe or ORCA.find_orca_exe()
        self._mw_exe = self._find_multiwfn()
        self.setWindowTitle(self._t("title"))
        self.resize(1080, 830)
        self.setMinimumSize(920, 700)
        self._build_ui()
        self._restore_settings()
        if self._orb_exe:
            self.lbl_orca.setText("ORCA: %s" % self._orb_exe)
        if initial_path and os.path.isfile(initial_path):
            self._load_structure(initial_path)
        self._refresh_preview()

    # ── 基础 ────────────────────────────────────────────────────────
    def _t(self, key, **fmt):
        table = TEXT.get(self.lang, TEXT["zh"])
        text = table.get(key, key)
        if fmt:
            try:
                text = text.format(**fmt)
            except Exception:                            # noqa: BLE001
                pass
        return text

    def _find_multiwfn(self):
        try:
            from molstudio.core.fchk_orbital import (
                DEFAULT_MULTIWFN, load_config)
            cfg = load_config()
            path = str(cfg.get("multiwfn", "") or "")
            return path if path and os.path.isfile(path) else DEFAULT_MULTIWFN
        except Exception:                                # noqa: BLE001
            return ""

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        title = QLabel(self._t("title"))
        title.setStyleSheet("font-size:17pt;font-weight:700;color:#16233F;")
        sub = QLabel(self._t("subtitle"))
        sub.setWordWrap(True)
        sub.setStyleSheet("color:#5B6A82;font-size:9pt;")
        root.addWidget(title)
        root.addWidget(sub)
        self.lbl_orca = QLabel("ORCA: %s" % (self._orb_exe or "未找到"))
        self.lbl_orca.setStyleSheet("color:#8A97AB;font-size:8.5pt;")
        self.lbl_orca.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.lbl_orca)

        # 设置区
        grp = QGroupBox(self._t("grp_setup"))
        form = QGridLayout(grp)
        form.setContentsMargins(10, 14, 10, 10)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)

        self.edit_struct = QLineEdit()
        self.edit_struct.setPlaceholderText(
            "*.xyz / *.gjf / *.com / *.fchk / *.log / *.out")
        btn_browse = QPushButton(self._t("browse"))
        btn_browse.clicked.connect(self._browse_structure)
        self.btn_use_current = QPushButton(self._t("use_current"))
        self.btn_use_current.clicked.connect(self._use_current_structure)
        row = QHBoxLayout()
        row.addWidget(self.edit_struct, 1)
        row.addWidget(btn_browse)
        row.addWidget(self.btn_use_current)
        form.addWidget(QLabel(self._t("structure")), 0, 0)
        form.addLayout(row, 0, 1, 1, 3)

        self.cmb_method = QComboBox()
        self.cmb_method.setEditable(True)
        self.cmb_method.addItems(ORCA.COMMON_METHODS)
        self.cmb_basis = QComboBox()
        self.cmb_basis.setEditable(True)
        self.cmb_basis.addItems(ORCA.COMMON_BASES)
        form.addWidget(QLabel(self._t("method")), 1, 0)
        form.addWidget(self.cmb_method, 1, 1)
        form.addWidget(QLabel(self._t("basis")), 1, 2)
        form.addWidget(self.cmb_basis, 1, 3)

        self.cmb_task = QComboBox()
        for key in ORCA.JOB_TYPES:
            self.cmb_task.addItem(self._task_label(key), key)
        form.addWidget(QLabel(self._t("task")), 2, 0)
        form.addWidget(self.cmb_task, 2, 1)
        self.cmb_disp = QComboBox()
        self.cmb_disp.addItem(self._t("disp_none"), "")
        for name in ("D3BJ", "D4", "D3ZERO"):
            self.cmb_disp.addItem(name, name)
        form.addWidget(QLabel(self._t("dispersion")), 2, 2)
        form.addWidget(self.cmb_disp, 2, 3)

        self.spin_charge = QSpinBox()
        self.spin_charge.setRange(-5, 5)
        self.spin_mult = QSpinBox()
        self.spin_mult.setRange(1, 10)
        form.addWidget(QLabel(self._t("charge")), 3, 0)
        form.addWidget(self.spin_charge, 3, 1)
        form.addWidget(QLabel(self._t("mult")), 3, 2)
        form.addWidget(self.spin_mult, 3, 3)

        self.spin_nprocs = QSpinBox()
        self.spin_nprocs.setRange(1, 128)
        self.spin_nprocs.setValue(4)
        self.spin_nprocs.setToolTip(self._t("hint_msmpi"))
        self.spin_maxcore = QSpinBox()
        self.spin_maxcore.setRange(100, 200000)
        self.spin_maxcore.setSingleStep(500)
        self.spin_maxcore.setValue(2000)
        form.addWidget(QLabel(self._t("nprocs")), 4, 0)
        form.addWidget(self.spin_nprocs, 4, 1)
        form.addWidget(QLabel(self._t("maxcore")), 4, 2)
        form.addWidget(self.spin_maxcore, 4, 3)

        self.cmb_solvent = QComboBox()
        self.cmb_solvent.addItem(self._t("solvent_none"), "")
        for name in ORCA.COMMON_SOLVENTS:
            self.cmb_solvent.addItem(name, name)
        self.cmb_solvent_model = QComboBox()
        self.cmb_solvent_model.addItem("CPCM", "cpcm")
        self.cmb_solvent_model.addItem("SMD", "smd")
        form.addWidget(QLabel(self._t("solvent")), 5, 0)
        form.addWidget(self.cmb_solvent, 5, 1)
        form.addWidget(QLabel(self._t("solvent_model")), 5, 2)
        form.addWidget(self.cmb_solvent_model, 5, 3)

        self.spin_nroots = QSpinBox()
        self.spin_nroots.setRange(1, 100)
        self.spin_nroots.setValue(10)
        self.lbl_nroots = QLabel(self._t("nroots"))
        form.addWidget(self.lbl_nroots, 6, 0)
        form.addWidget(self.spin_nroots, 6, 1)
        self.lbl_nroots.setVisible(False)
        self.spin_nroots.setVisible(False)

        self.edit_extra = QLineEdit()
        self.edit_extra.setPlaceholderText("例如：TightSCF / SlowConv / %geom ...")
        form.addWidget(QLabel(self._t("extra")), 7, 0)
        form.addWidget(self.edit_extra, 7, 1, 1, 3)

        self.edit_workdir = QLineEdit(self._default_workdir())
        btn_wd = QPushButton(self._t("browse"))
        btn_wd.clicked.connect(self._browse_workdir)
        self.edit_name = QLineEdit("orca_job")
        row_wd = QHBoxLayout()
        row_wd.addWidget(self.edit_workdir, 1)
        row_wd.addWidget(btn_wd)
        form.addWidget(QLabel(self._t("workdir")), 8, 0)
        form.addLayout(row_wd, 8, 1, 1, 2)
        form.addWidget(QLabel(self._t("job_name")), 8, 3)
        form.addWidget(self.edit_name, 8, 4)
        root.addWidget(grp)

        # 页签：输入 / 日志 / 结果
        self.tabs = QTabWidget()
        self.tabs.setMinimumHeight(300)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.preview.setStyleSheet(
            "QPlainTextEdit{font-family:Consolas,'Courier New',monospace;"
            "font-size:9pt;background:#FFFFFF;}")
        self.tabs.addTab(self.preview, self._t("tab_input"))

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.log_view.setPlaceholderText(self._t("log_placeholder"))
        self.log_view.setStyleSheet(
            "QPlainTextEdit{font-family:Consolas,'Courier New',monospace;"
            "font-size:8.5pt;background:#0E1726;color:#D7E2F0;"
            "border:1px solid #1E2A44;}")
        self.tabs.addTab(self.log_view, self._t("tab_log"))
        self.tabs.addTab(self._build_result_tab(), self._t("tab_result"))
        root.addWidget(self.tabs, 1)

        # 底部
        self.status = QLabel(self._t("hint_no_struct"))
        self.status.setStyleSheet("color:#5B6A82;")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(6)
        root.addWidget(self.progress)
        root.addWidget(self.status)

        row_btn = QHBoxLayout()
        self.btn_gen = QPushButton(self._t("gen"))
        self.btn_gen.clicked.connect(self._refresh_preview)
        self.btn_save_inp = QPushButton(self._t("save_inp"))
        self.btn_save_inp.clicked.connect(self._save_input)
        self.btn_copy = QPushButton(self._t("copy_cmd"))
        self.btn_copy.clicked.connect(self._copy_command)
        self.btn_run = QPushButton(self._t("run"))
        self.btn_run.setDefault(True)
        self.btn_run.clicked.connect(self._run)
        self.btn_stop = QPushButton(self._t("stop"))
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop)
        self.btn_close = QPushButton(self._t("close"))
        self.btn_close.clicked.connect(self.reject)
        row_btn.addWidget(self.btn_gen)
        row_btn.addWidget(self.btn_save_inp)
        row_btn.addWidget(self.btn_copy)
        row_btn.addStretch(1)
        row_btn.addWidget(self.btn_stop)
        row_btn.addWidget(self.btn_run)
        row_btn.addWidget(self.btn_close)
        root.addLayout(row_btn)

        # 信号
        for w in (self.cmb_method,):
            w.currentTextChanged.connect(self._schedule_preview)
        for w in (self.cmb_basis,):
            w.currentTextChanged.connect(self._schedule_preview)
        for w in (self.cmb_task, self.cmb_disp, self.cmb_solvent,
                  self.cmb_solvent_model):
            w.currentIndexChanged.connect(self._schedule_preview)
        for w in (self.spin_charge, self.spin_mult, self.spin_nprocs,
                  self.spin_maxcore, self.spin_nroots):
            w.valueChanged.connect(self._schedule_preview)
        for w in (self.edit_extra, self.edit_name, self.edit_workdir):
            w.textChanged.connect(self._schedule_preview)
        self.cmb_solvent.currentIndexChanged.connect(self._toggle_solvent)
        self.cmb_task.currentIndexChanged.connect(self._toggle_task_ui)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(180)
        self._preview_timer.timeout.connect(self._refresh_preview)
        self._toggle_solvent()
        self._toggle_task_ui()

    def _build_result_tab(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        content = QWidget()
        lay = QGridLayout(content)
        lay.setContentsMargins(10, 10, 10, 4)
        lay.setHorizontalSpacing(16)
        lay.setVerticalSpacing(6)
        self._res_labels = {}
        rows = [
            ("energy", self._t("energy")), ("homo", self._t("homo")),
            ("lumo", self._t("lumo")), ("gap", self._t("gap")),
            ("freq", self._t("freq")), ("imag", self._t("imag")),
            ("opt", self._t("opt")), ("normal", self._t("normal")),
            ("runtime", self._t("runtime")), ("gbw", self._t("gbw")),
            ("molden_path", self._t("molden_path")),
            ("fchk_path", self._t("fchk_path")),
        ]
        for i, (key, label) in enumerate(rows):
            r, c = divmod(i, 2)
            lab = QLabel(label)
            lab.setStyleSheet("color:#5B6A82;")
            val = QLabel(self._t("none"))
            val.setWordWrap(True)
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            val.setStyleSheet("color:#16233F;")
            lay.addWidget(lab, r, c * 2)
            lay.addWidget(val, r, c * 2 + 1)
            self._res_labels[key] = val
        self.lbl_result_hint = QLabel(self._t("result_none"))
        self.lbl_result_hint.setWordWrap(True)
        self.lbl_result_hint.setStyleSheet("color:#8A97AB;font-size:8.5pt;")
        lay.addWidget(self.lbl_result_hint, 6, 0, 1, 4)
        lay.setRowStretch(7, 1)
        lay.setColumnStretch(1, 1)
        lay.setColumnStretch(3, 1)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        act = QHBoxLayout()
        act.setSpacing(8)
        self.btn_molden = QPushButton(self._t("molden"))
        self.btn_molden.setEnabled(False)
        self.btn_molden.clicked.connect(self._convert_molden)
        self.btn_load_fchk = QPushButton(self._t("load_fchk"))
        self.btn_load_fchk.setEnabled(False)
        self.btn_load_fchk.clicked.connect(self._load_fchk_into_main)
        self.btn_open_out = QPushButton(self._t("open_out"))
        self.btn_open_out.setEnabled(False)
        self.btn_open_out.clicked.connect(self._open_output)
        self.btn_open_dir = QPushButton(self._t("open_dir"))
        self.btn_open_dir.clicked.connect(self._open_workdir)
        for btn in (self.btn_molden, self.btn_load_fchk,
                    self.btn_open_out, self.btn_open_dir):
            act.addWidget(btn)
        act.addStretch(1)
        outer.addLayout(act)
        return page

    # ── 设置/预填 ──────────────────────────────────────────────────
    def _default_workdir(self):
        base = os.path.expanduser("~")
        try:
            from PyQt5.QtCore import QStandardPaths
            docs = QStandardPaths.writableLocation(
                QStandardPaths.DocumentsLocation)
            if docs:
                base = docs
        except Exception:                                # noqa: BLE001
            pass
        return os.path.join(base, "MolStudio_ORCA")

    def _task_label(self, key):
        return TEXT.get(self.lang, TEXT["zh"])["task_labels"].get(
            key, key)

    def _restore_settings(self):
        s = self._settings
        try:
            self.cmb_method.setCurrentText(
                s.value("method", "B3LYP", type=str))
            self.cmb_basis.setCurrentText(
                s.value("basis", "def2-SVP", type=str))
            self.spin_nprocs.setValue(s.value("nprocs", 4, type=int))
            self.spin_maxcore.setValue(s.value("maxcore", 2000, type=int))
            wd = s.value("workdir", "", type=str)
            if wd:
                self.edit_workdir.setText(wd)
                self.edit_workdir.setCursorPosition(0)
            last = s.value("last_structure", "", type=str)
            if last and os.path.isfile(last):
                self._load_structure(last)
        except Exception:                                # noqa: BLE001
            pass

    def _save_settings(self):
        s = self._settings
        try:
            s.setValue("method", self.cmb_method.currentText().strip())
            s.setValue("basis", self.cmb_basis.currentText().strip())
            s.setValue("nprocs", self.spin_nprocs.value())
            s.setValue("maxcore", self.spin_maxcore.value())
            s.setValue("workdir", self.edit_workdir.text().strip())
            if self._struct_path:
                s.setValue("last_structure", self._struct_path)
            s.sync()
        except Exception:                                # noqa: BLE001
            pass

    # ── 结构 ────────────────────────────────────────────────────────
    def _browse_structure(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self._t("browse_struct"),
            os.path.dirname(self._struct_path) if self._struct_path else "",
            "结构文件 (*.xyz *.gjf *.com *.fchk *.fch *.log *.out);;"
            "所有文件 (*.*)")
        if path:
            self._load_structure(path)

    def _browse_workdir(self):
        path = QFileDialog.getExistingDirectory(
            self, self._t("browse_dir"),
            self.edit_workdir.text().strip() or os.path.expanduser("~"))
        if path:
            self.edit_workdir.setText(path)

    def _use_current_structure(self):
        path = ""
        main = self.parent()
        try:
            if main is not None and getattr(main, "var_path", None) is not None:
                path = main.var_path.text().strip()
            if not path and main is not None:
                path = getattr(main, "_current_fchk", "") or ""
        except Exception:                                # noqa: BLE001
            path = ""
        if path and os.path.isfile(path):
            self._load_structure(path)
            return
        if self._get_structure:
            try:
                symbols, coords, path = self._get_structure()
                self._set_structure(symbols, coords, path)
                return
            except Exception as exc:                     # noqa: BLE001
                QMessageBox.warning(self, self._t("title"),
                                    "%s\n%s" % (self._t("load_fail"), exc))
                return
        QMessageBox.information(self, self._t("title"),
                                self._t("no_parent") + "\n" +
                                self._t("hint_no_struct"))

    def _load_structure(self, path):
        try:
            symbols, coords = _read_structure(path)
        except Exception as exc:                         # noqa: BLE001
            QMessageBox.warning(self, self._t("title"),
                                "%s\n%s" % (self._t("load_fail"), exc))
            return
        self._set_structure(symbols, coords, path)

    def _set_structure(self, symbols, coords, path=""):
        self._symbols = list(symbols)
        self._coords = [list(map(float, xyz)) for xyz in coords]
        self._struct_path = path or ""
        self.edit_struct.setText(path or "")
        self.edit_struct.setCursorPosition(0)
        if path:
            stem = os.path.splitext(os.path.basename(path))[0]
            if not self.edit_name.text().strip() or \
                    self.edit_name.text().strip() == "orca_job":
                self.edit_name.setText(stem + "_orca")
        self._schedule_preview()

    # ── 输入预览 ────────────────────────────────────────────────────
    def _schedule_preview(self, *_args):
        try:
            if self._preview_timer.isActive():
                self._preview_timer.stop()
            self._preview_timer.start()
        except Exception:                                # noqa: BLE001
            self._refresh_preview()

    def _config(self):
        return {
            "symbols": list(self._symbols),
            "coords": [list(x) for x in self._coords],
            "charge": self.spin_charge.value(),
            "mult": self.spin_mult.value(),
            "method": self.cmb_method.currentText().strip(),
            "basis": self.cmb_basis.currentText().strip(),
            "task": str(self.cmb_task.currentData() or "sp"),
            "nprocs": self.spin_nprocs.value(),
            "maxcore": self.spin_maxcore.value(),
            "solvent": str(self.cmb_solvent.currentData() or ""),
            "solvent_model": str(
                self.cmb_solvent_model.currentData() or "cpcm"),
            "dispersion": str(self.cmb_disp.currentData() or ""),
            "extra": self.edit_extra.text().strip(),
            "nroots": self.spin_nroots.value(),
            "workdir": (self.edit_workdir.text().strip()
                        or self._default_workdir()),
            "name": self.edit_name.text().strip() or "orca_job",
            "orca_exe": self._orb_exe,
            "multiwfn_exe": self._mw_exe,
        }

    def _refresh_preview(self, *_args):
        cfg = self._config()
        if not self._symbols:
            self.preview.setPlainText(self._t("hint_no_struct"))
            self.status.setText(self._t("hint_no_struct"))
            return
        if not cfg["method"]:
            self.preview.setPlainText(self._t("need_method"))
            return
        try:
            text = ORCA.build_input(
                cfg["symbols"], cfg["coords"], charge=cfg["charge"],
                mult=cfg["mult"], method=cfg["method"], basis=cfg["basis"],
                task=cfg["task"], nprocs=cfg["nprocs"],
                maxcore=cfg["maxcore"], solvent=cfg["solvent"],
                solvent_model=cfg["solvent_model"],
                dispersion=cfg["dispersion"], extra_keywords=cfg["extra"],
                td_nroots=cfg["nroots"])
        except Exception as exc:                         # noqa: BLE001
            self.preview.setPlainText("[输入生成失败] %s" % exc)
            return
        self.preview.setPlainText(text)
        wd = cfg["workdir"] or self._default_workdir()
        name = cfg["name"]
        self._prepared = None
        self.status.setText("%s  %s" % (
            self._t("hint_ready"),
            os.path.join(wd, name + ".inp")))

    def _save_input(self):
        if not self._symbols:
            QMessageBox.information(self, self._t("title"),
                                    self._t("need_struct"))
            return
        wd = self.edit_workdir.text().strip() or self._default_workdir()
        name = self.edit_name.text().strip() or "orca_job"
        try:
            prepared = ORCA.prepare_job(
                wd, name, self._symbols, self._coords,
                charge=self.spin_charge.value(), mult=self.spin_mult.value(),
                method=self.cmb_method.currentText().strip(),
                basis=self.cmb_basis.currentText().strip(),
                task=str(self.cmb_task.currentData() or "sp"),
                nprocs=self.spin_nprocs.value(),
                maxcore=self.spin_maxcore.value(),
                solvent=str(self.cmb_solvent.currentData() or ""),
                solvent_model=str(self.cmb_solvent_model.currentData()
                                  or "cpcm"),
                dispersion=str(self.cmb_disp.currentData() or ""),
                extra_keywords=self.edit_extra.text().strip(),
                td_nroots=self.spin_nroots.value(),
                orca_exe=self._orb_exe)
            self._prepared = prepared
            self._log("[MolStudio] 已保存输入：%s" % prepared.inp_path)
            self.status.setText(prepared.inp_path)
        except Exception as exc:                         # noqa: BLE001
            QMessageBox.warning(self, self._t("title"),
                                "%s\n%s" % (self._t("save_fail"), exc))

    # ── 运行 ────────────────────────────────────────────────────────
    def _log(self, line):
        self.log_view.appendPlainText(str(line))
        doc = self.log_view.document()
        if doc.blockCount() > 6000:
            cursor = self.log_view.textCursor()
            cursor.movePosition(cursor.Start)
            cursor.select(cursor.LineUnderCursor)
            cursor.removeSelectedText()
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _run(self):
        if not self._symbols:
            QMessageBox.information(self, self._t("title"),
                                    self._t("need_struct"))
            return
        method = self.cmb_method.currentText().strip()
        if not method:
            QMessageBox.information(self, self._t("title"),
                                    self._t("need_method"))
            return
        cfg = self._config()
        cfg["orca_exe"] = self._orb_exe or ORCA.find_orca_exe()
        self._active_task = cfg["task"]
        if not cfg["orca_exe"]:
            QMessageBox.warning(self, self._t("title"),
                                "找不到 orca.exe：请检查 ORCA 安装或环境变量")
            return
        os.makedirs(cfg["workdir"] or self._default_workdir(), exist_ok=True)
        self._save_settings()
        self._save_input()
        self.log_view.clear()
        self.log_view.setPlaceholderText(self._t("log_placeholder"))
        self._log("[MolStudio] %s" % self._t("running"))
        self.tabs.setCurrentIndex(1)
        self.progress.setRange(0, 0)
        self.status.setText(self._t("running"))
        self._set_running(True)
        self._worker = OrcaWorker(cfg, self)
        self._worker.log_line.connect(self._log)
        self._worker.stage.connect(self.status.setText)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _set_running(self, running):
        self.btn_run.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.btn_gen.setEnabled(not running)
        self.btn_save_inp.setEnabled(not running)
        self.btn_molden.setEnabled(False if running else
                                   bool(self._result and self._result.gbw_path))
        self.btn_load_fchk.setEnabled(False if running else bool(
            self._result and (self._result.parsed or {}).get("fchk_path")))
        self.btn_open_out.setEnabled(False if running else
                                     bool(self._result))

    def _stop(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self.status.setText(self._t("stopped"))
            self._log("[MolStudio] 正在终止 ORCA…")

    def _on_done(self, result):
        self._worker = None
        self._result = result
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self._set_running(False)
        self.tabs.setCurrentIndex(2)
        parsed = result.parsed or {}
        self._fill_results(result)
        if parsed.get("terminated_normally"):
            self.status.setText(self._t("done"))
        else:
            self.status.setText(self._t("failed") + "：" +
                                (result.error or ""))
        self.btn_open_out.setEnabled(True)
        self.btn_molden.setEnabled(bool(result.gbw_path))
        self.btn_load_fchk.setEnabled(bool((result.parsed or {}).get(
            "fchk_path")))

    def _on_failed(self, message):
        self._worker = None
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self._set_running(False)
        if message == "__cancelled__":
            self.status.setText(self._t("stopped"))
            return
        self.status.setText(self._t("failed") + "：" + message)
        self._log("[MolStudio] %s" % message)
        QMessageBox.warning(self, self._t("title"),
                            "%s\n%s" % (self._t("failed"), message))

    def _fill_results(self, result):
        p = result.parsed or {}
        val = self._res_labels

        def fmt(x, nd=6):
            if x is None:
                return self._t("none")
            return ("%%.%df" % nd) % x

        val["energy"].setText(fmt(p.get("final_energy")))
        homo = p.get("homo") or {}
        lumo = p.get("lumo") or {}
        if homo:
            val["homo"].setText("%.4f eV  (%.6f Eh)" % (
                homo["energy_ev"], homo["energy_hartree"]))
        if lumo:
            val["lumo"].setText("%.4f eV  (%.6f Eh)" % (
                lumo["energy_ev"], lumo["energy_hartree"]))
        if p.get("homo_lumo_gap_ev") is not None:
            val["gap"].setText("%.4f eV" % p["homo_lumo_gap_ev"])
        freqs = p.get("frequencies") or []
        if freqs:
            val["freq"].setText("%d 个" % len(freqs))
        imag = p.get("imaginary") or []
        if imag:
            val["imag"].setText(", ".join("%.2f" % f for f in imag))
        elif freqs:
            val["imag"].setText(self._t("none"))
        if self._active_task in ("opt", "opt_freq", "ts", "ts_freq"):
            val["opt"].setText(self._t("yes") if p.get("opt_converged")
                               else self._t("no"))
        else:
            val["opt"].setText(self._t("none"))
        val["normal"].setText(self._t("yes") if p.get(
            "terminated_normally") else self._t("no"))
        rt = p.get("run_time_text") or ""
        val["runtime"].setText("%s（%.1f s）" % (rt, result.elapsed)
                               if rt else "%.1f s" % result.elapsed)
        val["gbw"].setText(result.gbw_path or self._t("none"))
        val["molden_path"].setText(p.get("molden_path") or self._t("none"))
        val["fchk_path"].setText(p.get("fchk_path") or self._t("none"))
        self.lbl_result_hint.setText(
            "可直接把 .fchk 载入主窗口（轨道 / ESP / IGMH / AIM / DOS 等页面"
            "都能直接读）；.molden.input 与 .gbw 保留作备份。"
            if self.lang == "zh" else
            "Load the .fchk into the main window; orbital / ESP / IGMH / AIM / "
            "DOS pages can read it directly. The .molden.input and .gbw are "
            "kept as fallbacks.")

    # ── 转换/打开 ──────────────────────────────────────────────────
    def _load_fchk_into_main(self):
        fchk = ""
        if self._result is not None:
            fchk = (self._result.parsed or {}).get("fchk_path", "")
        if not fchk or not os.path.isfile(fchk):
            return
        main = self.parent()
        if main is None or not hasattr(main, "_load_molecule"):
            QMessageBox.information(self, self._t("title"),
                                    self._t("no_main"))
            return
        try:
            if getattr(main, "var_path", None) is not None:
                main.var_path.setText(fchk)
            main._load_molecule(fchk)
            self.status.setText(self._t("load_fchk_done") % fchk)
        except Exception as exc:                         # noqa: BLE001
            QMessageBox.warning(self, self._t("title"),
                                self._t("load_fchk_fail") % exc)

    def _convert_molden(self):
        if not (self._result and self._result.gbw_path):
            return
        self.status.setText(self._t("converting"))
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            parsed = self._result.parsed
            molden = parsed.get("molden_path", "")
            if not (molden and os.path.isfile(molden)):
                molden = ORCA.convert_gbw(self._result.gbw_path,
                                          self._orb_exe)
                parsed["molden_path"] = molden
                self._log("[MolStudio] Molden：%s" % molden)
            self._res_labels["molden_path"].setText(molden)
            fchk = parsed.get("fchk_path", "")
            if not (fchk and os.path.isfile(fchk)):
                fchk = ORCA.molden_to_fchk(molden, self._mw_exe)
                parsed["fchk_path"] = fchk
                self._log("[MolStudio] FCHK：%s" % fchk)
            self._res_labels["fchk_path"].setText(fchk)
            self.btn_load_fchk.setEnabled(True)
            self.status.setText(self._t("converted") + "：" + fchk)
        except Exception as exc:                         # noqa: BLE001
            QMessageBox.warning(self, self._t("title"),
                                "%s\n%s" % (self._t("convert_fail"), exc))
        finally:
            QApplication.restoreOverrideCursor()

    def _open_output(self):
        path = ""
        if self._result is not None:
            path = self._result.prepared.out_path
        elif self._prepared is not None:
            path = self._prepared.out_path
        if path and os.path.isfile(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _open_workdir(self):
        wd = self.edit_workdir.text().strip() or self._default_workdir()
        if os.path.isdir(wd):
            QDesktopServices.openUrl(QUrl.fromLocalFile(wd))

    def _copy_command(self):
        cmd = ""
        if self._result is not None:
            cmd = self._result.prepared.command_str
        elif self._prepared is not None:
            cmd = self._prepared.command_str
        else:
            exe = self._orb_exe or ORCA.find_orca_exe() or "orca.exe"
            name = self.edit_name.text().strip() or "orca_job"
            cmd = ORCA.command_preview(
                [exe, os.path.join(self.edit_workdir.text().strip() or ".",
                                   name + ".inp")])
        QApplication.clipboard().setText(cmd)
        self.status.setText(self._t("copied"))

    def _toggle_solvent(self):
        enabled = bool(self.cmb_solvent.currentData())
        self.cmb_solvent_model.setEnabled(enabled)

    def _toggle_task_ui(self):
        task = str(self.cmb_task.currentData() or "sp")
        show = task == "td"
        self.spin_nroots.setEnabled(show)
        self.spin_nroots.setVisible(show)
        self.lbl_nroots.setVisible(show)

    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
        self._save_settings()
        super().closeEvent(event)


#: 便捷函数：从主窗口打开弹窗
def open_orca_dialog(parent=None, lang="zh", initial_path="",
                     get_structure=None, orca_exe=""):
    dlg = OrcaLocalDialog(parent=parent, lang=lang,
                          initial_path=initial_path,
                          get_structure=get_structure, orca_exe=orca_exe)
    dlg.setModal(False)
    dlg.show()
    return dlg
