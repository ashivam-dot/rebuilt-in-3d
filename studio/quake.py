"""A quake Short written entirely from USGS data: no language model, so every sentence is traceable to a field."""
from __future__ import annotations

import math

from . import terrain, usgs
from .spec import Beat, Fact, Short

CHANNEL_CREDIT = "Earthquake data: U.S. Geological Survey (public domain)"
PAGER_MEANING = {
    "green": "a low likelihood of casualties and damage",
    "yellow": "some casualties and damage are possible",
    "orange": "significant casualties and damage are likely",
    "red": "high casualties and extensive damage are probable",
}
FAULT_SENTENCE = {
    "reverse": "Its moment tensor shows reverse faulting: one block of rock was pushed up and over another.",
    "normal": "Its moment tensor shows normal faulting: the crust was pulled apart and one block dropped.",
    "strike-slip": "Its moment tensor shows strike-slip faulting: two blocks of rock slid sideways past each other.",
}


def _km(lat1, lon1, lat2, lon2) -> float:
    r = math.radians
    a = math.sin(r(lat2 - lat1) / 2) ** 2 + math.cos(r(lat1)) * math.cos(r(lat2)) * math.sin(r(lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(a))


def depth_class(km: float) -> str:
    return "shallow" if km < 70 else "intermediate-depth" if km < 300 else "deep"


def _contour_extent(contours: dict | None, level: float) -> list[tuple[float, float]]:
    pts = []
    for f in (contours or {}).get("features", []):
        if float(f["properties"].get("value", 0)) < level:
            continue
        geom = f["geometry"]
        lines = geom["coordinates"] if geom["type"] == "MultiLineString" else [geom["coordinates"]]
        for line in lines:
            pts += [(lat, lon) for lon, lat, *_ in line]
    return pts


def _bbox(lat: float, lon: float, keep: list[tuple[float, float]]) -> list[float]:
    half = 70.0
    for plat, plon in keep:
        half = max(half, _km(lat, lon, plat, plon) * 1.15)
    half = min(half, 240.0)
    dlat = half / 110.574
    dlon = half / (111.320 * math.cos(math.radians(lat)))
    return [lon - dlon, lat - dlat, lon + dlon, lat + dlat]


def build(event_id: str) -> Short:
    pk = usgs.pack(event_id)
    q: usgs.Quake = pk["quake"]
    place = pk["place"]
    page = pk["page"]
    region = place["region"] or place["ref"]
    mag = f"{q.mag:.1f}"
    depth = int(round(q.depth))
    clock = f"{q.time.hour}:{q.time:%M}"
    when = f"{clock} UTC on {usgs.date_words(q.time)}"
    facts = [
        Fact("magnitude", f"M{mag} ({pk['mag_type']})", page, [mag], f"mag={q.mag}, magType={pk['mag_type']}"),
        Fact("time", when, page, [clock, str(q.time.day)], f"time={q.time.isoformat()}"),
        Fact("place", q.place, page, [str(place["distance_km"])] if place["distance_km"] else [], f"place={q.place}"),
        Fact("depth", f"{depth} km ({pk['depth_type'] or 'computed'})", page, [str(depth)], f"depth={q.depth}"),
    ]
    over_sea = terrain.elevation_at(q.lat, q.lon) < 0
    where = f"off {region}" if over_sea else f"in {region}"
    beats = [Beat(f"A magnitude {mag} earthquake struck {where}. Here is what happened underground, rebuilt in 3D "
                  f"from USGS data.", "overview", {"big": f"M{mag}", "small": f"{region} · {usgs.date_words(q.time)}"})]
    if place["distance_km"]:
        beats.append(Beat(f"It hit at {when}, about {place['distance_km']} kilometres {place['direction']} of "
                          f"{place['ref']}.", "approach",
                          {"big": f"{place['distance_km']} km", "small": f"{place['direction']} of {place['ref']}"}))
    else:
        beats.append(Beat(f"It hit at {when}.", "approach", {"big": f"{clock} UTC", "small": usgs.date_words(q.time)}))
    kind = depth_class(q.depth)
    if pk["depth_type"] == "operator assigned":
        text = f"USGS puts its depth at roughly {depth} kilometres, which makes it a {kind} quake."
    else:
        text = f"It began about {depth} kilometres below the surface, a {kind} quake."
    beats.append(Beat(text, "cut", {"big": f"≈{depth} km", "small": f"depth · a {kind} quake"}))
    if pk.get("faulting"):
        beats.append(Beat(FAULT_SENTENCE[pk["faulting"]], "fault",
                          {"big": f"{pk['faulting'].capitalize()} fault", "small": "USGS moment tensor"}))
        facts.append(Fact("faulting", pk["faulting"], page, [], f"moment tensor nodal plane 1 rake={pk['mt_rake']}"))
    exposure = pk.get("exposure") or {}
    strong = sum(n for mmi, n in exposure.items() if mmi >= 7)
    level, label = (7, "very strong") if strong >= 100 else (6, "strong")
    people = usgs.round_people(sum(n for mmi, n in exposure.items() if mmi >= level))
    if people >= 100:
        n = usgs.fmt_int(people)
        beats.append(Beat(f"USGS estimates about {n} people were exposed to {label} shaking or worse.", "shaking",
                          {"big": f"≈{n}", "small": f"people in {label} shaking or worse (USGS estimate)"}))
        facts.append(Fact("exposure", f"{n} people at MMI {usgs.ROMAN[level]}+", page, [n],
                          f"PAGER exposures.json aggregated_exposure={exposure}"))
    alert = pk.get("pager_alert")
    if alert in PAGER_MEANING:
        text = f"Its USGS PAGER alert is {alert}, meaning {PAGER_MEANING[alert]}."
        city = next((c for c in pk.get("cities", []) if c["name"] == place["ref"]), None)
        if city and city.get("mmi"):
            word = usgs.MMI_WORDS[max(1, min(10, int(round(city["mmi"]))))]
            text += f" In {city['name']}, shaking was likely {word}."
            facts.append(Fact("city_mmi", f"{city['name']} MMI {city['mmi']:.1f}", page, [], "PAGER cities.json"))
        beats.append(Beat(text, "impact", {"big": alert.upper(), "small": "USGS PAGER alert", "tone": alert}))
        facts.append(Fact("pager", alert, page, [], pk.get("pager_impact", "")))
    hist = pk.get("pager_history")
    if hist:
        beats.append(Beat(f"The zone is active. In {hist['year']}, a magnitude {hist['mag']} quake struck about "
                          f"{hist['km']} kilometres {hist['direction']} of this one.", "history",
                          {"big": f"M{hist['mag']} · {hist['year']}", "small": f"{hist['km']} km {hist['direction']}"}))
        evidence = pk.get("pager_history_text", "")
        if hist.get("measured"):
            evidence += (f" Distance and direction measured between the USGS epicentres ({hist['lat']}, {hist['lon']}) "
                         f"and this event's: about {hist['km']} km {hist['direction']}.")
        facts.append(Fact("history", f"M{hist['mag']} {hist['date']}", page, [hist["year"], hist["mag"], str(hist["km"])],
                          evidence))
    beats.append(Beat("Every number here comes from USGS. Follow for the data behind the world's biggest events.",
                      "outro", {"big": "Orbitwire", "small": "Data: USGS · not real footage"}, pause_after=0.6))

    keep = _contour_extent(pk.get("mmi_contours"), 5.0)
    ref_city = next((c for c in pk.get("cities", []) if c["name"] == place["ref"]), None)
    if ref_city:
        keep.append((ref_city["lat"], ref_city["lon"]))
    if hist and hist.get("lat") is not None:
        keep.append((hist["lat"], hist["lon"]))
    bbox = _bbox(q.lat, q.lon, keep)
    scene = {
        "template": "quake",
        "bbox": bbox,
        "epicentre": {"lat": q.lat, "lon": q.lon, "depth_km": q.depth, "mag": q.mag},
        "faulting": pk.get("faulting"),
        "dip": pk.get("mt_dip", 45.0),
        "alert": alert,
        "cities": [{"name": c["name"], "lat": c["lat"], "lon": c["lon"], "mmi": c.get("mmi")}
                   for c in pk.get("cities", [])[:5]],
        "history": hist if hist and hist.get("lat") is not None else None,
        "aftershocks": pk.get("aftershocks", []),
        "contours": pk.get("mmi_contours"),
        "labels": {"region": region},
        "ref": place["ref"],
    }
    loss = alert in ("orange", "red")
    title = f"How the M{mag} {region} quake ruptured, in 3D"
    return Short(
        id=f"eq-{event_id}", kind="quake", title=title, beats=beats, facts=facts, sources=[page], loss=loss,
        scene=scene, event_time=q.time.isoformat(),
        tags=["earthquake", f"{region} earthquake", f"magnitude {mag}", "USGS", "3D map", "explained", "geology"],
        summary=f"A magnitude {mag} earthquake struck {q.place} at {when}, {q.time.year}, at a depth USGS puts at "
                f"about {depth} km.",
        credits=[CHANNEL_CREDIT, terrain.CREDIT],
        hashtags=["earthquake", region, "science"],
    )
