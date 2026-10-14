"""Word timings for synthetic narration: Whisper (MIT) transcribes the audio with word timestamps, and the script's
own words are aligned onto them, so captions show exactly what was written, at the moment it is spoken.

The transcript doubles as a check that the voice said the script: a low match means a garbled or truncated take.
"""
from __future__ import annotations

import difflib
import re

import numpy as np

MODEL = "openai/whisper-base.en"
_asr = None


def _pipe():
    global _asr
    if _asr is None:
        from transformers import pipeline

        _asr = pipeline("automatic-speech-recognition", model=MODEL, device="cpu")
    return _asr


def _norm(word: str) -> str:
    return re.sub(r"[^a-z0-9]", "", word.lower())


def transcribe(audio: np.ndarray, sr: int) -> list[dict]:
    """[{text, start, end}] from Whisper's word-level timestamps."""
    if sr != 16000:
        n = int(len(audio) * 16000 / sr)
        audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)
    out = _pipe()({"raw": audio.astype(np.float32), "sampling_rate": 16000}, return_timestamps="word",
                  chunk_length_s=30)
    words = []
    for c in out.get("chunks", []):
        start, end = c["timestamp"]
        if start is None:
            continue
        words.append({"text": c["text"].strip(), "start": float(start), "end": float(end if end is not None else start + 0.3)})
    return words


CLOSE = 0.75  # spelling likeness at which a heard word is the script's word ("rahman" for "rehman")


def _spelled_alike(a: list[str], heard: list[dict]) -> tuple[list[str], list[dict]]:
    """Whisper spells names and British words its own way: "Rehman" comes back "Rahman", "kilometres" "kilometers",
    and "Sher Shah" one word "Shershah". A heard word that joins two script words is split in two, and a script word
    of 5+ letters takes the heard spelling when CLOSE alike, so a good take of a foreign name is not called garbled."""
    pairs = {x + y: (x, y) for x, y in zip(a, a[1:]) if x and y}
    split = []
    for h in heard:
        n = _norm(h["text"])
        if n in pairs:
            mid = (h["start"] + h["end"]) / 2
            split += [h | {"text": pairs[n][0], "end": mid}, h | {"text": pairs[n][1], "start": mid}]
        else:
            split.append(h)
    vocab = {_norm(h["text"]) for h in split}
    out = []
    for w in a:
        if len(w) >= 5 and w not in vocab:
            near = difflib.get_close_matches(w, [v for v in vocab if len(v) >= 4], n=1, cutoff=CLOSE)
            w = near[0] if near else w
        out.append(w)
    return out, split


def align(script: str, heard: list[dict], duration: float) -> tuple[list[dict], float]:
    """Script words with times taken from the matching heard words; unmatched words are spread between neighbours.

    Returns (words, match ratio of script words found in the transcript).
    """
    said = script.split()
    a, heard = _spelled_alike([_norm(w) for w in said], heard)
    b = [_norm(w["text"]) for w in heard]
    times: list[tuple[float, float] | None] = [None] * len(said)
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            h = heard[block.b + k]
            times[block.a + k] = (h["start"], h["end"])
    matched = sum(t is not None for t in times)
    # Fill gaps by spreading unmatched words evenly between the surrounding known times.
    i = 0
    while i < len(times):
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < len(times) and times[j] is None:
            j += 1
        lo = times[i - 1][1] if i > 0 else 0.0
        hi = times[j][0] if j < len(times) else duration
        step = max(hi - lo, 0.05 * (j - i)) / (j - i)
        for k in range(i, j):
            times[k] = (lo + step * (k - i), lo + step * (k - i + 1))
        i = j
    words = [{"text": w, "start": round(t[0], 3), "end": round(max(t[1], t[0] + 0.05), 3)} for w, t in zip(said, times)]
    return words, matched / max(len(said), 1)
