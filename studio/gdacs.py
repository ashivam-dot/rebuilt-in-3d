"""GDACS alerts (EU JRC / UN OCHA): cyclones, floods, volcanoes and quakes rated Orange or Red, as a watch list."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from . import net

RSS = "https://www.gdacs.org/xml/rss.xml"
NS = {"gdacs": "http://www.gdacs.org", "geo": "http://www.w3.org/2003/01/geo/wgs84_pos#"}


def alerts(levels=("Orange", "Red"), kinds=("EQ", "TC", "FL", "VO", "WF")) -> list[dict]:
    root = ET.fromstring(net.get(RSS))
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
            "link": item.findtext("link"), "published": parsedate_to_datetime(pub).isoformat() if pub else None,
            "lat": item.findtext("geo:Point/geo:lat", namespaces=NS), "lon": item.findtext("geo:Point/geo:long", namespaces=NS),
        })
    return out
