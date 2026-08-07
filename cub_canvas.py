"""
cub_canvas.py — 可嵌入的 Cube 可视化画布组件
=================================================
把 cub_viewer.py 的 OpenGL 渲染管线 (CubGLWidget) 封装成一个普通
QWidget，可以直接放进主程序 (main_window.py) 的左侧面板作为画布使用。

与 cub_viewer.CubViewer 的区别：
  * 继承 QWidget 而非 QMainWindow —— 可被任意布局/Splitter 收纳；
  * 控制项收拢成一条紧凑工具条 + 可折叠的参数区，节省左侧空间；
  * 提供 load_cube() / set_cube_list() 等公开接口供主窗口调用；
  * 不含 sys.argv 解析与独立窗口样式。

渲染内核 100% 复用 cub_viewer，任何渲染改动自动同步。
"""

import os

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QPushButton, QSlider, QGroupBox, QFileDialog, QMessageBox,
    QGridLayout, QCheckBox, QSizePolicy, QToolButton, QFrame, QColorDialog,
    QListView,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QDoubleValidator, QColor

from cub_viewer import (
    CubGLWidget, STYLE_NAMES, STYLE_DISPLAY, IBOVIEW_DEFAULTS,
    MOL_STYLE_NAMES, MOL_STYLE_DISPLAY, _ensure_pyopengl,
    SHININESS_PRESETS, SHININESS_DEFAULT,
)
from marching_cubes import read_cube, relative_iso_threshold
from color_wheel import ColorWheelWidget


class _LimitedStyleCombo(QComboBox):
    """QComboBox 子类：重写 showPopup，强制把下拉弹出窗口固定在一个
    较低的高度，超出部分用滚动条浏览。

    Qt 默认的弹出容器（QComboBoxPrivateContainer）计算高度时不一定遵守
    view 的 maximumHeight，setMaxVisibleItems 对自定义 view 也未必生效；
    只有直接把弹出窗口 setFixedHeight 才是跨版本都可靠的方案（与 VMD
    那种短小的 Representation 下拉框行为一致）。
    """
    def __init__(self, max_popup_height=220, parent=None):
        super().__init__(parent)
        self._popup_height = max_popup_height
        view = QListView()
        view.setUniformItemSizes(True)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)  # type: ignore[attr-defined]
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # type: ignore[attr-defined]
        self.setView(view)

    def showPopup(self):
        super().showPopup()
        popup = self.view().window()
        popup.setFixedHeight(self._popup_height)


# 画布区配色 —— 与 theme.LIGHT_QSS 浅色科技风保持一致。
# 只补充 LIGHT_QSS 中没有覆盖到的部分（工具条容器、GL 外框、状态栏），
# 其余控件（QPushButton / QComboBox / QSlider ...）直接继承全局主题，
# 这样主题一改，画布自动跟随。
_CANVAS_QSS = """
QWidget#CubCanvasRoot {
    background-color: #E4EAF2;
}

/* 顶部工具条：白底 + 底部细分隔线，呼应 QGroupBox 的白色卡片 */
QWidget#CubToolBar {
    background-color: #FFFFFF;
    border-bottom: 1px solid #CBD5E1;
}

QWidget#CubToolBar QLabel {
    color: #4A5568;
    font-size: 9pt;
    padding: 0px 2px;
}

/* 参数区：淡灰底，和主窗口背景同色系 */
QFrame#CubParams {
    background-color: #F5F6FA;
    border-top: 1px solid #CBD5E1;
}

/* 状态栏文字 */
QLabel#CubStatus {
    color: #5C6BC0;
    font-size: 8.5pt;
    background-color: #EEF2FF;
    border-top: 1px solid #C5CAE9;
    padding: 4px 10px;
}

/* 工具条上的小按钮，压扁一点以免占高 */
QWidget#CubToolBar QPushButton,
QWidget#CubToolBar QToolButton {
    padding: 5px 12px;
    font-size: 9pt;
}

QToolButton {
    background-color: #F8FAFE;
    border: 1px solid #CBD5E1;
    border-radius: 5px;
    color: #2C3E50;
    font-weight: bold;
}

QToolButton:hover {
    background-color: #E3F2FD;
    border: 1px solid #1E88E5;
    color: #1565C0;
}

QToolButton:checked {
    background-color: #BBDEFB;
    border: 1px solid #1565C0;
    color: #0D47A1;
}

/* 参数区里的分组框收紧内边距，避免左侧面板太挤 */
QFrame#CubParams QGroupBox {
    margin-top: 14px;
    padding: 14px 10px 8px 10px;
}
"""


class CubCanvasPanel(QWidget):
    """可嵌入主窗口的 cube 画布。

    信号:
        statusChanged(str)  渲染/加载状态文本，方便主窗口写进日志或状态栏。
    """

    statusChanged = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CubCanvasRoot")
        self.setStyleSheet(_CANVAS_QSS)
        self.setAcceptDrops(True)

        self._gl_ok = _ensure_pyopengl()
        self._cube_paths = []
        self._loaded_path = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        if not self._gl_ok:
            tip = QLabel("未安装 PyOpenGL，画布不可用。\n"
                         "请运行: pip install PyOpenGL PyOpenGL-accelerate")
            tip.setAlignment(Qt.AlignCenter)
            tip.setStyleSheet("color:#94A3B8; font-size:10pt; background:#F5F6FA;")
            root.addWidget(tip)
            self.glw = None
            return

        root.addWidget(self._build_toolbar())

        # GL 画布：无边框，直接铺满
        self.glw = CubGLWidget(self)
        self.glw.set_status_callback(self._set_status)
        self.glw.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.glw.setMinimumSize(320, 240)
        self.glw.setStyleSheet("border: none; background: transparent;")
        root.addWidget(self.glw, stretch=1)

        self._params = self._build_params()
        self._params.setVisible(True)
        root.addWidget(self._params)

        self._status_lbl = QLabel("渲染器初始化中…")
        self._status_lbl.setObjectName("CubStatus")
        self._status_lbl.hide()
        root.addWidget(self._status_lbl)

    # ── UI 构建 ────────────────────────────────────────────────
    def _build_toolbar(self):
        bar = QWidget()
        bar.setObjectName("CubToolBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(6, 4, 6, 4)
        h.setSpacing(6)

        # 轨道 cube 下拉框与"打开…"按钮已移除：轨道预览由双击轨道表格自动触发。
        # 内部仍维护 _cube_paths / _loaded_path，供 load_cube 正常渲染。

        h.addWidget(QLabel("风格:"))
        self._style_cb = _LimitedStyleCombo(max_popup_height=220)
        self._style_cb.addItems(STYLE_DISPLAY)
        self._style_cb.setMinimumWidth(150)
        self._style_cb.currentIndexChanged.connect(self._on_style)
        h.addWidget(self._style_cb, stretch=1)

        h.addWidget(QLabel("分子:"))
        self._mol_style_cb = _LimitedStyleCombo(max_popup_height=200)
        self._mol_style_cb.addItems(MOL_STYLE_DISPLAY)
        self._mol_style_cb.setMinimumWidth(120)
        self._mol_style_cb.setToolTip("球棍模型配色：CPK 按元素 / VMD 单色随风格")
        self._mol_style_cb.currentIndexChanged.connect(self._on_mol_style)
        h.addWidget(self._mol_style_cb)

        h.addWidget(QLabel("光泽:"))
        self._shiny_cb = QComboBox()
        self._shiny_cb.addItems(list(SHININESS_PRESETS.keys()))
        self._shiny_cb.setMinimumWidth(120)
        self._shiny_cb.setCurrentText(SHININESS_DEFAULT)
        self._shiny_cb.setToolTip("IboView 光泽预设：调节原子与等值面的 Phong 高光")
        self._shiny_cb.currentIndexChanged.connect(self._on_shiny)
        h.addWidget(self._shiny_cb)

        btn_reset = QPushButton("重置视角")
        btn_reset.setObjectName("SmallBtn")
        btn_reset.clicked.connect(self._reset_view)
        h.addWidget(btn_reset)

        self._more_btn = QToolButton()
        self._more_btn.setText("参数 ▴")
        self._more_btn.setCheckable(True)
        self._more_btn.setChecked(True)
        self._more_btn.setToolTip("展开等值面 / 球棍 / 导出参数")
        self._more_btn.toggled.connect(self._on_toggle_params)
        h.addWidget(self._more_btn)

        return bar

    def _build_params(self):
        box = QFrame()
        box.setObjectName("CubParams")
        outer = QHBoxLayout(box)
        outer.setContentsMargins(6, 4, 6, 6)
        outer.setSpacing(8)

        # 当前背景色 (r,g,b,a)；默认不透明白底
        if not hasattr(self, "_bg_rgba"):
            self._bg_rgba = (1.0, 1.0, 1.0, 1.0)

        # 等值面
        gi = QGroupBox("等值面")
        il = QGridLayout(gi)
        il.setContentsMargins(8, 6, 8, 6)
        il.setSpacing(4)
        # 让滑块所在列（第1列）横向拉伸，使等值面大小/透明度滑块更长
        il.setColumnStretch(1, 1)

        self._rel_chk = QCheckBox(
            f"IboView 相对阈值 ({IBOVIEW_DEFAULTS['IsoThreshold']:.0f}%)")
        self._rel_chk.setToolTip(
            "勾选后按 IboView IsoThreshold 语义取等值面：\n"
            "选取使 |data| 累积权重达到指定百分比的等值面。\n"
            "取消勾选则使用下方的绝对 isovalue（cube 文件原始单位）。")
        self._rel_chk.toggled.connect(self._on_rel_mode)
        il.addWidget(self._rel_chk, 0, 0, 1, 3)

        il.addWidget(QLabel("百分比:"), 1, 0)
        self._rel_sld = QSlider(Qt.Horizontal)
        self._rel_sld.setRange(50, 99)
        self._rel_sld.setValue(int(IBOVIEW_DEFAULTS['IsoThreshold']))
        self._rel_sld.setEnabled(False)
        self._rel_sld.valueChanged.connect(self._on_rel_slider)
        il.addWidget(self._rel_sld, 1, 1)
        self._rel_lbl = QLabel(f"{IBOVIEW_DEFAULTS['IsoThreshold']:.0f}%")
        self._rel_lbl.setMinimumWidth(44)
        il.addWidget(self._rel_lbl, 1, 2)

        # 隐藏相对阈值相关控件（用户不需要；仍保留逻辑，默认未勾选）
        self._rel_chk.hide()
        self._rel_lbl.hide()  # 第1行“百分比:”标签
        _rel_pct_lbl = il.itemAtPosition(1, 0)
        if _rel_pct_lbl is not None:
            _rel_pct_lbl.widget().hide()
        self._rel_sld.hide()

        il.addWidget(QLabel("等值面大小:"), 2, 0)
        self._iso_sld = QSlider(Qt.Horizontal)
        self._iso_sld.setRange(1, 500)
        self._iso_sld.setValue(50)
        self._iso_sld.setMinimumWidth(200)
        self._iso_sld.valueChanged.connect(self._on_iso_slider)
        il.addWidget(self._iso_sld, 2, 1)
        self._iso_edit = QLineEdit("0.050")
        self._iso_edit.setValidator(QDoubleValidator(0.005, 0.5, 4))
        self._iso_edit.setMaximumWidth(64)
        self._iso_edit.editingFinished.connect(self._on_iso_edit)
        il.addWidget(self._iso_edit, 2, 2)

        il.addWidget(QLabel("透明度:"), 3, 0)
        self._op_sld = QSlider(Qt.Horizontal)
        self._op_sld.setRange(5, 100)
        # 滑块值直接表示“透明度(%)”，与 opacity 互补：opacity = 1 - 值/100
        self._op_sld.setValue(int((1.0 - IBOVIEW_DEFAULTS['OrbitalOpacity']) * 100))
        self._op_sld.setMinimumWidth(200)
        self._op_sld.valueChanged.connect(self._on_op)
        il.addWidget(self._op_sld, 3, 1)
        self._op_edit = QLineEdit(f"{1.0 - IBOVIEW_DEFAULTS['OrbitalOpacity']:.2f}")
        self._op_edit.setValidator(QDoubleValidator(0.0, 1, 2))
        self._op_edit.setMaximumWidth(64)
        self._op_edit.editingFinished.connect(self._on_op_edit)
        il.addWidget(self._op_edit, 3, 2)

        self._dp_chk = QCheckBox(
            f"Depth peeling ({IBOVIEW_DEFAULTS['DepthPeelingLayers']} 层)")
        self._dp_chk.setChecked(True)
        self._dp_chk.setToolTip("关闭后回退到按 chunk 深度排序的 alpha 混合")
        self._dp_chk.toggled.connect(self._on_dp_toggle)

        # Depth peeling 与 网格精度 放同一行（HBox 统一间距）
        dp_row = QWidget()
        dpl = QHBoxLayout(dp_row)
        dpl.setContentsMargins(0, 0, 0, 0)
        dpl.setSpacing(12)
        dpl.addWidget(self._dp_chk)
        dpl.addStretch(1)
        dpl.addWidget(QLabel("网格精度:"))
        self._grid_quality_cb = QComboBox()
        self._grid_quality_cb.addItems(["低 (1)", "中 (2)", "高 (3)"])
        self._grid_quality_cb.setCurrentIndex(1)
        self._grid_quality_cb.setToolTip("生成轨道 cube 的网格密度：1=稀疏，2=中等，3=精细")
        self._grid_quality_cb.setMaximumWidth(110)
        dpl.addWidget(self._grid_quality_cb)
        il.addWidget(dp_row, 4, 0, 1, 3)

        # 色轮 / 重置 / 启用色轮配色 / 相位色 统一放一行（HBox 保证间距一致）
        wheel_row = QWidget()
        wl = QHBoxLayout(wheel_row)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(12)  # 统一间隙，避免 grid 列宽不一导致的拥挤/错位

        wl.addWidget(QLabel("色轮:"))
        self._color_wheel = ColorWheelWidget(size=84)
        self._color_wheel.setToolTip("拖动旋转色轮：转一圈循环改变等值面配色")
        self._color_wheel.hueChanged.connect(self._on_wheel_hue)
        wl.addWidget(self._color_wheel)

        self._wheel_btn = QPushButton("重置")
        self._wheel_btn.setObjectName("SmallBtn")
        self._wheel_btn.setMaximumWidth(54)
        self._wheel_btn.setToolTip("恢复样式默认配色")
        self._wheel_btn.clicked.connect(self._on_wheel_reset)
        wl.addWidget(self._wheel_btn)

        # 启用色轮：默认关闭，避免覆盖样式（style）里的正/负相位配色
        self._wheel_enabled = False
        self._wheel_en_chk = QCheckBox("启用色轮配色")
        self._wheel_en_chk.setToolTip("勾选后由色轮控制正/负相位颜色；否则沿用样式默认配色")
        self._wheel_en_chk.toggled.connect(self._on_wheel_toggle)
        wl.addWidget(self._wheel_en_chk)
        self._color_wheel.setEnabled(False)

        # 相位配色模式：互补色（IboView scheme2）/ 相近色（IboView 默认 scheme0）
        wl.addWidget(QLabel("相位色:"))
        self._phase_mode_btn = QPushButton("互补色")
        self._phase_mode_btn.setObjectName("SmallBtn")
        self._phase_mode_btn.setMaximumWidth(110)
        self._phase_mode_btn.setToolTip("点击切换：互补色（±180°） / 相近色（IboView 默认 ±25°）")
        self._phase_mode_btn.clicked.connect(self._on_phase_mode_toggle)
        wl.addWidget(self._phase_mode_btn)
        self._phase_complementary = True  # True=互补色, False=相近色

        il.addWidget(wheel_row, 6, 0, 1, 6)

        # 翻转相位：交换正/负相位颜色（IboView chkBox_FlipPhase 的等价实现）
        self._phase_flipped = False
        self._flip_phase_btn = QPushButton("翻转相位")
        self._flip_phase_btn.setObjectName("SmallBtn")
        self._flip_phase_btn.setToolTip("交换正/负相位颜色（等价 IboView 翻转相位，几何不变）")
        self._flip_phase_btn.clicked.connect(self._on_flip_phase)
        il.addWidget(self._flip_phase_btn, 7, 0, 1, 3)

        outer.addWidget(gi, stretch=1)

        # 球棍模型
        gb = QGroupBox("球棍模型")
        bl = QGridLayout(gb)
        bl.setContentsMargins(8, 6, 8, 6)
        bl.setSpacing(4)
        # 与等值面组一致：滑块所在列（第1列）横向拉伸
        bl.setColumnStretch(1, 1)

        bl.addWidget(QLabel("原子半径:"), 0, 0)
        self._atom_scale_sld = QSlider(Qt.Horizontal)
        self._atom_scale_sld.setRange(20, 300)
        self._atom_scale_sld.setValue(200)
        self._atom_scale_sld.setMinimumWidth(200)
        self._atom_scale_sld.valueChanged.connect(self._on_atom_scale_sld)
        bl.addWidget(self._atom_scale_sld, 0, 1)
        self._atom_scale_edit = QLineEdit("2.00")
        self._atom_scale_edit.setValidator(QDoubleValidator(0.20, 3.00, 2))
        self._atom_scale_edit.setMaximumWidth(64)
        self._atom_scale_edit.editingFinished.connect(self._on_atom_scale_edit)
        bl.addWidget(self._atom_scale_edit, 0, 2)

        self._outline_color = (0.0, 0.0, 0.0)   # 默认黑边

        bl.addWidget(QLabel("化学键:"), 1, 0)
        self._bond_scale_sld = QSlider(Qt.Horizontal)
        self._bond_scale_sld.setRange(20, 300)
        self._bond_scale_sld.setValue(180)
        self._bond_scale_sld.setMinimumWidth(200)
        self._bond_scale_sld.valueChanged.connect(self._on_bond_scale_sld)
        bl.addWidget(self._bond_scale_sld, 1, 1)
        self._bond_scale_edit = QLineEdit("1.80")
        self._bond_scale_edit.setValidator(QDoubleValidator(0.20, 3.00, 2))
        self._bond_scale_edit.setMaximumWidth(64)
        self._bond_scale_edit.editingFinished.connect(self._on_bond_scale_edit)
        bl.addWidget(self._bond_scale_edit, 1, 2)

        # ── 键收腰 ──
        bl.addWidget(QLabel("键收腰:"), 2, 0)
        self._thinning_sld = QSlider(Qt.Horizontal)
        self._thinning_sld.setRange(20, 100)   # 0.20 .. 1.00 (1.0 = 不收腰)
        self._thinning_sld.setValue(72)
        self._thinning_sld.setMinimumWidth(200)
        self._thinning_sld.valueChanged.connect(self._on_thinning_sld)
        bl.addWidget(self._thinning_sld, 2, 1)
        self._thinning_edit = QLineEdit("0.72")
        self._thinning_edit.setValidator(QDoubleValidator(0.20, 1.00, 2))
        self._thinning_edit.setMaximumWidth(64)
        self._thinning_edit.editingFinished.connect(self._on_thinning_edit)
        bl.addWidget(self._thinning_edit, 2, 2)

        # ── 成键阈值（已隐藏：使用 cub_viewer 中的默认值 1.0 / 1.3 / 0.4） ──
        # 保留底层回调（_on_brf_tight_edit / _on_brf_loose_edit / _on_dash_w_edit）
        # 与默认值，仅不显示控件。如需恢复，取消下方注释即可。
        # bl.addWidget(QLabel("成键阈值:"), 3, 0)
        # bl.addWidget(QLabel("实线"), 3, 1)
        # self._brf_tight_edit = QLineEdit("1.00")
        # self._brf_tight_edit.setValidator(QDoubleValidator(0.50, 2.00, 2))
        # self._brf_tight_edit.setMaximumWidth(54)
        # self._brf_tight_edit.editingFinished.connect(self._on_brf_tight_edit)
        # bl.addWidget(self._brf_tight_edit, 3, 2)
        # bl.addWidget(QLabel("虚线"), 3, 3)
        # self._brf_loose_edit = QLineEdit("1.30")
        # self._brf_loose_edit.setValidator(QDoubleValidator(0.50, 3.00, 2))
        # self._brf_loose_edit.setMaximumWidth(54)
        # self._brf_loose_edit.editingFinished.connect(self._on_brf_loose_edit)
        # bl.addWidget(self._brf_loose_edit, 3, 4)
        # bl.addWidget(QLabel("虚密"), 3, 5)
        # self._dash_w_edit = QLineEdit("0.40")
        # self._dash_w_edit.setValidator(QDoubleValidator(0.05, 1.00, 2))
        # self._dash_w_edit.setMaximumWidth(54)
        # self._dash_w_edit.editingFinished.connect(self._on_dash_w_edit)
        # bl.addWidget(self._dash_w_edit, 3, 6)

        # ── 虚线小圆球：大小 / 间隔 ──
        bl.addWidget(QLabel("虚线大小:"), 6, 0)
        self._dot_size_sld = QSlider(Qt.Horizontal)
        self._dot_size_sld.setRange(20, 400)    # ×0.2 .. ×4.0
        self._dot_size_sld.setValue(100)        # ×1.0
        self._dot_size_sld.setMinimumWidth(200)
        self._dot_size_sld.valueChanged.connect(self._on_dot_size_sld)
        bl.addWidget(self._dot_size_sld, 6, 1)
        self._dot_size_edit = QLineEdit("1.00")
        self._dot_size_edit.setValidator(QDoubleValidator(0.20, 4.00, 2))
        self._dot_size_edit.setMaximumWidth(64)
        self._dot_size_edit.editingFinished.connect(self._on_dot_size_edit)
        bl.addWidget(self._dot_size_edit, 6, 2)

        bl.addWidget(QLabel("虚线间隔:"), 7, 0)
        self._dot_spacing_sld = QSlider(Qt.Horizontal)
        self._dot_spacing_sld.setRange(30, 400)  # ×0.3 .. ×4.0
        self._dot_spacing_sld.setValue(100)      # ×1.0
        self._dot_spacing_sld.setMinimumWidth(200)
        self._dot_spacing_sld.valueChanged.connect(self._on_dot_spacing_sld)
        bl.addWidget(self._dot_spacing_sld, 7, 1)
        self._dot_spacing_edit = QLineEdit("1.00")
        self._dot_spacing_edit.setValidator(QDoubleValidator(0.30, 4.00, 2))
        self._dot_spacing_edit.setMaximumWidth(64)
        self._dot_spacing_edit.editingFinished.connect(self._on_dot_spacing_edit)
        bl.addWidget(self._dot_spacing_edit, 7, 2)

        # ── 原子描边 ──
        bl.addWidget(QLabel("原子描边:"), 8, 0)
        self._outline_chk = QCheckBox("启用")
        self._outline_chk.setChecked(False)
        self._outline_chk.toggled.connect(self._on_outline_toggle)
        bl.addWidget(self._outline_chk, 8, 1)
        self._outline_color_btn = QPushButton("颜色")
        self._outline_color_btn.setObjectName("SmallBtn")
        self._outline_color_btn.clicked.connect(self._on_outline_color)
        bl.addWidget(self._outline_color_btn, 8, 2)

        bl.addWidget(QLabel("描边粗细:"), 9, 0)
        self._outline_w_sld = QSlider(Qt.Horizontal)
        self._outline_w_sld.setRange(1, 600)
        self._outline_w_sld.setValue(35)
        self._outline_w_sld.setMinimumWidth(200)
        self._outline_w_sld.valueChanged.connect(self._on_outline_width)
        bl.addWidget(self._outline_w_sld, 9, 1)
        self._outline_w_lbl = QLabel("0.035")
        self._outline_w_lbl.setMaximumWidth(64)
        bl.addWidget(self._outline_w_lbl, 9, 2)

        bl.addWidget(QLabel("DPI:"), 10, 0)
        self._dpi_edit = QLineEdit("600")
        self._dpi_edit.setValidator(QDoubleValidator(50, 2400, 0))
        self._dpi_edit.setMaximumWidth(64)
        bl.addWidget(self._dpi_edit, 10, 1)
        self._bg_color_btn = QPushButton("背景色")
        self._bg_color_btn.setObjectName("SmallBtn")
        self._bg_color_btn.setToolTip("设置导出/预览的背景颜色")
        self._bg_color_btn.clicked.connect(self._on_bg_color)
        bl.addWidget(self._bg_color_btn, 10, 2)

        self._transparent_chk = QCheckBox("透明背景")
        self._transparent_chk.setToolTip(
            "导出 PNG 时背景透明（背景 alpha=0，参照 IboView）")
        bl.addWidget(self._transparent_chk, 11, 0, 1, 2)

        btn_sc = QPushButton("快速截图")
        btn_sc.setObjectName("SmallBtn")
        btn_sc.clicked.connect(self._screenshot)
        bl.addWidget(btn_sc, 11, 2)

        # 导出图片：移到球棍模型区域底部，蓝色背景突出
        btn_ex = QPushButton("导出图片")
        btn_ex.setObjectName("ExportImageBtn")
        btn_ex.setMinimumHeight(30)
        btn_ex.setStyleSheet(
            "QPushButton#ExportImageBtn { background-color: #2E6FD6; color: #ffffff;"
            " border: none; border-radius: 4px; font-weight: 600; }"
            "QPushButton#ExportImageBtn:hover { background-color: #3B7DE8; }"
            "QPushButton#ExportImageBtn:pressed { background-color: #2257AE; }")
        btn_ex.setToolTip("离屏分块超采样渲染，输出高 DPI PNG（可透明背景）")
        btn_ex.clicked.connect(self._export_image)
        bl.addWidget(btn_ex, 12, 0, 1, 3)

        outer.addWidget(gb, stretch=1)
        return box

    # ── 公开接口 ───────────────────────────────────────────────
    def is_available(self) -> bool:
        """OpenGL 画布是否可用。"""
        return self.glw is not None

    def grid_quality(self) -> str:
        """返回网格精度档位（'1'/'2'/'3'），供 cube 生成使用。"""
        if not hasattr(self, "_grid_quality_cb"):
            return "2"
        return str(self._grid_quality_cb.currentIndex() + 1)

    # ── 色轮（IboView 风格配色） ─────────────────────────
    def _on_wheel_toggle(self, checked):
        """启用/禁用色轮配色：禁用时恢复样式默认配色，避免与样式冲突。"""
        self._wheel_enabled = bool(checked)
        self._color_wheel.setEnabled(self._wheel_enabled)
        if not self.glw:
            return
        if self._wheel_enabled:
            # 启用后立即按当前色相应用一次
            self._on_wheel_hue(self._color_wheel.hue())
        else:
            # 恢复样式（style）默认正/负相位配色
            style_name = getattr(self.glw, "_style_name", None)
            if style_name:
                self.glw.set_style(style_name)

    def _on_wheel_hue(self, hue):
        """旋转色轮：正相位 = hue，负相位依当前模式计算。

        - 互补色（IboView scheme2）：负相位 = hue + 0.5（色环正对面，相差 180°）
        - 相近色（IboView 默认 scheme0，spread=50°）：负相位 = hue - 25°/360

        仅当色轮已启用（_wheel_enabled）时生效，否则沿用样式配色。
        """
        if not self._wheel_enabled or self.glw is None:
            return
        pos = ColorWheelWidget.hue_to_rgb(hue)
        if self._phase_complementary:
            neg = ColorWheelWidget.hue_to_rgb((hue + 0.5) % 1.0)
        else:
            neg = ColorWheelWidget.hue_to_rgb((hue - 25.0 / 360.0) % 1.0)
        if self._phase_flipped:
            pos, neg = neg, pos
        self.glw.set_phase_colors(pos_rgb=pos, neg_rgb=neg)

    def _on_phase_mode_toggle(self):
        """在互补色 / 相近色两种模式间切换，并立即按当前色相重渲染。"""
        if not self._wheel_enabled:
            return
        self._phase_complementary = not self._phase_complementary
        self._phase_mode_btn.setText("互补色" if self._phase_complementary else "相近色")
        self._on_wheel_hue(self._color_wheel.hue())

    def _on_flip_phase(self):
        """翻转相位：交换正/负相位颜色（等价 IboView chkBox_FlipPhase）。

        直接作用于 glw 当前配色（样式或色轮均可），与色轮启用与否无关，
        几何不变。已翻转时再次点击即翻转回来。
        """
        if self.glw is None:
            return
        self.glw.flip_phase()
        self._phase_flipped = not self._phase_flipped
        self._flip_phase_btn.setText("相位已翻 ✓" if self._phase_flipped else "翻转相位")

    def _on_wheel_reset(self):
        """恢复当前样式默认配色（等价于取消色轮配色）。"""
        if not self._wheel_enabled or self.glw is None:
            return
        style_name = getattr(self.glw, "_style_name", None)
        if style_name:
            self.glw.set_style(style_name)  # 重新解析默认正/负相位色
        self._color_wheel.set_hue(0.33)

    def set_cube_list(self, paths, auto_load=True):
        """记录一批 cube 文件路径；auto_load 时自动渲染第一个。
        顶部下拉框已移除，这里仅维护 _cube_paths 并触发渲染。"""
        if self.glw is None:
            return
        self._cube_paths = [p for p in (paths or []) if os.path.isfile(p)]
        if self._cube_paths and auto_load:
            self.load_cube(self._cube_paths[0])

    def load_cube(self, path, iso=None, style_name=None):
        """在画布中加载并渲染一个 cube 文件。"""
        if self.glw is None or not path or not os.path.isfile(path):
            return False

        # 记录路径（顶部下拉框已移除，仅维护列表）
        if path not in self._cube_paths:
            self._cube_paths.append(path)

        if style_name:
            self.set_style_name(style_name)

        if iso is not None:
            try:
                self.set_isovalue(float(iso))
            except (TypeError, ValueError):
                pass

        try:
            iso_val = float(self._iso_edit.text() or "0.05")
        except ValueError:
            iso_val = 0.05

        note = ""
        if self._rel_chk.isChecked():
            try:
                cd = read_cube(path)
                pct = float(self._rel_sld.value())
                iso_val = relative_iso_threshold(cd, pct)
                self._iso_edit.blockSignals(True)
                self._iso_edit.setText(f"{iso_val:.4f}")
                self._iso_edit.blockSignals(False)
                note = f"  (相对阈值 {pct:.0f}% -> iso={iso_val:.4f})"
            except Exception as e:
                self._set_status(f"相对阈值计算失败，改用绝对值: {e}")

        self.glw.set_style(STYLE_NAMES[self._style_cb.currentIndex()])
        ok = self.glw.load(path, iso_val)
        if ok:
            self._loaded_path = path
            self._set_status(f"已加载: {os.path.basename(path)}{note}")
        else:
            self._set_status(f"加载失败: {os.path.basename(path)}")
        return ok

    def set_style_name(self, name):
        """按风格名切换（与 fchk_orbital.STYLES 的 key 一致）。"""
        if self.glw is None or name not in STYLE_NAMES:
            return
        idx = STYLE_NAMES.index(name)
        if self._style_cb.currentIndex() != idx:
            self._style_cb.setCurrentIndex(idx)
        else:
            self.glw.set_style(name)

    def set_isovalue(self, iso):
        """同步 isovalue 到画布与控件。"""
        if self.glw is None:
            return
        iso = max(0.005, min(float(iso), 0.5))
        self._iso_edit.blockSignals(True)
        self._iso_edit.setText(f"{iso:.4f}")
        self._iso_edit.blockSignals(False)
        self._iso_sld.blockSignals(True)
        self._iso_sld.setValue(int(round(iso * 1000)))
        self._iso_sld.blockSignals(False)
        self.glw.set_isovalue(iso)

    def clear(self):
        """清空下拉列表（不销毁 GL 上下文）。"""
        if self.glw is None:
            return
        self._cube_paths = []
        self._loaded_path = None

    def current_cube(self):
        return self._loaded_path

    def set_molecule(self, atoms, bonds=None):
        """载入 fchk/xyz 后把分子结构推到 GL 画布，使其立即显示球棍模型。"""
        if self.glw is not None:
            self.glw.set_molecule(atoms, bonds)

    # ── 内部回调 ───────────────────────────────────────────────
    def _set_status(self, msg):
        if hasattr(self, "_status_lbl"):
            self._status_lbl.setText(str(msg))
        self.statusChanged.emit(str(msg))

    def _on_toggle_params(self, on):
        self._params.setVisible(bool(on))
        self._more_btn.setText("参数 ▴" if on else "参数 ▾")

    def show_params_panel(self, visible):
        """外部控制画布参数区是否显示在画布下方。"""
        self._params.setVisible(bool(visible))
        self._more_btn.setChecked(bool(visible))
        self._more_btn.setText("参数 ▴" if visible else "参数 ▾")

    def _on_cube_pick(self, idx):
        if 0 <= idx < len(self._cube_paths):
            self.load_cube(self._cube_paths[idx])

    def _browse(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "选择 Cube 文件", "", "Cube Files (*.cub *.cube);;All (*)")
        if p:
            self.load_cube(p)

    def _reset_view(self):
        if self.glw is not None:
            self.glw.reset_view()

    def _on_style(self, idx):
        if self.glw is not None and 0 <= idx < len(STYLE_NAMES):
            self.glw.set_style(STYLE_NAMES[idx])
            # 若分子样式为 VMD 单色，跟随等值面风格切换碳色
            if self.glw is not None and self._mol_style_cb.currentIndex() == 1:
                self.glw.set_mol_style("VMD single")

    def _on_mol_style(self, idx):
        if self.glw is None or not (0 <= idx < len(MOL_STYLE_NAMES)):
            return
        name = MOL_STYLE_NAMES[idx]
        # widget 内部会按当前等值面风格的 c_rgb 取碳色（VMD single 时）
        self.glw.set_mol_style(name)

    def _on_shiny(self, idx):
        if self.glw is None or not (0 <= idx < len(SHININESS_PRESETS)):
            return
        name = list(SHININESS_PRESETS.keys())[idx]
        self.glw.set_shininess(name)

    def _on_rel_mode(self, on):
        self._rel_sld.setEnabled(bool(on))
        self._iso_sld.setEnabled(not on)
        self._iso_edit.setEnabled(not on)
        if on and self._loaded_path:
            self._on_rel_slider(self._rel_sld.value())

    def _on_rel_slider(self, v):
        self._rel_lbl.setText(f"{v}%")
        if not self._rel_chk.isChecked() or self.glw is None:
            return
        if self.glw.cube is None:
            return
        try:
            iso = relative_iso_threshold(self.glw.cube, float(v))
        except Exception:
            return
        self._iso_edit.blockSignals(True)
        self._iso_edit.setText(f"{iso:.4f}")
        self._iso_edit.blockSignals(False)
        self.glw.set_isovalue(iso)

    def _on_dp_toggle(self, on):
        if self.glw is not None:
            self.glw.set_depth_peeling(bool(on))

    def _on_iso_slider(self, v):
        iso = v / 1000.0
        self._iso_edit.blockSignals(True)
        self._iso_edit.setText(f"{iso:.3f}")
        self._iso_edit.blockSignals(False)
        if self.glw is not None:
            self.glw.set_isovalue(iso)

    def _on_iso_edit(self):
        try:
            iso = float(self._iso_edit.text())
        except ValueError:
            return
        self.set_isovalue(iso)

    def _on_op(self, v):
        # 滑块值 = 透明度(%)；opacity = 1 - 透明度
        transparency = v / 100.0
        op = 1.0 - transparency
        self._op_edit.setText(f"{transparency:.2f}")
        if self.glw is not None:
            self.glw.set_opacity(op)

    def _on_op_edit(self):
        try:
            transparency = float(self._op_edit.text())
        except ValueError:
            return
        transparency = max(0.0, min(transparency, 1.0))
        op = 1.0 - transparency
        self._op_sld.blockSignals(True)
        self._op_sld.setValue(int(transparency * 100))
        self._op_sld.blockSignals(False)
        if self.glw is not None:
            self.glw.set_opacity(op)

    def _on_atom_scale_sld(self, val):
        s = val / 100.0
        self._atom_scale_edit.blockSignals(True)
        self._atom_scale_edit.setText(f"{s:.2f}")
        self._atom_scale_edit.blockSignals(False)
        if self.glw is not None:
            self.glw.set_atom_scale(s)

    def _on_atom_scale_edit(self):
        try:
            s = float(self._atom_scale_edit.text())
        except ValueError:
            return
        s = max(0.20, min(s, 3.00))
        self._atom_scale_sld.blockSignals(True)
        self._atom_scale_sld.setValue(int(s * 100))
        self._atom_scale_sld.blockSignals(False)
        if self.glw is not None:
            self.glw.set_atom_scale(s)

    def _on_bond_scale_sld(self, val):
        s = val / 100.0
        self._bond_scale_edit.blockSignals(True)
        self._bond_scale_edit.setText(f"{s:.2f}")
        self._bond_scale_edit.blockSignals(False)
        if self.glw is not None:
            self.glw.set_bond_scale(s)

    def _on_bond_scale_edit(self):
        try:
            s = float(self._bond_scale_edit.text())
        except ValueError:
            return
        s = max(0.20, min(s, 3.00))
        self._bond_scale_sld.blockSignals(True)
        self._bond_scale_sld.setValue(int(s * 100))
        self._bond_scale_sld.blockSignals(False)
        if self.glw is not None:
            self.glw.set_bond_scale(s)

    def _on_thinning_sld(self, v):
        t = v / 100.0
        self._thinning_edit.blockSignals(True)
        self._thinning_edit.setText(f"{t:.2f}")
        self._thinning_edit.blockSignals(False)
        if self.glw is not None:
            self.glw.set_bond_thinning(t)

    def _on_thinning_edit(self):
        try:
            t = float(self._thinning_edit.text())
        except ValueError:
            return
        t = max(0.20, min(t, 1.00))
        self._thinning_sld.blockSignals(True)
        self._thinning_sld.setValue(int(t * 100))
        self._thinning_sld.blockSignals(False)
        if self.glw is not None:
            self.glw.set_bond_thinning(t)

    # ── 成键阈值控制（控件已隐藏，方法保留但仅当属性存在时生效） ──
    def _on_brf_tight_edit(self):
        if not hasattr(self, '_brf_tight_edit'):
            return
        try:
            v = float(self._brf_tight_edit.text())
        except ValueError:
            return
        v = max(0.50, min(v, 2.00))
        self._brf_tight_edit.blockSignals(True)
        self._brf_tight_edit.setText(f"{v:.2f}")
        self._brf_tight_edit.blockSignals(False)
        if self.glw is not None:
            self.glw.set_bond_rf_tight(v)

    def _on_brf_loose_edit(self):
        if not hasattr(self, '_brf_loose_edit'):
            return
        try:
            v = float(self._brf_loose_edit.text())
        except ValueError:
            return
        v = max(0.50, min(v, 3.00))
        self._brf_loose_edit.blockSignals(True)
        self._brf_loose_edit.setText(f"{v:.2f}")
        self._brf_loose_edit.blockSignals(False)
        if self.glw is not None:
            self.glw.set_bond_rf_loose(v)

    def _on_dash_w_edit(self):
        if not hasattr(self, '_dash_w_edit'):
            return
        try:
            v = float(self._dash_w_edit.text())
        except ValueError:
            return
        v = max(0.05, min(v, 1.00))
        self._dash_w_edit.blockSignals(True)
        self._dash_w_edit.setText(f"{v:.2f}")
        self._dash_w_edit.blockSignals(False)
        if self.glw is not None:
            self.glw.set_dash_weight(v)

    def _on_dot_size_sld(self, val):
        v = val / 100.0   # ×0.2 .. ×4.0
        self._dot_size_edit.blockSignals(True)
        self._dot_size_edit.setText(f"{v:.2f}")
        self._dot_size_edit.blockSignals(False)
        if self.glw is not None:
            self.glw.set_dot_size(v)

    def _on_dot_size_edit(self):
        try:
            v = float(self._dot_size_edit.text())
        except ValueError:
            return
        v = max(0.20, min(v, 4.00))
        self._dot_size_sld.blockSignals(True)
        self._dot_size_sld.setValue(int(v * 100))
        self._dot_size_sld.blockSignals(False)
        if self.glw is not None:
            self.glw.set_dot_size(v)

    def _on_dot_spacing_sld(self, val):
        v = val / 100.0   # ×0.3 .. ×4.0
        self._dot_spacing_edit.blockSignals(True)
        self._dot_spacing_edit.setText(f"{v:.2f}")
        self._dot_spacing_edit.blockSignals(False)
        if self.glw is not None:
            self.glw.set_dot_spacing(v)

    def _on_dot_spacing_edit(self):
        try:
            v = float(self._dot_spacing_edit.text())
        except ValueError:
            return
        v = max(0.30, min(v, 4.00))
        self._dot_spacing_sld.blockSignals(True)
        self._dot_spacing_sld.setValue(int(v * 100))
        self._dot_spacing_sld.blockSignals(False)
        if self.glw is not None:
            self.glw.set_dot_spacing(v)

    # ── 原子描边控制 ──
    def _on_outline_toggle(self, on):
        if self.glw is None:
            return
        self.glw.set_atom_outline(on)

    def _on_outline_color(self):
        cur = self._outline_color
        col = QColorDialog.getColor(QColor(int(cur[0] * 255), int(cur[1] * 255),
                                           int(cur[2] * 255)), self, "描边颜色")
        if not col.isValid():
            return
        self._outline_color = (col.redF(), col.greenF(), col.blueF())
        if self.glw is not None:
            self.glw.set_atom_outline(self._outline_chk.isChecked(), color=self._outline_color)

    def _on_bg_color(self):
        cur = self._bg_rgba
        col = QColorDialog.getColor(
            QColor(int(cur[0] * 255), int(cur[1] * 255), int(cur[2] * 255)),
            self, "背景颜色")
        if not col.isValid():
            return
        self._bg_rgba = (col.redF(), col.greenF(), col.blueF(), 1.0)
        if self.glw is not None:
            self.glw.set_background(self._bg_rgba)

    def _on_outline_width(self, v):
        w = v / 1000.0
        self._outline_w_lbl.setText(f"{w:.3f}")
        if self.glw is not None:
            self.glw.set_atom_outline(self._outline_chk.isChecked(), width=w)

    def _screenshot(self):
        if self.glw is None:
            return
        base = os.path.splitext(os.path.basename(self._loaded_path or "cub_view"))[0]
        p, _ = QFileDialog.getSaveFileName(self, "保存截图", base + ".png", "PNG (*.png)")
        if p:
            self.glw.screenshot(p)

    def _export_image(self):
        if self.glw is None:
            return
        if self._loaded_path is None:
            QMessageBox.information(self, "提示", "请先加载一个 cube 文件。")
            return
        base = os.path.splitext(os.path.basename(self._loaded_path))[0]
        p, _ = QFileDialog.getSaveFileName(self, "导出高分辨率图片",
                                           base + ".png", "PNG (*.png)")
        if not p:
            return
        try:
            dpi = float(self._dpi_edit.text())
        except ValueError:
            dpi = 600.0
        dpi = max(50.0, min(dpi, 2400.0))
        # 透明背景：导出时临时把背景 alpha 设为 0，导出后恢复（参照 IboView）
        restore_bg = None
        if self._transparent_chk.isChecked() and self.glw is not None:
            r, g, b, _ = self._bg_rgba
            restore_bg = self._bg_rgba
            self.glw.set_background((r, g, b, 0.0))
        try:
            self.glw.export_image(p, dpi=dpi)
        finally:
            if restore_bg is not None and self.glw is not None:
                self.glw.set_background(restore_bg)

    # ── 拖放 ───────────────────────────────────────────────────
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            for u in e.mimeData().urls():
                if u.toLocalFile().lower().endswith(('.cub', '.cube')):
                    e.acceptProposedAction()
                    return
        e.ignore()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if p.lower().endswith(('.cub', '.cube')):
                QTimer.singleShot(0, lambda path=p: self.load_cube(path))
                e.acceptProposedAction()
                return
