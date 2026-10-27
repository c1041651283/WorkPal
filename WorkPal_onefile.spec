# WorkPal_onefile.spec — 单文件模式打包（便于分发）
# 用法: scripts\build_onefile.bat（或 pyinstaller WorkPal_onefile.spec）
# 注意: 单文件模式启动较慢（需解压临时目录），但只有一个 exe 文件
# network_config.ini.example 由 scripts\build_package.ps1 复制到 exe 旁，不打进包内。

import sys
from pathlib import Path

sys.path.insert(0, str(Path(SPECPATH) / 'scripts'))
from version_resource import version_info

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets/icon_*.ico', 'assets'),
    ],
    hiddenimports=[
        'wmi',
        'pywintypes',
        'win32com',
        'win32com.client',
        'win32api',
        'win32con',
        'psutil',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='WorkPal',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX 压缩容易被公司杀毒软件误报，且启动更慢
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon_default.ico',
    version=version_info(SPECPATH),
    uac_admin=True,
)
