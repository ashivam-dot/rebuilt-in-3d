"""Trusted outlets beyond Wikipedia: feeds, corroboration by independent owners, nw- stories and Openverse photos.
Every feed, article and API answer here is a fixture; nothing touches the network."""
from datetime import datetime, timedelta, timezone

import pytest

from studio import compose, gate, media, news, outlets, plan, trends, writer, youtube
from studio.spec import Beat, Fact, Short

NOW = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
BY_KEY = {o["key"]: o for o in outlets.OUTLETS}
OPENVERSE_FOR = media.openverse_for  # conftest stubs it for every other test

RSS = """<?xml version="1.0"?><rss><channel>
<item><title><![CDATA[Cloudburst hits Chamoli, roads cut]]></title><link>https://www.thehindu.com/a1</link>
<pubDate>Tue, 13 Oct 2026 09:00:00 +0530</pubDate>
<description><![CDATA[<p>Rescue teams &amp; locals reached the village.</p>]]></description></item>
<item><title>An old story</title><link>https://www.thehindu.com/old</link>
<pubDate>Wed, 07 Oct 2026 09:00:00 +0000</pubDate></item>
</channel></rss>"""


def item(key, title, hours_ago=1.0, url=None, now=NOW):
    o = BY_KEY[key]
    return {"title": title, "url": url or f"https://{key}.example/{abs(hash(title)) % 10**8}", "outlet": o["name"],
            "outlet_hi": o["name_hi"], "owner": o["owner"], "group": o["group"], "lang": o["lang"], "geo": o["geo"],
            "feed": key, "at": (now - timedelta(hours=hours_ago)).isoformat(), "summary": ""}


def report(key, text, title="Chamoli cloudburst"):
    return item(key, title) | {"text": text}


def test_feeds_parse_and_orbitwire_reads_english_feeds_only(monkeypatch):
    seen = []
    monkeypatch.setattr(outlets, "_feed", lambda o: seen.append(o["key"]) or RSS)
    items, errors = outlets.recent(now=NOW, langs=trends.OUTLET_LANGS)
    assert errors == [] and [i["title"] for i in items] == ["Cloudburst hits Chamoli, roads cut"]
    assert seen and all(BY_KEY[k]["lang"] == "en" for k in seen)


def test_a_failed_feed_is_reported_not_fatal(monkeypatch):
    def feed(o):
        if o["key"] == "npr":
            raise TimeoutError("timed out")
        return "<rss></rss>"

    monkeypatch.setattr(outlets, "_feed", feed)
    assert outlets.recent(now=NOW, langs=("en",)) == ([], ["outlet npr: TimeoutError: timed out"])


def test_outlet_headlines_weigh_a_story_by_independent_owners(monkeypatch):
    monkeypatch.setattr(news, "FEEDS", {})
    monkeypatch.setattr(news, "match", lambda h, now=None: "2026 Chamoli cloudburst")
    got = [item("bbc-world", "Chamoli cloudburst kills"), item("bbc-india", "Chamoli cloudburst: what we know"),
           item("thehindu", "Cloudburst in Chamoli"), item("ht", "Chamoli cloudburst latest")]
    hits, errors = news.signals(NOW, outlet_items=got)
    row = hits["2026 Chamoli cloudburst"]
    assert errors == [] and row["owners"] == ["BBC", "The Hindu Group", "HT Media"]
    assert row["news"] == 3 * news.HEADLINE_FAME and len(row["reports"]) == 4
    assert row["geos"] == {"world", "IN"}


@pytest.mark.parametrize("texts, wikidata, want", [
    (["12 people were killed in the cloudburst.", "The death toll rose to 12."], None, (12, ["BBC", "The Hindu Group"])),
    (["12 people were killed.", "At least 15 people died."], None, None),
    (["12 people were killed.", "Officials said 12 people were killed."], {15}, None),
    (["12 people were killed.", "Rescue work continues."], {12}, (12, ["BBC"])),
    (["12 people were killed.", "Rescue work continues."], None, None),
])
def test_a_reported_death_toll(texts, wikidata, want):
    assert gate.reported_toll([report("bbc-world", texts[0]), report("thehindu", texts[1])], wikidata) == want


def test_a_reported_toll_never_overrides_the_infobox():
    reports = [report("bbc-world", "12 people were killed."), report("thehindu", "12 people were killed.")]
    assert writer.reported_toll(reports, {}, "15 (est.)") is None
    assert writer.reported_toll(reports, {}, None) == (12, ["BBC", "The Hindu Group"])


def test_the_gate_refuses_a_fact_only_one_owner_reports():
    reps = [outlets.compact(item("bbc-world", "a", url="https://bbc/1")),
            outlets.compact(item("thehindu", "c", url="https://hindu/1"))]
    short = Short(id="wk-Q1", kind="incident", title="t", beats=[Beat("x", "photo:0")], loss=False,
                  sources=["https://en.wikipedia.org/wiki/X"], scene={"reporting": reps, "outlets": ["BBC"]},
                  facts=[Fact("source-14", "14", "https://bbc/1", ["14"], "", owners=["BBC"])])
    assert gate._reported(short) == ["fact source-14: 1 independent outlet(s) report it (want 2)"]
    short.facts[0].owners = ["BBC", "The Hindu Group"]
    assert gate._reported(short) == []


TEXT_A = "The cloudburst struck Chamoli on Monday. Rescuers reached 14 villages near the Alaknanda river."
TEXT_B = "In Chamoli, teams reached 14 villages by evening as the Alaknanda river swelled."
TEXT_C = "Officials in Chamoli said 9 bridges were damaged."
SAY = ["A cloudburst over Chamoli has cut off villages high in the Himalayan valleys of northern India this week.",
       "Rescue teams have now reached 14 villages, carrying food and medicine along roads the water tore apart.",
       "The Alaknanda river rose fast, and families living along its banks were moved to safer ground.",
       "The work to reopen the roads goes on, and the whole valley waits for the water to fall."]


def _draft(say=SAY):
    return {"title": "Chamoli cloudburst: what happened",
            "beats": [{"say": s, "photo": i % 3, "caption": "Chamoli"} for i, s in enumerate(say)]}


def _problems(reports):
    photos = [{"file": f"File:{i}.jpg", "description": "Chamoli"} for i in range(3)]
    return writer._validate(_draft(), photos, "Chamoli", "Place: Chamoli. Himalayan valleys of northern India.", [],
                            reports)


def test_the_writer_may_use_names_and_numbers_two_owners_report():
    problems = _problems([report("bbc-world", TEXT_A), report("thehindu", TEXT_B)])
    assert not any("not in the sources" in p for p in problems)


def test_the_writer_may_not_use_what_one_owner_reports():
    problems = _problems([report("bbc-world", TEXT_A), report("thehindu", TEXT_C)])
    bad = next(p for p in problems if "not in the sources" in p)
    assert "14" in bad and "Alaknanda" in bad and "one outlet is not enough" in bad
    assert any("not in the sources" in p for p in _problems([]))


def test_reports_lose_casualty_and_suspect_sentences():
    got = writer.clean_reports([report("bbc-world", "A blast hit Chamoli market. 12 people were killed. Police named "
                                                    "the suspect as a local man. Shops reopened on Tuesday.")],
                               ["Chamoli"], perpetrators=True)[0]
    assert "killed" not in got["text"] and "suspect" not in got["text"] and "Shops reopened" in got["excerpt"]
    died = writer.clean_reports([report("bbc-world", "A bus fell near Chamoli. Twelve people died and 12 bodies were "
                                                     "recovered. Police arrested the driver. The road reopened."),
                                 report("thehindu", "A bus fell near Chamoli. 12 people died. The road reopened.")],
                                ["Chamoli"], perpetrators=True)
    assert all(r["text"] == "A bus fell near Chamoli. The road reopened." for r in died)
    assert "12" not in gate.corroborated_values(died)


def test_an_agreed_toll_never_lets_another_reported_count_through():
    # Infobox and Wikidata agree on 12; two outlets say "at least 15 killed, 30 injured".
    kept = writer.clean_reports([report("bbc-world", "A blast hit Chamoli. At least 15 people were killed and 30 "
                                                     "injured, officials said. Markets shut."),
                                 report("thehindu", "A blast hit Chamoli. At least 15 people were killed, 30 injured. "
                                                    "Markets shut.")], ["Chamoli"], perpetrators=True)
    assert not {"15", "30"} & gate.corroborated_values(kept)
    assert not writer.reported_ok("15", kept)


@pytest.mark.parametrize("text", ["12 or more people were killed.", "12 feared dead after the blast."])
def test_a_hedge_after_the_number_is_not_an_exact_toll(text):
    reports = [report("bbc-world", text), report("thehindu", text), report("ht", "12 people were killed.")]
    assert gate.reported_toll(reports) is None


def test_one_owner_and_one_of_several_wikidata_tolls_is_not_a_toll():
    reports = [report("bbc-world", "12 people were killed."), report("thehindu", "Rescue work continues.")]
    assert gate.reported_toll(reports, {12, 15}) is None


def test_the_fact_check_sees_each_reports_owner():
    reports = [report("bbc-world", TEXT_A) | {"excerpt": TEXT_A}]
    ground = writer.report_ground(reports)
    assert ground.startswith("[owner: BBC] The cloudburst struck Chamoli")
    msg = writer._check_messages(["x"], [], "", reports)[1]["content"]
    assert "two DIFFERENT owners" in msg and "[owner: BBC]" in msg


def _cluster(now=NOW):
    return [item("bbc-world", "Chamoli cloudburst: villages cut off in Uttarakhand", 3, now=now),
            item("thehindu", "Cloudburst in Chamoli leaves villages cut off", 2, now=now),
            item("toi", "Chamoli cloudburst: rescue teams reach cut off villages", 1, now=now)]


def test_an_nw_story_is_found_and_waits_behind_the_setting(monkeypatch):
    now = datetime.now(timezone.utc)

    def signals():
        trends.READ.extend(_cluster(now))
        return {}, []

    monkeypatch.setattr(trends, "_signals", signals)
    monkeypatch.setattr(trends, "NEW_STORIES", False)
    got = trends.radar()
    assert [c["id"][12:] for c in got["emerging"]] == ["chamoli-flood"] and got["candidates"] == []
    assert got["outlets"]["owners"] == 3
    assert "1 nw- stories (off: STUDIO_NEW_STORIES)" in plan.outlet_note(got["outlets"], got["emerging"])
    monkeypatch.setattr(trends, "NEW_STORIES", True)
    assert len(trends.radar()["candidates"]) == 1


TIGER = [("bbc-world", "Bollywood actor Tiger Shroff survives shooting attempt in Mumbai", 5),
         ("toi", "Tiger Shroff shooting: Videos piece together moments before, during and after attack", 4),
         ("ndtv", "Tiger Shroff Firing Case LIVE Updates: Accused Tracked Actor For 10 Days", 3),
         ("ht", "Attack on Tiger Shroff: 3 shooters held from Kota station en route to Nepal", 2),
         ("ndtv", "Tiger Shroff escapes unhurt after shots fired, Lawrence Bishnoi gang claims attack", 1)]


def test_an_attack_on_a_famous_actor_is_one_story_named_by_their_full_name():
    matched = [item(k, t, h) | {"matched": "Tiger Shroff" if n % 2 else "Lawrence Bishnoi"}
               for n, (k, t, h) in enumerate(TIGER)]
    assert len(outlets.stories(matched, NOW, known=["2026 Chamoli cloudburst"])) == 1  # a biography tells no incident
    got = outlets.stories([item(k, t, h) for k, t, h in TIGER], NOW)
    assert [(c["name"], c["category"]) for c in got] == [("Tiger Shroff", "attack")]
    assert "Lawrence" in got[0]["attackers"] and "Bishnoi" in got[0]["attackers"]
    assert outlets.headline_kind("Tiger Shroff resumes shooting for his new film in London") is None
    assert outlets.headline_kind("Watch: Bollywood stars at the Diwali party") is None


class Told(Exception):
    pass


def test_an_nw_story_about_a_person_is_told_over_their_own_portraits(monkeypatch, tmp_path):
    monkeypatch.setattr(trends, "NEW_STORIES", True)
    monkeypatch.setattr(writer, "WORK", tmp_path)
    cand = outlets.stories([item(k, t, h) for k, t, h in TIGER], NOW)[0]
    monkeypatch.setattr(writer, "_reporting", lambda c, name, **kw: [report(k, TEXT_A) for k in ("bbc-world", "toi", "ht")])
    monkeypatch.setattr(writer.gate, "reported", lambda name, reports: ["BBC", "HT Media", "Bennett, Coleman & Co."])
    monkeypatch.setattr(writer, "story_place", lambda name: (None, {}))
    monkeypatch.setattr(writer, "story_subject", lambda name: None)
    monkeypatch.setattr(writer, "story_person", lambda name: ("Tiger Shroff", PERSON))
    asked = {}
    monkeypatch.setattr(writer, "pick_photos", lambda title, ent, folder, person, **kw:
                        asked.update(title=title, person=person) or [{"file": f"File:T{i}.jpg"} for i in range(3)])
    monkeypatch.setattr(writer, "write", lambda kind, name, she, facts, *a, **kw: (_ for _ in ()).throw(Told(facts)))
    with pytest.raises(Told) as told:
        writer.build(cand)
    assert asked == {"title": "Tiger Shroff", "person": True} and told.value.args[0][0] == "Person: Tiger Shroff."


def test_an_nw_story_is_told_only_from_two_owners_reporting(monkeypatch, tmp_path):
    monkeypatch.setattr(trends, "NEW_STORIES", True)
    cand = outlets.stories(_cluster(), NOW)[0]
    texts = {"bbc-world": TEXT_A, "thehindu": TEXT_B, "toi": TEXT_C}
    monkeypatch.setattr(outlets, "_extract", lambda url: texts[url.split("/")[2].split(".")[0]] + " " * 300)
    monkeypatch.setattr(writer, "WORK", tmp_path)
    monkeypatch.setattr(writer, "story_place", lambda name: ("Q1", {"labels": {}}))
    monkeypatch.setattr(writer.wiki, "claims", lambda ent, pid: [])
    photos = [{"file": f"File:{i}.jpg", "description": "Chamoli", "credit": "Photo: A / CC BY 2.0 / Openverse (Flickr)",
               "page": f"https://flickr/{i}", "host": "Openverse (Flickr)", "license": "CC BY 2.0"} for i in range(3)]
    monkeypatch.setattr(writer, "fill_photos", lambda qids, folder, exclude, need=3: photos)
    seen = {}

    def write(kind, name, pronoun, facts, source, photos, **kw):
        seen.update(kw, source=source)
        return _draft(), []

    monkeypatch.setattr(writer, "write", write)
    short = writer.build(cand)
    assert short.id == cand["id"] and seen["source"] == "" and len(seen["reports"]) == 3
    assert short.scene["outlets"] == ["BBC", "Times of India", "The Hindu"] and short.scene["article"] is None
    assert "reporting: BBC, Times of India, The Hindu" in short.credits[0] and "Openverse" in short.credits[0]
    assert next(f for f in short.facts if f.key == "source-14").owners == ["BBC", "The Hindu Group"]
    assert gate._reported(short) == []
    assert youtube.source_lines(short)[0] == "Sources: BBC, Times of India, The Hindu"


def test_an_nw_story_needs_two_owners_naming_it_and_the_setting(monkeypatch):
    cand = outlets.stories(_cluster(), NOW)[0]
    monkeypatch.setattr(trends, "NEW_STORIES", False)
    with pytest.raises(ValueError, match="STUDIO_NEW_STORIES"):
        writer.build(cand)
    monkeypatch.setattr(trends, "NEW_STORIES", True)
    monkeypatch.setattr(outlets, "_extract", lambda url: (TEXT_B + " " * 300) if "thehindu" in url else
                        "Rescue work went on. " * 20)
    with pytest.raises(ValueError, match="articles name Chamoli"):
        writer.build(cand)


PERSON = {"claims": {"P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}}]}}
PLACE = {"claims": {"P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q515"}}}}],
                    "P625": [{"mainsnak": {"datavalue": {"value": {"latitude": 30.4, "longitude": 79.3}}}}]}}


def test_an_nw_story_place_is_never_a_person(monkeypatch):
    monkeypatch.setattr(writer.wiki, "search", lambda name: "Imran Khan" if name == "Khan" else "Chamoli district")
    monkeypatch.setattr(writer.wiki, "page_info", lambda titles: {t: {"qid": "Q1"} for t in titles})
    monkeypatch.setattr(writer.wiki, "entities", lambda qids: {"Q1": PERSON})
    assert writer.story_place("Khan") == (None, {})
    monkeypatch.setattr(writer.wiki, "entities", lambda qids: {"Q1": PLACE})
    assert writer.story_place("Chamoli") == ("Q1", PLACE)


def test_openverse_is_searched_only_for_places(monkeypatch):
    asked = []
    monkeypatch.setattr(media.wiki, "entities", lambda qids: {"Q1": PERSON | {"labels": {"en": {"value": "A Singer"}}},
                                                              "Q2": PLACE | {"labels": {"en": {"value": "Chamoli"}}}})
    monkeypatch.setattr(media, "openverse", lambda q, exclude=None, role="subject": asked.append(q) or [])
    OPENVERSE_FOR(["Q1", "Q2"])
    assert asked == ["Chamoli"]


def test_discovery_reports_must_name_the_story(monkeypatch):
    monkeypatch.setattr(outlets, "_extract", lambda url: "Chamoli report. " * 30)
    cand = {"reports": [item("bbc-world", "Chamoli cloudburst: villages cut off"),
                        item("thehindu", "Cloudburst in Chamoli leaves villages cut off"),
                        item("ht", "Uttarakhand assembly session adjourned")]}
    got = writer._reporting(cand, "2026 Chamoli cloudburst", search=False)
    assert sorted(outlets.owners(got)) == ["BBC", "HT Media", "The Hindu Group"]  # nw- clusters are the story
    got = writer._reporting(cand, "2026 Chamoli cloudburst", search=True)
    assert sorted(outlets.owners(got)) == ["BBC", "The Hindu Group"]


def test_a_plain_http_link_becomes_https_and_a_mixed_feed_is_not_indian(monkeypatch):
    feed = RSS.replace("https://www.thehindu.com/a1", "http://www.thehindu.com/a1")
    assert outlets.parse(feed, BY_KEY["thehindu"], NOW)[0]["url"] == "https://www.thehindu.com/a1"
    monkeypatch.setattr(news, "FEEDS", {})
    monkeypatch.setattr(news, "match", lambda h, now=None: "2026 Lisbon tram crash")
    hits, _ = news.signals(NOW, outlet_items=[item("toi", "Lisbon tram crash"), item("guardian", "Lisbon tram crash")])
    assert hits["2026 Lisbon tram crash"]["geos"] == {"world"}


def test_a_story_told_from_reporting_is_not_told_again_from_its_new_article():
    rows = [{"id": "nw-20261013-chamoli-flood", "published_at": "2026-10-13T10:00:00+00:00",
             "headlines": ["Chamoli cloudburst: villages cut off in Uttarakhand"], "report_urls": ["https://bbc/1"]}]
    assert plan.told_before({"id": "wk-Q99", "title": "2026 Chamoli cloudburst"}, rows, NOW)
    assert not plan.told_before({"id": "wk-Q98", "title": "2026 Kerala boat accident"}, rows, NOW)
    assert plan.told_before({"id": "nw-20261014-chamoli-flood", "title": "x"}, rows, NOW)


def test_openverse_keeps_only_free_licences_naming_the_place(monkeypatch):
    results = {"results": [
        {"id": "a", "title": "Chamoli valley", "license": "by", "license_version": "2.0", "url": "https://x/a.jpg",
         "filetype": "jpg", "width": 2000, "height": 1300, "creator": "Asha", "source": "flickr",
         "foreign_landing_url": "https://www.flickr.com/photos/asha/1"},
        {"id": "b", "title": "Chamoli river", "license": "by-nd", "url": "https://x/b.jpg", "filetype": "jpg",
         "width": 2000, "height": 1300, "creator": "B"},
        {"id": "c", "title": "Chamoli bridge", "license": "pdm", "url": "https://x/c.jpg", "filetype": "jpg",
         "width": 2000, "height": 1300, "creator": "C"},
        {"id": "d", "title": "Holiday snap", "license": "cc0", "url": "https://x/d.jpg", "filetype": "jpg",
         "width": 2000, "height": 1300, "creator": "D"}]}
    monkeypatch.setattr(media.net, "get_json", lambda url, params=None, **k: results)
    got = media.openverse("Chamoli")
    assert [p.file for p in got] == ["openverse:a"] and got[0].credit == "Photo: Asha / CC BY 2.0 / Openverse (Flickr)"


def test_openverse_photos_are_named_on_the_end_card():
    assert compose.disclosure([{"host": "Openverse (Flickr)"}]) == \
        "Real photos: Wikimedia Commons, Openverse · Narration: AI voice"
    assert compose.disclosure([{"host": "Wikimedia Commons"}]) == compose.DISCLOSURE


def test_the_description_names_the_outlets_behind_the_facts():
    short = Short(id="wk-Q1", kind="incident", title="t", beats=[], facts=[], loss=False,
                  sources=["https://en.wikipedia.org/wiki/X", "https://www.bbc.com/news/1"],
                  scene={"template": "story", "outlets": ["BBC", "The Hindu"]})
    assert youtube.source_lines(short)[0] == "Sources: Wikipedia, BBC, The Hindu"
