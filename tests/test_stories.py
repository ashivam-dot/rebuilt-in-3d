from studio import render, stories, wiki


def amount_claims(*values, preferred=None):
    rows = []
    for v in values:
        rows.append({"rank": "preferred" if v == preferred else "normal",
                     "mainsnak": {"datavalue": {"value": {"amount": f"+{v}"}}}})
    return rows


def test_toll_needs_both_sources_to_agree():
    ent = {"claims": {"P1120": amount_claims(269, 229, 260)}}
    assert stories.agreed("260", ent, "P1120", need_wikidata=True) == 260
    assert stories.agreed("241 (plus 19 on the ground)", ent, "P1120", need_wikidata=True) is None
    assert stories.agreed("6+", {"claims": {"P1339": amount_claims(6)}}, "P1339", need_wikidata=True) is None
    assert stories.agreed("At least 12", {"claims": {"P1120": amount_claims(12)}}, "P1120", need_wikidata=True) is None
    assert stories.agreed("180", {"claims": {}}, "P1120", need_wikidata=True) is None
    assert stories.agreed("180", {"claims": {}}, "P1132", need_wikidata=False) == 180


def test_single_number_prefers_preferred_rank():
    assert wiki.single_number({"claims": {"P1120": amount_claims(269, 260, preferred=260)}}, "P1120") == 260
    assert wiki.single_number({"claims": {"P1120": amount_claims(269, 260)}}, "P1120") is None


def test_leading_number():
    assert wiki.leading_number("260 (241 on board, 19 on ground)") == 260
    assert wiki.leading_number("1,234") == 1234
    assert wiki.leading_number("Unknown") is None


def test_place_names():
    assert stories.city_of("Dubai International Airport, Dubai, United Arab Emirates") == "Dubai"
    assert stories.city_of("Newark, New Jersey, U.S.") == "Newark"
    assert stories.place_words("Los Angeles, California, U.S.") == "Los Angeles, California"


def test_speculative_summaries_are_not_read_out():
    assert stories.SPECULATIVE.search("Suspected hijacking, terrorism, and suicide attempt; under investigation")
    assert not stories.SPECULATIVE.search("Runway excursion on landing")


def test_route_is_clipped_to_the_map():
    g = {"xmin": -100, "xmax": 100, "zmin": -100, "zmax": 100}
    a, b = render._clip([-300, 0], [50, 0], g)
    assert a == [-100, 0] and b == [50, 0]
    assert render._clip([200, 200], [300, 300], g) is None
