"""Voice pronunciation repairs preserve numeric evidence and the existing readback gate."""
import json

import pytest

from studio import align, voice
from studio.longform import voice as chapter_voice


@pytest.mark.parametrize('written,spoken', [
    ('In 1916, a magnitude 7.1 quake struck Costa Rica.',
     'In nineteen sixteen, a magnitude seven point one quake struck Costa Rica.'),
    ('In 1906,', 'In nineteen oh six,'),
    ('In 1900,', 'In nineteen hundred,'),
    ('In 2000,', 'In two thousand,'),
    ('In 2026,', 'In two thousand twenty six,'),
    ('A depth of 7.1 km and a magnitude 7.1 quake.',
     'A depth of 7.1 kilometres and a magnitude seven point one quake.'),
])
def test_only_the_explicit_voice_number_contexts_expand(written, spoken):
    assert chapter_voice.speakable(written) == spoken


def test_original_failed_transcript_still_fails_unchanged_alignment():
    script = 'In 1916, a magnitude 7.1 quake struck Costa Rica.'
    heard = 'In 1906, a magnitude 7 .1 quake struck Costa Rica.'
    rows = [{'text': w, 'start': i * .1, 'end': (i + 1) * .1} for i, w in enumerate(heard.split())]
    assert align.align(script, rows, 3)[1] < voice.MIN_MATCH == .8


def test_chapter_keeps_numeric_written_bytes_and_passes_only_voice_normalizer(tmp_path, monkeypatch):
    script = 'In 1916, a magnitude 7.1 quake struck Costa Rica.'
    chapter = tmp_path / 'chapter.json'
    chapter.write_text(json.dumps({'key': 'before', 'lines': [script]}))
    original = chapter.read_bytes()
    seen = []
    monkeypatch.setattr(voice, 'synthesize_story', lambda short, out, **kwargs:
                        seen.append((short, kwargs)) or {'ok': True})
    chapter_voice.run('episode', chapter, tmp_path / 'out')
    assert chapter.read_bytes() == original
    assert seen[0][0].beats[0].text == script
    assert seen[0][1]['speech_normalizer'] is chapter_voice.speakable
    assert voice.speakable(script) == script  # The Shorts voice path is unchanged.
