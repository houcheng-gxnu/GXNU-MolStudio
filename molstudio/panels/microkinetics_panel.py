# -*- coding: utf-8 -*-
"""microkinetics_panel.py — 催化循环微观动力学（AUTOF 稳态模型）分析面板。

算法核心见 :mod:`molstudio.core.microkinetics`（纯数值、无 Qt 依赖）。
与能量跨度 (ESM) 面板的关系：本页用 Kozuch 的精确稳态解析式，
ESM 页的 TOF = (kBT/h)·exp(-δE/RT) 是它在标准浓度/单一决速态下的近似。

算法来源：Uhe, Kozuch & Shaik, J. Comput. Chem. 2011, 32, 978；
Kozuch & Shaik, Acc. Chem. Res. 2011, 44, 101；AUTOF (S. Kozuch)。
本文件为独立实现，未复制原 Excel 版 VBA 代码。
"""

from __future__ import annotations

import configparser
import csv
import datetime
import json
import math

import matplotlib
matplotlib.use("Qt5Agg")
import matplotlib as _mpl
_mpl.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
_mpl.rcParams["axes.unicode_minus"] = False
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QCheckBox, QGroupBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QScrollArea, QSplitter, QFrame,
    QMessageBox, QSpinBox, QAbstractItemView,
)

from molstudio.core.microkinetics import (
    CycleProfile, Deactivation, steady_state, ton_until_deactivation, simulate,
)
from molstudio.ui.file_dialogs import save_file

COLOR_PRIMARY = "#4f46e5"
COLOR_DANGER = "#ef4444"
COLOR_SUCCESS = "#10b981"
COLOR_TEXT = "#1e293b"
COLOR_TEXT2 = "#64748b"
COLOR_MUTED = "#94a3b8"

HEADERS = ("Step", "Int G0", "TS G0", "[R]", "[P]", "XTOF(Int)", "XTOF(TS)",
           "XTOF(R)", "XTOF(P)", "[Cat]", "G!=0", "TDI/TDTS")
INPUT_COLS = (1, 2, 3, 4)
TIME_FACTORS = {"s": 1.0, "min": 60.0, "h": 3600.0}

#: 中英文字对照（切语言时由 set_lang 整树套用，见 molstudio/ui/i18n_utils.py）
_LANG_EXTRA = {
    "🧪 微观动力学分析": "🧪 Microkinetic Analysis",
    "催化循环能量剖面（浓度留空 = 该步无外部给料）":
        "Catalytic cycle profile (blank concentration = no external species in this step)",
    "＋ 添加步骤": "＋ Add step",
    "－ 删除步骤": "－ Remove step",
    "📋 AUTOF 示例": "📋 AUTOF example",
    "循环设置": "Cycle setup",
    "温度 (K):": "Temperature (K):",
    "能量单位:": "Energy unit:",
    "催化剂总浓度 [Ct] (M):": "Total catalyst [Ct] (M):",
    "可选动力学过程": "Optional kinetic processes",
    "启用时间演化": "Enable time evolution",
    "演化时间:": "Time:",
    "启用催化剂失活": "Enable deactivation",
    "失活起始步 Cx:": "Deactivation step Cx:",
    "失活过渡态 Td:": "Deactivation TS Td:",
    "失活反应物 [Rd]:": "Deactivation reactant [Rd]:",
    "预活化能垒 ΔG‡:": "Preactivation barrier ΔG‡:",
    "▶ 计算": "▶ Compute",
    "计算结果": "Results",
    "反应自由能 ΔG_r": "Reaction free energy ΔG_r",
    "能量跨度 δE": "Energetic span δE",
    "ESM 最大跨度": "ESM maximum span",
    "决速中间体 (TDI)": "TOF-determining intermediate (TDI)",
    "决速过渡态 (TDTS)": "TOF-determining TS (TDTS)",
    "周转频率 TOF": "Turnover frequency TOF",
    "ESM 近似 TOF": "ESM approximate TOF",
    "失活前 TON": "TON before deactivation",
    "TOF(t)": "TOF(t)",
    "TON(t)": "TON(t)",
    "活性催化剂 [Cat]": "Active catalyst [Cat]",
    "图表与导出": "Plots and export",
    "导出 CSV": "Export CSV",
    "导出 PNG": "Export PNG",
    "导出 SVG": "Export SVG",
    "导出 PDF": "Export PDF",
    "↺ 重置": "↺ Reset",
    "提示": "Notice",
    "计算错误": "Calculation error",
    "输入错误": "Invalid input",
    "导出失败": "Export failed",
    "导出成功": "Exported",
    "请先计算": "Please compute first",
    "已保存至:": "Saved to:",
    "格式:": "Format:",
    "计算完成": "Done",
    "微观动力学": "Microkinetics",
    "请输入数据后点击「计算」": "Enter data and press Compute",
}


def _autof_example_data():
    """AUTOF_Excel_v0.9.xlsm 自带示例（同时作为回归基准）。"""
    return {
        "inter": [0.0, -7.0, 5.0, -10.0],
        "ts": [15.0, 8.0, 11.5],
        "react": [1.0, "", 1.0],
        "prod": ["", 0.1, 0.1],
        "temp": "298.15", "unit": "kcal/mol", "cat": "0.01",
        "dynamics": True, "time": "20", "time_unit": "min",
        "deact": True, "cx": 2, "td": "16", "rd": "1", "pre": "21.5",
    }


class MicrokineticsPanel(QWidget):
    """线性催化循环精确稳态微观动力学面板（右侧 tab）。"""

    def __init__(self, log_func=None, parent=None):
        super().__init__(parent)
        self._log = log_func or (lambda m: None)
        self._lang = "zh"
        self.profile = None
        self.steady = None
        self.trajectory = None
        self._canvas = None
        self._build_ui()
        self._load_settings()
        self._draw_placeholder()

    # ── UI ────────────────────────────────────────────────────────────────
    def _t(self, zh, en):
        return zh if self._lang == "zh" else en

    def _build_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        left = QWidget()
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)
        left_l.setSpacing(6)
        header = QHBoxLayout()
        title = QLabel("🧪 微观动力学分析")
        title.setStyleSheet("font-size:14pt;font-weight:bold;color:#1E293B;")
        header.addWidget(title)
        self.badge = QLabel("")
        self.badge.setStyleSheet(
            "background:#10B981;color:white;font-weight:bold;"
            "border-radius:4px;padding:2px 12px;")
        header.addWidget(self.badge)
        header.addStretch(1)
        left_l.addLayout(header)
        self.fig_holder = QWidget()
        self._canvas_layout = QVBoxLayout(self.fig_holder)
        self._canvas_layout.setContentsMargins(0, 0, 0, 0)
        left_l.addWidget(self.fig_holder, stretch=1)

        right = QWidget()
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(right)
        scroll.setMinimumWidth(430)

        grp_cycle = QGroupBox("循环设置")
        g = QGridLayout(grp_cycle)
        g.setContentsMargins(10, 8, 10, 10)
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(6)

        lbl_tbl = QLabel("催化循环能量剖面（浓度留空 = 该步无外部给料）")
        lbl_tbl.setWordWrap(True)
        lbl_tbl.setStyleSheet("font-weight:bold;color:#1E293B;")
        g.addWidget(lbl_tbl, 0, 0, 1, 4)

        self.table = QTableWidget()
        self.table.setColumnCount(len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setMinimumHeight(150)
        self.table.setMaximumHeight(260)
        self.table.horizontalHeader().setDefaultSectionSize(74)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.setColumnWidth(0, 48)
        self.table.setColumnWidth(11, 90)
        self.table.verticalHeader().setVisible(False)
        g.addWidget(self.table, 1, 0, 1, 4)

        btns = QHBoxLayout()
        btn_add = QPushButton("＋ 添加步骤")
        btn_add.clicked.connect(self._add_step)
        btn_del = QPushButton("－ 删除步骤")
        btn_del.clicked.connect(self._remove_step)
        btn_demo = QPushButton("📋 AUTOF 示例")
        btn_demo.clicked.connect(lambda: self._restore(_autof_example_data()))
        for b in (btn_add, btn_del, btn_demo):
            btns.addWidget(b)
        btns.addStretch(1)
        g.addLayout(btns, 2, 0, 1, 4)

        g.addWidget(QLabel("温度 (K):"), 3, 0)
        self.txt_temp = QLineEdit("298.15")
        self.txt_temp.setMaximumWidth(100)
        g.addWidget(self.txt_temp, 3, 1)
        g.addWidget(QLabel("能量单位:"), 3, 2)
        self.combo_unit = QComboBox()
        self.combo_unit.addItems(["kcal/mol", "kJ/mol"])
        g.addWidget(self.combo_unit, 3, 3)

        g.addWidget(QLabel("催化剂总浓度 [Ct] (M):"), 4, 0, 1, 2)
        self.txt_cat = QLineEdit("1")
        self.txt_cat.setMaximumWidth(100)
        g.addWidget(self.txt_cat, 4, 2, 1, 2)
        right_l.addWidget(grp_cycle)

        grp_dyn = QGroupBox("可选动力学过程")
        d = QGridLayout(grp_dyn)
        d.setContentsMargins(10, 8, 10, 10)
        d.setHorizontalSpacing(8)
        d.setVerticalSpacing(6)
        self.chk_dyn = QCheckBox("启用时间演化")
        self.chk_dyn.setChecked(True)
        d.addWidget(self.chk_dyn, 0, 0, 1, 2)
        d.addWidget(QLabel("演化时间:"), 0, 2)
        h_time = QHBoxLayout()
        self.txt_time = QLineEdit("20")
        self.txt_time.setMaximumWidth(70)
        self.combo_time = QComboBox()
        self.combo_time.addItems(list(TIME_FACTORS))
        h_time.addWidget(self.txt_time)
        h_time.addWidget(self.combo_time)
        d.addLayout(h_time, 0, 3)

        self.chk_deact = QCheckBox("启用催化剂失活")
        d.addWidget(self.chk_deact, 1, 0, 1, 2)
        d.addWidget(QLabel("预活化能垒 ΔG‡:"), 1, 2)
        self.txt_pre = QLineEdit("")
        self.txt_pre.setPlaceholderText("optional")
        self.txt_pre.setMaximumWidth(80)
        d.addWidget(self.txt_pre, 1, 3)

        d.addWidget(QLabel("失活起始步 Cx:"), 2, 0)
        self.spin_cx = QSpinBox()
        self.spin_cx.setRange(1, 27)
        self.spin_cx.setValue(2)
        d.addWidget(self.spin_cx, 2, 1)
        d.addWidget(QLabel("失活过渡态 Td:"), 2, 2)
        self.txt_td = QLineEdit("16")
        self.txt_td.setMaximumWidth(80)
        d.addWidget(self.txt_td, 2, 3)

        d.addWidget(QLabel("失活反应物 [Rd]:"), 3, 0)
        self.txt_rd = QLineEdit("1")
        self.txt_rd.setMaximumWidth(80)
        d.addWidget(self.txt_rd, 3, 1)
        right_l.addWidget(grp_dyn)

        act = QHBoxLayout()
        self.btn_calc = QPushButton("▶ 计算")
        self.btn_calc.setStyleSheet(
            "QPushButton{background:#4F46E5;color:white;font-weight:bold;"
            "border-radius:6px;padding:6px 14px;}")
        self.btn_calc.clicked.connect(self._calculate)
        act.addWidget(self.btn_calc)
        btn_reset = QPushButton("↺ 重置")
        btn_reset.clicked.connect(lambda: self._restore(_autof_example_data()))
        act.addWidget(btn_reset)
        act.addStretch(1)
        right_l.addLayout(act)

        grp_res = QGroupBox("计算结果")
        r_lay = QGridLayout(grp_res)
        r_lay.setContentsMargins(10, 8, 10, 10)
        r_lay.setHorizontalSpacing(8)
        r_lay.setVerticalSpacing(4)
        result_rows = [
            ("dgr", "反应自由能 ΔG_r"), ("delta_e", "能量跨度 δE"),
            ("max_span", "ESM 最大跨度"), ("tdi", "决速中间体 (TDI)"),
            ("tdts", "决速过渡态 (TDTS)"), ("tof", "周转频率 TOF"),
            ("tof_esm", "ESM 近似 TOF"), ("ton", "失活前 TON"),
            ("tof_t", "TOF(t)"), ("ton_t", "TON(t)"),
            ("cat_active", "活性催化剂 [Cat]"),
        ]
        self._result_labels = {}
        for i, (key, text) in enumerate(result_rows):
            lab = QLabel(text)
            lab.setStyleSheet("color:#64748B;")
            lab.setWordWrap(True)
            val = QLabel("—")
            val.setStyleSheet("font-family:Consolas;font-weight:bold;color:#1E293B;")
            r_lay.addWidget(lab, i, 0)
            r_lay.addWidget(val, i, 1)
            self._result_labels[key] = val
        right_l.addWidget(grp_res)

        grp_exp = QGroupBox("图表与导出")
        e_lay = QHBoxLayout(grp_exp)
        e_lay.setContentsMargins(10, 8, 10, 10)
        e_lay.setSpacing(6)
        self._export_buttons = []
        for text, slot in (("导出 CSV", self._export_csv),
                           ("导出 PNG", lambda: self._export("png")),
                           ("导出 SVG", lambda: self._export("svg")),
                           ("导出 PDF", lambda: self._export("pdf"))):
            b = QPushButton(text)
            b.clicked.connect(slot)
            b.setEnabled(False)
            e_lay.addWidget(b)
            self._export_buttons.append(b)
        right_l.addWidget(grp_exp)
        right_l.addStretch(1)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(scroll)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([700, 470])
        outer.addWidget(splitter)

        self._restore(_autof_example_data())
        try:
            from molstudio.core import i18n
            self._lang = "zh" if i18n._CURRENT_LANG == "zh" else "en"
        except Exception:
            self._lang = "zh"
        if self._lang == "en":
            self.set_lang("en")

    # ── 表格与输入 ─────────────────────────────────────────────────────────
    def _set_cell(self, row, col, text, editable=False, output=False):
        item = QTableWidgetItem("" if text is None else str(text))
        if editable:
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsEditable | Qt.ItemIsSelectable)
        else:
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        if output:
            item.setBackground(QColor("#F1F5F9"))
        self.table.setItem(row, col, item)

    def _refresh_step_labels(self):
        rows = self.table.rowCount()
        for k in range(rows):
            self._set_cell(k, 0, "Final" if k == rows - 1 else str(k + 1))

    def _restore(self, data):
        n = len(data["ts"])
        self.table.setRowCount(n + 1)
        for k in range(n + 1):
            self._set_cell(k, 1, data["inter"][k], editable=True)
            self._set_cell(k, 2, data["ts"][k] if k < n else "", editable=k < n)
            self._set_cell(k, 3, data["react"][k] if k < n else "", editable=k < n)
            self._set_cell(k, 4, data["prod"][k] if k < n else "", editable=k < n)
            for c in range(5, len(HEADERS)):
                self._set_cell(k, c, "", output=True)
        self._refresh_step_labels()
        self.txt_temp.setText(str(data["temp"]))
        self.combo_unit.setCurrentText(data["unit"])
        self.txt_cat.setText(str(data["cat"]))
        self.chk_dyn.setChecked(bool(data["dynamics"]))
        self.txt_time.setText(str(data["time"]))
        self.combo_time.setCurrentText(data["time_unit"])
        self.chk_deact.setChecked(bool(data["deact"]))
        self.spin_cx.setValue(int(data["cx"]))
        self.txt_td.setText(str(data["td"]))
        self.txt_rd.setText(str(data["rd"]))
        self.txt_pre.setText(str(data["pre"]))
        self.spin_cx.setRange(1, max(n, 1))

    def _snapshot(self):
        n = self.table.rowCount() - 1
        def val(row, col):
            item = self.table.item(row, col)
            return item.text().strip() if item else ""
        return {
            "inter": [val(k, 1) for k in range(n + 1)],
            "ts": [val(k, 2) for k in range(n)],
            "react": [val(k, 3) for k in range(n)],
            "prod": [val(k, 4) for k in range(n)],
            "temp": self.txt_temp.text(), "unit": self.combo_unit.currentText(),
            "cat": self.txt_cat.text(), "dynamics": self.chk_dyn.isChecked(),
            "time": self.txt_time.text(), "time_unit": self.combo_time.currentText(),
            "deact": self.chk_deact.isChecked(), "cx": self.spin_cx.value(),
            "td": self.txt_td.text(), "rd": self.txt_rd.text(),
            "pre": self.txt_pre.text(),
        }

    def _add_step(self):
        rows = self.table.rowCount()
        self.table.insertRow(rows - 1)
        k = rows - 1
        for c, v in ((1, "0"), (2, "20"), (3, ""), (4, "")):
            self._set_cell(k, c, v, editable=True)
        for c in range(5, len(HEADERS)):
            self._set_cell(k, c, "", output=True)
        self._refresh_step_labels()
        self.spin_cx.setRange(1, self.table.rowCount() - 1)

    def _remove_step(self):
        if self.table.rowCount() <= 2:
            return
        self.table.removeRow(self.table.rowCount() - 2)
        self._refresh_step_labels()
        self.spin_cx.setRange(1, self.table.rowCount() - 1)

    def _read_profile(self):
        def val(row, col):
            item = self.table.item(row, col)
            return item.text().strip() if item else ""
        n = self.table.rowCount() - 1
        inter = [float(val(k, 1)) for k in range(n + 1)]
        ts = [float(val(k, 2)) for k in range(n)]
        react = [float(val(k, 3)) if val(k, 3) else None for k in range(n)]
        prod = [float(val(k, 4)) if val(k, 4) else None for k in range(n)]
        temp = float(self.txt_temp.text().strip() or "298.15")
        cat = float(self.txt_cat.text().strip() or "1")
        deact = None
        if self.chk_deact.isChecked() and self.txt_td.text().strip():
            deact = Deactivation(
                step=int(self.spin_cx.value()),
                ts_energy=float(self.txt_td.text().strip()),
                reactant_conc=float(self.txt_rd.text().strip() or "1"))
        pre = self.txt_pre.text().strip()
        return CycleProfile(
            intermediates=inter, transition_states=ts,
            reactants=react, products=prod,
            temperature=temp, energy_unit=self.combo_unit.currentText(),
            catalyst_total=cat, deactivation=deact,
            preactivation_barrier=float(pre) if pre else None)

    # ── 计算 ───────────────────────────────────────────────────────────────
    def _calculate(self):
        try:
            profile = self._read_profile()
            st = steady_state(profile)
        except ValueError as e:
            QMessageBox.critical(self, self._t("输入错误", "Invalid input"), str(e))
            return
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, self._t("计算错误", "Calculation error"), str(e))
            return

        trajectory = None
        if self.chk_dyn.isChecked():
            try:
                t_end = (float(self.txt_time.text().strip() or "0")
                         * TIME_FACTORS[self.combo_time.currentText()])
                trajectory = simulate(profile, t_end)
                if not trajectory.success:
                    self._log("Microkinetics: integrator warning: %s"
                              % trajectory.message)
            except Exception as e:  # noqa: BLE001
                QMessageBox.critical(
                    self, self._t("计算错误", "Calculation error"), str(e))
                return

        self.profile, self.steady, self.trajectory = profile, st, trajectory
        self._fill_outputs(profile, st)
        self._display_results(profile, st, trajectory)
        self._draw(profile, st, trajectory)
        for b in self._export_buttons:
            b.setEnabled(True)
        self.badge.setText("TOF = %.3g s⁻¹" % st.tof)
        self._log("Microkinetics: ΔG_r = %.2f, δE = %.2f %s, TOF = %.4g s⁻¹, "
                  "ESM TOF = %.4g s⁻¹, TDI = I%d, TDTS = TS%d"
                  % (st.delta_g_reaction, st.delta_e, profile.energy_unit,
                     st.tof, st.esm_tof, st.tdi_step + 1, st.tdts_step + 1))
        self._save_settings()

    def _fill_outputs(self, profile, st):
        n = profile.n
        for k in range(n + 1):
            vals = ["", "", "", "", "", ""]
            label = ""
            if k < n:
                vals = [
                    "%.6g" % st.x_int[k], "%.6g" % st.x_ts[k],
                    "%.6g" % st.x_react[k] if profile.reactants[k] is not None else "",
                    "%.6g" % st.x_prod[k] if profile.products[k] is not None else "",
                    "%.6g" % st.coverages[k],
                    "%.6g" % st.potentials[k] if st.potentials[k] is not None else "",
                ]
                is_tdi = k in st.tdi_steps
                is_tdts = k in st.tdts_steps
                label = "TDI/TDTS" if is_tdi and is_tdts else (
                    "TDI" if is_tdi else ("TDTS" if is_tdts else ""))
            else:
                vals[5] = ("%.6g" % st.potentials[n]
                           if st.potentials[n] is not None else "")
            for off, text in enumerate(vals):
                self._set_cell(k, 5 + off, text, output=True)
            self._set_cell(k, 11, label, output=True)

    def _display_results(self, profile, st, trajectory):
        unit = profile.energy_unit
        def put(key, text, color=COLOR_TEXT):
            lab = self._result_labels[key]
            lab.setText(text)
            lab.setStyleSheet("font-family:Consolas;font-weight:bold;color:%s;" % color)
        put("dgr", "%.2f %s" % (st.delta_g_reaction, unit))
        put("delta_e", "%.2f %s" % (st.delta_e, unit), COLOR_PRIMARY)
        put("max_span", "%.2f %s" % (st.max_span, unit))
        put("tdi", "I%d (%.6g)" % (st.tdi_step + 1, st.x_int[st.tdi_step]),
            COLOR_SUCCESS)
        put("tdts", "TS%d (%.6g)" % (st.tdts_step + 1, st.x_ts[st.tdts_step]),
            COLOR_DANGER)
        put("tof", "%.4g s⁻¹  (%.4g min⁻¹, %.4g h⁻¹)"
            % (st.tof, st.tof * 60, st.tof * 3600), COLOR_PRIMARY)
        put("tof_esm", "%.4g s⁻¹  (×%.3f)"
            % (st.esm_tof, st.esm_tof / st.tof if st.tof else float("nan")))
        ton = ton_until_deactivation(profile, st)
        put("ton", "%.6g" % ton if ton is not None else "—")
        if trajectory is not None and trajectory.success:
            f = trajectory.final
            put("tof_t", "%.4g s⁻¹ @ %.6g s" % (f["tof"], f["time"]))
            put("ton_t", "%.6g" % f["turnovers"])
            put("cat_active", "%.6g M" % f["cat_active"])
        else:
            for key in ("tof_t", "ton_t", "cat_active"):
                put(key, "—")

    # ── 绘图 ───────────────────────────────────────────────────────────────
    def _set_canvas(self, fig):
        if self._canvas is not None:
            self._canvas_layout.removeWidget(self._canvas)
            try:
                self._canvas.close()
            except Exception:
                pass
        self._canvas = FigureCanvas(fig)
        self._canvas_layout.addWidget(self._canvas)
        self._canvas.draw()

    def _draw_placeholder(self):
        fig = Figure(figsize=(8, 9), dpi=100, facecolor="white")
        for ax in (fig.add_subplot(211), fig.add_subplot(212)):
            ax.text(0.5, 0.5, "Enter data and press Compute", ha="center",
                    va="center", fontsize=13, color=COLOR_MUTED)
            ax.set_xticks([])
            ax.set_yticks([])
            for spine in ax.spines.values():
                spine.set_visible(False)
        self._set_canvas(fig)

    def _draw(self, profile, st, trajectory):
        inter, ts = profile.intermediates, profile.transition_states
        n = profile.n
        unit = profile.energy_unit
        fig = Figure(figsize=(8, 9), dpi=100, facecolor="white")
        ax1 = fig.add_subplot(211)
        ax2 = fig.add_subplot(212)

        for k, g in enumerate(inter):
            ax1.plot([k - 0.22, k + 0.22], [g, g], color=COLOR_PRIMARY, lw=3)
            ax1.text(k, g, "I%d" % (k + 1), ha="center", va="top", fontsize=8,
                     color=COLOR_TEXT2)
        for k, t in enumerate(ts):
            ax1.plot([k + 0.28, k + 0.72], [t, t], color=COLOR_DANGER, lw=3)
            ax1.text(k + 0.5, t, "TS%d" % (k + 1), ha="center", va="bottom",
                     fontsize=8, color=COLOR_DANGER)
            ax1.plot([k + 0.22, k + 0.28], [inter[k], t], color=COLOR_TEXT2, lw=1.2)
            ax1.plot([k + 0.72, k + 0.78], [t, inter[k + 1]],
                     color=COLOR_TEXT2, lw=1.2)
            if st.potentials[k] is not None:
                ax1.plot([k - 0.12, k + 0.12], [st.potentials[k]] * 2,
                         color=COLOR_SUCCESS, lw=3)
        if st.potentials[n] is not None:
            ax1.plot([n - 0.12, n + 0.12], [st.potentials[n]] * 2,
                     color=COLOR_SUCCESS, lw=3)

        tdi_y = inter[st.tdi_step]
        tdts_x = st.tdts_step + 0.5
        tdts_y = ts[st.tdts_step]
        if st.tdts_step < st.tdi_step:
            # TDTS 位于 TDI 之前：δE 跨越两个循环，补画第二循环剖面
            shift = n + 1
            dg = st.delta_g_reaction
            for k, g in enumerate(inter):
                ax1.plot([k + shift - 0.22, k + shift + 0.22],
                         [g + dg, g + dg], color="#14b8a6", lw=2, alpha=0.55)
            for k, t in enumerate(ts):
                ax1.plot([k + shift + 0.28, k + shift + 0.72],
                         [t + dg, t + dg], color="#f59e0b", lw=2, alpha=0.55)
                ax1.plot([k + shift + 0.22, k + shift + 0.28],
                         [inter[k] + dg, t + dg], color="#94a3b8", lw=1)
                ax1.plot([k + shift + 0.72, k + shift + 0.78],
                         [t + dg, inter[k + 1] + dg], color="#94a3b8", lw=1)
            ax1.axvline(shift - 0.5, color="#CBD5E1", ls="--", lw=1.2)
            tdts_x += shift
            tdts_y += dg
        ax1.annotate("", xy=(tdts_x, tdts_y), xytext=(tdts_x, tdi_y),
                     arrowprops=dict(arrowstyle="->", color="#555555", lw=1.6))
        ax1.plot([st.tdi_step, tdts_x], [tdi_y, tdi_y], color="#555555",
                 ls="--", lw=1.2)
        ax1.text((st.tdi_step + tdts_x) / 2, tdi_y, "δE = %.2f" % st.delta_e,
                 ha="center", va="bottom", fontsize=10, fontweight="bold")
        ax1.set_xlim(-0.6, (2 * (n + 1) if st.tdts_step < st.tdi_step else n + 0.9))
        ax1.set_ylabel("G0 / G!=0 (%s)" % unit, fontsize=10)
        ax1.set_xlabel("Reaction coordinate", fontsize=10)
        ax1.set_title("Energy profile, non-standard potentials and TDI/TDTS",
                      fontsize=11)
        ax1.grid(True, axis="y", color="#E2E8F0", ls="--")
        ax1.spines["top"].set_visible(False)
        ax1.spines["right"].set_visible(False)

        if trajectory is not None and trajectory.success:
            x = [t / TIME_FACTORS[self.combo_time.currentText()]
                 for t in trajectory.times]
            ax2.plot(x, trajectory.tof, color=COLOR_PRIMARY, lw=2.2, label="TOF (s-1)")
            ax2.set_xlabel("Time (%s)" % self.combo_time.currentText(), fontsize=10)
            ax2.set_ylabel("TOF (s-1)", color=COLOR_PRIMARY, fontsize=10)
            ax2b = ax2.twinx()
            ax2b.plot(x, trajectory.turnovers, color=COLOR_SUCCESS, lw=2,
                      ls="--", label="TON")
            ax2b.plot(x, trajectory.cat_active, color="#f59e0b", lw=1.6,
                      ls=":", label="[Cat] active")
            ax2b.set_ylabel("TON / [Cat] active (M)", fontsize=10)
            ax2.set_title("Quasi-steady-state time evolution", fontsize=11)
            lines = ax2.get_lines() + ax2b.get_lines()
            ax2.legend(lines, [ln.get_label() for ln in lines], fontsize=8,
                       loc="best")
        else:
            xs = list(range(n))
            ax2.bar([x - 0.2 for x in xs], st.x_int, width=0.4,
                    color=COLOR_PRIMARY, label="XTOF(Int)")
            ax2.bar([x + 0.2 for x in xs], st.x_ts, width=0.4,
                    color=COLOR_DANGER, label="XTOF(TS)")
            ax2.set_xticks(xs)
            ax2.set_xticklabels(["step %d" % (k + 1) for k in xs])
            ax2.set_ylabel("Degree of TOF control", fontsize=10)
            ax2.set_title("Degree of TOF control (XTOF)", fontsize=11)
            ax2.legend(fontsize=8)
        ax2.grid(True, axis="y", color="#E2E8F0", ls="--")
        ax2.spines["top"].set_visible(False)
        fig.subplots_adjust(left=0.10, right=0.94, top=0.94, bottom=0.07,
                            hspace=0.32)
        self._set_canvas(fig)

    # ── 导出 ───────────────────────────────────────────────────────────────
    def _export(self, fmt):
        if self._canvas is None or self.steady is None:
            QMessageBox.information(self, self._t("提示", "Notice"),
                                    self._t("请先计算", "Please compute first"))
            return
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path, _ = save_file(
            self, self._t("导出 %s 图片" % fmt.upper(),
                          "Export %s image" % fmt.upper()),
            "microkinetics_%s.%s" % (stamp, fmt), "%s Image (*.%s)"
            % (fmt.upper(), fmt))
        if not path:
            return
        try:
            self._canvas.figure.savefig(
                path, dpi=300 if fmt == "png" else None,
                bbox_inches="tight", facecolor="white", edgecolor="none")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, self._t("导出失败", "Export failed"), str(e))
            return
        self._log("Microkinetics: exported %s -> %s" % (fmt.upper(), path))
        QMessageBox.information(
            self, self._t("导出成功", "Exported"),
            "%s\n%s\n\n%s %s" % (self._t("已保存至:", "Saved to:"), path,
                                  self._t("格式:", "Format:"), fmt.upper()))

    def _export_csv(self):
        if self.profile is None or self.steady is None:
            QMessageBox.information(self, self._t("提示", "Notice"),
                                    self._t("请先计算", "Please compute first"))
            return
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path, _ = save_file(self, self._t("导出 CSV", "Export CSV"),
                            "microkinetics_%s.csv" % stamp, "CSV (*.csv)")
        if not path:
            return
        p, st, tr = self.profile, self.steady, self.trajectory
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                wr = csv.writer(f)
                wr.writerow(["# Microkinetics (AUTOF steady-state model)"])
                wr.writerow(["temperature_K", p.temperature])
                wr.writerow(["energy_unit", p.energy_unit])
                wr.writerow(["catalyst_total_M", p.catalyst_total])
                wr.writerow(["deltaG_r", st.delta_g_reaction])
                wr.writerow(["deltaE", st.delta_e])
                wr.writerow(["max_span_ESM", st.max_span])
                wr.writerow(["TOF_s-1", st.tof])
                wr.writerow(["TOF_ESM_s-1", st.esm_tof])
                wr.writerow(["TDI_step", st.tdi_step + 1])
                wr.writerow(["TDTS_step", st.tdts_step + 1])
                ton = ton_until_deactivation(p, st)
                wr.writerow(["TON_deactivation", "" if ton is None else ton])
                wr.writerow([])
                wr.writerow(HEADERS)
                for k in range(self.table.rowCount()):
                    wr.writerow([self.table.item(k, c).text()
                                 if self.table.item(k, c) else ""
                                 for c in range(len(HEADERS))])
                if tr is not None and tr.success:
                    wr.writerow([])
                    wr.writerow(["time_s", "TOF_s-1", "TON", "cat_active_M"]
                                + ["R%d" % (i + 1) for i in range(p.n)]
                                + ["P%d" % (i + 1) for i in range(p.n)])
                    for k, t in enumerate(tr.times):
                        wr.writerow([t, tr.tof[k], tr.turnovers[k],
                                     tr.cat_active[k]]
                                    + tr.reactants[k] + tr.products[k])
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, self._t("导出失败", "Export failed"), str(e))
            return
        self._log("Microkinetics: exported CSV -> %s" % path)

    # ── 配置持久化 ─────────────────────────────────────────────────────────
    def _settings_path(self):
        from molstudio.paths import config_file
        return config_file("microkinetics_panel_settings.ini")

    def _save_settings(self):
        try:
            cfg = configparser.ConfigParser()
            cfg["microkinetics"] = {"cycle": json.dumps(self._snapshot(),
                                                      ensure_ascii=False)}
            with open(self._settings_path(), "w", encoding="utf-8") as f:
                cfg.write(f)
        except Exception:
            pass

    def _load_settings(self):
        try:
            cfg = configparser.ConfigParser()
            cfg.read(self._settings_path(), encoding="utf-8")
            raw = cfg.get("microkinetics", "cycle", fallback="")
            if raw:
                data = json.loads(raw)
                if data.get("ts") and data.get("inter"):
                    self._restore(data)
                    return
        except Exception:
            pass
        self._restore(_autof_example_data())

    # ── i18n / 生命周期 ───────────────────────────────────────────────────
    def set_lang(self, lang):
        """切换界面语言（中/英）。"""
        self._lang = "zh" if lang == "zh" else "en"
        from molstudio.ui.i18n_utils import apply_text_map
        apply_text_map(self, _LANG_EXTRA, self._lang)

    def shutdown(self):
        """关闭时保存输入数据（本面板无后台线程）。"""
        self._save_settings()
