# WorkPal_onefile.spec — 单文件模式打包（便于分发）
# 用法: pyinstaller WorkPal_onefile.spec
# 注意: 单文件模式启动较慢（需解压临时目录），但只有一个 exe 文件

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets/icon_*.ico', 'assets'),
        ('network_config.ini.example', '.'),
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
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='WorkPal',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon_default.ico',
    uac_admin=True,
)
