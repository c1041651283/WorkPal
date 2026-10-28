"""托盘退出线程与图标优先级；不创建真实托盘或修改网络。"""

import threading
from unittest.mock import MagicMock, patch

import pytest

from workpal import tray


def test_quit_runs_in_background_and_releases_lock(monkeypatch):
    started, finish = threading.Event(), threading.Event()

    def slow_quit(icon):
        started.set()
        finish.wait(5)

    monkeypatch.setattr(tray, '_quit_when_idle', slow_quit)
    tray._on_quit(MagicMock(), None)
    # 回调立即返回，托盘线程不等待代理守护停止。
    assert started.wait(2)
    assert tray._switch_lock.locked()
    finish.set()
    for thread in threading.enumerate():
        if thread.name == 'quit':
            thread.join(2)
    assert not tray._switch_lock.locked()


def test_quit_failure_is_reported_and_releases_lock(monkeypatch):
    monkeypatch.setattr(tray, '_quit_when_idle', MagicMock(side_effect=RuntimeError('boom')))
    icon = MagicMock()
    tray._switch_lock.acquire()
    tray._quit_and_release(icon)
    assert not tray._switch_lock.locked()
    assert icon.notify.call_args.kwargs['title'] == '退出失败'


@pytest.mark.parametrize('switching,alive,mode,expected', [
    (True, True, 'wifi', 'switching'),
    (False, True, 'wifi', 'alive'),
    (False, False, 'ethernet', 'ethernet'),
    (False, False, 'unknown', 'default'),
])
def test_icon_priority(monkeypatch, switching, alive, mode, expected):
    monkeypatch.setattr(tray, '_switching', switching)
    monkeypatch.setattr(tray.keep_alive, 'is_active', lambda: alive)
    monkeypatch.setattr(tray, '_current_network_mode', lambda: mode)
    with patch.object(tray, '_set_icon') as set_icon:
        tray._refresh_icon(MagicMock())
    set_icon.assert_called_once()
    assert set_icon.call_args.args[1] == expected


def test_network_switch_keeps_keep_alive_icon(monkeypatch):
    monkeypatch.setattr(tray.keep_alive, 'is_active', lambda: True)
    monkeypatch.setattr(tray.network, 'get_current_mode', lambda: 'wifi')
    monkeypatch.setattr(tray.network, 'switch_to_ethernet', lambda: (True, ''))
    with patch.object(tray, '_set_icon') as set_icon:
        tray._switch_lock.acquire()
        tray._do_switch_and_release(MagicMock())
    assert [call.args[1] for call in set_icon.call_args_list] == ['switching', 'alive']
    assert not tray._switching and not tray._switch_lock.locked()


def test_loaded_icons_are_cached():
    tray._load_icon.cache_clear()
    assert tray._load_icon('wifi') is tray._load_icon('wifi')
