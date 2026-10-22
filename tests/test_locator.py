import io

import pytest
from PIL import Image

from studio import compose, gate, locator, media, net, wiki, writer
from studio.spec import Beat, Fact, Short

SITE = (44.0344, -121.2953)  # Silver Rail Elementary School, Bend, Oregon (2026-10-16)
PHOTO = {"file": "File:Bend.jpg", "license": "CC BY-SA 4.0", "page": "https://commons.wikimedia.org/wiki/File:Bend.jpg",
         "role": "setting"}
MAP = {"file": "OpenStreetMap (wide): Bend", "license": locator.LICENSE, "page": locator.PAGE, "role": "map"}


def _tile(*args, **kwargs):
    buf = io.BytesIO()
    Image.new("RGB", (256, 256), (240, 236, 228)).save(buf, "PNG")
    return buf.getvalue()


def _short(photos, kind="incident"):
    return Short(id="wk-Q141745391", kind=kind, title="The Silver Rail Elementary School Shooting",
                 beats=[Beat("At Silver Rail Elementary School in Bend, a shooting unfolded. " * 4, "photo:0"),
                        Beat(writer.OUTRO, "outro")],
                 facts=[Fact("name", "Silver Rail Elementary School shooting", "https://en.wikipedia.org/wiki/X", [])],
                 sources=["https://en.wikipedia.org/wiki/X"], loss=False,
                 scene={"template": "story", "photos": photos},
                 credits=[PHOTO["page"], locator.CREDIT + " " + locator.PAGE])


def test_the_site_sits_above_the_captions_in_the_middle():
    win = locator.frame(*SITE, 520.0)
    x, y = locator.project(win, *SITE)
    assert x == pytest.approx(locator.W / 2, abs=0.5) and y == pytest.approx(locator.SITE_Y * locator.H, abs=0.5)
    assert locator.scale_km(520.0) == 100 and locator.scale_km(16.0) == 2


def test_tiles_are_zoomed_so_the_map_labels_stay_readable():
    for _, km in locator.SPANS:
        win = locator.frame(*SITE, km)
        shown = locator.W / ((win["x1"] - win["x0"]) * 256 * 2 ** locator.zoom(win))
        assert locator.UPSCALE / 2 < shown <= locator.UPSCALE


def test_plates_are_free_credited_maps(tmp_path, monkeypatch):
    monkeypatch.setattr(net, "get", _tile)
    maps = locator.plates(SITE, "Silver Rail Elementary School", tmp_path, where="Bend, Oregon")
    assert [m["role"] for m in maps] == ["map", "map"]
    assert all(media.FREE.match(m["license"]) and "OpenStreetMap contributors" in m["credit"] for m in maps)
    assert all(m["description"].startswith("MAP:") for m in maps)
    assert Image.open(maps[0]["path"]).size == (locator.W, locator.H)


def test_a_short_is_never_maps_alone():
    assert any("only maps" in p for p in gate.check(_short([MAP, MAP])))
    # Owner, 2026-10-22: a town photo beside two maps is a map Short, not a story.
    assert any("only 0 show who or what" in p for p in gate.check(_short([PHOTO, MAP, MAP])))
    real = [dict(PHOTO, role=None, file=f"File:{i}.jpg") for i in range(3)]
    # Owner, 2026-10-22 ("do you think people are here to watch the map"): one map at most, beside real photos.
    assert not any("map" in p or "only" in p for p in gate.check(_short(real + [MAP])))
    assert any("2 maps (at most 1)" in p for p in gate.check(_short(real + [MAP, MAP])))
    assert any("3 maps" in p for p in gate.check(_short([PHOTO, MAP, MAP, MAP])))
    assert any("never a map" in p for p in gate.check(_short([PHOTO, PHOTO, MAP], kind="death")))


def test_one_map_joins_enough_real_photos_and_never_stands_in_for_them(tmp_path, monkeypatch):
    # Until 2026-10-22 two maps (and a town photo) made up for a story with one photo or none; the owner: "do you
    # think people are here to watch the map". Now one map joins gate.REAL_PHOTOS real photos, or none does.
    monkeypatch.setattr(locator, "plates", lambda site, label, folder, where="", spans=locator.SPANS:
                        [dict(MAP, kind="map", shows=[label]) for _ in spans])
    one = [dict(PHOTO, role="subject")]
    three = [dict(PHOTO, role="subject", file=f"File:{i}.jpg") for i in range(3)]
    got = writer.with_maps(three, SITE, "Silver Rail Elementary School, Bend, Oregon, U.S.", tmp_path, "attack")
    assert [p["role"] for p in got] == ["subject"] * 3 + ["map"] and got[-1]["shows"] == ["Silver Rail Elementary School"]
    assert writer.with_maps(got, SITE, None, tmp_path, "attack") == got  # never a second map
    assert writer.with_maps(one, SITE, None, tmp_path, "attack") == one  # too few real photos: no map
    assert writer.with_maps([], SITE, None, tmp_path, "attack") == []
    assert writer.with_maps(three, None, None, tmp_path, "attack") == three  # no precise site
    assert writer.with_maps(three, SITE, None, tmp_path, "rail") == three  # a derailment shows the train
    monkeypatch.setattr(writer, "LOCATOR_MAPS", False)
    assert writer.with_maps(three, SITE, None, tmp_path, "attack") == three


def test_unreachable_tiles_leave_the_story_waiting(tmp_path, monkeypatch):
    def down(*args, **kwargs):
        raise ConnectionError("tile server down")

    monkeypatch.setattr(net, "get", down)
    three = [dict(PHOTO, role="subject", file=f"File:{i}.jpg") for i in range(3)]
    assert writer.with_maps(three, SITE, "Bend, Oregon", tmp_path, "attack") == three


def test_code_keeps_the_town_photo_to_one_beat():
    photos = [dict(MAP), dict(MAP), dict(PHOTO)]
    draft = {"beats": [{"photo": p} for p in (2, 0, 2, 1, 2, 0, 1, 2)]}
    got = [b["photo"] for b in writer.place_photos(draft, photos)["beats"]]
    assert got.count(2) == 1 and got[0] != 2 and got[2] == 2
    assert got[:2] == [1, 0]  # beat 1 takes the photo beat 2 does not show
    plain = {"beats": [{"photo": p} for p in (0, 1, 0, 1)]}
    assert [b["photo"] for b in writer.place_photos(plain, [dict(MAP), dict(MAP)])["beats"]] == [0, 1, 0, 1]


def test_map_labels_name_the_site_then_its_town():
    assert writer.map_labels("Silver Rail Elementary School, Bend, Oregon, U.S.", SITE) == \
        ("Silver Rail Elementary School", "Bend, Oregon")
    assert writer.map_labels("Istanbul, Turkey", SITE) == ("Istanbul", "Istanbul, Turkey")


def _claim(value):
    return [{"rank": "normal", "mainsnak": {"datavalue": {"value": value}}}]


def test_a_country_is_never_a_site(monkeypatch):
    ethiopia = {"claims": {"P36": _claim({"id": "Q3624"}),
                           "P625": _claim({"latitude": 9.0, "longitude": 39.0})}}
    event = {"claims": {"P276": _claim({"id": "Q115"})}}
    monkeypatch.setattr(wiki, "page_info", lambda titles: {})
    monkeypatch.setattr(wiki, "entities", lambda qids: {"Q115": ethiopia})
    assert writer.precise_site("2026 Eritrean incursion into Ethiopia", event) is None


def test_a_story_given_up_for_photos_before_maps_gets_one_more_try(tmp_path, monkeypatch):
    from studio import ledger

    monkeypatch.setattr(ledger, "STATE", tmp_path)
    monkeypatch.setattr(ledger, "now", lambda: "2026-10-17T02:07:00+00:00")
    photos = "gave up after 6 tries: gate: only 0 usable photos of 2026 Silver Rail Elementary School shooting"
    ledger.save("skipped", {"wk-Q141745391": {"reason": photos, "at": "2026-10-16T10:14:43+00:00"},
                            "wk-Q2": {"reason": "gate: beat 7: banned wording 'gory'", "at": "2026-10-16T10:00:00+00:00"}})
    ledger.save("retries", {"wk-Q141745391": {"count": 6, "reason": photos, "at": "2026-10-16T10:14:43+00:00"}})
    assert not ledger.is_done("wk-Q141745391") and ledger.is_done("wk-Q2")
    assert ledger.retry("wk-Q141745391", "gate: no draft passed the fact checks: line 2")  # tries start afresh
    assert ledger.load("retries", {})["wk-Q141745391"]["count"] == 1
    for _ in range(5):
        ledger.retry("wk-Q141745391", "gate: only 0 usable photos of X (want 2)")
    assert ledger.is_done("wk-Q141745391")


def test_the_end_card_and_description_credit_the_maps():
    assert "Maps: OpenStreetMap" in compose.disclosure([PHOTO, MAP])
    assert "Maps" not in compose.disclosure([PHOTO])
    from studio import youtube
    text = youtube._description(_short([PHOTO, MAP, MAP]), narration=False)
    assert "© OpenStreetMap contributors" in text and "not what happened" in text
