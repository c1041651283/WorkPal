"""Qt 界面：卡片文字、面板按钮、通知卡片和跨线程信号；使用 offscreen 平台，不创建真实托盘。"""

import threading
from dataclasses import replace
from unittest.mock import patch

import pytest
import shiboken6
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest

from workpal import tray
from workpal.tray import TrayState
from workpal.ui import panel as panel_module, theme, toast as toast_module
from workpal.ui.panel import Panel, guard_summary, network_summary
from tests.fake_view import FakeView

BASE = TrayState(mode='ethernet', switching=False, switch_target=None, keep_alive=False,
                 guard_active=True, guard_status='守护中 · 公司网络已就绪 · 固定代理正常',
                 last_checked='16:30:12', interval=60, autostart='enabled')


# ---------------------------------------------------------------- 卡片文字


@pytest.mark.parametrize('changes,expected', [
    ({'mode': 'wifi'}, ('accent', 'wifi', 'WiFi', '点击切换到有线网络')),
    ({'mode': 'ethernet'}, ('success', 'ethernet', '有线', '点击切换到 WiFi')),
    ({'mode': 'unknown'}, ('neutral', 'unknown', '未识别', '选择要切换到的网络')),
    ({'switching': True, 'switch_target': 'wifi'}, ('warning', 'switching', '切换中', '正在切换到WiFi…')),
])
def test_network_card_text(changes, expected):
    assert network_summary(replace(BASE, **changes)) == expected


@pytest.mark.parametrize('changes,expected', [
    ({}, ('accent', 'shield_ok', '守护中', '固定代理正常 · 16:30')),
    ({'guard_active': False, 'guard_status': '已暂停 · 保留当前代理', 'last_checked': ''},
     ('neutral', 'shield', '已暂停', '保留当前代理')),
    ({'guard_active': False, 'guard_status': '脚本代理开启 · 手动代理关闭 · 守护未开启', 'last_checked': ''},
     ('neutral', 'shield', '未开启', '当前使用脚本代理')),
    ({'guard_active': False, 'guard_status': '未开启（需手动开启）', 'last_checked': ''},
     ('neutral', 'shield', '未开启', '用下方开关开启守护')),
    ({'guard_active': False, 'guard_status': '守护已停止：未找到 FortiClient.exe'},
     ('error', 'shield_error', '已停止', '未找到 FortiClient.exe')),
    ({'guard_active': False, 'guard_status': '单次检查完成 · 公司网络已就绪 · 固定代理正常'},
     ('neutral', 'shield', '检查完成', '固定代理正常 · 16:30')),
])
def test_guard_card_text(changes, expected):
    assert guard_summary(replace(BASE, **changes)) == expected


# ---------------------------------------------------------------- 面板


@pytest.fixture
def shown_panel(qapp):
    view = FakeView()
    panel = Panel(view)
    panel.popup(QRect(1800, 1050, 24, 24), BASE)
    qapp.processEvents()
    yield panel, view
    panel.hide()
    panel.deleteLater()


def _click(widget):
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=widget.rect().center())


def test_panel_reflects_state(shown_panel):
    panel, _ = shown_panel
    assert panel.network_card.title.text() == '有线'
    assert panel.guard_card.title.text() == '守护中'
    assert panel.guard_switch.isChecked() and not panel.keep_alive_switch.isChecked()
    assert not panel.wifi_chip.isVisibleTo(panel) and not panel.ethernet_chip.isVisibleTo(panel)
    panel.update_state(replace(BASE, mode='unknown', autostart='outdated'))
    assert panel.wifi_chip.isVisibleTo(panel) and panel.ethernet_chip.isVisibleTo(panel)
    # 设置页未显示，只检查控件自身的隐藏状态。
    assert not panel.autostart_fix.isHidden() and panel.autostart_switch.isHidden()


def test_network_card_switches_and_closes_panel(shown_panel):
    panel, view = shown_panel
    with patch.object(tray, 'switch_network') as switch:
        _click(panel.network_card)
    switch.assert_called_once_with(view)
    assert not panel.isVisible()


def test_unknown_network_chips_pick_target(shown_panel):
    panel, view = shown_panel
    panel.update_state(replace(BASE, mode='unknown'))
    with patch.object(tray, 'switch_network') as switch:
        _click(panel.ethernet_chip)
    switch.assert_called_once_with(view, 'ethernet')


def test_switching_card_is_not_clickable(shown_panel):
    panel, _ = shown_panel
    panel.update_state(replace(BASE, switching=True, switch_target='wifi'))
    with patch.object(tray, 'switch_network') as switch:
        _click(panel.network_card)
    switch.assert_not_called()


def test_toggles_keep_panel_open(shown_panel):
    panel, view = shown_panel
    with patch.object(tray, 'toggle_keep_alive') as keep_alive, patch.object(tray, 'stop_guard') as stop:
        _click(panel.keep_alive_row)
        _click(panel.guard_switch)
    keep_alive.assert_called_once_with(view)
    stop.assert_called_once_with(view)  # 守护原为开启，点击即暂停
    assert panel.isVisible()


def test_guard_switch_starts_guard_when_off(shown_panel):
    panel, view = shown_panel
    panel.update_state(replace(BASE, guard_active=False))
    with patch.object(tray, 'start_guard') as start:
        _click(panel.guard_row)
    start.assert_called_once_with(view)


@pytest.mark.parametrize('row,action', [
    ('check_row', 'check_now'), ('home_row', 'connect_home'), ('script_row', 'use_script'),
    ('log_button', 'open_logs'), ('quit_button', 'quit_app'),
])
def test_action_rows_call_controller(shown_panel, row, action):
    panel, view = shown_panel
    with patch.object(tray, action) as called:
        _click(getattr(panel, row))
    called.assert_called_once_with(view)
    assert not panel.isVisible()


def test_settings_page(shown_panel):
    panel, view = shown_panel
    main_height = panel.height()
    _click(panel.settings_button)
    assert panel.pages.currentIndex() == 1
    assert panel.height() < main_height  # 设置页按自身内容计算高度
    with patch.object(tray, 'set_interval') as interval:
        _click(panel.interval.buttons[300])
    interval.assert_called_once_with(view, 300)
    with patch.object(tray, 'edit_config') as edit:
        _click(panel.config_row)
    edit.assert_called_once_with(view)
    panel.popup(None, BASE)
    assert panel.pages.currentIndex() == 0  # 再次打开回到主页
    _click(panel.settings_button)
    _click(panel.back_button)
    assert panel.pages.currentIndex() == 0


def test_escape_closes_panel(shown_panel):
    panel, _ = shown_panel
    QTest.keyClick(panel, Qt.Key.Key_Escape)
    assert not panel.isVisible()


def test_panel_opens_above_bottom_taskbar_inside_screen(qapp, shown_panel):
    panel, _ = shown_panel
    area = qapp.primaryScreen().availableGeometry()
    point = panel._position(QRect(area.right() - 30, area.bottom() + 10, 24, 24))
    gap = panel_module.SCREEN_GAP
    # 与 Windows 11 浮出面板一样离屏幕边缘（任务栏）留出间距
    assert point.x() + panel.width() - 1 == area.right() - gap
    assert point.y() + panel.height() - 1 == area.bottom() - gap
    assert point.y() >= area.top()


@pytest.mark.parametrize('dark', [False, True])
def test_panel_applies_both_palettes(qapp, dark):
    panel = Panel(FakeView())
    panel.apply_palette(theme.DARK if dark else theme.LIGHT)
    panel.update_state(BASE)
    assert theme.DARK.bg in panel.styleSheet() if dark else theme.LIGHT.bg in panel.styleSheet()
    assert not panel.grab().isNull()


# ---------------------------------------------------------------- 通知卡片


@pytest.fixture
def toasts(qapp):
    manager = toast_module.ToastManager()
    yield manager
    for card in list(manager.toasts):
        card.hide()
        card.deleteLater()


def test_same_key_updates_one_card(toasts):
    first = toasts.show('正在切换到有线网络', '', 'progress', 'network')
    second = toasts.show('已切换到有线网络', '', 'success', 'network')
    assert first is second and len(toasts.toasts) == 1
    assert second.title.text() == '已切换到有线网络'
    assert second.timer.interval() == toast_module.DURATIONS['success']


def test_errors_stay_longer_and_cards_stack(toasts, qapp):
    a = toasts.show('A', level='info')
    b = toasts.show('B', 'detail', level='error')
    assert b.timer.interval() > a.timer.interval()
    targets = toasts.targets()  # 卡片滑动到这些位置
    assert targets[b].y() > targets[a].y()  # 新卡片在下面，旧卡片向上让位
    assert targets[b].y() - (targets[a].y() + a.height()) == toast_module.SPACING
    area = qapp.primaryScreen().availableGeometry()
    assert targets[b].x() + b.width() - 1 == area.right() - toast_module.MARGIN
    assert targets[b].y() + b.height() - 1 == area.bottom() - toast_module.MARGIN


def test_at_most_three_cards(toasts):
    cards = [toasts.show(str(i)) for i in range(4)]
    assert cards[0]._closing
    assert [card for card in toasts.toasts if not card._closing] == cards[1:]


def test_click_dismisses_card(toasts, qapp):
    card = toasts.show('A')
    QTest.mouseClick(card, Qt.MouseButton.LeftButton)
    assert card._closing
    assert card.isVisible()  # 先淡出滑走，动画结束后才隐藏
    QTest.qWait(toast_module.EXIT_MS + 200)
    assert not shiboken6.isValid(card)  # 动画结束后已隐藏并释放


def test_cards_fade_in(toasts, qapp):
    card = toasts.show('A')
    assert card.windowOpacity() < 1.0
    QTest.qWait(toast_module.ENTER_MS + 200)
    assert card.windowOpacity() == 1.0


def test_open_panel_holds_toasts(toasts, qapp):
    card = toasts.show('A', key='a')
    toasts.set_suspended(True)
    assert card._held and not card.timer.isActive()
    later = toasts.show('B', key='b')  # 面板打开期间到达的通知先不显示，也不计时
    assert later._held and not later.isVisible() and not later.timer.isActive()
    QTest.qWait(toast_module.EXIT_MS + 200)
    assert not card.isVisible()
    toasts.set_suspended(False)
    assert card.isVisible() and later.isVisible()
    assert card.timer.isActive() and later.timer.remainingTime() > toast_module.DURATIONS['info'] - 1000


def test_panel_reports_visibility(shown_panel):
    panel, _ = shown_panel
    seen = []
    panel.visibility_changed.connect(seen.append)
    panel.hide()
    panel.popup(None, BASE)
    assert seen == [False, True]


# ---------------------------------------------------------------- 跨线程


def test_view_delivers_background_calls_on_ui_thread(qapp):
    from workpal.ui.app import QtView
    view = QtView()
    received = []
    view.notify_requested.connect(lambda *args: received.append((args, threading.current_thread())))
    worker = threading.Thread(target=lambda: view.notify('标题', '内容', level='error', key='k'))
    worker.start()
    worker.join()
    for _ in range(20):
        qapp.processEvents()
        if received:
            break
    assert received[0][0] == ('标题', '内容', 'error', 'k')
    assert received[0][1] is threading.main_thread()


def test_tray_refresh_updates_icon_and_tooltip(qapp, monkeypatch):
    from workpal.ui import app as app_module
    tray_app = app_module.TrayApp(qapp)
    monkeypatch.setattr(tray, 'current_state', lambda: replace(BASE, keep_alive=True))
    tray_app.refresh()
    assert tray_app._icon_key == ('ethernet', True)
    assert '网络：有线' in tray_app.tray.toolTip()
    tray_app.timer.stop()
    tray_app.panel.deleteLater()
