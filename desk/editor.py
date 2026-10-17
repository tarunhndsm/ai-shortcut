"""The assignment editor: reads the scouts' board and picks the one story worth a Short right now."""

from __future__ import annotations

import json
import logging
import re

from . import gemini

log = logging.getLogger(__name__)

FORMATS = ("tool", "repo", "model", "research", "launch", "news", "howto")

SYSTEM = """You are the assignment editor of AI Shortcut, an English YouTube Shorts channel: "One AI shortcut a day".
Viewers are developers, students, freelancers and desk workers who want to know which new AI thing is worth their
time, and what it means for them. Every Short covers ONE story in 25-45 seconds with motion graphics.

From the scouts' board, pick the best story to make RIGHT NOW. Judge:
1. Is it genuinely new (last 48 hours) or trending today? Prefer stories several scouts report.
2. Will a broad tech audience care? Big launches from major labs, open models that beat famous ones, free or
   open-source tools that do something impressive, viral GitHub repos, tools viewers can try today.
3. Can we SHOW it? A repo page, a demo, a benchmark table, code, a product page, real numbers.
4. Is there one clear, surprising, useful takeaway?
Avoid: rumors, leaks, drama, lawsuits and politics, funding or stock news without a product, NSFW, crypto, weapons,
anything unverifiable, and anything already covered (list given). Do not pick generic listicles, tutorials,
awesome-lists or course repos unless they are clearly the day's biggest story.
Several items can be the same story (a model on Hugging Face, Hacker News, Reddit and OpenRouter): treat them as one,
and list all their indexes in "items".

Answer JSON: {"picks": [{"items": [indexes, the best source first], "story": "one line: what happened",
"angle": "the hook: why a viewer should care, in one line", "format": one of tool|repo|model|research|launch|news|howto,
"why": "one line"}]} with the best 3 picks in order."""


def _line(i: int, item: dict) -> dict:
    sig = item.get("signals", {})
    stats = ", ".join(f"{k.replace('_', ' ')} {v:,}" if isinstance(v, int) else f"{k.replace('_', ' ')} {v}"
                      for k, v in sig.items() if k in ("stars_today", "stars", "stars_per_day", "points", "comments",
                                                       "upvotes", "likes", "downloads", "rank", "outlet") and v)
    return {"i": i, "source": item["label"], "title": item["title"], "about": item["summary"][:220],
            "stats": stats, "heat": item["heat"], "published": item.get("published") or "trending now",
            "also_on": item.get("also_on", [])}


def pick(board: list[dict], made: list[dict], limit: int = 45) -> list[dict]:
    """The editor's picks, best first: each {"items": [board items], "story", "angle", "format", "why"}. `made` is the
    Shorts of the last days (posted or waiting), never to be repeated."""
    done = {k for short in made for k in short.get("keys", []) if k}
    covered = [f"{s.get('title', '')} [{s.get('entity') or s.get('source', '')}]" for s in made]
    fresh = [item for item in board if item["key"] not in done][:limit]
    if not fresh:
        return []
    prompt = (f"Already covered in the last 10 days (do not repeat):\n{json.dumps(covered[-40:], ensure_ascii=False)}\n\n"
              f"Scouts' board, hottest first (heat 0-100):\n{json.dumps([_line(i, it) for i, it in enumerate(fresh)], ensure_ascii=False)}")
    try:
        data, model = gemini.text_json(SYSTEM, prompt, models=gemini.FAST, temperature=0.4)
        log.info("editor (%s): %s", model, json.dumps(data, ensure_ascii=False)[:1500])
    except gemini.NoModel as exc:
        log.warning("editor: no model answered (%s); taking the hottest item", exc)
        return [{"items": [fresh[0]], "story": fresh[0]["title"], "angle": "", "format": "news", "why": "hottest"}]
    picks = []
    for entry in data.get("picks", [])[:3]:
        idx = [int(i) for i in entry.get("items", []) if re.fullmatch(r"\d+", str(i)) and int(i) < len(fresh)]
        if not idx:
            continue
        fmt = entry.get("format") if entry.get("format") in FORMATS else "news"
        picks.append({"items": [fresh[i] for i in idx], "story": str(entry.get("story", ""))[:300],
                      "angle": str(entry.get("angle", ""))[:300], "format": fmt, "why": str(entry.get("why", ""))[:300]})
    return picks
