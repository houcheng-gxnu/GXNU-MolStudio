# -*- coding: utf-8 -*-
"""
property_card.py — 右侧检查器顶部的「属性信息」卡片（PyQt5）
=============================================================

IDE 风格壳层的检查器需要一眼看到当前文件的分子式/分子量/能量/轨道等信息。
本模块只负责显示：数据来自 :func:`molstudio.core.quick_info.quick_info`，
由主窗口在载入文件后调用 :meth:`PropertyCard.set_info` 填入。

样式全部内嵌在控件上（QSS），不依赖全局主题；``set_lang("zh"/"en")`` 可按
静态中英对照表即时切换标题/行名/提示。
"""

from __future__ import annotations

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                             QToolButton, QVBoxLayout)

#: 卡片及子控件样式（白底、1px 浅灰边框、10px 圆角、10px 内边距）
_STYLE_SHEET = """
QFrame#PropertyCard {
    background-color: #FFFFFF;
    border: 1px solid #E5E9F0;
    border-radius: 10px;
    padding: 10px;
}
QLabel#PropertyCardTitle {
    font-size: 14px;
    font-weight: 600;
    color: #1F2937;
    border: none;
    background: transparent;
}
QLabel#PropertyCardSection {
    font-size: 12px;
    font-weight: 600;
    color: #2F6FEB;
    padding-top: 6px;
    border: none;
    background: transparent;
}
QLabel#PropertyCardKey {
    font-size: 12px;
    color: #6B7280;
    border: none;
    background: transparent;
}
QLabel#PropertyCardValue {
    font-size: 12px;
    color: #111827;
    border: none;
    background: transparent;
}
QToolButton#PropertyCardRefresh {
    border: none;
    background: transparent;
    color: #6B7280;
    font-size: 14px;
    padding: 0px 3px;
    border-radius: 6px;
}
QToolButton#PropertyCardRefresh:hover {
    color: #2F6FEB;
    background-color: #EEF3FF;
}
"""

#: 静态中→英对照表（set_lang 时按它整张卡片切换）
_LANG_ZH_EN = {
    "属性信息": "Property info",
    "刷新当前结构信息": "Refresh current structure info",
    "基本信息": "Basic info",
    "总能量": "Total energy",
    "零点能": "Zero-point energy",
    "相对自由能": "Gibbs correction",
    "HOMO": "HOMO",
    "LUMO": "LUMO",
    "能隙": "HOMO-LUMO gap",
    "分子式": "Formula",
    "分子量": "Molecular weight",
    "计算方法": "Method",
    "计算状态": "State",
    "任务时间": "Task time",
}

#: 能量类行（Hartree，%.6f）
_ENERGY_ROWS = (
    ("energy", "总能量"),
    ("zpe", "零点能"),
    ("gibbs_corr", "相对自由能"),
)

#: 轨道类行（a.u.，%.4f）
_ORBITAL_ROWS = (
    ("homo", "HOMO"),
    ("lumo", "LUMO"),
    ("gap", "能隙"),
)

#: 基本信息行（分子量 %.2f，其余原样显示）
_BASIC_ROWS = (
    ("formula", "分子式"),
    ("mol_weight", "分子量"),
    ("method", "计算方法"),
    ("state", "计算状态"),
    ("task_time", "任务时间"),
)

#: 所有展示行（key -> 中文行名），顺序即界面顺序
_ROW_DEFS = _ENERGY_ROWS + _ORBITAL_ROWS + _BASIC_ROWS

#: 空值占位符
_PLACEHOLDER = "—"

__all__ = ["PropertyCard"]


class PropertyCard(QFrame):
    """「属性信息」卡片：标题 + 刷新按钮 + 两组键值行。

    Parameters
    ----------
    parent : QWidget, optional
        父控件。

    Signals
    -------
    refreshRequested
        用户点标题栏的「↻」时发出，主窗口据此重新读取当前文件。
    """

    refreshRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PropertyCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_STYLE_SHEET)

        #: 最近一次 set_info 传入的 dict（clear 后为 None）
        self.current_info = None
        #: key -> 值 QLabel（测试/集成用）
        self.value_labels = {}
        #: key -> 行名 QLabel（set_lang 用）
        self.label_labels = {}
        self._lang = "zh"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(6)
        self.title_label = QLabel("属性信息", self)
        self.title_label.setObjectName("PropertyCardTitle")
        header.addWidget(self.title_label)
        header.addStretch(1)

        self.refresh_button = QToolButton(self)
        self.refresh_button.setObjectName("PropertyCardRefresh")
        self.refresh_button.setText("↻")
        self.refresh_button.setToolTip("刷新当前结构信息")
        self.refresh_button.setAutoRaise(True)
        self.refresh_button.setCursor(Qt.PointingHandCursor)
        self.refresh_button.clicked.connect(self._on_refresh_clicked)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)

        row = 0
        for key, _text in _ENERGY_ROWS + _ORBITAL_ROWS:
            self._add_row(grid, row, key)
            row += 1

        self.section_label = QLabel("基本信息", self)
        self.section_label.setObjectName("PropertyCardSection")
        grid.addWidget(self.section_label, row, 0, 1, 2)
        row += 1

        for key, _text in _BASIC_ROWS:
            self._add_row(grid, row, key)
            row += 1
        layout.addLayout(grid)
        layout.addStretch(1)

        self.clear()

    # ── 布局 ────────────────────────────────────────────────────────

    def _add_row(self, grid, row, key):
        """在网格里加一行「行名 + 值」。"""
        text = dict(_ROW_DEFS)[key]
        label = QLabel(text, self)
        label.setObjectName("PropertyCardKey")
        value_label = QLabel(_PLACEHOLDER, self)
        value_label.setObjectName("PropertyCardValue")
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        value_label.setWordWrap(True)
        value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        grid.addWidget(label, row, 0)
        grid.addWidget(value_label, row, 1)
        self.label_labels[key] = label
        self.value_labels[key] = value_label

    # ── 数据填充 ────────────────────────────────────────────────────

    def _format_value(self, key, value):
        """按行的类型格式化值；缺失一律显示占位符。"""
        if value is None or value == "":
            return _PLACEHOLDER
        try:
            if key in ("energy", "zpe", "gibbs_corr"):
                return "%.6f Hartree" % float(value)
            if key in ("homo", "lumo", "gap"):
                return "%.4f a.u." % float(value)
            if key == "mol_weight":
                return "%.2f" % float(value)
        except (TypeError, ValueError):
            return _PLACEHOLDER
        return str(value)

    def set_info(self, info):
        """用 ``quick_info()`` 返回的 dict 填充所有行。"""
        self.current_info = dict(info) if info else {}
        for key, value_label in self.value_labels.items():
            value_label.setText(
                self._format_value(key, self.current_info.get(key)))

    def clear(self):
        """恢复为空状态（所有值为占位符）。"""
        self.current_info = None
        for value_label in self.value_labels.values():
            value_label.setText(_PLACEHOLDER)

    # ── 语言切换 ────────────────────────────────────────────────────

    def set_lang(self, lang):
        """即时切换中/英文（``"zh"`` / ``"en"``，其余按中文处理）。"""
        english = str(lang or "").strip().lower().startswith("en")
        self._lang = "en" if english else "zh"

        def translate(text):
            return _LANG_ZH_EN.get(text, text) if english else text

        self.title_label.setText(translate("属性信息"))
        self.refresh_button.setToolTip(translate("刷新当前结构信息"))
        self.section_label.setText(translate("基本信息"))
        for key, text in _ROW_DEFS:
            self.label_labels[key].setText(translate(text))

    # ── Qt 接口 ─────────────────────────────────────────────────────

    def _on_refresh_clicked(self, *_args):
        self.refreshRequested.emit()

    def sizeHint(self):
        """检查器卡片的目标尺寸（宽 360、高约 300）。"""
        return QSize(360, 300)
