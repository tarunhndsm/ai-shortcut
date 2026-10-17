"""The desk's run loop.

python -m desk.run make [--url URL] [--dry]   make one Short now (optionally about URL); --dry keeps it local
python -m desk.run plan                       the scheduled cycle: post a ready Short when a slot is due, and say
                                              (make=true|false in GITHUB_OUTPUT) whether to make the next one now
python -m desk.run board                      print the scouts' board
python -m desk.run status                     what was made and posted
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import assets, compose, editor, env, publish, qa, render, research, scouts, sound, state, voice, writer

log = logging.getLogger("desk")

IST = timezone(timedelta(hours=5, minutes=30))
# Posting slots in India time: Indian mornings, lunch and evenings, and US mornings (19:30) and afternoons (23:30).
SLOTS = ("08:00", "13:00", "19:30", "23:30")
SLOT_GRACE = timedelta(minutes=75)
MAKE_AHEAD = timedelta(hours=3)
READY_MAX_AGE = timedelta(hours=16)
SHORTS = env.STATE / "shorts.json"
DISCLOSURE = "Researched, written and narrated with AI tools (Gemini), checked against the sources above."


def shorts() -> list[dict]:
    return state.load(SHORTS, [])


def save_shorts(items: list[dict]) -> None:
    state.save(SHORTS, items[-500:])


def _forced(url: str) -> dict:
    m = re.match(r"https?://(?:www\.)?github\.com/([\w.-]+/[\w.-]+)", url)
    h = re.match(r"https?://huggingface\.co/(?!spaces/|papers/)([\w.-]+/[\w.-]+)", url)
    p = re.match(r"https?://(?:huggingface\.co/papers|arxiv\.org/abs)/([\d.]+)", url)
    if m:
        key, title, kind = f"gh:{m.group(1).lower()}", m.group(1), "repo"
    elif h:
        key, title, kind = f"hf:{h.group(1).lower()}", h.group(1), "model"
    elif p:
        key, title, kind = f"paper:{p.group(1)}", p.group(1), "paper"
    else:
        key, title, kind = url, url, "news"
    item = {"key": key, "source": "owner", "label": "Chosen by the owner", "kind": kind, "title": title, "url": url,
            "summary": "", "published": None, "heat": 100, "entity": key, "signals": {}}
    return {"items": [item], "story": title, "angle": "", "format": "tool" if kind == "repo" else kind, "why": "forced"}


def _covered_now() -> list[dict]:
    """Made Shorts (posted or waiting) as the editor's "already covered" list."""
    cutoff = state.now() - timedelta(days=10)
    return [s for s in shorts() if (state.parse(s.get("made_at")) or cutoff) >= cutoff and s.get("status") != "failed"]


def make(url: str | None = None, dry: bool = False) -> dict | None:
    sid = "as-" + datetime.now(IST).strftime("%Y%m%d-%H%M")
    work = env.WORK / sid
    work.mkdir(parents=True, exist_ok=True)
    if url:
        picks = [_forced(url)]
    else:
        board = scouts.scan()
        state.save(work / "board.json", board[:120])
        picks = editor.pick(board, _covered_now())
    for n, pick in enumerate(picks[:3]):
        log.info("pick %d: %s | %s", n + 1, pick["story"], [i["url"] for i in pick["items"]])
        try:
            dossier = research.dossier(pick)
            state.save(work / "dossier.json", dossier)
            visuals, face = assets.gather(dossier, work / "assets")
            state.save(work / "visuals.json", visuals)
            script = writer.write(dossier, visuals)
            state.save(work / "script.json", script)
            narration = voice.narrate([s["say"].strip() for s in script["scenes"]], work / "voice")
            state.save(work / "narration.json", narration)
            built = compose.build(script, narration, visuals, face, dossier, work / "assets", work / "project")
            mix = sound.mix(Path(narration["wav"]), compose.VO_START, built["duration"], work / "audio", sid, "tech",
                            built["events"])
            shutil.copy(mix, work / "project" / "assets" / "mix.wav")
            video = render.render(work / "project", work / f"{sid}.mp4")
            problems = qa.technical(video, built["duration"])
            verdict = qa.judge(video, built["data"], script, work / "qa")
            ok = not problems and bool(verdict.get("publish"))
            src = compose._primary(dossier)
            entry = {"id": sid, "made_at": state.iso(), "status": "ready" if ok else "rejected", "story": pick["story"],
                     "title": script["title"], "description": script["description"], "tags": script.get("tags", []),
                     "hashtags": script.get("hashtags", ["#Shorts", "#AI"]), "chip": script.get("chip"),
                     "source": (dossier.get("subject") or {}).get("url") or src["url"],
                     "keys": [i["key"] for i in pick["items"]], "entity": pick["items"][0].get("entity", ""),
                     "duration": built["duration"], "voice": narration.get("model"), "writer": script.get("writer_model"),
                     "problems": problems, "judge": {k: verdict.get(k) for k in ("score", "publish", "defects", "notes")}}
            if not dry and env.in_ci():
                entry["video"] = publish.host(video, f"{sid}.mp4")
                entry["sheet"] = publish.host(Path(verdict["sheet"]), f"{sid}-sheet.jpg", "image/jpeg")
            items = shorts()
            items.append(entry)
            save_shorts(items)
            log.info("made %s: %s (%s)", sid, entry["title"], entry["status"])
            return entry
        except Exception as exc:
            log.error("pick %d failed: %s\n%s", n + 1, exc, traceback.format_exc()[-2500:])
    items = shorts()
    items.append({"id": sid, "made_at": state.iso(), "status": "failed", "title": "", "keys": []})
    save_shorts(items)
    return None


def _slot_due(now: datetime) -> str | None:
    """The slot (as "YYYY-MM-DD HH:MM" IST) that is due now and not yet used."""
    local = now.astimezone(IST)
    used = {s.get("slot") for s in shorts()}
    for day in (local.date(), local.date() - timedelta(days=1)):
        for hm in SLOTS:
            at = datetime.combine(day, datetime.strptime(hm, "%H:%M").time(), IST)
            key = at.strftime("%Y-%m-%d %H:%M")
            if at <= local < at + SLOT_GRACE and key not in used:
                return key
    return None


def _next_slot(now: datetime) -> datetime:
    local = now.astimezone(IST)
    for day in (local.date(), local.date() + timedelta(days=1)):
        for hm in SLOTS:
            at = datetime.combine(day, datetime.strptime(hm, "%H:%M").time(), IST)
            if at > local:
                return at
    raise RuntimeError("no slot")


def post_due(now: datetime) -> dict | None:
    slot = _slot_due(now)
    if not slot or not publish.configured():
        return None
    items = shorts()
    ready = [s for s in items if s.get("status") == "ready" and s.get("video")]
    fresh = [s for s in ready if now - (state.parse(s["made_at"]) or now) <= READY_MAX_AGE]
    for s in ready:
        if s not in fresh:
            s["status"] = "stale"
    if not fresh:
        save_shorts(items)
        return None
    short = fresh[0]
    meta = {**short, "disclosure": DISCLOSURE}
    short["posted"] = publish.post(short["video"], meta)
    short["slot"], short["posted_at"] = slot, state.iso()
    short["status"] = "posted" if any("id" in r for r in short["posted"].values()) else "post-failed"
    save_shorts(items)
    log.info("posted %s in slot %s: %s", short["id"], slot, short["posted"])
    return short


def plan() -> bool:
    """Post a ready Short if a slot is due; whether a new Short should be made now."""
    now = state.now()
    post_due(now)
    items = shorts()
    ready = [s for s in items if s.get("status") == "ready" and now - (state.parse(s["made_at"]) or now) <= READY_MAX_AGE]
    nxt = _next_slot(now)
    if ready:
        log.info("%d Short(s) ready; next slot %s IST%s", len(ready), nxt.strftime("%d %b %H:%M"),
                 "" if publish.configured() else " (Buffer not connected yet)")
        return False
    tries = [s for s in items if now - (state.parse(s.get("made_at")) or now) <= timedelta(minutes=50)]
    if len(tries) >= 2:
        log.info("two tries in the last 50 minutes; waiting")
        return False
    if nxt - now.astimezone(IST) <= MAKE_AHEAD:
        log.info("making the Short for %s IST", nxt.strftime("%d %b %H:%M"))
        return True
    log.info("next slot %s IST is more than %s away", nxt.strftime("%d %b %H:%M"), MAKE_AHEAD)
    return False


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S")
    for noisy in ("httpx", "urllib3", "faster_whisper"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    ap = argparse.ArgumentParser(prog="desk")
    sub = ap.add_subparsers(dest="cmd", required=True)
    mk = sub.add_parser("make")
    mk.add_argument("--url")
    mk.add_argument("--dry", action="store_true")
    sub.add_parser("plan")
    sub.add_parser("board")
    sub.add_parser("status")
    args = ap.parse_args(argv)
    if args.cmd == "make":
        return 0 if make(args.url, args.dry) else 1
    if args.cmd == "plan":
        needed = plan()
        if out := os.environ.get("GITHUB_OUTPUT"):
            with open(out, "a") as fh:
                fh.write(f"make={'true' if needed else 'false'}\n")
        return 0
    if args.cmd == "board":
        for item in scouts.scan()[:50]:
            print(f"{item['heat']:5.1f}  {item['label'][:30]:30}  {item['title'][:80]}")
        return 0
    for s in shorts()[-20:]:
        print(s["id"], s["status"], s.get("slot", ""), s["title"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
