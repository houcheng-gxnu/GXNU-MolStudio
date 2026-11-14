# -*- coding: utf-8 -*-
"""di_local_dialog.py — DI 本机一键计算弹窗
================================================

把「载入过渡态 → Shift+左键框选分片段 → 生成 4 个 Gaussian 输入 → 本机一键
跑完」整套流程收进一个弹出窗口：主 DI 页面只保留结果图/表/导出与一个入口按钮，
不再占用页面的绘图空间。

流程（与 ``molstudio/core/di_local.py`` 一致）：
  1. 载入过渡态复合物的 Gaussian ``.log``（推荐，可读取 route 参数）或 ``.fchk``；
  2. 内嵌结构画布上 **Shift+左键拖框**把原子分到片段 1/2（点原子可单独切换，
     也可按成键连通性自动识别），原子颜色随归属实时变化；
  3. 按 TS log 的 route 参数生成 4 个输入：片段 1/2 在 TS 几何下的单点（def）
     + 片段 1/2 的结构优化（opt）；
  4. 调用本机 g16 顺序跑完，窗口内显示里程碑日志与进度；
  5. 关闭窗口后主 DI 页自动载入 5 个 log 计算 ΔE_strain / ΔE_int / ΔE‡ 并出图。
"""

import os
import re

from PyQt5.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QLineEdit, QPushButton, QGroupBox, QFrame, QSizePolicy, QProgressBar,
    QMessageBox, QTextEdit,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont

from molstudio.ui.file_dialogs import open_file, existing_directory
from molstudio.core import di_local
from molstudio.core.gaussian_run import find_gaussian
from molstudio.panels.etsnocv.molcanvas import MolCanvas


class _DiMolCanvas(MolCanvas):
    """弹窗用的结构画布：自动缩放留白小一点，结构在卡片里更清楚。"""

    _ZOOM_BOOST = 1.35

    def auto_fit(self):
        super().auto_fit()
        self.scale *= self._ZOOM_BOOST


class DiLocalWorker(QThread):
    """后台跑 4 个 DI 任务：片段 1/2 单点 + 片段 1/2 优化。"""

    log = pyqtSignal(str)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, jobs, g16_exe, parent=None):
        super().__init__(parent)
        self.jobs = jobs
        self.g16_exe = g16_exe
        self._cancel_requested = False

    def request_cancel(self):
        self._cancel_requested = True

    def is_cancel_requested(self):
        return self._cancel_requested

    def run(self):
        try:
            result = di_local.run_di_jobs(
                self.jobs, self.g16_exe,
                on_log=self.log.emit,
                cancel=self.is_cancel_requested)
            self.completed.emit(result)
        except di_local.DiLocalCancelled as exc:
            self.failed.emit(str(exc))
        except Exception as exc:                        # noqa: BLE001
            self.failed.emit(str(exc))


def fchk_charge_multiplicity(fchk_path):
    """从 fchk 读取电荷/多重度（只用于预填片段输入，失败返回 None）。"""
    try:
        with open(fchk_path, "r", encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
    except OSError:
        return None
    m_c = re.search(r"^Charge\s+I\s+(-?\d+)", text, re.MULTILINE)
    m_m = re.search(r"^Multiplicity\s+I\s+(-?\d+)", text, re.MULTILINE)
    if m_c and m_m:
        return int(m_c.group(1)), int(m_m.group(1))
    return None


#: 弹窗自身独有的中英对照（与 DI 面板共用的条目从面板表里合并）
_DIALOG_LANG_EXTRA = {
    "DI 本机一键计算": "DI local workflow",
    "运行日志": "Run log",
    "关闭": "Close",
    "关闭并出图": "Close & plot",
    "载入过渡态并分片段，生成 4 个 Gaussian 输入后一键运行":
        "Load the TS, split atoms into fragments, generate four Gaussian "
        "inputs and run them in one click",
    "这些设置只影响本机生成的 4 个片段输入（方法与基组等取自 TS route）":
        "These settings only affect the four fragment inputs; method/basis "
        "and other keywords are taken from the TS route",
    "就绪": "Ready",
    "载入中…": "Loading…",
    "已生成 4 个输入文件": "Generated 4 input files",
    "本机计算中…": "Running locally…",
    "完成：已载入 5 个 log": "Done: 5 logs loaded",
    "已停止": "Stopped",
    "计算失败": "Failed",
    "请先载入过渡态复合物。": "Load the transition-state complex first.",
    "自动识别": "Auto-detect",
    "按成键连通性自动分成两个片段":
        "Split into two fragments from bond connectivity",
    "已载入过渡态": "TS loaded",
    "尚未载入过渡态": "No TS loaded yet",
    "片段 1：0 原子　|　片段 2：0 原子":
        "Fragment 1: 0 atoms  |  Fragment 2: 0 atoms",
    "片段 1 电荷 / 多重度:": "Fragment 1 charge / mult.:",
    "片段 2 电荷 / 多重度:": "Fragment 2 charge / mult.:",
    "片段 1 的电荷（整数，可为负）":
        "Charge of Fragment 1 (integer, may be negative)",
    "片段 1 的多重度（≥ 1）": "Multiplicity of Fragment 1 (>= 1)",
    "片段 2 的电荷（整数，可为负）":
        "Charge of Fragment 2 (integer, may be negative)",
    "片段 2 的多重度（≥ 1）": "Multiplicity of Fragment 2 (>= 1)",
}


def _translation_map():
    """面板共用条目 + 弹窗专有条目（延迟导入避免循环依赖）。"""
    merged = dict(_DIALOG_LANG_EXTRA)
    try:
        from molstudio.panels.di_analysis_panel import _LANG_EXTRA as panel_map
        merged.update(panel_map)
    except Exception:                                   # noqa: BLE001
        pass
    return merged


class DiLocalDialog(QDialog):
    """DI 本机一键计算弹窗（模态）。"""

    def __init__(self, parent=None, get_g16=None, log_func=None,
                 initial=None, lang="zh"):
        super().__init__(parent)
        self.lang = "zh" if lang == "zh" else "en"
        self._get_g16 = get_g16 if callable(get_g16) else (lambda: "")
        self._log_cb = log_func if callable(log_func) else None
        initial = dict(initial or {})

        self._ts_path = ""
        self._ts_atoms = []
        self._ts_bonds = []
        self._ts_route = ""
        self._frag1 = set()
        self._frag2 = set()
        self._target_frag = 1
        self._worker = None
        self._last_jobs = []
        self._done = False
        self._status_key = ("status", "ready")

        self.setWindowTitle("DI 本机一键计算")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumSize(940, 660)
        self.resize(1100, 760)

        self._build_ui()
        self._apply_initial(initial)
        self._sync_fragment_ui()
        self._refresh_dynamic_labels()
        self._apply_lang()

        ts = self.edit_ts.text().strip()
        if ts and os.path.exists(ts):
            try:
                self._load_ts_from_path(ts)
            except Exception:                           # noqa: BLE001
                pass

    # ── UI ──
    @staticmethod
    def _card(object_name):
        card = QFrame()
        card.setObjectName(object_name)
        card.setStyleSheet(
            "QFrame#%s{background:#FFFFFF;border:1px solid #D5DEE9;"
            "border-radius:10px;}" % object_name)
        return card

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        hint = QLabel("载入过渡态并分片段，生成 4 个 Gaussian 输入后一键运行")
        hint.setStyleSheet("color:#64748B;font-size:9pt;")
        outer.addWidget(hint)

        body = QHBoxLayout()
        body.setSpacing(8)

        # ── 左：载入 TS / 结构分片段 / 片段设置 ──
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(8)

        grp_ts = QGroupBox("1  载入过渡态复合物（.log / .fchk）")
        ts_l = QGridLayout(grp_ts)
        ts_l.setContentsMargins(9, 10, 9, 8)
        ts_l.setHorizontalSpacing(6)
        ts_l.setVerticalSpacing(4)
        self.edit_ts = QLineEdit()
        self.edit_ts.setPlaceholderText(
            "选择过渡态复合物的 Gaussian .log（推荐，可读取方法/基组）或 .fchk")
        self.edit_ts.returnPressed.connect(
            lambda: self._load_ts_from_path(self.edit_ts.text()))
        ts_l.addWidget(self.edit_ts, 0, 0, 1, 2)
        self.btn_ts_browse = QPushButton("浏览")
        self.btn_ts_browse.clicked.connect(self._browse_ts)
        ts_l.addWidget(self.btn_ts_browse, 0, 2)
        self.btn_ts_load = QPushButton("载入")
        self.btn_ts_load.clicked.connect(
            lambda: self._load_ts_from_path(self.edit_ts.text()))
        ts_l.addWidget(self.btn_ts_load, 0, 3)
        self.lbl_ts_info = QLabel("尚未载入过渡态")
        self.lbl_ts_info.setStyleSheet("color:#64748B;font-size:9pt;")
        ts_l.addWidget(self.lbl_ts_info, 1, 0, 1, 4)
        lv.addWidget(grp_ts)

        struct_card = self._card("DiStructCard")
        struct_card.setMinimumHeight(260)
        st_l = QVBoxLayout(struct_card)
        st_l.setContentsMargins(8, 6, 8, 6)
        st_l.setSpacing(3)
        head = QHBoxLayout()
        head.setSpacing(6)
        self.lbl_struct_title = QLabel("结构与分片段")
        self.lbl_struct_title.setStyleSheet(
            "font-size:12px;font-weight:700;color:#0D47A1;")
        head.addWidget(self.lbl_struct_title)
        self.lbl_frag_counts = QLabel("片段 1：0 原子　|　片段 2：0 原子")
        self.lbl_frag_counts.setStyleSheet("color:#64748B;font-size:9pt;")
        head.addWidget(self.lbl_frag_counts, 1)
        self.btn_frag1 = QPushButton("片段 1")
        self.btn_frag1.setCheckable(True)
        self.btn_frag1.setChecked(True)
        self.btn_frag1.setToolTip("框选/点选的原子归入片段 1")
        self.btn_frag1.clicked.connect(lambda: self._set_target(1))
        self.btn_frag2 = QPushButton("片段 2")
        self.btn_frag2.setCheckable(True)
        self.btn_frag2.setToolTip("框选/点选的原子归入片段 2")
        self.btn_frag2.clicked.connect(lambda: self._set_target(2))
        self.btn_frag_auto = QPushButton("自动识别")
        self.btn_frag_auto.setToolTip("按成键连通性自动分成两个片段")
        self.btn_frag_auto.clicked.connect(self._auto_fragments)
        self.btn_frag_clear = QPushButton("清空")
        self.btn_frag_clear.setToolTip("清空两个片段的原子归属")
        self.btn_frag_clear.clicked.connect(self._clear_fragments)
        head.addWidget(self.btn_frag1)
        head.addWidget(self.btn_frag2)
        head.addWidget(self.btn_frag_auto)
        head.addWidget(self.btn_frag_clear)
        st_l.addLayout(head)

        self.mol_canvas = _DiMolCanvas()
        self.mol_canvas.setMinimumSize(320, 200)
        self.mol_canvas.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.mol_canvas.box_selected.connect(self._on_canvas_box_select)
        self.mol_canvas.atom_clicked.connect(self._on_canvas_atom_click)
        st_l.addWidget(self.mol_canvas, 1)
        hint_frag = QLabel(
            "左键点原子可单独切换归属；框选默认并入当前激活片段"
            "（片段 1 / 片段 2 按钮）。")
        hint_frag.setWordWrap(True)
        hint_frag.setStyleSheet("color:#64748B;font-size:9pt;")
        st_l.addWidget(hint_frag)
        lv.addWidget(struct_card, 1)

        grp_frag = QGroupBox("2  分片段（画布 Shift+左键拖框选中原子）")
        fg = QGridLayout(grp_frag)
        fg.setContentsMargins(9, 10, 9, 8)
        fg.setHorizontalSpacing(6)
        fg.setVerticalSpacing(4)
        fg.addWidget(QLabel("片段 1 原子:"), 0, 0)
        self.edit_frag1 = QLineEdit()
        self.edit_frag1.setPlaceholderText("如 1-7,14-16")
        self.edit_frag1.editingFinished.connect(self._apply_frag_edits)
        fg.addWidget(self.edit_frag1, 0, 1, 1, 3)
        fg.addWidget(QLabel("片段 2 原子:"), 1, 0)
        self.edit_frag2 = QLineEdit()
        self.edit_frag2.setPlaceholderText("如 8-13")
        self.edit_frag2.editingFinished.connect(self._apply_frag_edits)
        fg.addWidget(self.edit_frag2, 1, 1, 1, 3)
        fg.addWidget(QLabel("片段 1 电荷 / 多重度:"), 2, 0)
        self.edit_frag1_charge = QLineEdit("0")
        self.edit_frag1_charge.setMaximumWidth(46)
        self.edit_frag1_charge.setToolTip("片段 1 的电荷（整数，可为负）")
        fg.addWidget(self.edit_frag1_charge, 2, 1)
        self.edit_frag1_mult = QLineEdit("1")
        self.edit_frag1_mult.setMaximumWidth(46)
        self.edit_frag1_mult.setToolTip("片段 1 的多重度（≥ 1）")
        fg.addWidget(self.edit_frag1_mult, 2, 2)
        fg.addWidget(QLabel("片段 2 电荷 / 多重度:"), 3, 0)
        self.edit_frag2_charge = QLineEdit("0")
        self.edit_frag2_charge.setMaximumWidth(46)
        self.edit_frag2_charge.setToolTip("片段 2 的电荷（整数，可为负）")
        fg.addWidget(self.edit_frag2_charge, 3, 1)
        self.edit_frag2_mult = QLineEdit("1")
        self.edit_frag2_mult.setMaximumWidth(46)
        self.edit_frag2_mult.setToolTip("片段 2 的多重度（≥ 1）")
        fg.addWidget(self.edit_frag2_mult, 3, 2)
        fg.setColumnStretch(1, 1)
        lv.addWidget(grp_frag)
        body.addWidget(left, 3)

        # ── 右：输出设置 / 运行日志 / 进度 ──
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(8)

        grp_run = QGroupBox("3  本机计算（2 个单点 + 2 个优化）")
        rg = QGridLayout(grp_run)
        rg.setContentsMargins(9, 10, 9, 8)
        rg.setHorizontalSpacing(6)
        rg.setVerticalSpacing(4)
        rg.addWidget(QLabel("输出目录:"), 0, 0)
        self.edit_out = QLineEdit()
        self.edit_out.setPlaceholderText("选择 4 个 gjf/log 的输出目录")
        rg.addWidget(self.edit_out, 0, 1, 1, 2)
        self.btn_out_browse = QPushButton("浏览")
        self.btn_out_browse.clicked.connect(self._browse_out_dir)
        rg.addWidget(self.btn_out_browse, 0, 3)
        rg.addWidget(QLabel("内存 %mem:"), 1, 0)
        self.edit_mem = QLineEdit("8GB")
        self.edit_mem.setMaximumWidth(80)
        rg.addWidget(self.edit_mem, 1, 1)
        rg.addWidget(QLabel("核数 %nprocshared:"), 1, 2)
        self.edit_nproc = QLineEdit("8")
        self.edit_nproc.setMaximumWidth(60)
        rg.addWidget(self.edit_nproc, 1, 3)
        hint_run = QLabel(
            "这些设置只影响本机生成的 4 个片段输入"
            "（方法与基组等取自 TS route）")
        hint_run.setWordWrap(True)
        hint_run.setStyleSheet("color:#64748B;font-size:9pt;")
        rg.addWidget(hint_run, 2, 0, 1, 4)
        rv.addWidget(grp_run)

        grp_log = QGroupBox("运行日志")
        gl = QVBoxLayout(grp_log)
        gl.setContentsMargins(8, 10, 8, 8)
        gl.setSpacing(4)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QTextEdit.WidgetWidth)
        self.log_view.setStyleSheet(
            "QTextEdit{font-family:Consolas,'Microsoft YaHei UI';"
            "font-size:9pt;background:#FBFCFE;border:1px solid #E2E8F0;"
            "border-radius:6px;}")
        gl.addWidget(self.log_view, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 4)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(10)
        gl.addWidget(self.progress)
        self.lbl_run_status = QLabel("就绪")
        self.lbl_run_status.setStyleSheet("color:#64748B;font-size:9pt;")
        gl.addWidget(self.lbl_run_status)
        rv.addWidget(grp_log, 1)
        body.addWidget(right, 2)
        outer.addLayout(body, 1)

        # ── 底部操作条 ──
        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addStretch(1)
        self.btn_gen_only = QPushButton("仅生成输入文件")
        self.btn_gen_only.setMinimumWidth(118)
        self.btn_gen_only.clicked.connect(self._generate_only)
        bar.addWidget(self.btn_gen_only)
        self.btn_run_local = QPushButton(">> 一键生成并运行（4 个 gjf）")
        self.btn_run_local.setObjectName("PrimaryBtn")
        self.btn_run_local.setMinimumHeight(34)
        self.btn_run_local.clicked.connect(self._run_local_workflow)
        bar.addWidget(self.btn_run_local)
        self.btn_stop_local = QPushButton("停止")
        self.btn_stop_local.setMinimumWidth(62)
        self.btn_stop_local.setEnabled(False)
        self.btn_stop_local.clicked.connect(self._stop_local_workflow)
        bar.addWidget(self.btn_stop_local)
        self.btn_close = QPushButton("关闭")
        self.btn_close.setMinimumWidth(122)
        self.btn_close.clicked.connect(self._on_close_clicked)
        bar.addWidget(self.btn_close)
        outer.addLayout(bar)

        self.log_view.document().setMaximumBlockCount(3000)

    def _apply_initial(self, initial):
        for key, edit in (
                ("ts_log", self.edit_ts),
                ("out_dir", self.edit_out),
                ("mem", self.edit_mem),
                ("nproc", self.edit_nproc),
                ("frag1", self.edit_frag1),
                ("frag2", self.edit_frag2),
                ("frag1_charge", self.edit_frag1_charge),
                ("frag1_mult", self.edit_frag1_mult),
                ("frag2_charge", self.edit_frag2_charge),
                ("frag2_mult", self.edit_frag2_mult)):
            value = str(initial.get(key, "") or "")
            if value:
                edit.setText(value)
                edit.setCursorPosition(0)

    # ── 语言 / 动态文字 ──
    def _t(self, key):
        return _translation_map().get(key, key) if self.lang == "en" else key

    def _apply_lang(self):
        if self.lang == "en":
            from molstudio.ui.i18n_utils import apply_text_map
            apply_text_map(self, _translation_map(), "en")
            self.setWindowTitle(self._t("DI 本机一键计算"))
        self._refresh_dynamic_labels()

    def _frag_counts_text(self):
        if self.lang == "en":
            return "Fragment 1: %d atoms  |  Fragment 2: %d atoms" % (
                len(self._frag1), len(self._frag2))
        return "片段 1：%d 原子　|　片段 2：%d 原子" % (
            len(self._frag1), len(self._frag2))

    def _ts_info_text(self):
        if not self._ts_atoms:
            return "No TS loaded yet" if self.lang == "en" else "尚未载入过渡态"
        level = self._route_summary(self._ts_route) or (
            "unknown" if self.lang == "en" else "未知")
        if self.lang == "en":
            return "TS loaded: %d atoms  |  level: %s" % (
                len(self._ts_atoms), level)
        return "已载入过渡态：%d 原子　|　参数：%s" % (
            len(self._ts_atoms), level)

    @staticmethod
    def _route_summary(route):
        route = (route or "").strip()
        if not route:
            return ""
        for token in route.split():
            if "/" in token:
                return token
        return route[:60]

    def _status_text(self, *key):
        table = {
            ("status", "ready"): ("就绪", "Ready"),
            ("status", "loading"): ("载入中…", "Loading…"),
            ("status", "generated"): ("已生成 4 个输入文件",
                                      "Generated 4 input files"),
            ("status", "running"): ("本机计算中…", "Running locally…"),
            ("status", "done"): ("完成：已载入 5 个 log",
                                 "Done: 5 logs loaded"),
            ("status", "stopped"): ("已停止", "Stopped"),
            ("status", "failed"): ("计算失败", "Failed"),
        }
        zh, en = table.get(tuple(key), ("", ""))
        return en if self.lang == "en" else zh

    def _refresh_dynamic_labels(self):
        if hasattr(self, "lbl_ts_info"):
            self.lbl_ts_info.setText(self._ts_info_text())
        if hasattr(self, "lbl_frag_counts"):
            self.lbl_frag_counts.setText(self._frag_counts_text())
        if hasattr(self, "lbl_run_status"):
            self.lbl_run_status.setText(self._status_text(*self._status_key))
            if self._done and hasattr(self, "btn_close"):
                self.btn_close.setText(self._t("关闭并出图"))

    def _append_log(self, message, forward=True):
        text = str(message).rstrip()
        if not text:
            return
        self.log_view.append(text)
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())
        if forward and self._log_cb is not None:
            try:
                self._log_cb("DI: " + text)
            except Exception:                           # noqa: BLE001
                pass

    # ── 片段归属 ──
    def _set_target(self, frag):
        self._target_frag = 1 if frag == 1 else 2
        self.btn_frag1.setChecked(self._target_frag == 1)
        self.btn_frag2.setChecked(self._target_frag == 2)

    def _assign_atoms(self, ids):
        ids = set(ids)
        if not ids:
            return
        if self._target_frag == 1:
            self._frag1 |= ids
            self._frag2 -= ids
        else:
            self._frag2 |= ids
            self._frag1 -= ids
        self._sync_fragment_ui()

    def _sync_fragment_ui(self):
        f1 = di_local.format_ranges(sorted(self._frag1)) or ""
        f2 = di_local.format_ranges(sorted(self._frag2)) or ""
        for edit, text in ((self.edit_frag1, f1), (self.edit_frag2, f2)):
            edit.blockSignals(True)
            edit.setText(text)
            edit.blockSignals(False)
        self.lbl_frag_counts.setText(self._frag_counts_text())
        self.btn_frag1.setChecked(self._target_frag == 1)
        self.btn_frag2.setChecked(self._target_frag == 2)
        if getattr(self, "mol_canvas", None) is not None:
            self.mol_canvas.fragment_atoms = {
                0: set(self._frag1), 1: set(self._frag2)}
            self.mol_canvas.update()

    def _on_canvas_box_select(self, indices):
        if not self._ts_atoms:
            return
        ids = {int(i) for i in indices if int(i) > 0}
        if not ids:
            return
        self._assign_atoms(ids)
        self._append_log("框选 %d 个原子 → 片段 %d（片段 1：%d，片段 2：%d）"
                         % (len(ids), self._target_frag,
                            len(self._frag1), len(self._frag2)))

    def _on_canvas_atom_click(self, atom_idx):
        if not self._ts_atoms:
            return
        try:
            idx = int(atom_idx)
        except (TypeError, ValueError):
            return
        target = self._frag1 if self._target_frag == 1 else self._frag2
        other = self._frag2 if self._target_frag == 1 else self._frag1
        if idx in target:
            target.discard(idx)
        else:
            other.discard(idx)
            target.add(idx)
        self._sync_fragment_ui()

    def _apply_frag_edits(self):
        try:
            f1 = di_local.parse_ranges(self.edit_frag1.text())
            f2 = di_local.parse_ranges(self.edit_frag2.text())
        except ValueError as exc:
            QMessageBox.warning(self, "原子编号", "无法解析原子编号：%s" % exc)
            self._sync_fragment_ui()
            return
        overlap = f1 & f2
        if overlap:
            f1 -= overlap
            f2 -= overlap
            self._append_log("原子 %s 同时出现在两个片段，已从两个片段移除"
                             % di_local.format_ranges(sorted(overlap)))
        self._frag1, self._frag2 = f1, f2
        self._sync_fragment_ui()

    def _auto_fragments(self):
        if not self._ts_atoms:
            QMessageBox.information(self, "自动识别", "请先载入过渡态复合物。")
            return
        bonds = di_local.get_bonds_from_atoms(self._ts_atoms)
        comps = di_local.connected_components(len(self._ts_atoms), bonds)
        if len(comps) != 2:
            QMessageBox.information(
                self, "自动识别",
                "按成键判据检测到 %d 个连通片段，无法自动分成两个片段。\n"
                "请手动 Shift+左键拖框选择。" % len(comps))
            return
        comps = sorted((sorted(c) for c in comps), key=lambda c: c[0])
        self._frag1, self._frag2 = set(comps[0]), set(comps[1])
        self._sync_fragment_ui()
        self._append_log("自动识别片段：片段 1 = %s；片段 2 = %s"
                         % (di_local.format_ranges(comps[0]),
                            di_local.format_ranges(comps[1])))

    def _clear_fragments(self):
        self._frag1.clear()
        self._frag2.clear()
        self._target_frag = 1
        self._sync_fragment_ui()

    # ── 载入过渡态 ──
    def _browse_ts(self):
        p, _ = open_file(
            self, "选择过渡态复合物", "",
            "Gaussian 输出/格式检查点 (*.log *.out *.fchk *.fch);;所有文件 (*.*)")
        if p:
            self.edit_ts.setText(p)
            self._load_ts_from_path(p)

    def _default_out_dir(self):
        if not self._ts_path:
            return ""
        stem = os.path.splitext(os.path.basename(self._ts_path))[0] or "DI"
        return os.path.join(
            os.path.dirname(os.path.abspath(self._ts_path)), stem + "_DI")

    def _browse_out_dir(self):
        d = existing_directory(self, "选择 4 个 gjf/log 的输出目录")
        if d:
            self.edit_out.setText(d)

    def _load_ts_from_path(self, path):
        path = (path or "").strip().strip('"')
        if not path:
            QMessageBox.warning(self, "提示", "请先选择过渡态复合物文件。")
            return
        if not os.path.exists(path):
            QMessageBox.warning(self, "文件不存在", "文件不存在：\n%s" % path)
            return
        try:
            atoms = di_local.read_structure(path)
        except ValueError as exc:
            QMessageBox.critical(self, "无法读取结构", str(exc))
            return
        self._ts_path = os.path.abspath(path)
        self._ts_atoms = atoms
        self._ts_bonds = di_local.get_bonds_from_atoms(atoms)
        self._frag1.clear()
        self._frag2.clear()
        self._target_frag = 1
        self.edit_ts.setText(self._ts_path)
        self.edit_ts.setCursorPosition(0)
        if self.mol_canvas is not None:
            self.mol_canvas.set_data(atoms, self._ts_bonds)
            self.mol_canvas.auto_fit()
            self.mol_canvas.update()

        ext = os.path.splitext(self._ts_path)[1].lower()
        cm = None
        if ext in (".log", ".out"):
            try:
                self._ts_route = di_local.parse_route_section(self._ts_path)
            except Exception:                           # noqa: BLE001
                self._ts_route = ""
            try:
                cm = di_local.parse_charge_multiplicity(self._ts_path)
            except Exception:                           # noqa: BLE001
                cm = None
        else:
            try:
                self._ts_route = di_local.fchk_route_hint(self._ts_path)
            except Exception:                           # noqa: BLE001
                self._ts_route = ""
            cm = fchk_charge_multiplicity(self._ts_path)
        if not self.edit_out.text().strip():
            self.edit_out.setText(self._default_out_dir())
            self.edit_out.setCursorPosition(0)
        self._sync_fragment_ui()
        self._refresh_dynamic_labels()
        level = self._route_summary(self._ts_route) or "未知"
        if cm:
            self._append_log(
                "已载入过渡态 %s（%d 原子，电荷 %d / 多重度 %d，参数：%s）"
                % (os.path.basename(self._ts_path), len(atoms),
                   cm[0], cm[1], level))
        else:
            self._append_log(
                "已载入过渡态 %s（%d 原子，参数：%s）"
                % (os.path.basename(self._ts_path), len(atoms), level))
        self._status_key = ("status", "ready")
        self._refresh_dynamic_labels()

    def _read_fragment_cm(self, edit_c, edit_m, label):
        try:
            charge = int(edit_c.text().strip() or "0")
            mult = int(edit_m.text().strip() or "1")
        except ValueError:
            QMessageBox.warning(
                self, "错误", "%s 的电荷/多重度必须是整数。" % label)
            return None
        if mult < 1:
            QMessageBox.warning(self, "错误", "%s 的多重度必须 ≥ 1。" % label)
            return None
        return charge, mult

    # ── 生成输入 / 本机运行 ──
    def _prepare_jobs(self):
        if not self._ts_atoms:
            QMessageBox.warning(self, "缺少结构",
                                "请先载入过渡态复合物（.log / .fchk）。")
            return None
        try:
            di_local.validate_fragments(
                len(self._ts_atoms), self._frag1, self._frag2)
        except ValueError as exc:
            QMessageBox.warning(self, "片段不完整", str(exc))
            return None
        if not self._ts_route:
            QMessageBox.critical(
                self, "缺少计算参数",
                "没有从过渡态文件里读到 route（方法/基组等计算参数）。\n"
                "请载入过渡态的 Gaussian .log 文件。")
            return None
        cm1 = self._read_fragment_cm(
            self.edit_frag1_charge, self.edit_frag1_mult, "片段 1")
        cm2 = self._read_fragment_cm(
            self.edit_frag2_charge, self.edit_frag2_mult, "片段 2")
        if cm1 is None or cm2 is None:
            return None
        out_dir = self.edit_out.text().strip() or self._default_out_dir()
        if not out_dir:
            QMessageBox.warning(self, "缺少输出目录",
                                "请先选择 4 个 gjf/log 的输出目录。")
            return None
        try:
            nproc = int(self.edit_nproc.text().strip() or "8")
        except ValueError:
            QMessageBox.warning(self, "错误", "核数必须是整数。")
            return None
        if nproc < 1:
            QMessageBox.warning(self, "错误", "核数必须 ≥ 1。")
            return None
        mem = self.edit_mem.text().strip() or "8GB"
        stem = os.path.splitext(os.path.basename(self._ts_path))[0] or "TS"
        try:
            jobs = di_local.prepare_di_jobs(
                self._ts_atoms, self._frag1, self._frag2, out_dir, stem,
                self._ts_route, frag_charges=(cm1, cm2),
                mem=mem, nprocshared=nproc)
        except (ValueError, OSError) as exc:
            QMessageBox.critical(self, "无法生成输入文件", str(exc))
            return None
        self.edit_out.setText(out_dir)
        self.edit_out.setCursorPosition(0)
        for job in jobs:
            self._append_log("生成 %s（%s）"
                             % (os.path.basename(job["gjf"]), job["route"]))
        return jobs

    def _generate_only(self):
        jobs = self._prepare_jobs()
        if not jobs:
            return
        self._last_jobs = jobs
        self._status_key = ("status", "generated")
        self._refresh_dynamic_labels()
        self._append_log("已生成 4 个输入文件，可手动提交或点「一键生成并运行」。")

    def _run_local_workflow(self):
        if self._worker is not None and self._worker.isRunning():
            return
        g16 = (self._get_g16() or "").strip() or find_gaussian()
        if not g16 or not os.path.isfile(g16):
            QMessageBox.critical(
                self, "缺少 Gaussian",
                "没有找到 g16.exe。\n"
                "请在主窗口 ⚙️ 路径设置里配置 Gaussian 可执行文件。")
            return
        jobs = self._prepare_jobs()
        if not jobs:
            return
        self._last_jobs = jobs
        self._set_busy(True)
        self._done = False
        self.progress.setRange(0, len(jobs))
        self.progress.setValue(0)
        self._status_key = ("status", "running")
        self._refresh_dynamic_labels()
        self._append_log("开始本机计算（%d 个 Gaussian 任务）…" % len(jobs))
        self._worker = DiLocalWorker(jobs, g16, parent=self)
        self._worker.log.connect(self._on_local_log)
        self._worker.completed.connect(self._on_local_done)
        self._worker.failed.connect(self._on_local_failed)
        self._worker.start()

    def _on_local_log(self, message):
        text = str(message).rstrip()
        if not text:
            return
        m = re.search(r"\[(\d+)/(\d+)\]", text)
        if m:
            total = max(1, int(m.group(2)))
            self.progress.setRange(0, total)
            self.progress.setValue(max(0, int(m.group(1)) - 1))
        keep = ("===" in text or "SCF Done" in text
                or "Normal termination" in text
                or "Error termination" in text
                or "Optimization completed" in text
                or "Stationary point found" in text
                or "Frequencies --" in text
                or "完成" in text)
        if keep:
            self._append_log(text)

    def _on_local_done(self, result):
        self._set_busy(False)
        jobs = (result or {}).get("jobs") or self._last_jobs
        if jobs:
            self._last_jobs = jobs
        self.progress.setValue(self.progress.maximum())
        self._done = True
        self._status_key = ("status", "done")
        self._refresh_dynamic_labels()
        self._append_log("本机计算完成：关闭窗口后自动载入 5 个 log 并出图。")

    def _on_local_failed(self, message):
        self._set_busy(False)
        self.progress.setValue(0)
        stopped = "停止" in (message or "")
        self._status_key = (
            ("status", "stopped") if stopped else ("status", "failed"))
        self._refresh_dynamic_labels()
        self._append_log("本机计算中止：%s" % message)

    def _stop_local_workflow(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.request_cancel()
            self._append_log("正在停止本机计算…")

    def _set_busy(self, busy):
        for widget in (self.btn_run_local, self.btn_gen_only,
                       self.btn_ts_browse, self.btn_ts_load,
                       self.btn_frag1, self.btn_frag2,
                       self.btn_frag_auto, self.btn_frag_clear,
                       self.btn_out_browse):
            widget.setEnabled(not busy)
        self.btn_stop_local.setEnabled(bool(busy))

    # ── 关闭 / 结果 ──
    def _on_close_clicked(self):
        if self._done:
            self.accept()
            return
        self.reject()

    def reject(self):
        if self._done:
            # 已经跑完：无论点 X / 按 Esc 都按「关闭并出图」处理，别把结果丢掉
            self.accept()
            return
        if self._worker is not None and self._worker.isRunning():
            ans = QMessageBox.question(
                self, "本机计算",
                "计算仍在进行，停止并关闭窗口？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ans != QMessageBox.Yes:
                return
            self._worker.request_cancel()
            self._worker.wait(6000)
        super().reject()

    def closeEvent(self, event):
        if self._done:
            self.accept()
            event.accept()
            return
        if self._worker is not None and self._worker.isRunning():
            ans = QMessageBox.question(
                self, "本机计算",
                "计算仍在进行，停止并关闭窗口？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ans != QMessageBox.Yes:
                event.ignore()
                return
            self._worker.request_cancel()
            self._worker.wait(6000)
        super().closeEvent(event)

    @property
    def is_done(self):
        return bool(self._done)

    def log_data(self):
        """成功后返回 5 个 log 的路径映射；未完成返回 None。"""
        if not self._done or not self._last_jobs:
            return None
        logs = {"ts": self._ts_path}
        for job in self._last_jobs:
            role = job.get("role", "")
            if role:
                logs[role] = job.get("log", "")
        return logs

    def config(self):
        """当前窗口里的可持久化配置（取消关闭也会带回）。"""
        return {
            "ts_log": self._ts_path or self.edit_ts.text().strip(),
            "out_dir": self.edit_out.text().strip(),
            "mem": self.edit_mem.text().strip(),
            "nproc": self.edit_nproc.text().strip(),
            "frag1": self.edit_frag1.text().strip(),
            "frag2": self.edit_frag2.text().strip(),
            "frag1_charge": self.edit_frag1_charge.text().strip(),
            "frag1_mult": self.edit_frag1_mult.text().strip(),
            "frag2_charge": self.edit_frag2_charge.text().strip(),
            "frag2_mult": self.edit_frag2_mult.text().strip(),
        }
