"""
main_window: 主窗口
GXNU MolStudio — PyQt5 主界面，分子可视化与量子化学分析。
"""

import os
import sys
import glob
import subprocess
import socket
import shutil

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGroupBox, QLabel, QLineEdit, QPushButton, QRadioButton, QCheckBox,
    QComboBox, QTextEdit, QFileDialog, QMessageBox, QButtonGroup,
    QFrame, QSplitter, QSplitterHandle, QScrollArea, QGridLayout, QSizePolicy,
    QSlider, QTabWidget, QDialog, QDialogButtonBox, QFormLayout,
    QTextBrowser, QTableWidget, QTableWidgetItem, QHeaderView,
    QToolButton, QListWidget, QStackedWidget, QAbstractItemView,
    QInputDialog, QDoubleSpinBox,
)
from PyQt5 import QtCore
from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PyQt5.QtGui import (
    QFont, QColor, QPalette, QFontDatabase, QTextCursor, QTextCharFormat,
    QKeySequence, QLinearGradient, QRadialGradient, QBrush, QPainter, QPen,
    QPainterPath, QPixmap, QIcon, QDoubleValidator,
)

# ── Backend imports ──
import fchk_orbital as backend
from fchk_orbital import find_tachyon
import orbital_viewer_lib as ovlib
from file_dialogs import open_file, existing_directory
from molcanvas import (
    MolCanvas, get_atoms_from_fchk, get_bonds_from_fchk,
    get_atoms_from_cube, get_bonds_from_cube, ELEMENT_SYMBOLS,
)

# 元素符号 → 原子序数（XYZ 解析用）。符号按首字母大写归一化，
# 便于处理 "C"/"cl"/"CL" 等写法；查不到时回退 0。
_SYMBOL_TO_AN = {sym: an for an, sym in ELEMENT_SYMBOLS.items()}

# ── OpenGL 渲染器（替代 VMD 预览） ──
try:
    from orbital_gl_viewer import OrbitalGLViewer
    _HAS_GL_VIEWER = True
except ImportError:
    _HAS_GL_VIEWER = False

# ── 内嵌 OpenGL cube 画布（左侧面板） ──
try:
    from ovcanvas import OVCanvas as CubCanvasPanel
    from ovcanvas import LimitedPopupComboBox
    _HAS_CUB_CANVAS = True
except Exception:
    _HAS_CUB_CANVAS = False
    LimitedPopupComboBox = QComboBox   # 画布不可用时退化为普通下拉框

# ── 原子电荷读取/分析（整合自 ChargeViewer） ──
try:
    from charge_viewer import ChargePanel, BondOrderPanel
    _HAS_CHARGE_VIEWER = True
except Exception:
    _HAS_CHARGE_VIEWER = False

# ── NBO 分析（整合自 NBOViewer） ──
try:
    from nbo_viewer import NboPanel
    _HAS_NBO_VIEWER = True
except Exception:
    _HAS_NBO_VIEWER = False

# ── ESP 表面（整合自 ESPViewer v3.0，第一步：ISO 模式） ──
try:
    from esp_panel import EspPanel
    _HAS_ESP_PANEL = True
except Exception:
    _HAS_ESP_PANEL = False

# ── IGMH/IRI 分析（整合自 IGMH_Toolbox V4） ──
try:
    from igmh_panel import IgmhPanel
    _HAS_IGMH_PANEL = True
except Exception:
    _HAS_IGMH_PANEL = False

# ── AIM 拓扑分析（移植自 AIM_Qt5_Analyzer） ──
try:
    from aim_panel import AIMPanel
    _HAS_AIM_PANEL = True
except Exception:
    _HAS_AIM_PANEL = False

# ── ETS-NOCV 分析（移植自 ETS-NOCV-Viewer） ──
try:
    from etsnocv_panel import ETSNOCVPanel
    _HAS_ETSNOCV_PANEL = True
except Exception:
    _HAS_ETSNOCV_PANEL = False

# ── MPP 分子平面性参数分析（移植自 mpp_auto_qt.py） ──
try:
    from mpp_panel import MPPPanel
    _HAS_MPP_PANEL = True
except Exception:
    _HAS_MPP_PANEL = False

# ── IRC 整合分析（整合自 D:\IRC\IRC_Integrated_Qt.py） ──
try:
    from irc_panel import IrcPanel
    _HAS_IRC_PANEL = True
except Exception:
    _HAS_IRC_PANEL = False

# ── DI 能量分解分析（整合自 D:\traetest\DI分析\di_analysis_gui.py） ──
try:
    from di_analysis_panel import DiAnalysisPanel
    _HAS_DI_PANEL = True
except Exception:
    _HAS_DI_PANEL = False

# ── Energetic Span Model 跨循环催化能量分析（整合自 energy_span_model.py） ──
try:
    from energy_span_panel import EnergySpanPanel
    _HAS_ESM_PANEL = True
except Exception:
    _HAS_ESM_PANEL = False

# ── 拆分后的模块 ──
import i18n
from theme import LIGHT_QSS
from fchk_parser import parse_fchk_mo_info
from workers import CubeWorker, RenderWorker, SpinDensityWorker
from widgets import SciFiGroupBox
from dialogs import OrbitalBrowserDialog


# 限制下拉弹出高度并严格贴合选框的组合框（实现见 ovcanvas._panel）。
# 注意：不要在 super().showPopup() 之后再改弹出窗口尺寸而不重新定位——
# Qt 是按改尺寸前的高度把弹出窗口对齐到选框边缘的，那样会导致弹出框
# 与选框之间裂开一条缝（向上弹时尤其明显）。
_PopupLimitedComboBox = LimitedPopupComboBox


class _BodySplitterHandle(QSplitterHandle):
    """分隔条：双击复位到默认栏宽。"""

    def mouseDoubleClickEvent(self, e):
        sp = self.splitter()
        reset = getattr(sp, "_reset_sizes", None)
        if reset:
            reset()
            e.accept()
            return
        super().mouseDoubleClickEvent(e)


class BodySplitter(QSplitter):
    """主分栏：拖动分隔条调整栏宽，双击分隔条复位到默认比例。

    分隔条本身由 theme.LIGHT_QSS 的 QSplitter::handle 上色（默认浅灰药丸、
    悬停变蓝），这里只负责热区宽度与双击复位。
    """

    #: 分隔条热区宽度（px）。Qt 默认约 4px 且透明，看不出能拖，加宽更好抓。
    HANDLE_WIDTH = 2

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setHandleWidth(self.HANDLE_WIDTH)
        self._default_sizes = None

    def set_default_sizes(self, sizes):
        """记录默认栏宽（setSizes 之后调用），供双击复位使用。"""
        self._default_sizes = list(sizes)

    def _reset_sizes(self):
        if self._default_sizes:
            self.setSizes(self._default_sizes)

    def createHandle(self):
        h = _BodySplitterHandle(self.orientation(), self)
        h.setToolTip("拖动调整栏宽，双击复位")
        h.setCursor(Qt.SplitHCursor if self.orientation() == Qt.Horizontal
                    else Qt.SplitVCursor)
        return h


class PathsDialog(QDialog):
    """软件路径设置对话框（Multiwfn / VMD / Tachyon + 致谢）。"""

    def __init__(self, paths, ack_html, tr, parent=None):
        super().__init__(parent)
        self._tr_fn = tr  # 供 _browse 等实例方法使用（tr 只是构造参数，方法内不可见）
        self.setWindowTitle(tr("dlg_paths_title"))
        self.resize(580, 560)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        grp = SciFiGroupBox(tr("grp_paths"))
        g = QVBoxLayout(grp)
        g.setSpacing(4)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.edit_mw = QLineEdit(paths.get("multiwfn", ""))
        self.edit_mw.setMinimumWidth(320)
        mw_row = QHBoxLayout()
        mw_row.addWidget(self.edit_mw)
        btn_mw = QPushButton(tr("btn_browse"))
        btn_mw.clicked.connect(lambda: self._browse(self.edit_mw, "multiwfn"))
        mw_row.addWidget(btn_mw)
        form.addRow(tr("lbl_multiwfn"), mw_row)

        self.edit_vmd = QLineEdit(paths.get("vmd", ""))
        self.edit_vmd.setMinimumWidth(320)
        vmd_row = QHBoxLayout()
        vmd_row.addWidget(self.edit_vmd)
        self.btn_vmd = QPushButton(tr("btn_browse"))
        self.btn_vmd.clicked.connect(lambda: self._browse(self.edit_vmd, "vmd"))
        vmd_row.addWidget(self.btn_vmd)
        form.addRow(tr("lbl_vmd"), vmd_row)

        self.edit_tachyon = QLineEdit(paths.get("tachyon", ""))
        self.edit_tachyon.setMinimumWidth(320)
        ty_row = QHBoxLayout()
        ty_row.addWidget(self.edit_tachyon)
        self.btn_ty = QPushButton(tr("btn_browse"))
        self.btn_ty.clicked.connect(lambda: self._browse(self.edit_tachyon, "tachyon"))
        ty_row.addWidget(self.btn_ty)
        form.addRow(tr("lbl_tachyon"), ty_row)

        g.addLayout(form)

        btn_save = QPushButton(tr("btn_save"))
        btn_save.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn_save.clicked.connect(self._save)
        g.addWidget(btn_save)
        root.addWidget(grp)

        grp_ack = SciFiGroupBox(tr("grp_acknowledgments"))
        al = QVBoxLayout(grp_ack)
        al.setContentsMargins(4, 4, 4, 4)
        self.tb_ack = QTextBrowser()
        self.tb_ack.setOpenExternalLinks(True)
        self.tb_ack.setStyleSheet(
            "QTextBrowser { border: none; background: transparent;"
            " font-family: 'Microsoft YaHei'; }")
        self.tb_ack.setHtml(ack_html)
        al.addWidget(self.tb_ack)
        root.addWidget(grp_ack, stretch=1)

    def _browse(self, target, which):
        path, _ = open_file(
            self, self._tr_fn("dlg_select_exe", which=which), "",
            "Executables (*.exe);;All Files (*)")
        if path:
            target.setText(path)

    def _save(self):
        """把对话框里的路径写回主窗口并保存配置。"""
        parent = self.parent()
        if parent is not None and hasattr(parent, "_do_save_paths"):
            parent._do_save_paths(
                self,
                self.edit_mw.text().strip(),
                self.edit_vmd.text().strip(),
                self.edit_tachyon.text().strip())


class DashBondDialog(QDialog):
    """弹出窗口：分子画布 + 虚线绘制控制面板"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._parent = parent
        self.setWindowTitle(parent._tr("chk_dash_mode") if parent else "虚线模式")
        self.resize(700, 650)
        self.setMinimumSize(500, 400)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 画布
        canvas_frame = QFrame()
        canvas_frame.setObjectName("ViewerFrame")
        canvas_frame.setAutoFillBackground(True)
        canvas_frame.setMinimumSize(300, 300)
        cl = QVBoxLayout(canvas_frame)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        # 复用主窗口的 MolCanvas
        self.mol_canvas = parent.mol_canvas
        cl.addWidget(self.mol_canvas, stretch=1)

        # 画布底部工具栏
        vbar = QWidget()
        vbar.setMaximumHeight(36)
        vbhl = QHBoxLayout(vbar)
        vbhl.setContentsMargins(6, 2, 6, 2)
        vbhl.setSpacing(6)
        lbl_mode = QLabel(parent._tr("lbl_label_mode") if parent else "标签")
        vbhl.addWidget(lbl_mode)
        cb_label = QComboBox()
        cb_label.addItems([
            parent._tr("label_mode_elem") if parent else "元素",
            parent._tr("label_mode_index") if parent else "序号",
            parent._tr("label_mode_none") if parent else "无",
        ])
        cb_label.setMaximumWidth(60)
        cb_label.currentIndexChanged.connect(
            lambda idx: (setattr(self.mol_canvas, 'label_mode', idx), self.mol_canvas.update())
        )
        cb_label.setCurrentIndex(1)  # 序号模式（在 connect 之后，确保初始生效）
        vbhl.addWidget(cb_label)
        vbhl.addStretch()
        btn_reset = QPushButton(parent._tr("btn_reset_view") if parent else "重置视角")
        btn_reset.setMaximumHeight(26)
        btn_reset.clicked.connect(lambda: (self.mol_canvas.auto_fit(), self.mol_canvas.update()))
        vbhl.addWidget(btn_reset)
        cl.addWidget(vbar)
        layout.addWidget(canvas_frame, stretch=1)

        # 启用虚线模式
        self.mol_canvas.set_dash_bond_mode(True)

        # 虚线控制面板
        dash_panel = parent._build_draw_bond_panel(target=self)
        layout.addWidget(dash_panel)

        # 填充下拉框选项并连接信号（populate 后 connect，避免初始化时触发）
        self._init_bond_combos(parent)
        self.var_dash_color.currentIndexChanged.connect(parent._on_dash_color_changed)
        self.var_bond_type.currentIndexChanged.connect(parent._vmd_reapply_dashes)
        self.var_bond_mat.currentIndexChanged.connect(parent._vmd_reapply_dashes)

        # 初始设置文字
        self._apply_lang()

    def _init_bond_combos(self, parent):
        """初始化虚线颜色和类型的下拉框（blockSignals 防触发）。"""
        idx = 1 if parent._lang == "en" else 2
        self.var_dash_color.blockSignals(True)
        for it in parent._bond_color_items:
            self.var_dash_color.addItem(it[idx])
        self.var_dash_color.setCurrentText("黑色" if parent._lang == "zh" else "Black")
        self.var_dash_color.blockSignals(False)

        self.var_bond_type.blockSignals(True)
        for it in parent._bond_type_items:
            self.var_bond_type.addItem(it[idx])
        self.var_bond_type.setCurrentText("圆点" if parent._lang == "zh" else "Dots")
        self.var_bond_type.blockSignals(False)

    def showEvent(self, event):
        """弹窗打开时启用虚线模式"""
        super().showEvent(event)

    def _enable_dash_controls(self):
        """启用弹窗内的虚线控件"""
        self.chk_dash_mode.setEnabled(True)
        self.chk_dash_mode.setChecked(True)
        self.btn_undo_bond.setEnabled(True)
        self.btn_clear_bond.setEnabled(True)

    def _apply_lang(self):
        """弹窗语言切换"""
        if not self._parent:
            return
        p = self._parent
        self.setWindowTitle(p._tr("chk_dash_mode"))
        self.grp_draw_bond.setTitle(p._tr("grp_draw_bond"))
        self.lbl_bond_color.setText(p._tr("lbl_color"))
        self.lbl_bond_type.setText(p._tr("lbl_type"))
        self.lbl_bond_mat.setText(p._tr("lbl_material"))
        self.lbl_bond_segments.setText(p._tr("lbl_segments"))
        self.lbl_bond_radius.setText(p._tr("lbl_radius"))
        self.btn_undo_bond.setText(p._tr("btn_undo"))
        self.btn_clear_bond.setText(p._tr("btn_clear_all"))
        self.chk_dash_mode.setText(p._tr("chk_dash_mode"))
        self._parent._populate_bond_combos()

    def closeEvent(self, event):
        # 关闭弹窗时退出虚线模式
        if self.mol_canvas:
            self.mol_canvas.set_dash_bond_mode(False)
            if self._parent:
                self._parent._update_dash_status()
                # 同步弹窗控件值到主窗口 _dash_params
                dp = self._parent._dash_params
                if hasattr(self, 'bond_nbars_slider'):
                    dp['gap'] = self.bond_nbars_slider.value() / 100.0
                    dp['radius'] = self.bond_radius_slider.value() / 100.0
        super().closeEvent(event)


class OrbitalVisApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(1400, 820)
        self.setMinimumSize(1100, 680)

        self.paths = backend.load_config()
        self.running = False
        # ── VMD 会话（委托给 orbital_viewer_lib）──
        self._vmd_session = ovlib.VMDOrbitalSession(log_func=self._append_log, paths=self.paths)
        self.vmd_port = None       # 读取时从 session 同步
        self.vmd_render_dir = None # 读取时从 session 同步
        self.vmd_cube_path = None
        self._vmd_persist_sock = None  # 已废弃，保留兼容
        self._vmd_dash_pairs = []
        self.vmd_multi_cubes = None
        self._dash_dialog = None
        # ── VMD 控制台弹出窗口 ──
        self._vmd_console_win = None
        # 应用图标（打包后 exe 同目录或 _internal/sys._MEIPASS；多候选回退）
        try:
            from PyQt5.QtGui import QIcon
            _dirs = [os.path.dirname(os.path.abspath(__file__))]
            if getattr(sys, "frozen", False):
                _dirs.insert(0, os.path.dirname(sys.executable))
                _meipass = getattr(sys, "_MEIPASS", None)
                if _meipass:
                    _dirs.append(_meipass)
            _icon_path = None
            for _name in ("OV.png", "molstudio.ico", "gxnu_molstudio.ico",
                          "molstudio_icon_src.png"):
                for _dir in _dirs:
                    _p = os.path.join(_dir, _name)
                    if os.path.exists(_p):
                        _icon_path = _p
                        break
                if _icon_path:
                    break
            if _icon_path:
                self.setWindowIcon(QIcon(_icon_path))
        except Exception:
            pass
        self._vmd_style_applied = None
        self._custom_pos_rgb = None  # 自定义正相位颜色 (R,G,B), None=用风格默认
        self._custom_neg_rgb = None  # 自定义负相位颜色
        self.current_iso = 0.05
        self.current_opacity = None
        self.iso_step = 0.005
        # ── 轨道状态管理（统一追踪 rep/molid/phase） ──
        self._vmd_state = {"rep_pos": 1, "rep_neg": 2, "molid": 0}
        # 多轨道相位翻转状态：{轨道标签: 是否已翻转}（volset i ↔ rep 2i+1/2i+2）
        self._vmd_orbital_flips = {}
        self.opacity_step = 0.05
        # ── 虚线绘制共享参数（弹窗控件 → VMD 绘制） ──
        self._dash_params = {
            'gap': 0.2, 'radius': 0.06,
            'color_hex': '#000000', 'mat': 'Opaque', 'type': 'dots'
        }
        self._bond_color_items = [
            ("black",  "Black",  "黑色",   "#000000"),
            ("gray",   "Gray",   "灰色",   "#808080"),
            ("cyan",   "Cyan",   "青色",   "#00FFFF"),
            ("yellow", "Yellow", "黄色",   "#FFFF00"),
            ("red",    "Red",    "红色",   "#FF0000"),
            ("blue",   "Blue",    "蓝色",   "#0000FF"),
            ("green",  "Green",  "绿色",   "#00FF00"),
            ("white",  "White",  "白色",   "#FFFFFF"),
        ]
        self._bond_type_items = [
            ("dots",     "Dots",          "圆点"),
            ("pymol",    "Dashed(pymol)", "PyMOL虚线"),
            ("cylinder", "Cylinder",      "圆柱"),
            ("cone",     "Cone",          "锥形"),
            ("line",     "Line",          "线段"),
        ]
        self._bond_mat_map = {
            "Opaque": "Opaque", "Transparent": "Transparent",
            "50%Transparent": "HalfTransparent"}

        self._current_cubes = []
        # 轨道预览目标: "canvas" = 左侧内嵌 OpenGL 画布, "vmd" = 外部 VMD
        self._preview_target = "canvas"
        # 拖放支持
        self.setAcceptDrops(True)
        self._current_orbitals = []

        # ── MolCanvas 状态 ──
        self.mol_canvas = None
        self._current_fchk = ""

        self._lang = "zh"
        self._h_hidden = False  # track hydrogen filter state

        self._setup_ui()
        self._setup_shortcuts()

        # 延迟加载：QSS 主题、语言、图标等非关键初始化在窗口显示后执行
        QTimer.singleShot(10, self._deferred_init)

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 8, 12, 10)
        main_layout.setSpacing(6)

        # ── 输入文件行：全宽、置顶（所有 tab 共用） ──
        main_layout.addWidget(self._build_input_panel())

        # ── 主体：左栏(画布) | 右栏(tab 区) ──
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        # 主水平分割：功能导航条（画布左侧） | 左栏画布 | 右栏 tabs 内容
        # 导航条与右栏参数区都用白色圆角卡片包裹（浅灰窗口底上更自然）
        # BodySplitter：拖动分隔条即可调左右栏宽度，双击分隔条复位
        main_splitter = BodySplitter(Qt.Horizontal)
        main_splitter.setChildrenCollapsible(False)
        self.main_nav = QListWidget()
        self.main_nav.setObjectName("MainNav")
        self.main_nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.main_nav.setCurrentRow(0)
        nav_card = QFrame()
        nav_card.setObjectName("NavCard")
        nav_card.setFixedWidth(122)
        nav_l = QVBoxLayout(nav_card)
        nav_l.setContentsMargins(0, 6, 0, 6)
        nav_l.addWidget(self.main_nav)
        main_splitter.addWidget(nav_card)
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setStretchFactor(2, 1)
        main_splitter.setSizes([122, 620, 620])
        self._body_splitter = main_splitter

        # ===== 左栏：输入文件行 + 画布（参数设置在画布下方） =====
        left_widget = QWidget()
        self._left_widget = left_widget   # 供按 tab 隐藏画布用
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        # 创建 MolCanvas 实例但不加到主窗口布局中（由弹窗复用）
        self.mol_canvas = MolCanvas(None)

        # ── 可视化画布（纯容器，无边框/标题，保证与右侧 tabs 上下对齐） ──
        self.grp_canvas = QWidget()
        cv = QVBoxLayout(self.grp_canvas)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)

        self.cub_canvas = None
        if _HAS_CUB_CANVAS:
            try:
                self.cub_canvas = CubCanvasPanel(self)
                self.cub_canvas.setMinimumWidth(360)
                self.cub_canvas.show_params_panel(True)
                self.cub_canvas.statusChanged.connect(self._on_canvas_status)
                # 元素原子颜色设置等画布改动 → VMD 已连接时自动同步
                self.cub_canvas.on_vmd_refresh = self._push_canvas_to_vmd_if_running
                cv.addWidget(self.cub_canvas, stretch=1)
            except Exception as e:
                self.cub_canvas = None
                print(f"[cub_canvas] 初始化失败: {e}")

        if self.cub_canvas is None:
            _tip = QLabel(self._tr("msg_gl_install_hint"))
            _tip.setAlignment(Qt.AlignCenter)
            _tip.setStyleSheet("color:#94A3B8; background:#F5F6FA; font-size:10pt;")
            cv.addWidget(_tip, stretch=1)

        left_layout.addWidget(self.grp_canvas, stretch=1)

        # ── 画布参数区（显示/等值面 + 球棍模型）→ 移入「可视化控制」tab ──
        # ── 一键样式 + 分子显示卡片 → 保留在画布内部（圆角矩形卡片） ──
        # 注意：_style_wrap 仍由画布自身的 root 布局承载，不再抽离到窗口底部。
        self.canvas_params = None
        self._style_wrap = None
        if self.cub_canvas is not None:
            try:
                self.canvas_params = self.cub_canvas._params
                self.canvas_params.setParent(None)
                self._style_wrap = getattr(self.cub_canvas, "_style_wrap", None)
                # 「同步到VMD」按钮注入主窗口回调（按钮本身在画布一键样式卡片内）
                try:
                    self.cub_canvas.on_sync_vmd = self._open_vmd_console
                    self.btn_sync_vmd = getattr(
                        self.cub_canvas, "_sync_vmd_btn", None)
                except Exception:
                    self.btn_sync_vmd = None
                # 「清空样式」按钮注入主窗口回调（联动各分析面板）
                try:
                    self.cub_canvas.on_clear_analysis = self._clear_analysis
                except Exception:
                    pass
                # 画布工具栏（仅剩“参数 ▴”开关）一并隐藏；
                # 仅隐藏真正的工具栏，避免 GL 不可用时误藏“未安装 PyOpenGL”提示
                _bar = self.cub_canvas.layout().itemAt(0).widget()
                if _bar is not None and getattr(_bar, "objectName", lambda: "")() == "CubToolBar":
                    _bar.hide()
            except Exception:
                self.canvas_params = None
                self._style_wrap = None
                self.btn_sync_vmd = None

        # ── VMD 控制台（渲染参数/操作/辅助行）→ 移入「可视化控制」tab ──
        # 复用 SciFiGroupBox，使其外观与「渲染参数 / 操作」分组框一致
        # （蓝底白字标题条，压在圆角矩形顶边上）
        self._vmd_content = SciFiGroupBox(self._tr("vmd_console_title"))
        self._vmd_content.setObjectName("VmdConsoleBox")
        vc = QVBoxLayout(self._vmd_content)
        vc.setContentsMargins(12, 6, 12, 10)
        vc.setSpacing(10)
        vc.addWidget(self._build_render_params_panel())
        # 实时调节滑杆与内嵌画布参数区重复：控件仍构建（供 _apply_lang_ui
        # 等引用），但保持隐藏
        vc.addWidget(self._build_live_panel())
        self.grp_live.hide()
        vc.addWidget(self._build_buttons_panel())
        # AIM 期刊级出图（原 AIM tab 的 VMD 渲染区，整合到 VMD 控制台）
        vc.addWidget(self._build_aim_vmd_panel())
        # 注：δg等值面/不透明度/极值点半径/数值/色标条 已并入操作按钮区
        #（_build_buttons_panel 内部第二行），不再单独追加在底部。
        # 不加入 left_layout；稍后与参数区一起放进「可视化控制」tab

        # ===== 右栏：tab 区（输入行已移到窗口顶部通栏） =====
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        scroll_right = QScrollArea()
        scroll_right.setWidgetResizable(True)
        scroll_right.setFrameShape(QFrame.NoFrame)
        scroll_right.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_right.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tabs = QStackedWidget()
        # 右侧功能页容器：导航条在画布左侧（self.main_nav，QListWidget），
        # 文字横排、宽度充足；选中联动由 _setup_main_nav / _sync_main_nav 维护
        self.tabs.setObjectName("MainStack")

        # ── 可视化控制 tab（第一个，始终可点）：显示/等值面 + 球棍模型 ──
        self._viz_tab = QWidget()
        viz_l = QVBoxLayout(self._viz_tab)
        viz_l.setContentsMargins(6, 6, 6, 6)
        viz_l.setSpacing(6)
        # 「同步到VMD」入口已移到左侧画布下方一键样式卡片（见画布初始化处）
        self.btn_sync_vmd = None
        if self.canvas_params is not None:
            viz_l.addWidget(self.canvas_params)
        viz_l.addStretch(1)
        self.tabs.addWidget(self._viz_tab)
        self._viz_tab.setEnabled(True)
        # 参数区两个折叠组默认展开（不再隐藏）
        if self.cub_canvas is not None:
            try:
                self.cub_canvas._btn_toggle_iso.setChecked(True)
                self.cub_canvas._btn_toggle_ball.setChecked(True)
            except Exception:
                pass

        tab_setup = QWidget()
        tab_setup_layout = QVBoxLayout(tab_setup)
        tab_setup_layout.setContentsMargins(4, 4, 4, 4)
        tab_setup_layout.setSpacing(6)
        # 输入文件行在右侧控制面板顶部、跨 tab 共用（见右栏构建处）
        # 轨道面板（轨道选择/浏览轨道/编号规则）已按需求隐藏，不再加入布局
        self._build_orbital_panel()
        # 自旋密度行（可见）：挂在轨道 tab 顶部，轨道表格上方
        if getattr(self, "spin_density_bar", None) is not None:
            tab_setup_layout.addWidget(self.spin_density_bar, 0)
        # 轨道表格 — 嵌入第一个选项卡，载入 fchk 后自动填充
        self.orbital_tabs = QTabWidget()
        self.orbital_table_alpha = self._make_orbital_table()
        self.orbital_tabs.addTab(self.orbital_table_alpha, "")
        self.orbital_table_beta = None
        # 提示 tab（假标签，固定在最右端）
        self.tab_hint = QWidget()
        self.orbital_tabs.addTab(self.tab_hint, "")
        self.orbital_tabs.setTabEnabled(self.orbital_tabs.indexOf(self.tab_hint), False)
        self.tab_hint.setStyleSheet("background:#3498DB; color:white;")
        idx = self.orbital_tabs.indexOf(self.tab_hint)
        self.orbital_tabs.setTabText(idx, self._tr("tab_orbit_hint"))
        # 设置 tab 栏样式（提示 tab #1565C0 蓝底白字）
        self.orbital_tabs.setStyleSheet("""
            QTabBar::tab:disabled { background:#1565C0; color:white; border:1px solid #0D47A1; border-bottom:none; }
        """)
        tab_setup_layout.addWidget(self.orbital_tabs, 1)
        self.tabs.addWidget(tab_setup)

        # （原「VMD 渲染」tab 已取消：渲染参数/动作按钮搬到左侧画布下方，
        #   见 _build_left_vmd_area；tab 索引顺移，_set_tab_texts 已同步）

        # ── 电荷 + 键级 合并 Tab（包裹 ChargePanel 与 BondOrderPanel，
        #    纵向组合到同一页签，共用左侧 OpenGL 画布） ──
        self.charge_panel = None        # 仍为组合面板实例
        self.bond_order_panel = None    # 兼容属性：指向组合面板
        self.nbo_panel = None
        # Multiwfn 路径只在此统一提供（⚙️ 路径设置 → fchk_orbital.ini → self.paths）
        _get_mw = lambda: self.paths.get("multiwfn", "") or ""
        if _HAS_CHARGE_VIEWER:
            glw = self.cub_canvas.glw if self.cub_canvas is not None else None
            from charge_bond_panel import ChargeBondPanel
            self.charge_panel = ChargeBondPanel(
                glw=glw,
                multiwfn_path=self.paths.get("multiwfn", ""),
                get_fchk=lambda: getattr(self, "_current_fchk", "") or "",
                get_multiwfn=_get_mw,
                log_func=self._append_log,
                parent=self,
            )
            self.bond_order_panel = self.charge_panel
            self.tabs.addWidget(self.charge_panel)

        # ── NBO 分析 Tab（整合自 NBOViewer） ──
        if _HAS_NBO_VIEWER:
            glw = self.cub_canvas.glw if self.cub_canvas is not None else None
            self.nbo_panel = NboPanel(
                glw=glw,
                multiwfn_path=self.paths.get("multiwfn", ""),
                get_fchk=lambda: getattr(self, "_current_fchk", "") or "",
                get_style=lambda: self._get_style_name(),
                get_multiwfn=_get_mw,
                log_func=self._append_log,
                parent=self,
            )
            self.tabs.addWidget(self.nbo_panel)

        # ── ESP 表面 Tab（整合自 ESPViewer，第一步：ISO 模式） ──
        self.esp_panel = None
        if _HAS_ESP_PANEL:
            glw = self.cub_canvas.glw if self.cub_canvas is not None else None
            self.esp_panel = EspPanel(
                glw=glw,
                multiwfn_path=self.paths.get("multiwfn", ""),
                get_fchk=lambda: getattr(self, "_current_fchk", "") or "",
                get_multiwfn=_get_mw,
                parent=self,
                on_vmd_refresh=self._push_canvas_to_vmd_if_running,
            )
            self.tabs.addWidget(self.esp_panel)

        # ── IGMH/IRI 分析 Tab（整合自 IGMH_Toolbox V4） ──
        self.igmh_panel = None
        if _HAS_IGMH_PANEL:
            glw = self.cub_canvas.glw if self.cub_canvas is not None else None
            self.igmh_panel = IgmhPanel(
                glw=glw,
                multiwfn_path=self.paths.get("multiwfn", ""),
                get_fchk=lambda: getattr(self, "_current_fchk", "") or "",
                get_multiwfn=_get_mw,
                parent=self,
                log_func=self._append_log,
                iso_slider=(getattr(self.cub_canvas, "_iso_sld", None)
                            if self.cub_canvas is not None else None),
            )
            self.tabs.addWidget(self.igmh_panel)
            # IGMH 面板 → VMD 控制区 双向同步（δg 等值面 / 不透明度）
            try:
                self.igmh_panel.sld_iso.valueChanged.connect(
                    self._igmh_iso_to_vmd_area)
                self.igmh_panel.sld_op.valueChanged.connect(
                    self._igmh_op_to_vmd_area)
            except Exception:
                pass

        # ── AIM 拓扑分析 tab（第七个）──
        self.aim_panel = None
        if _HAS_AIM_PANEL:
            glw = self.cub_canvas.glw if self.cub_canvas is not None else None
            try:
                self.aim_panel = AIMPanel(
                    glw=glw,
                    multiwfn_path=self.paths.get("multiwfn", ""),
                    get_fchk=lambda: getattr(self, "_current_fchk", "") or "",
                    get_multiwfn=_get_mw,
                    get_vmd=lambda: self.paths.get("vmd", "") or "",
                    get_tachyon=lambda: self.paths.get("tachyon", "") or "",
                    log_func=self._append_log,
                    parent=self,
                )
                self.tabs.addWidget(self.aim_panel)
            except Exception:
                self.aim_panel = None

        # ── ETS-NOCV 分析 tab（第八个）──
        self.etsnocv_panel = None
        if _HAS_ETSNOCV_PANEL:
            glw = self.cub_canvas.glw if self.cub_canvas is not None else None
            try:
                self.etsnocv_panel = ETSNOCVPanel(
                    glw=glw,
                    multiwfn_path=self.paths.get("multiwfn", ""),
                    get_fchk=lambda: getattr(self, "_current_fchk", "") or "",
                    get_multiwfn=_get_mw,
                    get_vmd=lambda: self.paths.get("vmd", "") or "",
                    get_tachyon=lambda: self.paths.get("tachyon", "") or "",
                    log_func=self._append_log,
                    parent=self,
                )
                self.tabs.addWidget(self.etsnocv_panel)
            except Exception:
                self.etsnocv_panel = None

        # ── MPP 分子平面性参数分析 tab ──
        self.mpp_panel = None
        if _HAS_MPP_PANEL:
            glw = self.cub_canvas.glw if self.cub_canvas is not None else None
            try:
                self.mpp_panel = MPPPanel(
                    glw=glw,
                    multiwfn_path=self.paths.get("multiwfn", ""),
                    get_fchk=lambda: getattr(self, "_current_fchk", "") or "",
                    get_multiwfn=_get_mw,
                    on_sync_vmd=self._open_vmd_console,
                    on_vmd_refresh=self._push_canvas_to_vmd_if_running,
                    on_set_mol_style=(self.cub_canvas.set_mol_style_name
                                      if self.cub_canvas is not None else None),
                    log_func=self._append_log,
                    parent=self,
                )
                self.tabs.addWidget(self.mpp_panel)
            except Exception:
                self.mpp_panel = None

        # ── IRC 整合分析 tab ──
        self.irc_panel = None
        if _HAS_IRC_PANEL:
            glw = self.cub_canvas.glw if self.cub_canvas is not None else None
            try:
                self.irc_panel = IrcPanel(
                    glw=glw,
                    multiwfn_path=self.paths.get("multiwfn", ""),
                    log_func=self._append_log,
                    parent=self,
                )
                self.tabs.addWidget(self.irc_panel)
            except Exception:
                self.irc_panel = None

        # ── DI 能量分解分析 tab ──
        self.di_panel = None
        if _HAS_DI_PANEL:
            glw = self.cub_canvas.glw if self.cub_canvas is not None else None
            try:
                self.di_panel = DiAnalysisPanel(
                    glw=glw,
                    log_func=self._append_log,
                    parent=self,
                )
                self.tabs.addWidget(self.di_panel)
            except Exception:
                self.di_panel = None

        # ── Energetic Span Model tab ──
        self.esm_panel = None
        if _HAS_ESM_PANEL:
            try:
                self.esm_panel = EnergySpanPanel(
                    log_func=self._append_log,
                    parent=self,
                )
                self.tabs.addWidget(self.esm_panel)
            except Exception:
                self.esm_panel = None

        scroll_right.setWidget(self.tabs)
        # 参数设置区用白色圆角卡片整体包裹
        right_card = QFrame()
        right_card.setObjectName("RightCard")
        rc_l = QVBoxLayout(right_card)
        rc_l.setContentsMargins(0, 0, 0, 0)
        rc_l.addWidget(scroll_right)
        right_layout.addWidget(right_card, stretch=1)

        # ── 运行日志（独立 tab，各分析面板的日志统一汇总到这里） ──
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setUndoRedoEnabled(False)
        self.log_text.setLineWrapMode(QTextEdit.WidgetWidth)
        self.log_text.setStyleSheet("""
            QTextEdit{
                border:none;
                background:transparent;
                padding:8px;
                font-family:"Consolas","JetBrains Mono","Microsoft YaHei UI";
                font-size:16px;
            }
        """)
        self.tabs.addWidget(self.log_text)

        main_splitter.addWidget(left_widget)
        main_splitter.addWidget(right_widget)
        # 左右宽度相等：忽略右侧内容的最小尺寸提示，避免分析面板撑宽分割条
        self.tabs.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        scroll_right.setMinimumWidth(0)
        # 必须在 addWidget 之后设置 stretch 才生效：导航固定、画布与右栏 1:1 均分
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setStretchFactor(2, 1)
        _DEFAULT_SPLIT_SIZES = [122, 620, 620]
        main_splitter.setSizes(_DEFAULT_SPLIT_SIZES)
        main_splitter.set_default_sizes(_DEFAULT_SPLIT_SIZES)
        body_layout.addWidget(main_splitter, stretch=1)

        main_layout.addWidget(body, stretch=5)

        self.progress_label = QLabel()
        self.progress_label.setObjectName("ProgressLabel")
        self.progress_label.hide()
        main_layout.addWidget(self.progress_label)

        # VMD 相关功能已停用：可视化全部走左侧 OpenGL 画布
        self._hide_vmd_features()

    def _hide_vmd_features(self):
        """VMD 显示辅助开关（1.1 布局）。

        1.1 起「VMD 渲染」tab 取消，渲染参数/动作按钮已搬到左侧画布下方
        （VMD 控制台，▾/▸ 折叠）；这里负责隐藏与内嵌画布实时预览重复的
        实时调节滑杆组。
        """
        # 实时调节（VMD 等值面/不透明度滑杆）与内嵌画布参数区重复，保持隐藏
        if getattr(self, "grp_live", None) is not None:
            self.grp_live.hide()

    def _build_input_panel(self):
        self.grp_input = SciFiGroupBox("")
        layout = QHBoxLayout(self.grp_input)
        layout.setSpacing(6)

        self.mode_group = QButtonGroup(self)
        self.rb_folder = QRadioButton("")
        self.rb_file = QRadioButton("")
        self.mode_group.addButton(self.rb_folder, 0)
        self.mode_group.addButton(self.rb_file, 1)
        self.rb_file.setChecked(True)
        self.rb_folder.hide()
        self.rb_file.hide()

        self.var_path = QLineEdit()
        self.var_path.setPlaceholderText("")
        layout.addWidget(self.var_path, stretch=1)
        self.btn_browse_input = QPushButton("")
        self.btn_browse_input.setObjectName("SmallBtn")
        self.btn_browse_input.clicked.connect(self._browse_input)
        layout.addWidget(self.btn_browse_input)

        self._lang_btn = QPushButton("EN")
        self._lang_btn.setObjectName("SmallBtn")
        self._lang_btn.setCursor(Qt.PointingHandCursor)
        self._lang_btn.clicked.connect(self._switch_lang)
        layout.addWidget(self._lang_btn)

        self.btn_paths = QPushButton(self._tr("btn_paths"))
        self.btn_paths.setObjectName("SmallBtn")
        self.btn_paths.setMinimumWidth(150)
        self.btn_paths.setCursor(Qt.PointingHandCursor)
        self.btn_paths.setToolTip(self._tr("tab_paths"))
        self.btn_paths.clicked.connect(self._open_paths_dialog)
        layout.addWidget(self.btn_paths)

        return self.grp_input

    def _build_orbital_panel(self):
        self.grp_orbital = SciFiGroupBox("")
        layout = QGridLayout(self.grp_orbital)
        layout.setVerticalSpacing(4)
        layout.setHorizontalSpacing(6)

        # 轨道选择区域（输入框保留供代码使用，UI 上隐藏）
        self.lbl_orbital_main = QLabel("")
        self.lbl_orbital_main.hide()
        self.var_orbital = QLineEdit("h")
        self.var_orbital.setMaximumWidth(160)
        self.var_orbital.hide()
        layout.addWidget(self.lbl_orbital_main, 0, 0)
        layout.addWidget(self.var_orbital, 0, 1)

        # 网格精度控件已移至左侧画布面板的"等值面"区域（cub_canvas）

        # Browse orbitals button（已隐藏：轨道浏览器由双击轨道表格触发）
        self.btn_browse_orbital = QPushButton(self._tr("btn_browse_orbital"))
        self.btn_browse_orbital.setToolTip(self._tr("btn_browse_orbital"))
        self.btn_browse_orbital.setFixedHeight(48)
        self.btn_browse_orbital.setCursor(Qt.PointingHandCursor)
        self.btn_browse_orbital.clicked.connect(self._open_orbital_browser)
        self.btn_browse_orbital.hide()
        layout.addWidget(self.btn_browse_orbital, 0, 5)

        # Rules button（已隐藏：轨道编号规则说明）
        self.btn_rules = QPushButton(self._tr("orbital_rules_btn"))
        self.btn_rules.setToolTip(self._tr("orbital_rules_btn"))
        self.btn_rules.setText(self._tr("orbital_rules_btn"))
        self.btn_browse_orbital.setText(self._tr("btn_browse_orbital"))
        self.btn_browse_orbital.setToolTip(self._tr("btn_browse_orbital"))
        self.btn_rules.setFixedHeight(48)
        self.btn_rules.setCursor(Qt.PointingHandCursor)
        self.btn_rules.clicked.connect(self._show_rules_dialog)
        self.btn_rules.hide()
        layout.addWidget(self.btn_rules, 0, 6)

        for c in range(7):
            layout.setColumnStretch(c, 0)
        layout.setColumnStretch(1, 1)

        # ── 自旋密度行：独立可见行（grp_orbital 隐藏不挂布局，此行挂到轨道 tab） ──
        self.spin_density_bar = QWidget()
        spin_row = QHBoxLayout(self.spin_density_bar)
        spin_row.setSpacing(6)
        spin_row.setContentsMargins(0, 0, 0, 0)
        self.btn_spin_density = QPushButton(self._tr("spin_density_btn"))
        self.btn_spin_density.setToolTip(self._tr("spin_density_iso_tip"))
        self.btn_spin_density.setCursor(Qt.PointingHandCursor)
        self.btn_spin_density.clicked.connect(self._run_spin_density)
        spin_row.addWidget(self.btn_spin_density)
        self.lbl_spin_iso = QLabel(self._tr("spin_density_iso"))
        spin_row.addWidget(self.lbl_spin_iso)
        self.spin_iso = QDoubleSpinBox()
        self.spin_iso.setRange(0.0001, 0.5)
        self.spin_iso.setDecimals(4)
        self.spin_iso.setValue(0.001)
        self.spin_iso.setSingleStep(0.0005)
        self.spin_iso.setMaximumWidth(96)
        self.spin_iso.setToolTip(self._tr("spin_density_iso_tip"))
        spin_row.addWidget(self.spin_iso)
        spin_row.addStretch()
        return self.grp_orbital

    # ── 自旋密度：Multiwfn 生成 cube → 画布显示 + VMD 场景登记 ──
    def _run_spin_density(self):
        try:
            if getattr(self, "_spin_worker", None) is not None \
                    and self._spin_worker.isRunning():
                return
            path = self.var_path.text().strip()
            if not path:
                QMessageBox.warning(self, self._tr("msg_title_hint"),
                                    self._tr("spin_density_need_fchk"))
                return
            fchk = path if os.path.isfile(path) else None
            if not fchk:
                files = sorted(glob.glob(os.path.join(path, "*.fchk")))
                fchk = files[0] if files else None
            if not fchk or not os.path.isfile(fchk):
                QMessageBox.warning(self, self._tr("msg_title_hint"),
                                    self._tr("spin_density_need_fchk"))
                return
            exe_paths = self._get_paths()
            if not os.path.exists(exe_paths["multiwfn"]):
                QMessageBox.warning(self, self._tr("msg_title_error"),
                                    self._tr("msg_mw_not_found",
                                             path=exe_paths["multiwfn"]))
                return
            out = self._get_out_dir(fchk)
            try:
                os.makedirs(out, exist_ok=True)
            except OSError:
                out = os.path.dirname(os.path.abspath(fchk))
            self._spin_iso = self.spin_iso.value()
            self.btn_spin_density.setEnabled(False)
            self._append_log(self._tr("spin_density_gen"))
            self._spin_worker = SpinDensityWorker(
                fchk, exe_paths["multiwfn"], work_dir=out, grid_quality=3)
            self._spin_worker.log_signal.connect(self._append_log)
            self._spin_worker.progress_signal.connect(
                lambda v: self._set_progress(f"自旋密度 {int(v)}%"))
            self._spin_worker.finished_signal.connect(self._on_spin_done)
            self._spin_worker.error_signal.connect(self._on_spin_error)
            self._spin_worker.start()
        except Exception as e:
            self.btn_spin_density.setEnabled(True)
            try:
                self._append_log(f"自旋密度失败: {e}")
            except Exception:
                pass

    def _on_spin_done(self, cube):
        self.btn_spin_density.setEnabled(True)
        try:
            if not self._canvas_ready():
                QMessageBox.warning(self, self._tr("msg_title_hint"),
                                    self._tr("msg_gl_unavailable"))
                return
            glw = self.cub_canvas.glw
            iso = getattr(self, "_spin_iso", 0.001)
            glw._esp_point_mode = False   # 确保按表面（非点云）显示
            ok = glw.load(cube, isovalue=iso)
            if ok:
                # 登记 VMD 场景：type=orbital → +iso/-iso 双等值面，
                # 颜色用当前样式默认（sob-art 正绿/负蓝）
                glw.set_vmd_scene([{"type": "orbital", "vol": cube,
                                    "iso": iso}])
                self._append_log(self._tr(
                    "spin_density_done", name=os.path.basename(cube)))
            else:
                self._append_log(self._tr("spin_density_failed"))
        except Exception as e:
            self._append_log(f"自旋密度显示失败: {e}")

    def _on_spin_error(self, msg):
        self.btn_spin_density.setEnabled(True)
        try:
            self._append_log(str(msg))
        except Exception:
            pass

    def _build_render_params_panel(self):
        self.grp_render = SciFiGroupBox("")
        rlayout = QGridLayout(self.grp_render)
        rlayout.setVerticalSpacing(4)
        rlayout.setHorizontalSpacing(6)

        # 风格下拉框（占满可用宽度）
        self.lbl_render_style = QLabel("")
        self.var_style = _PopupLimitedComboBox(
            max_popup_height=210, max_visible_items=6, scroll_bar_always_on=True)
        self.var_style.setIconSize(QtCore.QSize(30, 13))
        self.var_style.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.var_style.setMaximumWidth(480)
        for name in backend.STYLES:
            icon = self._make_style_icon(backend.STYLES[name])
            self.var_style.addItem(icon, f"  {name}")
        # 默认样式 = sob-art（STYLES 第一个键不是 sob-art，需显式定位）
        _idx = self.var_style.findText("  sob-art")
        self.var_style.setCurrentIndex(_idx if _idx >= 0 else 0)
        self.var_style.currentTextChanged.connect(self._on_style_changed)

        # 正相位颜色按钮
        self.btn_pos_color = QPushButton("")
        self.btn_pos_color.setFixedSize(24, 24)
        self.btn_pos_color.setToolTip(self._tr("pick_pos_color"))
        self.btn_pos_color.setStyleSheet("background:#00AA00; border:1px solid #555; border-radius:12px;")
        self.btn_pos_color.clicked.connect(lambda: self._pick_phase_color("pos"))
        self.btn_pos_color.setContextMenuPolicy(Qt.CustomContextMenu)
        self.btn_pos_color.customContextMenuRequested.connect(lambda: self._reset_phase_color("pos"))

        # 负相位颜色按钮
        self.btn_neg_color = QPushButton("")
        self.btn_neg_color.setFixedSize(24, 24)
        self.btn_neg_color.setToolTip(self._tr("pick_neg_color"))
        self.btn_neg_color.setStyleSheet("background:#0000AA; border:1px solid #555; border-radius:12px;")
        self.btn_neg_color.clicked.connect(lambda: self._pick_phase_color("neg"))
        self.btn_neg_color.setContextMenuPolicy(Qt.CustomContextMenu)
        self.btn_neg_color.customContextMenuRequested.connect(lambda: self._reset_phase_color("neg"))

        self.lbl_pos_phase = QLabel("")
        self.lbl_neg_phase = QLabel("")

        # ── 布局：样式 + 正负相位，全部一行 ──
        top_row = QHBoxLayout()
        top_row.setSpacing(6)
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.addWidget(self.lbl_render_style)
        top_row.addWidget(self.var_style, 1)
        top_row.addSpacing(12)
        top_row.addWidget(self.lbl_pos_phase)
        top_row.addSpacing(6)
        top_row.addWidget(self.btn_pos_color)
        top_row.addSpacing(12)
        top_row.addWidget(self.lbl_neg_phase)
        top_row.addSpacing(6)
        top_row.addWidget(self.btn_neg_color)
        rlayout.addLayout(top_row, 0, 0, 1, 7)

        self.lbl_render_res = QLabel("")
        self.var_res = QComboBox()
        self.var_res.addItems(["2000x1500", "1200x900", "3000x2250"])
        self.var_res.setCurrentIndex(0)
        self.var_res.setMaximumWidth(150)

        self.lbl_render_shading = QLabel("")
        self.shade_group = QButtonGroup(self)
        self.rb_shadow = QRadioButton("")
        self.rb_noshadow = QRadioButton("")
        self.shade_group.addButton(self.rb_shadow, 0)
        self.shade_group.addButton(self.rb_noshadow, 1)
        self.rb_shadow.setChecked(True)

        self.lbl_trans_raster = QLabel("")
        self.var_trans_raster = QComboBox()
        self.var_trans_raster.addItems(["Raster3D", "VMD-match", "Orig", "Off"])
        self.var_trans_raster.setCurrentIndex(0)  # default: Raster3D
        self.var_trans_raster.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.lbl_render_threads = QLabel("")
        self.var_threads = QLineEdit("8")
        self.var_threads.setMaximumWidth(50)
        self.var_threads.setAlignment(Qt.AlignCenter)

        # ── 合并行：分辨率 + 阴影 + 透明度 + 线程数 ──
        row2 = QHBoxLayout()
        row2.setSpacing(6)
        row2.setContentsMargins(0, 0, 0, 0)
        row2.addWidget(self.lbl_render_res)
        row2.addWidget(self.var_res)
        row2.addSpacing(12)
        row2.addWidget(self.lbl_render_shading)
        row2.addWidget(self.rb_shadow)
        row2.addWidget(self.rb_noshadow)
        row2.addSpacing(12)
        row2.addWidget(self.lbl_trans_raster)
        row2.addWidget(self.var_trans_raster)
        row2.addSpacing(12)
        row2.addWidget(self.lbl_render_threads)
        row2.addWidget(self.var_threads)
        rlayout.addLayout(row2, 1, 0, 1, 7)

        # hidden
        self.var_auto = QCheckBox("")
        self.var_open = QCheckBox("")
        self.var_auto.hide()
        self.var_open.hide()
        rlayout.addWidget(self.var_auto, 2, 0)
        rlayout.addWidget(self.var_open, 2, 1)

        for c in range(7):
            rlayout.setColumnStretch(c, 0)
        rlayout.setColumnStretch(0, 1)
        return self.grp_render

    def _build_buttons_panel(self):
        """VMD 控制台操作按钮：单行（渲染出图/翻转相位/隐藏氢/虚线模式/预览/同步到VMD/保留编号）。"""
        self.grp_actions = SciFiGroupBox("")
        layout = QVBoxLayout(self.grp_actions)
        layout.setSpacing(6)
        layout.setContentsMargins(6, 6, 6, 6)

        row = QHBoxLayout()
        row.setSpacing(6)

        self.btn_run = QPushButton("")
        self.btn_run.setObjectName("ActionBtnSmall")
        self.btn_run.clicked.connect(self._run_cubes)
        self.btn_run.hide()
        row.addWidget(self.btn_run)

        self.btn_preview = QPushButton("")
        self.btn_preview.setObjectName("ActionBtnSmall")
        self.btn_preview.setEnabled(False)
        self.btn_preview.clicked.connect(self._preview)
        self.btn_preview.hide()
        row.addWidget(self.btn_preview)

        self.btn_render = QPushButton("")
        self.btn_render.setObjectName("ActionBtnSmall")
        self.btn_render.setEnabled(False)
        self.btn_render.clicked.connect(self._render_view)
        row.addWidget(self.btn_render)

        self.btn_flip_phase = QPushButton("")
        self.btn_flip_phase.setObjectName("ActionBtnSmall")
        self.btn_flip_phase.setEnabled(False)
        self.btn_flip_phase.clicked.connect(self._on_flip_phase)
        row.addWidget(self.btn_flip_phase)

        self.btn_h_filter = QPushButton("")
        self.btn_h_filter.setObjectName("ActionBtnSmall")
        self.btn_h_filter.setEnabled(False)
        self.btn_h_filter.clicked.connect(self._toggle_h_filter)
        row.addWidget(self.btn_h_filter)

        self.btn_dash_mode = QPushButton("")
        self.btn_dash_mode.setObjectName("ActionBtnSmall")
        self.btn_dash_mode.setEnabled(False)
        self.btn_dash_mode.clicked.connect(self._open_dash_bond_dialog)
        row.addWidget(self.btn_dash_mode)

        self.btn_preview_both = QPushButton(self._tr("btn_preview_both"))
        self.btn_preview_both.setObjectName("ActionBtnSmall")
        self.btn_preview_both.setCursor(Qt.PointingHandCursor)
        self.btn_preview_both.setToolTip(self._tr("btn_preview_both"))
        self.btn_preview_both.clicked.connect(self._preview_both_selected)
        row.addWidget(self.btn_preview_both)

        # 注：btn_sync_vmd 已作为「同步到VMD」入口移到 tab0（点击弹出嵌入窗口）

        self.lbl_h_keep = QLabel("")
        self.lbl_h_keep.setToolTip("逗号分隔的 H 原子编号（如 1,3,5-8），留空 = 全部隐藏")
        row.addWidget(self.lbl_h_keep)
        self.var_h_indices = QLineEdit()
        self.var_h_indices.setMaximumWidth(80)
        self.var_h_indices.setToolTip("逗号分隔的 H 原子编号（如 1,3,5-8），留空 = 全部隐藏")
        self.var_h_indices.setPlaceholderText("")
        row.addWidget(self.var_h_indices)
        row.addStretch()
        layout.addLayout(row)

        # ── 实时调节（δg等值面 / 不透明度 / 极值点半径 / 数值 / 色标条）──
        # 并入操作按钮区第二行，滑块拉长并与上方控件对齐
        layout.addLayout(self._build_vmd_extras())

        return self.grp_actions

    def _push_canvas_to_vmd_if_running(self):
        """VMD 已连接时把更新后的画布场景（ESP/MPP 等）推送到 VMD；未运行则不启动。"""
        try:
            sess = getattr(self, "_vmd_session", None)
            if sess is not None and sess.is_connected():
                self._sync_canvas_to_vmd()
        except Exception:
            pass

    def _build_aim_vmd_panel(self):
        """AIM 期刊级出图控制区（从 AIM tab 整合到 VMD 控制台）。

        仅 AIM 面板可用时启用；按钮点击后委托给 self.aim_panel 的 AIM 渲染逻辑。
        """
        self.grp_aim_vmd = SciFiGroupBox(self._tr("aim_vmd_grp"))
        self.grp_aim_vmd.setObjectName("AimVmdBox")
        grp = self.grp_aim_vmd
        lay = QVBoxLayout(grp)
        lay.setContentsMargins(12, 6, 12, 10)
        lay.setSpacing(6)

        row = QHBoxLayout()
        self.lbl_aim_vmd_style = QLabel(self._tr("aim_vmd_style"))
        row.addWidget(self.lbl_aim_vmd_style)
        self.combo_aim_vmd_style = QComboBox()
        try:
            from aim_visualize import STYLES as _AIM_STYLES
        except Exception:
            _AIM_STYLES = ["sob-art"]
        for k in _AIM_STYLES:
            self.combo_aim_vmd_style.addItem(k)
        if self.combo_aim_vmd_style.count():
            self.combo_aim_vmd_style.setCurrentText("sob-art")
        row.addWidget(self.combo_aim_vmd_style, 1)
        lay.addLayout(row)

        self.lbl_aim_vmd_hint = QLabel(self._tr("aim_vmd_hint"))
        self.lbl_aim_vmd_hint.setStyleSheet("color:#8899AA; font-size:9pt;")
        lay.addWidget(self.lbl_aim_vmd_hint)

        btn_row = QHBoxLayout()
        self.btn_aim_vmd_preview = QPushButton(self._tr("aim_vmd_preview"))
        self.btn_aim_vmd_preview.setCursor(Qt.PointingHandCursor)
        self.btn_aim_vmd_preview.clicked.connect(self._aim_vmd_preview)
        btn_row.addWidget(self.btn_aim_vmd_preview)
        self.btn_aim_vmd_render = QPushButton(self._tr("aim_vmd_render"))
        self.btn_aim_vmd_render.setCursor(Qt.PointingHandCursor)
        self.btn_aim_vmd_render.clicked.connect(self._aim_vmd_render)
        btn_row.addWidget(self.btn_aim_vmd_render)
        lay.addLayout(btn_row)

        # 与 VMD 控制台上方的「预览 / 渲染出图」功能类似，默认隐藏。
        # 控件仍构建（供 _apply_lang_ui 等引用），需要恢复时删除下面这行即可。
        grp.hide()
        return grp

    def _aim_vmd_preview(self):
        """VMD 控制台里的「在 VMD 中预览」（AIM 场景）。"""
        if not getattr(self, "aim_panel", None):
            QMessageBox.warning(self, self._tr("msg_title_hint"),
                                self._tr("msg_aim_unavailable"))
            return
        style = self.combo_aim_vmd_style.currentText()
        self.aim_panel._vmd_preview(style=style)

    def _aim_vmd_render(self):
        """VMD 控制台里的「渲染当前视角为 PNG」（AIM 场景）。"""
        if not getattr(self, "aim_panel", None):
            QMessageBox.warning(self, self._tr("msg_title_hint"),
                                self._tr("msg_aim_unavailable"))
            return
        style = self.combo_aim_vmd_style.currentText()
        self.aim_panel._vmd_render(style=style)

    def _build_live_panel(self):
        self.grp_live = QWidget()
        layout = QGridLayout(self.grp_live)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setHorizontalSpacing(8)

        self.lbl_live_iso = QLabel("")
        layout.addWidget(self.lbl_live_iso, 0, 0)
        self.iso_slider = QSlider(Qt.Horizontal)
        self.iso_slider.setRange(1, 500)
        self.iso_slider.setSingleStep(1)
        self.iso_slider.setPageStep(5)
        self.iso_slider.setValue(50)
        self.iso_slider.setEnabled(False)
        self.iso_slider.valueChanged.connect(self._on_iso_slider_changed)
        layout.addWidget(self.iso_slider, 0, 1)
        self.iso_edit = QLineEdit("0.050")
        self.iso_edit.setValidator(QDoubleValidator(0.005, 0.500, 4))
        self.iso_edit.setMaximumWidth(90)
        self.iso_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.iso_edit.setEnabled(False)
        self.iso_edit.editingFinished.connect(self._on_iso_edit_finished)
        layout.addWidget(self.iso_edit, 0, 2)

        self.lbl_live_opacity = QLabel("")
        layout.addWidget(self.lbl_live_opacity, 0, 3)
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(5, 100)
        self.opacity_slider.setValue(75)
        self.opacity_slider.setEnabled(False)
        self.opacity_slider.valueChanged.connect(self._on_opacity_slider_changed)
        layout.addWidget(self.opacity_slider, 0, 4)
        self.opacity_edit = QLineEdit("0.75")
        self.opacity_edit.setValidator(QDoubleValidator(0.05, 1.00, 2))
        self.opacity_edit.setMaximumWidth(70)
        self.opacity_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.opacity_edit.setEnabled(False)
        self.opacity_edit.editingFinished.connect(self._on_opacity_edit_finished)
        layout.addWidget(self.opacity_edit, 0, 5)

        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(4, 1)
        return self.grp_live

    def _build_vmd_extras(self):
        """VMD 实时调节区（并入操作按钮区）：等值面 / δg等值面 / 不透明度 /
        极值点半径 / 数值标签 / 色标条。每个滑块各占一行，标签/滑块/数值
        按列对齐，滑块拉长。

        对齐 ESPViewer2 与 IGMH-V4：δg 等值面与不透明度滑块实时控制 VMD
        （IGMH 场景），默认 0.004 / 0.75，并与 IGMH tab 双向同步。
        """
        lay = QGridLayout()
        lay.setSpacing(6)
        lay.setColumnStretch(1, 1)   # 滑块列拉伸

        # ── 等值面（轨道/等值面通用，默认 0.05，实时改 Isosurface） ──
        self.vmd_iso_main_sld = QSlider(Qt.Horizontal)
        self.vmd_iso_main_sld.setRange(1, 500)        # iso = 值/1000（0.001..0.5）
        self.vmd_iso_main_sld.setValue(50)            # 默认 0.050
        self.vmd_iso_main_sld.setToolTip("实时调节轨道/等值面大小（isovalue），立即生效")
        self.vmd_iso_main_lbl = QLabel("0.050")
        self.vmd_iso_main_lbl.setMinimumWidth(52)
        self.vmd_iso_main_sld.valueChanged.connect(self._on_vmd_iso_main)
        self.vmd_iso_main_cap = QLabel(self._tr("lbl_isovalue"))
        lay.addWidget(self.vmd_iso_main_cap, 0, 0)
        lay.addWidget(self.vmd_iso_main_sld, 0, 1)
        lay.addWidget(self.vmd_iso_main_lbl, 0, 2)

        # ── δg 等值面（IGMH 场景，默认 0.004，对齐 IGMH-V4） ──
        self.vmd_iso_sld = QSlider(Qt.Horizontal)
        self.vmd_iso_sld.setRange(1, 2000)           # iso = 值/1000（0.001..2.0）
        self.vmd_iso_sld.setValue(4)                 # 默认 0.004
        self.vmd_iso_sld.setToolTip("VMD 中 δg 等值面大小（a.u.），实时生效，与 IGMH 面板同步")
        self.vmd_iso_lbl = QLabel("0.004")
        self.vmd_iso_lbl.setMinimumWidth(52)
        self.vmd_iso_sld.valueChanged.connect(self._on_vmd_iso)
        self.vmd_dg_cap = QLabel(self._tr("lbl_dg_iso"))
        lay.addWidget(self.vmd_dg_cap, 1, 0)
        lay.addWidget(self.vmd_iso_sld, 1, 1)
        lay.addWidget(self.vmd_iso_lbl, 1, 2)

        # ── 不透明度（IGMH 场景，默认 0.75，对齐 IGMH-V4） ──
        self.vmd_op_sld = QSlider(Qt.Horizontal)
        self.vmd_op_sld.setRange(5, 100)             # 不透明度 %
        self.vmd_op_sld.setValue(75)                 # 默认 0.75
        self.vmd_op_sld.setToolTip("VMD 中等值面不透明度（%），实时生效，与 IGMH 面板同步")
        self.vmd_op_lbl = QLabel("0.75")
        self.vmd_op_lbl.setMinimumWidth(52)
        self.vmd_op_sld.valueChanged.connect(self._on_vmd_op)
        self.vmd_op_cap = QLabel(self._tr("lbl_opacity"))
        lay.addWidget(self.vmd_op_cap, 2, 0)
        lay.addWidget(self.vmd_op_sld, 2, 1)
        lay.addWidget(self.vmd_op_lbl, 2, 2)

        # ── 极值点半径（ESP 场景，默认 0.25 Å） ──
        self.vmd_ext_radius_sld = QSlider(Qt.Horizontal)
        self.vmd_ext_radius_sld.setRange(5, 100)      # 0.05 .. 1.00 Å
        self.vmd_ext_radius_sld.setValue(25)          # 默认 0.25
        self.vmd_ext_radius_sld.setToolTip("VMD 中极值点球半径（Å），实时生效")
        self.vmd_ext_radius_lbl = QLabel("0.25")
        self.vmd_ext_radius_lbl.setMinimumWidth(52)
        self.vmd_ext_radius_sld.valueChanged.connect(self._on_vmd_ext_radius)
        self.vmd_ext_cap = QLabel(self._tr("lbl_ext_radius"))
        lay.addWidget(self.vmd_ext_cap, 3, 0)
        lay.addWidget(self.vmd_ext_radius_sld, 3, 1)
        lay.addWidget(self.vmd_ext_radius_lbl, 3, 2)

        # ── 复选框行（极值点数值 / 色标条） ──
        chk_row = QHBoxLayout()
        chk_row.setSpacing(12)
        self.vmd_ext_labels_chk = QCheckBox(self._tr("chk_ext_values"))
        self.vmd_ext_labels_chk.setToolTip("在 VMD 中显示极值点数值（graphics text），实时生效")
        self.vmd_ext_labels_chk.toggled.connect(self._on_vmd_ext_labels)
        chk_row.addWidget(self.vmd_ext_labels_chk)
        self.vmd_colorbar_chk = QCheckBox(self._tr("chk_colorbar"))
        self.vmd_colorbar_chk.setToolTip("在 VMD 中叠加 ColorScaleBar 色标条（ESP/IGMH 表面），实时生效")
        self.vmd_colorbar_chk.toggled.connect(self._on_vmd_colorbar)
        chk_row.addWidget(self.vmd_colorbar_chk)
        chk_row.addStretch()
        lay.addLayout(chk_row, 4, 0, 1, 3)

        return lay

    # ── VMD 实时控制（socket 下发 Tcl，无需重新同步） ──

    def _on_vmd_iso_main(self, v):
        """VMD 等值面滑块：实时修改轨道等值面大小（isovalue）。"""
        iso = v / 1000.0
        self.vmd_iso_main_lbl.setText(f"{iso:.3f}")
        if not self.vmd_port:
            return
        # 同步隐藏的 grp_live iso_slider/iso_edit 状态，保持界面一致
        self.current_iso = iso
        if hasattr(self, "iso_edit"):
            self.iso_edit.blockSignals(True)
            self.iso_edit.setText(f"{iso:.3f}")
            self.iso_edit.blockSignals(False)
        if hasattr(self, "iso_slider"):
            self.iso_slider.blockSignals(True)
            self.iso_slider.setValue(v)
            self.iso_slider.blockSignals(False)
        self._vmd_session.set_isovalue(iso)

    def _on_vmd_iso(self, v):
        """VMD δg 等值面滑块：改 IGMH 等值面 iso + 同步 IGMH 面板。"""
        iso = v / 1000.0
        self.vmd_iso_lbl.setText(f"{iso:.3f}")
        if self.vmd_port:
            # IGMH 场景 rep 1 = Isosurface（参考实现：Isosurface iso 1 0 0 1 1）
            self._send_vmd_cmd(f"mol modstyle 1 top Isosurface {iso:.4f} 1 0 0 1 1")
        # 同步 IGMH tab（若有）
        ig = getattr(self, "igmh_panel", None)
        if ig is not None:
            ig.sld_iso.blockSignals(True)
            ig.sld_iso.setValue(v)
            ig.sld_iso.blockSignals(False)
            ig._iso_val = iso
            ig.lbl_iso_val.setText(f"{iso:.3f}")
            ig.edit_iso.blockSignals(True)
            ig.edit_iso.setText(f"{iso:.3f}")
            ig.edit_iso.blockSignals(False)

    def _on_vmd_op(self, v):
        """VMD 不透明度滑块：改所有等值面材质不透明度 + 同步 IGMH 面板。

        覆盖各场景的等值面材质：
          - 轨道/ESP 通用场景：_stl_a / _stl_b / _stl_bgr / EdgyGlass
          - IGMH 场景：_igmh_surf
        这样无论当前 VMD 是哪种场景，滑块都能生效。
        """
        op = v / 100.0
        self.vmd_op_lbl.setText(f"{op:.2f}")
        if self.vmd_port:
            for mat in ("_stl_a", "_stl_b", "_stl_bgr", "EdgyGlass", "_igmh_surf"):
                self._send_vmd_cmd(f"material change opacity {mat} {op:.3f}")
        # 同步 IGMH tab（若有）
        ig = getattr(self, "igmh_panel", None)
        if ig is not None:
            ig.sld_op.blockSignals(True)
            ig.sld_op.setValue(v)
            ig.sld_op.blockSignals(False)
            ig.edit_op.blockSignals(True)
            ig.edit_op.setText(str(v))
            ig.edit_op.blockSignals(False)

    def _igmh_iso_to_vmd_area(self, v):
        """IGMH 面板 δg 等值面 → VMD 控制区滑块跟随。"""
        if hasattr(self, "vmd_iso_sld"):
            self.vmd_iso_sld.blockSignals(True)
            self.vmd_iso_sld.setValue(v)
            self.vmd_iso_sld.blockSignals(False)
            self.vmd_iso_lbl.setText(f"{v / 1000.0:.3f}")

    def _igmh_op_to_vmd_area(self, v):
        """IGMH 面板不透明度 → VMD 控制区滑块跟随。"""
        if hasattr(self, "vmd_op_sld"):
            self.vmd_op_sld.blockSignals(True)
            self.vmd_op_sld.setValue(v)
            self.vmd_op_sld.blockSignals(False)
            self.vmd_op_lbl.setText(f"{v / 100.0:.2f}")

    def _on_vmd_ext_radius(self, v):
        self.vmd_ext_radius_lbl.setText(f"{v / 100:.2f}")
        if self.vmd_port:
            self._send_vmd_cmd(f"gxnu_ext_spheres {v / 100.0:.3f}")

    def _on_vmd_ext_labels(self, on):
        if self.vmd_port:
            self._send_vmd_cmd(f"gxnu_ext_labels {'1' if on else '0'}")

    def _on_vmd_colorbar(self, on):
        if not self.vmd_port:
            return
        # 从画布登记的 bgr 表面取 cmin/cmax/单位；无表面则关闭
        low = high = 0.0
        unit = "kcal/mol"
        try:
            reg = self.cub_canvas.glw.vmd_scene() or {}
            for sf in reg.get("surfaces", []):
                if sf.get("type") == "bgr":
                    try:
                        low = float(sf.get("cmin", low))
                        high = float(sf.get("cmax", high))
                    except (TypeError, ValueError):
                        pass
        except Exception:
            pass
        if on:
            self._send_vmd_cmd(
                f"gxnu_colorbar 1 {low} {high} {{kcal/mol}} {{ESP}}")
        else:
            self._send_vmd_cmd("gxnu_colorbar 0 0 0 {} {}")



    def _build_draw_bond_panel(self, target=None):
        """VMD 虚线样式面板。target: 用于分配控件的对象（默认 self）。"""
        if target is None:
            target = self

        target.grp_draw_bond = SciFiGroupBox("")
        vmd_layout = QVBoxLayout(target.grp_draw_bond)
        vmd_layout.setSpacing(4)

        # ── Row 1: 虚线 / 画布样式 / VMD 颜色 / 类型 / 材质 ──
        row1 = QHBoxLayout()
        target.chk_dash_mode = QCheckBox("")
        target.chk_dash_mode.setEnabled(False)
        target.chk_dash_mode.toggled.connect(lambda v: (
            target.mol_canvas.set_dash_bond_mode(v),
            self._update_dash_status()
        ))
        row1.addWidget(target.chk_dash_mode)

        target.lbl_bond_color = QLabel("")
        row1.addWidget(target.lbl_bond_color)
        target.var_dash_color = QComboBox()
        target.var_dash_color.setMaximumWidth(70)
        row1.addWidget(target.var_dash_color)

        target.lbl_bond_type = QLabel("")
        row1.addWidget(target.lbl_bond_type)
        target.var_bond_type = QComboBox()
        target.var_bond_type.setMaximumWidth(100)
        row1.addWidget(target.var_bond_type)

        target.lbl_bond_mat = QLabel("")
        row1.addWidget(target.lbl_bond_mat)
        target.var_bond_mat = QComboBox()
        target.var_bond_mat.addItems(list(self._bond_mat_map.keys()))
        target.var_bond_mat.setCurrentText("Opaque")
        target.var_bond_mat.setMaximumWidth(140)
        row1.addWidget(target.var_bond_mat)
        row1.addStretch()

        target.btn_undo_bond = QPushButton("")
        target.btn_undo_bond.setEnabled(False)
        target.btn_undo_bond.clicked.connect(self._undo_bond)
        row1.addWidget(target.btn_undo_bond)

        target.btn_clear_bond = QPushButton("")
        target.btn_clear_bond.setEnabled(False)
        target.btn_clear_bond.clicked.connect(self._clear_bond)
        row1.addWidget(target.btn_clear_bond)

        vmd_layout.addLayout(row1)

        # ── Row 2: 段数 / 半径 (label + slider + edit，同行) ──
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)

        target.lbl_bond_segments = QLabel("")
        grid.addWidget(target.lbl_bond_segments, 0, 0)
        target.bond_nbars_slider = QSlider(Qt.Horizontal)
        target.bond_nbars_slider.setRange(5, 100)
        target.bond_nbars_slider.setValue(20)
        target.bond_nbars_slider.valueChanged.connect(self._on_nbars_slider)
        grid.addWidget(target.bond_nbars_slider, 0, 1)
        target.bond_nbars_edit = QLineEdit("0.20")
        target.bond_nbars_edit.setValidator(QDoubleValidator(0.05, 1.00, 2))
        target.bond_nbars_edit.setMaximumWidth(50)
        target.bond_nbars_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        target.bond_nbars_edit.editingFinished.connect(self._on_nbars_edit)
        grid.addWidget(target.bond_nbars_edit, 0, 2)

        target.lbl_bond_radius = QLabel("")
        grid.addWidget(target.lbl_bond_radius, 0, 3)
        target.bond_radius_slider = QSlider(Qt.Horizontal)
        target.bond_radius_slider.setRange(1, 50)
        target.bond_radius_slider.setValue(6)
        target.bond_radius_slider.valueChanged.connect(self._on_bond_radius_slider)
        grid.addWidget(target.bond_radius_slider, 0, 4)
        target.bond_radius_edit = QLineEdit("0.06")
        target.bond_radius_edit.setValidator(QDoubleValidator(0.01, 0.50, 2))
        target.bond_radius_edit.setMaximumWidth(70)
        target.bond_radius_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        target.bond_radius_edit.editingFinished.connect(self._on_bond_radius_edit)
        grid.addWidget(target.bond_radius_edit, 0, 5)

        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(4, 1)
        vmd_layout.addLayout(grid)

        # 控件变化 → 同步到主窗口 _dash_params
        def _sync_dp():
            self._dash_params['gap'] = target.bond_nbars_slider.value() / 100.0
            self._dash_params['radius'] = target.bond_radius_slider.value() / 100.0
        target.bond_nbars_slider.valueChanged.connect(lambda: _sync_dp())
        target.bond_radius_slider.valueChanged.connect(lambda: _sync_dp())

        return target.grp_draw_bond

    def closeEvent(self, event):
        """关闭程序时，快速清理资源。"""
        # 1) 用短超时尝试优雅关闭 VMD（不阻塞）
        try:
            sock = getattr(self._vmd_session, '_sock', None)
            if sock and self.vmd_port:
                sock.settimeout(0.5)
                sock.sendall(b"quit\n")
        except Exception:
            pass
        # 2) 清理 socket
        self._close_persist_sock()
        # 3) 强制终止 VMD 进程（带超时）
        try:
            subprocess.run(["taskkill", "/IM", "vmd.exe", "/F"],
                           capture_output=True, timeout=3)
        except Exception:
            pass
        # 4) 停掉电荷分析的后台 Multiwfn 线程
        if getattr(self, "charge_panel", None) is not None:
            try:
                self.charge_panel.shutdown()
            except Exception:
                pass
        if getattr(self, "nbo_panel", None) is not None:
            try:
                self.nbo_panel.shutdown()
            except Exception:
                pass
        if getattr(self, "esp_panel", None) is not None:
            try:
                self.esp_panel.shutdown()
            except Exception:
                pass
        if getattr(self, "igmh_panel", None) is not None:
            try:
                self.igmh_panel.shutdown()
            except Exception:
                pass
        if getattr(self, "etsnocv_panel", None) is not None:
            try:
                self.etsnocv_panel.shutdown()
            except Exception:
                pass
        if getattr(self, "mpp_panel", None) is not None:
            try:
                self.mpp_panel.shutdown()
            except Exception:
                pass
        if getattr(self, "aim_panel", None) is not None:
            try:
                self.aim_panel.shutdown()
            except Exception:
                pass
        if getattr(self, "irc_panel", None) is not None:
            try:
                self.irc_panel.shutdown()
            except Exception:
                pass
        if getattr(self, "di_panel", None) is not None:
            try:
                self.di_panel.shutdown()
            except Exception:
                pass
        if getattr(self, "esm_panel", None) is not None:
            try:
                self.esm_panel.shutdown()
            except Exception:
                pass
        # 5) 停掉自旋密度后台线程（cancel_check 使 Multiwfn 快速退出）
        if getattr(self, "_spin_worker", None) is not None:
            try:
                self._spin_worker.stop()
                self._spin_worker.wait(3000)
            except Exception:
                pass
        event.accept()

    def _apply_theme(self):
        self.setStyleSheet(LIGHT_QSS)

    # ═══════════════════════════════════════════════════════════════
    #  i18n Methods
    # ═══════════════════════════════════════════════════════════════
    def _tr(self, key, **fmt):
        s = i18n.TR.get(key, {}).get(i18n._CURRENT_LANG, key)
        return s.format(**fmt) if fmt else s

    def _switch_lang(self):
        i18n._CURRENT_LANG = "en" if i18n._CURRENT_LANG == "zh" else "zh"
        self._lang = i18n._CURRENT_LANG
        self._apply_lang_ui()
        if self._dash_dialog:
            self._dash_dialog._apply_lang()

    def _set_tab_texts(self):
        """设置各 tab 文本并同步分析面板语言（可由新布局子类覆写）。

        1.1 起「VMD 渲染」tab 已取消；tab 顺序：0=可视化控制, 1=轨道绘制,
        2=电荷+键级(合并), 3=NBO, 4=ESP, 5=IGMH, 6=AIM, 7=ETS-NOCV, 8=运行日志。
        主 tabs 为 West 竖排：文字由自定义 QLabel（横排）承载，见
        _setup_west_tab_labels()。
        """
        if not hasattr(self, "_main_nav_ready"):
            self._main_nav_ready = True
            self._setup_main_nav()
        if self.charge_panel is not None:
            self.charge_panel.set_lang(i18n._CURRENT_LANG)
        if getattr(self, "bond_order_panel", None) is not None:
            # 合并后 bond_order_panel 与 charge_panel 指向同一组合面板，避免重复 set_lang
            pass
        if getattr(self, "nbo_panel", None) is not None:
            self.nbo_panel.set_lang(i18n._CURRENT_LANG)
        if getattr(self, "esp_panel", None) is not None:
            self.esp_panel.set_lang(i18n._CURRENT_LANG)
        if getattr(self, "igmh_panel", None) is not None:
            self.igmh_panel.set_lang(i18n._CURRENT_LANG)
        if getattr(self, "aim_panel", None) is not None:
            if hasattr(self.aim_panel, "set_lang"):
                try:
                    self.aim_panel.set_lang(i18n._CURRENT_LANG)
                except Exception:
                    pass
        if getattr(self, "etsnocv_panel", None) is not None:
            if hasattr(self.etsnocv_panel, "set_lang"):
                try:
                    self.etsnocv_panel.set_lang(i18n._CURRENT_LANG)
                except Exception:
                    pass
        if getattr(self, "mpp_panel", None) is not None:
            if hasattr(self.mpp_panel, "set_lang"):
                try:
                    self.mpp_panel.set_lang(i18n._CURRENT_LANG)
                except Exception:
                    pass
        # 画布参数区（一键样式/参数/测键长）随语言刷新
        canvas_panel = getattr(self, "cub_canvas", None)
        if canvas_panel is not None and hasattr(canvas_panel, "set_lang"):
            try:
                canvas_panel.set_lang(i18n._CURRENT_LANG)
            except Exception:
                pass
        # 左侧功能导航条的文字随语言刷新
        self._sync_main_nav()

    # 功能导航条（画布左侧）的 i18n key（与页面顺序一一对应）
    _main_tab_keys = ["tab_viz", "tab_setup", "tab_charge_bond", "tab_nbo",
                      "tab_esp", "tab_igmh", "tab_aim", "tab_etsnocv",
                      "tab_mpp", "tab_irc", "tab_di", "tab_esm", "tab_log"]

    def _setup_main_nav(self):
        """建立画布左侧的功能导航条（QListWidget），并联动右侧页面栈。

        文字横排、宽度固定 110px，9 项全部完整显示；点击项 → 切换
        QStackedWidget 页面；页面索引变化（如有）也会同步回导航条。
        """
        nav = self.main_nav
        nav.clear()
        for key in self._main_tab_keys:
            nav.addItem(self._tr(key))
        nav.currentRowChanged.connect(self._on_nav_row_changed)
        # 页面索引变化（如有代码切换页面）→ 同步导航条高亮 + 画布显隐
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._sync_main_nav()

    def _on_tab_changed(self, index):
        """切换右侧页面：同步导航高亮，并按页面需要显示/隐藏左侧画布。"""
        self._sync_main_nav()
        # 能量跨度（ESM）纯能量分析，不需要画布 → 隐藏左侧画布，右栏占满
        key = self._main_tab_keys[index] \
            if 0 <= index < len(self._main_tab_keys) else ""
        left = getattr(self, "_left_widget", None)
        if left is not None:
            if key == "tab_esm":
                left.hide()
            else:
                left.show()

    def _on_nav_row_changed(self, row):
        """导航条点击 → 切换右侧页面。"""
        if 0 <= row < self.tabs.count() and row != self.tabs.currentIndex():
            self.tabs.setCurrentIndex(row)
        # 切到轨道页时把 HOMO/LUMO 行定位到表格中间（表格在载入 fchk 时
        # 尚未显示，填充期的 scrollToItem 不生效，只能在页面可见后做）
        if 0 <= row < len(self._main_tab_keys) and \
                self._main_tab_keys[row] == "tab_setup":
            QTimer.singleShot(0, self._focus_homo_lumo)

    def _focus_homo_lumo(self):
        """把内嵌轨道表中带 HOMO 标记的行滚动到表格中间、并选中该行。"""
        tabs = getattr(self, "orbital_tabs", None)
        if tabs is None:
            return
        table = tabs.currentWidget()
        if table is None:
            return
        if table.viewport().height() <= 0:
            QTimer.singleShot(50, self._focus_homo_lumo)   # 布局未就绪重试
            return
        for r in range(table.rowCount()):
            it = table.item(r, 3)
            if it is not None and "HOMO" in (it.text() or ""):
                table.selectRow(r)
                table.scrollToItem(
                    table.item(r, 0), QAbstractItemView.PositionAtCenter)
                return

    def _sync_main_nav(self):
        """按当前语言刷新导航条文字，并同步高亮到当前页面。"""
        nav = getattr(self, "main_nav", None)
        if nav is None:
            return
        for i, key in enumerate(self._main_tab_keys):
            if i < nav.count():
                nav.item(i).setText(self._tr(key))
        row = self.tabs.currentIndex()
        if row >= 0 and nav.currentRow() != row:
            nav.blockSignals(True)
            nav.setCurrentRow(row)
            nav.blockSignals(False)

    def _apply_lang_ui(self):
        # Window
        self.setWindowTitle(self._tr("win_title"))
        self._lang_btn.setText(self._tr("lang_btn"))

        # Tabs（路径设置已改为输入栏 ⚙️ 按钮，不再是 tab）
        self._set_tab_texts()

        # Group boxes
        if hasattr(self, "btn_paths"):
            self.btn_paths.setText(self._tr("btn_paths"))
            self.btn_paths.setToolTip(self._tr("tab_paths"))
        self.grp_input.setTitle(self._tr("grp_input"))
        self.grp_orbital.setTitle(self._tr("grp_orbital"))
        self.grp_render.setTitle(self._tr("grp_render"))
        self.grp_actions.setTitle(self._tr("grp_actions"))
        # grp_draw_bond now lives in DashBondDialog

        # MolCanvas toolbar (now in DashBondDialog)

        # Input panel
        self.rb_folder.setText(self._tr("rb_folder"))
        self.rb_file.setText(self._tr("rb_file"))
        self.btn_browse_input.setText(self._tr("btn_browse"))
        self._lang_btn.setText(self._tr("lang_btn"))
        self.var_path.setPlaceholderText(self._tr("placeholder_input"))

        # Orbital panel
        self.lbl_orbital_main.setText(self._tr("lbl_orbital"))
        if hasattr(self, 'btn_preview_both'):
            self.btn_preview_both.setText(self._tr("btn_preview_both"))
            self.btn_preview_both.setToolTip(self._tr("btn_preview_both"))
        if hasattr(self, 'btn_sync_vmd') and self.btn_sync_vmd is not None:
            self.btn_sync_vmd.setText(self._tr("btn_sync_vmd"))
            self.btn_sync_vmd.setToolTip(self._tr("btn_sync_vmd_tip"))
        self.btn_rules.setToolTip(self._tr("orbital_rules_btn"))
        self.btn_rules.setText(self._tr("orbital_rules_btn"))
        self.orbital_tabs.setTabText(self.orbital_tabs.indexOf(self.tab_hint), self._tr("tab_orbit_hint"))

        # 自旋密度行
        if hasattr(self, "btn_spin_density"):
            self.btn_spin_density.setText(self._tr("spin_density_btn"))
            self.btn_spin_density.setToolTip(self._tr("spin_density_iso_tip"))
        if hasattr(self, "lbl_spin_iso"):
            self.lbl_spin_iso.setText(self._tr("spin_density_iso"))
            self.spin_iso.setToolTip(self._tr("spin_density_iso_tip"))

        # VMD 控制台标题
        if hasattr(self, "_vmd_content"):
            self._vmd_content.setTitle(self._tr("vmd_console_title"))
        # AIM 期刊级出图区
        if hasattr(self, "grp_aim_vmd"):
            self.grp_aim_vmd.setTitle(self._tr("aim_vmd_grp"))
            self.lbl_aim_vmd_style.setText(self._tr("aim_vmd_style"))
            self.lbl_aim_vmd_hint.setText(self._tr("aim_vmd_hint"))
            self.btn_aim_vmd_preview.setText(self._tr("aim_vmd_preview"))
            self.btn_aim_vmd_render.setText(self._tr("aim_vmd_render"))

        # Render params
        self.lbl_render_style.setText(self._tr("lbl_style"))
        self.lbl_pos_phase.setText(self._tr("lbl_pos_phase"))
        self.lbl_neg_phase.setText(self._tr("lbl_neg_phase"))
        self.lbl_render_res.setText(self._tr("lbl_res"))
        self.lbl_render_shading.setText(self._tr("lbl_shading"))
        self.rb_shadow.setText(self._tr("rb_full"))
        self.rb_noshadow.setText(self._tr("rb_medium"))
        self.var_auto.setText(self._tr("chk_auto"))
        self.var_open.setText(self._tr("chk_open"))
        self.lbl_trans_raster.setText(self._tr("chk_trans_raster"))
        items = [self._tr("trans_raster3d"), self._tr("trans_vmd"),
                 self._tr("trans_orig"), self._tr("trans_off")]
        current = self.var_trans_raster.currentIndex()
        self.var_trans_raster.clear()
        self.var_trans_raster.addItems(items)
        if current < len(items):
            self.var_trans_raster.setCurrentIndex(current)
        self.var_trans_raster.setToolTip(self._tr("tooltip_trans_raster"))
        self.lbl_render_threads.setText(self._tr("lbl_threads"))

        # Shading tooltips
        self.rb_shadow.setToolTip(self._tr("tooltip_full"))
        self.rb_noshadow.setToolTip(self._tr("tooltip_medium"))
        self.var_trans_raster.setToolTip(self._tr("tooltip_trans_raster"))
        self.var_threads.setToolTip(self._tr("tooltip_threads"))

        # Custom color buttons tooltip
        self.btn_pos_color.setToolTip(self._tr("pick_pos_color"))
        self.btn_neg_color.setToolTip(self._tr("pick_neg_color"))

        # Buttons
        self.btn_run.setText(self._tr("btn_run_cubes"))
        self.btn_preview.setText(self._tr("btn_preview"))
        self.btn_render.setText(self._tr("btn_render_view"))
        self.btn_flip_phase.setText(self._tr("btn_flip_phase"))
        self.btn_dash_mode.setText(self._tr("chk_dash_mode"))

        # Live adjustments
        self.lbl_live_iso.setText(self._tr("lbl_isovalue"))
        self.lbl_live_opacity.setText(self._tr("lbl_opacity"))
        for cap in ("vmd_iso_main_cap", "vmd_dg_cap", "vmd_op_cap",
                    "vmd_ext_cap"):
            w = getattr(self, cap, None)
            if w is not None:
                w.setText(self._tr(
                    {"vmd_iso_main_cap": "lbl_isovalue",
                     "vmd_dg_cap": "lbl_dg_iso",
                     "vmd_op_cap": "lbl_opacity",
                     "vmd_ext_cap": "lbl_ext_radius"}[cap]))
        for chk, key in (("vmd_ext_labels_chk", "chk_ext_values"),
                         ("vmd_colorbar_chk", "chk_colorbar")):
            w = getattr(self, chk, None)
            if w is not None:
                w.setText(self._tr(key))

        # Hydrogen panel
        self.lbl_h_keep.setText(self._tr("lbl_keep_indices"))
        if self._h_hidden:
            self.btn_h_filter.setText(self._tr("btn_show_h"))
        else:
            self.btn_h_filter.setText(self._tr("btn_hide_h"))
        self.var_h_indices.setPlaceholderText(self._tr("placeholder_h_indices"))

        # 轨道表表头（已存在的表随语言刷新）
        headers = [self._tr(k) for k in ("dlg_orbital_col_energy_au",
                                         "dlg_orbital_col_energy_ev",
                                         "dlg_orbital_col_occ",
                                         "dlg_orbital_col_tag")]
        for attr in ("orbital_table_alpha", "orbital_table_beta"):
            t = getattr(self, attr, None)
            if t is not None:
                for c, txt in enumerate(headers):
                    t.horizontalHeaderItem(c).setText(txt)

        # Progress
        self.progress_label.setText(self._tr("progress_ready"))

    def _setup_shortcuts(self):
        pass

    def _deferred_init(self):
        """窗口显示后执行的延迟初始化，减少启动白屏时间。"""
        # QSS 主题（首次加载最重）
        self._apply_theme()
        # 语言 UI
        self._apply_lang_ui()
        # 欢迎日志
        self._append_log("═" * 50)
        self._append_log("GXNU MolStudio 1.0 已启动 — 分子可视化与量子化学分析")
        self._append_log("请拖放 .fchk / .log 文件到界面，或使用「浏览轨道」载入轨道数据")
        self._append_log("═" * 50)
        # 启动预热：splash 盖着窗口时编译全部着色器，消除首操作卡顿
        if self.cub_canvas is not None:
            try:
                self.cub_canvas.warmup_gl()
            except Exception:
                pass

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_PageUp:
            self._key_iso_up()
        elif key == Qt.Key_PageDown:
            self._key_iso_down()
        elif key == Qt.Key_Home:
            self._key_opacity_up()
        elif key == Qt.Key_End:
            self._key_opacity_down()
        else:
            super().keyPressEvent(event)

    # ── Drag & Drop ──────────────────────────────────────────

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            ext = os.path.splitext(path)[1].lower()
            if ext in (".fchk", ".log", ".out", ".cub", ".cube", ".xyz"):
                self.var_path.setText(path)
                self._load_molecule(path)

    # ── Helper Methods ──

    def _make_style_icon(self, style):
        """Build a dual-color icon (pos|neg) for style combo preview."""
        VMD_BUILTIN = {
            12: (0.00, 1.00, 0.00),
            22: (0.00, 0.00, 1.00),
        }
        def _rgb(color_entry):
            if color_entry[1] is not None:
                return [int(c * 255) for c in color_entry[1:4]]
            return [int(c * 255) for c in VMD_BUILTIN.get(color_entry[0], (0.5, 0.5, 0.5))]

        pos = style.get("pos_color", [31, 0.5, 0.5, 0.5])
        neg = style.get("neg_color", [32, 0.5, 0.5, 0.5])
        r1, g1, b1 = _rgb(pos)
        r2, g2, b2 = _rgb(neg)

        pm = QPixmap(30, 13)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(r1, g1, b1))
        p.drawRoundedRect(0, 0, 14, 13, 2, 2)
        p.setBrush(QColor(r2, g2, b2))
        p.drawRoundedRect(16, 0, 14, 13, 2, 2)
        p.end()
        return QIcon(pm)

    def _append_log(self, msg):
        """追加运行日志 — 纯 QTextCursor + QTextCharFormat，不使用 HTML。"""
        if not getattr(self, "log_text", None):
            return  # 日志控件尚未创建（面板构造阶段的消息直接丢弃）
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")

        # ── 标签颜色判定（逻辑不变，颜色适配浅色背景） ──
        if "失败" in msg or "Failed" in msg or "fail" in msg or "错误" in msg:
            tag_color = QColor("#C0392B")
            tag = "ERR"
        elif "成功" in msg or "OK" in msg or "done" in msg or "ready" in msg:
            tag_color = QColor("#27AE60")
            tag = " OK"
        elif "VMD" in msg and ("start" in msg or "Start" in msg or "ready" in msg):
            tag_color = QColor("#2980B9")
            tag = "VMD"
        elif "选中" in msg or "选择" in msg or "Selected" in msg:
            tag_color = QColor("#8E44AD")
            tag = "SEL"
        elif "生成" in msg or "Generating" in msg or "render" in msg.lower():
            tag_color = QColor("#E67E22")
            tag = "GEN"
        elif "写入" in msg or "write" in msg.lower() or "Saved" in msg:
            tag_color = QColor("#16A085")
            tag = "WRT"
        elif "DEBUG" in msg:
            tag_color = QColor("#95A5A6")
            tag = "DBG"
        elif "═" in msg or "━" in msg or "─" in msg:
            # ── 分隔线 ──
            cursor = self.log_text.textCursor()
            cursor.movePosition(QTextCursor.End)
            cursor.insertBlock()
            sep_fmt = QTextCharFormat()
            sep_fmt.setForeground(QColor("#BDC3C7"))
            cursor.insertText(msg, sep_fmt)
            cursor.insertBlock()
            self.log_text.setTextCursor(cursor)
            self.log_text.ensureCursorVisible()
            return
        else:
            tag_color = QColor("#95A5A6")
            tag = "INF"

        # ── 构建各段格式 ──
        # 1) 时间戳 — 浅灰
        time_fmt = QTextCharFormat()
        time_fmt.setForeground(QColor("#95A5A6"))

        # 2) 标签 — 彩色粗体
        tag_fmt = QTextCharFormat()
        tag_fmt.setForeground(tag_color)
        tag_fmt.setFontWeight(QFont.Bold)

        # 3) 正文 — 深色（#2C3E50 在浅/深色背景下均清晰可读）
        body_fmt = QTextCharFormat()
        body_fmt.setForeground(QColor("#2C3E50"))

        # ── 写入 ──
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertBlock()
        cursor.insertText(ts + "  ", time_fmt)
        cursor.insertText("[" + tag + "]", tag_fmt)
        cursor.insertText("  " + msg, body_fmt)

        # ── 自动滚动到底部 ──
        self.log_text.setTextCursor(cursor)
        self.log_text.ensureCursorVisible()

    def _set_progress(self, msg):
        self.progress_label.setText(f"◆  {msg}")

    def _get_style_name(self):
        val = self.var_style.currentText().strip()
        if val:
            return val.split("  ")[0].strip()
        return "sob-art"

    def _get_orbitals(self):
        orb_str = self.var_orbital.text().strip()
        if not orb_str:
            return []
        return [x.strip() for x in orb_str.split(',') if x.strip()]

    def _add_orbital(self, orb):
        current = self.var_orbital.text().strip()
        if not current:
            self.var_orbital.setText(orb)
        else:
            orbs = [x.strip() for x in current.split(',') if x.strip()]
            if orb not in orbs:
                orbs.append(orb)
                self.var_orbital.setText(','.join(orbs))

    def _extract_orbital_name(self, cube_path):
        basename = os.path.basename(cube_path)
        name_without_ext = os.path.splitext(basename)[0]
        if '_MO' in name_without_ext:
            return name_without_ext.rsplit('_MO', 1)[1]
        return name_without_ext

    def _get_paths(self):
        return {
            "multiwfn": self.paths["multiwfn"],
            "vmd": self.paths["vmd"],
            "tachyon": self.paths.get("tachyon", find_tachyon(os.path.dirname(self.paths["vmd"]))),
        }

    def _show_rules_dialog(self):
        """弹窗显示轨道编号规则。"""
        QMessageBox.information(self, self._tr("orbital_rules_btn"),
                                self._tr("orbital_rules"))

    def _open_dash_bond_dialog(self):
        """弹出虚线模式窗口（含画布 + 虚线控制面板）。"""
        # 确保画布有原子数据
        if not self.mol_canvas.atoms:
            QMessageBox.warning(self, self._tr("msg_title_hint"),
                                self._tr("msg_no_cube"))
            return
        # 确保 VMD 已启动
        if not self.vmd_port:
            QMessageBox.warning(self, self._tr("msg_title_hint"),
                                self._tr("msg_preview_first"))
            return
        if self._dash_dialog is not None:
            self._dash_dialog.raise_()
            self._dash_dialog.activateWindow()
            return
        dlg = DashBondDialog(self)
        self._dash_dialog = dlg
        # 启用弹窗内的虚线控件
        dlg._enable_dash_controls()
        # 同步弹窗控件值到 _dash_params
        dp = self._dash_params
        dp['gap'] = dlg.bond_nbars_slider.value() / 100.0
        dp['radius'] = dlg.bond_radius_slider.value() / 100.0
        # 同步 Canvas → VMD 回调
        self.mol_canvas.on_dash_added = self._vmd_draw_dash
        self.mol_canvas.on_dash_undone = self._vmd_undo_bond
        self.mol_canvas.on_dash_cleared = self._vmd_clear_bonds
        # 同步已有的虚线
        self._vmd_dash_pairs.clear()
        for a1, a2, _ in self.mol_canvas.custom_dash_lines:
            pair = (a1, a2)
            if pair not in self._vmd_dash_pairs:
                self._vmd_dash_pairs.append(pair)
        if self._vmd_dash_pairs:
            self._send_vmd_cmd("")
            self._vmd_reapply_dashes()
        dlg.finished.connect(lambda: setattr(self, '_dash_dialog', None))
        dlg.exec_()

    def _open_orbital_browser(self):
        """解析 fchk 并填充画布下方的轨道表格。"""
        path = self.var_path.text().strip()
        if not path:
            QMessageBox.warning(self, self._tr("msg_title_hint"),
                                self._tr("msg_select_file_or_folder"))
            return
        fchk_path = path if os.path.isfile(path) else None
        if not fchk_path:
            fchks = sorted(glob.glob(os.path.join(path, "*.fchk")))
            if not fchks:
                QMessageBox.warning(self, self._tr("msg_title_hint"),
                                    self._tr("msg_no_fchk"))
                return
            fchk_path = fchks[0]
        if not os.path.exists(fchk_path):
            return
        self._fill_orbital_table(fchk_path)

    def _make_orbital_table(self):
        """创建统一的轨道表格。"""
        t = QTableWidget()
        t.setColumnCount(4)
        t.setHorizontalHeaderLabels([
            i18n.tr("dlg_orbital_col_energy_au"),
            i18n.tr("dlg_orbital_col_energy_ev"),
            i18n.tr("dlg_orbital_col_occ"),
            i18n.tr("dlg_orbital_col_tag"),
        ])
        oh = t.horizontalHeader()
        oh.setSectionResizeMode(0, QHeaderView.Stretch)
        oh.setSectionResizeMode(1, QHeaderView.Stretch)
        oh.setSectionResizeMode(2, QHeaderView.Stretch)
        oh.setSectionResizeMode(3, QHeaderView.Stretch)
        t.setSelectionBehavior(QTableWidget.SelectRows)
        t.setAlternatingRowColors(True)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.cellDoubleClicked.connect(self._on_table_orbital_clicked)
        return t

    def _fill_orbital_table(self, fchk_path):
        """解析 fchk 并填充轨道表格（闭壳层单表，开壳层 α/β 双 tab）。"""
        try:
            info = parse_fchk_mo_info(fchk_path)
        except Exception as e:
            self._append_log(f"轨道解析失败: {e}")
            return
        n_a = info["n_alpha"]
        n_b = info["n_beta"]
        homo = info["homo_idx"]
        lumo = info["lumo_idx"]
        alpha_e = info["alpha_energies"]
        beta_e = info.get("beta_energies") or []
        is_open = info["is_open_shell"]
        eV = 27.211386

        # ── 清理 β tab（按 widget 定位，避免硬编码 index 出错）──
        if self.orbital_table_beta:
            self.orbital_tabs.removeTab(self.orbital_tabs.indexOf(self.orbital_table_beta))
            self.orbital_table_beta.deleteLater()
            self.orbital_table_beta = None
        # 重置当前页到 α（注意 index 0 是提示页 tab_hint，α 表在其后）
        self.orbital_tabs.setCurrentIndex(self.orbital_tabs.indexOf(self.orbital_table_alpha))

        # ── 构建数据 ──
        if is_open:
            alpha_rows, beta_rows = [], []
            for i, e in enumerate(alpha_e, 1):
                occ = 1.0 if i <= n_a else 0.0
                tag = ""
                if i == n_a:     tag = "HOMO"
                elif i == n_a+1: tag = "LUMO"
                alpha_rows.append((i, e, e*eV, occ, tag))
            for i, e in enumerate(beta_e, 1):
                occ = 1.0 if i <= n_b else 0.0
                tag = ""
                if i == n_b:     tag = "HOMO"
                elif i == n_b+1: tag = "LUMO"
                beta_rows.append((i, e, e*eV, occ, tag))
            # 能量最高（LUMO 一侧）在上方，能量最低在底部
            alpha_rows = alpha_rows[::-1]
            beta_rows = beta_rows[::-1]
        else:
            alpha_rows = []
            for i, e in enumerate(alpha_e, 1):
                occ = 2.0 if i <= n_a else 0.0
                tag = ""
                if i == homo:     tag = "HOMO"
                elif i == lumo:   tag = "LUMO"
                alpha_rows.append((i, e, e*eV, occ, tag))
            # 能量最高（LUMO 一侧）在上方，能量最低在底部
            alpha_rows = alpha_rows[::-1]

        # ── 填充 α 表 ──
        self._populate_table(self.orbital_table_alpha, alpha_rows, is_open, n_a, orb_sign=1)
        self.orbital_tabs.setTabText(self.orbital_tabs.indexOf(self.orbital_table_alpha),
                                      "α 轨道" if is_open else i18n.tr("dlg_orbital_browser"))

        # ── 开壳层：创建并填充 β 表 ──
        if is_open and beta_rows:
            self.orbital_table_beta = self._make_orbital_table()
            self.orbital_tabs.addTab(self.orbital_table_beta,
                                     i18n.tr("tab_beta"))
            self._populate_table(self.orbital_table_beta, beta_rows, is_open, n_b, orb_sign=-1)

        # 提示 tab（假标签）始终固定到最右端
        self.orbital_tabs.tabBar().moveTab(
            self.orbital_tabs.indexOf(self.tab_hint), self.orbital_tabs.count() - 1)

        self._append_log(
            f"已解析 {len(alpha_rows)}{' + '+str(len(beta_rows)) if is_open else ''}"
            f" 个轨道 (HOMO={homo}, LUMO={lumo if lumo else 'N/A'})")

    def _populate_table(self, table, rows, is_open, homo_idx, orb_sign):
        """填充单个轨道表格。orb_sign=1 为正索引，-1 为负索引（β）。"""
        table.setRowCount(len(rows))
        for r, (orb, energy, ev, occ, tag) in enumerate(rows):
            # orb_sign=-1 → β 轨道，需转 Multiwfn 的 hb/lb 写法
            if orb_sign == -1 and homo_idx:
                if orb == homo_idx:
                    mw_orb = "hb"
                elif orb == homo_idx + 1:
                    mw_orb = "lb"
                elif orb < homo_idx:
                    mw_orb = f"hb-{homo_idx - orb}"
                else:
                    mw_orb = f"lb+{orb - homo_idx - 1}"
            else:
                mw_orb = str(orb)  # α or closed-shell: just the number
            full_orb = orb * orb_sign  # display-only
            # 能量 a.u. (col 0)
            it0 = QTableWidgetItem(f"{energy:.6f}")
            it0.setTextAlignment(Qt.AlignCenter)
            it0.setData(Qt.UserRole, full_orb)        # 显示用（填入 var_orbital）
            it0.setData(Qt.UserRole + 1, mw_orb)       # Multiwfn 用（传给 gen_cube）
            table.setItem(r, 0, it0)
            # 能量 eV (col 1)
            it1 = QTableWidgetItem(f"{ev:.4f}")
            it1.setTextAlignment(Qt.AlignCenter)
            table.setItem(r, 1, it1)
            # 占据 (col 2) — 用 emoji 箭头表示
            if is_open:
                # 开壳层：α=⬆️ β=⬇️
                if occ > 0:
                    occ_text = "⬆️" if orb_sign > 0 else "⬇️"
                else:
                    occ_text = "⬜"
            else:
                # 闭壳层：2.0=⬆️⬇️ 0.0=⬜⬜（空轨道也用两个方框，对应 α/β 两个自旋轨道）
                if occ > 1.5:
                    occ_text = "⬆️⬇️"
                elif occ > 0.5:
                    occ_text = "⬆️"
                else:
                    occ_text = "⬜⬜"
            it2 = QTableWidgetItem(occ_text)
            it2.setTextAlignment(Qt.AlignCenter)
            if occ > 0:
                it2.setBackground(QColor("#E8F5E9"))
            table.setItem(r, 2, it2)
            # 标记 (col 3)
            it3 = QTableWidgetItem(tag)
            it3.setTextAlignment(Qt.AlignCenter)
            if tag == "HOMO":
                it3.setBackground(QColor("#FFF3E0"))
                it3.setFont(QFont("", -1, QFont.Bold))
            elif tag == "LUMO":
                it3.setBackground(QColor("#E3F2FD"))
                it3.setFont(QFont("", -1, QFont.Bold))
            table.setItem(r, 3, it3)
        # 滚动到 HOMO：表格按能量降序排列（最低在底部），
        # 原升序列表中第 homo_idx 个轨道在反转后位于 len(rows)-homo_idx 行
        if homo_idx and 1 <= homo_idx <= len(rows):
            homo_row = len(rows) - homo_idx
            table.scrollToItem(table.item(homo_row, 0))

    def _on_table_orbital_clicked(self, row, _col):
        """双击轨道表格行 → 从 UserRole 取轨道编号并预览。"""
        table = self.orbital_tabs.currentWidget()
        if not table:
            return
        it = table.item(row, 0)
        if not it:
            return
        orb_display = str(it.data(Qt.UserRole))
        orb_mw = it.data(Qt.UserRole + 1) or orb_display  # Multiwfn 写法（开壳层 β 用 hb/lb）
        self.var_orbital.setText(orb_display)
        self._append_log(f"已选择轨道: {orb_display}" + (f" ({orb_mw})" if orb_mw != orb_display else ""))

        # 双击优先走左侧内嵌画布；画布不可用时才回退到 VMD
        if self._canvas_ready():
            self._auto_preview_orbital(orb_mw, target="canvas")
            return

        # ── DEBUG: 切换轨道前的状态 ──
        self._append_log(f"  [DEBUG SWITCH] vmd_port={self.vmd_port} current_iso={self.current_iso} "
                         f"_vmd_state={self._vmd_state} vmd_cube_path={self.vmd_cube_path}")
        self._auto_preview_orbital(orb_mw, target="vmd")

    def _vmd_visualize_selected(self):
        """从表格获取选中轨道并在 VMD 中可视化。"""
        table = self.orbital_tabs.currentWidget()
        if not table:
            return
        row = table.currentRow()
        if row < 0:
            QMessageBox.warning(self, self._tr("msg_title_hint"),
                                self._tr("msg_select_orbital_first"))
            return
        it = table.item(row, 0)
        if not it:
            return
        orb_mw = it.data(Qt.UserRole + 1) or str(it.data(Qt.UserRole))
        orb_display = str(it.data(Qt.UserRole))
        self.var_orbital.setText(orb_display)
        self._append_log(f"VMD可视化: {orb_display}" + (f" ({orb_mw})" if orb_mw != orb_display else ""))
        # 这个按钮是显式的 VMD 入口，始终走 VMD
        self._auto_preview_orbital(orb_mw, target="vmd")

    def _preview_both_selected(self):
        """画布+VMD 双预览。

        - 轨道表格有选中行：按该轨道重新生成 cube，同时渲染到画布与 VMD。
        - 表格未选中，但左侧画布已可视化某轨道：直接把画布当前 cube
          送到 VMD（画布侧已满足），即"VMD+画布"组合功能，无需重新生成。
        """
        table = self.orbital_tabs.currentWidget()
        row = table.currentRow() if table else -1
        if row >= 0:
            it = table.item(row, 0)
            if it:
                orb_mw = it.data(Qt.UserRole + 1) or str(it.data(Qt.UserRole))
                orb_display = str(it.data(Qt.UserRole))
                self.var_orbital.setText(orb_display)
                self._append_log(f"画布+VMD 双预览: {orb_display}"
                                 + (f" ({orb_mw})" if orb_mw != orb_display else ""))
                self._auto_preview_orbital(orb_mw, target="both")
                return

        # 回退：用画布当前已渲染的轨道 cube
        cur = self.cub_canvas.current_cube() if self.cub_canvas else None
        if cur and os.path.isfile(cur):
            self._append_log(f"画布+VMD 双预览（沿用画布当前轨道）: {os.path.basename(cur)}")
            # 画布已有该轨道；仅需把同一 cube 送到 VMD
            self._launch_vmd_orbital(cur)
            return

        QMessageBox.warning(self, self._tr("msg_title_hint"),
                            self._tr("msg_select_orbital_vis"))

    def _auto_preview_orbital(self, orb_str, target="vmd"):
        """选中轨道后：删旧 cube → 生成新 cube → 送到画布或 VMD。

        target: "canvas" 在左侧内嵌 OpenGL 画布渲染；"vmd" 走原有 VMD 流程。
        """
        path = self.var_path.text().strip()
        out = self._get_out_dir(path)
        exe_paths = self._get_paths()
        if not os.path.exists(exe_paths["multiwfn"]):
            return

        # 确定 fchk 文件
        fchk_file = path if os.path.isfile(path) else None
        if not fchk_file:
            fchks = sorted(glob.glob(os.path.join(path, "*.fchk")))
            if not fchks:
                return
            fchk_file = fchks[0]

        # 删旧 cube（仅清理当前分子重新生成的 _MO* 文件）
        stem = os.path.splitext(os.path.basename(fchk_file))[0]
        self._clean_old_cubes(out, stem=stem)

        # 始终生成新 cube
        self._append_log(f"正在生成轨道 {orb_str} 的 cube...")
        self._preview_target = target
        grid = self._canvas_grid()
        self.worker = CubeWorker(
            [fchk_file], out, [orb_str], "0.05", grid, "sob-art",
            (1024, 768), "full", False, exe_paths, False)
        self.worker.log_signal.connect(self._append_log)
        self.worker.progress_signal.connect(self._set_progress)
        self.worker.finished_signal.connect(self._on_orbital_cube_ready)
        self.worker.start()

    def _on_orbital_cube_ready(self, _auto, ok, total, cubes):
        """cube 生成完毕 → 送进左侧画布，或刷新/启动 VMD。"""
        if not cubes:
            self._append_log("Cube 生成失败")
            return
        # cubes[0] 在单轨道模式下是字符串路径，多轨道是 (path, label) 元组
        cube_path = cubes[0] if isinstance(cubes[0], str) else cubes[0][0]

        target = getattr(self, "_preview_target", "vmd")

        if target == "both":
            # 画布 + VMD 同时渲染
            if self._canvas_ready():
                self._append_log(f"在画布中渲染: {os.path.basename(cube_path)}")
                self._push_cubes_to_canvas([cube_path], auto_load=True)
            else:
                self._append_log("[画布] 不可用，仅用 VMD 渲染")
            # 无论画布是否可用，VMD 都要渲染
            self._launch_vmd_orbital(cube_path)
            return

        if target == "canvas" and self._canvas_ready():
            self._append_log(f"在画布中渲染: {os.path.basename(cube_path)}")
            self._push_cubes_to_canvas([cube_path], auto_load=True)
            return

        self._launch_vmd_orbital(cube_path)

    def _clean_old_cubes(self, out_dir, stem=None):
        """删除输出目录中本次将重新生成的旧轨道 cube 文件。

        只清理形如 <fchk名>_MO*.cub/.cube 的自动生成文件（默认匹配全部 _MO*，
        避免误删用户目录里自己保留的 cube 文件）。
        """
        if not out_dir:
            return
        patterns = ([f"{stem}_MO*.cub", f"{stem}_MO*.cube"]
                    if stem else ["*_MO*.cub", "*_MO*.cube"])
        for pat in patterns:
            for f in glob.glob(os.path.join(out_dir, pat)):
                try:
                    os.remove(f)
                except OSError:
                    pass

    def _reset_orbital_state(self, cube_path, iso):
        """切换轨道后重置状态：rep 编号、isovalue 绝对值、相位标记。"""
        self._append_log(f"  [DEBUG RESET] BEFORE: iso={self.current_iso} state={self._vmd_state}")
        self.vmd_cube_path = cube_path
        self.current_iso = abs(float(iso))          # 始终存正值
        self._vmd_state["rep_pos"] = 1
        self._vmd_state["rep_neg"] = 2
        self._vmd_state["molid"] = 0
        self._vmd_orbital_labels = [os.path.basename(cube_path)]
        self._append_log(f"  [DEBUG RESET] AFTER:  iso={self.current_iso} state={self._vmd_state}")

    def _launch_vmd_orbital(self, cube_path):
        """启动或刷新 VMD：先尝试 socket 刷新，失败则启动新进程。"""
        self._append_log(f"  [DEBUG LAUNCH] vmd_port={self.vmd_port} cube={os.path.basename(cube_path)} "
                         f"→ {'refresh' if self.vmd_port else 'new VMD'}")
        if self.vmd_port and self._refresh_vmd_orbital(cube_path):
            self._append_log(f"  [DEBUG LAUNCH] refresh succeeded")
            return
        # 启动新 VMD
        self._append_log(f"  [DEBUG LAUNCH] falling back to _do_preview")
        self._do_preview(cube_path)

    def _refresh_vmd_orbital(self, cube_path):
        """通过 socket 刷新已运行的 VMD：删旧分子 → 加载新 cube → 应用样式。"""
        import tempfile as _tmp
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect(("127.0.0.1", self.vmd_port))

            # 删旧分子
            sock.sendall(b"if {[molinfo num] > 0} {mol delete top}\n")
            try:
                sock.recv(4096)
            except socket.timeout:
                pass

            # 复制 cube 到临时目录（避免中文路径）
            cube_name = os.path.basename(cube_path)
            tmp_dir = _tmp.mkdtemp(prefix="vmd_orbital_")
            tmp_cube = os.path.join(tmp_dir, cube_name)
            shutil.copy2(cube_path, tmp_cube)

            # 用 backend._style_tcl 生成完整场景（分子+等值面+着色）
            style_name = self._get_style_name()
            try:
                iso = float(self.iso_edit.text().strip())
            except ValueError:
                iso = 0.05
            style_tcl = backend._style_tcl(
                cube_name, isovalue=iso, style_name=style_name)
            tcl_path = os.path.join(tmp_dir, "_refresh.tcl")
            with open(tcl_path, "w", encoding="utf-8") as f:
                f.write(style_tcl)

            # 逐条执行关键命令
            cmds = [
                f"cd {tmp_dir.replace(chr(92), '/')}",
                "source _refresh.tcl",
                "display resetview",
            ]
            for cmd in cmds:
                sock.sendall((cmd + "\n").encode("utf-8"))
                try:
                    resp = sock.recv(4096)
                    if b"ERROR" in resp:
                        self._append_log(f"VMD: {resp.decode('utf-8', errors='replace').strip()}")
                except socket.timeout:
                    pass

            sock.close()
            self.vmd_render_dir = tmp_dir   # 更新目录，让 live style 切换能正确写入
            self.vmd_multi_cubes = None
            self._reset_orbital_state(cube_path, iso)   # 统一管理状态
            self._append_log(f"VMD 轨道已刷新: {os.path.basename(cube_path)}")
            return True
        except Exception as e:
            self._append_log(f"VMD socket 刷新失败: {e}")
            self.vmd_port = None
            return False

    # ── 一键同步：画布场景 → VMD ────────────────────────────

    def _ext_vmd_radius(self):
        """VMD 极值点球半径（来自画布下方 VMD 区域滑块；回退 ESP 面板值）。"""
        try:
            sld = getattr(self, "vmd_ext_radius_sld", None)
            if sld is not None:
                return sld.value() / 100.0
        except Exception:
            pass
        try:
            if self.esp_panel is not None and hasattr(self.esp_panel, "sld_ext_radius"):
                return self.esp_panel.sld_ext_radius.value() / 100.0
        except Exception:
            pass
        return 0.25

    def _ext_vmd_labels_on(self):
        """VMD 极值点数值标签开关。"""
        try:
            chk = getattr(self, "vmd_ext_labels_chk", None)
            if chk is not None:
                return bool(chk.isChecked())
        except Exception:
            pass
        try:
            if self.esp_panel is not None and hasattr(self.esp_panel, "chk_ext_labels"):
                return bool(self.esp_panel.chk_ext_labels.isChecked())
        except Exception:
            pass
        return False

    def _ext_vmd_unit(self):
        """VMD 极值点数值单位（跟随 ESP 面板）。"""
        try:
            if self.esp_panel is not None and hasattr(self.esp_panel, "_unit"):
                return str(self.esp_panel._unit)
        except Exception:
            pass
        return "kcal/mol"

    def _ext_vmd_colorbar(self, surfaces):
        """VMD 色标条参数：仅当有 bgr（ESP/IGMH）表面且开关开启时返回。"""
        has_bgr = any(sf.get("type") == "bgr" for sf in surfaces)
        try:
            chk = getattr(self, "vmd_colorbar_chk", None)
            show = bool(chk.isChecked()) if chk is not None else False
        except Exception:
            show = False
        if not (has_bgr and show):
            return None
        low = high = 0.0
        unit = "kcal/mol"
        for sf in surfaces:
            if sf.get("type") == "bgr":
                try:
                    low = float(sf.get("cmin", low))
                    high = float(sf.get("cmax", high))
                except (TypeError, ValueError):
                    pass
        return {"show": True, "low": low, "high": high, "unit": unit,
                "label": "ESP"}

    # ── VMD 控制台弹出窗口 ─────────────────────────────────────
    def _clear_analysis(self):
        """「清空样式」：清空画布上全部分析效果并联动各分析面板。
        保留分子与渲染样式设置；各面板调用容错，个别异常不影响整体。"""
        glw = self.cub_canvas.glw if self.cub_canvas is not None else None
        if glw is not None:
            try:
                glw.clear_analysis()
            except Exception:
                pass
        if getattr(self, "esp_panel", None) is not None:
            try:
                self.esp_panel._clear_canvas()
                self.esp_panel._extrema_pts = []
            except Exception:
                pass
        if getattr(self, "igmh_panel", None) is not None:
            try:
                self.igmh_panel._clear_canvas()
            except Exception:
                pass
        if getattr(self, "aim_panel", None) is not None:
            try:
                self.aim_panel.clear_canvas()
            except Exception:
                pass

    def _open_vmd_console(self):
        """弹出独立的 VMD 控制台窗口，并把画布场景同步到 VMD（VMD 独立窗口）。

        VMD 本身不嵌入（保持独立窗口）；仅把「VMD 控制台」按钮组放进一个
        可弹出的独立窗口。窗口不设 parent（QWidget(None) + Qt.Window），
        使其成为完全独立的顶层窗口，不随主窗口最小化/最大化。
        控制台窗口不设 WA_DeleteOnClose，close() 默认即隐藏而非销毁，
        _vmd_content 始终保持有效，避免二次引用崩溃。
        """
        if self._vmd_console_win is None:
            win = QWidget(None)
            win.setWindowFlags(Qt.Window)
            win.setWindowTitle(self._tr("vmd_console_title"))
            win.resize(760, 620)
            # 独立窗口不继承主窗口样式表，需单独应用主题 QSS
            win.setStyleSheet(LIGHT_QSS)
            lay = QVBoxLayout(win)
            lay.setContentsMargins(8, 8, 8, 8)
            lay.setSpacing(6)
            if getattr(self, "_vmd_content", None) is not None:
                lay.addWidget(self._vmd_content)
            self._vmd_console_win = win

        self._vmd_console_win.show()
        self._vmd_console_win.raise_()
        self._vmd_console_win.activateWindow()

        # 同步画布场景到 VMD（独立窗口）
        self._sync_canvas_to_vmd()

    def _close_vmd_console(self):
        """主窗口退出前关闭控制台窗口（避免无 parent 的孤儿窗口阻止退出）。"""
        win = getattr(self, "_vmd_console_win", None)
        if win is not None:
            try:
                win.close()   # 仅隐藏，不销毁
                win.deleteLater()
            except Exception:
                pass
            self._vmd_console_win = None

    def _sync_canvas_to_vmd(self):
        """把左侧画布当前场景（分子 + 等值面 + 配色 + 极值点）同步到 VMD。

        场景来源：
          - 分子：glw._molecule / cube 原子（球棍 + 片段着色 + H 过滤）
          - 表面：各面板登记在 glw 上的 vmd_scene（orbital / bgr 两类）
          - 极值点 / 不透明度：直接读画布当前状态
        VMD 已运行时走 socket 刷新，否则启动新进程。
        """
        if not self._canvas_ready():
            QMessageBox.warning(self, self._tr("msg_title_hint"),
                                self._tr("msg_gl_unavailable"))
            return
        glw = self.cub_canvas.glw

        # ── 分子原子（Bohr → Å） ──
        if glw._molecule:
            raw = [(int(m[0]), float(m[2]), float(m[3]), float(m[4]))
                   for m in glw._molecule]
        elif glw._cube is not None and getattr(glw._cube, "atoms", None):
            raw = [(int(a[0]), float(a[2]), float(a[3]), float(a[4]))
                   for a in glw._cube.atoms]
        else:
            QMessageBox.warning(self, "提示", self._tr("msg_sync_no_molecule"))
            return
        conv = 0.529177210903
        xyz_lines = [f"{len(raw)}", "MolStudio canvas sync"]
        for anum, x, y, z in raw:
            sym = ELEMENT_SYMBOLS.get(anum, "X")
            xyz_lines.append(f"{sym:2s} {x * conv:.6f} {y * conv:.6f} {z * conv:.6f}")
        xyz_text = "\n".join(xyz_lines) + "\n"

        # ── 表面（过滤不存在的文件） ──
        reg = glw.vmd_scene() or {}
        surfaces = []
        for sf in reg.get("surfaces", []):
            st = sf.get("type")
            if st == "orbital":
                if sf.get("vol") and os.path.isfile(sf["vol"]):
                    surfaces.append(dict(sf))
            elif st == "pqr":
                # MPP：PQR 电荷着色表面（无 vol/color_vol，只有 pqr 文件）
                if sf.get("pqr") and os.path.isfile(sf["pqr"]):
                    surfaces.append(dict(sf))
            else:
                if (sf.get("vol") and os.path.isfile(sf["vol"])
                        and sf.get("color_vol") and os.path.isfile(sf["color_vol"])):
                    surfaces.append(dict(sf))

        # ── 相位色：首个轨道用自定义色（若有），其余用多轨道色板 ──
        pal = ovlib.VMDOrbitalSession.MULTI_ORBIT_COLORS
        for i, sf in enumerate(surfaces):
            if sf.get("type") != "orbital":
                continue
            if i == 0:
                if self._custom_pos_rgb:
                    sf["pos_color"] = (31, self._custom_pos_rgb[0] / 255.0,
                                       self._custom_pos_rgb[1] / 255.0,
                                       self._custom_pos_rgb[2] / 255.0)
                if self._custom_neg_rgb:
                    sf["neg_color"] = (32, self._custom_neg_rgb[0] / 255.0,
                                       self._custom_neg_rgb[1] / 255.0,
                                       self._custom_neg_rgb[2] / 255.0)
            else:
                p = pal[(i - 1) % len(pal)]
                sf["pos_color"] = tuple(p["pos"])
                sf["neg_color"] = tuple(p["neg"])

        # ── 片段原子着色（1-based → VMD 0-based index 选择，按颜色分组） ──
        overrides = dict(getattr(glw, "_atom_color_overrides", None) or {})
        # 元素原子颜色覆盖 → 展开为原子索引覆盖（原子索引覆盖优先）
        elem_ov = dict(getattr(glw, "_element_color_overrides", None) or {})
        if elem_ov:
            if getattr(glw, "_molecule", None):
                src_atoms = [(int(a[0]),) for a in glw._molecule]
            elif glw._cube is not None and getattr(glw._cube, "atoms", None):
                src_atoms = [(int(a[0]),) for a in glw._cube.atoms]
            else:
                src_atoms = []
            for i, at in enumerate(src_atoms, start=1):
                if i not in overrides and at[0] in elem_ov:
                    overrides[i] = elem_ov[at[0]]
        groups = {}
        for idx, rgb in overrides.items():
            key = tuple(round(float(c), 3) for c in rgb)
            groups.setdefault(key, []).append(int(idx) - 1)
        atom_groups = []
        cid = 20
        for rgb, idxs in groups.items():
            atom_groups.append({
                "sel": "index " + " ".join(str(i) for i in sorted(idxs)),
                "cid": cid, "rgb": rgb})
            cid += 1

        # ── H 过滤（沿用画布当前状态） ──
        keep_h = None
        if self._h_hidden:
            h_str = self.var_h_indices.text().strip()
            if h_str:
                try:
                    keep_h = [int(x.strip()) - 1 for x in h_str.split(",")
                              if x.strip()]
                except ValueError:
                    keep_h = []
            else:
                keep_h = []

        # ── 极值点（Bohr → Å，含数值） ──
        # 坐标/种类在 _extrema_pts（(x,y,z,kind)，Bohr）；数值在 _extrema_vals
        #（与 _extrema_pts 对齐，显示单位跟随 ESP 面板 _unit）
        ext_pts = list(getattr(glw, "_extrema_pts", []) or [])
        ext_vals = list(getattr(glw, "_extrema_vals", []) or [])
        unit = self._ext_vmd_unit()
        extrema = []
        ext_values = []
        for i, (x, y, z, kind) in enumerate(ext_pts):
            extrema.append((float(x) * conv, float(y) * conv,
                            float(z) * conv, kind))
            try:
                v = float(ext_vals[i]) if i < len(ext_vals) else 0.0
            except (TypeError, ValueError):
                v = 0.0
            ext_values.append((v, unit))
        if not extrema:
            # 兼容旧数据：_extrema_pts 里可能直接带数值（5 元组）
            for item in (getattr(glw, "_extrema_pts", []) or []):
                if len(item) >= 5:
                    try:
                        x, y, z, kind, v = (float(item[0]), float(item[1]),
                                             float(item[2]), item[3], float(item[4]))
                        extrema.append((x * conv, y * conv, z * conv, kind))
                        ext_values.append((v, unit))
                    except (TypeError, ValueError):
                        pass

        # ── AIM 临界点 / 键径（Bohr → Å，颜色/类型随画布 AIM overlay） ──
        # glw._aim_cps = [(x, y, z, (r,g,b), serial, cp_type)]，世界帧 Bohr；
        # _aim_path_pts = [(x, y, z)] 世界帧 Bohr；半径属性单位 Å
        aim_cps = []
        for item in (getattr(glw, "_aim_cps", []) or []):
            try:
                ax, ay, az = float(item[0]), float(item[1]), float(item[2])
            except (TypeError, ValueError, IndexError):
                continue
            col = tuple(float(c) for c in item[3][:3]) if len(item) > 3 else None
            serial = int(item[4]) if len(item) > 4 else 0
            ct = str(item[5]) if len(item) > 5 else "N"
            aim_cps.append((ax * conv, ay * conv, az * conv, col, serial, ct))
        aim_paths = []
        for p in (getattr(glw, "_aim_path_pts", []) or []):
            try:
                aim_paths.append((float(p[0]) * conv, float(p[1]) * conv,
                                  float(p[2]) * conv))
            except (TypeError, ValueError, IndexError):
                continue
        aim_overlay = None
        if aim_cps or aim_paths:
            aim_overlay = {
                "cps": aim_cps,
                "paths": aim_paths,
                "cp_radius": getattr(glw, "_aim_cp_radius", None),
                "path_radius": getattr(glw, "_aim_path_radius", None),
            }

        # ── 不透明度 ──
        op = None
        try:
            sp = getattr(glw, "_sp", None)
            if sp is not None and "opacity" in sp:
                op = sp["opacity"]
        except Exception:
            op = None

        # IGMH 场景：δg 等值面 / 不透明度以画布左下方 VMD 控制区滑块为准
        #（默认 0.004 / 0.75，对齐 IGMH-V4），同步覆盖场景值
        for sf in surfaces:
            if sf.get("kind") == "igmh":
                try:
                    sf["iso"] = self.vmd_iso_sld.value() / 1000.0
                except Exception:
                    pass
                try:
                    op = self.vmd_op_sld.value() / 100.0
                except Exception:
                    pass

        # 球棍配色方案：ESP 场景登记 atom_color="Name"（对齐 ESPViewer2），其余默认 Element
        atom_color = "Element"
        for sf in surfaces:
            if sf.get("atom_color"):
                atom_color = str(sf["atom_color"])
                break

        scene = {
            "xyz": "scene.xyz",
            "xyz_text": xyz_text,
            "surfaces": surfaces,
            "atom_groups": atom_groups,
            "keep_h": keep_h,
            "extrema": extrema,
            "ext_values": ext_values,
            "ext_radius": self._ext_vmd_radius(),
            "ext_show_labels": self._ext_vmd_labels_on(),
            "colorbar": self._ext_vmd_colorbar(surfaces),
            "opacity": op,
            "atom_color": atom_color,
            "aim_overlay": aim_overlay,
        }

        exe = self._get_paths()["vmd"]
        if not exe or not os.path.exists(exe):
            QMessageBox.warning(self, "提示", self._tr("msg_no_vmd"))
            return
        style_name = self._get_style_name()
        _, _, _, _, _, shade_mode = self._get_params()

        self._append_log(self._tr("log_sync_vmd_start", n=len(surfaces)))

        launched = False
        if self.vmd_port:
            launched = self._refresh_vmd_scene(scene, style_name, shade_mode)
        if not launched:
            try:
                port, render_dir = backend.preview_scene(
                    scene, style_name, vmd_exe=exe, shade_mode=shade_mode)
            except Exception as e:
                self._append_log(self._tr("log_sync_vmd_fail", err=e))
                return
            if not port:
                self._append_log(self._tr("log_sync_vmd_fail", err="VMD 启动失败"))
                return
            self.vmd_port = port
            self.vmd_render_dir = render_dir
            self._vmd_session.port = port
            self._vmd_session.render_dir = render_dir
            self._vmd_session._current_style = style_name
            self._vmd_session._multi_cubes = None
            self._vmd_session._mol_mode = False
            self.vmd_multi_cubes = None
            self._vmd_style_applied = style_name

        # ── 状态复位（iso 取第一个表面；无表面用画布当前 iso） ──
        labels = [str(sf.get("label") or os.path.basename(sf.get("vol") or sf.get("pqr") or ""))
                  for sf in surfaces]
        first_iso = 0.05
        if surfaces:
            try:
                first_iso = float(surfaces[0].get("iso", 0.05))
            except (TypeError, ValueError):
                pass
        self.current_iso = abs(first_iso)
        self.current_opacity = op
        self._vmd_orbital_labels = labels
        # 清理已不在场景中的轨道翻转状态（避免残留导致错位）
        try:
            self._vmd_orbital_flips = {
                k: v for k, v in self._vmd_orbital_flips.items() if k in labels}
        except Exception:
            pass
        self._vmd_session._vmd_state["rep_pos"] = 1
        self._vmd_session._vmd_state["rep_neg"] = 2
        self._vmd_session._current_isovalue = self.current_iso
        self._vmd_session._current_opacity = op

        # ── 控件启用 ──
        self.btn_render.setEnabled(True)
        self.btn_dash_mode.setEnabled(True)
        self.btn_h_filter.setEnabled(True)
        self.btn_flip_phase.setEnabled(True)
        self.iso_slider.setEnabled(True)
        self.iso_slider.blockSignals(True)
        self.iso_slider.setValue(int(self.current_iso * 1000))
        self.iso_slider.blockSignals(False)
        self.iso_edit.setEnabled(True)
        self.iso_edit.setText(f"{self.current_iso:.3f}")
        self.opacity_slider.setEnabled(True)
        self.opacity_edit.setEnabled(True)
        if self.current_opacity is not None:
            self.opacity_slider.blockSignals(True)
            self.opacity_slider.setValue(int(self.current_opacity * 100))
            self.opacity_slider.blockSignals(False)
            self.opacity_edit.setText(f"{self.current_opacity:.2f}")

        # ── 虚线重放（VMD 场景重建后） ──
        self.mol_canvas.on_dash_added = self._vmd_draw_dash
        self.mol_canvas.on_dash_undone = self._vmd_undo_bond
        self.mol_canvas.on_dash_cleared = self._vmd_clear_bonds
        if self._vmd_dash_pairs:
            self._vmd_reapply_dashes()

        self._append_log(self._tr("log_sync_vmd_ok"))

    def _refresh_vmd_scene(self, scene, style_name, shade_mode):
        """通过 socket 刷新运行中的 VMD：删全部分子 → source 新场景脚本。"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect(("127.0.0.1", self.vmd_port))
            render_dir, tcl_name = backend.build_scene_tcl(
                scene, style_name, shade_mode, port=None)
            sock.sendall(b"mol delete all\n")
            try:
                sock.recv(4096)
            except socket.timeout:
                pass
            for cmd in (f"cd {render_dir.replace(chr(92), '/')}",
                        f"source {tcl_name}"):
                sock.sendall((cmd + "\n").encode("utf-8"))
                try:
                    resp = sock.recv(4096)
                    if b"ERROR" in resp:
                        self._append_log("VMD: " + resp.decode(
                            "utf-8", errors="replace").strip())
                except socket.timeout:
                    pass
            sock.close()
            self.vmd_render_dir = render_dir
            self._vmd_session.render_dir = render_dir
            self._vmd_session._current_style = style_name
            self._append_log("VMD 场景已刷新")
            return True
        except Exception as e:
            self._append_log(f"VMD socket 刷新失败: {e}")
            self.vmd_port = None
            return False

    def _open_paths_dialog(self):
        """打开软件路径设置对话框（Multiwfn / VMD / Tachyon + 致谢）。"""
        dlg = PathsDialog(self.paths,
                          self._ack_html(i18n._CURRENT_LANG == "zh"),
                          self._tr, self)
        dlg.exec_()

    @staticmethod
    def _ack_html(is_cn):
        if is_cn:
            return (
                "<p><b>Multiwfn</b><br>"
                "本软件的核心计算引擎来自 <b>卢天</b> 老师开发的 "
                "<b>Multiwfn</b> 多功能波函数分析程序，特此致以最诚挚的感谢！</p>"
                "<p style='font-size:9pt;color:#c00'>"
                "⚠️ 使用本软件绘图时，请务必规范引用以下文章：</p>"
                "<p style='font-size:9pt;color:#666'>"
                "Tian Lu, Feiwu Chen, <i>Multiwfn: A Multifunctional Wavefunction Analyzer</i>, "
                "J. Comput. Chem., 2012, 33, 580–592.<br>"
                "Tian Lu, <i>A Comprehensive Electron Wavefunction Analysis Toolbox for Chemists, Multiwfn</i>, "
                "J. Chem. Phys., 2024, 161, 082503. <i>(JCP Editors' Choice 2024)</i></p>"
                "<p>Multiwfn 目前已被超过 <b>4 万篇</b> 论文引用，用户遍布全球 <b>90 余国</b>。</p>"
                "<p><b>vcube2.0</b><br>"
                "渲染样式系统源自 <b>vcube2.0</b>（钟成老师），提供了 11 套精美的 VMD 轨道渲染配置。</p>"
                "<p><b>IboView</b><br>"
                "球棍模型、键的锥形圆柱几何、双指数镜面反射光照模型及深度剥离透明渲染，"
                "均移植自 <b>Gerald Knizia</b> 开发的 <b>IboView</b> "
                "(<a href='https://www.iboview.org'>www.iboview.org</a>)，特此致谢。</p>"
                "<p><b>IGMH / IRI</b><br>"
                "IGMH 与 IRI 分析方法来自 <b>卢天</b> 老师课题组：<br>"
                "Tian Lu, Qinxue Chen, <i>Independent gradient model based on "
                "Hirshfeld partition: A new method for visual study of interactions "
                "in chemical systems</i>, J. Comput. Chem., 2022, 43, 539–553.<br>"
                "Tian Lu, Qinxue Chen, <i>Interaction region indicator (IRI): A simple "
                "real space function clearly revealing both chemical bonds and weak "
                "interactions</i>, Chemistry–Methods, 2021, 1, 231–239.</p>"
                "<p><b>虚线绘制</b><br>"
                "VMD 虚线绘制功能来自 KeinSci 论坛 <b>Eming 老师</b> 的 <b>draw_bond Tcl 脚本</b>，特此致谢。</p>"
                "<p><b>VMD</b><br>"
                "Humphrey, W., Dalke, A. and Schulten, K., "
                "<i>VMD: Visual Molecular Dynamics</i>, J. Molec. Graphics, 1996, 14, 33–38.</p>"
                "<p><b>Tachyon</b><br>"
                "Stone, J. E., <i>An Efficient Library for Parallel Ray Tracing and Animation</i>, "
                "M.Sc. Thesis, University of Missouri-Rolla, 1998.</p>"
            )
        else:
            return (
                "<p><b>Multiwfn</b><br>"
                "The core calculation engine of this software comes from <b>Multiwfn</b>, "
                "a multifunctional wavefunction analysis program developed by <b>Prof. Tian Lu</b>. "
                "Our sincere gratitude!</p>"
                "<p style='font-size:9pt;color:#c00'>"
                "⚠️ If you use this software to generate images, please properly cite the following articles:</p>"
                "<p style='font-size:9pt;color:#666'>"
                "Tian Lu, Feiwu Chen, <i>Multiwfn: A Multifunctional Wavefunction Analyzer</i>, "
                "J. Comput. Chem., 2012, 33, 580–592.<br>"
                "Tian Lu, <i>A Comprehensive Electron Wavefunction Analysis Toolbox for Chemists, Multiwfn</i>, "
                "J. Chem. Phys., 2024, 161, 082503. <i>(JCP Editors' Choice 2024)</i></p>"
                "<p>Multiwfn has been cited by over <b>40,000</b> papers across <b>90+</b> countries.</p>"
                "<p><b>vcube2.0</b><br>"
                "The rendering style system originates from <b>vcube2.0</b> (by Zhong Cheng), "
                "providing 11 elegant VMD orbital rendering presets.</p>"
                "<p><b>IboView</b><br>"
                "The ball-and-stick model, tapered-cylinder bond geometry, dual-exponential "
                "specular lighting model and depth-peeling transparency rendering are all "
                "ported from <b>IboView</b> by <b>Gerald Knizia</b> "
                "(<a href='https://www.iboview.org'>www.iboview.org</a>). Many thanks!</p>"
                "<p><b>IGMH / IRI</b><br>"
                "The IGMH and IRI methods were developed by <b>Prof. Tian Lu</b>'s group:<br>"
                "Tian Lu, Qinxue Chen, <i>Independent gradient model based on "
                "Hirshfeld partition: A new method for visual study of interactions "
                "in chemical systems</i>, J. Comput. Chem., 2022, 43, 539–553.<br>"
                "Tian Lu, Qinxue Chen, <i>Interaction region indicator (IRI): A simple "
                "real space function clearly revealing both chemical bonds and weak "
                "interactions</i>, Chemistry–Methods, 2021, 1, 231–239.</p>"
                "<p><b>Draw Bond</b><br>"
                "The VMD dashed bond feature is based on the <b>draw_bond Tcl script</b> "
                "by <b>Eming 老师</b> from the KeinSci forum. Many thanks!</p>"
                "<p><b>VMD</b><br>"
                "Humphrey, W., Dalke, A. and Schulten, K., "
                "<i>VMD: Visual Molecular Dynamics</i>, J. Molec. Graphics, 1996, 14, 33–38.</p>"
                "<p><b>Tachyon</b><br>"
                "Stone, J. E., <i>An Efficient Library for Parallel Ray Tracing and Animation</i>, "
                "M.Sc. Thesis, University of Missouri-Rolla, 1998.</p>"
            )

    def _do_save_paths(self, dlg, mw, vmd, tachyon=""):
        if mw:
            self.paths["multiwfn"] = mw
        if vmd:
            self.paths["vmd"] = vmd
        # 若用户未指定 tachyon，则自动检测 VMD 目录下的版本
        tachyon = tachyon or find_tachyon(os.path.dirname(vmd or self.paths["vmd"]))
        self.paths["tachyon"] = tachyon
        try:
            backend.save_config(
                self.paths["multiwfn"], self.paths["vmd"], tachyon)
        except Exception as e:
            # 打包版配置文件写在 exe 同目录；目录只读或被杀软拦截时
            # 写入会失败。弹窗提示而不是放任异常静默闪退。
            QMessageBox.warning(
                self, self._tr("msg_title_hint"),
                self._tr("msg_paths_save_fail", err=e,
                         cfg=backend.CONFIG_FILE))
            return
        self._append_log(self._tr("log_paths_saved",
                                  mw=self.paths["multiwfn"],
                                  vmd=self.paths["vmd"]))
        if dlg:
            dlg.accept()

    def _get_params(self):
        orbitals = self._get_orbitals()
        orbital = orbitals[0] if orbitals else ""
        try:
            iso = float(self.iso_edit.text().strip())
        except ValueError:
            iso = 0.05
        grid = self._canvas_grid()
        style_name = self._get_style_name()
        try:
            res_str = self.var_res.currentText().strip()
            w, h = res_str.split("x")
            resolution = (int(w), int(h))
        except (ValueError, AttributeError):
            resolution = (2000, 1500)
        shade_id = self.shade_group.checkedId()
        shade_mode = "full" if shade_id == 0 else "noshadow"
        return orbital, iso, grid, style_name, resolution, shade_mode

    # ── Browse Methods ──

    def _browse_input(self):
        if self.mode_group.checkedId() == 0:
            path = existing_directory(self, self._tr("dlg_select_input_folder"))
        else:
            path, _ = open_file(
                self, self._tr("dlg_select_input_file"), "",
                self._tr("dlg_input_filter"))
        if path:
            self.var_path.setText(path)
            self._load_molecule(path)

    def _load_molecule(self, path):
        """Parse fchk/cub/log atoms and display in MolCanvas."""
        if not path or not os.path.isfile(path):
            return
        # 载入新分子时清空电荷分析状态与左侧画布上的电荷着色 / 键级选中
        if getattr(self, "charge_panel", None) is not None:
            # ChargeBondPanel.reset_view_state 会同时清空电荷着色与键级选中
            self.charge_panel.reset_view_state()
        if getattr(self, "nbo_panel", None) is not None:
            self.nbo_panel.reset_view_state()
        if getattr(self, "esp_panel", None) is not None:
            self.esp_panel.reset_view_state()
        if getattr(self, "igmh_panel", None) is not None:
            self.igmh_panel.reset_view_state()
        ext = os.path.splitext(path)[1].lower()
        atoms, bonds = [], []
        if ext == ".fchk":
            parser = get_atoms_from_fchk
            bond_parser = get_bonds_from_fchk
        elif ext in (".cub", ".cube"):
            parser = get_atoms_from_cube
            bond_parser = get_bonds_from_cube
        elif ext in (".log", ".out"):
            # Use Gaussian log parser from backend
            try:
                atoms, bonds = backend.parse_log(path)
            except Exception:
                atoms, bonds = [], []
            if atoms:
                self.mol_canvas.set_data(atoms, bonds)
                if self.cub_canvas is not None:
                    self.cub_canvas.set_molecule(atoms, bonds)
                self._current_fchk = None
                self.btn_run.setEnabled(False)
                self.btn_preview.setEnabled(True)
                if _HAS_GL_VIEWER:
                    getattr(self, "btn_gl_preview", None)  # OpenGL 按钮已移除
                self.btn_render.setEnabled(False)
                self.btn_dash_mode.setEnabled(True)
                self._update_color_buttons()
                # Show log file info
                log_info = backend.parse_log_info(path)
                info_str = " | ".join(f"{k}: {v}" for k, v in log_info.items())
                self._append_log(
                    f"{len(atoms)} atoms, {len(bonds)} bonds  |  {os.path.basename(path)}\n"
                    f"  {info_str}")
                return
            else:
                self._append_log(f"Failed to parse log file: {os.path.basename(path)}")
                return
        elif ext == ".xyz":
            atoms, bonds = self._parse_xyz(path)
            if atoms:
                self.mol_canvas.set_data(atoms, bonds)
                if self.cub_canvas is not None:
                    self.cub_canvas.set_molecule(atoms, bonds)
                self._current_fchk = None
                self.btn_run.setEnabled(False)
                self.btn_preview.setEnabled(True)
                if _HAS_GL_VIEWER:
                    getattr(self, "btn_gl_preview", None)  # OpenGL 按钮已移除
                self.btn_render.setEnabled(False)
                self.btn_dash_mode.setEnabled(True)
                self._update_color_buttons()
                self._append_log(
                    f"{len(atoms)} atoms, {len(bonds)} bonds  |  {os.path.basename(path)}")
                # 清理轨道表格
                self._clear_orbital_table()
                return
            else:
                self._append_log(f"Failed to parse XYZ file: {os.path.basename(path)}")
                return
        else:
            return
        try:
            atoms = parser(path)
            if atoms:
                bonds = bond_parser(atoms)
                self.mol_canvas.set_data(atoms, bonds)
                if self.cub_canvas is not None:
                    self.cub_canvas.set_molecule(atoms, bonds)
                self._current_fchk = path
                self.btn_run.setEnabled(True)  # fchk 需要生成 cub
                self.btn_dash_mode.setEnabled(True)
                self._update_color_buttons()
                self._append_log(
                    self._tr("mol_hint_atoms",
                             natoms=len(atoms), nbonds=len(bonds),
                             name=os.path.basename(path)))
                # 自动填充轨道表格
                if ext == ".fchk":
                    self._fill_orbital_table(path)
                # 载入 .cub/.cube 文件：禁用"生成cub"，直接预览此文件
                if ext in (".cub", ".cube"):
                    self._current_cubes = [path]
                    self.btn_preview.setEnabled(True)
                    if _HAS_GL_VIEWER:
                        getattr(self, "btn_gl_preview", None)  # OpenGL 按钮已移除
                    self.btn_run.setEnabled(False)
                    self._append_log(
                        self._tr("log_start_preview").format(os.path.basename(path)))
                    # 直接在左侧画布显示这个 cube
                    self._push_cubes_to_canvas([path], auto_load=True)
            else:
                self._append_log(self._tr("mol_hint_no_atoms"))
        except Exception as e:
            import traceback
            self._append_log(f"Parse error: {e}\n{traceback.format_exc()}")

    def _parse_xyz(self, path):
        """Parse XYZ file → (atoms, bonds) tuples."""
        atoms = []
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = [l.strip() for l in f if l.strip()]
        if len(lines) < 3:
            return [], []
        try:
            natom = int(lines[0])
        except ValueError:
            return [], []
        # 跳过 comment 行, 从第2行开始解析原子
        start = 2 if len(lines) > 2 and not lines[1][0].isalpha() else 1
        center = 0
        for line in lines[start:start + natom]:
            parts = line.split()
            if len(parts) < 4:
                continue
            symbol = parts[0]
            try:
                x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
            except ValueError:
                continue
            # 元素序号：兼容 "C"/"cl"/"Cl" 及直接写原子序数两种 XYZ 写法，
            # 缺失时回退 0（避免 GL 画布按 0 号占位色渲染成黑色）。
            if symbol.isdigit():
                an = int(symbol)
            else:
                an = _SYMBOL_TO_AN.get(symbol.capitalize(), 0)
            center += 1
            atoms.append((center, symbol, an, (x, y, z)))
        bonds = get_bonds_from_fchk(atoms) if atoms else []
        return atoms, bonds

    # ── Core Actions ──

    def _clear_orbital_table(self):
        """清空轨道表格（非 fchk 文件无轨道数据）。"""
        self.orbital_table_alpha.setRowCount(0)
        if self.orbital_table_beta:
            self.orbital_tabs.removeTab(self.orbital_tabs.indexOf(self.orbital_table_beta))
            self.orbital_table_beta.deleteLater()
            self.orbital_table_beta = None

    def _get_out_dir(self, input_path=None):
        """输出目录 = 输入目录。"""
        if input_path is None:
            input_path = self.var_path.text().strip()
        return input_path if os.path.isdir(input_path) else os.path.dirname(input_path)

    def _run_cubes(self):
        if self.running:
            return
        path = self.var_path.text().strip()
        if not path:
            QMessageBox.warning(self, self._tr("msg_title_hint"),
                                self._tr("msg_select_file_or_folder"))
            return

        # Auto-parse molecular structure
        self._load_molecule(path)

        exe_paths = self._get_paths()
        if not os.path.exists(exe_paths["multiwfn"]):
            QMessageBox.warning(self, self._tr("msg_title_error"),
                self._tr("msg_mw_not_found", path=exe_paths['multiwfn']))
            return
        if not os.path.exists(exe_paths["vmd"]):
            QMessageBox.warning(self, self._tr("msg_title_error"),
                self._tr("msg_vmd_not_found", path=exe_paths['vmd']))
            return

        files = (sorted(glob.glob(os.path.join(path, "*.fchk")))
                 if os.path.isdir(path) else [path])
        if not files:
            QMessageBox.warning(self, self._tr("msg_title_hint"),
                                self._tr("msg_no_fchk"))
            return

        out = self._get_out_dir(path)
        os.makedirs(out, exist_ok=True)

        orbitals = self._get_orbitals()
        if not orbitals:
            QMessageBox.warning(self, self._tr("msg_title_hint"),
                                self._tr("msg_enter_orbital"))
            return

        orbital, iso, grid, style_name, resolution, shade_mode = self._get_params()
        auto_render = self.var_auto.isChecked()
        do_open = self.var_open.isChecked()

        self.running = True
        self._set_buttons_state("running")

        self.worker = CubeWorker(
            files, out, orbitals, iso, grid, style_name,
            resolution, shade_mode, auto_render, exe_paths, do_open)
        self.worker.log_signal.connect(self._append_log)
        self.worker.progress_signal.connect(self._set_progress)
        self.worker.finished_signal.connect(self._on_cubes_done)
        self.worker.start()

    def _on_cubes_done(self, auto_render, ok, total, cubes):
        self.running = False
        self._set_buttons_state("idle")

        if not auto_render and cubes:
            self._current_cubes = cubes
            self._append_log(self._tr("log_done_hint"))
            self.btn_preview.setEnabled(True)
            if _HAS_GL_VIEWER:
                getattr(self, "btn_gl_preview", None)  # OpenGL 按钮已移除

        # cube 生成完毕 —— 自动送进左侧画布渲染
        if cubes:
            self._push_cubes_to_canvas(cubes, auto_load=True)

        if auto_render:
            self._append_log(self._tr("log_all_done", ok=ok, total=total))
            self._set_progress(self._tr("progress_done", ok=ok, total=total))
            if self.var_open.isChecked() and ok > 0 and cubes:
                out = self._get_out_dir()
                os.startfile(out)

    def _preview_mol(self):
        """Write atoms to XYZ directly, then launch VMD molecule preview."""
        path = self.var_path.text().strip()
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        if ext not in (".log", ".out", ".xyz"):
            self._append_log("Only .log/.out/.xyz files supported for molecule preview")
            return

        exe_paths = self._get_paths()
        if not os.path.exists(exe_paths["vmd"]):
            QMessageBox.warning(self, self._tr("msg_title_error"),
                self._tr("msg_vmd_not_found", path=exe_paths['vmd']))
            return

        # 直接用画布里已解析的 atoms 写 XYZ（不走 Multiwfn）
        atoms = self.mol_canvas.atoms
        if not atoms:
            self._append_log("No atoms loaded — re-parse log...")
            try:
                atoms, _ = backend.parse_log(path)
            except Exception:
                self._append_log("Parse log failed")
                return
            if not atoms:
                self._append_log("No atoms found in log file")
                return

        out_dir = self._get_out_dir(path)
        stem = os.path.splitext(os.path.basename(path))[0]
        xyz_path = os.path.join(out_dir, f"{stem}.xyz")

        with open(xyz_path, "w", encoding="utf-8") as f:
            f.write(f"{len(atoms)}\n")
            f.write(f"Generated from {os.path.basename(path)}\n")
            for a in atoms:
                # atoms format: (center_num, symbol, atomic_num, (x, y, z))
                sym = a[1]
                x, y, z = a[3]
                f.write(f"{sym:>2s} {x:12.6f} {y:12.6f} {z:12.6f}\n")

        self._append_log(f"xyz written: {os.path.basename(xyz_path)} ({len(atoms)} atoms)")
        self._append_log(f"Launching VMD molecule preview...")

        style_name = self._get_style_name()
        try:
            port, render_dir, vmd_proc = backend.preview_mol(
                xyz_path, style_name=style_name,
                representation="CPK", cpk_scale="1.0",
                vmd_exe=exe_paths["vmd"])
            self.vmd_port = port
            self.vmd_render_dir = render_dir
            self._vmd_proc = vmd_proc
            # ── 同步 VMD 会话状态 ──
            self._vmd_session.port = port
            self._vmd_session.render_dir = render_dir
            self._vmd_session._current_style = style_name
            self._vmd_session._current_isovalue = 0.0
            self._vmd_session._multi_cubes = None
            self._vmd_session._mol_mode = True
            self._reset_orbital_state(xyz_path, 0.0)
            self._vmd_state["molid"] = 0
            self._vmd_orbital_labels = [os.path.basename(xyz_path)]
            self.iso_slider.setEnabled(False)
            self.iso_edit.setEnabled(False)
            self.opacity_slider.setEnabled(True)
            self.opacity_edit.setEnabled(True)
            self.btn_render.setEnabled(True)
            self.btn_dash_mode.setEnabled(True)
            self.btn_h_filter.setEnabled(True)
            self.btn_flip_phase.setEnabled(False)
            # Canvas → VMD dash sync
            self.mol_canvas.on_dash_added = self._vmd_draw_dash
            self.mol_canvas.on_dash_undone = self._vmd_undo_bond
            self.mol_canvas.on_dash_cleared = self._vmd_clear_bonds
            self._vmd_dash_pairs.clear()
            for a1, a2, _ in self.mol_canvas.custom_dash_lines:
                pair = (a1, a2)
                if pair not in self._vmd_dash_pairs:
                    self._vmd_dash_pairs.append(pair)
            if self._vmd_dash_pairs:
                self._send_vmd_cmd("")
                self._vmd_reapply_dashes()
            self.btn_flip_phase.setEnabled(False)
            self._append_log(f"VMD ready (port {port}) — molecule: {os.path.basename(xyz_path)}")
        except Exception as e:
            self._append_log(f"VMD launch failed: {e}")

    def _preview(self):
        path = self.var_path.text().strip()

        # .log/.out 文件：预览分子结构
        ext = os.path.splitext(path)[1].lower() if os.path.isfile(path) else ""
        if ext in (".log", ".out"):
            self._preview_mol()
            return

        out = self._get_out_dir(path)

        # 如果是直接载入的 .cub 文件，用已有的 cube 列表
        if ext in (".cub", ".cube") and self._current_cubes:
            all_cubes = list(self._current_cubes)
        else:
            all_cubes = sorted(glob.glob(os.path.join(out, "*.cub")))
        if not all_cubes:
            QMessageBox.warning(self, self._tr("msg_title_hint"),
                                self._tr("msg_no_cube"))
            return

        from PyQt5.QtWidgets import QListWidget

        if len(all_cubes) == 1:
            self._do_preview(all_cubes[0])
        else:
            dlg = QDialog(self)
            dlg.setWindowTitle(self._tr("dlg_select_orbitals"))
            dlg.resize(500, 420)
            dlg_layout = QVBoxLayout(dlg)

            dlg_layout.addWidget(QLabel(
                self._tr("dlg_select_orbitals_hint")))

            list_widget = QListWidget()
            list_widget.setSelectionMode(QListWidget.ExtendedSelection)
            for i, c in enumerate(all_cubes):
                list_widget.addItem(os.path.basename(c))
                list_widget.item(i).setSelected(True)
            dlg_layout.addWidget(list_widget)

            btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            btn_box.accepted.connect(dlg.accept)
            btn_box.rejected.connect(dlg.reject)
            dlg_layout.addWidget(btn_box)

            if dlg.exec_() != QDialog.Accepted:
                return

            selected = [all_cubes[i.row()] for i in list_widget.selectedIndexes()]
            if not selected:
                return

            if len(selected) == 1:
                self._do_preview(selected[0])
            else:
                cubes = [(c, self._extract_orbital_name(c)) for c in selected]
                self._do_preview_multi(cubes)

    def _do_preview(self, cube_path):
        self._close_persist_sock()
        self._vmd_orbital_labels = [os.path.basename(cube_path)]
        try:
            iso = float(self.iso_edit.text().strip())
        except ValueError:
            iso = 0.05

        style_name = self._get_style_name()
        _, _, _, _, _, shade_mode = self._get_params()
        exe_paths = self._get_paths()

        self.current_iso = iso
        self.current_opacity = None
        self._vmd_style_applied = style_name

        self._append_log(self._tr("log_start_preview").format(os.path.basename(cube_path)))
        self._append_log(self._tr("log_style_iso").format(style_name, iso))
        self._append_log(self._tr("log_adjust_view"))

        try:
            port, render_dir = backend.preview_cube(
                cube_path, isovalue=iso, style_name=style_name,
                vmd_exe=exe_paths["vmd"], shade_mode=shade_mode)
            if port:
                self.vmd_port = port
                self.vmd_render_dir = render_dir
                # ── 同步 VMD 会话状态 ──
                self._vmd_session.port = port
                self._vmd_session.render_dir = render_dir
                self._vmd_session._current_style = style_name
                self._vmd_session._current_isovalue = iso
                self.vmd_multi_cubes = None
                self._vmd_session._multi_cubes = None
                self._vmd_session._mol_mode = False
                self._reset_orbital_state(cube_path, iso)   # 统一管理状态
                self.btn_render.setEnabled(True)
                self.btn_dash_mode.setEnabled(True)
                self.btn_h_filter.setEnabled(True)
                # Canvas → VMD dash sync setup
                self.mol_canvas.on_dash_added = self._vmd_draw_dash
                self.mol_canvas.on_dash_undone = self._vmd_undo_bond
                self.mol_canvas.on_dash_cleared = self._vmd_clear_bonds
                self._vmd_dash_pairs.clear()
                for a1, a2, _ in self.mol_canvas.custom_dash_lines:
                    pair = (a1, a2)
                    if pair not in self._vmd_dash_pairs:
                        self._vmd_dash_pairs.append(pair)
                # Replay existing dashes on new VMD
                if self._vmd_dash_pairs:
                    self._send_vmd_cmd("")
                    self._vmd_reapply_dashes()
                self.iso_slider.setEnabled(True)
                self.iso_slider.blockSignals(True)
                self.iso_slider.setValue(int(iso * 1000))
                self.iso_slider.blockSignals(False)
                self.iso_edit.setEnabled(True)
                self.iso_edit.setText(f"{iso:.3f}")
                self.opacity_slider.setEnabled(True)
                self.opacity_edit.setEnabled(True)
                if self.current_opacity is None:
                    style = backend.STYLES.get(style_name, backend.STYLES["sob-art"])
                    self.current_opacity = style["surface_mat"][5]
                self.opacity_slider.blockSignals(True)
                self.opacity_slider.setValue(int(self.current_opacity * 100))
                self.opacity_slider.blockSignals(False)
                self.opacity_edit.setText(f"{self.current_opacity:.2f}")
                self.btn_flip_phase.setEnabled(True)
                self._append_log(self._tr("log_vmd_started", port=port))
            else:
                self._append_log(self._tr("log_vmd_failed"))
        except Exception as e:
            self._append_log(self._tr("log_vmd_error").format(e))

    # ══════════════════════════════════════════════════════════
    # 内嵌 OpenGL 画布（左侧面板）
    # ══════════════════════════════════════════════════════════
    def _on_canvas_status(self, msg):
        """画布状态回调 —— 只把有意义的信息写进日志。"""
        try:
            if msg and not str(msg).startswith("就绪"):
                self._append_log(f"[画布] {msg}")
        except Exception:
            pass

    def _canvas_ready(self):
        return getattr(self, "cub_canvas", None) is not None \
            and self.cub_canvas.is_available()

    def _canvas_grid(self):
        """返回画布网格精度档位；画布不可用（GL 失败/缺依赖）时回退 '2'。"""
        if self._canvas_ready():
            try:
                return self.cub_canvas.grid_quality()
            except Exception:
                pass
        return "2"

    def _canvas_iso(self):
        try:
            return float(self.iso_edit.text().strip())
        except (ValueError, AttributeError):
            return 0.05

    def _push_cubes_to_canvas(self, cubes, auto_load=True):
        """生成/载入 cube 后，把列表送进左侧画布并自动渲染第一个。"""
        if not self._canvas_ready() or not cubes:
            return
        paths = []
        for c in cubes:
            # _current_cubes 里可能是 (path, orbital) 元组
            p = c[0] if isinstance(c, (tuple, list)) and c else c
            if isinstance(p, str) and os.path.isfile(p):
                paths.append(p)
        if not paths:
            return
        try:
            self.cub_canvas.set_cube_list(paths, auto_load=False)
            if auto_load:
                iso = self._canvas_iso()
                self.cub_canvas.load_cube(
                    paths[0], iso=iso, style_name=self._get_style_name())
                # 登记 VMD 同步场景（画布当前显示的轨道）
                self.cub_canvas.glw.set_vmd_scene([
                    {"type": "orbital", "vol": p, "iso": iso} for p in paths
                ])
        except Exception as e:
            self._append_log(f"[画布] 加载失败: {e}")

    def _gl_preview(self):
        """在左侧内嵌画布中预览轨道；画布不可用时回退到独立 OpenGL 窗口。"""
        # 优先使用左侧内嵌画布
        if self._canvas_ready():
            path0 = self.var_path.text().strip()
            out0 = self._get_out_dir(path0)
            ext0 = os.path.splitext(path0)[1].lower() if os.path.isfile(path0) else ""
            if ext0 in (".cub", ".cube") and self._current_cubes:
                cubes = list(self._current_cubes)
            else:
                cubes = sorted(glob.glob(os.path.join(out0, "*.cub")))
            if not cubes:
                QMessageBox.warning(self, self._tr("msg_title_hint"),
                                    self._tr("msg_no_cube"))
                return
            self._push_cubes_to_canvas(cubes, auto_load=True)
            return

        if not _HAS_GL_VIEWER:
            QMessageBox.warning(self, self._tr("msg_title_hint"),
                                self._tr("msg_need_pyopengl"))
            return

        path = self.var_path.text().strip()
        out = self._get_out_dir(path)
        ext = os.path.splitext(path)[1].lower() if os.path.isfile(path) else ""

        # 获取 cube 文件
        if ext in (".cub", ".cube") and self._current_cubes:
            all_cubes = list(self._current_cubes)
        else:
            all_cubes = sorted(glob.glob(os.path.join(out, "*.cub")))

        if not all_cubes:
            QMessageBox.warning(self, self._tr("msg_title_hint"),
                                self._tr("msg_no_cube"))
            return

        # 取第一个 cube
        cube_path = all_cubes[0]
        if len(all_cubes) > 1:
            # 如果有多个，用对话框选择
            from PyQt5.QtWidgets import QListWidget
            dlg = QDialog(self)
            dlg.setWindowTitle(self._tr("dlg_select_orb_gl"))
            dlg.resize(500, 400)
            dlg_layout = QVBoxLayout(dlg)
            dlg_layout.addWidget(QLabel(self._tr("lbl_select_orb_gl")))
            list_widget = QListWidget()
            for i, c in enumerate(all_cubes):
                list_widget.addItem(os.path.basename(c))
                list_widget.item(i).setSelected(i == 0)
            dlg_layout.addWidget(list_widget)
            btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            btn_box.accepted.connect(dlg.accept)
            btn_box.rejected.connect(dlg.reject)
            dlg_layout.addWidget(btn_box)
            if dlg.exec_() != QDialog.Accepted:
                return
            selected = [all_cubes[i.row()] for i in list_widget.selectedIndexes()]
            if not selected:
                return
            cube_path = selected[0]

        try:
            iso = float(self.iso_edit.text().strip())
        except ValueError:
            iso = 0.05

        style_name = self._get_style_name()

        # 创建或复用 OpenGL 窗口
        if not hasattr(self, '_gl_viewer') or self._gl_viewer is None:
            self._gl_viewer = OrbitalGLViewer(self)
            self._gl_viewer.setAttribute(Qt.WA_DeleteOnClose, True)
            self._gl_viewer.destroyed.connect(lambda: setattr(self, '_gl_viewer', None))

        self._gl_viewer.load_cube_file(cube_path, iso, style_name)
        self._gl_viewer.show()
        self._gl_viewer.raise_()
        self._gl_viewer.activateWindow()

        self._append_log(f"OpenGL 预览: {os.path.basename(cube_path)} | 风格: {style_name}")

    def _do_preview_multi(self, cubes):
        self._close_persist_sock()
        orbitals = [orb for _, orb in cubes]
        self._vmd_orbital_labels = orbitals
        try:
            iso = float(self.iso_edit.text().strip())
        except ValueError:
            iso = 0.05

        style_name = self._get_style_name()
        _, _, _, _, _, shade_mode = self._get_params()
        exe_paths = self._get_paths()

        h_str = self.var_h_indices.text().strip()
        if h_str:
            try:
                keep_h_indices = [int(x.strip()) for x in h_str.split(",") if x.strip()]
            except ValueError:
                keep_h_indices = []
        else:
            keep_h_indices = None

        self.current_iso = iso
        self.current_opacity = None
        self._vmd_style_applied = style_name

        orb_names = ", ".join([orb for _, orb in cubes])
        self._append_log(self._tr("log_start_preview_multi").format(orb_names))
        self._append_log(self._tr("log_style_iso").format(style_name, iso))
        self._append_log(self._tr("log_adjust_view"))

        try:
            port, render_dir, copied_cubes = backend.preview_multi_cubes(
                cubes, iso, style_name=style_name,
                vmd_exe=exe_paths["vmd"], shade_mode=shade_mode,
                keep_h_indices=keep_h_indices)
            if port:
                self.vmd_port = port
                self.vmd_render_dir = render_dir
                # ── 同步 VMD 会话状态 ──
                self._vmd_session.port = port
                self._vmd_session.render_dir = render_dir
                self._vmd_session._current_style = style_name
                self._vmd_session._current_isovalue = iso
                self._vmd_session._multi_cubes = copied_cubes
                self._vmd_session._mol_mode = False
                self.vmd_multi_cubes = copied_cubes
                self.vmd_cube_path = None
                self.btn_render.setEnabled(True)
                self.btn_dash_mode.setEnabled(True)
                self.btn_h_filter.setEnabled(True)
                # Canvas → VMD dash sync setup
                self.mol_canvas.on_dash_added = self._vmd_draw_dash
                self.mol_canvas.on_dash_undone = self._vmd_undo_bond
                self.mol_canvas.on_dash_cleared = self._vmd_clear_bonds
                self._vmd_dash_pairs.clear()
                for a1, a2, _ in self.mol_canvas.custom_dash_lines:
                    pair = (a1, a2)
                    if pair not in self._vmd_dash_pairs:
                        self._vmd_dash_pairs.append(pair)
                if self._vmd_dash_pairs:
                    self._send_vmd_cmd("")
                    self._vmd_reapply_dashes()
                self.iso_slider.setEnabled(True)
                self.iso_slider.blockSignals(True)
                self.iso_slider.setValue(int(iso * 1000))
                self.iso_slider.blockSignals(False)
                self.iso_edit.blockSignals(True)
                self.iso_edit.setText(f"{iso:.3f}")
                self.iso_edit.blockSignals(False)
                self.iso_edit.setEnabled(True)
                self.opacity_slider.setEnabled(True)
                self.opacity_edit.setEnabled(True)
                if self.current_opacity is None:
                    style = backend.STYLES.get(style_name, backend.STYLES["sob-art"])
                    self.current_opacity = style["surface_mat"][5]
                self.opacity_slider.blockSignals(True)
                self.opacity_slider.setValue(int(self.current_opacity * 100))
                self.opacity_slider.blockSignals(False)
                self.opacity_edit.setText(f"{self.current_opacity:.2f}")
                self.btn_flip_phase.setEnabled(True)
                self._append_log(self._tr("log_vmd_started", port=port))
            else:
                self._append_log(self._tr("log_vmd_failed"))
        except Exception as e:
            self._append_log(self._tr("log_vmd_error").format(e))

    def _render_view(self):
        """VMD 控制台『渲染出图』：后台 Tachyon 渲染当前 VMD 视角为 PNG。

        注意：PyQt5 中未捕获的 Qt 槽异常会直接 fail-fast 终止整个程序（闪退），
        因此本方法整体 try/except，任何错误都写入运行日志并恢复按钮。
        """
        try:
            if not self.vmd_port or not self.vmd_render_dir:
                QMessageBox.warning(self, self._tr("msg_title_hint"),
                                    self._tr("msg_preview_first"))
                return

            # ETS-NOCV 等面板自带文件选择器，主输入行可能为空：
            # os.makedirs("") 会抛 FileNotFoundError → 槽异常 → 闪退，
            # 故空目录回退到 VMD 渲染目录（已由 build_scene_tcl 创建）。
            out = self._get_out_dir()
            if not out:
                out = self.vmd_render_dir
            if out:
                try:
                    os.makedirs(out, exist_ok=True)
                except OSError:
                    out = self.vmd_render_dir
                    os.makedirs(out, exist_ok=True)

            _, _, _, style_name, resolution, shade_mode = self._get_params()
            exe_paths = self._get_paths()

            output_png = None
            if self.vmd_cube_path:
                cube_stem = os.path.splitext(os.path.basename(self.vmd_cube_path))[0]
                fchk_name = cube_stem.rsplit("_MO", 1)[0]
                orbital = self._get_orbitals()
                orbital_str = ",".join(orbital) if orbital else "unknown"
                output_png = os.path.join(out, f"{fchk_name}_MO{orbital_str}.png") if out else None
            elif self.vmd_multi_cubes and self.vmd_multi_cubes[0][0]:
                cube_stem = os.path.splitext(os.path.basename(self.vmd_multi_cubes[0][0]))[0]
                fchk_name = cube_stem.rsplit("_MO", 1)[0]
                orbitals = self._get_orbitals()
                orbital_suffix = "_".join(orbitals) if orbitals else "multi"
                output_png = os.path.join(out, f"{fchk_name}_MO{orbital_suffix}.png") if out else None
            elif getattr(self, "etsnocv_panel", None) is not None:
                # ETS-NOCV：没有 vmd_cube_path，用面板当前 NOCV cube 命名
                #（存到 cube 所在目录，即工作目录）
                cub = getattr(self.etsnocv_panel, "_current_cube", None)
                if cub and os.path.isfile(cub):
                    stem = os.path.splitext(os.path.basename(cub))[0]
                    d = os.path.dirname(cub)
                    if d and os.path.isdir(d):
                        output_png = os.path.join(d, f"{stem}.png")

            trans_mode = {0: "raster3d", 1: "vmd", 2: "orig"}.get(
                self.var_trans_raster.currentIndex(), None)
            try:
                threads = int(self.var_threads.text().strip())
            except (ValueError, AttributeError):
                threads = 8

            self.btn_render.setEnabled(False)
            self.render_worker = RenderWorker(
                self.vmd_port, self.vmd_render_dir, output_png,
                exe_paths["tachyon"], resolution, style_name,
                shade_mode, trans_mode, threads)
            self.render_worker.log_signal.connect(self._append_log)
            self.render_worker.finished_signal.connect(self._on_render_done)
            self.render_worker.start()
        except Exception as e:
            self.btn_render.setEnabled(True)
            try:
                self._append_log(f"渲染出图失败: {e}")
            except Exception:
                pass

    def _on_render_done(self, png_path):
        self.btn_render.setEnabled(True)
        if png_path and os.path.exists(png_path):
            try:
                os.startfile(png_path)
            except OSError as e:
                try:
                    self._append_log(f"无法打开渲染结果: {e}")
                except Exception:
                    pass

    def _stop(self):
        self.running = False
        if hasattr(self, 'worker') and self.worker.isRunning():
            self.worker.stop()

    def closeEvent(self, event):
        """主窗口退出前关闭无 parent 的 VMD 控制台窗口，避免孤儿窗口。"""
        try:
            self._close_vmd_console()
        except Exception:
            pass
        super().closeEvent(event)

    # ── Hydrogen Filter ──

    def _toggle_h_filter(self):
        if not self.vmd_port:
            self._append_log(self._tr("log_preview_first_hint"))
            return

        if not self._h_hidden:
            self._h_hidden = True
            self.btn_h_filter.setText(self._tr("btn_show_h"))
            h_str = self.var_h_indices.text().strip()
            if h_str:
                try:
                    keep_indices = [int(x.strip()) for x in h_str.split(",") if x.strip()]
                    # VMD index 是 0-based，画布编号是 1-based，需要减1
                    vmd_indices = [str(i - 1) for i in keep_indices]
                    idx_str = " ".join(vmd_indices)
                    # pqr 分子 element 属性为空，氢判断用 (element H or name H) 兜底
                    sel_str = ("not (element H or name H) or "
                               f"((element H or name H) and index {idx_str})")
                except ValueError:
                    sel_str = "not (element H or name H)"
            else:
                sel_str = "not (element H or name H)"
            # 注意：VMD socket 服务器用 gets 逐行读命令，多行 Tcl 会只执行
            # 第一行（报 missing close brace）。必须拼成单行（分号分隔）。
            inner = 'mol modselect $r $mid "' + sel_str + '"'
            cmd = ('foreach mid [molinfo list] {set nr [molinfo $mid get numreps]; '
                   'for {set r 0} {$r < $nr} {incr r} {' + inner + '}}')
            self._send_vmd_cmd(cmd)
            self._append_log(self._tr("log_hide_h_done"))
        else:
            self._h_hidden = False
            self.btn_h_filter.setText(self._tr("btn_hide_h"))
            cmd = (
                'foreach mid [molinfo list] {set nr [molinfo $mid get numreps]; '
                'for {set r 0} {$r < $nr} {incr r} {mol modselect $r $mid all}}'
            )
            self._send_vmd_cmd(cmd)
            self._append_log(self._tr("log_show_h_done"))

    # ── Draw Bond Methods (移植自 MolViewer) ──

    # ── Draw Bond Methods (Python 实现，graphics top delete all 安全) ──

    def _vmd_delete_all_user_gfx(self):
        """删除全部用户图形（graphics top delete all 不影响等值面）。"""
        self._send_vmd_cmd("graphics top delete all")

    def _vmd_draw_one(self, a1, a2, log=True):
        """向 VMD 发送虚线命令，全部 6 种风格均为虚线分段。"""
        if not self.vmd_port:
            return False
        atoms = self.mol_canvas.atoms
        a1_idx = int(a1) - 1
        a2_idx = int(a2) - 1
        if a1_idx >= len(atoms) or a2_idx >= len(atoms):
            return False
        pos1 = atoms[a1_idx][3]
        pos2 = atoms[a2_idx][3]
        x1, y1, z1 = pos1
        x2, y2, z2 = pos2

        # 读取虚线参数（直接从控件读取，确保实时更新）
        if self._dash_dialog:
            gap = self._dash_dialog.bond_nbars_slider.value() / 100.0
            radius = self._dash_dialog.bond_radius_slider.value() / 100.0
            mat = self._bond_mat_map.get(self._dash_dialog.var_bond_mat.currentText(), "Opaque")
            h_type = self._resolve_bond_tcl_key(self._dash_dialog.var_bond_type.currentText(), is_color=False)
        else:
            dp = self._dash_params
            gap = dp.get('gap', 0.2)
            radius = dp.get('radius', 0.06)
            mat = self._bond_mat_map.get(dp.get('mat', 'Opaque'), 'Opaque')
            h_type = dp.get('type', 'dots')
        color_hex = self._get_bond_color_hex()
        vmd_color = self._hex_to_vmd_color(color_hex)
        h_resol = 6

        dx, dy, dz = x2 - x1, y2 - y1, z2 - z1
        length = (dx*dx + dy*dy + dz*dz) ** 0.5
        if length < 0.001:
            return False

        n_bars = max(1, int(length / gap))
        ratio = 0.7

        self._send_vmd_cmd(f"graphics top color {vmd_color}; graphics top material {mat}")

        if h_type == "dots":
            for i in range(n_bars):
                t = (i + 0.5) / n_bars
                cx, cy, cz = x1+dx*t, y1+dy*t, z1+dz*t
                self._send_vmd_cmd(f"graphics top sphere {{{cx} {cy} {cz}}} radius {radius} resolution 12")

        elif h_type == "pymol":
            seg_len = length / n_bars
            piece_len = seg_len * ratio
            for i in range(n_bars):
                t0 = i * seg_len / length
                t1 = t0 + piece_len / length
                self._send_vmd_cmd(
                    f"graphics top cylinder {{{x1+dx*t0} {y1+dy*t0} {z1+dz*t0}}} {{{x1+dx*t1} {y1+dy*t1} {z1+dz*t1}}} radius {radius} resolution {h_resol}")

        elif h_type == "cylinder":
            seg_len = length / n_bars
            piece_len = seg_len * ratio
            for i in range(n_bars):
                t0 = i * seg_len / length
                t1 = t0 + piece_len / length
                self._send_vmd_cmd(
                    f"graphics top cylinder {{{x1+dx*t0} {y1+dy*t0} {z1+dz*t0}}} {{{x1+dx*t1} {y1+dy*t1} {z1+dz*t1}}} radius {radius} resolution {h_resol}")

        elif h_type == "sphere":
            for i in range(n_bars):
                t = (i + 0.5) / n_bars
                cx, cy, cz = x1+dx*t, y1+dy*t, z1+dz*t
                self._send_vmd_cmd(f"graphics top sphere {{{cx} {cy} {cz}}} radius {radius} resolution 12")

        elif h_type == "cone":
            seg_len = length / n_bars
            piece_len = seg_len * ratio
            for i in range(n_bars):
                t0 = i * seg_len / length
                t1 = t0 + piece_len / length
                self._send_vmd_cmd(
                    f"graphics top cone {{{x1+dx*t0} {y1+dy*t0} {z1+dz*t0}}} {{{x1+dx*t1} {y1+dy*t1} {z1+dz*t1}}} radius {radius} resolution {h_resol}")

        elif h_type == "line":
            seg_len = length / n_bars
            piece_len = seg_len * ratio
            for i in range(n_bars):
                t0 = i * seg_len / length
                t1 = t0 + piece_len / length
                self._send_vmd_cmd(
                    f"graphics top line {{{x1+dx*t0} {y1+dy*t0} {z1+dz*t0}}} {{{x1+dx*t1} {y1+dy*t1} {z1+dz*t1}}}")

        if log:
            self._append_log(self._tr("log_draw_bond_ok", a1=a1, a2=a2,
                                       color=color_hex, btype=h_type, mat=mat))
        return True

    def _hex_to_vmd_color(self, hex_str):
        """将 #rrggbb 转为最接近的 VMD 内建颜色名。"""
        if not hex_str.startswith('#'):
            return hex_str
        r = int(hex_str[1:3], 16) / 255.0
        g = int(hex_str[3:5], 16) / 255.0
        b = int(hex_str[5:7], 16) / 255.0
        named = [
            (0.00, 0.00, 0.00, "black"), (1.00, 1.00, 1.00, "white"),
            (1.00, 0.00, 0.00, "red"), (0.00, 1.00, 0.00, "green"),
            (0.00, 0.00, 1.00, "blue"), (1.00, 1.00, 0.00, "yellow"),
            (0.00, 1.00, 1.00, "cyan"), (1.00, 0.00, 1.00, "magenta"),
            (0.50, 0.50, 0.50, "gray"), (0.75, 0.75, 0.75, "silver"),
            (1.00, 0.50, 0.00, "orange"), (0.50, 0.00, 0.50, "purple"),
            (0.00, 0.50, 0.00, "green2"), (0.50, 0.50, 0.00, "yellow2"),
            (0.00, 0.00, 0.50, "blue2"), (0.50, 0.00, 0.00, "red2"),
            (0.65, 0.16, 0.16, "brickred"),
        ]
        best, best_d = "black", 999.0
        for nr, ng, nb, name in named:
            d = (r - nr) ** 2 + (g - ng) ** 2 + (b - nb) ** 2
            if d < best_d:
                best, best_d = name, d
        return best

    def _vmd_reapply_dashes(self):
        """用当前样式重绘全部虚线（graphics top delete all 安全，不动等值面）。"""
        if not self._vmd_dash_pairs:
            return
        self._send_vmd_cmd("graphics top delete all")
        for a1, a2 in self._vmd_dash_pairs:
            self._vmd_draw_one(a1, a2, log=False)

    def _vmd_draw_dash(self, a1, a2):
        """画布虚线同步回调：在 VMD 中画虚线并记录。"""
        if not self.vmd_port:
            return
        if self._vmd_draw_one(a1, a2):
            pair = (int(a1), int(a2))
            if pair not in self._vmd_dash_pairs:
                self._vmd_dash_pairs.append(pair)
            self._update_dash_status()

    def _vmd_undo_bond(self):
        """VMD 撤销最后一根虚线（删掉全部再重绘剩余）。"""
        if self._vmd_dash_pairs:
            self._vmd_dash_pairs.pop()
        self._send_vmd_cmd("graphics top delete all")
        for a1, a2 in self._vmd_dash_pairs:
            self._vmd_draw_one(a1, a2, log=False)
        self._append_log(self._tr("log_undo_bond"))

    def _vmd_clear_bonds(self):
        """清空 VMD 虚线（只清 graphics，不动等值面）。"""
        self._send_vmd_cmd("graphics top delete all")
        self._vmd_dash_pairs.clear()
        self._append_log(self._tr("log_clear_bond"))

    def _undo_bond(self):
        # Remove from canvas
        if hasattr(self, 'mol_canvas'):
            self.mol_canvas.undo_last_dash_line()
        # VMD: 用 draw_bond_redraw + 重绘（不删等值面）
        self._send_vmd_cmd("draw_bond_redraw")
        if self._vmd_dash_pairs:
            self._vmd_dash_pairs.pop()
            for a1, a2 in self._vmd_dash_pairs:
                self._vmd_draw_one(a1, a2, log=False)
        self._append_log(self._tr("log_undo_bond"))

    def _clear_bond(self):
        # Clear canvas
        if hasattr(self, 'mol_canvas'):
            self.mol_canvas.clear_dash_lines()
        # VMD: 用 draw_bond_redraw 清空（不删等值面）
        self._send_vmd_cmd("draw_bond_redraw")
        self._vmd_dash_pairs.clear()
        self._append_log(self._tr("log_clear_bond"))

    def _on_style_changed(self, _text=None):
        """VMD预览已启动时，切换样式立即刷新VMD（委托给库会话）。"""
        self._custom_pos_rgb = None  # 切换风格时重置自定义颜色
        self._custom_neg_rgb = None
        self._update_color_buttons()
        if not self.vmd_port:
            return
        style_name = self._get_style_name()
        if not style_name or style_name == self._vmd_style_applied:
            return
        _, _, _, _, _, shade_mode = self._get_params()
        ok = self._vmd_session.set_style(style_name, shade_mode=shade_mode)
        if ok:
            self._vmd_style_applied = style_name
            self._append_log(self._tr("log_style_live_updated").format(style_name))

    def _update_color_buttons(self):
        """更新颜色按钮的背景色，优先用自定义颜色，否则用风格默认。"""
        style_name = self._get_style_name()
        style = backend.STYLES.get(style_name, None)
        if style is None:
            return
        pc = style["pos_color"]
        nc = style["neg_color"]
        pos_rgb = self._custom_pos_rgb if self._custom_pos_rgb else \
                  self._resolve_color_rgb(pc)
        neg_rgb = self._custom_neg_rgb if self._custom_neg_rgb else \
                  self._resolve_color_rgb(nc)
        self.btn_pos_color.setStyleSheet(
            f"background:rgb({pos_rgb[0]},{pos_rgb[1]},{pos_rgb[2]}); "
            "border:2px solid #999; border-radius:14px;")
        self.btn_neg_color.setStyleSheet(
            f"background:rgb({neg_rgb[0]},{neg_rgb[1]},{neg_rgb[2]}); "
            "border:2px solid #999; border-radius:14px;")
        # 自定义时加粗边框提示
        if self._custom_pos_rgb:
            self.btn_pos_color.setStyleSheet(
                f"background:rgb({pos_rgb[0]},{pos_rgb[1]},{pos_rgb[2]}); "
                "border:3px solid #FFD700; border-radius:14px;")
        if self._custom_neg_rgb:
            self.btn_neg_color.setStyleSheet(
                f"background:rgb({neg_rgb[0]},{neg_rgb[1]},{neg_rgb[2]}); "
                "border:3px solid #FFD700; border-radius:14px;")

    def _resolve_color_rgb(self, color_def):
        """把样式的颜色定义 [ColorID, R,G,B 或 None] 转为 (R*255, G*255, B*255) 0-255 整数。"""
        import math
        if len(color_def) == 4 and color_def[1] is not None:
            r = int(round(color_def[1] * 255))
            g = int(round(color_def[2] * 255))
            b = int(round(color_def[3] * 255))
            return (r, g, b)
        cid = color_def[0]
        # VMD ColorID → 默认 RGB (VMD 1.9.3 color scale)
        VMD_COLORS = {
            0: (0, 0, 255), 1: (255, 0, 0), 2: (128, 128, 128), 3: (255, 165, 0),
            4: (255, 255, 0), 5: (0, 255, 0), 6: (0, 255, 255), 7: (255, 0, 255),
            8: (128, 0, 128), 9: (0, 128, 128), 10: (128, 128, 0), 11: (0, 128, 0),
            12: (0, 128, 0), 13: (0, 128, 0), 14: (0, 128, 0), 15: (0, 128, 0),
            16: (0, 128, 0), 17: (0, 0, 255), 18: (255, 255, 255), 19: (255, 0, 255),
            20: (0, 255, 255), 21: (255, 255, 0), 22: (0, 0, 255),
            23: (255, 0, 0), 24: (0, 255, 0), 25: (0, 255, 255),
            26: (255, 0, 255), 27: (255, 255, 0), 28: (255, 165, 0),
            29: (255, 192, 203), 30: (255, 105, 180), 31: (0, 255, 0),
            32: (0, 0, 255), 33: (255, 255, 0),
        }
        return VMD_COLORS.get(cid, (128, 128, 128))

    def _pick_phase_color(self, lobe):
        """弹出颜色对话框选择自定义相位颜色。"""
        from PyQt5.QtWidgets import QColorDialog
        from PyQt5.QtGui import QColor
        current = self._custom_pos_rgb if lobe == "pos" else self._custom_neg_rgb
        if current is None:
            style = backend.STYLES.get(self._get_style_name(), None)
            if style:
                cd = style["pos_color"] if lobe == "pos" else style["neg_color"]
                current = self._resolve_color_rgb(cd)
            else:
                current = (0, 128, 0) if lobe == "pos" else (0, 0, 255)
        init = QColor(current[0], current[1], current[2])
        title_key = "pick_color_title" if lobe == "pos" else "pick_color_title_neg"
        color = QColorDialog.getColor(init, self, self._tr(title_key))
        if not color.isValid():
            return
        rgb = (color.red(), color.green(), color.blue())
        if lobe == "pos":
            self._custom_pos_rgb = rgb
        else:
            self._custom_neg_rgb = rgb
        self._update_color_buttons()
        self._apply_custom_colors_to_vmd()

    def _reset_phase_color(self, lobe):
        """右键重置单个相位颜色为风格默认。"""
        if lobe == "pos":
            self._custom_pos_rgb = None
        else:
            self._custom_neg_rgb = None
        self._update_color_buttons()
        self._apply_custom_colors_to_vmd()

    def _apply_custom_colors_to_vmd(self):
        """将自定义颜色写入 VMD（委托给库会话）。"""
        if not self.vmd_port:
            return
        pos_rgb = self._custom_pos_rgb
        neg_rgb = self._custom_neg_rgb
        self._vmd_session.set_phase_colors(pos_rgb=pos_rgb, neg_rgb=neg_rgb)
        if pos_rgb is None and neg_rgb is None:
            self._append_log(self._tr("log_color_reset"))
        else:
            self._append_log(self._tr("log_color_custom").format(
                pos=pos_rgb, neg=neg_rgb))

    # ── Socket Communication (delegated to VMD session) ──

    def _send_vmd_cmd(self, cmd):
        """向 VMD 发送 TCL 命令（委托给 orbital_viewer_lib 会话）。"""
        return self._vmd_session.send_cmd(cmd)

    def _close_persist_sock(self):
        """关闭持久 socket 连接。"""
        self._vmd_session._close_socket()
        # 兼容旧代码
        sock = getattr(self, '_vmd_persist_sock', None)
        if sock:
            try:
                sock.close()
            except Exception:
                pass
            self._vmd_persist_sock = None

    # ── Keyboard Shortcuts ──

    def _key_iso_up(self):
        self.current_iso = round(min(self.current_iso + self.iso_step, 0.5), 4)
        self._apply_iso_change()

    def _key_iso_down(self):
        self.current_iso = round(max(self.current_iso - self.iso_step, 0.005), 4)
        self._apply_iso_change()

    def _key_opacity_up(self):
        if self.current_opacity is None:
            style = backend.STYLES.get(self._get_style_name(), backend.STYLES["sob-art"])
            self.current_opacity = style["surface_mat"][5]
        self.current_opacity = round(min(self.current_opacity + self.opacity_step, 1.0), 2)
        self._apply_opacity_change()

    def _key_opacity_down(self):
        if self.current_opacity is None:
            style = backend.STYLES.get(self._get_style_name(), backend.STYLES["sob-art"])
            self.current_opacity = style["surface_mat"][5]
        self.current_opacity = round(max(self.current_opacity - self.opacity_step, 0.05), 2)
        self._apply_opacity_change()

    # ── Slider Handlers ──

    def _on_iso_slider_changed(self, val):
        if not self.vmd_port:
            return
        iso = val / 1000.0
        self.current_iso = iso
        self.iso_edit.blockSignals(True)
        self.iso_edit.setText(f"{iso:.3f}")
        self.iso_edit.blockSignals(False)
        self._vmd_session.set_isovalue(iso)

    def _on_opacity_slider_changed(self, val):
        if not self.vmd_port:
            return
        op = val / 100.0
        self.current_opacity = op
        self.opacity_edit.blockSignals(True)
        self.opacity_edit.setText(f"{op:.2f}")
        self.opacity_edit.blockSignals(False)
        self._vmd_session.set_opacity(op)

    def _on_iso_edit_finished(self):
        """从输入框精确设置等值面"""
        if not self.vmd_port:
            return
        try:
            iso = float(self.iso_edit.text())
        except ValueError:
            return
        iso = max(0.005, min(iso, 0.500))
        self.current_iso = iso
        self._apply_iso_change()

    def _on_opacity_edit_finished(self):
        """从输入框精确设置透明度"""
        if not self.vmd_port:
            return
        try:
            op = float(self.opacity_edit.text())
        except ValueError:
            return
        op = round(max(0.05, min(op, 1.00)), 2)
        self.current_opacity = op
        self._apply_opacity_change()

    # ── Canvas Dash Mode ──

    def _update_dash_status(self):
        """更新画布虚线模式状态（日志输出）。"""
        n = len(self.mol_canvas.custom_dash_lines)
        if self.mol_canvas._dash_bond_atom1 is not None:
            self._append_log(f"{self._tr('dash_selected')} {self.mol_canvas._dash_bond_atom1}，{self._tr('dash_select_other')}（{n} {self._tr('dash_lines')}）")
        elif n:
            self._append_log(f"{n} {self._tr('dash_status_lines')}，{self._tr('dash_click_two')}")

    def _bond_display_label(self, tcl_key, is_color=False):
        """根据当前语言返回显示标签。"""
        idx = 1 if self._lang == "en" else 2
        items = self._bond_color_items if is_color else self._bond_type_items
        for it in items:
            if it[0] == tcl_key:
                return it[idx]
        return tcl_key

    def _populate_bond_combos(self):
        """根据当前语言重建颜色和类型下拉框。"""
        if not self._dash_dialog:
            return
        idx = 1 if self._lang == "en" else 2
        dlg = self._dash_dialog

        # 虚线颜色
        cur_color = dlg.var_dash_color.currentText()
        dlg.var_dash_color.blockSignals(True)
        dlg.var_dash_color.clear()
        new_idx = 0
        for i, it in enumerate(self._bond_color_items):
            dlg.var_dash_color.addItem(it[idx])
            if it[0] == self._resolve_bond_tcl_key(cur_color, is_color=True):
                new_idx = i
        dlg.var_dash_color.setCurrentIndex(new_idx)
        dlg.var_dash_color.blockSignals(False)

        # 虚线类型
        cur_type = dlg.var_bond_type.currentText()
        dlg.var_bond_type.blockSignals(True)
        dlg.var_bond_type.clear()
        new_idx = 0
        for i, it in enumerate(self._bond_type_items):
            dlg.var_bond_type.addItem(it[idx])
            if it[0] == self._resolve_bond_tcl_key(cur_type, is_color=False):
                new_idx = i
        dlg.var_bond_type.setCurrentIndex(new_idx)
        dlg.var_bond_type.blockSignals(False)

    def _resolve_bond_tcl_key(self, label, is_color=False):
        """根据显示标签（中/英）反查 tcl_key。"""
        items = self._bond_color_items if is_color else self._bond_type_items
        for it in items:
            if label in (it[1], it[2]):
                return it[0]
        return "black" if is_color else "dots"

    def _get_bond_color_hex(self):
        """获取当前选择的虚线颜色 hex。"""
        if self._dash_dialog:
            label = self._dash_dialog.var_dash_color.currentText()
            for it in self._bond_color_items:
                if label in (it[1], it[2]):
                    return it[3]
        return self._dash_params.get('color_hex', '#000000')

    def _on_dash_color_changed(self):
        """下拉选择虚线颜色 → 同步画布 + VMD。"""
        if not hasattr(self, 'mol_canvas') or not self.vmd_port:
            return
        hex_str = self._get_bond_color_hex()
        self.mol_canvas.dash_color_hex = hex_str
        self._dash_params['color_hex'] = hex_str
        self.mol_canvas.update()
        self._vmd_reapply_dashes()

    def _sync_dash_to_canvas(self):
        """将虚线面板的参数同步到画布。"""
        if not self._dash_dialog or not hasattr(self._dash_dialog, 'bond_nbars_slider'):
            return
        gap = self._dash_dialog.bond_nbars_slider.value() / 100.0
        self.mol_canvas.dash_dot_count = max(2, int(3.0 / gap))
        self.mol_canvas.dash_dot_radius = max(1, self._dash_dialog.bond_radius_slider.value())
        self.mol_canvas.repaint()

    def _on_nbars_slider(self, val):
        gap = val / 100.0
        self._dash_params['gap'] = gap
        if self._dash_dialog:
            self._dash_dialog.bond_nbars_edit.blockSignals(True)
            self._dash_dialog.bond_nbars_edit.setText(f"{gap:.2f}")
            self._dash_dialog.bond_nbars_edit.blockSignals(False)
        self._vmd_reapply_dashes()
        self._sync_dash_to_canvas()

    def _on_nbars_edit(self):
        if not self._dash_dialog:
            return
        try:
            gap = float(self._dash_dialog.bond_nbars_edit.text())
            gap = max(0.05, min(1.00, gap))
        except ValueError:
            return
        val = int(round(gap * 100))
        self._dash_dialog.bond_nbars_slider.blockSignals(True)
        self._dash_dialog.bond_nbars_slider.setValue(val)
        self._dash_dialog.bond_nbars_slider.blockSignals(False)
        self._dash_dialog.bond_nbars_edit.setText(f"{val/100.0:.2f}")
        self._vmd_reapply_dashes()
        self._sync_dash_to_canvas()

    def _on_bond_radius_slider(self, val):
        r = val / 100.0
        self._dash_params['radius'] = r
        if self._dash_dialog:
            self._dash_dialog.bond_radius_edit.blockSignals(True)
            self._dash_dialog.bond_radius_edit.setText(f"{r:.2f}")
            self._dash_dialog.bond_radius_edit.blockSignals(False)
        self._vmd_reapply_dashes()
        self._sync_dash_to_canvas()

    def _on_bond_radius_edit(self):
        if not self._dash_dialog:
            return
        try:
            r = float(self._dash_dialog.bond_radius_edit.text())
            r = max(0.01, min(0.50, r))
        except ValueError:
            return
        val = int(round(r * 100))
        self._dash_dialog.bond_radius_slider.blockSignals(True)
        self._dash_dialog.bond_radius_slider.setValue(val)
        self._dash_dialog.bond_radius_slider.blockSignals(False)
        self._dash_dialog.bond_radius_edit.setText(f"{val/100.0:.2f}")
        self._vmd_reapply_dashes()
        self._sync_dash_to_canvas()

    def _on_flip_phase(self):
        """翻转等值面相位：单轨道直接翻；多轨道（如 NBO 叠加）弹出选择——
        翻转所选轨道 / 翻转全部（per-orbital 独立追踪相位状态）。"""
        if not self.vmd_port or self.current_iso is None:
            self._append_log("翻转相位失败 (VMD 未连接或无当前 isovalue)")
            return
        labels = list(getattr(self, "_vmd_orbital_labels", []) or [])
        if len(labels) <= 1:
            # 单轨道：直接翻转
            self._flip_orbital(0, labels[0] if labels else "轨道")
            return
        # 多轨道：弹出选择（轨道列表 + 翻转全部）
        items = labels + [self._tr("flip_all")]
        item, ok = QInputDialog.getItem(
            self, self._tr("btn_flip_phase"), self._tr("flip_choose"),
            items, 0, False)
        if not ok:
            return
        if item == self._tr("flip_all"):
            for i, lab in enumerate(labels):
                self._flip_orbital(i, lab, log=False)
            self._append_log(self._tr("log_flip_all", n=len(labels)))
        else:
            try:
                i = labels.index(item)
            except ValueError:
                return
            self._flip_orbital(i, item)

    def _flip_orbital(self, i, label, log=True):
        """翻转第 i 个轨道（volset=i，+iso rep=2i+1，-iso rep=2i+2）的相位。

        per-orbital 状态记录在 _vmd_orbital_flips（键=标签），重复点击可来回翻转；
        current_iso 始终为正的绝对值（与等值面滑杆一致）。
        """
        flips = self._vmd_orbital_flips
        flips[label] = not flips.get(label, False)
        iso = abs(float(self.current_iso))
        rp = 2 * i + 1
        rn = 2 * i + 2
        rp_val = -iso if flips[label] else iso
        rn_val = iso if flips[label] else -iso
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect(("127.0.0.1", self.vmd_port))
            cmd1 = f"mol modstyle {rp} top Isosurface {rp_val} {i} 0 0 1 1"
            cmd2 = f"mol modstyle {rn} top Isosurface {rn_val} {i} 0 0 1 1"
            sock.sendall((cmd1 + "\n").encode("utf-8"))
            try:
                resp1 = sock.recv(4096).decode("utf-8", errors="replace").strip()
            except socket.timeout:
                resp1 = "(timeout)"
            sock.sendall((cmd2 + "\n").encode("utf-8"))
            try:
                resp2 = sock.recv(4096).decode("utf-8", errors="replace").strip()
            except socket.timeout:
                resp2 = "(timeout)"
            sock.close()
            ok = "ERROR" not in (resp1 + resp2)
            if log:
                self._append_log(
                    self._tr("log_flip_one", label=label) if ok
                    else f"翻转相位失败: resp1={resp1} resp2={resp2}")
        except Exception as e:
            self._append_log(f"翻转相位失败 (连接): {e}")

    def _apply_iso_change(self):
        iso = self.current_iso
        self.iso_slider.blockSignals(True)
        self.iso_slider.setValue(int(iso * 1000))
        self.iso_slider.blockSignals(False)
        self.iso_edit.blockSignals(True)
        self.iso_edit.setText(f"{iso:.3f}")
        self.iso_edit.blockSignals(False)
        self._vmd_session.set_isovalue(iso)
        self._append_log(self._tr("log_iso_change", iso=iso, status="OK"))

    def _apply_opacity_change(self):
        op = self.current_opacity
        self.opacity_slider.blockSignals(True)
        self.opacity_slider.setValue(int(op * 100))
        self.opacity_slider.blockSignals(False)
        self.opacity_edit.blockSignals(True)
        self.opacity_edit.setText(f"{op:.2f}")
        self.opacity_edit.blockSignals(False)
        self._vmd_session.set_opacity(op)
        self._append_log(self._tr("log_opacity_change", op=op))

    # ── Button State Management ──

    def _set_buttons_state(self, state):
        if state == "running":
            self.btn_run.setEnabled(False)
            self.btn_preview.setEnabled(False)
            if _HAS_GL_VIEWER:
                getattr(self, "btn_gl_preview", None)  # OpenGL 按钮已移除
            self.btn_render.setEnabled(False)
            self.btn_h_filter.setEnabled(False)
            self.btn_dash_mode.setEnabled(False)
            self.btn_flip_phase.setEnabled(False)
            self.iso_slider.setEnabled(False)
            self.opacity_slider.setEnabled(False)
            self.iso_edit.setEnabled(False)
            self.opacity_edit.setEnabled(False)
        else:
            self.btn_run.setEnabled(True)
            self._vmd_orbital_labels = []

