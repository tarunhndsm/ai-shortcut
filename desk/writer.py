"""The writer and the fact-checker: a Short's script as typed scenes, each a line of narration and what is on screen,
checked against the dossier before anything is voiced."""

from __future__ import annotations

import json
import logging
import re

from . import gemini

log = logging.getLogger(__name__)

TYPES = ("hook", "card", "stat", "bars", "list", "code", "shot", "media", "versus", "quote", "punch", "cta")
CHIPS = ("NEW MODEL", "TRENDING REPO", "FREE TOOL", "RESEARCH", "LAUNCH", "AI NEWS", "OPEN SOURCE", "HOW TO")

SYSTEM = """You write YouTube Shorts for AI Shortcut ("One AI shortcut a day"), a faceless English channel with
motion graphics and a confident, upbeat narrator. Viewers: developers, students, freelancers, desk workers.

Write ONE Short about the story in the dossier. Hard rules:
- Every claim and every number must come from the dossier. Never invent features, numbers, dates, prices,
  comparisons or quotes. If the dossier doesn't say it, don't say it. Say "claims" or "says" for a maker's own claims.
- 110 to 130 words of narration in total (about 40-45 seconds), in 7 to 9 scenes. Each scene's "say" is ONE short
  spoken sentence (6-20 words).
- Scene 1 is the hook: the payoff first, the most surprising concrete true thing (a number, a result, what it lets you
  do), in the first 2 seconds. No greetings, no "in this video". Scene 2 shows the proof on screen (shot, card, stat,
  bars, code or versus).
- Add what the sources don't spell out: why it matters, who it's for, how it compares with what people use today
  (only from the dossier), or the catch. At least two scenes are your analysis, not a summary. Never copy a sentence
  from the sources; explain it in your own words.
- No fixed formula: pick the scene types that prove this story (code for a tool you can install, bars or versus for
  benchmarks, shot for a product, quote when someone said something telling) and vary their order.
- Talk to the viewer ("you"), use contractions, short punchy words. Vary rhythm. Be specific, not hypey.
- A comparison names its measure in the same line ("on the DeepSWE coding benchmark"); never turn one win into
  "beats X" in general, and don't hide where it loses if the dossier shows it. No hype words: shocking, secretly,
  insane, crazy, mind-blowing, game-changer, destroys, killer, you won't believe.
- Write "say" exactly as it should be spoken: no URLs, slashes, underscores, hashtags or emoji; say names the way a
  person would ("Qwen three point eight", "V4.1" is fine, "claude-plugins-official" becomes "Claude plugins official").
- The second-to-last scene gives the takeaway: what it means for the viewer or who should try it (an honest opinion).
- The last scene is "cta": one short line asking to follow for daily AI shortcuts (vary the wording).

Scene types (pick what the dossier can fill; never repeat a type except list/stat/punch):
- {"type":"hook","say":...,"headline":"3-6 punchy words for the screen","highlight":["ONE","WORD"],"kicker":"2-5 words, e.g. #1 ON GITHUB TODAY"}
- {"type":"card","say":...}  the subject's card (repo or model: name, description, stars/likes) built from the dossier
- {"type":"stat","say":...,"value":"a number from the dossier, e.g. 12,400 or 1M or 37%","label":"what it counts, 2-6 words","sub":"optional context, 2-6 words"}
- {"type":"bars","say":...,"title":"2-5 words","unit":"% or empty","items":[{"label":"name","value":number,"hot":true for the subject}]} 2-5 bars, numbers copied exactly from a dossier table
- {"type":"list","say":...,"title":"2-5 words","items":["3-6 words","...","..."]} 3 or 4 items
- {"type":"code","say":...,"lang":"bash","code":"1-4 short lines copied from the dossier's code","caption":"2-5 words"}
- {"type":"shot","say":...,"label":"2-5 words"}  a screenshot of the main page (only if "screenshot" is listed in visuals)
- {"type":"media","say":...,"image":index from the visuals list,"label":"2-5 words"}
- {"type":"versus","say":...,"left":"name","right":"name","rows":[["row label","left value","right value"]]} 2-4 rows, from the dossier
- {"type":"quote","say":...,"quote":"a real quote from the dossier, under 22 words","who":"who said it"}
- {"type":"punch","say":...,"headline":"2-6 words","highlight":["WORD"]}  a big statement, for the takeaway
- {"type":"cta","say":...}

Also give:
- "title": under 70 characters, names the thing and makes people curious, no clickbait the video can't back up, no ALL CAPS words except names
- "description": 2-3 short sentences on what it is and why it matters (no links; they are added for you)
- "tags": 6-10 search tags; "hashtags": 3 hashtags starting with #Shorts
- "chip": one of NEW MODEL, TRENDING REPO, FREE TOOL, RESEARCH, LAUNCH, AI NEWS, OPEN SOURCE, HOW TO

Answer JSON: {"title":..., "description":..., "tags":[...], "hashtags":[...], "chip":..., "scenes":[...]}"""

CHECK = """You are the fact-checker of an AI news Shorts channel. Compare every scene of the script (both what is said
and what is shown: headline, value, label, items, rows, quote, code) with the dossier. Flag anything not supported by
the dossier, any number that differs from the dossier, any exaggeration ("best ever", "beats everyone" when the
dossier shows otherwise), anything that presents a maker's claim as independent fact, and anything misleading.
Ignore style. Answer JSON: {"ok": true|false, "problems": [{"scene": index, "issue": "...", "fix": "a corrected line"}]}"""


def _brief(dossier: dict, visuals: list[dict]) -> str:
    sources = []
    for i, src in enumerate(dossier["sources"]):
        sources.append({"n": i, "type": src["type"], "site": src.get("site"), "url": src["url"], "title": src.get("title"),
                        "about": src.get("about"), "published": src.get("published"), "numbers": src.get("numbers"),
                        "facts": src.get("facts"), "scout_signals": (src.get("scout") or {}).get("signals"),
                        "text": (src.get("text") or "")[:3500], "code": src.get("code", [])[:3],
                        "tables": src.get("tables", [])[:2]})
    return json.dumps({"story": dossier["story"], "angle": dossier["angle"], "format": dossier["format"],
                       "subject": dossier.get("subject"), "visuals": visuals, "sources": sources}, ensure_ascii=False)


def _num(text: str) -> list[float]:
    out = []
    for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s*([kKmMbB](?![a-z]))?", str(text)):
        value = float(m.group(1).replace(",", ""))
        out.append(value * {"k": 1e3, "m": 1e6, "b": 1e9}.get((m.group(2) or "").lower(), 1))
    return out


def _numbers_ok(script: dict, dossier: dict) -> list[str]:
    """Every number shown on screen is one the dossier has (within 3%, so 12.4K matches 12,437)."""
    known = _num(json.dumps(dossier, ensure_ascii=False))
    problems = []
    for i, scene in enumerate(script["scenes"]):
        shown = []
        if scene["type"] == "stat":
            shown += _num(scene.get("value", ""))
        if scene["type"] == "bars":
            shown += [float(it.get("value", 0)) for it in scene.get("items", [])]
        if scene["type"] == "versus":
            shown += [n for row in scene.get("rows", []) for cell in row[1:] for n in _num(cell)]
        for n in shown:
            if n and not any(abs(n - k) <= max(0.03 * k, 0.051) for k in known):
                problems.append(f"scene {i}: {n:g} is not in the dossier")
    return problems


def _valid(script: dict, visuals: list[dict]) -> list[str]:
    problems = []
    scenes = script.get("scenes")
    if not isinstance(scenes, list) or not 6 <= len(scenes) <= 10:
        return ["needs 7-9 scenes"]
    words = sum(len(str(s.get("say", "")).split()) for s in scenes)
    if not 98 <= words <= 140:
        problems.append(f"narration is {words} words; it must be 110-130")
    if scenes[0].get("type") != "hook" or scenes[-1].get("type") != "cta":
        problems.append("first scene must be hook and last must be cta")
    for i, s in enumerate(scenes):
        kind = s.get("type")
        if kind not in TYPES:
            problems.append(f"scene {i}: unknown type {kind}")
            continue
        if not str(s.get("say", "")).strip():
            problems.append(f"scene {i}: empty say")
        if re.search(r"https?://|www\.|[/_#]", str(s.get("say", ""))):
            problems.append(f"scene {i}: say must be spoken words only (no URLs, slashes, underscores, hashtags)")
        if kind == "media" and not (isinstance(s.get("image"), int) and 0 <= s["image"] < len(visuals)
                                    and visuals[s["image"]]["kind"] == "image"):
            problems.append(f"scene {i}: media needs an image index from visuals")
        if kind == "shot" and not any(v["kind"] == "screenshot" for v in visuals):
            problems.append(f"scene {i}: no screenshot is available")
        if kind == "bars" and not 2 <= len(s.get("items", [])) <= 6:
            problems.append(f"scene {i}: bars needs 2-5 items")
        if kind == "list" and not 2 <= len(s.get("items", [])) <= 5:
            problems.append(f"scene {i}: list needs 3-4 items")
        if kind == "code" and not str(s.get("code", "")).strip():
            problems.append(f"scene {i}: code is empty")
    if len(str(script.get("title", ""))) > 80 or not script.get("title"):
        problems.append("title must be under 70 characters (80 at most)")
    return problems


def write(dossier: dict, visuals: list[dict], rounds: int = 3) -> dict:
    """A checked script. Raises when no draft passes."""
    brief = _brief(dossier, visuals)
    feedback = ""
    for attempt in range(rounds):
        prompt = f"Dossier:\n{brief}" + (f"\n\nYour last draft had these problems; fix them all:\n{feedback}" if feedback else "")
        script, model = gemini.text_json(SYSTEM, prompt, models=gemini.SMART, temperature=0.8, timeout=200)
        problems = _valid(script, visuals)
        if not problems:
            problems = _numbers_ok(script, dossier)
        if not problems:
            verdict, checker = gemini.text_json(CHECK, f"Dossier:\n{brief}\n\nScript:\n{json.dumps(script, ensure_ascii=False)}",
                                                models=gemini.FAST, temperature=0.2)
            log.info("fact-check (%s): %s", checker, json.dumps(verdict, ensure_ascii=False)[:1200])
            if verdict.get("ok") or not verdict.get("problems"):
                script["writer_model"], script["checker_model"] = model, checker
                script["chip"] = script.get("chip") if script.get("chip") in CHIPS else "AI NEWS"
                return script
            problems = [f"scene {p.get('scene')}: {p.get('issue')} (fix: {p.get('fix')})" for p in verdict["problems"]]
        log.info("draft %d (%s) rejected: %s", attempt + 1, model, problems)
        feedback = "\n".join(f"- {p}" for p in problems)
    raise RuntimeError(f"no draft passed: {feedback}")
