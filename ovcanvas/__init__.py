"""
ovcanvas — OrbitalViewer 画布可视化库
=====================================

将 OrbitalViewer 的 OpenGL 画布（等值面 + 球棍模型渲染，IboView 移植管线）
封装为可复用包。核心入口为 :class:`OVCanvas`（= :class:`CubCanvasPanel`），
可直接嵌入任意 PyQt5 布局。

典型用法::

    from ovcanvas import OVCanvas

    canvas = OVCanvas()
    layout.addWidget(canvas)
    canvas.load_cube_files(["xxx_orb.cub"])     # 加载 .cub
    canvas.set_positive_color("#ff0000")        # 正相位配色
    canvas.set_negative_color("#0000ff")
    canvas.set_iso(0.03)                         # 等值面阈值
    canvas.export_image("out.png")              # 一键出图

本文件部分渲染参数 / 着色器 / 原子表逐字移植自 IboView
(Copyright (c) 2015 Gerald Knizia, GPLv3)。本项目作为 IboView 衍生作品，
依 GNU GPLv3 发布。
"""

from ._panel import CubCanvasPanel, LimitedPopupComboBox
# OVCanvas 是面向调用方的统一入口别名
OVCanvas = CubCanvasPanel

from ._glwidget import (
    CubGLWidget,
    STYLE_NAMES,
    STYLE_DISPLAY,
    IBOVIEW_DEFAULTS,
    MOL_STYLE_NAMES,
    MOL_STYLE_DISPLAY,
    SHININESS_PRESETS,
    SHININESS_DEFAULT,
    _ensure_pyopengl,
)

from ._colorwheel import ColorWheelWidget

from ._molviewer_style import (
    MOLVIEWER_PRESETS,
    MOLVIEWER_NAMES,
    apply_molviewer_preset,
)

__all__ = [
    "OVCanvas",
    "CubCanvasPanel",
    "LimitedPopupComboBox",
    "CubGLWidget",
    "ColorWheelWidget",
    "STYLE_NAMES",
    "STYLE_DISPLAY",
    "IBOVIEW_DEFAULTS",
    "MOL_STYLE_NAMES",
    "MOL_STYLE_DISPLAY",
    "SHININESS_PRESETS",
    "SHININESS_DEFAULT",
    "MOLVIEWER_PRESETS",
    "MOLVIEWER_NAMES",
    "apply_molviewer_preset",
    "_ensure_pyopengl",
]
