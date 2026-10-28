"""面板用到的小控件：拨动开关、可点击行、状态卡片、分段选择。尺寸与配色参照 Windows 11 控件。"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton, QButtonGroup, QFrame, QHBoxLayout, QLabel, QLayout, QPushButton, QVBoxLayout,
    QWidget,
)

from workpal.ui import icons
from workpal.ui.theme import Palette

# 中文字形比同字号的西文显得大，图标需要略大于字号才协调：14px 文字配 20px 图标
ROW_ICON = 20
CARD_ICON = 20


def fitted_height(widget: QWidget, width: int) -> int:
    """按给定宽度计算布局真正需要的高度（含换行文字）。

    样式表在显示前才生效，各级布局又会缓存旧尺寸；先应用样式并让缓存失效再量。
    直接用 adjustSize() 会高估换行文字，多出的空间被分给标题，留出不均匀的空白。
    """
    for child in [widget, *widget.findChildren(QWidget)]:
        child.ensurePolished()
    layout = widget.layout()
    for item in [layout, *widget.findChildren(QLayout)]:
        item.invalidate()
    return layout.heightForWidth(width) if layout.hasHeightForWidth() else layout.sizeHint().height()


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class ToggleSwitch(QAbstractButton):
    """Windows 11 拨动开关：40×20，关闭时描边，打开时填充强调色；悬停时滑块略微放大。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(40, 20)
        self._position = 0.0
        self._hover = False
        self._on_color = '#005fb8'
        self._palette: Palette | None = None
        self._animation = QVariantAnimation(self, duration=160,
                                            easingCurve=QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._set_position)
        self.toggled.connect(self._animate)

    def sizeHint(self) -> QSize:
        return QSize(40, 20)

    def set_colors(self, palette: Palette, on_color: str) -> None:
        self._palette, self._on_color = palette, on_color
        self.update()

    def set_hover(self, hover: bool) -> None:
        self._hover = hover
        self.update()

    def set_checked_silently(self, checked: bool) -> None:
        """按真实状态更新，不触发 clicked，也不播放动画。"""
        self.blockSignals(True)
        self.setChecked(checked)
        self.blockSignals(False)
        self._animation.stop()
        self._set_position(1.0 if checked else 0.0)

    def _animate(self, checked: bool) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._position)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def _set_position(self, value) -> None:
        self._position = float(value)
        self.update()

    def enterEvent(self, event) -> None:
        self.set_hover(True)

    def leaveEvent(self, event) -> None:
        self.set_hover(False)

    def paintEvent(self, event) -> None:
        palette = self._palette
        if palette is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.4)
        on = self._position > 0.5
        track = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        radius = track.height() / 2
        if on:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self._on_color))
        else:
            painter.setPen(QPen(QColor(palette.stroke), 1.0))
            painter.setBrush(QColor(palette.hover if self._hover else palette.card))
        painter.drawRoundedRect(track, radius, radius)
        knob = 14.0 if self._hover else 12.0
        travel = self.width() - 2 * 4 - 12.0
        center_x = 4 + 6.0 + travel * self._position
        center_y = self.height() / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(palette.knob_on if on else palette.stroke))
        painter.drawEllipse(QRectF(center_x - knob / 2, center_y - knob / 2, knob, knob))


class Row(QFrame):
    """图标 + 文字 + 可选尾部控件的一行，整行可点击，悬停和按下有反馈。"""

    clicked = Signal()

    def __init__(self, glyph: str, text: str, trailing: QWidget | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.glyph = glyph
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty('state', 'normal')
        self.setFixedHeight(40)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 8, 0)
        layout.setSpacing(12)
        self.icon = QLabel()
        self.icon.setFixedSize(ROW_ICON, ROW_ICON)
        self.label = QLabel(text)
        layout.addWidget(self.icon)
        layout.addWidget(self.label, 1)
        self.trailing = trailing
        if trailing is not None:
            layout.addWidget(trailing)

    def set_colors(self, palette: Palette, icon_color: str | None = None) -> None:
        color = icon_color or palette.text2
        self.icon.setPixmap(icons.glyph(self.glyph, color, ROW_ICON, self.devicePixelRatioF()))

    def _set_state(self, state: str) -> None:
        if self.property('state') != state:
            self.setProperty('state', state)
            _repolish(self)

    def enterEvent(self, event) -> None:
        self._set_state('hover')
        if isinstance(self.trailing, ToggleSwitch):
            self.trailing.set_hover(True)

    def leaveEvent(self, event) -> None:
        self._set_state('normal')
        if isinstance(self.trailing, ToggleSwitch):
            self.trailing.set_hover(False)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._set_state('pressed')

    def mouseReleaseEvent(self, event) -> None:
        inside = self.rect().contains(event.position().toPoint())
        self._set_state('hover' if inside else 'normal')
        if event.button() == Qt.MouseButton.LeftButton and inside:
            if isinstance(self.trailing, ToggleSwitch):
                self.trailing.click()
            else:
                self.clicked.emit()


class Card(QFrame):
    """状态卡片：图标、标题、说明；tone 决定底色。可选整卡点击。"""

    clicked = Signal()

    def __init__(self, width: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedWidth(width)
        self.setProperty('tone', 'neutral')
        self.setProperty('state', 'normal')
        self._clickable = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)
        # 图标与标题同一行，图标不再孤零零悬在上方
        head = QHBoxLayout()
        head.setSpacing(8)
        self.icon = QLabel()
        self.icon.setFixedSize(CARD_ICON, CARD_ICON)
        self.title = QLabel()
        self.title.setProperty('role', 'cardTitle')
        head.addWidget(self.icon)
        head.addWidget(self.title, 1)
        layout.addLayout(head)
        self.subtitle = QLabel()
        self.subtitle.setProperty('role', 'cardText')
        self.subtitle.setWordWrap(True)
        layout.addWidget(self.subtitle)
        self.extra = QHBoxLayout()
        self.extra.setSpacing(6)
        self.extra.setContentsMargins(0, 4, 0, 0)
        layout.addLayout(self.extra)
        self._text_width = width - 24

    def set_content(self, palette: Palette, tone: str, glyph: str, title: str, subtitle: str,
                    *, clickable: bool) -> None:
        foreground, _ = palette.tone(tone)
        self.setProperty('tone', tone)
        _repolish(self)
        # 卡片统一用实心图标（网络图标本身就是实心），与行内的线条图标区分层次
        filled = f'{glyph}_filled' if f'{glyph}_filled' in icons.SVG else glyph
        self.icon.setPixmap(icons.glyph(filled, foreground, CARD_ICON, self.devicePixelRatioF()))
        self.title.setText(title)
        self.title.setStyleSheet(f'color: {palette.text};')
        self.subtitle.setText(subtitle)
        self.subtitle.setStyleSheet(f'color: {palette.text2};')
        self.subtitle.setVisible(bool(subtitle))
        # 按卡片实际文字宽度计算换行后的高度，避免 QLabel 高估留出空白
        self.subtitle.setFixedHeight(self.subtitle.heightForWidth(self._text_width))
        self._clickable = clickable
        self.setCursor(Qt.CursorShape.PointingHandCursor if clickable else Qt.CursorShape.ArrowCursor)

    def _set_state(self, state: str) -> None:
        if self.property('state') != state:
            self.setProperty('state', state)
            _repolish(self)

    def enterEvent(self, event) -> None:
        if self._clickable:
            self._set_state('hover')

    def leaveEvent(self, event) -> None:
        self._set_state('normal')

    def mouseReleaseEvent(self, event) -> None:
        if (self._clickable and event.button() == Qt.MouseButton.LeftButton
                and self.rect().contains(event.position().toPoint())):
            self.clicked.emit()


class Segmented(QFrame):
    """分段选择（如 1/2/5 分钟），选中项浮起高亮。"""

    selected = Signal(int)

    def __init__(self, options: list[tuple[int, str]], parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[int, QPushButton] = {}
        for value, text in options:
            button = QPushButton(text)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setProperty('role', 'segment')
            self.group.addButton(button, value)
            self.buttons[value] = button
            layout.addWidget(button, 1)
        self.group.idClicked.connect(self.selected.emit)

    def set_value(self, value: int) -> None:
        for key, button in self.buttons.items():
            button.setChecked(key == value)
