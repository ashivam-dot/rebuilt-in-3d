from dataclasses import replace

from studio import gate, ledger, quake, writer
from studio.spec import Short
from tests.test_youtube import FIXTURE

OLD = "How the M6.3 Vanuatu quake ruptured, in 3D"


def test_a_quake_title_leads_with_magnitude_nearest_place_and_impact():
    t = quake.quake_title("6.3", "Vanuatu", "Norsup", True, quake.impact_words("green", 8700, "very strong", 10), [])
    assert t == "Quake near Norsup: M6.3, ≈8,700 people in very strong shaking"
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
