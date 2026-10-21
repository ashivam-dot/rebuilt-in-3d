"""The open data an episode is explained from, all public domain (US federal works):
- USGS ComCat (FDSN event service): every catalogued earthquake since 1900, for the history chapter and the map;
- USGS event products: the event's own "general-text" (Key Points and Tectonic Summary, written by USGS
  scientists: the mechanism chapter's source) and its operational aftershock forecast ("oaf": the what-comes-next
  chapter; often missing, so the caller has a fallback);
- NOAA NHC best tracks (ATCF b-decks, this season) and HURDAT2 (the reanalysed record since 1949/1851).
GDACS is not used here: its terms ask for attribution and limit reuse, and the federal sources cover the same storms.
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from pathlib import Path

from .. import net, usgs

CACHE = Path(__file__).resolve().parents[2] / "work" / "cache" / "longform"
COUNT = "https://earthquake.usgs.gov/fdsnws/event/1/count"
BTK = "https://ftp.nhc.noaa.gov/atcf/btk/"
HURDAT = "https://www.nhc.noaa.gov/data/hurdat/"
COMCAT_URL = "https://earthquake.usgs.gov/earthquakes/search/"
HURDAT_URL = "https://www.nhc.noaa.gov/data/#hurdat"
KT_TO_MPH = 1.15078
BASIN_WORDS = {"al": "Atlantic", "ep": "eastern Pacific", "cp": "central Pacific"}


# --- earthquakes --------------------------------------------------------------------------------------------------

def _event(f: dict) -> dict:
    lon, lat, depth = f["geometry"]["coordinates"]
    p = f["properties"]
    t = datetime.fromtimestamp(p["time"] / 1000, timezone.utc)
    return {"id": f["id"], "mag": round(float(p["mag"]), 1), "time": t.isoformat(timespec="seconds"), "year": t.year,
            "lat": round(float(lat), 3), "lon": round(float(lon), 3), "depth": round(float(depth or 0), 1),
            "place": p.get("place") or ""}


def history(lat: float, lon: float, km: float = 500, min_mag: float = 6.0, start: str = "1900-01-01",
            end: str | None = None) -> list[dict]:
    """Every catalogued quake of min_mag or more within km of (lat, lon) since start, oldest first."""
    params = {"format": "geojson", "latitude": lat, "longitude": lon, "maxradiuskm": km, "minmagnitude": min_mag,
              "starttime": start, "orderby": "time-asc"}
    if end:
        params["endtime"] = end
    return [_event(f) for f in net.get_json(usgs.QUERY, params=params, timeout=(10, 90))["features"]
            if f["properties"].get("mag") is not None]


def count(lat: float, lon: float, km: float = 500, min_mag: float = 6.0, start: str = "1900-01-01") -> int:
    return int(net.get_json(COUNT, params={"format": "geojson", "latitude": lat, "longitude": lon,
                                           "maxradiuskm": km, "minmagnitude": min_mag, "starttime": start},
                            timeout=(10, 60))["count"])


def comcat_query(lat: float, lon: float, km: float, min_mag: float, start: str) -> str:
    """A URL a viewer can open to see the same list (the FDSN query as CSV)."""
    return (f"{usgs.QUERY}?format=csv&latitude={lat}&longitude={lon}&maxradiuskm={km:g}&minmagnitude={min_mag:g}"
            f"&starttime={start}&orderby=time-asc")


def _strip(markup: str) -> str:
    text = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", markup, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    return "\n".join(ln.strip() for ln in text.splitlines() if ln.strip())


BOILERPLATE = re.compile(r"Did You Feel It|tsunami\.gov|please visit|tell us about it|updated \w+ \d+", re.I)


def general_text(detail: dict) -> str:
    """USGS's own write-up of the event (Key Points, Tectonic Summary), without the links to other services."""
    out = []
    for prod in (detail.get("properties", {}).get("products", {}).get("general-text") or []):
        for name, c in (prod.get("contents") or {}).items():
            body = c.get("bytes")
            if body is None and c.get("url") and name.endswith((".html", "")):
                try:
                    body = net.get(c["url"], cache=CACHE).decode("utf-8", "replace")
                except Exception:  # noqa: BLE001 - the write-up is an extra; facts still come from the event
                    body = ""
            if body:
                out.append(_strip(body))
    lines = [ln for ln in "\n".join(out).splitlines() if not BOILERPLATE.search(ln)]
    return "\n".join(lines)


def forecast(detail: dict) -> dict | None:
    """The USGS aftershock forecast: when it was made and, per window ("1 Week", "1 Month"), the chance of at least
    one aftershock of each magnitude or larger. None when the event has none (common: only some events get one)."""
    prods = detail.get("properties", {}).get("products", {}).get("oaf") or []
    for prod in prods:
        c = (prod.get("contents") or {}).get("forecast.json") or {}
        if not c.get("url"):
            continue
        try:
            raw = net.get_json(c["url"], cache=CACHE)
        except Exception:  # noqa: BLE001
            return None
        made = datetime.fromtimestamp(raw["creationTime"] / 1000, timezone.utc)
        windows = [{"label": w["label"], "bins": [{"mag": float(b["magnitude"]), "p": float(b["probability"])}
                                                  for b in w.get("bins", [])]} for w in raw.get("forecast", [])]
        return {"made": made.isoformat(timespec="seconds"), "windows": windows,
                "url": usgs.EVENT_PAGE.format(id=detail["id"]) + "/oaf/forecast"}
    return None


def per_decade(events: list[dict], first: int = 1900, last: int | None = None) -> list[list]:
    """[["1900s", n], ...] for each decade from first to last (decades with none count 0)."""
    last = last or max([e["year"] for e in events] + [first])
    out = []
    for d in range(first - first % 10, last + 1, 10):
        out.append([f"{d}s", sum(1 for e in events if d <= e["year"] < d + 10)])
    return out


# --- tropical cyclones --------------------------------------------------------------------------------------------

def _latlon(lat: str, lon: str) -> tuple[float, float]:
    la = float(lat[:-1]) / 10 * (1 if lat.endswith("N") else -1)
    lo = float(lon[:-1]) / 10 * (-1 if lon.endswith("W") else 1)
    return la, lo


def parse_btk(text: str) -> dict:
    """An ATCF b-deck: one point per synoptic time (the 34/50/64-kt wind-radii rows repeat it), the storm's name."""
    points, names = {}, []
    for line in text.splitlines():
        f = [x.strip() for x in line.split(",")]
        if len(f) < 11 or f[4] != "BEST":
            continue
        t = datetime.strptime(f[2], "%Y%m%d%H").replace(tzinfo=timezone.utc)
        lat, lon = _latlon(f[6], f[7])
        points.setdefault(f[2], {"t": t.isoformat(timespec="minutes"), "lat": lat, "lon": lon, "kt": int(f[8]),
                                 "mb": int(f[9]) if f[9].isdigit() else None, "type": f[10]})
        if len(f) > 27 and f[27] and not re.match(r"INVEST|GENESIS", f[27]):
            names.append(f[27])
    rows = [points[k] for k in sorted(points)]
    named = [n for n in names if not re.fullmatch(r"(?:[A-Z]+-)?(?:ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN|"
                                                  r"ELEVEN|TWELVE|THIRTEEN|FOURTEEN|FIFTEEN|SIXTEEN|SEVENTEEN|"
                                                  r"EIGHTEEN|NINETEEN|TWENTY)(?:-\w+)?", n)]
    return {"name": named[-1].title() if named else None, "points": rows}


def btk_files(year: int) -> list[str]:
    listing = net.get(BTK, timeout=30).decode("utf-8", "replace")
    return sorted(set(re.findall(rf"b(?:al|ep|cp)[0-4]\d{year}\.dat", listing)))


def season(year: int, basin: str | None = None) -> list[dict]:
    """This season's storms from the b-decks: file, basin, name, peak winds (kt) and when it peaked."""
    out = []
    for name in btk_files(year):
        if basin and name[1:3] != basin:
            continue
        track = parse_btk(net.get(BTK + name, timeout=30).decode("utf-8", "replace"))
        if not track["points"]:
            continue
        peak = max(track["points"], key=lambda p: p["kt"])
        out.append({"file": name, "basin": name[1:3], "name": track["name"], "peak_kt": peak["kt"], "peak": peak,
                    "track": track["points"]})
    return out


def best_track(name: str, year: int) -> dict | None:
    """The named storm's b-deck this season, or None (an older season's storm, or a basin NHC does not track)."""
    for row in season(year):
        if (row["name"] or "").lower() == name.lower():
            return row | {"url": BTK + row["file"]}
    return None


def mph(kt: float) -> int:
    """Knots to mph the way NHC writes them: to the nearest 5 mph (105 kt = 120 mph)."""
    return int(5 * round(kt * KT_TO_MPH / 5))


def category(kt: float) -> int:
    """Saffir-Simpson category (0 below hurricane strength)."""
    return sum(kt >= v for v in (64, 83, 96, 113, 137))


def hurdat_file(basin: str) -> str:
    """The newest HURDAT2 file for a basin ("al" -> hurdat2-1851-YYYY-..., "ep"/"cp" -> hurdat2-nepac-...)."""
    listing = net.get(HURDAT, timeout=30).decode("utf-8", "replace")
    pattern = r"hurdat2-nepac-1949-(\d{4})-(\d+)a?\.txt" if basin in ("ep", "cp") else r"hurdat2-1851-(\d{4})-(\d+)\.txt"
    found = []
    for m in re.finditer(pattern, listing):
        stamp = m.group(2)
        mmdd, yy = stamp[:4], stamp[4:]
        year = int(yy) + (2000 if len(yy) == 2 else 0)
        found.append(((int(m.group(1)), year, mmdd), m.group(0)))
    if not found:
        raise RuntimeError(f"no HURDAT2 file for basin {basin}")
    return HURDAT + max(found)[1]


def parse_hurdat(text: str) -> list[dict]:
    storms, cur = [], None
    for line in text.splitlines():
        f = [x.strip() for x in line.split(",")]
        if len(f) >= 3 and re.fullmatch(r"[A-Z]{2}\d{6}", f[0]):
            cur = {"id": f[0], "name": f[1].title(), "year": int(f[0][4:]), "points": []}
            storms.append(cur)
        elif cur is not None and len(f) >= 7 and f[0].isdigit():
            lat = float(f[4][:-1]) * (1 if f[4].endswith("N") else -1)
            lon = float(f[5][:-1]) * (-1 if f[5].endswith("W") else 1)
            cur["points"].append({"t": f"{f[0][:4]}-{f[0][4:6]}-{f[0][6:]}T{f[1][:2]}:{f[1][2:]}", "lat": lat,
                                  "lon": lon, "kt": int(f[6]), "type": f[3]})
    return storms


def hurricanes_near(storms: list[dict], lat: float, lon: float, km: float = 400) -> list[dict]:
    """Storms that passed within km of (lat, lon) at hurricane strength (64 kt or more): id, name, year, peak there."""
    out = []
    for s in storms:
        near = [p for p in s["points"] if p["kt"] >= 64 and usgs.distance_bearing((lat, lon), (p["lat"], p["lon"]))[0] <= km]
        if near:
            out.append({"id": s["id"], "name": s["name"], "year": s["year"], "kt": max(p["kt"] for p in near),
                        "track": s["points"]})
    return out
