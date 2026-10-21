import json
from datetime import date, datetime, timedelta, timezone

import pytest
import requests

from studio import ledger, net, trends, wiki

SINCE = date(2026, 10, 11)
AT = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
PEOPLE = [{"title": "Nana Patekar", "qid": "Q1"}, {"title": "Cliff Hagan", "qid": "Q2"}]


def _down(since):
    raise requests.ConnectionError("HTTPSConnectionPool(host='query.wikidata.org', port=443): Read timed out.")


def test_a_good_list_is_kept_and_stands_in_when_the_query_service_times_out(monkeypatch):
    monkeypatch.setattr(trends.wiki, "recent_deaths", lambda since: PEOPLE)
    errors = []
    assert trends.recent_deaths(SINCE, errors, now=AT) == PEOPLE and errors == []
    assert ledger.load(trends.DEATHS_CACHE, {})["rows"] == PEOPLE
    monkeypatch.setattr(trends.wiki, "recent_deaths", _down)
    assert trends.recent_deaths(SINCE, errors, now=AT + timedelta(hours=2)) == PEOPLE
    assert "query.wikidata.org" in errors[0] and "used the list from 2.0 h ago, 2 people" in errors[0]


def test_a_list_older_than_three_hours_is_not_used(monkeypatch):
    monkeypatch.setattr(trends.wiki, "recent_deaths", lambda since: PEOPLE)
    trends.recent_deaths(SINCE, [], now=AT)
    monkeypatch.setattr(trends.wiki, "recent_deaths", _down)
    errors = []
    assert trends.recent_deaths(SINCE, errors, now=AT + timedelta(hours=trends.DEATHS_CACHE_H, minutes=1)) == []
    assert errors and "used the list" not in errors[0]


def test_no_list_at_all_is_an_error_and_an_empty_pool(monkeypatch):
    monkeypatch.setattr(trends.wiki, "recent_deaths", _down)
    errors = []
    assert trends.recent_deaths(SINCE, errors, now=AT) == [] and errors[0].startswith("wikidata recent deaths:")


def test_an_empty_answer_never_replaces_the_last_good_list(monkeypatch):
    monkeypatch.setattr(trends.wiki, "recent_deaths", lambda since: PEOPLE)
    trends.recent_deaths(SINCE, [], now=AT)
    monkeypatch.setattr(trends.wiki, "recent_deaths", lambda since: [])
    trends.recent_deaths(SINCE, [], now=AT + timedelta(hours=1))
    assert ledger.load(trends.DEATHS_CACHE, {})["rows"] == PEOPLE


def test_the_deaths_query_retries_with_backoff_and_reads_past_the_services_60_s_limit(monkeypatch):
    calls, waits = [], []
    answer = {"results": {"bindings": [{"article": {"value": "https://en.wikipedia.org/wiki/Nana_Patekar"},
                                        "p": {"value": "http://www.wikidata.org/entity/Q1"}}]}}

    class Resp:
        status_code, content = 200, b""

        def raise_for_status(self):
            pass

    def fake_get(url, params=None, timeout=None, headers=None):
        calls.append(timeout)
        if len(calls) < wiki.SPARQL_TRIES:
            raise requests.ReadTimeout("Read timed out.")
        r = Resp()
        r.content = json.dumps(answer).encode()
        return r

    monkeypatch.setattr(net._session, "get", fake_get)
    monkeypatch.setattr(net.time, "sleep", waits.append)
    assert wiki.recent_deaths(SINCE) == [{"title": "Nana Patekar", "qid": "Q1"}]
    assert calls == [wiki.SPARQL_TIMEOUT] * wiki.SPARQL_TRIES and wiki.SPARQL_TIMEOUT[1] > 60
    assert waits == [2, 8]


def _write_cache(text):
    ledger.STATE.mkdir(parents=True, exist_ok=True)
    (ledger.STATE / f"{trends.DEATHS_CACHE}.json").write_text(text, encoding="utf-8")


@pytest.mark.parametrize("text", [
    '{"at": "2026-10-21T12:00:00+00:00", "rows": [{"title": "Nana', "", "[]", '"rows"', '{"at": 5, "rows": []}',
    '{"at": "not a time", "rows": [{"title": "Nana Patekar", "qid": "Q1"}]}', '{"at": "2026-10-21T12:00:00"}',
    '{"at": "2026-10-21T12:00:00+00:00", "rows": "Nana Patekar"}',
])
def test_a_cut_short_or_malformed_cache_with_the_service_down_is_an_error_not_a_crash(monkeypatch, text):
    _write_cache(text)
    monkeypatch.setattr(trends.wiki, "recent_deaths", _down)
    errors = []
    assert trends.recent_deaths(SINCE, errors, now=AT) == []
    assert any(e.startswith("wikidata recent deaths:") for e in errors)


def test_a_cache_time_without_a_zone_is_read_as_utc(monkeypatch):
    _write_cache(json.dumps({"at": "2026-10-21T12:00:00", "rows": PEOPLE}))
    monkeypatch.setattr(trends.wiki, "recent_deaths", _down)
    errors = []
    assert trends.recent_deaths(SINCE, errors, now=AT + timedelta(hours=1)) == PEOPLE
    assert "used the list from 1.0 h ago" in errors[0]


def test_the_story_pool_survives_a_corrupt_cache_and_an_outage(monkeypatch):
    _write_cache("{")
    monkeypatch.setattr(trends.wiki, "recent_deaths", _down)
    monkeypatch.setattr(trends.wiki, "new_articles", lambda hours: [])
    errors = []
    assert trends.story_pool(AT.date(), errors) == []
    assert any(e.startswith("wikidata recent deaths:") for e in errors)


def test_state_is_written_whole():
    ledger.save("x", {"a": 1})
    assert ledger.load("x", {}) == {"a": 1}
    assert not list(ledger.STATE.glob("*.tmp"))
