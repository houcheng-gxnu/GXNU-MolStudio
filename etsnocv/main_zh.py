# -*- coding: utf-8 -*-
"""
ETSNOCV Viewer v6.0 — Chinese Entry Point

Usage:
    python -m etsnocv.main_zh
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication

from etsnocv.viewer import ETSNOCVViewer


def main():
    app = QApplication(sys.argv)
    win = ETSNOCVViewer(lang="zh")
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
