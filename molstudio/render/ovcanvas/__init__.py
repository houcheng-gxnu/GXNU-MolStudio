"""
ovcanvas — OrbitalViewer 画布可视化库
=====================================

将 OrbitalViewer 的 OpenGL 画布（等值面 + 球棍模型渲染，IboView 移植管线）
封装为可复用包。核心入口为 :class:`OVCanvas`（= :class:`CubCanvasPanel`），
可直接嵌入任意 PyQt5 布局。

典型用法::

    from molstudio.render.ovcanvas import OVCanvas

    canvas = OVCanvas()
    layout.addWidget(canvas)
    canvas.load_cube_files(["xxx_orb.cub"])     # 加载 .cub
    canvas.set_positive_color("#ff0000")        # 正相位配色
    canvas.set_negative_color("#0000ff")
    canvas.set_iso(0.03)                         # 等值面阈值
    canvas.export_image("out.png")              # 一键出图

────────────────────────────────────────────────────────────
授权声明（GPLv3 §5(a)(b)(c)）
────────────────────────────────────────────────────────────
本包是 IboView 的衍生作品（derivative work），依 GNU GPLv3 发布：

    Based on IboView (Copyright (c) 2015 Gerald Knizia), GPLv3 — modified.

移植自 IboView 的内容（其源文件均为 GPLv3）位于 `ovcanvas/_glwidget.py`：
渲染参数、着色器、原子绘制半径表与共价半径表；逐项来源标注见该文件头部
及各数据表上方注释。`_panel.py` 复刻了 IboView 的部分交互语义。

与本包独立、非 IboView 来源的内容：范德华半径（Bondi 1964）、
CPK/GaussView/Jmol/MolCanvas 配色、MolViewer 球体渐变。

重写进度与逐项判定见 ../../docs/iboview_transplant_audit.md。
注：IboView 为 GPLv3-only，本作品在仍含其代码时不得改称 "GPLv3 or later"。
────────────────────────────────────────────────────────────
"""

from ._panel import CubCanvasPanel, LimitedPopupComboBox
# OVCanvas 是面向调用方的统一入口别名
OVCanvas = CubCanvasPanel

from ._glwidget import (
    CubGLWidget,
    STYLE_NAMES,
    STYLE_DISPLAY,
    _RENDER_DEFAULTS,
    MOL_STYLE_NAMES,
    MOL_STYLE_DISPLAY,
    _GLOSS_DEFAULT,
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
    "_RENDER_DEFAULTS",
    "MOL_STYLE_NAMES",
    "MOL_STYLE_DISPLAY",
    "_GLOSS_DEFAULT",
    "MOLVIEWER_PRESETS",
    "MOLVIEWER_NAMES",
    "apply_molviewer_preset",
    "_ensure_pyopengl",
]
