"""
workpal/features/keep_alive.py
保持在线状态功能。

通过两种机制防止系统息屏/睡眠并保持 Teams 在线状态：
1. 调用 Windows SetThreadExecutionState API，直接告知系统保持显示器开启并阻止睡眠。
2. 每隔 CHECK_INTERVAL 秒检查 Windows 真实空闲时长（GetLastInputInfo），
   当用户已空闲超过 IDLE_THRESHOLD 秒时，通过 SendInput 模拟 F15 键按下/释放，
   可靠重置系统空闲计时器，防止 Teams 等应用将状态切换为离线/空闲。

Teams 在 Windows 上依赖 GetLastInputInfo 判断用户是否活跃（官方文档：
https://learn.microsoft.com/en-us/microsoftteams/presence-admins），
SendInput 是重置该计时器的 Windows 保证手段。
"""

import ctypes
import ctypes.wintypes
import threading
import logging

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 30       # 检查空闲状态的间隔（秒）
IDLE_THRESHOLD = 180      # 超过此空闲秒数时才模拟按键（Teams 约 5 分钟后变 Away，取 3 分钟作为触发阈值）

# Windows SetThreadExecutionState 标志
_ES_CONTINUOUS       = 0x80000000
_ES_SYSTEM_REQUIRED  = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002

# SendInput 常量
_INPUT_KEYBOARD   = 1
_VK_F15           = 0x7E   # F15 虚拟键码，现代键盘上无实际功能
_KEYEVENTF_KEYUP  = 0x0002

_enabled = False
_thread: threading.Thread = None
_stop_event = threading.Event()
_lock = threading.Lock()


# ---------- Windows API 结构体 ----------

class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk",         ctypes.c_ushort),
        ("wScan",       ctypes.c_ushort),
        ("dwFlags",     ctypes.c_ulong),
        ("time",        ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_size_t),   # ULONG_PTR，64 位下为 8 字节
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx",          ctypes.c_long),
        ("dy",          ctypes.c_long),
        ("mouseData",   ctypes.c_ulong),
        ("dwFlags",     ctypes.c_ulong),
        ("time",        ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("_input", _INPUT_UNION)]


# ---------- 核心工具函数 ----------

def _get_idle_seconds() -> float:
    """返回 Windows 系统自上次用户输入起经过的秒数；查询失败返回 0。"""
    try:
        lii = _LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            tick_count = ctypes.windll.kernel32.GetTickCount
            tick_count.argtypes = []
            tick_count.restype = ctypes.wintypes.DWORD
            # 两个时间戳均为 DWORD，模减同时处理符号边界和 49.7 天回绕。
            return ((tick_count() - lii.dwTime) & 0xffffffff) / 1000.0
    except Exception as e:
        logger.warning(f"GetLastInputInfo 调用失败: {e}")
    return 0.0


def _simulate_f15_key() -> None:
    """通过 SendInput 模拟 F15 键按下/释放，重置 Windows 空闲计时器。"""
    try:
        key_down = _INPUT()
        key_down.type = _INPUT_KEYBOARD
        key_down._input.ki.wVk = _VK_F15

        key_up = _INPUT()
        key_up.type = _INPUT_KEYBOARD
        key_up._input.ki.wVk = _VK_F15
        key_up._input.ki.dwFlags = _KEYEVENTF_KEYUP

        inputs = (_INPUT * 2)(key_down, key_up)
        sent = ctypes.windll.user32.SendInput(2, inputs, ctypes.sizeof(_INPUT))
        if sent == 2:
            logger.debug("保持在线：已通过 SendInput(F15) 重置系统空闲计时器")
        else:
            logger.warning(f"SendInput 仅发送了 {sent}/2 个事件")
    except Exception as e:
        logger.warning(f"SendInput 调用失败: {e}")


def _set_execution_state(prevent_sleep: bool) -> None:
    """调用 Windows API 阻止或恢复系统息屏与睡眠。"""
    try:
        if prevent_sleep:
            ctypes.windll.kernel32.SetThreadExecutionState(
                _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED | _ES_DISPLAY_REQUIRED
            )
            logger.debug("SetThreadExecutionState：已阻止息屏和系统睡眠")
        else:
            ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS)
            logger.debug("SetThreadExecutionState：已恢复系统默认电源策略")
    except Exception as e:
        logger.warning(f"SetThreadExecutionState 调用失败: {e}")


def _keep_alive_loop(stop_event: threading.Event) -> None:
    global _thread, _enabled
    logger.info("保持在线循环已启动")
    try:
        _set_execution_state(True)
        while not stop_event.wait(timeout=CHECK_INTERVAL):
            idle = _get_idle_seconds()
            if idle >= IDLE_THRESHOLD and not stop_event.is_set():
                logger.debug(f"保持在线：检测到空闲 {idle:.0f}s，触发模拟按键")
                _simulate_f15_key()
            else:
                logger.debug(f"保持在线：用户仍活跃（空闲 {idle:.0f}s），跳过模拟")
    finally:
        _set_execution_state(False)
        logger.info("保持在线循环已停止")
        with _lock:
            if _thread is threading.current_thread():
                _thread = None
                if _enabled and stop_event.is_set():
                    # 关闭后立即开启的最后请求，由旧线程完成清理后接续。
                    _start_thread_locked()
                else:
                    _enabled = False


def _start_thread_locked() -> None:
    global _thread, _stop_event
    _stop_event = threading.Event()
    _thread = threading.Thread(target=_keep_alive_loop, args=(_stop_event,),
                               daemon=True, name='keep-alive')
    _thread.start()


def toggle_keep_alive(enable: bool) -> None:
    """开启或关闭保持在线功能。线程安全。"""
    global _enabled, _thread, _stop_event

    with _lock:
        _enabled = enable
        if enable:
            if _thread and _thread.is_alive():
                logger.debug("已记录开启请求，继续运行或等待旧线程清理")
                return
            _start_thread_locked()
            logger.info("保持在线已开启")
        else:
            _enabled = False
            _stop_event.set()
            logger.info("保持在线已关闭")


def is_active() -> bool:
    """返回当前保持在线是否处于激活状态。"""
    with _lock:
        return _enabled
