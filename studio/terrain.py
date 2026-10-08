"""Terrain for a scene: keyless Terrarium elevation tiles (land and sea floor), baked into a mesh grid and a
newsroom-style relief texture. Nothing photographic, so the picture reads as a data graphic."""
from __future__ import annotations

import io
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from . import net

TILE = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
CREDIT = ("Terrain: Mapzen Terrain Tiles on AWS (SRTM, GMTED2010, ETOPO1, GEBCO and others; "
          "https://github.com/tilezen/joerd/blob/master/docs/attribution.md)")
CACHE = Path(__file__).resolve().parents[1] / "work" / "cache" / "tiles"
MMI_COLORS = {4: (160, 230, 255), 5: (128, 255, 255), 6: (122, 255, 147), 7: (255, 255, 0), 8: (255, 200, 0),
              9: (255, 145, 0), 10: (255, 0, 0)}
LAND = [(0, (95, 122, 92)), (300, (128, 146, 102)), (900, (170, 162, 120)), (1800, (212, 202, 180)), (3200, (244, 244, 244))]
SEA = [(-8000, (8, 30, 56)), (-4000, (14, 48, 84)), (-1500, (28, 78, 118)), (-200, (52, 118, 158)), (0, (84, 150, 186))]


def lon2x(lon: float, z: int) -> float:
    return (lon + 180) / 360 * 2 ** z


def lat2y(lat: float, z: int) -> float:
    r = math.radians(lat)
    return (1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * 2 ** z


def x2lon(x, z):
    return x / 2 ** z * 360 - 180


def y2lat(y, z):
    n = np.pi - 2 * np.pi * np.asarray(y) / 2 ** z
    return np.degrees(np.arctan(np.sinh(n)))


def _tile(z: int, x: int, y: int) -> np.ndarray:
    raw = net.get(TILE.format(z=z, x=x % 2 ** z, y=y), cache=CACHE)
    rgb = np.asarray(Image.open(io.BytesIO(raw)).convert("RGB"), dtype=np.float32)
    return rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768


def elevation_at(lat: float, lon: float, z: int = 10) -> float:
    x, y = lon2x(lon, z), lat2y(lat, z)
    t = _tile(z, int(x), int(y))
    return float(t[min(255, int((y % 1) * 256)), min(255, int((x % 1) * 256))])


def dem(bbox: list[float], target_px: int = 1600) -> tuple[np.ndarray, dict]:
    west, south, east, north = bbox
    z = max(3, min(12, math.ceil(math.log2(target_px * 360 / (256 * (east - west))))))
    x0, x1 = lon2x(west, z), lon2x(east, z)
    y0, y1 = lat2y(north, z), lat2y(south, z)
    tx0, tx1, ty0, ty1 = int(x0), int(x1), int(y0), int(y1)
    mosaic = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256), dtype=np.float32)
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            mosaic[(ty - ty0) * 256:(ty - ty0 + 1) * 256, (tx - tx0) * 256:(tx - tx0 + 1) * 256] = _tile(z, tx, ty)
    c0, c1 = int((x0 - tx0) * 256), int(math.ceil((x1 - tx0) * 256))
    r0, r1 = int((y0 - ty0) * 256), int(math.ceil((y1 - ty0) * 256))
    meta = {"z": z, "x0": tx0 + c0 / 256, "x1": tx0 + c1 / 256, "y0": ty0 + r0 / 256, "y1": ty0 + r1 / 256}
    return mosaic[r0:r1, c0:c1], meta


def _ramp(h: np.ndarray, stops) -> np.ndarray:
    xs = [s for s, _ in stops]
    return np.stack([np.interp(h, xs, [c[i] for _, c in stops]) for i in range(3)], axis=-1)


def texture(h: np.ndarray, meta: dict, width: int = 2048) -> Image.Image:
    height = round(width * h.shape[0] / h.shape[1])
    hh = np.asarray(Image.fromarray(h).resize((width, height), Image.BILINEAR), dtype=np.float32)
    lat_mid = float(y2lat((meta["y0"] + meta["y1"]) / 2, meta["z"]))
    metres_px = 40075016.7 * math.cos(math.radians(lat_mid)) / 2 ** meta["z"] / 256 * h.shape[1] / width
    gy, gx = np.gradient(hh, metres_px)
    slope = np.arctan(np.hypot(gx, gy) * 3.0)
    aspect = np.arctan2(-gx, gy)
    az, alt = math.radians(315), math.radians(42)
    shade = np.clip(np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect), 0, 1)
    # Low-zoom tiles are coarse: classify land on a blurred surface and drop specks, so shores aren't pixel stairs.
    mask = Image.fromarray(((hh >= 0) * 255).astype(np.uint8))
    mask = mask.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.MinFilter(9))
    mask = mask.filter(ImageFilter.GaussianBlur(2)).point(lambda v: 255 if v > 127 else 0).filter(ImageFilter.MedianFilter(5))
    land = np.asarray(mask) > 127
    col = np.where(land[..., None], _ramp(np.maximum(hh, 0), LAND), _ramp(np.minimum(hh, 0), SEA))
    k = np.where(land, 0.45 + 0.65 * shade, 0.75 + 0.35 * shade)[..., None]
    col = np.clip(col * k, 0, 255)
    coast = Image.fromarray((land * 255).astype(np.uint8)).filter(ImageFilter.FIND_EDGES).filter(ImageFilter.MaxFilter(3))
    edge = np.asarray(coast, dtype=np.float32)[..., None] / 255
    col = col * (1 - 0.7 * edge) + np.array([236, 242, 246]) * 0.7 * edge
    return Image.fromarray(col.astype(np.uint8))


def contour_overlay(size: tuple[int, int], meta: dict, contours: dict | None) -> Image.Image:
    """ShakeMap intensity lines drawn on a transparent layer the page fades in."""
    w, h = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    z = meta["z"]

    def px(lon, lat):
        return ((lon2x(lon, z) - meta["x0"]) / (meta["x1"] - meta["x0"]) * w,
                (lat2y(lat, z) - meta["y0"]) / (meta["y1"] - meta["y0"]) * h)

    for f in (contours or {}).get("features", []):
        value = float(f["properties"].get("value", 0))
        if value < 4 or value != int(value):
            continue
        color = MMI_COLORS.get(int(value), (255, 255, 255))
        geom = f["geometry"]
        lines = geom["coordinates"] if geom["type"] == "MultiLineString" else [geom["coordinates"]]
        for line in lines:
            pts = [px(lon, lat) for lon, lat, *_ in line]
            if len(pts) > 1:
                draw.line(pts, fill=color + (90,), width=max(10, w // 120), joint="curve")
                draw.line(pts, fill=color + (255,), width=max(4, w // 320), joint="curve")
    return img


def grid(h: np.ndarray, meta: dict, origin: tuple[float, float], cols: int = 400) -> tuple[np.ndarray, dict]:
    """Mesh vertices in km around the origin (lat, lon): x east, y up (sea level 0), z south."""
    rows = round(cols * h.shape[0] / h.shape[1])
    g = np.asarray(Image.fromarray(h).resize((cols, rows), Image.BILINEAR), dtype=np.float32)
    z = meta["z"]
    lons = x2lon(np.linspace(meta["x0"], meta["x1"], cols), z)
    lats = y2lat(np.linspace(meta["y0"], meta["y1"], rows), z)
    lat0, lon0 = origin
    xs = (lons - lon0) * math.cos(math.radians(lat0)) * 111.320
    zs = -(lats - lat0) * 110.574
    X, Z = np.meshgrid(xs, zs)
    pos = np.stack([X, g / 1000.0, Z], axis=-1).astype(np.float32)
    info = {"cols": cols, "rows": rows, "xmin": float(xs[0]), "xmax": float(xs[-1]), "zmin": float(zs[0]),
            "zmax": float(zs[-1]), "hmin": float(g.min()), "hmax": float(g.max())}
    return pos, info


def to_km(lat: float, lon: float, origin: tuple[float, float]) -> tuple[float, float]:
    lat0, lon0 = origin
    return (lon - lon0) * math.cos(math.radians(lat0)) * 111.320, -(lat - lat0) * 110.574
