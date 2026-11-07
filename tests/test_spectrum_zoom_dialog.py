# -*- coding: utf-8 -*-
"""Regression: the zoom dialog must not open with a blank plot.

``show_scaled(True)`` used to run *before* ``dlg.exec_()``.  At that point the
QScrollArea viewport had not been laid out yet (about 100x30), so the
1872x1053 source pixmap was scaled into a nearly zero-sized placeholder and
the dialog appeared empty.  The first fit now happens on the first turn of
the dialog's event loop, after it has been mapped.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt5.QtGui import QColor, QPixmap  # noqa: E402
from PyQt5.QtWidgets import QApplication, QLabel  # noqa: E402

from molstudio.panels import spectrum_panel as sp  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_zoom_dialog_shows_a_full_size_plot(app, monkeypatch):
    panel = sp.SpectrumPanel()
    source = QPixmap(1872, 1053)
    source.fill(QColor("white"))
    panel.plot_view._source = source
    panel.plot_view._path = "fake.png"
    assert panel.plot_view.has_plot()

    seen = {}

    def fake_exec(dlg):
        dlg.show()
        for _ in range(8):
            app.processEvents()
        pixmaps = [lbl.pixmap() for lbl in dlg.findChildren(QLabel)
                   if lbl.pixmap() is not None and not lbl.pixmap().isNull()]
        seen["sizes"] = [(p.width(), p.height()) for p in pixmaps]
        dlg.reject()
        return 0

    monkeypatch.setattr(sp.QDialog, "exec_", fake_exec)
    panel._zoom_plot()

    assert seen["sizes"], "zoom dialog contains no pixmap at all"
    biggest = max(w * h for w, h in seen["sizes"])
    assert biggest > 800 * 450, (
        "plot was scaled into the unmapped viewport: %r" % seen["sizes"])
