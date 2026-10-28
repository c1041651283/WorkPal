"""点击托盘图标弹出的菜单面板：状态卡片、开关、常用操作，以及“设置”二级页。"""

from __future__ import annotations

import time

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from workpal import tray
from workpal.tray import TrayState
from workpal.ui import icons, native, theme
from workpal.ui.theme import Palette
from workpal.ui.widgets import Card, Row, Segmented, ToggleSwitch, fitted_height

PANEL_WIDTH = 336
FRAME_PADDING = 12
CARD_GAP = 8
# 卡片固定宽度，换行文字才能算准高度
CARD_WIDTH = (PANEL_WIDTH - 2 * FRAME_PADDING - CARD_GAP) // 2
# 与 Windows 11 浮出面板一致：离任务栏 12 像素，弹出时向上滑入
SCREEN_GAP = 12
FOOTER_ICON = 18
SLIDE_DISTANCE = 12


def network_summary(state: TrayState) -> tuple[str, str, str, str]:
    """网络卡片：(tone, glyph, 标题, 说明)。"""
    if state.switching:
        return 'warning', 'switching', '切换中', f'正在切换到{tray.target_name(state.switch_target)}…'
    if state.mode == 'wifi':
        return 'accent', 'wifi', 'WiFi', '点击切换到有线网络'
    if state.mode == 'ethernet':
        return 'success', 'ethernet', '有线', '点击切换到 WiFi'
    return 'neutral', 'unknown', '未识别', '选择要切换到的网络'


def guard_summary(state: TrayState) -> tuple[str, str, str, str]:
    """代理卡片：(tone, glyph, 标题, 说明)。状态文字来自代理守护，形如“守护中 · 公司网络已就绪 · 固定代理正常”。"""
    parts = [part.strip() for part in state.guard_status.split('·') if part.strip()]
    checked = state.last_checked[:5]
    if tray.is_error_message(state.guard_status):
        title = '已停止' if not state.guard_active else parts[0]
        detail = state.guard_status.split('：', 1)[-1] if '：' in state.guard_status else parts[-1]
        return 'error', 'shield_error', title, detail
    if state.guard_active:
        detail = parts[-1] if len(parts) > 1 else '正在检查'
        if checked:
            detail = f'{detail} · {checked}'
        return 'accent', 'shield_ok', parts[0] if parts else '守护中', detail
    if parts and parts[0].startswith('已暂停'):
        return 'neutral', 'shield', '已暂停', '保留当前代理'
    if parts and parts[0].startswith('单次检查完成'):
        detail = parts[-1] if len(parts) > 1 else ''
        return 'neutral', 'shield', '检查完成', f'{detail} · {checked}' if checked else detail
    if parts and parts[0].startswith('脚本代理'):
        return 'neutral', 'shield', '未开启', '当前使用脚本代理'
    if not parts or parts[0].startswith('未开启'):
        return 'neutral', 'shield', '未开启', '用下方开关开启守护'
    return 'neutral', 'shield', '未开启', parts[0]


def _shade(color: str, dark: bool, amount: int) -> str:
    """把颜色调暗（浅色主题）或调亮（深色主题）一点，用于描边和悬停。"""
    qcolor = QColor(color)
    return (qcolor.lighter(100 + amount) if dark else qcolor.darker(100 + amount)).name()


def stylesheet(p: Palette) -> str:
    cards = []
    for tone in ('accent', 'success', 'warning', 'error', 'neutral'):
        background = p.tone(tone)[1]
        border = p.card_border if tone == 'neutral' else _shade(background, p.dark, 6)
        hover = _shade(background, p.dark, 4)
        cards.append(f'Card[tone="{tone}"] {{ background: {background}; border: 1px solid {border};'
                     f' border-radius: 8px; }}'
                     f'Card[tone="{tone}"][state="hover"] {{ background: {hover}; }}')
    return f'''
    #panel {{ background: {p.bg}; }}
    QLabel {{ color: {p.text}; background: transparent; }}
    QLabel[role="title"] {{ font-weight: 600; }}
    QLabel[role="muted"] {{ color: {p.muted}; font-size: 12px; }}
    QLabel[role="section"] {{ color: {p.text2}; font-size: 12px; }}
    QLabel[role="cardTitle"] {{ font-size: 15px; font-weight: 600; }}
    QLabel[role="cardText"] {{ font-size: 12px; }}
    Row {{ border-radius: 4px; background: transparent; }}
    Row[state="hover"] {{ background: {p.hover}; }}
    Row[state="pressed"] {{ background: {p.pressed}; }}
    {''.join(cards)}
    #divider {{ background: {p.divider}; }}
    QPushButton[role="footer"], QPushButton[role="danger"] {{
        border: none; border-radius: 4px; min-height: 36px; padding: 0 4px; background: transparent;
    }}
    QPushButton[role="footer"] {{ color: {p.text}; }}
    QPushButton[role="footer"]:hover {{ background: {p.hover}; }}
    QPushButton[role="footer"]:pressed {{ background: {p.pressed}; }}
    QPushButton[role="danger"] {{ color: {p.error}; }}
    QPushButton[role="danger"]:hover {{ background: {p.error_bg}; }}
    QPushButton[role="chip"] {{
        border: 1px solid {p.card_border}; border-radius: 4px; min-height: 26px; padding: 0 12px;
        color: {p.text}; background: {p.card}; font-size: 12px;
    }}
    QPushButton[role="chip"]:hover {{ background: {p.hover}; }}
    QPushButton[role="chip"]:pressed {{ background: {p.pressed}; }}
    QPushButton[role="back"] {{
        border: none; border-radius: 4px; min-height: 32px; padding: 0 8px; color: {p.text};
        background: transparent; font-weight: 600; text-align: left;
    }}
    QPushButton[role="back"]:hover {{ background: {p.hover}; }}
    Segmented {{ background: {p.neutral_bg}; border-radius: 6px; }}
    QPushButton[role="segment"] {{
        border: 1px solid transparent; border-radius: 4px; min-height: 28px; color: {p.text2};
        background: transparent;
    }}
    QPushButton[role="segment"]:hover {{ color: {p.text}; }}
    QPushButton[role="segment"]:checked {{
        background: {p.card}; border: 1px solid {p.card_border}; color: {p.accent}; font-weight: 600;
    }}
    '''


class Panel(QWidget):
    # 显示/隐藏时发出，托盘程序据此暂停通知卡片，避免卡片遮挡面板
    visibility_changed = Signal(bool)

    def __init__(self, view):
        # 不透明窗口：文字用 ClearType 渲染；圆角、描边和阴影交给 Windows 11 绘制。
        super().__init__(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.view = view
        self.palette_: Palette = theme.current()
        self.state: TrayState | None = None
        self.last_hidden = 0.0
        self._anchor: QRect | None = None
        self.setFixedWidth(PANEL_WIDTH)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.frame = QFrame(objectName='panel')
        outer.addWidget(self.frame)
        frame_layout = QVBoxLayout(self.frame)
        frame_layout.setContentsMargins(FRAME_PADDING, FRAME_PADDING + 2, FRAME_PADDING, FRAME_PADDING - 4)
        self.pages = QStackedWidget()
        frame_layout.addWidget(self.pages)
        self.pages.addWidget(self._build_main())
        self.pages.addWidget(self._build_settings())

        self.slide = QPropertyAnimation(self, b'pos', self, duration=200,
                                        easingCurve=QEasingCurve.Type.OutCubic)

    # ---------------------------------------------------------------- 构建

    def _build_main(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        header = QHBoxLayout()
        header.setContentsMargins(4, 0, 4, 10)
        title = QLabel('WorkPal')
        title.setProperty('role', 'title')
        version = QLabel(tray.VERSION)
        version.setProperty('role', 'muted')
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(version)
        layout.addLayout(header)

        cards = QHBoxLayout()
        cards.setSpacing(CARD_GAP)
        self.network_card = Card(CARD_WIDTH)
        self.network_card.clicked.connect(lambda: self._act(tray.switch_network))
        self.wifi_chip = self._chip('WiFi', lambda: self._act(tray.switch_network, 'wifi'))
        self.ethernet_chip = self._chip('有线', lambda: self._act(tray.switch_network, 'ethernet'))
        self.network_card.extra.addWidget(self.wifi_chip)
        self.network_card.extra.addWidget(self.ethernet_chip)
        self.network_card.extra.addStretch(1)
        self.guard_card = Card(CARD_WIDTH)
        cards.addWidget(self.network_card, 0, Qt.AlignmentFlag.AlignTop)
        cards.addWidget(self.guard_card, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(cards)
        layout.addSpacing(8)

        self.keep_alive_switch = ToggleSwitch()
        self.keep_alive_switch.clicked.connect(lambda: self._toggle(tray.toggle_keep_alive))
        self.keep_alive_row = Row('heart', '保持在线', self.keep_alive_switch)
        self.guard_switch = ToggleSwitch()
        self.guard_switch.clicked.connect(self._toggle_guard)
        self.guard_row = Row('shield', '代理守护', self.guard_switch)
        self.check_row = Row('refresh', '立即检查并修复')
        self.check_row.clicked.connect(lambda: self._act(tray.check_now))
        self.home_row = Row('home', '在家连接公司')
        self.home_row.clicked.connect(lambda: self._act(tray.connect_home))
        self.script_row = Row('script', '切回脚本代理')
        self.script_row.clicked.connect(lambda: self._act(tray.use_script))
        for row in (self.keep_alive_row, self.guard_row, self.check_row, self.home_row, self.script_row):
            layout.addWidget(row)

        layout.addSpacing(6)
        layout.addWidget(self._divider())
        layout.addSpacing(6)
        footer = QHBoxLayout()
        footer.setSpacing(4)
        self.settings_button = self._footer_button('settings', '设置', self._show_settings)
        self.log_button = self._footer_button('log', '日志', lambda: self._act(tray.open_logs))
        self.quit_button = self._footer_button('power', '退出', lambda: self._act(tray.quit_app),
                                               role='danger')
        for button in (self.settings_button, self.log_button, self.quit_button):
            footer.addWidget(button, 1)
        layout.addLayout(footer)
        return page

    def _build_settings(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.back_button = QPushButton('设置')
        self.back_button.setProperty('role', 'back')
        self.back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_button.clicked.connect(self._show_main)
        layout.addWidget(self.back_button)
        layout.addSpacing(6)

        section = QLabel('代理守护检查间隔')
        section.setProperty('role', 'section')
        section.setContentsMargins(4, 0, 0, 4)
        layout.addWidget(section)
        self.interval = Segmented([(seconds, f'{seconds // 60} 分钟') for seconds in tray.INTERVAL_CHOICES])
        self.interval.selected.connect(lambda seconds: tray.set_interval(self.view, seconds))
        layout.addWidget(self.interval)
        layout.addSpacing(8)

        self.autostart_switch = ToggleSwitch()
        self.autostart_switch.clicked.connect(lambda: self._toggle(tray.toggle_autostart))
        self.autostart_fix = self._chip('更新', lambda: self._toggle(tray.toggle_autostart))
        trailing = QWidget()
        trailing_layout = QHBoxLayout(trailing)
        trailing_layout.setContentsMargins(0, 0, 0, 0)
        trailing_layout.setSpacing(8)
        self.autostart_status = QLabel()
        self.autostart_status.setProperty('role', 'muted')
        trailing_layout.addWidget(self.autostart_status)
        trailing_layout.addWidget(self.autostart_fix)
        trailing_layout.addWidget(self.autostart_switch)
        self.autostart_row = Row('rocket', '开机自动启动', trailing)
        self.autostart_row.clicked.connect(lambda: self._toggle(tray.toggle_autostart))
        self.config_row = Row('edit', '编辑配置文件')
        self.config_row.clicked.connect(lambda: self._act(tray.edit_config))
        layout.addWidget(self.autostart_row)
        layout.addWidget(self.config_row)

        layout.addSpacing(6)
        layout.addWidget(self._divider())
        about = QLabel(f'{tray.APP_NAME} {tray.VERSION}\n本软件仅供个人学习使用。')
        about.setProperty('role', 'muted')
        about.setContentsMargins(4, 8, 4, 2)
        layout.addWidget(about)
        layout.addStretch(1)
        return page

    def _chip(self, text: str, action) -> QPushButton:
        button = QPushButton(text)
        button.setProperty('role', 'chip')
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(action)
        return button

    def _footer_button(self, glyph: str, text: str, action, role: str = 'footer') -> QPushButton:
        button = QPushButton(text)
        button.setProperty('role', role)
        button.setProperty('glyph', glyph)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(action)
        return button

    @staticmethod
    def _divider() -> QFrame:
        line = QFrame(objectName='divider')
        line.setFixedHeight(1)
        return line

    # ---------------------------------------------------------------- 动作

    def _act(self, action, *args) -> None:
        """普通操作：先关闭面板，结果通过通知卡片显示。"""
        self.hide()
        action(self.view, *args)

    def _toggle(self, action) -> None:
        """开关类操作：面板保持打开，便于看到结果。"""
        action(self.view)
        self.view.refresh()

    def _toggle_guard(self) -> None:
        self._toggle(tray.start_guard if self.guard_switch.isChecked() else tray.stop_guard)

    def _show_settings(self) -> None:
        self._set_page(1)

    def _show_main(self) -> None:
        self._set_page(0)

    def _set_page(self, index: int) -> None:
        """只按当前页计算高度，否则设置页会被撑到主页那么高。"""
        for i in range(self.pages.count()):
            policy = QSizePolicy.Policy.Preferred if i == index else QSizePolicy.Policy.Ignored
            self.pages.widget(i).setSizePolicy(policy, policy)
        self.pages.setCurrentIndex(index)
        self._fit()

    # ---------------------------------------------------------------- 状态与主题

    def apply_palette(self, palette: Palette) -> None:
        self.palette_ = palette
        self.setStyleSheet(stylesheet(palette))
        # 样式表在显示前才生效；立即应用，卡片才能按正确字号计算换行高度。
        self.ensurePolished()
        for child in self.findChildren(QWidget):
            child.ensurePolished()
        native.round_window(self, palette.border)
        ratio = self.devicePixelRatioF()
        for button in (self.settings_button, self.log_button, self.quit_button):
            color = palette.error if button.property('role') == 'danger' else palette.text2
            button.setIcon(icons.glyph(button.property('glyph'), color, FOOTER_ICON, ratio))
            # QPushButton 默认按 16px 绘制图标，显式设置才与 14px 文字协调
            button.setIconSize(QSize(FOOTER_ICON, FOOTER_ICON))
        self.back_button.setIcon(icons.glyph('back', palette.text, FOOTER_ICON, ratio))
        self.back_button.setIconSize(QSize(FOOTER_ICON, FOOTER_ICON))
        self.keep_alive_switch.set_colors(palette, palette.purple)
        self.guard_switch.set_colors(palette, palette.accent)
        self.autostart_switch.set_colors(palette, palette.accent)
        self.keep_alive_row.set_colors(palette, palette.purple)
        self.guard_row.set_colors(palette, palette.accent)
        for row in (self.check_row, self.home_row, self.script_row, self.autostart_row, self.config_row):
            row.set_colors(palette)
        if self.state is not None:
            self.update_state(self.state)

    def update_state(self, state: TrayState) -> None:
        self.state = state
        p = self.palette_
        tone, glyph, title, subtitle = network_summary(state)
        unknown = state.mode == 'unknown' and not state.switching
        self.network_card.set_content(p, tone, glyph, title, subtitle,
                                      clickable=not state.switching and not unknown)
        self.wifi_chip.setVisible(unknown)
        self.ethernet_chip.setVisible(unknown)
        tone, glyph, title, subtitle = guard_summary(state)
        self.guard_card.set_content(p, tone, glyph, title, subtitle, clickable=False)
        self.guard_card.setToolTip(state.guard_status)
        self.keep_alive_switch.set_checked_silently(state.keep_alive)
        self.guard_switch.set_checked_silently(state.guard_active)
        self.interval.set_value(state.interval)
        self.autostart_status.setText(tray.autostart_label(state.autostart))
        outdated = state.autostart == 'outdated'
        self.autostart_fix.setVisible(outdated)
        self.autostart_switch.setVisible(not outdated)
        self.autostart_switch.setEnabled(state.autostart in ('enabled', 'disabled'))
        self.autostart_switch.set_checked_silently(state.autostart == 'enabled')

    # ---------------------------------------------------------------- 显示

    def popup(self, anchor: QRect | None, state: TrayState) -> None:
        self._anchor = anchor
        self.apply_palette(theme.current())
        self.update_state(state)
        self._set_page(0)
        target = self.pos()
        # 从任务栏方向滑入：任务栏在下方时由下往上。
        offset = SLIDE_DISTANCE if self._opens_upward() else -SLIDE_DISTANCE
        self.move(target.x(), target.y() + offset)
        self.show()
        self.activateWindow()
        self.slide.stop()
        self.slide.setStartValue(self.pos())
        self.slide.setEndValue(target)
        self.slide.start()

    def _fit(self) -> None:
        margins = self.frame.layout().contentsMargins()
        width = PANEL_WIDTH - margins.left() - margins.right()
        content = fitted_height(self.pages.currentWidget(), width)
        self.setFixedSize(PANEL_WIDTH, content + margins.top() + margins.bottom())
        self.slide.stop()
        self.move(self._position(self._anchor))

    def _anchor_point(self, anchor: QRect | None) -> QPoint:
        return anchor.center() if anchor is not None and anchor.isValid() else QCursor.pos()

    def _opens_upward(self) -> bool:
        point = self._anchor_point(self._anchor)
        screen = QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()
        return point.y() >= screen.availableGeometry().center().y()

    def _position(self, anchor: QRect | None) -> QPoint:
        """贴着托盘图标弹出：任务栏在下方时向上展开，并保持在屏幕可用区域内。"""
        point = self._anchor_point(anchor)
        screen = QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        width, height = self.width(), self.height()
        x = point.x() - width // 2
        x = max(area.left() + SCREEN_GAP, min(x, area.right() - width - SCREEN_GAP + 1))
        if point.y() >= area.center().y():
            y = area.bottom() - height - SCREEN_GAP + 1
        else:
            y = area.top() + SCREEN_GAP
        return QPoint(x, y)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.visibility_changed.emit(True)

    def hideEvent(self, event) -> None:
        self.last_hidden = time.monotonic()
        super().hideEvent(event)
        self.visibility_changed.emit(False)
