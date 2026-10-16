from datetime import date, datetime, timedelta, timezone

import pytest

from studio import cli, ledger, plan, stories, usgs, writer
from studio.spec import Beat, Short


def _quake(mag, alert):
    at = datetime.now(timezone.utc) - timedelta(hours=11)
    return usgs.Quake(f"q{mag}", mag, "76 km NE of Ozernovskiy, Russia", at, 51.9, 157.4, 30.0, alert, 733, "")


def test_a_green_m6_5_quake_is_news_without_trending(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "STATE", tmp_path)
    monkeypatch.setattr(usgs, "recent", lambda: [_quake(6.9, "green"), _quake(6.2, "green"), _quake(6.1, "yellow")])
    found = {c["event"] for c in plan.quake_candidates()}
    assert found == {"q6.9", "q6.1"}


def _incident(kind="incident", sid="wk-Q1"):
    return {"id": sid, "kind": kind, "category": "attack", "qid": "Q1", "title": "2026 Example shooting"}


@pytest.mark.parametrize("cand,count,why", [
    (_incident(kind="death"), 3, "gate: only 0 usable photos of X on Wikimedia Commons (want 3)"),
    (_incident(sid="nw-20261015-oregon-attack"), 3, "gate: only 0 usable photos of Oregon (want 2)"),
    (_incident(), 0, "gate: only 0 usable photos of X on Wikimedia Commons (want 2)"),
    (_incident(), 3, "gate: no draft passed the fact checks: line 1"),
])
def test_no_3d_fallback_for_tributes_reports_first_tries_or_other_failures(tmp_path, monkeypatch, cand, count, why):
    monkeypatch.setattr(ledger, "STATE", tmp_path)
    if count:
        ledger.save("retries", {cand["id"]: {"count": count, "reason": why, "at": ledger.now()}})
    monkeypatch.setattr(writer, "build_incident", lambda *a, **k: pytest.fail("must not build in 3D"))
    assert cli.in_3d(cand, ValueError(why)) is None


def test_a_photo_short_incident_is_rewritten_over_3d_views_on_its_second_try(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "STATE", tmp_path)
    cand = _incident()
    ledger.save("retries", {cand["id"]: {"count": 1, "reason": "usable photos", "at": ledger.now()}})
    seen = {}
    monkeypatch.setattr(writer, "build_incident", lambda c, views=False: seen.update(views=views) or "short")
    assert cli.in_3d(cand, ValueError("gate: only 1 usable photos of X on Wikimedia Commons (want 2)")) == "short"
    assert seen == {"views": True}


def test_in_3d_maps_the_writers_views_to_3d_shots(monkeypatch):
    monkeypatch.setattr(stories, "_cities", lambda *a: [{"name": "Bend", "lat": 44.05, "lon": -121.3}])
    short = Short(id="wk-Q1", kind="incident", title="t", loss=True, facts=[], sources=[],
                  beats=[Beat("a", "photo:0", {"big": "5 killed", "small": ""}), Beat("b", "photo:1"),
                         Beat("c", "photo:3"), Beat(writer.OUTRO, "outro", {"big": "Orbitwire", "small": ""})],
                  scene={"template": "story", "photos": [], "voice": "world", "mood": "news"},
                  credits=[writer.CREDIT], tags=["attack"])
    out = writer.in_3d(short, (44.03, -121.29), "Silver Rail", date(2026, 10, 15))
    assert [b.shot for b in out.beats] == ["overview", "site", "toll", "outro"]
    assert out.scene["template"] == "site" and out.scene["narration"] == "story"
    assert "photos" not in out.scene and out.scene["voice"] == "world"
    assert "not real footage" in out.beats[-1].card["small"]
    assert writer.CREDIT not in out.credits and writer.VIEW_CREDIT in out.credits
