"""Validate a finished same-repository weekly build before downloading or releasing its media."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

from . import media_review, review

REPO = "ashivam-dot/rebuilt-in-3d"


def source(run_id: str, source_sha: str, api) -> dict:
    if not re.fullmatch(r"[1-9][0-9]*", run_id) or not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("invalid pinned source run/commit")
    run = api(f"repos/{REPO}/actions/runs/{run_id}")
    if run.get("repository", {}).get("full_name") != REPO \
            or run.get("head_repository", {}).get("full_name") != REPO \
            or run.get("head_sha") != source_sha or run.get("status") != "completed" \
            or run.get("conclusion") != "success" or run.get("path") != ".github/workflows/longform.yml":
        raise RuntimeError("source is not the pinned successful same-repository weekly build")
    rows = api(f"repos/{REPO}/actions/runs/{run_id}/artifacts?per_page=100")["artifacts"]
    artifacts = [a for a in rows if a["name"] == "longform-episode" and not a.get("expired")]
    if len(artifacts) != 1:
        raise RuntimeError("missing or ambiguous finished weekly episode artifact")
    return {"run_id": int(run_id), "source_sha": source_sha, "artifact_id": artifacts[0]["id"],
            "artifact_digest": artifacts[0].get("digest")}


def media(work: Path, expected_sha: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha) \
            or media_review.digest(work / "episode.mp4") != expected_sha:
        raise RuntimeError("downloaded weekly video differs from the reviewed source hash")
    return review.brief(work)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("source", "media"))
    a = p.parse_args()
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise RuntimeError("weekly recovery must run inside its own channel repository")
    if a.mode == "source":
        def api(path):
            return json.loads(subprocess.check_output(["gh", "api", path], timeout=90))
        result = source(os.environ["SOURCE_RUN"], os.environ["SOURCE_SHA"], api)
        Path("work").mkdir(exist_ok=True)
        Path("work/recovery-source.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))
    else:
        result = media(Path("work/longform"), os.environ["VIDEO_SHA256"])
        print(json.dumps({"id": result["metadata"]["id"], "media_bound": True}))


if __name__ == "__main__":
    main()
