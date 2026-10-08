"""USGS earthquake feeds and products: the official (tier 1) source for every quake fact the channel states."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from . import net

FEED = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson"
DETAIL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/detail/{id}.geojson"
QUERY = "https://earthquake.usgs.gov/fdsnws/event/1/query"
EVENT_PAGE = "https://earthquake.usgs.gov/earthquakes/eventpage/{id}"
MMI_WORDS = {1: "not felt", 2: "weak", 3: "weak", 4: "light", 5: "moderate", 6: "strong", 7: "very strong",
             8: "severe", 9: "violent", 10: "extreme"}
ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII", 8: "VIII", 9: "IX", 10: "X"}
COMPASS = {"N": "north", "S": "south", "E": "east", "W": "west", "NE": "north-east", "NW": "north-west",
           "SE": "south-east", "SW": "south-west", "NNE": "north-north-east", "ENE": "east-north-east",
           "ESE": "east-south-east", "SSE": "south-south-east", "SSW": "south-south-west",
           "WSW": "west-south-west", "WNW": "west-north-west", "NNW": "north-north-west"}
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")


@dataclass
class Quake:
    id: str
    mag: float
    place: str
    time: datetime
    lat: float
    lon: float
    depth: float
    alert: str | None
    sig: int
    url: str

    @property
    def age_hours(self) -> float:
        return (datetime.now(timezone.utc) - self.time).total_seconds() / 3600


def _quake(feature: dict) -> Quake:
    p, (lon, lat, depth) = feature["properties"], feature["geometry"]["coordinates"]
    return Quake(feature["id"], float(p["mag"]), p["place"] or "", datetime.fromtimestamp(p["time"] / 1000, timezone.utc),
                 float(lat), float(lon), float(depth), p.get("alert"), int(p.get("sig") or 0), p["url"])


def recent() -> list[Quake]:
    return [_quake(f) for f in net.get_json(FEED)["features"] if f["properties"].get("type") == "earthquake"]


def detail(event_id: str) -> dict:
    return net.get_json(DETAIL.format(id=event_id))


def product(d: dict, name: str) -> dict | None:
    items = d["properties"].get("products", {}).get(name)
    return items[0] if items else None


def content(prod: dict, name: str):
    meta = prod.get("contents", {}).get(name)
    return net.get_json(meta["url"]) if meta else None


def round_people(n: float) -> int:
    """Two significant figures, the precision PAGER's estimates deserve."""
    if n < 100:
        return int(round(n, -1))
    digits = len(str(int(n))) - 2
    return int(round(n, -digits))


def fmt_int(n: int) -> str:
    return f"{n:,}"


def parse_place(place: str) -> dict:
    m = re.match(r"(?:(\d+) km ([NSEW]{1,3}) of )?(.+?)(?:, (.+))?$", place)
    if not m:
        return {"distance_km": None, "direction": None, "ref": place, "region": ""}
    dist, direc, ref, region = m.groups()
    return {"distance_km": int(dist) if dist else None, "direction": COMPASS.get(direc or "", direc), "ref": ref,
            "region": region or ""}


def faulting(rake: float) -> str:
    if 45 < rake < 135:
        return "reverse"
    if -135 < rake < -45:
        return "normal"
    return "strike-slip"


def date_words(t: datetime) -> str:
    return f"{MONTHS[t.month - 1]} {t.day}"


def historical(comment: str, events: list[dict], near: tuple[float, float] | None = None) -> dict | None:
    """The past quake PAGER's historical comment names, with its position from historical_earthquakes.json."""
    m = re.search(r"A magnitude (\d+(?:\.\d)?) earthquake (\d+) km (\w+) of this event struck .*? on (\w+ \d+, (\d{4}))",
                  comment or "")
    if not m:
        return None
    mag, km, direc, when, year = m.groups()
    match = next((e for e in events if abs(float(e.get("Magnitude", 0)) - float(mag)) < 0.05
                  and str(e.get("Time", "")).startswith(year)), None)
    lat, lon = (match["Lat"], match["Lon"]) if match else (None, None)
    if match is None and near is not None:
        day = datetime.strptime(when, "%B %d, %Y")
        found = net.get_json(QUERY, params={"format": "geojson", "starttime": day.strftime("%Y-%m-%d"),
                                            "endtime": (day.replace(hour=23, minute=59)).strftime("%Y-%m-%dT%H:%M"),
                                            "latitude": near[0], "longitude": near[1], "maxradiuskm": int(km) + 60,
                                            "minmagnitude": float(mag) - 0.3})["features"]
        if found:
            best = max(found, key=lambda f: f["properties"]["mag"])
            lon, lat = best["geometry"]["coordinates"][:2]
    out = {"mag": mag, "km": int(km), "direction": COMPASS.get(direc.upper(), direc.lower()), "date": when,
           "year": year, "lat": lat, "lon": lon, "measured": False}
    # PAGER's comment text is templated and has been seen with a wrong bearing ("95 km e ... struck UK" for a quake
    # due south), so when both epicentres are known, distance and direction come from the coordinates instead.
    if near is not None and lat is not None:
        dist, bearing = distance_bearing(near, (float(lat), float(lon)))
        out.update(km=int(round(dist / 5) * 5), direction=compass(bearing), measured=True)
    return out


def distance_bearing(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    """Great-circle distance (km) and initial bearing (degrees) from a to b, both (lat, lon)."""
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    d = 2 * 6371.0 * math.asin(math.sqrt(math.sin((la2 - la1) / 2) ** 2
                                         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2))
    y = math.sin(lo2 - lo1) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(lo2 - lo1)
    return d, (math.degrees(math.atan2(y, x)) + 360) % 360


def compass(bearing: float) -> str:
    return ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"][
        round(bearing / 45) % 8]


def aftershocks(q: Quake, radius_km: float = 150, min_mag: float = 4.0) -> list[dict]:
    data = net.get_json(QUERY, params={"format": "geojson", "starttime": q.time.isoformat(timespec="seconds"),
                                       "latitude": q.lat, "longitude": q.lon, "maxradiuskm": radius_km,
                                       "minmagnitude": min_mag, "orderby": "time-asc"})
    out = []
    for f in data["features"]:
        if f["id"] == q.id:
            continue
        lon, lat, depth = f["geometry"]["coordinates"]
        out.append({"mag": f["properties"]["mag"], "lat": lat, "lon": lon, "depth": depth,
                    "hours": (f["properties"]["time"] / 1000 - q.time.timestamp()) / 3600})
    return out


def pack(event_id: str) -> dict:
    """Everything a quake Short may say, read straight from the USGS event and its products."""
    d = detail(event_id)
    p = d["properties"]
    lon, lat, depth = d["geometry"]["coordinates"]
    q = Quake(event_id, float(p["mag"]), p["place"], datetime.fromtimestamp(p["time"] / 1000, timezone.utc),
              float(lat), float(lon), float(depth), p.get("alert"), int(p.get("sig") or 0), p["url"])
    origin = (product(d, "origin") or {}).get("properties", {})
    out = {"quake": q, "page": EVENT_PAGE.format(id=event_id), "place": parse_place(q.place),
           "mag_type": (origin.get("magnitude-type") or p.get("magType") or "").replace("mww", "Mww"),
           "depth_type": origin.get("depth-type", ""), "review": origin.get("review-status") or p.get("status"),
           "tsunami_flag": p.get("tsunami")}
    mt = product(d, "moment-tensor")
    if mt:
        props = mt["properties"]
        rake = props.get("nodal-plane-1-rake")
        if rake is not None:
            out["faulting"] = faulting(float(rake))
            out["mt_rake"] = float(rake)
            out["mt_dip"] = float(props.get("nodal-plane-1-dip", 45))
    pager = product(d, "losspager")
    if pager:
        exp = content(pager, "exposures.json") or {}
        agg = exp.get("population_exposure", {}).get("aggregated_exposure", [])
        out["exposure"] = {i + 1: n for i, n in enumerate(agg)}
        out["pager_alert"] = pager["properties"].get("alertlevel")
        out["max_mmi"] = float(pager["properties"].get("maxmmi") or 0)
        comments = content(pager, "comments.json") or {}
        out["pager_impact"] = comments.get("impact1", "")
        out["pager_history"] = historical(comments.get("historical_comment", ""),
                                          content(pager, "historical_earthquakes.json") or [], (q.lat, q.lon))
        out["pager_history_text"] = comments.get("historical_comment", "")
        cities = (content(pager, "cities.json") or {}).get("all_cities", [])
        out["cities"] = sorted(cities, key=lambda c: -c.get("pop", 0))[:8]
    shake = product(d, "shakemap")
    if shake:
        out["mmi_contours"] = content(shake, "download/cont_mmi.json")
    dyfi = product(d, "dyfi")
    if dyfi:
        out["felt_reports"] = int(dyfi["properties"].get("numResp") or 0)
    out["aftershocks"] = aftershocks(q)
    return out
