"""One-shot channel jobs that ride the scheduled run: the About text and keywords, playlists by series with their
Home sections, and taking the old public MARKER tag off uploads made before 2026-10-22.

Each job is off unless named in the repo-root file CHANNEL_JOBS (one per line: "setup", "untag"; "#" comments) or the
environment variable STUDIO_CHANNEL_JOBS ("setup,untag"). run.yml passes no such variable and a security hook keeps
workflow files unedited, so the file, committed to main, is the switch the scheduled run sees. Every job is idempotent
(done-ness in state/channel.json, and YouTube itself is read before each write), spends at most RUN_UNITS of the
project's 10,000-unit day and DAY_UNITS of it across runs (uploads need the rest), stops for the day on quotaExceeded
and for the run when the sign-in lacks a write scope, gives up on one video or playlist after MAX_FAILURES, and is
called inside a try in cli.run so it can never stop a publish.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from googleapiclient.errors import HttpError

from . import ledger, youtube

ROOT = Path(__file__).resolve().parents[1]
JOBS_FILE = ROOT / "CHANNEL_JOBS"
JOBS = ("setup", "untag")

# Quota: list calls cost 1 unit, every insert or update 50 (channels.update, playlists.insert, playlistItems.insert,
# channelSections.insert, videos.update). The day is YouTube's, which resets at midnight Pacific time.
READ, WRITE = 1, 50
RUN_UNITS = 500
DAY_UNITS = 1500
QUOTA_DAY = ZoneInfo("America/Los_Angeles")
MAX_FAILURES = 2  # a video or playlist refused twice is left alone (and listed) instead of spending every run on it
UNTAG_PER_RUN = 5
UPLOAD_PAGES = 6  # the uploads playlist, 50 a page: the whole channel (about 45 uploads on 2026-10-22)

# About (brandingSettings.channel.description, under YouTube's 1,000 characters), keywords and language. Every claim is
# what CHANNEL.md binds the desk to: real photos, 3D only for quakes, two independent sources, AI voice, corrections.
ABOUT = """Orbitwire tells the stories the world is following as short documentaries in English.

Pictures: real, freely licensed photos (Wikimedia Commons, Openverse, NASA), each credited, with a gentle camera move; nothing in a photo is altered. Earthquakes are rebuilt in 3D on real terrain from USGS data, marked "not real footage". We never generate a realistic image of a real person or event.

Sources: every name and number must appear in Wikipedia/Wikidata or in reports from at least two independent outlets (USGS for quakes), listed in each description. A death toll is said only when the sources agree.

Voice: an AI voice reads a script checked line by line against those sources; every upload is labelled as altered or synthetic content.

Editorial rules: no gore, no victims shown, attackers never named, no guessing at causes.

Corrections: comment with a source. A wrong fact is fixed in the description; a wrong number on screen means the Short is taken down and remade."""
KEYWORDS = ["Orbitwire", "world news", "news explained", "short documentary", "earthquake", "earthquakes in 3D",
            "USGS", "hurricane", "natural disasters", "obituary", "remembering", "real photos"]
LANGUAGE = "en"

# Playlists by series, each with the rule that files a published ledger row into it. Topic lists follow the ledger's
# kind and category; a hand-made series names its parts in order. Titles say only what the videos are: storms are
# photo stories, so they are not called "in 3D".
NATURAL = re.compile(r"\b(hurricane|typhoon|cyclone|tropical storm|storm|flood|floods|wildfire|volcano|eruption|"
                     r"landslide|tsunami|cloudburst)\b", re.I)
PLAYLISTS = {
    "quakes": {"title": "Earthquakes in 3D",
               "description": "Major earthquakes rebuilt on real terrain from USGS data: where the fault ruptured, how "
                              "deep, and who felt it. 3D reconstructions from data, not real footage.",
               "match": lambda r: r.get("kind") == "quake"},
    "storms": {"title": "Storms and Natural Disasters",
               "description": "Hurricanes, cyclones, floods and other natural disasters, told with real photos and "
                              "facts from Wikipedia, Wikidata and independent outlets.",
               "match": lambda r: r.get("kind") == "incident" and (
                   r.get("category") == "cyclone" or bool(NATURAL.search(r.get("title") or "")))},
    "lives": {"title": "Lives Remembered",
              "description": "Short tributes to well-known people who have died: their work and what they leave "
                             "behind, told with real photos and sourced facts.",
              "match": lambda r: r.get("kind") == "death"},
}
SERIES = {
    "cjp": {"title": "The Cockroach Janta Party, in Parts",
            "description": "The Cockroach Janta Party story in parts, in order, from sourced reporting.",
            "parts": ["wk-Q139857349-p1", "wk-Q140615137-p2", "wk-Q139857349-p3"]},
}


class Stop(RuntimeError):
    """No more channel writes this run: the day's quota is spent or the sign-in may not write."""


def enabled(env: dict | None = None, path: Path | None = None) -> set[str]:
    """The jobs switched on: STUDIO_CHANNEL_JOBS when set, else the CHANNEL_JOBS file; none by default."""
    env = os.environ if env is None else env
    raw = env.get("STUDIO_CHANNEL_JOBS")
    if raw is None:
        path = path or JOBS_FILE
        raw = "\n".join(l.split("#")[0] for l in path.read_text(encoding="utf-8").splitlines()) if path.exists() else ""
    return {w for w in re.split(r"[\s,]+", raw.lower()) if w in JOBS}


def reasons(exc: HttpError) -> set[str]:
    """The error reasons YouTube gives ("quotaExceeded", "insufficientPermissions", ...)."""
    try:
        error = json.loads(exc.content.decode() if isinstance(exc.content, bytes) else exc.content)["error"]
    except (ValueError, KeyError, TypeError, AttributeError):
        return set()
    found = {e.get("reason") for e in error.get("errors") or []}
    found |= {d.get("reason") for d in error.get("details") or [] if isinstance(d, dict)}
    return {r for r in found if r}


QUOTA = {"quotaExceeded", "dailyLimitExceeded"}
SCOPE = {"insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"}
NO_SCOPE = ("the YouTube sign-in has no youtube or youtube.force-ssl scope; the owner must re-consent the token "
            "with it")


def _next_quota_day(at: datetime) -> str:
    local = at.astimezone(QUOTA_DAY)
    midnight = datetime.combine(local.date() + timedelta(days=1), datetime.min.time(), QUOTA_DAY)
    return midnight.astimezone(timezone.utc).isoformat(timespec="seconds")


class Desk:
    """The jobs' shared state for one run: the API, state/channel.json and the quota spent."""

    def __init__(self, api, at: datetime | None = None):
        self.api, self.at = api, at or datetime.now(timezone.utc)
        self.state = ledger.load("channel", {})
        day = self.at.astimezone(QUOTA_DAY).date().isoformat()
        if self.state.get("day") != day:
            self.state["day"], self.state["units"] = day, 0
        self.run_units = 0

    def save(self) -> None:
        ledger.save("channel", self.state)

    def blocked(self) -> str | None:
        until = self.state.get("quota_until")
        if until and self.at < datetime.fromisoformat(until):
            return f"YouTube quota spent until {until}"
        return None

    def can(self, units: int) -> bool:
        return self.run_units + units <= RUN_UNITS and self.state["units"] + units <= DAY_UNITS

    def call(self, request, units: int):
        """Execute one request, counting its units; quotaExceeded and a missing scope raise Stop."""
        if not self.can(units):
            raise Stop("unit cap reached")
        self.run_units += units
        self.state["units"] += units
        try:
            return request.execute()
        except HttpError as exc:
            why = reasons(exc)
            if exc.resp.status == 403 and why & QUOTA:
                self.state["quota_until"] = _next_quota_day(self.at)
                self.save()
                raise Stop(f"quotaExceeded, paused until {self.state['quota_until']}") from exc
            if exc.resp.status == 403 and why & SCOPE:
                raise Stop(NO_SCOPE + " (HTTP 403)") from exc
            if exc.resp.status == 401:
                raise Stop("YouTube refused the sign-in (HTTP 401)") from exc
            raise

    def failed(self, key: str) -> bool:
        return (self.state.get("failed") or {}).get(key, {}).get("count", 0) >= MAX_FAILURES

    def fail(self, key: str, exc: Exception) -> None:
        rows = self.state.setdefault("failed", {})
        row = rows.get(key, {"count": 0})
        rows[key] = {"count": row["count"] + 1, "reason": f"{type(exc).__name__}: {exc}"[:200],
                     "at": self.at.isoformat(timespec="seconds")}
        self.save()


# --- setup: About, playlists, sections -------------------------------------------------------------------------


def _about_hash() -> str:
    return hashlib.sha256(json.dumps([ABOUT, KEYWORDS, LANGUAGE]).encode()).hexdigest()[:16]


def keywords_text(words: list[str]) -> str:
    """brandingSettings.channel.keywords: space-separated, a phrase in double quotes."""
    return " ".join(f'"{w}"' if " " in w else w for w in words)


def about(desk: Desk) -> str | None:
    """Write the About text, keywords and default language once (read-modify-write of the whole brandingSettings:
    YouTube clears what an update leaves out, and the channel title is required)."""
    if (desk.state.get("about") or {}).get("hash") == _about_hash() or desk.failed("about"):
        return None
    items = desk.call(desk.api.channels().list(part="brandingSettings", id=youtube.CHANNEL_ID), READ).get("items", [])
    if len(items) != 1 or items[0].get("id") != youtube.CHANNEL_ID:
        raise RuntimeError("channels.list did not return this channel: refusing to write its About")
    branding = items[0].get("brandingSettings") or {}
    current = branding.get("channel") or {}
    if not current.get("title"):
        raise RuntimeError("brandingSettings.channel has no title to send back")
    want = {"description": ABOUT, "keywords": keywords_text(KEYWORDS), "defaultLanguage": LANGUAGE}
    if any(current.get(k) != v for k, v in want.items()):
        body = {"id": youtube.CHANNEL_ID, "brandingSettings": {**branding, "channel": {**current, **want}}}
        desk.call(desk.api.channels().update(part="brandingSettings", body=body), WRITE)
        back = desk.call(desk.api.channels().list(part="brandingSettings", id=youtube.CHANNEL_ID), READ)
        got = ((back.get("items") or [{}])[0].get("brandingSettings") or {}).get("channel") or {}
        if (got.get("description") or "").strip() != ABOUT.strip():
            desk.fail("about", RuntimeError("the About did not read back"))
            return "About written but did not read back"
        note = "About, keywords and language written"
    else:
        note = "About already current"
    desk.state["about"] = {"hash": _about_hash(), "at": desk.at.isoformat(timespec="seconds")}
    desk.save()
    return note


def _gone() -> set[str]:
    """Video ids never to file: retracted (private by the owner's review) and retired (deleted) uploads."""
    return set(youtube.RETRACTED) | {r.get("video_id") for r in ledger.load("retired", [])}


def members(at: datetime) -> dict[str, list[str]]:
    """{playlist key: video ids in publish order} from the ledger: public uploads, and scheduled ones once out."""
    rows = sorted(ledger.published(), key=lambda r: r.get("published_at") or "")
    gone = _gone()

    def live(r: dict) -> bool:
        if not r.get("video_id") or r["video_id"] in gone:
            return False
        if r.get("privacy") == "scheduled":
            when = r.get("publish_at") or r.get("published_at")
            return bool(when) and datetime.fromisoformat(when.replace("Z", "+00:00")) <= at
        return r.get("privacy", "public") == "public"

    out = {k: [r["video_id"] for r in rows if live(r) and p["match"](r)] for k, p in PLAYLISTS.items()}
    by_id = {r["id"]: r for r in rows if live(r)}
    for k, s in SERIES.items():
        out[k] = [by_id[p]["video_id"] for p in s["parts"] if p in by_id]
    return out


def _spec(key: str) -> dict:
    return PLAYLISTS.get(key) or SERIES[key]


def _playlist(desk: Desk, key: str, mine: list[dict] | None) -> tuple[str | None, list[dict] | None]:
    """This key's playlist id, made when neither the ledger nor the channel (by title, so a lost state save never
    makes a second one) has it."""
    known = (desk.state.get("playlists") or {}).get(key)
    if known:
        return known, mine
    spec = _spec(key)
    if mine is None:
        mine = desk.call(desk.api.playlists().list(part="snippet", mine=True, maxResults=50), READ).get("items", [])
    hit = next((p for p in mine if (p.get("snippet") or {}).get("title") == spec["title"]), None)
    if hit is None:
        body = {"snippet": {"title": spec["title"], "description": spec["description"], "defaultLanguage": LANGUAGE},
                "status": {"privacyStatus": "public"}}
        hit = desk.call(desk.api.playlists().insert(part="snippet,status", body=body), WRITE)
    desk.state.setdefault("playlists", {})[key] = hit["id"]
    desk.save()
    return hit["id"], mine


def _items(desk: Desk, playlist_id: str) -> set[str]:
    ids, token = set(), None
    for _ in range(UPLOAD_PAGES):
        res = desk.call(desk.api.playlistItems().list(part="contentDetails", playlistId=playlist_id, maxResults=50,
                                                      **({"pageToken": token} if token else {})), READ)
        ids |= {r["contentDetails"]["videoId"] for r in res.get("items", [])}
        token = res.get("nextPageToken")
        if not token:
            break
    return ids


def playlists(desk: Desk) -> dict:
    """File each published video into its playlists, once: counts of playlists made and videos added."""
    made = added = 0
    filed = desk.state.setdefault("filed", {})
    mine = None
    for key, videos in members(desk.at).items():
        todo = [v for v in videos if v not in filed.get(key, []) and not desk.failed(f"file:{key}:{v}")]
        if not todo or desk.failed(f"playlist:{key}"):
            continue
        had = bool((desk.state.get("playlists") or {}).get(key))
        try:
            pid, mine = _playlist(desk, key, mine)
        except HttpError as exc:
            desk.fail(f"playlist:{key}", exc)
            continue
        made += not had
        # YouTube's own list first: a lost state save never adds a video twice.
        present = _items(desk, pid)
        for vid in todo:
            if vid not in present:
                if not desk.can(WRITE):
                    raise Stop("unit cap reached")
                body = {"snippet": {"playlistId": pid, "resourceId": {"kind": "youtube#video", "videoId": vid}}}
                try:
                    desk.call(desk.api.playlistItems().insert(part="snippet", body=body), WRITE)
                except HttpError as exc:
                    desk.fail(f"file:{key}:{vid}", exc)
                    continue
                added += 1
            filed.setdefault(key, []).append(vid)
            desk.save()
    return {"made": made, "added": added}


def sections(desk: Desk) -> int:
    """A Home-tab shelf per playlist that has videos, once (channelSections.insert, singlePlaylist)."""
    done = desk.state.setdefault("sections", {})
    want = [k for k, pid in (desk.state.get("playlists") or {}).items()
            if k not in done and (desk.state.get("filed") or {}).get(k) and not desk.failed(f"section:{k}")]
    if not want:
        return 0
    have = desk.call(desk.api.channelSections().list(part="contentDetails", mine=True), READ).get("items", [])
    shown = {p for s in have for p in (s.get("contentDetails") or {}).get("playlists") or []}
    made = 0
    for key in want:
        pid = desk.state["playlists"][key]
        if pid not in shown:
            body = {"snippet": {"type": "singlePlaylist"}, "contentDetails": {"playlists": [pid]}}
            try:
                desk.call(desk.api.channelSections().insert(part="snippet,contentDetails", body=body), WRITE)
            except HttpError as exc:
                desk.fail(f"section:{key}", exc)
                continue
            made += 1
        done[key] = pid
        desk.save()
    return made


# --- untag: the old MARKER tag -----------------------------------------------------------------------------------


def uploads(desk: Desk, channel: dict) -> list[dict]:
    """Every upload on the channel (snippet, status), through the uploads playlist."""
    pid = channel["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, token = [], None
    for _ in range(UPLOAD_PAGES):
        res = desk.call(desk.api.playlistItems().list(part="contentDetails", playlistId=pid, maxResults=50,
                                                      **({"pageToken": token} if token else {})), READ)
        ids += [r["contentDetails"]["videoId"] for r in res.get("items", [])]
        token = res.get("nextPageToken")
        if not token:
            break
    out = []
    for i in range(0, len(ids), 50):
        out += desk.call(desk.api.videos().list(part="snippet,status", id=",".join(ids[i:i + 50])), READ).get(
            "items", [])
    return out


def remember(videos: list[dict]) -> int:
    """Make sure the ledger knows each story's video before any tag goes: a published row without a video id takes
    the one its old MARKER tag names, else the upload no ledger row owns that has its exact title; a tagged video the
    published rows do not name is kept in state/markers.json (youtube.find reads it). How many it added."""
    rows = ledger.published()
    owned = {r.get("video_id") for r in rows} | {u.get("video_id") for u in ledger.uploads().values()}
    owned |= set(ledger.markers().values())
    by_story = {r["id"]: r for r in rows}
    added = changed = 0
    for v in videos:
        if v["id"] in youtube.RETRACTED:  # private by the owner's review: never a story's live upload again
            continue
        for t in v["snippet"].get("tags") or []:
            if not t.startswith(youtube.MARKER):
                continue
            story = t[len(youtube.MARKER):]
            row = by_story.get(story)
            if row is not None and not row.get("video_id"):
                row["video_id"], changed = v["id"], changed + 1
            elif row is None and story not in ledger.uploads() and v["id"] not in owned:
                ledger.remember_marker(story, v["id"])
                owned.add(v["id"])
                added += 1
    owned |= {r.get("video_id") for r in rows}
    for row in rows:
        if row.get("video_id"):
            continue
        hits = [v for v in videos if v["id"] not in owned and v["snippet"].get("title") == row.get("title")]
        if len(hits) == 1:
            row["video_id"], changed = hits[0]["id"], changed + 1
            owned.add(hits[0]["id"])
    if changed:
        ledger.save("published", rows)
    return added + changed


def untag(desk: Desk, channel: dict, limit: int = UNTAG_PER_RUN) -> dict:
    """Take the MARKER tag off up to `limit` uploads (read-modify-write of the snippet: title, description, category,
    languages and topic tags as YouTube returned them), after remember(); then read them back."""
    videos = uploads(desk, channel)
    remembered = remember(videos)
    marked = [v for v in videos if any(t.startswith(youtube.MARKER) for t in v["snippet"].get("tags") or [])
              and v["id"] not in youtube.RETRACTED]
    todo = [v for v in marked if not desk.failed(f"untag:{v['id']}")]
    done = []
    for v in todo[:limit]:
        snippet = v["snippet"]
        if snippet.get("channelId") != youtube.CHANNEL_ID:
            raise RuntimeError(f"{v['id']} is on another channel")
        if not desk.can(WRITE + READ):
            break
        body = {"id": v["id"], "snippet": {
            "title": snippet["title"], "description": snippet.get("description", ""),
            "categoryId": snippet.get("categoryId") or youtube.CATEGORY,
            "tags": [t for t in snippet.get("tags") or [] if not t.startswith(youtube.MARKER)]}}
        for key in ("defaultLanguage", "defaultAudioLanguage"):
            if snippet.get(key):
                body["snippet"][key] = snippet[key]
        try:
            desk.call(desk.api.videos().update(part="snippet", body=body), WRITE)
        except HttpError as exc:
            desk.fail(f"untag:{v['id']}", exc)
            continue
        done.append(v["id"])
    if done:
        back = desk.call(desk.api.videos().list(part="snippet", id=",".join(done)), READ).get("items", [])
        still = {b["id"] for b in back if any(t.startswith(youtube.MARKER) for t in b["snippet"].get("tags") or [])}
        for vid in still:
            desk.fail(f"untag:{vid}", RuntimeError("the marker tag was still there on read-back"))
        done = [v for v in done if v not in still]
        untagged = desk.state.setdefault("untagged", {})
        for vid in done:
            untagged[vid] = desk.at.isoformat(timespec="seconds")
        desk.save()
    skipped = [v["id"] for v in marked if desk.failed(f"untag:{v['id']}")]
    return {"done": len(done), "left": len(marked) - len(done) - len(skipped), "given_up": skipped,
            "remembered": remembered}


# --- the run's entry point ---------------------------------------------------------------------------------------


def run(api_factory=None, at: datetime | None = None, jobs: set[str] | None = None) -> str | None:
    """Run the switched-on jobs within the unit caps: one health line, or None when every job is off. Never raises
    for a YouTube refusal (cli.run still wraps it)."""
    jobs = enabled() if jobs is None else jobs
    if not jobs:
        return None
    listed = youtube.scopes()
    if listed is not None and not listed & youtube.WRITE_SCOPES:
        return "channel jobs: " + NO_SCOPE
    api = (api_factory or youtube.client)()
    desk = Desk(api, at)
    if why := desk.blocked():
        return f"channel jobs: {why}"
    parts, stop = [], None
    try:
        channel = desk.call(api.channels().list(part="snippet,contentDetails", mine=True), READ).get("items", [])
        if len(channel) != 1 or channel[0]["id"] != youtube.CHANNEL_ID:
            raise RuntimeError("signed in to the wrong channel: refusing every write")
        channel = channel[0]
        if "setup" in jobs:
            try:
                if note := about(desk):
                    parts.append(note)
            except HttpError as exc:  # refused twice, the About is left for a person (Studio)
                desk.fail("about", exc)
                parts.append(f"About refused (HTTP {exc.resp.status} {','.join(sorted(reasons(exc)))})")
            got = playlists(desk)
            if got["made"] or got["added"]:
                parts.append(f"playlists {got['made']} made, {got['added']} videos added")
            if made := sections(desk):
                parts.append(f"{made} Home sections")
        if "untag" in jobs and desk.state.get("untag_finished"):
            given_up = sorted(k[6:] for k, r in (desk.state.get("failed") or {}).items()
                              if k.startswith("untag:") and r.get("count", 0) >= MAX_FAILURES)
            parts.append(f"untag finished {desk.state['untag_finished']}"
                         + (f", left on {','.join(given_up)} (fix in Studio)" if given_up else ""))
        elif "untag" in jobs:
            got = untag(desk, channel)
            if not (got["done"] or got["left"]):  # nothing left but what YouTube refused twice: no more reads
                desk.state["untag_finished"] = desk.at.isoformat(timespec="seconds")
            parts.append(f"untag {got['done']} done, {got['left']} left"
                         + (f", gave up on {','.join(got['given_up'])}" if got["given_up"] else "")
                         + (f", {got['remembered']} story ids kept first" if got["remembered"] else ""))
    except Stop as exc:
        stop = str(exc)
    finally:
        desk.save()
    if stop:
        parts.append(f"stopped: {stop}")
    return f"channel jobs ({'+'.join(sorted(jobs))}): " + ("; ".join(parts) or "nothing to do") + \
        f"; {desk.state['units']} units today"
