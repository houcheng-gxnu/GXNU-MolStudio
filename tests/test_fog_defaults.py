# -*- coding: utf-8 -*-
"""景深雾化默认状态回归。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from molstudio.render.ovcanvas._glwidget import CubGLWidget
from molstudio.render.ovcanvas._looks import LOOK_PRESETS
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


def test_all_one_click_styles_disable_depth_fog_by_default():
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
    enabled = [name for name, state in styles.items() if state.get("fade")]
    assert not enabled, f"以下一键样式仍开启景深雾化：{enabled}"
    look_enabled = [name for name, item in LOOK_PRESETS.items()
                    if item["state"].get("fade")]
    assert not look_enabled, f"以下出图观感仍开启景深雾化：{look_enabled}"


def test_style_reset_keeps_depth_fog_disabled():
    app = QApplication.instance() or QApplication([])
    glw = CubGLWidget()
    try:
        glw.set_fade_enabled(True)
        glw.reset_molviewer_style()
        assert not glw._fade_enabled
        app.processEvents()
    finally:
        glw.close()
        glw.deleteLater()
        app.processEvents()
