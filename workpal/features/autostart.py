"""Windows 任务计划开机自启动管理（任务计划 COM 接口，不启动 PowerShell）。"""

from __future__ import annotations

import logging
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

import pythoncom
import win32api
import win32com.client
import win32con

from workpal.system import is_frozen

logger = logging.getLogger(__name__)

TASK_NAME = 'WorkPal_AutoStart'
TASK_DESCRIPTION = 'WorkPal 工作助手 开机自启动'

STATUS_UNKNOWN = 'unknown'
STATUS_CHECKING = 'checking'
STATUS_ENABLED = 'enabled'
STATUS_DISABLED = 'disabled'
STATUS_OUTDATED = 'outdated'
STATUS_FAILED = 'failed'

# Task Scheduler 2.0 常量
_ROOT_FOLDER = '\\'
_ERROR_FILE_NOT_FOUND = -2147024894  # HRESULT_FROM_WIN32(ERROR_FILE_NOT_FOUND)
_TASK_TRIGGER_LOGON = 9
_TASK_ACTION_EXEC = 0
_TASK_CREATE_OR_UPDATE = 6
_TASK_LOGON_INTERACTIVE_TOKEN = 3
_TASK_RUNLEVEL_HIGHEST = 1
_NO_TIME_LIMIT = 'PT0S'

_status_lock = threading.RLock()
_cached_status = STATUS_UNKNOWN
_cached_error = ''


@dataclass(frozen=True)
class LaunchTarget:
    execute: str
    arguments: str
    working_directory: str


def build_launch_target(
    *,
    frozen: bool | None = None,
    executable: str | None = None,
    main_path: Path | None = None,
) -> LaunchTarget:
    """返回任务计划应启动的程序、参数和工作目录。"""
    frozen = is_frozen() if frozen is None else frozen
    executable = executable or sys.executable

    if frozen:
        exe_path = Path(executable)
        return LaunchTarget(
            execute=str(exe_path),
            arguments='',
            working_directory=str(exe_path.parent),
        )

    main_path = main_path or Path(__file__).resolve().parents[2] / 'main.py'
    return LaunchTarget(
        execute=str(executable),
        arguments=f'"{main_path}"',
        working_directory=str(main_path.parent),
    )


def _connect():
    """返回已连接的任务计划服务；COM 按线程初始化，由系统在线程/进程退出时清理。"""
    pythoncom.CoInitialize()
    service = win32com.client.Dispatch('Schedule.Service')
    service.Connect()
    return service


def _find_task(folder):
    try:
        return folder.GetTask(TASK_NAME)
    except pythoncom.com_error as exc:
        if exc.hresult == _ERROR_FILE_NOT_FOUND:
            return None
        raise


def _same_text(actual, expected: str) -> bool:
    return str(actual or '').casefold() == expected.casefold()


def _matches_target(definition, target: LaunchTarget) -> bool:
    """只有唯一一个启动动作且路径、参数、工作目录都指向当前程序才算有效。"""
    actions = definition.Actions
    if actions.Count != 1:
        return False
    action = actions.Item(1)
    return (action.Type == _TASK_ACTION_EXEC
            and _same_text(action.Path, target.execute)
            and str(action.Arguments or '') == target.arguments
            and _same_text(action.WorkingDirectory, target.working_directory)
            and Path(target.execute).is_file()
            and Path(target.working_directory).is_dir())


def _task_status(task, target: LaunchTarget) -> str:
    if task is None or not task.Enabled:
        return STATUS_DISABLED
    return STATUS_ENABLED if _matches_target(task.Definition, target) else STATUS_OUTDATED


def _query_status() -> str:
    """返回 enabled/disabled/outdated；查询失败时抛出异常。"""
    folder = _connect().GetFolder(_ROOT_FOLDER)
    return _task_status(_find_task(folder), build_launch_target())


def _describe(exc: Exception) -> str:
    if isinstance(exc, pythoncom.com_error):
        detail = exc.excepinfo[2] if exc.excepinfo and exc.excepinfo[2] else exc.strerror
        return f'{detail}（0x{exc.hresult & 0xFFFFFFFF:08X}）'
    return str(exc)


def is_enabled() -> bool:
    """同步检查自启动是否指向当前程序。菜单线程不要直接调用。"""
    return _query_status() == STATUS_ENABLED


def _set_cached_status(status: str, error: str = '') -> None:
    """更新自启动状态缓存。公开给测试，实际菜单只读缓存。"""
    global _cached_status, _cached_error
    with _status_lock:
        _cached_status = status
        _cached_error = error


def get_cached_autostart_status() -> str:
    with _status_lock:
        return _cached_status


def get_cached_autostart_error() -> str:
    with _status_lock:
        return _cached_error


def refresh_autostart_status_async(
    *,
    on_done=None,
    wait: bool = False,
) -> threading.Thread:
    """后台刷新任务计划状态，避免托盘菜单打开时同步查询。"""
    _set_cached_status(STATUS_CHECKING)

    def _worker() -> None:
        try:
            _set_cached_status(_query_status())
        except Exception as exc:
            logger.exception('刷新自启动状态失败')
            _set_cached_status(STATUS_FAILED, _describe(exc))
        finally:
            if on_done is not None:
                try:
                    on_done()
                except Exception:
                    logger.exception('自启动状态刷新回调失败')

    thread = threading.Thread(target=_worker, daemon=True, name='autostart-status')
    thread.start()
    if wait:
        thread.join(timeout=30)
    return thread


def _build_definition(service, target: LaunchTarget):
    definition = service.NewTask(0)
    definition.RegistrationInfo.Description = TASK_DESCRIPTION
    definition.Triggers.Create(_TASK_TRIGGER_LOGON)
    principal = definition.Principal
    principal.UserId = win32api.GetUserNameEx(win32con.NameSamCompatible)
    principal.LogonType = _TASK_LOGON_INTERACTIVE_TOKEN
    principal.RunLevel = _TASK_RUNLEVEL_HIGHEST
    settings = definition.Settings
    settings.Enabled = True
    settings.DisallowStartIfOnBatteries = False
    settings.StopIfGoingOnBatteries = False
    settings.StartWhenAvailable = True
    settings.ExecutionTimeLimit = _NO_TIME_LIMIT
    action = definition.Actions.Create(_TASK_ACTION_EXEC)
    action.Path = target.execute
    if target.arguments:
        action.Arguments = target.arguments
    action.WorkingDirectory = target.working_directory
    return definition


def enable_autostart() -> tuple[bool, str]:
    """创建或覆盖开机自启动任务，注册后重新读取验证。需要管理员权限。"""
    target = build_launch_target()
    try:
        service = _connect()
        folder = service.GetFolder(_ROOT_FOLDER)
        definition = _build_definition(service, target)
        # 用户和密码留空（VT_EMPTY），使用定义中的交互式令牌主体。
        folder.RegisterTaskDefinition(TASK_NAME, definition, _TASK_CREATE_OR_UPDATE,
                                      pythoncom.Empty, pythoncom.Empty,
                                      _TASK_LOGON_INTERACTIVE_TOKEN)
        registered = _find_task(folder)
        if (_task_status(registered, target) != STATUS_ENABLED
                or registered.Definition.Settings.ExecutionTimeLimit != _NO_TIME_LIMIT):
            raise RuntimeError('任务注册后的启动路径、状态或运行时限不正确')
    except Exception as exc:
        reason = _describe(exc)
        logger.error('启用自启动失败: %s', reason)
        _set_cached_status(STATUS_FAILED, reason)
        return False, reason
    _set_cached_status(STATUS_ENABLED)
    return True, ''


def disable_autostart() -> tuple[bool, str]:
    """删除开机自启动任务并确认已不存在。需要管理员权限。"""
    try:
        folder = _connect().GetFolder(_ROOT_FOLDER)
        if _find_task(folder) is not None:
            folder.DeleteTask(TASK_NAME, 0)
        if _find_task(folder) is not None:
            raise RuntimeError('任务删除后仍存在')
    except Exception as exc:
        reason = _describe(exc)
        logger.error('禁用自启动失败: %s', reason)
        _set_cached_status(STATUS_FAILED, reason)
        return False, reason
    _set_cached_status(STATUS_DISABLED)
    return True, ''
