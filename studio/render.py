"""Bake a story's scene, render it frame by frame in headless Chromium (CPU WebGL), and mux the narration."""
from __future__ import annotations

import asyncio
import base64
import functools
import json
import math
import shutil
import subprocess
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import soundfile as sf

from . import terrain
from .spec import Short

WEB = Path(__file__).resolve().parent / "web"
FPS = 30
TAIL = 0.8
BROWSER_ARGS = ["--use-angle=swiftshader", "--use-gl=angle", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]


def _focus_pose(x: float, z: float, span: float, angle: float) -> tuple[tuple, tuple, tuple]:
    """A slow push towards (x, z), seen from the south rotated by angle (radians) about the vertical."""
    c, s = math.cos(angle), math.sin(angle)
    rot = lambda dx, y, dz: (x + dx * c + dz * s, y, z - dx * s + dz * c)
    return rot(0.08 * span, 1.05 * span, 1.15 * span), rot(0.0, 0.95 * span, 1.0 * span), (x, 0.0, z)


def _poses(name: str, R: float, D: float, scene: dict) -> tuple[tuple, tuple, tuple]:
    """(start position, end position, look-at) for a shot, in scene units (km, y up, z south)."""
    if name in scene.get("focus", {}):
        return _focus_pose(*scene["focus"][name])
    ref = scene.get("ref_xz") or [0.0, 0.0]
    if name == "overview":
        return (0.3 * R, 1.55 * R, 2.05 * R), (-0.12 * R, 1.35 * R, 1.8 * R), (0, -0.05 * R, 0)
    if name == "approach":
        # Frame both the reference city and the epicentre; a portrait frame is narrow, so width counts double.
        mx, mz = ref[0] / 2, ref[1] / 2
        span = max(0.45 * R, math.hypot(1.9 * ref[0], ref[1]))
        return (mx + 0.08 * span, 1.05 * span, mz + 1.15 * span), (mx, 0.95 * span, mz + 1.0 * span), (mx, 0, mz)
    if name == "cut":
        return (0.14 * R, 0.22 * R, 1.45 * R), (-0.06 * R, 0.16 * R, 1.25 * R), (0, -0.55 * D, 0)
    if name == "fault":
        return (0.06 * R, 0.05 * R - 0.3 * D, 1.3 * R), (-0.03 * R, -0.35 * D, 1.15 * R), (0, -D, 0)
    if name == "shaking":
        return (0.05 * R, 2.25 * R, 1.05 * R), (0.18 * R, 2.05 * R, 0.92 * R), (0, 0, 0.05 * R)
    if name == "impact":
        lx, lz = ref[0] * 0.8, ref[1] * 0.8
        return (lx + 0.15 * R, 1.0 * R, lz + 1.2 * R), (lx + 0.04 * R, 0.9 * R, lz + 1.05 * R), (lx, 0, lz)
    if name == "history":
        hx, hz = scene.get("hist_xz") or [0, 0]
        mx, mz = hx * 0.75, hz * 0.75
        span = max(R * 0.6, math.hypot(hx, hz))
        return (mx + 0.1 * R, 1.2 * span, mz + 1.35 * span), (mx - 0.05 * R, 1.1 * span, mz + 1.2 * span), (mx, 0, mz)
    return (0.35 * R, 1.75 * R, 2.25 * R), (-0.3 * R, 1.65 * R, 2.15 * R), (0, -0.05 * R, 0)


def _camera(shots: list[dict], R: float, D: float, scene: dict) -> list[dict]:
    keys = []
    for i, s in enumerate(shots):
        start, end, look = _poses(s["name"], R, D, scene)
        if i == 0:
            keys.append({"t": 0.0, "pos": start, "look": look})
        else:
            keys.append({"t": s["t0"] + min(1.3, (s["t1"] - s["t0"]) * 0.45), "pos": start, "look": look})
        keys.append({"t": s["t1"], "pos": end, "look": look})
    return [{"t": round(k["t"], 3), "pos": [round(p, 3) for p in k["pos"]], "look": [round(p, 3) for p in k["look"]]}
            for k in keys]


def _clip(a: list[float], b: list[float], g: dict) -> tuple[list[float], list[float]] | None:
    """The part of segment a-b inside the grid box (Liang-Barsky), or None if it misses the box."""
    t0, t1 = 0.0, 1.0
    dx, dz = b[0] - a[0], b[1] - a[1]
    for p, q in ((-dx, a[0] - g["xmin"]), (dx, g["xmax"] - a[0]), (-dz, a[1] - g["zmin"]), (dz, g["zmax"] - a[1])):
        if p == 0:
            if q < 0:
                return None
            continue
        r = q / p
        if p < 0:
            t0 = max(t0, r)
        else:
            t1 = min(t1, r)
    if t0 > t1:
        return None
    return [a[0] + dx * t0, a[1] + dz * t0], [a[0] + dx * t1, a[1] + dz * t1]


def _bake_places(short: Short, timing: dict, stage: Path) -> dict:
    """Site and life-map scenes: terrain around the story's places, a marker, labels, and a route arc."""
    sc = short.scene
    origin = (sc["center"]["lat"], sc["center"]["lon"])
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(WEB, stage)
    out = stage / "scene"
    out.mkdir()
    h, meta = terrain.dem(sc["bbox"])
    tex = terrain.texture(h, meta)
    tex.save(out / "texture.jpg", quality=92)
    terrain.contour_overlay(tex.size, meta, None).save(out / "mmi.png")
    pos, g = terrain.grid(h, meta, origin)
    pos.tofile(out / "pos.bin")
    R = max(abs(g["xmin"]), abs(g["xmax"]), abs(g["zmin"]), abs(g["zmax"]))
    ex = int(max(1, min(25, round(R / 30))))
    deepest = float(-pos.reshape(-1, 3)[:, 1].min())
    slab = max(0.06 * R / ex, deepest * 1.15 + 0.02 * R / ex)
    km = lambda lat, lon: [round(v, 3) for v in terrain.to_km(lat, lon, origin)]
    inside = lambda x, z: g["xmin"] < x < g["xmax"] and g["zmin"] < z < g["zmax"]
    places = []
    for p in sc.get("places", []):
        x, z = km(p["lat"], p["lon"])
        if inside(x, z):
            places.append({"name": p["name"], "sub": p["sub"], "x": x, "z": z, "kind": p["kind"]})
    cities = [{"name": c["name"], "x": km(c["lat"], c["lon"])[0], "z": km(c["lat"], c["lon"])[1]} for c in sc.get("cities", [])]
    cities = [c for c in cities if inside(c["x"], c["z"])]
    route = None
    if sc.get("route"):
        a = km(sc["route"]["from"]["lat"], sc["route"]["from"]["lon"])
        b = km(sc["route"]["to"]["lat"], sc["route"]["to"]["lon"])
        seg = _clip(a, b, g)
        if seg:
            route = {"points": [seg[0], seg[1]],
                     "from": {"name": sc["route"]["from"]["name"], "x": seg[0][0], "z": seg[0][1], "edge": not inside(*a)},
                     "to": {"name": sc["route"]["to"]["name"], "x": seg[1][0], "z": seg[1][1], "edge": not inside(*b)}}
    shots = []
    for beat, (t0, t1) in zip(short.beats, timing["beats"]):
        shots.append({"name": beat.shot, "t0": t0, "t1": t1, "card": beat.card})
    shots[0]["t0"] = 0.0
    shots[-1]["t1"] = timing["duration"] + TAIL
    # Close shots stay wide enough that the 1600 px terrain texture stays sharp and the marker stays a marker.
    focus = {"site": [0.0, 0.0, 0.55 * R, 0.0], "toll": [0.0, 0.0, 0.45 * R, 0.5], "status": [0.0, 0.0, 0.7 * R, -0.35]}
    # A portrait frame is narrow: to fit a horizontal stretch dx the span must be about 1.9 dx (see "approach").
    frame = lambda a, b: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, max(0.5 * R, math.hypot(1.9 * (b[0] - a[0]), b[1] - a[1])), 0.0]
    if route:
        focus["route"] = focus["outro"] = frame(*route["points"])
    for p in places:
        focus[p["kind"]] = [p["x"], p["z"], 0.5 * R, 0.25 if p["kind"] == "born" else -0.25]
    if len(places) == 2:
        journey = frame([places[0]["x"], places[0]["z"]], [places[1]["x"], places[1]["z"]])
        focus["career"] = focus["outro"] = journey
        focus["overview"] = [journey[0], journey[1], journey[2] * 1.1, 0.2]
    scene = {
        "template": sc["template"], "grid": g, "radius": round(R, 3), "exaggeration": ex, "slab_km": round(slab, 3),
        "epicentre": None, "site": sc.get("site"), "places": places, "cities": cities, "route": route,
        "route_shot": "died" if sc["template"] == "life" else "route",
        "history": None, "aftershocks": [], "shots": shots, "words": timing["words"], "legend": [],
        "ref": None, "ref_xz": None, "hist_xz": None, "focus": focus,
        "credits": f"{sc['credits']} · Vertical scale ×{ex}",
    }
    scene["camera"] = _camera(shots, R, 0.0, scene)
    (out / "scene.json").write_text(json.dumps(scene), encoding="utf-8")
    return scene


def bake(short: Short, timing: dict, stage: Path) -> dict:
    sc = short.scene
    if sc.get("template", "quake") != "quake":
        return _bake_places(short, timing, stage)
    epi = sc["epicentre"]
    origin = (epi["lat"], epi["lon"])
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(WEB, stage)
    out = stage / "scene"
    out.mkdir()
    h, meta = terrain.dem(sc["bbox"])
    tex = terrain.texture(h, meta)
    tex.save(out / "texture.jpg", quality=92)
    terrain.contour_overlay(tex.size, meta, sc.get("contours")).save(out / "mmi.png")
    pos, g = terrain.grid(h, meta, origin)
    pos.tofile(out / "pos.bin")
    R = max(abs(g["xmin"]), abs(g["xmax"]), abs(g["zmin"]), abs(g["zmax"]))
    depth = float(epi["depth_km"])
    ex = int(max(1, min(6, round(0.35 * R / max(depth, 1)))))
    D = depth * ex
    km = lambda lat, lon: [round(v, 3) for v in terrain.to_km(lat, lon, origin)]
    cities = [{"name": c["name"], "x": km(c["lat"], c["lon"])[0], "z": km(c["lat"], c["lon"])[1]} for c in sc.get("cities", [])]
    cities = [c for c in cities if g["xmin"] < c["x"] < g["xmax"] and g["zmin"] < c["z"] < g["zmax"]]
    ref = next((c for c in cities if c["name"] == sc.get("ref")), cities[0] if cities else None)
    hist = sc.get("history")
    if hist:
        hx, hz = km(hist["lat"], hist["lon"])
        hist = {"x": hx, "z": hz, "mag": hist["mag"], "year": hist["year"]} if g["xmin"] < hx < g["xmax"] and g["zmin"] < hz < g["zmax"] else None
    shots = []
    for beat, (t0, t1) in zip(short.beats, timing["beats"]):
        shots.append({"name": beat.shot, "t0": t0, "t1": t1, "card": beat.card})
    shots[0]["t0"] = 0.0
    shots[-1]["t1"] = timing["duration"] + TAIL
    if not hist:
        shots = [s if s["name"] != "history" else {**s, "name": "outro"} for s in shots]
    levels = sorted({int(float(f["properties"]["value"])) for f in (sc.get("contours") or {}).get("features", [])
                     if float(f["properties"]["value"]) >= 4 and float(f["properties"]["value"]).is_integer()})
    roman = {4: "IV", 5: "V", 6: "VI", 7: "VII", 8: "VIII", 9: "IX", 10: "X"}
    legend = [{"roman": roman[v], "color": "#%02x%02x%02x" % terrain.MMI_COLORS[v]} for v in levels if v in roman]
    scene = {
        "grid": g, "radius": round(R, 3), "exaggeration": ex, "slab_km": round(max(depth * 1.7, 12.0), 2),
        "epicentre": {"depth_km": depth, "mag": epi["mag"]}, "faulting": sc.get("faulting"), "dip": sc.get("dip", 45),
        "cities": cities, "history": hist,
        "aftershocks": [{"x": km(a["lat"], a["lon"])[0], "z": km(a["lat"], a["lon"])[1], "mag": a["mag"]}
                        for a in sc.get("aftershocks", [])[:40]],
        "shots": shots, "words": timing["words"], "legend": legend,
        "ref": ref["name"] if ref else None, "ref_xz": [ref["x"], ref["z"]] if ref else None, "hist_xz": [hist["x"], hist["z"]] if hist else None,
        "credits": f"Data: USGS · Terrain: Mapzen/AWS Terrain Tiles · Vertical scale ×{ex}",
    }
    scene["camera"] = _camera(shots, R, D, scene)
    (out / "scene.json").write_text(json.dumps(scene), encoding="utf-8")
    return scene


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


async def _capture(stage: Path, duration: float, video: Path, stills: Path | None, still_times: list[float]) -> dict:
    from playwright.async_api import async_playwright

    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(stage)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    frames = math.ceil(duration * FPS)
    ffmpeg = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-c:v", "mjpeg", "-framerate",
                               str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                               "-pix_fmt", "yuv420p", "-r", str(FPS), str(video)], stdin=subprocess.PIPE)
    errors: list[str] = []
    t0 = time.time()
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, args=BROWSER_ARGS)
            page = await browser.new_page(viewport={"width": 1080, "height": 1920}, device_scale_factor=1)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            await page.goto(f"http://127.0.0.1:{server.server_port}/stage.html")
            try:
                await page.wait_for_function("window.ready === true", timeout=240000)
            except Exception as exc:
                raise RuntimeError(f"stage did not load: {errors[:5]}") from exc
            cdp = await page.context.new_cdp_session(page)
            wanted = {round(t * FPS): t for t in still_times}
            for i in range(frames):
                await page.evaluate(f"window.renderAt({i / FPS})")
                shot = await cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": 93, "optimizeForSpeed": True})
                ffmpeg.stdin.write(base64.b64decode(shot["data"]))
                if stills is not None and i in wanted:
                    png = await cdp.send("Page.captureScreenshot", {"format": "png"})
                    (stills / f"t{wanted[i]:05.1f}.png").write_bytes(base64.b64decode(png["data"]))
            await browser.close()
    finally:
        ffmpeg.stdin.close()
        ffmpeg.wait()
        server.shutdown()
    if errors:
        raise RuntimeError(f"stage errors: {errors[:5]}")
    return {"frames": frames, "seconds": round(time.time() - t0, 1), "s_per_frame": round((time.time() - t0) / frames, 3)}


def music_bed(path: Path, duration: float, rate: int = 48000) -> Path:
    """A quiet low drone generated here, so nothing can be claimed by Content ID."""
    t = np.arange(int(duration * rate)) / rate
    tones = [(55.0, 1.0), (82.41, 0.55), (110.0, 0.35), (164.81, 0.12)]
    swell = 0.6 + 0.4 * np.sin(2 * np.pi * t / 9.0) ** 2
    bed = sum(a * np.sin(2 * np.pi * f * t + i) for i, (f, a) in enumerate(tones)) * swell
    noise = np.convolve(np.random.default_rng(7).standard_normal(len(t)), np.ones(400) / 400, mode="same") * 2.0
    bed = bed + noise
    fade = np.minimum(1, np.minimum(t / 1.5, (duration - t) / 1.5))
    bed = (bed / np.abs(bed).max() * 0.5 * fade).astype(np.float32)
    sf.write(path, np.stack([bed, bed], axis=1), rate)
    return path


def mux(video: Path, narration: Path, bed: Path, out: Path) -> Path:
    graph = ("[1:a]aresample=48000,loudnorm=I=-15:TP=-2:LRA=7,apad[v];"
             "[2:a]volume=0.07[b];[v][b]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=9[a]")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(narration), "-i", str(bed),
                    "-filter_complex", graph, "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-ar", "48000", "-shortest", "-movflags", "+faststart", str(out)], check=True)
    return out


def render(short: Short, timing: dict, work: Path, stills: bool = True) -> dict:
    stage = work / "stage"
    scene = bake(short, timing, stage)
    duration = timing["duration"] + TAIL
    still_dir = work / "stills"
    if stills:
        still_dir.mkdir(parents=True, exist_ok=True)
    times = [round((s["t0"] + s["t1"]) / 2, 1) for s in scene["shots"]]
    stats = asyncio.run(_capture(stage, duration, work / "video.mp4", still_dir if stills else None, times))
    bed = music_bed(work / "bed.wav", duration)
    final = mux(work / "video.mp4", work / "narration.wav", bed, work / "short.mp4")
    return {"mp4": str(final), "duration": round(duration, 2), **stats, "exaggeration": scene["exaggeration"]}
