"""调用 Windows 11 DWM，让不透明的弹出窗口获得系统原生的圆角、描边和阴影。

窗口保持不透明，文字才能使用 ClearType 渲染，与系统菜单一样清晰。
Windows 10 不支持这些属性，调用失败时保持直角，不影响使用。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging

from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)

_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWA_BORDER_COLOR = 34
_DWMWCP_ROUND = 2


def _set_attribute(widget: QWidget, attribute: int, value: int) -> bool:
    try:
        hwnd = wintypes.HWND(int(widget.winId()))
        data = wintypes.DWORD(value)
        result = ctypes.WinDLL('dwmapi').DwmSetWindowAttribute(
            hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data))
        return result == 0
    except OSError:
        logger.debug('DWM 属性设置失败', exc_info=True)
        return False


def _colorref(color: str) -> int:
    red, green, blue = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return red | green << 8 | blue << 16


def round_window(widget: QWidget, border: str) -> bool:
    """系统圆角和 1 像素描边；返回是否由系统绘制（Windows 11）。"""
    rounded = _set_attribute(widget, _DWMWA_WINDOW_CORNER_PREFERENCE, _DWMWCP_ROUND)
    if rounded:
        _set_attribute(widget, _DWMWA_BORDER_COLOR, _colorref(border))
    return rounded

