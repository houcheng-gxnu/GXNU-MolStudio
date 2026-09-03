# -*- coding: utf-8 -*-
"""
energy_span_panel.py — Energetic Span Model 跨循环催化能量分析面板（MolStudio 的一个 tab）

功能（整合自 D:\\traetest\\energy_span_model.py，适配 MolStudio 架构）：
  1. 输入催化循环各物种能量（Int / TS + ΔG kcal/mol）
  2. 自动识别 TDI（决速中间体）/ TDTS（决速过渡态）
  3. 计算能量跨度 δE 与周转频率 TOF
  4. matplotlib 台阶式能量剖面图：双循环、跨度箭头、数值/名称标注
  5. 导出 PNG / SVG / PDF，配置持久化

核心公式：
  δE  = max( G[TDTS] - G[TDI] )（跨循环时加 ΔG_cycle）
  TOF = (kB·T/h) · exp(-δE / (R·T))
"""

import os
import math
import configparser

import matplotlib
matplotlib.use("Qt5Agg")
import matplotlib as _mpl
_mpl.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
_mpl.rcParams["axes.unicode_minus"] = False
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QCheckBox, QGroupBox, QGridLayout, QFrame, QDoubleSpinBox,
    QSpinBox, QMessageBox, QScrollArea, QSplitter,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor

from file_dialogs import save_file

# ── 配色（沿用原工具，与面板风格协调） ──
COLOR_PRIMARY = "#4f46e5"
COLOR_PRIMARY_DARK = "#3730a3"
COLOR_SUCCESS = "#10b981"
COLOR_DANGER = "#ef4444"
COLOR_CYCLE2 = "#14b8a6"
COLOR_TEXT = "#1e293b"
COLOR_TEXT2 = "#64748b"
COLOR_MUTED = "#94a3b8"
PALETTE = [
    "#4f46e5", "#ef4444", "#10b981", "#8b5cf6",
    "#f59e0b", "#06b6d4", "#ec4899", "#84cc16",
    "#f97316", "#14b8a6", "#6366f1", "#dc2626",
]


# ═══════════════════════════════════════════════════════════
# 计算核心（与 tkinter 原版一致）
# ═══════════════════════════════════════════════════════════

def compute_energy_span(species, temperature=298.15):
    """
    计算 Energy Span Model
    species: list of dict, keys: name, type ('Int' 或 'TS'), G (float, kcal/mol)
    temperature: float, K
    返回: deltaE, TDI_idx, TDTS_idx, deltaG_cycle, TOF,
          needCycle2, cycle2Species, T
    """
    n = len(species)
    if n < 2:
        raise ValueError("数据行数过少，至少需要2个物种")

    start_G = species[0]['G']
    end_G = species[-1]['G']
    deltaG_cycle = end_G - start_G

    int_indices = [i for i, sp in enumerate(species) if sp['type'] == 'Int']
    ts_indices = [i for i, sp in enumerate(species) if sp['type'] == 'TS']

    if not int_indices:
        raise ValueError("没有找到中间体(Int)类型的物种")
    if not ts_indices:
        raise ValueError("没有找到过渡态(TS)类型的物种")

    max_span = -1e10
    TDI_idx = None
    TDTS_idx = None

    for i in int_indices:
        for j in ts_indices:
            if j >= i:
                span = species[j]['G'] - species[i]['G']
            else:
                span = species[j]['G'] - species[i]['G'] + deltaG_cycle
            if span > max_span:
                max_span = span
                TDI_idx = i
                TDTS_idx = j

    if TDI_idx is None or TDTS_idx is None:
        raise ValueError("无法计算出有效的能量跨度")

    deltaE_J = max_span * 4184
    kB = 1.380649e-23
    h = 6.62607015e-34
    R = 8.314
    TOF = (kB * temperature / h) * math.exp(-deltaE_J / (R * temperature))

    need_cycle2 = TDTS_idx < TDI_idx
    cycle2_species = []
    if need_cycle2:
        for sp in species:
            cycle2_species.append({
                'name': sp['name'] + '_C2',
                'type': sp['type'],
                'G': sp['G'] + deltaG_cycle
            })

    return {
        'deltaE': max_span,
        'TDI_idx': TDI_idx,
        'TDTS_idx': TDTS_idx,
        'deltaG_cycle': deltaG_cycle,
        'TOF': TOF,
        'needCycle2': need_cycle2,
        'cycle2Species': cycle2_species,
        'T': temperature,
    }


# ═══════════════════════════════════════════════════════════
# 物种行（名称 / 类型 / ΔG / 删除）
# ═══════════════════════════════════════════════════════════

class SpeciesRow(QWidget):
    """一行物种数据编辑。"""

    def __init__(self, parent, on_delete, data=None):
        super().__init__(parent)
        self.on_delete = on_delete

        if data:
            name = data.get('name', '')
            stype = data.get('type', 'Int')
            energy = data.get('energy', data.get('G', ''))
        else:
            name, stype, energy = '', 'Int', ''

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 1, 0, 1)
        lay.setSpacing(6)

        self.txt_name = QLineEdit(str(name))
        self.txt_name.setPlaceholderText("名称")
        lay.addWidget(self.txt_name, 3)

        self.combo_type = QComboBox()
        self.combo_type.addItems(["Int", "TS"])
        self.combo_type.setCurrentText(stype)
        self.combo_type.setMaximumWidth(70)
        lay.addWidget(self.combo_type)

        self.txt_energy = QLineEdit("" if energy == '' else str(energy))
        self.txt_energy.setPlaceholderText("ΔG")
        self.txt_energy.setMaximumWidth(90)
        lay.addWidget(self.txt_energy)

        btn_del = QPushButton("✕")
        btn_del.setMaximumWidth(28)
        btn_del.setStyleSheet("""
            QPushButton { background:transparent; color:#94A3B8;
                           border:none; font-weight:bold; }
            QPushButton:hover { color:#EF4444; background:#FEF2F2;
                                border-radius:4px; }
        """)
        btn_del.clicked.connect(self._on_del)
        lay.addWidget(btn_del)

        self.setStyleSheet("""
            SpeciesRow QLineEdit {
                background:#FFFFFF; border:1px solid #CBD5E1;
                border-radius:6px; padding:3px 8px;
            }
            SpeciesRow QComboBox {
                background:#FFFFFF; border:1px solid #CBD5E1;
                border-radius:6px; padding:2px 6px;
            }
        """)

    def _on_del(self):
        self.on_delete(self)

    def get_data(self):
        name = self.txt_name.text().strip()
        stype = self.combo_type.currentText()
        energy_str = self.txt_energy.text().strip()
        try:
            energy = float(energy_str)
        except ValueError:
            return None
        if not name or energy_str == '':
            return None
        return {'name': name, 'type': stype, 'G': energy}


# ═══════════════════════════════════════════════════════════
# 面板
# ═══════════════════════════════════════════════════════════

class EnergySpanPanel(QWidget):
    """Energetic Span Model 分析面板（右侧 tab）。"""

    def __init__(self, log_func=None, parent=None):
        super().__init__(parent)
        self._log = log_func or (lambda m: None)
        self.rows = []
        self.result = None
        self.species_data = []
        self._figure = None
        self._canvas = None

        self._build_ui()
        self._load_settings()
        self._load_template('default')
        self._draw_placeholder()

    # ── UI ──
    def showEvent(self, event):
        super().showEvent(event)
        if self.result is not None:
            QTimer.singleShot(0, self._redraw)

    def _build_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        # ── 左侧：标题行 + 图表（占主要空间） ──
        left_widget = QWidget()
        left_l = QVBoxLayout(left_widget)
        left_l.setContentsMargins(0, 0, 0, 0)
        left_l.setSpacing(8)

        header = QHBoxLayout()
        t = QLabel("📊 能量剖面图")
        t.setStyleSheet("font-size:14pt;font-weight:bold;color:#1E293B;")
        header.addWidget(t)
        self.badge_label = QLabel("")
        self.badge_label.setStyleSheet(
            "background:#10B981;color:white;font-weight:bold;"
            "border-radius:4px;padding:2px 12px;")
        header.addWidget(self.badge_label)
        header.addStretch(1)
        left_l.addLayout(header)

        self.fig_holder = QWidget()
        self._canvas_layout = QVBoxLayout(self.fig_holder)
        self._canvas_layout.setContentsMargins(0, 0, 0, 0)
        left_l.addWidget(self.fig_holder, stretch=1)
        outer.addWidget(left_widget, stretch=1)

        # ── 右侧：设置区（浅色渐变圆角卡片，固定宽度） ──
        grp = QGroupBox("Energetic Span Model 设置")
        grp.setObjectName("EsmSettingsBox")
        grp.setStyleSheet("""
            QGroupBox#EsmSettingsBox {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0 #FFFFFF, stop:1 #F1F5FB);
                border: 1px solid #D5DEE9;
                border-radius: 12px;
                margin-top: 14px;
            }
            QGroupBox#EsmSettingsBox::title {
                subcontrol-origin: margin;
                left: 14px;
                padding: 2px 10px;
                background-color: #4F46E5;
                color: #FFFFFF;
                border-radius: 4px;
                font-weight: bold;
                font-size: 10pt;
            }
            QGroupBox#EsmSettingsBox QLineEdit {
                background: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 3px 8px;
            }
            QGroupBox#EsmSettingsBox QComboBox {
                background: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 2px 6px;
            }
            QGroupBox#EsmSettingsBox QPushButton {
                background: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 4px 12px;
            }
            QGroupBox#EsmSettingsBox QPushButton:hover {
                background: #EEF2FF;
                border-color: #4F46E5;
            }
        """)
        gl = QGridLayout(grp)
        gl.setContentsMargins(10, 8, 10, 10)
        gl.setHorizontalSpacing(10)
        gl.setVerticalSpacing(6)

        # ── 物种数据区 ──
        lbl_data = QLabel("催化循环 - 能量数据（Int = 中间体, TS = 过渡态）")
        lbl_data.setStyleSheet("font-weight:bold;color:#1E293B;")
        gl.addWidget(lbl_data, 0, 0, 1, 4)

        hdr = QHBoxLayout()
        for txt, st in [("物种名称", "font-weight:bold;color:#64748B;"),
                        ("类型", "font-weight:bold;color:#64748B;"),
                        ("ΔG (kcal/mol)", "font-weight:bold;color:#64748B;"),
                        ("", "")]:
            l = QLabel(txt)
            l.setStyleSheet(st)
            hdr.addWidget(l)
        gl.addLayout(hdr, 1, 0, 1, 4)

        # 行列表（外层套一个可滚动区域防过多行）
        self.rows_container = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_container)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(2)
        scroll = QScrollArea()
        scroll.setWidget(self.rows_container)
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(120)
        scroll.setMaximumHeight(200)
        scroll.setStyleSheet("QScrollArea{border:1px solid #D5DEE9;"
                             "border-radius:6px;background:transparent;}")
        gl.addWidget(scroll, 2, 0, 1, 4)

        row_btns = QHBoxLayout()
        btn_add = QPushButton("＋ 添加物种")
        btn_add.clicked.connect(lambda: self._add_row())
        row_btns.addWidget(btn_add)
        btn_tpl1 = QPushButton("📋 默认示例")
        btn_tpl1.clicked.connect(lambda: self._load_template('default'))
        row_btns.addWidget(btn_tpl1)
        btn_tpl2 = QPushButton("📋 简单反应")
        btn_tpl2.clicked.connect(lambda: self._load_template('simple'))
        row_btns.addWidget(btn_tpl2)
        row_btns.addStretch(1)
        gl.addLayout(row_btns, 3, 0, 1, 4)

        # ── 参数设置 ──
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setStyleSheet("color:#E2E8F0;")
        gl.addWidget(sep1, 4, 0, 1, 4)

        lbl_param = QLabel("参数与绘图设置")
        lbl_param.setStyleSheet("font-weight:bold;color:#1E293B;")
        gl.addWidget(lbl_param, 5, 0, 1, 4)

        gl.addWidget(QLabel("温度 (K):"), 6, 0)
        self.txt_temp = QLineEdit("298.15")
        self.txt_temp.setMaximumWidth(90)
        gl.addWidget(self.txt_temp, 6, 1)

        gl.addWidget(QLabel("线条粗细:"), 6, 2)
        self.spin_lw = QDoubleSpinBox()
        self.spin_lw.setRange(1.0, 8.0)
        self.spin_lw.setSingleStep(0.5)
        self.spin_lw.setValue(3.0)
        self.spin_lw.setMaximumWidth(80)
        self.spin_lw.valueChanged.connect(self._on_setting_change)
        gl.addWidget(self.spin_lw, 6, 3)

        gl.addWidget(QLabel("标签字号:"), 7, 0)
        self.spin_ts = QSpinBox()
        self.spin_ts.setRange(8, 24)
        self.spin_ts.setValue(12)
        self.spin_ts.setMaximumWidth(80)
        self.spin_ts.valueChanged.connect(self._on_setting_change)
        gl.addWidget(self.spin_ts, 7, 1)

        chk_row = QHBoxLayout()
        self.chk_values = QCheckBox("数值")
        self.chk_values.setChecked(True)
        self.chk_values.toggled.connect(self._on_setting_change)
        chk_row.addWidget(self.chk_values)
        self.chk_tags = QCheckBox("标签")
        self.chk_tags.setChecked(True)
        self.chk_tags.toggled.connect(self._on_setting_change)
        chk_row.addWidget(self.chk_tags)
        self.chk_grid = QCheckBox("网格")
        self.chk_grid.setChecked(True)
        self.chk_grid.toggled.connect(self._on_setting_change)
        chk_row.addWidget(self.chk_grid)
        self.chk_span = QCheckBox("跨度箭头")
        self.chk_span.setChecked(True)
        self.chk_span.toggled.connect(self._on_setting_change)
        chk_row.addWidget(self.chk_span)
        chk_row.addStretch(1)
        gl.addLayout(chk_row, 7, 2, 1, 2)

        # ── 计算结果 ──
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("color:#E2E8F0;")
        gl.addWidget(sep2, 8, 0, 1, 4)

        lbl_res = QLabel("计算结果")
        lbl_res.setStyleSheet("font-weight:bold;color:#1E293B;")
        gl.addWidget(lbl_res, 9, 0, 1, 4)

        self._result_labels = {}
        result_rows = [
            ("dG_cycle", "ΔG_cycle"),
            ("tdi", "决速中间体 (TDI)"),
            ("tdts", "决速过渡态 (TDTS)"),
            ("deltaE", "能量跨度 (δE)"),
            ("tof", "周转频率 (TOF)"),
            ("cycle2", "循环2数据"),
        ]
        for i, (key, txt) in enumerate(result_rows):
            r = 10 + i
            l = QLabel(txt)
            l.setStyleSheet("color:#64748B;")
            gl.addWidget(l, r, 0)
            v = QLabel("—")
            v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            v.setStyleSheet("font-family:Consolas;font-weight:bold;color:#1E293B;")
            gl.addWidget(v, r, 1, 1, 3)
            self._result_labels[key] = v

        # ── 操作按钮 ──
        sep3 = QFrame()
        sep3.setFrameShape(QFrame.HLine)
        sep3.setStyleSheet("color:#E2E8F0;")
        gl.addWidget(sep3, 16, 0, 1, 4)

        act = QHBoxLayout()
        btn_calc = QPushButton("▶ 计算并绘图")
        btn_calc.setStyleSheet("""
            background:#4F46E5;color:#FFFFFF;font-weight:bold;
            border:1px solid #4F46E5;border-radius:6px;padding:5px 18px;
        """)
        btn_calc.clicked.connect(self._do_calculate)
        act.addWidget(btn_calc)
        btn_reset = QPushButton("↺ 重置")
        btn_reset.clicked.connect(self._do_reset)
        act.addWidget(btn_reset)
        self.btn_png = QPushButton("导出 PNG")
        self.btn_png.clicked.connect(lambda: self._export('png'))
        self.btn_png.setEnabled(False)
        act.addWidget(self.btn_png)
        self.btn_svg = QPushButton("导出 SVG")
        self.btn_svg.clicked.connect(lambda: self._export('svg'))
        self.btn_svg.setEnabled(False)
        act.addWidget(self.btn_svg)
        self.btn_pdf = QPushButton("导出 PDF")
        self.btn_pdf.clicked.connect(lambda: self._export('pdf'))
        self.btn_pdf.setEnabled(False)
        act.addWidget(self.btn_pdf)
        act.addStretch(1)
        gl.addLayout(act, 17, 0, 1, 4)

        # 右侧设置卡片包一层纵向滚动区，防止矮窗口下内容被截断
        right_scroll = QScrollArea()
        right_scroll.setWidget(grp)
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        right_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        # 左右可拖动分隔条（与主窗口画布/设置区一致）
        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setHandleWidth(1)
        self._splitter.addWidget(left_widget)
        self._splitter.addWidget(right_scroll)
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 0)
        self._splitter.setSizes([760, 460])
        self._splitter.splitterMoved.connect(self._on_splitter_moved)
        outer.addWidget(self._splitter, stretch=1)

    # ── 物种行操作 ──
    def _add_row(self, data=None):
        row = SpeciesRow(self.rows_container, self._delete_row, data)
        self.rows_layout.addWidget(row)
        self.rows.append(row)

    def _delete_row(self, row):
        if len(self.rows) <= 2:
            QMessageBox.information(self, "提示", "至少保留2个物种")
            return
        self.rows_layout.removeWidget(row)
        row.deleteLater()
        self.rows.remove(row)

    def _read_species_data(self):
        species = []
        for row in self.rows:
            d = row.get_data()
            if d:
                species.append(d)
        return species

    def _clear_rows(self):
        for row in self.rows:
            self.rows_layout.removeWidget(row)
            row.deleteLater()
        self.rows.clear()

    def _load_template(self, tpl_type):
        self._clear_rows()
        if tpl_type == 'default':
            data = [
                {'name': 'IM1', 'type': 'Int', 'energy': 0},
                {'name': 'TS1', 'type': 'TS', 'energy': 30.3},
                {'name': 'IM2', 'type': 'Int', 'energy': -7.0},
                {'name': 'TS2', 'type': 'TS', 'energy': 29.3},
                {'name': 'IM1', 'type': 'Int', 'energy': -2.6},
            ]
        else:
            data = [
                {'name': 'Reactant', 'type': 'Int', 'energy': 0},
                {'name': 'TS1', 'type': 'TS', 'energy': 25},
                {'name': 'Product', 'type': 'Int', 'energy': -10},
            ]
        for d in data:
            self._add_row(d)

    # ── 计算与绘图 ──
    def _do_calculate(self):
        try:
            species = self._read_species_data()
            if len(species) < 2:
                QMessageBox.warning(self, "提示", "请至少输入2个物种数据")
                return
            temp_str = self.txt_temp.text().strip()
            temp = float(temp_str) if temp_str else 298.15
            self.result = compute_energy_span(species, temp)
            self.species_data = species

            self._display_results(self.result, species)
            self._draw(species, self.result)

            self.badge_label.setText("δE = %.1f kcal/mol" % self.result["deltaE"])
            for b in (self.btn_png, self.btn_svg, self.btn_pdf):
                b.setEnabled(True)
            self._log("ESM: δE = %.2f kcal/mol, TOF = %.2e s⁻¹, TDI=%s, TDTS=%s"
                      % (self.result["deltaE"], self.result["TOF"],
                         species[self.result["TDI_idx"]]["name"],
                         species[self.result["TDTS_idx"]]["name"]))
            self._save_settings()
        except ValueError as e:
            QMessageBox.critical(self, "计算错误", str(e))
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def _do_reset(self):
        self._load_template('default')
        self.result = None
        self.species_data = []
        self._draw_placeholder()
        self.badge_label.setText("")
        for key in self._result_labels:
            self._result_labels[key].setText("—")
        for b in (self.btn_png, self.btn_svg, self.btn_pdf):
            b.setEnabled(False)

    def _display_results(self, result, species):
        def _set(key, val, color):
            lbl = self._result_labels[key]
            lbl.setText(val)
            lbl.setStyleSheet(
                "font-family:Consolas;font-weight:bold;color:%s;" % color)

        _set("dG_cycle", "%.2f kcal/mol" % result["deltaG_cycle"], COLOR_TEXT)
        _set("tdi", species[result["TDI_idx"]]["name"], COLOR_SUCCESS)
        _set("tdts", species[result["TDTS_idx"]]["name"], COLOR_DANGER)
        _set("deltaE", "%.2f kcal/mol" % result["deltaE"], COLOR_PRIMARY)
        _set("tof", "%.2e s⁻¹" % result["TOF"], COLOR_TEXT)
        if result["needCycle2"]:
            _set("cycle2", "已生成 ✓", COLOR_CYCLE2)
        else:
            _set("cycle2", "无需生成", COLOR_TEXT2)

    def _on_setting_change(self, *args):
        if self.result is not None:
            self._redraw()

    def _on_splitter_moved(self, *_args):
        """拖动左右分隔条后按新宽度重绘图表。"""
        if self.result is not None:
            QTimer.singleShot(0, self._redraw)

    def _redraw(self):
        if self.result is not None:
            self._draw(self.species_data, self.result)

    # ── 图表 ──
    def _figsize(self):
        # 左侧图区宽度取分隔条左栏实际宽度（可拖动）
        try:
            w = self._splitter.sizes()[0]
        except Exception:
            w = self.width()
        w = max(w - 8, 320)
        h = max(self.height() - 60, 240)
        return (w / 100.0, h / 100.0)

    def _set_canvas(self, fig):
        if self._canvas is None:
            self._canvas = FigureCanvas(fig)
            self._canvas_layout.addWidget(self._canvas)
        else:
            self._canvas_layout.removeWidget(self._canvas)
            try:
                self._canvas.close()
            except Exception:
                pass
            self._canvas = FigureCanvas(fig)
            self._canvas_layout.addWidget(self._canvas)
        self._canvas.draw()

    def _draw_placeholder(self):
        fig = Figure(figsize=self._figsize(), dpi=100, facecolor="white")
        ax = fig.add_subplot(111)
        ax.text(0.5, 0.5, "请输入数据后点击「计算并绘图」",
                ha="center", va="center", fontsize=14, color=COLOR_MUTED)
        ax.set_xticks([])
        ax.set_yticks([])
        for s in ax.spines.values():
            s.set_visible(False)
        self._set_canvas(fig)

    def _draw(self, species, result):
        fig = Figure(figsize=self._figsize(), dpi=100, facecolor="white")
        ax = fig.add_subplot(111)
        ax.set_facecolor("white")

        # 构建路径（含循环2）
        paths = [{'label': '催化循环1', 'color': PALETTE[0], 'data': species}]
        if result['needCycle2']:
            paths.append({'label': '催化循环2', 'color': COLOR_CYCLE2,
                          'data': result['cycle2Species']})

        all_y = [pt['G'] for p in paths for pt in p['data']]
        min_y = min(all_y)
        max_y = max(all_y)
        y_range = max_y - min_y if max_y != min_y else 1
        y_pad = y_range * 0.25
        y_min = min_y - y_pad
        y_max = max_y + y_pad

        step_w = 0.6
        half = step_w / 2
        cycle1_len = len(paths[0]['data'])
        lw = self.spin_lw.value()
        tag_size = self.spin_ts.value()

        for path_idx, path in enumerate(paths):
            color = path['color']
            pts = path['data']
            n = len(pts)
            x_offset = cycle1_len if path_idx == 1 else 0

            for i, pt in enumerate(pts):
                x_pos = i + x_offset
                ax.plot([x_pos - half, x_pos + half], [pt['G'], pt['G']],
                        color=color, linewidth=lw)
                if self.chk_values.isChecked():
                    ax.text(x_pos, pt['G'] + y_pad * 0.05, "%.1f" % pt['G'],
                            ha='center', va='bottom', fontsize=tag_size - 2,
                            color=color, fontweight='bold')
                if self.chk_tags.isChecked() and pt['name']:
                    ax.text(x_pos, pt['G'] - y_pad * 0.08, pt['name'],
                            ha='center', va='top', fontsize=tag_size,
                            color='#666666', fontweight='bold')

            for i in range(n - 1):
                x1 = i + x_offset
                x2 = i + 1 + x_offset
                ax.plot([x1 + half, x2 - half],
                        [pts[i]['G'], pts[i + 1]['G']],
                        color=color, linewidth=lw * 0.7)

        # 能量跨度箭头
        if self.chk_span.isChecked():
            tdi_x = result['TDI_idx']
            tdi_y = species[result['TDI_idx']]['G']
            if result['needCycle2']:
                target_x = result['TDTS_idx'] + cycle1_len
                target_y = result['cycle2Species'][result['TDTS_idx']]['G']
            else:
                target_x = result['TDTS_idx']
                target_y = species[result['TDTS_idx']]['G']
            ax.plot([target_x, target_x], [target_y, tdi_y],
                    color='#666666', linestyle='--', linewidth=2)
            ax.plot([tdi_x, target_x], [tdi_y, tdi_y],
                    color='#666666', linestyle='--', linewidth=2)
            mid_x = (tdi_x + target_x) / 2
            ax.text(mid_x, tdi_y + y_pad * 0.08, "δE = %.1f" % result["deltaE"],
                    ha='center', va='bottom', fontsize=12,
                    fontweight='bold', color='#333333')
            ax.annotate('', xy=(target_x, tdi_y), xytext=(target_x, target_y),
                        arrowprops=dict(arrowstyle='->', color='#666666',
                                        linewidth=2))

        # 循环分隔线
        if result['needCycle2']:
            ax.axvline(x=cycle1_len - 0.5, color='#cccccc',
                       linestyle='--', linewidth=1.5)

        total_x = cycle1_len + (len(paths[1]['data'])
                                if result['needCycle2'] else 0)
        ax.set_xlim(-0.8, total_x - 0.2)
        ax.set_ylim(y_min, y_max)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        if self.chk_grid.isChecked():
            ax.grid(True, axis='y', color='#d1d5db', linestyle='--')
        ax.set_ylabel('ΔG (kcal/mol)', fontsize=12, fontweight='bold')
        ax.set_xlabel('Reaction Coordinate', fontsize=12, fontweight='bold')
        ax.set_xticks([])
        fig.subplots_adjust(left=0.10, right=0.97, top=0.95, bottom=0.10)
        self._set_canvas(fig)

    # ── 导出 ──
    def _export(self, fmt):
        if self.result is None or self._canvas is None:
            QMessageBox.information(self, "提示", "请先计算并绘图")
            return
        fname = "energy_span_%s.%s" % (
            __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S"), fmt)
        path, _ = save_file(self, "导出 %s 图片" % fmt.upper(), fname,
                            "%s Image (*.%s)" % (fmt.upper(), fmt))
        if not path:
            return
        try:
            dpi = 300 if fmt == 'png' else None
            self._canvas.figure.savefig(path, dpi=dpi, bbox_inches='tight',
                                        facecolor='white', edgecolor='none')
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))
            return
        self._log("ESM: 已导出 %s：%s" % (fmt.upper(), path))
        QMessageBox.information(self, "导出成功",
                                "已保存至:\n%s\n\n格式: %s" % (path, fmt.upper()))

    # ── 配置持久化 ──
    def _settings_path(self):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "esm_panel_settings.ini")

    def _load_settings(self):
        cfg = configparser.ConfigParser()
        try:
            if os.path.exists(self._settings_path()):
                cfg.read(self._settings_path(), encoding="utf-8")
                if "esm" in cfg:
                    t = cfg["esm"].get("temperature", "")
                    if t:
                        self.txt_temp.setText(t)
                    self.spin_lw.setValue(
                        float(cfg["esm"].get("line_width", "3.0")))
                    self.spin_ts.setValue(
                        int(cfg["esm"].get("tag_size", "12")))
                    self.chk_values.setChecked(
                        cfg["esm"].getboolean("show_values", True))
                    self.chk_tags.setChecked(
                        cfg["esm"].getboolean("show_tags", True))
                    self.chk_grid.setChecked(
                        cfg["esm"].getboolean("show_grid", True))
                    self.chk_span.setChecked(
                        cfg["esm"].getboolean("show_span", True))
        except Exception:
            pass

    def _save_settings(self):
        cfg = configparser.ConfigParser()
        cfg["esm"] = {
            "temperature": self.txt_temp.text().strip() or "298.15",
            "line_width": str(self.spin_lw.value()),
            "tag_size": str(self.spin_ts.value()),
            "show_values": "1" if self.chk_values.isChecked() else "0",
            "show_tags": "1" if self.chk_tags.isChecked() else "0",
            "show_grid": "1" if self.chk_grid.isChecked() else "0",
            "show_span": "1" if self.chk_span.isChecked() else "0",
        }
        try:
            with open(self._settings_path(), "w", encoding="utf-8") as f:
                cfg.write(f)
        except Exception:
            pass

    def shutdown(self):
        """关闭时清理（本面板无后台线程）。"""
        self._save_settings()
