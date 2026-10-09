# Channel rules (binding for every Short)

The channel is **Orbitwire** (`@orbitwirenews`, `UCfqAy1IxE2Cwu9pmZGMambA`), a brand channel owned by
aksha.shivam18@gmail.com. It was called Rebuilt in 3D until 9 October 2026; the repo, site URL and upload tag marker
keep that old name on purpose. All browser work for it happens in Chrome Profile 5 only; never a work account.

## What it is

The world's most famous trending stories, told as short documentaries: real photos of the person or the event, a
story with feeling, and facts checked against public sources. English, 35–50 second vertical Shorts, at most three a
day and three hours apart.

A story qualifies only when the world is already looking at it (English Wikipedia's most-read list or Google Trends
in the US, India or the UK; see `studio/trends.py`) **and** it can be shown honestly:

- an incident at most 30 days old: flight incidents, storms, floods, wildfires, volcanoes, rail and maritime
  accidents, explosions, terror attacks, strikes in a war; earthquakes keep their 3D terrain format;
- the death of a famous person, at most 10 days ago.

## How a story Short looks (since 9 October 2026)

The owner rejected the first format (a map with a flat voice reading facts) as lifeless; it must never come back.

- **Pictures:** at least three real, freely licensed photos from Wikimedia Commons (CC0, public domain, CC BY,
  CC BY-SA; never non-commercial or fair-use files), each credited by author and licence in the description and on
  screen. For a person, every photo must show them: their face is matched across the set. A gentle depth-parallax
  camera move brings each still to life; nothing in a photo is invented or altered.
- **Never** generate a realistic image or video of a real person or a real incident. YouTube removes realistic
  simulations of deceased people and of victims, and it would break the channel's promise of real facts.
- **Story, not a résumé:** a hook that says plainly what happened; then where they began, the turning point, the
  work people loved (named, with years on screen), a human detail, and what they leave behind. On-screen chips name
  works, roles, honours or years, never places (a place over a photo reads as where it was taken).
- **Voice:** an expressive AI voice (Chatterbox), each line checked by speech recognition before use; word-by-word
  captions; a quiet score written in code.
- **Checks:** every name and number in the script must appear in the Wikipedia article or the confirmed Wikidata
  facts, and a second model pass lists anything unsupported. Deaths and casualty counts keep the two-source rule.

Sport, celebrity gossip, elections and crime trials are out of scope even when they trend. Quakes also qualify without
a trend signal when USGS rates them PAGER yellow or worse, or magnitude 7+.

## Editorial standards

- Every number on screen or in the narration comes from a named public source listed in the description. `gate.py`
  enforces this mechanically. A death toll is said only when Wikipedia's infobox and Wikidata agree on it.
- Decorum: no victims, no bodies, no injuries shown or described in detail, no gore or sensational words, no
  "BREAKING", no emoji, no all-caps titles. Loss is stated plainly with official figures.
- Attacks: never name or show the attacker, never describe weapons or methods. Deaths: never speculate on a cause;
  no people convicted of crimes, no suicides.
- 3D quake frames carry the badge "3D RECONSTRUCTION FROM DATA · NOT REAL FOOTAGE"; photo stories end on a card
  saying "Real photos: Wikimedia Commons · Narration: AI voice". Every upload sets YouTube's
  altered-or-synthetic-content flag.
- At most two loss stories in any three consecutive uploads where the trend list allows it.
- Corrections: a wrong fact is fixed in the description and pinned comment the same day; a wrong number on screen
  means the Short is made private and re-made.

## Lanes

| Lane | Status | Source |
|---|---|---|
| Earthquakes | Live | USGS event, PAGER, ShakeMap, moment tensor, DYFI |
| Trend radar | Live | Wikipedia pageviews, Google Trends RSS, Wikidata classes |
| Incidents (flights, attacks, disasters, conflict strikes) | Live, photo story | Wikipedia article, Wikidata, Commons |
| Famous deaths | Live, photo story | Wikipedia article, Wikidata dates confirmed by the infobox, Commons |

Incident Shorts wait until the article is 6 hours old. Summaries that guess at a cause (suspected, alleged, terror,
hijack, suicide…) are never read out; the Short says the cause is under investigation instead.

## Operations

- The hourly GitHub Actions run (`run.yml`) is the only publisher. Its state lives on the `state` branch. Setting
  the repository variable `PAUSED` to `true` holds the schedule; manual runs still work.
- An open issue labelled `alert` means the studio needs attention; GitHub emails the repo owner.
- Never promise views or earnings; growth comes from accuracy, consistency and clarity.
