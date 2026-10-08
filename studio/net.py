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


def get(url: str, *, params: dict | None = None, cache: Path | None = None, timeout: float = 45, tries: int = 4) -> bytes:
    key = None
    if cache is not None:
        key = cache / hashlib.sha1((url + json.dumps(params or {}, sort_keys=True)).encode()).hexdigest()
        if key.exists():
            return key.read_bytes()
    for attempt in range(tries):
        try:
            resp = _session.get(url, params=params, timeout=timeout)
            if resp.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
            resp.raise_for_status()
            if key is not None:
                key.parent.mkdir(parents=True, exist_ok=True)
                key.write_bytes(resp.content)
            return resp.content
        except requests.RequestException:
            if attempt == tries - 1:
                raise
            time.sleep(2 * (attempt + 1) ** 2)
    raise AssertionError("unreachable")


def get_json(url: str, **kwargs):
    return json.loads(get(url, **kwargs))
