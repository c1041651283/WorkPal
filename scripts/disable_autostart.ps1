# scripts/disable_autostart.ps1
# 禁用 WorkPal 开机自启动（删除任务计划程序中的任务）
# 注意: 需要管理员权限

#Requires -RunAsAdministrator

$ErrorActionPreference = 'Stop'
$TaskName = 'WorkPal_AutoStart'

if (Get-ScheduledTask -TaskPath '\' -ErrorAction Stop | Where-Object { $_.TaskName -eq $TaskName }) {
    Unregister-ScheduledTask -TaskName $TaskName -TaskPath '\' -Confirm:$false -ErrorAction Stop
    if (Get-ScheduledTask -TaskPath '\' -ErrorAction Stop | Where-Object { $_.TaskName -eq $TaskName }) {
        throw '任务删除后仍存在'
    }
    Write-Host "[成功] 已删除自启动任务: $TaskName" -ForegroundColor Green
} else {
    Write-Host "[提示] 未找到自启动任务: $TaskName（可能从未启用）" -ForegroundColor Yellow
}
