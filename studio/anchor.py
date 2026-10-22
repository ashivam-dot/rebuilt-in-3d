"""What each picture of a photo Short shows, and whether the beat it stands under names it.

Owner, 2026-10-22, on the Macron protest-ban Short: "No real photos of incidents, no Macron photo, no school photo ...
do you think people are here to watch the map". Each beat shows only who, what or where it names:
- a person: their own photo;
- a place: a photo of that place;
- a thing (the police, a school, a ship): a photo of it;
- the event itself: a photo of the event, from its own Commons category or its recent uploads.

A map stands only under a beat whose point is where it happened. A Short shows at most MAX_MAPS map, for at most
MAP_SHARE of its picture time. Pictures that show what is said fill at least SHOWN_SHARE of it.

Each photo dict carries "kind" (KINDS) and "shows" (the names a beat says to show it), stamped where it was found
(studio/media.py, studio/writer.py). A photo made before the stamp is read from its origin, role and description
(legacy_kind, legacy_terms), so the plans of Shorts already published are judged the same way (tests/tools/replay.py).
"""
from __future__ import annotations

import re
import unicodedata

KINDS = ("person", "event", "thing", "place", "setting", "map", "view")
MAX_MAPS = 1
MAP_SHARE = 0.20
SHOWN_SHARE = 0.70
# compose cuts to a beat's picture on the word that names it, when that word comes this early in the beat.
CUT_WITHIN = 0.45
# Origins of a story's own photos (the event's Wikidata image, article, category; an editor's choice; NASA's).
OWN = {"wikidata", "article", "category", "editor", "search", "nasa", "event", "recent"}
# Particles never matched alone ("del" in Puerta del Sol).
STOP = {"de", "del", "la", "le", "les", "van", "von", "der", "da", "di", "du", "the", "of", "and", "el", "al", "bin",
        "ibn", "y", "e", "do", "dos", "das", "st", "mr", "mrs", "dr", "photo", "file", "jpg", "jpeg", "png"}


def norm(text: str) -> str:
    """Lower case without accents ("São Paulo" -> "sao paulo"; "Nuñez" -> "nunez")."""
    text = unicodedata.normalize("NFKD", text or "").replace("’", "'")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def says(text: str, term: str) -> re.Match | None:
    """Where text names term: whole words, any case and accents, with a plural or possessive ending."""
    t = norm(term).strip()
    if len(t) < 3 or t in STOP:
        return None
    return re.search(r"(?<![\w])" + re.escape(t) + r"(?:'s|s|es)?(?![\w])", norm(text))


def person_terms(name: str) -> list[str]:
    """A person is named by their full name or their surname ("Emmanuel Macron", "Macron")."""
    parts = [p for p in re.split(r"\s+", (name or "").strip()) if p]
    return list(dict.fromkeys([name.strip()] + ([parts[-1]] if len(parts) > 1 else []))) if parts else []


def _ordinary(word: str) -> bool:
    from . import writer

    return writer.ordinary(word)


def distinct(text: str) -> list[str]:
    """The distinctive names in a caption: capitalised words that are not plain English ("Entrance to the Sol Metro
    station in Madrid" -> Madrid)."""
    out = []
    for m in re.finditer(r"\b[A-ZÀ-Þ][\w'’\-]{2,}", text or ""):
        w = re.sub(r"['’]s$", "", m.group(0))
        if norm(w) in STOP or _ordinary(norm(w)):
            continue
        out.append(w)
    return list(dict.fromkeys(out))


def legacy_kind(photo: dict, sid: str = "", short_kind: str = "") -> str:
    """What an unstamped photo shows, from where it was found. A report story's (nw-) Commons photos were all of the
    places and things it links to, never of the event; a tribute's own photos are the person's face-matched
    portraits."""
    text = f"{photo.get('file', '')} {photo.get('description', '')}"
    if photo.get("role") == "map" or photo.get("origin") == "map":
        return "map"
    if photo.get("role") == "view":
        return "view"
    from . import media

    if media.MAP_TEXT.search(text):
        return "map"
    if photo.get("role") == "setting":
        return "setting"
    own = photo.get("origin") in OWN or photo.get("origin") in (None, "")
    if photo.get("focus") or (short_kind == "death" and own):
        return "person"
    if own and not sid.startswith("nw-"):
        return "event"
    return "place"


def kind_of(photo: dict, sid: str = "", short_kind: str = "") -> str:
    return photo.get("kind") or legacy_kind(photo, sid, short_kind)


def legacy_terms(photo: dict, kind: str, subject: str = "") -> list[str]:
    if kind == "person":
        return person_terms(subject)
    if kind == "map":
        m = re.search(r"\baround ([^,]+)", photo.get("description") or "")
        return [m.group(1).strip()] if m else []
    if kind in ("event", "view"):
        return []
    file = re.sub(r"^File:|\.\w+$|\(\d+\)", " ", photo.get("file") or "").replace("_", " ")
    return distinct(f"{photo.get('description') or ''} {file}")


def terms_of(photo: dict, kind: str, subject: str = "") -> list[str]:
    shows = [s for s in photo.get("shows") or [] if s]
    if shows:
        out = []
        for s in shows:
            out += person_terms(s) if kind == "person" else [s]
        return list(dict.fromkeys(out))
    return legacy_terms(photo, kind, subject)


class Story:
    """A Short's photos as anchors: who or what each shows, and which stand under any beat about the event.

    subject: the story's name (a person for a tribute). people: people the reporting names, with or without a free
    photo of their own; a beat naming one without a photo has nothing to show (a protest photo under "Trump said ..."
    shows neither Trump nor what he said)."""

    def __init__(self, photos: list[dict], subject: str = "", people: list[str] | None = None, sid: str = "",
                 short_kind: str = ""):
        self.photos = photos
        self.subject = subject or ""
        self.kinds = [kind_of(p, sid, short_kind) for p in photos]
        self.terms = [terms_of(p, k, self.subject) for p, k in zip(photos, self.kinds)]
        events = [i for i, k in enumerate(self.kinds) if k in ("event", "view")]
        own = [i for i, k in enumerate(self.kinds) if k == "person"
               and any(says(t, s) or says(s, t) for t in self.terms[i] for s in person_terms(self.subject)[-1:])]
        # The pictures a beat about the story itself stands on: the event's own photos; for a story about a person
        # without event photos (a tribute, an attack on an actor), that person's portraits.
        if not own and (short_kind == "death" or not self.subject):
            own = [i for i, k in enumerate(self.kinds) if k == "person"]  # a tribute's photos are all face-matched
        self.defaults = set(events) or set(own)
        shown = {norm(t) for i, k in enumerate(self.kinds) if k == "person" for t in self.terms[i]}
        self.unshown = [p for p in people or [] if not any(norm(t) in shown for t in person_terms(p))]

    # -- what a beat names --------------------------------------------------------------------------------------
    def named(self, text: str) -> list[int]:
        """Photos (not maps) whose names the text says, in the order it says them."""
        hits = []
        for i, k in enumerate(self.kinds):
            if k == "map":
                continue
            at = [m.start() for t in self.terms[i] if (m := says(text, t))]
            if at:
                hits.append((min(at), i))
        return [i for _, i in sorted(hits)]

    def faceless_names(self, text: str) -> list[str]:
        """People the text names who have no free photo of their own."""
        return [p for p in self.unshown if any(says(text, t) for t in person_terms(p))]

    def word(self, text: str, i: int) -> str:
        """The word in text that names photo i (where compose cuts to it), "" for a photo shown by default."""
        found = [m for t in self.terms[i] if (m := says(text, t))]
        if not found:
            return ""
        m = min(found, key=lambda m: m.start())
        return text_at(text, m)

    def fits(self, text: str, i: int, first: bool = False) -> bool:
        """Photo i shows what the beat says: the beat names it; or it is a picture of the event (or of the person a
        tribute is about) and the beat names nobody else who has a picture or nobody without one; or it is the map
        and the beat's point is where it happened (map_fits)."""
        if not 0 <= i < len(self.photos):
            return False
        if self.kinds[i] == "map":
            return not first and self.map_fits(text, i)
        named = self.named(text)
        if i in named:
            return True
        if i not in self.defaults:
            return False
        others = [j for j in named if self.kinds[j] in ("person", "thing") and j not in self.defaults]
        return not others and not self.faceless_names(text)

    def map_fits(self, text: str, i: int) -> bool:
        """A map under a beat that names its place and names no person or thing (with a picture or without)."""
        if not any(says(text, t) for t in self.terms[i]):
            return False
        named = self.named(text)
        return not any(self.kinds[j] in ("person", "thing") for j in named) and not self.faceless_names(text)

    # -- choosing each beat's picture -----------------------------------------------------------------------
    def assign(self, texts: list[str], chosen: list[int] | None = None) -> list[tuple[int, str]]:
        """(photo, naming word) for each beat, decided by code: a photo the beat names (first named first), else a
        picture of the event, else the map when the beat is about where, else the writer's choice (then unanchored,
        and the checks send the script back). The same photo twice in a row only when nothing else fits."""
        chosen = list(chosen or [])
        weights = [max(len(t.split()), 1) for t in texts]
        total = sum(weights) or 1
        uses: dict[int, int] = {}
        map_words = 0
        maps_used: set[int] = set()
        out: list[tuple[int, str]] = []
        for k, text in enumerate(texts):
            prev = out[-1][0] if out else None
            first = k == 0
            fit = [i for i in self.named(text) if self.fits(text, i, first)]
            fit += [i for i in sorted(self.defaults, key=lambda i: (uses.get(i, 0), i))
                    if i not in fit and self.fits(text, i, first)]
            mine = chosen[k] if k < len(chosen) else None
            pick = None
            if mine in fit and (mine != prev or len(fit) == 1):
                pick = mine
            elif fit:
                named = [i for i in fit if i in self.named(text)]
                pool = named or fit
                pool = [i for i in pool if i != prev] or pool
                pick = min(pool, key=lambda i: (uses.get(i, 0), pool.index(i))) if not named else pool[0]
            else:
                maps = [i for i, kd in enumerate(self.kinds) if kd == "map" and self.fits(text, i, first)]
                maps = [i for i in maps if (not maps_used or i in maps_used) and len(maps_used | {i}) <= MAX_MAPS
                        and (map_words + weights[k]) / total <= MAP_SHARE]
                if maps:
                    pick = maps[0]
                    maps_used.add(pick)
                    map_words += weights[k]
            if pick is None:
                real = [i for i, kd in enumerate(self.kinds) if kd != "map"]
                pick = mine if mine is not None and 0 <= mine < len(self.photos) and self.kinds[mine] != "map" \
                    else (prev if prev is not None and self.kinds[prev] != "map" else (real or [0])[0])
            uses[pick] = uses.get(pick, 0) + 1
            out.append((pick, self.word(text, pick)))
        return out

    # -- judging a plan ---------------------------------------------------------------------------------------
    def judge(self, texts: list[str], shots: list[int], weights: list[float] | None = None) -> dict:
        """How a plan (each beat's photo) shows what it says: the share of picture time on photos that show what the
        beat names ("shown"), on maps ("maps"), the beats that show something else ("unanchored"), the maps on a beat
        that is not about where ("bad_maps"), and the different maps used."""
        weights = weights or [max(len(t.split()), 1) for t in texts]
        total = sum(weights) or 1
        shown = maps = 0.0
        unanchored, bad_maps, used_maps = [], [], set()
        for k, (text, i, w) in enumerate(zip(texts, shots, weights)):
            ok = self.fits(text, i, k == 0)
            if 0 <= i < len(self.kinds) and self.kinds[i] == "map":
                maps += w
                used_maps.add(i)
                if not ok:
                    bad_maps.append(k)
            elif ok:
                shown += w
            else:
                unanchored.append(k)
        return {"shown": shown / total, "maps": maps / total, "unanchored": unanchored, "bad_maps": bad_maps,
                "map_photos": len(used_maps)}

    def showable(self) -> list[str]:
        """The names a beat may say to show a picture, for the writer."""
        return list(dict.fromkeys(t for i, k in enumerate(self.kinds) if k not in ("map", "event", "view")
                                  for t in self.terms[i][:1]))

    def subject_shown(self, kind: str) -> bool:
        """The story's own subject has a real picture: the person a tribute (or person story) is about, else the
        event itself, or a person or thing named as the story."""
        if kind == "death":
            return any(k == "person" for k in self.kinds)
        if any(k in ("event", "view") for k in self.kinds):
            return True
        return any(k in ("person", "thing") and any(says(self.subject, t) or says(t, self.subject)
                                                    for t in self.terms[i]) for i, k in enumerate(self.kinds))


def text_at(text: str, m: re.Match) -> str:
    """The original-cased word of text at a match made on norm(text) (same length: norm keeps one char per char
    for Latin text; falls back to the normalised word)."""
    word = text[m.start():m.end()] if len(norm(text)) == len(text) else m.group(0)
    return word.split()[0] if word.split() else word


def story_of(short) -> Story:
    """The Story of a Short: its photos, subject and the people its reporting names (scene)."""
    scene = short.scene
    subject = (scene.get("subject") or {}).get("name") or next((f.value for f in short.facts if f.key == "name"), "")
    return Story(scene.get("photos") or [], subject, [p["name"] for p in scene.get("people") or []], short.id,
                 short.kind)
