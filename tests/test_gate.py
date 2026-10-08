from dataclasses import replace
from pathlib import Path

import pytest

from studio import gate
from studio.spec import Beat, Short

FIXTURE = Path(__file__).parent / "fixtures" / "eq-us6000u0xi.json"


@pytest.fixture
def short() -> Short:
    return Short.load(FIXTURE)


def test_pilot_passes(short):
    assert gate.check(short) == []


def test_unsourced_number_fails(short):
    beats = short.beats + [Beat("At least 4,321 homes were damaged.", "outro")]
    problems = gate.check(replace(short, beats=beats))
    assert any("4321" in p for p in problems)


def test_magnitude_and_3d_are_not_counted_as_claims():
    assert gate.numbers("How the M6.3 quake ruptured, in 3D") == ["6.3"]
    assert gate.numbers("about 8,700 people at 9:00 UTC") == ["8700", "9:00"]


@pytest.mark.parametrize("bad", ["SHOCKING quake footage", "Breaking: the quake in Vanuatu explained",
                                 "The horrific Vanuatu quake, explained"])
def test_sensational_titles_fail(short, bad):
    assert gate.check(replace(short, title=bad))


def test_emoji_and_shouting_fail(short):
    assert any("emoji" in p for p in gate.check(replace(short, title="How the Vanuatu quake ruptured \U0001F525")))
    assert any("capitals" in p for p in gate.check(replace(short, title="How the VANUATU quake ruptured, in 3D")))


def test_acronyms_are_not_shouting(short):
    assert not [p for p in gate.check(replace(short, title="What USGS PAGER says about the quake")) if "capitals" in p]


def test_sources_must_be_https(short):
    assert any("sources" in p for p in gate.check(replace(short, sources=["http://example.com"])))


def test_channel_mix_limits_loss_runs():
    assert gate.channel_mix([True, True], True)
    assert gate.channel_mix([True, True], False) is None
    assert gate.channel_mix([False, True], True) is None
    assert gate.channel_mix([], True) is None
