# Channel rules (binding for every Short)

The channel is **Orbitwire** (`@orbitwirenews`, `UCfqAy1IxE2Cwu9pmZGMambA`), a brand channel owned by
aksha.shivam18@gmail.com. It was called Rebuilt in 3D until 9 October 2026; the repo, site URL and upload tag marker
keep that old name on purpose. All browser work for it happens in Chrome Profile 5 only; never a work account.

## What it is

The world's most famous trending stories, told as short documentaries: real photos of the person or the event, a
story with feeling, and facts checked against public sources. English, 35–60 second vertical Shorts.

A story qualifies only when the world is already looking at it (Google News lead stories for India, the US, the UK
and the world; Google Trends in the US, India or the UK, any listed search; English Wikipedia's most-read list; the
story articles on today's and yesterday's Wikipedia Current events page, each counting like two lead headlines; a
GDACS Orange or Red alert from the last 4 days, through its disaster's own article; see `studio/news.py` and
`studio/trends.py`) **and** it can be shown honestly:

- an incident at most 30 days old: flight incidents, storms, floods, wildfires, volcanoes, rail and maritime
  accidents, explosions, terror attacks, strikes in a war; earthquakes keep their 3D terrain format;
- a protest or public movement that at least two lead stories are about, that Wikidata does not mark as ended, and
  that began within two years (movements need a start date, so ideologies stay out). A months-old war is not
  ongoing news: its Shorts came out as generic "human cost" pieces with casualty claims, so only its new strikes
  and attacks qualify, as incidents;
- the death of a famous person, at most 10 days ago.

**Fresh articles (2026-10-13).** A brand-new event article often has no Wikidata item for its first day, exactly while
the story is hottest. It still qualifies when its English title names this or last year and an incident or protest
shape ("2026 Erie shooting"; riots, trials, elections and sport never). Its date comes from the infobox, its location
photos from the places the infobox links to (never a map, never one that features a face), its id is
`wp-<article title>` (so it never comes back as `wk-<QID>`), and with no Wikidata to agree with, no casualty number
is ever said. Wikipedia's search ranks long-standing articles first, so headlines and Trends news items are also
matched by their words to people Wikidata says died in the last 10 days and to fresh event articles (a person by
their whole name in order, an event by its place or name plus one more title word; a headline two items fit
matches nothing). The most-read list is read 1000 deep for those. Titles of works that contain a banned word
("Breaking Bad") are names, not wording; banned words match whole words only (so "category" is not "gory").

**Trusted sources beyond Wikipedia (2026-10-13; owner: "don't relay on wikipedia only search for other trusted souces
as well").** `studio/outlets.py` (the same file as the Hindi desk's `desk/outlets.py`) keeps an allowlist of trusted
outlets with public RSS feeds; Orbitwire reads the English ones: official (PIB), public broadcasters (BBC World, BBC
India, DW, NPR), international (Al Jazeera, The Guardian) and Indian national (The Hindu, Hindustan Times, Times of
India). Each outlet has an `owner`; sister brands count once (the BBC's feeds are one owner). Feeds are read in
parallel once a run (36 hours back); a feed that fails is listed in the run's errors and the rest still count.
Articles are read with trafilatura (20 s timeout, at most 12 a run, cached). Outlet photos are never used.
Plain-http links are read as https.
- **Discovery:** outlet headlines join Google News: matched to a Wikipedia article the same way, each independent
  owner adding one lead headline's fame (at most 6). Only national sections count as an India signal; Times of
  India top stories mixes India and world news and never makes a story an India story.
- **Corroboration:** the writer gets a REPORTING block of 2-4 articles about the story (named by its headline or
  summary, inside its time window), each from a different owner, official, public and international ones first; a
  report found at discovery is used only if it names the story. Every name and number must be in Wikipedia/Wikidata
  or in the articles of at least two independent owners; one outlet alone never backs a fact (the writer's checks and
  `studio/gate.py` both refuse it, and the line-by-line fact check sees each report sentence marked with its owner).
  A casualty number still needs the infobox and Wikidata to agree, or else two owners stating the same exact number
  (no hedge before or after it, such as "at least" or "or more"; no other number from any outlet; never a number
  different from the infobox's; and Wikidata agreeing when it has one), or one owner and Wikidata's only toll. The
  toll reaches the writer as a confirmed fact: every sentence about deaths, bodies or injuries is removed from the
  articles, as are sentences about suicide and, for an incident, any naming a suspect, attacker or arrest.
- **Stories Wikipedia has no article for yet** (`nw-<yyyymmdd>-<place>-<kind>`): at least 3 independent owners
  within 24 hours, one of them official, a public broadcaster or international, whose headlines name the same
  incident or protest (same scope rules). They are told only from the reporting (at least two owners' articles must
  name the place), with photos of the place (Commons, then Openverse; the place must be a Wikidata item with
  coordinates, never a person). Once Wikipedia writes the article, the story is not told again for 7 days, and the published
  record keeps the report URLs and headlines so the Hindi desk's overlap rules match nw- stories too. **The lane is
  on (2026-10-13)** through the repository variable `STUDIO_NEW_STORIES=true`, passed into the run job's `env` in
  `.github/workflows/run.yml`. Set the variable to anything else to turn it off: the radar then still finds and logs
  these stories (the run's "outlets:" step) but does not offer them.
- **Photos:** when Commons has fewer than 3 usable photos, Openverse (keyless; CC0, CC BY and CC BY-SA only) fills
  in with photos of the places the story links to (Wikidata items with coordinates; never a person, group or work),
  never one that features a face.
- **Description:** "Sources: Wikipedia, BBC, The Hindu" names the outlets behind the facts, then every URL.

## The editorial desk (`studio/plan.py`)

The owner wants hot news caught on time without stepping in; the desk decides what goes out and when.

- Priority is fame halved every half-life (18 h for protests, 36 h for deaths), so a fresh story beats a bigger
  stale one. A follow-up headline does not make an old incident fresh.
- India stories go out 09:00–23:00 IST, world stories 07:00–24:00 US Eastern; at most five a UTC day, two hours
  apart. Breaking news (fame 400k+ and under 12 hours old, or a quake that is magnitude 7+ or PAGER orange/red) may
  go out at any hour as a sixth, 75 minutes after the last; wars never take the breaking lane.
- An ongoing story comes back at most once in 6 days, whatever its id, including hand-made series parts.
- Without a death toll that Wikipedia and Wikidata agree on, an incident never mentions casualties (gate), and
  photo collages are never used (they mix in injured people).
- A big ongoing story may be told as a 2–3 part series (Part N title, a teaser for the next part, editor-picked
  Commons photos). Parts can be scheduled with YouTube's own `publishAt`; the ledger records the release time, and
  the desk keeps two hours clear around it.
- The run happens every 30 minutes.

## How a story Short looks (since 9 October 2026)

The owner rejected the first format (a map with a flat voice reading facts) as lifeless; it must never come back.

- **Pictures:** at least three real, freely licensed photos from Wikimedia Commons (CC0, public domain, CC BY,
  CC BY-SA; never non-commercial or fair-use files), each credited by author and licence in the description and on
  screen. For a person, every photo of a person must show them: their face is matched across the set. A story with
  fewer than three photos of its own (a tribute needs at least one matched photo of its subject) is filled with
  photos of the places and things it links to: a person's birthplace, school, employer, team or award, an
  incident's places. A fill photo never features a face. A gentle depth-parallax camera move brings each still to
  life; nothing in a photo is invented or altered.
- **Never** generate a realistic image or video of a real person or a real incident. YouTube removes realistic
  simulations of deceased people and of victims, and it would break the channel's promise of real facts.
- **Story, not a résumé:** a hook that says plainly what happened; then where they began, the turning point, the
  work people loved (named, with years on screen), a human detail, and what they leave behind. On-screen chips name
  works, roles, honours or years, never places (a place over a photo reads as where it was taken).
- **Voice:** an expressive AI voice (Chatterbox), each line checked by speech recognition before use; word-by-word
  captions; a quiet score written in code. Two lanes, chosen by the story's region: India stories clone an Indian
  English reference (`tts/voices/india.wav`, Veena "kavya", Apache-2.0), all others a clear, warm US voice
  (`tts/voices/world.wav`, Kokoro "am_puck", Apache-2.0). Both were chosen by measured accent, naturalness (UTMOS
  4.5) and intelligibility; gated models that need a token are not used.
- **Protests:** strictly neutral. Claims are attributed ("organisers said", "police said"); the script never urges
  anyone to join or avoid a protest, and suicide is never mentioned (such sentences are removed from the source).
  Headlines are context only, and only those whose names and numbers the article confirms reach the writer.
- **Checks:** every name and number in the script must appear in the Wikipedia article or the confirmed Wikidata
  facts. Each line must quote the source sentence that supports it; the quote is verified against the sources, and
  a line that fails gets a second look against its best-matching source sentences before the draft is rewritten
  (three drafts, then the story is dropped). Deaths and casualty counts keep the two-source rule. The dry run of
  2026-10-09 (run 37984798160) dropped a Mike Ditka draft for an unsourced anecdote and corrected an Eva Marie
  Saint line ("two children" became the sourced "four grandchildren"); the hourly desk was unpaused after it.

Sport, celebrity gossip, election results and crime trials are out of scope even when they trend. Quakes also qualify without
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

Incident Shorts wait until the article is 6 hours old; waiting never counts as a failed try, so a fresh story is not
given up before it is ready. Summaries that guess at a cause (suspected, alleged, terror,
hijack, suicide…) are never read out; the Short says the cause is under investigation instead.

## Operations

- The half-hourly GitHub Actions run (`run.yml`) is the only automatic publisher; hand-made series parts are
  published from the Mac with `.scratch/publish_story.py` and recorded in the same ledger. Its state lives on the `state` branch. Setting
  the repository variable `PAUSED` to `true` holds the schedule; manual runs still work.
- An open issue labelled `alert` means the studio needs attention; GitHub emails the repo owner.
- Never promise views or earnings; growth comes from accuracy, consistency and clarity.
