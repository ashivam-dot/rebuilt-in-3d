"""The channel's memory: what was published, what was skipped and why, and the health of the last run.

In GitHub Actions the `state` directory is a checkout of the repo's `state` branch, committed back after each run.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

STATE = Path(__file__).resolve().parents[1] / "state"
# Reasons that only mean "not yet": they never count as a try, and a story once given up for them comes back.
WAITS = ("under 6 hours old",)
# A story given up for want of photos before locator maps went live (studio/locator.py) gets one more try: a map
# may now stand in for the photos Commons lacked.
MAPS_SINCE = "2026-10-16T19:20:00+00:00"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load(name: str, default):
    path = STATE / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save(name: str, data) -> Path:
    STATE.mkdir(parents=True, exist_ok=True)
    path = STATE / f"{name}.json"
    # Written beside the file and moved over it: a run cut short never leaves half a file for the next run to read.
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def set_identity() -> None:
    """Give the state checkout a committer, so the workflow's `git pull --rebase` can replay its commit when the
    state branch moved during the run."""
    import subprocess

    if not (STATE / ".git").exists():
        return
    for key, value in (("user.name", "ashivam-dot"),
                       ("user.email", "335661989+ashivam-dot@users.noreply.github.com")):
        subprocess.run(["git", "-C", str(STATE), "config", key, value], check=False, capture_output=True)


def published() -> list[dict]:
    return load("published", [])


def record_publish(entry: dict) -> None:
    rows = published()
    rows = [r for r in rows if r["id"] != entry["id"]] + [entry]
    save("published", rows)
    pending = uploads()
    if pending.pop(entry["id"], None) is not None:
        save("uploads", pending)


def uploads() -> dict:
    """Stories uploaded and not yet recorded as published, by story id: {"video_id", "at"}. The ledger, not a public
    tag, says which video is which story (studio/youtube.py find)."""
    return load("uploads", {})


def record_upload(story_id: str, video_id: str) -> None:
    pending = uploads()
    pending[story_id] = {"video_id": video_id, "at": now()}
    save("uploads", pending)


def longform_videos() -> set[str]:
    """The long-form episodes' video ids (state/longform.json, written only by studio/longform/publish.py): never a
    Short's upload, so no Short job adopts, retags or re-uploads over one."""
    rows = (load("longform", {}).get("episodes") or {}).values()
    return {r["video_id"] for r in rows if r.get("video_id")}


def markers() -> dict:
    """Story ids read off an old upload's public MARKER tag that no published row names, by story id: video id. Kept
    before channel.untag takes the tag off, so youtube.find still knows the upload."""
    return load("markers", {})


def remember_marker(story_id: str, video_id: str) -> None:
    kept = markers()
    kept.setdefault(story_id, video_id)
    save("markers", kept)


# An upload still unpublished after this long is not a run cut short but a story that failed or was skipped on its
# rebuild: its private video waits on the channel for a person.
STALE_UPLOAD_HOURS = 24


def stale_uploads(at: datetime | None = None) -> list[str]:
    """Health notes for uploads.json entries older than STALE_UPLOAD_HOURS (each left as a private video)."""
    at = at or datetime.now(timezone.utc)
    notes = []
    for story_id, row in sorted(uploads().items()):
        try:
            hours = (at - datetime.fromisoformat(row["at"])).total_seconds() / 3600
        except (KeyError, TypeError, ValueError):
            continue
        if hours >= STALE_UPLOAD_HOURS:
            notes.append(f"stale upload {story_id}: video {row.get('video_id')} uploaded {hours:.0f} h ago and never "
                         "published; publish or delete it in Studio, then drop it from state/uploads.json")
    return notes


def skip(story_id: str, reason: str) -> None:
    skipped = load("skipped", {})
    skipped[story_id] = {"reason": reason, "at": now()}
    save("skipped", skipped)


def retry(story_id: str, reason: str, limit: int = 6) -> bool:
    """Count a retryable failure; past `limit` the story is skipped for good. True while it may still be retried."""
    tries = load("retries", {})
    row = tries.get(story_id, {"count": 0})
    if waiting(row.get("reason")) or reopened(row):
        row = {"count": 0}
    row = {"count": row["count"] + 1, "reason": reason, "at": now()}
    tries[story_id] = row
    save("retries", tries)
    if row["count"] >= limit:
        skip(story_id, f"gave up after {row['count']} tries: {reason}")
        return False
    return True


def waiting(reason: str | None) -> bool:
    return any(w in (reason or "") for w in WAITS)


def reopened(row: dict | None) -> bool:
    """A skip or retry for want of photos from before locator maps: the story starts its tries afresh."""
    return bool(row) and "usable photos" in row.get("reason", "") and row.get("at", "") < MAPS_SINCE


def is_done(story_id: str) -> bool:
    skipped = load("skipped", {}).get(story_id)
    if reopened(skipped):
        skipped = None
    return any(r["id"] == story_id for r in published()) or bool(skipped and not waiting(skipped.get("reason")))
