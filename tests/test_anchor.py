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


def _photo(file, kind, shows=(), **kw):
    return {"file": file, "license": "CC BY-SA 4.0", "page": f"https://commons.wikimedia.org/wiki/{file}",
            "description": kw.pop("description", ""), "kind": kind, "shows": list(shows), "origin": "event", **kw}


# Proposed for retraction by the picture audit (studio/youtube.py AUDIT_RETRACT, awaiting the owner), and the
# Macron Short the owner retracted.
REFUSED = ["ox3fConJ7EA", "dzq6GUxZyMc", "GTUwT6GQhV4", "mXR5B18rbtE", "a2qA0Fu19vc", "DwUtz4R4hzY", "XH8L7r7QUnk",
           "OT6g4NIr7Q8", "gCQ4ZWtobXA"]
# The audit's keepers: their pictures show what they say. A5rMcUkzmF0 (the 17 October riots), kept by the audit,
# is refused since review round 1 (2026-10-23): its "mid-September" beat stands on a 17 October photo, its "Milan"
# beat on the Eiffel Tower, its Interior Minister beat on a riot photo, and one photo carries 3 of 8 beats.
KEPT = ["EtrzpnJmwZs", "KheKmEYUvpc", "qwT1K_9MFwQ"]
REFUSED_SINCE_REVIEW = ["A5rMcUkzmF0"]


def _load(vid: str) -> Short:
    return Short.load(FIX / f"{vid}.json")


def _repicked(short: Short) -> Short:
    """The Short's own script and photos with each beat's picture chosen by the branch's picker (Story.assign): the
    plan the new pipeline would publish (review round 1: judging only the old choices hid Spain, Riehle, Flydubai)."""
    told = [b for b in short.beats if b.shot.startswith("photo:")]
    picks = anchor.story_of(short).assign([b.text for b in told], [int(b.shot[6:]) for b in told])
    beats = [replace(b, shot=f"photo:{i}", anchor=w) for b, (i, w) in zip(told, picks)]
    return replace(short, beats=beats + [b for b in short.beats if not b.shot.startswith("photo:")])


@pytest.mark.parametrize("vid", REFUSED + REFUSED_SINCE_REVIEW)
def test_the_audited_shorts_that_show_what_they_do_not_say_are_refused(vid):
    short = _load(vid)
    assert gate.pictures(short, anchor.story_of(short)), vid
    again = _repicked(short)
    assert gate.pictures(again, anchor.story_of(again)), vid  # re-picked by the new code, still refused


@pytest.mark.parametrize("vid", KEPT)
def test_the_audited_shorts_that_show_what_they_say_still_pass(vid):
    short = _load(vid)
    assert gate.pictures(short, anchor.story_of(short)) == [], vid
    again = _repicked(short)
    assert gate.pictures(again, anchor.story_of(again)) == [], vid


def test_a_place_photo_never_stands_in_for_a_person_without_a_photo():
    # Review round 1: re-picked, the Spanish housing Short put the Sol platforms under "Prime Minister Pedro Sanchez
    # agreed ..." and passed at 75%; with "In Madrid" added to every beat (as the feedback asked), at 100%.
    short = _repicked(_load("DwUtz4R4hzY"))
    story = anchor.story_of(short)
    told = [b for b in short.beats if b.shot.startswith("photo:")]
    texts = [("In Madrid, " + b.text[0].lower() + b.text[1:]) if "Madrid" not in b.text else b.text for b in told]
    story.prepare(texts)
    assert "Pedro Sánchez" in story.unshown
    for i, kind in enumerate(story.kinds):
        if kind in ("place", "setting"):
            assert not story.fits(texts[1], i), (texts[1], story.photos[i]["file"])
            assert not story.named("In Madrid, Spain, people marched.") or story.kinds[story.named(
                "In Madrid, Spain, people marched.")[0]] not in ("place", "setting")
    picks = [i for i, _ in story.assign(texts)]
    assert story.judge(texts, picks)["shown"] < anchor.SHOWN_SHARE


def test_a_title_naming_someone_without_a_photo_is_faceless():
    # Review round 1: Flydubai, "The Courage of Captain Machchhar", re-picked, put a stock A6-FKF photo (taken nine
    # months before) under "attacked Captain Smit Machchhar with a crash axe" and passed.
    short = _repicked(_load("OT6g4NIr7Q8"))
    story = anchor.story_of(short)
    assert all(k != "event" for k in story.kinds)  # dated outside the story's days: the aircraft, not the hijacking
    problems = gate.pictures(short, story)
    assert any(p.startswith("faceless:") and "Machchhar" in p for p in problems)


def _plan(name, photos, beats, people=(), when=date(2026, 10, 16), kind="protest"):
    return anchor.Story(photos, name, list(people), "wk-test", kind, when, "protest"), beats


ITALY = [_photo("File:Italian protests 2026.jpg", "event", description="A broken shopfront in Milan, due to the riots.",
                date="2026-10-19 09:49:39", categories=["October 2026 in Milan", "2026 Italian unrest (Milan)"]),
         _photo("File:Studenti Roma Manifestazione.png", "event", date="2026-10-17",
                description="Studenti che manifestano di fronte al Ministero dell'Istruzione"),
         _photo("File:Studenti Torino Manifestazione.png", "event", date="2026-10-17",
                description="Studenti che occupano il monumento a Vittorio Emanuele"),
         _photo("File:Giorgia Meloni Official 2024 (cropped).jpg", "person", ["Giorgia Meloni"], origin="wikidata")]
FLAMINGO = [_photo("File:Flamingo Revolution Tirana Protest nr14 June 13 2026 12.jpg", "event", date="2026-06-13"),
            _photo("File:Flamingo Revolution on 4 July 2026.jpg", "event", date="2026-07-04"),
            _photo("File:(20260621 164613782 HDR) Flamingo Revolution Berlin.jpg", "event", date="2026-06-21",
                   description="Albanians demonstrate at Brandenburg Gate, Berlin, to show support and solidarity"),
            _photo("File:Flamingo Revolution rally in Toronto, June 6, 2026 (2).jpg", "event", date="2026-06-06",
                   description="A rally in Toronto in support of Albanian Flamingo Revolution protesters"),
            _photo("File:Edi Rama (2024-02-29).jpg", "person", ["Edi Rama"], origin="wikidata")]


def test_an_event_photo_is_not_shown_under_another_place_or_day():
    # Review round 1, from dry runs 39845886597 (Italy) and 39878762603 (Flamingo Revolution).
    beats = ["Italian unrest began on October 16, 2026, with nationwide student demonstrations.",
             "In Rome, some demonstrators threw firecrackers near the Ministry of Education.",
             "Clashes broke out in Milan and Bologna as masked groups broke away from marches.",
             "The government announced plans to send 500 military personnel to Milan for security."]
    story = anchor.Story(ITALY, "2026 Italian unrest", ["Giorgia Meloni"], "wk-Q141776873", "protest",
                         date(2026, 10, 16), "conflict")
    story.prepare(beats)
    assert not story.fits(beats[1], 2)  # the Turin march under "In Rome"
    assert story.fits(beats[1], 1)  # the Rome march
    assert not story.fits(beats[3], 1) and story.fits(beats[3], 0)  # Milan's military over Milan, not Rome
    assert not story.fits(beats[0], 0) and story.fits(beats[0], 1)  # 16 October: not the 19th, the 17th will do
    assert story.fits("The 17 October Movement called for more marches.", 0)  # a name, not a day
    flam = ["Flamingo Revolution began as a local land dispute in Baks-Rrjoll on 2 February 2026.",
            "By May, demonstrations shifted to Zvërnec over luxury tourism projects.",
            "Violence against protesters triggered further demonstrations in the capital of Tirana.",
            "Protests spread to Albania, Kosovo, and the diaspora, with a 20 June demonstration.",
            "The movement remains active as protesters demand constitutional reforms."]
    story = anchor.Story(FLAMINGO, "Flamingo Revolution", ["Edi Rama"], "wk-Q139998119", "protest",
                         date(2026, 10, 23), "movement")
    story.prepare(flam)
    assert not any(story.fits(flam[0], i) for i in range(4))  # Baks-Rrjoll in February: no photo of it
    assert not any(story.fits(flam[1], i) for i in range(4))  # Zvernec in May
    assert story.fits(flam[2], 0) and not story.fits(flam[2], 2)
    assert [i for i, _ in story.assign(flam)][3] == 2  # the diaspora beat shows Berlin on 21 June
    assert not story.fits(flam[3], 0)
    assert not story.fits(flam[4], 2) and story.fits(flam[4], 1)  # Berlin only under the diaspora


def test_a_caption_card_never_claims_what_its_photo_does_not_show():
    # Review round 1: "Map of Albania" over a Tirana rally, "Military deployment" over a march (dry runs).
    story = anchor.Story(FLAMINGO + ITALY, "Flamingo Revolution", ["Edi Rama"], "wk-Q139998119", "protest",
                         date(2026, 10, 23), "movement")
    story.prepare(["The Flamingo Revolution filled Tirana.", "Edi Rama defended the projects."])
    assert not story.caption_fits("Map of Albania", 0)
    assert not story.caption_fits("Baks-Rrjoll Protests 2026", 0)
    assert not story.caption_fits("Military deployment", 5)
    assert not story.caption_fits("Police response", 5)
    assert story.caption_fits("Tirana Demonstrations", 0)  # the file says Tirana
    assert story.caption_fits("Edi Rama", 4) and story.caption_fits("July 2026 Protests", 1)
    assert story.caption_fits("20,000 marched", 0)
    draft = {"beats": [{"say": "The Flamingo Revolution filled Tirana.", "photo": 0, "caption": "Map of Albania"},
                       {"say": "Edi Rama defended the projects.", "photo": 4, "caption": "Edi Rama"}]}
    beats = writer.anchor_photos(draft, story)["beats"]
    assert [b["caption"] for b in beats] == ["", "Edi Rama"]


def test_no_photo_carries_more_than_its_share_of_beats():
    beats = [f"Students marched again on day {n} of the unrest." for n in range(8)]
    story = anchor.Story(ITALY[:1] + ITALY[3:], "2026 Italian unrest", ["Giorgia Meloni"], "wk-x", "protest",
                         date(2026, 10, 19), "conflict")
    assert story.most(len(beats)) == 4
    got = story.judge(beats, [0] * 8)
    assert got["unanchored"] == [4, 5, 6, 7]


def test_an_event_photo_of_the_thing_beats_a_stock_photo_of_it():
    photos = [_photo("File:Milan riot police 17 October 2026.jpg", "event", date="2026-10-17",
                     description="Police in riot gear face protesters in Milan"),
              _photo("File:Italy Police car.jpg", "thing", ["police"], date="2015-01-23")]
    story = anchor.Story(photos, "2026 Italian unrest", [], "wk-x", "protest", date(2026, 10, 16), "conflict")
    assert story.assign(["Police used water cannons and tear gas."], [1])[0][0] == 0


def test_code_keeps_the_town_photo_to_one_beat_and_never_first():
    # Review round 1: assign put the setting photo on beats 2 and 4, and _validate then refused every draft.
    photos = [_photo("File:Paris riots 1.jpg", "event", date="2026-10-17"),
              _photo("File:Paris riots 2.jpg", "event", date="2026-10-17"),
              {"file": "File:Paris skyline.jpg", "description": "", "role": "setting", "kind": "setting",
               "shows": ["Paris"]}]
    beats = ["Paris saw riots.", "Thousands marched.", "In Paris the night was loud.", "Shops burned.",
             "In Paris, calm returned."]
    picks = [i for i, _ in anchor.Story(photos, "2026 riots", [], "wk-x", "protest", date(2026, 10, 17),
                                        "protest").assign(beats, [0, 0, 2, 2, 0])]
    assert picks[0] != 2 and picks.count(2) <= 1
    draft = {"beats": [{"say": t, "photo": n, "caption": ""} for t, n in zip(beats, [2, 2, 2, 2, 2])]}
    writer.anchor_photos(draft, anchor.Story(photos, "2026 riots"))
    assert sum(b["photo"] == 2 for b in draft["beats"]) <= 1 and draft["beats"][0]["photo"] != 2


def test_the_spanish_housing_short_is_refused_for_its_metro_signs():
    short = _load("DwUtz4R4hzY")
    problems = gate.pictures(short, anchor.story_of(short))
    assert any("show what is said for only" in p for p in problems)


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


def test_a_map_is_never_held_into_the_next_beat():
    # Review round 1: a 2 s hold out of a map at the 20% cap would put it on screen for 24%.
    beats = [Beat("Paris is in the north of France.", "photo:1"),
             Beat("On Friday President Macron blamed the ultra-left.", "photo:0", anchor="Macron")]
    shots = [{"photo": 1, "start": 0.0, "end": 3.0, "beat": beats[0], "outro": False, "map": True},
             {"photo": 0, "start": 3.0, "end": 6.0, "beat": beats[1], "outro": False}]
    words = [{"text": "Macron", "start": 3.95, "end": 4.3, "beat": 1}]
    compose.cut_on_names(shots, words)
    assert shots[1]["start"] == 3.0 and shots[0]["end"] == 3.0


def _search(cats=(), files=(), parents=None):
    def get_json(url, params=None, **kw):
        if params.get("prop") == "categories":
            title = params["titles"].removeprefix("Category:")
            return {"query": {"pages": [{"categories": [{"title": "Category:" + c}
                                                        for c in (parents or {}).get(title, [])]}]}}
        if params.get("list") == "search" and params["srnamespace"] == 14:
            return {"query": {"search": [{"title": f"Category:{c}"} for c in cats]}}
        if params.get("list") == "search":
            return {"query": {"search": [{"title": f} for f in files]}}
        return {"query": {}}
    return get_json


def test_an_events_own_commons_category_is_found_by_its_own_name(monkeypatch):
    # Review round 1: a search by "Madrid" took a Madrid education march for the housing protests, and year-wide
    # categories ("Demonstrations and protests in Paris in 2026") counted as the event.
    monkeypatch.setattr(net, "get_json", _search(["2026 high school student movement and blockades in France",
                                                  "Demonstrations and protests in France in 2026",
                                                  "October 2026 in France", "Manifestation du 17 octobre 2026 à Montréal",
                                                  "2025 French student protests", "Paris Fashion Week 2026",
                                                  "2026 French fuel protests"]))
    assert media.event_categories("2026 French student protests", date(2026, 10, 22), "protest") == [
        "2026 high school student movement and blockades in France"]
    assert media.event_categories("Madrid", date(2026, 10, 10), "protest") == []  # a town is no event's name
    assert media.event_keys("2026 Italian unrest") == [("italian", "italy", "itali")]
    assert media.event_keys("2026 protests") == []


def test_recent_uploads_must_name_the_event(monkeypatch):
    monkeypatch.setattr(net, "get_json", _search(files=["File:Flamingo Revolution Tirana Protest 2026.jpg",
                                                        "File:Tirana skyline 2026.jpg", "File:Flamingo at the zoo.jpg"]))
    assert media.recent_files("Flamingo Revolution", date(2026, 10, 21), "protest") == [
        "File:Flamingo Revolution Tirana Protest 2026.jpg"]
    assert media.recent_files("Madrid", date(2026, 10, 21), "protest") == []


def test_event_photos_are_searched_by_the_events_name_only(monkeypatch):
    asked = []
    monkeypatch.setattr(media, "event_categories", lambda name, *a, **k: asked.append(name) or [])
    monkeypatch.setattr(media, "recent_files", lambda name, *a, **k: asked.append(name) or [])
    REAL["event"](["2026 Spanish housing protests", "Madrid", "Spain"], date(2026, 10, 10), "protest")
    assert set(asked) == {"2026 Spanish housing protests"}


def test_the_event_lookup_never_stops_a_run(monkeypatch):
    def down(*a, **kw):
        raise ConnectionError("commons down")

    monkeypatch.setattr(net, "get_json", down)
    assert REAL["event"](["Paris", "", None], date(2026, 10, 21), "protest") == []
    assert media.event_categories("Paris", date(2026, 10, 21)) == []


def _infos(rows):
    return {f"File:{n}.jpg": {"mime": m, "width": 2000, "height": 1500, "url": "u", "descriptionurl": f"d{n}",
                              "sha1": n, "user": "Old", "timestamp": "2026-10-18T20:41:00Z",
                              "commonmetadata": [{"name": "Make", "value": "NIKON"}],
                              "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"},
                                              "DateTimeOriginal": {"value": d}}}
            for n, d, m in rows}


def test_a_photo_without_the_day_it_was_taken_or_after_the_story_is_not_the_event(monkeypatch):
    info = _infos([("a", "2026-10-17 12:00", "image/jpeg"), ("b", "", "image/jpeg"), ("c", "2019-05-01", "image/jpeg"),
                   ("d", "2026-10-14", "image/jpeg")])
    monkeypatch.setattr(media, "_info", lambda files, deep=False: info)
    monkeypatch.setattr(media, "_uploaders", lambda names: {})
    got = media._usable([(f, "recent", "subject", media.EVENT_STAMP) for f in info], set(), 6,
                        since=date(2026, 10, 3), until=date(2026, 10, 11), vet=True)
    assert got == []  # the 14 October education march is after a story of the 10th
    got = media._usable([(f, "recent", "subject", media.EVENT_STAMP) for f in info], set(), 6,
                        since=date(2026, 10, 14), until=date(2026, 10, 18), vet=True)
    assert [p.file for p in got] == ["File:a.jpg", "File:d.jpg"] and got[0].kind == "event"
    assert media.window(date(2026, 10, 10), "protest", today=date(2026, 10, 23)) == (date(2026, 10, 3),
                                                                                    date(2026, 10, 11))
    assert media.window(date(2026, 10, 22), "conflict", today=date(2026, 10, 23))[1] == date(2026, 10, 23)


def test_a_screenshot_uploaded_as_own_work_by_a_new_account_is_not_used(monkeypatch):
    # Review round 1, dry run 39845886597: User:Vene14 (registered 2026-10-15, 10 edits) uploaded two CC0 "own work"
    # PNGs of the Italian student marches 3 s apart, with no camera data and a 1440 px laptop-screen width.
    vene = {"user": "Vene14", "timestamp": "2026-10-17T20:41:00Z", "mime": "image/png",
            "commonmetadata": [{"name": "PixelXDimension", "value": 1440}], "extmetadata": {}}
    users = {"Vene14": {"registration": "2026-10-15T16:48:00Z", "editcount": 10},
             "Old": {"registration": "2015-01-01T00:00:00Z", "editcount": 5000}}
    assert media.provenance(vene, users) == "a screenshot (no camera data)"
    assert "new uploader" in media.provenance(vene | {"mime": "image/jpeg", "commonmetadata": []}, users)
    assert media.provenance(vene | {"mime": "image/jpeg", "commonmetadata": [{"name": "Model", "value": "iPhone 15"}]},
                            users) is None
    vrts = {"user": "X", "mime": "image/jpeg", "commonmetadata": [], "extmetadata": {"Categories": {
        "value": "Items with VRTS permission confirmed|Manifestations du 17 octobre 2026"}}}
    assert media.provenance(vrts, {}) is None
    assert media.provenance({"user": "Old", "timestamp": "2026-10-18T00:00:00Z", "mime": "image/jpeg",
                             "commonmetadata": [], "extmetadata": {}}, users) is None
    assert "unknown" in media.provenance({"user": "Gone", "mime": "image/jpeg", "commonmetadata": []}, users)


def test_an_impossible_commons_date_is_no_day():
    assert media._day("31 November 2025") is None and media._day("0 January 2020") is None
    assert media._day("17 October 2026, 10:48") == date(2026, 10, 17)


@pytest.mark.parametrize("caption", ["Students holding posters during the protest in Paris",
                                     "Protesters with a poster reading Macron demission",
                                     "Police car with the Polizia logo in Milan",
                                     "Street artist painting a mural during the strike"])
def test_ordinary_protest_captions_are_not_derivative(caption):
    assert not media.DERIVATIVE.search(caption)


@pytest.mark.parametrize("caption", ["Photo of a poster of Chuck Amato", "Film poster for Krantiveer",
                                     "Screenshot of the news", "Album cover", "Logo of the party",
                                     "An oil painting of the king", "Oil on canvas"])
def test_derivative_works_are_still_refused(caption):
    assert media.DERIVATIVE.search(caption)


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


def test_place_names_are_read_from_an_infobox():
    assert writer.place_names("[[Milan]], [[Lombardy]], [[Italy]]") == ["Milan", "Italy"]
    assert writer.place_names(None) == []


def test_a_title_before_a_name_is_dropped_and_an_articles_people_are_found(monkeypatch):
    asked = []
    monkeypatch.setattr(writer, "story_person", lambda name, reports=None: asked.append(name) or
                        (("Giorgia Meloni", {}) if name == "Giorgia Meloni" else (None, {})))
    text = [{"owner": "Wikipedia", "text": "Prime Minister Giorgia Meloni condemned the violence."}]
    assert REAL["named_people"]("2026 Italian unrest", text, need=1) == ["Giorgia Meloni"]
    assert "Giorgia Meloni" in asked and not any(a.startswith("Prime") for a in asked)
