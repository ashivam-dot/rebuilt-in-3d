"""studio watch | make <usgs-id> | publish <story-id> | run | health"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import traceback
from pathlib import Path

from . import gate, ledger, plan

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work"
log = logging.getLogger("studio")


def make(event_id: str) -> tuple[object, dict]:
    from . import quake, render, voice

    short = quake.build(event_id)
    work = WORK / short.id
    work.mkdir(parents=True, exist_ok=True)
    short.save(work / "short.json")
    problems = gate.check(short)
    if problems:
        raise ValueError("gate: " + "; ".join(problems))
    timing = voice.synthesize(short, work)
    stats = render.render(short, timing, work)
    (work / "render.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")
    return short, stats


def publish(story_id: str) -> dict:
    from . import youtube
    from .spec import Short

    work = WORK / story_id
    short = Short.load(work / "short.json")
    problems = gate.check(short)
    if problems:
        raise ValueError("gate: " + "; ".join(problems))
    result = youtube.publish(short, work / "short.mp4")
    ledger.record_publish({"id": short.id, "kind": short.kind, "title": short.title, "loss": short.loss,
                           "published_at": ledger.now(), "event_time": short.event_time, **result})
    return result


def run(dry: bool = False) -> dict:
    """One scheduled pass: watch, pick the best eligible story, make it, gate it, publish it."""
    health = {"at": ledger.now(), "ok": True, "steps": []}
    try:
        found = plan.watch()
        health["steps"].append(f"watch: {len(found['quakes'])} quake candidates, {len(found['hazards'])} hazard alerts")
        wait = plan.can_publish()
        if wait and not dry:
            health["steps"].append(f"hold: {wait}")
            return health
        recent_loss = [r.get("loss", False) for r in ledger.published()]
        for cand in found["quakes"][:3]:
            try:
                short, stats = make(cand["event"])
            except ValueError as exc:
                ledger.skip(cand["id"], str(exc)[:300])
                health["steps"].append(f"skip {cand['id']}: {exc}")
                continue
            mix = gate.channel_mix(recent_loss, short.loss)
            if mix:
                health["steps"].append(f"hold {cand['id']}: {mix}")
                continue
            if dry:
                health["steps"].append(f"dry run: made {short.id} ({stats['duration']} s), not published")
                return health
            result = publish(short.id)
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
