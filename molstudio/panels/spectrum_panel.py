# -*- coding: utf-8 -*-
"""MolStudio's one-click molecular spectrum workflow panel."""

from __future__ import annotations

import os

from PyQt5.QtCore import QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
    QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QSpinBox, QVBoxLayout, QWidget,
)

from molstudio.core.spectra import (
    SPECTRUM_KINDS,
    SpectrumCancelled,
    run_spectrum_pipeline,
)
from molstudio.panels.etsnocv.molcanvas import (
    get_atoms_from_any,
    get_bonds_from_fchk,
)
from molstudio.render.molcanvas import (
    get_atoms_from_cube,
    get_atoms_from_fchk,
)


TEXT = {
    "zh": {
        "title": "分子光谱 · 一键计算",
        "intro": (
            "导入分子结构后，MolStudio 会按所选谱型生成 Gaussian 任务，"
            "计算结束后自动调用 Multiwfn 展宽并绘制光谱。"
        ),
        "structure": "1  分子结构",
        "load": "导入分子…",
        "current": "使用当前画布",
        "source": "结构文件",
        "placeholder": "支持 .xyz / .gjf / .com / .log / .out / .fchk / .fch",
        "not_loaded": "尚未载入分子",
        "loaded": "已载入 {n} 个原子 · {name}",
        "calc": "2  计算设置",
        "kind": "光谱类型",
        "theory": "方法与基组",
        "solvent": "溶剂（可选）",
        "charge": "电荷",
        "multiplicity": "自旋多重度",
        "nstates": "激发态数量",
        "optimize": "优化基态几何",
        "optimize_tip": (
            "吸收谱先优化 S0；荧光随后优化 S1；磷光随后优化 T1。"
            "振动谱则生成 Opt + Freq 任务。"),
        "reuse": "复用已有 Gaussian 输出",
        "reuse_tip": "不重新运行 Gaussian，只调用 Multiwfn 绘图。",
        "resources": "资源（核数 / 内存）",
        "nproc": "核",
        "wavelengths": "ROA 波长",
        "wavelength_hint": "例如 532nm 或 450nm 532nm 600nm",
        "roa_index": "绘图波长序号",
        "ecd_rep": "ECD 转子强度",
        "ecd_velocity": "速度表象（推荐）",
        "ecd_length": "长度表象",
        "fwhm": "FWHM",
        "scale": "频率因子",
        "xrange": "横轴范围",
        "xrange_hint": "例如 200,3800,200",
        "output": "3  输出与运行",
        "outdir": "输出目录",
        "browse": "选择…",
        "run": "一键计算并绘制光谱",
        "stop": "停止",
        "open": "打开输出目录",
        "ready": "就绪：导入分子后点击一键计算。",
        "plot": "4  光谱图预览",
        "none": "计算完成后在这里预览光谱（图表会自动填满整个预览区）",
        "plot_hint": "双击图像可放大查看 · 可另存为高清 PNG",
        "zoom": "放大查看",
        "save_plot": "保存图片",
        "zoom_title": "光谱图 · 放大查看",
        "zoom_hint": "原始尺寸显示，可拖动滚动条查看细节；也可以用「适应窗口」快速浏览",
        "fit": "适应窗口",
        "actual": "原始大小",
        "close": "关闭",
        "warning": "提示",
        "need_structure": "请先导入分子结构，或先在主画布载入结构。",
        "need_paths": "请先在主窗口 ⚙️ 路径设置中配置 Gaussian 和 Multiwfn。",
        "working": "光谱工作流运行中…",
        "failed": "光谱计算失败",
        "done": "光谱计算完成",
        "emission_line": "发射能：{ev:.4f} eV（{nm:.2f} nm）",
        "emission_normalized": "磷光强度未考虑 SOC，曲线已归一化",
        "dark_emission": "S1 振子强度为 0：该跃迁很弱，谱图为暗态结果",
        "cancel": "正在停止…",
        "outputs": "输出文件：{dir}",
        "roa_need": "ROA 需要至少一个入射波长，例如 532nm。",
        "kind_desc": {
            "uvvis": "TDDFT/TDA 电子激发 → Gaussian 展宽 → UV-Vis 吸收光谱",
            "ecd": "TDDFT/TDA 的转子强度 → ECD 谱（默认速度表象）",
            "fluorescence": (
                "可选 S0 优化 → S1 几何优化 → Multiwfn 只保留 S1 振子强度，"
                "绘制 S1→S0 垂直荧光发射谱"),
            "phosphorescence": (
                "可选 S0 优化 → T1 几何优化 → T1 位置三重态 TD。普通 TDDFT "
                "不含 SOC，因此谱带位置可信、强度按归一化显示；T1 固定按三重态处理"),
            "ir": "Opt + Freq → 红外振动光谱",
            "raman": "Opt + Freq=Raman → 拉曼光谱",
            "vcd": "Opt + Freq=VCD → 振动圆二色谱",
            "roa": "Opt + Freq=ROA + 入射波长 → 拉曼光学活性光谱",
        },
    },
    "en": {
        "title": "Molecular spectra · One-click workflow",
        "intro": (
            "Import a structure to generate a Gaussian spectrum job. "
            "MolStudio then calls Multiwfn to broaden and plot the spectrum."
        ),
        "structure": "1  Molecular structure",
        "load": "Import molecule…",
        "current": "Use current canvas",
        "source": "Structure file",
        "placeholder": ".xyz / .gjf / .com / .log / .out / .fchk / .fch",
        "not_loaded": "No molecule loaded",
        "loaded": "{n} atoms loaded · {name}",
        "calc": "2  Calculation",
        "kind": "Spectrum",
        "theory": "Method / basis",
        "solvent": "Solvent (optional)",
        "charge": "Charge",
        "multiplicity": "Multiplicity",
        "nstates": "Excited states",
        "optimize": "Optimise ground state",
        "optimize_tip": (
            "Absorption pre-optimises S0; fluorescence then optimises S1; "
            "phosphorescence then optimises T1. Vibrational jobs use Opt + Freq."),
        "reuse": "Reuse Gaussian output",
        "reuse_tip": "Skip Gaussian and run Multiwfn only.",
        "resources": "Processors / memory",
        "nproc": "cores",
        "wavelengths": "ROA wavelength",
        "wavelength_hint": "e.g. 532nm or 450nm 532nm 600nm",
        "roa_index": "Plot wavelength #",
        "ecd_rep": "ECD rotatory strength",
        "ecd_velocity": "Velocity (recommended)",
        "ecd_length": "Length",
        "fwhm": "FWHM",
        "scale": "X scale",
        "xrange": "X range",
        "xrange_hint": "e.g. 200,3800,200",
        "output": "3  Output and run",
        "outdir": "Output directory",
        "browse": "Browse…",
        "run": "Calculate and plot spectrum",
        "stop": "Stop",
        "open": "Open output folder",
        "ready": "Ready: import a molecule, then run the workflow.",
        "plot": "4  Spectrum preview",
        "none": "The spectrum preview appears here after the workflow "
                "(the plot fills the whole preview area)",
        "plot_hint": "Double-click the plot to zoom · export a high-resolution PNG",
        "zoom": "Zoom",
        "save_plot": "Save PNG",
        "zoom_title": "Spectrum · zoomed view",
        "zoom_hint": "Shown at native size; scroll to inspect details, "
                     "or use Fit to window",
        "fit": "Fit to window",
        "actual": "Actual size",
        "close": "Close",
        "warning": "Notice",
        "need_structure": "Import a molecular structure first.",
        "need_paths": "Configure Gaussian and Multiwfn in ⚙️ Path Settings.",
        "working": "Spectrum workflow is running…",
        "failed": "Spectrum calculation failed",
        "done": "Spectrum calculation complete",
        "emission_line": "Emission energy: {ev:.4f} eV ({nm:.2f} nm)",
        "emission_normalized": (
            "Phosphorescence intensity excludes SOC; curve is normalised"),
        "dark_emission": (
            "The S1 oscillator strength is 0; this is a weak/dark transition."),
        "cancel": "Stopping…",
        "outputs": "Outputs: {dir}",
        "roa_need": "ROA requires at least one incident wavelength, e.g. 532nm.",
        "kind_desc": {
            "uvvis": "TDDFT/TDA excited states → broadened UV-Vis absorption spectrum",
            "ecd": "TDDFT/TDA rotatory strengths → ECD spectrum (velocity representation)",
            "fluorescence": (
                "Optional S0 optimisation → S1 geometry → Multiwfn keeps only "
                "the S1 oscillator strength for vertical S1→S0 emission"),
            "phosphorescence": (
                "Optional S0 optimisation → T1 geometry → triplet TD at T1. "
                "Band position is physical; intensity is normalised because "
                "plain TDDFT has no SOC. T1 is treated as a triplet by default."),
            "ir": "Opt + Freq → infrared vibrational spectrum",
            "raman": "Opt + Freq=Raman → Raman spectrum",
            "vcd": "Opt + Freq=VCD → vibrational circular dichroism",
            "roa": "Opt + Freq=ROA + wavelengths → Raman optical activity",
        },
    },
}


class _ParamScroll(QScrollArea):
    """Scrollable settings area with a *bounded* size hint.

    ``PagedScrollArea`` sizes every right-hand page to ``max(viewport,
    page.sizeHint())``.  A plain QVBoxLayout containing all the spectrum
    settings has a ~1360px size hint on a 1080px screen, so the page was
    always taller than the window and the plot was pushed off-screen.  Giving
    the settings their own scroll area with a bounded hint keeps the whole
    page within one viewport; the plot then receives all remaining height.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setStyleSheet("QScrollArea{background:transparent;border:none;}")

    def sizeHint(self):
        return QSize(760, 420)

    def minimumSizeHint(self):
        # QVBoxLayout shrinks the stretch=0 item down to its minimum when the
        # page is tight.  Keeping this too small leaves only one settings row
        # visible (and makes the wheel hit the combo box instead of scrolling).
        return QSize(320, 340)


class SpectrumPlotView(QLabel):
    """Scalable spectrum preview.

    Previously the PNG was scaled once to a hard-coded 1000x620 and shown in a
    330px-high label, so the chart stayed small even on a tall panel.  This
    view keeps the original pixmap and re-fits it whenever the panel resizes.
    """

    zoomRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source = QPixmap()
        self._path = ""
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(360)
        self._set_empty_style()

    def _set_empty_style(self):
        self.setStyleSheet(
            "background:#F8FAFC;border:1px dashed #CBD5E1;"
            "border-radius:8px;color:#64748B;font-size:13px;")

    def set_empty(self, text):
        self._source = QPixmap()
        self._path = ""
        super().setPixmap(QPixmap())
        self.setText(text)
        self._set_empty_style()

    def has_plot(self):
        return not self._source.isNull()

    def source(self):
        return self._source

    def path(self):
        return self._path

    def set_plot(self, path):
        pix = QPixmap(str(path or ""))
        if pix.isNull():
            return False
        self._source = pix
        self._path = str(path)
        self.setStyleSheet(
            "background:white;border:1px solid #E2E8F0;border-radius:8px;")
        self._fit()
        return True

    def sizeHint(self):
        return QSize(900, 380)

    def minimumSizeHint(self):
        return QSize(320, 300)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.has_plot():
            self._fit()

    def _fit(self):
        if self._source.isNull():
            return
        rect = self.contentsRect()
        target = QSize(max(1, rect.width() - 12),
                       max(1, rect.height() - 12))
        scaled = self._source.scaled(
            target, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        super().setPixmap(scaled)

    def mouseDoubleClickEvent(self, event):
        if self.has_plot():
            self.zoomRequested.emit()
        super().mouseDoubleClickEvent(event)


class SpectrumWorker(QThread):
    stage = pyqtSignal(int, str)
    log = pyqtSignal(str)
    completed = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, kwargs, parent=None):
        super().__init__(parent)
        self.kwargs = kwargs
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True

    def _cancelled(self):
        return self._stop_requested

    def run(self):
        try:
            result = run_spectrum_pipeline(
                on_stage=lambda pct, text: self.stage.emit(int(pct), text),
                on_log=self.log.emit,
                cancel=self._cancelled,
                **self.kwargs)
            self.completed.emit(result)
        except SpectrumCancelled as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class SpectrumPanel(QWidget):
    """Structure import, Gaussian spectrum job and Multiwfn plotting UI."""

    _THEORIES = (
        "B3LYP/6-31G(d)",
        "PBE0/def2SVP",
        "PBE0/def2TZVP",
        "CAM-B3LYP/6-31G(d)",
        "WB97XD/def2TZVP",
    )
    _KIND_LABELS_ZH = {
        "fluorescence": "荧光",
        "phosphorescence": "磷光",
    }

    def __init__(self, get_structure=None, get_multiwfn=None, get_g16=None,
                 on_structure_loaded=None, log_func=None, parent=None):
        super().__init__(parent)
        self._get_structure = get_structure or (lambda: ([], []))
        self._get_multiwfn = get_multiwfn or (lambda: "")
        self._get_g16 = get_g16 or (lambda: "")
        self._on_structure_loaded = on_structure_loaded
        self._log_func = log_func or (lambda _s: None)
        self._atoms = []
        self._bonds = []
        self._source_path = ""
        self._output_dir = ""
        self._worker = None
        self._lang = "zh"
        self._last_result = None
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self._build_ui()
        self._apply_lang()
        self._on_kind_changed()

    def _t(self, key):
        return TEXT[self._lang].get(key, key)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        title = QLabel()
        title.setObjectName("SpectrumTitle")
        title.setStyleSheet(
            "font-size:18px;font-weight:700;color:#0D47A1;")
        self.lbl_title = title
        root.addWidget(title)
        self.lbl_intro = QLabel()
        self.lbl_intro.setWordWrap(True)
        self.lbl_intro.setStyleSheet("color:#475569;")
        root.addWidget(self.lbl_intro)

        # Settings live in their own scroll area so the preview never gets
        # pushed below the fold.  The plot group takes the remaining height.
        self.param_scroll = _ParamScroll()
        self.param_content = QWidget()
        self.param_content.setStyleSheet("background:transparent;")
        param_l = QVBoxLayout(self.param_content)
        param_l.setContentsMargins(0, 2, 6, 0)
        param_l.setSpacing(8)

        self.grp_structure = QGroupBox()
        sg = QVBoxLayout(self.grp_structure)
        sg.setContentsMargins(10, 12, 10, 10)
        row = QHBoxLayout()
        self.lbl_source = QLabel()
        self.edit_source = QLineEdit()
        self.edit_source.setReadOnly(True)
        self.btn_load = QPushButton()
        self.btn_load.clicked.connect(self._open_structure)
        self.btn_current = QPushButton()
        self.btn_current.clicked.connect(self._use_canvas)
        row.addWidget(self.lbl_source)
        row.addWidget(self.edit_source, 1)
        row.addWidget(self.btn_load)
        row.addWidget(self.btn_current)
        sg.addLayout(row)
        self.lbl_structure = QLabel()
        self.lbl_structure.setStyleSheet("color:#64748B;")
        sg.addWidget(self.lbl_structure)
        param_l.addWidget(self.grp_structure)

        self.grp_calc = QGroupBox()
        form = QFormLayout(self.grp_calc)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setContentsMargins(10, 12, 10, 10)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(7)

        self.cmb_kind = QComboBox()
        for key, kind in SPECTRUM_KINDS.items():
            self.cmb_kind.addItem(kind.name, key)
        self.cmb_kind.currentIndexChanged.connect(self._on_kind_changed)
        self.lbl_kind = QLabel()
        form.addRow(self.lbl_kind, self.cmb_kind)
        self.lbl_kind_desc = QLabel()
        self.lbl_kind_desc.setWordWrap(True)
        self.lbl_kind_desc.setStyleSheet("color:#64748B;")
        form.addRow("", self.lbl_kind_desc)

        self.cmb_theory = QComboBox()
        self.cmb_theory.setEditable(True)
        self.cmb_theory.setMinimumContentsLength(8)
        self.cmb_theory.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_theory.setMinimumWidth(0)
        self.cmb_theory.addItems(self._THEORIES)
        self.lbl_theory = QLabel()
        form.addRow(self.lbl_theory, self.cmb_theory)

        self.cmb_solvent = QComboBox()
        self.cmb_solvent.addItem("None", "")
        for name in ("Water", "Methanol", "Ethanol", "Acetonitrile",
                     "Chloroform", "Toluene", "DimethylSulfoxide"):
            self.cmb_solvent.addItem(name, name)
        self.lbl_solvent = QLabel()
        form.addRow(self.lbl_solvent, self.cmb_solvent)

        state_row = QWidget()
        state_l = QHBoxLayout(state_row)
        state_l.setContentsMargins(0, 0, 0, 0)
        self.lbl_charge = QLabel()
        self.spin_charge = QSpinBox()
        self.spin_charge.setRange(-20, 20)
        self.lbl_multiplicity = QLabel()
        self.spin_mult = QSpinBox()
        self.spin_mult.setRange(1, 12)
        state_l.addWidget(self.lbl_charge)
        state_l.addWidget(self.spin_charge)
        state_l.addSpacing(8)
        state_l.addWidget(self.lbl_multiplicity)
        state_l.addWidget(self.spin_mult)
        state_l.addStretch(1)
        self.lbl_state = QLabel()
        form.addRow(self.lbl_state, state_row)

        self.spin_nstates = QSpinBox()
        self.spin_nstates.setRange(1, 300)
        self.spin_nstates.setValue(20)
        self.lbl_nstates = QLabel()
        form.addRow(self.lbl_nstates, self.spin_nstates)

        self.chk_optimize = QCheckBox()
        self.chk_optimize.setChecked(True)
        self.chk_optimize.setToolTip(self._t("optimize_tip"))
        self.lbl_optimize = QLabel()
        form.addRow(self.lbl_optimize, self.chk_optimize)

        self.chk_reuse = QCheckBox()
        self.chk_reuse.setEnabled(False)
        self.chk_reuse.setToolTip(self._t("reuse_tip"))
        self.chk_reuse.toggled.connect(self._update_controls)
        self.lbl_reuse = QLabel()
        form.addRow(self.lbl_reuse, self.chk_reuse)

        res_row = QWidget()
        res_l = QHBoxLayout(res_row)
        res_l.setContentsMargins(0, 0, 0, 0)
        self.spin_nproc = QSpinBox()
        self.spin_nproc.setRange(1, 256)
        self.spin_nproc.setValue(8)
        self.lbl_nproc = QLabel()
        self.edit_mem = QLineEdit("8GB")
        self.edit_mem.setMaximumWidth(110)
        res_l.addWidget(self.spin_nproc)
        res_l.addWidget(self.lbl_nproc)
        res_l.addSpacing(8)
        res_l.addWidget(self.edit_mem)
        res_l.addStretch(1)
        self.lbl_resources = QLabel()
        form.addRow(self.lbl_resources, res_row)

        self.edit_wavelengths = QLineEdit("532nm")
        self.lbl_wavelengths = QLabel()
        roa_row = QWidget()
        self.roa_row = roa_row
        roa_l = QHBoxLayout(roa_row)
        roa_l.setContentsMargins(0, 0, 0, 0)
        self.spin_roa_index = QSpinBox()
        self.spin_roa_index.setRange(1, 20)
        self.lbl_roa_index = QLabel()
        roa_l.addWidget(self.edit_wavelengths, 1)
        roa_l.addWidget(self.lbl_roa_index)
        roa_l.addWidget(self.spin_roa_index)
        form.addRow(self.lbl_wavelengths, roa_row)

        self.cmb_ecd_rep = QComboBox()
        self.cmb_ecd_rep.addItem("", "velocity")
        self.cmb_ecd_rep.addItem("", "length")
        self.lbl_ecd_rep = QLabel()
        form.addRow(self.lbl_ecd_rep, self.cmb_ecd_rep)

        adv = QGridLayout()
        adv.setHorizontalSpacing(8)
        self.lbl_fwhm = QLabel()
        self.edit_fwhm = QLineEdit()
        self.edit_fwhm.setPlaceholderText("auto")
        self.lbl_scale = QLabel()
        self.spin_scale = QDoubleSpinBox()
        self.spin_scale.setRange(0.5, 2.0)
        self.spin_scale.setDecimals(5)
        self.spin_scale.setSingleStep(0.0001)
        self.spin_scale.setValue(0.9614)
        self.lbl_xrange = QLabel()
        self.edit_xrange = QLineEdit()
        adv.addWidget(self.lbl_fwhm, 0, 0)
        adv.addWidget(self.edit_fwhm, 0, 1)
        adv.addWidget(self.lbl_scale, 0, 2)
        adv.addWidget(self.spin_scale, 0, 3)
        adv.addWidget(self.lbl_xrange, 1, 0)
        adv.addWidget(self.edit_xrange, 1, 1, 1, 3)
        adv.setColumnStretch(1, 1)
        adv.setColumnStretch(3, 1)
        form.addRow("", adv)
        param_l.addWidget(self.grp_calc)

        self.grp_output = QGroupBox()
        out_l = QVBoxLayout(self.grp_output)
        out_l.setContentsMargins(10, 12, 10, 10)
        out_row = QHBoxLayout()
        self.lbl_outdir = QLabel()
        self.edit_outdir = QLineEdit()
        self.btn_outdir = QPushButton()
        self.btn_outdir.clicked.connect(self._browse_output)
        out_row.addWidget(self.lbl_outdir)
        out_row.addWidget(self.edit_outdir, 1)
        out_row.addWidget(self.btn_outdir)
        out_l.addLayout(out_row)
        action_row = QHBoxLayout()
        self.btn_run = QPushButton()
        self.btn_run.setObjectName("PrimaryBtn")
        self.btn_run.setMinimumHeight(40)
        self.btn_run.clicked.connect(self._start)
        self.btn_stop = QPushButton()
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop)
        self.btn_open = QPushButton()
        self.btn_open.setEnabled(False)
        self.btn_open.clicked.connect(self._open_output)
        action_row.addWidget(self.btn_run, 2)
        action_row.addWidget(self.btn_stop)
        action_row.addWidget(self.btn_open)
        out_l.addLayout(action_row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        out_l.addWidget(self.progress)
        self.lbl_status = QLabel()
        self.lbl_status.setWordWrap(True)
        out_l.addWidget(self.lbl_status)
        self.param_scroll.setWidget(self.param_content)
        root.addWidget(self.param_scroll, 0)
        # Step 3 stays outside the scroll area: the primary "run" button and
        # progress must always be visible, even when settings are scrolled.
        root.addWidget(self.grp_output)

        self.grp_plot = QGroupBox()
        plot_l = QVBoxLayout(self.grp_plot)
        plot_l.setContentsMargins(12, 14, 12, 12)
        plot_l.setSpacing(8)
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.lbl_plot_hint = QLabel()
        self.lbl_plot_hint.setStyleSheet("color:#64748B;")
        bar.addWidget(self.lbl_plot_hint, 1)
        self.btn_zoom = QPushButton()
        self.btn_zoom.setEnabled(False)
        self.btn_zoom.clicked.connect(self._zoom_plot)
        self.btn_save_plot = QPushButton()
        self.btn_save_plot.setEnabled(False)
        self.btn_save_plot.clicked.connect(self._save_plot)
        for btn in (self.btn_zoom, self.btn_save_plot):
            btn.setStyleSheet(
                "QPushButton{padding:5px 12px;border:1px solid #CBD5E1;"
                "border-radius:6px;background:#FFFFFF;color:#334155;}"
                "QPushButton:hover{background:#EFF6FF;border-color:#93C5FD;}"
                "QPushButton:disabled{color:#94A3B8;background:#F8FAFC;}")
        bar.addWidget(self.btn_zoom)
        bar.addWidget(self.btn_save_plot)
        plot_l.addLayout(bar)
        self.plot_view = SpectrumPlotView()
        self.plot_view.zoomRequested.connect(self._zoom_plot)
        plot_l.addWidget(self.plot_view, 1)
        # The stretch goes to the preview itself.  PagedScrollArea stretches
        # each page to the viewport height, so the chart now grows with the
        # window instead of staying at a fixed 330px label.
        root.addWidget(self.grp_plot, 1)

        self._advanced_widgets = [
            self.edit_fwhm, self.spin_scale, self.edit_xrange]

    def _apply_lang(self):
        t = self._t
        for index in range(self.cmb_kind.count()):
            key = self.cmb_kind.itemData(index)
            kind = SPECTRUM_KINDS[key]
            label = (self._KIND_LABELS_ZH.get(key, kind.name)
                     if self._lang == "zh"
                     else kind.name.split(" / ", 1)[0])
            self.cmb_kind.setItemText(index, label)
        self.lbl_title.setText(t("title"))
        self.lbl_intro.setText(t("intro"))
        self.grp_structure.setTitle(t("structure"))
        self.lbl_source.setText(t("source"))
        self.edit_source.setPlaceholderText(t("placeholder"))
        self.btn_load.setText(t("load"))
        self.btn_current.setText(t("current"))
        self.grp_calc.setTitle(t("calc"))
        self.lbl_kind.setText(t("kind"))
        self.lbl_theory.setText(t("theory"))
        self.lbl_solvent.setText(t("solvent"))
        self.lbl_charge.setText(t("charge"))
        self.lbl_multiplicity.setText(t("multiplicity"))
        self.lbl_state.setText("")
        self.lbl_nstates.setText(t("nstates"))
        self.lbl_optimize.setText("")
        self.chk_optimize.setText(t("optimize"))
        self.chk_optimize.setToolTip(t("optimize_tip"))
        self.lbl_reuse.setText("")
        self.chk_reuse.setText(t("reuse"))
        self.chk_reuse.setToolTip(t("reuse_tip"))
        self.lbl_resources.setText(t("resources"))
        self.lbl_nproc.setText(t("nproc"))
        self.lbl_wavelengths.setText(t("wavelengths"))
        self.edit_wavelengths.setPlaceholderText(t("wavelength_hint"))
        self.lbl_roa_index.setText(t("roa_index"))
        self.spin_roa_index.setToolTip(t("roa_index"))
        self.lbl_ecd_rep.setText(t("ecd_rep"))
        self.cmb_ecd_rep.setItemText(0, t("ecd_velocity"))
        self.cmb_ecd_rep.setItemText(1, t("ecd_length"))
        self.lbl_fwhm.setText(t("fwhm"))
        self.lbl_scale.setText(t("scale"))
        self.lbl_xrange.setText(t("xrange"))
        self.edit_xrange.setPlaceholderText(t("xrange_hint"))
        self.grp_output.setTitle(t("output"))
        self.lbl_outdir.setText(t("outdir"))
        self.btn_outdir.setText(t("browse"))
        self.btn_run.setText(t("run"))
        self.btn_stop.setText(t("stop"))
        self.btn_open.setText(t("open"))
        self.grp_plot.setTitle(t("plot"))
        self.btn_zoom.setText(t("zoom"))
        self.btn_save_plot.setText(t("save_plot"))
        if not self.plot_view.has_plot():
            self.plot_view.set_empty(t("none"))
        self.lbl_plot_hint.setText(
            t("plot_hint") if self.plot_view.has_plot() else "")
        if not self._atoms:
            self.lbl_structure.setText(t("not_loaded"))
        else:
            self.lbl_structure.setText(t("loaded").format(
                n=len(self._atoms),
                name=os.path.basename(self._source_path) or "canvas"))
        if self.progress.value() == 0 and self._worker is None:
            self.lbl_status.setText(t("ready"))
        self._on_kind_changed()

    def set_lang(self, lang):
        self._lang = "en" if lang == "en" else "zh"
        self._apply_lang()

    def _on_kind_changed(self, *_args):
        key = self.cmb_kind.currentData()
        if not key:
            return
        kind = SPECTRUM_KINDS[key]
        desc = TEXT[self._lang]["kind_desc"].get(key, "")
        self.lbl_kind_desc.setText(desc)
        self.spin_nstates.setEnabled(kind.electronic)
        is_roa = key == "roa"
        self.lbl_wavelengths.setVisible(is_roa)
        self.roa_row.setVisible(is_roa)
        self.edit_wavelengths.setEnabled(is_roa)
        self.spin_roa_index.setEnabled(is_roa)
        self.lbl_ecd_rep.setVisible(key == "ecd")
        self.cmb_ecd_rep.setVisible(key == "ecd")
        self.cmb_ecd_rep.setEnabled(key == "ecd")
        for widget in self._advanced_widgets:
            widget.setEnabled(True)
        if kind.electronic:
            self.spin_scale.setEnabled(False)
        self._update_controls()

    def _update_controls(self):
        key = self.cmb_kind.currentData()
        if not key:
            return
        kind = SPECTRUM_KINDS[key]
        reuse = bool(self.chk_reuse.isChecked())
        # Vibrational jobs also legitimately support either Opt+Freq (from a
        # raw structure) or Freq only (from an already optimised geometry).
        self.chk_optimize.setEnabled(not reuse)
        self.cmb_theory.setEnabled(not reuse)
        self.cmb_solvent.setEnabled(not reuse)
        self.spin_nproc.setEnabled(not reuse)
        self.edit_mem.setEnabled(not reuse)
        self.spin_nstates.setEnabled(not reuse and kind.electronic)

    @staticmethod
    def _parse_structure(path):
        ext = os.path.splitext(path)[1].lower()
        if ext in (".fchk", ".fch"):
            atoms = get_atoms_from_fchk(path)
        elif ext in (".cub", ".cube"):
            atoms = get_atoms_from_cube(path)
        else:
            atoms = get_atoms_from_any(path)
        if not atoms:
            raise ValueError("文件中未找到可用的三维原子坐标")
        bonds = get_bonds_from_fchk(atoms)
        return atoms, bonds

    def _set_structure(self, atoms, bonds, path=""):
        if not atoms:
            raise ValueError("没有可用的分子结构")
        self._atoms = list(atoms)
        self._bonds = list(bonds or [])
        self._source_path = path or ""
        self.edit_source.setText(path or "canvas")
        self.chk_reuse.setEnabled(
            bool(path) and os.path.splitext(path)[1].lower() in
            (".log", ".out"))
        if not self.chk_reuse.isEnabled():
            self.chk_reuse.setChecked(False)
        if path and not self.edit_outdir.text().strip():
            self.edit_outdir.setText(os.path.dirname(os.path.abspath(path)))
        self._output_dir = self.edit_outdir.text().strip()
        self._apply_lang()
        if self._on_structure_loaded:
            try:
                self._on_structure_loaded(self._atoms, self._bonds, path)
            except Exception as exc:  # noqa: BLE001
                self._log_func("画布同步失败：%s" % exc)

    def _open_structure(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self._t("load"), "",
            "Molecule (*.xyz *.gjf *.com *.log *.out *.fchk *.fch);;"
            "All files (*.*)")
        if not path:
            return
        try:
            atoms, bonds = self._parse_structure(path)
            self._set_structure(atoms, bonds, path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, self._t("warning"), str(exc))

    def _use_canvas(self):
        try:
            atoms, bonds = self._get_structure()
            if not atoms:
                raise ValueError(self._t("need_structure"))
            current_path = ""
            parent = self.parent()
            while parent is not None and not hasattr(parent, "var_path"):
                parent = parent.parent()
            if parent is not None:
                current_path = parent.var_path.text().strip()
            self._set_structure(atoms, bonds, current_path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, self._t("warning"), str(exc))

    def _browse_output(self):
        path = QFileDialog.getExistingDirectory(
            self, self._t("outdir"), self.edit_outdir.text().strip())
        if path:
            self.edit_outdir.setText(path)
            self._output_dir = path

    def _start(self):
        if self._worker is not None and self._worker.isRunning():
            return
        if not self._atoms:
            QMessageBox.warning(self, self._t("warning"),
                                self._t("need_structure"))
            return
        key = self.cmb_kind.currentData()
        mw = (self._get_multiwfn() or "").strip()
        g16 = (self._get_g16() or "").strip()
        reuse = self.chk_reuse.isChecked()
        if not mw or not os.path.isfile(mw):
            QMessageBox.warning(self, self._t("warning"),
                                self._t("need_paths"))
            return
        if not reuse and (not g16 or not os.path.isfile(g16)):
            QMessageBox.warning(self, self._t("warning"),
                                self._t("need_paths"))
            return
        if key == "roa" and not self.edit_wavelengths.text().strip():
            QMessageBox.warning(self, self._t("warning"),
                                self._t("roa_need"))
            return
        outdir = self.edit_outdir.text().strip()
        if not outdir:
            source_dir = (os.path.dirname(os.path.abspath(self._source_path))
                          if self._source_path else os.getcwd())
            outdir = source_dir
            self.edit_outdir.setText(outdir)
        try:
            os.makedirs(outdir, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, self._t("warning"), str(exc))
            return

        theory = self.cmb_theory.currentText().strip()
        kwargs = {
            "atoms": self._atoms,
            "source_name": os.path.basename(self._source_path) or
                           "molstudio_molecule",
            "output_dir": outdir,
            "kind_key": key,
            "theory": theory,
            "gaussian_exe": g16,
            "multiwfn_exe": mw,
            "charge": self.spin_charge.value(),
            "multiplicity": self.spin_mult.value(),
            "nstates": self.spin_nstates.value(),
            "nprocshared": self.spin_nproc.value(),
            "mem": self.edit_mem.text().strip(),
            "optimize": self.chk_optimize.isChecked(),
            "solvent": self.cmb_solvent.currentData() or "",
            "wavelengths": self.edit_wavelengths.text().strip(),
            "fwhm": self.edit_fwhm.text().strip() or None,
            "frequency_scale": self.spin_scale.value(),
            "x_range": self.edit_xrange.text().strip(),
            "ecd_representation": self.cmb_ecd_rep.currentData(),
            "roa_wavelength_index": self.spin_roa_index.value(),
            "existing_log": (self._source_path if reuse else ""),
        }
        self._worker = SpectrumWorker(kwargs, self)
        self._worker.stage.connect(self._on_stage)
        self._worker.log.connect(self._on_log)
        self._worker.completed.connect(self._on_completed)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_worker_finished)
        self._set_running(True)
        self.progress.setValue(0)
        self.lbl_status.setText(self._t("working"))
        self._worker.start()

    def _set_running(self, running):
        self.btn_run.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.btn_load.setEnabled(not running)
        self.btn_current.setEnabled(not running)
        self.cmb_kind.setEnabled(not running)

    def _stop(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.stop()
            self.lbl_status.setText(self._t("cancel"))

    def _on_stage(self, pct, text):
        self.progress.setValue(max(0, min(100, int(pct))))
        self.lbl_status.setText(text)

    def _on_log(self, text):
        self._log_func(text)

    def _on_completed(self, result):
        self._last_result = result
        path = result.get("plot_path", "")
        if path and self.plot_view.set_plot(path):
            self.btn_zoom.setEnabled(True)
            self.btn_save_plot.setEnabled(True)
            self.lbl_plot_hint.setText(self._t("plot_hint"))
        self.progress.setValue(100)
        status_lines = [
            self._t("done"),
            self._t("outputs").format(dir=result.get("output_dir", "")),
        ]
        emission = result.get("emission")
        if emission:
            status_lines.insert(1, self._t("emission_line").format(
                ev=emission["ev"], nm=emission["nm"]))
            if result.get("normalized"):
                status_lines.insert(2, self._t("emission_normalized"))
            elif (result.get("kind") == "fluorescence"
                  and abs(emission.get("oscillator_strength", 0.0)) <= 1e-8):
                status_lines.insert(2, self._t("dark_emission"))
        self.lbl_status.setText("\n".join(status_lines))
        self.btn_open.setEnabled(True)
        self._log_func("MolStudio 光谱输出：%s" % path)

    def _zoom_plot(self):
        """Open the full-resolution plot in a scrollable dialog."""
        if not self.plot_view.has_plot():
            return
        source = self.plot_view.source()
        dlg = QDialog(self)
        dlg.setWindowTitle(self._t("zoom_title"))
        dlg.resize(1500, 980)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)
        hint = QLabel(self._t("zoom_hint"))
        hint.setStyleSheet("color:#64748B;")
        lay.addWidget(hint)
        scroll = QScrollArea(dlg)
        scroll.setWidgetResizable(False)
        scroll.setAlignment(Qt.AlignCenter)
        scroll.setStyleSheet(
            "background:#F1F5F9;border:1px solid #E2E8F0;border-radius:8px;")
        view = QLabel()
        view.setAlignment(Qt.AlignCenter)
        view.setPixmap(source)
        scroll.setWidget(view)
        lay.addWidget(scroll, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        btn_fit = QPushButton(self._t("fit"))
        btn_actual = QPushButton(self._t("actual"))
        btn_close = QPushButton(self._t("close"))
        row.addWidget(btn_fit)
        row.addWidget(btn_actual)
        row.addWidget(btn_close)
        lay.addLayout(row)

        def show_scaled(scale_to_view):
            target = scroll.viewport().size()
            # Before the dialog is mapped, viewport() is still a tiny
            # placeholder (about 100x30).  Scaling the 1872x1053 PNG into
            # that produced an essentially empty pixmap and a blank dialog.
            if target.width() < 200 or target.height() < 200:
                target = QSize(dlg.width() - 40, dlg.height() - 120)
            pix = (source.scaled(target, Qt.KeepAspectRatio,
                                 Qt.SmoothTransformation)
                   if scale_to_view else source)
            view.setPixmap(pix)
            view.adjustSize()

        btn_fit.clicked.connect(lambda: show_scaled(True))
        btn_actual.clicked.connect(lambda: show_scaled(False))
        btn_close.clicked.connect(dlg.reject)
        # exec_() shows and lays out the dialog; fit on the first turn of its
        # event loop, when viewport() finally carries the real geometry.
        QTimer.singleShot(0, lambda: show_scaled(True))
        dlg.exec_()

    def _save_plot(self):
        """Export the currently displayed plot as a high-resolution PNG."""
        if not self.plot_view.has_plot():
            return
        dest, _filter = QFileDialog.getSaveFileName(
            self, self._t("save_plot"),
            self.plot_view.path() or "spectrum.png",
            "PNG image (*.png);;All files (*.*)")
        if dest:
            self.plot_view.source().save(dest, "PNG")

    def _on_failed(self, message):
        self.progress.setValue(0)
        self.lbl_status.setText(self._t("failed"))
        QMessageBox.warning(self, self._t("failed"), message)
        self._log_func("[spectrum] %s" % message)

    def _on_worker_finished(self):
        self._set_running(False)
        self._worker = None
        self._update_controls()

    def _open_output(self):
        path = ""
        if self._last_result:
            path = self._last_result.get("output_dir", "")
        path = path or self.edit_outdir.text().strip()
        if path and os.path.isdir(path):
            os.startfile(path)

    def shutdown(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(5000)


__all__ = ["SpectrumPanel", "SpectrumWorker"]
