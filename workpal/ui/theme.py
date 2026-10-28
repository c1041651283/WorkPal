"""浅色/深色配色，跟随 Windows 的应用颜色设置；颜色取自 Windows 11 的 Fluent 风格。"""

from __future__ import annotations

from dataclasses import dataclass
import winreg

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication

FONT_FAMILIES = ['Segoe UI Variable Text', 'Microsoft YaHei UI', 'Segoe UI']


@dataclass(frozen=True)
class Palette:
    dark: bool
    bg: str
    border: str
    text: str
    text2: str
    muted: str
    hover: str
    pressed: str
    divider: str
    neutral_bg: str
    accent: str
    accent_bg: str
    success: str
    success_bg: str
    warning: str
    warning_bg: str
    error: str
    error_bg: str
    purple: str
    knob_on: str
    card: str          # 中性卡片底色，比面板略亮/略深一层
    card_border: str
    stroke: str        # 关闭状态开关的描边和滑块

    def tone(self, tone: str) -> tuple[str, str]:
        """返回 (前景色, 背景色)；tone：accent/success/warning/error/neutral。"""
        return {
            'accent': (self.accent, self.accent_bg),
            'success': (self.success, self.success_bg),
            'warning': (self.warning, self.warning_bg),
            'error': (self.error, self.error_bg),
        }.get(tone, (self.text2, self.card))


# 取值参照 Windows 11 浮出面板（Flyout）和控件的配色
LIGHT = Palette(
    dark=False, bg='#f9f9f9', border='#d9d9d9', text='#1a1a1a', text2='#5c5c5c',
    muted='#8a8a8a', hover='#efefef', pressed='#e8e8e8', divider='#e5e5e5',
    neutral_bg='#f0f0f0', accent='#005fb8', accent_bg='#e6f0fa', success='#0f7b0f',
    success_bg='#e8f4e6', warning='#9d5d00', warning_bg='#fdf3dd', error='#c42b1c',
    error_bg='#fbe9e8', purple='#8a3fd1', knob_on='#ffffff', card='#ffffff',
    card_border='#e5e5e5', stroke='#767676',
)

DARK = Palette(
    dark=True, bg='#2c2c2c', border='#3f3f3f', text='#ffffff', text2='#cfcfcf',
    muted='#9a9a9a', hover='#383838', pressed='#333333', divider='#3a3a3a',
    neutral_bg='#363636', accent='#60cdff', accent_bg='#1f3447', success='#6ccb5f',
    success_bg='#253622', warning='#fce100', warning_bg='#3d3519', error='#ff99a4',
    error_bg='#442b2e', purple='#c79cf7', knob_on='#000000', card='#343434',
    card_border='#3d3d3d', stroke='#a0a0a0',
)


def _registry_prefers_dark() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
            return winreg.QueryValueEx(key, 'AppsUseLightTheme')[0] == 0
    except OSError:
        return False


def is_dark() -> bool:
    scheme = QGuiApplication.styleHints().colorScheme()
    if scheme == Qt.ColorScheme.Dark:
        return True
    if scheme == Qt.ColorScheme.Light:
        return False
    return _registry_prefers_dark()


def current() -> Palette:
    return DARK if is_dark() else LIGHT


def app_font() -> QFont:
    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    font.setPixelSize(14)
    return font
