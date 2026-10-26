"""Hear one pinned repaired sentence in isolation; this never creates publishable media."""
import argparse
import hashlib
import json
from pathlib import Path

import soundfile as sf

from .. import align, voice
from . import chapter_recover


def run(chapter: Path, out: Path, line: int):
    data = json.loads(chapter.read_text())
    if not 1 <= line <= len(data['lines']):
        raise ValueError('voice probe line is outside the pinned chapter')
    text = data['lines'][line - 1]
    style = voice.STYLE['news'] | {'voice': str(voice.VOICES['world'])}
    result = {'chapter_sha256': hashlib.sha256(chapter.read_bytes()).hexdigest(),
              'chapter': data['key'], 'line': line, 'text': text, 'speakable': voice.speakable(text),
              'engine': 'chatterbox', 'lane': 'world', 'minimum_match': voice.MIN_MATCH,
              'scope': 'Isolated diagnostic takes, not the lost original batch take',
              'release_approval': False, 'attempts': []}
    out.mkdir(parents=True, exist_ok=False)
    for seed in (7, 100 + 31 + line - 1, 100 + 62 + line - 1):
        take = voice._chatterbox([result['speakable']], out / f'seed-{seed}', style, seed)[0]
        audio, rate = sf.read(take['file'], dtype='float32')
        audio = voice._trim(audio if audio.ndim == 1 else audio.mean(axis=1), rate)
        heard = align.transcribe(audio, rate)
        words, match = align.align(text, heard, len(audio) / rate)
        result['attempts'].append({'seed': seed, 'heard': heard, 'aligned': words, 'match': match,
                                   'passed': match >= voice.MIN_MATCH,
                                   'audio_sha256': hashlib.sha256(Path(take['file']).read_bytes()).hexdigest(),
                                   'file': str(Path(take['file']).relative_to(out))})
        (out / 'voice-probe.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--chapter', choices=('before', 'people'), required=True)
    p.add_argument('--line', type=int, required=True)
    a = p.parse_args()
    chapter_recover.prepare(a.manifest)
    result = run(chapter_recover.WORK / 'chapters' / a.chapter / 'chapter.json',
                 chapter_recover.WORK / 'voice-probe', a.line)
    print(json.dumps({'line': a.line, 'scores': [r['match'] for r in result['attempts']], 'release_approval': False}))


if __name__ == '__main__':
    main()
