"""What the channel's numbers said on 2026-11-05: weekly protest retells that flopped, and the evening tribute test."""
from datetime import datetime, timedelta, timezone

from studio import ledger, plan

AT = datetime(2026, 11, 5, 14, 0, tzinfo=timezone.utc)
PERF = {"learned": {"baseline_views_24h": 197},
        "videos": {"V44": {"views_24h": 65}, "V43": {"views_24h": 420}}}


def _row(id_, vid, hours_ago):
    return {"id": id_, "video_id": vid, "published_at": (AT - timedelta(hours=hours_ago)).isoformat()}


def test_a_weekly_retell_waits_for_its_last_short_to_have_drawn_half_the_baseline():
    cand = {"id": "wk-Q141615137-2026w45", "qid": "Q141615137", "category": "protest"}
    rows = [_row("wk-Q141615137-2026w44", "V44", 240)]
    assert plan.retell_flopped(cand, rows, PERF)  # French student protests: 65 views in week 44
    assert not plan.retell_flopped(cand, [_row("wk-Q141615137-2026w44", "V43", 240)], PERF)
    # Not judged: a first telling, a Short with no 24 h read yet, no baseline, a story that is not ongoing.
    assert not plan.retell_flopped(cand, [], PERF)
    assert not plan.retell_flopped(cand, [_row("wk-Q141615137-2026w44", "NEW", 5)], PERF)
    assert not plan.retell_flopped(cand, rows, {"videos": PERF["videos"]})
    assert not plan.retell_flopped(cand | {"category": "death"}, rows, PERF)


def test_the_evening_test_splits_daytime_tributes_and_never_holds_breaking_news():
    arms = {}
    for i in range(40):
        slot, arm = plan.evening_slot({"id": f"wk-Q{i}", "kind": "death"}, AT, [])
        arms.setdefault(arm, []).append(slot)
    assert set(arms) == {"held", "control"} and len(arms["held"]) > 5 and len(arms["control"]) > 5
    assert all(s is None for s in arms["control"])
    assert all(s == AT.replace(hour=20, minute=30) for s in arms["held"])
    held = next(f"wk-Q{i}" for i in range(40) if plan.evening_slot({"id": f"wk-Q{i}", "kind": "death"}, AT, [])[1] == "held")
    tribute = {"id": held, "kind": "death"}
    for out_of_test in (tribute | {"breaking": True}, tribute | {"kind": "incident"}):
        assert plan.evening_slot(out_of_test, AT, []) == (None, None)
    for hour in (11, 20, 23):
        assert plan.evening_slot(tribute, AT.replace(hour=hour), []) == (None, None)
    # A Short already scheduled at 20:30 moves the held one a gap later.
    taken = [{"published_at": AT.replace(hour=20, minute=30).isoformat()}]
    assert plan.evening_slot(tribute, AT, taken)[0] == AT.replace(hour=20, minute=30) + plan.MIN_GAP
    plan.EVENING_TEST, was = False, plan.EVENING_TEST
    try:
        assert plan.evening_slot(tribute, AT, []) == (None, None)
    finally:
        plan.EVENING_TEST = was


def test_a_held_tribute_is_scheduled_and_its_arm_recorded(monkeypatch):
    from studio import cli
    from studio.spec import Short

    from .test_youtube import FIXTURE

    held = next(f"wk-Q{i}" for i in range(40)
                if plan.evening_slot({"id": f"wk-Q{i}", "kind": "death"}, AT, [])[1] == "held")
    cand = {"id": held, "kind": "death", "fame": 9}
    short = Short.load(FIXTURE)
    monkeypatch.setattr(ledger, "set_identity", lambda: None)
    monkeypatch.setattr(cli.learn, "refresh", lambda: None)
    monkeypatch.setattr(cli, "datetime", type("D", (datetime,), {"now": staticmethod(lambda tz=None: AT)}))
    from studio import youtube

    monkeypatch.setattr(youtube, "client", lambda *a: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(plan, "watch", lambda: {"candidates": [cand], "quakes": [], "trending": [], "hazards": []})
    monkeypatch.setattr(plan, "lineup", lambda c: (c, []))
    monkeypatch.setattr(cli, "prepare", lambda c: short)
    monkeypatch.setattr(cli, "make", lambda c, s: (s, {"duration": 40}))
    monkeypatch.setattr(cli.gate, "channel_mix", lambda *a: None)
    calls = []

    def publish(story_id, publish_at=None, extra=None):
        calls.append((publish_at, extra))
        return {"url": "https://www.youtube.com/shorts/x"}

    monkeypatch.setattr(cli, "publish", publish)
    assert cli.run()["ok"]
    assert calls == [(AT.replace(hour=20, minute=30).isoformat(), {"slot_test": "held"})]
