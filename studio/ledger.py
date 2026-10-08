"""The channel's memory: what was published, what was skipped and why, and the health of the last run.

In GitHub Actions the `state` directory is a checkout of the repo's `state` branch, committed back after each run.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

STATE = Path(__file__).resolve().parents[1] / "state"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load(name: str, default):
    path = STATE / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save(name: str, data) -> Path:
    STATE.mkdir(parents=True, exist_ok=True)
    path = STATE / f"{name}.json"
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def published() -> list[dict]:
    return load("published", [])


def record_publish(entry: dict) -> None:
    rows = published()
    rows = [r for r in rows if r["id"] != entry["id"]] + [entry]
    save("published", rows)


def skip(story_id: str, reason: str) -> None:
    skipped = load("skipped", {})
    skipped[story_id] = {"reason": reason, "at": now()}
    save("skipped", skipped)


def is_done(story_id: str) -> bool:
    return any(r["id"] == story_id for r in published()) or story_id in load("skipped", {})
