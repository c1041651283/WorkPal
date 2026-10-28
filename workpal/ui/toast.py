"""右下角的通知卡片：同一件事（相同 key）原地更新，最多同时显示 3 张，悬停暂停倒计时。

与菜单面板一样使用不透明窗口，圆角、描边和阴影由 Windows 11 绘制，文字清晰。
出现和消失都带淡入淡出与滑动；菜单面板打开时卡片暂时隐藏并暂停倒计时，面板关闭后再显示。
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from workpal.ui import icons, native, theme
from workpal.ui.theme import Palette
from workpal.ui.widgets import fitted_height

TOAST_WIDTH = 360
MARGIN = 12          # 离屏幕边缘（任务栏）的距离
SPACING = 8          # 卡片之间的距离
SLIDE_DISTANCE = 32  # 从右侧滑入、向右滑出的距离
MAX_TOASTS = 3
ICON_SIZE = 20
# 动画时长（毫秒）：出现减速停下，消失加速离开，堆叠位置变化时平滑移动
ENTER_MS = 360
EXIT_MS = 280
MOVE_MS = 280
# 各类通知的停留时间（毫秒）；进行中的通知等结果到达后原地更新
DURATIONS = {'info': 6000, 'success': 6000, 'error': 10000, 'progress': 60000}


def _tone(palette: Palette, level: str) -> str:
    return {'success': palette.success, 'error': palette.error}.get(level, palette.accent)


class Toast(QWidget):
    closed = Signal(object)

    def __init__(self, key):
        # ToolTip 窗口：置顶、不抢焦点、不出现在任务栏，并带系统阴影。
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.key = key
        self.level = 'info'
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(TOAST_WIDTH)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.frame = QFrame(objectName='toast')
        outer.addWidget(self.frame)
        layout = QHBoxLayout(self.frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        self.icon = QLabel()
        self.icon.setFixedSize(ICON_SIZE, ICON_SIZE)
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(4)
        self.title = QLabel(objectName='title')
        self.title.setWordWrap(True)
        self.message = QLabel(objectName='message')
        self.message.setWordWrap(True)
        texts.addWidget(self.title)
        texts.addWidget(self.message)
        layout.addLayout(texts, 1)

        self.timer = QTimer(self, singleShot=True)
        self.timer.timeout.connect(self.dismiss)
        self.slide = QPropertyAnimation(self, b'pos', self)
        # 半透明期间是分层窗口，Windows 11 仍会绘制圆角和阴影；动画结束时恢复为不透明。
        self.fade = QPropertyAnimation(self, b'windowOpacity', self)
        self.fade.finished.connect(self._fade_finished)
        self._after_fade = None
        self._closing = False
        self._shown = False
        self._held = False       # 面板打开期间暂停：不显示，倒计时停止
        self._remaining = 0

    def set_content(self, title: str, message: str, level: str) -> None:
        palette = theme.current()
        self.level = level
        self.frame.setStyleSheet(
            f'#toast {{ background: {palette.bg}; }}'
            f'QLabel {{ background: transparent; }}'
            f'#title {{ color: {palette.text}; font-weight: 600; }}'
            f'#message {{ color: {palette.text2}; font-size: 13px; }}')
        native.round_window(self, palette.error if level == 'error' else palette.border)
        self.icon.setPixmap(icons.glyph(level if level in DURATIONS else 'info', _tone(palette, level),
                                        ICON_SIZE, self.devicePixelRatioF()))
        self.title.setText(title)
        self.message.setText(message)
        self.message.setVisible(bool(message))
        self.setFixedHeight(fitted_height(self, TOAST_WIDTH))
        self.restart_timer()

    def _duration(self) -> int:
        return DURATIONS.get(self.level, DURATIONS['info'])

    def restart_timer(self) -> None:
        if self._held:
            self._remaining = self._duration()  # 暂停期间内容更新：显示后重新计时
        elif not self.underMouse():
            self.timer.start(self._duration())

    # ---------------------------------------------------------------- 动画

    @staticmethod
    def _animate(animation: QPropertyAnimation, start, end, duration: int,
                 curve: QEasingCurve.Type) -> None:
        animation.stop()
        animation.setDuration(duration)
        animation.setEasingCurve(curve)
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.start()

    def _slide_to(self, target: QPoint, duration: int, curve: QEasingCurve.Type) -> None:
        self._animate(self.slide, self.pos(), target, duration, curve)

    def _fade_to(self, opacity: float, duration: int, curve: QEasingCurve.Type, then=None) -> None:
        self._after_fade = then
        self._animate(self.fade, self.windowOpacity(), opacity, duration, curve)

    def _fade_finished(self) -> None:
        then, self._after_fade = self._after_fade, None
        if then is not None:
            then()

    def place(self, target: QPoint) -> None:
        """第一次显示时从右侧淡入滑入，之后（堆叠位置变化时）平滑移动到新位置。"""
        if not self._shown:
            self._shown = True
            self.setWindowOpacity(0.0)
            self.move(target.x() + SLIDE_DISTANCE, target.y())
            self.show()
            self._slide_to(target, ENTER_MS, QEasingCurve.Type.OutCubic)
            self._fade_to(1.0, ENTER_MS, QEasingCurve.Type.OutCubic)
            return
        if self.slide.endValue() == target and self.slide.state() == QPropertyAnimation.State.Running:
            return
        self._slide_to(target, MOVE_MS, QEasingCurve.Type.InOutCubic)

    def _leave(self, then) -> None:
        """向右淡出滑走，结束后执行 then。"""
        if not self.isVisible():
            then()
            return
        self._slide_to(self.pos() + QPoint(SLIDE_DISTANCE, 0), EXIT_MS, QEasingCurve.Type.InCubic)
        self._fade_to(0.0, EXIT_MS, QEasingCurve.Type.InCubic, then)

    # ---------------------------------------------------------------- 暂停与关闭

    def hold(self) -> None:
        """暂时隐藏并记住剩余时间，release 后继续。"""
        if self._held or self._closing:
            return
        self._held = True
        self._remaining = self.timer.remainingTime() if self.timer.isActive() else self._duration()
        self.timer.stop()
        self._shown = False

        def hidden():
            if self._held:
                self.hide()
        self._leave(hidden)

    def release(self) -> None:
        if not self._held or self._closing:
            return
        self._held = False
        self.timer.start(max(self._remaining, 1000))

    def dismiss(self) -> None:
        if self._closing:
            return
        self._closing = True
        self.timer.stop()
        self.closed.emit(self)  # 其余卡片立即开始让位

        def finish():
            self.hide()
            self.deleteLater()
        self._leave(finish)

    def enterEvent(self, event) -> None:
        self.timer.stop()

    def leaveEvent(self, event) -> None:
        if not self._closing:
            self.restart_timer()

    def mouseReleaseEvent(self, event) -> None:
        self.dismiss()


class ToastManager:
    def __init__(self):
        self.toasts: list[Toast] = []
        self._suspended = False

    def show(self, title: str, message: str = '', level: str = 'info', key=None) -> Toast:
        toast = next((t for t in self.toasts if key is not None and t.key == key and not t._closing), None)
        if toast is None:
            toast = Toast(key)
            toast.closed.connect(self._remove)
            self.toasts.append(toast)
            if self._suspended:
                toast.hold()
            while len([t for t in self.toasts if not t._closing]) > MAX_TOASTS:
                next(t for t in self.toasts if not t._closing).dismiss()
        toast.set_content(title, message, level)
        self._layout()
        return toast

    def set_suspended(self, suspended: bool) -> None:
        """菜单面板打开时调用：通知不与面板同时出现，面板关闭后按剩余时间继续显示。"""
        if suspended == self._suspended:
            return
        self._suspended = suspended
        for toast in [t for t in self.toasts if not t._closing]:
            toast.hold() if suspended else toast.release()
        self._layout()

    def _remove(self, toast: Toast) -> None:
        if toast in self.toasts:
            self.toasts.remove(toast)
        self._layout()

    def targets(self) -> dict[Toast, QPoint]:
        """从屏幕右下角向上堆叠，最新的在最下面。"""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return {}
        area = screen.availableGeometry()
        bottom = area.bottom() + 1 - MARGIN
        positions = {}
        for toast in reversed([t for t in self.toasts if not t._closing]):
            top = bottom - toast.height()
            positions[toast] = QPoint(area.right() + 1 - MARGIN - toast.width(), top)
            bottom = top - SPACING
        return positions

    def _layout(self) -> None:
        if self._suspended:
            return
        for toast, target in self.targets().items():
            toast.place(target)
