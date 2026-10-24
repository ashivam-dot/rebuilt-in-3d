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
           "It formed in the Gulf of Mexico and strengthened over very warm water.",
           "Forecasters warned Florida to prepare as the storm turned east toward Tampa Bay.",
           "The National Hurricane Center said the storm would weaken before it reached Florida."]
    source = (" ".join(say) + " Milton reached Category 5 on October 7, 2024.").replace("  ", " ")
    checked = []

    def draft(title):
        return {"title": title, "hook": "Hurricane Milton grew to Category 5",
                "beats": [{"say": s.strip(), "photo": i, "caption": "Category 5"} for i, s in enumerate(say)]}

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
                n = messages[-1]["content"].split("LINES:", 1)[1].strip().count("\n") + 1
                return {"lines": [{"line": i, "verdict": "supported", "quote": ""} for i in range(1, n + 1)]}
            return draft(Fake.title)

    monkeypatch.setattr(writer.llm, "Model", Fake)
    for title in ("How Hurricane Milton Grew to Category 5 in a Day", "Hurricane Milton Reaches Category 5"):
        Fake.title = title
        writer.write("incident", "Hurricane Milton", "It", ["Event: Hurricane Milton."], source,
                     MILTON_PHOTOS)
    curious, plain = (c.split("LINES:", 1)[1] for c in checked)
    assert curious.rstrip().endswith("5. TITLE: How Hurricane Milton Grew to Category 5 in a Day")
    assert "Hurricane Milton Reaches Category 5" not in plain and "\n5. " not in plain


# One photo for each beat: the writer shows every photo once (2026-10-23).
MILTON_PHOTOS = [{"file": f"File:{i}.jpg", "description": "Hurricane Milton, a Category 5 storm over the Gulf of Mexico"}
                 for i in range(4)]
SAY = ["Hurricane Milton grew to Category 5 in a single day over the Gulf of Mexico in October 2024.",
       "It formed in the Gulf of Mexico and strengthened over very warm water.",
       "Forecasters warned Florida to prepare as the storm turned east toward Tampa Bay.",
       "The National Hurricane Center said the storm would weaken before it reached Florida."]
SOURCE = (" ".join(SAY) + " Milton reached Category 5 on October 7, 2024.").replace("  ", " ")


def checker(monkeypatch, title_verdict, asked=None):
    """A fake model whose drafts always carry the curiosity title and whose checker supports every beat, giving the
    title line `title_verdict` (None: the checker leaves the title out)."""
    asked = asked if asked is not None else []

    class Fake:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def chat(self, messages, schema=None, **kw):
            asked.append((schema, messages[-1]["content"]))
            if schema is writer.CHECK_SCHEMA:
                rows = [{"line": i, "verdict": "supported", "quote": ""} for i in range(1, len(SAY) + 1)]
                if title_verdict:
                    rows.append({"line": len(SAY) + 1, "verdict": title_verdict, "quote": "",
                                 "why": "no source says in a day"})
                return {"lines": rows}
            if schema is writer.RECHECK_SCHEMA:
                return {"supported": False, "why": "not stated"}
            return {"title": "How Hurricane Milton Grew to Category 5 in a Day",
                    "hook": "Hurricane Milton grew to Category 5",
                    "beats": [{"say": x.strip(), "photo": i, "caption": "Category 5"} for i, x in enumerate(SAY)]}

    monkeypatch.setattr(writer.llm, "Model", Fake)
    return asked


def test_a_title_flagged_on_the_last_attempt_falls_back_to_the_plain_title(monkeypatch):
    """Every beat is supported and only the curiosity title's claim is not: the story keeps its beats under the plain
    fallback title instead of failing "no draft passed the fact checks"."""
    asked = checker(monkeypatch, "partly")
    draft, log = writer.write("incident", "Hurricane Milton", "It", ["Event: Hurricane Milton."], SOURCE,
                              MILTON_PHOTOS)
    assert draft["title"] == "Hurricane Milton: what happened" == writer.plain_title("incident", "Hurricane Milton")
    assert [b["say"] for b in draft["beats"]] == [x.strip() for x in SAY]
    assert len(log) == 3 and all(p.startswith("the title (How Hurricane Milton") for p in log[-1]["problems"])
    # The rewrite feedback named the title, not "line 5".
    rewrites = [c for schema, c in asked if "beats" in schema.get("properties", {}) and "Fix these problems" in c]
    assert len(rewrites) == 2 and all("- the title (How" in c and "line 5" not in c for c in rewrites)
    assert writer.plain_title("death", "Nana Patekar") == "Remembering Nana Patekar"
    assert writer.plain_title("incident", "Cyclone Montha", {"part": 2}) == "Part 2: Cyclone Montha: what happened"


def test_a_title_the_checker_leaves_out_counts_as_unsupported(monkeypatch):
    checker(monkeypatch, None)
    draft, log = writer.write("incident", "Hurricane Milton", "It", ["Event: Hurricane Milton."], SOURCE,
                              MILTON_PHOTOS)
    assert draft["title"] == "Hurricane Milton: what happened"
    assert log and "no verdict" in log[0]["problems"][0] and log[0]["problems"][0].startswith("the title (")


def test_a_supported_curiosity_title_is_kept(monkeypatch):
    checker(monkeypatch, "supported")
    draft, log = writer.write("incident", "Hurricane Milton", "It", ["Event: Hurricane Milton."], SOURCE,
                              MILTON_PHOTOS)
    assert draft["title"] == "How Hurricane Milton Grew to Category 5 in a Day" and log == []


def test_a_flagged_beat_still_costs_the_story_on_the_last_attempt(monkeypatch):
    """The fallback only ever replaces the title: an unsupported beat fails the story as before."""
    checker(monkeypatch, "partly")
    real = writer.check_verdict

    def with_beat(verdict, lines, ground):
        return real(verdict, lines, ground) | {1: "line 1 (Hurricane Milton grew): partly: not stated"}

    monkeypatch.setattr(writer, "check_verdict", with_beat)
    with pytest.raises(ValueError, match="no draft passed the fact checks"):
        writer.write("incident", "Hurricane Milton", "It", ["Event: Hurricane Milton."], SOURCE,
                     MILTON_PHOTOS)


@pytest.mark.parametrize("title", [
    "Hurricane Milton: Why Tampa Bay Was Spared", "Tigray War: How Famine Followed the Siege",
    "Hurricane Milton Grew to Category 5 Because of Warm Water", "Kakinada Flooded Due to Cyclone Montha",
])
def test_a_name_first_causal_title_is_still_sent_to_the_evidence_check(title):
    """The pre-push review (2026-10-22): these claimed a cause and skipped the check."""
    assert writer.CURIOUS.search(title)


@pytest.mark.parametrize("title", ["Nana Patekar, Krantiveer Star, Dies at 75", "CFB Wainwright Fire Kills Two Soldiers"])
def test_a_plain_title_is_not_a_causal_claim(title):
    assert not writer.CURIOUS.search(title)
