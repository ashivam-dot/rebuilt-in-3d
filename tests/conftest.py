import pytest

from studio import ledger, media, outlets, writer

# The real lookups conftest turns off, for the tests of them.
REAL = {"named_people": writer.named_people, "thing_photos": writer.thing_photos, "event": media.event}


@pytest.fixture(autouse=True)
def offline_outlets(monkeypatch):
    """No test reads a live outlet feed, article, Openverse or NASA search; tests that need them give fixtures."""
    def offline(*args, **kwargs):
        raise ConnectionError("offline in tests")

    outlets.reset()
    monkeypatch.setattr(outlets, "_feed", offline)
    monkeypatch.setattr(outlets, "_extract", offline)
    monkeypatch.setattr(media, "openverse_for", lambda *args, **kwargs: [])
    monkeypatch.setattr(media, "nasa_for", lambda *args, **kwargs: [])
    # Nor a live Commons event category, nor a search for the people and things the reports name.
    monkeypatch.setattr(media, "event", lambda *args, **kwargs: [])
    monkeypatch.setattr(writer, "named_people", lambda *args, **kwargs: [])
    monkeypatch.setattr(writer, "thing_photos", lambda *args, **kwargs: [])
    yield
    outlets.reset()


@pytest.fixture(autouse=True)
def private_state(monkeypatch, tmp_path_factory):
    """No test writes the repo's state/ (the radar caches its last good Wikidata list there)."""
    monkeypatch.setattr(ledger, "STATE", tmp_path_factory.mktemp("state"))


@pytest.fixture(autouse=True)
def quakes_unheld(monkeypatch):
    """The quake hold (gate.QUAKES_HELD) is policy, not a check: tests judge the quake gate as if it were lifted."""
    from studio import gate

    monkeypatch.setattr(gate, "QUAKES_HELD", False)
