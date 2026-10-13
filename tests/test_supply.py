"""Story supply (2026-10-13): whole-word decorum, young articles wait instead of being given up, events dated by their
infobox, fresh articles and Current events on the radar, headlines matched to fresh articles by their words, and
stories short of their own photos filled with photos of their places."""
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from studio import cli, gate, ledger, media, news, plan, stories, trends, writer
from studio.spec import Short

FIXTURE = Path(__file__).parent / "fixtures" / "eq-us6000u0xi.json"
NOW = datetime(2026, 10, 13, 8, tzinfo=timezone.utc)


@pytest.mark.parametrize("text, word", [
    ("It reached Category 4 strength off the coast.", None),
    ("A school trip ended early.", None),
    ("He starred as Walter Jr. in Breaking Bad for five seasons.", None),
    ("Breaking: a storm hits the coast.", "breaking"),
    ("A gory scene unfolded.", "gory"),
    ("Two men were decapitated.", "decapitat"),
    ("Fans wrote RIP under every post.", "rip"),
])
def test_banned_wording_is_whole_words(text, word):
    assert gate.banned_word(text) == word


def test_a_title_naming_a_show_passes_but_hype_does_not():
    short = Short.load(FIXTURE)
    assert not any("banned" in p for p in gate.check(replace(short, title="RJ Mitte, Walter Jr. of Breaking Bad")))
    assert any("banned" in p for p in gate.check(replace(short, title="Breaking news: the Vanuatu quake")))


def test_a_young_article_waits_and_a_story_given_up_only_for_that_comes_back(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "STATE", tmp_path)
    young = "gate: the article is under 6 hours old; facts may still move"
    ledger.skip("wp-2026_Aubagne_school_shooting", "gave up after 6 tries: " + young)
    ledger.skip("wk-Q1", "gate: beat 7: banned wording 'gory'")
    assert not ledger.is_done("wp-2026_Aubagne_school_shooting") and ledger.is_done("wk-Q1")
    ledger.save("retries", {"wk-Q2": {"count": 6, "reason": young, "at": "x"}})
    assert ledger.retry("wk-Q2", "gate: only 2 usable photos of Y on Wikimedia Commons (want 3)")
    assert ledger.load("retries", {})["wk-Q2"]["count"] == 1


def test_a_run_waits_for_young_articles_without_counting_a_try_or_taking_a_slot(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "STATE", tmp_path / "state")
    monkeypatch.setattr(ledger, "set_identity", lambda: None)
    monkeypatch.setattr(cli.learn, "refresh", lambda: None)
    cands = [{"id": f"wp-young-{i}", "kind": "incident", "fame": 9} for i in range(4)] + \
            [{"id": "wk-Q5", "kind": "incident", "fame": 1}]
    monkeypatch.setattr(plan, "watch", lambda: {"candidates": cands, "quakes": [], "trending": cands, "hazards": []})
    monkeypatch.setattr(plan, "lineup", lambda c: (c, []))
    tried = []

    def prepare(c):
        tried.append(c["id"])
        raise ValueError("gate: the article is under 6 hours old; facts may still move (ready in 2.0 h)"
                         if c["id"].startswith("wp-young") else "gate: only 1 usable photos of X (want 3)")
    monkeypatch.setattr(cli, "prepare", prepare)
    health = cli.run()
    assert tried[-1] == "wk-Q5" and sum(s.startswith("wait wp-young") for s in health["steps"]) == 4
    assert set(ledger.load("retries", {})) == {"wk-Q5"} and ledger.load("skipped", {}) == {}


@pytest.mark.parametrize("fields, day", [
    ({"date": "8 October 2026 (2026-10-08)"}, date(2026, 10, 8)),
    ({"date": "October 9, 2026"}, date(2026, 10, 9)),
    ({"date": "9–10 October 2026"}, date(2026, 10, 9)),
    ({"formed": "October 5, 2026"}, date(2026, 10, 5)),
    ({"date": "October 2026"}, None),
    ({}, None),
])
def test_infobox_dates(fields, day):
    assert stories.infobox_date(fields) == day


POOL = [news.pool_item("2026 Aubagne school shooting"), news.pool_item("RJ Mitte", person=True),
        news.pool_item("October 2026 attacks on Saudi Arabia airports"), news.pool_item("Mike Love", person=True)]


@pytest.mark.parametrize("headline, title", [
    ("RJ Mitte, 'Breaking Bad' actor and disability rights champion, dies at 34", "RJ Mitte"),
    ("Aubagne school shooting: teenager held after teacher wounded", "2026 Aubagne school shooting"),
    ("Saudi warning system stayed silent before deadly airport attacks",
     "October 2026 attacks on Saudi Arabia airports"),
    ("Teen wounds headmaster and teacher after opening fire at French school", None),
    ("Aubagne mayor opens a new library", None),
    ("A love song for Mike's birthday", None),
])
def test_headlines_find_fresh_story_articles_by_their_words(headline, title):
    assert news.reverse(headline, POOL) == title


@pytest.mark.parametrize("title, kind", [
    ("2026 Aubagne school shooting", "attack"), ("2026 Budhi Gandaki flood", "flood"),
    ("October 2026 attacks on Saudi Arabia airports", "attack"), ("2026 ISSF World Shooting Championships", None),
    ("2019 Christchurch mosque shootings", None), ("2026 Estonian presidential election", None),
])
def test_fresh_event_titles(title, kind):
    assert trends.title_kind(title, date(2026, 10, 13)) == kind


def _quiet(monkeypatch):
    monkeypatch.setattr(trends.wiki, "top_articles", lambda: (date(2026, 10, 12), []))
    monkeypatch.setattr(trends.wiki, "current_events", lambda day: [])
    monkeypatch.setattr(trends.wiki, "recent_deaths", lambda since: [])
    monkeypatch.setattr(trends.wiki, "new_articles", lambda hours: [])
    monkeypatch.setattr(trends, "google_trends", lambda geo: [])
    monkeypatch.setattr(trends, "gdacs_hits", lambda today: [])
    monkeypatch.setattr(trends.news, "signals", lambda **k: ({}, []))


def test_a_listed_article_wikidata_does_not_know_yet_is_a_candidate(monkeypatch):
    _quiet(monkeypatch)
    monkeypatch.setattr(trends.wiki, "current_events", lambda day: [("2026 Aubagne school shooting", False)])
    monkeypatch.setattr(trends.wiki, "page_info", lambda titles: {t: {"title": t, "qid": None, "lat": None,
                                                                      "lon": None} for t in titles})
    monkeypatch.setattr(trends.wiki, "classify", lambda qids: pytest.fail("no QIDs to classify"))
    monkeypatch.setattr(trends.wiki, "entities", lambda qids: {})
    monkeypatch.setattr(trends.wiki, "created", lambda t: datetime(2026, 10, 12, 9, tzinfo=timezone.utc))
    out = trends.radar(date(2026, 10, 13))["candidates"]
    assert [(c["id"], c["category"], c["fame"], c["date"]) for c in out] == [
        ("wp-2026_Aubagne_school_shooting", "attack", 2 * trends.PORTAL_FAME, "2026-10-12")]


def test_a_recent_death_named_by_a_trend_news_item_counts(monkeypatch):
    _quiet(monkeypatch)
    monkeypatch.setattr(trends.wiki, "recent_deaths", lambda since: [{"title": "RJ Mitte", "qid": "Q2118568"}])
    monkeypatch.setattr(trends, "google_trends", lambda geo: [
        {"query": "breaking bad actor", "traffic": 200, "geo": geo,
         "news": ["RJ Mitte, Breaking Bad actor, dies at 34"]}] if geo == "US" else [])
    monkeypatch.setattr(trends.wiki, "search", lambda q: pytest.fail("searched although a news item named the story"))
    hits, _ = trends._signals()
    assert hits["RJ Mitte"]["traffic"] == 200


def _photo(name, origin="article"):
    return media.Photo(file=f"File:{name}.jpg", url="u", page=f"https://commons.wikimedia.org/wiki/File:{name}.jpg",
                       width=1600, height=1200, author="A", license="CC BY 4.0", description=name, date="",
                       origin=origin)


@pytest.fixture
def photos(monkeypatch, tmp_path):
    """Own photos and context photos by name; a name with 'face' has a big face, one with 'tiny' a small one."""
    shelf = {"own": [], "context": []}
    monkeypatch.setattr(media, "find", lambda *a, **k: shelf["own"])
    monkeypatch.setattr(media, "context", lambda qids, limit=6, exclude=None: [p for p in shelf["context"]
                                                                               if p.file not in (exclude or set())])

    def download(found, folder):
        for p in found:
            p.path = str(Path(folder) / Path(p.file).name)
        return found
    monkeypatch.setattr(media, "download", download)
    monkeypatch.setattr(writer.cv2, "imread", lambda path: np.zeros((1000, 1000, 3), np.uint8))
    me = np.ones(128) / np.sqrt(128)
    order = []

    def detect(img):
        name = order.pop(0) if order else ""
        return [{"box": (0, 0, 300, 300), "score": 0.9, "feature": me}] if "face" in name else (
            [{"box": (0, 0, 20, 20), "score": 0.9, "feature": me}] if "tiny" in name else [])
    monkeypatch.setattr(writer.faces, "detect", detect)
    return shelf, order, tmp_path


def test_a_tribute_short_of_portraits_fills_in_with_its_places_but_never_other_faces(photos):
    shelf, order, tmp = photos
    shelf["own"] = [_photo("Michael Kearns face")]
    shelf["context"] = [_photo("Los Angeles skyline", "related"), _photo("Crowd face at a rally", "place"),
                        _photo("Juilliard School tiny", "place")]
    order += ["face", "", "face", "tiny"]
    got = writer.pick_photos("Michael Kearns", {}, tmp, person=True, context_qids=["Q1"])
    assert [p["file"] for p in got] == ["File:Michael Kearns face.jpg", "File:Los Angeles skyline.jpg",
                                       "File:Juilliard School tiny.jpg"]
    assert got[0]["focus"] and got[1]["focus"] is None


def test_incident_context_adds_the_place_it_is_located_in():
    claims = {"P131": [{"mainsnak": {"datavalue": {"value": {"id": "Q400"}}}}]}
    assert writer.incident_context({"claims": claims}, ["Q9"]) == ["Q9", "Q400"]
    assert writer.incident_context({}, []) == []


def test_no_portrait_means_no_tribute(photos):
    shelf, order, tmp = photos
    shelf["context"] = [_photo("Kolhapur skyline", "related")] * 3
    assert writer.pick_photos("Madhu Kambikar", {}, tmp, person=True, context_qids=["Q1"]) == []
