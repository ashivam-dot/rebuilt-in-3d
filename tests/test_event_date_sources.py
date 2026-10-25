from datetime import date

import pytest

from studio import stories, wiki


def test_a_real_start_date_template_survives_plain_text_stripping(monkeypatch):
    monkeypatch.setattr(wiki, 'wikitext', lambda _: '{{Infobox civilian attack|date={{start date|2026|10|25}}}}')
    _, plain, raw = wiki.infobox('Example')
    assert 'date' not in plain
    assert stories.infobox_date(plain, raw) == date(2026, 10, 25)


@pytest.mark.parametrize('value, expected', [
    ('{{start date|df=yes|2026|10|25}}', date(2026, 10, 25)),
    ('{{Start_date_and_age|2026|2|28}}', date(2026, 2, 28)),
    ('{{start date|2026|2|30}}', None),
    ('{{start date|2026|10}}', None),
    ('{{start date|2026|10|unknown}}', None),
    ('{{cite news|date=2026-10-25}}', None),
    ('{{start date|2026|10|24}} and {{start date|2026|10|25}}', None),
])
def test_only_one_complete_valid_start_date_can_supply_a_missing_plain_date(value, expected):
    assert stories.infobox_date({}, {'date': value}) == expected


def test_a_present_but_imprecise_plain_date_is_not_overridden():
    assert stories.infobox_date({'date': 'October 2026'}, {'date': '{{start date|2026|10|25}}'}) is None


def test_conflicting_current_article_lead_is_held():
    with pytest.raises(ValueError, match='event date conflicts'):
        stories.check_lead_event_date(date(2026, 10, 25),
            'On October 24, 2026, a mass shooting occurred near a university campus.')
    stories.check_lead_event_date(date(2026, 10, 24), 'On October 24, 2026, a shooting occurred.')
    stories.check_lead_event_date(date(2026, 10, 24), 'On 24 October 2026, a shooting occurred.')
    stories.check_lead_event_date(date(2026, 10, 24), 'The date of this incident remains unclear.')


@pytest.mark.parametrize('reason', [
    'gate: neither Wikidata nor the infobox gives a date for this event',
    'gate: event date conflicts between the structured source (2026-10-25) and article lead (2026-10-24)',
])
def test_an_incomplete_or_conflicting_date_retries_without_producing_media(tmp_path, monkeypatch, reason):
    from studio import cli, ledger, plan, youtube

    monkeypatch.setattr(ledger, 'STATE', tmp_path)
    monkeypatch.setattr(ledger, 'set_identity', lambda: None)
    monkeypatch.setattr(cli.learn, 'refresh', lambda: None)
    monkeypatch.setattr(youtube, 'client', lambda: (_ for _ in ()).throw(RuntimeError('offline')))
    candidate = {'id': 'wp-date-test', 'kind': 'incident', 'fame': 1}
    monkeypatch.setattr(plan, 'watch', lambda: {'candidates': [candidate], 'quakes': [],
                                             'trending': [candidate], 'hazards': []})
    monkeypatch.setattr(plan, 'lineup', lambda c: (c, []))
    monkeypatch.setattr(cli, 'prepare', lambda c: (_ for _ in ()).throw(ValueError(reason)))
    monkeypatch.setattr(cli, 'make', lambda *a: pytest.fail('a date refusal reached media production'))
    cli.run()
    assert ledger.load('skipped', {}) == {}
    assert ledger.load('retries', {})[candidate['id']]['count'] == 1
    for _ in range(5):
        ledger.retry(candidate['id'], reason)
    assert ledger.is_done(candidate['id'])
