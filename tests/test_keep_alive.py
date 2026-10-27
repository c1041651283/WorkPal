"""
tests/test_keep_alive.py
保持在线模块单元测试（mock Windows API，不产生真实输入）。
"""

import os
import sys
import time
import threading
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestKeepAlive(unittest.TestCase):

    def setUp(self):
        # 每次测试前重置模块状态
        from workpal.features import keep_alive
        self._ka = keep_alive
        self.addCleanup(setattr, keep_alive, 'CHECK_INTERVAL', keep_alive.CHECK_INTERVAL)
        self.addCleanup(setattr, keep_alive, 'IDLE_THRESHOLD', keep_alive.IDLE_THRESHOLD)
        keep_alive.toggle_keep_alive(False)
        time.sleep(0.05)

    def tearDown(self):
        self._ka.toggle_keep_alive(False)
        if self._ka._thread:
            self._ka._thread.join(timeout=2)

    @patch('workpal.features.keep_alive._simulate_f15_key')
    @patch('workpal.features.keep_alive._set_execution_state')
    @patch('workpal.features.keep_alive._get_idle_seconds', return_value=0.0)
    def test_toggle_on_starts_thread(self, _mock_idle, _mock_state, _mock_key):
        self._ka.toggle_keep_alive(True)
        time.sleep(0.1)
        self.assertTrue(self._ka.is_active())
        self.assertIsNotNone(self._ka._thread)
        self.assertTrue(self._ka._thread.is_alive())

    @patch('workpal.features.keep_alive._simulate_f15_key')
    @patch('workpal.features.keep_alive._set_execution_state')
    @patch('workpal.features.keep_alive._get_idle_seconds', return_value=0.0)
    def test_toggle_off_sets_flag(self, _mock_idle, _mock_state, _mock_key):
        self._ka.toggle_keep_alive(True)
        time.sleep(0.1)
        self._ka.toggle_keep_alive(False)
        self.assertFalse(self._ka.is_active())

    @patch('workpal.features.keep_alive._simulate_f15_key')
    @patch('workpal.features.keep_alive._set_execution_state')
    @patch('workpal.features.keep_alive._get_idle_seconds', return_value=0.0)
    def test_double_toggle_on_no_duplicate_thread(self, _mock_idle, _mock_state, _mock_key):
        """连续两次开启不会创建第二个线程。"""
        self._ka.toggle_keep_alive(True)
        time.sleep(0.1)
        thread1 = self._ka._thread
        self._ka.toggle_keep_alive(True)
        time.sleep(0.1)
        thread2 = self._ka._thread
        self.assertIs(thread1, thread2)

    def test_is_active_false_initially(self):
        """初始状态为非激活。"""
        self.assertFalse(self._ka.is_active())

    @patch('workpal.features.keep_alive._simulate_f15_key')
    @patch('workpal.features.keep_alive._set_execution_state')
    @patch('workpal.features.keep_alive._get_idle_seconds', return_value=0.0)
    def test_toggle_on_off_on(self, _mock_idle, _mock_state, _mock_key):
        """开 → 关 → 开，第二次开启应创建新线程。"""
        self._ka.toggle_keep_alive(True)
        time.sleep(0.1)
        thread1 = self._ka._thread
        self._ka.toggle_keep_alive(False)
        time.sleep(0.1)
        self._ka.toggle_keep_alive(True)
        time.sleep(0.1)
        thread2 = self._ka._thread
        self.assertIsNot(thread1, thread2)
        self.assertTrue(self._ka.is_active())

    @patch('workpal.features.keep_alive._simulate_f15_key')
    @patch('workpal.features.keep_alive._set_execution_state')
    @patch('workpal.features.keep_alive._get_idle_seconds', return_value=200.0)
    def test_simulates_key_when_idle(self, _mock_idle, _mock_state, mock_key):
        """当空闲时长超过阈值时，应触发模拟按键。"""
        self._ka.IDLE_THRESHOLD = 180
        self._ka.CHECK_INTERVAL = 0  # 立即触发
        self._ka.toggle_keep_alive(True)
        time.sleep(0.2)
        self._ka.toggle_keep_alive(False)
        mock_key.assert_called()


    @patch('workpal.features.keep_alive._simulate_f15_key')
    @patch('workpal.features.keep_alive._set_execution_state')
    @patch('workpal.features.keep_alive._get_idle_seconds', return_value=0.0)
    def test_toggle_thread_safety(self, _mock_idle, _mock_state, _mock_key):
        """多线程并发调用 toggle 应只创建一个后台线程。"""
        errors = []
        start_event = threading.Event()

        def _toggle():
            try:
                start_event.wait()
                self._ka.toggle_keep_alive(True)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_toggle) for _ in range(10)]
        for t in threads:
            t.start()
        start_event.set()
        for t in threads:
            t.join(timeout=2)
        time.sleep(0.2)

        self.assertFalse(errors, f"并发调用中出现异常: {errors}")
        self.assertTrue(self._ka.is_active())
        # 确认 lock 属性存在（修复 #9 引入）
        self.assertTrue(hasattr(self._ka, '_lock'))

    @patch('workpal.features.keep_alive._simulate_f15_key')
    @patch('workpal.features.keep_alive._set_execution_state')
    @patch('workpal.features.keep_alive._get_idle_seconds', return_value=0.0)
    def test_lock_is_released_after_toggle(self, _mock_idle, _mock_state, _mock_key):
        """toggle_keep_alive 调用后锁应被释放，允许后续操作。"""
        # 应能正常连续调用不会死锁
        for _ in range(10):
            self._ka.toggle_keep_alive(True)
            self._ka.toggle_keep_alive(False)


if __name__ == '__main__':
    unittest.main(verbosity=2)
