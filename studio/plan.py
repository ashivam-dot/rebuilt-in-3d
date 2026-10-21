"""The editorial desk: which story to make next, and whether the channel may publish now.

The channel covers what the world is already looking at (see CHANNEL.md): incidents, protests and movements that
newsrooms lead with, famous deaths, and quakes that trend or that USGS rates PAGER yellow or worse, or magnitude 7+.

Priority is fame (Google News lead stories, Google Trends traffic, Wikipedia views) decayed by age, so a fresh
story beats a bigger stale one. Regular stories go out in their audience's waking hours (India stories 09:00-23:00
IST; world stories whenever Europe or the US is awake, 07:00-24:00 in London or in New York, which leaves only about
two hours before London's morning closed), at most twelve a UTC day, 40 minutes apart. A breaking story (huge fame or
five independent outlets on one incident, under 12 hours old, or a quake USGS rates orange or red or magnitude 7+)
may go out at any hour, 30 minutes after the last Short, as one more that day; wars and their strikes never take the
breaking lane. An ongoing story (protest, movement) comes back
at most once in COOLDOWN_DAYS, however its id changes. No more than two loss stories in any three consecutive
uploads.
An attack, shooting or stabbing that is not breaking ranks at 0.85 of its fame (ad suitability as a tie-break).
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import gdacs, ledger, news, outlets, trends, usgs
from .stories import km_between

MAX_PER_DAY = 12
MIN_GAP = timedelta(minutes=40)
BREAKING_GAP = timedelta(minutes=30)
BREAKING_FAME = 400_000
# Or this many independent outlets on one incident, BREAKING_STRONG of them official, public or international: a big
# story hours before Wikipedia's page views show it.
BREAKING_OWNERS, BREAKING_STRONG = 5, 2
BREAKING_MAX_AGE_H = 12
HALF_LIFE_H = {"death": 36, "quake": 18, "protest": 18, "movement": 18, "conflict": 12}
DEFAULT_HALF_LIFE_H = 24
# India's window in UTC hours (09:00-23:00 IST). The world window is local waking hours in any of WORLD_ZONES, so it
# follows daylight saving: 06:00-04:00 UTC in summer, 07:00-05:00 UTC in winter.
WINDOWS = {"india": (3.5, 17.5)}
WORLD_ZONES = (ZoneInfo("Europe/London"), ZoneInfo("America/New_York"))
WORLD_HOURS = (7.0, 24.0)
NO_BREAKING = ("conflict", "strike")
MIN_AGE_H, MAX_AGE_H = 3, 96
QUAKE_MIN_MAG = 6.0
# A quake is news when people felt it: it trends, USGS PAGER expects losses (yellow+), or it is M7+ near a named town.
# Lowering this to M6.5 green (2026-10-16) put a mid-ocean-ridge M6.8 and a green M6.9 in news slots: 5 and 2 views
# against 300-1,000 for the news they displaced.
QUAKE_BIG_MAG = 7.0
COOLDOWN_DAYS = {"protest": 6, "movement": 6}
# A quake with no trend signal ranks by USGS significance (about 600-2000 for these) on the fame scale.
SIG_TO_FAME = 100
# Ad suitability as a tie-break (2026-10-21): advertisers avoid violence, so an attack, shooting or stabbing ranks
# at AD_SUITABILITY of its fame unless it is breaking (five independent outlets on it), when it is the story to tell.
AD_SUITABILITY = 0.85
AD_UNSUITED = ("attack",)
AD_UNSUITED_WORDS = re.compile(r"\b(shootings?|stabbings?|attacks?)\b", re.I)


def can_publish(at: datetime | None = None, breaking: bool = False) -> str | None:
    at = at or datetime.now(timezone.utc)
    rows = ledger.published()
    today = [r for r in rows if r["published_at"][:10] == at.date().isoformat()]
    if len(today) >= MAX_PER_DAY + breaking:
        return f"already {len(today)} Shorts today"
    gap = BREAKING_GAP if breaking else MIN_GAP
    times = [datetime.fromisoformat(r["published_at"]) for r in rows]
    past, scheduled = [t for t in times if t <= at], [t for t in times if t > at]
    if past and at - max(past) < gap:
        return f"last Short went out {(at - max(past)).total_seconds() / 3600:.1f} h ago"
    if scheduled and min(scheduled) - at < gap:
        return f"a scheduled Short goes out in {(min(scheduled) - at).total_seconds() / 3600:.1f} h"
    return None


def age_hours(cand: dict, at: datetime) -> float:
    """Hours since the story broke. An ongoing story is as old as its newest lead headline; any other story is as old
    as the event itself, however fresh a follow-up headline is."""
    if cand.get("age_h") is not None:
        return float(cand["age_h"])
    ages = []
    if cand.get("news_at"):
        ages.append((at - datetime.fromisoformat(cand["news_at"])).total_seconds() / 3600)
    if cand.get("date") and cand.get("category") not in trends.ONGOING:
        day = datetime.fromisoformat(cand["date"]).replace(tzinfo=timezone.utc) + timedelta(hours=12)
        ages.append((at - day).total_seconds() / 3600)
    return max(0.0, *ages)


def priority(cand: dict, at: datetime) -> float:
    """Fame halved every half-life, times the channel's own learned lift: what the desk would lead with right now."""
    from . import learn

    half = HALF_LIFE_H.get(cand.get("kind"), HALF_LIFE_H.get(cand.get("category"), DEFAULT_HALF_LIFE_H))
    return cand.get("fame", 0) * 0.5 ** (age_hours(cand, at) / half) * learn.factor(cand) * ad_factor(cand, at)


def ad_factor(cand: dict, at: datetime) -> float:
    """AD_SUITABILITY for an attack, shooting or stabbing that is not breaking; 1.0 for everything else. The words
    count in an incident's title only: a tribute to someone who died of a heart attack is not violence."""
    unsuited = cand.get("category") in AD_UNSUITED or (
        cand.get("kind") == "incident" and AD_UNSUITED_WORDS.search(cand.get("title") or ""))
    return AD_SUITABILITY if unsuited and cand.get("kind") != "quake" and not is_breaking(cand, at) else 1.0


def ad_note(cands: list[dict], at: datetime | None = None) -> str | None:
    """The health line naming the candidates ad_factor ranked down, kept apart from lineup's hold notes so it never
    pushes one of them out of the health log."""
    at = at or datetime.now(timezone.utc)
    if scaled := [c["id"] for c in cands if ad_factor(c, at) < 1]:
        return f"ad-suitability x{AD_SUITABILITY} (attack, not breaking): {', '.join(scaled[:8])}"
    return None


def is_breaking(cand: dict, at: datetime) -> bool:
    if age_hours(cand, at) > BREAKING_MAX_AGE_H or cand.get("category") in NO_BREAKING:
        return False
    if cand.get("kind") == "quake":
        return cand.get("mag", 0) >= QUAKE_BIG_MAG or (cand.get("alert") or "") in ("orange", "red")
    who = cand.get("owners") or []
    if cand.get("kind") == "incident" and cand.get("category") not in trends.ONGOING and len(who) >= BREAKING_OWNERS \
            and len(outlets.strong(who)) >= BREAKING_STRONG:
        return True
    return cand.get("fame", 0) >= BREAKING_FAME


def cooling(cand: dict, at: datetime, rows: list[dict]) -> bool:
    """True when this ongoing story already went out within its cool-down, under any id (weekly or series part)."""
    days = COOLDOWN_DAYS.get(cand.get("category"))
    if not days or not cand.get("qid"):
        return False
    stem = f"wk-{cand['qid']}"
    return any(r["id"] == stem or r["id"].startswith(stem + "-")
               for r in rows if at - datetime.fromisoformat(r["published_at"]) < timedelta(days=days))


TOLD_DAYS = 7


def told_before(cand: dict, rows: list[dict], at: datetime, moved: dict[str, str] | None = None) -> bool:
    """True when this story went out in the last TOLD_DAYS under another id: first told from outlet reporting (nw-)
    and now from its Wikipedia article, or the other way round. One story shares a report URL, or its nw- ids name
    the same place and kind, or an nw- story's headlines name the article. A story told by its Wikidata item and
    back by its title (wp-) after its article moved is the same article: moved maps each told article to where it
    now lives (renamed; "October 2026 attacks on Saudi airports" became "...Houthi attacks on Saudi Arabian airports"
    and went out twice, 2026-10-14 and 2026-10-16)."""
    urls = {r["url"] for r in cand.get("reports") or []}
    for r in rows:
        if at - datetime.fromisoformat(r["published_at"]) > timedelta(days=TOLD_DAYS):
            continue
        if r.get("article") and (cand["id"].startswith("wp-") or r["id"].startswith("wp-")) and \
                {r["article"], (moved or {}).get(r["article"], r["article"])} & {cand.get("title"), cand.get("article")}:
            return True
        if not (r["id"].startswith("nw-") or cand["id"].startswith("nw-")):
            continue  # stories told from Wikipedia on both sides are matched by their ids already
        if urls & set(r.get("report_urls") or []) or outlets.same_story(cand["id"], r["id"]):
            return True
        if r.get("article") and r["article"] in (cand.get("title"), cand.get("article")):
            return True  # told from the reporting while its article was too new to use
        if r["id"].startswith("nw-") and not cand["id"].startswith("nw-"):
            heads, title = r.get("headlines") or [], cand.get("title")
        elif cand["id"].startswith("nw-") and not r["id"].startswith("nw-"):
            heads, title = cand.get("headlines") or [], r.get("article")
        else:
            continue
        if title and any(news.reverse(h, [news.pool_item(title)]) for h in heads):
            return True
    return False


def renamed(rows: list[dict], at: datetime) -> dict[str, str]:
    """Where each article told in the last TOLD_DAYS lives now (a moved page leaves a redirect); {} when Wikipedia
    cannot be read."""
    from . import wiki

    titles = list(dict.fromkeys(r["article"] for r in rows if r.get("article")
                                and at - datetime.fromisoformat(r["published_at"]) <= timedelta(days=TOLD_DAYS)))
    try:
        info = wiki.page_info(titles) if titles else {}
    except Exception:
        return {}
    return {t: info[t]["title"] for t in titles if t in info}


def outlet_note(stats: dict, emerging: list[dict]) -> str:
    lane = "on" if trends.NEW_STORIES else "off: STUDIO_NEW_STORIES"
    return (f"outlets: {stats['headlines']} headlines from {stats['feeds']} feeds ({stats['owners']} owners), "
            f"{stats['matched']} matched to articles, {stats['corroborated']} candidates with 2+ owners, "
            f"{len(emerging)} nw- stories ({lane})" + (f": {', '.join(c['id'] for c in emerging[:3])}" if emerging else ""))


def in_window(cand: dict, at: datetime) -> bool:
    if cand.get("region", "world") not in WINDOWS:
        start, end = WORLD_HOURS
        return any(start <= (t := at.astimezone(zone)).hour + t.minute / 60 < end for zone in WORLD_ZONES)
    start, end = WINDOWS[cand["region"]]
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
        near_people = usgs.parse_place(q.place)["distance_km"] is not None
        big = (q.mag >= QUAKE_BIG_MAG and near_people) or (q.alert or "") in ("yellow", "orange", "red")
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
        if radar.get("outlets"):
            found["outlets"] = radar["outlets"]
            found["emerging"] = radar.get("emerging", [])
            found["outlet_note"] = outlet_note(radar["outlets"], found["emerging"])
    except Exception as exc:  # the quake lane must keep working when Wikipedia or Trends is down
        found["trend_errors"] = [f"{type(exc).__name__}: {exc}"[:200]]
    quakes_trending = [c for c in found["trending"] if c.get("category") == "earthquake"]
    found["quakes"] = quake_candidates(quakes_trending)
    # Stories are told with real photos now, so an incident no longer needs coordinates to qualify.
    at = datetime.now(timezone.utc)
    rows = ledger.published()
    moved = renamed(rows, at)
    stories = [c for c in found["trending"] if c.get("category") != "earthquake" and not ledger.is_done(c["id"])
               and not cooling(c, at, rows) and not ledger.is_done(trends.article_id(c["title"]))
               and not told_before(c, rows, at, moved)]
    found["candidates"] = sorted(found["quakes"] + stories, key=lambda c: -priority(c, at))
    try:
        found["hazards"] = gdacs.alerts()
    except Exception as exc:  # GDACS is context only; a failure must not stop the quake lane
        found["hazards_error"] = str(exc)[:200]
    ledger.save("candidates", found)
    return found
