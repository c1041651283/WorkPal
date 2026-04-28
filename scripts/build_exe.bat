@echo off
chcp 65001 >nul
echo ============================================
echo  WorkPal 打包工具 (文件夹模式)
echo ============================================
echo.

:: 检查是否在项目根目录
if not exist "main.py" (
    echo [错误] 请在项目根目录下运行此脚本
    pause
    exit /b 1
)

:: 生成图标 (如果 assets/ 中不存在)
if not exist "assets\icon_default.ico" (
    echo [提示] 正在生成图标...
    python scripts\gen_icons.py
    if errorlevel 1 (
        echo [错误] 图标生成失败，请检查 Pillow 是否已安装
        pause
        exit /b 1
    )
)

:: 运行 PyInstaller
echo [提示] 开始打包 (文件夹模式)...
python -m PyInstaller WorkPal.spec --noconfirm

if errorlevel 1 (
    echo [错误] 打包失败，请查看上方错误信息
    pause
    exit /b 1
)

:: 复制配置模板到 dist\WorkPal\
copy /Y network_config.ini.example dist\WorkPal\network_config.ini.example >nul
if not exist "dist\WorkPal\network_config.ini" (
    echo.
    echo [提示] 未检测到 network_config.ini，已复制模板文件
    echo        请编辑 dist\WorkPal\network_config.ini.example 并重命名为 network_config.ini
)

echo.
echo ============================================
echo  打包完成！输出目录: dist\WorkPal\
echo  以管理员身份运行: dist\WorkPal\WorkPal.exe
echo  (网络适配器操作需要管理员权限)
echo ============================================
pause
