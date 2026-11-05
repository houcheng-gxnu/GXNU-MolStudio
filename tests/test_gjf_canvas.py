# -*- coding: utf-8 -*-
"""载入 .gjf / .xyz 后必须保留真实原子序数（3D 球棍模型靠 Z 取球径/元素色）。

回归背景：``molstudio.panels.etsnocv.molcanvas.parse_gjf_file`` 曾把所有
元素的原子序数写成 0，主画布（ovcanvas）按 Z 取球径/配色，于是 .gjf 显示成
“黑色骨架、没有球”。这里同时校验解析层与主窗口两条路径。
"""

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtGui import QSurfaceFormat  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

_fmt = QSurfaceFormat()
_fmt.setSamples(0)
_fmt.setDepthBufferSize(24)
_fmt.setVersion(3, 3)
_fmt.setProfile(QSurfaceFormat.CoreProfile)
QSurfaceFormat.setDefaultFormat(_fmt)
QApplication.setAttribute(Qt.AA_DisableWindowContextHelpButton, True)

_app = None


def _pump(ms=120):
    t0 = time.time()
    while (time.time() - t0) * 1000 < ms:
        _app.processEvents()
        time.sleep(0.005)


GJF_TEXT = """%chk=water.chk
#p opt freq b3lyp/6-31g(d)

water

0 1
O 0.000000 0.000000 0.117300
H 0.000000 0.757200 -0.469200
H 0.000000 -0.757200 -0.469200
"""

XYZ_TEXT = """3
water
O 0.000000 0.000000 0.117300
H 0.000000 0.757200 -0.469200
H 0.000000 -0.757200 -0.469200
"""


def test_gjf_and_xyz_parsers_keep_atomic_numbers(tmp_path):
    from molstudio.panels.etsnocv.molcanvas import (
        get_atoms_from_any, parse_gjf_file,
    )

    gjf = tmp_path / "water.gjf"
    gjf.write_text(GJF_TEXT, encoding="utf-8")
    atoms = parse_gjf_file(str(gjf))
    assert [a[1] for a in atoms] == ["O", "H", "H"]
    assert [a[2] for a in atoms] == [8, 1, 1], "gjf 解析必须给出真实原子序数"

    xyz = tmp_path / "water.xyz"
    xyz.write_text(XYZ_TEXT, encoding="utf-8")
    atoms = get_atoms_from_any(str(xyz))
    assert [a[2] for a in atoms] == [8, 1, 1], "xyz 解析也必须给出真实原子序数"


def test_main_window_gjf_load_fills_ball_and_stick(tmp_path):
    global _app
    _app = QApplication.instance() or QApplication(sys.argv)
    _app.setStyle("Fusion")
    from molstudio.render.ovcanvas._glwidget import _atom_base_radius
    from molstudio.ui.main_window import OrbitalVisApp

    gjf = tmp_path / "water.gjf"
    gjf.write_text(GJF_TEXT, encoding="utf-8")

    w = OrbitalVisApp()
    try:
        w.resize(1400, 900)
        w.setAttribute(Qt.WA_DontShowOnScreen, True)
        w.show()
        _pump(900)
        w._load_molecule(str(gjf))
        _pump(500)

        # 2D MolCanvas：原子序数跟随真实 Z
        assert [int(a[2]) for a in (w.mol_canvas.atoms or [])] == [8, 1, 1]
        # 3D 画布：内部 (anum, charge, x, y, z) 的 anum 必须可用于取球径/颜色
        glw = w.cub_canvas.glw
        mol = glw._molecule
        assert mol and [int(a[0]) for a in mol] == [8, 1, 1]
        assert all(_atom_base_radius(int(a[0])) > 0.5 for a in mol)
        # 氧是红色、氢接近白色（不是全黑骨架）
        o_rgb = glw._atom_color(8)
        h_rgb = glw._atom_color(1)
        assert tuple(o_rgb[:3])[0] > 0.6 and tuple(o_rgb[:3])[1] < 0.4
        assert min(tuple(h_rgb[:3])) > 0.85
    finally:
        w.hide()
