# -*- coding: utf-8 -*-
"""自定义 Qt 控件：激活倒计时弹窗、音量条。"""
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPainter, QColor
from PyQt5.QtWidgets import QDialog, QLabel, QVBoxLayout

from core.config import COUNT_DOWN_SEC


class CountDownDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.cnt = COUNT_DOWN_SEC
        self.setWindowTitle("激活成功")
        self.setFixedSize(320, 160)
        self.setWindowFlags(Qt.Dialog | Qt.WindowStaysOnTopHint)
        self.setStyleSheet("""
            QDialog{background:#121826;border:1px solid #2d88ff;border-radius:10px;}
            QLabel{color:#00ccff;font-size:14px;}
        """)
        self.label = QLabel(f"授权已激活，{self.cnt}秒后自动关闭")
        self.label.setAlignment(Qt.AlignCenter)
        lay = QVBoxLayout()
        lay.addWidget(self.label)
        self.setLayout(lay)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_cnt)
        self.timer.start(1000)
    def update_cnt(self):
        self.cnt -= 1
        self.label.setText(f"授权已激活，{self.cnt}秒后自动关闭")
        if self.cnt <= 0:
            self.timer.stop()
            self.accept()

class VolumeBar(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.vol = 15
        self.setFixedHeight(20)
        self.setStyleSheet("""
            background:#1a1a2e;
            border-radius:6px;
            border:1px solid #2d88ff;
        """)
    def set_vol(self, val):
        self.vol = max(15, min(100, val))
        self.update()
    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = int(self.width() * self.vol / 100)
        color = QColor(0, 204, 255) if self.vol < 70 else QColor(255, 90, 90)
        p.fillRect(2, 2, w-4, self.height()-4, color)
