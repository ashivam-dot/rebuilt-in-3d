"""studio watch | make <usgs-id | wiki:Article title> | publish <story-id> | run | health"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

from . import gate, ledger, learn, plan

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work"
RETRYABLE = ("faceless:", "words (want", "does not confirm the death", "usable photos", "no draft passed",
             "came out garbled", "banned wording", "casualties without an agreed toll", "isn't backed by any sourced",
             "show who or what the story is about", "pictures show what is said for only",
             # a feed's article that could not be read this run (a timeout, the run's fetches spent) may be next run
             "could be read")
MAX_WRITTEN = 2  # each script costs minutes of CPU on the runner
log = logging.getLogger("studio")


class Refused(ValueError):
    """The gate refused a Short already built; written: a story Short, whose script the model wrote."""

    def __init__(self, message: str, written: bool = False):
        super().__init__(message)
        self.written = written


def writer_faceless() -> str:
    from . import writer

    return writer.FACELESS


def prepare(target: str | dict):
    """Build and gate a Short from a USGS event id, a 'wiki:<title>' string, a 'candidate:<id>' from the watcher's
    last list (state/candidates.json, so an nw- story can be reviewed while it waits out a back-off), or a watcher
    candidate."""
    from . import quake, trends, writer

    if isinstance(target, str) and target.startswith("wiki:"):
        target = trends.candidate(target[5:])
    elif isinstance(target, str) and target.startswith("candidate:"):
        seen = ledger.load("candidates", {})
        found = [c for c in seen.get("candidates", []) + seen.get("trending", []) if c.get("id") == target[10:]]
        if not found:  # a story only this branch's radar sees: look again now
            radar = trends.radar()
            found = [c for c in radar.get("candidates", []) + radar.get("emerging", []) if c.get("id") == target[10:]]
        if not found:
            raise ValueError(f"{target[10:]} is not in the watcher's last candidates")
        target = found[0]
    if isinstance(target, dict) and target["kind"] == "quake":
        target = target["event"]
    try:
        short = quake.build(target) if isinstance(target, str) else writer.build(target)
    except ValueError as exc:
        short = in_3d(target, exc)
        if short is None:
            raise
    if isinstance(target, dict):
        short.scene.setdefault("category", target.get("category"))
        short.scene.setdefault("region", target.get("region"))
        if target.get("kind") != "quake":
            short.scene.setdefault("article", target.get("title"))
    work = WORK / short.id
    work.mkdir(parents=True, exist_ok=True)
    short.save(work / "short.json")
    problems = gate.check(short)
    if problems:
        raise Refused("gate: " + "; ".join(problems), written=short.scene.get("template") == "story")
    return short


# Off (owner, 2026-10-16): a news story told over a 3D map instead of real photos reads as a lesser video than the
# channel's photo news. A story without free photos waits for them instead.
STORIES_IN_3D = False


def in_3d(target, exc: ValueError):
    """An incident still short of free photos on its second try is written over a 3D reconstruction of where it
    happened (writer.build_incident views=True, badged "not real footage") instead of being lost: Commons rarely has
    photos of an event in its first days, and 10 of the 14 stories given up by 2026-10-16 were."""
    from . import writer

    if not STORIES_IN_3D:
        return None
    if not isinstance(target, dict) or "usable photos" not in str(exc) or target.get("kind") == "death":
        return None
    if (target.get("id") or "").startswith("nw-"):
        return None
    if ledger.load("retries", {}).get(target["id"], {}).get("count", 0) < 1:
        return None
    return writer.build_incident(target, views=True)


def make(target: str | dict, short=None) -> tuple[object, dict]:
    from . import compose, render, voice

    short = short or prepare(target)
    work = WORK / short.id
    timing = voice.synthesize(short, work)
    stats = (compose if short.scene.get("template") == "story" else render).render(short, timing, work)
    (work / "render.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")
    return short, stats


def publish(story_id: str, publish_at: str | None = None) -> dict:
    """Publish now, or schedule for publish_at (ISO UTC); the ledger records the time it goes public."""
    from . import youtube
    from .spec import Short

    work = WORK / story_id
    short = Short.load(work / "short.json")
    problems = gate.check(short)
    if problems:
        raise ValueError("gate: " + "; ".join(problems))
    result = youtube.publish(short, work / "short.mp4", publish_at=publish_at)
    when = datetime.fromisoformat(publish_at.replace("Z", "+00:00")).isoformat(timespec="seconds") if publish_at \
        else ledger.now()
    ledger.record_publish({"id": short.id, "kind": short.kind, "title": short.title, "loss": short.loss,
                           "published_at": when, "event_time": short.event_time,
                           "category": short.scene.get("category"), "region": short.scene.get("region"),
                           "maps": sum(p.get("role") == "map" for p in short.scene.get("photos") or []),
                           "article": short.scene.get("article"),
                           "report_urls": [r["url"] for r in short.scene.get("reporting") or []],
                           "outlets": short.scene.get("outlets") or [], "headlines": short.scene.get("headlines") or [],
                           **result})
    return result


def run(dry: bool = False) -> dict:
    """One scheduled pass: watch, pick the best eligible story, make it, gate it, publish it."""
    health = {"at": ledger.now(), "ok": True, "steps": []}
    try:
        if not dry:
            ledger.set_identity()
            try:
                learned = learn.refresh()
                if learned is not None:
                    health["steps"].append(f"learn: {learned['scored']} scored Shorts, lifts {learned['lifts']}"[:400])
                    if learned.get("note"):
                        health["steps"].append(learned["note"])
            except Exception as exc:  # the numbers steer ranking; reading them must never stop a publish
                health["steps"].append(f"learn: {type(exc).__name__}: {exc}"[:300])
            try:
                from . import youtube

                health["steps"] += youtube.retract(youtube.client())
            except Exception as exc:
                health["steps"].append(f"retract: {type(exc).__name__}: {exc}"[:300])
            health["steps"] += ledger.stale_uploads()
            try:  # About, playlists, old tags: off unless CHANNEL_JOBS names them (studio/channel.py)
                from . import channel

                if note := channel.run():
                    health["steps"].append(note[:400])
            except Exception as exc:  # channel tidying must never stop a publish
                health["steps"].append(f"channel jobs: {type(exc).__name__}: {exc}"[:300])
        found = plan.watch()
        health["steps"].append(f"watch: {len(found['candidates'])} candidates ({len(found['quakes'])} quakes, "
                               f"{len(found['trending'])} trending), {len(found['hazards'])} hazard alerts")
        if found.get("outlet_note"):
            health["steps"].append(found["outlet_note"])
        if found.get("trend_errors"):
            health["steps"].append(f"trend radar errors: {found['trend_errors']}")
        ready, held = plan.lineup(found["candidates"])
        health["steps"] += held[:6]
        if note := plan.ad_note(found["candidates"]):
            health["steps"].append(note)
        if dry and not ready:
            ready = found["candidates"]
        if dry and (passed := {s.strip() for s in os.environ.get("STUDIO_DRY_SKIP", "").split(",") if s.strip()}):
            # A dry run saves no state, so the next one would make the same story: it may be told to pass over it.
            # A bare Wikidata id ("Q3424313") passes over its story too (review round 2: it was ignored).
            ready = [c for c in ready if not any(c["id"] == p or c["id"].startswith(p + "-")
                                                 or c["id"] in ("wk-" + p,) or c["id"].startswith("wk-" + p + "-")
                                                 for p in passed)]
        if not ready:
            return health
        recent_loss = [r.get("loss", False) for r in ledger.published()]
        written = tried = 0
        for cand in ready:
            if tried >= 4:
                break
            tried += 1
            if written >= MAX_WRITTEN and cand["kind"] != "quake":
                health["steps"].append(f"later {cand['id']}: this run already wrote {written} scripts")
                continue
            try:
                short = prepare(cand)
            except ValueError as exc:
                # A script was written when the writer gave up on its drafts, or when the gate refused the written
                # Short (review round 2: gate-stage faceless refusals gave their slot back, 12 scripts in one run).
                written += "no draft passed" in str(exc) or getattr(exc, "written", False)
                if ledger.waiting(str(exc)):
                    # A brand-new article waits for its facts to settle; waiting is not a failed try, and it does
                    # not take a slot from the stories that are ready now.
                    tried -= 1
                    health["steps"].append(f"wait {cand['id']}: {exc}")
                    continue
                # Thin articles, and stories still short of free photos, get another chance next run.
                if any(m in str(exc) for m in RETRYABLE):
                    ledger.retry(cand["id"], str(exc)[:300])
                    # Faceless before any script is written (writer.faceless) does not take a candidate's slot.
                    tried -= str(exc).startswith(writer_faceless()) and not getattr(exc, "written", False)
                else:
                    ledger.skip(cand["id"], str(exc)[:300])
                health["steps"].append(f"skip {cand['id']}: {exc}")
                continue
            except Exception as exc:  # one malformed article must not stop the other candidates
                health.setdefault("warnings", []).append(f"{cand['id']}: {type(exc).__name__}: {exc}"[:300])
                continue
            written += short.scene.get("template") == "story" or short.scene.get("narration") == "story"
            mix = gate.channel_mix(recent_loss, short.loss)
            if mix:
                health["steps"].append(f"hold {cand['id']}: {mix}")
                continue
            try:
                short, stats = make(cand, short)
            except ValueError as exc:
                ledger.retry(cand["id"], str(exc)[:300])
                health["steps"].append(f"skip {cand['id']}: {exc}")
                continue
            if dry:
                health["steps"].append(f"dry run: made {short.id} ({stats['duration']} s), not published")
                return health
            from . import youtube

            try:
                result = publish(short.id)
            except youtube.Unrecorded as exc:
                # A story already on the channel under a lost ledger row: never a second copy of it.
                ledger.skip(cand["id"], f"already uploaded: {exc}"[:300])
                health["steps"].append(f"hold {cand['id']}: {exc}"[:400])
                health.setdefault("warnings", []).append(f"{cand['id']}: unrecorded upload {exc}"[:300])
                continue
            health["steps"].append(f"published {short.id}: {result['url']}")
            health["published"] = result
            return health
        health["steps"].append("nothing eligible to publish")
        return health
    except Exception as exc:
        health["ok"] = False
        health["error"] = f"{type(exc).__name__}: {exc}"[:500]
        health["trace"] = traceback.format_exc()[-2000:]
        return health
    finally:
        ledger.save("health", health)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    p = argparse.ArgumentParser(prog="studio")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("watch")
    m = sub.add_parser("make"); m.add_argument("event")
    pb = sub.add_parser("publish"); pb.add_argument("story")
    r = sub.add_parser("run"); r.add_argument("--dry", action="store_true")
    sub.add_parser("health")
    a = p.parse_args(argv)
    if a.cmd == "watch":
        print(json.dumps(plan.watch(), indent=1))
    elif a.cmd == "make":
        short, stats = make(a.event)
        print(json.dumps({"id": short.id, "title": short.title, **stats}, indent=1))
    elif a.cmd == "publish":
        print(json.dumps(publish(a.story), indent=1))
    elif a.cmd == "run":
        health = run(dry=a.dry)
        print(json.dumps({k: v for k, v in health.items() if k != "trace"}, indent=1))
        return 0 if health["ok"] else 1
    elif a.cmd == "health":
        print(json.dumps(ledger.load("health", {}), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
