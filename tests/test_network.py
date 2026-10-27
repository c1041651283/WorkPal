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


class TestUserDataPath(unittest.TestCase):

    def setUp(self):
        from workpal import config as cfg
        self._cfg = cfg

    def test_uses_localappdata_workpal_directory(self):
        from workpal.system import get_user_data_path

        with tempfile.TemporaryDirectory() as tmp, \
             patch.dict(os.environ, {'LOCALAPPDATA': tmp}):
            path = get_user_data_path('app.log')

        self.assertEqual(path, os.path.join(tmp, 'WorkPal', 'app.log'))

    def test_removed_application_settings_are_ignored(self):
        content = (
            "OA_URL=http://oa.example.test\n"
            "OA_USERNAME=legacy-user\n"
            "OA_PASSWORD=legacy-secret\n"
            "OA_AUTO_SCHEDULE=true\n"
        )
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.ini', delete=False, encoding='utf-8'
        ) as f:
            f.write(content)
            tmp = f.name
        try:
            self._cfg.load_config(config_file=tmp)
            self.assertFalse(any(key.startswith('oa_') for key in self._cfg.CONFIG))
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
        proc.exe.return_value = r'C:\some\app.exe'
        mock_psutil.process_iter.return_value = [proc]
        mock_psutil.NoSuchProcess = Exception
        mock_psutil.AccessDenied = Exception
        self.assertTrue(network.check_process_running('C:\\some\\app.exe'))

    @patch('workpal.features.network.psutil')
    def test_check_running_not_found(self, mock_psutil):
        from workpal.features import network
        proc = MagicMock()
        proc.info = {'name': 'other.exe'}
        proc.exe.return_value = r'C:\some\other.exe'
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


class TestConnectWifi(unittest.TestCase):
    """connect_wifi() 测试 —— XML 转义、错误处理、临时文件清理。"""

    @patch('workpal.features.network.os.remove')
    @patch('workpal.features.network.os.fdopen')
    @patch('workpal.features.network.tempfile.mkstemp')
    @patch('workpal.features.network._run_netsh')
    def test_xml_escaping_special_characters(self, mock_netsh, mock_mkstemp,
                                              _mock_fdopen, _mock_remove):
        """SSID 含 XML 特殊字符时正确转义，避免 XML 损坏。"""
        from workpal.features import network
        fd_mock = MagicMock()
        mock_mkstemp.return_value = (fd_mock, r'C:\Temp\test.xml')
        mock_netsh.side_effect = [(True, ''), (True, '')]

        network.connect_wifi('Test<Net>&"WiFi\'', 'p@ss<word>&')

        # 确认传给 netsh 的 XML 已被转义
        call_args = mock_netsh.call_args_list
        self.assertEqual(call_args[0][0][0], ['wlan', 'add', 'profile',
                          'filename=C:\\Temp\\test.xml', f"interface={network.CONFIG['wifi_adapter_name']}"])
        self.assertEqual(call_args[1][0][0], ['wlan', 'connect',
                          "name=Test<Net>&\"WiFi'", "ssid=Test<Net>&\"WiFi'",
                          f"interface={network.CONFIG['wifi_adapter_name']}"])
        from xml.etree import ElementTree
        xml = _mock_fdopen.return_value.__enter__.return_value.write.call_args.args[0]
        root = ElementTree.fromstring(xml)
        ns = {'w': 'http://www.microsoft.com/networking/WLAN/profile/v1'}
        self.assertEqual(root.findtext('w:SSIDConfig/w:SSID/w:name', namespaces=ns), 'Test<Net>&"WiFi\'')
        self.assertEqual(root.findtext('w:MSM/w:security/w:sharedKey/w:keyMaterial', namespaces=ns), 'p@ss<word>&')

    @patch('workpal.features.network.os.remove')
    @patch('workpal.features.network.os.fdopen')
    @patch('workpal.features.network.tempfile.mkstemp')
    @patch('workpal.features.network._run_netsh')
    def test_normal_ssid_no_escaping_needed(self, mock_netsh, mock_mkstemp,
                                             _mock_fdopen, _mock_remove):
        """正常 SSID/密码不受转义影响。"""
        from workpal.features import network
        fd_mock = MagicMock()
        mock_mkstemp.return_value = (fd_mock, r'C:\Temp\test.xml')
        mock_netsh.side_effect = [(True, ''), (True, '')]

        result = network.connect_wifi('MyWiFi', 'simplepass')
        self.assertTrue(result)

    @patch('workpal.features.network.os.remove')
    @patch('workpal.features.network.os.fdopen')
    @patch('workpal.features.network.tempfile.mkstemp')
    @patch('workpal.features.network._run_netsh')
    def test_add_profile_failure_returns_false(self, mock_netsh, mock_mkstemp,
                                                _mock_fdopen, _mock_remove):
        """add profile 失败时应返回 False，不尝试 connect。"""
        from workpal.features import network
        fd_mock = MagicMock()
        mock_mkstemp.return_value = (fd_mock, r'C:\Temp\test.xml')
        mock_netsh.side_effect = [(False, 'error')]  # add profile 失败

        result = network.connect_wifi('MyWiFi', 'pass')
        self.assertFalse(result)
        # 确认只调用了 add profile，没有调 connect
        self.assertEqual(len(mock_netsh.call_args_list), 1)

    @patch('workpal.features.network.os.path.exists', return_value=True)
    @patch('workpal.features.network.os.remove')
    @patch('workpal.features.network.os.fdopen')
    @patch('workpal.features.network.tempfile.mkstemp')
    @patch('workpal.features.network._run_netsh')
    def test_temp_file_cleaned_up_on_error(self, mock_netsh, mock_mkstemp,
                                            _mock_fdopen, mock_remove, _mock_exists):
        """发生异常时 finally 块确保临时文件被清理。"""
        from workpal.features import network
        fd_mock = MagicMock()
        mock_mkstemp.return_value = (fd_mock, r'C:\Temp\test.xml')
        mock_netsh.side_effect = RuntimeError('boom')

        result = network.connect_wifi('MyWiFi', 'pass')
        self.assertFalse(result)
        mock_remove.assert_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
