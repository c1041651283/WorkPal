# scripts/build_exe.ps1 — 文件夹模式打包脚本
# 用法: .\scripts\build_exe.ps1  (在项目根目录下运行)

$ErrorActionPreference = 'Stop'

Write-Host '============================================' -ForegroundColor Cyan
Write-Host ' WorkPal 打包工具 (文件夹模式)' -ForegroundColor Cyan
Write-Host '============================================' -ForegroundColor Cyan
Write-Host ''

# 检查是否在项目根目录
if (-not (Test-Path 'main.py')) {
    Write-Host '[错误] 请在项目根目录下运行此脚本' -ForegroundColor Red
    exit 1
}

# 生成图标 (如果 assets/ 中不存在)
if (-not (Test-Path 'assets\icon_default.ico')) {
    Write-Host '[提示] 正在生成图标...' -ForegroundColor Yellow
    python scripts\gen_icons.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host '[错误] 图标生成失败，请检查 Pillow 是否已安装' -ForegroundColor Red
        exit 1
    }
}

# 运行 PyInstaller
Write-Host '[提示] 开始打包 (文件夹模式)...' -ForegroundColor Green
python -m PyInstaller WorkPal.spec --noconfirm
if ($LASTEXITCODE -ne 0) {
    Write-Host '[错误] 打包失败，请查看上方错误信息' -ForegroundColor Red
    exit 1
}

# 复制配置模板到 dist\WorkPal\
Copy-Item -Path 'network_config.ini.example' -Destination 'dist\WorkPal\network_config.ini.example' -Force
if (-not (Test-Path 'dist\WorkPal\network_config.ini')) {
    Write-Host ''
    Write-Host '[提示] 未检测到 network_config.ini，已复制模板文件' -ForegroundColor Yellow
    Write-Host '       请编辑 dist\WorkPal\network_config.ini.example 并重命名为 network_config.ini' -ForegroundColor Yellow
}

Write-Host ''
Write-Host '============================================' -ForegroundColor Cyan
Write-Host " 打包完成！输出目录: dist\WorkPal\" -ForegroundColor Green
Write-Host ' 以管理员身份运行: dist\WorkPal\WorkPal.exe' -ForegroundColor Green
Write-Host ' (网络适配器操作需要管理员权限)' -ForegroundColor Yellow
Write-Host '============================================' -ForegroundColor Cyan
