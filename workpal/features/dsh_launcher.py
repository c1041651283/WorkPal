"""
workpal/features/dsh_launcher.py
带公司代理启动 DeepSeek Harness（DSH）桌面版。

DSH 自带的 Node 不读取 Windows 系统代理，直连外网会被防火墙拦截，插件安装因此一直卡在“正在检查”。
这里只给 DSH 进程注入代理环境变量，不修改系统或用户级环境变量，其他程序不受影响：
  - HTTP(S)_PROXY 指向公司固定代理（VPN_PROXY_SERVER）
  - NODE_USE_ENV_PROXY=1 让 Node 内置的 fetch 使用上述代理
  - NO_PROXY 列出要直连的内网地址：本机回环、DSH_NO_PROXY 配置项，
    以及 DSH 配置文件中模型接口（baseURL）的主机名，避免内网模型被送到代理而连不上
Node 的 NO_PROXY 不支持 10.0.0.0/8 这类网段写法，因此按主机名逐个列出。
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

EXE_NAME = 'DeepSeek Harness.exe'
LOOPBACK = ('localhost', '127.0.0.1', '::1')
_BASE_URL = re.compile(r'^\s*baseURL\s*:\s*["\']?([^"\'\s#]+)', re.IGNORECASE | re.MULTILINE)
_PROXY_KEYS = ('HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY')

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


def candidate_paths(configured: str = '') -> list[Path]:
    """配置的路径优先，其次是常见安装位置。"""
    paths = []
    if configured.strip():
        paths.append(Path(os.path.expandvars(configured.strip().strip('"'))))
    local = os.environ.get('LOCALAPPDATA', '')
    roots = [r'D:\dsh', r'C:\dsh']
    if local:
        roots.append(os.path.join(local, 'Programs', 'DeepSeek Harness'))
    for env in ('ProgramFiles', 'ProgramFiles(x86)'):
        if os.environ.get(env):
            roots.append(os.path.join(os.environ[env], 'DeepSeek Harness'))
    paths += [Path(root) / EXE_NAME for root in roots]
    return paths


def find_executable(configured: str = '') -> Path | None:
    """配置了路径但文件不存在时不再猜测，避免启动到另一份安装。"""
    if configured.strip():
        path = candidate_paths(configured)[0]
        return path if path.is_file() else None
    return next((path for path in candidate_paths() if path.is_file()), None)


def config_files(home: Path | None = None) -> list[Path]:
    base = (home or Path.home()) / '.dsh'
    return [base / 'profiles' / 'desktop' / 'cordis.patch.yml',
            base / 'profiles' / 'desktop' / 'cordis.yml',
            base / 'cordis.patch.yml']


def model_hosts(files: list[Path] | None = None) -> list[str]:
    """读取 DSH 配置中模型接口的主机名；文件缺失或无法读取时跳过。"""
    hosts: list[str] = []
    for path in files if files is not None else config_files():
        try:
            text = path.read_text(encoding='utf-8-sig')
        except OSError:
            continue
        for url in _BASE_URL.findall(text):
            host = urlparse(url).hostname
            if host and host not in hosts:
                hosts.append(host)
    return hosts


def no_proxy_list(configured: str = '', hosts: list[str] | None = None) -> list[str]:
    """合并回环地址、配置项和模型主机名，保持顺序并去重（不区分大小写）。"""
    items = list(LOOPBACK)
    items += [x.strip() for x in re.split(r'[,;\s]+', configured) if x.strip()]
    items += hosts if hosts is not None else model_hosts()
    seen: set[str] = set()
    result = []
    for item in items:
        if item.lower() not in seen:
            seen.add(item.lower())
            result.append(item)
    return result


def proxy_url(server: str) -> str:
    server = server.strip()
    return server if '://' in server else f'http://{server}'


def build_env(base: dict[str, str], server: str, no_proxy: list[str]) -> dict[str, str]:
    """在 base 副本上设置代理变量。大小写两种写法都设置，避免残留的小写变量覆盖。"""
    env = dict(base)
    values = {'HTTP_PROXY': proxy_url(server), 'HTTPS_PROXY': proxy_url(server),
              'NO_PROXY': ','.join(no_proxy)}
    for key in _PROXY_KEYS:
        for existing in [k for k in env if k.upper() == key]:
            del env[existing]
        env[key] = env[key.lower()] = values[key]
    env['NODE_USE_ENV_PROXY'] = '1'
    return env


def is_running() -> bool:
    import psutil
    for process in psutil.process_iter(['name']):
        try:
            if (process.info.get('name') or '').lower() == EXE_NAME.lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def launch(path: Path, env: dict[str, str]) -> None:
    """独立启动，WorkPal 退出不影响 DSH。"""
    subprocess.Popen([str(path)], env=env, cwd=str(path.parent), close_fds=True,
                     creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
