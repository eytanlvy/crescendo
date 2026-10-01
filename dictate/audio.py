"""Analyse d'un wav PCM 16 bits (stdlib) : durée, niveaux, durée de parole active."""
from __future__ import annotations

import math
import operator
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path

FRAME_S = 0.03
FLOOR_DBFS = -120.0


@dataclass
class WavInfo:
    duration_s: float
    rms_dbfs: float
    peak_dbfs: float
    speech_s: float


def _dbfs(ratio: float) -> float:
    return 20 * math.log10(ratio) if ratio > 0 else FLOOR_DBFS


def analyze_wav(path: Path | str, speech_threshold_dbfs: float = -42.0) -> WavInfo:
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError(f"{path}: seul le PCM 16 bits est supporté")
        rate, channels = w.getframerate(), w.getnchannels()
        samples = array("h")
        samples.frombytes(w.readframes(w.getnframes()))
    if channels > 1:
        samples = samples[::channels]  # premier canal suffit pour une estimation de niveau
    n = len(samples)
    if n == 0:
        return WavInfo(0.0, FLOOR_DBFS, FLOOR_DBFS, 0.0)

    frame = max(1, int(rate * FRAME_S))
    threshold = (10 ** (speech_threshold_dbfs / 20) * 32768) ** 2
    total_sq = 0
    speech_frames = 0
    for start in range(0, n, frame):
        chunk = samples[start:start + frame]
        sq = sum(map(operator.mul, chunk, chunk))
        total_sq += sq
        if sq / len(chunk) >= threshold:
            speech_frames += len(chunk)
    peak = max(max(samples), -min(samples))
    return WavInfo(
        duration_s=n / rate,
        rms_dbfs=_dbfs(math.sqrt(total_sq / n) / 32768),
        peak_dbfs=_dbfs(peak / 32768),
        speech_s=speech_frames / rate,
    )


RAW_SUFFIXES = {".pcm", ".raw"}


def ensure_wav(path: Path | str, rate: int = 16000) -> Path:
    """Enveloppe un enregistrement PCM brut (s16le mono) dans un wav. Les enregistreurs tués brutalement
    (Windows, Linux) ne finalisent pas l'en-tête wav : le PCM brut reste toujours lisible."""
    path = Path(path)
    if path.suffix.lower() not in RAW_SUFFIXES:
        return path
    wav = path.with_suffix(".wav")
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        data = path.read_bytes()
        w.writeframes(data[:len(data) - len(data) % 2])
    return wav
