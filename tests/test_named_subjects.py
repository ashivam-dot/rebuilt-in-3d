"""Owner review 2026-10-16: "A Growing Shadow Over the Black Sea" (a tanker hit by drones) was named "Black", and its
photos were the colour's: Malevich's Black Square and the M87 black hole."""
from studio import outlets, wiki, writer
from tests.test_outlets import NOW, item

BLACK_SEA = [("bbc-world", "Drone attack hits tanker in Black Sea, seven crew missing", 6),
             ("guardian", "Drone strikes on Black Sea tankers leave seven crew missing", 4),
             ("euronews", "Tanker Wine Trader hit by drone in Black Sea as search for crew continues", 2)]


def test_a_story_is_named_by_the_whole_name_its_headlines_write():
    [story] = outlets.stories([item(k, t, h) for k, t, h in BLACK_SEA], NOW)
    assert story["name"] == "Black Sea" and story["id"].endswith("-black-sea-strike")


def test_a_title_case_headline_does_not_make_a_long_name():
    rows = [item("bbc-world", "Drone Attack Hits Tanker In Black Sea, Seven Crew Missing", 6),
            item("guardian", "Drone strikes on Black Sea tankers leave seven crew missing", 4),
            item("euronews", "Tanker hit by drone in Black Sea as search for crew continues", 2)]
    [story] = outlets.stories(rows, NOW)
    assert story["name"] == "Black Sea"


def test_a_one_word_name_and_the_phrase_it_heads_are_one_story():
    assert outlets.same_story("nw-20261014-black-strike", "nw-20261014-black-sea-strike")
    assert not outlets.same_story("nw-20261014-black-strike", "nw-20261014-black-sea-attack")
    assert not outlets.same_story("nw-20261014-kyiv-strike", "nw-20261014-kharkiv-strike")


def _claim(value):
    return {"mainsnak": {"datavalue": {"value": value}}}


def test_a_subject_is_a_made_thing_never_an_idea(monkeypatch):
    colour = {"claims": {"P31": [_claim({"id": "Q1075"})], "P18": [_claim("Color icon black.svg")]}}
    company = {"claims": {"P31": [_claim({"id": "Q4830453"})], "P571": [_claim({"time": "+1933-00-00T00:00:00Z"})],
                          "P159": [_claim({"id": "Q268915"})]}}
    ents = {"Black": ("Q23445", colour), "Aramco": ("Q679322", company)}
    monkeypatch.setattr(wiki, "search", lambda name: "Saudi Aramco" if name == "Aramco" else name)
    monkeypatch.setattr(wiki, "page_info", lambda titles: {t: {"qid": ents["Aramco" if "Aramco" in t else t][0]}
                                                          for t in titles})
    monkeypatch.setattr(wiki, "entities", lambda qids: {q: e for q, e in ents.values() if q in qids})
    assert writer.story_subject("Black") is None
    assert writer.story_subject("Aramco") == "Q679322"
