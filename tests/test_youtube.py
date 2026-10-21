from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from studio import youtube
from studio.spec import Short

FIXTURE = Path(__file__).parent / "fixtures" / "eq-us6000u0xi.json"


def test_description_hashtags_are_clean():
    short = replace(Short.load(FIXTURE), hashtags=["earthquake", "Papua New Guinea", "science"])
    last = youtube.description(short).splitlines()[-1]
    assert last == "#earthquake #PapuaNewGuinea #science"


def test_description_carries_sources_and_disclosure():
    text = youtube.description(Short.load(FIXTURE))
    assert "https://earthquake.usgs.gov/earthquakes/eventpage/us6000u0xi" in text
    assert "not real footage" in text and len(text) <= 4900


def test_every_description_says_how_the_short_is_made_once():
    quake = Short.load(FIXTURE)
    story = replace(quake, scene={**quake.scene, "template": "story", "photos": []})
    for short, line in ((quake, youtube.EDITORIAL_QUAKE), (story, youtube.EDITORIAL)):
        text = youtube.description(short)
        assert text.count("How it is made:") == 1 and line in text.splitlines()
    # It claims mechanical checks, never a person reviewing each Short.
    assert not any(w in youtube.EDITORIAL + youtube.EDITORIAL_QUAKE for w in ("human", "editor", "reviewed by"))


def test_tags_carry_topics_but_no_machine_marker():
    short = Short.load(FIXTURE)
    tags = youtube.tags(replace(short, tags=[f"tag number {i}" for i in range(60)]))
    assert tags[0] == "tag number 0" and sum(len(t) + 2 for t in tags) <= 482
    assert not any(t.startswith(youtube.MARKER) or short.id in t for t in tags)
    assert youtube.tags(replace(short, tags=["earthquake", "Papua New Guinea"])) == \
        ["earthquake", "Papua New Guinea", "Orbitwire"]


class _Channel:
    """videos.list by id and the uploads playlist, for find()."""

    def __init__(self, videos: list[dict]):
        self.videos, self.asked = videos, []

    def playlistItems(self):
        rows = [{"contentDetails": {"videoId": v["id"]}} for v in self.videos]
        return type("P", (), {"list": lambda _, **k: _Call({"items": rows})})()

    def list(self, **k):
        self.asked.append(k["id"])
        ids = k["id"].split(",")
        return _Call({"items": [v for v in self.videos if v["id"] in ids]})

    def __call__(self):
        return self


def _video(vid, tags=(), channel=youtube.CHANNEL_ID):
    return {"id": vid, "snippet": {"channelId": channel, "tags": list(tags)}, "status": {"privacyStatus": "private"}}


CHANNEL = {"contentDetails": {"relatedPlaylists": {"uploads": "UU"}}}


def _api(videos):
    chan = _Channel(videos)
    return type("Api", (), {"videos": lambda self: chan, "playlistItems": lambda self: chan.playlistItems()})(), chan


def test_find_knows_an_upload_from_the_ledger_not_a_public_tag():
    from studio import ledger

    api, chan = _api([_video("OLD", [youtube.MARKER + "wk-Q1"]), _video("NEW"), _video("PUB")])
    assert youtube.find(api, CHANNEL, "wk-Q2") is None
    ledger.record_upload("wk-Q2", "NEW")
    assert youtube.find(api, CHANNEL, "wk-Q2")["id"] == "NEW"
    # Uploads from before 2026-10-22 are still known by the marker tag they carry.
    assert youtube.find(api, CHANNEL, "wk-Q1")["id"] == "OLD"
    ledger.record_publish({"id": "wk-Q3", "video_id": "PUB", "published_at": "2026-10-22T00:00:00+00:00"})
    assert youtube.find(api, CHANNEL, "wk-Q3")["id"] == "PUB"
    # Publishing clears the pending upload.
    ledger.record_publish({"id": "wk-Q2", "video_id": "NEW", "published_at": "2026-10-22T01:00:00+00:00"})
    assert "wk-Q2" not in ledger.uploads() and youtube.find(api, CHANNEL, "wk-Q2")["id"] == "NEW"


def test_find_ignores_a_ledger_video_gone_from_the_channel_and_refuses_doubles():
    from studio import ledger

    api, _ = _api([_video("ELSE", channel="UCother"), _video("A", [youtube.MARKER + "wk-Q9"]),
                   _video("B", [youtube.MARKER + "wk-Q9"])])
    ledger.record_upload("wk-Q8", "GONE")
    assert youtube.find(api, CHANNEL, "wk-Q8") is None
    ledger.record_upload("wk-Q7", "ELSE")
    assert youtube.find(api, CHANNEL, "wk-Q7") is None
    with pytest.raises(RuntimeError, match="twice"):
        youtube.find(api, CHANNEL, "wk-Q9")


class _Insert:
    def next_chunk(self, num_retries=3):
        return None, {"id": "V9"}


def test_publish_records_the_upload_before_waiting_for_youtube(tmp_path, monkeypatch):
    from studio import ledger

    class Videos(_Videos):
        def insert(self, **k):
            self.body = k["body"]
            return _Insert()

        def list(self, **k):
            assert ledger.uploads()["wk-up"]["video_id"] == "V9"  # known before processing ends
            return super().list(**k)

    videos = Videos(["public", "public"])
    monkeypatch.setattr(youtube, "client", lambda: type("Api", (), {"videos": lambda self: videos})())
    monkeypatch.setattr(youtube, "identity", lambda api: {})
    monkeypatch.setattr(youtube, "find", lambda api, channel, short_id: None)
    monkeypatch.setattr(youtube, "unrecorded", lambda api, channel, short: None)
    monkeypatch.setattr(youtube, "MediaFileUpload", lambda *a, **k: None)
    monkeypatch.setattr(youtube.time, "sleep", lambda s: None)
    short = replace(Short.load(FIXTURE), id="wk-up")
    assert youtube.publish(short, tmp_path / "short.mp4")["video_id"] == "V9"
    assert not any(t.startswith(youtube.MARKER) for t in videos.body["snippet"]["tags"])


class _Call:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result() if callable(self.result) else self.result


class _Videos:
    def __init__(self, privacy):
        self.privacy, self.updates = list(privacy), []

    def list(self, **k):
        status = {"uploadStatus": "processed", "privacyStatus": self.privacy.pop(0)}
        return _Call({"items": [{"snippet": {"channelId": youtube.CHANNEL_ID, "title": "T"}, "status": status}]})

    def update(self, **k):
        self.updates.append(k["body"]["status"]["privacyStatus"])
        return _Call({})


def test_publish_waits_for_youtube_to_report_the_video_public(tmp_path, monkeypatch):
    videos = _Videos(["private", "private", "private", "public"])
    monkeypatch.setattr(youtube, "client", lambda: type("Api", (), {"videos": lambda self: videos})())
    monkeypatch.setattr(youtube, "identity", lambda api: {})
    monkeypatch.setattr(youtube, "find", lambda api, channel, short_id: {"id": "V1"})
    monkeypatch.setattr(youtube.time, "sleep", lambda s: None)
    result = youtube.publish(Short.load(FIXTURE), tmp_path / "short.mp4")
    assert result["privacy"] == "public" and result["video_id"] == "V1" and videos.updates == ["public"]
    videos = _Videos(["private"] * 7)
    with pytest.raises(RuntimeError, match=r"did not go public \(private\)"):
        youtube.publish(Short.load(FIXTURE), tmp_path / "short.mp4")


AT = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)
SOURCE = "https://earthquake.usgs.gov/earthquakes/eventpage/us6000u0xi"


def _upload(vid, at="2026-10-22T02:00:00Z", description=f"A quake.\n\nSources:\n{SOURCE}\n", privacy="private",
            tags=()):
    v = _video(vid, tags)
    v["snippet"] |= {"publishedAt": at, "description": description}
    v["status"]["privacyStatus"] = privacy
    return v


def test_an_upload_whose_state_save_was_lost_is_found_by_its_source_url():
    """Uploaded, then the run's state save failed: uploads.json never reached the state branch, and new uploads carry
    no marker tag. The story's source URL in the description still says the video is this story's."""
    from studio import ledger

    short = Short.load(FIXTURE)
    assert SOURCE in short.sources
    api, _ = _api([_upload("LOST")])
    assert youtube.find(api, CHANNEL, short.id) is None
    assert youtube.unrecorded(api, CHANNEL, short, at=AT)["id"] == "LOST"
    # The same lost save after it went public too.
    assert youtube.unrecorded(_api([_upload("LOST", privacy="public")])[0], CHANNEL, short, at=AT)["id"] == "LOST"
    # Not when the ledger knows the video (it is another story's), or it is old, or a marker tag claims it, or its
    # description only shares a prefix of the URL.
    for videos in ([_upload("LOST", at="2026-10-19T00:00:00Z")], [_upload("TAG", tags=[youtube.MARKER + "wk-Q1"])],
                   [_upload("NEAR", description=f"Sources:\n{SOURCE}x\n")]):
        assert youtube.unrecorded(_api(videos)[0], CHANNEL, short, at=AT) is None
    ledger.record_upload("eq-other", "LOST")
    assert youtube.unrecorded(api, CHANNEL, short, at=AT) is None


def test_publish_never_uploads_a_story_already_on_the_channel_unrecorded(tmp_path, monkeypatch):
    class Videos(_Videos):
        def insert(self, **k):
            raise AssertionError("uploaded a second copy")

    api, _ = _api([_upload("LOST", at=datetime.now(timezone.utc).isoformat())])
    monkeypatch.setattr(youtube, "client", lambda: api)
    monkeypatch.setattr(youtube, "identity", lambda a: CHANNEL)
    with pytest.raises(youtube.Unrecorded, match="LOST"):
        youtube.publish(Short.load(FIXTURE), tmp_path / "short.mp4")


def test_a_run_holds_an_unrecorded_upload_and_reports_it(monkeypatch):
    from studio import cli, ledger, plan

    cand = {"id": "eq-us6000u0xi", "kind": "quake", "fame": 9}
    short = Short.load(FIXTURE)
    monkeypatch.setattr(ledger, "set_identity", lambda: None)
    monkeypatch.setattr(cli.learn, "refresh", lambda: None)
    monkeypatch.setattr(youtube, "client", lambda *a: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(plan, "watch", lambda: {"candidates": [cand], "quakes": [cand], "trending": [], "hazards": []})
    monkeypatch.setattr(plan, "lineup", lambda c: (c, []))
    monkeypatch.setattr(cli, "prepare", lambda c: short)
    monkeypatch.setattr(cli, "make", lambda c, s: (s, {"duration": 40}))
    monkeypatch.setattr(cli.gate, "channel_mix", lambda *a: None)

    def publish(story_id):
        raise youtube.Unrecorded("LOST (uploaded 2026-10-22T02:00:00Z, private) lists this story's source")

    monkeypatch.setattr(cli, "publish", publish)
    health = cli.run()
    assert health["ok"] and "published" not in health
    assert any(s.startswith(f"hold {cand['id']}: LOST") for s in health["steps"])
    assert any("unrecorded upload" in w for w in health["warnings"])
    assert ledger.is_done(cand["id"])  # never rebuilt and offered again


def test_an_upload_never_published_is_reported_after_a_day():
    from studio import ledger

    ledger.save("uploads", {"wk-Q1": {"video_id": "OLD1", "at": "2026-10-20T10:00:00+00:00"},
                            "wk-Q2": {"video_id": "NEW2", "at": "2026-10-22T09:00:00+00:00"}})
    notes = ledger.stale_uploads(AT)
    assert len(notes) == 1 and notes[0].startswith("stale upload wk-Q1: video OLD1 uploaded 50 h ago")
