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
