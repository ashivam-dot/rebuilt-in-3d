from datetime import date, datetime, timezone

from studio import ledger, plan, trends

TODAY = date(2026, 11, 1)


def _person(died: str, **extra) -> dict:
    claims = {"P570": [{"mainsnak": {"datavalue": {"value": {"time": f"+{died}T00:00:00Z"}}}, "rank": "normal"}]}
    for pid, qid in extra.items():
        claims[pid] = [{"mainsnak": {"datavalue": {"value": {"id": qid}}}, "rank": "normal"}]
    return {"claims": claims}


PEOPLE = {
    "Q1": ("William Nordhaus", _person("2026-10-27"), 4715),
    "Q2": ("Little Known", _person("2026-10-28"), 300),
    "Q3": ("Old News", _person("2026-10-01"), 90000),
    "Q4": ("A Convict", _person("2026-10-29", P1399="Q99"), 50000),
    "Q5": ("Claude Cohen-Tannoudji", _person("2026-10-26"), 1664),
}


def _wire(monkeypatch):
    ledger.save(trends.DEATHS_CACHE, {"at": "2026-11-01T10:00:00+00:00",
                                      "rows": [{"title": t, "qid": q} for q, (t, _, _) in PEOPLE.items()]})
    monkeypatch.setattr(trends.wiki, "entities", lambda qids: {q: PEOPLE[q][1] for q in qids})
    views = {t: v for t, _, v in PEOPLE.values()}
    monkeypatch.setattr(trends.wiki, "daily_views", lambda title, days=30: [views[title] // 2, views[title]])


def test_notable_recent_deaths_become_tributes_and_the_rest_stay_out(monkeypatch):
    _wire(monkeypatch)
    out = trends.quiet_day_deaths(TODAY, lambda sid: True, [])
    assert [c["title"] for c in out] == ["William Nordhaus", "Claude Cohen-Tannoudji"]
    assert out[0]["id"] == "wk-Q1" and out[0]["kind"] == "death" and out[0]["fame"] == 4715
    assert out[0]["date"] == "2026-10-27" and out[0]["via"] == ["quiet day"]


def test_stories_the_desk_may_not_make_are_never_looked_up(monkeypatch):
    _wire(monkeypatch)
    asked = []
    monkeypatch.setattr(trends.wiki, "entities", lambda qids: asked.extend(qids) or {q: PEOPLE[q][1] for q in qids})
    out = trends.quiet_day_deaths(TODAY, lambda sid: sid != "wk-Q1", [])
    assert "Q1" not in asked and [c["title"] for c in out] == ["Claude Cohen-Tannoudji"]


def test_wikidata_down_is_an_error_not_a_crash(monkeypatch):
    _wire(monkeypatch)

    def down(qids):
        raise ConnectionError("timeout")

    monkeypatch.setattr(trends.wiki, "entities", down)
    errors = []
    assert trends.quiet_day_deaths(TODAY, lambda sid: True, errors) == [] and "quiet day" in errors[0]


def test_a_day_is_quiet_only_after_the_hour_and_with_no_short_out_or_scheduled():
    rows = [{"id": "wk-Q9", "published_at": "2026-10-31T23:32:27+00:00"}]
    assert not plan.quiet_day(datetime(2026, 11, 1, 13, 59, tzinfo=timezone.utc), rows)
    assert plan.quiet_day(datetime(2026, 11, 1, 14, 0, tzinfo=timezone.utc), rows)
    rows.append({"id": "wk-Q8", "published_at": "2026-11-01T20:00:00+00:00"})
    assert not plan.quiet_day(datetime(2026, 11, 1, 15, tzinfo=timezone.utc), rows)


def test_a_trending_story_still_ranks_above_a_quiet_day_tribute():
    at = datetime(2026, 11, 1, 15, tzinfo=timezone.utc)
    trending = {"id": "wk-Q7", "kind": "death", "category": "death", "fame": 60000, "date": "2026-10-31"}
    quiet = {"id": "wk-Q1", "kind": "death", "category": "death", "fame": 4715, "date": "2026-10-31"}
    assert plan.priority(trending, at) > plan.priority(quiet, at)
