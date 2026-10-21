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
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from . import net, wiki

COMMONS = "https://commons.wikimedia.org/w/api.php"
FREE = re.compile(r"^(CC0|Public domain|PD\b|CC BY(-SA)? \d(\.\d)?( [a-z]{2,})?$|CC BY(-SA)?$)", re.I)
NOT_PHOTO = re.compile(r"(\.svg$|\.gif$|\.tiff?$|\blogo|signature|autograph|\bmap\b|map\.\w+$|locator|location|\bflag\b|coat of arms|"
                       r"\bicon\b|\bseal\b|emblem|chart|graph|diagram|insignia|\bplan\b|route|blank|wordmark|"
                       r"collage|montage)", re.I)
# Dignity: a Short never shows bodies, wounds or grief at a funeral.
GRAPHIC = re.compile(r"(corpse|bodies|\bbody\b|victim|blood|wound|injur|\bdead\b|killed|funeral|cremat|coffin|casket|"
                     r"wreckage|debris|crash site|aftermath)", re.I)
MIN_SIDE = 480


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


def too_wide(ent: dict) -> bool:
    """A country, province or state (it has a capital): its photos are satellite views and landmarks far from any
    one event, so a Short never shows them."""
    return bool(wiki.claims(ent, "P36"))


def role_of(ent: dict) -> str:
    """"setting" for a town, city or village (it has a population): its photos show where something happened, never
    what happened. A station, an airport, a school, a train, a line or an operator is the story's "subject"."""
    return "setting" if wiki.claims(ent, "P1082") else "subject"


def find(title: str, ent: dict, limit: int = 8, extra_qids: list[str] | None = None,
         places: bool = False) -> list[Photo]:
    """Up to `limit` usable photos: the Wikidata image first, then the article's own images, then its Commons category.

    Article and category files must name the story (the person's surname, the storm's name) in their file name or
    description, so a festival photo that merely sits in a person's category is not passed off as them.
    extra_qids adds the main image of related items (a birthplace, an aircraft type, an airport) after those, in the
    order given, each with its role (role_of); countries and provinces are skipped (too_wide).
    places: also take photos from each related item's own article whose file name names that item (a city skyline,
    the airport's terminal), for an article so new that Commons has nothing of the event itself. Such an article's
    own images were put there by its editors (the station it happened at), so they need not name the story.
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
            ordered += [("File:" + c["value"], "related", role_of(e)) for c in wiki.claims(e, "P18")[:1]]
        for q, e in related.items() if places else ():
            ordered += _place_files(e)
    return _usable(ordered, keys, limit, trust_article=places)


def _place_files(e: dict) -> list[tuple[str, str, str]]:
    """Up to three files from an item's own article whose names name the item (a city skyline, a school's front)."""
    page, own = wiki.sitelink(e, "enwiki"), _keys(wiki.label(e) or "")
    try:
        files = _article_files(page) if page and own else []
    except Exception:
        files = []
    role = role_of(e)
    return [(f, "place", role) for f in files if _names(f.replace("_", " "), own) and not NOT_PHOTO.search(f)][:3]


def named(name: str, also: str = "", limit: int = 3, exclude: set[str] | None = None) -> list[Photo]:
    """Commons photos found by searching for a thing's name (a train, a railway, an airline) whose file name or
    description names it, for an item with no main image of its own. also: a word that narrows the search ("train")."""
    d = net.get_json(COMMONS, params={"action": "query", "list": "search", "srnamespace": 6, "srlimit": 20,
                                      "srsearch": f'"{name}" {also} filetype:bitmap'.replace("  ", " "),
                                      "format": "json", "formatversion": 2})
    files = [h["title"] for h in d.get("query", {}).get("search", [])]
    return _usable([(f, "search", "subject") for f in files], _keys(name), limit, exclude=exclude)


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
        ordered += [("File:" + c["value"], "related", role_of(e)) for c in wiki.claims(e, "P18")[:1]]
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
                            host="Openverse" + (f" ({source.capitalize()})" if source else ""), role=role))
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
# A third party's rights named anywhere in the record.
THIRD_PARTY = re.compile(r"(courtesy|©|\(c\)\s*\d|copyright|all rights reserved|used with permission|getty|reuters|"
                         r"associated press|\bAP Photo|\bAFP\b|\bESA\b|JAXA|Roscosmos|Maxar|DigitalGlobe|Planet Labs|"
                         r"Airbus)", re.I)
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
        if NOT_PHOTO.search(title) or NASA_NOT_PHOTO.search(title) or GRAPHIC.search(f"{title} {desc}"):
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
                            description=title, date=taken, origin="nasa", host=NASA_HOST))
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
            exclude: set[str] | None = None, trust_article: bool = False) -> list[Photo]:
    """ordered: (file, origin) or (file, origin, role) rows, best first."""
    seen, files = set(), []
    banned = {e.replace("_", " ") for e in exclude or ()}
    for f, origin, *role in ordered:
        f = f.replace("_", " ")
        if f in banned:
            continue
        if f not in seen and not GRAPHIC.search(f) and (origin == "editor" or not NOT_PHOTO.search(f)):
            seen.add(f)
            files.append((f, origin, role[0] if role else "subject"))
    info = _info([f for f, _, _ in files])
    photos, hashes, shoots = [], set(), {}
    for f, origin, role in files:
        ii = info.get(f)
        if not ii or ii.get("mime") not in ("image/jpeg", "image/png", "image/webp"):
            continue
        meta = ii.get("extmetadata", {})
        lic = _text(meta.get("LicenseShortName", {}).get("value"), 40)
        desc = _text(meta.get("ImageDescription", {}).get("value"))
        if not FREE.match(lic) or meta.get("NonFree", {}).get("value") or GRAPHIC.search(desc):
            continue
        if min(ii["width"], ii["height"]) < MIN_SIDE or ii.get("sha1") in hashes:
            continue
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
                            date=_text(meta.get("DateTimeOriginal", {}).get("value"), 40), origin=origin, role=role))
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
