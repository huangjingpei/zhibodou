# -*- coding: utf-8 -*-
"""自定义 Qt 控件：音量条。

风格与全局深海蓝视觉系统（ui.theme）保持一致，不在本文件内联写死颜色。
"""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPainter, QColor
from PyQt5.QtWidgets import QLabel

from ui import theme


class VolumeBar(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.vol = 0
        self.setFixedHeight(20)
        self.setStyleSheet(
            f"background-color:{theme.SURFACE_SOFT};"
            f"border-radius:6px;border:1px solid {theme.BORDER};")

    def set_vol(self, val):
        self.vol = max(0, min(100, int(val)))
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = max(0, int((self.width() - 4) * self.vol / 100))
        color = QColor(theme.CYAN) if self.vol < 70 else QColor(theme.RED)
        if w:
            p.fillRect(2, 2, w, self.height() - 4, color)
