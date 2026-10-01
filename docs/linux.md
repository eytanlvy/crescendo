# Linux

Same pipeline as macOS (`bin/dictate`). Only the frontend differs: a small Python daemon
(`frontends/linux/dictation_daemon.py`) for the shortcut, recording and paste.

| | macOS | Linux |
|---|---|---|
| Frontend | Hammerspoon | Python daemon |
| Trigger | hold ⌥Space | toggle shortcut, or hold a key (evdev) |
| Recording | sox `rec` | `arecord` |
| Paste | ⌘V | X11: xclip + xdotool · Wayland: wl-clipboard + ydotool |
| Services | LaunchAgents | systemd user units |

## Install

```sh
git clone https://github.com/eytanlvy/crescendo.git
cd crescendo
scripts/install-linux.sh
```

- Packages: apt (Ubuntu, Debian), dnf (Fedora) or pacman (Arch).
- whisper.cpp is built from source, with CUDA if `nvidia-smi` and `nvcc` are present.
- Whisper model: `large-v3-turbo` with CUDA, `small` otherwise.
- Ollama is installed from ollama.com if missing.
- Services: `crescendo-whisper.service`, `crescendo.service` (systemd user units).
- GNOME: shortcuts are added automatically.

Options:

- `--hold-key KEY_RIGHTCTRL` — hold-to-talk with evdev (adds you to the `input` group; log out and back in).
- `--model small|base|large-v3-turbo-q8_0` — Whisper model.
- `--llm qwen2.5:3b-instruct` — cleanup model.
- `--shortcut "<Control><Alt>space"` — GNOME shortcut, or `none`.
- `--no-systemd` — no services; whisper-server runs in the background (containers, CI).

## Use

- **Toggle (default):** Ctrl+Alt+Space to record, again to paste.
- **Toggle + Enter:** Ctrl+Shift+Alt+Space.
- **Hold (with `--hold-key`):** hold the key, speak, release. Esc cancels.
- **Other desktops (KDE, sway…):** bind `python3 <repo>/frontends/linux/dictation_daemon.py ctl toggle`
  (and `ctl toggle enter`) in your keyboard settings.

Notes:

- Terminals are detected (X11) and pasted into with Ctrl+Shift+V.
- Wayland: run `ydotoold`; pass `--paste-keys ctrl+shift+v` to the daemon if you mostly dictate into terminals.
- evdev only listens: the held key still reaches the app. Pick one with no effect on its own.
- CPU only: `large-v3-turbo` is slow; keep `small` or try `base`.

## Check

```sh
systemctl --user status crescendo-whisper crescendo
python3 bin/dictate history -v
journalctl --user -u crescendo -f
```

Quick test without the shortcut:

```sh
arecord -f S16_LE -r 16000 -c 1 -d 5 test.wav && python3 bin/dictate test.wav
```

## Uninstall

```sh
scripts/uninstall-linux.sh            # services, shortcuts, whisper.cpp build, models, history
scripts/uninstall-linux.sh --ollama   # + the cleanup model
```

Ollama and system packages are kept.

## What CI verifies

- Test suite on Ubuntu and macOS.
- A real paste into an `xterm` under Xvfb (clipboard restored).
- `install-linux.sh` on a fresh Ubuntu, then a spoken French sample transcribed end to end, then uninstall.

Not verified: real microphones, real desktops, Wayland. Reports welcome.
