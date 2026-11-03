"""Direct uploads to the channel through the desk's own YouTube API project (ai-shortcut-desk), signed in as the
channel with AI_YOUTUBE_TOKEN (one line of JSON: client_id, client_secret, refresh_token, token_uri, scopes). A Short
for a slot is uploaded private with a publishAt time, so YouTube makes it public on time with no run needed then; one
due within SOONEST goes public at once. A used-up daily quota is kept in state/youtube.json until it resets.

python -m desk.youtube uploads [count]   the channel's latest uploads, with their privacy
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from . import env, state

log = logging.getLogger(__name__)

API = "https://www.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"
TOKEN_URI = "https://oauth2.googleapis.com/token"
UPLOADS = "UU" + env.CHANNEL["channel_id"][2:]
PAUSE = env.STATE / "youtube.json"
PACIFIC = ZoneInfo("America/Los_Angeles")  # YouTube's daily quota resets at midnight Pacific
SOONEST = timedelta(minutes=15)
HELD_PRIVATE = timedelta(minutes=30)
CATEGORY = "28"  # Science & Technology
DESCRIPTION_BYTES = 4900  # YouTube allows 5,000
TAG_CHARS = 450  # of YouTube's 500, counting a comma after each tag and quotes around one with a space
_access: dict = {}


class YouTubeError(RuntimeError):
    pass


class Paused(YouTubeError):
    """YouTube takes no more requests from the desk until `until`."""

    def __init__(self, message: str, until: datetime):
        super().__init__(message)
        self.until = until


def configured() -> bool:
    return bool(os.environ.get("AI_YOUTUBE_TOKEN", "").strip())


def blocked() -> Paused | None:
    """The standing pause (a used-up daily quota), until it ends."""
    held = state.load(PAUSE, {})
    until = state.parse(held.get("until"))
    if until and state.now() < until:
        return Paused(held.get("reason") or "YouTube's quota is used up", until)
    return None


def ready() -> bool:
    return configured() and not blocked()


def _pause(until: datetime, why: str) -> Paused:
    reason = f"{why} until {until.astimezone(timezone(timedelta(hours=5, minutes=30))):%d %b %H:%M} IST"
    state.save(PAUSE, {"until": state.iso(until), "reason": reason})
    log.warning("YouTube: %s", reason)
    return Paused(reason, until)


def _token() -> str:
    if _access.get("token") and _access["until"] > datetime.now(timezone.utc):
        return _access["token"]
    saved = json.loads(env.need("AI_YOUTUBE_TOKEN"))
    resp = requests.post(saved.get("token_uri") or TOKEN_URI, timeout=30,
                         data={"client_id": saved["client_id"], "client_secret": saved["client_secret"],
                               "refresh_token": saved["refresh_token"], "grant_type": "refresh_token"})
    if resp.status_code >= 400:
        try:
            why = resp.json().get("error_description") or resp.json().get("error")
        except ValueError:
            why = resp.text[:200]
        raise YouTubeError(f"YouTube sign-in refused ({resp.status_code}: {why}); sign the channel in again")
    body = resp.json()
    _access.update(token=body["access_token"],
                   until=datetime.now(timezone.utc) + timedelta(seconds=int(body.get("expires_in", 3600)) - 120))
    return _access["token"]


def _check(resp: requests.Response) -> None:
    """Raise YouTubeError for a refusal; a used-up quota also pauses uploads until it resets."""
    if resp.status_code < 400:
        return
    try:
        error = resp.json().get("error") or {}
        reason = ((error.get("errors") or [{}])[0].get("reason")) or error.get("status") or ""
        message = error.get("message") or ""
    except ValueError:
        reason, message = "", resp.text[:200]
    if reason in ("quotaExceeded", "uploadLimitExceeded"):
        reset = (state.now().astimezone(PACIFIC) + timedelta(days=1)).replace(hour=0, minute=5, second=0,
                                                                               microsecond=0)
        raise _pause(reset.astimezone(timezone.utc),
                     "YouTube's daily upload limit is reached" if reason == "uploadLimitExceeded"
                     else "YouTube's daily API quota is used up")
    if reason == "rateLimitExceeded":
        raise _pause(state.now() + timedelta(hours=1), "YouTube says the desk is uploading too fast")
    raise YouTubeError(f"YouTube {resp.status_code} {reason}: {message}"[:300])


def _api(path: str, params: dict) -> dict:
    if refused := blocked():
        raise refused
    resp = requests.get(f"{API}/{path}", params=params, headers={"Authorization": f"Bearer {_token()}"}, timeout=60)
    _check(resp)
    return resp.json()


def fit(text: str, limit: int = DESCRIPTION_BYTES) -> str:
    """`text` without < and > (YouTube refuses them), cut at a line to fit `limit` bytes."""
    text = text.replace("<", "").replace(">", "")
    if len(text.encode("utf-8")) <= limit:
        return text
    out, used = [], 0
    for line in text.split("\n"):
        cost = len(line.encode("utf-8")) + 1
        if used + cost > limit:
            break
        out.append(line)
        used += cost
    return "\n".join(out).rstrip()


def title_of(title: str) -> str:
    return re.sub(r"\s+", " ", title.replace("<", "").replace(">", "")).strip()[:100]


def tags(found: list[str], limit: int = TAG_CHARS) -> list[str]:
    """`found` without #, repeats or < > and commas, within YouTube's limit on tags."""
    out, used = [], 0
    for tag in dict.fromkeys(re.sub(r"[<>,#]", "", t).strip() for t in found):
        cost = len(tag) + 1 + (2 if " " in tag else 0)
        if not tag or used + cost > limit or tag.lower() in {o.lower() for o in out}:
            continue
        out.append(tag)
        used += cost
    return out


def uploads(count: int = 25) -> list[dict]:
    """The channel's latest uploads, newest first: {"id", "title", "privacy"} (1 quota unit)."""
    got = _api("playlistItems", {"part": "snippet,status", "playlistId": UPLOADS, "maxResults": count})
    return [{"id": i["snippet"]["resourceId"]["videoId"], "title": i["snippet"]["title"],
             "privacy": (i.get("status") or {}).get("privacyStatus")} for i in got.get("items", [])]


def find(title: str) -> str | None:
    """The id of a recent upload with this title, from any route (the desk, Buffer or by hand)."""
    want = title_of(title).casefold()
    return next((u["id"] for u in uploads() if title_of(u["title"]).casefold() == want), None)


def status(video_id: str) -> dict:
    """An upload read back like a Buffer post: "sent" once public, "error" if YouTube refused, lost or still holds
    it private well after its time, else "scheduled"; with sentAt and externalLink (1 quota unit)."""
    items = _api("videos", {"part": "status,snippet", "id": video_id}).get("items", [])
    link = f"https://www.youtube.com/shorts/{video_id}"
    if not items:
        return {"status": "error", "error": {"message": "YouTube no longer has the video"}, "externalLink": link}
    st, sn = items[0].get("status") or {}, items[0].get("snippet") or {}
    if st.get("uploadStatus") in ("rejected", "failed", "deleted"):
        why = st.get("rejectionReason") or st.get("failureReason") or st["uploadStatus"]
        return {"status": "error", "error": {"message": f"YouTube {st['uploadStatus']} the upload: {why}"},
                "externalLink": link}
    if st.get("privacyStatus") == "public":
        return {"status": "sent", "sentAt": sn.get("publishedAt"), "externalLink": link}
    due = state.parse(st.get("publishAt"))
    if st.get("privacyStatus") != "unlisted" and (not due or state.now() > due + HELD_PRIVATE):
        return {"status": "error", "externalLink": link,
                "error": {"message": f"still {st.get('privacyStatus')} after its time"}}
    return {"status": "scheduled", "externalLink": link}


def _send(body: dict, data: bytes) -> dict:
    """A resumable upload of `data` with the video resource `body`; resumes where YouTube stopped receiving."""
    size = len(data)
    init = requests.post(UPLOAD, params={"uploadType": "resumable", "part": "snippet,status", "notifySubscribers": "true"},
                         headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json; charset=UTF-8",
                                  "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)},
                         data=json.dumps(body), timeout=60)
    _check(init)
    session, start = init.headers["Location"], 0
    for attempt in range(4):
        headers = {"Authorization": f"Bearer {_token()}", "Content-Type": "video/mp4"}
        if start:
            headers["Content-Range"] = f"bytes {start}-{size - 1}/{size}"
        try:
            resp = requests.put(session, headers=headers, data=data[start:], timeout=900)
            if resp.status_code in (200, 201):
                return resp.json()
            if resp.status_code not in (308, 500, 502, 503, 504):
                _check(resp)
                raise YouTubeError(f"YouTube upload answered {resp.status_code}")
        except requests.RequestException as exc:
            log.warning("YouTube upload interrupted: %s", exc)
        time.sleep(5 * (attempt + 1))
        try:
            probe = requests.put(session, headers={"Authorization": f"Bearer {_token()}",
                                                   "Content-Range": f"bytes */{size}"}, timeout=60)
        except requests.RequestException as exc:
            log.warning("YouTube upload status: %s", exc)
            continue
        if probe.status_code in (200, 201):
            return probe.json()
        if probe.status_code != 308:
            _check(probe)
            continue
        got = re.search(r"-(\d+)$", probe.headers.get("Range", ""))
        start = int(got.group(1)) + 1 if got else 0
    raise YouTubeError("YouTube upload kept failing")


def upload(video_url: str, title: str, description: str, keywords: list[str], due: datetime | None = None,
           local: Path | None = None) -> dict:
    """Upload a Short (the local render if there is one, else from `video_url`), public at `due` or now:
    {"id", "status", "link", "via"}. An upload with the same title already on the channel is used instead."""
    if refused := blocked():
        raise refused
    title = title_of(title)
    if (found := find(title)) and (got := status(found))["status"] != "error":
        log.info("YouTube already has %r as %s; not uploading it again", title, found)
        return {"id": found, "status": got["status"], "via": "youtube",
                "link": got.get("externalLink") or f"https://www.youtube.com/shorts/{found}"}
    if local and local.is_file():
        data = local.read_bytes()
    else:
        resp = requests.get(video_url, timeout=300)
        resp.raise_for_status()
        data = resp.content
    st = {"privacyStatus": "public", "selfDeclaredMadeForKids": False, "embeddable": True,
          "publicStatsViewable": True, "containsSyntheticMedia": False}
    if due and due - state.now() > SOONEST:
        st |= {"privacyStatus": "private", "publishAt": due.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    body = {"snippet": {"title": title, "description": fit(description), "tags": tags(keywords),
                        "categoryId": CATEGORY, "defaultLanguage": "en", "defaultAudioLanguage": "en"},
            "status": st}
    video = _send(body, data)
    out = {"id": video["id"], "status": "scheduled" if st.get("publishAt") else "sent",
           "link": f"https://www.youtube.com/shorts/{video['id']}", "via": "youtube"}
    log.info("uploaded %r to YouTube as %s (%s)", title, video["id"], st.get("publishAt") or "public now")
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S")
    if sys.argv[1:2] == ["uploads"]:
        for u in uploads(int(sys.argv[2]) if len(sys.argv) > 2 else 10):
            print(u["id"], u["privacy"], u["title"])
    else:
        print(__doc__.strip().splitlines()[-1])
