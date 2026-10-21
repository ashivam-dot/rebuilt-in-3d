"""Curiosity framing in titles, where the sources state the cause or the outcome (2026-10-22): "How/Why <specific
thing> <specific outcome>", "<X> Exists Because of <Y>". The existing title rules all still hold."""
import pytest

from studio import gate, writer


@pytest.mark.parametrize("title, name", [
    ("How Hurricane Milton Grew to Category 5 in a Day", "Hurricane Milton"),
    ("Why the Tigray War Displaced Millions", "Tigray War"),
    ("How the Multan Train Derailment Stopped a Line", "2026 Multan train derailment"),
    ("Part 2: How Cyclone Montha Flooded Kakinada", "Cyclone Montha"),
    ("Kakinada's Sea Wall Exists Because of Cyclone Hudhud", "Kakinada"),
    ("Why Nana Patekar's Roar Won Krantiveer an Award", "Nana Patekar"),
])
def test_a_factual_curiosity_title_passes_the_title_rules(title, name):
    assert writer.title_problems(title, name, ["How Typhoon Ragasa Hit Hong Kong", "Why Paris Marched"]) == []
    assert writer.CURIOUS.search(title)
    assert 20 <= len(title) <= 70 and not gate.banned_word(title)


def test_the_title_rules_still_hold_for_curiosity_titles():
    recent = ["How Hurricane Melissa Hit Jamaica"]
    # The opening words of another story's recent title.
    assert any("starts like the recent title" in p for p in writer.title_problems(
        "How Hurricane Melissa's Rains Reached Cuba", "Cuba floods", recent))
    # The name's key words still within the first 4 words.
    assert any("must lead with" in p for p in writer.title_problems(
        "Why a Whole Coast Feared the Storm Called Montha", "Cyclone Montha", []))
    # Template openers stay banned.
    assert any("template" in p for p in writer.title_problems("The Path of How Hurricane Milton Grew",
                                                              "Hurricane Milton", []))


@pytest.mark.parametrize("title", [
    "Why Hurricane Milton Grew So Fast?", "Hurricane Milton: What Happened Next",
    "Hurricane Milton and the Real Reason It Grew", "Here's Why Hurricane Milton Grew",
])
def test_a_question_or_vague_tease_is_clickbait(title):
    assert any("teases" in p for p in writer.title_problems(title, "Hurricane Milton", []))


def test_the_brief_offers_curiosity_framing_only_on_the_sources_facts():
    assert "How Hurricane Milton Grew to Category 5 in a Day" in writer.RULES
    assert "Exists Because of" in writer.RULES and "under investigation" in writer.RULES
    assert "factual, no clickbait" in writer.RULES


def test_a_curiosity_titles_claim_is_fact_checked_with_the_beats(monkeypatch):
    """A How/Why title states a cause or an outcome, so the evidence check reads it as one more line."""
    say = ["Hurricane Milton grew to Category 5 in a single day over the Gulf of Mexico in October 2024.",
           "It formed in the Gulf of Mexico and strengthened over very warm water. " * 4,
           "Forecasters warned Florida to prepare as the storm turned east toward Tampa Bay. " * 3,
           "The National Hurricane Center said the storm would weaken before it reached Florida."]
    source = (" ".join(say) + " Milton reached Category 5 on October 7, 2024.").replace("  ", " ")
    checked = []

    def draft(title):
        return {"title": title, "hook": "Hurricane Milton grew to Category 5",
                "beats": [{"say": s.strip(), "photo": 0, "caption": "Category 5"} for s in say]}

    class Fake:
        title = ""

        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def chat(self, messages, schema=None, **kw):
            if schema is writer.CHECK_SCHEMA:
                checked.append(messages[-1]["content"])
                return {"lines": []}
            return draft(Fake.title)

    monkeypatch.setattr(writer.llm, "Model", Fake)
    for title in ("How Hurricane Milton Grew to Category 5 in a Day", "Hurricane Milton Reaches Category 5"):
        Fake.title = title
        writer.write("incident", "Hurricane Milton", "It", ["Event: Hurricane Milton."], source,
                     [{"file": "File:0.jpg", "description": ""}])
    curious, plain = (c.split("LINES:", 1)[1] for c in checked)
    assert curious.rstrip().endswith("5. How Hurricane Milton Grew to Category 5 in a Day")
    assert "Hurricane Milton Reaches Category 5" not in plain and "\n5. " not in plain
