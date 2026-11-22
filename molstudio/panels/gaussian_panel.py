# -*- coding: utf-8 -*-
"""高斯计算页（左侧「常用」下的 Gaussian 计算；参数在右侧设置区）。

版面与 ORCA / xTB 页完全同构：结构 → 计算设置（两列表单）→ 按钮行 + 细进度条
→ 状态 → 三页签（输入预览 / 运行日志 / 结果摘要）。

两种模式：

* **常规**：按右侧参数生成 ``.gjf``，本机跑 g16，实时跟随 ``.log``；
* **高斯 × xTB 联用**：勾选后路由里去掉方法关键字、挂上 ``external='...'``，
  高斯只当优化器，每一步的能量/梯度（可含 Hessian）由 xTB 通过
  :mod:`molstudio.tools.gau_xtb` 提供——适合大体系先用 GFN2-xTB 快速预优化。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from PyQt5.QtCore import QSettings, QStandardPaths, QTimer, QUrl, Qt
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from molstudio.core import gaussian_run as G
from molstudio.core import xtb_bridge as BRIDGE
from molstudio.core.orca_run import read_structure_file, resolve_run_dir
from molstudio.core.xtb import METHODS as XTB_METHODS
from molstudio.panels.gaussian_worker import GaussianWorker

_ROUTE_POP_RE = re.compile(r"(?i)\bpop\s*=\s*([A-Za-z0-9()=,\-]+)")


def route_pop_keyword(text):
    """从 gjf 文本（或单行 route）里取 ``pop=...`` 关键词；没有则返回 ``""``。

    这一页会用「方法 / 基组 / 任务」字段重建 route，``pop=saveNBO`` 这种布居
    关键词不在任何字段里，会被静默丢掉——NBO 任务跑完就没有 NBO 数据。所以
    载入 gjf 时要先把 pop 关键词接住，放进「附加关键字」。
    """
    content = str(text or "")
    if not content.strip():
        return ""
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            match = _ROUTE_POP_RE.search(stripped)
            if match:
                return "pop=" + match.group(1)
    match = _ROUTE_POP_RE.search(content)
    return "pop=" + match.group(1) if match else ""

TEXT = {
    "zh": {
        "grp_struct": "结构",
        "grp_calc": "计算设置",
        "src_none": "未载入结构（先在主窗口打开 gjf / xyz / fchk）",
        "src_canvas": "画布结构（{n} 个原子）",
        "src_file": "文件：{name}（{n} 个原子）",
        "read_canvas": "读取画布结构",
        "load_gjf": "载入 gjf / 结构…",
        "nbo_input": "NBO 输入…",
        "method": "方法",
        "basis": "基组",
        "task": "任务",
        "dispersion": "色散校正",
        "disp_none": "无",
        "charge": "电荷",
        "mult": "多重度",
        "nproc": "核数",
        "mem": "内存 (GB)",
        "solvent": "溶剂",
        "solvent_none": "无（气相）",
        "solvent_model": "溶剂模型",
        "extra": "附加关键字",
        "extra_ph": "例如：TightSCF / int=ultrafine / 5D 7F",
        "workdir": "工作目录",
        "job_name": "任务名",
        "g16": "Gaussian 可执行文件",
        "browse": "浏览…",
        "detect": "自动检测",
        "gen": "生成输入",
        "save_inp": "保存 .gjf",
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
        "steps": "优化步数",
        "runtime": "运行时间",
        "log_file": ".log 文件",
        "chk_file": ".chk 文件",
        "fchk_file": "FCHK 文件",
        "convert": "转 FCHK",
        "load_fchk": "载入 fchk",
        "open_log": "打开 .log",
        "open_dir": "打开目录",
        "log_clear": "清空输出",
        "log_copy": "复制输出",
        "steps_bridge": "{n}（xTB）",
        "yes": "是",
        "no": "否",
        "none": "—",
        "preview_empty": "载入结构后这里显示 Gaussian 输入。",
        "log_ph": "Gaussian 输出会显示在这里…",
        "result_hint": "运行完成后显示能量、HOMO/LUMO、频率与输出文件。",
        "status_ready": "就绪",
        "status_no_structure": "请先载入结构（主窗口打开文件或点「载入 gjf」）",
        "status_loaded": "已载入结构：{n} 个原子",
        "status_loaded_pop": (
            "已载入结构：{n} 个原子 · 已把 {kw} 放进「附加关键字」"
            "（本页会重建 route，不接住会丢）"),
        "nbo_pop_filled": (
            "已把 {kw} 填进「附加关键字」——方法/基组请与本页核对，"
            "再点「开始计算」"),
        "nbo_plot_needs_cmd": (
            "NBO plot 模式需要 $NBO 数据块：请用 g16 命令行提交刚保存的 gjf"),
        "status_preview": "输入已生成",
        "status_running": "正在运行 Gaussian…",
        "status_done": "计算完成",
        "status_failed": "计算失败：{err}",
        "status_stopped": "已停止",
        "status_need_structure": "请先载入结构",
        "status_need_method": "请填写方法",
        "status_no_g16": "找不到 g16.exe：请检查 Gaussian 安装或环境变量",
        "status_no_xtb": "找不到 xtb.exe：联用模式需要 xTB",
        "status_save_fail": "生成输入失败：{err}",
        "status_need_charge_mult": "联用模式下电荷/多重度必须与电子数自洽",
        "status_converting": "正在转换 FCHK…",
        "status_converted": "已生成 {path}",
        "status_copied": "命令已复制到剪贴板",
        "status_no_main": "没有主窗口可载入 fchk",
        "status_load_fchk": "已载入 fchk：{path}",
        "browse_struct": "选择结构文件",
        "browse_dir": "选择工作目录",
        "browse_exe": "选择可执行文件",
        "bridge": "高斯 × xTB 联用（External，能量/梯度由 xTB 提供）",
        "bridge_hint": "联用时方法/基组/色散/溶剂都不生效：高斯只负责优化步进，"
                       "能量梯度来自 xTB；路由里不能写方法关键字。",
        "bridge_route": "联用路由：{route}",
        "bridge_cmd": "xTB 每步命令：{cmd}",
        "warn_bridge_not_run": "计算正常结束，但没有检测到 external 调用——联用"
                               "可能没生效（路由里不能有方法关键字）。请在高斯 "
                               ".log 里搜索 Running external command 确认。",
        "xmethod": "xTB 方法",
        "xthreads": "xTB 线程",
        "xexe": "xTB 可执行文件",
        "tip_workdir": "基目录：每次运行都会在它下面新建时间戳子目录，"
                       ".gjf / .log / .chk 都放在里面",
        "tip_open_dir": "在文件管理器中打开本次计算的目录",
        "tip_bridge": "勾选后使用 external= 让 xTB 提供能量与梯度，"
                      "适合大体系预优化；频率任务需要 xTB 的 Hessian",
    },
    "en": {
        "grp_struct": "Structure",
        "grp_calc": "Calculation settings",
        "src_none": "No structure (open gjf / xyz / fchk in the main window)",
        "src_canvas": "Canvas structure ({n} atoms)",
        "src_file": "File: {name} ({n} atoms)",
        "read_canvas": "Read canvas structure",
        "load_gjf": "Load gjf / structure…",
        "nbo_input": "NBO input…",
        "method": "Method",
        "basis": "Basis set",
        "task": "Task",
        "dispersion": "Dispersion",
        "disp_none": "None",
        "charge": "Charge",
        "mult": "Multiplicity",
        "nproc": "Cores",
        "mem": "Memory (GB)",
        "solvent": "Solvent",
        "solvent_none": "None (gas phase)",
        "solvent_model": "Solvent model",
        "extra": "Extra keywords",
        "extra_ph": "e.g. TightSCF / int=ultrafine / 5D 7F",
        "workdir": "Working directory",
        "job_name": "Job name",
        "g16": "Gaussian executable",
        "browse": "Browse…",
        "detect": "Auto-detect",
        "gen": "Build input",
        "save_inp": "Save .gjf",
        "copy": "Copy command",
        "run": "Run Gaussian",
        "stop": "Stop",
        "tab_input": "Input preview",
        "tab_log": "Run log",
        "tab_result": "Result summary",
        "energy": "Final energy (Hartree)",
        "homo": "HOMO",
        "lumo": "LUMO",
        "gap": "HOMO–LUMO gap",
        "freq": "Frequencies",
        "imag": "Imaginary",
        "opt": "Optimization converged",
        "normal": "Normal termination",
        "steps": "Optimization steps",
        "runtime": "Run time",
        "log_file": ".log file",
        "chk_file": ".chk file",
        "fchk_file": "FCHK file",
        "convert": "Convert to FCHK",
        "load_fchk": "Load fchk",
        "open_log": "Open .log",
        "open_dir": "Open folder",
        "log_clear": "Clear output",
        "log_copy": "Copy output",
        "steps_bridge": "{n} (xTB)",
        "yes": "yes",
        "no": "no",
        "none": "—",
        "preview_empty": "Load a structure to preview the Gaussian input.",
        "log_ph": "Gaussian output will appear here…",
        "result_hint": "Energy, HOMO/LUMO, frequencies and output files "
                       "will appear here after the run.",
        "status_ready": "Ready",
        "status_no_structure": "Load a structure first (open a file in the "
                               "main window or click Load gjf)",
        "status_loaded": "Structure loaded: {n} atoms",
        "status_preview": "Input built",
        "status_running": "Running Gaussian…",
        "status_done": "Calculation finished",
        "status_failed": "Calculation failed: {err}",
        "status_stopped": "Stopped",
        "status_need_structure": "Load a structure first",
        "status_need_method": "Method is empty",
        "status_no_g16": "g16.exe not found: check the Gaussian installation "
                         "or environment variable",
        "status_no_xtb": "xtb.exe not found: the bridge mode needs xTB",
        "status_save_fail": "Could not build the input: {err}",
        "status_need_charge_mult": "Bridge mode needs a charge/multiplicity "
                                   "consistent with the electron count",
        "status_converting": "Converting to FCHK…",
        "status_converted": "Created {path}",
        "status_copied": "Command copied to clipboard",
        "status_loaded_pop": (
            "Structure loaded: {n} atoms · moved {kw} into Extra keywords "
            "(this page rebuilds the route)"),
        "nbo_pop_filled": (
            "{kw} moved into Extra keywords — check the method/basis here, "
            "then Run Gaussian"),
        "nbo_plot_needs_cmd": (
            "NBO plot mode needs the $NBO data block: submit the saved gjf "
            "with g16 on the command line"),
        "status_no_main": "No main window to load the fchk",
        "status_load_fchk": "fchk loaded: {path}",
        "browse_struct": "Choose structure file",
        "browse_dir": "Choose working directory",
        "browse_exe": "Choose executable",
        "bridge": "Gaussian × xTB bridge (external energy/gradient)",
        "bridge_hint": "In bridge mode method/basis/dispersion/solvent are "
                       "ignored: Gaussian only drives the optimization and "
                       "xTB supplies energy and gradient.",
        "bridge_route": "Bridge route: {route}",
        "bridge_cmd": "xTB command per step: {cmd}",
        "warn_bridge_not_run": "The job ended normally but no external call was "
                               "detected — the bridge probably did not run "
                               "(a method keyword in the route disables "
                               "external=). Search the .log for "
                               "'Running external command'.",
        "xmethod": "xTB method",
        "xthreads": "xTB threads",
        "xexe": "xTB executable",
        "tip_workdir": "Base folder: every run creates a fresh timestamped "
                       "subfolder holding the .gjf / .log / .chk",
        "tip_open_dir": "Open this calculation's folder in the file manager",
        "tip_bridge": "Use external= so xTB supplies energy and gradient; "
                      "handy for pre-optimizing large systems",
    },
}


def _inverse_symbols():
    from molstudio.core.fchk_orbital import ELEMENT_SYMBOLS
    return {str(sym).capitalize(): int(z) for z, sym in ELEMENT_SYMBOLS.items()}


_SYMBOL_TO_Z = _inverse_symbols()


class GaussianPanel(QWidget):
    """高斯计算页：左侧共享画布，本页=右侧参数设置区。"""

    def __init__(self, get_structure=None, on_open_structure=None,
                 log_func=None, parent=None, lang="zh", g16_exe="",
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
        self._source_kind = "none"        # none | canvas | file
        self._source_path = ""
        self._worker = None
        self._result = None
        self._prepared = None
        self._active_task = "sp"
        self._status = ("status_ready", {})
        self._workdir_base = ""
        self._workdir_user_edited = False
        self._workdir_auto = True
        self._last_run_dir = ""
        self._auto_name = ""
        self._meta_path = ""
        self._settings = QSettings("MolStudio", "GaussianPanel")
        self._g16_exe = g16_exe or G.find_gaussian()
        self._formchk_exe = G.find_formchk(self._g16_exe)
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

    def _default_workdir(self):
        """默认「基目录」——每次运行在它下面新建时间戳子目录。"""
        if self._source_kind == "file" and self._source_path:
            src = Path(self._source_path)
            return str(src.parent / (src.stem + "_GAUSS"))
        home = os.path.expanduser("~")
        docs = QStandardPaths.writableLocation(
            QStandardPaths.DocumentsLocation)
        base = docs or home
        if any("\u4e00" <= ch <= "\u9fff" for ch in base):
            base = home
        return os.path.join(base, "MolStudio_Gaussian")

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
        return resolve_run_dir(base)

    def _on_structure_switched(self):
        """结构换了：用户没指定过目录时，基目录跟到新结构旁边。"""
        self._last_run_dir = ""
        if self._workdir_auto and not self._workdir_user_edited:
            self._workdir_base = ""
            self.edit_workdir.setText(self._default_workdir())
            self.edit_workdir.setCursorPosition(0)
        elif self._workdir_user_edited:
            self._workdir_base = self.edit_workdir.text().strip()
        self._workdir_user_edited = False

    def _apply_gjf_meta(self, path):
        try:
            charge, mult = G.read_gjf_charge_mult(path)
        except Exception:                                # noqa: BLE001
            return
        if charge is not None and self.spin_charge.minimum() <= charge <= \
                self.spin_charge.maximum():
            self.spin_charge.setValue(int(charge))
        if mult is not None and self.spin_mult.minimum() <= mult <= \
                self.spin_mult.maximum():
            self.spin_mult.setValue(int(mult))

    # ── UI ──────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        root.addWidget(self._build_source_group())
        root.addWidget(self._build_calc_group())
        root.addLayout(self._build_action_row())

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(6)
        root.addWidget(self.progress)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color:#5B6A82;")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.lbl_status)

        root.addWidget(self._build_tabs(), 1)

    def _build_source_group(self):
        self.grp_struct = QGroupBox("")
        gl = QVBoxLayout(self.grp_struct)
        gl.setContentsMargins(8, 12, 8, 8)
        gl.setSpacing(5)
        self.lbl_source = QLabel("")
        self.lbl_source.setStyleSheet("color:#5B6A82;")
        self.lbl_source.setWordWrap(True)
        gl.addWidget(self.lbl_source)
        row = QHBoxLayout()
        self.btn_read = QPushButton("")
        self.btn_read.clicked.connect(self.sync_from_canvas)
        self.btn_load = QPushButton("")
        self.btn_load.clicked.connect(self._browse_structure)
        self.btn_nbo_input = QPushButton("")
        self.btn_nbo_input.clicked.connect(self._open_nbo_input)
        row.addWidget(self.btn_read)
        row.addWidget(self.btn_load)
        row.addWidget(self.btn_nbo_input)
        row.addStretch(1)
        gl.addLayout(row)
        return self.grp_struct

    def _build_calc_group(self):
        self.grp_calc = QGroupBox("")
        form = QGridLayout(self.grp_calc)
        form.setContentsMargins(8, 14, 8, 8)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(6)

        def label(key, r, c):
            lab = QLabel("")
            self._labels[key] = lab
            form.addWidget(lab, r, c)
            return lab

        self._labels = {}
        self.cmb_method = QComboBox()
        self.cmb_method.setEditable(True)
        self.cmb_method.addItems(G.COMMON_METHODS)
        self.cmb_basis = QComboBox()
        self.cmb_basis.setEditable(True)
        self.cmb_basis.addItems(G.COMMON_BASES)
        label("method", 0, 0)
        form.addWidget(self.cmb_method, 0, 1)
        label("basis", 0, 2)
        form.addWidget(self.cmb_basis, 0, 3)

        self.cmb_task = QComboBox()
        for key in G.JOB_TYPES:
            self.cmb_task.addItem("", key)
        self.cmb_disp = QComboBox()
        self.cmb_disp.addItem("", "")
        for disp in ("D3BJ", "D3ZERO", "GD3BJ"):
            self.cmb_disp.addItem(disp, disp)
        label("task", 1, 0)
        form.addWidget(self.cmb_task, 1, 1)
        label("dispersion", 1, 2)
        form.addWidget(self.cmb_disp, 1, 3)

        self.spin_charge = QSpinBox()
        self.spin_charge.setRange(-10, 10)
        self.spin_mult = QSpinBox()
        self.spin_mult.setRange(1, 10)
        label("charge", 2, 0)
        form.addWidget(self.spin_charge, 2, 1)
        label("mult", 2, 2)
        form.addWidget(self.spin_mult, 2, 3)

        self.spin_nproc = QSpinBox()
        self.spin_nproc.setRange(1, 128)
        self.spin_nproc.setValue(min(8, max(1, os.cpu_count() or 4)))
        self.spin_mem = QSpinBox()
        self.spin_mem.setRange(1, 512)
        self.spin_mem.setValue(8)
        label("nproc", 3, 0)
        form.addWidget(self.spin_nproc, 3, 1)
        label("mem", 3, 2)
        form.addWidget(self.spin_mem, 3, 3)

        self.cmb_solvent = QComboBox()
        self.cmb_solvent.addItem("", "")
        for name in G.COMMON_SOLVENTS:
            self.cmb_solvent.addItem(name, name)
        self.cmb_solvent_model = QComboBox()
        self.cmb_solvent_model.addItem("CPCM", "cpcm")
        self.cmb_solvent_model.addItem("SMD", "smd")
        label("solvent", 4, 0)
        form.addWidget(self.cmb_solvent, 4, 1)
        label("solvent_model", 4, 2)
        form.addWidget(self.cmb_solvent_model, 4, 3)

        self.edit_extra = QLineEdit()
        label("extra", 5, 0)
        form.addWidget(self.edit_extra, 5, 1, 1, 3)

        self.edit_workdir = QLineEdit(self._default_workdir())
        self.btn_workdir = QPushButton("")
        self.btn_workdir.clicked.connect(self._browse_workdir)
        label("workdir", 6, 0)
        form.addWidget(self.edit_workdir, 6, 1, 1, 2)
        form.addWidget(self.btn_workdir, 6, 3)

        self.edit_name = QLineEdit("gauss_job")
        label("job_name", 7, 0)
        form.addWidget(self.edit_name, 7, 1, 1, 3)

        self.edit_g16 = QLineEdit(self._g16_exe)
        self.btn_browse_g16 = QPushButton("")
        self.btn_browse_g16.clicked.connect(self._browse_g16)
        self.btn_detect_g16 = QPushButton("")
        self.btn_detect_g16.clicked.connect(self._detect_g16)
        g16_host = QWidget()
        g16_row = QHBoxLayout(g16_host)
        g16_row.setContentsMargins(0, 0, 0, 0)
        g16_row.setSpacing(5)
        g16_row.addWidget(self.btn_browse_g16)
        g16_row.addWidget(self.btn_detect_g16)
        label("g16", 8, 0)
        form.addWidget(self.edit_g16, 8, 1, 1, 2)
        form.addWidget(g16_host, 8, 3)

        # 联用模式
        self.chk_bridge = QCheckBox("")
        self.chk_bridge.toggled.connect(self._on_bridge_toggled)
        form.addWidget(self.chk_bridge, 9, 0, 1, 4)

        self.cmb_xmethod = QComboBox()
        for key, info in XTB_METHODS.items():
            self.cmb_xmethod.addItem(info.get(self.lang) or info.get("zh") or key,
                                     key)
        self.cmb_xmethod.setCurrentIndex(
            max(0, self.cmb_xmethod.findData("gfn2")))
        self.spn_xthreads = QSpinBox()
        self.spn_xthreads.setRange(1, 128)
        self.spn_xthreads.setValue(min(4, max(1, os.cpu_count() or 4)))
        label("xmethod", 10, 0)
        form.addWidget(self.cmb_xmethod, 10, 1)
        label("xthreads", 10, 2)
        form.addWidget(self.spn_xthreads, 10, 3)

        self.edit_xexe = QLineEdit(self._find_xtb())
        self.btn_browse_xexe = QPushButton("")
        self.btn_browse_xexe.clicked.connect(self._browse_xtb)
        self.btn_detect_xexe = QPushButton("")
        self.btn_detect_xexe.clicked.connect(self._detect_xtb)
        xexe_host = QWidget()
        xrow = QHBoxLayout(xexe_host)
        xrow.setContentsMargins(0, 0, 0, 0)
        xrow.setSpacing(5)
        xrow.addWidget(self.btn_browse_xexe)
        xrow.addWidget(self.btn_detect_xexe)
        label("xexe", 11, 0)
        form.addWidget(self.edit_xexe, 11, 1, 1, 2)
        form.addWidget(xexe_host, 11, 3)

        self.lbl_bridge_hint = QLabel("")
        self.lbl_bridge_hint.setWordWrap(True)
        self.lbl_bridge_hint.setStyleSheet("color:#b07200;")
        form.addWidget(self.lbl_bridge_hint, 12, 0, 1, 4)

        for col in (1, 3):
            form.setColumnStretch(col, 1)

        for widget in (self.cmb_method, self.cmb_basis, self.cmb_task,
                       self.cmb_disp, self.cmb_solvent,
                       self.cmb_solvent_model):
            widget.currentIndexChanged.connect(self._schedule_preview)
        for widget in (self.spin_charge, self.spin_mult, self.spin_nproc,
                       self.spin_mem):
            widget.valueChanged.connect(self._schedule_preview)
        for widget in (self.edit_extra, self.edit_name, self.edit_workdir,
                       self.edit_g16, self.edit_xexe):
            widget.textChanged.connect(self._schedule_preview)
        self.edit_name.textEdited.connect(self._on_name_edited)
        self.edit_workdir.textEdited.connect(self._on_workdir_edited)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(200)
        self._preview_timer.timeout.connect(self._refresh_preview)
        return self.grp_calc

    def _build_action_row(self):
        row = QHBoxLayout()
        row.setSpacing(6)
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
        self._row_widgets = (self.btn_gen, self.btn_save, self.btn_copy,
                             self.btn_stop, self.btn_run)
        return row

    def _build_tabs(self):
        self.tabs = QTabWidget()
        self.tabs.setMinimumHeight(320)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.preview.setStyleSheet(
            "QPlainTextEdit{font-family:Consolas,'Courier New',monospace;"
            "font-size:9pt;background:#FFFFFF;}")
        self.tabs.addTab(self.preview, "")

        self.tabs.addTab(self._build_log_page(), "")
        self.tabs.addTab(self._build_result_page(), "")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        return self.tabs

    def _build_log_page(self):
        page = QWidget()
        gv = QVBoxLayout(page)
        gv.setContentsMargins(0, 6, 0, 0)
        gv.setSpacing(4)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.log_view.setMaximumBlockCount(4000)
        self.log_view.setStyleSheet(
            "QPlainTextEdit{font-family:Consolas,'Courier New',monospace;"
            "font-size:8.5pt;background:#0E1726;color:#D7E2F0;"
            "border:1px solid #1E2A44;}")
        gv.addWidget(self.log_view, 1)
        row = QHBoxLayout()
        row.setSpacing(5)
        self.btn_log_clear = QPushButton("")
        self.btn_log_clear.clicked.connect(self._clear_log)
        self.btn_log_copy = QPushButton("")
        self.btn_log_copy.clicked.connect(self._copy_log)
        row.addWidget(self.btn_log_clear)
        row.addWidget(self.btn_log_copy)
        row.addStretch(1)
        gv.addLayout(row)
        return page

    def _build_result_page(self):
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
        lay.setContentsMargins(6, 6, 6, 4)
        lay.setHorizontalSpacing(12)
        lay.setVerticalSpacing(6)
        self._res_labels = {}
        self._res_keys = [
            ("energy", "energy"), ("homo", "homo"), ("lumo", "lumo"),
            ("gap", "gap"), ("freq", "freq"), ("imag", "imag"),
            ("opt", "opt"), ("normal", "normal"), ("steps", "steps"),
            ("runtime", "runtime"), ("log_file", "log_file"),
            ("chk_file", "chk_file"), ("fchk_file", "fchk_file"),
        ]
        for index, (key, text_key) in enumerate(self._res_keys):
            lab = QLabel("")
            self._labels["res_" + key] = lab
            value = QLabel(self._t("none"))
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            value.setStyleSheet("color:#16233F;")
            lay.addWidget(lab, index, 0)
            lay.addWidget(value, index, 1)
            self._res_labels[key] = value
        self.lbl_result_hint = QLabel("")
        self.lbl_result_hint.setWordWrap(True)
        self.lbl_result_hint.setStyleSheet("color:#8A97AB;font-size:8.5pt;")
        lay.addWidget(self.lbl_result_hint, len(self._res_keys), 0, 1, 2)
        lay.setColumnStretch(1, 1)
        lay.setRowStretch(len(self._res_keys) + 1, 1)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        row = QHBoxLayout()
        self.btn_convert = QPushButton("")
        self.btn_convert.setEnabled(False)
        self.btn_convert.clicked.connect(self._convert_fchk)
        self.btn_load_fchk = QPushButton("")
        self.btn_load_fchk.setEnabled(False)
        self.btn_load_fchk.clicked.connect(self._load_fchk)
        self.btn_open_log = QPushButton("")
        self.btn_open_log.setEnabled(False)
        self.btn_open_log.clicked.connect(self._open_output)
        self.btn_open_dir = QPushButton("")
        self.btn_open_dir.clicked.connect(self._open_workdir)
        for btn in (self.btn_convert, self.btn_load_fchk, self.btn_open_log,
                    self.btn_open_dir):
            row.addWidget(btn)
        row.addStretch(1)
        outer.addLayout(row)
        return page

    # ── 语言 ────────────────────────────────────────────────────────
    def set_lang(self, lang):
        self.lang = "en" if str(lang).lower().startswith("en") else "zh"
        self.grp_struct.setTitle(self._t("grp_struct"))
        self.grp_calc.setTitle(self._t("grp_calc"))
        self.btn_read.setText(self._t("read_canvas"))
        self.btn_load.setText(self._t("load_gjf"))
        self.btn_nbo_input.setText(self._t("nbo_input"))
        self.btn_workdir.setText(self._t("browse"))
        self.btn_browse_g16.setText(self._t("browse"))
        self.btn_detect_g16.setText(self._t("detect"))
        self.btn_browse_xexe.setText(self._t("browse"))
        self.btn_detect_xexe.setText(self._t("detect"))
        self.btn_gen.setText(self._t("gen"))
        self.btn_save.setText(self._t("save_inp"))
        self.btn_copy.setText(self._t("copy"))
        self.btn_run.setText(self._t("run"))
        self.btn_stop.setText(self._t("stop"))
        self.btn_convert.setText(self._t("convert"))
        self.btn_load_fchk.setText(self._t("load_fchk"))
        self.btn_open_log.setText(self._t("open_log"))
        self.btn_open_dir.setText(self._t("open_dir"))
        self.btn_log_clear.setText(self._t("log_clear"))
        self.btn_log_copy.setText(self._t("log_copy"))
        self.tabs.setTabText(0, self._t("tab_input"))
        self.tabs.setTabText(1, self._t("tab_log"))
        self.tabs.setTabText(2, self._t("tab_result"))
        self.preview.setPlaceholderText(self._t("preview_empty"))
        self.log_view.setPlaceholderText(self._t("log_ph"))
        self.lbl_result_hint.setText(self._t("result_hint"))
        self.edit_extra.setPlaceholderText(self._t("extra_ph"))
        self.edit_workdir.setToolTip(self._t("tip_workdir"))
        self.btn_open_dir.setToolTip(self._t("tip_open_dir"))
        self.chk_bridge.setText(self._t("bridge"))
        self.chk_bridge.setToolTip(self._t("tip_bridge"))
        self.lbl_bridge_hint.setText(self._t("bridge_hint"))
        for key, lab in self._labels.items():
            if key.startswith("res_"):
                lab.setText(self._t(key[4:]))
            else:
                lab.setText(self._t(key))
        for index in range(self.cmb_task.count()):
            key = str(self.cmb_task.itemData(index))
            self.cmb_task.setItemText(
                index, G.JOB_TYPES.get(key, {}).get(self.lang, key))
        self.cmb_disp.setItemText(0, self._t("disp_none"))
        self.cmb_solvent.setItemText(0, self._t("solvent_none"))
        for index in range(self.cmb_xmethod.count()):
            key = str(self.cmb_xmethod.itemData(index))
            info = XTB_METHODS.get(key, {})
            self.cmb_xmethod.setItemText(
                index, info.get(self.lang) or info.get("zh") or key)
        self._apply_sources()
        self._render_status()
        if self._result is not None:
            self._fill_results(self._result)
        else:
            self.lbl_result_hint.setText(self._t("result_hint"))
        if not self._symbols:
            self.preview.setPlainText(self._t("preview_empty"))
        self._sync_bridge_ui()

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
            symbols, coords = read_structure_file(path)
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
        if current in ("", "gauss_job") or current == self._auto_name:
            self._auto_name = stem + "_gauss"
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

    def _open_nbo_input(self):
        """Open the editable NBO generator, optionally seeded by the live file."""
        from molstudio.panels.nbo_input_dialog import NboInputDialog

        source = self._source_path if self._source_kind == "file" else ""
        fchk = source if os.path.splitext(source)[1].lower() in (".fchk", ".fch") else ""
        dlg = NboInputDialog(
            initial_source=source, initial_fchk=fchk,
            lang=self.lang, parent=self)
        dlg.exec_()
        self._adopt_nbo_pop(dlg)

    def _adopt_nbo_pop(self, dlg):
        """把生成器里选定的 ``pop=`` 关键词接到本页的「附加关键字」。

        否则用户在这里点「开始计算」时，route 会被重建成不含 pop 的版本，
        saveNBO 任务白跑。plot 模式还需要 ``$NBO`` 数据块，本页不写数据块，
        所以只提示改用命令行。
        """
        editor = getattr(dlg, "editor", None)
        if editor is None:
            return
        keyword = route_pop_keyword(editor.toPlainText())
        if not keyword:
            return
        if keyword.lower() == "pop=nboread":
            self._set_status("nbo_plot_needs_cmd")
            return
        current = self.edit_extra.text().strip()
        if "pop=" in current.lower():
            return
        self.edit_extra.setText((current + " " + keyword).strip())
        self._refresh_preview()
        # 放在 _refresh_preview 之后：它会把状态改成「输入已生成」，
        # 而这条提示才是用户需要看到的交接结果。
        self._set_status("nbo_pop_filled", kw=keyword)

    def load_structure_path(self, path):
        """载入 gjf/xyz/fchk/log/out，并通知主窗口把结构画到画布上。"""
        if self._on_open_structure is not None:
            try:
                self._on_open_structure(path)
            except Exception as exc:                     # noqa: BLE001
                self._set_status("status_save_fail", err=exc)
                return False
        try:
            symbols, coords = read_structure_file(path)
        except Exception as exc:                         # noqa: BLE001
            self._set_status("status_save_fail", err=exc)
            return False
        self._symbols = [str(s) for s in symbols]
        self._coords = [[float(v) for v in row] for row in coords]
        self._source_kind = "file"
        self._source_path = path
        stem = os.path.splitext(os.path.basename(path))[0]
        current = self.edit_name.text().strip()
        if current in ("", "gauss_job") or current == self._auto_name:
            self._auto_name = stem + "_gauss"
            self.edit_name.setText(self._auto_name)
        self._meta_path = path
        self._apply_gjf_meta(path)
        pop_kw = self._capture_route_pop(path)
        self._on_structure_switched()
        self._apply_sources()
        self._set_status("status_loaded", n=len(symbols))
        self._refresh_preview()
        if pop_kw:
            # 放在 _refresh_preview 之后：它会用「输入已生成」覆盖状态，
            # 而这条提示正是用户最需要看到的。
            self._set_status("status_loaded_pop", n=len(symbols), kw=pop_kw)
        return True

    def _capture_route_pop(self, path):
        """载入 gjf 时把 ``pop=...`` 接住，填进「附加关键字」。

        返回被接住的关键词；没有（或用户自己已经填过）时返回 ``""``。
        """
        ext = os.path.splitext(str(path))[1].lower()
        if ext not in (".gjf", ".com"):
            return ""
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                keyword = route_pop_keyword(fh.read())
        except OSError:
            return ""
        if not keyword:
            return ""
        current = self.edit_extra.text().strip()
        if "pop=" in current.lower():
            return ""
        self.edit_extra.setText((current + " " + keyword).strip())
        return keyword

    # ── 输入 ────────────────────────────────────────────────────────
    def _schedule_preview(self, *_args):
        try:
            self._preview_timer.start()
        except Exception:                                # noqa: BLE001
            self._refresh_preview()

    def _on_name_edited(self, *_args):
        self._auto_name = ""

    def _on_workdir_edited(self, *_args):
        self._workdir_user_edited = True
        self._workdir_auto = False

    def _on_tab_changed(self, index):
        index = int(index)
        if index == 0:
            self._refresh_preview()
        elif index == 1:
            self._fix_log_view()

    def _fix_log_view(self):
        view = getattr(self, "log_view", None)
        if view is None:
            return
        bar = view.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 2
        height = view.height()
        if height > 2:
            view.resize(view.width(), height + 1)
            view.resize(view.width(), height - 1)
        if at_end:
            bar.setValue(bar.maximum())

    def _bridge_enabled(self):
        return bool(self.chk_bridge.isChecked())

    def _max_z(self):
        return max([_SYMBOL_TO_Z.get(str(s).capitalize(), 0)
                    for s in self._symbols] or [0])

    def _xtb_method_args(self):
        key = str(self.cmb_xmethod.currentData() or "gfn2")
        info = XTB_METHODS.get(key, {})
        return " ".join(info.get("args") or ["--gfn", "2"])

    def _bridge_env(self):
        return BRIDGE.build_bridge_env(
            {}, self.edit_xexe.text().strip(),
            method_args=self._xtb_method_args(),
            threads=self.spn_xthreads.value())

    def _route_for(self, workdir):
        """返回 ``(路由行, 提示列表)``；联用时挂上 external 的 bat。"""
        task = str(self.cmb_task.currentData() or "sp")
        if self._bridge_enabled():
            base = G.build_route(include_method=False, task=task,
                                 extra_keywords=self.edit_extra.text().strip())
            route, notes = BRIDGE.prepare_bridge_route(base, self._max_z())
            bat = os.path.join(workdir, BRIDGE.CLIENT_BAT_NAME)
            return BRIDGE.external_route(route, bat), notes
        route = G.build_route(
            method=self.cmb_method.currentText().strip(),
            basis=self.cmb_basis.currentText().strip(),
            task=task,
            dispersion=str(self.cmb_disp.currentData() or ""),
            solvent=str(self.cmb_solvent.currentData() or ""),
            solvent_model=str(self.cmb_solvent_model.currentData() or "cpcm"),
            extra_keywords=self.edit_extra.text().strip())
        return route, []

    def _build_input_text(self, workdir):
        route, notes = self._route_for(workdir)
        name = self.edit_name.text().strip() or "gauss_job"
        text = G.build_gjf(
            self._symbols, self._coords,
            charge=self.spin_charge.value(), mult=self.spin_mult.value(),
            route=route, title=name, nproc=self.spin_nproc.value(),
            mem_gb=self.spin_mem.value(), chk_name=name + ".chk")
        return text, route, notes

    def _refresh_preview(self, *_args):
        if not self._symbols:
            self.preview.setPlainText(self._t("preview_empty"))
            self._set_status("status_no_structure")
            return
        if not self._bridge_enabled() and not self.cmb_method.currentText().strip():
            self.preview.setPlainText(self._t("status_need_method"))
            return
        workdir = (self.edit_workdir.text().strip()
                   or self._default_workdir())
        try:
            text, route, notes = self._build_input_text(workdir)
        except Exception as exc:                         # noqa: BLE001
            self.preview.setPlainText("[input error] %s" % exc)
            return
        self.preview.setPlainText(text)
        if self._bridge_enabled():
            self.lbl_bridge_hint.setText(
                self._t("bridge_hint") + ("\n" + "\n".join(notes) if notes else ""))
        self._set_status("status_preview")

    def _prepare_input(self, workdir):
        """把 .gjf（联用时还有 bat）写到 ``workdir``，返回运行配置。"""
        os.makedirs(workdir, exist_ok=True)
        extra_env = {}
        if self._bridge_enabled():
            xtb = self.edit_xexe.text().strip()
            if not xtb or not os.path.isfile(xtb):
                raise RuntimeError(self._t("status_no_xtb"))
            BRIDGE.write_client_bat(workdir)
            extra_env = self._bridge_env()
        text, route, notes = self._build_input_text(workdir)
        name = self.edit_name.text().strip() or "gauss_job"
        gjf_path = os.path.join(workdir, name + ".gjf")
        with open(gjf_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        self._prepared = {
            "gjf_path": gjf_path, "text": text, "route": route,
            "notes": notes, "workdir": workdir,
            "log_path": os.path.join(workdir, name + ".log"),
            "chk_path": os.path.join(workdir, name + ".chk"),
        }
        return self._prepared

    def _prepared_or_default(self):
        if self._prepared is not None:
            return self._prepared
        text, route, notes = self._build_input_text(
            self.edit_workdir.text().strip() or self._default_workdir())
        return {"gjf_path": "", "text": text, "route": route, "notes": notes}

    def _save_input(self):
        if not self._symbols:
            self._set_status("status_need_structure")
            return None
        workdir = self.edit_workdir.text().strip() or self._default_workdir()
        try:
            prepared = self._prepare_input(workdir)
        except Exception as exc:                         # noqa: BLE001
            self._set_status("status_save_fail", err=exc)
            return None
        self._log("[MolStudio] %s" % prepared["gjf_path"])
        for note in prepared["notes"]:
            self._log("[MolStudio] %s" % note)
        self._set_status("status_preview")
        return prepared

    def _log(self, line):
        self.log_view.appendPlainText(str(line))
        bar = self.log_view.verticalScrollBar()
        bar.setValue(bar.maximum())
        if self._log_func:
            try:
                self._log_func(line)
            except Exception:                            # noqa: BLE001
                pass

    def _clear_log(self):
        self.log_view.clear()

    def _copy_log(self):
        QApplication.clipboard().setText(self.log_view.toPlainText())
        self._set_status("status_copied")

    def _copy_command(self):
        g16 = self.edit_g16.text().strip() or "g16.exe"
        name = self.edit_name.text().strip() or "gauss_job"
        cmd = 'cmd /c "%s" "%s.gjf"' % (g16, name)
        if self._bridge_enabled():
            cmd += "    # external='%s'" % BRIDGE.CLIENT_BAT_NAME
        QApplication.clipboard().setText(cmd)
        self._set_status("status_copied")

    # ── 运行 ────────────────────────────────────────────────────────
    def run(self):
        if not self._symbols:
            self._set_status("status_need_structure")
            return
        if not self._bridge_enabled() and not self.cmb_method.currentText().strip():
            self._set_status("status_need_method")
            return
        g16 = self.edit_g16.text().strip()
        if not g16 or not os.path.isfile(g16):
            self._set_status("status_no_g16")
            return
        if self._bridge_enabled():
            xtb = self.edit_xexe.text().strip()
            if not xtb or not os.path.isfile(xtb):
                self._set_status("status_no_xtb")
                return
        run_dir = self._resolve_run_dir()
        self.edit_workdir.setText(run_dir)
        self.edit_workdir.setCursorPosition(len(run_dir))
        self._workdir_base = os.path.dirname(run_dir)
        self._workdir_user_edited = False
        self._last_run_dir = run_dir
        os.makedirs(run_dir, exist_ok=True)
        try:
            prepared = self._prepare_input(run_dir)
        except Exception as exc:                         # noqa: BLE001
            self._set_status("status_save_fail", err=exc)
            return
        self._save_settings()
        self.log_view.clear()
        self.tabs.setCurrentIndex(1)
        self.progress.setRange(0, 0)
        self._set_status("status_running")
        self._set_running(True)
        self._active_task = str(self.cmb_task.currentData() or "sp")
        self._run_bridge = self._bridge_enabled()
        self._log("[MolStudio] %s" % prepared["gjf_path"])
        self._log("[MolStudio] %s" % prepared["route"])
        for note in prepared["notes"]:
            self._log("[MolStudio] %s" % note)
        if self._bridge_enabled():
            self._log("[MolStudio] " + self._t(
                "bridge_cmd",
                cmd=" ".join(BRIDGE.xtb_bridge_argv(
                    self.edit_xexe.text().strip(),
                    self.spin_charge.value(), self.spin_mult.value() - 1,
                    self._xtb_method_args(), self.spn_xthreads.value(),
                    derivs=2 if self._active_task in ("freq", "opt_freq",
                                                     "ts_freq") else 1))))

        cfg = {
            "gjf_path": prepared["gjf_path"],
            "log_path": prepared["log_path"],
            "g16_exe": g16,
            "formchk_exe": self._formchk_exe
            or G.find_formchk(self.edit_g16.text().strip()),
            "extra_env": self._bridge_env() if self._bridge_enabled() else {},
            "timeout": 0,
        }
        self._worker = GaussianWorker(cfg, self)
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
        for widget in (self.btn_gen, self.btn_save, self.btn_copy,
                       self.cmb_method, self.cmb_basis, self.cmb_task,
                       self.cmb_disp, self.spin_charge, self.spin_mult,
                       self.spin_nproc, self.spin_mem, self.cmb_solvent,
                       self.cmb_solvent_model, self.edit_extra,
                       self.edit_workdir, self.btn_workdir, self.edit_name,
                       self.edit_g16, self.btn_browse_g16, self.btn_detect_g16,
                       self.chk_bridge, self.cmb_xmethod, self.spn_xthreads,
                       self.edit_xexe, self.btn_browse_xexe,
                       self.btn_detect_xexe, self.btn_read, self.btn_load):
            widget.setEnabled(not running)
        self.btn_run.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        if running:
            self.progress.setRange(0, 0)
            self.progress.setValue(0)
        else:
            self.progress.setRange(0, 100)
        self.btn_convert.setEnabled(False if running else bool(
            self._result and self._result.chk_path))
        self.btn_load_fchk.setEnabled(False if running else bool(
            self._result and self._result.fchk_path))
        self.btn_open_log.setEnabled(False if running else bool(self._result))
        if not running:
            self._sync_bridge_ui()

    def _on_done(self, result):
        self._worker = None
        self._result = result
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.tabs.setCurrentIndex(2)
        self._set_running(False)
        self._fill_results(result)
        if result.normal:
            self._set_status("status_done")
            if getattr(self, "_run_bridge", False) and not result.bridge:
                self._log("[MolStudio] " + self._t("warn_bridge_not_run"))
        else:
            self._set_status("status_failed", err=result.error or "")
        self.btn_convert.setEnabled(bool(result.chk_path))
        self.btn_load_fchk.setEnabled(bool(result.fchk_path))
        self.btn_open_log.setEnabled(True)

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

    # ── 结果 ────────────────────────────────────────────────────────
    def _fill_results(self, result):
        p = result.parsed or {}
        val = self._res_labels
        none = self._t("none")

        def fmt(value, spec="%.6f"):
            return none if value is None else spec % value

        val["energy"].setText(fmt(p.get("final_energy")))
        hartree_to_ev = 27.211386245988
        if p.get("homo") is not None:
            val["homo"].setText("%.4f eV  (%.6f Eh)" % (
                p["homo"] * hartree_to_ev, p["homo"]))
        if p.get("lumo") is not None:
            val["lumo"].setText("%.4f eV  (%.6f Eh)" % (
                p["lumo"] * hartree_to_ev, p["lumo"]))
        if p.get("homo_lumo_gap_ev") is not None:
            val["gap"].setText("%.4f eV" % p["homo_lumo_gap_ev"])
        freqs = p.get("frequencies") or []
        if freqs:
            val["freq"].setText(str(len(freqs)))
        imag = p.get("imaginary") or []
        if imag:
            val["imag"].setText(", ".join("%.2f" % f for f in imag))
        elif freqs:
            val["imag"].setText(none)
        if self._active_task in ("opt", "opt_freq", "ts", "ts_freq", "irc"):
            val["opt"].setText(self._t("yes") if p.get("opt_converged")
                               else self._t("no"))
        else:
            val["opt"].setText(none)
        val["normal"].setText(self._t("yes") if p.get("terminated_normally")
                              else self._t("no"))
        steps = p.get("steps") or 0
        if p.get("bridge") and steps:
            val["steps"].setText(self._t("steps_bridge", n=steps))
        else:
            val["steps"].setText(str(steps) if steps else none)
        val["runtime"].setText("%.1f s" % result.elapsed)
        val["log_file"].setText(result.log_path or none)
        val["chk_file"].setText(result.chk_path or none)
        val["fchk_file"].setText(result.fchk_path or none)
        self.lbl_result_hint.setText(
            "可直接把 .fchk 载入主窗口，现有轨道 / ESP / IGMH / AIM / DOS "
            "页面都能读。" if self.lang == "zh" else
            "Load the .fchk into the main window; orbital / ESP / IGMH / AIM / "
            "DOS pages can read it directly.")

    def _convert_fchk(self):
        if not (self._result and self._result.chk_path):
            return
        self._set_status("status_converting")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            fchk = G.chk_to_fchk(self._result.chk_path, self._formchk_exe)
            self._result.fchk_path = fchk
            self._fill_results(self._result)
            self.btn_convert.setEnabled(True)
            self.btn_load_fchk.setEnabled(True)
            self._set_status("status_converted", path=fchk)
        except Exception as exc:                         # noqa: BLE001
            self._set_status("status_failed", err=exc)
        finally:
            QApplication.restoreOverrideCursor()

    def _load_fchk(self):
        fchk = self._result.fchk_path if self._result else ""
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
            path = self._result.log_path
        elif self._prepared is not None:
            path = self._prepared.get("log_path", "")
        if path and os.path.isfile(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _open_workdir(self):
        for cand in (self._last_run_dir,
                     (self._result.workdir if self._result is not None else ""),
                     (self._prepared or {}).get("workdir", ""),
                     self.edit_workdir.text().strip()
                     or self._default_workdir()):
            if cand and os.path.isdir(cand):
                QDesktopServices.openUrl(QUrl.fromLocalFile(cand))
                return

    # ── 联用 / 可执行文件 ───────────────────────────────────────────
    def _on_bridge_toggled(self, *_args):
        self._sync_bridge_ui()
        self._save_settings()

    def _sync_bridge_ui(self):
        on = self._bridge_enabled()
        for widget in (self._labels.get("xmethod"), self.cmb_xmethod,
                       self._labels.get("xthreads"), self.spn_xthreads,
                       self._labels.get("xexe"), self.edit_xexe,
                       self.btn_browse_xexe, self.btn_detect_xexe,
                       self.lbl_bridge_hint):
            if widget is not None:
                widget.setVisible(on)
        # 联用时方法/基组/色散/溶剂都不生效（路由里不能出现方法关键字）
        for widget in (self.cmb_method, self.cmb_basis, self.cmb_disp,
                       self.cmb_solvent, self.cmb_solvent_model):
            widget.setEnabled(not on and not self._is_busy())
        self._refresh_preview()

    def _is_busy(self):
        return self._worker is not None and self._worker.isRunning()

    def _find_xtb(self):
        try:
            from molstudio.core.xtb import find_xtb_executable
            return find_xtb_executable() or ""
        except Exception:                                # noqa: BLE001
            return ""

    def _browse_g16(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self._t("browse_exe"),
            os.path.dirname(self.edit_g16.text().strip() or ""),
            "可执行文件 (*.exe);;所有文件 (*.*)")
        if path:
            self.edit_g16.setText(path)
            self._formchk_exe = G.find_formchk(path)

    def _detect_g16(self):
        found = G.find_gaussian()
        if found:
            self.edit_g16.setText(found)
            self._formchk_exe = G.find_formchk(found)

    def _browse_xtb(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self._t("browse_exe"),
            os.path.dirname(self.edit_xexe.text().strip() or ""),
            "可执行文件 (*.exe);;所有文件 (*.*)")
        if path:
            self.edit_xexe.setText(path)

    def _detect_xtb(self):
        found = self._find_xtb()
        if found:
            self.edit_xexe.setText(found)

    def _browse_workdir(self):
        path = QFileDialog.getExistingDirectory(
            self, self._t("browse_dir"),
            self.edit_workdir.text().strip() or os.path.expanduser("~"))
        if path:
            self.edit_workdir.setText(path)
            self._workdir_base = ""
            self._workdir_user_edited = True
            self._workdir_auto = False

    # ── 设置持久化 ──────────────────────────────────────────────────
    def _restore_settings(self):
        s = self._settings
        try:
            method = s.value("method", "B3LYP", type=str)
            basis = s.value("basis", "6-31G(d)", type=str)
            if method:
                self.cmb_method.setCurrentText(method)
            if basis:
                self.cmb_basis.setCurrentText(basis)
            self.spin_nproc.setValue(s.value(
                "nproc", min(8, max(1, os.cpu_count() or 4)), type=int))
            self.spin_mem.setValue(s.value("mem", 8, type=int))
            self.chk_bridge.setChecked(s.value("bridge", False, type=bool))
            self.spn_xthreads.setValue(s.value(
                "xthreads", min(4, max(1, os.cpu_count() or 4)), type=int))
            xmethod = s.value("xmethod", "gfn2", type=str)
            idx = self.cmb_xmethod.findData(xmethod)
            if idx >= 0:
                self.cmb_xmethod.setCurrentIndex(idx)
            g16 = s.value("g16", "", type=str)
            if g16 and os.path.isfile(g16):
                self.edit_g16.setText(g16)
                self._formchk_exe = G.find_formchk(g16)
            xtb = s.value("xtb", "", type=str)
            if xtb and os.path.isfile(xtb):
                self.edit_xexe.setText(xtb)
            wd = s.value("workdir", "", type=str)
            auto = bool(s.value("workdir_auto", True, type=bool))
            if wd and not auto and not any(
                    "\u4e00" <= ch <= "\u9fff" for ch in wd):
                self.edit_workdir.setText(wd)
                self._workdir_base = wd
            self._workdir_auto = auto
            self.edit_workdir.setCursorPosition(0)
        except Exception:                                # noqa: BLE001
            pass

    def _save_settings(self):
        try:
            s = self._settings
            s.setValue("method", self.cmb_method.currentText().strip())
            s.setValue("basis", self.cmb_basis.currentText().strip())
            s.setValue("nproc", self.spin_nproc.value())
            s.setValue("mem", self.spin_mem.value())
            s.setValue("bridge", self._bridge_enabled())
            s.setValue("xthreads", self.spn_xthreads.value())
            s.setValue("xmethod",
                       str(self.cmb_xmethod.currentData() or "gfn2"))
            s.setValue("g16", self.edit_g16.text().strip())
            s.setValue("xtb", self.edit_xexe.text().strip())
            s.setValue("workdir", self._workdir_base
                       or self.edit_workdir.text().strip())
            s.setValue("workdir_auto", bool(self._workdir_auto))
            s.sync()
        except Exception:                                # noqa: BLE001
            pass

    def shutdown(self):
        worker = self._worker
        if worker is not None and worker.isRunning():
            try:
                worker.cancel()
                worker.wait(5000)
            except Exception:                            # noqa: BLE001
                pass
        self._worker = None
        self._save_settings()
