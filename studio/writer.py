"""Story Shorts: real photos of the person or event, and a narrated story with feeling, written by a local open model
from the Wikipedia article and the confirmed Wikidata facts.

The model writes; code decides. Every name and every number in the script must appear in the sources, a second
model pass lists anything unsupported, and the draft is rewritten or the story is dropped. Death and casualty facts
still pass the same two-source gates as before.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import cv2

from . import faces, llm, media, stories, wiki
from .spec import Beat, Fact, Short

WORK = Path(__file__).resolve().parents[1] / "work"
MIN_PHOTOS = 3
OUTRO = "Follow Orbitwire for the stories the whole world is talking about."
CREDIT = "Facts: Wikipedia (CC BY-SA 4.0) and Wikidata (CC0); photos: Wikimedia Commons (licences listed below)"
# Capitalised words that start sentences in any story and need no source.
COMMON = set("""a an and as at after before but by even every for from he her his how in it its now on one only
or she so still that the their then there these they this those through today tonight until what when where which while
who whose with without yet years decades across beyond never always more most many few once later soon over under
into first last no not our we you your all both each some such here once again ever forever""".split())
SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "beats": {"type": "array", "minItems": 6, "maxItems": 9, "items": {
            "type": "object",
            "properties": {"say": {"type": "string"}, "photo": {"type": "integer"}, "caption": {"type": "string"}},
            "required": ["say", "photo", "caption"]}},
    },
    "required": ["title", "beats"],
}
CHECK_SCHEMA = {"type": "object", "properties": {"unsupported": {"type": "array", "items": {"type": "string"}}},
                "required": ["unsupported"]}

SYSTEM = ("You are the head writer of Orbitwire, a YouTube Shorts channel that tells the world's biggest stories with "
          "warmth, dignity and complete accuracy. Your narration sounds like a great documentary narrator speaking to "
          "one person: vivid, human and emotional, never robotic and never a list of facts. You never invent anything.")

DEATH_BRIEF = """STORY: {name} has died. Write a tribute Short that makes a viewer who barely knew {name} feel the loss,
and makes a fan feel {pronoun} was honoured.

Shape:
1. Hook (beat 1, under 15 words): say plainly that {name} has died, with the one detail that makes it matter.
2. Where {pronoun} began, or the struggle before success.
3. The turning point or breakthrough, naming the specific work from the SOURCE.
4. The work people loved most, and what made {object} different from everyone else.
5. A human detail from the SOURCE that shows who {pronoun} was off screen or off stage.
6. Legacy: what {pronoun} leaves behind. The last beat is one short, moving sentence.
Do not describe the cause or manner of death unless the SOURCE states it plainly; never mention suicide."""

INCIDENT_BRIEF = """STORY: {name}. Write a news Short that helps a viewer understand what happened and why the world is
watching, with compassion for everyone affected.

Shape:
1. Hook (beat 1, under 15 words): what happened and where, stated plainly, with the detail that makes it matter.
2. The moment it began, in order, as a story.
3. The people involved and what they faced, with official figures only if the SOURCE gives them.
4. The response: rescuers, officials, investigators.
5. What is still unknown or under investigation, said honestly.
6. Why it matters now. The last beat is one short, steady sentence.
Never name or describe any attacker, perpetrator or suspect. Never guess at causes. No graphic detail of injuries or
death."""

RULES = """RULES (all mandatory):
- Use ONLY information in CONFIRMED FACTS and SOURCE. Never add a name, title, number, place, date, quote, award or
  relationship that is not written there. If you are unsure, leave it out.
- 7 or 8 beats and 110 to 130 words in total (about 45 seconds spoken). Each beat is one or two spoken sentences
  of 12 to 20 words. Count the words before you answer.
- Every beat must carry a specific fact from the SOURCE (a work, a place, a year, an honour, a choice they made);
  feeling comes from how you tell those facts, not from vague praise.
- Write numbers as digits (1994, 75). Use a year only when it helps the story.
- Respectful, warm English. No slang, no hype ("shocking", "insane", "legendary", "breaking"), no "RIP", no emojis,
  no questions to the viewer, no request to like or follow.
- photo: the index of the PHOTO that best fits the beat. Beat 1 uses photo {best}. Use every photo at least once if
  you can, and the same photo at most twice.
- caption: 1 to 4 words shown on screen that match what the beat says: the exact work title it names with its year,
  a role, an honour, or a year. Never a place name: viewers read a place over a photo as where the photo was taken.
- title: 30 to 60 characters in normal title case, factual and moving, includes "{name}", no clickbait.
Return only the JSON."""


_lexicon: set[str] | None = None


def english() -> set[str]:
    """Ordinary lower-case English words (Kokoro's misaki lexicon, already installed): capitalised forms of these are
    title-case captions, not names."""
    global _lexicon
    if _lexicon is None:
        import importlib.resources as res

        words = json.loads((res.files("misaki") / "data" / "us_gold.json").read_text(encoding="utf-8"))
        _lexicon = {w for w in words if w.islower()} | COMMON
    return _lexicon


def _numbers(text: str) -> list[str]:
    return [n.replace(",", "") for n in re.findall(r"\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?", text)]


def ungrounded(text: str, source: str) -> list[str]:
    """Names and numbers in text that the source never mentions.

    A capitalised word passes if the source contains it (any case) or it is an ordinary English word; so an invented
    film title or person is caught here, and invented claims in plain words are left to the fact-check pass.
    """
    low = source.lower()
    src_numbers = set(_numbers(source))
    problems = [n for n in _numbers(text) if n not in src_numbers]
    for m in re.finditer(r"\b[A-Z][\w'’\-]*", text):
        word = m.group(0).strip("'’-")
        key = re.sub(r"['’]s$", "", word).lower()
        if len(key) < 2 or key in english() or re.search(r"\b" + re.escape(key) + r"\b", low):
            continue
        problems.append(word)
    return sorted(set(problems))


def _messages(brief: str, facts: list[str], source: str, photos: list[dict], name: str) -> list[dict]:
    listing = "\n".join(f"{i}: {p['description'] or p['file']}" for i, p in enumerate(photos))
    user = (brief + "\n\nCONFIRMED FACTS:\n" + "\n".join(f"- {f}" for f in facts) + "\n\nSOURCE (Wikipedia):\n" + source
            + "\n\nPHOTOS:\n" + listing + "\n\n" + RULES.format(best=0, name=name))
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def _check_messages(script: str, facts: list[str], source: str) -> list[dict]:
    user = ("List every statement in SCRIPT that is not directly supported by CONFIRMED FACTS or SOURCE: any name, "
            "title, number, date, place, award, relationship, quote, cause or superlative that the sources do not "
            "state. Emotional or figurative phrasing that asserts no new fact (\"has gone quiet\", \"will be missed\") "
            "is fine. Return {\"unsupported\": []} when everything is supported.\n\n"
            "CONFIRMED FACTS:\n" + "\n".join(f"- {f}" for f in facts) + "\n\nSOURCE:\n" + source +
            "\n\nSCRIPT:\n" + script)
    return [{"role": "system", "content": "You are a meticulous fact-checker for a news channel."},
            {"role": "user", "content": user}]


def _validate(draft: dict, photos: list[dict], name: str, ground: str, banned_names: list[str]) -> list[str]:
    problems = []
    beats = draft.get("beats", [])
    words = sum(len(b["say"].split()) for b in beats)
    if not 85 <= words <= 145:
        problems.append(f"the script has {words} words; it must have 100 to 130")
    if not beats or name.split()[-1].lower() not in beats[0]["say"].lower():
        problems.append(f"beat 1 must name {name}")
    for b in beats:
        if not 0 <= b["photo"] < len(photos):
            problems.append(f"photo {b['photo']} does not exist")
    text = " ".join(b["say"] + " " + b["caption"] for b in beats) + " " + draft.get("title", "")
    bad = ungrounded(text, ground)
    if bad:
        problems.append("these names or numbers are not in the sources: " + ", ".join(bad))
    for person in banned_names:
        for token in re.findall(r"[A-Z][a-z]{2,}", person):
            if re.search(r"\b" + token + r"\b", text):
                problems.append(f"never name a perpetrator ({token})")
    return problems


def write(kind: str, name: str, pronoun: str, facts: list[str], source: str, photos: list[dict],
          banned_names: list[str] | None = None, model: str | None = None,
          log_path: Path | None = None) -> tuple[dict, list[str]]:
    """The script as {title, beats: [{say, photo, caption}]} plus the log of rejected drafts (also kept at log_path)."""
    obj = {"He": "him", "She": "her"}.get(pronoun, "them")
    brief = (DEATH_BRIEF if kind == "death" else INCIDENT_BRIEF).format(name=name, pronoun=pronoun.lower(), object=obj)
    messages = _messages(brief, facts, source, photos, name)
    ground = source + "\n" + "\n".join(facts) + "\n" + "\n".join(p["description"] for p in photos)
    log = []
    with llm.Model(model or llm.DEFAULT) as m:
        for attempt in range(3):
            draft = m.chat(messages, SCHEMA, temperature=0.75 if attempt == 0 else 0.6)
            problems = _validate(draft, photos, name, ground, banned_names or [])
            if not problems:
                script = "\n".join(b["say"] for b in draft["beats"])
                verdict = m.chat(_check_messages(script, facts, source), CHECK_SCHEMA, temperature=0.0, max_tokens=500)
                problems = [f"unsupported: {u}" for u in verdict.get("unsupported", []) if u.strip()]
            if not problems:
                return draft, log
            log.append({"attempt": attempt + 1, "problems": problems, "draft": draft})
            if log_path:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_path.write_text(json.dumps(log, indent=1, ensure_ascii=False), encoding="utf-8")
            messages = messages + [{"role": "assistant", "content": json.dumps(draft)},
                                   {"role": "user", "content": "Rewrite the whole JSON. Fix these problems and change "
                                    "nothing else that is supported:\n- " + "\n- ".join(problems)}]
    raise ValueError("gate: no draft passed the fact checks: " + "; ".join(log[-1]["problems"])[:400])


def _sentence_with(number: str, text: str) -> str:
    for s in re.split(r"(?<=[.!?])\s+", text):
        if number in _numbers(s):
            return s[:240]
    return ""


def pick_photos(title: str, ent: dict, folder: Path, person: bool, extra_qids: list[str] | None = None) -> list[dict]:
    """Downloaded photos as dicts with a "focus" box: for a person, only photos in which their face is matched."""
    found = media.download(media.find(title, ent, limit=10, extra_qids=extra_qids), folder)
    rows = media.as_dicts(found)
    images = [cv2.imread(r["path"]) for r in rows]
    detected = [faces.detect(img) if img is not None else [] for img in images]
    picks = faces.subject(detected) if person else [None] * len(rows)
    kept = []
    for r, f in zip(rows, picks):
        if person and f is None:
            continue
        r["focus"] = [round(v) for v in f["box"]] if f else None
        kept.append(r)
    return kept[:8]


def build_death(cand: dict) -> Short:
    title, qid = cand["title"], cand["qid"]
    ent = wiki.entities([qid])[qid]
    _, ib, raw = wiki.infobox(title)
    if not raw:
        raise ValueError("gate: the article has no infobox to confirm the death")
    born = next((wiki.wd_time(c["value"]) for c in wiki.claims(ent, "P569")), None)
    died = next((wiki.wd_time(c["value"]) for c in wiki.claims(ent, "P570")), None)
    if not born or not died:
        raise ValueError("gate: Wikidata lacks an exact birth or death date")
    if str(died.year) not in raw.get("death_date", ""):
        raise ValueError("gate: Wikipedia's infobox does not confirm the death yet")
    page, item = wiki.url(title), f"https://www.wikidata.org/wiki/{qid}"
    name = stories.plain_title(wiki.label(ent) or title)
    she, _ = stories._pronouns(ent)
    age = died.year - born.year - ((died.month, died.day) < (born.month, born.day))
    job = (ib.get("occupation") or "").split(",")[0].strip()
    if not job:
        job = next(iter(wiki.labels([c["value"] for c in wiki.claims(ent, "P106")[:1]]).values()), "")
    work = WORK / f"wk-{qid}"
    photos = pick_photos(title, ent, work / "photos", person=True)
    if len(photos) < MIN_PHOTOS:
        raise ValueError(f"gate: only {len(photos)} usable photos of {name} on Wikimedia Commons (want {MIN_PHOTOS})")
    facts_text = [f"{name} died on {stories.date_words(died)}, aged {age}.",
                  f"Born {stories.date_words(born)}" + (f" in {ib['birth_place']}." if ib.get("birth_place") else "."),
                  f"Died in {ib['death_place']}." if ib.get("death_place") else "",
                  f"Occupation: {ib.get('occupation')}." if ib.get("occupation") else "",
                  f"Years active: {ib.get('years_active')}." if ib.get("years_active") else ""]
    facts_text = [f for f in facts_text if f]
    source = wiki.article_text(title)
    draft, log = write("death", name, she, facts_text, source, photos, log_path=work / "writer_log.json")
    facts = [Fact("name", name, page, stories.numbers_in(name), "Wikipedia article title"),
             Fact("died", stories.date_words(died), item, [str(died.day), str(died.year)],
                  f"Wikidata P570 = {died.isoformat()}; infobox death_date present"),
             Fact("born", stories.date_words(born), item, [str(born.day), str(born.year)], f"Wikidata P569 = {born}"),
             Fact("age", str(age), item, [str(age)], "computed from P569 and P570")]
    return _short(f"wk-{qid}", "death", name, draft, log, facts, facts_text, source, photos, [page, item],
                  died.isoformat(), loss=False, mood="tribute",
                  tags=[name, job, "tribute", "remembering " + name, "news"],
                  summary=f"Remembering {name} ({born.year}–{died.year}), {job.lower() or 'public figure'}.",
                  hashtags=[name.replace(" ", ""), job or "tribute", "news"])


def build_incident(cand: dict) -> Short:
    article, qid, cat = cand["title"], cand["qid"], cand["category"]
    name = stories.plain_title(article)
    stories._check_age(article)
    ent = wiki.entities([qid])[qid]
    _, ib, _ = wiki.infobox(article)
    when = stories._event_date(ent)
    if not when:
        raise ValueError("gate: Wikidata has no date for this event")
    page, item = wiki.url(article), f"https://www.wikidata.org/wiki/{qid}"
    extra = [c["value"] for pid in ("P276", "P1427", "P1444", "P121", "P137") for c in wiki.claims(ent, pid)[:1]
             if isinstance(c["value"], str) and c["value"].startswith("Q")]
    work = WORK / f"wk-{qid}"
    photos = pick_photos(article, ent, work / "photos", person=False, extra_qids=extra)
    if len(photos) < MIN_PHOTOS:
        raise ValueError(f"gate: only {len(photos)} usable photos of {name} on Wikimedia Commons (want {MIN_PHOTOS})")
    deaths = stories.agreed(stories._first(ib, "total_fatalities", "fatalities", "deaths"), ent, "P1120", True)
    hurt = stories.agreed(stories._first(ib, "total_injuries", "injuries", "injured"), ent, "P1339", True)
    facts_text = [f"{name} happened on {stories.date_words(when)}."]
    where = stories._first(ib, "site", "location", "place", "areas affected", "areas")
    if where:
        facts_text.append(f"Location: {where}.")
    if deaths is not None:
        facts_text.append(f"Official death toll (Wikipedia and Wikidata agree): {deaths:,}.")
    if hurt:
        facts_text.append(f"Injured (Wikipedia and Wikidata agree): {hurt:,}.")
    banned = [v for k, v in ib.items() if re.match(r"(perpetrators?|assailants?|attackers?|suspects?|accused)$", k)]
    source = wiki.article_text(article)
    if deaths is None:
        # Casualty numbers only when both sources agree: strip unconfirmed tolls from what the writer may use.
        source = re.sub(r"[^.]*\b(killed|dead|deaths|died|fatalit\w*|injured|wounded)\b[^.]*\.", "", source)
    draft, log = write("incident", name, "It", facts_text, source, photos, banned_names=banned,
                       log_path=work / "writer_log.json")
    loss = bool(deaths) or cat in ("attack", "strike", "conflict")
    facts = [Fact("name", name, page, stories.numbers_in(name), "Wikipedia article title"),
             Fact("date", stories.date_words(when), item, [str(when.day), str(when.year)], f"Wikidata date {when}")]
    if deaths is not None:
        facts.append(Fact("deaths", str(deaths), page, [f"{deaths:,}", str(deaths)], "infobox and Wikidata P1120 agree"))
    region = stories.city_of(where) if where else None
    return _short(f"wk-{qid}", "incident", name, draft, log, facts, facts_text, source, photos, [page, item],
                  when.isoformat(), loss=loss, mood="news",
                  tags=[name, cat, "news explained", "world news"] + ([region] if region else []),
                  summary=f"{name}, {stories.date_words(when)}: what happened, from Wikipedia and Wikidata.",
                  hashtags=[cat, region or "world", "news"])


def _short(sid, kind, name, draft, log, facts, facts_text, source, photos, sources, event_time, loss, mood, tags,
           summary, hashtags) -> Short:
    beats = []
    for b in draft["beats"]:
        beats.append(Beat(b["say"].strip(), f"photo:{b['photo']}", {"big": b["caption"].strip(), "small": ""}))
    beats.append(Beat(OUTRO, "outro", {"big": "Orbitwire", "small": "Sources in the description"}, pause_after=0.5))
    ground = source + "\n" + "\n".join(facts_text)
    allowed = {n for f in facts for n in f.numbers}
    for n in sorted(set(_numbers(" ".join(b.text + " " + (b.card or {}).get("big", "") for b in beats) + " "
                                 + draft["title"]))):
        if n not in allowed:
            facts.append(Fact(f"source-{n}", n, sources[0], [n], _sentence_with(n, ground)))
            allowed.add(n)
    title = draft["title"].strip().strip('"')
    if not 20 <= len(title) <= 70:
        title = f"Remembering {name}" if kind == "death" else f"{name}: what happened"
    credits = [CREDIT] + sorted({p["credit"] + " " + p["page"] for p in photos})
    tags = [t for t in tags if t]
    return Short(id=sid, kind=kind, title=title[:70], beats=beats, facts=facts, sources=sources, loss=loss,
                 scene={"template": "story", "mood": mood, "photos": photos, "writer": {"model": llm.DEFAULT,
                                                                                        "rejected": log}},
                 event_time=event_time, tags=tags, summary=summary, credits=credits, hashtags=hashtags)


def build(cand: dict) -> Short:
    return build_death(cand) if cand["kind"] == "death" else build_incident(cand)
