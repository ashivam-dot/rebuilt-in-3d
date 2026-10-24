"""Satellite images of a storm, and the story names that lost their compass word (2026-10-23)."""
import re
from datetime import date, datetime

from studio import media, outlets


def test_only_public_domain_us_federal_true_colour_passes():
    ok = media.satellite_ok("File:Champi 2026-10-20 0636Z.jpg", "Typhoon Champi near Taiwan", "Public domain",
                            "NASA Worldview, EOSDIS", "MODIS on Aqua")
    assert ok
    assert not media.satellite_ok("File:Champi.jpg", "Typhoon Champi", "CC BY 4.0", "NASA Worldview", "")
    assert not media.satellite_ok("File:Champi.jpg", "Typhoon Champi from Himawari-9", "Public domain",
                                  "Japan Meteorological Agency", "")
    assert not media.satellite_ok("File:Champi IR.jpg", "Infrared image of Typhoon Champi", "Public domain",
                                  "NOAA", "")
    assert not media.satellite_ok("File:Champi track.png", "Forecast track of Typhoon Champi", "Public domain",
                                  "Joint Typhoon Warning Center", "")
    assert not media.satellite_ok("File:Champi.jpg", "Typhoon Champi", "Public domain", "A Wikimedian", "")


def test_a_satellite_image_says_so_with_its_day_before_its_credit():
    assert media.satellite_label(date(2026, 10, 20)) == "Satellite image, 20 Oct 2026"
    p = media.Photo(file="File:Champi.jpg", url="", page="", width=2000, height=2000, author="NASA Worldview",
                    license="Public domain", description="", date="2026-10-20", origin="satellite",
                    label=media.satellite_label(date(2026, 10, 20)))
    assert p.credit == "Satellite image, 20 Oct 2026 · NASA Worldview / Public domain / Wikimedia Commons"


def test_a_pass_is_timed_by_its_file_name_on_its_own_day():
    def photo(file, when):
        return media.Photo(file=file, url="", page="", width=1, height=1, author="", license="", description="",
                           date=when, origin="satellite")

    assert media.pass_time(photo("File:Champi 2026-10-20 0636Z.jpg", "2026-10-20")) == datetime(2026, 10, 20, 6, 36)
    assert media.pass_time(photo("File:Champi.jpg", "2026-10-20 17:05")) == datetime(2026, 10, 20, 17, 5)
    assert media.pass_time(photo("File:Champi 2026-10-19 0636Z.jpg", "2026-10-20")) == datetime(2026, 10, 20)
    assert media.pass_time(photo("File:Champi.jpg", "")) is None


def test_satellite_images_are_only_for_storms_floods_and_fires():
    from .conftest import REAL

    assert REAL["satellite"](["Typhoon Champi"], date(2026, 10, 23), "attack") == []  # refused before any lookup
    assert media.SATELLITE_CATEGORIES == {"cyclone", "flood", "wildfire"}


def test_a_shooting_or_an_ambush_is_an_attack():
    attack = re.compile(media.EVENT_WORDS["attack"], re.I)
    assert attack.search("2026 Karak church shooting") and attack.search("2026 Croix-des-Bouquets gang ambush")
    assert not attack.search("Paris Fashion Week 2026")


def test_west_bank_is_one_story_with_bank():
    assert outlets.same_story("nw-20261023-bank-shooting", "nw-20261023-west-bank-shooting")
    assert outlets.same_story("nw-20261016-black-maritime", "nw-20261016-black-sea-maritime")
    assert not outlets.same_story("nw-20261023-bank-shooting", "nw-20261023-west-bengal-shooting")


def test_a_storm_named_by_its_place_is_found_by_the_name_its_headlines_give():
    heads = ["Typhoon Champi nears Taiwan as thousands evacuate", "Taiwan braces for Super Typhoon Champi",
             "Typhoon Warning issued across Taiwan", "Typhoon Warning: schools shut", "Storm Hits Taiwan"]
    assert media.storm_names(heads) == ["Typhoon Champi"]
    assert media.storm_names(["Typhoon Champi nears Taiwan"]) == []
    assert media.storm_names(["Taiwan shuts schools", "Quake hits Taiwan"]) == []


def test_a_waiting_candidate_can_be_made_for_review(monkeypatch):
    import pytest
    from studio import cli, ledger, writer
    ledger.save("candidates", {"candidates": [], "trending": [{"id": "nw-x-cyclone", "kind": "news"}]})
    built = []
    monkeypatch.setattr(writer, "build", lambda c: built.append(c["id"]) or (_ for _ in ()).throw(ValueError("stop")))
    with pytest.raises(ValueError, match="stop"):
        cli.prepare("candidate:nw-x-cyclone")
    assert built == ["nw-x-cyclone"]
    from studio import trends
    monkeypatch.setattr(trends, "radar", lambda: {"candidates": [], "emerging": [{"id": "nw-y-conflict", "kind": "incident"}]})
    with pytest.raises(ValueError, match="stop"):
        cli.prepare("candidate:nw-y-conflict")
    assert built[-1] == "nw-y-conflict"
    with pytest.raises(ValueError, match="not in the watcher"):
        cli.prepare("candidate:nw-missing")


def test_the_writer_sees_a_pass_as_what_it_shows_not_its_commons_note(monkeypatch, tmp_path):
    from studio import writer
    p = media.Photo("File:Champi 2026-10-20 0636Z.jpg", "u", "pg", 1600, 1200, "NASA", "Public domain",
                    "Super Typhoon Champi over the Philippine Sea, southwest of Guam", "2026-10-20 06:36", "satellite")
    monkeypatch.setattr(media, "satellite", lambda *a, **k: [p])
    monkeypatch.setattr(media, "download", lambda found, folder: found)
    rows = writer.satellite_photos("cyclone", ["Typhoon Champi", "Taiwan"], date(2026, 10, 23), tmp_path, set())
    assert [r["description"] for r in rows] == ["Typhoon Champi from orbit"]
