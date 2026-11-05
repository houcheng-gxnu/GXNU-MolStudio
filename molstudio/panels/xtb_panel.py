# -*- coding: utf-8 -*-
"""xTB 计算功能页（外部 xTB 半经验程序：SP / OPT / OHEss / Hess / TS / Scan）。

面板只负责「取结构 → 传参数 → 后台跑 xTB → 展示/导出结果」，计算全部由
:mod:`molstudio.core.xtb` 完成（纯计算内核，无 PyQt 依赖）。结构默认取自
**左侧画布当前分子**，也可以直接打开 xyz / gjf / com / log / out 文件；优化后的
结构可以一键送回画布。

布局（右栏约 680 px，自上而下）：

* 结构来源：刷新画布结构 / 打开文件…，以及「画布：N 个原子」状态；
* 计算设置：xTB 可执行文件、方法 / 任务、电荷 / 自旋、精度、溶剂化、并行、
  输出开关、工作目录；job=scan 时展开 xcontrol 编辑框，job=ts 时给出提示；
* 运行 / 停止 / 预览命令；
* 结果区：总能量、gap / HOMO / LUMO / 偶极 / 梯度、频率与热化学、
  原子电荷表、送回画布与 XYZ / GJF / JSON 导出；
* 扫描结果：扫描步 - 相对能量小图 + 轨迹导出。

运行期同时写入 ``<workdir>/xtb.out``（引擎负责），日志逐行转发给主窗口。
本模块不 import OpenGL / ovcanvas，可在 ``QT_QPA_PLATFORM=offscreen`` 下构建、
运行与截图。

xTB 参数/产物格式参考 xTBridge（MIT，同作者）与 gxtb_gui.py 的独立 xTB 页，
运行期不依赖 ``D:\\xbt-windows``。
"""

from __future__ import annotations

import configparser
import json
import os
import tempfile
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg   # noqa: E402
from matplotlib.figure import Figure                               # noqa: E402

from PyQt5.QtCore import QSize, Qt, QThread, QTimer, QUrl, pyqtSignal  # noqa: E402
from PyQt5.QtGui import QDesktopServices, QFont                    # noqa: E402
from PyQt5.QtWidgets import (                                     # noqa: E402
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy,
    QSpinBox, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

# ── 计算内核（另一份文件；导入失败时面板仍可构建，只是不能真正运行）──────
try:                                                        # pragma: no cover
    from molstudio.core import xtb
except Exception:                                           # noqa: BLE001
    xtb = None

SETTINGS_NAME = "xtb_panel_settings.ini"
HARTREE_TO_EV = 27.211386245988


# 引擎尚未落地时的最小兜底表（仅用于构建界面；引擎可用时永远用引擎的表）。
_FALLBACK_METHODS = {
    "gxtb": {"zh": "g-xTB", "en": "g-xTB", "args": ["--gxtb"]},
    "gfn2": {"zh": "GFN2-xTB", "en": "GFN2-xTB", "args": ["--gfn", "2"]},
    "gfn1": {"zh": "GFN1-xTB", "en": "GFN1-xTB", "args": ["--gfn", "1"]},
    "gfn0": {"zh": "GFN0-xTB", "en": "GFN0-xTB", "args": ["--gfn", "0"]},
    "gfnff": {"zh": "GFN-FF", "en": "GFN-FF", "args": ["--gfnff"]},
}
_FALLBACK_JOBS = {
    "sp": {"zh": "单点能", "en": "Single point"},
    "opt": {"zh": "几何优化", "en": "Geometry optimization"},
    "ohess": {"zh": "优化 + 频率", "en": "Opt + Hessian"},
    "hess": {"zh": "频率（数值 Hessian）", "en": "Frequency (Hessian)"},
    "ts": {"zh": "过渡态优化", "en": "Transition state"},
    "scan": {"zh": "柔性扫描", "en": "Relaxed scan"},
}
_FALLBACK_SOLVATION = {
    "gas": {"zh": "真空", "en": "Gas phase"},
    "alpb": {"zh": "ALPB", "en": "ALPB"},
    "gbsa": {"zh": "GBSA", "en": "GBSA"},
    "cosmo": {"zh": "COSMO", "en": "COSMO"},
}
_FALLBACK_SOLVENTS = {
    "alpb": ("water", "thf", "toluene", "dichloromethane"),
    "gbsa": ("water", "thf", "toluene", "dichloromethane"),
    "cosmo": ("water", "thf", "toluene", "dichloromethane"),
}


def _engine_module():
    """返回计算内核模块；引擎尚未落地时抛 ImportError。"""
    global xtb
    if xtb is None:
        from molstudio.core import xtb as _mod      # noqa: PLC0415
        xtb = _mod
    return xtb


def _engine_attr(name, fallback):
    try:
        return getattr(_engine_module(), name)
    except Exception:                                       # noqa: BLE001
        return fallback


def _method_table():
    return _engine_attr("METHODS", _FALLBACK_METHODS)


def _job_table():
    return _engine_attr("JOB_TYPES", _FALLBACK_JOBS)


def _solvation_table():
    return _engine_attr("SOLVATION_MODELS", _FALLBACK_SOLVATION)


def _solvents_for(model):
    attr = {"alpb": "ALPB_SOLVENTS", "gbsa": "GBSA_SOLVENTS",
            "cosmo": "COSMO_SOLVENTS"}.get(str(model or "gas"))
    if not attr:
        return ()
    names = _engine_attr(attr, None)
    if names is None:
        return _FALLBACK_SOLVENTS.get(str(model), ())
    try:
        return tuple(str(n) for n in names)
    except TypeError:
        return _FALLBACK_SOLVENTS.get(str(model), ())


def settings_file() -> str:
    """设置文件路径：源码运行放仓库根目录，打包后放 exe 同目录。"""
    from molstudio.paths import config_file              # noqa: PLC0415
    return config_file(SETTINGS_NAME)


# ══════════════════════════════════════════════════════════════════════
#  双语文字表（所有控件文案都必须走这里）
# ══════════════════════════════════════════════════════════════════════
_TR = {
    "zh": {
        # 分组
        "grp_source": "结构来源",
        "grp_calc": "计算设置",
        "grp_result": "计算结果",
        "grp_scan": "扫描结果",
        # 结构来源
        "btn_refresh": "刷新画布结构",
        "btn_open": "打开文件…",
        "src_canvas": "画布：{n} 个原子",
        "src_canvas_empty": "画布无结构",
        "src_file": "文件：{name}（{n} 个原子）",
        # 计算设置
        "lbl_exe": "xTB 可执行文件",
        "ph_exe": "留空自动检测",
        "btn_browse_exe": "浏览…",
        "btn_detect": "自动检测",
        "lbl_method": "方法",
        "lbl_job": "任务",
        "lbl_charge": "电荷",
        "lbl_uhf": "未成对电子",
        "lbl_acc": "SCF 精度",
        "lbl_etemp": "电子温度",
        "lbl_solvation": "溶剂化",
        "lbl_solvent": "溶剂",
        "lbl_parallel": "并行核数",
        "chk_json": "写 JSON",
        "chk_molden": "Molden",
        "chk_verbose": "详细输出",
        "lbl_extra": "额外参数",
        "ph_extra": "附加命令行参数（可选）",
        "lbl_workdir": "工作目录",
        "ph_workdir": "留空自动用默认基目录（每次运行新建时间戳子目录）",
        "btn_browse_dir": "浏览…",
        "btn_open_dir": "打开目录",
        "lbl_xcontrol": "xcontrol 内容",
        "ph_xcontrol": ("$constrain\n force constant=0.50\n"
                        " dihedral: 8,5,1,4,60.0\n$scan\n 1: 60.0, 120.0, 6\n$end"),
        "hint_xcontrol": "扫描任务会以 --opt --input 运行，内容必须包含 $constrain 与 $scan。",
        "hint_ts": "将写入 $opt ts=1，用于过渡态优化。",
        "hint_gxtb_solv": "g-xTB 不支持溶剂化，运行时将按真空处理。",
        # 按钮
        "btn_run": "运行 xTB",
        "btn_cancel": "停止",
        "btn_preview": "预览命令",
        "btn_to_canvas": "送回画布",
        "btn_export_xyz": "导出 XYZ…",
        "btn_export_gjf": "导出 GJF…",
        "btn_export_json": "导出 JSON…",
        "btn_open_workdir": "打开工作目录",
        "btn_export_scan": "导出扫描轨迹 XYZ…",
        # 结果文字
        "energy_none": "E = —",
        "energy_fmt": "E = {e} Eh",
        "gap_fmt": "HOMO-LUMO gap: {v} eV",
        "homo_fmt": "HOMO: {v} eV",
        "lumo_fmt": "LUMO: {v} eV",
        "dipole_fmt": "偶极: {v} Debye",
        "grad_fmt": "梯度范数: {v} Eh/Å",
        "na": "—",
        "vib_imag_fmt": "虚频数: {n}",
        "vib_lowest_fmt": "最低振动波数: {vals} cm⁻¹",
        "thermo_fmt": "G = {g} Eh    H = {h} Eh    ZPE = {z} Eh",
        "lbl_charges": "原子电荷",
        "col_index": "#",
        "col_element": "元素",
        "col_charge": "电荷",
        "scan_summary": "{n} 帧，ΔE = {de} eV",
        "scan_x": "扫描步",
        "scan_y": "相对能量 (eV)",
        # 状态行
        "st_ready": "就绪",
        "st_engine_missing": "未找到 xTB 可执行文件，请点「自动检测」或浏览选择。",
        "st_no_struct": "当前没有结构：请刷新画布或打开文件。",
        "st_invalid": "参数不合法：{err}",
        "st_phase": "{phase}… 已运行 {t:.1f} s",
        "phase_preparing": "准备中",
        "phase_running": "运行中",
        "phase_parsing": "解析结果",
        "st_cancelling": "正在停止…",
        "st_cancelled": "已取消（用时 {t:.1f} s）",
        "st_done": "完成：{e} Eh，用时 {t:.1f} s",
        "st_failed": "计算失败：{err}",
        "st_saved": "已保存：{path}",
        "st_preview": "命令已写入日志。",
        "st_sent_canvas": "已送回画布：{n} 个原子。",
        "st_scan_saved": "已导出扫描轨迹：{n} 帧。",
        "st_load_ok": "已载入 {n} 个原子。",
        "st_open_fail": "载入结构失败：{err}",
        "st_export_fail": "导出失败：{err}",
        "st_engine_error": "计算内核不可用：{err}",
        "st_detected": "已找到 xTB：{path}",
        "st_detect_fail": "没有找到 xTB 可执行文件。",
        "st_no_result": "还没有结果。",
        "st_need_optimized": "该结果没有优化后结构。",
        "st_workdir_missing": "工作目录不存在：{path}",
        # 日志
        "log_header": "—— xTB 计算 ——",
        "log_start": "结构 {n} 个原子｜方法 {method}｜任务 {job}｜工作目录 {dir}",
        "log_command": "命令：{cmd}",
        "log_warn": "提示：{msg}",
        "log_done": "完成：E = {e} Eh，gap = {g} eV，用时 {t:.1f} s",
        "log_fail": "失败：{err}",
        "log_cancel": "计算已取消。",
        # 对话框
        "dlg_open": "打开结构文件",
        "filter_struct": "结构文件 (*.xyz *.gjf *.com *.log *.out);;所有文件 (*.*)",
        "dlg_save_xyz": "导出 XYZ",
        "filter_xyz": "XYZ 文件 (*.xyz);;所有文件 (*.*)",
        "dlg_save_gjf": "导出 GJF",
        "filter_gjf": "Gaussian 输入 (*.gjf *.com);;所有文件 (*.*)",
        "dlg_save_json": "导出 JSON",
        "filter_json": "JSON 文件 (*.json);;所有文件 (*.*)",
        "dlg_save_scan": "导出扫描轨迹",
        "dlg_workdir": "选择工作目录",
        "dlg_exe": "选择 xTB 可执行文件",
        "filter_exe": "可执行文件 (*.exe);;所有文件 (*.*)",
        # 提示
        "tip_refresh": "从左侧画布重新读取当前分子（会覆盖手动打开的文件）",
        "tip_open": "支持 .xyz / .gjf / .com / .log / .out",
        "tip_detect": "按保存路径、XTB_EXE 环境变量、PATH、常见安装位置查找 xTB",
        "tip_run": "在后台运行 xTB，主界面不会卡住",
        "tip_cancel": "请求停止当前计算（会终止 xTB 进程）",
        "tip_preview": "只构造并显示命令，不真正运行",
        "tip_to_canvas": "把优化后（或扫描末帧）结构送回左侧画布",
        "tip_export_xyz": "导出结构为 XYZ（优先优化后坐标）",
        "tip_export_gjf": "导出 Gaussian 输入文件（含电荷与多重度）",
        "tip_export_json": "导出本次计算的完整 JSON 摘要",
        "tip_open_workdir": "在文件管理器中打开本次计算的工作目录",
        "tip_scan_export": "把每一帧写成多帧 XYZ 轨迹",
        "tip_parallel": "xTB 并行核数（--parallel）",
        "tip_extra": "拆分后附加到命令末尾的额外参数",
        "tip_workdir": "基目录：每次运行都会在其下新建独立的时间戳子目录（避免旧产物污染）；留空用默认位置",
        "tip_xcontrol": "job=scan 时写入 xcontrol 文件",
        "tip_acc": "SCF 收敛精度（--acc）",
        "tip_etemp": "电子温度（--etemp，单位 K）",
        "tip_solvation": "ALPB / GBSA / COSMO 隐式溶剂模型",
        "tip_method": "xTB 方法：g-xTB / GFN2 / GFN1 / GFN0 / GFN-FF",
    },
    "en": {
        # Groups
        "grp_source": "Structure source",
        "grp_calc": "Calculation settings",
        "grp_result": "Results",
        "grp_scan": "Scan results",
        # Structure source
        "btn_refresh": "Refresh from canvas",
        "btn_open": "Open file…",
        "src_canvas": "Canvas: {n} atoms",
        "src_canvas_empty": "No structure on canvas",
        "src_file": "File: {name} ({n} atoms)",
        # Calculation settings
        "lbl_exe": "xTB executable",
        "ph_exe": "Leave empty for auto-detect",
        "btn_browse_exe": "Browse…",
        "btn_detect": "Auto-detect",
        "lbl_method": "Method",
        "lbl_job": "Job",
        "lbl_charge": "Charge",
        "lbl_uhf": "Unpaired e-",
        "lbl_acc": "SCF accuracy",
        "lbl_etemp": "Electronic temp.",
        "lbl_solvation": "Solvation",
        "lbl_solvent": "Solvent",
        "lbl_parallel": "Threads",
        "chk_json": "Write JSON",
        "chk_molden": "Molden",
        "chk_verbose": "Verbose",
        "lbl_extra": "Extra args",
        "ph_extra": "Additional command-line arguments (optional)",
        "lbl_workdir": "Work folder",
        "ph_workdir": "Leave empty for the default base (a new timestamped "
                       "sub-folder per run)",
        "btn_browse_dir": "Browse…",
        "btn_open_dir": "Open folder",
        "lbl_xcontrol": "xcontrol content",
        "ph_xcontrol": ("$constrain\n force constant=0.50\n"
                        " dihedral: 8,5,1,4,60.0\n$scan\n 1: 60.0, 120.0, 6\n$end"),
        "hint_xcontrol": "Runs with --opt --input; the content must contain "
                         "$constrain and $scan.",
        "hint_ts": "Will write $opt ts=1 for transition-state optimization.",
        "hint_gxtb_solv": "g-xTB does not support solvation; it runs in vacuum.",
        # Buttons
        "btn_run": "Run xTB",
        "btn_cancel": "Stop",
        "btn_preview": "Preview command",
        "btn_to_canvas": "Send to canvas",
        "btn_export_xyz": "Export XYZ…",
        "btn_export_gjf": "Export GJF…",
        "btn_export_json": "Export JSON…",
        "btn_open_workdir": "Open work folder",
        "btn_export_scan": "Export scan trajectory XYZ…",
        # Result text
        "energy_none": "E = —",
        "energy_fmt": "E = {e} Eh",
        "gap_fmt": "HOMO-LUMO gap: {v} eV",
        "homo_fmt": "HOMO: {v} eV",
        "lumo_fmt": "LUMO: {v} eV",
        "dipole_fmt": "Dipole: {v} Debye",
        "grad_fmt": "Gradient norm: {v} Eh/Å",
        "na": "—",
        "vib_imag_fmt": "Imaginary modes: {n}",
        "vib_lowest_fmt": "Lowest modes: {vals} cm⁻¹",
        "thermo_fmt": "G = {g} Eh    H = {h} Eh    ZPE = {z} Eh",
        "lbl_charges": "Atomic charges",
        "col_index": "#",
        "col_element": "Element",
        "col_charge": "Charge",
        "scan_summary": "{n} frames, ΔE = {de} eV",
        "scan_x": "Scan step",
        "scan_y": "Relative energy (eV)",
        # Status line
        "st_ready": "Ready",
        "st_engine_missing": "xTB executable not found - use Auto-detect or Browse.",
        "st_no_struct": "No structure - refresh the canvas or open a file.",
        "st_invalid": "Invalid parameters: {err}",
        "st_phase": "{phase}… {t:.1f} s elapsed",
        "phase_preparing": "Preparing",
        "phase_running": "Running",
        "phase_parsing": "Parsing results",
        "st_cancelling": "Stopping…",
        "st_cancelled": "Cancelled ({t:.1f} s)",
        "st_done": "Done: {e} Eh in {t:.1f} s",
        "st_failed": "Calculation failed: {err}",
        "st_saved": "Saved: {path}",
        "st_preview": "Command written to the log.",
        "st_sent_canvas": "Sent {n} atoms to the canvas.",
        "st_scan_saved": "Exported {n} scan frames.",
        "st_load_ok": "Loaded {n} atoms.",
        "st_open_fail": "Failed to load structure: {err}",
        "st_export_fail": "Export failed: {err}",
        "st_engine_error": "Calculation engine unavailable: {err}",
        "st_detected": "Found xTB: {path}",
        "st_detect_fail": "xTB executable not found.",
        "st_no_result": "No results yet.",
        "st_need_optimized": "This result has no optimized structure.",
        "st_workdir_missing": "Work folder does not exist: {path}",
        # Log
        "log_header": "--- xTB calculation ---",
        "log_start": "{n} atoms | method {method} | job {job} | workdir {dir}",
        "log_command": "Command: {cmd}",
        "log_warn": "Note: {msg}",
        "log_done": "Done: E = {e} Eh, gap = {g} eV, {t:.1f} s",
        "log_fail": "Failed: {err}",
        "log_cancel": "Calculation cancelled.",
        # Dialogs
        "dlg_open": "Open structure file",
        "filter_struct": "Structure files (*.xyz *.gjf *.com *.log *.out);;All files (*.*)",
        "dlg_save_xyz": "Export XYZ",
        "filter_xyz": "XYZ files (*.xyz);;All files (*.*)",
        "dlg_save_gjf": "Export GJF",
        "filter_gjf": "Gaussian input (*.gjf *.com);;All files (*.*)",
        "dlg_save_json": "Export JSON",
        "filter_json": "JSON files (*.json);;All files (*.*)",
        "dlg_save_scan": "Export scan trajectory",
        "dlg_workdir": "Choose work folder",
        "dlg_exe": "Choose xTB executable",
        "filter_exe": "Executables (*.exe);;All files (*.*)",
        # Tooltips
        "tip_refresh": "Re-read the molecule on the left canvas (overrides an opened file)",
        "tip_open": "Supports .xyz / .gjf / .com / .log / .out",
        "tip_detect": "Search saved path, XTB_EXE, PATH and common install locations",
        "tip_run": "Run xTB in the background without blocking the UI",
        "tip_cancel": "Request cancellation (terminates the xTB process)",
        "tip_preview": "Build and show the command without running it",
        "tip_to_canvas": "Send the optimized (or last scan) structure to the canvas",
        "tip_export_xyz": "Export the structure as XYZ (optimized coordinates first)",
        "tip_export_gjf": "Export a Gaussian input with charge and multiplicity",
        "tip_export_json": "Export a complete JSON summary of this calculation",
        "tip_open_workdir": "Open this calculation's work folder in the file manager",
        "tip_scan_export": "Write every frame as a multi-frame XYZ trajectory",
        "tip_parallel": "xTB thread count (--parallel)",
        "tip_extra": "Extra arguments appended to the command after shell splitting",
        "tip_workdir": "Base folder: every run creates a fresh timestamped "
                        "sub-folder under it (so old artefacts cannot leak into "
                        "a new result); leave empty for the default location",
        "tip_xcontrol": "Written as the xcontrol file for job=scan",
        "tip_acc": "SCF convergence accuracy (--acc)",
        "tip_etemp": "Electronic temperature (--etemp, K)",
        "tip_solvation": "ALPB / GBSA / COSMO implicit solvation model",
        "tip_method": "xTB method: g-xTB / GFN2 / GFN1 / GFN0 / GFN-FF",
    },
}

_STATUS_COLORS = {
    "normal": "#2b2b2b",
    "ok": "#1a7a4c",
    "warn": "#b07200",
    "error": "#b3261e",
}


class _ScanCanvas(FigureCanvasQTAgg):
    """随控件尺寸缩放的扫描曲线画布（与 surface_projection 面板同款）。"""

    def __init__(self, figure, min_height=170):
        super().__init__(figure)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumHeight(int(min_height))
        self.setMaximumHeight(260)

    def resizeEvent(self, event):                                # noqa: N802
        super().resizeEvent(event)
        w = max(self.width(), 60)
        h = max(self.height(), 60)
        dpi = float(self.figure.get_dpi()) or 100.0
        self.figure.set_size_inches(w / dpi, h / dpi, forward=False)
        self.draw_idle()


class XtbWorker(QThread):
    """后台跑 ``xtb.run_job``：日志 / 阶段 / 结果都通过信号回主线程。"""

    line = pyqtSignal(str)
    progress = pyqtSignal(str, str)          # (step, 引擎给的本地化文字)
    done = pyqtSignal(dict)                  # {ok, result, error, cancelled, traceback, elapsed}

    def __init__(self, params, symbols, coords, workdir, lang, parent=None):
        super().__init__(parent)
        self._params = dict(params)
        self._symbols = [str(s) for s in symbols]
        self._coords = np.asarray(coords, dtype=float)
        self._workdir = str(workdir)
        self._lang = str(lang or "zh")
        self._cancel_event = threading.Event()
        self._started_at = 0.0

    # ── 取消 ─────────────────────────────────────────────────────────
    def cancel(self):
        self._cancel_event.set()

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    # ── 线程入口 ─────────────────────────────────────────────────────
    def run(self):
        self._started_at = time.monotonic()
        try:
            eng = _engine_module()
        except Exception as exc:                             # noqa: BLE001
            self.done.emit({"ok": False, "error": str(exc),
                            "elapsed": time.monotonic() - self._started_at})
            return
        error_cls = getattr(eng, "XtbError", RuntimeError)
        try:
            result = eng.run_job(
                self._params, self._symbols, self._coords, self._workdir,
                on_line=self._emit_line,
                on_progress=lambda step, text: self.progress.emit(
                    str(step or ""), str(text or "")),
                should_cancel=self.is_cancelled,
                lang=self._lang,
            )
        except error_cls as exc:                             # noqa: BLE001
            cancelled = self.is_cancelled()
            self.done.emit({
                "ok": False, "cancelled": cancelled,
                "error": str(exc),
                "elapsed": time.monotonic() - self._started_at,
            })
            return
        except Exception as exc:                             # noqa: BLE001
            self.done.emit({
                "ok": False, "error": str(exc),
                "traceback": traceback.format_exc(),
                "elapsed": time.monotonic() - self._started_at,
            })
            return
        elapsed = time.monotonic() - self._started_at
        if self.is_cancelled() or bool(getattr(result, "cancelled", False)):
            self.done.emit({"ok": False, "cancelled": True, "result": result,
                            "error": "cancelled", "elapsed": elapsed})
            return
        self.done.emit({"ok": True, "result": result, "elapsed": elapsed})

    def _emit_line(self, text):
        if text is None:
            return
        self.line.emit(str(text))


class XtbPanel(QWidget):
    """「xTB 计算」页：结构来源 + 计算设置 + 后台运行 + 结果/导出。"""

    #: 右栏内容宽约 680px；布局自适应，这里只是保证不会被长文案顶破。
    MIN_WIDTH_CAP = 620

    def __init__(self, get_structure=None, on_structure_loaded=None,
                 log_func=None, parent=None):
        super().__init__(parent)
        self.lang = "zh"
        self._get_structure = get_structure if callable(get_structure) else (lambda: None)
        self._on_structure_loaded = (on_structure_loaded
                                     if callable(on_structure_loaded) else None)
        self._log_func = log_func

        self._worker = None
        self._result = None
        self._symbols = []
        self._coords = None
        self._source_kind = "canvas"          # 'canvas' | 'file'
        self._source_path = ""

        # 状态行：key 形式可随 set_lang 重译；literal 用于引擎错误原文
        self._status_key = None
        self._status_fmt = {}
        self._status_literal = None
        self._status_level = "normal"

        # 运行计时
        self._run_started = 0.0
        self._run_phase_key = "phase_preparing"
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(250)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)

        # 工作目录
        self._loaded_workdir = ""
        self._last_workdir = ""
        self._workdir_base = ""
        self._workdir_user_edited = False
        self._loading_settings = False

        self._scan_ev = []

        self._build_ui()
        self._apply_lang()
        self._load_settings()
        self._auto_detect(initial=True)
        self._sync_job_widgets()
        self._sync_gxtb_solvation()
        self._refresh_from_canvas(initial=True)
        self._update_result_labels()
        self._hide_scan()
        self._set_export_enabled(False)

        if not self.edit_exe.text().strip():
            self._set_status_i18n("st_engine_missing", "warn")
        else:
            self._set_status_i18n("st_ready")

    # ── 尺寸 ─────────────────────────────────────────────────────────
    def minimumSizeHint(self):                                    # noqa: N802
        hint = super().minimumSizeHint()
        return QSize(min(hint.width(), self.MIN_WIDTH_CAP), hint.height())

    # ── i18n ─────────────────────────────────────────────────────────
    def _t(self, key, **fmt):
        table = _TR.get(self.lang) or _TR["zh"]
        text = table.get(key)
        if text is None:
            text = _TR["zh"].get(key, key)
        return text.format(**fmt) if fmt else text

    def set_lang(self, lang):
        self.lang = "zh" if str(lang).lower().startswith("zh") else "en"
        self._apply_lang()
        self._update_result_labels()
        self._refresh_source_label()
        if self._result is not None and getattr(self._result, "scan", None):
            self._render_scan(self._result)
        self._render_status()

    def _apply_lang(self):
        # 分组标题
        self.grp_source.setTitle(self._t("grp_source"))
        self.grp_calc.setTitle(self._t("grp_calc"))
        self.grp_result.setTitle(self._t("grp_result"))
        self.grp_scan.setTitle(self._t("grp_scan"))

        # 结构来源
        self.btn_refresh.setText(self._t("btn_refresh"))
        self.btn_refresh.setToolTip(self._t("tip_refresh"))
        self.btn_open.setText(self._t("btn_open"))
        self.btn_open.setToolTip(self._t("tip_open"))

        # 计算设置：标签 / 占位 / 提示
        self.lbl_exe.setText(self._t("lbl_exe"))
        self.edit_exe.setPlaceholderText(self._t("ph_exe"))
        self.btn_browse_exe.setText(self._t("btn_browse_exe"))
        self.btn_detect.setText(self._t("btn_detect"))
        self.btn_detect.setToolTip(self._t("tip_detect"))
        self.lbl_method.setText(self._t("lbl_method"))
        self.lbl_method.setToolTip(self._t("tip_method"))
        self.cmb_method.setToolTip(self._t("tip_method"))
        self.lbl_job.setText(self._t("lbl_job"))
        self.lbl_charge.setText(self._t("lbl_charge"))
        self.lbl_uhf.setText(self._t("lbl_uhf"))
        self.lbl_acc.setText(self._t("lbl_acc"))
        self.lbl_acc.setToolTip(self._t("tip_acc"))
        self.spn_acc.setToolTip(self._t("tip_acc"))
        self.lbl_etemp.setText(self._t("lbl_etemp"))
        self.lbl_etemp.setToolTip(self._t("tip_etemp"))
        self.spn_etemp.setToolTip(self._t("tip_etemp"))
        self.lbl_solvation.setText(self._t("lbl_solvation"))
        self.lbl_solvation.setToolTip(self._t("tip_solvation"))
        self.cmb_solvation.setToolTip(self._t("tip_solvation"))
        self.lbl_solvent.setText(self._t("lbl_solvent"))
        self.lbl_parallel.setText(self._t("lbl_parallel"))
        self.lbl_parallel.setToolTip(self._t("tip_parallel"))
        self.spn_parallel.setToolTip(self._t("tip_parallel"))
        self.chk_json.setText(self._t("chk_json"))
        self.chk_molden.setText(self._t("chk_molden"))
        self.chk_verbose.setText(self._t("chk_verbose"))
        self.lbl_extra.setText(self._t("lbl_extra"))
        self.edit_extra.setPlaceholderText(self._t("ph_extra"))
        self.edit_extra.setToolTip(self._t("tip_extra"))
        self.lbl_workdir.setText(self._t("lbl_workdir"))
        self.edit_workdir.setPlaceholderText(self._t("ph_workdir"))
        self.edit_workdir.setToolTip(self._t("tip_workdir"))
        self.btn_browse_dir.setText(self._t("btn_browse_dir"))
        self.btn_open_dir.setText(self._t("btn_open_dir"))
        self.lbl_xcontrol.setText(self._t("lbl_xcontrol"))
        self.lbl_xcontrol.setToolTip(self._t("tip_xcontrol"))
        self.txt_xcontrol.setPlaceholderText(self._t("ph_xcontrol"))
        self.lbl_scan_hint.setText(self._t("hint_xcontrol"))
        self.lbl_ts_hint.setText(self._t("hint_ts"))
        self.lbl_gxtb_hint.setText(self._t("hint_gxtb_solv"))

        # 按钮
        self.btn_run.setText(self._t("btn_run"))
        self.btn_run.setToolTip(self._t("tip_run"))
        self.btn_cancel.setText(self._t("btn_cancel"))
        self.btn_cancel.setToolTip(self._t("tip_cancel"))
        self.btn_preview.setText(self._t("btn_preview"))
        self.btn_preview.setToolTip(self._t("tip_preview"))
        self.btn_to_canvas.setText(self._t("btn_to_canvas"))
        self.btn_to_canvas.setToolTip(self._t("tip_to_canvas"))
        self.btn_export_xyz.setText(self._t("btn_export_xyz"))
        self.btn_export_xyz.setToolTip(self._t("tip_export_xyz"))
        self.btn_export_gjf.setText(self._t("btn_export_gjf"))
        self.btn_export_gjf.setToolTip(self._t("tip_export_gjf"))
        self.btn_export_json.setText(self._t("btn_export_json"))
        self.btn_export_json.setToolTip(self._t("tip_export_json"))
        self.btn_open_workdir.setText(self._t("btn_open_workdir"))
        self.btn_open_workdir.setToolTip(self._t("tip_open_workdir"))
        self.btn_export_scan.setText(self._t("btn_export_scan"))
        self.btn_export_scan.setToolTip(self._t("tip_scan_export"))

        # 结果区静态文字 / 表头
        self.lbl_charges_title.setText(self._t("lbl_charges"))
        self.tbl_charges.setHorizontalHeaderLabels(
            [self._t("col_index"), self._t("col_element"), self._t("col_charge")])
        self.lbl_scan_summary.setText("")

        # 下拉项文字
        self._relabel_combo(self.cmb_method, _method_table())
        self._relabel_combo(self.cmb_job, _job_table())
        self._relabel_combo(self.cmb_solvation, _solvation_table())

        # 动态提示 / 状态行重译
        self._sync_job_widgets()
        self._sync_gxtb_solvation()
        self._render_status()

    def _relabel_combo(self, combo, table):
        for i in range(combo.count()):
            key = combo.itemData(i)
            if isinstance(key, str) and key in table:
                item = table[key] or {}
                label = item.get(self.lang) or item.get("zh") or key
                combo.setItemText(i, str(label))

    # ── UI 构建 ──────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        root.addWidget(self._build_source_group())
        root.addWidget(self._build_calc_group())
        root.addLayout(self._build_action_row())

        self.lbl_status = QLabel()
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.lbl_status)

        root.addWidget(self._build_result_group())
        root.addWidget(self._build_scan_group())

    def _build_source_group(self):
        self.grp_source = QGroupBox()
        gv = QVBoxLayout(self.grp_source)
        gv.setContentsMargins(8, 4, 8, 4)
        gv.setSpacing(3)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.btn_refresh = QPushButton()
        self.btn_refresh.clicked.connect(self._refresh_from_canvas)
        self.btn_open = QPushButton()
        self.btn_open.clicked.connect(self._open_file_dialog)
        row.addWidget(self.btn_refresh)
        row.addWidget(self.btn_open)
        row.addStretch(1)
        gv.addLayout(row)

        self.lbl_source = QLabel()
        self.lbl_source.setWordWrap(True)
        self.lbl_source.setStyleSheet("color:#5b6573;")
        gv.addWidget(self.lbl_source)
        return self.grp_source

    def _build_calc_group(self):
        self.grp_calc = QGroupBox()
        gv = QVBoxLayout(self.grp_calc)
        gv.setContentsMargins(8, 4, 8, 4)
        gv.setSpacing(4)

        # xTB 可执行文件
        exe_row = QHBoxLayout()
        exe_row.setSpacing(5)
        self.lbl_exe = QLabel()
        self.edit_exe = QLineEdit()
        self.edit_exe.setMinimumWidth(120)
        self.edit_exe.editingFinished.connect(self._on_edit_changed)
        self.btn_browse_exe = QPushButton()
        self.btn_browse_exe.clicked.connect(self._browse_executable)
        self.btn_detect = QPushButton()
        self.btn_detect.clicked.connect(self._detect_executable_clicked)
        exe_row.addWidget(self.lbl_exe)
        exe_row.addWidget(self.edit_exe, 1)
        exe_row.addWidget(self.btn_browse_exe)
        exe_row.addWidget(self.btn_detect)
        gv.addLayout(exe_row)

        g = QGridLayout()
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(3)

        cpus = max(1, int(os.cpu_count() or 4))
        self.cmb_method = QComboBox()
        for key in _method_table():
            self.cmb_method.addItem("", str(key))
        self._set_combo_data(self.cmb_method, "gfn2")
        self.cmb_method.currentIndexChanged.connect(self._on_method_changed)
        self.cmb_job = QComboBox()
        for key in _job_table():
            self.cmb_job.addItem("", str(key))
        self._set_combo_data(self.cmb_job, "opt")
        self.cmb_job.currentIndexChanged.connect(self._on_job_changed)

        self.spn_charge = QSpinBox()
        self.spn_charge.setRange(-10, 10)
        self.spn_charge.setValue(0)
        self.spn_charge.setMinimumWidth(74)
        self.spn_uhf = QSpinBox()
        self.spn_uhf.setRange(0, 20)
        self.spn_uhf.setValue(0)
        self.spn_uhf.setMinimumWidth(74)
        self.spn_acc = QDoubleSpinBox()
        self.spn_acc.setDecimals(3)
        self.spn_acc.setRange(0.01, 10.0)
        self.spn_acc.setSingleStep(0.1)
        self.spn_acc.setValue(1.0)
        self.spn_acc.setMinimumWidth(84)
        self.spn_etemp = QSpinBox()
        self.spn_etemp.setRange(0, 10000)
        self.spn_etemp.setSingleStep(100)
        self.spn_etemp.setValue(300)
        self.spn_etemp.setSuffix(" K")
        self.spn_etemp.setMinimumWidth(88)

        self.cmb_solvation = QComboBox()
        for key in _solvation_table():
            self.cmb_solvation.addItem("", str(key))
        self._set_combo_data(self.cmb_solvation, "gas")
        self.cmb_solvation.currentIndexChanged.connect(self._on_solvation_changed)
        self.cmb_solvent = QComboBox()
        self._fill_solvent_combo("alpb")
        self.cmb_solvent.setEnabled(False)

        self.spn_parallel = QSpinBox()
        self.spn_parallel.setRange(1, cpus)
        self.spn_parallel.setValue(min(4, cpus))
        self.spn_parallel.setMinimumWidth(74)

        self.chk_json = QCheckBox()
        self.chk_json.setChecked(True)
        self.chk_molden = QCheckBox()
        self.chk_verbose = QCheckBox()

        self.lbl_method = QLabel()
        self.lbl_job = QLabel()
        self.lbl_charge = QLabel()
        self.lbl_uhf = QLabel()
        self.lbl_acc = QLabel()
        self.lbl_etemp = QLabel()
        self.lbl_solvation = QLabel()
        self.lbl_solvent = QLabel()
        self.lbl_parallel = QLabel()
        self.lbl_extra = QLabel()
        self.lbl_workdir = QLabel()

        opts_host = QWidget()
        opts = QHBoxLayout(opts_host)
        opts.setContentsMargins(0, 0, 0, 0)
        opts.setSpacing(8)
        for _w in (self.chk_json, self.chk_molden, self.chk_verbose):
            opts.addWidget(_w)
        opts.addStretch(1)

        # 方法 / 任务各占一整行：英文任务名（Opt + Hessian (frequency)）较长，
        # 并排两列会被省略号截断。
        g.addWidget(self.lbl_method, 0, 0)
        g.addWidget(self.cmb_method, 0, 1, 1, 3)
        g.addWidget(self.lbl_job, 1, 0)
        g.addWidget(self.cmb_job, 1, 1, 1, 3)
        g.addWidget(self.lbl_charge, 2, 0)
        g.addWidget(self.spn_charge, 2, 1)
        g.addWidget(self.lbl_uhf, 2, 2)
        g.addWidget(self.spn_uhf, 2, 3)
        g.addWidget(self.lbl_acc, 3, 0)
        g.addWidget(self.spn_acc, 3, 1)
        g.addWidget(self.lbl_etemp, 3, 2)
        g.addWidget(self.spn_etemp, 3, 3)
        g.addWidget(self.lbl_solvation, 4, 0)
        g.addWidget(self.cmb_solvation, 4, 1)
        g.addWidget(self.lbl_solvent, 4, 2)
        g.addWidget(self.cmb_solvent, 4, 3)
        g.addWidget(self.lbl_parallel, 5, 0)
        g.addWidget(self.spn_parallel, 5, 1)
        g.addWidget(opts_host, 5, 2, 1, 2)
        g.addWidget(self.lbl_extra, 6, 0)
        self.edit_extra = QLineEdit()
        self.edit_extra.editingFinished.connect(self._on_edit_changed)
        g.addWidget(self.edit_extra, 6, 1, 1, 3)
        g.setColumnStretch(1, 1)
        g.setColumnStretch(2, 1)
        g.setColumnStretch(3, 1)
        gv.addLayout(g)

        self.lbl_gxtb_hint = QLabel()
        self.lbl_gxtb_hint.setWordWrap(True)
        self.lbl_gxtb_hint.setStyleSheet("color:#b07200;")
        self.lbl_gxtb_hint.setVisible(False)
        gv.addWidget(self.lbl_gxtb_hint)

        # 工作目录
        wd_row = QHBoxLayout()
        wd_row.setSpacing(5)
        self.edit_workdir = QLineEdit()
        self.edit_workdir.setMinimumWidth(120)
        self.edit_workdir.textEdited.connect(self._on_workdir_edited)
        self.btn_browse_dir = QPushButton()
        self.btn_browse_dir.clicked.connect(self._browse_workdir)
        self.btn_open_dir = QPushButton()
        self.btn_open_dir.clicked.connect(self._open_workdir)
        wd_row.addWidget(self.lbl_workdir)
        wd_row.addWidget(self.edit_workdir, 1)
        wd_row.addWidget(self.btn_browse_dir)
        wd_row.addWidget(self.btn_open_dir)
        gv.addLayout(wd_row)

        # job=scan 的 xcontrol 编辑区
        self.scan_box = QWidget()
        sv = QVBoxLayout(self.scan_box)
        sv.setContentsMargins(0, 2, 0, 0)
        sv.setSpacing(2)
        self.lbl_xcontrol = QLabel()
        self.txt_xcontrol = QTextEdit()
        self.txt_xcontrol.setMinimumHeight(78)
        self.txt_xcontrol.setMaximumHeight(110)
        self.txt_xcontrol.setStyleSheet(
            "QTextEdit { font-family: 'Cascadia Mono', 'Consolas', monospace; }")
        self.lbl_scan_hint = QLabel()
        self.lbl_scan_hint.setWordWrap(True)
        self.lbl_scan_hint.setStyleSheet("color:#5b6573;")
        sv.addWidget(self.lbl_xcontrol)
        sv.addWidget(self.txt_xcontrol)
        sv.addWidget(self.lbl_scan_hint)
        self.scan_box.setVisible(False)
        gv.addWidget(self.scan_box)

        self.lbl_ts_hint = QLabel()
        self.lbl_ts_hint.setWordWrap(True)
        self.lbl_ts_hint.setStyleSheet("color:#5b6573;")
        self.lbl_ts_hint.setVisible(False)
        gv.addWidget(self.lbl_ts_hint)

        for _combo in (self.cmb_method, self.cmb_job, self.cmb_solvation,
                       self.cmb_solvent):
            _combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            _combo.setMinimumContentsLength(6)
            _combo.setMinimumWidth(110)
        # 「气相（无溶剂）」/ solvent 名较长：保证不省略成「气相（无溶…」
        self.cmb_solvation.setMinimumWidth(138)
        self.cmb_solvent.setMinimumWidth(142)

        # 运行中需要禁用的参数控件
        self._param_widgets = [
            self.edit_exe, self.btn_browse_exe, self.btn_detect,
            self.cmb_method, self.cmb_job, self.spn_charge, self.spn_uhf,
            self.spn_acc, self.spn_etemp, self.cmb_solvation, self.cmb_solvent,
            self.spn_parallel, self.chk_json, self.chk_molden, self.chk_verbose,
            self.edit_extra, self.edit_workdir, self.btn_browse_dir,
            self.btn_open_dir, self.txt_xcontrol,
        ]
        return self.grp_calc

    def _build_action_row(self):
        row = QHBoxLayout()
        row.setSpacing(6)
        self.btn_run = QPushButton()
        self.btn_run.setDefault(True)
        self.btn_run.setMinimumHeight(32)
        self.btn_run.clicked.connect(self.start)
        self.btn_cancel = QPushButton()
        self.btn_cancel.setMinimumHeight(32)
        self.btn_cancel.clicked.connect(self.cancel)
        self.btn_cancel.setEnabled(False)
        self.btn_preview = QPushButton()
        self.btn_preview.setMinimumHeight(32)
        self.btn_preview.clicked.connect(self._preview_command)
        row.addWidget(self.btn_run, 1)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_preview)
        return row

    def _build_result_group(self):
        self.grp_result = QGroupBox()
        g = QGridLayout(self.grp_result)
        g.setContentsMargins(8, 6, 8, 6)
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(3)

        self.lbl_energy = QLabel()
        f = QFont(self.font())
        base_pt = f.pointSize() if f.pointSize() > 0 else 9
        f.setPointSize(max(12, base_pt + 5))
        f.setBold(True)
        self.lbl_energy.setFont(f)
        self.lbl_energy.setStyleSheet("color:#123f8a;")
        self.lbl_energy.setTextInteractionFlags(Qt.TextSelectableByMouse)
        g.addWidget(self.lbl_energy, 0, 0, 1, 4)

        self.lbl_gap = QLabel()
        self.lbl_homo = QLabel()
        self.lbl_lumo = QLabel()
        self.lbl_dipole = QLabel()
        self.lbl_grad = QLabel()
        for _lab in (self.lbl_gap, self.lbl_homo, self.lbl_lumo,
                     self.lbl_dipole, self.lbl_grad):
            _lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        g.addWidget(self.lbl_gap, 1, 0, 1, 2)
        g.addWidget(self.lbl_homo, 1, 2, 1, 1)
        g.addWidget(self.lbl_lumo, 1, 3, 1, 1)
        g.addWidget(self.lbl_dipole, 2, 0, 1, 2)
        g.addWidget(self.lbl_grad, 2, 2, 1, 2)

        self.lbl_vib = QLabel()
        self.lbl_vib.setWordWrap(True)
        self.lbl_vib.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_thermo = QLabel()
        self.lbl_thermo.setWordWrap(True)
        self.lbl_thermo.setTextInteractionFlags(Qt.TextSelectableByMouse)
        g.addWidget(self.lbl_vib, 3, 0, 1, 4)
        g.addWidget(self.lbl_thermo, 4, 0, 1, 4)

        self.lbl_charges_title = QLabel()
        self.lbl_charges_title.setStyleSheet("color:#5b6573;")
        g.addWidget(self.lbl_charges_title, 5, 0, 1, 4)

        self.tbl_charges = QTableWidget(0, 3)
        self.tbl_charges.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tbl_charges.setSelectionBehavior(QTableWidget.SelectRows)
        self.tbl_charges.setAlternatingRowColors(True)
        self.tbl_charges.verticalHeader().setVisible(False)
        self.tbl_charges.horizontalHeader().setStretchLastSection(True)
        self.tbl_charges.setMinimumHeight(150)
        self.tbl_charges.setMaximumHeight(170)
        self.tbl_charges.setColumnWidth(0, 48)
        self.tbl_charges.setColumnWidth(1, 72)
        g.addWidget(self.tbl_charges, 6, 0, 1, 4)

        self.btn_to_canvas = QPushButton()
        self.btn_to_canvas.clicked.connect(self._send_to_canvas)
        self.btn_export_xyz = QPushButton()
        self.btn_export_xyz.clicked.connect(self._export_xyz)
        self.btn_export_gjf = QPushButton()
        self.btn_export_gjf.clicked.connect(self._export_gjf)
        self.btn_export_json = QPushButton()
        self.btn_export_json.clicked.connect(self._export_json)
        self.btn_open_workdir = QPushButton()
        self.btn_open_workdir.clicked.connect(self._open_workdir)

        row = QHBoxLayout()
        row.setSpacing(5)
        row.addWidget(self.btn_to_canvas, 1)
        row.addWidget(self.btn_export_xyz, 1)
        row.addWidget(self.btn_export_gjf, 1)
        row.addWidget(self.btn_export_json, 1)
        g.addLayout(row, 7, 0, 1, 4)

        row2 = QHBoxLayout()
        row2.setSpacing(5)
        row2.addWidget(self.btn_open_workdir, 1)
        g.addLayout(row2, 8, 0, 1, 4)

        for col in range(4):
            g.setColumnStretch(col, 1)
        return self.grp_result

    def _build_scan_group(self):
        self.grp_scan = QGroupBox()
        sv = QVBoxLayout(self.grp_scan)
        sv.setContentsMargins(8, 6, 8, 6)
        sv.setSpacing(4)

        self.lbl_scan_summary = QLabel()
        self.lbl_scan_summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        sv.addWidget(self.lbl_scan_summary)

        self.scan_figure = Figure(figsize=(4.8, 2.0), dpi=100)
        self.scan_canvas = _ScanCanvas(self.scan_figure)
        sv.addWidget(self.scan_canvas)

        self.btn_export_scan = QPushButton()
        self.btn_export_scan.clicked.connect(self._export_scan_traj)
        sv.addWidget(self.btn_export_scan)

        self.grp_scan.setVisible(False)
        return self.grp_scan

    # ── 小工具 ───────────────────────────────────────────────────────
    def _set_combo_data(self, combo, key):
        key = str(key)
        idx = combo.findData(key)
        if idx >= 0:
            combo.setCurrentIndex(idx)
            return True
        return False

    def _fill_solvent_combo(self, model):
        names = list(_solvents_for(model))
        if not names:
            # 真空（gas）：保留上一次的溶剂列表但置灰，避免下拉框变成空白。
            return
        current = self.cmb_solvent.currentText()
        self.cmb_solvent.blockSignals(True)
        self.cmb_solvent.clear()
        for name in names:
            self.cmb_solvent.addItem(str(name), str(name))
        if current:
            idx = self.cmb_solvent.findText(current)
            if idx >= 0:
                self.cmb_solvent.setCurrentIndex(idx)
        self.cmb_solvent.blockSignals(False)

    def _log(self, msg):
        if callable(self._log_func):
            try:
                self._log_func(str(msg))
            except Exception:                                     # noqa: BLE001
                pass

    def _set_status(self, text, level="normal"):
        self._status_key = None
        self._status_fmt = {}
        self._status_literal = str(text)
        self._status_level = level
        self._render_status()

    def _set_status_i18n(self, key, level="normal", **fmt):
        self._status_key = key
        self._status_fmt = dict(fmt)
        self._status_literal = None
        self._status_level = level
        self._render_status()

    def _render_status(self):
        if self._status_key is not None:
            try:
                text = self._t(self._status_key, **self._status_fmt)
            except (KeyError, IndexError, ValueError):
                text = self._status_key
        else:
            text = self._status_literal or ""
        self.lbl_status.setText(str(text))
        self.lbl_status.setStyleSheet(
            "color:%s;" % _STATUS_COLORS.get(self._status_level,
                                             _STATUS_COLORS["normal"]))

    def _busy(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def _on_edit_changed(self, *_args):
        # 参数改完即落盘（轻量、无对话框）；读取/写盘失败静默。
        self._save_settings()

    def _on_workdir_edited(self, *_args):
        self._workdir_user_edited = True

    # ── 结构来源 ─────────────────────────────────────────────────────
    def _refresh_source_label(self):
        n = len(self._symbols)
        if n == 0:
            self.lbl_source.setText(self._t("src_canvas_empty"))
            return
        if self._source_kind == "file" and self._source_path:
            self.lbl_source.setText(self._t(
                "src_file", name=Path(self._source_path).name, n=n))
        else:
            self.lbl_source.setText(self._t("src_canvas", n=n))

    def refresh_canvas(self):
        """公开入口：从左侧画布重新取结构。"""
        self._refresh_from_canvas()

    def showEvent(self, event):                                    # noqa: N802
        """切到本页时自动同步左侧画布（手动打开文件时保持文件优先）。"""
        super().showEvent(event)
        if self._busy() or self._source_kind == "file":
            return
        try:
            got = self._get_structure()
        except Exception:                                          # noqa: BLE001
            got = None
        if not got or len(got) < 2:
            if self._symbols:
                self._clear_structure()
            return
        symbols, coords = got
        try:
            coords = np.asarray(coords, dtype=float)
            same = (self._symbols and self._coords is not None
                    and len(symbols) == len(self._symbols)
                    and coords.shape == self._coords.shape
                    and np.array_equal(coords, self._coords))
        except Exception:                                          # noqa: BLE001
            same = False
        if not same:
            self._refresh_from_canvas()

    def _refresh_from_canvas(self, *_args, initial=False):
        if self._busy():
            return
        self._workdir_user_edited = False
        try:
            got = self._get_structure()
        except Exception as exc:                                  # noqa: BLE001
            self._log(self._t("st_open_fail", err=exc))
            got = None
        if not got or len(got) < 2:
            self._clear_structure()
            if not initial:
                self._set_status_i18n("src_canvas_empty", "warn")
            return
        symbols, coords = got
        coords = np.asarray(coords, dtype=float)
        # 只有结构/来源真的变了才把工作目录基目录复位；同一结构点「刷新
        # 画布结构」不应静默丢掉用户自定义的输出基目录。
        if not initial and not self._same_structure(symbols, coords):
            self._workdir_base = ""
        self._set_structure(symbols, coords, kind="canvas")

    def _same_structure(self, symbols, coords) -> bool:
        if not self._symbols or self._coords is None:
            return False
        if len(symbols) != len(self._symbols) or list(symbols) != list(self._symbols):
            return False
        try:
            return (self._coords.shape == coords.shape
                    and bool(np.array_equal(self._coords, coords)))
        except Exception:                                          # noqa: BLE001
            return False

    def _set_structure(self, symbols, coords, kind="canvas", path=""):
        symbols = [str(s) for s in symbols]
        try:
            coords = np.asarray(coords, dtype=float)
        except Exception:                                          # noqa: BLE001
            coords = None
        if (coords is None or coords.ndim != 2 or coords.shape[1] != 3
                or coords.shape[0] != len(symbols)):
            self._clear_structure()
            self._set_status(self._t("st_open_fail", err="bad coordinates"), "error")
            return False
        changed = not self._same_structure(symbols, coords)
        self._symbols = symbols
        self._coords = coords
        self._source_kind = "canvas" if kind == "canvas" else "file"
        self._source_path = str(path or "")
        if changed:
            self._clear_result()
        self._refresh_source_label()
        self._set_status_i18n("st_load_ok", n=len(symbols))
        return True

    def _clear_structure(self):
        self._symbols = []
        self._coords = None
        self._source_path = ""
        self._clear_result()
        self._refresh_source_label()

    def _clear_result(self):
        self._result = None
        self._update_result_labels()
        self._fill_charges(None)
        self._set_export_enabled(False)
        self._hide_scan()

    def _default_dir(self) -> Path:
        if self._source_kind == "file" and self._source_path:
            return Path(self._source_path).parent
        return Path(tempfile.gettempdir())

    def _open_file_dialog(self):
        if self._busy():
            return
        path, _f = QFileDialog.getOpenFileName(
            self, self._t("dlg_open"), str(self._default_dir()),
            self._t("filter_struct"))
        if path:
            self.load_file(path)

    def load_file(self, path) -> bool:
        """载入 xyz / gjf / com / log / out 结构文件（测试直接调用）。"""
        if self._busy():
            return False
        path = str(path)
        try:
            from molstudio.core.surface_projection import load_atoms  # noqa: PLC0415
            symbols, coords = load_atoms(path)
        except Exception as exc:                                  # noqa: BLE001
            msg = self._t("st_open_fail", err=exc)
            self._set_status(msg, "error")
            self._log("  " + msg)
            return False
        ok = self._set_structure(symbols, coords, kind="file", path=path)
        if ok:
            self._workdir_user_edited = False
            self._workdir_base = ""
            self._log(self._t("st_load_ok", n=len(symbols)))
        return ok

    # ── 设置持久化 ───────────────────────────────────────────────────
    def _settings_path(self):
        return settings_file()

    def _load_settings(self):
        # 读设置时下拉框会触发 *_changed → _save_settings；用标记避免把
        # 半加载状态写回文件（损坏文件也只是静默回退默认）。
        self._loading_settings = True
        cfg = configparser.ConfigParser()
        path = self._settings_path()
        try:
            if path and os.path.exists(path):
                cfg.read(path, encoding="utf-8")
        except Exception:                                          # noqa: BLE001
            self._loading_settings = False
            return
        if not cfg.has_section("xtb"):
            self._loading_settings = False
            return
        sec = cfg["xtb"]

        def _get(key, default=""):
            try:
                return str(sec.get(key, default) or "").strip()
            except Exception:                                      # noqa: BLE001
                return default

        def _as_int(key, default):
            try:
                return int(float(_get(key, str(default))))
            except (TypeError, ValueError):
                return default

        def _as_float(key, default):
            try:
                return float(_get(key, str(default)))
            except (TypeError, ValueError):
                return default

        try:
            exe = _get("exe", "")
            if exe:
                self.edit_exe.setText(exe)
            self._set_combo_data(self.cmb_method, _get("method", "gfn2"))
            self._set_combo_data(self.cmb_job, _get("job", "opt"))
            self.spn_charge.setValue(_as_int("charge", 0))
            self.spn_uhf.setValue(_as_int("uhf", 0))
            self.spn_acc.setValue(_as_float("acc", 1.0))
            self.spn_etemp.setValue(_as_int("etemp", 300))
            model = _get("solvation", "gas")
            if self._set_combo_data(self.cmb_solvation, model):
                self._fill_solvent_combo(model)
            self._workdir_user_edited = False
            solvent = _get("solvent", "")
            if solvent:
                idx = self.cmb_solvent.findData(solvent)
                if idx < 0:
                    idx = self.cmb_solvent.findText(solvent)
                if idx >= 0:
                    self.cmb_solvent.setCurrentIndex(idx)
            cpus = max(1, int(os.cpu_count() or 4))
            self.spn_parallel.setValue(max(1, min(cpus, _as_int(
                "parallel", min(4, cpus)))))
            self.chk_json.setChecked(_get("json", "1") not in ("0", "false", "False"))
            self.chk_molden.setChecked(_get("molden", "0") in ("1", "true", "True"))
            self.chk_verbose.setChecked(_get("verbose", "0") in ("1", "true", "True"))
            self.edit_extra.setText(_get("extra_args", ""))
            saved_dir = _get("workdir", "")
            self._loaded_workdir = saved_dir
            self._workdir_base = saved_dir
            if saved_dir:
                self.edit_workdir.setText(saved_dir)
                self.edit_workdir.setCursorPosition(0)
        except Exception:                                          # noqa: BLE001
            pass
        finally:
            self._loading_settings = False

    def _save_settings(self):
        if getattr(self, "_loading_settings", False):
            return
        cfg = configparser.ConfigParser()
        if self._workdir_user_edited and self.edit_workdir.text().strip():
            workdir = self.edit_workdir.text().strip()
        else:
            workdir = (self._workdir_base
                       or self.edit_workdir.text().strip()
                       or self._last_workdir)
        cfg["xtb"] = {
            "exe": self.edit_exe.text().strip(),
            "method": str(self.cmb_method.currentData() or "gfn2"),
            "job": str(self.cmb_job.currentData() or "opt"),
            "charge": str(int(self.spn_charge.value())),
            "uhf": str(int(self.spn_uhf.value())),
            "acc": "%.3f" % float(self.spn_acc.value()),
            "etemp": str(int(self.spn_etemp.value())),
            "solvation": str(self.cmb_solvation.currentData() or "gas"),
            "solvent": str(self.cmb_solvent.currentData()
                           or self.cmb_solvent.currentText() or ""),
            "parallel": str(int(self.spn_parallel.value())),
            "json": "1" if self.chk_json.isChecked() else "0",
            "molden": "1" if self.chk_molden.isChecked() else "0",
            "verbose": "1" if self.chk_verbose.isChecked() else "0",
            "extra_args": self.edit_extra.text().strip(),
            "workdir": workdir,
        }
        try:
            with open(self._settings_path(), "w", encoding="utf-8") as fh:
                cfg.write(fh)
        except Exception:                                          # noqa: BLE001
            pass

    def closeEvent(self, event):                                   # noqa: N802
        self._save_settings()
        super().closeEvent(event)

    # ── xTB 路径 ─────────────────────────────────────────────────────
    def _auto_detect(self, initial=False):
        try:
            eng = _engine_module()
        except Exception as exc:                                  # noqa: BLE001
            if not initial:
                self._set_status_i18n("st_engine_error", "error", err=exc)
            return None
        current = self.edit_exe.text().strip()
        try:
            found = eng.find_xtb_executable(current)
        except Exception:                                          # noqa: BLE001
            found = None
        if found:
            self.edit_exe.setText(str(found))
            self.edit_exe.setCursorPosition(0)      # 长路径显示开头，而不是末尾
            if not initial:
                self._set_status_i18n("st_detected", "ok", path=str(found))
            return str(found)
        if not initial:
            self._set_status_i18n("st_detect_fail", "warn")
        return None

    def _detect_executable_clicked(self):
        if self._busy():
            return
        found = self._auto_detect(initial=False)
        if found:
            self._save_settings()

    def _browse_executable(self):
        start = str(Path(self.edit_exe.text().strip()).parent) \
            if self.edit_exe.text().strip() else ""
        path, _f = QFileDialog.getOpenFileName(
            self, self._t("dlg_exe"), start, self._t("filter_exe"))
        if path:
            self.edit_exe.setText(str(path))
            self._save_settings()

    # ── 计算设置联动 ─────────────────────────────────────────────────
    def _on_job_changed(self, *_args):
        self._sync_job_widgets()
        self._save_settings()

    def _on_method_changed(self, *_args):
        self._sync_gxtb_solvation()
        self._save_settings()

    def _on_solvation_changed(self, *_args):
        model = str(self.cmb_solvation.currentData() or "gas")
        self._fill_solvent_combo(model)
        self._sync_gxtb_solvation()
        self._save_settings()

    def _sync_job_widgets(self):
        job = str(self.cmb_job.currentData() or "opt")
        try:
            self.scan_box.setVisible(job == "scan")
            self.lbl_ts_hint.setVisible(job == "ts")
        except AttributeError:
            pass

    def _sync_gxtb_solvation(self):
        gxtb = str(self.cmb_method.currentData() or "") == "gxtb"
        solv = str(self.cmb_solvation.currentData() or "gas")
        self.lbl_gxtb_hint.setVisible(gxtb)
        self.cmb_solvation.setEnabled(not gxtb)
        self.cmb_solvent.setEnabled((not gxtb) and solv != "gas")

    # ── 参数 / 校验 ──────────────────────────────────────────────────
    def _params(self) -> dict:
        method = str(self.cmb_method.currentData() or "gfn2")
        job = str(self.cmb_job.currentData() or "opt")
        solvation = str(self.cmb_solvation.currentData() or "gas")
        solvent = str(self.cmb_solvent.currentData()
                      or self.cmb_solvent.currentText() or "")
        if method == "gxtb":
            # 引擎会忽略，面板也不把溶剂化传给 g-xTB（提示见 lbl_gxtb_hint）。
            solvation = "gas"
            solvent = ""
        xcontrol = self.txt_xcontrol.toPlainText() if job == "scan" else ""
        return {
            "xtb_exe": self.edit_exe.text().strip(),
            "method": method,
            "job": job,
            "charge": int(self.spn_charge.value()),
            "uhf": int(self.spn_uhf.value()),
            "acc": round(float(self.spn_acc.value()), 3),
            "etemp": int(self.spn_etemp.value()),
            "solvation": solvation,
            "solvent": solvent,
            "parallel": int(self.spn_parallel.value()),
            "json": bool(self.chk_json.isChecked()),
            "molden": bool(self.chk_molden.isChecked()),
            "verbose": bool(self.chk_verbose.isChecked()),
            "extra_args": self.edit_extra.text().strip(),
            "xcontrol": xcontrol,
            # 引擎 validate_params() 用 params["lang"] 决定预检查错误文案语言；
            # 其它参数不受影响（build_command/run_job 只读各自需要的键）。
            "lang": self.lang,
        }

    def _prepare_run_error(self):
        """运行前的本地检查；返回本地化错误或 None。"""
        if not self._symbols or self._coords is None:
            return self._t("st_no_struct")
        exe = self.edit_exe.text().strip()
        if not exe:
            return self._t("st_engine_missing")
        if not Path(exe).is_file():
            return self._t("st_engine_missing")
        try:
            eng = _engine_module()
        except Exception as exc:                                  # noqa: BLE001
            return self._t("st_engine_error", err=exc)
        params = self._params()
        try:
            err = eng.validate_params(params)
        except TypeError:
            err = eng.validate_params(params, None)
        except Exception as exc:                                  # noqa: BLE001
            return self._t("st_invalid", err=exc)
        if err:
            return self._t("st_invalid", err=err)
        return None

    def _default_workdir(self) -> Path:
        """默认工作目录的“基目录”（每次运行会在其下新建时间戳子目录）。"""
        if self._source_kind == "file" and self._source_path:
            src = Path(self._source_path)
            return src.parent / ("%s_xtb" % src.stem)
        return Path(tempfile.gettempdir()) / "MolStudio_xtb"

    def _resolve_workdir(self) -> Path:
        """本次运行的独立目录：``<基目录>/<时间戳>``（同一秒重跑再加后缀）。

        基目录 = 用户刚编辑/浏览指定的路径，或上次的基目录，或默认位置。
        每次运行都换新目录，避免同目录旧产物（频率 / 优化结构 / JSON）把
        上一次的结果混进本次（尤其是换分子、换方法重跑时）。
        """
        text = self.edit_workdir.text().strip()
        if self._workdir_user_edited and text:
            base = Path(text)
        elif self._workdir_base:
            base = Path(self._workdir_base)
        elif text and text != self._loaded_workdir:
            base = Path(text)
        else:
            base = self._default_workdir()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = base / stamp
        n = 1
        while run_dir.exists():
            run_dir = base / ("%s_%d" % (stamp, n))
            n += 1
        return run_dir

    # ── 运行 ─────────────────────────────────────────────────────────
    def start(self):
        if self._busy():
            return
        err = self._prepare_run_error()
        if err:
            msg = err
            self._set_status(msg, "error")
            self._log("  " + msg)
            if not self._symbols:
                self._set_status_i18n("st_no_struct", "warn")
            return

        params = self._params()
        workdir = self._resolve_workdir()
        self.edit_workdir.setText(str(workdir))
        self.edit_workdir.setCursorPosition(0)      # 显示路径开头
        self._workdir_base = str(Path(workdir).parent)
        self._loaded_workdir = str(workdir)
        self._last_workdir = str(workdir)
        self._workdir_user_edited = False

        if params["method"] == "gxtb" and str(
                self.cmb_solvation.currentData() or "gas") != "gas":
            self._log(self._t("log_warn", msg=self._t("hint_gxtb_solv")))

        self._log(self._t("log_header"))
        self._log(self._t(
            "log_start", n=len(self._symbols),
            method=self.cmb_method.currentText() or params["method"],
            job=self.cmb_job.currentText() or params["job"],
            dir=workdir))
        self._log(self._t("log_command",
                          cmd=self._command_text(params)))

        self._run_started = time.monotonic()
        self._run_phase_key = "phase_preparing"
        self._set_busy(True)
        self._set_status_i18n("st_phase", level="normal",
                              phase=self._t(self._run_phase_key), t=0.0)
        self._elapsed_timer.start()

        worker = XtbWorker(params, self._symbols, self._coords,
                           str(workdir), self.lang, parent=self)
        worker.line.connect(self._on_worker_line)
        worker.progress.connect(self._on_worker_progress)
        worker.done.connect(self._on_worker_done)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def _command_text(self, params) -> str:
        exe = str(params.get("xtb_exe") or self.edit_exe.text()).strip()
        try:
            eng = _engine_module()
            cmd = eng.build_command(exe, params, "input.xyz")
        except Exception:                                          # noqa: BLE001
            return "(?)"
        # Windows 命令行显示（与 subprocess.list2cmdline 一致）
        out = []
        for part in cmd:
            if part == "" or any(ch.isspace() for ch in part):
                out.append('"%s"' % part)
            else:
                out.append(str(part))
        return " ".join(out)

    def _preview_command(self):
        if self._busy():
            return
        if not self._symbols or self._coords is None:
            self._set_status_i18n("st_no_struct", "warn")
            return
        params = self._params()
        text = self._command_text(params)
        self._log(self._t("log_command", cmd=text))
        self._set_status_i18n("st_preview", "ok")

    def cancel(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self.btn_cancel.setEnabled(False)
            self._set_status_i18n("st_cancelling", "warn")
            self._log("  " + self._t("st_cancelling"))

    def shutdown(self):
        """主窗口退出时清理：停定时器、取消并等待线程、保存设置。"""
        try:
            self._elapsed_timer.stop()
        except Exception:                                          # noqa: BLE001
            pass
        try:
            self._save_settings()
        except Exception:                                          # noqa: BLE001
            pass
        worker = self._worker
        if worker is not None and worker.isRunning():
            try:
                worker.cancel()
                worker.wait(5000)
            except Exception:                                      # noqa: BLE001
                pass
        self._worker = None

    # ── worker 回调（主线程）─────────────────────────────────────────
    def _on_worker_line(self, text):
        self._log(str(text).rstrip("\r\n"))

    def _on_worker_progress(self, step, text):
        step = str(step or "")
        key = "phase_" + step
        if key in _TR["zh"]:
            self._run_phase_key = key
        self._tick_elapsed()

    def _tick_elapsed(self):
        if not self._busy():
            return
        elapsed = max(0.0, time.monotonic() - self._run_started)
        self._set_status_i18n("st_phase", level="normal",
                              phase=self._t(self._run_phase_key), t=elapsed)

    def _on_worker_done(self, payload):
        self._elapsed_timer.stop()
        worker = self._worker
        self._worker = None
        # done 是 run() 末尾发出的：等线程真正退出再丢引用，避免 Qt 在析构时
        # 报「QThread: Destroyed while thread is still running」。
        if worker is not None:
            try:
                worker.wait(3000)
            except Exception:                                  # noqa: BLE001
                pass
        self._set_busy(False)
        elapsed = float(payload.get("elapsed") or
                        max(0.0, time.monotonic() - self._run_started))

        if payload.get("cancelled"):
            # 取消不清空上一次成功结果：结果区展示/导出的仍是它，这是合理交互；
            # 只把状态标成“已取消”，提醒用户本次任务没有算完。
            self._set_status_i18n("st_cancelled", "warn", t=elapsed)
            self._log("  " + self._t("log_cancel"))
            self.btn_run.setEnabled(True)
            return
        if not payload.get("ok"):
            err = str(payload.get("error") or "?")
            self._clear_result()
            self._set_status_i18n("st_failed", "error", err=err)
            self._log("  " + self._t("log_fail", err=err))
            if payload.get("traceback"):
                self._log(payload["traceback"])
            return

        result = payload.get("result")
        if result is None:
            self._clear_result()
            self._set_status_i18n("st_failed", "error", err="?")
            return
        if getattr(result, "cancelled", False):
            self._clear_result()
            self._set_status_i18n("st_cancelled", "warn", t=elapsed)
            self._log("  " + self._t("log_cancel"))
            return
        if not getattr(result, "success", False):
            # xTB 返回码非 0（参数文件缺失、溶剂/方法不兼容、语法错误等）：
            # 不能显示成绿色「完成」，也不允许导出/送回画布，避免拿错数据。
            reason = self._failure_reason(result)
            self._clear_result()
            self._set_status_i18n("st_failed", "error", err=reason)
            self._log("  " + self._t("log_fail", err=reason))
            for warning in (getattr(result, "warnings", None) or []):
                self._log("  " + self._t("log_warn", msg=str(warning)))
            return
        self._display_result(result)
        energy = getattr(result, "energy", None)
        energy = getattr(result, "electronic_energy", None) if energy is None else energy
        self._set_status_i18n(
            "st_done", "ok", e=self._fmt(energy, ".6f"), t=elapsed)
        gap = getattr(result, "gap", None)
        self._log(self._t(
            "log_done", e=self._fmt(energy, ".6f"), g=self._fmt(gap, ".2f"),
            t=elapsed))
        for warning in (getattr(result, "warnings", None) or []):
            self._log("  " + self._t("log_warn", msg=str(warning)))

    def _set_busy(self, busy):
        busy = bool(busy)
        for widget in self._param_widgets:
            widget.setEnabled(not busy)
        self.btn_run.setEnabled(not busy)
        self.btn_cancel.setEnabled(busy)
        self.btn_preview.setEnabled(not busy)
        self.btn_refresh.setEnabled(not busy)
        self.btn_open.setEnabled(not busy)
        if busy:
            self._set_export_enabled(False)
        else:
            self._set_export_enabled(self._result is not None)
            self._sync_gxtb_solvation()
            self._sync_job_widgets()

    # ── 结果显示 ─────────────────────────────────────────────────────
    @staticmethod
    def _fmt(value, spec=".6f"):
        if value is None:
            return "—"
        try:
            return format(float(value), spec)
        except (TypeError, ValueError):
            return "—"

    def _grad_text(self, value):
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if abs(number) < 1.0e-3:
            return "%.2e" % number
        return "%.6f" % number

    def _display_result(self, result):
        self._result = result
        self._update_result_labels()
        self._fill_charges(result)
        self._set_export_enabled(True)
        if getattr(result, "scan", None):
            self._render_scan(result)
        else:
            self._hide_scan()

    def _failure_reason(self, result) -> str:
        """从失败结果里挑一条最能说明原因的文字（状态行/日志用）。"""
        warnings = [str(w).strip() for w in
                    (getattr(result, "warnings", None) or []) if str(w).strip()]
        if warnings:
            return "；".join(warnings[:3])
        text = str(getattr(result, "output_text", "") or "")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for line in reversed(lines):
            upper = line.upper()
            if line.startswith("[ERROR]") or "ERROR" in upper:
                return line[:300]
        if lines:
            return lines[-1][:300]
        return "rc=%s" % getattr(result, "returncode", "?")

    def _update_result_labels(self):
        res = self._result
        if res is None:
            self.lbl_energy.setText(self._t("energy_none"))
            for lab in (self.lbl_gap, self.lbl_homo, self.lbl_lumo,
                        self.lbl_dipole, self.lbl_grad):
                lab.setText("")
            self.lbl_vib.setText("")
            self.lbl_vib.setVisible(False)
            self.lbl_thermo.setText("")
            self.lbl_thermo.setVisible(False)
            return

        energy = getattr(res, "energy", None)
        if energy is None:
            energy = getattr(res, "electronic_energy", None)
        if energy is None:
            self.lbl_energy.setText(self._t("energy_none"))
        else:
            self.lbl_energy.setText(self._t("energy_fmt",
                                            e=self._fmt(energy, ".6f")))
        self.lbl_gap.setText(self._t("gap_fmt", v=self._fmt(
            getattr(res, "gap", None), ".2f")))
        self.lbl_homo.setText(self._t("homo_fmt", v=self._fmt(
            getattr(res, "homo", None), ".2f")))
        self.lbl_lumo.setText(self._t("lumo_fmt", v=self._fmt(
            getattr(res, "lumo", None), ".2f")))
        self.lbl_dipole.setText(self._t("dipole_fmt", v=self._fmt(
            getattr(res, "dipole_debye", None), ".2f")))
        grad = self._grad_text(getattr(res, "gradient_norm", None))
        self.lbl_grad.setText(
            self._t("grad_fmt", v=grad) if grad is not None else "")

        # 频率 / 热化学
        freqs = list(getattr(res, "frequencies", None) or [])
        imag = getattr(res, "imaginary_count", None)
        thermo = getattr(res, "thermo", None) or {}
        vib_parts = []
        if imag is not None:
            vib_parts.append(self._t("vib_imag_fmt", n=int(imag)))
        if freqs:
            values = []
            for item in freqs:
                try:
                    if isinstance(item, dict):
                        values.append(float(item.get("frequency")))
                    else:
                        values.append(float(item))
                except (TypeError, ValueError):
                    continue
            values = sorted(values)
            # xTB 会把平动/转动近零模也列出来；显示真正的振动模，避免「-0.00」。
            nonzero = [v for v in values if abs(v) >= 1.0]
            if nonzero:
                values = nonzero
            if values:
                text = ", ".join("%.2f" % v for v in values[:3])
                vib_parts.append(self._t("vib_lowest_fmt", vals=text))
        self.lbl_vib.setText("    ".join(vib_parts))
        self.lbl_vib.setVisible(bool(vib_parts))

        thermo_bits = []
        for key, spec in (("free_energy", ".6f"), ("enthalpy", ".6f"),
                          ("zpe", ".6f")):
            if thermo and thermo.get(key) is not None:
                thermo_bits.append(self._fmt(thermo.get(key), spec))
            else:
                thermo_bits.append("—")
        has_thermo = bool(thermo) and any(
            thermo.get(k) is not None
            for k in ("free_energy", "enthalpy", "zpe"))
        if has_thermo:
            self.lbl_thermo.setText(self._t(
                "thermo_fmt", g=thermo_bits[0], h=thermo_bits[1],
                z=thermo_bits[2]))
        else:
            self.lbl_thermo.setText("")
        self.lbl_thermo.setVisible(has_thermo)

    def _fill_charges(self, res):
        charges = list(getattr(res, "charges", None) or []) if res else []
        symbols = list(getattr(res, "symbols", None) or []) if res else []
        if not symbols:
            symbols = list(self._symbols)
        if res is None:
            self.tbl_charges.setRowCount(0)
            return
        rows = max(len(symbols), len(charges))
        self.tbl_charges.setRowCount(rows)
        for row in range(rows):
            sym = symbols[row] if row < len(symbols) else ""
            charge = charges[row] if row < len(charges) else None
            idx_item = QTableWidgetItem(str(row + 1))
            idx_item.setTextAlignment(Qt.AlignCenter)
            sym_item = QTableWidgetItem(str(sym))
            sym_item.setTextAlignment(Qt.AlignCenter)
            chg_item = QTableWidgetItem(
                "%.6f" % float(charge) if charge is not None else "")
            chg_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl_charges.setItem(row, 0, idx_item)
            self.tbl_charges.setItem(row, 1, sym_item)
            self.tbl_charges.setItem(row, 2, chg_item)

    def _set_export_enabled(self, enabled):
        has = bool(enabled) and self._result is not None
        for button in (self.btn_export_xyz, self.btn_export_gjf,
                       self.btn_export_json, self.btn_open_workdir):
            button.setEnabled(has)
        optimized = has and getattr(self._result, "optimized_coords", None) is not None
        self.btn_to_canvas.setEnabled(bool(optimized))
        scan = has and bool(getattr(self._result, "scan", None))
        self.btn_export_scan.setEnabled(bool(scan))
        if not has:
            self.btn_to_canvas.setEnabled(False)

    # ── 扫描结果 ─────────────────────────────────────────────────────
    def _hide_scan(self):
        self._scan_ev = []
        self.lbl_scan_summary.setText("")
        try:
            self.grp_scan.setVisible(False)
        except AttributeError:
            pass

    def _render_scan(self, res):
        frames = list(getattr(res, "scan", None) or [])
        if not frames:
            self._hide_scan()
            return
        energies, relatives = [], []
        for frame in frames:
            getter = (frame.get if isinstance(frame, dict)
                      else lambda k, f=frame: getattr(f, k, None))
            try:
                energies.append(float(getter("energy")))
            except (TypeError, ValueError):
                energies.append(None)
            try:
                relatives.append(float(getter("energy_relative")))
            except (TypeError, ValueError):
                relatives.append(None)
        if all(value is not None for value in relatives):
            values = [value * HARTREE_TO_EV for value in relatives]
        elif all(value is not None for value in energies):
            base = min(energies)
            values = [(value - base) * HARTREE_TO_EV for value in energies]
        else:
            values = [float(i) for i in range(len(frames))]
        self._scan_ev = values
        steps = list(range(1, len(values) + 1))
        span = (max(values) - min(values)) if len(values) > 1 else 0.0
        self.lbl_scan_summary.setText(
            self._t("scan_summary", n=len(values), de="%.3f" % span))

        fig = self.scan_figure
        try:
            fig.clear()
            ax = fig.add_subplot(111)
            ax.plot(steps, values, marker="o", markersize=3.0, linewidth=1.2,
                    color="#1f5fa8")
            ax.set_xlabel(self._t("scan_x"), fontsize=9)
            ax.set_ylabel(self._t("scan_y"), fontsize=9)
            ax.tick_params(labelsize=8)
            ax.grid(True, alpha=0.3, linewidth=0.5)
            try:
                fig.tight_layout()
            except Exception:                                      # noqa: BLE001
                pass
            self.scan_canvas.draw_idle()
        except Exception:                                          # noqa: BLE001
            pass
        self.grp_scan.setVisible(True)

    def _scan_frames(self):
        res = self._result
        if res is None:
            return []
        return list(getattr(res, "scan", None) or [])

    def _export_scan_traj(self):
        frames = self._scan_frames()
        if not frames:
            self._set_status_i18n("st_no_result", "warn")
            return
        default = self._default_export_path("scan_traj.xyz")
        path, _f = QFileDialog.getSaveFileName(
            self, self._t("dlg_save_scan"), default, self._t("filter_xyz"))
        if not path:
            return
        try:
            lines = []
            for index, frame in enumerate(frames, start=1):
                getter = (frame.get if isinstance(frame, dict)
                          else lambda k, f=frame: getattr(f, k, None))
                symbols = list(getter("symbols") or self._symbols)
                coords = getter("coords")
                if coords is None:
                    coords = getter("positions")
                coords = np.asarray(coords, dtype=float)
                energy = getter("energy")
                comment = "frame %d" % index
                if energy is not None:
                    comment += " energy=%.8f" % float(energy)
                lines.append(str(len(symbols)))
                lines.append(comment)
                for sym, xyz in zip(symbols, coords):
                    lines.append("%-3s %14.8f %14.8f %14.8f"
                                 % (str(sym), xyz[0], xyz[1], xyz[2]))
            Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception as exc:                                  # noqa: BLE001
            msg = self._t("st_export_fail", err=exc)
            self._set_status(msg, "error")
            self._log("  " + msg)
            return
        self._set_status_i18n("st_saved", "ok", path=str(path))
        self._log(self._t("st_scan_saved", n=len(frames)))

    # ── 导出 / 回画布 ───────────────────────────────────────────────
    def _export_structure(self):
        res = self._result
        if res is None:
            return None
        symbols = list(getattr(res, "optimized_symbols", None) or [])
        coords = getattr(res, "optimized_coords", None)
        if symbols and coords is not None:
            return symbols, np.asarray(coords, dtype=float)
        symbols = list(getattr(res, "symbols", None) or self._symbols)
        coords = getattr(res, "input_coords", None)
        if coords is None:
            coords = self._coords
        if coords is None:
            return None
        return symbols, np.asarray(coords, dtype=float)

    def _default_export_path(self, filename):
        res = self._result
        workdir = (getattr(res, "workdir", "") if res is not None else "") \
            or self.edit_workdir.text().strip()
        if workdir and Path(workdir).is_dir():
            return str(Path(workdir) / filename)
        return str(Path(self._default_dir()) / filename)

    def _export_xyz(self):
        data = self._export_structure()
        if data is None:
            self._set_status_i18n("st_no_result", "warn")
            return
        symbols, coords = data
        default = self._default_export_path("%s.xyz" % self._export_stem())
        path, _f = QFileDialog.getSaveFileName(
            self, self._t("dlg_save_xyz"), default, self._t("filter_xyz"))
        if not path:
            return
        try:
            lines = [str(len(symbols)), "MolStudio xTB %s" % self._job_tag()]
            for sym, xyz in zip(symbols, coords):
                lines.append("%-3s %14.8f %14.8f %14.8f"
                             % (str(sym), xyz[0], xyz[1], xyz[2]))
            Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception as exc:                                  # noqa: BLE001
            msg = self._t("st_export_fail", err=exc)
            self._set_status(msg, "error")
            self._log("  " + msg)
            return
        self._set_status_i18n("st_saved", "ok", path=str(path))
        self._log(self._t("st_saved", path=str(path)))

    def _export_gjf(self):
        data = self._export_structure()
        if data is None:
            self._set_status_i18n("st_no_result", "warn")
            return
        symbols, coords = data
        default = self._default_export_path("%s.gjf" % self._export_stem())
        path, _f = QFileDialog.getSaveFileName(
            self, self._t("dlg_save_gjf"), default, self._t("filter_gjf"))
        if not path:
            return
        charge = int(self.spn_charge.value())
        mult = max(1, int(self.spn_uhf.value()) + 1)
        routed = False
        try:
            eng = _engine_module()
            eng.write_gjf(path, symbols, coords, charge=charge, mult=mult)
            routed = Path(path).exists()
        except Exception:                                          # noqa: BLE001
            routed = False
        if not routed:
            try:
                self._write_gjf_fallback(path, symbols, coords, charge, mult)
            except Exception as exc:                              # noqa: BLE001
                msg = self._t("st_export_fail", err=exc)
                self._set_status(msg, "error")
                self._log("  " + msg)
                return
        self._set_status_i18n("st_saved", "ok", path=str(path))
        self._log(self._t("st_saved", path=str(path)))

    def _write_gjf_fallback(self, path, symbols, coords, charge, mult):
        lines = ["# MolStudio xTB export",
                 "# %s" % self._job_tag(),
                 "",
                 "%d %d" % (int(charge), int(mult))]
        for sym, xyz in zip(symbols, coords):
            lines.append("%-3s %14.8f %14.8f %14.8f"
                         % (str(sym), xyz[0], xyz[1], xyz[2]))
        lines.append("")
        Path(path).write_text("\n".join(lines), encoding="utf-8")

    def _result_json_dict(self):
        res = self._result
        if res is None:
            return {}
        data = self._export_structure()
        symbols, coords = (data if data is not None
                           else (list(getattr(res, "symbols", []) or []), None))

        def _plain(value):
            if isinstance(value, np.ndarray):
                return value.tolist()
            if isinstance(value, (np.floating, np.integer)):
                return value.item()
            if isinstance(value, dict):
                return {str(k): _plain(v) for k, v in value.items()}
            if isinstance(value, (list, tuple)):
                return [_plain(v) for v in value]
            return value

        payload = {
            "program": "xTB",
            "method": getattr(res, "method", ""),
            "method_label": getattr(res, "method_label", ""),
            "job": getattr(res, "job", ""),
            "job_label": getattr(res, "job_label", ""),
            "symbols": list(symbols),
            "coords": coords.tolist() if coords is not None else None,
            "energy": getattr(res, "energy", None),
            "electronic_energy": getattr(res, "electronic_energy", None),
            "gap": getattr(res, "gap", None),
            "homo": getattr(res, "homo", None),
            "lumo": getattr(res, "lumo", None),
            "dipole_debye": getattr(res, "dipole_debye", None),
            "gradient_norm": getattr(res, "gradient_norm", None),
            "formula": getattr(res, "formula", ""),
            "charges": getattr(res, "charges", None),
            "orbital_energies": getattr(res, "orbital_energies", None),
            "occupations": getattr(res, "occupations", None),
            "frequencies": getattr(res, "frequencies", None),
            "imaginary_count": getattr(res, "imaginary_count", None),
            "thermo": getattr(res, "thermo", None),
            "scan": getattr(res, "scan", None),
            "params": getattr(res, "params", None),
            "command": getattr(res, "command", None),
            "workdir": getattr(res, "workdir", ""),
            "returncode": getattr(res, "returncode", None),
            "success": getattr(res, "success", None),
            "cancelled": getattr(res, "cancelled", None),
            "normal_termination": getattr(res, "normal_termination", None),
            "elapsed": getattr(res, "elapsed", None),
            "warnings": getattr(res, "warnings", None),
            "output_text": getattr(res, "output_text", None),
        }
        return _plain(payload)

    def _export_json(self):
        if self._result is None:
            self._set_status_i18n("st_no_result", "warn")
            return
        default = self._default_export_path("%s.json" % self._export_stem())
        path, _f = QFileDialog.getSaveFileName(
            self, self._t("dlg_save_json"), default, self._t("filter_json"))
        if not path:
            return
        try:
            Path(path).write_text(
                json.dumps(self._result_json_dict(), ensure_ascii=False,
                           indent=2),
                encoding="utf-8")
        except Exception as exc:                                  # noqa: BLE001
            msg = self._t("st_export_fail", err=exc)
            self._set_status(msg, "error")
            self._log("  " + msg)
            return
        self._set_status_i18n("st_saved", "ok", path=str(path))
        self._log(self._t("st_saved", path=str(path)))

    def _export_stem(self):
        res = self._result
        formula = str(getattr(res, "formula", "") or "").strip()
        if formula:
            safe = "".join(ch for ch in formula if ch.isalnum())
            if safe:
                return safe + "_xtb"
        return "xtb_structure"

    def _job_tag(self):
        res = self._result
        method = str(getattr(res, "method", "") or "")
        job = str(getattr(res, "job", "") or "")
        energy = getattr(res, "energy", None)
        if energy is None:
            energy = getattr(res, "electronic_energy", None)
        tag = " ".join(part for part in (method, job) if part) or "xTB"
        if energy is not None:
            tag += " E=%.6f Eh" % float(energy)
        return tag

    def _send_to_canvas(self):
        res = self._result
        if res is None:
            self._set_status_i18n("st_no_result", "warn")
            return
        coords = getattr(res, "optimized_coords", None)
        symbols = list(getattr(res, "optimized_symbols", None) or [])
        if coords is None:
            self._set_status_i18n("st_need_optimized", "warn")
            return
        if not symbols:
            symbols = list(getattr(res, "symbols", None) or self._symbols)
        coords = np.asarray(coords, dtype=float)
        label = "xTB %s" % (str(getattr(res, "job_label", "")
                                or getattr(res, "job", "")) or "")
        if self._on_structure_loaded is None:
            self._set_status(self._t("st_sent_canvas", n=len(symbols)), "ok")
            return
        try:
            self._on_structure_loaded(symbols, coords, label.strip())
        except Exception as exc:                                  # noqa: BLE001
            msg = self._t("st_export_fail", err=exc)
            self._set_status(msg, "error")
            self._log("  " + msg)
            return
        self._set_status_i18n("st_sent_canvas", "ok", n=len(symbols))
        self._log(self._t("st_sent_canvas", n=len(symbols)))

    # ── 工作目录 ─────────────────────────────────────────────────────
    def _browse_workdir(self):
        start = self.edit_workdir.text().strip() or str(self._default_dir())
        path = QFileDialog.getExistingDirectory(
            self, self._t("dlg_workdir"), start)
        if path:
            self.edit_workdir.setText(str(path))
            self._workdir_user_edited = True
            self._save_settings()

    def _open_workdir(self):
        res = self._result
        path = ""
        if res is not None:
            path = str(getattr(res, "workdir", "") or "")
        if not path:
            path = self.edit_workdir.text().strip()
        if not path or not Path(path).is_dir():
            self._set_status_i18n("st_workdir_missing", "warn", path=path or "—")
            return
        try:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        except Exception:                                          # noqa: BLE001
            pass
