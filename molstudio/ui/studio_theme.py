# -*- coding: utf-8 -*-
"""studio_theme.py — MolStudio「studio」皮肤（DeepSeek Harness / DSH 设计语言）
===========================================================================

本文件是 ``--ui studio`` 新界面的**唯一**换肤层，独立可 import：

    import molstudio.ui.studio_theme as st      # 不会创建 QApplication

设计来源
--------
``outputs/ui_redesign_2026-11-11/DSH_DESIGN_SPEC.md``（DSH Web GUI 实测 token）：
浅色主题只有 **1 个实色表面** ``#FFFFFF`` + 1 个侧栏 tint ``#F9FAFB``，层级靠
极淡描边（等效 ``#E6E6E6`` / ``#F0F1F2``）表达；主按钮是**近黑底白字**而不是
蓝色底；选中态是中性浅灰 pill（``#EBEEF2``）而不是蓝底白字；蓝色 ``#4176E6``
只用于链接 / focus / 活动指示。

对外契约
--------
``TOKENS``                 —— 色板 / 尺寸 / 字号（键名固定，窗口与侧栏按名取用）
``STUDIO_QSS``             —— 完整窗口 QSS（CLEAN_QSS 重映射 + 组件层）
``STUDIO_CANVAS_AUGMENT``  —— 画布面板追加样式（替代 clean 的 ``_CANVAS_AUGMENT``）
``ICON_MUTED`` / ``ICON_ACCENT`` —— 矢量图标常态 / 选中色
``remap_qss_studio(text)`` —— 面板内联 QSS 的构件色重映射

窗口侧建议用法（见文件末尾集成说明）
------------------------------------
    self.setStyleSheet(STUDIO_QSS)
    for wd in self.findChildren(QWidget):
        if wd.styleSheet():
            wd.setStyleSheet(remap_qss_studio(wd.styleSheet()))
    cub.setStyleSheet(cub.styleSheet() + STUDIO_CANVAS_AUGMENT)
"""

from __future__ import annotations

import re

# CLEAN_QSS 是「已经 % 格式化好的完整浅色 QSS」，直接拿来当基线做 hex 级
# 重映射（只换颜色，不改结构），这样 27 个分析面板依赖的 QSS 选择器全部保留。
# 注意：main_window_clean 只 import PyQt5 / main_window，不创建 QApplication。
from molstudio.ui.main_window_clean import CLEAN_QSS


# ══════════════════════════════════════════════════════════════════════════ #
#  1. TOKENS —— DSH 设计 token（窗口 / 侧栏 / inspector 按名取用）
# ══════════════════════════════════════════════════════════════════════════ #
TOKENS = {
    # ── 颜色：表面 ─────────────────────────────────────────────────────
    # DSH 浅色主题 bg-base == layer-1..3 == #FFFFFF，层级靠描边而不是灰阶；
    # shell 只是窗口最外层底色（模块平台底 F5F6F7），侧栏用 F9FAFB。
    "shell": "#F5F6F7",
    "surface": "#FFFFFF",
    "sidebar": "#F9FAFB",
    "surface_subtle": "#F9FAFB",
    "inset": "#F7F8FA",            # 画布底 / 输入框底（卡片内的凹陷区）
    # ── 颜色：描边（DSH 全用 alpha 黑，这里是合成到白底后的实色）────────
    "border": "#E6E6E6",           # = rgba(0,0,0,.10)
    "border_soft": "#F0F1F2",      # = rgba(0,0,0,.04)，分隔线 / 发丝线
    "border_input": "#E0E0E0",     # = rgba(0,0,0,.12)，控件描边
    # ── 颜色：文字（DSH 只有 5 级）────────────────────────────────────
    "text_primary": "#0F1115",     # label-primary
    "text_body": "#1B1D21",
    "text_secondary": "#61666B",   # label-secondary
    "text_tertiary": "#81858C",    # label-tertiary
    "text_caption": "#ADB2B8",     # label-caption
    # ── 颜色：交互（hover 与 selected 同色是 DSH 的核心规则）───────────
    "hover": "#F2F3F4",
    "selected": "#EBEEF2",
    # ── 颜色：强调（只用于链接 / focus / 活动指示，不做大面积底色）─────
    "accent": "#4176E6",
    "accent_hover": "#6C97EE",
    "accent_soft": "#E4EDFD",
    "accent_ink": "#2F5FD0",
    # 主操作按钮：DSH 品牌色不是蓝，是近黑
    "primary_bg": "#0F1115",
    "primary_hover": "#2E2F33",
    "primary_text": "#FFFFFF",
    # ── 颜色：状态 ─────────────────────────────────────────────────────
    "success": "#22C55E",
    "error": "#EC1313",
    "warn": "#F59E0B",
    # ── 颜色：图标 ─────────────────────────────────────────────────────
    "icon": "#61666B",
    "icon_active": "#0F1115",
    # ── 尺寸 ──────────────────────────────────────────────────────────
    "radius_card": 12,             # 卡片 / 面板 / 菜单容器
    "radius_ctrl": 8,              # 按钮 / 输入框 / 导航行
    "row_h": 34,                   # 通用行高（菜单项等）；侧栏单独用下面四个键
    # ── 侧栏排版：展开态要「松」，rail 态由 studio_sidebar 收紧 ──
    # 之前导航条目 34px + 组内 spacing 1 + 组间 spacing 0，字贴字；
    # 这里把行高、组间距、字号收敛成一套，避免代码 QFont 与 QSS font-size 打架。
    "nav_row_h": 40,
    "nav_group_h": 34,
    "nav_item_gap": 4,
    "nav_group_gap": 10,
    "nav_text_pt": 10,             # 侧栏主文字统一字号（条目/搜索/分组标题/底部动作）
    "nav_aux_pt": 9,               # 辅助标注（Ctrl K / 折叠箭头 / 版本号）
    "ctl_h": 32,                   # 常规输入框 / 搜索框
    "ctl_h_sm": 28,                # 小按钮 / 图标按钮
    "topbar_h": 52,
    "status_h": 24,
    "sidebar_w": 232,
    "sidebar_rail_w": 56,
    "inspector_w": 400,
    # ── 字号（pt）─────────────────────────────────────────────────────
    "font_body": 10,               # 正文基准（≈13.3px）
    "font_secondary": 9.5,         # ≈12.7px
    "font_caption": 9,             # ≈12px
    "font_title": 14,              # 品牌名 / 面板标题（≈18.7px）
    "font_section": 10,            # 分区标题（≈14px）
}


# 图标：常态用 label-secondary，选中/激活用 label-primary（DSH 导航选中是
# 「浅灰 pill + 深色字」，不是蓝底白字，所以选中图标也是近黑色）。
ICON_MUTED = TOKENS["icon"]
ICON_ACCENT = TOKENS["icon_active"]

# 主按钮上的图标必须用白色，否则深色底上的 ICON_MUTED 图标不可见。
ICON_ON_PRIMARY = TOKENS["primary_text"]


# ══════════════════════════════════════════════════════════════════════════ #
#  2. 构件色重映射表（面板内联 QSS 用）
# ══════════════════════════════════════════════════════════════════════════ #
# 设计边界（很重要）
# ------------------
# 1) **白名单制**：只有本表显式列出的 hex 会被替换，其余 hex 原样保留。
#    因此下面这些语义色天然不受影响（它们不是表的键）：
#      · 轨道相位红/蓝：``#FF0000`` / ``#0000FF``（纯原色）
#      · 色标：``#0000FF #00FFFF #FFFF00`` 及其它 colormap 端点
#      · 元素色 / CPK 色（如 N 的 ``#3050F8``）、3D 场景色
#      · 渲染绿 ``#00897B``（clean 的 ``#0F766E/#115E59/#14B8A6`` 同族也保留）
#      · 纯黑白 ``#FFFFFF`` / ``#000000``
# 2) **一次性正则 + 查表**：``re.sub`` 只扫一遍原文，不做多次 ``str.replace``，
#    所以不会出现 "A→B 之后 B→C" 的链式误伤。为保证这一点，三张表的值
#    **都不是**任何一张表的键（键集互斥、值集与键集不相交，测试里会验证
#    幂等性：remap(remap(x)) == remap(x)）。
# 3) 8 位 hex（Qt 里是 ``#AARRGGBB``）与 ``#RGB`` 简写不匹配、不替换；
#    正则的 ``\b`` 保证 8 位 hex 不会被截断成 6 位误伤。
# 4) 默认值用 ``m.group(0)`` 返回**原文**，所以大小写和未被识别的颜色都保持原样。

# ── 2a. 两代皮肤共有的中性色（clean 与 classic 都在用，目标值一致）─────────
_SHARED_TO_STUDIO = {
    "#f1f5f9": "#F7F8FA",   # 禁用底 / 浅灰底
    "#dce3ec": "#E6E6E6",   # 分割条 handle
    "#94a3b8": "#81858C",   # 弱化文字
    "#1e293b": "#1B1D21",   # 正文（日志 / 文本区）
}

# ── 2b. clean 皮肤（CLEAN_QSS / main_window_clean 常量）→ DSH ──────────────
_CLEAN_TO_STUDIO = {
    # 表面
    "#eef2f7": "#F5F6F7",   # 窗口底（同时被 clean 当分隔线用，见 STUDIO_EXTRA 修正）
    "#f4f7fb": "#F7F8FA",   # 画布凹陷底
    "#f7fafd": "#F9FAFB",   # 次级按钮 / 表格斑马底
    "#fbfdff": "#FFFFFF",   # 输入框 focus 底
    "#f2f6fc": "#F9FAFB",   # 页签 / 表头底
    "#e8eef6": "#F0F1F2",   # 滑槽 / 进度条轨道
    # 描边
    "#e6ecf4": "#E6E6E6",
    "#dfe7f1": "#E0E0E0",
    "#d6e2fb": "#E6E6E6",
    "#c3d7fa": "#E0E0E0",
    "#b6c2d2": "#D6D6D6",
    # 文字
    "#334155": "#1B1D21",
    "#0f172a": "#0F1115",
    "#64748b": "#61666B",
    "#475569": "#1B1D21",
    # 主色系
    "#2563eb": "#4176E6",
    "#1d4ed8": "#2F5FD0",
    "#3b82f6": "#6C97EE",
    "#eaf1fe": "#E4EDFD",
    "#dce7fd": "#D3E2FF",
    # 滚动条
    "#d3ddea": "#D9D9D9",
    "#a9bad0": "#C9C9C9",
    # 状态（停止按钮红系；渲染绿 #0F766E / #115E59 / #14B8A6 保留不动）
    "#dc2626": "#EC1313",
    "#b91c1c": "#C31616",
    "#f87171": "#F25A5A",
    "#fef2f2": "#FEF3F3",
    "#fee2e2": "#FBE5E5",
}

# ── 2c. 经典皮肤（theme.LIGHT_QSS）与老面板里的构件色 → DSH ─────────────────
_CLASSIC_TO_STUDIO = {
    # 表面
    "#e4eaf2": "#F5F6F7",   # 老窗口底
    "#f5f6fa": "#F7F8FA",   # 文本区 / 列表底
    "#f8fafe": "#FFFFFF",   # 输入框 focus 底
    "#f1f5fb": "#F7F8FA",   # 渐变卡收尾色
    "#e8eff7": "#F2F3F4",   # 导航 hover 底
    "#eef2ff": "#E4EDFD",   # 进度标签淡底
    "#e8eaf6": "#EBEEF2",   # 选中底（老靛蓝）
    "#e3f2fd": "#EBEEF2",   # 选中底（老浅蓝）→ DSH 中性 pill
    "#bbdefb": "#D3E2FF",   # 按下底
    # 描边
    "#cbd5e1": "#E0E0E0",   # 老控件描边
    "#e2e8f0": "#E6E6E6",
    "#d5dee9": "#E0E0E0",
    "#c5cae9": "#E6E6E6",
    "#a0aec0": "#D6D6D6",   # 单选 / 复选 indicator 描边
    # 文字
    "#2c3e50": "#1B1D21",
    "#4a5568": "#61666B",
    "#1a237e": "#0F1115",
    "#7986cb": "#81858C",
    # 主色系
    "#1565c0": "#4176E6",
    "#0d47a1": "#2F5FD0",
    "#1e88e5": "#4176E6",
    "#5c6bc0": "#6C97EE",
    "#3498db": "#4176E6",
    # 老面板里的蓝灰 / 中性构件色（QSS 专用，改名后不影响 3D / 图表）
    "#f8fafc": "#F9FAFB",
    "#fafbfd": "#F9FAFB",
    "#f4f8fc": "#F7F8FA",
    "#f5f7fb": "#F7F8FA",
    "#e8edf5": "#F0F1F2",
    "#f0f2f5": "#F0F1F2",
    "#eff6ff": "#E4EDFD",
    "#dbeafe": "#E4EDFD",
    "#bfdbfe": "#D3E2FF",
    "#93c5fd": "#6C97EE",
    "#d7e1ec": "#E6E6E6",
    "#d9e4ef": "#E6E6E6",
    "#dde5ec": "#E6E6E6",
    "#d8dee9": "#E6E6E6",
    "#b8c2d0": "#D6D6D6",
    "#7e9ab8": "#D6D6D6",
    "#5b6573": "#61666B",
    "#5b6b7f": "#61666B",
    "#5a6b7d": "#61666B",
    "#6b7280": "#61666B",
    "#7a8595": "#81858C",
    "#7a8699": "#81858C",
    "#9aa7b8": "#ADB2B8",
    "#2d3748": "#1B1D21",
    "#1f2d3d": "#0F1115",
    "#1a1a2e": "#0F1115",
    "#24445f": "#1B1D21",
    "#123f8a": "#2F5FD0",
    "#1e40af": "#2F5FD0",
    "#1976d2": "#4176E6",
    "#0369a1": "#4176E6",
    # 状态（UI 红 / 琥珀；相位红 #FF0000、色标、渲染绿不在表内 → 保留）
    "#e53935": "#EC1313",
    "#ef5350": "#F25A5A",
    "#d32f2f": "#C31616",
    "#f44336": "#EC1313",
    "#ef4444": "#EC1313",
    "#ffebee": "#FEF3F3",
    "#ffcdd2": "#FBE5E5",
    "#b45309": "#DD8629",   # 警告文字（DSH state-warn-label）
    "#b07200": "#DD8629",
    "#10b981": "#22C55E",
}

# 合并顺序：共有 → clean → 经典。一次查表，天然「clean 优先于经典」且不链式。
_COLOR_MAP = {**_SHARED_TO_STUDIO, **_CLEAN_TO_STUDIO, **_CLASSIC_TO_STUDIO}

_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}\b")


def remap_qss_studio(text):
    """把一段 QSS 里的旧皮肤构件色映射成 DSH 色（大小写不敏感）。

    - 只替换 ``_COLOR_MAP`` 里显式登记的 hex（白名单）；
    - 语义色（相位红蓝 / 色标 / 元素色 / 渲染绿）不在表里，原样保留；
    - 单次正则替换，不产生 A→B→C 链式误伤；
    - ``None`` / 空串原样返回，方便直接套在 ``widget.styleSheet()`` 上。
    """
    if not text:
        return text
    return _HEX_RE.sub(lambda m: _COLOR_MAP.get(m.group(0).lower(), m.group(0)), text)


# ══════════════════════════════════════════════════════════════════════════ #
#  3. STUDIO_QSS = CLEAN_QSS(重映射) + 组件层
# ══════════════════════════════════════════════════════════════════════════ #
_BASE = remap_qss_studio(CLEAN_QSS)


# ── 3a. 组件层：DSH 交互规则 / 新增 objectName ──────────────────────────────
# 说明：CLEAN_QSS 里带 ID 选择器的规则（#PrimaryBtn / #ActionBtn …）优先级
# 高于类型选择器，所以这里凡是改对象既定外观的地方都重新用 ID 选择器覆盖。
# 颜色全部来自 TOKENS，用 %(name)s 注入（QSS 不支持 CSS 变量）。
STUDIO_EXTRA = """
/* ══════════════════════════════════════════════════════════════════════
   DSH 组件层（追加在 clean 重映射结果之后；后写规则覆盖先写规则）
   ══════════════════════════════════════════════════════════════════════ */

/* ── 0. 全局基线 ───────────────────────────────────────────────────── */
QMainWindow, QDialog {
    background-color: %(shell)s;
}
QWidget {
    font-size: %(font_body)spt;
    color: %(text_body)s;
}

/* ── 1. 白卡：DSH 只有 #FFFFFF 一个实色表面，层级靠 1px 极淡描边 ───── */
QFrame#NavCard, QFrame#RightCard, QWidget#CanvasCard {
    background-color: %(surface)s;
    border: 1px solid %(border)s;
    border-radius: %(radius_card)spx;
}

/* clean 把 #EEF2F7 同时用作窗口底与分隔线（重映射后都成了 shell），
   这里把「线」类用法改回 border_soft，避免分隔线消失。 */
QFrame#Separator {
    background-color: %(border_soft)s;
}
QComboBox::drop-down {
    border-left: 1px solid %(border_soft)s;
}

/* ── 2. 分组框：无边框分区（clean 风格保留），标题 10pt semibold 次要字色 ── */
QGroupBox {
    border: none;
    border-radius: 0px;
    margin-top: 16px;
    padding: 10px 2px 4px 2px;
    background-color: transparent;
    font-size: %(font_body)spt;
    font-weight: 600;
    color: %(text_secondary)s;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 0px;
    padding: 2px 0px 6px 0px;
    color: %(text_secondary)s;
    background-color: transparent;
    border-radius: 0px;
    font-size: %(font_section)spt;
    font-weight: 600;
}
/* 容器型分组框：仍是白卡，但去蓝底标题徽章 */
QGroupBox#InputCard {
    background-color: %(surface)s;
    border: 1px solid %(border)s;
    border-radius: %(radius_card)spx;
    padding: 12px 14px 12px 14px;
}
QGroupBox#VmdConsoleBox {
    background-color: %(surface)s;
    border: 1px solid %(border)s;
    border-radius: %(radius_card)spx;
    padding: 16px 12px 12px 12px;
}
QGroupBox#AimVmdBox {
    background-color: %(surface)s;
    border: 1px solid %(border)s;
    border-radius: %(radius_card)spx;
}
QGroupBox#AimVmdBox::title {
    color: %(text_secondary)s;
    background-color: transparent;
    border: none;
    font-size: %(font_section)spt;
    font-weight: 600;
}

/* ── 3. 文字层级 ───────────────────────────────────────────────────── */
QLabel#TitleLabel {
    color: %(text_primary)s;
    font-size: %(font_title)spt;
    font-weight: 600;
}
QLabel#SubTitleLabel {
    color: %(text_tertiary)s;
    font-size: %(font_caption)spt;
}
QLabel#ProgressLabel {
    color: %(text_secondary)s;
    background-color: %(inset)s;
    border: 1px solid %(border_soft)s;
    border-radius: %(radius_ctrl)spx;
    font-size: %(font_secondary)spt;
    font-weight: 500;
}
QLabel#HintLabel {
    color: %(text_caption)s;
    font-size: %(font_caption)spt;
}
QLabel#InputLabel {
    color: %(text_primary)s;
    font-size: %(font_section)spt;
    font-weight: 600;
}
QLabel:disabled {
    color: %(text_caption)s;
}

/* ── 4. 输入控件：focus 只改描边色（DSH 规则），不画蓝底 ──────────── */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: %(surface)s;
    border: 1px solid %(border_input)s;
    border-radius: %(radius_ctrl)spx;
    padding: 1px 8px;
    min-height: %(ctl_h_sm)spx;
    color: %(text_body)s;
    selection-background-color: %(accent_soft)s;
    selection-color: %(text_primary)s;
}
QLineEdit:focus, QComboBox:focus,
QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid %(accent)s;
    background-color: %(surface)s;
}
QLineEdit:disabled, QComboBox:disabled,
QSpinBox:disabled, QDoubleSpinBox:disabled {
    background-color: %(surface_subtle)s;
    border-color: %(border_soft)s;
    color: %(text_caption)s;
}
QComboBox::drop-down {
    background-color: transparent;
    width: 22px;
}
QComboBox QAbstractItemView {
    background-color: %(surface)s;
    border: 1px solid %(border)s;
    border-radius: %(radius_ctrl)spx;
    padding: 4px;
    color: %(text_body)s;
    selection-background-color: %(selected)s;
    selection-color: %(text_primary)s;
    outline: none;
}
QComboBox QAbstractItemView::item {
    min-height: %(ctl_h_sm)spx;
    padding: 2px 8px;
    border-radius: 6px;
}
QComboBox QAbstractItemView::item:hover {
    background-color: %(hover)s;
    color: %(text_primary)s;
}

QTextEdit, QPlainTextEdit {
    background-color: %(inset)s;
    border: 1px solid %(border_soft)s;
    border-radius: %(radius_ctrl)spx;
    padding: 6px 8px;
    color: %(text_body)s;
    selection-background-color: %(accent_soft)s;
    selection-color: %(text_primary)s;
}
QTextEdit:focus, QPlainTextEdit:focus {
    border: 1px solid %(accent)s;
}

/* ── 5. 单选 / 复选：DSH 16px 方/圆 indicator，选中填 accent ───────── */
QRadioButton, QCheckBox {
    color: %(text_body)s;
    spacing: 6px;
    padding: 2px 4px;
}
QRadioButton::indicator, QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid %(text_caption)s;
    background-color: %(surface)s;
}
QRadioButton::indicator { border-radius: 8px; }
QCheckBox::indicator    { border-radius: 4px; }
QRadioButton::indicator:checked, QCheckBox::indicator:checked {
    border: 1px solid %(accent)s;
    background-color: %(accent)s;
}
QRadioButton::indicator:hover, QCheckBox::indicator:hover {
    border: 1px solid %(accent_hover)s;
}
QRadioButton:checked, QCheckBox:checked {
    color: %(text_primary)s;
    font-weight: 500;
}

/* ── 6. 按钮：DSH 默认 ghost；只有主操作才是近黑底白字 ────────────── */
QPushButton {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: %(radius_ctrl)spx;
    padding: 0 10px;
    min-height: %(ctl_h_sm)spx;
    color: %(text_body)s;
    font-size: %(font_body)spt;
    font-weight: 500;
}
QPushButton:hover {
    background-color: %(hover)s;
    border-color: transparent;
    color: %(text_primary)s;
}
QPushButton:pressed {
    background-color: %(selected)s;
    border-color: transparent;
}
QPushButton:disabled {
    background-color: transparent;
    border-color: transparent;
    color: %(text_caption)s;
}

/* 次级描边按钮 */
QPushButton#ActionBtnSmall {
    background-color: %(surface)s;
    border: 1px solid %(border)s;
    border-radius: %(radius_ctrl)spx;
    padding: 0 10px;
    min-height: %(ctl_h_sm)spx;
    color: %(text_body)s;
    font-size: %(font_secondary)spt;
    font-weight: 500;
}
QPushButton#ActionBtnSmall:hover {
    background-color: %(hover)s;
    border-color: %(border_input)s;
    color: %(text_primary)s;
}
QPushButton#ActionBtnSmall:pressed { background-color: %(selected)s; }
QPushButton#ActionBtnSmall:disabled {
    background-color: %(surface)s;
    border-color: %(border_soft)s;
    color: %(text_caption)s;
}

/* 图标型小按钮（画布工具条等）：ghost 方按钮 */
QPushButton#SmallBtn {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: %(radius_ctrl)spx;
    padding: 0 6px;
    min-height: %(ctl_h_sm)spx;
    min-width: %(ctl_h_sm)spx;
    color: %(text_secondary)s;
}
QPushButton#SmallBtn:hover {
    background-color: %(hover)s;
    color: %(text_primary)s;
}
QPushButton#SmallBtn:pressed { background-color: %(selected)s; }

/* ★ DSH 最关键的一条：强调色不泛滥 —— 主操作按钮=近黑底白字 */
QPushButton#PrimaryBtn, QPushButton#RunBtn,
QPushButton#RenderBtn, QPushButton#ActionBtn {
    background-color: %(primary_bg)s;
    border: 1px solid %(primary_bg)s;
    border-radius: %(radius_ctrl)spx;
    min-height: 34px;
    padding: 0 18px;
    color: %(primary_text)s;
    font-size: %(font_body)spt;
    font-weight: 600;
}
QPushButton#PrimaryBtn:hover, QPushButton#RunBtn:hover,
QPushButton#RenderBtn:hover, QPushButton#ActionBtn:hover {
    background-color: %(primary_hover)s;
    border-color: %(primary_hover)s;
    color: %(primary_text)s;
}
QPushButton#PrimaryBtn:pressed, QPushButton#RunBtn:pressed,
QPushButton#RenderBtn:pressed, QPushButton#ActionBtn:pressed {
    background-color: #000000;
    border-color: #000000;
    color: %(primary_text)s;
}
QPushButton#PrimaryBtn:disabled, QPushButton#RunBtn:disabled,
QPushButton#RenderBtn:disabled, QPushButton#ActionBtn:disabled {
    background-color: %(selected)s;
    border-color: %(selected)s;
    color: %(text_tertiary)s;
}

/* 停止按钮：错误色只做描边 + 文字，不填满（DSH 危险态） */
QPushButton#StopBtn {
    background-color: %(surface)s;
    border: 1px solid %(error)s;
    border-radius: %(radius_ctrl)spx;
    min-height: 34px;
    padding: 0 18px;
    color: %(error)s;
    font-size: %(font_body)spt;
    font-weight: 500;
}
QPushButton#StopBtn:hover {
    background-color: #FEF3F3;
    border-color: #F25A5A;
    color: %(error)s;
}
QPushButton#StopBtn:pressed { background-color: #FBE5E5; }

/* 链接型按钮 */
QPushButton#GhostBtn {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: %(radius_ctrl)spx;
    padding: 0 8px;
    min-height: %(ctl_h_sm)spx;
    color: %(accent)s;
    font-weight: 500;
}
QPushButton#GhostBtn:hover {
    background-color: %(hover)s;
    color: %(accent_ink)s;
}

/* ── 7. 页签：白底 pill + 深色字 + 1px 描边（无蓝色实底/下划线）────── */
QTabWidget::pane {
    border: 1px solid %(border)s;
    border-radius: %(radius_card)spx;
    background-color: %(surface)s;
    padding: 8px;
    top: -1px;
}
QTabBar {
    background: transparent;
}
QTabBar::tab {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: %(radius_ctrl)spx;
    padding: 6px 14px;
    margin: 2px 3px 2px 0;
    min-width: 56px;
    color: %(text_secondary)s;
    font-size: %(font_secondary)spt;
    font-weight: 500;
}
QTabBar::tab:hover:!selected {
    background-color: %(hover)s;
    color: %(text_body)s;
}
QTabBar::tab:selected {
    background-color: %(surface)s;
    border: 1px solid %(border)s;
    color: %(text_primary)s;
    font-weight: 600;
}
QTabBar::tab:disabled {
    background-color: transparent;
    color: %(text_caption)s;
}

/* ── 8. 列表 / 表格：hover 与 selected 同色（DSH 核心规则）────────── */
QListWidget, QListView {
    background-color: transparent;
    border: none;
    outline: none;
}
QListWidget::item, QListView::item {
    min-height: %(ctl_h_sm)spx;
    padding: 0 8px;
    border-radius: %(radius_ctrl)spx;
    color: %(text_body)s;
}
QListWidget::item:hover:!selected, QListView::item:hover {
    background-color: %(hover)s;
}
QListWidget::item:selected, QListView::item:selected {
    background-color: %(selected)s;
    color: %(text_primary)s;
}

QTableWidget, QTableView, QTreeWidget, QTreeView {
    background-color: %(surface)s;
    alternate-background-color: %(surface_subtle)s;
    border: 1px solid %(border)s;
    border-radius: %(radius_card)spx;
    gridline-color: %(border_soft)s;
    selection-background-color: %(selected)s;
    selection-color: %(text_primary)s;
    outline: none;
}
QTableWidget::item, QTreeWidget::item {
    padding: 4px 6px;
    border: none;
}
QHeaderView::section {
    background-color: %(surface_subtle)s;
    color: %(text_secondary)s;
    border: none;
    border-right: 1px solid %(border_soft)s;
    border-bottom: 1px solid %(border_soft)s;
    padding: 6px 8px;
    font-size: %(font_caption)spt;
    font-weight: 600;
}

/* ── 9. 滚动条：6px 细条（无箭头；thumb #D9D9D9 / hover #C9C9C9）──── */
QScrollBar:vertical {
    background-color: transparent;
    width: 6px;
    margin: 0px;
    border: none;
}
QScrollBar::handle:vertical {
    background-color: #D9D9D9;
    border-radius: 3px;
    min-height: 32px;
    margin: 0px;
}
QScrollBar::handle:vertical:hover { background-color: #C9C9C9; }
QScrollBar::handle:vertical:pressed { background-color: #B3B3B3; }
QScrollBar:horizontal {
    background-color: transparent;
    height: 6px;
    margin: 0px;
    border: none;
}
QScrollBar::handle:horizontal {
    background-color: #D9D9D9;
    border-radius: 3px;
    min-width: 32px;
    margin: 0px;
}
QScrollBar::handle:horizontal:hover { background-color: #C9C9C9; }
QScrollBar::handle:horizontal:pressed { background-color: #B3B3B3; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
    height: 0px;
    background: none;
    border: none;
}
QScrollBar::up-arrow, QScrollBar::down-arrow,
QScrollBar::left-arrow, QScrollBar::right-arrow {
    width: 0px;
    height: 0px;
    background: none;
    border: none;
}
QScrollBar::add-page, QScrollBar::sub-page { background: none; }

/* ── 10. 滑块 / 进度 / 分割条 ──────────────────────────────────────── */
QSlider::groove:horizontal {
    height: 4px;
    background-color: #EDEEF0;
    border: none;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background-color: %(accent)s;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background-color: %(surface)s;
    border: 1px solid %(border_input)s;
    width: 14px;
    height: 14px;
    margin: -6px 0;
    border-radius: 8px;
}
QSlider::handle:horizontal:hover { border-color: %(accent)s; }
QSlider::handle:horizontal:pressed {
    background-color: %(accent_soft)s;
    border-color: %(accent_ink)s;
}
QSlider::groove:horizontal:disabled { background-color: %(border_soft)s; }
QSlider::handle:horizontal:disabled {
    background-color: %(surface_subtle)s;
    border-color: %(border_soft)s;
}

QProgressBar {
    background-color: %(border_soft)s;
    border: none;
    border-radius: 3px;
    min-height: 6px;
    max-height: 6px;
    color: transparent;
}
QProgressBar::chunk {
    background-color: %(accent)s;
    border-radius: 3px;
}

QSplitter::handle:horizontal:hover, QSplitter::handle:horizontal:pressed,
QSplitter::handle:vertical:hover, QSplitter::handle:vertical:pressed {
    background-color: %(text_caption)s;
}

/* ── 11. 菜单 / 提示：白底 + 1px 描边 + 12px 圆角；tooltip 用 #2C2C2E ── */
QMenuBar {
    background-color: transparent;
    color: %(text_secondary)s;
}
QMenuBar::item {
    background: transparent;
    padding: 5px 10px;
    border-radius: %(radius_ctrl)spx;
}
QMenuBar::item:selected {
    background-color: %(hover)s;
    color: %(text_primary)s;
}
QMenu {
    background-color: %(surface)s;
    border: 1px solid %(border)s;
    border-radius: %(radius_card)spx;
    padding: 4px;
    color: %(text_body)s;
}
QMenu::item {
    padding: 4px 20px 4px 10px;
    border-radius: %(radius_ctrl)spx;
    min-height: 30px;
    color: %(text_body)s;
    font-size: %(font_secondary)spt;
}
QMenu::item:selected {
    background-color: %(selected)s;
    color: %(text_primary)s;
}
QMenu::item:disabled { color: %(text_caption)s; }
QMenu::separator {
    height: 1px;
    background-color: %(border_soft)s;
    margin: 4px 8px;
}
QToolTip {
    background-color: #2C2C2E;
    color: #FFFFFF;
    border: 1px solid #2C2C2E;
    border-radius: %(radius_card)spx;
    padding: 4px 8px;
    font-size: %(font_caption)spt;
}

/* ══════════════════════════════════════════════════════════════════════
   以下为新界面（--ui studio）专属 objectName：窗口 / 侧栏 / inspector /
   状态栏 / 画布条 / 命令面板。窗口必须按名命名，否则这些规则不生效。
   ══════════════════════════════════════════════════════════════════════ */

/* ── 12. 顶栏 ─────────────────────────────────────────────────────── */
QFrame#TopBar {
    background-color: %(surface)s;
    border: none;
    border-bottom: 1px solid %(border_soft)s;
    min-height: %(topbar_h)spx;
    max-height: %(topbar_h)spx;
}
QLabel#BrandName {
    color: %(text_primary)s;
    font-size: %(font_title)spt;
    font-weight: 600;
}
QLabel#BrandVersion {
    color: %(text_caption)s;
    font-size: %(font_caption)spt;
}
QLineEdit#PathChip {
    background-color: %(surface)s;
    border: 1px solid %(border)s;
    border-radius: 15px;
    min-height: 30px;
    max-height: 30px;
    padding: 0 14px;
    color: %(text_secondary)s;
    font-size: %(font_secondary)spt;
}
QLineEdit#PathChip:focus {
    background-color: %(surface)s;
    border-color: %(accent)s;
    color: %(text_body)s;
}
QWidget#PathBox { background: transparent; }
QLabel#PathChipLabel {
    background-color: %(surface)s;
    border: 1px solid %(border)s;
    border-radius: 15px;
    padding: 0 14px;
    color: %(text_secondary)s;
    font-size: %(font_secondary)spt;
}
QLabel#PathChipLabel:hover {
    border-color: %(border_input)s;
    color: %(text_body)s;
}
QPushButton#TopBarAction {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: %(radius_ctrl)spx;
    min-height: %(ctl_h_sm)spx;
    padding: 0 10px;
    color: %(text_secondary)s;
    font-size: %(font_secondary)spt;
    font-weight: 500;
}
QPushButton#TopBarAction:hover {
    background-color: %(hover)s;
    color: %(text_primary)s;
}
QPushButton#TopBarAction:pressed { background-color: %(selected)s; }
QToolButton#TopBarIcon {
    background: transparent;
    border: none;
    border-radius: %(radius_ctrl)spx;
    min-width: %(ctl_h_sm)spx;
    max-width: %(ctl_h_sm)spx;
    min-height: %(ctl_h_sm)spx;
    max-height: %(ctl_h_sm)spx;
    padding: 0;
}
QToolButton#TopBarIcon:hover { background-color: %(hover)s; }
QToolButton#TopBarIcon:checked { background-color: %(selected)s; }
QToolButton#TopBarIcon:disabled { background: transparent; }
QFrame#TopBarDivider {
    background-color: %(border_soft)s;
    border: none;
    min-width: 1px;
    max-width: 1px;
}

/* ── 13. 侧栏导航 ─────────────────────────────────────────────────── */
QFrame#StudioSidebar {
    background-color: %(sidebar)s;
    border: none;
    border-right: 1px solid %(border_soft)s;
}
QToolButton#NavItem {
    background-color: transparent;
    border: none;
    border-radius: %(radius_ctrl)spx;
    min-height: %(nav_row_h)spx;
    padding: 0 12px;
    color: %(text_secondary)s;
    font-size: %(nav_text_pt)spt;
    font-weight: 500;
    text-align: left;
}
QToolButton#NavItem:hover {
    background-color: %(hover)s;
    color: %(text_body)s;
}
/* 选中态 = 中性浅灰 pill + 深色字（不是蓝底白字） */
QToolButton#NavItem:checked {
    background-color: %(selected)s;
    color: %(text_primary)s;
}
QToolButton#NavItem:checked:hover {
    background-color: %(selected)s;
    color: %(text_primary)s;
}
QToolButton#NavItem:disabled { color: %(text_caption)s; }
QLabel#NavGroupTitle {
    color: %(text_tertiary)s;
    font-size: %(nav_text_pt)spt;
    font-weight: 600;
    padding: 0 12px;
}
QToolButton#SidebarSearch {
    background-color: %(inset)s;
    border: 1px solid %(border_soft)s;
    border-radius: %(radius_ctrl)spx;
    min-height: %(nav_row_h)spx;
    padding: 0 12px;
    color: %(text_tertiary)s;
    font-size: %(nav_text_pt)spt;
    text-align: left;
}
QToolButton#SidebarSearch:hover {
    background-color: %(surface)s;
    border-color: %(border_input)s;
    color: %(text_secondary)s;
}
QFrame#SidebarSep {
    background-color: %(border_soft)s;
    border: none;
    min-height: 1px;
    max-height: 1px;
}

/* ── 14. 右侧 Inspector 头部 ───────────────────────────────────────── */
QWidget#InspectorHeader {
    background-color: %(surface)s;
    border: none;
    border-bottom: 1px solid %(border_soft)s;
}
QLabel#InspectorTitle {
    color: %(text_primary)s;
    font-size: %(font_title)spt;
    font-weight: 600;
}
QLabel#InspectorSub {
    color: %(text_tertiary)s;
    font-size: %(font_secondary)spt;
}
QToolButton#InspectorIcon {
    background: transparent;
    border: none;
    border-radius: %(radius_ctrl)spx;
    min-width: %(ctl_h_sm)spx;
    max-width: %(ctl_h_sm)spx;
    min-height: %(ctl_h_sm)spx;
    max-height: %(ctl_h_sm)spx;
    padding: 0;
}
QToolButton#InspectorIcon:hover { background-color: %(hover)s; }
QToolButton#InspectorIcon:checked { background-color: %(selected)s; }
QToolButton#InspectorIcon:disabled { background: transparent; }

/* ── 15. 底部状态栏 ───────────────────────────────────────────────── */
QFrame#StatusBar {
    background-color: %(surface)s;
    border: none;
    border-top: 1px solid %(border_soft)s;
    min-height: %(status_h)spx;
    max-height: %(status_h)spx;
}
QLabel#StatusLeft {
    color: %(text_secondary)s;
    font-size: %(font_caption)spt;
}
QLabel#StatusRight {
    color: %(text_tertiary)s;
    font-size: %(font_caption)spt;
}
QFrame#StatusSep {
    background-color: %(border_soft)s;
    border: none;
    min-width: 1px;
    max-width: 1px;
}

/* ── 16. 画布工具条（浮动药丸）────────────────────────────────────── */
QFrame#CanvasBar {
    background-color: %(surface)s;
    border: 1px solid %(border)s;
    border-radius: %(radius_card)spx;
}
QToolButton#CanvasBarBtn {
    background: transparent;
    border: none;
    border-radius: %(radius_ctrl)spx;
    min-height: %(ctl_h_sm)spx;
    max-height: %(ctl_h_sm)spx;
    padding: 0 8px;
}
QToolButton#CanvasBarBtn:hover { background-color: %(hover)s; }
QToolButton#CanvasBarBtn:checked { background-color: %(selected)s; }
QToolButton#CanvasBarBtn:disabled { background: transparent; }
QFrame#CanvasBarSep {
    background-color: %(border_soft)s;
    border: none;
    min-width: 1px;
    max-width: 1px;
    margin: 6px 2px;
}

/* 画布上的悬浮信息胶囊（文件 / 空态提示） */
QLabel#CanvasChip {
    background-color: rgba(255, 255, 255, 0.94);
    border: 1px solid %(border)s;
    border-radius: %(radius_ctrl)spx;
    padding: 4px 10px;
    color: %(text_secondary)s;
    font-size: %(font_caption)spt;
}
QLabel#CanvasEmptyHint {
    background: transparent;
    color: %(text_tertiary)s;
    font-size: %(font_secondary)spt;
}

/* 侧栏底部动作（日志 / 路径 / 关于） */
QToolButton#SidebarFootBtn {
    background: transparent;
    border: none;
    border-radius: %(radius_ctrl)spx;
    text-align: left;
    padding: 8px 12px;
    color: %(text_secondary)s;
    font-size: %(nav_text_pt)spt;
}
QToolButton#SidebarFootBtn:hover {
    background-color: %(hover)s;
    color: %(text_primary)s;
}

/* ── 17. 命令面板（Ctrl+K 风格）───────────────────────────────────── */
QDialog#CommandPalette {
    background-color: %(surface)s;
    border: 1px solid %(border)s;
    border-radius: %(radius_card)spx;
}
QLineEdit#PaletteSearch {
    background-color: %(inset)s;
    border: 1px solid %(border_input)s;
    border-radius: %(radius_ctrl)spx;
    min-height: %(ctl_h)spx;
    padding: 0 12px;
    color: %(text_primary)s;
    font-size: %(font_body)spt;
}
QLineEdit#PaletteSearch:focus {
    background-color: %(surface)s;
    border: 1px solid %(accent)s;
}
QListWidget#PaletteList {
    background-color: transparent;
    border: none;
    outline: none;
    padding: 4px;
}
QListWidget#PaletteList::item {
    min-height: %(row_h)spx;
    padding: 0 10px;
    border-radius: %(radius_ctrl)spx;
    color: %(text_body)s;
}
QListWidget#PaletteList::item:hover {
    background-color: %(hover)s;
}
/* 选中 = selected 底 + text_primary 字（不填主色） */
QListWidget#PaletteList::item:selected {
    background-color: %(selected)s;
    color: %(text_primary)s;
}
QLabel#PaletteHint {
    color: %(text_caption)s;
    font-size: %(font_caption)spt;
    padding: 4px 8px;
}
""" % TOKENS

STUDIO_QSS = _BASE + ("" if _BASE.endswith("\n") else "\n") + STUDIO_EXTRA


# ── 3b. 画布面板补充样式（clean 的 _CANVAS_AUGMENT 的 DSH 版）───────────────
# 各分析面板自带的 _CANVAS_QSS 会把 CubCanvasRoot 画成整块方角灰底；新皮肤里
# 画布是白卡内的凹陷视口，这里补圆角 + 内凹底色（追加在面板自身 QSS 之后）。
STUDIO_CANVAS_AUGMENT = """
/* ── Studio 皮肤补充（DSH）：画布面板 ── */
QWidget#CubCanvasRoot {
    background-color: %(inset)s;
    border-radius: %(radius_ctrl)spx;
}
QWidget#CubToolBar {
    background-color: %(surface)s;
    border-bottom: 1px solid %(border_soft)s;
    border-top-left-radius: %(radius_ctrl)spx;
    border-top-right-radius: %(radius_ctrl)spx;
}
QFrame#CubParams {
    background-color: %(inset)s;
    border-top: 1px solid %(border_soft)s;
    border-bottom-left-radius: %(radius_ctrl)spx;
    border-bottom-right-radius: %(radius_ctrl)spx;
}
QLabel#CubStatus {
    color: %(text_secondary)s;
    background-color: %(inset)s;
    border-top: 1px solid %(border_soft)s;
}

/* ── 数值输入框：收窄内边距与上下按钮，避免固定宽度里 "0.050" 被裁成 ").050" ── */
QSpinBox, QDoubleSpinBox {
    padding: 1px 1px 1px 4px;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    width: 12px;
    border-left: 1px solid %(border_soft)s;
}
""" % TOKENS


__all__ = [
    "TOKENS",
    "STUDIO_QSS",
    "STUDIO_CANVAS_AUGMENT",
    "ICON_MUTED",
    "ICON_ACCENT",
    "ICON_ON_PRIMARY",
    "remap_qss_studio",
]


# ══════════════════════════════════════════════════════════════════════════ #
#  4. 集成说明（窗口侧照抄即可，不需要再 import 别的东西）
# ══════════════════════════════════════════════════════════════════════════ #
# 1) 应用：``self.setStyleSheet(STUDIO_QSS)``；应用后不要再被父类的
#    ``_apply_theme()`` 用 LIGHT_QSS / CLEAN_QSS 覆盖（在 ``_apply_theme`` 里改）。
# 2) 面板内联 QSS：遍历子控件 ``wd.setStyleSheet(remap_qss_studio(wd.styleSheet()))``
#    （不要包含窗口自身，否则会把 STUDIO_QSS 再映射一遍；本模块的映射是幂等的，
#    但没必要）。画布控件追加 ``STUDIO_CANVAS_AUGMENT``。
# 3) 图标：普通按钮/导航用 ``make_icon(kind, ICON_MUTED, 16, selected_color=ICON_ACCENT)``；
#    近黑主按钮上的图标必须用 ``ICON_ON_PRIMARY``（白色），否则看不见。
# 4) objectName：``QWidget`` 子类（如 InspectorHeader、CanvasCard）要显示 QSS 背景，
#    必须 ``setAttribute(Qt.WA_StyledBackground, True)``。
# 5) 尺寸：侧栏 ``sidebar_w`` / 收起 ``sidebar_rail_w``、inspector ``inspector_w``、
#    顶栏 ``topbar_h``、状态栏 ``status_h`` 由窗口的布局设置，QSS 只做视觉约束。
