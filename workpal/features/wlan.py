"""通过 Native WiFi API 只读查询 WLAN 状态和 Windows 已保存的配置。

不解析 netsh 输出，因此不受系统语言影响；不读取明文密钥，也不修改任何配置。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from xml.etree import ElementTree

_ERROR_INVALID_STATE = 5023  # 接口未连接时查询当前连接
_PROFILE_NS = '{http://www.microsoft.com/networking/WLAN/profile/v1}'

# WLAN_INTERFACE_STATE
_STATE_CONNECTED = 1
_STATES_DISCONNECTED = (0, 4)  # not_ready, disconnected


class _Guid(ctypes.Structure):
    _fields_ = [('data1', wintypes.DWORD), ('data2', wintypes.WORD),
                ('data3', wintypes.WORD), ('data4', ctypes.c_ubyte * 8)]


class _InterfaceInfo(ctypes.Structure):
    _fields_ = [('guid', _Guid), ('description', wintypes.WCHAR * 256),
                ('state', wintypes.DWORD)]


class _InterfaceList(ctypes.Structure):
    _fields_ = [('count', wintypes.DWORD), ('index', wintypes.DWORD),
                ('items', _InterfaceInfo * 1)]


class _Ssid(ctypes.Structure):
    _fields_ = [('length', wintypes.ULONG), ('value', ctypes.c_ubyte * 32)]


class _ConnectionAttributes(ctypes.Structure):
    # WLAN_CONNECTION_ATTRIBUTES 的固定前缀，只读取到关联的 SSID。
    _fields_ = [('state', wintypes.DWORD), ('mode', wintypes.DWORD),
                ('profile', wintypes.WCHAR * 256), ('ssid', _Ssid)]


class _ProfileInfo(ctypes.Structure):
    _fields_ = [('name', wintypes.WCHAR * 256), ('flags', wintypes.DWORD)]


class _ProfileList(ctypes.Structure):
    _fields_ = [('count', wintypes.DWORD), ('index', wintypes.DWORD),
                ('items', _ProfileInfo * 1)]


def _items(head, item_type, count: int) -> list:
    """WLAN 列表结构末尾是变长数组，按真实数量读取。"""
    pointer = ctypes.cast(ctypes.addressof(head.items), ctypes.POINTER(item_type))
    return [pointer[i] for i in range(count)]


def _check(code: int) -> None:
    if code:
        raise ctypes.WinError(code)


class _Client:
    def __init__(self):
        self.api = ctypes.WinDLL('wlanapi')
        self.handle = wintypes.HANDLE()
        version = wintypes.DWORD()
        _check(self.api.WlanOpenHandle(2, None, ctypes.byref(version), ctypes.byref(self.handle)))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.api.WlanCloseHandle(self.handle, None)

    def _free(self, pointer) -> None:
        self.api.WlanFreeMemory(pointer)

    def interface(self, adapter_name: str) -> _InterfaceInfo | None:
        pointer = ctypes.POINTER(_InterfaceList)()
        _check(self.api.WlanEnumInterfaces(self.handle, None, ctypes.byref(pointer)))
        try:
            for item in _items(pointer.contents, _InterfaceInfo, pointer.contents.count):
                if _interface_alias(item.guid) == adapter_name:
                    # 复制一份，释放列表内存后仍可使用。
                    return _InterfaceInfo.from_buffer_copy(item)
            return None
        finally:
            self._free(pointer)

    def connection(self, guid: _Guid) -> tuple[str, str] | None:
        size = wintypes.DWORD()
        pointer = ctypes.POINTER(_ConnectionAttributes)()
        code = self.api.WlanQueryInterface(self.handle, ctypes.byref(guid), 7, None,
                                           ctypes.byref(size), ctypes.byref(pointer), None)
        if code == _ERROR_INVALID_STATE:
            return None
        _check(code)
        try:
            attributes = pointer.contents
            ssid = bytes(attributes.ssid.value[:attributes.ssid.length])
            return attributes.profile, ssid.decode('utf-8', errors='replace')
        finally:
            self._free(pointer)

    def profile_names(self, guid: _Guid) -> list[str]:
        pointer = ctypes.POINTER(_ProfileList)()
        _check(self.api.WlanGetProfileList(self.handle, ctypes.byref(guid), None,
                                           ctypes.byref(pointer)))
        try:
            return [item.name for item in _items(pointer.contents, _ProfileInfo,
                                                 pointer.contents.count)]
        finally:
            self._free(pointer)

    def profile_ssids(self, guid: _Guid, name: str) -> list[str]:
        xml = wintypes.LPWSTR()
        flags = wintypes.DWORD(0)  # 不请求明文密钥
        _check(self.api.WlanGetProfile(self.handle, ctypes.byref(guid), name, None,
                                       ctypes.byref(xml), ctypes.byref(flags), None))
        try:
            root = ElementTree.fromstring(xml.value)
        finally:
            self._free(xml)
        return [node.text or '' for node in
                root.iter(f'{_PROFILE_NS}SSID') for node in node.iter(f'{_PROFILE_NS}name')]


def _interface_alias(guid: _Guid) -> str:
    """把 WLAN 接口 GUID 转成“网络连接”中显示的名称（如 WLAN）。"""
    iphlpapi = ctypes.WinDLL('iphlpapi')
    luid = ctypes.c_uint64()
    _check(iphlpapi.ConvertInterfaceGuidToLuid(ctypes.byref(guid), ctypes.byref(luid)))
    alias = ctypes.create_unicode_buffer(257)
    _check(iphlpapi.ConvertInterfaceLuidToAlias(ctypes.byref(luid), alias, len(alias)))
    return alias.value


def interface_status(adapter_name: str) -> dict:
    """返回 {'state': connected/disconnected/unknown, 'profile', 'ssid'}。

    网卡被禁用时不会出现在 WLAN 接口列表中，返回 unknown，与“已断开”区分。
    """
    with _Client() as client:
        info = client.interface(adapter_name)
        if info is None:
            return {'state': 'unknown'}
        if info.state in _STATES_DISCONNECTED:
            return {'state': 'disconnected'}
        if info.state != _STATE_CONNECTED:
            return {'state': 'unknown'}  # 关联、认证等过渡状态
        current = client.connection(info.guid)
        if current is None:
            return {'state': 'unknown'}
        profile, ssid = current
        return {'state': 'connected', 'profile': profile, 'ssid': ssid}


def find_profile(adapter_name: str, ssid: str) -> str | None:
    """在 Windows 已保存的配置中查找连接该 SSID 的配置名；同名配置优先。

    接口不存在（例如网卡已禁用）时抛出 LookupError，调用方应在启用网卡后再查。
    """
    with _Client() as client:
        info = client.interface(adapter_name)
        if info is None:
            raise LookupError(f'找不到 WLAN 接口 {adapter_name}')
        names = client.profile_names(info.guid)
        if ssid in names:
            return ssid
        for name in names:
            if ssid in client.profile_ssids(info.guid, name):
                return name
        return None
