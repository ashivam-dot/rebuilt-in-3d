"""Trend radar: which famous, fresh stories the world is looking at right now.

Fame comes from three public signals: Google News lead stories in India, the US and the world (minutes old),
Google Trends trending searches in the US, India and the UK (hourly) and English Wikipedia's most-read articles
(daily). Each hit is resolved to a Wikipedia article and its Wikidata item, then classified. Three shapes of story
pass: a recent incident, a protest or public movement that newsrooms are leading with, or the recent death of a
famous person. Sport, celebrity gossip, party politics and crime trials are ignored by design.

Trusted outlets' English feeds (studio/outlets.py) add their headlines, once per independent owner, and the articles
that name a story are kept as its reports. Stories at least three owners report that Wikipedia has no article for yet
(nw- ids) are found and logged, and offered only when STUDIO_NEW_STORIES is true.
"""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

from . import ledger, net, news, outlets, wiki

# Stories told only from trusted outlets' reporting, before Wikipedia has an article (nw- ids): off unless the run's
# environment sets STUDIO_NEW_STORIES=true.
NEW_STORIES = os.environ.get("STUDIO_NEW_STORIES", "").lower() == "true"
OUTLET_LANGS = ("en",)
READ: list[dict] = []  # the trusted outlets' items the last _signals read, each marked with the article it matched

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
# Google Trends' RSS now lists about ten searches a country with traffic of "100+" to "5000+": any listed search is
# trending now, so none is ignored for its size (a 1000 floor once left every Trends signal at zero).
TRENDS_MIN_TRAFFIC = 100
TOP_N = 400
# Below the top TOP_N, Wikipedia's most-read list (1000 deep) still counts for people who just died and fresh events.
TOP_DEEP = 1000
NEW_ARTICLE_H = 48
# A GDACS Orange or Red alert (EU JRC / UN OCHA) for a disaster counts like a Current events listing, or more.
GDACS_FAME = {"Orange": 50000, "Red": 150000}
GDACS_MAX_DAYS = 4
# A story Wikipedia's editors list on today's or yesterday's Current events page counts like two lead headlines.
PORTAL_FAME = 50000
PORTAL_LEADS = 2
INCIDENT_MAX_DAYS = 30
DEATH_MAX_DAYS = 10
# The Wikidata query service timed out on 7 of the last 80 runs (state branch health.json, 2026-10-21), each time
# blinding the death lane. The last good list of recent deaths is kept in state and stands in for this long.
DEATHS_CACHE = "recent_deaths"
DEATHS_CACHE_H = 3
SUICIDE = "Q10737"


def google_trends(geo: str) -> list[dict]:
    root = ET.fromstring(net.get(TRENDS_RSS.format(geo=geo), tries=2))
    out = []
    for item in root.iter("item"):
        traffic = re.sub(r"[^\d]", "", item.findtext(f"{HT}approx_traffic") or "0") or "0"
        news = [n.findtext(f"{HT}news_item_title") or "" for n in item.iter(f"{HT}news_item")]
        out.append({"query": item.findtext("title") or "", "traffic": int(traffic), "geo": geo, "news": news[:3]})
    return out


def recent_deaths(since: date, errors: list[str], now: datetime | None = None) -> list[dict]:
    """People Wikidata says died on or after since (wiki.recent_deaths, which retries with backoff). When the query
    service fails, the last good list stands in for up to DEATHS_CACHE_H hours, and the error says so."""
    now = now or datetime.now(timezone.utc)
    try:
        rows = wiki.recent_deaths(since)
    except Exception as exc:
        cached = ledger.load(DEATHS_CACHE, {})
        age = (now - datetime.fromisoformat(cached["at"])).total_seconds() / 3600 if cached.get("at") else None
        if age is not None and 0 <= age <= DEATHS_CACHE_H and cached.get("rows"):
            errors.append(f"wikidata recent deaths: {exc}"[:160] + f" (used the list from {age:.1f} h ago, "
                          f"{len(cached['rows'])} people)")
            return cached["rows"]
        errors.append(f"wikidata recent deaths: {exc}"[:200])
        return []
    if rows:
        ledger.save(DEATHS_CACHE, {"at": now.isoformat(timespec="seconds"), "since": since.isoformat(), "rows": rows})
    return rows


def story_pool(today: date, errors: list[str]) -> list[dict]:
    """Articles headlines and searches may be matched to by their words (news.reverse): people who died in the last
    DEATH_MAX_DAYS days and event articles created in the last NEW_ARTICLE_H hours."""
    pool = [news.pool_item(d["title"], person=True, qid=d["qid"])
            for d in recent_deaths(today - timedelta(days=DEATH_MAX_DAYS), errors)]
    try:
        pool += [news.pool_item(t) for t in wiki.new_articles(NEW_ARTICLE_H) if title_kind(t, today)]
    except Exception as exc:
        errors.append(f"wikipedia new articles: {exc}"[:200])
    return pool


def _add_events(pool: list[dict], titles, today: date) -> None:
    """Add the event-shaped titles among titles to the pool."""
    known = {p["title"] for p in pool}
    pool += [news.pool_item(t) for t in dict.fromkeys(titles) if t not in known and title_kind(t, today)]


def gdacs_hits(today: date) -> list[tuple[str, dict]]:
    """(English article, alert) for each recent GDACS Orange or Red alert whose disaster has an article."""
    from . import gdacs

    out = []
    for a in gdacs.alerts():
        if not a.get("published") or (today - date.fromisoformat(a["published"][:10])).days > GDACS_MAX_DAYS:
            continue
        name, cat = gdacs.subject(a)
        if not name:
            continue
        hits = net.get_json(wiki.API, params={"action": "query", "list": "search", "srlimit": 5, "format": "json",
                                              "formatversion": 2, "srsearch": f"{today.year} {name} {gdacs.WORD[cat]}"})
        title = next((h["title"] for h in hits["query"]["search"] if title_kind(h["title"], today) == cat
                      and name.lower() in h["title"].lower()), None)
        if title:
            out.append((title, a))
    return out


def _signals() -> tuple[dict[str, dict], list[str]]:
    """title -> {views, traffic, via}; plus any errors (one failed source must not stop the radar)."""
    hits: dict[str, dict] = {}
    errors = []
    now = datetime.now(timezone.utc)
    pool = story_pool(now.date(), errors)
    deep = {p["title"] for p in pool}
    try:
        day, top = wiki.top_articles()
        for rank, (title, views) in enumerate(top[:TOP_DEEP]):
            if rank >= TOP_N and title not in deep and not title_kind(title, now.date()):
                continue
            hits.setdefault(title, {"views": 0, "traffic": 0, "via": []})
            hits[title]["views"] = views
            hits[title]["via"].append(f"wikipedia-top-{day.isoformat()}")
    except Exception as exc:
        errors.append(f"wikipedia top: {exc}"[:200])
    listed = {}
    for back in (1, 0):
        d = now.date() - timedelta(days=back)
        try:
            listed[d] = wiki.current_events(d)
        except Exception as exc:
            errors.append(f"wikipedia current events {d}: {exc}"[:200])
    _add_events(pool, list(hits) + [t for rows in listed.values() for t, _ in rows], now.date())
    for geo in GEOS:
        try:
            trends = google_trends(geo)
        except Exception as exc:
            errors.append(f"google trends {geo}: {exc}"[:200])
            continue
        for t in trends:
            if t["traffic"] < TRENDS_MIN_TRAFFIC:
                continue
            # A search is matched to the story its own news items name before Wikipedia's search is asked.
            title = next(filter(None, (news.reverse(s, pool) for s in [t["query"]] + t["news"])), None)
            try:
                title = title or (None if re.search(r"[^\x00-\u024f]", t["query"]) else wiki.search(t["query"]))
            except Exception:
                continue
            if not title:
                continue
            h = hits.setdefault(title, {"views": 0, "traffic": 0, "via": []})
            h["traffic"] += t["traffic"]
            h["via"].append(f"google-trends-{geo}:{t['query']}")
            h.setdefault("geos", set()).add(geo)
    try:
        for title, a in gdacs_hits(now.date()):
            h = hits.setdefault(title, {"views": 0, "traffic": 0, "via": []})
            h["gdacs"] = max(h.get("gdacs", 0), GDACS_FAME.get(a["level"], 0))
            h["gdacs_at"] = max(h.get("gdacs_at", a["published"]), a["published"])
            h["via"].append(f"{a['id']}:{a['level']}")
            if a.get("country") == "India":
                h.setdefault("geos", set()).add("IN")
    except Exception as exc:
        errors.append(f"gdacs: {exc}"[:200])
    for day, rows in listed.items():
        live_at = min(now, datetime.combine(day + timedelta(days=1), datetime.min.time(), timezone.utc)).isoformat()
        for title, india in rows:
            h = hits.setdefault(title, {"views": 0, "traffic": 0, "via": []})
            h["portal"] = h.get("portal", 0) + PORTAL_FAME
            h["portal_at"] = max(h.get("portal_at", live_at), live_at)
            h["via"].append(f"wikipedia-current-events-{day}")
            if india:
                h.setdefault("geos", set()).add("IN")
    try:
        outlet_items, outlet_errors = outlets.recent(langs=OUTLET_LANGS)
        errors += outlet_errors
    except Exception as exc:
        outlet_items = []
        errors.append(f"outlets: {exc}"[:200])
    READ.extend(outlet_items)
    try:
        lead, news_errors = news.signals(pool=pool, outlet_items=outlet_items)
        errors += news_errors
    except Exception as exc:
        lead = {}
        errors.append(f"google news: {exc}"[:200])
    for title, n in lead.items():
        h = hits.setdefault(title, {"views": 0, "traffic": 0, "via": []})
        h["news"], h["news_at"], h["headlines"] = n["news"], n["news_at"], n["headlines"][:5]
        h.setdefault("geos", set()).update(n["geos"])
        h["via"] += [f"google-news:{t}" for t in n["headlines"][:3]]
        if n.get("owners"):
            h["owners"], h["reports"] = n["owners"], n["reports"]
            h["via"] += [f"outlet:{o}" for o in n["owners"]]
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
    today = datetime.now(timezone.utc).date()
    if page and not page.get("qid") and (cat := title_kind(page["title"], today)):
        # A brand-new event article Wikidata has no item for yet, as the radar tells it (a wp- story).
        return {"qid": None, "title": page["title"], "id": article_id(page["title"]), "fame": 0, "via": ["manual"],
                "region": region({}, set()), "kind": "incident", "category": cat}
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
    return base | {"id": story_id(page["qid"], cat, today), "kind": "incident", "category": cat}


ORDER = ("aviation", "attack", "explosion", "rail", "maritime", "strike", "earthquake", "cyclone", "volcano", "flood",
         "wildfire", "landslide", "tsunami", "conflict", "disaster", "accident", "protest", "movement")

# A brand-new event article often has no Wikidata item (or no instance-of) for its first day, exactly while the story
# is hottest. Such an article still qualifies when its English title names the current year and one of these shapes,
# the way Wikipedia titles events ("2026 Erie shooting", "2026 anti-CEC protests"). Riots, trials and elections stay out.
TITLE_KINDS = (
    (r"\bflight \d+\b|\b(air|plane|aircraft|helicopter|jet) ?crash", "aviation"),
    (r"\b(shootings?|stabbings?|bombings?|massacre|attacks?|airstrikes?|missile strikes?|drone strikes?)\b", "attack"),
    (r"\b(explosions?|blasts?)\b", "explosion"),
    (r"\bderailment\b|\btrain (crash|collision|accident)\b", "rail"),
    (r"\b(ferry|boat|ship) (sinking|capsizing|disaster|accident)\b|\bsinking of\b", "maritime"),
    (r"\bearthquakes?\b", "earthquake"),
    (r"\b(cyclone|hurricane|typhoon|tropical storm)\b", "cyclone"),
    (r"\beruptions?\b", "volcano"),
    (r"\b(floods?|flooding|cloudbursts?)\b", "flood"),
    (r"\b(wild|bush|forest) ?fires?\b", "wildfire"),
    (r"\b(landslides?|mudslides?|avalanches?)\b", "landslide"),
    (r"\b(stampede|crowd crush|(building|bridge|dam) collapse|fire)\b", "disaster"),
    (r"\b(bus|road|boat) (crash|accident)\b", "accident"),
    (r"\b(protests?|demonstrations?)\b", "protest"),
)
TITLE_SKIP = (r"\b(riots?|trials?|elections?|by-?elections?|referendums?|seasons?|tournaments?|championships?|cups?|"
              r"leagues?|films?|series|games|olympics)\b")


def title_kind(title: str, today: date) -> str | None:
    """The category a fresh event article's title names, or None (see TITLE_KINDS)."""
    if not re.search(rf"\b({today.year}|{today.year - 1})\b", title) or re.search(TITLE_SKIP, title, re.I):
        return None
    return next((cat for pattern, cat in TITLE_KINDS if re.search(pattern, title, re.I)), None)


def article_id(title: str) -> str:
    """The id of a story told from an article Wikidata did not know yet; kept so it never comes back as wk-<QID>."""
    return "wp-" + re.sub(r"[^\w-]+", "_", title).strip("_")


def radar(today: date | None = None) -> dict:
    """Trending candidates, ranked by fame. Written to state/trends.json by the caller."""
    today = today or datetime.now(timezone.utc).date()
    READ.clear()
    hits, errors = _signals()
    read = list(READ)
    try:
        info = wiki.page_info(list(hits))
        qids = sorted({i["qid"] for i in info.values() if i.get("qid")})
        kinds = wiki.classify(qids) if qids else {}
        for page in info.values():
            if page.get("qid") and not kinds.get(page["qid"]) and (cat := title_kind(page["title"], today)):
                kinds[page["qid"]] = {cat, "by-title"}
        relevant = [q for q in qids if kinds.get(q)]
        ents = wiki.entities(relevant) if relevant else {}
    except Exception as exc:
        errors.append(f"wikidata: {exc}"[:200])
        return {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "candidates": [], "errors": errors,
                "scanned": len(hits), "emerging": [], "outlets": outlet_stats(read, [])}
    out, seen = [], set()
    for title, h in hits.items():
        page = info.get(title)
        if not page:
            continue
        if not page.get("qid"):
            cat = title_kind(page["title"], today)
            if not cat or page["title"] in seen or not page.get("unlinked"):
                continue
            qid, cats, ent = None, {cat, "by-title"}, {}
            seen.add(page["title"])
        else:
            qid, cats = page["qid"], kinds.get(page["qid"], set())
            ent = ents.get(qid)
            if qid in seen or not cats or not ent:
                continue
            seen.add(qid)
        fame = h["views"] + h["traffic"] + h.get("news", 0) + h.get("portal", 0) + h.get("gdacs", 0)
        news_at = max(filter(None, (h.get("news_at"), h.get("portal_at"), h.get("gdacs_at"))), default=None)
        base = {"qid": qid, "title": page["title"], "fame": fame, "views": h["views"], "traffic": h["traffic"],
                "news": h.get("news", 0), "news_at": news_at, "headlines": h.get("headlines", []),
                "region": region(ent, h.get("geos", set())), "via": h["via"],
                "owners": h.get("owners", []), "reports": [outlets.compact(r) for r in h.get("reports", [])][:8]}
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
            leads = len(h.get("headlines", [])) + (PORTAL_LEADS if h.get("portal") else 0)
            if leads < ONGOING_MIN_HEADLINES or not is_current(ent, cat, today):
                continue  # only news while several lead stories are about it, and while it is still going on
            when = date.fromisoformat(news_at[:10])
        if not when:
            made = wiki.created(page["title"])
            when = made.date() if made else None
        if not when or not 0 <= (today - when).days <= INCIDENT_MAX_DAYS:
            continue
        coords = (page["lat"], page["lon"]) if page.get("lat") is not None else wiki.coords(ent)
        sid = story_id(qid, cat, when) if qid else article_id(page["title"])
        out.append(base | {"id": sid, "kind": "incident", "category": cat, "date": when.isoformat(),
                           "coords": coords,
                           "has_coords": bool(coords or wiki.claims(ent, "P276") or wiki.claims(ent, "P1427"))})
    try:
        # Only an article the desk could tell the story from takes it over: a strike's headlines also name the armed
        # group, the country and the years-old war ("Houthis", "Yemen", "Houthi–Saudi conflict"), which never can.
        emerging = outlets.stories(read, datetime.now(timezone.utc), known=[c["title"] for c in out],
                                   young=young_articles(out))
    except Exception as exc:
        emerging = []
        errors.append(f"outlet stories: {type(exc).__name__}: {exc}"[:200])
    if NEW_STORIES:
        out += emerging
    out.sort(key=lambda c: -c["fame"])
    return {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "candidates": out, "errors": errors,
            "scanned": len(hits), "emerging": emerging, "outlets": outlet_stats(read, out)}


def young_articles(cands: list[dict]) -> list[str]:
    """Incident articles too new to tell from (stories.MIN_ARTICLE_AGE) that enough independent outlets already
    report: a big story is told from that reporting at once instead of waiting hours for the article to settle."""
    from .stories import MIN_ARTICLE_AGE

    out, now = [], datetime.now(timezone.utc)
    for c in cands:
        if c["kind"] != "incident" or len(c.get("owners") or []) < outlets.NEW_OWNERS:
            continue
        try:
            made = wiki.created(c["title"])
        except Exception:  # the story then simply waits for its article, as before
            continue
        if made and now - made < MIN_ARTICLE_AGE:
            out.append(c["title"])
    return out


def outlet_stats(read: list[dict], cands: list[dict]) -> dict:
    """What the trusted outlets added this run (recorded in candidates.json and the run's health)."""
    return {"headlines": len(read), "feeds": len({i["feed"] for i in read}), "owners": len(outlets.owners(read)),
            "matched": sum(1 for i in read if i.get("matched")),
            "corroborated": sum(1 for c in cands if len(outlets.owners(c.get("reports") or [])) >= 2)}
