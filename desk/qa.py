"""Quality control before anything is posted: technical checks on the file, then a judge who looks at frames from
every scene and reads the script, and blocks a Short with broken, unreadable or misleading pictures."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from . import gemini, render

log = logging.getLogger(__name__)

JUDGE = """You are the final quality judge of a YouTube Shorts channel about AI. You get a contact sheet of frames from
one Short (left to right, top to bottom, in time order) and its script. Check what a viewer would see:
- text cut off, overlapping, unreadable, or spilling out of its box; empty or broken areas; missing images;
- frames that look unfinished or glitchy; wrong or misleading visuals for the line being said;
- overall: would this stop a scroller and look professional?
Answer JSON: {"score": 1-10, "publish": true|false, "defects": ["..."], "notes": "one line"}.
Publish only if there is no defect a viewer would notice and the score is 7 or more."""


def technical(video: Path, expected: float) -> list[str]:
    info = render.probe(video)
    problems = []
    if (info["width"], info["height"]) != (1080, 1920):
        problems.append(f"size {info['width']}x{info['height']}")
    if not info["audio"]:
        problems.append("no audio track")
    if abs(info["duration"] - expected) > 1.0:
        problems.append(f"duration {info['duration']:.1f} s, expected {expected:.1f} s")
    if not 12 <= info["duration"] <= 59:
        problems.append(f"duration {info['duration']:.1f} s is outside 12-59 s")
    if info["bytes"] < 400_000:
        problems.append("file is suspiciously small")
    return problems


def judge(video: Path, data: dict, script: dict, folder: Path) -> dict:
    times = []
    for s in data["scenes"]:
        span = s["t1"] - s["t0"]
        times += [s["t0"] + min(1.2, span * 0.45), s["t0"] + span * 0.85]
    paths = render.frames(video, times[:16], folder)
    board = render.sheet(paths, folder / "sheet.jpg")
    lines = [{"scene": i, "type": s["type"], "say": s.get("say")} for i, s in enumerate(script["scenes"])]
    try:
        verdict, model = gemini.text_json(JUDGE, f"Script:\n{json.dumps(lines, ensure_ascii=False)}",
                                          models=gemini.FAST, temperature=0.2,
                                          images=[("image/jpeg", board.read_bytes())])
    except gemini.NoModel as exc:
        log.warning("judge unavailable (%s); passing on technical checks alone", exc)
        return {"score": None, "publish": True, "defects": [], "notes": "judge unavailable", "sheet": str(board)}
    verdict["model"], verdict["sheet"] = model, str(board)
    log.info("judge (%s): %s", model, json.dumps(verdict, ensure_ascii=False)[:800])
    return verdict
