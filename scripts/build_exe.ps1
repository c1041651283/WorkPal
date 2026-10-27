# 构建到独立目录，保留旧程序和用户配置。
param([string]$Python = 'python')
& "$PSScriptRoot\build_package.ps1" -Mode 'folder' -Python $Python
exit $LASTEXITCODE
