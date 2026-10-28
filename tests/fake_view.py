"""记录通知和刷新的界面替身，实现 workpal.tray.View。"""

from dataclasses import dataclass


@dataclass
class Note:
    title: str
    message: str
    level: str
    key: object

    @property
    def text(self) -> str:
        return f'{self.title} {self.message}'


class FakeView:
    def __init__(self):
        self.notes: list[Note] = []
        self.refreshes = 0
        self.quit_called = False

    def notify(self, title, message='', *, level='info', key=None):
        self.notes.append(Note(title, message, level, key))

    def refresh(self):
        self.refreshes += 1

    def quit(self):
        self.quit_called = True

    @property
    def last(self) -> Note:
        return self.notes[-1]

    def texts(self) -> list[str]:
        return [note.text for note in self.notes]
