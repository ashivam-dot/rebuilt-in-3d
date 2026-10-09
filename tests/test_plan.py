from datetime import datetime, timezone

from studio import ledger, plan


def test_publish_cadence(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "STATE", tmp_path)
    at = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
    assert plan.can_publish(at) is None
    ledger.record_publish({"id": "eq-a", "published_at": "2026-10-09T10:00:00+00:00", "loss": False})
    assert "h ago" in plan.can_publish(at)
    ledger.record_publish({"id": "eq-b", "published_at": "2026-10-09T03:00:00+00:00", "loss": False})
    assert plan.can_publish(datetime(2026, 10, 9, 20, tzinfo=timezone.utc)) is None
    ledger.record_publish({"id": "wk-c", "published_at": "2026-10-09T06:30:00+00:00", "loss": False})
    assert "today" in plan.can_publish(datetime(2026, 10, 9, 20, tzinfo=timezone.utc))
    assert plan.can_publish(datetime(2026, 10, 10, 1, tzinfo=timezone.utc)) is None


def test_ledger_skip_marks_done(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "STATE", tmp_path)
    assert not ledger.is_done("eq-x")
    ledger.skip("eq-x", "gate: test")
    assert ledger.is_done("eq-x")
