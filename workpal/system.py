import sys
import os
from pathlib import Path


def is_frozen() -> bool:
    """判断是否为冻结程序（已打包为 exe）。"""
    return getattr(sys, 'frozen', False)


def get_user_data_path(relative_path: str = '') -> str:
    """返回稳定的用户数据目录，不受当前工作目录或打包模式影响。"""
    local_app_data = Path(
        os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')
    )
    base = local_app_data / 'WorkPal'
    base.mkdir(parents=True, exist_ok=True)
    return str(base / relative_path) if relative_path else str(base)
