"""A chapter's narration through the Shorts' own Chatterbox path (studio/voice.py synthesize_story): one take per
sentence, each heard back by Whisper and retaken when garbled. A chapter is read as a pseudo-Short whose beats are its
sentences, so nothing about the voice, its licence or its checks differs from the Shorts."""
from __future__ import annotations

import json
from pathlib import Path
import re

from .. import voice
from ..spec import Beat, Short

PAUSE = 0.35  # seconds between sentences
PARAGRAPH = 0.7  # every PARAGRAPH_EVERY sentences, a longer breath
PARAGRAPH_EVERY = 4
_ONES = 'zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split()
_TENS = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety']


def _under_hundred(number: int) -> str:
    if number < 20:
        return _ONES[number]
    return _TENS[number // 10] + (' ' + _ONES[number % 10] if number % 10 else '')


def speakable(text: str) -> str:
    """Pronounce explicit years and decimal magnitudes; written facts/captions stay in digits.

    The isolated 1916 diagnostic was transcribed as 1906 in all three takes.
    Expansion affects only the voice input. The original numeric script and the
    unchanged Whisper alignment and 80% threshold still judge every take.
    """
    text = voice.speakable(text)
    def year(match):
        value = int(match.group(2))
        century, last = divmod(value, 100)
        spoken = ('two thousand' + (' ' + _under_hundred(last) if last else '') if century == 20
                  else _ONES[century] + ' ' + ('hundred' if not last else
                       'oh ' + _ONES[last] if last < 10 else _under_hundred(last)))
        return match.group(1) + spoken
    text = re.sub(r'\b([Ii]n\s+)(1[89]\d{2}|20\d{2})(?=[,\s])', year, text)
    return re.sub(r'\b(magnitude\s+)(\d)\.(\d)\b',
                  lambda m: m.group(1) + _ONES[int(m.group(2))] + ' point ' + _ONES[int(m.group(3))], text)


def as_short(episode_id: str, key: str, lines: list[str]) -> Short:
    beats = [Beat(text=t, shot=f"line-{i}", pause_after=PARAGRAPH if (i + 1) % PARAGRAPH_EVERY == 0 else PAUSE)
             for i, t in enumerate(lines)]
    return Short(id=f"{episode_id}-{key}", kind="longform", title=key, beats=beats, facts=[], sources=[], loss=False,
                 scene={"mood": "news", "voice": "world", "narration": "story"})


def run(episode_id: str, chapter: Path, out: Path) -> dict:
    """narration.wav and timing.json in out, for the chapter written to chapter (write.py)."""
    data = json.loads(chapter.read_text(encoding="utf-8"))
    out.mkdir(parents=True, exist_ok=True)
    return voice.synthesize_story(as_short(episode_id, data["key"], data["lines"]), out,
                                  speech_normalizer=speakable)
