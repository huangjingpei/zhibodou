# -*- coding: utf-8 -*-
"""自绘单色线性图标（QPainter 版）。

不用彩色 emoji：它在深色界面里颜色不可控、不同系统字形还不一致，会破坏层次
感。这里用 QPainter 画 18px 线性图标，单色、可跟随输入框聚焦变色、跨平台一致。

绘制坐标全部按 size 比例给出，与 zhibodou-ai 项目 `src/gui/login.py` 的
Tkinter 版本逐点对应，保证两个项目图标形状一致。

角度约定：Qt 的 drawArc 角度单位是 1/16 度，0° 在 3 点钟方向、逆时针为正，
与 Tkinter create_arc 一致，因此上半弧同样是 (0, 180*16)。
"""
from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QPainter, QPen, QPixmap

ICON_SIZE = 18


def _pen(color, width=1.6):
    p = QPen(QColor(color))
    p.setWidthF(width)
    p.setCapStyle(Qt.RoundCap)
    p.setJoinStyle(Qt.RoundJoin)
    return p


def _draw_user(p, s, color):
    """用户：头部圆 + 肩部弧。"""
    p.setPen(_pen(color))
    p.setBrush(Qt.NoBrush)
    cx = s / 2
    hr = s * 0.17
    p.drawEllipse(QRectF(cx - hr, s * 0.24 - hr, hr * 2, hr * 2))
    p.drawArc(QRectF(cx - s * 0.27, s * 0.42, s * 0.54, s * 0.58), 0, 180 * 16)


def _draw_lock(p, s, color):
    """锁：上半弧（锁梁）+ 圆角矩形（锁体）。"""
    cx = s / 2
    p.setPen(_pen(color))
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(cx - s * 0.17, s * 0.20, s * 0.34, s * 0.42), 0, 180 * 16)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawRoundedRect(
        QRectF(cx - s * 0.27, s * 0.54, s * 0.54, s * 0.34),
        s * 0.06, s * 0.06,
    )


def _draw_key(p, s, color):
    """钥匙：圆环 + 斜杆 + 两道齿。"""
    p.setPen(_pen(color))
    p.setBrush(Qt.NoBrush)
    r = s * 0.15
    cx, cy = s * 0.34, s * 0.36
    p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
    p.drawLine(int(cx + r * 0.7), int(cy + r * 0.7), int(s * 0.84), int(s * 0.80))
    p.drawLine(int(s * 0.70), int(s * 0.63), int(s * 0.79), int(s * 0.54))
    p.drawLine(int(s * 0.78), int(s * 0.71), int(s * 0.87), int(s * 0.62))


def _draw_card(p, s, color):
    """卡密：卡片描边 + 磁条 + 一小段号码。"""
    p.setPen(_pen(color, 1.5))
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(s * 0.12, s * 0.24, s * 0.76, s * 0.54))
    p.drawLine(int(s * 0.12), int(s * 0.42), int(s * 0.88), int(s * 0.42))
    p.drawLine(int(s * 0.24), int(s * 0.60), int(s * 0.60), int(s * 0.60))


ICON_PAINTERS = {
    "user": _draw_user,
    "lock": _draw_lock,
    "key": _draw_key,
    "card": _draw_card,
}


def icon_pixmap(key, color, size=ICON_SIZE, ratio=1):
    """把指定图标渲染成透明底 QPixmap，供 QLabel.setPixmap 使用。

    ratio 传入 devicePixelRatio 可在高分屏下保持锐利。
    """
    painter_fn = ICON_PAINTERS.get(key)
    px = QPixmap(int(size * ratio), int(size * ratio))
    px.fill(Qt.transparent)
    if painter_fn is None:
        return px
    px.setDevicePixelRatio(ratio)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.scale(ratio, ratio)
    painter_fn(p, size, color)
    p.end()
    return px
