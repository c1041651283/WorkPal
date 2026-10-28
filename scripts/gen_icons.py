"""生成 EXE 文件图标 assets/WorkPal.ico：与托盘图标相同的渐变圆角色块（WiFi 状态）。

图形来自已内嵌的 workpal/ui/glyphs.py，用 Qt 绘制，不需联网，也不需 Pillow。
ICO 中每个尺寸以 PNG 存储（Windows Vista 起支持）。打包脚本会先运行本脚本。
用法：python scripts/gen_icons.py
"""

import os
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication, QPixmap  # noqa: E402

from workpal.ui.icons import tray_pixmap  # noqa: E402

TARGET = ROOT / 'assets' / 'WorkPal.ico'
SIZES = (16, 20, 24, 32, 40, 48, 64, 256)
GLYPH = 'wifi'


def _png(pixmap: QPixmap) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, 'PNG')
    return bytes(buffer.data())


def build_ico(images: list[tuple[int, bytes]]) -> bytes:
    """ICONDIR + 每个尺寸一条 ICONDIRENTRY + PNG 数据；256 像素在目录中记为 0。"""
    header = struct.pack('<HHH', 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, data = b'', b''
    for size, png in images:
        dimension = 0 if size >= 256 else size
        entries += struct.pack('<BBBBHHII', dimension, dimension, 0, 0, 1, 32, len(png),
                               offset + len(data))
        data += png
    return header + entries + data


def main() -> None:
    app = QGuiApplication(sys.argv)  # 绘制 QPixmap 需要
    images = [(size, _png(tray_pixmap(GLYPH, False, size))) for size in SIZES]
    TARGET.parent.mkdir(exist_ok=True)
    TARGET.write_bytes(build_ico(images))
    print(f'已生成 {TARGET}')
    del app


if __name__ == '__main__':
    main()
