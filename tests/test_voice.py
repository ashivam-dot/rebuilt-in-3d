from studio.voice import speakable


def test_clock_times_are_spoken_like_a_newsreader():
    assert speakable("It hit at 9:00 UTC") == "It hit at 9 a.m. UTC"
    assert speakable("at 14:05 UTC") == "at 2 oh 5 p.m. UTC"
    assert speakable("at 00:00 UTC and 12:00 UTC") == "at midnight UTC and noon UTC"


def test_symbols():
    assert speakable("≈8,700 people, 5%") == "about 8,700 people, 5 percent"


def test_kilometres_are_spoken_as_a_unit_without_changing_the_claim():
    assert speakable("A magnitude 7.1 quake struck 6 km west-north-west.") == \
        "A magnitude 7.1 quake struck 6 kilometres west-north-west."
