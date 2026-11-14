# -*- coding: utf-8 -*-
"""canvas_cards_bar.py — 画布下方「四张工具卡片」行（渲染风格 / 显示设置 / 测量与分析 / 文件导出）
================================================================================

参考稿把画布下方的「一键样式 + 分子显示 + 导出」拆成 **四张白色圆角卡片**，
一行并排放在 42px 紧凑工具条（``studio_canvas_bar._CanvasBar``）**下面**：

    ┌─ 渲染风格 ─┐ ┌─ 显示设置 ─┐ ┌─ 测量与分析 ─┐ ┌─ 文件导出 ─┐
    │ sob-art    │ │ 隐藏氢原子 │ │ 距离 角度     │ │ 截图       │
    │ HoukMol3d  │ │ 显示原子编号│ │ 二面角        │ │ 导出图片   │
    │ …           │ │ …          │ │ 测量开关 …    │ │ 3D 模型 …  │
    └────────────┘ └────────────┘ └──────────────┘ └────────────┘

设计原则
--------
1. **只做转发，不复制业务逻辑**：卡片上的每个按钮都点原控件 / 原 QAction
   （``_CanvasBar._apply_style``、``act.trigger()``、``源按钮.click()``），
   与原工具条永远同一份状态，不存在「两套状态对不上」的问题。
2. **不搬走、不删除、不 reparent 任何已有控件**：只在紧凑工具条**下面**
   插入本控件；原卡片、原工具条、原菜单一行不动。安装失败返回 ``None``，
   界面保持原样。
3. **默认隐藏**：由 ``reference_shell`` 的「工具 ▾」按钮负责显隐；隐藏时
   不占布局高度，不影响画布。
4. 所有对内私有属性都用 ``getattr`` / ``try-except`` 读，Qt 对象被销毁
   （``RuntimeError``）也只跳过那一项，不崩。

对外 API
--------
::

    install_canvas_cards(win) -> CanvasCardsBar | None
    CanvasCardsBar.refresh() -> None      # 重读原工具条/窗口的文字与勾选态
    CanvasCardsBar.set_lang(lang) -> None # "zh" / "en"，内部固定文案中英切换

依赖：PyQt5；可选 ``molstudio.ui.ui_icons.make_icon``（没有就纯文字）。
"""

from __future__ import annotations

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

__all__ = ["CanvasCardsBar", "install_canvas_cards"]


# ══════════════════════════════════════════════════════════════════════════ #
#  固定文案（中英对照）：卡片标题 + 卡片内自建的「更多 / 开关」按钮
# ══════════════════════════════════════════════════════════════════════════ #
_CARD_ORDER = ("render", "display", "measure", "export")

#: 四张卡片的标题
_TITLES = {
    "render": ("渲染风格", "Render Style"),
    "display": ("显示设置", "Display"),
    "measure": ("测量与分析", "Measure & Analyze"),
    "export": ("文件导出", "File Export"),
}

#: 卡片内自建按钮的文字（键 → (中文, 英文)），与源 QAction 无关，需自己翻译
_LABELS = {
    "render_more": ("更多", "More"),
    "display_more": ("更多", "More"),
    "measure_toggle": ("测量开关", "Measure"),
    "measure_clear": ("清除测量", "Clear"),
    "surface": ("表面分析", "Surface"),
    "export_more": ("更多导出", "More Export"),
    "model3d": ("3D 模型", "3D Model"),
}

#: 按钮统一 objectName（测试 / QSS 用）
_BTN_NAME = "CanvasCardsBtn"
_CARD_NAME = "CanvasCard"
_BAR_NAME = "CanvasCardsBar"
_TITLE_NAME = "CanvasCardTitle"

#: 卡片按钮网格列数。参考稿写的是「4 列」，但画布列实测只有 ~600px，
#: 四张卡片均分后每张 ~145px，4 列会把「HoukMol3d」压成 30px 宽的一小截；
#: 2 列（每列 ~65px）是这个宽度下唯一能读清文字的排法。宽度富余的窗口下
#: 按钮会被拉伸铺满，不会留下空洞。
_GRID_COLS = 2

# ══════════════════════════════════════════════════════════════════════════ #
#  QSS：白卡 / 1px #E5E9F0 描边 / 10px 圆角；hover 浅蓝；选中浅蓝 + 蓝字
# ══════════════════════════════════════════════════════════════════════════ #
_CARDS_QSS = """
QWidget#CanvasCardsBar {
    background: transparent;
    border: none;
}
QFrame#CanvasCard {
    background: #FFFFFF;
    border: 1px solid #E5E9F0;
    border-radius: 10px;
}
QFrame#CanvasCard QLabel#CanvasCardTitle {
    color: #374151;
    font-size: 10pt;
    font-weight: 600;
    background: transparent;
    border: none;
    padding: 0px;
}
QFrame#CanvasCard QToolButton#CanvasCardsBtn {
    background: #FFFFFF;
    border: 1px solid #E5E9F0;
    border-radius: 8px;
    padding: 0px 2px;
    min-height: 16px;
    max-height: 18px;
    color: #4B5563;
    font-size: 8pt;
    font-weight: 500;
}
QFrame#CanvasCard QToolButton#CanvasCardsBtn:hover {
    background: #EEF3FF;
    border-color: #C7D8F0;
}
QFrame#CanvasCard QToolButton#CanvasCardsBtn:pressed {
    background: #E3F2FD;
}
QFrame#CanvasCard QToolButton#CanvasCardsBtn:checked {
    background: #E3F2FD;
    border-color: #90CAF9;
    color: #1565C0;
}
QFrame#CanvasCard QToolButton#CanvasCardsBtn:disabled {
    color: #9CA3AF;
    background: #F7F8FA;
}
"""


# ══════════════════════════════════════════════════════════════════════════ #
#  安全取值小工具（Qt 对象可能已被 deleteLater 销毁 → RuntimeError）
# ══════════════════════════════════════════════════════════════════════════ #
def _safe_attr(obj, name, default=None):
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


def _safe_text(widget) -> str:
    try:
        return (widget.text() or "").strip()
    except Exception:
        return ""


def _safe_tip(widget) -> str:
    try:
        return (widget.toolTip() or "").strip()
    except Exception:
        return ""


def _make_icon(kind: str, size: int = 14) -> QIcon | None:
    """可选图标：``ui_icons`` 不可用时返回 None（纯文字照常工作）。"""
    try:
        from molstudio.ui.ui_icons import make_icon

        return make_icon(kind, "#4B5563", size)
    except Exception:
        return None


def _set_checked(btn, on: bool) -> None:
    """改勾选态但不触发 ``clicked``（QToolButton 的 clicked 只在用户点击时发）。"""
    try:
        if bool(btn.isChecked()) == bool(on):
            return
        btn.blockSignals(True)
        try:
            btn.setChecked(bool(on))
        finally:
            btn.blockSignals(False)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════ #
#  四张卡片本体
# ══════════════════════════════════════════════════════════════════════════ #
class CanvasCardsBar(QWidget):
    """画布下方一行四张工具卡片；所有按钮转发给 ``_CanvasBar`` 的原控件。"""

    def __init__(self, win, bar, parent=None):
        super().__init__(parent)
        self.setObjectName(_BAR_NAME)
        self.setStyleSheet(_CARDS_QSS)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setMinimumHeight(96)

        self._win = win
        self._bar = bar
        self._lang = self._window_lang(win)

        # 结构登记表
        self._cards = {}        # key -> (QFrame, QGridLayout, [QToolButton])
        self._titles = {}       # key -> QLabel
        self._labels = {}       # label key -> QToolButton（自建固定文案按钮）
        self._style_btns = []   # [(QToolButton, 原样式按钮)]
        self._display_btns = []  # [(QToolButton, QAction)]
        self._kind_btns = []    # [(QToolButton, QAction, combo 索引)]
        self._plain_btns = []   # [(QToolButton, QAction, 原控件)]
        self._measure_toggle = None
        self._measure_src = None

        self._build()
        self.refresh()

    # ── 构造 ────────────────────────────────────────────────────────────
    @staticmethod
    def _window_lang(win) -> str:
        try:
            lang = str(getattr(win, "_lang", "") or "").lower()
            if lang in ("zh", "en"):
                return lang
        except Exception:
            pass
        try:
            import molstudio.core.i18n as i18n

            return "zh" if getattr(i18n, "_CURRENT_LANG", "zh") == "zh" else "en"
        except Exception:
            return "zh"

    def _build(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 3, 6, 3)
        root.setSpacing(8)
        for key in _CARD_ORDER:
            card, grid = self._make_card(key)
            self._cards[key] = (card, grid, [])
            root.addWidget(card, 1)
        try:
            self._build_render_card()
        except Exception:
            pass
        try:
            self._build_display_card()
        except Exception:
            pass
        try:
            self._build_measure_card()
        except Exception:
            pass
        try:
            self._build_export_card()
        except Exception:
            pass

    def _make_card(self, key: str):
        card = QFrame(self)
        card.setObjectName(_CARD_NAME)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        card.setMinimumWidth(0)
        v = QVBoxLayout(card)
        v.setContentsMargins(8, 4, 8, 4)
        v.setSpacing(4)

        title = QLabel("")
        title.setObjectName(_TITLE_NAME)
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        title.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        v.addWidget(title)
        self._titles[key] = title

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(4)
        for col in range(_GRID_COLS):
            grid.setColumnStretch(col, 1)
        v.addLayout(grid)
        # 四张卡片内容行数不同（2~3 行），底部留 stretch 让它们等高时
        # 内容统一顶对齐，而不是在卡片里垂直居中。
        v.addStretch(1)
        return card, grid

    def _new_btn(self, card, grid, text: str, *, tip: str = "",
                 icon: str | None = None, checkable: bool = False) -> QToolButton:
        btn = QToolButton(card)
        btn.setObjectName(_BTN_NAME)
        btn.setText(text or "—")
        if tip:
            btn.setToolTip(tip)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setCheckable(bool(checkable))
        # 显式 1px 下限：画布列只有 ~540px，四张卡片并排时按钮必须能被压缩，
        # 否则 cards 的 minimumSizeHint 会把画布列顶宽、挤掉右侧面板。
        btn.setMinimumWidth(1)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        ic = _make_icon(icon) if icon else None
        if ic is not None:
            btn.setIcon(ic)
            btn.setIconSize(QSize(14, 14))
            btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        else:
            btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        # 注意：btn 已挂在 card 下，计数时要排除它自己，否则第一个按钮会
        # 被算成 index=1（第一行只放得下一个按钮）。
        index = len(self._card_buttons(card, exclude=btn))
        grid.addWidget(btn, index // _GRID_COLS, index % _GRID_COLS)
        return btn

    def _card_buttons(self, card, exclude=None) -> list:
        try:
            return [w for w in card.findChildren(QToolButton)
                    if w.parentWidget() is card and w is not exclude]
        except Exception:
            return []

    def _register(self, key: str, btn: QToolButton, label_key: str | None = None) -> None:
        try:
            self._cards[key][2].append(btn)
        except Exception:
            pass
        if label_key is not None:
            self._labels[label_key] = btn

    # ── 卡片 ①：渲染风格 ────────────────────────────────────────────────
    def _build_render_card(self) -> None:
        card, grid, _btns = self._cards["render"]
        chips = list(_safe_attr(self._bar, "_chips", []) or [])
        for chip, src in chips:
            text = _safe_text(chip) or _safe_text(src)
            tip = _safe_tip(src) or _safe_tip(chip)
            btn = self._new_btn(card, grid, text, tip=tip, checkable=True)
            btn.clicked.connect(
                lambda _checked=False, s=src: self._apply_style(s))
            self._style_btns.append((btn, src))
            self._register("render", btn)

        more = self._new_btn(card, grid, self._label_text("render_more"),
                             tip=self._more_tip("render"), icon="chevron")
        more.clicked.connect(
            lambda _checked=False: self._popup_bar_menu("_style_btn", more))
        self._register("render", more, "render_more")

    def _apply_style(self, src) -> None:
        try:
            fn = getattr(self._bar, "_apply_style", None)
            if callable(fn):
                fn(src)
        except Exception:
            pass
        self.refresh()

    # ── 卡片 ②：显示设置 ────────────────────────────────────────────────
    def _build_display_card(self) -> None:
        card, grid, _btns = self._cards["display"]
        acts = self._display_actions()[:4]
        for act in acts:
            btn = self._new_btn(card, grid, _safe_text(act),
                                tip=_safe_tip(act), checkable=True)
            btn.clicked.connect(
                lambda _checked=False, a=act: self._trigger_action(a))
            self._display_btns.append((btn, act))
            self._register("display", btn)

        more = self._new_btn(card, grid, self._label_text("display_more"),
                             tip=self._more_tip("display"), icon="chevron")
        more.clicked.connect(
            lambda _checked=False: self._popup_bar_menu("_display_btn", more))
        self._register("display", more, "display_more")

    def _display_actions(self) -> list:
        """显示菜单里的 checkable QAction（跳过分隔线与 QWidgetAction 行）。"""
        menu = self._bar_menu("_display_btn")
        if menu is None:
            return []
        out = []
        try:
            for act in menu.actions():
                try:
                    if act.isSeparator():
                        continue
                    if act.isCheckable():
                        out.append(act)
                except Exception:
                    continue
        except Exception:
            return []
        return out

    # ── 卡片 ③：测量与分析 ──────────────────────────────────────────────
    def _build_measure_card(self) -> None:
        card, grid, _btns = self._cards["measure"]
        kinds = list(_safe_attr(self._bar, "_kind_acts", []) or [])
        for entry in kinds:
            try:
                act, idx = entry[0], int(entry[1])
            except Exception:
                try:
                    act = entry[0]
                    idx = -1
                except Exception:
                    continue
            btn = self._new_btn(card, grid, _safe_text(act),
                                tip=_safe_tip(act), checkable=True)
            btn.clicked.connect(
                lambda _checked=False, a=act, i=idx: self._pick_kind(a, i))
            self._kind_btns.append((btn, act, idx))
            self._register("measure", btn)

        src = _safe_attr(self._bar, "_measure_src", None)
        self._measure_src = src
        toggle = self._new_btn(card, grid, self._label_text("measure_toggle"),
                               tip=self._label_tip("measure_toggle", "切换测量模式"),
                               icon="target", checkable=True)
        toggle.clicked.connect(lambda _checked=False: self._toggle_measure())
        self._measure_toggle = toggle
        self._register("measure", toggle, "measure_toggle")

        act, src = self._find_plain_action(
            ("清除", "clear"),
            contains=("清除", "clear", "测量", "measure"),
            exclude=("样式", "style", "analysis"))
        if act is not None or src is not None:
            btn = self._new_btn(card, grid, self._label_text("measure_clear"),
                                tip=self._label_tip("measure_clear", "清除全部测量标注"),
                                icon="close")
            btn.clicked.connect(
                lambda _checked=False, a=act, s=src: self._trigger_plain(a, s))
            self._plain_btns.append((btn, act, src))
            self._register("measure", btn, "measure_clear")

        surface = self._new_btn(card, grid, self._label_text("surface"),
                                tip=self._label_tip("surface", "打开表面距离投影图"),
                                icon="chart")
        surface.clicked.connect(lambda _checked=False: self._open_surface_page())
        self._register("measure", surface, "surface")

    def _pick_kind(self, act, idx: int) -> None:
        combo = _safe_attr(self._bar, "_kind_combo", None)
        try:
            if combo is not None and idx >= 0:
                combo.setCurrentIndex(idx)
        except Exception:
            pass
        self._trigger_action(act)

    def _toggle_measure(self) -> None:
        try:
            src = self._measure_src or _safe_attr(self._bar, "_measure_src", None)
            if src is not None:
                src.click()
        except Exception:
            pass
        self.refresh()

    def _open_surface_page(self) -> None:
        """切到「表面距离投影图」功能页（tab_surfproj）。

        优先走窗口自己的 ``_on_sidebar_page``（会同步侧栏高亮），没有就退回
        ``tabs.setCurrentIndex``；两者都没有就静默失败。
        """
        win = self._win
        if win is None:
            return
        try:
            keys = list(_safe_attr(win, "_tab_keys", []) or [])
            idx = keys.index("tab_surfproj")
        except Exception:
            return
        try:
            handler = getattr(win, "_on_sidebar_page", None)
            if callable(handler):
                handler(idx)
                return
        except Exception:
            pass
        try:
            tabs = getattr(win, "tabs", None)
            if tabs is not None:
                tabs.setCurrentIndex(idx)
        except Exception:
            pass

    # ── 卡片 ④：文件导出 ────────────────────────────────────────────────
    def _build_export_card(self) -> None:
        card, grid, _btns = self._cards["export"]

        act, src = self._find_plain_action(("截图", "snapshot", "snap"))
        if act is not None or src is not None:
            btn = self._new_btn(card, grid, _safe_text(act) or _safe_text(src),
                                tip=_safe_tip(act) or _safe_tip(src))
            btn.clicked.connect(
                lambda _checked=False, a=act, s=src: self._trigger_plain(a, s))
            self._plain_btns.append((btn, act, src))
            self._register("export", btn)

        act, src = self._find_plain_action(
            ("导出图片", "export image"),
            contains=("图片", "image", "导出图片"),
            exclude=("截图", "snapshot"))
        if act is not None or src is not None:
            btn = self._new_btn(card, grid, _safe_text(act) or _safe_text(src),
                                tip=_safe_tip(act) or _safe_tip(src))
            btn.clicked.connect(
                lambda _checked=False, a=act, s=src: self._trigger_plain(a, s))
            self._plain_btns.append((btn, act, src))
            self._register("export", btn)

        model3d = self._new_btn(card, grid, self._label_text("model3d"),
                                tip=self._label_tip("model3d", "导出可旋转的 3D 模型（.glb）"),
                                icon="cube")
        model3d.clicked.connect(lambda _checked=False: self._export_3d())
        self._register("export", model3d, "model3d")

        more = self._new_btn(card, grid, self._label_text("export_more"),
                             tip=self._label_tip("export_more", "打开导出菜单"),
                             icon="download")
        more.clicked.connect(
            lambda _checked=False: self._popup_bar_menu("_export_btn", more))
        self._register("export", more, "export_more")

    def _export_3d(self) -> None:
        try:
            fn = getattr(self._win, "_export_current_ppt3d", None)
            if callable(fn):
                fn()
        except Exception:
            pass

    # ── 转发 / 菜单 / 查找 ─────────────────────────────────────────────
    @staticmethod
    def _trigger_action(act) -> None:
        try:
            if act is not None:
                act.trigger()
        except Exception:
            pass

    def _trigger_plain(self, act, src) -> None:
        """点原 QAction（文字随语言）；没有 action 就退回原控件 click()。"""
        if act is not None:
            self._trigger_action(act)
        elif src is not None:
            try:
                src.click()
            except Exception:
                pass
        self.refresh()

    def _bar_menu(self, attr: str):
        btn = _safe_attr(self._bar, attr, None)
        if btn is None:
            return None
        try:
            return btn.menu()
        except Exception:
            return None

    def _popup_bar_menu(self, attr: str, anchor) -> None:
        menu = self._bar_menu(attr)
        if menu is None or anchor is None:
            return
        try:
            menu.exec_(anchor.mapToGlobal(anchor.rect().bottomLeft()))
        except Exception:
            pass

    def _plain_entries(self) -> list:
        out = []
        for entry in list(_safe_attr(self._bar, "_plain_acts", []) or []):
            try:
                act = entry[0]
                src = entry[1] if len(entry) > 1 else None
            except Exception:
                continue
            out.append((act, src))
        return out

    def _find_plain_action(self, exact, contains=(), exclude=()):
        """在 ``_plain_acts`` 里按文字认领一个转发目标（中英都认）。"""
        exact_l = tuple(str(w).lower() for w in exact)
        contains_l = tuple(str(w).lower() for w in contains) or exact_l
        exclude_l = tuple(str(w).lower() for w in exclude)
        entries = self._plain_entries()

        def _excluded(*texts) -> bool:
            return any(e and e in t for t in texts for e in exclude_l)

        # ① 文字全等（最准，中英各一条）
        for act, src in entries:
            t = _safe_text(act).lower()
            if t and t in exact_l and not _excluded(t, t):
                return act, src
        # ② 文字 / tooltip 包含关键字
        for act, src in entries:
            t = _safe_text(act).lower()
            tip = _safe_tip(act).lower()
            if _excluded(t, tip):
                continue
            if any(w and w in t for w in contains_l) or \
                    any(w and w in tip for w in contains_l):
                return act, src
        return None, None

    # ── 文字 ────────────────────────────────────────────────────────────
    def _label_text(self, key: str) -> str:
        pair = _LABELS.get(key, (key, key))
        return pair[1] if self._lang == "en" else pair[0]

    def _label_tip(self, key: str, zh_tip: str) -> str:
        return zh_tip if self._lang != "en" else self._label_text(key)

    @staticmethod
    def _more_tip(card_key: str) -> str:
        return {"render": "更多渲染样式", "display": "更多显示选项",
                "measure": "更多测量选项", "export": "更多导出选项"}.get(card_key, "")

    # ── 对外：语言 / 刷新 ───────────────────────────────────────────────
    def set_lang(self, lang: str) -> None:
        """切换卡片自带文案的语言，并重读源控件（源控件文字跟随 app 语言）。"""
        try:
            self._lang = "en" if str(lang or "").lower().startswith("en") else "zh"
        except Exception:
            self._lang = "zh"
        # 源控件（原工具条菜单项等）由 studio_canvas_bar.update_texts 负责中英
        try:
            updater = getattr(self._bar, "update_texts", None)
            if callable(updater):
                updater()
        except Exception:
            pass
        self.refresh()

    def refresh(self) -> None:
        """重读原工具条 / 窗口的文字与勾选态；任何一项缺失都只跳过。"""
        self._sync_titles()
        for key, btn in list(self._labels.items()):
            try:
                btn.setText(self._label_text(key))
            except Exception:
                continue
        self._sync_style_btns()
        self._sync_display_btns()
        self._sync_kind_btns()
        self._sync_plain_btns()
        self._sync_measure_toggle()

    def _sync_titles(self) -> None:
        for key, label in list(self._titles.items()):
            pair = _TITLES.get(key)
            if pair is None:
                continue
            try:
                label.setText(pair[1] if self._lang == "en" else pair[0])
            except Exception:
                continue

    def _sync_style_btns(self) -> None:
        is_active = getattr(self._bar, "_is_active", None)
        for btn, src in list(self._style_btns):
            try:
                text = _safe_text(src) or _safe_text(btn)
                if text:
                    btn.setText(text)
                tip = _safe_tip(src)
                if tip:
                    btn.setToolTip(tip)
                active = False
                if callable(is_active):
                    try:
                        active = bool(is_active(src))
                    except Exception:
                        active = False
                _set_checked(btn, active)
            except Exception:
                continue

    def _sync_display_btns(self) -> None:
        for btn, act in list(self._display_btns):
            try:
                text = _safe_text(act)
                if text:
                    btn.setText(text)
                tip = _safe_tip(act)
                if tip:
                    btn.setToolTip(tip)
                try:
                    checked = bool(act.isChecked())
                except Exception:
                    checked = False
                _set_checked(btn, checked)
            except Exception:
                continue

    def _sync_kind_btns(self) -> None:
        combo = _safe_attr(self._bar, "_kind_combo", None)
        for btn, act, idx in list(self._kind_btns):
            try:
                text = _safe_text(act)
                if text:
                    btn.setText(text)
                tip = _safe_tip(act)
                if tip:
                    btn.setToolTip(tip)
                checked = False
                if combo is not None and idx >= 0:
                    try:
                        checked = int(combo.currentIndex()) == int(idx)
                    except Exception:
                        checked = False
                _set_checked(btn, checked)
            except Exception:
                continue

    def _sync_plain_btns(self) -> None:
        # 「清除测量」这类按钮自带固定中英文案（见 _LABELS），不跟随源控件文字
        internal = set(self._labels.values())
        for btn, act, src in list(self._plain_btns):
            if btn in internal:
                continue
            try:
                text = _safe_text(act) or _safe_text(src)
                if text:
                    btn.setText(text)
                tip = _safe_tip(act) or _safe_tip(src)
                if tip:
                    btn.setToolTip(tip)
            except Exception:
                continue

    def _sync_measure_toggle(self) -> None:
        btn = self._measure_toggle
        if btn is None:
            return
        src = self._measure_src or _safe_attr(self._bar, "_measure_src", None)
        if src is None:
            return
        try:
            _set_checked(btn, bool(src.isChecked()))
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════ #
#  对外入口
# ══════════════════════════════════════════════════════════════════════════ #
def install_canvas_cards(win):
    """在紧凑工具条 ``win._studio_canvas_bar`` 正下方插入四张工具卡片。

    参数
    ----
    win : QMainWindow
        需要已有 ``win._studio_canvas_bar``（``install_compact_canvas_bar``
        安装的 ``_CanvasBar``）与 ``win.cub_canvas``；缺一个就返回 ``None``。

    返回
    ----
    CanvasCardsBar | None
        成功返回卡片控件（默认隐藏，由窗口的「工具 ▾」开关显隐）；插入失败
        返回 ``None``，界面保持原样。

    幂等：重复调用返回同一个已安装的卡片控件。
    """
    try:
        if win is None:
            return None
        bar = _safe_attr(win, "_studio_canvas_bar", None)
        if bar is None:
            return None
        if _safe_attr(win, "cub_canvas", None) is None:
            return None

        prev = _safe_attr(win, "_canvas_cards_bar", None)
        if prev is not None:
            try:
                if prev.parent() is not None:
                    return prev
            except RuntimeError:
                pass

        parent = bar.parentWidget()
        if parent is None:
            return None
        lay = parent.layout()
        if lay is None:
            return None

        # 万一窗口属性丢了：先看父布局里有没有已经装过的卡片
        try:
            for child in parent.findChildren(CanvasCardsBar):
                return child
        except Exception:
            pass

        cards = CanvasCardsBar(win, bar, parent)
        idx = lay.indexOf(bar)
        if idx < 0:
            lay.addWidget(cards)
        else:
            lay.insertWidget(idx + 1, cards)
        cards.setVisible(False)
        try:
            win._canvas_cards_bar = cards
        except Exception:
            pass
        return cards
    except Exception:
        return None
