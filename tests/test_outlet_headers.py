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


def test_ndtv_and_france24_get_full_browser_headers():
    for url in ("https://www.ndtv.com/world-news/a-1", "https://ndtv.in/india/b-2",
                "https://www.france24.com/en/europe/20261013-c"):
        headers = outlets._headers(url)
        assert headers["Accept"].startswith("text/html") and headers["Accept-Language"]
    owners = {o["key"]: o["owner"] for o in outlets.OUTLETS}
    assert owners["ndtv"] == owners["ndtv-hi"] != owners["france24"]


def test_other_outlets_keep_the_desk_user_agent():
    assert outlets._headers("https://feeds.bbci.co.uk/news/world/rss.xml") is None
    assert outlets._headers("https://notpib.gov.in.example.com/rss") is None
    assert outlets._headers("https://notndtv.in/rss") is None
