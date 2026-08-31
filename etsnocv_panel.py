# -*- coding: utf-8 -*-
"""
ETS-NOCV 分析面板（GXNU MolStudio 的一个 tab）。

能量分解 + 自然轨道化学价（ETS-NOCV）分析，移植自 ETS-NOCV-Viewer v6.0：
  - 复合物 + 两个碎片的 fchk → Multiwfn 做 ETS-NOCV 分解（持久会话）
  - NOCV 对表（ΔE_pair / 轨道 / 本征值 / 能量）
  - 选中一对 → 按需生成 NOCV 对密度 cube → 左侧 OpenGL 画布显示正负形变密度
  - 注册 glw.set_vmd_scene，复用主窗口「同步到 VMD」
  - Gaussian .gjf 输入生成器（复用 GjfGeneratorWidget，弹出子窗口）

依赖：Multiwfn / VMD / Tachyon 路径全部走主窗口 ⚙️ 路径设置。
"""

import os
import csv
import sys
import traceback
import tempfile
import shutil

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QPushButton,
    QLineEdit, QFileDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QComboBox, QCheckBox, QMessageBox, QFrame, QProgressBar,
    QSlider, QDialog, QColorDialog, QAbstractItemView, QSizePolicy,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QDoubleValidator

from etsnocv.runner import SetupWorker, CubeGenWorker
from etsnocv.nocv_analyzer import parse_nocv_table, read_fch_alpha_beta
from etsnocv.fchk_parser import get_atoms_from_fchk
from etsnocv.config import NOCV_STYLES
from etsnocv.locale import get_locale
from etsnocv.gaussian_generator import GjfGeneratorWidget


# ── i18n 字典（ETS-NOCV 面板）──
_ETS_TR = {
    "zh": {
        "nocv_head": "NOCV 结果（选中行后点击『可视化』显示到画布）",
        "visualize": "可视化选中对",
        "export_csv": "导出 CSV",
        "grp_files": "文件设置（复合物 + 两个碎片）",
        "complex": "复合物",
        "frag1": "碎片 1", "frag2": "碎片 2",
        "ph_complex": "*.fchk（可留空，用主窗口已载入文件）",
        "ph_fchk": "*.fchk",
        "browse": "浏览",
        "flip1": "碎片 1 翻转自旋", "flip2": "碎片 2 翻转自旋",
        "gen_gjf": "生成 Gaussian 输入 (.gjf)",
        "no_complex": "尚未加载复合物",
        "atoms_n": "{n} 原子 | {name}",
        "loaded_complex": "已载入复合物: {name} ({n} 原子)\n",
        "parse_fail": "解析复合物失败: {e}\n{tb}\n",
        "grp_settings": "分析设置",
        "grid": "网格精度",
        "grp_run": "运行",
        "run_btn": "◆  开始 ETS-NOCV 分析",
        "stop": "■  停止",
        "grp_visual": "可视化（左侧 OpenGL 画布）",
        "iso": "等值面", "opacity": "不透明度",
        "pos_phase": "正相位", "neg_phase": "负相位",
        "refresh": "刷新画布",
        "col_idx": "编号", "col_pair": "ΔE_pair",
        "col_orb_p": "轨道(+)", "col_eig_p": "本征值(+)", "col_e_p": "能量(+)",
        "col_orb_m": "轨道(-)", "col_eig_m": "本征值(-)", "col_e_m": "能量(-)",
        "error": "错误", "hint": "提示", "export_fail": "导出失败",
        "need_mw": "请先在主窗口 ⚙️ 路径设置中配置 Multiwfn！",
        "need_complex": "请先选择复合物 fchk！",
        "need_frags": "请先选择碎片 1 和碎片 2 的 fchk！",
        "sel_row": "请先在表格中选中要可视化的行。",
        "no_session": "无活动的 Multiwfn 会话，请重新运行 ETS-NOCV 分析。",
        "run_start": "开始 ETS-NOCV 分析...\n",
        "tmp_dir": "临时目录: {d}\n",
        "run_fail": "启动分析失败: {e}\n{tb}\n",
        "stopped": "已请求停止...\n",
        "setup_done_log": "分析完成，日志已保存: {p}\n",
        "parsed_n": "解析到 {n} 个 NOCV 对。\n",
        "parsed_none": "未解析到 NOCV 对表，请检查输出日志。\n",
        "select_hint": "提示: 选中表格中的行，点击『可视化选中对』。\n",
        "gen_cube": "生成 NOCV 对密度 cube（{name}）...\n",
        "cube_cached": "显示缓存 cube: {name}\n",
        "cube_done": "cube 已生成: {name}\n",
        "cube_fail": "cube 生成失败: {err}\n",
        "csv_name": "NOCV_table.csv", "dlg_csv": "导出 NOCV 表",
        "exported": "NOCV 表已导出: {p}\n",
        "refresh_canvas": "已刷新左侧画布（可用主窗口『同步到 VMD』导出）。\n",
        "dlg_complex": "选择复合物 fchk", "dlg_frag1": "选择碎片 1 fchk",
        "dlg_frag2": "选择碎片 2 fchk",
        "gjf_title": "生成 Gaussian 输入 (.gjf)",
    },
    "en": {
        "nocv_head": "NOCV Results (select rows, then click Visualize to render)",
        "visualize": "Visualize Selected",
        "export_csv": "Export CSV",
        "grp_files": "Files (Complex + Two Fragments)",
        "complex": "Complex",
        "frag1": "Frag 1", "frag2": "Frag 2",
        "ph_complex": "*.fchk (leave empty to reuse main-window file)",
        "ph_fchk": "*.fchk",
        "browse": "Browse",
        "flip1": "Flip spin of Frag 1", "flip2": "Flip spin of Frag 2",
        "gen_gjf": "Generate Gaussian Input (.gjf)",
        "no_complex": "No complex loaded",
        "atoms_n": "{n} atoms | {name}",
        "loaded_complex": "Complex loaded: {name} ({n} atoms)\n",
        "parse_fail": "Failed to parse complex: {e}\n{tb}\n",
        "grp_settings": "Analysis Settings",
        "grid": "Grid quality",
        "grp_run": "Run",
        "run_btn": "◆  Start ETS-NOCV Analysis",
        "stop": "■  Stop",
        "grp_visual": "Visualization (left OpenGL canvas)",
        "iso": "Isosurface", "opacity": "Opacity",
        "pos_phase": "Pos phase", "neg_phase": "Neg phase",
        "refresh": "Refresh Canvas",
        "col_idx": "Pair", "col_pair": "ΔE_pair",
        "col_orb_p": "Orb(+)", "col_eig_p": "Eigen(+)", "col_e_p": "E(+)",
        "col_orb_m": "Orb(-)", "col_eig_m": "Eigen(-)", "col_e_m": "E(-)",
        "error": "Error", "hint": "Notice", "export_fail": "Export Failed",
        "need_mw": "Configure Multiwfn in ⚙️ Path Settings (main window) first!",
        "need_complex": "Select the complex .fchk first!",
        "need_frags": "Select .fchk files for both fragments first!",
        "sel_row": "Select rows in the table to visualize first.",
        "no_session": "No active Multiwfn session — run the ETS-NOCV analysis again.",
        "run_start": "Starting ETS-NOCV analysis...\n",
        "tmp_dir": "Temp dir: {d}\n",
        "run_fail": "Failed to start analysis: {e}\n{tb}\n",
        "stopped": "Stop requested...\n",
        "setup_done_log": "Analysis done, log saved: {p}\n",
        "parsed_n": "Parsed {n} NOCV pairs.\n",
        "parsed_none": "No NOCV pair table parsed — check the Multiwfn output.\n",
        "select_hint": "Tip: select rows in the table, then click Visualize.\n",
        "gen_cube": "Generating NOCV pair density cube ({name})...\n",
        "cube_cached": "Showing cached cube: {name}\n",
        "cube_done": "Cube generated: {name}\n",
        "cube_fail": "Cube generation failed: {err}\n",
        "csv_name": "NOCV_table.csv", "dlg_csv": "Export NOCV Table",
        "exported": "NOCV table exported: {p}\n",
        "refresh_canvas": "Canvas refreshed (use main-window 'Sync to VMD' to export).\n",
        "dlg_complex": "Select complex .fchk", "dlg_frag1": "Select fragment 1 .fchk",
        "dlg_frag2": "Select fragment 2 .fchk",
        "gjf_title": "Generate Gaussian Input (.gjf)",
    },
}


# 默认相位色（NOCV 约定：正=蓝=电子聚集，负=红=电子耗尽），来自 blue-red 样式
_STYLE0 = NOCV_STYLES.get("blue-red", {})
_DEF_POS = tuple(int(c * 255) for c in _STYLE0.get("pos_color", [0.05, 0.35, 0.8])[1:])
_DEF_NEG = tuple(int(c * 255) for c in _STYLE0.get("neg_color", [0.9, 0.25, 0.25])[1:])


def _safe_ascii_tmp_dir(prefix="ets_nocv_"):
    """创建 Multiwfn 可写的工作目录。

    Multiwfn（Fortran）无法读写含非 ASCII 字符（中文用户名等）的路径，
    而系统临时目录在中文 Windows 上常见于 C:\\Users\\<中文名>\\AppData\\...
    因此若系统临时目录路径非纯 ASCII，回退到 exe 目录 / 盘符根目录等
    纯 ASCII 位置，保证 NOCV cube 等文件能正常生成。
    """
    def _is_ascii(p):
        try:
            p.encode("ascii")
            return True
        except UnicodeEncodeError:
            return False

    def _mk(base=None):
        if base:
            return tempfile.mkdtemp(prefix=prefix, dir=base)
        return tempfile.mkdtemp(prefix=prefix)

    # 1) 系统临时目录（最常用，路径为 ASCII 时最佳）
    try:
        d = _mk()
        if _is_ascii(d):
            return d
    except OSError:
        pass
    # 2) exe 目录（打包后）→ 3) 当前盘符根目录
    cands = []
    if getattr(sys, "frozen", False):
        cands.append(os.path.dirname(os.path.abspath(sys.executable)))
    try:
        cands.append(os.path.splitdrive(os.path.abspath(__file__))[0] + os.sep)
    except Exception:
        pass
    for base in cands:
        try:
            d = _mk(base)
            if _is_ascii(d):
                return d
        except OSError:
            continue
    # 4) 最后兜底
    return _mk()


class ETSNOCVPanel(QWidget):
    def __init__(self, glw=None, multiwfn_path="", get_fchk=None,
                 get_multiwfn=None, log_func=None, parent=None,
                 get_vmd=None, get_tachyon=None):
        super().__init__(parent)
        self.lang = "zh"
        self.glw = glw
        self.multiwfn_path = multiwfn_path
        self.get_fchk = get_fchk or (lambda: "")
        self.get_multiwfn = get_multiwfn or (lambda: "")
        self.get_vmd = get_vmd or (lambda: "")
        self.get_tachyon = get_tachyon or (lambda: "")
        self._log_func = log_func

        self.fchk_complex = ""
        self.fchk_frag1 = ""
        self.fchk_frag2 = ""
        self.frag1_open_shell = False
        self.frag2_open_shell = False
        self.current_atoms = []
        self._mwfn_session = None
        self._tmp_dir = None
        self._work_dir = None
        self._archive_dir = None   # 结果归档目录 <复合物目录>/<stem>_NOCV
        self._calc_worker = None
        self._cube_gen_worker = None
        self._calculating = False
        self._is_generating_cube = False
        self._nocv_rows = []
        self._cub_files = {}
        self._current_cube = None
        self._row_labels = {}    # i18n：行标签引用（var_name -> QLabel）
        self._browse_btns = []   # i18n：三个浏览按钮引用
        self._iso_val = 0.003
        self._opacity = 0.75
        self._pos_rgb = _DEF_POS
        self._neg_rgb = _DEF_NEG

        self._build_ui()

        cur = self.get_fchk()
        if cur:
            self.txt_complex.setText(cur)
            self._load_molecule(cur)

    def showEvent(self, event):
        """切到本 tab 时回填主窗口已载入的复合物 fchk 并画到画布。"""
        super().showEvent(event)
        cur = self.get_fchk()
        if cur:
            if not self.txt_complex.text().strip():
                self.txt_complex.setText(cur)
            if not self.current_atoms:
                self._load_molecule(cur)

    # ── i18n ──
    def _t(self, key, **fmt):
        s = _ETS_TR.get(self.lang, {}).get(key, key)
        return s.format(**fmt) if fmt else s

    def set_lang(self, lang):
        """主窗口切换语言时调用（"zh"/"en"）。"""
        if lang not in ("zh", "en"):
            lang = "zh"
        self.lang = lang
        self._apply_lang()

    def _apply_lang(self):
        """刷新常驻控件文本（运行时消息每次构造时走 _t()）。"""
        self.lbl_nocv_head.setText(self._t("nocv_head"))
        self.btn_visualize.setText(self._t("visualize"))
        self.btn_export.setText(self._t("export_csv"))
        self.grp_files.setTitle(self._t("grp_files"))
        self._row_labels["txt_complex"].setText(self._t("complex"))
        self._row_labels["txt_frag1"].setText(self._t("frag1"))
        self._row_labels["txt_frag2"].setText(self._t("frag2"))
        self.txt_complex.setPlaceholderText(self._t("ph_complex"))
        self.txt_frag1.setPlaceholderText(self._t("ph_fchk"))
        self.txt_frag2.setPlaceholderText(self._t("ph_fchk"))
        self.chk_flip_frag1.setText(self._t("flip1"))
        self.chk_flip_frag2.setText(self._t("flip2"))
        self.btn_gjf.setText(self._t("gen_gjf"))
        self.lbl_grid.setText(self._t("grid"))
        self.grp_run.setTitle(self._t("grp_run"))
        self.btn_run.setText(self._t("run_btn"))
        self.btn_stop.setText(self._t("stop"))
        self.grp_visual.setTitle(self._t("grp_visual"))
        self.lbl_iso.setText(self._t("iso"))
        self.lbl_op.setText(self._t("opacity"))
        self.lbl_pos_phase.setText(self._t("pos_phase"))
        self.lbl_neg_phase.setText(self._t("neg_phase"))
        self.btn_refresh.setText(self._t("refresh"))
        self.table_nocv.setHorizontalHeaderLabels([
            self._t("col_idx"), self._t("col_pair"),
            self._t("col_orb_p"), self._t("col_eig_p"), self._t("col_e_p"),
            self._t("col_orb_m"), self._t("col_eig_m"), self._t("col_e_m")])
        if not self.current_atoms:
            self.lbl_hint.setText(self._t("no_complex"))
        # 浏览按钮按新语言文字重新定宽（QSS padding 6px 16px）
        for b in self._browse_btns:
            b.setText(self._t("browse"))
            b.setFixedWidth(b.fontMetrics().horizontalAdvance(b.text()) + 40)

    # ── UI ──
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        root.addWidget(self._grp_files())
        root.addWidget(self._grp_run())
        root.addWidget(self._grp_visual())

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.hide()
        root.addWidget(self.progress_bar)

        # NOCV 结果卡片：圆角矩形包裹「标题标签 + 结果表格 + 可视化/导出行」，
        # 表格随窗口高度自适应伸缩（原固定最大高度 200px 改为最小高度并拉伸）。
        card = QFrame()
        card.setObjectName("NocvCard")
        card.setStyleSheet("""
            QFrame#NocvCard {
                background-color: #FFFFFF;
                border: 1px solid #D7E1EC;
                border-radius: 10px;
            }
            QLabel#NocvChip {
                background-color: #1565C0;
                color: #FFFFFF;
                border-radius: 4px;
                padding: 2px 14px;
                font-weight: bold;
                font-size: 9pt;
            }
            QTableWidget#NocvTable {
                border: 1px solid #CBD5E1;
                border-radius: 6px;
            }
        """)
        card_l = QVBoxLayout(card)
        card_l.setContentsMargins(12, 10, 12, 10)
        card_l.setSpacing(8)

        self.lbl_nocv_head = QLabel(self._t("nocv_head"))
        self.lbl_nocv_head.setObjectName("NocvChip")
        self.lbl_nocv_head.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        card_l.addWidget(self.lbl_nocv_head, 0, Qt.AlignLeft)

        self.table_nocv = self._build_table()
        self.table_nocv.setObjectName("NocvTable")
        card_l.addWidget(self.table_nocv, 1)

        row_btn = QHBoxLayout()
        self.btn_visualize = QPushButton(self._t("visualize"))
        self.btn_visualize.setEnabled(False)
        self.btn_visualize.clicked.connect(self._visualize_selected)
        self.btn_export = QPushButton(self._t("export_csv"))
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._export_table)
        row_btn.addWidget(self.btn_visualize)
        row_btn.addWidget(self.btn_export)
        row_btn.addStretch()
        card_l.addLayout(row_btn)

        root.addWidget(card, 1)

    def _row(self, label, var_name, browse_slot, placeholder):
        row = QHBoxLayout()
        lab = QLabel(label)
        lab.setMinimumWidth(64)
        self._row_labels[var_name] = lab
        le = QLineEdit()
        le.setPlaceholderText(placeholder)
        setattr(self, var_name, le)
        btn = QPushButton(self._t("browse"))
        self._browse_btns.append(btn)
        # QSS 的 QPushButton 是 padding: 6px 16px + 1px 边框（左右共 34px），
        # 旧的 setMaximumWidth(56) 只给文字剩 22px，「浏览」会被截断。
        # 按字体实际宽度算出固定宽（+40 = padding 34 + 余量 6），
        # 三行按钮文字相同 → 计算结果一致，天然对齐。
        btn.setFixedWidth(btn.fontMetrics().horizontalAdvance(btn.text()) + 40)
        btn.clicked.connect(browse_slot)
        row.addWidget(lab)
        row.addWidget(le, 1)
        row.addWidget(btn)
        return row

    def _grp_files(self):
        self.grp_files = QGroupBox(self._t("grp_files"))
        grp = self.grp_files
        l = QVBoxLayout(grp)
        l.setSpacing(6)
        l.addLayout(self._row(self._t("complex"), "txt_complex",
                              self._browse_complex, self._t("ph_complex")))
        l.addLayout(self._row(self._t("frag1"), "txt_frag1",
                              self._browse_frag1, self._t("ph_fchk")))
        l.addLayout(self._row(self._t("frag2"), "txt_frag2",
                              self._browse_frag2, self._t("ph_fchk")))

        row = QHBoxLayout()
        self.chk_flip_frag1 = QCheckBox(self._t("flip1"))
        self.chk_flip_frag2 = QCheckBox(self._t("flip2"))
        self.chk_flip_frag1.setVisible(False)
        self.chk_flip_frag2.setVisible(False)
        row.addWidget(self.chk_flip_frag1)
        row.addWidget(self.chk_flip_frag2)
        row.addStretch()
        self.btn_gjf = QPushButton(self._t("gen_gjf"))
        self.btn_gjf.clicked.connect(self._open_gjf_generator)
        row.addWidget(self.btn_gjf)
        l.addLayout(row)

        self.lbl_hint = QLabel(self._t("no_complex"))
        l.addWidget(self.lbl_hint)
        return grp

    def _grp_run(self):
        self.grp_run = QGroupBox(self._t("grp_run"))
        grp = self.grp_run
        l = QHBoxLayout(grp)
        l.setSpacing(8)
        # 网格精度（原「分析设置」组）与运行按钮合并为一组
        self.lbl_grid = QLabel(self._t("grid"))
        l.addWidget(self.lbl_grid)
        self.combo_grid = QComboBox()
        for i in range(1, 6):
            self.combo_grid.addItem(str(i))
        self.combo_grid.setCurrentIndex(2)   # 默认 3
        l.addWidget(self.combo_grid)
        l.addSpacing(12)
        self.btn_run = QPushButton(self._t("run_btn"))
        self.btn_run.setMinimumWidth(170)
        self.btn_run.clicked.connect(self._run_analysis)
        l.addWidget(self.btn_run)
        self.btn_stop = QPushButton(self._t("stop"))
        self.btn_stop.setEnabled(False)
        self.btn_stop.setMinimumWidth(90)
        self.btn_stop.clicked.connect(self._stop_analysis)
        l.addWidget(self.btn_stop)
        l.addStretch()
        return grp

    def _grp_visual(self):
        self.grp_visual = QGroupBox(self._t("grp_visual"))
        grp = self.grp_visual
        # 三行合并为一行：等值面 / 不透明度 / 正负相位色块 / 刷新画布
        l = QHBoxLayout(grp)
        l.setSpacing(6)

        self.lbl_iso = QLabel(self._t("iso"))
        l.addWidget(self.lbl_iso)
        self.sld_iso = QSlider(Qt.Horizontal)
        self.sld_iso.setRange(1, 100)          # 0.001 .. 0.100
        self.sld_iso.setValue(3)               # 默认 0.003
        self.sld_iso.setMinimumWidth(60)
        self.sld_iso.valueChanged.connect(self._on_iso_slider)
        l.addWidget(self.sld_iso, 1)
        self.edit_iso = QLineEdit("0.003")
        self.edit_iso.setValidator(QDoubleValidator(0.0001, 1.0, 4))
        self.edit_iso.setMaximumWidth(70)
        self.edit_iso.returnPressed.connect(self._on_iso_edit)
        l.addWidget(self.edit_iso)

        self.lbl_op = QLabel(self._t("opacity"))
        l.addWidget(self.lbl_op)
        self.sld_op = QSlider(Qt.Horizontal)
        self.sld_op.setRange(5, 100)           # 0.05 .. 1.00
        self.sld_op.setValue(75)
        self.sld_op.setMinimumWidth(60)
        self.sld_op.valueChanged.connect(self._on_op_slider)
        self.lbl_op_val = QLabel("0.75")
        self.lbl_op_val.setMinimumWidth(44)
        l.addWidget(self.sld_op, 1)
        l.addWidget(self.lbl_op_val)

        self.lbl_pos_phase = QLabel(self._t("pos_phase"))
        l.addWidget(self.lbl_pos_phase)
        self.btn_pos = QPushButton("")
        self.btn_pos.setFixedSize(24, 24)
        self.btn_pos.setToolTip(self._t("pos_phase"))
        self.btn_pos.clicked.connect(lambda: self._pick_color("pos"))
        l.addWidget(self.btn_pos)
        self.lbl_neg_phase = QLabel(self._t("neg_phase"))
        l.addWidget(self.lbl_neg_phase)
        self.btn_neg = QPushButton("")
        self.btn_neg.setFixedSize(24, 24)
        self.btn_neg.setToolTip(self._t("neg_phase"))
        self.btn_neg.clicked.connect(lambda: self._pick_color("neg"))
        l.addWidget(self.btn_neg)
        self.btn_refresh = QPushButton(self._t("refresh"))
        self.btn_refresh.clicked.connect(self._apply_glw)
        l.addWidget(self.btn_refresh)

        self._update_color_buttons()
        return grp

    def _build_table(self):
        t = QTableWidget(0, 8)
        t.setHorizontalHeaderLabels(
            [self._t("col_idx"), self._t("col_pair"),
             self._t("col_orb_p"), self._t("col_eig_p"), self._t("col_e_p"),
             self._t("col_orb_m"), self._t("col_eig_m"), self._t("col_e_m")])
        t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setMinimumHeight(200)   # 原为 setMaximumHeight(200)：改为最小高度，随卡片/窗口自适应拉伸
        return t

    # ── 日志（统一转发到主窗口「运行日志」tab）──
    def _append_log(self, msg):
        if self._log_func:
            try:
                self._log_func(msg)
            except Exception:
                pass

    # ── 浏览 / 载入 ──
    def _browse_complex(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self._t("dlg_complex"), "",
            "格式化 Checkpoint (*.fchk);;所有文件 (*.*)")
        if path:
            self.txt_complex.setText(path)
            self._load_molecule(path)

    def _browse_frag1(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self._t("dlg_frag1"), "", "格式化 Checkpoint (*.fchk);;所有文件 (*.*)")
        if path:
            self.txt_frag1.setText(path)
            self.fchk_frag1 = path
            ab = read_fch_alpha_beta(path)
            self.frag1_open_shell = ab is not None and ab[0] != ab[1]
            self._update_spin_flip_ui()

    def _browse_frag2(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self._t("dlg_frag2"), "", "格式化 Checkpoint (*.fchk);;所有文件 (*.*)")
        if path:
            self.txt_frag2.setText(path)
            self.fchk_frag2 = path
            ab = read_fch_alpha_beta(path)
            self.frag2_open_shell = ab is not None and ab[0] != ab[1]
            self._update_spin_flip_ui()

    def _update_spin_flip_ui(self):
        """仅对开壳层碎片显示『翻转自旋』勾选（对齐原程序：闭壳层不送答案）。"""
        self.chk_flip_frag1.setVisible(self.frag1_open_shell)
        self.chk_flip_frag2.setVisible(self.frag2_open_shell)
        if self.frag1_open_shell:
            self.chk_flip_frag1.setChecked(False)
        if self.frag2_open_shell:
            self.chk_flip_frag2.setChecked(False)

    def _build_spin_answers(self):
        """只对开壳层碎片追加翻转答案；全闭壳层返回 None（不污染菜单流）。"""
        answers = []
        if self.frag1_open_shell:
            answers.append(self.chk_flip_frag1.isChecked())
        if self.frag2_open_shell:
            answers.append(self.chk_flip_frag2.isChecked())
        return answers if answers else None

    def _load_molecule(self, path):
        if not path or not os.path.isfile(path):
            return
        try:
            atoms = get_atoms_from_fchk(path)
            if not atoms:
                return
            self.fchk_complex = path
            self.current_atoms = atoms
            self.lbl_hint.setText(self._t(
                "atoms_n", n=len(atoms), name=os.path.basename(path)))
            self._append_log(self._t(
                "loaded_complex", name=os.path.basename(path), n=len(atoms)))
            if self.glw is not None:
                self.glw.set_molecule(atoms)
                try:
                    self.glw.frame_to_molecule()
                except Exception:
                    pass
        except Exception as e:
            self._append_log(self._t(
                "parse_fail", e=e, tb=traceback.format_exc()))

    def _open_gjf_generator(self):
        dlg = QDialog(self)
        dlg.setWindowTitle(self._t("gjf_title"))
        dlg.resize(1200, 760)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        w = GjfGeneratorWidget(L=get_locale(self.lang),
                               last_dir=self._work_dir or os.path.expanduser("~"))
        lay.addWidget(w)
        dlg.exec_()

    # ── 运行 ──
    def _resolve_complex(self):
        p = self.txt_complex.text().strip()
        if not p:
            p = self.get_fchk()
        return p

    def _run_analysis(self):
        if self._calculating:
            return
        exe = self.get_multiwfn() or self.multiwfn_path
        if not exe or not os.path.exists(exe):
            QMessageBox.warning(self, self._t("error"), self._t("need_mw"))
            return
        comp = self._resolve_complex()
        f1 = self.txt_frag1.text().strip()
        f2 = self.txt_frag2.text().strip()
        if not comp or not os.path.exists(comp):
            QMessageBox.warning(self, self._t("error"), self._t("need_complex"))
            return
        if not f1 or not f2 or not os.path.exists(f1) or not os.path.exists(f2):
            QMessageBox.warning(self, self._t("error"), self._t("need_frags"))
            return

        self.fchk_complex = comp
        self.fchk_frag1 = f1
        self.fchk_frag2 = f2
        if not self.current_atoms:
            self._load_molecule(comp)

        self._grid_quality = self.combo_grid.currentIndex() + 1
        self._work_dir = os.path.dirname(os.path.abspath(comp))
        # 结果归档目录（同 ESP 的 <stem>_ESP 惯例）：
        # ets_nocv_output.txt / NOCVpair cube / CSV 默认导出都放这里，不散在复合物目录
        stem = os.path.splitext(os.path.basename(comp))[0]
        self._archive_dir = os.path.join(self._work_dir, f"{stem}_NOCV")
        os.makedirs(self._archive_dir, exist_ok=True)
        self._tmp_dir = _safe_ascii_tmp_dir("ets_nocv_")
        os.makedirs(self._tmp_dir, exist_ok=True)

        for src in (comp, f1, f2):
            dst = os.path.join(self._tmp_dir, os.path.basename(src))
            if not os.path.exists(dst):
                shutil.copy2(src, dst)

        # 若上一 cube 生成线程仍在运行，先终止再关会话，
        # 避免 QThread 销毁时仍在运行导致 Qt 致命崩溃（0xC0000409）
        self._stop_cube_worker()
        if self._mwfn_session is not None:
            self._mwfn_session.shutdown()
            self._mwfn_session = None
        self._cub_files = {}
        self._current_cube = None

        spin_answers = self._build_spin_answers()

        self._calculating = True
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress_bar.show()
        self._append_log(self._t("run_start"))
        self._append_log(self._t("tmp_dir", d=self._tmp_dir))

        try:
            self._calc_worker = SetupWorker(
                exe,
                os.path.join(self._tmp_dir, os.path.basename(comp)),
                os.path.join(self._tmp_dir, os.path.basename(f1)),
                os.path.join(self._tmp_dir, os.path.basename(f2)),
                spin_answers, self._tmp_dir, self)
            self._calc_worker.finished.connect(self._on_setup_done)
            self._calc_worker.log.connect(lambda m: self._append_log(m + "\n"))
            self._calc_worker.start()
        except Exception as e:
            self._calculating = False
            self.progress_bar.hide()
            self.btn_run.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self._append_log(self._t(
                "run_fail", e=e, tb=traceback.format_exc()))

    def _stop_analysis(self):
        self._append_log(self._t("stopped"))
        self._stop_cube_worker()
        if self._calc_worker is not None:
            try:
                self._calc_worker.stop()
            except Exception:
                pass
        if self._mwfn_session is not None:
            self._mwfn_session.shutdown()
            self._mwfn_session = None
        self.btn_stop.setEnabled(False)

    def _on_setup_done(self, output, session, error):
        self._calculating = False
        self.progress_bar.hide()
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)

        self._mwfn_session = session if (session is not None and session.is_alive()) else None

        if error or output is None:
            self._append_log(f"ETS-NOCV analysis failed: {error}\n")
            return

        log_path = os.path.join(self._archive_dir or self._work_dir, "ets_nocv_output.txt")
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(output)
            self._append_log(self._t("setup_done_log", p=log_path))
        except Exception:
            pass

        header, rows, table_str = parse_nocv_table(output)
        self._append_log(table_str + "\n")
        if rows:
            self._nocv_rows = rows
            self._populate_table(rows)
            self.btn_visualize.setEnabled(True)
            self.btn_export.setEnabled(True)
            self._append_log(self._t("parsed_n", n=len(rows)))
            self._append_log(self._t("select_hint"))
        else:
            self._append_log(self._t("parsed_none"))

    def _populate_table(self, rows):
        t = self.table_nocv
        t.setRowCount(len(rows))
        has_spin = any(r.get('spin', 'Total') != 'Total' for r in rows)
        for r_idx, r in enumerate(rows):
            spin_tag = r.get('spin', 'Total')
            prefix = f"[{spin_tag[0]}] " if has_spin else ""
            items = [prefix + str(r['pair']), f"{r['pair_energy']:.2f}",
                     str(r['de_orbital']), f"{r['de_eigen']:.5f}", f"{r['de_energy']:.2f}",
                     str(r['dk_orbital']), f"{r['dk_eigen']:.5f}", f"{r['dk_energy']:.2f}"]
            for c_idx, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                t.setItem(r_idx, c_idx, item)

    def _export_table(self):
        if not self._nocv_rows:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, self._t("dlg_csv"),
            os.path.join(self._archive_dir or self._work_dir or "", self._t("csv_name")),
            "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            has_spin = any(r.get('spin', 'Total') != 'Total' for r in self._nocv_rows)
            cols = []
            if has_spin:
                cols.append("Spin")
            cols += [self._t("col_idx"), self._t("col_pair"),
                     self._t("col_orb_p"), self._t("col_eig_p"), self._t("col_e_p"),
                     self._t("col_orb_m"), self._t("col_eig_m"), self._t("col_e_m")]
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f)
                w.writerow(cols)
                for r in self._nocv_rows:
                    row = []
                    if has_spin:
                        row.append(r.get('spin', 'Total'))
                    row += [r['pair'], f"{r['pair_energy']:.2f}",
                            r['de_orbital'], f"{r['de_eigen']:.5f}", f"{r['de_energy']:.2f}",
                            r['dk_orbital'], f"{r['dk_eigen']:.5f}", f"{r['dk_energy']:.2f}"]
                    w.writerow(row)
            self._append_log(self._t("exported", p=path))
        except Exception as e:
            QMessageBox.warning(self, self._t("export_fail"), str(e))

    # ── cube 生成 + 可视化 ──
    def _stop_cube_worker(self):
        """终止仍在运行的 cube 生成线程（避免 QThread 销毁时仍在运行）。"""
        w = getattr(self, "_cube_gen_worker", None)
        if w is not None and w.isRunning():
            try:
                w.terminate()
                w.wait(3000)
            except Exception:
                pass

    def _visualize_selected(self):
        selected = set(i.row() for i in self.table_nocv.selectionModel().selectedRows())
        if not selected:
            QMessageBox.information(self, self._t("hint"), self._t("sel_row"))
            return
        if self._is_generating_cube:
            return
        if self._mwfn_session is None or not self._mwfn_session.is_alive():
            QMessageBox.warning(self, self._t("hint"), self._t("no_session"))
            return

        pair_nums = sorted(set(self._nocv_rows[r]['pair'] for r in selected
                               if r < len(self._nocv_rows)))
        if not pair_nums:
            return

        if len(pair_nums) == 1:
            pair_selector = str(pair_nums[0])
            cub_name = f"NOCVpair_{pair_nums[0]}.cub"
            spin = self._nocv_rows[min(selected)].get('spin', 'Total')
            if spin == 'Alpha':
                cub_name = f"NOCVpair_A{pair_nums[0]}.cub"
            elif spin == 'Beta':
                cub_name = f"NOCVpair_B{pair_nums[0]}.cub"
        else:
            pair_selector = self._build_pair_selector(pair_nums)
            cub_name = f"NOCVpair_{pair_selector.replace(',', '_').replace('-', 'to')}.cub"

        # 已缓存 → 直接显示
        cub = self._cub_files.get(cub_name)
        if cub and os.path.exists(cub):
            self._current_cube = cub
            self._apply_glw()
            self._append_log(self._t("cube_cached", name=cub_name))
            return

        self._is_generating_cube = True
        self.btn_visualize.setEnabled(False)
        self._append_log(self._t("gen_cube", name=cub_name))
        # 终止上一个 worker（若仍在运行），再启动新的
        self._stop_cube_worker()
        self._cube_gen_worker = CubeGenWorker(
            self._mwfn_session, pair_selector,
            self._grid_quality,
            cub_name, self._tmp_dir, self)
        self._cube_gen_worker.finished.connect(self._on_cube_ready)
        self._cube_gen_worker.error.connect(self._on_cube_error)
        self._cube_gen_worker.log.connect(lambda m: self._append_log(m + "\n"))
        self._cube_gen_worker.start()

    @staticmethod
    def _build_pair_selector(pair_nums):
        nums = sorted(set(pair_nums))
        if not nums:
            return ""
        parts = []
        start = prev = nums[0]
        for n in nums[1:]:
            if n == prev + 1:
                prev = n
                continue
            parts.append(f"{start}-{prev}" if prev > start else str(start))
            start = prev = n
        parts.append(f"{start}-{prev}" if prev > start else str(start))
        return ",".join(parts)

    def _on_cube_ready(self, cub_path, pair_selector, output_delta=""):
        if not self._is_generating_cube:
            return
        self._is_generating_cube = False
        self.btn_visualize.setEnabled(True)

        cub_name = os.path.basename(cub_path)
        dst = os.path.join(self._archive_dir or self._work_dir, cub_name)
        try:
            shutil.copy2(cub_path, dst)
        except (shutil.SameFileError, PermissionError):
            pass
        self._cub_files[cub_name] = dst
        self._current_cube = dst
        self._append_log(self._t("cube_done", name=cub_name))
        if output_delta:
            log_path = os.path.join(self._archive_dir or self._work_dir,
                                    "ets_nocv_output.txt")
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write("\n" + "#" * 60 + f"\n# Cube output (pair {pair_selector})\n"
                            + "#" * 60 + "\n\n" + output_delta)
            except Exception:
                pass
        self._apply_glw()

    def _on_cube_error(self, err, pair_selector):
        self._is_generating_cube = False
        self.btn_visualize.setEnabled(True)
        self._append_log(self._t("cube_fail", err=err))

    # ── glw 可视化 ──
    def _apply_glw(self):
        if self.glw is None:
            return
        if self.current_atoms:
            self.glw.set_molecule(self.current_atoms)
        self.glw.set_phase_colors(self._pos_rgb, self._neg_rgb)
        if self._current_cube and os.path.exists(self._current_cube):
            self.glw.load(self._current_cube, self._iso_val)
        self.glw.set_opacity(self._opacity)
        if self._current_cube:
            self.glw.set_vmd_scene([
                {"type": "orbital", "vol": self._current_cube, "iso": self._iso_val}])
        self._append_log(self._t("refresh_canvas"))

    def _on_iso_slider(self, v):
        self._iso_val = v / 1000.0
        self.edit_iso.setText(f"{self._iso_val:.3f}")
        if self.glw is not None and self._current_cube:
            self.glw.set_isovalue(self._iso_val)
            self.glw.set_vmd_scene([
                {"type": "orbital", "vol": self._current_cube, "iso": self._iso_val}])

    def _on_iso_edit(self):
        try:
            v = float(self.edit_iso.text().strip())
        except ValueError:
            return
        self._iso_val = v
        self.sld_iso.blockSignals(True)
        self.sld_iso.setValue(int(v * 1000))
        self.sld_iso.blockSignals(False)
        if self.glw is not None and self._current_cube:
            self.glw.set_isovalue(v)
            self.glw.set_vmd_scene([
                {"type": "orbital", "vol": self._current_cube, "iso": v}])

    def _on_op_slider(self, v):
        self._opacity = v / 100.0
        self.lbl_op_val.setText(f"{self._opacity:.2f}")
        if self.glw is not None:
            self.glw.set_opacity(self._opacity)

    def _pick_color(self, phase):
        cur = QColor(*self._pos_rgb) if phase == "pos" else QColor(*self._neg_rgb)
        col = QColorDialog.getColor(cur, self, "选择颜色")
        if not col.isValid():
            return
        rgb = (col.red(), col.green(), col.blue())
        if phase == "pos":
            self._pos_rgb = rgb
        else:
            self._neg_rgb = rgb
        self._update_color_buttons()
        if self.glw is not None:
            self.glw.set_phase_colors(self._pos_rgb, self._neg_rgb)

    def _update_color_buttons(self):
        self.btn_pos.setStyleSheet(
            f"background:rgb({self._pos_rgb[0]},{self._pos_rgb[1]},{self._pos_rgb[2]});"
            f"border:1px solid #555; border-radius:12px;")
        self.btn_neg.setStyleSheet(
            f"background:rgb({self._neg_rgb[0]},{self._neg_rgb[1]},{self._neg_rgb[2]});"
            f"border:1px solid #555; border-radius:12px;")

    def shutdown(self):
        """主窗口关闭时调用：终止后台线程并关闭 Multiwfn 会话。

        必须在线程仍在运行时显式 terminate+wait，否则 Python 退出时
        QThread 被直接销毁 → Qt 致命错误（0xC0000409）崩溃。
        """
        self._stop_cube_worker()
        w = getattr(self, "_calc_worker", None)
        if w is not None and w.isRunning():
            try:
                w.stop()
                w.wait(3000)
            except Exception:
                pass
        sess = getattr(self, "_mwfn_session", None)
        if sess is not None:
            try:
                sess.shutdown()
            except Exception:
                pass
            self._mwfn_session = None
