from datetime import datetime, timezone

from studio import usgs


def test_round_people_two_significant_figures():
    assert usgs.round_people(8734) == 8700
    assert usgs.round_people(123456) == 120000
    assert usgs.round_people(47) == 50


def test_parse_place():
    p = usgs.parse_place("102 km NE of Norsup, Vanuatu")
    assert p["distance_km"] == 102 and p["ref"] == "Norsup" and p["region"] == "Vanuatu"
    assert p["direction"] == "north-east"
    assert usgs.parse_place("Vanuatu Islands")["distance_km"] is None


def test_faulting_from_rake():
    assert usgs.faulting(90) == "reverse"
    assert usgs.faulting(-90) == "normal"
    assert usgs.faulting(0) == "strike-slip"
    assert usgs.faulting(178) == "strike-slip"


def test_date_words():
    assert usgs.date_words(datetime(2026, 10, 8, 9, tzinfo=timezone.utc)) == "October 8"


def test_historical_comment_with_listed_event():
    comment = ("Recent earthquakes in this area have caused secondary hazards such as tsunamis. "
               "A magnitude 7.4 earthquake 95 km east of this event struck Vanuatu on November 26, 1999 (UTC), "
               "with estimated population exposures of 3,000 at intensity VIII.")
    events = [{"Lat": -16.4, "Lon": 168.2, "Magnitude": 7.4, "Time": "1999-11-26T13:21:15", "Name": "Vanuatu"}]
    h = usgs.historical(comment, events)
    assert h and h["mag"] == "7.4" and h["year"] == "1999" and h["km"] == 95
    assert (h["lat"], h["lon"]) == (-16.4, 168.2) and h["direction"] == "east"


def test_historical_bearing_comes_from_coordinates():
    # The real PAGER comment for us6000u0xi says "95 km e ... struck UK"; the 1999 quake is due south.
    comment = ("A magnitude 7.4 earthquake 95 km e of this event struck UK on November 26, 1999 (UTC), "
               "with estimated population exposures of 32,000 at intensity VII.")
    events = [{"Lat": -16.423, "Lon": 168.214, "Magnitude": 7.4, "Time": "1999-11-26T13:21:15"}]
    h = usgs.historical(comment, events, near=(-15.5411, 168.1889))
    assert h["direction"] == "south" and h["km"] == 100 and h["measured"]


def test_compass():
    assert [usgs.compass(b) for b in (0, 44, 46, 180, 300, 350)] == ["north", "north-east", "north-east", "south",
                                                                       "north-west", "north"]


def test_historical_without_comment():
    assert usgs.historical("", []) is None
