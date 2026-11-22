# -*- coding: utf-8 -*-
"""Softbox Gloss 一键样式与高精度抗锯齿的静态契约。"""

from molstudio.render.ovcanvas._glwidget import FRAG_POST, _GLSL_COMMON
from molstudio.render.ovcanvas._looks import LOOK_ORDER, look_state


def test_reference_gloss_look_is_registered():
    assert "reference-gloss" in LOOK_ORDER
    state = look_state("reference-gloss")
    assert state is not None
    assert state["env_on"] == 1
    assert state["env_softbox"] == 1
    assert state["linear_space"] is True
    assert state["bg"] == [1.0, 1.0, 1.0, 1.0]
    assert state["orb_alpha_mod"] == 0.0
    assert state["phase_pos"] == [0.86, 0.035, 0.075]
    assert state["phase_neg"] == [0.035, 0.105, 0.80]


def test_reference_gloss_uses_high_quality_supersampling():
    state = look_state("reference-gloss")
    assert state["post"][0] is True
    assert state["post"][1] == 3.0
    assert "s / 16.0" in FRAG_POST
    assert "u_EnvSoftbox" in _GLSL_COMMON
    assert "lp_soft_oval" in _GLSL_COMMON


def test_lemon_orbital_look_uses_reference_palette():
    state = look_state("lemon-orbital")
    assert state is not None
    assert state["bg"] == [1.0, 1.0, 1.0, 1.0]
    assert state["phase_pos"] == [0.96, 0.90, 0.36]
    assert state["phase_neg"] == [0.50, 0.84, 0.46]
    assert state["carbon"] == [0.36, 0.36, 0.38]
    assert state["bond_color"] == [0.72, 0.72, 0.74]
    assert state["orb_opacity"] == 0.80
    assert state["orb_spec_mul"] == 0.25
    assert state["light_count"] == 1
    assert state["post"][1] == 3.0
