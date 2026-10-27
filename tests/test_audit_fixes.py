"""审计问题回归；只使用临时文件和系统操作替身。"""

from pathlib import Path
import threading
from unittest.mock import MagicMock, patch

import pytest

from workpal import tray
from workpal.features import autostart, vpn_proxy as vpn
from workpal.features.proxy_settings import ProxySession
from tests.test_vpn_proxy import DOWN, ORIGINAL, SERVER, UP, manager_environment


@pytest.mark.parametrize('save_number', [1, 2])
def test_stop_during_proxy_backup_does_not_write_or_launch(manager_environment, save_number):
    manager, store, stack = manager_environment
    stack.enter_context(patch.object(vpn, 'query_tunnel', return_value=DOWN))
    stack.enter_context(patch.object(vpn, 'find_forticlient', return_value=Path('FortiClient.exe')))
    launch = stack.enter_context(patch.object(vpn, 'launch_forticlient'))
    save = ProxySession._save
    calls = 0

    def save_and_pause(session):
        nonlocal calls
        save(session)
        calls += 1
        if calls == save_number:
            manager._stop.set()

    stack.enter_context(patch.object(ProxySession, '_save', save_and_pause))
    manager._run(lambda _: None, home=True)
    assert store.writes == []
    assert store.current == ORIGINAL
    launch.assert_not_called()
    assert '已暂停' in manager.status


def test_stop_during_initial_proxy_write_restores_before_launch(manager_environment):
    manager, store, stack = manager_environment
    stack.enter_context(patch.object(vpn, 'query_tunnel', return_value=DOWN))
    stack.enter_context(patch.object(vpn, 'find_forticlient', return_value=Path('FortiClient.exe')))
    launch = stack.enter_context(patch.object(vpn, 'launch_forticlient'))
    write = store.write

    def write_and_pause(settings):
        write(settings)
        manager._stop.set()

    stack.enter_context(patch.object(store, 'write', side_effect=write_and_pause))
    manager._run(lambda _: None, home=True)
    assert store.current == ORIGINAL
    launch.assert_not_called()
    assert '已暂停' in manager.status


def test_public_stop_waits_for_backup_and_prevents_proxy_change(manager_environment):
    manager, store, stack = manager_environment
    stack.enter_context(patch.object(vpn, 'query_tunnel', return_value=DOWN))
    stack.enter_context(patch.object(vpn, 'find_forticlient', return_value=Path('FortiClient.exe')))
    launch = stack.enter_context(patch.object(vpn, 'launch_forticlient'))
    saving, release = threading.Event(), threading.Event()
    save = ProxySession._save

    def blocked_save(session):
        save(session)
        saving.set()
        assert release.wait(5)

    stack.enter_context(patch.object(ProxySession, '_save', blocked_save))
    results = []
    stopper = threading.Thread(target=lambda: results.append(manager.stop()))
    manager.start(lambda _: None, home=True)
    try:
        assert saving.wait(3)
        stopper.start()
        assert manager._stop.wait(3)
    finally:
        release.set()
        if stopper.ident is not None:
            stopper.join(5)
        manager.stop()
    assert results == [True]
    assert not manager.active
    assert store.writes == []
    launch.assert_not_called()


@pytest.mark.parametrize('restore_fails', [False, True])
def test_pause_during_reconnect_restores_immediate_previous_proxy(manager_environment, restore_fails):
    manager, store, stack = manager_environment
    stack.enter_context(patch.object(vpn, 'query_tunnel', side_effect=[UP, DOWN]))
    stack.enter_context(patch.object(vpn, 'find_forticlient', return_value=Path('FortiClient.exe')))
    launch = stack.enter_context(patch.object(vpn, 'launch_forticlient'))
    stack.enter_context(patch.object(manager._wake, 'wait',
                                    side_effect=lambda _: manager._reconnect.set()))
    write = store.write

    def write_and_pause(settings):
        if manager._stop.is_set() and restore_fails:
            raise OSError('restore denied')
        write(settings)
        if settings.flags == 1:
            manager._stop.set()

    stack.enter_context(patch.object(store, 'write', side_effect=write_and_pause))
    manager._run(lambda _: None)
    launch.assert_not_called()
    assert vpn.backup_path().exists()
    if restore_fails:
        assert 'restore denied' in manager.status
        assert '已暂停' not in manager.status
    else:
        assert store.current == ORIGINAL.manual(SERVER)
        assert [value.flags for value in store.writes] == [3, 1, 3]


@pytest.mark.parametrize('resource', ['missing', 'corrupt'])
def test_source_startup_without_usable_icon_runs_tray(tmp_path, resource):
    path = tmp_path / 'icon_default.ico'
    if resource == 'corrupt':
        path.write_bytes(b'not an icon')
    with patch.object(tray, 'get_resource_path', return_value=str(path)), \
         patch.object(tray.pystray, 'Icon') as icon, \
         patch('workpal.features.session_events.session_events.stop'):
        tray.initial_tray()
    image = icon.call_args.args[1]
    assert image.width > 0 and image.height > 0
    assert image.getbbox() is not None
    icon.return_value.run.assert_called_once()


def test_outdated_autostart_menu_updates_instead_of_disabling():
    with patch.object(autostart, 'get_cached_autostart_status', return_value='outdated'), \
         patch.object(autostart, 'enable_autostart', return_value=(True, '')) as enable, \
         patch.object(autostart, 'disable_autostart') as disable:
        assert '需更新' in tray._autostart_status_label()
        tray._do_autostart_toggle(MagicMock())
    enable.assert_called_once()
    disable.assert_not_called()


@pytest.mark.parametrize('kind,expected', [
    ('current', 'enabled'), ('old', 'outdated'), ('missing', 'outdated'),
    ('arguments', 'outdated'), ('directory', 'outdated'), ('two-actions', 'outdated'),
    ('disabled', 'disabled'), ('absent', 'disabled'),
])
def test_autostart_checks_actual_launch_target(tmp_path, kind, expected):
    from tests import fake_task_scheduler as fake
    executable = tmp_path / "WorkPal's.exe"
    executable.touch()
    old_executable = tmp_path / 'old.exe'
    old_executable.touch()
    target = autostart.LaunchTarget(str(executable), '', str(tmp_path))
    service = fake.Service()
    if kind != 'absent':
        task = fake.make_task(
            str(old_executable) if kind == 'old' else str(executable).upper(),
            '--old' if kind == 'arguments' else '',
            str(tmp_path / 'old') if kind == 'directory' else str(tmp_path),
            enabled=kind != 'disabled')
        if kind == 'two-actions':
            task.Definition.Actions.Create(0)
        service.folder.tasks['WorkPal_AutoStart'] = task
    if kind == 'missing':
        executable.unlink()
    with patch.object(autostart, 'build_launch_target', return_value=target), \
         patch.object(autostart, '_connect', return_value=service):
        assert autostart._query_status() == expected
        autostart.refresh_autostart_status_async(wait=True)
        assert autostart.get_cached_autostart_status() == expected
