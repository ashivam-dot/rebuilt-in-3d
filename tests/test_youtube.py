from dataclasses import replace
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
