"""Polite HTTP for open-data hosts: a contact User-Agent, retries with backoff, and an optional disk cache."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import requests

USER_AGENT = "rebuilt-in-3d/0.1 (+https://ashivam-dot.github.io/rebuilt-in-3d/; aksha.shivam18@gmail.com)"
_session = requests.Session()
_session.headers["User-Agent"] = USER_AGENT


def get(url: str, *, params: dict | None = None, cache: Path | None = None, timeout: float | tuple = 45, tries: int = 4,
        headers: dict | None = None) -> bytes:
    key = None
    if cache is not None:
        key = cache / hashlib.sha1((url + json.dumps(params or {}, sort_keys=True)).encode()).hexdigest()
        if key.exists():
            return key.read_bytes()
    for attempt in range(tries):
        try:
            resp = _session.get(url, params=params, timeout=timeout, headers=headers)
            if resp.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
            resp.raise_for_status()
            if key is not None:
                key.parent.mkdir(parents=True, exist_ok=True)
                key.write_bytes(resp.content)
            return resp.content
        except requests.RequestException as exc:
            if attempt == tries - 1:
                raise
            time.sleep(pause(exc, attempt))
    raise AssertionError("unreachable")


def pause(exc: Exception, attempt: int) -> float:
    """Seconds before the next try. A rate limit (HTTP 429) waits longer, as long as its Retry-After asks (at most a
    minute): the Wikidata query service's limit outlasts the short backoff."""
    resp = getattr(exc, "response", None)
    if resp is None or resp.status_code != 429:
        return 2 * (attempt + 1) ** 2
    try:
        asked = float(resp.headers.get("Retry-After") or 0)
    except ValueError:
        asked = 0
    return min(60.0, max(asked, 15.0 * (attempt + 1)))


def get_json(url: str, **kwargs):
    return json.loads(get(url, **kwargs))
