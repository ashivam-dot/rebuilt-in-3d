"""Which topic this week's episode explains: chosen by a fixed rule from the channel's own numbers, so the same state
always picks the same topic and the reason is written down (plan.json "why").

Candidates are the natural hazards Orbitwire already covered as Shorts in the last WINDOW_DAYS: earthquakes grouped by
region ("How the M7.7 Panama quake ruptured" and its two Panama aftershock Shorts are one candidate), and named
storms. Score = the Shorts' summed 24-hour views x a data-richness factor (1 + log10(1 + events in the open catalogue
the history chapter draws on)). Decided 2026-10-22:
- views_24h, not average % viewed: state/performance.json has no retention for most videos (the audit's verify pass).
- 30 days, not the design's 10: a 10-day window had already lost the Panama Shorts the first episode builds on.
- Only quakes and storms: attacks, wars, protests, strikes and politics are never a long-form topic (advertiser
  suitability and the channel's own rule), and a death or an accident has no open catalogue to explain it from.
- A topic explained in the last REPEAT_DAYS is not explained again; with nothing left, an evergreen quake region.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone

WINDOW_DAYS = 30
REPEAT_DAYS = 90
EXCLUDE = re.compile(r"\b(attack\w*|shoot\w*|stabb\w*|war|wars|offensive|militar\w*|army|protest\w*|riot\w*|strike\w*|"
                     r"election\w*|vote|party|coup|bomb\w*|terror\w*|missile\w*|drone\w*)\b", re.I)
EXCLUDE_CATEGORIES = {"attack", "conflict", "protest", "strike", "politics", "war", "death"}
QUAKE_TITLE = re.compile(r"\bM(?P<mag>\d+(?:\.\d+)?) (?P<region>.+?) quake\b")
STORM_TITLE = re.compile(r"\b(?P<type>Hurricane|Typhoon|Cyclone|Tropical Storm) (?P<name>[A-Z][a-z]+)\b")
# Seismically active regions an episode can explain with no Short behind it: (name, lat, lon). The first one not
# explained in REPEAT_DAYS is used when no candidate qualifies.
EVERGREEN = [("Japan", 37.5, 142.0), ("Chile", -30.0, -71.5), ("Indonesia", -3.0, 120.0), ("Alaska", 58.0, -153.0),
             ("Nepal", 28.2, 84.7), ("Turkey", 38.5, 37.0), ("Mexico", 17.0, -99.5), ("New Zealand", -41.5, 174.0)]


def _when(text: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat((text or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def key_of(kind: str, topic: str) -> str:
    return f"{kind}:{topic.lower()}"


def recent_topics(longform: dict, at: datetime, days: int = REPEAT_DAYS) -> set[str]:
    """Topic keys explained (planned to publish) within `days` before `at`."""
    out = set()
    for row in (longform.get("episodes") or {}).values():
        when = _when(row.get("publish_at") or row.get("at"))
        if row.get("topic_key") and when and at - when < timedelta(days=days):
            out.add(row["topic_key"])
    return out


def slot_taken(longform: dict, publish_at: str, episode: str | None = None) -> str | None:
    """The episode (other than `episode`) already in the ledger for the same publish time or ISO week, if any: one
    episode a week. Without this, a re-run or a second run in a week picks the runner-up (the first topic is now
    "explained recently") and schedules it into the same Saturday slot."""
    want = _when(publish_at)
    if want is None:
        return None
    for key, row in (longform.get("episodes") or {}).items():
        if key == episode:
            continue
        when = _when(row.get("publish_at"))
        if when and (when == want or when.isocalendar()[:2] == want.isocalendar()[:2]):
            return key
    return None


def candidates(published: list[dict], performance: dict, retracted: set[str], at: datetime,
               window_days: int = WINDOW_DAYS) -> list[dict]:
    """The quake regions and storms covered in the window, each with its Shorts and their summed 24-hour views."""
    views = performance.get("videos") or {}
    since = at - timedelta(days=window_days)
    found: dict[str, dict] = {}
    for row in published:
        when = _when(row.get("published_at"))
        vid = row.get("video_id")
        title = row.get("title") or ""
        if not when or when < since or when > at or not vid or vid in retracted:
            continue
        if (row.get("category") or "") in EXCLUDE_CATEGORIES or EXCLUDE.search(title):
            continue
        if row.get("kind") == "quake" and (m := QUAKE_TITLE.search(title)):
            region = re.sub(r"^(?:the |central |northern |southern |eastern |western |off )+", "", m["region"], flags=re.I)
            kind, topic = "quake-region", region.strip()
            if re.search(r"\b(ridge|rise|ocean|sea|fracture zone)\b", topic, re.I):
                continue  # mid-ocean: no one felt it, nothing on land to show (quake.py's land rule)
            extra = {"event": row["id"][3:] if row["id"].startswith("eq-") else None, "mag": float(m["mag"])}
        elif row.get("category") == "cyclone" and (m := STORM_TITLE.search(title)):
            kind, topic, extra = "cyclone", m["name"], {"label": f"{m['type']} {m['name']}"}
        else:
            continue
        cand = found.setdefault(key_of(kind, topic), {"key": key_of(kind, topic), "kind": kind, "topic": topic,
                                                      "shorts": [], "views": 0.0, "events": []})
        cand["shorts"].append({"id": row["id"], "video_id": vid, "title": title,
                               "views_24h": round(float((views.get(vid) or {}).get("views_24h") or 0), 1)})
        cand["views"] = round(cand["views"] + cand["shorts"][-1]["views_24h"], 1)
        if extra.get("event"):
            cand["events"].append({"id": extra["event"], "mag": extra["mag"]})
        if extra.get("label"):
            cand["label"] = extra["label"]
    return sorted(found.values(), key=lambda c: c["key"])


def score(cand: dict, richness: int) -> float:
    return round(cand["views"] * (1 + math.log10(1 + max(richness, 0))), 1)


def pick(cands: list[dict], richness, longform: dict, at: datetime, override: str | None = None) -> tuple[dict, dict]:
    """(the chosen candidate, why): every candidate's views, richness and score, and what was excluded and why.
    richness(cand) -> int counts the catalogue events the history chapter would use (a network read in plan.py)."""
    done = recent_topics(longform, at)
    rows, chosen = [], None
    for c in cands:
        row = {"key": c["key"], "views_24h": c["views"], "shorts": [s["id"] for s in c["shorts"]]}
        if c["key"] in done:
            rows.append(row | {"excluded": f"explained in the last {REPEAT_DAYS} days"})
            continue
        try:
            n = int(richness(c))
        except Exception as exc:  # noqa: BLE001 - one unreadable catalogue never sinks the other candidates
            rows.append(row | {"excluded": f"catalogue unreadable: {type(exc).__name__}: {exc}"[:200]})
            continue
        c["richness"] = n
        c["score"] = score(c, n)
        rows.append(row | {"richness": n, "score": c["score"]})
    live = [c for c in cands if "score" in c]
    rule = (f"score = summed views_24h of the topic's Shorts in the last {WINDOW_DAYS} days x (1 + log10(1 + catalogue "
            "events)); ties go to the alphabetically first key")
    if override:
        want = override.strip().lower()
        chosen = next((c for c in cands if want in (c["key"], c["topic"].lower())), None)
        if chosen is None:
            chosen = evergreen(done, want)
        if chosen is None:
            raise ValueError(f"topic override {override!r} matches no candidate or evergreen region")
        how = f"owner override {override!r}"
    elif live:
        chosen = sorted(live, key=lambda c: (-c["score"], c["key"]))[0]
        how = "highest score"
    else:
        chosen = evergreen(done)
        if chosen is None:
            raise RuntimeError("no topic: every candidate and evergreen region was explained recently")
        how = "no candidate qualified: first evergreen region not explained recently"
    why = {"at": at.astimezone(timezone.utc).isoformat(timespec="seconds"), "rule": rule, "how": how,
           "chosen": chosen["key"], "candidates": rows}
    return chosen, why


def evergreen(done: set[str], want: str | None = None) -> dict | None:
    for name, lat, lon in EVERGREEN:
        key = key_of("quake-region", name)
        if (want is None and key not in done) or want in (key, name.lower()):
            return {"key": key, "kind": "quake-region", "topic": name, "shorts": [], "views": 0.0, "events": [],
                    "center": [lat, lon], "evergreen": True}
    return None
