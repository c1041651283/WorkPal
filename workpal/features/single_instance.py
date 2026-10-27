"""同一 Windows 用户会话只运行一份 WorkPal，避免网卡和代理操作互相干扰。"""

import win32api
import win32con
import win32event
import win32security
import winerror


class SingleInstance:
    def __init__(self):
        self._handle = None

    def acquire(self) -> bool:
        token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
        try:
            sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
            name = 'Local\\WorkPal-Instance-' + win32security.ConvertSidToStringSid(sid)
        finally:
            win32api.CloseHandle(token)
        handle = win32event.CreateMutex(None, False, name)
        if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
            win32api.CloseHandle(handle)
            return False
        self._handle = handle
        return True

    def close(self) -> None:
        if self._handle is not None:
            win32api.CloseHandle(self._handle)
            self._handle = None
