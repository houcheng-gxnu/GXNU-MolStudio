# -*- coding: utf-8 -*-
"""
ui_icons.py — MolStudio 矢量图标库（纯 QPainter 现画，零图片资源）
=================================================================

为什么不用图片/图标字体：
- 不引入任何 .png/.svg/字体文件，**不增加打包体积**，也不会有资源路径找不到的问题
  （PyInstaller onedir 下 `_internal` 路径问题很常见）；
- 任意颜色、任意尺寸，2x 超采样保证 HiDPI 下不糊；
- 图标随主题色走，换皮肤不用重新出图。

用法
----
    from molstudio.ui.ui_icons import make_icon, icon_pixmap
    btn.setIcon(make_icon("save", "#64748B", 16))

`make_icon` 可以额外给一个 `selected_color`，会同时写入 QIcon 的 Selected 状态，
这样 QListWidget / QTabBar 选中时会自动换成高亮色（否则选中项图标还是灰的，
和变蓝的文字不搭）。
"""

from __future__ import annotations

import math

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

# 所有可用图标名（供自检/文档用）
KINDS = (
    # 分子 / 计算化学
    "orbital", "molecule", "atom", "bond", "wave", "cube", "axes", "layers",
    "thermal", "chart", "grid", "sigma",
    # 界面 / 通用
    "folder", "save", "download", "upload", "eye", "play", "stop", "pause",
    "search", "sun", "moon", "gear", "menu", "close", "chevron",
    "arrow", "up", "down", "left", "right", "plus", "minus", "check",
    "info", "help", "target", "filter", "link", "list", "table", "clock",
)


def icon_pixmap(kind: str, color: str = "#4A5568", size: int = 20,
                width: float = 1.6) -> QPixmap:
    """按名字画一个线性矢量图标。

    以 24×24 为设计基准（`u = size/24`），先按 2 倍尺寸绘制再设 devicePixelRatio，
    这样在高 DPI 下边缘依然锐利。
    """
    ss = 2
    pm = QPixmap(int(size * ss), int(size * ss))
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.scale(ss, ss)
    pen = QPen(QColor(color), width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)

    s = float(size)
    c = s / 2.0
    u = s / 24.0
    fill = QColor(color)

    def poly(*pts):
        p.drawPolygon(*[QPointF(x * u, y * u) for x, y in pts])

    def line(x1, y1, x2, y2):
        p.drawLine(QPointF(x1 * u, y1 * u), QPointF(x2 * u, y2 * u))

    def ellipse(cx, cy, rx, ry):
        p.drawEllipse(QPointF(cx * u, cy * u), rx * u, ry * u)

    def rect(x, y, w, h, r=0.0):
        if r:
            p.drawRoundedRect(QRectF(x * u, y * u, w * u, h * u), r * u, r * u)
        else:
            p.drawRect(QRectF(x * u, y * u, w * u, h * u))

    # ── 分子 / 计算化学 ──────────────────────────────────────────────
    if kind == "orbital":                       # 两个轨道瓣
        ellipse(c - 4.5, c, 4.5, 8)
        ellipse(c + 4.5, c, 4.5, 8)
        line(c, c - 9, c, c + 9)
    elif kind == "molecule":                    # 三球两键
        line(c - 3, c + 4, c + 5, c - 4)
        p.setBrush(fill)
        ellipse(c - 5, c + 6, 3.2, 3.2)
        ellipse(c + 6, c - 5.5, 3.0, 3.0)
        p.setBrush(Qt.NoBrush)
        ellipse(c + 3.5, c + 5.5, 2.4, 2.4)
    elif kind == "atom":                        # 原子核 + 轨道环
        ellipse(c, c, 2.4, 2.4)
        p.save()
        p.translate(c, c)
        for ang in (30, -30, 90):
            p.save()
            p.rotate(ang)
            p.drawEllipse(QRectF(-9 * u, -3.6 * u, 18 * u, 7.2 * u))
            p.restore()
        p.restore()
    elif kind == "bond":                        # 双键
        line(4, c, c - 4, c)
        line(c + 4, c, 20, c)
        line(4, c + 2.6, c - 4, c + 2.6)
        line(c + 4, c + 2.6, 20, c + 2.6)
    elif kind == "wave":                        # 正弦波（ESP/光谱）
        path = QPainterPath(QPointF(3 * u, c * u))
        for i in range(1, 25):
            path.lineTo(QPointF((3 + i * 0.78) * u,
                                (c - 7 * math.sin(i / 24.0 * 3.2 * math.pi)) * u))
        p.drawPath(path)
    elif kind == "cube":                        # 等轴立方（CUB 文件）
        poly((12, 4), (20, 8), (20, 16), (12, 20), (4, 16), (4, 8))
        line(4, 8, 12, 12)
        line(20, 8, 12, 12)
        line(12, 20, 12, 12)
    elif kind == "axes":                        # 坐标轴
        line(5, 19, 5, 5)
        line(5, 19, 19, 19)
        line(5, 19, 13, 11)
    elif kind == "layers":                      # 叠层
        for dy in (0, 5, 10):
            poly((12, 3 + dy), (20, 6 + dy), (12, 9 + dy), (4, 6 + dy))
    elif kind == "thermal":                     # 热力学漏斗
        line(4, 5, 20, 5)
        line(4, 5, 14, 14)
        line(20, 5, 14, 14)
        line(14, 14, 14, 19)
    elif kind == "chart":                       # 柱状图
        for i, h in enumerate((5, 10, 7, 13)):
            x = 4 + i * 4.4
            line(x, c + 8, x, c + 8 - h)
        line(3, c + 9, 21, c + 9)
    elif kind == "grid":                        # 九宫格
        rect(4, 4, 16, 16)
        line(c, 4, c, 20)
        line(4, c, 20, c)
    elif kind == "sigma":                       # σ/求和符号
        line(5, 5, 19, 5)
        line(5, 5, 12, 12)
        line(12, 12, 5, 19)
        line(5, 19, 19, 19)
    # ── 界面 / 通用 ────────────────────────────────────────────────
    elif kind == "folder":
        path = QPainterPath(QPointF(3.5 * u, 19 * u))
        path.lineTo(3.5 * u, 6 * u)
        path.lineTo(10 * u, 6 * u)
        path.lineTo(12 * u, 8.5 * u)
        path.lineTo(20.5 * u, 8.5 * u)
        path.lineTo(20.5 * u, 19 * u)
        path.closeSubpath()
        p.drawPath(path)
    elif kind == "save":                        # 软盘
        rect(4, 4, 16, 16)
        rect(8, 4, 8, 6)
        rect(8, 14, 8, 6)
    elif kind == "download":                    # 下箭头 + 托盘
        line(c, 4, c, 14)
        line(c - 4, 10, c, 14)
        line(c + 4, 10, c, 14)
        line(5, 17, 5, 19)
        line(5, 19, 19, 19)
        line(19, 19, 19, 17)
    elif kind == "upload":                      # 上箭头 + 托盘
        line(c, 14, c, 4)
        line(c - 4, 8, c, 4)
        line(c + 4, 8, c, 4)
        line(5, 17, 5, 19)
        line(5, 19, 19, 19)
        line(19, 19, 19, 17)
    elif kind == "eye":
        path = QPainterPath(QPointF(3 * u, c * u))
        path.quadTo(QPointF(c * u, (c - 9) * u), QPointF(21 * u, c * u))
        path.quadTo(QPointF(c * u, (c + 9) * u), QPointF(3 * u, c * u))
        p.drawPath(path)
        ellipse(c, c, 2.6, 2.6)
    elif kind == "play":
        p.setBrush(fill)
        poly((7, 4), (20, 12), (7, 20))
    elif kind == "stop":
        p.setBrush(fill)
        rect(6, 6, 12, 12, 1.6)
    elif kind == "pause":
        p.setBrush(fill)
        rect(7, 5, 4, 14, 1.2)
        rect(13, 5, 4, 14, 1.2)
    elif kind == "search":
        ellipse(10.5, 10.5, 6, 6)
        line(15, 15, 20, 20)
    elif kind == "sun":
        ellipse(c, c, 4.2, 4.2)
        for i in range(8):
            a = math.radians(i * 45)
            line(c + 7 * math.cos(a), c + 7 * math.sin(a),
                 c + 9.6 * math.cos(a), c + 9.6 * math.sin(a))
    elif kind == "moon":
        path = QPainterPath(QPointF(15 * u, 4 * u))
        path.arcTo(QRectF(4 * u, 4 * u, 16 * u, 16 * u), 90, -230)
        path.quadTo(QPointF(11 * u, c * u), QPointF(15 * u, 4 * u))
        p.drawPath(path)
    elif kind == "gear":
        ellipse(c, c, 4, 4)
        for i in range(8):
            a = math.radians(i * 45)
            line(c + 6.5 * math.cos(a), c + 6.5 * math.sin(a),
                 c + 9.5 * math.cos(a), c + 9.5 * math.sin(a))
    elif kind == "menu":
        for dy in (7, 12, 17):
            line(5, dy, 19, dy)
    elif kind == "close":
        line(7, 7, 17, 17)
        line(17, 7, 7, 17)
    elif kind == "chevron":
        p.drawPolyline(QPointF(9 * u, 6 * u), QPointF(15 * u, 12 * u), QPointF(9 * u, 18 * u))
    elif kind == "arrow":
        line(5, 19, 18, 6)
        line(12, 6, 18, 6)
        line(18, 6, 18, 12)
    elif kind == "up":
        line(c, 19, c, 5)
        line(c - 5, 11, c, 5)
        line(c + 5, 11, c, 5)
    elif kind == "down":
        line(c, 5, c, 19)
        line(c - 5, 13, c, 19)
        line(c + 5, 13, c, 19)
    elif kind == "left":
        line(19, c, 5, c)
        line(11, c - 5, 5, c)
        line(11, c + 5, 5, c)
    elif kind == "right":
        line(5, c, 19, c)
        line(13, c - 5, 19, c)
        line(13, c + 5, 19, c)
    elif kind == "plus":
        line(c, 5, c, 19)
        line(5, c, 19, c)
    elif kind == "minus":
        line(5, c, 19, c)
    elif kind == "check":
        p.drawPolyline(QPointF(5 * u, 12.5 * u), QPointF(10 * u, 17 * u), QPointF(19 * u, 7 * u))
    elif kind == "info":
        ellipse(c, c, 8.6, 8.6)
        line(c, 11, c, 17)
        p.setBrush(fill)
        ellipse(c, 7.6, 0.9, 0.9)
        p.setBrush(Qt.NoBrush)
    elif kind == "help":
        ellipse(c, c, 8.6, 8.6)
        path = QPainterPath(QPointF(9.2 * u, 9.5 * u))
        path.quadTo(QPointF(9.6 * u, 6.6 * u), QPointF(12.2 * u, 6.8 * u))
        path.quadTo(QPointF(15 * u, 7.0 * u), QPointF(14.6 * u, 10.0 * u))
        path.quadTo(QPointF(14.2 * u, 12.2 * u), QPointF(12.2 * u, 12.8 * u))
        path.lineTo(QPointF(12.0 * u, 14.6 * u))
        p.drawPath(path)
        p.setBrush(fill)
        ellipse(c, 17.4, 0.9, 0.9)
        p.setBrush(Qt.NoBrush)
    elif kind == "target":
        ellipse(c, c, 8.4, 8.4)
        ellipse(c, c, 4.4, 4.4)
        p.setBrush(fill)
        ellipse(c, c, 1.4, 1.4)
        p.setBrush(Qt.NoBrush)
    elif kind == "filter":
        poly((4, 5), (20, 5), (14, 12), (14, 19), (10, 17), (10, 12))
    elif kind == "link":
        line(9, 12, 15, 12)
        p.save()
        p.translate(9 * u, 12 * u)
        p.rotate(-45)
        p.drawRoundedRect(QRectF(-6 * u, -3.2 * u, 12 * u, 6.4 * u), 3.2 * u, 3.2 * u)
        p.restore()
        p.save()
        p.translate(15 * u, 12 * u)
        p.rotate(-45)
        p.drawRoundedRect(QRectF(-6 * u, -3.2 * u, 12 * u, 6.4 * u), 3.2 * u, 3.2 * u)
        p.restore()
    elif kind == "list":
        for i, dy in enumerate((7, 12, 17)):
            p.setBrush(fill)
            ellipse(5.5, dy, 1.2, 1.2)
            p.setBrush(Qt.NoBrush)
            line(9, dy, 19, dy)
    elif kind == "table":
        rect(3.5, 5, 17, 14)
        line(3.5, 10, 20.5, 10)
        line(c, 5, c, 19)
    elif kind == "clock":
        ellipse(c, c, 8.6, 8.6)
        line(c, c, c, 7)
        line(c, c, 16, c + 2)
    else:                                        # 未知名字 → 画一个圆点，避免静默失败
        p.setBrush(fill)
        ellipse(c, c, 2.5, 2.5)

    p.end()
    pm.setDevicePixelRatio(ss)
    return pm


def make_icon(kind: str, color: str = "#4A5568", size: int = 20, width: float = 1.6,
              selected_color: str | None = None) -> QIcon:
    """构造 QIcon。给了 `selected_color` 时同时写入 Selected 状态，
    QListWidget / QTabBar 等选中项会自动切到高亮色。"""
    ic = QIcon()
    ic.addPixmap(icon_pixmap(kind, color, size, width), QIcon.Normal)
    if selected_color:
        ic.addPixmap(icon_pixmap(kind, selected_color, size, width), QIcon.Selected)
    return ic


def available() -> tuple:
    """返回所有可用图标名。"""
    return KINDS
