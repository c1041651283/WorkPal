"""测试期间把用户数据目录指向临时目录，避免读写真实的 %LOCALAPPDATA%\\WorkPal。"""

import atexit
import os
import shutil
import tempfile

# 必须在任何测试模块导入 workpal 之前设置：config 在导入时就会读取配置。
_user_data = tempfile.mkdtemp(prefix='workpal-tests-')
os.environ['LOCALAPPDATA'] = _user_data
# 界面测试不打开真实窗口
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
atexit.register(shutil.rmtree, _user_data, ignore_errors=True)

import pytest


@pytest.fixture(autouse=True)
def _no_real_proxy_writes(monkeypatch):
    """测试漏掉替身时直接失败，绝不读写本机真实的 Windows 代理设置。"""
    from workpal.features import vpn_proxy

    def refuse(*args, **kwargs):
        raise AssertionError('测试不得读写真实的 Windows 代理设置，请使用替身')

    monkeypatch.setattr(vpn_proxy, 'WindowsProxyStore', refuse)


@pytest.fixture(scope='session')
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
