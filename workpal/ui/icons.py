"""把内嵌的矢量图标绘制成指定颜色的位图，并合成托盘图标。

Fluent 图标在 16/20/24 像素各有手工调整的版本，按实际物理像素选用最接近的版本，线条才清晰。
"""

from __future__ import annotations

import functools

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from workpal.ui.glyphs import SVG

# 托盘图标：渐变圆角色块 + 白色图形，颜色表示网络状态；保持在线用紫色圆点表示
TRAY_GRADIENTS = {  # (上, 下)
    'wifi': ('#3a8dde', '#0a5fc2'),
    'ethernet': ('#2fb36b', '#0b7f43'),
    'switching': ('#ffab3d', '#e07800'),
    'unknown': ('#8a8f96', '#5d6268'),
}
BADGE_COLOR = '#a259e6'
TRAY_SIZES = (16, 20, 24, 32, 40, 48, 64)


def variant(name: str, pixels: int) -> int:
    """选用设计尺寸：有正好的用正好的，否则用略大的缩小，都没有时用最大的。"""
    sizes = sorted(SVG[name])
    if pixels in sizes:
        return pixels
    larger = [size for size in sizes if size > pixels]
    return larger[0] if larger and larger[0] <= pixels * 1.5 else sizes[-1]


@functools.lru_cache(maxsize=512)
def _renderer(name: str, design: int, color: str) -> QSvgRenderer:
    svg = SVG[name][design].replace('currentColor', color)
    return QSvgRenderer(QByteArray(svg.encode('utf-8')))


def _draw(painter: QPainter, name: str, color: str, rect: QRectF) -> None:
    _renderer(name, variant(name, round(rect.width())), color).render(painter, rect)


@functools.lru_cache(maxsize=512)
def glyph(name: str, color: str, size: int = 16, ratio: float = 1.0) -> QPixmap:
    """按设备像素比绘制整数像素的位图，高分屏下依然清晰。"""
    pixels = max(1, round(size * ratio))
    pixmap = QPixmap(pixels, pixels)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    _draw(painter, name, color, QRectF(0, 0, pixels, pixels))
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def tray_pixmap(name: str, badge: bool, size: int) -> QPixmap:
    """渐变圆角色块 + 大号白色图形；badge 为真时在右下角挖出一圈透明缝隙再画紫色圆点，任何底色上都清楚。"""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    top, bottom = TRAY_GRADIENTS.get(name, TRAY_GRADIENTS['unknown'])
    gradient = QLinearGradient(QPointF(0, 0), QPointF(0, size))
    gradient.setColorAt(0, QColor(top))
    gradient.setColorAt(1, QColor(bottom))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    radius = size * 0.25
    painter.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)
    pad = size * 0.12
    _draw(painter, name, '#ffffff', QRectF(pad, pad, size - 2 * pad, size - 2 * pad))
    if badge:
        diameter = size * 0.44
        gap = max(1.0, size * 0.08)
        rect = QRectF(size - diameter, size - diameter, diameter, diameter)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.drawEllipse(rect.adjusted(-gap, -gap, gap, gap))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setBrush(QColor(BADGE_COLOR))
        painter.drawEllipse(rect)
    painter.end()
    return pixmap


@functools.lru_cache(maxsize=16)
def tray_icon(name: str, badge: bool) -> QIcon:
    icon = QIcon()
    for size in TRAY_SIZES:
        icon.addPixmap(tray_pixmap(name, badge, size))
    return icon
