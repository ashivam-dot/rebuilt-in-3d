import numpy as np

from studio import align, faces, gate, media, writer
from studio.spec import Beat, Fact, Short

SOURCE = ("Patekar was born in Murud-Janjira. He played a truant, gambling son in Krantiveer (1994), for which he won "
          "the National Film Award for Best Actor. He died on 8 October 2026 at his home in Goa.")


def test_invented_names_and_numbers_are_caught():
    ok = "He won the National Film Award for Krantiveer in 1994, and the nation mourned in Goa."
    assert writer.ungrounded(ok, SOURCE) == []
    assert writer.ungrounded("He starred in Tiranga in 1993.", SOURCE) == ["1993", "Tiranga"]
    # Title-case captions made of ordinary words are not names.
    assert writer.ungrounded("A Final Legacy", SOURCE) == []


def test_photo_relevance_keys():
    assert media._keys("Hurricane Isaias (2026)") == {"isaias"}
    assert media._keys("Nana Patekar") == {"nana", "patekar"}
    assert media._names("Nana Patekar at IFFI Goa, 2017", {"nana", "patekar"})
    assert not media._names("Cine star Waheeda Rehman at IFFI 2009", {"nana", "patekar"})
    assert media._shoot("File:Nana Patekar (Image 2), at IFFI Goa, 2017.jpg") == \
        media._shoot("File:Nana Patekar (Image 3), at IFFI Goa, 2017.jpg")


def test_licences():
    for ok in ("CC BY-SA 4.0", "CC BY 2.0", "CC0", "Public domain", "CC BY-SA 3.0 igo"):
        assert media.FREE.match(ok), ok
    for bad in ("CC BY-NC-SA 2.0", "CC BY-ND 4.0", "Fair use", "All rights reserved"):
        assert not media.FREE.match(bad), bad


def test_graphic_files_are_never_picked():
    assert media.GRAPHIC.search("Victims of the crash.jpg")
    assert media.GRAPHIC.search("Funeral of the actor.jpg")
    assert not media.GRAPHIC.search("Nana Patekar at IFFI Goa.jpg")


def test_subject_face_is_the_one_that_recurs():
    me, other, stranger = np.eye(3)[0], np.eye(3)[1], np.eye(3)[2]
    per = [[{"box": (0, 0, 9, 9), "feature": other}, {"box": (0, 0, 5, 5), "feature": me}],
           [{"box": (0, 0, 5, 5), "feature": me}],
           [{"box": (0, 0, 5, 5), "feature": stranger}]]
    picks = faces.subject(per)
    assert picks[0]["feature"] is me and picks[1]["feature"] is me
    assert picks[2] is None


def test_alignment_keeps_script_words():
    heard = [{"text": "India", "start": 0.0, "end": 0.4}, {"text": "has", "start": 0.4, "end": 0.6},
             {"text": "lost", "start": 0.6, "end": 0.9}]
    words, ratio = align.align("India has lost, today.", heard, 1.5)
    assert [w["text"] for w in words] == ["India", "has", "lost,", "today."]
    assert ratio == 0.75 and words[3]["start"] >= 0.9


def story(photos, credits):
    return Short(id="wk-Q1", kind="death", title="The Final Bow of Nana Patekar",
                 beats=[Beat("Nana Patekar has died at 75, and Indian cinema has lost a voice like no other. " * 3,
                             "photo:0"), Beat(writer.OUTRO, "outro")],
                 facts=[Fact("age", "75", "https://www.wikidata.org/wiki/Q1", ["75"])],
                 sources=["https://en.wikipedia.org/wiki/Nana_Patekar"], loss=False,
                 scene={"template": "story", "photos": photos}, credits=credits)


def test_story_gate_needs_free_credited_photos():
    photo = {"file": "File:A.jpg", "license": "CC BY-SA 4.0", "page": "https://commons.wikimedia.org/wiki/File:A.jpg"}
    good = story([photo] * 3, [photo["page"]])
    assert gate.check(good) == []
    nc = dict(photo, license="CC BY-NC 2.0")
    assert any("not free" in p for p in gate.check(story([photo, photo, nc], [photo["page"]])))
    assert any("not credited" in p for p in gate.check(story([photo] * 3, [])))
    assert any("only 2" in p for p in gate.check(story([photo] * 2, [photo["page"]])))
