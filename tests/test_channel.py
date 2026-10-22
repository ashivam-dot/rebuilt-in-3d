import json
from datetime import datetime, timezone

import httplib2
import pytest
from googleapiclient.errors import HttpError

from studio import channel, ledger, youtube

AT = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)
UPLOADS = {"contentDetails": {"relatedPlaylists": {"uploads": "UU"}}}


def refusal(status: int, reason: str) -> HttpError:
    content = json.dumps({"error": {"code": status, "errors": [{"reason": reason}]}}).encode()
    return HttpError(httplib2.Response({"status": status}), content)


class Call:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class FakeYouTube:
    """The channel as YouTube holds it, with every write logged; `refuse` maps an operation (or "op:id") to the
    HttpError it raises."""

    def __init__(self, videos=(), branding=None):
        self.videos_ = {v["id"]: v for v in videos}
        self.branding = branding or {"channel": {"title": "Orbitwire", "description": "old", "keywords": "old",
                                                 "unsubscribedTrailer": "TRAILER"},
                                     "watch": {"textColor": "#fff"}}
        self.lists, self.items, self.sections = [], {}, []
        self.writes, self.refuse = [], {}

    def _do(self, op, key, fn):
        def run():
            for k in (f"{op}:{key}", op):
                if k in self.refuse:
                    raise self.refuse[k]
            return fn()
        return Call(run)

    # resources
    def channels(self):
        return self._Res(self, "channels")

    def playlists(self):
        return self._Res(self, "playlists")

    def playlistItems(self):
        return self._Res(self, "playlistItems")

    def channelSections(self):
        return self._Res(self, "channelSections")

    def videos(self):
        return self._Res(self, "videos")

    class _Res:
        def __init__(self, yt, name):
            self.yt, self.name = yt, name

        def list(self, **k):
            yt = self.yt
            if self.name == "channels":
                if k.get("mine"):
                    return yt._do("channels.list", "", lambda: {"items": [{"id": youtube.CHANNEL_ID, **UPLOADS}]})
                return yt._do("channels.list", "", lambda: {"items": [{"id": youtube.CHANNEL_ID,
                                                                       "brandingSettings": json.loads(
                                                                           json.dumps(yt.branding))}]})
            if self.name == "playlists":
                return yt._do("playlists.list", "", lambda: {"items": [
                    {"id": pid, "snippet": {"title": t}} for pid, t in yt.lists]})
            if self.name == "playlistItems":
                pid = k["playlistId"]
                ids = list(yt.videos_) if pid == "UU" else yt.items.get(pid, [])
                return yt._do("playlistItems.list", pid, lambda: {"items": [
                    {"contentDetails": {"videoId": v}} for v in ids]})
            if self.name == "channelSections":
                return yt._do("channelSections.list", "", lambda: {"items": [
                    {"contentDetails": {"playlists": [p]}} for p in yt.sections]})
            ids = k["id"].split(",")
            return yt._do("videos.list", "", lambda: {"items": [json.loads(json.dumps(yt.videos_[v]))
                                                                for v in ids if v in yt.videos_]})

        def insert(self, part, body):
            yt = self.yt

            def go():
                yt.writes.append((self.name + ".insert", body))
                if self.name == "playlists":
                    pid = f"PL{len(yt.lists)}"
                    yt.lists.append((pid, body["snippet"]["title"]))
                    return {"id": pid}
                if self.name == "playlistItems":
                    s = body["snippet"]
                    yt.items.setdefault(s["playlistId"], []).append(s["resourceId"]["videoId"])
                    return {}
                yt.sections.append(body["contentDetails"]["playlists"][0])
                return {}
            key = body["snippet"].get("resourceId", {}).get("videoId", "")
            return yt._do(self.name + ".insert", key, go)

        def update(self, part, body):
            yt = self.yt

            def go():
                yt.writes.append((self.name + ".update", body))
                if self.name == "channels":
                    yt.branding = body["brandingSettings"]
                else:
                    yt.videos_[body["id"]]["snippet"] = {**yt.videos_[body["id"]]["snippet"], **body["snippet"]}
                return {}
            return yt._do(self.name + ".update", body.get("id", ""), go)


def video(vid, tags=(), title=None, desc="d", **extra):
    return {"id": vid, "snippet": {"channelId": youtube.CHANNEL_ID, "title": title or f"T {vid}", "description": desc,
                                   "categoryId": "27", "defaultLanguage": "en", "defaultAudioLanguage": "en",
                                   "tags": list(tags), **extra}, "status": {"privacyStatus": "public"}}


def publish(story, vid, kind="incident", category=None, title="", privacy="public", publish_at=None, at="01"):
    ledger.record_publish({"id": story, "video_id": vid, "kind": kind, "category": category, "title": title,
                           "privacy": privacy, "publish_at": publish_at,
                           "published_at": f"2026-10-{at}T00:00:00+00:00"})


@pytest.fixture(autouse=True)
def write_scope(monkeypatch):
    monkeypatch.setattr(youtube, "scopes", lambda: {"https://www.googleapis.com/auth/youtube.force-ssl"})


def run(yt, jobs=("setup",), at=AT):
    return channel.run(lambda: yt, at=at, jobs=set(jobs))


def test_jobs_are_off_unless_switched_on(tmp_path):
    assert channel.enabled({}, tmp_path / "CHANNEL_JOBS") == set()
    (tmp_path / "CHANNEL_JOBS").write_text("# switches\nsetup\n# untag\nbogus\n")
    assert channel.enabled({}, tmp_path / "CHANNEL_JOBS") == {"setup"}
    assert channel.enabled({"STUDIO_CHANNEL_JOBS": "setup, untag"}, tmp_path / "none") == {"setup", "untag"}
    assert not (channel.ROOT / "CHANNEL_JOBS").exists()  # shipped off
    assert channel.run(lambda: pytest.fail("no job should touch YouTube"), jobs=set()) is None


def test_about_is_a_read_modify_write_of_the_whole_branding_once():
    yt = FakeYouTube()
    line = run(yt)
    sent = [b for op, b in yt.writes if op == "channels.update"]
    assert len(sent) == 1 and "About, keywords and language written" in line
    ch = sent[0]["brandingSettings"]["channel"]
    assert ch["title"] == "Orbitwire" and ch["unsubscribedTrailer"] == "TRAILER"  # kept
    assert ch["description"] == channel.ABOUT and ch["defaultLanguage"] == "en" and '"world news"' in ch["keywords"]
    assert sent[0]["brandingSettings"]["watch"] == {"textColor": "#fff"}
    assert len(channel.ABOUT) <= 1000 and len(ch["keywords"]) <= 500
    for claim in ("AI voice", "two independent outlets", "USGS", "Corrections", "not real footage"):
        assert claim in channel.ABOUT
    run(yt)
    assert len([op for op, _ in yt.writes if op == "channels.update"]) == 1  # done once


def test_an_about_that_does_not_read_back_is_tried_twice_then_left(monkeypatch):
    yt = FakeYouTube()
    real = FakeYouTube._Res.update

    def ignored(self, part, body):  # YouTube accepts the write but keeps the old text
        return Call(lambda: yt.writes.append((self.name + ".update", body)) or {})

    monkeypatch.setattr(FakeYouTube._Res, "update", ignored)
    assert "did not read back" in run(yt) and "did not read back" in run(yt)
    run(yt)
    assert sum(op == "channels.update" for op, _ in yt.writes) == 2
    monkeypatch.setattr(FakeYouTube._Res, "update", real)


def test_playlists_are_made_once_and_filed_from_the_ledger():
    publish("eq-1", "Q1", kind="quake", at="01")
    publish("wk-storm", "S1", category="cyclone", title="Hurricane Rachel's Landfall", at="02")
    publish("wk-fire", "F1", category="disaster", title="Poland School Stabbings", at="03")
    publish("wk-dead", "D1", kind="death", at="04")
    publish("wk-Q139857349-p1", "P1", at="05")
    publish("wk-Q140615137-p2", "P2", privacy="scheduled", publish_at="2026-10-30T00:00:00Z", at="06")
    publish("eq-x", "B3TumXzN63I", kind="quake", at="07")  # retracted: never filed
    yt = FakeYouTube()
    line = run(yt)
    titles = dict((t, p) for p, t in yt.lists)
    assert set(titles) == {"Earthquakes in 3D", "Storms and Natural Disasters", "Lives Remembered",
                           "The Cockroach Janta Party, in Parts"}
    assert yt.items[titles["Earthquakes in 3D"]] == ["Q1"]
    assert yt.items[titles["Storms and Natural Disasters"]] == ["S1"]  # a stabbing is not a disaster
    assert yt.items[titles["The Cockroach Janta Party, in Parts"]] == ["P1"]  # part 2 is not out yet
    assert "playlists 4 made, 4 videos added" in line and "unit cap reached" in line  # 458 units: sections next run
    assert "4 Home sections" in run(yt) and len(yt.sections) == 4
    writes = len(yt.writes)
    run(yt)
    assert len(yt.writes) == writes  # nothing twice
    # Part 2 goes out: only it is added. A lost state save never makes a second playlist or item.
    ledger.save("channel", {})
    run(yt, at=datetime(2026, 10, 31, tzinfo=timezone.utc))
    assert len(yt.lists) == 4 and yt.items[titles["The Cockroach Janta Party, in Parts"]] == ["P1", "P2"]
    assert sum(op == "playlistItems.insert" for op, _ in yt.writes) == 5


def test_units_are_capped_per_run_and_per_day(monkeypatch):
    for i in range(30):
        publish(f"eq-{i}", f"V{i}", kind="quake", at=f"{i % 28 + 1:02d}")
    yt = FakeYouTube()
    line = run(yt)
    state = ledger.load("channel", {})
    assert state["units"] <= channel.RUN_UNITS and "unit cap reached" in line
    for _ in range(5):
        run(yt)
    assert ledger.load("channel", {})["units"] <= channel.DAY_UNITS
    filed = len(yt.items["PL0"])
    assert filed < 30
    # The next Pacific day carries on where it stopped.
    run(yt, at=datetime(2026, 10, 23, 12, tzinfo=timezone.utc))
    assert len(yt.items["PL0"]) > filed


def test_quota_exceeded_pauses_until_pacific_midnight_and_a_missing_scope_stops_the_run():
    publish("eq-1", "Q1", kind="quake")
    yt = FakeYouTube()
    yt.refuse["channels.update"] = refusal(403, "quotaExceeded")
    line = run(yt)
    assert "quotaExceeded" in line
    until = ledger.load("channel", {})["quota_until"]
    assert until == "2026-10-23T07:00:00+00:00"
    assert "quota spent until" in run(yt) and not yt.writes
    yt2 = FakeYouTube()
    ledger.save("channel", {})
    yt2.refuse["channels.update"] = refusal(403, "insufficientPermissions")
    line = run(yt2)
    assert "force-ssl" in line and "quota_until" not in ledger.load("channel", {})


def test_a_token_without_a_write_scope_never_calls_youtube(monkeypatch):
    monkeypatch.setattr(youtube, "scopes", lambda: {"https://www.googleapis.com/auth/youtube.upload"})
    assert "force-ssl" in channel.run(lambda: pytest.fail("called YouTube"), at=AT, jobs={"setup"})


def test_untag_keeps_story_ids_first_strips_only_the_marker_and_reads_back():
    publish("wk-Q1", "A")
    publish("wk-Q2", None, title="Lost Row")  # a published row whose video id was never kept
    ledger.save("published", [dict(r, video_id=None) if r["id"] == "wk-Q2" else r for r in ledger.published()])
    yt = FakeYouTube([video("A", ["quake", youtube.MARKER + "wk-Q1", "Orbitwire"]),
                      video("B", [youtube.MARKER + "wk-Q9"]),  # tagged, no published row
                      video("C", title="Lost Row"),
                      video("B3TumXzN63I", [youtube.MARKER + "eq-x"]),  # retracted: left alone
                      video("N", ["Orbitwire"])])
    line = run(yt, jobs={"untag"})
    # First run: the story ids are kept and no tag comes off (that waits for this run's state to be saved).
    assert "untag 0 done, 2 left, 2 story ids kept first" in line
    assert not any(op == "videos.update" for op, _ in yt.writes)
    assert ledger.markers() == {"wk-Q9": "B"}
    assert {r["id"]: r["video_id"] for r in ledger.published()} == {"wk-Q1": "A", "wk-Q2": "C"}
    line = run(yt, jobs={"untag"})
    assert "untag 2 done, 0 left" in line and "kept first" not in line
    a = yt.videos_["A"]["snippet"]
    assert a["tags"] == ["quake", "Orbitwire"] and a["title"] == "T A" and a["description"] == "d"
    sent = next(b for op, b in yt.writes if op == "videos.update" and b["id"] == "A")["snippet"]
    assert {"title", "description", "categoryId", "tags", "defaultLanguage", "defaultAudioLanguage"} <= set(sent)
    # find() still knows wk-Q9's upload with its tag gone.
    api = type("Api", (), {"videos": lambda self: yt.videos()})()
    assert youtube.find(api, UPLOADS, "wk-Q9")["id"] == "B"
    assert "untag 0 done, 0 left" in run(yt, jobs={"untag"})
    reads = len(yt.writes), ledger.load("channel", {})["units"]
    assert "untag finished" in run(yt, jobs={"untag"})
    assert (len(yt.writes), ledger.load("channel", {})["units"]) == (reads[0], reads[1] + 1)  # the identity read only


def test_a_video_youtube_keeps_refusing_is_given_up_after_two_tries():
    yt = FakeYouTube([video("BAD", [youtube.MARKER + "wk-Q1"]), video("OK", [youtube.MARKER + "wk-Q2"])])
    yt.refuse["videos.update:BAD"] = refusal(400, "invalidTags")
    assert "untag 0 done, 2 left, 2 story ids kept first" in run(yt, jobs={"untag"})
    assert "untag 1 done, 1 left" in run(yt, jobs={"untag"})
    assert "gave up on BAD" in run(yt, jobs={"untag"})
    tries = sum(op == "videos.update" for op, _ in yt.writes)
    run(yt, jobs={"untag"})
    assert ledger.load("channel", {})["failed"]["untag:BAD"]["count"] == 2
    assert "untag finished" in run(yt, jobs={"untag"}) and "left on BAD (fix in Studio)" in run(yt, jobs={"untag"})
    assert sum(op == "videos.update" for op, _ in yt.writes) == tries  # never tried a third time


def test_a_story_id_kept_this_run_keeps_its_tag_until_a_later_run(monkeypatch):
    """A lost state push after remember() must never leave a story with no ledger row, no marker and no tag."""
    yt = FakeYouTube([video("V9", [youtube.MARKER + "wk-Q9"])])
    assert "untag 0 done, 1 left, 1 story ids kept first" in run(yt, jobs={"untag"})
    assert ledger.markers() == {"wk-Q9": "V9"}
    assert not any(op == "videos.update" for op, _ in yt.writes)
    # The push is lost: markers.json is gone, but the tag is still on YouTube, so find() and remember() still see it.
    ledger.save("markers", {})
    assert youtube.find(yt, UPLOADS, "wk-Q9")["id"] == "V9"
    assert "untag 0 done, 1 left, 1 story ids kept first" in run(yt, jobs={"untag"})
    # Saved this time: the next run starts with the mapping and takes the tag off.
    assert "untag 1 done, 0 left" in run(yt, jobs={"untag"})
    assert yt.videos_["V9"]["snippet"]["tags"] == [] and ledger.markers() == {"wk-Q9": "V9"}
    assert youtube.find(yt, UPLOADS, "wk-Q9")["id"] == "V9"


def test_two_uploads_of_one_unpublished_story_do_not_hold_the_untag_forever():
    """The b3 re-check (2026-10-22): the second upload's story id is already kept, so it is no new mapping."""
    yt = FakeYouTube([video("V1", [youtube.MARKER + "wk-Q9"]), video("V2", [youtube.MARKER + "wk-Q9"])])
    assert "untag 0 done, 2 left, 1 story ids kept first" in run(yt, jobs={"untag"})
    assert ledger.markers() == {"wk-Q9": "V1"}
    assert "untag 2 done, 0 left" in run(yt, jobs={"untag"})


def test_a_stale_read_back_is_read_again_and_a_5xx_is_no_strike(monkeypatch):
    monkeypatch.setattr(channel, "READBACK_WAIT", 0)
    yt = FakeYouTube([video("A", [youtube.MARKER + "wk-Q1"]), video("B", [youtube.MARKER + "wk-Q2"])])
    run(yt, jobs={"untag"})  # keeps the story ids
    real = FakeYouTube._Res.list
    lists = []

    def stale_once(self, **k):  # the first videos.list after the update still shows the old tags
        if self.name == "videos" and "status" not in k.get("part", "") and not lists:
            lists.append(1)
            old = {"items": [video(v, [youtube.MARKER + "x"]) for v in k["id"].split(",")]}
            return Call(lambda: old)
        return real(self, **k)

    monkeypatch.setattr(FakeYouTube._Res, "list", stale_once)
    yt.refuse["videos.update:B"] = refusal(503, "backendError")
    line = run(yt, jobs={"untag"})
    assert "untag 1 done, 1 left" in line and "gave up" not in line
    state = ledger.load("channel", {})
    assert "untag:A" not in state.get("failed", {}) and "untag:B" not in state.get("failed", {})


def test_a_playlist_deleted_in_studio_is_made_again_not_retried_forever():
    publish("eq-1", "Q1", kind="quake", at="01")
    yt = FakeYouTube()
    run(yt)
    pid = ledger.load("channel", {})["playlists"]["quakes"]
    assert yt.items[pid] == ["Q1"]
    publish("eq-2", "Q2", kind="quake", at="02")
    yt.lists[:] = [("GONE", "deleted in Studio")]  # its title is gone; a new playlist gets a new id
    yt.refuse[f"playlistItems.list:{pid}"] = refusal(404, "playlistNotFound")
    run(yt)
    state = ledger.load("channel", {})
    assert "quakes" not in state["playlists"] and "quakes" not in state["filed"]
    line = run(yt)
    new = ledger.load("channel", {})["playlists"]["quakes"]
    assert new != pid and yt.items[new] == ["Q1", "Q2"] and "1 made" in line


def test_an_about_read_back_with_other_line_endings_still_counts(monkeypatch):
    yt = FakeYouTube()
    real = FakeYouTube._Res.update

    def crlf(self, part, body):
        call = real(self, part, body)

        def go():
            out = call.execute()
            if self.name == "channels":
                ch = yt.branding["channel"]
                ch["description"] = ch["description"].replace("\n", "\r\n") + " "
            return out
        return Call(go)

    monkeypatch.setattr(FakeYouTube._Res, "update", crlf)
    assert "About, keywords and language written" in run(yt)
    assert sum(op == "channels.update" for op, _ in yt.writes) == 1


def test_a_failing_job_never_stops_the_run(monkeypatch):
    from studio import cli, plan

    monkeypatch.setattr(ledger, "set_identity", lambda: None)
    monkeypatch.setattr(cli.learn, "refresh", lambda: None)
    monkeypatch.setattr(youtube, "retract", lambda api: [])
    monkeypatch.setattr(youtube, "client", lambda *a: object())
    monkeypatch.setattr(channel, "run", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(plan, "watch", lambda: {"candidates": [], "quakes": [], "trending": [], "hazards": []})
    monkeypatch.setattr(plan, "lineup", lambda c: ([], []))
    health = cli.run()
    assert health["ok"] and any(s.startswith("channel jobs: RuntimeError: boom") for s in health["steps"])
