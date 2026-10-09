"""Trend radar: which famous, fresh stories the world is looking at right now.

Fame comes from three public signals: Google News lead stories in India, the US and the world (minutes old),
Google Trends trending searches in the US, India and the UK (hourly) and English Wikipedia's most-read articles
(daily). Each hit is resolved to a Wikipedia article and its Wikidata item, then classified. Three shapes of story
pass: a recent incident, a protest or public movement that newsrooms are leading with, or the recent death of a
famous person. Sport, celebrity gossip, party politics and crime trials are ignored by design.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

from . import net, news, wiki

GEOS = ("US", "IN", "GB")
INDIA = "Q668"
# Protests and movements are ongoing: they qualify while lead stories are about them, unless they have ended or began
# long ago (an ideology or an old movement is not news because a headline mentions it). A war is not: a months-old
# war always has headlines, and its Shorts became generic "human cost" pieces. New strikes and attacks in a war still
# qualify as incidents through their own articles.
ONGOING = ("protest", "movement")
ONGOING_MAX_YEARS = 2
ONGOING_MIN_HEADLINES = 2
TRENDS_RSS = "https://trends.google.com/trending/rss?geo={geo}"
HT = "{https://trends.google.com/trending/rss}"
TOP_N = 400
INCIDENT_MAX_DAYS = 30
DEATH_MAX_DAYS = 10
SUICIDE = "Q10737"


def google_trends(geo: str) -> list[dict]:
    root = ET.fromstring(net.get(TRENDS_RSS.format(geo=geo), tries=2))
    out = []
    for item in root.iter("item"):
        traffic = re.sub(r"[^\d]", "", item.findtext(f"{HT}approx_traffic") or "0") or "0"
        news = [n.findtext(f"{HT}news_item_title") or "" for n in item.iter(f"{HT}news_item")]
        out.append({"query": item.findtext("title") or "", "traffic": int(traffic), "geo": geo, "news": news[:3]})
    return out


def _signals() -> tuple[dict[str, dict], list[str]]:
    """title -> {views, traffic, via}; plus any errors (one failed source must not stop the radar)."""
    hits: dict[str, dict] = {}
    errors = []
    try:
        day, top = wiki.top_articles()
        for title, views in top[:TOP_N]:
            hits.setdefault(title, {"views": 0, "traffic": 0, "via": []})
            hits[title]["views"] = views
            hits[title]["via"].append(f"wikipedia-top-{day.isoformat()}")
    except Exception as exc:
        errors.append(f"wikipedia top: {exc}"[:200])
    for geo in GEOS:
        try:
            trends = google_trends(geo)
        except Exception as exc:
            errors.append(f"google trends {geo}: {exc}"[:200])
            continue
        for t in trends:
            if t["traffic"] < 1000:
                continue
            try:
                title = wiki.search(t["query"])
            except Exception:
                continue
            if not title:
                continue
            h = hits.setdefault(title, {"views": 0, "traffic": 0, "via": []})
            h["traffic"] += t["traffic"]
            h["via"].append(f"google-trends-{geo}:{t['query']}")
            h.setdefault("geos", set()).add(geo)
    try:
        lead, news_errors = news.signals()
        errors += news_errors
    except Exception as exc:
        lead = {}
        errors.append(f"google news: {exc}"[:200])
    for title, n in lead.items():
        h = hits.setdefault(title, {"views": 0, "traffic": 0, "via": []})
        h["news"], h["news_at"], h["headlines"] = n["news"], n["news_at"], n["headlines"][:5]
        h.setdefault("geos", set()).update(n["geos"])
        h["via"] += [f"google-news:{t}" for t in n["headlines"][:3]]
    return hits, errors


def region(ent: dict, geos: set[str]) -> str:
    """'india' for stories about India (Wikidata country or citizenship, or only Indian signals), else 'world'."""
    countries = {c["value"] for pid in ("P17", "P27", "P495") for c in wiki.claims(ent, pid)}
    return "india" if INDIA in countries or (geos and geos <= {"IN"}) else "world"


def _event_date(ent: dict) -> date | None:
    for pid in ("P585", "P580"):
        for c in wiki.claims(ent, pid):
            d = wiki.wd_time(c["value"])
            if d:
                return d
    return None


def _year(value: str) -> int | None:
    m = re.match(r"\+(\d{4})", value or "")
    return int(m.group(1)) if m else None


def is_current(ent: dict, cat: str, today: date) -> bool:
    """An ongoing story is current unless Wikidata says it ended, or it began more than ONGOING_MAX_YEARS ago.
    A movement or war must have a start date at all, so ideologies and long-standing causes stay out."""
    for c in wiki.claims(ent, "P582") + wiki.claims(ent, "P576"):
        end, year = wiki.wd_time(c["value"]), _year(c["value"])
        if (end and end < today) or (year and year < today.year):
            return False
    started = [y for pid in ("P580", "P571", "P585") for c in wiki.claims(ent, pid) if (y := _year(c["value"]))]
    if not started:
        return cat == "protest"
    return today.year - max(started) <= ONGOING_MAX_YEARS


def story_id(qid: str, cat: str, when: date) -> str:
    """One id per story; an ongoing story may come back once per ISO week while newsrooms keep leading with it."""
    if cat not in ONGOING:
        return f"wk-{qid}"
    year, week, _ = when.isocalendar()
    return f"wk-{qid}-{year}w{week:02d}"


def candidate(title: str) -> dict:
    """One article as a candidate, without the trend and freshness filters (for making a chosen story by hand)."""
    page = wiki.page_info([title]).get(title)
    if not page or not page.get("qid"):
        raise ValueError(f"no Wikidata item for {title!r}")
    cats = wiki.classify([page["qid"]])[page["qid"]]
    ent = wiki.entities([page["qid"]])[page["qid"]]
    base = {"qid": page["qid"], "title": page["title"], "id": f"wk-{page['qid']}", "fame": 0, "via": ["manual"],
            "region": region(ent, set())}
    if "human" in cats:
        return base | {"kind": "death", "category": "death"}
    cat = next((c for c in ORDER if c in cats), None)
    if not cat:
        raise ValueError(f"{title!r} is neither an incident nor a person ({sorted(cats)})")
    today = datetime.now(timezone.utc).date()
    return base | {"id": story_id(page["qid"], cat, today), "kind": "incident", "category": cat}


ORDER = ("aviation", "attack", "explosion", "rail", "maritime", "strike", "earthquake", "cyclone", "volcano", "flood",
         "wildfire", "landslide", "tsunami", "conflict", "disaster", "accident", "protest", "movement")


def radar(today: date | None = None) -> dict:
    """Trending candidates, ranked by fame. Written to state/trends.json by the caller."""
    today = today or datetime.now(timezone.utc).date()
    hits, errors = _signals()
    try:
        info = wiki.page_info(list(hits))
        qids = sorted({i["qid"] for i in info.values() if i.get("qid")})
        kinds = wiki.classify(qids) if qids else {}
        relevant = [q for q in qids if kinds.get(q)]
        ents = wiki.entities(relevant) if relevant else {}
    except Exception as exc:
        errors.append(f"wikidata: {exc}"[:200])
        return {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "candidates": [], "errors": errors,
                "scanned": len(hits)}
    out, seen = [], set()
    for title, h in hits.items():
        page = info.get(title)
        if not page or not page.get("qid") or page["qid"] in seen:
            continue
        qid, cats = page["qid"], kinds.get(page["qid"], set())
        ent = ents.get(qid)
        if not cats or not ent:
            continue
        seen.add(qid)
        fame = h["views"] + h["traffic"] + h.get("news", 0)
        base = {"qid": qid, "title": page["title"], "fame": fame, "views": h["views"], "traffic": h["traffic"],
                "news": h.get("news", 0), "news_at": h.get("news_at"), "headlines": h.get("headlines", []),
                "region": region(ent, h.get("geos", set())), "via": h["via"]}
        if "human" in cats:
            died = next((wiki.wd_time(c["value"]) for c in wiki.claims(ent, "P570")), None)
            if not died or not 0 <= (today - died).days <= DEATH_MAX_DAYS:
                continue
            if wiki.claims(ent, "P1399"):
                continue  # people convicted of crimes are not eulogised on this channel
            if any(c["value"] == SUICIDE for c in wiki.claims(ent, "P1196")):
                continue
            out.append(base | {"id": f"wk-{qid}", "kind": "death", "category": "death", "date": died.isoformat()})
            continue
        cat = next((c for c in ORDER if c in cats), None)
        if not cat:
            continue
        when = _event_date(ent)
        if cat in ONGOING:
            if len(h.get("headlines", [])) < ONGOING_MIN_HEADLINES or not is_current(ent, cat, today):
                continue  # only news while several lead stories are about it, and while it is still going on
            when = date.fromisoformat(h["news_at"][:10])
        if not when:
            made = wiki.created(page["title"])
            when = made.date() if made else None
        if not when or not 0 <= (today - when).days <= INCIDENT_MAX_DAYS:
            continue
        coords = (page["lat"], page["lon"]) if page.get("lat") is not None else wiki.coords(ent)
        out.append(base | {"id": story_id(qid, cat, when), "kind": "incident", "category": cat, "date": when.isoformat(),
                           "coords": coords,
                           "has_coords": bool(coords or wiki.claims(ent, "P276") or wiki.claims(ent, "P1427"))})
    out.sort(key=lambda c: -c["fame"])
    return {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "candidates": out, "errors": errors,
            "scanned": len(hits)}
