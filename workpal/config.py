import os
import logging

logger = logging.getLogger(__name__)

# 运行时配置字典（程序全局共享）
CONFIG: dict = {
    'wifi_adapter_name': 'WLAN',
    'ethernet_adapter_name': '以太网',
    'wifi_ssid': '',
    'wifi_password': '',
    'ethernet_program_path': '',
}

_KEY_MAP = {
    'WIFI_ADAPTER_NAME': 'wifi_adapter_name',
    'ETHERNET_ADAPTER_NAME': 'ethernet_adapter_name',
    'WIFI_SSID': 'wifi_ssid',
    'WIFI_PASSWORD': 'wifi_password',
    'ETHERNET_PROGRAM_PATH': 'ethernet_program_path',
}

_DEFAULT_CONFIG_FILE = 'network_config.ini'


def load_config(config_file: str = _DEFAULT_CONFIG_FILE) -> None:
    """
    从 INI 文件加载配置，文件不存在时保持默认值。
    格式：KEY=VALUE（不含 section，以 # 开头的行为注释）。
    """
    if not os.path.exists(config_file):
        logger.warning(f"配置文件 {config_file} 不存在，使用默认配置")
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

        logger.info(
            f"配置加载成功 | WiFi 网卡={CONFIG['wifi_adapter_name']} "
            f"| 有线网卡={CONFIG['ethernet_adapter_name']} "
            f"| SSID={CONFIG['wifi_ssid']}"
        )
    except Exception as e:
        logger.error(f"加载配置文件失败: {e}")


# 模块首次导入时自动加载
load_config()
