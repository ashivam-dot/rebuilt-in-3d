"""Narration with Kokoro-82M (Apache-2.0): the af_kore voice at 1.25x, with the timing of every spoken word."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from .spec import Short

VOICE, SPEED, LANG = "af_kore", 1.25, "a"
SAMPLE_RATE = 24000
LEAD_IN = 0.35
SPEECH_FLOOR = 0.01
_PUNCT = set(".,!?;:\u2026\u2014\u2013-\"'()[]\u201c\u201d\u2018\u2019")
_pipeline = None


@dataclass
class Word:
    text: str
    start: float
    end: float
    beat: int


def _kokoro():
    global _pipeline
    if _pipeline is None:
        from kokoro import KPipeline

        _pipeline = KPipeline(lang_code=LANG, repo_id="hexgrad/Kokoro-82M")
    return _pipeline


def _words(tokens, offset: float, beat: int) -> list[Word]:
    merged, pending = [], None
    for tok in tokens:
        if tok.start_ts is None or tok.end_ts is None:
            continue
        if pending is None:
            pending = [tok.text, offset + tok.start_ts, offset + tok.end_ts]
        else:
            pending[0] += tok.text
            pending[2] = offset + tok.end_ts
        if tok.whitespace:
            merged.append(pending)
            pending = None
    if pending is not None:
        merged.append(pending)
    words: list[Word] = []
    for text, start, end in merged:
        text = text.strip()
        if not text:
            continue
        if all(ch in _PUNCT for ch in text):
            if words:
                words[-1].text += text
            continue
        words.append(Word(text, start, max(end, start + 0.05), beat))
    return words


def _trim(audio: np.ndarray, rate: int = SAMPLE_RATE) -> np.ndarray:
    loud = np.flatnonzero(np.abs(audio) > SPEECH_FLOOR * np.abs(audio).max(initial=0.0))
    if not loud.size:
        return audio
    keep = int(0.05 * rate)
    return audio[max(0, loud[0] - keep): loud[-1] + keep + 1]


def _clock(m: re.Match) -> str:
    h, mins = int(m.group(1)), int(m.group(2))
    if mins == 0 and h in (0, 12):
        return "midnight" if h == 0 else "noon"
    hour = f"{h % 12 or 12}"
    mm = "" if mins == 0 else f" oh {mins}" if mins < 10 else f" {mins}"
    return f"{hour}{mm} {'a.m.' if h < 12 else 'p.m.'}"


def speakable(text: str) -> str:
    """What Kokoro should read: symbols and clock times spelled the way a newsreader says them."""
    text = re.sub(r"\b(\d{1,2}):(\d{2})\b", _clock, text)
    return text.replace("≈", "about ").replace("%", " percent")


TTS_DIR = Path(__file__).resolve().parents[1] / "tts"
STYLE = {"tribute": {"exaggeration": 0.7, "cfg_weight": 0.35}, "news": {"exaggeration": 0.55, "cfg_weight": 0.45}}
MIN_MATCH = 0.8


def _chatterbox(lines: list[str], out: Path, style: dict, seed: int) -> list[dict]:
    import subprocess

    job = out / "job.json"
    out.mkdir(parents=True, exist_ok=True)
    job.write_text(json.dumps({"lines": lines, "out": str(out), "seed": seed, **style}), encoding="utf-8")
    python = TTS_DIR / ".venv" / "bin" / "python"
    subprocess.run([str(python), str(TTS_DIR / "speak.py"), str(job)], check=True, stdout=subprocess.DEVNULL)
    return json.loads((out / "lines.json").read_text(encoding="utf-8"))


def synthesize_story(short: Short, out_dir: Path) -> dict:
    """Chatterbox narration, one take per beat, each checked by Whisper; same outputs as synthesize()."""
    from . import align

    mood = short.scene.get("mood", "tribute")
    texts = [speakable(b.text) for b in short.beats]
    takes = _chatterbox(texts, out_dir / "takes", STYLE.get(mood, STYLE["tribute"]), seed=7)
    clips, checks = [], []
    for i, (beat, take) in enumerate(zip(short.beats, takes)):
        best = None
        for attempt in range(3):
            if attempt:
                take = _chatterbox([texts[i]], out_dir / f"retake{i:02d}-{attempt}", STYLE.get(mood, STYLE["tribute"]),
                                   seed=100 + 31 * attempt + i)[0]
            audio, sr = sf.read(take["file"], dtype="float32")
            audio = _trim(audio if audio.ndim == 1 else audio.mean(axis=1), sr)
            heard = align.transcribe(audio, sr)
            words, match = align.align(beat.text, heard, len(audio) / sr)
            if best is None or match > best[2]:
                best = (audio, words, match)
            if match >= MIN_MATCH:
                break
        if best[2] < MIN_MATCH:
            raise ValueError(f"voice: beat {i + 1} came out garbled ({best[2]:.0%} of words heard)")
        clips.append(best)
        checks.append(round(best[2], 2))
    rate = sr
    pieces = [np.zeros(int(LEAD_IN * rate), dtype=np.float32)]
    t, words, spans = LEAD_IN, [], []
    for index, (beat, (audio, beat_words, _)) in enumerate(zip(short.beats, clips)):
        start = t
        words.extend(Word(w["text"], round(t + w["start"], 3), round(t + w["end"], 3), index) for w in beat_words)
        pieces.append(audio)
        t += len(audio) / rate
        pieces.append(np.zeros(int(beat.pause_after * rate), dtype=np.float32))
        t += beat.pause_after
        spans.append([round(start, 3), round(t, 3)])
    audio = np.concatenate(pieces)
    sf.write(out_dir / "narration.wav", audio, rate)
    timing = {"duration": round(t, 3), "words": [asdict(w) for w in words], "beats": spans,
              "voice": {"engine": "chatterbox", **STYLE.get(mood, STYLE["tribute"]), "heard": checks},
              "sample_rate": rate}
    (out_dir / "timing.json").write_text(json.dumps(timing, indent=1), encoding="utf-8")
    return timing


def synthesize(short: Short, out_dir: Path) -> dict:
    """narration.wav plus timing.json: {duration, words, beats: [[start, end], ...]}."""
    if short.scene.get("template") == "story":
        return synthesize_story(short, out_dir)
    pipe = _kokoro()
    out_dir.mkdir(parents=True, exist_ok=True)
    pieces = [np.zeros(int(LEAD_IN * SAMPLE_RATE), dtype=np.float32)]
    t, words, spans = LEAD_IN, [], []
    for index, beat in enumerate(short.beats):
        start = t
        for result in pipe(speakable(beat.text), voice=VOICE, speed=SPEED):
            audio = result.audio.numpy().astype(np.float32)
            words.extend(_words(result.tokens or [], t, index))
            pieces.append(audio)
            t += len(audio) / SAMPLE_RATE
        pieces.append(np.zeros(int(beat.pause_after * SAMPLE_RATE), dtype=np.float32))
        t += beat.pause_after
        spans.append([round(start, 3), round(t, 3)])
    audio = np.concatenate(pieces)
    sf.write(out_dir / "narration.wav", audio, SAMPLE_RATE)
    timing = {"duration": round(t, 3), "words": [asdict(w) for w in words], "beats": spans,
              "voice": {"engine": "kokoro", "voice": VOICE, "speed": SPEED}}
    (out_dir / "timing.json").write_text(json.dumps(timing, indent=1), encoding="utf-8")
    return timing
