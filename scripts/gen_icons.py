"""
scripts/gen_icons.py
从 Iconify 公共 API 下载 Fluent UI System Icons（Microsoft，MIT 协议）
并生成多尺寸 ICO 托盘图标。

运行方式：
    python scripts/gen_icons.py

输出到 assets/ 目录（16/24/32/48 多尺寸 ICO）：
  icon_default.ico   — 深灰底 + WiFi-off 图标（默认/空闲）
  icon_wifi.ico      — 蓝底   + WiFi 图标（WiFi 模式）
  icon_ethernet.ico  — 绿底   + 插头图标（有线模式）
  icon_switching.ico — 橙底   + 同步箭头图标（切换中）
  icon_alive.ico     — 紫底   + 心跳图标（保持在线激活）

图标来源：Fluent UI System Icons by Microsoft Corporation
许可证：MIT — https://github.com/microsoft/fluentui-system-icons/blob/main/LICENSE
"""

import io
import os
import tempfile
import urllib.request

from PIL import Image, ImageDraw

try:
    from svglib.svglib import svg2rlg
    from reportlab.graphics import renderPM
    _SVG_AVAILABLE = True
except ImportError:
    _SVG_AVAILABLE = False

# 输出目录（相对于项目根目录）
ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets')

# 图标尺寸（生成多尺寸 ICO）
SIZES = [16, 24, 32, 48, 64, 128, 256]

# 配色方案（背景色）
COLORS = {
    'default':   '#3c3c3c',  # 深灰
    'wifi':      '#1a73e8',  # 蓝
    'ethernet':  '#0f9d58',  # 绿
    'switching': '#f29900',  # 橙
    'alive':     '#7b3fa0',  # 紫
}

# Iconify API：Fluent UI System Icons（MIT 协议）
# 用黑色下载，渲染后反转为白色 + alpha 蒙版，再叠加背景色
_ICONIFY_BASE = 'https://api.iconify.design/fluent/{icon}.svg?color=%23000000&width=96&height=96'
ICON_SOURCES = {
    'default':   'wifi-off-24-filled',
    'wifi':      'wifi-1-24-filled',
    'ethernet':  'plug-connected-24-filled',
    'switching': 'arrow-sync-24-filled',
    'alive':     'heart-pulse-24-filled',
}


def _fetch_svg(icon_id: str) -> str:
    """从 Iconify API 下载 SVG 文本（白色图标，96px 视口）。"""
    url = _ICONIFY_BASE.format(icon=icon_id)
    req = urllib.request.Request(url, headers={'User-Agent': 'WorkPal-IconGen/1.0'})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode('utf-8')


def _svg_to_pil(svg_text: str, render_size: int) -> Image.Image:
    """将 SVG 文本渲染为指定尺寸的白色图标（RGBA，透明背景）。"""
    if not _SVG_AVAILABLE:
        raise RuntimeError('需要安装 svglib 和 reportlab：pip install svglib reportlab')

    with tempfile.NamedTemporaryFile(suffix='.svg', delete=False, mode='w', encoding='utf-8') as f:
        f.write(svg_text)
        tmp_path = f.name

    try:
        drawing = svg2rlg(tmp_path)
        if drawing is None:
            raise ValueError('svglib 无法解析 SVG')

        # 等比缩放到目标尺寸（超采样：4倍后缩小以获得抗锯齿）
        oversample = 4
        src_w = drawing.width or 96
        src_h = drawing.height or 96
        large = render_size * oversample
        scale = large / max(src_w, src_h)
        drawing.width = large
        drawing.height = large
        drawing.transform = (scale, 0, 0, scale, 0, 0)

        # 以白色背景渲染（SVG 图标是黑色），得到黑色图标 + 白色背景
        png_bytes = renderPM.drawToString(drawing, fmt='PNG', bg=0xFFFFFF)
        raw = Image.open(io.BytesIO(png_bytes)).convert('L')  # 转灰度

        # 缩小到目标尺寸（LANCZOS 抗锯齿）
        raw = raw.resize((render_size, render_size), Image.LANCZOS)

        # 将灰度亮度取反作为 alpha：黑色(0)→完全不透明，白色(255)→完全透明
        from PIL import ImageOps
        alpha = ImageOps.invert(raw)

        # 合成：白色像素 + 以灰度亮度反转值为 alpha
        white = Image.new('RGBA', (render_size, render_size), (255, 255, 255, 255))
        white.putalpha(alpha)
        return white
    finally:
        os.unlink(tmp_path)


def _make_rounded_bg(size: int, color: str) -> Image.Image:
    """创建圆角矩形背景（带超采样抗锯齿）。"""
    scale = 4
    s = size * scale
    img = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    radius = s // 5
    draw.rounded_rectangle([0, 0, s - 1, s - 1], radius=radius, fill=color)
    return img.resize((size, size), Image.LANCZOS)


def generate_icon(name: str, svg_text: str) -> None:
    """合成图标并保存为多尺寸 ICO。"""
    bg_color = COLORS[name]
    frames = []

    for sz in SIZES:
        # 背景（圆角矩形）
        bg = _make_rounded_bg(sz, bg_color)

        # 图标区域留 15% 内边距
        padding = max(1, int(sz * 0.15))
        icon_area = sz - 2 * padding

        # 渲染图标
        icon_img = _svg_to_pil(svg_text, icon_area)
        icon_img = icon_img.resize((icon_area, icon_area), Image.LANCZOS)

        # 将图标（透明背景）贴到背景上
        bg.paste(icon_img, (padding, padding), icon_img)
        frames.append(bg)

    os.makedirs(ASSETS_DIR, exist_ok=True)
    out_path = os.path.join(ASSETS_DIR, f'icon_{name}.ico')
    # 以最大帧（256x256）为基础，Pillow 会自动缩小到各目标尺寸
    frames[-1].save(
        out_path,
        format='ICO',
        sizes=[(s, s) for s in SIZES],
    )
    print(f'  ✓ {out_path}')


def main() -> int:
    if not _SVG_AVAILABLE:
        print('错误：缺少依赖，请先运行：pip install svglib reportlab')
        return 1

    print('正在从 Iconify（Fluent UI System Icons，MIT）下载图标...')
    svg_cache: dict[str, str] = {}
    for name, icon_id in ICON_SOURCES.items():
        print(f'  下载 {icon_id} ...', end=' ', flush=True)
        try:
            svg_cache[name] = _fetch_svg(icon_id)
            print('完成')
        except Exception as exc:
            print(f'失败 ({exc})')
            return 1

    print('正在生成 ICO 文件...')
    for name in ICON_SOURCES:
        generate_icon(name, svg_cache[name])

    print(f'\n全部完成 → {ASSETS_DIR}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
