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


def test_tags_keep_the_marker():
    short = Short.load(FIXTURE)
    tags = youtube.tags(replace(short, tags=[f"tag number {i}" for i in range(60)]))
    assert tags[-1] == youtube.MARKER + short.id and sum(len(t) + 2 for t in tags) <= 482


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
