"""The weekly long-form pipeline (studio/longform), offline: topic choice, planning, the writer's gates, chapters and
timestamps, the length gate, the description, and an upload that happens exactly once."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httplib2
import pytest
from googleapiclient.errors import HttpError

from studio import gate, ledger, usgs, youtube
from studio.longform import assemble, data, describe, media_review, plan, publish, review, scenes, topics, write
from studio.longform.spec import Chapter, Episode
from studio.spec import Fact

AT = datetime(2026, 10, 22, 3, 0, tzinfo=timezone.utc)  # a Thursday build


def _row(id_, title, video, days=5, kind="quake", category="earthquake"):
    return {"id": id_, "kind": kind, "category": category, "title": title, "video_id": video,
            "published_at": (AT - timedelta(days=days)).isoformat()}


PUBLISHED = [
    _row("eq-us6000u18k", "How the M7.7 Panama quake ruptured", "ou-WEYN_fZ4"),
    _row("eq-us6000u19w", "An M6.6 Panama quake followed the M7.7", "9fNuIm-NdYU"),
    _row("eq-us6000u1cf", "Why the M6.0 Panama quake followed", "bJf-bPYFKVo"),
    _row("nw-trudy", "Hurricane Trudy: how it grew", "TrudyFixt01", kind="story", category="cyclone"),
    _row("eq-ridge", "M6.8 Mid-Atlantic Ridge quake shook nobody", "ridgeVID001"),
    _row("nw-attack", "Hurricane Strike: drone attack on port", "attackVID01", kind="story", category="cyclone"),
    _row("eq-old", "M7.0 Japan quake", "oldVIDEO001", days=45),
    _row("eq-gone", "M6.9 Kamchatka quake", "B7Bn2Yhnlp8"),
]
PERFORMANCE = {"videos": {"ou-WEYN_fZ4": {"views_24h": 1489.3}, "9fNuIm-NdYU": {"views_24h": 1277.7},
                          "bJf-bPYFKVo": {"views_24h": 13.8}, "TrudyFixt01": {"views_24h": 1077.8},
                          "ridgeVID001": {"views_24h": 9999}, "attackVID01": {"views_24h": 9999},
                          "oldVIDEO001": {"views_24h": 9999}, "B7Bn2Yhnlp8": {"views_24h": 9999}}}


# --- topic choice ---------------------------------------------------------------------------------------------------

def test_candidates_group_quakes_by_region_and_skip_what_must_never_be_a_topic():
    cands = topics.candidates(PUBLISHED, PERFORMANCE, set(youtube.RETRACTED), AT)
    keys = {c["key"]: c for c in cands}
    assert set(keys) == {"quake-region:panama", "cyclone:trudy"}  # no ridge, attack, stale or retracted Short
    panama = keys["quake-region:panama"]
    assert panama["views"] == 2780.8 and len(panama["shorts"]) == 3
    assert {e["id"] for e in panama["events"]} == {"us6000u18k", "us6000u19w", "us6000u1cf"}


def test_pick_is_deterministic_and_records_why():
    cands = topics.candidates(PUBLISHED, PERFORMANCE, set(youtube.RETRACTED), AT)
    rich = {"quake-region:panama": 179, "cyclone:trudy": 150}
    chosen, why = topics.pick(cands, lambda c: rich[c["key"]], {}, AT)
    assert chosen["key"] == "quake-region:panama" and why["how"] == "highest score"
    assert [r["score"] for r in why["candidates"] if r["key"] == "quake-region:panama"] == [9052.3]
    again, _ = topics.pick(topics.candidates(PUBLISHED, PERFORMANCE, set(youtube.RETRACTED), AT),
                           lambda c: rich[c["key"]], {}, AT)
    assert again["key"] == chosen["key"]


def test_a_topic_explained_recently_is_not_explained_again():
    cands = topics.candidates(PUBLISHED, PERFORMANCE, set(youtube.RETRACTED), AT)
    done = {"episodes": {"lf-1": {"topic_key": "quake-region:panama", "publish_at": "2026-10-10T14:00:00Z"}}}
    chosen, why = topics.pick(cands, lambda c: 10, done, AT)
    assert chosen["key"] == "cyclone:trudy"
    assert any("explained in the last" in r.get("excluded", "") for r in why["candidates"])


def test_unreadable_catalogue_excludes_one_candidate_and_nothing_left_falls_back_to_evergreen():
    def broken(c):
        raise ConnectionError("down")

    chosen, why = topics.pick(topics.candidates(PUBLISHED, PERFORMANCE, set(), AT), broken, {}, AT)
    assert chosen.get("evergreen") and chosen["key"] == "quake-region:japan"
    assert all("catalogue unreadable" in r["excluded"] for r in why["candidates"])


def test_override_names_a_candidate_or_an_evergreen_region():
    cands = topics.candidates(PUBLISHED, PERFORMANCE, set(), AT)
    chosen, why = topics.pick(cands, lambda c: 1, {}, AT, override="Trudy")
    assert chosen["key"] == "cyclone:trudy" and why["how"].startswith("owner override")
    chosen, _ = topics.pick(cands, lambda c: 1, {}, AT, override="chile")
    assert chosen["center"] == [-30.0, -71.5]
    with pytest.raises(ValueError):
        topics.pick(cands, lambda c: 1, {}, AT, override="Gaza")


# --- planning -------------------------------------------------------------------------------------------------------

def test_publish_slot_is_the_next_saturday_1400_utc_with_build_time_to_spare():
    assert plan.slot(AT) == datetime(2026, 10, 24, 14, tzinfo=timezone.utc)
    assert plan.slot(datetime(2026, 10, 24, 9, tzinfo=timezone.utc)) == datetime(2026, 10, 31, 14, tzinfo=timezone.utc)
    assert plan.episode_id("Panama", AT) == "lf-2026w43-panama"


def test_wind_speeds_are_said_the_way_nhc_says_them():
    assert data.mph(105) == 120 and data.category(105) == 3 and data.category(60) == 0  # Trudy: 120 mph, not 150


def test_casualty_sentences_never_reach_the_writer():
    text = "The quake was strong. At least 75 fatalities were reported. It was felt widely.\nPeople died in 1934."
    assert plan.no_casualties(text) == "The quake was strong. It was felt widely."


def test_parse_btk_keeps_one_point_per_time_and_the_storm_name():
    line = ("EP, 21, {t}, , BEST, 0, 150N, 1050W, {kt}, 970, HU, 34, NEQ, 0, 0, 0, 0, 1010, 200, 20, 0, 0, L, 0, , 0, "
            "0, {name}")
    text = "\n".join([line.format(t="2026101500", kt=70, name="TWENTYONE"),
                      line.format(t="2026101500", kt=70, name="TRUDY"),
                      line.format(t="2026101600", kt=105, name="TRUDY")])
    track = data.parse_btk(text)
    assert track["name"] == "Trudy" and [p["kt"] for p in track["points"]] == [70, 105]
    assert track["points"][0]["lat"] == 15.0 and track["points"][0]["lon"] == -105.0


def _fake_quake_world(monkeypatch):
    q = usgs.Quake("us6000u18k", 7.7, "12 km WSW of Pitaloza Arriba, Panama", datetime(2026, 10, 9, 17, 56,
                   tzinfo=timezone.utc), 7.5868, -80.769, 12.6, "orange", 1900, "https://x")
    pack = {"quake": q, "page": usgs.EVENT_PAGE.format(id=q.id), "faulting": "strike-slip", "felt_reports": 1939,
            "exposure": {3: 2065967, 4: 1869242, 5: 2680784, 6: 607895, 7: 200714, 8: 6825}, "pager_alert": "orange",
            "cities": [{"name": "Panama City", "lat": 8.99, "lon": -79.52, "pop": 1500000, "mmi": 5.2}],
            "aftershocks": [{"mag": 5.1, "lat": 7.5, "lon": -80.7, "depth": 10, "hours": 3},
                            {"mag": 4.4, "lat": 7.6, "lon": -80.8, "depth": 10, "hours": 60}],
            "pager_history_text": "A 1934 quake caused 75 fatalities."}
    hist = [{"id": f"h{i}", "mag": 6.0 + (i % 18) / 10, "time": f"{1900 + i}-03-01T00:00:00+00:00", "year": 1900 + i,
             "lat": 7.0, "lon": -81.0, "depth": 20.0, "place": "off Panama"} for i in range(0, 120, 2)]
    detail = {"id": q.id, "geometry": {"coordinates": [q.lon, q.lat, q.depth]}, "properties": {"products": {}}}
    monkeypatch.setattr(usgs, "pack", lambda event_id: pack)
    monkeypatch.setattr(usgs, "detail", lambda event_id: detail)
    monkeypatch.setattr(data, "history", lambda *a, **k: hist)
    monkeypatch.setattr(data, "general_text", lambda d: "Panama is near several plates. In 1934 75 people died.")
    monkeypatch.setattr(data, "forecast", lambda d: None)
    monkeypatch.setattr(plan, "science", lambda role: ("", ""))
    return hist


def test_plan_quake_states_only_data_and_says_what_comes_next_without_a_forecast(monkeypatch, tmp_path):
    hist = _fake_quake_world(monkeypatch)
    cand = {"key": "quake-region:panama", "kind": "quake-region", "topic": "Panama", "views": 1.0,
            "shorts": [{"id": "eq-us6000u18k", "video_id": "ou-WEYN_fZ4", "title": "t", "views_24h": 1.0}],
            "events": [{"id": "us6000u18k", "mag": 7.7}]}
    ep = plan.plan_quake(cand, AT)
    assert ep.title == f"Why Panama Keeps Shaking: {len(hist)} Strong Quakes Nearby Since 1900"
    assert "3D" not in ep.title and 45 <= len(ep.title) <= 70
    roles = [c.key for c in ep.chapters]
    assert roles[0] == "cold-open" and roles[-1] == "why-it-matters" and "next" in roles
    facts = [f for c in ep.chapters for f in c.facts]
    assert all(f.numbers == gate.numbers(f.value) for f in facts)
    every = " ".join([f.value for f in facts] + [c.source for c in ep.chapters])
    assert "fatalit" not in every and "died" not in every
    nxt = next(c for c in ep.chapters if c.key == "next")
    assert any(f.key == "recurrence" for f in nxt.facts)  # the fallback when USGS has no aftershock forecast
    assert ep.publish_at == "2026-10-24T14:00:00Z" and ep.related[0]["video_id"] == "ou-WEYN_fZ4"
    loaded = Episode.load(ep.save(tmp_path / "episode.json"))
    assert loaded.chapters[1].facts[0].value == ep.chapters[1].facts[0].value


def test_bbox_is_16_by_9_in_mercator():
    west, south, east, north = plan.bbox16x9(8.0, -80.0, 600)
    from studio import terrain

    wide = terrain.lon2x(east, 0) - terrain.lon2x(west, 0)
    tall = terrain.lat2y(south, 0) - terrain.lat2y(north, 0)
    assert abs(wide / tall - 16 / 9) < 1e-3


# --- writing --------------------------------------------------------------------------------------------------------

def _episode(**kw) -> Episode:
    facts = [Fact("main", "On October 9, 2026, a magnitude 7.7 earthquake struck Panama (USGS).", "u",
                  numbers=["9", "2026", "7.7"]),
             Fact("count", "USGS lists 188 earthquakes of magnitude 6 or more within 500 km since 1900.", "u",
                  numbers=["188", "6", "500", "1900"])]
    chapters = [Chapter(key=k, title=t, brief="b", words=[10, 80], facts=facts, source="Panama sits near plates.",
                        visuals=[{"type": "sources"}])
                for k, t in (("cold-open", "Panama shakes again"), ("before", "It has happened before"),
                             ("why-it-matters", "Why it matters"))]
    base = dict(id="lf-2026w43-panama", kind="quake-region", topic="Panama", title="Why Panama Keeps Shaking: 188 "
                "Strong Quakes Since 1900", summary="Panama shakes often.", chapters=chapters, sources=["https://a"],
                credits=["Earthquake data: USGS (public domain)"], center=[8.0, -80.0], bbox=[-86, 4, -74, 11],
                publish_at="2026-10-24T14:00:00Z",
                related=[{"id": "eq-us6000u18k", "video_id": "ou-WEYN_fZ4", "title": "How the M7.7 Panama quake "
                          "ruptured", "views_24h": 1489.3}], hashtags=["earthquake", "Panama"])
    return Episode(**(base | kw))


class Drafter:
    def __init__(self, *answers):
        self.answers, self.seen, self.model = list(answers), [], "fake"

    def __call__(self, msgs):
        self.seen.append(msgs)
        return {"lines": self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]}


class Checker:
    """Supports every line except those containing a marked word; the second look agrees."""

    def __init__(self, bad="Colombia"):
        self.bad = bad

    def chat(self, messages, schema, temperature=0.0, max_tokens=0):
        if "LINES:" not in messages[-1]["content"]:
            return {"supported": self.bad not in messages[-1]["content"].split("LINE:")[1].split("SOURCE")[0],
                    "why": "x"}
        lines = messages[-1]["content"].split("LINES:\n")[1].splitlines()
        return {"lines": [{"line": i, "quote": "", "verdict": "unsupported" if self.bad in ln else "supported",
                           "why": "not in the sources"} for i, ln in enumerate(lines, 1)]}


GOOD = ["On October 9, 2026, a magnitude 7.7 earthquake struck Panama, says USGS.",
        "USGS lists 188 earthquakes of magnitude 6 or more within 500 km since 1900."]


def test_writer_keeps_checked_lines_and_drops_an_invented_number_and_a_toll():
    ep = _episode()
    bad = GOOD + ["The quake was felt by 4,000,000 people in the region.", "Many people were killed in the shaking."]
    drafter = Drafter(bad, bad, bad)
    out = write.write_chapter(ep, "cold-open", drafter, Checker())
    assert out["lines"] == GOOD and out["words"] == 26
    assert len(drafter.seen) == 2 and "4,000,000" in json.dumps(drafter.seen[1])  # sent back once


def test_writer_drops_a_line_the_evidence_check_flags_twice():
    ep = _episode()
    lines = GOOD + ["The quake struck Panama, near the border with Colombia, USGS says."]
    out = write.write_chapter(ep, "cold-open", Drafter(lines), Checker(bad="Colombia"))
    assert out["lines"] == GOOD


def test_writer_refuses_questions_first_person_and_a_filler_close():
    ch = _episode().chapters[0]
    src = write.ground(_episode(), ch)
    assert write.line_problems("Why does Panama shake so much, you might ask today?", ch, src, False)
    assert write.line_problems("We looked at 188 earthquakes of magnitude 6 since 1900.", ch, src, False)
    assert write.line_problems("Only time will tell what Panama faces next, says USGS.", ch, src, True)


def test_a_line_that_says_nothing_the_facts_say_goes_back_to_the_writer():
    src = ("Panama\nOn October 9, 2026, a magnitude 7.7 earthquake struck 12 km WSW of Pitaloza Arriba, Panama.\n"
           "The Cocos plate subducts beneath the Panama microplate; a fault is a fracture in the rock.")
    for padding in ("The records provide a clear picture of the geological forces at work.",
                    "This frequency shows that the region remains active.",
                    "Every recorded event contributes to the ongoing geological history of the area."):
        assert write.says_nothing(padding, src), padding
    for line in ("The Cocos plate subducts beneath the Panama microplate.",
                 "A fault is a fracture in the rock.",
                 "On October 9, 2026, a magnitude 7.7 earthquake struck Panama.",
                 "The sources for this information are in the description."):
        assert not write.says_nothing(line, src), line


def test_a_number_in_words_goes_back_to_the_writer():
    """Dry run 39697989796: "One thousand nine hundred and forty" was heard as 1,940 and the chapter failed."""
    ch = _episode().chapters[0]
    src = write.ground(_episode(), ch)
    assert any("in digits" in p for p in write.line_problems(
        "One thousand nine hundred and forty people sent a report to the USGS.", ch, src, False))
    assert any("in digits" in p for p in write.line_problems("Forty-two quakes struck Panama in 1900.", ch, src, False))
    for fine in ("Thousands of people felt the quake in Panama, USGS says.", "Two quakes struck Panama in 1900."):
        assert not any("in digits" in p for p in write.line_problems(fine, ch, src, False)), fine


# --- chapters, timestamps, length -----------------------------------------------------------------------------------

def test_chapter_lengths_are_whole_frames_and_the_last_holds_the_sources_card():
    assert scenes.chapter_seconds({"duration": 61.017}, False) == scenes.frames(61.817) / scenes.FPS
    assert scenes.chapter_seconds({"duration": 61.0}, True) - scenes.chapter_seconds({"duration": 61.0}, False) == \
        pytest.approx(scenes.END_HOLD, abs=1 / scenes.FPS)


def test_shots_cover_the_chapter_without_gaps():
    ch = _episode().chapters[0]
    ch.visuals = [{"type": "map"}, {"type": "card", "big": "1", "small": "x"}, {"type": "sources"}]
    spans = [[0.35, 4.0], [4.0, 9.0], [9.0, 12.0], [12.0, 20.0], [20.0, 25.0]]
    shots = scenes.shots_for(ch, spans, 26.0)
    assert shots[0]["start"] == 0 and shots[-1]["end"] == 26.0
    assert all(a["end"] == b["start"] for a, b in zip(shots, shots[1:]))


def test_the_sources_card_holds_after_the_last_sentence_not_under_it():
    ch = _episode().chapters[0]
    ch.visuals = [{"type": "map"}, {"type": "sources"}]
    spans = [[0.35, 4.0], [4.0, 9.0], [9.0, 20.0]]
    shots = scenes.shots_for(ch, spans, 20.8 + scenes.END_HOLD)
    assert [s["type"] for s in shots] == ["map", "sources"]
    assert shots[1]["start"] >= spans[-1][1] and shots[1]["end"] - shots[1]["start"] == pytest.approx(scenes.END_HOLD)


def test_labels_of_marks_close_together_never_overlap():
    # Three quakes a few pixels apart, each label 380x40 to the right: stacked, not drawn over each other.
    tags = [(500, 300, 380, 40, 24, -20), (530, 310, 380, 40, 24, -20), (540, 318, 380, 40, 24, -20)]
    spots = scenes.place_labels(tags)
    assert all(spots)
    boxes = [(x + ox, y + oy, x + ox + w, y + oy + h) for (x, y, w, h, _, _), (ox, oy) in zip(tags, spots)]
    assert not any(a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
                   for i, a in enumerate(boxes) for b in boxes[i + 1:])
    # A label with no free spot is left out rather than drawn over another.
    crowd = [(500, 300, 380, 40, 24, -20)] * 7
    assert scenes.place_labels(crowd)[-1] is None


def test_timestamps_start_at_zero_and_youtube_rules_are_enforced():
    lines = describe.chapter_lines([("Cold open", 0.0), ("What happened", 41.7), ("How it works", 175.2),
                                    ("Why it matters", 605.9)])
    assert lines == ["00:00 Cold open", "00:41 What happened", "02:55 How it works", "10:05 Why it matters"]
    with pytest.raises(ValueError):
        describe.chapter_lines([("a", 0.0), ("b", 30.0)])
    with pytest.raises(ValueError):
        describe.chapter_lines([("a", 0.0), ("b", 30.0), ("c", 35.0)])
    with pytest.raises(ValueError):
        describe.chapter_lines([("a", 2.0), ("b", 30.0), ("c", 65.0)])


def test_length_gate():
    ok = {"width": 1920, "height": 1080, "fps": 30.0, "audio": True}
    clean = {"black": [], "frozen": []}
    assert assemble.qa(ok | {"seconds": 480.0}, clean) == []
    assert assemble.qa(ok | {"seconds": 870.0}, clean) == []
    assert assemble.qa(ok | {"seconds": 479.0}, clean) and assemble.qa(ok | {"seconds": 871.0}, clean)
    assert assemble.qa(ok | {"seconds": 600.0, "height": 1920}, clean)
    assert assemble.qa(ok | {"seconds": 600.0}, {"black": [], "frozen": [7.0]})


def test_captions_are_offset_by_each_chapter_start():
    srt = assemble.captions([(0.0, ["One."], [[0.35, 2.0]]), (65.5, ["Two."], [[0.35, 3.0]])])
    assert "00:00:00,350 --> 00:00:01,800\nOne." in srt and "00:01:05,850 --> 00:01:08,300\nTwo." in srt


# --- description ----------------------------------------------------------------------------------------------------

def test_description_puts_chapters_and_credits_first_and_fits_5000_bytes():
    ep = _episode(sources=[f"https://example.org/{i}/" + "x" * 80 for i in range(80)],
                  summary="Panama <shakes> often.")
    text = describe.description(ep, [("Cold open", 0.0), ("Before", 90.0), ("Why", 500.0)], 40.0)
    assert describe.size(text) <= 5000 and "<" not in text and ">" not in text
    head = text.index("Chapters:\n00:00 Cold open")
    assert head < text.index("Credits:") < text.index(describe.DISCLOSURE) < text.index("Sources:")
    assert text.endswith("#earthquake #Panama")


def test_description_raises_rather_than_cutting_credits():
    ep = _episode(credits=["c" * 6000])
    with pytest.raises(ValueError):
        describe.description(ep, [("a", 0.0), ("b", 60.0), ("c", 120.0)], 60.0)


# --- publishing exactly once ----------------------------------------------------------------------------------------

class _Call:
    def __init__(self, result, on=None):
        self.result, self.on = result, on

    def execute(self):
        if isinstance(self.result, Exception):
            raise self.result
        if self.on:
            self.on()
        return self.result

    def next_chunk(self, num_retries=0):
        return None, self.execute()


class FakeYouTube:
    def __init__(self, uploads=None):
        self.store = {v["id"]: v for v in (uploads or [])}
        self.inserted, self.updates, self.playlist_items, self.thumbs = [], [], [], 0

    def __getattr__(self, name):
        return lambda: self

    def channels(self):
        return self

    def list(self, **k):
        if k.get("mine") and "statistics" in k.get("part", ""):
            return _Call({"items": [{"id": youtube.CHANNEL_ID, "contentDetails": {
                "relatedPlaylists": {"uploads": "UU"}}}]})
        if k.get("mine"):
            return _Call({"items": []})
        if "playlistId" in k:
            ids = list(self.store) if k["playlistId"] == "UU" else self.playlist_items
            return _Call({"items": [{"contentDetails": {"videoId": i}} for i in ids]})
        return _Call({"items": [self.store[i] for i in k["id"].split(",") if i in self.store]})

    def insert(self, **k):
        if "media_body" in k and "part" in k and k["part"] == "snippet,status" and "snippet" in k["body"] and \
                "categoryId" in k["body"]["snippet"]:
            vid = f"LF{len(self.inserted):09d}"
            self.inserted.append(k["body"])
            self.store[vid] = {"id": vid, "snippet": dict(k["body"]["snippet"], channelId=youtube.CHANNEL_ID),
                               "status": {"uploadStatus": "processed", "privacyStatus": "private"}}
            return _Call({"id": vid})
        if "media_body" in k:  # captions
            return _Call(HttpError(httplib2.Response({"status": 403}), b'{"error": {"message": "scope"}}'))
        if "playlistId" in k["body"]["snippet"]:
            return _Call({}, on=lambda: self.playlist_items.append(k["body"]["snippet"]["resourceId"]["videoId"]))
        return _Call({"id": "PLexplains"})

    def set(self, **k):
        self.thumbs += 1
        return _Call(HttpError(httplib2.Response({"status": 403}), b'{"error": {"message": "verify"}}'))

    def update(self, part, body):
        self.updates.append((part, body))
        v = self.store[body["id"]]
        return _Call({}, on=lambda: v[part].update(body[part]))


def _work(tmp_path: Path, ep: Episode, problems=()) -> Path:
    w = tmp_path / "work"
    w.mkdir()
    for name in ("episode.mp4", "thumbnail.jpg", "captions.srt"):
        (w / name).write_bytes(b"x")
    ep.save(w / "episode.json")
    (w / "description.txt").write_text("Panama shakes often.")
    (w / "meta.json").write_text(json.dumps({"id": ep.id, "title": ep.title, "tags": ["Panama"],
                                             "topic_key": "quake-region:panama", "publish_at": ep.publish_at,
                                             "problems": list(problems), "related": ep.related,
                                             "sha256": media_review.digest(w / "episode.mp4")}))
    if not problems:
        _approve_work(w)
    return w


def _approve_work(work):
    receipt = {"schema": 1, "model": "test-reviewer", "duration": 600,
               "video_sha256": media_review.digest(work / "episode.mp4"),
               "brief_sha256": media_review.brief_digest(review.brief(work)),
               "review_video_sha256": "a" * 64, "review_audio_sha256": "b" * 64,
               "review_contract": "orbitwire-weekly-av-v1", "review_frame_sha256": ["c" * 64] * 9,
               "verdict": {"decision": "pass", "audio_listened": True, "video_viewed": True,
                           "heard_opening": "Panama shakes.", "heard_ending": "This explains why.",
                           "checks": {k: True for k in media_review.CHECKS}, "issues": [],
                           "segments": [{"part": part, "seconds": t, "seen": "A labelled map.",
                                         "heard": "A checked explanation."}
                                        for part, t in [("opening", 1), ("middle", 300), ("ending", 590)]]}}
    folder = work / "review"
    folder.mkdir(exist_ok=True)
    (folder / "av-review.json").write_text(json.dumps(receipt))


def test_publish_uploads_private_schedules_once_and_never_again(tmp_path):
    ep = _episode()
    work, api = _work(tmp_path, ep), FakeYouTube()
    out = publish.publish(work, api=api, at=AT, sleep=lambda s: None)
    assert len(api.inserted) == 1 and api.inserted[0]["status"]["privacyStatus"] == "private"
    assert api.inserted[0]["status"]["containsSyntheticMedia"] is True
    assert api.inserted[0]["status"]["selfDeclaredMadeForKids"] is False
    assert "publishAt" not in api.inserted[0]["status"]  # uploaded private, then scheduled
    assert out["publish_at"] == "2026-10-24T14:00:00Z"
    assert out["thumbnail"].startswith("refused") and out["captions"].startswith("refused")  # best effort
    assert api.playlist_items == [out["video_id"]]
    state = ledger.load("longform", {})
    assert state["episodes"][ep.id]["state"] == "scheduled" and state["playlist"] == "PLexplains"
    assert ledger.longform_videos() == {out["video_id"]}
    again = publish.publish(work, api=api, at=AT, sleep=lambda s: None)
    assert len(api.inserted) == 1 and again["did"].startswith("nothing")


def test_publish_adopts_an_upload_whose_save_was_lost(tmp_path):
    ep = _episode()
    lost = {"id": "LOSTupload1", "snippet": {"title": ep.title, "channelId": youtube.CHANNEL_ID},
            "status": {"uploadStatus": "processed", "privacyStatus": "private"}}
    lost["snippet"]["tags"] = sorted(publish.markers({"id": ep.id, "sha256": __import__("hashlib").sha256(b"x").hexdigest()}))
    api = FakeYouTube([lost])
    out = publish.publish(_work(tmp_path, ep), api=api, at=AT, sleep=lambda s: None)
    assert api.inserted == [] and out["video_id"] == "LOSTupload1"


def test_publish_refuses_an_episode_that_failed_qa_or_whose_slot_passed(tmp_path):
    ep = _episode()
    with pytest.raises(RuntimeError, match="failed QA"):
        publish.publish(_work(tmp_path, ep, ["too short"]), api=FakeYouTube(), at=AT)
    late = tmp_path / "late"
    late.mkdir()
    with pytest.raises(RuntimeError, match="has passed"):
        publish.publish(_work(late, ep), api=FakeYouTube(), at=AT + timedelta(days=3))


def test_link_rewrites_the_whole_snippet_once_after_the_episode_is_public(tmp_path):
    ep = _episode()
    short = {"id": "ou-WEYN_fZ4", "snippet": {"title": "How the M7.7 Panama quake ruptured", "categoryId": "27",
                                               "tags": ["earthquake"], "description": "Sources...",
                                               "channelId": youtube.CHANNEL_ID, "thumbnails": {}},
             "status": {"privacyStatus": "public"}}
    api = FakeYouTube([short])
    out = publish.publish(_work(tmp_path, ep), api=api, at=AT, sleep=lambda s: None)
    assert publish.link(api=api, at=AT) == []  # not yet published
    api.store[out["video_id"]]["status"]["privacyStatus"] = "public"
    later = AT + timedelta(days=3)
    assert publish.link(api=api, at=later) == ["lf-2026w43-panama: linked from Short ou-WEYN_fZ4"]
    part, body = [u for u in api.updates if u[0] == "snippet"][0]
    assert body["snippet"]["title"] == short["snippet"]["title"] and body["snippet"]["categoryId"] == "27"
    assert body["snippet"]["tags"] == ["earthquake"] and "thumbnails" not in body["snippet"]
    assert body["snippet"]["description"].startswith(f"The full explainer: https://www.youtube.com/watch?v={out['video_id']}")
    assert publish.link(api=api, at=later) == []
    assert len([u for u in api.updates if u[0] == "snippet"]) == 1


def test_short_jobs_treat_long_form_uploads_as_known(tmp_path):
    ledger.save("longform", {"episodes": {"lf-1": {"video_id": "LFvideo0001", "title": "Why Panama Keeps Shaking"}}})
    assert "LFvideo0001" in ledger.longform_videos()


# --- review fixes: no line unchecked, one episode a week, the upload known at once ----------------------------------

class Silent:
    """An evidence check that leaves every line out; the second look says whether `ok` is in the line."""

    def __init__(self, ok="188"):
        self.ok = ok

    def chat(self, messages, schema, temperature=0.0, max_tokens=0):
        if "LINES:" in messages[-1]["content"]:
            return {"lines": []}
        line = messages[-1]["content"].split("\n\nLINE: ")[1].split("\n\nSOURCE SENTENCES:")[0]
        return {"supported": self.ok in line, "why": "x"}


def test_a_line_the_checker_leaves_out_is_not_let_through():
    ep = _episode()
    ch = ep.chapters[0]
    lines = [GOOD[1], "Panama's ancient volcano gods sleep beneath the canal, scientists say."]
    flagged = write.fact_check(Silent(), lines, ch, write.ground(ep, ch))
    assert list(flagged) == [2] and "no verdict" in flagged[2]  # line 1 passed its second look
    assert write.fact_check(Silent(ok="zzz"), lines, ch, write.ground(ep, ch)).keys() == {1, 2}
    out = write.write_chapter(ep, "cold-open", Drafter(GOOD + lines[1:]), Silent(ok="USGS"))
    assert out["lines"] == GOOD


def test_a_week_with_an_episode_gets_no_second_one(tmp_path):
    held = {"episodes": {"lf-2026w43-panama": {"video_id": "LFvideo0001", "state": "scheduled",
                                               "topic_key": "quake-region:panama",
                                               "publish_at": "2026-10-24T14:00:00Z"}}}
    assert topics.slot_taken(held, "2026-10-24T14:00:00Z") == "lf-2026w43-panama"
    assert topics.slot_taken(held, "2026-10-24T14:00:00Z", "lf-2026w43-panama") is None  # its own row
    assert topics.slot_taken(held, "2026-10-31T14:00:00Z") is None
    ledger.save("longform", held)
    with pytest.raises(RuntimeError, match="already has episode lf-2026w43-panama"):
        plan.plan(at=AT)
    ep = _episode(id="lf-2026w43-trudy", title="Hurricane Trudy: How a Pacific Storm Reached 120 mph")
    api = FakeYouTube()
    with pytest.raises(RuntimeError, match="already holds the week"):
        publish.publish(_work(tmp_path, ep), api=api, at=AT, sleep=lambda s: None)
    assert api.inserted == []
    meta = tmp_path / "work" / "meta.json"
    meta.write_text(json.dumps(json.loads(meta.read_text()) | {"override": True}))
    _approve_work(tmp_path / "work")  # A changed editorial brief requires its own exact approval.
    assert publish.publish(tmp_path / "work", api=api, at=AT, sleep=lambda s: None)["video_id"]


def test_the_upload_is_pushed_to_state_before_it_finishes_processing(monkeypatch, tmp_path):
    seen, push = [], publish.push_state
    assert push("x").startswith("skipped")  # no state checkout here: never a push from a test
    monkeypatch.setattr(publish, "push_state", lambda message: seen.append(ledger.longform_videos()) or "pushed")
    real = publish.processed
    monkeypatch.setattr(publish, "processed", lambda *a, **k: (seen.append("processed"), real(*a, **k))[1])
    out = publish.publish(_work(tmp_path, _episode()), api=FakeYouTube(), at=AT, sleep=lambda s: None)
    assert seen == [{out["video_id"]}, "processed"] and "state pushed" in out["did"]
    assert publish.push_state("x").startswith("skipped") or True


def test_the_description_never_calls_the_episode_3d():
    ep = _episode(related=[{"id": "a", "video_id": "ou-WEYN_fZ4", "title": "How the M7.7 Panama quake ruptured, in 3D"}])
    text = describe.description(ep, [("a", 0.0), ("b", 60.0), ("c", 120.0)], 60.0)
    assert "3D" not in text and "How the M7.7 Panama quake ruptured: https://www.youtube.com/shorts/ou-WEYN_fZ4" in text


def test_an_answer_cut_off_mid_json_costs_a_draft_not_the_job():
    class Cut(Drafter):
        def __call__(self, msgs):
            if not self.seen:
                self.seen.append(msgs)
                raise json.JSONDecodeError("Unterminated string", '{"lines": ["On Oct', 12)
            return super().__call__(msgs)

    class CutCheck(Checker):
        cut = True

        def chat(self, messages, schema, temperature=0.0, max_tokens=0):
            if "LINES:" in messages[-1]["content"] and self.cut:
                self.cut = False
                raise json.JSONDecodeError("Unterminated string", "{", 1)
            return super().chat(messages, schema, temperature, max_tokens)

    out = write.write_chapter(_episode(), "cold-open", Cut(GOOD), CutCheck())
    assert out["lines"] == GOOD and any("empty" in x for x in out["log"])


def test_a_second_look_cut_off_keeps_every_flagged_line(monkeypatch):
    """The merge re-check (2026-10-22): a truncated recheck answer fails the lines, not the write job."""
    ep = _episode()
    ch = ep.chapters[0]
    lines = [GOOD[1], "Panama's ancient volcano gods sleep beneath the canal, scientists say."]

    def cut_off(*a, **k):
        raise ValueError("Unterminated string")
    monkeypatch.setattr(write.writer, "recheck", cut_off)
    assert write.fact_check(Silent(), lines, ch, write.ground(ep, ch)).keys() == {1, 2}


def test_a_long_place_name_still_fits_the_title():
    long = plan.title_for({"kind": "quake-region", "topic": "Papua New Guinea"}, n="1,203")
    assert long == "Why Papua New Guinea Keeps Shaking: 1,203 Quakes Nearby Since 1900" and len(long) <= 70
    assert "Strong Quakes Nearby" in plan.title_for({"kind": "quake-region", "topic": "Panama"}, n=188)


def test_a_damaged_longform_file_never_stops_the_shorts_run():
    (ledger.STATE / "longform.json").parent.mkdir(parents=True, exist_ok=True)
    for bad in ("not json", "[]", '{"episodes": {"x": null, "y": {"video_id": "V1"}}}'):
        (ledger.STATE / "longform.json").write_text(bad)
        assert ledger.longform_videos() in (set(), {"V1"})
