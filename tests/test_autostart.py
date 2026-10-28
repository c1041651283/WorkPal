"""WorkPal 开机自启动任务计划管理测试。"""

from pathlib import Path
from unittest.mock import patch


def test_build_launch_target_for_frozen_exe():
    from workpal.features.autostart import build_launch_target

    target = build_launch_target(
        frozen=True,
        executable=r'C:\Tools\WorkPal\WorkPal.exe',
    )

    assert target.execute == r'C:\Tools\WorkPal\WorkPal.exe'
    assert target.arguments == ''
    assert target.working_directory == r'C:\Tools\WorkPal'


def test_build_launch_target_for_source_run():
    from workpal.features.autostart import build_launch_target

    target = build_launch_target(
        frozen=False,
        executable=r'C:\Python311\python.exe',
        main_path=Path(r'D:\WorkPal\main.py'),
    )

    assert target.execute == r'C:\Python311\python.exe'
    assert target.arguments == r'"D:\WorkPal\main.py"'
    assert target.working_directory == r'D:\WorkPal'








def test_tray_autostart_toggle_reports_success():
    from workpal import tray
    from workpal.features import autostart
    from tests.fake_view import FakeView

    autostart._set_cached_status(autostart.STATUS_DISABLED)
    with patch('workpal.features.autostart.enable_autostart', return_value=(True, '')) as enable:
        view = FakeView()
        tray._do_autostart_toggle(view)

    enable.assert_called_once()
    assert len(view.notes) == 1
    assert '已启用' in view.last.message and view.last.level == 'success'


def test_tray_autostart_label_uses_cached_status_without_scheduler_query():
    from workpal import tray
    from workpal.features import autostart

    autostart._set_cached_status(autostart.STATUS_ENABLED)
    with patch(
        'workpal.features.autostart.is_enabled',
        side_effect=AssertionError('menu must not query task scheduler synchronously'),
    ):
        assert tray.current_state().autostart == 'enabled'
        assert tray.autostart_label('enabled') == '已开启'
