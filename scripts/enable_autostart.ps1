# scripts/enable_autostart.ps1
# 启用 WorkPal 开机自启动（使用 Windows 任务计划程序）
# 注意: 需要管理员权限

#Requires -RunAsAdministrator

param(
    [string]$ExePath = '',
    [string]$Arguments = '',
    [string]$WorkingDirectory = ''
)

$ErrorActionPreference = 'Stop'
$TaskName = 'WorkPal_AutoStart'

if (-not $ExePath) {
    $ResolvedExePath = Join-Path $PSScriptRoot '..\dist\WorkPal\WorkPal.exe' | Resolve-Path -ErrorAction SilentlyContinue
    if ($ResolvedExePath) {
        $ExePath = [string]$ResolvedExePath
    } else {
        throw '请通过托盘启用自启动，或用 -ExePath 指定本次构建的 WorkPal.exe。'
    }
}

if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) {
    throw '指定的启动程序不存在'
}
$ExePath = (Resolve-Path -LiteralPath $ExePath).Path
if (-not $WorkingDirectory) {
    $WorkingDirectory = Split-Path -Parent ([string]$ExePath)
}

$ActionParams = @{
    Execute = $ExePath
    WorkingDirectory = $WorkingDirectory
}
if ($Arguments) {
    $ActionParams.Argument = $Arguments
}
$Action  = New-ScheduledTaskAction @ActionParams
$Trigger = New-ScheduledTaskTrigger -AtLogOn

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

$Principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -RunLevel Highest `
    -LogonType Interactive

Register-ScheduledTask `
    -TaskName  $TaskName `
    -TaskPath '\' -Force `
    -Action    $Action `
    -Trigger   $Trigger `
    -Settings  $Settings `
    -Principal $Principal `
    -Description 'WorkPal 工作助手 开机自启动' -ErrorAction Stop | Out-Null

$Registered = Get-ScheduledTask -TaskName $TaskName -TaskPath '\' -ErrorAction Stop
if (-not $Registered.Settings.Enabled -or [System.Xml.XmlConvert]::ToTimeSpan($Registered.Settings.ExecutionTimeLimit) -ne [TimeSpan]::Zero) {
    throw '任务注册后的状态或运行时限不正确'
}

Write-Host "[成功] 已创建自启动任务: $TaskName" -ForegroundColor Green
Write-Host "       程序路径: $ExePath" -ForegroundColor Cyan
