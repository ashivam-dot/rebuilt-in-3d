"""A Short uploaded by a run that then failed (run 42488550978: "video moTbSDJOQjk was not scheduled") is published
from the spec kept with its upload, never written again."""
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from studio import cli, ledger, outlets, plan, youtube
from studio.spec import Short

FIXTURE = Path(__file__).parent / "fixtures" / "eq-us6000u0xi.json"


class _Call:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class _Scheduled:
    """videos.list misses the fresh publishAt for `lag` reads after the update."""

    def __init__(self, lag):
        self.lag, self.updated = lag, False

    def list(self, **k):
        status = {"uploadStatus": "processed", "privacyStatus": "private"}
        if self.updated:
            if self.lag:
                self.lag -= 1
            else:
                status["publishAt"] = "2026-11-08T20:30:00Z"
        return _Call({"items": [{"snippet": {"channelId": youtube.CHANNEL_ID, "title": "T"}, "status": status}]})

    def update(self, **k):
        self.updated = True
        return _Call({})


def _client(monkeypatch, videos):
    monkeypatch.setattr(youtube, "client", lambda: type("Api", (), {"videos": lambda self: videos})())
    monkeypatch.setattr(youtube, "identity", lambda api: {})
    monkeypatch.setattr(youtube, "find", lambda api, channel, short_id: {"id": "V1"})
    monkeypatch.setattr(youtube.time, "sleep", lambda s: None)


def test_schedule_waits_for_youtube_to_report_publish_at(tmp_path, monkeypatch):
    _client(monkeypatch, _Scheduled(lag=2))
    out = youtube.publish(Short.load(FIXTURE), tmp_path / "short.mp4", publish_at="2026-11-08T20:30:00+00:00")
    assert out["privacy"] == "scheduled" and out["publish_at"] == "2026-11-08T20:30:00Z"
    _client(monkeypatch, _Scheduled(lag=9))
    with pytest.raises(RuntimeError, match="was not scheduled"):
        youtube.publish(Short.load(FIXTURE), tmp_path / "short.mp4", publish_at="2026-11-08T20:30:00+00:00")


def test_the_upload_keeps_the_short_it_uploaded():
    short = Short.load(FIXTURE)
    ledger.record_upload(short.id, "V1", short=asdict(short))
    assert Short.load_dict(ledger.uploads()[short.id]["short"]) == short
    ledger.record_upload("wk-old", "V2")
    assert "short" not in ledger.uploads()["wk-old"]


def test_a_run_publishes_a_pending_upload_before_writing_anything(monkeypatch, tmp_path):
    short = replace(Short.load(FIXTURE), id="wk-Q1150359", kind="death")
    ledger.record_upload(short.id, "moTbSDJOQjk", short=asdict(short))
    ledger.record_upload("wk-bare", "V3")  # an upload from before specs were kept: left for a person
    monkeypatch.setattr(cli, "WORK", tmp_path)
    monkeypatch.setattr(cli.gate, "check", lambda s: [])
    monkeypatch.setattr(plan, "evening_slot", lambda cand, at, rows: (None, "control"))
    sent = []

    def publish(s, mp4, publish_at=None):
        sent.append((s.id, publish_at))
        return {"video_id": "moTbSDJOQjk", "url": "https://www.youtube.com/shorts/moTbSDJOQjk", "title": s.title,
                "privacy": "public", "synthetic_declared": True}

    monkeypatch.setattr(youtube, "publish", publish)
    health = {"steps": []}
    assert cli.finish_uploads(health)["video_id"] == "moTbSDJOQjk"
    assert sent == [("wk-Q1150359", None)]
    row = ledger.published()[-1]
    assert row["id"] == "wk-Q1150359" and row["slot_test"] == "control"
    assert set(ledger.uploads()) == {"wk-bare"}
    assert cli.finish_uploads({"steps": []}) is None  # nothing left with a spec


def test_a_stale_or_failing_pending_upload_never_stops_the_run(monkeypatch, tmp_path):
    short = replace(Short.load(FIXTURE), id="wk-Q2")
    ledger.record_upload(short.id, "V2", short=asdict(short))
    monkeypatch.setattr(cli, "WORK", tmp_path)
    monkeypatch.setattr(cli.gate, "check", lambda s: ["gate says no"])
    health = {"steps": []}
    assert cli.finish_uploads(health) is None and "gate says no" in health["steps"][0]
    rows = ledger.uploads()
    rows["wk-Q2"]["at"] = (datetime.now(timezone.utc) - timedelta(hours=ledger.STALE_UPLOAD_HOURS + 1)).isoformat()
    ledger.save("uploads", rows)
    health = {"steps": []}
    assert cli.finish_uploads(health) is None and health["steps"] == []


def test_two_clusters_naming_one_story_give_one_candidate(monkeypatch):
    a = {"id": "nw-20261107-krakow-attack", "fame": 30, "reports": [1, 2, 3]}
    b = {"id": "nw-20261107-krakow-attack", "fame": 20, "reports": [1]}
    c = {"id": "nw-20261108-senegal-maritime", "fame": 25, "reports": [1]}
    assert outlets.one_per_id([b, c, a]) == [a, c]
