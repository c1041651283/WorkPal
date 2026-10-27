"""执行真实 PowerShell 控制流，所有任务计划命令均由内存函数替代。"""

import subprocess

import pytest

from workpal.features import autostart


STUBS = r'''
$script:Registered = $null
function New-ScheduledTaskAction {
    [CmdletBinding()] param($Execute, $WorkingDirectory, $Argument)
    [pscustomobject]@{ Execute=$Execute; Arguments=$Argument; WorkingDirectory=$WorkingDirectory }
}
function New-ScheduledTaskTrigger { [CmdletBinding()] param([switch]$AtLogOn) @{} }
function New-ScheduledTaskSettingsSet {
    [CmdletBinding()] param([switch]$AllowStartIfOnBatteries, [switch]$DontStopIfGoingOnBatteries,
        [switch]$StartWhenAvailable, [TimeSpan]$ExecutionTimeLimit)
    if ($ExecutionTimeLimit -ne [TimeSpan]::Zero) { throw 'finite execution time' }
    [pscustomobject]@{ Enabled=$true; ExecutionTimeLimit='PT0S' }
}
function New-ScheduledTaskPrincipal { [CmdletBinding()] param($UserId,$RunLevel,$LogonType) @{} }
function Register-ScheduledTask {
    [CmdletBinding()] param($TaskName,$TaskPath,[switch]$Force,$Action,$Trigger,$Settings,$Principal,$Description)
    __REGISTER__
}
function Get-ScheduledTask { [CmdletBinding()] param($TaskName,$TaskPath) $script:Registered }
function Unregister-ScheduledTask { [CmdletBinding()] param($TaskName,$TaskPath,[switch]$Confirm) $script:Registered=$null }
'''


@pytest.mark.parametrize('registration,expected', [
    ("Write-Error 'simulated registration failure'", False),
    ("$script:Registered=[pscustomobject]@{ TaskName=$TaskName; Settings=$Settings; Actions=@($Action) }", True),
    ("$script:Registered=[pscustomobject]@{ TaskName=$TaskName; Settings=[pscustomobject]@{ Enabled=$false; ExecutionTimeLimit='PT72H' }; Actions=@($Action) }", False),
    ("$Action.Execute='Z:\\missing-old-package\\WorkPal.exe'; $script:Registered=[pscustomobject]@{ TaskName=$TaskName; Settings=$Settings; Actions=@($Action) }", False),
    ('', False),
])
def test_registration_result_is_verified_with_real_powershell(monkeypatch, registration, expected):
    native_run = subprocess.run
    def run_with_stubs(args, **kwargs):
        return native_run([*args[:-1], STUBS.replace('__REGISTER__', registration) + args[-1]], **kwargs)
    monkeypatch.setattr(autostart.subprocess, 'run', run_with_stubs)
    success, reason = autostart.enable_autostart()
    assert success is expected
    assert autostart.get_cached_autostart_status() == (autostart.STATUS_ENABLED if expected else autostart.STATUS_FAILED)
    if not expected:
        assert reason


@pytest.mark.parametrize('output,expected', [('enabled', True), ('disabled', False), ('unexpected enabled text', None)])
def test_task_status_requires_exact_result(monkeypatch, output, expected):
    monkeypatch.setattr(autostart, '_run_powershell', lambda command: (True, output))
    assert autostart._query_autostart_enabled()[0] is expected
