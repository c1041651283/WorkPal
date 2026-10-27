"""手动启用的低频代理守护；只读网络状态，不操作 VPN 连接或配置。"""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from urllib.parse import urlsplit

from workpal.features.proxy_settings import (
    ProxyOperationCancelled, ProxySession, WindowsProxyStore,
)
from workpal.system import get_user_data_path
from workpal.features.network_guard import network_change_lock
from workpal.features.adapter_status import read_adapters

logger = logging.getLogger(__name__)
POLL_SECONDS = 60
RESUME_CHECK_SECONDS = 5
MUTEX_NAME = r'Local\WorkPal-FortiClient-Proxy-Assistant'


@dataclass(frozen=True)
class TunnelStatus:
    state: str  # connected / disconnected / unknown
    proxy_ready: bool = False
    office_connected: bool = False

    @property
    def ready(self) -> bool:
        return self.proxy_ready and (self.state == 'connected' or self.office_connected)


def check_interval() -> int:
    from workpal.config import CONFIG
    try:
        return max(30, min(3600, int(CONFIG.get('proxy_check_interval', POLL_SECONDS))))
    except (ValueError, TypeError):
        return POLL_SECONDS


def classify_adapters(adapters: list[dict], proxy_ready: bool = False) -> TunnelStatus:
    """缺少网卡、查询失败和连接中的状态均不视作断线。"""
    found = False
    uncertain = False
    for adapter in adapters:
        name = str(adapter.get('name', '')).lower()
        if not (name.startswith('fortinet ') and 'virtual ethernet adapter' in name):
            continue
        found = True
        status = adapter.get('status')
        if status == 2:
            addresses = adapter.get('addresses') or []
            if isinstance(addresses, str):
                addresses = [addresses]
            for address in addresses:
                try:
                    ip = ipaddress.ip_address(address)
                except (ValueError, TypeError):
                    continue
                if not (ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast):
                    return TunnelStatus('connected', proxy_ready)
            uncertain = True
        elif status not in (0, 4, 5, 7):
            uncertain = True
    return TunnelStatus('disconnected' if found and not uncertain else 'unknown')


def parse_proxy(server: str) -> tuple[str, int]:
    server = server.removeprefix('http://')
    match = re.fullmatch(r'([a-zA-Z0-9.-]+):(\d{1,5})', server)
    if not match or not 1 <= int(match[2]) <= 65535:
        raise ValueError('VPN_PROXY_SERVER 必须为 主机名:端口，不包含账号、路径或命令')
    return match[1], int(match[2])


def probe_proxy(server: str) -> bool:
    """有超时的 TCP 检查；异步连接同时限制 DNS 等待，不发送业务数据。"""
    host, port = parse_proxy(server)
    script = r'''
$client = [System.Net.Sockets.TcpClient]::new()
$ready = $false
try {
    $operation = $client.BeginConnect('__HOST__', __PORT__, $null, $null)
    if ($operation.AsyncWaitHandle.WaitOne(2500)) {
        $client.EndConnect($operation)
        $ready = $client.Connected
    }
} catch {} finally { $client.Dispose() }
$ready | ConvertTo-Json -Compress
'''.replace('__HOST__', host).replace('__PORT__', str(port))
    powershell = str(Path(os.environ.get('SystemRoot', r'C:\Windows')) /
                     'System32/WindowsPowerShell/v1.0/powershell.exe')
    result = subprocess.run(
        [powershell, '-NoProfile', '-NonInteractive', '-Command', script],
        capture_output=True, encoding='utf-8', errors='replace',
        timeout=8, creationflags=subprocess.CREATE_NO_WINDOW, check=True,
    )
    return json.loads(result.stdout.lstrip('\ufeff')) is True


def query_tunnel(server: str) -> TunnelStatus:
    """网卡查询失败与公司代理不可达分开处理，不再依赖 CIM/WMI。"""
    from workpal.config import CONFIG
    try:
        adapters = read_adapters()
        tunnel = classify_adapters(adapters)
        office = any(x['friendly_name'] == CONFIG['ethernet_adapter_name']
                     and x['interface_type'] == 6 and x['status'] == 2
                     and x['addresses'] and not x['name'].lower().startswith('fortinet ')
                     for x in adapters)
    except (OSError, ValueError, KeyError, TypeError):
        logger.exception('读取网卡失败，保持未知状态')
        return TunnelStatus('unknown')
    ready = False
    if tunnel.state == 'connected' or office:
        try:
            ready = probe_proxy(server)
        except (OSError, subprocess.SubprocessError, ValueError):
            logger.warning('公司代理探测失败或超时，网卡状态=%s', tunnel.state)
    return TunnelStatus(tunnel.state, ready, office)


def find_forticlient(configured: str = '') -> Path:
    candidates = ([Path(configured)] if configured else [
        Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Fortinet/FortiClient/FortiClient.exe',
        Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Fortinet/FortiClient/FortiClient.exe',
    ])
    for path in candidates:
        if path.is_absolute() and path.name.lower() == 'forticlient.exe' and path.is_file():
            return path
    raise RuntimeError('未找到 FortiClient.exe，请配置 FORTICLIENT_PATH；尚未修改代理')


def launch_forticlient(path: Path) -> None:
    # 仅启动已有 GUI，不传任何参数，不触碰密码、连接配置、服务或网卡。
    subprocess.Popen([str(path)], cwd=str(path.parent), shell=False)


class ProxyFlow:
    """已确认公司网络可用才恢复固定代理；连续断线才关闭，不把未知当断线。"""

    def __init__(self, session: ProxySession, server: str, *, home: bool = True):
        self.session = session
        self.server = server
        self.home = home
        self.good = self.down = self.unreachable = 0
        self.mode = 'waiting'
        self.reconciled = False

    def reset_observations(self) -> None:
        self.good = self.down = self.unreachable = 0
        self.reconciled = False

    def prepare(self, status: TunnelStatus, *, reconnect: bool = False) -> None:
        if self.home and status.state == 'unknown' and not status.ready and not reconnect:
            raise RuntimeError('无法确认 VPN 状态，未修改代理；请确认 FortiClient 正常运行后重试')
        self.session.begin(resume=True)
        if self.home and not status.ready and (status.state == 'disconnected' or reconnect):
            self.session.enforce(server=None)

    def reconnect(self, status: TunnelStatus) -> None:
        """用户明确点击重连：只准备代理，沿用原会话备份。"""
        self.home = True
        self.reset_observations()
        if not status.ready:
            self.session.enforce(server=None)
            self.mode = 'reconnecting'

    def tick(self, status: TunnelStatus, *, immediate: bool = False) -> str | None:
        self.reconciled = False
        if status.ready:
            self.good += 1
            self.down = self.unreachable = 0
            if self.good >= 2 or immediate:
                changed = self.session.enforce(server=self.server)
                transitioned = self.mode != 'connected'
                self.mode = 'connected'
                self.reconciled = True
                if changed:
                    logger.info('代理守护：公司网络可用，已恢复固定代理（关闭系统 PAC 和自动检测）')
                    return '已恢复公司固定代理；公司网页请用专用 Edge 快捷方式'
                if transitioned:
                    return '公司网络已就绪，固定代理设置正确'
        elif status.state == 'disconnected' and (self.home or not status.office_connected):
            self.good = self.unreachable = 0
            self.down += 1
            if self.down >= 3 and (self.home or self.mode != 'waiting'):
                changed = self.session.enforce(server=None)
                transitioned = self.mode != 'disconnected'
                self.mode = 'disconnected'
                if changed or transitioned:
                    logger.info('代理守护：连续确认 VPN 断开且公司代理未就绪，系统代理已关闭')
                    return '已确认 VPN 断开，已关闭系统代理；重新连接后会自动启用'
        elif status.state == 'connected' and not status.proxy_ready and self.home:
            self.good = self.down = 0
            self.unreachable += 1
            if self.unreachable >= 3:
                changed = self.session.enforce(server=None)
                transitioned = self.mode != 'unavailable'
                self.mode = 'unavailable'
                if changed or transitioned:
                    return '公司代理连续不可达，已临时关闭系统代理；可点击“在家连接 / 重新连接公司”重新登录'
        else:
            # 网卡读取失败不是 VPN 已断开的证据。
            self.good = self.down = self.unreachable = 0
        return None

    def describe(self, status: TunnelStatus) -> str:
        if status.ready and self.reconciled:
            return '公司网络已就绪 · 固定代理正常'
        if self.mode == 'disconnected' and status.state == 'disconnected' and not status.ready:
            return 'VPN 已断开 · 系统代理已关闭'
        if status.state == 'disconnected' and not status.ready:
            return 'VPN 已断开 · 正在复核代理设置'
        if status.state == 'unknown' and not status.ready:
            return '无法确认 VPN 状态 · 保持当前代理'
        if not status.proxy_ready:
            if self.mode == 'unavailable':
                return '公司代理不可达 · 已临时关闭系统代理'
            return '公司代理不可达 · 正在复核连接'
        return '等待确认公司网络 · 保持当前代理'


class VpnProxyAssistant:
    def __init__(self):
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._manual_check = threading.Event()
        self._resume_check = threading.Event()
        self._reconnect = threading.Event()
        self._last_resume = float('-inf')
        self._thread: threading.Thread | None = None
        self._finishing = False
        self._pending_start = None
        self.status = '未开启（需手动开启）'
        self.last_checked = ''

    @property
    def active(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self, notify, *, home: bool = False, once: bool = False, refresh=None) -> None:
        message = None
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                if self._stop.is_set():
                    message = '代理守护正在暂停，请稍候再开启'
                elif self._finishing:
                    previous = self._pending_start
                    self._pending_start = (notify, home or bool(previous and previous[1]),
                                           once and (previous is None or previous[2]), refresh)
                    message = '已接收请求，将在本次检查结束后执行'
                elif home:
                    self._reconnect.set()
                    self._wake.set()
                    message = '已请求准备重新连接；无需恢复旧代理或停止守护'
                elif once:
                    self._manual_check.set()
                    self._wake.set()
                    message = '已请求立即检查'
                else:
                    message = '代理守护已在运行；更换模式前请先暂停'
            else:
                self._start_locked(notify, home=home, once=once, refresh=refresh)
        # 菜单刷新会再次查询 active，回调必须在锁外执行。
        if message:
            notify(message)

    def _start_locked(self, notify, *, home=False, once=False, refresh=None):
        self._stop.clear()
        self._wake.clear()
        self._manual_check.clear()
        self._resume_check.clear()
        self._reconnect.clear()
        self._finishing = False
        self._pending_start = None
        self._last_resume = float('-inf')
        self.status = '正在检查'
        self._thread = threading.Thread(target=self._run, args=(notify,),
                                        kwargs={'home': home, 'once': once and not home, 'refresh': refresh},
                                        daemon=True, name='proxy-guard')
        self._thread.start()

    def request_resume_check(self, reason: str) -> bool:
        """电源/会话消息仅唤醒已有守护，不自动开启守护或连接 VPN。"""
        with self._lock:
            if not self._thread or not self._thread.is_alive() or self._stop.is_set():
                return False
            now = time.monotonic()
            if now - self._last_resume < 15:
                return False
            self._last_resume = now
            self._resume_check.set()
            self._wake.set()
        logger.info('%s：请求短暂复查 VPN 和公司代理', reason)
        return True

    def stop(self) -> bool:
        with self._lock:
            self._stop.set()
            self._wake.set()
            self._pending_start = None
            thread = self._thread
        if thread:
            thread.join(timeout=20)
            return not thread.is_alive()
        return True

    def _run(self, notify, *, home: bool = False, once: bool = False, refresh=None) -> None:
        from workpal.config import CONFIG
        import win32api
        import win32event

        mutex = None
        acquired = False
        network_acquired = False
        session = None
        flow = None
        final_message = None
        failed = False
        try:
            mutex = win32event.CreateMutex(None, False, MUTEX_NAME)
            acquired = win32event.WaitForSingleObject(mutex, 0) in (0, 0x80)
            if not acquired:
                raise RuntimeError('另一份 WorkPal 正在管理代理，请先在那一份中停止助手')
            network_acquired = network_change_lock.acquire(blocking=False)
            if not network_acquired:
                raise RuntimeError('正在切换网卡，请完成后再启动代理助手；尚未修改代理')
            server = CONFIG['vpn_proxy_server'].removeprefix('http://')
            parse_proxy(server)
            initial = query_tunnel(server)
            if self._stop.is_set():
                return
            launch = home and not initial.ready
            executable = find_forticlient(CONFIG.get('forticlient_path', '')) if launch else None
            session = ProxySession(WindowsProxyStore(), backup_path(), cancelled=self._stop.is_set)
            before = session.store.read()
            flow = ProxyFlow(session, server, home=home)
            flow.prepare(initial, reconnect=home)
            if launch:
                if not self._launch_prepared_client(session, before, executable):
                    return
                notify('系统代理已临时关闭；请在 FortiClient 中自行登录、连接和输入验证码')
            if self._stop.is_set():
                return
            logger.info('代理守护开启：home=%s, once=%s, interval=%s', home, once, check_interval())
            if not once:
                notify(f'代理守护已开启，每 {check_interval()} 秒检查一次；可随时立即检查或暂停')
            status = initial
            immediate = not home
            rechecks = 0
            while not self._stop.is_set():
                # 所有检查共用一个线程；手动点击唤醒它，不再启动并发写入。
                message = flow.tick(status, immediate=immediate)
                description = flow.describe(status)
                prefix = '单次检查完成 · ' if once else '在家守护中 · ' if flow.home else '守护中 · '
                previous_status = self.status
                self.status = prefix + description
                self.last_checked = time.strftime('%H:%M:%S')
                if previous_status != self.status:
                    logger.info('代理守护状态：%s', self.status)
                if refresh:
                    try:
                        refresh()
                    except Exception:
                        logger.exception('刷新代理守护菜单失败')
                if once:
                    with self._lock:
                        if self._reconnect.is_set():
                            once = False
                        elif not self._manual_check.is_set():
                            # 请求接收和完成判定使用同一把锁，避免承诺后丢失请求。
                            self._finishing = True
                    if self._finishing:
                        final_message = '单次检查完成 · ' + (message or description)
                        break
                if message:
                    notify(message)
                elif immediate:
                    notify(description)
                self._wake.wait(RESUME_CHECK_SECONDS if rechecks else check_interval())
                with self._lock:
                    self._wake.clear()
                    if self._stop.is_set():
                        break
                    immediate = self._manual_check.is_set()
                    self._manual_check.clear()
                    resume = self._resume_check.is_set()
                    self._resume_check.clear()
                    reconnect = self._reconnect.is_set()
                    self._reconnect.clear()
                if resume or reconnect:
                    flow.reset_observations()
                    rechecks = 2  # 本次 + 两次 5 秒间隔的复查，随后恢复用户间隔。
                elif rechecks:
                    rechecks -= 1
                status = query_tunnel(server)
                if self._stop.is_set():
                    break
                if reconnect:
                    self._prepare_reconnect(flow, status, notify)
        except ProxyOperationCancelled:
            pass
        except Exception as exc:
            failed = True
            self.status = f'守护已停止：{exc}'
            logger.exception('代理守护停止；保留当前代理和恢复备份')
            final_message = self.status
        finally:
            with self._lock:
                self._finishing = True
            if self._stop.is_set() and not failed:
                self.status = '已暂停 · 保留当前代理'
                final_message = '代理守护已暂停，当前代理保持不变'
            logger.info('代理守护结束：%s', self.status)
            if acquired:
                win32event.ReleaseMutex(mutex)
            if mutex is not None:
                win32api.CloseHandle(mutex)
            if network_acquired:
                network_change_lock.release()
            with self._lock:
                if self._thread is threading.current_thread():
                    self._thread = None
                    pending = self._pending_start
                    self._pending_start = None
                    if pending and not self._stop.is_set():
                        callback, next_home, next_once, next_refresh = pending
                        self._start_locked(callback, home=next_home, once=next_once, refresh=next_refresh)
            if final_message:
                # 先释放会话和线程，再通知菜单，使“开启”按钮立即重新可用。
                notify(final_message)

    def _launch_prepared_client(self, session: ProxySession, before, executable: Path) -> bool:
        """暂停发生在临时关闭之后时，撤销本次准备，不恢复更早的代理备份。"""
        def undo_preparation():
            if not session.store.read().equivalent(before):
                # apply 检查当前值仍属本次操作，避免覆盖外部程序的新设置。
                session.apply(before)

        if self._stop.is_set():
            undo_preparation()
            return False
        try:
            launch_forticlient(executable)
        except Exception:
            undo_preparation()
            raise
        return True

    def _prepare_reconnect(self, flow: ProxyFlow, status: TunnelStatus, notify) -> None:
        from workpal.config import CONFIG
        # 查找失败时尚未关闭代理；不传递任何 FortiClient 连接或配置参数。
        executable = find_forticlient(CONFIG.get('forticlient_path', '')) if not status.ready else None
        before = flow.session.store.read()
        flow.reconnect(status)
        if executable:
            if not self._launch_prepared_client(flow.session, before, executable):
                return
            notify('已临时关闭系统代理，请在 FortiClient 中重新登录；守护会继续检查')
        else:
            notify('公司网络仍可用，保持当前连接；未关闭代理或重连 VPN')


def backup_path() -> Path:
    return Path(get_user_data_path('vpn_proxy_session.json'))


assistant = VpnProxyAssistant()


def use_script_proxy() -> None:
    """一次性启用脚本、关闭手动代理；暂停守护，后续由用户自行开启。"""
    from workpal.config import CONFIG
    import win32api
    import win32event

    url = CONFIG['office_pac_url'].strip()
    parsed = urlsplit(url)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or any(char.isspace() for char in url)):
        raise ValueError('OFFICE_PAC_URL 必须为有效的 HTTP/HTTPS 脚本地址')
    if not assistant.stop():
        raise RuntimeError('代理守护仍在结束检查，请稍后重试；尚未切换脚本代理')
    mutex = win32event.CreateMutex(None, False, MUTEX_NAME)
    acquired = win32event.WaitForSingleObject(mutex, 0) in (0, 0x80)
    network_acquired = False
    try:
        if not acquired:
            raise RuntimeError('另一份 WorkPal 正在管理代理，请先停止那一份助手')
        network_acquired = network_change_lock.acquire(blocking=False)
        if not network_acquired:
            raise RuntimeError('正在切换网卡，请稍后重试；尚未切换脚本代理')
        session = ProxySession(WindowsProxyStore(), backup_path())
        session.begin(resume=True)
        session.enforce(pac_url=url)
        assistant.status = '脚本代理开启 · 手动代理关闭 · 守护未开启'
        assistant.last_checked = ''
        logger.info('已启用脚本代理并关闭手动代理，守护等待用户手动开启')
    finally:
        if network_acquired:
            network_change_lock.release()
        if acquired:
            win32event.ReleaseMutex(mutex)
        win32api.CloseHandle(mutex)


def restore_backup() -> None:
    """用户显式点击恢复；不在启动时自动覆盖代理。"""
    import win32api
    import win32event

    if not assistant.stop():
        raise RuntimeError('助手仍在退出，请稍后重试')
    mutex = win32event.CreateMutex(None, False, MUTEX_NAME)
    acquired = win32event.WaitForSingleObject(mutex, 0) in (0, 0x80)
    try:
        if not acquired:
            raise RuntimeError('另一份 WorkPal 正在管理代理，请先停止那一份助手')
        if backup_path().exists():
            ProxySession(WindowsProxyStore(), backup_path()).restore(explicit=True)
        assistant.status = '原代理已恢复'
    finally:
        if acquired:
            win32event.ReleaseMutex(mutex)
        win32api.CloseHandle(mutex)
