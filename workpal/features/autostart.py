"""Windows 任务计划开机自启动管理。"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from workpal.system import is_frozen

logger = logging.getLogger(__name__)

TASK_NAME = 'WorkPal_AutoStart'

STATUS_UNKNOWN = 'unknown'
STATUS_CHECKING = 'checking'
STATUS_ENABLED = 'enabled'
STATUS_DISABLED = 'disabled'
STATUS_OUTDATED = 'outdated'
STATUS_FAILED = 'failed'

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


def is_enabled() -> bool:
    """同步检查自启动是否指向当前程序。菜单线程不要直接调用。"""
    enabled, reason = _query_autostart_enabled()
    if enabled is None:
        raise RuntimeError(reason or '查询任务计划失败')
    return enabled


def _query_autostart_enabled() -> tuple[bool | None, str]:
    """返回当前程序的自启动状态；旧任务返回 False/outdated，查询失败返回 None。"""
    target = build_launch_target()
    command = (
        f"$Task = Get-ScheduledTask -TaskPath '\\' -ErrorAction Stop | Where-Object {{ $_.TaskName -eq '{TASK_NAME}' }}\n"
        + _target_check_command('$Task', target)
        + "\nif ($null -eq $Task -or -not $Task.Settings.Enabled) { 'disabled' } "
          "elseif ($MatchesTarget) { 'enabled' } else { 'outdated' }"
    )
    success, output = _run_powershell(command)
    if not success:
        return None, output
    value = output.strip().lower()
    if value not in ('enabled', 'disabled', 'outdated'):
        return None, '任务计划返回了无法识别的状态'
    return value == 'enabled', output


def _target_check_command(task: str, target: LaunchTarget) -> str:
    """查询及注册后验证复用同一组检查；task 只能由内部固定变量名传入。"""
    return f"""
$Actions = @({task}.Actions)
$MatchesTarget = ($Actions.Count -eq 1 -and
    [string]$Actions[0].Execute -ieq '{_ps_quote(target.execute)}' -and
    [string]$Actions[0].Arguments -ceq '{_ps_quote(target.arguments)}' -and
    [string]$Actions[0].WorkingDirectory -ieq '{_ps_quote(target.working_directory)}' -and
    (Test-Path -LiteralPath '{_ps_quote(target.execute)}' -PathType Leaf) -and
    (Test-Path -LiteralPath '{_ps_quote(target.working_directory)}' -PathType Container))
"""


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
    """后台刷新任务计划状态，避免托盘菜单打开时同步执行 PowerShell。"""
    _set_cached_status(STATUS_CHECKING)

    def _worker() -> None:
        try:
            enabled, reason = _query_autostart_enabled()
            if enabled is None:
                _set_cached_status(STATUS_FAILED, reason)
            elif reason.strip().lower() == STATUS_OUTDATED:
                _set_cached_status(STATUS_OUTDATED)
            else:
                _set_cached_status(STATUS_ENABLED if enabled else STATUS_DISABLED)
        except Exception as exc:
            logger.exception('刷新自启动状态失败')
            _set_cached_status(STATUS_FAILED, str(exc))
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


def enable_autostart() -> tuple[bool, str]:
    """创建或覆盖开机自启动任务。需要管理员权限。"""
    target = build_launch_target()
    action_argument = ''
    if target.arguments:
        action_argument = (
            f"\n$ActionParams.Argument = '{_ps_quote(target.arguments)}'"
        )
    command = f"""
$TaskName = '{TASK_NAME}'
$ActionParams = @{{
    Execute = '{_ps_quote(target.execute)}'
    WorkingDirectory = '{_ps_quote(target.working_directory)}'
}}{action_argument}
$Action = New-ScheduledTaskAction @ActionParams
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)
$Principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -RunLevel Highest -LogonType Interactive
Register-ScheduledTask -TaskName $TaskName -TaskPath '\\' -Force -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Description 'WorkPal 工作助手 开机自启动' -ErrorAction Stop | Out-Null
$Registered = Get-ScheduledTask -TaskName $TaskName -TaskPath '\\' -ErrorAction Stop
{_target_check_command('$Registered', target)}
if (-not $MatchesTarget -or -not $Registered.Settings.Enabled -or [System.Xml.XmlConvert]::ToTimeSpan($Registered.Settings.ExecutionTimeLimit) -ne [TimeSpan]::Zero) {{
    throw '任务注册后的启动路径、状态或运行时限不正确'
}}
"""
    success, output = _run_powershell(command)
    if not success:
        logger.error('启用自启动失败: %s', output)
        _set_cached_status(STATUS_FAILED, output)
    else:
        _set_cached_status(STATUS_ENABLED)
    return success, output


def disable_autostart() -> tuple[bool, str]:
    """删除开机自启动任务。需要管理员权限。"""
    command = f"""
$TaskName = '{TASK_NAME}'
$Task = Get-ScheduledTask -TaskPath '\\' -ErrorAction Stop | Where-Object {{ $_.TaskName -eq $TaskName }}
if ($null -ne $Task) {{
    Unregister-ScheduledTask -TaskName $TaskName -TaskPath '\\' -Confirm:$false -ErrorAction Stop
}}
if (Get-ScheduledTask -TaskPath '\\' -ErrorAction Stop | Where-Object {{ $_.TaskName -eq $TaskName }}) {{
    throw '任务删除后仍存在'
}}
"""
    success, output = _run_powershell(command)
    if not success:
        logger.error('禁用自启动失败: %s', output)
        _set_cached_status(STATUS_FAILED, output)
    else:
        _set_cached_status(STATUS_DISABLED)
    return success, output


def _run_powershell(command: str) -> tuple[bool, str]:
    command = ("$ErrorActionPreference = 'Stop'\ntry {\n" + command +
               "\n} catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }\n")
    startupinfo = None
    if hasattr(subprocess, 'STARTUPINFO'):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    try:
        completed = subprocess.run(
            [
                'powershell.exe',
                '-NoProfile',
                '-ExecutionPolicy',
                'Bypass',
                '-Command',
                command,
            ],
            capture_output=True,
            text=True,
            startupinfo=startupinfo,
            timeout=30,
        )
    except Exception as exc:
        return False, str(exc)

    output = '\n'.join(
        part.strip() for part in (completed.stdout, completed.stderr) if part.strip()
    )
    return completed.returncode == 0, output


def _ps_quote(value: str) -> str:
    return value.replace("'", "''")
