from studio import outlets


def test_pib_gets_a_browser_user_agent_and_the_english_feed():
    pib = next(o for o in outlets.OUTLETS if o["key"] == "pib")
    assert "Lang=1" in pib["feed"] and "reg=3" in pib["feed"]
    assert outlets._headers(pib["feed"])["User-Agent"].startswith("Mozilla/5.0")
    assert outlets._headers("https://www.pib.gov.in/PressReleasePage.aspx?PRID=1")


def test_an_undated_feed_counts_its_items_as_current_only_when_marked():
    from datetime import datetime, timezone

    now = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
    body = "<rss><channel><item><title>Relief for flood-hit districts</title><link>https://pib.gov.in/P?PRID=1</link></item></channel></rss>"
    pib = next(o for o in outlets.OUTLETS if o["key"] == "pib")
    assert [i["at"] for i in outlets.parse(body, pib, now)] == [now.isoformat()]
    bbc = next(o for o in outlets.OUTLETS if o["key"] == "bbc-world")
    assert outlets.parse(body, bbc, now) == []


def test_other_outlets_keep_the_desk_user_agent():
    assert outlets._headers("https://feeds.bbci.co.uk/news/world/rss.xml") is None
    assert outlets._headers("https://notpib.gov.in.example.com/rss") is None
