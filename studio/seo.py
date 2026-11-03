"""Search phrases viewers type, from YouTube's own autocomplete (the free suggest endpoint every keyword tool uses).

Only tags that the video itself backs are kept: each suggestion must name the subject and add words the title, script
or a plain news word already says ("walter koenig tribute", "cyclone murasu landfall"), never "net worth" or "wife".
A failed or slow lookup returns nothing; publishing never waits on it."""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

ENDPOINT = "https://suggestqueries.google.com/complete/search"
TIMEOUT_S = 4
MAX_TAGS = 4
NEWS_WORDS = {"news", "latest", "update", "updates", "today", "tribute", "death", "dies", "died", "obituary"}


def fetch(query: str, hl: str = "en", gl: str = "us") -> list[str]:
    url = ENDPOINT + "?" + urllib.parse.urlencode({"client": "firefox", "ds": "yt", "q": query, "hl": hl, "gl": gl})
    try:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
                                     timeout=TIMEOUT_S).read().decode("utf-8", "replace")
        found = json.loads(raw)[1]
    except Exception:  # noqa: BLE001 - an optional signal; the upload goes on without it
        return []
    return [s for s in found if isinstance(s, str)]


def words(text: str) -> set[str]:
    return set(re.findall(r"[\w\u0900-\u097F]+", (text or "").casefold()))


def suggested(subject: str, text: str, hl: str = "en", gl: str = "us", extra: set[str] = frozenset()) -> list[str]:
    """Up to MAX_TAGS autocomplete phrases for `subject` whose added words all appear in `text` or the news words."""
    subject = " ".join(subject.split())
    if not subject or len(subject.split()) > 5:
        return []
    allowed = words(text) | NEWS_WORDS | set(extra)
    name = words(subject)
    out = []
    for s in fetch(subject.casefold(), hl, gl):
        added = words(s) - name
        if subject.casefold() in s.casefold() and added and added <= allowed and not re.search(r"\d{4}", s):
            out.append(s.casefold())
        if len(out) == MAX_TAGS:
            break
    return out
