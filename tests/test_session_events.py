"""只模拟消息和原生接口，不锁屏、不休眠、不操作真实 VPN。"""

from unittest.mock import MagicMock, patch

from workpal.features import session_events as events


def test_only_resume_and_unlock_request_network_recheck():
    listener = events.SessionEvents()
    listener._callback = MagicMock()
    with patch.object(events.win32gui, 'DefWindowProc', return_value=0):
        listener._handle(1, events.WM_WTSSESSION_CHANGE, 7, 1)  # 锁屏不改代理。
        listener._handle(1, events.WM_POWERBROADCAST, 4, 0)  # 休眠不改代理。
        listener._callback.assert_not_called()
        listener._handle(1, events.WM_WTSSESSION_CHANGE, 8, 1)
        listener._handle(1, events.WM_POWERBROADCAST, 18, 0)
    assert [call.args[0] for call in listener._callback.call_args_list] == ['解锁', '系统唤醒']


def test_listener_cleanup_unregisters_session_before_destroying_hidden_window():
    listener = events.SessionEvents()
    listener._stop.set()
    order = []
    with patch.object(events.win32api, 'GetModuleHandle', return_value=1), \
         patch.object(events.win32gui, 'RegisterClass'), \
         patch.object(events.win32gui, 'UnregisterClass'), \
         patch.object(events.win32gui, 'CreateWindowEx', return_value=123) as create, \
         patch.object(events.win32gui, 'IsWindow', return_value=True), \
         patch.object(events.win32gui, 'PumpMessages') as pump, \
         patch.object(events.win32gui, 'DestroyWindow', side_effect=lambda _: order.append('destroy')), \
         patch.object(events.win32ts, 'WTSRegisterSessionNotification') as register, \
         patch.object(events.win32ts, 'WTSUnRegisterSessionNotification', side_effect=lambda _: order.append('unregister')):
        listener._run()
    register.assert_called_once_with(123, 0)
    assert create.call_args.args[3] == 0  # 无 WS_VISIBLE。
    assert create.call_args.args[8] == 0  # 顶层窗口，非 HWND_MESSAGE。
    assert order == ['unregister', 'destroy']
    assert listener._window is None
    pump.assert_not_called()


def test_event_callback_failure_does_not_escape_windows_message_handler():
    listener = events.SessionEvents()
    listener._callback = MagicMock(side_effect=RuntimeError('callback failed'))
    assert listener._handle(1, events.WM_POWERBROADCAST, 18, 0) == 1
