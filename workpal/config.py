import json
import os
import logging
import shutil
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
    # 代理守护：仅手动启动 FortiClient，不改变 VPN 自身的连接配置。
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

_DEFAULTS = dict(CONFIG)

_DEFAULT_CONFIG_FILE = 'network_config.ini'
_TEMPLATE_FILE = 'network_config.ini.example'
_USER_CONFIG_FILE = Path(get_user_data_path('settings.json'))


def config_path() -> Path:
    """配置文件的固定位置（%LOCALAPPDATA%\\WorkPal），与程序所在目录无关，重新打包后无需重填。"""
    return Path(get_user_data_path(_DEFAULT_CONFIG_FILE))


def _program_dir() -> Path:
    """打包后为 EXE 所在目录，源码运行时为项目根目录。"""
    return Path(sys.executable).resolve().parent if is_frozen() else Path(__file__).resolve().parent.parent


def _copy_file(source: Path, target: Path) -> None:
    temp_path = target.with_suffix(target.suffix + '.tmp')
    shutil.copyfile(source, temp_path)
    os.replace(temp_path, target)


def _write_blank_config(target: Path) -> None:
    """找不到模板时生成只含默认值的配置，供用户在记事本中修改。"""
    lines = ['# WorkPal 配置文件；在记事本中保存即可生效']
    lines += [f'{key}={_DEFAULTS[name]}' for key, name in _KEY_MAP.items()]
    temp_path = target.with_suffix(target.suffix + '.tmp')
    temp_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    os.replace(temp_path, target)


def prepare_config_file(*, create: bool = False) -> Path:
    """返回用户目录中的配置文件。

    首次使用时把程序目录中旧位置的 network_config.ini 复制过来（原文件保留）；
    create=True 且两处都没有配置时，用模板生成一份。
    """
    target = config_path()
    legacy = _program_dir() / _DEFAULT_CONFIG_FILE
    if target.exists():
        if legacy.is_file() and legacy.read_bytes() != target.read_bytes():
            logger.warning(f'{legacy} 已不再读取，当前配置位于 {target}；可删除旧文件')
        return target
    if legacy.is_file():
        _copy_file(legacy, target)
        logger.info(f'已将配置从 {legacy} 迁移到 {target}')
    elif create:
        template = _program_dir() / _TEMPLATE_FILE
        if template.is_file():
            _copy_file(template, target)
        else:
            _write_blank_config(target)
        logger.info(f'已创建配置文件 {target}')
    return target


def load_config(config_file: str | Path | None = None, *, base: dict | None = None) -> None:
    """
    从 INI 文件加载配置，文件不存在时保持默认值。
    格式：KEY=VALUE（不含 section，以 # 开头的行为注释）。
    先在副本中解析，最后一次性更新 CONFIG，后台线程不会读到只加载一半的配置。
    """
    values = dict(CONFIG if base is None else base)
    if config_file is None:
        try:
            config_file = prepare_config_file()
        except OSError as exc:
            logger.error(f'准备配置文件失败: {exc}')
            config_file = config_path()
    if not os.path.exists(config_file):
        logger.warning(f"配置文件 {config_file} 不存在，使用默认配置")
    else:
        try:
            # utf-8-sig：记事本保存的带 BOM 文件也能正确读取第一行。
            with open(config_file, 'r', encoding='utf-8-sig') as f:
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
                        values[_KEY_MAP[key]] = value
                    elif key == 'WIFI_PASSWORD' and value:
                        # 不保留值；切换 WiFi 改用 Windows 已保存的配置。
                        logger.warning('WIFI_PASSWORD 已不再使用，建议从配置文件中删除这行明文密码')

            logger.info(
                f"配置加载成功 | WiFi 网卡={values['wifi_adapter_name']} "
                f"| 有线网卡={values['ethernet_adapter_name']}"
            )
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")

    _load_user_overrides(values)
    CONFIG.update(values)


def reload_config() -> None:
    """从默认值开始重新读取配置文件和托盘设置，已删除的配置项回到默认值。"""
    load_config(base=_DEFAULTS)


def set_config_value(key: str, value: str) -> None:
    """更新运行时配置并写入用户覆盖文件。"""
    if key not in CONFIG:
        raise KeyError(f'未知配置项: {key}')

    overrides = _read_user_overrides()
    overrides[key] = str(value)
    _write_user_overrides(overrides)
    CONFIG[key] = str(value)


def _load_user_overrides(values: dict) -> None:
    overrides = _read_user_overrides()
    for key, value in overrides.items():
        if key in values:
            values[key] = str(value)


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
