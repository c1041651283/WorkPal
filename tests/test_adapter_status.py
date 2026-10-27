import ctypes
from ctypes import wintypes
import socket
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from workpal.features import adapter_status as native


def test_native_reader_keeps_disconnected_vpn_and_does_not_depend_on_wmi():
    first = native._Adapter()
    second = native._Adapter()
    first.description, first.friendly_name = 'Intel Ethernet', 'LAN'
    first.oper_status, first.interface_type = 1, 6
    first.next = ctypes.pointer(second)
    second.description, second.friendly_name = 'Fortinet SSL VPN Virtual Ethernet Adapter', 'VPN'
    second.oper_status, second.interface_type = 2, 53
    api = MagicMock()
    def fill(family, flags, reserved, buffer, size):
        assert family == socket.AF_UNSPEC and flags & 0x100
        assert reserved is None
        ctypes.memmove(buffer, ctypes.byref(first), ctypes.sizeof(first))
        return 0
    api.side_effect = fill
    addresses = {'LAN': [SimpleNamespace(family=socket.AF_INET, address='10.1.2.3'),
                         SimpleNamespace(family=socket.AF_INET6, address='fe80::1%4'),
                         SimpleNamespace(family=-1, address='00:00:00:00:00:00')]}
    with patch.object(native.ctypes, 'WinDLL') as dll, \
         patch.object(native.psutil, 'net_if_addrs', return_value=addresses):
        dll.return_value.GetAdaptersAddresses = api
        result = native.read_adapters()
    assert result[0]['addresses'] == ['10.1.2.3', 'fe80::1']
    assert result[0]['status'] == 2
    assert result[1]['status'] == 7
    assert result[1]['addresses'] == []


def test_native_buffer_growth_has_bounded_retries():
    api = MagicMock(return_value=111)
    with patch.object(native.ctypes, 'WinDLL') as dll:
        dll.return_value.GetAdaptersAddresses = api
        with pytest.raises(OSError, match='持续变化'):
            native.read_adapters()
    assert api.call_count == 3


def test_no_adapters_is_distinct_from_a_read_error():
    with patch.object(native.ctypes, 'WinDLL') as dll:
        dll.return_value.GetAdaptersAddresses.return_value = 232
        assert native.read_adapters() == []
        dll.return_value.GetAdaptersAddresses.return_value = 5
        with pytest.raises(OSError):
            native.read_adapters()
