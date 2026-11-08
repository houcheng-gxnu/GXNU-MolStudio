# -*- coding: utf-8 -*-
"""PowerPoint GLB export must carry a real 3D unit-cell frame when asked."""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from molstudio.core.molecule_export import export_glb  # noqa: E402

WATER = ["O", "H", "H"]
COORDS = [[0.0, 0.0, 0.0], [0.76, 0.59, 0.0], [-0.76, 0.59, 0.0]]
CORNERS = [[x, y, z] for x in (0.0, 4.0) for y in (0.0, 4.0)
           for z in (0.0, 4.0)]


def _gltf(path):
    raw = Path(path).read_bytes()
    magic, version, _total = struct.unpack("<III", raw[:12])
    assert magic == 0x46546C67 and version == 2
    length, kind = struct.unpack("<II", raw[12:20])
    assert kind == 0x4E4F534A
    return json.loads(raw[20:20 + length].decode("utf-8").rstrip(" "))


def test_without_cell_box(tmp_path):
    out = tmp_path / "plain.glb"
    export_glb(out, WATER, COORDS, title="water")
    gltf = _gltf(out)
    assert gltf["extras"]["chemistry"]["cell_box"] is False
    assert not any(m.get("name") == "Unit cell" for m in gltf["materials"])


def test_with_cell_box(tmp_path):
    out = tmp_path / "boxed.glb"
    export_glb(out, WATER, COORDS, title="water",
               cell_box={"corners": CORNERS, "radius": 0.06,
                         "color": "#123456"})
    gltf = _gltf(out)
    assert gltf["extras"]["chemistry"]["cell_box"] is True
    names = [m.get("name") for m in gltf["materials"]]
    assert "Unit cell" in names
    # 12 edges x 8 sides x 2 triangles -> its own primitive
    box_material = names.index("Unit cell")
    box_primitives = [p for p in gltf["meshes"][0]["primitives"]
                      if p["material"] == box_material]
    assert len(box_primitives) == 1
    accessor = gltf["accessors"][box_primitives[0]["indices"]]
    assert accessor["count"] == 12 * 8 * 6
    for prim in gltf["meshes"][0]["primitives"]:
        for index in prim["attributes"].values():
            view = gltf["bufferViews"][gltf["accessors"][index]["bufferView"]]
            assert view["byteOffset"] + view["byteLength"] <= gltf["buffers"][0]["byteLength"]


def test_cell_box_survives_native_pbr_and_unlit(tmp_path):
    for label, kwargs in (
            ("pbr", {"native_pbr": True, "high_detail": True}),
            ("unlit", {"unlit": True, "texture_colours": True})):
        out = tmp_path / (label + ".glb")
        export_glb(out, WATER, COORDS, cell_box={"corners": CORNERS},
                   **kwargs)
        gltf = _gltf(out)
        assert gltf["extras"]["chemistry"]["cell_box"] is True, label
        assert "Unit cell" in [m.get("name") for m in gltf["materials"]], label


def test_invalid_corners_are_ignored(tmp_path):
    out = tmp_path / "short.glb"
    export_glb(out, WATER, COORDS,
               cell_box={"corners": [[0, 0, 0], [1, 0, 0]]})
    assert _gltf(out)["extras"]["chemistry"]["cell_box"] is False


def test_export_dialog_exposes_the_crystal_group():
    """The crystal-only unit-cell settings must be visible without scrolling."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication
    from molstudio.ui.ppt3d_options_widget import Ppt3dExportDialog

    app = QApplication.instance() or QApplication([])  # noqa: F841
    dlg = Ppt3dExportDialog(lang="zh", crystal=True)
    assert dlg.height() >= 700
    assert dlg.widget.grp_cell.isEnabled()
    assert dlg.widget.chk_cell_box.isChecked()
    plain = Ppt3dExportDialog(lang="zh", crystal=False)
    assert not plain.widget.grp_cell.isEnabled()


def test_library_export_passes_live_options():
    """Library tab must hand the *current* widget state to the export callback."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication
    from molstudio.panels.library_panel import LibraryPanel

    app = QApplication.instance() or QApplication([])  # noqa: F841
    captured = []
    panel = LibraryPanel(
        lang="zh",
        on_export_crystal=lambda entry, opt: captured.append((entry, opt)))
    panel.switch_to_crystals("CaF2")
    panel.options_widget.chk_cell_box.setChecked(False)
    panel.options_widget.spin_reps[0].setValue(2)
    panel._export_current()
    assert len(captured) == 1
    entry, opt = captured[0]
    assert entry.id.startswith("caf2")
    assert opt.show_cell_box is False
    assert opt.reps() == (2, 1, 1)
    assert opt.cell_box_spec([[0, 0, 0]] * 8) is None


def test_library_page_has_four_tabs_on_one_row():
    """Exactly one tab bar with four sibling tabs; no nested tab widget."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication, QTabWidget
    from molstudio.panels.library_panel import LibraryPanel

    app = QApplication.instance() or QApplication([])  # noqa: F841
    panel = LibraryPanel(lang="zh")
    tab_widgets = panel.findChildren(QTabWidget)
    assert len(tab_widgets) == 1, "nested tab widgets are back"
    tabs = panel.sub_tabs
    assert tabs.count() == 4
    titles = [tabs.tabText(i) for i in range(4)]
    assert titles == ["🧪 分子结构库", "💎 晶体结构库",
                      "⚙ 导出设置", "📖 引文"]
    assert tabs.tabBar().count() == 4
    assert tabs.tabBar().usesScrollButtons()
    assert panel.findChildren(QTabWidget) == [tabs]
    # 标题 / 副标题两行说明已移除；页签不再自带小字体 QSS，
    # 继承全局 QTabBar::tab 才能与其他功能页的页签等高、等宽、等字号。
    assert not hasattr(panel, "lbl_title")
    assert not hasattr(panel, "lbl_subtitle")
    assert panel.sub_tabs.styleSheet() == ""
    assert panel.molecule_view.list_widget.count() > 50
    assert panel.crystal_view.list_widget.count() > 35

    # Export settings and citation each own a full page (no cramped sidebar).
    assert panel.options_widget.grp_cell.isEnabled()
    citation = panel.txt_citation.toPlainText()
    assert "Avogadro2" in citation and "COD" in citation
    assert "AMCSD" in citation and "教学模型说明" in citation
    assert "SrTiO3" in citation

    # Shared action bar follows the active tab.
    tabs.setCurrentIndex(1)
    assert panel.btn_export.isEnabled() and panel.btn_crystal_tab.isEnabled()
    assert panel.is_crystal_page()
    tabs.setCurrentIndex(2)
    assert not panel.btn_export.isEnabled()
    assert not panel.btn_crystal_tab.isEnabled()
    tabs.setCurrentIndex(3)
    assert not panel.btn_visualize.isEnabled()

    panel.switch_to_crystals("NaCl")
    assert panel.is_crystal_page()
    assert "COD" in panel.lbl_current_source.text()

    panel.set_language("en")
    assert [panel.sub_tabs.tabText(i) for i in range(4)] == [
        "🧪 Molecules", "💎 Crystals", "⚙ Export settings", "📖 Citation"]
    assert "教学" not in panel.txt_citation.toPlainText()


def test_library_page_has_only_one_visible_tab_bar():
    """结构库页隐藏右栏全局「设置 / 引文」页签栏，其他功能页保持原样。"""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication
    from molstudio.ui.main_window import OrbitalVisApp

    app = QApplication.instance() or QApplication([])  # noqa: F841
    win = OrbitalVisApp()
    try:
        bar = win.right_tabs.tabBar()
        assert win.library_panel.sub_tabs.count() == 4
        win._switch_to_tab("tab_library")
        assert bar.isHidden(), "外层全局页签栏仍显示，结构库成了两层 tab"
        assert win.right_tabs.currentIndex() == 0

        other = next(k for k in win._tab_keys if k != "tab_library")
        win._switch_to_tab(other)
        assert not bar.isHidden(), "切回其他功能页后全局页签栏未恢复"

        win._switch_to_tab("tab_library")
        assert bar.isHidden()
    finally:
        win.close()
