"""HTTP for every adapter: one request at a time per host, at least 1 second apart.

Different hosts may run in parallel (one thread per jurisdiction). Every
request sends a browser User-Agent; any HTTP error raises. No retries: a
failed run is re-run, and the archive skips what it already holds.
"""
from __future__ import annotations

import threading
import time
from urllib.parse import urlsplit

import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
MIN_INTERVAL = 1.0
TIMEOUT = 120

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})
_hosts: dict[str, tuple[threading.Lock, list[float]]] = {}
_hosts_lock = threading.Lock()


def _host_slot(url: str) -> tuple[threading.Lock, list[float]]:
    host = urlsplit(url).hostname or ""
    with _hosts_lock:
        if host not in _hosts:
            _hosts[host] = (threading.Lock(), [0.0])
        return _hosts[host]


def request(method: str, url: str, **kwargs) -> requests.Response:
    lock, last = _host_slot(url)
    with lock:
        wait = last[0] + MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            response = _session.request(method, url, timeout=TIMEOUT, **kwargs)
        finally:
            last[0] = time.monotonic()
    response.raise_for_status()
    return response


def get(url: str, **kwargs) -> requests.Response:
    return request("GET", url, **kwargs)


def post(url: str, **kwargs) -> requests.Response:
    return request("POST", url, **kwargs)


def head(url: str, **kwargs) -> requests.Response:
    return request("HEAD", url, allow_redirects=True, **kwargs)
