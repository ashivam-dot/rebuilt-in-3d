"""Relative depth for a photo with Depth Anything V2 Small (Apache-2.0), so a still can move like a camera shot."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

MODEL = "depth-anything/Depth-Anything-V2-Small-hf"
_pipe = None


def _model():
    global _pipe
    if _pipe is None:
        from transformers import pipeline

        _pipe = pipeline("depth-estimation", model=MODEL, device="cpu")
    return _pipe


def estimate(image: Image.Image, cache: Path | None = None) -> np.ndarray:
    """Depth in [0, 1], 1 = nearest, at the image's own size; cached as a .npy next to the photo."""
    if cache is not None and cache.exists():
        return np.load(cache)
    small = image.convert("RGB")
    if max(small.size) > 1024:
        small.thumbnail((1024, 1024))
    out = np.asarray(_model()(small)["predicted_depth"].squeeze(), dtype=np.float32)
    out = np.asarray(Image.fromarray(out).resize(image.size, Image.BICUBIC), dtype=np.float32)
    lo, hi = np.percentile(out, 2), np.percentile(out, 98)
    out = np.clip((out - lo) / max(hi - lo, 1e-6), 0, 1)
    if cache is not None:
        np.save(cache, out)
    return out
