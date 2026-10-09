from datetime import datetime, timezone

from studio import ledger, plan, writer


def test_publish_cadence(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "STATE", tmp_path)
    at = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
    assert plan.can_publish(at) is None
    ledger.record_publish({"id": "eq-a", "published_at": "2026-10-09T11:00:00+00:00", "loss": False})
    assert "h ago" in plan.can_publish(at)
    assert "h ago" in plan.can_publish(at, breaking=True)
    assert plan.can_publish(datetime(2026, 10, 9, 12, 20, tzinfo=timezone.utc), breaking=True) is None
    for i, hour in enumerate(("01", "03", "05", "07")):
        ledger.record_publish({"id": f"wk-{i}", "published_at": f"2026-10-09T{hour}:00:00+00:00", "loss": False})
    late = datetime(2026, 10, 9, 20, tzinfo=timezone.utc)
    assert "today" in plan.can_publish(late)
    assert plan.can_publish(late, breaking=True) is None
    assert plan.can_publish(datetime(2026, 10, 10, 1, tzinfo=timezone.utc)) is None


def test_ledger_skip_marks_done(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "STATE", tmp_path)
    assert not ledger.is_done("eq-x")
    ledger.skip("eq-x", "gate: test")
    assert ledger.is_done("eq-x")


def test_fresh_story_beats_bigger_stale_one():
    at = datetime(2026, 10, 9, 14, tzinfo=timezone.utc)
    fresh = {"id": "a", "kind": "incident", "category": "protest", "fame": 200_000, "news_at": "2026-10-09T12:00:00+00:00"}
    stale = {"id": "b", "kind": "incident", "category": "flood", "fame": 600_000, "date": "2026-10-06"}
    assert plan.priority(fresh, at) > plan.priority(stale, at)


def test_windows_follow_the_audience():
    india = {"region": "india"}
    world = {"region": "world"}
    ist_night = datetime(2026, 10, 9, 20, tzinfo=timezone.utc)  # 01:30 IST, 16:00 New York
    assert not plan.in_window(india, ist_night) and plan.in_window(world, ist_night)
    ist_morning = datetime(2026, 10, 9, 5, tzinfo=timezone.utc)  # 10:30 IST, 01:00 New York
    assert plan.in_window(india, ist_morning) and not plan.in_window(world, ist_morning)
    assert plan.in_window(world, datetime(2026, 10, 10, 2, tzinfo=timezone.utc))  # 22:00 New York


def test_lineup_holds_regular_stories_but_not_breaking_ones(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "STATE", tmp_path)
    at = datetime(2026, 10, 9, 20, tzinfo=timezone.utc)
    quiet = {"id": "wk-1", "kind": "incident", "region": "india", "fame": 150_000,
             "news_at": "2026-10-09T18:00:00+00:00"}
    big = {"id": "wk-2", "kind": "incident", "region": "india", "fame": 900_000,
           "news_at": "2026-10-09T19:00:00+00:00"}
    ready, notes = plan.lineup([quiet, big], at)
    assert [c["id"] for c in ready] == ["wk-2"] and ready[0]["breaking"]
    assert any("india window" in n for n in notes)


def test_protest_brief_is_used_for_ongoing_stories():
    msgs = writer._messages(writer.PROTEST_BRIEF.format(name="X"), [], "src", [], "X", ["Headline one"])
    assert "strictly neutral" in msgs[1]["content"] and "context only" in msgs[1]["content"]
