"""Starts the studio's `run` workflow every EVERY minutes, because GitHub drops most of its scheduled runs (30-31 Oct:
6 runs in 30 h, 4-7 h apart, against a 30 min cron), then starts the next keeper before this job's time runs out.

    python .github/scripts/keeper.py <owner/repo>
"""
import json
import subprocess
import sys
import time
from datetime import datetime, timezone

REPO = sys.argv[1]
EVERY = 15 * 60
LIFETIME = 5.5 * 3600  # a GitHub job may run 6 h
RECENT = 25 * 60  # a run created this recently means the cron did its job
FAILING_BACKOFF = 60 * 60  # after 3 failed runs in a row, try at most hourly (each failure wakes the doctor)
started = time.time()


def log(*parts: str) -> None:
    print(datetime.now(timezone.utc).isoformat(timespec="seconds"), *parts, flush=True)


def gh(*args: str) -> str:
    p = subprocess.run(["gh", *args, "-R", REPO], capture_output=True, text=True, timeout=60)
    if p.returncode:
        raise RuntimeError(f"gh {' '.join(args)}: {p.stderr.strip()[:300]}")
    return p.stdout


def should_wait() -> str:
    runs = json.loads(gh("run", "list", "-w", "run", "-L", "5", "--json", "status,conclusion,createdAt") or "[]")
    now = datetime.now(timezone.utc)
    ages = [(now - datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00"))).total_seconds() for r in runs]
    if any(r["status"] in ("queued", "in_progress", "waiting", "pending", "requested") for r in runs):
        return "a run is queued or running"
    if ages and ages[0] < RECENT:
        return "a run started recently"
    done = [r["conclusion"] for r in runs if r["status"] == "completed"][:3]
    if len(done) == 3 and all(c == "failure" for c in done) and ages[0] < FAILING_BACKOFF:
        return "the last 3 runs failed"
    return ""


while time.time() - started < LIFETIME - EVERY:
    try:
        reason = should_wait()
        if reason:
            log("waiting:", reason)
        else:
            gh("workflow", "run", "run", "-f", "dry=false")
            log("started run")
    except Exception as exc:  # noqa: BLE001 - try again next round
        log("keeper:", str(exc))
    time.sleep(EVERY)
try:
    gh("workflow", "run", "keeper")
    log("handed over to the next keeper")
except Exception as exc:  # noqa: BLE001 - the hourly cron restarts the chain
    log("hand-over failed, the hourly cron restarts it:", str(exc))
