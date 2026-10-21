"""A chapter's narration through the Shorts' own Chatterbox path (studio/voice.py synthesize_story): one take per
sentence, each heard back by Whisper and retaken when garbled. A chapter is read as a pseudo-Short whose beats are its
sentences, so nothing about the voice, its licence or its checks differs from the Shorts."""
from __future__ import annotations

import json
from pathlib import Path

from .. import voice
from ..spec import Beat, Short

PAUSE = 0.35  # seconds between sentences
PARAGRAPH = 0.7  # every PARAGRAPH_EVERY sentences, a longer breath
PARAGRAPH_EVERY = 4


def as_short(episode_id: str, key: str, lines: list[str]) -> Short:
    beats = [Beat(text=t, shot=f"line-{i}", pause_after=PARAGRAPH if (i + 1) % PARAGRAPH_EVERY == 0 else PAUSE)
             for i, t in enumerate(lines)]
    return Short(id=f"{episode_id}-{key}", kind="longform", title=key, beats=beats, facts=[], sources=[], loss=False,
                 scene={"mood": "news", "voice": "world", "narration": "story"})


def run(episode_id: str, chapter: Path, out: Path) -> dict:
    """narration.wav and timing.json in out, for the chapter written to chapter (write.py)."""
    data = json.loads(chapter.read_text(encoding="utf-8"))
    out.mkdir(parents=True, exist_ok=True)
    return voice.synthesize_story(as_short(episode_id, data["key"], data["lines"]), out)
