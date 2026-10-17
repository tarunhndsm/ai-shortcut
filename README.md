# AI Shortcut desk

An automated newsroom for the [AI Shortcut](https://www.youtube.com/@AIShortcut-p4k) YouTube channel. It finds what is
trending in AI right now (repos, models, papers, launches, posts) and turns the best story into a 40-45 second
animated Short. Everything runs on GitHub Actions; nothing is rendered on a laptop.

## The desk

| Stage | Agents | What they do |
|---|---|---|
| Scouts | 39 | GitHub trending (6 languages) and new rising repos, Hugging Face models, Spaces and daily papers, Hacker News, 11 lab blogs (OpenAI, Google, Google Research, DeepMind, Microsoft Research, Meta, Mistral, NVIDIA, Hugging Face, AWS, GitHub), Anthropic's news page, 12 tech news feeds and newsletters (including Techmeme, TLDR AI and Latent Space), Product Hunt, Lobsters, one subreddit per scan in turn, OpenRouter's new models. Each item gets a heat score from its own signal (stars today, points, likes) and freshness, plus a boost when several independent sources carry the same thing. |
| Editor | 1 | Groups items that are the same story and picks the three best for a broad tech audience, skipping anything covered in the last 10 days, rumors, drama and NSFW. |
| Researcher | 1 per source | Reads the primary sources: repo API, README, releases, model cards, papers, articles, the top Hacker News comments, OpenRouter pricing. |
| Picture desk | 1 | Screenshots of the real pages (Playwright), the README's own images, the maker's avatar. |
| Writer and fact-checker | 2 | Gemini writes a 6-8 scene script from the dossier only; a second pass checks every claim, and code checks every on-screen number against the dossier. |
| Narrator | 1 | Gemini TTS, aligned word by word with Whisper for karaoke captions; Kokoro as the offline fallback. |
| Composer and sound | 2 | Builds a HyperFrames (HTML + GSAP) project from 12 scene types (hook, card, stat, bars, list, code, shot, media, versus, quote, punch, cta) with rolling counters, typing code, browser-frame pans and karaoke captions; mixes a synthesized music bed and sound effects to -14 LUFS. |
| Renderer and judge | 2 | HyperFrames renders 1080x1920 at 30 fps; technical checks plus a vision judge that looks at frames from every scene and blocks broken or misleading Shorts. |
| Publisher | 1 | Posts through Buffer to YouTube, and to Instagram and Facebook when connected, at the best slots. |

## Schedule

`desk.yml` runs every 30 minutes, dispatched by `clock.yml`. GitHub's cron fires this account's schedules only every
few hours, so each clock tick waits out the 30-minute wait timer of the `clock` environment (no runner is held), then
dispatches the desk and the next tick; both workflows keep a cron that restarts the chain if it ever stops. A light
plan step posts a ready Short when a slot is due and decides whether to make the next one (about three hours before
its slot). Slots, India time: 06:00 (the US evening and India's best morning
window) and 20:00 (India's evening, the US morning). A story that is hot, under 8 hours old and carried by at least
three kinds of sources is made and posted at once instead, at most once a day and at least 90 minutes after the last
post. At most three Shorts a day.

## Secrets

| Secret | What |
|---|---|
| `AI_GEMINI_API_KEY` | Gemini API key from the channel's own Google AI Studio project |
| `AI_BUFFER_API_KEY` | Buffer API key of the channel's own Buffer account |
| `AI_BUFFER_YOUTUBE_ID` | Buffer channel id of the YouTube channel |
| `AI_BUFFER_INSTAGRAM_ID`, `AI_BUFFER_FACEBOOK_ID` | Optional: Buffer channel ids of the Instagram account and Facebook Page |

Until the Buffer secrets are set, the desk makes Shorts and keeps them in the `media` release, but posts nothing.

## Commands

```bash
python -m desk.run board                 # the scouts' board, hottest first
python -m desk.run make --url <url>      # one Short about a given repo, model or article (cloud only)
python -m desk.run status                # what was made and posted
gh workflow run desk.yml -f command=make # make one now in the cloud
```

## Policy

Every claim comes from primary sources and is checked before rendering. Visuals are screenshots and images of the
subject's own pages, shown as commentary. The music and sound effects are synthesized, so there is nothing to claim.
Descriptions say the Short was researched, written and narrated with AI tools. Cadence stays moderate (at most four
Shorts a day) and each Short covers a different story.
