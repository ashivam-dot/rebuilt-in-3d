"""The checks a Short must pass before it can publish: grounded numbers, decorum, title rules, disclosure, and two
independent owners behind any fact taken from trusted outlets' reporting (studio/outlets.py)."""
from __future__ import annotations

import re
from pathlib import Path

from .spec import Short

STAGE = Path(__file__).resolve().parent / "web" / "stage.html"
DISCLOSURE = "3D RECONSTRUCTION FROM DATA · NOT REAL FOOTAGE"
# Gore, sensationalism and clickbait never appear in a title, a card or the narration. A trailing * matches any
# ending ("decapitat*" also catches decapitated); everything else matches whole words only (so "gory" never trips on
# "category", nor "rip" on "trip").
BANNED = [
    "blood", "bloody", "gore", "gory", "graphic", "corpse", "corpses", "body bag", "bodies", "dismember*", "decapitat*",
    "mutilat*", "charred", "burned alive", "horrific", "horrifying", "gruesome", "shocking", "terrifying", "nightmare",
    "massacre", "slaughter", "carnage", "apocalyp*", "armageddon", "doomed", "you won't believe", "insane", "breaking",
    "must watch", "watch till the end", "omg", "wtf", "rip", "sexy", "nude", "naked", "porn", "kill count",
]
# Titles of works and names that contain a banned word; written exactly so, they are a name, not wording.
NAMED = ("Breaking Bad", "Breaking Dawn", "Breaking Benjamin", "A Nightmare on Elm Street",
         "The Nightmare Before Christmas", "There Will Be Blood", "True Blood", "Blood Diamond", "Insane Clown Posse")


def banned_word(text: str) -> str | None:
    """The first banned word in text (see BANNED), ignoring the names in NAMED."""
    for name in NAMED:
        text = text.replace(name, " ")
    low = text.lower().replace("’", "'")
    for w in BANNED:
        tail = "" if w.endswith("*") else r"(?![a-z])"
        if re.search(r"(?<![a-z])" + re.escape(w.rstrip("*")) + tail, low):
            return w.rstrip("*")
    return None
ACRONYMS = {"USGS", "UTC", "PAGER", "NASA", "NOAA", "GDACS", "EMSC", "ADS-B", "NTSB", "AAIB", "BEA", "MMI", "ICAO",
            "IATA", "UN", "WHO", "EU", "UK", "US", "USA", "3D", "NHC", "JTWC", "IMD", "JMA", "PTWC", "GREEN", "YELLOW",
            "ORANGE", "RED"}
# Without a death toll that two sources agree on, an incident Short may not speak of casualties at all.
CASUALTY = re.compile(r"\b(casualt\w*|death toll|killed|fatalit\w*|wounded|injured)\b", re.I)
NUMBER = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?::\d{2})?(?:\.\d+)?)(?![\w])")
EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\U0001F000-\U0001F2FF]")
# Outlet reporting (studio/outlets.py) backs a fact only when this many independent owners state it; a fact only one
# outlet reports is never said.
OWNERS_NEEDED = 2
# Real photos a story Short needs (2026-10-14: two for an incident, beats reuse them with other camera moves); a
# tribute keeps three, at least one of them the person's matched face.
MIN_PHOTOS, TRIBUTE_PHOTOS = 2, 3
# Photos of the town it happened in, not of what happened (studio/media.py role "setting"), a Short may carry: a train
# derailment once went out over a church, a shrine and a clock tower and no train at all (2026-10-14).
MAX_SETTING = 1
# Locator maps (studio/locator.py: OpenStreetMap, the site marked) a Short may carry: one, under a beat about where it
# happened, for at most a fifth of the picture time (anchor.MAP_SHARE). Until 2026-10-22 it was two, and Shorts went
# out over 88% maps ("do you think people are here to watch the map").
MAX_MAPS = 1
# Photos of who or what the story is about (not a map, not the town) a Short needs.
REAL_PHOTOS = 3
# Owner, 2026-10-22, of the Nagqu quake (55 s of empty terrain, no town, no people): quake Shorts are held
# until they show the place and the people, not only the ground.
QUAKES_HELD = True
# Pictures a Short needs, each on its own beat (2026-10-23): fewer is under 20 seconds.
MIN_BEATS = 4
# What a transport incident's photos must show (file name or Commons description): the vehicle, its line, or the
# station, airport or port. A railway's headquarters or a sign board shows none of them.
SHOWS = {
    "rail": re.compile(r"\b(trains?|railways?|rail|locomotives?|express|stations?|coach(es)?|carriages?|wagons?|"
                       r"tracks?|metro|platforms?)\b", re.I),
    "aviation": re.compile(r"\b(aircraft|airplanes?|aeroplanes?|airliners?|planes?|jets?|boeing|airbus|embraer|atr|"
                           r"helicopters?|airports?|runways?|terminals?|airlines?|airways)\b", re.I),
    "maritime": re.compile(r"\b(ships?|vessels?|ferr(y|ies)|boats?|ports?|harbou?rs?|docks?|jetty|piers?)\b", re.I),
}
NOT_SHOWN = re.compile(r"\b(headquarters|offices?|board|signs?|signboard|tickets?|logo|map)\b", re.I)
SHOWN_NEEDED = 2


def showing(category: str | None, photos: list[dict]) -> int:
    """How many photos show what a rail, air or sea incident involved (SHOWS); 0 for other categories."""
    pattern = SHOWS.get(category or "")
    if not pattern:
        return 0
    return sum(bool(pattern.search(text)) and not NOT_SHOWN.search(text)
               for text in (f"{p.get('file', '')} {p.get('description', '')}" for p in photos))
_N = r"\d{1,3}(?:,\d{3})+|\d+"
_HEDGE = r"(?P<hedge>(?:at least|more than|over|nearly|about|around|up to|some|almost|roughly)\s+)?"
TOLLS = [
    re.compile(rf"(?<![\w.,]){_HEDGE}(?P<n>{_N})\s+(?:[A-Za-z-]+\s+){{0,3}}?(?:killed|dead|died|lost their lives)\b",
               re.I),
    re.compile(rf"\b(?:death toll|toll)\s+(?:[A-Za-z-]+\s+){{0,3}}?{_HEDGE}(?P<n>{_N})\b", re.I),
    re.compile(rf"\b(?:killing|killed)\s+{_HEDGE}(?P<n>{_N})\s+(?:people|persons|passengers|civilians|workers)\b",
               re.I),
]
# A hedge written after the number ("12 or more killed", "12 feared dead") is not exact either.
_HEDGE_AFTER = re.compile(r"\b(?:or more|or so|plus|feared|presumed|believed|reportedly)\b|\+", re.I)


def numbers(text: str) -> list[str]:
    text = re.sub(r"\b3D\b", "", text)
    text = re.sub(r"\bM(?=\d)", "", text)
    return [m.group(1).replace(",", "") for m in NUMBER.finditer(text)]


def reported(needle: str, reports: list[dict]) -> list[str]:
    """The independent owners whose articles write needle (whole words, any case)."""
    pattern = re.compile(r"(?<![\w])" + re.escape(needle.lower()) + r"(?![\w])")
    return sorted({r["owner"] for r in reports if r.get("text") and pattern.search(r["text"].lower())})


def reported_values(reports: list[dict]) -> dict[str, list[str]]:
    """Every number the reports state (written without thousands separators) -> the owners stating it."""
    by: dict[str, set[str]] = {}
    for r in reports:
        for v in numbers(r.get("text") or ""):
            by.setdefault(v, set()).add(r["owner"])
    return {v: sorted(o) for v, o in by.items()}


def corroborated_values(reports: list[dict]) -> set[str]:
    """Numbers at least OWNERS_NEEDED independent owners state."""
    return {v for v, o in reported_values(reports).items() if len(o) >= OWNERS_NEEDED}


def reported_tolls(reports: list[dict]) -> dict[str, set[int]]:
    """owner -> the exact death tolls its articles state ("12 people were killed"); hedged counts ("at least 12")
    are not exact and are left out."""
    by: dict[str, set[int]] = {}
    for r in reports:
        body = r.get("text") or ""
        for pattern in TOLLS:
            for m in pattern.finditer(body):
                n = int(m.group("n").replace(",", ""))
                if m.group("hedge") or _HEDGE_AFTER.search(body[m.end("n"):m.end() + 12]):
                    n = -1  # a hedged count: no exact toll may be said beside it
                by.setdefault(r["owner"], set()).add(n)
    return by


def reported_toll(reports: list[dict], wikidata: set[int] | None = None) -> tuple[int, list[str]] | None:
    """A death toll the reporting agrees on, with the owners stating it: two independent owners give the same exact
    number (or one does and Wikidata's only toll is that number), no outlet gives a different or hedged one (a rising
    toll is not said), and Wikidata, when it has a toll, agrees. None otherwise."""
    by = reported_tolls(reports)
    stated = {n for ns in by.values() for n in ns}
    if len(stated) != 1:
        return None
    n = stated.pop()
    who = sorted(o for o, ns in by.items() if n in ns)
    if wikidata and n not in wikidata:
        return None
    if len(who) >= OWNERS_NEEDED or (who and wikidata == {n}):
        return n, who
    return None


def narration_problems(text: str) -> list[str]:
    """The same spoken-length contract applies while drafting and before publishing."""
    words = len(text.split())
    return [] if 50 <= words <= 200 else [f"narration: {words} words (want 50-200)"]


def check(short: Short) -> list[str]:
    problems = []
    if short.kind == "quake" and QUAKES_HELD:
        problems.append("quake: held; a Short of terrain alone shows no town and no people")
    allowed = {n.replace(",", "") for f in short.facts for n in f.numbers}
    texts = [("title", short.title)] + [(f"beat {i + 1}", b.text) for i, b in enumerate(short.beats)]
    for i, b in enumerate(short.beats):
        if b.card:
            texts.append((f"card {i + 1}", f"{b.card.get('big', '')} {b.card.get('small', '')}"))
    if short.scene.get("hook"):
        texts.append(("hook", short.scene["hook"]))
    for where, text in texts:
        for num in numbers(text.replace("≈", "")):
            if num not in allowed:
                problems.append(f"{where}: the number {num} isn't backed by any sourced fact")
        word = banned_word(text)
        if word:
            problems.append(f"{where}: banned wording {word!r}")
        if EMOJI.search(text):
            problems.append(f"{where}: emoji")
        if short.kind == "incident" and not any(f.key == "deaths" for f in short.facts) and CASUALTY.search(text):
            problems.append(f"{where}: casualties without an agreed toll ({CASUALTY.search(text).group(0)})")
    for word in re.findall(r"\b[A-Z][A-Z\-]{3,}\b", short.title):
        if word not in ACRONYMS:
            problems.append(f"title: shouting in capitals ({word})")
    if not 20 <= len(short.title) <= 70:
        problems.append(f"title: {len(short.title)} characters (want 20-70)")
    problems += narration_problems(short.narration)
    if not short.sources or any(not s.startswith("https://") for s in short.sources):
        problems.append("sources: every Short needs https primary sources")
    if short.scene.get("template") == "story":
        problems += _story(short)
    elif DISCLOSURE not in STAGE.read_text(encoding="utf-8"):
        problems.append("stage: the on-screen disclosure badge is missing")
    for f in short.facts:
        if not f.source.startswith("https://"):
            problems.append(f"fact {f.key}: no https source")
    problems += _reported(short)
    return problems


def _reported(short: Short) -> list[str]:
    """A fact taken from outlet reporting needs OWNERS_NEEDED independent owners among the Short's reports, and the
    outlets it comes from are named in the description."""
    reports = short.scene.get("reporting") or []
    known = {r["owner"] for r in reports}
    urls = {r["url"] for r in reports}
    problems = []
    for f in short.facts:
        if f.owners or f.source in urls:
            who = set(f.owners) & known
            if len(who) < OWNERS_NEEDED:
                problems.append(f"fact {f.key}: {len(who)} independent outlet(s) report it (want {OWNERS_NEEDED})")
    if reports and not short.scene.get("outlets"):
        problems.append("sources: the outlets the facts come from are not named")
    return problems


def _story(short: Short) -> list[str]:
    """Photo Shorts: enough real photos, every one freely licensed, and each one's author credited."""
    from . import anchor, compose, media

    problems = []
    photos = short.scene.get("photos", [])
    need = TRIBUTE_PHOTOS if short.kind == "death" else MIN_PHOTOS
    if len(photos) < need:
        problems.append(f"photos: only {len(photos)} (want {need} or more)")
    credits = " ".join(short.credits)
    for p in photos:
        if not media.FREE.match(p.get("license", "")):
            problems.append(f"photo {p.get('file')}: licence {p.get('license')!r} is not free")
        if p.get("page", "") not in credits:
            problems.append(f"photo {p.get('file')}: not credited")
    used = {b.shot for b in short.beats if b.shot.startswith("photo:")}
    if any(int(s.split(":")[1]) >= len(photos) for s in used):
        problems.append("beats: a beat points at a photo that does not exist")
    story = anchor.story_of(short)
    # A map by what it shows too (anchor.legacy_kind): a world map of sea zones or a satellite hotspot map is a map.
    maps = [p for p, k in zip(photos, story.kinds) if k == "map"]
    if maps and len(maps) == len(photos):
        problems.append("photos: only maps; a Short needs at least one real photo")
    if len(maps) > MAX_MAPS:
        problems.append(f"photos: {len(maps)} maps (at most {MAX_MAPS})")
    if short.kind == "death" and maps:
        problems.append("photos: a tribute is told over the person's photos, never a map")
    setting = {i for i, p in enumerate(photos) if p.get("role") == "setting"}
    if len(setting) > MAX_SETTING:
        problems.append(f"photos: {len(setting)} only show the town or area (at most {MAX_SETTING})")
    if short.beats and short.beats[0].shot in {f"photo:{i}" for i in setting}:
        problems.append("beats: beat 1 opens on a photo of the town, not of what happened")
    # The Macron protest ban (gCQ4ZWtobXA, 2026-10-22) passed with two Paris maps and an Eiffel Tower photo under all
    # nine beats: a map or the town may stand under at most a third of the beats, beside REAL_PHOTOS real photos.
    backdrop = {f"photo:{i}" for i, p in enumerate(photos) if p.get("role") in ("map", "setting")}
    on_backdrop = sum(b.shot in backdrop for b in short.beats)
    shots = [b.shot for b in short.beats if b.shot.startswith("photo:")]
    if twice := sorted({s for s in shots if shots.count(s) > 1}):
        # Owner, 2026-10-23: the same picture shown again spoils the Short (studio/writer.py MAX_BEATS).
        problems.append(f"beats: {', '.join(twice)} shown on more than one beat (each picture once)")
    if short.beats and len(shots) < MIN_BEATS:
        problems.append(f"beats: only {len(shots)} pictures (want {MIN_BEATS} or more, each shown once)")
    if short.beats and on_backdrop * 3 > len(short.beats):
        problems.append(f"beats: {on_backdrop} of {len(short.beats)} beats stand on a map or the town (at most a third)")
    real = sum(k not in ("map", "setting") for k in story.kinds)
    if short.kind != "death" and real < REAL_PHOTOS:
        problems.append(f"photos: only {real} show who or what the story is about (want {REAL_PHOTOS} or more)")
    problems += pictures(short, story)
    category = short.scene.get("category")
    if short.kind == "incident" and category in SHOWS and (n := showing(category, photos)) < SHOWN_NEEDED:
        problems.append(f"photos: only {n} usable photos show the {category} vehicle, line or station "
                        f"(want {SHOWN_NEEDED})")
    if "AI voice" not in compose.DISCLOSURE:
        problems.append("end card: the AI-voice disclosure is missing")
    return problems


def pictures(short: Short, story) -> list[str]:
    """Each beat shows who, what or where it says (studio/anchor.py). Owner, 2026-10-22, on Shorts told over maps, a
    school and the town: "do you think people are here to watch the map".
    - The story's subject has a real picture: the person a tribute is about, else the event itself, else the person
      or thing named as the story. Otherwise the Short is refused as faceless.
    - At most one map, never on beat 1, only under a beat about where it happened, for at most a fifth of the
      picture time.
    - Pictures that show what their beat says fill at least anchor.SHOWN_SHARE of it. A filler picture never counts
      toward that, however many there are.
    - No photograph of a photo, poster, painting or screen, and no cover or logo, whatever its licence tag."""
    from . import anchor, media

    problems = []
    photos = short.scene.get("photos") or []
    beats = [b for b in short.beats if b.shot.startswith("photo:")]
    if not photos or not beats:
        return problems
    for p in photos:
        if media.DERIVATIVE.search(f"{p.get('file', '')} {p.get('description', '')}"):
            problems.append(f"photo {p.get('file')}: a photograph of a photo, poster, painting or screen is not "
                            "licence-safe")
    if not story.subject_shown(short.kind):
        problems.append(f"faceless: no real picture shows {story.subject or 'the story'} (a map, the town or a filler "
                        "photo never stands in)")
    texts = [b.text for b in beats]
    story.prepare(texts)
    if who := story.title_faceless(short.title):
        # Review round 1: "The Courage of Captain Machchhar on Flydubai Flight 1073" never showed the captain.
        problems.append(f"faceless: the title names {', '.join(who)}, who has no free photo here")
    shots = [int(b.shot.split(":")[1]) for b in beats]
    got = story.judge(texts, shots)
    if story.kinds and 0 <= shots[0] < len(story.kinds) and story.kinds[shots[0]] == "map":
        problems.append("beats: beat 1 opens on a map, not on who or what the story is about")
    if got["map_photos"] > anchor.MAX_MAPS:
        problems.append(f"beats: {got['map_photos']} different maps are shown (at most {anchor.MAX_MAPS})")
    if got["maps"] > anchor.MAP_SHARE + 1e-9:
        problems.append(f"beats: maps fill {got['maps']:.0%} of the picture time (at most {anchor.MAP_SHARE:.0%})")
    if got["bad_maps"]:
        problems.append("beats: a map stands under beat " + ", ".join(str(k + 1) for k in got["bad_maps"])
                        + ", which is not about where it happened or names someone or something")
    if got["shown"] < anchor.SHOWN_SHARE - 1e-9:
        problems.append(f"beats: pictures show what is said for only {got['shown']:.0%} of the time (want "
                        f"{anchor.SHOWN_SHARE:.0%})" + ("; beat " + ", ".join(str(k + 1) for k in got["unanchored"])
                                                        + " shows something it does not name" if got["unanchored"]
                                                        else ""))
    return problems


def channel_mix(recent_loss_flags: list[bool], loss: bool) -> str | None:
    """At most 2 of any 3 consecutive uploads may be loss stories (YouTube's 2026 'disturbing themes' rule)."""
    window = (recent_loss_flags[-2:] + [loss])
    if loss and sum(window) > 2:
        return "two of the last uploads were loss stories; this one waits for a non-loss Short"
    return None
