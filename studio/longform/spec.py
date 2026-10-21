"""What an episode is made of: the topic, its chapters (each with the facts and source text it may use and the
pictures it shows), and the data the pictures are drawn from. Written by plan, read by every later stage."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..spec import Fact


@dataclass
class Chapter:
    key: str  # its role: cold-open, what-happened, how-it-works, before, people, next, why-it-matters
    title: str  # the chapter name in the description's timestamps
    brief: str  # what this chapter must do, for the writer
    words: list[int]  # [fewest, most] words of narration
    facts: list[Fact]
    source: str = ""  # source text beside the facts (public-domain USGS/NOAA text, or Wikipedia), casualties removed
    visuals: list[dict] = field(default_factory=list)  # shots, in order (studio/longform/scenes.py)


@dataclass
class Episode:
    id: str
    kind: str  # "quake-region" or "cyclone"
    topic: str  # the place or storm, as the title names it
    title: str
    summary: str
    chapters: list[Chapter]
    sources: list[str]
    credits: list[str]
    center: list[float]  # [lat, lon]
    bbox: list[float]  # [west, south, east, north], 16:9 in Web Mercator
    publish_at: str  # ISO UTC
    tags: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    related: list[dict] = field(default_factory=list)  # the Shorts it grew from: {"id", "video_id", "title"}
    data: dict = field(default_factory=dict)  # marks and series for the pictures
    why: dict = field(default_factory=dict)  # how the topic was chosen: every candidate and its score

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=1, ensure_ascii=False), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> "Episode":
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["chapters"] = [Chapter(**{**c, "facts": [Fact(**f) for f in c["facts"]]}) for c in raw["chapters"]]
        return cls(**raw)


ROLES = ("cold-open", "what-happened", "how-it-works", "before", "people", "next", "why-it-matters")
