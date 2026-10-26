import json

import numpy as np
import pytest
import soundfile as sf

from studio import align, voice
from studio.longform import voice_probe


def test_isolated_probe_retains_all_verdicts_and_the_exact_existing_voice(tmp_path, monkeypatch):
    chapter = tmp_path / 'chapter.json'
    text = 'In 1916, a magnitude 7.1 quake struck Costa Rica.'
    chapter.write_text(json.dumps({'key': 'before', 'lines': ['Earlier context.', text]}))
    requests = []
    def synth(lines, out, style, seed):
        requests.append((lines, style, seed))
        out.mkdir(parents=True)
        path = out / 'line00.wav'
        sf.write(path, np.ones(2400, dtype=np.float32) * .1, 24000)
        return [{'file': str(path)}]
    monkeypatch.setattr(voice, '_chatterbox', synth)
    heard = iter(['garbled', text, 'truncated'])
    monkeypatch.setattr(align, 'transcribe', lambda *a: [
        {'text': w, 'start': i * .1, 'end': (i + 1) * .1} for i, w in enumerate(next(heard).split())])
    output = tmp_path / 'probe'
    result = voice_probe.run(chapter, output, 2)
    assert [r['passed'] for r in result['attempts']] == [False, True, False]
    assert [r[2] for r in requests] == [7, 132, 163]
    assert all(r[0] == [voice.speakable(text)] and r[1] == voice.STYLE['news'] | {
        'voice': str(voice.VOICES['world'])} for r in requests)
    assert result['minimum_match'] == voice.MIN_MATCH == .8 and result['release_approval'] is False
    assert len(list(output.rglob('*.wav'))) == 3
    assert json.loads((output / 'voice-probe.json').read_text()) == result
    assert not list(output.glob('narration.wav')) and not list(output.glob('timing.json'))
    with pytest.raises(FileExistsError):
        voice_probe.run(chapter, output, 2)


@pytest.mark.parametrize('line', [0, -1, 2])
def test_probe_cannot_invent_a_line_outside_the_pinned_chapter(tmp_path, line):
    chapter = tmp_path / 'chapter.json'
    chapter.write_text(json.dumps({'key': 'before', 'lines': ['Exact sentence.']}))
    with pytest.raises(ValueError, match='outside the pinned chapter'):
        voice_probe.run(chapter, tmp_path / 'probe', line)
    assert not (tmp_path / 'probe').exists()
