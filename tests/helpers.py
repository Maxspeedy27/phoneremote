import tempfile
from pathlib import Path

from phoneremote.backends.base import Backend
from phoneremote.pairing import DeviceStore


class FakeBackend(Backend):
    """Records calls instead of touching the real keyboard and mouse."""

    name = "fake"

    def __init__(self):
        self.calls = []

    def move(self, dx, dy):
        self.calls.append(("move", dx, dy))

    def scroll(self, px):
        self.calls.append(("scroll", px))

    def button(self, name, down):
        self.calls.append(("button", name, down))

    def click(self, name):
        self.calls.append(("click", name))

    def hotkey(self, *keys):
        self.calls.append(("hotkey",) + keys)

    def type_text(self, text):
        self.calls.append(("type", text))


class Approver:
    """Stand-in for the laptop user answering the pairing prompt."""

    def __init__(self, answer=True):
        self.answer = answer
        self.prompts = []

    def __call__(self, name, code, timeout):
        self.prompts.append((name, code))
        return self.answer


def temp_store(testcase):
    tmp = tempfile.TemporaryDirectory()
    testcase.addCleanup(tmp.cleanup)
    return DeviceStore(Path(tmp.name) / "conf" / "paired-phone.json")
