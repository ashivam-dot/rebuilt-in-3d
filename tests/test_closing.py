"""The last beat closes the story with what happens next or why it matters, from the sources; the spoken "Follow
Orbitwire..." outro that ended every Short until 2026-10-22 is gone, and the end card holds silently."""
import json

import numpy as np
import pytest

from studio import voice, writer
from studio.spec import Beat, Short


@pytest.mark.parametrize("close", [
    "Follow Orbitwire for the stories the whole world is talking about.",
    "Follow us for what happens next in Kakinada.",
    "Subscribe to see how the rebuilding goes.",
    "Only time will tell what Kakinada does next.",
    "What comes next for the valley remains to be seen.",
    "Stay tuned as the inquiry continues.",
])
def test_a_call_to_action_or_filler_close_is_rewritten(close):
    draft = {"beats": [{"say": "Cyclone Montha hit Kakinada.", "photo": 0, "caption": ""}, {"say": close}]}
    assert any("the last beat says" in p for p in writer.closing_problems(draft))


@pytest.mark.parametrize("close", [
    "The rail safety commissioner's inquiry is due to report by March.",
    "Investigators will follow the flight recorders to the cause.",  # "follow" not addressed to the viewer
    "Part 2 tells how the rescue unfolded.",  # a series teaser is a what-happens-next close
    "His roar in Krantiveer is still quoted by every young actor in Mumbai.",
])
def test_a_close_on_what_happens_next_or_why_it_matters_passes(close):
    assert writer.closing_problems({"beats": [{"say": close}]}) == []
    assert writer.closing_problems({"beats": []}) == []


def test_the_brief_asks_for_a_grounded_close_and_no_call_to_action():
    assert "what happens next or why it matters" in writer.RULES and "Never a call to follow" in writer.RULES
    for brief in (writer.DEATH_BRIEF, writer.INCIDENT_BRIEF, writer.PROTEST_BRIEF):
        assert "from the SOURCE" in brief.split("\n6. ")[1]


def test_a_filler_close_is_rewritten_twice_then_never_costs_the_story(monkeypatch):
    """Like the hook rules: the first two drafts are sent back, the last is judged on the facts alone (every beat,
    the close included, is still fact-checked)."""
    draft = {"title": "Nana Patekar, Krantiveer Star, Dies at 75", "hook": "Nana Patekar's roar in Krantiveer",
             "beats": [{"say": "Nana Patekar's roar in Krantiveer won him a National Film Award.", "photo": 0,
                        "caption": "1994"},
                       {"say": "He was an actor of the Hindi screen. " * 11, "photo": 0, "caption": "Actor"},
                       {"say": "Only time will tell what comes next.", "photo": 0, "caption": "Actor"}]}
    calls = []

    class Fake:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def chat(self, messages, schema=None, **kw):
            calls.append(messages)
            return json.loads(json.dumps(draft))

    monkeypatch.setattr(writer.llm, "Model", Fake)
    got, log = writer.write("death", "Nana Patekar", "He", ["Person: Nana Patekar.", "Age: 75."],
                            "Nana Patekar, 75, won a National Film Award for Krantiveer in 1994. He was an actor of "
                            "the Hindi screen.", [{"file": "File:0.jpg", "description": ""}])
    # Drafts 1 and 2 are sent back for the close; draft 3 goes straight to the fact check (a fake that flags nothing).
    assert all("the last beat says 'Only time will tell'" in m[-1]["content"] for m in calls[1:3])
    assert len(calls) == 4 and "Check every numbered LINE" in calls[3][-1]["content"]
    assert [entry["attempt"] for entry in log] == [1, 2] and got["beats"][-1]["say"].startswith("Only time")


def test_the_end_card_is_silent_and_holds(monkeypatch, tmp_path):
    assert writer.OUTRO == "" and writer.END_CARD >= 1.5
    sent = []

    def chatterbox(lines, out, style, seed):
        sent.extend(lines)
        out.mkdir(parents=True, exist_ok=True)
        takes = []
        for i, _ in enumerate(lines):
            f = out / f"{i}.wav"
            voice.sf.write(f, np.full(voice.SAMPLE_RATE, 0.3, dtype=np.float32), voice.SAMPLE_RATE)
            takes.append({"file": str(f)})
        return takes

    monkeypatch.setattr(voice, "_chatterbox", chatterbox)
    from studio import align
    monkeypatch.setattr(align, "transcribe", lambda audio, sr: [])
    monkeypatch.setattr(align, "align", lambda text, heard, d: ([{"text": text, "start": 0.0, "end": d}], 1.0))
    short = Short(id="wk-Q1", kind="death", title="t", loss=False, sources=[], facts=[],
                  beats=[Beat("Nana Patekar won a National Film Award.", "photo:0", pause_after=0.3),
                         Beat(writer.OUTRO, "outro", {"big": "Orbitwire", "small": ""}, pause_after=writer.END_CARD)],
                  scene={"template": "story", "mood": "tribute"})
    timing = voice.synthesize_story(short, tmp_path)
    assert sent == ["Nana Patekar won a National Film Award."]  # the end card is never sent to the voice
    (s0, e0), (s1, e1) = timing["beats"]
    assert s1 == e0 and e1 - s1 == pytest.approx(writer.END_CARD, abs=1e-3)
    assert all(w["beat"] == 0 for w in timing["words"]) and timing["voice"]["heard"] == [1.0]
