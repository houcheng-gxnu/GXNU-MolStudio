# -*- coding: utf-8 -*-
"""Regression tests for the NBO table double-click workflow."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from molstudio.panels.nbo_viewer import NboPanel

_APP = QApplication.instance() or QApplication([])


def _app():
    return _APP


def _visual(kind="canonical"):
    return {
        "kind": kind,
        "direct": kind != "canonical",
        "renderable": True,
        "source": "source.fchk",
        "orbital": "6",
        "mo_type": "Alpha",
        "mo_num": 6,
        "nbo_id": 10,
        "display": "AMO 6 approx.",
    }


def test_canonical_nbo_row_double_click_still_requests_visualization():
    _app()
    panel = NboPanel()
    captured = []
    panel._visualize_visual = lambda visual: captured.append(visual)
    try:
        panel._render_nbo_table({
            "nbo_overview": [{
                "nbo_id": 10, "type": "LP", "atoms_str": "O2",
                "occupancy": 1.9, "energy": -0.2,
                "type_label": "LP", "visual": _visual(),
            }]
        })
        panel._on_nbo_double_click(0, 5)
        assert len(captured) == 1
        assert captured[0]["kind"] == "canonical"
    finally:
        panel.close()


def test_dual_atom_e2_row_double_click_still_requests_visualization():
    _app()
    panel = NboPanel()
    captured = []
    panel._visualize_dual = lambda visuals: captured.extend(visuals)
    try:
        panel._render_e2_table({"cross_e2_details": [{
            "idx": 1, "e2": 4.2, "stars": "*",
            "donor_label": "LP(2)O2", "acceptor_label": "BD*(2)C1-O2",
            "visual_donor": _visual(), "visual_acceptor": _visual(),
        }]})
        panel._on_e2_double_click(0, 5)
        assert len(captured) == 2
    finally:
        panel.close()


def test_source_label_names_savenbo_storage(tmp_path):
    """saveNBO 的 fchk 里存的就是 NBO，来源行必须说清楚 MO 号的来历。"""
    _app()
    panel = NboPanel()
    fchk = tmp_path / "test_saveNBO2.fchk"
    fchk.write_text("", encoding="utf-8")
    try:
        panel._on_analysis_done({
            "nbo_overview": [], "cross_e2_details": [],
            "single_atom_mode": False, "full_mode": True,
            "visual_source": {"kind": "saveNBO", "direct": True,
                              "fchk": str(fchk)},
            "atom1": None, "atom2": None,
        }, "")
        text = panel.lbl_source.text()
        assert "saveNBO" in text and "test_saveNBO2.fchk" in text
        assert "NBO" in text
    finally:
        panel.close()


def test_source_label_warns_canonical_approximation(tmp_path):
    _app()
    panel = NboPanel()
    fchk = tmp_path / "plain.fchk"
    fchk.write_text("", encoding="utf-8")
    try:
        panel._on_analysis_done({
            "nbo_overview": [], "cross_e2_details": [],
            "single_atom_mode": False, "full_mode": True,
            "visual_source": {"kind": "canonical", "fchk": str(fchk)},
            "atom1": None, "atom2": None,
        }, "")
        text = panel.lbl_source.text()
        assert "近似" in text or "approximation" in text.lower()
        panel.reset_view_state()
        assert "载入" in panel.lbl_source.text() or \
            "load" in panel.lbl_source.text().lower()
    finally:
        panel.close()
