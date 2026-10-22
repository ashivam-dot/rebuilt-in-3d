"""Identity-pinned YouTube publishing for the Orbitwire channel: upload private, verify, then make public."""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from . import ledger, media
from .spec import Short

CHANNEL_ID = "UCfqAy1IxE2Cwu9pmZGMambA"
TOKEN_FILE = Path(__file__).resolve().parents[1] / "secrets" / "token.json"
CATEGORY = "27"  # Education: explainers, not breaking news
# Uploads before 2026-10-22 carry MARKER + story id as a public tag ("rebuilt-in-3d:wk-Q123", the channel's first
# name), which viewers can read in the page source. New uploads carry topic tags only; find() still reads the old
# marker so a story uploaded before then is never uploaded again, so it must not change. channel.untag takes it off
# the old uploads (when switched on), keeping each story's video id in the ledger first.
MARKER = "rebuilt-in-3d:"


def client(service: str = "youtube", version: str = "v3"):
    raw = os.environ.get("YOUTUBE_OAUTH_JSON") or (TOKEN_FILE.read_text() if TOKEN_FILE.exists() else "")
    if not raw:
        raise RuntimeError("no YouTube sign-in: set YOUTUBE_OAUTH_JSON or create secrets/token.json")
    creds = Credentials.from_authorized_user_info(json.loads(raw))
    if not creds.valid:
        creds.refresh(Request())
    return build(service, version, credentials=creds, cache_discovery=False)


# channels.update, videos.update and the playlist writes need one of these; an upload-only token is refused (403).
WRITE_SCOPES = {"https://www.googleapis.com/auth/youtube", "https://www.googleapis.com/auth/youtube.force-ssl"}


def scopes() -> set[str] | None:
    """The scopes the sign-in token lists, or None when it lists none (then only the API can tell)."""
    raw = os.environ.get("YOUTUBE_OAUTH_JSON") or (TOKEN_FILE.read_text() if TOKEN_FILE.exists() else "")
    try:
        listed = json.loads(raw).get("scopes") if raw else None
    except (ValueError, AttributeError):
        return None
    if isinstance(listed, str):
        listed = listed.split()
    return set(listed) if listed else None


def identity(api) -> dict:
    items = api.channels().list(part="snippet,statistics,contentDetails", mine=True).execute().get("items", [])
    if len(items) != 1 or items[0]["id"] != CHANNEL_ID:
        raise RuntimeError("signed in to the wrong channel: refusing every write")
    return items[0]


# Uploads the owner had taken down (made private, never deleted): owner review of 2026-10-16.
RETRACTED = {
    "B3TumXzN63I": "M6.8 mid-ocean-ridge quake: nobody felt it, not news",
    "B7Bn2Yhnlp8": "green M6.9 off Kamchatka: not news",
    "MAKHg-RUtRw": "M6.7 mid-ocean-ridge quake: nobody felt it, not news",
    "Pyn07q8sFcs": "Black Sea tanker strike shown with the colour black's photos (a painting, a black hole)",
    "P3_BBUFzurk": "repeat of W2Zvww-jNK4 (2026-10-14): the same Oct 6 Saudi airport attacks, its article renamed",
    # Owner, 2026-10-22: "do you think people are here to watch the map".
    "dMv6M3-6O4s": "Nagqu M7.0 told over 55 s of empty 3D terrain and rings: no town, no people, no damage",
    "gCQ4ZWtobXA": "Macron protest ban told over two Paris maps (11 of 13 sampled moments) and one Eiffel Tower photo: "
                   "no Macron, no protest, no students",
}


def retract(api) -> list[str]:
    """Makes each RETRACTED upload on this channel private (clearing a scheduled publish), once: what it did."""
    done = []
    items = api.videos().list(part="status,snippet", id=",".join(RETRACTED)).execute().get("items", [])
    for v in items:
        if v["snippet"]["channelId"] != CHANNEL_ID or (v["status"]["privacyStatus"] == "private"
                                                      and not v["status"].get("publishAt")):
            continue
        api.videos().update(part="status", body={"id": v["id"], "status": {
            "privacyStatus": "private", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True,
            "embeddable": True, "publicStatsViewable": True}}).execute()
        done.append(f"retracted {v['id']} ({RETRACTED[v['id']]})")
    return done


def recent(api, channel: dict, limit: int = 50) -> list[dict]:
    uploads = channel["contentDetails"]["relatedPlaylists"]["uploads"]
    rows = api.playlistItems().list(part="contentDetails", playlistId=uploads, maxResults=limit).execute().get("items", [])
    ids = [r["contentDetails"]["videoId"] for r in rows]
    if not ids:
        return []
    return api.videos().list(part="snippet,status,statistics", id=",".join(ids)).execute().get("items", [])


# YouTube Analytics v2, read only: what share of each Short viewers watched. Its numbers settle over two or three
# days, so a video counts once it is ANALYTICS_AGE old. The sign-in needs the yt-analytics.readonly scope; without
# it the reader returns nothing and says so once, and lifts stay views alone.
ANALYTICS_METRICS = "views,engagedViews,averageViewPercentage"
ANALYTICS_AGE = timedelta(days=3)
ANALYTICS_BATCH = 200


def analytics(api, published: dict[str, str], at: datetime | None = None) -> tuple[dict, str | None]:
    """{video_id: {"views", "engaged_views", "avg_view_pct"}} for each video in `published` ({video_id: ISO publish
    time}) at least ANALYTICS_AGE old, and a health note when YouTube Analytics refused (403, missing scope)."""
    at = at or datetime.now(timezone.utc)
    when = {v: datetime.fromisoformat(t) for v, t in published.items()}
    old = {v: t for v, t in when.items() if at - t >= ANALYTICS_AGE}
    if not old:
        return {}, None
    ids, out = sorted(old), {}
    try:
        for i in range(0, len(ids), ANALYTICS_BATCH):
            batch = ids[i:i + ANALYTICS_BATCH]
            res = api.reports().query(
                ids="channel==MINE", startDate=min(old[v] for v in batch).date().isoformat(),
                endDate=at.date().isoformat(), metrics=ANALYTICS_METRICS, dimensions="video",
                filters="video==" + ",".join(batch), sort="-views", maxResults=ANALYTICS_BATCH).execute()
            names = [h["name"] for h in res.get("columnHeaders", [])]
            for row in res.get("rows") or []:
                r = dict(zip(names, row))
                if r.get("video") in old:
                    out[r["video"]] = {"views": int(r.get("views") or 0),
                                       "engaged_views": int(r.get("engagedViews") or 0),
                                       "avg_view_pct": float(r.get("averageViewPercentage") or 0.0)}
    except HttpError as exc:
        if exc.resp.status not in (401, 403):
            raise
        return {}, (f"analytics: YouTube Analytics refused ({exc.resp.status}); the sign-in needs the "
                    "yt-analytics.readonly scope. Lifts are views alone.")
    except RefreshError as exc:
        return {}, f"analytics: sign-in refused for YouTube Analytics ({exc}). Lifts are views alone."[:300]
    return out, None


def find(api, channel: dict, short_id: str) -> dict | None:
    """The upload already made for a story, if any: the one the ledger records (published, or uploaded and not yet
    public, state/uploads.json; or read off its old MARKER tag before channel.untag took it, state/markers.json) while
    it is still on this channel, else one of the recent uploads still carrying the old MARKER tag."""
    known = [r.get("video_id") for r in ledger.published() if r["id"] == short_id]
    known.append((ledger.uploads().get(short_id) or {}).get("video_id"))
    known.append(ledger.markers().get(short_id))
    ids = list(dict.fromkeys(v for v in known if v))
    hits = []
    if ids:
        items = api.videos().list(part="snippet,status", id=",".join(ids)).execute().get("items", [])
        hits = [v for v in items if v["snippet"]["channelId"] == CHANNEL_ID]
    if not hits:
        hits = [v for v in recent(api, channel) if MARKER + short_id in (v["snippet"].get("tags") or [])]
    if len(hits) > 1:
        raise RuntimeError(f"{short_id} is on the channel twice: resolve by hand before publishing again")
    return hits[0] if hits else None


# How far back an upload the ledger lost can be found again: a state save that failed (a rebase conflict, a failed
# push, a lost runner) is retried by the next hourly run, and a story is rebuilt within a day or two.
UNRECORDED_AGE = timedelta(hours=48)


class Unrecorded(RuntimeError):
    """This story is already on the channel as an upload the ledger does not know: never upload it a second time."""


def unrecorded(api, channel: dict, short: Short, at: datetime | None = None) -> dict | None:
    """An upload of this story the ledger lost: one of the recent uploads under UNRECORDED_AGE old (private,
    scheduled, or public when the state save after publishing was the one lost) that no ledger row or old MARKER tag
    claims and whose description lists the story's Wikipedia or first source URL (already public, so nothing new is
    said about which video is which story)."""
    at = at or datetime.now(timezone.utc)
    urls = [u for u in dict.fromkeys(short.sources[:1] + [u for u in short.sources if "wikipedia.org/" in u]) if u]
    if not urls:
        return None
    known = {r.get("video_id") for r in ledger.published()} | {u.get("video_id") for u in ledger.uploads().values()}
    known |= ledger.longform_videos()
    for v in recent(api, channel):
        snippet = v["snippet"]
        uploaded = snippet.get("publishedAt")
        if v["id"] in known or v["id"] in RETRACTED or not uploaded:
            continue
        if any(t.startswith(MARKER) for t in snippet.get("tags") or []):
            continue
        if at - datetime.fromisoformat(uploaded.replace("Z", "+00:00")) > UNRECORDED_AGE:
            continue
        lines = set((snippet.get("description") or "").splitlines())
        if any(u in lines for u in urls):
            return v
    return None


def source_lines(short: Short) -> list[str]:
    """The sources block: "Sources: Wikipedia, BBC, The Hindu" naming who the facts come from (when trusted outlets'
    reporting backs any), then every source URL."""
    named = short.scene.get("outlets") or []
    if not named:
        return ["Sources:"] + short.sources + [""]
    wiki = ["Wikipedia"] if any("wikipedia.org" in s or "wikidata.org" in s for s in short.sources) else []
    return ["Sources: " + ", ".join(wiki + named)] + short.sources + [""]


DESCRIPTION_BYTES = 5000
# What the desk does before a Short goes out, said once in every description: reviewers of a channel read how it is
# made, and the checks are mechanical (gate.py, the writer's evidence check), so no person is claimed to review it.
EDITORIAL = ("How it is made: a story is told only when the world is already following it; every name and number "
             "must appear in Wikipedia/Wikidata or in two independent outlets' reports, each line is checked against "
             "them before upload, and a death toll is said only when the sources agree on it.")
EDITORIAL_QUAKE = ("How it is made: every number comes from the USGS event data listed above and is checked against "
                   "it before upload; the scene is rebuilt from open terrain data, nothing is invented.")


def description(short: Short) -> str:
    """The full description; when it passes YouTube's 5,000 bytes, without the narration (the video says it), so the
    sources and every photo credit stay. Only a description still too long after that is cut."""
    text = _description(short, narration=True)
    if len(text.encode()) > DESCRIPTION_BYTES:
        text = _description(short, narration=False)
    while len(text.encode()) > DESCRIPTION_BYTES:
        text = text[:-50]
    return text


def _description(short: Short, narration: bool) -> str:
    lines = [short.summary, ""]
    if short.scene.get("template") == "story" or short.scene.get("narration") == "story":
        if narration:
            lines += [" ".join(b.text for b in short.beats[:-1]), ""]
        lines += source_lines(short)
        pictures = (f"The photos are real, from {media.hosts(short.scene.get('photos') or [])}, with a gentle 3D "
                    "camera move added." if short.scene.get("template") == "story" else
                    "The pictures are a 3D reconstruction of the location from open terrain data, not real footage.")
        if any(p.get("role") == "map" for p in short.scene.get("photos") or []):
            pictures += (" The maps are OpenStreetMap (© OpenStreetMap contributors), with the site marked by "
                         "Orbitwire: they show where it happened, not what happened.")
        lines += [pictures + " The narration is an AI voice (Chatterbox) reading a script checked line by line "
                  "against the sources above.", EDITORIAL,
                  "Spotted an error? Comment with a source and we will correct it.", ""]
        lines += ["Credits:"] + [f"• {c}" for c in short.credits] + [""]
    else:
        lines += ["What the data shows:"] + [f"• {b.text}" for b in short.beats[1:-1]] + [""]
        lines += ["Sources:"] + short.sources + [""]
        lines += ["This is a 3D reconstruction built from open data, not real footage. The vertical scale is "
                  "exaggerated so depth and relief are visible. Narration is synthetic (Kokoro text-to-speech).",
                  EDITORIAL_QUAKE, "Spotted an error? Comment with a source and we will correct it.", ""]
        lines += ["Credits: " + "; ".join(short.credits), ""]
    words = ["".join(w[:1].upper() + w[1:] for w in h.split()) if " " in h else h for h in short.hashtags]
    lines.append(" ".join("#" + re.sub(r"[^0-9A-Za-z]", "", w) for w in words if re.sub(r"[^0-9A-Za-z]", "", w)))
    return "\n".join(lines)


def tags(short: Short) -> list[str]:
    """The story's topic tags and the channel's name, within YouTube's 500 characters; no machine identifier (the
    ledger knows which video is which story)."""
    out, total = [], 0
    for t in short.tags + ["Orbitwire"]:
        if total + len(t) + 2 > 480:
            break
        out.append(t)
        total += len(t) + 2
    return out


def publish(short: Short, mp4: Path, max_wait: int = 900, publish_at: str | None = None) -> dict:
    """Upload and make public now, or with publish_at (ISO UTC, in the future) leave it private for YouTube to
    release at that time."""
    api = client()
    channel = identity(api)
    existing = find(api, channel, short.id)
    if existing:
        video_id = existing["id"]
    elif twin := unrecorded(api, channel, short):
        raise Unrecorded(f"{twin['id']} (uploaded {twin['snippet'].get('publishedAt')}, "
                         f"{(twin.get('status') or {}).get('privacyStatus')}) lists this story's source but no ledger row: the "
                         "state save after its upload was lost; publish or delete it in Studio, never upload again")
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
        # Recorded at once: a run cut short while YouTube processes it finishes this upload next time (find).
        ledger.record_upload(short.id, video_id)
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
    if publish_at:
        api.videos().update(part="status", body={"id": video_id, "status": {
            "privacyStatus": "private", "publishAt": publish_at, "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True, "embeddable": True, "publicStatsViewable": True}}).execute()
        final = api.videos().list(part="status,snippet", id=video_id).execute()["items"][0]
        if not final["status"].get("publishAt"):
            raise RuntimeError(f"video {video_id} was not scheduled")
        return {"video_id": video_id, "url": f"https://www.youtube.com/shorts/{video_id}",
                "title": final["snippet"]["title"], "privacy": "scheduled", "publish_at": final["status"]["publishAt"],
                "synthetic_declared": True}
    if video["status"]["privacyStatus"] != "public":
        api.videos().update(part="status", body={"id": video_id, "status": {
            "privacyStatus": "public", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True,
            "embeddable": True, "publicStatsViewable": True}}).execute()
    # videos.list can report the old privacy for a while after the update.
    for wait in (0, 5, 10, 20, 30):
        time.sleep(wait)
        final = api.videos().list(part="status,snippet", id=video_id).execute()["items"][0]
        if final["status"]["privacyStatus"] == "public":
            break
    else:
        raise RuntimeError(f"video {video_id} did not go public ({final['status']['privacyStatus']})")
    # containsSyntheticMedia is write-only in practice: videos.list omits it even though Studio shows "AI use: Yes".
    return {"video_id": video_id, "url": f"https://www.youtube.com/shorts/{video_id}", "title": final["snippet"]["title"],
            "privacy": "public", "synthetic_declared": True}
