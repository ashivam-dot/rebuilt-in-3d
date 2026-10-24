"""The second speed-up (2026-10-14; owner: Orbitwire "must be among the most active channels"): world stories whenever
Europe or the US is awake, 12 a day 40 minutes apart, two photos for an incident, flight incidents, strikes and
cyberattacks as nw- stories, and no retries for a tribute with no portrait. Headlines are real ones from that day."""
from datetime import datetime, timezone

import pytest

from studio import cli, gate, outlets, plan, writer
from studio.spec import Short
from tests.test_outlets import NOW, item

WORLD, INDIA = {"region": "world"}, {"region": "india"}


def utc(month, day, hour, minute=0):
    return datetime(2026, month, day, hour, minute, tzinfo=timezone.utc)


def test_world_stories_go_out_whenever_london_or_new_york_is_awake():
    # October: London is on BST (UTC+1), New York on EDT (UTC-4).
    assert plan.in_window(WORLD, utc(10, 14, 6))  # 07:00 London; it was closed until 11:00 UTC
    assert plan.in_window(WORLD, utc(10, 14, 9))  # 14:30 IST, 10:00 London
    assert plan.in_window(WORLD, utc(10, 14, 3, 30))  # 23:30 New York
    assert not plan.in_window(WORLD, utc(10, 14, 4))  # 00:00 New York, 05:00 London
    assert not plan.in_window(WORLD, utc(10, 14, 5, 59))
    # December: GMT and EST, so the closed hours move to 05:00-07:00 UTC.
    assert plan.in_window(WORLD, utc(12, 1, 4, 30)) and not plan.in_window(WORLD, utc(12, 1, 6, 30))
    assert plan.in_window(WORLD, utc(12, 1, 7))
    # India's window is unchanged: 09:00-23:00 IST.
    assert plan.in_window(INDIA, utc(10, 14, 3, 30)) and not plan.in_window(INDIA, utc(10, 14, 17, 30))


def test_twelve_a_day_forty_minutes_apart_and_wars_never_break():
    assert plan.MAX_PER_DAY == 12 and plan.MIN_GAP.total_seconds() == 40 * 60
    strike = {"kind": "incident", "category": "strike", "fame": 50_000, "news_at": NOW.isoformat(),
              "owners": ["BBC", "United Nations", "NBCUniversal", "Fox Corporation", "Los Angeles Times"]}
    assert not plan.is_breaking(strike, NOW)
    assert plan.is_breaking(strike | {"category": "aviation"}, NOW)


@pytest.mark.parametrize("title, kind", [
    ("Frankfurt-Delhi Air India Flight Diverted To Jaipur After Hijack Alert: Report", "aviation"),
    ("Frankfurt-Delhi Air India flight diverted to Jaipur after hijacking alert, probe on", "aviation"),
    ("ATC got hijack code but pilots deny: Baffling mystery behind Air India flight scare", "aviation"),
    ("IndiGo flight makes emergency landing in Nagpur after bomb threat", "aviation"),
    ("Several hurt as Singapore Airlines jet hits severe turbulence", "aviation"),
    ("Pilot declares mayday as engine fire forces plane back to Heathrow", "aviation"),
    ("Houthi missile hits Aramco building after Saudi-led coalition strike on Yemen fuel depot", "strike"),
    ("Ukraine: Russian missiles hit Kyiv homes and power plant, killing 3 and injuring 22", "strike"),
    ("3 killed in Russian missile & drone barrage, 600,000 left without power in Ukraine", "strike"),
    ("Russia batters Ukraine’s power facilities amid Kyiv’s growing strain with US", "strike"),
    ("Russia's 'targeted' strikes on energy leave 600,000 without power, Zelensky says", "strike"),
    ("Saudi Arabia strikes oil depots in Yemen and says missiles launched toward location of Saudi Aramco HQ", "strike"),
    ("Israeli air strike kills Palestinian woman in Gaza City", "strike"),
    ("Massive cyberattack targets refrigerators in supermarkets across France", "cyberattack"),
    ("Ransomware attack shuts down hospital systems across Bavaria", "cyberattack"),
    ("Lawmaker reportedly loses leg as car ramming stuns Australia", "attack"),
    ("Helen Haines loses leg as surgeons fight to save the other after alleged attack in Wangaratta", "attack"),
    ("Horror and disbelief after lawmaker attacked in rural Australia", "attack"),
    ("Deadly fire at Canada military base moved a kilometre 'in 30 to 60 seconds'", "disaster"),
    ("4 dead, dozens injured after fire at Canadian military base, officials say", "disaster"),
    ("Newport school bus crashes into railway bridge injuring three children", "accident"),
    # Not incidents: a live blog, a video, a labour strike, a deal, a warning, a drill, a launch, an explainer.
    ("Trump attacked Democrats over the shutdown at a North Carolina rally", None),
    ("Chancellor comes under fire over capital gains plans", None),
    ("Firefighters praised as ceasefire talks resume in Doha", "conflict"),  # a war's turn (owner, 2026-10-24)
    ("🔴Ukraine live: Russia's 'targeted' strikes on energy leave 600,000 without power, Zelensky says", None),
    ("Watch: Block of flats destroyed in Russian strikes on Ukraine", None),
    ("Refinery workers strike over pay, oil output hit", None),
    ("Shell strikes deal for Nigerian oil field", None),
    ("Terrorists could use AI to target UK with drones and bioweapons, MI5 chief warns", None),
    ("China’s Liaoning carrier heads to the Pacific as US, Japan prepare for missile drills", None),
    ("SpaceX rocket launch hits a delay at Cape Canaveral", None),
    ("How a radio glitch triggered a false hijack alert in Germany", None),
    ("DGCA bans MOBIKINS model power bank on flights after IndiGo fire incident", None),
    ("Pope Leo XIV undergoes surgery for cancer", None),
])
def test_flight_incidents_strikes_and_cyberattacks_are_headline_kinds(title, kind):
    assert outlets.headline_kind(title) == kind


ARAMCO = [("guardian", "Saudi Arabia strikes oil depots in Yemen and says missiles launched toward location of Saudi "
                       "Aramco HQ", 20),
          ("euronews", "Trump blasts 'not nice' Houthis as attack hits Saudi Aramco facility", 5.5),
          ("bbc-world", "Houthi missile hits Aramco building after Saudi-led coalition strike on Yemen fuel depot", 1)]


def test_a_strike_three_outlets_report_is_one_nw_story_never_named_after_its_attacker():
    rows = [item(key, title, hours) for key, title, hours in ARAMCO]
    [story] = outlets.stories(rows, NOW)
    # The Euronews headline came before the BBC one that links it to the Guardian's, and still joins.
    assert story["id"] == "nw-20261012-aramco-strike" and len(story["owners"]) == 3
    assert story["category"] == "strike" and story["places"][0] == "Yemen"
    assert {"Houthi", "Houthis", "Saudi", "Arabia"} <= set(story["attackers"]) and "Aramco" not in story["attackers"]


def test_two_flights_diverted_after_bomb_threats_are_two_stories():
    rows = [item("bbc-world", "IndiGo flight diverted to Nagpur after bomb threat", 3),
            item("ndtv", "Akasa Air flight diverted to Lucknow after bomb threat", 2.5),
            item("thehindu", "IndiGo flight to Nagpur diverted after bomb threat", 2),
            item("ht", "Bomb threat: Akasa Air flight diverted to Lucknow", 1.5)]
    assert outlets.stories(rows, NOW) == []  # each has two owners only; they never merge into one of four


def test_a_flight_incident_still_needs_a_strong_outlet():
    rows = [item("ndtv", "Frankfurt-Delhi Air India Flight Diverted To Jaipur After Hijack Alert: Report", 3),
            item("ht", "Frankfurt-Delhi Air India flight diverted to Jaipur after hijacking alert, probe on", 2),
            item("toi", "Air India flight from Frankfurt diverted to Jaipur after hijack alert", 1)]
    assert outlets.stories(rows, NOW) == []
    [story] = outlets.stories(rows + [item("bbc-world", "Air India flight to Delhi diverted to Jaipur after hijack "
                                                        "alert", 0.5)], NOW)
    assert story["id"].endswith("-jaipur-aviation") and story["attackers"] == []


def test_the_story_name_does_not_depend_on_set_order():
    rows = [item("independent", "French police clash with school protesters in Paris as Greta Thunberg joins "
                                "demonstration", 3),
            item("fox-world", "Greta Thunberg joins massive French student protests as cars burn", 2),
            item("abc-us-top", "Greta Thunberg backs French high school protests over run-down schools", 1)]
    assert [s["id"] for s in outlets.stories(rows, NOW)] == ["nw-20261013-greta-thunberg-protest"]


@pytest.mark.parametrize("title, who", [
    ("Houthi missile hits Aramco building after Saudi-led coalition strike on Yemen fuel depot", ["Houthi", "Saudi"]),
    ("Russia's 'targeted' strikes on energy leave 600,000 without power", ["Russia"]),
    ("Ukraine: Russian missiles hit Kyiv homes and power plant", ["Russian"]),
    ("Russia pounds Kharkiv and Lviv region with missiles and drones", ["Russia"]),
    ("Bulgaria says Russia likely behind Black Sea strikes as rescue operations continue", ["Russia"]),
    ("U.S. may have withheld warnings to Ukraine on deadly Kyiv strikes", []),
    ("ATC got hijack code but pilots deny: Baffling mystery behind Air India flight scare", []),
])
def test_attackers_are_found_and_targets_are_not(title, who):
    assert outlets.attackers([title]) == who


def test_the_writer_never_names_an_attacker_in_any_form():
    photos = [{"file": "File:0.jpg", "description": ""}, {"file": "File:1.jpg", "description": ""}]
    draft = {"title": "Aramco building hit", "beats": [
        {"say": "A missile fired by the Houthis hit an Aramco building in Riyadh.", "photo": 0, "caption": "October"}]}
    got = writer._validate(draft, photos, "Aramco", "Aramco Riyadh Houthis", ["Houthi"])
    assert "never name a perpetrator or attacker (Houthi)" in got


TEXTS = {
    "guardian": "Saudi Arabia said it struck fuel depots in Yemen on Monday. Officials said missiles were later "
                "launched toward the Aramco headquarters in Riyadh and an Aramco building was damaged.",
    "euronews": "An Aramco facility in Riyadh was hit on Tuesday, the company said. Yemen has seen a wave of "
                "strikes on fuel depots this week, and Aramco said its staff were safe.",
    "bbc-world": "A missile hit an Aramco building in Riyadh early on Tuesday. Hours earlier a fuel depot in Yemen "
                 "had been struck. Aramco said operations would continue.",
}


def _two_photos():
    return [{"file": f"File:{i}.jpg", "description": "Yemen", "credit": "Photo: A / CC BY 2.0 / Openverse (Flickr)",
             "page": f"https://flickr/{i}", "host": "Openverse (Flickr)", "license": "CC BY 2.0"} for i in range(2)]


def test_a_strike_with_two_photos_of_the_next_named_place_and_no_attacker_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(writer.trends, "NEW_STORIES", True)
    cand = outlets.stories([item(key, title, hours) for key, title, hours in ARAMCO], NOW)[0]
    monkeypatch.setattr(outlets, "_extract", lambda url: TEXTS[url.split("/")[2].split(".")[0]] + " " * 300)
    monkeypatch.setattr(writer, "WORK", tmp_path)
    monkeypatch.setattr(writer, "story_place", lambda name: ("Q805", {"labels": {}}) if name == "Yemen" else (None, {}))
    monkeypatch.setattr(writer.wiki, "claims", lambda ent, pid: [])
    monkeypatch.setattr(writer, "fill_photos", lambda qids, folder, exclude, need=3: _two_photos())
    seen = {}

    def write(kind, name, pronoun, facts, source, photos, **kw):
        seen.update(kw, facts=facts, photos=photos)
        say = ["A missile hit an Aramco building in Riyadh early on Tuesday, the reports say.",
               "Hours earlier a fuel depot in Yemen had been struck, the reports say.",
               "Aramco said its operations would continue."]
        return {"title": "Aramco building hit in Riyadh", "beats": [
            {"say": s, "photo": i % 2, "caption": "Tuesday"} for i, s in enumerate(say)]}, []

    monkeypatch.setattr(writer, "write", write)
    # Owner, 2026-10-22: two photos of Yemen do not show a strike in Riyadh. Since then the story is refused before
    # a word is written (writer.faceless), and retried: Commons may have the event's photos hours later.
    with pytest.raises(ValueError, match="faceless: no free photo shows Aramco") as refused:
        writer.build(cand)
    assert not seen and any(m in str(refused.value) for m in __import__("studio.cli").cli.RETRYABLE)
    event = [dict(p, kind="event", file=f"File:strike{i}.jpg", page=f"https://flickr/s{i}") for i, p in
             enumerate(_two_photos() + _two_photos()[:1])]
    monkeypatch.setattr(writer, "event_photos", lambda *a, **kw: event)
    short = writer.build(cand)
    assert seen["facts"][0] == "Place: Yemen." and len(seen["photos"]) == 5
    assert {"Houthi", "Saudi"} <= set(seen["banned_names"]) and "Aramco" not in seen["banned_names"]
    assert short.loss and gate._reported(short) == []
    assert next(f for f in short.facts if f.key == "name").owners == ["BBC", "Euronews", "Guardian Media Group"]


def test_an_incident_and_a_tribute_both_want_three_photos():
    photos = _two_photos()
    incident = Short(id="nw-x", kind="incident", title="t", beats=[], facts=[], sources=[], loss=False, scene={"photos": photos},
                     credits=[p["page"] for p in photos])
    assert gate._story(incident) == ["photos: only 2 show who or what the story is about (want 3 or more)"]
    three = photos + [dict(photos[0], file="File:2.jpg", page="https://flickr/2")]
    incident.scene, incident.credits = {"photos": three}, [p["page"] for p in three]
    assert gate._story(incident) == []
    tribute = Short(id="wk-x", kind="death", title="t", beats=[], facts=[], sources=[], loss=False, scene={"photos": photos},
                    credits=[p["page"] for p in photos])
    assert gate._story(tribute) == ["photos: only 2 (want 3 or more)"]


def test_the_writer_shows_each_photo_on_one_beat():
    """Owner, 2026-10-23: a picture shown again spoils the Short, so there are as many beats as photos (at most 8)."""
    msg = writer._messages("brief", [], "", _two_photos(), "Yemen")[1]["content"]
    assert "Exactly 2 beats, one for each PHOTO, and 26 to 34 words" in msg and "never show a photo twice" in msg
    assert "Exactly 8 beats" in writer._messages("brief", [], "", _two_photos() * 5, "Yemen")[1]["content"]


def test_fill_photos_are_still_sought_for_a_third(monkeypatch, tmp_path):
    asked = {}
    monkeypatch.setattr(writer, "_own_photos", lambda *a: [{"file": "File:a.jpg"}, {"file": "File:b.jpg"}])

    def fill(qids, folder, exclude, need):
        asked["need"] = need
        return [{"file": "File:c.jpg"}]

    monkeypatch.setattr(writer, "fill_photos", fill)
    got = writer.pick_photos("Hurricane Rachel", {}, tmp_path, person=False, context_qids=["Q1"])
    assert asked["need"] == 1 and len(got) == 3


def _death(monkeypatch, photos):
    ent = {"labels": {"en": {"value": "Doug Loft"}}}
    dates = {"P569": [{"value": "+1940-05-02T00:00:00Z"}], "P570": [{"value": "+2026-10-12T00:00:00Z"}]}
    monkeypatch.setattr(writer.wiki, "entities", lambda qids: {"Q5300674": ent})
    monkeypatch.setattr(writer.wiki, "infobox", lambda title: ({}, {}, {"death_date": "October 12, 2026"}))
    monkeypatch.setattr(writer.wiki, "claims", lambda e, pid: dates.get(pid, []))
    monkeypatch.setattr(writer, "pick_photos", lambda *a, **k: photos)
    with pytest.raises(ValueError) as err:
        writer.build_death({"title": "Doug Loft", "qid": "Q5300674", "kind": "death"})
    return str(err.value)


def test_a_tribute_with_no_portrait_is_skipped_at_once_and_a_short_one_is_retried(monkeypatch):
    none = _death(monkeypatch, [])
    assert "no photo on Wikimedia Commons shows Doug Loft's face" in none
    assert not any(m in none for m in cli.RETRYABLE)
    short = _death(monkeypatch, _two_photos())
    assert "only 2 usable photos" in short and any(m in short for m in cli.RETRYABLE)
