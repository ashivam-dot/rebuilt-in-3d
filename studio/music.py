"""A quiet score written in code for each Short (no samples, so no licence or Content ID claims).

"tribute": soft piano arpeggios over a warm pad, in a minor key, slow. "news": a low pulse and pad, steadier.
The key is chosen from the story id, so consecutive Shorts don't sound identical.
"""
from __future__ import annotations

import hashlib

import numpy as np

SR = 44100
PROGRESSIONS = {
    "tribute": [(57, "m"), (53, "M"), (48, "M"), (55, "M")],  # Am F C G
    "news": [(50, "m"), (46, "M"), (53, "M"), (48, "M")],  # Dm Bb F C
}


def _hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def _chord(root: int, kind: str) -> list[int]:
    return [root, root + (3 if kind == "m" else 4), root + 7]


def _piano(f: float, dur: float, vel: float) -> np.ndarray:
    t = np.arange(int(dur * SR)) / SR
    tone = sum((1 / n ** 1.4) * np.sin(2 * np.pi * f * n * (1 + 0.0004 * n * n) * t) * np.exp(-t * (1.2 + 0.9 * n))
               for n in range(1, 9))
    attack = np.minimum(1, t / 0.006)
    return (vel * tone * attack).astype(np.float32)


def _pad(freqs: list[float], dur: float) -> np.ndarray:
    t = np.arange(int(dur * SR)) / SR
    out = np.zeros_like(t)
    for f in freqs:
        for detune in (-0.12, 0.0, 0.12):
            g = f * 2 ** (detune / 12)
            out += sum((0.6 / n) * np.sin(2 * np.pi * g * n * t + n) for n in range(1, 5))
    env = np.minimum(1, t / 1.2) * np.minimum(1, (dur - t) / 1.2).clip(0, 1)
    return (out * env / (len(freqs) * 3)).astype(np.float32)


def _reverb(x: np.ndarray, seconds: float = 2.8, wet: float = 0.35, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    ir = rng.standard_normal(n).astype(np.float32) * np.exp(-np.arange(n) / SR * 3.2).astype(np.float32)
    ir /= np.sqrt((ir ** 2).sum())
    size = 1 << int(np.ceil(np.log2(len(x) + n)))
    y = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)[:len(x)].astype(np.float32)
    return (1 - wet) * x + wet * y


def score(seconds: float, mood: str, seed_text: str) -> np.ndarray:
    """Stereo float32 [n, 2] at 44.1 kHz, peak about -6 dBFS, with fades."""
    seed = int(hashlib.sha1(seed_text.encode()).hexdigest()[:8], 16)
    shift = [0, 2, -2, 3, -3][seed % 5]
    bpm = 66 if mood == "tribute" else 84
    beat = 60 / bpm
    bar = 4 * beat
    total = int((seconds + 1 + bar + 4) * SR)
    left = np.zeros(total, np.float32)
    right = np.zeros(total, np.float32)
    prog = PROGRESSIONS.get(mood, PROGRESSIONS["tribute"])
    rng = np.random.default_rng(seed)
    t0, k = 0.0, 0
    while t0 < seconds + 1:
        root, kind = prog[k % len(prog)]
        notes = [n + shift for n in _chord(root, kind)]
        start = int(t0 * SR)
        pad = _pad([_hz(n - 12) for n in notes], bar + 1.2)
        end = min(total, start + len(pad))
        left[start:end] += 0.5 * pad[:end - start]
        right[start:end] += 0.5 * pad[:end - start]
        if mood == "tribute":
            pattern = [notes[0], notes[1], notes[2], notes[1] + 12, notes[2], notes[1], notes[0] + 12, notes[2]]
            for i, n in enumerate(pattern):
                s = int((t0 + i * beat / 2) * SR)
                tone = _piano(_hz(n + 12), 2.4, 0.22 + 0.05 * rng.random())
                e = min(total, s + len(tone))
                pan = 0.5 + 0.25 * np.sin(i)
                left[s:e] += (1 - pan) * tone[:e - s]
                right[s:e] += pan * tone[:e - s]
        else:
            for i in range(8):
                s = int((t0 + i * beat / 2) * SR)
                tone = _piano(_hz(notes[0] - 24), 0.5, 0.35 if i % 2 == 0 else 0.18)
                e = min(total, s + len(tone))
                left[s:e] += tone[:e - s]
                right[s:e] += tone[:e - s]
        t0 += bar
        k += 1
    left, right = _reverb(left, seed=seed), _reverb(right, seed=seed + 1)
    mix = np.stack([left, right], axis=1)[: int(seconds * SR)]
    fade_in, fade_out = int(1.0 * SR), int(1.8 * SR)
    mix[:fade_in] *= np.linspace(0, 1, fade_in)[:, None]
    mix[-fade_out:] *= np.linspace(1, 0, fade_out)[:, None]
    return (mix / max(np.abs(mix).max(), 1e-6) * 0.5).astype(np.float32)
