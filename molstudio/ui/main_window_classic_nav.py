# -*- coding: utf-8 -*-
"""MolStudio 默认界面：经典蓝色主题 + 分组侧栏
================================================

2026-11-12：侯老师判定「经典蓝色版整体更好，但左侧 tab 分级的效果更好」，
于是把两者合成一套默认界面；Focus 灰色卡片主题完整保留为 ``--ui focus``。

做法：**只换左侧导航，别的一个不动**。

* 继承 ``OrbitalVisApp``（classic），``_apply_theme()`` 不覆写 →
  整个窗口仍是 ``theme.LIGHT_QSS`` 的经典蓝色主题：蓝底白字分节徽章、
  「设置 / 引文」页签、参数顶部工具条、蓝色按钮，一概原样。
* 只覆写 ``_setup_main_nav()``：父类把 27 个功能页装进 ``main_nav``
  （QListWidget）之后，用 ``QSplitter.replaceWidget(0, ...)`` 把第 0 栏换成
  ``StudioSidebar`` 分组导航。``main_nav`` 连同 NavCard 被 reparent + 隐藏，
  **继续当选中状态模型**，所以切页、语言刷新、引文联动、画布显隐这些
  经典版的信号接线一行都不用改。
* 侧栏自己追加一层蓝色主题 QSS（白卡 / 1px #CBD5E1 描边 / 8px 圆角 /
  选中项 #E3F2FD 浅蓝），让它读起来是经典蓝而不是 Studio 的中性灰。

顶栏精简：``结构库`` 与 ``PPT 3D`` 两个按钮隐藏 —— 前者在侧栏「常用」
组里已有等价的功能页（原按钮只是 ``_switch_to_tab("tab_library")``）；
后者不是功能页，改由 ``Ctrl+K`` 命令面板里的「PPT 3D 导出」动作触发，
功能一个没丢。「路径设置 / 关于 MolStudio」搬到侧栏版本文字下方。

功能入口：点击分组项切页、``Ctrl+K`` 命令面板直达 27 页 + PPT 3D 导出、
``Ctrl+B`` 在 232px 分组栏 ⇄ 56px 图标 rail 之间切换、双击分隔条复位栏宽。

用法::

    python main.py                      # 默认即本界面
    python main.py --ui classic         # 纯经典版（不分级，行为与以前完全一致）
    python main.py --ui focus           # 保留的灰色卡片主题
    python main.py --ui studio          # 完整 Studio 界面
"""

from __future__ import annotations

import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QShortcut, QSizePolicy

from molstudio.ui.main_window import OrbitalVisApp
from molstudio.ui.main_window_clean import NAV_ICONS
from molstudio.ui.main_window_studio import GROUP_DEFS
from molstudio.ui.reference_shell import ReferenceShellMixin
from molstudio.ui.studio_sidebar import CommandPalette, StudioSidebar


# ══════════════════════════════════════════════════════════════════════════ #
#  分组侧栏的蓝色主题皮肤
#
#  挂在 StudioSidebar **自己**的 styleSheet 后面：它的 _apply_style() 已经在
#  实例上设了一份中性灰 QSS，窗口级 QSS 顶不过内联样式（同一批老坑），
#  而且 _deferred_init 里 _apply_theme() 会重刷窗口 QSS，挂在窗口上会被冲掉。
# ══════════════════════════════════════════════════════════════════════════ #
BLUE_SIDEBAR_QSS = """
QFrame#StudioSidebar {
    background: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 8px;
}
QWidget#SidebarScrollBody { background: transparent; }
QScrollArea#SidebarScroll,
QScrollArea#SidebarScroll > QWidget > QWidget {
    background: transparent;
    border: none;
}
QToolButton#SidebarSearch {
    background: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
}
QToolButton#NavItem:checked {
    background-color: #E3F2FD;
    border-radius: 6px;
    color: #1565C0;
}
QFrame#SidebarSep { background: #E2E8F0; border: none; }
QLabel#SidebarVersion { color: #7C96B9; }
"""


class MolStudioClassicNavWindow(ReferenceShellMixin, OrbitalVisApp):
    """经典蓝色主题 + 分级侧栏 + 参考稿外壳；功能与 classic 完全一致。"""

    SIDEBAR_W = 232
    RAIL_W = 56

    def __init__(self):
        # 必须在 super().__init__()（内部建 UI + 延迟刷主题/语言）之前就位
        self._sidebar = None
        self._nav_card_old = None
        self._palette_shortcut = None
        self._rail_shortcut = None
        self._footer_moved = False
        self._page_group = {}
        super().__init__()
        # 画布在父类里随 UI 一起建好，等事件循环跑起来再压工具条（此时
        # CubStyleBar 已加入布局，能拿到真实父控件与尺寸）
        QTimer.singleShot(0, self._setup_canvas_bar)

    # ── 不覆写 _apply_theme()：完整保留 LIGHT_QSS 经典蓝色主题 ──────────

    def _setup_canvas_bar(self) -> None:
        """把画布底部那块 302px 的「一键样式 + 显示 + 导出」卡片压成 42px 单行。

        此前只有 studio 版装过紧凑工具条，classic_nav 一直在用原卡片，7 行 22 个
        控件把画布吃掉 302px。工具条实现在 ``studio_canvas_bar`` 里，安装失败
        就保持原样（不会开不了机）。
        """
        if getattr(self, "_canvas_bar_done", False):
            return
        try:
            from molstudio.ui.studio_canvas_bar import install_compact_canvas_bar
            bar = install_compact_canvas_bar(self)
        except Exception as e:      # noqa: BLE001
            print(f"[classic_nav] 画布工具条应用失败：{e}")
            bar = None
        if bar is not None:
            self._canvas_bar_done = True
            # 与 studio 同名，切语言/换主题时走同一套刷新路径
            self._studio_canvas_bar = bar

    def _setup_main_nav(self):
        """父类建好 main_nav + 全部联动后，把第 0 栏换成分组侧栏。"""
        super()._setup_main_nav()
        self._install_group_nav()

    def _install_group_nav(self):
        if self._sidebar is not None:
            return
        split = getattr(self, "_body_splitter", None)
        if split is None or split.count() < 3:
            return
        # 先记下经典版的三栏宽度：侧栏从 122 → 232 会多吃 110px，
        # 若让 QSplitter 按 4:5 自己摊，右栏会从 764 掉到 704，EDD 那行
        # 「用画框选中原子」立刻被裁（实测 121px / 需要 160px）。
        # 这里把这 110px 全部记在画布账上，右栏保持经典宽度不变。
        before = list(split.sizes())
        right_w = before[2] if len(before) >= 3 else 680
        total = sum(before) if before else split.width()
        sb = StudioSidebar()
        sb.pageRequested.connect(self._on_sidebar_page)
        sb.searchRequested.connect(self._open_palette)
        sb.railChanged.connect(self._on_rail_changed)
        old = split.replaceWidget(0, sb)
        if old is not None:
            self._nav_card_old = old
            try:
                old.setParent(self)     # 退出布局，但 main_nav 仍作状态模型
                old.hide()
            except Exception:
                pass
        self._sidebar = sb
        try:
            sb.show()                   # 插入时不可见会被 QSplitter 给 0 宽
            sb.setStyleSheet((sb.styleSheet() or "")
                             + "\n/* ClassicNav */\n" + BLUE_SIDEBAR_QSS)
            sb.set_bottom_text("MolStudio v1.0")
        except Exception:
            pass
        self._move_sidebar_footer()
        self._slim_topbar()
        self._rebuild_sidebar()
        try:
            canvas = max(360, total - self.SIDEBAR_W - right_w)
            sizes = [self.SIDEBAR_W, canvas, right_w]
            split.setSizes(sizes)
            if hasattr(split, "set_default_sizes"):
                split.set_default_sizes(list(sizes))
        except Exception:
            pass
        self._setup_shortcuts()
        # 参考稿外壳（顶栏 / 画布头 / 属性卡片 / 日志页签 / 状态栏 / 工具卡片）
        self._setup_reference_shell()
        # showEvent 之后父类还会刷一次主题/尺寸，补齐侧栏宽度与高亮
        QTimer.singleShot(0, self._sync_group_nav)

    def _move_sidebar_footer(self):
        """把顶栏的「路径设置 / 关于」搬到侧栏版本文字下方。

        直接 reparent **原按钮**，不新建转发按钮：这样
        ``clicked → _open_paths_dialog / _open_about_dialog`` 的连线、
        ``_apply_lang_ui()`` 的 setText / setToolTip、以及各处对
        ``self.btn_paths`` / ``self.btn_about`` 的引用全都继续有效。

        StudioSidebar 的 outer 布局顺序是 搜索 / 滚动区 / 分隔线 / 版本文字，
        ``addWidget`` 追加在最后，正好落在 "MolStudio v1.0" 下面。
        """
        sb = self._sidebar
        if sb is None or sb.layout() is None:
            return
        if getattr(self, "_footer_moved", False):
            return
        self._footer_moved = True
        lay = sb.layout()
        for btn in (getattr(self, "btn_paths", None),
                    getattr(self, "btn_about", None)):
            if btn is None:
                continue
            try:
                parent = btn.parentWidget()
                old_lay = parent.layout() if parent is not None else None
                if old_lay is not None:
                    old_lay.removeWidget(btn)
                btn.setParent(sb)
                # 顶部那行给的 150px 下限会把 232px 侧栏里的按钮挤成一小块；
                # 改成撑满，文字左右各留侧栏自带的 12px 边距即可。
                btn.setMinimumWidth(0)
                btn.setMaximumWidth(16777215)
                btn.setMinimumHeight(30)
                btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                lay.addWidget(btn)
                btn.show()
            except Exception as e:      # noqa: BLE001
                print(f"[classic-nav] 侧栏底部按钮搬运失败：{e}")
        # 「路径设置（Multiwfn&VMD）」原文在 232px 侧栏里会被裁掉一半，
        # 底部只显示短名，完整说明留在 tooltip（语言切换后同样压短）。
        self._apply_footer_labels()
        # rail（56px）下放不下文字按钮，跟版本文字一起收起
        self._sync_footer_rail()

    def _slim_topbar(self):
        """顶栏收掉「结构库 / PPT 3D」两个按钮（幂等，可重复调用）。

        结构库在侧栏「常用」组里已有专门的功能页，顶栏是重复入口：
        父类 ``_open_molecule_library()`` 本质就是切到 ``tab_library``，
        隐藏它一个功能都不丢。

        PPT 3D 不是功能页，侧栏没有替代品，所以把它挂进 ``Ctrl+K``
        命令面板（见 ``_palette_entries`` / ``_run_palette_action``），
        按钮隐藏后仍能照常导出 .glb。

        语言刷新（``_deferred_init → _apply_lang_ui``）会重写这两个按钮的
        文字和 tooltip，虽不会 ``show()``，但延迟主题刷新链路较长，
        所以 ``_apply_lang_ui()`` 与 ``showEvent`` 的延迟回调里各补一次，
        保证任何刷新顺序之后都仍是隐藏状态。
        """
        for btn in (getattr(self, "btn_molecule_library", None),
                    getattr(self, "btn_ppt3d", None)):
            if btn is not None and not btn.isHidden():
                try:
                    btn.hide()
                except Exception:
                    pass

    def _apply_footer_labels(self):
        en = getattr(self, "_lang", "zh") == "en"
        labels = (("Paths", "About MolStudio") if en
                  else ("路径设置", "关于 MolStudio"))
        tips = (self._tr("tab_paths"), self._tr("dlg_about_title"))
        for btn, text, tip in zip(
                (getattr(self, "btn_paths", None),
                 getattr(self, "btn_about", None)), labels, tips):
            if btn is None:
                continue
            try:
                btn.setText(text)
                btn.setToolTip(tip)
            except Exception:
                pass

    def _sync_footer_rail(self):
        sb = getattr(self, "_sidebar", None)
        if sb is None:
            return
        visible = not sb.is_rail()
        for btn in (getattr(self, "btn_paths", None),
                    getattr(self, "btn_about", None)):
            if btn is not None:
                try:
                    btn.setVisible(visible)
                except Exception:
                    pass

    # ── 分组数据（与 Studio 同一份 GROUP_DEFS，避免两套分组漂移） ────────
    def _group_title(self, gid):
        en = getattr(self, "_lang", "zh") == "en"
        for g, zh, e, _keys in GROUP_DEFS:
            if g == gid:
                return e if en else zh
        return "Other" if en else "其他"

    def _build_sidebar_groups(self):
        key2idx = {k: i for i, k in enumerate(self._tab_keys)}
        used = set()
        groups = []
        page_group = {}
        for gid, _zh, _en, keys in GROUP_DEFS:
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
            label = ("Other" if getattr(self, "_lang", "zh") == "en"
                     else "其他")
            groups.append((label, [{
                "index": i,
                "key": k,
                "text": self._tr(k),
                "icon": NAV_ICONS.get(k) or "cube",
            } for i, k in rest]))
            for i, _k in rest:
                page_group[i] = "other"
        self._page_group = page_group
        return groups

    def _rebuild_sidebar(self):
        if self._sidebar is None:
            return
        try:
            cur = self.tabs.currentIndex()
            self._sidebar.set_entries(self._build_sidebar_groups(), max(cur, 0))
            self._sidebar.set_current(max(cur, 0))
        except Exception as e:      # noqa: BLE001
            print(f"[classic-nav] 侧栏条目构建失败：{e}")

    # ── 与经典版状态模型联动 ────────────────────────────────────────────
    def _on_sidebar_page(self, index):
        """分组项点击 → 转发给 main_nav / tabs，保留经典版的切页副作用。"""
        nav = getattr(self, "main_nav", None)
        if nav is not None and 0 <= index < nav.count():
            if nav.currentRow() == index:
                self.tabs.setCurrentIndex(index)
            else:
                nav.setCurrentRow(index)
        else:
            self.tabs.setCurrentIndex(index)
        self._sync_group_nav()

    def _sync_main_nav(self):
        """语言刷新 / 切页时同步经典版导航，并补上分组侧栏高亮。"""
        super()._sync_main_nav()
        self._sync_group_nav()

    def _sync_group_nav(self):
        sb = self._sidebar
        if sb is None:
            return
        try:
            idx = max(self.tabs.currentIndex(), 0)
            sb.set_current(idx)
            sb.expand_group_of(idx)
            split = getattr(self, "_body_splitter", None)
            if split is not None and split.sizes():
                sizes = split.sizes()
                want = self.RAIL_W if sb.is_rail() else self.SIDEBAR_W
                if sizes[0] != want:
                    sizes[0] = want
                    split.setSizes(sizes)
        except Exception:
            pass

    def _apply_lang_ui(self):
        super()._apply_lang_ui()
        # 语言切换：分组标题与条目文字全部重建（不复用旧条目），
        # 父类会把两个底部按钮设回长名，这里再压回侧栏用的短名。
        self._rebuild_sidebar()
        self._apply_footer_labels()
        self._slim_topbar()

    # ── 附加功能入口 ────────────────────────────────────────────────────
    def _setup_shortcuts(self):
        if self._palette_shortcut is None:
            sc = QShortcut(QKeySequence("Ctrl+K"), self)
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(self._open_palette)
            self._palette_shortcut = sc
        if self._rail_shortcut is None:
            sc = QShortcut(QKeySequence("Ctrl+B"), self)
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(self._toggle_rail)
            self._rail_shortcut = sc

    def _toggle_rail(self):
        if self._sidebar is not None:
            self._sidebar.toggle_rail()

    def _on_rail_changed(self, rail):
        self._sync_footer_rail()
        self._sync_group_nav()

    def _palette_entries(self):
        """命令面板条目：27 个功能页 + 顶栏收起来的动作。

        ``CommandPalette`` 的 payload 允许 int 或 str；这里用 int 表示页序号，
        用 ``"ppt3d"`` 表示被隐藏的导出按钮。三元组第 3 项是附加搜索关键字，
        让中文 / 英文 / 扩展名都能搜到这个动作。
        """
        entries = [(self._tr(k), i)
                   for i, k in enumerate(self._tab_keys)]
        en = getattr(self, "_lang", "zh") == "en"
        entries.append((
            "Export PPT 3D (.glb)" if en else "PPT 3D 导出（可旋转 .glb）",
            "ppt3d",
            "ppt3d ppt 3d 导出 export glb powerpoint 365 可旋转模型",
        ))
        return entries

    def _run_palette_action(self, payload):
        """执行非功能页动作：目前只有被顶栏收起来的 PPT 3D 导出。

        不 ``btn.click()`` 而直接调原槽：隐藏按钮的 ``click()`` 在部分 Qt
        版本上依赖可见性，直接调槽更稳，且连线本来就只有这一个槽。
        """
        if payload == "ppt3d":
            self._export_current_ppt3d()
            return True
        return False

    def _open_palette(self):
        """Ctrl+K / 侧栏搜索：27 个功能页 + PPT 3D 导出动作。"""
        try:
            picked = CommandPalette(self._palette_entries(), self).pick()
            if picked is None:
                return
            if isinstance(picked, str):
                self._run_palette_action(picked)
            else:
                self._on_sidebar_page(int(picked))
        except Exception as e:      # noqa: BLE001
            print(f"[classic-nav] 命令面板打开失败：{e}")

    def showEvent(self, event):
        super().showEvent(event)
        if self._sidebar is not None:
            # 父类 _deferred_init 会重刷主题 / 语言，这里兜底再压一次顶栏
            QTimer.singleShot(120, self._sync_group_nav)
            QTimer.singleShot(140, self._slim_topbar)


def main():
    """独立启动入口：复用 main.py 的完整引导流程。"""
    os.environ["MOLSTUDIO_UI"] = "classic_nav"
    _canon = "molstudio.ui.main_window_classic_nav"
    if _canon not in sys.modules:
        sys.modules[_canon] = sys.modules[__name__]
    import molstudio.app as _main
    _main.main()


if __name__ == "__main__":
    main()
