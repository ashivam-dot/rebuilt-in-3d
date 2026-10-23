"""Replay the picture rules (studio/anchor.py, gate.pictures) on published Shorts' plans, and estimate uploads.

    .venv/bin/python -m tests.tools.replay [short.json ...] [--live] [--ledger published.json]

Without arguments it judges tests/fixtures/pictures (the 13 newest public Shorts as of 2026-10-22). For each plan:
pass or refuse, the share of picture time on maps and on pictures that show what is said, and the gate's reasons.
--live also asks Wikimedia Commons (read-only) whether the event now has free photos of its own (media.event), the
new source a refused story would be told over. --ledger: a copy of state/published.json, for the upload rate."""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from studio import anchor, gate, media
from studio.spec import Short

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "pictures"


def judge(short: Short, repick: bool = True) -> dict:
    """The verdict on the plan the new pipeline would publish: each beat's photo re-picked by Story.assign (the
    picker writer.anchor_photos uses) from the same photos and script, unless repick=False (the published choices)."""
    from dataclasses import replace

    story = anchor.story_of(short)
    beats = [b for b in short.beats if b.shot.startswith("photo:")]
    texts = [b.text for b in beats]
    story.prepare(texts)
    if repick:
        picked = iter(story.assign(texts, [int(b.shot[6:]) for b in beats]))
        short = replace(short, beats=[replace(b, shot=f"photo:{i}", anchor=w) if b.shot.startswith("photo:") else b
                                      for b in short.beats for i, w in [next(picked) if b.shot.startswith("photo:")
                                                                         else (None, "")]])
        beats = [b for b in short.beats if b.shot.startswith("photo:")]
        story = anchor.story_of(short)
    got = story.judge(texts, [int(b.shot[6:]) for b in beats])
    problems = gate.pictures(short, story)
    return {"id": short.id, "kind": short.kind, "title": short.title, "pass": not problems,
            "shown": round(got["shown"], 2), "maps": round(got["maps"], 2), "map_photos": got["map_photos"],
            "problems": problems}


def names_of(short: Short) -> list[str]:
    name = next((f.value for f in short.facts if f.key == "name"), "")
    where = next((t.split(":", 1)[1].strip(" .") for t in short.scene.get("facts_text") or []
                  if t.startswith(("Location:", "Place:"))), "")
    # A story told over maps names its place on them ("MAP: the region around Paris, France").
    mapped = [t[0] for p in short.scene.get("photos") or [] if anchor.kind_of(p) == "map"
              for t in [anchor.legacy_terms(p, "map")] if t]
    return [n for n in dict.fromkeys([name, where.split(",")[0]] + [m.split(",")[0] for m in mapped]) if n]


def live(short: Short) -> int:
    when = date.fromisoformat((short.event_time or "")[:10]) if short.event_time else date.today()
    return len(media.event(names_of(short), when, short.scene.get("category")))


def rate(ledger: Path, days: int = 7) -> dict:
    rows = json.loads(ledger.read_text())
    rows = rows if isinstance(rows, list) else list(rows.values())
    end = max(datetime.fromisoformat(r["published_at"]) for r in rows)
    recent = [r for r in rows if datetime.fromisoformat(r["published_at"]) > end - timedelta(days=days)]
    kinds = Counter(r.get("kind") for r in recent)
    return {"days": days, "uploads": len(recent), "per_day": round(len(recent) / days, 1), "kinds": dict(kinds)}


def main(argv: list[str]) -> None:
    files = [Path(a) for a in argv if a.endswith(".json") and "published" not in a] or sorted(FIX.glob("*.json"))
    results = []
    for f in files:
        short = Short.load(f)
        r = judge(short) | {"file": f.name}
        if "--live" in argv and short.kind != "death":
            r["event_photos_now"] = live(short)
        results.append(r)
        print(json.dumps(r, ensure_ascii=False))
    passed = sum(r["pass"] for r in results)
    print(json.dumps({"plans": len(results), "pass": passed, "refuse": len(results) - passed,
                      "maps_per_short_old": round(sum(r["map_photos"] for r in results) / max(len(results), 1), 2)}))
    if "--ledger" in argv:
        print(json.dumps(rate(Path(argv[argv.index("--ledger") + 1]))))


if __name__ == "__main__":
    main(sys.argv[1:])
