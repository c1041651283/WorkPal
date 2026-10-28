param(
    [ValidateSet('folder', 'onefile')]
    [string]$Mode = 'folder',
    [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$buildId = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
$distRoot = Join-Path $projectRoot "dist\$Mode-$buildId"
$workRoot = Join-Path $projectRoot "build\$Mode-$buildId"
$spec = if ($Mode -eq 'folder') { 'WorkPal.spec' } else { 'WorkPal_onefile.spec' }

Push-Location -LiteralPath $projectRoot
try {
    # 每次只写新目录；旧程序、运行中的进程和私人配置保持不变。
    New-Item -ItemType Directory -Path $distRoot -ErrorAction Stop | Out-Null
    Write-Host "本次输出目录: $distRoot"
    & $Python 'scripts\gen_icons.py'
    if ($LASTEXITCODE -ne 0) { throw '图标生成失败；旧包和配置未改变' }
    & $Python -m PyInstaller $spec --noconfirm --distpath $distRoot --workpath $workRoot
    if ($LASTEXITCODE -ne 0) { throw '打包失败；旧包和配置未改变' }
    $outputDir = if ($Mode -eq 'folder') { Join-Path $distRoot 'WorkPal' } else { $distRoot }
    if (-not (Test-Path -LiteralPath (Join-Path $outputDir 'WorkPal.exe'))) {
        throw '没有生成 WorkPal.exe；旧包和配置未改变'
    }
    Copy-Item -LiteralPath (Join-Path $projectRoot 'network_config.ini.example') `
        -Destination (Join-Path $outputDir 'network_config.ini.example') -ErrorAction Stop
    Write-Host "打包完成: $outputDir"
    Write-Host '分发包仅包含模板；配置保存在 %LOCALAPPDATA%\WorkPal\network_config.ini，新 EXE 直接沿用。'
} catch {
    Write-Error -Message $_ -ErrorAction Continue
    exit 1
} finally {
    Pop-Location
}
exit 0
