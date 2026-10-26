"""Repair pinned written chapters while retaining successful same-run chapter media."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from . import media_review, write
from .spec import Episode, ROLES

REPO = 'ashivam-dot/rebuilt-in-3d'
WORK = Path('work/longform')


def api(path):
    return json.loads(subprocess.check_output(['gh', 'api', f'repos/{REPO}/{path}'], timeout=90))


def load_manifest(path: Path) -> dict:
    root = Path('.github/longform-repairs').resolve()
    if not path.resolve().is_relative_to(root) or path.suffix != '.json':
        raise ValueError('chapter repair must use a committed bounded manifest')
    data = json.loads(path.read_text())
    if data.get('schema') != 1 or type(data.get('source_run')) is not int \
            or not re.fullmatch(r'[0-9a-f]{40}', data.get('source_sha', '')) \
            or not re.fullmatch(r'[0-9a-f]{64}', data.get('episode_sha256', '')) \
            or set(data.get('chapters', {})) != set(ROLES):
        raise ValueError('invalid pinned chapter repair manifest')
    changed = []
    for key, row in data['chapters'].items():
        if not re.fullmatch(r'[0-9a-f]{64}', row.get('source_sha256', '')):
            raise ValueError('missing exact original chapter hash')
        if 'edits' in row:
            if not isinstance(row['edits'], list) or not 1 <= len(row['edits']) <= 8:
                raise ValueError('chapter edits must be bounded')
            changed.append(key)
    if set(changed) != {'before', 'people'}:
        raise ValueError('this recovery workflow repairs exactly before and people')
    return data


def validate_source(manifest: dict, fetch=api) -> dict:
    source = fetch(f"actions/runs/{manifest['source_run']}")
    if source.get('repository', {}).get('full_name') != REPO \
            or source.get('head_repository', {}).get('full_name') != REPO \
            or source.get('head_sha') != manifest['source_sha'] \
            or source.get('path') != '.github/workflows/longform.yml' \
            or source.get('status') != 'completed' or source.get('conclusion') not in ('success', 'failure'):
        raise ValueError('chapter source is not the pinned completed same-repository weekly run')
    artifacts = fetch(f"actions/runs/{manifest['source_run']}/artifacts?per_page=100")['artifacts']
    jobs = fetch(f"actions/runs/{manifest['source_run']}/jobs?per_page=100")['jobs']
    needed = ['longform-plan'] + ['longform-write-' + k for k in ROLES]
    retained = [k for k in ROLES if not manifest['chapters'][k].get('edits')]
    needed += ['longform-make-' + k for k in retained]
    pinned = {}
    for name in needed:
        found = [a for a in artifacts if a['name'] == name and not a.get('expired')]
        if len(found) != 1:
            raise ValueError('missing or ambiguous chapter artifact: ' + name)
        pinned[name] = {k: found[0].get(k) for k in ('id', 'name', 'digest')}
    for key in ROLES:
        for phase in ('write', 'make') if key in retained else ('write',):
            found = [j for j in jobs if j['name'] == f'{phase} ({key})']
            if len(found) != 1 or found[0]['conclusion'] != 'success':
                raise ValueError(f'cannot retain an unsuccessful {phase} chapter: {key}')
    return {'source_run': manifest['source_run'], 'source_sha': manifest['source_sha'],
            'episode_sha256': manifest['episode_sha256'], 'artifacts': pinned,
            'retained_chapters': retained, 'repaired_chapters': [k for k in ROLES if k not in retained]}


def download(run: int, name: str, target: Path):
    if target.exists():
        raise ValueError('preserve an existing recovery download: ' + str(target))
    target.mkdir(parents=True)
    subprocess.run(['gh', 'run', 'download', str(run), '--repo', REPO, '--name', name,
                    '--dir', str(target)], check=True, timeout=600)


def patch_chapter(original: Path, spec: dict, ep: Episode, key: str) -> dict:
    if media_review.digest(original) != spec['source_sha256']:
        raise ValueError('original chapter hash differs: ' + key)
    data = json.loads(original.read_text())
    if data['key'] != key:
        raise ValueError('wrong chapter identity')
    lines = list(data['lines'])
    for edit in spec.get('edits', []):
        if set(edit) != {'before', 'after'} or not isinstance(edit['before'], str) \
                or edit['after'] is not None and not isinstance(edit['after'], str) \
                or lines.count(edit['before']) != 1:
            raise ValueError('ambiguous or stale exact-line chapter edit')
        index = lines.index(edit['before'])
        if edit['after'] is None:
            lines.pop(index)
        else:
            lines[index] = edit['after']
    ch = next(c for c in ep.chapters if c.key == key)
    src = write.ground(ep, ch)
    errors = [p for i, line in enumerate(lines)
              for p in write.line_problems(line, ch, src, i == len(lines) - 1)]
    words = sum(len(line.split()) for line in lines)
    if words < ch.words[0] * .7 or words > ch.words[1]:
        errors.append('chapter is outside the existing checked-word floor/ceiling')
    if errors:
        raise ValueError('chapter repair failed existing writing gates: ' + '; '.join(errors))
    return {**data, 'lines': lines, 'words': words, 'editorial_repair': {
        'source_sha256': spec['source_sha256'], 'edits': spec['edits'],
        'kind': 'exact editorial correction; original model attribution retained for original lines'}}


def prepare(path: Path):
    manifest = load_manifest(path)
    proof = validate_source(manifest)
    source = Path('work/chapter-source')
    plan = source / 'plan'
    download(manifest['source_run'], 'longform-plan', plan)
    if media_review.digest(plan / 'episode.json') != manifest['episode_sha256']:
        raise ValueError('source episode hash differs')
    ep = Episode.load(plan / 'episode.json')
    if [ch.key for ch in ep.chapters] != list(ROLES):
        raise ValueError('source chapter order differs')
    WORK.mkdir(parents=True, exist_ok=True)
    for name in ('episode.json', 'plan.json'):
        shutil.copy2(plan / name, WORK / name)
    for key in ROLES:
        original = source / 'written' / key
        download(manifest['source_run'], 'longform-write-' + key, original)
        if media_review.digest(original / 'episode.json') != manifest['episode_sha256']:
            raise ValueError('written chapter belongs to another episode')
        file = original / 'chapters' / key / 'chapter.json'
        spec = manifest['chapters'][key]
        if spec.get('edits'):
            patched = patch_chapter(file, spec, ep, key)
            target = WORK / 'chapters' / key
            target.mkdir(parents=True)
            (target / 'chapter.json').write_text(json.dumps(patched, ensure_ascii=False, indent=1))
        elif media_review.digest(file) != spec['source_sha256']:
            raise ValueError('unmodified written source differs')
    proof.update(manifest=manifest, manifest_sha256=media_review.digest(path),
                 prepared_at=datetime.now(timezone.utc).isoformat(), release_approval=False)
    (WORK / 'repair-source.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n')
    return proof


def check():
    from .. import llm
    proof = json.loads((WORK / 'repair-source.json').read_text())
    ep = Episode.load(WORK / 'episode.json')
    with llm.Model() as model:
        for key in proof['repaired_chapters']:
            folder = WORK / 'chapters' / key
            data = json.loads((folder / 'chapter.json').read_text())
            ch = next(c for c in ep.chapters if c.key == key)
            flagged = write.fact_check(model, data['lines'], ch, write.ground(ep, ch))
            receipt = {'chapter_sha256': media_review.digest(folder / 'chapter.json'),
                       'episode_sha256': media_review.digest(WORK / 'episode.json'),
                       'checker': model.name, 'flagged': flagged}
            (folder / 'repair-check.json').write_text(json.dumps(receipt, indent=2) + '\n')
            if flagged:
                raise ValueError('the existing evidence checker held the repaired chapter: ' + key)


def retain():
    proof = json.loads((WORK / 'repair-source.json').read_text())
    for key in proof['repaired_chapters']:
        folder = WORK / 'chapters' / key
        checked = json.loads((folder / 'repair-check.json').read_text())
        if checked.get('flagged') or checked['chapter_sha256'] != media_review.digest(folder / 'chapter.json') \
                or checked['episode_sha256'] != proof['episode_sha256']:
            raise ValueError('repaired chapter lacks exact passing source check')
    retained = {}
    for key in proof['retained_chapters']:
        target = Path('work/chapter-source/made') / key
        download(proof['source_run'], 'longform-make-' + key, target)
        folder = target / 'chapters' / key
        if media_review.digest(target / 'episode.json') != proof['episode_sha256'] \
                or media_review.digest(folder / 'chapter.json') != proof['manifest']['chapters'][key]['source_sha256']:
            raise ValueError('retained media belongs to another episode/chapter')
        timing = json.loads((folder / 'timing.json').read_text())
        voice = timing.get('voice', {})
        if voice.get('engine') != 'chatterbox' or voice.get('lane') != 'world' \
                or not voice.get('heard') or min(voice['heard']) < .8:
            raise ValueError('retained chapter lacks the established narrator/readback')
        retained[key] = {p.name: media_review.digest(p) for p in folder.iterdir() if p.is_file()}
        shutil.copytree(folder, WORK / 'chapters' / key, dirs_exist_ok=False)
    proof['retained_media_sha256'] = retained
    proof['repaired_chapter_sha256'] = {k: media_review.digest(WORK / 'chapters' / k / 'chapter.json')
                                      for k in proof['repaired_chapters']}
    (WORK / 'repair-source.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n')


def main():
    if os.environ.get('GITHUB_REPOSITORY') != REPO:
        raise ValueError('chapter recovery must run within its channel repository')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'check', 'retain'))
    parser.add_argument('--manifest', type=Path)
    args = parser.parse_args()
    if args.mode == 'prepare':
        if args.manifest is None:
            parser.error('--manifest is required')
        prepare(args.manifest)
    elif args.mode == 'check':
        check()
    else:
        retain()


if __name__ == '__main__':
    main()
