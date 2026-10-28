"""下载界面用到的 Fluent UI System Icons（Microsoft，MIT），生成 workpal/ui/glyphs.py。

Fluent 图标为 16/20/24 像素分别手工调整过线条，按显示尺寸选用对应版本最清晰，
因此每个图标下载所有可用尺寸。只在需要新增或更换图标时运行；生成的文件提交到仓库，
运行和打包都不再联网。
用法：python scripts/gen_glyphs.py
"""

from pathlib import Path
import time
import urllib.error
import urllib.request

# 程序中使用的名字 → (Fluent 图标名, 样式)
GLYPHS = {
    'wifi': ('wifi-1', 'filled'),
    'ethernet': ('plug-connected', 'filled'),
    'unknown': ('wifi-off', 'filled'),
    'switching': ('arrow-sync', 'filled'),
    'shield': ('shield', 'regular'),
    'shield_ok': ('shield-checkmark', 'regular'),
    'shield_error': ('shield-error', 'regular'),
    # 状态卡片用实心图标，与网络图标风格一致；名字为对应图标加 _filled
    'shield_filled': ('shield', 'filled'),
    'shield_ok_filled': ('shield-checkmark', 'filled'),
    'shield_error_filled': ('shield-error', 'filled'),
    'heart': ('heart-pulse', 'regular'),
    'refresh': ('arrow-clockwise', 'regular'),
    'home': ('home', 'regular'),
    'script': ('document-code', 'regular'),
    'settings': ('settings', 'regular'),
    'log': ('document-text', 'regular'),
    'power': ('power', 'regular'),
    'back': ('chevron-left', 'regular'),
    'edit': ('edit', 'regular'),
    'rocket': ('rocket', 'regular'),
    'info': ('info', 'filled'),
    'success': ('checkmark-circle', 'filled'),
    'error': ('error-circle', 'filled'),
    'progress': ('arrow-sync-circle', 'filled'),
}
SIZES = (16, 20, 24)

TARGET = Path(__file__).resolve().parent.parent / 'workpal' / 'ui' / 'glyphs.py'


def download(name: str) -> str | None:
    url = f'https://api.iconify.design/fluent/{name}.svg'
    # 与 gen_icons.py 相同，Iconify 拒绝默认的 Python User-Agent。
    request = urllib.request.Request(url, headers={'User-Agent': 'WorkPal-IconGen/1.0'})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                svg = response.read().decode('utf-8')
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            # 连续下载数十个图标会触发限流，按服务器要求等待后重试
            if exc.code != 429 or attempt == 5:
                raise
            delay = int(exc.headers.get('Retry-After') or 2 ** attempt * 2)
            print(f'  限流，{delay} 秒后重试 {name}')
            time.sleep(delay)
    if 'currentColor' not in svg:
        raise RuntimeError(f'{name} 不含 currentColor，无法着色')
    return svg


def main() -> None:
    lines = [
        '"""界面图标：Fluent UI System Icons（Microsoft，MIT 协议）。',
        '',
        '由 scripts/gen_glyphs.py 生成，请勿手工修改。SVG[名字][设计尺寸] 为该尺寸手工调整过的版本；',
        'fill 使用 currentColor，绘制时替换为实际颜色。',
        '"""',
        '',
        'SVG = {',
    ]
    for key, (base, style) in GLYPHS.items():
        variants = {}
        for size in SIZES:
            svg = download(f'{base}-{size}-{style}')
            if svg is not None:
                variants[size] = svg
        if not variants:
            raise RuntimeError(f'{base} 没有可用尺寸')
        print(f'{key}: {sorted(variants)}')
        lines.append(f'    {key!r}: {{')
        lines += [f'        {size}: {svg!r},' for size, svg in sorted(variants.items())]
        lines.append('    },')
    lines.append('}')
    TARGET.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'已生成 {TARGET}')


if __name__ == '__main__':
    main()
