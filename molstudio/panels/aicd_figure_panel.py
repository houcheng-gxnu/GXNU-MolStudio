# -*- coding: utf-8 -*-
"""
AICD 效果图页（独立查看用）
===========================

从「感应电流」工作流页算完的图会送到这里显示；也支持直接打开任意 PNG，
所以这一页可以单独给合作者看/截图，不需要跑计算。

交互：

* 滚轮缩放（以鼠标位置为中心）、左键拖动平移、双击适应窗口；
* 工具栏：打开图片 / 保存 / 适应窗口 / 原始尺寸 / 放大 / 缩小；
* 底部状态行显示图来自哪个体系、参数摘要（由工作流页在出图时带过来）。
"""

from __future__ import annotations

import os

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPainter, QPixmap
from PyQt5.QtWidgets import (QFileDialog, QGraphicsPixmapItem, QGraphicsScene,
                             QGraphicsView, QHBoxLayout, QLabel, QMessageBox,
                             QPushButton, QSizePolicy, QVBoxLayout, QWidget)


_TR = {
    "zh": {
        "open": "打开图片…",
        "save": "保存图片…",
        "fit": "适应窗口",
        "actual": "原始尺寸",
        "zoom_in": "放大",
        "zoom_out": "缩小",
        "hint": "还没有效果图。\n在「感应电流」页算完后会自动显示到这里；"
                "也可以直接「打开图片…」查看已有的 PNG。",
        "saved": "已保存：{path}",
        "opened": "已打开：{path}",
        "fail": "无法打开：{err}",
        "view_hint": "滚轮缩放 · 拖动平移 · 双击适应窗口",
    },
    "en": {
        "open": "Open image…",
        "save": "Save image…",
        "fit": "Fit window",
        "actual": "Actual size",
        "zoom_in": "Zoom in",
        "zoom_out": "Zoom out",
        "hint": "No figure yet.\nIt appears here automatically after the AICD "
                "workflow finishes; you can also open an existing PNG.",
        "saved": "Saved: {path}",
        "opened": "Opened: {path}",
        "fail": "Cannot open: {err}",
        "view_hint": "Wheel = zoom · drag = pan · double-click = fit",
    },
}


class _ZoomView(QGraphicsView):
    """支持滚轮缩放（以光标为中心）、拖动平移、双击适应的图片视图。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background:#FFFFFF; border:1px solid #D8DEE9;")
        self._scale = 1.0

    def wheelEvent(self, event):                       # noqa: N802
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.zoom(factor)

    def mouseDoubleClickEvent(self, event):            # noqa: N802
        self.fit()

    def zoom(self, factor):
        new = self._scale * factor
        if new < 0.05 or new > 40.0:
            return
        self._scale = new
        self.scale(factor, factor)

    def fit(self):
        scene = self.scene()
        if scene is None or scene.itemsBoundingRect().isEmpty():
            return
        self.resetTransform()
        self.fitInView(scene.itemsBoundingRect(), Qt.KeepAspectRatio)
        self._scale = self.transform().m11()

    def actual(self):
        self.resetTransform()
        self._scale = 1.0


class AicdFigurePanel(QWidget):
    """AICD 效果图查看页（可独立打开任意 PNG）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lang = "zh"
        self._path = ""
        self._summary = ""
        self._build_ui()
        self._apply_lang()

    def _t(self, key, **fmt):
        s = _TR.get(self.lang, _TR["zh"]).get(key, key)
        return s.format(**fmt) if fmt else s

    def set_lang(self, lang):
        self.lang = "zh" if lang == "zh" else "en"
        self._apply_lang()

    def _apply_lang(self):
        self.btn_open.setText(self._t("open"))
        self.btn_save.setText(self._t("save"))
        self.btn_fit.setText(self._t("fit"))
        self.btn_actual.setText(self._t("actual"))
        self.btn_zoom_in.setText(self._t("zoom_in"))
        self.btn_zoom_out.setText(self._t("zoom_out"))
        self._refresh_status()
        if not self._path:
            self.lbl_status.setText(self._t("hint"))
        self.lbl_view_hint.setText(self._t("view_hint"))

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        bar = QHBoxLayout()
        self.btn_open = QPushButton()
        self.btn_open.clicked.connect(self._open)
        self.btn_save = QPushButton()
        self.btn_save.clicked.connect(self._save)
        self.btn_save.setEnabled(False)
        self.btn_fit = QPushButton()
        self.btn_fit.clicked.connect(lambda: self.view.fit())
        self.btn_actual = QPushButton()
        self.btn_actual.clicked.connect(lambda: self.view.actual())
        self.btn_zoom_in = QPushButton()
        self.btn_zoom_in.clicked.connect(lambda: self.view.zoom(1.25))
        self.btn_zoom_out = QPushButton()
        self.btn_zoom_out.clicked.connect(lambda: self.view.zoom(0.8))
        for b in (self.btn_open, self.btn_save):
            bar.addWidget(b)
        bar.addSpacing(10)
        for b in (self.btn_fit, self.btn_actual, self.btn_zoom_out, self.btn_zoom_in):
            bar.addWidget(b)
        bar.addStretch(1)
        self.lbl_view_hint = QLabel()
        self.lbl_view_hint.setStyleSheet("color:#94A3B8;")
        bar.addWidget(self.lbl_view_hint)
        root.addLayout(bar)

        self.scene = QGraphicsScene(self)
        self.view = _ZoomView(self)
        self.view.setScene(self.scene)
        self.item = QGraphicsPixmapItem()
        self.item.setTransformationMode(Qt.SmoothTransformation)
        self.scene.addItem(self.item)
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(self.view, 1)

        self.lbl_status = QLabel()
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("color:#64748B;")
        root.addWidget(self.lbl_status)

    # ── 内容 ──────────────────────────────────────────────────────────────
    def set_figure(self, path, summary=""):
        """显示一张效果图（工作流页算完会调它）。"""
        if not path or not os.path.isfile(path):
            return False
        pix = QPixmap(path)
        if pix.isNull():
            return False
        self._path = path
        self._summary = summary or ""
        self.item.setPixmap(pix)
        self.scene.setSceneRect(self.item.boundingRect())
        self.view.fit()
        self.btn_save.setEnabled(True)
        self._refresh_status()
        return True

    def current_path(self):
        return self._path

    def _refresh_status(self):
        if not self._path:
            self.lbl_status.setText(self._t("hint"))
            return
        text = os.path.basename(self._path)
        if self._summary:
            text += "  ·  " + self._summary
        self.lbl_status.setText(text)

    def _open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self._t("open"),
            os.path.dirname(self._path) if self._path else "",
            "Images (*.png *.jpg *.jpeg *.bmp);;All files (*)")
        if not path:
            return
        if self.set_figure(path):
            self.lbl_status.setText(self._t("opened", path=path))
        else:
            self.lbl_status.setText(self._t("fail", err=path))

    def _save(self):
        if not self._path:
            return
        start = os.path.basename(self._path)
        path, _ = QFileDialog.getSaveFileName(
            self, self._t("save"), start, "PNG image (*.png)")
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        try:
            pix = self.item.pixmap()
            if pix.save(path, "PNG"):
                self.lbl_status.setText(self._t("saved", path=path))
                return
        except Exception as exc:                        # noqa: BLE001
            pass
        QMessageBox.warning(self, self._t("save"), self._t("fail", err=path))
