"""
widgets: 自定义 PyQt 控件
"""

from PyQt5.QtWidgets import QGroupBox


class SciFiGroupBox(QGroupBox):
    """Custom group box with sci-fi style corner decorations."""

    def __init__(self, title, parent=None):
        super().__init__(title, parent)
