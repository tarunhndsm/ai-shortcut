"""HTTP for the desk's agents: one session, a browser-like agent, a retry on rate limits and server errors."""

from __future__ import annotations

import logging
import os
import time

import requests

log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"
_session = requests.Session()


def get(url: str, *, params: dict | None = None, headers: dict | None = None, timeout: float = 25,
        tries: int = 2) -> requests.Response:
    error: Exception | None = None
    for attempt in range(tries):
        try:
            resp = _session.get(url, params=params, headers={"User-Agent": UA, **(headers or {})}, timeout=timeout)
        except requests.RequestException as exc:
            error = exc
            time.sleep(2 * (attempt + 1))
            continue
        if resp.status_code in (429, 500, 502, 503, 504) and attempt + 1 < tries:
            time.sleep(4 * (attempt + 1))
            continue
        resp.raise_for_status()
        return resp
    raise error or RuntimeError(f"GET {url} failed")


def json_get(url: str, **kw):
    return get(url, **kw).json()


def text_get(url: str, **kw) -> str:
    return get(url, **kw).text


def github_headers(raw: bool = False) -> dict:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    headers = {"Accept": "application/vnd.github.raw+json" if raw else "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers
