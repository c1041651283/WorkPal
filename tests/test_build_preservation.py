"""在临时项目中运行打包入口，以假 PyInstaller 验证旧包和配置不被改写。"""

import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('script', ['build_exe.ps1', 'build_onefile.ps1'])
@pytest.mark.parametrize('failure', ['icons', 'packager', 'success'])
def test_build_uses_new_output_and_preserves_old_private_files(tmp_path, script, failure):
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    for name in (script, 'build_package.ps1'):
        (scripts / name).write_bytes((ROOT / 'scripts' / name).read_bytes())
    (scripts / 'gen_icons.py').write_text('raise SystemExit(' + ('1' if failure == 'icons' else '0') + ')')
    (tmp_path / 'network_config.ini.example').write_text('WIFI_PASSWORD=example')
    (tmp_path / 'network_config.ini').write_text('PRIVATE ROOT CONFIG')
    old = tmp_path / 'dist' / 'WorkPal'
    old.mkdir(parents=True)
    (old / 'network_config.ini').write_text('PRIVATE INSTALL CONFIG')
    (old / 'WorkPal.exe').write_bytes(b'OLD FOLDER PROGRAM')
    (tmp_path / 'dist' / 'WorkPal.exe').write_bytes(b'OLD SINGLE PROGRAM')
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    module = tmp_path / 'PyInstaller'
    module.mkdir()
    (module / '__init__.py').touch()
    (module / '__main__.py').write_text(
        "import sys\nfrom pathlib import Path\n"
        + ("raise SystemExit(2)\n" if failure == 'packager' else '')
        + "dest=Path(sys.argv[sys.argv.index('--distpath')+1])\n"
        + "if sys.argv[1]=='WorkPal.spec': dest=dest/'WorkPal'\n"
        + "dest.mkdir(parents=True, exist_ok=True)\n(dest/'WorkPal.exe').write_bytes(b'NEW')\n"
    )
    env = os.environ.copy()
    env.pop('PYTHONPATH', None)
    # 执行复制到临时项目的真实入口；没有调用实际 PyInstaller 或生成图标。
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                             '-File', str(scripts / script), '-Python', sys.executable],
                            cwd=tmp_path, env=env, capture_output=True, timeout=30,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    assert (result.returncode == 0) == (failure == 'success'), result.stderr.decode(errors='replace')
    if failure == 'success':
        repeated = subprocess.run(result.args, cwd=tmp_path, env=env, capture_output=True,
                                  timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        assert repeated.returncode == 0
    assert all(path.read_bytes() == data for path, data in before.items())
    outputs = [p for p in (tmp_path / 'dist').iterdir() if p.name.startswith(('folder-', 'onefile-'))]
    assert len(outputs) == (2 if failure == 'success' else 1)
    assert not any(list(output.rglob('network_config.ini')) for output in outputs)
    if failure == 'success':
        assert len(list(outputs[0].rglob('WorkPal.exe'))) == 1
        assert len(list(outputs[0].rglob('network_config.ini.example'))) == 1
