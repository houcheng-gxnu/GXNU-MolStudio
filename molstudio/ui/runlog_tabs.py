# -*- coding: utf-8 -*-
"""runlog_tabs.py — 运行日志控制台：运行日志 / 计算输出 / 错误信息 三个页签。

背景
----
主窗口原来只有一个 ``QTextEdit``（``self.log_text``，objectName ``RunLog``，见
``_setup_log_dock``），所有面板的日志、Multiwfn/Gaussian/xTB 的输出和报错都往
同一个地方灌：出问题时错误信息混在正常日志里，翻起来很累。本模块把这个单文本
框升级成参考版式的三页签控制台，**控件实例仍是原来那一个**（``self.log_text``
直接 reparent 到第一个页签），因此主窗口现有的 ``_append_log()`` /
``_append_log_plain()`` / ``_clear_log_text()`` 全部不用改。

版式
----
* 页签：运行日志（原 ``log_text``）/ 计算输出 / 错误信息；
* 工具条：自动滚动（checkable，默认开）/ 清空 / 复制 / 保存；
* 白卡片、1px ``#E5E9F0`` 边框、8px 圆角、页签字体 9pt、正文 Consolas 等宽
  ``#2C3E50`` —— 与画布工具条（``studio_canvas_bar``）同一套浅色 token。
* 高度策略 Expanding：放进 dock/布局后由宿主决定实际高度（原来 144px 的固定
  高度仍由主窗口的 ``_setup_log_dock`` / ``_toggle_log_dock`` 管，本模块不碰）。
* 「全部（过滤下拉）」在需求里标注为可选，未实现（三个页签本身已覆盖分类），
  见 ``_TEXTS`` 中缺失的 ``filter_combo``。

过滤规则（``notify``，大小写不敏感子串）
----------------------------------------
* 错误信息：失败 / 错误 / failed / error termination / traceback / 异常 / 崩溃
* 计算输出：scf done / normal termination / multiwfn / gaussian / orca / xtb /
  cube / cub / 计算完成 / 已完成 / 输出 / iteration / converged
* ``notify`` **不再写运行日志**：主窗口在调用前已经 ``_append_log(msg)`` 写进
  ``log_text`` 了，再写一次就会每行出现两遍。

集成（主窗口）::

    from molstudio.ui.runlog_tabs import RunLogConsole

    self.runlog = RunLogConsole(self.log_text)   # 原 QTextEdit 被 reparent 到页签
    lay.addWidget(self.runlog)                   # 接替原来的 lay.addWidget(self.log_text)

    # _append_log() 末尾（已写 log_text 之后）：
    self.runlog.notify(msg)
    # 语言切换 / 清空按钮：
    self.runlog.set_lang(lang)
    self.runlog.clear_all()

注意
----
* ``self.log_text`` 始终是公开属性，且指向主窗口原来那个 ``QTextEdit`` 实例
  （传入 ``None`` 时才内部新建一个）。
* ``notify`` / ``clear_all`` / 复制 / 保存都不连接 ``textChanged`` 之类的回环信号，
  不会因为主窗口往 ``log_text`` 里追加而递归。
* 测试里不弹 ``QFileDialog``：``_save_to(path)`` 是可直接调用的无对话框落盘助手。
"""

from __future__ import annotations

import os
from datetime import datetime

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QTextCursor
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QSizePolicy,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

#: 保存对话框优先走统一的「记住上次目录」助手；不可用时退回 QFileDialog。
try:  # pragma: no cover - 正常仓库里一定可用，只是给独立拷走文件的场景兜底
    from molstudio.ui.file_dialogs import save_file as _save_file
except Exception:  # noqa: BLE001
    _save_file = None

__all__ = ["RunLogConsole"]

# ── 过滤关键词（全部小写；中文子串不受 lower() 影响）──────────────────────
_ERROR_KEYWORDS = (
    "失败", "错误", "failed", "error termination", "traceback", "异常", "崩溃",
)
_OUTPUT_KEYWORDS = (
    "scf done", "normal termination", "multiwfn", "gaussian", "orca", "xtb",
    "cube", "cub", "计算完成", "已完成", "输出", "iteration", "converged",
)

#: 页签顺序：0 = 运行日志（原 log_text），1 = 计算输出，2 = 错误信息
_TAB_KEYS = ("tab_main", "tab_output", "tab_error")

# ── 中英文字（set_lang 用；键 → {zh, en}）─────────────────────────────────
_TEXTS = {
    "tab_main": {"zh": "运行日志", "en": "Run Log"},
    "tab_output": {"zh": "计算输出", "en": "Output"},
    "tab_error": {"zh": "错误信息", "en": "Errors"},
    "tip_tab_main": {
        "zh": "主运行日志（主窗口每条日志都会写入这里）",
        "en": "Main run log (every main-window log line is written here)",
    },
    "tip_tab_output": {
        "zh": "SCF / 优化 / Multiwfn / Gaussian / ORCA / xTB 等计算输出",
        "en": "Computation output from SCF, optimization, Multiwfn, Gaussian, ORCA, xTB…",
    },
    "tip_tab_error": {
        "zh": "失败、错误、异常、崩溃与 traceback",
        "en": "Failures, errors, exceptions, crashes and tracebacks",
    },
    "btn_auto_scroll": {"zh": "自动滚动", "en": "Auto-scroll"},
    "btn_clear": {"zh": "清空", "en": "Clear"},
    "btn_copy": {"zh": "复制", "en": "Copy"},
    "btn_save": {"zh": "保存", "en": "Save"},
    "tip_auto_scroll": {
        "zh": "新日志到达时自动滚动到最新一行（取消勾选可固定查看历史）",
        "en": "Scroll to the newest line when new log arrives (uncheck to freeze the view)",
    },
    "tip_clear": {
        "zh": "清空运行日志 / 计算输出 / 错误信息三个视图（不影响任何计算状态）",
        "en": "Clear all three views (does not touch computation state)",
    },
    "tip_copy": {
        "zh": "复制当前页签的选中文本；没有选中时复制整页",
        "en": "Copy the selection of the current tab, or the whole tab when nothing is selected",
    },
    "tip_save": {
        "zh": "把当前页签保存为 UTF-8 文本文件",
        "en": "Save the current tab as a UTF-8 text file",
    },
    "dlg_save": {"zh": "保存当前日志视图", "en": "Save current log view"},
    "filter_txt": {
        "zh": "文本文件 (*.txt);;所有文件 (*.*)",
        "en": "Text files (*.txt);;All files (*.*)",
    },
}

# ── 样式表：白卡片 + 1px #E5E9F0 + 8px 圆角 + 9pt 页签 + 等宽正文 ────────
_CONSOLE_QSS = """
QWidget#RunLogConsole {
    background: #FFFFFF;
    border: 1px solid #E5E9F0;
    border-radius: 8px;
}
QWidget#RunLogToolbar {
    background: transparent;
    border: none;
}
QToolButton#RunLogAutoScroll, QToolButton#RunLogClear,
QToolButton#RunLogCopy, QToolButton#RunLogSave {
    background: #FFFFFF;
    border: 1px solid #E5E9F0;
    border-radius: 8px;
    padding: 2px 10px;
    color: #5A6B85;
    font-size: 9pt;
}
QToolButton#RunLogAutoScroll:hover, QToolButton#RunLogClear:hover,
QToolButton#RunLogCopy:hover, QToolButton#RunLogSave:hover {
    background: #F4F7FB;
    color: #2C3E50;
}
QToolButton#RunLogAutoScroll:checked {
    background: #EDF2F9;
    color: #2C3E50;
    border-color: #C9D6E5;
}
QTabWidget#RunLogTabs::pane {
    background: #FFFFFF;
    border: 1px solid #E5E9F0;
    border-radius: 6px;
    top: -1px;
}
QTabWidget#RunLogTabs QTabBar::tab {
    background: transparent;
    border: none;
    padding: 4px 14px;
    margin-right: 4px;
    color: #7A8AA0;
    font-size: 9pt;
}
QTabWidget#RunLogTabs QTabBar::tab:selected {
    color: #2C3E50;
    font-weight: bold;
    border-bottom: 2px solid #C9D6E5;
}
QTabWidget#RunLogTabs QTabBar::tab:hover:!selected {
    color: #2C3E50;
}
QTabWidget#RunLogTabs QTextEdit {
    background: #FFFFFF;
    color: #2C3E50;
    border: none;
    padding: 4px 6px;
    font-family: Consolas, "Cascadia Mono", "Courier New", monospace;
    font-size: 9pt;
}
"""


def _mono_font(point_size: int = 9) -> QFont:
    """日志正文等宽字体：Consolas 打头，缺失时由 Qt 回退到系统等宽字体。"""
    font = QFont("Consolas")
    font.setStyleHint(QFont.Monospace)
    font.setFixedPitch(True)
    font.setPointSize(point_size)
    return font


class RunLogConsole(QWidget):
    """运行日志三页签控制台（白卡片 + 小工具条）。

    Parameters
    ----------
    log_text:
        主窗口已经存在、并且仍在被 ``_append_log()`` 写入的 ``QTextEdit``。
        传入时这个**实例**会被 reparent 到第一个页签「运行日志」，之后
        ``console.log_text is log_text`` 恒成立；``None`` 时内部新建一个。
    parent:
        常规 Qt 父控件（宿主 dock / 布局）。

    Attributes
    ----------
    log_text:
        第一个页签的 ``QTextEdit``（传入实例或内部新建），公开可写引用。
    output_text / error_text:
        第二个 / 第三个页签的新建只读 ``QTextEdit``。
    tabs:
        页签容器（``QTabWidget``，objectName ``RunLogTabs``）。
    auto_scroll_btn / clear_btn / copy_btn / save_btn:
        工具条按钮（同时提供 ``btn_auto_scroll`` 等别名）。
    """

    def __init__(self, log_text=None, parent=None):
        super().__init__(parent)
        self.setObjectName("RunLogConsole")
        # 普通 QWidget 默认不画样式表背景/边框，必须打开 WA_StyledBackground。
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_CONSOLE_QSS)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        self._lang = "zh"
        self._auto_scroll = True

        # ── 三个视图：第一个尽量复用主窗口的 log_text 实例 ──
        if log_text is None:
            log_text = self._make_view("RunLog")
        else:
            self._detach(log_text)
        self.log_text = log_text
        self.output_text = self._make_view("RunLogOutput")
        self.error_text = self._make_view("RunLogErrors")
        self._views = (self.log_text, self.output_text, self.error_text)

        # ── 页签 ──
        self.tabs = QTabWidget()
        self.tabs.setObjectName("RunLogTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        for key, view in zip(_TAB_KEYS, self._views):
            self.tabs.addTab(view, _TEXTS[key]["zh"])
        self.tab_widget = self.tabs  # 语义别名，方便宿主代码书写

        # ── 工具条 ──
        self._build_toolbar()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(6)
        lay.addWidget(self.toolbar)
        lay.addWidget(self.tabs, 1)

        self._apply_lang()

    # ══════════════════════════════════════════════════════════════════════ #
    #  构造辅助
    # ══════════════════════════════════════════════════════════════════════ #
    @staticmethod
    def _make_view(object_name: str) -> QTextEdit:
        """新建一个只读、无边框、等宽的日志视图。"""
        view = QTextEdit()
        view.setObjectName(object_name)
        view.setReadOnly(True)
        view.setUndoRedoEnabled(False)
        view.setAcceptRichText(False)
        view.setLineWrapMode(QTextEdit.WidgetWidth)
        view.setFrameShape(QFrame.NoFrame)
        view.setFont(_mono_font())
        view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return view

    @staticmethod
    def _detach(widget: QWidget) -> None:
        """把 log_text 从旧父布局里摘出来，稍后由 addTab() reparent。

        主窗口可能在构造本控件之前已经把 ``log_text`` 放进旧 dock 的布局里；
        不先 removeWidget 的话，旧布局仍会继续管理它的几何。全程 try/except：
        摘不出来也不影响后续 addTab 的 reparent。
        """
        try:
            old_parent = widget.parentWidget()
            if old_parent is not None:
                old_layout = old_parent.layout()
                if old_layout is not None:
                    old_layout.removeWidget(widget)
            widget.setParent(None)
        except Exception:  # noqa: BLE001 - 布局状态千奇百怪，绝不因此崩
            pass

    def _build_toolbar(self) -> None:
        """自动滚动 / 清空 / 复制 / 保存 一行小工具条。"""
        self.toolbar = QWidget()
        self.toolbar.setObjectName("RunLogToolbar")
        row = QHBoxLayout(self.toolbar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        def _mk_btn(object_name):
            btn = QToolButton()
            btn.setObjectName(object_name)
            btn.setAutoRaise(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.NoFocus)
            return btn

        self.auto_scroll_btn = _mk_btn("RunLogAutoScroll")
        self.auto_scroll_btn.setCheckable(True)
        self.auto_scroll_btn.setChecked(True)
        self.clear_btn = _mk_btn("RunLogClear")
        self.copy_btn = _mk_btn("RunLogCopy")
        self.save_btn = _mk_btn("RunLogSave")

        # 兼容别名：宿主/测试用哪个名字都行
        self.btn_auto_scroll = self.auto_scroll_btn
        self.btn_clear = self.clear_btn
        self.btn_copy = self.copy_btn
        self.btn_save = self.save_btn

        row.addWidget(self.auto_scroll_btn)
        row.addStretch(1)
        row.addWidget(self.clear_btn)
        row.addWidget(self.copy_btn)
        row.addWidget(self.save_btn)

        # 信号全部是「按钮 → 本控件方法」，本控件不回写按钮（自动滚动除外，
        # 且用 blockSignals 防回环），因此不会递归。
        self.auto_scroll_btn.toggled.connect(self.set_auto_scroll)
        self.clear_btn.clicked.connect(self.clear_all)
        self.copy_btn.clicked.connect(self.copy_current)
        self.save_btn.clicked.connect(self.save_current_view)

        # 工具条放不下时按钮文字省略而不是撑破卡片
        self.toolbar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    # ══════════════════════════════════════════════════════════════════════ #
    #  语言
    # ══════════════════════════════════════════════════════════════════════ #
    def _t(self, key: str) -> str:
        entry = _TEXTS.get(key, {})
        return entry.get(self._lang) or entry.get("zh") or key

    def _apply_lang(self) -> None:
        """按 ``self._lang`` 刷新页签文字/tooltip 与按钮文字/tooltip。"""
        for i, key in enumerate(_TAB_KEYS):
            self.tabs.setTabText(i, self._t(key))
            self.tabs.setTabToolTip(i, self._t("tip_" + key))
        self.auto_scroll_btn.setText(self._t("btn_auto_scroll"))
        self.auto_scroll_btn.setToolTip(self._t("tip_auto_scroll"))
        self.clear_btn.setText(self._t("btn_clear"))
        self.clear_btn.setToolTip(self._t("tip_clear"))
        self.copy_btn.setText(self._t("btn_copy"))
        self.copy_btn.setToolTip(self._t("tip_copy"))
        self.save_btn.setText(self._t("btn_save"))
        self.save_btn.setToolTip(self._t("tip_save"))

    def set_lang(self, lang: str) -> None:
        """切换界面语言：``"zh"`` / ``"en"``（其它值按中文处理）。"""
        self._lang = "en" if str(lang).strip().lower() == "en" else "zh"
        self._apply_lang()

    # ══════════════════════════════════════════════════════════════════════ #
    #  日志写入 / 过滤
    # ══════════════════════════════════════════════════════════════════════ #
    def notify(self, msg: str) -> None:
        """主窗口每写一行日志就调用一次；按关键词分发到计算输出/错误信息。

        只写第 1、2 个页签，**不写运行日志**（主窗口在调用前已经写过了）。
        每条追加 ``HH:MM:SS  `` 时间戳前缀，并遵守「自动滚动」开关。
        """
        if msg is None:
            return
        text = msg if isinstance(msg, str) else str(msg)
        if not text:
            return
        low = text.lower()
        line = datetime.now().strftime("%H:%M:%S") + "  " + text
        if any(key in low for key in _ERROR_KEYWORDS):
            self._append_line(self.error_text, line)
        if any(key in low for key in _OUTPUT_KEYWORDS):
            self._append_line(self.output_text, line)

    def _append_line(self, view: QTextEdit, line: str) -> None:
        """往视图末尾追加一行；只有开启自动滚动时才移动视图光标。

        关掉自动滚动时只动文档、不动可见光标 —— 正在翻历史的人不会被拽到底部。
        """
        try:
            cursor = view.textCursor()
            cursor.movePosition(QTextCursor.End)
            cursor.insertText(line + "\n")
            if self._auto_scroll:
                view.setTextCursor(cursor)
                view.ensureCursorVisible()
        except Exception:  # noqa: BLE001 - 日志控件而已，绝不能因追加失败中断计算
            pass

    def clear_all(self) -> None:
        """清空三个视图（包含主窗口的 ``log_text``），不动任何计算状态。"""
        for view in self._views:
            try:
                view.clear()
            except Exception:  # noqa: BLE001
                pass

    def set_auto_scroll(self, enabled: bool) -> None:
        """开/关自动滚动，并与工具条复选框保持同步（不回环）。"""
        self._auto_scroll = bool(enabled)
        btn = getattr(self, "auto_scroll_btn", None)
        if btn is not None and btn.isChecked() != self._auto_scroll:
            btn.blockSignals(True)
            try:
                btn.setChecked(self._auto_scroll)
            finally:
                btn.blockSignals(False)

    def auto_scroll(self) -> bool:
        return bool(self._auto_scroll)

    # ══════════════════════════════════════════════════════════════════════ #
    #  当前页 / 复制 / 保存
    # ══════════════════════════════════════════════════════════════════════ #
    def current_view(self) -> QTextEdit:
        """返回当前选中页签的 ``QTextEdit``（索引异常时退回 ``log_text``）。"""
        try:
            index = self.tabs.currentIndex()
        except AttributeError:
            return self.log_text
        if 0 <= index < len(self._views):
            return self._views[index]
        return self.log_text

    def copy_current(self) -> str:
        """复制当前页签的选中文本；无选中则复制整页。返回复制的内容。"""
        view = self.current_view()
        if view is None:
            return ""
        text = view.textCursor().selectedText()
        if text:
            # QTextEdit 里段落分隔符是 U+2029，粘贴出去要还原成换行。
            text = text.replace("\u2029", "\n").replace("\u2028", "\n")
        else:
            text = view.toPlainText()
        try:
            QApplication.clipboard().setText(text)
        except Exception:  # noqa: BLE001
            pass
        return text

    def save_current_view(self) -> str:
        """弹保存对话框，把当前页签写成 UTF-8 .txt；取消/失败返回空串。"""
        view = self.current_view()
        if view is None:
            return ""
        default_name = "runlog_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".txt"
        caption = self._t("dlg_save")
        filter_str = self._t("filter_txt")
        path = ""
        try:
            if _save_file is not None:
                path, _selected = _save_file(self, caption, default_name, filter_str)
            else:  # pragma: no cover - 仓库内 file_dialogs 一定可用
                from PyQt5.QtWidgets import QFileDialog

                path, _selected = QFileDialog.getSaveFileName(
                    self, caption, default_name, filter_str)
        except Exception:  # noqa: BLE001 - 对话框异常不应影响主界面
            return ""
        if not path:
            return ""
        try:
            return self._save_to(path, view)
        except Exception:  # noqa: BLE001 - 写盘失败（权限/占用）静默返回
            return ""

    def _save_to(self, path, view: QTextEdit = None) -> str:
        """无对话框落盘助手：把 ``view``（默认当前页）写成 UTF-8 文本。

        单独抽出来是为了测试能直接调用（不弹 QFileDialog）；返回写入的路径。
        调用方保证目录存在（保存对话框选出来的路径一定存在），这里不建目录。
        """
        if view is None:
            view = self.current_view()
        text = view.toPlainText() if view is not None else ""
        path = os.fspath(path)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path
