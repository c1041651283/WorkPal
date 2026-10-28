"""Qt 托盘程序：托盘图标、菜单面板和通知卡片，实现 workpal.tray.View。"""

from __future__ import annotations

import logging
import sys
import threading
import time

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from workpal import tray
from workpal.ui import icons, theme
from workpal.ui.panel import Panel
from workpal.ui.toast import ToastManager

logger = logging.getLogger(__name__)

STATUS_POLL_MS = 5000
# 面板因点击托盘图标而失焦关闭后，同一次点击不再把它重新打开
REOPEN_GUARD_SECONDS = 0.3


class QtView(QObject):
    """后台线程调用 notify/refresh/quit 时，经由信号排队到界面线程执行。"""

    notify_requested = Signal(str, str, str, object)
    refresh_requested = Signal()
    quit_requested = Signal()

    def notify(self, title: str, message: str = '', *, level: str = 'info', key=None) -> None:
        logger.info('[通知] %s：%s', title, message)
        self.notify_requested.emit(title, message, level, key)

    def refresh(self) -> None:
        self.refresh_requested.emit()

    def quit(self) -> None:
        self.quit_requested.emit()


class TrayApp(QObject):
    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.view = QtView()
        self.toasts = ToastManager()
        self.panel = Panel(self.view)
        self.panel.visibility_changed.connect(self.toasts.set_suspended)
        self._icon_key = None

        self.tray = QSystemTrayIcon()
        # 首次登记的提示文字用于识别本程序的托盘设置项（见 tray_promotion），必须在 show 之前设置。
        self.tray.setToolTip(tray.APP_NAME)
        self.tray.setIcon(icons.tray_icon('unknown', False))
        self.tray.activated.connect(self._on_activated)

        self.view.notify_requested.connect(self._show_toast)
        self.view.refresh_requested.connect(self.refresh)
        self.view.quit_requested.connect(self._quit)

        # 定时刷新，反映在 WorkPal 之外发生的网络变化
        self.timer = QTimer(self, interval=STATUS_POLL_MS)
        self.timer.timeout.connect(self.refresh)

    def start(self) -> None:
        self.tray.show()
        self.refresh()
        self.timer.start()
        threading.Thread(target=tray.startup, args=(self.view,), daemon=True, name='startup').start()

    def refresh(self) -> None:
        try:
            state = tray.current_state()
        except Exception:
            logger.exception('读取托盘状态失败')
            return
        key = (tray.icon_name(state), state.keep_alive)
        if key != self._icon_key:
            self._icon_key = key
            self.tray.setIcon(icons.tray_icon(*key))
        tip = tray.tooltip(state)
        if self.tray.toolTip() != tip:
            self.tray.setToolTip(tip)
        if self.panel.isVisible():
            self.panel.update_state(state)

    def _on_activated(self, reason) -> None:
        if reason not in (QSystemTrayIcon.ActivationReason.Trigger,
                          QSystemTrayIcon.ActivationReason.Context):
            return
        if self.panel.isVisible():
            self.panel.hide()
            return
        if time.monotonic() - self.panel.last_hidden < REOPEN_GUARD_SECONDS:
            return
        self.panel.popup(self.tray.geometry(), tray.current_state())

    def _show_toast(self, title: str, message: str, level: str, key) -> None:
        self.toasts.show(title, message, level, key)

    def _quit(self) -> None:
        self.timer.stop()
        self.panel.hide()
        self.tray.hide()
        self.app.quit()


def run() -> None:
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName(tray.APP_NAME)
    app.setFont(theme.app_font())
    if not QSystemTrayIcon.isSystemTrayAvailable():
        logger.error('系统托盘不可用')
    tray_app = TrayApp(app)
    tray_app.start()
    app.exec()
