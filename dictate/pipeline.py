"""Orchestration : wav → Whisper → filtres → LLM → vocabulaire → texte final (+ historique)."""
from __future__ import annotations

import json
import shutil
import time
from datetime import datetime
from pathlib import Path

from .audio import analyze_wav, ensure_wav
from .cleanup import cleanup
from .filters import clean_transcript, normalize_text, remove_fillers
from .services import ServiceError
from .vocab import Vocabulary, apply_replacements, apply_term_case, build_prompt, load_vocabulary
from .whisper import transcribe

CLEANUP_WARNINGS = {
    "down": "Nettoyage indisponible (Ollama injoignable) : texte brut inséré.",
    "timeout": "Nettoyage trop lent (délai Ollama dépassé) : texte brut inséré.",
    "error": "Erreur Ollama : texte brut inséré.",
}


def _now_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]


def finalize(text: str, vocab: Vocabulary, auto_case: bool) -> str:
    text = apply_replacements(normalize_text(text), vocab.replacements)
    if auto_case:
        text = apply_term_case(text, vocab.terms)
    return normalize_text(text)


def _keep_audio(wav: Path, data_dir: Path, rec_id: str, keep: int) -> None:
    if keep <= 0:
        return
    audio_dir = data_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(wav, audio_dir / f"{rec_id}.wav")
    for old in sorted(audio_dir.glob("*.wav"))[:-keep]:
        old.unlink(missing_ok=True)


def _append_history(data_dir: Path, record: dict) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    with open(data_dir / "history.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def run(wav: Path | str, cfg: dict, mode: str = "insert", app: str | None = None,
        rec_window_ms: float | None = None) -> dict:
    """rec_window_ms : temps entre l'appui et l'arrêt de `rec` vu par Hammerspoon. La différence avec la
    durée réellement enregistrée mesure le délai de démarrage du micro (début de phrase perdu)."""
    t_start = time.perf_counter()
    wav = ensure_wav(wav)
    rec_cfg, w_cfg = cfg["recording"], cfg["whisper"]
    data_dir = Path(cfg["paths"]["data_dir"])
    timings: dict[str, float] = {}
    warnings: list[str] = []
    res: dict = {"id": _now_id(), "status": "ok", "text": "", "warnings": warnings, "timings_ms": timings}
    record: dict = {"ts": datetime.now().isoformat(timespec="milliseconds"), "id": res["id"], "mode": mode,
                    "app": app, "rec_window_ms": rec_window_ms, "whisper_model": Path(w_cfg["model"]).name,
                    "language": w_cfg["language"], "llm_model": cfg["cleanup"]["model"]}

    def lap(name: str, t0: float) -> float:
        now = time.perf_counter()
        timings[name] = round((now - t0) * 1000, 1)
        return now

    def finish(status: str, **extra) -> dict:
        res["status"] = status
        res.update(extra)
        timings["total"] = round((time.perf_counter() - t_start) * 1000, 1)
        record.update(status=status, final=res["text"].rstrip(" "), warnings=warnings, timings_ms=timings,
                      **{k: v for k, v in extra.items() if k not in record})
        try:
            _append_history(data_dir, record)
            if status not in ("too_short",):
                _keep_audio(wav, data_dir, res["id"], rec_cfg["keep_audio"])
        except OSError as e:
            warnings.append(f"Historique non écrit : {e}")
        return res

    t = time.perf_counter()
    info = analyze_wav(wav, rec_cfg["speech_threshold_dbfs"])
    t = lap("analyze", t)
    record.update(duration_s=round(info.duration_s, 3), speech_s=round(info.speech_s, 3),
                  rms_dbfs=round(info.rms_dbfs, 1), peak_dbfs=round(info.peak_dbfs, 1),
                  rec_gap_ms=None if rec_window_ms is None else round(rec_window_ms - info.duration_s * 1000, 1))
    if info.duration_s < rec_cfg["min_duration_s"]:
        return finish("too_short")
    if info.speech_s < rec_cfg["min_speech_s"]:
        return finish("silence")

    try:
        vocab = load_vocabulary(cfg["paths"]["vocabulary"])
    except (OSError, ValueError) as e:
        warnings.append(f"Fichier de vocabulaire ignoré : {e}")
        vocab = Vocabulary()
    prompt = build_prompt(vocab.terms) if w_cfg["use_vocabulary_prompt"] else ""

    try:
        raw = transcribe(wav, w_cfg["url"], w_cfg["language"], prompt, w_cfg["timeout_s"])
    except ServiceError as e:
        lap("whisper", t)
        return finish("error", error=str(e), error_service=e.service, error_kind=e.kind)
    t = lap("whisper", t)
    record["raw"] = raw

    filtered = clean_transcript(raw, prompt)
    t = lap("filter", t)
    record["filtered"] = filtered
    if not filtered or not remove_fillers(filtered):
        return finish("empty")

    cres = cleanup(filtered, cfg["cleanup"])
    t = lap("cleanup", t)
    record.update(cleanup_status=cres.status, llm_output=cres.llm_output)
    res["cleanup_status"] = cres.status
    if cres.status in CLEANUP_WARNINGS:
        warnings.append(CLEANUP_WARNINGS[cres.status])
    text = cres.text if cres.status == "ok" else remove_fillers(filtered)

    final = finalize(text, vocab, cfg["output"]["auto_case_terms"])
    lap("finalize", t)
    if not final:
        return finish("empty")
    res["text"] = final + (" " if cfg["output"]["trailing_space"] and mode != "enter" else "")
    return finish("ok")
