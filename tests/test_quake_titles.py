from dataclasses import replace

from studio import gate, ledger, quake, writer
from studio.spec import Short
from tests.test_youtube import FIXTURE

OLD = "How the M6.3 Vanuatu quake ruptured, in 3D"


def test_a_quake_title_leads_with_magnitude_nearest_place_and_impact():
    t = quake.quake_title("6.3", "Vanuatu", "Norsup", True, quake.impact_words("green", 8700, "very strong", 10), [])
    assert t == "Quake near Norsup: M6.3, ≈8,700 in very strong shaking or worse"
    t = quake.quake_title("7.7", "Panama", "Boca Chica", True, quake.impact_words("yellow", 50, "strong", 20), [])
    assert t == "M7.7 earthquake near Boca Chica, Panama: USGS PAGER yellow alert"
    t = quake.quake_title("6.8", "", "central Mid-Atlantic Ridge", False, quake.impact_words("green", 0, "strong", 10),
                          [])
    assert t == "Quake on the central Mid-Atlantic Ridge: M6.8, 10 km below the surface"
    assert "ruptured, in 3D" not in t


def test_quake_titles_never_open_like_a_recent_title():
    recent = []
    impact = quake.impact_words("yellow", 50, "strong", 20)
    for mag in ("6.1", "6.1", "6.1"):
        recent.append(quake.quake_title(mag, "Panama", "Boca Chica", True, impact, recent))
    assert len({writer._opening(t) for t in recent}) == 3
    assert all(20 <= len(t) <= 70 for t in recent)


def test_the_new_title_passes_the_publish_gate_with_the_facts_it_names():
    short = Short.load(FIXTURE)
    assert short.title == OLD
    title = quake.quake_title("6.3", "Vanuatu", "Norsup", True, quake.impact_words("green", 8700, "very strong", 10),
                              [])
    assert gate.check(replace(short, title=title)) == []
    # A number USGS did not give is still refused.
    assert any("9,100" in p or "9100" in p for p in gate.check(replace(short, title=title.replace("8,700", "9,100"))))


def test_quake_titles_read_the_last_published_titles():
    ledger.record_publish({"id": "eq-a", "title": "Quake near Norsup: M6.3, ≈8,700 people in very strong shaking",
                           "published_at": "2026-10-20T00:00:00+00:00"})
    t = quake.quake_title("6.3", "Vanuatu", "Norsup", True, quake.impact_words("green", 8700, "very strong", 10),
                          writer.recent_titles())
    assert not t.startswith("Quake near Norsup")


def test_impact_counts_people_at_that_shaking_or_worse_as_usgs_does():
    assert quake.impact_words("green", 8700, "very strong", 10) == "≈8,700 in very strong shaking or worse"


def test_a_place_with_no_region_is_never_repeated_or_said_to_be_struck(monkeypatch):
    """build() passes USGS's own region: "12 km SW of Kokopo" has none, so no title reads "near Kokopo, Kokopo"."""
    from studio import usgs

    seen = []
    for place in ("12 km SW of Kokopo", "central Mid-Atlantic Ridge", "20 km S of Boca Chica, Panama"):
        p = usgs.parse_place(place)
        recent = []
        for _ in range(3):
            t = quake.quake_title("6.1", p["region"], p["ref"], bool(p["distance_km"]),
                                  quake.impact_words("yellow", 0, "strong", 10), recent)
            recent.append(t)
            assert 20 <= len(t) <= 70
            if not p["region"]:
                assert t.count(p["ref"]) == 1 and ("near " + p["ref"] in t or "on the " + p["ref"] in t)
        seen.append(recent)
    assert seen[1][0] == "Quake on the central Mid-Atlantic Ridge: M6.1, USGS PAGER yellow alert"
    assert "Kokopo, Kokopo" not in " ".join(seen[0])
    assert any("Boca Chica, Panama" in t for t in seen[2])


def test_build_titles_a_distance_only_place_once_and_passes_the_gate(monkeypatch):
    from datetime import datetime, timezone

    from studio import usgs

    q = usgs.Quake("us1", 6.1, "12 km SW of Kokopo", datetime(2026, 10, 20, 3, 4, tzinfo=timezone.utc), -4.4, 152.2,
                   35.0, "yellow", 700, "https://earthquake.usgs.gov/earthquakes/eventpage/us1")
    pk = {"quake": q, "place": usgs.parse_place(q.place), "page": q.url, "mag_type": "mww", "depth_type": "",
          "pager_alert": "yellow", "exposure": {}, "cities": []}
    monkeypatch.setattr(quake.usgs, "pack", lambda event_id: pk)
    monkeypatch.setattr(quake.terrain, "elevation_at", lambda lat, lon: -100)
    short = quake.build("us1")
    assert short.title == "M6.1 earthquake near Kokopo: USGS PAGER yellow alert"
    assert gate.check(short) == []
    assert "Kokopo, Kokopo" not in short.title
