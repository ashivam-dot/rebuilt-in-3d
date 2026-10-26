"""Plan an episode: choose the topic (topics.py), read its open data (data.py), and lay out the seven chapters with
the facts each may state, the source text beside them, and the shots it shows. No model runs here: every fact is a
sentence built from a data field, so the writer can only retell what the data says.

The title follows the design's formula "<Place/Event> <mechanism or number>" from fixed templates (gated by
writer.title_problems and gate.banned_word): a model-written title is the one thing the evidence check cannot hold to
a number. "in 3D" is never claimed: the episode's pictures are data maps and charts, not the Shorts' 3D stage.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone

from .. import gate, ledger, terrain, usgs, wiki, writer, youtube
from ..spec import Fact
from . import data, topics
from .spec import Chapter, Episode

HISTORY_KM = 500
HISTORY_MAG = 6.0
HISTORY_START = "1900-01-01"
STORM_KM = 400
PUBLISH_WEEKDAY, PUBLISH_HOUR = 5, 14  # Saturday 14:00 UTC: US morning, Europe afternoon, India evening
BUILD_HOURS = 6  # the build's own wall time: a slot closer than this goes to the next Saturday
WIKI_CREDIT = "Text: Wikipedia (CC BY-SA 4.0)"
CREDITS = ["Narration: AI voice (Chatterbox, MIT licence), script checked line by line against the sources",
           "Music: original, generated in code by Orbitwire", terrain.CREDIT]
QUAKE_CREDIT = "Earthquake data: U.S. Geological Survey ComCat, PAGER, ShakeMap and event pages (public domain)"
STORM_CREDIT = "Storm data: NOAA National Hurricane Center best tracks and HURDAT2 (public domain)"
NHC_GLOSSARY = "https://www.nhc.noaa.gov/aboutgloss.shtml"
NHC_CLIMO = "https://www.nhc.noaa.gov/climo/"
SEASON = {"al": "June 1 to November 30", "ep": "May 15 to November 30", "cp": "June 1 to November 30"}
CASUALTY_SENTENCE = writer.CASUALTY_WORDS
MMI_WORDS = {5: "moderate", 6: "strong", 7: "very strong", 8: "severe", 9: "violent", 10: "extreme"}
# General science beside the event's own data: Wikipedia's articles (CC BY-SA, credited), read at plan time, casualty
# sentences removed. (USGS's teaching pages refuse scripted reads, so their wording could not be checked.)
SCIENCE_ARTICLES = {"how-it-works": ("Fault (geology)", "strike|slip|transform|types|mechanic"),
                    "next": ("Aftershock", "omori|distribution|size|frequen|law|duration")}
SCIENCE_CHARS = 3500


def fact(key: str, value: str, source: str) -> Fact:
    return Fact(key, value, source, numbers=gate.numbers(value), evidence=value)


def science(role: str) -> tuple[str, str]:
    """(text, url) of the role's Wikipedia background article, or ("", "") when it can't be read."""
    title, focus = SCIENCE_ARTICLES[role]
    try:
        return no_casualties(wiki.article_text(title, limit=SCIENCE_CHARS, focus=focus)), wiki.url(title)
    except Exception:  # noqa: BLE001 - background only: the chapter still has USGS's own text and the facts
        return "", ""


def no_casualties(text: str) -> str:
    """Source text without a sentence that speaks of deaths or injuries: a long-form episode states no toll (no two
    outlets' agreement is read here), and a toll left in the source would tempt the writer."""
    keep = []
    for para in text.split("\n"):
        kept = " ".join(s for s in re.split(r"(?<=[.!?])\s+", para) if s and not CASUALTY_SENTENCE.search(s))
        if kept.strip():
            keep.append(kept)
    return "\n".join(keep)


def slot(at: datetime) -> datetime:
    """The first Saturday 14:00 UTC at least BUILD_HOURS after `at`."""
    t = (at + timedelta(hours=BUILD_HOURS)).astimezone(timezone.utc)
    day = t.replace(hour=PUBLISH_HOUR, minute=0, second=0, microsecond=0)
    day += timedelta(days=(PUBLISH_WEEKDAY - day.weekday()) % 7)
    if day < t:
        day += timedelta(days=7)
    return day


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def episode_id(topic: str, at: datetime) -> str:
    y, w, _ = slot(at).isocalendar()
    return f"lf-{y}w{w:02d}-{slug(topic)}"


def bbox16x9(lat: float, lon: float, half_km: float) -> list[float]:
    """[west, south, east, north] around (lat, lon), half_km to each side, 16:9 in Web Mercator."""
    dlon = half_km / (111.32 * max(math.cos(math.radians(lat)), 0.2))
    xs = dlon * 2 / 360
    yc = terrain.lat2y(lat, 0)
    north, south = float(terrain.y2lat(yc - xs * 9 / 32, 0)), float(terrain.y2lat(yc + xs * 9 / 32, 0))
    return [round(lon - dlon, 4), round(south, 4), round(lon + dlon, 4), round(north, 4)]


def fit_bbox(points: list[tuple[float, float]], pad_km: float = 250) -> list[float]:
    """The smallest 16:9 box holding every (lat, lon), with pad_km around."""
    lats, lons = [p[0] for p in points], [p[1] for p in points]
    lat, lon = (min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2
    wide = (max(lons) - min(lons)) / 2 * 111.32 * math.cos(math.radians(lat)) + pad_km
    tall = (terrain.lat2y(min(lats), 0) - terrain.lat2y(max(lats), 0)) * 40075 / 2 * math.cos(math.radians(lat))
    return bbox16x9(lat, lon, max(wide, (tall / 2 + pad_km) * 16 / 9))


def pct(p: float) -> str:
    """A probability as the narration says it: "56", "8", "less than 1"."""
    v = p * 100
    return "less than 1" if v < 0.5 else f"{v:.0f}"


def when(iso: str) -> str:
    t = datetime.fromisoformat(iso)
    return f"{usgs.date_words(t)}, {t.year}"


def title_for(cand: dict, n: int | None = None, peak_mph: int | None = None, basin: str | None = None,
              cat: int | None = None) -> str:
    if cand["kind"] == "quake-region":
        title = f"Why {cand['topic']} Keeps Shaking: {n} Strong Quakes Nearby Since 1900"
        # A long place name and a 4-digit count pass 70 characters: "Strong" goes first (the count is M6+ either way).
        return title if len(title) <= 70 else title.replace(" Strong Quakes", " Quakes")
    kind = "Hurricane" if (cat or 0) >= 1 else "Tropical Storm"
    sea = "Atlantic" if basin == "al" else "Pacific"
    return f"{kind} {cand['topic']}: How a {sea} Storm Reached {peak_mph} mph"


def check_title(title: str, name: str) -> None:
    problems = writer.title_problems(title, name, writer.recent_titles())
    if (bad := gate.banned_word(title)) is not None:
        problems.append(f"banned word {bad!r}")
    if not 45 <= len(title) <= 70:
        problems.append(f"title is {len(title)} characters (want 45-70)")
    if problems:
        raise ValueError(f"title {title!r}: " + "; ".join(problems))


# --- topic richness (the score's second factor) -------------------------------------------------------------------

def richness(cand: dict) -> int:
    if cand["kind"] == "quake-region":
        lat, lon = center_of(cand)
        return data.count(lat, lon, HISTORY_KM, HISTORY_MAG, HISTORY_START)
    track = data.best_track(cand["topic"], datetime.now(timezone.utc).year)
    if not track:
        return 0
    peak = track["peak"]
    storms = data.parse_hurdat(data_text(data.hurdat_file(track["basin"])))
    return len(data.hurricanes_near(storms, peak["lat"], peak["lon"], STORM_KM)) + 1


def data_text(url: str) -> str:
    from .. import net

    return net.get(url, cache=data.CACHE, timeout=(10, 120)).decode("utf-8", "replace")


def center_of(cand: dict) -> tuple[float, float]:
    if cand.get("center"):
        return tuple(cand["center"])
    main = max(cand["events"], key=lambda e: e["mag"])
    d = usgs.detail(main["id"])
    lon, lat, _ = d["geometry"]["coordinates"]
    cand["center"] = [round(lat, 4), round(lon, 4)]
    return lat, lon


# --- earthquakes --------------------------------------------------------------------------------------------------

def plan_quake(cand: dict, at: datetime) -> Episode:
    topic = cand["topic"]
    lat, lon = center_of(cand)
    events = sorted(cand["events"], key=lambda e: -e["mag"])
    end = at.date().isoformat()
    hist = data.history(lat, lon, HISTORY_KM, HISTORY_MAG, HISTORY_START, end=end)
    n = len(hist)
    query = data.comcat_query(lat, lon, HISTORY_KM, HISTORY_MAG, HISTORY_START)
    sources = [query]
    F = {r: [] for r in ("cold-open", "what-happened", "how-it-works", "before", "people", "next", "why-it-matters")}
    text = {r: "" for r in F}
    marks = {"shorts": [], "aftershocks": [], "cities": [],
             "history": [{k: e[k] for k in ("lat", "lon", "mag", "year", "depth")} for e in hist]}
    series = {}
    main_pack = None
    for i, e in enumerate(events):
        pk = usgs.pack(e["id"])
        q = pk["quake"]
        page = pk["page"]
        sources.append(page)
        day = f"{usgs.date_words(q.time)}, {q.time.year}"
        place = usgs.spoken_place(q.place)
        F["what-happened"].append(fact(f"event-{q.id}", f"On {day}, a magnitude {q.mag:.1f} earthquake struck {place}, "
                                                       f"{q.depth:.0f} km below the surface (USGS).", page))
        if pk.get("faulting"):
            F["what-happened"].append(fact(f"fault-{q.id}", f"The USGS moment tensor for the magnitude {q.mag:.1f} "
                                                           f"quake shows {pk['faulting']} faulting.", page))
        marks["shorts"].append({"lat": q.lat, "lon": q.lon, "mag": q.mag, "label": f"M{q.mag:.1f} · {day}"})
        if i == 0:
            main_pack = pk
    if main_pack is None:  # an evergreen region: the largest catalogued quake stands in as the episode's anchor
        big = max(hist, key=lambda e: (e["mag"], e["year"]))
        F["what-happened"].append(fact("largest", f"The largest quake catalogued within {HISTORY_KM} km since 1900 was "
                                                  f"a magnitude {big['mag']:.1f} on {when(big['time'])}, "
                                                  f"{usgs.spoken_place(big['place'])} "
                                                  "(USGS).", query))
        marks["shorts"].append({"lat": big["lat"], "lon": big["lon"], "mag": big["mag"],
                                "label": f"M{big['mag']:.1f} · {big['year']}"})
    years = max(1, at.year - 1900 + at.timetuple().tm_yday / 366)
    months = years * 12 / max(n, 1)
    big7 = [e for e in hist if e["mag"] >= 7]
    decades = data.per_decade(hist, 1900, at.year)
    busiest = max(decades, key=lambda d: (d[1], d[0]))
    series["decades"] = decades
    F["before"] += [
        fact("history-count", f"USGS's catalogue lists {n} earthquakes of magnitude 6 or more within {HISTORY_KM} km of "
                              f"this spot between 1900 and {at.year}.", query),
        fact("history-7", f"{len(big7)} of them were magnitude 7 or more.", query),
        fact("history-busiest", f"The busiest decade was the {busiest[0]}, with {busiest[1]} of them.", query),
    ]
    for e in sorted(hist, key=lambda e: (-e["mag"], e["year"]))[:4]:
        F["before"].append(fact(f"history-{e['id']}", f"In {e['year']}, a magnitude {e['mag']:.1f} quake struck "
                                                      f"{usgs.spoken_place(e['place']) or 'the region'}.", query))
    every = f"{months:.0f} months" if months >= 1.5 else "few weeks"
    recurrence = fact("recurrence", f"Averaged over the {years:.0f} years since 1900, that is one magnitude 6 or "
                                    f"larger quake about every {every} within {HISTORY_KM} km.", query)
    F["before"].append(recurrence)
    F["cold-open"].append(fact("history-count", F["before"][0].value, query))
    q = main_pack["quake"] if main_pack else None
    if main_pack:
        d = usgs.detail(q.id)
        page = main_pack["page"]
        day = f"{usgs.date_words(q.time)}, {q.time.year}"
        F["cold-open"].append(fact("main", f"On {day}, a magnitude {q.mag:.1f} earthquake struck "
                                           f"{usgs.spoken_place(q.place)} (USGS).", page))
        summary_text = no_casualties(data.general_text(d))
        text["how-it-works"] = summary_text
        text["people"] = "\n".join(ln for ln in summary_text.splitlines()[:6])
        if main_pack.get("faulting"):
            F["how-it-works"].append(fact("faulting", f"The USGS moment tensor shows {main_pack['faulting']} faulting "
                                                      f"{q.depth:.0f} km down.", page))
        if main_pack.get("felt_reports"):
            felt = main_pack["felt_reports"]
            F["people"].append(fact("felt", f"{usgs.fmt_int(felt)} people sent USGS a \"Did You Feel It?\" report.", page))
            F["cold-open"].append(fact("felt", F["people"][-1].value, page))
        exposure = main_pack.get("exposure") or {}
        if exposure:
            series["exposure"] = [[usgs.ROMAN[k], int(v)] for k, v in sorted(exposure.items()) if k >= 3 and v]
            strong = sum(v for k, v in exposure.items() if k >= 5)
            if strong:
                F["people"].append(fact("exposure-5", f"The USGS PAGER exposure model estimates that about "
                                                      f"{usgs.fmt_int(usgs.round_people(strong))} people were where "
                                                      "shaking reached intensity V (moderate) or stronger.", page))
            for level in (7, 6):
                many = sum(v for k, v in exposure.items() if k >= level)
                if many:
                    F["people"].append(fact(f"exposure-{level}", f"The USGS PAGER exposure model estimates about {usgs.fmt_int(usgs.round_people(many))} people were "
                                                                  f"where it reached intensity {usgs.ROMAN[level]} "
                                                                  f"({MMI_WORDS[level]}) or stronger.", page))
                    break
        if main_pack.get("pager_alert"):
            alert = main_pack["pager_alert"]
            article = "an" if str(alert)[:1].lower() in "aeiou" else "a"
            F["people"].append(fact("pager", f"USGS gave the quake {article} {alert} PAGER alert, on a "
                                             "scale of likely impact that runs green, yellow, orange, red.", page))
        for c in [c for c in main_pack.get("cities") or [] if c.get("mmi")][:4]:
            level = int(round(c["mmi"]))
            marks["cities"].append({"lat": c["lat"], "lon": c["lon"], "label": c["name"]})
            if level >= 4:
                F["people"].append(fact(f"city-{slug(c['name'])}", f"In {c['name']}, a city of about "
                                                                   f"{usgs.fmt_int(usgs.round_people(c['pop']))}, "
                                                                   f"USGS estimates intensity {usgs.ROMAN[level]}.", page))
        shocks = main_pack.get("aftershocks") or []
        marks["aftershocks"] = [{"lat": a["lat"], "lon": a["lon"], "mag": a["mag"]} for a in shocks]
        if shocks:
            last = max(a["hours"] for a in shocks)
            first_day = sum(1 for a in shocks if a["hours"] <= 24)
            F["what-happened"].append(fact("aftershocks", f"By {when(at.isoformat())}, USGS had catalogued "
                                                          f"{len(shocks)} aftershocks of magnitude 4 or more within "
                                                          f"150 km.", page))
            F["next"].append(fact("aftershocks-day1", f"{first_day} of those aftershocks came in the first 24 hours.", page))
            F["next"].append(fact("aftershocks-all", F["what-happened"][-1].value, page))
            days = max(1, math.ceil(last / 24))
            series["aftershock-days"] = [[f"day {k + 1}", sum(1 for a in shocks if k * 24 < a["hours"] <= (k + 1) * 24)]
                                         for k in range(min(days, 14))]
        fc = data.forecast(d)
        if fc:
            sources.append(fc["url"])
            week = next((w for w in fc["windows"] if w["label"] == "1 Week"), fc["windows"][0] if fc["windows"] else None)
            if week:
                made = when(fc["made"])
                series["forecast"] = [[f"M{b['mag']:.0f}+", round(b["p"] * 100, 1)] for b in week["bins"]
                                      if 5 <= b["mag"] <= 7]
                for b in week["bins"]:
                    if b["mag"] in (5.0, 6.0, 7.0):
                        F["next"].append(fact(f"oaf-{b['mag']:.0f}", f"USGS's aftershock forecast of {made} put the "
                                                                    f"chance of at least one magnitude {b['mag']:.0f} or "
                                                                    f"larger aftershock in the following week at "
                                                                    f"{pct(b['p'])} percent.", fc["url"]))
                F["next"].append(fact("oaf-note", "USGS updates its aftershock forecast as the sequence changes; it "
                                                  "gives chances, not predictions.", fc["url"]))
    # Without a forecast (most events have none), what-comes-next speaks of the long-run rate, framed as an average.
    F["next"].append(recurrence)
    for role in SCIENCE_ARTICLES:
        body, url = science(role)
        if body:
            text[role] = (text[role] + "\n\n" if text[role] else "") + body
            sources.append(url)
    for e in sorted(big7, key=lambda e: e["year"]):
        F["before"].append(fact(f"history-{e['id']}", f"In {e['year']}, a magnitude {e['mag']:.1f} quake struck "
                                                      f"{usgs.spoken_place(e['place']) or 'the region'}.", query))
    F["why-it-matters"] += [F["before"][0], recurrence] + F["people"][:2]
    F["how-it-works"].append(fact("depth-pattern", "On the map, each dot is a catalogued quake of magnitude 6 or more, "
                                                   "coloured by depth: shallow in yellow, deeper in red.", query))
    biggest = main_pack["quake"].mag if main_pack else max(e["mag"] for e in hist)
    cand_title = title_for(cand, n=n)
    check_title(cand_title, topic)
    focus = [q.lat, q.lon] if q else [lat, lon]
    visuals = {
        "cold-open": [{"type": "map", "marks": ["shorts"], "focus": focus, "zoom": [1.0, 1.35]},
                      {"type": "card", "big": f"M{biggest:.1f}", "small": f"{topic} · USGS"},
                      {"type": "card", "big": str(n), "small": f"magnitude 6+ quakes within {HISTORY_KM} km since 1900"}],
        "what-happened": [{"type": "map", "marks": ["shorts"], "focus": focus, "zoom": [1.2, 1.6]},
                          {"type": "map", "marks": ["aftershocks", "shorts"], "focus": focus, "zoom": [1.6, 2.0]}]
                         + ([{"type": "chart", "series": "aftershock-days", "title": "Aftershocks of M4+ per day",
                              "unit": ""}] if "aftershock-days" in series else []),
        "how-it-works": [{"type": "map", "marks": ["history"], "focus": None, "zoom": [1.0, 1.12], "depth": True},
                         {"type": "card", "big": (main_pack or {}).get("faulting", "faults").upper(),
                          "small": "USGS moment tensor"} if main_pack else
                         {"type": "card", "big": "PLATES", "small": "USGS tectonic summary"},
                         {"type": "map", "marks": ["history", "shorts"], "focus": focus, "zoom": [1.3, 1.5],
                          "depth": True}],
        "before": [{"type": "map", "marks": ["history"], "focus": None, "zoom": [1.0, 1.1], "reveal": True},
                   {"type": "chart", "series": "decades", "title": "M6+ quakes per decade, within 500 km", "unit": ""},
                   {"type": "card", "big": str(len(big7)), "small": "of them magnitude 7 or more"}],
        "people": ([{"type": "chart", "series": "exposure", "title": "People by shaking intensity (USGS PAGER)",
                     "unit": ""}] if "exposure" in series else [])
                  + [{"type": "map", "marks": ["cities", "shorts"], "focus": focus, "zoom": [1.1, 1.3]}],
        "next": ([{"type": "chart", "series": "forecast", "title": "Chance of an aftershock this big, next week (%)",
                   "unit": "%"}] if "forecast" in series else [])
                + [{"type": "card", "big": f"~{every}", "small": "average gap between M6+ quakes here"},
                   {"type": "map", "marks": ["aftershocks", "history"], "focus": focus, "zoom": [1.2, 1.0]}],
        "why-it-matters": [{"type": "map", "marks": ["history", "shorts"], "focus": None, "zoom": [1.15, 1.0]},
                           {"type": "sources"}],
    }
    chapters = _chapters("quake", topic, F, text, visuals)
    when_main = f" on {usgs.date_words(q.time)}, {q.time.year}" if q else ""
    summary = (f"{topic} shakes often: USGS lists {n} earthquakes of magnitude 6 or more within {HISTORY_KM} km since "
               f"1900{', and a magnitude ' + format(q.mag, '.1f') + ' struck' + when_main if q else ''}. This explainer "
               "uses USGS data to show what happened, the fault mechanics behind it, the region's history, who felt "
               "it and what the aftershock numbers say.")
    return Episode(
        id=episode_id(topic, at), kind="quake-region", topic=topic, title=cand_title, summary=summary,
        chapters=chapters, sources=list(dict.fromkeys(sources)),
        credits=[QUAKE_CREDIT] + CREDITS + ([WIKI_CREDIT] if any("wikipedia.org" in u for u in sources) else []),
        center=[round(lat, 4), round(lon, 4)], bbox=bbox16x9(lat, lon, HISTORY_KM * 1.35),
        publish_at=slot(at).isoformat(timespec="seconds").replace("+00:00", "Z"),
        tags=[topic, f"{topic} earthquake", "earthquake", "earthquakes explained", "plate tectonics", "USGS",
              "Orbitwire Explains", "Orbitwire"],
        hashtags=["earthquake", topic, "science"],
        related=sorted(cand["shorts"], key=lambda s: -s["views_24h"]),
        data={"marks": marks, "series": series})


# --- tropical cyclones --------------------------------------------------------------------------------------------

def plan_cyclone(cand: dict, at: datetime) -> Episode:
    name = cand["topic"]
    track = data.best_track(name, at.year)
    if not track:
        raise RuntimeError(f"no NHC best track for {name} {at.year}: only Atlantic and Pacific storms of this season")
    pts = track["track"]
    peak = max(pts, key=lambda p: (p["kt"], p["t"]))
    peak_mph, cat = data.mph(peak["kt"]), data.category(peak["kt"])
    basin = track["basin"]
    sea = data.BASIN_WORDS[basin]
    btk = track["url"]
    sources = [btk]
    F = {r: [] for r in ("cold-open", "what-happened", "how-it-works", "before", "people", "next", "why-it-matters")}
    text = {r: "" for r in F}
    label = f"{'Hurricane' if cat else 'Tropical Storm'} {name}"
    F["cold-open"].append(fact("peak", f"{label}'s winds peaked at {peak['kt']} knots, about {peak_mph} mph, on "
                                       f"{when(peak['t'])} (NHC best track).", btk))
    if cat:
        F["cold-open"].append(fact("category", f"That made {name} a Category {cat} hurricane on the Saffir-Simpson "
                                               "scale.", NHC_GLOSSARY))
    start, end = pts[0], pts[-1]
    F["what-happened"] += [
        fact("start", f"NHC's best track for {name} begins on {when(start['t'])}, with winds of {start['kt']} knots.", btk),
        fact("end", f"It ends on {when(end['t'])}, with winds of {end['kt']} knots.", btk),
        F["cold-open"][0],
    ]
    if peak.get("mb"):
        F["what-happened"].append(fact("pressure", f"Its lowest central pressure in the best track is "
                                                   f"{min(p['mb'] for p in pts if p.get('mb'))} millibars.", btk))
    # The fastest 24-hour rise in winds, from the 6-hourly points.
    by_t = {p["t"]: p for p in pts}
    rise, a, b = 0, None, None
    for p in pts:
        later = by_t.get((datetime.fromisoformat(p["t"]) + timedelta(hours=24)).isoformat(timespec="minutes"))
        if later and later["kt"] - p["kt"] > rise:
            rise, a, b = later["kt"] - p["kt"], p, later
    if rise:
        F["how-it-works"].append(fact("rise", f"In its fastest 24 hours, from {when(a['t'])}, {name}'s winds rose by "
                                              f"{rise} knots, from {a['kt']} to {b['kt']}.", btk))
        F["how-it-works"].append(fact("ri-definition", "NHC calls an increase of at least 30 knots in 24 hours rapid "
                                                       "intensification.", NHC_GLOSSARY))
        sources.append(NHC_GLOSSARY)
    mech = wiki.article_text("Tropical cyclone", limit=6000, focus="formation|structure|mechanic|physical|intensif")
    text["how-it-works"] = no_casualties(mech)
    sources.append(wiki.url("Tropical cyclone"))
    article = wiki.search(f"Hurricane {name} {at.year}")
    if article and name.lower() in article.lower():
        body = no_casualties(wiki.article_text(article, limit=7000, focus="impact|preparation|landfall|history"))
        text["what-happened"] = body
        text["people"] = body
        sources.append(wiki.url(article))
    storms = data.season(at.year, basin)
    named = [s for s in storms if s["peak_kt"] >= 34]
    canes = [s for s in named if s["peak_kt"] >= 64]
    majors = [s for s in named if s["peak_kt"] >= 96]
    F["before"] += [fact("season", f"NHC's best tracks list {len(named)} named storms in the {at.year} {sea} season "
                                   f"so far, {len(canes)} of them hurricanes and {len(majors)} major hurricanes.", data.BTK)]
    hfile = data.hurdat_file(basin)
    near = data.hurricanes_near(data.parse_hurdat(data_text(hfile)), peak["lat"], peak["lon"], STORM_KM)
    sources.append(data.HURDAT_URL)
    first_year = 1949 if basin != "al" else 1851
    F["before"].append(fact("near", f"NOAA's HURDAT2 record lists {len(near)} hurricanes that passed within "
                                    f"{STORM_KM} km of where {name} peaked, from {first_year} to the end of the last "
                                    "reanalysed season.", data.HURDAT_URL))
    for s in sorted(near, key=lambda s: (-s["kt"], s["year"]))[:4]:
        F["before"].append(fact(f"near-{s['id']}", f"Hurricane {s['name']} of {s['year']} passed there with winds of "
                                                   f"{s['kt']} knots, about {data.mph(s['kt'])} mph.", data.HURDAT_URL))
    sources.append(NHC_CLIMO)
    F["next"] += [fact("season-end", f"NHC says the {sea} hurricane season runs from {SEASON[basin]}.", NHC_CLIMO),
                  F["before"][0]]
    F["why-it-matters"] += [F["cold-open"][0], F["before"][1]]
    title = title_for(cand, peak_mph=peak_mph, basin=basin, cat=cat)
    check_title(title, label)
    series = {"intensity": [[p["t"][5:13].replace("T", " "), p["kt"]] for p in pts],
              "season": [[s["name"] or s["file"][1:5].upper(), s["peak_kt"]] for s in named]}
    marks = {"track": pts, "past": [{"name": s["name"], "year": s["year"], "points": s["track"][::2]} for s in near]}
    visuals = {
        "cold-open": [{"type": "map", "marks": ["track"], "focus": [peak["lat"], peak["lon"]], "zoom": [1.0, 1.3]},
                      {"type": "card", "big": f"{peak_mph} MPH", "small": f"{label} at its peak · NHC"}],
        "what-happened": [{"type": "map", "marks": ["track"], "focus": None, "zoom": [1.0, 1.1], "reveal": True},
                          {"type": "chart", "series": "intensity", "title": f"{name}'s peak winds (knots)", "unit": ""}],
        "how-it-works": [{"type": "chart", "series": "intensity", "title": f"{name}'s peak winds (knots)", "unit": ""},
                         {"type": "card", "big": f"+{rise} KT", "small": "its fastest 24 hours"},
                         {"type": "map", "marks": ["track"], "focus": [peak["lat"], peak["lon"]], "zoom": [1.4, 1.8]}],
        "before": [{"type": "map", "marks": ["past", "track"], "focus": None, "zoom": [1.0, 1.1], "reveal": True},
                   {"type": "chart", "series": "season", "title": f"{at.year} {sea} storms: peak winds (knots)",
                    "unit": ""}],
        "people": [{"type": "map", "marks": ["track"], "focus": [peak["lat"], peak["lon"]], "zoom": [1.2, 1.5]}],
        "next": [{"type": "chart", "series": "season", "title": f"{at.year} {sea} storms: peak winds (knots)",
                  "unit": ""}, {"type": "card", "big": "30 NOV", "small": "official end of the season"}],
        "why-it-matters": [{"type": "map", "marks": ["past", "track"], "focus": None, "zoom": [1.1, 1.0]},
                           {"type": "sources"}],
    }
    chapters = _chapters("cyclone", name, F, text, visuals)
    lat, lon = peak["lat"], peak["lon"]
    summary = (f"{label} peaked at {peak['kt']} knots (about {peak_mph} mph) in the {sea} on {when(peak['t'])}. This "
               "explainer uses NOAA best-track data to show how it grew, how hurricanes draw strength from warm water, "
               "how often storms this strong pass the same waters, and what is left of the season.")
    credits = [STORM_CREDIT] + CREDITS + ([WIKI_CREDIT] if any("wikipedia.org" in s for s in sources) else [])
    return Episode(
        id=episode_id(name, at), kind="cyclone", topic=name, title=title, summary=summary, chapters=chapters,
        sources=list(dict.fromkeys(sources)), credits=credits, center=[lat, lon],
        bbox=fit_bbox([(p["lat"], p["lon"]) for p in pts]),
        publish_at=slot(at).isoformat(timespec="seconds").replace("+00:00", "Z"),
        tags=[label, name, "hurricane", "hurricanes explained", "tropical cyclone", "NOAA", "Orbitwire Explains",
              "Orbitwire"],
        hashtags=["hurricane", name, "science"], related=sorted(cand["shorts"], key=lambda s: -s["views_24h"]),
        data={"marks": marks, "series": series})


# --- chapters -------------------------------------------------------------------------------------------------------

TITLES = {
    "quake": {"cold-open": "{topic} shakes again", "what-happened": "What happened", "how-it-works":
              "How the plates move", "before": "It has happened before", "people": "Who felt it",
              "next": "What comes next", "why-it-matters": "Why it matters"},
    "cyclone": {"cold-open": "{topic} at its peak", "what-happened": "What happened", "how-it-works":
                "How a hurricane grows", "before": "Storms on the same path", "people": "Who was in its way",
                "next": "What comes next", "why-it-matters": "Why it matters"},
}
BRIEFS = {
    "cold-open": "Open on the single most striking verified number and the question the episode answers. No welcome, "
                 "no channel name, no question to the viewer. The first sentence names {topic}.",
    "what-happened": "Tell what happened, in time order, from the data: when, where, how strong, and what followed.",
    "how-it-works": "Explain the mechanism in plain words, as a patient teacher: what moved, where and why, using only "
                    "the SOURCE and the facts. This is the heart of the episode.",
    "before": "Show that this has happened before: the long record, the biggest events, and how often it comes.",
    "people": "Say who was in the way, using exposure and felt reports only: never deaths, injuries or damage "
              "figures. Keep modelled PAGER exposure separate from actual felt reports. The alert colour "
              "describes estimated impact, not the number of people who felt shaking.",
    "next": "Say what the numbers say about what comes next, framed as chances and averages, never as an outcome.",
    "why-it-matters": "Close: why this matters for the people who live there, in two or three calm sentences, and a "
                      "final line that the sources are in the description.",
}
# About 155 spoken words a minute: 1,220-1,790 words is about 8.2-12 minutes with the pauses (assemble.py gates
# 8:00-14:30 on the real length). The close is the brief's two or three sentences: a 100-word floor there had the
# writer pad it with figures from earlier chapters (dry run 39705000818).
WORDS = {"cold-open": [90, 140], "what-happened": [220, 320], "how-it-works": [260, 360], "before": [240, 340],
         "people": [180, 270], "next": [180, 270], "why-it-matters": [50, 90]}


def _chapters(kind: str, topic: str, F: dict, text: dict, visuals: dict) -> list[Chapter]:
    out = []
    for role in ("cold-open", "what-happened", "how-it-works", "before", "people", "next", "why-it-matters"):
        facts = list({f.key: f for f in F[role]}.values())
        if len(facts) < 2 and not text[role] and role not in ("cold-open", "why-it-matters"):
            continue  # nothing to say: the chapter is left out rather than padded
        words = WORDS[role] if (len(facts) >= 3 or text[role]) else [int(WORDS[role][0] * 0.6), WORDS[role][1]]
        out.append(Chapter(key=role, title=TITLES[kind][role].format(topic=topic),
                           brief=BRIEFS[role].format(topic=topic), words=words, facts=facts, source=text[role][:6000],
                           visuals=visuals[role]))
    return out


# --- entry point ----------------------------------------------------------------------------------------------------

def plan(at: datetime | None = None, override: str | None = None, rich=None) -> Episode:
    """Choose this week's topic and plan its episode."""
    at = at or datetime.now(timezone.utc)
    state = ledger.load("longform", {})
    when = slot(at).isoformat(timespec="seconds").replace("+00:00", "Z")
    if not override and (taken := topics.slot_taken(state, when)):
        raise RuntimeError(f"the {when} slot already has episode {taken} "
                           f"({(state['episodes'][taken] or {}).get('state')}): one episode a week. To resume it, "
                           "re-run the failed jobs of its own run; to make another anyway, pass --topic")
    cands = topics.candidates(ledger.published(), ledger.load("performance", {}), set(youtube.RETRACTED), at)
    chosen, why = topics.pick(cands, rich or richness, state, at, override)
    ep = plan_quake(chosen, at) if chosen["kind"] == "quake-region" else plan_cyclone(chosen, at)
    ep.why = why | {"topic_key": chosen["key"]}
    return ep
