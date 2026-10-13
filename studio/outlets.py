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

GROUPS = ("official", "public broadcaster", "international", "Indian national", "Hindi")
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


def reporting(items: list[dict], limit: int = REPORTS) -> list[dict]:
    """Up to `limit` readable articles about the story, each from a different owner (official, public broadcaster
    and international outlets first, then the newest), with their text. Fewer than two owners give nothing to
    corroborate, so then the list is empty."""
    picked, have = [], set()
    for item in sorted(items, key=_rank):
        if item["owner"] in have or len(picked) >= limit:
            continue
        body = text(item["url"])
        if body:
            picked.append(compact(item) | {"text": body})
            have.add(item["owner"])
    return picked if len(have) >= 2 else []


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
HEADLINE_KINDS = (
    (r"\b(plane|aircraft|helicopter|jet|airliner|flight)\b.*\b(crash\w*|crash-lands?)\b|\b(plane|helicopter|air) crash",
     "aviation"),
    (r"\b(shooting|gunman|gunmen|stabbing|bombing|suicide bomb\w*|terror attack|militant attack|drone strikes?|"
     r"missile strikes?|air ?strikes?|grenade attack)\b", "attack"),
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
    r"convict\w*|sentenc\w*|actor|actress|film|movie|box office|wedding|bigg boss|celebrity|trailer|review|"
    r"opinion|editorial|analysis|explainer|explained|live|watch|video|podcast|quiz|horoscope|anniversary|years? "
    r"after|recalls?|remember\w*|stock|sensex|nifty|ipo|minister|bjp|congress|mla|party|hc|sc|plea|petition|pil|"
    r"all about)\b|^(how|why|what|who|when|where|is|are|can|should|will|inside)\b", re.I)
# Countries, regions and institutions name too much to tell one story by: they never identify an nw- story alone.
GENERIC = set("""india indian pakistan pakistani china chinese bangladesh nepal sri lanka us usa america american uk
britain british england english europe european eu israel israeli iran iranian iraq russia russian ukraine ukrainian
gaza palestinian lebanon syria afghanistan africa african asia asian japan japanese korea korean france french germany
german italy spain canada australia mexico brazil indonesia philippines turkey saudi arabia uae world global
government police army centre center state states national north south east west northern southern eastern western
pm president un""".split())
STOP = set("""the and for from with into over after near of on in at to by a an as is are was were be been has have had
its it this that these those their they them his her who what when where how why amid says said say will would
could can may more most than new latest update updates report reports reported day days week year years""".split())


def headline_kind(title: str) -> str | None:
    """The incident or protest a headline names, or None (see HEADLINE_KINDS)."""
    if HEADLINE_SKIP.search(title):
        return None
    return next((kind for pattern, kind in HEADLINE_KINDS if re.search(pattern, title, re.I)), None)


def _stem(word: str) -> str:
    word = re.sub(r"['’]s$", "", word.lower())
    return word[:-1] if len(word) > 4 and word.endswith("s") and not word.endswith("ss") else word


def _kind_word(word: str) -> bool:
    return any(re.search(p, word, re.I) for p, _ in HEADLINE_KINDS)


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
    if not ma or not mb or ma.group(2, 3) != mb.group(2, 3):
        return False
    da, db = (datetime.strptime(m.group(1), "%Y%m%d").date() for m in (ma, mb))
    return abs((da - db).days) <= days


def stories(items: list[dict], now: datetime, known: list[str] | None = None) -> list[dict]:
    """Stories at least NEW_OWNERS independent owners report within NEW_WINDOW_H (one of them STRONG) that no
    Wikipedia article in `known` (or that Wikipedia's search found for any of their items) is about. English
    headlines only. Two headlines tell one story when they name the same kind and a name, and share two distinctive
    words that are not countries or institutions (one of them the name), or three when the shared name is only a
    country; a headline's first word counts as a name when the other headline writes it as one."""
    from . import news

    pool = [news.pool_item(t) for t in known or []]
    rows = []
    for i in items:
        if i["lang"] != "en" or i.get("matched"):
            continue
        kind = headline_kind(i["title"])
        if kind:
            keys, names_, lead = headline_keys(i["title"])
            rows.append({"item": i, "kind": kind, "keys": keys, "names": names_,
                         "maybe": names_ | ({lead} if lead else set())})

    def same(a: dict, b: dict) -> bool:
        if a["kind"] != b["kind"]:
            return False
        shared = a["keys"] & b["keys"] - GENERIC
        named = a["maybe"] & b["maybe"] & (a["names"] | b["names"])
        return bool(named) and len(shared) >= (2 if named - GENERIC else 3)

    clusters: list[dict] = []
    for row in sorted(rows, key=lambda r: r["item"]["at"]):
        home = next((c for c in clusters if any(same(row, other) for other in c["rows"])), None)
        if home is None:
            home = {"kind": row["kind"], "names": set(), "rows": [], "items": [], "counts": Counter()}
            clusters.append(home)
        home["names"] |= row["names"]
        home["counts"].update(row["maybe"])
        home["rows"].append(row)
        home["items"].append(row["item"])
    out = []
    for c in clusters:
        fresh = [i for i in c["items"] if (now - datetime.fromisoformat(i["at"])).total_seconds() <= NEW_WINDOW_H * 3600]
        who = owners(fresh)
        if len(who) < NEW_OWNERS or not any(i["group"] in STRONG for i in fresh):
            continue
        if any(news.reverse(i["title"], [p]) for p in pool for i in c["items"]):
            continue  # Wikipedia already has the story's article: it is told from there
        named = [k for k, _ in c["counts"].most_common() if k in c["names"] and k not in GENERIC]
        if not named:
            continue
        name_key = named[0]
        name = next(w for i in c["items"] for w in re.findall(r"[A-Za-z][A-Za-z'’\-]*", i["title"])
                    if _stem(w) == name_key)
        name = re.sub(r"['’]s$", "", name)
        first = min(datetime.fromisoformat(i["at"]) for i in c["items"])
        newest = max(i["at"] for i in c["items"])
        lead = sorted(c["items"], key=_rank)[0]
        geos = {i["geo"] for i in c["items"] if i["geo"]}
        out.append({"id": story_id(first.date(), name, c["kind"]), "qid": None, "title": lead["title"],
                    "name": name, "kind": "incident", "category": c["kind"], "date": first.date().isoformat(),
                    "news_at": newest, "owners": who, "fame": news.HEADLINE_FAME * min(len(who), 6),
                    "news": news.HEADLINE_FAME * min(len(who), 6), "views": 0, "traffic": 0,
                    "headlines": list(dict.fromkeys(i["title"] for i in c["items"]))[:5],
                    "hindi_headlines": [], "hindi_news": 0, "geos": sorted(geos),
                    "region": "india" if geos == {"IN"} else "world", "india_link": "IN" in geos,
                    "label_hi": None, "reports": [compact(i) for i in sorted(c["items"], key=_rank)][:8],
                    "via": [f"outlet:{o}" for o in who], "emerging": True})
    return sorted(out, key=lambda c: -c["fame"])
