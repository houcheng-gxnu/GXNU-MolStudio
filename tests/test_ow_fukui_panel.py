# -*- coding: utf-8 -*-
"""``OWFukuiPanel`` 结果表 / 合计行 / 列宽 / CSV / 中英文回归。

离屏 Qt、不启动 Multiwfn、不加载主窗口：用假 result dict 直接调
``_apply_result`` 覆盖面板的展示逻辑，运行时间应在 1 s 量级。
"""

import os
import re
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import (  # noqa: E402
    QAbstractButton,
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QTabWidget,
    QTableWidget,
)

_CJK = re.compile(r"[\u4e00-\u9fff]")
_APP = None


def _app():
    global _APP
    _APP = QApplication.instance() or QApplication(sys.argv)
    return _APP


@pytest.fixture()
def panel():
    _app()
    from molstudio.panels.ow_fukui_panel import OWFukuiPanel

    widget = OWFukuiPanel()
    widget.resize(820, 1000)
    widget.set_lang("zh")
    yield widget
    widget.shutdown()
    widget.deleteLater()


def _fake_result(total=(70.46, 70.37)):
    """C60 默认 Δ 的典型形状：f+/f− 各列 10 条，简缩表 4 个原子。"""
    weights = {
        "fplus": [
            {"index": 181 + i, "label": "LUMO+%d" % i if i else "LUMO",
             "weight": 12.47, "ediff_ev": 1.75} for i in range(10)],
        "fminus": [
            {"index": 180 - i, "label": "HOMO-%d" % i if i else "HOMO",
             "weight": 9.06, "ediff_ev": -1.75} for i in range(10)],
    }
    condensed = [
        {"index": 1, "element": "C", "fplus": 0.01667,
         "fminus": 0.01667, "f0": 0.01667, "dd": -0.01667},
        {"index": 2, "element": "C", "fplus": 0.01599,
         "fminus": 0.01700, "f0": 0.01650, "dd": -0.00101},
        {"index": 3, "element": "H", "fplus": 0.01758,
         "fminus": 0.01010, "f0": 0.01384, "dd": 0.00748},
        {"index": 4, "element": "H", "fplus": 0.01757,
         "fminus": 0.01010, "f0": 0.01384, "dd": 0.00747},
    ]
    result = {
        "ok": True,
        "error": "",
        "seconds": 11.1,
        "settings": {"delta": 0.1, "grid_quality": 2},
        "homo_energy": -0.232805,
        "lumo_energy": -0.104063,
        "chemical_potential": -0.168434,
        "delta": 0.1,
        "weights": weights,
        "condensed": condensed,
        "sums": {"fplus": 1.000162, "fminus": 1.000148},
        "grid": {"quality": 2, "nx": 82, "ny": 81, "nz": 79,
                 "npoints": 524718, "spacing_bohr": 0.240630},
        "exported": [],
        "warnings": [],
        "cubes": {"fplus": "", "fminus": "", "f0": "", "dd": ""},
        "log_path": "",
        "raw": "",
        "work_dir": "",
    }
    if total is not None:
        result["total_weight"] = {"fplus": total[0], "fminus": total[1]}
    return result


def _collect_texts(widget):
    """收集面板内所有可能显示给用户的文本（含 tooltip / 表头 / 单元格）。"""
    out = []
    for obj in [widget] + widget.findChildren(object):
        getters = []
        if isinstance(obj, QLabel):
            getters.append("text")
        if isinstance(obj, QGroupBox):
            getters.append("title")
        if isinstance(obj, QAbstractButton):
            getters.append("text")
        if isinstance(obj, QLineEdit):
            getters.extend(("text", "placeholderText"))
        for attr in ("windowTitle", "toolTip"):
            getters.append(attr)
        for attr in getters:
            getter = getattr(obj, attr, None)
            if callable(getter):
                try:
                    value = getter()
                except RuntimeError:
                    value = None
                if isinstance(value, str) and value.strip():
                    out.append(value)
        if isinstance(obj, QComboBox):
            out.extend(obj.itemText(i) for i in range(obj.count()))
        if isinstance(obj, QTabWidget):
            out.extend(obj.tabText(i) for i in range(obj.count()))
        if isinstance(obj, QTableWidget):
            for column in range(obj.columnCount()):
                header = obj.horizontalHeaderItem(column)
                if header is not None:
                    out.append(header.text())
            for row in range(obj.rowCount()):
                for column in range(obj.columnCount()):
                    item = obj.item(row, column)
                    if item is not None:
                        out.append(item.text())
        if isinstance(obj, QDoubleSpinBox):
            out.append(obj.suffix())
    return out


def _pump(app, rounds=40):
    for _ in range(rounds):
        app.processEvents()


# ── 1. 实例化 / 运行前状态 ──────────────────────────────────────────────
def test_instantiate_without_callbacks(panel):
    from molstudio.panels.ow_fukui_panel import OWFukuiPanel

    assert isinstance(panel, OWFukuiPanel)
    assert panel.tabs.count() == 3
    assert [panel.tabs.tabText(i) for i in range(3)] == [
        "轨道权重", "简缩值", "可视化"]
    assert panel.cmb_function.count() == 4
    assert panel.cmb_grid.count() == 3
    assert abs(panel.spin_delta.value() - 0.1) < 1e-9
    assert not panel.btn_run.isEnabled()
    assert panel.lbl_weight_total.isHidden()
    assert panel.table_fplus.rowCount() == 0
    assert panel.table_condensed.rowCount() == 0
    # 设置区字段不再被 QFormLayout 拉满整页
    assert 180 <= panel.spin_delta.maximumWidth() <= 260
    assert 180 <= panel.cmb_grid.maximumWidth() <= 260
    assert panel.spin_delta.minimumWidth() >= 160


def test_shutdown_without_running_is_safe(panel):
    assert panel._worker is None
    panel.shutdown()
    assert panel._shutting_down
    assert panel._worker is None
    # 重复调用也必须安全（主窗口 closeEvent 与显式 shutdown 可能各调一次）
    panel.shutdown()
    assert not panel._running


# ── 2. 假 result 填表 ───────────────────────────────────────────────────
def test_apply_result_fills_tables_and_summary(panel):
    panel._apply_result(_fake_result())

    assert panel.table_fplus.rowCount() == 10
    assert panel.table_fminus.rowCount() == 10
    assert panel.table_condensed.rowCount() == 6  # 4 原子 + 2 行 sum
    assert panel.table_fplus.item(0, 0).text() == "181"
    assert panel.table_fplus.item(0, 1).text() == "LUMO"
    assert panel.table_fplus.item(5, 1).text() == "LUMO+5"
    assert panel.table_fplus.item(0, 2).text() == "12.47"
    assert panel.table_fplus.item(0, 3).text() == "1.750"

    summary = panel.lbl_orb_summary.text()
    for token in ("HOMO", "LUMO", "μ", "Δ"):
        assert token in summary
    assert "-0.232805" in summary

    # 简缩表 + 两行 sum（底部行加粗，值落在各自列）
    assert panel.table_condensed.item(0, 1).text() == "C"
    assert panel.table_condensed.item(2, 1).text() == "H"
    sum_plus_row = panel.table_condensed.rowCount() - 2
    sum_minus_row = panel.table_condensed.rowCount() - 1
    assert panel.table_condensed.item(sum_plus_row, 0).text() == panel._t(
        "sum_fplus")
    assert panel.table_condensed.item(sum_plus_row, 2).text() == "1.000162"
    assert panel.table_condensed.item(sum_minus_row, 0).text() == panel._t(
        "sum_fminus")
    assert panel.table_condensed.item(sum_minus_row, 3).text() == "1.000148"


def test_total_weight_line(panel):
    panel._apply_result(_fake_result())
    label = panel.lbl_weight_total
    assert not label.isHidden()
    text = label.text()
    assert "70.46" in text and "70.37" in text
    assert "合计" in text

    # 切换英文后同一行必须跟着本地化，且数值不变
    panel.set_lang("en")
    text = label.text()
    assert "70.46" in text and "70.37" in text
    assert "Sum of the listed orbital weights" in text
    assert not _CJK.search(text)

    # total_weight 缺失/为 None 时显示 — 而不是 0
    result = _fake_result(total=None)
    panel.set_lang("zh")
    panel._apply_result(result)
    text = label.text()
    assert panel._t("dash") in text
    assert "70.46" not in text


def test_total_weight_hidden_when_no_weights(panel):
    result = _fake_result()
    result["weights"] = {"fplus": [], "fminus": []}
    panel._apply_result(result)
    assert panel.lbl_weight_total.isHidden()


# ── 3. 列宽：LUMO+10 / 0.01667 必须放得下 ───────────────────────────────
def test_table_column_widths_fit_content(panel):
    app = _app()
    panel.resize(1200, 1000)
    panel.setAttribute(Qt.WA_DontShowOnScreen, True)
    panel.show()
    _pump(app)

    panel._apply_result(_fake_result())
    _pump(app)

    for table in (panel.table_fplus, panel.table_fminus):
        metrics = table.fontMetrics()
        assert table.columnWidth(1) >= 96
        assert table.columnWidth(0) >= 60
        assert table.columnWidth(2) >= 76
        # 标记列至少能放下 LUMO+10（宽度按字体度量给足，最多到 160 上限）
        need_mark = max(96, min(160,
                                metrics.horizontalAdvance("LUMO+10") + 16))
        assert table.columnWidth(1) >= need_mark - 1
        # 1200 px 页面下不应出现水平滚动条（4 列都在视口内）
        assert table.horizontalScrollBar().maximum() == 0

    condensed = panel.table_condensed
    panel.tabs.setCurrentIndex(1)
    _pump(app)
    metrics = condensed.fontMetrics()
    need_value = max(95, min(150,
                             metrics.horizontalAdvance("0.01667") + 16))
    for column in (2, 3, 4):
        assert condensed.columnWidth(column) >= need_value - 1
    assert condensed.columnWidth(0) >= 56
    assert condensed.columnWidth(1) >= 56
    # OW DD 是最后一列，吃掉剩余宽度
    assert condensed.columnWidth(5) > condensed.columnWidth(2)
    assert condensed.horizontalScrollBar().maximum() == 0

    # 内容控件真的能完成一次渲染（离屏下 grab 不应崩/为空）
    pixmap = panel.content_widget.grab()
    assert not pixmap.isNull()
    assert pixmap.width() > 400
    panel.hide()


# ── 4. CSV 导出（中英各一次）────────────────────────────────────────────
def test_export_condensed_csv_zh_en(panel, tmp_path, monkeypatch):
    from molstudio.panels import ow_fukui_panel as mod

    panel._apply_result(_fake_result())

    saved_paths = iter((str(tmp_path / "owf_zh.csv"),
                        str(tmp_path / "owf_en.csv")))

    def _fake_save(_parent, _caption, _default, filt):
        return next(saved_paths), filt

    monkeypatch.setattr(mod.QFileDialog, "getSaveFileName", _fake_save)

    panel.set_lang("zh")
    panel._export_csv()
    zh_path = tmp_path / "owf_zh.csv"
    assert zh_path.is_file()
    zh_text = zh_path.read_text(encoding="utf-8-sig")
    zh_lines = [line for line in zh_text.splitlines() if line.strip()]
    assert len(zh_lines) == 1 + 4       # 表头 + 4 原子
    assert zh_lines[0].startswith("原子,元素,OW f+")

    panel.set_lang("en")
    panel._export_csv()
    en_path = tmp_path / "owf_en.csv"
    assert en_path.is_file()
    en_text = en_path.read_text(encoding="utf-8-sig")
    en_lines = [line for line in en_text.splitlines() if line.strip()]
    assert len(en_lines) == 1 + 4
    assert en_lines[0].startswith("Atom,Element,OW f+")
    assert "-0.01667" in en_lines[1]


# ── 5. 中英文整页刷新 ──────────────────────────────────────────────────
def test_english_ui_has_no_chinese(panel):
    panel._apply_result(_fake_result())
    panel.set_lang("en")

    texts = _collect_texts(panel)
    hits = [text for text in texts if _CJK.search(text)]
    assert not hits, f"英文界面仍有中文：{hits[:8]}"

    assert panel.table_fplus.horizontalHeaderItem(0).text() == "Orbital"
    assert panel.table_fplus.horizontalHeaderItem(1).text() == "Label"
    assert panel.table_condensed.horizontalHeaderItem(2).text() == "OW f+"
    assert panel.tabs.tabText(0) == "Orbital weights"
    assert "Sum of the listed orbital weights" in panel.lbl_weight_total.text()

    panel.set_lang("zh")
    assert panel.table_fplus.horizontalHeaderItem(0).text() == "编号"
    assert panel.table_fplus.item(0, 1).text() == "LUMO"
    assert "合计" in panel.lbl_weight_total.text()
    assert panel.tabs.tabText(1) == "简缩值"
