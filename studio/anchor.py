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


# Words a caption card uses to say what is pictured: such a card over a photo that does not show it misleads.
CAPTION_THINGS = {"map", "police", "military", "army", "troop", "soldier", "ministry", "parliament", "school",
                  "court", "hospital", "embassy", "tank", "aircraft", "plane", "ship", "train", "station", "airport",
                  "resort", "camp", "border", "palace"}
_plain: set[str] | None = None


def plain_english() -> set[str]:
    """Ordinary English words (writer.english, the TTS lexicon), normalised; empty if it cannot be read."""
    global _plain
    if _plain is None:
        try:
            from .writer import english
            _plain = {norm(w) for w in english()}
        except Exception:  # the lexicon is optional: without it only CAPTION_THINGS are checked
            _plain = set()
    return _plain


def is_plain(word: str) -> bool:
    """An ordinary English word, a month or a weekday, inflected or not ("Dispersing", "Demonstrations", "September")."""
    w, plain = norm(word), plain_english()
    if w in MONTHS or w in WEEKDAYS:
        return True
    stems = {w}
    for end, subs in (("ies", ("y",)), ("es", ("", "e")), ("s", ("",)), ("ing", ("", "e")), ("ed", ("", "e")),
                      ("ers", ("", "e", "er"))):
        if w.endswith(end):
            stems |= {w[:-len(end)] + sub for sub in subs}
    return any(len(t) >= 3 and t in plain for t in stems)


def _tokens(text: str) -> list[str]:
    return [norm(w) for w in re.findall(r"[^\W\d_][\w'’-]*", text.replace("_", " "))]


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


PARTICLES = {"le", "la", "de", "del", "da", "di", "van", "von", "bin", "al", "du", "des", "der", "den", "dos", "das",
             "ter", "ten", "el", "ibn"}


def surname(name: str) -> str:
    """A full name's surname, with its particle ("Marine Le Pen" -> "Le Pen", "Emmanuel Macron" -> "Macron"); "" for
    a one-word name."""
    parts = [p for p in re.split(r"\s+", (name or "").strip()) if p]
    if len(parts) < 2:
        return ""
    if len(parts) >= 3 and norm(parts[-2]) in PARTICLES:
        return " ".join(parts[-2:])
    return parts[-1]


def person_terms(name: str) -> list[str]:
    """A person is named by their full name or their surname ("Emmanuel Macron", "Macron"). The surname alone names
    them only when no one else in the story shares it (name_hit)."""
    parts = [p for p in re.split(r"\s+", (name or "").strip()) if p]
    sur = surname(name)
    return list(dict.fromkeys([name.strip()] + ([sur] if sur else []))) if parts else []


def name_hit(text: str, full: str, rivals: set[str] | frozenset = frozenset(), strict: bool = True) -> re.Match | None:
    """Where text names the person `full`: their full name; or their surname alone, when the word before it is not
    another given name ("Rahul Gandhi" never names Indira Gandhi) and (strict) no rival, another person of the story
    by full name, shares it. Review round 2 (2026-10-23): Indira Gandhi's portrait stood under every Rahul Gandhi
    beat, the surname alone matching."""
    if m := says(text, full):
        return m
    sur = surname(full)
    if not sur or len(norm(sur)) < 4:
        return None
    nf, ns = norm(full), norm(sur)
    if strict and any(r != nf and norm(surname(r)) == ns and len(r.split()) > 1 for r in rivals):
        return None
    given = {norm(p) for p in full.split()[:-len(sur.split())]}
    low = norm(text)
    same = len(low) == len(text or "")
    for m in re.finditer(r"(?<![\w])" + re.escape(ns) + r"(?:'s|s)?(?![\w])", low):
        prev = re.search(r"([^\W\d_][\w'’.\-]*)\s+$", low[:m.start()])
        if prev:
            pw = prev.group(1).rstrip(".")
            orig = text[prev.start(1):prev.end(1)] if same else pw
            if orig[:1].isupper() and pw not in given and pw not in STOP and pw not in PARTICLES and not is_plain(pw):
                continue  # another given name: another person of the same surname
        return m
    return None


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


MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december")
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _photo_day(photo: dict):
    from . import media

    return media._day(photo.get("date") or "")


def own_window(when, category: str = "", origin: str = "", ongoing: bool = False):
    """The days a story's own photo (its Wikidata image, article or category files) must be taken on to show the event
    itself: media.window's days; for a protest or movement, its Wikidata or article image from up to two years back
    (a movement is pictured by its earlier marches). Review round 1 (2026-10-23): a stock photo of the Flydubai
    aircraft taken nine months before the hijacking was counted as the hijacking."""
    from datetime import timedelta

    from . import media

    ongoing = ongoing or category in media.ONGOING
    since, until = media.window(when, category if category in media.EVENT_WORDS else ("protest" if ongoing else ""))
    if ongoing and origin in ("wikidata", "article"):
        since = when - timedelta(days=730)
    return since, until


def legacy_kind(photo: dict, sid: str = "", short_kind: str = "", when=None, category: str = "") -> str:
    """What an unstamped photo shows, from where it was found. A report story's (nw-) Commons photos were all of the
    places and things it links to, never of the event; a tribute's own photos are the person's face-matched
    portraits. An incident's own photo is the event only when it was taken within own_window of the story's date
    (or carries no date); otherwise it shows a thing (the aircraft, the building)."""
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
        if when is None:
            return "event"  # a Short with no date (old fixtures) cannot tell; its plan was judged so before
        day = _photo_day(photo)
        # Review round 2: a photo dated only "2014" (or undated) fell through to the event. Only a full day inside
        # the window shows the event; anything else shows a thing (the aircraft, the building).
        since, until = own_window(when, category, photo.get("origin") or "", short_kind == "protest")
        if not day or not since <= day <= until:
            return "thing"
        return "event"
    return "place"


def kind_of(photo: dict, sid: str = "", short_kind: str = "", when=None, category: str = "") -> str:
    return photo.get("kind") or legacy_kind(photo, sid, short_kind, when, category)


def stamp_own(photos: list[dict], sid: str, short_kind: str, when, category: str = "") -> list[dict]:
    """Stamp a story's own photos where they are found (review round 1: the Wikidata image was left unstamped)."""
    for p in photos:
        if not p.get("kind"):
            p["kind"] = legacy_kind(p, sid, short_kind, when, category)
            p["shows"] = [] if p["kind"] in ("event", "view", "map") else legacy_terms(p, p["kind"])
    return photos


def legacy_terms(photo: dict, kind: str, subject: str = "") -> list[str]:
    if kind == "person":
        return [subject.strip()] if subject and subject.strip() else []
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
        return list(dict.fromkeys(s.strip() for s in shows))
    return legacy_terms(photo, kind, subject)


# Old and local names of the same city, read as one ("Studenti Roma" is in Rome).
EXONYMS = {"roma": "rome", "torino": "turin", "milano": "milan", "napoli": "naples", "firenze": "florence",
           "venezia": "venice", "genova": "genoa", "munchen": "munich", "koln": "cologne", "wien": "vienna",
           "praha": "prague", "warszawa": "warsaw", "lisboa": "lisbon", "athina": "athens", "moskva": "moscow",
           "kiev": "kyiv", "beograd": "belgrade", "kobenhavn": "copenhagen", "bruxelles": "brussels",
           "brussel": "brussels", "sevilla": "seville", "marseilles": "marseille", "lyons": "lyon",
           "bucuresti": "bucharest", "tirane": "tirana", "geneve": "geneva", "zvernec": "zvernec"}
CONTINENTS = {"europe", "european", "africa", "african", "asia", "asian", "america", "americas", "world", "global",
              "latin", "middle", "east", "west", "north", "south"}
# A beat about the diaspora or solidarity abroad, and a photo of it.
ABROAD = re.compile(r"\b(diaspora|abroad|overseas|worldwide|around the world|solidarity|expatriates?|emigrants?)\b",
                    re.I)
ABROAD_PHOTO = re.compile(r"\b(diaspora|solidarity|in support of|show support|abroad|exile)\b", re.I)
_NAMEW = r"[A-ZÀ-Þ][\w'’\-]+"
_PREP = r"(?i:in|at|to|from|near|across|of|outside|through|into|towards?|around)"
PLACE_RUN = re.compile(rf"\b{_PREP}\s+(?:the\s+)?({_NAMEW}(?:\s+(?:(?:of|del|de|di|la|le|du|des)\s+)?{_NAMEW})*"
                       rf"(?:\s*(?:,|\band\b)\s*(?:the\s+)?{_NAMEW}(?:\s+{_NAMEW})*)*)")
TITLES = (r"(?:President|Vice President|Prime Minister|Deputy Prime Minister|(?:[A-Z][a-z]+ )?Minister|Chancellor|"
          r"Captain|Capt\.|First Officer|Mayor|Governor|Senator|Congressman|Congresswoman|General|Colonel|Commander|"
          r"Judge|Justice|Pope|King|Queen|Prince|Princess|Sheikh|Emir|Sultan|Commissioner|Secretary|Ambassador|"
          r"Dr\.?|Mr\.?|Mrs\.?|Ms\.?|activist|investor|journalist|businessman|businesswoman|tycoon|billionaire|"
          r"lawyer|spokesperson|spokesman|spokeswoman|student|teacher|pilot|officer|photographer|reporter|singer|"
          r"actor|actress|footballer|coach|founder|CEO|leader|opposition leader|resident|grandmother|grandfather)")
_PERSON = rf"({_NAMEW}(?:\s+(?:(?:del|de|da|di|van|von|bin|al|la|le)\s+)?{_NAMEW}){{0,3}})"
TITLED = re.compile(rf"\b{TITLES}\s+{_PERSON}")
AGED = re.compile(rf"\b\d+-year-old\s+(?:[a-z]+\s+){{0,2}}{_PERSON}")


def place_word(word: str) -> str:
    w = re.sub(r"'s$", "", norm(word))
    return EXONYMS.get(w, w)


def _countries() -> set[str]:
    from . import media

    out = set(CONTINENTS)
    for k, v in media.DEMONYMS.items():
        out.add(k)
        out.update(x for x in v if " " not in x)
        out.update(x.split()[-1] for x in v if " " in x)
    return out


def places_in(text: str) -> set[str]:
    """The places a beat names: capitalised words after in, at, to, from, near, across, of ... ("In Rome",
    "shifted to Zvërnec", "in Milan and Bologna"), not months, weekdays or plain English words."""
    out = set()
    for m in PLACE_RUN.finditer(text or ""):
        for w in re.findall(_NAMEW, m.group(1)):
            n = norm(w)
            if n in STOP or n in MONTHS or n in WEEKDAYS or _ordinary(n):
                continue
            out.add(place_word(w))
    return out


def titled_names(text: str) -> list[str]:
    """People a beat names by a title or an age ("Captain Smit Machchhar", "investor Jared Kushner", "87-year-old
    María del Carmen Abascal"), whether or not they have a Wikipedia article."""
    out = []
    for m in list(TITLED.finditer(text or "")) + list(AGED.finditer(text or "")):
        name = re.sub(r"['’]s$", "", m.group(1)).strip()
        last = norm(name.split()[-1])
        if _ordinary(last) or last in MONTHS or last in WEEKDAYS:
            continue
        out.append(name)
    return list(dict.fromkeys(out))


_M = "|".join(MONTHS)
BEAT_DAY = re.compile(rf"\b(?:(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_M})|({_M})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b)"
                      rf"(?:,?\s+(\d{{4}}))?", re.I)
BEAT_MONTH = re.compile(rf"\b({_M})\b(?:\s+(\d{{4}}))?", re.I)


def beat_dates(text: str) -> tuple[list[tuple], list[tuple]]:
    """The days ((year or None, month, day)) and months ((year or None, month)) a beat says, not those in a name
    ("the 17 October Movement") or after "since"."""
    text = text or ""
    days, months, spans = [], [], []
    for m in BEAT_DAY.finditer(text):
        spans.append(m.span())
        if re.match(r"\s+[A-Z]", text[m.end():]) or re.search(r"\bsince\s+$", text[:m.start()], re.I):
            continue
        d, mon = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
        days.append((int(m.group(5)) if m.group(5) else None, MONTHS.index(mon.lower()) + 1, int(d)))
    for m in BEAT_MONTH.finditer(text):
        if any(a <= m.start() < b for a, b in spans) or not text[m.start()].isupper():
            continue
        if re.match(r"\s+[A-Z]", text[m.end():]) or re.search(r"\bsince\s+$", text[:m.start()], re.I):
            continue
        months.append((int(m.group(2)) if m.group(2) else None, MONTHS.index(m.group(1).lower()) + 1))
    return days, months


# What a beat and a picture's own words (file name, description, categories) must share for an event photo to show
# the beat, and for a caption card to stand over a photo (review round 2, 2026-10-23: "teacher shortages and
# overcrowded classrooms" and the card "Government accusations" stood over a smoking church with no one in it, and
# counted as shown only because nothing contradicted it). Words of one family are read as one.
FUNCTION = {"about", "above", "across", "after", "again", "against", "also", "among", "around", "because", "been",
            "before", "began", "being", "between", "both", "called", "came", "could", "during", "each", "even",
            "every", "first", "from", "further", "have", "having", "here", "including", "into", "just", "last",
            "later", "like", "made", "make", "many", "more", "most", "much", "must", "near", "next", "only", "other",
            "over", "part", "people", "said", "same", "says", "should", "since", "some", "still", "such", "than",
            "that", "their", "them", "then", "there", "these", "they", "this", "those", "through", "told", "took",
            "under", "until", "upon", "very", "were", "what", "when", "where", "which", "while", "will", "with",
            "within", "without", "would", "year", "years", "week", "weeks", "today", "yesterday", "tomorrow",
            "night", "morning", "evening", "day", "days", "month", "months", "time", "times", "photo", "photograph",
            "file", "image", "jpeg", "view", "according", "several", "thousands", "hundreds", "dozens", "million",
            "millions", "half", "whole", "entire", "across", "another", "among", "began", "become", "became",
            "remain", "remains", "continue", "continued", "continues", "following", "number", "numbers", "least",
            "nearly", "almost", "around", "high", "large", "small", "major", "many", "new", "long", "full", "big"}
FAMILIES = {
    "crowd": ("protest", "demonstrat", "march", "rally", "ralli", "gather", "crowd", "strike", "striking", "blockad",
              "block", "manifest", "unrest", "riot", "clash", "mobilis", "mobiliz", "walkout", "sit-in", "placard",
              "banner", "chant", "occupation", "occupi", "revolution", "uprising", "movement",
              "mouvement", "manif", "sciopero", "huelga", "greve"),
    "police": ("police", "polizia", "policier", "gendarm", "officer", "cop", "tear gas", "teargas", "water cannon",
               "cannon", "baton", "carabinier", "guardia"),
    "fire": ("fire", "smoke", "burn", "blaze", "flame", "torch", "arson", "ablaze", "incendi"),
    "student": ("student", "pupil", "lycee", "lyceen", "school", "universit", "college", "teen"),
    "shop": ("shop", "store", "loot", "smash", "window", "vandal", "storefront", "shopfront"),
    "storm": ("storm", "hurrican", "cyclon", "typhoon", "landfall", "gale"),
    "flood": ("flood", "inundat", "submerg", "deluge"),
    "quake": ("earthquak", "quake", "tremor", "seism"),
    "eruption": ("erupt", "volcan", "lava", "ash"),
    "vehicle": ("vehicle", "car", "cars", "truck", "lorr"),
    "rail": ("train", "rail", "coach", "carriage", "locomotiv", "station", "track", "derail", "express", "platform",
             "wagon", "metro"),
    "air": ("aircraft", "plane", "airplane", "aeroplane", "airliner", "flight", "jet", "airport", "runway",
            "airline", "airway", "boeing", "airbus", "helicopter"),
    "sea": ("ship", "vessel", "ferr", "boat", "harbo", "port", "dock", "sank", "sink", "capsiz", "shipwreck"),
}


def _stem(w: str) -> str:
    for end in ("ations", "ation", "ings", "ing", "ers", "ed", "es", "s", "er"):
        if w.endswith(end) and len(w) - len(end) >= 4:
            return w[:-len(end)]
    return w


def content(text: str) -> set[str]:
    """The content words of a text, stemmed, a word of a family (FAMILIES) read as the family, without function
    words, months, weekdays, countries or particles."""
    low = norm(text).replace("_", " ")
    out = {fam for fam, stems in FAMILIES.items() for st in stems if " " in st and st in low}
    countries = _countries()
    for w in re.findall(r"[^\W\d_]+", low):
        if len(w) < 4 or w in FUNCTION or w in STOP or w in MONTHS or w in WEEKDAYS or w in countries:
            continue
        st = _stem(w)
        fam = next((f for f, stems in FAMILIES.items() for p in stems if " " not in p and
                    (w.startswith(p) if len(p) >= 4 else w in (p, p + "s"))), None)
        out.add(fam or EXONYMS.get(st, st))
    return out


class Story:
    """A Short's photos as anchors: who or what each shows, and which stand under any beat about the event.

    subject: the story's name (a person for a tribute). people: people the reporting names, with or without a free
    photo of their own; a beat naming one without a photo has nothing to show (a protest photo under "Trump said ..."
    shows neither Trump nor what he said). when, category: the story's date and kind of event, for the days its own
    photos may be from (own_window).

    Review round 1 (2026-10-23): an event photo no longer fits any beat that names nobody. It carries where it was
    taken (its file name, description and categories) and when; a beat naming another place or another day does not
    show it ("In Rome" over a Turin march). A place photo anchors a beat only by a name no other photo shares, no
    country and no word half the script says ("Madrid" under the Prime Minister's beat). A beat naming someone
    without a photo is never shown, whatever place it also names. No photo stands under more than its share of beats
    (most)."""

    def __init__(self, photos: list[dict], subject: str = "", people: list[str] | None = None, sid: str = "",
                 short_kind: str = "", when=None, category: str = ""):
        self.photos = photos
        self.subject = subject or ""
        self.kinds = [kind_of(p, sid, short_kind, when, category) for p in photos]
        self.terms = [terms_of(p, k, self.subject) for p, k in zip(photos, self.kinds)]
        self.texts = [" ".join([p.get("file") or "", p.get("description") or ""] + list(p.get("categories") or []))
                      for p in photos]
        events = [i for i, k in enumerate(self.kinds) if k in ("event", "view")]
        self.short_kind, self.category = short_kind, category or ""
        # The pictures a beat about the story itself stands on: the event's own photos; for a tribute, the person's
        # face-matched portraits. Review round 2 (2026-10-23): a portrait is never the default of a news story (the
        # Macron protest ban passed with his face under "half a million people gathered"); it stands only under a
        # beat that names its person.
        own = [i for i, k in enumerate(self.kinds) if k == "person"] \
            if short_kind == "death" or not (short_kind or self.subject) else []
        self.defaults = set(events) or set(own)
        self.people = list(people or [])
        self.fulls = [list(self.terms[i]) if k == "person" else [] for i, k in enumerate(self.kinds)]
        self._base_rivals = {norm(n) for n in [t for f in self.fulls for t in f] + self.people
                             if len(n.split()) > 1}
        self.rivals = set(self._base_rivals)
        self._base_unshown = [p for p in self.people if not self.is_shown(p)]
        self.unshown = list(self._base_unshown)
        self.days = [_photo_day(p) if k == "event" else None for p, k in zip(photos, self.kinds)]
        self.where = [self._where(i) if k == "event" else set() for i, k in enumerate(self.kinds)]
        self.abroad = [k == "event" and bool(ABROAD_PHOTO.search(self.texts[i])) for i, k in enumerate(self.kinds)]
        subject_words = {place_word(w) for w in re.findall(r"[^\W\d_]{3,}", self.subject)}
        people_words = {place_word(w) for p in self.people for w in p.split()} | \
            {place_word(w) for i, k in enumerate(self.kinds) if k == "person" for t in self.terms[i] for w in t.split()}
        self._base_broad = _countries() | subject_words | people_words
        self.broad = set(self._base_broad)
        self.anchorable = [list(t) for t in self.terms]
        self.words = [content(" ".join([self.texts[i]] + list(self.terms[i]))) for i in range(len(photos))]
        self.own_places = [{place_word(w) for w in re.findall(r"[^\W\d_]+", norm(self.texts[i]).replace("_", " "))}
                           for i in range(len(photos))]
        self.located = [set() for _ in photos]
        self._prepared = None

    def _where(self, i: int) -> set[str]:
        text = re.sub(r"^File:|\.\w+$", " ", self.photos[i].get("file") or "").replace("_", " ")
        text = " ".join([text, self.photos[i].get("description") or ""] + list(self.photos[i].get("categories") or []))
        return {place_word(w) for w in distinct(text) if norm(w) not in MONTHS and norm(w) not in WEEKDAYS}

    def is_shown(self, name: str) -> bool:
        """A person a photo shows: by their full name, or by a surname no other person of the story shares."""
        return any(norm(name) == norm(f) or name_hit(name, f, self.rivals) for fs in self.fulls for f in fs)

    def hits(self, text: str, i: int) -> list[re.Match]:
        """Where text names photo i: a person by name_hit, a place by its anchorable names, a thing by its own."""
        k = self.kinds[i]
        if k == "person":
            return [m for t in self.terms[i] if (m := name_hit(text, t, self.rivals))]
        terms = self.anchorable[i] if k in ("place", "setting") else self.terms[i]
        return [m for t in terms if (m := says(text, t))]

    # -- the script as a whole ----------------------------------------------------------------------------------
    def prepare(self, texts: list[str]) -> None:
        """Read the whole script once: people it names by a title or age (unshown when they have no photo), the
        places half the script says (broad: they never tell one photo from another), and the place photos' own names
        (anchorable: no other photo, no country, no common word)."""
        key = tuple(texts)
        if key == self._prepared:
            return
        self._prepared = key
        titled = [n for t in texts for n in titled_names(t)]
        self.rivals = self._base_rivals | {norm(n) for n in titled if len(n.split()) > 1}
        self._base_unshown = [p for p in self.people if not self.is_shown(p)]
        extra = [n for n in titled if not self.is_shown(n)
                 and not (self.subject and (says(self.subject, n) or says(n, self.subject)))]
        self.unshown = list(dict.fromkeys(self._base_unshown + extra))
        beat_places = [places_in(t) for t in texts]
        common = {w for w in set().union(*beat_places) if 2 * sum(w in b for b in beat_places) > len(texts)} \
            if len(texts) >= 3 else set()
        titled_words = {place_word(w) for n in self.unshown for w in n.split()}
        self.broad = self._base_broad | common | titled_words
        # Where an event photo was taken, among the places the script says or a known city: a word of its caption
        # that is no place ("Sher Shah station") never contradicts a beat.
        known = set().union(*beat_places) | set(EXONYMS) | set(EXONYMS.values()) if beat_places else set(EXONYMS)
        self.located = [(w - self.broad) & known for w in self.where]
        said = {norm(t) for t in set(t for ts in self.terms for t in ts)
                if len(texts) >= 3 and 3 * sum(bool(says(x, t)) for x in texts) > len(texts)}
        for i, k in enumerate(self.kinds):
            if k not in ("place", "setting"):
                continue
            keep = []
            for t in self.terms[i]:
                n = norm(t)
                shared = any(j != i and self.terms[j] != self.terms[i] and n in {norm(x) for x in self.terms[j]}
                             for j in range(len(self.terms)))
                if shared or n in said or all(place_word(w) in self.broad for w in t.split()):
                    continue
                keep.append(t)
            self.anchorable[i] = keep

    def _ready(self, text: str) -> None:
        if self._prepared is None:
            self.prepare([text])

    def most(self, beats: int) -> int:
        """How many beats one photo may stand under: the writer's rule (at most `most` times)."""
        real = sum(k != "map" for k in self.kinds) or 1
        return max(2, -(-beats // real))

    # -- what a beat names --------------------------------------------------------------------------------------
    def named(self, text: str) -> list[int]:
        """Photos (not maps) whose names the text says, in the order it says them. A place photo is named only by
        its anchorable names."""
        self._ready(text)
        hits = []
        for i, k in enumerate(self.kinds):
            if k == "map":
                continue
            at = [m.start() for m in self.hits(text, i)]
            if at:
                hits.append((min(at), i))
        return [i for _, i in sorted(hits)]

    def faceless_names(self, text: str) -> list[str]:
        """People the text names who have no free photo of their own."""
        self._ready(text)
        return [p for p in self.unshown if name_hit(text, p, self.rivals, strict=False)]

    def title_faceless(self, title: str) -> list[str]:
        """People the title names who have no free photo (titled or not): the Short would promise a face it never
        shows ("The Courage of Captain Machchhar")."""
        return list(dict.fromkeys(self.faceless_names(title) + [
            n for n in titled_names(title) if not self.is_shown(n)
            and not (self.subject and (says(self.subject, n) or says(n, self.subject)))]))

    def word(self, text: str, i: int) -> str:
        """The word in text that names photo i (where compose cuts to it), "" for a photo shown by default."""
        found = self.hits(text, i)
        if not found:
            return ""
        m = min(found, key=lambda m: m.start())
        return text_at(text, m)

    def dates_fit(self, text: str, i: int) -> bool:
        """An event photo's day against the days and months the beat says: a day within one day of it, a month its
        own (and the year, if said)."""
        day = self.days[i] if 0 <= i < len(self.days) else None
        if not day:
            return True
        from datetime import date

        days, months = beat_dates(text)
        for y, mon, d in days:
            try:
                said = date(y or day.year, mon, d)
            except ValueError:
                continue
            if abs((said - day).days) > 1:
                return False
        return all(mon == day.month and (not y or y == day.year) for y, mon in months)

    def placed(self, text: str, i: int) -> bool:
        """An event photo the beat places: it names where the photo was taken, or tells the diaspora over a photo of
        it."""
        if self.kinds[i] != "event":
            return False
        if self.abroad[i] and ABROAD.search(text or ""):
            return True
        return bool((places_in(text) - self.broad) & self.where[i])

    def event_fits(self, text: str, i: int) -> bool:
        if self.kinds[i] != "event":
            return True
        if not self.dates_fit(text, i):
            return False
        places = places_in(text) - self.broad
        if self.abroad[i]:
            return bool(places & self.where[i]) or bool(ABROAD.search(text or ""))
        if ABROAD.search(text or "") and any(self.abroad):
            return bool(places & self.where[i])
        return not places or bool(places & self.where[i]) or not self.located[i]

    def fits(self, text: str, i: int, first: bool = False) -> bool:
        """Photo i shows what the beat says: the beat names it (a place photo by its own name, under a beat naming
        no person or thing); or it is a picture of the event (or of the person a tribute is about), the beat names
        nobody else who has a picture, and no place or day the beat says is not the photo's; or it is the map and
        the beat's point is where it happened (map_fits). A beat naming someone without a photo is shown only by a
        person it names who has one."""
        if not 0 <= i < len(self.photos):
            return False
        self._ready(text)
        kind = self.kinds[i]
        if kind == "map":
            return not first and self.map_fits(text, i)
        if kind == "setting" and first:
            return False
        named = self.named(text)
        if self.faceless_names(text):
            return kind == "person" and i in named
        if i in named:
            if kind in ("place", "setting"):
                return not any(self.kinds[j] in ("person", "thing") for j in named if j != i)
            if kind == "thing":
                return self.thing_placed(text, i)
            return True
        if i not in self.defaults:
            return False
        # A thing the event photo itself shows ("Police in riot gear face protesters") is no one else's.
        others = [j for j in named if self.kinds[j] in ("person", "thing") and j not in self.defaults
                  and not (self.kinds[j] == "thing" and any(says(self.texts[i], t) for t in self.terms[j]))]
        return not others and self.event_fits(text, i) and self.about(text, i)

    def about(self, text: str, i: int) -> bool:
        """The beat says something photo i's own words say (content): an event photo of a march under a beat about
        the march, not under "the government accused the far-left" (review round 2). A tribute's portrait stands
        under any beat about the person."""
        if self.kinds[i] == "person" or self.kinds[i] == "view":
            return True
        return bool(content(text) & self.words[i])

    def thing_placed(self, text: str, i: int) -> bool:
        """A stock photo of a thing under a beat naming a place shows that place too: a school in Cantal never stands
        for a high school in French Guiana (review round 2). The beat's own places (a country only when it names no
        town or region) must be in the photo's words."""
        said = {p for p in places_in(text) if p not in CONTINENTS}
        if not said:
            return True
        from . import media

        countries = _countries()
        country_of = {k: v[0] for k, v in media.DEMONYMS.items()}
        local = {p for p in said if p not in countries}
        if local:
            return bool(local & self.own_places[i])
        nations = {country_of.get(p, p) for p in said}
        return bool((nations | said) & self.own_places[i])

    def map_fits(self, text: str, i: int) -> bool:
        """A map under a beat that names its place and names no person or thing (with a picture or without)."""
        if not any(says(text, t) for t in self.terms[i]):
            return False
        named = self.named(text)
        return not any(self.kinds[j] in ("person", "thing") for j in named) and not self.faceless_names(text)

    # -- choosing each beat's picture -----------------------------------------------------------------------
    def assign(self, texts: list[str], chosen: list[int] | None = None) -> list[tuple[int, str]]:
        """(photo, naming word) for each beat, decided by code: a photo the beat names (first named first; an event
        photo that itself shows the thing named before a stock photo of it), else an event photo the beat places,
        else the least-used picture of the event that fits, else the map when the beat is about where, else the
        writer's choice (then unanchored, and the checks send the script back). No photo past `most` beats while
        another fits; a SETTING photo on one beat, never beat 1; the same photo twice in a row only when nothing
        else fits."""
        self.prepare(texts)
        chosen = list(chosen or [])
        most = self.most(len(texts))
        weights = [max(len(t.split()), 1) for t in texts]
        total = sum(weights) or 1
        uses: dict[int, int] = {}
        map_words = 0
        maps_used: set[int] = set()
        out: list[tuple[int, str]] = []
        for k, text in enumerate(texts):
            prev = out[-1][0] if out else None
            first = k == 0
            named = [i for i in self.named(text) if self.fits(text, i, first)]
            placed = [i for i in sorted(self.defaults) if i not in named and self.placed(text, i)
                      and self.fits(text, i, first)]
            rest = [i for i in sorted(self.defaults, key=lambda i: (uses.get(i, 0), i))
                    if i not in named and i not in placed and self.fits(text, i, first)]
            things = [i for i in named if self.kinds[i] == "thing"]
            if things:  # the event's own photo of the police beats a stock police car
                better = [i for i in placed + rest
                          if any(says(self.texts[i], t) for j in things for t in self.terms[j])]
                named = better + [i for i in named if i not in better and not (better and i in things)]
            top = [i for i in named + placed if not (self.kinds[i] == "setting" and uses.get(i))]
            rest = [i for i in rest if not (self.kinds[i] == "setting" and uses.get(i))]
            fit = top + rest
            under = [i for i in fit if uses.get(i, 0) < most]
            top = [i for i in top if i in under] or ([] if under else top)
            rest = [i for i in rest if i in under] or ([] if under else rest)
            mine = chosen[k] if k < len(chosen) else None
            pick = None
            pool = top or rest
            if pool:
                if mine in pool and (mine != prev or len(pool) == 1):
                    pick = mine
                else:
                    free = [i for i in pool if i != prev] or pool
                    pick = free[0] if top else min(free, key=lambda i: (uses.get(i, 0), free.index(i)))
            else:
                maps = [i for i, kd in enumerate(self.kinds) if kd == "map" and self.fits(text, i, first)]
                maps = [i for i in maps if (not maps_used or i in maps_used) and len(maps_used | {i}) <= MAX_MAPS
                        and (map_words + weights[k]) / total <= MAP_SHARE]
                if maps:
                    pick = maps[0]
                    maps_used.add(pick)
                    map_words += weights[k]
            if pick is None:
                # Nothing shows this beat (the checks send it back): stand it on the least-used real photo, so it
                # never spends the use of a photo another beat names.
                real = [i for i, kd in enumerate(self.kinds) if kd != "map"] or [0]
                pick = mine if mine is not None and 0 <= mine < len(self.photos) and self.kinds[mine] != "map" \
                    and uses.get(mine, 0) == 0 and not any(self.fits(t, mine) for t in texts[k + 1:]) \
                    else min(real, key=lambda i: (uses.get(i, 0) + sum(self.fits(t, i) for t in texts[k + 1:]),
                                                  i == prev, i))
            uses[pick] = uses.get(pick, 0) + 1
            out.append((pick, self.word(text, pick)))
        return out

    # -- judging a plan ---------------------------------------------------------------------------------------
    def caption_fits(self, caption: str, i: int) -> bool:
        """A caption card may not claim what photo i does not show: "Map of Albania" over a rally, "Military
        deployment" over a march, "Baks-Rrjoll Protests" over Tirana (review round 1). A word naming a thing that is
        pictured (map, police, military, ...) or a name (a word not in plain English) must be in the photo's own words."""
        if not 0 <= i < len(self.photos):
            return False
        own = set(_tokens(" ".join([self.texts[i]] + list(self.terms[i]) + [self.kinds[i]])))
        for word in re.findall(r"[^\W\d_][\w'’-]*", caption or ""):
            w = norm(word)
            pictured = w.rstrip("s") in CAPTION_THINGS or w in CAPTION_THINGS
            named = word[:1].isupper() and not is_plain(word) and w not in self.broad
            if (pictured or named) and w not in own and w.rstrip("s") not in own:
                return False
        # Review round 2: "High school blockades" over a stock village school, "6,800 arrests" over a parked police
        # car, "Government accusations" over a smoking church. Over anything but the person's own portrait, every
        # content word of a card is in the photo's own words.
        if self.kinds[i] != "person" and content(caption or "") - self.words[i]:
            return False
        return True

    def judge(self, texts: list[str], shots: list[int], weights: list[float] | None = None) -> dict:
        """How a plan (each beat's photo) shows what it says: the share of picture time on photos that show what the
        beat names ("shown"), on maps ("maps"), the beats that show something else ("unanchored": also a photo's
        beats past `most`), the maps on a beat that is not about where ("bad_maps"), and the different maps used."""
        self.prepare(texts)
        weights = weights or [max(len(t.split()), 1) for t in texts]
        total = sum(weights) or 1
        most = self.most(len(texts))
        shown = maps = 0.0
        uses: dict[int, int] = {}
        unanchored, bad_maps, used_maps = [], [], set()
        for k, (text, i, w) in enumerate(zip(texts, shots, weights)):
            ok = self.fits(text, i, k == 0)
            if 0 <= i < len(self.kinds) and self.kinds[i] == "map":
                maps += w
                used_maps.add(i)
                if not ok:
                    bad_maps.append(k)
                continue
            uses[i] = uses.get(i, 0) + 1
            if ok and uses[i] <= most:
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
        """The story's own subject has a real picture: the person a tribute is about; for any other story, a photo of
        the event itself (review round 2: the Macron protest ban re-made over his portrait, a stock police car and a
        stock school passed with no picture of the protests). A rail, air or sea incident may instead show the
        vehicle it is named after (gate.SHOWS, which also counts those photos)."""
        if kind == "death":
            return any(k == "person" for k in self.kinds)
        if any(k in ("event", "view") for k in self.kinds):
            return True
        from . import gate

        if self.category not in gate.SHOWS:
            return False
        return any(k in ("thing", "place") and gate.showing(self.category, [self.photos[i]])
                   for i, k in enumerate(self.kinds))


def text_at(text: str, m: re.Match) -> str:
    """The original-cased word of text at a match made on norm(text) (same length: norm keeps one char per char
    for Latin text; falls back to the normalised word)."""
    word = text[m.start():m.end()] if len(norm(text)) == len(text) else m.group(0)
    return word.split()[0] if word.split() else word


def story_of(short) -> Story:
    """The Story of a Short: its photos, subject and the people its reporting names (scene)."""
    scene = short.scene
    subject = (scene.get("subject") or {}).get("name") or next((f.value for f in short.facts if f.key == "name"), "")
    from datetime import date

    from . import media

    try:
        when = date.fromisoformat((short.event_time or "")[:10])
    except (TypeError, ValueError):
        when = None
    category = scene.get("category") or next((t for t in (short.tags or [])[1:2] if t in media.EVENT_WORDS), "")
    return Story(scene.get("photos") or [], subject, [p["name"] for p in scene.get("people") or []], short.id,
                 short.kind, when, category)
