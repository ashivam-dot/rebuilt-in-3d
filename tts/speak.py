"""Read a narration job and write one WAV per line with Chatterbox (MIT): python speak.py job.json

job.json: {"lines": ["...", ...], "out": "/dir", "exaggeration": 0.6, "cfg_weight": 0.4, "voice": "/ref.wav" | null,
"seed": 7}. Writes out/line00.wav ... and out/lines.json with each file's duration and sample rate.
"""
import json
import sys
import time
from pathlib import Path

import torch
import torchaudio as ta
from chatterbox.tts import ChatterboxTTS


def main(job_path: str) -> None:
    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    out = Path(job["out"])
    out.mkdir(parents=True, exist_ok=True)
    torch.manual_seed(job.get("seed", 7))
    torch.set_num_threads(max(1, torch.get_num_threads()))
    model = ChatterboxTTS.from_pretrained(device="cpu")
    if job.get("voice"):
        model.prepare_conditionals(job["voice"], exaggeration=job.get("exaggeration", 0.5))
    rows = []
    for i, text in enumerate(job["lines"]):
        t = time.time()
        wav = model.generate(text, audio_prompt_path=None, exaggeration=job.get("exaggeration", 0.5),
                             cfg_weight=job.get("cfg_weight", 0.5), temperature=job.get("temperature", 0.8))
        path = out / f"line{i:02d}.wav"
        ta.save(str(path), wav, model.sr)
        rows.append({"file": str(path), "seconds": wav.shape[-1] / model.sr, "sr": model.sr,
                     "took": round(time.time() - t, 1)})
        print(f"line {i}: {rows[-1]['seconds']:.1f} s audio in {rows[-1]['took']} s", flush=True)
    (out / "lines.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
