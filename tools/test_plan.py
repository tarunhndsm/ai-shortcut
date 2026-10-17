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
posted = []
publish.post = lambda url, meta: posted.append(meta["id"]) or {"youtube": {"id": "p-" + meta["id"]}}
IST = run.IST


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
