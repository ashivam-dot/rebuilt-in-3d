"""Real, freely licensed photos for a story from Wikimedia Commons, each carrying its author and licence.

Only files hosted on Commons qualify (non-free "fair use" files live on Wikipedia itself and are never touched), and
only CC0, public-domain, CC BY and CC BY-SA licences pass. Logos, maps, signatures and anything whose name suggests
injury or death imagery are skipped. When Commons has too few, Openverse (keyless) fills in photos of the story's
places and things only, under CC0, CC BY or CC BY-SA; outlet photos are never used. A storm, eruption, flood, fire or
other natural disaster may also take NASA Image and Video Library photos of the event itself (public domain, NASA's
own only: nasa()).
"""
from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path

from . import net, wiki

COMMONS = "https://commons.wikimedia.org/w/api.php"
# GODL-India: the Government Open Data License - India, under which PIB publishes its photos; free to reuse with
# attribution (data.gov.in/government-open-data-license-india), credited like CC BY.
FREE = re.compile(r"^(CC0|Public domain|PD\b|CC BY(-SA)? \d(\.\d)?( [a-z]{2,})?$|CC BY(-SA)?$|GODL-India$)", re.I)
NOT_PHOTO = re.compile(r"(\.svg$|\.gif$|\.tiff?$|\blogo|signature|autograph|\bmap\b|map\.\w+$|locator|location|\bflag\b|coat of arms|"
                       r"\bicon\b|\bseal\b|emblem|chart|graph|diagram|insignia|\bplan\b|route|blank|wordmark|"
                       r"collage|montage)", re.I)
# Dignity: a Short never shows bodies, wounds or grief at a funeral.
GRAPHIC = re.compile(r"(corpse|bodies|\bbody\b|victim|blood|wound|injur|\bdead\b|killed|funeral|cremat|coffin|casket|"
                     r"wreckage|debris|crash site|aftermath)", re.I)
MIN_SIDE = 480
# A person's own Wikidata portrait (P18) may be smaller: Captain Smit Machchhar's only free photo is 450x542.
PORTRAIT_SIDE = 360
# A map by what it shows, not by its file name: "Internationalwaters.png" (sea zones in blue) and the NASA FIRMS
# hotspot image of the CFB Wainwright fire both passed NOT_PHOTO and stood under beats as photos (2026-10-22 audit).
MAP_TEXT = re.compile(r"\b(maps?|locator|location of|exclusive economic zones?|EEZs?|hotspots?|FIRMS|"
                      r"fire detections?|choropleth|topographic)\b", re.I)
# Not licence-safe however it is tagged: a photograph of someone else's photo, poster, painting or screen, a cover
# or a logo. Chuck Amato's portrait was a CC0 "photo taken of a photo displayed at" a restaurant (2026-10-22).
DERIVATIVE = re.compile(r"(\bphoto(graph)?s? (taken )?of (a|an|the|his|her) (photo|photograph|picture|print|"
                        r"poster|painting|portrait|screen|tv|television)|\b(displayed|on display|hanging) (at|in)\b|"
                        r"\bposters?\b|screen ?shots?|screen ?capture|screengrab|\bpaintings?\b|"
                        r"\b(book|album|dvd|magazine|film|record) cover|\bstill from\b|\blogos?\b)", re.I)


@dataclass
class Photo:
    file: str  # "File:Name.jpg" on Commons
    url: str  # a 1600 px rendition
    page: str  # the Commons file page, for credits
    width: int
    height: int
    author: str
    license: str
    description: str
    date: str
    origin: str  # "wikidata", "article", "category", ... or "openverse"
    path: str = ""
    host: str = "Wikimedia Commons"  # where the file is credited: Commons, or "Openverse (Flickr)"
    role: str = "subject"  # "setting": only the town or area it happened in, never the event or what was involved
    # What the photo shows (studio/anchor.py): "person", "event", "thing", "place" or "setting" ("" until the writer
    # stamps it), and the names a beat says to show it ("Emmanuel Macron", "Macron"; "Puerta del Sol").
    kind: str = ""
    shows: list = field(default_factory=list)

    @property
    def credit(self) -> str:
        return f"Photo: {self.author} / {self.license} / {self.host}"


def _text(value: str | None, limit: int = 200) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    return text[:limit]


def _info(files: list[str]) -> dict[str, dict]:
    out = {}
    for i in range(0, len(files), 40):
        d = net.get_json(COMMONS, params={
            "action": "query", "titles": "|".join(files[i:i + 40]), "prop": "imageinfo", "iiurlwidth": 1600,
            "iiprop": "url|size|mime|extmetadata|sha1", "format": "json", "formatversion": 2, "redirects": 1})
        for p in d["query"].get("pages", []):
            if p.get("missing") or not p.get("imageinfo"):
                continue
            out[p["title"]] = p["imageinfo"][0]
    return out


def _article_files(title: str) -> list[str]:
    d = net.get_json(wiki.API, params={"action": "parse", "page": title, "prop": "images", "redirects": 1,
                                       "format": "json", "formatversion": 2})
    return ["File:" + f for f in d.get("parse", {}).get("images", [])]


def _category_files(category: str, limit: int = 60) -> list[str]:
    d = net.get_json(COMMONS, params={"action": "query", "list": "categorymembers", "cmtitle": "Category:" + category,
                                      "cmtype": "file", "cmlimit": limit, "format": "json", "formatversion": 2})
    return [m["title"] for m in d.get("query", {}).get("categorymembers", [])]


GENERIC = {"the", "of", "and", "in", "on", "at", "flight", "hurricane", "cyclone", "typhoon", "storm", "tropical",
           "earthquake", "attack", "bombing", "shooting", "crash", "fire", "flood", "floods", "disaster", "accident",
           "incident", "explosion", "derailment", "collision", "sinking", "airlines", "air", "airways", "season"}


def _keys(title: str) -> set[str]:
    """Distinctive words of a story title: 'Hurricane Isaias (2026)' -> {'isaias'}; 'Nana Patekar' -> both names.

    Long titles keep only their longest word, so 'Air India Flight 171' still matches a photo captioned 'Air India'.
    """
    words = re.findall(r"[^\W\d_]{3,}", re.sub(r"\([^)]*\)", "", title).lower())
    keys = {w for w in words if w not in GENERIC}
    return {max(keys, key=len)} if len(keys) > 3 else keys


def _names(text: str, keys: set[str]) -> bool:
    low = text.lower()
    return bool(keys) and all(k in low for k in keys)


def _shoot(file: str) -> str:
    """Files from one photo shoot share a name up to the numbering: group them so a Short shows variety."""
    stem = re.sub(r"\.[a-z]+$", "", file.lower())
    return re.sub(r"[\s_(-]*(\(?image )?\d+\)?(?=[\s,.]|$).*$", "", stem)[:40]


# Oceans, seas, gulfs, bays, straits, continents and regions: a photo of one is a sunset or a world map, never
# the story (Hurricane Trudy went out over three Openverse "Pacific Ocean" sunsets, 2026-10-17).
WIDE_TYPES = {"Q9430", "Q165", "Q1322134", "Q39594", "Q37901", "Q5107", "Q82794", "Q1620908", "Q15324", "Q23442"}


def too_wide(ent: dict) -> bool:
    """A country, province or state (it has a capital), an ocean, sea or region (WIDE_TYPES): its photos are
    satellite views, sunsets and landmarks far from any one event, so a Short never shows them."""
    return bool(wiki.claims(ent, "P36")) or bool({c["value"] for c in wiki.claims(ent, "P31")} & WIDE_TYPES)


def role_of(ent: dict) -> str:
    """"setting" for a town, city or village (it has a population): its photos show where something happened, never
    what happened. A station, an airport, a school, a train, a line or an operator is the story's "subject"."""
    return "setting" if wiki.claims(ent, "P1082") else "subject"


def stamp_of(ent: dict) -> dict:
    """What a related item's photo shows (anchor kinds): the town ("setting"), a place, or a thing, by its name."""
    name = wiki.label(ent) or ""
    kind = "setting" if role_of(ent) == "setting" else "place" if place_like(ent) else "thing"
    return {"kind": kind, "shows": [name] if name else []}


def find(title: str, ent: dict, limit: int = 8, extra_qids: list[str] | None = None,
         places: bool = False, portrait: bool = False) -> list[Photo]:
    """Up to `limit` usable photos: the Wikidata image first, then the article's own images, then its Commons category.

    Article and category files must name the story (the person's surname, the storm's name) in their file name or
    description, so a festival photo that merely sits in a person's category is not passed off as them.
    extra_qids adds the main image of related items (a birthplace, an aircraft type, an airport) after those, in the
    order given, each with its role (role_of); countries and provinces are skipped (too_wide).
    places: also take photos from each related item's own article whose file name names that item (a city skyline,
    the airport's terminal), for an article so new that Commons has nothing of the event itself. Such an article's
    own images were put there by its editors (the station it happened at), so they need not name the story.
    portrait: the item is a person, whose own Wikidata portrait may be as small as PORTRAIT_SIDE.
    The Hindi desk reproduces this ranking to keep its photos apart (hindi-news-desk desk/orbitwire.py).
    """
    keys = _keys(wiki.label(ent) or title) | _keys(title)
    ordered: list[tuple[str, str, str]] = []
    for c in wiki.claims(ent, "P18"):
        ordered.append(("File:" + c["value"], "wikidata", "subject"))
    try:
        ordered += [(f, "article", "subject") for f in _article_files(title)]
    except Exception:
        pass
    for c in wiki.claims(ent, "P373")[:1]:
        try:
            ordered += [(f, "category", "subject") for f in _category_files(c["value"])]
        except Exception:
            pass
    if extra_qids:
        related = {q: e for q, e in wiki.entities(extra_qids).items() if not too_wide(e)}
        for q, e in related.items():
            ordered += [("File:" + c["value"], "related", role_of(e), stamp_of(e)) for c in wiki.claims(e, "P18")[:1]]
        for q, e in related.items() if places else ():
            ordered += _place_files(e)
    return _usable(ordered, keys, limit, trust_article=places, small={"wikidata"} if portrait else set())


def _place_files(e: dict) -> list[tuple[str, str, str]]:
    """Up to three files from an item's own article whose names name the item (a city skyline, a school's front)."""
    page, own = wiki.sitelink(e, "enwiki"), _keys(wiki.label(e) or "")
    try:
        files = _article_files(page) if page and own else []
    except Exception:
        files = []
    role, stamp = role_of(e), stamp_of(e)
    return [(f, "place", role, stamp) for f in files if _names(f.replace("_", " "), own) and not NOT_PHOTO.search(f)][:3]


def named(name: str, also: str = "", limit: int = 3, exclude: set[str] | None = None) -> list[Photo]:
    """Commons photos found by searching for a thing's name (a train, a railway, an airline) whose file name or
    description names it, for an item with no main image of its own. also: a word that narrows the search ("train")."""
    d = net.get_json(COMMONS, params={"action": "query", "list": "search", "srnamespace": 6, "srlimit": 20,
                                      "srsearch": f'"{name}" {also} filetype:bitmap'.replace("  ", " "),
                                      "format": "json", "formatversion": 2})
    files = [h["title"] for h in d.get("query", {}).get("search", [])]
    return _usable([(f, "search", "subject") for f in files], _keys(name), limit, exclude=exclude)


_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december")


def _day(text: str) -> date | None:
    """The day a Commons date field gives ("2026-10-17 19:55", "17 October 2026"), else None."""
    if m := re.search(r"\b(\d{4})-(\d{2})-(\d{2})", text or ""):
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    if m := re.search(r"\b(\d{1,2})(?:st|nd|rd|th)? (" + "|".join(_MONTHS) + r"),? (\d{4})\b", (text or "").lower()):
        return date(int(m.group(3)), _MONTHS.index(m.group(2)) + 1, int(m.group(1)))
    return None


# Words a Commons category or file name uses for each kind of event: a category of the event names it so
# ("Category:Hurricane Trudy (2026)", "Category:17 October 2026 protests in Paris"), where "Paris Fashion Week 2026"
# does not.
EVENT_WORDS = {
    "protest": r"protests?|demonstrations?|manifestations?|rall(y|ies)|marches|marche|protest march|riots?|unrest|strikes?|gr[eè]ve|"
               r"yellow vests|gilets jaunes|sit-?in|encampment|acampada",
    "cyclone": r"hurricane|typhoon|cyclone|storm|tropical depression",
    "wildfire": r"fires?|wildfires?|bushfires?|smoke|burn",
    "flood": r"floods?|flooding|cloudburst|inundation",
    "earthquake": r"earthquakes?|quakes?",
    "volcano": r"eruptions?|volcan\w*|lava|ash plume",
    "landslide": r"landslides?|mudslides?",
    "attack": r"attacks?|strikes?|bombings?|shelling|explosions?|missiles?|drones?",
    "rail": r"derailments?|train|railway|collision",
    "aviation": r"crash|flight|aircraft|hijack\w*|emergency landing",
    "maritime": r"sinking|capsiz\w*|shipwreck|ferry|collision",
}
EVENT_WORDS["movement"] = EVENT_WORDS["protest"]
EVENT_WORDS["strike"] = EVENT_WORDS["attack"]
EVENT_WORDS["conflict"] = EVENT_WORDS["attack"] + "|" + EVENT_WORDS["protest"]  # "2026 Italian unrest" is a conflict
EVENT_WORDS["tsunami"] = r"tsunamis?"
EVENT_WORDS["disaster"] = "|".join(EVENT_WORDS[k] for k in ("cyclone", "flood", "earthquake", "landslide", "wildfire"))
EVENT_STAMP = {"kind": "event", "shows": []}


def _event_words(category: str | None) -> re.Pattern:
    words = EVENT_WORDS.get(category or "") or "|".join(dict.fromkeys(EVENT_WORDS.values()))
    return re.compile(r"\b(" + words + r")\b", re.I)


# The words a search for an event's files uses ("Paris manifestation" finds "Manifestation du 17 octobre 2026 à
# Paris 112.jpg"), in the languages Commons uploaders caption in most.
EVENT_QUERY = {"protest": ("protest", "manifestation", "demonstration"), "cyclone": ("storm", "hurricane"),
               "wildfire": ("fire",), "flood": ("flood",), "earthquake": ("earthquake",), "volcano": ("eruption",),
               "landslide": ("landslide",), "attack": ("attack",), "rail": ("train",), "aviation": ("crash",),
               "maritime": ("ship",), "tsunami": ("tsunami",)}
EVENT_QUERY["movement"] = EVENT_QUERY["protest"]
EVENT_QUERY["strike"] = EVENT_QUERY["attack"]
EVENT_QUERY["conflict"] = ("protest", "attack", "demonstration")
# Month names in the languages Commons event categories are named in ("Manifestations du 17 octobre 2026").
MONTHS = (_MONTHS_EN := ("january", "february", "march", "april", "may", "june", "july", "august", "september",
                         "october", "november", "december"),
          ("janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout", "septembre", "octobre", "novembre",
           "decembre"),
          ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
           "noviembre", "diciembre"),
          ("januar", "februar", "marz", "april", "mai", "juni", "juli", "august", "september", "oktober", "november",
           "dezember"))
# A protest or a conflict goes on for days: its photos may be from the week before the story; anything else is
# photographed from the day before it on.
ONGOING = {"protest", "movement", "conflict"}


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(c)).lower()


def _on_the_day(title: str, when: date, back: int) -> bool:
    """The title names a day of the event's last `back` days ("17 octobre 2026", "2026-10-17")."""
    low = _plain(title)
    for k in range(back + 1):
        d = when - timedelta(days=k)
        if f"{d:%Y-%m-%d}" in low:
            return True
        for names in MONTHS:
            month = names[d.month - 1][:3] + r"\w*"  # "17 Oct 2026" too
            if re.search(rf"\b{d.day}(er|st|nd|rd|th)? {month}\b", low) or re.search(rf"\b{month} {d.day}\b", low):
                return True
    return False


def _back(category: str | None) -> int:
    return 7 if category in ONGOING else 1


def event_categories(name: str, when: date, category: str | None = None, limit: int = 3) -> list[str]:
    """Commons categories of the event itself: found by its name, the kind of event and its year, each naming the
    year and the kind of event (EVENT_WORDS) and either the name's distinctive words or one of its days ("Manifestations
    du 17 octobre 2026"). [] on any failure: a lookup never stops a run."""
    keys, words = _keys(name), _event_words(category)
    out: list[str] = []
    for query in (f"{name} {when.year}",) + tuple(f"{w} {when.year} {name}" for w in EVENT_QUERY.get(category or "",
                                                                                                    ())[:2]):
        try:
            d = net.get_json(COMMONS, params={"action": "query", "list": "search", "srnamespace": 14, "srlimit": 20,
                                              "srsearch": query, "format": "json", "formatversion": 2},
                             tries=2, timeout=20)
        except Exception:
            continue
        for hit in d.get("query", {}).get("search", []):
            title = hit.get("title", "").removeprefix("Category:")
            if str(when.year) in title and words.search(_plain(title)) and title not in out \
                    and (_names(_plain(title), {_plain(k) for k in keys}) or _on_the_day(title, when, _back(category))):
                out.append(title)
    return out[:limit]


def recent_files(name: str, when: date, category: str | None = None, limit: int = 40) -> list[str]:
    """Commons files about the event uploaded lately: searches for its name with the kind of event, newest first,
    whose file name names it and the kind of event. Their dates are checked by _usable (since). [] on any failure."""
    keys, words = {_plain(k) for k in _keys(name)}, _event_words(category)
    out: list[str] = []
    for w in EVENT_QUERY.get(category or "", ("",))[:3]:
        try:
            d = net.get_json(COMMONS, params={"action": "query", "list": "search", "srnamespace": 6, "srlimit": limit,
                                              "srsearch": f"{name} {w} filetype:bitmap".replace("  ", " "),
                                              "srsort": "create_timestamp_desc", "format": "json",
                                              "formatversion": 2}, tries=2, timeout=20)
        except Exception:
            continue
        out += [h["title"] for h in d.get("query", {}).get("search", []) if h.get("title") not in out
                and _names(_plain(h.get("title", "")), keys) and words.search(_plain(h.get("title", "")))]
    return out


def _event_files(category: str, keys: list[set[str]], limit: int = 60) -> list[str]:
    """The files of an event's Commons category and of its subcategories (by city: "Manifestations du 17 octobre
    2026 à Paris"), the subcategories naming the story's own places first, three at most."""
    d = net.get_json(COMMONS, params={"action": "query", "list": "categorymembers", "cmtitle": "Category:" + category,
                                      "cmtype": "file|subcat", "cmlimit": 100, "format": "json", "formatversion": 2},
                     tries=2, timeout=20)
    members = d.get("query", {}).get("categorymembers", [])
    files = [m["title"] for m in members if m.get("ns") == 6][:limit]
    subs = [m["title"].removeprefix("Category:") for m in members if m.get("ns") == 14]
    subs = [c for c in subs if any(k and _names(_plain(c), k) for k in keys)][:3]
    for sub in subs:
        if len(files) >= limit:
            break
        files += _category_files(sub, limit - len(files))
    return files


def event(names: list[str], when: date, category: str | None = None, limit: int = 6,
          exclude: set[str] | None = None) -> list[Photo]:
    """Free photos of the event itself (anchor kind "event"): the files of its own Commons categories, then recent
    uploads naming it, none taken before its first day (the day before it, or a week before for a protest or a
    conflict: a photo from another year is not this event), under the same licence, size, decency, derivative and
    map checks as every photo. Wikimedia Commons hosts the free imports of official sources (kremlin.ru and
    president.gov.ua under CC BY 4.0, US federal works in the public domain, PIB under GODL-India), each with its
    licence read per file. [] on any failure."""
    rows: list[tuple] = []
    keys = [{_plain(k) for k in _keys(n)} for n in names if n]
    try:
        for name in dict.fromkeys(n for n in names if n):
            for cat in event_categories(name, when, category):
                try:
                    rows += [(f, "event", "subject", EVENT_STAMP) for f in _event_files(cat, keys)]
                except Exception:
                    continue
        for name in dict.fromkeys(n for n in names if n):
            rows += [(f, "recent", "subject", EVENT_STAMP) for f in recent_files(name, when, category)]
        if not rows:
            return []
        return _usable(rows, set(), limit, exclude=exclude, since=when - timedelta(days=_back(category)))
    except Exception:
        return []


def context(qids: list[str], limit: int = 6, exclude: set[str] | None = None) -> list[Photo]:
    """Photos of the places and things a story links to (a birthplace, a school, an award, the airport): each item's
    main image, then files from its article that name it. They fill a Short whose own photos are too few, and are
    never of the story's person (the caller drops any that feature a face). Countries and provinces are skipped."""
    if not qids:
        return []
    ordered = []
    for e in wiki.entities(qids).values():
        if too_wide(e):
            continue
        ordered += [("File:" + c["value"], "related", role_of(e), stamp_of(e)) for c in wiki.claims(e, "P18")[:1]]
        ordered += _place_files(e)
    return _usable(ordered, set(), limit, exclude=exclude)


OPENVERSE = "https://api.openverse.org/v1/images/"
# Openverse licence codes a Short may use: CC0, CC BY and CC BY-SA. Non-commercial, no-derivatives and the
# public-domain mark (which asserts no licence) never pass.
OPENVERSE_LICENCES = {"cc0": "CC0", "by": "CC BY", "by-sa": "CC BY-SA"}
OPENVERSE_PER_PLACE = 3


def openverse(query: str, limit: int = OPENVERSE_PER_PLACE, exclude: set[str] | None = None,
              role: str = "subject") -> list[Photo]:
    """Freely licensed photos of a place, object or scene from Openverse (keyless): CC0, CC BY or CC BY-SA only,
    from sources other than Wikimedia (Commons is read directly), whose title names the query, at most two by one
    creator. Never asked about a person: callers search only the places and things a story links to, and drop any
    photo that features a face."""
    d = net.get_json(OPENVERSE, params={"q": query, "license_type": "commercial,modification",
                                        "excluded_source": "wikimedia", "page_size": 20}, tries=2, timeout=30)
    keys = _keys(query)
    photos, creators = [], {}
    for r in d.get("results") or []:
        lic, url = OPENVERSE_LICENCES.get((r.get("license") or "").lower()), r.get("url") or ""
        file, title = f"openverse:{r.get('id')}", _text(r.get("title"))
        ext = (r.get("filetype") or url.rsplit(".", 1)[-1]).lower()
        if not lic or r.get("mature") or not url.startswith("https://") or file in (exclude or set()):
            continue
        if ext not in ("jpg", "jpeg", "png", "webp") or NOT_PHOTO.search(title) or GRAPHIC.search(title):
            continue
        if min(r.get("width") or 0, r.get("height") or 0) < MIN_SIDE or not _names(title, keys):
            continue
        author = _text(r.get("creator"), 60) or "unknown author"
        if creators.get(author, 0) >= 2:
            continue
        creators[author] = creators.get(author, 0) + 1
        source = (r.get("source") or r.get("provider") or "").replace("_", " ")
        photos.append(Photo(file=file, url=url, page=r.get("foreign_landing_url") or url, width=r["width"],
                            height=r["height"], author=author, license=f"{lic} {r.get('license_version') or ''}".strip(),
                            description=title, date="", origin="openverse",
                            host="Openverse" + (f" ({source.capitalize()})" if source else ""), role=role,
                            kind="setting" if role == "setting" else "place", shows=[query]))
        if len(photos) >= limit:
            break
    return photos


NASA = "https://images-api.nasa.gov/search"
NASA_LICENCE = "Public domain (NASA)"
NASA_HOST = "NASA Image and Video Library"
# Story categories (trends.ORDER) whose events NASA's cameras see: storms and smoke from orbit, eruptions, floods.
# Never people, attacks or transport incidents.
NASA_CATEGORIES = {"cyclone", "volcano", "flood", "wildfire", "landslide", "tsunami", "earthquake", "disaster"}
NASA_PER_STORY = 3
# NASA's own works are public domain; its library also holds partners' and agencies' images under their terms. A
# credit passes only when every party in it is NASA, one of its centres, or (after "NASA/") a NASA photographer;
# US federal partners' works (NOAA, USGS) are public domain too.
NASA_PARTY = re.compile(r"^(?:NASA\b.*|JPL(?:-Caltech)?|Caltech|GSFC|LaRC|JSC|KSC|MSFC|ARC|GRC|AFRC|SSC|NOAA|USGS)$")
_PERSON = re.compile(r"^[A-Z][a-z'’.-]+(?: [A-Z][a-z'’.-]*){1,3}$")
_ORG_WORD = re.compile(r"\b(?:Systems?|Agency|Space|University|Institute|Inc|Corp\w*|Ltd|LLC|Company|Images?|Photos?|"
                       r"Press|News|Team|Mission|Labs?|Laborator\w+|Observatory|Society|Foundation|Japan|Europe\w*|"
                       r"Getty|Reuters|Associated|Maxar|Airbus|Planet)\b")
# A third party's rights named anywhere in the record: wire and commercial credits, and the space and weather
# agencies whose satellite data NASA's Earth Observatory often processes but which keep their own terms (Copernicus
# Sentinel, Himawari/JMA, EUMETSAT/Meteosat, KOMPSAT/KARI), however they are written.
THIRD_PARTY = re.compile(r"(courtesy|©|\(c\)\s*\d|copyright|all rights reserved|used with permission|getty|reuters|"
                         r"associated press|\bAP Photo|\bAFP\b|\bESA\b|European Space Agency|Copernicus|"
                         r"\bSentinel-?\d|JAXA|Japan Aerospace|Himawari|Japan Meteorological|\bJMA\b|EUMETSAT|"
                         r"Meteosat|KOMPSAT|\bKARI\b|Korea Aerospace|\bKMA\b|Korea Meteorological|GEO-?KOMPSAT|"
                         r"\bCNES\b|Pl[eé]iades|\bDLR\b|TerraSAR|\bISRO\b|Canadian Space Agency|RADARSAT|Fengyun|"
                         r"Gaofen|Roscosmos|Maxar|DigitalGlobe|Planet Labs|Airbus)", re.I)
# Data a named party "processed", "provided", "operated" or "supplied" is that party's unless it is NASA, NOAA, USGS
# or another US federal body: "data (2024) processed by the European Space Agency", "operated by the Japan ...".
_BY_PARTY = re.compile(r"\b(?:processed|provided|operated|supplied|distributed|licen[cs]ed)\s+by\s+(?:the\s+)?"
                       r"([A-Z][\w.’'-]*(?:\s+[A-Z][\w.’'-]*)*)")
_FEDERAL = re.compile(r"^(?:NASA|NOAA|USGS|U\.?S\.?|United States|National Aeronautics|National Oceanic|"
                      r"National (?:Hurricane|Weather|Interagency)|Naval|Department of|Federal|Jet Propulsion|JPL|"
                      r"Goddard|Landsat)\b")
# Not a photograph of what happened: radar and thermal data, annotated or false-colour views, artwork.
NASA_NOT_PHOTO = re.compile(r"(radar|interferogra|insar|\bsar\b|infrared|thermal|annotated|false.colou?r|"
                            r"illustration|artist|concept|animation|render|simulat|\bmodel\b|visuali[sz]ation|"
                            r"graphic|poster|\bplot\b)", re.I)


def nasa_credit_ok(credit: str) -> bool:
    """Every party a NASA credit names is NASA's own ("NASA/JPL-Caltech", "NASA/Bill Ingalls"), never a partner's
    ("NASA/METI/AIST/Japan Space Systems, and U.S./Japan ASTER Science Team")."""
    parts = [p.strip(" .") for p in re.split(r"\s*(?:/|,|;|&|\band\b)\s*", credit or "") if p.strip(" .")]
    lead = bool(parts) and parts[0].startswith("NASA")
    return all(NASA_PARTY.match(p) or (lead and _PERSON.match(p) and not _ORG_WORD.search(p)) for p in parts)


def nasa_rights_ok(data: dict) -> bool:
    """A NASA library record whose credits are all NASA's and that names no other rights holder."""
    desc = " ".join(str(data.get(k) or "") for k in ("description", "description_508", "title"))
    if THIRD_PARTY.search(desc) or THIRD_PARTY.search(str(data.get("secondary_creator") or "")):
        return False
    if any(not _FEDERAL.match(m.group(1)) for m in _BY_PARTY.finditer(desc)):
        return False
    credits = [data.get("secondary_creator"), data.get("photographer")]
    credits += [m.group(1) for m in re.finditer(r"\b(?:image |photo )?credits?\s*:\s*([^\n;]+?)(?:\.\s|$)", desc,
                                                re.I)]
    return all(nasa_credit_ok(c) for c in credits if c)


def _nasa_rendition(links: list[dict]) -> dict | None:
    """The "~large" JPEG (1920 px), else the widest rendition with its size; None without one."""
    sized = [link for link in links or [] if link.get("width") and link.get("height")
             and (link.get("href") or "").startswith("https://") and link["href"].lower().endswith((".jpg", ".jpeg"))]
    large = [link for link in sized if "~large." in link["href"]]
    return (large or sorted(sized, key=lambda link: -link["width"]) or [None])[0]


def nasa(query: str, since: date, words: tuple[str, ...] = (), limit: int = NASA_PER_STORY,
         exclude: set[str] | None = None) -> list[Photo]:
    """Photos of a natural disaster from NASA's Image and Video Library (keyless): taken on or after `since` (a
    photo of the place from another year would pass an old storm off as this one), whose title names the query and,
    given `words`, a word starting with one of them ("hurricane", "smoke"), with NASA's own credit only
    (nasa_rights_ok), at most two under one title. Never asked about a person; callers drop any photo that features
    a face."""
    d = net.get_json(NASA, params={"q": query, "media_type": "image", "year_start": since.year, "page_size": 40},
                     tries=2, timeout=30)
    keys = _keys(query)
    photos, today, titles = [], date.today().isoformat(), {}
    for item in (d.get("collection") or {}).get("items") or []:
        data = (item.get("data") or [{}])[0]
        nid, title = str(data.get("nasa_id") or ""), _text(data.get("title"))
        desc, taken = _text(data.get("description"), 400), str(data.get("date_created") or "")[:10]
        file = f"nasa:{nid}"
        if not nid or data.get("media_type") != "image" or file in (exclude or set()):
            continue
        if not since.isoformat() <= taken <= today or not nasa_rights_ok(data):
            continue
        # The description too: "Park Fire Burn Scar" may be a false-colour or annotated view only it says so.
        if NOT_PHOTO.search(title) or NASA_NOT_PHOTO.search(f"{title} {desc}") or GRAPHIC.search(f"{title} {desc}") \
                or MAP_TEXT.search(title):
            continue
        if not _names(title, keys) or (words and not re.search(r"\b(?:" + "|".join(words) + ")", title.lower())):
            continue
        if titles.get(title.lower(), 0) >= 2:  # one crew's run of near-identical frames: keep the Short varied
            continue
        link = _nasa_rendition(item.get("links"))
        if not link or min(link["width"], link["height"]) < MIN_SIDE:
            continue
        credit = _text(data.get("secondary_creator"), 60) or "NASA"
        titles[title.lower()] = titles.get(title.lower(), 0) + 1
        photos.append(Photo(file=file, url=link["href"], page=f"https://images.nasa.gov/details/{nid}",
                            width=link["width"], height=link["height"], author=credit, license=NASA_LICENCE,
                            description=title, date=taken, origin="nasa", host=NASA_HOST, kind="event"))
        if len(photos) >= limit:
            break
    return photos


# What a NASA photo's title must say for a category, so a quiet view of the region is not passed off as the event.
NASA_WORDS = {"cyclone": ("hurricane", "typhoon", "cyclone", "storm"),
              "volcano": ("volcan", "erupt", "ash", "lava", "plume"), "flood": ("flood", "cloudburst"),
              "wildfire": ("fire", "wildfire", "bushfire", "smoke", "burn"), "landslide": ("landslide",),
              "tsunami": ("tsunami",), "earthquake": ("earthquake", "quake"), "disaster": ()}


def nasa_for(category: str | None, names: list[str], since: date, limit: int = NASA_PER_STORY,
             exclude: set[str] | None = None) -> list[Photo]:
    """NASA photos of a natural-disaster story by its name, then its places' names, each title also naming the kind
    of event (NASA_WORDS); nothing for any other kind of story (NASA_CATEGORIES)."""
    if category not in NASA_CATEGORIES:
        return []
    out, seen = [], set(exclude or ())
    for name in dict.fromkeys(n for n in names if n):
        try:
            found = nasa(name, since, NASA_WORDS.get(category, ()), limit - len(out), seen)
        except Exception:
            continue
        for p in found:
            seen.add(p.file)
            out.append(p)
        if len(out) >= limit:
            break
    return out


def place_like(ent: dict) -> bool:
    """A Wikidata item that is somewhere: it has coordinates and is not a person."""
    kinds = {c["value"] for c in wiki.claims(ent, "P31")}
    return wiki.HUMAN not in kinds and bool(wiki.claims(ent, "P625"))


def openverse_for(qids: list[str], limit: int = 6, exclude: set[str] | None = None) -> list[Photo]:
    """Openverse photos of the places a story links to (by their English Wikidata labels), in order; never of a
    person, a group or a work (an item without coordinates), nor of a country or province."""
    if not qids:
        return []
    out, seen = [], set(exclude or ())
    for e in wiki.entities(qids).values():
        name = wiki.label(e)
        if not name or not place_like(e) or too_wide(e):
            continue
        try:
            found = openverse(name, exclude=seen, role=role_of(e))
        except Exception:
            continue
        for p in found:
            seen.add(p.file)
            out.append(p)
        if len(out) >= limit:
            break
    return out[:limit]


def picks(files: list[str], limit: int = 8) -> list[Photo]:
    """Photos an editor chose for a story, in order, under the same licence, size and decency checks as find()."""
    return _usable([(f if f.startswith("File:") else "File:" + f, "editor") for f in files], set(), limit,
                   shoot_cap=limit)


def _usable(ordered: list[tuple], keys: set[str], limit: int, shoot_cap: int = 2,
            exclude: set[str] | None = None, trust_article: bool = False, small: set[str] = frozenset(),
            since: date | None = None) -> list[Photo]:
    """ordered: (file, origin), (file, origin, role) or (file, origin, role, stamp) rows, best first; stamp is
    {"kind", "shows"} (anchor kinds). small: origins whose files may be as small as PORTRAIT_SIDE. since: a file
    taken (DateTimeOriginal) before this day is dropped: a photo of the place from another year is not the event."""
    seen, files = set(), []
    banned = {e.replace("_", " ") for e in exclude or ()}
    for f, origin, *rest in ordered:
        f = f.replace("_", " ")
        if f in banned:
            continue
        if f not in seen and not GRAPHIC.search(f) and (origin == "editor" or not NOT_PHOTO.search(f)):
            seen.add(f)
            files.append((f, origin, rest[0] if rest else "subject", rest[1] if len(rest) > 1 else {}))
    info = _info([f for f, _, _, _ in files])
    photos, hashes, shoots = [], set(), {}
    for f, origin, role, stamp in files:
        ii = info.get(f)
        if not ii or ii.get("mime") not in ("image/jpeg", "image/png", "image/webp"):
            continue
        meta = ii.get("extmetadata", {})
        lic = _text(meta.get("LicenseShortName", {}).get("value"), 40)
        desc = _text(meta.get("ImageDescription", {}).get("value"))
        if not FREE.match(lic) or meta.get("NonFree", {}).get("value") or GRAPHIC.search(desc):
            continue
        if DERIVATIVE.search(f"{f} {desc}") or MAP_TEXT.search(f"{f} {desc}"):
            continue
        if min(ii["width"], ii["height"]) < (PORTRAIT_SIDE if origin in small else MIN_SIDE) or ii.get("sha1") in hashes:
            continue
        taken = _text(meta.get("DateTimeOriginal", {}).get("value"), 40)
        day = _day(taken)
        if since and (not day or day < since):
            continue  # a photo without the day it was taken may be of another day's protest
        if (origin in ("category", "search") or (origin == "article" and not trust_article)) \
                and not _names(f"{f} {desc}", keys):
            continue
        shoot = _shoot(f)
        if shoots.get(shoot, 0) >= shoot_cap:
            continue
        shoots[shoot] = shoots.get(shoot, 0) + 1
        hashes.add(ii.get("sha1"))
        author = _text(meta.get("Artist", {}).get("value"), 60) or "unknown author"
        photos.append(Photo(file=f, url=ii.get("thumburl") or ii["url"], page=ii["descriptionurl"], width=ii["width"],
                            height=ii["height"], author=author, license=lic, description=desc,
                            date=taken, origin=origin, role=role, kind=stamp.get("kind", ""),
                            shows=list(stamp.get("shows") or [])))
        if len(photos) >= limit:
            break
    return photos


def download(photos: list[Photo], folder: Path) -> list[Photo]:
    folder.mkdir(parents=True, exist_ok=True)
    kept = []
    for i, p in enumerate(photos):
        ext = ".png" if p.url.lower().endswith(".png") else ".jpg"
        # Named by the photo's URL too: a retry whose photo order changed never reuses another photo's file.
        path = folder / f"photo{i:02d}-{hashlib.sha1(p.url.encode()).hexdigest()[:10]}{ext}"
        try:
            if not path.exists():
                path.write_bytes(net.get(p.url, timeout=60))
        except Exception:
            continue
        p.path = str(path)
        kept.append(p)
    return kept


def as_dicts(photos: list[Photo]) -> list[dict]:
    return [asdict(p) | {"credit": p.credit} for p in photos]


def from_openverse(photo: dict) -> bool:
    return (photo.get("host") or "").startswith("Openverse")


def from_nasa(photo: dict) -> bool:
    return photo.get("host") == NASA_HOST


def hosts(photos: list[dict]) -> str:
    """Where a Short's photos come from, as its end card and description name them."""
    named = ["Wikimedia Commons"] + (["Openverse"] if any(from_openverse(p) for p in photos) else []) \
        + (["NASA"] if any(from_nasa(p) for p in photos) else [])
    return ", ".join(named[:-1]) + " and " + named[-1] if len(named) > 1 else named[0]
