# -*- coding: utf-8 -*-
"""
studio_sidebar.py — MolStudio「studio」界面：左侧分组导航 + Ctrl+K 命令面板
=========================================================================

本文件是 `--ui studio` 新界面的**独立组件**，只新增文件，不改任何既有窗口/面板。
窗口侧只需要：构造 `StudioSidebar`、把 `NAV_ICONS` 映射成 `entry["icon"]`、
把 `pageRequested(int)` 接到页栈 `setCurrentIndex`，`searchRequested()` 里打开
`CommandPalette`。

导出的两个类
------------
StudioSidebar(QFrame)        objectName = "StudioSidebar"
    pageRequested = pyqtSignal(int)      点击某条导航（参数=页栈页序号）
    searchRequested = pyqtSignal()       点了顶部“搜索功能 / Ctrl K”
    railChanged = pyqtSignal(bool)       True = 56px 图标 rail

    set_entries(groups, current=0)   groups = [("常用", [entry, ...]), ...]
                                     entry = {"index": int, "text": str,
                                              "icon": str|None, "key": str}
    set_current(index)               选中某页（自动展开它所在的组；未展开才展开）
    set_rail(rail) / toggle_rail() / is_rail()
    expand_group_of(index)           只展开组，不改变选中
    set_bottom_text(text)            底部版本/状态文字（可选）

CommandPalette(QDialog)      objectName = "CommandPalette"
    __init__(entries, parent=None, title=None)
        entries = [(显示文字, payload), ...]，payload 由窗口决定（int 页序号或 str action）
    pick() -> payload | None          内部 exec_()，取消返回 None

设计依据
--------
`outputs/ui_redesign_2026-11-11/DSH_DESIGN_SPEC.md`：侧栏展开 280 / 收起 56、
行高 36、hover 与 selected 同色 `rgba(38,49,72,.06)`、分组标题 11px tertiary、
圆角 sm=8。本组件按窗口契约取 232 / 56 / 34。

颜色/字号优先取 `molstudio.ui.studio_theme.TOKENS`；import 失败时使用文件内
**同键名**兜底 dict，所以本文件不依赖 studio_theme 也能单独 import（本文件在
模块层不创建任何 widget，没有 QApplication 也能 import）。

只写这一个文件；验证脚本只写到 %TEMP%。
"""

from __future__ import annotations

from functools import partial

from PyQt5.QtCore import QEvent, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QDialog,
    QFrame,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from molstudio.ui.ui_icons import make_icon

__all__ = ("StudioSidebar", "CommandPalette")


# ══════════════════════════════════════════════════════════════════════════ #
#  Token：优先 studio_theme.TOKENS，失败用同键名兜底
# ══════════════════════════════════════════════════════════════════════════ #
try:  # pragma: no cover - 取决于同目录 studio_theme.py 是否存在
    from molstudio.ui.studio_theme import TOKENS as _STUDIO_TOKENS
except Exception:  # noqa: BLE001 - import 失败绝不能变成硬错误
    _STUDIO_TOKENS = {}

# 兜底色值全部来自 DSH 实测（DSH_DESIGN_SPEC.md §1/§3）：浅色只有 2 个表面、
# 5 级文字、hover 与 selected 同色、边框 1px 极淡。
_FALLBACK_TOKENS = {
    # 尺寸
    "sidebar_w": 232,
    "sidebar_rail_w": 56,
    "row_h": 34,
    "icon_size": 18,
    # 表面
    "sidebar_bg": "#F9FAFB",
    "surface": "#FFFFFF",
    "menu_bg": "#FBFCFD",
    "hover": "rgba(38, 49, 72, 15)",
    "selected_bg": "#F2F3F4",
    "active": "#E9EAED",
    # 文字
    "text_primary": "#0F1115",
    "text_secondary": "#61666B",
    "text_tertiary": "#81858C",
    "text_caption": "#ADB2B8",
    # 图标
    "icon": "#353638",
    "icon_active": "#0F1115",
    # 描边 / 强调 / 滚动条
    "border": "#E6E6E6",
    "border_strong": "#D6D6D6",
    "hairline": "#F0F1F3",
    "accent": "#4176E6",
    "accent_subtle": "#E4EDFD",
    "scrollbar": "#E5E5E5",
    "scrollbar_hover": "#D4D4D4",
    # 形状 / 字号
    "radius": {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 20, "panel": 28},
    "font_size": {"caption": 11, "small": 12, "secondary": 13,
                  "body": 14, "title": 16, "page": 20, "display": 24},
}


def _tok(*keys, default=None):
    """按顺序在 studio_theme.TOKENS、兜底 dict 里查键；都没有返回 default。

    先在整个 studio_theme 里查所有候选键，再查兜底，避免「studio_theme 有
    别名键但兜底同名键先命中」。
    """
    for source in (_STUDIO_TOKENS, _FALLBACK_TOKENS):
        if not isinstance(source, dict):
            continue
        for key in keys:
            try:
                value = source.get(key)
            except Exception:  # noqa: BLE001 - 第三方 dict 允许出任何状况
                value = None
            if value is not None:
                return value
    return default


def _tok_int(*keys, default=0):
    try:
        return int(_tok(*keys, default=default))
    except (TypeError, ValueError):
        return int(default)


def _tok_radius(fallback, *keys, slot="sm"):
    """圆角：优先扁平键（radius_ctrl / radius_card …），其次 radius 字典的 slot。"""
    for source in (_STUDIO_TOKENS, _FALLBACK_TOKENS):
        if not isinstance(source, dict):
            continue
        for key in keys:
            value = source.get(key)
            if isinstance(value, (int, float)):
                return int(value)
        radius = source.get("radius")
        if isinstance(radius, dict) and isinstance(radius.get(slot), (int, float)):
            return int(radius[slot])
        if isinstance(radius, (int, float)):
            return int(radius)
    return int(fallback)


def _font_pt(kind, fallback_pt):
    """字号（统一用 pt 设置）。

    studio_theme 的扁平 `font_<kind>` 键是 **pt**（font_caption=8.5）；
    兜底 dict 的 `font_size` 是 **px**，这里换算成 pt，保证两条路径观感一致。
    """
    if isinstance(_STUDIO_TOKENS, dict):
        value = _STUDIO_TOKENS.get("font_" + kind)
        if isinstance(value, (int, float)):
            return float(value)
        sizes = _STUDIO_TOKENS.get("font_size")
        if isinstance(sizes, dict) and isinstance(sizes.get(kind), (int, float)):
            return float(sizes[kind]) * 0.75
    sizes = _FALLBACK_TOKENS.get("font_size")
    if isinstance(sizes, dict) and isinstance(sizes.get(kind), (int, float)):
        return float(sizes[kind]) * 0.75
    return float(fallback_pt)


def _c(*keys, default="#000000"):
    value = _tok(*keys, default=default)
    return str(value)


# ── 组件常量 ────────────────────────────────────────────────────────────────
SIDEBAR_W = _tok_int("sidebar_w", "sidebar_width", default=232)
RAIL_W = _tok_int("sidebar_rail_w", "sidebar_rail", default=56)
ICON_SIZE = _tok_int("icon_size", default=18)
# 展开态：行高 40 / 组标题 34 / 条目间距 4 / 组间距 10。
# rail 态没有文字，用更紧的间距，避免 27 个图标滚太长。
ROW_H = _tok_int("nav_row_h", "row_h", default=40)
GROUP_TITLE_H = _tok_int("nav_group_h", default=34)
NAV_ITEM_GAP = _tok_int("nav_item_gap", default=4)
NAV_GROUP_GAP = _tok_int("nav_group_gap", default=10)
RAIL_ITEM_GAP = 1
RAIL_GROUP_GAP = 2

C_BG = _c("sidebar", "sidebar_bg", "surface_subtle", default="#F9FAFB")
C_SURFACE = _c("surface", "window_bg", default="#FFFFFF")
C_HOVER = _c("hover", "hover_alpha", "selected_bg", default="rgba(38, 49, 72, 15)")
C_SELECTED = _c("selected", "selected_bg", "hover", default="#F2F3F4")
C_ACTIVE = _c("active", "hover", default="#E9EAED")
C_TEXT = _c("text_primary", default="#0F1115")
C_TEXT2 = _c("text_secondary", default="#61666B")
C_TEXT3 = _c("text_tertiary", default="#81858C")
C_CAPTION = _c("text_caption", default="#ADB2B8")
C_ICON = _c("icon", "icon_muted", default="#353638")
C_ICON_ACTIVE = _c("icon_active", "icon_selected", default="#0F1115")
C_BORDER = _c("border", "border_accent", default="#E6E6E6")
C_BORDER_STRONG = _c("border_strong", "border_l4", default="#D6D6D6")
C_HAIRLINE = _c("border_soft", "hairline", "border", default="#F0F1F3")
C_ACCENT = _c("accent", "focus_ring", default="#4176E6")
C_ACCENT_SUBTLE = _c("accent_soft", "accent_subtle", default="#E4EDFD")
C_MENU_BG = _c("menu_bg", "surface", default="#FBFCFD")
C_SCROLL = _c("scrollbar", default="#E5E5E5")
C_SCROLL_HOVER = _c("scrollbar_hover", default="#D4D4D4")

R_SM = _tok_radius(8, "radius_ctrl", "radius_sm", slot="sm")
R_MD = _tok_radius(12, "radius_card", "radius_md", slot="md")
R_LG = max(R_MD + 4, 16)

# 侧栏所有主文字统一一档，辅助标注单独一档。
# 之前代码里的 QFont.setPointSizeF 与 QSS 的 font-size 各给一套，叠出
# 8.5 / 9 / 9.5 / 10pt 四档字号 + 三种字重，观感参差；这里收敛到两档。
F_NAV_PT = float(_tok("nav_text_pt", default=10))
F_NAV_AUX_PT = float(_tok("nav_aux_pt", default=9))
# 兼容别名：命令面板等继续按语义取字号，实际都落到上面两档
F_BODY_PT = F_NAV_PT
F_SECONDARY_PT = F_NAV_PT
F_CAPTION_PT = F_NAV_AUX_PT

# 命令面板尺寸（窗口契约）
PALETTE_W = 560
PALETTE_H = 420
PALETTE_ROW_H = 36


# ══════════════════════════════════════════════════════════════════════════ #
#  图标缓存（make_icon 现画，QIcon 可重复用；rail 与 drawer 共用）
# ══════════════════════════════════════════════════════════════════════════ #
_ICON_CACHE: dict = {}


def _icon(kind: str, color: str, size: int):
    """返回缓存的 QIcon；kind 未知时 make_icon 会退化成一个圆点而不是报错。"""
    key = (str(kind or "list"), str(color), int(size))
    icon = _ICON_CACHE.get(key)
    if icon is None:
        icon = make_icon(key[0], key[1], key[2], 1.5)
        _ICON_CACHE[key] = icon
    return icon


# ══════════════════════════════════════════════════════════════════════════ #
#  内部控件：导航条目（自绘图标+文字，避免 QToolButton 居中对齐的跨平台差异）
# ══════════════════════════════════════════════════════════════════════════ #
class _NavItemButton(QToolButton):
    """分组导航条目。

    `QToolButton` 提供 checkable/互斥/键盘 Space 的语义，但它的内容区在
    不同 style 下（Fusion / WindowsVista / macOS）默认是居中的；DSH 侧栏
    条目是**左对齐**的。所以这里不在按钮自身上放 icon/text，而是自绘内容，
    样式表只负责 hover/checked 的浅底与圆角 —— macOS 与 Windows 表现一致。
    """

    def __init__(self, text, icon_kind, index, parent=None):
        super().__init__(parent)
        self.setObjectName("NavItem")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.setFixedHeight(ROW_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._full_text = str(text or "")
        self._icon_kind = str(icon_kind or "list")
        self._index = int(index)
        self._rail = False
        self._icon_size = ICON_SIZE
        font = self.font()
        font.setPointSizeF(F_BODY_PT)
        self.setFont(font)

    # -- rail ---------------------------------------------------------------
    def set_rail(self, rail: bool) -> None:
        self._rail = bool(rail)
        self.update()

    # -- 自绘 ---------------------------------------------------------------
    def paintEvent(self, event):  # noqa: N802 - Qt 命名
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect()
        icon_size = self._icon_size
        color = C_ICON_ACTIVE if self.isChecked() else C_ICON
        icon = _icon(self._icon_kind, color, icon_size)

        if self._rail:
            x = max(0, (rect.width() - icon_size) // 2)
            y = max(0, (rect.height() - icon_size) // 2)
            icon.paint(painter, x, y, icon_size, icon_size)
            return

        left = 14
        icon.paint(painter, left, (rect.height() - icon_size) // 2,
                   icon_size, icon_size)
        painter.setFont(self.font())
        painter.setPen(QColor(C_TEXT if self.isChecked() else C_TEXT2))
        text_x = left + icon_size + 12
        avail = max(0, rect.width() - text_x - 14)
        metrics = QFontMetrics(self.font())
        shown = metrics.elidedText(self._full_text, Qt.ElideRight, avail)
        painter.drawText(
            rect.adjusted(text_x, 0, -14, 0),
            Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine,
            shown,
        )


# ══════════════════════════════════════════════════════════════════════════ #
#  内部控件：顶部搜索按钮（右侧 Ctrl K 小字）
# ══════════════════════════════════════════════════════════════════════════ #
class _SearchButton(QToolButton):
    """「搜索功能」入口。自绘：左图标 + 文字，右端 caption 色 Ctrl K。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SidebarSearch")
        self.setText("")
        self.setCursor(Qt.PointingHandCursor)
        self.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.setFixedHeight(ROW_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._rail = False
        font = self.font()
        font.setPointSizeF(F_BODY_PT)
        self.setFont(font)
        self._hint_font = QFont(self.font())
        self._hint_font.setPointSizeF(F_NAV_AUX_PT)

    def set_rail(self, rail: bool) -> None:
        self._rail = bool(rail)
        self.setToolTip("搜索功能（Ctrl K）" if self._rail else "")
        self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt 命名
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect()
        icon = _icon("search", C_TEXT2, 16)
        if self._rail:
            icon.paint(painter, (rect.width() - 16) // 2,
                       (rect.height() - 16) // 2, 16, 16)
            return
        left = 14
        icon.paint(painter, left, (rect.height() - 16) // 2, 16, 16)
        painter.setFont(self.font())
        painter.setPen(QColor(C_TEXT2))
        painter.drawText(
            rect.adjusted(left + 16 + 12, 0, -14, 0),
            Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine,
            "搜索功能",
        )
        painter.setFont(self._hint_font)
        painter.setPen(QColor(C_CAPTION))
        painter.drawText(rect.adjusted(0, 0, -14, 0),
                         Qt.AlignRight | Qt.AlignVCenter, "Ctrl K")


# ══════════════════════════════════════════════════════════════════════════ #
#  内部控件：分组标题（可点击折叠，右侧 ▾ / ▸）
# ══════════════════════════════════════════════════════════════════════════ #
class _GroupTitle(QLabel):
    """分组标题：11px tertiary + 右侧收起/展开箭头。整行可点。"""

    clicked = pyqtSignal(str)

    def __init__(self, name, parent=None):
        super().__init__("", parent)
        self.setObjectName("NavGroupTitle")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(GROUP_TITLE_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._name = str(name)
        self._open = False
        self._font = QFont(self.font())
        self._font.setPointSizeF(F_NAV_PT)
        self._chevron_font = QFont(self.font())
        self._chevron_font.setPointSizeF(F_NAV_AUX_PT)

    def sizeHint(self):  # noqa: N802 - Qt 命名
        return QSize(120, GROUP_TITLE_H)

    def set_open(self, is_open: bool) -> None:
        self._open = bool(is_open)
        self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt 命名
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect()
        painter.setFont(self._font)
        painter.setPen(QColor(C_TEXT3))
        painter.drawText(
            rect.adjusted(14, 0, -28, 0),
            Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine,
            self._name,
        )
        painter.setFont(self._chevron_font)
        painter.setPen(QColor(C_CAPTION))
        painter.drawText(rect.adjusted(0, 0, -14, 0),
                         Qt.AlignRight | Qt.AlignVCenter,
                         "▾" if self._open else "▸")

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt 命名
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._name)
            event.accept()
            return
        super().mouseReleaseEvent(event)


# ══════════════════════════════════════════════════════════════════════════ #
#  StudioSidebar
# ══════════════════════════════════════════════════════════════════════════ #
class StudioSidebar(QFrame):
    """DSH 风左侧分组导航：展开 232px / rail 56px，中间可滚动。"""

    pageRequested = pyqtSignal(int)
    searchRequested = pyqtSignal()
    railChanged = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("StudioSidebar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFrameShape(QFrame.NoFrame)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        self._rail = False
        self._expand_w = SIDEBAR_W
        self._rail_w = RAIL_W

        self._buttons: dict = {}          # page index -> [_NavItemButton, ...]
        self._index_group: dict = {}      # page index -> group name（最后一个=分类组）
        self._item_text: dict = {}        # page index -> 全名（rail tooltip）
        self._group_titles: dict = {}     # group name -> _GroupTitle
        self._group_bodies: dict = {}     # group name -> QWidget(NavGroupBody)
        self._group_open: dict = {}       # group name -> bool

        # 同一个页面允许同时出现在「常用」和分类组里（重复 index）。QButtonGroup
        # 的 autoExclusive 在这种重复场景下只会让一个副本高亮，所以这里关掉自动
        # 互斥，由 _set_checked() 手动保证「同一 index 的所有副本一起高亮、其它
        # index 全部取消」。
        self._group = QButtonGroup(self)
        self._group.setExclusive(False)

        self._build_ui()
        self._apply_style()
        self.setFixedWidth(self._expand_w)

    # -- UI 骨架 ------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 8)
        outer.setSpacing(10)
        self._outer = outer

        self._search = _SearchButton(self)
        self._search.clicked.connect(self._on_search_clicked)
        outer.addWidget(self._search, 0)

        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("SidebarScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.viewport().setAutoFillBackground(False)

        self._scroll_body = QWidget()
        self._scroll_body.setObjectName("SidebarScrollBody")
        self._scroll_body.setAttribute(Qt.WA_StyledBackground, True)
        self._scroll_body.setAutoFillBackground(False)
        self._body_layout = QVBoxLayout(self._scroll_body)
        self._body_layout.setContentsMargins(0, 2, 0, 0)
        self._body_layout.setSpacing(NAV_GROUP_GAP)
        self._body_layout.addStretch(1)
        self._scroll.setWidget(self._scroll_body)
        outer.addWidget(self._scroll, 1)

        self._sep = QFrame(self)
        self._sep.setObjectName("SidebarSep")
        self._sep.setFrameShape(QFrame.HLine)
        self._sep.setFixedHeight(1)
        outer.addWidget(self._sep, 0)

        self._bottom = QLabel("", self)
        self._bottom.setObjectName("SidebarVersion")
        self._bottom.setAlignment(Qt.AlignCenter)
        bottom_font = self._bottom.font()
        bottom_font.setPointSizeF(F_NAV_AUX_PT)
        self._bottom.setFont(bottom_font)
        self._bottom.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._bottom.hide()
        outer.addWidget(self._bottom, 0)

    def _apply_style(self) -> None:
        qss = """
QFrame#StudioSidebar {{
    background: {bg};
    border: none;
    border-right: 1px solid {border};
}}
QWidget#SidebarScrollBody {{ background: transparent; }}
QScrollArea#SidebarScroll,
QScrollArea#SidebarScroll > QWidget > QWidget {{
    background: transparent;
    border: none;
}}
QToolButton#SidebarSearch {{
    background: {surface};
    border: 1px solid {border};
    border-radius: {r_sm}px;
}}
QToolButton#SidebarSearch:hover {{ background: {hover}; }}
QToolButton#SidebarSearch:focus {{ border: 1px solid {accent}; }}
QToolButton#SidebarSearch:pressed {{ background: {active}; }}
QToolButton#NavItem {{
    background: transparent;
    border: none;
    border-radius: {r_sm}px;
}}
QToolButton#NavItem:hover {{ background: {hover}; }}
QToolButton#NavItem:checked {{ background: {selected}; }}
QToolButton#NavItem:pressed {{ background: {active}; }}
QLabel#NavGroupTitle {{
    background: transparent;
    border: none;
    border-radius: {r_sm}px;
}}
QLabel#NavGroupTitle:hover {{ background: {hover}; }}
QFrame#SidebarSep {{ background: {hairline}; border: none; }}
QLabel#SidebarVersion {{ color: {caption}; background: transparent; }}
QScrollBar:vertical {{
    width: 8px;
    background: transparent;
    margin: 0px;
}}
QScrollBar::handle:vertical {{
    background: {scroll};
    border-radius: 3px;
    min-height: 24px;
    margin: 1px 2px;
}}
QScrollBar::handle:vertical:hover {{ background: {scroll_hover}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
""".format(
            bg=C_BG,
            surface=C_SURFACE,
            border=C_BORDER,
            hover=C_HOVER,
            accent=C_ACCENT,
            active=C_ACTIVE,
            selected=C_SELECTED,
            hairline=C_HAIRLINE,
            caption=C_CAPTION,
            scroll=C_SCROLL,
            scroll_hover=C_SCROLL_HOVER,
            r_sm=R_SM,
        )
        self.setStyleSheet(qss)

    # -- 数据 ---------------------------------------------------------------
    def set_entries(self, groups, current=0) -> None:
        """重建整棵导航树。

        groups = [("常用", [entry, ...]), ...]；entry 至少含
        index/text，icon 与 key 可缺省。current 为当前页 index，传入后自动
        选中并展开它所在的组；传 None 则不自动选中。
        """
        self._clear_entries()

        normalized = []
        for group in groups or []:
            try:
                name, entries = group[0], list(group[1] or [])
            except (TypeError, IndexError):
                continue
            normalized.append((str(name), entries))

        opened = {}
        has_common = False
        for name, _entries in normalized:
            is_common = name in ("常用", "Common", "Frequently Used", "常用功能")
            opened[name] = is_common
            has_common = has_common or is_common
        # 没有「常用」组时至少展开第一组，避免整侧栏全折叠、看起来像空面板
        if normalized and not has_common:
            opened[normalized[0][0]] = True
        self._group_open = opened

        for name, entries in normalized:
            title = _GroupTitle(name)
            title.set_open(self._group_open.get(name, False))
            title.clicked.connect(self._on_group_clicked)
            self._group_titles[name] = title

            body = QWidget()
            body.setObjectName("NavGroupBody")
            body_layout = QVBoxLayout(body)
            body_layout.setContentsMargins(0, 3, 0, 6)
            body_layout.setSpacing(NAV_ITEM_GAP)
            for entry in entries:
                try:
                    button = self._make_item(entry, name)
                except Exception:  # noqa: BLE001 - 单条脏数据不拖垮整个侧栏
                    continue
                body_layout.addWidget(button)
            self._group_bodies[name] = body

            self._body_layout.insertWidget(self._body_layout.count() - 1, title)
            self._body_layout.insertWidget(self._body_layout.count() - 1, body)

        self._apply_group_visibility()
        # 切语言等重建导航树时，别把已收起的 rail 又撑回展开态的松间距
        if self._rail:
            self._body_layout.setSpacing(RAIL_GROUP_GAP)
            for body in self._group_bodies.values():
                lay = body.layout()
                if lay is not None:
                    lay.setSpacing(RAIL_ITEM_GAP)
                    lay.setContentsMargins(0, 0, 0, 0)

        if current is not None:
            try:
                self.set_current(int(current))
            except (TypeError, ValueError):
                pass

    def _clear_entries(self) -> None:
        while self._body_layout.count() > 1:  # 保留最后一个 stretch
            item = self._body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

        self._buttons.clear()
        self._index_group.clear()
        self._item_text.clear()
        self._group_titles.clear()
        self._group_bodies.clear()

        old_group = self._group
        self._group = QButtonGroup(self)
        self._group.setExclusive(False)
        if old_group is not None:
            old_group.deleteLater()

    def _make_item(self, entry, group_name):
        text = str(entry.get("text") or "")
        icon_kind = str(entry.get("icon") or "list")
        index = int(entry.get("index", -1))
        button = _NavItemButton(text, icon_kind, index)
        button.set_rail(self._rail)
        button.clicked.connect(partial(self._on_item_clicked, index))
        button.toggled.connect(partial(self._on_item_toggled, button))
        self._group.addButton(button)
        self._buttons.setdefault(index, []).append(button)
        self._index_group[index] = group_name
        self._item_text[index] = text
        self._apply_item_tooltip(button)
        return button

    # -- 选中 / 展开 --------------------------------------------------------
    def set_current(self, index: int) -> None:
        """选中某页：条目 checked，并展开它所在的分组（未展开才展开）。"""
        index = int(index)
        buttons = self._buttons.get(index)
        if not buttons:
            return
        self._set_checked(index)
        self.expand_group_of(index)
        try:
            self._scroll.ensureWidgetVisible(buttons[0], 0, 16)
        except Exception:  # noqa: BLE001 - 未显示时部分平台会拒绝滚动
            pass

    def _set_checked(self, index: int) -> None:
        """手动互斥：同一页的所有副本一起 checked，其它页全部取消。"""
        for page_index, buttons in self._buttons.items():
            wanted = page_index == index
            for button in buttons:
                if button.isChecked() != wanted:
                    button.setChecked(wanted)

    def expand_group_of(self, index: int) -> None:
        name = self._index_group.get(int(index))
        if name is None:
            return
        if not self._group_open.get(name, False):
            self._group_open[name] = True
            self._apply_group_visibility()

    def _on_group_clicked(self, name) -> None:
        self._group_open[name] = not self._group_open.get(name, False)
        self._apply_group_visibility()

    def _apply_group_visibility(self) -> None:
        for name, title in self._group_titles.items():
            title.setVisible(not self._rail)
            title.set_open(self._group_open.get(name, False))
        for name, body in self._group_bodies.items():
            body.setVisible(True if self._rail else bool(self._group_open.get(name, False)))

    # -- rail ---------------------------------------------------------------
    def set_rail(self, rail: bool) -> None:
        """切换成 56px 图标 rail（分组标题/文字全部隐藏，只留图标列）。"""
        rail = bool(rail)
        if rail == self._rail:
            return
        self._rail = rail
        # 展开态给足留白；rail 态没有文字，收紧间距免得图标列滚太长。
        if rail:
            self._outer.setContentsMargins(8, 10, 8, 8)
            self._body_layout.setSpacing(RAIL_GROUP_GAP)
            item_gap, body_margins = RAIL_ITEM_GAP, (0, 0, 0, 0)
        else:
            self._outer.setContentsMargins(12, 12, 12, 8)
            self._body_layout.setSpacing(NAV_GROUP_GAP)
            item_gap, body_margins = NAV_ITEM_GAP, (0, 3, 0, 6)
        for body in self._group_bodies.values():
            lay = body.layout()
            if lay is not None:
                lay.setSpacing(item_gap)
                lay.setContentsMargins(*body_margins)
        self.setFixedWidth(self._rail_w if rail else self._expand_w)
        self._search.set_rail(rail)
        self._apply_group_visibility()
        for buttons in self._buttons.values():
            for button in buttons:
                button.set_rail(rail)
                self._apply_item_tooltip(button)
        self._bottom.setVisible(bool(self._bottom.text()) and not rail)
        self.railChanged.emit(rail)

    def toggle_rail(self) -> None:
        self.set_rail(not self._rail)

    def is_rail(self) -> bool:
        return bool(self._rail)

    # -- 底部 / 其它 --------------------------------------------------------
    def set_bottom_text(self, text: str) -> None:
        """底部版本/状态文字；空串则隐藏（rail 下只保留分隔线）。"""
        self._bottom.setText(str(text or ""))
        self._bottom.setVisible(bool(self._bottom.text()) and not self._rail)

    def _apply_item_tooltip(self, button) -> None:
        text = self._item_text.get(button._index, "")
        button.setToolTip(text if self._rail else "")

    # -- 信号 ---------------------------------------------------------------
    def _on_item_clicked(self, index, checked=False) -> None:
        self._set_checked(int(index))
        self.expand_group_of(index)
        self.pageRequested.emit(int(index))

    def _on_item_toggled(self, button, checked=False) -> None:
        button.update()

    def _on_search_clicked(self, checked=False) -> None:
        self.searchRequested.emit()


# ══════════════════════════════════════════════════════════════════════════ #
#  CommandPalette（Ctrl+K）
# ══════════════════════════════════════════════════════════════════════════ #
class CommandPalette(QDialog):
    """无边框命令面板：搜索框 + 过滤列表。

    entries = [(显示文字, payload), ...]；payload 可以是页序号(int)或
    action 名(str)，也可以传 (文字, payload, key) 三元组，key 一并参与过滤。
    """

    def __init__(self, entries, parent=None, title=None):
        super().__init__(parent)
        self.setObjectName("CommandPalette")
        self.setWindowTitle(str(title or "命令面板"))
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(PALETTE_W, PALETTE_H)

        self._entries = []
        for raw in entries or []:
            try:
                text = str(raw[0])
                payload = raw[1]
                key = str(raw[2]) if len(raw) > 2 else ""
            except (TypeError, IndexError):
                continue
            self._entries.append((text, payload, key))
        self._picked = None

        self._build_ui()
        self._apply_style()
        self.filter_items("")

    # -- UI -----------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 12)
        outer.setSpacing(10)

        self._search = QLineEdit(self)
        self._search.setObjectName("PaletteSearch")
        self._search.setPlaceholderText("搜索功能或动作…")
        self._search.setFixedHeight(38)
        self._search.setClearButtonEnabled(False)
        search_font = self._search.font()
        search_font.setPointSizeF(F_BODY_PT)
        self._search.setFont(search_font)

        self._list = QListWidget(self)
        self._list.setObjectName("PaletteList")
        self._list.setFrameShape(QFrame.NoFrame)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._list.setUniformItemSizes(True)
        self._list.setSpacing(3)
        list_font = self._list.font()
        list_font.setPointSizeF(F_SECONDARY_PT)
        self._list.setFont(list_font)

        self._hint = QLabel("↑↓ 选择 · Enter 打开 · Esc 关闭", self)
        self._hint.setObjectName("PaletteHint")
        self._hint.setAlignment(Qt.AlignCenter)
        hint_font = self._hint.font()
        hint_font.setPointSizeF(max(6.5, F_CAPTION_PT))
        self._hint.setFont(hint_font)

        outer.addWidget(self._search, 0)
        outer.addWidget(self._list, 1)
        outer.addWidget(self._hint, 0)

        self._search.textChanged.connect(self._apply_filter)
        self._search.installEventFilter(self)
        self._list.installEventFilter(self)
        self._list.itemDoubleClicked.connect(lambda _item: self._accept_current())
        self._list.itemActivated.connect(lambda _item: self._accept_current())

    def _apply_style(self) -> None:
        qss = """
QDialog#CommandPalette {{ background: transparent; }}
QLineEdit#PaletteSearch {{
    background: {surface};
    color: {text};
    border: 1px solid {border_strong};
    border-radius: {r_md}px;
    padding: 0 12px;
    selection-background-color: {accent_subtle};
    selection-color: {text};
}}
QLineEdit#PaletteSearch:focus {{ border: 1px solid {accent}; }}
QListWidget#PaletteList {{
    background: transparent;
    border: none;
    outline: none;
}}
QListWidget#PaletteList::item {{
    height: {row_h}px;
    padding: 0 10px;
    border-radius: {r_sm}px;
    color: {text};
}}
QListWidget#PaletteList::item:hover {{ background: {hover}; }}
QListWidget#PaletteList::item:selected {{
    background: {selected};
    color: {text};
}}
QLabel#PaletteHint {{ color: {caption}; background: transparent; }}
QScrollBar:vertical {{ width: 8px; background: transparent; margin: 0px; }}
QScrollBar::handle:vertical {{
    background: {scroll};
    border-radius: 3px;
    min-height: 24px;
    margin: 1px 2px;
}}
QScrollBar::handle:vertical:hover {{ background: {scroll_hover}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
""".format(
            surface=C_SURFACE,
            text=C_TEXT,
            border=C_BORDER,
            border_strong=C_BORDER_STRONG,
            accent=C_ACCENT,
            accent_subtle=C_ACCENT_SUBTLE,
            hover=C_HOVER,
            selected=C_SELECTED,
            caption=C_CAPTION,
            scroll=C_SCROLL,
            scroll_hover=C_SCROLL_HOVER,
            r_sm=R_SM,
            r_md=R_MD,
            row_h=PALETTE_ROW_H,
        )
        self.setStyleSheet(qss)

    # -- 过滤 ---------------------------------------------------------------
    def filter_items(self, text: str) -> int:
        """按查询串重建列表，返回命中条数。

        子串、大小写不敏感；同时匹配显示文字、三元组的 key、以及 str 型
        payload（这样动作名也能被搜到）。空查询显示全部。
        """
        query = str(text or "").strip().lower()
        self._list.clear()
        shown = 0
        for display, payload, key in self._entries:
            haystack = [display, key]
            if isinstance(payload, str):
                haystack.append(payload)
            if query and not any(query in part.lower() for part in haystack if part):
                continue
            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, payload)
            item.setSizeHint(QSize(0, PALETTE_ROW_H))
            item.setToolTip(display)
            self._list.addItem(item)
            shown += 1
        if shown:
            self._list.setCurrentRow(0)
        return shown

    def _apply_filter(self, text: str) -> None:
        self.filter_items(text)

    # -- 键盘 ---------------------------------------------------------------
    def _move_current(self, step: int) -> None:
        count = self._list.count()
        if count <= 0:
            return
        row = self._list.currentRow()
        if row < 0:
            row = 0
        else:
            row = max(0, min(count - 1, row + int(step)))
        self._list.setCurrentRow(row)
        item = self._list.item(row)
        if item is not None:
            self._list.scrollToItem(item)

    def _accept_current(self) -> None:
        item = self._list.currentItem()
        if item is None:
            if self._list.count() <= 0:
                return
            item = self._list.item(0)
        self._picked = item.data(Qt.UserRole)
        self.accept()

    def eventFilter(self, obj, event):  # noqa: N802 - Qt 命名
        if event.type() == QEvent.KeyPress:
            key = event.key()
            if key == Qt.Key_Down:
                self._move_current(1)
                return True
            if key == Qt.Key_Up:
                self._move_current(-1)
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter):
                self._accept_current()
                return True
            if key == Qt.Key_Escape:
                self.reject()
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):  # noqa: N802 - Qt 命名
        key = event.key()
        if key == Qt.Key_Escape:
            self.reject()
            return
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self._accept_current()
            return
        if key == Qt.Key_Down:
            self._move_current(1)
            return
        if key == Qt.Key_Up:
            self._move_current(-1)
            return
        super().keyPressEvent(event)

    # -- 显示 / 结果 --------------------------------------------------------
    def showEvent(self, event):  # noqa: N802 - Qt 命名
        super().showEvent(event)
        self._center_on_parent()
        QTimer.singleShot(0, self._focus_search)

    def _focus_search(self) -> None:
        try:
            self._search.setFocus(Qt.OtherFocusReason)
            self._search.selectAll()
        except Exception:  # noqa: BLE001 - 窗口正在销毁时忽略
            pass

    def _center_on_parent(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            window = parent.window()
            geometry = (window if window is not None else parent).frameGeometry()
            if geometry.isValid() and geometry.width() > 0:
                self.move(geometry.center() - self.rect().center())
                return
        screen = QApplication.primaryScreen()
        if screen is not None:
            geometry = screen.availableGeometry()
            self.move(geometry.center() - self.rect().center())

    def paintEvent(self, event):  # noqa: N802 - Qt 命名
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, R_LG, R_LG)
        painter.fillPath(path, QColor(C_MENU_BG))
        painter.setPen(QPen(QColor(C_BORDER), 1))
        painter.drawPath(path)

    def selected_payload(self):
        """当前高亮项的 payload（未选中返回 None）。"""
        item = self._list.currentItem()
        return None if item is None else item.data(Qt.UserRole)

    def pick(self):
        """模态运行；选中返回 payload，取消（Esc / 关闭）返回 None。"""
        self._picked = None
        result = self.exec_()
        if result == QDialog.Accepted:
            return self._picked
        return None
