"""配置固定放在用户目录：迁移旧配置、按需生成、重新加载；全部在临时目录中进行。"""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from workpal import config
from tests.fake_view import FakeView


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    program, user = tmp_path / 'program', tmp_path / 'user'
    program.mkdir()
    user.mkdir()
    monkeypatch.setattr(config, '_program_dir', lambda: program)
    monkeypatch.setattr(config, 'config_path', lambda: user / 'network_config.ini')
    monkeypatch.setattr(config, '_load_user_overrides', lambda values: None)
    monkeypatch.setattr(config, 'CONFIG', dict(config._DEFAULTS))
    return program, user


def test_config_lives_in_user_data_directory(monkeypatch, tmp_path):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    assert config.config_path() == tmp_path / 'WorkPal' / 'network_config.ini'


def test_legacy_config_is_migrated_once_and_kept(dirs):
    program, user = dirs
    (program / 'network_config.ini').write_text('WIFI_SSID=office', encoding='utf-8')
    config.load_config()
    assert config.CONFIG['wifi_ssid'] == 'office'
    assert (user / 'network_config.ini').read_text(encoding='utf-8') == 'WIFI_SSID=office'
    assert (program / 'network_config.ini').exists()  # 原文件不删除


def test_new_build_without_config_keeps_user_settings(dirs):
    program, user = dirs
    (user / 'network_config.ini').write_text('WIFI_SSID=office', encoding='utf-8')
    config.load_config()
    assert config.CONFIG['wifi_ssid'] == 'office'
    assert not (program / 'network_config.ini').exists()


def test_stale_program_copy_is_ignored_with_warning(dirs, caplog):
    program, user = dirs
    (user / 'network_config.ini').write_text('WIFI_SSID=current', encoding='utf-8')
    (program / 'network_config.ini').write_text('WIFI_SSID=stale', encoding='utf-8')
    config.load_config()
    assert config.CONFIG['wifi_ssid'] == 'current'
    assert '不再读取' in caplog.text


def test_missing_config_is_not_created_on_startup(dirs):
    _, user = dirs
    config.load_config()
    assert not (user / 'network_config.ini').exists()
    assert config.CONFIG == config._DEFAULTS


def test_edit_creates_from_template_or_defaults(dirs):
    program, user = dirs
    (program / 'network_config.ini.example').write_text('WIFI_SSID=your_wifi_ssid', encoding='utf-8')
    assert config.prepare_config_file(create=True).read_text(encoding='utf-8') == 'WIFI_SSID=your_wifi_ssid'
    (user / 'network_config.ini').unlink()
    (program / 'network_config.ini.example').unlink()
    text = config.prepare_config_file(create=True).read_text(encoding='utf-8')
    assert 'WIFI_ADAPTER_NAME=WLAN' in text and 'WIFI_PASSWORD' not in text


def test_notepad_utf8_bom_is_read(dirs):
    _, user = dirs
    (user / 'network_config.ini').write_bytes('WIFI_SSID=家里'.encode('utf-8-sig'))
    config.load_config()
    assert config.CONFIG['wifi_ssid'] == '家里'


def test_reload_restores_defaults_for_removed_keys(dirs):
    _, user = dirs
    path = user / 'network_config.ini'
    path.write_text('WIFI_SSID=office\nWIFI_ADAPTER_NAME=WiFi 2', encoding='utf-8')
    config.load_config()
    path.write_text('WIFI_SSID=home', encoding='utf-8')
    config.reload_config()
    assert config.CONFIG['wifi_ssid'] == 'home'
    assert config.CONFIG['wifi_adapter_name'] == 'WLAN'


@pytest.fixture
def watch(monkeypatch):
    from workpal import tray
    monkeypatch.setattr(tray, 'CONFIG_POLL_SECONDS', 0.02)
    monkeypatch.setattr(tray, 'CONFIG_WATCH_SECONDS', 5)
    yield tray
    with tray._config_watch_lock:
        tray._config_watch_until = 0.0
        watcher = tray._config_watcher
    if watcher is not None:
        watcher.join(2)


def _wait_for(condition, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


def test_tray_edit_reloads_on_every_save_even_if_notepad_returns_at_once(dirs, watch):
    _, user = dirs
    view = FakeView()
    with patch.object(watch.subprocess, 'Popen') as popen:
        watch.edit_config(view)
    args = popen.call_args.args[0]
    assert args[0].lower().endswith('notepad.exe') and args[1] == str(user / 'network_config.ini')
    # 新版记事本立即返回：此时尚未保存，不应重新加载或提示。
    time.sleep(0.1)
    assert view.notes == []
    (user / 'network_config.ini').write_text('WIFI_SSID=edited', encoding='utf-8')
    assert _wait_for(lambda: config.CONFIG['wifi_ssid'] == 'edited')
    assert _wait_for(lambda: view.notes and '已生效' in view.last.message)
    (user / 'network_config.ini').write_text('WIFI_SSID=again', encoding='utf-8')
    assert _wait_for(lambda: config.CONFIG['wifi_ssid'] == 'again')


def test_tray_edit_twice_reuses_one_watcher(dirs, watch):
    view = FakeView()
    with patch.object(watch.subprocess, 'Popen') as popen:
        watch.edit_config(view)
        first = watch._config_watcher
        watch.edit_config(view)
    assert popen.call_count == 2  # 再次点击重新打开记事本窗口
    assert watch._config_watcher is first
    assert [t.name for t in threading.enumerate()].count('config-watch') == 1


def test_edit_failure_is_reported(dirs, watch, monkeypatch):
    monkeypatch.setattr(config, 'prepare_config_file', MagicMock(side_effect=PermissionError('denied')))
    view = FakeView()
    watch.edit_config(view)
    assert '失败' in view.last.title and view.last.level == 'error'
    assert watch._config_watcher is None or not watch._config_watcher.is_alive()
