import math
from datetime import datetime, timedelta, timezone

import pytest

from studio import learn, ledger, plan, youtube

AT = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "STATE", tmp_path)
    learn._cache.clear()
    return tmp_path


def test_views_at_interpolates_and_waits_for_age():
    snaps = [{"age_h": 12, "views": 100}, {"age_h": 36, "views": 300}]
    assert learn.views_at(snaps, 24) == pytest.approx(200)
    assert learn.views_at([{"age_h": 10, "views": 50}], 24) is None
    assert learn.views_at([{"age_h": 96, "views": 400}], 24) == pytest.approx(200)


def _video(i, views, category="death", kind="incident"):
    return {"id": f"s{i}", "published_at": AT.isoformat(), "category": category, "kind": kind,
            "views_24h": views, "snapshots": []}


def test_no_lift_below_min_samples():
    out = learn.learn([_video(i, 100) for i in range(learn.MIN_SAMPLES - 1)])
    assert out["lifts"] == {}


def test_lifts_are_shrunk_and_bounded():
    vids = [_video(i, 10_000, "earthquake") for i in range(4)] + [_video(10 + i, 10, "death") for i in range(4)]
    lifts = learn.learn(vids)["lifts"]
    assert lifts["category:earthquake"]["lift"] == learn.LIFT_RANGE[1]
    assert lifts["category:death"]["lift"] == learn.LIFT_RANGE[0]
    assert "kind:incident" in lifts and lifts["kind:incident"]["lift"] == pytest.approx(1.0)
    mild = [_video(i, 130, "earthquake") for i in range(4)] + [_video(10 + i, 100, "death") for i in range(4)]
    gap = math.log(131 / 101) / 2
    assert learn.learn(mild)["lifts"]["category:earthquake"]["lift"] == pytest.approx(math.exp(gap * 0.5), abs=1e-3)


def test_factor_defaults_to_one_and_steers_priority():
    cand = {"category": "earthquake", "fame": 1000, "kind": "earthquake",
            "date": AT.isoformat()}
    base = plan.priority(cand, AT)
    assert learn.factor(cand) == 1.0
    ledger.save("performance", {"at": "x", "learned": {"lifts": {"category:earthquake": {"lift": 1.2}}}})
    assert learn.factor(cand) == pytest.approx(1.2)
    assert plan.priority(cand, AT) == pytest.approx(base * 1.2)


def test_refresh_snapshots_scores_and_throttles(monkeypatch, state):
    rows = [{"id": f"s{i}", "video_id": f"v{i}", "kind": "story", "category": "death", "region": "world",
             "published_at": (AT - timedelta(hours=30)).isoformat()} for i in range(5)]
    rows.append({"id": "later", "video_id": "vf", "published_at": (AT + timedelta(hours=2)).isoformat()})
    ledger.save("published", rows)
    monkeypatch.setattr(youtube, "identity", lambda api: {})
    monkeypatch.setattr(youtube, "recent", lambda api, ch: [
        {"id": f"v{i}", "statistics": {"viewCount": str(100 * (i + 1)), "likeCount": "3"}} for i in range(5)]
        + [{"id": "vf", "statistics": {"viewCount": "0"}}])
    learned = learn.refresh(at=AT, api=object())
    assert learned["scored"] == 5 and "category:death" in learned["lifts"]
    perf = ledger.load("performance", {})
    assert set(perf["videos"]) == {f"v{i}" for i in range(5)}
    assert perf["videos"]["v0"]["snapshots"][0]["likes"] == 3
    assert (state / "LEARNINGS.md").read_text().startswith("# What this channel's own numbers say")
    assert learn.refresh(at=AT + timedelta(hours=1), api=object()) is None
    assert learn.refresh(at=AT + learn.REFRESH, api=object()) is not None
    assert len(ledger.load("performance", {})["videos"]["v0"]["snapshots"]) == 2


def test_without_retention_data_lifts_are_views_alone():
    vids = [_video(i, 130, "earthquake") for i in range(4)] + [_video(10 + i, 100, "death") for i in range(4)]
    out = learn.learn(vids)
    assert "baseline_view_pct" not in out and "n_retention" not in out["lifts"]["category:earthquake"]
    # Too few records with the field: still views alone.
    few = [v | {learn.RETENTION_FIELD: 90} for v in vids[:3]] + vids[3:]
    assert learn.learn(few)["lifts"] == out["lifts"]


def test_retention_is_blended_into_lifts_shrunk_and_bounded():
    same = [_video(i, 100, "earthquake") for i in range(4)] + [_video(10 + i, 100, "death") for i in range(4)]
    held = [v | {learn.RETENTION_FIELD: 80 if v["category"] == "earthquake" else 40} for v in same]
    out = learn.learn(held)
    assert out["baseline_view_pct"] == pytest.approx(math.expm1((math.log(81) + math.log(41)) / 2), abs=0.1)
    quake, death = out["lifts"]["category:earthquake"], out["lifts"]["category:death"]
    gap = (math.log(81) - math.log(41)) / 2 * 0.5  # each side's distance from the channel's mean, shrunk by 4/8
    assert quake["lift"] == pytest.approx(math.exp(learn.RETENTION_WEIGHT * gap), abs=1e-3)
    assert death["lift"] == pytest.approx(math.exp(-learn.RETENTION_WEIGHT * gap), abs=1e-3)
    assert quake["n_retention"] == 4 and quake["typical_view_pct"] == pytest.approx(80, abs=0.1)
    assert out["lifts"]["kind:incident"]["lift"] == pytest.approx(1.0)  # every Short is one kind: no signal
    # Equal views, wildly different retention: the lift stays within LIFT_RANGE.
    wild = [v | {learn.RETENTION_FIELD: 10_000 if v["category"] == "earthquake" else 0} for v in same]
    lifts = learn.learn(wild)["lifts"]
    assert lifts["category:earthquake"]["lift"] == learn.LIFT_RANGE[1]
    assert lifts["category:death"]["lift"] == learn.LIFT_RANGE[0]
    report = learn.report({"at": "x", "learned": out, "videos": {}})
    assert "Retention: a typical Short" in report
    assert f"category:earthquake: x{quake['lift']} ranking lift (4 Shorts, typical 100 views; 4 with retention, " \
           "typically 80.0% watched)" in report
    # A lift learned from views alone says nothing about retention.
    assert "with retention" not in learn.report({"at": "x", "learned": learn.learn(same), "videos": {}})


class _Request:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class _Analytics:
    """A fake YouTube Analytics v2 client: answers reports().query with `rows`, or raises `error`."""
    def __init__(self, rows=(), error=None):
        self.rows, self.error, self.asked = list(rows), error, []

    def reports(self):
        return self

    def query(self, **params):
        self.asked.append(params)

        def answer():
            if self.error:
                raise self.error
            ids = params["filters"].removeprefix("video==").split(",")
            return {"columnHeaders": [{"name": n} for n in ("video", "views", "engagedViews", "averageViewPercentage")],
                    "rows": [r for r in self.rows if r[0] in ids]}
        return _Request(answer)


def _refused(status):
    from googleapiclient.errors import HttpError
    from httplib2 import Response
    return HttpError(Response({"status": status}), b'{"error": {"message": "Insufficient permission"}}')


def test_analytics_reads_only_shorts_three_days_old():
    fake = _Analytics([["old", 900, 610, 72.5], ["mid", 50, 40, 60.0]])
    published = {"old": (AT - timedelta(days=5)).isoformat(), "mid": (AT - timedelta(days=3)).isoformat(),
                 "new": (AT - timedelta(days=2, hours=23)).isoformat()}
    got, note = youtube.analytics(fake, published, AT)
    assert note is None
    assert got == {"old": {"views": 900, "engaged_views": 610, "avg_view_pct": 72.5},
                   "mid": {"views": 50, "engaged_views": 40, "avg_view_pct": 60.0}}
    q = fake.asked[0]
    assert q["ids"] == "channel==MINE" and q["metrics"] == "views,engagedViews,averageViewPercentage"
    assert q["dimensions"] == "video" and q["filters"] == "video==mid,old"  # the 2-day-old Short is not asked about
    assert q["startDate"] == (AT - timedelta(days=5)).date().isoformat() and q["endDate"] == AT.date().isoformat()
    assert youtube.analytics(fake, {"new": published["new"]}, AT) == ({}, None) and len(fake.asked) == 1


def test_analytics_without_the_scope_is_a_quiet_no_op():
    published = {"old": (AT - timedelta(days=5)).isoformat()}
    for status in (401, 403):
        got, note = youtube.analytics(_Analytics(error=_refused(status)), published, AT)
        assert got == {} and "yt-analytics.readonly" in note
    from google.auth.exceptions import RefreshError
    got, note = youtube.analytics(_Analytics(error=RefreshError("invalid_scope")), published, AT)
    assert got == {} and "invalid_scope" in note
    with pytest.raises(Exception):  # any other failure is not a scope problem: refresh() reports it
        youtube.analytics(_Analytics(error=_refused(500)), published, AT)


def _published(monkeypatch, n=5, age=timedelta(days=4)):
    rows = [{"id": f"s{i}", "video_id": f"v{i}", "kind": "incident", "category": "cyclone" if i < 4 else "death",
             "published_at": (AT - age).isoformat()} for i in range(n)]
    ledger.save("published", rows)
    monkeypatch.setattr(youtube, "identity", lambda api: {})
    monkeypatch.setattr(youtube, "recent", lambda api, ch: [
        {"id": f"v{i}", "statistics": {"viewCount": "100"}} for i in range(n)])


def test_refresh_feeds_retention_into_the_performance_data(monkeypatch):
    _published(monkeypatch)
    fake = _Analytics([[f"v{i}", 100, 70, 80.0 if i < 4 else 40.0] for i in range(5)])
    learned = learn.refresh(at=AT, api=object(), analytics=fake)
    assert "note" not in learned and learned["baseline_view_pct"] is not None
    assert learned["lifts"]["category:cyclone"]["n_retention"] == 4
    rec = ledger.load("performance", {})["videos"]["v0"]
    assert rec[learn.RETENTION_FIELD] == 80.0 and rec["engaged_views"] == 70


def test_refresh_without_analytics_access_keeps_learning_from_views(monkeypatch):
    _published(monkeypatch)
    learned = learn.refresh(at=AT, api=object(), analytics=_Analytics(error=_refused(403)))
    assert learned["scored"] == 5 and "yt-analytics.readonly" in learned["note"]
    assert "baseline_view_pct" not in learned
    assert learn.RETENTION_FIELD not in ledger.load("performance", {})["videos"]["v0"]
    # Any other Analytics failure is one note too, never a lost views refresh.
    boom = _Analytics(error=ValueError("bad rows"))
    learned = learn.refresh(at=AT + learn.REFRESH, api=object(), analytics=boom)
    assert learned["scored"] == 5 and learned["note"] == "analytics: ValueError: bad rows"
    # Passing only the Data API client (as the tests above do) reads no retention and says nothing.
    assert "note" not in learn.refresh(at=AT + 2 * learn.REFRESH, api=object())


def test_refresh_keeps_a_records_retention(monkeypatch):
    published = (AT - timedelta(hours=30)).isoformat()
    ledger.save("published", [{"id": "s0", "video_id": "v0", "kind": "incident", "category": "death",
                               "published_at": published}])
    ledger.save("performance", {"at": None, "videos": {"v0": {"id": "s0", "published_at": published,
                                                              "snapshots": [], learn.RETENTION_FIELD: 55.0}}})
    monkeypatch.setattr(youtube, "identity", lambda api: {})
    monkeypatch.setattr(youtube, "recent", lambda api, ch: [{"id": "v0", "statistics": {"viewCount": "9"}}])
    learn.refresh(at=AT, api=object())
    assert ledger.load("performance", {})["videos"]["v0"][learn.RETENTION_FIELD] == 55.0
