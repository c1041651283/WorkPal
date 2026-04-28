# scripts/enable_autostart.ps1
# 启用 WorkPal 开机自启动（使用 Windows 任务计划程序）
# 注意: 需要管理员权限

#Requires -RunAsAdministrator

$TaskName = 'WorkPal_AutoStart'
$ExePath  = Join-Path $PSScriptRoot '..\dist\WorkPal\WorkPal.exe' | Resolve-Path -ErrorAction SilentlyContinue

if (-not $ExePath) {
    $ExePath = Join-Path (Get-Location) 'dist\WorkPal\WorkPal.exe'
    Write-Host "[警告] 未找到 dist\WorkPal\WorkPal.exe，将使用路径: $ExePath" -ForegroundColor Yellow
    Write-Host '        请先运行 scripts\build_exe.bat 完成打包' -ForegroundColor Yellow
}

$Action  = New-ScheduledTaskAction -Execute $ExePath
$Trigger = New-ScheduledTaskTrigger -AtLogOn

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

$Principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -RunLevel Highest `
    -LogonType Interactive

# 如果任务已存在则先删除
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "[提示] 已删除旧任务: $TaskName" -ForegroundColor Yellow
}

Register-ScheduledTask `
    -TaskName  $TaskName `
    -Action    $Action `
    -Trigger   $Trigger `
    -Settings  $Settings `
    -Principal $Principal `
    -Description 'WorkPal 工作助手 开机自启动'

Write-Host "[成功] 已创建自启动任务: $TaskName" -ForegroundColor Green
Write-Host "       程序路径: $ExePath" -ForegroundColor Cyan
