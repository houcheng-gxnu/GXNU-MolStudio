# -*- coding: utf-8 -*-
"""MolStudio — 「画布优先」界面（Canvas-First，2026-09-27）

**新界面，独立文件**：不修改 main_window.py / main_window_clean.py /
main_window_clean2.py 的任何行为，只在本文件里对已有控件树做布局搬运。

启动方式（任选）::

    python main_window_canvas_first.py      # 直接启动（自带引导：GL 格式、启动画面、异常钩子）
    python main.py --ui canvas              # 走 main.py，也可用环境变量 MOLSTUDIO_UI=canvas

布局（设计稿见 ui_demos/layout_2026-09/01_canvas_first.html）：
  1. 左侧功能导航 122px 竖排文字 → **58px 图标 rail**：只显示矢量图标，悬停出全名，
     底部「☰」一键展开回「图标 + 文字」（122px）。
  2. 右侧「设置 / 引文」抽屉**可整体收起**：Tab 栏右上角「▤」或 Ctrl+B；
     收起后画布吃满整宽；画布卡片里另有一个「▤ 设置」常驻入口负责展开。
  3. 一键样式 8 个按钮 → **一个下拉菜单**（原地替换，卡片更矮更窄，且不丢任何样式）。
  4. 其余（分析面板、引文页签、皮肤、快捷键、比例记忆）全部沿用现有实现。

实现方式：继承 MolStudioCleanWindow（Clean 皮肤），只覆写
`_setup_ui / _setup_main_nav / _sync_main_nav` 三个钩子做布局后处理；
所有失败都就地 try/except 兜住 —— 布局改造失败最多是"回到底层界面"，
绝不影响功能。
"""

import os
import sys

# 以脚本方式直接运行时才需要；正常入口是 `python main.py --ui canvas`。
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))

from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (QAction, QFrame, QMenu, QShortcut, QToolButton,
                             QWidget)

from molstudio.ui.main_window_clean import (ICON_ACCENT, ICON_MUTED, NAV_ICONS,
                               MolStudioCleanWindow)
from molstudio.ui.ui_icons import make_icon


# 补两个 clean 皮肤没配到的 tab 图标（晶体、DI）：不覆盖原来的映射表，
# 只在本界面里生效。
RAIL_EXTRA_ICONS = {
    "tab_crystal": "cube",      # 晶胞
    "tab_di": "sigma",          # 能量分解（Σ）
}

# 一键样式按钮 → 下拉菜单项（顺序与设计稿一致）
ONE_CLICK_STYLES = (
    ("sob-art", "_style_sob_btn"),
    ("IBOview", "_style_ibo_btn"),
    ("HoukMol", "_style_hm_btn"),
    ("HoukMol3d", "_style_hm3d_btn"),
    ("IQmol", "_style_iq_btn"),
    ("MolStudio", "_style_ms_btn"),
    ("CYLview", "_style_cv_btn"),
    ("VESTA", "_style_vesta_btn"),
)


class MolStudioCanvasFirstWindow(MolStudioCleanWindow):
    """画布优先布局：图标 rail + 可收起抽屉 + 样式下拉。"""

    RAIL_W = 58              # 图标 rail 宽度
    RAIL_W_EXPANDED = 122    # 展开后的宽度（= 原导航条宽度）

    def __init__(self):
        # 这些状态必须在 super().__init__()（内部会调 _setup_ui）之前就位
        self._rail_built = False
        self._rail_expanded = False
        self._style_menu_built = False
        self._drawer_built = False
        self._drawer_collapsed = False
        self._drawer_sizes = None
        self._nav_card = None
        self._rail_toggle = None
        self._style_menu_btn = None
        self._drawer_btn = None
        self._oneclick_style = ""
        super().__init__()

    # ═══════════════════════════════════════════════════════════
    #  布局钩子
    # ═══════════════════════════════════════════════════════════
    def _setup_ui(self):
        super()._setup_ui()          # 经典布局 + Clean 皮肤
        self._apply_canvas_first()
        # Clean 皮肤是 QTimer.singleShot(60, ...) 延后套用的（见
        # MolStudioCleanWindow.__init__），它会把导航卡重新钉成 150px，
        # 所以皮肤套完后再补一次；下面 _apply_clean_skin 的覆写也兜了一道。
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(120, self._apply_canvas_first)

    def _apply_clean_skin(self):
        """皮肤套用后（皮肤会把导航卡钉成 150px）重新套用本界面的布局。"""
        super()._apply_clean_skin()
        self._apply_canvas_first()

    def _apply_canvas_first(self):
        """幂等：可以反复调用（皮肤/语言变化后再套一次）。"""
        for label, fn in (("图标 rail", self._build_rail),
                          ("样式下拉", self._build_style_menu),
                          ("抽屉开关", self._build_drawer_toggle)):
            try:
                fn()
            except Exception as e:   # 布局改造失败不能拖垮功能界面
                print(f"[canvas-first] {label} 应用失败: {e}")
        self._apply_rail_mode()      # 始终把 rail 宽度/文字状态压回去

    def _setup_main_nav(self):
        """父类建好条目/图标后，套用 rail 模式。"""
        super()._setup_main_nav()
        if not getattr(self, "_rail_built", False):
            try:
                self._build_rail()
            except Exception as e:
                print(f"[canvas-first] 图标 rail 应用失败: {e}")
        self._apply_rail_mode()

    def _sync_main_nav(self):
        """切语言会重刷条目文字：刷完再套回 rail 模式（图标不丢）。"""
        super()._sync_main_nav()
        self._apply_rail_mode()

    # ═══════════════════════════════════════════════════════════
    #  ① 图标 rail
    # ═══════════════════════════════════════════════════════════
    def _build_rail(self):
        nav = getattr(self, "main_nav", None)
        if nav is None or self._rail_built:
            return
        card = self.findChild(QFrame, "NavCard")
        self._nav_card = card

        # 展开/收起按钮：贴在 rail 底部
        if card is not None and card.layout() is not None:
            btn = QToolButton(card)
            btn.setText("☰")
            btn.setObjectName("SmallBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip("展开导航文字（当前只显示图标）")
            btn.setFixedHeight(26)
            btn.clicked.connect(self._toggle_rail)
            card.layout().addWidget(btn, 0, Qt.AlignHCenter)
            self._rail_toggle = btn

        nav.setSpacing(0)
        nav.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._rail_built = True
        self._apply_rail_mode()

    def _apply_rail_mode(self):
        """按 _rail_expanded 切换「纯图标 / 图标+文字」。"""
        nav = getattr(self, "main_nav", None)
        if nav is None:
            return
        expanded = bool(getattr(self, "_rail_expanded", False))
        w = self.RAIL_W_EXPANDED if expanded else self.RAIL_W

        card = self._nav_card
        if card is not None:
            # 父类把 nav_card 的 min/max 设成 96/320，这里两者都要覆盖
            card.setMinimumWidth(w)
            card.setMaximumWidth(w)

        icon = 18 if expanded else 21
        pad = max(6, int((w - icon) / 2) - 2)
        nav.setIconSize(QSize(icon, icon))
        nav.setStyleSheet(
            "QListWidget#MainNav::item { padding: 11px 0 11px %dpx; }" % pad)

        keys = getattr(self, "_tab_keys", [])
        for i, key in enumerate(keys):
            if i >= nav.count():
                break
            it = nav.item(i)
            full = self._tr(key)
            kind = NAV_ICONS.get(key) or RAIL_EXTRA_ICONS.get(key)
            if kind:
                try:
                    it.setIcon(make_icon(kind, ICON_MUTED, icon, 1.6,
                                         selected_color=ICON_ACCENT))
                except Exception:
                    pass
            if expanded:
                it.setText(full)
                it.setToolTip("")
            else:
                it.setText("")            # 纯图标
                it.setToolTip(full)       # 全名走悬停提示

        if self._rail_toggle is not None:
            self._rail_toggle.setText("⇤" if expanded else "☰")
            self._rail_toggle.setToolTip(
                "只显示图标（画布更宽）" if expanded
                else "展开导航文字（当前只显示图标）")

    def _toggle_rail(self):
        self._rail_expanded = not self._rail_expanded
        self._apply_rail_mode()
        self._cf_status("导航：" + ("图标 + 文字" if self._rail_expanded
                                    else "仅图标（悬停看名称）"))

    # ═══════════════════════════════════════════════════════════
    #  ② 一键样式下拉（替换画布下方的 8 个按钮）
    # ═══════════════════════════════════════════════════════════
    def _build_style_menu(self):
        cub = getattr(self, "cub_canvas", None)
        if cub is None or self._style_menu_built:
            return
        bar = cub.findChild(QWidget, "CubStyleBar")
        if bar is None or bar.layout() is None:
            return

        btn = QToolButton(bar)
        btn.setObjectName("SmallBtn")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setPopupMode(QToolButton.InstantPopup)
        btn.setText("🎨 选择样式 ▾")
        menu = QMenu(btn)

        pairs = []
        for name, attr in ONE_CLICK_STYLES:
            b = getattr(cub, attr, None)
            if b is None:
                continue
            pairs.append((name, b))
            b.hide()                        # 原按钮保留（功能不动），只是不再显示
            act = QAction(name, menu)
            act.triggered.connect(
                lambda _checked=False, _b=b, _n=name: self._apply_oneclick(_b, _n))
            menu.addAction(act)
        btn.setMenu(menu)
        if not pairs:
            btn.hide()
        tip = "一键样式（等价于原来画布下方那排按钮）：\n· " + "\n· ".join(
            n for n, _ in pairs)
        btn.setToolTip(tip)
        self._style_menu_btn = btn

        # 插到「一键样式:」标签后面（FlowLayout 没有 insertWidget，
        # 这里用它的内部列表手动挪位，失败就退回追加到行尾）
        lay = bar.layout()
        lay.addWidget(btn)
        try:
            items = getattr(lay, "_items", None)
            lbl = getattr(cub, "_lbl_styles", None)
            if items and lbl is not None:
                item = items.pop()
                idx = next((i for i, x in enumerate(items)
                            if getattr(x, "widget", lambda: None)() is lbl), None)
                items.insert((idx + 1) if idx is not None else len(items), item)
        except Exception:
            pass
        lay.invalidate()

        # 记住当前样式名（点按钮后按钮文字跟着变），并随按钮自身状态同步
        for name, b in pairs:
            b.clicked.connect(
                lambda _checked=False, _n=name: self._remember_oneclick(_n))
        self._style_menu_built = True

    def _apply_oneclick(self, button, name):
        try:
            button.click()                 # 直接复用原按钮的行为（含状态同步）
        except Exception as e:
            self._cf_status(f"应用样式 {name} 失败: {e}")

    def _remember_oneclick(self, name):
        self._oneclick_style = name
        if self._style_menu_btn is not None:
            self._style_menu_btn.setText(f"🎨 {name} ▾")
        self._cf_status(f"已应用一键样式：{name}")

    # ═══════════════════════════════════════════════════════════
    #  ③ 右侧抽屉收起 / 展开
    # ═══════════════════════════════════════════════════════════
    def _build_drawer_toggle(self):
        if self._drawer_built:
            return
        tabs = getattr(self, "right_tabs", None)
        if tabs is not None:
            btn = QToolButton(tabs)
            btn.setObjectName("SmallBtn")
            btn.setText("▤")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip("收起右侧「设置 / 引文」（Ctrl+B）")
            btn.clicked.connect(self._toggle_drawer)
            tabs.setCornerWidget(btn, Qt.TopRightCorner)

        # 画布卡片里的常驻入口：收起后靠它再展开
        cub = getattr(self, "cub_canvas", None)
        bar = cub.findChild(QWidget, "CubStyleBar") if cub is not None else None
        if bar is not None and bar.layout() is not None:
            btn2 = QToolButton(bar)
            btn2.setObjectName("SmallBtn")
            btn2.setText("▤ 设置面板")
            btn2.setCursor(Qt.PointingHandCursor)
            btn2.setToolTip("显示 / 隐藏右侧「设置 / 引文」（Ctrl+B）")
            btn2.clicked.connect(self._toggle_drawer)
            bar.layout().addWidget(btn2)
            self._drawer_btn = btn2

        sc = QShortcut(QKeySequence("Ctrl+B"), self)
        sc.activated.connect(self._toggle_drawer)
        self._drawer_shortcut = sc      # 保引用，防被 GC
        self._drawer_built = True

    def _right_pane(self):
        sp = getattr(self, "_body_splitter", None)
        if sp is None or sp.count() < 2:
            return None
        return sp.widget(sp.count() - 1)

    def _toggle_drawer(self):
        pane = self._right_pane()
        if pane is None:
            return
        sp = self._body_splitter
        if pane.isVisible():
            self._drawer_sizes = list(sp.sizes())
            pane.hide()
            self._drawer_collapsed = True
        else:
            pane.show()
            self._drawer_collapsed = False
            sizes = self._drawer_sizes or []
            if len(sizes) == sp.count():
                sp.setSizes(sizes)
        if self._drawer_btn is not None:
            self._drawer_btn.setText("▸ 设置面板" if self._drawer_collapsed
                                     else "▤ 设置面板")
        self._cf_status("右侧设置：" + ("已收起（画布全宽）"
                                        if self._drawer_collapsed else "已展开"))

    # ═══════════════════════════════════════════════════════════
    #  小工具
    # ═══════════════════════════════════════════════════════════
    def _cf_status(self, msg):
        """状态提示：优先写到画布状态栏，退回主窗口日志。"""
        cub = getattr(self, "cub_canvas", None)
        if cub is not None and hasattr(cub, "_set_status"):
            try:
                cub._set_status(msg)
                return
            except Exception:
                pass
        try:
            self._append_log(msg)
        except Exception:
            pass


def main():
    """独立启动入口：复用 main.py 的完整引导流程。"""
    os.environ["MOLSTUDIO_UI"] = "canvas"
    # 直接以脚本运行时本模块名是 __main__，登记到规范名下。
    _canon = "molstudio.ui.main_window_canvas_first"
    if _canon not in sys.modules:
        sys.modules[_canon] = sys.modules[__name__]
    import molstudio.app as _main
    _main.main()


if __name__ == "__main__":
    main()
