"""NASA Image and Video Library photos for natural disasters: public domain, NASA's own credit only, of the event.

The fixture is a recorded images-api.nasa.gov search (2026-10-22): six ISS photos of Hurricane Milton (October 2024),
two ASTER/radar records credited to NASA's partners (METI/Japan, ASI) and a 2012 Hurricane Sandy record.
"""
import json
from datetime import date
from pathlib import Path

import pytest

from studio import compose, gate, media, writer

FIXTURE = Path(__file__).parent / "fixtures" / "nasa-hurricane-milton.json"
NASA_FOR = media.nasa_for  # taken at import, before conftest stubs it for every test


@pytest.fixture
def milton(monkeypatch):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    asked = []

    def get_json(url, params=None, **k):
        asked.append((url, params))
        return data

    monkeypatch.setattr(media.net, "get_json", get_json)
    return data, asked


def test_nasa_keeps_its_own_photos_of_the_event(milton):
    _, asked = milton
    got = media.nasa("Hurricane Milton", date(2024, 10, 5), ("hurricane",), limit=6)
    assert asked[0][0] == media.NASA and asked[0][1]["media_type"] == "image" and asked[0][1]["q"] == "Hurricane Milton"
    # Two frames at most under one title, so a Short is not three copies of one shot.
    titles = [p.description for p in got]
    assert len(got) == 3 and max(titles.count(t) for t in titles) <= 2
    p = got[0]
    assert p.file.startswith("nasa:iss072e") and p.page == f"https://images.nasa.gov/details/{p.file[5:]}"
    assert p.license == "Public domain (NASA)" and p.author == "NASA" and p.host == media.NASA_HOST
    assert p.credit == "Photo: NASA / Public domain (NASA) / NASA Image and Video Library"
    assert p.url.endswith("~large.jpg") and min(p.width, p.height) >= media.MIN_SIDE and p.date >= "2024-10-05"
    assert media.FREE.match(p.license)  # the publish gate's licence check passes it


def test_nasa_refuses_old_photos_partners_credits_and_other_storms(milton):
    data, _ = milton
    # A storm of the same name in another year: every photo predates it.
    assert media.nasa("Hurricane Milton", date(2026, 9, 1), ("hurricane",)) == []
    assert media.nasa("Hurricane Sandy", date(2012, 10, 1), ("hurricane",)) == []  # its record is from 2017
    # Re-dated into the window, the partners' records still fail on their credit (and the radar one on its title).
    for item in data["collection"]["items"]:
        item["data"][0]["date_created"] = "2024-10-08T00:00:00Z"
    got = media.nasa("Kilauea", date(2024, 10, 1), ("lava",))
    assert got == []
    assert media.nasa("Hurricane Milton", date(2024, 10, 5), ("typhoon",)) == []  # the event word must match


def test_a_courtesy_or_partner_credit_is_never_public_domain():
    ok = {"title": "Hurricane Milton", "description": "Hurricane Milton is pictured from the station."}
    assert media.nasa_rights_ok(ok)
    assert media.nasa_rights_ok(ok | {"secondary_creator": "NASA/JPL-Caltech"})
    assert media.nasa_rights_ok(ok | {"photographer": "NASA/Bill Ingalls"})
    assert not media.nasa_rights_ok(ok | {"description": "Image courtesy of Maxar Technologies."})
    assert not media.nasa_rights_ok(ok | {"description": "Credit: ESA/Copernicus Sentinel."})
    assert not media.nasa_rights_ok(ok | {"description": "The storm at landfall. Credit: Planet Labs PBC. More."})
    assert not media.nasa_rights_ok(ok | {"secondary_creator": "NASA/METI/AIST/Japan Space Systems, and U.S./Japan "
                                                                "ASTER Science Team"})
    assert not media.nasa_rights_ok(ok | {"secondary_creator": "ASI/NASA/JPL-Caltech"})
    assert not media.nasa_rights_ok(ok | {"photographer": "Joel Kowsky"})  # a name alone is not NASA's credit



@pytest.mark.parametrize("record", [
    # Earth Observatory's own credit over a partner's satellite data, named only in the description.
    {"secondary_creator": "NASA Earth Observatory/Lauren Dauphin", "title": "Typhoon Ragasa Nears Luzon",
     "description": "The image was made using modified Copernicus Sentinel-2 data (2024) processed by the European "
                    "Space Agency."},
    {"title": "Typhoon Ragasa", "description": "Image acquired by the Advanced Himawari Imager on Himawari-9, "
                                               "operated by the Japan Meteorological Agency."},
    {"title": "Storm Boris Over Europe", "description": "Meteosat data from EUMETSAT show the storm's spiral."},
    {"title": "Typhoon Hinnamnoor", "description": "A view from KOMPSAT-3A, operated by KARI."},
    {"title": "Cyclone Montha", "description": "Data processed by the Indian Space Research Organisation show it."},
])
def test_a_partners_data_named_in_the_description_is_not_public_domain(record):
    assert not media.nasa_rights_ok(record)


def test_us_federal_data_named_in_the_description_stays_public_domain():
    assert media.nasa_rights_ok({"title": "Hurricane Milton", "description": "VIIRS data on NOAA-20, operated by "
                                 "NOAA, and Landsat 9 data provided by the U.S. Geological Survey."})
    assert media.nasa_rights_ok({"title": "Hurricane Milton", "description": "Track provided by the National "
                                 "Hurricane Center. An astronaut on the station took the photo."})


def test_a_description_saying_false_colour_or_annotated_is_not_a_photo_of_the_event(milton):
    data, _ = milton
    first = data["collection"]["items"][0]["data"][0]
    assert not media.NASA_NOT_PHOTO.search(first["title"])
    first["description"] = "This false-color view, annotated by NASA, shows the burn scar. " + first["description"]
    got = media.nasa("Hurricane Milton", date(2024, 10, 5), ("hurricane",), limit=6)
    assert got and first["nasa_id"] not in {p.file[5:] for p in got}

def test_nasa_is_asked_only_about_natural_disasters(monkeypatch):
    monkeypatch.setattr(media, "nasa_for", NASA_FOR)  # the real one, over a fake search
    seen = []
    monkeypatch.setattr(media, "nasa", lambda q, since, words=(), limit=3, exclude=None: seen.append((q, words)) or [])
    for category in ("attack", "aviation", "rail", "protest", "death", None):
        assert media.nasa_for(category, ["X"], date(2026, 10, 1)) == []
    assert seen == []
    media.nasa_for("cyclone", ["Cyclone Montha", "Kakinada", "Cyclone Montha"], date(2026, 10, 1))
    assert seen == [("Cyclone Montha", media.NASA_WORDS["cyclone"]), ("Kakinada", media.NASA_WORDS["cyclone"])]


def test_the_writer_fills_a_storm_with_nasa_photos_without_faces(monkeypatch, tmp_path):
    asked = []
    photo = media.Photo(file="nasa:a", url="https://images-assets.nasa.gov/image/a/a~large.jpg",
                        page="https://images.nasa.gov/details/a", width=1920, height=1280, author="NASA",
                        license=media.NASA_LICENCE, description="Hurricane X", date="2026-10-02", origin="nasa",
                        host=media.NASA_HOST)
    monkeypatch.setattr(media, "nasa_for", lambda cat, names, since, limit, exclude: asked.append(
        (cat, names, since, limit)) or [photo])
    monkeypatch.setattr(writer, "_faceless", lambda found, folder: [p.__dict__ | {"credit": p.credit}
                                                                    for p in found])
    got = writer.nasa_photos("cyclone", ["Hurricane X"], date(2026, 10, 3), tmp_path, set(), 2)
    assert [p["file"] for p in got] == ["nasa:a"] and asked == [("cyclone", ["Hurricane X"], date(2026, 10, 1), 2)]
    assert writer.nasa_photos("attack", ["X"], date(2026, 10, 3), tmp_path, set(), 2) == []
    assert writer.nasa_photos("cyclone", ["X"], date(2026, 10, 3), tmp_path, set(), 0) == []


def test_nasa_photos_are_named_on_the_end_card_and_in_the_credits():
    nasa = {"host": media.NASA_HOST}
    assert media.hosts([nasa]) == "Wikimedia Commons and NASA"
    assert media.hosts([nasa, {"host": "Openverse (Flickr)"}]) == "Wikimedia Commons, Openverse and NASA"
    assert compose.disclosure([nasa]) == "Real photos: Wikimedia Commons, NASA · Narration: AI voice"
    assert gate.MIN_PHOTOS == 2 and gate.TRIBUTE_PHOTOS == 3  # NASA adds supply; the photo floors stay
