"""A title-case incident noun must not replace the reported place as subject."""
from datetime import datetime, timedelta, timezone

from studio import outlets


NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)


def rows(titles):
    keys = ['france24', 'independent', 'scmp']
    sources = {o['key']: o for o in outlets.OUTLETS}
    return [{'title': title, 'url': f'https://example.org/{key}',
             'outlet': sources[key]['name'], 'owner': sources[key]['owner'],
             'group': sources[key]['group'], 'lang': 'en', 'geo': 'world',
             'at': (NOW - timedelta(hours=2)).isoformat(), 'summary': ''}
            for key, title in zip(keys, titles)]


def test_current_protest_headlines_keep_the_reported_city():
    items = rows([
        'France: Clashes erupt as protests sweep across cities',
        'More than 1000 arrested as protesters clash with police in Paris as demonstrations turn hostile across France',
        'Clashes flare at Paris protests as more than 400,000 march across France'])
    got = outlets.stories(items, NOW)
    assert len(got) == 1 and got[0]['name'] == 'Paris'
    assert got[0]['id'] == 'nw-20261025-paris-protest'
    assert len(got[0]['owners']) == 3


def test_clashes_without_a_distinct_subject_do_not_create_a_story():
    items = rows([
        'France: Clashes erupt as protests sweep across cities',
        'France: Clashes erupt across cities as protests continue',
        'Clashes erupt across France cities as protests continue'])
    assert outlets.stories(items, NOW) == []
