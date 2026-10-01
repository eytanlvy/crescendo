"""Logique du frontend Linux (testable partout : aucune dépendance système à l'import)."""
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "dictation_daemon", Path(__file__).resolve().parent.parent / "frontends" / "linux" / "dictation_daemon.py")
daemon = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(daemon)


class FakeRecorder:
    def __init__(self, path):
        self.path, self.started, self.stopped, self.killed = path, False, False, False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def kill(self):
        self.killed = True


class Harness:
    def __init__(self, result=None):
        self.now = 0.0
        self.recorders, self.pipeline_calls, self.pasted, self.notes = [], [], [], []
        self.result = result or {"status": "ok", "text": "Bonjour. "}
        self.ctl = daemon.Controller(
            recorder_factory=self._recorder, pipeline=self._pipeline, paster=self._paste,
            notify=lambda t, m: self.notes.append((t, m)), clock=lambda: self.now,
            min_duration_s=0.3, tail_s=0.0, tmpdir="/tmp", run_async=lambda fn: fn())

    def _recorder(self, path):
        r = FakeRecorder(path)
        self.recorders.append(r)
        return r

    def _pipeline(self, path, mode, window_ms):
        self.pipeline_calls.append((path, mode, window_ms))
        return self.result

    def _paste(self, text, enter):
        self.pasted.append((text, enter))


def test_press_release_pastes_result():
    h = Harness()
    h.ctl.press("insert")
    h.now = 2.0
    h.ctl.release()
    assert h.recorders[0].started and h.recorders[0].stopped
    assert h.pipeline_calls[0][1] == "insert"
    assert h.pipeline_calls[0][2] == pytest.approx(2000)
    assert h.pasted == [("Bonjour. ", False)]


def test_enter_mode_is_forwarded():
    h = Harness()
    h.ctl.press("enter")
    h.now = 1.0
    h.ctl.release()
    assert h.pasted == [("Bonjour. ", True)]


def test_key_repeat_does_not_restart_recording():
    h = Harness()
    h.ctl.press("insert")
    h.ctl.press("insert")
    h.ctl.press("insert")
    assert len(h.recorders) == 1


def test_short_press_is_ignored():
    h = Harness()
    h.ctl.press("insert")
    h.now = 0.1
    h.ctl.release()
    assert h.recorders[0].killed and h.pipeline_calls == [] and h.pasted == []


def test_cancel_discards_recording():
    h = Harness()
    h.ctl.press("insert")
    h.now = 1.5
    h.ctl.cancel()
    h.ctl.release()
    assert h.recorders[0].killed and h.pipeline_calls == []


def test_toggle_starts_then_stops():
    h = Harness()
    h.ctl.toggle("insert")
    h.now = 1.0
    h.ctl.toggle("insert")
    assert h.pasted == [("Bonjour. ", False)]


def test_empty_result_pastes_nothing():
    h = Harness({"status": "silence", "text": ""})
    h.ctl.press("insert")
    h.now = 1.0
    h.ctl.release()
    assert h.pasted == []


def test_service_error_notifies():
    h = Harness({"status": "error", "text": "", "error": "whisper : injoignable"})
    h.ctl.press("insert")
    h.now = 1.0
    h.ctl.release()
    assert h.pasted == [] and "injoignable" in h.notes[-1][1]


@pytest.mark.parametrize("wm_class,keys", [
    ("gnome-terminal-server", "ctrl+shift+v"),
    ("org.wezfurlong.wezterm", "ctrl+shift+v"),
    ("kitty", "ctrl+shift+v"),
    ("Alacritty", "ctrl+shift+v"),
    ("code", "ctrl+v"),               # VS Code : ctrl+v marche dans l'éditeur ET le terminal intégré
    ("firefox", "ctrl+v"),
    ("", "ctrl+v"),
])
def test_paste_keys_by_window_class(wm_class, keys):
    assert daemon.paste_keys(wm_class) == keys


@pytest.mark.parametrize("line,expected", [
    ("toggle", ("toggle", "insert")),
    ("toggle enter", ("toggle", "enter")),
    ("start enter", ("start", "enter")),
    ("stop", ("stop", "insert")),
    ("cancel", ("cancel", "insert")),
])
def test_parse_command(line, expected):
    assert daemon.parse_command(line) == expected


def test_parse_command_rejects_unknown():
    with pytest.raises(ValueError):
        daemon.parse_command("rm -rf /")
