"""Find the story's person in each photo: YuNet (MIT) detects faces, SFace (Apache-2.0) matches them across photos.

The subject is the face that recurs across the set, so a group photo is framed on them rather than on whoever stands
next to them, and a photo in which they cannot be found is dropped from a person's Short.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from . import net

MODELS = Path(__file__).resolve().parents[1] / "work" / "cache" / "models"
ZOO = "https://github.com/opencv/opencv_zoo/raw/main/models/"
YUNET = ("face_detection_yunet_2023mar.onnx", ZOO + "face_detection_yunet/face_detection_yunet_2023mar.onnx")
SFACE = ("face_recognition_sface_2021dec.onnx", ZOO + "face_recognition_sface/face_recognition_sface_2021dec.onnx")
SAME_PERSON = 0.36  # SFace cosine similarity; the model's published threshold is 0.363
_nets: dict = {}


def _file(spec: tuple[str, str]) -> str:
    path = MODELS / spec[0]
    if not path.exists():
        MODELS.mkdir(parents=True, exist_ok=True)
        path.write_bytes(net.get(spec[1], timeout=120))
    return str(path)


def _detector(w: int, h: int):
    import cv2

    if "det" not in _nets:
        _nets["det"] = cv2.FaceDetectorYN.create(_file(YUNET), "", (w, h), 0.6)
    _nets["det"].setInputSize((w, h))
    return _nets["det"]


def _recognizer():
    import cv2

    if "rec" not in _nets:
        _nets["rec"] = cv2.FaceRecognizerSF.create(_file(SFACE), "")
    return _nets["rec"]


def detect(bgr: np.ndarray) -> list[dict]:
    """[{box: (x, y, w, h), score, feature}] for faces at least 4% of the image's shorter side.

    Detection runs at most 800 px wide (YuNet misses faces that fill a large frame); boxes are in full-size pixels.
    """
    import cv2

    h, w = bgr.shape[:2]
    scale = min(1.0, 800 / max(w, h))
    small = cv2.resize(bgr, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else bgr
    sh, sw = small.shape[:2]
    _, found = _detector(sw, sh).detect(small)
    out = []
    for row in [] if found is None else found:
        x, y, fw, fh = (float(v) / scale for v in row[:4])
        if min(fw, fh) < 0.04 * min(w, h):
            continue
        rec = _recognizer()
        feature = rec.feature(rec.alignCrop(small, row)).flatten()
        out.append({"box": (x, y, fw, fh), "score": float(row[-1]), "feature": feature / np.linalg.norm(feature)})
    return out


def subject(per_photo: list[list[dict]]) -> list[dict | None]:
    """For each photo, the face that best matches the faces in the other photos (None when nobody matches).

    With a single photo, or when no face recurs, the largest face is taken.
    """
    picks: list[dict | None] = []
    for i, faces in enumerate(per_photo):
        best, best_score = None, -1.0
        for f in faces:
            sims = [max(float(f["feature"] @ g["feature"]) for g in other)
                    for j, other in enumerate(per_photo) if j != i and other]
            agree = sum(s >= SAME_PERSON for s in sims)
            score = agree + (np.mean(sims) if sims else 0.0)
            if score > best_score:
                best, best_score = f, score
        others = sum(1 for j, o in enumerate(per_photo) if j != i and o)
        if best is not None and others and best_score < 1:
            best = None  # the person's face isn't confirmed anywhere else in the set
        if best is None and faces and not others:
            best = max(faces, key=lambda f: f["box"][2] * f["box"][3])
        picks.append(best)
    return picks
