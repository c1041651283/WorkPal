import ctypes
import subprocess
import sys
import threading
import uuid
from unittest.mock import MagicMock

import pytest

from workpal.features import keep_alive as ka


@pytest.mark.parametrize('now,last,expected', [
    (2147483904, 2147183648, 300.256),
    (-2147483392, 2147183648, 300.256),
    (1000, 4294667296, 301.0),
    (1000, 1000, 0),
])
def test_idle_time_unsigned_and_rollover(monkeypatch, now, last, expected):
    def last_input(pointer):
        ctypes.cast(pointer, ctypes.POINTER(ka._LASTINPUTINFO)).contents.dwTime = last
        return 1
    monkeypatch.setattr(ka.ctypes.windll.user32, 'GetLastInputInfo', last_input)
    ticks = MagicMock(return_value=now)
    monkeypatch.setattr(ka.ctypes.windll.kernel32, 'GetTickCount', ticks)
    assert ka._get_idle_seconds() == expected
    assert ticks.restype == ctypes.wintypes.DWORD


def test_last_enable_request_restarts_after_old_worker_cleans_up(monkeypatch):
    ka.toggle_keep_alive(False)
    if ka._thread:
        ka._thread.join(2)
    entered, release, restarted = threading.Event(), threading.Event(), threading.Event()
    transitions = []

    def execution_state(enabled):
        transitions.append(enabled)
        if enabled and not entered.is_set():
            entered.set()
            assert release.wait(3)
        elif enabled:
            restarted.set()

    monkeypatch.setattr(ka, '_set_execution_state', execution_state)
    monkeypatch.setattr(ka, '_simulate_f15_key', MagicMock())
    monkeypatch.setattr(ka, '_get_idle_seconds', lambda: 0)
    monkeypatch.setattr(ka, 'CHECK_INTERVAL', 30)
    try:
        ka.toggle_keep_alive(True)
        assert entered.wait(2)
        old_thread, old_event = ka._thread, ka._stop_event
        ka.toggle_keep_alive(False)
        ka.toggle_keep_alive(True)
        assert ka.is_active()
        release.set()
        old_thread.join(2)
        assert restarted.wait(2)
        assert transitions[:3] == [True, False, True]
        assert ka._thread is not old_thread
        assert ka._stop_event is not old_event
        assert old_event.is_set() and not ka._stop_event.is_set()
    finally:
        release.set()
        ka.toggle_keep_alive(False)
        if ka._thread:
            ka._thread.join(2)


@pytest.mark.parametrize('frozen', [False, True])
def test_default_configuration_is_independent_of_cwd(tmp_path, monkeypatch, frozen):
    from workpal import config
    app = tmp_path / 'app'
    app.mkdir()
    other = tmp_path / 'other'
    other.mkdir()
    (app / 'network_config.ini').write_text('WIFI_SSID=correct', encoding='utf-8')
    (other / 'network_config.ini').write_text('WIFI_SSID=wrong', encoding='utf-8')
    monkeypatch.chdir(other)
    monkeypatch.setattr(config, 'is_frozen', lambda: frozen)
    monkeypatch.setattr(config.sys, 'executable', str(app / 'WorkPal.exe'))
    monkeypatch.setattr(config, '__file__', str(app / 'workpal' / 'config.py'))
    monkeypatch.setattr(config, 'config_path', lambda: tmp_path / 'user' / 'network_config.ini')
    (tmp_path / 'user').mkdir()
    monkeypatch.setattr(config, '_load_user_overrides', lambda values: None)
    monkeypatch.setattr(config, 'CONFIG', config.CONFIG.copy())
    config.load_config()
    # 旧配置从程序目录迁移到用户目录，而不是从当前工作目录读取。
    assert config.CONFIG['wifi_ssid'] == 'correct'
    assert (tmp_path / 'user' / 'network_config.ini').read_text(encoding='utf-8') == 'WIFI_SSID=correct'
    config.load_config(other / 'network_config.ini')
    assert config.CONFIG['wifi_ssid'] == 'wrong'


def test_single_instance_handles_are_released_on_duplicate(monkeypatch):
    from workpal.features import single_instance as si
    monkeypatch.setattr(si.win32security, 'OpenProcessToken', lambda *args: 'token')
    monkeypatch.setattr(si.win32security, 'GetTokenInformation', lambda *args: ('sid',))
    monkeypatch.setattr(si.win32security, 'ConvertSidToStringSid', lambda _: 'user-sid')
    create = MagicMock(side_effect=['first', 'second'])
    close = MagicMock()
    monkeypatch.setattr(si.win32event, 'CreateMutex', create)
    monkeypatch.setattr(si.win32api, 'GetLastError', MagicMock(side_effect=[0, 183]))
    monkeypatch.setattr(si.win32api, 'CloseHandle', close)
    first, second = si.SingleInstance(), si.SingleInstance()
    assert first.acquire()
    assert not second.acquire()
    assert create.call_args.args[2] == r'Local\WorkPal-Instance-user-sid'
    assert ('second',) in [call.args for call in close.call_args_list]
    first.close()
    first.close()
    assert [call.args for call in close.call_args_list].count(('first',)) == 1


def test_quit_during_network_switch_does_not_exit(monkeypatch):
    from workpal import tray
    quit_action = MagicMock()
    monkeypatch.setattr(tray, '_quit_when_idle', quit_action)
    from tests.fake_view import FakeView
    view = FakeView()
    with tray._switch_lock:
        tray.quit_app(view)
    quit_action.assert_not_called()
    assert len(view.notes) == 1


def test_native_single_instance_excludes_another_process_and_releases(monkeypatch):
    from workpal.features import single_instance as si
    isolated_sid = 'test-' + uuid.uuid4().hex
    monkeypatch.setattr(si.win32security, 'ConvertSidToStringSid', lambda _: isolated_sid)
    code = ("from workpal.features import single_instance as s; "
            f"s.win32security.ConvertSidToStringSid=lambda _: {isolated_sid!r}; "
            "guard=s.SingleInstance(); print(guard.acquire()); guard.close()")
    guard = si.SingleInstance()
    assert guard.acquire()
    try:
        child = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                               timeout=10, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        assert child.stdout.strip() == 'False'
    finally:
        guard.close()
    child = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                           timeout=10, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    assert child.stdout.strip() == 'True'
