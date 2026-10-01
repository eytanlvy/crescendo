#!/usr/bin/env python3
"""Frontend Linux (EXPÉRIMENTAL) de la dictée vocale : l'équivalent de hammerspoon/dictation.lua.

Deux façons de déclencher la dictée :
  1. Raccourci du bureau (GNOME, KDE, sway…) → `dictation_daemon.py ctl toggle` : un appui démarre,
     le suivant arrête et insère (`ctl toggle enter` : idem + Entrée). Marche sous X11 et Wayland.
  2. Maintien d'une touche (push-to-talk) via evdev : `dictation_daemon.py run --hold-key KEY_RIGHTCTRL`.
     Nécessite python3-evdev et l'accès en lecture à /dev/input (groupe `input`). La touche n'est pas
     « consommée » : choisissez-en une sans effet seule (Ctrl droit, F13…).

Dépendances système : arecord (alsa-utils) ou rec (sox) ; X11 : xclip + xdotool ; Wayland : wl-clipboard + ydotool
(avec le démon ydotoold) ; optionnel : notify-send, paplay.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
DICTATE = REPO / "bin" / "dictate"

# Terminaux où le collage est Ctrl+Maj+V (classe de fenêtre X11, en minuscules, préfixes acceptés).
TERMINALS = ("gnome-terminal", "org.gnome.console", "kgx", "konsole", "xterm", "uxterm", "urxvt", "rxvt",
             "kitty", "alacritty", "org.wezfurlong.wezterm", "wezterm", "tilix", "terminator", "xfce4-terminal",
             "mate-terminal", "lxterminal", "foot", "ghostty", "com.mitchellh.ghostty", "st-256color", "terminology")
COMMANDS = {"toggle", "start", "stop", "cancel"}
SOUNDS = Path("/usr/share/sounds/freedesktop/stereo")


def paste_keys(wm_class: str) -> str:
    cls = (wm_class or "").lower()
    return "ctrl+shift+v" if any(cls.startswith(t) for t in TERMINALS) else "ctrl+v"


def parse_command(line: str) -> tuple[str, str]:
    parts = line.split()
    if not parts or parts[0] not in COMMANDS:
        raise ValueError(f"commande inconnue : {line!r} (attendu : {', '.join(sorted(COMMANDS))})")
    mode = parts[1] if len(parts) > 1 else "insert"
    if mode not in ("insert", "enter"):
        raise ValueError(f"mode inconnu : {mode!r}")
    return parts[0], mode


class Controller:
    """Machine à états appui/relâche, indépendante du système (dépendances injectées pour les tests)."""

    def __init__(self, recorder_factory, pipeline, paster, notify, clock=time.monotonic, min_duration_s=0.3,
                 tail_s=0.15, tmpdir=None, run_async=None, sound=lambda name: None):
        self.recorder_factory, self.pipeline, self.paster, self.notify = recorder_factory, pipeline, paster, notify
        self.clock, self.min_duration_s, self.tail_s, self.sound = clock, min_duration_s, tail_s, sound
        self.tmpdir = tmpdir or tempfile.gettempdir()
        self.run_async = run_async or (lambda fn: threading.Thread(target=fn, daemon=True).start())
        self._lock = threading.Lock()
        self._rec = None  # (recorder, mode, t_press, path)
        self._work = threading.Lock()  # transcriptions séquentielles : l'ordre des collages est préservé

    def press(self, mode: str = "insert") -> None:
        with self._lock:
            if self._rec:
                return  # auto-répétition ou double déclenchement
            path = os.path.join(self.tmpdir, f"dictation-{int(time.time() * 1000)}.pcm")
            rec = self.recorder_factory(path)
            rec.start()
            self._rec = (rec, mode, self.clock(), path)
        self.sound("start")

    def release(self) -> None:
        with self._lock:
            if not self._rec:
                return
            rec, mode, t_press, path = self._rec
            self._rec = None
            if self.clock() - t_press < self.min_duration_s:
                rec.kill()
                _remove(path)
                return
            if self.tail_s:
                time.sleep(self.tail_s)
            rec.stop()
            window_ms = (self.clock() - t_press) * 1000
        self.run_async(lambda: self._process(path, mode, window_ms))

    def cancel(self) -> None:
        with self._lock:
            if self._rec:
                rec, _, _, path = self._rec
                self._rec = None
                rec.kill()
                _remove(path)

    def toggle(self, mode: str = "insert") -> None:
        if self._rec:
            self.release()
        else:
            self.press(mode)

    def _process(self, path: str, mode: str, window_ms: float) -> None:
        with self._work:
            try:
                res = self.pipeline(path, mode, window_ms)
                for w in res.get("warnings", []):
                    self.notify("Dictée — attention", w)
                if res.get("status") == "error":
                    self.sound("error")
                    self.notify("Dictée — échec", res.get("error", "erreur inconnue"))
                elif res.get("text"):
                    self.paster(res["text"], mode == "enter")
                    self.sound("stop")
            finally:
                _remove(path)
                _remove(path[:-4] + ".wav")


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


# --------------------------------------------------------------------------- implémentations système

class SubprocessRecorder:
    def __init__(self, cmd: list[str]):
        self.cmd, self.proc = cmd, None

    def start(self):
        self.proc = subprocess.Popen(self.cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGINT)
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def kill(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()


def recorder_command(kind: str, path: str, max_s: int) -> list[str]:
    if kind == "arecord":
        return ["arecord", "-q", "-f", "S16_LE", "-r", "16000", "-c", "1", "-t", "raw", "-d", str(max_s), path]
    return ["rec", "-q", "-t", "raw", "-r", "16000", "-c", "1", "-b", "16", "-e", "signed-integer", path,
            "trim", "0", str(max_s)]


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=5, **kw)


class Paster:
    """Presse-papiers + raccourci de collage, puis restauration du presse-papiers (texte uniquement)."""

    def __init__(self, keys: str = "auto", restore_delay_s: float = 0.4, enter_delay_s: float = 0.12):
        self.wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
        self.keys, self.restore_delay_s, self.enter_delay_s = keys, restore_delay_s, enter_delay_s

    def active_class(self) -> str:
        if self.wayland or not shutil.which("xdotool"):
            return ""
        for query in ("getactivewindow", "getwindowfocus"):  # getwindowfocus : sans gestionnaire de fenêtres
            out = _run(["xdotool", query, "getwindowclassname"])
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.decode(errors="replace").strip()
        return ""

    def _get(self) -> bytes | None:
        cmd = ["wl-paste", "-n"] if self.wayland else ["xclip", "-selection", "clipboard", "-o"]
        try:
            out = _run(cmd)
            return out.stdout if out.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            return None

    def _set(self, data: bytes) -> None:
        cmd = ["wl-copy"] if self.wayland else ["xclip", "-selection", "clipboard", "-i"]
        subprocess.run(cmd, input=data, timeout=5)

    def _keys(self, combo: str) -> None:
        if self.wayland:
            codes = {"ctrl": 29, "shift": 42, "v": 47, "return": 28}  # codes evdev pour ydotool
            keys = [codes[k] for k in combo.split("+")]
            seq = [f"{k}:1" for k in keys] + [f"{k}:0" for k in reversed(keys)]
            subprocess.run(["ydotool", "key", *seq], timeout=5)
        else:
            subprocess.run(["xdotool", "key", "--clearmodifiers", combo.replace("return", "Return")], timeout=5)

    def __call__(self, text: str, enter: bool) -> None:
        saved = self._get()
        self._set(text.encode())
        combo = paste_keys(self.active_class()) if self.keys == "auto" else self.keys
        self._keys(combo)
        if enter:
            time.sleep(self.enter_delay_s)
            self._keys("return")
        time.sleep(self.restore_delay_s)
        if saved is not None:
            self._set(saved)


def notify(title: str, message: str) -> None:
    print(f"{title} : {message}", file=sys.stderr)
    if shutil.which("notify-send"):
        subprocess.Popen(["notify-send", "-a", "voice-dictation", title, message])


def sound(name: str) -> None:
    files = {"start": "message.oga", "stop": "complete.oga", "error": "dialog-error.oga"}
    f = SOUNDS / files.get(name, "")
    if shutil.which("paplay") and f.is_file():
        subprocess.Popen(["paplay", str(f)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def load_config() -> dict:
    out = subprocess.run([sys.executable, str(DICTATE), "config", "--json"], capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(out.stderr)
    return json.loads(out.stdout)


def make_pipeline(cfg: dict, paster: Paster):
    def pipeline(path: str, mode: str, window_ms: float) -> dict:
        cmd = [sys.executable, str(DICTATE), path, "--json", "--mode", mode, "--rec-window-ms", f"{window_ms:.0f}"]
        app = paster.active_class()
        if app:
            cmd += ["--app", app]
        limit = cfg["whisper"]["timeout_s"] + cfg["cleanup"]["timeout_s"] + 30
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=limit)
            return json.loads(out.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            return {"status": "error", "error": f"pipeline : {e}"}
    return pipeline


def socket_path() -> str:
    return os.path.join(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir(), "voice-dictation.sock")


def serve_socket(ctl: Controller) -> None:
    path = socket_path()
    _remove(path)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    os.chmod(path, 0o600)
    srv.listen()
    while True:
        conn, _ = srv.accept()
        with conn:
            line = conn.recv(256).decode(errors="replace").strip()
            try:
                cmd, mode = parse_command(line)
                {"toggle": lambda: ctl.toggle(mode), "start": lambda: ctl.press(mode),
                 "stop": ctl.release, "cancel": ctl.cancel}[cmd]()
                conn.sendall(b"ok\n")
            except ValueError as e:
                conn.sendall(f"erreur : {e}\n".encode())


def watch_evdev(ctl: Controller, hold_key: str, enter_key: str | None) -> None:
    try:
        import evdev  # type: ignore
    except ImportError:
        raise SystemExit("--hold-key nécessite python3-evdev (apt install python3-evdev)")
    ecodes = evdev.ecodes
    hold, enter = ecodes.ecodes[hold_key], ecodes.ecodes[enter_key] if enter_key else None
    devices = [d for d in map(evdev.InputDevice, evdev.list_devices()) if ecodes.EV_KEY in d.capabilities()]
    if not devices:
        raise SystemExit("aucun clavier lisible dans /dev/input (ajoutez-vous au groupe `input`)")

    def loop(dev):
        for ev in dev.read_loop():
            if ev.type != ecodes.EV_KEY or ev.value == 2:  # 2 = auto-répétition
                continue
            if ev.code in (hold, enter):
                (ctl.press("enter" if ev.code == enter else "insert") if ev.value == 1 else ctl.release())
            elif ev.code == ecodes.KEY_ESC and ev.value == 1:
                ctl.cancel()

    for dev in devices:
        threading.Thread(target=loop, args=(dev,), daemon=True).start()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="lance le démon")
    run.add_argument("--hold-key", help="touche à maintenir (evdev), ex. KEY_RIGHTCTRL")
    run.add_argument("--enter-hold-key", help="idem, puis Entrée, ex. KEY_RIGHTALT")
    run.add_argument("--recorder", choices=["arecord", "rec"], default="arecord")
    run.add_argument("--paste-keys", default="auto", help="auto (selon la fenêtre), ctrl+v ou ctrl+shift+v")
    ctl_p = sub.add_parser("ctl", help="envoie une commande au démon (toggle, start, stop, cancel)")
    ctl_p.add_argument("command", nargs="+")
    args = ap.parse_args(argv)

    if args.cmd == "ctl":
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.connect(socket_path())
        except OSError:
            print("le démon ne tourne pas : dictation_daemon.py run", file=sys.stderr)
            return 1
        s.sendall(" ".join(args.command).encode())
        print(s.recv(256).decode().strip())
        return 0

    cfg = load_config()
    rec_cfg = cfg["recording"]
    paster = Paster(args.paste_keys, cfg["output"]["restore_clipboard_delay_ms"] / 1000,
                    cfg["output"]["enter_delay_ms"] / 1000)
    ctl = Controller(
        recorder_factory=lambda p: SubprocessRecorder(recorder_command(args.recorder, p, int(rec_cfg["max_duration_s"]))),
        pipeline=make_pipeline(cfg, paster), paster=paster, notify=notify,
        min_duration_s=rec_cfg["min_duration_s"], tail_s=rec_cfg["tail_ms"] / 1000,
        sound=sound if cfg["feedback"]["sounds"] else (lambda name: None))
    if args.hold_key:
        watch_evdev(ctl, args.hold_key, args.enter_hold_key)
    print(f"dictée prête (socket {socket_path()})", file=sys.stderr)
    serve_socket(ctl)
    return 0


if __name__ == "__main__":
    sys.exit(main())
