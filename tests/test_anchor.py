"""Each beat shows who, what or where it says (studio/anchor.py). Owner, 2026-10-22, on the Macron protest-ban Short
(gCQ4ZWtobXA): "No real photos of incidents, no Macron photo, no school photo ... do you think people are here to
watch the map". The fixtures are the 13 newest public Shorts' plans as published (audit/orbitwire/PICTURE-AUDIT.md)."""
import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from studio import anchor, compose, gate, media, net, writer
from studio.spec import Beat, Short
from tests.conftest import REAL

FIX = Path(__file__).parent / "fixtures" / "pictures"
# Retired after the picture audit (studio/youtube.py RETRACTED), and the Macron Short the owner saw.
REFUSED = ["ox3fConJ7EA", "dzq6GUxZyMc", "GTUwT6GQhV4", "mXR5B18rbtE", "a2qA0Fu19vc", "DwUtz4R4hzY", "XH8L7r7QUnk",
           "OT6g4NIr7Q8", "gCQ4ZWtobXA"]
# The audit's keepers: their pictures show what they say.
KEPT = ["A5rMcUkzmF0", "EtrzpnJmwZs", "KheKmEYUvpc", "qwT1K_9MFwQ"]


def _load(vid: str) -> Short:
    return Short.load(FIX / f"{vid}.json")


@pytest.mark.parametrize("vid", REFUSED)
def test_the_audited_shorts_that_show_what_they_do_not_say_are_refused(vid):
    short = _load(vid)
    assert gate.pictures(short, anchor.story_of(short)), vid


@pytest.mark.parametrize("vid", KEPT)
def test_the_audited_shorts_that_show_what_they_say_still_pass(vid):
    short = _load(vid)
    assert gate.pictures(short, anchor.story_of(short)) == [], vid


def test_the_spanish_housing_short_is_refused_for_its_metro_signs():
    short = _load("DwUtz4R4hzY")
    problems = gate.pictures(short, anchor.story_of(short))
    assert any("show what is said for only" in p for p in problems)


def _photo(file, kind, shows=(), **kw):
    return {"file": file, "license": "CC BY-SA 4.0", "page": f"https://commons.wikimedia.org/wiki/{file}",
            "description": kw.pop("description", ""), "kind": kind, "shows": list(shows), "origin": "event", **kw}


MACRON = [_photo("File:Emmanuel Macron in 2026.jpg", "person", ["Emmanuel Macron"], origin="article", focus=[1, 2, 3, 4]),
          _photo("File:Manifestation du 17 octobre 2026 à Paris - 1.jpg", "event"),
          _photo("File:Paris riots, 17 October 2026 - Firefighters extinguishing a burning car.jpg", "event"),
          _photo("File:17 octobre 2026 faubourg Saint Denis Paris dégradation.jpg", "event"),
          _photo("OpenStreetMap (wide): Paris", "map", ["Paris"], role="map", origin="map",
                 description="MAP: the region around Paris, France, where it happened marked")]


def _replan(short: Short, photos: list[dict], people=None) -> Short:
    """The Short's script told over photos, each beat's picture chosen by writer.anchor_photos."""
    told = [b for b in short.beats if b.shot.startswith("photo:")]
    story = anchor.Story(photos, "Emmanuel Macron", people)
    draft = writer.anchor_photos({"beats": [{"say": b.text, "photo": 0} for b in told]}, story)
    beats = [Beat(b["say"], f"photo:{b['photo']}", {}, anchor=b["anchor"]) for b in draft["beats"]]
    return replace(short, beats=beats + [Beat("", "outro")],
                   scene={**short.scene, "photos": photos, "subject": {"name": "Emmanuel Macron", "kind": "person"},
                          "people": [{"name": "Emmanuel Macron"}]})


def test_the_macron_plan_is_refused_and_the_new_plan_shows_macron_the_protest_and_one_map_at_most():
    old = _load("gCQ4ZWtobXA")
    problems = gate.pictures(old, anchor.story_of(old))
    assert any("faceless" in p for p in problems) and any("maps fill" in p for p in problems)
    new = _replan(old, MACRON)
    assert gate.pictures(new, anchor.story_of(new)) == []
    shots = [int(b.shot[6:]) for b in new.beats if b.shot.startswith("photo:")]
    texts = [b.text for b in new.beats if b.shot.startswith("photo:")]
    assert all(shots[k] == 0 for k, t in enumerate(texts) if "Macron" in t)  # Macron's own photo when he is named
    assert any(MACRON[i]["kind"] == "event" for i in shots)  # the protest itself
    assert sum(MACRON[i]["kind"] == "map" for i in shots) <= 1 and MACRON[shots[0]]["kind"] != "map"
    assert new.beats[0].anchor == "Macron"
    listing = writer._messages("brief", [], "", MACRON, "Macron")[1]["content"]
    assert "0: File:Emmanuel Macron in 2026.jpg [PERSON: shows Emmanuel Macron]" in listing
    assert "[EVENT: shows the story itself]" in listing and "[MAP of Paris" in listing


def test_the_old_macron_photos_could_never_have_been_written_up():
    old = _load("gCQ4ZWtobXA")
    assert writer.faceless(old.scene["photos"], "Macron", old.id) is not None
    assert writer.faceless(MACRON, "Macron", old.id) is None


def test_filler_never_meets_the_floor():
    # Five photos of the Eiffel Tower under a protest script: plenty of pictures, none of what is said.
    town = [_photo(f"File:Eiffel {i}.jpg", "place", ["Eiffel Tower"]) for i in range(5)]
    old = _load("gCQ4ZWtobXA")
    texts = [b.text for b in old.beats if b.shot.startswith("photo:")]
    got = anchor.Story(town, "Macron").judge(texts, [k % 5 for k in range(len(texts))])
    assert got["shown"] == 0 and len(got["unanchored"]) == len(texts)


def test_a_beat_naming_someone_with_no_photo_has_nothing_to_show():
    story = anchor.Story(MACRON, "Emmanuel Macron", ["Emmanuel Macron", "Marine Le Pen"])
    assert story.unshown == ["Marine Le Pen"]
    assert not story.fits("Marine Le Pen called for calm.", 1)  # a protest photo does not show Le Pen
    assert story.fits("Thousands marched again on Saturday.", 1)
    assert story.fits("Macron spoke on Friday.", 0) and not story.fits("Macron spoke on Friday.", 1)


def test_a_map_stands_only_under_a_beat_about_where_and_never_first():
    story = anchor.Story(MACRON, "Emmanuel Macron")
    assert story.fits("Demonstrations were barred in Paris and Lyon.", 4)
    assert not story.fits("Demonstrations were barred in Paris and Lyon.", 4, first=True)
    assert not story.fits("Macron spoke in Paris.", 4)  # a beat naming a person shows the person
    assert not story.fits("Police fired tear gas.", 4)  # not about where


def test_a_tribute_still_needs_the_persons_own_face():
    assert gate.TRIBUTE_PHOTOS == 3
    story = anchor.Story([_photo("File:Stage.jpg", "place", ["Carnegie Hall"])], "Martina Arroyo",
                         short_kind="death")
    assert not story.subject_shown("death")


def test_the_cut_lands_on_the_word_that_names_the_picture():
    beats = [Beat("Paris woke up to burnt out cars.", "photo:1"),
             Beat("On Friday President Macron blamed the ultra-left.", "photo:0", anchor="Macron"),
             Beat("Late at night the defence council finally met to talk about Macron.", "photo:2", anchor="Macron")]
    shots = [{"photo": 1, "start": 0.0, "end": 3.0, "beat": beats[0], "outro": False},
             {"photo": 0, "start": 3.0, "end": 6.0, "beat": beats[1], "outro": False},
             {"photo": 2, "start": 6.0, "end": 10.0, "beat": beats[2], "outro": False}]
    words = [{"text": "On", "start": 3.05, "end": 3.2, "beat": 1}, {"text": "Friday", "start": 3.2, "end": 3.5, "beat": 1},
             {"text": "President", "start": 3.5, "end": 3.9, "beat": 1}, {"text": "Macron", "start": 3.95, "end": 4.3, "beat": 1},
             {"text": "Macron.", "start": 9.2, "end": 9.7, "beat": 2}]
    compose.cut_on_names(shots, words)
    assert shots[1]["start"] == pytest.approx(3.87) and shots[0]["end"] == shots[1]["start"]
    assert shots[2]["start"] == 6.0  # named too late in its beat: the cut stays on the beat


def _search(cats=(), files=()):
    def get_json(url, params=None, **kw):
        if params.get("list") == "search" and params["srnamespace"] == 14:
            return {"query": {"search": [{"title": f"Category:{c}"} for c in cats]}}
        if params.get("list") == "search":
            return {"query": {"search": [{"title": f} for f in files]}}
        return {"query": {}}
    return get_json


def test_an_events_own_commons_category_names_its_year_its_kind_and_its_place_or_day(monkeypatch):
    monkeypatch.setattr(net, "get_json", _search(["Manifestations du 17 octobre 2026", "Paris Fashion Week 2026",
                                                  "Demonstrations and protests in Paris in 2019",
                                                  "Emmanuel Macron in March 2026", "Manifestations, Lille, 17 Oct 2026"]))
    got = media.event_categories("Paris", date(2026, 10, 21), "protest")
    assert got == ["Manifestations du 17 octobre 2026", "Manifestations, Lille, 17 Oct 2026"]


def test_recent_uploads_must_name_the_place_and_the_event(monkeypatch):
    monkeypatch.setattr(net, "get_json", _search(files=["File:Manifestation du 17 octobre 2026 à Paris 112.jpg",
                                                        "File:Paris skyline 2026.jpg", "File:Lyon protest 2026.jpg"]))
    assert media.recent_files("Paris", date(2026, 10, 21), "protest") == [
        "File:Manifestation du 17 octobre 2026 à Paris 112.jpg"]


def test_the_event_lookup_never_stops_a_run(monkeypatch):
    def down(*a, **kw):
        raise ConnectionError("commons down")

    monkeypatch.setattr(net, "get_json", down)
    assert REAL["event"](["Paris", "", None], date(2026, 10, 21), "protest") == []
    assert media.event_categories("Paris", date(2026, 10, 21)) == []


def test_a_photo_without_the_day_it_was_taken_is_not_the_event(monkeypatch):
    info = {f"File:{n}.jpg": {"mime": "image/jpeg", "width": 2000, "height": 1500, "url": "u", "descriptionurl": f"d{n}",
                              "sha1": n, "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"},
                                                         "DateTimeOriginal": {"value": d}}}
            for n, d in (("a", "2026-10-17 12:00"), ("b", ""), ("c", "2019-05-01"))}
    monkeypatch.setattr(media, "_info", lambda files: info)
    got = media._usable([(f, "recent", "subject", media.EVENT_STAMP) for f in info], set(), 6,
                        since=date(2026, 10, 14))
    assert [p.file for p in got] == ["File:a.jpg"] and got[0].kind == "event"


def test_a_story_named_by_a_surname_is_the_person_the_reports_name_in_full(monkeypatch):
    human = {"claims": {"P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}}]}}
    monkeypatch.setattr(writer.wiki, "search", lambda name: "Emmanuel Macron")
    monkeypatch.setattr(writer.wiki, "page_info", lambda titles: {t: {"qid": "Q3052772"} for t in titles})
    monkeypatch.setattr(writer.wiki, "entities", lambda qids: {"Q3052772": human})
    reports = [{"owner": "BBC", "text": "President Emmanuel Macron said on Tuesday ..."}]
    assert writer.story_person("Macron", reports)[0] == "Emmanuel Macron"
    assert writer.story_person("Macron") == (None, {})  # without reports naming him in full
    assert writer.story_person("Macro", reports) == (None, {})


def test_the_people_two_owners_name_are_looked_up(monkeypatch):
    seen = []
    monkeypatch.setattr(writer, "story_person", lambda name, reports=None: seen.append(name) or
                        (("Emmanuel Macron", {}) if name == "Emmanuel Macron" else (None, {})))
    reports = [{"owner": "BBC", "text": "Emmanuel Macron said. Laurent Nuñez spoke."},
               {"owner": "Guardian Media Group", "text": "Emmanuel Macron said. The Interior Ministry agreed."}]
    assert REAL["named_people"]("Macron", reports) == ["Emmanuel Macron"]
    assert seen == ["Emmanuel Macron"]  # named by one owner only: never looked up


def test_a_thing_photo_must_name_the_thing(monkeypatch):
    found = [media.Photo(file="File:Police nationale Paris 2024.jpg", url="u", page="p", width=1, height=1, author="a",
                         license="CC BY-SA 4.0", description="", date="", origin="search"),
             media.Photo(file="File:France flag.jpg", url="u", page="p2", width=1, height=1, author="a",
                         license="CC BY-SA 4.0", description="", date="", origin="search")]
    monkeypatch.setattr(media, "named", lambda name, also="", limit=3, exclude=None: list(found))
    monkeypatch.setattr(writer, "_faceless", lambda rows, folder: media.as_dicts(rows))
    reports = [{"owner": o, "text": "Riot police fired tear gas."} for o in ("BBC", "Guardian Media Group")]
    got = REAL["thing_photos"](reports, "France", Path("/tmp/ow-rp/unused"), set())
    assert [(p["file"], p["kind"], p["shows"]) for p in got] == [("File:Police nationale Paris 2024.jpg", "thing",
                                                                  ["police"])]


def test_the_map_is_stamped_with_the_place_it_shows(tmp_path, monkeypatch):
    from studio import locator

    monkeypatch.setattr(locator, "ground", lambda win: __import__("PIL.Image").Image.new("RGB", (locator.W, locator.H)))
    maps = locator.plates((48.85, 2.35), "Paris", tmp_path, where="Paris, France", spans=locator.SPANS[:1])
    assert len(maps) == 1 and maps[0]["kind"] == "map" and maps[0]["shows"] == ["Paris"]
    assert "exact" not in maps[0]["description"]


def test_dry_runs_can_pass_over_a_story_and_never_hold_credentials():
    flow = (Path(__file__).parents[1] / ".github" / "workflows" / "run.yml").read_text()
    assert "STUDIO_DRY_SKIP" in flow and "if: always() && env.DRY != 'true' && env.EVENT == ''" in flow
    assert "!(inputs.dry || inputs.event != '') && secrets.YOUTUBE_OAUTH_JSON || ''" in flow


def test_retired_shorts_are_retracted():
    from studio import youtube

    ids = {v for v in youtube.RETRACTED} if not isinstance(youtube.RETRACTED, dict) else set(youtube.RETRACTED)
    assert set(REFUSED[:-1]) <= ids


def test_an_unrest_is_found_by_where_it_happened(monkeypatch):
    assert writer.place_names("[[Milan]], [[Lombardy]], [[Italy]]") == ["Milan", "Italy"]
    assert writer.place_names(None) == []
    monkeypatch.setattr(net, "get_json", _search(["Demonstrations and protests in Italy in 2026", "2026 in Italy"]))
    assert media.event_categories("Italy", date(2026, 10, 16), "conflict") == [
        "Demonstrations and protests in Italy in 2026"]
