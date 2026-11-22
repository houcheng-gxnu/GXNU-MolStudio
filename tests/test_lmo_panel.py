# -*- coding: utf-8 -*-
"""``LMOPanel`` 结果表 / 中心映射 / CSV / 中英文回归（离屏 Qt，不跑 Multiwfn）。

这些用例覆盖 2026-11 独立评审发现的三个数据缺陷：

* 开壳层 + occupied/unoccupied 一起定域化时，只出现在 ``character`` 里、
  没有能量行的 β 占据 LMO 曾被整行丢掉；
* LMOcen 的 β 中心是“每自旋编号”，旧实现只在 ``<= n_beta_occupied`` 时
  加偏移，导致 β13..β75 与 α13..α75 撞车、β88+ 全没中心；
* CSV 的 Spin 列对闭壳层曾一律写 α。
"""

import os
import re
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import QApplication, QComboBox, QTableWidget, QWidget  # noqa: E402

_CJK = re.compile(r"[\u4e00-\u9fff]")
_APP = None


def _app():
    global _APP
    _APP = QApplication.instance() or QApplication(sys.argv)
    return _APP


@pytest.fixture()
def panel():
    _app()
    from molstudio.panels.lmo_panel import LMOPanel

    widget = LMOPanel()
    widget.resize(760, 950)
    widget.set_lang("zh")
    yield widget
    widget.deleteLater()


def _atom(index, element, percent):
    return {"index": index, "element": element, "percent": percent}


def _closed_result():
    return {
        "ok": True,
        "converged": True,
        "settings": {"method": "pm_mulliken"},
        "seconds": 0.5,
        "n_alpha_total": 0,
        "n_occupied": 2,
        "n_beta_occupied": 0,
        "energies": [
            {"index": 1, "energy_au": -0.7, "energy_ev": -19.0,
             "spin": "A+B", "occ": 2.0},
            {"index": 2, "energy_au": -0.6, "energy_ev": -16.0,
             "spin": "A+B", "occ": 2.0},
        ],
        "character": {
            1: {"kind": "single", "spin": "A+B", "atoms": [_atom(2, "O", 99.6)]},
            2: {"kind": "two", "spin": "A+B",
                "atoms": [_atom(2, "O", 63.1), _atom(1, "C", 35.5)]},
        },
        "lmo_centers": {"closed": {}, "alpha": {}, "beta": {}},
        "lmo_fch": "",
        "warnings": [],
    }


def _open_both_result():
    """开壳层 occupied+unoccupied：β76/β77 只有 character，没有能量行。"""
    energies = [
        {"index": i, "energy_au": -0.5 - 0.01 * i, "energy_ev": -13.0,
         "spin": "A", "occ": 1.0} for i in (1, 2, 3)
    ]
    energies.append({"index": 88, "energy_au": 0.1, "energy_ev": 2.7,
                     "spin": "B", "occ": 0.0})
    return {
        "ok": True,
        "converged": True,
        "settings": {"method": "pm_mulliken"},
        "seconds": 1.2,
        "n_alpha_total": 75,
        "n_occupied": 3,
        "n_beta_occupied": 2,
        "energies": energies,
        "character": {
            1: {"kind": "single", "spin": "A", "atoms": [_atom(8, "O", 99.6)]},
            2: {"kind": "single", "spin": "A", "atoms": [_atom(1, "C", 98.9)]},
            76: {"kind": "single", "spin": "B", "atoms": [_atom(8, "O", 99.7)]},
            77: {"kind": "two", "spin": "B",
                 "atoms": [_atom(8, "O", 62.5), _atom(5, "C", 30.3)]},
        },
        # α13 / β13 / β75 的 LMOcen 键都是“每自旋编号”
        "lmo_centers": {
            "closed": {},
            "alpha": {13: {"bq": 22, "xyz_bohr": (0.0, 0.0, 0.0),
                           "xyz_ang": (1.0, 1.0, 1.0)}},
            "beta": {13: {"bq": 97, "xyz_bohr": (0.0, 0.0, 0.0),
                          "xyz_ang": (2.0, 2.0, 2.0)},
                     75: {"bq": 159, "xyz_bohr": (0.0, 0.0, 0.0),
                          "xyz_ang": (3.0, 3.0, 3.0)}},
        },
        "lmo_fch": "",
        "warnings": [],
    }


def _loba_result():
    return {
        "ok": True,
        "settings": {"method": "loba", "threshold": 50.0,
                     "fragment": "1-3"},
        "seconds": 0.2,
        "atoms": [
            {"index": 1, "element": "Fe", "oxidation_state": 3.0},
            {"index": 2, "element": "C", "oxidation_state": 2.0},
            {"index": 3, "element": "N", "oxidation_state": -3.0},
        ],
        "sum": -3.0,
        "net_charge": -3,
        "sum_difference": 0.0,
        "fragment_oxidation_state": -1.0,
        "log_path": "",
        "warnings": [],
    }


def _find_row(table, label):
    for row in range(table.rowCount()):
        item = table.item(row, 0)
        if item is not None and item.text() == label:
            return row
    return -1


def test_rows_include_character_only_lmos(panel):
    panel._apply_result(_open_both_result())
    table = panel.table

    # 能量行：α1..α3 + β88；character 另有 β76/β77（无能量）→ 取并集
    assert table.rowCount() == 6
    assert [table.item(r, 0).text() for r in range(6)] == [
        "α 1", "α 2", "α 3", "β 76", "β 77", "β 88"]

    for label in ("β 76", "β 77"):
        row = _find_row(table, label)
        assert row >= 0, f"{label} 被丢掉了"
        assert table.item(row, 1).text() == panel._t("dash")
        assert table.item(row, 4).text() == panel._t(
            "kind_single" if label == "β 76" else "kind_two")


def test_open_shell_beta_character_keeps_global_index(panel):
    panel._apply_result(_open_both_result())
    row = _find_row(panel.table, "β 77")
    assert row >= 0
    assert panel.table.item(row, 5).text().startswith("O8 62.5%")


def test_center_mapping_offsets_all_beta_lmos(panel):
    result = _open_both_result()
    # 让 α13 / β150 行存在（真实 scope=both 运行里 character 覆盖全部 LMO）
    result["character"][13] = {"kind": "single", "spin": "A",
                               "atoms": [_atom(8, "O", 88.0)]}
    result["character"][88] = {"kind": "more", "spin": "B",
                               "atoms": [_atom(6, "Fe", 75.0)]}
    result["character"][150] = {"kind": "two", "spin": "B",
                                "atoms": [_atom(1, "C", 50.0),
                                          _atom(2, "H", 40.0)]}
    panel._apply_result(result)
    table = panel.table

    alpha13 = _find_row(table, "α 13")
    beta13 = _find_row(table, "β 88")
    beta150 = _find_row(table, "β 150")
    # α13 的中心来自 alpha{13}；β88 来自 beta{13}；β150 来自 beta{75}
    assert alpha13 >= 0 and beta13 >= 0 and beta150 >= 0
    assert table.item(alpha13, 6).text().startswith("1.0")
    assert table.item(beta13, 6).text().startswith("2.0")
    assert table.item(beta150, 6).text().startswith("3.0")


def test_closed_shell_spin_and_csv(panel, tmp_path, monkeypatch):
    from molstudio.panels import lmo_panel as mod

    captured = {}

    def _fake_save(_parent, _caption, _default, _filt):
        path = str(tmp_path / "lmo.csv")
        captured["default"] = _default
        return path, _filt

    monkeypatch.setattr(mod.QFileDialog, "getSaveFileName", _fake_save)
    result = _closed_result()
    result["lmo_fch"] = str(tmp_path / "Ferrocene_LMO.fch")
    panel._apply_result(result)
    panel._export_csv()

    text = (tmp_path / "lmo.csv").read_text(encoding="utf-8-sig")
    lines = [line for line in text.splitlines() if line.strip()]
    assert lines[0].startswith("轨道,自旋,")
    assert ",α+β," in lines[1]
    assert not captured["default"].endswith("_LMO_LMO.csv")


def test_loba_table_summary_method_and_csv(panel, tmp_path, monkeypatch):
    from molstudio.panels import lmo_panel as mod

    lmo = tmp_path / "Ferrocene_LMO.fch"
    lmo.write_text("dummy", encoding="utf-8")
    result = _closed_result()
    result["lmo_fch"] = str(lmo)
    panel._apply_result(result)
    assert panel.btn_loba_run.isEnabled()

    loba = _loba_result()
    loba["log_path"] = str(tmp_path / "Ferrocene_LMO_LOBA.log")
    panel._apply_loba_result(loba)
    assert panel.loba_table.rowCount() == 3
    assert panel.loba_table.item(0, 0).text() == "1"
    assert panel.loba_table.item(0, 1).text() == "Fe"
    assert panel.loba_table.item(0, 2).text() == "+3"
    assert "1-3" in panel.lbl_loba_summary.text()
    assert "50.0%" in panel.lbl_loba_summary.text()

    panel.cmb_loba_method.setCurrentIndex(
        panel.cmb_loba_method.findData("mloba"))
    assert not panel.spin_loba_threshold.isEnabled()
    panel.cmb_loba_method.setCurrentIndex(
        panel.cmb_loba_method.findData("loba"))
    assert panel.spin_loba_threshold.isEnabled()

    captured = {}

    def _fake_save(_parent, _caption, _default, _filt):
        path = str(tmp_path / "loba.csv")
        captured["default"] = _default
        return path, _filt

    monkeypatch.setattr(mod.QFileDialog, "getSaveFileName", _fake_save)
    panel._export_loba_csv()
    lines = (tmp_path / "loba.csv").read_text(
        encoding="utf-8-sig").splitlines()
    assert lines[0] == "原子,元素,氧化态"
    assert lines[1] == "1,Fe,3"
    assert captured["default"].endswith("Ferrocene_LOBA.csv")


def test_loba_accepts_already_loaded_localized_wavefunction(panel, tmp_path):
    path = tmp_path / "External_LMO.fch"
    path.write_text("dummy", encoding="utf-8")
    panel.set_source_from_main(str(path))

    assert panel._loba_input_path() == str(path)
    assert panel.btn_loba_run.isEnabled()
    assert "Ready" in panel.lbl_loba_status.text() or "就绪" in (
        panel.lbl_loba_status.text())


def test_english_ui_has_no_chinese(panel):
    panel._apply_result(_open_both_result())
    panel._apply_loba_result(_loba_result())
    panel.set_lang("en")

    def texts(widget):
        out = []
        for attr in ("text", "windowTitle", "placeholderText", "toolTip"):
            getter = getattr(widget, attr, None)
            if callable(getter):
                try:
                    value = getter()
                except RuntimeError:
                    value = None
                if isinstance(value, str) and value.strip():
                    out.append(value)
        if isinstance(widget, QComboBox):
            out += [widget.itemText(i) for i in range(widget.count())]
        if isinstance(widget, QTableWidget):
            out += [widget.horizontalHeaderItem(c).text()
                    for c in range(widget.columnCount())
                    if widget.horizontalHeaderItem(c)]
            out += [widget.item(r, c).text()
                    for r in range(widget.rowCount())
                    for c in range(widget.columnCount())
                    if widget.item(r, c)]
        return out

    hits = []
    for widget in [panel] + panel.findChildren(QWidget):
        hits += [text for text in texts(widget) if _CJK.search(text)]
    assert not hits, f"英文界面仍有中文：{hits[:8]}"

    panel.set_lang("zh")
    assert panel.table.horizontalHeaderItem(0).text() == "轨道"
    assert panel.table.item(0, 4).text() == "单中心"
