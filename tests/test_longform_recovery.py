"""Recovery cannot turn stale metadata, uncertain uploads or refused media into a release."""
import copy
import json
from types import SimpleNamespace

import pytest

from studio import ledger, youtube
from studio.longform import media_review, publish, recover, review
from .test_longform import AT, FakeYouTube, _episode, _work


def test_changed_media_or_missing_approval_never_reaches_youtube(tmp_path):
    work = _work(tmp_path, _episode())
    api = FakeYouTube()
    (work / "review/av-review.json").unlink()
    with pytest.raises(RuntimeError, match="approval is required"):
        publish.publish(work, api=api, at=AT)
    (work / "episode.mp4").write_bytes(b"different video")
    with pytest.raises(RuntimeError, match="hash differs"):
        publish.publish(work, api=api, at=AT)
    assert not api.inserted and not api.updates


@pytest.mark.parametrize("tags", [[], ["orbitwire-longform:lf-2026w43-panama", "orbitwire-longform-sha256:" + "f" * 64]])
def test_a_title_or_episode_match_without_exact_media_holds_instead_of_duplicate_upload(tmp_path, tags):
    ep = _episode()
    api = FakeYouTube([{"id": "UNCERTAIN01", "snippet": {"title": ep.title, "channelId": youtube.CHANNEL_ID,
                                                         "tags": tags}, "status": {"privacyStatus": "private"}}])
    with pytest.raises(RuntimeError, match="unbound or different-media"):
        publish.publish(_work(tmp_path, ep), api=api, at=AT)
    assert not api.inserted and not api.updates


def test_a_wrong_schedule_readback_keeps_the_known_upload_for_retry(tmp_path):
    class WrongSlot(FakeYouTube):
        def update(self, part, body):
            if part == "status" and "publishAt" in body.get("status", {}):
                body = copy.deepcopy(body)
                body["status"]["publishAt"] = "2026-10-31T14:00:00Z"
            return super().update(part, body)
    work = _work(tmp_path, _episode())
    api = WrongSlot()
    with pytest.raises(RuntimeError, match="was not scheduled"):
        publish.publish(work, api=api, at=AT)
    row = ledger.load("longform", {})["episodes"][_episode().id]
    assert row["state"] == "uploaded" and row["video_id"] in api.store
    assert len(api.inserted) == 1


def test_a_refused_exact_media_review_survives_a_fresh_runner_without_another_model_call(tmp_path, monkeypatch):
    work = _work(tmp_path, _episode())
    receipt = json.loads((work / "review/av-review.json").read_text())
    receipt["verdict"]["decision"] = "hold"
    receipt["verdict"]["checks"]["speech_clear"] = False
    with monkeypatch.context() as m:
        m.setattr(media_review, "review", lambda *a: receipt)
        with pytest.raises(RuntimeError, match="speech_clear"):
            review.run(work)
    (work / "review/av-review.json").unlink()
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="speech_clear"):
        review.run(work)
    saved = ledger.STATE / "longform-reviews" / (receipt["video_sha256"] + ".json")
    assert json.loads(saved.read_text())["verdict"]["decision"] == "hold"
    (work / "description.txt").write_text("Changed brief trying to evade the old refusal")
    with pytest.raises(RuntimeError, match="saved review differs"):
        review.run(work)


def test_recovery_requires_exact_successful_same_repository_build_and_one_live_artifact():
    run = {"repository": {"full_name": recover.REPO}, "head_repository": {"full_name": recover.REPO},
           "head_sha": "a" * 40, "status": "completed", "conclusion": "success",
           "path": ".github/workflows/longform.yml"}
    artifact = {"id": 42, "name": "longform-episode", "expired": False}
    def api(path):
        return {"artifacts": [artifact]} if "/artifacts?" in path else run
    assert recover.source("123", "a" * 40, api)["artifact_id"] == 42
    for field, value in [("head_sha", "b" * 40), ("conclusion", "failure"),
                         ("repository", {"full_name": "someone/fork"}), ("path", ".github/workflows/run.yml")]:
        original = run[field]
        run[field] = value
        with pytest.raises(RuntimeError, match="pinned successful"):
            recover.source("123", "a" * 40, api)
        run[field] = original
    artifact["expired"] = True
    with pytest.raises(RuntimeError, match="missing or ambiguous"):
        recover.source("123", "a" * 40, api)
    with pytest.raises(ValueError, match="invalid pinned"):
        recover.source("123; command", "a" * 40, api)


@pytest.mark.parametrize("oversized_proxy", [False, True])
def test_full_episode_reviewer_receives_complete_audio_video_and_readable_samples(tmp_path, monkeypatch, oversized_proxy):
    work = _work(tmp_path, _episode())
    verdict = json.loads((work / "review/av-review.json").read_text())["verdict"]
    (work / "review/av-review.json").unlink()
    calls, requests = [], []
    def command(args, **kwargs):
        calls.append(args)
        if args[0] == "ffprobe":
            return SimpleNamespace(stdout=json.dumps({"format": {"duration": "600"}}))
        target = __import__("pathlib").Path(args[-1])
        if oversized_proxy and target.name == "review-video.mp4" and "-b:v" not in args:
            with target.open("wb") as fh:
                fh.truncate(13_000_001)
        else:
            target.write_bytes(b"actual stream fixture")
        return SimpleNamespace()
    def post(url, **kwargs):
        requests.append(kwargs["json"])
        return SimpleNamespace(status_code=200, json=lambda: {"candidates": [{"finishReason": "STOP",
                     "content": {"parts": [{"text": json.dumps(verdict)}]}}]})
    monkeypatch.setenv("GEMINI_API_KEY", "test-only")
    monkeypatch.setattr(media_review.subprocess, "run", command)
    monkeypatch.setattr(media_review.requests, "post", post)
    monkeypatch.setattr(media_review, "_models", lambda key: ["gemini-3.6-flash"])
    receipt = media_review.review(work / "episode.mp4", review.brief(work), work / "review")
    parts = requests[0]["contents"][0]["parts"]
    types = [p["inlineData"]["mimeType"] for p in parts if "inlineData" in p]
    assert types.count("video/mp4") == 1 and types.count("audio/ogg") == 1 and types.count("image/jpeg") == 9
    whole = [c for c in calls if c[-1].endswith(("review-video.mp4", "review-audio.ogg"))]
    assert len(whole) == (3 if oversized_proxy else 2)
    assert all(not {"-t", "-to", "-ss"} & set(c) for c in whole)
    assert all("-an" in c for c in whole if c[-1].endswith("review-video.mp4"))
    if oversized_proxy:
        assert "-maxrate" in whole[-1] and int(whole[-1][whole[-1].index("-b:v") + 1]) >= 32_000
    assert receipt["duration"] == 600 and len(receipt["review_frame_sha256"]) == 9
    assert not review.problems(receipt, work, review.brief(work))
