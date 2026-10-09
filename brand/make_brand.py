"""Channel art from the channel's own data look: a terrain diorama block with a cutaway to the hypocentre.

Writes brand/avatar.png (800x800), brand/banner.png (2560x1440) and brand/watermark.png (150x150, transparent).
"""
import asyncio
import base64
import io
import sys
from pathlib import Path

from PIL import Image, ImageEnhance

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from studio import terrain

OUT = ROOT / "brand"
FONT = (ROOT / "studio" / "web" / "vendor" / "InterVariable.woff2").as_uri()


def texture_b64(bbox, width, crop=None, dim=1.0) -> str:
    h, meta = terrain.dem(bbox, target_px=width)
    img = terrain.texture(h, meta, width=width)
    if crop:
        w, hgt = crop
        top = max(0, (img.height - hgt) // 2)
        img = img.resize((w, round(img.height * w / img.width))) if img.width != w else img
        img = img.crop((0, top, w, top + hgt))
    if dim != 1.0:
        img = ImageEnhance.Brightness(img).enhance(dim)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def block_svg(tex: str, size: int, background: bool) -> str:
    """Isometric diorama: real relief on top, rock cutaway in front, hypocentre with rising waves."""
    W = 1024
    bg = """<defs>
      <radialGradient id="bg" cx="50%" cy="42%" r="62%"><stop offset="0" stop-color="#16294a"/>
        <stop offset="1" stop-color="#060c17"/></radialGradient>
    </defs><rect width="1024" height="1024" fill="url(#bg)"/>""" if background else ""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
      width="{size}" height="{size}" viewBox="0 0 {W} {W}">
    {bg}
    <defs>
      <clipPath id="top"><polygon points="512,214 818,390 512,566 206,390"/></clipPath>
      <linearGradient id="rockL" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#9a7550"/>
        <stop offset="1" stop-color="#4a3424"/></linearGradient>
      <linearGradient id="rockR" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7a5a3d"/>
        <stop offset="1" stop-color="#33241a"/></linearGradient>
      <radialGradient id="glow"><stop offset="0" stop-color="#ff6b3d" stop-opacity="0.9"/>
        <stop offset="1" stop-color="#ff6b3d" stop-opacity="0"/></radialGradient>
    </defs>
    <!-- left face: the cut, with strata and the hypocentre -->
    <polygon points="206,390 512,566 512,812 206,636" fill="url(#rockL)"/>
    <polyline points="206,470 512,646" stroke="#c9a27a" stroke-opacity="0.25" stroke-width="4" fill="none"/>
    <polyline points="206,556 512,732" stroke="#c9a27a" stroke-opacity="0.18" stroke-width="4" fill="none"/>
    <polygon points="206,390 512,566 512,592 206,416" fill="#2f6f9c" opacity="0.85"/>
    <!-- right face -->
    <polygon points="512,566 818,390 818,636 512,812" fill="url(#rockR)"/>
    <polygon points="512,566 818,390 818,416 512,592" fill="#25587d" opacity="0.85"/>
    <!-- top face: real terrain and sea floor -->
    <g clip-path="url(#top)">
      <image xlink:href="{tex}" width="1000" height="1000" preserveAspectRatio="none"
        transform="matrix(0.306 -0.176 0.306 0.176 206 390)"/>
    </g>
    <polygon points="512,214 818,390 512,566 206,390" fill="none" stroke="#e9eef5" stroke-opacity="0.55" stroke-width="3"/>
    <!-- hypocentre, depth line, waves -->
    <circle cx="372" cy="610" r="92" fill="url(#glow)"/>
    <ellipse cx="372" cy="610" rx="70" ry="70" fill="none" stroke="#ffb000" stroke-width="7" opacity="0.85"/>
    <line x1="372" y1="588" x2="372" y2="490" stroke="#ffffff" stroke-width="7" stroke-dasharray="16 12"/>
    <circle cx="372" cy="610" r="24" fill="#ff3b30"/>
    <!-- epicentre ring on the surface, above the hypocentre -->
    <ellipse cx="372" cy="486" rx="56" ry="32" fill="none" stroke="#ff3b30" stroke-width="9"/>
    <ellipse cx="372" cy="486" rx="92" ry="53" fill="none" stroke="#ff3b30" stroke-width="5" opacity="0.5"/>
    </svg>"""


def page(body: str, w: int, h: int, transparent: bool = False) -> str:
    bg = "transparent" if transparent else "#060c17"
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
      @font-face {{ font-family: Inter; src: url('{FONT}') format('woff2'); font-weight: 100 900; }}
      html, body {{ margin: 0; width: {w}px; height: {h}px; background: {bg}; overflow: hidden; font-family: Inter; }}
    </style></head><body>{body}</body></html>"""


def banner_html(bg: str, icon: str) -> str:
    body = f"""
    <div style="position:absolute;inset:0;background:url('{bg}') center/cover"></div>
    <div style="position:absolute;inset:0;background:radial-gradient(ellipse 60% 55% at 50% 50%,
      rgba(6,12,23,0.55),rgba(6,12,23,0.92))"></div>
    <div style="position:absolute;left:507px;top:508px;width:1546px;height:423px;display:flex;align-items:center;
      justify-content:center;gap:44px">
      <div style="width:380px;height:380px;flex:none">{icon}</div>
      <div style="color:#fff">
        <div style="font-size:132px;font-weight:820;letter-spacing:-0.02em;line-height:1">Rebuilt in 3D</div>
        <div style="margin-top:22px;font-size:42px;font-weight:560;color:#cfd8e3;white-space:nowrap">
          Earthquakes and natural hazards, rebuilt from official data</div>
        <div style="margin-top:26px;display:inline-block;font-size:28px;font-weight:700;letter-spacing:0.08em;color:#e9eef5;
          padding:10px 22px;border-radius:10px;border:2px solid rgba(255,176,0,0.8);background:rgba(8,17,29,0.6)">
          USGS DATA · EVERY NUMBER SOURCED · NOT REAL FOOTAGE</div>
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


def main() -> None:
    OUT.mkdir(exist_ok=True)
    island = texture_b64([167.55, -15.95, 168.45, -15.05], 1000)  # Ambae and Maewo, Vanuatu: the first Short
    japan = texture_b64([135.5, 32.0, 145.5, 40.0], 2560, crop=(2560, 1440), dim=0.9)  # Japan and its trench
    asyncio.run(shoot(page(block_svg(island, 800, True), 800, 800), 800, 800, OUT / "avatar.png"))
    asyncio.run(shoot(page(block_svg(island, 150, False), 150, 150, True), 150, 150, OUT / "watermark.png", True))
    asyncio.run(shoot(banner_html(japan, block_svg(island, 380, False)), 2560, 1440, OUT / "banner.png"))
    for name in ("avatar.png", "watermark.png", "banner.png"):
        im = Image.open(OUT / name)
        print(name, im.size, im.mode, (OUT / name).stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
