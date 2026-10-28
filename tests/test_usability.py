"""托盘交互与提示：切换方向、悬停状态、定时刷新、报错提示、托盘图标直接显示；系统调用全部使用替身。"""

from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest

from workpal import tray
from workpal.features import network as net, tray_promotion, vpn_proxy
from tests.fake_view import FakeView


@pytest.fixture(autouse=True)
def reset_tray_state(monkeypatch):
    monkeypatch.setattr(tray, '_switching', False)
    monkeypatch.setattr(tray, '_switch_target', None)


@pytest.mark.parametrize('mode,target', [('wifi', 'ethernet'), ('ethernet', 'wifi'), ('unknown', None)])
def test_switch_goes_to_the_other_network(monkeypatch, mode, target):
    monkeypatch.setattr(tray, '_current_network_mode', lambda: mode)
    with patch.object(tray, '_start_switch') as start:
        tray.switch_network(FakeView())
    assert start.call_args.args[1] == target


def test_explicit_target_is_used_as_is(monkeypatch):
    monkeypatch.setattr(tray, '_current_network_mode', lambda: 'unknown')
    with patch.object(tray, '_start_switch') as start:
        tray.switch_network(FakeView(), 'ethernet')
    assert start.call_args.args[1] == 'ethernet'


def test_switch_reports_unknown_state_without_switching(monkeypatch):
    monkeypatch.setattr(tray.network, 'get_current_mode', lambda: 'unknown')
    view = FakeView()
    with patch.object(tray.network, 'switch_to_wifi') as wifi,          patch.object(tray.network, 'switch_to_ethernet') as ethernet:
        tray._switch_lock.acquire()
        tray._do_switch_and_release(view)
    wifi.assert_not_called()
    ethernet.assert_not_called()
    assert view.last.title == '无法识别当前网络' and view.last.level == 'error'
    assert not tray._switch_lock.locked()


def test_tooltip_shows_network_keep_alive_and_proxy(monkeypatch):
    monkeypatch.setattr(tray, '_current_network_mode', lambda: 'ethernet')
    monkeypatch.setattr(tray.keep_alive, 'is_active', lambda: True)
    with patch.object(vpn_proxy, 'assistant', status='守护中 · 公司网络已就绪', active=True,
                      last_checked='12:00:00'):
        state = tray.current_state()
        text = tray.tooltip(state)
    assert state.guard_active and state.keep_alive and state.mode == 'ethernet'
    assert '网络：有线' in text and '保持在线：开' in text and '代理：守护中' in text
    assert len(tray.tooltip(replace(state, guard_status='很长的状态' * 50))) <= 127


def test_open_log_folder(monkeypatch):
    opened = []
    monkeypatch.setattr(tray.os, 'startfile', opened.append, raising=False)
    tray.open_logs(FakeView())
    assert opened == [tray.get_user_data_path()]


# ---------------------------------------------------------------- 报错提示


@pytest.fixture
def adapters(monkeypatch):
    monkeypatch.setattr(vpn_proxy, 'assistant', MagicMock(active=False))
    monkeypatch.setitem(net.CONFIG, 'wifi_adapter_name', 'WLAN')
    monkeypatch.setitem(net.CONFIG, 'ethernet_adapter_name', '以太网')
    monkeypatch.setitem(net.CONFIG, 'wifi_ssid', 'office')
    status = {'WLAN': 'enabled_connected', '以太网': 'not_found'}
    monkeypatch.setattr(net, 'get_adapter_status', lambda name: status[name])
    monkeypatch.setattr(net, 'list_adapter_names', lambda: ['WLAN', '以太网 2'])
    return status


def test_missing_adapter_names_the_config_key_and_existing_adapters(adapters):
    success, reason = net.switch_to_ethernet()
    assert not success
    assert '找不到网卡「以太网」' in reason and 'ETHERNET_ADAPTER_NAME' in reason
    assert '以太网 2' in reason and '编辑配置文件' in reason and '未开始切换' in reason


@pytest.mark.parametrize('ssid', ['', net.SSID_PLACEHOLDER])
def test_unfilled_ssid_points_to_config_editor(adapters, monkeypatch, ssid):
    adapters['以太网'] = 'enabled_connected'
    adapters['WLAN'] = 'disabled'
    monkeypatch.setitem(net.CONFIG, 'wifi_ssid', ssid)
    success, reason = net.switch_to_wifi()
    assert not success and 'WIFI_SSID' in reason and '编辑配置文件' in reason


def test_guard_message_uses_pause_wording(adapters, monkeypatch):
    monkeypatch.setattr(vpn_proxy, 'assistant', MagicMock(active=True))
    success, reason = net.switch_to_ethernet()
    assert not success and '暂停守护' in reason and '助手' not in reason


# ---------------------------------------------------------------- 守护读取最新配置


def test_guard_uses_new_proxy_address_from_config(monkeypatch):
    from workpal.config import CONFIG
    monkeypatch.setitem(CONFIG, 'vpn_proxy_server', 'http://new.example.com:3128')
    assert vpn_proxy._configured_server('old.example.com:8080') == 'new.example.com:3128'


def test_guard_keeps_current_address_when_new_one_is_invalid(monkeypatch):
    from workpal.config import CONFIG
    monkeypatch.setitem(CONFIG, 'vpn_proxy_server', 'not a proxy')
    assert vpn_proxy._configured_server('old.example.com:8080') == 'old.example.com:8080'


# ---------------------------------------------------------------- 托盘图标直接显示


EXE = r'D:\WorkPal\dist\folder-1\WorkPal\WorkPal.exe'


@pytest.fixture
def registry(monkeypatch):
    entries = {}
    monkeypatch.setattr(tray_promotion, '_entries', lambda: (
        (name, *values) for name, values in list(entries.items())))

    def set_promoted(name):
        path, tooltip, _ = entries[name]
        entries[name] = (path, tooltip, 1)

    monkeypatch.setattr(tray_promotion, '_set_promoted', set_promoted)
    return entries


def test_new_icon_entry_is_promoted(registry):
    registry['1'] = (EXE, tray.APP_NAME, None)
    registry['2'] = (r'D:\Other\app.exe', tray.APP_NAME, None)
    assert tray_promotion.promote(EXE, tray.APP_NAME)
    assert registry['1'][2] == 1 and registry['2'][2] is None


def test_user_choice_to_hide_is_respected(registry):
    registry['1'] = (EXE, tray.APP_NAME, 0)
    assert tray_promotion.promote(EXE, tray.APP_NAME)
    assert registry['1'][2] == 0


def test_shared_executable_with_other_tooltip_is_left_alone(registry):
    python = r'C:\Python311\python.exe'
    registry['1'] = (python, '别的托盘工具', None)
    assert not tray_promotion.promote(python, tray.APP_NAME)
    assert registry['1'][2] is None


def test_known_folder_prefix_is_expanded(registry, monkeypatch):
    monkeypatch.setenv('ProgramW6432', r'C:\Program Files')
    registry['1'] = (r'{6D809377-6AF0-444B-8957-A3773F02200E}\WorkPal\WorkPal.exe', tray.APP_NAME, None)
    assert tray_promotion.promote(r'C:\Program Files\WorkPal\WorkPal.exe', tray.APP_NAME)
    assert registry['1'][2] == 1


def test_windows_10_without_settings_key_is_skipped(monkeypatch):
    def missing():
        raise FileNotFoundError
        yield  # pragma: no cover

    monkeypatch.setattr(tray_promotion, '_entries', missing)
    assert tray_promotion.promote(EXE, tray.APP_NAME)


def test_waits_until_explorer_registers_icon(registry):
    calls = []

    def wait(delay):
        calls.append(delay)
        registry['1'] = (EXE, tray.APP_NAME, None)
        return False

    stop = MagicMock(wait=wait)
    tray_promotion.promote_when_registered(EXE, tray.APP_NAME, stop=stop, delay=0.5)
    assert calls == [0.5] and registry['1'][2] == 1
