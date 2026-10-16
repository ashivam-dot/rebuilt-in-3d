"""Locator maps: where a news story happened, on OpenStreetMap's standard map (its roads, towns and borders) with the
site marked. They stand in for photos Commons does not have yet (a story's first days) beside at least one real photo,
and are always badged as maps: a map shows where, never what happened."""
from __future__ import annotations

import io
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import net, terrain

W, H = 1260, 2240  # a story plate (compose.MARGIN times the 1080x1920 frame), 9:16
SITE_Y = 0.40  # where the site sits down the plate: above the captions, below the hook
# Width of ground each map shows: the region, so viewers know which part of the world, then the town around the site.
SPANS = (("wide", 520.0), ("near", 16.0))
# OpenStreetMap's tile policy: a contact User-Agent (net.USER_AGENT), tiles cached, no bulk fetching, and the credit
# shown wherever the map is. A Short fetches about 50 tiles.
TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
CACHE = Path(__file__).resolve().parents[1] / "work" / "cache" / "osm"
UPSCALE = 2.6  # tile pixels are shown at most this much larger: the map's own labels stay readable on a phone
PAGE = "https://www.openstreetmap.org/copyright"
LICENSE = "CC BY-SA 2.0"
CREDIT = "Map: © OpenStreetMap contributors / CC BY-SA 2.0 / Orbitwire"
BADGE_X, BADGE_Y = 200, 0.57  # inside every camera move (compose.MARGIN, MOTIONS), clear of the hook and chips
MARKER = (232, 36, 36)
INK = (12, 16, 22)
FONTS = Path(__file__).resolve().parent / "fonts"


def _font(size: int, weight: str = "Bold") -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONTS / "Montserrat.ttf"), size)
    font.set_variation_by_name(weight)
    return font


def frame(lat: float, lon: float, width_km: float) -> dict:
    """The Web Mercator window (z0 tile units) width_km wide, 9:16, with the site at SITE_Y down from the top."""
    half = width_km / 2 / (111.320 * math.cos(math.radians(lat)))
    x0, x1 = terrain.lon2x(lon - half, 0), terrain.lon2x(lon + half, 0)
    dy = (x1 - x0) * H / W
    ys = terrain.lat2y(lat, 0)
    return {"x0": x0, "x1": x1, "y0": ys - SITE_Y * dy, "y1": ys + (1 - SITE_Y) * dy}


def project(win: dict, lat: float, lon: float) -> tuple[float, float]:
    return ((terrain.lon2x(lon, 0) - win["x0"]) / (win["x1"] - win["x0"]) * W,
            (terrain.lat2y(lat, 0) - win["y0"]) / (win["y1"] - win["y0"]) * H)


def zoom(win: dict) -> int:
    """The tile zoom whose pixels are shown between UPSCALE / 2 and UPSCALE times larger."""
    native = (win["x1"] - win["x0"]) * 256
    return max(2, min(18, math.ceil(math.log2(W / UPSCALE / native))))


def ground(win: dict) -> Image.Image:
    """The OpenStreetMap tiles under the window, stitched, cropped to it and scaled to the plate."""
    z = zoom(win)
    n = 2 ** z
    x0, x1, y0, y1 = (win[k] * n for k in ("x0", "x1", "y0", "y1"))
    tx0, tx1, ty0, ty1 = int(x0), int(x1), int(max(y0, 0)), int(min(y1, n - 1e-9))
    mosaic = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256), (170, 211, 223))
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            raw = net.get(TILES.format(z=z, x=tx % n, y=ty), cache=CACHE, timeout=30, tries=3)
            mosaic.paste(Image.open(io.BytesIO(raw)).convert("RGB"), ((tx - tx0) * 256, (ty - ty0) * 256))
    box = ((x0 - tx0) * 256, (y0 - ty0) * 256, (x1 - tx0) * 256, (y1 - ty0) * 256)
    return mosaic.resize((W, H), Image.LANCZOS, box=box)


def _pill(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, font, fill, ink, anchor: str = "mb"):
    box = draw.textbbox(xy, text, font=font, anchor=anchor)
    pad = font.size * 0.42
    draw.rounded_rectangle((box[0] - pad, box[1] - pad * 0.8, box[2] + pad, box[3] + pad * 0.8),
                           radius=font.size * 0.5, fill=fill)
    draw.text(xy, text, font=font, fill=ink, anchor=anchor)


def scale_km(width_km: float) -> float:
    """A round distance about a fifth of the map's width."""
    target = width_km / 5
    step = 10 ** math.floor(math.log10(target))
    return next(s * step for s in (5, 2, 1) if s * step <= target)


def draw(base: Image.Image, win: dict, site: tuple[float, float], label: str, width_km: float) -> Image.Image:
    """The map plate: the map a little dimmed, the site as a red marker named label, a scale bar and a MAP badge."""
    img = Image.blend(base.convert("RGB"), Image.new("RGB", (W, H), INK), 0.12).convert("RGBA")
    sx, sy = project(win, *site)
    halo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(halo).ellipse((sx - 72, sy - 72, sx + 72, sy + 72), fill=MARKER + (120,))
    img = Image.alpha_composite(img, halo.filter(ImageFilter.GaussianBlur(24)))
    over = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    d.ellipse((sx - 36, sy - 36, sx + 36, sy + 36), outline=MARKER + (255,), width=9)
    d.ellipse((sx - 14, sy - 14, sx + 14, sy + 14), fill=MARKER + (255,), outline=(255, 255, 255, 255), width=4)
    if label:
        _pill(d, (sx, sy - 66), label, _font(46), INK + (232,), (255, 255, 255, 255))
    # Badge and scale bar on the left, just above the captions: the camera crops the plate's edges, chips sit top
    # left, and YouTube's buttons cover the right.
    km = scale_km(width_km)
    bar = km / width_km * W
    x0, y = BADGE_X, round(BADGE_Y * H)
    badge = _font(34, "ExtraBold")
    _pill(d, (x0, y), "MAP", badge, INK + (225,), (255, 255, 255, 255), anchor="lm")
    bx = x0 + d.textlength("MAP", font=badge) + 44
    d.rectangle((bx, y + 6, bx + bar, y + 16), fill=(255, 255, 255, 255), outline=INK + (230,), width=3)
    d.text((bx, y - 2), f"{km:g} km", font=_font(32, "Bold"), fill=(255, 255, 255, 255), anchor="lb",
           stroke_width=5, stroke_fill=INK + (235,))
    return Image.alpha_composite(img, over).convert("RGB")


def short_label(text: str) -> str:
    return text if len(text) <= 32 else text[:31].rstrip() + "…"


def plates(site: tuple[float, float], label: str, folder: Path, where: str = "") -> list[dict]:
    """The wide and the close locator map of site as story photos (role "map"), saved in folder. The wide map names
    the town and region (where, "Bend, Oregon"), the close one the site itself (label)."""
    folder.mkdir(parents=True, exist_ok=True)
    around = f" around {where}" if where else ""
    out = []
    for name, km in SPANS:
        win = frame(site[0], site[1], km)
        img = draw(ground(win), win, site, short_label(where if name == "wide" and where else label), km)
        path = folder / f"map-{name}.jpg"
        img.save(path, quality=92)
        text = (f"MAP: the region{around}, where it happened marked" if name == "wide"
                else f"MAP: the streets{around}, the exact site marked")
        out.append({"file": f"OpenStreetMap ({name}): {short_label(label)}", "url": "", "page": PAGE, "width": W, "height": H,
                    "author": "OpenStreetMap contributors", "license": LICENSE, "description": text, "date": "",
                    "origin": "map", "path": str(path), "host": "OpenStreetMap", "role": "map", "focus": None,
                    "credit": CREDIT})
    return out


def is_map(photo: dict) -> bool:
    return photo.get("role") == "map"
