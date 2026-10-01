# -*- coding: utf-8 -*-
"""
cub_stack_panel.py — 多 CUB 叠加可视化面板（GXNU MolStudio 的一个 tab）

载入多个 Gaussian .cub 文件，在**同一个分子结构**上叠加显示各自的等值面；
每个等值面可独立设置正 / 负相位颜色与相位翻转。

设计约定（已与用户确认）：
  · **分子结构取自第一个启用的 cub** 自带的原子坐标
    —— 多个 cub 应为同一体系的不同性质（不同 MO、自旋密度、密度差等）
  · **等值（isovalue）与不透明度为全局共用**
    —— 渲染管线用 `merge_iso_surfaces` 把各轨道合并成单张网格，一次 draw
       call，故只能有一个全局不透明度；等值也统一更简单
  · **颜色是每轨道独立的**
    —— 顶点色在生成网格时烘焙进各轨道自己的顶点，所以可各不相同

底层直接复用 `CubGLWidget.load_orbitals(cube_paths, isovalue, color_pairs)`。
"""

import os
import configparser

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFileDialog, QColorDialog, QMessageBox, QGroupBox, QDoubleSpinBox,
    QSlider, QFormLayout, QSizePolicy,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor

# 表格列号
C_ON, C_NAME, C_POS, C_NEG, C_FLIP = range(5)

# 默认自动配色（与 CubGLWidget._auto_orbital_color 的 4 组色相保持一致，
# 保证「不手动设色」时与 NBO 多轨道叠加的观感一致）
_PALETTE = [
    ((0.85, 0.20, 0.20), (0.20, 0.45, 0.95)),   # 红 / 蓝
    ((0.20, 0.75, 0.30), (0.95, 0.55, 0.15)),   # 绿 / 橙
    ((0.75, 0.20, 0.85), (0.95, 0.82, 0.20)),   # 紫 / 黄
    ((0.15, 0.80, 0.85), (0.95, 0.30, 0.55)),   # 青 / 粉
]

DEFAULT_ISO = 0.05
DEFAULT_OPACITY = 0.78


class CubStackPanel(QWidget):
    """多 CUB 叠加面板（右侧 tab；共享左侧 OpenGL 画布）。"""

    def __init__(self, glw=None, log_func=None, parent=None):
        super().__init__(parent)
        self.glw = glw
        self._log = log_func or (lambda m: None)
        # 每项: {"path", "enabled", "pos", "neg", "flipped"}
        # pos / neg 为 0..1 的 (r,g,b)；flipped 表示正负相位色互换
        self._items = []
        # 离散操作（增删/改色/勾选/翻转）后的重载防抖：重载要重跑 marching
        # cubes 并重建网格，快速连点会明显卡顿，统一合入最后一次。
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(300)
        self._reload_timer.timeout.connect(self._reload)
        # 等值变化（数字框输入/滑块拖动）由画布在工作线程做全分辨率 marching
        # cubes，拖动全程不阻塞 GUI（glw 内部只保留最后一次请求自动合帧），
        # 这里只需按拖动/输入两种节奏防抖，不必再降分辨率。
        self._drag_timer = QTimer(self)
        self._drag_timer.setSingleShot(True)
        self._drag_timer.setInterval(50)
        self._drag_timer.timeout.connect(self._apply_iso)
        self._live_timer = QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.setInterval(150)
        self._live_timer.timeout.connect(self._apply_iso)
        self._iso_dragging = False
        self._build_ui()
        self._load_settings()

    # ── UI ──
    def _build_ui(self):
        root = QVBoxLayout(self)
        # 全站统一：页面外边距 8px + 一级块间距 8px（基准 = AIM 面板，见
        # aim_panel._build_ui）。
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # 文件操作
        h1 = QHBoxLayout()
        b_add = QPushButton("载入 CUB…")
        b_add.clicked.connect(self._add_cubs)
        h1.addWidget(b_add)
        b_del = QPushButton("移除选中")
        b_del.clicked.connect(self._remove_selected)
        h1.addWidget(b_del)
        b_clr = QPushButton("清空")
        b_clr.clicked.connect(self._clear_all)
        h1.addWidget(b_clr)
        h1.addStretch(1)
        root.addLayout(h1)

        self.lbl_struct = QLabel("结构: （未载入）")
        self.lbl_struct.setStyleSheet("color:#64748B;")
        root.addWidget(self.lbl_struct)

        # 全局参数
        gb = QGroupBox("全局参数（所有等值面共用）")
        gf = QFormLayout(gb)
        gf.setLabelAlignment(Qt.AlignRight)
        # 等值：数字框精确输入 + 滑块实时调节（两者双向同步）
        iso_row = QWidget()
        iso_lay = QHBoxLayout(iso_row)
        iso_lay.setContentsMargins(0, 0, 0, 0)
        iso_lay.setSpacing(4)
        self.spin_iso = QDoubleSpinBox()
        self.spin_iso.setRange(0.0005, 0.5)
        self.spin_iso.setDecimals(4)
        self.spin_iso.setSingleStep(0.005)
        self.spin_iso.setValue(DEFAULT_ISO)
        self.spin_iso.setToolTip("等值面阈值（a.u.），所有 cub 共用")
        self.spin_iso.valueChanged.connect(self._on_iso_spin)
        self.sld_iso = QSlider(Qt.Horizontal)
        self.sld_iso.setRange(1, 500)          # 0.001 ~ 0.5 a.u.
        self.sld_iso.setValue(int(DEFAULT_ISO * 1000))
        self.sld_iso.setMinimumWidth(120)
        self.sld_iso.setToolTip("拖动实时调节等值面大小")
        self.sld_iso.valueChanged.connect(self._on_iso_slider)
        self.sld_iso.sliderPressed.connect(self._on_iso_pressed)
        self.sld_iso.sliderReleased.connect(self._on_iso_released)
        iso_lay.addWidget(self.spin_iso)
        iso_lay.addWidget(self.sld_iso, 1)
        gf.addRow("等值:", iso_row)
        self.sld_op = QSlider(Qt.Horizontal)
        self.sld_op.setRange(0, 100)
        self.sld_op.setValue(int(DEFAULT_OPACITY * 100))
        self.sld_op.setMinimumWidth(140)
        self.sld_op.setToolTip("等值面不透明度，所有 cub 共用")
        self.sld_op.valueChanged.connect(self._on_global_changed)
        gf.addRow("不透明度:", self.sld_op)
        root.addWidget(gb)

        # CUB 列表
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["显示", "文件", "正相位色", "负相位色", "翻转"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(C_ON, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(C_NAME, QHeaderView.Stretch)
        for c in (C_POS, C_NEG, C_FLIP):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.setToolTip(
            "每行一个 cub：勾选控制是否显示，点色块改颜色，\n"
            "「翻转」交换该 cub 的正负相位色")
        root.addWidget(self.table, 1)

        self.lbl_status = QLabel("点「载入 CUB…」选择一个或多个 .cub 文件")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet(
            "background:#F1F5F9;color:#475569;border:1px solid #E2E8F0;"
            "border-radius:4px;padding:5px 8px;")
        root.addWidget(self.lbl_status)

    # ── 列表维护 ──
    def _add_cubs(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择 CUB 文件", "",
            "Gaussian cube (*.cub *.cube);;所有文件 (*.*)")
        if not paths:
            return
        for p in paths:
            idx = len(self._items)
            pc, nc = _PALETTE[idx % len(_PALETTE)]
            self._items.append({"path": p, "enabled": True,
                                "pos": pc, "neg": nc, "flipped": False})
        self._fill_table()
        self._reload()

    def _remove_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()},
                      reverse=True)
        for r in rows:
            if 0 <= r < len(self._items):
                self._items.pop(r)
        self._fill_table()
        self._reload()

    def _clear_all(self):
        self._items = []
        self._fill_table()
        self._reload()
        self.lbl_status.setText("已清空")

    def _fill_table(self):
        self.table.setRowCount(len(self._items))
        for r, it in enumerate(self._items):
            # 显示勾选
            chk = QCheckBox()
            chk.setChecked(it["enabled"])
            chk.stateChanged.connect(
                lambda _s, r=r: self._on_enabled_changed(r))
            self.table.setCellWidget(r, C_ON, self._centered(chk))
            # 文件名
            name = os.path.basename(it["path"])
            cell = QTableWidgetItem(name)
            cell.setToolTip(it["path"])
            self.table.setItem(r, C_NAME, cell)
            # 正 / 负相位色按钮
            for col, key in ((C_POS, "pos"), (C_NEG, "neg")):
                btn = QPushButton()
                btn.setFixedSize(46, 20)
                btn.setToolTip("点击修改该 cub 的%s" %
                               ("正相位色" if key == "pos" else "负相位色"))
                btn.clicked.connect(
                    lambda _c=False, r=r, k=key: self._pick_color(r, k))
                self._paint_swatch(btn, it[key])
                btn.setEnabled(it["enabled"])
                self.table.setCellWidget(r, col, self._centered(btn))
            # 翻转
            bflip = QPushButton("⇄")
            bflip.setFixedSize(34, 20)
            bflip.setToolTip("交换该 cub 的正负相位色")
            bflip.clicked.connect(lambda _c=False, r=r: self._toggle_flip(r))
            bflip.setEnabled(it["enabled"])
            self.table.setCellWidget(r, C_FLIP, self._centered(bflip))

    @staticmethod
    def _centered(w):
        """把控件包进居中容器，避免表格里贴边难看。"""
        c = QWidget()
        h = QHBoxLayout(c)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(w)
        h.setAlignment(Qt.AlignCenter)
        return c

    @staticmethod
    def _paint_swatch(btn, rgb01):
        r, g, b = (int(round(c * 255)) for c in rgb01[:3])
        fg = "#FFFFFF" if (0.299 * r + 0.587 * g + 0.114 * b) < 128 \
            else "#1E293B"
        btn.setStyleSheet(
            "QPushButton { background-color: rgb(%d,%d,%d); color: %s;"
            " border: 1px solid #9AA7B8; border-radius: 3px; }"
            % (r, g, b, fg))

    # ── 交互 ──
    def _on_enabled_changed(self, r):
        if 0 <= r < len(self._items):
            it = self._items[r]
            # 勾选状态由内部 QCheckBox 决定，这里读回
            w = self.table.cellWidget(r, C_ON)
            chk = w.findChild(QCheckBox) if w is not None else None
            it["enabled"] = bool(chk.isChecked()) if chk is not None else True
            self._fill_table()
            self._reload()

    def _pick_color(self, r, key):
        if not (0 <= r < len(self._items)):
            return
        cur = self._items[r][key]
        col = QColorDialog.getColor(
            QColor(*(int(round(c * 255)) for c in cur)), self, "选择颜色")
        if not col.isValid():
            return
        self._items[r][key] = (col.redF(), col.greenF(), col.blueF())
        self._fill_table()
        self._reload()

    def _toggle_flip(self, r):
        if not (0 <= r < len(self._items)):
            return
        self._items[r]["flipped"] = not self._items[r]["flipped"]
        self._fill_table()
        self._reload()

    # ── 等值实时调节（滑块/数字框双向同步） ──
    def _sync_iso_slider(self):
        """把数字框的等值同步到滑块（精确输入/读设置后调用）。"""
        iso = float(self.spin_iso.value())
        v = max(1, min(500, int(round(iso * 1000.0))))
        self.sld_iso.blockSignals(True)
        self.sld_iso.setValue(v)
        self.sld_iso.blockSignals(False)

    def _on_iso_spin(self, _v=None):
        """数字框等值变化：同步滑块，防抖后全分辨率精修。"""
        self._sync_iso_slider()
        if self._items:
            self._live_timer.start()

    def _on_iso_pressed(self):
        """开始拖动滑块：进入高频防抖的异步实时重算节奏。"""
        self._iso_dragging = True
        self._drag_timer.start()

    def _on_iso_released(self):
        """松开滑块：确认一次最终值（若与上次一致画布会自动跳过重算）。"""
        self._iso_dragging = False
        self._drag_timer.stop()
        if self._items:
            self._live_timer.start()

    def _on_iso_slider(self, v):
        """等值滑块：按拖动节奏高频防抖触发异步重算，数字框同步显示。"""
        iso = max(0.0005, min(0.5, v / 1000.0))
        self.spin_iso.blockSignals(True)
        self.spin_iso.setValue(iso)
        self.spin_iso.blockSignals(False)
        if not self._items:
            return
        if self._iso_dragging:
            self._drag_timer.start()
        else:
            # 键盘方向键步进等非拖动变化：按单次变化触发
            self._live_timer.start()

    def _apply_iso(self, _=None):
        """请求画布在后台线程重算等值面（复用内存数据，不重读文件、不动视角）。

        glw.set_orbitals_isovalue 是全分辨率异步计算：工作线程跑 marching cubes，
        拖动过程中 GUI 不阻塞；画布内部自动把高频请求合帧为最后一次。
        """
        if self.glw is None:
            return
        act = [it for it in self._items if it["enabled"]]
        if not act:
            return
        iso = float(self.spin_iso.value())
        try:
            self.glw.set_orbitals_isovalue(iso)
        except Exception:
            return
        self.lbl_status.setText("已叠加 %d 个 cub（等值 %.4f）" % (len(act), iso))

    def _on_global_changed(self, _v=None):
        """不透明度等全局参数改动：防抖后重载（离散操作如增删/改色则直接调 _reload）。"""
        if self._items:
            self._reload_timer.start()

    # ── 重载到画布 ──
    def _reload(self):
        """按当前设置重新生成叠加等值面。"""
        if self.glw is None:
            return
        act = [it for it in self._items if it["enabled"]]
        if not act:
            self.lbl_struct.setText("结构: （未载入）")
            self.lbl_status.setText("没有启用的 cub")
            return

        # 结构来源 = 第一个启用的 cub（load_orbitals 内部取 recs[0]）
        self.lbl_struct.setText("结构: 取自 %s" % os.path.basename(act[0]["path"]))

        iso = float(self.spin_iso.value())
        # 翻转在这里体现：直接交换传给 load_orbitals 的正/负色
        # （load_orbitals 每次都会重建并把 flipped 重置，故不用 flip_orbital）
        pairs = []
        for it in act:
            pos, neg = it["pos"], it["neg"]
            if it["flipped"]:
                pos, neg = neg, pos
            pairs.append((tuple(int(round(c * 255)) for c in pos),
                          tuple(int(round(c * 255)) for c in neg)))

        self.glw.set_opacity(float(self.sld_op.value()) / 100.0)
        ok = self.glw.load_orbitals([it["path"] for it in act],
                                    isovalue=iso, color_pairs=pairs)
        if ok:
            self.lbl_status.setText(
                "已叠加 %d 个 cub（等值 %.4f）" % (len(act), iso))
            self._log("CUB 叠加: %d 个，等值 %.4f" % (len(act), iso))
        else:
            self.lbl_status.setText("加载失败，请检查 cub 文件格式")
        self._save_settings()

    # ── 配置持久化 ──
    def _settings_path(self):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "cub_stack_panel_settings.ini")

    def _load_settings(self):
        cfg = configparser.ConfigParser()
        try:
            if not os.path.exists(self._settings_path()):
                return
            cfg.read(self._settings_path(), encoding="utf-8")
            if "cub_stack" not in cfg:
                return
            s = cfg["cub_stack"]
            self.spin_iso.blockSignals(True)
            self.spin_iso.setValue(float(s.get("isovalue", DEFAULT_ISO)))
            self.spin_iso.blockSignals(False)
            self._sync_iso_slider()
            self.sld_op.blockSignals(True)
            self.sld_op.setValue(int(float(s.get("opacity", DEFAULT_OPACITY))
                                     * 100))
            self.sld_op.blockSignals(False)
            for line in s.get("items", "").splitlines():
                p = line.split("|")
                if len(p) != 6:
                    continue
                try:
                    self._items.append({
                        "path": p[0],
                        "enabled": p[1] == "1",
                        "pos": tuple(float(x) for x in p[2].split(",")),
                        "neg": tuple(float(x) for x in p[3].split(",")),
                        "flipped": p[4] == "1",
                    })
                except ValueError:
                    continue
            if self._items:
                self._fill_table()
        except Exception:
            pass

    def _save_settings(self):
        cfg = configparser.ConfigParser()
        lines = []
        for it in self._items:
            lines.append("|".join((
                it["path"],
                "1" if it["enabled"] else "0",
                ",".join("%.4f" % c for c in it["pos"]),
                ",".join("%.4f" % c for c in it["neg"]),
                "1" if it["flipped"] else "0",
                "",      # 预留，保持 6 字段便于以后扩展
            )))
        cfg["cub_stack"] = {
            "isovalue": "%.6f" % float(self.spin_iso.value()),
            "opacity": "%.4f" % (float(self.sld_op.value()) / 100.0),
            "items": "\n".join(lines),
        }
        try:
            with open(self._settings_path(), "w", encoding="utf-8") as f:
                cfg.write(f)
        except Exception:
            pass

    def shutdown(self):
        """关闭时清理（本面板无后台线程）。"""
        self._save_settings()
