"""Native WiFi API 解析；用内存中的结构体替代 wlanapi.dll，不访问真实网卡。"""

import ctypes
from ctypes import wintypes
from unittest.mock import patch

import pytest

from workpal.features import wlan

PROFILE_XML = ('<?xml version="1.0"?><WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">'
               '<name>{name}</name><SSIDConfig><SSID><name>{ssid}</name></SSID></SSIDConfig></WLANProfile>')


def _list_of(item_type, head_type, items):
    class Head(ctypes.Structure):
        _fields_ = [('count', wintypes.DWORD), ('index', wintypes.DWORD),
                    ('items', item_type * max(1, len(items)))]
    head = Head(len(items), 0)
    for i, item in enumerate(items):
        head.items[i] = item
    return head, head_type.from_buffer(head)


class FakeApi:
    def __init__(self, interfaces=(), connection=None, profiles=None, open_error=0):
        self.interfaces = [wlan._InterfaceInfo(wlan._Guid(i + 1), name, state)
                           for i, (name, state) in enumerate(interfaces)]
        self.connection = connection
        self.profiles = profiles or {}
        self.open_error = open_error
        self.closed = self.freed = 0
        self.profile_flags = []
        self._keep = []

    def WlanOpenHandle(self, version, reserved, negotiated, handle):
        handle._obj.value = 99
        return self.open_error

    def WlanCloseHandle(self, handle, reserved):
        self.closed += 1

    def WlanFreeMemory(self, pointer):
        self.freed += 1

    def WlanEnumInterfaces(self, handle, reserved, out):
        keep, head = _list_of(wlan._InterfaceInfo, wlan._InterfaceList, self.interfaces)
        self._keep.append(keep)
        out._obj.contents = head
        return 0

    def WlanQueryInterface(self, handle, guid, opcode, reserved, size, out, kind):
        assert opcode == 7
        if self.connection is None:
            return 5023
        profile, ssid = self.connection
        attributes = wlan._ConnectionAttributes(1, 0, profile)
        raw = ssid.encode('utf-8')
        attributes.ssid.length = len(raw)
        attributes.ssid.value[:len(raw)] = list(raw)
        self._keep.append(attributes)
        out._obj.contents = attributes
        return 0

    def WlanGetProfileList(self, handle, guid, reserved, out):
        items = [wlan._ProfileInfo(name, 0) for name in self.profiles]
        keep, head = _list_of(wlan._ProfileInfo, wlan._ProfileList, items)
        self._keep.append(keep)
        out._obj.contents = head
        return 0

    def WlanGetProfile(self, handle, guid, name, reserved, xml, flags, access):
        self.profile_flags.append(flags._obj.value)
        xml._obj.value = PROFILE_XML.format(name=name, ssid=self.profiles[name])
        return 0


@pytest.fixture
def api(monkeypatch):
    def install(**kwargs):
        fake = FakeApi(**kwargs)
        monkeypatch.setattr(wlan.ctypes, 'WinDLL', lambda name: fake)
        names = {i + 1: name for i, (name, _) in enumerate(kwargs.get('interfaces', ()))}
        monkeypatch.setattr(wlan, '_interface_alias', lambda guid: names[guid.data1])
        return fake
    return install


def test_connected_interface_reports_profile_and_exact_ssid(api):
    fake = api(interfaces=[('Other', 1), ('WLAN', 1)], connection=('家里 5G', 'Café-5G'))
    assert wlan.interface_status('WLAN') == {'state': 'connected', 'profile': '家里 5G', 'ssid': 'Café-5G'}
    assert fake.closed == 1 and fake.freed == 2


@pytest.mark.parametrize('state,expected', [(4, 'disconnected'), (0, 'disconnected'),
                                            (5, 'unknown'), (7, 'unknown')])
def test_interface_states(api, state, expected):
    api(interfaces=[('WLAN', state)])
    assert wlan.interface_status('WLAN') == {'state': expected}


def test_missing_interface_or_lost_connection_is_unknown(api):
    api(interfaces=[('Other', 1)])
    assert wlan.interface_status('WLAN') == {'state': 'unknown'}
    api(interfaces=[('WLAN', 1)], connection=None)
    assert wlan.interface_status('WLAN') == {'state': 'unknown'}


def test_find_profile_prefers_same_name_then_matches_ssid_without_cleartext_key(api):
    fake = api(interfaces=[('WLAN', 4)], profiles={'Office': 'corp', 'Home (2)': 'Home', 'Home': 'Home'})
    assert wlan.find_profile('WLAN', 'Home') == 'Home'
    assert fake.profile_flags == []
    assert wlan.find_profile('WLAN', 'corp') == 'Office'
    assert wlan.find_profile('WLAN', 'absent') is None
    assert set(fake.profile_flags) == {0}  # 从不请求 WLAN_PROFILE_GET_PLAINTEXT_KEY


def test_find_profile_without_interface_raises(api):
    api(interfaces=[])
    with pytest.raises(LookupError):
        wlan.find_profile('WLAN', 'Home')


def test_open_failure_raises_os_error(api):
    api(open_error=1062)
    with pytest.raises(OSError):
        wlan.interface_status('WLAN')


def test_struct_sizes_match_windows_sdk():
    assert ctypes.sizeof(wlan._InterfaceInfo) == 532
    assert ctypes.sizeof(wlan._ProfileInfo) == 516
    assert wlan._ConnectionAttributes.ssid.offset == 520
