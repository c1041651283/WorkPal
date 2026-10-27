"""WorkPal 开机自启动任务计划管理测试。"""

from pathlib import Path
from unittest.mock import patch


def test_build_launch_target_for_frozen_exe():
    from workpal.features.autostart import build_launch_target

    target = build_launch_target(
        frozen=True,
        executable=r'C:\Tools\WorkPal\WorkPal.exe',
    )

    assert target.execute == r'C:\Tools\WorkPal\WorkPal.exe'
    assert target.arguments == ''
    assert target.working_directory == r'C:\Tools\WorkPal'


def test_build_launch_target_for_source_run():
    from workpal.features.autostart import build_launch_target

    target = build_launch_target(
        frozen=False,
        executable=r'C:\Python311\python.exe',
        main_path=Path(r'D:\WorkPal\main.py'),
    )

    assert target.execute == r'C:\Python311\python.exe'
    assert target.arguments == r'"D:\WorkPal\main.py"'
    assert target.working_directory == r'D:\WorkPal'


def test_enable_autostart_registers_workpal_task():
    from workpal.features import autostart

    target = autostart.LaunchTarget(
        execute=r'C:\Tools\WorkPal\WorkPal.exe',
        arguments='',
        working_directory=r'C:\Tools\WorkPal',
    )
    with patch('workpal.features.autostart.build_launch_target', return_value=target), \
         patch('workpal.features.autostart._run_powershell', return_value=(True, '')) as run:
        success, reason = autostart.enable_autostart()

    assert success
    assert reason == ''
    command = run.call_args.args[0]
    assert 'WorkPal_AutoStart' in command
    assert 'Register-ScheduledTask' in command
    assert r'C:\Tools\WorkPal\WorkPal.exe' in command
    assert "-Argument ''" not in command
    assert '-Argument' not in command
    assert '-ExecutionTimeLimit ([TimeSpan]::Zero)' in command
    assert 'Unregister-ScheduledTask' not in command
    assert '$Registered = Get-ScheduledTask' in command


def test_enable_autostart_keeps_source_run_argument():
    from workpal.features import autostart

    target = autostart.LaunchTarget(
        execute=r'C:\Python311\python.exe',
        arguments=r'"D:\WorkPal\main.py"',
        working_directory=r'D:\WorkPal',
    )
    with patch('workpal.features.autostart.build_launch_target', return_value=target), \
         patch('workpal.features.autostart._run_powershell', return_value=(True, '')) as run:
        success, _ = autostart.enable_autostart()

    assert success
    command = run.call_args.args[0]
    assert r'C:\Python311\python.exe' in command
    assert r'"D:\WorkPal\main.py"' in command


def test_disable_autostart_unregisters_workpal_task():
    from workpal.features import autostart

    with patch('workpal.features.autostart._run_powershell', return_value=(True, '')) as run:
        success, reason = autostart.disable_autostart()

    assert success
    assert reason == ''
    command = run.call_args.args[0]
    assert 'WorkPal_AutoStart' in command
    assert 'Unregister-ScheduledTask' in command


def test_tray_autostart_toggle_reports_success():
    from workpal import tray
    from workpal.features import autostart
    from unittest.mock import MagicMock

    autostart._set_cached_status(autostart.STATUS_DISABLED)
    with patch('workpal.features.autostart.enable_autostart', return_value=(True, '')) as enable:
        real_icon = MagicMock()
        tray._do_autostart_toggle(real_icon)

    enable.assert_called_once()
    real_icon.notify.assert_called_once()
    assert '已启用' in real_icon.notify.call_args.kwargs['message']


def test_tray_autostart_label_uses_cached_status_without_powershell_query():
    from workpal import tray
    from workpal.features import autostart

    autostart._set_cached_status(autostart.STATUS_ENABLED)
    with patch(
        'workpal.features.autostart.is_enabled',
        side_effect=AssertionError('menu must not query PowerShell synchronously'),
    ):
        assert tray._autostart_status_label(None) == '开机自动启动：已开启'


def test_refresh_autostart_status_async_updates_cache():
    from workpal.features import autostart

    with patch(
        'workpal.features.autostart._run_powershell',
        return_value=(True, 'enabled'),
    ):
        thread = autostart.refresh_autostart_status_async(wait=True)

    assert not thread.is_alive()
    assert autostart.get_cached_autostart_status() == autostart.STATUS_ENABLED


def test_enable_autostart_failure_sets_failed_cache():
    from workpal.features import autostart

    with patch(
        'workpal.features.autostart._run_powershell',
        return_value=(False, 'Access is denied'),
    ):
        success, reason = autostart.enable_autostart()

    assert not success
    assert reason == 'Access is denied'
    assert autostart.get_cached_autostart_status() == autostart.STATUS_FAILED
    assert 'Access is denied' in autostart.get_cached_autostart_error()
