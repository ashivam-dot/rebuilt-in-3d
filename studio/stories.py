"""Trending stories written from Wikidata (CC0) and Wikipedia infobox fields: no language model, so every sentence
is traceable to a field, and anything uncertain is left out rather than guessed.

Two shapes: an incident (a "where it happened" 3D site, with the route for flights, trains and ships) and the
death of a famous person (a "life map" from birthplace to the place they died).
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta, timezone

from . import terrain, wiki
from .spec import Beat, Fact, Short

CREDIT = "Facts: Wikidata (CC0) and Wikipedia (CC BY-SA 4.0)"
OUTRO = ("Every fact here comes from public records, linked in the description. Follow Orbitwire for the world's "
         "biggest stories, in 3D.")
# Summaries that guess at motive or cause are never read out; the Short says the cause is under investigation.
SPECULATIVE = re.compile(r"\b(suspect\w*|alleged\w*|possibl\w*|reported\w*|believed|likely|apparent\w*|suicid\w*|"
                         r"terror\w*|murder\w*|hijack\w*|sabotage|unknown|disputed)\b", re.I)
FEMALE, MALE = "Q6581072", "Q6581097"
AWARD_WORDS = ("Academy Award", "Nobel", "Grammy", "Emmy", "Tony Award", "Golden Globe", "Olympic", "Booker",
               "Pulitzer", "Bharat Ratna", "Padma", "BAFTA", "Ballon d'Or")
ROUTED = {"aviation", "rail", "maritime"}
MIN_ARTICLE_AGE = timedelta(hours=6)


def date_words(d: date) -> str:
    return f"{d:%B} {d.day}, {d.year}"


def km_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    r = math.radians
    h = math.sin(r(b[0] - a[0]) / 2) ** 2 + math.cos(r(a[0])) * math.cos(r(b[0])) * math.sin(r(b[1] - a[1]) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def bbox(lat: float, lon: float, half_km: float) -> list[float]:
    dlat = half_km / 110.574
    dlon = half_km / (111.320 * math.cos(math.radians(lat)))
    return [lon - dlon, lat - dlat, lon + dlon, lat + dlat]


def city_of(text: str | None) -> str | None:
    """'Dubai International Airport, Dubai, United Arab Emirates' -> 'Dubai'; 'Newark, New Jersey, U.S.' -> 'Newark'."""
    if not text:
        return None
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if len(parts) >= 3 and re.search(r"\b(Airport|Station|Port|Harbou?r|Terminal)\b", parts[0]):
        return parts[1]
    return parts[0]


def place_words(text: str, parts: int = 2) -> str:
    return ", ".join(p.strip() for p in text.split(",")[:parts] if p.strip())


def plain_title(title: str) -> str:
    """'Margaret Hamilton (software engineer)' -> 'Margaret Hamilton': disambiguation is for search, not speech."""
    return re.sub(r"\s*\([^)]*\)$", "", title).strip()


def numbers_in(text: str) -> list[str]:
    return re.findall(r"\d{1,3}(?:,\d{3})+|\d+", text or "")


def agreed(text: str | None, ent: dict, pid: str, need_wikidata: bool) -> int | None:
    """A count both sources give: the infobox's exact leading number, matching a Wikidata value of the property.

    Without Wikidata values, the infobox alone counts only when need_wikidata is False (never for deaths).
    """
    n = wiki.leading_number(text)
    if n is None or re.search(r"\d\s*\+|\bat least\b|\bover\b|\bmore than\b|\bup to\b", text or "", re.I):
        return None
    values = {int(c["value"]) for c in wiki.claims(ent, pid)}
    if not values:
        return None if need_wikidata else n
    return n if n in values else None


def _first(fields: dict, *keys: str) -> str | None:
    return next((fields[k] for k in keys if fields.get(k)), None)


def _event_date(ent: dict) -> date | None:
    for pid in ("P585", "P580"):
        for c in wiki.claims(ent, pid):
            d = wiki.wd_time(c["value"])
            if d:
                return d
    return None


def _check_age(title: str) -> None:
    made = wiki.created(title)
    if made and datetime.now(timezone.utc) - made < MIN_ARTICLE_AGE:
        raise ValueError(f"gate: the article is under {MIN_ARTICLE_AGE.seconds // 3600} hours old; facts may still move")


def _places(ent: dict, pid: str) -> list[dict]:
    out = []
    for c in wiki.claims(ent, pid):
        if isinstance(c["value"], str) and c["value"].startswith("Q"):
            p = wiki.place(c["value"])
            if p:
                out.append(p)
    return out


def _cities(lat: float, lon: float, half: float, skip: set[str]) -> list[dict]:
    try:
        if half <= 300:
            rows = wiki.nearby_cities(lat, lon, half * 0.95, limit=6, min_pop=20000 if half < 120 else 100000)
        else:
            rows = [c for c in wiki.big_cities() if km_between((lat, lon), (c["lat"], c["lon"])) < half * 0.95][:6]
    except Exception:
        return []
    return [c for c in rows if c["name"] not in skip][:5]


def build_incident(cand: dict) -> Short:
    article, qid, cat = cand["title"], cand["qid"], cand["category"]
    title = plain_title(article)
    _check_age(article)
    ent = wiki.entities([qid])[qid]
    _, ib, _ = wiki.infobox(article)
    when = _event_date(ent)
    if not when:
        raise ValueError("gate: Wikidata has no date for this event")
    page, item = wiki.url(article), f"https://www.wikidata.org/wiki/{qid}"
    info = wiki.page_info([article]).get(article, {})
    site = (info["lat"], info["lon"]) if info.get("lat") is not None else wiki.coords(ent)
    origin = _places(ent, "P1427")[:1] if cat in ROUTED else []
    dest = _places(ent, "P1444")[:1] if cat in ROUTED else []
    if not site:
        located = _places(ent, "P276")
        if located and origin and dest:
            # Several locations: take the one nearest the straight route, i.e. the least detour.
            o, d = (origin[0]["lat"], origin[0]["lon"]), (dest[0]["lat"], dest[0]["lon"])
            located.sort(key=lambda p: km_between(o, (p["lat"], p["lon"])) + km_between((p["lat"], p["lon"]), d))
        site = (located[0]["lat"], located[0]["lon"]) if located else None
    if not site:
        raise ValueError("gate: no coordinates for the site")
    words = date_words(when)
    facts = [
        Fact("name", title, page, numbers_in(title), "Wikipedia article title"),
        Fact("date", words, item, [str(when.day), str(when.year)], f"Wikidata P585/P580 = {when.isoformat()}"),
    ]
    beats: list[Beat] = []
    occ = (ib.get("occurrence_type") or "").lower()
    label = ib.get("iata") or (title if len(title) <= 22 else city_of(_first(ib, "site", "location", "place")) or title)
    if cat == "aviation":
        kind = occ if occ in ("accident", "incident") else "incident"
        beats.append(Beat(f"On {words}, {title} was involved in an {kind}. Here is where it happened, rebuilt in 3D.",
                          "overview", {"big": label, "small": f"{ib.get('operator') or 'Flight'} · {words}"}))
    else:
        name = f"the {title}" if title[:1].isdigit() else title
        beats.append(Beat(f"This is where {name} happened, on {words}, rebuilt in 3D from public records.",
                          "overview", {"big": label, "small": words}))

    route = None
    if origin and dest:
        o_name = origin[0].get("serves") or city_of(ib.get("origin")) or origin[0]["name"]
        d_name = dest[0].get("serves") or city_of(ib.get("destination")) or dest[0]["name"]
        craft = _first(ib, "aircraft_type", "train", "ship_name", "vessel")
        if craft:
            facts.append(Fact("craft", craft, page, numbers_in(craft), "infobox aircraft_type/train/vessel"))
        aboard = agreed(_first(ib, "occupants", "passengers"), ent, "P1132", need_wikidata=False)
        text = f"The {craft} was" if craft else "It was"
        text += f" travelling from {o_name} to {d_name}"
        text += f" with {aboard:,} people on board." if aboard else "."
        small = " · ".join(x for x in (craft, f"{aboard:,} on board" if aboard else None) if x)
        beats.append(Beat(text, "route", {"big": f"{o_name} → {d_name}", "small": small or "route"}))
        facts.append(Fact("route", f"{o_name} to {d_name}", page, [], f"infobox origin={ib.get('origin')}; "
                                                                        f"destination={ib.get('destination')}"))
        if aboard:
            facts.append(Fact("aboard", str(aboard), page, [f"{aboard:,}", str(aboard)],
                              f"infobox occupants={ib.get('occupants')}; Wikidata P1132"))
        route = {"from": {"name": o_name, "lat": origin[0]["lat"], "lon": origin[0]["lon"]},
                 "to": {"name": d_name, "lat": dest[0]["lat"], "lon": dest[0]["lon"]}}

    where = _first(ib, "site", "location", "place", "areas affected", "areas")
    if where:
        where = place_words(where, 3) if len(where) > 70 else where
        prep = "" if re.match(r"(?i)(in|at|near|over|off|on)\b", where) else \
            "in " if re.search(r"(?i)airspace|sea|ocean|gulf|bay|river|province|state|district|region", where) else "at "
        beats.append(Beat(f"Records place it {prep}{where}.", "site", {"big": city_of(where) or where, "small": "the site"}))
        facts.append(Fact("site", where, page, numbers_in(where), "infobox site/location"))

    deaths = agreed(_first(ib, "total_fatalities", "fatalities", "deaths"), ent, "P1120", need_wikidata=True)
    hurt = agreed(_first(ib, "total_injuries", "injuries", "injured", "non-fatal injuries"), ent, "P1339", need_wikidata=True)
    survivors = agreed(ib.get("survivors"), ent, "P1561", need_wikidata=False)
    aboard_n = next((int(f.value) for f in facts if f.key == "aboard"), None)
    if deaths == 0 and aboard_n and survivors == aboard_n:
        beats.append(Beat(f"All {aboard_n:,} people on board survived.", "toll",
                          {"big": "No deaths", "small": f"all {aboard_n:,} on board survived"}))
        facts.append(Fact("deaths", "0", page, ["0"], f"infobox fatalities={ib.get('fatalities')}; survivors="
                                                       f"{ib.get('survivors')}; Wikidata P1120/P1561"))
    elif deaths is not None and deaths > 0:
        text = f"Official figures compiled on Wikipedia and Wikidata put the death toll at {deaths:,}"
        text += f", with {hurt:,} people injured." if hurt else "."
        beats.append(Beat(text, "toll", {"big": f"{deaths:,} deaths", "small": "official figures"}))
        facts.append(Fact("deaths", str(deaths), page, [f"{deaths:,}", str(deaths)],
                          "infobox fatalities and Wikidata P1120 agree"))
        if hurt:
            facts.append(Fact("injured", str(hurt), page, [f"{hurt:,}", str(hurt)], "infobox injuries and Wikidata P1339 agree"))
    elif deaths == 0:
        beats.append(Beat("No deaths have been reported.", "toll", {"big": "No deaths", "small": "official figures"}))
        facts.append(Fact("deaths", "0", page, ["0"], "infobox fatalities and Wikidata P1120 agree"))

    summary = ib.get("summary") or ""
    investigators = [wiki.labels([c["value"]]).get(c["value"]) for c in wiki.claims(ent, "P1840")[:1]]
    agency = investigators[0] if investigators and investigators[0] else None
    if "investigation" in summary.lower() or agency:
        text = "The cause is under investigation" + (f", led by the {agency}." if agency else ".")
        beats.append(Beat(text, "status", {"big": "Under investigation", "small": agency or "official inquiry"}))
        facts.append(Fact("status", "under investigation", page, numbers_in(agency or ""),
                          f"infobox summary={summary}; Wikidata P1840"))
    elif summary and not SPECULATIVE.search(summary) and len(summary) < 90:
        beats.append(Beat(f"Investigators' summary: {summary}.", "status", {"big": "What happened", "small": summary}))
        facts.append(Fact("summary", summary, page, numbers_in(summary), "infobox summary"))
    beats.append(Beat(OUTRO, "outro", {"big": "Orbitwire", "small": "Wikidata · Wikipedia · not real footage"},
                      pause_after=0.6))

    keep = [(p["lat"], p["lon"]) for p in ([route["from"], route["to"]] if route else [])]
    half = 60.0
    for p in keep:
        half = max(half, km_between(site, p) * 1.12)
    half = min(half, 1500.0)
    named = {route["from"]["name"], route["to"]["name"]} if route else set()
    scene = {
        "template": "site", "bbox": bbox(site[0], site[1], half), "center": {"lat": site[0], "lon": site[1]},
        "site": {"label": label, "sub": words}, "route": route,
        "cities": _cities(site[0], site[1], half, named),
        "credits": "Facts: Wikidata · Wikipedia · Terrain: Mapzen/AWS Terrain Tiles",
    }
    loss = bool(deaths) or cat in ("attack", "strike", "conflict")
    yt_title = f"Where {title} happened, in 3D"
    if len(yt_title) > 70:
        yt_title = f"{title} in 3D"[:70]
    region = city_of(where) if where else None
    return Short(
        id=f"wk-{qid}", kind="incident", title=yt_title, beats=beats, facts=facts, sources=[page, item], loss=loss,
        scene=scene, event_time=when.isoformat(),
        tags=[title, cat, "3D map", "news explained", "trending news"] + ([region] if region else []),
        summary=f"{title}, {words}. Facts from Wikidata and Wikipedia; the 3D scene is a reconstruction from data.",
        credits=[CREDIT, terrain.CREDIT],
        hashtags=[cat if cat != "aviation" else "aviation", region or "world", "news"],
    )


def _pronouns(ent: dict) -> tuple[str, str]:
    sex = next((c["value"] for c in wiki.claims(ent, "P21")), None)
    return ("She", "Her") if sex == FEMALE else ("He", "His") if sex == MALE else ("They", "Their")


def build_death(cand: dict) -> Short:
    title, qid = cand["title"], cand["qid"]
    ent = wiki.entities([qid])[qid]
    _, ib, raw = wiki.infobox(title)
    if not raw:
        raise ValueError("gate: the article has no infobox to confirm the death")
    born = next((wiki.wd_time(c["value"]) for c in wiki.claims(ent, "P569")), None)
    died = next((wiki.wd_time(c["value"]) for c in wiki.claims(ent, "P570")), None)
    if not born or not died:
        raise ValueError("gate: Wikidata lacks an exact birth or death date")
    if str(died.year) not in raw.get("death_date", ""):
        raise ValueError("gate: Wikipedia's infobox does not confirm the death yet")
    page, item = wiki.url(title), f"https://www.wikidata.org/wiki/{qid}"
    name = plain_title(wiki.label(ent) or title)
    she, her = _pronouns(ent)
    age = died.year - born.year - ((died.month, died.day) < (born.month, born.day))
    job = (ib.get("occupation") or "").split(",")[0].strip().lower()
    if not job:
        jobs = wiki.labels([c["value"] for c in wiki.claims(ent, "P106")[:1]])
        job = next(iter(jobs.values()), "")
    facts = [
        Fact("name", name, page, numbers_in(name), "Wikipedia article title"),
        Fact("born", date_words(born), item, [str(born.day), str(born.year)], f"Wikidata P569 = {born.isoformat()}"),
        Fact("died", date_words(died), item, [str(died.day), str(died.year)],
             f"Wikidata P570 = {died.isoformat()}; infobox death_date present"),
        Fact("age", str(age), item, [str(age)], "computed from P569 and P570"),
    ]
    lead = f"{name}, the {job}," if job else name
    beats = [Beat(f"{lead} died on {date_words(died)}, at {age}. Here is the map of {her.lower()} life, in 3D.",
                  "overview", {"big": name, "small": f"{born.year} – {died.year}"})]
    birth = next(iter(_places(ent, "P19")), None)
    death = next(iter(_places(ent, "P20")), None)
    b_words = place_words(ib["birth_place"]) if ib.get("birth_place") else birth["name"] if birth else None
    d_words = place_words(ib["death_place"]) if ib.get("death_place") else death["name"] if death else None
    if b_words:
        beats.append(Beat(f"{she} was born in {b_words}, on {date_words(born)}.", "born",
                          {"big": city_of(b_words), "small": f"born · {born.year}"}))
        facts.append(Fact("birthplace", b_words, page, numbers_in(b_words), "infobox birth_place; Wikidata P19"))
    works = list(wiki.labels([c["value"] for c in wiki.claims(ent, "P800")[:2]]).values())
    awards = [a for a in wiki.labels([c["value"] for c in wiki.claims(ent, "P166")[:40]]).values()
              if any(w in a for w in AWARD_WORDS)]
    career = []
    if works:
        career.append(f"{she} {'were' if she == 'They' else 'was'} known for {' and '.join(works)}.")
        facts.append(Fact("works", "; ".join(works), item, [n for w in works for n in numbers_in(w)], "Wikidata P800"))
    if awards:
        career.append(f"{she} won the {awards[0]}.")
        facts.append(Fact("award", awards[0], item, numbers_in(awards[0]), "Wikidata P166"))
    span = re.match(r"\s*(\d{4})\s*[–-]\s*(\d{4})", ib.get("years_active", ""))
    if span:
        career.append(f"{her} career ran from {span.group(1)} to {span.group(2)}.")
        facts.append(Fact("career", f"{span.group(1)}-{span.group(2)}", page, [span.group(1), span.group(2)],
                          f"infobox years_active={ib.get('years_active')}"))
    if career:
        small = awards[0] if awards else f"{span.group(1)}–{span.group(2)}" if span else (works[0] if works else "")
        beats.append(Beat(" ".join(career), "career", {"big": job.capitalize() or name, "small": small}))
    if d_words:
        beats.append(Beat(f"{she} died in {d_words}.", "died", {"big": city_of(d_words), "small": f"died · {died.year}"}))
        facts.append(Fact("deathplace", d_words, page, numbers_in(d_words), "infobox death_place; Wikidata P20"))
    beats.append(Beat(OUTRO, "outro", {"big": "Orbitwire", "small": "Wikidata · Wikipedia · not real footage"},
                      pause_after=0.6))

    pts = [p for p in (birth, death) if p]
    if not pts:
        raise ValueError("gate: no mapped places for this life")
    places = []
    if birth:
        places.append({"name": city_of(b_words) or birth["name"], "sub": f"born {born.year}", "lat": birth["lat"],
                       "lon": birth["lon"], "kind": "born"})
    if death:
        places.append({"name": city_of(d_words) or death["name"], "sub": f"died {died.year}", "lat": death["lat"],
                       "lon": death["lon"], "kind": "died"})
    if len(pts) == 2 and km_between((pts[0]["lat"], pts[0]["lon"]), (pts[1]["lat"], pts[1]["lon"])) > 5:
        dist = km_between((pts[0]["lat"], pts[0]["lon"]), (pts[1]["lat"], pts[1]["lon"]))
        if dist / 2 * 1.3 <= 2800:
            lat, lon = (pts[0]["lat"] + pts[1]["lat"]) / 2, (pts[0]["lon"] + pts[1]["lon"]) / 2
            half = max(150.0, dist / 2 * 1.3)
        else:
            lat, lon, half = pts[-1]["lat"], pts[-1]["lon"], 1500.0
    else:
        lat, lon, half = pts[-1]["lat"], pts[-1]["lon"], 150.0
    scene = {
        "template": "life", "bbox": bbox(lat, lon, half), "center": {"lat": lat, "lon": lon},
        "site": None, "route": {"from": places[0], "to": places[-1]} if len(places) == 2 else None,
        "places": places, "cities": [],
        "credits": "Facts: Wikidata · Wikipedia · Terrain: Mapzen/AWS Terrain Tiles",
    }
    yt_title = f"The life of {name}, mapped in 3D"
    return Short(
        id=f"wk-{qid}", kind="death", title=yt_title if len(yt_title) <= 70 else f"{name}, mapped in 3D"[:70],
        beats=beats, facts=facts, sources=[page, item], loss=False, scene=scene, event_time=died.isoformat(),
        tags=[name, job, "tribute", "3D map", "trending news"],
        summary=f"{name} ({born.year}–{died.year}), {job}. Places and dates from Wikidata and Wikipedia.",
        credits=[CREDIT, terrain.CREDIT],
        hashtags=[name.replace(" ", ""), job or "news", "news"],
    )


def build(cand: dict) -> Short:
    return build_death(cand) if cand["kind"] == "death" else build_incident(cand)
