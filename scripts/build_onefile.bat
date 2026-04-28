@echo off
chcp 65001 >nul
echo ============================================
echo  WorkPal 打包工具 (单文件模式)
echo ============================================
echo.

if not exist "main.py" (
    echo [错误] 请在项目根目录下运行此脚本
    pause
    exit /b 1
)

if not exist "assets\icon_default.ico" (
    echo [提示] 正在生成图标...
    python scripts\gen_icons.py
    if errorlevel 1 (
        echo [错误] 图标生成失败
        pause
        exit /b 1
    )
)

echo [提示] 开始打包 (单文件模式)...
python -m PyInstaller WorkPal_onefile.spec --noconfirm

if errorlevel 1 (
    echo [错误] 打包失败，请查看上方错误信息
    pause
    exit /b 1
)

echo.
echo ============================================
echo  打包完成！输出文件: dist\WorkPal.exe
echo  注意: 单文件模式启动较慢，首次运行需解压
echo  以管理员身份运行 dist\WorkPal.exe
echo  运行 exe 后将 network_config.ini 放在同目录
echo ============================================
pause
