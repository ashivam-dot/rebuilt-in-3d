"""Run 40129764554: four accepted beats totaled 48 words and died at the publishing gate."""
from copy import deepcopy

import pytest

from studio import gate, writer


LINES = [
    "Dónal Lunny, a pioneer of the Irish folk renaissance, has died.",
    "He began playing in pubs as a teenager with his elder brother.",
    "In 1971, a session on an album led him to form Planxty.",
    "He was honored with the RTÉ Radio 1 Folk Awards Lifetime Achievement Award.",
]


@pytest.mark.parametrize("style", [True, False])
def test_short_draft_returns_the_real_publish_failure(style):
    photos = [{"file": f"{i}.jpg", "kind": "person", "shows": ["Dónal Lunny"]} for i in range(4)]
    draft = {"title": "Dónal Lunny, Irish Folk Musician, Dies at 79", "hook": "Dónal Lunny has died",
             "beats": [{"say": line, "photo": i, "caption": ""} for i, line in enumerate(LINES)]}
    source = " ".join(LINES) + " Dónal Lunny died aged 79 in 2026."
    failures = writer._validate(draft, photos, "Dónal Lunny", source, [], recent=[], style=style)
    assert "narration: 48 words (want 50-200)" in failures
    repaired = deepcopy(draft)
    repaired["beats"][-1]["say"] += " in 2025."
    fixed = writer._validate(repaired, photos, "Dónal Lunny", source + " The award was in 2025.", [],
                             recent=[], style=style)
    assert not [p for p in fixed if p.startswith("narration:")]


@pytest.mark.parametrize("words,accepted", [(49, False), (50, True), (200, True), (201, False)])
def test_shared_length_contract_keeps_both_publish_boundaries(words, accepted):
    assert (not gate.narration_problems(" ".join(["word"] * words))) is accepted
