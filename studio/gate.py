"""The checks a Short must pass before it can publish: grounded numbers, decorum, title rules and disclosure."""
from __future__ import annotations

import re
from pathlib import Path

from .spec import Short

STAGE = Path(__file__).resolve().parent / "web" / "stage.html"
DISCLOSURE = "3D RECONSTRUCTION FROM DATA · NOT REAL FOOTAGE"
# Gore, sensationalism and clickbait never appear in a title, a card or the narration.
BANNED = [
    "blood", "bloody", "gore", "gory", "graphic", "corpse", "corpses", "body bag", "bodies", "dismember", "decapitat",
    "mutilat", "charred", "burned alive", "horrific", "horrifying", "gruesome", "shocking", "terrifying", "nightmare",
    "massacre", "slaughter", "carnage", "apocalyp", "armageddon", "doomed", "you won't believe", "insane", "breaking",
    "must watch", "watch till the end", "omg", "wtf", "rip ", "sexy", "nude", "naked", "porn", "kill count",
]
ACRONYMS = {"USGS", "UTC", "PAGER", "NASA", "NOAA", "GDACS", "EMSC", "ADS-B", "NTSB", "AAIB", "BEA", "MMI", "ICAO",
            "IATA", "UN", "WHO", "EU", "UK", "US", "USA", "3D", "NHC", "JTWC", "IMD", "JMA", "PTWC", "GREEN", "YELLOW",
            "ORANGE", "RED"}
# Without a death toll that two sources agree on, an incident Short may not speak of casualties at all.
CASUALTY = re.compile(r"\b(casualt\w*|death toll|killed|fatalit\w*|wounded|injured)\b", re.I)
NUMBER = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?::\d{2})?(?:\.\d+)?)(?![\w])")
EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\U0001F000-\U0001F2FF]")


def numbers(text: str) -> list[str]:
    text = re.sub(r"\b3D\b", "", text)
    text = re.sub(r"\bM(?=\d)", "", text)
    return [m.group(1).replace(",", "") for m in NUMBER.finditer(text)]


def check(short: Short) -> list[str]:
    problems = []
    allowed = {n.replace(",", "") for f in short.facts for n in f.numbers}
    texts = [("title", short.title)] + [(f"beat {i + 1}", b.text) for i, b in enumerate(short.beats)]
    for i, b in enumerate(short.beats):
        if b.card:
            texts.append((f"card {i + 1}", f"{b.card.get('big', '')} {b.card.get('small', '')}"))
    for where, text in texts:
        for num in numbers(text.replace("≈", "")):
            if num not in allowed:
                problems.append(f"{where}: the number {num} isn't backed by any sourced fact")
        low = f" {text.lower()} "
        for word in BANNED:
            if word in low:
                problems.append(f"{where}: banned wording {word.strip()!r}")
        if EMOJI.search(text):
            problems.append(f"{where}: emoji")
        if short.kind == "incident" and not any(f.key == "deaths" for f in short.facts) and CASUALTY.search(text):
            problems.append(f"{where}: casualties without an agreed toll ({CASUALTY.search(text).group(0)})")
    for word in re.findall(r"\b[A-Z][A-Z\-]{3,}\b", short.title):
        if word not in ACRONYMS:
            problems.append(f"title: shouting in capitals ({word})")
    if not 20 <= len(short.title) <= 70:
        problems.append(f"title: {len(short.title)} characters (want 20-70)")
    words = len(short.narration.split())
    if not 50 <= words <= 200:
        problems.append(f"narration: {words} words (want 50-200)")
    if not short.sources or any(not s.startswith("https://") for s in short.sources):
        problems.append("sources: every Short needs https primary sources")
    if short.scene.get("template") == "story":
        problems += _story(short)
    elif DISCLOSURE not in STAGE.read_text(encoding="utf-8"):
        problems.append("stage: the on-screen disclosure badge is missing")
    for f in short.facts:
        if not f.source.startswith("https://"):
            problems.append(f"fact {f.key}: no https source")
    return problems


def _story(short: Short) -> list[str]:
    """Photo Shorts: enough real photos, every one freely licensed, and each one's author credited."""
    from . import compose, media

    problems = []
    photos = short.scene.get("photos", [])
    if len(photos) < 3:
        problems.append(f"photos: only {len(photos)} (want 3 or more)")
    credits = " ".join(short.credits)
    for p in photos:
        if not media.FREE.match(p.get("license", "")):
            problems.append(f"photo {p.get('file')}: licence {p.get('license')!r} is not free")
        if p.get("page", "") not in credits:
            problems.append(f"photo {p.get('file')}: not credited")
    used = {b.shot for b in short.beats if b.shot.startswith("photo:")}
    if any(int(s.split(":")[1]) >= len(photos) for s in used):
        problems.append("beats: a beat points at a photo that does not exist")
    if "AI voice" not in compose.DISCLOSURE:
        problems.append("end card: the AI-voice disclosure is missing")
    return problems


def channel_mix(recent_loss_flags: list[bool], loss: bool) -> str | None:
    """At most 2 of any 3 consecutive uploads may be loss stories (YouTube's 2026 'disturbing themes' rule)."""
    window = (recent_loss_flags[-2:] + [loss])
    if loss and sum(window) > 2:
        return "two of the last uploads were loss stories; this one waits for a non-loss Short"
    return None
