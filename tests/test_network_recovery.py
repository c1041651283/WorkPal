"""验证网络状态与恢复结果，不执行网卡、WLAN 或进程操作。"""

from pathlib import Path
import subprocess
from unittest.mock import MagicMock

import psutil
import pytest

from workpal.features import network as net, vpn_proxy


@pytest.fixture
def machine(monkeypatch):
    monkeypatch.setattr(vpn_proxy, 'assistant', MagicMock(active=False))
    monkeypatch.setitem(net.CONFIG, 'wifi_adapter_name', 'WiFi')
    monkeypatch.setitem(net.CONFIG, 'ethernet_adapter_name', 'LAN')
    monkeypatch.setitem(net.CONFIG, 'wifi_ssid', 'target')
    monkeypatch.setitem(net.CONFIG, 'wifi_password', 'test-password')
    monkeypatch.setitem(net.CONFIG, 'ethernet_program_path', '')
    state = {'adapters': {'WiFi': 'enabled_disconnected', 'LAN': 'enabled_connected'},
             'wifi': {'state': 'disconnected'}, 'connect_ok': True, 'link_up': True,
             'commands': [], 'saved_profile': b'<original/>', 'fail_enable': ''}

    def enable(name):
        if state['fail_enable'] == name:
            return False
        state['adapters'][name] = 'enabled_connected' if name == 'LAN' and state['link_up'] else 'enabled_disconnected'
        return True

    def disable(name):
        state['adapters'][name] = 'disabled'
        return True

    def disconnect(name):
        state['wifi'] = {'state': 'disconnected'}
        return True

    def connect(ssid, password, *, profile_name):
        state['commands'].append(('new', ssid, profile_name))
        state['saved_profile'] = b'<new/>'
        if state['connect_ok']:
            state['wifi'] = {'state': 'connected', 'profile': profile_name, 'ssid': ssid}
        return state['connect_ok']

    def restore_profile(name, data, adapter):
        state['saved_profile'] = data
        return True

    def netsh(args):
        state['commands'].append(args)
        if args[:2] == ['wlan', 'connect']:
            values = dict(arg.split('=', 1) for arg in args[2:])
            state['wifi'] = {'state': 'connected', 'profile': values['name'], 'ssid': values['ssid']}
        return True, ''

    monkeypatch.setattr(net, 'get_adapter_status', lambda name: state['adapters'][name])
    monkeypatch.setattr(net, 'get_wifi_connection_info', lambda name: dict(state['wifi']))
    monkeypatch.setattr(net, 'enable_adapter', enable)
    monkeypatch.setattr(net, 'disable_adapter', disable)
    monkeypatch.setattr(net, 'disconnect_wifi', disconnect)
    monkeypatch.setattr(net, 'connect_wifi', connect)
    monkeypatch.setattr(net, '_backup_wifi_profile', lambda *args: state['saved_profile'])
    monkeypatch.setattr(net, '_restore_wifi_profile', restore_profile)
    monkeypatch.setattr(net, '_run_netsh', netsh)
    monkeypatch.setattr(net, '_wait_for', lambda check, timeout, interval=1: check())
    return state


def test_wifi_failure_restores_ethernet_and_previous_profile(machine):
    machine['connect_ok'] = False
    success, reason = net.switch_to_wifi()
    assert not success and '已恢复原网络状态' in reason
    assert machine['adapters']['LAN'] == 'enabled_connected'
    assert machine['wifi']['state'] == 'disconnected'
    assert machine['saved_profile'] == b'<original/>'


def test_missing_cable_restores_actual_wifi_profile_not_configured_ssid(machine):
    machine['adapters']['LAN'] = 'disabled'
    original = {'state': 'connected', 'profile': 'personal-profile', 'ssid': 'actual-network'}
    machine['wifi'] = original.copy()
    machine['link_up'] = False
    success, reason = net.switch_to_ethernet()
    assert not success and '网线' in reason and '已恢复' in reason
    assert machine['adapters']['LAN'] == 'disabled'
    assert machine['wifi'] == original


def test_unknown_original_state_makes_no_changes(machine):
    machine['wifi'] = {'state': 'unknown'}
    before = machine['adapters'].copy()
    assert net.switch_to_wifi()[0] is False
    assert machine['adapters'] == before
    assert machine['commands'] == []


def test_failed_disconnect_cannot_be_reported_as_success(machine, monkeypatch):
    monkeypatch.setattr(net, 'disconnect_wifi', lambda _: False)
    success, reason = net.switch_to_ethernet()
    assert not success and '断开命令' in reason


def test_connection_timeout_rolls_back_and_does_not_claim_success(machine, monkeypatch):
    monkeypatch.setattr(net, 'wait_for_wifi_connected', lambda *args, **kwargs: False)
    success, reason = net.switch_to_wifi()
    assert not success and '超时' in reason
    assert machine['adapters']['LAN'] == 'enabled_connected'


def test_rollback_failure_is_visible(machine):
    machine['connect_ok'] = False
    machine['fail_enable'] = 'LAN'
    success, reason = net.switch_to_wifi()
    assert not success and '回滚未完成' in reason and 'LAN' in reason
    assert '已恢复原网络状态' not in reason


def test_success_requires_target_connection(machine):
    assert net.switch_to_wifi() == (True, '')
    assert machine['adapters']['LAN'] == 'disabled'
    assert machine['wifi']['ssid'] == 'target'


def test_backup_failure_prevents_any_network_change(machine, monkeypatch):
    monkeypatch.setattr(net, '_backup_wifi_profile', MagicMock(side_effect=OSError('backup failed')))
    before = machine['adapters'].copy()
    assert net.switch_to_wifi() == (False, 'backup failed')
    assert machine['adapters'] == before


def test_unknown_is_not_disconnected(monkeypatch):
    monkeypatch.setattr(net, 'get_wifi_connection_status', lambda _: 'unknown')
    monkeypatch.setattr(net, '_wait_for', lambda check, timeout: check())
    assert not net.wait_for_wifi_disconnected('WiFi')


@pytest.mark.parametrize('state,expected', [('not connected', 'disconnected'), ('connected', 'connected'), ('connecting', 'unknown')])
def test_wifi_info_matches_exact_interface_and_preserves_profile(monkeypatch, state, expected):
    output = f'Name : WiFi\nState : {state}\nSSID : actual\nProfile : saved\n\nName : Other\nState : connected\n'
    monkeypatch.setattr(net, '_run_netsh', lambda args: (True, output))
    assert net.get_wifi_connection_info('WiFi') == {'state': expected, 'ssid': 'actual', 'profile': 'saved'}
    assert net.get_wifi_connection_status('Missing') == 'unknown'


def test_unconnected_ethernet_is_not_current_mode(monkeypatch):
    monkeypatch.setattr(net, 'get_wifi_connection_status', lambda _: 'disconnected')
    monkeypatch.setattr(net, 'get_adapter_status', lambda _: 'enabled_disconnected')
    assert net.get_current_mode() == 'unknown'


def test_profile_backup_never_exports_cleartext_password(monkeypatch):
    data = b'<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1"><name>WorkPal-safe</name></WLANProfile>'
    def export(args):
        assert 'key=clear' not in args
        folder = Path(next(arg.split('=', 1)[1] for arg in args if arg.startswith('folder=')))
        (folder / 'saved.xml').write_bytes(data)
        return True, ''
    monkeypatch.setattr(net, '_run_netsh', export)
    assert net._backup_wifi_profile('WorkPal-safe', 'WiFi') == data


def test_process_path_matching_and_graceful_close(monkeypatch):
    wanted, other, denied = MagicMock(pid=1), MagicMock(pid=2), MagicMock(pid=3)
    wanted.exe.return_value = r'C:\Tools\app.exe'
    other.exe.return_value = r'C:\Other\app.exe'
    denied.exe.side_effect = psutil.AccessDenied(3)
    monkeypatch.setattr(net.psutil, 'process_iter', lambda: [wanted, other, denied])
    close = MagicMock()
    monkeypatch.setattr(net, '_request_process_close', close)
    assert net.kill_process(r'c:\TOOLS\app.exe')
    close.assert_called_once_with(1)
    wanted.wait.assert_called_once_with(timeout=3)
    wanted.kill.assert_not_called()
    other.wait.assert_not_called()
    other.kill.assert_not_called()
    denied.kill.assert_not_called()


def test_only_unresponsive_matching_process_is_killed(monkeypatch):
    proc = MagicMock(pid=1)
    proc.exe.return_value = r'C:\Tools\app.exe'
    proc.wait.side_effect = [psutil.TimeoutExpired(3), 0]
    proc.is_running.return_value = True
    monkeypatch.setattr(net.psutil, 'process_iter', lambda: [proc])
    monkeypatch.setattr(net, '_request_process_close', lambda _: None)
    assert net.kill_process(r'C:\Tools\app.exe')
    proc.kill.assert_called_once()
    assert proc.wait.call_count == 2


def test_netsh_timeout_is_bounded_and_returned_as_failure(monkeypatch):
    run = MagicMock(side_effect=subprocess.TimeoutExpired('netsh', 10))
    monkeypatch.setattr(net.subprocess, 'run', run)
    assert net._run_netsh(['wlan', 'show', 'interfaces'])[0] is False
    assert run.call_args.kwargs['timeout'] == 10


def test_missing_wmi_status_is_unknown_not_disabled(monkeypatch):
    monkeypatch.setattr(net, '_get_wmi_adapter', lambda _: MagicMock(ConfigManagerErrorCode=0, NetConnectionStatus=None))
    assert net.get_adapter_status('LAN') == 'unknown'


def test_pid_reused_during_graceful_wait_is_not_killed(monkeypatch):
    proc = MagicMock(pid=1)
    proc.exe.return_value = r'C:\Tools\app.exe'
    proc.wait.side_effect = psutil.TimeoutExpired(3)
    proc.is_running.return_value = False
    monkeypatch.setattr(net.psutil, 'process_iter', lambda: [proc])
    monkeypatch.setattr(net, '_request_process_close', lambda _: None)
    assert net.kill_process(r'C:\Tools\app.exe')
    proc.kill.assert_not_called()
