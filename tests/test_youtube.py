from dataclasses import replace
from pathlib import Path

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
