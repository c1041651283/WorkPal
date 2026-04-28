"""
tests/test_network.py
网络模块单元测试（不做真实网络操作，使用 mock）。
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestLoadConfig(unittest.TestCase):
    """workpal.config.load_config() 测试。"""

    def setUp(self):
        from workpal import config as cfg
        self._cfg = cfg
        # 每次测试前恢复默认配置
        cfg.CONFIG.update({
            'wifi_adapter_name': 'WLAN',
            'ethernet_adapter_name': '以太网',
            'wifi_ssid': '',
            'wifi_password': '',
            'ethernet_program_path': '',
        })

    def test_defaults_when_file_missing(self):
        """配置文件不存在时保持默认值。"""
        self._cfg.load_config(config_file='__non_existent__.ini')
        self.assertEqual(self._cfg.CONFIG['wifi_adapter_name'], 'WLAN')
        self.assertEqual(self._cfg.CONFIG['ethernet_adapter_name'], '以太网')
        self.assertEqual(self._cfg.CONFIG['wifi_ssid'], '')

    def test_parse_valid_file(self):
        """从合法配置文件加载所有字段。"""
        content = (
            "# comment\n"
            "WIFI_ADAPTER_NAME=WiFi\n"
            "ETHERNET_ADAPTER_NAME=Ethernet\n"
            "WIFI_SSID=TestNet\n"
            "WIFI_PASSWORD=secret123\n"
            "ETHERNET_PROGRAM_PATH=C:\\test\\app.exe\n"
        )
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.ini', delete=False, encoding='utf-8'
        ) as f:
            f.write(content)
            tmp = f.name
        try:
            self._cfg.load_config(config_file=tmp)
            self.assertEqual(self._cfg.CONFIG['wifi_adapter_name'], 'WiFi')
            self.assertEqual(self._cfg.CONFIG['ethernet_adapter_name'], 'Ethernet')
            self.assertEqual(self._cfg.CONFIG['wifi_ssid'], 'TestNet')
            self.assertEqual(self._cfg.CONFIG['wifi_password'], 'secret123')
            self.assertEqual(self._cfg.CONFIG['ethernet_program_path'], 'C:\\test\\app.exe')
        finally:
            os.unlink(tmp)

    def test_skip_comments_and_blank_lines(self):
        """注释行和空行不影响解析。"""
        content = "# this is a comment\n\nWIFI_SSID=MySSID\n"
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.ini', delete=False, encoding='utf-8'
        ) as f:
            f.write(content)
            tmp = f.name
        try:
            self._cfg.load_config(config_file=tmp)
            self.assertEqual(self._cfg.CONFIG['wifi_ssid'], 'MySSID')
        finally:
            os.unlink(tmp)

    def test_unknown_keys_ignored(self):
        """未知键不会影响 CONFIG 字典。"""
        content = "UNKNOWN_KEY=value\nWIFI_SSID=OK\n"
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.ini', delete=False, encoding='utf-8'
        ) as f:
            f.write(content)
            tmp = f.name
        try:
            self._cfg.load_config(config_file=tmp)
            self.assertNotIn('UNKNOWN_KEY', self._cfg.CONFIG)
            self.assertEqual(self._cfg.CONFIG['wifi_ssid'], 'OK')
        finally:
            os.unlink(tmp)


class TestGetCurrentMode(unittest.TestCase):
    """network.get_current_mode() 测试（mock WMI / netsh）。"""

    @patch('workpal.features.network.get_wifi_connection_status', return_value='connected')
    @patch('workpal.features.network.get_adapter_status', return_value='enabled_disconnected')
    def test_wifi_mode(self, _mock_eth, _mock_wifi):
        from workpal.features import network
        self.assertEqual(network.get_current_mode(), 'wifi')

    @patch('workpal.features.network.get_wifi_connection_status', return_value='disconnected')
    @patch('workpal.features.network.get_adapter_status', return_value='enabled_connected')
    def test_ethernet_mode(self, _mock_eth, _mock_wifi):
        from workpal.features import network
        self.assertEqual(network.get_current_mode(), 'ethernet')

    @patch('workpal.features.network.get_wifi_connection_status', return_value='disconnected')
    @patch('workpal.features.network.get_adapter_status', return_value='disabled')
    def test_unknown_mode(self, _mock_eth, _mock_wifi):
        from workpal.features import network
        self.assertEqual(network.get_current_mode(), 'unknown')

    @patch('workpal.features.network.get_wifi_connection_status', return_value='unknown')
    @patch('workpal.features.network.get_adapter_status', return_value='not_found')
    def test_unknown_mode_both_not_found(self, _mock_eth, _mock_wifi):
        from workpal.features import network
        self.assertEqual(network.get_current_mode(), 'unknown')


class TestProcessManagement(unittest.TestCase):
    """network.check_process_running / kill_process 测试（mock psutil）。"""

    @patch('workpal.features.network.psutil')
    def test_check_running_found(self, mock_psutil):
        from workpal.features import network
        proc = MagicMock()
        proc.info = {'name': 'app.exe'}
        mock_psutil.process_iter.return_value = [proc]
        mock_psutil.NoSuchProcess = Exception
        mock_psutil.AccessDenied = Exception
        self.assertTrue(network.check_process_running('C:\\some\\app.exe'))

    @patch('workpal.features.network.psutil')
    def test_check_running_not_found(self, mock_psutil):
        from workpal.features import network
        proc = MagicMock()
        proc.info = {'name': 'other.exe'}
        mock_psutil.process_iter.return_value = [proc]
        mock_psutil.NoSuchProcess = Exception
        mock_psutil.AccessDenied = Exception
        self.assertFalse(network.check_process_running('C:\\some\\app.exe'))

    @patch('workpal.features.network.psutil')
    def test_check_running_empty_path(self, _mock_psutil):
        from workpal.features import network
        self.assertFalse(network.check_process_running(''))

    @patch('workpal.features.network.psutil')
    def test_kill_process_empty_path(self, _mock_psutil):
        from workpal.features import network
        self.assertTrue(network.kill_process(''))


if __name__ == '__main__':
    unittest.main(verbosity=2)
