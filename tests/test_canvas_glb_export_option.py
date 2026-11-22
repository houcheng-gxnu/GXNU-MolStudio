# -*- coding: utf-8 -*-
"""Canvas export dropdown → PowerPoint GLB for surface-only orbital scenes."""
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from molstudio.core.marching_cubes import IsoSurface
from molstudio.core.molecule_export import validate_glb
from molstudio.core.ppt3d_options import Ppt3dOptions
from molstudio.render.ovcanvas._panel import _EXPORT_MENU_ITEMS
import molstudio.ui.main_window as main_window


def _tetra_surface():
    surf = IsoSurface()
    surf.vertices = np.array([
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ], dtype=np.float32)
    surf.normals = np.array([
        [-0.577, -0.577, -0.577],
        [0.577, -0.577, -0.577],
        [-0.577, 0.577, -0.577],
        [-0.577, -0.577, 0.577],
    ], dtype=np.float32)
    surf.indices = np.array([
        0, 2, 1, 0, 1, 3, 0, 3, 2, 1, 2, 3,
    ], dtype=np.uint32)
    surf.colors = None
    return surf


def test_export_dropdown_contains_glb():
    assert ("glb", "GLB") in _EXPORT_MENU_ITEMS


def test_surface_only_canvas_exports_valid_glb(tmp_path, monkeypatch):
    surf = _tetra_surface()
    glw = SimpleNamespace(
        _pos_surf=surf,
        _neg_surf=None,
        _sp={"opacity": 0.8, "roughness": 0.35},
        _pc=(0.96, 0.90, 0.36),
        _nc=(0.50, 0.84, 0.46),
        _orbital_recs=[{"cube": "demo.cub"}],
        _surf_vcolor=False,
        _aicd_surf=None,
        _aicd_show=False,
    )
    target = tmp_path / "orbital.glb"

    class FakeWindow:
        _lang = "en"
        cub_canvas = SimpleNamespace(glw=glw)
        var_path = SimpleNamespace(text=lambda: "")
        report = None

        def _ppt3d_save_path(self, _stem, _start_dir=None):
            return str(target)

        @staticmethod
        def _ppt3d_canvas_options(_symbols):
            return {
                "surfaces": [],
                "roughness": 0.35,
                "native_pbr": True,
                "high_detail": True,
                "bake_ao": True,
                "ao_rays": 8,
            }

        @staticmethod
        def _write_ppt3d_esp_legend(*_args, **_kwargs):
            return None

        def _ppt3d_report(self, path, options, surfaces, legend,
                          cell_box, source="", note=None):
            self.report = (path, options, surfaces, source, note)

    from molstudio.ui import ppt3d_options_widget
    monkeypatch.setattr(
        ppt3d_options_widget.Ppt3dExportDialog, "get_options",
        staticmethod(lambda *_a, **_kw: Ppt3dOptions(include_surfaces=True)))
    monkeypatch.setattr(main_window, "QApplication", SimpleNamespace(
        setOverrideCursor=lambda *_a: None,
        restoreOverrideCursor=lambda *_a: None,
    ))

    window = FakeWindow()
    main_window.OrbitalVisApp._export_canvas_surfaces_ppt3d(window)

    assert target.is_file()
    info = validate_glb(str(target))
    assert len(info["meshes"]) >= 1
    assert window.report is not None
    assert len(window.report[2]) == 1
