import logging
from logging.handlers import RotatingFileHandler

from workpal.system import get_user_data_path, is_frozen


def _setup_logging() -> None:
    # 指定 UTF-8，GBK 无法表示的字符（如 SSID 中的 emoji）也能记录。
    handler = RotatingFileHandler(
        get_user_data_path('app.log'),
        maxBytes=2 * 1024 * 1024,
        backupCount=1,
        encoding='utf-8',
    )
    handlers: list[logging.Handler] = [handler]
    if not is_frozen():
        # 打包的窗口程序没有控制台，sys.stderr 为 None。
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO if is_frozen() else logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=handlers,
    )


def main() -> None:
    from workpal.features.single_instance import SingleInstance
    instance = SingleInstance()
    if not instance.acquire():
        import win32api
        win32api.MessageBox(0, 'WorkPal 已在当前用户会话中运行，请使用已有托盘图标。', 'WorkPal', 0x40)
        return
    try:
        _setup_logging()
        from workpal.tray import initial_tray
        initial_tray()
    finally:
        instance.close()


if __name__ == '__main__':
    main()
