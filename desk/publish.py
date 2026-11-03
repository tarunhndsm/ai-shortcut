"""Publishing: the MP4 goes to a GitHub release of this public repo (a stable public URL), and Buffer posts it to the
channel's YouTube, and to its Instagram and Facebook Page when those are connected. Buffer's YouTube client is
Google-audited, so its uploads are public; this repo never uploads through the YouTube API itself."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from . import env, state

log = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
# Buffer allows this key 150 requests in 15 minutes, 600 in a day and 1,000 in a rolling 30 days (its rate-limit
# headers, 3 Nov 2026). A refusal longer than 15 minutes is kept in LIMIT, and until it ends Buffer is asked again only
# once every PROBE_EVERY, so a raised limit is noticed. A refused request costs no quota.
LIMIT = env.STATE / "buffer.json"
PROBE_EVERY = timedelta(hours=6)

BUFFER = "https://api.buffer.com"
RELEASE = "media"
CATEGORY = "28"  # Science & Technology
CREATE = """mutation Create($input: CreatePostInput!) { createPost(input: $input) { __typename
  ... on PostActionSuccess { post { id status externalLink } } ... on MutationError { message } } }"""
STATUS = "query Post($input: PostInput!) { post(input: $input) { id status sentAt externalLink error { message } } }"
CHANNEL = "query Channel($input: ChannelInput!) { channel(input: $input) { name isDisconnected isLocked isQueuePaused } }"


def _gh(method: str, url: str, **kw) -> requests.Response:
    headers = {"Authorization": f"Bearer {env.need('GITHUB_TOKEN')}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28", **kw.pop("headers", {})}
    return requests.request(method, url, headers=headers, timeout=kw.pop("timeout", 120), **kw)


def host(path: Path, name: str, kind: str = "video/mp4") -> str:
    """Upload a file to the repo's "media" release; its public download URL."""
    repo = env.need("GITHUB_REPOSITORY")
    resp = _gh("GET", f"https://api.github.com/repos/{repo}/releases/tags/{RELEASE}")
    if resp.status_code == 404:
        resp = _gh("POST", f"https://api.github.com/repos/{repo}/releases",
                   json={"tag_name": RELEASE, "name": "Rendered Shorts", "prerelease": True,
                         "body": "Every Short the desk renders, kept for Buffer to fetch and for the record."})
    resp.raise_for_status()
    release = resp.json()
    for asset in release.get("assets", []):
        if asset["name"] == name:
            _gh("DELETE", asset["url"]).raise_for_status()
    with path.open("rb") as fh:
        up = _gh("POST", f"https://uploads.github.com/repos/{repo}/releases/{release['id']}/assets",
                 params={"name": name}, headers={"Content-Type": kind}, data=fh, timeout=600)
    up.raise_for_status()
    return up.json()["browser_download_url"]


class Blocked(RuntimeError):
    """Buffer refuses this key's requests until `until`."""

    def __init__(self, message: str, until: datetime):
        super().__init__(message)
        self.until = until


def blocked() -> Blocked | None:
    """Buffer's standing refusal, unless it has run out or is due another try."""
    held = state.load(LIMIT, {})
    until, probed, now = state.parse(held.get("until")), state.parse(held.get("probed")), state.now()
    if until and probed and now < until and now - probed < PROBE_EVERY:
        return Blocked(held.get("reason") or "Buffer's API limit is used up", until)
    return None


def _refusal(resp: requests.Response) -> tuple[float, str]:
    """Seconds until Buffer takes requests again, and the window of the limit that was hit ("15m", "24h", "30d")."""
    try:
        wait = float(resp.headers.get("Retry-After") or 0)
    except ValueError:
        wait = 0.0
    try:
        window = resp.json()["errors"][0]["extensions"]["window"]
    except (ValueError, KeyError, IndexError, TypeError):
        window = "?"
    return wait, window


def _buffer(query: str, variables: dict | None = None) -> dict:
    if refused := blocked():
        raise refused
    for attempt in range(3):
        resp = requests.post(BUFFER, json={"query": query, "variables": variables or {}}, timeout=120,
                             headers={"Authorization": f"Bearer {env.need('AI_BUFFER_API_KEY')}"})
        if resp.status_code == 429:
            wait, window = _refusal(resp)
            if wait > 900:
                now = state.now()
                until = now + timedelta(seconds=wait)
                reason = f"Buffer's {window} API limit is used up until {until.astimezone(IST):%d %b %H:%M} IST"
                state.save(LIMIT, {"until": state.iso(until), "probed": state.iso(now), "window": window,
                                   "reason": reason})
                raise Blocked(reason, until)
            if attempt < 2:
                time.sleep(30 * (attempt + 1))
                continue
        resp.raise_for_status()
        data = resp.json()
        if data.get("errors"):
            raise RuntimeError(f"Buffer: {data['errors'][0].get('message')}")
        if state.load(LIMIT, {}):
            state.save(LIMIT, {})
        return data["data"]
    raise RuntimeError("Buffer kept rate-limiting")


def configured() -> bool:
    return bool(os.environ.get("AI_BUFFER_API_KEY") and os.environ.get("AI_BUFFER_YOUTUBE_ID"))


def channels() -> dict[str, str]:
    """Connected channels by service: YouTube always; Instagram and Facebook once their ids are set."""
    out = {"youtube": env.need("AI_BUFFER_YOUTUBE_ID")}
    for service in ("instagram", "facebook"):
        if os.environ.get(f"AI_BUFFER_{service.upper()}_ID"):
            out[service] = os.environ[f"AI_BUFFER_{service.upper()}_ID"]
    return out


def _caption(meta: dict, service: str) -> str:
    tags = " ".join(meta.get("hashtags", [])[:3])
    if service == "youtube":
        return f"{meta['description']}\n\nSource: {meta['source']}\n\n{meta['disclosure']}\n\n{tags}"[:4900]
    return f"{meta['title']}\n\n{meta['description']}\n\nSource: {meta['source']}\n{meta['disclosure']}\n\n{tags}"[:2100]


def post(video_url: str, meta: dict, due: datetime | None = None) -> dict:
    """Share now on every connected channel, or have Buffer post it at `due`: {service: {"id", "status", "error"}}."""
    results = {}
    for service, channel in channels().items():
        payload = {"channelId": channel, "text": _caption(meta, service), "schedulingType": "automatic",
                   "mode": "shareNow", "assets": [{"video": {"url": video_url}}]}
        if due:
            payload["mode"] = "customScheduled"
            payload["dueAt"] = due.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        if service == "youtube":
            payload["metadata"] = {"youtube": {"title": meta["title"][:100].replace("<", "").replace(">", ""),
                                               "categoryId": CATEGORY, "privacy": "public", "madeForKids": False,
                                               "notifySubscribers": True, "isAiGenerated": False, "embeddable": True}}
        elif service == "instagram":
            payload["metadata"] = {"instagram": {"type": "reel", "shouldShareToFeed": True, "isAiGenerated": False}}
        else:
            payload["metadata"] = {"facebook": {"type": "reel"}}
        try:
            got = _buffer(CREATE, {"input": payload})["createPost"]
            if got.get("__typename") == "PostActionSuccess":
                results[service] = {"id": got["post"]["id"], "status": got["post"]["status"]}
            else:
                results[service] = {"error": got.get("message", got.get("__typename"))}
        except Exception as exc:
            results[service] = {"error": str(exc)[:300]}
        log.info("buffer %s: %s", service, results[service])
    return results


def status(post_id: str) -> dict:
    return _buffer(STATUS, {"input": {"id": post_id}})["post"]


def channel_problems() -> list[str]:
    """Connected channels Buffer can't post to (disconnected, locked or queue paused). A failed check counts as none;
    a used-up API limit raises Blocked."""
    problems = []
    for service, channel in channels().items():
        try:
            got = _buffer(CHANNEL, {"input": {"id": channel}})["channel"] or {}
        except Blocked:
            raise
        except Exception as exc:
            log.warning("buffer channel check for %s: %s", service, exc)
            continue
        flags = [k for k in ("isDisconnected", "isLocked", "isQueuePaused") if got.get(k)]
        if flags:
            problems.append(f"{service} ({got.get('name')}): {', '.join(flags)}")
    return problems
