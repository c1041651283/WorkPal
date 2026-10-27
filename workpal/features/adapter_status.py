"""通过 IP Helper 只读枚举网卡，避免 WMI 在锁屏/恢复期间超时。"""

import ctypes
from ctypes import wintypes
import socket

import psutil


class _Adapter(ctypes.Structure):
    pass


# IP_ADAPTER_ADDRESSES_LH 的固定前缀，只读取到 OperStatus。
_Adapter._fields_ = [
    ('alignment', ctypes.c_ulonglong),
    ('next', ctypes.POINTER(_Adapter)),
    ('adapter_name', ctypes.c_void_p),
    ('unicast', ctypes.c_void_p), ('anycast', ctypes.c_void_p),
    ('multicast', ctypes.c_void_p), ('dns_server', ctypes.c_void_p),
    ('dns_suffix', wintypes.LPWSTR), ('description', wintypes.LPWSTR),
    ('friendly_name', wintypes.LPWSTR),
    ('physical_address', ctypes.c_ubyte * 8),
    ('physical_address_length', wintypes.ULONG),
    ('flags', wintypes.ULONG), ('mtu', wintypes.ULONG),
    ('interface_type', wintypes.ULONG), ('oper_status', wintypes.ULONG),
]


def read_adapters() -> list[dict]:
    api = ctypes.WinDLL('iphlpapi').GetAdaptersAddresses
    api.argtypes = [wintypes.ULONG, wintypes.ULONG, ctypes.c_void_p,
                    ctypes.c_void_p, ctypes.POINTER(wintypes.ULONG)]
    api.restype = wintypes.ULONG
    size = wintypes.ULONG(15000)
    for _ in range(3):
        buffer = ctypes.create_string_buffer(size.value)
        # INCLUDE_ALL_INTERFACES：也枚举断开、尚未分配 IP 的 VPN 网卡。
        result = api(socket.AF_UNSPEC, 0x100, None, buffer, ctypes.byref(size))
        if result == 111:  # ERROR_BUFFER_OVERFLOW：网卡可能正在变化。
            continue
        if result == 232:  # ERROR_NO_DATA
            return []
        if result:
            raise ctypes.WinError(result)
        addresses = psutil.net_if_addrs()
        adapters = []
        pointer = ctypes.cast(buffer, ctypes.POINTER(_Adapter))
        while pointer:
            item = pointer.contents
            # 保持现有状态机的输入：2=连接；7=断开；None=无法确认。
            status = 2 if item.oper_status == 1 else 7 if item.oper_status in (2, 6, 7) else None
            adapters.append({
                'name': item.description or '', 'friendly_name': item.friendly_name or '',
                'status': status, 'interface_type': item.interface_type,
                'addresses': [x.address.split('%')[0] for x in addresses.get(item.friendly_name, [])
                              if x.family in (socket.AF_INET, socket.AF_INET6)],
            })
            pointer = item.next
        return adapters
    raise OSError('网卡列表持续变化，请稍后重试')
