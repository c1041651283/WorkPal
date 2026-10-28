"""打包时去掉 WorkPal 用不到的 Qt 文件，两个 .spec 共用。

界面只用 QtWidgets 自绘并直接用 QSvgRenderer 画图标，不需要：
  - opengl32sw.dll：软件 OpenGL 渲染（约 20MB）
  - translations：Qt 自带控件的多语言翻译
  - imageformats：TIFF/JPEG/WebP 等图片格式插件
  - 除 qwindows 以外的平台插件
"""

_UNUSED = (
    '/opengl32sw.dll',
    '/translations/',
    '/plugins/imageformats/',
    '/plugins/generic/',
    '/plugins/platforms/qdirect2d',
    '/plugins/platforms/qminimal',
    '/plugins/platforms/qoffscreen',
)


def _keep(entry) -> bool:
    path = '/' + str(entry[0]).replace('\\', '/')
    return not ('/PySide6/' in path and any(part in path for part in _UNUSED))


def trim(analysis) -> None:
    analysis.binaries = [entry for entry in analysis.binaries if _keep(entry)]
    analysis.datas = [entry for entry in analysis.datas if _keep(entry)]
