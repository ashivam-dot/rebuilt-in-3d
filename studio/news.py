"""Breaking-news signal: Google News top stories for India, the US and the world, refreshed every few minutes.

Wikipedia's most-read list is a day behind and Google Trends shows searches, not stories. The front pages of
Google News show what newsrooms are leading with right now. Each headline is matched to the Wikipedia article
about it; an article's heat is how many lead stories and outlets point at it, and how recent the newest one is.
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


def headlines(feed: str, now: datetime | None = None) -> list[dict]:
    """[{title, outlet, outlets, at, feed}] for lead stories younger than MAX_AGE_H."""
    now = now or datetime.now(timezone.utc)
    root = ET.fromstring(net.get(FEEDS[feed], tries=2))
    out = []
    for item in root.iter("item"):
        raw = item.findtext("title") or ""
        title, _, outlet = raw.rpartition(" - ")
        title = NOISE.sub("", title or raw).strip()
        try:
            at = parsedate_to_datetime(item.findtext("pubDate") or "")
        except (TypeError, ValueError):
            continue
        if (now - at).total_seconds() > MAX_AGE_H * 3600:
            continue
        outlets = max(1, (item.findtext("description") or "").count("<li>"))
        out.append({"title": title, "outlet": outlet.strip(), "outlets": outlets, "at": at.isoformat(), "feed": feed})
    return out


def signals(now: datetime | None = None) -> tuple[dict[str, dict], list[str]]:
    """Wikipedia title -> {news, news_at, headlines, geos}; plus errors from feeds that failed."""
    hits: dict[str, dict] = {}
    errors = []
    items = []
    for feed in FEEDS:
        try:
            items += headlines(feed, now)
        except Exception as exc:
            errors.append(f"google news {feed}: {exc}"[:200])

    def safe_match(h):
        try:
            return match(h["title"], now)
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        titles = list(pool.map(safe_match, items))
    for h, title in zip(items, titles):
        if not title:
            continue
        row = hits.setdefault(title, {"news": 0, "news_at": h["at"], "headlines": [], "geos": set()})
        if h["title"] in row["headlines"]:
            continue
        row["news"] += HEADLINE_FAME * min(h["outlets"], 6)
        row["news_at"] = max(row["news_at"], h["at"])
        row["headlines"].append(h["title"])
        row["geos"].add(h["feed"].split("-")[0])
    return hits, errors
