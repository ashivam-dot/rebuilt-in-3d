"""The episode's thumbnail (1280x720): its own hero map frame, 2-5 words in Anton, a number badge from the plan's facts
and a "data map" ribbon. Then the legibility test ported from pangaea-nights/studio/thumbnail.py: at phone-feed size
(320x180) Tesseract must read every word back, and the words must have 4.5:1 contrast with what is behind them;
failing layouts are retried darker, smaller, or on a panel. Without tesseract (a laptop) the OCR step is skipped
and the result says so; the workflow installs it."""
from __future__ import annotations

import difflib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from ..compose import _font

W, H = 1280, 720
INK = (255, 255, 255)
BADGE = (255, 196, 70)
RIBBON = "DATA MAP · NOT REAL FOOTAGE"


def _lum(rgb: np.ndarray) -> np.ndarray:
    c = rgb / 255.0
    c = np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * c[..., 0] + 0.7152 * c[..., 1] + 0.0722 * c[..., 2]


def contrast(text_rgb: tuple, background: np.ndarray) -> float:
    lt = float(_lum(np.array(text_rgb, np.float32)[None, None])[0, 0])
    lb = float(np.percentile(_lum(background.astype(np.float32)), 90))
    return (max(lt, lb) + 0.05) / (min(lt, lb) + 0.05)


def ocr_words(img: Image.Image, psm: int = 6) -> list[str]:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.png"
        img.save(p)
        out = subprocess.run(["tesseract", str(p), "stdout", "--psm", str(psm)], capture_output=True,
                             text=True).stdout
    return re.findall(r"[a-z0-9']+", out.lower())


def legible(img: Image.Image, words: list[str], box: tuple) -> tuple[bool | None, list[str]]:
    if not shutil.which("tesseract"):
        return None, []
    small = img.resize((320, 180), Image.LANCZOS)
    sx, sy, m = 320 / img.width, 180 / img.height, 6
    region = small.crop((max(0, int(box[0] * sx) - m), max(0, int(box[1] * sy) - m),
                         min(320, int(box[2] * sx) + m), min(180, int(box[3] * sy) + m)))
    seen = []
    for k in (3, 4, 5):
        up = ImageOps.autocontrast(region.resize((region.width * k, region.height * k), Image.LANCZOS).convert("L"))
        up = ImageOps.expand(up, border=32, fill=up.getpixel((0, 0)))
        for view in (up, ImageOps.invert(up)):
            seen += ocr_words(view, 6) + ocr_words(view, 11)
    missing = [w for w in (re.sub(r"[^a-z0-9']", "", x.lower()) for x in words)
               if w and not any(difflib.SequenceMatcher(None, w, s).ratio() >= 0.8 for s in seen)]
    return not missing, seen


def words_for(ep) -> tuple[list[str], str]:
    """(the 2-5 headline words, the badge): both stated by the plan's facts."""
    if ep.kind == "quake-region":
        n = next((f.numbers[0] for c in ep.chapters for f in c.facts if f.key == "history-count" and f.numbers), "")
        return ep.topic.upper().split()[:3] + ["KEEPS", "SHAKING"], (f"{n} M6+ QUAKES SINCE 1900" if n else "")
    peak = next(f for c in ep.chapters for f in c.facts if f.key == "peak")
    mph = next(n for n in peak.numbers if n.isdigit() and int(n) > 60 and f"{n} mph" in peak.value)
    return [ep.topic.upper(), mph, "MPH"], "NOAA BEST TRACK"


def _shaded(base: Image.Image, shade: float) -> Image.Image:
    grad = np.clip(1 - np.linspace(0, 1.25, W), 0, 1) ** 1.3 * shade
    return Image.fromarray((np.asarray(base, np.float32) * (1 - grad[None, :, None])).astype(np.uint8))


def _layout(base: Image.Image, words: list[str], badge: str, size: int, shade: float, panel: bool):
    img = _shaded(base, shade)
    lines = [" ".join(words[:-2]), " ".join(words[-2:])] if len(words) > 2 else [" ".join(words)]
    f = _font("Anton-Regular.ttf", size)
    while max(f.getlength(ln) for ln in lines) > W * 0.55 and size > 70:
        size -= 6
        f = _font("Anton-Regular.ttf", size)
    asc, desc = f.getmetrics()
    block_h = len(lines) * (asc + desc)
    y0 = (H - block_h) // 2 - 30
    if panel:
        width = int(max(f.getlength(ln) for ln in lines))
        backing = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(backing).rectangle((40, y0 - 24, 100 + width, y0 + block_h + 24), fill=(8, 10, 14, 225))
        img = img.convert("RGBA")
        img.alpha_composite(backing)
        img = img.convert("RGB")
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for i, ln in enumerate(lines):
        d.text((70, y0 + i * (asc + desc)), ln, font=f, fill=INK + (255,))
    box = layer.getbbox() or (0, 0, W // 2, H)
    halo = layer.split()[3].filter(ImageFilter.GaussianBlur(14)).point(lambda v: min(255, int(v * 1.6)))
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow.putalpha(halo)
    out = img.convert("RGBA")
    out.alpha_composite(shadow)
    out.alpha_composite(layer)
    d = ImageDraw.Draw(out)
    if badge:
        bf = _font("Montserrat.ttf", 40, "Bold")
        bw = int(bf.getlength(badge)) + 40
        d.rounded_rectangle((70, box[3] + 26, 70 + bw, box[3] + 94), radius=10, fill=BADGE + (255,))
        d.text((90, box[3] + 36), badge, font=bf, fill=(10, 14, 20, 255))
    rf = _font("Montserrat.ttf", 24, "SemiBold")
    rw = int(rf.getlength(RIBBON)) + 32
    d.rectangle((W - rw - 24, H - 58, W - 24, H - 20), fill=(0, 0, 0, 190))
    d.text((W - rw - 8, H - 53), RIBBON, font=rf, fill=(255, 255, 255, 230))
    return out.convert("RGB"), box, img


def build(hero: Path, ep, out: Path) -> dict:
    words, badge = words_for(ep)
    if not 2 <= len(words) <= 5:
        raise ValueError(f"thumbnail needs 2-5 words, got {words}")
    src = Image.open(hero).convert("RGB")
    base = src.resize((W, round(src.height * W / src.width)), Image.LANCZOS).crop((0, 0, W, H))
    attempts = []
    for size, shade, panel in ((170, 0.55, False), (170, 0.75, False), (146, 0.85, False), (128, 0.92, False),
                               (150, 0.6, True), (128, 0.6, True)):
        img, box, plain = _layout(base, words, badge, size, shade, panel)
        ratio = contrast(INK, np.asarray(plain)[box[1]:box[3], box[0]:box[2]])
        ok, seen = legible(img, words, box)
        attempts.append({"size": size, "shade": shade, "panel": panel, "contrast": round(ratio, 2), "ocr": seen,
                         "ok": ok})
        if ok is not False and ratio >= 4.5:
            img.save(out, quality=92)
            return {"path": str(out), "words": words, "badge": badge, "attempts": attempts, "ok": True,
                    "ocr_checked": ok is not None}
    img.save(out, quality=92)
    return {"path": str(out), "words": words, "badge": badge, "attempts": attempts, "ok": False,
            "ocr_checked": True}
