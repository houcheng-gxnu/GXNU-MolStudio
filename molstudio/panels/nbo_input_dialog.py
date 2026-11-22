# -*- coding: utf-8 -*-
"""Editable Gaussian NBO input generator dialog."""

from __future__ import annotations

import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from molstudio.core.nbo_input import build_nbo_input

TEXT = {
    "zh": {
        "title": "Gaussian NBO 输入生成器",
        "source": "结构 / route 来源",
        "placeholder": "载入 .gjf 可直接编辑，也可从 .log/.fchk 继承最终结构",
        "load": "载入 GJF…",
        "mode": "NBO 输出",
        "plot": "NBO plot：生成 .31–.40（推荐）",
        "save_nbo": "saveNBO：把 NBO 写入 chk",
        "apply_template": "套用 NBO 模板",
        "preview": "输入文件（可直接编辑）",
        "hint": "载入 GJF 后会替换计算/布居关键词并保留原方法和几何。",
        "submit_hint": (
            "提交方式：用 g16 命令行或 GaussView 跑这份 gjf（saveNBO 之后还要"
            " formchk 转 fchk）。主窗口「高斯计算」页会按自己的方法/基组字段"
            "重建 route——pop 关键词会被接住，但方法/基组未必与这份输入一致。"),
        "copy": "复制",
        "save_as": "另存为 GJF…",
        "close": "关闭",
        "need_source": "请先载入 .gjf 或其他结构/输出文件",
        "loaded": "已载入：{name}",
        "failed": "生成失败：{err}",
        "saved": "已保存：{path}",
        "save_title": "保存 Gaussian NBO 输入",
        "load_title": "选择 GJF 或已有计算结果",
    },
    "en": {
        "title": "Gaussian NBO Input Generator",
        "source": "Structure / route source",
        "placeholder": (
            "Load a .gjf to edit directly, or inherit a final geometry from "
            ".log/.fchk"
        ),
        "load": "Load GJF…",
        "mode": "NBO output",
        "plot": "NBO plot: emit .31–.40 (recommended)",
        "save_nbo": "saveNBO: store NBOs in checkpoint",
        "apply_template": "Apply NBO template",
        "preview": "Input file (editable)",
        "hint": (
            "Loading a GJF preserves its method and geometry while replacing "
            "calculation and population keywords."
        ),
        "submit_hint": (
            "Submit this GJF with the g16 command line or GaussView (saveNBO "
            "also needs formchk afterwards). The Gaussian page rebuilds the "
            "route from its own method/basis fields: the pop keyword is kept, "
            "but the level of theory may differ from this input."
        ),
        "copy": "Copy",
        "save_as": "Save GJF As…",
        "close": "Close",
        "need_source": "Load a .gjf or another structure/output file first",
        "loaded": "Loaded: {name}",
        "failed": "Could not build input: {err}",
        "saved": "Saved: {path}",
        "save_title": "Save Gaussian NBO input",
        "load_title": "Choose a GJF or existing result",
    },
}


class NboInputDialog(QDialog):
    """Load a Gaussian input, build an NBO-ready template, and edit it."""

    def __init__(self, initial_source="", initial_fchk="", lang="zh",
                 parent=None):
        super().__init__(parent)
        self.lang = "en" if str(lang).lower().startswith("en") else "zh"
        self.initial_fchk = initial_fchk or ""
        self._initial_source = (
            os.path.abspath(initial_source) if initial_source else "")
        self.source_path = ""
        self._template_stem = ""
        self._build_ui()
        self._apply_lang()
        if initial_source:
            self.load_source(initial_source)

    def _t(self, key, **fmt):
        text = TEXT.get(self.lang, TEXT["zh"]).get(key, key)
        return text.format(**fmt) if fmt else text

    def _build_ui(self):
        self.setMinimumSize(820, 650)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        source_row = QHBoxLayout()
        self.lbl_source = QLabel()
        source_row.addWidget(self.lbl_source)
        self.edit_source = QLineEdit()
        self.edit_source.setReadOnly(True)
        source_row.addWidget(self.edit_source, 1)
        self.btn_load = QPushButton()
        self.btn_load.clicked.connect(self._choose_source)
        source_row.addWidget(self.btn_load)
        root.addLayout(source_row)

        mode_row = QHBoxLayout()
        self.lbl_mode = QLabel()
        mode_row.addWidget(self.lbl_mode)
        self.combo_mode = QComboBox()
        self.combo_mode.addItem("", "plot")
        self.combo_mode.addItem("", "saveNBO")
        mode_row.addWidget(self.combo_mode)
        self.btn_apply = QPushButton()
        self.btn_apply.clicked.connect(self._apply_template)
        mode_row.addWidget(self.btn_apply)
        mode_row.addStretch(1)
        root.addLayout(mode_row)

        self.lbl_preview = QLabel()
        root.addWidget(self.lbl_preview)
        self.editor = QPlainTextEdit()
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.editor.setStyleSheet(
            "QPlainTextEdit{font-family:Consolas,'Courier New',monospace;"
            "font-size:9.5pt;background:#FFFFFF;}")
        root.addWidget(self.editor, 1)

        self.lbl_hint = QLabel()
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet("color:#66758D;")
        root.addWidget(self.lbl_hint)

        self.lbl_submit = QLabel()
        self.lbl_submit.setWordWrap(True)
        self.lbl_submit.setStyleSheet(
            "color:#8A5A00;background:#FFF7E6;border:1px solid #F3D9A4;"
            "border-radius:4px;padding:5px 8px;")
        root.addWidget(self.lbl_submit)

        buttons = QHBoxLayout()
        self.btn_copy = QPushButton()
        self.btn_copy.clicked.connect(self._copy)
        self.btn_save = QPushButton()
        self.btn_save.clicked.connect(self._save_as)
        self.btn_close = QPushButton()
        self.btn_close.clicked.connect(self.accept)
        buttons.addWidget(self.btn_copy)
        buttons.addWidget(self.btn_save)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_close)
        root.addLayout(buttons)

        # 换输出方式 = 换模板：直接重生成，不用再点一次「套用 NBO 模板」。
        # 连接放在控件都建好之后，避免 addItem 期间的早期信号。
        self.combo_mode.currentIndexChanged.connect(self._on_mode_changed)

    def _apply_lang(self):
        self.setWindowTitle(self._t("title"))
        self.lbl_source.setText(self._t("source"))
        self.edit_source.setPlaceholderText(self._t("placeholder"))
        self.btn_load.setText(self._t("load"))
        self.lbl_mode.setText(self._t("mode"))
        self.combo_mode.setItemText(0, self._t("plot"))
        self.combo_mode.setItemText(1, self._t("save_nbo"))
        self.btn_apply.setText(self._t("apply_template"))
        self.lbl_preview.setText(self._t("preview"))
        self.lbl_hint.setText(self._t("hint"))
        self.lbl_submit.setText(self._t("submit_hint"))
        self.btn_copy.setText(self._t("copy"))
        self.btn_save.setText(self._t("save_as"))
        self.btn_close.setText(self._t("close"))

    def _choose_source(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self._t("load_title"),
            os.path.dirname(self.source_path) if self.source_path else "",
            "Gaussian input (*.gjf *.com);;"
            "Existing calculation (*.log *.out *.fchk *.fch);;"
            "All files (*.*)")
        if path:
            self.load_source(path)

    def _same_stem_fchk(self, path):
        ext = os.path.splitext(path)[1].lower()
        if ext in (".fchk", ".fch"):
            return ""
        candidate = os.path.splitext(path)[0] + ".fchk"
        return candidate if os.path.isfile(candidate) else ""

    def load_source(self, path):
        self.source_path = os.path.abspath(path)
        self.edit_source.setText(self.source_path)
        fchk = self._same_stem_fchk(self.source_path)
        if not fchk and self.source_path == self._initial_source:
            fchk = self.initial_fchk
        self._generate(fchk)

    def _generate(self, fchk=None):
        if not self.source_path:
            self.lbl_hint.setText(self._t("need_source"))
            return False
        source_stem = os.path.splitext(os.path.basename(self.source_path))[0]
        mode = str(self.combo_mode.currentData() or "plot")
        suffix = "_NBOplot" if mode == "plot" else "_saveNBO"
        self._template_stem = source_stem + suffix
        try:
            text, _meta = build_nbo_input(
                self.source_path, fchk, self._template_stem, mode=mode)
        except Exception as exc:                         # noqa: BLE001
            self.lbl_hint.setText(self._t("failed", err=exc))
            return False
        self.editor.setPlainText(text)
        self.lbl_hint.setText(self._t(
            "loaded", name=os.path.basename(self.source_path)))
        return True

    def _apply_template(self):
        if not self.source_path:
            self.lbl_hint.setText(self._t("need_source"))
            return
        fchk = self._same_stem_fchk(self.source_path)
        if not fchk and self.source_path == self._initial_source:
            fchk = self.initial_fchk
        self._generate(fchk)

    def _on_mode_changed(self, _index=0):
        """输出方式一变就重生成模板（有源文件时）。"""
        if not self.source_path:
            return
        self._apply_template()

    def _copy(self):
        QApplication.clipboard().setText(self.editor.toPlainText())

    def _adapt_output_refs(self, text, old_stem, new_stem):
        if not old_stem or old_stem == new_stem:
            return text
        return (
            text.replace("%chk=" + old_stem + ".chk",
                         "%chk=" + new_stem + ".chk")
            .replace("$NBO plot file=" + old_stem + " $END",
                     "$NBO plot file=" + new_stem + " $END")
        )

    def _save_as(self):
        if not self.source_path:
            self.lbl_hint.setText(self._t("need_source"))
            return
        suggested = os.path.join(
            os.path.dirname(self.source_path), self._template_stem + ".gjf")
        path, _ = QFileDialog.getSaveFileName(
            self, self._t("save_title"), suggested,
            "Gaussian input (*.gjf *.com);;All files (*.*)")
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".gjf"
        new_stem = os.path.splitext(os.path.basename(path))[0]
        text = self._adapt_output_refs(
            self.editor.toPlainText(), self._template_stem, new_stem)
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
        except OSError as exc:
            self.lbl_hint.setText(self._t("failed", err=exc))
            return
        self.editor.setPlainText(text)
        self._template_stem = new_stem
        self.lbl_hint.setText(self._t("saved", path=path))


__all__ = ["NboInputDialog"]
