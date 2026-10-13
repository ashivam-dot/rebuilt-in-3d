"""Breaking-news signal: Google News top stories for India, the US and the world, refreshed every few minutes.

Wikipedia's most-read list is a day behind and Google Trends shows searches, not stories. The front pages of
Google News show what newsrooms are leading with right now. Each headline is matched to the Wikipedia article
about it; an article's heat is how many lead stories and outlets point at it, and how recent the newest one is.
Trusted outlets' own feeds (studio/outlets.py) count too, once per independent owner.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from . import net, wiki

FEEDS = {
    "IN": "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en",
    "IN-nation": "https://news.google.com/rss/headlines/section/topic/NATION?hl=en-IN&gl=IN&ceid=IN:en",
    "US": "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
    "world": "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en",
    "GB": "https://news.google.com/rss?hl=en-GB&gl=GB&ceid=GB:en",
}
MAX_AGE_H = 36
# One lead story counts like this much Google Trends traffic on the fame scale, times the outlets covering it.
HEADLINE_FAME = 25000
NOISE = re.compile(r"^(BREAKING|LIVE|LIVE UPDATES|WATCH|EXCLUSIVE|EXPLAINED)\s*[|:\-]\s*", re.I)
EDITED_WITHIN_H = 72
# Title words too common to show that a headline is about this article.
GENERIC = set("""protest protests war party election elections attack attacks crash fire flood floods earthquake
death killing killings shooting bombing riots strike strikes movement march crisis disaster accident explosion
collapse case india indian united states world national government state city south north east west""".split())


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z'’\-]+", text.lower().replace("’", "'")) if len(w) >= 4}


def match(headline: str, now: datetime | None = None) -> str | None:
    """The Wikipedia article a headline is about: one of the top search hits, edited in the last EDITED_WITHIN_H
    hours, whose title shares a distinctive word with the headline. None when nothing fits."""
    now = now or datetime.now(timezone.utc)
    d = net.get_json(wiki.API, params={"action": "query", "list": "search", "srsearch": headline, "srlimit": 5,
                                       "srprop": "timestamp", "format": "json", "formatversion": 2})
    words = _tokens(headline)
    for hit in d["query"]["search"]:
        edited = datetime.fromisoformat(hit["timestamp"].replace("Z", "+00:00"))
        if (now - edited).total_seconds() > EDITED_WITHIN_H * 3600:
            continue
        if (_tokens(hit["title"]) - GENERIC) & words:
            return hit["title"]
    return None


MONTH_WORDS = set("january february march april may june july august september october november december".split())
TITLE_STOP = set("the and for from with into over after near of on in at to by".split())


def _stem(word: str) -> str:
    word = re.sub(r"['’]s$", "", word.lower())
    return word[:-1] if len(word) > 4 and word.endswith("s") and not word.endswith("ss") else word


def _seq(text: str) -> list[str]:
    return [_stem(w) for w in re.findall(r"[A-Za-z][A-Za-z'’\-]*", text)]


def _has_run(seq: list[str], run: list[str]) -> bool:
    return bool(run) and any(seq[i:i + len(run)] == run for i in range(len(seq) - len(run) + 1))


def pool_item(title: str, person: bool = False, qid: str | None = None) -> dict:
    """A story article headlines may be matched to by their words: its distinctive title words (stemmed) and which of
    them are names ('2026 Aubagne school shooting' -> {aubagne, school}, names {aubagne}); a person's whole name."""
    plain = re.sub(r"\s*\([^)]*\)", "", title)
    raw = re.findall(r"[A-Za-z][A-Za-z'’\-]*", plain)
    if person:
        words = [w for w in raw if len(w) >= 2]
    else:
        words = [w for w in raw if len(w) >= 3 and w.lower() not in GENERIC | MONTH_WORDS | TITLE_STOP]
    return {"title": title, "person": person, "qid": qid, "keys": sorted({_stem(w) for w in words}),
            "names": sorted({_stem(w) for w in words if w[0].isupper()}),
            "run": [_stem(w) for w in words] if person else []}


def reverse(headline: str, pool: list[dict]) -> str | None:
    """The pool article a headline names, or None. Wikipedia's search ranks long-standing articles first, so a
    headline about a brand-new event rarely finds that event's article; the pool (fresh event articles, people who
    just died) is matched by words instead. A headline must name a person's whole name in order, or an event's place
    or other name plus one more of its title words. A headline two different items fit matches nothing."""
    seq, best = _seq(headline), set()
    words = set(seq)
    for item in pool:
        keys = set(item["keys"])
        if item["person"]:
            ok = len(keys) >= 2 or (len(keys) == 1 and len(next(iter(keys))) >= 5)
            hit = ok and _has_run(seq, item.get("run") or [])
        else:
            hit = bool(set(item["names"]) & words) and len(keys & words) >= min(2, len(keys))
        if hit:
            best.add(item["title"])
    return best.pop() if len(best) == 1 else None


def headlines(feed: str, now: datetime | None = None) -> list[dict]:
    """[{title, outlet, outlets, at, feed}] for lead stories younger than MAX_AGE_H."""
    now = now or datetime.now(timezone.utc)
    root = ET.fromstring(net.get(FEEDS[feed], tries=2))
    out = []
    for item in root.iter("item"):
        raw = item.findtext("title") or ""
        title, _, outlet = raw.rpartition(" - ")
        if not title:
            title, outlet = raw, ""
        title = NOISE.sub("", title).strip()
        try:
            at = parsedate_to_datetime(item.findtext("pubDate") or "")
        except (TypeError, ValueError):
            continue
        if at is None:
            continue
        at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
        at = at.astimezone(timezone.utc)
        if (now - at).total_seconds() > MAX_AGE_H * 3600:
            continue
        outlets = max(1, (item.findtext("description") or "").count("<li>"))
        out.append({"title": title, "outlet": outlet.strip(), "outlets": outlets, "at": at.isoformat(), "feed": feed})
    return out


OUTLET_MAX_OWNERS = 6
# Trusted outlets' items looked up on Wikipedia's search a run (newest first); the rest are matched to the pool only.
OUTLET_SEARCHES = 160


def _from_outlet(item: dict) -> dict:
    return {"title": item["title"], "outlet": item["outlet"], "outlets": 1, "at": item["at"], "feed": item["feed"],
            "geo": item["geo"], "owner": item["owner"], "src": item}


def signals(now: datetime | None = None, pool: list[dict] | None = None,
            outlet_items: list[dict] | None = None) -> tuple[dict[str, dict], list[str]]:
    """Wikipedia title -> {news, news_at, headlines, geos, owners, reports}; plus errors from feeds that failed. A
    headline whose search finds no pool article is matched against pool (see reverse).

    outlet_items (studio/outlets.py, English feeds) join the Google News lead stories: each independent owner covering
    an article adds one HEADLINE_FAME, and the items are kept as the story's reports. Each outlet item matched to an
    article is marked with it ("matched"); the newest OUTLET_SEARCHES are looked up on Wikipedia's search, the rest
    only in pool."""
    hits: dict[str, dict] = {}
    errors = []
    items = []
    for feed in FEEDS:
        try:
            items += headlines(feed, now)
        except Exception as exc:
            errors.append(f"google news {feed}: {exc}"[:200])
    searchable = len(items) + OUTLET_SEARCHES
    items += [_from_outlet(i) for i in outlet_items or []]

    def safe_match(numbered):
        n, h = numbered
        if n >= searchable:
            return None
        try:
            return match(h["title"], now)
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=6) as workers:
        titles = list(workers.map(safe_match, enumerate(items)))
    pooled = {p["title"] for p in pool or []}
    for h, title in zip(items, titles):
        if pool and title not in pooled:
            # A story article the headline names beats whatever older article the search ranked first.
            title = reverse(h["title"], pool) or title
        if not title:
            continue
        row = hits.setdefault(title, {"news": 0, "news_at": h["at"], "headlines": [], "geos": set(), "owners": [],
                                      "reports": []})
        if "src" in h:
            h["src"]["matched"] = title
            row["reports"].append(h["src"])
            if h["owner"] in row["owners"]:
                continue  # sister brands and a second headline from one newsroom count once
            row["owners"].append(h["owner"])
            if len(row["owners"]) <= OUTLET_MAX_OWNERS:
                row["news"] += HEADLINE_FAME
        elif h["title"] in row["headlines"]:
            continue
        else:
            row["news"] += HEADLINE_FAME * min(h["outlets"], 6)
        row["news_at"] = max(row["news_at"], h["at"])
        if h["title"] not in row["headlines"]:
            row["headlines"].append(h["title"])
        # A world section is not a country's signal (it must not make a story an India story).
        geo = h.get("geo") if "src" in h else (
            h.get("geo") or ("world" if h["feed"] == "world" else h["feed"].split("-")[0]))
        if geo:
            row["geos"].add(geo)
    return hits, errors
