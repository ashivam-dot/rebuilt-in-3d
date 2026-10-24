"""What the channel's own numbers say, fed back into the desk.

Every REFRESH the scheduled run reads each published Short's views, likes and comments, scores it by its views at
SCORE_AT_H hours, and compares story kinds and categories with the channel's baseline. The desk multiplies a
candidate's priority by the learned lift of its kind and category. A lift needs MIN_SAMPLES scored Shorts, is
shrunk toward 1 by n / (n + PRIOR) and stays within LIFT_RANGE, so a couple of lucky uploads cannot steer the desk.
Everything lands in state/performance.json, with a readable state/LEARNINGS.md.

Views say who clicked; how much of the Short they watched says whether the story held them. A video record that
carries RETENTION_FIELD (YouTube Analytics' averageViewPercentage, 0-100+, read by youtube.analytics once a Short is
three days old) adds a second score: a group's mean retention against the channel's, shrunk the same way by its own
count, blended in at RETENTION_WEIGHT before the same LIFT_RANGE bounds. Without the yt-analytics.readonly scope the
reader returns nothing, the run's health says so, and lifts are views alone.
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
RETENTION_FIELD = "avg_view_pct"
RETENTION_WEIGHT = 0.5
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
    held_base, retention = _retention(scored)
    if held_base is not None:
        out["baseline_view_pct"] = round(math.expm1(held_base), 1)
    for feature in FEATURES:
        groups: dict[str, list[float]] = {}
        for v, score in zip(scored, logs):
            if v.get(feature):
                groups.setdefault(str(v[feature]), []).append(score)
        for value, scores in groups.items():
            n = len(scores)
            if n < MIN_SAMPLES:
                continue
            diff = (sum(scores) / n - base) * n / (n + PRIOR)
            entry = {"n": n, "typical_views_24h": round(math.expm1(sum(scores) / n))}
            if (held := retention.get(f"{feature}:{value}")) is not None:
                diff = (1 - RETENTION_WEIGHT) * diff + RETENTION_WEIGHT * held["diff"]
                entry |= {"n_retention": held["n"], "typical_view_pct": held["typical"]}
            lift = min(max(math.exp(diff), LIFT_RANGE[0]), LIFT_RANGE[1])
            out["lifts"][f"{feature}:{value}"] = {"n": n, "lift": round(lift, 3)} | entry
    return out


def _retention(scored: list[dict]) -> tuple[float | None, dict]:
    """The channel's mean log retention and, per feature value with MIN_SAMPLES records carrying it, the shrunk
    log-ratio of its mean to the channel's."""
    held = [v for v in scored if isinstance(v.get(RETENTION_FIELD), (int, float)) and v[RETENTION_FIELD] >= 0]
    if len(held) < MIN_SAMPLES:
        return None, {}
    logs = [math.log1p(v[RETENTION_FIELD]) for v in held]
    base = sum(logs) / len(logs)
    out = {}
    for feature in FEATURES:
        groups: dict[str, list[float]] = {}
        for v, score in zip(held, logs):
            if v.get(feature):
                groups.setdefault(str(v[feature]), []).append(score)
        for value, scores in groups.items():
            n = len(scores)
            if n >= MIN_SAMPLES:
                out[f"{feature}:{value}"] = {"n": n, "diff": (sum(scores) / n - base) * n / (n + PRIOR),
                                             "typical": round(math.expm1(sum(scores) / n), 1)}
    return base, out


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
    if learned.get("baseline_view_pct") is not None:
        lines.append(f"Retention: a typical Short is watched {learned['baseline_view_pct']}% through; a group's "
                     f"retention is blended into its lift at {RETENTION_WEIGHT}.")
    for key, v in sorted(learned.get("lifts", {}).items(), key=lambda kv: -kv[1]["lift"]):
        held = (f"; {v['n_retention']} with retention, typically {v['typical_view_pct']}% watched"
                if v.get("n_retention") else "")
        lines.append(f"- {key}: x{v['lift']} ranking lift ({v['n']} Shorts, typical {v['typical_views_24h']} views"
                     f"{held})")
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


def refresh(at: datetime | None = None, force: bool = False, api=None, analytics=None) -> dict | None:
    """Read the channel's numbers and relearn, at most once per REFRESH. Returns what was learned (with "note" when
    YouTube Analytics could not be read), or None if the last read is still fresh. `analytics` is a YouTube Analytics
    v2 client; signed in here it is built from the same sign-in, and a caller passing only `api` reads views alone."""
    from . import youtube

    at = at or datetime.now(timezone.utc)
    perf = ledger.load("performance", {"at": None, "videos": {}})
    note = None
    if not force and perf.get("at") and at - datetime.fromisoformat(perf["at"]) < REFRESH:
        return None
    if api is None:
        api = youtube.client()
        try:
            analytics = youtube.client("youtubeAnalytics", "v2")
        except Exception as exc:  # noqa: BLE001 - retention is an extra; views still count
            note = f"analytics: {type(exc).__name__}: {exc}"[:300]
    stats = {v["id"]: v.get("statistics", {}) for v in youtube.recent(api, youtube.identity(api))}
    for row in ledger.published():
        vid = row.get("video_id")
        if not vid or vid not in stats or _age_h(row, at) < 0:
            continue
        s = stats[vid]
        rec = perf["videos"].setdefault(vid, {"id": row["id"], "published_at": row["published_at"], "snapshots": []})
        rec.update({f: row.get(f) or rec.get(f) for f in FEATURES})
        rec.update({f: row.get(f) or rec.get(f) for f in ("production_version", "producer_sha")})
        rec["snapshots"] = _thin(rec["snapshots"] + [{
            "age_h": round(_age_h(row, at), 2), "views": int(s.get("viewCount", 0)),
            "likes": int(s.get("likeCount", 0)), "comments": int(s.get("commentCount", 0))}])
        rec["views_24h"] = views_at(rec["snapshots"], SCORE_AT_H)
    if analytics is not None:
        try:
            held, note = youtube.analytics(analytics, {v: r["published_at"] for v, r in perf["videos"].items()}, at)
        except Exception as exc:  # noqa: BLE001 - retention is an extra; views still count
            held, note = {}, f"analytics: {type(exc).__name__}: {exc}"[:300]
        for vid, got in held.items():
            perf["videos"][vid].update({RETENTION_FIELD: got["avg_view_pct"], "engaged_views": got["engaged_views"]})
    perf["at"] = at.isoformat(timespec="seconds")
    perf["learned"] = learn(list(perf["videos"].values()))
    ledger.save("performance", perf)
    (ledger.STATE / "LEARNINGS.md").write_text(report(perf), encoding="utf-8")
    return perf["learned"] | ({"note": note} if note else {})
