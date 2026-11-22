# -*- coding: utf-8 -*-
"""reference_shell.py — MolStudio 默认界面的「参考布局」外壳
================================================================

2026-11-13：按参考稿（顶栏工具条 + 左侧分类栏 + 中间 3D 视图 + 右侧属性/设置
+ 底部 运行日志/计算输出/错误信息 + 状态栏）给默认界面做的一次布局升级。

实现方式：**不重写 main_window.py**，而是给 ``MolStudioClassicNavWindow``
混入这一层外壳（mixin 排在其 MRO 前面）。所有原有面板、信号、快捷键、
语言切换、拖放、画布逻辑一行都不动；这里只做三件事：

1. 把顶部「输入文件」条重排成参考稿的顶栏：品牌 + 文件 chip + 打开/截图/
   保存图片/测量/重置视角 + 语言/设置；
2. 在画布上方加「3D 视图」头，画布下方加可展开的四张工具卡片
   （渲染风格 / 显示设置 / 测量与分析 / 文件导出，由 canvas_cards_bar 提供）；
3. 右侧设置页顶部加「属性信息」卡片（quick_info + PropertyCard），底部日志
   换成「运行日志 / 计算输出 / 错误信息」三页签（runlog_tabs），窗口底部加
   状态栏（版本 / 状态 / CPU / 内存）。

所有新模块都用延迟导入 + try/except 包裹：任何一个可选模块缺失时界面照常
启动，只是少那一块，不影响既有功能。
"""

from __future__ import annotations

import os
import sys
import time

from PyQt5.QtCore import QEvent, QRectF, Qt, QTimer
from PyQt5.QtGui import QColor, QIcon, QPainter, QPen
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QStatusBar, QToolButton, QVBoxLayout, QWidget,
)

from molstudio.ui.theme import LIGHT_QSS

__all__ = ["ReferenceShellMixin", "REFERENCE_QSS"]


#: 参考稿风格的补充 QSS（追加在 LIGHT_QSS 之后；只作用于本外壳新增的
#: objectName，尽量不碰各分析面板自己的样式）
REFERENCE_QSS = """
QMainWindow { background: #F4F6FA; }
QFrame#RefTopBar {
    background: #FFFFFF;
    border: 1px solid #E5E9F0;
    border-radius: 12px;
}
QLabel#RefBrand {
    font-size: 16px;
    font-weight: 700;
    color: #111827;
}
QLabel#RefBrandVer { color: #94A3B8; font-size: 9pt; }
QLabel#RefBrandTag { color: #6B7280; font-size: 9pt; }
QPushButton#RefTool, QToolButton#RefTool {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 5px 10px;
    color: #374151;
    font-size: 9pt;
}
QPushButton#RefTool:hover, QToolButton#RefTool:hover {
    background: #EEF2F7;
}
QPushButton#RefTool:checked, QToolButton#RefTool:checked {
    background: #E3F2FD;
    border-color: #BFDBFE;
    color: #1565C0;
    font-weight: 600;
}
QFrame#RefTopBar QLineEdit {
    background: #FFFFFF;
    border: 1px solid #DDE3ED;
    border-radius: 8px;
    padding: 4px 10px;
    min-height: 24px;
    color: #1F2937;
}
QFrame#RefCanvasHeader { background: transparent; border: none; }
QLabel#RefCanvasTitle {
    color: #374151;
    font-size: 10pt;
    font-weight: 600;
}
QFrame#LogDock {
    background: #FFFFFF;
    border: 1px solid #E5E9F0;
    border-radius: 10px;
}
QFrame#RightCard {
    background: #FFFFFF;
    border: 1px solid #E5E9F0;
    border-radius: 12px;
}
QStatusBar {
    background: #FFFFFF;
    border-top: 1px solid #E5E9F0;
}
QStatusBar QLabel { color: #6B7280; font-size: 9pt; }
QLabel#RefStatusText { color: #374151; font-size: 9pt; }
QLabel#RefStatusDot { color: #22C55E; font-size: 10pt; }
QPushButton#PrimaryBtn {
    background: #2F6FEB;
    border: 1px solid #2F6FEB;
    color: #FFFFFF;
    font-weight: 600;
    border-radius: 8px;
}
QPushButton#PrimaryBtn:hover { background: #2563EB; }
"""

#: 新外壳的中英对照（与 i18n.TR 解耦，避免动共享词表）
_REF_TR = {
    "分子可视化与量子化学分析": "Molecular visualization & quantum chemistry analysis",
    "打开": "Open",
    "截图": "Snapshot",
    "保存图片": "Save image",
    "测量": "Measure",
    "重置视角": "Reset view",
    "3D 视图": "3D view",
    "工具": "Tools",
    "属性信息": "Properties",
    "获取并查看计算结果": "Load / refresh results",
    "载入 fchk / log / gjf / xyz 后自动刷新；右上角 ↻ 可手动刷新":
        "Refreshes automatically after loading fchk / log / gjf / xyz; "
        "click ↻ to refresh manually",
    "就绪": "Ready",
    "CPU": "CPU",
    "内存": "Memory",
    "版本": "Version",
}


class _RefTopBar(QFrame):
    """参考稿顶栏容器。

    main_window.py 的 ``_apply_lang_ui()`` 会无条件调用
    ``self.grp_input.setTitle(...)``；换成 QFrame 后补一个空实现，
    避免语言切换时抛 AttributeError。
    """

    def setTitle(self, *_args, **_kwargs):      # noqa: N802 - Qt 命名
        return None


class _CardBorderOverlay(QWidget):
    """卡片最上层的 1px 圆角描边（画布卡片专用）。

    背景：``grp_canvas`` 是 QWidget + QSS（白色圆角 + 1px 描边），但里面的
    GL 画布 / 工具条会把自己的白底画满子控件矩形，把父级的**左右两条描边
    整条盖住**——实测卡片只剩上边一条线，左右边缘看不见，看起来就像"画布
    超出了卡片范围"（2026-11-21 反馈）。

    父级的 ``paintEvent`` 永远在子控件之前画，所以描边只能放在最上层：这是一块
    覆盖整张卡片、不吃鼠标、只画 1px 圆角线的透明子控件；父级尺寸一变就跟着
    重设几何并重新 ``raise_()``，保证它始终压在 GL 画布之上。
    """

    def __init__(self, parent, radius: int = 12, color: str = "#E5E9F0"):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self._radius = int(radius)
        self._color = QColor(color)
        self.setGeometry(parent.rect())
        parent.installEventFilter(self)
        # 本控件是在窗口 show() 之后才建的（延迟初始化），不会自动跟随父级显示
        self.show()
        self.raise_()

    def eventFilter(self, obj, ev):
        try:
            if obj is self.parentWidget() and ev.type() in (
                    QEvent.Resize, QEvent.Show, QEvent.LayoutRequest):
                self.setGeometry(obj.rect())
                self.raise_()
        except Exception:
            pass
        return super().eventFilter(obj, ev)

    def paintEvent(self, ev):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setPen(QPen(self._color, 1))
            p.setBrush(Qt.NoBrush)
            r = self._radius
            p.drawRoundedRect(
                QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), r, r)
        finally:
            p.end()


class ReferenceShellMixin:
    """给默认界面套上参考稿布局（见模块 docstring）。"""

    def _ref_t(self, zh):
        en = getattr(self, "_lang", "zh") == "en"
        return _REF_TR.get(zh, zh) if en else zh

    # ── 入口：由 _install_group_nav() 末尾调用（此时全部控件已建好）──
    def _setup_reference_shell(self):
        if getattr(self, "_ref_shell_ready", False):
            return
        self._ref_shell_ready = True
        self._ref_props = None
        self._ref_prop_page = None
        self._ref_prop_load_btn = None
        self._ref_prop_hint = None
        self._ref_log_console = None
        self._ref_cards = None
        self._ref_cards_btn = None
        self._ref_canvas_header = None
        self._ref_status_text = None
        self._ref_status_dot = None
        self._ref_cpu_label = None
        self._ref_mem_label = None
        self._ref_cpu_prev = None
        self._ref_tool_buttons = {}
        for step in (
                self._restyle_reference_topbar,
                self._install_canvas_header,
                self._install_property_card,
                self._install_runlog_console,
                self._install_canvas_cards,
                self._install_statusbar,
        ):
            try:
                step()
            except Exception as exc:                     # noqa: BLE001
                print("[reference-shell] %s 失败：%s" % (
                    getattr(step, "__name__", step), exc))
        try:
            self._apply_reference_theme()
        except Exception as exc:                         # noqa: BLE001
            print("[reference-shell] 主题刷新失败：%s" % exc)
        try:
            self._refresh_property_card()
        except Exception:                                # noqa: BLE001
            pass

    # ── 顶栏 ──────────────────────────────────────────────────────────
    def _restyle_reference_topbar(self):
        """把父类那块「输入文件」大面板换成参考稿的顶栏。"""
        old = getattr(self, "grp_input", None)
        if old is None:
            return
        parent = old.parentWidget()
        parent_lay = parent.layout() if parent is not None else None
        if parent_lay is None:
            return

        bar = _RefTopBar()
        bar.setObjectName("RefTopBar")
        bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        h = QHBoxLayout(bar)
        h.setContentsMargins(12, 7, 12, 7)
        h.setSpacing(8)

        # 品牌：图标 + 名称 + 定位语
        brand = QHBoxLayout()
        brand.setContentsMargins(0, 0, 0, 0)
        brand.setSpacing(7)
        icon_lbl = QLabel()
        try:
            from molstudio import paths as _paths
            from PyQt5.QtGui import QPixmap

            icon_path = _paths.find_asset(
                "OV.png", "molstudio.ico", "gxnu_molstudio.ico")
            if icon_path:
                pm = QPixmap(icon_path)
                if not pm.isNull():
                    icon_lbl.setPixmap(pm.scaled(
                        24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception:                                # noqa: BLE001
            pass
        if icon_lbl.pixmap() is None:
            icon_lbl.setText("⬡")
            icon_lbl.setStyleSheet("font-size:16px;color:#2F6FEB;")
        brand.addWidget(icon_lbl)
        title = QLabel("MolStudio")
        title.setObjectName("RefBrand")
        brand.addWidget(title)
        ver = QLabel("v1.0")
        ver.setObjectName("RefBrandVer")
        brand.addWidget(ver)
        tag = QLabel(self._ref_t("分子可视化与量子化学分析"))
        tag.setObjectName("RefBrandTag")
        self._ref_brand_tag = tag
        brand.addWidget(tag)
        h.addLayout(brand)

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color:#E5E9F0;")
        h.addWidget(sep)

        # 文件 chip：沿用原 var_path（拖放、占位提示、语言刷新都照旧）
        var_path = getattr(self, "var_path", None)
        if var_path is not None:
            try:
                var_path.setParent(bar)
                var_path.setMinimumWidth(220)
                var_path.setMaximumHeight(30)
                var_path.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                h.addWidget(var_path, 1)
            except Exception:                            # noqa: BLE001
                pass

        # 打开（复用原浏览按钮，保留全部拖放/浏览逻辑）
        btn_open = getattr(self, "btn_browse_input", None)
        if btn_open is not None:
            try:
                btn_open.setParent(bar)
                btn_open.setObjectName("RefTool")
                btn_open.setText(self._ref_t("打开"))
                h.addWidget(btn_open)
                self._ref_tool_buttons["open"] = btn_open
            except Exception:                            # noqa: BLE001
                pass

        # 画布工具：截图 / 保存图片 / 测量 / 重置视角
        self._ref_snapshot_btn = self._find_canvas_button(
            ("截图", "Snapshot", "Snap"))
        self._ref_export_btn = self._find_canvas_button(
            ("导出图片", "Export image", "Export Image"))
        _cub = getattr(self, "cub_canvas", None)
        self._ref_measure_btn = (getattr(_cub, "_measure_btn", None)
                                 if _cub is not None else None)
        self._ref_reset_btn = self._find_canvas_button(("重置视角", "Reset"))

        for key, text, tip, callback in (
                ("snapshot", "截图", "截取当前画布",
                 lambda: self._click_canvas_button(self._ref_snapshot_btn)),
                ("export", "保存图片", "导出当前画布图片",
                 lambda: self._click_canvas_button(self._ref_export_btn)),
                ("measure", "测量", "距离 / 角度 / 二面角测量",
                 self._toggle_measure_mode),
                ("reset", "重置视角", "把分子重新居中到画布",
                 self._reset_canvas_view),
        ):
            btn = QPushButton(self._ref_t(text))
            btn.setObjectName("RefTool")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(tip)
            if key == "measure":
                btn.setCheckable(True)
                btn.setChecked(bool(getattr(self._ref_measure_btn, "isChecked",
                                            lambda: False)()))
            btn.clicked.connect(callback)
            h.addWidget(btn)
            self._ref_tool_buttons[key] = btn
        # 测量按钮与原按钮状态双向同步
        try:
            if self._ref_measure_btn is not None:
                self._ref_measure_btn.toggled.connect(
                    lambda on: self._ref_tool_buttons["measure"].setChecked(on))
        except Exception:                                # noqa: BLE001
            pass

        # 独立 ORCA 本机计算模块（弹窗；先不并入轨道/ESP 等分析页）
        orca_btn = QPushButton("ORCA")
        orca_btn.setObjectName("RefTool")
        orca_btn.setCursor(Qt.PointingHandCursor)
        orca_btn.setToolTip("打开左侧「常用 → ORCA 计算」页")
        orca_btn.clicked.connect(self._open_orca_dialog)
        h.addWidget(orca_btn)
        self._ref_orca_btn = orca_btn

        h.addStretch(1)
        # 语言（沿用原按钮） / 设置齿轮
        lang_btn = getattr(self, "_lang_btn", None)
        if lang_btn is not None:
            try:
                lang_btn.setParent(bar)
                lang_btn.setObjectName("RefTool")
                h.addWidget(lang_btn)
            except Exception:                            # noqa: BLE001
                pass
        gear = QToolButton()
        gear.setObjectName("RefTool")
        gear.setText("⚙")
        gear.setToolTip(self._tr("tab_paths") if hasattr(self, "_tr") else "路径设置")
        gear.setCursor(Qt.PointingHandCursor)
        gear.clicked.connect(self._open_paths_dialog)
        h.addWidget(gear)
        self._ref_gear = gear

        # 插到原位置；旧面板从布局里摘掉但保留对象（其他代码仍持有其子控件）
        # 注意：必须留一个强引用，否则 Python 侧 wrapper 被回收时 Qt 会把
        # 「结构库 / PPT 3D」这些按钮一起删掉（语言刷新链路会访问它们）。
        self._ref_legacy_topbar = old
        try:
            idx = parent_lay.indexOf(old)
            if idx < 0:
                idx = parent_lay.count()
            parent_lay.insertWidget(idx, bar)
            parent_lay.removeWidget(old)
            old.hide()
        except Exception:                                # noqa: BLE001
            try:
                parent_lay.addWidget(bar)
                old.hide()
            except Exception:                            # noqa: BLE001
                return
        self.grp_input = bar
        self._ref_topbar = bar

    def _open_orca_dialog(self):
        """定位到左侧「常用 → ORCA 计算」页；没有该页时退回独立弹窗。"""
        try:
            idx = self._tab_keys.index("tab_orca")
            self._on_sidebar_page(idx)
            return
        except Exception:                                # noqa: BLE001
            pass
        try:
            from molstudio.panels.orca_local_dialog import open_orca_dialog
        except Exception as exc:                         # noqa: BLE001
            print("[reference-shell] ORCA 弹窗不可用：%s" % exc)
            return
        path = ""
        try:
            path = self.var_path.text().strip()
        except Exception:                                # noqa: BLE001
            path = ""
        if not path:
            path = getattr(self, "_current_fchk", "") or ""
        try:
            open_orca_dialog(parent=self, lang=getattr(self, "_lang", "zh"),
                             initial_path=path)
        except Exception as exc:                         # noqa: BLE001
            print("[reference-shell] 打开 ORCA 弹窗失败：%s" % exc)

    def _find_canvas_button(self, words):
        """在 CubStyleBar 原卡片里按文字找按钮（截图/导出图片/重置视角）。"""
        cub = getattr(self, "cub_canvas", None)
        if cub is None:
            return None
        try:
            for btn in cub.findChildren(QPushButton):
                text = btn.text() or ""
                if any(w in text for w in words):
                    return btn
        except Exception:                                # noqa: BLE001
            pass
        return None

    @staticmethod
    def _click_canvas_button(btn):
        if btn is None:
            return
        try:
            btn.click()
        except Exception:                                # noqa: BLE001
            pass

    def _toggle_measure_mode(self, checked=False):
        btn = getattr(self, "_ref_measure_btn", None)
        if btn is None:
            return
        try:
            if bool(btn.isChecked()) != bool(checked):
                btn.click()
        except Exception:                                # noqa: BLE001
            pass

    def _reset_canvas_view(self):
        btn = getattr(self, "_ref_reset_btn", None)
        if btn is not None:
            try:
                btn.click()
                return
            except Exception:                            # noqa: BLE001
                pass
        glw = getattr(getattr(self, "cub_canvas", None), "glw", None)
        if glw is not None:
            try:
                glw.frame_to_molecule()
            except Exception:                            # noqa: BLE001
                pass

    # ── 画布上方「3D 视图」头 ──────────────────────────────────────────
    def _install_canvas_header(self):
        canvas = getattr(self, "grp_canvas", None)
        lay = canvas.layout() if canvas is not None else None
        if lay is None:
            return
        # 画布整体做成参考稿里的白色圆角卡片
        try:
            canvas.setObjectName("RefCanvasCard")
            canvas.setStyleSheet(
                "QWidget#RefCanvasCard{background:#FFFFFF;"
                "border:1px solid #E5E9F0;border-radius:12px;}")
        except Exception:                                # noqa: BLE001
            pass
        header = QFrame()
        header.setObjectName("RefCanvasHeader")
        h = QHBoxLayout(header)
        h.setContentsMargins(8, 0, 8, 0)
        h.setSpacing(8)
        title = QLabel("◫  " + self._ref_t("3D 视图"))
        title.setObjectName("RefCanvasTitle")
        self._ref_canvas_title = title
        h.addWidget(title)
        h.addStretch(1)
        reset = QPushButton(self._ref_t("重置视角"))
        reset.setObjectName("RefTool")
        reset.setCursor(Qt.PointingHandCursor)
        reset.clicked.connect(self._reset_canvas_view)
        h.addWidget(reset)
        self._ref_cards_btn = QPushButton(self._ref_t("工具") + " ▾")
        self._ref_cards_btn.setObjectName("RefTool")
        self._ref_cards_btn.setCursor(Qt.PointingHandCursor)
        self._ref_cards_btn.setCheckable(True)
        self._ref_cards_btn.clicked.connect(self._toggle_canvas_cards)
        h.addWidget(self._ref_cards_btn)
        lay.insertWidget(0, header)
        self._ref_canvas_header = header
        # 最上层补一条 1px 圆角描边：GL 画布会把父级 QSS 的左右描边盖掉
        try:
            self._ref_canvas_border = _CardBorderOverlay(canvas, 12, "#E5E9F0")
            self._ref_canvas_border.raise_()
        except Exception:                                # noqa: BLE001
            self._ref_canvas_border = None

    # ── 画布下方四张工具卡片（可选模块）──────────────────────────────
    #: 画布列只有 ~540px，四张卡片并排时每个按钮只有 ~52px；
    #: 原控件文字（HoukMol3d / 导出图片 …）放不下，这里用短标签，完整名留 tooltip。
    _CARD_SHORT_LABELS = {
        "sob-art": "sob", "HoukMol3d": "Houk", "2D 平涂": "2D",
        "IQmol": "IQmol",
        "隐藏氢原子": "隐藏H", "隐藏氢": "隐藏H",
        "显示原子": "原子", "显示元素": "元素",
        "原子符号": "原子", "元素符号": "元素",
        "透明背景": "透明", "透明": "透明", "保留 H 编号": "H 编号",
        "距离": "距离", "键角": "键角", "二面角": "二面角",
        "测量开关": "测量", "清除测量": "清除", "表面分析": "表面",
        "截图": "截图", "导出图片": "图片", "3D 模型": "3D", "更多导出": "更多",
        "更多": "更多",
    }
    _CARD_SHORT_LABELS_EN = {
        "Snapshot": "Snap", "Export Image": "Image", "Save image": "Image",
        "Hide H": "HideH", "Hide hydrogens": "HideH",
        "Atom numbers": "Numbers", "Atom symbols": "Symbol",
        "Element symbols": "Element",
        "Transparent background": "Transp.", "Keep H numbers": "H nums",
        "Measurement": "Measure", "Distance": "Dist.", "Angle": "Angle",
        "Dihedral": "Dihed.", "Surface analysis": "Surface",
        "3D model": "3D", "3D Model": "3D", "More": "More",
    }

    def _compact_card_labels(self):
        """把卡片按钮的文字压成短标签（完整文字进 tooltip）。"""
        cards = getattr(self, "_ref_cards", None)
        if cards is None:
            return
        table = dict(self._CARD_SHORT_LABELS)
        if getattr(self, "_lang", "zh") == "en":
            table.update(self._CARD_SHORT_LABELS_EN)
        try:
            for card, _grid, _btns in getattr(cards, "_cards", {}).values():
                for btn in card.findChildren(QToolButton):
                    text = btn.text() or ""
                    short = table.get(text)
                    if short is None and len(text) > 5:
                        short = text[:4]
                    if short and short != text:
                        if not btn.toolTip():
                            btn.setToolTip(text)
                        btn.setText(short)
                    # 卡片只有 52px 宽：图标会再吃掉 18px，一律只留文字
                    try:
                        btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
                        btn.setIcon(QIcon())
                    except Exception:                    # noqa: BLE001
                        pass
        except Exception:                                # noqa: BLE001
            pass

    def _install_canvas_cards(self):
        if getattr(self, "_ref_cards", None) is not None:
            return
        try:
            from molstudio.ui.canvas_cards_bar import install_canvas_cards
        except Exception as exc:                         # noqa: BLE001
            print("[reference-shell] 工具卡片模块不可用：%s" % exc)
            return
        cards = install_canvas_cards(self)
        if cards is None:
            return
        self._ref_cards = cards
        # 默认收起（保留经典 42px 紧凑条与画布高度）；顶栏「工具 ▾」展开四张卡片
        try:
            cards.setVisible(False)
            btn = getattr(self, "_ref_cards_btn", None)
            if btn is not None:
                btn.setChecked(False)
                btn.setText(self._ref_t("工具") + "  ▾")
        except Exception:                                # noqa: BLE001
            pass
        self._compact_card_labels()

    def _toggle_canvas_cards(self, checked=False):
        cards = getattr(self, "_ref_cards", None)
        if cards is None:
            self._install_canvas_cards()
            cards = getattr(self, "_ref_cards", None)
        if cards is None:
            return
        want = bool(checked)
        cards.setVisible(want)
        # 展开时把 42px 紧凑工具条收起来（两套入口不重复占位）；收起时恢复
        bar = getattr(self, "_studio_canvas_bar", None)
        if bar is not None:
            try:
                bar.setVisible(not want)
            except Exception:                            # noqa: BLE001
                pass
        btn = getattr(self, "_ref_cards_btn", None)
        if btn is not None:
            btn.setText(self._ref_t("工具") + ("  ▴" if want else "  ▾"))
            btn.setChecked(want)
        if want:
            self._compact_card_labels()

    # ── 右侧「属性信息」独立页签（可选模块）──────────────────────────
    def _install_property_card(self):
        if getattr(self, "_ref_props", None) is not None:
            return
        try:
            from molstudio.ui.property_card import PropertyCard
        except Exception as exc:                         # noqa: BLE001
            print("[reference-shell] 属性卡片模块不可用：%s" % exc)
            return
        right_tabs = getattr(self, "right_tabs", None)
        if right_tabs is not None and hasattr(right_tabs, "insertTab"):
            # 独立页签：属性信息 | 设置 | 引文
            page = QScrollArea()
            page.setObjectName("PropertyPage")
            page.setWidgetResizable(True)
            page.setFrameShape(QFrame.NoFrame)
            page.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            page.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            try:
                page.setStyleSheet(
                    "QScrollArea#PropertyPage{background:transparent;"
                    "border:none;}"
                    "QScrollArea#PropertyPage > QWidget > QWidget"
                    "{background:transparent;}")
            except Exception:                            # noqa: BLE001
                pass
            body = QWidget()
            body_lay = QVBoxLayout(body)
            body_lay.setContentsMargins(8, 8, 8, 8)
            body_lay.setSpacing(8)
            # 参考稿顶部的「获取并查看计算结果」主按钮
            self._ref_prop_load_btn = QPushButton(
                self._ref_t("获取并查看计算结果"))
            self._ref_prop_load_btn.setObjectName("PrimaryBtn")
            self._ref_prop_load_btn.setMinimumHeight(34)
            self._ref_prop_load_btn.setCursor(Qt.PointingHandCursor)
            self._ref_prop_load_btn.clicked.connect(
                self._on_property_load_clicked)
            body_lay.addWidget(self._ref_prop_load_btn)
            card = PropertyCard(body)
            card.setObjectName("PropertyCard")
            body_lay.addWidget(card)
            hint = QLabel(
                self._ref_t("载入 fchk / log / gjf / xyz 后自动刷新；"
                            "右上角 ↻ 可手动刷新"))
            hint.setWordWrap(True)
            hint.setStyleSheet("color:#6B7280;font-size:9pt;")
            self._ref_prop_hint = hint
            body_lay.addWidget(hint)
            body_lay.addStretch(1)
            page.setWidget(body)
            try:
                card.refreshRequested.connect(self._refresh_property_card)
            except Exception:                            # noqa: BLE001
                pass
            right_tabs.insertTab(0, page, self._ref_t("属性信息"))
            # 默认仍停在「设置」页，属性信息点一下就到
            try:
                right_tabs.setCurrentIndex(1)
            except Exception:                            # noqa: BLE001
                pass
            # 切到属性信息页时自动刷新（DI 本机流程等不经过主画布载入，
            # 只改「过渡态 log」输入框的场景也能显示属性）
            try:
                right_tabs.currentChanged.connect(self._on_right_tab_changed)
            except Exception:                            # noqa: BLE001
                pass
            self._ref_prop_page = page
            self._ref_props = card
            try:
                self._refresh_right_tab_texts()
            except Exception:                            # noqa: BLE001
                pass
            return
        # 兜底：右侧没有页签容器时，仍把卡片放在设置页顶部
        right_card = getattr(self, "right_card", None)
        if right_card is None or right_card.layout() is None:
            return
        card = PropertyCard(right_card)
        card.setObjectName("PropertyCard")
        try:
            card.refreshRequested.connect(self._refresh_property_card)
        except Exception:                                # noqa: BLE001
            pass
        try:
            rlay = right_card.layout()
            rlay.setContentsMargins(8, 8, 8, 8)
            rlay.setSpacing(8)
        except Exception:                                # noqa: BLE001
            pass
        right_card.layout().insertWidget(0, card)
        self._ref_props = card

    def _refresh_right_tab_texts(self):
        """右侧页签：属性信息 / 设置 / 引文（兼容外壳安装前的两页签状态）。"""
        tabs = getattr(self, "right_tabs", None)
        if tabs is None:
            return
        try:
            if tabs.count() >= 3:
                texts = [self._ref_t("属性信息"),
                         self._tr("right_tab_settings"),
                         self._tr("right_tab_cite")]
            else:
                texts = [self._tr("right_tab_settings"),
                         self._tr("right_tab_cite")]
            for i, text in enumerate(texts):
                if i < tabs.count():
                    tabs.setTabText(i, text)
        except Exception:                                # noqa: BLE001
            pass

    def _ref_settings_tab_index(self):
        """「设置」页在右侧页签里的下标（属性信息插到 0 后不再是 0）。"""
        tabs = getattr(self, "right_tabs", None)
        if tabs is None:
            return 0
        card = getattr(self, "right_card", None)
        if card is not None:
            try:
                idx = tabs.indexOf(card)
                if idx >= 0:
                    return idx
            except Exception:                            # noqa: BLE001
                pass
        return 1 if tabs.count() >= 2 else 0

    def _sync_right_tab_bar(self, key=None):
        """结构库页要显示它自己的四页签 → 右侧全局页签栏隐藏、并回到「设置」页。

        父类写死了 ``right_tabs.setCurrentIndex(0)``（那时 0 就是设置页）。
        现在 0 号页签是「属性信息」，直接沿用它会让结构库页停在属性页、
        页面栈整个被盖住 —— 也就是「结构库没了」。这里按 right_card 的实际
        下标切回设置页。
        """
        super()._sync_right_tab_bar(key)
        tabs = getattr(self, "right_tabs", None)
        if tabs is None:
            return
        if key is None:
            try:
                idx = self.tabs.currentIndex()
                key = (self._tab_keys[idx]
                       if 0 <= idx < len(self._tab_keys) else "")
            except Exception:                            # noqa: BLE001
                key = ""
        if key == "tab_library":
            try:
                tabs.setCurrentIndex(self._ref_settings_tab_index())
            except Exception:                            # noqa: BLE001
                pass

    def _on_property_load_clicked(self):
        """「获取并查看计算结果」：有文件就重读，没有就打开文件对话框。"""
        path = ""
        try:
            path = self.var_path.text().strip()
        except Exception:                                # noqa: BLE001
            path = ""
        if not path or not os.path.isfile(path):
            try:
                self._browse_input()
                return
            except Exception:                            # noqa: BLE001
                return
        self._refresh_property_card()

    def _on_right_tab_changed(self, index):
        try:
            if index == 0:                               # 属性信息页
                self._refresh_property_card()
        except Exception:                                # noqa: BLE001
            pass

    def _refresh_property_card(self, *_args):
        card = getattr(self, "_ref_props", None)
        if card is None:
            return
        path = (getattr(self, "var_path", None).text().strip()
                if getattr(self, "var_path", None) is not None else "")
        if not path:
            path = getattr(self, "_current_fchk", "") or ""
        if not path:
            # DI 本机流程只填了 DI 面板的「过渡态 log」输入框，没有走主画布载入
            di = getattr(self, "di_panel", None)
            try:
                if di is not None and hasattr(di, "_file_edits"):
                    path = di._file_edits["ts"].text().strip()
            except Exception:                            # noqa: BLE001
                path = ""
        try:
            card.set_lang(getattr(self, "_lang", "zh"))
        except Exception:                                # noqa: BLE001
            pass
        if not path or not os.path.isfile(path):
            try:
                card.clear()
            except Exception:                            # noqa: BLE001
                pass
            return
        try:
            from molstudio.core.quick_info import quick_info
            info = quick_info(path)
            card.set_info(info)
        except Exception as exc:                         # noqa: BLE001
            print("[reference-shell] 属性信息解析失败：%s" % exc)

    # ── 底部日志三页签（可选模块）─────────────────────────────────────
    def _install_runlog_console(self):
        if getattr(self, "_ref_log_console", None) is not None:
            return
        dock = getattr(self, "log_dock", None)
        log_text = getattr(self, "log_text", None)
        if dock is None or log_text is None or dock.layout() is None:
            return
        try:
            from molstudio.ui.runlog_tabs import RunLogConsole
        except Exception as exc:                         # noqa: BLE001
            print("[reference-shell] 日志页签模块不可用：%s" % exc)
            return
        try:
            dock.setStyleSheet(
                "QFrame#LogDock{background:#FFFFFF;border:1px solid #E5E9F0;"
                "border-radius:10px;}")
            lay = dock.layout()
            lay.removeWidget(log_text)
            console = RunLogConsole(log_text, parent=dock)
            lay.addWidget(console, 1)
            # 让日志正文在页签里自动撑高（父类曾给它固定 144px 高）
            log_text.setMinimumHeight(0)
            log_text.setMaximumHeight(16777215)
            # 改由拖动条统一控制高度（默认 144px），别让它撑满整块 dock
            try:
                self._apply_log_body_height(getattr(self, "_log_body_h", 144))
            except Exception:                        # noqa: BLE001
                pass
            # 参考稿的日志头只有页签 + 右侧过滤控件：父类那条「运行日志 / 清空」
            # 标题条与页签重复。折叠按钮已经挪到画布与日志之间的拖动条上
            # （main_window._LogDockGrip），标题条整条隐掉，不再留一行空白。
            try:
                self._log_title.hide()
                self._log_clear_btn.hide()
                head = getattr(self, "_log_dock_head", None)
                if head is not None:
                    head.hide()
            except Exception:                            # noqa: BLE001
                pass
            # 小工具按钮统一固定宽度，别被工具栏的 stretch 拉成一长条
            try:
                for btn in (console.auto_scroll_btn, console.clear_btn,
                            console.copy_btn, console.save_btn):
                    btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
                    btn.setMaximumWidth(96)
            except Exception:                            # noqa: BLE001
                pass
            # 高度上限不再写死 248px：日志高度改由拖动条（_LogDockGrip）控制，
            # 这里的硬上限会把用户拖出来的高度又切回去。
            try:
                dock.setMaximumHeight(16777215)
            except Exception:                            # noqa: BLE001
                pass
            self._ref_log_console = console
            try:
                console.set_lang(getattr(self, "_lang", "zh"))
            except Exception:                            # noqa: BLE001
                pass
        except Exception as exc:                         # noqa: BLE001
            print("[reference-shell] 日志页签安装失败：%s" % exc)

    # ── 状态栏 ────────────────────────────────────────────────────────
    def _install_statusbar(self):
        if getattr(self, "_ref_statusbar", None) is not None:
            return
        sb = QStatusBar(self)
        sb.setSizeGripEnabled(False)
        self.setStatusBar(sb)
        ver = QLabel("MolStudio v1.0")
        sb.addWidget(ver)
        dot = QLabel("●")
        dot.setObjectName("RefStatusDot")
        sb.addWidget(dot)
        text = QLabel(self._ref_t("就绪"))
        text.setObjectName("RefStatusText")
        sb.addWidget(text)
        self._ref_status_dot = dot
        self._ref_status_text = text
        self._ref_statusbar = sb
        cpu = QLabel(self._ref_t("CPU") + " —")
        mem = QLabel(self._ref_t("内存") + " —")
        cpu.setContentsMargins(0, 0, 14, 0)
        mem.setContentsMargins(0, 0, 8, 0)
        sb.addPermanentWidget(cpu)
        sb.addPermanentWidget(mem)
        self._ref_cpu_label = cpu
        self._ref_mem_label = mem
        self._ref_ver_label = ver
        timer = QTimer(self)
        timer.timeout.connect(self._update_status_resources)
        timer.start(2000)
        self._ref_res_timer = timer
        self._update_status_resources()

    def _update_status_resources(self):
        cpu, mem = self._read_cpu_mem()
        if self._ref_cpu_label is not None:
            self._ref_cpu_label.setText(
                self._ref_t("CPU") + (" %d%%" % cpu if cpu is not None else " —"))
        if self._ref_mem_label is not None:
            self._ref_mem_label.setText(
                self._ref_t("内存")
                + (" %.1f GB" % mem if mem is not None else " —"))

    def _read_cpu_mem(self):
        """Windows 下用 kernel32 读 CPU 占用与已用物理内存；其他平台返回 (None, None)。"""
        if os.name != "nt":
            return None, None
        try:
            import ctypes
            from ctypes import wintypes

            class FILETIME(ctypes.Structure):
                _fields_ = [("dwLowDateTime", wintypes.DWORD),
                            ("dwHighDateTime", wintypes.DWORD)]

            idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
            ctypes.windll.kernel32.GetSystemTimes(
                ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))

            def _ft(f):
                return ((int(f.dwHighDateTime) << 32)
                        | int(f.dwLowDateTime)) & 0xFFFFFFFFFFFFFFFF

            now = (_ft(idle), _ft(kernel), _ft(user))
            prev = getattr(self, "_ref_cpu_prev", None)
            self._ref_cpu_prev = now
            cpu = None
            if prev is not None:
                d_idle = now[0] - prev[0]
                d_kernel = now[1] - prev[1]
                d_user = now[2] - prev[2]
                total = d_kernel + d_user
                if total > 0:
                    cpu = int(max(0, min(100, 100 * (total - d_idle) / total)))

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", wintypes.DWORD),
                    ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            ms = MEMORYSTATUSEX()
            ms.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
            used = (float(ms.ullTotalPhys) - float(ms.ullAvailPhys)) / (1024.0 ** 3)
            return cpu, used
        except Exception:                                # noqa: BLE001
            return None, None

    # ── 主题 ──────────────────────────────────────────────────────────
    def _apply_reference_theme(self):
        try:
            self.setStyleSheet(LIGHT_QSS + "\n/* ReferenceShell */\n" + REFERENCE_QSS)
        except Exception:                                # noqa: BLE001
            pass

    def _apply_theme(self):                             # override
        self._apply_reference_theme()

    # ── 语言刷新 ──────────────────────────────────────────────────────
    def _apply_lang_ui(self):
        super()._apply_lang_ui()
        try:
            zh = getattr(self, "_lang", "zh") == "zh"
            tag = getattr(self, "_ref_brand_tag", None)
            if tag is not None:
                tag.setText(self._ref_t("分子可视化与量子化学分析"))
            title = getattr(self, "_ref_canvas_title", None)
            if title is not None:
                title.setText("◫  " + self._ref_t("3D 视图"))
            for key, text in (
                    ("open", "打开"), ("snapshot", "截图"),
                    ("export", "保存图片"), ("measure", "测量"),
                    ("reset", "重置视角")):
                btn = self._ref_tool_buttons.get(key)
                if btn is not None:
                    btn.setText(self._ref_t(text))
            cards_btn = getattr(self, "_ref_cards_btn", None)
            if cards_btn is not None:
                show = bool(cards_btn.isChecked())
                cards_btn.setText(self._ref_t("工具") + ("  ▴" if show else "  ▾"))
            props = getattr(self, "_ref_props", None)
            if props is not None:
                try:
                    props.set_lang(getattr(self, "_lang", "zh"))
                except Exception:                        # noqa: BLE001
                    pass
            load_btn = getattr(self, "_ref_prop_load_btn", None)
            if load_btn is not None:
                load_btn.setText(self._ref_t("获取并查看计算结果"))
            prop_hint = getattr(self, "_ref_prop_hint", None)
            if prop_hint is not None:
                prop_hint.setText(self._ref_t(
                    "载入 fchk / log / gjf / xyz 后自动刷新；"
                    "右上角 ↻ 可手动刷新"))
            console = getattr(self, "_ref_log_console", None)
            if console is not None:
                try:
                    console.set_lang(getattr(self, "_lang", "zh"))
                except Exception:                        # noqa: BLE001
                    pass
            cards = getattr(self, "_ref_cards", None)
            if cards is not None:
                try:
                    cards.set_lang(getattr(self, "_lang", "zh"))
                except Exception:                        # noqa: BLE001
                    pass
                try:
                    self._compact_card_labels()
                except Exception:                        # noqa: BLE001
                    pass
            if self._ref_status_text is not None:
                self._ref_status_text.setText(
                    self._ref_t("就绪") if not self._ref_status_text.text()
                    else self._ref_status_text.text())
            # 顶栏「打开」按钮：父类会把它写成「浏览」，这里改回工具语义
            btn_open = getattr(self, "btn_browse_input", None)
            if btn_open is not None and getattr(self, "_ref_topbar", None) is not None:
                try:
                    btn_open.setText(self._ref_t("打开"))
                except Exception:                        # noqa: BLE001
                    pass
        except Exception as exc:                         # noqa: BLE001
            print("[reference-shell] 语言刷新失败：%s" % exc)

    # ── 父类钩子增强 ──────────────────────────────────────────────────
    def _load_molecule(self, path):
        super()._load_molecule(path)
        try:
            self._refresh_property_card()
        except Exception:                                # noqa: BLE001
            pass

    def _append_log(self, msg):
        super()._append_log(msg)
        console = getattr(self, "_ref_log_console", None)
        if console is not None:
            try:
                console.notify(str(msg))
            except Exception:                            # noqa: BLE001
                pass

    def _clear_log_text(self):
        super()._clear_log_text()
        console = getattr(self, "_ref_log_console", None)
        if console is not None:
            try:
                console.clear_all()
            except Exception:                            # noqa: BLE001
                pass

    # 说明：这里原来重写了 ``_toggle_log_dock``，展开时把 log_text 的
    # min/max 高度重置成「不限」——那会把用户拖动条调好的高度复原（实测
    # 展开后从 144 跳回 179）。现在折叠/展开与正文高度都由基类统一处理
    # （``_toggle_log_dock`` + ``_apply_log_body_height``），本类不再插手。

    def _on_canvas_status(self, msg):
        super()._on_canvas_status(msg)
        label = getattr(self, "_ref_status_text", None)
        if label is not None:
            try:
                label.setText(str(msg) if msg else self._ref_t("就绪"))
            except Exception:                            # noqa: BLE001
                pass

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_ref_shell_ready", False):
            QTimer.singleShot(0, self._setup_reference_shell)
        else:
            QTimer.singleShot(200, self._refresh_property_card)
