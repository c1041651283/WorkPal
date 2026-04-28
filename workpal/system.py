import sys
import os


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


def exit_app() -> None:
    """退出程序。"""
    sys.exit(0)
