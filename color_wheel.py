"""IboView 风格的圆形色轮控件。

移植自 IboView 的色相环交互：在画布上画一个 HSV 色环，用户按住中心圆形
按钮沿环拖动旋转，hue（色相）随之改变，转一圈即循环一周。外部把 hue 映射为
等值面正/负相位颜色（负相位取互补 hue+180°）即可实现"IboView 转一圈换色"。
"""
import math
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPixmap, QRadialGradient, QBrush
from PyQt5.QtWidgets import QWidget


class ColorWheelWidget(QWidget):
    """可旋转的圆形色轮；拖动旋转改变色相，发出 hueChanged(0-1)。"""

    hueChanged = pyqtSignal(float)

    def __init__(self, size=64, parent=None):
        super().__init__(parent)
        self._size = size
        self._hue = 0.33          # 当前色相 (0-1)
        self._sat = 0.85          # 旋转只改色相，固定较高饱和度
        self._val = 0.95
        self._ring = max(8, size // 7)   # 色环厚度
        self._dragging = False
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self._render_wheel()

    # ── 色轮位图预渲染 ───────────────────────────────────
    def _render_wheel(self):
        r = self._size // 2
        pix = QPixmap(self._size, self._size)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        cx = cy = r
        outer = r - 1
        inner = max(1, outer - self._ring)
        # 逐角度画色环扇形（更平滑：每步画两像素宽度的径向线）
        steps = 360
        for i in range(steps):
            ang = 2 * math.pi * i / steps
            hue = i / steps
            col = QColor.fromHsvF(hue, self._sat, self._val)
            p.setPen(col)
            # 从内到外画径向线，形成平滑色环
            x0 = cx + inner * math.cos(ang)
            y0 = cy + inner * math.sin(ang)
            x1 = cx + outer * math.cos(ang)
            y1 = cy + outer * math.sin(ang)
            p.drawLine(int(x0), int(y0), int(x1), int(y1))
        # 外圈细描边，提升精致感
        p.setPen(QColor(255, 255, 255, 120))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(cx - outer, cy - outer, outer * 2, outer * 2)
        # 内圈细描边（色环与中心把手的分界）
        p.setPen(QColor(255, 255, 255, 70))
        p.drawEllipse(cx - inner, cy - inner, inner * 2, inner * 2)
        # 中心圆（旋转把手）
        inner_r = max(2, inner - 3)
        grad = QRadialGradient(cx, cy, inner_r)
        cur = QColor.fromHsvF(self._hue, self._sat, self._val)
        grad.setColorAt(0, cur.lighter(150))
        grad.setColorAt(0.6, cur)
        grad.setColorAt(1, cur.darker(140))
        p.setBrush(QBrush(grad))
        p.setPen(QColor(255, 255, 255, 160))
        p.drawEllipse(cx - inner_r, cy - inner_r, inner_r * 2, inner_r * 2)
        # 当前色相指示线 + 末端圆点（更醒目）
        ang = self._angle()
        ex = cx + (inner_r + self._ring) * math.cos(ang)
        ey = cy + (inner_r + self._ring) * math.sin(ang)
        p.setPen(QColor(255, 255, 255, 220))
        p.drawLine(cx, cy, int(ex), int(ey))
        p.setBrush(QBrush(QColor(255, 255, 255)))
        p.setPen(QColor(40, 40, 40))
        dot_r = max(3, self._ring // 3)
        p.drawEllipse(int(ex) - dot_r, int(ey) - dot_r, dot_r * 2, dot_r * 2)
        p.end()
        self._pix = pix

    def _angle(self):
        return 2 * math.pi * self._hue

    # ── 交互 ─────────────────────────────────────────────
    def _hue_from_pos(self, x, y):
        r = self._size // 2
        dx = x - r
        dy = y - r
        ang = math.atan2(dy, dx)
        if ang < 0:
            ang += 2 * math.pi
        return ang / (2 * math.pi)

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

    def _set_hue(self, hue):
        if abs(hue - self._hue) < 1e-4:
            return
        self._hue = hue
        self._render_wheel()
        self.update()
        self.hueChanged.emit(hue)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.drawPixmap(0, 0, self._pix)
        p.end()

    # ── 外部接口 ─────────────────────────────────────────
    def set_hue(self, hue):
        self._hue = max(0.0, min(1.0, hue))
        self._render_wheel()
        self.update()

    def hue(self):
        return self._hue

    @staticmethod
    def hue_to_rgb(hue, sat=0.85, val=0.95):
        """hue(0-1) -> (r,g,b) 0-255 元组。"""
        c = QColor.fromHsvF(hue, sat, val)
        return (c.red(), c.green(), c.blue())
