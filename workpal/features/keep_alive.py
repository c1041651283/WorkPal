"""
workpal/features/keep_alive.py
保持在线状态功能。

每隔 INTERVAL_SECONDS 秒移动鼠标 1 像素再归位，
模拟用户活动，防止 Teams/系统进入空闲/离线状态。
"""

import threading
import time
import logging

import pyautogui

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 60  # 保持活跃的轮询间隔（秒）

_enabled = False
_thread: threading.Thread = None
_stop_event = threading.Event()


def _keep_alive_loop() -> None:
    logger.info("保持在线循环已启动")
    while not _stop_event.wait(timeout=INTERVAL_SECONDS):
        try:
            x, y = pyautogui.position()
            pyautogui.moveRel(1, 0, duration=0.05)
            pyautogui.moveRel(-1, 0, duration=0.05)
            logger.debug(f"保持在线：已模拟鼠标活动 (原位置 {x},{y})")
        except Exception as e:
            logger.warning(f"保持在线操作失败: {e}")
    logger.info("保持在线循环已停止")


def toggle_keep_alive(enable: bool) -> None:
    """开启或关闭保持在线功能。线程安全。"""
    global _enabled, _thread, _stop_event

    if enable:
        if _thread and _thread.is_alive():
            logger.debug("保持在线已在运行中，忽略重复开启")
            return
        _enabled = True
        _stop_event.clear()
        _thread = threading.Thread(
            target=_keep_alive_loop,
            daemon=True,
            name="keep-alive",
        )
        _thread.start()
        logger.info("保持在线已开启")
    else:
        _enabled = False
        _stop_event.set()
        logger.info("保持在线已关闭")


def is_active() -> bool:
    """返回当前保持在线是否处于激活状态。"""
    return _enabled
