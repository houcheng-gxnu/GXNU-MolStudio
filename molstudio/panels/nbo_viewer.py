# -*- coding: utf-8 -*-
"""
nbo_viewer.py — NBO 分析面板（整合自 NBOViewer）
=================================================

读取 Gaussian ``pop=nbo`` 日志里的 NBO 轨道与 E(2) 二阶微扰相互作用。
可视化优先使用 NBO plot ``.31/.37`` 的真实 NBO 系数；对于
``pop=saveNBO`` 的 fchk，则严格按日志里的 storage permutation 选轨道。
普通 fchk 只显示明确标注的 canonical-MO 近似提示，不冒充 NBO。

NboPanel 是作为主窗口右侧 QTabWidget 的一个页签使用的面板：

    from molstudio.panels.nbo_viewer import NboPanel
    panel = NboPanel(glw=app.cub_canvas.glw,
                     multiwfn_path=app.paths["multiwfn"],
                     get_fchk=lambda: app._current_fchk)

本模块解析逻辑移植自 NBOViewer (nbo_parser.py)。
"""

import os
import shutil
import subprocess
import sys
import tempfile
import traceback

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFrame, QGroupBox, QInputDialog, QComboBox,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer

from molstudio.panels.nbo_parser import (
    run_analysis, build_full_overview, resolve_nbo_visual_source,
)
from molstudio.core.fchk_orbital import gen_cube
from molstudio.panels.nbo_input_dialog import NboInputDialog
from molstudio.ui.file_dialogs import open_file


# ═══════════════════════════════════════════════════════════════
# NBO cube 归档（仿 ESP：与 fchk 同目录建 <stem>_NBO，生成的 MO cube
# 全部收进该目录；同一行再双击时直接复用，不重跑 Multiwfn）
# ═══════════════════════════════════════════════════════════════

def nbo_arch_dir(fchk):
    """NBO cube 归档目录：与 fchk 同目录的 '<stem>_NBO'（对应 ESP 的 <stem>_ESP）。"""
    stem = os.path.splitext(os.path.basename(fchk))[0]
    return os.path.join(os.path.dirname(os.path.abspath(fchk)), f"{stem}_NBO")


def nbo_orbital_str(mo_num, mo_type):
    """NBO 轨道 → Multiwfn orbital 参数：Alpha 用正数，Beta 用负数。"""
    return str(mo_num) if mo_type == "Alpha" else "-" + str(mo_num)


def nbo_mo_cube_path(fchk, mo_num, mo_type):
    """某 MO 在归档目录中的 cube 路径（可能尚未生成）。"""
    orbital = nbo_orbital_str(mo_num, mo_type)
    stem = os.path.splitext(os.path.basename(fchk))[0]
    return os.path.join(nbo_arch_dir(fchk), f"{stem}_MO{orbital}.cub")


def nbo_plot_cube_path(plot31, nbo_id):
    """Cube archive path for an actual ``.37`` NBO plot orbital."""
    stem = os.path.splitext(os.path.basename(plot31))[0]
    return os.path.join(
        nbo_arch_dir(plot31), f"{stem}_NBO{nbo_id}.cub")


def gen_nbo_plot_cube(plot31, nbo_id, grid_quality=2, multiwfn_exe=None,
                      plot_type=37):
    """Generate a cube directly from the NBO ``.31`` + ``.37`` plot pair.

    Unlike a normal fchk, the plot pair stores the real NBO coefficients, so
    the selected orbital number is identical to the NBO number in the log.
    """
    plot31 = os.path.abspath(plot31)
    root = os.path.splitext(plot31)[0]
    selected_plot = root + "." + str(plot_type)
    target = nbo_plot_cube_path(plot31, nbo_id)
    if os.path.exists(target):
        return target
    os.makedirs(os.path.dirname(target), exist_ok=True)

    # Run Multiwfn in the system temp folder with ASCII input names. The final
    # cube is moved into the archive, so Chinese/space-containing project paths
    # do not become command-line inputs for older Multiwfn builds.
    temp_dir = tempfile.mkdtemp(prefix="_multiwfn_nbo_")
    local_basis = os.path.join(temp_dir, "nbo.31")
    local_selected = os.path.join(temp_dir, "nbo." + str(plot_type))
    try:
        shutil.copy2(plot31, local_basis)
        shutil.copy2(selected_plot, local_selected)
        inputs = (
            "\nnbo.31\n" + str(plot_type) + "\n5\n4\n"
            + str(int(nbo_id)) + "\n" + str(int(grid_quality))
            + "\n2\n0\nq\n"
        )
        result = subprocess.run(
            [multiwfn_exe], cwd=temp_dir, input=inputs, timeout=600,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace",
            creationflags=(
                subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
                if sys.platform == "win32" else 0),
        )
        cube_src = os.path.join(temp_dir, "MOvalue.cub")
        if result.returncode != 0 or not os.path.isfile(cube_src):
            return None
        shutil.move(cube_src, target)
        return target
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════
# 后台线程
# ═══════════════════════════════════════════════════════════════

class NboAnalysisWorker(QThread):
    """后台跑 NBO 分析，完成后发射 (data_dict, text_report)。

    atom1=None 且 atom2=None 时执行「全量概览」（列出所有 NBO 轨道）。
    """
    finished = pyqtSignal(object, object)

    def __init__(self, log_file, atom1, atom2, min_e2, fchk_file,
                 plot_file=None):
        super().__init__()
        self.log_file = log_file
        self.atom1 = atom1
        self.atom2 = atom2
        self.min_e2 = min_e2
        self.fchk_file = fchk_file
        self.plot_file = plot_file

    def run(self):
        try:
            if self.atom1 is None:
                overview = build_full_overview(
                    self.log_file, self.fchk_file, self.plot_file)
                data = {
                    "nbo_overview": overview,
                    "cross_e2_details": [],
                    "single_atom_mode": False,
                    "full_mode": True,
                    "visual_source": resolve_nbo_visual_source(
                        self.log_file, self.fchk_file, self.plot_file),
                    "atom1": None,
                    "atom2": None,
                }
                self.finished.emit(data, "")
                return
            text, data = run_analysis(
                self.log_file, self.atom1, self.atom2, self.min_e2,
                self.fchk_file, plot_file=self.plot_file)
            self.finished.emit(data, text)
        except Exception:
            traceback.print_exc()
            self.finished.emit(None, "")


class NboCubeWorker(QThread):
    """Generate one direct-source NBO/MO cube, reusing the archive."""
    finished = pyqtSignal(object, object)  # (cube_path, visual_ref)
    error = pyqtSignal(str)

    def __init__(self, visual, multiwfn_exe, grid_quality=2,
                 work_dir=None):
        super().__init__()
        self.visual = dict(visual)
        self.multiwfn_exe = multiwfn_exe
        self.grid_quality = int(grid_quality)
        self.work_dir = work_dir

    def run(self):
        try:
            cube = None
            kind = self.visual.get("kind")
            source = self.visual.get("source", "")
            orbital = self.visual.get("orbital")
            if kind == "plot":
                target = nbo_plot_cube_path(source, self.visual["nbo_id"])
                if os.path.exists(target):
                    cube = target
                else:
                    cube = gen_nbo_plot_cube(
                        source, self.visual["nbo_id"],
                        grid_quality=self.grid_quality,
                        multiwfn_exe=self.multiwfn_exe,
                        plot_type=self.visual.get("plot_type", 37))
            elif kind in ("fchk", "canonical") and source and os.path.exists(source):
                mo_num = int(orbital)
                target = nbo_mo_cube_path(
                    source, abs(mo_num), "Alpha" if mo_num >= 0 else "Beta")
                if os.path.exists(target):
                    cube = target
                else:
                    cube = gen_cube(
                        source, orbital=orbital,
                        grid_quality=self.grid_quality,
                        multiwfn_exe=self.multiwfn_exe,
                        work_dir=os.path.dirname(target))
            else:
                self.error.emit("No direct NBO wavefunction source")
                return
            if cube:
                self.finished.emit(cube, self.visual)
            else:
                self.error.emit(
                    f"NBO orbital #{self.visual.get('nbo_id', orbital)} "
                    "cube generation failed")
        except Exception as e:
            self.error.emit(str(e))


# ═══════════════════════════════════════════════════════════════
# NBO 分析面板
# ═══════════════════════════════════════════════════════════════

_NBO_TR = {
    "zh": {
        "open_log": "打开 NBO log…",
        "open_fchk": "打开 fchk…",
        "open_plot": "NBO plot…",
        "make_input": "NBO 输入…",
        "lbl_log": "NBO log:",
        "placeholder_log": "选择 Gaussian .log/.out 文件…",
        "analyze": "分析",
        "e2_threshold": "E(2) 阈值:",
        "grid_quality": "格点:",
        "tip_open_plot": "推荐直接选择 .37，程序会自动配对 .31",
        "tip_make_input": "载入 gjf 后编辑并生成 Gaussian NBO 输入",
        "tip_grid": "Multiwfn 空间格点质量：1 稀疏，5 精细",
        "reset_view": "重置视角",
        "clear": "清空",
        "multiwfn": "Multiwfn:",
        "browse": "浏览",
        "nbo_table": "NBO 轨道概览",
        "e2_table": "跨原子 E(2) 相互作用",
        "status_ready": "就绪 — 打开 NBO log，点「分析」看全部 NBO；或左画布选 1/2 个原子查指定原子",
        "no_log": "请先打开 Gaussian NBO 日志文件 (.log/.out)",
        "no_fchk": "未关联 fchk，无法载入分子结构",
        "no_plot_hint": "要绘制真实 NBO，请选择同名的 .31 + .37 NBO plot 文件",
        "source": "轨道来源: {source}",
        "source_canonical": (
            "普通 fchk 只存 canonical MO；双击仍可查看 nearest-MO 近似，"
            "但严格 NBO 需使用 .31/.37 或 saveNBO fchk。"),
        "source_none": (
            "未找到 NBO plot 或 saveNBO fchk。当前日志/文件只能用于 NBO/E(2) "
            "数值分析。"),
        "no_exe": "Multiwfn.exe 不存在，请先在主界面 ⚙️ 路径设置中配置",
        "analyzing": "正在分析…",
        "done_full": "全部 {n} 个 NBO 轨道（选 1/2 个原子可筛选）",
        "done_single": "原子 #{a}: {n} 个 NBO 轨道",
        "done_dual": "原子 #{a} 与 #{b}: {n} 个 NBO + {m} 个跨原子 E(2)",
        "no_nbo": "该选择下没有 NBO 轨道",
        "sel_one_or_two": "请选择 1 个原子查 NBO，或 2 个原子查跨原子 E(2)",
        "double_click": "双击表格行可视化对应轨道",
        "gen_mo": "生成 {mo_type} MO #{mo_num} cube…",
        "reuse_mo": "复用已归档 {mo_type} MO #{mo_num} cube",
        "gen_nbo": "生成 {label} cube…",
        "reuse_nbo": "复用已归档 {label} cube",
        "loaded_mo": "{mo_type} MO #{mo_num} 已加载到画布",
        "loaded_visual": "{label} 已加载到画布",
        "dual_loaded": "{n} 个轨道已叠加到画布",
        "no_mo": "该行没有可靠的可视化来源",
        "no_direct": "canonical MO 近似视图；不等同于严格 NBO",
        "flip_phase": "翻转相位",
        "flip_choose": "选择要翻转的轨道:",
        "flip_all": "翻转全部",
        "flip_none": "画布上还没有轨道，先双击表格行可视化",
        "flip_done_one": "画布轨道 {label} 相位已翻转",
        "flip_done_all": "画布 {n} 个轨道相位已翻转",
        "src_label_plot": "轨道来源：NBO plot（{name}）· .37 里是真实 NBO 系数",
        "src_label_save": (
            "轨道来源：saveNBO fchk（{name}）· fchk 里存的就是 NBO，"
            "MO 号 = NBO 存储位置"),
        "src_label_canonical": (
            "轨道来源：普通 fchk（{name}）· 只存 canonical MO，"
            "双击是近似视图，不是严格 NBO"),
        "src_label_none": "轨道来源：未找到 NBO 波函数 · 只能看占据与 E(2) 数值",
        "src_label_empty": "轨道来源：尚未载入 NBO 日志",
        "col_nbo_id": "NBO",
        "col_type": "类型",
        "col_atoms": "原子",
        "col_occ": "占据",
        "col_energy": "能量",
        "col_mo": "MO",
        "col_source": "MO",
        "col_idx": "#",
        "col_e2": "E(2)",
        "col_stars": "强度",
        "col_donor": "供体",
        "col_acceptor": "受体",
        "tip_source_cell": "双击可视化（{display}）",
    },
    "en": {
        "open_log": "Open NBO log…",
        "open_fchk": "Open fchk…",
        "open_plot": "NBO plot…",
        "make_input": "NBO input…",
        "lbl_log": "NBO log:",
        "placeholder_log": "Choose a Gaussian .log/.out file…",
        "analyze": "Analyze",
        "e2_threshold": "E(2) threshold:",
        "grid_quality": "Grid:",
        "tip_open_plot": "Choose .37; the matching .31 is paired automatically",
        "tip_make_input": "Load a GJF, edit it, and build a Gaussian NBO input",
        "tip_grid": "Multiwfn spatial-grid quality: 1 sparse, 5 fine",
        "reset_view": "Reset View",
        "clear": "Clear",
        "multiwfn": "Multiwfn:",
        "browse": "Browse",
        "nbo_table": "NBO ORBITAL OVERVIEW",
        "e2_table": "CROSS-ATOM E(2) INTERACTIONS",
        "status_ready": "Ready — open NBO log, click Analyze for all NBOs, or pick 1/2 atoms to filter",
        "no_log": "Please open a Gaussian NBO log first (.log/.out)",
        "no_fchk": "No fchk linked; molecule geometry cannot be loaded",
        "no_plot_hint": "For true NBOs, select the matching .31 + .37 NBO plot files",
        "source": "Orbital source: {source}",
        "source_canonical": (
            "A normal fchk stores canonical MOs. Double-click still shows a "
            "nearest-MO approximation; strict NBOs require .31/.37 or saveNBO."),
        "source_none": (
            "No NBO plot or saveNBO fchk was found. This log can still be "
            "used for NBO occupations and E(2) analysis."),
        "no_exe": "Multiwfn.exe not found, configure it in ⚙️ Path Settings first",
        "analyzing": "Analyzing…",
        "done_full": "All {n} NBO orbitals (pick 1/2 atoms to filter)",
        "done_single": "Atom #{a}: {n} NBO orbitals",
        "done_dual": "Atom #{a} & #{b}: {n} NBOs + {m} cross-atom E(2)",
        "no_nbo": "No NBO orbitals for this selection",
        "sel_one_or_two": "Pick 1 atom for NBOs, or 2 atoms for cross-atom E(2)",
        "double_click": "Double-click a row to visualize its orbital",
        "gen_mo": "Generating {mo_type} MO #{mo_num} cube…",
        "reuse_mo": "Reuse archived {mo_type} MO #{mo_num} cube",
        "gen_nbo": "Generating {label} cube…",
        "reuse_nbo": "Reuse archived {label} cube",
        "loaded_mo": "{mo_type} MO #{mo_num} loaded to canvas",
        "loaded_visual": "{label} loaded to canvas",
        "dual_loaded": "{n} orbitals overlaid on canvas",
        "no_mo": "No reliable visualization source for this row",
        "no_direct": "Canonical-MO approximation, not a strict NBO",
        "col_nbo_id": "NBO",
        "col_type": "Type",
        "col_atoms": "Atoms",
        "col_occ": "Occ.",
        "col_energy": "Energy",
        "col_mo": "MO",
        "col_source": "MO",
        "col_idx": "#",
        "col_e2": "E(2)",
        "col_stars": "Str",
        "col_donor": "Donor",
        "col_acceptor": "Acceptor",
        "tip_source_cell": "Double-click to visualize ({display})",
        "flip_phase": "Flip Phase",
        "flip_choose": "Select orbital to flip:",
        "flip_all": "Flip All",
        "flip_none": "No orbitals on canvas — double-click a row to visualize first",
        "flip_done_one": "Canvas orbital {label} phase flipped",
        "flip_done_all": "Flipped {n} canvas orbitals",
        "src_label_plot": "Source: NBO plot ({name}) · .37 holds the real NBO coefficients",
        "src_label_save": (
            "Source: saveNBO fchk ({name}) · the fchk stores NBOs, so the MO "
            "index is the NBO storage position"),
        "src_label_canonical": (
            "Source: plain fchk ({name}) · canonical MOs only; double-click "
            "shows an approximation, not a strict NBO"),
        "src_label_none": "Source: no NBO wavefunction found · numeric NBO/E(2) only",
        "src_label_empty": "Source: no NBO log loaded yet",
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
        self.plot_file = None    # 手动/自动关联的 NBO .37（或 .31）
        self._analysis_worker = None
        self._cube_worker = None
        self._nbo_data = None      # 最近一次 data_dict
        self._e2_details = []      # cross_e2_details
        self._visual_source = {}   # 最近一次 resolve_nbo_visual_source 结果
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
        self.btn_open_plot.setText(self._t("open_plot"))
        self.btn_make_input.setText(self._t("make_input"))
        self.lbl_log.setText(self._t("lbl_log"))
        self.edit_log.setPlaceholderText(self._t("placeholder_log"))
        self.btn_browse_log.setText(self._t("browse"))
        self.btn_analyze.setText(self._t("analyze"))
        self.lbl_e2.setText(self._t("e2_threshold"))
        self.lbl_grid.setText(self._t("grid_quality"))
        self.btn_open_plot.setToolTip(self._t("tip_open_plot"))
        self.btn_make_input.setToolTip(self._t("tip_make_input"))
        self.combo_grid.setToolTip(self._t("tip_grid"))
        self.btn_reset.setText(self._t("reset_view"))
        self.btn_clear.setText(self._t("clear"))
        self.btn_flip.setText(self._t("flip_phase"))
        self.grp_nbo.setTitle(self._t("nbo_table"))
        self.grp_e2.setTitle(self._t("e2_table"))
        self.table_nbo.setHorizontalHeaderLabels([
            self._t("col_nbo_id"), self._t("col_type"), self._t("col_atoms"),
            self._t("col_occ"), self._t("col_energy"),
            self._t("col_source")])
        self.table_e2.setHorizontalHeaderLabels([
            self._t("col_idx"), self._t("col_e2"), self._t("col_stars"),
            self._t("col_donor"), self._t("col_acceptor"),
            self._t("col_source")])
        self._render_source_label()

    def set_lang(self, lang):
        self.lang = "zh" if lang == "zh" else "en"
        self._apply_lang()

    # ── 轨道来源提示 ──
    _SRC_STYLES = {
        "plot": "color:#1D4ED8;background:#EEF4FF;border:1px solid #C7D7F5;",
        "saveNBO": "color:#1D4ED8;background:#EEF4FF;border:1px solid #C7D7F5;",
        "canonical": "color:#8A5A00;background:#FFF7E6;border:1px solid #F3D9A4;",
        "none": "color:#B91C1C;background:#FEF2F2;border:1px solid #F5C9C9;",
    }

    def _render_source_label(self, source=None):
        """显示当前分析用的轨道来源（plot / saveNBO / canonical / none）。

        没有这行时，用户看到 ``Alpha#9`` 无法判断它是 NBO 还是正则轨道；
        canonical 与 none 两种必须明确标出来，避免把近似当成严格 NBO。
        """
        if source is not None:
            self._visual_source = dict(source)
        source = self._visual_source or {}
        kind = str(source.get("kind") or "")
        name = ""
        if kind == "plot":
            name = os.path.basename(
                source.get("selected") or source.get("basis") or "")
            text = self._t("src_label_plot", name=name)
        elif kind == "saveNBO":
            name = os.path.basename(source.get("fchk") or "")
            text = self._t("src_label_save", name=name)
        elif kind == "canonical":
            name = os.path.basename(source.get("fchk") or "")
            text = self._t("src_label_canonical", name=name)
        elif kind == "none":
            text = self._t("src_label_none")
        else:
            text = self._t("src_label_empty")
        style = self._SRC_STYLES.get(
            kind, "color:#64748B;background:#F8FAFC;border:1px solid #E2E8F0;")
        if hasattr(self, "lbl_source"):
            self.lbl_source.setText(text)
            self.lbl_source.setStyleSheet(
                style + "border-radius:4px;padding:4px 8px;font-size:9pt;")

    # ── UI ──
    def _build_ui(self):
        v = QVBoxLayout(self)
        # 全站统一：页面外边距 8px + 一级块间距 8px（基准 = AIM 面板，见
        # aim_panel._build_ui）。原来这里是 0，内容直接贴住右栏卡片边线。
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

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

        self.lbl_grid = QLabel()
        bv.addWidget(self.lbl_grid)
        self.combo_grid = QComboBox()
        self.combo_grid.addItems(["1", "2", "3", "4", "5"])
        self.combo_grid.setCurrentIndex(1)
        self.combo_grid.setMaximumWidth(52)
        bv.addWidget(self.combo_grid)

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
        self.btn_open_plot = QPushButton()
        self.btn_open_plot.clicked.connect(self._browse_plot)
        lh.addWidget(self.btn_open_plot)
        self.btn_make_input = QPushButton()
        self.btn_make_input.clicked.connect(self._open_nbo_input_generator)
        lh.addWidget(self.btn_make_input)
        v.addWidget(log_row)

        # 轨道来源提示：让「Alpha#9」这类编号的含义一眼可见
        self.lbl_source = QLabel()
        self.lbl_source.setWordWrap(True)
        self.lbl_source.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.lbl_source)

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
        # A plot file belongs to the previously opened stem. Never carry it
        # across logs or two different molecules can silently share cubes.
        root = os.path.splitext(p)[0]
        sibling_37 = root + ".37"
        sibling_31 = root + ".31"
        self.plot_file = sibling_37 if (
            os.path.exists(sibling_37) and os.path.exists(sibling_31)
        ) else None
        if self.plot_file:
            self._log("自动关联 NBO plot: " + os.path.basename(self.plot_file))
        # 自动检测同目录下的同名 .fchk；新 log 不能沿用上一分子的面板内
        # fchk，否则轨道来源和画布结构会悄悄串到另一份计算上。
        self.fchk_file = None
        candidate = root + ".fchk"
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

    def _browse_plot(self):
        p, _ = open_file(
            self, "选择 NBO plot (.37 或 .31)", "",
            "NBO plot (*.37 *.31 *.32 *.33 *.34 *.35 *.36 *.38 *.39 *.40);;"
            "所有文件 (*)")
        if not p:
            return
        try:
            ext = int(os.path.splitext(p)[1].lstrip("."))
        except ValueError:
            ext = 0
        if ext not in (31,) and not (32 <= ext <= 40):
            self._set_status(self._t("no_plot_hint"))
            return
        self.plot_file = p
        self._log("NBO plot: " + os.path.basename(p))
        fchk = self._resolve_fchk()
        if not fchk:
            root = os.path.splitext(p)[0]
            candidate = root + ".fchk"
            if os.path.exists(candidate):
                self.fchk_file = candidate
                fchk = candidate
        if fchk:
            self._load_molecule_to_canvas(fchk)
        self._on_analyze_clicked()

    def _open_nbo_input_generator(self):
        """Open the editable generator; a current log is only an optional seed."""
        dlg = NboInputDialog(
            initial_source=self.log_file or "",
            initial_fchk=self._resolve_fchk(),
            lang=self.lang, parent=self)
        dlg.exec_()

    def _load_molecule_to_canvas(self, fchk):
        """把 fchk 的分子结构加载到左侧画布（供选原子 + 定位）。"""
        if self.glw is None:
            return
        try:
            from molstudio.render.molcanvas import get_atoms_from_fchk, get_bonds_from_fchk
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

    def _grid_quality(self):
        try:
            return int(self.combo_grid.currentText())
        except (TypeError, ValueError):
            return 2

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
            self.log_file, atom1, atom2, min_e2, fchk, self.plot_file)
        self._analysis_worker.finished.connect(self._on_analysis_done)
        self._analysis_worker.start()

    def _on_analysis_done(self, data, text):
        if data is None:
            self._set_status(self._t("no_nbo"))
            return
        self._nbo_data = data
        self._render_source_label(data.get("visual_source"))
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
    def _fit_columns(self, table, content_cols, stretch_cols):
        """按内容收窄数字列，把剩余宽度让给文字列（供体/受体/MO）。

        右栏面板本来就窄，默认 100 px 的列宽会把 ``BD*(1)C5-Cl8`` 截成
        ``BD*(1)C5-…``；数字列用 ResizeToContents 省下的宽度正好补给它。
        """
        header = table.horizontalHeader()
        for c in content_cols:
            header.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        for c in stretch_cols:
            header.setSectionResizeMode(c, QHeaderView.Stretch)

    def _render_nbo_table(self, data):
        overview = data.get("nbo_overview", [])
        self.table_nbo.setRowCount(0)
        self.table_nbo.setRowCount(len(overview))
        for i, e in enumerate(overview):
            visual = e.get("visual")
            source_text = visual.get("display", "—") if visual else "—"
            cells = [
                str(e["nbo_id"]),
                e.get("type_label", e["type"]),
                e.get("atoms_str", ""),
                f"{e['occupancy']:.5f}" if e.get("occupancy") is not None else "—",
                f"{e['energy']:.5f}" if e.get("energy") is not None else "—",
                source_text,
            ]
            for j, txt in enumerate(cells):
                item = QTableWidgetItem(txt)
                item.setTextAlignment(Qt.AlignCenter)
                if j == 5 and visual:
                    item.setData(Qt.UserRole, visual)
                    item.setToolTip(self._t(
                        "tip_source_cell", display=source_text))
                self.table_nbo.setItem(i, j, item)
        self._fit_columns(self.table_nbo, [0, 1, 2, 3, 4], [5])

    def _render_e2_table(self, data):
        details = data.get("cross_e2_details", [])
        self._e2_details = details
        self.table_e2.setRowCount(0)
        self.table_e2.setRowCount(len(details))
        for i, d in enumerate(details):
            visuals = [
                v for v in (d.get("visual_donor"),
                            d.get("visual_acceptor")) if v
            ]
            source_text = " + ".join(
                v.get("display", "—") for v in visuals) if visuals else "—"
            cells = [
                str(d["idx"]),
                f"{d['e2']:.2f}",
                d.get("stars", ""),
                d.get("donor_label", ""),
                d.get("acceptor_label", ""),
                source_text,
            ]
            tips = [
                "", "", "",
                d.get("donor_str", ""), d.get("acceptor_str", ""),
                self._t("tip_source_cell", display=source_text),
            ]
            for j, txt in enumerate(cells):
                item = QTableWidgetItem(txt)
                if j in (1, 2, 5):
                    item.setTextAlignment(Qt.AlignCenter)
                if j == 5 and visuals:
                    item.setData(Qt.UserRole, visuals)
                if tips[j]:
                    # 面板窄，「供体 / 受体」列常被截断；悬停可看完整标签
                    item.setToolTip(tips[j])
                self.table_e2.setItem(i, j, item)
        self._fit_columns(self.table_e2, [0, 1, 2, 5], [3, 4])

    # ── 双击可视化 MO ──
    def _on_nbo_double_click(self, row, _col):
        item = self.table_nbo.item(row, 5)
        if item is None:
            return
        visual = item.data(Qt.UserRole)
        if not visual:
            self._set_status(self._t("no_mo"))
            return
        if not visual.get("renderable", visual.get("direct")):
            self._set_status(self._t("no_mo"))
            return
        self._visualize_visual(visual)

    def _on_e2_double_click(self, row, _col):
        item = self.table_e2.item(row, 5)
        if item is None:
            return
        visuals = item.data(Qt.UserRole)
        if not visuals:
            self._set_status(self._t("no_mo"))
            return
        if any(not v.get("renderable", v.get("direct")) for v in visuals):
            self._set_status(self._t("no_mo"))
            return
        # E(2) 双轨道：donor + acceptor 同时可视化
        self._visualize_dual(list(visuals))

    def _apply_style(self):
        """（已停用）曾用于把「主窗口的 VMD 风格下拉」套到画布上。

        2026-09-27 移除调用：那个下拉与画布的等值面样式不是同一套东西，
        而且 set_style() 会把**相位色重置成该样式的默认值** —— 用户先点了一键
        样式（VESTA / CYLview / IQmol … 各有自己的等值面配色），一进 NBO 可视
        化就被打回 sob-art 的配色，二阶微扰（E(2) 双 cub 叠加）尤其明显。
        现在 NBO 的可视化只把 cube 交给画布，配色/材质沿用画布**当前**那套
        （即用户刚点的一键样式），E(2) 的两个轨道再用「同一对色、相位互换」
        彼此区分（见 _visualize_dual）。本方法保留为空壳，避免外部旧代码调用
        时报 AttributeError。
        """
        return

    def _visualize_visual(self, visual):
        source = visual.get("source")
        if not source or not os.path.exists(source):
            self._set_status(self._t("source_none"))
            return
        mw = (self._get_mw() or "").strip()
        if not mw or not os.path.exists(mw):
            self._set_status(self._t("no_exe"))
            return
        if visual.get("kind") == "plot":
            target = nbo_plot_cube_path(source, visual["nbo_id"])
            label = visual.get("display", "NBO")
            if os.path.exists(target):
                self._log(self._t("reuse_nbo", label=label))
            else:
                self._log(self._t("gen_nbo", label=label))
        else:
            mo_num = abs(int(visual["orbital"]))
            mo_type = visual.get("mo_type", "Alpha")
            if os.path.exists(nbo_mo_cube_path(source, mo_num, mo_type)):
                self._log(self._t("reuse_mo", mo_type=mo_type, mo_num=mo_num))
            else:
                self._log(self._t("gen_mo", mo_type=mo_type, mo_num=mo_num))
        self._cube_worker = NboCubeWorker(
            visual, mw, grid_quality=self._grid_quality())
        self._cube_worker.finished.connect(self._on_cube_done)
        self._cube_worker.error.connect(lambda e: self._set_status(str(e)))
        self._cube_worker.start()

    def _on_cube_done(self, cube_path, visual):
        label = visual.get("display", "NBO")
        if self.glw is not None:
            # 不再套主窗口的 VMD 风格（会把画布相位色重置成 sob-art）：
            # 直接按画布**当前**配色渲染，见 _apply_style 的说明。
            self.glw.load(cube_path, 0.05)
            self._canvas_orbitals = [(label, cube_path)]
            # 登记 VMD 同步场景（画布当前 MO）
            self.glw.set_vmd_scene(
                [{"type": "orbital", "vol": cube_path, "iso": 0.05,
                  "label": label}])
        self._log(self._t("loaded_visual", label=label))

    # ── E(2) 双轨道叠加 ──
    def _visualize_dual(self, entries):
        """donor + acceptor 两个 MO 同时可视化。

        配色：两者都用**画布当前**的正/负相位色（即用户刚点的一键样式配色），
        受体用同一对色交换相位 —— 既保持该样式自己的配色，又能区分两个轨道。
        不再套主窗口的 VMD 风格（那会把配色打回 sob-art，见 _apply_style 说明）。
        """
        if not entries:
            return
        entries = [
            v for v in entries[:2]
            if v.get("renderable", v.get("direct"))
            and os.path.exists(v.get("source", ""))
        ]
        if not entries:
            self._set_status(self._t("source_none"))
            return
        # 同上：不覆盖画布当前配色/材质。E(2) 双轨道的配色在**真正载入 cube 的
        # 那一刻**（_load_dual_cubes）从画布当前相位色取，避免"生成 cube 期间
        # 用户又换了样式"导致配色对不上。
        self._dual_color_pairs = []

        self._dual_queue = list(entries)
        self._dual_entries = list(entries)   # 保存标签（队列生成 cube 时会被消费）
        self._dual_cubes = []
        self._set_status(self._t("analyzing"))
        self._log("E(2) 双轨道叠加: " + ", ".join(
            str(v.get("display", "NBO")) for v in entries))
        self._gen_next_dual_cube()

    def _gen_next_dual_cube(self):
        if not self._dual_queue:
            self._load_dual_cubes()
            return
        visual = self._dual_queue.pop(0)
        source = visual.get("source")
        mw = (self._get_mw() or "").strip()
        if not source or not os.path.exists(source):
            self._set_status(self._t("source_none"))
            self._dual_queue.clear()
            return
        if not mw or not os.path.exists(mw):
            self._set_status(self._t("no_exe"))
            self._dual_queue.clear()
            return
        if visual.get("kind") == "plot":
            target = nbo_plot_cube_path(source, visual["nbo_id"])
            label = visual.get("display", "NBO")
        else:
            mo_num = abs(int(visual["orbital"]))
            mo_type = visual.get("mo_type", "Alpha")
            target = nbo_mo_cube_path(source, mo_num, mo_type)
            label = visual.get("display", mo_type)
        if os.path.exists(target):
            if visual.get("kind") == "plot":
                self._log(self._t("reuse_nbo", label=label))
            else:
                self._log(self._t("reuse_mo", mo_type=mo_type, mo_num=mo_num))
        else:
            if visual.get("kind") == "plot":
                self._log(self._t("gen_nbo", label=label))
            else:
                self._log(self._t("gen_mo", mo_type=mo_type, mo_num=mo_num))
        self._cube_worker = NboCubeWorker(
            visual, mw, grid_quality=self._grid_quality())
        self._cube_worker.finished.connect(self._on_dual_cube_done)
        self._cube_worker.error.connect(lambda e: self._set_status(str(e)))
        self._cube_worker.start()

    def _on_dual_cube_done(self, cube_path, visual):
        self._dual_cubes.append(cube_path)
        self._gen_next_dual_cube()

    def _load_dual_cubes(self):
        if not self._dual_cubes:
            self._set_status(self._t("no_mo"))
            return
        if self.glw is not None:
            # 配色 = 画布**当前**的正/负相位色（用户刚点的一键样式）
            pc = tuple(int(round(c * 255)) for c in self.glw._pc)
            nc = tuple(int(round(c * 255)) for c in self.glw._nc)
            pairs = [(pc, nc)]
            if len(self._dual_cubes) > 1:
                pairs.append((nc, pc))      # 受体：同一对色、相位互换
            self._dual_color_pairs = pairs
            self.glw.load_orbitals(self._dual_cubes, 0.05, pairs)
            # 登记 VMD 同步场景（E(2) 双轨道叠加；label 供「翻转相位」选择轨道）
            self._canvas_orbitals = [
                (v.get("display", "NBO"), c)
                for c, v in zip(self._dual_cubes, self._dual_entries)]
            self.glw.set_vmd_scene(
                [{"type": "orbital", "vol": c, "iso": 0.05,
                  "label": v.get("display", "NBO")}
                 for c, v in zip(self._dual_cubes, self._dual_entries)])
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
        self.fchk_file = None
        self.plot_file = None
        self._nbo_data = None
        self._visual_source = {}
        self._render_source_label({})
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
