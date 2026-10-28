import json
import os
import logging
import sys
from pathlib import Path

from workpal.system import get_user_data_path, is_frozen

logger = logging.getLogger(__name__)

# 运行时配置字典（程序全局共享）
CONFIG: dict = {
    'wifi_adapter_name': 'WLAN',
    'ethernet_adapter_name': '以太网',
    'wifi_ssid': '',
    'ethernet_program_path': '',
    # FortiClient 代理助手：仅手动启动，不改变 VPN 自身的连接配置。
    'forticlient_path': '',
    'vpn_proxy_server': 'proxy.ricoh.co.jp:8080',
    'proxy_check_interval': '60',
    'office_pac_url': 'http://proxy.psh.com.cn/proxy-psh1.pac',
}

_KEY_MAP = {
    'WIFI_ADAPTER_NAME': 'wifi_adapter_name',
    'ETHERNET_ADAPTER_NAME': 'ethernet_adapter_name',
    'WIFI_SSID': 'wifi_ssid',
    'ETHERNET_PROGRAM_PATH': 'ethernet_program_path',
    'FORTICLIENT_PATH': 'forticlient_path',
    'VPN_PROXY_SERVER': 'vpn_proxy_server',
    'PROXY_CHECK_INTERVAL': 'proxy_check_interval',
    'OFFICE_PAC_URL': 'office_pac_url',
}

_DEFAULT_CONFIG_FILE = 'network_config.ini'
_USER_CONFIG_FILE = Path(get_user_data_path('settings.json'))


def load_config(config_file: str | Path | None = None) -> None:
    """
    从 INI 文件加载配置，文件不存在时保持默认值。
    格式：KEY=VALUE（不含 section，以 # 开头的行为注释）。
    """
    if config_file is None:
        base = Path(sys.executable).resolve().parent if is_frozen() else Path(__file__).resolve().parent.parent
        config_file = base / _DEFAULT_CONFIG_FILE
    if not os.path.exists(config_file):
        logger.warning(f"配置文件 {config_file} 不存在，使用默认配置")
        _load_user_overrides()
        return

    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' not in line:
                    continue
                key, _, value = line.partition('=')
                key = key.strip()
                value = value.strip()
                if key in _KEY_MAP:
                    CONFIG[_KEY_MAP[key]] = value
                elif key == 'WIFI_PASSWORD' and value:
                    # 不保留值；切换 WiFi 改用 Windows 已保存的配置。
                    logger.warning('WIFI_PASSWORD 已不再使用，建议从配置文件中删除这行明文密码')

        logger.info(
            f"配置加载成功 | WiFi 网卡={CONFIG['wifi_adapter_name']} "
            f"| 有线网卡={CONFIG['ethernet_adapter_name']}"
        )
    except Exception as e:
        logger.error(f"加载配置文件失败: {e}")

    _load_user_overrides()


def set_config_value(key: str, value: str) -> None:
    """更新运行时配置并写入用户覆盖文件。"""
    if key not in CONFIG:
        raise KeyError(f'未知配置项: {key}')

    overrides = _read_user_overrides()
    overrides[key] = str(value)
    _write_user_overrides(overrides)
    CONFIG[key] = str(value)


def _load_user_overrides() -> None:
    overrides = _read_user_overrides()
    for key, value in overrides.items():
        if key in CONFIG:
            CONFIG[key] = str(value)


def _read_user_overrides() -> dict:
    try:
        if not _USER_CONFIG_FILE.exists():
            return {}
        with open(_USER_CONFIG_FILE, 'r', encoding='utf-8') as f:
            value = json.load(f)
        return value if isinstance(value, dict) else {}
    except Exception as exc:
        logger.warning(f'读取用户配置失败: {exc}')
        return {}


def _write_user_overrides(overrides: dict) -> None:
    _USER_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _USER_CONFIG_FILE.with_suffix(_USER_CONFIG_FILE.suffix + '.tmp')
    with open(temp_path, 'w', encoding='utf-8') as f:
        json.dump(overrides, f, ensure_ascii=False, indent=2)
    os.replace(temp_path, _USER_CONFIG_FILE)


# 模块首次导入时自动加载
load_config()
