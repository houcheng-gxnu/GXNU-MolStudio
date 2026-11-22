# -*- coding: utf-8 -*-
"""Offscreen tests for the editable NBO input generator dialog."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QFileDialog

from molstudio.panels import nbo_input_dialog as mod
from molstudio.panels.nbo_input_dialog import NboInputDialog

_APP = None


def _app():
    """Keep a module-level reference: a discarded QApplication is GC'd and the
    next QWidget construction aborts the process."""
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def _write_gjf(tmp_path):
    path = tmp_path / "source.gjf"
    path.write_text(
        "%nprocshared=4\n"
        "%mem=6GB\n"
        "#p b3lyp/def2svp opt\n"
        "\n"
        "water\n"
        "\n"
        "0 1\n"
        "O 0.0 0.0 0.1\n"
        "H 0.0 0.75 -0.5\n"
        "H 0.0 -0.75 -0.5\n"
        "\n",
        encoding="utf-8",
    )
    return path


def test_dialog_loads_gjf_and_offers_editable_input(tmp_path):
    _app()
    source = _write_gjf(tmp_path)
    dialog = NboInputDialog(str(source), lang="zh")
    try:
        text = dialog.editor.toPlainText()
        assert "pop=nboread" in text
        assert "$NBO plot file=source_NBOplot $END" in text
        dialog.editor.setPlainText(text + "# user edit\n")
        assert dialog.editor.isReadOnly() is False
    finally:
        dialog.close()


def test_dialog_can_switch_to_save_nbo(tmp_path):
    _app()
    source = _write_gjf(tmp_path)
    dialog = NboInputDialog(str(source), lang="zh")
    try:
        dialog.combo_mode.setCurrentIndex(1)
        dialog._apply_template()
        text = dialog.editor.toPlainText()
        assert "pop=saveNBO" in text
        assert "$NBO" not in text
    finally:
        dialog.close()


def test_switching_mode_regenerates_template_immediately(tmp_path):
    """换输出方式就该换模板，不需要用户再点一次「套用 NBO 模板」。"""
    _app()
    source = _write_gjf(tmp_path)
    dialog = NboInputDialog(str(source), lang="zh")
    try:
        assert "pop=nboread" in dialog.editor.toPlainText()
        dialog.combo_mode.setCurrentIndex(1)          # → saveNBO
        text = dialog.editor.toPlainText()
        assert "pop=saveNBO" in text
        assert "$NBO" not in text
        dialog.combo_mode.setCurrentIndex(0)          # → 回到 plot
        assert "pop=nboread" in dialog.editor.toPlainText()
    finally:
        dialog.close()


def test_dialog_explains_submission_path(tmp_path):
    """生成器必须点明「用 g16 命令行提交」，因为高斯计算页会重建 route。"""
    _app()
    source = _write_gjf(tmp_path)
    dialog = NboInputDialog(str(source), lang="zh")
    try:
        hint = dialog.lbl_submit.text()
        assert "g16" in hint
        assert "pop" in hint
    finally:
        dialog.close()


def test_dialog_saves_edited_text_and_updates_default_references(
        tmp_path, monkeypatch):
    _app()
    source = _write_gjf(tmp_path)
    output = tmp_path / "edited.gjf"
    dialog = NboInputDialog(str(source), lang="zh")
    try:
        monkeypatch.setattr(
            mod.QFileDialog, "getSaveFileName",
            lambda *_args, **_kwargs: (str(output), "Gaussian input (*.gjf)"))
        dialog._save_as()
        text = output.read_text(encoding="utf-8")
        assert "%chk=edited.chk" in text
        assert "$NBO plot file=edited $END" in text
    finally:
        dialog.close()


def test_dialog_english_mode_has_nbo_entry(tmp_path):
    _app()
    source = _write_gjf(tmp_path)
    dialog = NboInputDialog(str(source), lang="en")
    try:
        assert dialog.windowTitle() == "Gaussian NBO Input Generator"
        assert dialog.btn_load.text() == "Load GJF…"
    finally:
        dialog.close()
