# Channel rules (binding for every Short)

The channel is **Rebuilt in 3D** (`UCfqAy1IxE2Cwu9pmZGMambA`), a brand channel owned by aksha.shivam18@gmail.com.
All browser work for it happens in Chrome Profile 5 only; never a work account.

## What it is

Explainers, not breaking news: 3D data reconstructions of major hazards, published 3–96 hours after the event when
official products (USGS PAGER, ShakeMap, moment tensor) exist. English, 40–60 second vertical Shorts, at most two a day
and four hours apart.

## Editorial standards

- Every number on screen or in the narration comes from a primary source listed in the description. `gate.py`
  enforces this mechanically.
- Decorum: no victims, no bodies, no injuries shown or described in detail, no gore or sensational words, no
  "BREAKING", no emoji, no all-caps titles. Loss is stated plainly with official estimates and their uncertainty.
- Every frame carries the badge "3D RECONSTRUCTION FROM DATA · NOT REAL FOOTAGE", and every upload sets YouTube's
  altered-or-synthetic-content flag.
- At most two loss stories in any three consecutive uploads; the rest are non-loss science stories.
- Celebrity deaths, terror attacks and wars are not core categories. They are never rebuilt in 3D.
- Corrections: a wrong fact is fixed in the description and pinned comment the same day; a wrong number on screen
  means the Short is made private and re-made.

## Lanes

| Lane | Status | Source |
|---|---|---|
| Earthquakes M6+ | Live | USGS event, PAGER, ShakeMap, moment tensor, DYFI |
| Tropical cyclones, volcanoes, floods | Planned | GDACS, NHC/JTWC, Smithsonian GVP |
| Aviation incidents | Planned | ADS-B Exchange-style open feeds (adsb.lol), official investigator reports |

## Operations

- The hourly GitHub Actions run (`run.yml`) is the only publisher. Its state lives on the `state` branch.
- An open issue labelled `alert` means the studio needs attention; GitHub emails the repo owner.
- Never promise views or earnings; growth comes from accuracy, consistency and clarity.
