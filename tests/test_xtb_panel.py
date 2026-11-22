# -*- coding: utf-8 -*-
"""``molstudio.panels.xtb_panel`` 的面板测试（离屏 Qt + 真实 xTB 可执行文件）。

运行（默认 python 无 pytest）：

    C:\\ProgramData\\Anaconda3\\python.exe -m pytest tests/test_xtb_panel.py -q

离屏截图/字体：

    set QT_QPA_PLATFORM=offscreen
    set QT_QPA_FONTDIR=C:\\Windows\\Fonts
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PyQt5.QtWidgets import (                                   # noqa: E402
    QApplication, QComboBox, QGridLayout, QTableWidget, QWidget,
)
from PyQt5.QtGui import QShowEvent                              # noqa: E402

from molstudio.core import xtb                                  # noqa: E402
from molstudio.core.surface_projection import load_atoms        # noqa: E402
from molstudio.panels import xtb_panel                          # noqa: E402
from molstudio.panels.xtb_panel import XtbPanel, _TR            # noqa: E402

CJK_RE = re.compile(r"[\u4e00-\u9fff]")

WATER_SYMBOLS = ["O", "H", "H"]
WATER_COORDS = np.array([
    [0.00000000, 0.00000000, 0.00000000],
    [0.00000000, 0.75700000, 0.58700000],
    [0.00000000, -0.75700000, 0.58700000],
])
AMMONIA_SYMBOLS = ["N", "H", "H", "H"]
AMMONIA_COORDS = np.array([
    [0.0, 0.0, 0.0],
    [0.0, 0.94, 0.0],
    [0.815, -0.47, 0.0],
    [-0.815, -0.47, 0.0],
])


# ══════════════════════════════════════════════════════════════════════
#  fixtures / helpers
# ══════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="session")
def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication([])
    return instance


@pytest.fixture
def settings_path(tmp_path, monkeypatch):
    path = tmp_path / "xtb_panel_settings.ini"
    monkeypatch.setattr(xtb_panel, "settings_file", lambda: str(path))
    return path


class PanelHarness:
    """小包装：面板 + 可变画布结构 + 日志/回画布记录。"""

    def __init__(self, panel):
        self.panel = panel
        self.canvas = (list(WATER_SYMBOLS), WATER_COORDS.copy())
        self.logs = []
        self.loaded = []


@pytest.fixture
def harness(app, settings_path):
    holder = {"canvas": (list(WATER_SYMBOLS), WATER_COORDS.copy())}
    logs, loaded = [], []

    def get_structure():
        return holder["canvas"]

    def on_loaded(symbols, coords, label=""):
        loaded.append((list(symbols), np.asarray(coords, dtype=float), label))

    panel = XtbPanel(get_structure=get_structure,
                     on_structure_loaded=on_loaded,
                     log_func=logs.append)
    panel.resize(680, 1200)
    h = PanelHarness(panel)
    h.holder = holder
    h.logs = logs
    h.loaded = loaded
    h.canvas = holder["canvas"]
    panel.harness = h
    yield h
    panel.shutdown()
    panel.deleteLater()


def wait_until(app, predicate, timeout=30.0):
    """转事件循环直到 predicate 为真或超时。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return bool(predicate())


def make_result(params=None, symbols=None, coords=None, workdir="", **overrides):
    """构造字段齐全的 XtbResult 替身（SimpleNamespace，面板只按属性读取）。"""
    params = dict(params or {
        "method": "gfn2", "job": "opt", "charge": 0, "uhf": 0, "acc": 1.0,
        "etemp": 300, "solvation": "gas", "solvent": "",
        "parallel": 4, "json": True, "molden": False, "verbose": False,
        "extra_args": "", "xcontrol": "",
    })
    symbols = list(symbols or WATER_SYMBOLS)
    coords = np.asarray(WATER_COORDS if coords is None else coords, dtype=float)
    fields = dict(
        symbols=symbols, input_coords=coords, input_xyz="",
        method=params.get("method", "gfn2"),
        method_label=params.get("method", "gfn2"),
        job=params.get("job", "opt"), job_label=params.get("job", "opt"),
        params=params, command=["xtb"], command_str="xtb",
        workdir=str(workdir), output_file="",
        returncode=0, success=True, normal_termination=True, cancelled=False,
        elapsed=0.42, output_text="",
        energy=-5.070371, electronic_energy=-5.070371, gap=14.63,
        homo=-12.60, lumo=2.03, dipole_debye=1.85, gradient_norm=None,
        charges=[-0.68, 0.34, 0.34],
        orbital_energies=[-12.60, 2.03], occupations=[2.0, 0.0],
        formula="H2O",
        optimized_symbols=None, optimized_coords=None, optimized_xyz_file="",
        frequencies=[], imaginary_count=None, thermo={},
        scan=[], scan_file="", json_file="", charges_file="",
        vibspectrum_file="", warnings=[],
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


def optimized_result(**overrides):
    return make_result(optimized_symbols=list(WATER_SYMBOLS),
                       optimized_coords=WATER_COORDS.copy(), **overrides)


def scan_result(n=4):
    frames = []
    for i in range(n):
        frames.append({
            "step": i + 1,
            "energy": -5.0 + 0.01 * i,
            "energy_relative": 0.01 * i,
            "symbols": list(WATER_SYMBOLS),
            "coords": WATER_COORDS + np.array([[0.0, 0.0, 0.02 * i]] * 3),
        })
    return make_result(job="scan", scan=frames,
                       optimized_symbols=list(WATER_SYMBOLS),
                       optimized_coords=WATER_COORDS.copy())


def use_fake_run(monkeypatch, factory):
    monkeypatch.setattr(xtb, "run_job", factory)


def fake_fast_run(params, symbols, coords, workdir, *, on_line=None,
                  on_progress=None, should_cancel=None, lang="zh"):
    if on_progress:
        on_progress("preparing", "preparing")
        on_progress("running", "running")
    if on_line:
        on_line("fake: running")
    if on_progress:
        on_progress("parsing", "parsing")
    result = make_result(params, symbols, coords, workdir)
    if params.get("job") in ("ohess", "hess", "ts"):
        result.frequencies = [
            {"mode": i + 1, "frequency": 100.0 + 50.0 * i, "ir": 1.0,
             "symmetry": "A1"} for i in range(3)
        ]
        result.imaginary_count = 0
        result.thermo = {"free_energy": -5.0631, "enthalpy": -5.0612,
                         "zpe": 0.0213}
    if params.get("job") == "scan":
        base = scan_result()
        return base
    return result


def widget_texts(root):
    """收集控件上所有可能显示给用户的文字（用于 en 无中文残留检查）。"""
    texts = []
    for widget in root.findChildren(QWidget):
        try:
            for attr in ("text", "title", "placeholderText", "toolTip",
                         "windowTitle"):
                getter = getattr(widget, attr, None)
                if callable(getter):
                    value = getter()
                    if isinstance(value, str):
                        texts.append(value)
        except Exception:                                      # noqa: BLE001
            pass
        if isinstance(widget, QComboBox):
            texts.extend(widget.itemText(i) for i in range(widget.count()))
        if isinstance(widget, QTableWidget):
            header = widget.horizontalHeader()
            for col in range(widget.columnCount()):
                item = widget.horizontalHeaderItem(col) or header
                try:
                    texts.append(item.text())
                except Exception:                              # noqa: BLE001
                    pass
        # suffix 之类
        for attr in ("suffix", "prefix"):
            getter = getattr(widget, attr, None)
            if callable(getter):
                try:
                    value = getter()
                except Exception:                              # noqa: BLE001
                    continue
                if isinstance(value, str):
                    texts.append(value)
    return texts


# ══════════════════════════════════════════════════════════════════════
#  构造 / 默认值 / i18n
# ══════════════════════════════════════════════════════════════════════
def test_constructor_defaults_and_detection(harness):
    panel = harness.panel
    assert panel.cmb_method.currentData() == "gfn2"
    assert panel.cmb_job.currentData() == "opt"
    assert panel.chk_json.isChecked()
    assert panel.spn_charge.value() == 0
    assert panel.spn_uhf.value() == 0
    assert abs(panel.spn_acc.value() - 1.0) < 1e-9
    assert panel.spn_etemp.value() == 300
    assert panel.cmb_solvation.currentData() == "gas"
    assert not panel.cmb_solvent.isEnabled()

    expected = xtb.find_xtb_executable()
    if expected:
        assert panel.edit_exe.text().strip() == expected
        assert panel.lbl_status.text() == _TR["zh"]["st_ready"]
    else:
        assert panel.lbl_status.text() == _TR["zh"]["st_engine_missing"]

    assert panel.btn_run.isEnabled()
    assert not panel.btn_cancel.isEnabled()
    assert not panel.btn_to_canvas.isEnabled()
    assert not panel.btn_export_xyz.isEnabled()
    assert panel.grp_scan.isHidden()
    assert panel.tbl_charges.editTriggers() == QTableWidget.NoEditTriggers
    assert panel.minimumSizeHint().width() <= 680
    assert len(harness.panel._symbols) == 3


def test_language_toggle_and_no_cjk_in_en(harness):
    panel = harness.panel
    assert panel.btn_run.text() == _TR["zh"]["btn_run"]
    assert panel.btn_cancel.text() == _TR["zh"]["btn_cancel"]
    assert panel.lbl_status.text() == _TR["zh"]["st_ready"]

    panel.set_lang("en")
    assert panel.btn_run.text() == _TR["en"]["btn_run"]
    assert panel.btn_cancel.text() == _TR["en"]["btn_cancel"]
    assert panel.grp_calc.title() == _TR["en"]["grp_calc"]
    assert panel.lbl_status.text() == _TR["en"]["st_ready"]
    assert panel.cmb_job.itemText(panel.cmb_job.currentIndex()) == \
        xtb.JOB_TYPES["opt"]["en"]
    assert panel.tbl_charges.horizontalHeaderItem(2).text() == _TR["en"]["col_charge"]

    # 中文下拉项不能残留
    for combo in (panel.cmb_method, panel.cmb_job, panel.cmb_solvation):
        for i in range(combo.count()):
            assert not CJK_RE.search(combo.itemText(i)), combo.itemText(i)
    for text in widget_texts(panel):
        assert not CJK_RE.search(text), "en 下仍有中文：%r" % text

    panel.set_lang("zh")
    assert panel.btn_run.text() == _TR["zh"]["btn_run"]
    assert panel.lbl_status.text() == _TR["zh"]["st_ready"]
    assert panel.tbl_charges.horizontalHeaderItem(1).text() == _TR["zh"]["col_element"]
    assert set(_TR["zh"]) == set(_TR["en"])


def test_status_and_source_labels_translate(harness):
    panel = harness.panel
    assert "3" in panel.lbl_source.text()
    panel.set_lang("en")
    assert "3" in panel.lbl_source.text()
    assert "Canvas" in panel.lbl_source.text()
    panel.set_lang("zh")
    assert "画布" in panel.lbl_source.text()


# ══════════════════════════════════════════════════════════════════════
#  结构来源 / 文件载入 / showEvent
# ══════════════════════════════════════════════════════════════════════
def test_canvas_structure_and_file_load(harness, tmp_path):
    panel = harness.panel
    assert len(panel._symbols) == 3
    assert panel._source_kind == "canvas"

    xyz = tmp_path / "water.xyz"
    xyz.write_text(
        "3\nwater\n"
        "O 0.00000000 0.00000000 0.00000000\n"
        "H 0.00000000 0.75700000 0.58700000\n"
        "H 0.00000000 -0.75700000 0.58700000\n",
        encoding="utf-8")
    assert panel.load_file(str(xyz)) is True
    assert panel._source_kind == "file"
    assert panel._symbols == WATER_SYMBOLS
    assert np.allclose(panel._coords, WATER_COORDS)
    assert "water.xyz" in panel.lbl_source.text()
    assert "3" in panel.lbl_source.text()

    # 刷新画布结构 → 重新回到画布来源
    harness.holder["canvas"] = (list(AMMONIA_SYMBOLS), AMMONIA_COORDS.copy())
    panel.btn_refresh.click()
    assert panel._source_kind == "canvas"
    assert panel._symbols == AMMONIA_SYMBOLS
    assert "画布" in panel.lbl_source.text()

    # 坏文件：状态行报错，不崩溃
    bad = tmp_path / "bad.xyz"
    bad.write_text("not an xyz", encoding="utf-8")
    assert panel.load_file(str(bad)) is False
    assert panel.lbl_status.text()


def test_show_event_syncs_canvas(harness, tmp_path):
    panel = harness.panel
    # 切页时画布结构改变 → 自动同步
    harness.holder["canvas"] = (list(AMMONIA_SYMBOLS), AMMONIA_COORDS.copy())
    panel.showEvent(QShowEvent())
    assert panel._symbols == AMMONIA_SYMBOLS

    # 手动打开文件后，文件优先，切页不覆盖
    xyz = tmp_path / "water.xyz"
    xyz.write_text(
        "3\nwater\nO 0 0 0\nH 0 0.757 0.587\nH 0 -0.757 0.587\n",
        encoding="utf-8")
    panel.load_file(str(xyz))
    harness.holder["canvas"] = (list(WATER_SYMBOLS), WATER_COORDS.copy())
    panel.showEvent(QShowEvent())
    assert panel._source_kind == "file"
    assert panel._symbols == ["O", "H", "H"]


# ══════════════════════════════════════════════════════════════════════
#  后台运行（合成结果）
# ══════════════════════════════════════════════════════════════════════
def _prepare_synthetic_run(harness, tmp_path):
    panel = harness.panel
    panel.edit_exe.setText(sys.executable)
    panel.edit_workdir.setText(str(tmp_path / "job"))
    panel._workdir_user_edited = True
    return panel


def test_run_with_synthetic_result(harness, app, monkeypatch, tmp_path):
    panel = _prepare_synthetic_run(harness, tmp_path)
    calls = []

    def fake_run(params, symbols, coords, workdir, **kwargs):
        calls.append(params.copy())
        return fake_fast_run(params, symbols, coords, workdir, **kwargs)

    use_fake_run(monkeypatch, fake_run)
    panel._set_combo_data(panel.cmb_job, "sp")
    panel.btn_run.click()

    assert wait_until(app, lambda: panel._worker is None
                      and panel._result is not None, 15)
    result = panel._result
    assert result is not None
    assert "-5.070371" in panel.lbl_energy.text()
    assert "14.63" in panel.lbl_gap.text()
    assert panel.tbl_charges.rowCount() == 3
    assert panel.tbl_charges.item(0, 2).text() == "-0.680000"
    assert panel.btn_run.isEnabled()
    assert not panel.btn_cancel.isEnabled()
    assert panel.btn_export_xyz.isEnabled()
    assert "完成" in panel.lbl_status.text()
    assert any("fake: running" in line for line in harness.logs)
    # 面板内也有实时输出窗口，与主窗口日志同步刷新
    assert "fake: running" in panel.log_view.toPlainText()
    assert calls and calls[0]["method"] == "gfn2"

    # 结束后可再次运行
    panel.btn_run.click()
    assert wait_until(app, lambda: panel._worker is None
                      and len(calls) == 2, 15)
    assert panel.btn_run.isEnabled()


def test_log_view_streams_clears_and_copies(harness, app):
    """运行输出窗口：逐行追加、可清空/复制、只保留最近的行。"""
    panel = harness.panel
    panel._log("line-1")
    panel._log("line-2")
    assert panel.log_view.isReadOnly()
    assert "line-1" in panel.log_view.toPlainText()
    assert "line-2" in panel.log_view.toPlainText()
    # 主窗口日志照旧收到，两边内容一致
    assert harness.logs[-2:] == ["line-1", "line-2"]
    assert panel.log_view.maximumBlockCount() == 3000

    panel._copy_log()
    assert "line-2" in QApplication.clipboard().text()

    panel._clear_log()
    assert panel.log_view.toPlainText() == ""
    assert panel.tabs.tabText(1) == _TR["zh"]["tab_log"]


def test_start_clears_previous_run_output(harness, app, monkeypatch, tmp_path):
    panel = _prepare_synthetic_run(harness, tmp_path)
    use_fake_run(monkeypatch, fake_fast_run)
    panel._log("stale output from an old run")
    panel.btn_run.click()
    assert wait_until(app, lambda: panel._worker is None
                      and panel._result is not None, 15)
    text = panel.log_view.toPlainText()
    assert "fake: running" in text
    assert "stale output" not in text


def test_layout_matches_orca_tabs_and_order(harness):
    """右栏版面对齐 ORCA 页：结构 → 计算设置 → 按钮 → 进度 → 状态 → 三页签。"""
    panel = harness.panel
    assert [panel.tabs.tabText(i) for i in range(panel.tabs.count())] == [
        _TR["zh"]["tab_preview"], _TR["zh"]["tab_log"],
        _TR["zh"]["tab_result"]]
    assert panel.tabs.currentIndex() == 0
    # 进度条与 ORCA 页一样是细条、初始 0
    assert panel.progress.maximumHeight() == 6
    assert panel.progress.value() == 0
    # 结构区：来源文字在按钮上面
    src_lay = panel.grp_source.layout()
    assert src_lay.itemAt(0).widget() is panel.lbl_source
    # 按钮行：左侧生成输入 / 复制命令，右侧停止 / 运行
    row = panel.layout().itemAt(2).layout()
    assert row.itemAt(0).widget() is panel.btn_preview
    assert row.itemAt(1).widget() is panel.btn_copy_cmd
    assert row.itemAt(3).widget() is panel.btn_cancel
    assert row.itemAt(4).widget() is panel.btn_run
    # 计算设置是两列表单（标签 + 控件），不再是散行
    grid = panel.grp_calc.layout()
    assert isinstance(grid, QGridLayout)
    assert grid.itemAtPosition(0, 0).widget() is panel.lbl_method
    assert grid.itemAtPosition(0, 1).widget() is panel.cmb_method
    assert grid.itemAtPosition(0, 2).widget() is panel.lbl_job
    assert grid.itemAtPosition(0, 3).widget() is panel.cmb_job


def test_input_preview_shows_command_and_xyz(harness, app):
    panel = harness.panel
    panel.edit_exe.setText("xtb.exe")
    panel._refresh_preview()
    text = panel.preview.toPlainText()
    assert _TR["zh"]["preview_cmd"] in text
    assert "xtb.exe" in text and "--gfn 2" in text
    assert _TR["zh"]["preview_xyz"] in text
    assert "3" in text.splitlines()          # 原子数行
    assert "O " in text and "H " in text
    # 切到预览页签会按当前参数重建
    panel.tabs.setCurrentIndex(0)
    app.processEvents()
    assert panel.preview.toPlainText().strip()


def test_copy_command_copies_command_line(harness):
    panel = harness.panel
    panel.edit_exe.setText("xtb.exe")
    panel._copy_command()
    copied = QApplication.clipboard().text()
    assert "xtb.exe" in copied and "--gfn 2" in copied


def test_run_switches_to_log_then_result_tab(harness, app, monkeypatch, tmp_path):
    panel = _prepare_synthetic_run(harness, tmp_path)
    use_fake_run(monkeypatch, fake_fast_run)
    panel.tabs.setCurrentIndex(0)
    panel.btn_run.click()
    assert wait_until(app, lambda: panel._worker is None
                      and panel._result is not None, 15)
    assert panel.tabs.currentIndex() == 2          # 成功后停在结果摘要
    assert panel.progress.value() == 100


def test_run_disables_parameters_and_cancel(harness, app, monkeypatch, tmp_path):
    panel = _prepare_synthetic_run(harness, tmp_path)

    def slow_run(params, symbols, coords, workdir, *, on_line=None,
                 on_progress=None, should_cancel=None, lang="zh"):
        for _ in range(400):
            if should_cancel is not None and should_cancel():
                return make_result(params, symbols, coords, workdir,
                                   cancelled=True, success=False,
                                   returncode=1)
            time.sleep(0.01)
        return make_result(params, symbols, coords, workdir)

    use_fake_run(monkeypatch, slow_run)
    panel.btn_run.click()
    assert wait_until(app, lambda: panel._worker is not None
                      and panel._worker.isRunning(), 10)
    assert not panel.cmb_method.isEnabled()
    assert not panel.btn_run.isEnabled()
    assert panel.btn_cancel.isEnabled()
    assert wait_until(app, lambda: "已运行" in panel.lbl_status.text(), 5)

    panel.btn_cancel.click()
    assert wait_until(app, lambda: panel._worker is None, 15)
    assert panel.btn_run.isEnabled()
    assert panel.cmb_method.isEnabled()
    assert not panel.btn_cancel.isEnabled()
    assert "取消" in panel.lbl_status.text()
    assert panel._result is None


# ══════════════════════════════════════════════════════════════════════
#  真机集成：水 SP
# ══════════════════════════════════════════════════════════════════════
def test_real_xtb_water_single_point(harness, app, tmp_path):
    exe = xtb.find_xtb_executable()
    if not exe:
        pytest.skip("本机没有找到 xTB 可执行文件")
    panel = harness.panel
    panel.edit_exe.setText(exe)
    panel._set_combo_data(panel.cmb_method, "gfn2")
    panel._set_combo_data(panel.cmb_job, "sp")
    panel.spn_charge.setValue(0)
    panel.spn_uhf.setValue(0)
    panel.chk_json.setChecked(True)
    panel.edit_workdir.setText(str(tmp_path / "sp"))
    panel._workdir_user_edited = True

    panel.btn_run.click()
    assert wait_until(app, lambda: panel._worker is None, 30), \
        panel.lbl_status.text()
    result = panel._result
    assert result is not None, panel.lbl_status.text()
    assert result.success is True
    assert result.cancelled is False
    assert result.energy == pytest.approx(-5.0704, abs=0.02)
    assert panel.tbl_charges.rowCount() == 3
    assert "-5.07" in panel.lbl_energy.text()
    assert "Eh" in panel.lbl_energy.text()
    assert "Hz" not in panel.lbl_vib.text()


# ══════════════════════════════════════════════════════════════════════
#  频率 / 热化学 / 结果区
# ══════════════════════════════════════════════════════════════════════
def test_frequency_and_thermo_display(harness):
    panel = harness.panel
    result = optimized_result(
        job="ohess",
        frequencies=[{"mode": 1, "frequency": 1601.2, "ir": 10.0, "symmetry": "A1"},
                     {"mode": 2, "frequency": 3700.5, "ir": 20.0, "symmetry": "A1"},
                     {"mode": 3, "frequency": 3800.1, "ir": 30.0, "symmetry": "A1"},
                     {"mode": 4, "frequency": 900.3, "ir": 5.0, "symmetry": "A1"}],
        imaginary_count=0,
        thermo={"free_energy": -5.063100, "enthalpy": -5.061200,
                "zpe": 0.021300})
    panel._display_result(result)
    assert "虚频数" in panel.lbl_vib.text()
    assert "0" in panel.lbl_vib.text()
    assert "900.30" in panel.lbl_vib.text()
    assert "-5.063100" in panel.lbl_thermo.text()
    assert "-5.061200" in panel.lbl_thermo.text()
    assert "0.021300" in panel.lbl_thermo.text()
    assert not panel.lbl_vib.isHidden()
    assert not panel.lbl_thermo.isHidden()

    panel.set_lang("en")
    assert "Imaginary modes" in panel.lbl_vib.text()
    assert "G =" in panel.lbl_thermo.text()


def test_imaginary_mode_count(harness):
    panel = harness.panel
    result = optimized_result(
        job="hess",
        frequencies=[{"mode": 1, "frequency": -412.5, "ir": 1.0,
                      "symmetry": "A1"}],
        imaginary_count=1)
    panel._display_result(result)
    assert "1" in panel.lbl_vib.text()
    assert "-412.50" in panel.lbl_vib.text()


def test_gradient_norm_display(harness):
    panel = harness.panel
    panel._display_result(make_result(gradient_norm=2.5e-04))
    assert panel.lbl_grad.text()
    assert "2.50e-04" in panel.lbl_grad.text()


# ══════════════════════════════════════════════════════════════════════
#  导出 / 送回画布
# ══════════════════════════════════════════════════════════════════════
def test_send_to_canvas(harness):
    panel = harness.panel
    panel._display_result(make_result())            # SP：无优化坐标
    assert not panel.btn_to_canvas.isEnabled()
    panel._send_to_canvas()
    assert panel.lbl_status.text() == _TR["zh"]["st_need_optimized"]

    panel._display_result(optimized_result())
    assert panel.btn_to_canvas.isEnabled()
    panel.btn_to_canvas.click()
    assert harness.loaded
    symbols, coords, label = harness.loaded[-1]
    assert symbols == WATER_SYMBOLS
    assert np.allclose(coords, WATER_COORDS)
    assert "xTB" in label
    assert "画布" in panel.lbl_status.text()


def test_export_xyz_gjf_json(harness, monkeypatch, tmp_path):
    panel = harness.panel
    panel._display_result(optimized_result(formula="H2O"))
    panel.spn_charge.setValue(0)
    panel.spn_uhf.setValue(0)

    xyz_path = tmp_path / "out.xyz"
    gjf_path = tmp_path / "out.gjf"
    json_path = tmp_path / "out.json"

    def patch_save(path):
        monkeypatch.setattr(
            xtb_panel.QFileDialog, "getSaveFileName",
            staticmethod(lambda *a, **k: (str(path), "")))

    patch_save(xyz_path)
    panel.btn_export_xyz.click()
    assert xyz_path.is_file()
    lines = xyz_path.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0].strip() == "3"
    sym_xyz, coords_xyz = load_atoms(str(xyz_path))
    assert sym_xyz == WATER_SYMBOLS
    assert np.allclose(coords_xyz, WATER_COORDS, atol=1e-8)

    patch_save(gjf_path)
    panel.btn_export_gjf.click()
    assert gjf_path.is_file()
    sym_gjf, coords_gjf = load_atoms(str(gjf_path))
    assert sym_gjf == WATER_SYMBOLS
    assert np.allclose(coords_gjf, WATER_COORDS, atol=1e-8)

    patch_save(json_path)
    panel.btn_export_json.click()
    assert json_path.is_file()
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["energy"] == pytest.approx(-5.070371)
    assert data["symbols"] == WATER_SYMBOLS
    assert data["method"] == "gfn2"


def test_scan_result_plot_and_trajectory_export(harness, monkeypatch, tmp_path):
    panel = harness.panel
    result = scan_result(n=4)
    panel._display_result(result)
    assert not panel.grp_scan.isHidden()
    assert panel.scan_figure.axes
    axes = panel.scan_figure.axes[0]
    line = axes.get_lines()[0]
    assert len(line.get_xdata()) == 4
    assert "4" in panel.lbl_scan_summary.text()
    assert "ΔE" in panel.lbl_scan_summary.text()
    assert panel.btn_export_scan.isEnabled()

    traj = tmp_path / "scan.xyz"
    monkeypatch.setattr(
        xtb_panel.QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **k: (str(traj), "")))
    panel.btn_export_scan.click()
    assert traj.is_file()
    lines = traj.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4 * (3 + 2)          # 帧数 ×（原子数 + 帧头 2 行）
    assert lines[0].strip() == "3"
    assert lines[1].startswith("frame 1")

    # 切英文后图注也重译
    panel.set_lang("en")
    axes = panel.scan_figure.axes[0]
    assert axes.get_xlabel() == _TR["en"]["scan_x"]
    assert "frames" in panel.lbl_scan_summary.text()


def test_no_result_exports_are_safe(harness):
    panel = harness.panel
    panel._clear_result()
    panel._export_xyz()
    panel._export_json()
    panel._export_scan_traj()
    panel._send_to_canvas()
    assert panel.lbl_status.text() == _TR["zh"]["st_no_result"]
    for button in (panel.btn_export_xyz, panel.btn_export_gjf,
                   panel.btn_export_json, panel.btn_export_scan,
                   panel.btn_to_canvas):
        assert not button.isEnabled()


# ══════════════════════════════════════════════════════════════════════
#  参数联动 / 预览 / 设置持久化
# ══════════════════════════════════════════════════════════════════════
def test_gxtb_solvation_hint_and_params(harness):
    panel = harness.panel
    panel._set_combo_data(panel.cmb_solvation, "alpb")
    assert panel.cmb_solvent.isEnabled()
    assert panel.cmb_solvent.count() > 0

    panel._set_combo_data(panel.cmb_method, "gxtb")
    assert not panel.cmb_solvation.isEnabled()
    assert panel.lbl_gxtb_hint.isVisibleTo(panel)
    params = panel._params()
    assert params["method"] == "gxtb"
    assert params["solvation"] == "gas"

    panel._set_combo_data(panel.cmb_method, "gfn2")
    assert panel.cmb_solvation.isEnabled()

    panel._set_combo_data(panel.cmb_solvation, "gas")
    assert not panel.cmb_solvent.isEnabled()


def test_job_scan_and_ts_widgets(harness):
    panel = harness.panel
    panel._set_combo_data(panel.cmb_job, "sp")
    assert panel.scan_box.isHidden()
    assert panel.lbl_ts_hint.isHidden()
    panel._set_combo_data(panel.cmb_job, "scan")
    assert not panel.scan_box.isHidden()
    panel._set_combo_data(panel.cmb_job, "ts")
    assert not panel.lbl_ts_hint.isHidden()
    assert panel.scan_box.isHidden()
    panel._set_combo_data(panel.cmb_job, "opt")


def test_preview_command_writes_log(harness, tmp_path):
    panel = harness.panel
    panel.edit_exe.setText(sys.executable)
    panel._preview_command()
    assert panel.lbl_status.text() == _TR["zh"]["st_preview"]
    assert any("命令" in line for line in harness.logs)


def test_settings_roundtrip_and_corrupt_file(harness, settings_path, monkeypatch):
    panel = harness.panel
    panel.edit_exe.setText(sys.executable)
    panel._set_combo_data(panel.cmb_method, "gfn1")
    panel._set_combo_data(panel.cmb_job, "hess")
    panel.spn_parallel.setValue(2)
    panel.spn_charge.setValue(1)
    panel.chk_molden.setChecked(True)
    panel._save_settings()
    assert settings_path.is_file()

    other = XtbPanel(get_structure=lambda: (list(WATER_SYMBOLS), WATER_COORDS))
    try:
        assert other.edit_exe.text() == sys.executable
        assert other.cmb_method.currentData() == "gfn1"
        assert other.cmb_job.currentData() == "hess"
        assert other.spn_parallel.value() == 2
        assert other.spn_charge.value() == 1
        assert other.chk_molden.isChecked()
    finally:
        other.shutdown()

    # 损坏的 ini：静默回退默认值
    settings_path.write_text("this is not an ini = [[[", encoding="utf-8")
    broken = XtbPanel(get_structure=lambda: (list(WATER_SYMBOLS), WATER_COORDS))
    try:
        assert broken.cmb_method.currentData() == "gfn2"
        assert broken.cmb_job.currentData() == "opt"
        expected = xtb.find_xtb_executable()
        if expected:
            assert broken.edit_exe.text().strip() == expected
    finally:
        broken.shutdown()


def test_saved_workdir_and_user_override(harness, settings_path):
    panel = harness.panel
    panel.edit_exe.setText(sys.executable)
    panel.edit_workdir.setText(r"C:\some\workdir")
    panel._workdir_user_edited = True
    panel._save_settings()
    assert "C:\\some\\workdir" in settings_path.read_text(encoding="utf-8")

    other = XtbPanel(get_structure=lambda: (list(WATER_SYMBOLS), WATER_COORDS))
    try:
        assert other.edit_workdir.text() == r"C:\some\workdir"
        # 上次会话保存的是“基目录”，运行时在其下新建独立的时间戳目录
        resolved = Path(other._resolve_workdir())
        assert resolved.parent == Path(r"C:\some\workdir")
        assert resolved != Path(r"C:\some\workdir")
    finally:
        other.shutdown()


def test_default_workdir_paths(harness, tmp_path):
    panel = harness.panel
    # 画布结构 → 基目录 %TEMP%/MolStudio_xtb，本次运行目录再加时间戳子目录
    base = panel._default_workdir()
    assert base.name == "MolStudio_xtb"
    default = Path(panel._resolve_workdir())
    assert default.parent == base
    assert re.fullmatch(r"\d{8}_\d{6}(_\d+)?", default.name)

    # 文件结构 → 基目录 <文件目录>/<stem>_xtb，运行目录再加时间戳子目录
    xyz = tmp_path / "methane.xyz"
    xyz.write_text(
        "1\nmethane\nC 0.0 0.0 0.0\n", encoding="utf-8")
    assert panel.load_file(str(xyz))
    base = panel._default_workdir()
    assert base.name == "methane_xtb"
    assert base.parent == tmp_path
    default = Path(panel._resolve_workdir())
    assert default.parent == base
    assert re.fullmatch(r"\d{8}_\d{6}(_\d+)?", default.name)

    # 用户显式填写的工作目录作为基目录，不允许两次运行复用同一目录
    custom = tmp_path / "custom_dir"
    panel.edit_workdir.setText(str(custom))
    panel._workdir_user_edited = True
    first = Path(panel._resolve_workdir())
    assert first.parent == custom
    first.mkdir(parents=True, exist_ok=True)   # 模拟第一次运行已创建目录
    # 模拟一次运行后：基目录记录、用户编辑标记复位
    panel._workdir_base = str(custom)
    panel._workdir_user_edited = False
    panel.edit_workdir.setText(str(first))
    second = Path(panel._resolve_workdir())
    assert second.parent == custom
    assert second != first


def test_params_carry_xtb_exe_path(harness, tmp_path):
    panel = harness.panel
    exe = str(tmp_path / "my_xtb.exe")
    panel.edit_exe.setText(exe)
    params = panel._params()
    assert params["xtb_exe"] == exe
    assert params["lang"] == panel.lang


def test_refresh_keeps_custom_base_unless_structure_changed(harness):
    panel = harness.panel
    panel._workdir_base = r"C:\custom\base"
    panel._workdir_user_edited = False
    # 同一结构点“刷新画布结构”：基目录不应丢失
    panel._refresh_from_canvas()
    assert panel._workdir_base == r"C:\custom\base"
    # 画布结构真的变了：基目录回到默认位置
    panel._get_structure = lambda: (
        ["C", "H", "H", "H", "H"],
        np.array([[0.0, 0.0, 0.0], [0.63, 0.63, 0.63],
                  [-0.63, -0.63, 0.63], [-0.63, 0.63, -0.63],
                  [0.63, -0.63, -0.63]]),
    )
    panel._refresh_from_canvas()
    assert panel._workdir_base == ""


def test_run_failure_and_missing_structure(harness, app, monkeypatch, tmp_path):
    panel = _prepare_synthetic_run(harness, tmp_path)

    def boom(params, symbols, coords, workdir, **kwargs):
        raise xtb.XtbError("boom!")

    use_fake_run(monkeypatch, boom)
    panel._set_combo_data(panel.cmb_job, "sp")
    panel.btn_run.click()
    assert wait_until(app, lambda: panel._worker is None, 15)
    assert "计算失败" in panel.lbl_status.text()
    assert "boom!" in panel.lbl_status.text()
    assert panel.btn_run.isEnabled()
    assert panel._result is None

    # 没有结构 → 状态行提示，不崩溃
    panel._clear_structure()
    panel.btn_run.click()
    assert "没有结构" in panel.lbl_status.text()


def test_failed_result_is_not_reported_as_done(harness, app, monkeypatch, tmp_path):
    panel = _prepare_synthetic_run(harness, tmp_path)

    def failed(params, symbols, coords, workdir, **kwargs):
        return make_result(params, symbols, coords, workdir,
                           success=False, returncode=1,
                           normal_termination=False, energy=None,
                           output_text="[ERROR] Parameter file not found",
                           warnings=["参数文件缺失"])

    use_fake_run(monkeypatch, failed)
    panel._set_combo_data(panel.cmb_job, "sp")
    panel.btn_run.click()
    assert wait_until(app, lambda: panel._worker is None, 15)
    assert panel._result is None
    assert "计算失败" in panel.lbl_status.text()
    assert "完成" not in panel.lbl_status.text()
    assert not panel.btn_export_xyz.isEnabled()
    assert not panel.btn_to_canvas.isEnabled()


def test_scan_requires_xcontrol(harness, app, tmp_path):
    panel = _prepare_synthetic_run(harness, tmp_path)
    panel._set_combo_data(panel.cmb_job, "scan")
    panel.txt_xcontrol.setPlainText("")
    panel.btn_run.click()
    assert panel._worker is None
    assert "参数不合法" in panel.lbl_status.text()
    assert panel.btn_run.isEnabled()


def test_validation_error_language_follows_panel(harness, app, tmp_path):
    panel = _prepare_synthetic_run(harness, tmp_path)
    assert panel._params()["lang"] == "zh"
    panel.set_lang("en")
    assert panel._params()["lang"] == "en"
    panel._set_combo_data(panel.cmb_job, "scan")
    panel.txt_xcontrol.setPlainText("")
    panel.btn_run.click()
    assert panel._worker is None
    text = panel.lbl_status.text()
    assert "Invalid parameters" in text
    assert not CJK_RE.search(text)
    panel.set_lang("zh")
    assert panel._params()["lang"] == "zh"


def test_shutdown_is_idempotent(harness):
    panel = harness.panel
    panel.shutdown()
    panel.shutdown()
    assert panel._worker is None


def test_busy_shutdown_stops_worker(harness, app, monkeypatch, tmp_path):
    panel = _prepare_synthetic_run(harness, tmp_path)

    def slow_run(params, symbols, coords, workdir, *, on_line=None,
                 on_progress=None, should_cancel=None, lang="zh"):
        for _ in range(500):
            if should_cancel is not None and should_cancel():
                return make_result(params, symbols, coords, workdir,
                                   cancelled=True, success=False)
            time.sleep(0.01)
        return make_result(params, symbols, coords, workdir)

    use_fake_run(monkeypatch, slow_run)
    panel.btn_run.click()
    assert wait_until(app, lambda: panel._worker is not None
                      and panel._worker.isRunning(), 10)
    panel.shutdown()
    app.processEvents()
    assert panel._worker is None
    assert not panel._busy()
