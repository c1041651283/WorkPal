"""退出线程、托盘图标状态与绘制；不创建真实托盘或修改网络。"""

import threading
from unittest.mock import MagicMock

import pytest

from workpal import tray
from tests.fake_view import FakeView


def test_quit_runs_in_background_and_releases_lock(monkeypatch):
    started, finish = threading.Event(), threading.Event()

    def slow_quit(view):
        started.set()
        finish.wait(5)

    monkeypatch.setattr(tray, '_quit_when_idle', slow_quit)
    tray.quit_app(FakeView())
    # 回调立即返回，界面线程不等待代理守护停止。
    assert started.wait(2)
    assert tray._switch_lock.locked()
    finish.set()
    for thread in threading.enumerate():
        if thread.name == 'quit':
            thread.join(2)
    assert not tray._switch_lock.locked()


def test_quit_failure_is_reported_and_releases_lock(monkeypatch):
    monkeypatch.setattr(tray, '_quit_when_idle', MagicMock(side_effect=RuntimeError('boom')))
    view = FakeView()
    tray._switch_lock.acquire()
    tray._quit_and_release(view)
    assert not tray._switch_lock.locked()
    assert view.last.title == '退出失败' and view.last.level == 'error'


def _state(**changes):
    values = dict(mode='wifi', switching=False, switch_target=None, keep_alive=False,
                  guard_active=False, guard_status='', last_checked='', interval=60, autostart='enabled')
    values.update(changes)
    return tray.TrayState(**values)


@pytest.mark.parametrize('switching,mode,expected', [
    (True, 'wifi', 'switching'),
    (False, 'wifi', 'wifi'),
    (False, 'ethernet', 'ethernet'),
    (False, 'unknown', 'unknown'),
])
def test_icon_follows_network_and_switching(switching, mode, expected):
    # 保持在线只画角标，不再替换网络图标。
    assert tray.icon_name(_state(switching=switching, mode=mode, keep_alive=True)) == expected


def test_network_switch_marks_switching_then_clears(monkeypatch):
    seen = []
    monkeypatch.setattr(tray.network, 'get_current_mode', lambda: 'wifi')

    def switch():
        seen.append((tray._switching, tray._switch_target))
        return True, ''

    monkeypatch.setattr(tray.network, 'switch_to_ethernet', switch)
    view = FakeView()
    tray._switch_lock.acquire()
    tray._do_switch_and_release(view)
    assert seen == [(True, 'ethernet')]
    assert not tray._switching and tray._switch_target is None and not tray._switch_lock.locked()
    assert [note.title for note in view.notes] == ['正在切换到有线网络', '已切换到有线网络']
    assert {note.key for note in view.notes} == {'network'}  # 同一张卡片原地更新
    assert view.refreshes >= 2


def test_tray_icons_render_without_assets(qapp):
    from workpal.ui import icons
    for name in ('wifi', 'ethernet', 'switching', 'unknown'):
        for badge in (False, True):
            icon = icons.tray_icon(name, badge)
            assert not icon.isNull()
            assert not icons.tray_pixmap(name, badge, 16).toImage().isNull()


def test_keep_alive_badge_changes_icon(qapp):
    from workpal.ui import icons
    plain = icons.tray_pixmap('wifi', False, 32).toImage()
    badged = icons.tray_pixmap('wifi', True, 32).toImage()
    assert plain != badged
    assert plain.pixelColor(4, 4) == badged.pixelColor(4, 4)  # 左上角网络底色不变
