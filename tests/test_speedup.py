"""Orbitwire's 2026-10-14 speed-up: world outlets, wire copy counted once, one-story clustering, the publish gate's
wording rules inside the rewrite loop, a description that keeps every credit, and a person's own portraits first.
Every feed, article and API answer here is a fixture; nothing touches the network."""
from dataclasses import replace

import numpy as np

from datetime import datetime, timedelta, timezone

from studio import cli, gate, outlets, plan, trends, writer, youtube
from studio.spec import Beat, Short
from tests.test_outlets import NOW, _cluster, _draft, item, report


def test_world_outlets_are_english_and_name_their_owners():
    world = [o for o in outlets.OUTLETS if o["key"] in ("cbs-world", "nbc-world", "abc-us-intl", "fox-world",
                                                         "independent", "abc-au-world", "un-en", "euronews")]
    assert len(world) == 8 and all(o["lang"] == "en" and o["geo"] == "world" for o in world)
    assert all(o["group"] in outlets.GROUPS for o in outlets.OUTLETS)
    assert {o["owner"] for o in outlets.OUTLETS if o["key"] in ("un-en", "un-hi")} == {"United Nations"}


AP = ("LONDON (AP) — A ferry capsized off the coast of Lesbos on Tuesday, the coast guard said. Rescuers pulled "
      "dozens of passengers from the water near the port of Mytilene after the vessel overturned in strong winds. "
      "The coast guard said the search would continue through the night.")


def test_agency_copy_and_repeated_text_count_as_one_owner(monkeypatch):
    texts = {"https://abc/1": AP, "https://ind/1": "By Associated Press\n" + AP.replace("LONDON (AP) — ", ""),
             "https://bbc/1": "The ferry overturned near Mytilene, the Greek coast guard told the BBC, and the search "
                              "for the missing went on after dark with two helicopters and four boats."}
    monkeypatch.setattr(outlets, "text", lambda url: texts[url])
    rows = [item("abc-us-intl", "Ferry capsizes off Lesbos", url="https://abc/1"),
            item("independent", "Ferry capsizes off Lesbos", url="https://ind/1"),
            item("bbc-world", "Lesbos ferry capsizes", url="https://bbc/1")]
    got = outlets.reporting(rows)
    assert [r["owner"] for r in got] == ["BBC", "AP (news agency)"]
    assert got[1]["publisher"] in ("Disney (ABC News)", "Independent Digital News")
    assert outlets.reporting(rows[:2]) == []  # one AP story twice is not two sources
    assert outlets.wire("Paris (Reuters) - Police said") == "Reuters"


def test_a_loose_link_never_chains_two_incidents():
    rows = [item("bbc-world", "Lesbos ferry capsizes near Mytilene port", 3),
            item("independent", "Ferry capsizes near Mytilene port on Lesbos", 2.5),
            item("guardian", "Mytilene port ferry capsizes; Athens boat also sinks off Piraeus", 2),
            item("aljazeera", "Boat sinks off Piraeus near Athens port", 1.5),
            item("france24", "Athens: boat sinks off Piraeus", 1)]
    [story] = [s for s in outlets.stories(rows, NOW) if "mytilene" in s["id"]]
    assert story["headlines"] == [r["title"] for r in rows[:3]]  # the two Piraeus-only headlines never chain in


def test_a_big_story_with_a_brand_new_article_is_told_from_the_reporting_at_once(monkeypatch):
    rows = [i | {"matched": "2026 Chamoli cloudburst"} for i in _cluster()]
    known = ["2026 Chamoli cloudburst"]
    assert outlets.stories(rows, NOW, known=known) == []  # the article is settled: it is told from Wikipedia
    [story] = outlets.stories(rows, NOW, known=known, young=known)
    assert story["id"].startswith("nw-") and story["article"] == "2026 Chamoli cloudburst"

    cand = {"id": "wk-Q99", "kind": "incident", "title": "2026 Chamoli cloudburst", "owners": ["BBC", "A", "B"]}
    # Corroboration is outlets.stories' to count (2026-10-23): an article one owner's headline names is young too;
    # one under trends.YOUNG_MIN_AGE is not yet.
    hours = {"2026 Chamoli cloudburst": 2, "Settled": 9, "Quiet": 1.5, "Brand new": 0.5}
    monkeypatch.setattr(trends.wiki, "created", lambda title: datetime.now(timezone.utc) - timedelta(hours=hours[title]))
    cands = [cand, cand | {"title": "Settled"}, cand | {"title": "Quiet", "owners": ["BBC"]},
             cand | {"title": "Brand new"}]
    assert trends.young_articles(cands) == ["2026 Chamoli cloudburst", "Quiet"]
    told = [{"id": story["id"], "published_at": NOW.isoformat(), "article": "2026 Chamoli cloudburst"}]
    assert plan.told_before(cand, told, NOW)


def test_five_outlets_on_one_incident_make_it_breaking():
    at = NOW
    crash = {"kind": "incident", "category": "accident", "fame": 50_000, "news_at": NOW.isoformat(),
             "owners": ["BBC", "United Nations", "NBCUniversal", "Fox Corporation", "Los Angeles Times"]}
    assert plan.is_breaking(crash, at)
    assert not plan.is_breaking(crash | {"owners": crash["owners"][1:]}, at)  # four outlets
    assert not plan.is_breaking(crash | {"owners": ["BBC", "NBCUniversal", "Fox Corporation", "Los Angeles Times",
                                                    "Paramount (CBS)"]}, at)  # one strong outlet
    assert not plan.is_breaking(crash | {"category": "protest"}, at)


def _validate(say, casualties=True, ground="Place: Chamoli. Himalayan valleys of northern India."):
    photos = [{"file": f"File:{i}.jpg", "description": "Chamoli"} for i in range(3)]
    return writer._validate(_draft(say), photos, "Chamoli", ground, [], [], casualties)


def test_the_gates_wording_rules_are_rewritten_not_skipped():
    say = ["A cloudburst over Chamoli has cut off villages high in the Himalayan valleys of northern India this week.",
           "The gory scenes as the water tore through the valley left families with nothing at all.",
           "Two people were killed and the whole valley waits for the water to fall again.",
           "Teams reached the villages at 24:00, carrying food and medicine along roads the water tore apart."]
    problems = _validate(say, casualties=False)
    assert any("banned word 'gory'" in p for p in problems)
    assert any("says 'killed'" in p and "never mention deaths" in p for p in problems)
    assert any("24:00" in p for p in problems)
    assert not any("says 'killed'" in p for p in _validate(say, casualties=True))
    assert all(any(m in reason for m in cli.RETRYABLE) for reason in (
        "gate: beat 7: banned wording 'gory'", "gate: card 4: casualties without an agreed toll (injured)",
        "gate: beat 6: the number 24:00 isn't backed by any sourced fact"))


def test_a_caption_naming_a_place_is_rewritten():
    say = ["A cloudburst over Chamoli has cut off villages high in the Himalayan valleys of northern India this week."]
    draft = _draft(say)
    draft["beats"][0]["caption"] = "King Khalid International Airport"
    photos = [{"file": "File:0.jpg", "description": ""}]
    problems = writer._validate(draft, photos, "Chamoli", "Place: Chamoli.", [], [])
    assert any("names a place" in p for p in problems)
    draft["beats"][0]["caption"] = "Sher Shah Junction"
    assert any("names a place" in p for p in writer._validate(draft, photos, "Chamoli", "Place: Chamoli.", [], []))
    draft["beats"][0]["caption"] = "120 mph"
    assert not any("names a place" in p for p in writer._validate(draft, photos, "Chamoli", "Place: Chamoli.", [], []))


def test_the_narrator_never_speaks_for_a_country():
    say = ["The nation stands in mourning for the brave members of our armed forces."]
    assert any("says 'our'" in p for p in _validate(say))
    say = ["Carney said \"the nation is in mourning\" as the US sent condolences to the families."]
    assert not any("narrator never speaks" in p for p in _validate(say))


def test_photo_descriptions_are_never_a_source():
    say = ["A cloudburst over Chamoli has cut off villages high in the Himalayan valleys of northern India this week.",
           "The Nanda Devi temple stood above the water as rescue teams reached the villages.",
           "The Alaknanda river rose fast, and families living along its banks were moved to safer ground.",
           "The work to reopen the roads goes on, and the whole valley waits for the water to fall."]
    photos = [{"file": f"File:{i}.jpg", "description": "Nanda Devi temple"} for i in range(3)]
    draft = _draft(say)
    assert any("Nanda" in p for p in writer._validate(draft, photos, "Chamoli", "Place: Chamoli.", [], []))


def test_a_long_description_drops_the_narration_and_keeps_every_credit():
    fixture = Short.load(__import__("tests.test_youtube", fromlist=["FIXTURE"]).FIXTURE)
    url = "https://commons.wikimedia.org/wiki/File:" + "%CE%A3" * 70 + ".jpg"
    story = replace(fixture, scene={**fixture.scene, "template": "story", "photos": []},
                    beats=[Beat("Narration that the video already says. " * 30, "photo:0"), Beat("Outro", "outro")],
                    credits=[f"Photo: Author {i} / CC BY-SA 2.0 / Wikimedia Commons {url}" for i in range(8)])
    text = youtube.description(story)
    assert len(text.encode()) <= youtube.DESCRIPTION_BYTES
    assert "Narration that the video" not in text and "Author 7 / CC BY-SA 2.0" in text
    assert "Narration that the video" in youtube.description(replace(story, credits=story.credits[:1]))


def test_a_persons_own_portraits_go_before_photos_with_strangers(monkeypatch, tmp_path):
    from studio import media

    found = [type("P", (), {"file": f"File:{n}.jpg", "path": str(tmp_path / f"{n}.jpg")})() for n in
             ("with students", "portrait", "at a desk")]
    monkeypatch.setattr(media, "find", lambda *a, **k: found)
    monkeypatch.setattr(media, "download", lambda f, folder: f)
    monkeypatch.setattr(media, "as_dicts", lambda f: [{"file": p.file, "path": p.path, "origin": "own"} for p in f])
    monkeypatch.setattr(writer.cv2, "imread", lambda path: np.zeros((1000, 1000, 3), np.uint8))
    me, other = np.ones(128) / np.sqrt(128), np.eye(128)[0]
    faces = iter([[(0, 0, 300, 300, me), (400, 0, 280, 280, other)], [(0, 0, 300, 300, me)],
                  [(0, 0, 300, 300, me), (500, 500, 40, 40, other)]])
    monkeypatch.setattr(writer.faces, "detect", lambda img: [{"box": f[:4], "score": 0.9, "feature": f[4]}
                                                             for f in next(faces)])
    got = writer._own_photos("Someone", {}, tmp_path, True, None, None, False)
    assert [p["file"] for p in got] == ["File:portrait.jpg", "File:at a desk.jpg", "File:with students.jpg"]
    assert [p["others"] for p in got] == [0, 0, 1]
