"""Which story to make next, and whether the channel may publish now.

Rules (from research/market-policy.md): explainers 3-96 hours after the event, at most two Shorts a UTC day and
four hours apart, and no more than two loss stories in any three consecutive uploads.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import gdacs, ledger, usgs

MAX_PER_DAY = 2
MIN_GAP = timedelta(hours=4)
MIN_AGE_H, MAX_AGE_H = 3, 96
QUAKE_MIN_MAG = 6.0


def can_publish(at: datetime | None = None) -> str | None:
    at = at or datetime.now(timezone.utc)
    rows = ledger.published()
    today = [r for r in rows if r["published_at"][:10] == at.date().isoformat()]
    if len(today) >= MAX_PER_DAY:
        return f"already {len(today)} Shorts today"
    if rows:
        last = max(datetime.fromisoformat(r["published_at"]) for r in rows)
        if at - last < MIN_GAP:
            return f"last Short went out {(at - last).total_seconds() / 3600:.1f} h ago"
    return None


def quake_candidates() -> list[dict]:
    out = []
    for q in usgs.recent():
        sid = f"eq-{q.id}"
        if q.mag < QUAKE_MIN_MAG or not MIN_AGE_H <= q.age_hours <= MAX_AGE_H or ledger.is_done(sid):
            continue
        score = q.sig + {"yellow": 150, "orange": 300, "red": 500}.get(q.alert or "", 0)
        out.append({"id": sid, "kind": "quake", "event": q.id, "title": q.place, "mag": q.mag, "score": score,
                    "age_h": round(q.age_hours, 1), "alert": q.alert})
    return sorted(out, key=lambda c: -c["score"])


def watch() -> dict:
    """Everything the watcher sees this run, written to state/candidates.json for the record."""
    found = {"at": ledger.now(), "quakes": quake_candidates(), "hazards": []}
    try:
        found["hazards"] = gdacs.alerts()
    except Exception as exc:  # GDACS is context only; a failure must not stop the quake lane
        found["hazards_error"] = str(exc)[:200]
    ledger.save("candidates", found)
    return found
