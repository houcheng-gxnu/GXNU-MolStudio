"""等值面色轮控件（A · 经典渐变环样式）。

自绘风格：按住拖动旋转，转一圈循环改变色相 hue(0-1)，发出 hueChanged(float)。
外观为精致化的经典渐变环：
  底部柔和投影 + 双层描边色环 + 当前色相高光中心把手 + 白色指示线及末端圆点。
外部把 hue 映射为等值面正/负相位颜色即可实现"IboView 转一圈换色"。
"""
import math

from PyQt5.QtCore import Qt, pyqtSignal, QPointF, QRectF
from PyQt5.QtGui import QColor, QPainter, QRadialGradient, QPen, QBrush
from PyQt5.QtWidgets import QWidget


class ColorWheelWidget(QWidget):
    """A · 经典渐变环；hue 0-1，顶部为 hue 0，顺时针增大。"""

    hueChanged = pyqtSignal(float)

    def __init__(self, size=84, parent=None):
        super().__init__(parent)
        self._size = size
        self._hue = 0.33
        self._dragging = False
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)

    # ── 交互 ──────────────────────────────────────────────
    def mousePressEvent(self, ev):
        self._dragging = True
        self._set_hue(self._hue_from_pos(ev.x(), ev.y()))
        self.grabMouse()

    def mouseMoveEvent(self, ev):
        if self._dragging:
            self._set_hue(self._hue_from_pos(ev.x(), ev.y()))

    def mouseReleaseEvent(self, ev):
        self._dragging = False
        self.releaseMouse()

    def _hue_from_pos(self, x, y):
        r = self._size / 2.0
        ang = math.atan2(y - r, x - r) + math.pi / 2   # 顶部 = hue 0
        if ang >= 2 * math.pi:
            ang -= 2 * math.pi
        return ang / (2 * math.pi)

    def _set_hue(self, hue):
        hue = max(0.0, min(1.0, hue))
        if abs(hue - self._hue) < 1e-4:
            return
        self._hue = hue
        self.update()
        self.hueChanged.emit(hue)

    # ── 外部接口（与原实现一致）───────────────────────────
    def set_hue(self, hue):
        self._hue = max(0.0, min(1.0, hue))
        self.update()

    def hue(self):
        return self._hue

    @staticmethod
    def hue_to_rgb(hue, sat=0.85, val=0.95):
        """hue(0-1) -> (r,g,b) 0-255 元组。"""
        c = QColor.fromHsvF(hue % 1.0, sat, val)
        return (c.red(), c.green(), c.blue())

    # ── 渲染（A · 经典渐变环）─────────────────────────────
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._draw(p)
        p.end()

    def _angle(self):
        """当前 hue 对应角度（弧度，顶部为 0）。"""
        return 2 * math.pi * self._hue - math.pi / 2

    def _draw(self, p):
        s = self._size
        r = s / 2.0
        outer = r - 2
        inner = outer - max(4, int(outer * 0.30))
        # 色环 + 双层描边（无阴影）
        self._draw_hue_ring(p, r, outer, inner, 0.85, 0.95)
        p.setPen(QPen(QColor(255, 255, 255, 150), 1))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(r - outer, r - outer, outer * 2, outer * 2))
        p.setPen(QPen(QColor(255, 255, 255, 55), 1))
        p.drawEllipse(QRectF(r - inner, r - inner, inner * 2, inner * 2))
        # 中心把手：当前色相径向渐变 + 高光
        ir = max(4, inner - 4)
        cur = QColor.fromHsvF(self._hue, 0.85, 0.95)
        grad = QRadialGradient(r, r, ir)
        grad.setColorAt(0, cur.lighter(165))
        grad.setColorAt(0.55, cur)
        grad.setColorAt(1, cur.darker(150))
        p.setPen(QPen(QColor(255, 255, 255, 190), 1))
        p.setBrush(QBrush(grad))
        p.drawEllipse(QRectF(r - ir, r - ir, ir * 2, ir * 2))
        # 指示线 + 末端圆点
        ang = self._angle()
        ex = r + (ir + 2) * math.cos(ang)
        ey = r + (ir + 2) * math.sin(ang)
        p.setPen(QPen(QColor(255, 255, 255, 235), 2))
        p.drawLine(QPointF(r, r), QPointF(ex, ey))
        dr = max(3, (outer - ir) // 4)
        p.setBrush(QColor(255, 255, 255))
        p.setPen(QPen(QColor(40, 40, 40), 1))
        p.drawEllipse(QRectF(ex - dr, ey - dr, dr * 2, dr * 2))

    @staticmethod
    def _draw_hue_ring(p, r, outer, inner, sat, val):
        """逐角度径向线画平滑色环。"""
        steps = 360
        for i in range(steps):
            ang = 2 * math.pi * i / steps - math.pi / 2
            col = QColor.fromHsvF(i / steps, sat, val)
            p.setPen(col)
            p.drawLine(int(r + inner * math.cos(ang)), int(r + inner * math.sin(ang)),
                       int(r + outer * math.cos(ang)), int(r + outer * math.sin(ang)))
