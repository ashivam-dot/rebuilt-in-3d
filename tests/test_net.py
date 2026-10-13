import requests

from studio import net


def _err(status, headers=None):
    resp = requests.Response()
    resp.status_code, resp.headers = status, requests.structures.CaseInsensitiveDict(headers or {})
    return requests.HTTPError(f"HTTP {status}", response=resp)


def test_rate_limits_wait_longer_than_other_failures():
    assert net.pause(_err(503), 0) == 2 and net.pause(requests.ConnectionError(), 1) == 8
    assert net.pause(_err(429), 0) == 15 and net.pause(_err(429), 2) == 45
    assert net.pause(_err(429, {"Retry-After": "40"}), 0) == 40
    assert net.pause(_err(429, {"Retry-After": "600"}), 0) == 60
    assert net.pause(_err(429, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}), 0) == 15
