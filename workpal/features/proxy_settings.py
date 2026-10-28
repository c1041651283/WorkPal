"""当前用户的 Windows LAN 代理，以及可恢复的接管记录。不修改 VPN 配置。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import asdict, dataclass, replace
import json
import os
from pathlib import Path


@dataclass(frozen=True)
class ProxySettings:
    flags: int
    server: str
    bypass: str
    pac_url: str

    def direct(self) -> ProxySettings:
        # 保留地址和例外，只关闭手动代理、系统 PAC 和自动检测。
        return replace(self, flags=1)

    def manual(self, server: str) -> ProxySettings:
        return replace(self, flags=3, server=server)

    def pac(self, url: str) -> ProxySettings:
        return replace(self, flags=5, pac_url=url)

    def equivalent(self, other: ProxySettings) -> bool:
        # WinINet 可能为同一个 HTTP 代理补上 http://，不应因此反复写入。
        def normalize(server: str) -> str:
            return server.strip().lower().removeprefix('http://')
        return (self.flags == other.flags and normalize(self.server) == normalize(other.server)
                and self.bypass == other.bypass and self.pac_url == other.pac_url)


class _Value(ctypes.Union):
    _fields_ = [('number', wintypes.DWORD), ('text', ctypes.c_void_p),
                ('time', wintypes.FILETIME)]


class _Option(ctypes.Structure):
    _fields_ = [('option', wintypes.DWORD), ('value', _Value)]


class _OptionList(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('connection', wintypes.LPWSTR),
                ('count', wintypes.DWORD), ('error', wintypes.DWORD),
                ('options', ctypes.POINTER(_Option))]


class WindowsProxyStore:
    """使用 WinINet 正式接口；connection=NULL 只操作当前用户 LAN 设置。"""

    def __init__(self):
        self.api = ctypes.WinDLL('wininet', use_last_error=True)
        self.api.InternetQueryOptionW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.api.InternetQueryOptionW.restype = wintypes.BOOL
        self.api.InternetSetOptionW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
        ]
        self.api.InternetSetOptionW.restype = wintypes.BOOL
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.GlobalFree.argtypes = [ctypes.c_void_p]
        self.kernel.GlobalFree.restype = ctypes.c_void_p

    @staticmethod
    def _make_options(flag_option: int):
        options = (_Option * 4)()
        for option, number in zip(options, (flag_option, 2, 3, 4)):
            option.option = number
        info = _OptionList(ctypes.sizeof(_OptionList), None, 4, 0, options)
        return options, info

    def read(self) -> ProxySettings:
        # FLAGS_UI (10) 保存用户选择，避免把自动检测结果误当原始设置。
        options, info = self._make_options(10)
        size = wintypes.DWORD(ctypes.sizeof(info))
        try:
            if not self.api.InternetQueryOptionW(None, 75, ctypes.byref(info), ctypes.byref(size)):
                raise ctypes.WinError(ctypes.get_last_error())
            strings = [ctypes.wstring_at(x.value.text) if x.value.text else ''
                       for x in options[1:]]
            return ProxySettings(int(options[0].value.number), *strings)
        finally:
            for option in options[1:]:
                if option.value.text:
                    self.kernel.GlobalFree(option.value.text)

    def write(self, settings: ProxySettings) -> None:
        options, info = self._make_options(1)
        options[0].value.number = settings.flags
        buffers = [ctypes.create_unicode_buffer(value) for value in
                   (settings.server, settings.bypass, settings.pac_url)]
        for option, buffer in zip(options[1:], buffers):
            option.value.text = ctypes.cast(buffer, ctypes.c_void_p).value
        if not self.api.InternetSetOptionW(None, 75, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        for flag in (39, 37):  # SETTINGS_CHANGED, REFRESH
            if not self.api.InternetSetOptionW(None, flag, None, 0):
                raise ctypes.WinError(ctypes.get_last_error())
        if not self.read().equivalent(settings):
            raise RuntimeError('代理设置未生效，可能受组织策略限制；已保留恢复备份')


class ProxyChangedExternally(RuntimeError):
    pass


class ProxyOperationCancelled(RuntimeError):
    """守护已收到暂停请求，尚未执行本次系统写入。"""


class ProxySession:
    """先持久化原值和预期值，再写系统；崩溃后仍能显式恢复。"""

    def __init__(self, store, path: Path, *, cancelled=None):
        self.store = store
        self.path = path
        self.cancelled = cancelled
        self.original: ProxySettings | None = None
        self.expected: ProxySettings | None = None
        self.previous: ProxySettings | None = None

    def begin(self, *, resume: bool = False) -> None:
        if self.path.exists():
            if not resume:
                raise RuntimeError('存在上次代理备份，未修改设置')
            # 用户再次手动开启时继续使用原备份，不把已修复的设置当成原值。
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if data.get('version') != 1:
                raise RuntimeError('无法识别代理备份版本，未修改设置')
            self.original = ProxySettings(**data['original'])
            self.expected = self.previous = self.store.read()
        else:
            self.original = self.expected = self.previous = self.store.read()
        self._save()

    def _save(self) -> None:
        data = {'version': 1, 'original': asdict(self.original),
                'expected': asdict(self.expected), 'previous': asdict(self.previous)}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)

    def check_owned(self) -> None:
        if not self.store.read().equivalent(self.expected):
            raise ProxyChangedExternally('代理被其他程序或手动修改，代理守护已停止接管，未覆盖新设置')

    def apply(self, settings: ProxySettings) -> None:
        self.check_owned()
        if settings.equivalent(self.expected):
            return
        self.previous, self.expected = self.expected, settings
        self._save()
        self.store.write(settings)

    def enforce(self, *, server: str | None = None, pac_url: str | None = None) -> bool:
        """应用选定代理模式，保留例外及非目标地址；写入前先保存恢复备份。"""
        self._check_cancelled()
        current = self.store.read()
        if server is not None and pac_url is not None:
            raise ValueError('固定代理和 PAC 不能同时接管')
        wanted = (current.pac(pac_url) if pac_url is not None else
                  current.manual(server) if server is not None else current.direct())
        if current.equivalent(wanted):
            return False
        self.previous, self.expected = current, wanted
        self._save()
        # fsync 期间可能收到暂停；备份已落盘不代表可以继续修改系统。
        self._check_cancelled()
        self.store.write(wanted)
        return True

    def _check_cancelled(self) -> None:
        if self.cancelled is not None and self.cancelled():
            raise ProxyOperationCancelled()

    def restore(self, *, explicit: bool = False) -> None:
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if data.get('version') != 1:
            raise RuntimeError('无法识别代理备份版本，未修改设置')
        original = ProxySettings(**data['original'])
        expected = ProxySettings(**data['expected'])
        previous = ProxySettings(**data['previous'])
        current = self.store.read()
        if not explicit and not any(current.equivalent(x) for x in (original, expected, previous)):
            raise ProxyChangedExternally('代理已被其他程序修改，未自动恢复；备份仍保留')
        if not current.equivalent(original):
            self.store.write(original)
        self.path.unlink()
