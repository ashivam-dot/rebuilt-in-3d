# Rebuilt in 3D

An unattended studio that watches official hazard feeds and rebuilds major events as 3D data graphics for YouTube
Shorts: terrain and sea floor from open elevation data, the quake drawn where seismologists located it, the shaking
mapped from the USGS ShakeMap, and every number said aloud traced to a primary source.

Channel: [Rebuilt in 3D](https://www.youtube.com/channel/UCfqAy1IxE2Cwu9pmZGMambA) ·
Site and privacy policy: <https://ashivam-dot.github.io/rebuilt-in-3d/>

## How a Short is made

| Step | Module | What it does |
|---|---|---|
| Watch | `studio/plan.py`, `studio/usgs.py`, `studio/gdacs.py` | Reads the USGS M4.5+ week feed and GDACS alerts; ranks M6+ quakes 3–96 hours old by significance and PAGER alert. |
| Facts | `studio/usgs.py` | Pulls the event, PAGER (exposure, cities, impact comments, history), moment tensor, ShakeMap contours, DYFI reports and aftershocks. |
| Script | `studio/quake.py` | Writes the narration beats deterministically from those facts. No language model; every number carries its source. |
| Gate | `studio/gate.py` | Refuses any number not backed by a sourced fact, gore or clickbait wording, emoji, shouting titles, missing sources or a missing disclosure badge; limits loss stories to 2 of any 3 uploads. |
| Voice | `studio/voice.py` | Kokoro-82M (Apache-2.0) on CPU, with word timings for captions. |
| Render | `studio/render.py`, `studio/web/` | three.js scene in headless Chromium (SwiftShader), captured frame by frame at 1080×1920, 30 fps; a generated drone bed; loudness to −14 LUFS. |
| Publish | `studio/youtube.py` | Uploads private, waits for processing, then goes public with the altered-or-synthetic-content flag set; never uploads the same story twice. |
| Memory | `studio/ledger.py` | `published.json`, `skipped.json`, `candidates.json` and `health.json` on the `state` branch. |

## Running it

```
uv sync --extra dev
uv run playwright install chromium-headless-shell
uv run python -m studio.cli watch            # what's eligible right now
uv run python -m studio.cli make us6000u0xi  # build, gate, voice and render one quake into work/
uv run python -m studio.cli publish eq-us6000u0xi
uv run python -m studio.cli run --dry        # one scheduled pass without publishing
uv run pytest
```

`.github/workflows/run.yml` runs one pass every hour on GitHub Actions; `health.yml` opens an issue when a run fails or
the studio goes quiet for four hours. The YouTube credential lives only in the `youtube` environment secret
`YOUTUBE_OAUTH_JSON`.

## Data and credits

Earthquake data: U.S. Geological Survey (public domain). Hazard alerts: GDACS (European Commission JRC / UN OCHA).
Terrain: Mapzen Terrain Tiles on AWS (SRTM, GMTED2010, ETOPO1, GEBCO and others; see the
[attribution](https://github.com/tilezen/joerd/blob/master/docs/attribution.md)). 3D engine: three.js (MIT). Font:
Inter (OFL). Voice: Kokoro-82M (Apache-2.0).
