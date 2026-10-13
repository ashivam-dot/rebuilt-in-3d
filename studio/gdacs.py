"""GDACS alerts (EU JRC / UN OCHA): cyclones, floods, volcanoes and quakes rated Orange or Red.

An alert is a signal, never a source: the radar looks for the disaster's own Wikipedia article ("Cyclone Montha
(2026)", "2026 Nepal floods") and the Short is written from that article like any other story.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from . import net

RSS = "https://www.gdacs.org/xml/rss.xml"
NS = {"gdacs": "http://www.gdacs.org", "geo": "http://www.w3.org/2003/01/geo/wgs84_pos#"}
KINDS = {"EQ": "earthquake", "TC": "cyclone", "FL": "flood", "VO": "volcano", "WF": "wildfire"}
# The word a disaster's article title carries, for the search that finds it.
WORD = {"earthquake": "earthquake", "cyclone": "cyclone", "flood": "floods", "volcano": "eruption",
        "wildfire": "wildfires"}


def alerts(levels=("Orange", "Red"), kinds=tuple(KINDS)) -> list[dict]:
    root = ET.fromstring(net.get(RSS, timeout=30))
    out = []
    for item in root.iter("item"):
        level = item.findtext("gdacs:alertlevel", namespaces=NS)
        kind = item.findtext("gdacs:eventtype", namespaces=NS)
        if level not in levels or kind not in kinds:
            continue
        pub = item.findtext("pubDate")
        out.append({
            "id": f"gdacs-{kind}-{item.findtext('gdacs:eventid', namespaces=NS)}",
            "kind": kind, "level": level, "title": (item.findtext("title") or "")[:160],
            "country": (item.findtext("gdacs:country", namespaces=NS) or "").strip(),
            "link": item.findtext("link"), "published": parsedate_to_datetime(pub).isoformat() if pub else None,
            "lat": item.findtext("geo:Point/geo:lat", namespaces=NS), "lon": item.findtext("geo:Point/geo:long", namespaces=NS),
        })
    return out


def subject(alert: dict) -> tuple[str | None, str]:
    """(the name a disaster's article would carry, its radar category): a storm's own name, a volcano's name, or the
    country of a quake or flood."""
    cat, title = KINDS[alert["kind"]], alert.get("title") or ""
    if alert["kind"] == "TC":
        m = re.search(r"tropical cyclone ([A-Z][A-Z\-]*?)-\d{2}\b", title, re.I)
        name = m.group(1).title() if m and not re.search(r"\d|^(ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN|"
                                                         r"ELEVEN|TWELVE|THIRTEEN|FOURTEEN|FIFTEEN|SIXTEEN|"
                                                         r"SEVENTEEN|EIGHTEEN|NINETEEN|TWENTY)", m.group(1)) else None
        return name, cat
    if alert["kind"] == "VO":
        m = re.search(r"for ([A-Z][\w\-' ]+?) in ", title)
        return (m.group(1).strip() if m else None), cat
    m = re.search(r"\bin ([A-Z][A-Za-z .'\-]+?)(?: \d{2}/\d{2}/\d{4}|,|$)", title)
    country = alert.get("country") or (m.group(1).strip() if m else "")
    return (country.split(",")[0].strip() or None), cat
