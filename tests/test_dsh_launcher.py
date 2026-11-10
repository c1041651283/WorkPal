"""带代理启动 DeepSeek Harness：环境变量、直连列表、配置解析和托盘动作；不启动真实进程。"""

from pathlib import Path

import pytest

from workpal import config, tray
from workpal.features import dsh_launcher
from tests.fake_view import FakeView


# ---------------------------------------------------------------- 环境变量


def test_build_env_sets_proxy_and_keeps_others():
    base = {'PATH': r'C:\Windows', 'https_proxy': 'http://old:1', 'No_Proxy': 'stale'}
    env = dsh_launcher.build_env(base, 'proxy.ricoh.co.jp:8080', ['localhost', '10.96.135.60'])
    assert env['PATH'] == r'C:\Windows'
    for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
        assert env[key] == 'http://proxy.ricoh.co.jp:8080'
    assert env['NO_PROXY'] == env['no_proxy'] == 'localhost,10.96.135.60'
    assert 'No_Proxy' not in env  # 残留的其他大小写写法被替换，不会与新值冲突
    assert env['NODE_USE_ENV_PROXY'] == '1'
    assert base['https_proxy'] == 'http://old:1'  # 不修改传入的环境（即 WorkPal 自身）


@pytest.mark.parametrize('server,expected', [
    ('proxy:8080', 'http://proxy:8080'),
    (' http://proxy:8080 ', 'http://proxy:8080'),
])
def test_proxy_url(server, expected):
    assert dsh_launcher.proxy_url(server) == expected


def test_no_proxy_merges_and_dedupes():
    result = dsh_launcher.no_proxy_list('.psh.com.cn; LOCALHOST  10.0.0.1',
                                        hosts=['10.0.0.1', 'chat.psh.com.cn'])
    assert result == ['localhost', '127.0.0.1', '::1', '.psh.com.cn', '10.0.0.1', 'chat.psh.com.cn']


# ---------------------------------------------------------------- DSH 配置


def test_model_hosts_reads_base_urls(tmp_path):
    first = tmp_path / 'cordis.patch.yml'
    first.write_text(
        'plugins:\n'
        '  a:\n'
        '        baseURL: https://localchat.psh.com.cn/api\n'
        '  b:\n'
        "        baseURL: 'http://10.96.135.60:4000/v1'  # 内网\n"
        '  c:\n'
        '        baseurl: https://localchat.psh.com.cn/other\n',
        encoding='utf-8-sig')
    missing = tmp_path / 'missing.yml'
    assert dsh_launcher.model_hosts([first, missing]) == ['localchat.psh.com.cn', '10.96.135.60']


def test_find_executable_respects_configured_path(tmp_path):
    exe = tmp_path / dsh_launcher.EXE_NAME
    assert dsh_launcher.find_executable(str(exe)) is None  # 配置了但不存在时不去猜其他位置
    exe.write_bytes(b'')
    assert dsh_launcher.find_executable(f'"{exe}"') == exe


# ---------------------------------------------------------------- 托盘动作


@pytest.fixture
def launcher(monkeypatch, tmp_path):
    exe = tmp_path / dsh_launcher.EXE_NAME
    exe.write_bytes(b'')
    launched = []
    monkeypatch.setitem(config.CONFIG, 'dsh_path', str(exe))
    monkeypatch.setitem(config.CONFIG, 'vpn_proxy_server', 'proxy.example:8080')
    monkeypatch.setitem(config.CONFIG, 'dsh_no_proxy', '.corp.example')
    monkeypatch.setattr(dsh_launcher, 'is_running', lambda: False)
    monkeypatch.setattr(dsh_launcher, 'model_hosts', lambda files=None: ['10.1.2.3'])
    monkeypatch.setattr(dsh_launcher, 'launch', lambda path, env: launched.append((path, env)))
    return exe, launched


def test_launch_injects_proxy_env(launcher):
    exe, launched = launcher
    view = FakeView()
    tray._do_launch_dsh(view)
    (path, env), = launched
    assert path == exe
    assert env['HTTPS_PROXY'] == 'http://proxy.example:8080'
    assert env['NO_PROXY'] == 'localhost,127.0.0.1,::1,.corp.example,10.1.2.3'
    assert view.last.level == 'success' and view.last.key == 'dsh'


def test_launch_refuses_when_already_running(launcher, monkeypatch):
    _, launched = launcher
    monkeypatch.setattr(dsh_launcher, 'is_running', lambda: True)
    view = FakeView()
    tray._do_launch_dsh(view)
    assert launched == []
    assert view.last.level == 'error' and '完全退出' in view.last.message


def test_launch_reports_missing_executable(launcher, monkeypatch, tmp_path):
    _, launched = launcher
    monkeypatch.setitem(config.CONFIG, 'dsh_path', str(tmp_path / 'nope.exe'))
    view = FakeView()
    tray._do_launch_dsh(view)
    assert launched == []
    assert view.last.title == '未找到 DeepSeek Harness' and 'nope.exe' in view.last.message


def test_launch_reports_failure(launcher, monkeypatch):
    def boom(path, env):
        raise OSError('拒绝访问')
    monkeypatch.setattr(dsh_launcher, 'launch', boom)
    view = FakeView()
    tray._do_launch_dsh(view)
    assert view.last.level == 'error' and '拒绝访问' in view.last.message


def test_config_keys_load_from_ini(tmp_path):
    ini = tmp_path / 'network_config.ini'
    ini.write_text('DSH_PATH=E:\\apps\\dsh\\DeepSeek Harness.exe\nDSH_NO_PROXY=10.9.9.9\n',
                   encoding='utf-8')
    saved = dict(config.CONFIG)
    try:
        config.load_config(ini, base=config._DEFAULTS)
        assert config.CONFIG['dsh_path'] == r'E:\apps\dsh\DeepSeek Harness.exe'
        assert config.CONFIG['dsh_no_proxy'] == '10.9.9.9'
    finally:
        config.CONFIG.clear()
        config.CONFIG.update(saved)
