"""供两个 .spec 共用：用 workpal.__version__ 生成 exe 的 Windows 版本资源。"""

import re
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable,
    VarFileInfo, VarStruct, VSVersionInfo,
)


def read_version(project_root) -> str:
    text = (Path(project_root) / 'workpal' / '__init__.py').read_text(encoding='utf-8')
    return re.search(r"^__version__ = '([0-9.]+)'$", text, re.M)[1]


def version_info(project_root) -> VSVersionInfo:
    version = read_version(project_root)
    numbers = tuple(int(part) for part in version.split('.'))
    numbers = (numbers + (0, 0, 0, 0))[:4]
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
        kids=[
            StringFileInfo([StringTable('080404B0', [
                StringStruct('ProductName', 'WorkPal 工作助手'),
                StringStruct('FileDescription', 'WorkPal 工作助手'),
                StringStruct('FileVersion', version),
                StringStruct('ProductVersion', version),
                StringStruct('OriginalFilename', 'WorkPal.exe'),
                StringStruct('InternalName', 'WorkPal'),
            ])]),
            VarFileInfo([VarStruct('Translation', [0x0804, 1200])]),
        ],
    )
