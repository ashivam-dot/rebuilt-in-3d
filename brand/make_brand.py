"""Orbitwire channel art: a real-relief globe with an orbit ring and a live pulse, in the videos' own palette.

Writes brand/avatar.png and avatar.jpg (800x800), brand/banner.png (2560x1440) and brand/watermark.png
(150x150, transparent).
"""
import asyncio
import base64
import io
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from studio import terrain

OUT = ROOT / "brand"
FONT = (ROOT / "studio" / "web" / "vendor" / "InterVariable.woff2").as_uri()
CENTER = (24.0, 48.0)  # lat, lon: Europe, Africa, the Middle East and India face the viewer
PIN = (25.25, 55.36)  # Dubai


def world() -> tuple[np.ndarray, dict]:
    h, meta = terrain.dem([-180, -84, 180, 84], target_px=2048)
    return np.asarray(terrain.texture(h, meta, width=2048), dtype=np.float32), meta


def globe(tex: np.ndarray, meta: dict, size: int) -> tuple[str, tuple[float, float]]:
    """Orthographic globe as a transparent PNG, lit from the upper left; returns it and the pin's position (0..1)."""
    n = size * 2
    ys, xs = np.mgrid[0:n, 0:n]
    u, v = (xs + 0.5) / n * 2 - 1, 1 - (ys + 0.5) / n * 2
    r2 = u * u + v * v
    inside = r2 <= 1
    w = np.sqrt(np.clip(1 - r2, 0, 1))
    lat0, lon0 = map(math.radians, CENTER)
    lat = np.arcsin(np.clip(v * math.cos(lat0) + w * math.sin(lat0), -1, 1))
    lon = lon0 + np.arctan2(u, w * math.cos(lat0) - v * math.sin(lat0))
    lond = (np.degrees(lon) + 540) % 360 - 180
    latd = np.clip(np.degrees(lat), -84, 84)
    z = meta["z"]
    px = ((lond + 180) / 360 * 2 ** z - meta["x0"]) / (meta["x1"] - meta["x0"]) * tex.shape[1]
    lr = np.radians(latd)
    yy = (1 - np.log(np.tan(lr) + 1 / np.cos(lr)) / math.pi) / 2 * 2 ** z
    py = (yy - meta["y0"]) / (meta["y1"] - meta["y0"]) * tex.shape[0]
    col = tex[np.clip(py.astype(int), 0, tex.shape[0] - 1), np.clip(px.astype(int), 0, tex.shape[1] - 1)]
    light = np.array([-0.55, 0.5, 0.67])
    light /= np.linalg.norm(light)
    lam = np.clip(u * light[0] + v * light[1] + w * light[2], 0, 1)
    col = col * (0.28 + 0.9 * lam[..., None] ** 0.8)
    rim = np.clip((r2 - 0.82) / 0.18, 0, 1)[..., None]
    col = col * (1 - 0.5 * rim) + np.array([90, 190, 255]) * 0.5 * rim
    alpha = np.clip((1 - np.sqrt(r2)) * n / 2, 0, 1) * 255
    img = Image.fromarray(np.dstack([np.clip(col, 0, 255), alpha]).astype(np.uint8), "RGBA").resize((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    pl, po = math.radians(PIN[0]), math.radians(PIN[1]) - lon0
    pu = math.cos(pl) * math.sin(po)
    pv = math.cos(lat0) * math.sin(pl) - math.sin(lat0) * math.cos(pl) * math.cos(po)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(), ((pu + 1) / 2, (1 - pv) / 2)


def mark_svg(globe_uri: str, pin: tuple[float, float], size: int, background: bool) -> str:
    """Globe, a tilted orbit ring passing behind and in front of it, a satellite, and a pulse on the story."""
    W, g0, gs = 1024, 192, 640
    px, py = g0 + pin[0] * gs, g0 + pin[1] * gs
    bg = """<radialGradient id="bg" cx="50%" cy="45%" r="65%"><stop offset="0" stop-color="#132a4f"/>
      <stop offset="1" stop-color="#050a14"/></radialGradient>""" if background else ""
    back = '<rect width="1024" height="1024" fill="url(#bg)"/>' if background else ""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
      width="{size}" height="{size}" viewBox="0 0 {W} {W}">
    <defs>{bg}
      <radialGradient id="halo"><stop offset="0.62" stop-color="#4cc3ff" stop-opacity="0.35"/>
        <stop offset="1" stop-color="#4cc3ff" stop-opacity="0"/></radialGradient>
      <linearGradient id="ring" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#4cc3ff"/>
        <stop offset="0.55" stop-color="#9be7ff"/><stop offset="1" stop-color="#ffb000"/></linearGradient>
      <clipPath id="front"><rect x="0" y="512" width="1024" height="512"/></clipPath>
      <clipPath id="backc"><rect x="0" y="0" width="1024" height="512"/></clipPath>
    </defs>
    {back}
    <circle cx="512" cy="512" r="400" fill="url(#halo)"/>
    <g transform="rotate(-18 512 512)">
      <ellipse cx="512" cy="512" rx="470" ry="132" fill="none" stroke="url(#ring)" stroke-width="20" opacity="0.45"
        clip-path="url(#backc)"/>
    </g>
    <image xlink:href="{globe_uri}" x="{g0}" y="{g0}" width="{gs}" height="{gs}"/>
    <g transform="rotate(-18 512 512)">
      <ellipse cx="512" cy="512" rx="470" ry="132" fill="none" stroke="url(#ring)" stroke-width="24"
        clip-path="url(#front)"/>
      <circle cx="{512 + 470 * math.cos(math.radians(62)):.1f}" cy="{512 + 132 * math.sin(math.radians(62)):.1f}" r="30"
        fill="#ffb000" stroke="#fff4d6" stroke-width="8"/>
    </g>
    <circle cx="{px:.1f}" cy="{py:.1f}" r="78" fill="none" stroke="#ff4d3d" stroke-width="10" opacity="0.45"/>
    <circle cx="{px:.1f}" cy="{py:.1f}" r="46" fill="none" stroke="#ff4d3d" stroke-width="12" opacity="0.8"/>
    <circle cx="{px:.1f}" cy="{py:.1f}" r="20" fill="#ff4d3d" stroke="#ffffff" stroke-width="7"/>
    </svg>"""


def page(body: str, w: int, h: int, transparent: bool = False) -> str:
    bg = "transparent" if transparent else "#050a14"
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
      @font-face {{ font-family: Inter; src: url('{FONT}') format('woff2'); font-weight: 100 900; }}
      html, body {{ margin: 0; width: {w}px; height: {h}px; background: {bg}; overflow: hidden; font-family: Inter; }}
    </style></head><body>{body}</body></html>"""


def banner_html(bg: str, icon: str) -> str:
    body = f"""
    <div style="position:absolute;inset:0;background:url('{bg}') center/cover"></div>
    <div style="position:absolute;inset:0;background:radial-gradient(ellipse 58% 52% at 50% 50%,
      rgba(5,10,20,0.45),rgba(5,10,20,0.93))"></div>
    <div style="position:absolute;left:507px;top:508px;width:1546px;height:423px;display:flex;align-items:center;
      justify-content:center;gap:40px">
      <div style="width:400px;height:400px;flex:none">{icon}</div>
      <div style="color:#fff">
        <div style="font-size:150px;font-weight:850;letter-spacing:-0.035em;line-height:1">Orbit<span
          style="font-weight:300;color:#7fd6ff">wire</span></div>
        <div style="margin-top:20px;font-size:46px;font-weight:600;color:#dbe4ee;white-space:nowrap">
          The world's biggest stories, in 3D</div>
        <div style="margin-top:28px;display:inline-block;font-size:27px;font-weight:700;letter-spacing:0.08em;color:#e9eef5;
          padding:10px 22px;border-radius:10px;border:2px solid rgba(255,176,0,0.85);background:rgba(8,17,29,0.6)">
          VERIFIED FACTS · SOURCES IN EVERY VIDEO · 3D, NOT REAL FOOTAGE</div>
      </div>
    </div>"""
    return page(body, 2560, 1440)


async def shoot(html: str, w: int, h: int, out: Path, transparent: bool = False) -> None:
    from playwright.async_api import async_playwright

    tmp = OUT / f"_{out.stem}.html"
    tmp.write_text(html, encoding="utf-8")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        p = await browser.new_page(viewport={"width": w, "height": h})
        await p.goto(tmp.as_uri())
        await p.evaluate("document.fonts.ready")
        await p.wait_for_timeout(300)
        await p.screenshot(path=str(out), omit_background=transparent)
        await browser.close()
    tmp.unlink()


def banner_bg(tex: np.ndarray, meta: dict) -> str:
    """The world from 68N, centred on 20E so the old world fills the middle."""
    w = tex.shape[1]
    img = Image.fromarray(np.roll(tex, -round(20 / 360 * w), axis=1).astype(np.uint8))
    top = round((terrain.lat2y(68, meta["z"]) - meta["y0"]) / (meta["y1"] - meta["y0"]) * tex.shape[0])
    img = img.crop((0, top, w, top + round(w * 1440 / 2560))).resize((2560, 1440), Image.LANCZOS)
    img = ImageEnhance.Brightness(img).enhance(0.85)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def main() -> None:
    OUT.mkdir(exist_ok=True)
    tex, meta = world()
    big, pin = globe(tex, meta, 900)
    small, _ = globe(tex, meta, 200)
    asyncio.run(shoot(page(mark_svg(big, pin, 800, True), 800, 800), 800, 800, OUT / "avatar.png"))
    asyncio.run(shoot(page(mark_svg(small, pin, 150, False), 150, 150, True), 150, 150, OUT / "watermark.png", True))
    asyncio.run(shoot(banner_html(banner_bg(tex, meta), mark_svg(big, pin, 400, False)), 2560, 1440, OUT / "banner.png"))
    Image.open(OUT / "avatar.png").convert("RGB").save(OUT / "avatar.jpg", quality=92)
    for name in ("avatar.png", "avatar.jpg", "watermark.png", "banner.png"):
        im = Image.open(OUT / name)
        print(name, im.size, im.mode, (OUT / name).stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
