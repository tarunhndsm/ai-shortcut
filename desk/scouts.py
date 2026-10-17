"""The scouts: one per source, each returning what is trending there now, scored 0-100 for heat.

GitHub's trending pages and fastest-rising new repos, Hugging Face's trending models, Spaces and papers, Hacker
News, Reddit's AI communities, the AI labs' own blogs, the AI desks of tech news sites, Product Hunt's AI launches,
and models newly listed on OpenRouter. A story that several scouts report gets hotter.

python -m desk.scouts            print the board
"""

from __future__ import annotations

import concurrent.futures as cf
import logging
import math
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse, urlunparse

import feedparser
from bs4 import BeautifulSoup

from . import net, state

log = logging.getLogger(__name__)

AI = re.compile(
    r"(?i)\b(ai|a\.i\.|llms?|gpts?|gpt-?\d[\w.-]*|agents?|agentic|rag|mcp|models?|diffusion|transformers?|neural|"
    r"machine learning|deep learning|inference|embeddings?|vector|prompts?|chatbots?|claude|openai|anthropic|gemini|"
    r"gemma|llama|qwen|deepseek|mistral|grok|kimi|glm|minimax|phi-?\d|whisper|tts|text-to-speech|speech|voice|"
    r"vision|ocr|copilot|cursor|codex|devin|autonomous|image generation|video generation|text-to-video|"
    r"text-to-image|lora|fine-?tun\w*|vllm|gguf|ollama|langchain|llamaindex|hugging ?face|multimodal|reasoning|"
    r"benchmark|evals?|sora|veo|midjourney|stable diffusion|flux|comfyui|nvidia|gpu|cuda|robot\w*|humanoid|"
    r"chatgpt|perplexity|notebooklm|semantic|tokens?|context window|open-?weights?|open-?source model|"
    r"generative|genai|deepfake|alignment|agi|asi|superintelligence)\b")
# Labs and major model makers: a post on their own blog is an announcement.
LAB_FEEDS = {
    "openai": ("OpenAI", "https://openai.com/news/rss.xml"),
    "google-ai": ("Google AI", "https://blog.google/technology/ai/rss/"),
    "deepmind": ("Google DeepMind", "https://deepmind.google/blog/rss.xml"),
    "nvidia": ("NVIDIA", "https://blogs.nvidia.com/feed/"),
    "huggingface": ("Hugging Face", "https://huggingface.co/blog/feed.xml"),
    "aws-ml": ("AWS Machine Learning", "https://aws.amazon.com/blogs/machine-learning/feed/"),
    "github-blog": ("GitHub", "https://github.blog/feed/"),
}
LAB_PAGES = {
    "anthropic": ("Anthropic", "https://www.anthropic.com/news", r"^/news/[\w-]+$"),
    "mistral": ("Mistral AI", "https://mistral.ai/news", r"^/news/[\w-]+/?$"),
}
NEWS_FEEDS = {
    "techcrunch": ("TechCrunch", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    "verge": ("The Verge", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    "ars": ("Ars Technica", "https://arstechnica.com/ai/feed/"),
    "wired": ("WIRED", "https://www.wired.com/feed/tag/ai/latest/rss"),
    "mit-tr": ("MIT Technology Review", "https://www.technologyreview.com/topic/artificial-intelligence/feed"),
    "decoder": ("The Decoder", "https://the-decoder.com/feed/"),
    "marktechpost": ("MarkTechPost", "https://www.marktechpost.com/feed/"),
    "simonw": ("Simon Willison", "https://simonwillison.net/atom/everything/"),
    "google-news": ("Google News", "https://news.google.com/rss/search?q=artificial+intelligence+when:1d&hl=en-US&gl=US&ceid=US:en"),
}
COMMUNITY_FEEDS = {
    "producthunt": ("Product Hunt", "https://www.producthunt.com/feed?category=artificial-intelligence"),
    "lobsters": ("Lobsters", "https://lobste.rs/t/ai.rss"),
}
SUBREDDITS = ("LocalLLaMA", "singularity", "OpenAI", "ClaudeAI", "StableDiffusion", "ChatGPT")
TRENDING = {"all": "", "python": "/python", "typescript": "/typescript", "jupyter": "/jupyter-notebook",
            "rust": "/rust", "go": "/go"}
MAJOR_MAKERS = ("openai", "anthropic", "google", "meta-llama", "mistralai", "deepseek", "qwen", "x-ai", "moonshotai",
                "z-ai", "minimax", "nvidia", "microsoft", "amazon", "cohere", "baidu", "tencent", "bytedance", "alibaba",
                "ai21", "perplexity", "inception", "stepfun", "xiaomi", "ibm-granite", "liquid", "arcee-ai")


def _canon(url: str) -> str:
    parts = urlparse(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    return urlunparse((parts.scheme or "https", host, parts.path.rstrip("/"), "", "", ""))


def _heat(value: float, scale: float = 22.0, base: float = 8.0) -> float:
    return max(0.0, min(100.0, base + scale * math.log10(1 + max(value, 0))))


def _fresh(published: datetime | None, half_life_h: float = 18.0) -> float:
    if not published:
        return 0.6
    hours = max(0.0, (state.now() - published).total_seconds() / 3600)
    return 0.5 ** (hours / half_life_h)


def _when(entry) -> datetime | None:
    for field in ("published_parsed", "updated_parsed"):
        value = entry.get(field)
        if value:
            return datetime(*value[:6], tzinfo=timezone.utc)
    for field in ("published", "updated"):
        try:
            return parsedate_to_datetime(entry[field]).astimezone(timezone.utc)
        except (KeyError, TypeError, ValueError):
            continue
    return None


def _clean(html: str, limit: int = 400) -> str:
    text = BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text)[:limit]


def _item(source: str, label: str, kind: str, title: str, url: str, heat: float, summary: str = "",
          published: datetime | None = None, entity: str = "", **signals) -> dict:
    return {"key": entity or _canon(url), "source": source, "label": label, "kind": kind, "title": title.strip(),
            "url": url, "summary": summary.strip(), "published": state.iso(published) if published else None,
            "heat": round(heat, 1), "entity": entity, "signals": {k: v for k, v in signals.items() if v is not None}}


def github_trending(name: str, path: str) -> list[dict]:
    html = net.text_get(f"https://github.com/trending{path}?since=daily")
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for rank, row in enumerate(soup.select("article.Box-row")):
        link = row.select_one("h2 a")
        if not link:
            continue
        full = link["href"].strip("/")
        desc = row.select_one("p")
        about = desc.get_text(" ", strip=True) if desc else ""
        if not AI.search(f"{full.replace('-', ' ')} {about}"):
            continue
        today = re.search(r"([\d,]+) stars? (today|this week)", row.get_text(" ", strip=True))
        stars_today = int(today.group(1).replace(",", "")) if today else 0
        total = row.select_one('a[href$="/stargazers"]')
        stars = int(re.sub(r"\D", "", total.get_text()) or 0) if total else None
        lang = row.select_one('[itemprop="programmingLanguage"]')
        items.append(_item(f"github-trending-{name}", f"GitHub Trending ({name})", "repo", full,
                           f"https://github.com/{full}", _heat(stars_today) - rank * 0.3, about,
                           entity=f"gh:{full.lower()}", stars_today=stars_today, stars=stars,
                           language=lang.get_text(strip=True) if lang else None, rank=rank + 1))
    return items


def github_rising() -> list[dict]:
    since = (state.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    data = net.json_get("https://api.github.com/search/repositories",
                        params={"q": f"created:>{since} stars:>150", "sort": "stars", "order": "desc", "per_page": 50},
                        headers=net.github_headers())
    items = []
    for repo in data.get("items", []):
        about = repo.get("description") or ""
        topics = " ".join(repo.get("topics") or [])
        if not AI.search(f"{repo['full_name'].replace('-', ' ')} {about} {topics}"):
            continue
        created = state.parse(repo.get("created_at"))
        days = max(0.5, (state.now() - created).total_seconds() / 86400) if created else 5
        rate = repo["stargazers_count"] / days
        items.append(_item("github-rising", "GitHub: fastest-rising new repos", "repo", repo["full_name"],
                           repo["html_url"], _heat(rate) - 2, about, created, entity=f"gh:{repo['full_name'].lower()}",
                           stars=repo["stargazers_count"], stars_per_day=round(rate), language=repo.get("language")))
    return items


def hf_models() -> list[dict]:
    data = net.json_get("https://huggingface.co/api/models", params={"sort": "trendingScore", "limit": 40})
    items = []
    for rank, model in enumerate(data):
        mid = model["id"]
        score = model.get("trendingScore") or 0
        items.append(_item("hf-models", "Hugging Face trending models", "model", mid, f"https://huggingface.co/{mid}",
                           _heat(score, 24, 6) - rank * 0.4, model.get("pipeline_tag") or "",
                           state.parse(model.get("createdAt")), entity=f"hf:{mid.lower()}", likes=model.get("likes"),
                           downloads=model.get("downloads"), trending_score=score, rank=rank + 1))
    return items


def hf_spaces() -> list[dict]:
    data = net.json_get("https://huggingface.co/api/spaces", params={"sort": "trendingScore", "limit": 30})
    items = []
    for rank, space in enumerate(data):
        sid = space["id"]
        score = space.get("trendingScore") or 0
        items.append(_item("hf-spaces", "Hugging Face trending Spaces (demos)", "demo", sid,
                           f"https://huggingface.co/spaces/{sid}", _heat(score, 22, 4) - rank * 0.4,
                           space.get("title") or "", state.parse(space.get("createdAt")), entity=f"hfs:{sid.lower()}",
                           likes=space.get("likes"), trending_score=score, rank=rank + 1))
    return items


def hf_papers() -> list[dict]:
    data = net.json_get("https://huggingface.co/api/daily_papers", params={"limit": 50})
    items = []
    for entry in data:
        paper = entry.get("paper", {})
        pid = paper.get("id")
        if not pid:
            continue
        upvotes = paper.get("upvotes") or 0
        items.append(_item("hf-papers", "Hugging Face daily papers", "paper", paper.get("title") or entry.get("title", ""),
                           f"https://huggingface.co/papers/{pid}", _heat(upvotes, 26, 2),
                           (paper.get("summary") or "")[:500], state.parse(entry.get("publishedAt")),
                           entity=f"paper:{pid}", upvotes=upvotes, comments=entry.get("numComments"),
                           github=paper.get("githubRepo"), thumbnail=entry.get("thumbnail")))
    return items


def hacker_news() -> list[dict]:
    since = int(time.time()) - 36 * 3600
    data = net.json_get("https://hn.algolia.com/api/v1/search",
                        params={"tags": "story", "numericFilters": f"created_at_i>{since},points>40", "hitsPerPage": 100})
    items = []
    for hit in data.get("hits", []):
        title = hit.get("title") or ""
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}"
        if not AI.search(f"{title} {url}"):
            continue
        published = datetime.fromtimestamp(hit["created_at_i"], timezone.utc)
        points = hit.get("points") or 0
        items.append(_item("hacker-news", "Hacker News", "link", title, url,
                           _heat(points, 22, 14) * (0.55 + 0.45 * _fresh(published, 24)), "", published,
                           points=points, comments=hit.get("num_comments"), hn_id=hit["objectID"]))
    return items


def _feed(source: str, label: str, url: str, kind: str, base: float, need_ai: bool, half_life: float) -> list[dict]:
    parsed = feedparser.parse(net.get(url, timeout=30).content)
    items = []
    for rank, entry in enumerate(parsed.entries[:40]):
        title = _clean(entry.get("title", ""), 200)
        link = entry.get("link", "")
        summary = _clean(entry.get("summary", ""))
        published = _when(entry)
        if not title or not link or (published and state.now() - published > timedelta(days=4)):
            continue
        if need_ai and not AI.search(f"{title} {summary}"):
            continue
        heat = base * _fresh(published, half_life) - rank * 0.5
        extra = {}
        if source == "google-news":
            src = entry.get("source", {})
            extra["outlet"] = src.get("title") if isinstance(src, dict) else None
        items.append(_item(source, label, kind, title, link, heat, summary, published, **extra))
    return items


def lab_feed(source: str) -> list[dict]:
    label, url = LAB_FEEDS[source]
    return _feed(source, f"{label} blog", url, "announcement", 80, source in ("nvidia", "aws-ml", "github-blog"), 20)


def news_feed(source: str) -> list[dict]:
    label, url = NEWS_FEEDS[source]
    return _feed(source, label, url, "news", 58 if source != "simonw" else 66, source in ("simonw",), 16)


def community_feed(source: str) -> list[dict]:
    label, url = COMMUNITY_FEEDS[source]
    return _feed(source, label, url, "launch" if source == "producthunt" else "link", 52, source == "lobsters", 20)


def lab_page(source: str) -> list[dict]:
    """Labs without a feed: their news index, newest first. Dates come from when a scout first saw each post."""
    label, url, pattern = LAB_PAGES[source]
    soup = BeautifulSoup(net.text_get(url), "html.parser")
    seen, items = state.seen(), []
    # On a source's first scan every post on its index is already out: those count as old news.
    first_scan = f"scanned:{source}" not in seen
    for link in soup.select("a[href]"):
        href = link["href"].split("?")[0]
        path = urlparse(href).path if href.startswith("http") else href
        if not re.match(pattern, path) or len(items) >= 10:
            continue
        full = urljoin(url, path)
        if any(i["url"] == full for i in items):
            continue
        title = re.sub(r"\s+", " ", link.get_text(" ", strip=True))[:180]
        first = state.parse(seen.get(_canon(full)))
        published = first or (state.now() - timedelta(days=5) if first_scan else state.now())
        item = _item(source, f"{label} news", "announcement", title or path.rsplit("/", 1)[-1], full,
                     80 * _fresh(published, 20) - len(items) * 0.5, "", published)
        item["first_seen"] = state.iso(published)
        items.append(item)
    return items


def reddit() -> list[dict]:
    items = []
    for sub in SUBREDDITS:
        try:
            parsed = feedparser.parse(net.get(f"https://www.reddit.com/r/{sub}/top/.rss?t=day", timeout=20,
                                              headers={"User-Agent": "linux:ai-shortcut-desk:1.0 (by /u/aishortcut)"}).content)
        except Exception as exc:  # Reddit often refuses cloud IPs; the other scouts carry on.
            log.info("reddit r/%s: %s", sub, exc)
            time.sleep(2)
            continue
        for rank, entry in enumerate(parsed.entries[:12]):
            title = _clean(entry.get("title", ""), 200)
            published = _when(entry)
            if not title or (published and state.now() - published > timedelta(hours=36)):
                continue
            items.append(_item(f"reddit-{sub.lower()}", f"Reddit r/{sub}", "discussion", title, entry.get("link", ""),
                               (62 - rank * 2.2) * (0.6 + 0.4 * _fresh(published, 18)), _clean(entry.get("summary", "")),
                               published, rank=rank + 1))
        time.sleep(7)
    return items


def openrouter() -> list[dict]:
    data = net.json_get("https://openrouter.ai/api/v1/models")
    items = []
    for model in data.get("data", []):
        maker = model["id"].split("/", 1)[0]
        created = datetime.fromtimestamp(model.get("created") or 0, timezone.utc)
        if maker not in MAJOR_MAKERS or state.now() - created > timedelta(days=3):
            continue
        items.append(_item("openrouter", "New on OpenRouter", "model", model.get("name") or model["id"],
                           f"https://openrouter.ai/{model['id']}", 64 * _fresh(created, 24),
                           (model.get("description") or "")[:400], created, entity=f"or:{model['id']}",
                           context=model.get("context_length")))
    return items


def scouts() -> dict:
    jobs = {f"github-trending-{k}": (github_trending, (k, v)) for k, v in TRENDING.items()}
    jobs |= {"github-rising": (github_rising, ()), "hf-models": (hf_models, ()), "hf-spaces": (hf_spaces, ()),
             "hf-papers": (hf_papers, ()), "hacker-news": (hacker_news, ()), "openrouter": (openrouter, ()),
             "reddit": (reddit, ())}
    jobs |= {k: (lab_feed, (k,)) for k in LAB_FEEDS}
    jobs |= {k: (lab_page, (k,)) for k in LAB_PAGES}
    jobs |= {k: (news_feed, (k,)) for k in NEWS_FEEDS}
    jobs |= {k: (community_feed, (k,)) for k in COMMUNITY_FEEDS}
    return jobs


# Names too common to tie two items to one story.
_GENERIC = set("""openai anthropic google deepmind meta microsoft nvidia apple amazon github hugging huggingface claude
chatgpt gemini copilot cursor python typescript javascript rust golang linux windows macos android iphone agent agents
model models llm llms code coding open source opensource reddit news""".split())
BLOCK = re.compile(r"(?i)\b(nsfw|porn\w*|nude\w*|naked|hentai|erotic\w*|sexual|onlyfans|undress\w*|deepnude|"
                   r"jailbreak\w*|crack(ed)?|keygen|stealer|malware|ransomware|phishing|casino|betting|gambl\w*)\b")


def _names(item: dict) -> set[str]:
    """Distinctive product names in an item: tokens with a digit (gpt-5.5, v4.1, qwen3.8), CamelCase (DeepSeek,
    MiniCPM), and a repo's or model's own name."""
    text = f"{item['title'].replace('/', ' ')} {item['summary'][:160]}"
    names = set()
    for word in re.findall(r"[A-Za-z][A-Za-z0-9.+_-]{2,}", text):
        low = word.lower().strip(".-_")
        if low in _GENERIC or len(low) < 4:
            continue
        if (any(c.isdigit() for c in word) and any(c.isalpha() for c in word)) or re.search(r"[a-z][A-Z]", word):
            names.add(low)
    if item["kind"] in ("repo", "model", "demo") and "/" in item["title"]:
        own = item["title"].split("/", 1)[1].lower()
        if len(own) >= 5 and own not in _GENERIC:
            names.add(own)
    return names


def _cross_boost(items: list[dict]) -> None:
    """A story several kinds of scouts report is hotter: +6 per other kind naming the same product, up to +18."""
    names = [_names(i) for i in items]
    family = [i["source"].split("-")[0] for i in items]
    counts: dict[str, set[str]] = {}
    for fam, found in zip(family, names):
        for name in found:
            counts.setdefault(name, set()).add(fam)
    for item, fam, found in zip(items, family, names):
        others = {s for n in found if 2 <= len(counts[n]) <= 8 for s in counts[n]} - {fam}
        if others:
            item["heat"] = round(min(100.0, item["heat"] + 6 * min(3, len(others))), 1)
            item["also_on"] = sorted(others)


def scan(workers: int = 12) -> list[dict]:
    """Every scout's items, deduplicated by key (the hottest copy kept), hottest first."""
    jobs = scouts()
    found: list[dict] = []
    report = {}
    with cf.ThreadPoolExecutor(workers) as pool:
        futures = {pool.submit(fn, *args): name for name, (fn, args) in jobs.items()}
        for future in cf.as_completed(futures):
            name = futures[future]
            try:
                got = future.result()
                report[name] = len(got)
                found += got
            except Exception as exc:
                report[name] = f"failed: {type(exc).__name__}"
                log.info("scout %s failed: %s", name, exc)
    found = [i for i in found if not BLOCK.search(f"{i['title']} {i['summary'][:300]}")]
    _cross_boost(found)
    best: dict[str, dict] = {}
    for item in found:
        if item["key"] not in best or item["heat"] > best[item["key"]]["heat"]:
            best[item["key"]] = item
    stamps = {f"scanned:{name}": None for name, count in report.items() if isinstance(count, int)}
    for item in found:
        stamps.setdefault(_canon(item["url"]), item.pop("first_seen", None))
    state.mark_seen(stamps)
    log.info("scouts: %s", report)
    return sorted(best.values(), key=lambda i: -i["heat"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    board = scan()
    for item in board[:60]:
        sig = ", ".join(f"{k}={v}" for k, v in item["signals"].items() if k in ("stars_today", "stars", "points", "upvotes",
                                                                                "likes", "rank", "trending_score"))
        print(f"{item['heat']:5.1f}  {item['label'][:28]:28}  {item['title'][:70]:70}  {sig}  {item.get('also_on', '')}")
    print(len(board), "items")
