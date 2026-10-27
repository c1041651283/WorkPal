"""隐藏窗口接收 Windows 唤醒/解锁消息；不阻止锁屏、休眠或操作 VPN。"""

import logging
import os
import threading

import win32api
import win32gui
import win32ts

logger = logging.getLogger(__name__)
WM_POWERBROADCAST = 0x218
WM_WTSSESSION_CHANGE = 0x2B1
WM_CLOSE, WM_DESTROY = 0x10, 0x02


class SessionEvents:
    def __init__(self):
        self._thread = None
        self._window = None
        self._registered = False
        self._stop = threading.Event()
        self._callback = None

    def start(self, callback) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._callback = callback
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name='session-events')
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._window:
            try:
                win32gui.PostMessage(self._window, WM_CLOSE, 0, 0)
            except Exception:
                logger.debug('唤醒监听窗口已经关闭', exc_info=True)
        if self._thread:
            self._thread.join(timeout=2)

    def _unregister(self, hwnd) -> None:
        if self._registered:
            win32ts.WTSUnRegisterSessionNotification(hwnd)
            self._registered = False

    def _handle(self, hwnd, message, event, detail):
        # PBT_APMRESUMEAUTOMATIC / RESUMESUSPEND；WTS_SESSION_UNLOCK。
        if (message == WM_POWERBROADCAST and event in (7, 18)
                or message == WM_WTSSESSION_CHANGE and event == 8):
            try:
                self._callback('系统唤醒' if message == WM_POWERBROADCAST else '解锁')
            except Exception:
                logger.exception('唤醒检查回调失败')
            return 1
        if message == WM_CLOSE:
            self._unregister(hwnd)
            win32gui.DestroyWindow(hwnd)
            return 0
        if message == WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, message, event, detail)

    def _run(self):
        instance = win32api.GetModuleHandle(None)
        name = f'WorkPal-Session-{os.getpid()}-{id(self)}'
        registered_class = False
        try:
            wc = win32gui.WNDCLASS()
            wc.hInstance = instance
            wc.lpszClassName = name
            wc.lpfnWndProc = self._handle
            win32gui.RegisterClass(wc)
            registered_class = True
            # 顶层但不可见；message-only 窗口不会收到电源广播。
            self._window = win32gui.CreateWindowEx(0, name, '', 0, 0, 0, 0, 0,
                                                  0, 0, instance, None)
            try:
                win32ts.WTSRegisterSessionNotification(self._window, 0)
                self._registered = True
            except Exception:
                logger.exception('注册解锁监听失败；保留电源监听与定时检查')
            if not self._stop.is_set():
                win32gui.PumpMessages()
        except Exception:
            logger.exception('唤醒事件监听失败；代理守护仍按定时间隔检查')
        finally:
            if self._window:
                try:
                    self._unregister(self._window)
                    if win32gui.IsWindow(self._window):
                        win32gui.DestroyWindow(self._window)
                except Exception:
                    logger.exception('清理唤醒监听失败')
                self._window = None
            if registered_class:
                win32gui.UnregisterClass(name, instance)


session_events = SessionEvents()
