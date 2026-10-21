"""Upload an episode private, then schedule it, exactly once; then link it from the Shorts it grew from.

state/longform.json is the episode ledger (no Short job writes it; ledger.longform_videos lets them know its ids):
  {"episodes": {episode id: {"video_id", "state", "title", "topic_key", "publish_at", "at", ...}},
   "playlist": the "Orbitwire Explains" playlist id, "links": {episode id: {"shorts": [...], "done": [...]}}}
Each step is saved as soon as it is done, so a run cut short resumes where it stopped: an episode with a video id is
never uploaded again, and an upload whose save was lost is adopted by its exact title instead of uploaded twice.
The thumbnail (needs a phone-verified channel) and the captions (need the youtube.force-ssl scope) are best effort:
a refusal is recorded, not fatal. The Shorts' descriptions are edited only after the episode is public, by
read-modify-write of the whole snippet (videos.update replaces every snippet field it is given and drops tags it
is not given), once per Short.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from .. import ledger, youtube
from . import describe, topics

PLAYLIST = "Orbitwire Explains"
PLAYLIST_ABOUT = ("Orbitwire's long-form explainers: one natural hazard a week, told from open USGS and NOAA data: what "
                  "happened, how it works, its history and what comes next.")
MAX_LINKS = 4
LINK_LINE = "The full explainer: https://www.youtube.com/watch?v={id}"
SNIPPET_KEYS = ("title", "description", "tags", "categoryId", "defaultLanguage", "defaultAudioLanguage")


def _http_error():
    from googleapiclient.errors import HttpError

    return HttpError


def load() -> dict:
    state = ledger.load("longform", {})
    state.setdefault("episodes", {})
    state.setdefault("links", {})
    return state


def save(state: dict) -> None:
    ledger.save("longform", state)


def push_state(message: str) -> str:
    """Commit and push state/longform.json at once (Actions only): the hourly Shorts run must know the episode's video
    id as soon as it exists, not up to an hour later when this job's last step saves state, or a Short whose source
    the episode also cites could adopt the episode as its own upload. Best effort: the job's own save step follows."""
    import os
    import subprocess

    if os.environ.get("GITHUB_ACTIONS") != "true" or not (ledger.STATE / ".git").exists():
        return "skipped: not a state checkout in Actions"

    def git(*args: str) -> bool:
        return subprocess.run(["git", "-C", str(ledger.STATE), *args], capture_output=True, timeout=120).returncode == 0

    ledger.set_identity()
    git("add", "longform.json")
    git("commit", "-q", "-m", message, "--", "longform.json")
    for i in range(5):
        if git("pull", "-q", "--rebase", "origin", "state") and git("push", "-q", "origin", "HEAD:state"):
            return "pushed"
        time.sleep(10 * (i + 1))
    return "not pushed: the job's save step will retry"


def known_ids() -> set[str]:
    return ({r.get("video_id") for r in ledger.published()} | {u.get("video_id") for u in ledger.uploads().values()}
            | set(ledger.markers().values()) | ledger.longform_videos())


def adopt(api, channel: dict, title: str) -> str | None:
    """A recent upload with this exact title that no ledger knows: this episode's upload whose save was lost."""
    known = known_ids()
    hits = [v for v in youtube.recent(api, channel) if v["snippet"].get("title") == title and v["id"] not in known
            and v["id"] not in youtube.RETRACTED]
    return hits[0]["id"] if len(hits) == 1 else None


def upload(api, mp4: Path, meta: dict, desc: str) -> str:
    from googleapiclient.http import MediaFileUpload

    body = {"snippet": {"title": meta["title"], "description": desc, "tags": meta["tags"],
                        "categoryId": youtube.CATEGORY, "defaultLanguage": "en", "defaultAudioLanguage": "en"},
            "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True,
                       "embeddable": True, "publicStatsViewable": True}}
    media = MediaFileUpload(str(mp4), mimetype="video/mp4", chunksize=4 * 1024 * 1024, resumable=True)
    request = api.videos().insert(part="snippet,status", body=body, notifySubscribers=True, media_body=media)
    response = None
    while response is None:
        _, response = request.next_chunk(num_retries=3)
    return response["id"]


def processed(api, video_id: str, max_wait: float, sleep=time.sleep) -> dict:
    deadline = time.monotonic() + max_wait
    while True:
        video = api.videos().list(part="snippet,status,processingDetails", id=video_id).execute()["items"][0]
        if video["snippet"]["channelId"] != youtube.CHANNEL_ID:
            raise RuntimeError("the uploaded video is on another channel")
        status = video["status"]
        state = (video.get("processingDetails") or {}).get("processingStatus")
        if status.get("uploadStatus") in ("failed", "rejected", "deleted") or state in ("failed", "terminated"):
            raise RuntimeError(f"YouTube rejected the upload: {status.get('rejectionReason') or status.get('failureReason')}")
        if status.get("uploadStatus") == "processed" or state == "succeeded":
            return video
        if time.monotonic() > deadline:
            raise RuntimeError(f"{video_id} still processing (it is recorded): re-run this run's failed jobs to "
                               "finish it; a new run will not, as the week is taken")
        sleep(30)


def best_effort(step, *args) -> str:
    HttpError = _http_error()
    try:
        step(*args)
        return "done"
    except HttpError as exc:
        return f"refused: HTTP {exc.resp.status} {exc.reason if hasattr(exc, 'reason') else ''}".strip()[:200]


def set_thumbnail(api, video_id: str, jpg: Path) -> None:
    from googleapiclient.http import MediaFileUpload

    api.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(jpg), mimetype="image/jpeg")).execute()


def set_captions(api, video_id: str, srt: Path) -> None:
    from googleapiclient.http import MediaFileUpload

    api.captions().insert(part="snippet", body={"snippet": {"videoId": video_id, "language": "en", "name": "English",
                                                            "isDraft": False}},
                          media_body=MediaFileUpload(str(srt), mimetype="application/octet-stream")).execute()


def schedule(api, video_id: str, publish_at: str) -> str:
    api.videos().update(part="status", body={"id": video_id, "status": {
        "privacyStatus": "private", "publishAt": publish_at, "selfDeclaredMadeForKids": False,
        "containsSyntheticMedia": True, "embeddable": True, "publicStatsViewable": True}}).execute()
    final = api.videos().list(part="status", id=video_id).execute()["items"][0]["status"]
    if not final.get("publishAt"):
        raise RuntimeError(f"{video_id} was not scheduled (status {final})")
    return final["publishAt"]


def playlist(api, state: dict, video_id: str) -> str:
    pid = state.get("playlist")
    if not pid:
        mine = api.playlists().list(part="snippet", mine=True, maxResults=50).execute().get("items", [])
        hit = next((p for p in mine if p["snippet"].get("title") == PLAYLIST), None)
        if hit is None:
            hit = api.playlists().insert(part="snippet,status", body={
                "snippet": {"title": PLAYLIST, "description": PLAYLIST_ABOUT, "defaultLanguage": "en"},
                "status": {"privacyStatus": "public"}}).execute()
        pid = state["playlist"] = hit["id"]
        save(state)
    items = api.playlistItems().list(part="contentDetails", playlistId=pid, maxResults=50).execute().get("items", [])
    if video_id not in {i["contentDetails"]["videoId"] for i in items}:
        api.playlistItems().insert(part="snippet", body={"snippet": {
            "playlistId": pid, "resourceId": {"kind": "youtube#video", "videoId": video_id}}}).execute()
    return pid


def publish(work: Path, api=None, at: datetime | None = None, max_wait: float = 1800, sleep=time.sleep) -> dict:
    """The episode in work (assemble.finish's outputs), uploaded private and scheduled. What it did."""
    at = at or datetime.now(timezone.utc)
    meta = json.loads((work / "meta.json").read_text(encoding="utf-8"))
    if meta.get("problems"):
        raise RuntimeError("the episode failed QA; refusing to upload: " + "; ".join(meta["problems"]))
    publish_at = datetime.fromisoformat(meta["publish_at"].replace("Z", "+00:00"))
    desc = (work / "description.txt").read_text(encoding="utf-8")
    if describe.size(desc) > describe.LIMIT:
        raise RuntimeError("the description is over 5000 bytes")
    state = load()
    row = state["episodes"].get(meta["id"])
    if row and row.get("state") == "scheduled":
        return {"episode": meta["id"], "video_id": row["video_id"], "did": "nothing: already scheduled"}
    if (not row or not row.get("video_id")) and not meta.get("override") and \
            (taken := topics.slot_taken(state, meta["publish_at"], meta["id"])):
        raise RuntimeError(f"episode {taken} already holds the week of {meta['publish_at']}: refusing to schedule a "
                           f"second episode ({meta['id']}) into it; plan with --topic to make one anyway")
    api = api or youtube.client()
    channel = youtube.identity(api)
    did = []
    if not row or not row.get("video_id"):
        if publish_at <= at:
            raise RuntimeError(f"publishAt {meta['publish_at']} has passed: plan the episode again")
        video_id = adopt(api, channel, meta["title"])
        if video_id:
            did.append(f"adopted {video_id} (an upload whose save was lost)")
        else:
            video_id = upload(api, work / "episode.mp4", meta, desc)
            did.append(f"uploaded {video_id} (private)")
        row = state["episodes"][meta["id"]] = {
            "video_id": video_id, "state": "uploaded", "title": meta["title"], "topic_key": meta.get("topic_key"),
            "publish_at": meta["publish_at"], "sha256": meta.get("sha256"), "at": ledger.now()}
        save(state)
        did.append("state " + push_state(f"longform: uploaded {meta['id']} as {video_id}"))
    video_id = row["video_id"]
    processed(api, video_id, max_wait, sleep)
    if "thumbnail" not in row:
        row["thumbnail"] = best_effort(set_thumbnail, api, video_id, work / "thumbnail.jpg")
        save(state)
    if "captions" not in row:
        row["captions"] = best_effort(set_captions, api, video_id, work / "captions.srt")
        save(state)
    if publish_at <= at:
        raise RuntimeError(f"publishAt {meta['publish_at']} passed before {video_id} was scheduled: it stays private "
                           "for the owner to publish in Studio")
    row["publish_at"] = schedule(api, video_id, meta["publish_at"])
    row["state"] = "scheduled"
    save(state)
    did.append(f"scheduled for {row['publish_at']}")
    try:
        row["playlist"] = playlist(api, state, video_id)
    except _http_error() as exc:
        row["playlist"] = f"refused: HTTP {exc.resp.status}"
    shorts = [s["video_id"] for s in sorted(meta.get("related") or [], key=lambda s: -s.get("views_24h", 0))
              if s.get("video_id") and s["video_id"] not in youtube.RETRACTED][:MAX_LINKS]
    state["links"].setdefault(meta["id"], {"video_id": video_id, "shorts": shorts, "done": []})
    save(state)
    return {"episode": meta["id"], "video_id": video_id, "did": did, "thumbnail": row["thumbnail"],
            "captions": row["captions"], "playlist": row["playlist"], "publish_at": row["publish_at"]}


def linked(description: str, video_id: str) -> bool:
    return LINK_LINE.format(id=video_id) in description or f"watch?v={video_id}" in description


def link(api=None, at: datetime | None = None) -> list[str]:
    """For each scheduled episode that is now public, add its link to its Shorts' descriptions, once each."""
    at = at or datetime.now(timezone.utc)
    state = load()
    pending = {k: v for k, v in state["links"].items() if set(v["shorts"]) - set(v["done"])}
    due = {k: v for k, v in pending.items()
           if datetime.fromisoformat(state["episodes"][k]["publish_at"].replace("Z", "+00:00")) <= at}
    if not due:
        return []
    api = api or youtube.client()
    youtube.identity(api)
    out = []
    for key, row in due.items():
        status = api.videos().list(part="status", id=row["video_id"]).execute()["items"][0]["status"]
        if status.get("privacyStatus") != "public":
            out.append(f"{key}: {row['video_id']} is not public yet")
            continue
        for sid in [s for s in row["shorts"] if s not in row["done"]]:
            items = api.videos().list(part="snippet", id=sid).execute().get("items", [])
            if not items or items[0]["snippet"].get("channelId") != youtube.CHANNEL_ID:
                row["done"].append(sid)
                out.append(f"{key}: Short {sid} is gone or not ours; skipped")
                continue
            snippet = items[0]["snippet"]
            text = snippet.get("description") or ""
            if not linked(text, row["video_id"]):
                new = f"{LINK_LINE.format(id=row['video_id'])}\n\n{text}" if text else LINK_LINE.format(id=row["video_id"])
                if describe.size(new) > describe.LIMIT:
                    row["done"].append(sid)
                    out.append(f"{key}: Short {sid}'s description is full; no link added")
                    save(state)
                    continue
                body = {k: snippet[k] for k in SNIPPET_KEYS if k in snippet} | {"description": new}
                api.videos().update(part="snippet", body={"id": sid, "snippet": body}).execute()
                out.append(f"{key}: linked from Short {sid}")
            row["done"].append(sid)
            save(state)
    return out
