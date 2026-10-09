"""The editorial desk: which story to make next, and whether the channel may publish now.

The channel covers what the world is already looking at (see CHANNEL.md): incidents, protests and movements that
newsrooms lead with, famous deaths, and quakes that trend or that USGS rates PAGER yellow or worse, or magnitude 7+.

Priority is fame (Google News lead stories, Google Trends traffic, Wikipedia views) decayed by age, so a fresh
story beats a bigger stale one. Regular stories go out in their audience's waking hours (India stories 09:00-23:00
IST, world stories 07:00-24:00 US Eastern), at most five a UTC day, two hours apart. A breaking story (huge fame,
under 12 hours old) may go out at any hour, 75 minutes after the last Short, as a sixth that day. No more than two
loss stories in any three consecutive uploads.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from . import gdacs, ledger, trends, usgs
from .stories import km_between

MAX_PER_DAY = 5
MIN_GAP = timedelta(hours=2)
BREAKING_GAP = timedelta(minutes=75)
BREAKING_FAME = 400_000
BREAKING_MAX_AGE_H = 12
HALF_LIFE_H = {"death": 36, "quake": 18, "protest": 18, "movement": 18, "conflict": 12}
DEFAULT_HALF_LIFE_H = 24
# Publishing windows in UTC hours; the world window runs past midnight UTC into the US evening.
WINDOWS = {"india": (3.5, 17.5), "world": (11.0, 28.0)}
MIN_AGE_H, MAX_AGE_H = 3, 96
QUAKE_MIN_MAG = 6.0
QUAKE_BIG_MAG = 7.0
# A quake with no trend signal ranks by USGS significance (about 600-2000 for these) on the fame scale.
SIG_TO_FAME = 100


def can_publish(at: datetime | None = None, breaking: bool = False) -> str | None:
    at = at or datetime.now(timezone.utc)
    rows = ledger.published()
    today = [r for r in rows if r["published_at"][:10] == at.date().isoformat()]
    if len(today) >= MAX_PER_DAY + breaking:
        return f"already {len(today)} Shorts today"
    if rows:
        last = max(datetime.fromisoformat(r["published_at"]) for r in rows)
        if at - last < (BREAKING_GAP if breaking else MIN_GAP):
            return f"last Short went out {(at - last).total_seconds() / 3600:.1f} h ago"
    return None


def age_hours(cand: dict, at: datetime) -> float:
    if cand.get("age_h") is not None:
        return float(cand["age_h"])
    if cand.get("news_at"):
        return max(0.0, (at - datetime.fromisoformat(cand["news_at"])).total_seconds() / 3600)
    if cand.get("date"):
        day = datetime.fromisoformat(cand["date"]).replace(tzinfo=timezone.utc) + timedelta(hours=12)
        return max(0.0, (at - day).total_seconds() / 3600)
    return 0.0


def priority(cand: dict, at: datetime) -> float:
    """Fame halved every half-life: what the desk would lead with right now."""
    half = HALF_LIFE_H.get(cand.get("kind"), HALF_LIFE_H.get(cand.get("category"), DEFAULT_HALF_LIFE_H))
    return cand.get("fame", 0) * 0.5 ** (age_hours(cand, at) / half)


def is_breaking(cand: dict, at: datetime) -> bool:
    return cand.get("fame", 0) >= BREAKING_FAME and age_hours(cand, at) <= BREAKING_MAX_AGE_H


def in_window(cand: dict, at: datetime) -> bool:
    start, end = WINDOWS.get(cand.get("region", "world"), WINDOWS["world"])
    hour = at.hour + at.minute / 60
    return start <= hour < end or start <= hour + 24 < end


def lineup(cands: list[dict], at: datetime | None = None) -> tuple[list[dict], list[str]]:
    """Candidates the desk would publish now, best first, and a note for each one it is holding back."""
    at = at or datetime.now(timezone.utc)
    regular, urgent = can_publish(at), can_publish(at, breaking=True)
    ready, notes = [], []
    for c in sorted(cands, key=lambda c: -priority(c, at)):
        breaking = is_breaking(c, at)
        wait = urgent if breaking else regular or (None if in_window(c, at) else f"outside the {c.get('region', 'world')} window")
        if wait:
            notes.append(f"hold {c['id']}: {wait}")
        else:
            ready.append(c | {"breaking": breaking, "priority": round(priority(c, at))})
    return ready, notes


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
    # Stories are told with real photos now, so an incident no longer needs coordinates to qualify.
    stories = [c for c in found["trending"] if c.get("category") != "earthquake" and not ledger.is_done(c["id"])]
    at = datetime.now(timezone.utc)
    found["candidates"] = sorted(found["quakes"] + stories, key=lambda c: -priority(c, at))
    try:
        found["hazards"] = gdacs.alerts()
    except Exception as exc:  # GDACS is context only; a failure must not stop the quake lane
        found["hazards_error"] = str(exc)[:200]
    ledger.save("candidates", found)
    return found
