"""Gemini through Google AI Studio's free tier, used only when the repo has a GEMINI_API_KEY secret: the long-form
chapter drafts (a 300-word chapter is a lot for a 12B model on a CPU runner). Ported from hindi-news-desk/desk/gemini.py.
The key travels only in the x-goog-api-key header; it is never logged, printed or written anywhere. Every Gemini draft
still goes through the local evidence check (writer.check_verdict with Gemma), so a missing key changes speed, not
what may be said.

The models are discovered at run time (ListModels), newest Flash first, then Flash Lite, with a fixed list behind
them in case discovery fails. Each model has its own small daily quota: a 429 that names a daily limit moves on to
the next model, a short per-minute wait is waited out on the same one.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time

import requests

API = "https://generativelanguage.googleapis.com/v1beta/models"
FALLBACK = ("gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3-flash-preview",
            "gemini-flash-latest", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-flash-lite-latest")
TEXT_MODEL = re.compile(r"^gemini-(?:(?P<v>\d+(?:\.\d+)?)-)?flash(?P<lite>-lite)?(?P<tail>-preview(?:-[\w.-]+)?|-latest)?$")
MAX_WAIT = 70.0
READ_TIMEOUT = 240
MIN_GAP = 6.0
log = logging.getLogger("studio.longform.gemini")

_spent: set[str] = set()
_last: dict[str, float] = {}
_discovered: list[str] | None = None
_refused = False


class Unavailable(RuntimeError):
    """No Gemini model can answer now: no key, the key was refused, or every model is out of quota."""


def key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or None


def available() -> bool:
    return bool(key()) and not _refused


def _rank(name: str) -> tuple:
    m = TEXT_MODEL.match(name)
    version = float(m.group("v")) if m and m.group("v") else 0.0
    alias = bool(m and m.group("tail") == "-latest")
    preview = bool(m and m.group("tail") and m.group("tail") != "-latest")
    return (bool(m and m.group("lite")), alias, -version, preview, name)


def pick(names: list[str]) -> list[str]:
    """Text models from a ListModels answer, best first: Flash before Flash Lite, newer before older, stable before
    preview, and the -latest aliases after the pinned versions of their tier."""
    keep = [n for n in names if TEXT_MODEL.match(n)]
    return sorted(dict.fromkeys(keep), key=_rank)


def models() -> list[str]:
    global _discovered
    if _discovered is None:
        found: list[str] = []
        try:
            page = ""
            for _ in range(5):
                r = requests.get(API, headers={"x-goog-api-key": key() or ""}, timeout=30,
                                 params={"pageSize": 1000, **({"pageToken": page} if page else {})})
                if r.status_code != 200:
                    break
                data = r.json()
                found += [m["name"].split("/", 1)[-1] for m in data.get("models", [])
                          if "generateContent" in m.get("supportedGenerationMethods", [])]
                page = data.get("nextPageToken", "")
                if not page:
                    break
        except (requests.RequestException, ValueError):
            pass
        _discovered = pick(found)
        log.info("Gemini text models: %s", ", ".join(_discovered) or "(discovery failed; using the fixed list)")
    return list(dict.fromkeys(_discovered + sorted(FALLBACK, key=_rank)))


def _body(messages: list[dict], schema: dict | None, temperature: float, max_tokens: int) -> dict:
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                for m in messages if m["role"] != "system"]
    config = {"temperature": temperature, "maxOutputTokens": max(max_tokens, 8192)}
    if schema:
        config |= {"responseMimeType": "application/json", "responseJsonSchema": schema}
    body = {"contents": contents, "generationConfig": config}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    return body


def _json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = min([i for i in (text.find("{"), text.find("[")) if i >= 0] or [0])
        return json.JSONDecoder().raw_decode(text[start:])[0]


def _daily(error: dict) -> bool:
    return any("perday" in str(v.get("quotaId", "")).lower()
               for d in error.get("details", []) for v in d.get("violations", []))


def _delay(error: dict) -> float | None:
    for d in error.get("details", []):
        if str(d.get("@type", "")).endswith("RetryInfo"):
            try:
                return float(str(d.get("retryDelay", "")).rstrip("s"))
            except ValueError:
                return None
    return None


def chat(messages: list[dict], schema: dict | None = None, temperature: float = 0.7,
         max_tokens: int = 4096) -> tuple[dict | str, str]:
    """(answer, model) from the first model with quota left. Raises Unavailable when none can answer."""
    global _refused
    if not available():
        raise Unavailable("GEMINI_API_KEY is not set" if not key() else "Gemini refused the key")
    body = _body(messages, schema, temperature, max_tokens)
    errors = []
    for model in models():
        if model in _spent:
            continue
        for attempt in range(3):
            wait = _last.get(model, 0) + MIN_GAP - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            _last[model] = time.monotonic()
            try:
                r = requests.post(f"{API}/{model}:generateContent", headers={"x-goog-api-key": key()}, json=body,
                                  timeout=(20, READ_TIMEOUT))
            except requests.Timeout:
                log.info("%s timed out after %.0f s; next model for the rest of this run", model,
                         time.monotonic() - _last[model])
                _spent.add(model)
                errors.append(f"{model}: timeout")
                break
            except requests.RequestException as exc:
                errors.append(f"{model}: {type(exc).__name__}")
                time.sleep(5)
                continue
            log.info("%s: HTTP %s in %.0f s", model, r.status_code, time.monotonic() - _last[model])
            if r.status_code == 200:
                data = r.json()
                cand = (data.get("candidates") or [{}])[0]
                text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []) if not p.get("thought"))
                if not text.strip():
                    errors.append(f"{model}: empty answer ({cand.get('finishReason')})")
                    break  # a refusal or a safety stop: another model may answer
                if not schema:
                    return text, model
                try:
                    answer = _json(text)
                except (json.JSONDecodeError, ValueError):
                    errors.append(f"{model}: malformed JSON")
                    continue
                if isinstance(answer, dict) and all(k in answer for k in schema.get("required", [])):
                    return answer, model
                errors.append(f"{model}: JSON missing required fields")
                continue
            try:
                error = r.json().get("error", {})
            except ValueError:
                error = {}
            if r.status_code == 429:
                delay = _delay(error)
                if _daily(error) or attempt == 2 or (delay is not None and delay > MAX_WAIT):
                    log.info("%s is out of free quota for now; next model", model)
                    _spent.add(model)
                    errors.append(f"{model}: 429")
                    break
                time.sleep((delay if delay is not None else 20.0) + 1)
                continue
            if r.status_code in (401, 403):
                _refused = True
                raise Unavailable(f"Gemini refused the key (HTTP {r.status_code})")
            if r.status_code in (400, 404):
                if "API key" in str(error.get("message", "")):
                    _refused = True
                    raise Unavailable("Gemini refused the key")
                _spent.add(model)  # this model does not exist for the key, or rejects this request shape
                errors.append(f"{model}: HTTP {r.status_code}")
                break
            errors.append(f"{model}: HTTP {r.status_code}")
            time.sleep(8 * (attempt + 1))
    raise Unavailable("no Gemini model answered: " + "; ".join(errors[-6:]))
