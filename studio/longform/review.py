"""Review a finished weekly episode once and retain exact-media refusals across runners."""
from __future__ import annotations

import json
from pathlib import Path

from .. import ledger
from . import media_review


def brief(work: Path) -> dict:
    meta = json.loads((work / "meta.json").read_text())
    if meta.get("problems"):
        raise RuntimeError("the episode failed QA; refusing audiovisual approval")
    if meta.get("sha256") != media_review.digest(work / "episode.mp4"):
        raise RuntimeError("the finished episode hash differs from its QA metadata")
    episode = json.loads((work / "episode.json").read_text())
    if episode.get("id") != meta.get("id") or episode.get("title") != meta.get("title"):
        raise RuntimeError("the episode brief differs from its finished metadata")
    return {"channel": "Orbitwire", "format": "weekly-3d-explainer", "episode": episode,
            "metadata": meta, "description": (work / "description.txt").read_text(),
            "captions": (work / "captions.srt").read_text(),
            "rules": "Open USGS/NOAA data, clearly labelled original diagrams and relevant licensed visuals. "
                     "Never depict invented real-incident footage or confuse a locator with event footage. "
                     "Maintain the established world narrator, natural pronunciation, readable captions, "
                     "music balance, correct names/numbers, uncertainty and a complete explanatory payoff. "
                     "Watch and listen to the complete episode and each chapter transition."}


def problems(receipt: dict, work: Path, editorial: dict) -> list[str]:
    found = media_review.receipt_problems(receipt, work / "episode.mp4", editorial)
    if receipt.get("review_contract") != "orbitwire-weekly-av-v1" \
            or not 480 <= receipt.get("duration", 0) <= 870:
        found.append("missing complete weekly-episode review contract")
    frames = receipt.get("review_frame_sha256", [])
    if len(frames) != 9 or any(not isinstance(x, str) or len(x) != 64 for x in frames):
        found.append("missing higher-resolution opening/middle/ending frame provenance")
    return found


def require(work: Path) -> dict:
    editorial = brief(work)
    path = work / "review/av-review.json"
    if not path.exists():
        raise RuntimeError("complete exact-media audiovisual approval is required before upload")
    receipt = json.loads(path.read_text())
    if found := problems(receipt, work, editorial):
        raise RuntimeError("weekly audiovisual hold: " + "; ".join(found))
    return receipt


def run(work: Path) -> dict:
    editorial = brief(work)
    folder = work / "review"
    folder.mkdir(parents=True, exist_ok=True)
    digest = media_review.digest(work / "episode.mp4")
    saved = ledger.STATE / "longform-reviews" / (digest + ".json")
    target = folder / "av-review.json"
    if saved.exists():
        old = json.loads(saved.read_text())
        if old.get("video_sha256") != digest \
                or old.get("brief_sha256") != media_review.brief_digest(editorial):
            raise RuntimeError("saved review differs from this media/brief; reconcile it before retrying")
        target.write_bytes(saved.read_bytes())
    receipt = media_review.review(work / "episode.mp4", editorial, folder)
    # Persist either decision before the workflow's separate publication step.
    saved.parent.mkdir(parents=True, exist_ok=True)
    temporary = saved.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(saved)
    target.write_bytes(saved.read_bytes())
    return require(work)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=Path)
    args = parser.parse_args()
    result = run(args.work)
    print(json.dumps({k: result[k] for k in ("model", "video_sha256", "duration")}))
