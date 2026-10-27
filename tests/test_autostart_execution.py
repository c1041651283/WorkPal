"""任务计划 COM 调用流程；用内存替身代替 Schedule.Service，不注册真实任务。"""

import pythoncom
import pytest

from workpal.features import autostart
from tests import fake_task_scheduler as fake


@pytest.fixture
def scheduler(monkeypatch, tmp_path):
    service = fake.Service()
    executable = tmp_path / 'WorkPal.exe'
    executable.touch()
    target = autostart.LaunchTarget(str(executable), '', str(tmp_path))
    monkeypatch.setattr(autostart, '_connect', lambda: service)
    monkeypatch.setattr(autostart, 'build_launch_target', lambda: target)
    return service.folder, target


def test_enable_registers_logon_task_with_highest_privilege_and_no_time_limit(scheduler):
    folder, target = scheduler
    assert autostart.enable_autostart() == (True, '')
    name, definition, flags, user, password, logon = folder.registrations[-1]
    assert (name, flags, logon) == ('WorkPal_AutoStart', 6, 3)
    # 用户和密码留空，不在注册调用中传递任何凭据。
    assert user is pythoncom.Empty and password is pythoncom.Empty
    assert [t.Type for t in definition.Triggers] == [9]
    assert definition.Principal.RunLevel == 1 and definition.Principal.LogonType == 3
    assert definition.Principal.UserId
    settings = definition.Settings
    assert settings.ExecutionTimeLimit == 'PT0S' and settings.StartWhenAvailable
    assert not settings.DisallowStartIfOnBatteries and not settings.StopIfGoingOnBatteries
    [action] = definition.Actions
    assert (action.Path, action.Arguments, action.WorkingDirectory) == (target.execute, '', target.working_directory)
    assert autostart.get_cached_autostart_status() == autostart.STATUS_ENABLED


def test_source_run_keeps_main_script_argument(scheduler, monkeypatch, tmp_path):
    folder, _ = scheduler
    python = tmp_path / 'python.exe'
    python.touch()
    target = autostart.LaunchTarget(str(python), f'"{tmp_path / "main.py"}"', str(tmp_path))
    monkeypatch.setattr(autostart, 'build_launch_target', lambda: target)
    assert autostart.enable_autostart()[0]
    [action] = folder.registrations[-1][1].Actions
    assert action.Arguments == target.arguments


def _disable(folder, name):
    folder.tasks[name].Enabled = False


def _time_limit(folder, name):
    folder.tasks[name].Definition.Settings.ExecutionTimeLimit = 'PT72H'


def _old_path(folder, name):
    folder.tasks[name].Definition.Actions[0].Path = r'Z:\missing-old-package\WorkPal.exe'


def _vanish(folder, name):
    del folder.tasks[name]


def _denied(folder, name):
    raise fake.com_error(fake.ACCESS_DENIED, 'Access is denied.')


@pytest.mark.parametrize('after_register', [_disable, _time_limit, _old_path, _vanish, _denied])
def test_registration_result_is_verified(scheduler, after_register):
    folder, _ = scheduler
    folder.after_register = after_register
    success, reason = autostart.enable_autostart()
    assert not success and reason
    assert autostart.get_cached_autostart_status() == autostart.STATUS_FAILED
    assert reason in autostart.get_cached_autostart_error()


def test_access_denied_reason_is_readable(scheduler):
    folder, _ = scheduler
    folder.after_register = _denied
    _, reason = autostart.enable_autostart()
    assert 'Access is denied.' in reason and '0x80070005' in reason


def test_disable_removes_task_and_verifies(scheduler):
    folder, target = scheduler
    folder.tasks['WorkPal_AutoStart'] = fake.make_task(target.execute, '', target.working_directory)
    assert autostart.disable_autostart() == (True, '')
    assert 'WorkPal_AutoStart' not in folder.tasks
    assert autostart.get_cached_autostart_status() == autostart.STATUS_DISABLED
    # 任务本来就不存在也算成功。
    assert autostart.disable_autostart() == (True, '')


def test_disable_reports_task_that_survives_deletion(scheduler):
    folder, target = scheduler
    folder.tasks['WorkPal_AutoStart'] = fake.make_task(target.execute, '', target.working_directory)
    folder.delete_ignored = True
    success, reason = autostart.disable_autostart()
    assert not success and '仍存在' in reason
    assert autostart.get_cached_autostart_status() == autostart.STATUS_FAILED


def test_refresh_updates_cache_and_query_errors_are_failures(scheduler):
    folder, target = scheduler
    folder.tasks['WorkPal_AutoStart'] = fake.make_task(target.execute, '', target.working_directory)
    thread = autostart.refresh_autostart_status_async(wait=True)
    assert not thread.is_alive()
    assert autostart.get_cached_autostart_status() == autostart.STATUS_ENABLED
    assert autostart.is_enabled()
    folder.get_error = fake.ACCESS_DENIED
    autostart.refresh_autostart_status_async(wait=True)
    assert autostart.get_cached_autostart_status() == autostart.STATUS_FAILED
    assert '0x80070005' in autostart.get_cached_autostart_error()
    with pytest.raises(pythoncom.com_error):
        autostart.is_enabled()
