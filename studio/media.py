"""Real, freely licensed photos for a story from Wikimedia Commons, each carrying its author and licence.

Only files hosted on Commons qualify (non-free "fair use" files live on Wikipedia itself and are never touched), and
only CC0, public-domain, CC BY and CC BY-SA licences pass. Logos, maps, signatures and anything whose name suggests
injury or death imagery are skipped. When Commons has too few, Openverse (keyless) fills in photos of the story's
places and things only, under CC0, CC BY or CC BY-SA; outlet photos are never used.
"""
from __future__ import annotations

import hashlib
import html
import re
from dataclasses import asdict, dataclass
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


def hosts(photos: list[dict]) -> str:
    """Where a Short's photos come from, as its end card and description name them."""
    return "Wikimedia Commons and Openverse" if any(from_openverse(p) for p in photos) else "Wikimedia Commons"
