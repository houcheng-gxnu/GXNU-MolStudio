# -*- coding: utf-8 -*-
"""MolStudio 「Studio」界面（DeepSeek Harness 风）
================================================

设计目标（对应 docs / 评估报告里的「B 方案」）：

1. **左侧 27 项平铺导航 → 6 组分组侧栏 + 搜索 + Ctrl+K**：
   侧栏展开 232px、可收成 56px 图标 rail；「常用」默认展开，其余组折叠，
   切页时自动展开当前页所在组。
2. **顶部 90px 输入行 → 52px 单行顶栏**：品牌 + 文件 chip + 打开/语言/溢出菜单。
3. **右栏 677px → 400px 检查器**：页头显示「页名 / 所在分组」，全局
   「设置 / 引文」页签栏隐藏，引文改成页头按钮；主视图还给画布。
4. **画布底部 251px 控件区 → 44px 紧凑工具条**（见 studio_canvas_bar）。
5. **底部 24px 状态栏**，只显示一行状态。
6. **DSH 浅色 token**：近黑主按钮、蓝色只做链接/焦点、hover 与 selected 同色、
   无蓝底标题块、细描边代替卡片堆叠。

实现原则与 `main_window_clean.py` 完全一致：**子类继承 + 皮肤后处理**，
不复制任何功能代码，27 个分析面板、全部信号接线、快捷键、拖放、语言切换
都由父类原样建立；本文件只搬控件、改比例、换样式。

用法::

    python main.py --ui studio
    set MOLSTUDIO_UI=studio && python main.py
"""

from __future__ import annotations

import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))

from PyQt5.QtCore import QEvent, Qt, QSize, QTimer
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QAction,
    QAbstractSpinBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QShortcut,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from molstudio.ui.main_window_clean import (
    ICON_ACCENT,
    ICON_MUTED,
    NAV_ICONS,
    MolStudioCleanWindow,
    pick_button_icon,
)
from molstudio.ui.ui_icons import make_icon
from molstudio.ui.studio_theme import (
    ICON_ACCENT as STUDIO_ICON_ACCENT,
    ICON_MUTED as STUDIO_ICON_MUTED,
    ICON_ON_PRIMARY,
    STUDIO_CANVAS_AUGMENT,
    STUDIO_QSS,
    TOKENS,
    remap_qss_studio,
)
from molstudio.ui.studio_sidebar import CommandPalette, StudioSidebar

try:
    from molstudio.ui.studio_canvas_bar import install_compact_canvas_bar
except Exception as _e:      # noqa: BLE001 —— 工具条模块缺失时只降级，不拖垮整个界面
    print(f"[studio] 画布工具条模块不可用，退回原控件区：{_e}")

    def install_compact_canvas_bar(win):
        return None


# ══════════════════════════════════════════════════════════════════════════ #
#  信息架构：27 个功能页 → 6 组
# ══════════════════════════════════════════════════════════════════════════ #
# 每组：(组 id, 中文名, 英文名, 页 key 顺序)。页 key 与 main_window._tab_keys 一致；
# 不在表里的 key（插件缺面板时也不会发生）会落到「其他」组，保证 27 页全部可达。
GROUP_DEFS = (
    ("common", "常用", "Favorites",
     ("tab_viz", "tab_setup", "tab_library", "tab_orca", "tab_xtb",
      "tab_gaussian")),
    ("electronic", "电子结构", "Electronic",
     ("tab_nbo", "tab_charge_bond", "tab_lmo", "tab_ow_fukui")),
    ("surface", "表面与相互作用", "Surface & Interaction",
     ("tab_esp", "tab_igmh", "tab_aim", "tab_etsnocv",
      "tab_edd", "tab_steric", "tab_surfproj", "tab_aicd")),
    ("spectra", "光谱与能量", "Spectra & Energy",
     ("tab_spectrum", "tab_dos", "tab_esm", "tab_microkinetics", "tab_di")),
    ("reaction", "反应路径", "Reaction Paths",
     ("tab_irc", "tab_ircsplit", "tab_asm_irc")),
    ("tools", "结构与工具", "Structure & Tools",
     ("tab_crystal", "tab_cub_stack", "tab_mpp")),
)

# 参数分区的默认折叠规则：命中「运行类」关键词的永远展开，命中「附属信息」的
# 默认收起；其余前 3 个分区展开，第 4 个之后收起 —— 一屏之内只留「要动的东西」。
_SECTION_RUN_WORDS = ("运行", "计算", "开始", "生成", "出图", "绘制", "渲染",
                      "提交", "分析", "run", "compute", "start", "render")
_SECTION_AUX_WORDS = ("图例", "说明", "帮助", "高级", "颜色", "字体", "文献",
                      "引用", "选项", "输出设置", "其他", "更多", "legend",
                      "advanced", "option")

# 画布参数卡的 studio 覆盖样式（追加到 canvas_params 自己的样式表后面）
_PARAMS_STUDIO_QSS = """
/* Studio 参数卡：白卡 + 12px 圆角 + 中性标题 */
QWidget#CubParamCard {
    background-color: #FFFFFF;
    border: 1px solid #E6E6E6;
    border-radius: 12px;
}
QWidget#CubParamCard > QToolButton {
    color: #61666B;
    font-size: 9.5pt;
    font-weight: 600;
    text-align: left;
    padding: 6px 10px;
    min-height: 22px;
}
QWidget#CubParamCard > QToolButton:checked {
    color: #0F1115;
}
QWidget#CubParamCard > QToolButton:hover {
    background-color: #F2F3F4;
}
QWidget#CubParamSection {
    background: transparent;
    padding: 6px 6px 8px 6px;
}
"""


class MolStudioStudioWindow(MolStudioCleanWindow):
    """DSH 风主窗口：分组侧栏 + 单行顶栏 + 画布优先 + 400px 检查器。"""

    # 尺寸常量全部来自 studio_theme.TOKENS，这里只留窗口级默认值
    SIDEBAR_W = TOKENS["sidebar_w"]
    RAIL_W = TOKENS["sidebar_rail_w"]
    INSPECTOR_W = TOKENS["inspector_w"]

    def __init__(self):
        # 这些状态必须在 super().__init__()（内部会调 _setup_ui → 皮肤）之前就位
        self._topbar = None
        self._sidebar = None
        self._statusbar = None
        self._status_left = None
        self._status_right = None
        self._inspector_header = None
        self._inspector_title = None
        self._inspector_sub = None
        self._inspector_cite = None
        self._inspector_info = None
        self._inspector_menu_btn = None
        self._act_fold = None
        self._act_wide = None
        self._footer_buttons = []
        self._inspector_wide_btn = None
        self._inspector_wide = False
        self._page_intro = {}
        self._page_chrome_done = False
        self._sidebar_footer = None
        self._canvas_file_chip = None
        self._canvas_empty_hint = None
        self._path_box = None
        self._path_chip = None
        self._studio_bar_host = None
        self._bar_slimmed = False
        self._param_topbar_done = False
        self._params_qss_done = False
        self._param_compacted = False
        self._inspector_fold = None
        self._overflow_btn = None
        self._overflow_menu = None
        self._palette_dlg = None
        self._palette_shortcut = None
        self._rail_shortcut = None
        self._page_group = {}
        self._studio_sized = False
        self._studio_bar_done = False
        self._nav_card_old = None
        self._section_defaults_done = False
        super().__init__()

    # ═══════════════════════════════════════════════════════════
    #  主题 / 皮肤入口
    # ═══════════════════════════════════════════════════════════
    def _apply_theme(self):
        """只换这一处：CLEAN_QSS → STUDIO_QSS。"""
        self.setStyleSheet(STUDIO_QSS)

    def _apply_clean_skin(self):
        """子类覆写：把 clean 皮肤的后处理整段换成 studio 版（幂等）。"""
        self._apply_studio_skin()

    def _apply_studio_skin(self):
        """完整后处理。每一步都 try/except：皮肤失败最多是「不好看」，不能开不了机。"""
        try:
            self.setStyleSheet(STUDIO_QSS)
        except Exception:
            pass

        steps = (
            ("顶栏", self._setup_topbar),
            ("侧栏", self._setup_sidebar),
            ("侧栏底部", self._setup_sidebar_footer),
            ("检查器", self._setup_inspector),
            ("状态栏", self._setup_statusbar),
            ("外层间距", self._apply_outer_spacing),
            ("画布卡片", self._apply_canvas_card),
            ("数值框宽度", self._fix_fixed_width_fields),
            ("比例", self._apply_sizes),
            ("画布工具条", self._setup_canvas_bar),
            ("工具条瘦身", self._slim_canvas_bar),
            ("画布胶囊", self._install_canvas_chips),
            ("页内标题清理", self._hide_page_chrome),
            ("页内留白", self._apply_page_spacing),
            ("参数卡样式", self._augment_params_qss),
            ("参数顶部条", self._hide_param_topbar),
            ("分区折叠", self._apply_section_defaults),
            ("默认收起参数", self._compact_canvas_params_once),
            ("配色重映射", lambda: self._remap_widget_styles(self)),
        )
        for name, fn in steps:
            try:
                fn()
            except Exception as e:          # noqa: BLE001
                print(f"[studio] {name} 应用失败：{e}")

        # Ctrl+K 命令面板（只在第一次皮肤时挂一次）
        try:
            self._setup_palette_shortcut()
        except Exception:
            pass

        # 面板按钮图标（沿用 clean 的「按文字关键词配图标」规则）
        try:
            self._apply_button_icons()
        except Exception:
            pass
        # 画布补充样式（圆角 / 凹陷底色）
        try:
            self._augment_canvas_qss()
        except Exception:
            pass
        # 画布工具条按钮：补 ▾ 指示 + 钉最小宽度（工具条可能比皮肤晚建好）
        try:
            self._decorate_canvas_bar()
        except Exception:
            pass
        # 工具条改成居中浮动的药丸 + 画布信息胶囊
        try:
            self._float_canvas_bar()
            self._place_canvas_chips()
        except Exception:
            pass
        # 检查器 ⋯ 菜单随页重建（可视化页额外带样式预设动作）
        try:
            self._rebuild_inspector_menu()
        except Exception:
            pass
        # 最后再压一次全局样式，避免局部重映射把外壳刷花
        try:
            self.setStyleSheet(STUDIO_QSS)
        except Exception:
            pass
        try:
            self._refresh_inspector_header()
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════
    #  ① 单行顶栏
    # ═══════════════════════════════════════════════════════════
    def _setup_topbar(self):
        if self._topbar is not None:
            return
        central = self.centralWidget()
        outer = central.layout() if central is not None else None
        grp_input = getattr(self, "grp_input", None)
        if outer is None or grp_input is None:
            return

        top = QFrame()
        top.setObjectName("TopBar")
        top.setFixedHeight(int(TOKENS["topbar_h"]))
        lay = QHBoxLayout(top)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)

        # 左：折叠按钮 + 品牌
        btn_menu = QToolButton(top)
        btn_menu.setObjectName("TopBarIcon")
        btn_menu.setText("☰")
        btn_menu.setToolTip("收起 / 展开左侧导航（Ctrl+B）")
        btn_menu.setCursor(Qt.PointingHandCursor)
        btn_menu.clicked.connect(self._toggle_sidebar_rail)
        lay.addWidget(btn_menu)

        brand = QLabel("MolStudio", top)
        brand.setObjectName("BrandName")
        lay.addWidget(brand)
        ver = QLabel("v1.0", top)
        ver.setObjectName("BrandVersion")
        lay.addWidget(ver)

        sep = QFrame(top)
        sep.setObjectName("TopBarDivider")
        sep.setFixedWidth(1)
        sep.setFixedHeight(20)
        lay.addWidget(sep)

        # 中：文件 chip（显示文件名，点击就地变成可编辑路径框；复用父类 var_path）
        path = getattr(self, "var_path", None)
        if path is not None:
            path.setObjectName("PathChip")
            path.setMaximumWidth(430)
            path.setMinimumWidth(240)
            box = QWidget(top)
            box.setObjectName("PathBox")
            box.setMaximumWidth(430)
            bl = QHBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(0)
            path.hide()
            bl.addWidget(path)
            chip = QLabel(box)
            chip.setObjectName("PathChipLabel")
            chip.setCursor(Qt.PointingHandCursor)
            chip.setMinimumHeight(30)
            chip.setMaximumHeight(30)
            chip.setTextFormat(Qt.RichText)
            chip.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            chip.installEventFilter(self)
            bl.addWidget(chip)
            bl.addStretch(1)
            self._path_box = box
            self._path_chip = chip
            path.installEventFilter(self)
            try:
                path.textChanged.connect(lambda _t: self._refresh_path_chip())
            except Exception:
                pass
            self._move_widget(grp_input, box, top, lay, stretch=1)
            self._refresh_path_chip()

        # 右：打开文件（复用 btn_browse_input）+ 语言 + 溢出菜单
        open_btn = getattr(self, "btn_browse_input", None)
        if open_btn is not None:
            open_btn.setObjectName("TopBarAction")
            open_btn.setCursor(Qt.PointingHandCursor)
            self._move_widget(grp_input, open_btn, top, lay)

        lang_btn = getattr(self, "_lang_btn", None)
        if lang_btn is not None:
            lang_btn.setObjectName("TopBarAction")
            self._move_widget(grp_input, lang_btn, top, lay)

        # 溢出菜单：结构库 / PPT 3D / 路径设置 / 关于（原按钮保留在隐藏的
        # grp_input 里，这里用 QAction 反向触发它们的 click，功能零复制）
        self._overflow_btn = QToolButton(top)
        self._overflow_btn.setObjectName("TopBarIcon")
        self._overflow_btn.setText("...")
        self._overflow_btn.setFixedWidth(30)
        self._overflow_btn.setToolTip("更多")
        self._overflow_btn.setCursor(Qt.PointingHandCursor)
        self._overflow_btn.setPopupMode(QToolButton.InstantPopup)
        self._overflow_menu = QMenu(self._overflow_btn)
        self._overflow_btn.setMenu(self._overflow_menu)
        lay.addWidget(self._overflow_btn)
        # 只让路径框两侧留白可伸缩：品牌/版本/按钮全部固定宽度，否则 QLabel
        # 和按钮会被 QHBoxLayout 平均拉开（实测每个被拉到 230px）。
        for wd in (btn_menu, brand, ver, sep, open_btn, lang_btn,
                   self._overflow_btn):
            if wd is not None:
                wd.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        lay.insertStretch(5, 1)
        self._rebuild_overflow_menu()

        outer.insertWidget(0, top)
        outer.removeWidget(grp_input)
        grp_input.hide()
        self._topbar = top

    def _move_widget(self, old_parent, w, new_parent, layout, stretch=0):
        """把父类建好的控件搬到新容器（保持实例与信号不变）。"""
        try:
            lay = old_parent.layout()
            if lay is not None:
                lay.removeWidget(w)
        except Exception:
            pass
        w.setParent(new_parent)
        layout.addWidget(w, stretch)
        return w

    def _refresh_path_chip(self):
        """顶栏文件 chip：显示文件名（绿点 + 名字），点击就地编辑完整路径。"""
        chip = getattr(self, "_path_chip", None)
        if chip is None:
            return
        en = getattr(self, "_lang", "zh") == "en"
        path = ""
        try:
            path = (self.var_path.text() or "").strip()
        except Exception:
            pass
        if path:
            import html
            name = os.path.basename(path.replace("\\", "/"))
            chip.setText('<span style="color:#2EA56E">●</span> '
                         + html.escape(name))
            chip.setToolTip(path)
        else:
            chip.setText("选择或拖放 .fchk / .log / .out / .xyz 文件…" if not en
                         else "Choose or drop a .fchk / .log file…")
            chip.setToolTip("")

    def _edit_path_inline(self):
        """点 chip → 变回可编辑路径框。"""
        if self._path_chip is None or getattr(self, "var_path", None) is None:
            return
        self._path_chip.hide()
        self.var_path.show()
        self.var_path.setFocus()
        self.var_path.selectAll()

    def _show_path_chip(self):
        """路径框失焦 → 回到 chip。"""
        if self._path_chip is None or getattr(self, "var_path", None) is None:
            return
        self.var_path.hide()
        self._path_chip.show()
        self._refresh_path_chip()

    def _rebuild_overflow_menu(self):
        """溢出菜单文字随语言/按钮文字刷新（动作只是转发原按钮的 click）。"""
        menu = self._overflow_menu
        if menu is None:
            return
        menu.clear()
        items = (
            (getattr(self, "btn_molecule_library", None), self._tr("tab_library"), "结构库"),
            (getattr(self, "btn_ppt3d", None), None, "PPT 3D"),
            (getattr(self, "btn_paths", None), None, "路径设置"),
            (getattr(self, "btn_about", None), self._tr("btn_about"), "关于"),
        )
        for btn, text, fallback in items:
            if btn is None:
                continue
            label = text if text else (btn.text() or fallback)
            act = QAction(label.strip() or fallback, menu)
            act.triggered.connect(lambda _checked=False, b=btn: b.click())
            menu.addAction(act)
        # 运行日志已挪到画布下方（不再是一个页签），这里补一个「展开日志」入口
        try:
            if getattr(self, "log_dock", None) is not None:
                act = QAction(self._t_ui("展开运行日志", "Show run log"), menu)
                act.triggered.connect(self._show_log_dock)
                menu.addSeparator()
                menu.addAction(act)
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════
    #  ② 分组侧栏
    # ═══════════════════════════════════════════════════════════
    def _setup_sidebar(self):
        if self._sidebar is not None:
            return
        split = getattr(self, "_body_splitter", None)
        if split is None:
            return
        sidebar = StudioSidebar()
        sidebar.pageRequested.connect(self._on_sidebar_page)
        sidebar.searchRequested.connect(self._open_palette)
        sidebar.railChanged.connect(self._on_rail_changed)
        old = split.replaceWidget(0, sidebar)
        if old is not None:
            self._nav_card_old = old
            try:
                old.hide()
                old.setParent(self)     # 留在窗口内、退出布局；main_nav 仍是状态模型
                old.hide()
            except Exception:
                pass
        self._sidebar = sidebar
        try:
            sidebar.show()          # QSplitter 会给「插入时不可见」的子控件 0 宽
            if hasattr(sidebar, "set_bottom_text"):
                sidebar.set_bottom_text("MolStudio v1.0")
        except Exception:
            pass
        self._rebuild_sidebar()

    def _group_title(self, gid):
        en = getattr(self, "_lang", "zh") == "en"
        for g, zh, e, _keys in GROUP_DEFS:
            if g == gid:
                return e if en else zh
        return "Other" if en else "其他"

    def _build_sidebar_groups(self):
        """按 GROUP_DEFS 组装侧栏数据；保证 _tab_keys 里每一页都有归属。"""
        key2idx = {k: i for i, k in enumerate(self._tab_keys)}
        used = set()
        groups = []
        page_group = {}
        for gid, zh, en, keys in GROUP_DEFS:
            entries = []
            for key in keys:
                idx = key2idx.get(key)
                if idx is None:
                    continue
                entries.append({
                    "index": idx,
                    "key": key,
                    "text": self._tr(key),
                    "icon": NAV_ICONS.get(key) or "cube",
                })
                page_group[idx] = gid
                used.add(key)
            if entries:
                groups.append((self._group_title(gid), entries))
        rest = [(i, k) for i, k in enumerate(self._tab_keys) if k not in used]
        if rest:
            gid = "other"
            groups.append(("Other" if getattr(self, "_lang", "zh") == "en" else "其他",
                           [{
                               "index": i,
                               "key": k,
                               "text": self._tr(k),
                               "icon": NAV_ICONS.get(k) or "cube",
                           } for i, k in rest]))
            for i, _k in rest:
                page_group[i] = gid
        self._page_group = page_group
        return groups

    def _rebuild_sidebar(self):
        if self._sidebar is None:
            return
        try:
            groups = self._build_sidebar_groups()
            cur = self.tabs.currentIndex() if hasattr(self, "tabs") else 0
            self._sidebar.set_entries(groups, cur)
            self._sidebar.set_current(max(cur, 0))
        except Exception as e:      # noqa: BLE001
            import traceback
            print(f"[studio] 侧栏条目构建失败：{e}")
            traceback.print_exc()

    def _on_sidebar_page(self, index):
        """侧栏点击 → 走父类的导航联动（main_nav 是隐藏的状态模型）。"""
        nav = getattr(self, "main_nav", None)
        if nav is not None and 0 <= index < nav.count():
            if nav.currentRow() == index:
                self.tabs.setCurrentIndex(index)
            else:
                nav.setCurrentRow(index)
        else:
            self.tabs.setCurrentIndex(index)
        try:
            self._sidebar.expand_group_of(index)
            self._sidebar.set_current(index)
        except Exception:
            pass

    def _toggle_sidebar_rail(self):
        if self._sidebar is not None:
            self._sidebar.toggle_rail()

    def _on_rail_changed(self, rail):
        self._apply_sizes(force=True)

    def _setup_sidebar_footer(self):
        """侧栏底部的低频入口：运行日志 / 路径设置 / 关于（对应效果图底栏）。"""
        sb = self._sidebar
        if sb is None or self._sidebar_footer is not None:
            return
        lay = sb.layout()
        if lay is None:
            return
        foot = QWidget()
        foot.setObjectName("SidebarFoot")
        fl = QVBoxLayout(foot)
        fl.setContentsMargins(8, 2, 8, 8)
        fl.setSpacing(0)

        def _go_log():
            # 日志在画布下方（不再是页签）：展开它并跳到末尾
            self._show_log_dock()

        items = (
            (self._t_ui("运行日志", "Log"), _go_log),
            (self._t_ui("路径设置", "Paths"),
             lambda: self.btn_paths.click() if getattr(self, "btn_paths", None) else None),
            (self._t_ui("关于 MolStudio", "About"),
             lambda: self.btn_about.click() if getattr(self, "btn_about", None) else None),
        )
        for text, cb in items:
            b = QToolButton(foot)
            b.setObjectName("SidebarFootBtn")
            b.setText(text)
            b.setToolButtonStyle(Qt.ToolButtonTextOnly)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(28)
            b.clicked.connect(cb)
            fl.addWidget(b)
            self._footer_buttons.append(b)
        sep = QFrame(foot)
        sep.setObjectName("SidebarSep")
        sep.setFixedHeight(1)
        fl.insertWidget(0, sep)
        lay.addWidget(foot)
        self._sidebar_footer = foot
        try:
            sb.set_bottom_text("")      # 版本号已由底栏动作替代
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════
    #  ③ 右栏检查器（页头 + 隐藏全局页签）
    # ═══════════════════════════════════════════════════════════
    def _setup_inspector(self):
        if self._inspector_header is not None:
            return
        split = getattr(self, "_body_splitter", None)
        if split is None or split.count() < 2:
            return
        right = split.widget(split.count() - 1)
        lay = right.layout() if right is not None else None
        if lay is None:
            return

        header = QWidget()
        header.setObjectName("InspectorHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 12, 12, 10)
        hl.setSpacing(6)

        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(2)
        title = QLabel("—")
        title.setObjectName("InspectorTitle")
        sub = QLabel("")
        sub.setObjectName("InspectorSub")
        texts.addWidget(title)
        texts.addWidget(sub)
        hl.addLayout(texts, stretch=1)

        info = QToolButton(header)
        info.setObjectName("InspectorIcon")
        info.setText("i")
        info.setToolTip("功能说明")
        info.setCursor(Qt.PointingHandCursor)
        hl.addWidget(info)

        dots = QToolButton(header)
        dots.setObjectName("InspectorIcon")
        dots.setText("...")
        dots.setToolTip("更多（折叠参数 / 加宽面板）")
        dots.setCursor(Qt.PointingHandCursor)
        dots.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(dots)
        self._act_fold = menu.addAction(self._t_ui("折叠 / 展开参数分区",
                                                   "Collapse / expand sections"))
        self._act_fold.triggered.connect(self._toggle_all_sections)
        self._act_wide = menu.addAction(self._t_ui("加宽 / 还原参数面板",
                                                    "Widen / restore inspector"))
        self._act_wide.triggered.connect(self._toggle_inspector_wide)
        dots.setMenu(menu)
        hl.addWidget(dots)

        cite = QToolButton(header)
        cite.setObjectName("InspectorIcon")
        cite.setText("文")
        cite.setToolTip("显示 / 隐藏当前功能的参考文献")
        cite.setCheckable(True)
        cite.setCursor(Qt.PointingHandCursor)
        cite.clicked.connect(self._on_citation_clicked)
        hl.addWidget(cite)

        lay.insertWidget(0, header)
        self._inspector_header = header
        self._inspector_title = title
        self._inspector_sub = sub
        self._inspector_info = info
        self._inspector_menu_btn = dots
        self._inspector_cite = cite

        # 全局「设置 / 引文」页签栏隐藏：改为页头按钮，省掉一层 tab
        try:
            self.right_tabs.tabBar().hide()
        except Exception:
            pass
        self._refresh_inspector_header()

    def _t_ui(self, zh, en):
        return en if getattr(self, "_lang", "zh") == "en" else zh

    def _refresh_inspector_header(self):
        if self._inspector_title is None:
            return
        try:
            idx = self.tabs.currentIndex()
            keys = getattr(self, "_tab_keys", [])
            key = keys[idx] if 0 <= idx < len(keys) else ""
            self._inspector_title.setText(self._tr(key) if key else "—")
            gid = self._page_group.get(idx)
            self._inspector_sub.setText(self._group_title(gid) if gid else "")
            if self._inspector_cite is not None:
                self._inspector_cite.setChecked(
                    getattr(self, "right_tabs", None) is not None
                    and self.right_tabs.currentIndex() == 1)
            if self._inspector_info is not None:
                intro = self._page_intro.get(idx, "")
                if intro:
                    tip = intro if len(intro) < 600 else intro[:597] + "…"
                else:
                    tip = self._t_ui("当前功能没有额外说明",
                                     "No extra description for this page")
                self._inspector_info.setToolTip(tip)
        except Exception:
            pass

    def _on_citation_clicked(self, checked):
        tabs = getattr(self, "right_tabs", None)
        if tabs is None:
            return
        tabs.setCurrentIndex(1 if checked else 0)
        self._refresh_inspector_header()

    def _sync_right_tab_bar(self, key=None):
        """覆写父类：全局页签栏永久隐藏，结构库页只保留它自己的四页签。"""
        try:
            tabs = getattr(self, "right_tabs", None)
            if tabs is None:
                return
            if key is None:
                idx = self.tabs.currentIndex()
                keys = getattr(self, "_tab_keys", [])
                key = keys[idx] if 0 <= idx < len(keys) else ""
            tabs.tabBar().hide()
            if key == "tab_library":
                tabs.setCurrentIndex(0)
            self._set_right_card_flat_top(key == "tab_library")
            if self._inspector_cite is not None:
                self._inspector_cite.setChecked(tabs.currentIndex() == 1)
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════
    #  ④ 底部状态栏
    # ═══════════════════════════════════════════════════════════
    def _setup_statusbar(self):
        if self._statusbar is not None:
            return
        central = self.centralWidget()
        outer = central.layout() if central is not None else None
        if outer is None:
            return
        bar = QFrame()
        bar.setObjectName("StatusBar")
        bar.setFixedHeight(int(TOKENS["status_h"]))
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(8)
        left = QLabel("就绪")
        left.setObjectName("StatusLeft")
        right = QLabel("Multiwfn · VMD")
        right.setObjectName("StatusRight")
        sep = QFrame(bar)
        sep.setObjectName("StatusSep")
        sep.setFixedWidth(1)
        sep.setFixedHeight(12)
        lay.addWidget(left, stretch=1)
        lay.addWidget(sep)
        lay.addWidget(right)
        outer.addWidget(bar)
        self._statusbar = bar
        self._status_left = left
        self._status_right = right
        self._set_status(self._status_hint())

    def _status_hint(self):
        """状态栏默认文案：未载入文件时给下一步，已载入时显示文件名。"""
        en = getattr(self, "_lang", "zh") == "en"
        path = ""
        try:
            path = (self.var_path.text() or "").strip()
        except Exception:
            pass
        if path:
            name = os.path.basename(path.replace("\\", "/"))
            return ("Ready · " if en else "就绪 · ") + name
        return ("Ready · Drop a .fchk / .log file, or click Browse"
                if en else "就绪 · 拖入 .fchk / .log 文件，或点右上角「浏览」载入")

    def _set_status(self, msg):
        if self._status_left is not None and msg:
            text = str(msg).replace("\n", " ").strip()
            if len(text) > 120:
                text = text[:117] + "…"
            self._status_left.setText(text)

    def _on_canvas_status(self, msg):
        try:
            super()._on_canvas_status(msg)
        except Exception:
            pass
        self._set_status(msg)

    # ═══════════════════════════════════════════════════════════
    #  ⑤ 比例 / 工具条 / 分区折叠
    # ═══════════════════════════════════════════════════════════
    def _apply_outer_spacing(self):
        """外层留白：顶部 10、左右 12、间距 10（比父类更松，接近 DSH 的呼吸感）。"""
        central = self.centralWidget()
        lay = central.layout() if central is not None else None
        if lay is None:
            return
        try:
            lay.setContentsMargins(12, 10, 12, 8)
            lay.setSpacing(8)
        except Exception:
            pass

    def _apply_canvas_card(self):
        """画布区恢复白卡外观（clean 的卡化步骤被本类跳过，这里单独补）。"""
        grp = getattr(self, "grp_canvas", None)
        if grp is None:
            return
        try:
            grp.setObjectName("CanvasCard")
            grp.setAttribute(Qt.WA_StyledBackground, True)
            lay = grp.layout()
            if lay is not None:
                lay.setContentsMargins(6, 6, 6, 6)
                lay.setSpacing(0)
        except Exception:
            pass
        right_card = getattr(self, "right_card", None)
        if right_card is not None:
            try:
                lay = right_card.layout()
                if lay is not None:
                    lay.setContentsMargins(16, 12, 14, 14)
            except Exception:
                pass

    def _apply_sizes(self, force=False):
        split = getattr(self, "_body_splitter", None)
        if split is None:
            return
        if self._studio_sized and not force:
            return
        total = split.width()
        if total <= 100:                    # 还没上屏，等 show/resize 后再算
            return
        self._studio_sized = True
        try:
            if self._sidebar is not None and not self._sidebar.isVisible():
                self._sidebar.show()
        except Exception:
            pass
        rail = bool(self._sidebar is not None and self._sidebar.is_rail())
        sidebar_w = self.RAIL_W if rail else self.SIDEBAR_W
        try:
            split.setStretchFactor(0, 0)
            split.setStretchFactor(1, 6)
            split.setStretchFactor(2, 4)
        except Exception:
            pass
        rest = max(total - sidebar_w, 320)
        ratio = 0.62 if self._inspector_wide else 0.40
        right = int(rest * ratio)
        right = max(480, min(right, 760))
        canvas = max(rest - right, 320)
        sizes = [sidebar_w, canvas, right]
        try:
            right_widget = split.widget(split.count() - 1)
            if right_widget is not None:
                right_widget.setMinimumWidth(460)
        except Exception:
            pass
        try:
            split.setSizes(sizes)
            if hasattr(split, "set_default_sizes"):
                split.set_default_sizes(sizes)
        except Exception:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "_studio_resized_once", False):
            return
        if self.width() < 600:
            return
        self._studio_resized_once = True
        QTimer.singleShot(0, lambda: self._apply_sizes(force=True))

    def _setup_canvas_bar(self):
        if self._studio_bar_done:
            return
        try:
            bar = install_compact_canvas_bar(self)
        except Exception as e:      # noqa: BLE001
            print(f"[studio] 画布工具条应用失败：{e}")
            bar = None
        if bar is not None:
            self._studio_bar_done = True
            self._decorate_canvas_bar()

    def _float_canvas_bar(self):
        """把画布工具条从「通栏页脚」改成居中浮动药丸（效果图里的写法）。

        做法：在工具条原位置插一个透明宿主，把工具条塞进宿主中间的 HBox，
        两侧留 stretch；工具条设固定宽度并保留圆角描边，看起来就是浮在画布上。
        """
        bar = getattr(self, "_studio_canvas_bar", None)
        if bar is None:
            return
        host = self._studio_bar_host
        if host is None:
            parent = bar.parentWidget()
            lay = parent.layout() if parent is not None else None
            if lay is None:
                return
            idx = lay.indexOf(bar)
            if idx < 0:
                return
            host = QWidget()
            host.setObjectName("CanvasBarHost")
            host.setAttribute(Qt.WA_TranslucentBackground, True)
            hl = QHBoxLayout(host)
            hl.setContentsMargins(0, 4, 0, 8)
            hl.setSpacing(0)
            hl.addStretch(1)
            lay.removeWidget(bar)
            hl.addWidget(bar)
            hl.addStretch(1)
            lay.insertWidget(idx, host)
            self._studio_bar_host = host
        try:
            bar.adjustSize()
            width = min(max(bar.sizeHint().width() + 16, 300), 520)
            bar.setFixedWidth(width)
            bar.setFixedHeight(42)
        except Exception:
            pass
        self._place_canvas_chips()

    def _slim_canvas_bar(self):
        """历史遗留：以前要把「出图观感」从条上搬进「更多 ▾」。

        2026-11-12 起 `studio_canvas_bar` 自己就把观感与 DPI 放进「导出 ▾」的
        「导出设置」组，「更多 ▾」这个按钮已经取消，本方法成了空操作；保留
        签名是因为调用点在 `_setup_canvas_bar` / resize 链里，删了要连带改。
        """
        self._bar_slimmed = True

    def _apply_page_spacing(self):
        """所有功能页统一留白：外边距 12、块间距 10（比父类更接近效果图的呼吸感）。"""
        for i in range(self.tabs.count()):
            page = self.tabs.widget(i)
            lay = page.layout() if page is not None else None
            if lay is None:
                continue
            try:
                lay.setContentsMargins(12, 10, 12, 10)
                lay.setSpacing(10)
            except Exception:
                continue

    def _augment_params_qss(self):
        """画布参数卡（可视化页）追加 studio 样式。"""
        if self._params_qss_done:
            return
        cp = getattr(self, "canvas_params", None)
        if cp is None:
            return
        self._params_qss_done = True
        try:
            ss = cp.styleSheet() or ""
            if "Studio 参数卡" not in ss:
                cp.setStyleSheet(ss + _PARAMS_STUDIO_QSS)
        except Exception:
            pass

    def _hide_param_topbar(self):
        """隐藏「样式 保存/载入/重置视角/全部展开」工具行（动作移进检查器 ⋯）。"""
        if self._param_topbar_done:
            return
        self._param_topbar_done = True
        for root in (getattr(self, "canvas_params", None),
                     getattr(self, "cub_canvas", None)):
            if root is None:
                continue
            try:
                bar = root.findChild(QWidget, "CubParamTopBar")
            except Exception:
                bar = None
            if bar is not None:
                bar.hide()
                QTimer.singleShot(0, self._sync_scroll_height)
                return

    def _rebuild_inspector_menu(self):
        """检查器 ⋯ 菜单：折叠/加宽始终有；可视化页额外提供样式预设动作。"""
        btn = self._inspector_menu_btn
        if btn is None or btn.menu() is None:
            return
        menu = btn.menu()
        menu.clear()
        self._act_fold = menu.addAction(
            self._t_ui("折叠 / 展开参数分区", "Collapse / expand sections"))
        self._act_fold.triggered.connect(self._toggle_all_sections)
        self._act_wide = menu.addAction(
            self._t_ui("还原参数面板宽度" if self._inspector_wide
                       else "加宽 / 还原参数面板",
                       "Restore inspector width" if self._inspector_wide
                       else "Widen / restore inspector"))
        self._act_wide.triggered.connect(self._toggle_inspector_wide)
        try:
            idx = self.tabs.currentIndex()
            keys = getattr(self, "_tab_keys", [])
            key = keys[idx] if 0 <= idx < len(keys) else ""
        except Exception:
            key = ""
        if key != "tab_viz":
            return
        cub = getattr(self, "cub_canvas", None)
        if cub is None:
            return
        presets = (
            (self._t_ui("保存样式…", "Save style…"), "_style_save_btn"),
            (self._t_ui("载入样式…", "Load style…"), "_style_load_btn"),
            (self._t_ui("重置视角", "Reset view"), "_btn_reset_view"),
            (self._t_ui("全部展开 / 折叠", "Expand / collapse all"), "_param_all_btn"),
        )
        menu.addSeparator()
        for text, attr in presets:
            src = getattr(cub, attr, None)
            if src is None:
                continue
            act = menu.addAction(text)
            act.triggered.connect(lambda _c=False, b=src: b.click())

    def _install_canvas_chips(self):
        """画布左上角信息胶囊 + 空态提示（都是 QLabel，不吃鼠标事件）。"""
        cub = getattr(self, "cub_canvas", None)
        if cub is None or self._canvas_file_chip is not None:
            return
        chip = QLabel(cub)
        chip.setObjectName("CanvasChip")
        chip.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        chip.hide()
        empty = QLabel(cub)
        empty.setObjectName("CanvasEmptyHint")
        empty.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        empty.setAlignment(Qt.AlignCenter)
        empty.hide()
        self._canvas_file_chip = chip
        self._canvas_empty_hint = empty
        try:
            self.var_path.textChanged.connect(lambda _t: self._refresh_canvas_chips())
        except Exception:
            pass
        cub.installEventFilter(self)
        self._refresh_canvas_chips()
        self._place_canvas_chips()

    def _refresh_canvas_chips(self):
        chip = getattr(self, "_canvas_file_chip", None)
        empty = getattr(self, "_canvas_empty_hint", None)
        if chip is None or empty is None:
            return
        en = getattr(self, "_lang", "zh") == "en"
        path = ""
        try:
            path = (self.var_path.text() or "").strip()
        except Exception:
            pass
        if path:
            name = os.path.basename(path.replace("\\", "/"))
            atoms = 0
            try:
                atoms = len(getattr(self.mol_canvas, "atoms", []) or [])
            except Exception:
                atoms = 0
            if atoms:
                chip.setText(("%s · %d atoms" if en else "%s · %d 原子") % (name, atoms))
            else:
                chip.setText(name)
            chip.show()
            empty.hide()
        else:
            chip.hide()
            empty.setText("拖入 .fchk / .log 文件，或点右上角「浏览」载入"
                          if not en else
                          "Drop a .fchk / .log file, or click Browse")
            empty.show()
        try:
            chip.raise_()
            empty.raise_()
        except Exception:
            pass
        self._place_canvas_chips()

    def _place_canvas_chips(self):
        cub = getattr(self, "cub_canvas", None)
        if cub is None:
            return
        chip = getattr(self, "_canvas_file_chip", None)
        empty = getattr(self, "_canvas_empty_hint", None)
        try:
            if chip is not None and chip.isVisible():
                chip.adjustSize()
                chip.move(14, 14)
            if empty is not None and empty.isVisible():
                empty.adjustSize()
                empty.move(max(0, (cub.width() - empty.width()) // 2),
                           max(0, (cub.height() - empty.height()) // 2 - 18))
        except Exception:
            pass

    def eventFilter(self, obj, ev):
        if obj is getattr(self, "cub_canvas", None) and ev.type() == QEvent.Resize:
            self._place_canvas_chips()
        chip = getattr(self, "_path_chip", None)
        if obj is chip and ev.type() == QEvent.MouseButtonRelease:
            self._edit_path_inline()
            return True
        if obj is getattr(self, "var_path", None) and ev.type() == QEvent.FocusOut:
            QTimer.singleShot(0, self._show_path_chip)
        return super().eventFilter(obj, ev)

    def _decorate_canvas_bar(self):
        """给带菜单的工具条按钮补 ▾，并把最小宽度钉到文字宽度。

        工具条按钮是「文字 + 菜单」的窄按钮，QHBoxLayout 会在空间富余时仍按
        sizeHint 的 96% 压缩它（实测 49px → 46px），中文首字会被裁掉。
        这里显式给最小宽度，避免任何窗口尺寸下出现半个字。
        """
        bar = getattr(self, "_studio_canvas_bar", None)
        if bar is None:
            return
        try:
            for b in bar.findChildren(QToolButton):
                if b.objectName() != "CanvasBarBtn" or b.menu() is None:
                    continue
                if getattr(b, "_paints_own_chevron", False):
                    # 新工具条按钮自带「图标 + 文字 + 自绘箭头」：
                    # 不再补 ▾（会变成两个箭头），也不能强制 TextOnly（会丢图标）。
                    b.setMinimumWidth(b.sizeHint().width())
                    b.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
                    continue
                t = b.text()
                if t and not t.endswith("▾"):
                    b.setText(t + " ▾")
                b.setToolButtonStyle(Qt.ToolButtonTextOnly)
                need = b.fontMetrics().horizontalAdvance(b.text()) + 18
                b.setFixedWidth(max(48, min(need, 110)))
                b.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        except Exception:
            pass
        self._add_pill_separators()

    def _add_pill_separators(self):
        """药丸工具条上按钮之间补细竖线（对应效果图的分组感）。"""
        if getattr(self, "_pill_seps_done", False):
            return
        bar = getattr(self, "_studio_canvas_bar", None)
        if bar is None:
            return
        if getattr(bar, "_group_seps_done", False):
            # 紧凑条自己已经插了「胶囊 | 样式·显示 | 导出」的分组竖线，
            # 再补一轮会在每组之间出现两条。
            self._pill_seps_done = True
            return
        lay = bar.layout()
        if lay is None:
            return
        self._pill_seps_done = True
        try:
            btns = []
            for i in range(lay.count()):
                wd = lay.itemAt(i).widget()
                if wd is not None and wd.objectName() == "CanvasBarBtn":
                    btns.append(wd)
            for b in reversed(btns[1:]):
                idx = lay.indexOf(b)
                if idx <= 0:
                    continue
                sep = QFrame(bar)
                sep.setObjectName("CanvasBarSep")
                sep.setFixedWidth(1)
                sep.setFixedHeight(16)
                lay.insertWidget(idx, sep)
        except Exception:
            self._pill_seps_done = False
        except Exception:
            pass

    def _scroll_right_to_top(self):
        """切页后把右栏滚回顶部（否则会停在上一个页的滚动位置）。"""
        try:
            from molstudio.ui.main_window import PagedScrollArea
            sc = self.findChild(PagedScrollArea)
            if sc is not None:
                sc.verticalScrollBar().setValue(0)
        except Exception:
            pass

    def _apply_section_defaults(self):
        """给所有功能页装上「点标题折叠」，并按规则默认收起附属分区。"""
        if self._section_defaults_done:
            return
        try:
            self._install_section_toggles()
        except Exception as e:      # noqa: BLE001
            print(f"[studio] 分区折叠安装失败：{e}")
            return
        self._section_defaults_done = True
        for i in range(self.tabs.count()):
            page = self.tabs.widget(i)
            if page is None:
                continue
            try:
                groups = [gb for gb in page.findChildren(QGroupBox)
                          if getattr(gb, "_clean_section", False)]
                for j, gb in enumerate(groups):
                    title = gb.title()
                    # 去掉 clean 加上的 ▾/▸
                    if title[:1] in (self._CHEV_DOWN, self._CHEV_RIGHT):
                        title = title[1:].lstrip()
                    low = title.lower()
                    is_run = any(w in title or w in low for w in _SECTION_RUN_WORDS)
                    is_aux = any(w in title or w in low for w in _SECTION_AUX_WORDS)
                    should_collapse = (not is_run) and (is_aux or j >= 3)
                    st = getattr(self, "_section_state", {}).get(gb)
                    if st is not None and st["collapsed"] != should_collapse:
                        self._toggle_section(gb)
            except Exception:
                continue
        QTimer.singleShot(0, self._sync_scroll_height)

    def _toggle_inspector_wide(self):
        """检查器加宽 / 还原：分析面板默认按 ~660px 设计，窄屏下需要时可放开。"""
        self._inspector_wide = not self._inspector_wide
        if self._act_wide is not None:
            self._act_wide.setText(
                self._t_ui("还原参数面板宽度", "Restore inspector width")
                if self._inspector_wide else
                self._t_ui("加宽 / 还原参数面板", "Widen / restore inspector"))
        self._apply_sizes(force=True)

    def _fix_fixed_width_fields(self):
        """固定宽度的数值框/输入框按实际文字宽度补齐。

        分析面板里不少 QLineEdit 用 setFixedWidth(64) 这类写法，旧主题 9pt 时
        刚好装下 "0.050"；studio 的 9.5pt + 内边距会把它裁成 ").050"。
        这里只对「min == max 且 ≤120」的窄框按字体实测宽度补几像素，不动布局。
        """
        for wdg in self.findChildren((QLineEdit, QAbstractSpinBox)):
            try:
                maxw = wdg.maximumWidth()
                if maxw <= 0 or maxw >= 120 or wdg.minimumWidth() != maxw:
                    continue
                need = wdg.fontMetrics().horizontalAdvance(wdg.text()) + 22
                if need > maxw:
                    wdg.setFixedWidth(min(int(need), 120))
            except Exception:
                continue

    def _hide_page_chrome(self):
        """隐藏页内与检查器页头重复的「标题 + 长说明」，说明文字转到 ⓘ。

        分析面板顶部通常有「电子密度差 · EDD」蓝色标题和一段方法说明；在
        studio 里页头已经显示页名，再重复一遍会让首屏像表单。这里只处理
        「第一个分组框之前、且文字较短/较长」的 QLabel，宁少勿多。
        """
        if self._page_chrome_done:
            return
        self._page_chrome_done = True
        import re
        keys = getattr(self, "_tab_keys", [])
        for idx in range(self.tabs.count()):
            page = self.tabs.widget(idx)
            if page is None:
                continue
            lay = page.layout()
            if lay is None:
                continue
            title = self._tr(keys[idx]) if idx < len(keys) else ""
            found_title = False
            intro = []
            try:
                count = lay.count()
            except Exception:
                continue
            for j in range(min(count, 8)):
                try:
                    wd = lay.itemAt(j).widget()
                except Exception:
                    continue
                if wd is None:
                    continue
                if isinstance(wd, QGroupBox):
                    break
                if not isinstance(wd, QLabel):
                    continue
                try:
                    plain = re.sub(r"<[^>]+>", "", wd.text() or "").strip()
                except Exception:
                    continue
                if not plain:
                    continue
                if (not found_title and title and plain.startswith(title)
                        and len(plain) <= 80):
                    found_title = True
                    try:
                        wd.hide()
                    except Exception:
                        pass
                    continue
                if found_title and len(plain) >= 40:
                    intro.append(plain)
                    try:
                        wd.hide()
                    except Exception:
                        pass
            if intro:
                self._page_intro[idx] = "\n".join(intro)
        self._refresh_inspector_header()
        QTimer.singleShot(0, self._sync_scroll_height)

    def _compact_canvas_params_once(self):
        """可视化页的参数分节：本会话强制只展开第一节。

        面板自己会把展开状态写进 fchk_orbital.ini；直接调它的
        show_param_sections 会持久化，改坏 classic 的状态。这里只改按钮/内容
        可见性，跳过 toggled 信号，不落盘。
        """
        if self._param_compacted:
            return
        cub = getattr(self, "cub_canvas", None)
        secs = getattr(cub, "_sec", None) if cub is not None else None
        if not secs:
            return
        self._param_compacted = True
        try:
            keys = list(getattr(cub, "_PARAM_SECTIONS", []))
            for i, (key, _title) in enumerate(keys):
                st = secs.get(key)
                if st is None:
                    continue
                on = (i == 0)
                btn = st["btn"]
                btn.blockSignals(True)
                btn.setChecked(on)
                btn.blockSignals(False)
                st["body"].setVisible(on)
                try:
                    from molstudio.render.ovcanvas._panel import _cv  # 面板内中英转换
                    btn.setText(("▾ " if on else "▸ ") + _cv(dict(cub._PARAM_SECTIONS)[key]))
                except Exception:
                    pass
            if hasattr(cub, "_sync_all_btn"):
                cub._sync_all_btn()
            if hasattr(cub, "paramsChanged"):
                cub.paramsChanged.emit()
            for delay in (0, 60, 200):
                QTimer.singleShot(delay, self._sync_scroll_height)
        except Exception:
            pass

    def _sync_scroll_height(self):
        """折叠/隐藏内容后，让右栏滚动区按新内容高度重算（去掉多余滚动条）。"""
        try:
            from molstudio.ui.main_window import PagedScrollArea
            sc = self.findChild(PagedScrollArea)
            if sc is not None and hasattr(sc, "_sync_stack_height"):
                sc._sync_stack_height()
        except Exception:
            pass

    def _toggle_all_sections(self):
        """页头「折叠」按钮：当前页附属分区一键收起 / 全部展开。"""
        try:
            page = self.tabs.currentWidget()
            if page is None:
                return
            groups = [gb for gb in page.findChildren(QGroupBox)
                      if getattr(gb, "_clean_section", False)]
            state = getattr(self, "_section_state", {})
            has_collapsed = any(state.get(gb, {}).get("collapsed") for gb in groups)
            for gb in groups:
                st = state.get(gb)
                if st is None:
                    continue
                if has_collapsed:
                    if st["collapsed"]:
                        self._toggle_section(gb)
                else:
                    self._toggle_section(gb)
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════
    #  ⑥ Ctrl+K 命令面板
    # ═══════════════════════════════════════════════════════════
    def _setup_palette_shortcut(self):
        if self._palette_shortcut is not None:
            return
        try:
            sc = QShortcut(QKeySequence("Ctrl+K"), self)
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(self._open_palette)
            self._palette_shortcut = sc
        except Exception:
            self._palette_shortcut = None
        try:
            sc2 = QShortcut(QKeySequence("Ctrl+B"), self)
            sc2.setContext(Qt.ApplicationShortcut)
            sc2.activated.connect(self._toggle_sidebar_rail)
            self._rail_shortcut = sc2
        except Exception:
            self._rail_shortcut = None

    def _open_palette(self):
        entries = []
        try:
            keys = getattr(self, "_tab_keys", [])
            for i, key in enumerate(keys):
                gid = self._page_group.get(i)
                group = self._group_title(gid) if gid else ""
                label = f"{self._tr(key)}  ·  {group}" if group else self._tr(key)
                entries.append((label, ("page", i)))
            entries.extend([
                ("打开文件…", ("action", "open")),
                ("结构库…", ("action", "library")),
                ("导出 PPT 3D…", ("action", "ppt3d")),
                ("路径设置…", ("action", "paths")),
                ("切换中英文", ("action", "lang")),
                ("关于 MolStudio", ("action", "about")),
            ])
            dlg = CommandPalette(entries, self, title="跳转到功能或动作")
            self._palette_dlg = dlg
            payload = dlg.pick()
        except Exception as e:      # noqa: BLE001
            print(f"[studio] 命令面板打开失败：{e}")
            return
        finally:
            self._palette_dlg = None
        if not payload:
            return
        kind, value = payload
        if kind == "page":
            self._on_sidebar_page(int(value))
            return
        btn = {
            "open": getattr(self, "btn_browse_input", None),
            "library": getattr(self, "btn_molecule_library", None),
            "ppt3d": getattr(self, "btn_ppt3d", None),
            "paths": getattr(self, "btn_paths", None),
            "lang": getattr(self, "_lang_btn", None),
            "about": getattr(self, "btn_about", None),
        }.get(value)
        if btn is not None:
            try:
                btn.click()
            except Exception:
                pass

    # ═══════════════════════════════════════════════════════════
    #  ⑦ 与父类钩子的衔接
    # ═══════════════════════════════════════════════════════════
    def _setup_main_nav(self):
        """父类建好隐藏的 main_nav 状态模型后，重建侧栏条目。"""
        super()._setup_main_nav()
        self._rebuild_sidebar()

    def _sync_main_nav(self):
        """切页 / 切语言都走这里：刷新侧栏选中态与检查器页头。"""
        super()._sync_main_nav()
        try:
            idx = self.tabs.currentIndex()
            if self._sidebar is not None:
                self._sidebar.set_current(max(idx, 0))
                self._sidebar.expand_group_of(max(idx, 0))
        except Exception:
            pass
        self._refresh_inspector_header()

    def _on_tab_changed(self, index):
        super()._on_tab_changed(index)
        try:
            tabs = getattr(self, "right_tabs", None)
            if tabs is not None and tabs.currentIndex() != 0:
                tabs.setCurrentIndex(0)     # 切页回到「参数」视图
        except Exception:
            pass
        self._refresh_inspector_header()
        if self._sidebar is not None:
            try:
                self._sidebar.set_current(max(index, 0))
                self._sidebar.expand_group_of(max(index, 0))
            except Exception:
                pass
        QTimer.singleShot(0, self._scroll_right_to_top)
        try:
            self._rebuild_inspector_menu()
        except Exception:
            pass

    def _apply_lang_ui(self):
        """语言切换后刷新侧栏、顶栏溢出菜单、检查器页头。"""
        super()._apply_lang_ui()
        try:
            self._rebuild_sidebar()
        except Exception:
            pass
        try:
            self._rebuild_overflow_menu()
        except Exception:
            pass
        # 画布工具条：文字 + 菜单项跟着换语言，换完再补 ▾ 指示
        bar = getattr(self, "_studio_canvas_bar", None)
        if bar is not None:
            try:
                bar.update_texts()
            except Exception:
                pass
            self._decorate_canvas_bar()
            try:
                self._float_canvas_bar()
            except Exception:
                pass
        # 侧栏底部动作 / 检查器菜单 / 画布胶囊跟着换语言
        try:
            if self._footer_buttons:
                texts = (self._t_ui("运行日志", "Log"),
                         self._t_ui("路径设置", "Paths"),
                         self._t_ui("关于 MolStudio", "About"))
                for b, t in zip(self._footer_buttons, texts):
                    b.setText(t)
            if self._act_fold is not None:
                self._act_fold.setText(self._t_ui(
                    "折叠 / 展开参数分区", "Collapse / expand sections"))
            self._rebuild_inspector_menu()
            self._refresh_canvas_chips()
            self._refresh_path_chip()
        except Exception:
            pass
        if self._topbar is not None:
            try:
                self._set_status(self._status_hint())
            except Exception:
                pass
        self._refresh_inspector_header()

    def _augment_canvas_qss(self):
        """画布面板补充样式（studio 版配色）。"""
        cub = getattr(self, "cub_canvas", None)
        if cub is None:
            return
        try:
            ss = cub.styleSheet() or ""
        except Exception:
            return
        if "Studio 皮肤补充" in ss:
            return
        try:
            cub.setStyleSheet(ss + STUDIO_CANVAS_AUGMENT)
        except Exception:
            pass

    def _remap_widget_styles(self, root):
        """面板内联 QSS：经典色 / clean 色 → studio 色（一次性正则映射）。"""
        if root is None:
            return 0
        n = 0
        for wd in root.findChildren(QWidget):
            try:
                ss = wd.styleSheet()
            except RuntimeError:
                continue
            if not ss or "#" not in ss:
                continue
            new = remap_qss_studio(ss)
            if new != ss:
                try:
                    wd.setStyleSheet(new)
                    n += 1
                except RuntimeError:
                    continue
        return n

    def _apply_button_icons(self, root=None):
        """父类按文字关键词配图标；这里把近黑主按钮上的图标改成白色。"""
        n = super()._apply_button_icons(root)
        try:
            scope = root if root is not None else self
            for b in scope.findChildren((QPushButton, QToolButton)):
                if b.objectName() not in ("PrimaryBtn", "RunBtn",
                                          "RenderBtn", "ActionBtn"):
                    continue
                kind = pick_button_icon(b.text())
                if not kind:
                    continue
                b.setIcon(make_icon(kind, ICON_ON_PRIMARY, 16))
                b.setIconSize(QSize(16, 16))
        except Exception:
            pass
        return n

    # ═══════════════════════════════════════════════════════════
    #  ⑧ 启动后补一次（父类 +10ms 会重设主题/语言）
    # ═══════════════════════════════════════════════════════════
    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_studio_shown", False):
            return
        self._studio_shown = True
        # 默认给一个更宽的窗口（画布优先布局在 1560×900 下才有呼吸感；
        # 屏幕放不下时按可用区域收）
        try:
            from PyQt5.QtWidgets import QApplication
            scr = QApplication.primaryScreen()
            if scr is not None:
                g = scr.availableGeometry()
                tw = max(1080, min(1560, g.width() - 40))
                th = max(620, min(900, g.height() - 40))
                if self.width() < tw or self.height() < th:
                    self.resize(max(self.width(), tw), max(self.height(), th))
        except Exception:
            pass
        self._setup_palette_shortcut()
        QTimer.singleShot(80, lambda: self._apply_sizes(force=True))
        QTimer.singleShot(160, self._apply_studio_skin)
        QTimer.singleShot(220, lambda: self._apply_sizes(force=True))
        QTimer.singleShot(260, self._scroll_right_to_top)
        QTimer.singleShot(320, self._decorate_canvas_bar)


def main():
    """独立启动入口：复用 main.py 的完整引导流程。"""
    os.environ["MOLSTUDIO_UI"] = "studio"
    _canon = "molstudio.ui.main_window_studio"
    if _canon not in sys.modules:
        sys.modules[_canon] = sys.modules[__name__]
    import molstudio.app as _main
    _main.main()


if __name__ == "__main__":
    main()
