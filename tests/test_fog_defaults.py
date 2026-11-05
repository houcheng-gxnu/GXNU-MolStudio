# -*- coding: utf-8 -*-
"""景深雾化默认状态回归。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from molstudio.render.ovcanvas._glwidget import CubGLWidget
from molstudio.render.ovcanvas._panel import (
    _CYLVVIEW_STYLE,
    _HOUKMOL2D_STYLE,
    _HOUKMOL3D_STYLE,
    _HOUKMOL_STYLE,
    _IBOVIEW_STYLE,
    _IQMOL_STYLE,
    _MOLSTUDIO_STYLE,
    _SOBART_STYLE,
    _VESTA_STYLE,
)


def test_all_one_click_styles_enable_depth_fog():
    styles = {
        "sob-art": _SOBART_STYLE,
        "IBOview": _IBOVIEW_STYLE,
        "HoukMol": _HOUKMOL_STYLE,
        "HoukMol3d": _HOUKMOL3D_STYLE,
        "2D flat": _HOUKMOL2D_STYLE,
        "IQmol": _IQMOL_STYLE,
        "MolStudio": _MOLSTUDIO_STYLE,
        "CYLview": _CYLVVIEW_STYLE,
        "VESTA": _VESTA_STYLE,
    }
    disabled = [name for name, state in styles.items() if not state.get("fade")]
    assert not disabled, f"以下一键样式仍关闭景深雾化：{disabled}"


def test_style_reset_restores_depth_fog():
    app = QApplication.instance() or QApplication([])
    glw = CubGLWidget()
    try:
        glw.set_fade_enabled(False)
        glw.reset_molviewer_style()
        assert glw._fade_enabled
        app.processEvents()
    finally:
        glw.close()
        glw.deleteLater()
        app.processEvents()
