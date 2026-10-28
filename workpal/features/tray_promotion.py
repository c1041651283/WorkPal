"""Windows 11 默认把新托盘图标收进隐藏区；首次出现时改为直接显示在任务栏。

Explorer 为每个程序路径登记一项 HKCU\\Control Panel\\NotifyIconSettings\\<编号>，
“设置 → 任务栏 → 其他系统托盘图标”中的开关就是其中的 IsPromoted 值。
只在 IsPromoted 尚未设置时写入 1；用户之后自己把图标拖回隐藏区（写入 0）不会被覆盖。
Windows 10 没有这个键，直接跳过。
"""

from __future__ import annotations

import logging
import os
import threading
import winreg

logger = logging.getLogger(__name__)

_KEY = r'Control Panel\NotifyIconSettings'

# ExecutablePath 中常见的已知文件夹 GUID 前缀。
_KNOWN_FOLDERS = {
    '{6D809377-6AF0-444B-8957-A3773F02200E}': lambda: os.environ.get(
        'ProgramW6432', os.environ.get('ProgramFiles', r'C:\Program Files')),
    '{7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FA8E}': lambda: os.environ.get(
        'ProgramFiles(x86)', r'C:\Program Files (x86)'),
    '{F38BF404-1D43-42F2-9305-67DE0B28FC23}': lambda: os.environ.get('SystemRoot', r'C:\Windows'),
    '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}': lambda: os.path.join(
        os.environ.get('SystemRoot', r'C:\Windows'), 'System32'),
}


def _normalize(path: str) -> str:
    head, sep, rest = path.partition('\\')
    folder = _KNOWN_FOLDERS.get(head.upper())
    if folder and sep:
        path = os.path.join(folder(), rest)
    return os.path.normcase(os.path.abspath(path))


def _entries():
    """逐项返回 (子键名, ExecutablePath, InitialTooltip, IsPromoted 或 None)。

    没有 NotifyIconSettings（如 Windows 10）时抛出 FileNotFoundError。
    """
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY) as root:
        index = 0
        while True:
            try:
                name = winreg.EnumKey(root, index)
            except OSError:
                return
            index += 1
            with winreg.OpenKey(root, name) as entry:
                values = {}
                for value in ('ExecutablePath', 'InitialTooltip', 'IsPromoted'):
                    try:
                        values[value] = winreg.QueryValueEx(entry, value)[0]
                    except FileNotFoundError:
                        values[value] = None
            yield name, values['ExecutablePath'], values['InitialTooltip'], values['IsPromoted']


def _set_promoted(name: str) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, f'{_KEY}\\{name}', 0, winreg.KEY_SET_VALUE) as entry:
        winreg.SetValueEx(entry, 'IsPromoted', 0, winreg.REG_DWORD, 1)


def promote(executable: str, tooltip: str) -> bool:
    """把本程序的托盘图标设为直接显示；Explorer 已登记该图标（或系统不支持）时返回 True。

    同一个 python.exe 可能运行多个托盘程序，因此同时比对图标首次登记时的提示文字。
    """
    target = _normalize(executable)
    try:
        found = False
        for name, path, initial_tooltip, promoted in _entries():
            if not path or initial_tooltip != tooltip or _normalize(str(path)) != target:
                continue
            found = True
            if promoted is None:
                _set_promoted(name)
                logger.info('托盘图标已设为直接显示在任务栏：%s', path)
        return found
    except FileNotFoundError:
        return True


def promote_when_registered(executable: str, tooltip: str, *, attempts: int = 10,
                            delay: float = 3.0, stop: threading.Event | None = None) -> None:
    """图标显示后 Explorer 才登记，稍等片刻再查；失败只记日志，不影响托盘。"""
    stop = stop or threading.Event()
    for _ in range(attempts):
        try:
            if promote(executable, tooltip):
                return
        except OSError:
            logger.exception('设置托盘图标直接显示失败')
            return
        if stop.wait(delay):
            return
    logger.info('Explorer 尚未登记 WorkPal 托盘图标，本次未设置直接显示')
