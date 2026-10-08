from studio.voice import speakable


def test_clock_times_are_spoken_like_a_newsreader():
    assert speakable("It hit at 9:00 UTC") == "It hit at 9 a.m. UTC"
    assert speakable("at 14:05 UTC") == "at 2 oh 5 p.m. UTC"
    assert speakable("at 00:00 UTC and 12:00 UTC") == "at midnight UTC and noon UTC"


def test_symbols():
    assert speakable("≈8,700 people, 5%") == "about 8,700 people, 5 percent"
