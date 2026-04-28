# scripts/disable_autostart.ps1
# 禁用 WorkPal 开机自启动（删除任务计划程序中的任务）
# 注意: 需要管理员权限

#Requires -RunAsAdministrator

$TaskName = 'WorkPal_AutoStart'

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "[成功] 已删除自启动任务: $TaskName" -ForegroundColor Green
} else {
    Write-Host "[提示] 未找到自启动任务: $TaskName（可能从未启用）" -ForegroundColor Yellow
}
