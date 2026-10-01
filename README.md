# crescendo

Push-to-talk dictation for macOS. 100 % local. Types into any app.

- Hold **⌥Space**, speak, release → text is pasted at the cursor.
- Hold **⌥⇧Space** → same, then **Enter**.
- Works in terminals, Claude Code, Codex, VS Code, Slack, browsers, any text field.

> **Platforms:** macOS on Apple Silicon, Linux (see [below](#linux)).

## Features

- **Local.** [whisper.cpp](https://github.com/ggml-org/whisper.cpp) for speech-to-text, [Ollama](https://ollama.com) for cleanup.
- **No account, no API key.** Models download anonymously once. Nothing leaves your Mac.
- **Cleanup that never answers.** Fillers and punctuation are fixed; your prompt is never executed.
- **Guardrails.** Suspicious LLM output → raw transcript inserted instead.
- **Hallucination filter.** Silence is skipped; "Thanks for watching!"-style artifacts are removed.
- **Custom vocabulary.** Primes Whisper, fixes casing, applies replacements.
- **Clean paste.** One atomic paste; your clipboard is restored.
- **Mixed languages.** Tuned for French with English technical terms.

## Requirements

- Apple Silicon Mac, macOS (tested on 26).
- [Homebrew](https://brew.sh) in `/opt/homebrew`.
- ~3 GB free RAM, ~3 GB disk.

## Install

```sh
git clone https://github.com/eytanlvy/crescendo.git
cd crescendo
scripts/install.sh
```

The installer:

- installs `whisper.cpp`, `sox`, `ollama` and Hammerspoon (Homebrew);
- downloads the models;
- starts both services at login (LaunchAgents);
- creates your `vocabulary.txt`;
- hooks into `~/.hammerspoon/init.lua`.

Then grant permissions to **Hammerspoon** in System Settings ▸ Privacy & Security:

1. **Accessibility** — required to paste.
2. **Microphone** — or accept the prompt on first use.
3. **Restart Hammerspoon.**

Check the setup:

```sh
bin/doctor
```

## Usage

| Action | Result |
|---|---|
| Hold ⌥Space, speak, release | Paste |
| Hold ⌥⇧Space, speak, release | Paste + Enter |
| Esc while holding | Cancel |
| Tap < 0.3 s | Ignored |
| Hold > 2 min | Stops and transcribes |

- A sound marks start and end.
- A floating pill shows `● REC`, then `…`.
- The 🎙 menu re-pastes your last 5 dictations.

## Vocabulary

Fill it in. It is the biggest accuracy gain.

- File: `vocabulary.txt` (git-ignored, re-read on every dictation).
- **Terms:** one per line, most important first. They prime Whisper and fix casing.
- **Replacements:** `heard => written`, applied last.

```text
Kubernetes
pgvector

# Replacements
cube control => kubectl
```

- Write it by hand, or ask an LLM to draft it from your projects.
- Example prompt: *"List the 40 terms from this repository a speech recognizer is most likely to misspell, one per
  line, most important first. Then add likely mis-hearings as `heard => written`."*
- Improve it from real mistakes: `bin/dictate history -v`.

## Configuration

All settings live in [`config.toml`](config.toml). Reload Hammerspoon after editing.

- **Hotkeys:** `[hotkeys]` — e.g. `"alt+space"`, `"ctrl+shift+d"`, `"f13"`.
- **Language:** `[whisper] language` — pin it (`"fr"`, `"en"`). Faster and more accurate than `"auto"`.
- **Whisper model:** `[whisper] model`, then re-run `scripts/install.sh`.
- **Cleanup model:** `[cleanup] model`, then re-run `scripts/install.sh`.
- **Cleanup mode:** `"always"` or `"auto"` (LLM only when needed, ~0.65 s faster).
- **Disable cleanup:** `[cleanup] enabled = false`.

## History

- Every dictation is logged to `~/.local/share/voice-dictation/history.jsonl`.
- Includes: target app, raw and final text, per-stage latency.
- Recordings are deleted after transcription (`keep_audio = N` keeps the last N in `audio/`).

```sh
bin/dictate history -n 20 -v   # recent dictations, with raw text
bin/dictate history --stats    # latency per stage
```

## Performance

Measured on an M2 Pro, 16 GB.

- Release → text inserted: **~2.0 s** (median, real use).
- Whisper ~0.9 s, cleanup ~0.65 s.
- Memory: **~2.9 GB** with both models loaded.

| Speech-to-text | WER | Latency |
|---|---|---|
| **large-v3-turbo q8_0, `fr`** | **6.7 %** | **0.81 s** |
| large-v3-turbo q5_0, `fr` | 7.2 % | 0.89 s |
| large-v3-turbo q8_0, `auto` | 7.8 % | 1.49 s |

| Cleanup LLM | Faithful | Latency |
|---|---|---|
| **qwen2.5:3b-instruct** | yes | ~0.3 s |
| gemma3:4b | yes | 0.4–1.4 s |
| qwen3:4b-instruct | mostly | ~0.4 s |
| llama3.2:3b | no (translates) | ~0.4 s |
| qwen2.5:1.5b-instruct | no (translates) | ~0.2 s |

Need more speed?

- `cleanup.mode = "auto"` → −0.65 s.
- `qwen2.5:1.5b-instruct` → −0.1 s, less faithful.
- `recording.tail_ms = 50` → −0.1 s, may clip the last syllable.

Benchmarks: `bench/`.

## Troubleshooting

Run `bin/doctor` first.

| Symptom | Fix |
|---|---|
| ⌥Space does nothing | Check Accessibility, then restart Hammerspoon |
| ⌥Space types a space | Reload Hammerspoon |
| `REC` but no text | Check Microphone permission and input device |
| "Whisper unavailable" | `launchctl kickstart -k gui/$(id -u)/com.voice-dictation.whisper` |
| Raw text inserted | `launchctl kickstart -k gui/$(id -u)/com.voice-dictation.ollama` |
| First words cut | Use the built-in mic; Bluetooth is slow to start |
| A word is always wrong | Add it to `vocabulary.txt` |
| Pasted in the wrong place | Re-paste from the 🎙 menu |

Logs: `~/.local/share/voice-dictation/logs/`.

## Uninstall

```sh
scripts/uninstall.sh          # services, Hammerspoon hook, data, models
scripts/uninstall.sh --brew   # + Homebrew packages and Ollama models
```

- Then remove Hammerspoon from Privacy & Security and Login Items.
- Then delete the repository folder.

## Linux

- Same pipeline, Python daemon as frontend.
- Full guide: [docs/linux.md](docs/linux.md).

```sh
git clone https://github.com/eytanlvy/crescendo.git
cd crescendo
scripts/install-linux.sh
```

The installer:

- installs packages (apt, dnf or pacman; X11 or Wayland tools);
- builds whisper.cpp (CUDA if available) and downloads the model (`large-v3-turbo` with CUDA, `small` otherwise);
- installs Ollama and the cleanup model;
- creates systemd user services (start at login);
- adds GNOME shortcuts: **Ctrl+Alt+Space** to dictate, **Ctrl+Shift+Alt+Space** to dictate + Enter.

Usage and options:

- Toggle mode: press the shortcut to record, press again to paste.
- Hold-to-talk instead: `scripts/install-linux.sh --hold-key KEY_RIGHTCTRL` (re-login required).
- Other desktops: bind `python3 frontends/linux/dictation_daemon.py ctl toggle` to a shortcut.
- Terminals are detected and pasted into with Ctrl+Shift+V.
- Uninstall: `scripts/uninstall-linux.sh`.

## How it works

```
Hammerspoon (Lua)                     bin/dictate (Python, stdlib only)
⌥Space down → record (sox)
⌥Space up   → 16 kHz wav  ────────▶  1. skip silence
                                      2. whisper-server (vocabulary prompt)
                                      3. filter hallucinations
                                      4. Ollama cleanup + guardrails
                                      5. replacements, casing, history
            ◀──────── text ─────────
paste (⌘V), restore clipboard, Enter if ⌥⇧Space
```

- Tests: `uv run pytest`.
- Code comments are in French.

## License

[MIT](LICENSE)
