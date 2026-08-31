# -*- coding: utf-8 -*-
from PyQt5.QtWidgets import QPushButton
from PyQt5.QtCore import Qt, QPropertyAnimation, QEasingCurve, QRect, pyqtProperty
from PyQt5.QtGui import QFont, QColor, QPainter, QBrush


class NavButton(QPushButton):
    def __init__(self, text, icon_text="", parent=None):
        self._slide_offset = 0.0
        super().__init__(parent)
        self._text = text
        self._icon_text = icon_text
        self._is_active = False
        self._hover_anim = QPropertyAnimation(self, b"slide_offset")
        self._hover_anim.setDuration(180)
        self.setFixedHeight(40)
        self.setCursor(Qt.PointingHandCursor)
        font = QFont()
        font.setPointSizeF(10)
        self.setFont(font)

    def get_slide_offset(self):
        return self._slide_offset

    def set_slide_offset(self, value):
        self._slide_offset = value

    slide_offset = pyqtProperty(float, get_slide_offset, set_slide_offset)

    def set_active(self, active):
        self._is_active = active
        self.update()

    def enterEvent(self, event):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._slide_offset)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._hover_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._slide_offset)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._hover_anim.start()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        bg = QColor("#F1F5F9")
        bg_hover = QColor("#E3E8F0")
        if self._is_active:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(bg_hover))
            painter.drawRoundedRect(2, 3, w - 4, h - 6, 4, 4)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor("#1565C0")))
            painter.drawRoundedRect(2, 8, 3, h - 16, 1.5, 1.5)
        elif self._slide_offset > 0.01:
            painter.setPen(Qt.NoPen)
            c = bg
            r = int(c.red() + (bg_hover.red() - c.red()) * self._slide_offset)
            g = int(c.green() + (bg_hover.green() - c.green()) * self._slide_offset)
            b = int(c.blue() + (bg_hover.blue() - c.blue()) * self._slide_offset)
            painter.setBrush(QBrush(QColor(r, g, b)))
            painter.drawRoundedRect(2, 3, w - 4, h - 6, 4, 4)
        text_color = QColor("#2C3E50")
        if not self._is_active:
            text_color.setAlpha(160)
        painter.setPen(text_color)
        icon_rect = QRect(16, 0, 24, h)
        painter.drawText(icon_rect, Qt.AlignVCenter | Qt.AlignLeft, self._icon_text)
        text_rect = QRect(44, 0, w - 56, h)
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self._text)
        painter.end()
