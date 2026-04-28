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

import wmi as _wmi_module
import psutil

from workpal.config import CONFIG

logger = logging.getLogger(__name__)

# WMI 连接实例（懒加载）
_wmi_conn = None


def _get_wmi():
    global _wmi_conn
    if _wmi_conn is None:
        _wmi_conn = _wmi_module.WMI()
    return _wmi_conn


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
    返回: 'enabled_connected' | 'enabled_disconnected' | 'disabled' | 'not_found'

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
        elif status in (4, 5, 6):
            return 'disabled'
        else:
            return 'disabled'
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

def get_wifi_connection_status(adapter_name: str) -> str:
    """
    获取 WiFi 连接状态。
    返回: 'connected' | 'disconnected' | 'unknown'
    """
    try:
        success, output = _run_netsh(['wlan', 'show', 'interfaces'])
        if not success or not output:
            return 'unknown'

        current_name = None
        current_state = None
        states: dict = {}

        for line in output.splitlines():
            line_strip = line.strip()
            if not line_strip:
                if current_name and current_state:
                    states[current_name] = current_state
                current_name = None
                current_state = None
                continue
            if ':' not in line_strip:
                continue
            key, _, value = line_strip.partition(':')
            key = key.strip().lower()
            value = value.strip()
            if key in ('name', '名称', 'interface name', '接口名称'):
                current_name = value
            elif key in ('state', '状态'):
                current_state = value

        if current_name and current_state:
            states[current_name] = current_state

        target_state = states.get(adapter_name)
        if not target_state and len(states) == 1:
            target_state = next(iter(states.values()))
        if not target_state:
            return 'unknown'

        sv = target_state.lower()
        if ('已连接' in sv or 'connected' in sv) and 'disconnected' not in sv and '已断开' not in sv:
            return 'connected'
        if '已断开' in sv or 'disconnected' in sv or 'not connected' in sv or '未连接' in sv:
            return 'disconnected'
        if 'not ready' in sv or '不可用' in sv or '已禁用' in sv:
            return 'disconnected'
        return 'unknown'
    except Exception as e:
        logger.error(f"获取 WiFi 连接状态失败: {e}")
        return 'unknown'


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
    if ethernet_status.startswith('enabled'):
        return 'ethernet'
    return 'unknown'


def connect_wifi(ssid: str, password: str) -> bool:
    """通过 netsh wlan 临时配置文件连接 WiFi。"""
    logger.info(f"连接 WiFi: {ssid}")
    profile_xml = (
        '<?xml version="1.0"?>'
        '<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">'
        f'<name>{ssid}</name>'
        '<SSIDConfig><SSID>'
        f'<name>{ssid}</name>'
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
        f'<keyMaterial>{password}</keyMaterial>'
        '</sharedKey></security></MSM>'
        '</WLANProfile>'
    )
    profile_path = os.path.join(os.getenv('TEMP', os.getcwd()), 'workpal_wifi_profile.xml')
    try:
        with open(profile_path, 'w', encoding='utf-8') as f:
            f.write(profile_xml)
        _run_netsh(['wlan', 'add', 'profile', f'filename={profile_path}'])
        success, _ = _run_netsh(['wlan', 'connect', f'name={ssid}'])
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
    process_name = os.path.basename(program_path).lower()
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'] and proc.info['name'].lower() == process_name:
                logger.info(f"进程已在运行: {process_name}")
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def kill_process(program_path: str) -> bool:
    """终止指定程序的所有进程（psutil）。"""
    if not program_path:
        return True
    process_name = os.path.basename(program_path).lower()
    killed = False
    for proc in psutil.process_iter(['name', 'pid']):
        try:
            if proc.info['name'] and proc.info['name'].lower() == process_name:
                logger.info(f"终止进程: {process_name} (pid={proc.pid})")
                proc.kill()
                killed = True
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            logger.warning(f"终止进程失败 [{process_name}]: {e}")
    return killed


def start_program(program_path: str) -> bool:
    """启动外部程序。"""
    if not os.path.exists(program_path):
        logger.error(f"程序不存在: {program_path}")
        return False
    try:
        logger.info(f"启动程序: {program_path}")
        subprocess.Popen([program_path], shell=False)
        return True
    except Exception as e:
        logger.error(f"启动程序失败: {e}")
        return False


# ---------------------------------------------------------------------------
# 状态轮询等待
# ---------------------------------------------------------------------------

def _wait_for(check_fn, timeout: int, interval: float = 1.0) -> bool:
    """通用轮询等待，直到 check_fn() 返回 True 或超时。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if check_fn():
            return True
        time.sleep(interval)
    return False


def wait_for_adapter_disabled(adapter_name: str, timeout: int = 10) -> bool:
    return _wait_for(lambda: get_adapter_status(adapter_name) == 'disabled', timeout)


def wait_for_adapter_enabled(adapter_name: str, timeout: int = 10) -> bool:
    return _wait_for(lambda: get_adapter_status(adapter_name).startswith('enabled'), timeout)


def wait_for_wifi_connected(adapter_name: str, timeout: int = 15) -> bool:
    return _wait_for(lambda: get_wifi_connection_status(adapter_name) == 'connected', timeout)


def wait_for_wifi_disconnected(adapter_name: str, timeout: int = 5) -> bool:
    return _wait_for(lambda: get_wifi_connection_status(adapter_name) != 'connected', timeout)


# ---------------------------------------------------------------------------
# 高层切换操作
# ---------------------------------------------------------------------------

def switch_to_wifi() -> tuple:
    """
    切换到 WiFi 模式：禁用有线 → 连接 WiFi。
    返回 (success: bool, reason: str)。
    """
    logger.info("====== 开始切换到 WiFi 模式 ======")

    logger.info("[步骤1] 禁用有线网卡...")
    if not disable_adapter(CONFIG['ethernet_adapter_name']):
        return False, "无法禁用有线网卡"
    if not wait_for_adapter_disabled(CONFIG['ethernet_adapter_name'], timeout=5):
        return False, "有线网卡未能在 5 秒内禁用"

    logger.info("[步骤2] 连接 WiFi...")
    if not connect_wifi(CONFIG['wifi_ssid'], CONFIG['wifi_password']):
        return False, "WiFi 连接命令执行失败"
    if not wait_for_wifi_connected(CONFIG['wifi_adapter_name'], timeout=15):
        return False, "WiFi 连接超时 (15s)，可能密码错误或信号较弱"

    logger.info("====== ✓ 成功切换到 WiFi 模式 ======")
    return True, ''


def switch_to_ethernet() -> tuple:
    """
    切换到有线模式：断开 WiFi → 启用有线 → 等待就绪 → 重启验证程序。
    返回 (success: bool, reason: str)。
    """
    logger.info("====== 开始切换到有线模式 ======")

    logger.info("[步骤1] 断开 WiFi...")
    disconnect_wifi(CONFIG['wifi_adapter_name'])
    if not wait_for_wifi_disconnected(CONFIG['wifi_adapter_name'], timeout=5):
        return False, "WiFi 未能在 5 秒内断开"

    logger.info("[步骤2] 启用有线网卡...")
    if not enable_adapter(CONFIG['ethernet_adapter_name']):
        return False, "无法启用有线网卡"
    if not wait_for_adapter_enabled(CONFIG['ethernet_adapter_name'], timeout=5):
        return False, "有线网卡未能在 5 秒内启用"

    logger.info("[步骤3] 等待网络就绪 (5s)...")
    time.sleep(5)

    prog_path = CONFIG.get('ethernet_program_path', '')
    if prog_path:
        logger.info("[步骤4] 重新启动验证程序...")
        kill_process(prog_path)
        if not start_program(prog_path):
            return False, "验证程序启动失败"

    logger.info("====== ✓ 成功切换到有线模式 ======")
    return True, ''
