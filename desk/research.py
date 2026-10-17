"""The researcher: turns the editor's pick into a dossier of facts from primary sources, the repo and its README,
the model card, the paper, the lab's post or the article, and what Hacker News commenters say about it."""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse

import trafilatura
from bs4 import BeautifulSoup

from . import net

log = logging.getLogger(__name__)

TEXT_LIMIT = 6000
BADGE = re.compile(r"(?i)shields\.io|badge|travis-ci|codecov|circleci|github\.com/.+/workflows|/actions/workflows|"
                   r"buymeacoffee|ko-fi|discord|star-history|contrib\.rocks|visitor|hits\.|komarev|wakatime|\.svg(\?|$)")
CMD = re.compile(r"(?m)^\s*(\$ )?(pip3? install|uv (pip|add|tool)|uvx|npx|npm (i|install)|pnpm|yarn|brew install|"
                 r"docker (run|compose)|git clone|curl -|wget |cargo install|go install|ollama (run|pull)|"
                 r"python3? |hf |huggingface-cli|claude |gemini |codex )")


def _markdown(md: str, base: str) -> dict:
    """Plain text, short code blocks (install and run commands first), images (badges dropped) and tables."""
    md = re.sub(r"(?s)^---\n.*?\n---\n", "", md)
    code = []
    for lang, body in re.findall(r"(?s)```([\w+-]*)[^\n]*\n(.*?)```", md):
        lines = [l for l in body.strip("\n").splitlines() if l.strip()]
        if 1 <= len(lines) <= 14 and max(len(l) for l in lines) <= 110:
            code.append({"lang": lang or "bash", "code": "\n".join(lines), "commands": bool(CMD.search(body))})
    code.sort(key=lambda c: (not c["commands"], len(c["code"])))
    images = []
    for alt, src in re.findall(r"!\[([^\]]*)\]\(([^)\s]+)", md) + [("", s) for s in re.findall(r"<img[^>]+src=[\"']([^\"']+)", md)]:
        url = urljoin(base, src.strip("<>"))
        if url.startswith("http") and not BADGE.search(url) and url not in [i["url"] for i in images]:
            images.append({"url": url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
                           if "github.com" in url and "/blob/" in url else url, "alt": alt[:120]})
    tables = []
    for block in re.findall(r"(?m)((?:^\|.*\|\s*$\n?){3,})", md):
        rows = [[c.strip(" *`") for c in line.strip().strip("|").split("|")] for line in block.strip().splitlines()]
        rows = [r for r in rows if not all(re.fullmatch(r":?-{2,}:?", c or "--") for c in r)]
        if 2 <= len(rows) <= 16 and 2 <= len(rows[0]) <= 9:
            tables.append([[re.sub(r"<[^>]+>|\[([^\]]*)\]\([^)]*\)", r"\1", c)[:40] for c in row] for row in rows])
    text = re.sub(r"(?s)```.*?```", " ", md)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)|<[^>]+>", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", text)).strip()
    return {"text": text[:TEXT_LIMIT], "code": code[:4], "images": images[:8], "tables": tables[:3]}


def github(full: str) -> dict:
    api = net.json_get(f"https://api.github.com/repos/{full}", headers=net.github_headers())
    try:
        readme = net.get(f"https://api.github.com/repos/{full}/readme", headers=net.github_headers(raw=True)).text
    except Exception:
        readme = ""
    parsed = _markdown(readme, f"https://raw.githubusercontent.com/{full}/HEAD/")
    release = None
    try:
        rel = net.json_get(f"https://api.github.com/repos/{full}/releases/latest", headers=net.github_headers(), tries=1)
        release = {"tag": rel.get("tag_name"), "published": rel.get("published_at")}
    except Exception:
        pass
    owner = full.split("/")[0]
    return {"type": "github", "url": api["html_url"], "title": full, "site": "GitHub",
            "about": api.get("description") or "", "published": api.get("created_at"),
            "numbers": {"stars": api["stargazers_count"], "forks": api["forks_count"], "watchers": api.get("subscribers_count"),
                        "open_issues": api.get("open_issues_count"), "created": (api.get("created_at") or "")[:10],
                        "last_push": (api.get("pushed_at") or "")[:10]},
            "facts": {"language": api.get("language"), "license": (api.get("license") or {}).get("spdx_id"),
                      "topics": api.get("topics") or [], "homepage": api.get("homepage") or "", "latest_release": release},
            "subject": {"name": full, "owner": owner, "repo": full.split("/")[1], "platform": "github",
                        "avatar": f"https://github.com/{owner}.png?size=240", "url": api["html_url"]},
            "shots": [{"url": api["html_url"], "kind": "github"}], **parsed}


def _hf_avatar(org: str) -> str | None:
    for kind in ("organizations", "users"):
        try:
            data = net.json_get(f"https://huggingface.co/api/{kind}/{org}/avatar", tries=1)
            if data.get("avatarUrl"):
                url = data["avatarUrl"]
                return url if url.startswith("http") else f"https://huggingface.co{url}"
        except Exception:
            continue
    return None


def hf_model(mid: str) -> dict:
    api = net.json_get(f"https://huggingface.co/api/models/{mid}")
    try:
        card = net.text_get(f"https://huggingface.co/{mid}/raw/main/README.md")
    except Exception:
        card = ""
    parsed = _markdown(card, f"https://huggingface.co/{mid}/resolve/main/")
    meta = api.get("cardData") or {}
    params = (api.get("safetensors") or {}).get("total")
    org = mid.split("/")[0]
    return {"type": "huggingface", "url": f"https://huggingface.co/{mid}", "title": mid, "site": "Hugging Face",
            "about": api.get("pipeline_tag") or "", "published": api.get("createdAt"),
            "numbers": {"likes": api.get("likes"), "downloads_last_month": api.get("downloads"), "parameters": params,
                        "created": (api.get("createdAt") or "")[:10]},
            "facts": {"license": meta.get("license"), "pipeline": api.get("pipeline_tag"), "library": api.get("library_name"),
                      "tags": [t for t in api.get("tags", []) if ":" not in t][:12], "base_model": meta.get("base_model")},
            "subject": {"name": mid, "owner": org, "repo": mid.split("/")[1], "platform": "huggingface",
                        "avatar": _hf_avatar(org), "url": f"https://huggingface.co/{mid}"},
            "shots": [{"url": f"https://huggingface.co/{mid}", "kind": "huggingface"}], **parsed}


def hf_space(sid: str) -> dict:
    api = net.json_get(f"https://huggingface.co/api/spaces/{sid}")
    try:
        card = net.text_get(f"https://huggingface.co/spaces/{sid}/raw/main/README.md")
    except Exception:
        card = ""
    parsed = _markdown(card, f"https://huggingface.co/spaces/{sid}/resolve/main/")
    meta = api.get("cardData") or {}
    org = sid.split("/")[0]
    thumb = f"https://cdn-thumbnails.huggingface.co/social-thumbnails/spaces/{sid}.png"
    return {"type": "huggingface-space", "url": f"https://huggingface.co/spaces/{sid}", "title": meta.get("title") or sid,
            "site": "Hugging Face Spaces", "about": meta.get("short_description") or "", "published": api.get("createdAt"),
            "numbers": {"likes": api.get("likes")}, "facts": {"sdk": api.get("sdk"), "license": meta.get("license")},
            "subject": {"name": sid, "owner": org, "repo": sid.split("/")[1], "platform": "huggingface",
                        "avatar": _hf_avatar(org), "url": f"https://huggingface.co/spaces/{sid}"},
            "shots": [], **{**parsed, "images": [{"url": thumb, "alt": "Space preview"}] + parsed["images"]}}


def paper(pid: str) -> dict:
    api = net.json_get(f"https://huggingface.co/api/papers/{pid}")
    authors = [a.get("name") for a in api.get("authors", []) if a.get("name")]
    thumb = f"https://cdn-thumbnails.huggingface.co/social-thumbnails/papers/{pid}.png"
    return {"type": "paper", "url": f"https://arxiv.org/abs/{pid}", "title": api.get("title", ""), "site": "arXiv",
            "about": "", "published": api.get("publishedAt"), "text": (api.get("summary") or "")[:TEXT_LIMIT],
            "numbers": {"upvotes_on_hugging_face": api.get("upvotes"), "authors": len(authors)},
            "facts": {"authors": authors[:8], "github": api.get("githubRepo"), "project_page": api.get("projectPage"),
                      "ai_summary": api.get("ai_summary")},
            "subject": {"name": api.get("title", "")[:60], "owner": "arXiv " + pid, "platform": "paper", "avatar": None,
                        "url": f"https://arxiv.org/abs/{pid}"},
            "shots": [{"url": f"https://arxiv.org/abs/{pid}", "kind": "arxiv"}],
            "code": [], "images": [{"url": thumb, "alt": "Paper preview"}], "tables": []}


def article(url: str) -> dict:
    html = net.text_get(url, timeout=30)
    soup = BeautifulSoup(html, "html.parser")
    meta = trafilatura.extract_metadata(html)
    text = trafilatura.extract(html, include_tables=True, include_comments=False, favor_precision=True) or ""
    og = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "twitter:image"})
    images = [{"url": urljoin(url, og["content"]), "alt": "article image"}] if og and og.get("content") else []
    links = []
    for a in soup.select("a[href]"):
        href = a["href"]
        m = re.match(r"https?://(?:www\.)?github\.com/([\w.-]+/[\w.-]+)/?$", href)
        h = re.match(r"https?://huggingface\.co/([\w.-]+/[\w.-]+)/?$", href)
        if m and m.group(1).split("/")[0] not in ("features", "topics", "orgs", "sponsors", "about", "login", "settings"):
            links.append(("gh", m.group(1).removesuffix(".git")))
        elif h and h.group(1).split("/")[0] not in ("docs", "spaces", "datasets", "papers", "blog", "learn", "join"):
            links.append(("hf", h.group(1)))
    host = urlparse(url).netloc.removeprefix("www.")
    return {"type": "article", "url": url, "title": (meta.title if meta else "") or (soup.title.string if soup.title else ""),
            "site": (meta.sitename if meta and meta.sitename else host), "about": (meta.description if meta else "") or "",
            "published": meta.date if meta else None, "text": text[:TEXT_LIMIT], "numbers": {}, "facts": {},
            "subject": {"name": host, "owner": host, "platform": "web", "avatar": None, "url": url},
            "shots": [{"url": url, "kind": "article"}], "code": [], "images": images, "tables": [],
            "links": list(dict.fromkeys(links))[:6]}


def hn_discussion(hn_id: str) -> dict:
    data = net.json_get(f"https://hn.algolia.com/api/v1/items/{hn_id}")
    comments = []
    for child in data.get("children", [])[:30]:
        text = BeautifulSoup(child.get("text") or "", "html.parser").get_text(" ", strip=True)
        if 60 <= len(text) <= 420:
            comments.append(text)
        if len(comments) >= 6:
            break
    return {"type": "hn", "url": f"https://news.ycombinator.com/item?id={hn_id}", "title": data.get("title", ""),
            "site": "Hacker News", "about": "", "published": data.get("created_at"),
            "numbers": {"points": data.get("points")}, "facts": {"top_comments": comments}, "text": "",
            "subject": None, "shots": [], "code": [], "images": [], "tables": []}


def openrouter(model_id: str) -> dict:
    data = net.json_get("https://openrouter.ai/api/v1/models")
    model = next((m for m in data.get("data", []) if m["id"] == model_id), None) or {}
    price = model.get("pricing") or {}
    per_m = {k: round(float(v) * 1e6, 3) for k, v in price.items() if k in ("prompt", "completion") and v not in (None, "")}
    return {"type": "openrouter", "url": f"https://openrouter.ai/{model_id}", "title": model.get("name", model_id),
            "site": "OpenRouter", "about": "", "published": None, "text": (model.get("description") or "")[:2000],
            "numbers": {"context_tokens": model.get("context_length"), "usd_per_million_input_tokens": per_m.get("prompt"),
                        "usd_per_million_output_tokens": per_m.get("completion")},
            "facts": {"modalities": (model.get("architecture") or {}).get("input_modalities")},
            "subject": None, "shots": [], "code": [], "images": [], "tables": []}


def _one(item: dict) -> list[dict]:
    key, url = item["key"], item["url"]
    out = []
    if key.startswith("gh:"):
        out.append(github(item["title"]))
    elif key.startswith("hf:"):
        out.append(hf_model(item["title"]))
    elif key.startswith("hfs:"):
        out.append(hf_space(item["title"]))
    elif key.startswith("paper:"):
        out.append(paper(key.split(":", 1)[1]))
    elif key.startswith("or:"):
        out.append(openrouter(key.split(":", 1)[1]))
    elif "news.google.com" in url or "reddit.com" in url:
        out.append({"type": "headline", "url": url, "title": item["title"], "site": item["label"], "about": "",
                    "published": item.get("published"), "text": item.get("summary", ""), "numbers": {}, "facts": {},
                    "subject": None, "shots": [], "code": [], "images": [], "tables": []})
    else:
        out.append(article(url))
    hn_id = item.get("signals", {}).get("hn_id")
    if hn_id:
        out.append(hn_discussion(str(hn_id)))
    return out


def dossier(pick: dict) -> dict:
    """Everything the writer may say, with where each part came from."""
    sources, done = [], set()
    for item in pick["items"][:4]:
        try:
            for src in _one(item):
                if src["url"] not in done:
                    done.add(src["url"])
                    src["scout"] = {"label": item["label"], "signals": item.get("signals", {}), "heat": item["heat"]}
                    sources.append(src)
        except Exception as exc:
            log.info("research %s failed: %s", item["url"], exc)
    # An article about a repo or a model: read the repo or the model card too.
    for src in list(sources):
        for kind, ref in src.get("links", [])[:2]:
            try:
                extra = github(ref) if kind == "gh" else hf_model(ref)
            except Exception:
                continue
            if extra["url"] not in done:
                done.add(extra["url"])
                sources.append(extra)
    if not sources:
        raise RuntimeError("no source could be read")
    subject = next((s["subject"] for s in sources if s.get("subject") and s["type"] in ("github", "huggingface")), None) \
        or next((s["subject"] for s in sources if s.get("subject")), None)
    return {"story": pick["story"], "angle": pick["angle"], "format": pick["format"], "subject": subject,
            "sources": sources}
