"""python -m studio.longform plan [--topic T] | write KEY | make KEY | finish | publish | link

Each command is one workflow job (.github/workflows/longform.yml), reading and writing work/longform/:
  plan     episode.json and plan.json (why this topic), and the chapter keys for the jobs' matrix;
  write    chapters/KEY/chapter.json (checked narration);
  make     chapters/KEY/{narration.wav, timing.json, chapter.mp4, hero.png};
  finish   episode.mp4, thumbnail.jpg, captions.srt, description.txt, meta.json (fails on QA);
  publish  uploads private and schedules (state/longform.json); never in a dry run;
  link     after an episode is public, links it from its Shorts.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "work" / "longform"


def _output(name: str, value: str) -> None:
    if path := os.environ.get("GITHUB_OUTPUT"):
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m studio.longform")
    p.add_argument("--work", type=Path, default=WORK)
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("plan")
    pl.add_argument("--topic", default="")
    for name in ("write", "make"):
        sub.add_parser(name).add_argument("key")
    for name in ("finish", "publish", "link"):
        sub.add_parser(name)
    a = p.parse_args(argv)
    work: Path = a.work
    started = time.monotonic()
    if a.cmd == "plan":
        from . import plan

        ep = plan.plan(override=a.topic or None)
        ep.save(work / "episode.json")
        (work / "plan.json").write_text(json.dumps(ep.why, indent=1, ensure_ascii=False), encoding="utf-8")
        keys = [c.key for c in ep.chapters]
        _output("keys", json.dumps(keys))
        _output("episode", ep.id)
        print(json.dumps({"episode": ep.id, "title": ep.title, "chapters": keys, "publish_at": ep.publish_at,
                          "chosen": ep.why.get("chosen"), "how": ep.why.get("how")}, indent=1))
    elif a.cmd == "write":
        from . import write

        path = write.run(work / "episode.json", a.key, work / "chapters" / a.key)
        data = json.loads(path.read_text(encoding="utf-8"))
        print(json.dumps({"key": a.key, "words": data["words"], "lines": len(data["lines"]), "model": data["model"]}))
    elif a.cmd == "make":
        from . import scenes, voice
        from .spec import Episode

        ep = Episode.load(work / "episode.json")
        d = work / "chapters" / a.key
        timing = voice.run(ep.id, d / "chapter.json", d)
        index = [c.key for c in ep.chapters].index(a.key)
        print(json.dumps(scenes.render(ep, index, timing, d, scenes.Atlas(ep, work / "atlas"))))
        shutil.rmtree(d / "takes", ignore_errors=True)
        for retake in d.glob("retake*"):
            shutil.rmtree(retake, ignore_errors=True)
    elif a.cmd == "finish":
        from . import assemble

        meta = assemble.finish(work)
        print(json.dumps({k: meta[k] for k in ("id", "title", "seconds", "chapters", "publish_at", "words")}, indent=1))
    elif a.cmd == "publish":
        from . import publish

        print(json.dumps(publish.publish(work), indent=1))
    elif a.cmd == "link":
        from . import publish

        print("\n".join(publish.link()) or "no links due")
    print(f"{a.cmd}: {time.monotonic() - started:.0f} s", file=sys.stderr)
    return 0
