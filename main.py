import logging
from logging.handlers import RotatingFileHandler

from workpal.system import is_frozen
from workpal.tray import initial_tray


def _setup_logging() -> None:
    handler = RotatingFileHandler('app.log', maxBytes=2 * 1024 * 1024, backupCount=1)
    logging.basicConfig(
        level=logging.INFO if is_frozen() else logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[handler, logging.StreamHandler()],
    )


def main() -> None:
    _setup_logging()
    initial_tray()


if __name__ == '__main__':
    main()
