# -*- coding: utf-8 -*-
"""
main_window_clean2.py — MolStudio「Bridge」新界面窗口
=========================================================

与 `main_window_clean.py`（Clean Light 皮肤）的关系
--------------------------------------------------
本文件是在 **Clean Light 的基础上**、参照另一个项目 xTBridge Lite 的界面语言
（其 `xtbridge/lite.py` 里的 ``LITE_QSS_EXTRA``）再改的一版：

  * 色调更柔：强调色换 `#2F6FED`，窗口底 `#F4F6FA`，描边 `#E4E9F2`；
    圆角收紧一档（卡片 12 / 控件 8），控件底色统一成 `#FBFCFE` 那种"冷白"。
  * **多一条顶部标题栏**（`QFrame#HeaderBar`）：品牌名 + 一行副标题 + 右侧
    状态胶囊。这是 xTBridge Lite 最显眼的一处，MolStudio 原来没有，
    顶上只有一条"输入文件"卡显得没头。
  * 选项卡改「药丸」样式（选中是浅蓝底 + 蓝字），滚动条更细、轨道透明。

怎么写的
--------
本文件是 `main_window_clean.py` 的**副本 + 改色改形**（自包含，不 import 那个模块），
所以 **卡片命名与间距、导航/按钮图标、分组框折叠、语言切换时的刷新流程**
这些已经验证过的机械部分原样保留，本次只动"长相"：

  - `BRIDGE_QSS`      —— 新配色 + xTBridge 那几处补充规则
  - `_COLOR_REMAP`    —— 面板里硬编码旧色的重映射表（换成 Bridge 色）
  - `_CANVAS_AUGMENT` —— 画布面板的圆角/凹陷底色补充
  - `_install_header_bar()` —— 顶部标题栏

刻意没做的事
------------
- **不给卡片加 `QGraphicsDropShadowEffect` 投影**。窗口里内嵌了 `QOpenGLWidget`，
  而且这个 GL 控件会在各分析面板之间**被反复重新 parent**。图形效果会强制控件走
  QPainter 软件合成，导致 QOpenGLWidget 渲染异常或黑屏。因此这里只用
  1px 描边 + 圆角 + 浅灰窗口底来分层，视觉上足够，也不碰 GL。
- **不改回"蓝底白字标题徽章"**。Clean Light 特意把全窗口 36 个分组框的色块标题
  去掉了（色块用多了反而不强调任何东西），这一版沿用它的"无边框分区标题"，
  只把强调色/圆角/留白换成 xTBridge 那套。

用法
----
    python main_window_clean2.py            # 直接开这版界面
    python main.py --ui clean2              # 走统一入口
    set MOLSTUDIO_UI=clean2 && python main.py   # 环境变量也行

窗口内按 Ctrl+Shift+U 可另起一个进程开经典界面。
"""

from __future__ import annotations

import os
import re
import sys

# 以脚本方式直接运行时才需要；正常入口是 `python main.py --ui clean2`。
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))

from PyQt5.QtCore import QEvent, QObject, QSize, Qt, QTimer
from PyQt5.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QToolButton,
    QWidget,
)

from molstudio.ui.main_window import OrbitalVisApp
from molstudio.ui.ui_icons import make_icon

# ══════════════════════════════════════════════════════════════════════════ #
#  配色：Bridge（xTBridge Lite 那套冷白 + 蓝）
# ══════════════════════════════════════════════════════════════════════════ #
BG_WINDOW = "#F4F6FA"      # 窗口底（比 Clean 更冷一点，让白卡更"浮"）
BG_CARD = "#FFFFFF"        # 卡片
BG_INSET = "#FBFCFE"       # 卡片内的凹陷区（画布底 / 输入框底）
LINE = "#E4E9F2"           # 卡片描边
LINE_SOFT = "#EEF2F7"      # 分隔线
TEXT = "#334155"           # 正文
TEXT_STRONG = "#14213D"    # 标题（xTBridge 的 AppTitle 用色）
TEXT_MUTED = "#7A869A"     # 次要文字
TEXT_FAINT = "#94A3B8"     # 弱化文字
ACCENT = "#2F6FED"         # 主强调色
ACCENT_DEEP = "#245BD0"    # 主强调-深
ACCENT_LIGHT = "#4A84F2"   # 主强调-亮（悬停）
ACCENT_SOFT = "#EEF3FF"    # 选中底
ACCENT_SOFT2 = "#E1EAFD"   # 按下底
FIELD_LINE = "#DCE3EE"     # 输入框描边

CARD_RADIUS = 12
CTRL_RADIUS = 8

# 顶栏文案（中/英）。品牌名固定，副标题跟着语言走 —— 与 i18n.py 里
# `win_title` 的说法保持一致，只是拆成"名字 / 说明"两段排版。
HEADER_TEXT = {
    "zh": ("GXNU MolStudio", "分子可视化与量子化学分析"),
    "en": ("GXNU MolStudio", "Molecular Visualization & Quantum Chemistry"),
}

# ══════════════════════════════════════════════════════════════════════════ #
#  图标：导航 + 按钮
# ══════════════════════════════════════════════════════════════════════════ #
ICON_MUTED = "#7A869A"      # 常态图标色
ICON_ACCENT = "#2F6FED"     # 选中态图标色

# 左侧导航：tab key → 图标名（16 项各不同，全部是 ui_icons 现画的矢量图）
NAV_ICONS = {
    "tab_viz": "orbital",
    "tab_setup": "chart",
    "tab_charge_bond": "bond",
    "tab_nbo": "atom",
    "tab_esp": "wave",
    "tab_igmh": "layers",
    "tab_aim": "axes",
    "tab_etsnocv": "thermal",
    "tab_mpp": "grid",
    "tab_irc": "arrow",
    "tab_di": "cube",
    "tab_asm_irc": "molecule",
    "tab_cub_stack": "eye",
    "tab_esm": "play",
    "tab_ircsplit": "folder",
    "tab_log": "list",
}

# 按钮文字 → 图标。按顺序匹配，先命中先用；中英文都覆盖，
# 这样切换语言后重新识别也能拿到图标。
BUTTON_ICON_RULES = (
    (("停止", "取消", "中止", "中断", "stop", "cancel", "abort"), "stop"),
    (("导出", "保存", "另存", "输出", "export", "save"), "save"),
    (("解析", "读取", "parse", "read"), "download"),
    (("载入", "导入", "打开", "浏览", "加载", "选取", "load", "import", "open", "browse"), "folder"),
    (("清空", "清除", "删除", "移除", "重置", "复位", "clear", "delete", "remove", "reset"),
     "close"),
    (("添加", "新增", "插入", "加入", "add", "new", "insert"), "plus"),
    (("上一", "前一个", "previous", "prev"), "up"),
    (("下一", "后一个", "next"), "down"),
    (("渲染", "出图", "绘图", "画图", "作图", "render", "plot", "draw"), "sun"),
    (("计算", "运行", "执行", "扫描", "生成", "开始", "compute", "run", "scan", "generate"),
     "play"),
    (("预览", "查看", "显示", "preview", "view", "show"), "eye"),
    (("设置", "参数", "选项", "配置", "settings", "config", "option"), "gear"),
    (("路径", "文件夹", "目录", "path", "folder", "directory"), "folder"),
    (("关于", "about"), "info"),
    (("帮助", "说明", "help"), "help"),
    (("刷新", "更新", "重载", "refresh", "update", "reload"), "sun"),
    (("搜索", "查找", "筛选", "search", "find", "filter"), "search"),
    (("定位", "居中", "对齐", "center", "focus", "align"), "target"),
    (("同步", "链接", "sync", "link"), "link"),
    (("拆分", "分割", "split"), "grid"),
    (("应用", "确定", "确认", "apply", "ok", "confirm"), "check"),
    (("画布", "视图", "canvas", "viewport"), "eye"),
)


def pick_button_icon(text: str):
    """按按钮文字挑图标名；没命中返回 None。"""
    t = (text or "").strip()
    if not t:
        return None
    low = t.lower()
    for keys, kind in BUTTON_ICON_RULES:
        for k in keys:
            if k in t or k in low:
                return kind
    return None


def _starts_with_symbol(text: str) -> bool:
    """按钮文字以符号/emoji 开头（如 '⚙️ 路径设置'、'⇄'、'＋ 添加物种'）。

    这类按钮自己已经带了视觉标记，再塞一个矢量图标会变成「双图标」，很难看，
    所以直接跳过不动它们。
    """
    t = (text or "").strip()
    if not t:
        return True
    ch = t[0]
    if ch.isascii():
        return not ch.isalnum()
    # 非 ASCII：CJK 汉字算正常文字，其余（emoji、数学符号、箭头）算符号
    return not ("\u4e00" <= ch <= "\u9fff")


class _SectionClickFilter(QObject):
    """监听分组框标题区域的鼠标点击 → 触发展开/折叠。

    用事件过滤器而不是重写控件类，是为了完全不改动 15 个分析面板里的
    控件类型与结构（那些文件一行都不动）。
    """

    TITLE_ZONE = 28        # 标题行高度（含 margin-top），点这里才算点标题

    def __init__(self, owner):
        super().__init__(owner)
        self._owner = owner

    def eventFilter(self, obj, ev):
        try:
            if ev.type() == QEvent.MouseButtonRelease and \
                    ev.button() == Qt.LeftButton and \
                    isinstance(obj, QGroupBox) and ev.pos().y() <= self.TITLE_ZONE:
                self._owner._toggle_section(obj)
                return True
        except RuntimeError:
            return False
        return False

BRIDGE_QSS = """
/* ═══════════════ 全局 ═══════════════ */
QMainWindow {
    background-color: %(bg_window)s;
}

QWidget {
    font-family: %(font)s;
    font-size: 9pt;
    color: %(text)s;
}

/* ═══════════════ 卡片容器 ═══════════════ */
/* 左侧导航条 / 右侧功能页 / 中间画布 / 顶部输入行 —— 统一大圆角白卡 */
QFrame#NavCard, QFrame#RightCard, QWidget#CanvasCard {
    background-color: %(bg_card)s;
    border: 1px solid %(line)s;
    border-radius: %(card_r)dpx;
}

/* ═══════════════ 分组框 → 无边框分区标题 ═══════════════
   原来每个分组框都是「蓝底白字标题徽章」，全窗口 36 个——强调色被用成了
   底色，反而不强调任何东西，界面看着也就"糙"。这里改成无边框分区：
   只有一行加粗深色标题 + 留白，靠层级而不是色块来分节。
   （下面 #VmdConsoleBox / #AimVmdBox 两个是容器型分组框，单独保留卡片外观） */
QGroupBox {
    border: none;
    border-radius: 0px;
    margin-top: 18px;
    padding: 12px 2px 4px 2px;
    background-color: transparent;
    font-weight: bold;
    font-size: 10.5pt;
    color: %(text_strong)s;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 0px;
    padding: 2px 0px 6px 0px;
    color: %(text_strong)s;
    background-color: transparent;
    border-radius: 0px;
    font-size: 10.5pt;
    font-weight: bold;
}

/* 顶部输入行：整行白卡。
   注意 background / border 必须显式写 —— 改造 2 把通用 QGroupBox 改成了
   「无边框透明分区」，不再继承白底描边，这里不写就会退化成一条悬空的控件带。
   margin-top 也保持 0：标题不再由 QGroupBox 承担（见 #InputLabel）。 */
QGroupBox#InputCard {
    background-color: %(bg_card)s;
    border: 1px solid %(line)s;
    border-radius: %(card_r)dpx;
    margin-top: 0px;
    padding: 12px 14px 12px 14px;
}

/* 行内「输入文件」标签：替换原来的分组框标题，排成「输入文件 [路径框] [浏览] …」 */
QLabel#InputLabel {
    color: %(text_strong)s;
    font-size: 10.5pt;
    font-weight: bold;
    padding: 0px 6px 0px 2px;
}

/* VMD 控制台卡片（容器型分组框，保留卡片外观与内边距） */
QGroupBox#VmdConsoleBox {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #FFFFFF, stop:1 #F7FAFD);
    border: 1px solid %(line)s;
    border-radius: 12px;
    margin-top: 16px;
    padding: 16px 12px 12px 12px;
}

QGroupBox#AimVmdBox {
    margin-top: 0px;
    padding: 32px 12px 10px 12px;
    border: 1px solid %(line)s;
    border-radius: 12px;
    background-color: %(bg_card)s;
}

QGroupBox#AimVmdBox::title {
    subcontrol-origin: padding;
    subcontrol-position: top left;
    left: 16px;
    top: 6px;
    padding: 3px 12px 3px 12px;
    color: #FFFFFF;
    background-color: %(accent)s;
    border-radius: 6px;
    font-size: 9pt;
}

/* ═══════════════ 文字 ═══════════════ */
QLabel {
    color: #475569;
    padding: 1px 0px;
    background: transparent;
}

QLabel#TitleLabel {
    color: %(text_strong)s;
    font-size: 15pt;
    font-weight: bold;
    padding: 6px 8px 2px 8px;
    qproperty-alignment: AlignCenter;
}

QLabel#SubTitleLabel {
    color: %(accent)s;
    font-size: 8.5pt;
    padding: 0px 8px 8px 8px;
    qproperty-alignment: AlignCenter;
}

QLabel#ProgressLabel {
    color: %(accent_deep)s;
    font-size: 9pt;
    font-weight: bold;
    padding: 6px 14px;
    background-color: %(accent_soft)s;
    border: 1px solid #D6E2FB;
    border-radius: 8px;
}

QLabel#HintLabel {
    color: %(text_faint)s;
    font-size: 8pt;
    padding: 1px 4px;
}

/* ═══════════════ 输入控件 ═══════════════ */
QLineEdit {
    background-color: #FFFFFF;
    border: 1px solid %(field_line)s;
    border-radius: %(ctrl_r)dpx;
    padding: 6px 11px;
    color: %(text)s;
    selection-background-color: %(accent)s;
    selection-color: #FFFFFF;
}

QLineEdit:focus {
    border: 1px solid %(accent)s;
    background-color: #FBFDFF;
}

QLineEdit:disabled {
    background-color: #F4F7FB;
    color: %(text_faint)s;
    border: 1px solid %(line)s;
}

QComboBox {
    background-color: #FFFFFF;
    border: 1px solid %(field_line)s;
    border-radius: %(ctrl_r)dpx;
    padding: 6px 11px;
    color: %(text)s;
    min-width: 80px;
}

QComboBox:focus   { border: 1px solid %(accent)s; }
QComboBox:hover   { border: 1px solid %(accent_light)s; }
QComboBox:disabled { background-color: #F4F7FB; color: %(text_faint)s; }

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border-left: 1px solid %(line_soft)s;
    border-top-right-radius: %(ctrl_r)dpx;
    border-bottom-right-radius: %(ctrl_r)dpx;
    background-color: #F7FAFD;
}

QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    border: 1px solid %(line)s;
    border-radius: 8px;
    padding: 4px;
    color: %(text)s;
    selection-background-color: %(accent_soft)s;
    selection-color: %(accent_deep)s;
    outline: none;
}

QComboBox QAbstractItemView::item {
    min-height: 24px;
    padding: 2px 6px;
    border-radius: 6px;
}

QComboBox QAbstractItemView::item:hover {
    background-color: #F2F6FC;
    color: %(accent_deep)s;
}

/* ═══════════════ 单选 / 复选 ═══════════════ */
QRadioButton {
    color: #475569;
    spacing: 6px;
    padding: 3px 6px;
}

QRadioButton::indicator {
    width: 15px; height: 15px;
    border-radius: 8px;
    border: 2px solid #B6C2D2;
    background-color: #FFFFFF;
}

QRadioButton::indicator:checked {
    border: 2px solid %(accent)s;
    background-color: %(accent)s;
}

QRadioButton::indicator:hover { border: 2px solid %(accent_light)s; }

QRadioButton:checked {
    color: %(accent_deep)s;
    font-weight: bold;
}

QCheckBox {
    color: #475569;
    spacing: 6px;
    padding: 3px 6px;
}

QCheckBox::indicator {
    width: 15px; height: 15px;
    border-radius: 4px;
    border: 2px solid #B6C2D2;
    background-color: #FFFFFF;
}

QCheckBox::indicator:checked {
    border: 2px solid %(accent)s;
    background-color: %(accent)s;
}

QCheckBox::indicator:hover { border: 2px solid %(accent_light)s; }
QCheckBox:checked { color: %(accent_deep)s; }

/* ═══════════════ 按钮 ═══════════════ */
QPushButton {
    background-color: #F7FAFD;
    border: 1px solid %(field_line)s;
    border-radius: %(ctrl_r)dpx;
    padding: 6px 16px;
    color: %(text)s;
    font-weight: bold;
    font-size: 9pt;
}

QPushButton:hover {
    background-color: %(accent_soft)s;
    border: 1px solid #C3D7FA;
    color: %(accent_deep)s;
}

QPushButton:pressed {
    background-color: %(accent_soft2)s;
    border: 1px solid %(accent)s;
}

QPushButton:disabled {
    background-color: #F4F7FB;
    border: 1px solid %(line)s;
    color: %(text_faint)s;
}

QPushButton#PrimaryBtn {
    background-color: %(accent)s;
    border: 1px solid %(accent_deep)s;
    color: #FFFFFF;
    font-size: 10pt;
    padding: 8px 20px;
}

QPushButton#PrimaryBtn:hover {
    background-color: %(accent_light)s;
    border: 1px solid %(accent)s;
    color: #FFFFFF;
}

QPushButton#PrimaryBtn:pressed { background-color: %(accent_deep)s; }

QPushButton#RenderBtn {
    background-color: #0F766E;
    border: 1px solid #115E59;
    color: #FFFFFF;
    font-size: 10pt;
    padding: 8px 20px;
}

QPushButton#RenderBtn:hover {
    background-color: #14B8A6;
    border: 1px solid #0F766E;
    color: #FFFFFF;
}

QPushButton#RenderBtn:pressed { background-color: #115E59; }

QPushButton#StopBtn {
    background-color: #FFFFFF;
    border: 1px solid #DC2626;
    color: #DC2626;
    font-size: 10pt;
    padding: 8px 20px;
}

QPushButton#StopBtn:hover {
    background-color: #FEF2F2;
    border: 1px solid #F87171;
    color: #B91C1C;
}

QPushButton#StopBtn:pressed { background-color: #FEE2E2; }

QPushButton#ActionBtn {
    background-color: #F7FAFD;
    border: 1px solid %(field_line)s;
    border-radius: %(ctrl_r)dpx;
    color: %(text)s;
    font-weight: bold;
    font-size: 10pt;
    padding: 8px 20px;
}

QPushButton#ActionBtn:hover {
    background-color: %(accent_soft)s;
    border: 1px solid #C3D7FA;
    color: %(accent_deep)s;
}

QPushButton#ActionBtn:pressed {
    background-color: %(accent_soft2)s;
    border: 1px solid %(accent)s;
}

QPushButton#ActionBtn:disabled {
    background-color: #F4F7FB;
    border: 1px solid %(line)s;
    color: %(text_faint)s;
}

QPushButton#ActionBtnSmall {
    background-color: #F7FAFD;
    border: 1px solid %(field_line)s;
    border-radius: 8px;
    color: %(text)s;
    font-weight: bold;
    font-size: 9pt;
    padding: 6px 10px;
}

QPushButton#ActionBtnSmall:hover {
    background-color: %(accent_soft)s;
    border: 1px solid #C3D7FA;
    color: %(accent_deep)s;
}

QPushButton#ActionBtnSmall:pressed {
    background-color: %(accent_soft2)s;
    border: 1px solid %(accent)s;
}

QPushButton#ActionBtnSmall:disabled {
    background-color: #F4F7FB;
    border: 1px solid %(line)s;
    color: %(text_faint)s;
}

QPushButton#SmallBtn {
    padding: 6px 13px;
    font-size: 9pt;
    min-width: 34px;
    border-radius: 8px;
}

QPushButton#SmallBtn:hover {
    background-color: %(accent_soft)s;
    border: 1px solid #C3D7FA;
    color: %(accent_deep)s;
}

QPushButton#GhostBtn {
    background-color: transparent;
    border: none;
    color: %(accent_deep)s;
    font-weight: bold;
    padding: 5px 12px;
}

QPushButton#GhostBtn:hover {
    background-color: %(accent_soft)s;
    border-radius: 8px;
}

/* ═══════════════ 日志 / 文本区 ═══════════════ */
QTextEdit, QPlainTextEdit {
    background-color: #F7FAFD;
    border: 1px solid %(line)s;
    border-radius: 10px;
    padding: 8px 10px;
    color: #1E293B;
    font-family: %(mono)s;
    font-size: 8.5pt;
    selection-background-color: %(accent_soft2)s;
    selection-color: %(accent_deep)s;
}

QTextEdit:focus, QPlainTextEdit:focus {
    border: 1px solid %(accent)s;
}

/* ═══════════════ 滚动条 ═══════════════ */
QScrollBar:vertical {
    background-color: transparent;
    width: 10px;
    margin: 2px;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    background-color: #D3DDEA;
    border-radius: 5px;
    min-height: 32px;
}

QScrollBar::handle:vertical:hover { background-color: #A9BAD0; }

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0; background: none;
}

QScrollBar:horizontal {
    background-color: transparent;
    height: 10px;
    margin: 2px;
    border-radius: 5px;
}

QScrollBar::handle:horizontal {
    background-color: #D3DDEA;
    border-radius: 5px;
    min-width: 32px;
}

QScrollBar::handle:horizontal:hover { background-color: #A9BAD0; }

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0; background: none;
}

QScrollBar::add-page, QScrollBar::sub-page { background: none; }

/* ═══════════════ 分隔 / 滚动区 ═══════════════ */
QFrame#Separator {
    background-color: %(line_soft)s;
    max-height: 1px;
}

QScrollArea {
    border: none;
    background-color: transparent;
}

QScrollArea > QWidget > QWidget {
    background-color: transparent;
}

QFrame#ViewerFrame {
    background-color: #FFFFFF;
    border: 1px solid %(line)s;
    border-radius: 12px;
    padding: 3px;
}

/* ═══════════════ 滑块 ═══════════════ */
QSlider::groove:horizontal {
    border: none;
    height: 6px;
    background-color: #E8EEF6;
    border-radius: 3px;
}

QSlider::sub-page:horizontal {
    background-color: %(accent)s;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background-color: #FFFFFF;
    border: 2px solid %(accent)s;
    width: 15px;
    height: 15px;
    margin: -6px 0;
    border-radius: 9px;
}

QSlider::handle:horizontal:hover {
    background-color: %(accent_soft)s;
    border: 2px solid %(accent_deep)s;
}

QSlider::handle:horizontal:pressed {
    background-color: %(accent_soft2)s;
    border: 2px solid %(accent_deep)s;
}

QSlider::groove:horizontal:disabled {
    background-color: #F1F5F9;
    border: 1px solid %(line)s;
}

QSlider::handle:horizontal:disabled {
    background-color: #F4F7FB;
    border: 2px solid %(line)s;
}

/* ═══════════════ 提示 ═══════════════ */
QToolTip {
    background-color: #FFFFFF;
    color: %(text)s;
    border: 1px solid %(line)s;
    border-radius: 7px;
    padding: 5px 9px;
    font-size: 8.5pt;
}

/* ═══════════════ 选项卡 ═══════════════ */
QTabWidget::pane {
    border: 1px solid %(line)s;
    border-radius: 10px;
    background-color: #FFFFFF;
    padding: 8px;
    top: -1px;
}

QTabBar::tab {
    background-color: #F2F6FC;
    border: 1px solid %(line)s;
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 8px 22px;
    margin-right: 3px;
    min-width: 72px;
    color: %(text_muted)s;
    font-weight: bold;
    font-size: 9pt;
}

QTabBar::tab:selected {
    background-color: #FFFFFF;
    color: %(accent_deep)s;
    border-bottom: 2px solid %(accent)s;
}

QTabBar::tab:hover:!selected {
    background-color: %(accent_soft)s;
    color: %(accent_deep)s;
}

QTabBar::tab:disabled {
    color: %(text_faint)s;
    background-color: #F2F6FC;
}

/* ═══════════════ 左侧功能导航条 ═══════════════ */
QListWidget#MainNav {
    background: transparent;
    border: none;
    color: #475569;
    font-weight: bold;
    font-size: 9.5pt;
    outline: none;
}

QListWidget#MainNav::item {
    padding: 11px 10px;
    margin: 2px 6px;
    border-radius: 9px;
    border: none;
}

QListWidget#MainNav::item:selected {
    background-color: %(accent_soft)s;
    color: %(accent_deep)s;
}

QListWidget#MainNav::item:hover:!selected {
    background-color: #F2F6FC;
    color: %(accent_deep)s;
}

QListWidget#MainNav::item:disabled {
    color: %(text_faint)s;
}

/* 其它列表（面板里的轨道表等）保持轻量 */
QListWidget {
    background: transparent;
    border: none;
    outline: none;
}

QListWidget::item {
    padding: 6px 8px;
    border-radius: 8px;
}

QListWidget::item:selected {
    background-color: %(accent_soft)s;
    color: %(accent_deep)s;
}

QListWidget::item:hover:!selected {
    background-color: #F2F6FC;
}

/* ═══════════════ 表格 / 树 ═══════════════ */
QTableWidget, QTableView, QTreeWidget, QTreeView {
    background-color: #FFFFFF;
    alternate-background-color: #F7FAFD;
    border: 1px solid %(line)s;
    border-radius: 10px;
    gridline-color: %(line_soft)s;
    outline: none;
    selection-background-color: %(accent_soft)s;
    selection-color: %(accent_deep)s;
}

QTableWidget::item, QTreeWidget::item {
    padding: 4px 6px;
    border: none;
}

QHeaderView::section {
    background-color: #F2F6FC;
    color: %(text_muted)s;
    border: none;
    border-right: 1px solid %(line)s;
    border-bottom: 1px solid %(line)s;
    padding: 6px 8px;
    font-weight: bold;
    font-size: 8.5pt;
}

QHeaderView::section:first { border-top-left-radius: 10px; }
QHeaderView::section:last  { border-top-right-radius: 10px; }

/* ═══════════════ 分割条 ═══════════════ */
/* 浅灰「小药丸」，悬停/拖拽变主题蓝，提示这里能拖动 */
QSplitter::handle { background-color: transparent; }

QSplitter::handle:horizontal {
    width: 8px;
    margin: 8px 2px;
    border-radius: 4px;
    background-color: #DCE3EC;
}

QSplitter::handle:horizontal:hover,
QSplitter::handle:horizontal:pressed {
    background-color: %(accent)s;
}

QSplitter::handle:vertical {
    height: 8px;
    margin: 2px 8px;
    border-radius: 4px;
    background-color: #DCE3EC;
}

QSplitter::handle:vertical:hover,
QSplitter::handle:vertical:pressed {
    background-color: %(accent)s;
}

/* ═══════════════ SpinBox / 其它 ═══════════════ */
QSpinBox, QDoubleSpinBox {
    background-color: #FFFFFF;
    border: 1px solid %(field_line)s;
    border-radius: %(ctrl_r)dpx;
    padding: 5px 8px;
    color: %(text)s;
    selection-background-color: %(accent)s;
    selection-color: #FFFFFF;
}

QSpinBox:focus, QDoubleSpinBox:focus { border: 1px solid %(accent)s; }

QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    background-color: #F7FAFD;
    border: none;
    width: 18px;
}

QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
    background-color: %(accent_soft)s;
}

QProgressBar {
    background-color: #E8EEF6;
    border: none;
    border-radius: 5px;
    min-height: 10px;
    max-height: 10px;
    text-align: center;
    color: transparent;
}

QProgressBar::chunk {
    border-radius: 5px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 %(accent)s, stop:1 #7C3AED);
}

QMenuBar {
    background-color: transparent;
    color: %(text)s;
    padding: 2px 6px;
}

QMenuBar::item {
    background: transparent;
    padding: 5px 10px;
    border-radius: 7px;
}

QMenuBar::item:selected { background-color: %(accent_soft)s; color: %(accent_deep)s; }

QMenu {
    background-color: #FFFFFF;
    border: 1px solid %(line)s;
    border-radius: 10px;
    padding: 6px;
}

QMenu::item {
    padding: 7px 22px 7px 14px;
    border-radius: 7px;
    color: %(text)s;
}

QMenu::item:selected { background-color: %(accent_soft)s; color: %(accent_deep)s; }

QMenu::separator {
    height: 1px;
    background-color: %(line_soft)s;
    margin: 5px 8px;
}

QDialog {
    background-color: %(bg_window)s;
}

/* ═══════════════ Bridge 补充：顶部标题栏 ═══════════════
   xTBridge Lite 最显眼的一处：一整条白卡顶栏，左边品牌名 + 副标题，
   右边状态胶囊。MolStudio 原来顶上直接就是「输入文件」行，看着没头，
   这里补上（控件由 _install_header_bar() 建）。 */
QFrame#HeaderBar {
    background-color: %(bg_card)s;
    border: 1px solid %(line)s;
    border-radius: %(card_r)dpx;
}

QLabel#AppTitle {
    font-size: 15pt;
    font-weight: bold;
    color: %(text_strong)s;
    padding: 0px 2px;
}

/* 副标题与品牌名之间留 8px：读起来是「名字 · 说明」而不是一整串 */
QLabel#AppSubtitle {
    font-size: 9.5pt;
    color: %(text_muted)s;
    padding: 2px 0px 0px 8px;
}

/* 状态胶囊：浅蓝底 + 蓝字，与 xTBridge 的 StatusPill 同一处理 */
QLabel#StatusPill {
    color: %(accent)s;
    background-color: %(accent_soft)s;
    border-radius: 11px;
    padding: 5px 14px;
    font-size: 9pt;
    font-weight: bold;
}

/* ═══════════════ Bridge 补充：药丸选项卡 ═══════════════
   Clean 那版是「标签页」长相（实底 + 下边框）；xTBridge 用无边框药丸：
   常态透明、悬停浅灰、选中浅蓝底 + 蓝字，在密集面板里更轻。 */
QTabBar::tab {
    background: transparent;
    color: %(text_muted)s;
    padding: 6px 16px;
    margin: 4px 4px 0px 0px;
    border: none;
    border-radius: %(ctrl_r)dpx;
}

QTabBar::tab:selected {
    background-color: %(accent_soft)s;
    color: %(accent)s;
    font-weight: bold;
    border: none;
}

QTabBar::tab:hover:!selected {
    background-color: #F1F5FA;
}

/* ═══════════════ Bridge 补充：更细的滚动条 ═══════════════
   轨道透明、手柄 10px 圆头 —— 滚动条不再是一条灰槽。 */
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}

QScrollBar::handle:vertical {
    background: #D5DCE8;
    border-radius: 5px;
    min-height: 32px;
}

QScrollBar::handle:vertical:hover {
    background: #BFCADA;
}

QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 2px;
}

QScrollBar::handle:horizontal {
    background: #D5DCE8;
    border-radius: 5px;
    min-width: 32px;
}

QScrollBar::handle:horizontal:hover {
    background: #BFCADA;
}

/* 两端的小箭头块：xTBridge 里是彻底去掉的（占位 0） */
QScrollBar::add-line, QScrollBar::sub-line {
    background: transparent;
    height: 0px;
    width: 0px;
    border: none;
}
""" % {
    "font": '"Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "Consolas", sans-serif',
    "mono": '"Consolas", "JetBrains Mono", "Courier New", monospace',
    "bg_window": BG_WINDOW,
    "bg_card": BG_CARD,
    "line": LINE,
    "line_soft": LINE_SOFT,
    "text": TEXT,
    "text_strong": TEXT_STRONG,
    "text_muted": TEXT_MUTED,
    "text_faint": TEXT_FAINT,
    "accent": ACCENT,
    "accent_deep": ACCENT_DEEP,
    "accent_light": ACCENT_LIGHT,
    "accent_soft": ACCENT_SOFT,
    "accent_soft2": ACCENT_SOFT2,
    "field_line": FIELD_LINE,
    "card_r": CARD_RADIUS,
    "ctrl_r": CTRL_RADIUS,
}


# ══════════════════════════════════════════════════════════════════════════ #
#  局部样式表配色重映射
# ══════════════════════════════════════════════════════════════════════════ #
# 各分析面板（ovcanvas/esp_panel/nbo_viewer/... 共 92 处）自带 setStyleSheet，
# 局部样式优先级高于祖先窗口的样式表，不处理就会出现「壳新里旧」的割裂。
# 这里只重映射**界面构件色**（主色/边框/底色/文字），不碰元素色、轨道相位色、
# 色标等语义颜色，避免把分子配色也改掉。
_COLOR_REMAP = {
    # 窗口底 / 卡片底
    "#e4eaf2": "#f4f6fa",
    "#f5f6fa": "#fbfcfe",
    "#f8fafe": "#fbfcfe",
    "#f1f5f9": "#f4f6fa",
    "#eef2ff": "#eef3ff",
    # 主色系
    "#1565c0": "#2f6fed",
    "#0d47a1": "#245bd0",
    "#1e88e5": "#4a84f2",
    "#5c6bc0": "#6b7cf3",
    "#3498db": "#2f6fed",
    # 选中 / 按下底
    "#e3f2fd": "#eef3ff",
    "#bbdefb": "#e1eafd",
    "#e8eaf6": "#edf1fe",
    "#dbe7fd": "#e1eafd",
    # 描边
    "#cbd5e1": "#dce3ee",
    "#e2e8f0": "#e4e9f2",
    "#c5cae9": "#dbe3f5",
    "#a0aec0": "#b6c2d2",
    "#b6c2d2": "#b6c2d2",
    # 文字
    "#2c3e50": "#334155",
    "#4a5568": "#475569",
    "#94a3b8": "#94a3b8",
    "#7986cb": "#8b9bf5",
    "#1e293b": "#1e293b",
    # 语义色（渲染绿 / 停止红）保持色相，只做轻微现代化
    "#00897b": "#0f766e",
    "#26a69a": "#14b8a6",
    "#00695c": "#115e59",
    "#e53935": "#dc2626",
    "#ef5350": "#f87171",
    "#d32f2f": "#b91c1c",
    "#ffebee": "#fef2f2",
    "#ffcdd2": "#fee2e2",
}

_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}\b")


def remap_qss(text: str) -> str:
    """把一段 QSS 里的旧界面配色换成新配色（大小写不敏感）。"""
    if not text:
        return text

    def _sub(m):
        return _COLOR_REMAP.get(m.group(0).lower(), m.group(0))

    return _HEX_RE.sub(_sub, text)


# 画布区补充样式：面板自带 _CANVAS_QSS 把 CubCanvasRoot 画成整块方角灰底，
# 在圆角白卡里显得突兀，这里补上圆角与内边距（追加在后面，优先级更高）。
_CANVAS_AUGMENT = """
/* ── Bridge 皮肤补充 ── */
QWidget#CubCanvasRoot {
    background-color: #FBFCFE;
    border-radius: 10px;
}
QWidget#CubToolBar {
    background-color: #FFFFFF;
    border-bottom: 1px solid #EEF2F7;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
}
QFrame#CubParams {
    background-color: #FBFCFE;
    border-top: 1px solid #EEF2F7;
    border-bottom-left-radius: 10px;
    border-bottom-right-radius: 10px;
}
QLabel#CubStatus {
    color: #2F6FED;
    background-color: #EEF3FF;
    border-top: 1px solid #DCE6FB;
}
"""


# ══════════════════════════════════════════════════════════════════════════ #
#  新界面窗口
# ══════════════════════════════════════════════════════════════════════════ #
class MolStudioCleanWindow2(OrbitalVisApp):
    """Bridge 皮肤版主窗口（xTBridge Lite 风）。

    继承 `OrbitalVisApp`，只覆写皮肤相关方法；布局、面板、信号接线全部沿用父类。
    与 Clean Light 的差别：配色/圆角一套新的 + 顶部多一条标题栏。
    """

    # 导航条加宽（原 122px 在卡片风格里太窄，圆角条目会挤在一起）
    NAV_WIDTH = 150

    def __init__(self):
        super().__init__()
        # 父类 __init__ 末尾排了 +10ms 的 _deferred_init（会再调一次 _apply_theme
        # 与语言刷新），这里补一次皮肤后处理，保证那之后仍然一致。
        QTimer.singleShot(60, self._apply_bridge_skin)
        self._setup_bridge_extra()
        # 父类按 1400x820 设计、最小 1100x680。本机屏幕逻辑区只有 1280x684，
        # 680 的最小高度加上标题栏就放不下了，故新界面单独放宽一点。
        try:
            self.setMinimumSize(1080, 620)
        except Exception:
            pass
        self._clean_sized = False

    def showEvent(self, event):
        """首次显示时把窗口收进可用屏幕区域（只影响新界面）。"""
        super().showEvent(event)
        if self._clean_sized:
            return
        self._clean_sized = True
        try:
            from PyQt5.QtWidgets import QApplication
            scr = QApplication.primaryScreen()
            if scr is None:
                return
            g = scr.availableGeometry()
            w = min(self.width(), max(g.width(), 900))
            h = min(self.height(), max(g.height(), 560))
            if (w, h) != (self.width(), self.height()):
                self.resize(w, h)
        except Exception:
            pass

    def _setup_bridge_extra(self):
        """新皮肤独有的一点点交互：Ctrl+Shift+U 切回经典界面。"""
        try:
            from PyQt5.QtWidgets import QShortcut
            from PyQt5.QtGui import QKeySequence

            sc = QShortcut(QKeySequence("Ctrl+Shift+U"), self)
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(self._relaunch_classic)
            self._clean_shortcut = sc           # 保引用，防被 GC
        except Exception:
            self._clean_shortcut = None

    def _relaunch_classic(self):
        """另起一个进程开旧界面（不改动当前窗口，也不干预 GL 状态）。"""
        try:
            import subprocess
            import sys as _sys
            env = dict(os.environ)
            env["MOLSTUDIO_UI"] = "classic"
            from molstudio import paths
            entry = paths.entry_script()
            subprocess.Popen([_sys.executable, entry], env=env,
                             cwd=paths.project_root())
        except Exception:
            pass

    # ── 顶部标题栏（Bridge 皮肤的标志） ────────────────────────────────────
    def _install_header_bar(self):
        """在「输入文件」卡上方插一条顶栏：品牌名 + 副标题 + 状态胶囊。

        xTBridge Lite 的最上面就是这样一条：左边 AppTitle/AppSubtitle，
        右边一个 StatusPill。MolStudio 原来顶上直接是输入行，看着没头；
        这里补上，状态胶囊复用语画布已有的 statusChanged 回调。

        幂等：重复调用只会刷新文字，不会插第二条。
        """
        if getattr(self, "_hdr_bar", None) is not None:
            return self._hdr_bar
        central = self.centralWidget()
        lay = central.layout() if central is not None else None
        if lay is None:
            return None
        try:
            bar = QFrame()
            bar.setObjectName("HeaderBar")
            h = QHBoxLayout(bar)
            h.setContentsMargins(18, 12, 14, 12)
            h.setSpacing(0)
            self._hdr_title = QLabel()
            self._hdr_title.setObjectName("AppTitle")
            h.addWidget(self._hdr_title)
            self._hdr_sub = QLabel()
            self._hdr_sub.setObjectName("AppSubtitle")
            h.addWidget(self._hdr_sub)
            h.addStretch(1)
            self._hdr_status = QLabel()
            self._hdr_status.setObjectName("StatusPill")
            # 长状态（如"已载入 D:\...\very_long_name.fchk"）不去撑大窗口最小宽度
            self._hdr_status.setMaximumWidth(560)
            self._hdr_status.setMinimumWidth(64)
            h.addWidget(self._hdr_status)
            lay.insertWidget(0, bar)          # 排在「输入文件」卡之前
            self._hdr_bar = bar
            self._refresh_header_text()
            self._set_header_status("Ready" if self._header_lang() == "en"
                                    else "就绪")
            return bar
        except Exception:
            self._hdr_bar = None
            return None

    @staticmethod
    def _header_lang():
        """当前界面语言（拿不到就当中文）。"""
        try:
            import molstudio.core.i18n as i18n
            return getattr(i18n, "_CURRENT_LANG", "zh")
        except Exception:
            return "zh"

    def _refresh_header_text(self):
        """按当前语言刷新顶栏的品牌名与副标题。"""
        title = getattr(self, "_hdr_title", None)
        sub = getattr(self, "_hdr_sub", None)
        if title is None or sub is None:
            return
        lang = self._header_lang()
        name, desc = HEADER_TEXT.get(lang, HEADER_TEXT["zh"])
        title.setText(name)
        sub.setText(desc)

    def _set_header_status(self, text):
        """把一句话写进顶栏右侧的状态胶囊。"""
        pill = getattr(self, "_hdr_status", None)
        if pill is None or not text:
            return
        s = str(text)
        pill.setText(s if len(s) <= 64 else s[:61] + "…")
        pill.setToolTip(s)

    def _on_canvas_status(self, msg):
        """画布状态除了写日志，也同步到顶栏胶囊（看得到"在忙什么"）。"""
        super()._on_canvas_status(msg)
        try:
            if msg and not str(msg).startswith("就绪"):
                self._set_header_status(msg)
        except Exception:
            pass

    # ── 主题 ──────────────────────────────────────────────────────────────
    def _apply_theme(self):
        """只换这一处：原 theme.LIGHT_QSS → BRIDGE_QSS。"""
        self.setStyleSheet(BRIDGE_QSS)

    # ── 布局：完全复用父类，只做视觉后处理 ─────────────────────────────────
    def _setup_ui(self):
        super()._setup_ui()          # ← 16 个 tab、全部面板与接线都在这里建立
        self._apply_bridge_skin()     # ← 只改外观

    def _apply_bridge_skin(self):
        """把父类建好的控件树「卡化」：命名、间距、分割比例、局部配色重映射。

        全程 try/except 兜底 —— 皮肤失败最多是「不好看」，绝不能让功能界面打不开。
        """
        try:
            self.setStyleSheet(BRIDGE_QSS)
        except Exception:
            pass

        # 1) 顶部输入行 → 整行白卡 + 行内「输入文件」标签
        try:
            grp_input = getattr(self, "grp_input", None)
            if grp_input is not None:
                grp_input.setObjectName("InputCard")
                lay = grp_input.layout()
                if lay is not None:
                    lay.setContentsMargins(14, 12, 14, 12)
                    lay.setSpacing(8)
                self._ensure_input_label(grp_input)
        except Exception:
            pass

        # 2) 左侧导航卡：加宽 + 收紧内边距 + 条目圆角由 QSS 负责
        try:
            nav_card = self.findChild(QFrame, "NavCard")
            if nav_card is not None:
                nav_card.setFixedWidth(self.NAV_WIDTH)
                lay = nav_card.layout()
                if lay is not None:
                    lay.setContentsMargins(8, 10, 8, 10)
                    lay.setSpacing(0)
        except Exception:
            pass

        # 3) 中间画布区 → 白色圆角卡，内部留出 padding 形成「凹陷视口」
        try:
            grp_canvas = getattr(self, "grp_canvas", None)
            if grp_canvas is not None:
                grp_canvas.setObjectName("CanvasCard")
                grp_canvas.setAttribute(Qt.WA_StyledBackground, True)
                lay = grp_canvas.layout()
                if lay is not None:
                    lay.setContentsMargins(8, 8, 8, 8)
                    lay.setSpacing(0)
        except Exception:
            pass

        # 4) 右侧功能页卡片：加内边距，让 16 个面板不贴着圆角边线
        try:
            right_card = self.findChild(QFrame, "RightCard")
            if right_card is not None:
                lay = right_card.layout()
                if lay is not None:
                    lay.setContentsMargins(10, 10, 6, 10)
        except Exception:
            pass

        # 5) 主布局间距（原来 12,8,12,10 / spacing 6 偏紧）
        try:
            central = self.centralWidget()
            lay = central.layout() if central is not None else None
            if lay is not None:
                lay.setContentsMargins(10, 10, 10, 10)
                lay.setSpacing(10)
        except Exception:
            pass

        # 6) 分割条比例：导航加宽后按比例补回去
        try:
            split = getattr(self, "_body_splitter", None)
            if split is not None:
                sizes = split.sizes()
                total = sum(sizes) or 1240
                rest = max(total - self.NAV_WIDTH, 200)
                new_sizes = [self.NAV_WIDTH, rest // 2, rest - rest // 2]
                split.setSizes(new_sizes)
                if hasattr(split, "set_default_sizes"):
                    split.set_default_sizes(new_sizes)
        except Exception:
            pass

        # 7) 画布区圆角补充 + 全局局部样式配色重映射
        try:
            self._augment_canvas_qss()
        except Exception:
            pass
        try:
            self._remap_widget_styles(self)
        except Exception:
            pass
        # 8) 重映射只动子控件，主窗口自身的 BRIDGE_QSS 最后再压一次，确保干净
        try:
            self.setStyleSheet(BRIDGE_QSS)
        except Exception:
            pass

        # 9) 导航条图标（16 项各不同）
        try:
            self._apply_nav_icons()
        except Exception:
            pass

        # 10) 按钮图标（按文字关键词识别，覆盖全部 16 个功能页）
        try:
            self._apply_button_icons()
        except Exception:
            pass

        # 11) 分组框改成「点标题即折叠」
        try:
            self._install_section_toggles()
        except Exception:
            pass

        # 12) 顶部标题栏（Bridge 皮肤标志）：品牌名 + 副标题 + 状态胶囊
        try:
            self._install_header_bar()
        except Exception:
            pass

    # ── 顶部输入行：「输入文件」行内标签 ────────────────────────────────────
    def _ensure_input_label(self, grp_input=None):
        """把「输入文件」从分组框标题改成行内标签。

        父类是用 `self.grp_input.setTitle(self._tr("grp_input"))` 写的标题，
        而分组框标题是「浮在边框上方」的画法：在整行卡片这种 margin-top=0 的
        场合会被裁掉，看着就像这一段被隐藏了。改成插入布局第 0 位的 QLabel 后，
        排布就是「输入文件  [路径框]  [浏览]  [⚙️路径设置]  [关于]」，一眼能读。

        幂等：重复调用只刷新文字，不会插入第二个标签。
        """
        grp_input = grp_input if grp_input is not None else getattr(self, "grp_input", None)
        if grp_input is None:
            return None
        lay = grp_input.layout()
        if lay is None:
            return None
        text = self._tr("grp_input")
        lb = getattr(self, "_input_label", None)
        if lb is None:
            lb = QLabel(text)
            lb.setObjectName("InputLabel")
            lb.setToolTip(text)
            lay.insertWidget(0, lb)
            self._input_label = lb
        else:
            lb.setText(text)
            lb.setToolTip(text)
        try:
            grp_input.setTitle("")      # 标题已由行内标签承担，避免重复
        except Exception:
            pass
        return lb

    # ── 导航条图标 ────────────────────────────────────────────────────────
    def _setup_main_nav(self):
        """父类建好导航条目后，给每一项挂上矢量图标。"""
        super()._setup_main_nav()
        try:
            self._apply_nav_icons()
        except Exception:
            pass

    def _apply_nav_icons(self):
        """按 _tab_keys 给导航条目配图标。

        父类的 `_sync_main_nav` 只刷文字不碰图标，所以切语言不会把图标刷掉。
        """
        nav = getattr(self, "main_nav", None)
        if nav is None:
            return 0
        keys = getattr(self, "_tab_keys", [])
        n = 0
        for i, key in enumerate(keys):
            if i >= nav.count():
                break
            kind = NAV_ICONS.get(key)
            if not kind:
                continue
            nav.item(i).setIcon(
                make_icon(kind, ICON_MUTED, 18, 1.6, selected_color=ICON_ACCENT))
            n += 1
        nav.setIconSize(QSize(18, 18))
        return n

    # ── 按钮图标 ──────────────────────────────────────────────────────────
    def _apply_button_icons(self, root: QWidget | None = None):
        """遍历控件树，按按钮文字关键词配图标。

        - 已经自带图标的不动；
        - 文字以 emoji/符号开头的不动（避免出现「双图标」）；
        - 没命中关键词的不动。
        """
        root = root if root is not None else self
        n = 0
        for b in root.findChildren((QPushButton, QToolButton)):
            try:
                if not b.icon().isNull():
                    continue
                text = b.text()
                if _starts_with_symbol(text):
                    continue
                kind = pick_button_icon(text)
                if not kind:
                    continue
                size = 15 if b.objectName() not in ("PrimaryBtn", "RenderBtn", "ActionBtn") else 16
                b.setIcon(make_icon(kind, ICON_MUTED, size))
                b.setIconSize(QSize(size, size))
                n += 1
            except RuntimeError:
                continue
        return n

    # ── 分组框：点标题折叠 ────────────────────────────────────────────────
    _CHEV_DOWN = "\u25be"      # ▾
    _CHEV_RIGHT = "\u25b8"     # ▸

    def _install_section_toggles(self):
        """给所有分组框装上「点标题行折叠/展开」。

        不动控件树结构：只装一个事件过滤器监听标题区域的点击，折叠时把
        直接子控件的**当前可见性记录下来再隐藏**，展开时按记录还原 ——
        这样面板自己故意隐藏的控件不会被错误地显示出来。
        """
        if getattr(self, "_section_filter", None) is None:
            self._section_filter = _SectionClickFilter(self)
            self._section_state = {}
            self._section_titles = {}
        n = 0
        for gb in self.findChildren(QGroupBox):
            if getattr(gb, "_clean_section", False):
                continue
            # 空标题的分组框没有「标题行」可点，而它顶部 28px 里放的是真实控件，
            # 装过滤器会把那些控件的点击吞掉 —— 必须跳过。
            if not gb.title().strip():
                continue
            # 可勾选的分组框，标题区点击本来有别的语义，不动
            if gb.isCheckable():
                continue
            gb._clean_section = True
            gb.installEventFilter(self._section_filter)
            self._section_state[gb] = {"collapsed": False, "vis": {}}
            n += 1
        self._refresh_section_titles()
        return n

    def _refresh_section_titles(self):
        """给分区标题加 ▾/▸ 指示符（原有标题已带指示符的跳过）。"""
        for gb, st in list(getattr(self, "_section_state", {}).items()):
            try:
                title = gb.title()
            except RuntimeError:
                continue                      # 控件已被销毁
            if not title:
                continue
            if title[0] in (self._CHEV_DOWN, self._CHEV_RIGHT):
                title = title[2:] if len(title) > 1 and title[1] == " " else title[1:]
                if title.endswith(self._CHEV_DOWN) or title.endswith(self._CHEV_RIGHT):
                    continue                  # 面板自带折叠指示符，交给它自己管
            elif title.rstrip().endswith((self._CHEV_DOWN, self._CHEV_RIGHT)):
                continue
            self._section_titles[gb] = title
            mark = self._CHEV_RIGHT if st["collapsed"] else self._CHEV_DOWN
            gb.setTitle(f"{mark} {title}")

    def _toggle_section(self, gb):
        st = self._section_state.get(gb)
        if st is None:
            return
        if not st["collapsed"]:
            vis = {}
            for ch in gb.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
                try:
                    vis[ch] = ch.isVisible()
                except RuntimeError:
                    continue
            st["vis"] = vis
            st["collapsed"] = True
            for ch in vis:
                ch.hide()
        else:
            for ch, was in st.get("vis", {}).items():
                try:
                    ch.setVisible(was)
                except RuntimeError:
                    continue
            st["vis"] = {}
            st["collapsed"] = False
        st["collapsed"] = bool(st["collapsed"])
        try:
            gb.updateGeometry()
        except RuntimeError:
            pass
        self._refresh_section_titles()

    # ── 局部样式处理 ──────────────────────────────────────────────────────
    def _remap_widget_styles(self, root: QWidget):
        """遍历控件树，把**子控件**局部 QSS 里的旧配色映射成新配色。

        注意只处理子控件、不含 root 自身：root 上挂的往往就是 BRIDGE_QSS，
        而新配色里有些值恰好是映射表的键（如 #F1F5F9 / #94A3B8），
        连 root 一起映射会把新皮肤自己改花。
        """
        if root is None:
            return 0
        n = 0
        for wd in root.findChildren(QWidget):
            try:
                ss = wd.styleSheet()
            except RuntimeError:
                continue                      # 控件已被销毁
            if not ss or "#" not in ss:
                continue
            new = remap_qss(ss)
            if new != ss:
                wd.setStyleSheet(new)
                n += 1
        return n

    def _augment_canvas_qss(self):
        """给画布面板追加一小段补充样式（圆角/凹陷底色），不覆盖其原有规则。"""
        cub = getattr(self, "cub_canvas", None)
        if cub is None:
            return
        ss = cub.styleSheet() or ""
        if "Bridge 皮肤补充" in ss:
            return
        cub.setStyleSheet(ss + _CANVAS_AUGMENT)

    # ── 让皮肤在「重新设样式」的路径上也保持一致 ───────────────────────────
    def _apply_lang_ui(self):
        """切换中英文会重建一批文本与局部样式，这里把皮肤相关的都跟着刷一遍。"""
        super()._apply_lang_ui()
        try:
            self._remap_widget_styles(self)
        except Exception:
            pass
        try:
            self._apply_button_icons()      # 文字变成英文后按新文字重新配图标
        except Exception:
            pass
        try:
            self._refresh_section_titles()  # 面板重设了分组标题，补回 ▾/▸
        except Exception:
            pass
        try:
            # 父类在 _apply_lang_ui 里又给输入行设了分组框标题，这里再收回来，
            # 并把行内「输入文件」标签换成当前语言
            self._ensure_input_label()
        except Exception:
            pass
        try:
            self._refresh_header_text()     # 顶栏副标题也跟着切语言
        except Exception:
            pass

    def _on_style_changed(self, _text=None):
        """切换渲染风格会更新颜色按钮等局部样式，跟随刷新一次配色与按钮图标。"""
        super()._on_style_changed(_text)
        try:
            self._remap_widget_styles(self)
        except Exception:
            pass
        try:
            self._apply_button_icons()
        except Exception:
            pass

    def _open_vmd_console(self):
        """VMD 控制台是独立弹窗，父类给它单独设了旧的 LIGHT_QSS，这里换成新皮肤。"""
        super()._open_vmd_console()
        win = getattr(self, "_vmd_console_win", None)
        if win is not None:
            try:
                self._remap_widget_styles(win)   # 先映射子控件
                win.setStyleSheet(BRIDGE_QSS)     # 再压窗口自身的样式表
                self._apply_button_icons(win)    # 弹窗里的按钮也配上图标
            except Exception:
                pass


def main():
    """独立启动入口：复用 main.py 的完整引导流程（GL 格式、启动画面、异常钩子）。"""
    os.environ["MOLSTUDIO_UI"] = "clean2"
    # 直接以脚本运行时本模块名是 __main__，登记到规范名下，
    # 避免 app.py 再 import 一次、重复定义类。
    _canon = "molstudio.ui.main_window_clean2"
    if _canon not in sys.modules:
        sys.modules[_canon] = sys.modules[__name__]
    import molstudio.app as _main
    _main.main()


if __name__ == "__main__":
    main()
