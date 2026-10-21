# Channel rules (binding for every Short)

The channel is **Orbitwire** (`@orbitwirenews`, `UCfqAy1IxE2Cwu9pmZGMambA`), a brand channel owned by
aksha.shivam18@gmail.com. It was called Rebuilt in 3D until 9 October 2026; the repo and site URL keep that old name
on purpose. All browser work for it happens in Chrome Profile 5 only; never a work account.

**Which video is which story is the ledger's business, not a public tag (2026-10-22).** Uploads until then carried
`rebuilt-in-3d:<story id>` (e.g. `rebuilt-in-3d:wk-Q123`) among their public tags, a machine identifier anyone can
read in the page source. New uploads carry topic tags and "Orbitwire" only. The upload's video id is written to
`state/uploads.json` the moment YouTube accepts the file (so a run cut short while it processes finishes that upload
next time instead of uploading again) and moves to `published.json` once it is public. `youtube.find` checks the
ledger first, then still reads the old marker on recent uploads, so no story uploaded before the change is ever
uploaded twice; the old tags are left on those videos (rewriting 40 snippets costs quota and could undo Studio
edits, and a stale tag does no harm). When neither finds it, an upload under 48 hours old that no ledger row or old
tag claims and whose description lists the story's Wikipedia or first source URL on its own line is the same story
under a lost state save (a failed rebase or push, a lost runner): the run never uploads it again, skips the story
and reports `hold <id>` with the video id in the steps and warnings, for a person to publish or delete in Studio.
An upload left in `uploads.json` for 24 hours or more (its story failed or was skipped on the rebuild, so a private
video waits on the channel) is reported as `stale upload <id>` on every run until a person clears it.

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
as well").** `studio/outlets.py` (started as the Hindi desk's `desk/outlets.py`; since 2026-10-14 it adds world outlets and wire dedupe) keeps an allowlist of trusted
outlets with public RSS feeds; Orbitwire reads the English ones: official (PIB), public broadcasters (BBC World, BBC
India, DW, NPR, France 24), international (Al Jazeera, The Guardian) and Indian national (The Hindu, Hindustan Times,
Times of India, NDTV). Each outlet has an `owner`; sister brands count once (the BBC's feeds are one owner). PIB,
NDTV and France 24 get a browser's request headers (they refuse others with 403); a headless browser (Crawl4AI) was
benchmarked on 2026-10-13 and read nothing more, with noisier text. Feeds are read in
parallel once a run (36 hours back); a feed that fails is listed in the run's errors and the rest still count.
Articles are read with trafilatura (20 s timeout, at most 12 a run, cached). Outlet photos are never used.
Plain-http links are read as https.
**World outlets (2026-10-14 speed-up; owner: "do similar kind of speedup for orbitwire").** The list leaned Indian, so
world incidents rarely reached three owners. Added: BBC top stories, NPR's news feed, ABC (Australia), UN News, The Independent,
Euronews, SCMP, Guardian US, CBS, NBC, ABC News (US), Fox News and the LA Times (each probed from the Mac on
2026-10-14: fresh items and readable article text). Not added: Sky, NYT, PBS and Japan Times (no article text), AP
(403), CBC (timeout), CNN, USA Today and ReliefWeb (no fresh items). **Wire copy counts once:** an article with an
AP, Reuters, AFP, PTI, ANI or IANS dateline or byline counts as that agency, not its publisher, and two articles
whose text is at least half the same are one owner; a story with fewer than two owners left gets no REPORTING.
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
  incident or protest (same scope rules). A headline joins a story only when it matches most of the story's
  headlines, so one headline naming two incidents never chains them together; a headline left alone because it came
  before the one linking it to a story joins afterwards by the same rule. **Headline kinds (2026-10-14):** besides
  crashes, attacks, explosions, disasters and protests, flight incidents (an aircraft diverted, an emergency landing,
  a hijack alert or threat, a bomb threat or scare, turbulence, an engine fire or failure, a mayday), a war's new
  strikes (missiles, drones, rockets or shelling that hit something, air strikes, strikes on power, fuel, oil, ports
  and other infrastructure; never a labour strike, a deal, a warning, a drill, a test or a space launch) and
  cyberattacks qualify. Live blogs, videos, explainers and the rest of the skip list still never do. Words that only
  say what kind of incident it is ("flight", "diverted", "bomb threat", "missile") never match two headlines, so two
  flights diverted after bomb threats on one day stay two stories. The 2026-10-13/14 feeds missed the Houthi strike on
  an Aramco building (BBC, The Guardian, Euronews), which now forms one story; the Air India hijack alert reached
  three owners that are all Indian national outlets, so it still needs one official, public or international outlet.
  **Attackers are never named:** an attack or strike story's name is never an armed group or whoever the headlines
  say struck ("Houthi missile", "Russia's strikes", "Saudi-led", "Russia pounds Kharkiv"); those names go to the
  writer as banned words (plural and adjective forms included), and its draft is rewritten if it uses one. A story
  named by a company or building ("Aramco") takes its photos from the next name in its headlines that is a place and
  that two owners' articles name. They are told only from the reporting (at least two owners' articles must
  name the place), with photos of the place (Commons, then Openverse; the place must be a Wikidata item with
  coordinates, never a person). Once Wikipedia writes the article, the story is not told again for 7 days, and the published
  record keeps the report URLs and headlines so the Hindi desk's overlap rules match nw- stories too. **The lane is
  on (2026-10-13)** through the repository variable `STUDIO_NEW_STORIES=true`, passed into the run job's `env` in
  `.github/workflows/run.yml`. Set the variable to anything else to turn it off: the radar then still finds and logs
  these stories (the run's "outlets:" step) but does not offer them.
- **Photos:** when Commons has fewer than 3 usable photos, Openverse (keyless; CC0, CC BY and CC BY-SA only) fills
  in with photos of the places the story links to (Wikidata items with coordinates; never a person, group or work),
  never one that features a face.
- **NASA photos (2026-10-22):** a natural-disaster story (cyclone, volcano, flood, wildfire, landslide, tsunami,
  earthquake, disaster) still short of photos searches the NASA Image and Video Library (keyless) for its name and
  places, with an event word in the title ("hurricane", "lava"…), taken from two days before the event on.
  Licence "Public domain (NASA)", credit "NASA": a record whose credit names anyone but NASA and its centres (JPL,
  GSFC…, NOAA, USGS) or says "courtesy", ©, a partner agency or a picture desk is refused, and so is one whose
  description names a partner's data however it is written (Copernicus/Sentinel, European Space Agency,
  Himawari/Japan Meteorological Agency, EUMETSAT/Meteosat, KOMPSAT/KARI…) or data "processed/provided/operated by"
  anyone but NASA, NOAA, USGS or another US federal body (Earth Observatory credits itself for imagery made from such
  data). Radar, infrared, false-colour, annotated, illustration and model images are refused whether the title or
  the description says so, as is one that features a face. At most two frames under one title. The
  photo floors (2, a tribute 3) are unchanged. Smithsonian is not used: its open-access images are museum objects,
  never what happened.
- **Description:** "Sources: Wikipedia, BBC, The Hindu" names the outlets behind the facts, then every URL. YouTube
  refuses a description over 5,000 bytes, so a long one drops the narration first and keeps every source and
  photo credit.

## The editorial desk (`studio/plan.py`)

The owner wants hot news caught on time without stepping in; the desk decides what goes out and when.

- Priority is fame halved every half-life (18 h for protests, 36 h for deaths), so a fresh story beats a bigger
  stale one. A follow-up headline does not make an old incident fresh.
- India stories go out 09:00–23:00 IST. World stories go out whenever Europe or the US is awake: 07:00–24:00 London
  time or 07:00–24:00 New York time, following daylight saving (06:00–04:00 UTC in summer, 07:00–05:00 UTC in
  winter), so only about two hours a night are closed. At most twelve a UTC day, 40 minutes apart. **Second speed-up
  (2026-10-14; owner: Orbitwire "must be among the most active channels"):** in the 36 hours before, 72 holds were
  "outside the world window" (07:00–24:00 US Eastern closed it 04:00–11:00 UTC, while Europe and Asia were awake) and
  55 were the one-hour gap; the first speed-up that morning had already raised five a day, two hours apart, to eight,
  one hour apart. There is no minimum per day: a quota would force weak stories. Breaking news (under
  12 hours old with fame 400k+, or an incident five independent outlets report, two of them official, public or
  international; or a quake that is magnitude 7+ or PAGER orange/red) may go out at any hour as one more, 30 minutes
  after the last; wars, their strikes and ongoing protests never take the breaking lane. YouTube gives each project
  100 uploads a day of its own quota, so uploads are not the limit.
- **Ad suitability as a tie-break (2026-10-21):** an attack, or an incident whose title says shooting, stabbing or
  attack (never a tribute: "heart attack" is not violence), that is not breaking ranks at 0.85
  of its fame (`plan.AD_SUITABILITY`), so between two similar stories the desk leads with the one advertisers run
  against; a breaking one keeps its full rank, and a clearly bigger attack still leads. The health log lists the
  stories it scaled ("ad-suitability x0.85 ...") as a step of its own, after the hold notes. It changes order only,
  never what is told or how.
- **Big incidents are told while they happen (2026-10-14; owner: "these two channels should be fully active and
  publishing the videos as a big incident happen").** A Wikipedia article under 6 hours old is still not used (its
  facts move), but when at least three independent outlets, one of them official, public or international, already
  report the incident, it is told at once from that reporting, exactly as an nw- story (two owners for every fact,
  no toll unless the reports agree on it). The published record keeps the article's title, so the story is not told
  again from Wikipedia later.
- An ongoing story comes back at most once in 6 days, whatever its id, including hand-made series parts.
- Without a death toll that Wikipedia and Wikidata agree on, an incident never mentions casualties (gate), and
  photo collages are never used (they mix in injured people).
- A big ongoing story may be told as a 2–3 part series (Part N title, a teaser for the next part, editor-picked
  Commons photos). Parts can be scheduled with YouTube's own `publishAt`; the ledger records the release time, and
  the desk keeps the regular gap clear around it.
- The run happens every 30 minutes.

## How a story Short looks (since 9 October 2026)

The owner rejected the first format (a map with a flat voice reading facts) as lifeless; it must never come back.

- **Pictures:** real, freely licensed photos from Wikimedia Commons (CC0, public domain, CC BY,
  CC BY-SA; never non-commercial or fair-use files), each credited by author and licence in the description and on
  screen: at least two for an incident or an nw- story (since 2026-10-14; Hurricane Rachel was dropped after six
  runs with two), whose beats then take turns between them with different camera moves, and at least three for a
  tribute. For a person, every photo of a person must show them: their face is matched across the set. A tribute
  with no matched photo of its subject is dropped at once, not retried (2026-10-14: Madhu Kambikar, Doug Loft and
  Lucian Piane had each used five or six runs with none); one short of photos is still retried. A story with
  fewer than three photos of its own (a tribute needs at least one matched photo of its subject) is filled with
  photos of the places and things it links to: a person's birthplace, school, employer, team or award, an
  incident's places. A fill photo never features a face. A gentle depth-parallax camera move brings each still to
  life; nothing in a photo is invented or altered. A person's solo portraits come before photos where they stand
  with others. A photo's Commons description is never a source for a fact.
- **Never** generate a realistic image or video of a real person or a real incident. YouTube removes realistic
  simulations of deceased people and of victims, and it would break the channel's promise of real facts.
- **Story, not a résumé:** a hook that says plainly what happened; then where they began, the turning point, the
  work people loved (named, with years on screen), a human detail, and what they leave behind. On-screen chips name
  works, roles, honours or years, never places (a place over a photo reads as where it was taken).
- **Hook first (2026-10-21; the Phase 1 hook the owner approved on 2026-10-20, ported from Kyun Hua's `HOOK_WORDS`):**
  tributes that opened "X has died" held 41-43% of viewers for 16-19 s, against 64-101% for Shorts that opened on the
  event. Beat 1 now opens on the single most striking verified fact, with the name or the event in its first 4
  words; a dateline opener ("On 8 October...", "In 2026...", "Last week...") or a bare "<name> has died" is rewritten
  (a name or event that itself starts with a month, weekday or year is not a dateline: "June Carter Cash's voice",
  "The 2026 Kenyan protests drew"; nor is a count, "4000 homes", or a compound, "Late-night host", "This year's"),
  on the first two drafts; the third is judged on the fact checks alone, so a hook or title miss (below) never
  costs a story (2026-10-22: the channel is short of stories, not of hooks). The first frame shows a 3-6 word claim in beat
  1's own words (`hook`, checked like the script by the draft checks and `gate.py`) with the name under it when the
  claim lacks it, instead of the name over the years.
- **Titles (2026-10-21):** searchable core first (the name or place and what happened, its key words in the first 4
  words); never "The Legacy of", "A Tribute to", "The Life and Legacy" or "The Path of" (they made every tribute and
  storm title read alike), and never the same first 3 words as any of the last 20 published titles about other
  stories (a series part or a returning ongoing story leads with its name, as its earlier titles did).
  Since 2026-10-22 a title may be framed on a cause or an outcome the sources state: "How Hurricane Milton Grew to
  Category 5 in a Day", "Why the Tigray War Displaced Millions", "<X> Exists Because of <Y>", with the same
  name-first, template and recent-opener rules. Such a title makes a claim, so the evidence check reads it with the
  beats, labelled "TITLE:" (a verdict the checker leaves out for it counts as a flag, and the rewrite note says "the
  title"); on the last draft, when every beat is supported and only the title is not, the beats are kept under the
  plain title ("<Name>: what happened", "Remembering <Name>") instead of losing the story. A question mark or a vague tease ("What Happened Next", "The Real Reason", "Here's Why") is sent back on
  the first two drafts, and "Why" is never used for a cause the sources call unknown or under investigation.
  Quake titles lead with magnitude and the nearest named place, then the impact (people in strong shaking or worse,
  else the
  PAGER alert, else the depth), rotating between phrasings so no two open alike; "How the M… quake ruptured, in 3D"
  is retired (7 titles in a row opened that way).
- **The close (2026-10-22):** the last beat says what happens next or why it matters, with a fact from the sources
  (the inquiry, the vote, the rebuilding, the work that lives on), checked like every other beat. A call to
  follow, like or subscribe, the channel's name or a filler close ("only time will tell", "remains to be seen") is
  sent back on the first two drafts and never costs a story. A series part still ends on what Part N+1 tells. The
  spoken "Follow Orbitwire for the stories the whole world is talking about." is gone: it was the same 4 s on
  every Short. The end card (logo, "Sources in the description", the real-photos/AI-voice disclosure) holds
  silently for 2 s. The quake lane's own outro and the retired 3D story lane (`studio/stories.py`) are unchanged.
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
  (three drafts, then the story is dropped). Deaths and casualty counts keep the two-source rule. Since
  2026-10-14 the draft checks also catch what only the final gate used to: a banned word, any mention of deaths or
  injuries when the sources agree on no toll, and a number no source backs. These are rewritten, and a gate failure
  for them is retried on a later run instead of dropping the story for good (Hurricane Isaias, the Saudi airport
  attacks, RJ Mitte and Aubagne had been dropped for one word; their skips were lifted). The dry run of that day
  (run 38457366569, Hurricane Isaias) had every number right but turned "60 evacuated over the risk of landslides"
  into "families faced landslides", and a Saudi airports draft invented "hit first", ended on a moral and captioned
  airports. So the writer keeps each fact exactly as strong as its source (a risk or warning is not an event), adds
  no order and no moral, and a caption naming a place (airport, hospital, station, street, mosque...) is rewritten. The dry run of
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
  saying "Real photos: Wikimedia Commons · Narration: AI voice" (naming Openverse or NASA too when
  they supplied any). Every upload sets YouTube's
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
- **Wikidata outages (2026-10-21):** the recent-deaths query timed out ("Read timed out. (read timeout=45)") on 7 of
  80 runs, each time blinding the death lane. It now reads up to 65 s (the query service stops a query at 60 s),
  tries three times with backoff, and the last good list (`state/recent_deaths.json`) stands in for up to 3 hours;
  the run's trend radar errors say when it did.
- **What the numbers teach the desk (`studio/learn.py`):** every 3 hours the run reads each Short's public views and
  scores it by its views at 24 h; a story kind or category needs 4 scored Shorts before it lifts or lowers a
  candidate's rank (shrunk toward 1, kept within x0.75-x1.35). Since 2026-10-22 it also reads YouTube Analytics
  (views, engaged views, average percentage viewed) for Shorts at least 3 days old, and blends a group's retention
  into its lift at half weight, as the Hindi desk does. That needs the sign-in to carry the
  `yt-analytics.readonly` scope; without it the run's health says so once ("analytics: ...") and lifts are views
  alone. Everything lands in `state/performance.json` and `state/LEARNINGS.md`.
- Never promise views or earnings; growth comes from accuracy, consistency and clarity.

## Decisions log

| Date | Decision | Evidence |
|---|---|---|
| 2026-10-22 | Stop writing the public tag `rebuilt-in-3d:<story id>`; the ledger (`state/published.json`, `state/uploads.json`) identifies uploads, the old tag is still read | All 40 uploads in `state/published.json` carry it in their public tags (page source); YouTube's inauthentic-content review looks at templated, machine-made signals |
| 2026-10-22 | NASA Image and Video Library photos for natural-disaster stories (public domain, NASA's own credit only, of the event); Smithsonian not used | 26 of the 44 stories in `state/skipped.json` were dropped for "only N usable photos"; recorded search (`tests/fixtures/nasa-hurricane-milton.json`): 6 ISS photos of Milton pass, the ASTER (METI/Japan), ASI radar and 2017 "courtesy" records do not |
| 2026-10-22 | Blend YouTube Analytics retention into the desk's lifts (needs the `yt-analytics.readonly` scope, else a no-op with one health note) | Views alone rank: 40 Shorts at 0-1,626 views (`state/performance.json`, 2026-10-21 18:07 UTC) say who clicked, not what held them; retention ranged 41-43% (tribute "has died" openers) to 64-101% (event openers) |
| 2026-10-22 | The last beat closes on what happens next or why it matters; the spoken "Follow Orbitwire..." outro is dropped, the end card holds silently for 2 s | The same 10-word line (about 4 s) ended every story Short: identical narration across uploads is a templated signal, and a call to action is the last thing heard instead of the story |
| 2026-10-22 | Curiosity titles ("How/Why <thing> <outcome>", "<X> Exists Because of <Y>") where the sources state it, fact-checked; teases refused | Titles read as wire headlines ("<Place> <Event>: <What Happened>"); the How/Why framing names a specific outcome while keeping the searchable name first |
| 2026-10-22 | NASA records naming a partner's data in the description (Copernicus Sentinel, ESA, Himawari/JMA, EUMETSAT, KOMPSAT/KARI, "processed by" a non-US-federal party) are refused; the not-a-photo check reads the description too | Review of the NASA tier: an Earth Observatory record credited "NASA Earth Observatory/Lauren Dauphin" over "Copernicus Sentinel-2 data processed by the European Space Agency", and a Himawari-9 record "operated by the Japan Meteorological Agency", both passed as public domain; typhoon and storm stories are the tier's main use |
| 2026-10-22 | An upload under 48 h old with this story's source URL that the ledger lost is held, never re-uploaded; `uploads.json` entries 24 h old are reported | Without the public tag, a failed "Save state" step (rebase conflict, push, lost runner) left nothing to find the upload by; a second copy of a story is the repetitive-content signal this batch removes |
| 2026-10-22 | A curiosity title flagged on the last draft falls back to the plain title; the checked title is labelled and a missing verdict counts against it | A title-only flag on draft 3 failed a story whose every beat was supported ("no draft passed the fact checks"); 26 of 44 skips were already for want of photos, so supply is the constraint |
