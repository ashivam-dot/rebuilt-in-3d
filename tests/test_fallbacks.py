from datetime import date, datetime, timedelta, timezone

import pytest

from studio import cli, ledger, plan, stories, usgs, writer
from studio.spec import Beat, Short


def _quake(mag, alert, place="76 km NE of Ozernovskiy, Russia"):
    at = datetime.now(timezone.utc) - timedelta(hours=11)
    return usgs.Quake(f"q{mag}-{alert}", mag, place, at, 51.9, 157.4, 30.0, alert, 733, "")


def test_only_a_quake_people_felt_is_news_without_trending(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "STATE", tmp_path)
    monkeypatch.setattr(usgs, "recent", lambda: [
        _quake(6.9, "green"), _quake(6.8, "green", "central Mid-Atlantic Ridge"), _quake(6.1, "yellow"),
        _quake(7.2, "green"), _quake(7.4, "green", "central Mid-Atlantic Ridge")])
    found = {c["event"] for c in plan.quake_candidates()}
    assert found == {"q6.1-yellow", "q7.2-green"}


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


def test_a_photo_short_incident_waits_for_photos_and_is_never_told_over_a_3d_map(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "STATE", tmp_path)
    cand = _incident()
    ledger.save("retries", {cand["id"]: {"count": 1, "reason": "usable photos", "at": ledger.now()}})
    seen = {}
    monkeypatch.setattr(writer, "build_incident", lambda c, views=False: seen.update(views=views) or "short")
    why = ValueError("gate: only 1 usable photos of X on Wikimedia Commons (want 2)")
    assert not cli.STORIES_IN_3D and cli.in_3d(cand, why) is None and seen == {}
    monkeypatch.setattr(cli, "STORIES_IN_3D", True)
    assert cli.in_3d(cand, why) == "short" and seen == {"views": True}


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


def test_a_toll_that_counts_the_attacker_is_never_said_as_the_death_toll():
    ground = ("The perpetrator shot and killed three children and a teacher. "
              "Five people were killed at the scene, including the shooter. Two were hospitalized.")
    assert writer.tolls_with_perpetrator(ground) == {5}
    draft = {"title": "The Silver Rail Elementary School shooting", "beats": [
        {"say": "Five people were killed at the scene, including three children and a teacher.", "photo": 0,
         "caption": "x"},
        {"say": "Three children and a teacher were killed.", "photo": 0, "caption": "y"}]}
    problems = writer._validate(draft, [{"file": "a"}], "Silver Rail Elementary School shooting", ground, [])
    assert any("beat 1 says 5 died" in p for p in problems)
    assert not any("beat 2 says" in p for p in problems)
    assert writer.tolls_with_perpetrator("Five people were killed, including two children.") == set()
