import sys
import os
from pathlib import Path


def is_frozen() -> bool:
    """判断是否为冻结程序（已打包为 exe）。"""
    return getattr(sys, 'frozen', False)


def get_resource_path(relative_path: str) -> str:
    """
    获取资源文件的绝对路径。
    打包后从 sys._MEIPASS 读取，开发时从项目根目录读取。
    """
    if is_frozen():
        base = sys._MEIPASS
    else:
        # 项目根目录（workpal/ 的上一级）
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative_path)


def get_user_data_path(relative_path: str = '') -> str:
    """返回稳定的用户数据目录，不受当前工作目录或打包模式影响。"""
    local_app_data = Path(
        os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')
    )
    base = local_app_data / 'WorkPal'
    base.mkdir(parents=True, exist_ok=True)
    return str(base / relative_path) if relative_path else str(base)
