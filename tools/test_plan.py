"""Offline check of the run loop's scheduling: slots, breaking news, the gap between posts. No network."""

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desk import publish, run, scouts, state  # noqa: E402

tmp = Path(tempfile.mkdtemp())
run.SHORTS, run.PLAN = tmp / "shorts.json", tmp / "plan.json"
posted, booked, buffer_status = [], [], {}
IST = run.IST


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

run.save_shorts([short("s5", at(18, "05:00"), status="scheduled", slot="2026-10-18 20:00"),
                 short("s6", at(18, "06:30"))])
booked.clear()
posted.clear()
run.post_due(at(18, "07:30"))
check("no booking past 16 h after it was made", (booked, posted, run.shorts()[1]["status"]), ([], [], "ready"))
