"""Finish: the chapters into one episode, and the checks it must pass before anything may upload it.

Sound: each chapter's narration at one loudness, padded to its frame-exact length (scenes.chapter_seconds), joined;
a music bed scored per chapter (a different seed, and a calmer mood for the explaining chapters) and joined; then the
Shorts' own duck-and-loudnorm graph (compose.duck, -14 LUFS). Picture: the chapter files joined without re-encoding.
Checks (QA, all must pass): 1920x1080 at 30 fps; MIN_SECONDS to MAX_SECONDS (hard cap 14:30); no black stretch of
BLACK_SECONDS; no frozen stretch of FREEZE_SECONDS. Writes episode.mp4, thumbnail.jpg, captions.srt, description.txt
and meta.json (everything publish.py needs).
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from .. import music
from ..compose import duck
from . import describe, scenes, thumb
from .spec import Episode

MIN_SECONDS = 8 * 60
MAX_SECONDS = 14 * 60 + 30
BLACK_SECONDS = 2.0
FREEZE_SECONDS = 6
SPEECH_RMS = 0.08
CALM = {"how-it-works", "people", "why-it-matters"}


def rms(x: np.ndarray) -> float:
    loud = x[np.abs(x) > 0.01]
    return float(np.sqrt(np.mean(loud ** 2))) if loud.size else 0.0


def narration(chapter_dirs: list[Path], lengths: list[float], out: Path) -> Path:
    pieces, rate = [], None
    for d, seconds in zip(chapter_dirs, lengths):
        audio, sr = sf.read(d / "narration.wav", dtype="float32")
        audio = audio if audio.ndim == 1 else audio.mean(axis=1)
        if rate is None:
            rate = sr
        elif sr != rate:
            raise ValueError(f"{d}: narration at {sr} Hz, the others at {rate} Hz")
        level = rms(audio)
        if level:
            audio = np.clip(audio * (SPEECH_RMS / level), -0.98, 0.98)
        n = int(round(seconds * rate))
        pieces.append(np.pad(audio, (0, max(0, n - len(audio))))[:n])
    sf.write(out, np.concatenate(pieces), rate)
    return out


def bed(ep: Episode, lengths: list[float], out: Path) -> Path:
    parts = [music.score(seconds, "tribute" if ch.key in CALM else "news", f"{ep.id}:{ch.key}")
             for ch, seconds in zip(ep.chapters, lengths)]
    sf.write(out, np.concatenate(parts), music.SR)
    return out


def probe(mp4: Path) -> dict:
    raw = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate:"
                          "format=duration", "-of", "json", str(mp4)], capture_output=True, text=True, check=True).stdout
    data = json.loads(raw)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    num, den = video["r_frame_rate"].split("/")
    return {"width": video["width"], "height": video["height"], "fps": round(int(num) / int(den), 3),
            "seconds": float(data["format"]["duration"]),
            "audio": any(s["codec_type"] == "audio" for s in data["streams"])}


def defects(mp4: Path) -> dict:
    """Black and frozen stretches, from ffmpeg's blackdetect and freezedetect."""
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(mp4), "-vf",
                          f"blackdetect=d={BLACK_SECONDS}:pix_th=0.08,freezedetect=n=-60dB:d={FREEZE_SECONDS}",
                          "-an", "-f", "null", "-"], capture_output=True, text=True).stderr
    black = [float(x) for x in re.findall(r"black_duration:([\d.]+)", err)]
    frozen = [float(x) for x in re.findall(r"freeze_duration: ([\d.]+)", err)]
    return {"black": black, "frozen": frozen}


def qa(info: dict, found: dict) -> list[str]:
    problems = []
    if (info["width"], info["height"]) != (scenes.W, scenes.H):
        problems.append(f"{info['width']}x{info['height']}, not {scenes.W}x{scenes.H}")
    if abs(info["fps"] - scenes.FPS) > 0.01:
        problems.append(f"{info['fps']} fps, not {scenes.FPS}")
    if not info.get("audio"):
        problems.append("no audio")
    if not MIN_SECONDS <= info["seconds"] <= MAX_SECONDS:
        problems.append(f"{info['seconds']:.0f} s long: an episode runs {MIN_SECONDS // 60}-{MAX_SECONDS / 60:.1f} min")
    if found["black"]:
        problems.append(f"black stretches of {found['black']} s")
    if found["frozen"]:
        problems.append(f"frozen stretches of {found['frozen']} s")
    return problems


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def captions(chapters: list[tuple[float, list[str], list[list[float]]]]) -> str:
    """SRT from each chapter's start, sentences and their spans."""
    out, n = [], 0
    for start, lines, spans in chapters:
        for text, (a, b) in zip(lines, spans):
            n += 1
            out.append(f"{n}\n{srt_time(start + a)} --> {srt_time(start + max(a + 0.5, b - 0.2))}\n{text}\n")
    return "\n".join(out)


def finish(work: Path) -> dict:
    """work holds episode.json and chapters/<key>/ (chapter.json, timing.json, narration.wav, chapter.mp4, hero.png)."""
    ep = Episode.load(work / "episode.json")
    dirs = [work / "chapters" / ch.key for ch in ep.chapters]
    for d in dirs:
        for name in ("chapter.json", "timing.json", "narration.wav", "chapter.mp4"):
            if not (d / name).exists():
                raise FileNotFoundError(f"{d / name}: the chapter's make job did not finish")
    timings = [json.loads((d / "timing.json").read_text()) for d in dirs]
    lengths = [scenes.chapter_seconds(t, i == len(dirs) - 1) for i, t in enumerate(timings)]
    total = sum(lengths)
    starts = list(np.cumsum([0.0] + lengths[:-1]))
    narration(dirs, lengths, work / "narration.wav")
    bed(ep, lengths, work / "music.wav")
    duck(work / "narration.wav", work / "music.wav", total, work / "mix.wav")
    (work / "concat.txt").write_text("".join(f"file '{(d / 'chapter.mp4').resolve()}'\n" for d in dirs))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(work / "concat.txt"),
                    "-i", str(work / "mix.wav"), "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a",
                    "192k", "-movflags", "+faststart", str(work / "episode.mp4")], check=True)
    info, found = probe(work / "episode.mp4"), defects(work / "episode.mp4")
    problems = qa(info, found)
    chapters = [(ch.title, float(s)) for ch, s in zip(ep.chapters, starts)]
    desc = describe.description(ep, chapters, lengths[-1])
    (work / "description.txt").write_text(desc, encoding="utf-8")
    lines = [json.loads((d / "chapter.json").read_text())["lines"] for d in dirs]
    (work / "captions.srt").write_text(captions([(float(s), ln, t["beats"]) for s, ln, t in
                                                 zip(starts, lines, timings)]), encoding="utf-8")
    hero = next((d / "hero.png" for d in dirs if (d / "hero.png").exists()), None)
    if hero is None:
        raise FileNotFoundError("no chapter's make job left a hero.png for the thumbnail")
    thumbnail = thumb.build(hero, ep, work / "thumbnail.jpg")
    if not thumbnail["ok"]:
        problems.append("the thumbnail's words did not pass the legibility test")
    digest = hashlib.sha256((work / "episode.mp4").read_bytes()).hexdigest()
    meta = {"id": ep.id, "title": ep.title, "topic_key": ep.why.get("topic_key"),
            "override": str(ep.why.get("how") or "").startswith("owner override"), "publish_at": ep.publish_at,
            "tags": ep.tags, "seconds": round(info["seconds"], 2), "chapters": [[t, round(s, 2)] for t, s in chapters],
            "probe": info, "defects": found, "problems": problems, "thumbnail": thumbnail, "sha256": digest,
            "related": ep.related, "words": sum(len(x.split()) for ln in lines for x in ln)}
    (work / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    if problems:
        raise RuntimeError("the episode failed QA: " + "; ".join(problems))
    return meta
