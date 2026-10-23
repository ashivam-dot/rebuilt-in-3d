"""Review round 2 (2026-10-23) of the real-pictures branch: each finding as a regression test."""
from datetime import date, datetime, timedelta, timezone

import cv2
import numpy as np
import pytest

from studio import anchor, cli, ledger, media, plan, writer

WHEN = date(2026, 10, 20)


def test_a_shared_surname_never_names_another_person():
    # Indira Gandhi's portrait stood under every Rahul Gandhi beat.
    assert anchor.surname("Marine Le Pen") == "Le Pen" and anchor.surname("Rahul Gandhi") == "Gandhi"
    assert not anchor.name_hit("Rahul Gandhi spoke in Delhi.", "Indira Gandhi")
    assert anchor.name_hit("Gandhi spoke in Delhi.", "Indira Gandhi")
    assert not anchor.name_hit("Gandhi spoke in Delhi.", "Indira Gandhi", {"rahul gandhi", "indira gandhi"})
    indira = {"file": "File:Indira Gandhi.jpg", "kind": "person", "shows": ["Indira Gandhi"]}
    story = anchor.Story([indira], "Congress rally", people=["Rahul Gandhi"], short_kind="protest")
    assert not story.fits("Rahul Gandhi told the rally the vote was stolen.", 0)


@pytest.mark.parametrize("taken, kind", [("2014", "thing"), ("", "thing"), ("October 2026", "thing"),
                                         ("2026-10-20 10:00", "event"), ("2019-10-20", "thing")])
def test_only_a_photo_dated_to_the_day_inside_the_window_is_the_event(taken, kind):
    photo = {"file": "File:Airbus A320 at Delhi.jpg", "origin": "event", "date": taken}
    assert anchor.legacy_kind(photo, "wk-Q1", "incident", WHEN, "air") == kind


def test_a_pending_review_is_no_review_and_pibor_is_not_pib():
    assert not media.reviewed("License review needed|Flickr review needed")
    assert not media.reviewed("Pibor County|Files with no machine-readable author")
    assert media.reviewed("License review|Pibor County") and media.reviewed("Photos by PIB")
    users = {"new": {"registration": "2026-10-19T00:00:00Z", "editcount": 1}}
    ii = {"mime": "image/jpeg", "user": "new", "timestamp": "2026-10-20T00:00:00Z",
          "extmetadata": {"Categories": {"value": "License review needed|Pibor County"}}}
    assert media.provenance(ii, users)


def test_a_copy_of_a_photo_is_dropped():
    assert media.DERIVED.search("B&W version of File:Deva Music Director.jpg")
    assert media.DERIVED.search("Negative of the original image")
    assert not media.DERIVED.search("Photo taken from the stage at the concert")


def test_one_picture_counts_once_and_the_earlier_upload_is_kept(tmp_path):
    rng = np.random.default_rng(7)
    img = cv2.GaussianBlur((rng.random((240, 320, 3)) * 255).astype(np.uint8), (31, 31), 0)
    other = cv2.GaussianBlur((rng.random((240, 320, 3)) * 255).astype(np.uint8), (31, 31), 0)
    cv2.imwrite(str(tmp_path / "a.jpg"), img)
    cv2.imwrite(str(tmp_path / "bw.jpg"), cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR))
    cv2.imwrite(str(tmp_path / "neg.jpg"), 255 - img)
    cv2.imwrite(str(tmp_path / "c.jpg"), other)
    photos = [{"file": "File:Copy.jpg", "path": str(tmp_path / "bw.jpg"), "uploaded": "2026-01-02T00:00:00Z"},
              {"file": "File:Original.jpg", "path": str(tmp_path / "a.jpg"), "uploaded": "2020-05-01T00:00:00Z"},
              {"file": "File:Negative.jpg", "path": str(tmp_path / "neg.jpg"), "uploaded": "2026-02-01T00:00:00Z"},
              {"file": "File:Other.jpg", "path": str(tmp_path / "c.jpg"), "uploaded": "2026-03-01T00:00:00Z"}]
    assert [p["file"] for p in writer.dedupe(photos)] == ["File:Original.jpg", "File:Other.jpg"]


def _school_story():
    photos = [{"file": "File:Ecole de Saint-Flour.jpg", "kind": "thing", "shows": ["school"],
               "description": "A primary school in Cantal, France"},
              {"file": "File:Cayenne march.jpg", "kind": "event",
               "description": "Students march through Cayenne against the school closures"}]
    return anchor.Story(photos, "French Guiana school blockades", sid="nw-x", short_kind="protest",
                        category="protest")


def test_a_stock_thing_never_stands_for_the_same_thing_somewhere_else():
    story = _school_story()
    beat = "In French Guiana, the school was blockaded by students."
    assert not story.fits(beat, 0) and story.fits(beat, 1)


def test_an_event_photo_stands_only_under_what_it_shows():
    story = _school_story()
    assert not story.fits("The government accused the far-left of the attacks.", 1)
    assert story.fits("Students marched against the closures.", 1)


def test_a_card_claims_only_what_its_photo_shows():
    story = _school_story()
    assert not story.caption_fits("High school blockades", 0)
    assert story.caption_fits("Students march", 1)


def test_a_portrait_alone_does_not_carry_a_news_story():
    macron = {"file": "File:Emmanuel Macron 2024.jpg", "kind": "person", "shows": ["Emmanuel Macron"]}
    assert not anchor.Story([macron], "Macron protest ban", short_kind="protest").subject_shown("protest")
    assert anchor.Story([macron], "Emmanuel Macron", short_kind="death").subject_shown("death")
    assert writer.faceless([macron] * 3, "Macron protest ban", "nw-x", kind="protest")


@pytest.mark.parametrize("reason", [
    "gate: beat 3, 4 name(s) nothing its photo shows (only 51% of the script shows what it says; want 70%)",
    "gate: the title names Tiger Shroff, who has no photo here: title the event, not them"])
def test_the_writers_picture_refusals_back_off(tmp_path, monkeypatch, reason):
    monkeypatch.setattr(ledger, "STATE", tmp_path)
    assert ledger.pictures_reason(reason)
    assert ledger.retry("nw-x", reason)
    at = datetime.fromisoformat(ledger.load("retries", {})["nw-x"]["at"])
    assert not ledger.due("nw-x", at + timedelta(hours=1)) and ledger.due("nw-x", at + timedelta(hours=3))


def test_a_refusal_after_the_script_was_written_takes_its_slot(tmp_path, monkeypatch):
    # 12 scripts in one run: a gate-stage faceless refusal gave its candidate slot back.
    monkeypatch.setattr(ledger, "STATE", tmp_path / "state")
    monkeypatch.setattr(ledger, "set_identity", lambda: None)
    monkeypatch.setattr(cli.learn, "refresh", lambda: None)
    cands = [{"id": f"nw-{i}", "kind": "story", "fame": 1} for i in range(12)]
    monkeypatch.setattr(plan, "watch", lambda: {"candidates": cands, "quakes": [], "trending": cands, "hazards": []})
    monkeypatch.setattr(plan, "lineup", lambda c: (c, []))
    calls = []

    def prepare(c):
        calls.append(c["id"])
        raise cli.Refused("gate: faceless: no free photo shows X or the event itself", written=True)
    monkeypatch.setattr(cli, "prepare", prepare)
    health = cli.run()
    assert len(calls) == cli.MAX_WRITTEN and sum(s.startswith("later nw-") for s in health["steps"]) == 2

    calls.clear()
    monkeypatch.setattr(ledger, "STATE", tmp_path / "state2")

    def before(c):
        calls.append(c["id"])
        raise ValueError(writer.FACELESS + " X or the event itself (only 3 photos of places or things near it)")
    monkeypatch.setattr(cli, "prepare", before)
    cli.run()
    assert len(calls) == 12  # refused before writing: no script cost, no slot


def test_a_dry_run_passes_over_a_bare_wikidata_id(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "STATE", tmp_path / "state")
    monkeypatch.setattr(ledger, "set_identity", lambda: None)
    monkeypatch.setattr(cli.learn, "refresh", lambda: None)
    cands = [{"id": "wk-Q3424313", "kind": "incident", "fame": 1}, {"id": "wk-Q9", "kind": "incident", "fame": 1}]
    monkeypatch.setattr(plan, "watch", lambda: {"candidates": cands, "quakes": [], "trending": cands, "hazards": []})
    monkeypatch.setattr(plan, "lineup", lambda c: (c, []))
    monkeypatch.setenv("STUDIO_DRY_SKIP", "Q3424313")
    calls = []
    monkeypatch.setattr(cli, "prepare", lambda c: calls.append(c["id"]) or (_ for _ in ()).throw(ValueError("x")))
    cli.run(dry=True)
    assert calls == ["wk-Q9"]
