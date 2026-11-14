# -*- coding: utf-8 -*-
"""studio_canvas_bar.py — 画布底部「一键样式 + 分子显示」卡片 → 42px 单行工具条。

背景
----
``molstudio/render/ovcanvas/_panel.py`` 在画布正下方建了一张
``QWidget#CubStyleWrap`` 卡片（内部 ``QWidget#CubStyleBar``），实测在
1400x820 窗口下 **267px 高**（样式条本身 251px），把画布压缩到只剩 435px。
studio 界面（``main_window_studio``）要求把它换成一条 **≤44px** 的紧凑工具条。

本模块的做法
------------
**不改 `_panel.py` 一行**，只在既有控件树上做一次「皮肤后处理」：

1. 找到 ``cub_canvas`` 里的 ``CubStyleBar`` 及其所在卡片（通常是
   ``cub._style_wrap``），在卡片的**原父布局位置**插入 ``QFrame#CanvasBar``，
   然后把卡片 ``hide()`` —— 画布底部只剩新的一条。
2. 新工具条里 **不复制任何业务逻辑**，全部转发给原控件：
   - **常用样式胶囊**：sob-art / HoukMol3d / 2D 平涂 / IQmol 四条件做成常显的
     小胶囊，点一次就换风格（「一键样式」的本意）。当前样式高亮，初始值按画布
     ``glw._style_name`` 反查，认不出就按默认 sob-art。
   - 「样式 ▾」：其余五个一键样式 → ``QAction``，触发即 ``原按钮.click()``；
     菜单打开时按「最后应用过的那一项」打勾（原按钮可 checkable 时按 checked
     同步）。**「清空样式」并入本菜单底部** —— 它只对样式有意义，单独挂在
     VESTA 后面容易被误点。
   - 「显示 ▾」：``QCheckBox``（隐藏氢原子 / 显示原子编号 / 显示元素符号 /
     透明背景）→ checkable QAction，双向同步（``blockSignals`` 防回环）；
     「保留H编号」输入框整组搬进菜单（``QWidgetAction``，原实例不变）。
   - 「导出 ▾」：截图 / 导出图片 / 导出格式（PNG·JPG·TIFF·SVG）/ 测量类型
     （距离·键角·二面角）/ 测量开关（checkable 同步）/ 清除 / 同步到 VMD ——
     全部 ``原按钮.click()`` 或 ``原下拉.setCurrentIndex()``。
   - 「更多 ▾」：一组「导出设置」——**出图观感下拉与 DPI 输入组都放这里**。
     观感那个下拉实测 159px 宽，和四个胶囊 + 三个菜单挤一行要 632px，超过
     520px 的画布宽度；两者本来只影响出图，合进一组更合理（控件实例仍是原来
     那一个）。其余未覆盖按钮（新增的兜底按钮）也进这里。
3. **宽度不够时胶囊从右往左按顺序收起**（``_fit_chips``）。画布最窄能到
   360px，四个胶囊 + 三个菜单在那个宽度放不下；宁可少几个胶囊，也不能把
   「导出」挤出窗口 —— 完整样式列表永远在「样式 ▾」里。收起只影响**可见性**，
   不影响高亮：``_is_active`` 按 ``glw._style_name`` 认当前样式，**认不出就一个都不高亮**，
   绝不会把前排的某个胶囊错认成选中态（那样屏幕上就在骗人）。
3. 幂等、全程 try/except：重复调用直接返回同一个 bar；失败返回 ``None``，
   原卡片原样保留（最多是「没压扁」，不会开不了机）。

集成注意点
----------
* 调用时机：画布面板与样式条建好之后（studio 的 ``_setup_canvas_bar``）。
  ``bar = install_compact_canvas_bar(win)`` 成功后 ``win._studio_canvas_bar``
  会被赋值（另有 ``win._studio_style_btn`` 与 ``win._studio_canvas_bar_refresh``）。
* 语言切换：菜单项在 ``aboutToShow`` 时按原控件文字实时刷新；工具条上四个
  菜单按钮的文字由 ``win._studio_canvas_bar_refresh()``（或
  ``bar.update_texts()``）刷新。install 时已把 ``cub.set_lang`` 包了一层
  （主窗口切语言会走它），所以一般情况下**无需额外接线**即可中英同步。
* 尺寸：工具条固定 42px 高；原有「换行卡片高度锁定」
  （``cub._sync_style_card_height``）仍会作用于**已隐藏**的原卡片，无副作用。

只依赖 PyQt5 与 ``molstudio.core.i18n``；不 import 画布/主窗口，避免循环依赖。
"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractButton,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QWidget,
    QWidgetAction,
)

import molstudio.core.i18n as i18n

__all__ = ["install_compact_canvas_bar", "refresh_compact_canvas_bar"]

# ── 尺寸常量（DSH 设计规范：控件 28/32，圆角 8/12，hover 只加浅底、不画蓝）──
BAR_HEIGHT = 42          # ≤44px 的硬指标
BAR_MARGINS = (12, 4, 12, 4)
BAR_SPACING = 4

#: 9 个一键样式按钮在 CubCanvasPanel 上的属性名（顺序 = 菜单顺序）
_STYLE_ATTRS = (
    "_style_sob_btn",
    "_style_ibo_btn",
    "_style_hm_btn",
    "_style_hm3d_btn",
    "_style_hm2d_btn",
    "_style_iq_btn",
    "_style_ms_btn",
    "_style_cv_btn",
    "_style_vesta_btn",
)
#: 「显示」菜单里的 QCheckBox 属性名（顺序 = 菜单顺序）
_CHECK_ATTRS = ("_hide_h_chk", "_lbl_idx_chk", "_lbl_sym_chk", "_transparent_chk")

#: 常显在工具条最左侧的「常用样式」胶囊（按属性名认领，顺序 = 显示顺序）。
#: 选这四条的依据：sob-art 是默认出图风格、HoukMol3d 是 PPT 3D 用、
#: 2D 平涂是期刊插图、IQmol 是快速看结构。其余五条仍在「样式 ▾」里。
_QUICK_STYLE_ATTRS = ("_style_sob_btn", "_style_hm3d_btn",
                      "_style_hm2d_btn", "_style_iq_btn")

#: 原卡片里没有实例属性的局部按钮，用文字认领（中英都要认，语言可切换）
_SNAPSHOT_WORDS = ("截图", "Snapshot", "Snap")
_EXPORT_WORDS = ("导出图片", "Export Image", "Export image")

# ══════════════════════════════════════════════════════════════════════════ #
#  样式表：只作用在新条/菜单上，全部使用 DSH 浅色 token（无蓝底、无粗描边）
# ══════════════════════════════════════════════════════════════════════════ #
_BAR_QSS = """
QFrame#CanvasBar {
    background: #FFFFFF;
    border: none;
    border-top: 1px solid #E6E6E6;
}
QFrame#CanvasBar QLabel {
    color: #6B7280;
    font-size: 9pt;
    padding: 0px 2px;
    background: transparent;
}
QFrame#CanvasBar QToolButton#CanvasBarBtn {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 0px 7px;
    min-height: 26px;
    max-height: 28px;
    color: #1F2937;
    font-size: 9pt;
    font-weight: 500;
}
QFrame#CanvasBar QToolButton#CanvasBarBtn:hover {
    background: #F2F3F4;
}
QFrame#CanvasBar QToolButton#CanvasBarBtn:pressed,
QFrame#CanvasBar QToolButton#CanvasBarBtn:checked {
    background: #EBEEF2;
}
QFrame#CanvasBar QToolButton#CanvasBarBtn::menu-indicator {
    image: none;
    width: 0px;
    height: 0px;
}
/* 常用样式胶囊：一键样式仍然只点一次。选中态用浅蓝底 + 蓝描边，
   不用实心蓝（经典蓝主题里实心蓝是"主按钮"，这里是状态不是动作）。 */
QFrame#CanvasBar QToolButton#CanvasChip {
    background: #FFFFFF;
    border: 1px solid #E3E5E8;
    border-radius: 7px;
    padding: 0px 6px;
    min-height: 24px;
    max-height: 26px;
    color: #4B5563;
    font-size: 9pt;
}
QFrame#CanvasBar QToolButton#CanvasChip:hover {
    background: #F2F3F4;
    border-color: #D3D6DA;
}
QFrame#CanvasBar QToolButton#CanvasChip[active="true"] {
    background: #EAF2FC;
    border-color: #8FB6E0;
    color: #1F4E79;
}
QFrame#CanvasBar QComboBox {
    background: #FFFFFF;
    border: 1px solid #E6E6E6;
    border-radius: 8px;
    padding: 0px 6px;
    min-width: 120px;
    min-height: 22px;
    max-height: 28px;
    color: #1F2937;
    font-size: 9pt;
}
QFrame#CanvasBar QComboBox:hover {
    background: #F2F3F4;
}
QFrame#CanvasBar QComboBox:focus {
    border: 1px solid #1F2937;
}
QFrame#CanvasBar QLineEdit {
    background: #FFFFFF;
    border: 1px solid #E6E6E6;
    border-radius: 8px;
    padding: 0px 6px;
    min-height: 22px;
    max-height: 28px;
    color: #1F2937;
    font-size: 9pt;
}
QFrame#CanvasBar QLineEdit:focus {
    border: 1px solid #1F2937;
}
"""

_MENU_QSS = """
QMenu#CanvasBarMenu {
    background: #FFFFFF;
    border: 1px solid #E6E6E6;
    border-radius: 12px;
    padding: 4px;
    color: #1F2937;
}
QMenu#CanvasBarMenu::item {
    min-height: 24px;
    padding: 4px 12px 4px 26px;
    border-radius: 8px;
    font-size: 9pt;
}
QMenu#CanvasBarMenu::item:selected {
    background: #F2F3F4;
    color: #1F2937;
}
QMenu#CanvasBarMenu::item:disabled {
    color: #9CA3AF;
}
QMenu#CanvasBarMenu::separator {
    height: 1px;
    background: #F0F1F3;
    margin: 4px 8px;
}
"""

#: QWidgetAction 里的「标签 + 输入框」行（菜单中的原控件，样式跟着菜单走）
_MENU_ROW_QSS = """
QWidget#CanvasBarMenuRow {
    background: transparent;
}
QWidget#CanvasBarMenuRow QLabel {
    color: #6B7280;
    font-size: 9pt;
    background: transparent;
}
QWidget#CanvasBarMenuRow QLineEdit {
    background: #FFFFFF;
    border: 1px solid #E6E6E6;
    border-radius: 8px;
    padding: 0px 6px;
    min-height: 22px;
    max-height: 26px;
    color: #1F2937;
    font-size: 9pt;
}
"""


# ══════════════════════════════════════════════════════════════════════════ #
#  小工具
# ══════════════════════════════════════════════════════════════════════════ #
def _tr(zh: str, en: str) -> str:
    """当前语言下的文字（本模块只有 4 个菜单按钮需要，其余全跟随原控件）。"""
    try:
        return en if getattr(i18n, "_CURRENT_LANG", "zh") != "zh" else zh
    except Exception:
        return zh


def _attr(obj, name, default=None):
    """安全取属性（控件可能已被 Qt 销毁）。"""
    try:
        return getattr(obj, name, default)
    except RuntimeError:
        return default


def _norm_name(name) -> str:
    """样式名归一化：``HoukMol3d`` / ``houkmol-3d`` / ``HOUKMOL 3D`` 视为同一个。"""
    return "".join(ch for ch in str(name or "").lower() if ch.isalnum())


def _text(widget) -> str:
    try:
        return (widget.text() or "").strip()
    except Exception:
        return ""


def _widget_texts(widget) -> tuple:
    """(显示文字, 提示文字)，用于菜单项跟随原控件刷新。"""
    text = _text(widget)
    try:
        tip = widget.toolTip() or ""
    except Exception:
        tip = ""
    return text, tip


def _layout_containing(layout, widget):
    """在（可能嵌套的）布局树里找直接容纳 widget 的那个 QLayout。"""
    if layout is None:
        return None
    try:
        n = layout.count()
    except Exception:
        return None
    for i in range(n):
        try:
            item = layout.itemAt(i)
        except Exception:
            continue
        if item is None:
            continue
        if item.widget() is widget:
            return layout
        sub = item.layout()
        if sub is not None:
            found = _layout_containing(sub, widget)
            if found is not None:
                return found
    return None


def _detach_widget(root: QWidget, widget) -> bool:
    """把 widget 从 root 的布局树里摘下来（不删除、不改业务连接）。

    注意：不能用 ``QLayout.removeWidget()`` —— 它对 FlowLayout 这种
    「takeAt 弹出 + addItem 追加」的布局会打乱剩余项的顺序；这里自己按
    takeAt 精确摘除。
    """
    if root is None or widget is None:
        return False
    lay = _layout_containing(root.layout() if hasattr(root, "layout") else None, widget)
    if lay is None:
        return False
    try:
        for i in range(lay.count()):
            item = lay.itemAt(i)
            if item is not None and item.widget() is widget:
                lay.takeAt(i)
                return True
    except Exception:
        pass
    return False


def _wrapper_box(widget, root):
    """找到 widget 的「最小整组」外壳（父控件是 root 的那一层，如 _hgroup 的盒）。"""
    if widget is None or root is None:
        return None
    node = widget
    for _ in range(12):
        try:
            parent = node.parentWidget()
        except RuntimeError:
            return None
        if parent is root:
            return node
        if parent is None:
            return None
        node = parent
    return None


def _set_checked_blocked(widget, on: bool) -> None:
    """改 checked 但不触发自己的信号（防双向同步回环）。"""
    if widget is None:
        return
    try:
        if bool(widget.isChecked()) == bool(on):
            return
        widget.blockSignals(True)
        try:
            widget.setChecked(bool(on))
        finally:
            widget.blockSignals(False)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════ #
#  紧凑工具条本体
# ══════════════════════════════════════════════════════════════════════════ #
class _CanvasBar(QFrame):
    """单行紧凑工具条。内部所有交互都转发给原卡片里的控件实例。"""

    def __init__(self, win=None, cub=None, card=None, src_bar=None):
        super().__init__(None)
        self.setObjectName("CanvasBar")
        self.setFixedHeight(BAR_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet(_BAR_QSS)

        self._win = win
        self._cub = cub
        self._card = card
        self._src_bar = src_bar

        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(*BAR_MARGINS)
        self._lay.setSpacing(BAR_SPACING)

        # 控件引用 / 菜单项登记表（update_texts 与 aboutToShow 用）
        self._labels = []          # [(按钮, 中文, 英文)]
        self._sections = []        # [(QAction, 中文, 英文)] 菜单分组标题
        self._refreshers = []      # [callable] 菜单打开/切语言时刷新
        self._plain_acts = []      # [(QAction, 原控件, 中文?, 英文?)]
        self._style_acts = []      # [(QAction, 原样式按钮)]
        self._display_acts = []    # [(QAction, QCheckBox)]
        self._fmt_acts = []        # [(QAction, 索引)] 导出格式
        self._kind_acts = []       # [(QAction, 索引)] 测量类型
        self._measure_act = None
        self._active_style = None      # 最后点过的那条（读不到样式名时兜底）
        self._keep_moved = False
        self._clear_moved = False
        self._look_pending = None      # 待搬进「更多 ▾」的观感小盒
        self._chips = []               # [(胶囊按钮, 原样式按钮)]
        self._chip_fitting = False     # 收起/展开胶囊时防递归
        self._row_labels = []          # [(QLabel, 中文, 英文)] 菜单里的行标签
        # 从原卡片「搬走」的控件盒（安装失败时原样还回去）
        self._moved_boxes = []

        self._style_btn = None
        self._display_btn = None
        self._export_btn = None
        self._more_btn = None            # 已并入「导出 ▾」，保留字段免旧调用报错
        self._export_menu = None
        self._dpi_box = None
        self._look_box = None
        self._export_combo = None
        self._kind_combo = None
        self._measure_src = None

    # ── 构建 ────────────────────────────────────────────────────────────
    def build(self, parts: dict) -> bool:
        """按收集到的原控件建菜单；任何一步失败都只跳过那一步。"""
        self._export_combo = parts.get("export_cb")
        self._kind_combo = parts.get("measure_kind_cb")
        self._measure_src = parts.get("measure_btn")

        try:
            self._build_style_menu(parts)
        except Exception:
            pass
        try:
            self._build_quick_chips(parts)
        except Exception:
            pass
        try:
            self._build_display_menu(parts)
        except Exception:
            pass
        try:
            self._build_look_box(parts)
        except Exception:
            pass
        try:
            self._build_export_menu(parts)
        except Exception:
            pass
        try:
            self._build_more_menu(parts)
        except Exception:
            pass
        try:
            self._lay.addStretch(1)
        except Exception:
            pass

        # 至少有一个可用的入口才算安装成功，否则隐藏原卡片会丢功能
        if not any((self._style_btn, self._display_btn, self._export_btn)):
            return False
        # 更严的「一项不丢」校验：原卡片里有的控件，必须都搬进了新入口；
        # 任何一类没搬成功就整体放弃（返回 False → install 不隐藏原卡片）。
        checks = (
            (bool(parts.get("style_btns")), self._style_btn is not None),
            (bool(parts.get("checkboxes")), self._display_btn is not None),
            (parts.get("keep_box") is not None, self._keep_moved),
            (parts.get("look_box") is not None, self._look_box is not None),
            (parts.get("dpi_box") is not None, self._dpi_box is not None),
            (parts.get("clear_btn") is not None,
             self._clear_moved or self._export_btn is not None),
            (any((parts.get("snapshot_btn"), parts.get("export_btn"),
                  parts.get("export_cb"), parts.get("measure_kind_cb"),
                  parts.get("measure_btn"), parts.get("measure_clear_btn"),
                  parts.get("sync_btn"))),
             self._export_btn is not None),
        )
        for expected, got in checks:
            if expected and not got:
                return False
        self.update_texts()
        return True

    # ── 样式 ▾ ─────────────────────────────────────────────────────────
    def _build_style_menu(self, parts) -> None:
        style_btns = parts.get("style_btns") or []
        if not style_btns:
            return
        btn, menu = self._new_menu_btn("样式", "Style")

        for src in style_btns:
            text, tip = _widget_texts(src)
            act = menu.addAction(text or "—")
            act.setCheckable(True)
            act.setToolTip(tip)
            act.triggered.connect(
                lambda _checked=False, b=src: self._apply_style(b))
            self._style_acts.append((act, src))

        # 「清空样式」并进样式菜单底部：它只对样式有意义，单独挂在 VESTA
        # 后面既容易被误点，也让工具条多出一个孤立按钮。
        clear_btn = parts.get("clear_btn")
        if clear_btn is not None:
            try:
                menu.addSeparator()
                self._add_plain_action(menu, clear_btn)
                self._clear_moved = True
            except Exception:
                self._clear_moved = False

        self._style_btn = btn
        self._refreshers.append(self._refresh_style_menu)
        menu.aboutToShow.connect(self._refresh_style_menu)
        self._lay.addWidget(btn)

    # ── 常用样式胶囊（常显，一键仍然一键）──────────────────────────────
    def _build_quick_chips(self, parts) -> None:
        """把四条最常用的样式做成常显胶囊，插在工具条最左侧。

        样式菜单是二级入口（点两下），而「一键样式」的本意就是点一下就换；
        所以常用的四条必须留在第一层。全部九条仍可在「样式 ▾」里找到。
        """
        style_btns = parts.get("style_btns") or []
        if not style_btns:
            return
        wanted = []
        for name in _QUICK_STYLE_ATTRS:
            src = _attr(self._cub, name)
            if src is not None and src in style_btns:
                wanted.append(src)
        if not wanted:
            # 属性名对不上（老版本/桩件）：按原卡片视觉顺序取前四条
            wanted = list(style_btns)[:len(_QUICK_STYLE_ATTRS)]

        for src in wanted:
            text, tip = _widget_texts(src)
            chip = QToolButton(self)
            chip.setObjectName("CanvasChip")
            chip.setText(text or "—")
            chip.setToolTip(tip or text or "")
            chip.setCursor(Qt.PointingHandCursor)
            chip.setToolButtonStyle(Qt.ToolButtonTextOnly)
            chip.setFocusPolicy(Qt.NoFocus)
            chip.clicked.connect(
                lambda _checked=False, b=src: self._apply_style(b))
            self._chips.append((chip, src))
            self._lay.insertWidget(len(self._chips) - 1, chip)
        self._sync_chips()

    def _sync_chips(self) -> None:
        """胶囊的选中态 / 文字跟随原样式按钮（切语言、菜单里选样式都要同步）。"""
        for chip, src in self._chips:
            try:
                on = self._is_active(src)
            except RuntimeError:
                continue
            except Exception:
                on = False
            try:
                cur = chip.property("active")
                if cur is None or bool(cur) != on:
                    chip.setProperty("active", on)
                    chip.style().unpolish(chip)
                    chip.style().polish(chip)
            except Exception:
                pass
            try:
                text, tip = _widget_texts(src)
                if text and chip.text() != text:
                    chip.setText(text)
                chip.setToolTip(tip or chip.text())
            except Exception:
                pass

    def _canvas_style_name(self) -> str:
        """画布当前样式名，归一化（``HoukMol3d`` / ``houkmol-3d`` 视作同一个）。"""
        try:
            raw = str(getattr(getattr(self._cub, "glw", None),
                              "_style_name", "") or "")
        except Exception:
            raw = ""
        return _norm_name(raw)

    def _is_active(self, src) -> bool:
        """``src`` 是不是画布当前样式。

        样式按钮本身不可勾选（``_panel.py`` 里只是 ``clicked`` 连到应用函数），
        所以只能反查画布的 ``glw._style_name`` 按名字认。**认不出来就都不算
        选中**，绝不退回去点亮第一个 —— 开箱样式是 ``ultra-glass``（不在四条
        常用胶囊里），退回去点亮 ``sob-art`` 会让屏幕上那个高亮说谎。
        """
        name = self._canvas_style_name()
        if name:
            try:
                return _norm_name(_text(src)) == name
            except Exception:
                return False
        return src is self._active_style

    def _guess_active_style(self):
        """按名字在九个样式按钮里找当前那一个；认不出返回 ``None``。"""
        name = self._canvas_style_name()
        if not name:
            return None
        for _act, src in self._style_acts:
            try:
                if _norm_name(_text(src)) == name:
                    return src
            except Exception:
                continue
        return None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_chips()

    def _fit_chips(self) -> None:
        """宽度不够时胶囊从右往左按顺序收起（保留前缀，收掉尾部）。

        画布最窄能到 360px（``cub_canvas.setMinimumWidth``），四个胶囊 + 三个
        菜单按钮在那个宽度放不下。**能放几条放几条**：菜单按钮永远优先保住
        （「导出」不能被挤出窗口），剩下的宽度按顺序塞胶囊，塞不下的收掉。
        完整列表永远在「样式 ▾」里，菜单项带勾。

        只收可见性、不动高亮：被收掉的那条如果正是当前样式，屏幕上是「一条
        都没高亮」，而不是错亮在别的胶囊上（见 ``_is_active``）。
        """
        if not self._chips or self._chip_fitting:
            return
        self._chip_fitting = True
        try:
            avail = self.width() - BAR_MARGINS[0] - BAR_MARGINS[2]
            menus = [b for b in (self._style_btn, self._display_btn,
                                self._export_btn, self._more_btn) if b is not None]
            need = sum(b.sizeHint().width() + BAR_SPACING for b in menus)
            for chip, _src in self._chips:
                try:
                    w = chip.sizeHint().width() + BAR_SPACING
                    show = (need + w) <= avail
                    chip.setVisible(show)
                    if show:
                        need += w
                except RuntimeError:
                    continue
        finally:
            self._chip_fitting = False

    def _apply_style(self, src) -> None:
        """「样式」菜单项：点原按钮（业务逻辑全在原按钮里）。"""
        try:
            src.click()
        except Exception:
            return
        self._active_style = src
        for act, other in self._style_acts:
            try:
                act.setChecked(other is src)
            except Exception:
                pass
        self._sync_chips()

    def _refresh_style_menu(self) -> None:
        for act, src in self._style_acts:
            try:
                text, tip = _widget_texts(src)
                act.setText(text or "—")
                act.setToolTip(tip)
                if src.isCheckable():
                    on = bool(src.isChecked())
                else:
                    on = self._is_active(src)
                act.blockSignals(True)
                try:
                    act.setChecked(on)
                finally:
                    act.blockSignals(False)
            except Exception:
                continue
        self._sync_chips()

    # ── 显示 ▾ ─────────────────────────────────────────────────────────
    def _build_display_menu(self, parts) -> None:
        chks = list(parts.get("checkboxes") or [])
        keep_box = parts.get("keep_box")
        if not chks and keep_box is None:
            return
        btn, menu = self._new_menu_btn("显示", "Display")

        for chk in chks:
            text, tip = _widget_texts(chk)
            act = menu.addAction(text)
            act.setCheckable(True)
            act.setToolTip(tip)
            act.setChecked(bool(chk.isChecked()))
            self._display_acts.append((act, chk))

            def _act_toggled(on, c=chk):
                _set_checked_blocked(c, on)

            def _chk_toggled(on, a=act):
                _set_checked_blocked(a, on)

            act.toggled.connect(_act_toggled)
            try:
                chk.toggled.connect(_chk_toggled)
            except Exception:
                pass

        if keep_box is not None:
            try:
                menu.addSeparator()
                self._keep_moved = bool(self._add_widget_row(
                    menu, keep_box, parts.get("src_bar"), "保留 H 编号",
                    "Keep H labels"))
            except Exception:
                self._keep_moved = False

        self._display_btn = btn
        self._refreshers.append(self._refresh_display_menu)
        menu.aboutToShow.connect(self._refresh_display_menu)
        self._lay.addWidget(btn)

    def _refresh_display_menu(self) -> None:
        for act, chk in self._display_acts:
            try:
                text, tip = _widget_texts(chk)
                act.setText(text)
                act.setToolTip(tip)
                act.blockSignals(True)
                try:
                    act.setChecked(bool(chk.isChecked()))
                finally:
                    act.blockSignals(False)
            except Exception:
                continue

    # ── 出图观感（搬进「更多 ▾」，与 DPI 同一组）────────────────────────
    def _build_look_box(self, parts) -> None:
        """只登记「出图观感」下拉，真正加进布局是在「更多 ▾」里。

        这个下拉实测 159px 宽，和四个样式胶囊 + 三个菜单按钮挤在一行要
        632px，超过 520px 的画布宽度，右边的「更多」会被挤出窗口。观感本来
        只影响出图，放进「导出设置」组更合理 —— 控件实例仍是原来那一个。
        """
        box = parts.get("look_box")
        if box is None:
            return
        self._look_pending = (box, parts.get("src_bar"))

    # ── 导出 ▾ ─────────────────────────────────────────────────────────
    def _build_export_menu(self, parts) -> None:
        snap_btn = parts.get("snapshot_btn")
        export_btn = parts.get("export_btn")
        export_cb = parts.get("export_cb")
        kind_cb = parts.get("measure_kind_cb")
        measure_btn = parts.get("measure_btn")
        measure_clear = parts.get("measure_clear_btn")
        sync_btn = parts.get("sync_btn")
        if not any((snap_btn, export_btn, export_cb, kind_cb,
                    measure_btn, measure_clear, sync_btn)):
            return
        btn, menu = self._new_menu_btn("导出", "Export")
        self._export_btn = btn

        # 截图 / 导出图片 —— 原按钮.click()（会走原保存对话框）。
        # 这两个按钮在 _panel.py 里是局部变量，文字没进 i18n 注册表，所以
        # 菜单项用自己的中英对照（其余项一律跟随原控件文字）。
        if snap_btn is not None:
            self._add_plain_action(menu, snap_btn, _tr("截图", "Snapshot"),
                                   "截图", "Snapshot")

        if export_cb is not None:
            try:
                menu.addSeparator()
                self._add_section(menu, "导出格式", "Format")
                for i in range(export_cb.count()):
                    act = menu.addAction(export_cb.itemText(i))
                    act.setCheckable(True)
                    self._fmt_acts.append((act, i))
                    act.triggered.connect(
                        lambda _c=False, cb=export_cb, idx=i: self._choose_combo(cb, idx))
            except Exception:
                pass

        if export_btn is not None:
            self._add_plain_action(menu, export_btn, _tr("导出图片", "Export Image"),
                                   "导出图片", "Export Image")

        # 测量：类型（距离/键角/二面角）+ 开关 + 清除
        if kind_cb is not None or measure_btn is not None or measure_clear is not None:
            try:
                menu.addSeparator()
                self._add_section(menu, "测量", "Measure")
            except Exception:
                pass
        if kind_cb is not None:
            try:
                for i in range(kind_cb.count()):
                    act = menu.addAction(kind_cb.itemText(i))
                    act.setCheckable(True)
                    self._kind_acts.append((act, i))
                    act.triggered.connect(
                        lambda _c=False, cb=kind_cb, idx=i: self._choose_combo(cb, idx))
            except Exception:
                pass
        if measure_btn is not None:
            try:
                act = menu.addAction(_text(measure_btn) or _tr("测量", "Measure"))
                act.setCheckable(True)
                act.setChecked(bool(measure_btn.isChecked()))
                self._measure_act = act

                def _act_toggled(on, b=measure_btn):
                    _set_checked_blocked(b, on)

                def _btn_toggled(on, a=act):
                    _set_checked_blocked(a, on)

                act.toggled.connect(_act_toggled)
                measure_btn.toggled.connect(_btn_toggled)
            except Exception:
                pass
        if measure_clear is not None:
            self._add_plain_action(menu, measure_clear)

        if sync_btn is not None:
            try:
                menu.addSeparator()
                self._add_plain_action(menu, sync_btn)
            except Exception:
                pass

        self._export_menu = menu
        self._refreshers.append(self._refresh_export_menu)
        menu.aboutToShow.connect(self._refresh_export_menu)
        self._lay.addWidget(btn)

    def _refresh_export_menu(self) -> None:
        for act, i in self._fmt_acts:
            try:
                cb = self._export_combo
                if cb is None:
                    continue
                act.setText(cb.itemText(i))
                act.blockSignals(True)
                try:
                    act.setChecked(cb.currentIndex() == i)
                finally:
                    act.blockSignals(False)
            except Exception:
                continue
        for act, i in self._kind_acts:
            try:
                cb = self._kind_combo
                if cb is None:
                    continue
                act.setText(cb.itemText(i))
                act.blockSignals(True)
                try:
                    act.setChecked(cb.currentIndex() == i)
                finally:
                    act.blockSignals(False)
            except Exception:
                continue
        act, src = self._measure_act, self._measure_src
        if act is not None and src is not None:
            try:
                act.setText(_text(src) or _tr("测量", "Measure"))
                act.blockSignals(True)
                try:
                    act.setChecked(bool(src.isChecked()))
                finally:
                    act.blockSignals(False)
            except Exception:
                pass

    @staticmethod
    def _choose_combo(combo, index: int) -> None:
        try:
            combo.setCurrentIndex(index)
        except Exception:
            pass

    def _refresh_plain_acts(self) -> None:
        """菜单项文字/提示跟随原控件（截图/导出图片用自带中英对照）。"""
        for entry in self._plain_acts:
            try:
                act, src = entry[0], entry[1]
                zh = entry[2] if len(entry) > 2 else None
                en = entry[3] if len(entry) > 3 else None
                text = _tr(zh, en) if zh else (_text(src) or act.text())
                act.setText(text)
                act.setToolTip(src.toolTip() or "")
            except Exception:
                continue

    # ── 导出设置 + 兜底 → 并进「导出 ▾」，不再单独占一个按钮 ──────────────
    def _build_more_menu(self, parts) -> None:
        """把「导出设置」（出图观感 + DPI）与兜底按钮追加到「导出 ▾」菜单末尾。

        这几项原本单独占一个「更多 ▾」按钮，实测四个菜单按钮 316px、四个样式
        胶囊 361px，而 1920 宽屏的画布列只有 654px —— 多这一个按钮，胶囊就
        全部被挤掉（677 > 630）。而观感和 DPI 本来就只影响出图，并进导出更顺。
        """
        extra_btns = list(parts.get("extra_btns") or [])
        dpi_box = parts.get("dpi_box")
        look = self._look_pending
        menu = getattr(self, "_export_menu", None)
        if menu is None or (not extra_btns and dpi_box is None and look is None):
            return
        try:
            menu.addSeparator()
        except Exception:
            pass

        # 「出图观感」与 DPI 都是原控件的 QWidgetAction —— 实例、校验器、信号一行没动。
        if look is not None or dpi_box is not None:
            try:
                self._add_section(menu, "导出设置", "Export settings")
            except Exception:
                pass
        if look is not None:
            box, src_bar = look
            try:
                moved = bool(self._add_widget_row(menu, box, src_bar, "出图观感",
                                                 "Look"))
                self._look_box = box if moved else None
            except Exception:
                self._look_box = None
        if dpi_box is not None:
            try:
                moved = bool(self._add_widget_row(menu, dpi_box,
                                                 parts.get("src_bar"), "DPI",
                                                 "DPI"))
                self._dpi_box = dpi_box if moved else None
            except Exception:
                self._dpi_box = None

        if extra_btns:
            try:
                if not menu.isEmpty():
                    menu.addSeparator()
            except Exception:
                pass

        for src in extra_btns:
            try:
                self._add_plain_action(menu, src)
            except Exception:
                continue

        self._refreshers.append(self._refresh_plain_acts)
        menu.aboutToShow.connect(self._refresh_plain_acts)

    # ── 通用小件 ───────────────────────────────────────────────────────
    def _new_menu_btn(self, zh: str, en: str):
        """带 InstantPopup 菜单的 QToolButton（单点即展开）。"""
        btn = QToolButton(self)
        btn.setObjectName("CanvasBarBtn")
        btn.setText(_tr(zh, en) + " ▾")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setPopupMode(QToolButton.InstantPopup)
        btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        menu = QMenu(btn)
        menu.setObjectName("CanvasBarMenu")
        menu.setStyleSheet(_MENU_QSS)
        btn.setMenu(menu)
        self._labels.append((btn, zh, en))
        return btn, menu

    def _add_widget_row(self, menu, box, src_bar, zh=None, en=None) -> bool:
        """把原控件的「标签+输入框」小盒整体搬进菜单（QWidgetAction，原实例不变）。"""
        host = QWidget()
        host.setObjectName("CanvasBarMenuRow")
        host.setStyleSheet(_MENU_ROW_QSS)
        row = QHBoxLayout(host)
        row.setContentsMargins(8, 2, 8, 4)
        row.setSpacing(6)
        # 原卡片里这几组是「标签 + 裸输入框」：标签可能在小盒内部（保留 H 编号、
        # 出图观感、DPI 都是这样），也可能整组没有标签。只在**确实没有**时补一
        # 个字，否则会出现「保留 H 编号 保留H编号:」两遍。
        if zh:
            has_label = False
            try:
                has_label = any((lab.text() or "").strip()
                                for lab in box.findChildren(QLabel))
            except Exception:
                has_label = False
            if not has_label:
                lab = QLabel(_tr(zh, en))
                lab.setObjectName("CanvasBarRowLabel")
                row.addWidget(lab)
                self._row_labels.append((lab, zh, en))
        _detach_widget(src_bar, box)
        row.addWidget(box)
        box.show()
        action = QWidgetAction(menu)
        action.setDefaultWidget(host)
        menu.addAction(action)
        moved = host.isAncestorOf(box)
        if moved:
            self._moved_boxes.append(box)
        return moved

    def _add_section(self, menu, zh: str, en: str):
        """菜单分组标题（切语言时跟着刷新）。"""
        act = menu.addSection(_tr(zh, en))
        self._sections.append((act, zh, en))
        return act

    def _add_plain_action(self, menu, src, text=None, zh=None, en=None):
        """加一个「点原控件」的菜单项；text 为 None 时跟随原控件文字刷新。"""
        act = menu.addAction(text or _text(src) or "—")
        try:
            act.setToolTip(src.toolTip() or "")
        except Exception:
            pass
        act.triggered.connect(lambda _c=False, b=src: b.click())
        self._plain_acts.append((act, src, zh, en))
        return act

    # ── 文本刷新 ───────────────────────────────────────────────────────
    def update_texts(self) -> None:
        """刷新工具条按钮文字 + 所有菜单项（切语言后调一次即可）。"""
        for btn, zh, en in self._labels:
            try:
                btn.setText(_tr(zh, en) + " ▾")
            except RuntimeError:
                continue
        for act, zh, en in self._sections:
            try:
                act.setText(_tr(zh, en))
            except RuntimeError:
                continue
        for lab, zh, en in self._row_labels:
            try:
                lab.setText(_tr(zh, en))
            except RuntimeError:
                continue
        for fn in self._refreshers:
            try:
                fn()
            except Exception:
                pass
        try:
            self._refresh_plain_acts()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════ #
#  从原卡片收集控件
# ══════════════════════════════════════════════════════════════════════════ #
def _ordered_widgets(src_bar):
    """原卡片里控件的视觉顺序（FlowLayout 行序，含小盒里的控件）。"""

    def _collect_from_layout(lay, out):
        try:
            n = lay.count()
        except Exception:
            return
        for i in range(n):
            try:
                item = lay.itemAt(i)
            except Exception:
                continue
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                out.append(w)
                _collect_from_layout(w.layout(), out) if w.layout() is not None else None
            else:
                sub = item.layout()
                if sub is not None:
                    _collect_from_layout(sub, out)

    out = []
    _collect_from_layout(src_bar.layout(), out)
    return out


def _collect_style_buttons(cub, src_bar):
    out = []
    for name in _STYLE_ATTRS:
        btn = _attr(cub, name)
        if isinstance(btn, QAbstractButton):
            try:
                if src_bar.isAncestorOf(btn):
                    out.append(btn)
                    continue
            except Exception:
                continue
    if out:
        return out
    # 兜底（属性名变动/桩件）：按布局顺序取前 9 个 QPushButton
    return [w for w in _ordered_widgets(src_bar) if isinstance(w, QPushButton)][:9]


def _collect_checkboxes(cub, src_bar):
    out = []
    for name in _CHECK_ATTRS:
        chk = _attr(cub, name)
        if isinstance(chk, QCheckBox):
            try:
                if src_bar.isAncestorOf(chk):
                    out.append(chk)
                    continue
            except Exception:
                continue
    # 兜底：原卡片里还有别的 checkbox 也一并收进来，保证一项不丢
    try:
        for chk in src_bar.findChildren(QCheckBox):
            if chk not in out:
                out.append(chk)
    except Exception:
        pass
    return out


def _pick_button(candidates, words):
    """在原按钮里找文字匹配的按钮：先全等、后包含（中英都认）。"""
    for want in words:
        for btn in candidates:
            if _text(btn).lower() == want.lower():
                return btn
    for want in words:
        for btn in candidates:
            if want.lower() in _text(btn).lower():
                return btn
    return None


def _collect_parts(cub, src_bar) -> dict:
    """把原卡片里的控件按用途分类（找不到的槽位为 None，不报错）。"""
    parts = {"src_bar": src_bar}
    parts["style_btns"] = _collect_style_buttons(cub, src_bar)
    parts["checkboxes"] = _collect_checkboxes(cub, src_bar)

    look_cb = _attr(cub, "_look_cb")
    if not isinstance(look_cb, QComboBox):
        look_cb = None
    parts["look_cb"] = look_cb
    parts["look_box"] = _wrapper_box(look_cb, src_bar) if look_cb is not None else None

    dpi_edit = _attr(cub, "_dpi_edit")
    if not isinstance(dpi_edit, QLineEdit):
        dpi_edit = None
    parts["dpi_edit"] = dpi_edit
    parts["dpi_box"] = _wrapper_box(dpi_edit, src_bar) if dpi_edit is not None else None

    keep_edit = _attr(cub, "_keep_h_edit")
    if not isinstance(keep_edit, QLineEdit):
        keep_edit = None
    parts["keep_box"] = _wrapper_box(keep_edit, src_bar) if keep_edit is not None else None

    export_cb = _attr(cub, "_export_cb")
    if not isinstance(export_cb, QComboBox):
        export_cb = None
    parts["export_cb"] = export_cb
    kind_cb = _attr(cub, "_measure_kind_cb")
    if not isinstance(kind_cb, QComboBox):
        kind_cb = None
    parts["measure_kind_cb"] = kind_cb

    parts["sync_btn"] = _attr(cub, "_sync_vmd_btn")
    parts["measure_btn"] = _attr(cub, "_measure_btn")
    parts["measure_clear_btn"] = _attr(cub, "_measure_clear_btn")
    parts["clear_btn"] = _attr(cub, "_clear_analysis_btn")

    # 没有实例属性的局部按钮（截图 / 导出图片）按文字认领
    all_btns = [w for w in _ordered_widgets(src_bar) if isinstance(w, QPushButton)]
    consumed = set(parts["style_btns"])
    for key in ("sync_btn", "measure_btn", "measure_clear_btn", "clear_btn"):
        if parts[key] is not None:
            consumed.add(parts[key])
    remaining = [b for b in all_btns if b not in consumed]
    parts["snapshot_btn"] = _pick_button(remaining, _SNAPSHOT_WORDS)
    if parts["snapshot_btn"] is not None:
        remaining.remove(parts["snapshot_btn"])
    parts["export_btn"] = _pick_button(remaining, _EXPORT_WORDS)
    if parts["export_btn"] is not None:
        remaining.remove(parts["export_btn"])
    # 万一以后原卡片新增了按钮：统一兜底进「更多 ▾」，不丢功能
    parts["extra_btns"] = remaining
    return parts


def _rollback_moves(bar, src_bar) -> None:
    """安装失败时的回滚：把已搬走的原控件放回原卡片布局（可能排到末尾）。

    目标只有一个：**功能一项不丢**。原卡片本来就换行排版，顺序变化不影响使用。
    """
    try:
        for box in list(getattr(bar, "_moved_boxes", []) or []):
            try:
                parent = box.parentWidget()
                if parent is not None:
                    lay = _layout_containing(parent.layout(), box)
                    if lay is not None:
                        for i in range(lay.count()):
                            item = lay.itemAt(i)
                            if item is not None and item.widget() is box:
                                lay.takeAt(i)
                                break
                src_lay = src_bar.layout() if src_bar is not None else None
                if src_lay is not None:
                    src_lay.addWidget(box)
            except Exception:
                continue
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════ #
#  对外入口
# ══════════════════════════════════════════════════════════════════════════ #
def install_compact_canvas_bar(win):
    """把 ``win.cub_canvas`` 底部的「一键样式 + 分子显示」卡片压成 42px 单行条。

    参数
    ----
    win : QMainWindow
        需要有 ``cub_canvas`` 属性（``main_window`` / clean / studio 都有）。
        可选 ``_style_wrap`` 属性指向原卡片；缺失时用 ``CubStyleBar`` 的父控件。

    返回
    ----
    QFrame | None
        成功安装（或此前已安装）返回 ``QFrame#CanvasBar``；没有可压缩的原卡片、
        或插入失败返回 ``None``（原界面保持原样）。

    幂等：重复调用返回同一个 bar，不会插入第二个。
    """
    try:
        if win is None:
            return None
        cub = getattr(win, "cub_canvas", None)
        if cub is None:
            return None

        # ① 幂等：已经装过且还活着，直接返回
        prev = getattr(win, "_studio_canvas_bar", None)
        if prev is not None:
            try:
                if prev.parent() is not None:
                    return prev
            except RuntimeError:
                pass

        # ② 找原卡片：CubStyleBar → 其所在卡片（_style_wrap 或其父控件）
        src_bar = cub.findChild(QWidget, "CubStyleBar")
        if src_bar is None:
            return None
        card = getattr(cub, "_style_wrap", None)
        if card is None or card is src_bar:
            card = src_bar.parentWidget()
        if card is None:
            card = src_bar
        parent = card.parentWidget()
        if parent is None:
            return None
        parent_lay = parent.layout()

        # ③ 收集原控件并建条（失败不隐藏任何东西）
        parts = _collect_parts(cub, src_bar)
        if not parts["style_btns"] and not parts["checkboxes"] \
                and parts["snapshot_btn"] is None and parts["export_btn"] is None \
                and parts["sync_btn"] is None:
            return None
        new_bar = _CanvasBar(win=win, cub=cub, card=card, src_bar=src_bar)

        def _abort():
            """安装失败：把搬走的原控件放回原卡片，删掉半成品条。"""
            try:
                _rollback_moves(new_bar, src_bar)
            except Exception:
                pass
            try:
                new_bar.deleteLater()
            except Exception:
                pass
            return None

        try:
            ok = new_bar.build(parts)
        except Exception:
            ok = False
        if not ok:
            return _abort()

        # ④ 插到原卡片的原位置，再隐藏原卡片 —— 画布底部只剩这一条
        inserted = False
        if parent_lay is not None:
            try:
                index = parent_lay.indexOf(card)
                if index < 0:
                    index = parent_lay.count()
                parent_lay.insertWidget(index, new_bar)
                inserted = True
            except Exception:
                inserted = False
        if not inserted:
            # 退化：塞进卡片自己的布局，并隐藏卡片内其余控件
            try:
                card_lay = card.layout()
                if card_lay is None:
                    return _abort()
                card_lay.addWidget(new_bar)
                for i in range(card_lay.count()):
                    widget = card_lay.itemAt(i).widget()
                    if widget is not None and widget is not new_bar:
                        widget.hide()
                inserted = True
            except Exception:
                inserted = False
        if not inserted:
            return _abort()

        try:
            if card is not new_bar:
                card.hide()
        except Exception:
            pass
        try:
            src_bar.hide()
        except Exception:
            pass
        try:
            parent_lay.invalidate()
        except Exception:
            pass
        try:
            new_bar.show()
        except Exception:
            pass

        # ⑤ 给窗口留句柄（studio 皮肤/主窗口可以按需刷新/微调）
        try:
            win._studio_canvas_bar = new_bar
        except Exception:
            pass
        try:
            win._studio_style_btn = new_bar._style_btn
        except Exception:
            pass
        try:
            win._studio_canvas_bar_refresh = new_bar.update_texts
        except Exception:
            pass

        # ⑥ 语言切换：cub.set_lang 是主窗口切语言时唯一会走到画布的入口
        #    （main_window._apply_lang_ui → canvas_panel.set_lang）。包一层，
        #    保证四个菜单按钮的中英文跟着换；已经在原 set_lang 完成后执行。
        try:
            orig_set_lang = getattr(cub, "set_lang", None)
            if callable(orig_set_lang) and not getattr(cub, "_studio_bar_lang_hooked", False):
                def _set_lang_and_refresh(lang, _orig=orig_set_lang, _bar=new_bar):
                    try:
                        return _orig(lang)
                    finally:
                        try:
                            _bar.update_texts()
                        except Exception:
                            pass

                cub.set_lang = _set_lang_and_refresh
                cub._studio_bar_lang_hooked = True
        except Exception:
            pass
        return new_bar
    except Exception:
        return None


def refresh_compact_canvas_bar(win) -> bool:
    """切语言后刷新紧凑工具条文字（无条时返回 False，不影响启动）。"""
    try:
        bar = getattr(win, "_studio_canvas_bar", None)
        if bar is None:
            return False
        bar.update_texts()
        return True
    except Exception:
        return False
