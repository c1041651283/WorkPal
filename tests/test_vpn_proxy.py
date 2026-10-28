"""代理与 VPN 状态机回归；所有系统写入、VPN 状态和进程启动均使用替身。"""

import ctypes
from dataclasses import replace
import json
from pathlib import Path
import subprocess

from tests.fake_view import FakeView
from unittest.mock import MagicMock, patch

import pytest

from workpal.features.proxy_settings import (
    ProxyChangedExternally, ProxySession, ProxySettings, WindowsProxyStore, _OptionList,
)
from workpal.features import vpn_proxy as vpn


ORIGINAL = ProxySettings(13, 'http://proxy.example.test:8080', '<local>;*.example.test',
                         'http://config.example.test/company.pac')
SERVER = 'proxy.example.test:8080'
UP = vpn.TunnelStatus('connected', True)
DOWN = vpn.TunnelStatus('disconnected')
UNKNOWN = vpn.TunnelStatus('unknown')


class FakeStore:
    def __init__(self):
        self.current = ORIGINAL
        self.writes = []

    def read(self):
        return self.current

    def write(self, settings):
        self.writes.append(settings)
        self.current = settings


@pytest.fixture
def flow(tmp_path):
    store = FakeStore()
    session = ProxySession(store, tmp_path / 'session.json')
    return vpn.ProxyFlow(session, SERVER)


def test_connection_login_and_disconnect_reconnect_sequence(flow):
    flow.prepare(DOWN)
    assert flow.session.store.current.flags == 1
    assert flow.session.store.current.pac_url == ORIGINAL.pac_url
    # 进程已启动或网卡已连接，不等于公司代理就绪。
    for _ in range(4):
        flow.tick(vpn.TunnelStatus('connected', False))
    assert flow.session.store.current.flags == 1
    assert flow.tick(UP) is None
    assert flow.tick(UP)
    assert flow.session.store.current == ORIGINAL.manual(SERVER)
    flow.tick(DOWN)
    flow.tick(DOWN)
    assert flow.session.store.current.flags == 3
    assert flow.tick(DOWN)
    assert flow.session.store.current.equivalent(ORIGINAL.direct())
    flow.tick(UP)
    flow.tick(UP)
    assert flow.session.store.current == ORIGINAL.manual(SERVER)
    flow.session.restore()
    assert flow.session.store.current == ORIGINAL
    assert not flow.session.path.exists()


def test_already_connected_is_never_temporarily_disconnected_from_proxy(flow):
    flow.prepare(UP)
    assert flow.session.store.writes == []
    flow.tick(UP)
    flow.tick(UP)
    assert [x.flags for x in flow.session.store.writes] == [3]


def test_unknown_at_start_has_no_backup_or_proxy_write(flow):
    with pytest.raises(RuntimeError, match='无法确认'):
        flow.prepare(UNKNOWN)
    assert not flow.session.path.exists()
    assert flow.session.store.writes == []


def test_unknown_interrupts_disconnect_debounce_and_does_not_turn_proxy_off(flow):
    flow.prepare(UP)
    flow.tick(UP)
    flow.tick(UP)
    for state in (DOWN, DOWN, UNKNOWN, DOWN, DOWN):
        flow.tick(state)
    assert flow.session.store.current.flags == 3
    flow.tick(DOWN)
    assert flow.session.store.current.flags == 1


def test_unknown_or_proxy_outage_never_means_tunnel_disconnected(flow):
    flow.prepare(UP)
    flow.tick(UP)
    flow.tick(UP)
    for state in (UNKNOWN, vpn.TunnelStatus('connected', False)) * 4:
        flow.tick(state)
    assert flow.session.store.current.flags == 3


def test_connected_observations_must_be_consecutive(flow):
    flow.prepare(DOWN)
    for state in (UP, UNKNOWN, UP, DOWN, UP):
        flow.tick(state)
    assert flow.session.store.current.flags == 1
    flow.tick(UP)
    assert flow.session.store.current.flags == 3


def test_external_change_is_repaired_only_after_network_confirmation(flow):
    flow.prepare(DOWN)
    external = replace(ORIGINAL, server='other.example.test:3128', flags=3)
    flow.session.store.current = external
    flow.tick(UNKNOWN)
    flow.tick(UP)
    assert flow.session.store.current == external
    with pytest.raises(ProxyChangedExternally):
        flow.session.restore()
    assert flow.session.store.current == external
    assert flow.session.path.exists()
    flow.tick(UP)
    assert flow.session.store.current == external.manual(SERVER)
    flow.session.restore(explicit=True)
    assert flow.session.store.current == ORIGINAL


def test_existing_backup_cannot_be_overwritten(flow):
    flow.prepare(DOWN)
    before = flow.session.path.read_bytes()
    replacement = ProxySession(flow.session.store, flow.session.path)
    with pytest.raises(RuntimeError, match='上次代理备份'):
        replacement.begin()
    assert flow.session.path.read_bytes() == before


def test_backup_must_be_saved_before_any_proxy_write(flow):
    flow.prepare(UP)
    with patch.object(flow.session, '_save', side_effect=OSError('disk full')):
        with pytest.raises(OSError):
            flow.session.apply(ORIGINAL.direct())
    assert flow.session.store.current == ORIGINAL
    assert flow.session.store.writes == []


@pytest.mark.parametrize('write_completed', [True, False])
def test_crash_recovery_handles_either_side_of_system_write(flow, write_completed):
    flow.prepare(UP)
    flow.session.previous = ORIGINAL
    flow.session.expected = ORIGINAL.direct()
    flow.session._save()
    if write_completed:
        flow.session.store.current = ORIGINAL.direct()
    recovered = ProxySession(flow.session.store, flow.session.path)
    recovered.restore()
    assert flow.session.store.current == ORIGINAL


def test_partial_write_failure_still_has_original_backup(flow):
    flow.prepare(UP)
    with patch.object(flow.session.store, 'write', side_effect=OSError('write denied')):
        with pytest.raises(OSError):
            flow.session.apply(ORIGINAL.direct())
    data = json.loads(flow.session.path.read_text(encoding='utf-8'))
    assert data['original']['flags'] == ORIGINAL.flags
    assert data['expected']['flags'] == 1
    flow.session.restore()
    assert flow.session.store.current == ORIGINAL


def test_failed_restore_preserves_backup(flow):
    flow.prepare(DOWN)
    with patch.object(flow.session.store, 'write', side_effect=OSError('denied')):
        with pytest.raises(OSError):
            flow.session.restore()
    assert flow.session.path.exists()


def adapter(status, addresses=None, name='Fortinet SSL VPN Virtual Ethernet Adapter'):
    return {'name': name, 'status': status, 'addresses': addresses,
            'friendly_name': 'VPN', 'interface_type': 53}


@pytest.mark.parametrize('adapters,expected', [
    ([], 'unknown'),
    ([adapter(7)], 'disconnected'),
    ([adapter(5), adapter(7)], 'disconnected'),
    ([adapter(None)], 'unknown'),
    ([adapter(1)], 'unknown'),
    ([adapter(2)], 'unknown'),
    ([adapter(2, ['169.254.1.2', 'fe80::123'])], 'unknown'),
    ([adapter(2, ['10.1.2.3'])], 'connected'),
    ([adapter(2, ['fd00::123'])], 'connected'),
    ([adapter(7), adapter(2, ['10.1.2.3'])], 'connected'),
    ([adapter(2, ['10.1.2.3'], 'Intel Ethernet')], 'unknown'),
])
def test_tunnel_detection(adapters, expected):
    assert vpn.classify_adapters(adapters, True).state == expected


def test_probe_timeout_preserves_known_adapter_state_and_only_probes_tcp():
    with patch.object(vpn, 'read_adapters', return_value=[adapter(2, ['10.1.2.3'])]), \
         patch.object(vpn, '_resolve', return_value=[(2, 1, 6, '', ('10.0.0.1', 8080))]), \
         patch.object(vpn.socket, 'socket') as sock, \
         patch.object(vpn.subprocess, 'run') as run:
        sock.return_value.__enter__.return_value.connect.side_effect = TimeoutError()
        assert vpn.query_tunnel(SERVER) == vpn.TunnelStatus('connected', False)
    run.assert_not_called()
    connection = sock.return_value.__enter__.return_value
    connection.connect.assert_called_once_with(('10.0.0.1', 8080))
    connection.send.assert_not_called()
    connection.sendall.assert_not_called()


def test_probe_connects_to_local_listener_and_rejects_closed_port():
    import socket
    with socket.create_server(('127.0.0.1', 0)) as server:
        port = server.getsockname()[1]
        assert vpn.probe_proxy(f'127.0.0.1:{port}')
    assert not vpn.probe_proxy(f'127.0.0.1:{port}')


def test_probe_dns_failure_or_timeout_is_not_ready():
    with patch.object(vpn, '_resolve', side_effect=TimeoutError('slow dns')):
        assert vpn.probe_proxy(SERVER) is False
    with patch.object(vpn.socket, 'getaddrinfo', side_effect=lambda *a, **k: __import__('time').sleep(1)), \
         patch.object(vpn, 'PROBE_TIMEOUT_SECONDS', 0.05):
        assert vpn.probe_proxy(SERVER) is False


@pytest.mark.parametrize('value', ['bad;command:80', "host'bad:80", 'host:0', 'host:65536',
                                  'user:password@host:80', 'http://host:80/path'])
def test_proxy_configuration_rejects_invalid_or_command_text(value):
    with pytest.raises(ValueError):
        vpn.parse_proxy(value)


def test_launch_only_opens_existing_forticlient_gui_without_arguments(tmp_path):
    executable = tmp_path / 'FortiClient.exe'
    executable.touch()
    assert vpn.find_forticlient(str(executable)) == executable
    with patch.object(vpn.subprocess, 'Popen') as popen:
        vpn.launch_forticlient(executable)
    assert popen.call_args.args == ([str(executable)],)
    assert popen.call_args.kwargs['shell'] is False
    with pytest.raises(RuntimeError):
        vpn.find_forticlient(str(tmp_path / 'FortiVPN.exe'))


def test_wininet_write_only_targets_default_lan_and_preserves_addresses():
    store = WindowsProxyStore.__new__(WindowsProxyStore)
    store.api = MagicMock()
    wanted = ORIGINAL.direct()
    captured = []

    def set_option(handle, flag, pointer, size):
        assert handle is None
        if flag == 75:
            info = ctypes.cast(pointer, ctypes.POINTER(_OptionList)).contents
            assert info.connection is None
            assert info.options[0].option == 1
            captured.append(info.options[0].value.number)
            captured.extend(ctypes.wstring_at(info.options[i].value.text) for i in (1, 2, 3))
        return True

    store.api.InternetSetOptionW.side_effect = set_option
    with patch.object(store, 'read', return_value=wanted):
        store.write(wanted)
    assert captured == [1, ORIGINAL.server, ORIGINAL.bypass, ORIGINAL.pac_url]
    assert [c.args[1] for c in store.api.InternetSetOptionW.call_args_list] == [75, 39, 37]


def test_launch_failure_rolls_back_proxy_without_touching_vpn(tmp_path):
    store = FakeStore()
    manager = vpn.VpnProxyAssistant()
    messages = []
    with patch.object(vpn, 'query_tunnel', return_value=DOWN), \
         patch.object(vpn, 'find_forticlient', return_value=Path('FortiClient.exe')), \
         patch.object(vpn, 'launch_forticlient', side_effect=OSError('launch failed')), \
         patch.object(vpn, 'WindowsProxyStore', return_value=store), \
         patch.object(vpn, 'backup_path', return_value=tmp_path / 'backup.json'), \
         patch('win32event.CreateMutex', return_value=1), \
         patch('win32event.WaitForSingleObject', return_value=0), \
         patch('win32event.ReleaseMutex'), patch('win32api.CloseHandle'):
        manager._run(messages.append, home=True)
    assert [x.flags for x in store.writes] == [1, ORIGINAL.flags]
    assert (tmp_path / 'backup.json').exists()


def test_second_process_does_not_read_or_change_proxy():
    manager = vpn.VpnProxyAssistant()
    with patch('win32event.CreateMutex', return_value=1), \
         patch('win32event.WaitForSingleObject', return_value=258), \
         patch('win32api.CloseHandle'), patch.object(vpn, 'WindowsProxyStore') as store:
        manager._run(lambda _: None)
    store.assert_not_called()


@pytest.mark.parametrize('method', ['switch_to_wifi', 'switch_to_ethernet'])
def test_network_switch_is_blocked_while_assistant_owns_proxy(method):
    from workpal.features import network
    with patch.object(vpn, 'assistant', active=True), \
         patch.object(network, 'disable_adapter') as disable, \
         patch.object(network, 'disconnect_wifi') as disconnect:
        success, reason = getattr(network, method)()
    assert not success and 'VPN' in reason
    disable.assert_not_called()
    disconnect.assert_not_called()


def test_pac_reapplied_during_normal_use_is_repaired_without_vpn_restart(flow):
    flow.prepare(UP)
    flow.tick(UP)
    flow.tick(UP)
    external = replace(ORIGINAL, flags=5, pac_url='http://config.example.test/new.pac',
                       bypass='<local>;*.new.example.test')
    flow.session.store.current = external
    assert flow.tick(UP)
    assert flow.session.store.current == external.manual(SERVER)
    writes = len(flow.session.store.writes)
    for _ in range(10):
        flow.tick(UP)
    assert len(flow.session.store.writes) == writes


def test_equivalent_http_prefix_never_causes_repeated_writes(flow):
    flow.prepare(UP)
    flow.tick(UP, immediate=True)
    flow.session.store.current = replace(flow.session.store.current, server='http://' + SERVER)
    flow.session.check_owned()
    flow.tick(UP)
    assert len(flow.session.store.writes) == 1


def test_guard_never_overwrites_backup_when_restarted(flow):
    flow.prepare(UP)
    flow.tick(UP, immediate=True)
    replacement = ProxySession(flow.session.store, flow.session.path)
    replacement.begin(resume=True)
    assert replacement.original == ORIGINAL
    replacement.restore(explicit=True)
    assert flow.session.store.current == ORIGINAL


def test_guard_backup_failure_blocks_repair(flow):
    flow.prepare(UP)
    with patch.object(flow.session, '_save', side_effect=OSError('disk full')):
        with pytest.raises(OSError):
            flow.tick(UP, immediate=True)
    assert flow.session.store.writes == []


def test_corrupt_existing_backup_blocks_guard_start_without_proxy_write(flow):
    flow.session.path.write_text('{broken', encoding='utf-8')
    with pytest.raises(ValueError):
        flow.prepare(UP)
    assert flow.session.store.writes == []


def test_office_lan_enables_guard_even_without_a_fortinet_adapter(flow):
    flow.home = False
    office = vpn.TunnelStatus('unknown', True, True)
    flow.prepare(office)
    flow.tick(office, immediate=True)
    assert flow.session.store.current.flags == 3
    # 有线仍连接但代理暂时故障，不能误当 VPN 断开。
    for _ in range(5):
        flow.tick(vpn.TunnelStatus('disconnected', False, True))
    assert flow.session.store.current.flags == 3


def test_home_start_on_office_lan_never_turns_proxy_off(flow):
    flow.prepare(vpn.TunnelStatus('disconnected', True, True))
    assert flow.session.store.writes == []


def test_guard_on_unknown_network_or_unconnected_home_leaves_proxy_untouched(flow):
    flow.home = False
    flow.prepare(UNKNOWN)
    for _ in range(5):
        flow.tick(DOWN)
    assert flow.session.store.writes == []


@pytest.mark.parametrize('value,expected', [
    ('60', 60), ('120', 120), ('300', 300), ('5', 30), ('-1', 30),
    ('99999', 3600), ('bad', 60), (None, 60),
])
def test_check_interval_is_low_frequency_and_bounded(value, expected):
    with patch.dict('workpal.config.CONFIG', {'proxy_check_interval': value}):
        assert vpn.check_interval() == expected


@pytest.fixture
def manager_environment(tmp_path):
    from contextlib import ExitStack
    manager = vpn.VpnProxyAssistant()
    store = FakeStore()
    with ExitStack() as stack:
        for target, kwargs in [
            ('win32event.CreateMutex', {'return_value': 1}),
            ('win32event.WaitForSingleObject', {'return_value': 0}),
            ('win32event.ReleaseMutex', {}), ('win32api.CloseHandle', {}),
        ]:
            stack.enter_context(patch(target, **kwargs))
        stack.enter_context(patch.dict('workpal.config.CONFIG', {'vpn_proxy_server': SERVER,
                                                               'proxy_check_interval': '60'}))
        stack.enter_context(patch.object(vpn, 'WindowsProxyStore', return_value=store))
        stack.enter_context(patch.object(vpn, 'backup_path', return_value=tmp_path / 'backup.json'))
        yield manager, store, stack


def test_single_check_repairs_then_finishes_without_launch_or_restore(manager_environment):
    manager, store, stack = manager_environment
    query = stack.enter_context(patch.object(vpn, 'query_tunnel', return_value=UP))
    launch = stack.enter_context(patch.object(vpn, 'launch_forticlient'))
    find = stack.enter_context(patch.object(vpn, 'find_forticlient'))
    wait = stack.enter_context(patch.object(manager._wake, 'wait'))
    manager._run(lambda _: None, once=True)
    assert store.current == ORIGINAL.manual(SERVER)
    assert len(store.writes) == 1
    query.assert_called_once()
    launch.assert_not_called()
    find.assert_not_called()
    wait.assert_not_called()
    assert '单次检查完成' in manager.status


def test_single_check_unknown_network_makes_no_changes(manager_environment):
    manager, store, stack = manager_environment
    stack.enter_context(patch.object(vpn, 'query_tunnel', return_value=UNKNOWN))
    manager._run(lambda _: None, once=True)
    assert store.writes == []
    assert '保持当前代理' in manager.status


def test_low_frequency_guard_waits_and_stop_does_not_restore_old_pac(manager_environment):
    manager, store, stack = manager_environment
    stack.enter_context(patch.object(vpn, 'query_tunnel', return_value=UP))
    wait = stack.enter_context(patch.object(manager._wake, 'wait',
                                           side_effect=lambda _: manager._stop.set()))
    manager._run(lambda _: None)
    wait.assert_called_once_with(60)
    assert store.current == ORIGINAL.manual(SERVER)
    assert len(store.writes) == 1
    assert '已暂停' in manager.status


def test_manual_check_wakes_existing_worker_without_starting_another():
    manager = vpn.VpnProxyAssistant()
    manager._thread = MagicMock()
    manager._thread.is_alive.return_value = True
    with patch.object(vpn.threading, 'Thread') as thread:
        manager.start(lambda _: None, once=True)
    thread.assert_not_called()
    assert manager._wake.is_set()
    assert manager._manual_check.is_set()


def test_stop_during_network_query_prevents_proxy_write(manager_environment):
    manager, store, stack = manager_environment
    def query(_):
        manager._stop.set()
        return UP
    stack.enter_context(patch.object(vpn, 'query_tunnel', side_effect=query))
    manager._run(lambda _: None, once=True)
    assert store.writes == []


def test_bad_query_or_write_does_not_restore_original_pac(manager_environment):
    manager, store, stack = manager_environment
    stack.enter_context(patch.object(vpn, 'query_tunnel', side_effect=[UP, RuntimeError('query failed')]))
    stack.enter_context(patch.object(manager._wake, 'wait', return_value=False))
    manager._run(lambda _: None)
    assert store.current.flags == 3
    assert len(store.writes) == 1
    assert '守护已停止' in manager.status


def test_query_office_result_and_literal_adapter_name_are_handled():
    office = dict(adapter(2, ['10.1.2.3'], name='Intel Ethernet'),
                  friendly_name="Office'LAN", interface_type=6)
    with patch.dict('workpal.config.CONFIG', {'ethernet_adapter_name': "Office'LAN"}), \
         patch.object(vpn, 'read_adapters', return_value=[office]), \
         patch.object(vpn, 'probe_proxy', return_value=True) as probe:
        assert vpn.query_tunnel(SERVER).ready
    probe.assert_called_once_with(SERVER)  # 只探测代理地址，网卡名不进入任何命令。


def test_startup_does_not_enable_guard_even_with_existing_backup(tmp_path):
    from workpal import tray
    backup = tmp_path / 'backup.json'
    backup.touch()
    with patch.object(vpn, 'assistant') as manager, \
         patch.object(vpn, 'use_script_proxy') as script_proxy, \
         patch.object(vpn, 'backup_path', return_value=backup), \
         patch('workpal.features.session_events.session_events.start'), \
         patch('workpal.features.autostart.refresh_autostart_status_async'):
        tray.startup(FakeView())
    manager.start.assert_not_called()
    script_proxy.assert_called_once()


def test_manual_check_notification_can_read_status_without_deadlocking():
    manager = vpn.VpnProxyAssistant()
    manager._thread = MagicMock()
    manager._thread.is_alive.return_value = True
    def notify(_):
        assert manager._lock.acquire(blocking=False)
        manager._lock.release()
        assert manager.active
    manager.start(notify, once=True)


def test_home_wired_network_does_not_masquerade_as_company_lan(flow):
    home_wired = vpn.TunnelStatus('disconnected', False, True)
    flow.prepare(home_wired)
    assert flow.session.store.current.flags == 1
    flow.tick(UP)
    flow.tick(UP)
    for _ in range(3):
        flow.tick(home_wired)
    assert flow.session.store.current.flags == 1


def test_wininet_accepts_equivalent_normalized_proxy_result():
    store = WindowsProxyStore.__new__(WindowsProxyStore)
    store.api = MagicMock()
    wanted = ORIGINAL.manual(SERVER)
    with patch.object(store, 'read', return_value=replace(wanted, server='http://' + SERVER)):
        store.write(wanted)


def test_interval_menu_persists_choice_without_starting_guard(tmp_path):
    from workpal import tray, config
    settings = tmp_path / 'settings.json'
    with patch.object(config, '_USER_CONFIG_FILE', settings), \
         patch.dict(config.CONFIG, {'proxy_check_interval': '60'}), \
         patch.object(vpn, 'assistant') as manager:
        tray.set_interval(FakeView(), 300)
        assert vpn.check_interval() == 300
        assert json.loads(settings.read_text(encoding='utf-8'))['proxy_check_interval'] == '300'
    manager.start.assert_not_called()


def test_failed_interval_save_keeps_previous_setting():
    from workpal import config
    with patch.dict(config.CONFIG, {'proxy_check_interval': '60'}), \
         patch.object(config, '_write_user_overrides', side_effect=OSError('disk full')):
        with pytest.raises(OSError):
            config.set_config_value('proxy_check_interval', '300')
        assert config.CONFIG['proxy_check_interval'] == '60'


def test_single_check_notifies_completion_after_worker_releases_ownership(manager_environment):
    manager, store, stack = manager_environment
    stack.enter_context(patch.object(vpn, 'query_tunnel', return_value=UP))
    manager._thread = vpn.threading.current_thread()
    seen = []
    def notify(message):
        seen.append(message)
        assert not manager.active
        assert vpn.network_change_lock.acquire(blocking=False)
        vpn.network_change_lock.release()
    manager._run(notify, once=True)
    assert len(seen) == 1
    assert '单次检查完成' in seen[0]


def test_adapter_read_failure_is_unknown_without_proxy_probe():
    with patch.object(vpn, 'read_adapters', side_effect=OSError('read failed')), \
         patch.object(vpn, 'probe_proxy') as probe:
        assert vpn.query_tunnel(SERVER) == UNKNOWN
    probe.assert_not_called()


def test_stale_up_adapter_with_unreachable_proxy_is_not_reported_healthy(flow):
    flow.prepare(UP)
    flow.tick(UP)
    flow.tick(UP)
    lost = vpn.TunnelStatus('connected', False)
    for _ in range(2):
        flow.tick(lost)
        assert flow.session.store.current.flags == 3
        assert '不可达' in flow.describe(lost)
    assert flow.tick(lost)
    assert flow.session.store.current.flags == 1
    assert 'VPN 已断开' not in flow.describe(lost)
    flow.tick(UP)
    assert flow.session.store.current.flags == 1
    flow.tick(UP)
    assert flow.session.store.current.flags == 3


def test_unknown_does_not_trigger_home_outage_fallback(flow):
    flow.prepare(UP)
    flow.tick(UP, immediate=True)
    for _ in range(10):
        flow.tick(UNKNOWN)
    assert flow.session.store.current.flags == 3
    assert '无法确认' in flow.describe(UNKNOWN)


def test_explicit_reconnect_works_while_status_unknown_and_preserves_backup(flow):
    flow.prepare(UP)
    flow.tick(UP, immediate=True)
    flow.reconnect(UNKNOWN)
    assert flow.session.store.current.flags == 1
    assert json.loads(flow.session.path.read_text(encoding='utf-8'))['original']['flags'] == ORIGINAL.flags


def test_healthy_reconnect_request_never_temporarily_disables_proxy(flow):
    flow.prepare(UP)
    flow.tick(UP, immediate=True)
    writes = len(flow.session.store.writes)
    flow.reconnect(UP)
    assert len(flow.session.store.writes) == writes


def test_home_button_queues_reconnect_in_same_active_worker():
    manager = vpn.VpnProxyAssistant()
    manager._thread = MagicMock()
    manager._thread.is_alive.return_value = True
    with patch.object(vpn.threading, 'Thread') as thread:
        manager.start(lambda _: None, home=True)
    assert manager._reconnect.is_set()
    assert manager._wake.is_set()
    thread.assert_not_called()


def test_unlock_never_enables_inactive_guard_and_duplicate_events_are_coalesced():
    manager = vpn.VpnProxyAssistant()
    assert manager.request_resume_check('解锁') is False
    manager._thread = MagicMock()
    manager._thread.is_alive.return_value = True
    with patch.object(vpn.time, 'monotonic', side_effect=[100, 101, 120]):
        assert manager.request_resume_check('唤醒')
        assert not manager.request_resume_check('解锁')
        assert manager.request_resume_check('解锁')
    assert manager._resume_check.is_set()
    assert manager._wake.is_set()


def test_unlock_runs_only_three_quick_checks_then_restores_user_interval(manager_environment):
    manager, store, stack = manager_environment
    stack.enter_context(patch.dict('workpal.config.CONFIG', {'proxy_check_interval': '300'}))
    stack.enter_context(patch.object(vpn, 'query_tunnel', side_effect=[UP, DOWN, DOWN, DOWN]))
    waits = []
    def wait(seconds):
        waits.append(seconds)
        if len(waits) == 1:
            manager._resume_check.set()
        if len(waits) == 4:
            manager._stop.set()
    stack.enter_context(patch.object(manager._wake, 'wait', side_effect=wait))
    manager._run(lambda _: None)
    assert waits == [300, 5, 5, 300]
    assert [x.flags for x in store.writes] == [3, 1]


def test_status_and_check_time_refresh_even_when_unknown_does_not_write(manager_environment):
    manager, store, stack = manager_environment
    stack.enter_context(patch.object(vpn, 'query_tunnel', side_effect=[UP, UNKNOWN]))
    waits = []
    def wait(_):
        waits.append(1)
        if len(waits) == 2:
            manager._stop.set()
    stack.enter_context(patch.object(manager._wake, 'wait', side_effect=wait))
    states = []
    manager._run(lambda _: None, refresh=lambda: states.append((manager.status, manager.last_checked)))
    assert len(states) == 2
    assert '无法确认' in states[1][0]
    assert states[1][1]
    assert len(store.writes) == 1


def test_active_guard_can_prepare_reconnect_without_restoring_old_settings(manager_environment):
    manager, store, stack = manager_environment
    stack.enter_context(patch.object(vpn, 'query_tunnel', side_effect=[UP, DOWN]))
    stack.enter_context(patch.object(vpn, 'find_forticlient', return_value=Path('FortiClient.exe')))
    launch = stack.enter_context(patch.object(vpn, 'launch_forticlient'))
    waits = []
    def wait(_):
        waits.append(1)
        if len(waits) == 1:
            manager._reconnect.set()
        else:
            manager._stop.set()
    stack.enter_context(patch.object(manager._wake, 'wait', side_effect=wait))
    manager._run(lambda _: None)
    assert [x.flags for x in store.writes] == [3, 1]
    launch.assert_called_once()
    assert json.loads(vpn.backup_path().read_text(encoding='utf-8'))['original']['flags'] == ORIGINAL.flags


def test_menu_refresh_does_not_call_wmi_or_netsh():
    from workpal import tray
    from workpal.features import adapter_status
    wifi = dict(adapter(2, ['192.168.1.2'], name='Wi-Fi'), friendly_name='TestWiFi')
    with patch.dict('workpal.config.CONFIG', {'wifi_adapter_name': 'TestWiFi'}), \
         patch.object(adapter_status, 'read_adapters', return_value=[wifi]), \
         patch('workpal.features.network.get_current_mode') as old_query:
        assert tray.current_state().mode == 'wifi'
    old_query.assert_not_called()


def test_reconnect_during_single_check_upgrades_to_home_guard(manager_environment):
    import threading
    manager, store, stack = manager_environment
    manager._thread = threading.current_thread()
    messages = []
    calls = []
    def query(_):
        calls.append(1)
        if len(calls) == 1:
            manager.start(messages.append, home=True)
        return DOWN
    stack.enter_context(patch.object(vpn, 'query_tunnel', side_effect=query))
    stack.enter_context(patch.object(vpn, 'find_forticlient', return_value=Path('FortiClient.exe')))
    launch = stack.enter_context(patch.object(vpn, 'launch_forticlient'))
    waits = []
    def wait(seconds):
        waits.append(seconds)
        if len(waits) == 2:
            manager._stop.set()
    stack.enter_context(patch.object(manager._wake, 'wait', side_effect=wait))
    states = []
    manager._run(messages.append, once=True, refresh=lambda: states.append(manager.status))
    launch.assert_called_once()
    assert len(calls) == 2 and len(waits) == 2
    assert any('在家守护中' in state for state in states)
    assert store.current.flags == 1
    assert not manager._reconnect.is_set()


def test_request_during_single_check_cleanup_starts_after_resources_release(manager_environment):
    import threading
    manager, store, stack = manager_environment
    manager._thread = threading.current_thread()
    stack.enter_context(patch.object(vpn, 'query_tunnel', return_value=DOWN))
    stack.enter_context(patch('win32event.ReleaseMutex',
                             side_effect=lambda _: manager.start(lambda _: None, home=True)))
    def next_start(*args, **kwargs):
        assert not vpn.network_change_lock.locked()
        assert kwargs['home'] and not kwargs['once']
    start = stack.enter_context(patch.object(manager, '_start_locked', side_effect=next_start))
    manager._run(lambda _: None, once=True)
    start.assert_called_once()


def test_proxy_ownership_releases_mutex_and_network_lock_on_error():
    with patch('win32event.CreateMutex', return_value=7), \
         patch('win32event.WaitForSingleObject', return_value=0), \
         patch('win32event.ReleaseMutex') as release, patch('win32api.CloseHandle') as close:
        with pytest.raises(OSError):
            with vpn._proxy_ownership('busy', 'switching'):
                assert vpn.network_change_lock.locked()
                raise OSError('write failed')
        with vpn._proxy_ownership('busy'):
            assert not vpn.network_change_lock.locked()
    assert not vpn.network_change_lock.locked()
    assert release.call_count == 2 and close.call_count == 2


def test_proxy_ownership_busy_mutex_never_takes_network_lock():
    with patch('win32event.CreateMutex', return_value=7), \
         patch('win32event.WaitForSingleObject', return_value=258), \
         patch('win32event.ReleaseMutex') as release, patch('win32api.CloseHandle') as close:
        with pytest.raises(RuntimeError, match='busy'):
            with vpn._proxy_ownership('busy', 'switching'):
                pass
    release.assert_not_called()
    close.assert_called_once_with(7)
    assert not vpn.network_change_lock.locked()
