from datetime import datetime, timezone

from studio import plan, wiki, youtube

NOW = datetime(2026, 10, 16, 19, 30, tzinfo=timezone.utc)
TOLD = [{"id": "wk-Q141695384", "published_at": "2026-10-14T02:05:01+00:00",
         "article": "October 2026 attacks on Saudi airports"}]
BACK = {"id": "wp-October_2026_Houthi_attacks_on_Saudi_Arabian_airports",
        "title": "October 2026 Houthi attacks on Saudi Arabian airports"}


def test_a_story_whose_article_moved_is_not_told_again(monkeypatch):
    monkeypatch.setattr(wiki, "page_info", lambda titles: {
        "October 2026 attacks on Saudi airports": {"title": BACK["title"], "qid": None}})
    moved = plan.renamed(TOLD, NOW)
    assert moved == {"October 2026 attacks on Saudi airports": BACK["title"]}
    assert plan.told_before(BACK, TOLD, NOW, moved)
    assert not plan.told_before(BACK, TOLD, NOW, {})  # without the redirect it looked like a new story
    assert not plan.told_before({"id": "wp-2026_Kerala_boat_accident", "title": "2026 Kerala boat accident"},
                                TOLD, NOW, moved)


def test_wikipedia_down_means_no_renames_known(monkeypatch):
    def down(titles):
        raise ConnectionError("offline")

    monkeypatch.setattr(wiki, "page_info", down)
    assert plan.renamed(TOLD, NOW) == {}


def test_the_repeat_is_taken_down():
    assert "P3_BBUFzurk" in youtube.RETRACTED
