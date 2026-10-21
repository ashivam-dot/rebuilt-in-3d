"""A chapter's pictures, 1920x1080 at 30 fps: data maps on the episode's terrain plate (catalogued quakes appearing year by
year, aftershocks, cities, storm tracks), animated charts of the episode's series, number cards and the sources card,
with the chapter title, the narration as subtitles and a disclosure tag over them. Everything drawn is a data field of
the plan (spec.Episode.data); nothing is footage, and the tag says so. The Shorts' 3D stage is portrait-only, so this is
deliberately a 2D data film; the episode never claims "3D".

Each shot is a contiguous run of the chapter's sentences; shots cross-fade. The chapter lasts its narration plus TAIL
(END_HOLD more for the last chapter, under the sources card), rounded to whole frames: assemble.py pads the narration
to the same frame count, so picture and sound stay locked chapter after chapter.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from .. import terrain, usgs
from ..compose import _ease, _font
from .spec import Chapter, Episode

W, H, FPS = 1920, 1080, 30
PLATE = (2880, 1620)
TAIL = 0.8
END_HOLD = 4.0
CROSSFADE = 12  # frames
TITLE_HOLD = 3.6  # seconds the chapter title shows
ACCENT = (90, 200, 255)
WARM = (255, 196, 70)
DISCLOSURE = "DATA MAPS AND CHARTS · NOT REAL FOOTAGE · AI NARRATION"
DEPTH_COLORS = [(70, (255, 230, 80)), (300, (255, 140, 40)), (10_000, (230, 50, 50))]  # km -> RGB


def frames(seconds: float) -> int:
    return int(round(seconds * FPS))


def chapter_seconds(timing: dict, last: bool) -> float:
    return frames(timing["duration"] + TAIL + (END_HOLD if last else 0.0)) / FPS


# --- the map --------------------------------------------------------------------------------------------------------

class Atlas:
    """The episode's terrain plate (2880x1620, a little darkened so marks read) and its projection."""

    def __init__(self, ep: Episode, cache: Path):
        cache.mkdir(parents=True, exist_ok=True)
        png, meta_file = cache / "plate.png", cache / "plate.json"
        if png.exists() and meta_file.exists():
            self.meta = json.loads(meta_file.read_text())
            img = Image.open(png).convert("RGB")
        else:
            h, self.meta = terrain.dem(ep.bbox, PLATE[0])
            img = terrain.texture(h, self.meta, PLATE[0]).resize(PLATE, Image.LANCZOS)
            img = Image.blend(img, Image.new("RGB", PLATE, (6, 14, 26)), 0.22)
            img.save(png)
            meta_file.write_text(json.dumps(self.meta))
        self.rgb = np.asarray(img, dtype=np.uint8)
        self.blur = cv2.GaussianBlur(self.rgb, (0, 0), 14) // 2

    def px(self, lat: float, lon: float) -> tuple[float, float]:
        m = self.meta
        x = (terrain.lon2x(lon, m["z"]) - m["x0"]) / (m["x1"] - m["x0"]) * PLATE[0]
        y = (terrain.lat2y(lat, m["z"]) - m["y0"]) / (m["y1"] - m["y0"]) * PLATE[1]
        return x, y


def view(atlas: Atlas, focus, zoom: float) -> np.ndarray:
    """The 2x3 affine from plate to frame for a camera at focus (lat, lon or None: the middle) and zoom (1 = whole)."""
    s = W / PLATE[0] * zoom
    cx, cy = atlas.px(*focus) if focus else (PLATE[0] / 2, PLATE[1] / 2)
    hw, hh = W / 2 / s, H / 2 / s
    cx, cy = min(max(cx, hw), PLATE[0] - hw), min(max(cy, hh), PLATE[1] - hh)
    return np.array([[s, 0, W / 2 - s * cx], [0, s, H / 2 - s * cy]], dtype=np.float32)


def _apply(M: np.ndarray, x: float, y: float) -> tuple[int, int]:
    return int(round(M[0, 0] * x + M[0, 2])), int(round(M[1, 1] * y + M[1, 2]))


def depth_color(depth: float) -> tuple:
    return next(c for d, c in DEPTH_COLORS if depth < d)


def kt_color(kt: float) -> tuple:
    return [(64, (120, 200, 255)), (83, (255, 240, 110)), (96, (255, 180, 60)), (113, (255, 110, 50)),
            (10_000, (230, 40, 60))][[kt < v for v in (64, 83, 96, 113, 10_000)].index(True)][1]


class Labels:
    """Small text layers (city names, year counter), rendered once each."""

    def __init__(self):
        self.font = _font("Montserrat.ttf", 30, "SemiBold")
        self.big = _font("Anton-Regular.ttf", 92)
        self.cache = {}

    def get(self, text: str, big: bool = False) -> tuple[np.ndarray, np.ndarray]:
        key = (text, big)
        if key not in self.cache:
            f = self.big if big else self.font
            b = f.getbbox(text, stroke_width=4)
            img = Image.new("RGBA", (b[2] - b[0] + 12, b[3] - b[1] + 12), (0, 0, 0, 0))
            ImageDraw.Draw(img).text((6 - b[0], 6 - b[1]), text, font=f, fill=(255, 255, 255, 255), stroke_width=4,
                                     stroke_fill=(0, 0, 0, 255))
            a = np.asarray(img, dtype=np.float32)
            self.cache[key] = (a[..., :3], a[..., 3:4] / 255.0)
        return self.cache[key]


def blit(frame: np.ndarray, layer, x: int, y: int, alpha: float = 1.0) -> None:
    rgb, a = layer
    h, w = a.shape[:2]
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
    if x1 <= x0 or y1 <= y0 or alpha <= 0:
        return
    sub = frame[y0:y1, x0:x1].astype(np.float32)
    la = a[y0 - y:y1 - y, x0 - x:x1 - x] * alpha
    frame[y0:y1, x0:x1] = (sub * (1 - la) + rgb[y0 - y:y1 - y, x0 - x:x1 - x] * la).astype(np.uint8)


def draw_marks(frame: np.ndarray, atlas: Atlas, M: np.ndarray, shot: dict, data: dict, u: float, t: float,
               labels: Labels, end_year: int) -> None:
    marks = data.get("marks", {})
    s = M[0, 0] / (W / PLATE[0])  # zoom
    reveal = shot.get("reveal")
    for name in shot.get("marks", []):
        rows = marks.get(name) or []
        if name == "history" and rows:
            first = min(r["year"] for r in rows)
            year = first + (end_year - first) * _ease(u / 0.85) if reveal else end_year
            over = frame.copy()
            for r in rows:
                if r["year"] > year:
                    continue
                x, y = _apply(M, *atlas.px(r["lat"], r["lon"]))
                col = depth_color(r.get("depth", 0)) if shot.get("depth") else (255, 210, 90)
                rad = max(3, int((r["mag"] - 5.3) * 7 * min(s, 1.6)))
                cv2.circle(over, (x, y), rad, col, -1, cv2.LINE_AA)
            cv2.addWeighted(over, 0.62, frame, 0.38, 0, frame)
            for r in rows:
                if r["year"] <= year:
                    x, y = _apply(M, *atlas.px(r["lat"], r["lon"]))
                    rad = max(3, int((r["mag"] - 5.3) * 7 * min(s, 1.6)))
                    cv2.circle(frame, (x, y), rad, (20, 20, 20), 1, cv2.LINE_AA)
            if reveal:
                n = sum(1 for r in rows if r["year"] <= year)
                blit(frame, labels.get(f"{int(year)}", big=True), W - 330, 110)
                blit(frame, labels.get(f"{n} quakes of M6+"), W - 330, 220)
        elif name == "aftershocks":
            k = int(len(rows) * min(1.0, u / 0.7 + 0.15))
            for r in rows[:k]:
                x, y = _apply(M, *atlas.px(r["lat"], r["lon"]))
                cv2.circle(frame, (x, y), max(2, int((r["mag"] - 3.5) * 4)), (235, 235, 245), -1, cv2.LINE_AA)
        elif name == "shorts":
            for r in rows:
                x, y = _apply(M, *atlas.px(r["lat"], r["lon"]))
                pulse = (t * 0.8) % 1.0
                cv2.circle(frame, (x, y), int(14 + 70 * pulse), (255, 70, 60), 3, cv2.LINE_AA)
                cv2.circle(frame, (x, y), 13, (255, 70, 60), -1, cv2.LINE_AA)
                cv2.circle(frame, (x, y), 13, (255, 255, 255), 2, cv2.LINE_AA)
                if r.get("label") and len(rows) <= 3:
                    blit(frame, labels.get(r["label"]), x + 24, y - 20)
        elif name == "cities":
            for r in rows:
                x, y = _apply(M, *atlas.px(r["lat"], r["lon"]))
                cv2.circle(frame, (x, y), 7, (255, 255, 255), -1, cv2.LINE_AA)
                blit(frame, labels.get(r["label"]), x + 12, y - 18)
        elif name == "past":
            for storm in rows:
                pts = [_apply(M, *atlas.px(p["lat"], p["lon"])) for p in storm["points"]]
                if len(pts) > 1:
                    cv2.polylines(frame, [np.array(pts, np.int32)], False, (170, 180, 200), 2, cv2.LINE_AA)
        elif name == "track" and rows:
            k = max(2, int(len(rows) * min(1.0, u / 0.8))) if reveal else len(rows)
            pts = [(_apply(M, *atlas.px(p["lat"], p["lon"])), p["kt"]) for p in rows[:k]]
            for (a, _), (b, kt) in zip(pts, pts[1:]):
                cv2.line(frame, a, b, kt_color(kt), 6, cv2.LINE_AA)
            (x, y), kt = pts[-1]
            cv2.circle(frame, (x, y), 12, kt_color(kt), -1, cv2.LINE_AA)


# --- charts and cards ---------------------------------------------------------------------------------------------

def _num(v: float) -> str:
    return usgs.fmt_int(int(v)) if float(v).is_integer() or v >= 100 else f"{v:g}"


def chart(series: list[list], title: str, unit: str, grow: float) -> Image.Image:
    """Bars (16 or fewer values) or a line, grown to `grow` (0-1) of their height/length."""
    img = Image.new("RGB", (W, H), (10, 18, 30))
    d = ImageDraw.Draw(img)
    tf, lf, vf = _font("Anton-Regular.ttf", 64), _font("Montserrat.ttf", 26, "Medium"), _font("Montserrat.ttf", 30, "Bold")
    d.text((120, 70), title.upper(), font=tf, fill=(255, 255, 255))
    d.rectangle((120, 160, 220, 166), fill=ACCENT)
    x0, x1, y0, y1 = 140, W - 120, 250, H - 250
    values = [float(v) for _, v in series] or [0]
    top = max(values) or 1
    d.line((x0, y1, x1, y1), fill=(120, 140, 160), width=2)
    if len(series) <= 16:
        n = len(series)
        slot = (x1 - x0) / max(n, 1)
        bw = slot * 0.62
        for i, (label, v) in enumerate(series):
            g = _ease(min(1.0, grow * 1.3 - i * 0.3 / max(n, 1)))
            hgt = (y1 - y0) * float(v) / top * g
            bx = x0 + i * slot + (slot - bw) / 2
            if hgt > 0:
                d.rectangle((bx, y1 - hgt, bx + bw, y1), fill=WARM if float(v) == top else ACCENT)
            if g > 0.95:
                text = _num(float(v)) + unit
                tw = d.textlength(text, font=vf)
                d.text((bx + bw / 2 - tw / 2, y1 - hgt - 44), text, font=vf, fill=(255, 255, 255))
            lw = d.textlength(str(label), font=lf)
            d.text((bx + bw / 2 - lw / 2, y1 + 16), str(label), font=lf, fill=(200, 210, 222))
    else:
        n = len(series)
        k = max(2, int(n * _ease(grow)))
        pts = [(x0 + (x1 - x0) * i / (n - 1), y1 - (y1 - y0) * float(v) / top) for i, (_, v) in enumerate(series[:k])]
        d.line(pts, fill=ACCENT, width=7, joint="curve")
        peak = max(range(k), key=lambda i: float(series[i][1]))
        px, py = pts[peak]
        d.ellipse((px - 11, py - 11, px + 11, py + 11), fill=WARM)
        d.text((px + 16, py - 46), _num(float(series[peak][1])) + unit, font=vf, fill=(255, 255, 255))
        for i in (0, n // 2, n - 1):
            if i < k:
                lw = d.textlength(str(series[i][0]), font=lf)
                d.text((pts[i][0] - lw / 2, y1 + 16), str(series[i][0]), font=lf, fill=(200, 210, 222))
    return img


def card_layer(big: str, small: str) -> tuple[np.ndarray, np.ndarray]:
    bf = _font("Anton-Regular.ttf", 230)
    while bf.getlength(big) > W - 240 and bf.size > 90:
        bf = _font("Anton-Regular.ttf", bf.size - 10)
    sf_ = _font("Montserrat.ttf", 46, "SemiBold")
    bb, sb = bf.getbbox(big, stroke_width=6), sf_.getbbox(small)
    w = max(bb[2] - bb[0], sb[2] - sb[0]) + 60
    h = (bb[3] - bb[1]) + (sb[3] - sb[1]) + 90
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.text(((w - (bb[2] - bb[0])) / 2 - bb[0], 10 - bb[1]), big, font=bf, fill=WARM + (255,), stroke_width=6,
           stroke_fill=(0, 0, 0, 255))
    d.text(((w - (sb[2] - sb[0])) / 2 - sb[0], (bb[3] - bb[1]) + 60 - sb[1]), small, font=sf_,
           fill=(255, 255, 255, 255))
    a = np.asarray(img, dtype=np.float32)
    return a[..., :3], a[..., 3:4] / 255.0


def sources_image(ep: Episode) -> Image.Image:
    img = Image.new("RGB", (W, H), (10, 18, 30))
    d = ImageDraw.Draw(img)
    d.text((120, 90), "SOURCES", font=_font("Anton-Regular.ttf", 84), fill=(255, 255, 255))
    d.rectangle((120, 200, 240, 206), fill=ACCENT)
    f = _font("Montserrat.ttf", 32, "Medium")
    y = 250
    for line in ep.credits + ["All links are in the description."]:
        for part in _wrap(line, f, W - 260):
            d.text((120, y), part, font=f, fill=(220, 228, 236))
            y += 44
        y += 16
    d.text((120, H - 110), "ORBITWIRE EXPLAINS", font=_font("Anton-Regular.ttf", 48), fill=ACCENT)
    return img


def _wrap(text: str, font, width: int) -> list[str]:
    out, cur = [], ""
    for w in text.split():
        trial = f"{cur} {w}".strip()
        if font.getlength(trial) > width and cur:
            out.append(cur)
            cur = w
        else:
            cur = trial
    return out + ([cur] if cur else [])


# --- overlays -------------------------------------------------------------------------------------------------------

def title_layer(number: int, title: str) -> tuple[np.ndarray, np.ndarray]:
    nf, tf = _font("Montserrat.ttf", 34, "Bold"), _font("Anton-Regular.ttf", 96)
    tw = int(tf.getlength(title.upper())) + 80
    img = Image.new("RGBA", (max(tw, 400), 200), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, img.width - 1, 199), radius=16, fill=(8, 14, 24, 200))
    d.rectangle((24, 28, 32, 172), fill=ACCENT + (255,))
    d.text((52, 30), f"CHAPTER {number}", font=nf, fill=ACCENT + (255,))
    d.text((52, 70), title.upper(), font=tf, fill=(255, 255, 255, 255))
    a = np.asarray(img, dtype=np.float32)
    return a[..., :3], a[..., 3:4] / 255.0


def subtitle_layer(text: str) -> tuple[np.ndarray, np.ndarray]:
    f = _font("Montserrat.ttf", 40, "SemiBold")
    lines = _wrap(text, f, 1500)
    if len(lines) > 2:
        f = _font("Montserrat.ttf", 34, "SemiBold")
        lines = _wrap(text, f, 1600)
    lh = 52 if f.size == 40 else 46
    w = int(max(f.getlength(x) for x in lines)) + 56
    img = Image.new("RGBA", (w, lh * len(lines) + 30), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, img.height - 1), radius=12, fill=(0, 0, 0, 165))
    for i, x in enumerate(lines):
        d.text(((w - f.getlength(x)) / 2, 14 + i * lh), x, font=f, fill=(255, 255, 255, 255))
    a = np.asarray(img, dtype=np.float32)
    return a[..., :3], a[..., 3:4] / 255.0


def tag_layer() -> tuple[np.ndarray, np.ndarray]:
    f = _font("Montserrat.ttf", 22, "SemiBold")
    w = int(f.getlength(DISCLOSURE)) + 28
    img = Image.new("RGBA", (w, 40), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, 39), radius=8, fill=(0, 0, 0, 140))
    d.text((14, 8), DISCLOSURE, font=f, fill=(255, 255, 255, 210))
    a = np.asarray(img, dtype=np.float32)
    return a[..., :3], a[..., 3:4] / 255.0


# --- a chapter ------------------------------------------------------------------------------------------------------

def shots_for(ch: Chapter, spans: list[list[float]], seconds: float) -> list[dict]:
    """The chapter's visuals over its sentences: shot k covers a contiguous, near-equal run of sentences."""
    vis = ch.visuals or [{"type": "map", "marks": [], "focus": None, "zoom": [1.0, 1.1]}]
    n = len(spans)
    k = max(1, min(len(vis), n))
    bounds = [round(i * n / k) for i in range(k + 1)]
    out = []
    for i in range(k):
        start = 0.0 if i == 0 else spans[bounds[i]][0]
        end = seconds if i == k - 1 else spans[bounds[i + 1]][0]
        out.append(vis[i] | {"start": start, "end": end})
    return out


def drift(img: np.ndarray, u: float, amount: float = 0.035) -> np.ndarray:
    """A still picture with a slow push-in, so no shot holds a frozen frame (assemble.py's freeze check)."""
    z = 1 + amount * _ease(u)
    M = np.array([[z, 0, W / 2 * (1 - z)], [0, z, H / 2 * (1 - z)]], dtype=np.float32)
    return cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


class Painter:
    def __init__(self, ep: Episode, atlas: Atlas):
        self.ep, self.atlas, self.labels = ep, atlas, Labels()
        self.cards, self.charts, self.src = {}, {}, None
        times = [int(r["year"]) for r in ep.data.get("marks", {}).get("history", [])]
        self.end_year = max(times + [int(ep.publish_at[:4])])

    def frame(self, shot: dict, t: float) -> np.ndarray:
        u = (t - shot["start"]) / max(shot["end"] - shot["start"], 0.1)
        kind = shot["type"]
        if kind == "map":
            z0, z1 = shot.get("zoom", [1.0, 1.1])
            M = view(self.atlas, shot.get("focus"), z0 + (z1 - z0) * _ease(u))
            f = cv2.warpAffine(self.atlas.rgb, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            draw_marks(f, self.atlas, M, shot, self.ep.data, u, t, self.labels, self.end_year)
            return f
        if kind == "chart":
            g = min(1.0, (t - shot["start"]) / 1.6)
            key = (shot["series"], round(g, 2))
            if key not in self.charts:
                series = self.ep.data.get("series", {}).get(shot["series"]) or []
                self.charts = {k: v for k, v in self.charts.items() if k[0] == shot["series"]} | {
                    key: np.asarray(chart(series, shot["title"], shot.get("unit", ""), g))}
            return drift(self.charts[key], u)
        if kind == "card":
            M = view(self.atlas, self.ep.center, 1.1 + 0.08 * u)
            f = cv2.warpAffine(self.atlas.blur, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            key = (shot["big"], shot["small"])
            if key not in self.cards:
                self.cards[key] = card_layer(*key)
            layer = self.cards[key]
            a = _ease((t - shot["start"]) / 0.5)
            h, w = layer[1].shape[:2]
            blit(f, layer, (W - w) // 2, (H - h) // 2 - int(30 * (1 - a)), a)
            return f
        if self.src is None:
            self.src = np.asarray(sources_image(self.ep))
        return drift(self.src, u)


def render(ep: Episode, index: int, timing: dict, work: Path, atlas: Atlas) -> dict:
    """chapter.mp4 (video only) and hero.png in work."""
    ch = ep.chapters[index]
    last = index == len(ep.chapters) - 1
    seconds = chapter_seconds(timing, last)
    n = frames(seconds)
    spans = timing["beats"]
    shots = shots_for(ch, spans, seconds)
    lines = [b for b in json.loads((work / "chapter.json").read_text(encoding="utf-8"))["lines"]] \
        if (work / "chapter.json").exists() else []
    subs = [(s, e, subtitle_layer(text)) for (s, e), text in zip(spans, lines) if text.strip()]
    title, tag = title_layer(index + 1, ch.title), tag_layer()
    painter = Painter(ep, atlas)
    out = work / "chapter.mp4"
    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
         "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-g", str(FPS * 2),
         "-movflags", "+faststart", str(out)], stdin=subprocess.PIPE)
    hero_at = None
    for i in range(n):
        t = i / FPS
        k = next(j for j, s in enumerate(shots) if t < s["end"] or j == len(shots) - 1)
        f = painter.frame(shots[k], t)
        if k and (t - shots[k]["start"]) * FPS < CROSSFADE:
            a = (t - shots[k]["start"]) * FPS / CROSSFADE
            f = cv2.addWeighted(f, a, painter.frame(shots[k - 1], t), 1 - a, 0)
        if t < TITLE_HOLD:
            a = min(1.0, t / 0.4, (TITLE_HOLD - t) / 0.4)
            blit(f, title, 90, 90, a)
        blit(f, tag, W - tag[1].shape[1] - 30, H - 64 if not subs else 30, 0.9)
        sub = next((layer for s, e, layer in subs if s - 0.05 <= t < e), None)
        if sub is not None:
            blit(f, sub, (W - sub[1].shape[1]) // 2, H - sub[1].shape[0] - 70)
        if hero_at is None and shots[k]["type"] == "map" and t >= TITLE_HOLD + 0.5:
            hero_at = i
            # Without overlays or a mid-reveal counter: the thumbnail is drawn on it (thumb.py).
            Image.fromarray(painter.frame(shots[k] | {"reveal": False}, t)).save(work / "hero.png")
        enc.stdin.write(f.tobytes())
    enc.stdin.close()
    if enc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed to encode chapter {ch.key}")
    if hero_at is None:
        Image.fromarray(painter.frame(shots[0], 0.0)).save(work / "hero.png")
    return {"key": ch.key, "seconds": seconds, "frames": n, "shots": len(shots)}
