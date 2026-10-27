"""脚本代理按钮、启动默认值及守护重新开启；系统写入全部使用替身。"""

import json
from unittest.mock import MagicMock, patch

import pytest

from workpal.features import vpn_proxy as vpn
from tests.test_vpn_proxy import ORIGINAL, manager_environment
from tests.test_network_recovery import machine


@pytest.fixture
def script_environment(manager_environment):
    manager, store, stack = manager_environment
    stack.enter_context(patch.object(vpn, 'assistant', manager))
    return manager, store, stack


def test_script_action_keeps_original_backup_and_manual_guard_can_start(script_environment):
    manager, store, stack = script_environment
    vpn.use_script_proxy()
    assert store.current.flags == 5
    assert store.current.bypass == ORIGINAL.bypass
    assert store.current.server == ORIGINAL.server
    assert not manager.active
    original = json.loads(vpn.backup_path().read_text(encoding='utf-8'))['original']
    # 公司有线只按网络状态启用固定代理，没有检疫确认门槛。
    stack.enter_context(patch.object(vpn, 'query_tunnel', return_value=vpn.TunnelStatus('disconnected', True, True)))
    manager.start(lambda _: None, once=True)
    thread = manager._thread
    if thread:
        thread.join(timeout=3)
    assert not manager.active
    assert store.current.flags == 3
    vpn.use_script_proxy()
    assert store.current.flags == 5
    assert json.loads(vpn.backup_path().read_text(encoding='utf-8'))['original'] == original
    assert not manager.active


def test_script_action_stops_guard_before_writing_and_is_idempotent(script_environment):
    manager, store, stack = script_environment
    steps = []
    stack.enter_context(patch.object(manager, 'stop', side_effect=lambda: steps.append('stop') or True))
    original_write = store.write
    def write(settings):
        assert steps == ['stop']
        original_write(settings)
    stack.enter_context(patch.object(store, 'write', side_effect=write))
    vpn.use_script_proxy()
    vpn.use_script_proxy()
    assert len(store.writes) == 1
    assert steps == ['stop', 'stop']


def test_stop_timeout_does_not_change_proxy(script_environment):
    manager, store, stack = script_environment
    stack.enter_context(patch.object(manager, 'stop', return_value=False))
    with pytest.raises(RuntimeError, match='仍在结束'):
        vpn.use_script_proxy()
    assert not store.writes and not vpn.backup_path().exists()


def test_backup_failure_does_not_change_proxy_or_keep_locks(script_environment):
    manager, store, stack = script_environment
    stack.enter_context(patch.object(vpn.ProxySession, '_save', side_effect=OSError('disk full')))
    with pytest.raises(OSError):
        vpn.use_script_proxy()
    assert not store.writes and not vpn.network_change_lock.locked()


def test_other_instance_or_network_switch_blocks_script_write(script_environment):
    manager, store, stack = script_environment
    with patch('win32event.WaitForSingleObject', return_value=258):
        with pytest.raises(RuntimeError, match='另一份'):
            vpn.use_script_proxy()
    with vpn.network_change_lock:
        with pytest.raises(RuntimeError, match='网卡'):
            vpn.use_script_proxy()
    assert not store.writes


def test_startup_enables_script_but_leaves_manual_guard_available(script_environment):
    from workpal import tray
    manager, store, stack = script_environment
    stack.enter_context(patch('workpal.features.session_events.session_events.start'))
    stack.enter_context(patch('workpal.features.autostart.refresh_autostart_status_async'))
    tray._on_tray_setup(MagicMock())
    assert store.current.flags == 5 and not manager.active
    guard = next(x for x in tray._build_menu().items if x.text == '代理守护')
    labels = [x.text for x in guard.submenu.items]
    assert '开启脚本代理（关闭手动代理）' in labels
    assert '开始公司检疫' not in labels and '检疫已通过' not in labels
    assert next(x for x in guard.submenu.items if x.text == '开启定时守护').enabled


def test_guard_start_during_script_change_is_rejected_then_available():
    from workpal import tray
    with patch.object(vpn, 'assistant') as manager:
        with tray._switch_lock:
            tray._on_proxy_guard_start(MagicMock(), None)
            tray._on_proxy_check(MagicMock(), None)
            tray._on_vpn_start(MagicMock(), None)
        manager.start.assert_not_called()
        tray._on_proxy_guard_start(MagicMock(), None)
        manager.start.assert_called_once()


def test_startup_failure_is_reported_without_locking_guard_menu(script_environment):
    from workpal import tray
    manager, store, stack = script_environment
    stack.enter_context(patch.object(vpn, 'use_script_proxy', side_effect=OSError('write denied')))
    stack.enter_context(patch('workpal.features.session_events.session_events.start'))
    stack.enter_context(patch('workpal.features.autostart.refresh_autostart_status_async'))
    notify = stack.enter_context(patch.object(tray, '_vpn_notify'))
    icon = MagicMock()
    tray._on_tray_setup(icon)
    assert '切换脚本代理失败' in notify.call_args.args[1]
    assert not tray._switch_lock.locked() and icon.visible
    assert not store.writes and not manager.active


def test_wired_switch_does_not_automatically_start_proxy_guard(machine):
    from workpal import tray
    with patch.object(vpn, 'assistant') as manager, patch.object(tray.network, 'get_current_mode', return_value='wifi'), \
         patch.object(tray.network, 'switch_to_ethernet', return_value=(True, '')), patch.object(tray, '_set_icon'):
        tray._switch_lock.acquire()
        tray._do_switch_and_release(MagicMock())
    manager.start.assert_not_called()


def test_existing_inspection_client_is_not_restarted_when_switching_wire(machine, monkeypatch):
    from workpal.features import network
    monkeypatch.setitem(network.CONFIG, 'ethernet_program_path', r'C:\installed\iNSIC.exe')
    with patch.object(network, 'check_process_running', return_value=True), \
         patch.object(network, 'kill_process') as kill, patch.object(network, 'start_program') as start:
        assert network.switch_to_ethernet()[0]
    kill.assert_not_called()
    start.assert_not_called()
