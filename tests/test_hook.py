"""Beat 1 opens on the story, the first frame shows a claim from it (the 2026-10-20 hook plan), and titles are not
templates."""
import pytest

from studio import cli, compose, gate, ledger, writer
from studio.spec import Beat, Fact, Short


@pytest.mark.parametrize("say", [
    "On 8 October 2026, Nana Patekar died at his home in Goa, aged 75.",
    "On Monday, a train derailed near Multan and ten coaches left the track.",
    "In 2026, the Multan train derailment became the deadliest of the year.",
    "Early on Tuesday morning, Hurricane Rachel made landfall.",
    "Last week, protesters filled the streets of Paris.",
    "Today, the world remembers Nana Patekar and his roar.",
    "12 October was the day Hurricane Rachel turned north.",
])
def test_a_dateline_opener_is_rewritten(say):
    assert any("opens on a date or time" in p for p in writer.hook_problems(say, "Nana Patekar"))


@pytest.mark.parametrize("say, name", [
    ("Nana Patekar's roar in Krantiveer won him the National Film Award for Best Actor.", "Nana Patekar"),
    ("A passenger train derailed near Multan, and ten coaches left the track.", "2026 Multan train derailment"),
    ("Hurricane Rachel reached 120 mph winds before it turned toward Mexico.", "Hurricane Rachel"),
    ("In Paris, the protests over pensions reached their 17th day.", "2026 Paris pension protests"),
])
def test_an_opener_on_the_story_passes(say, name):
    assert writer.hook_problems(say, name) == []


def test_the_name_must_start_within_the_first_four_words():
    late = "Born in a small coastal town, and raised by his mother, Nana Patekar became a star."
    assert any("within its first 4 words" in p for p in writer.hook_problems(late, "Nana Patekar"))
    assert writer.hook_problems("Actor Nana Patekar won the National Film Award for Krantiveer.", "Nana Patekar") == []


@pytest.mark.parametrize("say", [
    "Nana Patekar has died.", "Nana Patekar has died at 75, in his home in Goa.",
    "Nana Patekar, the actor, has died at 75.", "Nana Patekar died on Wednesday, aged 75.",
])
def test_has_died_is_never_the_whole_opener(say):
    assert any("has died" in p for p in writer.hook_problems(say, "Nana Patekar"))


def test_the_death_may_follow_the_striking_fact():
    say = "Nana Patekar, whose roar in Krantiveer won a National Film Award, has died at 75."
    assert writer.hook_problems(say, "Nana Patekar") == []
    # An incident's toll is its striking fact, not a tribute's "has died" opener.
    assert writer.hook_problems("A teacher at an Aubagne school has been killed.", "2026 Aubagne school shooting") == []


def _draft(say, title="Nana Patekar, Krantiveer Star, Dies at 75", hook="Nana Patekar's roar in Krantiveer"):
    return {"title": title, "hook": hook, "beats": [{"say": say, "photo": 0, "caption": "1994"}]}


def test_the_validator_rewrites_a_dateline_and_a_bad_title():
    photos = [{"file": "File:0.jpg", "description": ""}]
    draft = _draft("On 8 October 2026, Nana Patekar died at his home in Goa.", title="The Legacy of Nana Patekar")
    problems = writer._validate(draft, photos, "Nana Patekar", "Nana Patekar died on 8 October 2026 at his home in "
                                "Goa.", [], recent=[])
    assert any("opens on a date or time" in p for p in problems)
    assert any("template 'The Legacy Of'" in p for p in problems)


def test_a_hook_problem_left_after_three_drafts_is_retried_next_run():
    assert any(m in "gate: no draft passed the fact checks: beat 1 opens on a date or time" for m in cli.RETRYABLE)


def test_the_hook_claim_is_said_in_the_hook_and_checked_like_the_script():
    photos = [{"file": "File:0.jpg", "description": ""}]
    say = "Nana Patekar's roar in Krantiveer won him the National Film Award."
    ground = "Nana Patekar won the National Film Award for Krantiveer (1994)."
    draft = _draft(say, hook="Shocking roar of 1995")
    problems = writer._validate(draft, photos, "Nana Patekar", ground, [], recent=[])
    assert any("the hook uses the banned word 'shocking'" in p for p in problems)
    assert any("1995" in p for p in problems)


def test_the_claim_on_screen_comes_from_beat_1():
    say = "Nana Patekar's roar in Krantiveer won him the National Film Award."
    good = _draft(say, hook="Nana Patekar's roar in Krantiveer")
    assert writer.hook_claim(good) == "Nana Patekar's roar in Krantiveer" and writer.hook_text_problems(good) == []
    # Words beat 1 does not say, hype, a question or the wrong length are rewritten on an early draft; a last
    # draft falls back to beat 1's opening clause, or to no claim when that clause would be cut mid-way.
    for bad in ("A legend is gone", "Shocking roar of Nana Patekar", "Who was Nana Patekar?", "Patekar",
                "Nana Patekar's roar in Krantiveer won him the award", "Nana Patekar won!"):
        assert writer.hook_text_problems(_draft(say, hook=bad)), bad
        assert writer.hook_claim(_draft(say, hook=bad)) == "", bad
    clause = "Hurricane Rachel, the strongest storm of the season, reached 120 mph."
    assert writer.hook_claim(_draft(clause, hook="")) == ""
    assert writer.hook_claim(_draft("Ten coaches left the track, officials in Multan said.", hook="")) == \
        "Ten coaches left the track"
    assert writer.hook_claim(_draft("Two dead.", hook="")) == ""


def _short(hook, kind="death"):
    facts = [Fact("name", "Nana Patekar", "https://x"), Fact("born", "1 January 1951", "https://x", ["1951"]),
             Fact("died", "8 October 2026", "https://x", ["2026"])]
    return Short(id="wk-Q1", kind=kind, title="Nana Patekar, Krantiveer Star, Dies at 75",
                 beats=[Beat("Nana Patekar's roar.", "photo:0", {"big": "1994", "small": ""})], facts=facts,
                 sources=["https://x"], loss=False, scene={"template": "story", "hook": hook, "photos": []})


def test_the_first_frame_shows_the_claim_not_the_name_and_dates():
    assert compose.hook_text(_short("Krantiveer won the National Film Award")) == (
        "Krantiveer won the National Film Award", "Nana Patekar")
    assert compose.hook_text(_short("Nana Patekar's roar in Krantiveer")) == ("Nana Patekar's roar in Krantiveer", "")
    # A Short made before the claim existed keeps the old card.
    assert compose.hook_text(_short("")) == ("Nana Patekar", "1951 – 2026")
    assert compose.hook_text(_short("", kind="incident")) == ("Nana Patekar", "1994")


def test_a_long_claim_breaks_onto_two_lines_and_fits_the_frame():
    def fits(line, size):
        return compose._font("Anton-Regular.ttf", size).getlength(line) <= compose.W - 120

    assert compose.hook_lines("Ten coaches left the track", fits) == ["TEN COACHES", "LEFT THE TRACK"]
    assert compose.hook_lines("120 mph", fits) == ["120 MPH"]
    _, alpha = compose._hook_layer("Nana Patekar's roar in Krantiveer", "Nana Patekar", (255, 200, 0))
    assert alpha.shape[1] <= compose.W


def test_the_publish_gate_checks_the_claim():
    short = _short("A horrific roar in 1999")
    problems = gate.check(short)
    assert "hook: banned wording 'horrific'" in problems
    assert "hook: the number 1999 isn't backed by any sourced fact" in problems


@pytest.mark.parametrize("title", [
    "The Legacy of Mike Ditka: A Life of Grit and Football", "A Tribute to Coach Chuck Amato",
    "The Life and Legacy of Arsenal's Ken Friar", "The Path of Hurricane Isaias", "Part 2: The Path of Hurricane Trudy",
])
def test_template_openers_are_banned(title):
    assert any("template" in p for p in writer.title_problems(title, "Mike Ditka", []))


def test_a_title_opening_like_a_recent_one_is_rewritten():
    recent = ["Hurricane Rachel Turns North Toward Mexico", "Part 1: Cockroach Janta Party Takes Delhi"]
    assert any("starts like the recent title" in p for p in
               writer.title_problems("Hurricane Rachel Turns Toward Baja California", "Hurricane Rachel", recent))
    assert any("starts like the recent title" in p for p in
               writer.title_problems("Part 2: Cockroach Janta Party Meets the CEC", "Cockroach Janta Party", recent))
    assert writer.title_problems("Hurricane Rachel Makes Landfall in Baja California", "Hurricane Rachel",
                                 recent) == []


def test_the_name_or_place_leads_the_title():
    assert any("must lead with" in p for p in writer.title_problems(
        "A Day of Mourning: The CFB Wainwright Fire", "2026 CFB Wainwright fire", []))
    assert writer.title_problems("CFB Wainwright Fire Kills Two Soldiers", "2026 CFB Wainwright fire", []) == []
    assert writer.title_problems("Nana Patekar, Krantiveer Star, Dies at 75", "Nana Patekar", []) == []


def test_recent_titles_are_the_last_twenty_published():
    for i in range(25):
        ledger.record_publish({"id": f"wk-{i}", "title": f"Story {i}", "published_at": "2026-10-20T00:00:00+00:00"})
    assert writer.recent_titles() == [f"Story {i}" for i in range(5, 25)]
