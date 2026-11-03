"""Offline check of the run loop's scheduling: slots, breaking news, the gap between posts. No network."""

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desk import publish, run, scouts, state, youtube  # noqa: E402

tmp = Path(tempfile.mkdtemp())
run.SHORTS, run.PLAN = tmp / "shorts.json", tmp / "plan.json"
youtube.PAUSE = tmp / "youtube.json"
posted, booked, buffer_status = [], [], {}
IST = run.IST
real_publish_post = publish.post


def fake_post(url: str, meta: dict, due=None) -> dict:
    if due:
        booked.append((meta["id"], due.astimezone(IST).strftime("%d %H:%M")))
    else:
        posted.append(meta["id"])
    return {"youtube": {"id": "p-" + meta["id"], "status": "scheduled" if due else "sent"}}


publish.post = fake_post
publish.status = lambda post_id: buffer_status.get(post_id, {"status": "scheduled"})


def at(day: int, hm: str) -> datetime:
    return datetime(2026, 10, day, *map(int, hm.split(":")), tzinfo=IST)


def board(published: datetime, heat: float = 88, also=("hacker", "techmeme", "openrouter")) -> list[dict]:
    return [{"key": "hf:acme/rocket-9", "url": "https://huggingface.co/acme/rocket-9", "title": "acme/Rocket-9",
             "summary": "", "kind": "model", "heat": heat, "also_on": list(also), "published": state.iso(published),
             "signals": {}, "source": "hf-models", "label": "HF", "entity": "hf:acme/rocket-9"}]


def short(sid: str, made: datetime, **kw) -> dict:
    return {"id": sid, "made_at": state.iso(made), "status": "ready", "video": "https://x/v.mp4", "title": sid,
            "story": sid, "keys": [], **kw}


def check(name: str, got, want) -> None:
    print(("ok  " if got == want else "FAIL") + f" {name}: {got!r}" + ("" if got == want else f" (want {want!r})"))


os.environ.pop("AI_BUFFER_API_KEY", None)
os.environ.pop("AI_YOUTUBE_TOKEN", None)
state.now = lambda: at(18, "02:30")
check("3.5 h before the slot: not yet", run.plan(), (False, "", False))
state.now = lambda: at(18, "03:30")
check("no Buffer: makes for the 06:00 slot", run.plan(), (True, "", False))

os.environ["AI_BUFFER_API_KEY"], os.environ["AI_BUFFER_YOUTUBE_ID"] = "fake", "fake"
scouts.scan = lambda *a, **k: board(at(18, "01:00"))
state.now = lambda: at(18, "02:30")
check("hot fresh multi-source story: breaking", run.plan(), (True, "https://huggingface.co/acme/rocket-9", True))
check("rescan within 55 min: no second scan", run.breaking(at(18, "03:00")), None)

run.save_shorts([short("b1", at(18, "02:50"), breaking=True)])
state.now = lambda: at(18, "03:00")
run.plan()
check("breaking Short posts at once", posted, ["b1"])

run.save_shorts([short("b1", at(18, "02:50"), breaking=True, status="posted", posted_at=state.iso(at(18, "03:00"))),
                 short("b2", at(18, "03:10"), breaking=True)])
state.now = lambda: at(18, "03:40")
posted.clear()
run.post_due(at(18, "03:40"))
check("second breaking waits for the 90-minute gap", posted, [])
run.post_due(at(18, "04:40"))
check("after the gap it goes", posted, ["b2"])

run.save_shorts([short("s1", at(18, "03:30"))])
posted.clear()
run.post_due(at(18, "06:10"))
check("slot Short posts in the 06:00 slot", posted, ["s1"])
check("slot recorded", run.shorts()[0].get("slot"), "2026-10-18 06:00")
buffer_status["p-s1"] = {"status": "sent", "sentAt": state.iso(at(18, "06:11")), "externalLink": "https://yt/s1"}
run.post_due(at(18, "06:20"))
got = run.shorts()[0]
check("a shared post is read back as posted", (got["status"], got["posted_at"], got["posted"]["youtube"].get("link")),
      ("posted", state.iso(at(18, "06:11")), "https://yt/s1"))

run.save_shorts([short("old", at(17, "03:00"))])
posted.clear()
run.post_due(at(18, "06:10"))
check("a Short older than 16 h goes stale", (posted, run.shorts()[0]["status"]), ([], "stale"))

run.save_shorts([short("b0", at(18, "01:00"), breaking=True, status="posted", posted_at=state.iso(at(18, "01:10")))])
run.PLAN.write_text("{}")
scouts.scan = lambda *a, **k: board(at(18, "05:00"))
check("one breaking Short a day", run.breaking(at(18, "07:00")), None)

run.save_shorts([])
run.PLAN.write_text("{}")
scouts.scan = lambda *a, **k: board(at(17, "12:00"))
check("too old for breaking", run.breaking(at(18, "07:00")), None)
run.PLAN.write_text("{}")
scouts.scan = lambda *a, **k: board(at(18, "05:00"), also=("hacker",))
check("one other source is not enough", run.breaking(at(18, "07:00")), None)

scouts.scan = lambda *a, **k: []
run.save_shorts([short("s2", at(18, "03:30"))])
posted.clear()
run.post_due(at(18, "03:45"))
check("a ready Short is booked into Buffer for its slot", (posted, booked), ([], [("s2", "18 06:00")]))
check("booked: scheduled for 06:00", (run.shorts()[0]["status"], run.shorts()[0]["slot"]),
      ("scheduled", "2026-10-18 06:00"))
state.now = lambda: at(18, "04:00")
check("no second Short for a booked slot", run.plan(), (False, "", False))
state.now = lambda: at(19, "17:30")
run.save_shorts([short("s2", at(18, "03:30"), status="posted", slot="2026-10-18 06:00"),
                 short("e1", at(19, "05:00"), status="scheduled", slot="2026-10-19 06:00")])
check("the next open slot is the one to make for", run.plan(), (True, "", False))

run.save_shorts([short("s2", at(18, "03:30"), status="scheduled", slot="2026-10-18 06:00",
                       due_at=state.iso(at(18, "06:00")), posted={"youtube": {"id": "p-s2"}})])
run.post_due(at(18, "06:03"))
check("not read back before it is due plus 5 minutes", run.shorts()[0]["status"], "scheduled")
buffer_status["p-s2"] = {"status": "sent", "sentAt": state.iso(at(18, "06:00")), "externalLink": "https://yt/s2"}
posted.clear()
run.post_due(at(18, "06:10"))
got = run.shorts()[0]
check("read back as posted, nothing shared again", (got["status"], got["posted_at"], posted),
      ("posted", state.iso(at(18, "06:00")), []))

run.save_shorts([short("s3", at(18, "03:30"), status="scheduled", slot="2026-10-18 06:00",
                       due_at=state.iso(at(18, "06:00")), posted={"youtube": {"id": "p-s3"}})])
buffer_status["p-s3"] = {"status": "error", "error": {"message": "upload failed"}}
posted.clear()
booked.clear()
run.post_due(at(18, "06:10"))
got = run.shorts()[0]
check("a failed booked post is shared once in its slot", (posted, booked, got["status"], got["slot"]),
      (["s3"], [], "scheduled", "2026-10-18 06:00"))
posted.clear()
run.post_due(at(18, "06:20"))
got = run.shorts()[0]
check("failing again, it is post-failed and not shared a third time", (posted, booked, got["status"]),
      ([], [], "post-failed"))

run.save_shorts([short("s4", at(18, "03:30"), status="scheduled", slot="2026-10-18 06:00",
                       due_at=state.iso(at(18, "06:00")), posted={"youtube": {"id": "p-s4"}}),
                 short("b3", at(18, "05:00"), breaking=True)])
posted.clear()
run.post_due(at(18, "05:10"))
check("breaking news keeps 90 minutes from a booked post", posted, [])
run.post_due(at(18, "07:40"))
check("and goes once the gap has passed", posted, ["b3"])

run.save_shorts([short("s5", at(18, "05:00"), status="scheduled", slot="2026-10-18 13:00"),
                 short("s7", at(18, "05:10"), status="scheduled", slot="2026-10-18 20:00"),
                 short("s6", at(18, "06:30"))])
booked.clear()
posted.clear()
run.post_due(at(18, "07:30"))
check("no booking past 16 h after it was made", (booked, posted, run.shorts()[2]["status"]), ([], [], "ready"))

run.save_shorts([short("s8", at(18, "03:30"), status="posted", slot="2026-10-18 06:00")])
state.now = lambda: at(18, "09:30")
check("3.5 h before the 13:00 slot: not yet", run.plan(), (False, "", False))
state.now = lambda: at(18, "10:05")
check("makes for the 13:00 slot", run.plan(), (True, "", False))
run.save_shorts([short("s8", at(18, "03:30"), status="posted", slot="2026-10-18 06:00"), short("s9", at(18, "10:20"))])
booked.clear()
run.post_due(at(18, "10:25"))
check("and books it for 13:00", booked, [("s9", "18 13:00")])

from desk import writer  # noqa: E402

def script(say: str, headline: str, title: str) -> dict:
    return {"title": title, "scenes": [{"type": "hook", "say": say, "headline": headline}]}

repo = {"platform": "github", "repo": "VoiceStudio", "name": "debpalash/VoiceStudio"}
check("a hook and title naming the repo pass", writer._name_missing(
    script("Voice Studio clones any voice from ten seconds of audio.", "VOICESTUDIO CLONES VOICES", "VoiceStudio: free voice cloning"),
    repo), [])
check("a hook that only says 'voice' is sent back", writer._name_missing(
    script("This free tool clones your voice in ten seconds.", "CLONE ANY VOICE", "VoiceStudio: free voice cloning"), repo),
    ["name VoiceStudio in scene 1's say", "name VoiceStudio in scene 1's headline"])
check("a model's name as spoken passes", writer._name_missing(
    script("Qwen three point eight now runs on a laptop.", "QWEN 3.8 ON A LAPTOP", "Qwen3.8 runs on a laptop"),
    {"platform": "huggingface", "repo": "Qwen3.8-Instruct"}), [])
check("papers and web pages are not checked", writer._name_missing(
    script("A new paper halves training cost.", "HALF THE COST", "Training at half the cost"),
    {"platform": "paper", "name": "Some long paper title"}), [])


class FakeResp:
    def __init__(self, code: int, body: dict, headers: dict | None = None):
        self.status_code, self._body, self.headers = code, body, headers or {}

    def json(self) -> dict:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


calls, answers = [], []
real_post, real_status, real_problems = publish.requests.post, publish.status, publish.channel_problems
publish.requests.post = lambda *a, **k: (calls.append(1), answers.pop(0))[1]
publish.LIMIT = tmp / "buffer.json"
state.now = lambda: at(20, "06:10")
answers.append(FakeResp(429, {"errors": [{"extensions": {"window": "30d"}}]}, {"Retry-After": "1190757"}))
try:
    publish._buffer(publish.CHANNEL)
    got = "no error"
except publish.Blocked as err:
    got = err.until == at(20, "06:10") + timedelta(seconds=1190757)
check("a 30-day refusal raises Blocked at once, with its end", (got, len(calls)), (True, 1))
state.now = lambda: at(20, "09:00")
try:
    publish._buffer(publish.CHANNEL)
except publish.Blocked:
    pass
check("while it lasts, Buffer isn't asked again within 6 hours", len(calls), 1)
state.now = lambda: at(20, "12:20")
answers.append(FakeResp(200, {"data": {"channel": {"name": "AI Shortcut"}}}))
check("after 6 hours one request goes out, and an answer ends the refusal",
      (publish._buffer(publish.CHANNEL), len(calls), publish.blocked(), state.load(publish.LIMIT, None)),
      ({"channel": {"name": "AI Shortcut"}}, 2, None, {}))


def refused(*args):
    raise publish.Blocked("Buffer's 30d API limit is used up", at(30, "00:00"))


def down(*args):
    raise RuntimeError("Buffer: 502")


publish.status = refused
run.save_shorts([short("s10", at(20, "03:30"), status="scheduled", slot="2026-10-20 06:00",
                       due_at=state.iso(at(20, "06:00")), posted={"youtube": {"id": "p-s10"}})])
run.post_due(at(20, "10:00"))
check("a post the limit keeps from being read isn't given up on", run.shorts()[0]["status"], "scheduled")
publish.status = down
run.post_due(at(20, "10:00"))
check("other read errors still give up after 3 hours", run.shorts()[0]["status"], "post-failed")
publish.status = real_status

out = tmp / "github_output"
os.environ["GITHUB_OUTPUT"] = str(out)
scouts.scan = lambda *a, **k: []
run.save_shorts([short("s11", at(20, "03:30"), status="posted", slot="2026-10-20 06:00")])
run.PLAN.write_text("{}")
state.now = lambda: at(20, "10:05")
publish.channel_problems = refused
out.write_text("")
code = run.main(["plan"])
check("Buffer refusing: no make, and the run passes", (code, out.read_text().splitlines()[0]), (0, "make=false"))
checked = []
publish.channel_problems = lambda: checked.append(1) or []
out.write_text("")
code = run.main(["plan"])
check("Buffer taking posts: makes for the 13:00 slot", (code, out.read_text().splitlines()[0], checked),
      (0, "make=true", [1]))
checked.clear()
state.now = lambda: at(20, "08:00")
out.write_text("")
run.main(["plan"])
check("no make, no channel check", (out.read_text().splitlines()[0], checked), ("make=false", []))
publish.requests.post, publish.channel_problems = real_post, real_problems

# Direct YouTube uploads through the desk's own API project, with Buffer as the fallback.
real_upload, real_yt_status, real_find, real_send, real_api = (youtube.upload, youtube.status, youtube.find,
                                                               youtube._send, youtube._api)
real_buffer = publish._buffer
os.environ["AI_YOUTUBE_TOKEN"] = "{}"
publish.post = real_publish_post
uploaded, refuse_upload, yt_status, yt_titles, buffer_calls = [], [], {}, {}, []


def fake_upload(video_url, title, description, keywords, due=None, local=None):
    if refuse_upload:
        raise youtube.YouTubeError(refuse_upload[0])
    uploaded.append((title, due.astimezone(IST).strftime("%d %H:%M") if due else "now"))
    return {"id": "yt-" + title, "status": "scheduled" if due else "sent", "link": "https://yt/" + title,
            "via": "youtube"}


def buffer_refusing(*args):
    buffer_calls.append(1)
    raise publish.Blocked("Buffer's 30d API limit is used up", at(30, "00:00"))


def dshort(sid: str, made: datetime, **kw) -> dict:
    return short(sid, made, description=f"About {sid}", source="https://example.com", **kw)


youtube.upload, youtube.find = fake_upload, lambda title: yt_titles.get(title)
youtube.status = lambda vid: yt_status.get(vid, {"status": "scheduled"})
publish._buffer = buffer_refusing

run.save_shorts([dshort("d1", at(21, "03:30"))])
run.post_due(at(21, "03:45"))
got = run.shorts()[0]
check("direct: a ready Short is uploaded for its slot, Buffer not asked",
      (uploaded, got["status"], got["slot"], got["posted"]["youtube"].get("via"), buffer_calls),
      ([("d1", "21 06:00")], "scheduled", "2026-10-21 06:00", "youtube", []))
yt_status["yt-d1"] = {"status": "sent", "sentAt": state.iso(at(21, "06:00")), "externalLink": "https://yt/d1"}
run.post_due(at(21, "06:10"))
got = run.shorts()[0]
check("direct: read back from YouTube as posted", (got["status"], got["posted_at"], got["posted"]["youtube"]["link"]),
      ("posted", state.iso(at(21, "06:00")), "https://yt/d1"))

refuse_upload.append("YouTube 400 invalidTitle: bad title")
run.save_shorts([dshort("d2", at(21, "10:20"))])
run.post_due(at(21, "10:25"))
got = run.shorts()[0]
check("direct upload refused: Buffer is tried, and refusing too, the Short stays ready",
      (got["status"], got.get("book_tries"), len(buffer_calls)), ("ready", 1, 1))
refuse_upload.clear()
buffer_calls.clear()

run.save_shorts([dshort("h1", at(21, "03:20"), status="scheduled", slot="2026-10-21 06:00",
                        due_at=state.iso(at(21, "06:00")), posted={"youtube": {"id": "buf-h1", "status": "scheduled"}})])
yt_titles["h1"] = "yt-h1"
yt_status["yt-h1"] = {"status": "sent", "sentAt": state.iso(at(21, "06:00")), "externalLink": "https://yt/h1"}
publish.status = refused
run.post_due(at(21, "07:00"))
got = run.shorts()[0]
check("a Buffer post Buffer won't be asked about is found on YouTube by its title",
      (got["status"], got["posted"]["youtube"].get("link")), ("posted", "https://yt/h1"))
publish.status = real_status

os.environ["GITHUB_OUTPUT"] = str(out)
run.save_shorts([dshort("d0", at(21, "03:30"), status="posted", slot="2026-10-21 06:00")])
run.PLAN.write_text("{}")
state.now = lambda: at(21, "10:05")
out.write_text("")
code = run.main(["plan"])
check("Buffer refusing, YouTube direct: makes for the 13:00 slot, Buffer not asked",
      (code, out.read_text().splitlines()[0], buffer_calls), (0, "make=true", []))
state.save(youtube.PAUSE, {"until": state.iso(at(22, "12:35")), "reason": "YouTube's daily API quota is used up"})
out.write_text("")
code = run.main(["plan"])
check("YouTube's quota used up and Buffer refusing: no make", (code, out.read_text().splitlines()[0]),
      (0, "make=false"))
os.environ.pop("AI_BUFFER_API_KEY")
out.write_text("")
code = run.main(["plan"])
check("YouTube's quota used up and no Buffer: no make", (code, out.read_text().splitlines()[0]), (0, "make=false"))
os.environ["AI_BUFFER_API_KEY"] = "fake"
os.environ.pop("GITHUB_OUTPUT")
state.save(youtube.PAUSE, {})
publish._buffer = real_buffer

state.now = lambda: at(21, "12:00")
try:
    youtube._check(FakeResp(403, {"error": {"errors": [{"reason": "quotaExceeded"}], "message": "quota"}}))
    got = "no error"
except youtube.Paused as err:
    got = err.until
check("quotaExceeded pauses YouTube until 00:05 Pacific", (got, youtube.ready()), (at(21, "12:35"), False))
state.now = lambda: at(21, "12:40")
check("and the pause ends then", youtube.ready(), True)
try:
    youtube._check(FakeResp(400, {"error": {"errors": [{"reason": "invalidTitle"}], "message": "bad"}}))
except youtube.Paused:
    got = "paused"
except youtube.YouTubeError:
    got = "error"
check("other refusals don't pause", (got, youtube.ready()), ("error", True))


def video(status: dict, snippet: dict | None = None):
    youtube._api = lambda path, params: {"items": [{"status": status, "snippet": snippet or {}}]}
    return real_yt_status("v1")["status"]


state.now = lambda: at(21, "13:20")
check("private, 20 minutes after its publishAt: still scheduled",
      video({"uploadStatus": "processed", "privacyStatus": "private", "publishAt": state.iso(at(21, "13:00"))}),
      "scheduled")
state.now = lambda: at(21, "13:40")
check("private, 40 minutes after its publishAt: an error",
      video({"uploadStatus": "processed", "privacyStatus": "private", "publishAt": state.iso(at(21, "13:00"))}),
      "error")
check("a rejected upload is an error", video({"uploadStatus": "rejected", "rejectionReason": "duplicate"}), "error")
check("public: sent", video({"uploadStatus": "processed", "privacyStatus": "public"}), "sent")
youtube._api = lambda path, params: {"items": []}
check("a video YouTube no longer has is an error", real_yt_status("v1")["status"], "error")

state.save(youtube.PAUSE, {})
bodies = []
youtube._send = lambda body, data: (bodies.append(body), {"id": "new1"})[1]
youtube.find = lambda title: None
clip = tmp / "v.mp4"
clip.write_bytes(b"mp4")
state.now = lambda: at(21, "10:30")
got = real_upload("https://x/v.mp4", "Rocket <9> ships", "About <b>it</b>", ["AI", "#Shorts", "#AI", "open source"],
                  at(21, "13:00"), clip)
body = bodies[0]
check("a slot upload goes private with publishAt at the slot",
      (body["status"]["privacyStatus"], body["status"].get("publishAt"), got["status"], got["id"]),
      ("private", "2026-10-21T07:30:00Z", "scheduled", "new1"))
check("title, description and tags are cleaned",
      (body["snippet"]["title"], body["snippet"]["description"], body["snippet"]["tags"], body["snippet"]["categoryId"]),
      ("Rocket 9 ships", "About bit/b", ["AI", "Shorts", "open source"], "28"))
bodies.clear()
got = real_upload("https://x/v.mp4", "Rocket ships", "About", [], at(21, "10:40"), clip)
check("due within 15 minutes: public at once", (bodies[0]["status"]["privacyStatus"], "publishAt" in bodies[0]["status"],
                                                 got["status"]), ("public", False, "sent"))
bodies.clear()
youtube.find = lambda title: "old1"
youtube.status = lambda vid: {"status": "scheduled", "externalLink": "https://yt/old1"}
got = real_upload("https://x/v.mp4", "Rocket ships", "About", [], at(21, "13:00"), clip)
check("already on the channel: not uploaded again", (bodies, got["id"], got["link"]), ([], "old1", "https://yt/old1"))
youtube.status = lambda vid: {"status": "error", "error": {"message": "rejected"}}
got = real_upload("https://x/v.mp4", "Rocket ships", "About", [], at(21, "13:00"), clip)
check("a broken earlier upload is uploaded anew", (len(bodies), got["id"]), (1, "new1"))
youtube.upload, youtube.status, youtube.find, youtube._send, youtube._api = (real_upload, real_yt_status, real_find,
                                                                             real_send, real_api)
os.environ.pop("AI_YOUTUBE_TOKEN")
