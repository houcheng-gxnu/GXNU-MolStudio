#!/usr/bin/env python3
"""
CubViewer 独立 demo 入口 — 快速预览 .cub 文件
==============================================
直接运行: python cubviewer.py
或拖放 .cub 文件到窗口。
"""
import sys
from PyQt5.QtWidgets import QApplication
from ovcanvas._glwidget import CubViewer

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = CubViewer()
    w.show()
    sys.exit(app.exec_())
