# -*- coding: utf-8 -*-
"""MolStudio 光谱渲染与 Multiwfn 出图的一致性回归测试。

覆盖此前发现的问题：离散跃迁线（含虚频负波数、横轴范围外的模式）会把
Matplotlib 的横轴撑大，导致 MolStudio 图与 Multiwfn 原生图横轴范围不一致。
render 之后 ``spectra._LAST_RENDER_LIMITS`` 记录实际横轴，用来断言这一点。

真正的数值一致性（曲线数据 == Multiwfn 导出的 spectrum_curve.txt、FWHM、
频率校正因子）由 ``_dev/probes/verify_spectrum_vs_multiwfn.py`` 端到端验证，
因为那需要本机 Multiwfn 和真实 Gaussian 输出。
"""
import os

import pytest

from molstudio.core import spectra


def _render(tmp_path, curve, transitions, kind_key="ir"):
    pytest.importorskip("matplotlib")
    kind = spectra.get_spectrum_kind(kind_key)
    out = str(tmp_path / "plot.png")
    spectra._render_curve(curve, kind, out, transitions=transitions)
    assert os.path.isfile(out)
    return spectra._LAST_RENDER_LIMITS


def test_render_clamps_axis_and_drops_out_of_range_transitions(tmp_path):
    # 400..4000 cm^-1，步长 10
    curve = [(400.0 + i * 10.0, float(i)) for i in range(361)]
    transitions = [
        (-1479.0, 500.0),   # 虚频：必须裁掉，否则横轴会扩到 -1500
        (500.0, 30.0),
        (3000.0, 20.0),
        (4200.0, 5.0),      # 超出上限：必须裁掉
    ]
    limits = _render(tmp_path, curve, transitions)
    assert limits[0] == pytest.approx(400.0)
    assert limits[1] == pytest.approx(4000.0)
    assert limits[2] == len(transitions)
    assert limits[3] == 2


def test_render_without_transitions_fits_curve(tmp_path):
    curve = [(150.0 + i, 1.0) for i in range(251)]  # 150..400 nm
    limits = _render(tmp_path, curve, [], kind_key="uvvis")
    assert limits[0] == pytest.approx(150.0)
    assert limits[1] == pytest.approx(400.0)
    assert limits[2] == 0
    assert limits[3] == 0


def test_vibrational_axis_keeps_multiwfn_high_to_low_direction(tmp_path):
    # Multiwfn 导出的振动谱曲线是 4000 -> 0 cm^-1，原生图左高右低；
    # 若强制 set_xlim(min, max) 会把谱图左右镜像。
    curve = [(4000.0 - i * 10.0, float(i)) for i in range(401)]
    _render(tmp_path, curve, [], kind_key="ir")
    assert spectra._LAST_RENDER_XLIM == pytest.approx((4000.0, 0.0))


def test_electronic_axis_stays_ascending(tmp_path):
    curve = [(150.0 + i, 1.0) for i in range(251)]
    _render(tmp_path, curve, [], kind_key="uvvis")
    assert spectra._LAST_RENDER_XLIM == pytest.approx((150.0, 400.0))


def test_reversed_range_from_multiwfn_option3_is_honoured(tmp_path):
    # 文章第 4 节：选项 3 可写 1000,0,100 主动反转横轴。
    curve = [(1000.0 - i * 5.0, 1.0) for i in range(201)]
    _render(tmp_path, curve, [], kind_key="vcd")
    assert spectra._LAST_RENDER_XLIM == pytest.approx((1000.0, 0.0))


def test_phosphorescence_curve_is_normalised_before_plotting(tmp_path):
    pytest.importorskip("matplotlib")
    kind = spectra.get_spectrum_kind("phosphorescence")
    curve = [(400.0 + i, float(i)) for i in range(101)]
    out = str(tmp_path / "phos.png")
    spectra._render_curve(curve, kind, out, transitions=[])
    assert os.path.isfile(out)
    assert spectra._LAST_RENDER_LIMITS[:2] == (400.0, 500.0)
