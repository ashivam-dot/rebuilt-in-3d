"""Regression coverage for recovery run 40120068546: contradictory beat counts and truncated drafts."""
import json

import pytest

from studio import writer


@pytest.mark.parametrize("count", [2, 3, 4, 5, 8, 10])
def test_decoder_and_editor_require_the_same_beat_count(count):
    schema = writer.draft_schema([{"file": f"{i}.jpg"} for i in range(count)])
    beats = schema["properties"]["beats"]
    assert beats["minItems"] == beats["maxItems"] == min(count, writer.MAX_BEATS)
    assert beats["items"]["properties"]["photo"]["maximum"] == count - 1
    assert writer.SCHEMA["properties"]["beats"]["minItems"] == 1  # no cross-request mutation


def test_truncation_changes_the_retry_and_keeps_the_verification(monkeypatch, tmp_path):
    calls = []
    draft = {"title": "Karak: what happened", "hook": "Karak church shooting",
             "beats": [{"say": "Karak church shooting prompted an investigation.", "photo": 0, "caption": "Inquiry"},
                       {"say": "Police continued their investigation.", "photo": 1, "caption": "Police"}]}

    class Fake:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def chat(self, messages, schema=None, **kwargs):
            calls.append((messages, schema, kwargs))
            if len(calls) == 1:
                raise json.JSONDecodeError("Unterminated string", '{"title":"', 10)
            if schema is writer.CHECK_SCHEMA:
                return {"lines": [{"line": i, "verdict": "supported", "quote": ""} for i in (1, 2)]}
            return draft

    monkeypatch.setattr(writer.llm, "Model", Fake)
    monkeypatch.setattr(writer, "_validate", lambda *a, **k: [])
    monkeypatch.setattr(writer, "monotone", lambda *a: [])
    monkeypatch.setattr(writer, "hook_text_problems", lambda *a: [])
    monkeypatch.setattr(writer, "closing_problems", lambda *a: [])
    log_path = tmp_path / "writer_log.json"
    got, log = writer.write("incident", "Karak", "It", [], "Police continued their investigation.",
                            [{"file": "0.jpg"}, {"file": "1.jpg"}], log_path=log_path)
    assert got["title"] == draft["title"]
    assert len(log) == 1 and "cut off" in log[0]["problems"][0]
    assert calls[1][2]["max_tokens"] > calls[0][2]["max_tokens"]
    assert "exactly 2 beats" in calls[1][0][-1]["content"]
    assert any(schema is writer.CHECK_SCHEMA for _, schema, _ in calls)
    assert json.loads(log_path.read_text()) == log
    evidence = json.loads((tmp_path / "writer_input.json").read_text())
    assert evidence["messages"] == calls[0][0]
    assert evidence["draft_schema"] == calls[0][1]
    assert evidence["ground"] == "Police continued their investigation.\n"
    assert [p["file"] for p in evidence["photos"]] == ["0.jpg", "1.jpg"]


def test_no_photos_cannot_reach_the_model():
    with pytest.raises(ValueError, match="at least one photo"):
        writer.draft_schema([])


@pytest.mark.parametrize("repair", [True, False])
def test_display_feedback_does_not_delay_a_factual_rewrite(monkeypatch, repair):
    """The Lunny recovery spent two drafts on a seven-word hook, finding factual faults too late."""
    drafts, checks, feedback = [], [], []

    class Fake:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def chat(self, messages, schema=None, **kwargs):
            if schema is writer.CHECK_SCHEMA:
                checks.append(len(drafts))
                fixed = repair and len(drafts) > 1
                return {"lines": [{"line": 1, "verdict": "supported", "quote": ""},
                                  {"line": 2, "verdict": "supported" if fixed else "partly", "quote": "",
                                   "why": "the source does not put the studies and pub trio together"}]}
            if schema is writer.RECHECK_SCHEMA:
                return {"supported": False, "why": "unsupported temporal relationship"}
            feedback.append(messages[-1]["content"])
            fixed = repair and bool(drafts)
            draft = {"title": "Dónal Lunny, Irish Folk Pioneer, Dies at 79",
                     "hook": "Dónal Lunny led Irish music" if fixed else
                             "Dónal Lunny led the Irish music renaissance",
                     "beats": [{"say": "Dónal Lunny led the Irish music renaissance and has died.",
                                "photo": 0, "caption": "Irish music pioneer"},
                               {"say": "He enrolled in design college in 1965." if fixed else
                                       "A student of design, he played in pub trios as a teenager.",
                                "photo": 1, "caption": "Early music"}]}
            drafts.append(draft)
            return draft

    monkeypatch.setattr(writer.llm, "Model", Fake)
    monkeypatch.setattr(writer, "_validate", lambda *a, **k: [])
    monkeypatch.setattr(writer, "monotone", lambda *a: [])
    monkeypatch.setattr(writer, "closing_problems", lambda *a: [])
    args = ("death", "Dónal Lunny", "He", [], "He enrolled in design college in 1965.",
            [{"file": "0.jpg"}, {"file": "1.jpg"}])
    if repair:
        got, log = writer.write(*args)
        assert "1965" in got["beats"][1]["say"] and len(log) == 1
        assert checks == [1, 2]
    else:
        with pytest.raises(ValueError, match="unsupported temporal relationship"):
            writer.write(*args)
        assert len(drafts) == 3 and checks == [1, 2, 3]
    assert "the hook" in feedback[1] and "unsupported temporal relationship" in feedback[1]
