"""内存中的 Task Scheduler 2.0 COM 替身，只实现 autostart 用到的成员。"""

from types import SimpleNamespace

import pythoncom


def com_error(hresult: int, message: str) -> pythoncom.com_error:
    return pythoncom.com_error(hresult, message, None, None)


NOT_FOUND = -2147024894
ACCESS_DENIED = -2147024891


class Actions(list):
    @property
    def Count(self):
        return len(self)

    def Item(self, index):
        return self[index - 1]

    def Create(self, kind):
        action = SimpleNamespace(Type=kind, Path='', Arguments='', WorkingDirectory='')
        self.append(action)
        return action


class Triggers(list):
    def Create(self, kind):
        trigger = SimpleNamespace(Type=kind, UserId='')
        self.append(trigger)
        return trigger


def new_definition():
    return SimpleNamespace(
        RegistrationInfo=SimpleNamespace(Description=''),
        Triggers=Triggers(),
        Principal=SimpleNamespace(UserId='', LogonType=0, RunLevel=0),
        Settings=SimpleNamespace(Enabled=True, DisallowStartIfOnBatteries=True,
                                 StopIfGoingOnBatteries=True, StartWhenAvailable=False,
                                 ExecutionTimeLimit='PT72H'),
        Actions=Actions(),
    )


def make_task(execute, arguments, directory, *, enabled=True, time_limit='PT0S'):
    definition = new_definition()
    definition.Settings.Enabled = enabled
    definition.Settings.ExecutionTimeLimit = time_limit
    action = definition.Actions.Create(0)
    action.Path, action.Arguments, action.WorkingDirectory = execute, arguments, directory
    return SimpleNamespace(Enabled=enabled, Definition=definition)


class Folder:
    def __init__(self):
        self.tasks = {}
        self.registrations = []
        self.after_register = None
        self.delete_ignored = False
        self.get_error = None

    def GetTask(self, name):
        if self.get_error is not None:
            raise com_error(self.get_error, 'query failed')
        if name not in self.tasks:
            raise com_error(NOT_FOUND, '系统找不到指定的文件。')
        return self.tasks[name]

    def RegisterTaskDefinition(self, name, definition, flags, user, password, logon):
        self.registrations.append((name, definition, flags, user, password, logon))
        self.tasks[name] = SimpleNamespace(Enabled=definition.Settings.Enabled, Definition=definition)
        if self.after_register is not None:
            self.after_register(self, name)

    def DeleteTask(self, name, flags):
        if not self.delete_ignored:
            self.tasks.pop(name, None)


class Service:
    def __init__(self):
        self.folder = Folder()

    def GetFolder(self, path):
        assert path == '\\'
        return self.folder

    def NewTask(self, flags):
        assert flags == 0
        return new_definition()
