"""The voice check hears foreign names the way Whisper spells them (2026-10-14: the Multan Short failed twice on
"Rehman Baba Express ... Sher Shah Junction", heard as "Rahman" and "Shershah"), yet still catches a cut-off take."""
from studio import align, voice

BEAT = "At 5:15 a.m., the Rehman Baba Express was passing through Sher Shah Junction."


def _heard(text: str) -> list[dict]:
    return [{"text": w, "start": i * 0.4, "end": i * 0.4 + 0.3} for i, w in enumerate(text.split())]


def test_a_good_take_of_foreign_names_and_british_spelling_passes():
    heard = _heard("At 5.15 a.m., the Rahman Baba Express was passing through Shershah Junction.")
    words, match = align.align(BEAT, heard, 6.0)
    assert match >= voice.MIN_MATCH and [w["text"] for w in words] == BEAT.split()
    assert words[10]["start"] < words[11]["start"]  # "Sher" and "Shah" share the heard word's time in order
    _, match = align.align("Traveling at 100 kilometres per hour, the driver applied the brakes.",
                           _heard("Traveling at 100 kilometers per hour, the driver applied the brakes."), 5.0)
    assert match == 1.0


def test_a_cut_off_or_babbled_take_is_still_garbled():
    _, match = align.align(BEAT, _heard("At 5.15 a.m., the Rahman"), 2.0)
    assert match < voice.MIN_MATCH
    _, match = align.align(BEAT, _heard("Ah tuh mana bah ex was pass thru shuh junk"), 4.0)
    assert match < voice.MIN_MATCH
