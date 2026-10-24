"""Real cloud run 40132734907 drafted two photos and spoke 'Photo 0' through all three repairs."""
from studio import gate, writer


def test_photo_acquisition_matches_the_unchanged_four_distinct_beats_rule():
    assert writer.MIN_PHOTOS == writer.TRIBUTE_PHOTOS == writer.WANT_PHOTOS == gate.MIN_BEATS == 4


def test_spoken_internal_photo_labels_receive_actionable_rewrite_feedback(monkeypatch):
    from types import SimpleNamespace

    draft = {'title': 'Donal Lunny, Irish Folk Pioneer, Dies at 79', 'hook': 'Donal Lunny has died',
             'beats': [{'say': 'Donal Lunny, a pioneer of the Irish folk renaissance, has died. Photo 0 shows him with Mozaik.',
                        'photo': 0, 'caption': 'Touring with Mozaik', 'anchor': 'Donal'}]}
    photos = [{'file': 'matched portrait', 'role': 'person', 'names': ['Donal Lunny']}]
    monkeypatch.setattr(writer, 'recent_titles', lambda: [])
    monkeypatch.setattr(writer, 'ordinary', lambda word: True)
    monkeypatch.setattr(writer, 'shown_problems', lambda *a: [])
    story = SimpleNamespace(prepare=lambda *a: None, title_faceless=lambda *a: [],
                            missing=lambda *a: [], subject_shown=lambda *a: True)
    problems = writer._validate(draft, photos, 'Donal Lunny', draft['beats'][0]['say'], [],
                                style=False, story=story)
    assert any("internal visual label 'Photo 0'" in p and 'verified story' in p for p in problems)
