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
from PIL import Image, ImageDraw, UnidentifiedImageError

import workpal.features.network as network
import workpal.features.keep_alive as keep_alive
from workpal.system import get_resource_path, exit_app

logger = logging.getLogger(__name__)

APP_NAME = 'WorkPal 工作助手'
VERSION = 'v1.2.4'

# 防止网络切换重入
_switch_lock = threading.Lock()
_autostart_lock = threading.Lock()

# 全局图标引用（供其他模块发送通知）
_icon_ref: pystray.Icon | None = None


def notify(title: str, message: str) -> None:
    """向系统托盘发送通知（可从其他模块调用）。"""
    if _icon_ref is not None:
        try:
            _icon_ref.notify(title=title, message=message)
        except Exception as exc:
            logger.warning(f'托盘通知失败: {exc}')
    else:
        logger.info(f'[通知] {title}: {message}')

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
    try:
        with Image.open(path) as image:
            return image.convert('RGBA')
    except (OSError, UnidentifiedImageError):
        logger.warning('图标不可用，使用内置备用图标：%s', path)
        colors = {'default': '#3c3c3c', 'wifi': '#1a73e8', 'ethernet': '#0f9d58',
                  'switching': '#f29900', 'alive': '#7b3fa0'}
        image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((2, 2, 61, 61), radius=12,
                               fill=colors.get(name, colors['default']))
        draw.line([(13, 19), (22, 45), (32, 28), (42, 45), (51, 19)],
                  fill='white', width=5)
        return image


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
    if not _switch_lock.acquire(blocking=False):
        icon.notify(title='请稍候', message='正在切换或恢复网络，完成后再退出')
        return
    try:
        _quit_when_idle(icon)
    finally:
        _switch_lock.release()


def _quit_when_idle(icon: pystray.Icon) -> None:
    from workpal.features.vpn_proxy import assistant
    if not assistant.stop():
        icon.notify(title='请稍候', message='正在停止代理检查，请稍后再次退出')
        return
    keep_alive.toggle_keep_alive(False)
    from workpal.features.session_events import session_events
    session_events.stop()
    icon.stop()
    exit_app()


def _on_autostart_toggle(icon: pystray.Icon, item) -> None:
    """后台启用/禁用开机自启动，避免阻塞托盘线程。"""
    if not _autostart_lock.acquire(blocking=False):
        icon.notify(title='开机自动启动', message='正在处理，请稍候…')
        return
    threading.Thread(
        target=_do_autostart_toggle,
        args=(icon,),
        daemon=True,
        name='autostart-toggle',
    ).start()


def _do_autostart_toggle(icon: pystray.Icon) -> None:
    try:
        from workpal.features import autostart

        status = autostart.get_cached_autostart_status()
        if status in (
            autostart.STATUS_UNKNOWN,
            autostart.STATUS_CHECKING,
            autostart.STATUS_FAILED,
        ):
            icon.notify(title='开机自动启动', message='正在确认当前状态，请稍候…')
            autostart.refresh_autostart_status_async(wait=True)
            status = autostart.get_cached_autostart_status()

        if status == autostart.STATUS_ENABLED:
            success, reason = autostart.disable_autostart()
            message = '已禁用开机自动启动' if success else f'禁用失败：{reason}'
        else:
            success, reason = autostart.enable_autostart()
            message = ('已更新自启动为当前程序' if status == autostart.STATUS_OUTDATED
                       else '已启用开机自动启动') if success else f'启用失败：{reason}'

        title = '开机自动启动 ✓' if success else '开机自动启动失败 ✗'
        icon.notify(title=title, message=message)
        icon.update_menu()
    finally:
        if _autostart_lock.locked():
            _autostart_lock.release()


def _autostart_status_label(item=None) -> str:
    try:
        from workpal.features import autostart
        status = autostart.get_cached_autostart_status()
    except Exception:
        status = 'failed'

    labels = {
        'enabled': '已开启',
        'disabled': '已关闭',
        'outdated': '需更新（点击修复）',
        'checking': '检测中',
        'failed': '失败',
        'unknown': '检测中',
    }
    return f'开机自动启动：{labels.get(status, "检测中")}'


def _on_keep_alive(icon: pystray.Icon, item) -> None:
    """切换保持在线状态。"""
    new_state = not keep_alive.is_active()
    keep_alive.toggle_keep_alive(new_state)

    if new_state:
        _set_icon(icon, 'alive')
        icon.notify(title='保持在线状态', message='✓ 已开启，将定期模拟按键防止空闲')
    else:
        mode = _current_network_mode()
        _set_icon(icon, mode if mode in ('wifi', 'ethernet') else 'default')
        icon.notify(title='保持在线状态', message='已关闭')

    icon.update_menu()


def _current_network_mode() -> str:
    """托盘刷新只读 IP Helper，不调用可能阻塞的 WMI/netsh。"""
    from workpal.config import CONFIG
    from workpal.features.adapter_status import read_adapters
    mode = 'unknown'
    try:
        connected = {x['friendly_name'] for x in read_adapters() if x['status'] == 2}
        if CONFIG['wifi_adapter_name'] in connected:
            mode = 'wifi'
        elif CONFIG['ethernet_adapter_name'] in connected:
            mode = 'ethernet'
    except OSError:
        logger.debug('无法更新网络菜单标签', exc_info=True)
    return mode


def _network_menu_label(item) -> str:
    mode = _current_network_mode()
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
                _set_icon(icon, _current_network_mode())
                icon.notify(title='网络切换', message=f'✗ 切换失败：{reason}')

        elif current_mode == 'ethernet':
            icon.notify(title='网络切换', message='正在切换到 WiFi...')
            success, reason = network.switch_to_wifi()
            if success:
                _set_icon(icon, 'wifi')
                icon.notify(title='网络切换', message='✓ 已切换到 WiFi')
            else:
                _set_icon(icon, _current_network_mode())
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


def _vpn_status_label(item=None) -> str:
    from workpal.features.vpn_proxy import assistant
    checked = f'（检查于 {assistant.last_checked}）' if assistant.last_checked else ''
    return assistant.status + checked


def _on_proxy_guard_start(icon: pystray.Icon, item) -> None:
    _start_proxy_guard(icon)


def _on_proxy_check(icon: pystray.Icon, item) -> None:
    _start_proxy_guard(icon, once=True)


def _interval_action(seconds: int):
    def action(icon, item):
        from workpal.config import set_config_value
        try:
            set_config_value('proxy_check_interval', str(seconds))
            _vpn_notify(icon, f'检查间隔已设为 {seconds // 60} 分钟，下次检查后使用新间隔')
        except Exception as exc:
            _vpn_notify(icon, f'保存检查间隔失败：{exc}')
    return action


def _interval_checked(seconds: int):
    def checked(item):
        from workpal.features.vpn_proxy import check_interval
        return check_interval() == seconds
    return checked


def _on_vpn_start(icon: pystray.Icon, item) -> None:
    _start_proxy_guard(icon, home=True)


def _start_proxy_guard(icon: pystray.Icon, *, home=False, once=False) -> None:
    from workpal.features.vpn_proxy import assistant
    if not _switch_lock.acquire(blocking=False):
        _vpn_notify(icon, '正在切换网络或代理，请完成后再开启检查')
        return
    try:
        assistant.start(lambda message: _vpn_notify(icon, message),
                        home=home, once=once, refresh=icon.update_menu)
    finally:
        _switch_lock.release()


def _on_script_proxy(icon: pystray.Icon, item) -> None:
    if not _switch_lock.acquire(blocking=False):
        _vpn_notify(icon, '正在切换网络或代理，请稍候')
        return
    threading.Thread(target=_do_script_proxy, args=(icon,), daemon=True,
                     name='script-proxy').start()


def _do_script_proxy(icon: pystray.Icon) -> None:
    """调用方持有切换锁，避免刚切到脚本又被并发开启的守护覆盖。"""
    from workpal.features.vpn_proxy import use_script_proxy
    try:
        use_script_proxy()
        _vpn_notify(icon, '脚本代理已开启、手动代理已关闭；需要时可手动开启代理守护')
    except Exception as exc:
        logger.exception('切换脚本代理失败')
        _vpn_notify(icon, f'切换脚本代理失败：{exc}')
    finally:
        _switch_lock.release()


def _vpn_notify(icon: pystray.Icon, message: str) -> None:
    notify('代理守护', message)
    try:
        icon.update_menu()
    except Exception:
        logger.exception('更新代理助手菜单失败')


def _on_vpn_stop(icon: pystray.Icon, item) -> None:
    from workpal.features.vpn_proxy import assistant

    def worker():
        if not assistant.stop():
            _vpn_notify(icon, '助手仍在结束状态查询，请稍候；没有操作 VPN 连接')
        icon.update_menu()

    threading.Thread(target=worker, daemon=True, name='vpn-proxy-stop').start()


def _on_vpn_restore(icon: pystray.Icon, item) -> None:
    from workpal.features.vpn_proxy import restore_backup
    if not _switch_lock.acquire(blocking=False):
        _vpn_notify(icon, '正在切换网络或代理，请稍候再恢复')
        return

    def worker():
        try:
            restore_backup()
            _vpn_notify(icon, '已恢复接管前的代理，FortiClient 配置和连接没有改变')
        except Exception as exc:
            _vpn_notify(icon, f'恢复失败：{exc}')
        finally:
            _switch_lock.release()

    threading.Thread(target=worker, daemon=True, name='vpn-proxy-restore').start()


def _vpn_active(item=None) -> bool:
    from workpal.features.vpn_proxy import assistant
    return assistant.active


def _build_menu() -> Menu:
    """构造托盘菜单；独立成函数便于测试 pystray 回调签名。"""
    return Menu(
        Item(
            '保持在线状态',
            action=_on_keep_alive,
            checked=lambda item: keep_alive.is_active(),
        ),
        Item(
            _network_menu_label,
            action=_on_switch_network,
        ),
        Item('代理守护', Menu(
            Item(_vpn_status_label, action=None, enabled=False),
            Item('开启脚本代理（关闭手动代理）', action=_on_script_proxy),
            Item('开启定时守护', action=_on_proxy_guard_start,
                 enabled=lambda item: not _vpn_active()),
            Item('立即检查并修复一次', action=_on_proxy_check),
            Item('检查间隔', Menu(*(
                Item(f'{seconds // 60} 分钟', action=_interval_action(seconds),
                     checked=_interval_checked(seconds), radio=True)
                for seconds in (60, 120, 300)
            ))),
            Item('在家连接 / 重新连接公司', action=_on_vpn_start),
            Item('暂停守护（保留当前代理）', action=_on_vpn_stop, enabled=_vpn_active),
            Item('恢复接管前的代理', action=_on_vpn_restore),
        )),
        Menu.SEPARATOR,
        Item(
            _autostart_status_label,
            action=_on_autostart_toggle,
        ),
        Item('帮助', Menu(
            Item('关于本软件', action=_on_about),
            Item(f'版本: {VERSION}', action=None, enabled=False),
        )),
        Item('退出', _on_quit),
    )


# ---------------------------------------------------------------------------
# 初始化
# ---------------------------------------------------------------------------

def _on_tray_setup(icon: pystray.Icon) -> None:
    """启动时只设置脚本代理，不自动开启守护或检疫流程。"""
    _switch_lock.acquire()
    icon.visible = True
    _do_script_proxy(icon)
    try:
        from workpal.features import autostart

        autostart.refresh_autostart_status_async(
            on_done=lambda: icon.update_menu(),
        )
    except Exception:
        logger.exception('启动时刷新自启动状态失败')
    from workpal.features.session_events import session_events
    from workpal.features.vpn_proxy import assistant
    session_events.start(assistant.request_resume_check)


def initial_tray() -> None:
    """初始化并运行系统托盘（阻塞直到退出）。"""
    global _icon_ref

    image = _load_icon('default')
    menu = _build_menu()

    icon = pystray.Icon(APP_NAME, image, APP_NAME, menu)
    _icon_ref = icon

    try:
        icon.run(setup=_on_tray_setup)
    finally:
        from workpal.features.session_events import session_events
        session_events.stop()
