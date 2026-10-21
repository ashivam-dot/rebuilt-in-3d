"""The episode's description, within YouTube's 5000 bytes: summary, then "Chapters:" with real timestamps (YouTube
makes chapters from them only when the first is 00:00, there are at least three, each at least 10 s, ascending), then
credits and the disclosure: those are required and raise rather than be cut. Sources, related Shorts and hashtags
follow while they fit. "<" and ">" are not allowed in a description and are dropped."""
from __future__ import annotations

from .spec import Episode

LIMIT = 5000
MIN_CHAPTERS = 3
MIN_CHAPTER_SECONDS = 10
DISCLOSURE = ("How it is made: every number in this video comes from the public data listed below (USGS, NOAA and, where "
              "named, Wikipedia) and each sentence of the script was checked against it. The maps and charts are drawn "
              "from that data; nothing is real footage. The narration is an AI voice. Deaths and injuries are not "
              "reported in this series.")


def stamp(seconds: float) -> str:
    s = int(seconds)
    h, m, sec = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def chapter_lines(chapters: list[tuple[str, float]]) -> list[str]:
    """chapters: (title, start seconds), in order. Raises unless YouTube would show them as chapters."""
    if len(chapters) < MIN_CHAPTERS:
        raise ValueError(f"{len(chapters)} chapters: YouTube needs at least {MIN_CHAPTERS}")
    if chapters[0][1] != 0:
        raise ValueError("the first chapter must start at 00:00")
    starts = [int(s) for _, s in chapters]
    for (title, a), b in zip(chapters, starts[1:] + [None]):
        if b is not None and b - int(a) < MIN_CHAPTER_SECONDS:
            raise ValueError(f"chapter {title!r} is under {MIN_CHAPTER_SECONDS} s")
    return [f"{stamp(s)} {title}" for title, s in chapters]


def clean(text: str) -> str:
    return text.replace("<", "").replace(">", "")


def size(text: str) -> int:
    return len(text.encode("utf-8"))


def description(ep: Episode, chapters: list[tuple[str, float]], last_chapter_seconds: float | None = None) -> str:
    if last_chapter_seconds is not None and last_chapter_seconds < MIN_CHAPTER_SECONDS:
        raise ValueError(f"the last chapter is under {MIN_CHAPTER_SECONDS} s")
    required = [ep.summary, "Chapters:\n" + "\n".join(chapter_lines(chapters)),
                "Credits:\n" + "\n".join(ep.credits), DISCLOSURE]
    text = clean("\n\n".join(required))
    if size(text) > LIMIT:
        raise ValueError(f"the description's required parts take {size(text)} bytes (limit {LIMIT})")
    optional = []
    if ep.sources:
        optional.append(("Sources:", list(ep.sources)))
    shorts = [f"{s['title']}: https://www.youtube.com/shorts/{s['video_id']}" for s in ep.related if s.get("video_id")]
    if shorts:
        optional.append(("The Shorts this episode grew from:", shorts))
    for head, rows in optional:
        block = head
        for row in rows:
            trial = clean(f"{text}\n\n{block}\n{row}")
            if size(trial) > LIMIT - 200:  # room for the hashtags
                break
            block = f"{block}\n{row}"
        if block != head:
            text = clean(f"{text}\n\n{block}")
    tags = " ".join("#" + "".join(h.split()) for h in ep.hashtags[:3])
    if tags and size(f"{text}\n\n{tags}") <= LIMIT:
        text = f"{text}\n\n{tags}"
    return text
