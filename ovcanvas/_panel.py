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
import math
import json

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QPushButton, QSlider, QGroupBox, QFileDialog, QMessageBox,
    QGridLayout, QCheckBox, QSizePolicy, QToolButton, QFrame, QColorDialog,
    QListView, QDialog, QSpinBox,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QPointF
from PyQt5.QtGui import (
    QDoubleValidator, QColor, QRadialGradient,
    QPainter, QPen, QBrush,
)

from ._glwidget import (
    CubGLWidget, STYLE_NAMES, STYLE_DISPLAY, IBOVIEW_DEFAULTS,
    MOL_STYLE_NAMES, MOL_STYLE_DISPLAY, _ensure_pyopengl,
    SHININESS_PRESETS, SHININESS_DEFAULT,
)
from file_dialogs import open_file, save_file
from marching_cubes import read_cube, relative_iso_threshold
from ._colorwheel import ColorWheelWidget

# 光照/渲染效果轴（与「原子配色」轴正交）：
# 显示名 → 渐变类型名（"" = IboView 三光，即 u_MvGrad=0；光泽由「光泽」下拉框独立控制）
_LIGHTING_OPTIONS = [
    ("IboView 三光", ""),
    ("单光 · Houk", "full"),
    ("单光 · 柔和", "soft_matte"),
    ("单光 · 微妙", "subtle"),
    ("单光 · 平面", "flat"),
    ("单光 · Chem311", "sob_art"),
    ("单光 · 苹果液态", "apple_liquid"),
    ("单光 · 纸感", "paper_matte"),
    ("单光 · 高级", "premium_full"),
    ("单光 · 粘土", "clay_matte"),
    ("单光 · 玻璃", "glass_plus"),
    ("单光 · 霓虹", "neon_glow"),
    ("单光 · 墨线", "ink_flat"),
    ("单光 · GaussView", "gau_default"),
    ("双光源", "two_light"),
    ("四光源", "four_light"),
]

# sob-art 一键样式：光照信息（导出自 light_style3.json，4 灯）
_SOBART_STYLE = {
    "light_count": 4,
    "light_dirs": [
        [0.373134328358209, 0.5373134328358209, 0.7563498184668613],
        [-0.2835820895522388, -0.6865671641791045, 0.6694824325971882],
        [0.05970149253731343, -0.014925373134328358, 0.9981046864059993],
        [-0.5522388059701493, 0.5373134328358209, 0.6374375075839588],
    ],
    "light_glow": 0.51,
    "light_glows": [0.88, 0.88, 0.88, 0.1],
}

# 默认样式「HoukMol」（导出自 HoukMol.json，单光 gau_default，默认不显示十字圆环）
_HOUKMOL_STYLE = {
    "mol_style": "HoukMol",
    "gradient": "gau_default",
    "shininess": "reasonably shiny",
    "light_count": 1,
    "light_dirs": [
        [-0.577, 0.577, 0.577],
        [0.0, 0.0, 1.0],
        [0.0, 0.0, 1.0],
        [0.0, 0.0, 1.0],
    ],
    "light_glow": 1.25,
    "atom_scale": 1.68,
    "bond_scale": 2.0,
    "atom_outline": [True, [0.0, 0.0, 0.0], 0.35],
    "orb_outline": [True, [0.0, 0.0, 0.0], 0.2],
    "orb_opacity": 0.3,
    "phase_pos": [0.6666666666666666, 1.0, 0.4980392156862745],
    "phase_neg": [0.0, 0.6666666666666666, 1.0],
    "bg": [1.0, 1.0, 1.0, 1.0],
    "crosshair": False,
    "fade": False,
    "carbon": None,
    "hydrogen": None,
}

# HoukMol 一键样式的默认圆环方位（导出自 ring_style.json，随分子转；默认不显示）
_HOUKMOL_RING = {
    "on": False,
    "az1": 90.0,
    "tilt1": 79.0,
    "az2": 19.0,
    "tilt2": 11.0,
    "locked": False,
    "width": 0.04,
    "color": [0.05, 0.05, 0.05],
}

# 默认样式「IQmol」（导出自 IQMOL.json：CPK 原子、双光、每灯独立光晕、红/蓝相位）
_IQMOL_STYLE = {
    "mol_style": "CPK",
    "gradient": "",
    "shininess": "reasonably shiny",
    "light_count": 2,
    "light_dirs": [
        [0.40298507462686567, 0.7761194029850746, 0.4850172181872215],
        [0.1791044776119403, 0.04477611940298507, 0.9828106049644375],
        [0.4330127, -0.25, 0.8660254],
        [0.0, 0.0, 1.0],
    ],
    "light_glow": 1.0,
    "light_glows": [0.1, 0.29, 1.0, 1.0],
    "atom_scale": 1.68,
    "bond_scale": 2.0,
    "atom_outline": [False, [0.0, 0.0, 0.0], 0.35],
    "orb_outline": [False, [0.0, 0.0, 0.0], 0.3],
    "orb_opacity": 0.95,
    "phase_pos": [0.8862745098039215, 0.1450980392156863, 0.30980392156862746],
    "phase_neg": [0.0, 0.3843137254901961, 1.0],
    "bg": [1.0, 1.0, 1.0, 1.0],
    "crosshair": False,
    "fade": True,
    "carbon": None,
    "hydrogen": None,
    "depth_peeling": False,
}


def _parse_color(color):
    """把颜色统一成 (r,g,b) 0-255 元组。

    接受 '#rrggbb' / '#rgb' 字符串，或 (r,g,b) / [r,g,b]（0-255）序列。
    """
    if isinstance(color, str):
        c = color.lstrip("#")
        if len(c) == 3:
            c = "".join(ch * 2 for ch in c)
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    return tuple(int(round(float(v))) for v in color[:3])


class RingControlDialog(QDialog):
    """十字圆环控制面板：两条环的方位角/俯仰角 + 锁定开关。

    锁定后圆环固定在屏幕系（分子怎么旋转圆环都不转）；未锁定时圆环随分子旋转。
    """

    def __init__(self, glw, parent=None):
        super().__init__(parent)
        self.glw = glw
        self.setWindowTitle("十字圆环控制")
        self.setMinimumWidth(360)
        f = QGridLayout(self)
        f.setVerticalSpacing(8)

        f.addWidget(QLabel("环 A 方位角:"), 0, 0)
        self.sl_az1 = QSlider(Qt.Horizontal)
        self.sl_az1.setRange(0, 360)
        self.sl_az1.setValue(90)
        self.sl_az1.valueChanged.connect(self._apply)
        f.addWidget(self.sl_az1, 0, 1)

        f.addWidget(QLabel("环 A 俯仰角:"), 1, 0)
        self.sl_tilt1 = QSlider(Qt.Horizontal)
        self.sl_tilt1.setRange(0, 90)
        self.sl_tilt1.setValue(71)
        self.sl_tilt1.valueChanged.connect(self._apply)
        f.addWidget(self.sl_tilt1, 1, 1)

        f.addWidget(QLabel("环 B 方位角:"), 2, 0)
        self.sl_az2 = QSlider(Qt.Horizontal)
        self.sl_az2.setRange(0, 360)
        self.sl_az2.setValue(205)
        self.sl_az2.valueChanged.connect(self._apply)
        f.addWidget(self.sl_az2, 2, 1)

        f.addWidget(QLabel("环 B 俯仰角:"), 3, 0)
        self.sl_tilt2 = QSlider(Qt.Horizontal)
        self.sl_tilt2.setRange(0, 90)
        self.sl_tilt2.setValue(0)
        self.sl_tilt2.valueChanged.connect(self._apply)
        f.addWidget(self.sl_tilt2, 3, 1)

        self.chk_lock = QCheckBox("锁定方位（锁定当前角度，分子旋转时圆环不变）")
        self.chk_lock.setChecked(False)
        self.chk_lock.setToolTip("勾选后把当前圆环角度冻结；分子怎么旋转圆环都不再改变")
        self.chk_lock.toggled.connect(self._apply)
        f.addWidget(self.chk_lock, 4, 0, 1, 2)

        f.addWidget(QLabel("环带粗细:"), 5, 0)
        self.sl_w = QSlider(Qt.Horizontal)
        self.sl_w.setRange(2, 20)          # 0.02 .. 0.20 环带半宽
        self.sl_w.setValue(7)              # 默认 0.07
        self.sl_w.valueChanged.connect(self._apply)
        f.addWidget(self.sl_w, 5, 1)
        self._w_lbl = QLabel("0.07")
        self._w_lbl.setMinimumWidth(34)
        f.addWidget(self._w_lbl, 5, 2)

        btns = QHBoxLayout()
        b_reset = QPushButton("重置默认")
        b_reset.clicked.connect(self._reset)
        b_save = QPushButton("保存…")
        b_save.clicked.connect(self._save)
        b_load = QPushButton("载入…")
        b_load.clicked.connect(self._load)
        b_close = QPushButton("关闭")
        b_close.clicked.connect(self.accept)
        btns.addWidget(b_reset)
        btns.addWidget(b_save)
        btns.addWidget(b_load)
        btns.addStretch(1)
        btns.addWidget(b_close)
        f.addLayout(btns, 6, 0, 1, 2)
        self.sync_from_glw()

    def sync_from_glw(self):
        """从画布当前圆环状态同步滑块。"""
        if self.glw is None:
            return
        self.sl_az1.blockSignals(True)
        self.sl_az1.setValue(int(getattr(self.glw, "_ring_az1", 90) % 360))
        self.sl_az1.blockSignals(False)
        self.sl_tilt1.blockSignals(True)
        self.sl_tilt1.setValue(int(getattr(self.glw, "_ring_tilt1", 71)))
        self.sl_tilt1.blockSignals(False)
        self.sl_az2.blockSignals(True)
        self.sl_az2.setValue(int(getattr(self.glw, "_ring_az2", 205) % 360))
        self.sl_az2.blockSignals(False)
        self.sl_tilt2.blockSignals(True)
        self.sl_tilt2.setValue(int(getattr(self.glw, "_ring_tilt2", 0)))
        self.sl_tilt2.blockSignals(False)
        self.chk_lock.blockSignals(True)
        self.chk_lock.setChecked(bool(getattr(self.glw, "_ring_locked", False)))
        self.chk_lock.blockSignals(False)
        self.sl_w.blockSignals(True)
        self.sl_w.setValue(int(getattr(self.glw, "_ring_width", 0.07) * 100))
        self.sl_w.blockSignals(False)
        self._w_lbl.setText(f"{getattr(self.glw, '_ring_width', 0.07):.2f}")

    def _save(self):
        if self.glw is None:
            return
        p, _ = save_file(self, "保存圆环设置", "ring_style.json",
                         "JSON (*.json)")
        if not p:
            return
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(self.glw.get_ring_state(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))

    def _load(self):
        if self.glw is None:
            return
        p, _ = open_file(self, "载入圆环设置", "", "JSON (*.json)")
        if not p:
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                st = json.load(f)
            self.glw.apply_ring_state(st)
            self.sync_from_glw()
            # 同步主面板「十字圆环」复选框
            par = self.parent()
            if hasattr(par, "_crosshair_chk"):
                par._crosshair_chk.blockSignals(True)
                par._crosshair_chk.setChecked(bool(self.glw._crosshair))
                par._crosshair_chk.blockSignals(False)
        except Exception as e:
            QMessageBox.warning(self, "载入失败", str(e))

    def _apply(self):
        if self.glw is None:
            return
        w = self.sl_w.value() / 100.0
        self._w_lbl.setText(f"{w:.2f}")
        self.glw.set_ring_style(width=w)
        self.glw.set_ring_orientation(
            az1=self.sl_az1.value(), tilt1=self.sl_tilt1.value(),
            az2=self.sl_az2.value(), tilt2=self.sl_tilt2.value(),
            locked=self.chk_lock.isChecked())

    def _reset(self):
        for sl, v in ((self.sl_az1, 90), (self.sl_tilt1, 71),
                      (self.sl_az2, 205), (self.sl_tilt2, 0),
                      (self.sl_w, 7)):
            sl.blockSignals(True)
            sl.setValue(v)
            sl.blockSignals(False)
        self._w_lbl.setText("0.07")
        self.chk_lock.blockSignals(True)
        self.chk_lock.setChecked(False)
        self.chk_lock.blockSignals(False)
        self._apply()


class LightSphereWidget(QWidget):
    """光源球体预览：画一个渐变球，把当前各光源方向投影成光点。

    支持鼠标拖拽光点手动摆放光源方向（dirsChanged 信号通知对话框同步）。
    """
    dirsChanged = pyqtSignal()

    def __init__(self, glw, parent=None):
        super().__init__(parent)
        self.glw = glw
        self.setFixedSize(150, 150)
        self.setToolTip("拖动光点可手动摆放光源方向（球面明暗渐变跟随主光源）")
        self._drag_idx = None

    def _center_r(self):
        w, h = self.width(), self.height()
        return w / 2.0, h / 2.0, min(w, h) / 2.0 - 8

    def _light_pos(self, d):
        cx, cy, r = self._center_r()
        m = math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]) or 1.0
        return cx + (d[0] / m) * r, cy - (d[1] / m) * r

    def _dir_from_pos(self, mx, my):
        cx, cy, r = self._center_r()
        rx = (mx - cx) / r
        ry = (cy - my) / r
        l2 = rx * rx + ry * ry
        if l2 > 1.0:
            inv = 1.0 / math.sqrt(l2)
            return (rx * inv, ry * inv, 0.0)
        return (rx, ry, math.sqrt(max(0.0, 1.0 - l2)))

    def _apply_pos(self, idx, mx, my):
        if self.glw is None:
            return
        self.glw.set_light_dir(idx, self._dir_from_pos(mx, my))
        self.update()
        self.dirsChanged.emit()

    def mousePressEvent(self, e):
        dirs = getattr(self.glw, "_light_dirs", None) or []
        count = getattr(self.glw, "_light_count", 0)
        best, best_d = None, 14.0
        for i in range(min(count, len(dirs))):
            px, py = self._light_pos(dirs[i])
            d = math.hypot(e.x() - px, e.y() - py)
            if d < best_d:
                best, best_d = i, d
        self._drag_idx = best
        if best is not None:
            self._apply_pos(best, e.x(), e.y())

    def mouseMoveEvent(self, e):
        if self._drag_idx is not None:
            self._apply_pos(self._drag_idx, e.x(), e.y())

    def mouseReleaseEvent(self, e):
        self._drag_idx = None

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy, r = self._center_r()
        dirs = getattr(self.glw, "_light_dirs", None) or []
        # 球体底：高光中心跟随主光源（第 0 盏）方向，方向可控。
        # 无光源时退回默认左上（0.35 偏移）。偏移限制在 0.6R 内，保证球面
        # 始终有明暗层次；光源越偏向屏幕中央（z 越大）高光越靠近球心。
        hx, hy = cx - r * 0.35, cy - r * 0.35
        if dirs:
            d0 = dirs[0]
            m = math.sqrt(d0[0] * d0[0] + d0[1] * d0[1] + d0[2] * d0[2]) or 1.0
            hx = cx + (d0[0] / m) * r * 0.6
            hy = cy - (d0[1] / m) * r * 0.6
        grad = QRadialGradient(hx, hy, r)
        grad.setColorAt(0.0, QColor(255, 255, 255))
        grad.setColorAt(0.25, QColor(215, 225, 240))
        grad.setColorAt(0.7, QColor(120, 140, 170))
        grad.setColorAt(1.0, QColor(55, 70, 95))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        p.drawEllipse(QPointF(cx, cy), r, r)
        # 光点：光方向在视图平面的投影
        dirs = getattr(self.glw, "_light_dirs", None) or []
        count = getattr(self.glw, "_light_count", 0)
        for i in range(min(count, len(dirs))):
            px, py = self._light_pos(dirs[i])
            col = QColor(255, 220, 60) if i == 0 else QColor(255, 150, 60)
            p.setPen(QPen(QColor(255, 255, 255), 1.5))
            p.setBrush(QBrush(col))
            p.drawEllipse(QPointF(px, py), 7.0, 7.0)
            p.setPen(QPen(QColor(20, 30, 45), 1.0))
            p.drawText(int(px - 8), int(py - 11), str(i + 1))
        p.end()


class LightControlDialog(QDialog):
    """光源控制面板：左侧球体实时预览光点，右侧数量/方向/光晕滑块。"""

    def __init__(self, glw, parent=None):
        super().__init__(parent)
        self.glw = glw
        self.setWindowTitle("光源控制")
        self.setMinimumWidth(430)
        lay = QHBoxLayout(self)
        self.sphere = LightSphereWidget(glw)
        self.sphere.dirsChanged.connect(self._on_sphere_dirs_changed)
        lay.addWidget(self.sphere)
        right = QVBoxLayout()
        right.setSpacing(4)

        right.addWidget(QLabel("光源数量:"))
        self.sl_cnt = QSlider(Qt.Horizontal)
        self.sl_cnt.setRange(1, 4)
        self.sl_cnt.valueChanged.connect(self._apply)
        right.addWidget(self.sl_cnt)
        self._cnt_lbl = QLabel("3")
        right.addWidget(self._cnt_lbl)

        right.addWidget(QLabel("方位角:"))
        self.sl_az = QSlider(Qt.Horizontal)
        self.sl_az.setRange(-180, 180)
        self.sl_az.valueChanged.connect(self._apply)
        right.addWidget(self.sl_az)

        right.addWidget(QLabel("俯仰角:"))
        self.sl_el = QSlider(Qt.Horizontal)
        self.sl_el.setRange(-90, 90)
        self.sl_el.valueChanged.connect(self._apply)
        right.addWidget(self.sl_el)

        right.addWidget(QLabel("光晕(整体):"))
        self.sl_glow = QSlider(Qt.Horizontal)
        self.sl_glow.setRange(10, 300)          # 0.1 .. 3.0
        self.sl_glow.valueChanged.connect(self._apply)
        right.addWidget(self.sl_glow)
        self._glow_lbl = QLabel("1.00")
        right.addWidget(self._glow_lbl)

        # 每盏灯独立光晕（仅显示当前生效的灯；数量改变时自动显隐）
        right.addWidget(QLabel("各灯光晕:"))
        glow_grid = QGridLayout()
        glow_grid.setContentsMargins(0, 0, 0, 0)
        glow_grid.setSpacing(4)
        self._glow_i_lbls, self._glow_i_sliders, self._glow_i_vals = [], [], []
        for i in range(4):
            lbl = QLabel("灯%d" % (i + 1))
            lbl.setAlignment(Qt.AlignHCenter)
            glow_grid.addWidget(lbl, 0, i)
            sl = QSlider(Qt.Horizontal)
            sl.setRange(10, 300)                # 0.1 .. 3.0
            sl.setMinimumWidth(52)
            sl.valueChanged.connect(self._apply)
            glow_grid.addWidget(sl, 1, i)
            v = QLabel("1.00")
            v.setAlignment(Qt.AlignHCenter)
            glow_grid.addWidget(v, 2, i)
            self._glow_i_lbls.append(lbl)
            self._glow_i_sliders.append(sl)
            self._glow_i_vals.append(v)
        right.addLayout(glow_grid)

        btns = QHBoxLayout()
        b_reset = QPushButton("重置")
        b_reset.clicked.connect(self._reset)
        b_save = QPushButton("保存设置…")
        b_save.setToolTip("把当前光源设置（数量/方向/光晕）保存为 JSON 文件")
        b_save.clicked.connect(self._save)
        b_load = QPushButton("载入设置…")
        b_load.setToolTip("从 JSON 文件载入光源设置并应用")
        b_load.clicked.connect(self._load)
        b_close = QPushButton("关闭")
        b_close.clicked.connect(self.accept)
        btns.addWidget(b_reset)
        btns.addWidget(b_save)
        btns.addWidget(b_load)
        btns.addStretch(1)
        btns.addWidget(b_close)
        right.addLayout(btns)
        lay.addLayout(right, 1)
        self.sync_from_glw()

    def _save(self):
        """保存光源设置（数量/方向/每灯光晕）到 JSON。"""
        if self.glw is None:
            return
        p, _ = save_file(self, "保存光源设置", "light_style.json",
                         "JSON (*.json)")
        if not p:
            return
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump({
                    "light_count": self.glw._light_count,
                    "light_dirs": [list(d) for d in self.glw._light_dirs],
                    "light_glow": self.glw._light_glow,
                    "light_glows": list(self.glw._light_glows),
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))

    def _load(self):
        """从 JSON 载入光源设置并应用（只动光源，不动光照模式/配色）。"""
        if self.glw is None:
            return
        p, _ = open_file(self, "载入光源设置", "", "JSON (*.json)")
        if not p:
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                st = json.load(f)
            if "light_count" in st:
                self.glw.set_light_count(int(st["light_count"]))
            if st.get("light_dirs"):
                self.glw._light_default_dirs = [
                    tuple(float(x) for x in d[:3]) for d in st["light_dirs"][:4]]
                while len(self.glw._light_default_dirs) < 4:
                    self.glw._light_default_dirs.append((0.0, 0.0, 1.0))
                self.glw._light_dirs = [list(x) for x in self.glw._light_default_dirs]
                self.glw._light_az = 0.0
                self.glw._light_el = 0.0
            if "light_glow" in st:
                self.glw.set_light_glow(float(st["light_glow"]))
            if st.get("light_glows"):
                for i, g in enumerate(st["light_glows"][:4]):
                    self.glw.set_light_glow_i(i, g)
            self.glw.update()
            self.sync_from_glw()
        except Exception as e:
            QMessageBox.warning(self, "载入失败", str(e))

    def sync_from_glw(self):
        """从画布当前光源状态同步滑块与球体预览。"""
        if self.glw is None:
            return
        self.sl_cnt.blockSignals(True)
        self.sl_cnt.setValue(getattr(self.glw, "_light_count", 3))
        self.sl_cnt.blockSignals(False)
        self._cnt_lbl.setText(str(getattr(self.glw, "_light_count", 3)))
        self.sl_az.blockSignals(True)
        self.sl_az.setValue(int(getattr(self.glw, "_light_az", 0)))
        self.sl_az.blockSignals(False)
        self.sl_el.blockSignals(True)
        self.sl_el.setValue(int(getattr(self.glw, "_light_el", 0)))
        self.sl_el.blockSignals(False)
        self.sl_glow.blockSignals(True)
        self.sl_glow.setValue(int(getattr(self.glw, "_light_glow", 1.0) * 100))
        self.sl_glow.blockSignals(False)
        self._glow_lbl.setText(f"{getattr(self.glw, '_light_glow', 1.0):.2f}")
        glows = list(getattr(self.glw, "_light_glows", None) or [1.0] * 4)
        while len(glows) < 4:
            glows.append(1.0)
        for i in range(4):
            self._glow_i_sliders[i].blockSignals(True)
            self._glow_i_sliders[i].setValue(int(glows[i] * 100))
            self._glow_i_sliders[i].blockSignals(False)
            self._glow_i_vals[i].setText(f"{glows[i]:.2f}")
        self._sync_glow_visibility()
        self.sphere.update()

    def _sync_glow_visibility(self):
        """按当前灯数显示/隐藏各灯光晕滑块。"""
        cnt = self.sl_cnt.value()
        for i in range(4):
            vis = i < cnt
            self._glow_i_lbls[i].setVisible(vis)
            self._glow_i_sliders[i].setVisible(vis)
            self._glow_i_vals[i].setVisible(vis)

    def _apply(self):
        if self.glw is None:
            return
        self.glw.set_light_count(self.sl_cnt.value())
        self._cnt_lbl.setText(str(self.sl_cnt.value()))
        self.glw.adjust_light_azimuth(self.sl_az.value())
        self.glw.adjust_light_elevation(self.sl_el.value())
        if self.sender() is self.sl_glow:
            # 整体光晕 → 全部灯统一
            glow = self.sl_glow.value() / 100.0
            self.glw.set_light_glow(glow)
            self._glow_lbl.setText(f"{glow:.2f}")
            for i in range(4):
                self._glow_i_sliders[i].blockSignals(True)
                self._glow_i_sliders[i].setValue(int(glow * 100))
                self._glow_i_sliders[i].blockSignals(False)
                self._glow_i_vals[i].setText(f"{glow:.2f}")
        elif self.sender() in self._glow_i_sliders:
            # 各灯独立光晕（仅由某盏灯自己的滑块触发；数量/方位/俯仰滑块
            # 变化不应重写每灯光晕）
            n = max(1, min(4, self.sl_cnt.value()))
            vals = []
            for i in range(4):
                v = self._glow_i_sliders[i].value() / 100.0
                self.glw.set_light_glow_i(i, v)
                self._glow_i_vals[i].setText(f"{v:.2f}")
                if i < n:
                    vals.append(v)
            # 仅统计当前生效的灯（灯数之外隐藏的滑块不参与联动判定）
            if vals and len(set(round(x, 2) for x in vals)) == 1:
                self.sl_glow.blockSignals(True)
                self.sl_glow.setValue(int(vals[0] * 100))
                self.sl_glow.blockSignals(False)
                self._glow_lbl.setText(f"{vals[0]:.2f}")
        self._sync_glow_visibility()
        self.sphere.update()

    def _on_sphere_dirs_changed(self):
        """手动拖拽摆放光点后：方位/俯仰滑块归零（手动摆放优先于整体旋转）。"""
        self.sl_az.blockSignals(True)
        self.sl_az.setValue(0)
        self.sl_az.blockSignals(False)
        self.sl_el.blockSignals(True)
        self.sl_el.setValue(0)
        self.sl_el.blockSignals(False)

    def _reset(self):
        if self.glw is not None:
            self.glw.reset_light_config()
        self.sync_from_glw()


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

/* 参数区里的分组框收紧内边距，避免左侧面板太挤
   （标题已移到折叠按钮，margin-top 保持小值避免留空） */
QFrame#CubParams QGroupBox {
    margin-top: 6px;
    padding: 10px 10px 8px 10px;
}

/* 一键样式行：画布正下方常驻，白底 + 上下细分隔线 */
QWidget#CubStyleBar {
    background-color: #FFFFFF;
    border-top: 1px solid #CBD5E1;
    border-bottom: 1px solid #CBD5E1;
}

QWidget#CubStyleBar QLabel {
    color: #4A5568;
    font-size: 9pt;
    padding: 0px 2px;
}

QWidget#CubStyleBar QPushButton {
    padding: 5px 12px;
    font-size: 9pt;
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

        # 一键样式：画布正下方常驻一行（sob-art / IBOVIEW / HoukMol）
        root.addWidget(self._build_style_bar())

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
        # 风格/分子/光泽/重置视角已移到画布下方参数区「显示」组（_build_params）。

        h.addStretch()
        self._more_btn = QToolButton()
        self._more_btn.setText("参数 ▴")
        self._more_btn.setCheckable(True)
        self._more_btn.setChecked(True)
        self._more_btn.setToolTip("展开等值面 / 显示 / 球棍 / 导出参数")
        self._more_btn.toggled.connect(self._on_toggle_params)
        h.addWidget(self._more_btn)

        return bar

    def _build_style_bar(self):
        """一键样式行：画布正下方常驻（sob-art / IBOVIEW / HoukMol / IQmol）
        + 分子显示辅助（隐藏氢 / 保留 H 编号 / 原子标签）。"""
        bar = QWidget()
        bar.setObjectName("CubStyleBar")
        v = QVBoxLayout(bar)
        v.setContentsMargins(8, 2, 8, 2)
        v.setSpacing(4)

        h = QHBoxLayout()
        h.setSpacing(6)
        h.addWidget(QLabel("一键样式:"))
        self._style_sob_btn = QPushButton("sob-art")
        self._style_sob_btn.setObjectName("SmallBtn")
        self._style_sob_btn.setToolTip("一键应用默认样式 sob-art（含手动摆放的光源方向）")
        self._style_sob_btn.clicked.connect(self._apply_sobart_style)
        h.addWidget(self._style_sob_btn)
        self._style_ibo_btn = QPushButton("IBOview")
        self._style_ibo_btn.setObjectName("SmallBtn")
        self._style_ibo_btn.setToolTip("一键回到默认 IboView 观感（CPK/三光/白底，等值面配色 ultra-glass）")
        self._style_ibo_btn.clicked.connect(self._apply_iboview_style)
        h.addWidget(self._style_ibo_btn)
        self._style_hm_btn = QPushButton("HoukMol")
        self._style_hm_btn.setObjectName("SmallBtn")
        self._style_hm_btn.setToolTip("一键应用默认样式 HoukMol（单光渐变 + 十字圆环）")
        self._style_hm_btn.clicked.connect(self._apply_houkmol_style)
        h.addWidget(self._style_hm_btn)
        self._style_iq_btn = QPushButton("IQmol")
        self._style_iq_btn.setObjectName("SmallBtn")
        self._style_iq_btn.setToolTip("一键应用默认样式 IQmol（CPK 双光 + 每灯独立光晕 + 红蓝相位）")
        self._style_iq_btn.clicked.connect(self._apply_iqmol_style)
        h.addWidget(self._style_iq_btn)
        h.addStretch()
        v.addLayout(h)

        # ── 分子显示辅助行 ──
        h2 = QHBoxLayout()
        h2.setSpacing(6)
        self._hide_h_chk = QCheckBox("隐藏氢原子")
        self._hide_h_chk.setToolTip("隐藏所有氢原子（球体/键/标签均不显示）")
        self._hide_h_chk.toggled.connect(self._on_hide_hydrogens)
        h2.addWidget(self._hide_h_chk)

        h2.addWidget(QLabel("保留H编号:"))
        self._keep_h_edit = QLineEdit("")
        self._keep_h_edit.setPlaceholderText("如 1,3,5-8")
        self._keep_h_edit.setMaximumWidth(90)
        self._keep_h_edit.setToolTip("隐藏氢时仍显示的 H 原子编号（1-based，逗号/连字符范围）")
        self._keep_h_edit.editingFinished.connect(self._on_keep_h_edited)
        h2.addWidget(self._keep_h_edit)

        self._lbl_idx_chk = QCheckBox("显示原子编号")
        self._lbl_idx_chk.setToolTip("在每个原子旁显示分子内编号（1, 2, 3 …）")
        self._lbl_idx_chk.toggled.connect(self._on_atom_label_idx)
        h2.addWidget(self._lbl_idx_chk)

        self._lbl_sym_chk = QCheckBox("显示元素符号")
        self._lbl_sym_chk.setToolTip("在每个原子旁显示元素符号（H, C, N, O …）")
        self._lbl_sym_chk.toggled.connect(self._on_atom_label_sym)
        h2.addWidget(self._lbl_sym_chk)
        h2.addStretch()
        v.addLayout(h2)

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

        # 显示 / 等值面（原「显示」与「等值面」两组合并为一组；标题移到折叠按钮）
        gi = QGroupBox("")
        il = QGridLayout(gi)
        il.setContentsMargins(8, 6, 8, 6)
        il.setSpacing(4)
        # 让滑块所在列（第1列）横向拉伸，使等值面大小/透明度滑块更长
        il.setColumnStretch(1, 1)

        # ── 显示：风格 / 分子 / 光泽 / 重置视角 ──
        il.addWidget(QLabel("风格:"), 0, 0)
        self._style_cb = _LimitedStyleCombo(max_popup_height=220)
        self._style_cb.addItems(STYLE_DISPLAY)
        self._style_cb.setMinimumWidth(170)
        il.addWidget(self._style_cb, 0, 1)

        # 光照 / 渲染效果（轴二，与「原子配色」轴正交）
        il.addWidget(QLabel("光照:"), 0, 2)
        self._light_cb = _LimitedStyleCombo(max_popup_height=220)
        self._light_cb.addItems([name for name, _ in _LIGHTING_OPTIONS])
        self._light_cb.setMinimumWidth(140)
        self._light_cb.setToolTip(
            "光照/渲染效果（独立于原子配色）：IboView 三光 / MolViewer 单光 / 双光 / 四光")
        il.addWidget(self._light_cb, 0, 3, 1, 3)

        il.addWidget(QLabel("原子配色:"), 1, 0)
        self._mol_style_cb = _LimitedStyleCombo(max_popup_height=200)
        self._mol_style_cb.addItems(MOL_STYLE_DISPLAY)
        self._mol_style_cb.setMinimumWidth(120)
        self._mol_style_cb.setToolTip("原子按元素配色方案（独立于光照），只改颜色不改材质")
        il.addWidget(self._mol_style_cb, 1, 1)

        il.addWidget(QLabel("光泽:"), 2, 0)
        self._shiny_cb = QComboBox()
        self._shiny_cb.addItems(list(SHININESS_PRESETS.keys()))
        self._shiny_cb.setMinimumWidth(120)
        self._shiny_cb.setCurrentText(SHININESS_DEFAULT)
        self._shiny_cb.setToolTip("IboView 光泽预设：调节原子与等值面的 Phong 高光")
        il.addWidget(self._shiny_cb, 2, 1)

        il.addWidget(QLabel("选中标记:"), 2, 2)
        self._sel_marker_cb = QComboBox()
        self._sel_marker_cb.addItems(["二十面体", "透明球", "圆环", "光晕"])
        self._sel_marker_cb.setMaximumWidth(100)
        self._sel_marker_cb.setToolTip("选中原子时的标记形状：二十面体 / 透明球 / 圆环 / 光晕")
        il.addWidget(self._sel_marker_cb, 2, 3)

        il.addWidget(QLabel("呼吸:"), 2, 4)
        self._sel_pulse_chk = QCheckBox()
        self._sel_pulse_chk.setToolTip("选中标记半径 ±12% 正弦呼吸动画")
        self._sel_pulse_chk.toggled.connect(self._on_sel_pulse)
        il.addWidget(self._sel_pulse_chk, 2, 5)

        self._btn_reset_view = QPushButton("重置视角")
        self._btn_reset_view.setObjectName("SmallBtn")
        self._btn_reset_view.setToolTip("重置相机视角（居中并铺满分子/等值面）")
        self._btn_reset_view.clicked.connect(self._reset_view)
        il.addWidget(self._btn_reset_view, 3, 0, 1, 2)

        # 先创建全部控件再连接信号，避免初始化 addItems 触发回调时
        # 访问尚未创建的控件（如 _on_style 会读取 _mol_style_cb）
        self._style_cb.currentIndexChanged.connect(self._on_style)
        self._light_cb.currentIndexChanged.connect(self._on_lighting)
        self._mol_style_cb.currentIndexChanged.connect(self._on_mol_style)
        self._shiny_cb.currentIndexChanged.connect(self._on_shiny)
        self._sel_marker_cb.currentIndexChanged.connect(self._on_sel_marker)
        # 初始应用一次默认（ultra-glass / IboView 三光 / CPK / reasonably shiny）
        self._on_style(self._style_cb.currentIndex())
        self._on_lighting(self._light_cb.currentIndex())
        self._on_mol_style(self._mol_style_cb.currentIndex())
        self._on_shiny(self._shiny_cb.currentIndex())
        self._on_sel_marker(self._sel_marker_cb.currentIndex())

        self._rel_chk = QCheckBox(
            f"IboView 相对阈值 ({IBOVIEW_DEFAULTS['IsoThreshold']:.0f}%)")
        self._rel_chk.setToolTip(
            "勾选后按 IboView IsoThreshold 语义取等值面：\n"
            "选取使 |data| 累积权重达到指定百分比的等值面。\n"
            "取消勾选则使用下方的绝对 isovalue（cube 文件原始单位）。")
        self._rel_chk.toggled.connect(self._on_rel_mode)
        il.addWidget(self._rel_chk, 4, 0, 1, 3)

        il.addWidget(QLabel("百分比:"), 5, 0)
        self._rel_sld = QSlider(Qt.Horizontal)
        self._rel_sld.setRange(50, 99)
        self._rel_sld.setValue(int(IBOVIEW_DEFAULTS['IsoThreshold']))
        self._rel_sld.setEnabled(False)
        self._rel_sld.valueChanged.connect(self._on_rel_slider)
        il.addWidget(self._rel_sld, 5, 1)
        self._rel_lbl = QLabel(f"{IBOVIEW_DEFAULTS['IsoThreshold']:.0f}%")
        self._rel_lbl.setMinimumWidth(44)
        il.addWidget(self._rel_lbl, 5, 2)

        # 隐藏相对阈值相关控件（用户不需要；仍保留逻辑，默认未勾选）
        self._rel_chk.hide()
        self._rel_lbl.hide()  # 第5行“百分比:”标签
        _rel_pct_lbl = il.itemAtPosition(5, 0)
        if _rel_pct_lbl is not None:
            _rel_pct_lbl.widget().hide()
        self._rel_sld.hide()

        il.addWidget(QLabel("等值面大小:"), 6, 0)
        self._iso_sld = QSlider(Qt.Horizontal)
        self._iso_sld.setRange(5, 2000)         # iso = 值/1000（0.005..2.0，含 IRI 的 1.0，与校验器下限一致）
        self._iso_sld.setValue(50)
        self._iso_sld.setMinimumWidth(200)
        self._iso_sld.valueChanged.connect(self._on_iso_slider)
        il.addWidget(self._iso_sld, 6, 1)
        self._iso_edit = QLineEdit("0.050")
        self._iso_edit.setValidator(QDoubleValidator(0.005, 2.0, 4))
        self._iso_edit.setMaximumWidth(64)
        self._iso_edit.editingFinished.connect(self._on_iso_edit)
        il.addWidget(self._iso_edit, 6, 2)

        il.addWidget(QLabel("透明度:"), 7, 0)
        self._op_sld = QSlider(Qt.Horizontal)
        self._op_sld.setRange(0, 100)
        # 滑块值直接表示“透明度(%)”，与 opacity 互补：opacity = 1 - 值/100
        self._op_sld.setValue(int((1.0 - IBOVIEW_DEFAULTS['OrbitalOpacity']) * 100))
        self._op_sld.setMinimumWidth(200)
        self._op_sld.valueChanged.connect(self._on_op)
        il.addWidget(self._op_sld, 7, 1)
        self._op_lbl = QLabel("20%")
        self._op_lbl.setMinimumWidth(40)
        il.addWidget(self._op_lbl, 7, 2)

        self._dp_chk = QCheckBox("Depth peeling")
        self._dp_chk.setChecked(True)
        self._dp_chk.setToolTip(
            "深度剥离：逐像素按深度分层渲染透明等值面（顺序正确）；"
            "关闭后回退到按 chunk 排序的 alpha 混合（无层数限制但有破洞风险）")
        self._dp_chk.toggled.connect(self._on_dp_toggle)
        self._dp_layers_spin = QSpinBox()
        self._dp_layers_spin.setRange(0, 8)
        self._dp_layers_spin.setValue(int(IBOVIEW_DEFAULTS['DepthPeelingLayers']))
        self._dp_layers_spin.setSuffix(" 层")
        self._dp_layers_spin.setToolTip(
            "深度剥离层数：0 = 关闭；层数越多，复杂轨道（折叠/交叠的等值面）"
            "显示越完整，代价是每层多一遍渲染、速度变慢")
        self._dp_layers_spin.valueChanged.connect(self._on_dp_layers)

        # Depth peeling 与 网格精度 放同一行（HBox 统一间距）
        dp_row = QWidget()
        dpl = QHBoxLayout(dp_row)
        dpl.setContentsMargins(0, 0, 0, 0)
        dpl.setSpacing(8)
        dpl.addWidget(self._dp_chk)
        dpl.addWidget(self._dp_layers_spin)
        dpl.addStretch(1)
        dpl.addWidget(QLabel("网格精度:"))
        self._grid_quality_cb = QComboBox()
        self._grid_quality_cb.addItems(["低 (1)", "中 (2)", "高 (3)"])
        self._grid_quality_cb.setCurrentIndex(1)
        self._grid_quality_cb.setToolTip("生成轨道 cube 的网格密度：1=稀疏，2=中等，3=精细")
        self._grid_quality_cb.setMaximumWidth(110)
        dpl.addWidget(self._grid_quality_cb)
        il.addWidget(dp_row, 8, 0, 1, 3)

        # 等值面剪影描边（独立开关 + 粗细滑块；MolViewer 带 rim 的预设会自动勾选）
        outline_row = QWidget()
        orl = QHBoxLayout(outline_row)
        orl.setContentsMargins(0, 0, 0, 0)
        orl.setSpacing(6)
        self._orb_outline_chk = QCheckBox("等值面描边")
        self._orb_outline_chk.setToolTip(
            "在等值面剪影边缘叠加细描边（颜色由 MolViewer 预设或默认深色决定）")
        self._orb_outline_chk.toggled.connect(self._on_orb_outline)
        orl.addWidget(self._orb_outline_chk)
        self._orb_outline_lbl = QLabel("粗细:")
        orl.addWidget(self._orb_outline_lbl)
        self._orb_outline_sld = QSlider(Qt.Horizontal)
        self._orb_outline_sld.setRange(1, 30)          # 0.01 .. 0.30 窄带阈值
        self._orb_outline_sld.setValue(8)              # 默认 0.08
        self._orb_outline_sld.setMaximumWidth(140)
        self._orb_outline_sld.valueChanged.connect(self._on_orb_outline_width)
        orl.addWidget(self._orb_outline_sld)
        self._orb_outline_val = QLabel("0.08")
        self._orb_outline_val.setMinimumWidth(34)
        orl.addWidget(self._orb_outline_val)
        # 描边颜色（默认黑色），按钮色块显示当前颜色
        self._orb_outline_color = (0.0, 0.0, 0.0)
        self._orb_outline_color_btn = QPushButton("颜色")
        self._orb_outline_color_btn.setObjectName("SmallBtn")
        self._orb_outline_color_btn.setMaximumWidth(56)
        self._orb_outline_color_btn.setToolTip("设置等值面描边颜色（默认黑色）")
        self._orb_outline_color_btn.clicked.connect(self._on_orb_outline_color)
        self._orb_outline_color_btn.setStyleSheet(
            "QPushButton { background-color: rgb(0,0,0); color: #ffffff;"
            " border: 1px solid #9AA7B8; border-radius: 3px; padding: 2px 6px; }")
        orl.addWidget(self._orb_outline_color_btn)
        orl.addStretch()
        il.addWidget(outline_row, 9, 0, 1, 3)

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

        il.addWidget(wheel_row, 10, 0, 1, 6)

        # 翻转相位：交换正/负相位颜色（IboView chkBox_FlipPhase 的等价实现）
        self._phase_flipped = False
        self._flip_phase_btn = QPushButton("翻转相位")
        self._flip_phase_btn.setObjectName("SmallBtn")
        self._flip_phase_btn.setToolTip("交换正/负相位颜色（等价 IboView 翻转相位，几何不变）")
        self._flip_phase_btn.clicked.connect(self._on_flip_phase)
        il.addWidget(self._flip_phase_btn, 11, 0, 1, 3)

        # 正/负相位色块选色：直接点击指定各相位颜色
        phase_row = QWidget()
        ppl = QHBoxLayout(phase_row)
        ppl.setContentsMargins(0, 0, 0, 0)
        ppl.setSpacing(6)
        ppl.addWidget(QLabel("正相位:"))
        self._phase_pos_btn = QPushButton("色块")
        self._phase_pos_btn.setObjectName("SmallBtn")
        self._phase_pos_btn.setToolTip("点击选择正相位等值面颜色")
        self._phase_pos_btn.clicked.connect(lambda: self._on_pick_phase_color("pos"))
        ppl.addWidget(self._phase_pos_btn)
        ppl.addSpacing(10)
        ppl.addWidget(QLabel("负相位:"))
        self._phase_neg_btn = QPushButton("色块")
        self._phase_neg_btn.setObjectName("SmallBtn")
        self._phase_neg_btn.setToolTip("点击选择负相位等值面颜色")
        self._phase_neg_btn.clicked.connect(lambda: self._on_pick_phase_color("neg"))
        ppl.addWidget(self._phase_neg_btn)
        ppl.addStretch()
        il.addWidget(phase_row, 12, 0, 1, 6)
        self._sync_phase_swatches()

        # 灯光手动微调（方位/俯仰；在 IboView Phong 模式即 vcube 预设下生效）
        light_row = QWidget()
        ll = QHBoxLayout(light_row)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(6)
        ll.addWidget(QLabel("灯光:"))
        self._light_btn = QPushButton("光源设置…")
        self._light_btn.setObjectName("SmallBtn")
        self._light_btn.setToolTip(
            "弹出光源控制面板：左侧球体实时预览光点，右侧调整数量/方向/光晕")
        self._light_btn.clicked.connect(self._open_light_dialog)
        ll.addWidget(self._light_btn)
        ll.addStretch()
        il.addWidget(light_row, 13, 0, 1, 6)

        # 样式保存 / 载入（一键样式 sob-art/IBOVIEW/HoukMol 已移至画布下方常驻行）
        style_io_row = QWidget()
        sio = QHBoxLayout(style_io_row)
        sio.setContentsMargins(0, 0, 0, 0)
        sio.setSpacing(6)
        sio.addWidget(QLabel("样式:"))
        self._style_save_btn = QPushButton("保存…")
        self._style_save_btn.setObjectName("SmallBtn")
        self._style_save_btn.setToolTip("把当前样式（配色/光照/描边/透明度/相位色等）保存为 JSON 文件")
        self._style_save_btn.clicked.connect(self._save_style)
        sio.addWidget(self._style_save_btn)
        self._style_load_btn = QPushButton("载入…")
        self._style_load_btn.setObjectName("SmallBtn")
        self._style_load_btn.setToolTip("从 JSON 文件载入样式并应用")
        self._style_load_btn.clicked.connect(self._load_style)
        sio.addWidget(self._style_load_btn)
        sio.addStretch()
        il.addWidget(style_io_row, 14, 0, 1, 6)

        # ── 折叠容器：按钮控制组展开/收起（默认收起） ──
        def _collapsible_col(title):
            col = QWidget()
            cl = QVBoxLayout(col)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(2)
            btn = QToolButton()
            btn.setText(f"▸ {title}")
            btn.setCheckable(True)
            btn.setChecked(False)
            btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                "QToolButton { border:none; color:#1565C0; font-weight:bold;"
                " text-align:left; padding:2px 4px; font-size:10pt; }"
                "QToolButton:hover { color:#0D47A1; }")
            cl.addWidget(btn)
            return col, btn, cl

        def _wire_toggle(btn, group, title):
            def _tog(on):
                group.setVisible(on)
                btn.setText(f"{'▾' if on else '▸'} {title}")
            btn.toggled.connect(_tog)

        col_iso, self._btn_toggle_iso, cl_iso = _collapsible_col("显示 / 等值面")
        cl_iso.addWidget(gi, 1)
        _wire_toggle(self._btn_toggle_iso, gi, "显示 / 等值面")
        gi.setVisible(False)   # 默认收起
        outer.addWidget(col_iso, stretch=1)

        # 球棍模型（标题移到折叠按钮）
        gb = QGroupBox("")
        bl = QGridLayout(gb)
        bl.setContentsMargins(8, 6, 8, 6)
        bl.setSpacing(4)
        # 与等值面组一致：滑块所在列（第1列）横向拉伸
        bl.setColumnStretch(1, 1)

        bl.addWidget(QLabel("原子半径:"), 0, 0)
        self._atom_scale_sld = QSlider(Qt.Horizontal)
        self._atom_scale_sld.setRange(20, 400)
        self._atom_scale_sld.setValue(168)
        self._atom_scale_sld.setMinimumWidth(200)
        self._atom_scale_sld.valueChanged.connect(self._on_atom_scale_sld)
        bl.addWidget(self._atom_scale_sld, 0, 1)
        self._atom_scale_edit = QLineEdit("1.68")
        self._atom_scale_edit.setValidator(QDoubleValidator(0.20, 4.00, 2))
        self._atom_scale_edit.setMaximumWidth(64)
        self._atom_scale_edit.editingFinished.connect(self._on_atom_scale_edit)
        bl.addWidget(self._atom_scale_edit, 0, 2)

        self._outline_color = (0.0, 0.0, 0.0)   # 默认黑边

        bl.addWidget(QLabel("化学键:"), 1, 0)
        self._bond_scale_sld = QSlider(Qt.Horizontal)
        self._bond_scale_sld.setRange(20, 400)
        self._bond_scale_sld.setValue(200)
        self._bond_scale_sld.setMinimumWidth(200)
        self._bond_scale_sld.valueChanged.connect(self._on_bond_scale_sld)
        bl.addWidget(self._bond_scale_sld, 1, 1)
        self._bond_scale_edit = QLineEdit("2.00")
        self._bond_scale_edit.setValidator(QDoubleValidator(0.20, 4.00, 2))
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

        # ── 原子十字圆环（两条贴球大圆带，GL 着色器绘制；主控开关 + 控制面板） ──
        bl.addWidget(QLabel("十字圆环:"), 4, 0)
        self._crosshair_chk = QCheckBox("显示")
        self._crosshair_chk.setChecked(False)
        self._crosshair_chk.setToolTip(
            "勾选后在每个原子球面画两条交叉的大圆环（十字效果）；"
            "未勾选则完全不显示")
        self._crosshair_chk.toggled.connect(self._on_crosshair)
        bl.addWidget(self._crosshair_chk, 4, 1)
        self._ring_btn = QPushButton("圆环设置…")
        self._ring_btn.setObjectName("SmallBtn")
        self._ring_btn.setMaximumWidth(90)
        self._ring_btn.setToolTip(
            "弹出圆环控制面板：调两条环的方位角/俯仰角；勾选锁定后分子怎么转圆环都不转")
        self._ring_btn.clicked.connect(self._open_ring_dialog)
        bl.addWidget(self._ring_btn, 4, 2)
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
        self._outline_w_sld.setValue(400)   # 0.4：细档（窄带公式下 ≈1px 细线）
        self._outline_w_sld.setMinimumWidth(200)
        self._outline_w_sld.valueChanged.connect(self._on_outline_width)
        bl.addWidget(self._outline_w_sld, 9, 1)
        self._outline_w_lbl = QLabel("0.400")
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

        # 景深雾化（IboView Fade：远处蒙白雾）
        self._fade_chk = QCheckBox("景深雾化")
        self._fade_chk.setChecked(True)
        self._fade_chk.setToolTip("关闭后远处原子/轨道不再因景深变淡发白")
        self._fade_chk.toggled.connect(self._on_fade_toggle)
        bl.addWidget(self._fade_chk, 13, 0, 1, 3)

        col_ball, self._btn_toggle_ball, cl_ball = _collapsible_col("球棍模型")
        cl_ball.addWidget(gb, 1)
        _wire_toggle(self._btn_toggle_ball, gb, "球棍模型")
        gb.setVisible(False)   # 默认收起
        outer.addWidget(col_ball, stretch=1)

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
            self._sync_phase_swatches()

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
        self._sync_phase_swatches()

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
        self._sync_phase_swatches()

    def _on_wheel_reset(self):
        """恢复当前样式默认配色（等价于取消色轮配色）。"""
        if not self._wheel_enabled or self.glw is None:
            return
        style_name = getattr(self.glw, "_style_name", None)
        if style_name:
            self.glw.set_style(style_name)  # 重新解析默认正/负相位色
        self._color_wheel.set_hue(0.33)
        self._sync_phase_swatches()

    # ── 正/负相位色块选色 ──
    @staticmethod
    def _style_swatch(btn, rgb01):
        """把按钮渲染成当前颜色色块（按亮度选文字黑/白）。rgb01 为 0..1 元组。"""
        r, g, b = (int(c * 255) for c in rgb01[:3])
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        btn.setStyleSheet(
            "QPushButton { background-color: rgb(%d,%d,%d); color: %s;"
            " border: 1px solid #9AA7B8; border-radius: 3px; padding: 2px 8px; }"
            % (r, g, b, "#ffffff" if lum < 128 else "#000000"))

    def _sync_phase_swatches(self):
        """把正/负相位色块按钮同步为 glw 当前相位配色。"""
        if not hasattr(self, "_phase_pos_btn") or self.glw is None:
            return
        self._style_swatch(self._phase_pos_btn, getattr(self.glw, "_pc", (0.1, 0.8, 0.1)))
        self._style_swatch(self._phase_neg_btn, getattr(self.glw, "_nc", (0.9, 0.25, 0.25)))

    def _on_pick_phase_color(self, which):
        """点击正/负相位色块选色（0-255），直接应用到等值面。"""
        if self.glw is None:
            return
        cur = self.glw._pc if which == "pos" else self.glw._nc
        col = QColorDialog.getColor(
            QColor(int(cur[0] * 255), int(cur[1] * 255), int(cur[2] * 255)),
            self, "正相位颜色" if which == "pos" else "负相位颜色")
        if not col.isValid():
            return
        rgb = (col.red(), col.green(), col.blue())   # 0-255
        if which == "pos":
            self.glw.set_phase_colors(pos_rgb=rgb)
        else:
            self.glw.set_phase_colors(neg_rgb=rgb)
        self._sync_phase_swatches()

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
        """载入 fchk/xyz 后把分子结构推到 GL 画布，使其立即显示球棍模型。
        载入文件后的初始样式默认用 HoukMol。"""
        if self.glw is not None:
            self.glw.set_molecule(atoms, bonds)
            if atoms:
                self._apply_houkmol_style()

    # ── 库便捷 API（桥接到内部 CubGLWidget，供外部直接调用） ──
    def load_cube_files(self, paths):
        """加载 .cub 文件列表（1 个=正负同色，2 个=[正,负] 分离配色）。"""
        self.set_cube_list(paths, auto_load=True)

    def set_iso(self, value):
        """设置等值面绝对阈值（a.u.）。"""
        self.set_isovalue(value)

    def get_iso(self):
        """返回当前等值面绝对阈值。"""
        if self.glw is not None:
            return self.glw._isovalue
        return None

    def set_positive_color(self, color):
        """设置正相位颜色，接受 '#rrggbb' 或 (r,g,b) 0-255。"""
        self._apply_phase(pos_rgb=_parse_color(color))

    def set_negative_color(self, color):
        """设置负相位颜色，接受 '#rrggbb' 或 (r,g,b) 0-255。"""
        self._apply_phase(neg_rgb=_parse_color(color))

    def set_transparency(self, value):
        """设置等值面透明度 value（0=不透明, 1=全透）。"""
        if self.glw is not None:
            self.glw.set_opacity(1.0 - float(value))

    def set_render_quality(self, level):
        """设置渲染质量: 'low' / 'medium' / 'high'。"""
        if self.glw is not None:
            self.glw.set_depth_peeling(level != "low")

    def set_mol_style_name(self, name):
        """设置分子风格（球棍 / 飘带 / 仅球 等），接受显示名或原名。"""
        self._set_mol_style_by_name(name)

    def set_shininess_name(self, name):
        """设置光泽预设名。"""
        self.set_shininess(name)

    def set_background_color(self, color):
        """设置背景颜色，接受 '#rrggbb' 或 (r,g,b) 0-255。"""
        if self.glw is not None:
            self.glw.set_background(_parse_color(color))

    def set_fade_enabled(self, enabled):
        """景深雾化（IboView Fade：远处蒙白雾）开关。默认开启以保留原貌。"""
        if self.glw is not None:
            self.glw.set_fade_enabled(bool(enabled))

    def reset_view(self):
        """重置相机视角。"""
        if self.glw is not None:
            self.glw.reset_view()

    def export_image(self, path, dpi=600.0):
        """离屏渲染导出图像。"""
        if self.glw is not None:
            return self.glw.export_image(path, dpi)
        return False

    def _apply_phase(self, pos_rgb=None, neg_rgb=None):
        """更新相位配色（pos/neg 可单独提供，未提供则沿用当前值）。"""
        if self.glw is None:
            return
        p = pos_rgb if pos_rgb is not None else self.glw._pc
        n = neg_rgb if neg_rgb is not None else self.glw._nc
        self.glw.set_phase_colors(pos_rgb=p, neg_rgb=n)

    def _set_mol_style_by_name(self, name):
        """按名称（显示名或原名）切换分子风格下拉框。"""
        idx = self._mol_style_cb.findText(name)
        if idx < 0:
            for i in range(self._mol_style_cb.count()):
                if self._mol_style_cb.itemText(i).split("—")[0].strip() == name:
                    idx = i
                    break
        if idx >= 0:
            self._mol_style_cb.setCurrentIndex(idx)

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
        p, _ = open_file(
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
            self._sync_phase_swatches()
            # 风格切换会重建 _sp（透明度等），同步透明度滑块/标签；
            # _build_params 早期会先触发一次 _on_style，此时控件未建全，
            # 用 hasattr 跳过（与 _sync_phase_swatches 的守卫一致）
            if hasattr(self, "_op_sld"):
                self._sync_style_ui()

    def _on_lighting(self, idx):
        """光照/渲染效果轴：只改 u_MvGrad（三光/单光/双光/四光），不碰配色/背景/描边。"""
        if self.glw is None or not (0 <= idx < len(_LIGHTING_OPTIONS)):
            return
        grad = _LIGHTING_OPTIONS[idx][1]
        self.glw.set_mv_gradient(grad)   # "" → IboView 三光

    def _on_mol_style(self, idx):
        """原子配色轴：只改原子元素配色方案，不触碰光照/材质/背景/描边。"""
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

    def _on_orb_outline(self, on):
        """等值面描边开关（保持当前描边颜色/宽度）。"""
        if self.glw is not None:
            self.glw.set_orb_outline(bool(on))

    def _on_crosshair(self, on):
        """原子十字圆环开关（主控：勾选显示，不勾不显示）。"""
        if self.glw is not None:
            self.glw.set_crosshair(bool(on))

    def _open_ring_dialog(self):
        """弹出十字圆环控制面板（方位/俯仰 + 锁定）。"""
        if self.glw is None:
            return
        if getattr(self, "_ring_dialog", None) is None:
            self._ring_dialog = RingControlDialog(self.glw, self)
        self._ring_dialog.show()
        self._ring_dialog.raise_()
        self._ring_dialog.activateWindow()

    def _open_light_dialog(self):
        """弹出光源控制面板（左侧球体预览 + 右侧数量/方向/光晕滑块）。"""
        if self.glw is None:
            return
        if getattr(self, "_light_dialog", None) is None:
            self._light_dialog = LightControlDialog(self.glw, self)
        self._light_dialog.sync_from_glw()
        self._light_dialog.show()
        self._light_dialog.raise_()
        self._light_dialog.activateWindow()

    # ── 样式保存 / 载入 ──
    def _apply_light_state(self, style):
        """应用样式字典中的光源部分（方向/数量/光晕），不影响光照模式。"""
        if self.glw is None:
            return
        if style.get("light_dirs"):
            self.glw._light_default_dirs = [
                tuple(float(x) for x in d[:3]) for d in style["light_dirs"][:4]]
            while len(self.glw._light_default_dirs) < 4:
                self.glw._light_default_dirs.append((0.0, 0.0, 1.0))
            self.glw._light_dirs = [list(x) for x in self.glw._light_default_dirs]
            # 方向整体替换后清掉旧偏移，避免光源对话框残留的方位/俯仰
            # 在用户微调时突然叠加生效（与 LightControlDialog._load 一致）
            self.glw._light_az = 0.0
            self.glw._light_el = 0.0
        if "light_count" in style:
            self.glw._light_count = max(1, min(4, int(style["light_count"])))
        if "light_glow" in style:
            self.glw.set_light_glow(float(style["light_glow"]))
        if style.get("light_glows"):
            for i, g in enumerate(style["light_glows"][:4]):
                self.glw.set_light_glow_i(i, g)
        self.glw.update()

    def _apply_sobart_style(self):
        """sob-art 默认：IBOVIEW 等值面绘制方法 + 等值面风格 sob-art +
        SobArt 原子配色 + 原子描边 0.35 + sob-art.json 光照。"""
        if self.glw is None:
            return
        self.glw.reset_molviewer_style()
        self.glw.set_style("sob-art")
        self.glw.set_mol_style("SobArt")
        self.glw.set_atom_scale(1.5)
        self.glw.set_atom_outline(True, (0.0, 0.0, 0.0), 0.35)
        self._apply_light_state(_SOBART_STYLE)
        self._sync_style_ui()
        self._set_status("已应用默认样式 sob-art")

    def _apply_iboview_style(self):
        """一键回到默认 IboView 观感：CPK / 三光 / 白底 / 无描边，
        等值面配色（相位色）用风格 ultra-glass。"""
        if self.glw is None:
            return
        self.glw.reset_molviewer_style()
        self.glw.set_style("ultra-glass")
        self.glw.set_atom_scale(1.5)
        self._sync_style_ui()
        self._set_status("已应用默认样式 IBOview")

    def _apply_iqmol_style(self):
        """IQmol 默认：IBOVIEW 等值面绘制方法 + 当前等值面风格 +
        相位色 #e2254f / #0062ff + 光照角度与 sob-art 一致。"""
        if self.glw is None:
            return
        self.glw.reset_molviewer_style()
        sn = getattr(self.glw, "_style_name", None)
        if sn:
            self.glw.set_style(sn)
        # 轨道相位颜色：#e2254f（正相位）/ #0062ff（负相位）
        self.glw.set_phase_colors(pos_rgb=(0xE2, 0x25, 0x4F),
                                  neg_rgb=(0x00, 0x62, 0xFF))
        self.glw.set_atom_scale(1.5)
        # 光照角度与 sob-art 一致
        self._apply_light_state(_SOBART_STYLE)
        self._sync_style_ui()
        self._set_status("已应用默认样式 IQmol")

    # ── 分子显示辅助：隐藏氢 / 保留编号 / 原子标签 ──

    def _parse_keep_h(self):
        """解析「保留H编号」输入框 → 1-based 序号集合。

        支持 "1,3,5-8" / "1 3 5-8" / "1;3" 等形式；非法输入返回空集。
        """
        txt = self._keep_h_edit.text().strip()
        if not txt:
            return set()
        out = set()
        for part in txt.replace(";", ",").replace(" ", ",").split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                try:
                    a, b = part.split("-", 1)
                    lo, hi = int(a), int(b)
                    if lo > hi:
                        lo, hi = hi, lo
                    out.update(range(lo, hi + 1))
                except ValueError:
                    continue
            else:
                try:
                    out.add(int(part))
                except ValueError:
                    continue
        return {x for x in out if x > 0}

    def _on_hide_hydrogens(self, on):
        if self.glw is not None:
            keep = self._parse_keep_h()
            self.glw.set_hide_hydrogens(bool(on), keep)

    def _on_keep_h_edited(self):
        if self.glw is not None and self._hide_h_chk.isChecked():
            keep = self._parse_keep_h()
            self.glw.set_hide_hydrogens(True, keep)
            self._set_status(f"保留 H 编号: {sorted(keep) or '无'}")

    def _on_atom_label_idx(self, on):
        if self.glw is None:
            return
        # 原子编号与元素符号互斥：开编号关符号，反之亦然
        if on:
            self._lbl_sym_chk.blockSignals(True)
            self._lbl_sym_chk.setChecked(False)
            self._lbl_sym_chk.blockSignals(False)
            self.glw.set_atom_labels(1)
        else:
            if not self._lbl_sym_chk.isChecked():
                self.glw.set_atom_labels(2)

    def _on_atom_label_sym(self, on):
        if self.glw is None:
            return
        if on:
            self._lbl_idx_chk.blockSignals(True)
            self._lbl_idx_chk.setChecked(False)
            self._lbl_idx_chk.blockSignals(False)
            self.glw.set_atom_labels(0)
        else:
            if not self._lbl_idx_chk.isChecked():
                self.glw.set_atom_labels(2)

    def _apply_houkmol_style(self):
        """一键应用默认样式 HoukMol（内嵌，单光渐变 + 默认圆环方位），
        等值面配色（相位色）用风格 mango-lime。"""
        if self.glw is None:
            return
        # 先定等值面风格（相位色取自 mango-lime），再套 HoukMol 材质/光照/
        # 透明度覆盖，避免 set_style 重建 _sp 时把 dict 里的 orb_opacity
        # 等字段静默冲掉。
        self.glw.set_style("mango-lime")
        st = dict(_HOUKMOL_STYLE)
        st.pop("phase_pos", None)   # 相位色保持 mango-lime，不覆盖
        st.pop("phase_neg", None)
        self.glw.apply_style_state(st)
        self.glw.set_atom_scale(1.5)
        self.glw.apply_ring_state(_HOUKMOL_RING)
        self._sync_style_ui()
        self._set_status("已应用默认样式 HoukMol")

    def _save_style(self):
        if self.glw is None:
            return
        p, _ = save_file(self, "保存样式", "gxnu_style.json",
                         "JSON (*.json)")
        if not p:
            return
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(self.glw.get_style_state(), f, ensure_ascii=False, indent=2)
            self._set_status(f"样式已保存: {os.path.basename(p)}")
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))

    def _load_style(self):
        if self.glw is None:
            return
        p, _ = open_file(self, "载入样式", "", "JSON (*.json)")
        if not p:
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                st = json.load(f)
            self.glw.apply_style_state(st)
            self._sync_style_ui()
            self._set_status(f"样式已载入: {os.path.basename(p)}")
        except Exception as e:
            QMessageBox.warning(self, "载入失败", str(e))

    def _sync_style_ui(self):
        """载入样式后把面板控件同步为当前画布状态。"""
        if self.glw is None:
            return
        # 光照下拉框
        gname = self.glw._mv_grad_name()
        for i, (name, grad) in enumerate(_LIGHTING_OPTIONS):
            if grad == gname:
                self._light_cb.blockSignals(True)
                self._light_cb.setCurrentIndex(i)
                self._light_cb.blockSignals(False)
                break
        # 原子配色
        if self.glw._mol_style in MOL_STYLE_NAMES:
            self._mol_style_cb.blockSignals(True)
            self._mol_style_cb.setCurrentIndex(MOL_STYLE_NAMES.index(self.glw._mol_style))
            self._mol_style_cb.blockSignals(False)
        # 光泽
        if self.glw._shininess in SHININESS_PRESETS:
            self._shiny_cb.blockSignals(True)
            self._shiny_cb.setCurrentIndex(list(SHININESS_PRESETS.keys()).index(self.glw._shininess))
            self._shiny_cb.blockSignals(False)
        # 原子/键 半径
        self._atom_scale_sld.blockSignals(True)
        self._atom_scale_sld.setValue(int(self.glw._atom_scale * 100))
        self._atom_scale_sld.blockSignals(False)
        self._atom_scale_edit.setText(f"{self.glw._atom_scale:.2f}")
        self._bond_scale_sld.blockSignals(True)
        self._bond_scale_sld.setValue(int(self.glw._bond_scale * 100))
        self._bond_scale_sld.blockSignals(False)
        self._bond_scale_edit.setText(f"{self.glw._bond_scale:.2f}")
        # 原子描边
        self._outline_chk.blockSignals(True)
        self._outline_chk.setChecked(bool(self.glw._atom_outline))
        self._outline_chk.blockSignals(False)
        self._outline_w_sld.blockSignals(True)
        self._outline_w_sld.setValue(int(self.glw._atom_outline_width * 1000))
        self._outline_w_sld.blockSignals(False)
        self._outline_w_lbl.setText(f"{self.glw._atom_outline_width:.3f}")
        # 等值面描边 + 透明度
        self._orb_outline_chk.blockSignals(True)
        self._orb_outline_chk.setChecked(bool(self.glw._orb_outline))
        self._orb_outline_chk.blockSignals(False)
        self._orb_outline_sld.blockSignals(True)
        self._orb_outline_sld.setValue(int(self.glw._orb_outline_width * 100))
        self._orb_outline_sld.blockSignals(False)
        self._orb_outline_val.setText(f"{self.glw._orb_outline_width:.2f}")
        op = self.glw._sp.get('opacity', 1.0)
        self._op_sld.blockSignals(True)
        self._op_sld.setValue(int((1.0 - op) * 100))
        self._op_sld.blockSignals(False)
        self._op_lbl.setText(f"{(1.0 - op) * 100:.0f}%")
        # 十字圆环 + 相位色
        self._crosshair_chk.blockSignals(True)
        self._crosshair_chk.setChecked(bool(self.glw._crosshair))
        self._crosshair_chk.blockSignals(False)
        self._sync_phase_swatches()
        # Depth peeling：复选框 + 层数
        dp = getattr(self.glw, "_dp_layers", 0)
        self._dp_chk.blockSignals(True)
        self._dp_chk.setChecked(dp > 0)
        self._dp_chk.blockSignals(False)
        if dp > 0:
            self._dp_layers_spin.blockSignals(True)
            self._dp_layers_spin.setValue(dp)
            self._dp_layers_spin.blockSignals(False)
        self._dp_layers_spin.setEnabled(dp > 0)
        # 分子显示辅助：隐藏氢 / 保留 H 编号 / 原子标签
        if hasattr(self, "_hide_h_chk"):
            hid = bool(getattr(self.glw, "_hide_hydrogens", False))
            self._hide_h_chk.blockSignals(True)
            self._hide_h_chk.setChecked(hid)
            self._hide_h_chk.blockSignals(False)
            keep = getattr(self.glw, "_keep_h_atoms", set())
            self._keep_h_edit.blockSignals(True)
            self._keep_h_edit.setText(",".join(str(x) for x in sorted(keep)))
            self._keep_h_edit.blockSignals(False)
            mode = int(getattr(self.glw, "_atom_labels", 2))
            self._lbl_idx_chk.blockSignals(True)
            self._lbl_idx_chk.setChecked(mode == 1)
            self._lbl_idx_chk.blockSignals(False)
            self._lbl_sym_chk.blockSignals(True)
            self._lbl_sym_chk.setChecked(mode == 0)
            self._lbl_sym_chk.blockSignals(False)
        if getattr(self, "_light_dialog", None) is not None:
            self._light_dialog.sync_from_glw()
        if getattr(self, "_ring_dialog", None) is not None:
            self._ring_dialog.sync_from_glw()

    def _on_orb_outline_width(self, v):
        """等值面描边粗细（窄带阈值 0.01..0.30；未勾选时也记住宽度）。"""
        w = v / 100.0
        self._orb_outline_val.setText(f"{w:.2f}")
        if self.glw is not None:
            self.glw.set_orb_outline(self._orb_outline_chk.isChecked(), width=w)

    def _on_orb_outline_color(self):
        """等值面描边颜色（默认黑色）。"""
        cur = self._orb_outline_color
        col = QColorDialog.getColor(QColor(int(cur[0] * 255), int(cur[1] * 255),
                                           int(cur[2] * 255)), self, "等值面描边颜色")
        if not col.isValid():
            return
        self._orb_outline_color = (col.redF(), col.greenF(), col.blueF())
        if self.glw is not None:
            self.glw.set_orb_outline(self._orb_outline_chk.isChecked(),
                                     color=self._orb_outline_color)
        self._apply_orb_outline_swatch()

    def _apply_orb_outline_swatch(self):
        """把按钮色块更新为当前描边颜色（按亮度选文字黑/白）。"""
        r, g, b = self._orb_outline_color
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        self._orb_outline_color_btn.setStyleSheet(
            "QPushButton { background-color: rgb(%d,%d,%d); color: %s;"
            " border: 1px solid #9AA7B8; border-radius: 3px; padding: 2px 6px; }"
            % (int(r * 255), int(g * 255), int(b * 255),
               "#ffffff" if lum < 0.5 else "#000000"))

    def _on_sel_marker(self, idx):
        if self.glw is None:
            return
        name = ["icosahedron", "sphere", "torus", "glow"][idx] if 0 <= idx < 4 \
            else "icosahedron"
        self.glw.set_selection_marker_shape(name)

    def _on_sel_pulse(self, on):
        if self.glw is not None:
            self.glw.set_selection_marker_pulse(bool(on))

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
            layers = self._dp_layers_spin.value()
            if on and layers <= 0:
                # 勾选时 spin 仍为 0（“关闭”占位）→ 落到引擎默认层数，
                # 并回填 spin，避免“显示 0 层、实际默认 4 层”的不一致。
                layers = int(IBOVIEW_DEFAULTS['DepthPeelingLayers'])
                self._dp_layers_spin.blockSignals(True)
                self._dp_layers_spin.setValue(layers)
                self._dp_layers_spin.blockSignals(False)
            self.glw.set_depth_peeling(bool(on), layers if layers > 0 else None)
            self._dp_layers_spin.setEnabled(bool(on))

    def _on_dp_layers(self, value):
        if self.glw is None:
            return
        if value <= 0:
            # 层数设为 0 = 关闭
            self.glw.set_depth_peeling(False)
            self._dp_chk.blockSignals(True)
            self._dp_chk.setChecked(False)
            self._dp_chk.blockSignals(False)
            self._dp_layers_spin.setEnabled(False)
        else:
            self.glw.set_depth_peeling(True, value)
            self._dp_chk.blockSignals(True)
            self._dp_chk.setChecked(True)
            self._dp_chk.blockSignals(False)
            self._dp_layers_spin.setEnabled(True)

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
        self._op_lbl.setText(f"{v}%")
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

    # ── 景深雾化（IboView Fade）回调 ──
    def _on_fade_toggle(self, on):
        if self.glw is not None:
            self.glw.set_fade_enabled(bool(on))

    def _on_outline_width(self, v):
        w = v / 1000.0
        self._outline_w_lbl.setText(f"{w:.3f}")
        if self.glw is not None:
            self.glw.set_atom_outline(self._outline_chk.isChecked(), width=w)

    def _screenshot(self):
        if self.glw is None:
            return
        base = os.path.splitext(os.path.basename(self._loaded_path or "cub_view"))[0]
        p, _ = save_file(self, "保存截图", base + ".png", "PNG (*.png)")
        if p:
            self.glw.screenshot(p)

    def _export_image(self):
        if self.glw is None:
            return
        if self._loaded_path is None:
            QMessageBox.information(self, "提示", "请先加载一个 cube 文件。")
            return
        base = os.path.splitext(os.path.basename(self._loaded_path))[0]
        p, _ = save_file(self, "导出高分辨率图片",
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
