"""Which story to make next, and whether the channel may publish now.

The channel covers what the world is already looking at (see CHANNEL.md): trending incidents and famous deaths from
the trend radar, plus quakes that trend or that USGS rates PAGER yellow or worse, or magnitude 7+. Everything is
ranked by fame: daily Wikipedia views plus Google Trends traffic. At most three Shorts a UTC day, three hours apart,
and no more than two loss stories in any three consecutive uploads.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from . import gdacs, ledger, trends, usgs
from .stories import km_between

MAX_PER_DAY = 3
MIN_GAP = timedelta(hours=3)
MIN_AGE_H, MAX_AGE_H = 3, 96
QUAKE_MIN_MAG = 6.0
QUAKE_BIG_MAG = 7.0
# A quake with no trend signal ranks by USGS significance (about 600-2000 for these) on the fame scale.
SIG_TO_FAME = 100


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


def quake_candidates(trending_quakes: list[dict] | None = None) -> list[dict]:
    trending_quakes = trending_quakes or []
    out = []
    for q in usgs.recent():
        sid = f"eq-{q.id}"
        if q.mag < QUAKE_MIN_MAG or not MIN_AGE_H <= q.age_hours <= MAX_AGE_H or ledger.is_done(sid):
            continue
        match = next((t for t in trending_quakes if t.get("coords") and abs(
            (date.fromisoformat(t["date"]) - q.time.date()).days) <= 1 and km_between(tuple(t["coords"]), (q.lat, q.lon)) < 300), None)
        big = q.mag >= QUAKE_BIG_MAG or (q.alert or "") in ("yellow", "orange", "red")
        if not match and not big:
            continue
        fame = match["fame"] if match else q.sig * SIG_TO_FAME
        out.append({"id": sid, "kind": "quake", "event": q.id, "title": q.place, "mag": q.mag, "fame": fame,
                    "age_h": round(q.age_hours, 1), "alert": q.alert, "trending": bool(match)})
    return out


def watch() -> dict:
    """Everything the watcher sees this run, written to state/candidates.json for the record."""
    found = {"at": ledger.now(), "quakes": [], "trending": [], "hazards": [], "candidates": []}
    try:
        radar = trends.radar()
        found["trending"] = radar["candidates"]
        if radar["errors"]:
            found["trend_errors"] = radar["errors"]
    except Exception as exc:  # the quake lane must keep working when Wikipedia or Trends is down
        found["trend_errors"] = [f"{type(exc).__name__}: {exc}"[:200]]
    quakes_trending = [c for c in found["trending"] if c.get("category") == "earthquake"]
    found["quakes"] = quake_candidates(quakes_trending)
    stories = [c for c in found["trending"] if c.get("category") != "earthquake" and not ledger.is_done(c["id"])
               and (c["kind"] == "death" or c.get("has_coords"))]
    found["candidates"] = sorted(found["quakes"] + stories, key=lambda c: -c["fame"])
    try:
        found["hazards"] = gdacs.alerts()
    except Exception as exc:  # GDACS is context only; a failure must not stop the quake lane
        found["hazards_error"] = str(exc)[:200]
    ledger.save("candidates", found)
    return found
