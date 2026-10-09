"""Wikipedia and Wikidata: what the world is reading (fame), what kind of event it is, and its structured facts.

Wikidata is CC0; Wikipedia text is CC BY-SA, so the studio only takes facts (dates, places, counts) and writes its
own sentences, crediting both.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

import mwparserfromhell

from . import net

API = "https://en.wikipedia.org/w/api.php"
WD_API = "https://www.wikidata.org/w/api.php"
SPARQL = "https://query.wikidata.org/sparql"
TOP = "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia/all-access/{y}/{m:02d}/{d:02d}"
PER_ARTICLE = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/"
               "{title}/daily/{start}/{end}")

# Wikidata classes (checked by label) and the studio category each one maps to.
CLASSES = {
    "Q744913": "aviation", "Q26975538": "aviation", "Q3149875": "aviation",
    "Q7944": "earthquake", "Q8092": "cyclone", "Q7692360": "volcano", "Q8068": "flood", "Q169950": "wildfire",
    "Q167903": "landslide", "Q8070": "tsunami",
    "Q2223653": "attack", "Q21480300": "attack", "Q2252077": "attack", "Q891854": "attack", "Q3882219": "attack",
    "Q179057": "explosion", "Q1078765": "rail", "Q852190": "maritime",
    "Q2380335": "strike", "Q645883": "conflict", "Q178561": "conflict", "Q198": "conflict", "Q350604": "conflict",
    "Q3839081": "disaster", "Q171558": "accident",
}
HUMAN = "Q5"
SKIP_PREFIX = ("Special:", "Main_Page", "Wikipedia:", "Portal:", "File:", "Help:", "Category:", "Template:", "Talk:")


def top_articles(day: date | None = None) -> tuple[date, list[tuple[str, int]]]:
    """The most-read English Wikipedia articles on the latest day with published data."""
    day = day or datetime.now(timezone.utc).date() - timedelta(days=1)
    for back in range(3):
        d = day - timedelta(days=back)
        try:
            items = net.get_json(TOP.format(y=d.year, m=d.month, d=d.day), tries=1)["items"][0]["articles"]
        except Exception:
            continue
        return d, [(a["article"].replace("_", " "), a["views"]) for a in items if not a["article"].startswith(SKIP_PREFIX)]
    raise RuntimeError("no Wikipedia pageview data for the last three days")


def daily_views(title: str, days: int = 30, end: date | None = None) -> list[int]:
    end = end or datetime.now(timezone.utc).date() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    url = PER_ARTICLE.format(title=title.replace(" ", "_").replace("/", "%2F"), start=f"{start:%Y%m%d}00",
                             end=f"{end:%Y%m%d}00")
    try:
        return [i["views"] for i in net.get_json(url, tries=2)["items"]]
    except Exception:
        return []


def page_info(titles: list[str]) -> dict[str, dict]:
    """title -> {title (canonical), qid, lat, lon, created}; resolves redirects."""
    out = {}
    for i in range(0, len(titles), 50):
        chunk = titles[i:i + 50]
        d = net.get_json(API, params={"action": "query", "prop": "pageprops|coordinates", "ppprop": "wikibase_item",
                                      "titles": "|".join(chunk), "redirects": 1, "format": "json", "formatversion": 2})
        q = d["query"]
        back = {r["to"]: r["from"] for r in q.get("redirects", [])} | {n["to"]: n["from"] for n in q.get("normalized", [])}
        for p in q.get("pages", []):
            if p.get("missing"):
                continue
            c = (p.get("coordinates") or [{}])[0]
            info = {"title": p["title"], "qid": p.get("pageprops", {}).get("wikibase_item"),
                    "lat": c.get("lat"), "lon": c.get("lon")}
            out[p["title"]] = info
            if p["title"] in back:
                out[back[p["title"]]] = info
    return out


def created(title: str) -> datetime | None:
    d = net.get_json(API, params={"action": "query", "prop": "revisions", "titles": title, "rvlimit": 1, "rvdir": "newer",
                                  "rvprop": "timestamp", "format": "json", "formatversion": 2})
    revs = d["query"]["pages"][0].get("revisions")
    return datetime.fromisoformat(revs[0]["timestamp"].replace("Z", "+00:00")) if revs else None


def classify(qids: list[str]) -> dict[str, set[str]]:
    """qid -> studio categories, following instance-of and subclass-of chains on the Wikidata query service."""
    out: dict[str, set[str]] = {q: set() for q in qids}
    roots = " ".join(f"wd:{r}" for r in list(CLASSES) + [HUMAN])
    for i in range(0, len(qids), 40):
        items = " ".join(f"wd:{q}" for q in qids[i:i + 40])
        query = (f"SELECT ?item ?root WHERE {{ VALUES ?item {{ {items} }} VALUES ?root {{ {roots} }} "
                 f"?item wdt:P31/wdt:P279* ?root . }}")
        rows = net.get_json(SPARQL, params={"query": query, "format": "json"})["results"]["bindings"]
        for r in rows:
            q, root = r["item"]["value"].rsplit("/", 1)[1], r["root"]["value"].rsplit("/", 1)[1]
            out[q].add("human" if root == HUMAN else CLASSES[root])
    return out


def entities(qids: list[str]) -> dict[str, dict]:
    out = {}
    for i in range(0, len(qids), 50):
        d = net.get_json(WD_API, params={"action": "wbgetentities", "ids": "|".join(qids[i:i + 50]),
                                         "props": "claims|labels|sitelinks", "languages": "en", "format": "json"})
        out.update(d.get("entities", {}))
    return out


def label(ent: dict) -> str | None:
    return ent.get("labels", {}).get("en", {}).get("value")


def claims(ent: dict, pid: str) -> list:
    """Values of a property, preferred-rank claims first and deprecated ones dropped."""
    rows = [c for c in ent.get("claims", {}).get(pid, []) if c.get("rank") != "deprecated"]
    rows.sort(key=lambda c: c.get("rank") != "preferred")
    out = []
    for c in rows:
        v = c["mainsnak"].get("datavalue", {}).get("value")
        if isinstance(v, dict):
            if "id" in v:
                v = v["id"]
            elif "time" in v:
                v = v["time"]
            elif "amount" in v:
                v = float(v["amount"])
            elif "latitude" in v:
                v = (v["latitude"], v["longitude"])
        if v is not None:
            out.append({"value": v, "preferred": c.get("rank") == "preferred", "qualifiers": list(c.get("qualifiers", {}))})
    return out


def single_number(ent: dict, pid: str) -> int | None:
    """A count only when Wikidata is unambiguous: one preferred value, or exactly one unqualified value."""
    rows = claims(ent, pid)
    preferred = [r for r in rows if r["preferred"]]
    if len(preferred) == 1:
        return int(preferred[0]["value"])
    plain = [r for r in rows if not r["qualifiers"]]
    if len(rows) == 1 or (len(plain) == 1 and not preferred):
        return int((plain or rows)[0]["value"])
    return None


def wd_time(value: str) -> date | None:
    m = re.match(r"[+-](\d{4})-(\d{2})-(\d{2})", value or "")
    if not m or m.group(2) == "00" or m.group(3) == "00":
        return None
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def coords(ent: dict) -> tuple[float, float] | None:
    rows = claims(ent, "P625")
    return tuple(rows[0]["value"]) if rows else None


def infobox(title: str) -> tuple[str, dict[str, str]]:
    """The article's first infobox: (template name, {field: plain text}) with refs, markup and notes removed."""
    d = net.get_json(API, params={"action": "parse", "page": title, "prop": "wikitext", "redirects": 1,
                                  "format": "json", "formatversion": 2})
    code = mwparserfromhell.parse(d["parse"]["wikitext"])
    for t in code.filter_templates(recursive=False):
        name = str(t.name).strip()
        if name.lower().startswith("infobox"):
            fields = {}
            for p in t.params:
                key = str(p.name).strip().lower()
                val = mwparserfromhell.parse(str(p.value))
                for ref in val.filter_tags(matches=lambda n: str(n.tag).lower() in ("ref", "sup", "small")):
                    try:
                        val.remove(ref)
                    except ValueError:
                        pass
                text = val.strip_code(normalize=True, collapse=True)
                text = re.sub(r"<[^>]+>", " ", text)
                text = re.sub(r"\s+", " ", text).strip(" ,;")
                if text:
                    fields[key] = text
            return name, fields
    return "", {}


def leading_number(text: str | None) -> int | None:
    """The count a field opens with ("260 (241 on board, 19 on ground)" -> 260); None if it opens with words."""
    m = re.match(r"\s*(?:at least |about |approximately |~|c\. ?)?(\d{1,3}(?:,\d{3})+|\d+)\b", text or "")
    return int(m.group(1).replace(",", "")) if m else None


def search(query: str) -> str | None:
    d = net.get_json(API, params={"action": "query", "list": "search", "srsearch": query, "srlimit": 1,
                                  "format": "json", "formatversion": 2})
    hits = d["query"]["search"]
    return hits[0]["title"] if hits else None


def url(title: str) -> str:
    return "https://en.wikipedia.org/wiki/" + title.replace(" ", "_")
