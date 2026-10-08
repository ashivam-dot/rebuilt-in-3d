"""What a Short is made of: the facts it may state (each with its source), the narration beats, and the scene."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Fact:
    key: str
    value: str
    source: str
    # Numbers the narration may say because of this fact, written as the narration writes them ("6.3", "8,700").
    numbers: list[str] = field(default_factory=list)
    # The field or sentence in the source that the value came from.
    evidence: str = ""


@dataclass
class Beat:
    text: str
    shot: str
    card: dict | None = None
    pause_after: float = 0.3


@dataclass
class Short:
    id: str
    kind: str
    title: str
    beats: list[Beat]
    facts: list[Fact]
    sources: list[str]
    loss: bool
    scene: dict
    tags: list[str] = field(default_factory=list)
    summary: str = ""
    event_time: str = ""
    credits: list[str] = field(default_factory=list)

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=1, ensure_ascii=False), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> "Short":
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["beats"] = [Beat(**b) for b in raw["beats"]]
        raw["facts"] = [Fact(**f) for f in raw["facts"]]
        return cls(**raw)

    @property
    def narration(self) -> str:
        return " ".join(b.text for b in self.beats)
