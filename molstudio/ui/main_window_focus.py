# -*- coding: utf-8 -*-
"""MolStudio 「Focus」界面 —— 对齐改版示意稿的卡片化观感
====================================================

在 Studio（``--ui studio``）之上只改**外观**，不复制、不改写任何分析面板：
27 个功能页、信号接线、快捷键、语言切换全部沿用父类。

设计取向（2026-11-11 二次调整）：「简洁」靠**留白 + 圆角卡片分层**，
不是把控件全藏掉。浅灰 #F5F6F7 底上放三块 12px 圆角白卡（画布 /
检查器 / 侧栏），分区各是一张 10px 圆角卡，输入框、按钮、文件胶囊、
浮动药丸统一 8~20px 圆角；描边一律 1px 发丝线，无阴影、无渐变。

相对 Studio 的调整：

===========================  =============================================
项                            Focus
===========================  =============================================
侧栏                          默认展开 232px（Ctrl+B 可收 56px rail），
                              字号统一 10pt / 行高 40 / 组间距 10
顶栏                          52px，保留 v1.0 / 文件胶囊 / 打开 / ⋯；
                              分隔线与 EN 收进 ⋯
检查器                        页头保留副标题 + ⓘ；「文」进 ⋯ 菜单
右栏参数                      ~790px（对标经典蓝色版）；蓝色分节徽章 +
                              蓝色粗体折叠标题；「样式/保存/载入/重置视角/
                              全部展开」常驻；按钮回到纯文字（Studio 配的
                              15px 图标会把密集表单行的文字挤掉）
画布                          左上信息胶囊、3D/2D、38px 浮动药丸（带细竖线）
分区                          前 3 张 + 运行类默认展开，其余折成一张卡片行
底栏                          常驻一行细状态（左状态 / 右 Multiwfn · VMD）
===========================  =============================================

功能一个没删：``Ctrl+K`` 命令面板直达 27 页，``Ctrl+B`` 收起侧栏，
``Ctrl+I`` 收起/展开参数抽屉，``Ctrl+Shift+F`` 或顶栏 ⋯ 一键在
Focus / 完整界面之间切换（不用重启）。旧界面 ``--ui studio / clean /
clean2 / canvas / classic`` 全部原样保留。

用法::

    python main.py                 # 默认即 Focus
    python main.py --ui focus      # 显式指定
    python main.py --ui studio     # 回到完整界面
"""

from __future__ import annotations

import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QIcon, QKeySequence
from PyQt5.QtWidgets import (
    QAction,
    QFrame,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QShortcut,
    QToolButton,
    QWidget,
)

from molstudio.ui.main_window_studio import (
    MolStudioStudioWindow,
    _SECTION_RUN_WORDS,
)
from molstudio.ui.studio_theme import STUDIO_QSS, TOKENS


# ══════════════════════════════════════════════════════════════════════════ #
#  Focus 皮肤：在 STUDIO_QSS 后面追加覆盖规则（同特异性后者生效）
#
#  设计取向（对齐改版示意稿）：**靠留白和圆角卡片分层，而不是把控件全藏掉**。
#  三块大圆角白卡（画布 / 检查器 / 侧栏）+ 分区圆角卡 + 圆角输入/按钮/胶囊，
#  落在浅灰 #F5F6F7 底上；描边一律 1px 发丝线，不用阴影、不用渐变。
# ══════════════════════════════════════════════════════════════════════════ #
FOCUS_QSS = STUDIO_QSS + """

/* ─────────── Focus 覆盖：卡片化 ─────────── */
QWidget#FocusShell { background-color: #EFF1F3; }

QFrame#TopBar {
    background-color: #FFFFFF;
    border-bottom: 1px solid #EDEEF0;
}
QLabel#BrandName { font-size: 13pt; font-weight: 600; }
QLabel#BrandVersion { color: #ADB2B8; }
QLabel#PathChipLabel {
    background-color: #FFFFFF;
    border: 1px solid #D5DAE0;
    border-radius: 9px;
    padding: 0 12px;
    color: #1B1D21;
}
QLabel#PathChipLabel:hover { border-color: #C9CDD2; }
QPushButton#TopBarAction {
    border: 1px solid #D5DAE0;
    border-radius: 8px;
    background-color: #FFFFFF;
    padding: 5px 14px;
}
QPushButton#TopBarAction:hover { background-color: #F5F6F7; }

/* 三块大圆角白卡 */
QFrame#NavCard, QFrame#RightCard, QWidget#CanvasCard {
    background-color: #FFFFFF;
    border: 1px solid #D5DAE0;
    border-radius: 12px;
}
/* 卡片之间只留 5px 浅灰细缝，不要 Fusion 默认那条粗灰 splitter。
   注意：控制 handle **几何**的规则必须挂在 QSplitter 自己身上
   （见 _FOCUS_SPLITTER_QSS + _apply_card_shell），窗口级 QSS 改不动
   QSplitterHandle 的 sizeHint；这里只留一层透明兜底。 */
QSplitter::handle, QSplitterHandle {
    background-color: transparent;
    border: none;
}
QFrame#StudioSidebar {
    background-color: #FFFFFF;
    border: 0px;
    border-right: 1px solid #EDEEF0;
    border-radius: 0px;
}

/* 分区：每张参数卡自己是一个圆角矩形。
   标题改回经典版的蓝色实心徽章 —— 右栏「哪一段到哪一段」全靠它分层，
   中性灰小标题在密集页（EDD / AIM / IGMH）里读起来就是一团乱麻。
   margin-top 必须给徽章留出 20px，否则它会压到卡片内容上。 */
QGroupBox {
    background-color: #FFFFFF;
    border: 1px solid #DDE2E7;
    border-radius: 10px;
    margin-top: 20px;
    /* 横向只留 6px：右栏表单列比留白重要 */
    padding: 12px 6px 10px 6px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 3px 12px;
    color: #FFFFFF;
    background-color: #1565C0;
    border-radius: 5px;
    font-size: 9.5pt;
    font-weight: 600;
}

/* 控件统一圆角：只加 border-radius，不动背景/边框/内边距，
   免得把 27 个面板里「近黑主按钮」和固定宽度数值框刷坏 */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
QPushButton, QToolButton { border-radius: 8px; }
QComboBox::drop-down { border: 0px; width: 18px; }

QWidget#InspectorHeader {
    background-color: transparent;
    border: 0px;
    border-bottom: 1px solid #F0F1F2;
}
QLabel#InspectorTitle { font-size: 13pt; font-weight: 600; }
QLabel#InspectorSub { color: #81858C; }

QLabel#CanvasChip {
    background-color: #FFFFFF;
    border: 1px solid #D5DAE0;
    border-radius: 8px;
    padding: 4px 10px;
    color: #61666B;
}
QFrame#CanvasBar {
    background-color: #FFFFFF;
    border: 1px solid #D5DAE0;
    border-radius: 20px;
}
QFrame#CanvasBarSep { background-color: #E6E8EB; border: 0px; }

QFrame#StatusBar {
    background-color: transparent;
    border-top: 1px solid #F0F1F2;
}
QLabel#StatusLeft, QLabel#StatusRight { color: #81858C; }
"""

# ══════════════════════════════════════════════════════════════════════════ #
#  右栏参数面板「清晰度」补丁
#
#  Studio 皮肤给 canvas_params 追加了 _PARAMS_STUDIO_QSS，把经典版的蓝色粗体
#  分节标题刷成中性灰；又用 _hide_param_topbar() 把「样式 / 保存 / 载入 /
#  重置视角 / 全部展开」整行藏进 ⋯ 菜单。结果右栏既没有面板头、又没有分节
#  层级，只剩一片白卡上散着的输入框 —— 这就是「比较混乱」的来源。
#
#  这份表追加到 canvas_params **自己**的 styleSheet 后面（面板级内联，优先级
#  高于窗口 QSS），把蓝色粗体标题与顶部工具条的样式补回来；工具条本身的显隐
#  由 _hide_param_topbar() 覆写处理。圆角/白底仍保留 Focus 的卡片观感。
# ══════════════════════════════════════════════════════════════════════════ #
FOCUS_PARAMS_QSS = """
QFrame#CubParams {
    background-color: transparent;
    border: none;
}

/* 顶部固定条：面板的「头」，与分节卡明确分开 */
QWidget#CubParamTopBar {
    background-color: #FFFFFF;
    border: 1px solid #D5DAE0;
    border-radius: 9px;
}
QLabel#CubParamTopLbl {
    color: #1565C0;
    font-weight: bold;
    font-size: 9.5pt;
    padding: 0px 2px;
}

/* 分节卡：经典版同款蓝色粗体标题，但保留 10px 圆角白卡 */
QWidget#CubParamCard {
    background-color: #FFFFFF;
    border: 1px solid #DDE2E7;
    border-radius: 10px;
}
QWidget#CubParamCard > QToolButton {
    color: #1565C0;
    background-color: transparent;
    border: none;
    border-radius: 0px;
    font-size: 10pt;
    font-weight: bold;
    text-align: left;
    padding: 6px 12px;
    min-height: 24px;
}
QWidget#CubParamCard > QToolButton:hover {
    background-color: #F2F7FD;
    color: #0D47A1;
}
QWidget#CubParamCard > QToolButton:checked {
    border-bottom: 1px solid #E8EDF3;
    color: #1565C0;
}
QWidget#CubParamSection {
    background-color: transparent;
    border: none;
    padding: 8px 6px 10px 6px;
}
"""


class MolStudioFocusWindow(MolStudioStudioWindow):
    """Studio 的卡片化变体：继承全部功能，只换外观与少量常驻控件显隐。"""

    def __init__(self):
        # 必须在 super().__init__()（内部会建 UI + 上皮肤）之前就位
        self._focus_on = True
        self._focus_done = False
        self._focus_hidden = []              # [(widget, tag)]，切回完整界面时恢复
        self._focus_shortcut = None
        self._inspector_shortcut = None
        self._focus_inspector_hidden = False
        self._status_hide_timer = None
        super().__init__()

    # ── 皮肤入口 ───────────────────────────────────────────────────────
    def _apply_theme(self):
        self.setStyleSheet(FOCUS_QSS if self._focus_on else STUDIO_QSS)

    def _apply_studio_skin(self):
        """Studio 每刷一次皮肤（含 showEvent 的延迟刷新），都补一层 Focus 减法。"""
        super()._apply_studio_skin()
        if self._focus_on:
            self._apply_focus_skin()

    # ── 减法本体（幂等） ───────────────────────────────────────────────
    def _hide_once(self, w, tag=""):
        if w is None:
            return
        if not any(item[0] is w for item in self._focus_hidden):
            self._focus_hidden.append((w, tag))
        try:
            w.hide()
        except Exception:
            pass

    # ── 卡片化：窗口级 QSS 会被面板自带的内联样式顶掉，这里直接设内联 ───
    _CARD_QSS = """
QGroupBox#CanvasCard, QWidget#CanvasCard, QFrame#RightCard {
    background-color: #FFFFFF;
    border: 1px solid #D5DAE0;
    border-radius: 12px;
}
"""
    _SECTION_QSS = """
QGroupBox {
    background-color: #FFFFFF;
    border: 1px solid #DDE2E7;
    border-radius: 10px;
}
"""
    # 面板自带的 styleSheet 优先级高于窗口级 QSS；蓝色徽章必须同样内联追加，
    # 否则带内联分组样式的页面（AIM / ETS-NOCV 等）仍旧是灰色小标题。
    # 自带 ::title 规则的分组不覆盖，尊重它自己的版式（如 AimVmdBox）。
    _SECTION_TITLE_QSS = """
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 3px 12px;
    color: #FFFFFF;
    background-color: #1565C0;
    border-radius: 5px;
    font-size: 9.5pt;
    font-weight: 600;
}
"""
    _FOCUS_MARKS = ("/* FocusCard */", "/* FocusSection */",
                    "/* FocusTitle */", "/* FocusClear */")

    # 分隔条细缝：这份表必须挂在 QSplitter **自己**身上。
    # Qt 用 QSplitterHandle.sizeHint() 排布，而 sizeHint 由 QStyleSheetStyle
    # 按 handle 的 width/margin/padding 算出来；窗口级 QSS 覆盖不到它
    # （实测 handleWidth()=5 但 sizeHint 仍被全局主题撑成 21px，
    #  QSplitter 于是按 21px 预留槽位，露出一条 21px 粗灰带）。
    # 挂到 splitter 自身后 sizeHint 变成 5×5，间隙才真的只有 5px。
    # 悬停时中间截出 3px 主题蓝细线，热区变窄后也能找到「这里能拖」。
    _FOCUS_SPLITTER_QSS = """
QSplitter::handle, QSplitter::handle:horizontal {
    width: 5px;
    margin: 0px;
    padding: 0px;
    border: none;
    background-color: transparent;
}
QSplitter::handle:horizontal:hover,
QSplitter::handle:horizontal:pressed {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0.2 rgba(0,0,0,0),
                                stop:0.2 #7BA7D7,
                                stop:0.8 #7BA7D7,
                                stop:0.8 rgba(0,0,0,0));
    border: none;
}
"""

    def _apply_card_shell(self):
        """三块大卡 + 每张分区卡：直接追加内联样式（优先级最高）。

        STUDIO_QSS 里 QGroupBox 本来是「无边框分区」，各分析面板还带自己的
        内联 stylesheet；只靠窗口级 QSS 覆盖不稳，实测圆角根本没显示出来。
        """
        canvas_card = getattr(self, "grp_canvas", None)
        for w in (canvas_card, getattr(self, "right_card", None)):
            if w is None:
                continue
            try:
                ss = w.styleSheet() or ""
                if "FocusCard" not in ss:
                    w.setStyleSheet(ss + "/* FocusCard */\n" + self._CARD_QSS)
            except Exception:
                pass
        for gb in self.findChildren(QGroupBox):
            if gb is canvas_card:
                continue
            try:
                ss = gb.styleSheet() or ""
                extra = ""
                if "FocusSection" not in ss:
                    extra += "/* FocusSection */\n" + self._SECTION_QSS
                if "FocusTitle" not in ss and "::title" not in ss:
                    extra += "/* FocusTitle */\n" + self._SECTION_TITLE_QSS
                if extra:
                    gb.setStyleSheet(ss + extra)
            except Exception:
                pass
        split = getattr(self, "_body_splitter", None)
        if split is not None:
            try:
                # 细缝 5px：卡片之间只要够看出圆角分离即可，10px 的灰带太粗。
                # 5px 同时还是可抓取的热区（Qt 默认约 4px），双击复位照常可用。
                split.setHandleWidth(5)
                if split.styleSheet() != self._FOCUS_SPLITTER_QSS:
                    split.setStyleSheet(self._FOCUS_SPLITTER_QSS)
                    # 换样式表后要重新 polish + 重算尺寸，sizeHint 才会 21 → 5
                    self.style().unpolish(split)
                    self.style().polish(split)
                    QTimer.singleShot(
                        0, lambda: self._apply_sizes(force=True))
            except Exception:
                pass

    def _strip_card_shell(self):
        """切回完整界面时撤掉内联卡片样式，不污染 Studio。"""
        widgets = [getattr(self, "grp_canvas", None),
                   getattr(self, "right_card", None),
                   getattr(self, "canvas_params", None)]
        widgets += list(self.findChildren(QGroupBox))
        for w in widgets:
            if w is None:
                continue
            try:
                ss = w.styleSheet() or ""
                cuts = [ss.index(m) for m in self._FOCUS_MARKS if m in ss]
                if cuts:
                    w.setStyleSheet(ss[:min(cuts)])
            except Exception:
                pass
        # 分隔条还给 BodySplitter 默认：8px 热区 + 全局主题的细线样式
        split = getattr(self, "_body_splitter", None)
        if split is not None:
            try:
                split.setStyleSheet("")
                split.setHandleWidth(getattr(split, "HANDLE_WIDTH", 8))
                self.style().unpolish(split)
                self.style().polish(split)
            except Exception:
                pass

    def _enforce_focus_geometry(self):
        """几何约束每次皮肤刷新都重压一遍。

        Studio 的 showEvent / 父类 _deferred_init 会在窗口上屏之后再次跑皮肤，
        会把顶栏、药丸重置回 52 / 42；只在第一次设置会被盖掉，所以把尺寸
        与显隐独立成可重复执行的步骤。
        """
        top = self._topbar
        if top is not None:
            try:
                top.setFixedHeight(52)
            except Exception:
                pass
        bar = getattr(self, "_studio_canvas_bar", None)
        if bar is not None:
            try:
                bar.setFixedHeight(38)
            except Exception:
                pass
        if self._statusbar is not None:
            self._statusbar.show()      # 效果图的细底栏：常驻一行

    # ── 右栏参数面板：把经典版的「清晰度」搬回来 ───────────────────────
    def _show_param_topbar(self):
        """「样式 / 保存… / 载入… / 重置视角 / 全部展开」常驻。

        Studio 皮肤把这行藏进 ⋯ 菜单，右栏于是没有「面板头」，一上来就是
        一堆输入框。这里只负责显隐，样式在 FOCUS_PARAMS_QSS 里。
        """
        # Studio 的 _hide_param_topbar 幂等标志：Focus 每次把工具条显示回来，
        # 都要把它清掉，否则下次切回完整界面时 hide() 会被标志挡掉。
        self._param_topbar_done = False
        for root in (getattr(self, "canvas_params", None),
                     getattr(self, "cub_canvas", None)):
            if root is None:
                continue
            try:
                bar = root.findChild(QWidget, "CubParamTopBar")
            except Exception:
                bar = None
            if bar is not None:
                if not bar.isVisible():
                    bar.show()
                QTimer.singleShot(0, self._sync_scroll_height)
                return

    def _hide_param_topbar(self):
        """覆写：Focus 下不隐藏，切回完整界面时仍按 Studio 原逻辑执行。"""
        if self._focus_on:
            self._show_param_topbar()
            return
        return super()._hide_param_topbar()

    def _apply_button_icons(self, root=None):
        """右栏按钮回到经典版的「纯文字」。

        Studio 皮肤按关键词给每个按钮配 15px 图标（经典版没有）。密集表单行
        里一排 8 个控件本就贴着宽度上限，图标再吃掉 ~20px/个，QHBoxLayout
        放不下时不是换行而是把按钮文字直接裁掉 —— EDD 的「用画框选中原子」
        只剩「用画布选中原」。右栏按钮去掉图标后既贴近经典版观感，也把
        文字完整让出来；画布工具条、侧栏的图标保持不动。
        """
        super()._apply_button_icons(root)
        self._strip_right_button_icons()

    def _strip_right_button_icons(self):
        if not self._focus_on:
            return
        right = getattr(self, "right_card", None)
        if right is None:
            return
        try:
            null_icon = QIcon()
            for b in right.findChildren((QPushButton, QToolButton)):
                if not b.icon().isNull():
                    b.setIcon(null_icon)
        except Exception:
            pass

    def _apply_focus_right_panel(self):
        """幂等：参数面板补蓝色分节标题 + 顶部工具条 + 收紧卡片外边距。

        皮肤会在 showEvent / 语言切换 / 切页之后重刷，所以这一步每次都跑，
        靠 marker 保证不会把样式表越叠越长。
        """
        # ① 面板级 QSS：必须挂在 canvas_params 自己身上（它会被摘出画布面板）
        cp = getattr(self, "canvas_params", None)
        if cp is not None:
            try:
                ss = cp.styleSheet() or ""
                if "FocusClear" not in ss:
                    cp.setStyleSheet(ss + "/* FocusClear */\n" + FOCUS_PARAMS_QSS)
            except Exception:
                pass
        # ② 分区蓝色徽章（新建的分组框也要补上）
        self._apply_card_shell()
        # ③ 顶部工具条
        self._show_param_topbar()
        # ④ 横向留白链收紧：右卡 12→8、功能页 12→6，把宽度让给表单列
        rc = getattr(self, "right_card", None)
        if rc is not None and rc.layout() is not None:
            try:
                rc.layout().setContentsMargins(8, 10, 8, 12)
            except Exception:
                pass
        try:
            for i in range(self.tabs.count()):
                page = self.tabs.widget(i)
                if page is not None and page.layout() is not None:
                    page.layout().setContentsMargins(6, 10, 6, 10)
        except Exception:
            pass
        # ⑤ 皮肤可能刚重新配过图标，这里再清一次右栏
        self._strip_right_button_icons()

    def _apply_focus_skin(self):
        # Studio 的皮肤方法会重刷 STUDIO_QSS，这里每次都压回 Focus 版
        self.setStyleSheet(FOCUS_QSS)
        self._enforce_focus_geometry()
        # 右栏清晰度补丁每次皮肤刷新都压一遍（showEvent 会延迟重刷）
        self._apply_focus_right_panel()
        if self._focus_done:
            return
        self._focus_done = True

        if self._path_box is not None:
            try:
                self._path_box.setMaximumWidth(300)
            except Exception:
                pass

        # ① 浅灰窗口底：三块白卡的圆角与间隙才看得出来
        central = self.centralWidget()
        if central is not None:
            try:
                central.setObjectName("FocusShell")
                central.setAttribute(Qt.WA_StyledBackground, True)
                lay = central.layout()
                if lay is not None:
                    lay.setContentsMargins(14, 12, 14, 10)
                    lay.setSpacing(12)
            except Exception:
                pass
        self.setStyleSheet(FOCUS_QSS)   # objectName 改完再压一次，让 #FocusShell 命中

        # ② 顶栏：保留 v1.0 与信息胶囊；只收起分隔线与 EN（后者进 ⋯）
        top = self._topbar
        if top is not None:
            for w in top.findChildren(QFrame, "TopBarDivider"):
                self._hide_once(w, "topbar-divider")
            self._hide_once(getattr(self, "_lang_btn", None), "lang")

        # ③ 侧栏保持展开态（效果图的分组侧栏），底部三个入口常驻且左对齐。
        #    不强制 rail：用户 Ctrl+B 收起后，皮肤刷新不该抢回去。
        foot = self._sidebar_footer
        if foot is not None and foot.layout() is not None:
            fl = foot.layout()
            for i in range(fl.count()):
                item = fl.itemAt(i)
                if item is not None and item.widget() in self._footer_buttons:
                    try:
                        item.setAlignment(Qt.AlignLeft)
                    except Exception:
                        pass
            for b in self._footer_buttons:
                try:
                    b.setMaximumWidth(160)
                except Exception:
                    pass

        # ④ 检查器页头保留副标题 + ⓘ 说明；只有「文」收进 ⋯ 菜单
        self._hide_once(self._inspector_cite, "inspector-cite")

        # ⑤ 底栏右侧给一句环境状态（效果图同款短文案）
        if self._status_right is not None:
            try:
                self._status_right.setText("Multiwfn OK · VMD OK")
            except Exception:
                pass

        self._rebuild_overflow_menu()
        self._rebuild_inspector_menu()
        self._setup_focus_shortcuts()
        QTimer.singleShot(0, lambda: self._apply_sizes(force=True))

    # ── 被皮肤流程回调的几处，改成 Focus 版 ────────────────────────────
    def _float_canvas_bar(self):
        """浮动药丸保留按钮间的细竖线（效果图同款胶囊）。"""
        super()._float_canvas_bar()
        if self._focus_on:
            bar = getattr(self, "_studio_canvas_bar", None)
            if bar is not None:
                try:
                    bar.setFixedHeight(38)
                except Exception:
                    pass

    def _refresh_path_chip(self):
        """空态占位文字收短，顶栏文件胶囊才是「胶囊」而不是长输入框。"""
        super()._refresh_path_chip()
        if not self._focus_on or self._path_chip is None:
            return
        try:
            path = (self.var_path.text() or "").strip()
        except Exception:
            path = ""
        if not path:
            self._path_chip.setText(
                '<span style="color:#ADB2B8">●</span> 打开文件 / 拖入 .fchk…')

    def _apply_section_defaults(self):
        """前 3 张分区卡 + 运行类默认展开，其余折成一行（贴效果图的层次）。"""
        if not self._focus_on:
            super()._apply_section_defaults()
            return
        if self._section_defaults_done:
            return
        try:
            self._install_section_toggles()
        except Exception as e:      # noqa: BLE001
            print(f"[focus] 分区折叠安装失败：{e}")
            return
        self._section_defaults_done = True
        for page_idx in range(self.tabs.count()):
            page = self.tabs.widget(page_idx)
            if page is None:
                continue
            try:
                groups = [gb for gb in page.findChildren(QGroupBox)
                          if getattr(gb, "_clean_section", False)]
            except Exception:
                continue
            if not groups:
                continue
            run_positions = []
            for j, gb in enumerate(groups):
                title = gb.title()
                if title[:1] in (self._CHEV_DOWN, self._CHEV_RIGHT):
                    title = title[1:].lstrip()
                low = title.lower()
                if any(w in title or w in low for w in _SECTION_RUN_WORDS):
                    run_positions.append(j)
            # 效果图的右栏是多张展开的分区卡：前 3 张 + 所有「运行/计算」分区
            # 默认展开，其余折成一行卡片标题，长页也不至于首屏塞满
            for j, gb in enumerate(groups):
                should_collapse = (j >= 3 and j not in run_positions)
                st = getattr(self, "_section_state", {}).get(gb)
                if st is not None and st["collapsed"] != should_collapse:
                    self._toggle_section(gb)
        QTimer.singleShot(0, self._sync_scroll_height)

    def _set_status(self, msg):
        """底栏常驻：只更新左侧一行短状态（效果图同款）。"""
        super()._set_status(msg)

    def _hide_statusbar(self):
        """兼容旧调用：Focus 下底栏常驻，不再自动收起。"""
        pass

    # ── 菜单：把收起来的入口全部补齐 ───────────────────────────────────
    def _rebuild_overflow_menu(self):
        super()._rebuild_overflow_menu()
        menu = self._overflow_menu
        if menu is None:
            return
        menu.addSeparator()
        lang = getattr(self, "_lang_btn", None)
        if lang is not None:
            act = QAction(self._t_ui("切换中 / EN", "中文 / English"), menu)
            act.triggered.connect(lambda _c=False: lang.click())
            menu.addAction(act)
        act = QAction(self._t_ui("搜索功能  Ctrl+K", "Search  Ctrl+K"), menu)
        act.triggered.connect(self._open_palette)
        menu.addAction(act)
        act = QAction(self._t_ui("参数抽屉  Ctrl+I", "Inspector  Ctrl+I"), menu)
        act.triggered.connect(self._toggle_inspector)
        menu.addAction(act)
        menu.addSeparator()
        act = QAction(self._t_ui("切换到完整界面  Ctrl+Shift+F",
                                 "Full interface  Ctrl+Shift+F")
                      if self._focus_on else
                      self._t_ui("切换到极简界面  Ctrl+Shift+F",
                                 "Focus interface  Ctrl+Shift+F"), menu)
        act.triggered.connect(lambda _c=False: self._set_focus(not self._focus_on))
        menu.addAction(act)

    def _rebuild_inspector_menu(self):
        super()._rebuild_inspector_menu()
        if not self._focus_on:
            return
        btn = self._inspector_menu_btn
        if btn is None or btn.menu() is None:
            return
        menu = btn.menu()
        menu.addSeparator()
        act = QAction(self._t_ui("功能说明", "About this tool"), menu)
        act.triggered.connect(self._show_page_intro)
        menu.addAction(act)
        act = QAction(self._t_ui("参考文献 / 返回参数", "References / back"), menu)
        act.triggered.connect(self._toggle_citation)
        menu.addAction(act)

    def _show_page_intro(self):
        idx = self.tabs.currentIndex()
        keys = getattr(self, "_tab_keys", [])
        name = self._tr(keys[idx]) if 0 <= idx < len(keys) else "MolStudio"
        text = (self._page_intro.get(idx) or
                self._t_ui("当前功能没有额外说明", "No extra description."))
        QMessageBox.information(self, name, text)

    def _toggle_citation(self):
        tabs = getattr(self, "right_tabs", None)
        if tabs is None:
            return
        self._on_citation_clicked(tabs.currentIndex() != 1)

    # ── 快捷键 / 抽屉 / 一键切换 ───────────────────────────────────────
    def _setup_focus_shortcuts(self):
        if self._focus_shortcut is None:
            sc = QShortcut(QKeySequence("Ctrl+Shift+F"), self)
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(lambda: self._set_focus(not self._focus_on))
            self._focus_shortcut = sc
        if self._inspector_shortcut is None:
            sc = QShortcut(QKeySequence("Ctrl+I"), self)
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(self._toggle_inspector)
            self._inspector_shortcut = sc

    def _toggle_inspector(self):
        """Ctrl+I：把右栏整个收起来当抽屉，画布占满。"""
        split = getattr(self, "_body_splitter", None)
        if split is None or split.count() < 3:
            return
        right = split.widget(2)
        if right is None:
            return
        self._focus_inspector_hidden = not self._focus_inspector_hidden
        if self._focus_inspector_hidden:
            right.hide()
            sb_w = (self.RAIL_W if (self._sidebar is not None
                                    and self._sidebar.is_rail())
                    else self.SIDEBAR_W)
            split.setSizes([sb_w, max(split.width() - sb_w, 320), 0])
        else:
            right.show()
            self._apply_sizes(force=True)

    def _on_tab_changed(self, index):
        """切页后补一次右栏补丁：新页面的分组框也要有蓝色徽章。"""
        super()._on_tab_changed(index)
        if self._focus_on:
            QTimer.singleShot(0, self._apply_focus_right_panel)

    def _apply_sizes(self, force=False):
        if self._focus_on and self._focus_inspector_hidden:
            return
        super()._apply_sizes(force)
        if not self._focus_on:
            return
        # 分析面板当初按 ~660px 设计（EDD / AIM / IGMH 尤其），经典蓝色版
        # 右栏实测 ~720–760px，两列表单与按钮文字能完整展开；Focus 早先
        # 只给 560px，下拉框 "ultra-glass — Ice Crystal…"、EDD 的
        # 「用画框选中原子 / 添加片段」都被直接裁掉。默认抬到接近经典版。
        split = getattr(self, "_body_splitter", None)
        if split is None or split.count() < 3:
            return
        total = split.width()
        if total <= 100:
            return
        rail = bool(self._sidebar is not None and self._sidebar.is_rail())
        sb_w = self.RAIL_W if rail else self.SIDEBAR_W
        rest = max(total - sb_w, 320)
        # 实测 QSplitter 会把 setSizes 的值按比例缩到 ~96%（handle 占位），
        # 想让 EDD 那行「用画框选中原子 / 添加片段」不被裁，右栏实际要有
        # ~780px，所以这里按 0.62 请求；canvas 仍留 ~470px，可手动拖 splitter。
        ratio = 0.70 if self._inspector_wide else 0.63
        right = max(790, min(int(rest * ratio), 880))
        if rest - right < 360:          # 小窗口优先保证画布还有可用宽度
            right = max(560, rest - 360)
        canvas = max(rest - right, 320)
        split.setSizes([sb_w, canvas, right])

    def _set_focus(self, on):
        """极简 ⇄ 完整，不重启、不重建控件。"""
        if bool(on) == bool(self._focus_on):
            return
        self._focus_on = bool(on)
        if self._focus_on:
            self._focus_done = False
            self._apply_focus_skin()
        else:
            for w, _tag in self._focus_hidden:
                try:
                    w.show()
                except Exception:
                    pass
            self._focus_hidden.clear()
            self._strip_card_shell()
            # 切回完整界面：按 Studio 原逻辑把参数顶部条收回 ⋯ 菜单
            try:
                MolStudioStudioWindow._hide_param_topbar(self)
            except Exception:
                pass
            self._focus_done = False
            if self._topbar is not None:
                self._topbar.setFixedHeight(int(TOKENS["topbar_h"]))
            if self._statusbar is not None:
                self._statusbar.show()
            bar = getattr(self, "_studio_canvas_bar", None)
            if bar is not None:
                bar.setFixedHeight(42)
            if self._sidebar is not None and self._sidebar.is_rail():
                self._sidebar.set_rail(False)
            self.setStyleSheet(STUDIO_QSS)
            # 完整界面恢复它自己的留白、按钮图标与参数顶部条
            try:
                MolStudioStudioWindow._apply_canvas_card(self)
                MolStudioStudioWindow._apply_page_spacing(self)
                self._apply_button_icons()
            except Exception:
                pass
            try:
                self._add_pill_separators()   # 补回药丸竖线
            except Exception:
                pass
            self._refresh_canvas_chips()
        self._rebuild_overflow_menu()
        self._apply_sizes(force=True)

    def showEvent(self, event):
        super().showEvent(event)
        if self._focus_on:
            # Studio 的 showEvent 会延迟 160ms 重刷皮肤，之后再补一次减法与尺寸
            QTimer.singleShot(380, self._apply_focus_skin)
            QTimer.singleShot(420, lambda: self._apply_sizes(force=True))


def main():
    """独立启动入口：复用 main.py 的完整引导流程。"""
    os.environ["MOLSTUDIO_UI"] = "focus"
    _canon = "molstudio.ui.main_window_focus"
    if _canon not in sys.modules:
        sys.modules[_canon] = sys.modules[__name__]
    import molstudio.app as _main
    _main.main()


if __name__ == "__main__":
    main()
