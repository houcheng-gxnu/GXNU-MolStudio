# -*- coding: utf-8 -*-
"""ORCA 本机计算页（左侧「常用」下的 ORCA 计算；参数在右侧设置区）。"""

from __future__ import annotations

import os
from pathlib import Path

from PyQt5.QtCore import QSettings, QStandardPaths, QTimer, QUrl, Qt
from PyQt5.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)
from PyQt5.QtGui import QDesktopServices

from molstudio.core import orca_run as ORCA
from molstudio.panels.orca_worker import OrcaWorker

TEXT = {
    "zh": {
        "grp_structure": "结构",
        "grp_calc": "计算设置",
        "src_none": "未载入结构（先在主窗口打开 gjf / xyz / fchk）",
        "src_canvas": "画布结构（{n} 个原子）",
        "src_file": "文件：{name}（{n} 个原子）",
        "read_canvas": "读取画布结构",
        "load_gjf": "载入 gjf / 结构…",
        "refresh": "刷新画布",
        "method": "方法",
        "basis": "基组",
        "task": "任务",
        "dispersion": "色散校正",
        "disp_none": "无",
        "charge": "电荷",
        "mult": "多重度",
        "nprocs": "核数",
        "maxcore": "每核内存 (MB)",
        "solvent": "溶剂",
        "solvent_none": "无（气相）",
        "solvent_model": "溶剂模型",
        "nroots": "TD-DFT 激发态数",
        "extra": "附加关键字",
        "extra_ph": "例如：TightSCF / SlowConv / %geom ...",
        "workdir": "工作目录",
        "job_name": "任务名",
        "browse": "浏览…",
        "gen": "生成输入",
        "save_inp": "保存 .inp",
        "copy": "复制命令",
        "run": "开始计算",
        "stop": "停止",
        "tab_input": "输入预览",
        "tab_log": "运行日志",
        "tab_result": "结果摘要",
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
        "molden": "转 Molden/FCHK",
        "load_fchk": "载入 fchk",
        "open_out": "打开 .out",
        "open_dir": "打开目录",
        "yes": "是",
        "no": "否",
        "none": "—",
        "preview_empty": "载入结构后这里显示 ORCA 输入。",
        "log_ph": "ORCA 输出会显示在这里…",
        "result_hint": "运行完成后显示能量、HOMO/LUMO、频率与输出文件。",
        "status_ready": "就绪",
        "status_no_structure": "请先载入结构（主窗口打开文件或点「载入 gjf」）",
        "status_loaded": "已载入结构：{n} 个原子",
        "status_preview": "输入已生成",
        "status_running": "正在运行 ORCA…",
        "status_done": "计算完成",
        "status_failed": "计算失败：{err}",
        "status_stopped": "已停止",
        "status_converting": "正在转换 Molden / fchk…",
        "status_converted": "已生成 {path}",
        "status_copied": "命令已复制到剪贴板",
        "status_need_structure": "请先载入结构",
        "status_need_method": "请填写方法",
        "status_no_orca": "找不到 orca.exe：请检查 ORCA 安装或环境变量",
        "status_load_fail": "结构载入失败：{err}",
        "status_save_fail": "保存失败：{err}",
        "status_no_main": "没有主窗口可载入 fchk",
        "status_load_fchk": "已载入 fchk：{path}",
        "browse_struct": "选择结构文件",
        "browse_dir": "选择工作目录",
        "orca_exe": "ORCA 可执行文件",
        "browse_exe": "选择 orca.exe",
        "detect": "自动检测",
        "tip_orca_exe": "留空则每次按环境变量 / PATH / 常见目录自动查找；"
                        "指定后就一直用这个 orca.exe",
        "msmpi_hint": "本机 ORCA 为 msmpi 版：核数必须 ≥ 2",
        "tip_workdir": "基目录：每次运行都会在它下面新建时间戳子目录，"
                       ".inp 与 .out / .gbw 等输出都放在里面",
        "tip_open_dir": "在文件管理器中打开本次计算的目录",
        "load_fchk_done": "已把 fchk 载入主窗口",
        "run_hint": "运行前请确认右侧参数",
    },
    "en": {
        "grp_structure": "Structure",
        "grp_calc": "Calculation settings",
        "src_none": "No structure (open gjf / xyz / fchk in the main window)",
        "src_canvas": "Canvas structure ({n} atoms)",
        "src_file": "File: {name} ({n} atoms)",
        "read_canvas": "Read canvas structure",
        "load_gjf": "Load gjf / structure…",
        "refresh": "Refresh canvas",
        "method": "Method",
        "basis": "Basis set",
        "task": "Task",
        "dispersion": "Dispersion",
        "disp_none": "None",
        "charge": "Charge",
        "mult": "Multiplicity",
        "nprocs": "Cores",
        "maxcore": "Memory / core (MB)",
        "solvent": "Solvent",
        "solvent_none": "None (gas phase)",
        "solvent_model": "Solvent model",
        "nroots": "TD-DFT roots",
        "extra": "Extra keywords",
        "extra_ph": "e.g. TightSCF / SlowConv / %geom ...",
        "workdir": "Working directory",
        "job_name": "Job name",
        "browse": "Browse…",
        "gen": "Build input",
        "save_inp": "Save .inp",
        "copy": "Copy command",
        "run": "Run ORCA",
        "stop": "Stop",
        "tab_input": "Input preview",
        "tab_log": "Run log",
        "tab_result": "Results",
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
        "molden": "Convert Molden/FCHK",
        "load_fchk": "Load fchk",
        "open_out": "Open .out",
        "open_dir": "Open folder",
        "yes": "yes",
        "no": "no",
        "none": "—",
        "preview_empty": "Load a structure to preview ORCA input.",
        "log_ph": "ORCA output will appear here…",
        "result_hint": "Energy, HOMO/LUMO, frequencies and output files "
                       "will appear here after the run.",
        "status_ready": "Ready",
        "status_no_structure": "Load a structure first (open a file in the "
                               "main window or click Load gjf)",
        "status_loaded": "Structure loaded: {n} atoms",
        "status_preview": "Input built",
        "status_running": "Running ORCA…",
        "status_done": "Calculation finished",
        "status_failed": "Calculation failed: {err}",
        "status_stopped": "Stopped",
        "status_converting": "Converting Molden / fchk…",
        "status_converted": "Created {path}",
        "status_copied": "Command copied to clipboard",
        "status_need_structure": "Load a structure first",
        "status_need_method": "Method is empty",
        "status_no_orca": "orca.exe not found: check the ORCA installation "
                          "or environment variable",
        "status_load_fail": "Could not load structure: {err}",
        "status_save_fail": "Could not save: {err}",
        "status_no_main": "No main window to load the fchk",
        "status_load_fchk": "fchk loaded: {path}",
        "browse_struct": "Choose structure file",
        "browse_dir": "Choose working directory",
        "orca_exe": "ORCA executable",
        "browse_exe": "Choose orca.exe",
        "detect": "Auto-detect",
        "tip_orca_exe": "Leave empty to auto-detect via environment variables / "
                        "PATH / common folders every time; set it to always use "
                        "this orca.exe",
        "msmpi_hint": "This ORCA build is msmpi: cores must be ≥ 2",
        "tip_workdir": "Base folder: every run creates a fresh timestamped "
                       "subfolder holding the .inp and all .out / .gbw outputs",
        "tip_open_dir": "Open this calculation's folder in the file manager",
        "load_fchk_done": "fchk loaded into the main window",
        "run_hint": "Check the settings before running",
    },
}

_METHODS = ORCA.COMMON_METHODS
_BASES = ORCA.COMMON_BASES
_SOLVENTS = ORCA.COMMON_SOLVENTS


class OrcaPanel(QWidget):
    """ORCA 计算页：左侧共享画布，本页=右侧参数设置区。"""

    def __init__(self, get_structure=None, on_open_structure=None,
                 log_func=None, parent=None, lang="zh", orca_exe="",
                 get_structure_path=None):
        super().__init__(parent)
        self.lang = "en" if str(lang).lower().startswith("en") else "zh"
        self._get_structure = (get_structure
                               if callable(get_structure) else (lambda: None))
        self._get_structure_path = (get_structure_path
                                    if callable(get_structure_path)
                                    else (lambda: ""))
        self._on_open_structure = (on_open_structure
                                   if callable(on_open_structure) else None)
        self._log_func = log_func
        self._symbols = []
        self._coords = []
        self._source_kind = "none"       # none | canvas | file
        self._source_path = ""
        self._worker = None
        self._result = None
        self._prepared = None
        self._active_task = "sp"
        self._status = ("status_ready", {})
        # 工作目录：界面上的框里显示「本次运行目录」，每次运行在基目录下新建
        # 时间戳子目录，避免同目录覆盖上一次的 .inp / .out / .gbw。
        self._workdir_base = ""
        self._workdir_user_edited = False
        self._workdir_auto = True        # 目录仍是自动推出的（未被用户指定）
        self._last_run_dir = ""
        self._auto_name = ""             # 自动生成的任务名（用户改名后清空）
        self._meta_path = ""             # 已应用过电荷/多重度的源文件
        self._settings = QSettings("MolStudio", "OrcaPanel")
        self._orb_exe = orca_exe or ORCA.find_orca_exe()
        self._mw_exe = self._find_multiwfn()
        self._build_ui()
        self._restore_settings()
        self._apply_sources()
        self.set_lang(self.lang)
        QTimer.singleShot(0, self.sync_from_canvas)

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

    def _default_workdir(self):
        """默认「基目录」——每次运行会在它下面新建时间戳子目录。

        载入过结构文件时按 xTB 页的习惯放在文件同级的 ``<文件名>_ORCA``；
        只有画布结构时退回「文档/MolStudio_ORCA」（路径含中文时退到用户
        主目录，避免英文界面里出现中文路径）。
        """
        if self._source_kind == "file" and self._source_path:
            src = Path(self._source_path)
            return str(src.parent / (src.stem + "_ORCA"))
        home = os.path.expanduser("~")
        docs = QStandardPaths.writableLocation(
            QStandardPaths.DocumentsLocation)
        base = docs or home
        # 中文「文档」路径会让英文界面的路径框出现中文；统一退到用户主目录
        if any("\u4e00" <= ch <= "\u9fff" for ch in base):
            base = home
        return os.path.join(base, "MolStudio_ORCA")

    def _resolve_run_dir(self):
        """本次运行的独立目录：``<基目录>/<时间戳>``（同秒重跑加 ``_1``）。"""
        text = self.edit_workdir.text().strip()
        if self._workdir_user_edited and text:
            base = text
        elif self._workdir_base:
            base = self._workdir_base
        elif text:
            base = text
        else:
            base = self._default_workdir()
        return ORCA.resolve_run_dir(base)

    def _on_structure_switched(self):
        """结构换了：用户没自己指定过目录时，基目录跟到新结构旁边。"""
        self._last_run_dir = ""
        if self._workdir_auto and not self._workdir_user_edited:
            self._workdir_base = ""
            self.edit_workdir.setText(self._default_workdir())
            self.edit_workdir.setCursorPosition(0)
        elif self._workdir_user_edited:
            self._workdir_base = self.edit_workdir.text().strip()
        self._workdir_user_edited = False

    def _apply_gjf_meta(self, path):
        """把 gjf/com 头部写的电荷与多重度填进右侧参数（读不到就保持原值）。"""
        try:
            charge, mult = ORCA.read_gjf_charge_mult(path)
        except Exception:                                # noqa: BLE001
            return
        if charge is not None:
            if self.spin_charge.minimum() <= charge <= \
                    self.spin_charge.maximum():
                self.spin_charge.setValue(int(charge))
        if mult is not None:
            if self.spin_mult.minimum() <= mult <= self.spin_mult.maximum():
                self.spin_mult.setValue(int(mult))

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # 结构来源
        self.grp_struct = QGroupBox("")
        gl = QVBoxLayout(self.grp_struct)
        gl.setContentsMargins(8, 12, 8, 8)
        gl.setSpacing(5)
        self.lbl_source = QLabel("")
        self.lbl_source.setStyleSheet("color:#5B6A82;")
        self.lbl_source.setWordWrap(True)
        gl.addWidget(self.lbl_source)
        row_src = QHBoxLayout()
        self.btn_read = QPushButton("")
        self.btn_read.clicked.connect(self.sync_from_canvas)
        self.btn_load = QPushButton("")
        self.btn_load.clicked.connect(self._browse_structure)
        row_src.addWidget(self.btn_read)
        row_src.addWidget(self.btn_load)
        row_src.addStretch(1)
        gl.addLayout(row_src)
        root.addWidget(self.grp_struct)

        # 计算设置
        self.grp_calc = QGroupBox("")
        form = QGridLayout(self.grp_calc)
        form.setContentsMargins(8, 14, 8, 8)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(6)
        self._labels = {}

        def label(key, r, c):
            lab = QLabel("")
            self._labels[key] = lab
            form.addWidget(lab, r, c)

        self.cmb_method = QComboBox()
        self.cmb_method.setEditable(True)
        self.cmb_method.addItems(_METHODS)
        self.cmb_basis = QComboBox()
        self.cmb_basis.setEditable(True)
        self.cmb_basis.addItems(_BASES)
        label("method", 0, 0)
        form.addWidget(self.cmb_method, 0, 1)
        label("basis", 0, 2)
        form.addWidget(self.cmb_basis, 0, 3)

        self.cmb_task = QComboBox()
        for key in ORCA.JOB_TYPES:
            self.cmb_task.addItem("", key)
        self.cmb_disp = QComboBox()
        self.cmb_disp.addItem("", "")
        for disp in ("D3BJ", "D4", "D3ZERO"):
            self.cmb_disp.addItem(disp, disp)
        label("task", 1, 0)
        form.addWidget(self.cmb_task, 1, 1)
        label("dispersion", 1, 2)
        form.addWidget(self.cmb_disp, 1, 3)

        self.spin_charge = QSpinBox()
        self.spin_charge.setRange(-5, 5)
        self.spin_mult = QSpinBox()
        self.spin_mult.setRange(1, 10)
        label("charge", 2, 0)
        form.addWidget(self.spin_charge, 2, 1)
        label("mult", 2, 2)
        form.addWidget(self.spin_mult, 2, 3)

        self.spin_nprocs = QSpinBox()
        self.spin_nprocs.setRange(1, 128)
        self.spin_nprocs.setValue(4)
        self.spin_nprocs.setToolTip(self._t("msmpi_hint"))
        self.spin_maxcore = QSpinBox()
        self.spin_maxcore.setRange(100, 200000)
        self.spin_maxcore.setSingleStep(500)
        self.spin_maxcore.setValue(2000)
        label("nprocs", 3, 0)
        form.addWidget(self.spin_nprocs, 3, 1)
        label("maxcore", 3, 2)
        form.addWidget(self.spin_maxcore, 3, 3)

        self.cmb_solvent = QComboBox()
        self.cmb_solvent.addItem("", "")
        for sol in _SOLVENTS:
            self.cmb_solvent.addItem(sol, sol)
        self.cmb_solvent_model = QComboBox()
        self.cmb_solvent_model.addItem("CPCM", "cpcm")
        self.cmb_solvent_model.addItem("SMD", "smd")
        label("solvent", 4, 0)
        form.addWidget(self.cmb_solvent, 4, 1)
        label("solvent_model", 4, 2)
        form.addWidget(self.cmb_solvent_model, 4, 3)

        self.spin_nroots = QSpinBox()
        self.spin_nroots.setRange(1, 100)
        self.spin_nroots.setValue(10)
        self.lbl_nroots = QLabel("")
        form.addWidget(self.lbl_nroots, 5, 0)
        form.addWidget(self.spin_nroots, 5, 1)
        self.spin_nroots.setVisible(False)
        self.lbl_nroots.setVisible(False)

        self.edit_extra = QLineEdit()
        label("extra", 6, 0)
        form.addWidget(self.edit_extra, 6, 1, 1, 3)

        self.edit_workdir = QLineEdit(self._default_workdir())
        self.btn_workdir = QPushButton("")
        self.btn_workdir.clicked.connect(self._browse_workdir)
        label("workdir", 7, 0)
        form.addWidget(self.edit_workdir, 7, 1, 1, 2)
        form.addWidget(self.btn_workdir, 7, 3)
        self.edit_name = QLineEdit("orca_job")
        label("job_name", 8, 0)
        form.addWidget(self.edit_name, 8, 1, 1, 3)

        # ORCA 可执行文件：留空自动检测，指定后一直用它
        self.edit_orca = QLineEdit(self._orb_exe)
        self.edit_orca.setMinimumWidth(120)
        self.edit_orca.setToolTip(self._t("tip_orca_exe"))
        self.edit_orca.editingFinished.connect(self._save_settings)
        self.btn_browse_orca = QPushButton("")
        self.btn_browse_orca.clicked.connect(self._browse_orca)
        self.btn_detect_orca = QPushButton("")
        self.btn_detect_orca.clicked.connect(self._detect_orca)
        orca_btns = QWidget()
        ob = QHBoxLayout(orca_btns)
        ob.setContentsMargins(0, 0, 0, 0)
        ob.setSpacing(5)
        ob.addWidget(self.btn_browse_orca)
        ob.addWidget(self.btn_detect_orca)
        label("orca_exe", 9, 0)
        form.addWidget(self.edit_orca, 9, 1, 1, 2)
        form.addWidget(orca_btns, 9, 3)
        root.addWidget(self.grp_calc)

        # 按钮
        row = QHBoxLayout()
        self.btn_gen = QPushButton("")
        self.btn_gen.clicked.connect(self._refresh_preview)
        self.btn_save = QPushButton("")
        self.btn_save.clicked.connect(self._save_input)
        self.btn_copy = QPushButton("")
        self.btn_copy.clicked.connect(self._copy_command)
        self.btn_run = QPushButton("")
        self.btn_run.setDefault(True)
        self.btn_run.clicked.connect(self.run)
        self.btn_stop = QPushButton("")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop)
        row.addWidget(self.btn_gen)
        row.addWidget(self.btn_save)
        row.addWidget(self.btn_copy)
        row.addStretch(1)
        row.addWidget(self.btn_stop)
        row.addWidget(self.btn_run)
        root.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(6)
        root.addWidget(self.progress)
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color:#5B6A82;")
        self.lbl_status.setWordWrap(True)
        root.addWidget(self.lbl_status)

        # 页签
        self.tabs = QTabWidget()
        self.tabs.setMinimumHeight(280)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.preview.setStyleSheet(
            "QPlainTextEdit{font-family:Consolas,'Courier New',monospace;"
            "font-size:9pt;background:#FFFFFF;}")
        self.tabs.addTab(self.preview, "")

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.log_view.setStyleSheet(
            "QPlainTextEdit{font-family:Consolas,'Courier New',monospace;"
            "font-size:8.5pt;background:#0E1726;color:#D7E2F0;"
            "border:1px solid #1E2A44;}")
        self.tabs.addTab(self.log_view, "")
        self.tabs.addTab(self._build_result_tab(), "")
        root.addWidget(self.tabs, 1)

        # 信号
        self.cmb_method.currentTextChanged.connect(self._schedule_preview)
        self.cmb_basis.currentTextChanged.connect(self._schedule_preview)
        for w in (self.cmb_task, self.cmb_disp, self.cmb_solvent,
                  self.cmb_solvent_model):
            w.currentIndexChanged.connect(self._schedule_preview)
        for w in (self.spin_charge, self.spin_mult, self.spin_nprocs,
                  self.spin_maxcore, self.spin_nroots):
            w.valueChanged.connect(self._schedule_preview)
        for w in (self.edit_extra, self.edit_name, self.edit_workdir):
            w.textChanged.connect(self._schedule_preview)
        self.edit_name.textEdited.connect(self._on_name_edited)
        self.edit_workdir.textEdited.connect(self._on_workdir_edited)
        self.cmb_solvent.currentIndexChanged.connect(self._toggle_solvent)
        self.cmb_task.currentIndexChanged.connect(self._toggle_task_ui)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(200)
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
        scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}")
        content = QWidget()
        lay = QGridLayout(content)
        lay.setContentsMargins(8, 8, 8, 4)
        lay.setHorizontalSpacing(12)
        lay.setVerticalSpacing(6)
        self._res_labels = {}
        self._res_keys = [
            ("energy", "energy"), ("homo", "homo"), ("lumo", "lumo"),
            ("gap", "gap"), ("freq", "freq"), ("imag", "imag"),
            ("opt", "opt"), ("normal", "normal"), ("runtime", "runtime"),
            ("gbw", "gbw"), ("molden_path", "molden_path"),
            ("fchk_path", "fchk_path"),
        ]
        for i, (key, _tkey) in enumerate(self._res_keys):
            lab = QLabel("")
            self._labels["res_" + key] = lab
            val = QLabel(self._t("none"))
            val.setWordWrap(True)
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            val.setStyleSheet("color:#16233F;")
            lay.addWidget(lab, i, 0)
            lay.addWidget(val, i, 1)
            self._res_labels[key] = val
        self.lbl_result_hint = QLabel("")
        self.lbl_result_hint.setWordWrap(True)
        self.lbl_result_hint.setStyleSheet(
            "color:#8A97AB;font-size:8.5pt;")
        lay.addWidget(self.lbl_result_hint, len(self._res_keys), 0, 1, 2)
        lay.setColumnStretch(1, 1)
        lay.setRowStretch(len(self._res_keys) + 1, 1)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        row = QHBoxLayout()
        self.btn_molden = QPushButton("")
        self.btn_molden.setEnabled(False)
        self.btn_molden.clicked.connect(self._convert_molden)
        self.btn_load_fchk = QPushButton("")
        self.btn_load_fchk.setEnabled(False)
        self.btn_load_fchk.clicked.connect(self._load_fchk)
        self.btn_open_out = QPushButton("")
        self.btn_open_out.setEnabled(False)
        self.btn_open_out.clicked.connect(self._open_output)
        self.btn_open_dir = QPushButton("")
        self.btn_open_dir.clicked.connect(self._open_workdir)
        for btn in (self.btn_molden, self.btn_load_fchk,
                    self.btn_open_out, self.btn_open_dir):
            row.addWidget(btn)
        row.addStretch(1)
        outer.addLayout(row)
        return page

    # ── 语言 ────────────────────────────────────────────────────────
    def set_lang(self, lang):
        self.lang = "en" if str(lang).lower().startswith("en") else "zh"
        self.grp_struct.setTitle(self._t("grp_structure"))
        self.grp_calc.setTitle(self._t("grp_calc"))
        self.btn_read.setText(self._t("read_canvas"))
        self.btn_load.setText(self._t("load_gjf"))
        self.btn_workdir.setText(self._t("browse"))
        self.btn_gen.setText(self._t("gen"))
        self.btn_save.setText(self._t("save_inp"))
        self.btn_copy.setText(self._t("copy"))
        self.btn_run.setText(self._t("run"))
        self.btn_stop.setText(self._t("stop"))
        self.btn_molden.setText(self._t("molden"))
        self.btn_load_fchk.setText(self._t("load_fchk"))
        self.btn_open_out.setText(self._t("open_out"))
        self.btn_open_dir.setText(self._t("open_dir"))
        self.tabs.setTabText(0, self._t("tab_input"))
        self.tabs.setTabText(1, self._t("tab_log"))
        self.tabs.setTabText(2, self._t("tab_result"))
        self.preview.setPlaceholderText(self._t("preview_empty"))
        self.log_view.setPlaceholderText(self._t("log_ph"))
        self.lbl_result_hint.setText(self._t("result_hint"))
        # 表单标签
        for key, lab in self._labels.items():
            if key.startswith("res_"):
                lab.setText(self._t(key[4:]))
            elif key == "nroots":
                self.lbl_nroots.setText(self._t("nroots"))
            else:
                lab.setText(self._t(key))
        # 任务下拉、溶剂/色散首项
        for i in range(self.cmb_task.count()):
            key = str(self.cmb_task.itemData(i))
            self.cmb_task.setItemText(
                i, ORCA.JOB_TYPES.get(key, {}).get(self.lang, key))
        self.lbl_nroots.setText(self._t("nroots"))
        self.cmb_disp.setItemText(0, self._t("disp_none"))
        self.cmb_solvent.setItemText(0, self._t("solvent_none"))
        self.edit_extra.setPlaceholderText(self._t("extra_ph"))
        self.spin_nprocs.setToolTip(self._t("msmpi_hint"))
        self.edit_workdir.setToolTip(self._t("tip_workdir"))
        self.btn_open_dir.setToolTip(self._t("tip_open_dir"))
        self.edit_orca.setToolTip(self._t("tip_orca_exe"))
        self.btn_browse_orca.setText(self._t("browse"))
        self.btn_browse_orca.setToolTip(self._t("browse_exe"))
        self.btn_detect_orca.setText(self._t("detect"))
        self._apply_sources()
        self._render_status()
        if self._result is not None:
            self._fill_results(self._result)
        else:
            self.lbl_result_hint.setText(self._t("result_hint"))
        if not self._symbols:
            self.preview.setPlainText(self._t("preview_empty"))

    def _apply_sources(self):
        n = len(self._symbols)
        if not n:
            self.lbl_source.setText(self._t("src_none"))
        elif self._source_kind == "file" and self._source_path:
            self.lbl_source.setText(self._t(
                "src_file", name=os.path.basename(self._source_path), n=n))
        else:
            self.lbl_source.setText(self._t("src_canvas", n=n))

    def _render_status(self):
        key, fmt = self._status
        self.lbl_status.setText(self._t(key, **fmt))

    def _set_status(self, key, **fmt):
        self._status = (key, fmt)
        self._render_status()

    # ── 结构 ────────────────────────────────────────────────────────
    def sync_from_canvas(self, *_args, force=False):
        got = None
        try:
            got = self._get_structure()
        except Exception:                                # noqa: BLE001
            got = None
        if not got or len(got) < 2:
            if force and not self._symbols:
                self._set_status("status_no_structure")
            return False
        symbols, coords = got
        if not symbols:
            return False
        try:
            symbols = [str(s) for s in symbols]
            coords = [[float(v) for v in row] for row in coords]
        except (TypeError, ValueError):
            return False
        same = (symbols == self._symbols
                and len(coords) == len(self._coords)
                and all(abs(a - b) < 1e-6 for c1, c2 in zip(coords, self._coords)
                        for a, b in zip(c1, c2)))
        if same:
            return True
        self._symbols, self._coords = symbols, coords
        self._source_kind = "canvas"
        self._source_path = ""
        self._apply_sources()
        self._sync_source_meta()
        self._on_structure_switched()
        self._apply_sources()
        self._set_status("status_loaded", n=len(symbols))
        self._refresh_preview()
        return True

    def _sync_source_meta(self):
        """主窗口刚打开的文件：认领来源 + 读电荷/多重度（同一文件只做一次）。

        画布结构如果与主窗口最近打开的文件完全一致，就把它当作「文件来源」，
        任务名和输出基目录都跟着这个文件走；用户改过坐标则仍算画布结构。
        """
        path = ""
        try:
            path = str(self._get_structure_path() or "")
        except Exception:                                # noqa: BLE001
            path = ""
        if not path or path == self._meta_path or not os.path.isfile(path):
            return
        self._meta_path = path
        self._adopt_source_file(path)
        self._apply_gjf_meta(path)

    def _adopt_source_file(self, path):
        """画布坐标与文件一致时，把来源认成该文件（名字 / 基目录跟着走）。"""
        try:
            symbols, coords = ORCA.read_structure_file(path)
        except Exception:                                # noqa: BLE001
            return False
        if [str(s) for s in symbols] != list(self._symbols):
            return False
        if len(coords) != len(self._coords):
            return False
        try:
            same = all(abs(a - b) < 1e-3
                       for c1, c2 in zip(coords, self._coords)
                       for a, b in zip(c1, c2))
        except (TypeError, ValueError):
            return False
        if not same:
            return False
        self._source_kind = "file"
        self._source_path = path
        stem = os.path.splitext(os.path.basename(path))[0]
        current = self.edit_name.text().strip()
        if current in ("", "orca_job") or current == self._auto_name:
            self._auto_name = stem + "_orca"
            self.edit_name.setText(self._auto_name)
        return True

    def _browse_structure(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self._t("browse_struct"),
            os.path.dirname(self._source_path) if self._source_path else "",
            "结构文件 (*.gjf *.com *.xyz *.fchk *.fch *.log *.out);;"
            "所有文件 (*.*)")
        if path:
            self.load_structure_path(path)

    def load_structure_path(self, path):
        """载入 gjf/xyz/fchk/log/out，并通知主窗口把结构画到画布上。

        载入后：任务名跟随文件名（``<文件名>_orca``）、输出基目录跟到文件同级
        的 ``<文件名>_ORCA``、gjf 里写的电荷/多重度填进右侧参数。
        """
        if self._on_open_structure is not None:
            try:
                self._on_open_structure(path)
            except Exception as exc:                     # noqa: BLE001
                self._set_status("status_load_fail", err=exc)
                return False
        try:
            symbols, coords = ORCA.read_structure_file(path)
        except Exception as exc:                         # noqa: BLE001
            self._set_status("status_load_fail", err=exc)
            return False
        self._symbols = [str(s) for s in symbols]
        self._coords = [[float(v) for v in row] for row in coords]
        self._source_kind = "file"
        self._source_path = path
        stem = os.path.splitext(os.path.basename(path))[0]
        current = self.edit_name.text().strip()
        if current in ("", "orca_job") or current == self._auto_name:
            self._auto_name = stem + "_orca"
            self.edit_name.setText(self._auto_name)
        self._meta_path = path
        self._apply_gjf_meta(path)
        self._on_structure_switched()
        self._apply_sources()
        self._set_status("status_loaded", n=len(symbols))
        self._refresh_preview()
        return True

    # ── 输入/运行 ──────────────────────────────────────────────────
    def _schedule_preview(self, *_args):
        try:
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
            "name": (self.edit_name.text().strip() or "orca_job"),
            "orca_exe": self._current_orca_exe(),
            "multiwfn_exe": self._mw_exe,
        }

    def _current_orca_exe(self):
        """当前使用的 orca.exe：手填优先，留空则按环境/PATH/常见目录查找。"""
        text = self.edit_orca.text().strip()
        return text or ORCA.find_orca_exe()

    def _browse_orca(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self._t("browse_exe"),
            os.path.dirname(self.edit_orca.text().strip() or ""),
            "可执行文件 (*.exe);;所有文件 (*.*)")
        if path:
            self.edit_orca.setText(path)
            self._save_settings()

    def _detect_orca(self):
        found = ORCA.find_orca_exe()
        if found:
            self.edit_orca.setText(found)
            self.edit_orca.setCursorPosition(0)
            self._save_settings()
        else:
            self._set_status("status_no_orca")

    def _refresh_preview(self, *_args):
        cfg = self._config()
        if not self._symbols:
            self.preview.setPlainText(self._t("preview_empty"))
            self._set_status("status_no_structure")
            return
        if not cfg["method"]:
            self.preview.setPlainText(self._t("status_need_method"))
            return
        try:
            text = ORCA.build_input(
                cfg["symbols"], cfg["coords"], charge=cfg["charge"],
                mult=cfg["mult"], method=cfg["method"],
                basis=cfg["basis"], task=cfg["task"],
                nprocs=cfg["nprocs"], maxcore=cfg["maxcore"],
                solvent=cfg["solvent"],
                solvent_model=cfg["solvent_model"],
                dispersion=cfg["dispersion"],
                extra_keywords=cfg["extra"], td_nroots=cfg["nroots"])
        except Exception as exc:                         # noqa: BLE001
            self.preview.setPlainText("[input error] %s" % exc)
            return
        self.preview.setPlainText(text)
        self._set_status("status_preview")

    def _save_input(self):
        if not self._symbols:
            self._set_status("status_need_structure")
            return
        cfg = self._config()
        try:
            self._prepared = ORCA.prepare_job(
                cfg["workdir"], cfg["name"], cfg["symbols"], cfg["coords"],
                charge=cfg["charge"], mult=cfg["mult"],
                method=cfg["method"], basis=cfg["basis"], task=cfg["task"],
                nprocs=cfg["nprocs"], maxcore=cfg["maxcore"],
                solvent=cfg["solvent"],
                solvent_model=cfg["solvent_model"],
                dispersion=cfg["dispersion"],
                extra_keywords=cfg["extra"], td_nroots=cfg["nroots"],
                orca_exe=cfg["orca_exe"])
        except Exception as exc:                         # noqa: BLE001
            self._set_status("status_save_fail", err=exc)
            return
        self._log("[MolStudio] %s" % self._prepared.inp_path)
        self._set_status("status_preview")
        return self._prepared

    def _log(self, line):
        self.log_view.appendPlainText(str(line))
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())
        if self._log_func:
            try:
                self._log_func(line)
            except Exception:                            # noqa: BLE001
                pass

    def run(self):
        if not self._symbols:
            self._set_status("status_need_structure")
            return
        cfg = self._config()
        if not cfg["method"]:
            self._set_status("status_need_method")
            return
        if not cfg["orca_exe"]:
            self._set_status("status_no_orca")
            return
        # 一个作业一个文件夹：在基目录下新建时间戳子目录，.inp 与 .out/.gbw
        # 等都落在里面，不同分子、同一分子重跑都不会互相覆盖。
        run_dir = self._resolve_run_dir()
        self.edit_workdir.setText(run_dir)
        # 路径通常是「基目录/时间戳」，光标放末尾才看得见本次的时间戳
        self.edit_workdir.setCursorPosition(len(run_dir))
        self._workdir_base = os.path.dirname(run_dir)
        self._workdir_user_edited = False
        self._last_run_dir = run_dir
        cfg = self._config()
        os.makedirs(run_dir, exist_ok=True)
        self._save_settings()
        self._save_input()
        self.log_view.clear()
        self.tabs.setCurrentIndex(1)
        self.progress.setRange(0, 0)
        self._set_status("status_running")
        self._set_running(True)
        self._active_task = cfg["task"]
        self._worker = OrcaWorker(cfg, self)
        self._worker.log_line.connect(self._log)
        self._worker.stage.connect(self.lbl_status.setText)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def stop(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._set_status("status_stopped")

    def _set_running(self, running):
        self.btn_run.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.btn_gen.setEnabled(not running)
        self.btn_save.setEnabled(not running)
        # 运行中不许改 orca.exe 路径（正在用的是启动时那一份）
        self.edit_orca.setEnabled(not running)
        self.btn_browse_orca.setEnabled(not running)
        self.btn_detect_orca.setEnabled(not running)
        self.btn_molden.setEnabled(False if running else bool(
            self._result and self._result.gbw_path))
        self.btn_load_fchk.setEnabled(False if running else bool(
            self._result and (self._result.parsed or {}).get("fchk_path")))
        self.btn_open_out.setEnabled(False if running else bool(self._result))

    def _on_done(self, result):
        self._worker = None
        self._result = result
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self._set_running(False)
        self.tabs.setCurrentIndex(2)
        self._fill_results(result)
        if result.parsed.get("terminated_normally"):
            self._set_status("status_done")
        else:
            self._set_status("status_failed",
                            err=result.error or "")
        self.btn_molden.setEnabled(bool(result.gbw_path))
        self.btn_load_fchk.setEnabled(bool(
            (result.parsed or {}).get("fchk_path")))
        self.btn_open_out.setEnabled(True)

    def _on_failed(self, message):
        self._worker = None
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self._set_running(False)
        if message == "__cancelled__":
            self._set_status("status_stopped")
            return
        self._set_status("status_failed", err=message)
        self._log("[MolStudio] %s" % message)

    def _fill_results(self, result):
        p = result.parsed or {}
        val = self._res_labels
        fmt = lambda x, nd=6: (self._t("none") if x is None
                               else ("%%.%df" % nd) % x)
        val["energy"].setText(fmt(p.get("final_energy")))
        homo, lumo = p.get("homo") or {}, p.get("lumo") or {}
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
            val["freq"].setText(str(len(freqs)))
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
        val["runtime"].setText(("%s（%.1f s）" % (rt, result.elapsed))
                               if rt else "%.1f s" % result.elapsed)
        val["gbw"].setText(result.gbw_path or self._t("none"))
        val["molden_path"].setText(p.get("molden_path") or self._t("none"))
        val["fchk_path"].setText(p.get("fchk_path") or self._t("none"))
        self.lbl_result_hint.setText(
            "可直接把 .fchk 载入主窗口，现有轨道 / ESP / IGMH / AIM / DOS "
            "页面都能读。" if self.lang == "zh" else
            "Load the .fchk into the main window; orbital / ESP / IGMH / AIM / "
            "DOS pages can read it directly.")

    def _convert_molden(self):
        if not (self._result and self._result.gbw_path):
            return
        self._set_status("status_converting")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            p = self._result.parsed
            molden = p.get("molden_path", "")
            if not (molden and os.path.isfile(molden)):
                molden = ORCA.convert_gbw(self._result.gbw_path,
                                          self._current_orca_exe())
                p["molden_path"] = molden
            fchk = p.get("fchk_path", "")
            if not (fchk and os.path.isfile(fchk)):
                fchk = ORCA.molden_to_fchk(molden, self._mw_exe)
                p["fchk_path"] = fchk
            self._fill_results(self._result)
            self.btn_molden.setEnabled(True)
            self.btn_load_fchk.setEnabled(True)
            self._set_status("status_converted", path=fchk)
        except Exception as exc:                         # noqa: BLE001
            self._set_status("status_failed", err=exc)
        finally:
            QApplication.restoreOverrideCursor()

    def _load_fchk(self):
        fchk = ""
        if self._result is not None:
            fchk = (self._result.parsed or {}).get("fchk_path", "")
        if not fchk or not os.path.isfile(fchk):
            return
        if self._on_open_structure is None:
            self._set_status("status_no_main")
            return
        try:
            self._on_open_structure(fchk)
            self._set_status("status_load_fchk", path=fchk)
        except Exception as exc:                         # noqa: BLE001
            self._set_status("status_failed", err=exc)

    def _open_output(self):
        path = ""
        if self._result is not None:
            path = self._result.prepared.out_path
        elif self._prepared is not None:
            path = self._prepared.out_path
        if path and os.path.isfile(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _open_workdir(self):
        for cand in (self._last_run_dir,
                     (self._result.prepared.workdir
                      if self._result is not None else ""),
                     (self._prepared.workdir
                      if self._prepared is not None else ""),
                     self.edit_workdir.text().strip()
                     or self._default_workdir()):
            if cand and os.path.isdir(cand):
                QDesktopServices.openUrl(QUrl.fromLocalFile(cand))
                return

    def _copy_command(self):
        cmd = ""
        if self._result is not None:
            cmd = self._result.prepared.command_str
        elif self._prepared is not None:
            cmd = self._prepared.command_str
        else:
            cmd = ORCA.command_preview(
                [self._current_orca_exe() or "orca.exe",
                 os.path.join(self.edit_workdir.text().strip() or ".",
                              (self.edit_name.text().strip() or "orca_job")
                              + ".inp")])
        QApplication.clipboard().setText(cmd)
        self._set_status("status_copied")

    def _browse_workdir(self):
        path = QFileDialog.getExistingDirectory(
            self, self._t("browse_dir"),
            self.edit_workdir.text().strip() or os.path.expanduser("~"))
        if path:
            self.edit_workdir.setText(path)
            self._workdir_base = ""
            self._workdir_user_edited = True
            self._workdir_auto = False

    def _toggle_solvent(self):
        self.cmb_solvent_model.setEnabled(bool(self.cmb_solvent.currentData()))

    def _on_name_edited(self, *_args):
        # 用户自己改过任务名后，不再随载入的文件名自动改
        self._auto_name = ""

    def _on_workdir_edited(self, *_args):
        self._workdir_user_edited = True
        self._workdir_auto = False

    def _toggle_task_ui(self):
        show = str(self.cmb_task.currentData() or "sp") == "td"
        self.spin_nroots.setVisible(show)
        self.lbl_nroots.setVisible(show)

    def _restore_settings(self):
        s = self._settings
        try:
            method = s.value("method", "B3LYP", type=str)
            basis = s.value("basis", "def2-SVP", type=str)
            if method:
                self.cmb_method.setCurrentText(method)
            if basis:
                self.cmb_basis.setCurrentText(basis)
            self.spin_nprocs.setValue(s.value("nprocs", 4, type=int))
            self.spin_maxcore.setValue(s.value("maxcore", 2000, type=int))
            wd = s.value("workdir", "", type=str)
            auto = bool(s.value("workdir_auto", True, type=bool))
            # 老版本只存了目录：当作「自动」，让基目录继续跟随结构文件，
            # 否则升级后所有分子都会堆在原来的全局目录里。
            if wd and not auto \
                    and not any("\u4e00" <= ch <= "\u9fff" for ch in wd):
                self.edit_workdir.setText(wd)
                self.edit_workdir.setCursorPosition(0)
                self._workdir_base = wd
            self._workdir_auto = auto
            self.edit_workdir.setCursorPosition(0)
            # 用户指定过的 orca.exe（文件已不存在就退回自动检测）
            saved_orca = s.value("orca", "", type=str).strip()
            if saved_orca and os.path.isfile(saved_orca):
                self.edit_orca.setText(saved_orca)
                self.edit_orca.setCursorPosition(0)
        except Exception:                                # noqa: BLE001
            pass

    def _save_settings(self):
        try:
            self._settings.setValue("method",
                                    self.cmb_method.currentText().strip())
            self._settings.setValue("basis",
                                    self.cmb_basis.currentText().strip())
            self._settings.setValue("nprocs", self.spin_nprocs.value())
            self._settings.setValue("maxcore", self.spin_maxcore.value())
            # 存「基目录」而不是本次的时间戳目录，下次运行仍在其下新建子目录
            self._settings.setValue(
                "workdir",
                self._workdir_base or self.edit_workdir.text().strip())
            self._settings.setValue("workdir_auto",
                                    bool(self._workdir_auto))
            self._settings.setValue("orca", self.edit_orca.text().strip())
            self._settings.sync()
        except Exception:                                # noqa: BLE001
            pass
