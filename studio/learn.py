"""What the channel's own numbers say, fed back into the desk.

Every REFRESH the scheduled run reads each published Short's views, likes and comments, scores it by its views at
SCORE_AT_H hours, and compares story kinds and categories with the channel's baseline. The desk multiplies a
candidate's priority by the learned lift of its kind and category. A lift needs MIN_SAMPLES scored Shorts, is
shrunk toward 1 by n / (n + PRIOR) and stays within LIFT_RANGE, so a couple of lucky uploads cannot steer the desk.
Everything lands in state/performance.json, with a readable state/LEARNINGS.md.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from . import ledger

REFRESH = timedelta(hours=3)
SCORE_AT_H = 24.0
MIN_SAMPLES = 4
PRIOR = 4.0
LIFT_RANGE = (0.75, 1.35)
FEATURES = ("kind", "category")
KEEP_SNAPSHOTS = 16

_cache: dict = {}


def _age_h(row: dict, at: datetime) -> float:
    return (at - datetime.fromisoformat(row["published_at"])).total_seconds() / 3600


def views_at(snapshots: list[dict], hours: float) -> float | None:
    """Views at `hours` after publishing: interpolated between snapshots, or scaled back from the first later one
    (views grow roughly with the square root of age once a Short's first push is over). None while too young."""
    snaps = sorted(snapshots, key=lambda s: s["age_h"])
    if not snaps or snaps[-1]["age_h"] < hours:
        return None
    later = next(s for s in snaps if s["age_h"] >= hours)
    earlier = [s for s in snaps if s["age_h"] < hours]
    if not earlier:
        return later["views"] * math.sqrt(hours / later["age_h"]) if later["age_h"] > 0 else float(later["views"])
    a = earlier[-1]
    span = later["age_h"] - a["age_h"]
    return a["views"] + (later["views"] - a["views"]) * ((hours - a["age_h"]) / span if span else 1.0)


def _thin(snapshots: list[dict]) -> list[dict]:
    """Every snapshot of the first two days (they set the score), then the newest few."""
    early = [s for s in snapshots if s["age_h"] <= 2 * SCORE_AT_H]
    late = [s for s in snapshots if s["age_h"] > 2 * SCORE_AT_H]
    return (early + late[-4:])[-KEEP_SNAPSHOTS:]


def learn(videos: list[dict]) -> dict:
    scored = [v for v in videos if v.get("views_24h") is not None]
    out = {"scored": len(scored), "min_samples": MIN_SAMPLES, "lifts": {}}
    if len(scored) < MIN_SAMPLES:
        return out
    logs = [math.log1p(v["views_24h"]) for v in scored]
    base = sum(logs) / len(logs)
    out["baseline_views_24h"] = round(math.expm1(base))
    for feature in FEATURES:
        groups: dict[str, list[float]] = {}
        for v, score in zip(scored, logs):
            if v.get(feature):
                groups.setdefault(str(v[feature]), []).append(score)
        for value, scores in groups.items():
            n = len(scores)
            if n < MIN_SAMPLES:
                continue
            diff = sum(scores) / n - base
            lift = min(max(math.exp(diff * n / (n + PRIOR)), LIFT_RANGE[0]), LIFT_RANGE[1])
            out["lifts"][f"{feature}:{value}"] = {"n": n, "lift": round(lift, 3),
                                                   "typical_views_24h": round(math.expm1(sum(scores) / n))}
    return out


def factor(cand: dict) -> float:
    """The learned multiplier for a candidate's kind and category (1.0 until there is evidence)."""
    perf = ledger.load("performance", {})
    if "lifts" not in _cache or _cache.get("at") != perf.get("at"):
        _cache.update(at=perf.get("at"), lifts=(perf.get("learned") or {}).get("lifts", {}))
    f = 1.0
    for feature in FEATURES:
        f *= _cache["lifts"].get(f"{feature}:{cand.get(feature)}", {}).get("lift", 1.0)
    return min(max(f, LIFT_RANGE[0]), LIFT_RANGE[1])


def report(perf: dict) -> str:
    learned = perf.get("learned") or {}
    lines = ["# What this channel's own numbers say", "",
             f"Updated {perf.get('at')}. Scored Shorts (views at {SCORE_AT_H:.0f} h): {learned.get('scored', 0)}. "
             f"A lift needs {MIN_SAMPLES} scored Shorts in a group; it is shrunk toward 1 and kept within "
             f"{LIFT_RANGE[0]}-{LIFT_RANGE[1]}.", ""]
    if learned.get("baseline_views_24h") is not None:
        lines.append(f"Baseline: a typical Short has {learned['baseline_views_24h']} views at 24 h.")
    for key, v in sorted(learned.get("lifts", {}).items(), key=lambda kv: -kv[1]["lift"]):
        lines.append(f"- {key}: x{v['lift']} ranking lift ({v['n']} Shorts, typical {v['typical_views_24h']} views)")
    if not learned.get("lifts"):
        lines.append("- No lift yet: not enough scored Shorts per group. The desk ranks on fame and freshness alone.")
    lines += ["", "| Short | published | " + " | ".join(FEATURES) + " | views now | views at 24 h |",
              "|---" * (len(FEATURES) + 4) + "|"]
    for v in sorted(perf.get("videos", {}).values(), key=lambda v: v["published_at"], reverse=True)[:30]:
        now = v["snapshots"][-1]["views"] if v.get("snapshots") else ""
        at24 = "" if v.get("views_24h") is None else round(v["views_24h"])
        cells = " | ".join(str(v.get(f) or "") for f in FEATURES)
        lines.append(f"| {v['id']} | {v['published_at'][:16]} | {cells} | {now} | {at24} |")
    return "\n".join(lines) + "\n"


def refresh(at: datetime | None = None, force: bool = False, api=None) -> dict | None:
    """Read the channel's numbers and relearn, at most once per REFRESH. Returns what was learned, or None if the
    last read is still fresh."""
    from . import youtube

    at = at or datetime.now(timezone.utc)
    perf = ledger.load("performance", {"at": None, "videos": {}})
    if not force and perf.get("at") and at - datetime.fromisoformat(perf["at"]) < REFRESH:
        return None
    if api is None:
        api = youtube.client()
    stats = {v["id"]: v.get("statistics", {}) for v in youtube.recent(api, youtube.identity(api))}
    for row in ledger.published():
        vid = row.get("video_id")
        if not vid or vid not in stats or _age_h(row, at) < 0:
            continue
        s = stats[vid]
        rec = perf["videos"].setdefault(vid, {"id": row["id"], "published_at": row["published_at"], "snapshots": []})
        rec.update({f: row.get(f) or rec.get(f) for f in FEATURES})
        rec["snapshots"] = _thin(rec["snapshots"] + [{
            "age_h": round(_age_h(row, at), 2), "views": int(s.get("viewCount", 0)),
            "likes": int(s.get("likeCount", 0)), "comments": int(s.get("commentCount", 0))}])
        rec["views_24h"] = views_at(rec["snapshots"], SCORE_AT_H)
    perf["at"] = at.isoformat(timespec="seconds")
    perf["learned"] = learn(list(perf["videos"].values()))
    ledger.save("performance", perf)
    (ledger.STATE / "LEARNINGS.md").write_text(report(perf), encoding="utf-8")
    return perf["learned"]
