"""Breaking stories reach the channel fast (2026-10-23): a brand-new article is told from the reporting once enough
independent owners report the event, however few headlines name the article, and one story's article fetches never
starve the next story's. Every feed, article and API answer here is a fixture; nothing touches the network."""
from datetime import datetime, timedelta, timezone

from studio import cli, ledger, outlets, trends, writer
from tests.test_outlets import NOW, item

KARAK = "2026 Karak church shooting"


def test_a_young_article_named_by_one_headline_is_told_from_every_owners_reporting():
    # Run 39985026749: only DW's headline named Karak; five other owners wrote "church in Jordan".
    rows = [item("dw", "Jordan: Karak church shooting leaves 7 dead, dozens injured", 2) | {"matched": KARAK},
            item("bbc-world", "Gunmen open fire at church in Jordan, killing at least six", 3),
            item("aljazeera", "At least seven killed after gunmen open fire at church in Jordan", 2.5),
            item("cbs-world", "Gunmen kill at least 7 in attack on Jordan church, authorities say", 2)]
    [waiting] = outlets.stories(rows, NOW, known=[KARAK])
    assert waiting["article"] is None and "Deutsche Welle" not in waiting["owners"]
    [story] = outlets.stories(rows, NOW, known=[KARAK], young=[KARAK])
    assert story["article"] == KARAK and len(story["owners"]) == 4
    # Without NEW_OWNERS independent owners there is nothing to tell it from: the article waits out its 6 hours.
    assert outlets.stories(rows[:2], NOW, known=[KARAK], young=[KARAK]) == []


def test_young_articles_need_an_hour(monkeypatch):
    made = {KARAK: 2, "Just written": 0.4, "Settled": 7}
    monkeypatch.setattr(trends.wiki, "created", lambda t: datetime.now(timezone.utc) - timedelta(hours=made[t]))
    cands = [{"kind": "incident", "title": t, "owners": ["Deutsche Welle"]} for t in made]
    assert trends.young_articles(cands + [{"kind": "death", "title": KARAK}]) == [KARAK]


def test_one_storys_fetches_never_starve_the_next(monkeypatch):
    # Run 39979592470: three stories spent the run's 12 fetches, then Paris's four readable articles went unread.
    fetched = []
    monkeypatch.setattr(outlets, "_extract", lambda url: fetched.append(url) or ("Police said a gunman opened fire. "
                                                                                 + url + " ") * 20)
    keys = ("bbc-world", "dw", "aljazeera", "cbs-world", "nbc-world", "fox-world", "independent", "abc-au-world")
    for n in range(5):
        rows = [item(k, f"Story {n} shooting", url=f"https://{k}.example/{n}") for k in keys]
        assert len(outlets.reporting(rows)) == outlets.REPORTS
    paris = [item(k, "Shooting in Paris suburb", url=f"https://{k}.example/paris") for k in keys[:3]]
    assert len(outlets.owners(outlets.reporting(paris))) == 3


def test_a_storys_reads_stop_at_story_texts(monkeypatch):
    monkeypatch.setattr(outlets, "_extract", lambda url: None)  # nothing readable: paywalls, video pages
    keys = ("bbc-world", "dw", "aljazeera", "cbs-world", "nbc-world", "fox-world", "independent", "abc-au-world")
    assert outlets.reporting([item(k, "Shooting", url=f"https://{k}.example/x") for k in keys]) == []
    assert outlets._fetched == outlets.STORY_TEXTS


def test_unread_reporting_is_retried_and_an_old_skip_for_it_comes_back():
    unread = "gate: fewer than 2 independent outlets' articles about Paris could be read"
    assert any(m in unread for m in cli.RETRYABLE)
    ledger.skip("nw-20261023-paris-attack", unread)
    assert not ledger.is_done("nw-20261023-paris-attack")
    ledger.skip("nw-20261023-paris-attack", "gave up after 6 tries: " + unread)
    assert ledger.is_done("nw-20261023-paris-attack")
