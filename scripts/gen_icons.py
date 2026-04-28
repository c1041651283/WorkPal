"""
scripts/gen_icons.py
程序化生成所有托盘图标（零版权风险）。

运行方式：
    python scripts/gen_icons.py

输出到 assets/ 目录（32x32 多尺寸 ICO）：
  icon_default.ico   — 深灰底 + 白色 WiFi 扇形（默认/空闲）
  icon_wifi.ico      — 蓝底   + 白色 WiFi 扇形（WiFi 模式）
  icon_ethernet.ico  — 绿底   + 白色以太网端口符号（有线模式）
  icon_switching.ico — 橙底   + 白色旋转双箭头（切换中）
  icon_alive.ico     — 紫底   + 白色心跳线（保持在线激活）
"""

import os
import math
from PIL import Image, ImageDraw

# 输出目录（相对于项目根目录）
ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets')

# 图标尺寸（生成多尺寸 ICO）
SIZES = [16, 24, 32, 48]
MAIN_SIZE = 32  # 主绘制画布大小

# 配色方案
COLORS = {
    'default':   ('#4a4a4a', '#ffffff'),  # 深灰底，白色图案
    'wifi':      ('#1a73e8', '#ffffff'),  # 蓝底，白色图案
    'ethernet':  ('#0f9d58', '#ffffff'),  # 绿底，白色图案
    'switching': ('#f4a300', '#ffffff'),  # 橙底，白色图案
    'alive':     ('#7b3fa0', '#ffffff'),  # 紫底，白色图案
}


def _make_base(size: int, bg_color: str) -> tuple:
    """创建圆角矩形背景画布。"""
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    radius = size // 5
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=bg_color)
    return img, draw


def _draw_wifi(draw: ImageDraw.Draw, size: int, color: str) -> None:
    """绘制 WiFi 扇形符号（三段弧 + 圆点）。"""
    cx, cy = size * 0.5, size * 0.62
    dot_r = size * 0.06
    # 圆点
    draw.ellipse(
        [cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r],
        fill=color,
    )
    # 三段弧（由内到外）
    for i, (r_inner, r_outer) in enumerate([
        (size * 0.14, size * 0.22),
        (size * 0.26, size * 0.34),
        (size * 0.38, size * 0.46),
    ]):
        bbox = [cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer]
        draw.arc(bbox, start=210, end=330, fill=color, width=max(1, int(r_outer - r_inner)))


def _draw_ethernet(draw: ImageDraw.Draw, size: int, color: str) -> None:
    """绘制以太网端口符号（矩形外框 + 内部横线）。"""
    lw = max(1, size // 16)
    margin = size * 0.18
    port_w = size * 0.62
    port_h = size * 0.46
    x0 = (size - port_w) / 2
    y0 = (size - port_h) / 2

    # 外框
    draw.rectangle([x0, y0, x0 + port_w, y0 + port_h], outline=color, width=lw)

    # 内部 4 条竖线（模拟网口针脚）
    pin_count = 4
    gap = port_w / (pin_count + 1)
    pin_h = port_h * 0.55
    pin_y0 = y0 + port_h * 0.22
    for i in range(pin_count):
        px = x0 + gap * (i + 1)
        draw.line([px, pin_y0, px, pin_y0 + pin_h], fill=color, width=lw)

    # 下方连接线（Tab）
    tab_w = port_w * 0.3
    tab_h = size * 0.12
    tx0 = (size - tab_w) / 2
    ty0 = y0 + port_h
    draw.rectangle([tx0, ty0, tx0 + tab_w, ty0 + tab_h], fill=color)


def _draw_switching(draw: ImageDraw.Draw, size: int, color: str) -> None:
    """绘制旋转双箭头（顺时针 + 逆时针各一段弧 + 箭头头部）。"""
    cx, cy = size / 2, size / 2
    r = size * 0.32
    lw = max(1, size // 10)
    offset = size * 0.1  # 两个圆弧的偏移

    def arc_arrow(cx_, cy_, start, end, flip=False):
        """绘制一段弧线并在末端加箭头。"""
        bb = [cx_ - r, cy_ - r, cx_ + r, cy_ + r]
        draw.arc(bb, start=start, end=end, fill=color, width=lw)
        # 箭头头部（简单三角）
        tip_angle = math.radians(end)
        tip_x = cx_ + r * math.cos(tip_angle)
        tip_y = cy_ + r * math.sin(tip_angle)
        perp = math.radians(end + (90 if not flip else -90))
        hw = lw * 1.8
        ax = tip_x + hw * math.cos(perp)
        ay = tip_y + hw * math.sin(perp)
        bx = tip_x - hw * math.cos(perp)
        by = tip_y - hw * math.sin(perp)
        fwd = math.radians(end + (0 if not flip else 180))
        fx = tip_x + hw * 1.5 * math.cos(fwd)
        fy = tip_y + hw * 1.5 * math.sin(fwd)
        draw.polygon([(ax, ay), (bx, by), (fx, fy)], fill=color)

    arc_arrow(cx - offset * 0.3, cy - offset * 0.3, start=200, end=340, flip=False)
    arc_arrow(cx + offset * 0.3, cy + offset * 0.3, start=20, end=160, flip=True)


def _draw_alive(draw: ImageDraw.Draw, size: int, color: str) -> None:
    """绘制简化心跳线（ECG 波形）。"""
    lw = max(1, size // 10)
    y_base = size * 0.55
    points = [
        (size * 0.08, y_base),
        (size * 0.30, y_base),
        (size * 0.38, y_base - size * 0.32),
        (size * 0.46, y_base + size * 0.20),
        (size * 0.54, y_base - size * 0.14),
        (size * 0.62, y_base),
        (size * 0.92, y_base),
    ]
    draw.line(points, fill=color, width=lw, joint='curve')


_DRAW_FN = {
    'default':   _draw_wifi,
    'wifi':      _draw_wifi,
    'ethernet':  _draw_ethernet,
    'switching': _draw_switching,
    'alive':     _draw_alive,
}


def generate_icon(name: str) -> None:
    bg, fg = COLORS[name]
    frames = []
    for sz in SIZES:
        img, draw = _make_base(sz, bg)
        _DRAW_FN[name](draw, sz, fg)
        frames.append(img)

    os.makedirs(ASSETS_DIR, exist_ok=True)
    out_path = os.path.join(ASSETS_DIR, f'icon_{name}.ico')
    # 以最大尺寸为主，其余作为额外尺寸
    frames[0].save(
        out_path,
        format='ICO',
        sizes=[(s, s) for s in SIZES],
        append_images=frames[1:],
    )
    print(f'  生成: {out_path}')


def main() -> None:
    print('正在生成图标...')
    for name in COLORS:
        generate_icon(name)
    print('✓ 所有图标生成完毕 →', ASSETS_DIR)


if __name__ == '__main__':
    main()
