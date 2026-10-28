"""
workpal/tray.py
托盘的业务动作，与界面无关。

界面（workpal/ui）实现 View 协议：notify 显示通知卡片，refresh 重新读取状态，quit 退出程序。
所有耗时操作在后台线程执行，View 的实现负责把调用转到界面线程。
  - threading.Lock 防止网络切换、代理操作重入
  - current_state() 汇总界面需要显示的全部状态
"""

import os
import subprocess
import sys
import threading
import time
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from workpal import __version__, config
from workpal.features import (
    adapter_status, autostart, keep_alive, network, session_events, tray_promotion, vpn_proxy,
)
from workpal.system import get_user_data_path, is_frozen

logger = logging.getLogger(__name__)

APP_NAME = 'WorkPal 工作助手'
VERSION = f'v{__version__}'

# 防止网络切换重入
_switch_lock = threading.Lock()
_autostart_lock = threading.Lock()
# 网络切换线程运行期间显示“切换中”，并记住切换目标
_switching = False
_switch_target: str | None = None
# 退出时通知后台线程（如托盘显示设置）结束
_stop_event = threading.Event()

# 记事本保存配置后自动重新加载：新版记事本会立即返回，不能靠等待进程退出判断
CONFIG_WATCH_SECONDS = 30 * 60
CONFIG_POLL_SECONDS = 1.0
_config_watch_lock = threading.Lock()
_config_watch_until = 0.0
_config_watcher: threading.Thread | None = None

INTERVAL_CHOICES = (60, 120, 300)


class View(Protocol):
    def notify(self, title: str, message: str = '', *, level: str = 'info',
               key: str | None = None) -> None:
        """显示通知；同一 key 的通知原地更新。level：info/success/error/progress。"""

    def refresh(self) -> None:
        """重新读取 current_state()，更新图标、悬停提示和菜单。"""

    def quit(self) -> None:
        """结束界面事件循环。"""


@dataclass(frozen=True)
class TrayState:
    mode: str                 # wifi / ethernet / unknown
    switching: bool
    switch_target: str | None
    keep_alive: bool
    guard_active: bool
    guard_status: str
    last_checked: str
    interval: int
    autostart: str            # enabled / disabled / outdated / checking / failed / unknown


_MODE_NAMES = {'wifi': 'WiFi', 'ethernet': '有线'}
# 代理守护的提示文字来自 vpn_proxy，含这些词时按错误样式显示
_ERROR_WORDS = ('失败', '无法', '不可达', '未找到', '已停止', '错误')
_AUTOSTART_LABELS = {
    'enabled': '已开启',
    'disabled': '已关闭',
    'outdated': '需更新',
    'checking': '检测中',
    'failed': '检测失败',
    'unknown': '检测中',
}


def current_state() -> TrayState:
    assistant = vpn_proxy.assistant
    try:
        autostart_status = autostart.get_cached_autostart_status()
    except Exception:
        autostart_status = 'failed'
    return TrayState(
        mode=_current_network_mode(),
        switching=_switching,
        switch_target=_switch_target,
        keep_alive=keep_alive.is_active(),
        guard_active=assistant.active,
        guard_status=assistant.status,
        last_checked=assistant.last_checked,
        interval=vpn_proxy.check_interval(),
        autostart=autostart_status,
    )


def icon_name(state: TrayState) -> str:
    """托盘图标的主体：切换中 > 网络模式；保持在线另用角标表示，不再盖住网络状态。"""
    if state.switching:
        return 'switching'
    return state.mode if state.mode in ('wifi', 'ethernet') else 'unknown'


def mode_name(mode: str) -> str:
    return _MODE_NAMES.get(mode, '未识别')


def autostart_label(status: str) -> str:
    return _AUTOSTART_LABELS.get(status, '检测中')


def target_name(target: str | None) -> str:
    """切换目标在提示中的叫法。"""
    return 'WiFi' if target == 'wifi' else '有线网络'


def is_error_message(text: str) -> bool:
    return any(word in text for word in _ERROR_WORDS)


def tooltip(state: TrayState) -> str:
    """鼠标悬停时显示的状态；Windows 限制 127 个字符。"""
    network_name = '切换中' if state.switching else mode_name(state.mode)
    alive = '开' if state.keep_alive else '关'
    text = f'{APP_NAME} {VERSION}\n网络：{network_name}　保持在线：{alive}\n代理：{state.guard_status}'
    return text[:127]


def _current_network_mode() -> str:
    """状态刷新只读 IP Helper，不调用可能阻塞的 WMI/netsh。"""
    mode = 'unknown'
    try:
        connected = {x['friendly_name'] for x in adapter_status.read_adapters() if x['status'] == 2}
        if config.CONFIG['wifi_adapter_name'] in connected:
            mode = 'wifi'
        elif config.CONFIG['ethernet_adapter_name'] in connected:
            mode = 'ethernet'
    except OSError:
        logger.debug('无法读取网络状态', exc_info=True)
    return mode


# ---------------------------------------------------------------------------
# 一般操作
# ---------------------------------------------------------------------------

def open_logs(view: View) -> None:
    try:
        os.startfile(get_user_data_path())
    except OSError as exc:
        view.notify('打开日志文件夹失败', str(exc), level='error')


def quit_app(view: View) -> None:
    """停止代理守护最多等待 20 秒，放到后台线程，避免界面无响应。"""
    if not _switch_lock.acquire(blocking=False):
        view.notify('请稍候', '正在切换或恢复网络，完成后再退出')
        return
    threading.Thread(target=_quit_and_release, args=(view,), daemon=True,
                     name='quit').start()


def _quit_and_release(view: View) -> None:
    try:
        _quit_when_idle(view)
    except Exception:
        logger.exception('退出失败')
        view.notify('退出失败', '请查看日志后重试', level='error')
    finally:
        _switch_lock.release()


def _quit_when_idle(view: View) -> None:
    if not vpn_proxy.assistant.stop():
        view.notify('请稍候', '正在停止代理检查，请稍后再次退出')
        return
    keep_alive.toggle_keep_alive(False)
    _stop_event.set()
    session_events.session_events.stop()
    # 界面事件循环结束后由 main() 释放单实例并正常退出。
    view.quit()


def toggle_autostart(view: View) -> None:
    """后台启用/禁用开机自启动，避免阻塞界面。"""
    if not _autostart_lock.acquire(blocking=False):
        view.notify('开机自动启动', '正在处理，请稍候…', key='autostart')
        return
    threading.Thread(
        target=_do_autostart_toggle,
        args=(view,),
        daemon=True,
        name='autostart-toggle',
    ).start()


def _do_autostart_toggle(view: View) -> None:
    try:
        status = autostart.get_cached_autostart_status()
        if status in (
            autostart.STATUS_UNKNOWN,
            autostart.STATUS_CHECKING,
            autostart.STATUS_FAILED,
        ):
            view.notify('开机自动启动', '正在确认当前状态，请稍候…', level='progress', key='autostart')
            autostart.refresh_autostart_status_async(wait=True)
            status = autostart.get_cached_autostart_status()

        if status == autostart.STATUS_ENABLED:
            success, reason = autostart.disable_autostart()
            message = '已禁用开机自动启动' if success else f'禁用失败：{reason}'
        else:
            success, reason = autostart.enable_autostart()
            message = ('已更新自启动为当前程序' if status == autostart.STATUS_OUTDATED
                       else '已启用开机自动启动') if success else f'启用失败：{reason}'

        view.notify('开机自动启动', message, level='success' if success else 'error', key='autostart')
        view.refresh()
    finally:
        if _autostart_lock.locked():
            _autostart_lock.release()


def edit_config(view: View) -> None:
    """用记事本打开配置文件；每次保存都自动重新加载，无需重启 WorkPal。"""
    global _config_watch_until, _config_watcher
    try:
        path = config.prepare_config_file(create=True)
        notepad = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'notepad.exe'
        subprocess.Popen([str(notepad), str(path)])
    except Exception as exc:
        logger.exception('打开配置文件失败')
        view.notify('打开配置文件失败', str(exc), level='error')
        return
    with _config_watch_lock:
        # 再次点击只延长监听时间，不重复启动线程。
        _config_watch_until = time.monotonic() + CONFIG_WATCH_SECONDS
        if _config_watcher is None or not _config_watcher.is_alive():
            _config_watcher = threading.Thread(target=_watch_config, args=(view, path),
                                               daemon=True, name='config-watch')
            _config_watcher.start()


def _read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def _watch_config(view: View, path: Path) -> None:
    global _config_watcher
    last = _read_bytes(path)
    while True:
        time.sleep(CONFIG_POLL_SECONDS)
        current = _read_bytes(path)
        if current is not None and current != last:
            last = current
            _reload_config(view)
        with _config_watch_lock:
            if time.monotonic() >= _config_watch_until:
                _config_watcher = None
                return


def _reload_config(view: View) -> None:
    try:
        config.reload_config()
        view.notify('配置文件', '已保存，新配置已生效', level='success', key='config')
        view.refresh()
    except Exception as exc:
        logger.exception('重新加载配置文件失败')
        view.notify('重新加载配置失败', str(exc), level='error', key='config')


def toggle_keep_alive(view: View) -> None:
    new_state = not keep_alive.is_active()
    keep_alive.toggle_keep_alive(new_state)
    view.refresh()
    if new_state:
        view.notify('保持在线已开启', '用户空闲时会定期模拟按键，防止显示离开', level='success',
                    key='keep-alive')
    else:
        view.notify('保持在线已关闭', key='keep-alive')


# ---------------------------------------------------------------------------
# 网络切换
# ---------------------------------------------------------------------------

def switch_network(view: View, target: str | None = None) -> None:
    """target 为空时按当前网络切到另一种；无法识别时由后台线程再判断一次。"""
    if target is None:
        target = {'wifi': 'ethernet', 'ethernet': 'wifi'}.get(_current_network_mode())
    _start_switch(view, target)


def _start_switch(view: View, target: str | None) -> None:
    """立即返回，切换在后台线程执行。"""
    if not _switch_lock.acquire(blocking=False):
        view.notify('请稍候', '正在切换网络或代理', key='network')
        return
    threading.Thread(
        target=_do_switch_and_release,
        args=(view, target),
        daemon=True,
        name='network-switch',
    ).start()


def _do_switch_and_release(view: View, target: str | None = None) -> None:
    """后台线程：执行切换，完成后释放锁并刷新界面。target 为空时按当前网络切到另一种。"""
    global _switching, _switch_target
    try:
        if target is None:
            current_mode = network.get_current_mode()
            logger.info(f"触发网络切换，当前模式: {current_mode}")
            target = {'wifi': 'ethernet', 'ethernet': 'wifi'}.get(current_mode)
            if target is None:
                view.notify('无法识别当前网络', '请在菜单的网络卡片中选择切换到 WiFi 或有线',
                            level='error', key='network')
                return
        _switching, _switch_target = True, target
        view.refresh()
        name = target_name(target)

        # 代理守护运行时会锁住网卡；先切回脚本代理（同时暂停守护）再切换。
        detail = ''
        if vpn_proxy.assistant.active:
            try:
                vpn_proxy.use_script_proxy()
            except Exception as exc:
                logger.exception('切换网络前切回脚本代理失败')
                view.notify('未切换网络', f'切回脚本代理失败：{exc}', level='error', key='network')
                return
            detail = '已暂停代理守护并切回脚本代理'

        view.notify(f'正在切换到{name}', detail, level='progress', key='network')
        switch = network.switch_to_wifi if target == 'wifi' else network.switch_to_ethernet
        success, reason = switch()
        if success:
            view.notify(f'已切换到{name}', detail, level='success', key='network')
        else:
            view.notify('切换失败', reason, level='error', key='network')
    except Exception as e:
        logger.exception('网络切换异常')
        view.notify('程序异常', str(e), level='error', key='network')
    finally:
        _switching, _switch_target = False, None
        _switch_lock.release()
        view.refresh()


# ---------------------------------------------------------------------------
# 代理守护
# ---------------------------------------------------------------------------

def start_guard(view: View) -> None:
    _start_proxy_guard(view)


def check_now(view: View) -> None:
    _start_proxy_guard(view, once=True)


def connect_home(view: View) -> None:
    _start_proxy_guard(view, home=True)


def set_interval(view: View, seconds: int) -> None:
    try:
        config.set_config_value('proxy_check_interval', str(seconds))
        _vpn_notify(view, f'检查间隔已设为 {seconds // 60} 分钟，下次检查后使用新间隔')
    except Exception as exc:
        _vpn_notify(view, f'保存检查间隔失败：{exc}')


def _start_proxy_guard(view: View, *, home=False, once=False) -> None:
    if not _switch_lock.acquire(blocking=False):
        _vpn_notify(view, '正在切换网络或代理，请完成后再开启检查')
        return
    try:
        vpn_proxy.assistant.start(lambda message: _vpn_notify(view, message),
                        home=home, once=once, refresh=view.refresh)
    finally:
        _switch_lock.release()


def use_script(view: View) -> None:
    if not _switch_lock.acquire(blocking=False):
        _vpn_notify(view, '正在切换网络或代理，请稍候')
        return
    threading.Thread(target=_do_script_proxy, args=(view,), daemon=True,
                     name='script-proxy').start()


def _do_script_proxy(view: View, *, notify_success: bool = True) -> None:
    """调用方持有切换锁，避免刚切到脚本又被并发开启的守护覆盖。启动时只在失败时通知。"""
    try:
        vpn_proxy.use_script_proxy()
        if notify_success:
            _vpn_notify(view, '脚本代理已开启、手动代理已关闭；需要时可手动开启代理守护')
        else:
            view.refresh()
    except Exception as exc:
        logger.exception('切换脚本代理失败')
        _vpn_notify(view, f'切换脚本代理失败：{exc}')
    finally:
        _switch_lock.release()


def _vpn_notify(view: View, message: str) -> None:
    level = 'error' if is_error_message(message) else 'info'
    view.notify('代理守护', message, level=level, key='proxy')
    try:
        view.refresh()
    except Exception:
        logger.exception('刷新代理守护状态失败')


def stop_guard(view: View) -> None:
    def worker():
        if not vpn_proxy.assistant.stop():
            _vpn_notify(view, '代理守护仍在结束状态查询，请稍候；没有操作 VPN 连接')
        view.refresh()

    threading.Thread(target=worker, daemon=True, name='vpn-proxy-stop').start()


# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------

def startup(view: View) -> None:
    """界面显示后在后台线程调用：设置脚本代理，不自动开启守护或检疫流程。"""
    _switch_lock.acquire()
    _do_script_proxy(view, notify_success=False)
    try:
        autostart.refresh_autostart_status_async(on_done=view.refresh)
    except Exception:
        logger.exception('启动时刷新自启动状态失败')
    session_events.session_events.start(vpn_proxy.assistant.request_resume_check)
    if is_frozen():
        # 源码运行时 python.exe 由多个程序共用，不自动修改它的托盘显示设置。
        threading.Thread(target=tray_promotion.promote_when_registered, args=(sys.executable, APP_NAME),
                         kwargs={'stop': _stop_event}, daemon=True,
                         name='tray-promotion').start()


def initial_tray() -> None:
    """初始化并运行托盘界面（阻塞直到退出）。"""
    from workpal.ui.app import run
    try:
        run()
    finally:
        session_events.session_events.stop()
