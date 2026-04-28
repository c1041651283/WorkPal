"""
workpal/tray.py
系统托盘入口。

改进点：
  - 网络切换在后台线程执行，不阻塞托盘
  - threading.Lock 防止重入
  - 动态菜单标签显示当前网络模式
  - 5 种图标随状态自动切换
  - 通知附带失败原因
"""

import threading
import logging

import pystray
from pystray import Menu, MenuItem as Item
from PIL import Image

import workpal.features.network as network
import workpal.features.keep_alive as keep_alive
from workpal.system import get_resource_path, exit_app

logger = logging.getLogger(__name__)

APP_NAME = 'WorkPal 工作助手'
VERSION = 'v1.0.0'

# 防止网络切换重入
_switch_lock = threading.Lock()

# 图标资源路径映射
_ICON_PATHS = {
    'default':   'assets/icon_default.ico',
    'wifi':      'assets/icon_wifi.ico',
    'ethernet':  'assets/icon_ethernet.ico',
    'switching': 'assets/icon_switching.ico',
    'alive':     'assets/icon_alive.ico',
}


def _load_icon(name: str) -> Image.Image:
    path = get_resource_path(_ICON_PATHS.get(name, _ICON_PATHS['default']))
    return Image.open(path)


def _set_icon(icon: pystray.Icon, name: str) -> None:
    try:
        icon.icon = _load_icon(name)
    except Exception as e:
        logger.warning(f"切换图标失败 [{name}]: {e}")


# ---------------------------------------------------------------------------
# 菜单回调
# ---------------------------------------------------------------------------

def _on_about(icon: pystray.Icon, item) -> None:
    icon.notify(
        title=f'关于 {APP_NAME}',
        message=f'{APP_NAME} {VERSION}\n本软件仅供个人学习使用。',
    )


def _on_quit(icon: pystray.Icon, item) -> None:
    keep_alive.toggle_keep_alive(False)
    icon.stop()
    exit_app()


def _on_keep_alive(icon: pystray.Icon, item) -> None:
    """切换保持在线状态。"""
    new_state = not keep_alive.is_active()
    keep_alive.toggle_keep_alive(new_state)

    if new_state:
        _set_icon(icon, 'alive')
        icon.notify(title='保持在线状态', message='✓ 已开启，将定期模拟鼠标活动')
    else:
        mode = network.get_current_mode()
        _set_icon(icon, mode if mode in ('wifi', 'ethernet') else 'default')
        icon.notify(title='保持在线状态', message='已关闭')

    icon.update_menu()


def _network_menu_label(item) -> str:
    """动态菜单标签，实时显示当前网络模式。"""
    mode = network.get_current_mode()
    labels = {'wifi': 'WiFi ✓', 'ethernet': '有线 ✓', 'unknown': '未知'}
    return f'网络切换  [{labels.get(mode, "?")}]'


def _on_switch_network(icon: pystray.Icon, item) -> None:
    """菜单回调：非阻塞，立即返回，切换在后台线程执行。"""
    if not _switch_lock.acquire(blocking=False):
        icon.notify(title='网络切换', message='⏳ 正在切换中，请稍候...')
        return
    threading.Thread(
        target=_do_switch_and_release,
        args=(icon,),
        daemon=True,
        name='network-switch',
    ).start()


def _do_switch_and_release(icon: pystray.Icon) -> None:
    """后台线程：执行切换，完成后释放锁并更新图标。"""
    try:
        current_mode = network.get_current_mode()
        logger.info(f"触发网络切换，当前模式: {current_mode}")
        _set_icon(icon, 'switching')

        if current_mode == 'wifi':
            icon.notify(title='网络切换', message='正在切换到有线网络...')
            success, reason = network.switch_to_ethernet()
            if success:
                _set_icon(icon, 'ethernet')
                icon.notify(title='网络切换', message='✓ 已切换到有线网络')
            else:
                _set_icon(icon, 'wifi')
                icon.notify(title='网络切换', message=f'✗ 切换失败：{reason}')

        elif current_mode == 'ethernet':
            icon.notify(title='网络切换', message='正在切换到 WiFi...')
            success, reason = network.switch_to_wifi()
            if success:
                _set_icon(icon, 'wifi')
                icon.notify(title='网络切换', message='✓ 已切换到 WiFi')
            else:
                _set_icon(icon, 'ethernet')
                icon.notify(title='网络切换', message=f'✗ 切换失败：{reason}')

        else:
            _set_icon(icon, 'default')
            icon.notify(title='网络切换', message='✗ 无法识别当前网络状态，请手动检查')

        icon.update_menu()
    except Exception as e:
        logger.error(f"网络切换异常: {e}")
        icon.notify(title='错误', message=f'程序异常: {e}')
    finally:
        _switch_lock.release()


# ---------------------------------------------------------------------------
# 初始化
# ---------------------------------------------------------------------------

def initial_tray() -> None:
    """初始化并运行系统托盘（阻塞直到退出）。"""
    image = _load_icon('default')

    menu = Menu(
        Item(
            '保持在线状态',
            action=_on_keep_alive,
            checked=lambda item: keep_alive.is_active(),
        ),
        Item(
            _network_menu_label,
            action=_on_switch_network,
        ),
        Menu.SEPARATOR,
        Item('帮助', Menu(
            Item('关于本软件', action=_on_about),
            Item(f'版本: {VERSION}', action=None, enabled=False),
        )),
        Item('退出', _on_quit),
    )

    icon = pystray.Icon(APP_NAME, image, APP_NAME, menu)
    icon.run()
