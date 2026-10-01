# -*- coding: utf-8 -*-
"""
ETSNOCV Viewer v6.0 — Chinese Entry Point

Usage:
    python -m molstudio.panels.etsnocv.main_zh
"""

import sys
import os

# 直接运行本文件时把仓库根目录加入 sys.path（包方式导入不需要）
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))

from PyQt5.QtWidgets import QApplication

from molstudio.panels.etsnocv.viewer import ETSNOCVViewer


def main():
    app = QApplication(sys.argv)
    win = ETSNOCVViewer(lang="zh")
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
