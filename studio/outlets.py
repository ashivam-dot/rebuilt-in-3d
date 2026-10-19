"""Trusted outlets beyond Wikipedia: their latest headlines, and the text of their articles.

Owner, 2026-10-13: "don't rely on wikipedia only search for other trusted sources as well". The allowlist below was
checked on a GitHub runner (feed readable, article text extracted). Each feed names its `owner`: sister brands
(Hindustan Times and Live Hindustan, BBC World and BBC Hindi, PIB in English and Hindi) belong to one owner and count
as ONE source, so "two independent outlets" means two different owners. Outlet photos are copyrighted and are never
used; only their words are read, as corroboration, and every outlet used is named in the description.

`recent()` reads every feed in parallel (a failed feed is reported, never fatal). `text()` extracts an article's text
with trafilatura, cached per run, at most MAX_TEXTS fetches a run. `stories()` finds stories Wikipedia has no article
for yet (`nw-` ids, see CHANNEL.md).
"""
from __future__ import annotations

import html
import re
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from . import net

GROUPS = ("official", "public broadcaster", "international", "national", "Indian national", "Hindi")
# A story told before Wikipedia has an article needs one of these among its owners.
STRONG = ("official", "public broadcaster", "international")
# geo: "IN" for an India section, "world" for a world one; None for a feed that mixes both (its headlines are never
# an Indian signal).
OUTLETS = [
    {"key": "pib", "name": "PIB", "name_hi": "पीआईबी", "owner": "Government of India", "group": "official",
     "lang": "en", "geo": "IN",
     "feed": "https://www.pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3&reg=3", "undated": True},
    {"key": "pib-hi", "name": "PIB", "name_hi": "पीआईबी", "owner": "Government of India", "group": "official",
     "lang": "hi", "geo": "IN",
     "feed": "https://www.pib.gov.in/RssMain.aspx?ModId=6&Lang=2&Regid=3&reg=3", "undated": True},
    {"key": "un-hi", "name": "UN News", "name_hi": "यूएन न्यूज़", "owner": "United Nations", "group": "official",
     "lang": "hi", "geo": "world", "feed": "https://news.un.org/feed/subscribe/hi/news/all/rss.xml"},
    {"key": "bbc-world", "name": "BBC", "name_hi": "बीबीसी", "owner": "BBC", "group": "public broadcaster",
     "lang": "en", "geo": "world", "feed": "https://feeds.bbci.co.uk/news/world/rss.xml"},
    {"key": "bbc-india", "name": "BBC", "name_hi": "बीबीसी", "owner": "BBC", "group": "public broadcaster",
     "lang": "en", "geo": "IN", "feed": "https://feeds.bbci.co.uk/news/world/asia/india/rss.xml"},
    {"key": "bbc-hindi", "name": "BBC Hindi", "name_hi": "बीबीसी हिंदी", "owner": "BBC", "group": "public broadcaster",
     "lang": "hi", "geo": "IN", "feed": "https://feeds.bbci.co.uk/hindi/rss.xml"},
    {"key": "dw", "name": "DW", "name_hi": "डीडब्ल्यू", "owner": "Deutsche Welle", "group": "public broadcaster",
     "lang": "en", "geo": "world", "feed": "https://rss.dw.com/rdf/rss-en-all"},
    {"key": "npr", "name": "NPR", "name_hi": "एनपीआर", "owner": "NPR", "group": "public broadcaster", "lang": "en",
     "geo": "world", "feed": "https://feeds.npr.org/1004/rss.xml"},
    {"key": "aljazeera", "name": "Al Jazeera", "name_hi": "अल जज़ीरा", "owner": "Al Jazeera Media Network",
     "group": "international", "lang": "en", "geo": "world", "feed": "https://www.aljazeera.com/xml/rss/all.xml"},
    {"key": "guardian", "name": "The Guardian", "name_hi": "द गार्डियन", "owner": "Guardian Media Group",
     "group": "international", "lang": "en", "geo": "world", "feed": "https://www.theguardian.com/world/rss"},
    {"key": "thehindu", "name": "The Hindu", "name_hi": "द हिंदू", "owner": "The Hindu Group",
     "group": "Indian national", "lang": "en", "geo": "IN",
     "feed": "https://www.thehindu.com/news/national/feeder/default.rss"},
    {"key": "ht", "name": "Hindustan Times", "name_hi": "हिंदुस्तान टाइम्स", "owner": "HT Media",
     "group": "Indian national", "lang": "en", "geo": "IN",
     "feed": "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml"},
    {"key": "toi", "name": "Times of India", "name_hi": "टाइम्स ऑफ़ इंडिया", "owner": "Bennett, Coleman & Co.",
     "group": "Indian national", "lang": "en", "geo": None,
     "feed": "https://timesofindia.indiatimes.com/rssfeedstopstories.cms"},
    {"key": "livehindustan", "name": "Live Hindustan", "name_hi": "लाइव हिन्दुस्तान", "owner": "HT Media",
     "group": "Hindi", "lang": "hi", "geo": "IN", "feed": "https://api.livehindustan.com/feeds/rss/national/rssfeed.xml"},
    {"key": "amarujala", "name": "Amar Ujala", "name_hi": "अमर उजाला", "owner": "Amar Ujala", "group": "Hindi",
     "lang": "hi", "geo": None, "feed": "https://www.amarujala.com/rss/breaking-news.xml"},
    {"key": "aajtak", "name": "AajTak", "name_hi": "आजतक", "owner": "India Today Group", "group": "Hindi",
     "lang": "hi", "geo": None, "feed": "https://www.aajtak.in/rssfeeds/?id=home"},
    {"key": "abp", "name": "ABP Live", "name_hi": "एबीपी लाइव", "owner": "ABP Group", "group": "Hindi", "lang": "hi",
     "geo": None, "feed": "https://www.abplive.com/home/feed"},
    {"key": "france24", "name": "France 24", "name_hi": "फ़्रांस 24", "owner": "France Médias Monde",
     "group": "public broadcaster", "lang": "en", "geo": "world", "feed": "https://www.france24.com/en/rss"},
    {"key": "ndtv", "name": "NDTV", "name_hi": "एनडीटीवी", "owner": "NDTV", "group": "Indian national", "lang": "en",
     "geo": None, "feed": "https://feeds.feedburner.com/ndtvnews-top-stories"},
    {"key": "ndtv-hi", "name": "NDTV India", "name_hi": "एनडीटीवी इंडिया", "owner": "NDTV", "group": "Hindi",
     "lang": "hi", "geo": None, "feed": "https://feeds.feedburner.com/ndtvkhabar-latest"},
    # World English outlets (2026-10-14; checked from the Mac: feed readable, article text extracted). Sky News, The
    # New York Times, PBS and The Japan Times give no article text, AP answers 403 and CBC timed out.
    {"key": "bbc-top", "name": "BBC", "name_hi": "बीबीसी", "owner": "BBC", "group": "public broadcaster",
     "lang": "en", "geo": "world", "feed": "https://feeds.bbci.co.uk/news/rss.xml"},
    {"key": "npr-news", "name": "NPR", "name_hi": "एनपीआर", "owner": "NPR", "group": "public broadcaster",
     "lang": "en", "geo": "world", "feed": "https://feeds.npr.org/1001/rss.xml"},
    {"key": "abc-au-world", "name": "ABC News (Australia)", "name_hi": "एबीसी न्यूज़", "owner": "ABC (Australia)",
     "group": "public broadcaster", "lang": "en", "geo": "world",
     "feed": "https://www.abc.net.au/news/feed/2942460/rss.xml"},
    {"key": "abc-au-top", "name": "ABC News (Australia)", "name_hi": "एबीसी न्यूज़", "owner": "ABC (Australia)",
     "group": "public broadcaster", "lang": "en", "geo": "world",
     "feed": "https://www.abc.net.au/news/feed/51120/rss.xml"},
    {"key": "un-en", "name": "UN News", "name_hi": "यूएन न्यूज़", "owner": "United Nations", "group": "official",
     "lang": "en", "geo": "world", "feed": "https://news.un.org/feed/subscribe/en/news/all/rss.xml"},
    {"key": "independent", "name": "The Independent", "name_hi": "द इंडिपेंडेंट", "owner": "Independent Digital News",
     "group": "international", "lang": "en", "geo": "world", "feed": "https://www.independent.co.uk/news/world/rss"},
    {"key": "euronews", "name": "Euronews", "name_hi": "यूरोन्यूज़", "owner": "Euronews", "group": "international",
     "lang": "en", "geo": "world", "feed": "https://www.euronews.com/rss?level=theme&name=news"},
    {"key": "scmp", "name": "South China Morning Post", "name_hi": "साउथ चाइना मॉर्निंग पोस्ट", "owner": "SCMP Group",
     "group": "international", "lang": "en", "geo": "world", "feed": "https://www.scmp.com/rss/91/feed"},
    {"key": "guardian-us", "name": "The Guardian", "name_hi": "द गार्डियन", "owner": "Guardian Media Group",
     "group": "international", "lang": "en", "geo": "world", "feed": "https://www.theguardian.com/us-news/rss"},
    {"key": "cbs-world", "name": "CBS News", "name_hi": "सीबीएस न्यूज़", "owner": "Paramount (CBS)", "group": "national",
     "lang": "en", "geo": "world", "feed": "https://www.cbsnews.com/latest/rss/world"},
    {"key": "cbs-us", "name": "CBS News", "name_hi": "सीबीएस न्यूज़", "owner": "Paramount (CBS)", "group": "national",
     "lang": "en", "geo": "world", "feed": "https://www.cbsnews.com/latest/rss/us"},
    {"key": "nbc-world", "name": "NBC News", "name_hi": "एनबीसी न्यूज़", "owner": "NBCUniversal", "group": "national",
     "lang": "en", "geo": "world", "feed": "https://feeds.nbcnews.com/nbcnews/public/world"},
    {"key": "nbc-news", "name": "NBC News", "name_hi": "एनबीसी न्यूज़", "owner": "NBCUniversal", "group": "national",
     "lang": "en", "geo": "world", "feed": "https://feeds.nbcnews.com/nbcnews/public/news"},
    {"key": "abc-us-intl", "name": "ABC News", "name_hi": "एबीसी न्यूज़", "owner": "Disney (ABC News)",
     "group": "national", "lang": "en", "geo": "world",
     "feed": "https://abcnews.go.com/abcnews/internationalheadlines"},
    {"key": "abc-us-top", "name": "ABC News", "name_hi": "एबीसी न्यूज़", "owner": "Disney (ABC News)",
     "group": "national", "lang": "en", "geo": "world", "feed": "https://abcnews.go.com/abcnews/topstories"},
    {"key": "fox-world", "name": "Fox News", "name_hi": "फ़ॉक्स न्यूज़", "owner": "Fox Corporation", "group": "national",
     "lang": "en", "geo": "world", "feed": "https://moxie.foxnews.com/google-publisher/world.xml"},
    {"key": "fox-latest", "name": "Fox News", "name_hi": "फ़ॉक्स न्यूज़", "owner": "Fox Corporation", "group": "national",
     "lang": "en", "geo": "world", "feed": "https://moxie.foxnews.com/google-publisher/latest.xml"},
    {"key": "latimes", "name": "Los Angeles Times", "name_hi": "लॉस एंजेलिस टाइम्स", "owner": "Los Angeles Times",
     "group": "national", "lang": "en", "geo": "world", "feed": "https://www.latimes.com/world-nation/rss2.0.xml"},
]
MAX_AGE_H = 36
# PIB answers 403 to a bot User-Agent, and serves the Hindi feed to any request without &reg=. NDTV and France 24
# answer 403 to a request without a browser's Accept headers (checked on a GitHub runner, 2026-10-13).
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/141.0 Safari/537.36")
BROWSER_HEADERS = {"User-Agent": BROWSER_UA,
                   "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                   "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8", "Sec-Fetch-Dest": "document",
                   "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "none", "Upgrade-Insecure-Requests": "1"}
BROWSER_HOSTS = ("pib.gov.in", "ndtv.com", "ndtv.in", "france24.com")
TEXT_TIMEOUT = 20
MAX_TEXTS = 12
MIN_TEXT = 300  # an extract shorter than this is a video page or a teaser, not an article
REPORTS = 4  # articles in the writer's Reporting block, each from a different owner
EXCERPT = 1400
# A story Wikipedia has no article for: this many owners within NEW_WINDOW_H, at least one of them STRONG.
NEW_OWNERS = 3
NEW_WINDOW_H = 24

_raw: dict[str, bytes] = {}
_texts: dict[str, str | None] = {}
_fetched = 0
_lock = threading.Lock()
ITEM = re.compile(r"<(item|entry)\b[^>]*>(.*?)</\1>", re.S | re.I)


def reset() -> None:
    """Forget this run's feeds and articles (tests; a long-lived process)."""
    global _fetched
    with _lock:
        _raw.clear()
        _texts.clear()
        _fetched = 0


def _clean(raw: str) -> str:
    raw = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", raw, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", html.unescape(raw))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _field(block: str, *tags: str) -> str:
    for tag in tags:
        m = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", block, re.S | re.I)
        if m and (value := _clean(m.group(1))):
            return value
    return ""


def _when(text: str) -> datetime | None:
    if not text:
        return None
    try:
        at = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        try:
            at = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if at is None:
        return None
    return (at if at.tzinfo else at.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def parse(body: bytes | str, outlet: dict, now: datetime, hours: float = MAX_AGE_H) -> list[dict]:
    """The feed's items younger than `hours`: {title, url, outlet, owner, group, at, summary, lang, geo, feed}.
    RSS 2.0 and RDF feeds both qualify; CDATA, escaped HTML and undated items are handled (undated ones dropped)."""
    text = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
    out = []
    for m in ITEM.finditer(text):
        block = m.group(2)
        title = _field(block, "title")
        url = _field(block, "link")
        if not url.startswith("http"):
            url = _field(block, "guid")
        at = _when(_field(block, "pubDate", "dc:date", "published", "updated"))
        if at is None and outlet.get("undated"):
            at = now  # the feed lists only the latest releases and dates none of them
        if not title or not url.startswith("http") or at is None:
            continue
        url = "https://" + url[len("http://"):] if url.startswith("http://") else url
        if not -1 <= (now - at).total_seconds() / 3600 <= hours:
            continue
        out.append({"title": title, "url": url, "outlet": outlet["name"], "outlet_hi": outlet.get("name_hi"),
                    "owner": outlet["owner"], "group": outlet["group"], "lang": outlet["lang"],
                    "geo": outlet["geo"], "feed": outlet["key"], "at": at.isoformat(),
                    "summary": _field(block, "description", "summary")[:400]})
    return out


def _headers(url: str) -> dict | None:
    host = re.sub(r"^https?://", "", url).split("/")[0].lower()
    return dict(BROWSER_HEADERS) if any(host == h or host.endswith("." + h) for h in BROWSER_HOSTS) else None


def _feed(outlet: dict) -> bytes:
    with _lock:
        if outlet["key"] in _raw:
            return _raw[outlet["key"]]
    body = net.get(outlet["feed"], tries=2, timeout=30, headers=_headers(outlet["feed"]))
    with _lock:
        _raw[outlet["key"]] = body
    return body


def recent(hours: float = MAX_AGE_H, now: datetime | None = None,
           langs: tuple[str, ...] | None = None) -> tuple[list[dict], list[str]]:
    """Every allowlisted feed's items younger than `hours` (newest first, one row per article), and an error line per
    feed that could not be read. Feeds are fetched once a run."""
    now = now or datetime.now(timezone.utc)
    chosen = [o for o in OUTLETS if not langs or o["lang"] in langs]

    def one(outlet):
        try:
            return parse(_feed(outlet), outlet, now, hours), None
        except Exception as exc:
            return [], f"outlet {outlet['key']}: {type(exc).__name__}: {exc}"[:200]

    with ThreadPoolExecutor(max_workers=6) as workers:
        rows = list(workers.map(one, chosen))
    items, seen = [], set()
    for got, _ in rows:
        for item in got:
            if item["url"] not in seen:
                seen.add(item["url"])
                items.append(item)
    items.sort(key=lambda i: i["at"], reverse=True)
    return items, [e for _, e in rows if e]


def _extract(url: str) -> str | None:
    import trafilatura

    return trafilatura.extract(net.get(url, timeout=TEXT_TIMEOUT, tries=2, headers=_headers(url)),
                               include_comments=False,
                               include_tables=False, favor_precision=True)


def text(url: str) -> str | None:
    """The article's text (trafilatura), or None when it can't be read or this run's MAX_TEXTS fetches are spent."""
    global _fetched
    with _lock:
        if url in _texts:
            return _texts[url]
        if _fetched >= MAX_TEXTS:
            return None
        _fetched += 1
    try:
        got = _extract(url)
    except Exception:
        got = None
    got = got if got and len(got) >= MIN_TEXT else None
    with _lock:
        _texts[url] = got
    return got


def owners(items: list[dict]) -> list[str]:
    return list(dict.fromkeys(i["owner"] for i in items))


def compact(item: dict) -> dict:
    """What a candidate and the ledger keep of an outlet item."""
    return {k: item.get(k) for k in ("title", "url", "outlet", "outlet_hi", "owner", "group", "lang", "at")}


def about(title: str, items: list[dict], since: datetime | None = None, person: bool = False,
          hi: str | None = None) -> list[dict]:
    """The items about one story: their headline (or headline and summary) names it the way news.reverse matches a
    headline to a story article (a person's whole name, an event's place plus another title word, a Hindi headline
    by the story's Hindi label), published since `since`."""
    from . import news

    target = [news.pool_item(title, person=person, **({"hi": hi} if hi else {}))]
    out = []
    for i in items:
        if since and datetime.fromisoformat(i["at"]) < since:
            continue
        if news.reverse(i["title"], target) or news.reverse(f"{i['title']} {i.get('summary', '')}", target):
            out.append(i)
    return out


def _rank(item: dict) -> tuple:
    return (item["group"] not in STRONG, GROUPS.index(item["group"]) if item["group"] in GROUPS else 9,
            -datetime.fromisoformat(item["at"]).timestamp())


# Outlets print news-agency copy word for word: ABC News and The Independent running one AP story are one source.
AGENCIES = r"AP|Reuters|AFP|PTI|ANI|IANS|UNI|Bloomberg"
WIRE = re.compile(rf"\(({AGENCIES})\)|\b(?:with inputs from|inputs from)\s+({AGENCIES}|agencies)\b|"
                  rf"^\s*By\s+(?:The\s+)?(Associated Press|Reuters|Agence France-Presse|AFP)\b|"
                  rf"^\s*(?:[A-Z][A-Za-z ,.]{{2,40}}[:,]\s*)?(PTI|ANI|IANS|UNI)\b", re.I | re.M)
WIRE_NAMES = {"associated press": "AP", "agence france-presse": "AFP", "reuters": "Reuters", "bloomberg": "Bloomberg",
              "agencies": "agencies"}
SAME_TEXT = 0.5  # share of one article's sentences found word for word in another: the same copy


def wire(body: str) -> str | None:
    """The news agency an article's text credits (its dateline, byline or an "inputs from" line), or None."""
    for m in WIRE.finditer(body[:600] + "\n" + body[-400:]):
        got = next(g for g in m.groups() if g)
        return WIRE_NAMES.get(got.lower(), got.upper())
    return None


def _same_copy(a: str, b: str) -> bool:
    sa, sb = {s.lower() for s in _sentences(a) if len(s) > 60}, {s.lower() for s in _sentences(b) if len(s) > 60}
    return bool(sa and sb) and len(sa & sb) >= SAME_TEXT * min(len(sa), len(sb))


def reporting(items: list[dict], limit: int = REPORTS) -> list[dict]:
    """Up to `limit` readable articles about the story, each from a different owner (official, public broadcaster
    and international outlets first, then the newest), with their text. An article that credits a news agency
    counts as that agency's ("AP via ABC News"), and one whose sentences repeat an article already picked counts as
    that article's owner, so syndicated copy never passes for independent reporting. Fewer than two owners give
    nothing to corroborate, so then the list is empty."""
    picked, have = [], set()
    for item in sorted(items, key=_rank):
        if item["owner"] in have or len(picked) >= limit:
            continue
        body = text(item["url"])
        if not body:
            continue
        agency = wire(body)
        owner = f"{agency} (news agency)" if agency else item["owner"]
        twin = next((p for p in picked if _same_copy(body, p["text"])), None)
        if twin:
            owner = twin["owner"]
        if owner in have:
            continue
        row = compact(item) | {"text": body}
        if owner != item["owner"]:
            row |= {"owner": owner, "publisher": item["owner"]}
        picked.append(row)
        have.update({owner, item["owner"]})
    return picked if len({p["owner"] for p in picked}) >= 2 else []


def _sentences(body: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?।])\s+|\n+", body) if len(s.strip()) > 25]


def excerpt(body: str, words: list[str], limit: int = EXCERPT) -> str:
    """The article's opening sentences and those that name the story, up to `limit` characters."""
    sentences = _sentences(body)
    keys = [w.lower() for w in words if len(w) >= 3]
    keep = [s for n, s in enumerate(sentences) if n < 3 or any(k in s.lower() for k in keys)]
    out = ""
    for s in keep:
        if len(out) + len(s) + 1 > limit:
            break
        out += s + " "
    return out.strip()


def names(reports: list[dict], lang: str = "en") -> list[str]:
    """The outlets a Short's facts come from, as the description names them ("BBC, The Hindu, PIB")."""
    key = "outlet_hi" if lang == "hi" else "outlet"
    return list(dict.fromkeys((r.get(key) or r["outlet"]) for r in sorted(reports, key=_rank)))


# Stories Wikipedia has no article for yet. Their headline must name an incident or a protest; sport, gossip,
# elections, trials and politics never qualify, nor do opinion, explainers and live blogs.
# Flight incidents (2026-10-14): an aircraft and what happened to it, in either order ("Air India flight diverted to
# Jaipur after hijack alert", "Hijack alert: flight diverted").
AIRCRAFT = r"planes?|aircraft|airliners?|jets?|helicopters?|choppers?|flights?|airlines?|airways"
AIR_EVENT = (r"crash\w*|divert\w*|emergency landings?|hijack\w*|bomb (threat|scare)s?|turbulence|engine (fire|failure)s?|"
             r"mayday|skid\w* off")
# A war's new strikes: missiles, drones and rockets that hit something, and strikes on infrastructure. Never a
# warning, a test or a launch into space, and a bare "strike" never when it is a labour strike or a deal.
WEAPON = r"missiles?|drones?|rockets?|shelling"
IMPACT = r"hits?|strikes?|struck|slams?|pounds?|batter\w*|barrage|attacks?|kill\w*|damag\w*|destroy\w*|sink\w*"
STRIKE_WORD = r"strikes?|struck|attacks?|batter\w*|pounds?|shell(s|ed|ing)|bombard\w*"
NOT_A_STRIKE = r"warns?|warning|could|might|plans?|drills?|exercises?|tests?|test-fire\w*|spacex|isro|nasa|satellites?"
NOT_AT_WAR = (r"workers?|unions?|employees|staff|doctors|nurses|teachers|drivers|truckers|pilots|miners|farmers|"
              r"walk-?outs?|wages?|pay|hunger|bandh|general strike|nationwide strike|on strike|deals?|agreements?|"
              r"pacts?|accords?|balance|shares|stocks?|prices?|profits?|earnings|gold|lightning")
INFRASTRUCTURE = (r"energy|power|grids?|infrastructure|substations?|depots?|refiner(y|ies)|oil|fuel|pipelines?|"
                  r"dams?|ports?|facilit(y|ies)|plants?")
HEADLINE_KINDS = (
    (rf"^(?=.*\b({AIRCRAFT})\b)(?=.*\b({AIR_EVENT})\b)|\b(plane|helicopter|air) crash", "aviation"),
    (r"\b(shooting|gunman|gunmen|stabbing|bombing|suicide bomb\w*|terror attack|militant attack|grenade attack|"
     r"firing|fired at|opened fire|shot at|shots fired|gunshots?|shooters?|stabbed)\b", "attack"),
    (r"\b(cyber ?-?attack\w*|ransomware|cyber ?-?(breach|incident)s?)\b", "cyberattack"),
    (rf"^(?!.*\b({NOT_A_STRIKE})\b)(?:(?=.*\b({WEAPON})\b)(?=.*\b({IMPACT})\b)|(?=.*\b(drone|missile|air ?) ?strikes?\b)|"
     rf"(?!.*\b({NOT_AT_WAR})\b)(?=.*\b({STRIKE_WORD})\b)(?=.*\b({INFRASTRUCTURE})\b))", "strike"),
    (r"\b(explosion|explosions|blast)\b", "explosion"),
    (r"\b(derail\w*|train (crash|collision|accident))\b", "rail"),
    (r"\b(boat|ferry|ship|vessel)\b.*\b(capsiz\w*|sinks|sank|sinking)\b", "maritime"),
    (r"\bearthquake|\bquake\b", "earthquake"),
    (r"\b(cyclone|hurricane|typhoon|tropical storm)\b", "cyclone"),
    (r"\b(volcan\w*|eruption|erupts)\b", "volcano"),
    (r"\b(floods?|flooding|flash floods?|cloudbursts?)\b", "flood"),
    (r"\b(wildfires?|bushfires?|forest fires?)\b", "wildfire"),
    (r"\b(landslides?|mudslides?|avalanches?)\b", "landslide"),
    (r"\b(stampede|crowd crush|building collapse|bridge collapse|fire breaks out|massive fire|blaze)\b", "disaster"),
    (r"\b(bus|truck|car|jeep|van|vehicle)\b.*\b(accident|crash|collision|plunges?|falls? into|gorge)\b", "accident"),
    (r"\b(protests?|protesters|demonstrations?|demonstrators)\b", "protest"),
)
HEADLINE_SKIP = re.compile(
    r"\b(cricket|ipl|t20|odi|football|fifa|hockey|tennis|olympic\w*|match|tournament|league|cup|squad|championships?|"
    r"elections?|electoral|polls?|bypolls?|voting|votes?|campaign\w*|court|verdict|trial|bail|hearing|acquit\w*|"
    r"convict\w*|sentenc\w*|box office|wedding|bigg boss|trailer|review|"
    r"opinion|editorial|analysis|explainer|explained|podcast|quiz|horoscope|anniversary|years? "
    r"after|recalls?|remember\w*|stock|sensex|nifty|ipo|minister|bjp|congress|mla|party|hc|sc|plea|petition|pil|"
    r"all about)\b|^(how|why|what|who|when|where|is|are|can|should|will|inside)\b", re.I)
# Film and live-blog words drop a headline unless it reports violence: "Bollywood actor Tiger Shroff survives
# shooting attempt" and "Tiger Shroff Firing Case LIVE Updates" are news; an actor "shooting" a film is not.
SOFT_SKIP = re.compile(r"\b(actor|actress|film|movie|celebrity|live|watch|video)\b", re.I)
VIOLENCE = re.compile(r"\b(firing|fired at|opened fire|shot at|shots fired|gunshots?|bullets?|shooters?|gunm[ae]n|"
                      r"shooting (attempt|incident|case)|stabb\w*|attack(ed)? on)\b", re.I)
# "Attack on Tiger Shroff": an attack on a named person (case-sensitive: two capitalised words after it).
ATTACK_ON = re.compile(r"\b[Aa]ttack(ed)? on [A-Z][a-z]+ [A-Z][a-z]+")
# Countries, regions and institutions name too much to tell one story by: they never identify an nw- story alone.
GENERIC = set("""india indian pakistan pakistani china chinese bangladesh nepal sri lanka us usa america american uk
britain british england english europe european eu israel israeli iran iranian iraq russia russian ukraine ukrainian
gaza palestinian lebanon syria afghanistan africa african asia asian japan japanese korea korean france french germany
german italy spain canada australia mexico brazil indonesia philippines turkey saudi arabia uae world global
government police army centre center state states national north south east west northern southern eastern western
pm president un""".split())
# Words that help match headlines but never name a story ("Air India", "Air Canada").
NAMELESS = {"air"}
STOP = set("""the and for from with into over after near of on in at to by a an as is are was were be been has have had
its it this that these those their they them his her who what when where how why amid says said say will would
could can may more most than new latest update updates report reports reported day days week year years""".split())


def headline_kind(title: str) -> str | None:
    """The incident or protest a headline names, or None (see HEADLINE_KINDS)."""
    if HEADLINE_SKIP.search(title) or (SOFT_SKIP.search(title) and not VIOLENCE.search(title)):
        return None
    return next((kind for pattern, kind in HEADLINE_KINDS if re.search(pattern, title, re.I)),
                "attack" if ATTACK_ON.search(title) else None)


def _stem(word: str) -> str:
    word = re.sub(r"['’]s$", "", word.lower())
    return word[:-1] if len(word) > 4 and word.endswith("s") and not word.endswith("ss") else word


# Words that say what kind of incident it is, not which one: two flights diverted after bomb threats on one day
# share "flight", "diverted", "bomb" and "threat" and are still two stories.
KIND_WORD = re.compile(rf"({AIRCRAFT}|{AIR_EVENT}|{WEAPON}|{IMPACT}|{STRIKE_WORD}|bombs?|threats?|alerts?|scares?|"
                       r"emergency|landing|airstrikes?)", re.I)


def _kind_word(word: str) -> bool:
    return bool(KIND_WORD.fullmatch(word)) or any(re.search(p, word, re.I) for p, _ in HEADLINE_KINDS)


# Armed groups, and who a strike headline says struck ("Houthi missile", "Russia's strikes", "Saudi-led coalition",
# "Russia pounds Kharkiv"): an attack or strike Short never names them.
ARMED_GROUPS = set("""houthi houthis hamas hezbollah taliban isis isil daesh al-qaeda qaeda al-shabaab shabaab boko
haram wagner pkk ttp rsf jnim lashkar jaish""".split())
# "Russian missiles", "Russia's strikes": a possessive or a demonym before the weapon is who fired it; a plain place
# there is the target ("deadly Kyiv strikes", "Black Sea strikes").
_BY_WEAPON = re.compile(rf"\b([A-Z][\w\-]*?)(['’]s)?\s+(?:['‘][^'’]{{1,20}}['’]\s+)?"
                        rf"(?i:{WEAPON}|(?:air ?)?strikes?|airstrikes?|attacks?|barrage|forces|troops|army|military)\b")
DEMONYM = re.compile(r"(an|ian|i|ese|ish)$")
_ATTACKER = (
    re.compile(r"^([A-Z][\w\-]+(?: [A-Z][\w\-]+)?)\s+(?i:strikes|batters|pounds|shells|bombs|attacks|hits|"
               r"launch(?:es)?|fires|targets)\s"),
    re.compile(r"\b([A-Z][\w\-]+)\s+(?i:intensif\w+|launch(?:es|ed)?|fire[sd]?)\s+(?i:new\s+|fresh\s+)?"
               rf"(?i:{WEAPON}|(?:air ?)?strikes?|attacks?|wave)"),
    re.compile(r"\b([A-Z]\w+)-(?i:led|backed)\b"),
    re.compile(r"\b([A-Z][\w\-]+)\s+(?:(?i:likely|probably|is|was|were|are)\s+)?(?i:behind)\b"),
    re.compile(r"\b(?i:strikes?|attacks?|struck)\s+(?i:by)\s+([A-Z][\w\-]+)"),
    re.compile(r"\b([A-Z][\w\-]+(?: [A-Z][\w\-]+)?)\s+(?i:gang)\b"),
)


# Who a headline says is "behind" an attack can be just a word for a person ("Man behind ... firing"): never banned.
PEOPLE = {"man", "men", "woman", "women", "boy", "girl", "youth", "people", "police", "cops", "officials"}


def attackers(titles: list[str]) -> list[str]:
    """The names these headlines give to whoever struck or attacked, for the writer to leave out."""
    found = []
    for title in titles:
        found += [w for w in re.findall(r"[A-Za-z][\w\-]*", title) if w.lower() in ARMED_GROUPS]
        for m in _BY_WEAPON.finditer(title):
            if m.group(2) or DEMONYM.search(m.group(1)):
                found.append(m.group(1))
        for pattern in _ATTACKER:
            found += [w for m in pattern.finditer(title) for w in m.group(1).split()]
    return sorted({w for w in found if not KIND_WORD.fullmatch(w) and w.lower() not in STOP | PEOPLE})


def headline_keys(title: str) -> tuple[set[str], set[str], str | None]:
    """A headline's distinctive words (not the words naming its kind: every protest headline says "protest"), among
    them its names (capitalised words other than the first), and its first word, which may be a name too ("Chamoli
    cloudburst: ...") but is capitalised either way."""
    words = re.findall(r"[A-Za-z][A-Za-z'’\-]*", title)
    keys, names_, lead = set(), set(), None
    for n, w in enumerate(words):
        stem = _stem(w)
        if len(stem) < 3 or stem in STOP or _kind_word(w):
            continue
        keys.add(stem)
        if n and w[0].isupper():
            names_.add(stem)
        elif not n:
            lead = stem
    return keys, names_, lead


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def story_id(day: date, name: str, kind: str) -> str:
    return f"nw-{day:%Y%m%d}-{slug(name)}-{kind}"


NW = re.compile(r"^nw-(\d{8})-(.+)-([a-z]+)$")


def same_story(a: str, b: str, days: int = 2) -> bool:
    """Two nw- ids name one story: the same place and kind, first reported within `days` of each other (the first
    report seen can shift between runs as old items leave the feeds)."""
    ma, mb = NW.match(a or ""), NW.match(b or "")
    if not ma or not mb or ma.group(3) != mb.group(3):
        return False
    # A one-word name and the phrase it heads are one place ("black" and "black-sea", named before and after 2026-10-16).
    pa, pb = sorted((ma.group(2).split("-"), mb.group(2).split("-")), key=len)
    if pb[:len(pa)] != pa:
        return False
    da, db = (datetime.strptime(m.group(1), "%Y%m%d").date() for m in (ma, mb))
    return abs((da - db).days) <= days


def strong(who: list[str]) -> list[str]:
    """The owners among these that are official, public broadcasters or international outlets."""
    top = {o["owner"] for o in OUTLETS if o["group"] in STRONG}
    return [o for o in who if o in top]


def stories(items: list[dict], now: datetime, known: list[str] | None = None,
            young: list[str] | None = None) -> list[dict]:
    """Stories at least NEW_OWNERS independent owners report within NEW_WINDOW_H (one of them STRONG) that no
    Wikipedia article in `known` (or that Wikipedia's search found for any of their items) is about. An article in
    `young` is too new to be told from (stories.MIN_ARTICLE_AGE), so its story is told from the reporting meanwhile
    and carries the article's title as "article". English headlines only. Two headlines tell one story when they name the same kind and a name, and share two distinctive
    words that are not countries or institutions (one of them the name), or three when the shared name is only a
    country; a headline's first word counts as a name when the other headline writes it as one."""
    from . import news

    young = set(young or [])
    told_from = set(known or []) - young
    pool = [news.pool_item(t) for t in told_from]
    rows = []
    for i in items:
        # Only an article the desk can tell the story from takes a headline: one matched to a person's biography
        # ("Tiger Shroff") or a gang's page still belongs to the incident.
        if i["lang"] != "en" or i.get("matched") in told_from:
            continue
        kind = headline_kind(i["title"])
        if kind:
            keys, names_, lead = headline_keys(i["title"])
            maybe = names_ | ({lead} if lead else set())
            # In headline order, so that the story's name is the same on every run when two names tie.
            ordered = list(dict.fromkeys(k for w in re.findall(r"[A-Za-z][A-Za-z'’\-]*", i["title"])
                                         if (k := _stem(w)) in maybe))
            rows.append({"item": i, "kind": kind, "keys": keys, "names": names_, "maybe": maybe, "ordered": ordered})

    def same(a: dict, b: dict) -> bool:
        if a["kind"] != b["kind"]:
            return False
        shared = a["keys"] & b["keys"] - GENERIC
        named = a["maybe"] & b["maybe"] & (a["names"] | b["names"])
        return bool(named) and len(shared) >= (2 if named - GENERIC else 3)

    def home_for(row: dict, clusters: list[dict]) -> dict | None:
        # A headline joins the story at least half of whose headlines it matches: with 35 feeds, one loose link
        # would otherwise chain two incidents into one.
        best, home = 0, None
        for c in clusters:
            hits = sum(same(row, other) for other in c["rows"])
            if hits * 2 >= len(c["rows"]) and hits > best:
                best, home = hits, c
        return home

    def add(home: dict, row: dict) -> None:
        home["names"] |= row["names"]
        home["counts"].update(row["ordered"])
        home["rows"].append(row)
        home["items"].append(row["item"])

    clusters: list[dict] = []
    for row in sorted(rows, key=lambda r: r["item"]["at"]):
        home = home_for(row, clusters)
        if home is None:
            home = {"kind": row["kind"], "names": set(), "rows": [], "items": [], "counts": Counter()}
            clusters.append(home)
        add(home, row)
    # A headline that came before the one linking it to a story stands alone after the first pass ("attack hits
    # Saudi Aramco facility" before "missile hits Aramco building ... Yemen fuel depot"): it joins now, by the same rule.
    for c in [c for c in clusters if len(c["rows"]) == 1]:
        if len(c["rows"]) != 1:
            continue
        if home := home_for(c["rows"][0], [o for o in clusters if o is not c]):
            add(home, c["rows"][0])
            clusters.remove(c)
    out = []
    for c in clusters:
        fresh = [i for i in c["items"] if (now - datetime.fromisoformat(i["at"])).total_seconds() <= NEW_WINDOW_H * 3600]
        who = owners(fresh)
        if len(who) < NEW_OWNERS or not any(i["group"] in STRONG for i in fresh):
            continue
        if any(news.reverse(i["title"], [p]) for p in pool for i in c["items"]):
            continue  # Wikipedia already has the story's article: it is told from there
        heads = list(dict.fromkeys(i["title"] for i in c["items"]))
        struck = attackers(heads) if c["kind"] in ("attack", "strike") else []
        banned = {_stem(w) for w in struck} | NAMELESS
        named = [k for k, _ in c["counts"].most_common() if k in c["names"] and k not in GENERIC and k not in banned]
        if not named:
            continue

        def spelt(key: str) -> str:
            word = next(w for i in c["items"] for w in re.findall(r"[A-Za-z][A-Za-z'’\-]*", i["title"])
                        if _stem(w) == key)
            return re.sub(r"['’]s$", "", word)

        def joinable(word: str) -> bool:
            return (word[0].isupper() and not _kind_word(word) and _stem(word) not in STOP
                    and word.lower() not in GENERIC and _stem(word) not in banned)

        def phrase(key: str) -> str:
            """The name the key's word stands in, as most headlines write it: "Black Sea", never "Black" (whose
            Wikipedia article is the colour). Runs over 3 words are a Title Case headline, not a name."""
            runs: Counter = Counter()
            for i in c["items"]:
                words = list(re.finditer(r"[A-Za-z][A-Za-z'’\-]*", i["title"]))
                for n, m in enumerate(words):
                    if _stem(m.group(0)) != key:
                        continue
                    lo = hi = n
                    while lo and joinable(words[lo - 1].group(0)) and i["title"][words[lo - 1].end():words[lo].start()] == " ":
                        lo -= 1
                    while (hi + 1 < len(words) and joinable(words[hi + 1].group(0))
                           and i["title"][words[hi].end():words[hi + 1].start()] == " "):
                        hi += 1
                    if hi - lo < 3:
                        runs[" ".join(re.sub(r"['’]s$", "", w.group(0)) for w in words[lo:hi + 1])] += 1
            # A tie goes to the shorter name ("Kolkata" over "Kolkata Durga Puja").
            return max(runs, key=lambda r: (runs[r], -len(r.split()))) if runs else spelt(key)

        name = phrase(named[0])
        first = min(datetime.fromisoformat(i["at"]) for i in c["items"])
        newest = max(i["at"] for i in c["items"])
        lead = sorted(c["items"], key=_rank)[0]
        geos = {i["geo"] for i in c["items"] if i["geo"]}
        out.append({"id": story_id(first.date(), name, c["kind"]), "qid": None, "title": lead["title"],
                    "name": name, "kind": "incident", "category": c["kind"], "date": first.date().isoformat(),
                    "news_at": newest, "owners": who, "fame": news.HEADLINE_FAME * min(len(who), 6),
                    "news": news.HEADLINE_FAME * min(len(who), 6), "views": 0, "traffic": 0,
                    "headlines": heads[:5], "places": [spelt(k) for k in named[1:4]], "attackers": struck,
                    "hindi_headlines": [], "hindi_news": 0, "geos": sorted(geos),
                    "region": "india" if geos == {"IN"} else "world", "india_link": "IN" in geos,
                    "label_hi": None, "reports": [compact(i) for i in sorted(c["items"], key=_rank)][:8],
                    "via": [f"outlet:{o}" for o in who], "emerging": True,
                    "article": next((i["matched"] for i in c["items"] if i.get("matched") in young), None)})
    return sorted(out, key=lambda c: -c["fame"])
