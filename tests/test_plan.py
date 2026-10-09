from datetime import date, datetime, timezone

from studio import ledger, news, plan, trends, writer


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


def test_a_scheduled_short_only_blocks_the_hours_around_it(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "STATE", tmp_path)
    ledger.record_publish({"id": "wk-s", "published_at": "2026-10-10T03:45:00+00:00", "loss": False})
    assert plan.can_publish(datetime(2026, 10, 9, 22, tzinfo=timezone.utc)) is None
    assert "scheduled" in plan.can_publish(datetime(2026, 10, 10, 2, 30, tzinfo=timezone.utc))
    assert "h ago" in plan.can_publish(datetime(2026, 10, 10, 5, tzinfo=timezone.utc))


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


def test_an_ongoing_story_is_not_repeated_across_a_week_boundary_or_a_series():
    sunday = trends.story_id("Q1", "protest", date(2026, 10, 11))
    monday = trends.story_id("Q1", "protest", date(2026, 10, 12))
    assert sunday != monday and sunday.startswith("wk-Q1-2026w")
    assert trends.story_id("Q1", "flood", date(2026, 10, 11)) == "wk-Q1"
    rows = [{"id": "wk-Q1-p1", "published_at": "2026-10-11T23:00:00+00:00"}]
    at = datetime(2026, 10, 12, 1, 7, tzinfo=timezone.utc)
    assert plan.cooling({"qid": "Q1", "category": "protest", "id": monday}, at, rows)
    assert not plan.cooling({"qid": "Q11", "category": "protest", "id": "wk-Q11-2026w42"}, at, rows)
    assert not plan.cooling({"qid": "Q1", "category": "protest"}, datetime(2026, 10, 18, 2, tzinfo=timezone.utc), rows)


def test_ended_or_old_movements_are_not_news():
    def ent(**claims):
        return {"claims": {p: [{"mainsnak": {"datavalue": {"value": {"time": v}}}}] for p, v in claims.items()}}
    today = date(2026, 10, 9)
    assert trends.is_current(ent(P571="+2026-05-00T00:00:00Z"), "movement", today)
    assert not trends.is_current(ent(P580="+2026-06-06T00:00:00Z", P582="+2026-07-25T00:00:00Z"), "protest", today)
    assert not trends.is_current(ent(P580="+2020-08-09T00:00:00Z"), "protest", today)
    assert not trends.is_current(ent(), "movement", today)
    assert not trends.is_current(ent(), "conflict", today)
    assert not trends.is_current(ent(P585="+2015-04-02T00:00:00Z"), "conflict", today)
    assert trends.is_current(ent(P580="+2026-02-28T00:00:00Z"), "conflict", today)
    assert trends.is_current(ent(), "protest", today)


def test_a_follow_up_headline_does_not_make_an_old_incident_breaking():
    at = datetime(2026, 10, 9, 14, tzinfo=timezone.utc)
    crash = {"kind": "incident", "category": "aviation", "fame": 900_000, "date": "2026-09-10",
             "news_at": "2026-10-09T13:00:00+00:00"}
    assert plan.age_hours(crash, at) > 600 and not plan.is_breaking(crash, at)
    war = {"kind": "incident", "category": "conflict", "fame": 2_000_000, "news_at": "2026-10-09T13:00:00+00:00"}
    assert not plan.is_breaking(war, at)
    quake = {"kind": "quake", "mag": 7.2, "age_h": 4, "fame": 90_000}
    assert plan.is_breaking(quake, at) and not plan.is_breaking(quake | {"age_h": 30}, at)


def test_feed_dates_without_a_zone_do_not_break_the_feed(monkeypatch):
    rss = ("<rss><channel><item><title>Quake hits city - Outlet</title><pubDate>Fri, 09 Oct 2026 10:00:00 -0000"
           "</pubDate></item><item><title>No outlet here</title><pubDate>Fri, 09 Oct 2026 11:00:00 GMT</pubDate>"
           "</item></channel></rss>")
    monkeypatch.setattr(news.net, "get", lambda *a, **k: rss)
    items = news.headlines("IN", datetime(2026, 10, 9, 12, tzinfo=timezone.utc))
    assert [i["outlet"] for i in items] == ["Outlet", ""] and all(i["at"].endswith("+00:00") for i in items)


def test_protest_brief_is_used_for_ongoing_stories():
    msgs = writer._messages(writer.PROTEST_BRIEF.format(name="X"), [], "src", [], "X", ["Headline one"])
    assert "strictly neutral" in msgs[1]["content"] and "context only" in msgs[1]["content"]
