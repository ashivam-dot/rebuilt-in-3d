import pytest

from studio import ledger, media, outlets


@pytest.fixture(autouse=True)
def offline_outlets(monkeypatch):
    """No test reads a live outlet feed, article or Openverse; tests that need them give fixtures."""
    def offline(*args, **kwargs):
        raise ConnectionError("offline in tests")

    outlets.reset()
    monkeypatch.setattr(outlets, "_feed", offline)
    monkeypatch.setattr(outlets, "_extract", offline)
    monkeypatch.setattr(media, "openverse_for", lambda *args, **kwargs: [])
    yield
    outlets.reset()


@pytest.fixture(autouse=True)
def private_state(monkeypatch, tmp_path_factory):
    """No test writes the repo's state/ (the radar caches its last good Wikidata list there)."""
    monkeypatch.setattr(ledger, "STATE", tmp_path_factory.mktemp("state"))
