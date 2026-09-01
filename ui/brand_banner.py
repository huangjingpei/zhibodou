# -*- coding: utf-8 -*-
"""登录窗口左侧品牌 banner（渐变背景 + 装饰 + logo + 文字层级）。

采用靛青到青蓝的水平渐变、四角装饰圆点/圆环和极淡网格，以
「logo 字母 > 项目名 > 产品定位 > 版本/版权」建立四级文字层次。

全部绘制按控件宽高比例计算，因此换尺寸不会错位。
"""
from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QLinearGradient, QPainter, QPen
from PyQt5.QtWidgets import QWidget

from ui import theme
from core.config import APP_VERSION


class BrandBanner(QWidget):
    """品牌区。直接 addWidget 即可，无需外部驱动重绘。"""

    def __init__(self, version=APP_VERSION, parent=None):
        super().__init__(parent)
        self.version = version
        # 背景自绘，关闭系统背景填充以免盖掉渐变
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAutoFillBackground(False)

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        if w <= 1 or h <= 1:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)

        self._paint_gradient(p, w, h)
        self._paint_grid(p, w, h)
        self._paint_decorations(p, w, h)
        self._paint_brand(p, w, h)
        p.end()

    # ---------------------------------------------------------------- 背景渐变
    def _paint_gradient(self, p, w, h):
        g = QLinearGradient(0, 0, w, 0)
        g.setColorAt(0.0, QColor(theme.BANNER_DARK))
        g.setColorAt(1.0, QColor(theme.BANNER_LIGHT))
        p.fillRect(0, 0, w, h, g)

    # ---------------------------------------------------------------- 极淡网格
    def _paint_grid(self, p, w, h):
        """只提供空间层次，不与品牌文字争夺注意力。

        Tkinter 版用 stipple="gray12" 做点阵透明，Qt 这里换成等效的低 alpha。
        """
        pen = QPen(QColor(131, 169, 210, 30))
        pen.setWidth(1)
        p.setPen(pen)
        for x in range(0, w, 80):
            p.drawLine(x, 0, x, h)
        for y in range(0, h, 80):
            p.drawLine(0, y, w, y)

    # ---------------------------------------------------------------- 四角装饰
    def _paint_decorations(self, p, w, h):
        # ① 实心点（极淡的蓝白，与渐变底色自然融合）
        p.setPen(Qt.NoPen)
        for cx, cy, rr, color in (
            (w * 0.10, h * 0.09, 13, "#93c5fd"),
            (w * 0.90, h * 0.93, 20, "#bfdbfe"),
            (w * 0.95, h * 0.07, 9, "#dbeafe"),
        ):
            p.setBrush(QColor(color))
            p.drawEllipse(QRectF(cx - rr, cy - rr, rr * 2, rr * 2))
        # ② 描边圆环（空心，带一点科技感）
        p.setBrush(Qt.NoBrush)
        for cx, cy, rr, color, lw in (
            (w * 0.10, h * 0.09, 26, "#bfdbfe", 2),
            (w * 0.90, h * 0.93, 34, "#93c5fd", 2),
        ):
            pen = QPen(QColor(color))
            pen.setWidth(lw)
            p.setPen(pen)
            p.drawEllipse(QRectF(cx - rr, cy - rr, rr * 2, rr * 2))

    # ---------------------------------------------------------------- 品牌文字
    def _paint_brand(self, p, w, h):
        cx, cy = w / 2, h * 0.34
        rr = 56

        # L0 logo 圆环 + 字母
        pen = QPen(QColor(theme.BANNER_TEXT))
        pen.setWidth(2)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(cx - rr, cy - rr, rr * 2, rr * 2))

        p.setPen(QColor(theme.BANNER_TEXT))
        p.setFont(theme.font_en(24, bold=True))
        p.drawText(QRectF(cx - rr, cy - rr, rr * 2, rr * 2), Qt.AlignCenter, "ZD")

        # 顶部产品线标签
        p.setPen(QColor(theme.BANNER_SUB))
        p.setFont(theme.font_en(9, bold=True))
        p.drawText(QRectF(0, 42 - 10, w, 20), Qt.AlignCenter, "MATRIX LIVE ROUTING")

        # L1 项目名（最大号 + bold + 纯白）
        p.setPen(QColor(theme.BANNER_TEXT))
        p.setFont(theme.font(theme.FS_DISPLAY, bold=True))
        p.drawText(QRectF(0, cy + rr + 38 - 24, w, 48), Qt.AlignCenter, "智播豆")

        # L2 副标题（小号 + 淡蓝，弱化）
        p.setPen(QColor(theme.BANNER_SUB))
        p.setFont(theme.font(theme.FS_CAPTION))
        p.drawText(QRectF(0, cy + rr + 76 - 14, w, 28), Qt.AlignCenter,
                   "矩阵转发 · 直播推流系统")

        # L3 版本 / 版权（最弱，退到更淡的蓝）
        p.setPen(QColor(theme.BANNER_FAINT))
        p.setFont(theme.font_en(theme.FS_SMALL))
        p.drawText(QRectF(0, h - 56 - 12, w, 24), Qt.AlignCenter, "v %s" % self.version)
        p.setFont(theme.font(theme.FS_TINY))
        p.drawText(QRectF(0, h - 30 - 12, w, 24), Qt.AlignCenter,
                   "© 杭州智鑫科技 · 智播豆")
