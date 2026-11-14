# -*- coding: utf-8 -*-
"""运行日志三页签控制台（``molstudio.ui.runlog_tabs.RunLogConsole``）。

这些用例全部走 offscreen Qt：不显示窗口、不弹 ``QFileDialog``（保存只测
``_save_to()`` 无对话框助手）。运行::

    python -m pytest tests/test_runlog_tabs.py -q
"""

import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from PyQt5.QtGui import QTextCursor  # noqa: E402
from PyQt5.QtWidgets import (  # noqa: E402
    QApplication,
    QSizePolicy,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

#: notify() 追加的 "HH:MM:SS  " 时间戳前缀
_TS = re.compile(r"^\d{2}:\d{2}:\d{2}  ")

_ZH_TABS = ["运行日志", "计算输出", "错误信息"]
_EN_TABS = ["Run Log", "Output", "Errors"]


@pytest.fixture(scope="module")
def qapp():
    """整个模块共用一个 QApplication（Qt 不允许重复创建）。"""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def console(qapp):
    """带一行启动日志的 console；log_text 是外部传入的真实 QTextEdit。"""
    from molstudio.ui.runlog_tabs import RunLogConsole

    src = QTextEdit()
    src.setObjectName("RunLog")
    src.setReadOnly(True)
    src.setPlainText("boot line")
    widget = RunLogConsole(src)
    yield widget, src
    widget.close()
    widget.deleteLater()
    qapp.processEvents()


def _last_line(view):
    lines = [line for line in view.toPlainText().splitlines() if line.strip()]
    return lines[-1] if lines else ""


# ══════════════════════════════════════════════════════════════════════════ #
#  结构：三页签 + 原 log_text reparent 到第 0 页
# ══════════════════════════════════════════════════════════════════════════ #
def test_structure_three_tabs_and_reparents_log_text(console):
    console, src = console
    assert console.log_text is src, "必须复用主窗口那个 QTextEdit 实例"
    assert isinstance(console.tabs, QTabWidget)
    assert console.objectName() == "RunLogConsole"
    assert console.tabs.objectName() == "RunLogTabs"
    assert console.tabs.count() == 3
    assert console.tabs.widget(0) is src          # 原控件就在「运行日志」页签里
    assert console.tabs.indexOf(src) == 0
    assert src.toPlainText() == "boot line"       # 原内容没丢
    assert isinstance(console.tabs.widget(1), QTextEdit)
    assert isinstance(console.tabs.widget(2), QTextEdit)
    assert console.tabs.widget(1).isReadOnly()
    assert console.tabs.widget(2).isReadOnly()
    assert [console.tabs.tabText(i) for i in range(3)] == _ZH_TABS
    assert console.current_view() is src
    assert console.sizePolicy().verticalPolicy() == QSizePolicy.Expanding


def test_current_view_follows_selected_tab(console):
    console, src = console
    console.tabs.setCurrentIndex(1)
    assert console.current_view() is console.tabs.widget(1)
    console.tabs.setCurrentIndex(2)
    assert console.current_view() is console.tabs.widget(2)
    console.tabs.setCurrentIndex(0)
    assert console.current_view() is src


def test_reparents_log_text_out_of_old_layout(qapp):
    """主窗口把 log_text 先放进旧 dock 布局再交给本控件，也要能干净摘出来。"""
    from molstudio.ui.runlog_tabs import RunLogConsole

    old_dock = QWidget()
    old_layout = QVBoxLayout(old_dock)
    src = QTextEdit()
    src.setPlainText("old text")
    old_layout.addWidget(src)

    widget = RunLogConsole(src)
    try:
        assert old_layout.count() == 0, "旧布局里不能留下悬空项"
        assert src.parentWidget() is not old_dock
        assert widget.tabs.widget(0) is src
        assert src.toPlainText() == "old text"
    finally:
        widget.close()
        widget.deleteLater()
        old_dock.deleteLater()
        qapp.processEvents()


def test_card_stylesheet_has_reference_tokens(console):
    """白卡片 + #E5E9F0 边框 + 8px 圆角 + 9pt 页签 + 等宽 #2C3E50。"""
    console, _src = console
    qss = console.styleSheet()
    assert "#FFFFFF" in qss
    assert "#E5E9F0" in qss
    assert "border-radius: 8px" in qss
    assert "9pt" in qss
    assert "Consolas" in qss
    assert "#2C3E50" in qss


# ══════════════════════════════════════════════════════════════════════════ #
#  notify() 过滤 + 时间戳 + 不重复写主日志
# ══════════════════════════════════════════════════════════════════════════ #
@pytest.mark.parametrize("msg", [
    "SCF Done:  E(RB3LYP) = -76.4",
    "Normal termination of Gaussian 16",
    "Multiwfn output written",
    "xtb converged in 12 cycles",
    "cube 已写出: homo.cub",
    "计算完成",
])
def test_notify_routes_computation_output(console, msg):
    console, src = console
    main_before = src.toPlainText()
    console.notify(msg)
    output = console.tabs.widget(1)
    assert msg in output.toPlainText()
    # 时间戳前缀 "HH:MM:SS  "
    assert _TS.match(_last_line(output))
    assert _last_line(output).endswith(msg)
    # 不重复写运行日志、不污染错误页签
    assert src.toPlainText() == main_before
    assert console.tabs.widget(2).toPlainText() == ""


@pytest.mark.parametrize("msg", [
    "Error termination",
    "任务失败：找不到可执行文件",
    "Traceback (most recent call last)",
    "检测到异常",
    "程序崩溃了",
])
def test_notify_routes_errors(console, msg):
    console, src = console
    main_before = src.toPlainText()
    console.notify(msg)
    error = console.tabs.widget(2)
    assert msg in error.toPlainText()
    assert _TS.match(_last_line(error))
    assert src.toPlainText() == main_before
    assert console.tabs.widget(1).toPlainText() == ""


def test_notify_neutral_message_does_not_touch_views(console):
    console, src = console
    main_before = src.toPlainText()
    output_before = console.tabs.widget(1).toPlainText()
    error_before = console.tabs.widget(2).toPlainText()
    console.notify("normal chatter")
    assert src.toPlainText() == main_before, "主窗口自己已经写过 log_text，不能再重复追加"
    assert console.tabs.widget(1).toPlainText() == output_before
    assert console.tabs.widget(2).toPlainText() == error_before


def test_notify_ignores_empty_message(console):
    console, _src = console
    console.notify("")
    console.notify(None)
    assert console.tabs.widget(1).toPlainText() == ""
    assert console.tabs.widget(2).toPlainText() == ""


# ══════════════════════════════════════════════════════════════════════════ #
#  clear_all / 自动滚动
# ══════════════════════════════════════════════════════════════════════════ #
def test_clear_all_clears_three_views(console):
    console, src = console
    console.notify("SCF Done")
    console.notify("Error termination")
    assert console.tabs.widget(1).toPlainText()
    assert console.tabs.widget(2).toPlainText()
    console.clear_all()
    assert src.toPlainText() == ""
    assert console.tabs.widget(1).toPlainText() == ""
    assert console.tabs.widget(2).toPlainText() == ""


def test_auto_scroll_toggle_and_append_no_crash(console):
    console, _src = console
    assert console.auto_scroll() is True
    assert console.auto_scroll_btn.isChecked() is True

    console.set_auto_scroll(False)
    assert console.auto_scroll() is False
    assert console.auto_scroll_btn.isChecked() is False

    # 关掉自动滚动后照常写入、不崩
    console.notify("SCF Done while frozen")
    assert "SCF Done while frozen" in console.tabs.widget(1).toPlainText()

    # 复选框点击 → set_auto_scroll 联动（信号双向不会回环）
    console.auto_scroll_btn.setChecked(True)
    assert console.auto_scroll() is True
    console.auto_scroll_btn.setChecked(False)
    assert console.auto_scroll() is False

    console.set_auto_scroll(True)
    assert console.auto_scroll() is True


# ══════════════════════════════════════════════════════════════════════════ #
#  工具条按钮 / 复制 / 保存助手
# ══════════════════════════════════════════════════════════════════════════ #
def test_toolbar_buttons_exist(console):
    console, _src = console
    expected = {
        "auto_scroll_btn": "RunLogAutoScroll",
        "clear_btn": "RunLogClear",
        "copy_btn": "RunLogCopy",
        "save_btn": "RunLogSave",
    }
    for attr, object_name in expected.items():
        btn = getattr(console, attr)
        assert btn.objectName() == object_name
        assert btn.text(), f"{object_name} 缺少文字"
        assert btn.toolTip(), f"{object_name} 缺少 tooltip"
    # 兼容别名指向同一批按钮
    assert console.btn_clear is console.clear_btn
    assert console.btn_copy is console.copy_btn
    assert console.btn_save is console.save_btn
    assert console.toolbar.objectName() == "RunLogToolbar"


def test_clear_button_clears_all(console):
    console, src = console
    console.notify("Error termination")
    src.setPlainText("main text")
    console.clear_btn.click()
    assert src.toPlainText() == ""
    assert console.tabs.widget(2).toPlainText() == ""


def test_copy_current_view_whole_text(console, qapp):
    console, _src = console
    console.tabs.setCurrentIndex(1)
    output = console.tabs.widget(1)
    output.setPlainText("alpha line\nbeta line")
    console.copy_btn.click()
    clipboard = qapp.clipboard().text()
    assert "alpha line" in clipboard
    assert "beta line" in clipboard


def test_copy_current_view_selection(console, qapp):
    console, _src = console
    console.tabs.setCurrentIndex(2)
    error = console.tabs.widget(2)
    error.setPlainText("first error\nsecond error")
    cursor = error.textCursor()
    cursor.movePosition(QTextCursor.Start)
    cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
    error.setTextCursor(cursor)
    copied = console.copy_current()
    assert copied == "first error"
    assert qapp.clipboard().text() == "first error"


def test_save_to_writes_utf8_without_dialog(console, tmp_path):
    console, _src = console
    console.tabs.setCurrentIndex(2)
    error = console.tabs.widget(2)
    error.setPlainText("错误信息: 测试失败")
    target = tmp_path / "runlog.txt"
    written = console._save_to(str(target))
    assert written == str(target)
    assert target.read_text(encoding="utf-8") == "错误信息: 测试失败"

    # 显式传 view 也要能用
    other = tmp_path / "output.txt"
    console._save_to(str(other), console.tabs.widget(1))
    assert other.exists()


# ══════════════════════════════════════════════════════════════════════════ #
#  语言切换
# ══════════════════════════════════════════════════════════════════════════ #
def test_set_lang_en_then_back_zh(console):
    console, _src = console
    console.set_lang("en")
    assert [console.tabs.tabText(i) for i in range(3)] == _EN_TABS
    assert console.auto_scroll_btn.text() == "Auto-scroll"
    assert console.clear_btn.text() == "Clear"
    assert console.copy_btn.text() == "Copy"
    assert console.save_btn.text() == "Save"
    assert console.tabs.tabToolTip(0)

    console.set_lang("zh")
    assert [console.tabs.tabText(i) for i in range(3)] == _ZH_TABS
    assert console.auto_scroll_btn.text() == "自动滚动"
    assert console.clear_btn.text() == "清空"
    assert console.copy_btn.text() == "复制"
    assert console.save_btn.text() == "保存"


def test_console_without_external_log_text_creates_own_view(qapp):
    from molstudio.ui.runlog_tabs import RunLogConsole

    widget = RunLogConsole(None)
    try:
        assert isinstance(widget.log_text, QTextEdit)
        assert widget.log_text.objectName() == "RunLog"
        assert widget.tabs.count() == 3
        assert widget.tabs.widget(0) is widget.log_text
    finally:
        widget.close()
        widget.deleteLater()
        qapp.processEvents()
