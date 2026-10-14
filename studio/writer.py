"""Story Shorts: real photos of the person or event, and a narrated story with feeling, written by a local open model
from the Wikipedia article and the confirmed Wikidata facts.

The model writes; code decides. Every name and every number in the script must appear in the sources, a second
model pass lists anything unsupported, and the draft is rewritten or the story is dropped. Death and casualty facts
still pass the same two-source gates as before.

REPORTING: excerpts from 2-4 trusted outlets' articles about the story (studio/outlets.py), each from a different
owner. A name or number the Wikipedia/Wikidata sources lack passes only when at least two independent owners' articles
state it; one outlet alone never backs a fact. A death toll from reporting needs two owners stating the same exact
number (or one and Wikidata).
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import cv2

from . import faces, gate, llm, media, outlets, stories, trends, wiki
from .spec import Beat, Fact, Short

WORK = Path(__file__).resolve().parents[1] / "work"
MIN_PHOTOS, TRIBUTE_PHOTOS = gate.MIN_PHOTOS, gate.TRIBUTE_PHOTOS
WANT_PHOTOS = 3  # fill photos are looked for until a story has this many
PLACE_FACE = 0.06  # a face this share of a place photo's shorter side features a person
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
CHECK_SCHEMA = {"type": "object", "properties": {"lines": {"type": "array", "items": {
    "type": "object", "properties": {"line": {"type": "integer"}, "quote": {"type": "string"},
                                     "verdict": {"type": "string", "enum": ["supported", "partly", "unsupported"]},
                                     "why": {"type": "string"}},
    "required": ["line", "quote", "verdict", "why"]}}}, "required": ["lines"]}

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

INCIDENT_BRIEF = """STORY: {name}. Write a news Short that helps a viewer understand what happened and why it matters,
with compassion for everyone affected.

Shape:
1. Hook (beat 1, under 15 words): what happened and where, stated plainly, with the detail that makes it matter.
2. The moment it began, in order, as a story.
3. The people involved and what they faced, with official figures only if the SOURCE gives them.
4. The response: rescuers, officials, investigators.
5. What is still unknown or under investigation, said honestly.
6. Where it stands now, from the SOURCE. The last beat is one short, steady sentence.
Never name or describe any attacker, perpetrator or suspect. Never guess at causes. No graphic detail of injuries or
death."""

PROTEST_BRIEF = """STORY: {name}. Write a news Short that explains, fairly and calmly, what this protest or movement is,
why people took to the streets, and where it stands now.

Shape:
1. Hook (beat 1, under 15 words): the newest development in the SOURCE, stated plainly.
2. How it began: the trigger, in order, as a story.
3. Who is involved and what they demand, attributed ("organisers demand", "the party says").
4. How the government, police or courts responded, attributed to them.
5. The turning point or the latest step.
6. What happens next, or what is still unresolved. The last beat is one short, steady sentence.
Be strictly neutral: give each side's position as the SOURCE states it, never take a side, never mock or praise any
person, party, community or religion, and use no loaded words ("brutal", "anti-national", "heroic", "historic").
Attribute every disputed claim and every injury, arrest or crowd figure to whoever reported it. Never urge anyone to
join or avoid a protest. Never mention suicide."""

RULES = """RULES (all mandatory):
- Use ONLY information in CONFIRMED FACTS and SOURCE. Never add a name, title, number, place, date, quote, award or
  relationship that is not written there. If you are unsure, leave it out.
- Keep every fact exactly as strong as the SOURCE: a risk, warning, forecast or evacuation is not something that
  happened ("60 people were evacuated over the risk of landslides", never "families faced landslides"), and a fact
  about one place or group is never moved to another. Never claim how people or "the world" felt or reacted
  ("the world watched", "resilience") unless the SOURCE says it. Never add an order the SOURCE does not state
  ("Abha was also attacked", never "Abha was hit first"), and never moralise ("this tragedy reminds us").
- 7 or 8 beats and 110 to 130 words in total (about 45 seconds spoken). Each beat is one or two spoken sentences
  of 12 to 20 words. Count the words before you answer.
- Every beat must carry a specific fact from the SOURCE (a work, a place, a year, an honour, a choice they made);
  feeling comes from how you tell those facts, not from vague praise.
- Tell it as a story, not a list: vary how beats open, and never start more than 2 beats with the same word
  ("She", "He", "The"). Open beats with the moment, the work, the year or the turn ("In 1954, ...", "Then came ...").
- Write numbers as digits (1994, 75). Use a year only when it helps the story.
- Respectful, warm English. No slang, no hype ("shocking", "insane", "legendary", "breaking"), no "RIP", no emojis,
  no questions to the viewer, no request to like or follow.
- photo: the index of the PHOTO that best fits the beat. Beat 1 uses photo {best}. Use every photo at least once,
  the same photo at most {most} times, and never the same photo on two beats in a row.
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


REPORTING_RULE = ("a fact that only REPORTING gives may be used only when at least two reports from DIFFERENT owners "
                  "state it; never use a fact that only one report states")


def reporting_block(reports: list[dict] | None) -> str:
    """The REPORTING section: each article's outlet, owner, date and headline, then its excerpt."""
    if not reports:
        return ""
    rows = [f"[{n}] {r['outlet']} (owner: {r['owner']}), {r['at'][:10]}: {r['title']}\n{r['excerpt']}"
            for n, r in enumerate(reports, 1)]
    return f"\n\nREPORTING (trusted outlets; {REPORTING_RULE}):\n" + "\n\n".join(rows)


def report_ground(reports: list[dict] | None) -> str:
    """The reports' excerpts sentence by sentence, each marked with its owner, for the evidence checks."""
    return "\n".join(f"[owner: {r['owner']}] {s}" for r in reports or [] for s in
                     re.split(r"(?<=[.!?])\s+", r["excerpt"]) if s.strip())


def _messages(brief: str, facts: list[str], source: str, photos: list[dict], name: str,
              headlines: list[str] | None = None, reports: list[dict] | None = None) -> list[dict]:
    listing = "\n".join(f"{i}: {p['description'] or p['file']}" for i, p in enumerate(photos))
    lead = ""
    if headlines:
        lead = ("\n\nTODAY'S LEAD HEADLINES (context only: use them to choose the angle and what to put first, but "
                "state only facts that are in CONFIRMED FACTS or SOURCE):\n" + "\n".join(f"- {h}" for h in headlines))
    user = (brief + "\n\nCONFIRMED FACTS:\n" + "\n".join(f"- {f}" for f in facts)
            + ("\n\nSOURCE (Wikipedia):\n" + source if source else "") + reporting_block(reports)
            + lead + "\n\nPHOTOS:\n" + listing + "\n\n"
            + RULES.format(best=0, name=name, most=max(2, -(-8 // max(len(photos), 1))))
            + ("\nREPORTING counts as a SOURCE under its own rule: " + REPORTING_RULE + "." if reports else ""))
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def _check_messages(lines: list[str], facts: list[str], source: str,
                    reports: list[dict] | None = None) -> list[dict]:
    if reports:
        source = (source + "\n\n" if source else "") + report_ground(reports)
    two = (" A sentence marked [owner: X] comes from one outlet's report: a detail that only such sentences state is "
           "supported only when sentences from two DIFFERENT owners state it; otherwise the verdict is partly."
           if reports else "")
    user = ("Check every numbered LINE of a news script against CONFIRMED FACTS and SOURCE." + two +
            " For each line, copy word "
            "for word the sentence from SOURCE or CONFIRMED FACTS that supports it (\"quote\"), then give a verdict:\n"
            "- supported: the quote states every fact in the line: who, what, when, where, numbers, causes and "
            "relationships. Emotional or figurative phrasing that adds no fact (\"has gone quiet\") is fine; such a "
            "line may have an empty quote.\n"
            "- partly: the line adds, changes or exaggerates a detail that no sentence in the sources states, "
            "including a risk, warning or forecast told as something that happened, or a fact moved to another "
            "place or group.\n"
            "- unsupported: no sentence in the sources says it.\n"
            "Leaving details out is fine: judge only what the line says. A detail stated anywhere in SOURCE (a "
            "reference title counts) or in CONFIRMED FACTS is supported, even if another sentence states it; quote "
            "that sentence. In \"why\", name the exact detail that no source states or that a source contradicts.\n\n"
            "CONFIRMED FACTS:\n" + "\n".join(f"- {f}" for f in facts) + "\n\nSOURCE:\n" + source +
            "\n\nLINES:\n" + "\n".join(f"{i}. {line}" for i, line in enumerate(lines, 1)))
    return [{"role": "system", "content": "You are a meticulous fact-checker for a news channel."},
            {"role": "user", "content": user}]


def _plain(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def check_verdict(verdict: dict, lines: list[str], ground: str) -> dict[int, str]:
    """Lines the evidence check flags, by line number: not fully supported, or backed by a quote that is not really in
    the sources (an invented quote means the checker did not find support)."""
    plain = _plain(ground)
    flagged = {}
    for row in verdict.get("lines", []):
        n = row.get("line", 0)
        if not 1 <= n <= len(lines):
            continue
        if row.get("verdict") != "supported":
            flagged[n] = f"line {n} ({lines[n - 1][:60]}): {row.get('verdict')}: {row.get('why', '')}"[:300]
            continue
        parts = [_plain(p) for p in re.split(r"\.\.\.|…", row.get("quote") or "")]
        if any(len(p) >= 12 and p not in plain for p in parts):
            flagged[n] = f"line {n} ({lines[n - 1][:60]}): its supporting quote is not in the sources"
    return flagged


RECHECK_SCHEMA = {"type": "object", "properties": {"supported": {"type": "boolean"}, "why": {"type": "string"}},
                  "required": ["supported", "why"]}
_STOP = set("the and for with from that this was were are has had have its his her their they them into after "
            "before over who which when where what".split())


def evidence(line: str, ground: str, k: int = 6) -> list[str]:
    """The k source sentences that share the most words with the line."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", ground) if len(s.strip()) > 20]
    words = {w for w in _plain(line).split() if len(w) > 2 and w not in _STOP}
    return sorted(sentences, key=lambda s: -len(words & set(_plain(s).split())))[:k]


def recheck(m, lines: list[str], flagged: dict[int, str], ground: str) -> list[str]:
    """A second look at each flagged line against only the sentences most like it: a long source dilutes the first
    check, which then flags true lines. A line stays a problem only if this look also finds it unsupported."""
    problems = []
    two = (" A sentence marked [owner: X] is one outlet's report: a fact that only such sentences state counts only "
           "when sentences from two DIFFERENT owners state it." if "[owner: " in ground else "")
    for n, problem in flagged.items():
        user = ("Do these SOURCE SENTENCES state every fact in the LINE: who, what, when, where, numbers, causes and "
                "relationships? A fact may come from any of the sentences, and leaving details out is fine. Answer "
                "false if the line adds, changes or exaggerates anything." + two + "\n\nLINE: " + lines[n - 1] +
                "\n\nSOURCE SENTENCES:\n" + "\n".join(f"- {s}" for s in evidence(lines[n - 1], ground)))
        verdict = m.chat([{"role": "system", "content": "You are a meticulous fact-checker for a news channel."},
                          {"role": "user", "content": user}], RECHECK_SCHEMA, temperature=0.0, max_tokens=200)
        if not verdict.get("supported"):
            problems.append(f"{problem} | second look: {verdict.get('why', '')}"[:400])
    return problems


def reported_ok(item: str, reports: list[dict] | None) -> bool:
    """A name or number the Wikipedia sources lack that at least two independent owners' reports state."""
    if not reports:
        return False
    if re.fullmatch(r"[\d.]+", item):
        return item in gate.corroborated_values(reports)
    return len(gate.reported(item, reports)) >= gate.OWNERS_NEEDED


PLACE_CAPTION = re.compile(r"\b(Airport|Hospital|Medical Complex|Station|Terminal|Province|County|District|Street|Square|"
                           r"Bridge|Harbou?r|Mosque|Cathedral|Church|Temple|Stadium)s?\b")


def _validate(draft: dict, photos: list[dict], name: str, ground: str, banned_names: list[str],
              reports: list[dict] | None = None, casualties: bool = True) -> list[str]:
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
    # The publish gate's wording rules (studio/gate.py), checked here so a slip is rewritten, not the story dropped.
    lines = [("the title", draft.get("title", ""))] + [(f"beat {i + 1}", f"{b['say']} {b['caption']}")
                                                        for i, b in enumerate(beats)]
    for where, line in lines:
        if word := gate.banned_word(line):
            problems.append(f"{where} uses the banned word {word!r}: say it plainly without that word")
        if not casualties and (hit := gate.CASUALTY.search(line)):
            problems.append(f"{where} says {hit.group(0)!r}: the sources agree on no toll, so never mention deaths, "
                            "injuries or casualties")
    for i, b in enumerate(beats):
        if PLACE_CAPTION.search(b["caption"]):
            problems.append(f"beat {i + 1}'s caption {b['caption']!r} names a place, which viewers read as where the "
                            "photo was taken: caption a date, a figure, a role or a work instead")
    text = " ".join(b["say"] + " " + b["caption"] for b in beats) + " " + draft.get("title", "")
    grounded = set(gate.numbers(ground)) | set(_numbers(ground))
    loose = [n for n in gate.numbers(text) if n not in grounded and not reported_ok(n, reports)]
    bad = list(dict.fromkeys([b for b in ungrounded(text, ground) if not reported_ok(b, reports)] + loose))
    if bad:
        single = [b for b in bad if reports and (gate.reported_values(reports).get(b) or gate.reported(b, reports))]
        problems.append("these names or numbers are not in the sources: " + ", ".join(bad)
                        + (f" ({', '.join(single)} only in one outlet's report: one outlet is not enough)"
                           if single else ""))
    for person in banned_names:
        for token in re.findall(r"[A-Z][a-z]{2,}", person):
            # "Houthi" also bans "Houthis", "Russia" also "Russian" and "Russians"
            if re.search(r"\b" + token + r"(?:s|n|ns|i|is)?\b", text):
                problems.append(f"never name a perpetrator or attacker ({token})")
    return problems


def monotone(draft: dict) -> list[str]:
    """Openings repeated so often that the script reads as a list."""
    openers = [re.sub(r"\W", "", b["say"].split()[0]).lower() for b in draft.get("beats", []) if b["say"].split()]
    return [f"{openers.count(w)} beats start with \"{w.capitalize()}\"; start at most 2 beats with the same word"
            for w in sorted(set(openers)) if openers.count(w) > 2]


def write(kind: str, name: str, pronoun: str, facts: list[str], source: str, photos: list[dict],
          banned_names: list[str] | None = None, model: str | None = None,
          log_path: Path | None = None, headlines: list[str] | None = None,
          series: dict | None = None, reports: list[dict] | None = None,
          casualties: bool = True) -> tuple[dict, list[str]]:
    """The script as {title, beats: [{say, photo, caption}]} plus the log of rejected drafts (also kept at log_path).
    kind is "death", "incident" or "protest". reports: trusted outlets' articles ({outlet, owner, at, title, excerpt,
    text}), see the module docstring. casualties: False when no toll is agreed, so the script may not speak of any."""
    obj = {"He": "him", "She": "her"}.get(pronoun, "them")
    brief = {"death": DEATH_BRIEF, "protest": PROTEST_BRIEF}.get(kind, INCIDENT_BRIEF)
    brief = brief.format(name=name, pronoun=pronoun.lower(), object=obj)
    if series:
        brief += (f"\n\nSERIES: this Short is Part {series['part']} of {series['of']} on {series['topic']}. Tell only "
                  f"this part: {series['angle']}. Beat 1 hooks with the most striking fact of this part (never a "
                  f"date, never \"is in the news\"). The title starts with \"Part {series['part']}: \".")
        brief += (f" The last beat ends by saying that Part {series['part'] + 1} tells {series['next']}."
                  if series.get("next") else " The last beat says where the story stands now.")
    messages = _messages(brief, facts, source, photos, name, headlines, reports)
    # A photo's Commons description is an uploader's note, not a source: no fact may come from it.
    ground = source + "\n" + "\n".join(facts)
    if series:
        ground += f"\nPart {series['part']}, Part {series['part'] + 1}, of {series['of']}. {series.get('next') or ''}"
    checked = ground + ("\n" + report_ground(reports) if reports else "")
    log = []
    with llm.Model(model or llm.DEFAULT) as m:
        for attempt in range(3):
            draft = m.chat(messages, SCHEMA, temperature=0.75 if attempt == 0 else 0.6)
            problems = _validate(draft, photos, name, ground, banned_names or [], reports, casualties)
            if attempt < 2:
                problems += monotone(draft)
            if not problems:
                teaser = f"part {series['part'] + 1}" if series else None
                lines = [b["say"] for b in draft["beats"] if not (teaser and b["say"].lower().startswith(teaser))]
                verdict = m.chat(_check_messages(lines, facts, source, reports), CHECK_SCHEMA, temperature=0.0,
                                 max_tokens=1800)
                problems = recheck(m, lines, check_verdict(verdict, lines, checked), checked)
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


def featured_face(img, seen: list[dict]) -> bool:
    """A face this big would pass whoever it is off as part of the story."""
    return img is None or any(d["box"][2] >= PLACE_FACE * min(img.shape[:2]) for d in seen)


def pick_photos(title: str, ent: dict, folder: Path, person: bool, extra_qids: list[str] | None = None,
                files: list[str] | None = None, places: bool = False,
                context_qids: list[str] | None = None) -> list[dict]:
    """Downloaded photos as dicts with a "focus" box: for a person, only photos in which their face is matched.
    files: Commons files an editor chose instead of searching; places: see media.find; context_qids: places and
    things the story links to, whose photos (with no featured face) fill in when the story has fewer than
    WANT_PHOTOS of its own: Commons first, then Openverse. A person needs at least one photo of their own face."""
    kept = _own_photos(title, ent, folder, person, extra_qids, files, places)
    if len(kept) >= WANT_PHOTOS or files or not context_qids or (person and not kept):
        return kept
    return (kept + fill_photos(context_qids, folder, {r["file"] for r in kept}, WANT_PHOTOS - len(kept)))[:8]


def fill_photos(context_qids: list[str], folder: Path, exclude: set[str], need: int = WANT_PHOTOS) -> list[dict]:
    """Photos of the places and things a story links to that feature no face: Commons (each item's main image and
    files from its article naming it), then, while fewer than `need`, Openverse photos naming the item. The Hindi
    desk excludes the same photos from a shared story (hindi-news-desk desk/orbitwire.py photo_pool)."""
    def faceless(found: list, sub: str) -> list[dict]:
        out = []
        for r in media.as_dicts(media.download(found, folder / sub)):
            img = cv2.imread(r["path"])
            if featured_face(img, faces.detect(img) if img is not None else []):
                continue
            r["focus"] = None
            out.append(r)
        return out

    kept = faceless(media.context(context_qids, exclude=exclude), "context")
    if len(kept) < need:
        try:
            found = media.openverse_for(context_qids, exclude=exclude | {r["file"] for r in kept})
        except Exception:
            found = []
        kept += faceless(found, "openverse")
    return kept


def _own_photos(title: str, ent: dict, folder: Path, person: bool, extra_qids: list[str] | None,
                files: list[str] | None, places: bool) -> list[dict]:
    found = media.picks(files) if files else media.find(title, ent, limit=10, extra_qids=extra_qids, places=places)
    found = media.download(found, folder)
    rows = media.as_dicts(found)
    images = [cv2.imread(r["path"]) for r in rows]
    detected = [faces.detect(img) if img is not None else [] for img in images]
    picks = faces.subject(detected) if person else [None] * len(rows)
    kept = []
    for r, f, img, seen in zip(rows, picks, images, detected):
        if person and f is None:
            continue
        if r["origin"] == "place" and img is not None and featured_face(img, seen):
            continue  # a place photo that features someone would pass them off as part of the story
        r["focus"] = [round(v) for v in f["box"]] if f else None
        r["others"] = sum(g is not f and g["box"][2] * g["box"][3] >= 0.25 * f["box"][2] * f["box"][3]
                          for g in seen) if f else 0
        kept.append(r)
    # Strangers beside the person would be shown as part of today's story: their own portraits go first.
    return sorted(kept, key=lambda r: r["others"] > 0)[:8]


PERSON_CONTEXT = ("P19", "P69", "P108", "P54", "P463", "P166", "P800")  # birthplace, school, employer, team, ...


def person_context(ent: dict) -> list[str]:
    """The places and things a person's life links to, whose photos may fill a tribute short of portraits."""
    return list(dict.fromkeys(c["value"] for pid in PERSON_CONTEXT for c in wiki.claims(ent, pid)[:1]
                              if isinstance(c["value"], str) and c["value"].startswith("Q")))[:6]


def incident_context(ent: dict, extra: list[str]) -> list[str]:
    """The items an incident's fill photos come from: its related items, then the place it is located in (P131)."""
    located = [c["value"] for c in wiki.claims(ent, "P131")[:1] if isinstance(c["value"], str)
               and c["value"].startswith("Q")]
    return list(dict.fromkeys(extra + located))[:4]


SUICIDE = re.compile(r"\bsuicid\w*", re.I)
# Reports name suspects and attackers; an incident Short never does, so such sentences never reach the writer.
PERPETRATOR = re.compile(r"\b(suspect\w*|accused|attackers?|assailants?|gunm[ae]n|shooters?|perpetrators?|"
                         r"identified as|named as|arrest\w*|detained|charged|held for)\b", re.I)
CASUALTY_WORDS = re.compile(r"\b(killed|dead|deaths?|died|toll|fatalit\w*|casualt\w*|injured|wounded|lives|"
                            r"bod(?:y|ies)|perish\w*)\b", re.I)


def _reporting(cand: dict, title: str, person: bool = False, since: datetime | None = None,
               search: bool = True) -> list[dict]:
    """2-4 trusted outlets' articles about the story, each from a different owner, with their text (outlets.reporting):
    the reports matched to it at discovery, and (search) any recent English outlet item that names it. [] when fewer
    than two owners' articles can be read."""
    found = [r for r in cand.get("reports") or [] if r.get("url")]
    if search:
        # Discovery matches a headline by one distinctive word; a report backs facts only when it names the story.
        found = outlets.about(title, found, person=person)
    found = {r["url"]: r for r in found}
    if search:
        try:
            items, _ = outlets.recent(langs=trends.OUTLET_LANGS)
        except Exception:
            items = []
        for i in outlets.about(title, items, since=since, person=person):
            found.setdefault(i["url"], i)
    rows = [r for r in found.values() if not since or datetime.fromisoformat(r["at"]) >= since]
    try:
        return outlets.reporting(rows)
    except Exception:
        return []


def _drop(text: str, pattern: re.Pattern) -> str:
    return " ".join(s for s in re.split(r"(?<=[.!?])\s+", text) if not pattern.search(s))


def clean_reports(reports: list[dict], words: list[str], perpetrators: bool) -> list[dict]:
    """The reports as the writer and the checks see them: no sentence about suicide or casualties (an agreed toll
    comes as a confirmed fact, and no other count may be said beside it), none naming a suspect or attacker in an
    incident; each with an excerpt naming the story."""
    out = []
    for r in reports:
        body = _drop(_drop(r["text"], SUICIDE), CASUALTY_WORDS)
        if perpetrators:
            body = _drop(body, PERPETRATOR)
        out.append(r | {"text": body, "excerpt": outlets.excerpt(body, words)})
    return out


def reported_toll(reports: list[dict], ent: dict, listed: str | None = None) -> tuple[int, list[str]] | None:
    """A death toll the reporting agrees on (gate.reported_toll, checked against Wikidata P1120), never one that
    differs from a number the infobox lists."""
    got = gate.reported_toll(reports, {int(c["value"]) for c in wiki.claims(ent, "P1120")})
    shown = wiki.leading_number(listed)
    return got if got and shown in (None, got[0]) else None


def toll_basis(owners: list[str]) -> str:
    return " and ".join(owners) if len(owners) >= gate.OWNERS_NEEDED else f"{owners[0]} and Wikidata P1120"


def toll_fact(deaths: int, owners: list[str], reports: list[dict], item: str | None) -> Fact:
    """The deaths fact for a reported toll: the owners' reports, or Wikidata when only one owner states it."""
    if len(owners) >= gate.OWNERS_NEEDED:
        url = next(r["url"] for r in reports if r["owner"] in owners)
        return Fact("deaths", str(deaths), url, [f"{deaths:,}", str(deaths)], f"reported alike by {toll_basis(owners)}",
                    owners=owners)
    return Fact("deaths", str(deaths), item or reports[0]["url"], [f"{deaths:,}", str(deaths)],
                f"{toll_basis(owners)} agree")


def _since(day: date, back_days: int = 1) -> datetime:
    return datetime.combine(day, datetime.min.time(), timezone.utc) - timedelta(days=back_days)


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
    photos = pick_photos(title, ent, work / "photos", person=True, context_qids=person_context(ent))
    if not photos:
        # Commons will not grow a portrait in the next few hours: give the runs to stories that can be made.
        raise ValueError(f"gate: no photo on Wikimedia Commons shows {name}'s face (a tribute needs one)")
    if len(photos) < TRIBUTE_PHOTOS:
        raise ValueError(f"gate: only {len(photos)} usable photos of {name} on Wikimedia Commons "
                         f"(want {TRIBUTE_PHOTOS})")
    facts_text = [f"{name} died on {stories.date_words(died)}, aged {age}.",
                  f"Born {stories.date_words(born)}" + (f" in {ib['birth_place']}." if ib.get("birth_place") else "."),
                  f"Died in {ib['death_place']}." if ib.get("death_place") else "",
                  f"Occupation: {ib.get('occupation')}." if ib.get("occupation") else "",
                  f"Years active: {ib.get('years_active')}." if ib.get("years_active") else ""]
    facts_text = [f for f in facts_text if f]
    source = wiki.article_text(title)
    reports = clean_reports(_reporting(cand, name, person=True, since=_since(died)), [name],
                            perpetrators=False)
    draft, log = write("death", name, she, facts_text, source, photos, log_path=work / "writer_log.json",
                       reports=reports)
    facts = [Fact("name", name, page, stories.numbers_in(name), "Wikipedia article title"),
             Fact("died", stories.date_words(died), item, [str(died.day), str(died.year)],
                  f"Wikidata P570 = {died.isoformat()}; infobox death_date present"),
             Fact("born", stories.date_words(born), item, [str(born.day), str(born.year)], f"Wikidata P569 = {born}"),
             Fact("age", str(age), item, [str(age)], "computed from P569 and P570")]
    return _short(f"wk-{qid}", "death", name, draft, log, facts, facts_text, source, photos, [page, item],
                  died.isoformat(), loss=False, mood="tribute", voice=cand.get("region", "world"),
                  tags=[name, job, "tribute", "remembering " + name, "news"],
                  summary=f"Remembering {name} ({born.year}–{died.year}), {job.lower() or 'public figure'}.",
                  hashtags=[name.replace(" ", ""), job or "tribute", "news"], reports=reports)


def build_incident(cand: dict) -> Short:
    article, qid, cat = cand["title"], cand.get("qid"), cand["category"]
    name = stories.plain_title(article)
    stories._check_age(article)
    ent = wiki.entities([qid])[qid] if qid else {}
    _, ib, raw = wiki.infobox(article)
    ongoing = cat in trends.ONGOING
    when, date_src = stories._event_date(ent), "Wikidata date"
    if not when and (when := stories.infobox_date(ib)):
        date_src = "Wikipedia infobox date"
    span = date_src == "Wikipedia infobox date" and stories.infobox_span(ib)
    if ongoing:
        when = date.fromisoformat((cand.get("news_at") or datetime.now(timezone.utc).isoformat())[:10])
    if not when:
        raise ValueError("gate: neither Wikidata nor the infobox gives a date for this event")
    page = wiki.url(article)
    item = f"https://www.wikidata.org/wiki/{qid}" if qid else page
    extra = [c["value"] for pid in ("P276", "P1427", "P1444", "P121", "P137") for c in wiki.claims(ent, pid)[:1]
             if isinstance(c["value"], str) and c["value"].startswith("Q")]
    if not extra:
        # An article Wikidata does not describe yet: the places its infobox links to give the location photos.
        links = re.findall(r"\[\[([^\]|#]+)", " ".join(raw.get(k, "") for k in ("target", "location", "site", "place",
                                                                                "areas affected", "areas", "country")))
        found = wiki.page_info(list(dict.fromkeys(links))[:6]) if links else {}
        extra = list(dict.fromkeys(p["qid"] for p in found.values() if p.get("qid")))[:3]
    sid = cand.get("id") or f"wk-{qid}"
    work = WORK / sid
    photos = pick_photos(article, ent, work / "photos", person=False, extra_qids=extra, files=cand.get("photo_files"),
                         places=not qid, context_qids=incident_context(ent, extra))
    if len(photos) < MIN_PHOTOS:
        raise ValueError(f"gate: only {len(photos)} usable photos of {name} on Wikimedia Commons (want {MIN_PHOTOS})")
    listed = stories._first(ib, "total_fatalities", "fatalities", "deaths")
    deaths = stories.agreed(listed, ent, "P1120", True)
    hurt = stories.agreed(stories._first(ib, "total_injuries", "injuries", "injured"), ent, "P1339", True)
    kind = "protest" if cat in ("protest", "movement") else "incident"
    reports = _reporting(cand, name, since=None if ongoing else _since(when))
    toll = None
    if deaths is None and (toll := reported_toll(reports, ent, listed)):
        deaths = toll[0]
    reports = clean_reports(reports, [name], perpetrators=kind == "incident")
    facts_text = [f"Today's date: {stories.date_words(when)}." if ongoing
                  else f"{name} {'began' if span else 'happened'} on {stories.date_words(when)}."]
    where = stories._first(ib, "site", "location", "place", "areas affected", "areas")
    if where:
        facts_text.append(f"Location: {where}.")
    if toll:
        facts_text.append(f"Death toll ({toll_basis(toll[1])} agree): {deaths:,}.")
    elif deaths is not None:
        facts_text.append(f"Official death toll (Wikipedia and Wikidata agree): {deaths:,}.")
    if hurt:
        facts_text.append(f"Injured (Wikipedia and Wikidata agree): {hurt:,}.")
    banned = [v for k, v in ib.items() if re.match(r"(perpetrators?|assailants?|attackers?|suspects?|accused)$", k)]
    series = cand.get("series") or {}
    also = series.get("also") or []
    source = "\n\n".join([wiki.article_text(t) for t in also]
                         + [wiki.article_text(article, focus=series.get("sections"))])
    if deaths is None or toll:
        # Casualty numbers only when both sources agree (or, failing that, the reporting does): strip the other
        # tolls from what the writer may use.
        source = re.sub(r"[^.]*\b(killed|dead|deaths|died|fatalit\w*|casualt\w*|injured|wounded)\b[^.]*\.", "",
                        source)
    source = re.sub(r"[^.]*\bsuicid\w*[^.]*\.", "", source, flags=re.I)
    # A headline whose names or numbers the article lacks may be about another event, or not yet verified.
    headlines = [h for h in cand.get("headlines") or [] if not ungrounded(h, source)]
    draft, log = write(kind, name, "It", facts_text, source, photos,
                       banned_names=banned, log_path=work / "writer_log.json", headlines=headlines,
                       series=cand.get("series"), reports=reports, casualties=deaths is not None)
    loss = bool(deaths) or cat in ("attack", "strike", "conflict")
    facts = [Fact("name", name, page, stories.numbers_in(name), "Wikipedia article title"),
             Fact("date", stories.date_words(when), item, [str(when.day), str(when.year)],
                  f"Google News lead story on {when}" if ongoing else f"{date_src} {when}")]
    if toll:
        facts.append(toll_fact(deaths, toll[1], reports, item if qid else None))
    elif deaths is not None:
        facts.append(Fact("deaths", str(deaths), page, [f"{deaths:,}", str(deaths)], "infobox and Wikidata P1120 agree"))
    region = stories.city_of(where) if where else None
    return _short(sid, "incident", name, draft, log, facts, facts_text, source, photos,
                  list(dict.fromkeys([page, item] + [wiki.url(t) for t in also])),
                  when.isoformat(), loss=loss, mood="news", voice=cand.get("region", "world"),
                  tags=[name, cat, "news explained", "india news" if cand.get("region") == "india" else "world news"]
                  + ([region] if region else []),
                  summary=f"{name}, {stories.date_words(when)}: what happened, from "
                          f"{'Wikipedia and Wikidata' if qid else 'Wikipedia'}.",
                  hashtags=[cat, region or "world", "news"], reports=reports)


def _short(sid, kind, name, draft, log, facts, facts_text, source, photos, sources, event_time, loss, mood, tags,
           summary, hashtags, voice="world", reports=None, credit=CREDIT) -> Short:
    reports = reports or []
    beats = []
    for b in draft["beats"]:
        beats.append(Beat(b["say"].strip(), f"photo:{b['photo']}", {"big": b["caption"].strip(), "small": ""}))
    beats.append(Beat(OUTRO, "outro", {"big": "Orbitwire", "small": "Sources in the description"}, pause_after=0.5))
    ground = source + "\n" + "\n".join(facts_text)
    in_ground, by_owner = set(_numbers(ground)) | set(gate.numbers(ground)), gate.reported_values(reports)
    allowed = {n for f in facts for n in f.numbers}
    said = " ".join(b.text + " " + (b.card or {}).get("big", "") for b in beats) + " " + draft["title"]
    for n in sorted(set(_numbers(said)) | {n for n in gate.numbers(said) if n in in_ground or n in by_owner}):
        if n not in allowed:
            who = by_owner.get(n, [])
            if who and n not in in_ground:
                url = next(r["url"] for r in reports if r["owner"] in who)
                facts.append(Fact(f"source-{n}", n, url, [n], "reported by " + ", ".join(who), owners=who))
            else:
                facts.append(Fact(f"source-{n}", n, sources[0], [n], _sentence_with(n, ground)))
            allowed.add(n)
    title = draft["title"].strip().strip('"')
    if not 20 <= len(title) <= 70:
        title = f"Remembering {name}" if kind == "death" else f"{name}: what happened"
    if any(media.from_openverse(p) for p in photos):
        credit = credit.replace("photos: Wikimedia Commons", "photos: Wikimedia Commons and Openverse")
    if reports:
        credit += "; reporting: " + ", ".join(outlets.names(reports))
    credits = [credit] + sorted({p["credit"] + " " + p["page"] for p in photos})
    tags = [t for t in tags if t]
    scene = {"template": "story", "mood": mood, "voice": voice, "photos": photos,
             "writer": {"model": llm.DEFAULT, "rejected": log}}
    if reports:
        scene["reporting"] = [outlets.compact(r) for r in reports]
        scene["outlets"] = outlets.names(reports)
        sources = list(dict.fromkeys(sources + [r["url"] for r in reports]))
    return Short(id=sid, kind=kind, title=title[:70], beats=beats, facts=facts, sources=sources, loss=loss,
                 scene=scene, event_time=event_time, tags=tags, summary=summary, credits=credits, hashtags=hashtags)


REPORT_CREDIT = "Facts: reporting by trusted news outlets; photos: Wikimedia Commons (licences listed below)"


def story_place(name: str) -> tuple[str | None, dict]:
    """The Wikidata item of the place an nw- story names: Wikipedia's first search hit, when its title names it and
    it is a place (it has coordinates and is not a person)."""
    try:
        title = wiki.search(name)
    except Exception:
        return None, {}
    if not title or name.lower() not in title.lower():
        return None, {}
    qid = (wiki.page_info([title]).get(title) or {}).get("qid")
    ent = wiki.entities([qid]).get(qid) if qid else None
    if not ent or not media.place_like(ent):
        return None, {}
    return qid, ent


def build_report(cand: dict) -> Short:
    """A story Wikipedia has no article for yet (an nw- id, studio/outlets.py stories): told only from what at least
    two independent owners' articles say, with photos of the place it happened (Commons, then Openverse), and no
    casualty count unless the reports agree on one. Once Wikipedia writes the article, plan.told_before keeps the
    story from being told again."""
    sid, name, cat = cand["id"], cand["name"], cand["category"]
    if not trends.NEW_STORIES:
        raise ValueError("gate: stories without a Wikipedia article are off (STUDIO_NEW_STORIES)")
    when = date.fromisoformat(cand["date"])
    work = WORK / sid
    reports = _reporting(cand, name, search=False)
    if len(outlets.owners(reports)) < gate.OWNERS_NEEDED:
        raise ValueError(f"gate: fewer than {gate.OWNERS_NEEDED} independent outlets' articles about {name} could "
                         "be read")
    named = gate.reported(name, reports)
    if len(named) < gate.OWNERS_NEEDED:
        raise ValueError(f"gate: fewer than {gate.OWNERS_NEEDED} independent outlets' articles name {name}")
    # The story is named by its most-cited word, which may be a company or a building ("Aramco"): the photos then
    # show the next named place that two owners' articles also name.
    where, (qid, place) = name, story_place(name)
    for other in [] if place else cand.get("places") or []:
        if len(gate.reported(other, reports)) >= gate.OWNERS_NEEDED and (found := story_place(other))[1]:
            where, (qid, place) = other, found
            break
    context = list(dict.fromkeys(([qid] if qid else []) + incident_context(place, [])))[:4] if place else []
    photos = fill_photos(context, work / "photos", set())[:8] if context else []
    if len(photos) < MIN_PHOTOS:
        raise ValueError(f"gate: only {len(photos)} usable photos of {where} (want {MIN_PHOTOS})")
    kind = "protest" if cat in ("protest", "movement") else "incident"
    toll = gate.reported_toll(reports)
    words = [name] + sorted(outlets.headline_keys(cand["title"])[0])
    reports = clean_reports(reports, words, perpetrators=kind == "incident")
    facts_text = [f"Place: {where}.", "Wikipedia's article on this is only hours old: only the REPORTING may be used."
                  if cand.get("article") else "Wikipedia has no article on this yet: only the REPORTING may be used."]
    if toll:
        facts_text.append(f"Death toll ({toll_basis(toll[1])} agree): {toll[0]:,}.")
    banned = []
    if cat in ("attack", "strike"):
        told = {w.lower() for w in (name, where)}
        banned = [w for w in outlets.attackers((cand.get("headlines") or []) + [r["title"] for r in reports])
                  if w.lower() not in told]
    draft, log = write(kind, name, "It", facts_text, "", photos, banned_names=banned, log_path=work / "writer_log.json",
                       reports=reports, casualties=bool(toll))
    facts = [Fact("name", name, next((r["url"] for r in reports if r["owner"] in named), reports[0]["url"]),
                  stories.numbers_in(name), "named in the reports of " + ", ".join(named), owners=named)]
    if toll:
        facts.append(toll_fact(toll[0], toll[1], reports, None))
    short = _short(sid, "incident", name, draft, log, facts, facts_text, "", photos, [r["url"] for r in reports],
                   when.isoformat(), loss=bool(toll) or cat in ("attack", "strike", "conflict"), mood="news",
                   voice=cand.get("region", "world"),
                   tags=[name, cat, "news explained", "india news" if cand.get("region") == "india" else "world news"],
                   summary=f"{name}: what happened, from the reporting of {', '.join(outlets.names(reports))}.",
                   hashtags=[cat, name, "news"], reports=reports, credit=REPORT_CREDIT)
    short.scene["article"] = cand.get("article")
    short.scene["headlines"] = cand.get("headlines") or []
    return short


def build(cand: dict) -> Short:
    if (cand.get("id") or "").startswith("nw-"):
        return build_report(cand)
    return build_death(cand) if cand["kind"] == "death" else build_incident(cand)
