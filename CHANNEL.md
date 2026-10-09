# Channel rules (binding for every Short)

The channel is **Orbitwire** (`@orbitwirenews`, `UCfqAy1IxE2Cwu9pmZGMambA`), a brand channel owned by
aksha.shivam18@gmail.com. It was called Rebuilt in 3D until 9 October 2026; the repo, site URL and upload tag marker
keep that old name on purpose. All browser work for it happens in Chrome Profile 5 only; never a work account.

## What it is

The world's most famous trending stories, shown in 3D: where and how it happened, on real terrain, from public data.
English, 40–60 second vertical Shorts, at most two a day and four hours apart.

A story qualifies only when the world is already looking at it (English Wikipedia's most-read list or Google Trends
in the US, India or the UK; see `studio/trends.py`) **and** it has the shape the channel can show honestly:

- an incident with a place on the map, at most 30 days old: flight incidents, earthquakes, storms, floods, wildfires,
  volcanoes, rail and maritime accidents, explosions, terror attacks, strikes in a war;
- the death of a famous person, at most 10 days ago (a "life map" of where they were born, worked and died).

Sport, celebrity gossip, elections and crime trials are out of scope even when they trend. Quakes also qualify without
a trend signal when USGS rates them PAGER yellow or worse, or magnitude 7+.

## Editorial standards

- Every number on screen or in the narration comes from a named public source listed in the description. `gate.py`
  enforces this mechanically. A death toll is said only when Wikipedia's infobox and Wikidata agree on it.
- Decorum: no victims, no bodies, no injuries shown or described in detail, no gore or sensational words, no
  "BREAKING", no emoji, no all-caps titles. Loss is stated plainly with official figures.
- Attacks: never name or show the attacker, never describe weapons or methods. Deaths: never speculate on a cause;
  no people convicted of crimes, no suicides.
- Every frame carries the badge "3D RECONSTRUCTION FROM DATA · NOT REAL FOOTAGE", and every upload sets YouTube's
  altered-or-synthetic-content flag.
- At most two loss stories in any three consecutive uploads where the trend list allows it.
- Corrections: a wrong fact is fixed in the description and pinned comment the same day; a wrong number on screen
  means the Short is made private and re-made.

## Lanes

| Lane | Status | Source |
|---|---|---|
| Earthquakes | Live | USGS event, PAGER, ShakeMap, moment tensor, DYFI |
| Trend radar | Live | Wikipedia pageviews, Google Trends RSS, Wikidata classes |
| Incidents (flights, attacks, disasters, conflict strikes) | Live | Wikidata (CC0) facts, Wikipedia infobox |
| Famous deaths (life map) | Live | Wikidata birth/death dates and places, confirmed by the infobox |

Incident Shorts wait until the article is 6 hours old. Summaries that guess at a cause (suspected, alleged, terror,
hijack, suicide…) are never read out; the Short says the cause is under investigation instead.

## Operations

- The hourly GitHub Actions run (`run.yml`) is the only publisher. Its state lives on the `state` branch.
- An open issue labelled `alert` means the studio needs attention; GitHub emails the repo owner.
- Never promise views or earnings; growth comes from accuracy, consistency and clarity.
