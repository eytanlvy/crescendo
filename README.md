# voice-dictation

**Push-to-talk dictation for macOS that runs 100 % locally and types anywhere** — Claude Code, Codex, any terminal,
VS Code, Slack, your browser, any text field.

Hold **⌥Space**, speak, release: the transcribed and cleaned-up text is pasted at your cursor.
Hold **⌥⇧Space** instead and it also presses **Enter** — handy to send a prompt to a coding agent straight away.

<!-- Demo GIF: docs/demo.gif (see "Recording the demo GIF" at the end) -->

Built for developers who dictate prompts in a mix of languages (it was tuned on French peppered with English
technical terms), it is deliberately small: a thin [Hammerspoon](https://www.hammerspoon.org) script for the hotkey,
UI and pasting, and a dependency-free Python pipeline you can run and test from the command line.

> **Platform:** macOS on Apple Silicon only (tested on an M2 Pro, macOS 26). Linux and Windows are not supported yet.

## Highlights

- **Fully local, no account, no API key.** Speech-to-text is [whisper.cpp](https://github.com/ggml-org/whisper.cpp)
  (`large-v3-turbo`, Metal) running as a resident server; cleanup is a 3B model served by [Ollama](https://ollama.com).
  Models are downloaded anonymously once (Hugging Face, Ollama registry); after that nothing leaves your Mac.
- **An LLM cleanup that never "answers".** Dictating *"write a function that…"* must give you that sentence, not the
  function. The prompt frames the transcript as data, and guardrails reject any output that looks like an answer
  (preamble, code or a list that wasn't dictated, a question turned into a statement, much longer text, new words,
  dropped content, translation). On rejection, timeout or if Ollama is down, the raw transcript is inserted.
- **Hallucination filtering.** Silence never reaches Whisper (speech-energy gate), and the classic Whisper
  hallucinations (*"Thanks for watching!"*, *"Sous-titres réalisés par la communauté d'Amara.org"*, `[BLANK_AUDIO]`,
  decoding loops, prompt echo) are removed.
- **Your vocabulary.** An editable word list primes Whisper and fixes casing (`github` → `GitHub`); a replacement
  table fixes recurring mistakes (`cloud code` → `Claude Code`).
- **Reliable insertion.** One atomic paste (no character-by-character typing), your clipboard is restored afterwards
  and the temporary content is marked transient so clipboard managers ignore it.
- **Measurable.** Every dictation is logged with per-stage latencies; `bin/doctor` checks the whole setup.

## Requirements

| | |
|---|---|
| Hardware | Apple Silicon Mac, ~3 GB of free RAM (both models stay loaded) |
| Software | macOS (tested on 26; 14+ should work), [Homebrew](https://brew.sh) in `/opt/homebrew`, Python 3.11+ (Homebrew's) |
| Disk | ~3 GB (Whisper model 0.9 GB, cleanup model 1.9 GB) |
| Permissions | Microphone and Accessibility for Hammerspoon |

## Install

```sh
git clone https://github.com/<you>/voice-dictation.git
cd voice-dictation
scripts/install.sh
```

The installer is idempotent. It installs `whisper.cpp`, `sox`, `ollama` and Hammerspoon with Homebrew, downloads
the models, creates two LaunchAgents (`whisper-server` and `ollama serve`, started at login and kept alive), copies
`vocabulary.example.txt` to your own `vocabulary.txt`, and adds a small block to `~/.hammerspoon/init.lua`.

Then grant the permissions (macOS only lets you do this by hand):

1. **System Settings ▸ Privacy & Security ▸ Accessibility** → enable **Hammerspoon** (needed to paste).
2. **System Settings ▸ Privacy & Security ▸ Microphone** → enable **Hammerspoon** (or accept the prompt on first use).
3. If the repo lives in `~/Desktop` or `~/Documents`, accept *"Hammerspoon would like to access files in your
   Desktop folder"*.
4. Quit and reopen Hammerspoon (accessibility changes are only picked up after a restart).

Check everything:

```sh
bin/doctor
```

## Usage

| Action | Result |
|---|---|
| Hold **⌥Space**, speak, release | text pasted at the cursor |
| Hold **⌥⇧Space**, speak, release | text pasted, then **Enter** |
| **Esc** while holding | cancel |
| Tap shorter than 0.3 s | ignored |
| Hold longer than 2 min | recording stops and is transcribed |

Feedback: a soft sound when recording starts and when the text is inserted, a floating `● REC 0:03` pill while
recording and `…` while processing. The 🎙 menu-bar item lets you re-paste one of your last five dictations (useful if
the focus moved) and opens the config, vocabulary and history.

Everything also works from the command line:

```sh
bin/dictate recording.wav          # prints the final text
bin/dictate recording.wav --json   # full result: raw text, cleanup status, per-stage timings
```

## Vocabulary — fill it in, it matters

Whisper is good, but it cannot guess your project names, your colleagues' names or your in-house acronyms. Accuracy
on those depends almost entirely on `vocabulary.txt` (git-ignored, so it never ends up in your commits). It is
re-read on every dictation.

```text
# Terms, most important first: they prime Whisper (≈224-token budget) and fix casing.
Kubernetes
pgvector
Alice Martin

# Replacements, applied last: "heard => written".
cube control => kubectl
```

Fill it by hand, or ask an LLM to draft it from your context — for example in Claude Code, at the root of a project:

> *Read this repository (README, package names, modules, main identifiers) and write a `vocabulary.txt` for a
> speech-to-text tool: one term per line, the 40 terms a speech recognizer is most likely to misspell, most important
> first. Then add a `# Replacements` section with likely mis-hearings in the form `heard => written`.*

Then review it, and keep improving it from real mistakes: `bin/dictate history -v` shows the raw transcript next
to the final text.

## Configuration

Everything lives in [`config.toml`](config.toml), commented. Reload Hammerspoon after editing (menu ▸ Reload
Config); a typo is reported with the offending key.

- **Hotkeys:** `[hotkeys] dictate = "alt+space"` — modifiers `cmd`, `alt`, `ctrl`, `shift`; keys `a`–`z`, `0`–`9`,
  `space`, `f1`–`f20`…
- **Whisper model or threads:** edit `[whisper] model` (any `ggml-*.bin` from
  [whisper.cpp's models](https://huggingface.co/ggerganov/whisper.cpp)), then re-run `scripts/install.sh`, which
  downloads it and regenerates the LaunchAgent.
- **Language:** `[whisper] language = "fr"`, `"en"` or `"auto"`. Pin your main language: in our tests it was both
  more accurate *and* twice as fast as `auto`, even on English sentences.
- **Cleanup model:** `[cleanup] model = "qwen2.5:3b-instruct"`, then `scripts/install.sh` (pulls it).
- **Cleanup mode:** `"always"` or `"auto"` (only call the LLM when the transcript contains hesitations, repeated
  words or lacks punctuation — saves ~650 ms on most dictations, see below), or `enabled = false`.

## History

Each dictation is appended to `~/.local/share/voice-dictation/history.jsonl` (timestamp, target app, raw and final
text, cleanup status, per-stage latencies, microphone start-up delay); the last 50 recordings are kept in `audio/`
(`keep_audio = 0` to disable). Nothing is ever sent anywhere.

```sh
bin/dictate history -n 20 -v   # last dictations, with raw transcripts
bin/dictate history --stats    # p50 / max latency per stage
```

## Performance (measured)

On an M2 Pro (16 GB), real usage, median: **Whisper ≈ 0.9 s, cleanup ≈ 0.65 s, release → text inserted ≈ 2.0 s**.
Resident memory with both models loaded: **≈ 2.9 GB** (whisper-server 0.9 GB, Ollama runner 2.0 GB).

Speech-to-text, 8 synthetic French/English code-switching samples, vocabulary prompt on:

| Model / language | WER | Technical terms exact | Latency p50 |
|---|---|---|---|
| **large-v3-turbo q8_0, `fr`** | **6.7 %** | **19/24** | **0.81 s** |
| large-v3-turbo q5_0, `fr` | 7.2 % | 17/24 | 0.89 s |
| large-v3-turbo q8_0, `auto` | 7.8 % | 17/24 | 1.49 s |
| reduced `audio_ctx` | > 75 % | 1/24 | unusable with turbo |

Cleanup LLM, 18 adversarial inputs (orders, questions, "translate…", "ignore previous instructions…", already
clean text). Every "answer" was caught by the guardrails, so the remaining question is how often the cleanup is
usable and faithful:

| Model | Accepted | Faithful when accepted | Latency p50 |
|---|---|---|---|
| **qwen2.5:3b-instruct** | 16–17/18 | yes | 0.26–0.32 s |
| llama3.2:3b | 13/18 | no (partial translation) | 0.38 s |
| qwen3:4b-instruct-2507 | 16/18 | mostly (one invented word) | 0.36–0.45 s |
| gemma3:4b | 17/18 | yes | 0.41–1.38 s |
| qwen2.5:1.5b-instruct | 16/18 | no (translated English to French) | 0.19 s |

Trade-offs if you need it faster: `cleanup.mode = "auto"` (−0.65 s on clean transcripts: Whisper turbo rarely
outputs hesitations), `qwen2.5:1.5b-instruct` (−0.1 s, less faithful), `recording.tail_ms = 50` (−0.1 s, may clip the
last syllable).

Reproduce: `bench/make_samples.py`, `bench/bench_whisper.py`, `bench/bench_llm.py`.

## Troubleshooting

Start with `bin/doctor`: it checks the config, binaries, models, services, permissions, hotkeys, memory and runs a
sample through the pipeline.

| Symptom | Fix |
|---|---|
| Nothing happens on ⌥Space | Hammerspoon running? Menu-bar 🎙 present? Accessibility granted, then Hammerspoon **restarted**? |
| "REC" shows but text is empty | Microphone permission for Hammerspoon; check the input device in System Settings ▸ Sound |
| ⌥Space types a non-breaking space | the hotkey is not registered: reload Hammerspoon, look at its console |
| "Whisper server unavailable" | `launchctl kickstart -k gui/$(id -u)/com.voice-dictation.whisper`, logs in `~/.local/share/voice-dictation/logs/` |
| "cleanup unavailable", raw text inserted | `launchctl kickstart -k gui/$(id -u)/com.voice-dictation.ollama` |
| First words cut off | Bluetooth headsets take long to open the mic: prefer the built-in mic, or start speaking a beat later |
| A word is always wrong | add it to `vocabulary.txt` (term or replacement) |
| Text pasted in the wrong place | focus changed during processing: re-paste it from the 🎙 menu |

## Uninstall

```sh
scripts/uninstall.sh           # services, Hammerspoon block, history, audio, Whisper models
scripts/uninstall.sh --brew    # also: whisper.cpp, sox, ollama + the models pulled for this project, Hammerspoon
rm -rf voice-dictation         # the repository itself
```

Finally remove Hammerspoon from System Settings ▸ Privacy & Security (Accessibility, Microphone) and from Login Items.

## How it works

```
Hammerspoon (Lua)                               bin/dictate (Python, stdlib only)
─────────────────                               ─────────────────────────────────
⌥Space down → sound + overlay + `rec` (sox)
⌥Space up   → +150 ms → stop → 16 kHz wav  ──▶  1. speech-energy gate (silence never reaches Whisper)
                                                2. whisper-server /inference (vocabulary prompt)
                                                3. hallucination filter
                                                4. Ollama cleanup + guardrails (fallback: raw text)
                                                5. replacements + casing, history.jsonl
            ◀── JSON on stdout ───────────────
transient clipboard → ⌘V → restore clipboard (+ Enter with ⌥⇧Space)
```

Tests: `uv run pytest` (unit tests, fake HTTP servers for both services). Code comments are in French.

## Recording the demo GIF

Record ~15 s with ⌘⇧5 (selected area), then:

```sh
brew install ffmpeg
ffmpeg -i demo.mov -vf "fps=12,scale=900:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse" docs/demo.gif
```

## License

[MIT](LICENSE)
