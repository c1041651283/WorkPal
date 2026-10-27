"""
workpal/features/network.py
网络切换功能模块。

网卡启用/禁用/状态查询：使用 wmi（替代 netsh interface set/show）
进程管理：使用 psutil（替代 tasklist/taskkill）
WiFi 连接/断开：保留 netsh wlan（无等价纯 Python API）
"""

import subprocess
import logging
import os
import locale
import time
import tempfile
import hashlib
from dataclasses import dataclass
from pathlib import Path
from functools import wraps
from xml.etree import ElementTree
from xml.sax.saxutils import escape as _xml_escape

import threading

import pythoncom
import wmi as _wmi_module
import psutil

from workpal.config import CONFIG
from workpal.features.network_guard import network_change_lock

logger = logging.getLogger(__name__)

# 线程本地 WMI 连接（每个线程独立初始化，避免 CoInitialize 错误）
_thread_local = threading.local()


def _get_wmi():
    """获取当前线程的 WMI 连接（线程安全）。COM 由 OS 在进程退出时清理。"""
    if not getattr(_thread_local, 'wmi_conn', None):
        pythoncom.CoInitialize()
        _thread_local.wmi_conn = _wmi_module.WMI()
    return _thread_local.wmi_conn


# ---------------------------------------------------------------------------
# 底层 netsh 命令（仅用于 WiFi，无纯 Python 替代方案）
# ---------------------------------------------------------------------------

def _run_netsh(args: list) -> tuple:
    """
    执行 netsh 命令。使用列表参数 + shell=False 避免命令注入。
    返回 (success: bool, stdout: str)。
    """
    sys_encoding = locale.getpreferredencoding()
    try:
        result = subprocess.run(
            ['netsh'] + args,
            shell=False,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=10,
        )
        try:
            stdout = result.stdout.decode(sys_encoding, errors='ignore')
            stderr = result.stderr.decode(sys_encoding, errors='ignore')
        except Exception:
            stdout = result.stdout.decode('utf-8', errors='ignore')
            stderr = result.stderr.decode('utf-8', errors='ignore')

        if result.returncode != 0:
            logger.error(f"netsh 命令失败: {stderr.strip()}")
        return result.returncode == 0, stdout
    except Exception as e:
        logger.error(f"netsh 命令异常: {e}")
        return False, str(e)


# ---------------------------------------------------------------------------
# 网卡管理（WMI 替代 netsh interface set/show）
# ---------------------------------------------------------------------------

def _get_wmi_adapter(adapter_name: str):
    """通过网卡连接名称获取 WMI NetworkAdapter 对象，未找到返回 None。"""
    try:
        c = _get_wmi()
        adapters = c.Win32_NetworkAdapter(NetConnectionID=adapter_name)
        return adapters[0] if adapters else None
    except Exception as e:
        logger.error(f"查询网卡 [{adapter_name}] 失败: {e}")
        return None


def get_adapter_status(adapter_name: str) -> str:
    """
    获取网卡状态。
    返回: 'enabled_connected' | 'enabled_disconnected' | 'disabled' | 'unknown' | 'not_found'

    WMI NetConnectionStatus 取值：
      2=Connected, 0/7=Disconnected/MediaDisconnected, 5=HardwareDisabled, 其余=其他
    ConfigManagerErrorCode == 22 表示设备已禁用。
    """
    adapter = _get_wmi_adapter(adapter_name)
    if adapter is None:
        return 'not_found'
    try:
        if adapter.ConfigManagerErrorCode == 22:
            return 'disabled'
        status = adapter.NetConnectionStatus
        if status == 2:
            return 'enabled_connected'
        elif status in (0, 1, 3, 7, 8, 9, 10, 11, 12):
            return 'enabled_disconnected'
        elif status == 5:
            return 'disabled'
        else:
            return 'unknown'
    except Exception as e:
        logger.error(f"读取网卡状态失败 [{adapter_name}]: {e}")
        return 'not_found'


def disable_adapter(adapter_name: str) -> bool:
    """禁用网卡（WMI）。已禁用则直接返回 True。"""
    status = get_adapter_status(adapter_name)
    if status == 'disabled':
        logger.info(f"网卡 [{adapter_name}] 已是禁用状态，跳过")
        return True

    adapter = _get_wmi_adapter(adapter_name)
    if adapter is None:
        return False
    try:
        result = adapter.Disable()
        rc = result[0] if isinstance(result, (list, tuple)) else result
        if rc == 0:
            logger.info(f"已禁用网卡: {adapter_name}")
            return True
        logger.error(f"禁用网卡 [{adapter_name}] 失败，错误码: {rc}")
        return False
    except Exception as e:
        logger.error(f"禁用网卡异常 [{adapter_name}]: {e}")
        return False


def enable_adapter(adapter_name: str) -> bool:
    """启用网卡（WMI）。已启用则直接返回 True。"""
    status = get_adapter_status(adapter_name)
    if status.startswith('enabled'):
        logger.info(f"网卡 [{adapter_name}] 已是启用状态，跳过")
        return True

    adapter = _get_wmi_adapter(adapter_name)
    if adapter is None:
        return False
    try:
        result = adapter.Enable()
        rc = result[0] if isinstance(result, (list, tuple)) else result
        if rc == 0:
            logger.info(f"已启用网卡: {adapter_name}")
            return True
        logger.error(f"启用网卡 [{adapter_name}] 失败，错误码: {rc}")
        return False
    except Exception as e:
        logger.error(f"启用网卡异常 [{adapter_name}]: {e}")
        return False


# ---------------------------------------------------------------------------
# WiFi 状态查询与操作（netsh wlan）
# ---------------------------------------------------------------------------

def get_wifi_connection_info(adapter_name: str) -> dict:
    """只匹配指定接口，保存实际连接的配置名和 SSID，供失败回滚使用。"""
    try:
        success, output = _run_netsh(['wlan', 'show', 'interfaces'])
        if not success or not output:
            return {'state': 'unknown'}
        interfaces = {}
        current = None
        for line in output.splitlines():
            if ':' not in line:
                continue
            key, _, value = line.strip().partition(':')
            key = key.strip().lower()
            value = value.strip()
            if key in ('name', '名称', 'interface name', '接口名称'):
                current = interfaces.setdefault(value, {})
            elif current is not None:
                field = {'state': 'state', '状态': 'state', 'profile': 'profile',
                         '配置文件': 'profile', 'ssid': 'ssid'}.get(key)
                if field:
                    current[field] = value
        info = interfaces.get(adapter_name, {})
        state = info.get('state', '').lower()
        info['state'] = ('connected' if state in ('connected', '已连接') else
                         'disconnected' if state in ('disconnected', 'not connected',
                             '已断开连接', '已断开', '未连接', 'not ready', '不可用', '已禁用')
                         else 'unknown')
        return info
    except Exception as e:
        logger.error(f"获取 WiFi 连接状态失败: {e}")
        return {'state': 'unknown'}


def get_wifi_connection_status(adapter_name: str) -> str:
    return get_wifi_connection_info(adapter_name)['state']


def get_current_mode() -> str:
    """
    获取当前网络模式。
    返回: 'wifi' | 'ethernet' | 'unknown'
    """
    wifi_conn = get_wifi_connection_status(CONFIG['wifi_adapter_name'])
    ethernet_status = get_adapter_status(CONFIG['ethernet_adapter_name'])
    logger.debug(f"当前模式检测 | WiFi={wifi_conn} | 有线={ethernet_status}")

    if wifi_conn == 'connected':
        return 'wifi'
    if ethernet_status == 'enabled_connected':
        return 'ethernet'
    return 'unknown'


def connect_wifi(ssid: str, password: str, *, profile_name: str | None = None) -> bool:
    """通过 netsh wlan 临时配置文件连接 WiFi。"""
    logger.info(f"连接 WiFi: {ssid}")
    safe_ssid = _xml_escape(ssid)
    safe_password = _xml_escape(password)
    profile_name = profile_name or ssid
    safe_profile = _xml_escape(profile_name)
    profile_xml = (
        '<?xml version="1.0"?>'
        '<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">'
        f'<name>{safe_profile}</name>'
        '<SSIDConfig><SSID>'
        f'<name>{safe_ssid}</name>'
        '</SSID></SSIDConfig>'
        '<connectionType>ESS</connectionType>'
        '<connectionMode>auto</connectionMode>'
        '<MSM><security><authEncryption>'
        '<authentication>WPA2PSK</authentication>'
        '<encryption>AES</encryption>'
        '<useOneX>false</useOneX>'
        '</authEncryption><sharedKey>'
        '<keyType>passPhrase</keyType>'
        '<protected>false</protected>'
        f'<keyMaterial>{safe_password}</keyMaterial>'
        '</sharedKey></security></MSM>'
        '</WLANProfile>'
    )
    # 使用随机文件名避免路径冲突，写入后尽快删除（netsh add profile 会内部缓存）
    fd, profile_path = tempfile.mkstemp(suffix='.xml', prefix='workpal_wifi_')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(profile_xml)
        add_ok, _ = _run_netsh(['wlan', 'add', 'profile', f'filename={profile_path}',
                               f"interface={CONFIG['wifi_adapter_name']}"])
        # 立即删除临时文件，WiFi 密码不应残留于磁盘
        os.remove(profile_path)
        if not add_ok:
            logger.error("添加 WiFi 配置文件失败")
            return False
        success, _ = _run_netsh(['wlan', 'connect', f'name={profile_name}', f'ssid={ssid}',
                               f"interface={CONFIG['wifi_adapter_name']}"])
        return success
    except Exception as e:
        logger.error(f"连接 WiFi 失败: {e}")
        return False
    finally:
        if os.path.exists(profile_path):
            try:
                os.remove(profile_path)
            except OSError as e:
                logger.warning(f"清理临时 WiFi 配置文件失败: {e}")


def disconnect_wifi(adapter_name: str) -> bool:
    """断开 WiFi 连接（不禁用网卡）。"""
    logger.info(f"断开 WiFi: {adapter_name}")
    success, _ = _run_netsh(['wlan', 'disconnect', f'interface={adapter_name}'])
    return success


# ---------------------------------------------------------------------------
# 进程管理（psutil 替代 tasklist/taskkill）
# ---------------------------------------------------------------------------

def check_process_running(program_path: str) -> bool:
    """检查程序是否已在运行（psutil）。"""
    if not program_path:
        return False
    target = _normalized_executable(program_path)
    for proc in psutil.process_iter():
        try:
            if _normalized_executable(proc.exe()) == target:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def _normalized_executable(path: str) -> str:
    return os.path.normcase(os.path.realpath(path)) if path else ''


def _request_process_close(pid: int) -> None:
    """Windows terminate() 等同 kill；先向目标进程窗口发送正常关闭请求。"""
    import win32con
    import win32gui
    import win32process

    def close_window(hwnd, _):
        if win32process.GetWindowThreadProcessId(hwnd)[1] == pid:
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        return True

    win32gui.EnumWindows(close_window, None)


def kill_process(program_path: str) -> bool:
    """只关闭完整路径匹配的进程；等待正常退出，再对同一进程强制结束。"""
    if not program_path:
        return True
    target = _normalized_executable(program_path)
    success = True
    for proc in psutil.process_iter():
        matched = False
        try:
            if _normalized_executable(proc.exe()) != target:
                continue
            matched = True
            _request_process_close(proc.pid)
            try:
                proc.wait(timeout=3)
            except psutil.TimeoutExpired:
                # is_running/kill 检查 PID 重用；不可终止后来占用该 PID 的进程。
                if proc.is_running() and _normalized_executable(proc.exe()) == target:
                    proc.kill()
                    proc.wait(timeout=3)
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied:
            logger.warning('进程路径或权限无法确认，跳过 pid=%s', proc.pid)
            if matched:
                success = False
        except Exception:
            logger.exception('关闭验证程序失败，pid=%s', proc.pid)
            success = False
    return success


def start_program(program_path: str) -> bool:
    """启动外部程序。"""
    if not os.path.exists(program_path):
        logger.error(f"程序不存在: {program_path}")
        return False
    try:
        logger.info(f"启动程序: {program_path}")
        subprocess.Popen([program_path], shell=False, creationflags=subprocess.CREATE_NO_WINDOW)
        return True
    except Exception as e:
        logger.error(f"启动程序失败: {e}")
        return False


# ---------------------------------------------------------------------------
# 状态轮询等待
# ---------------------------------------------------------------------------

def _wait_for(check_fn, timeout: int, interval: float = 1.0) -> bool:
    """通用轮询等待，直到 check_fn() 返回 True 或超时。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check_fn():
            return True
        time.sleep(interval)
    return False


def wait_for_adapter_disabled(adapter_name: str, timeout: int = 10) -> bool:
    return _wait_for(lambda: get_adapter_status(adapter_name) == 'disabled', timeout)


def wait_for_adapter_enabled(adapter_name: str, timeout: int = 10) -> bool:
    return _wait_for(lambda: get_adapter_status(adapter_name).startswith('enabled'), timeout)


def wait_for_adapter_connected(adapter_name: str, timeout: int = 15) -> bool:
    return _wait_for(lambda: get_adapter_status(adapter_name) == 'enabled_connected', timeout)


def wait_for_wifi_connected(adapter_name: str, timeout: int = 15, *, profile: str = '', ssid: str = '') -> bool:
    def connected():
        info = get_wifi_connection_info(adapter_name)
        return (info['state'] == 'connected' and (not profile or info.get('profile') == profile)
                and (not ssid or info.get('ssid') == ssid))
    return _wait_for(connected, timeout)


def wait_for_wifi_disconnected(adapter_name: str, timeout: int = 5) -> bool:
    return _wait_for(lambda: get_wifi_connection_status(adapter_name) == 'disconnected', timeout)


# ---------------------------------------------------------------------------
# 高层切换操作
# ---------------------------------------------------------------------------

def _serialize_network_change(action):
    @wraps(action)
    def guarded(*args, **kwargs):
        if not network_change_lock.acquire(blocking=False):
            return False, '网络切换或 FortiClient 代理助手正在运行，未改变网卡'
        try:
            return action(*args, **kwargs)
        finally:
            network_change_lock.release()
    return guarded


@dataclass(frozen=True)
class NetworkSnapshot:
    wifi_name: str
    ethernet_name: str
    wifi_adapter: str
    ethernet_adapter: str
    wifi_state: str
    wifi_profile: str = ''
    wifi_ssid: str = ''


def _capture_network_state() -> NetworkSnapshot:
    wifi, ethernet = CONFIG['wifi_adapter_name'], CONFIG['ethernet_adapter_name']
    wifi_status, ethernet_status = get_adapter_status(wifi), get_adapter_status(ethernet)
    known = {'disabled', 'enabled_connected', 'enabled_disconnected'}
    if wifi_status not in known or ethernet_status not in known:
        raise RuntimeError('无法确认网卡原状态，未开始切换')
    info = {'state': 'disconnected'} if wifi_status == 'disabled' else get_wifi_connection_info(wifi)
    if info['state'] == 'unknown' or (info['state'] == 'connected' and
                                     not (info.get('profile') and info.get('ssid'))):
        raise RuntimeError('无法保存原 WiFi 连接配置，未开始切换')
    return NetworkSnapshot(wifi, ethernet, wifi_status, ethernet_status,
                           info['state'], info.get('profile', ''), info.get('ssid', ''))


def _backup_wifi_profile(profile_name: str, adapter: str) -> bytes | None:
    # 不导出明文密钥；仅保留将被改写的 WorkPal 专用配置，其余配置不动。
    with tempfile.TemporaryDirectory(prefix='workpal_profiles_') as folder:
        ok, _ = _run_netsh(['wlan', 'export', 'profile', f'interface={adapter}', f'folder={folder}'])
        if not ok:
            raise RuntimeError('备份 WiFi 配置失败，未开始切换')
        for path in Path(folder).glob('*.xml'):
            data = path.read_bytes()
            root = ElementTree.fromstring(data)
            if root.findtext('{http://www.microsoft.com/networking/WLAN/profile/v1}name') == profile_name:
                return data
    return None


def _restore_wifi_profile(profile_name: str, data: bytes | None, adapter: str) -> bool:
    if data is None:
        # profile_name 由哈希生成，绝不把用户 SSID 当作删除通配符。
        return _run_netsh(['wlan', 'delete', 'profile', f'name={profile_name}', f'interface={adapter}'])[0]
    with tempfile.TemporaryDirectory(prefix='workpal_restore_') as folder:
        path = Path(folder) / 'profile.xml'
        path.write_bytes(data)
        return _run_netsh(['wlan', 'add', 'profile', f'filename={path}', f'interface={adapter}'])[0]


def _restore_network(snapshot: NetworkSnapshot, profile_name: str = '', profile_data: bytes | None = None) -> list[str]:
    errors = []

    def attempt(label, operation):
        try:
            if not operation():
                errors.append(label)
        except Exception:
            logger.exception('网络回滚失败：%s', label)
            errors.append(label)

    # 先撤销新连接/新配置，再恢复原网卡，避免错误配置自动重连。
    if profile_name or snapshot.wifi_state == 'disconnected':
        if get_adapter_status(snapshot.wifi_name) != 'disabled':
            attempt('断开新 WiFi 连接', lambda: disconnect_wifi(snapshot.wifi_name)
                    and wait_for_wifi_disconnected(snapshot.wifi_name))
    if profile_name:
        attempt('恢复 WiFi 配置', lambda: _restore_wifi_profile(profile_name, profile_data, snapshot.wifi_name))
    for name, state in ((snapshot.ethernet_name, snapshot.ethernet_adapter),
                        (snapshot.wifi_name, snapshot.wifi_adapter)):
        if state == 'disabled':
            attempt(f'禁用 {name}', lambda name=name: disable_adapter(name) and wait_for_adapter_disabled(name))
        else:
            attempt(f'启用 {name}', lambda name=name: enable_adapter(name) and wait_for_adapter_enabled(name))
    if snapshot.wifi_state == 'connected':
        attempt('恢复原 WiFi 连接', lambda: _run_netsh([
            'wlan', 'connect', f'name={snapshot.wifi_profile}', f'ssid={snapshot.wifi_ssid}',
            f'interface={snapshot.wifi_name}'])[0] and wait_for_wifi_connected(
                snapshot.wifi_name, profile=snapshot.wifi_profile, ssid=snapshot.wifi_ssid))
    if snapshot.ethernet_adapter == 'enabled_connected':
        attempt('恢复原有线连接', lambda: wait_for_adapter_connected(snapshot.ethernet_name))
    return errors


def _switch_network(target: str) -> tuple:
    from workpal.features.vpn_proxy import assistant
    if assistant.active:
        return False, 'FortiClient 代理助手正在运行，为保护 VPN 连接，未切换网卡；请先停止助手'
    profile_name, profile_data, changed_profile = '', None, False
    try:
        snapshot = _capture_network_state()
        if target == 'wifi':
            if not CONFIG['wifi_ssid'] or not CONFIG['wifi_password']:
                raise RuntimeError('WiFi 名称或密码未配置，未开始切换')
            profile_name = 'WorkPal-' + hashlib.sha256(CONFIG['wifi_ssid'].encode('utf-8')).hexdigest()[:24]
            profile_data = _backup_wifi_profile(profile_name, snapshot.wifi_name)
    except Exception as exc:
        return False, str(exc)

    def require(result, reason):
        if not result:
            raise RuntimeError(reason)

    try:
        if target == 'wifi':
            require(disable_adapter(snapshot.ethernet_name), '无法禁用有线网卡')
            require(wait_for_adapter_disabled(snapshot.ethernet_name, timeout=5), '有线网卡禁用超时')
            require(enable_adapter(snapshot.wifi_name), '无法启用 WiFi 网卡')
            require(wait_for_adapter_enabled(snapshot.wifi_name, timeout=5), 'WiFi 网卡启用超时')
            changed_profile = True
            require(connect_wifi(CONFIG['wifi_ssid'], CONFIG['wifi_password'], profile_name=profile_name),
                    'WiFi 连接命令执行失败')
            require(wait_for_wifi_connected(snapshot.wifi_name, profile=profile_name, ssid=CONFIG['wifi_ssid']),
                    '目标 WiFi 连接超时 (15s)')
        else:
            if snapshot.wifi_adapter != 'disabled':
                require(disconnect_wifi(snapshot.wifi_name), 'WiFi 断开命令执行失败')
                require(wait_for_wifi_disconnected(snapshot.wifi_name), 'WiFi 断开超时或状态未知')
            require(enable_adapter(snapshot.ethernet_name), '无法启用有线网卡')
            require(wait_for_adapter_enabled(snapshot.ethernet_name, timeout=5), '有线网卡启用超时')
            program = CONFIG.get('ethernet_program_path', '')
            if program:
                if Path(program).name.lower() == 'insic.exe':
                    # 已有检疫客户端继续运行，不再由代理守护接管它的状态。
                    if not check_process_running(program):
                        require(start_program(program), '验证程序启动失败')
                else:
                    require(kill_process(program), '原验证程序未能退出')
                    require(start_program(program), '验证程序启动失败')
            require(wait_for_adapter_connected(snapshot.ethernet_name), '有线网卡尚未连接，请检查网线')
        return True, ''
    except Exception as exc:
        logger.exception('网络切换失败，开始恢复原连接')
        try:
            errors = _restore_network(snapshot, profile_name if changed_profile else '', profile_data)
        except Exception:
            logger.exception('恢复原连接异常')
            errors = ['无法确认恢复结果']
        recovery = '已恢复原网络状态' if not errors else '回滚未完成：' + '、'.join(errors)
        return False, f'{exc}；{recovery}'


@_serialize_network_change
def switch_to_wifi() -> tuple:
    """禁用有线后连接 WiFi；失败恢复原状态，返回 (success, reason)。"""
    return _switch_network('wifi')


@_serialize_network_change
def switch_to_ethernet() -> tuple:
    """断开 WiFi 后连接有线；失败恢复原状态，返回 (success, reason)。"""
    return _switch_network('ethernet')
