"""Watch every channel from public data: the latest public upload of each channel (YouTube's feed) and the
scheduled workflows that make them (GitHub's API). Opens, updates or closes one "Channel fleet needs attention"
issue here. Read-only towards every other repo and channel; never changes another channel's automation."""
from __future__ import annotations

import json
import os
import subprocess
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

TITLE = "Channel fleet needs attention"
OWNER = "ashivam-dot"
# channel -> (YouTube channel id, hours without a new public upload before alerting, watch from)
CHANNELS = {
    "Universe Receipts": ("UCal2hAu7VaZimTwaAgeBEyg", 36, None),
    "Atlas in Numbers": ("UC6e6OB3iw3yp8JnnBYxLItA", 36, None),
    "Orbitwire": ("UCfqAy1IxE2Cwu9pmZGMambA", 72, None),
    "Kyun Hua": ("UCS-lEPHkz_dftfUjjeTuxOA", 36, None),
    "Pangaea Nights": ("UCtVG78IUTqvP9rH-LLies0A", 48, "2026-10-13T00:00:00+00:00"),
    "Mool Katha": ("UCdqxVnoHDWXgA2ZVJWkSu8w", 36, None),
}
# (repo, workflow file, hours since its last scheduled run before alerting[, watch from]); GitHub's cron can run an
# hour or more late.
WORKFLOWS = [
    ("hindi-news-desk", "run.yml", 3), ("hindi-news-desk", "health.yml", 9),
    ("rebuilt-in-3d", "run.yml", 3),
    ("pangaea-nights", "episode.yml", 30, "2026-10-11T12:00:00+00:00"), ("pangaea-nights", "health.yml", 9),
    ("history-last-hours-control", "atlas-publish.yml", 5),
    ("channel-doctor", "watch.yml", 2),
    ("mool-katha-control", "lite.yml", 15), ("mool-katha-control", "control-monitor.yml", 6),
    ("mool-katha-control", "control-alerts.yml", 4),
]
FAIL_STREAK = 3


def _get(url: str, token: str | None = None) -> bytes:
    headers = {"User-Agent": "orbitwire-fleet-check"}
    if token:
        headers |= {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
        return r.read()


def _hours(since: str, now: datetime) -> float:
    return (now - datetime.fromisoformat(since.replace("Z", "+00:00"))).total_seconds() / 3600


def latest_upload(channel_id: str) -> str | None:
    root = ET.fromstring(_get(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"))
    ns = {"a": "http://www.w3.org/2005/Atom"}
    times = [e.findtext("a:published", namespaces=ns) for e in root.findall("a:entry", ns)]
    return max((t for t in times if t), default=None)


def channel_problems(now: datetime) -> tuple[list[str], list[str]]:
    problems, notes = [], []
    for name, (cid, quiet_h, since) in CHANNELS.items():
        try:
            last = latest_upload(cid)
        except Exception as exc:
            notes.append(f"{name}: feed unreadable ({type(exc).__name__})")
            continue
        if since and now < datetime.fromisoformat(since):
            notes.append(f"{name}: watched from {since[:10]}; latest public upload {last}")
            continue
        if last is None:
            problems.append(f"{name}: no public upload at all")
        elif _hours(last, now) > quiet_h:
            problems.append(f"{name}: no new public upload for {_hours(last, now):.0f} h (last {last}, limit {quiet_h} h)")
        else:
            notes.append(f"{name}: last public upload {_hours(last, now):.1f} h ago")
    if sum("feed unreadable" in n for n in notes) == len(CHANNELS):
        problems.append("YouTube's feeds answered for no channel: the upload watch is blind")
    return problems, notes


def workflow_problems(now: datetime, token: str | None) -> tuple[list[str], list[str]]:
    problems, notes, unreadable = [], [], 0
    for repo, wf, max_h, *since in WORKFLOWS:
        base = f"https://api.github.com/repos/{OWNER}/{repo}/actions/workflows/{wf}"
        try:
            state = json.loads(_get(base, token))["state"]
            runs = json.loads(_get(f"{base}/runs?per_page=10&event=schedule", token))["workflow_runs"]
        except Exception as exc:
            notes.append(f"{repo}/{wf}: unreadable ({type(exc).__name__})")
            unreadable += 1
            continue
        if state != "active":
            problems.append(f"{repo}/{wf}: workflow is {state}; its schedule no longer runs")
            continue
        if since and now < datetime.fromisoformat(since[0]):
            notes.append(f"{repo}/{wf}: watched from {since[0][:10]}")
            continue
        if not runs:
            problems.append(f"{repo}/{wf}: no scheduled run on record")
            continue
        age = _hours(runs[0]["created_at"], now)
        if age > max_h:
            problems.append(f"{repo}/{wf}: no scheduled run for {age:.0f} h (limit {max_h} h)")
        done = [r["conclusion"] for r in runs if r["status"] == "completed"][:FAIL_STREAK]
        if len(done) == FAIL_STREAK and all(c == "failure" for c in done):
            problems.append(f"{repo}/{wf}: the last {FAIL_STREAK} scheduled runs failed ({runs[0]['html_url']})")
        if not any(p.startswith(f"{repo}/{wf}:") for p in problems):
            notes.append(f"{repo}/{wf}: ok, last scheduled run {age:.1f} h ago")
    if unreadable == len(WORKFLOWS):
        problems.append("GitHub's API answered none of the workflow checks: the fleet watch is blind")
    return problems, notes


def main() -> None:
    now = datetime.now(timezone.utc)
    token = os.environ.get("GH_TOKEN")
    cp, cn = channel_problems(now)
    wp, wn = workflow_problems(now, token)
    problems = cp + wp
    print("fleet:\n  " + "\n  ".join(problems + cn + wn))
    found = subprocess.run(["gh", "issue", "list", "--state", "open", "--label", "alert", "--search", TITLE,
                            "--json", "number", "--jq", ".[0].number"], capture_output=True, text=True).stdout.strip()
    if problems:
        body = "\n".join(f"- {p}" for p in problems)
        if found:
            subprocess.run(["gh", "issue", "comment", found, "--body", body], check=True)
        else:
            subprocess.run(["gh", "issue", "create", "--label", "alert", "--title", TITLE, "--body", body], check=True)
    elif found:
        subprocess.run(["gh", "issue", "close", found, "--comment", "Every channel and workflow is healthy again."],
                       check=True)


if __name__ == "__main__":
    main()
