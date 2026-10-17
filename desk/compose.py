"""The studio: turns a checked script, its narration and its visuals into a HyperFrames project (one HTML page with a
seekable GSAP timeline), and lists the sound effects that land on its cuts and reveals."""

from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name

from .env import TEMPLATE

VO_START = 0.25
TAIL = 1.1
LEAD = 0.12
LANG_COLORS = {"Python": "#3572A5", "TypeScript": "#3178c6", "JavaScript": "#f1e05a", "Rust": "#dea584", "Go": "#00ADD8",
               "Jupyter Notebook": "#DA5B0B", "C++": "#f34b7d", "C": "#555555", "Java": "#b07219", "Swift": "#F05138",
               "Kotlin": "#A97BFF", "Shell": "#89e051", "HTML": "#e34c26", "CSS": "#563d7c", "Ruby": "#701516",
               "Dart": "#00B4AB", "Zig": "#ec915c", "Mojo": "#ff4c1f", "Lua": "#000080", "Vue": "#41b883", "C#": "#178600"}
ICON = {
    "star": '<svg viewBox="0 0 16 16"><path fill="#e8ff47" d="M8 .25a.75.75 0 0 1 .67.42l1.88 3.81 4.21.61a.75.75 0 0 1 .42 1.28l-3.05 2.97.72 4.19a.75.75 0 0 1-1.09.79L8 12.35l-3.77 1.98a.75.75 0 0 1-1.09-.79l.72-4.19L.82 6.37a.75.75 0 0 1 .42-1.28l4.21-.61L7.33.67A.75.75 0 0 1 8 .25Z"/></svg>',
    "fork": '<svg viewBox="0 0 16 16"><path fill="#93a0b4" d="M5 5.37v.88c0 .41.34.75.75.75h4.5a.75.75 0 0 0 .75-.75v-.88a2.25 2.25 0 1 1 1.5 0v.88a2.25 2.25 0 0 1-2.25 2.25h-1.5v2.13a2.25 2.25 0 1 1-1.5 0V8.5h-1.5A2.25 2.25 0 0 1 3.5 6.25v-.88a2.25 2.25 0 1 1 1.5 0ZM5 3.25a.75.75 0 1 0-1.5 0 .75.75 0 0 0 1.5 0Zm6.75.75a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Zm-3 8.75a.75.75 0 1 0-1.5 0 .75.75 0 0 0 1.5 0Z"/></svg>',
    "heart": '<svg viewBox="0 0 16 16"><path fill="#ff3d5a" d="M8 14.25s-6.25-3.6-6.25-8.1A3.4 3.4 0 0 1 8 4.1a3.4 3.4 0 0 1 6.25 2.05c0 4.5-6.25 8.1-6.25 8.1Z"/></svg>',
    "down": '<svg viewBox="0 0 16 16"><path fill="#93a0b4" d="M7.25 1.75a.75.75 0 0 1 1.5 0v7.19l2.22-2.22a.75.75 0 1 1 1.06 1.06l-3.5 3.5a.75.75 0 0 1-1.06 0l-3.5-3.5a.75.75 0 1 1 1.06-1.06l2.22 2.22V1.75ZM2.75 13.5h10.5a.75.75 0 0 1 0 1.5H2.75a.75.75 0 0 1 0-1.5Z"/></svg>',
    "chip": '<svg viewBox="0 0 16 16"><path fill="#93a0b4" d="M5 1h1v2h1V1h2v2h1V1h1v2h1.5A1.5 1.5 0 0 1 14 4.5V5h2v1h-2v1h2v2h-2v1h2v1h-2v.5a1.5 1.5 0 0 1-1.5 1.5H11v2h-1v-2H9v2H7v-2H6v2H5v-2H3.5A1.5 1.5 0 0 1 2 11.5V11H0v-1h2V9H0V7h2V6H0V5h2v-.5A1.5 1.5 0 0 1 3.5 3H5V1Zm-.5 4v6h7V5h-7Z"/></svg>',
    "up": '<svg viewBox="0 0 16 16" width="34" height="34"><path fill="#e8ff47" d="M8 2 14 9H10v5H6V9H2z"/></svg>',
    "github": '<svg viewBox="0 0 16 16"><path fill="#ffffff" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z"/></svg>',
    "bell": '<svg viewBox="0 0 64 64"><path d="M32 6c-2.4 0-4.4 2-4.4 4.4v1.4C19.4 13.7 14 21 14 29.6V42l-5 6v2h46v-2l-5-6V29.6C50 21 44.6 13.7 36.4 11.8v-1.4C36.4 8 34.4 6 32 6z" fill="#ffffff"/><path d="M25 53a7 7 0 0 0 14 0z" fill="#ffffff"/></svg>',
}
MARK = ('<svg class="cta-mark" viewBox="0 0 100 100"><rect width="100" height="100" rx="26" fill="#e8ff47"/>'
        '<path d="M58 11 L23 57 H47 L41 89 L77 41 H53 Z" fill="#0b0f14"/></svg>')
RING = ('<svg class="ring" viewBox="0 0 780 780"><circle cx="390" cy="390" r="372" fill="none" stroke="rgba(232,255,71,0.18)" '
        'stroke-width="3"/><g class="ring-spin"><circle cx="390" cy="390" r="338" fill="none" stroke="rgba(232,255,71,0.5)" '
        'stroke-width="6" stroke-dasharray="44 28" stroke-linecap="round"/></g></svg>')


def e(text) -> str:
    return html.escape(str(text or ""), quote=True)


def compact(n) -> str | None:
    if n in (None, ""):
        return None
    n = float(n)
    if n >= 1e9:
        s = f"{n / 1e9:.1f}B"
    elif n >= 1e6:
        s = f"{n / 1e6:.0f}M" if n >= 1e8 else f"{n / 1e6:.1f}M"
    elif n >= 1e4:
        s = f"{n / 1e3:.0f}K" if n >= 1e5 else f"{n / 1e3:.1f}K"
    else:
        s = f"{int(round(n)):,}"
    return re.sub(r"\.0(?=[KMB])", "", s)


def odo(text: str) -> str:
    out = []
    for ch in str(text):
        if ch.isdigit():
            digits = "".join(f"<span>{d % 10}</span>" for d in range(20))
            out.append(f'<span class="odo"><span class="strip" data-d="{ch}">{digits}</span></span>')
        else:
            out.append(f'<span class="odo-ch">{"&nbsp;" if ch == " " else e(ch)}</span>')
    return "".join(out)


def _face(face: str | None, name: str, cls: str = "face") -> str:
    if face:
        return f'<div class="{cls}"><img src="{e(face)}" alt="" /></div>'
    letters = "".join(w[0] for w in re.findall(r"[A-Za-z0-9]+", name)[:2]).upper() or "AI"
    return f'<div class="{cls} mono">{e(letters)}</div>'


def _headline(text: str, highlight: list[str]) -> str:
    marks = {re.sub(r"\W", "", h).lower() for h in highlight or []}
    words = []
    for word in str(text).split():
        key = re.sub(r"\W", "", word).lower()
        if key and key in marks:
            words.append(f'<span class="hw hl"><span class="hl-bar"></span><span class="hl-tx">{e(word)}</span></span>')
        else:
            words.append(f'<span class="hw">{e(word)}</span>')
    return " ".join(words)


def _first_sentence(text: str, limit: int = 150) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if len(line) < 40 or line[0] in "#|<>-*![" or line.lower().startswith(("license", "pip ", "import ")):
            continue
        sentence = re.split(r"(?<=[.!?])\s", line)[0]
        return sentence if len(sentence) <= limit else sentence[:limit].rsplit(" ", 1)[0] + "…"
    return ""


def _shell(code: str) -> str:
    out = []
    for raw in code.splitlines():
        line = raw.rstrip()
        if line.lstrip().startswith("#"):
            out.append(f'<span class="tok-com">{e(line)}</span>')
            continue
        parts = re.split(r"(\s+)", line.lstrip("$ ").lstrip())
        pieces, first = [], True
        for part in parts:
            if not part or part.isspace():
                pieces.append(e(part))
            elif first:
                pieces.append(f'<span class="tok-cmd">{e(part)}</span>')
                first = False
            elif part.startswith("-"):
                pieces.append(f'<span class="tok-flag">{e(part)}</span>')
            elif part[:1] in "\"'":
                pieces.append(f'<span class="tok-str">{e(part)}</span>')
            else:
                pieces.append(e(part))
        out.append("".join(pieces))
    return "\n".join(out)


def _code_lines(lang: str, code: str) -> tuple[list[str], bool]:
    lines = [l.rstrip() for l in code.strip("\n").splitlines() if l.strip()][:5]
    shell = lang.lower() in ("bash", "sh", "shell", "console", "zsh", "terminal", "")
    if shell:
        return _shell("\n".join(lines)).splitlines(), True
    try:
        lexer = get_lexer_by_name(lang)
    except Exception:
        return [e(l) for l in lines], False
    body = highlight("\n".join(lines), lexer, HtmlFormatter(nowrap=True, classprefix="tok-"))
    return body.rstrip("\n").splitlines(), False


def _primary(dossier: dict) -> dict:
    return next((s for s in dossier["sources"] if s["type"] in ("github", "huggingface", "huggingface-space", "paper")),
                dossier["sources"][0])


def _card(dossier: dict, face: str | None) -> str:
    src = _primary(dossier)
    sub = src.get("subject") or dossier.get("subject") or {}
    nums, facts = src.get("numbers") or {}, src.get("facts") or {}
    kind = src["type"]
    stats, tags, desc_cls, trend = [], [], "card-desc", ""
    if kind == "github":
        name = f'<span class="owner">{e(sub.get("owner"))}/</span><span class="repo">{e(sub.get("repo"))}</span>'
        plat = f'<div class="platform">{ICON["github"]}</div>'
        desc = src.get("about") or _first_sentence(src.get("text", ""))
        stats.append(("star", compact(nums.get("stars")), "stars"))
        stats.append(("fork", compact(nums.get("forks")), "forks"))
        if facts.get("language"):
            dot = f'<span class="lang-dot" style="background:{LANG_COLORS.get(facts["language"], "#8b949e")}"></span>'
            stats.append(("lang", dot + e(facts["language"]), "language"))
        tags = (facts.get("topics") or [])[:4] or [t for t in (facts.get("license"),) if t and t != "NOASSERTION"]
        today = ((src.get("scout") or {}).get("signals") or {}).get("stars_today")
        if today:
            trend = f'<div class="trend rv">{ICON["up"]}+{today:,} stars today</div>'
    elif kind in ("huggingface", "huggingface-space"):
        name = f'<span class="owner">{e(sub.get("owner"))}/</span><span class="repo">{e(sub.get("repo"))}</span>'
        plat = '<div class="platform"><div class="plat-txt">HF</div></div>'
        desc = src.get("about") if kind == "huggingface-space" and src.get("about") else _first_sentence(src.get("text", ""))
        stats.append(("heart", compact(nums.get("likes")), "likes"))
        if nums.get("downloads_last_month"):
            stats.append(("down", compact(nums["downloads_last_month"]), "downloads"))
        if nums.get("parameters"):
            stats.append(("chip", compact(nums["parameters"]), "parameters"))
        tags = [t for t in (facts.get("pipeline"), facts.get("license"), facts.get("library")) if t][:4]
    elif kind == "paper":
        name = f'<span class="owner">arXiv </span><span class="repo">{e(src["url"].rsplit("/", 1)[-1])}</span>'
        plat = '<div class="platform"><div class="plat-txt" style="background:#b31b1b;color:#fff">arXiv</div></div>'
        desc, desc_cls = src.get("title", ""), "card-desc title"
        if nums.get("upvotes_on_hugging_face"):
            stats.append(("up", compact(nums["upvotes_on_hugging_face"]), "upvotes"))
        if nums.get("authors"):
            stats.append(("chip", str(nums["authors"]), "authors"))
        tags = (facts.get("authors") or [])[:2]
    else:
        name = f'<span class="repo">{e(src.get("site"))}</span>'
        plat = ""
        desc, desc_cls = src.get("title", ""), "card-desc title"
    boxes = []
    for icon, value, label in stats:
        if not value:
            continue
        shown = value if icon == "lang" else odo(value)
        svg = "" if icon == "lang" else ICON.get(icon, "")
        boxes.append(f'<div class="stat-box rv"><div class="stat-num">{svg}<span>{shown}</span></div>'
                     f'<div class="stat-lbl">{e(label)}</div></div>')
    tag_html = "".join(f'<span class="tag">{e(t)}</span>' for t in tags if t)
    return (f'<div class="card"><div class="card-top rv">{_face(face, sub.get("owner") or sub.get("name") or "", "card-face")}'
            f'<div class="card-name">{name}</div>{plat}</div>'
            f'<div class="{desc_cls} rv">{e(desc)}</div>'
            + (f'<div class="tags">{tag_html}</div>' if tag_html else "")
            + (f'<div class="stats">{"".join(boxes)}</div>' if boxes else "") + trend + "</div>")


def _url_html(url: str) -> str:
    parts = urlparse(url)
    host = parts.netloc.removeprefix("www.")
    return f"<b>{e(host)}</b>{e(parts.path[:60])}"


def build(script: dict, narration: dict, visuals: list[dict], face: str | None, dossier: dict, assets: Path,
          project: Path) -> dict:
    """Write the project; returns {"duration", "events", "data"}."""
    if project.exists():
        shutil.rmtree(project)
    shutil.copytree(TEMPLATE, project)
    shutil.copytree(assets, project / "assets", dirs_exist_ok=True)
    scenes = script["scenes"]
    words = [{**w, "start": w["start"] + VO_START, "end": w["end"] + VO_START} for w in narration["words"]]
    duration = round(VO_START + narration["duration"] + TAIL, 3)
    starts = [0.0]
    for i in range(1, len(scenes)):
        own = [w["start"] for w in words if w["beat"] == i]
        starts.append(max((min(own) - LEAD) if own else starts[-1] + 0.6, starts[-1] + 0.6))
    spans = [(round(starts[i], 3), round(starts[i + 1] if i + 1 < len(starts) else duration, 3)) for i in range(len(scenes))]

    events: list[tuple[float, str, float]] = []
    data_scenes, html_scenes = [], []
    shots = [v for v in visuals if v["kind"] == "screenshot"]
    shot_n = 0
    primary = _primary(dossier)
    sub = dossier.get("subject") or primary.get("subject") or {}
    for i, (scene, (t0, t1)) in enumerate(zip(scenes, spans)):
        kind = scene["type"]
        meta = {"type": kind, "t0": t0, "t1": t1}
        if i > 0:
            events.append((t0 - 0.12, "whoosh", -4))
        body = ""
        if kind == "hook":
            n = len(str(scene.get("headline", "")).split())
            meta["slam"] = round(t0 + 0.1 + 0.07 * n + 0.22, 3)
            events.append((meta["slam"], "hit", 0))
            label = sub.get("name") or primary.get("site") or ""
            badge = (f'<div class="badge">{_face(face, sub.get("owner") or label)}<div class="badge-label">{e(label)}</div></div>'
                     if label else "")
            kicker = f'<div class="kicker">{e(scene.get("kicker"))}</div>' if scene.get("kicker") else ""
            body = f'{badge}{kicker}<h1 class="headline">{_headline(scene.get("headline", ""), scene.get("highlight", []))}</h1>'
        elif kind == "punch":
            n = len(str(scene.get("headline", "")).split())
            meta["slam"] = round(t0 + 0.12 + 0.09 * n + 0.2, 3)
            events.append((meta["slam"], "hit", -5))
            body = f'<div class="punch-rule"></div><h1 class="headline">{_headline(scene.get("headline", ""), scene.get("highlight", []))}</h1>'
        elif kind == "card":
            meta["roll"] = round(t0 + 0.45, 3)
            events += [(meta["roll"], "pop", -6), (meta["roll"] + 1.25, "ding", -12)]
            body = _card(dossier, face)
        elif kind == "stat":
            meta["roll"] = round(t0 + 0.12, 3)
            events += [(t0 + 0.08, "hit", -7), (meta["roll"] + 1.15, "ding", -10)]
            sub_line = f'<div class="stat-sub rv">{e(scene.get("sub"))}</div>' if scene.get("sub") else ""
            number, _, unit = str(scene.get("value", "")).strip().partition(" ")
            unit_html = f'<div class="stat-unit rv">{e(unit)}</div>' if unit else ""
            body = (f'{RING}<div class="stat-value">{odo(number)}</div>{unit_html}'
                    f'<div class="stat-label rv">{e(scene.get("label"))}</div>{sub_line}')
        elif kind == "bars":
            items = [it for it in scene.get("items", []) if isinstance(it.get("value"), (int, float))][:5]
            top = max((float(it["value"]) for it in items), default=1) or 1
            gap = max(0.22, min(0.5, (t1 - t0 - 1.4) / max(1, len(items))))
            meta["marks"] = [round(t0 + 0.4 + k * gap, 3) for k in range(len(items))]
            events += [(m, "pop", -9) for m in meta["marks"]]
            unit = scene.get("unit") or ""
            rows = "".join(
                f'<div class="bar{" hot" if it.get("hot") else ""}"><div class="bar-head"><span>{e(it.get("label"))}</span>'
                f'<span class="v">{e(f"{float(it["value"]):g}{unit}")}</span></div><div class="bar-track">'
                f'<div class="bar-fill" style="width:{max(6.0, 100 * float(it["value"]) / top):.1f}%"></div></div></div>'
                for it in items)
            body = f'<div class="panel-title">{e(scene.get("title"))}</div>{rows}'
        elif kind == "list":
            items = [str(x) for x in scene.get("items", [])][:4]
            gap = max(0.3, min(1.3, (t1 - t0 - 0.9) / max(1, len(items))))
            meta["marks"] = [round(t0 + 0.35 + k * gap, 3) for k in range(len(items))]
            events += [(m, "pop", -7) for m in meta["marks"]]
            rows = "".join(f'<div class="item"><div class="item-n">{k + 1}</div><div class="item-t">{e(x)}</div></div>'
                           for k, x in enumerate(items))
            body = (f'<div class="panel-title">{e(scene.get("title"))}</div>' if scene.get("title") else "") + rows
        elif kind == "code":
            lines, shell = _code_lines(str(scene.get("lang", "bash")), str(scene.get("code", "")))
            plain = [re.sub(r"<[^>]+>", "", html.unescape(l)) for l in lines]
            longest = max((len(p) for p in plain), default=10) + (3 if shell else 0)
            size = max(20, min(36, int(880 / (0.6 * max(longest, 1)))))
            at, meta["lines"] = t0 + 0.55, []
            for p in plain:
                steps = max(1, len(p))
                dur = round(max(0.3, min(1.3, steps * 0.035)), 3)
                meta["lines"].append({"t0": round(at, 3), "dur": dur, "steps": steps})
                events += [(at + dur * k / steps, "click", -16) for k in range(0, steps, 2)]
                at += dur + 0.22
            meta["typed"] = round(at - 0.22, 3)
            prompt = '<span class="prompt">$</span>' if shell else ""
            body_lines = "".join(f'<span class="cl">{prompt}<span class="typed">{l}</span>'
                                 + ('<span class="cursor"></span>' if k == len(lines) - 1 else "") + "</span>"
                                 for k, l in enumerate(lines))
            cap = f'<div class="code-cap">{e(scene.get("caption"))}</div>' if scene.get("caption") else ""
            body = (f'<div class="term"><div class="term-bar"><i class="dot d1"></i><i class="dot d2"></i><i class="dot d3"></i>'
                    f'<span class="term-title">{"terminal" if shell else e(scene.get("lang"))}</span></div>'
                    f'<div class="term-body" style="font-size:{size}px">{body_lines}</div></div>{cap}')
        elif kind == "shot" and shots:
            shot = shots[shot_n % len(shots)]
            shot_n += 1
            shown_h = 960 * shot["h"] / shot["w"]
            meta["pan"] = round(max(0.0, min(shown_h - 794, 640)), 1)
            label = f'<div class="label">{e(scene.get("label"))}</div>' if scene.get("label") else ""
            body = (f'<div class="browser"><div class="browser-bar"><i class="dot d1"></i><i class="dot d2"></i>'
                    f'<i class="dot d3"></i><div class="url">{_url_html(shot["url"])}</div></div>'
                    f'<div class="viewport"><img src="{e(shot["file"])}" alt="" /></div></div>{label}')
        elif kind in ("media", "shot"):
            pick = scene.get("image")
            vis = visuals[pick] if isinstance(pick, int) and 0 <= pick < len(visuals) else (visuals[0] if visuals else None)
            if vis:
                meta["type"] = "media"
                label = f'<div class="label">{e(scene.get("label"))}</div>' if scene.get("label") else ""
                body = (f'<div class="frame"><img class="fill" src="{e(vis["file"])}" alt="" />'
                        f'<img class="main" src="{e(vis["file"])}" alt="" /></div>{label}')
            else:
                meta["type"], meta["slam"] = "punch", round(t0 + 0.5, 3)
                body = f'<div class="punch-rule"></div><h1 class="headline">{_headline(scene.get("label") or dossier["story"][:40], [])}</h1>'
        elif kind == "versus":
            meta["slam"] = round(t0 + 0.42, 3)
            events.append((meta["slam"], "hit", -7))
            rows = "".join(f'<div class="vs-row"><span class="vs-l">{e(r[1] if len(r) > 1 else "")}</span>'
                           f'<span class="vs-k">{e(r[0])}</span><span class="vs-r">{e(r[2] if len(r) > 2 else "")}</span></div>'
                           for r in scene.get("rows", [])[:4] if isinstance(r, list) and r)
            body = (f'<div class="vs-head"><div class="vs-side l">{e(scene.get("left"))}</div><div class="vs-badge">VS</div>'
                    f'<div class="vs-side r">{e(scene.get("right"))}</div></div>{rows}')
        elif kind == "quote":
            words_html = " ".join(f'<span class="qw">{e(w)}</span>' for w in str(scene.get("quote", "")).split())
            body = (f'<div class="qmark">&ldquo;</div><p class="qtext">{words_html}</p>'
                    f'<div class="qwho">— {e(scene.get("who"))}</div>')
        elif kind == "cta":
            meta["slam"] = round(t0 + 0.6, 3)
            events += [(meta["slam"], "pop", -4), (meta["slam"] + 0.08, "ding", -10)]
            body = (f'{MARK}<div class="cta-title">One AI shortcut <em>a day.</em></div>'
                    f'<div class="cta-btn">{ICON["bell"]}<span>FOLLOW</span></div>'
                    f'<div class="cta-handle">AI tools · models · repos</div>')
        html_scenes.append(f'<section class="scene sc-{meta["type"]}" id="s{i}"><div class="inner">{body}</div></section>')
        data_scenes.append(meta)

    chunks = _chunks(words, duration)
    chunk_html = "".join(f'<div class="chunk">{" ".join(f"<span class=w>{e(w)}</span>" for w in c["text"])}</div>' for c in chunks)
    data = {"duration": duration, "scenes": data_scenes,
            "chunks": [{"t0": c["t0"], "t1": c["t1"], "words": c["words"]} for c in chunks]}
    source = sub.get("url") or primary["url"]
    audio = (f'<audio id="mix" src="assets/mix.wav" data-start="0" data-duration="{duration}" '
             'data-volume="1" data-track-index="1"></audio>')
    page = (project / "index.html").read_text()
    for key, value in {"{{DURATION}}": str(duration), "{{CHIP}}": e(script.get("chip", "AI NEWS")),
                       "{{SCENES_HTML}}": "".join(html_scenes), "{{CHUNKS_HTML}}": chunk_html,
                       "{{SOURCE}}": _url_html(source), "{{AUDIO_HTML}}": audio,
                       "{{DATA_JSON}}": json.dumps(data, ensure_ascii=False)}.items():
        page = page.replace(key, value)
    (project / "index.html").write_text(page)
    return {"duration": duration, "events": sorted(events), "data": data}


def _chunks(words: list[dict], duration: float) -> list[dict]:
    """Caption groups of up to three words (18 letters), broken after punctuation and between scenes."""
    groups, cur = [], []
    for w in words:
        if cur and (len(cur) >= 3 or sum(len(x["text"]) for x in cur) + len(w["text"]) > 18 or w["beat"] != cur[-1]["beat"]
                    or re.search(r"[.,!?;:]$", cur[-1]["text"])):
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    out = []
    for k, g in enumerate(groups):
        t0 = round(max(0.0, g[0]["start"] - 0.04), 3)
        nxt = groups[k + 1][0]["start"] - 0.04 if k + 1 < len(groups) else duration - 0.1
        t1 = round(min(nxt, g[-1]["end"] + 0.5), 3)
        out.append({"t0": t0, "t1": max(t1, t0 + 0.2), "words": [[round(w["start"], 3), round(w["end"], 3)] for w in g],
                    "text": [re.sub(r"[,.;:]+$", "", w["text"]) for w in g]})
    return out
