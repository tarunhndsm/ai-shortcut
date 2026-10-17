"""Probe candidate trend sources: HTTP status, size, and a hint of what came back."""

import concurrent.futures as cf
import time
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"
DAY = int(time.time()) - 86400
URLS = {
    "gh-trending": "https://github.com/trending?since=daily",
    "gh-trending-py": "https://github.com/trending/python?since=daily",
    "gh-search": f"https://api.github.com/search/repositories?q=created:>{time.strftime('%Y-%m-%d', time.gmtime(time.time()-7*86400))}+stars:>200&sort=stars&order=desc&per_page=30",
    "hf-models": "https://huggingface.co/api/models?sort=trendingScore&limit=30",
    "hf-spaces": "https://huggingface.co/api/spaces?sort=trendingScore&limit=30",
    "hf-papers": "https://huggingface.co/api/daily_papers?limit=30",
    "hn": f"https://hn.algolia.com/api/v1/search?tags=story&numericFilters=created_at_i>{DAY},points>30&hitsPerPage=100",
    "reddit-localllama": "https://www.reddit.com/r/LocalLLaMA/top/.rss?t=day",
    "reddit-singularity": "https://www.reddit.com/r/singularity/top/.rss?t=day",
    "reddit-openai": "https://www.reddit.com/r/OpenAI/top/.rss?t=day",
    "reddit-claudeai": "https://www.reddit.com/r/ClaudeAI/top/.rss?t=day",
    "reddit-ml": "https://www.reddit.com/r/MachineLearning/top/.rss?t=day",
    "reddit-artificial": "https://www.reddit.com/r/artificial/top/.rss?t=day",
    "openai": "https://openai.com/news/rss.xml",
    "google-ai": "https://blog.google/technology/ai/rss/",
    "deepmind": "https://deepmind.google/blog/rss.xml",
    "anthropic": "https://www.anthropic.com/news",
    "meta-ai": "https://ai.meta.com/blog/",
    "mistral": "https://mistral.ai/news",
    "nvidia": "https://blogs.nvidia.com/feed/",
    "microsoft-ai": "https://blogs.microsoft.com/ai/feed/",
    "hf-blog": "https://huggingface.co/blog/feed.xml",
    "aws-ml": "https://aws.amazon.com/blogs/machine-learning/feed/",
    "techcrunch-ai": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "verge-ai": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "venturebeat-ai": "https://venturebeat.com/category/ai/feed/",
    "arstechnica-ai": "https://arstechnica.com/ai/feed/",
    "wired-ai": "https://www.wired.com/feed/tag/ai/latest/rss",
    "mit-tr-ai": "https://www.technologyreview.com/topic/artificial-intelligence/feed",
    "the-decoder": "https://the-decoder.com/feed/",
    "marktechpost": "https://www.marktechpost.com/feed/",
    "simonw": "https://simonwillison.net/atom/everything/",
    "producthunt": "https://www.producthunt.com/feed?category=artificial-intelligence",
    "lobsters-ai": "https://lobste.rs/t/ai.rss",
    "arxiv-cs-ai": "https://rss.arxiv.org/rss/cs.AI",
    "github-blog": "https://github.blog/feed/",
    "google-news-ai": "https://news.google.com/rss/search?q=artificial+intelligence+when:1d&hl=en-US&gl=US&ceid=US:en",
    "bsky-search": "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?q=AI%20model&sort=top&limit=25",
    "devto-ai": "https://dev.to/api/articles?tag=ai&top=1&per_page=30",
    "npm-ai": "https://registry.npmjs.org/-/v1/search?text=keywords:ai&popularity=1.0&size=20",
    "pypi-rss": "https://pypi.org/rss/packages.xml",
    "ollama": "https://ollama.com/library?sort=newest",
    "lmarena": "https://lmarena.ai/leaderboard",
    "openrouter": "https://openrouter.ai/api/v1/models",
}


def probe(item):
    name, url = item
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            body = r.read()
            return name, r.status, len(body), round(time.time() - started, 1), body[:90].decode("utf-8", "replace").replace("\n", " ")
    except urllib.error.HTTPError as e:
        return name, e.code, 0, round(time.time() - started, 1), ""
    except Exception as e:
        return name, "ERR", 0, round(time.time() - started, 1), type(e).__name__ + ": " + str(e)[:60]


with cf.ThreadPoolExecutor(16) as pool:
    for name, status, size, secs, head in sorted(pool.map(probe, URLS.items()), key=lambda r: str(r[1])):
        print(f"{name:20} {status!s:4} {size:>8} {secs:>5}s  {head[:70]}")
