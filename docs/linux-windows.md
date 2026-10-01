# Linux and Windows (experimental)

The pipeline (`bin/dictate`: Whisper → filters → LLM cleanup → vocabulary) is plain Python and is tested on macOS,
Linux and Windows in CI. Only the *frontend* — hotkey, recording, paste — is platform-specific:

| | macOS | Linux | Windows |
|---|---|---|---|
| Frontend | Hammerspoon (`hammerspoon/dictation.lua`) | Python daemon (`frontends/linux/dictation_daemon.py`) | AutoHotkey v2 (`frontends/windows/dictation.ahk`) |
| Hold-to-talk | ⌥Space | evdev hold key (e.g. Right Ctrl), or toggle via a desktop shortcut | Alt+Space |
| Recording | sox `rec` | `arecord` (or sox `rec`) | sox |
| Paste | ⌘V | X11: xclip + xdotool · Wayland: wl-clipboard + ydotool | Ctrl+V |
| Status | supported | **experimental, untested on real desktops** | **experimental, untested on real desktops** |

What CI verifies today: the full test suite on all three OSes, a real paste into an `xterm` under Xvfb (clipboard
restored afterwards), and the AutoHotkey script's syntax. What it cannot verify: microphones, global hotkeys and real
desktop environments — reports and fixes are welcome.

## Services (both platforms)

1. **whisper.cpp server** — build it or grab a release from
   [ggml-org/whisper.cpp](https://github.com/ggml-org/whisper.cpp) (CUDA/Vulkan builds for NVIDIA/AMD GPUs; CPU works
   but `large-v3-turbo` is then slow — consider `ggml-small.bin` or `ggml-base.bin`). Download the model into the
   models directory, then run:
   `whisper-server -m <models>/ggml-large-v3-turbo-q8_0.bin --host 127.0.0.1 --port 8178`
2. **Ollama** — install from [ollama.com](https://ollama.com) (it installs a background service), then
   `ollama pull qwen2.5:3b-instruct`.
3. `cp vocabulary.example.txt vocabulary.txt` and edit it.
4. `python3 bin/dictate config --json` must work; `python3 bin/doctor` is macOS-only for now.

Default paths: Linux `~/.local/share/voice-dictation/`, Windows `%LOCALAPPDATA%\voice-dictation\` (history, audio,
models). Override anything in `config.toml`.

## Linux

```sh
sudo apt install alsa-utils xclip xdotool x11-utils libnotify-bin # X11
sudo apt install alsa-utils wl-clipboard ydotool libnotify-bin   # Wayland (+ start ydotoold)
python3 frontends/linux/dictation_daemon.py run
```

Then bind a desktop shortcut (GNOME: Settings ▸ Keyboard ▸ Custom Shortcuts) to
`python3 /path/to/crescendo/frontends/linux/dictation_daemon.py ctl toggle` — press once to start, once more to
stop and paste (`ctl toggle enter` to also press Enter).

True hold-to-talk needs evdev (works on X11 and Wayland):

```sh
sudo apt install python3-evdev && sudo usermod -aG input $USER   # log out and back in
python3 frontends/linux/dictation_daemon.py run --hold-key KEY_RIGHTCTRL --enter-hold-key KEY_RIGHTALT
```

evdev only *listens*: the key still reaches the focused app, so pick one that does nothing on its own.
In terminals the daemon pastes with Ctrl+Shift+V (detected from the X11 window class; on Wayland pass
`--paste-keys ctrl+shift+v` if you mostly dictate into terminals).

To start at login, a systemd user unit:

```ini
# ~/.config/systemd/user/voice-dictation.service
[Unit]
Description=voice-dictation frontend
After=graphical-session.target

[Service]
ExecStart=/usr/bin/python3 %h/crescendo/frontends/linux/dictation_daemon.py run
Restart=on-failure

[Install]
WantedBy=graphical-session.target
```

`systemctl --user enable --now voice-dictation` (do the same for `whisper-server`).

## Windows

1. Install [Python 3.11+](https://www.python.org/downloads/) (tick "Add to PATH"), [AutoHotkey v2](https://www.autohotkey.com),
   and [sox](https://sourceforge.net/projects/sox/) (add its folder to PATH, or set `recording.rec_binary` to the full
   path of `sox.exe`).
2. Start whisper-server and Ollama (see above).
3. Double-click `frontends\windows\dictation.ahk`. Hold **Alt+Space**, speak, release (Alt+Shift+Space adds Enter;
   Esc cancels). To start at login, put a shortcut to the script in `shell:startup`.

Alt+Space normally opens the window menu: AutoHotkey intercepts it while the script runs. Clipboard content is
restored after pasting, but Windows' clipboard history (Win+V) may still record the dictated text.
