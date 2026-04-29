# scripts/build_onefile.ps1 — 单文件模式打包脚本
# 用法: .\scripts\build_onefile.ps1  (在项目根目录下运行)

$ErrorActionPreference = 'Stop'

Write-Host '============================================' -ForegroundColor Cyan
Write-Host ' WorkPal 打包工具 (单文件模式)' -ForegroundColor Cyan
Write-Host '============================================' -ForegroundColor Cyan
Write-Host ''

if (-not (Test-Path 'main.py')) {
    Write-Host '[错误] 请在项目根目录下运行此脚本' -ForegroundColor Red
    exit 1
}

# 每次打包前重新生成图标（确保使用最新高清版本）
Write-Host '[提示] 正在生成高清图标...' -ForegroundColor Yellow
python scripts\gen_icons.py
if ($LASTEXITCODE -ne 0) {
    Write-Host '[错误] 图标生成失败，请检查依赖是否已安装: pip install svglib reportlab' -ForegroundColor Red
    exit 1
}

Write-Host '[提示] 开始打包 (单文件模式)...' -ForegroundColor Green
python -m PyInstaller WorkPal_onefile.spec --noconfirm
if ($LASTEXITCODE -ne 0) {
    Write-Host '[错误] 打包失败' -ForegroundColor Red
    exit 1
}

Write-Host ''
Write-Host '============================================' -ForegroundColor Cyan
Write-Host ' 打包完成！输出文件: dist\WorkPal.exe' -ForegroundColor Green
Write-Host ' 注意: 单文件模式启动较慢，首次运行需解压' -ForegroundColor Yellow
Write-Host ' 以管理员身份运行 dist\WorkPal.exe' -ForegroundColor Green
Write-Host ' 运行 exe 后将 network_config.ini 放在同目录' -ForegroundColor Yellow
Write-Host '============================================' -ForegroundColor Cyan
