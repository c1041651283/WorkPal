"""
tests/test_keep_alive.py
保持在线模块单元测试（mock pyautogui，不移动真实鼠标）。
"""

import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestKeepAlive(unittest.TestCase):

    def setUp(self):
        # 每次测试前重置模块状态
        from workpal.features import keep_alive
        self._ka = keep_alive
        keep_alive.toggle_keep_alive(False)
        time.sleep(0.05)

    def tearDown(self):
        self._ka.toggle_keep_alive(False)
        time.sleep(0.05)

    @patch('workpal.features.keep_alive.pyautogui')
    def test_toggle_on_starts_thread(self, mock_pag):
        mock_pag.position.return_value = (100, 100)
        self._ka.toggle_keep_alive(True)
        time.sleep(0.1)
        self.assertTrue(self._ka.is_active())
        self.assertIsNotNone(self._ka._thread)
        self.assertTrue(self._ka._thread.is_alive())

    @patch('workpal.features.keep_alive.pyautogui')
    def test_toggle_off_sets_flag(self, mock_pag):
        mock_pag.position.return_value = (100, 100)
        self._ka.toggle_keep_alive(True)
        time.sleep(0.1)
        self._ka.toggle_keep_alive(False)
        self.assertFalse(self._ka.is_active())

    @patch('workpal.features.keep_alive.pyautogui')
    def test_double_toggle_on_no_duplicate_thread(self, mock_pag):
        """连续两次开启不会创建第二个线程。"""
        mock_pag.position.return_value = (100, 100)
        self._ka.toggle_keep_alive(True)
        time.sleep(0.1)
        thread1 = self._ka._thread
        self._ka.toggle_keep_alive(True)
        time.sleep(0.1)
        thread2 = self._ka._thread
        self.assertIs(thread1, thread2)

    @patch('workpal.features.keep_alive.pyautogui')
    def test_is_active_false_initially(self, _mock_pag):
        """初始状态为非激活。"""
        self.assertFalse(self._ka.is_active())

    @patch('workpal.features.keep_alive.pyautogui')
    def test_toggle_on_off_on(self, mock_pag):
        """开 → 关 → 开，第二次开启应创建新线程。"""
        mock_pag.position.return_value = (100, 100)
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
