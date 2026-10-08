"""Identity-pinned YouTube publishing for the Rebuilt in 3D channel: upload private, verify, then make public."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from .spec import Short

CHANNEL_ID = "UCfqAy1IxE2Cwu9pmZGMambA"
TOKEN_FILE = Path(__file__).resolve().parents[1] / "secrets" / "token.json"
CATEGORY = "27"  # Education: explainers, not breaking news
MARKER = "rebuilt-in-3d:"


def client(service: str = "youtube", version: str = "v3"):
    raw = os.environ.get("YOUTUBE_OAUTH_JSON") or (TOKEN_FILE.read_text() if TOKEN_FILE.exists() else "")
    if not raw:
        raise RuntimeError("no YouTube sign-in: set YOUTUBE_OAUTH_JSON or create secrets/token.json")
    creds = Credentials.from_authorized_user_info(json.loads(raw))
    if not creds.valid:
        creds.refresh(Request())
    return build(service, version, credentials=creds, cache_discovery=False)


def identity(api) -> dict:
    items = api.channels().list(part="snippet,statistics,contentDetails", mine=True).execute().get("items", [])
    if len(items) != 1 or items[0]["id"] != CHANNEL_ID:
        raise RuntimeError("signed in to the wrong channel: refusing every write")
    return items[0]


def recent(api, channel: dict, limit: int = 50) -> list[dict]:
    uploads = channel["contentDetails"]["relatedPlaylists"]["uploads"]
    rows = api.playlistItems().list(part="contentDetails", playlistId=uploads, maxResults=limit).execute().get("items", [])
    ids = [r["contentDetails"]["videoId"] for r in rows]
    if not ids:
        return []
    return api.videos().list(part="snippet,status,statistics", id=",".join(ids)).execute().get("items", [])


def find(api, channel: dict, short_id: str) -> dict | None:
    hits = [v for v in recent(api, channel) if MARKER + short_id in (v["snippet"].get("tags") or [])]
    if len(hits) > 1:
        raise RuntimeError(f"{short_id} is on the channel twice: resolve by hand before publishing again")
    return hits[0] if hits else None


def description(short: Short) -> str:
    lines = [short.summary, ""]
    lines += ["What the data shows:"] + [f"• {b.text}" for b in short.beats[1:-1]] + [""]
    lines += ["Sources:"] + short.sources + [""]
    lines += ["This is a 3D reconstruction built from open data, not real footage. The vertical scale is exaggerated "
              "so depth and relief are visible. Narration is synthetic (Kokoro text-to-speech).",
              "Spotted an error? Comment with a source and we will correct it.", ""]
    lines += ["Credits: " + "; ".join(short.credits), ""]
    lines += ["#" + t.replace(" ", "") for t in short.tags[:3]]
    text = "\n".join(lines)
    if len(text) > 4900:
        text = text[:4900]
    return text


def tags(short: Short) -> list[str]:
    out, total = [], 0
    for t in short.tags + ["Rebuilt in 3D", MARKER + short.id]:
        if total + len(t) + 2 > 480:
            break
        out.append(t)
        total += len(t) + 2
    if MARKER + short.id not in out:
        out[-1] = MARKER + short.id
    return out


def publish(short: Short, mp4: Path, max_wait: int = 900) -> dict:
    api = client()
    channel = identity(api)
    existing = find(api, channel, short.id)
    if existing:
        video_id = existing["id"]
    else:
        body = {
            "snippet": {"title": short.title, "description": description(short), "tags": tags(short),
                        "categoryId": CATEGORY, "defaultLanguage": "en", "defaultAudioLanguage": "en"},
            "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True},
        }
        media = MediaFileUpload(str(mp4), mimetype="video/mp4", chunksize=4 * 1024 * 1024, resumable=True)
        request = api.videos().insert(part="snippet,status", body=body, notifySubscribers=True, media_body=media)
        response = None
        while response is None:
            _, response = request.next_chunk(num_retries=3)
        video_id = response["id"]
    deadline = time.monotonic() + max_wait
    while True:
        video = api.videos().list(part="snippet,status,processingDetails", id=video_id).execute()["items"][0]
        if video["snippet"]["channelId"] != CHANNEL_ID:
            raise RuntimeError("uploaded video is on another channel")
        status = video["status"]
        processing = video.get("processingDetails", {}).get("processingStatus")
        if status.get("uploadStatus") in ("failed", "rejected", "deleted") or processing in ("failed", "terminated"):
            raise RuntimeError(f"YouTube rejected the upload: {status.get('rejectionReason') or status.get('failureReason')}")
        if status.get("uploadStatus") == "processed" or processing == "succeeded":
            break
        if time.monotonic() > deadline:
            raise RuntimeError("still processing; the next run will finish publishing it")
        time.sleep(15)
    if video["status"]["privacyStatus"] != "public":
        api.videos().update(part="status", body={"id": video_id, "status": {
            "privacyStatus": "public", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True,
            "embeddable": True, "publicStatsViewable": True}}).execute()
    final = api.videos().list(part="status,snippet", id=video_id).execute()["items"][0]
    if final["status"]["privacyStatus"] != "public":
        raise RuntimeError(f"video {video_id} did not go public ({final['status']['privacyStatus']})")
    return {"video_id": video_id, "url": f"https://www.youtube.com/shorts/{video_id}", "title": final["snippet"]["title"],
            "privacy": "public", "synthetic_flag": final["status"].get("containsSyntheticMedia")}
