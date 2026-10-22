"""Write one chapter's narration and hold every sentence to the chapter's facts and source, with the Shorts' own gates:
- writer.ungrounded: a name or number no fact or source sentence has is sent back;
- gate.banned_word, writer.FIRST_PERSON, writer.TEASE (no question, no "here's why"), writer.GENERIC_CLOSE;
- casualties: a line that speaks of deaths or injuries stands only on a fact two different owners state (gate.OWNERS_NEEDED);
  the planner gives none, so in practice the episode never states a toll;
- the evidence check (writer._check_messages, check_verdict, then recheck on the closest sentences) with the local
  model, always: a flagged line is rewritten once and checked again, else dropped.
The draft comes from Gemini when a key is set (gemini.py), else from the local model; the check is the local model's
either way. Up to DRAFTS drafts; the best (fewest problems, then closest to the word range) is kept.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .. import gate, writer
from . import gemini
from .spec import Chapter, Episode

DRAFTS = 3
LINE_WORDS = (6, 32)
LINES_SCHEMA = {"type": "object", "properties": {"lines": {"type": "array", "items": {"type": "string"}}},
                "required": ["lines"]}
SYSTEM = ("You are the head writer of Orbitwire Explains, a calm, precise science documentary series on YouTube. You "
          "write narration a viewer hears once, so every sentence is short, concrete and in plain English.")
RULES = """RULES (all mandatory):
- Use ONLY the FACTS and the SOURCE below. Every name, number, date and claim must appear there. Never add a number.
- Say numbers exactly as the facts write them ("7.7", "179", "2,900,000"): never round them again, never estimate.
- Never mention deaths, injuries, damage costs or anyone missing.
- No questions, no "here's why", no "stay tuned", no call to subscribe, no "we", "us" or "our".
- One sentence per line, {lo}-{hi} words each. Explain cause and effect plainly, like a patient teacher.
- Chances are chances: say "a 56 percent chance", never that something will happen.
- Total: {min_words}-{max_words} words."""


def ground(ep: Episode, ch: Chapter) -> str:
    facts = "\n".join(f.value for f in ch.facts)
    return "\n".join([ep.topic, ch.title, facts, ch.source])


def messages(ep: Episode, ch: Chapter, problems: list[str] | None = None, before: list[str] | None = None) -> list[dict]:
    outline = "\n".join(f"{i + 1}. {c.title}{'  <- THIS CHAPTER' if c.key == ch.key else ''}"
                        for i, c in enumerate(ep.chapters))
    user = (f"EPISODE: {ep.title}\nOUTLINE:\n{outline}\n\nTHIS CHAPTER: {ch.title}\nTASK: {ch.brief}\n\n"
            + RULES.format(lo=LINE_WORDS[0], hi=LINE_WORDS[1], min_words=ch.words[0], max_words=ch.words[1])
            + "\n\nFACTS:\n" + "\n".join(f"- {f.value}" for f in ch.facts)
            + ("\n\nSOURCE:\n" + ch.source if ch.source else "")
            + '\n\nAnswer as JSON: {"lines": ["sentence", ...]}.')
    out = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    if problems and before:
        out += [{"role": "assistant", "content": json.dumps({"lines": before})},
                {"role": "user", "content": "Rewrite the chapter. Fix these problems, keep everything else:\n"
                                            + "\n".join(f"- {p}" for p in problems[:12])}]
    return out


def casualty_ok(line: str, ch: Chapter) -> bool:
    if not (gate.CASUALTY.search(line) or writer.CASUALTY_WORDS.search(line)):
        return True
    return any(len(set(f.owners)) >= gate.OWNERS_NEEDED and writer.CASUALTY_WORDS.search(f.value) for f in ch.facts)


def line_problems(line: str, ch: Chapter, src: str, last: bool) -> list[str]:
    out = []
    n = len(line.split())
    if not LINE_WORDS[0] <= n <= LINE_WORDS[1]:
        out.append(f"{line[:50]!r}: {n} words (want {LINE_WORDS[0]}-{LINE_WORDS[1]})")
    if missing := writer.ungrounded(line, src):
        out.append(f"{line[:50]!r}: not in the facts or source: {', '.join(missing)}")
    if (word := gate.banned_word(line)) is not None:
        out.append(f"{line[:50]!r}: banned word {word!r}")
    if not casualty_ok(line, ch):
        out.append(f"{line[:50]!r}: speaks of casualties; leave deaths and injuries out")
    if writer.FIRST_PERSON.search(writer.QUOTED.sub("", line)):
        out.append(f"{line[:50]!r}: first person (we/us/our)")
    if hit := writer.TEASE.search(line):
        out.append(f"{line[:50]!r}: tease {hit.group(0)!r}: state it")
    if last and (hit := writer.GENERIC_CLOSE.search(line)):
        out.append(f"{line[:50]!r}: filler close {hit.group(0)!r}")
    return out


def problems(lines: list[str], ch: Chapter, src: str) -> list[str]:
    out = []
    for i, line in enumerate(lines):
        out += line_problems(line, ch, src, i == len(lines) - 1)
    words = sum(len(x.split()) for x in lines)
    if not ch.words[0] <= words <= ch.words[1]:
        out.append(f"the chapter is {words} words (want {ch.words[0]}-{ch.words[1]})")
    return out


def clean(lines) -> list[str]:
    out = []
    for x in lines or []:
        x = " ".join(str(x).split()).strip()
        x = re.sub(r"^[-*\d.)\s]+(?=[A-Z])", "", x)
        if x:
            out.append(x)
    return out


def fact_check(checker, lines: list[str], ch: Chapter, src: str) -> dict[int, str]:
    """{line number: problem} for the lines the evidence check and its second look both flag. A line the checker
    gave no verdict counts against it (check_verdict alone lets a left-out line through): it goes to the second look
    like any flagged line, so no sentence reaches the narration unchecked."""
    facts = [f.value for f in ch.facts]
    try:
        verdict = checker.chat(writer._check_messages(lines, facts, ch.source), writer.CHECK_SCHEMA, temperature=0.0,
                               max_tokens=min(6000, 160 * len(lines) + 400))
    except ValueError:  # an answer cut off mid-JSON: no verdicts, so every line gets the second look below
        verdict = {}
    verdict = verdict if isinstance(verdict, dict) else {}
    rows = verdict.get("lines") if isinstance(verdict.get("lines"), list) else []
    verdict = {"lines": [r for r in rows if isinstance(r, dict)]}
    flagged = writer.check_verdict(verdict, lines, src)
    seen = {r.get("line") for r in verdict["lines"]}
    for n in range(1, len(lines) + 1):
        if n not in seen and n not in flagged:
            flagged[n] = f"line {n} ({lines[n - 1][:60]}): no verdict"
    if not flagged:
        return {}
    try:
        kept = writer.recheck(checker, lines, flagged, src)
    except (ValueError, AttributeError):  # a second look cut off or malformed: every flagged line stays flagged
        return flagged
    return {n: p for n, p in flagged.items() if any(r.startswith(p) for r in kept)}


def draft(drafter, msgs: list[dict]) -> tuple[list[str], str]:
    try:
        answer = drafter(msgs)
    except ValueError as exc:  # an answer cut off mid-JSON counts as an empty draft, not the end of the job
        print(f"draft unreadable: {exc}"[:200], flush=True)
        answer = {}
    return clean(answer.get("lines") if isinstance(answer, dict) else []), getattr(drafter, "model", "")


def _rank(lines: list[str], ch: Chapter, src: str) -> tuple:
    words = sum(len(x.split()) for x in lines)
    off = max(ch.words[0] - words, words - ch.words[1], 0)
    return (len(problems(lines, ch, src)), off)


def write_chapter(ep: Episode, key: str, drafter, checker, drafts: int = DRAFTS) -> dict:
    """{key, lines, words, model, log}: the chapter's checked narration. drafter(messages) -> {"lines": [...]};
    checker is a writer-style model (chat(messages, schema, temperature, max_tokens) -> dict)."""
    ch = next(c for c in ep.chapters if c.key == key)
    src = ground(ep, ch)
    log, best = [], None
    msgs = messages(ep, ch)
    for n in range(drafts):
        lines, model = draft(drafter, msgs)
        if not lines:
            log.append(f"draft {n + 1}: empty")
            continue
        # Lines the gates refuse go back once; what still fails is dropped.
        bad = [p for i, ln in enumerate(lines) for p in line_problems(ln, ch, src, i == len(lines) - 1)]
        if bad:
            log.append(f"draft {n + 1}: " + "; ".join(bad)[:600])
            again, _ = draft(drafter, messages(ep, ch, bad, lines))
            lines = again or lines
        lines = [ln for i, ln in enumerate(lines) if not line_problems(ln, ch, src, i == len(lines) - 1)]
        flagged = fact_check(checker, lines, ch, src) if lines else {}
        if flagged:
            log.append(f"draft {n + 1} evidence: " + "; ".join(flagged.values())[:800])
            fixes = [f"line {k}: {lines[k - 1]!r} is not supported by the facts or source: rewrite it with only "
                     "what they state, or leave it out" for k in flagged]
            again, _ = draft(drafter, messages(ep, ch, fixes, lines))
            again = [ln for i, ln in enumerate(again) if not line_problems(ln, ch, src, i == len(again) - 1)]
            still = fact_check(checker, again, ch, src) if again else {}
            lines = [ln for i, ln in enumerate(again, 1) if i not in still] if again else \
                [ln for i, ln in enumerate(lines, 1) if i not in flagged]
            if still:
                log.append(f"draft {n + 1} dropped {len(still)} line(s) the second check also flagged")
        rest = problems(lines, ch, src)
        if best is None or _rank(lines, ch, src) < _rank(best[0], ch, src):
            best = (lines, model)
        if not rest:
            break
        log.append(f"draft {n + 1} left: " + "; ".join(rest)[:400])
        msgs = messages(ep, ch, rest, lines)
    if best is None or not best[0]:
        raise RuntimeError(f"chapter {key}: no draft passed the checks: " + " | ".join(log)[-1200:])
    lines, model = best
    words = sum(len(x.split()) for x in lines)
    if words < ch.words[0] * 0.7:
        raise RuntimeError(f"chapter {key}: only {words} checked words (want {ch.words[0]}+): " + " | ".join(log)[-800:])
    return {"key": key, "lines": lines, "words": words, "model": model, "log": log}


# --- the models ---------------------------------------------------------------------------------------------------

class LocalDrafter:
    """The local model as a drafter."""

    def __init__(self, m):
        self.m, self.model = m, f"local:{getattr(m, 'name', '')}"

    def __call__(self, msgs: list[dict]) -> dict:
        return self.m.chat(msgs, LINES_SCHEMA, temperature=0.6, max_tokens=2600)


class GeminiDrafter:
    """Gemini when it answers, else the local model (a run never stops for Gemini's quota)."""

    def __init__(self, fallback: LocalDrafter):
        self.fallback, self.model = fallback, ""

    def __call__(self, msgs: list[dict]) -> dict:
        if gemini.available():
            try:
                answer, self.model = gemini.chat(msgs, LINES_SCHEMA, temperature=0.6, max_tokens=4096)
                return answer
            except gemini.Unavailable as exc:
                print(f"Gemini unavailable, drafting locally: {exc}", flush=True)
        self.model = self.fallback.model
        return self.fallback(msgs)


def run(episode: Path, key: str, out: Path) -> Path:
    from .. import llm

    ep = Episode.load(episode)
    with llm.Model() as m:
        local = LocalDrafter(m)
        result = write_chapter(ep, key, GeminiDrafter(local), m)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "chapter.json"
    path.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    return path
