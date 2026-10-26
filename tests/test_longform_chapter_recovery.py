"""Targeted chapter recovery retains verified work and cannot hide changed inputs."""
import copy
import json

import pytest

from studio.longform import chapter_recover as repair, media_review
from studio.longform.spec import ROLES
from .test_longform import _episode


def test_exact_line_patch_keeps_factual_gates_and_rejects_changed_original(tmp_path):
    episode = _episode()
    line = 'On October 9, 2026, a magnitude 7.7 earthquake struck Panama.'
    file = tmp_path / 'chapter.json'
    file.write_text(json.dumps({'key': 'before', 'lines': [line], 'words': len(line.split()), 'model': 'original'}))
    spec = {'source_sha256': media_review.digest(file), 'edits': [
        {'before': line, 'after': 'A magnitude 7.7 earthquake struck Panama on October 9, 2026.'}]}
    result = repair.patch_chapter(file, spec, episode, 'before')
    assert result['lines'] == [spec['edits'][0]['after']]
    assert result['model'] == 'original' and result['editorial_repair']['source_sha256'] == spec['source_sha256']
    bad = copy.deepcopy(spec)
    bad['edits'][0]['after'] = 'A magnitude 9.9 earthquake struck Panama on October 9, 2026.'
    with pytest.raises(ValueError, match='existing writing gates'):
        repair.patch_chapter(file, bad, episode, 'before')
    bad['edits'][0]['before'] = 'A stale source line.'
    with pytest.raises(ValueError, match='stale exact-line'):
        repair.patch_chapter(file, bad, episode, 'before')
    file.write_text(file.read_text() + '\n')
    with pytest.raises(ValueError, match='original chapter hash differs'):
        repair.patch_chapter(file, spec, episode, 'before')


def test_source_must_be_pinned_and_each_retained_artifact_has_a_successful_job():
    manifest = {'source_run': 123, 'source_sha': 'a' * 40, 'episode_sha256': 'b' * 64,
                'chapters': {k: {'edits': [{'before': 'old', 'after': 'new'}]} if k in ('before', 'people')
                             else {} for k in ROLES}}
    run = {'repository': {'full_name': repair.REPO}, 'head_repository': {'full_name': repair.REPO},
           'head_sha': 'a' * 40, 'path': '.github/workflows/longform.yml',
           'status': 'completed', 'conclusion': 'failure'}
    names = ['longform-plan'] + ['longform-write-' + k for k in ROLES]
    names += ['longform-make-' + k for k in ROLES if k not in ('before', 'people')]
    artifacts = [{'name': n, 'id': i, 'expired': False} for i, n in enumerate(names)]
    jobs = [{'name': f'{phase} ({k})', 'conclusion': 'success'} for k in ROLES for phase in ('write', 'make')]
    def fetch(path):
        if '/artifacts?' in path:
            return {'artifacts': artifacts}
        if '/jobs?' in path:
            return {'jobs': jobs}
        return run
    result = repair.validate_source(manifest, fetch)
    assert len(result['retained_chapters']) == 5 and result['repaired_chapters'] == ['before', 'people']
    jobs[0]['conclusion'] = 'failure'
    with pytest.raises(ValueError, match='unsuccessful write'):
        repair.validate_source(manifest, fetch)
    jobs[0]['conclusion'] = 'success'
    artifacts[0]['expired'] = True
    with pytest.raises(ValueError, match='missing or ambiguous'):
        repair.validate_source(manifest, fetch)
    artifacts[0]['expired'] = False
    run['head_repository'] = {'full_name': 'someone/fork'}
    with pytest.raises(ValueError, match='pinned completed'):
        repair.validate_source(manifest, fetch)


def test_manifest_cannot_escape_the_committed_repair_folder(tmp_path):
    with pytest.raises(ValueError, match='committed bounded manifest'):
        repair.load_manifest(tmp_path / 'manifest.json')


def test_manifest_only_allows_the_two_chapters_the_workflow_rebuilds(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    folder = tmp_path / '.github/longform-repairs'
    folder.mkdir(parents=True)
    file = folder / 'repair.json'
    manifest = {'schema': 1, 'source_run': 123, 'source_sha': 'a' * 40,
                'episode_sha256': 'b' * 64,
                'chapters': {k: {'source_sha256': 'c' * 64} for k in ROLES}}
    for key in ('before', 'people'):
        manifest['chapters'][key]['edits'] = [{'before': 'old', 'after': 'new'}]
    file.write_text(json.dumps(manifest))
    assert repair.load_manifest(file) == manifest
    manifest['chapters']['next']['edits'] = manifest['chapters']['people'].pop('edits')
    file.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='exactly before and people'):
        repair.load_manifest(file)
