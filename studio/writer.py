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

from . import anchor, faces, gate, ledger, llm, media, outlets, stories, terrain, trends, wiki
from .spec import Beat, Fact, Short

WORK = Path(__file__).resolve().parents[1] / "work"
MIN_PHOTOS, TRIBUTE_PHOTOS = gate.MIN_PHOTOS, gate.TRIBUTE_PHOTOS
WANT_PHOTOS = 3  # fill photos are looked for until a story has this many
PLACE_FACE = 0.06  # a face this share of a place photo's shorter side features a person
# The end card is silent: the story's own last beat closes it, with what happens next or why it matters. Until
# 2026-10-22 every Short ended on the same spoken "Follow Orbitwire for the stories the whole world is talking
# about.", 4 seconds of narration identical on every upload.
OUTRO = ""
END_CARD = 2.0  # seconds the silent end card (logo, sources, disclosure) holds
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
        "hook": {"type": "string"},
        "beats": {"type": "array", "minItems": 6, "maxItems": 9, "items": {
            "type": "object",
            "properties": {"say": {"type": "string"}, "photo": {"type": "integer"}, "caption": {"type": "string"}},
            "required": ["say", "photo", "caption"]}},
    },
    "required": ["title", "hook", "beats"],
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
1. Hook (beat 1, under 15 words): open on {name} and the single most striking verified fact about {object} from the
   SOURCE (the record, the number, the work everyone knows), then that {pronoun} has died. Never open with
   "{name} has died" or a date.
2. Where {pronoun} began, or the struggle before success.
3. The turning point or breakthrough, naming the specific work from the SOURCE.
4. The work people loved most, and what made {object} different from everyone else.
5. A human detail from the SOURCE that shows who {pronoun} was off screen or off stage.
6. Legacy: what {pronoun} leaves behind and why it matters, from the SOURCE (a work still performed, a record still
   standing, a cause others carry on). The last beat is one short, moving sentence.
Do not describe the cause or manner of death unless the SOURCE states it plainly; never mention suicide."""

INCIDENT_BRIEF = """STORY: {name}. Write a news Short that helps a viewer understand what happened and why it matters,
with compassion for everyone affected.

Shape:
1. Hook (beat 1, under 15 words): the single most striking verified fact, what happened and to whom or how many,
   naming the place or the event in its first 4 words. Where and when can wait for beat 2.
2. The moment it began, in order, as a story.
3. The people involved and what they faced, with official figures only if the SOURCE gives them.
4. The response: rescuers, officials, investigators.
5. What is still unknown or under investigation, said honestly.
6. What happens next or why it matters, from the SOURCE: the inquiry, the recovery, the rule or plan it changes,
   or where it stands now. The last beat is one short, steady sentence.
Never name or describe any attacker, perpetrator or suspect. Never guess at causes. No graphic detail of injuries or
death."""

PROTEST_BRIEF = """STORY: {name}. Write a news Short that explains, fairly and calmly, what this protest or movement is,
why people took to the streets, and where it stands now.

Shape:
1. Hook (beat 1, under 15 words): the newest and most striking development in the SOURCE, stated plainly, naming
   the movement or its place in the first 4 words.
2. How it began: the trigger, in order, as a story.
3. Who is involved and what they demand, attributed ("organisers demand", "the party says").
4. How the government, police or courts responded, attributed to them.
5. The turning point or the latest step.
6. What happens next, or what is still unresolved, from the SOURCE (the vote, the hearing, the talks, the
   deadline). The last beat is one short, steady sentence.
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
- Never say "we", "us" or "our": the narrator speaks to the whole world, not for any country. Retell an official's
  words with their name ("Carney said the nation is in mourning"), never as the narrator's own.
- Exactly {beats} beats, one for each PHOTO, and {lo} to {hi} words in total. Each beat is one or two spoken
  sentences of 12 to 20 words. Count the words before you answer.
- Every beat must carry a specific fact from the SOURCE (a work, a place, a year, an honour, a choice they made);
  feeling comes from how you tell those facts, not from vague praise.
- Tell it as a story, not a list: vary how beats open, and never start more than 2 beats with the same word
  ("She", "He", "The"). Open beats with the moment, the work, the year or the turn ("In 1954, ...", "Then came ...").
- Hook: half the viewers decide in the first second. Beat 1 opens on the name or the event within its first 4
  words and states the single most striking verified fact ("<Name>'s <best-known work> <what it did>...", not
  "On <date>, ..." or "<Name> has died."). Never open beat 1 with a date, a day, a year or "On ...".
- The last beat closes the story: what happens next or why it matters, with a specific fact from the SOURCE (the
  inquiry, the vote, the rebuilding, the record that still stands). Never a call to follow, like or subscribe, never
  the channel's name, never filler ("only time will tell", "remains to be seen", "the world will be watching").
- Write numbers as digits (1994, 75). Use a year only when it helps the story.
- Respectful, warm English. No slang, no hype ("shocking", "insane", "legendary", "breaking"), no "RIP", no emojis,
  no questions to the viewer, no request to like or follow.
- photo: the index of the PHOTO the beat shows, and the beat names what that photo shows. A PERSON photo goes on
  a beat that names that person; a THING or PLACE photo on a beat that names it; an EVENT photo on a beat about the
  event itself that names nobody else. The names a beat can say to show a photo: {shows}. A beat that names
  someone who has no photo here has nothing to show: name such people rarely, and never in beat 1. Beat 1 uses
  photo {best}. A photo marked MAP goes on one beat at most, never beat 1: a beat whose point is where it happened,
  naming that place and nobody else. A photo marked SETTING goes only on a beat that names that town. Every photo goes on
  exactly one beat: never show a photo twice.
- caption: 1 to 4 words shown on screen that match what the beat says: the exact work title it names with its year,
  a role, an honour, or a year. Never a place name: viewers read a place over a photo as where the photo was taken.
- hook: 3 to 6 words shown big over the first photo: the claim beat 1 opens on, in beat 1's own words (a number,
  the event, the work). Never a date, a question or hype.
- title: 30 to 60 characters in normal title case, factual, no clickbait. Searchable core first: the name or place
  and what happened ("<Full Name>, <Known For>, Dies at <Age>"; "<Place> <Event>: <What Happened>"), with
  "{name}" or its key words in the first 4 words. Where the SOURCE states how it came about or what it led to,
  frame the title on that ("How <Name> <specific outcome>": "How Hurricane Milton Grew to Category 5 in a Day";
  "Why <Name> <specific outcome>"; "<Name> Exists Because of <specific cause>"), with the outcome or cause said in
  the script too. Never a question mark or a vague tease ("What Happened Next", "The Real Reason"), and never "Why"
  for a cause the SOURCE calls unknown or under investigation. Never open with "The Legacy of", "A Tribute to",
  "The Life and Legacy" or "The Path of", and never reuse the opening words of a recent title.
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


def ordinary(key: str) -> bool:
    """An ordinary English word or a plain inflection of one: the lexicon has "face" and "forecast" but not "faces",
    "forecasts" or "portraying"."""
    words = english()
    if key in words:
        return True
    stems = []
    if key.endswith("ies"):
        stems.append(key[:-3] + "y")
    if key.endswith("es"):
        stems.append(key[:-2])
    if key.endswith("s"):
        stems.append(key[:-1])
    for suffix in ("ing", "ed"):
        if key.endswith(suffix):
            base = key[:-len(suffix)]
            stems += [base, base + "e"] + ([base[:-1]] if len(base) > 2 and base[-1] == base[-2] else [])
    return any(len(s) > 2 and s in words for s in stems)


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
        if len(key) < 2 or ordinary(key) or re.search(r"\b" + re.escape(key) + r"\b", low):
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


SETTING_NOTE = " [SETTING: shows only the town or area, not what happened]"
MAP_NOTE = " [MAP: shows where it happened, not what happened]"


def _note(photo: dict) -> str:
    return SETTING_NOTE if photo.get("role") == "setting" else MAP_NOTE if photo.get("role") == "map" else ""


SHOWS_NOTE = {"event": " [EVENT: shows the story itself]", "person": " [PERSON: shows {0}]",
              "thing": " [THING: shows {0}]", "place": " [PLACE: shows {0}]", "setting": SETTING_NOTE,
              "map": " [MAP of {0}: shows where it happened, not what happened]", "view": ""}


def shows_note(story: anchor.Story, i: int) -> str:
    """What photo i shows, as the writer's PHOTOS list marks it ("[PERSON: shows Emmanuel Macron]")."""
    kind, terms = story.kinds[i], story.terms[i]
    return SHOWS_NOTE[kind].format(terms[0] if terms else "it")


def best_photo(story: anchor.Story) -> int:
    """The photo beat 1 opens on: the story's own picture (the event, or the person it is about), never a map."""
    own = sorted(story.defaults)
    return own[0] if own else next((i for i, k in enumerate(story.kinds) if k != "map"), 0)


def _messages(brief: str, facts: list[str], source: str, photos: list[dict], name: str,
              headlines: list[str] | None = None, reports: list[dict] | None = None,
              recent: list[str] | None = None, story: anchor.Story | None = None) -> list[dict]:
    story = story or anchor.Story(photos, name)
    listing = "\n".join(f"{i}: {p.get('description') or p['file']}" + shows_note(story, i)
                         for i, p in enumerate(photos))
    if story.unshown:
        listing += "\nNo photo of: " + ", ".join(story.unshown)
    lead = ""
    if headlines:
        lead = ("\n\nTODAY'S LEAD HEADLINES (context only: use them to choose the angle and what to put first, but "
                "state only facts that are in CONFIRMED FACTS or SOURCE):\n" + "\n".join(f"- {h}" for h in headlines))
    user = (brief + "\n\nCONFIRMED FACTS:\n" + "\n".join(f"- {f}" for f in facts)
            + ("\n\nSOURCE (Wikipedia):\n" + source if source else "") + reporting_block(reports)
            + lead + "\n\nPHOTOS:\n" + listing + "\n\n"
            + RULES.format(best=best_photo(story), name=name, beats=beat_count(photos), lo=13 * beat_count(photos),
                           hi=17 * beat_count(photos),
                           shows=", ".join(story.showable()) or "none (tell it over the EVENT photos)")
            + ("\nREPORTING counts as a SOURCE under its own rule: " + REPORTING_RULE + "." if reports else "")
            + ("\n\nRECENT TITLES (the title never starts with the same 3 words as any of these):\n"
               + "\n".join(f"- {t}" for t in recent) if recent else ""))
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


PLACE_CAPTION = re.compile(r"\b(Airport|Hospital|Medical Complex|Station|Junction|Terminal|Province|County|District|Street|Square|"
                           r"Bridge|Harbou?r|Mosque|Cathedral|Church|Temple|Stadium)s?\b")
# The narrator speaks to the whole world: "our armed forces" in Carney's statement, retold unquoted, made Orbitwire
# sound Canadian (CFB Wainwright, 2026-10-20). Lower-case "us" only, so "the US" passes.
FIRST_PERSON = re.compile(r"\b(?:[Ww]e|us|[Oo]urs?|[Oo]urselves)\b")
QUOTED = re.compile(r"[\"“][^\"”]*[\"”]")


COUNT_WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve "
                                          "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
_COUNT = r"(?P<n>\d+|" + "|".join(COUNT_WORDS) + r")"
TOLL_SAID = re.compile(_COUNT + r"\b[^.;]{0,60}?\b(?:killed|dead|died|lost their lives)\b", re.I)
# "Five people were killed at the scene, including the shooter": a script that drops the last words tells
# viewers five victims died (Silver Rail, 2026-10-16 test render).
WITH_PERPETRATOR = re.compile(TOLL_SAID.pattern + r"[^.;]{0,60}?\bincluding (?:the |a )?(?:shooter|gunman|attacker|"
                              r"perpetrator|suspect|bomber|assailant)s?\b", re.I)


def _count(word: str) -> int | None:
    return int(word) if word.isdigit() else COUNT_WORDS.get(word.lower())


def tolls_with_perpetrator(ground: str) -> set[int]:
    """Death tolls the sources state as including the attacker."""
    return {n for m in WITH_PERPETRATOR.finditer(ground) if (n := _count(m.group("n"))) is not None}


# Beat 1 and the title open on the story (2026-10-20 hook plan, ported from the Hindi desk's HOOK_WORDS): tributes
# opening "X has died" held 41-43% of viewers for 16-19 s, against 64-101% for Shorts opening on the event itself.
HOOK_WORDS = 4  # the name or the event starts within beat 1's first 4 words
HOOK_CLAIM = (3, 6)  # words in the on-screen hook claim
_MONTHS = ("january february march april may june july august september october november december "
           "jan feb mar apr jun jul aug sep sept oct nov dec").split()
_DAYS = "monday tuesday wednesday thursday friday saturday sunday".split()
# "On 12 October, ...", "In 2026, ...", "Early on Monday ...", "Last week ...", "Today ...": a dateline makes the
# viewer wait for the news. Not a dateline: a bare year or count that starts a noun ("The 2026 Kenyan protests drew",
# "4000 homes"), a compound ("Late-night host", "This year's"), or the story's own name ("June Carter Cash's voice").
DATELINE = re.compile(r"^\W*(?:(?:on|in|at|by|since|during|early|late|last|this|earlier|later)\s+)*(?:the\s+)?"
                      r"(?:(?:early|late|mid)[- ]?)?(?:(?:night|morning|evening|afternoon)\s+of\s+)?"
                      r"(?:\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:" + "|".join(_MONTHS) + r")\b|(?:"
                      + "|".join(_MONTHS + _DAYS) + r")\b|today\b|tonight\b|yesterday\b|"
                      r"(?<!-)(?:morning|afternoon|evening|night|week|weekend|month|year)\b(?![-'’]))", re.I)
# A year is a dateline after a preposition ("In 2026 ...", "Since mid-2025 ...") or as a clause of its own ("2026, a
# year ..."), not when it starts a name or a count ("2026 Multan train derailment", "2000 homes").
YEAR_DATELINE = re.compile(r"^\W*(?:(?:(?:on|in|at|by|since|during|until|through|from|early|late|mid)[- ]+)+"
                           r"(?:the\s+)?(?:(?:early|late|mid)[- ]?)?(?:1[89]|20)\d{2}s?\b"
                           r"|(?:the\s+)?(?:1[89]|20)\d{2}s?\s*[,.;:—–])", re.I)
DIED = re.compile(r"\b(?:has died|had died|died|has passed away|passed away|is dead|has been killed)\b", re.I)
# Openers that made every tribute and storm title read the same (published.json to 2026-10-21).
TEMPLATE_TITLES = ("the legacy of", "a tribute to", "the life and legacy", "the path of")
RECENT_TITLES = 20
# A curiosity title ("How Hurricane Milton Grew to Category 5 in a Day") claims a cause or an outcome, so the evidence
# check reads it with the beats; a tease that names no outcome is clickbait, sent back like a template opener.
# Name-first titles claim one too ("Hurricane Milton: Why Tampa Bay Was Spared", "... Because of Warm Water"; the
# pre-push review, 2026-10-22), so How/Why after a colon or dash and cause words anywhere count.
CURIOUS = re.compile(r"(?:^|[:–—-]\s*)(?:part \d+\s*:\s*)?(?:how|why)\b|\bbecause\b|\b(?:led to|leads to|caused|"
                     r"causes|thanks to|due to|the reason)\b", re.I)
TEASE = re.compile(r"\?|\b(?:what happened next|what happens next|the real reason|the truth about|here'?s why|"
                   r"this is why|no one expected|nobody expected|what really happened)\b", re.I)
_TITLE_STOP = set("a an the of and in on at to for by with from as is was its his her their part".split())
_PART = re.compile(r"^\s*Part \d+\s*:\s*", re.I)


def _words(text: str) -> list[str]:
    """Lower-case words without punctuation or a possessive 's."""
    cut = (w.strip(".,;:!?\"“”()—–-'") for w in re.sub(r"['’]s\b", "", text.lower()).replace("’", "'").split())
    return [w for w in cut if w]


def key_words(name: str) -> list[str]:
    """The words of a story's name a hook or title must open on: not years, numbers or small words."""
    return [w for w in _words(name) if not w.isdigit() and w not in _TITLE_STOP and w not in COMMON
            and w not in _MONTHS and len(w) > 1]


def _names(words: list[str], keys: list[str]) -> bool:
    """A word list names the story when one of its words is a key word or shares its first 5 letters
    ("derailed" for "derailment")."""
    return any(w == k or (len(k) > 5 and len(w) > 4 and w[:5] == k[:5]) for w in words for k in keys)


def opens_on(text: str, name: str) -> bool:
    """The text starts with the story's name (its first two words, past a leading "the"): "June Carter Cash's voice",
    "The 2026 Kenyan protests drew"."""
    def head(t: str) -> list[str]:
        w = _words(t)
        return w[1:] if w[:1] == ["the"] else w
    lead = head(name)[:2]
    return bool(lead) and head(text)[:len(lead)] == lead


def hook_problems(say: str, name: str) -> list[str]:
    """Beat 1 must open on the story: the name or the event within its first HOOK_WORDS words, never a dateline,
    and never "<name> has died" as the whole opener."""
    problems = []
    if (DATELINE.match(say) or YEAR_DATELINE.match(say)) and not opens_on(say, name):
        problems.append(f"beat 1 opens on a date or time ({' '.join(say.split()[:3])!r}): open on {name} and the most "
                        "striking fact; where and when can wait for beat 2")
    words, keys = _words(say), key_words(name)
    if keys and not _names(words[:HOOK_WORDS - 1 + max(1, len(name.split()))], keys):
        problems.append(f"beat 1 must open on {name}: the name or the event within its first {HOOK_WORDS} words")
    died = DIED.search(say)
    before = say[:died.start()] if died else ""
    if died and name.split()[-1].lower() in before.lower() and len(before.split()) < len(name.split()) + 5:
        problems.append(f"beat 1 opens with \"{name} has died\": open on the most striking fact about {name} and "
                        "say that they died after it")
    return problems


def recent_titles(n: int = RECENT_TITLES) -> list[str]:
    """The last n published titles."""
    return [r["title"] for r in ledger.published()[-n:] if r.get("title")]


def _opening(title: str, n: int = 3) -> tuple[str, ...]:
    return tuple(_words(_PART.sub("", title))[:n])


def names_story(title: str, keys: list[str]) -> bool:
    """A title about the same story: every key word of its name leads it ("Part 1: Cockroach Janta Party Takes
    Delhi" for "Cockroach Janta Party")."""
    lead = _words(_PART.sub("", title))[:HOOK_WORDS + len(keys)]
    return bool(keys) and all(_names(lead, [k]) for k in keys)


def title_problems(title: str, name: str, recent: list[str]) -> list[str]:
    """No template opener, no opening shared with a recent title, and the story's name or key words up front."""
    problems = []
    plain = _PART.sub("", title).strip().lower()
    if opener := next((t for t in TEMPLATE_TITLES if plain.startswith(t)), None):
        problems.append(f"the title opens with the template {opener.title()!r}: put {name} and what happened first")
    if tease := TEASE.search(title):
        problems.append(f"the title teases with {tease.group(0)!r}: state the specific outcome or cause from the "
                        "SOURCE instead (\"How <Name> <what it did>\")")
    head, keys = _opening(title), key_words(name)
    # A series part or a returning ongoing story must lead with its name, as its earlier titles did: only other
    # stories' titles count ("Part 2: Cockroach Janta Party ..." after Part 1).
    others = [t for t in recent if not names_story(t, keys)]
    if len(head) == 3 and (same := next((t for t in others if _opening(t) == head), None)):
        problems.append(f"the title starts like the recent title {same!r}: open with different words")
    if keys and not _names(_words(_PART.sub("", title))[:HOOK_WORDS], keys):
        problems.append(f"the title must lead with {name} or its key words in the first {HOOK_WORDS} words, then "
                        "what happened")
    return problems


def _own_hook(draft: dict) -> str | None:
    """The writer's hook, cleaned, when it is 3-6 of beat 1's own words with no hype, question or first person."""
    beats = draft.get("beats") or []
    if not beats:
        return None
    hook = " ".join((draft.get("hook") or "").split()).strip(" .,;:")
    own = set(_words(beats[0].get("say", "") + " " + beats[0].get("caption", "")))
    lo, hi = HOOK_CLAIM
    if lo <= len(hook.split()) <= hi and not re.search(r"[?!]", hook) and all(w in own for w in _words(hook)) \
            and not gate.banned_word(hook) and not FIRST_PERSON.search(hook):
        return hook
    return None


def hook_claim(draft: dict) -> str:
    """The 3-6 word claim shown over the first photo: the writer's hook (_own_hook), else beat 1's opening clause
    when it is 3-6 words long. Empty otherwise (the first frame then keeps the name card): a clause cut mid-way
    reads as a broken sentence."""
    if hook := _own_hook(draft):
        return hook
    beats = draft.get("beats") or []
    first = re.split(r"[.;:!?—–]|,\s", beats[0].get("say", ""), maxsplit=1)[0].split() if beats else []
    return " ".join(first) if HOOK_CLAIM[0] <= len(first) <= HOOK_CLAIM[1] else ""


def hook_text_problems(draft: dict) -> list[str]:
    """A hook the first frame cannot show, asked to be rewritten on the early drafts only: a last draft that passes
    everything else falls back to hook_claim instead of losing the story."""
    if _own_hook(draft):
        return []
    return [f"the hook {draft.get('hook', '')!r} must be {HOOK_CLAIM[0]} to {HOOK_CLAIM[1]} of beat 1's own words, "
            "with no question, exclamation or hype"]



# Owner, 2026-10-23: "if a single map or place is shown multiple times it spoils the whole interest of watching."
# Every photo is on one beat, so a Short has as many beats as photos (at most MAX_BEATS): fewer photos, a shorter Short.
MAX_BEATS = 8


def beat_count(photos: list[dict]) -> int:
    return min(len(photos), MAX_BEATS)


def _validate(draft: dict, photos: list[dict], name: str, ground: str, banned_names: list[str],
              reports: list[dict] | None = None, casualties: bool = True, recent: list[str] | None = None,
              style: bool = True, story: anchor.Story | None = None) -> list[str]:
    problems = []
    beats = draft.get("beats", [])
    words, n = sum(len(b["say"].split()) for b in beats), beat_count(photos)
    if not 11 * n <= words <= 19 * n:
        problems.append(f"the script has {words} words; it must have {13 * n} to {17 * n}")
    if len(beats) != n:
        problems.append(f"the script has {len(beats)} beats; it must have {n}, one for each photo")
    shown = [b["photo"] for b in beats]
    if twice := sorted({i for i in shown if shown.count(i) > 1}):
        problems.append(f"photo(s) {', '.join(map(str, twice))} are on more than one beat: show each photo on one beat "
                        "only, and write one beat for each photo")
    if not beats or name.split()[-1].lower() not in beats[0]["say"].lower():
        problems.append(f"beat 1 must name {name}")
    elif style:
        problems += hook_problems(beats[0]["say"], name)
    if style:  # hook and title style, unlike the fact checks, never cost a story: the last attempt goes without
        problems += title_problems(draft.get("title", ""), name, recent_titles() if recent is None else recent)
    for b in beats:
        if not 0 <= b["photo"] < len(photos):
            problems.append(f"photo {b['photo']} does not exist")
    setting = {i for i, p in enumerate(photos) if p.get("role") == "setting"}
    if beats and beats[0]["photo"] in setting:
        problems.append(f"beat 1 uses photo {beats[0]['photo']}, which only shows the town: open on photo 0")
    if sum(b["photo"] in setting for b in beats) > 1:
        problems.append("a SETTING photo is on more than one beat: use it only on the beat that says where it "
                        "happened, and show what each other beat says")
    if beats and all(0 <= b["photo"] < len(photos) for b in beats):
        problems += shown_problems(draft, story or anchor.Story(photos, name))
    judged = story or anchor.Story(photos, name)
    judged.prepare([b["say"] for b in beats])
    if who := judged.title_faceless(draft.get("title", "")):
        # The gate refuses a title naming someone with no photo here (review round 2): rewrite it, keep the story.
        problems.append(f"the title names {', '.join(who)}, who has no photo here: title the event, not them")
    # The publish gate's wording rules (studio/gate.py), checked here so a slip is rewritten, not the story dropped.
    lines = [("the title", draft.get("title", "")), ("the hook", draft.get("hook", ""))] + [
        (f"beat {i + 1}", f"{b['say']} {b['caption']}") for i, b in enumerate(beats)]
    for where, line in lines:
        if word := gate.banned_word(line):
            problems.append(f"{where} uses the banned word {word!r}: say it plainly without that word")
        if hit := FIRST_PERSON.search(QUOTED.sub("", line)):
            problems.append(f"{where} says {hit.group(0)!r}: the narrator never speaks for a country or group; "
                            "attribute the words to whoever said them (\"Carney said the nation is in mourning\")")
        if not casualties and (hit := gate.CASUALTY.search(line)):
            problems.append(f"{where} says {hit.group(0)!r}: the sources agree on no toll, so never mention deaths, "
                            "injuries or casualties")
    for i, b in enumerate(beats):
        if PLACE_CAPTION.search(b["caption"]):
            problems.append(f"beat {i + 1}'s caption {b['caption']!r} names a place, which viewers read as where the "
                            "photo was taken: caption a date, a figure, a role or a work instead")
    text = " ".join(b["say"] + " " + b["caption"] for b in beats) + " " + draft.get("title", "") + " " + \
        draft.get("hook", "")
    grounded = set(gate.numbers(ground)) | set(_numbers(ground))
    loose = [n for n in gate.numbers(text) if n not in grounded and not reported_ok(n, reports)]
    bad = list(dict.fromkeys([b for b in ungrounded(text, ground) if not reported_ok(b, reports)] + loose))
    if bad:
        single = [b for b in bad if reports and (gate.reported_values(reports).get(b) or gate.reported(b, reports))]
        problems.append("these names or numbers are not in the sources: " + ", ".join(bad)
                        + (f" ({', '.join(single)} only in one outlet's report: one outlet is not enough)"
                           if single else ""))
    for n in tolls_with_perpetrator(ground):
        for where, line in lines:
            if any(_count(m.group("n")) == n for m in TOLL_SAID.finditer(line)):
                problems.append(f"{where} says {n} died, but the sources' {n} counts the attacker: never say that "
                                "total; say who the victims were (\"three children and a teacher were killed\")")
    for person in banned_names:
        for token in re.findall(r"[A-Z][a-z]{2,}", person):
            # "Houthi" also bans "Houthis", "Russia" also "Russian" and "Russians"
            if re.search(r"\b" + token + r"(?:s|n|ns|i|is)?\b", text):
                problems.append(f"never name a perpetrator or attacker ({token})")
    return problems


# A last beat that closes on nothing the story says: a call to action or a filler line.
GENERIC_CLOSE = re.compile(
    r"\b(?:follow (?:us|along|orbitwire|for)|subscribe|like and share|stay tuned|orbitwire|only time will tell|"
    r"remains? to be seen|"
    r"the world (?:is|will be) watching|the whole world is talking|watch this space)\b", re.I)


def closing_problems(draft: dict) -> list[str]:
    """A last beat that ends on a call to action or filler instead of what happens next or why it matters, asked to
    be rewritten on the early drafts only (like the hook): the fact check already holds every word to the sources."""
    beats = draft.get("beats") or []
    if not beats or not (hit := GENERIC_CLOSE.search(beats[-1].get("say", ""))):
        return []
    return [f"the last beat says {hit.group(0)!r}: close on what happens next or why it matters, with a fact from "
            "the SOURCE (the inquiry, the vote, the rebuilding), never a call to follow or a filler line"]


def monotone(draft: dict) -> list[str]:
    """Openings repeated so often that the script reads as a list."""
    openers = [re.sub(r"\W", "", b["say"].split()[0]).lower() for b in draft.get("beats", []) if b["say"].split()]
    return [f"{openers.count(w)} beats start with \"{w.capitalize()}\"; start at most 2 beats with the same word"
            for w in sorted(set(openers)) if openers.count(w) > 2]


def shown_problems(draft: dict, story: anchor.Story) -> list[str]:
    """The publish gate's picture rules (gate.pictures) on a draft, asked to be rewritten: the beats that show
    something they do not name, and a map on a beat not about where."""
    beats = draft.get("beats") or []
    texts = [b["say"] for b in beats]
    got = story.judge(texts, [b["photo"] for b in beats])
    problems = []
    if got["shown"] < anchor.SHOWN_SHARE:
        names = ", ".join(story.showable()) or "the event itself"
        problems.append(f"beat {', '.join(str(k + 1) for k in got['unanchored'])} name(s) nothing its photo shows "
                        f"(only {got['shown']:.0%} of the script shows what it says; want {anchor.SHOWN_SHARE:.0%}): "
                        f"in each, name who or what a photo shows ({names}), or say what an EVENT photo itself shows "
                        "(the words of its description: the march, the smoke, the police line) without naming "
                        "someone who has no photo")
    if got["bad_maps"] or got["maps"] > anchor.MAP_SHARE or got["map_photos"] > anchor.MAX_MAPS:
        problems.append("a MAP may stand only under one beat whose point is where it happened, naming that place "
                        "and nobody else, and never beat 1")
    return problems


def anchor_photos(draft: dict, story: anchor.Story) -> dict:
    """Each beat's photo decided by code (anchor.Story.assign), not left to the model: the photo the beat names,
    else a photo of the event, else the map for a beat about where. The naming word is kept for compose's cut."""
    beats = draft.get("beats") or []
    texts = [b.get("say", "") for b in beats]
    picked = story.assign(texts, [b.get("photo") for b in beats])
    if beats and len(story.photos) >= len(beats):
        # The general picker permits repeats; this writer requires each picture once. Match the entire
        # script before validating it, so an early flexible beat cannot consume a later beat's only picture.
        weights = [max(len(t.split()), 1) for t in texts]
        maps = [i for i, kind in enumerate(story.kinds) if kind == "map"][:anchor.MAX_MAPS]
        options = []
        for k, text in enumerate(texts):
            fits = [i for i, kind in enumerate(story.kinds) if story.fits(text, i, k == 0)
                    and (kind != "map" or i in maps and weights[k] / sum(weights) <= anchor.MAP_SHARE)]
            preferred = [picked[k][0], *story.named(text)]
            options.append(sorted(fits, key=lambda i: (story.kinds[i] == "map",
                                                       preferred.index(i) if i in preferred else len(preferred), i)))
        owner: dict[int, int] = {}

        def match(k: int, seen: set[int]) -> bool:
            for i in options[k]:
                if i in seen:
                    continue
                seen.add(i)
                if i not in owner or match(owner[i], seen):
                    owner[i] = k
                    return True
            return False

        # Keep the opening and longer spoken beats anchored first when not every beat can be shown.
        for k in sorted(range(len(beats)), key=lambda k: (k != 0, -weights[k], len(options[k]), k)):
            match(k, set())
        assigned = {k: i for i, k in owner.items()}
        for k in range(len(beats)):
            if k not in assigned:
                unused = [i for i in range(len(story.photos)) if i not in assigned.values()]
                assigned[k] = min(unused, key=lambda i: (story.kinds[i] == "map", i != picked[k][0], i))
        # An unmatched beat is still unanchored: the unchanged relevance and map gates hold it or request repair.
        picked = [(assigned[k], story.word(text, assigned[k])) for k, text in enumerate(texts)]
    for b, (i, word) in zip(beats, picked):
        b["photo"], b["anchor"] = i, word
        if b.get("caption") and not story.caption_fits(b["caption"], i):
            b["caption"] = ""  # no card rather than one that claims what the photo does not show
    return draft


TITLE_LINE = "TITLE: "


def title_flag(verdict: dict, lines: list[str], flagged: dict[int, str]) -> dict[int, str]:
    """The curiosity title is the last line checked: a verdict the checker left out counts against it (a beat left out
    is let through by check_verdict), and its problem says it is the title, so the rewrite fixes the right thing."""
    n = len(lines)
    if not any(row.get("line") == n for row in verdict.get("lines", [])):
        flagged = flagged | {n: f"line {n} ({lines[n - 1][:60]}): no verdict"}
    if n in flagged:
        rest = flagged[n].split("): ", 1)[-1]
        flagged = flagged | {n: f"the title ({lines[n - 1][len(TITLE_LINE):][:60]}): {rest}"[:300]}
    return flagged


def plain_title(kind: str, name: str, series: dict | None = None) -> str:
    """The title that claims nothing beyond the name: _short's fallback, with a series part's "Part N: "."""
    title = f"Remembering {name}" if kind == "death" else f"{name}: what happened"
    return f"Part {series['part']}: {title}" if series else title


def write(kind: str, name: str, pronoun: str, facts: list[str], source: str, photos: list[dict],
          banned_names: list[str] | None = None, model: str | None = None,
          log_path: Path | None = None, headlines: list[str] | None = None,
          series: dict | None = None, reports: list[dict] | None = None,
          casualties: bool = True, people: list[str] | None = None) -> tuple[dict, list[str]]:
    """The script as {title, beats: [{say, photo, caption}]} plus the log of rejected drafts (also kept at log_path).
    kind is "death", "incident" or "protest". reports: trusted outlets' articles ({outlet, owner, at, title, excerpt,
    text}), see the module docstring. casualties: False when no toll is agreed, so the script may not speak of any.
    people: the people the reporting names (with a photo here or without), for the picture rules (studio/anchor.py)."""
    obj = {"He": "him", "She": "her"}.get(pronoun, "them")
    brief = {"death": DEATH_BRIEF, "protest": PROTEST_BRIEF}.get(kind, INCIDENT_BRIEF)
    brief = brief.format(name=name, pronoun=pronoun.lower(), object=obj)
    if series:
        brief += (f"\n\nSERIES: this Short is Part {series['part']} of {series['of']} on {series['topic']}. Tell only "
                  f"this part: {series['angle']}. Beat 1 hooks with the most striking fact of this part (never a "
                  f"date, never \"is in the news\"). The title starts with \"Part {series['part']}: \".")
        brief += (f" The last beat ends by saying that Part {series['part'] + 1} tells {series['next']}."
                  if series.get("next") else " The last beat says where the story stands now.")
    recent = recent_titles()
    story = anchor.Story(photos, name, people, short_kind=kind)
    messages = _messages(brief, facts, source, photos, name, headlines, reports, recent, story)
    # A photo's Commons description is an uploader's note, not a source: no fact may come from it.
    ground = source + "\n" + "\n".join(facts)
    if series:
        ground += f"\nPart {series['part']}, Part {series['part'] + 1}, of {series['of']}. {series.get('next') or ''}"
    checked = ground + ("\n" + report_ground(reports) if reports else "")
    log, base = [], messages
    with llm.Model(model or llm.DEFAULT) as m:
        for attempt in range(3):
            try:
                raw = m.chat(messages, SCHEMA, temperature=0.75 if attempt == 0 else 0.6)
            except json.JSONDecodeError as exc:
                # The local model ran a string past its token budget (dry runs 39922617481 and 39929261269 lost the
                # story on it): a failed attempt, not a failed story. The same request is asked again.
                log.append({"attempt": attempt + 1, "problems": [f"the draft was cut off ({exc.msg})"], "draft": {}})
                continue
            draft = anchor_photos(raw, story)
            problems = _validate(draft, photos, name, ground, banned_names or [], reports, casualties, recent,
                                 style=attempt < 2, story=story)
            if attempt < 2:
                problems += monotone(draft) + hook_text_problems(draft) + closing_problems(draft)
            if not problems:
                teaser = f"part {series['part'] + 1}" if series else None
                lines = [b["say"] for b in draft["beats"] if not (teaser and b["say"].lower().startswith(teaser))]
                titled = bool(CURIOUS.search(draft.get("title", "")))
                if titled:
                    lines.append(TITLE_LINE + draft["title"].strip())
                verdict = m.chat(_check_messages(lines, facts, source, reports), CHECK_SCHEMA, temperature=0.0,
                                 max_tokens=1800)
                flagged = check_verdict(verdict, lines, checked)
                if titled:
                    flagged = title_flag(verdict, lines, flagged)
                problems = recheck(m, lines, flagged, checked)
                if titled and problems and attempt == 2 and all(p.startswith("the title") for p in problems):
                    # Every beat is supported and only the title's claim is not: the plain title costs nothing.
                    log.append({"attempt": attempt + 1, "problems": problems, "draft": dict(draft)})
                    draft["title"] = plain_title(kind, name, series)
                    problems = []
            if not problems:
                return draft, log
            log.append({"attempt": attempt + 1, "problems": problems, "draft": draft})
            if log_path:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_path.write_text(json.dumps(log, indent=1, ensure_ascii=False), encoding="utf-8")
            # Only the latest draft and its problems go back: the whole history ran the third draft past the local
            # model's 12k context (cut off at about 300 characters in 4 dry runs of 2026-10-23).
            messages = base + [{"role": "assistant", "content": json.dumps(draft)},
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
    kept = arrange(dedupe(_own_photos(title, ent, folder, person, extra_qids, files, places)))
    if len(kept) >= WANT_PHOTOS or files or not context_qids or (person and not kept):
        return kept
    return arrange(dedupe(kept + fill_photos(context_qids, folder, {r["file"] for r in kept},
                                             WANT_PHOTOS - len(kept))))[:8]


SAME_PICTURE = 10  # of 63 bits: a crop, a black-and-white copy or a re-encode of one picture


def picture_hash(path: str):
    """A 63-bit perceptual hash of a photo's greyscale thumbnail (DCT, as pHash), None if it cannot be read."""
    import numpy as np

    try:
        img = cv2.imread(path) if path else None
        if img is None or getattr(img, "size", 0) == 0:
            return None
        grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
        if float(grey.std()) < 1.0:
            return None  # a blank frame tells no picture from another
        small = cv2.resize(grey, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
        d = cv2.dct(small)[:8, :8].flatten()[1:]
    except Exception:  # an unreadable or odd file is counted as its own picture
        return None
    return d > np.median(d)


def _taken_at(p: dict) -> str:
    """The time a photo was taken, to the second, when its date field gives one."""
    m = re.search(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}", p.get("date") or "")
    return m.group(0).replace("T", " ") if m else ""


def same_picture(a: dict, b: dict, ha, hb) -> bool:
    """Two files of one picture: the hashes agree (or one is the other's negative), or two authors give the same
    second it was taken."""
    if ha is not None and hb is not None:
        d = int((ha != hb).sum())
        if d <= SAME_PICTURE or d >= ha.size - SAME_PICTURE:
            return True
    t = _taken_at(a)
    return bool(t) and t == _taken_at(b) and (a.get("author") or "") != (b.get("author") or "")


def dedupe(photos: list[dict]) -> list[dict]:
    """One file per picture (review round 2, 2026-10-23): a tribute's "three photos" were two, one a black-and-white
    copy of another photographer's CC BY-SA photo re-released as CC0 under the copier's name. Of two copies the
    earlier upload is kept, with its own author and licence, in the place of the first; a photo counts once."""
    hashes = [picture_hash(p.get("path") or "") for p in photos]
    kept: list[int] = []
    for i, p in enumerate(photos):
        dup = next((k for k, j in enumerate(kept) if same_picture(photos[j], p, hashes[j], hashes[i])), None)
        if dup is None:
            kept.append(i)
            continue
        j = kept[dup]
        first, other = photos[j].get("uploaded") or "", p.get("uploaded") or ""
        if other and (not first or other < first):
            kept[dup] = i
        print(f"same picture: kept {photos[kept[dup]].get('file')}, dropped "
              f"{photos[i if kept[dup] == j else j].get('file')}", flush=True)
    return [photos[i] for i in kept]


def arrange(photos: list[dict], category: str | None = None) -> list[dict]:
    """Photos of what the story is about first (for a rail, air or sea incident, those showing the vehicle, line or
    station before the rest), then at most gate.MAX_SETTING of the town or area it happened in."""
    subject = [p for p in photos if p.get("role") != "setting"]
    subject.sort(key=lambda p: not gate.showing(category, [p]) if category in gate.SHOWS else False)
    return subject + [p for p in photos if p.get("role") == "setting"][:gate.MAX_SETTING]


def fill_photos(context_qids: list[str], folder: Path, exclude: set[str], need: int = WANT_PHOTOS) -> list[dict]:
    """Photos of the places and things a story links to that feature no face: Commons (each item's main image and
    files from its article naming it), then, while fewer than `need`, Openverse photos naming the item. The Hindi
    desk excludes the same photos from a shared story (hindi-news-desk desk/orbitwire.py photo_pool)."""
    kept = _faceless(media.context(context_qids, exclude=exclude), folder / "context")
    if len(kept) < need:
        try:
            found = media.openverse_for(context_qids, exclude=exclude | {r["file"] for r in kept})
        except Exception:
            found = []
        kept += _faceless(found, folder / "openverse")
    return kept


def nasa_photos(category: str | None, names: list[str], when: date, folder: Path, exclude: set[str],
                need: int) -> list[dict]:
    """NASA's own public-domain photos of a natural disaster taken from 2 days before its date on (media.nasa_for),
    with no featured face, for a storm, eruption, flood or fire whose free photos are fewer than WANT_PHOTOS."""
    if need <= 0 or category not in media.NASA_CATEGORIES:
        return []
    try:
        found = media.nasa_for(category, names, when - timedelta(days=2), limit=need, exclude=exclude)
    except Exception:
        found = []
    return _faceless(found, folder / "nasa")


def _faceless(found: list, folder: Path) -> list[dict]:
    """Downloaded photos as dicts, without any that features a face."""
    out = []
    for r in media.as_dicts(media.download(found, folder)):
        img = cv2.imread(r["path"])
        if featured_face(img, faces.detect(img) if img is not None else []):
            continue
        r["focus"] = None
        out.append(r)
    return out


VEHICLE_WORD = {"rail": "train", "aviation": "aircraft", "maritime": "ship"}


def vehicle_photos(category: str, qids: list[str], folder: Path, exclude: set[str], limit: int = 3) -> list[dict]:
    """For a rail, air or sea incident whose photos show too little of what was involved: Commons photos found by the
    names of the train, line, operator, airline or ship it links to ("Pakistan Railways" train), with no featured
    face. Never of a town or a country."""
    found = []
    for e in wiki.entities(qids).values() if qids else ():
        name = wiki.label(e)
        if not name or media.too_wide(e) or media.role_of(e) == "setting":
            continue
        try:
            found += media.named(name, VEHICLE_WORD[category], exclude=exclude | {p.file for p in found})
        except Exception:
            continue
        if len(found) >= limit:
            break
    return stamp([r for r in _faceless(found[:limit], folder / "named") if gate.showing(category, [r])], "thing",
                 [VEHICLE_WORD[category]])


def stamp(photos: list[dict], kind: str, shows: list[str] | tuple = ()) -> list[dict]:
    """Mark what photos show (studio/anchor.py), leaving a stamp made where they were found."""
    for p in photos:
        if not p.get("kind"):
            p["kind"], p["shows"] = kind, [s for s in shows if s]
    return photos


def event_photos(names: list[str], when: date, category: str | None, folder: Path, exclude: set[str],
                 limit: int = 4, places: list[str] | None = None) -> list[dict]:
    """Free photos of the event itself (media.event: its own Commons category, then recent uploads naming it, taken
    within media.window of its date, each showing where it came from), found by the event's own name (names[0]) and
    never by a town or a country (places only order its subcategories), with no featured face: a stranger in
    close-up would be passed off as part of the story. [] when Commons has none or cannot be read."""
    try:
        found = media.event(names[:1], when, category, limit=limit, exclude=exclude, places=places)
    except Exception:
        found = []
    return stamp(_faceless(found, folder / "event"), "event")


# Things reporting names whose own photo shows what a beat says ("Riot police fired tear gas"): searched on Commons
# with the country, and kept only when the file names both. Never weapons or rioters: no free photo shows the ones
# in the story.
THINGS = ("police", "parliament", "school", "court", "hospital", "embassy")


def thing_photos(reports: list[dict], country: str, folder: Path, exclude: set[str], limit: int = 2,
                 need: int = gate.OWNERS_NEEDED) -> list[dict]:
    """Photos of the things at least `need` owners' reports name (THINGS), in the story's country."""
    out: list[dict] = []
    if not country:
        return out
    for word in THINGS:
        if len(out) >= limit:
            break
        if len(gate.reported(word, reports)) < need:
            continue
        try:
            found = media.named(country, word, limit=3, exclude=exclude | {p["file"] for p in out})
        except Exception:
            continue
        found = [f for f in found if anchor.says(f"{f.file} {f.description}", word)][:1]
        out += stamp(_faceless(found, folder / "things"), "thing", [word])
    return out


def named_people(name: str, reports: list[dict], limit: int = 3, need: int = gate.OWNERS_NEEDED) -> list[str]:
    """The people the reports name ("Emmanuel Macron"), at least `need` owners each (an incident passes its Wikipedia
    article as one report, need=1), as Wikipedia titles them, most named first. Each is checked to be a human on
    Wikidata (story_person). Names are runs of capitalised words, tried two and three at a time ("Prime Minister
    Giorgia Meloni" -> "Giorgia Meloni")."""
    owners: dict[str, set[str]] = {}
    times: dict[str, int] = {}
    for r in reports:
        for run in re.finditer(r"\b[A-Z][a-z\u00C0-\u017F'\-]+(?: [A-Z][a-z\u00C0-\u017F'\-]+)+", r.get("text") or ""):
            words = run.group(0).split()
            for n in (2, 3):
                for i in range(len(words) - n + 1):
                    cand = " ".join(words[i:i + n])
                    if ordinary(words[i].lower()):
                        continue
                    owners.setdefault(cand, set()).add(r["owner"])
                    times[cand] = times.get(cand, 0) + 1
    cands = sorted((c for c, o in owners.items() if len(o) >= need), key=lambda c: (-len(owners[c]), -times[c]))[:8]
    out: list[str] = []
    for cand in cands:
        try:
            title, _ = story_person(cand, reports)
        except Exception:
            continue
        if title and stories.plain_title(title) not in out and stories.plain_title(title).lower() != name.lower():
            out.append(stories.plain_title(title))
        if len(out) >= limit:
            break
    return out


def people_photos(people: list[str], folder: Path, exclude: set[str], each: int = 2) -> list[dict]:
    """Face-matched photos of each person the reporting names (studio/faces.py), at most `each` per person."""
    out: list[dict] = []
    for who in people:
        try:
            title, ent = story_person(who)
            got = pick_photos(title, ent, folder / re.sub(r"\W+", "-", who), person=True) if title else []
        except Exception:
            continue
        got = [p for p in got if p["file"] not in exclude | {q["file"] for q in out}][:each]
        out += stamp(got, "person", [who])
    return out


def caption_side(description: str | None, title: str) -> str | None:
    """"left" or "right" when a photo's caption places the person ("Tiger Shroff (left) and ..."), else None."""
    name = re.escape(stories.plain_title(title))
    m = re.search(rf"{name}\s*\((?:on the |at )?(left|right)\)", description or "", re.I)
    return m.group(1).lower() if m else None


def _own_photos(title: str, ent: dict, folder: Path, person: bool, extra_qids: list[str] | None,
                files: list[str] | None, places: bool) -> list[dict]:
    found = media.picks(files) if files else media.find(title, ent, limit=10, extra_qids=extra_qids, places=places)
    found = media.download(found, folder)
    rows = media.as_dicts(found)
    images = [cv2.imread(r["path"]) for r in rows]
    detected = [faces.detect(img) if img is not None else [] for img in images]
    picks = faces.subject(detected, [caption_side(r.get("description"), title) for r in rows]) if person \
        else [None] * len(rows)
    kept = []
    for r, f, img, seen in zip(rows, picks, images, detected):
        if person and f is None:
            continue
        if (r["origin"] == "place" or (places and r["origin"] == "article")) and img is not None \
                and featured_face(img, seen):
            continue  # a place photo that features someone would pass them off as part of the story
        r["focus"] = [round(v) for v in f["box"]] if f else None
        r["others"] = sum(g is not f and g["box"][2] * g["box"][3] >= 0.25 * f["box"][2] * f["box"][3]
                          for g in seen) if f else 0
        kept.append(r)
    if person:
        stamp(kept, "person", [stories.plain_title(title)])
    # Strangers beside the person would be shown as part of today's story: their own portraits go first.
    return sorted(kept, key=lambda r: r["others"] > 0)[:8]


# Team, employer, organisation, award and notable work. Never school (P69) or birthplace (P19): Notre Dame's campus
# stood under Richard Riehle's film roles and a Crayola store under Chuck Amato's wrestling (2026-10-22 audit).
PERSON_CONTEXT = ("P54", "P108", "P463", "P166", "P800")


def person_context(ent: dict) -> list[str]:
    """The places and things a person's life links to, whose photos may fill a tribute short of portraits."""
    return list(dict.fromkeys(c["value"] for pid in PERSON_CONTEXT for c in wiki.claims(ent, pid)[:1]
                              if isinstance(c["value"], str) and c["value"].startswith("Q")))[:6]


def incident_context(ent: dict, extra: list[str]) -> list[str]:
    """The items an incident's fill photos come from: its related items, then the place it is located in (P131)."""
    located = [c["value"] for c in wiki.claims(ent, "P131")[:1] if isinstance(c["value"], str)
               and c["value"].startswith("Q")]
    return list(dict.fromkeys(extra + located))[:4]


PLACE_FIELDS = ("location", "site", "place", "areas affected", "areas", "country")
# Infobox fields that name what was involved: the train, its line and operator, the aircraft, airline or ship, the
# stations or airports at either end, an attack's target.
SUBJECT_FIELDS = ("target", "trains", "train", "line", "operator", "aircraft_type", "aircraft", "airline", "vessel",
                  "ship", "origin", "destination", "stations")
# Article links whose names say they are such a thing ("Rehman Baba Express", "Sher Shah Junction railway station").
SUBJECT_LINK = re.compile(r"\b(Express|Mail|Railways?|railway station|Junction|Line|Metro|Bridge|Airlines?|Airways|"
                          r"Air|Airport|Flight|Boeing|Airbus|[Ff]erry|MV|MS)\b")


def _links(wikitext: str) -> list[str]:
    """Article links in order, without files, categories or other namespaces."""
    return [t.strip() for t in re.findall(r"\[\[([^\]|#]+)", wikitext) if ":" not in t and t.strip()]


BACKGROUND = re.compile(r"^==\s*(Background|History|Previous incidents|Similar incidents|See also|References|"
                        r"External links)\s*==.*?(?=^==[^=]|\Z)", re.M | re.S)


def subject_links(raw: dict, wikitext: str) -> list[str]:
    """What an incident article links to that was involved in it, infobox subject fields first, then article links
    whose names say what they are. A lower-case link ("[[passenger train]]") is a general idea, never the thing, and
    a Background section's links (where the train was launched years ago) are not where it happened."""
    links = _links(" ".join(raw.get(k, "") for k in SUBJECT_FIELDS))
    links += [t for t in _links(BACKGROUND.sub("", wikitext)) if SUBJECT_LINK.search(t)]
    return [t for t in dict.fromkeys(links) if t[:1].isupper()]


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


# Camera views of the 3D reconstruction offered to the writer in place of photos (render._bake_places shots).
VIEWS = [("overview", "3D MAP: wide view of the region, the site marked"),
         ("site", "3D MAP: close view of the marked site"),
         ("status", "3D MAP: the site from another side, with the nearest towns"),
         ("toll", "3D MAP: slow push in on the marked site")]
VIEW_CREDIT = "Facts: Wikipedia (CC BY-SA 4.0) and Wikidata (CC0); 3D terrain: Mapzen Terrain Tiles on AWS"


def site_of(article: str, ent: dict) -> tuple[float, float] | None:
    info = wiki.page_info([article]).get(article, {})
    if info.get("lat") is not None:
        return info["lat"], info["lon"]
    if ent and (c := wiki.coords(ent)):
        return c
    located = stories._places(ent, "P276") if ent else []
    return (located[0]["lat"], located[0]["lon"]) if located else None


# On (owner, 2026-10-16): a story Commons has too few photos of yet is told over its real photos plus two locator
# maps (studio/locator.py) instead of waiting days, never over maps alone. Transport incidents still need photos of
# the vehicle (gate.SHOWS), and tributes never use maps.
LOCATOR_MAPS = True
TOWN_KM = 12  # a town photo stands in for the event's own only when the site is this close to the town


def precise_site(article: str, ent: dict) -> tuple[float, float] | None:
    """Where the story happened, when a point says so: the article's or Wikidata's coordinates, or a located-in place
    that is not a whole country or province (a centroid is not a site)."""
    info = wiki.page_info([article]).get(article, {}) if article else {}
    if info.get("lat") is not None:
        return info["lat"], info["lon"]
    if ent and (c := wiki.coords(ent)):
        return c
    for c in wiki.claims(ent, "P276") if ent else []:
        place = wiki.entities([c["value"]]).get(c["value"]) if str(c["value"]).startswith("Q") else None
        if place and not media.too_wide(place) and (xy := wiki.coords(place)):
            return xy
    return None


def map_labels(where: str | None, site: tuple[float, float]) -> tuple[str, str]:
    """(close label, wide label): the site and its town and region from the infobox location ("Silver Rail Elementary
    School, Bend, Oregon, U.S." -> "Silver Rail Elementary School", "Bend, Oregon"), else the nearest town."""
    parts = [p.strip() for p in re.sub(r"\[\[|\]\]|\{\{[^}]*\}\}", "", where or "").split(",") if p.strip()]
    if parts:
        return parts[0], ", ".join(parts[1:3] if len(parts) >= 3 else parts[:2])
    try:
        town = wiki.nearby_cities(site[0], site[1], TOWN_KM, limit=1, min_pop=5000)
    except Exception:
        town = []
    return (town[0]["name"], town[0]["name"]) if town else ("", "")


def with_maps(photos: list[dict], site: tuple[float, float] | None, where: str | None, folder: Path,
              category: str | None) -> list[dict]:
    """photos and one locator map of site (the region, the site marked), for the one beat about where it happened.
    A map never makes up for missing photos (owner, 2026-10-22: "do you think people are here to watch the map"): it
    is added only beside gate.REAL_PHOTOS real photos, never to a transport incident (the vehicle shows where) or a
    story that has a map already, and the photos come back unchanged when tiles are unavailable."""
    from . import locator

    kinds = [anchor.kind_of(p) for p in photos]
    real = sum(k not in ("map", "setting") for k in kinds)
    if not LOCATOR_MAPS or not site or category in gate.SHOWS or real < gate.REAL_PHOTOS or "map" in kinds:
        return photos
    near, wide = map_labels(where, site)
    try:
        maps = locator.plates(site, near, folder / "maps", where=wide, spans=locator.SPANS[:1])
    except Exception:
        return photos
    return photos + maps[:anchor.MAX_MAPS]


def place_names(where: str | None) -> list[str]:
    """The town and the country an infobox location names ("[[Milan]], [[Italy]]" -> Milan, Italy), for finding the
    event's photos by where it happened ("Demonstrations and protests in Milan in 2026")."""
    parts = [p.strip() for p in re.sub(r"\[\[(?:[^\]|]*\|)?|\]\]|\{\{[^}]*\}\}|<[^>]+>", "", where or "").split(",")
             if p.strip()]
    return list(dict.fromkeys(parts[:1] + parts[-1:]))[:2]


FACELESS = "gate: faceless: no free photo shows"


def faceless(photos: list[dict], subject: str, sid: str = "", kind: str = "incident",
             category: str | None = None) -> str | None:
    """Why a story cannot be told over these photos, before a word is written: none of them shows the event itself
    or who or what it is named after (a map, the town or a photo of somewhere nearby never stands in). The reason
    is retried: Commons often has the event's photos a few hours later."""
    if anchor.Story(photos, subject, sid=sid, short_kind=kind, category=category or "").subject_shown(kind):
        return None
    return (f"{FACELESS} {subject} or the event itself (only "
            f"{len(photos)} photos of places or things near it)")


def in_3d(short: Short, site: tuple[float, float], label: str, when: date) -> Short:
    """Turn a script written over VIEWS into a 3D reconstruction Short, narrated like a photo story."""
    for b in short.beats:
        if b.shot.startswith("photo:"):
            b.shot = VIEWS[int(b.shot.split(":")[1])][0]
    half = 60.0
    short.scene = {k: v for k, v in short.scene.items() if k != "photos"} | {
        "template": "site", "narration": "story", "bbox": stories.bbox(site[0], site[1], half),
        "center": {"lat": site[0], "lon": site[1]}, "site": {"label": label, "sub": stories.date_words(when)},
        "route": None, "cities": stories._cities(site[0], site[1], half, set()),
        "credits": "Facts: Wikipedia · Wikidata · Terrain: Mapzen/AWS Terrain Tiles"}
    short.credits = [c for c in short.credits if not c.startswith(CREDIT.split(";")[0])] + [VIEW_CREDIT, terrain.CREDIT]
    short.beats[-1].card = {"big": "Orbitwire", "small": "3D reconstruction · not real footage"}
    short.tags = list(dict.fromkeys(short.tags + ["3D map"]))
    return short


def build_incident(cand: dict, views: bool = False) -> Short:
    """views: when the story is short of free photos, write it over 3D views of where it happened (in_3d)."""
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
        # An article Wikidata does not describe yet: what it links to (the train, the station, the target) gives the
        # photos of what happened, and the places in its infobox at most one photo of where.
        try:
            text = wiki.wikitext(article)
        except Exception:
            text = ""
        links = subject_links(raw, text) + _links(" ".join(raw.get(k, "") for k in PLACE_FIELDS))
        found = wiki.page_info(list(dict.fromkeys(links))[:8]) if links else {}
        extra = list(dict.fromkeys(found[t]["qid"] for t in dict.fromkeys(links)
                                   if (found.get(t) or {}).get("qid")))[:5]
    sid = cand.get("id") or f"wk-{qid}"
    work = WORK / sid
    photos = pick_photos(article, ent, work / "photos", person=False, extra_qids=extra, files=cand.get("photo_files"),
                         places=not qid, context_qids=incident_context(ent, extra))
    # Stamped where found (review round 1): the story's own photo is the event only when taken in its days; the
    # aircraft photographed months before is the aircraft.
    anchor.stamp_own(photos, sid, "protest" if cat in ("protest", "movement") else "incident", when, cat)
    if cat in gate.SHOWS and not cand.get("photo_files") and gate.showing(cat, photos) < gate.SHOWN_NEEDED:
        photos += vehicle_photos(cat, extra, work / "photos", {p["file"] for p in photos})
    if not cand.get("photo_files") and len(photos) < WANT_PHOTOS:
        photos += event_photos([name], when, cat, work / "photos", {p["file"] for p in photos},
                               places=place_names(stories._first(ib, *PLACE_FIELDS[:5])))
    # The people and things the article names, so a beat that names one shows it (owner, 2026-10-22: "no Macron
    # photo, no school photo").
    try:
        article_text = [{"owner": "Wikipedia", "text": "" if cand.get("photo_files") else wiki.article_text(article)}]
    except Exception:
        article_text = [{"owner": "Wikipedia", "text": ""}]
    people = named_people(name, article_text, need=1) if article_text[0]["text"] else []
    if people:
        photos += people_photos(people, work / "photos", {p["file"] for p in photos})
    if article_text[0]["text"] and cat not in gate.SHOWS:
        photos += thing_photos(article_text, (place_names(stories._first(ib, *PLACE_FIELDS[:5])) or [""])[-1],
                               work / "photos", {p["file"] for p in photos}, need=1)
    if not cand.get("photo_files") and len(photos) < WANT_PHOTOS:
        photos += nasa_photos(cat, [name], when, work / "photos", {p["file"] for p in photos},
                              WANT_PHOTOS - len(photos))
    photos = arrange(dedupe(photos), cat)[:8]
    if cat in gate.SHOWS:
        # With enough photos of the train, plane or ship, a headquarters or a town photo would only be filler.
        shown = [p for p in photos if gate.showing(cat, [p])]
        photos = shown + [p for p in photos if p not in shown][:max(0, WANT_PHOTOS - len(shown))]
    if not views and LOCATOR_MAPS:
        photos = with_maps(photos, precise_site(article, ent), stories._first(ib, *PLACE_FIELDS[:5]),
                           work / "photos", cat)
    short_of = None
    if len(photos) < MIN_PHOTOS:
        short_of = f"gate: only {len(photos)} usable photos of {name} on Wikimedia Commons (want {MIN_PHOTOS})"
    elif cat in gate.SHOWS and (n := gate.showing(cat, photos)) < gate.SHOWN_NEEDED:
        short_of = (f"gate: only {n} usable photos of {name} show the {VEHICLE_WORD[cat]}, its line or a "
                    f"station or port (want {gate.SHOWN_NEEDED})")
    elif cand.get("photo_files") is None and (why := faceless(photos, name, sid, category=cat)):
        short_of = why
    site = site_of(article, ent) if short_of and views else None
    if short_of and not site:
        raise ValueError(short_of)
    if site:
        photos = [{"file": shot, "description": text, "role": "view"} for shot, text in VIEWS]
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
                       series=cand.get("series"), reports=reports, casualties=deaths is not None, people=people)
    loss = bool(deaths) or cat in ("attack", "strike", "conflict")
    facts = [Fact("name", name, page, stories.numbers_in(name), "Wikipedia article title"),
             Fact("date", stories.date_words(when), item, [str(when.day), str(when.year)],
                  f"Google News lead story on {when}" if ongoing else f"{date_src} {when}")]
    if toll:
        facts.append(toll_fact(deaths, toll[1], reports, item if qid else None))
    elif deaths is not None:
        facts.append(Fact("deaths", str(deaths), page, [f"{deaths:,}", str(deaths)], "infobox and Wikidata P1120 agree"))
    region = stories.city_of(where) if where else None
    short = _short(sid, "incident", name, draft, log, facts, facts_text, source, [] if site else photos,
                   list(dict.fromkeys([page, item] + [wiki.url(t) for t in also])),
                   when.isoformat(), loss=loss, mood="news", voice=cand.get("region", "world"),
                   tags=[name, cat, "news explained", "india news" if cand.get("region") == "india" else "world news"]
                   + ([region] if region else []),
                   summary=f"{name}, {stories.date_words(when)}: what happened, from "
                           f"{'Wikipedia and Wikidata' if qid else 'Wikipedia'}.",
                   hashtags=[cat, region or "world", "news"], reports=reports, people=people, category=cat)
    if site:
        label = name if len(name) <= 22 else region or stories.city_of(where) or name[:22]
        short = in_3d(short, site, label, when)
    return short


def _short(sid, kind, name, draft, log, facts, facts_text, source, photos, sources, event_time, loss, mood, tags,
           summary, hashtags, voice="world", reports=None, credit=CREDIT, subject=None, people=None,
           category=None) -> Short:
    reports = reports or []
    beats = []
    for b in draft["beats"]:
        beats.append(Beat(b["say"].strip(), f"photo:{b['photo']}", {"big": b["caption"].strip(), "small": ""},
                          anchor=b.get("anchor") or ""))
    beats.append(Beat(OUTRO, "outro", {"big": "Orbitwire", "small": "Sources in the description"},
                      pause_after=END_CARD))
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
        title = plain_title(kind, name)
    if any(media.from_openverse(p) or media.from_nasa(p) for p in photos):
        credit = credit.replace("photos: Wikimedia Commons", "photos: " + media.hosts(photos))
    if reports:
        credit += "; reporting: " + ", ".join(outlets.names(reports))
    credits = [credit] + sorted({p["credit"] + " " + p["page"] for p in photos})
    tags = [t for t in tags if t]
    scene = {"template": "story", "mood": mood, "voice": voice, "photos": photos, "hook": hook_claim(draft),
             "writer": {"model": llm.DEFAULT, "rejected": log},
             "subject": subject or {"name": name, "kind": "person" if kind == "death" else "event"},
             "people": [{"name": n} for n in people or []]}
    if category:
        scene["category"] = category  # the days an event photo may be from (anchor.own_window)
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


def story_subject(name: str) -> str | None:
    """The Wikidata item an nw- story is named after when it is a thing, not a place or a person (a company such as
    Aramco, an airline): its photos show what was hit, where a place's show only where."""
    try:
        title = wiki.search(name)
    except Exception:
        return None
    if not title or name.lower() not in title.lower():
        return None
    qid = (wiki.page_info([title]).get(title) or {}).get("qid")
    ent = wiki.entities([qid]).get(qid) if qid else None
    if not ent or media.place_like(ent) or wiki.HUMAN in {c["value"] for c in wiki.claims(ent, "P31")}:
        return None
    if not any(wiki.claims(ent, p) for p in MADE_THING):
        return None
    return qid


def story_person(name: str, reports: list[dict] | None = None) -> tuple[str | None, dict]:
    """(Wikipedia title, Wikidata item) of the person an nw- story names ("Attack on Tiger Shroff"): Wikipedia's first
    search hit, when its plain title is the name and the item is a human. A surname alone ("Macron") is the person
    when the reports write the full name ("Emmanuel Macron")."""
    try:
        title = wiki.search(name)
    except Exception:
        return None, {}
    plain = stories.plain_title(title or "")
    surname = bool(reports) and " " not in name.strip() and plain.lower().endswith(" " + name.lower()) \
        and bool(gate.reported(plain, reports))
    if not title or (plain.lower() != name.lower() and not surname):
        return None, {}
    qid = (wiki.page_info([title]).get(title) or {}).get("qid")
    ent = wiki.entities([qid]).get(qid) if qid else None
    if not ent or wiki.HUMAN not in {c["value"] for c in wiki.claims(ent, "P31")}:
        return None, {}
    return title, ent


# A subject is something made that can be hit: a company, a building, a ship, an aircraft. It has an inception, a
# maker, an operator or a headquarters; an idea has none ("Black" is the colour, whose photos are a painting and a
# black hole: run of 2026-10-15, "A Growing Shadow Over the Black Sea").
MADE_THING = ("P571", "P176", "P137", "P159")


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
    thing = None if place else story_subject(name)
    # An attack on a famous person is told about the person, over their own face-matched portraits.
    title, person = story_person(name, reports) if not place and not thing else (None, {})
    for other in [] if place or person else cand.get("places") or []:
        if len(gate.reported(other, reports)) >= gate.OWNERS_NEEDED and (found := story_place(other))[1]:
            where, (qid, place) = other, found
            break
    context = list(dict.fromkeys(([thing] if thing else []) + ([qid] if qid else [])
                                 + (incident_context(place, []) if place else [])))[:4]
    # What a beat may show (owner, 2026-10-22: "No real photos of incidents, no Macron photo, no school photo"): the
    # event's own free photos, the people the reporting names (their own faces), the things it names, then places.
    country = list(wiki.labels([c["value"] for c in wiki.claims(place, "P17")[:1]
                                if str(c["value"]).startswith("Q")]).values()) if place else []
    # Searched by the story's own name only, never by a town (review round 1): a protest named by its city
    # ("Paris", "Madrid") has no event photos of its own here, whatever else was marched there that week. A disaster
    # named by its place ("Chamoli" cloudburst) is searched with its kind of event and its days.
    photos = [] if place and where == name and cat in media.ONGOING else \
        event_photos([name], when, cat, work / "photos", set(), places=[where])
    people = named_people(name, reports)
    if person:
        own = stories.plain_title(title)
        people = [own] + [p for p in people if p != own]
        photos += stamp(pick_photos(title, person, work / "photos", person=True)[:3], "person", [own])
        photos += people_photos(people[1:], work / "photos", {p["file"] for p in photos})
    else:
        photos += people_photos(people, work / "photos", {p["file"] for p in photos})
    photos += thing_photos(reports, (country or [""])[0], work / "photos", {p["file"] for p in photos})
    if context and len(photos) < WANT_PHOTOS + 2:
        photos += fill_photos(context, work / "photos", {p["file"] for p in photos})
    if len(photos) < WANT_PHOTOS:
        photos += nasa_photos(cat, [name, where], when, work / "photos", {p["file"] for p in photos},
                              WANT_PHOTOS - len(photos))
    photos = arrange(dedupe(photos))[:8]
    if place and not media.too_wide(place):
        photos = with_maps(photos, wiki.coords(place), ", ".join(dict.fromkeys([where] + country[:1])),
                           work / "photos", cat)
    if len(photos) < MIN_PHOTOS:
        raise ValueError(f"gate: only {len(photos)} usable photos of {where} (want {MIN_PHOTOS})")
    if why := faceless(photos, name, sid, category=cat):
        raise ValueError(why)
    kind = "protest" if cat in ("protest", "movement") else "incident"
    toll = gate.reported_toll(reports)
    words = [name] + sorted(outlets.headline_keys(cand["title"])[0])
    reports = clean_reports(reports, words, perpetrators=kind == "incident")
    facts_text = [f"Person: {name}." if person else f"Place: {where}.",
                  "Wikipedia's article on this is only hours old: only the REPORTING may be used."
                  if cand.get("article") else "Wikipedia has no article on this yet: only the REPORTING may be used."]
    if toll:
        facts_text.append(f"Death toll ({toll_basis(toll[1])} agree): {toll[0]:,}.")
    banned = []
    if cat in ("attack", "strike"):
        told = {w.lower() for w in (name, where)}
        banned = [w for w in outlets.attackers((cand.get("headlines") or []) + [r["title"] for r in reports])
                  if w.lower() not in told]
    she = stories._pronouns(person)[0] if person else "It"
    draft, log = write(kind, name, she, facts_text, "", photos, banned_names=banned, log_path=work / "writer_log.json",
                       reports=reports, casualties=bool(toll), people=people)
    facts = [Fact("name", name, next((r["url"] for r in reports if r["owner"] in named), reports[0]["url"]),
                  stories.numbers_in(name), "named in the reports of " + ", ".join(named), owners=named)]
    if toll:
        facts.append(toll_fact(toll[0], toll[1], reports, None))
    short = _short(sid, "incident", name, draft, log, facts, facts_text, "", photos, [r["url"] for r in reports],
                   when.isoformat(), loss=bool(toll) or cat in ("attack", "strike", "conflict"), mood="news",
                   voice=cand.get("region", "world"),
                   tags=[name, cat, "news explained", "india news" if cand.get("region") == "india" else "world news"],
                   summary=f"{name}: what happened, from the reporting of {', '.join(outlets.names(reports))}.",
                   hashtags=[cat, name, "news"], reports=reports, credit=REPORT_CREDIT,
                   subject={"name": stories.plain_title(title) if person else name,
                            "kind": "person" if person else "thing" if thing else "event"}, people=people,
                   category=cat)
    short.scene["article"] = cand.get("article")
    short.scene["headlines"] = cand.get("headlines") or []
    return short


def build(cand: dict) -> Short:
    if (cand.get("id") or "").startswith("nw-"):
        return build_report(cand)
    return build_death(cand) if cand["kind"] == "death" else build_incident(cand)
