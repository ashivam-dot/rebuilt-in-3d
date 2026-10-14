"""Photos show what a story is about (2026-10-14): the Multan train derailment went out over a satellite view of
Pakistan, a sunrise, a shrine, a church and a clock tower, with no train. Every article, item and Commons answer here is
a fixture; nothing touches the network."""
from dataclasses import replace

from studio import gate, media, writer
from studio.spec import Beat, Short
from tests.test_outlets import _draft

MULTAN_BOX = {
    "location": "[[Multan]], [[Punjab, Pakistan|Punjab]]",
    "country": "{{Flagicon|Pakistan}} Pakistan",
    "line": "[[Karachi–Peshawar Line]]",
    "operator": "[[Pakistan Railways]]",
    "type": "[[Derailment]]",
    "trains": "A [[passenger train]] (Train No. 8223)",
}
MULTAN_TEXT = """{{Infobox public transit accident}}
On 13 October 2026, the [[Rehman Baba Express]] passenger train derailed in [[Multan]], [[Punjab, Pakistan]].

==Background==
The train was inaugurated at [[Peshawar Cantonment railway station]] by [[Sheikh Rasheed Ahmad]].

==Accident==
[[File:Sher shah railway station.jpg|thumb|The station in 2023]]
The train was passing through the [[Sher Shah Junction railway station]] near the [[Sher Shah Bridge]].
The injured were taken to [[Nishtar Hospital]].
"""


def test_an_incident_searches_the_train_line_operator_and_station_before_the_town():
    links = writer.subject_links(MULTAN_BOX, MULTAN_TEXT)
    assert links == ["Karachi–Peshawar Line", "Pakistan Railways", "Rehman Baba Express",
                     "Sher Shah Junction railway station", "Sher Shah Bridge"]
    # a general idea, a file, a hospital and a station named only in the Background are never the subject
    assert not {"passenger train", "Derailment", "Nishtar Hospital", "Peshawar Cantonment railway station"} & set(links)


def _info(files):
    return {f: {"mime": "image/jpeg", "width": 2000, "height": 1500, "sha1": f, "descriptionurl": "https://c/" + f,
                "url": "https://u/" + f, "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"},
                                                         "Artist": {"value": "A"}, "ImageDescription": {"value": ""}}}
            for f in files}


def test_a_town_is_a_setting_a_station_a_subject_and_a_province_is_never_shown(monkeypatch):
    items = {
        "Q1": {"labels": {"en": {"value": "Sher Shah Junction railway station"}},
               "claims": {"P18": [{"mainsnak": {"datavalue": {"value": "Sher Shah station front.jpg"}}}],
                          "P625": [{"mainsnak": {"datavalue": {"value": {}}}}]}},
        "Q2": {"labels": {"en": {"value": "Multan"}},
               "claims": {"P18": [{"mainsnak": {"datavalue": {"value": "Clock Tower Multan.jpg"}}}],
                          "P1082": [{"mainsnak": {"datavalue": {"value": {"amount": "+2000000"}}}}]}},
        "Q3": {"labels": {"en": {"value": "Punjab"}},
               "claims": {"P18": [{"mainsnak": {"datavalue": {"value": "View of Pakistan from space.jpg"}}}],
                          "P36": [{"mainsnak": {"datavalue": {"value": {"id": "Q4"}}}}]}},
    }
    monkeypatch.setattr(media.wiki, "entities", lambda qids: {q: items[q] for q in qids})
    monkeypatch.setattr(media, "_article_files", lambda title: ["File:Sher shah railway station.jpg"])
    monkeypatch.setattr(media, "_info", _info)
    got = media.find("2026 Multan train derailment", {}, extra_qids=["Q1", "Q2", "Q3"], places=False)
    # an established article's own image must name the story; the province's view from space is never used
    assert [(p.file, p.role) for p in got] == [("File:Sher Shah station front.jpg", "subject"),
                                              ("File:Clock Tower Multan.jpg", "setting")]
    got = media.find("2026 Multan train derailment", {}, extra_qids=["Q1"], places=True)
    # a brand-new article's own images were put there by its editors: the station it happened at is kept
    assert got[0].file == "File:Sher shah railway station.jpg" and got[0].role == "subject"


def test_photos_of_the_subject_go_first_and_at_most_one_of_the_town():
    photos = [{"file": "File:Church.jpg", "role": "setting"}, {"file": "File:Pakistan Railways headquarters.jpg"},
              {"file": "File:Clock tower.jpg", "role": "setting"}, {"file": "File:Pakistan Railway Train.jpg"}]
    assert [p["file"] for p in writer.arrange(photos)] == ["File:Pakistan Railways headquarters.jpg",
                                                          "File:Pakistan Railway Train.jpg", "File:Church.jpg"]
    assert [p["file"] for p in writer.arrange(photos, "rail")][:2] == ["File:Pakistan Railway Train.jpg",
                                                                      "File:Pakistan Railways headquarters.jpg"]


def test_a_rail_incident_needs_photos_of_the_train_line_or_station():
    landmarks = [{"file": f"File:{n}.jpg", "description": d} for n, d in (
        ("ISS006-E-12100 - View of Pakistan", "View of Pakistan taken during ISS Expedition 6."),
        ("Shrine of Hazrat Shah Shamsuddin Sabzwari, Multan", ""), ("CATHEDRAL OF St. MARY THE VIRGIN CHURCH MULTAN", ""),
        ("Pakistan Railways headquarters 1", ""))]
    assert gate.showing("rail", landmarks) == 0
    rail = [{"file": "File:Sher shah railway station.jpg"}, {"file": "File:Pakistan Railway Train.jpg"}]
    assert gate.showing("rail", rail) == 2
    assert gate.showing("aviation", [{"file": "File:Air India Boeing 787 at Delhi.jpg"}]) == 1
    assert gate.showing("cyclone", rail) == 0


def _story(photos, first=0, category="rail"):
    fixture = Short.load(__import__("tests.test_youtube", fromlist=["FIXTURE"]).FIXTURE)
    return replace(fixture, kind="incident", scene={**fixture.scene, "template": "story", "photos": photos,
                                                    "category": category},
                   beats=[Beat("A beat.", f"photo:{first}"), Beat("Outro", "outro")])


def test_the_gate_holds_a_short_of_landmarks():
    town = {"file": "File:Clock Tower Multan.jpg", "license": "CC BY-SA 4.0", "page": "p0", "role": "setting"}
    church = town | {"file": "File:Church Multan.jpg", "page": "p1"}
    train = town | {"file": "File:Pakistan Railway Train.jpg", "page": "p2", "role": "subject"}
    station = train | {"file": "File:Sher shah railway station.jpg", "page": "p3"}
    problems = gate._story(replace(_story([town, church]), credits=["p0 p1"]))
    assert any("only show the town" in p for p in problems)
    assert any("beat 1 opens on a photo of the town" in p for p in problems)
    assert any("show the rail" in p and "usable photos" in p for p in problems)
    ok = gate._story(replace(_story([train, station, town]), credits=["p0 p2 p3"]))
    assert not [p for p in ok if "town" in p or "show the" in p]


def test_the_writer_puts_the_town_on_one_beat_and_never_first():
    say = ["The Rehman Baba Express derailed in Multan early on Monday as it passed through a junction station.",
           "Around dawn the train was passing through the junction station when the driver felt a sudden push.",
           "The driver applied the brakes, and the coaches left the rails near the bridge as the train stopped.",
           "Rescue teams launched an evacuation, and a relief train carried stranded passengers on to Peshawar."]
    photos = [{"file": "File:Sher shah railway station.jpg", "description": ""},
              {"file": "File:Pakistan Railway Train.jpg", "description": ""},
              {"file": "File:Clock Tower Multan.jpg", "description": "", "role": "setting"}]
    ground = " ".join(say) + " Rehman Baba Express Multan Monday Peshawar"
    draft = _draft(say)
    for b, n in zip(draft["beats"], (2, 0, 2, 1)):
        b["photo"] = n
    problems = writer._validate(draft, photos, "Rehman Baba Express", ground, [], [])
    assert any("beat 1 uses photo 2" in p for p in problems)
    assert any("SETTING photo is on more than one beat" in p for p in problems)
    for b, n in zip(draft["beats"], (0, 1, 2, 0)):
        b["photo"] = n
    assert not [p for p in writer._validate(draft, photos, "Rehman Baba Express", ground, [], []) if "photo" in p]
    listing = writer._messages("brief", [], "", photos, "Rehman Baba Express")[1]["content"]
    assert "2: File:Clock Tower Multan.jpg" + writer.SETTING_NOTE in listing
