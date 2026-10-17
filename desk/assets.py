"""The picture desk: the subject's avatar, real screenshots of its page, and the images its README or article
shows, downloaded, checked and resized for the template. Screenshots need Playwright's Chromium (in CI)."""

from __future__ import annotations

import io
import logging
from pathlib import Path

from PIL import Image, ImageOps, ImageStat

from . import net

log = logging.getLogger(__name__)

HIDE = """[id*="cookie" i],[class*="cookie" i],[id*="consent" i],[class*="consent" i],#onetrust-consent-sdk,
.fc-consent-root,[aria-label*="cookie" i],[class*="newsletter" i],[class*="paywall" i],[id*="paywall" i],
[class*="modal" i][class*="subscribe" i],.signup-prompt,.js-signup-prompt,[data-testid*="banner" i]
{display:none !important;visibility:hidden !important}"""


def _save(img: Image.Image, dest: Path, max_w: int = 1600) -> dict:
    img = ImageOps.exif_transpose(img).convert("RGB")
    if img.width > max_w:
        img = img.resize((max_w, round(img.height * max_w / img.width)), Image.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, quality=90)
    return {"file": f"assets/{dest.name}", "w": img.width, "h": img.height}


def image(url: str, dest: Path, min_w: int = 420, min_h: int = 220) -> dict | None:
    """A usable picture from `url`, or None: big enough, not a banner strip, not blank."""
    try:
        resp = net.get(url, timeout=30, tries=1)
        if len(resp.content) > 25_000_000:
            return None
        img = Image.open(io.BytesIO(resp.content))
        if getattr(img, "n_frames", 1) > 1:
            img.seek(min(img.n_frames - 1, img.n_frames // 3))
        img = img.convert("RGBA")
        flat = Image.new("RGBA", img.size, (13, 17, 23, 255))
        flat.alpha_composite(img)
        img = flat.convert("RGB")
    except Exception as exc:
        log.info("image %s: %s", url, exc)
        return None
    ratio = img.width / max(img.height, 1)
    if img.width < min_w or img.height < min_h or ratio > 3.6 or ratio < 0.3:
        return None
    if max(ImageStat.Stat(img.convert("L")).stddev) < 9:
        return None
    return _save(img, dest)


def avatar(url: str | None, dest: Path) -> str | None:
    if not url:
        return None
    try:
        img = Image.open(io.BytesIO(net.get(url, timeout=20, tries=1).content)).convert("RGBA")
    except Exception:
        return None
    side = min(img.size)
    img = img.crop(((img.width - side) // 2, (img.height - side) // 2, (img.width + side) // 2, (img.height + side) // 2))
    bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
    bg.alpha_composite(img)
    bg.convert("RGB").resize((240, 240), Image.LANCZOS).save(dest)
    return f"assets/{dest.name}"


def screenshots(targets: list[dict], folder: Path) -> list[dict]:
    """Screenshots of each target page (dark mode, 960 px wide at 2x), cookie and sign-up banners hidden."""
    if not targets:
        return []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.info("no Playwright here; skipping screenshots")
        return []
    shots = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--disable-gpu", "--use-mock-keychain", "--password-store=basic"])
        ctx = browser.new_context(viewport={"width": 960, "height": 1300}, device_scale_factor=2, color_scheme="dark",
                                  user_agent=net.UA, locale="en-US")
        for n, target in enumerate(targets[:3]):
            page = ctx.new_page()
            try:
                page.goto(target["url"], wait_until="domcontentloaded", timeout=35000)
                page.wait_for_timeout(3500)
                page.add_style_tag(content=HIDE)
                page.wait_for_timeout(400)
                dest = folder / f"shot{n}.png"
                page.screenshot(path=str(dest), full_page=False)
                img = Image.open(dest)
                if max(ImageStat.Stat(img.convert("L")).stddev) >= 12:
                    shots.append({**_save(img, folder / f"shot{n}.jpg", 1920), "kind": "screenshot",
                                  "what": f"screenshot of {target['url']}", "url": target["url"]})
                if target.get("kind") == "github":
                    readme = page.locator("article.markdown-body").first
                    if readme.count():
                        readme.scroll_into_view_if_needed(timeout=5000)
                        page.wait_for_timeout(1500)
                        dest = folder / f"shot{n}r.png"
                        readme.screenshot(path=str(dest), timeout=20000)
                        img = Image.open(dest)
                        img = img.crop((0, 0, img.width, min(img.height, round(img.width * 1.45))))
                        if img.height > 500:
                            shots.append({**_save(img, folder / f"shot{n}r.jpg", 1920), "kind": "screenshot",
                                          "what": f"the README of {target['url']}", "url": target["url"]})
            except Exception as exc:
                log.info("screenshot %s: %s", target["url"], exc)
            finally:
                page.close()
        browser.close()
    return shots


def gather(dossier: dict, folder: Path) -> tuple[list[dict], str | None]:
    """The visuals the writer may use (screenshots and images, numbered) and the subject's avatar file."""
    folder.mkdir(parents=True, exist_ok=True)
    targets = [shot for src in dossier["sources"] for shot in src.get("shots", [])]
    visuals = screenshots(targets, folder)
    n = 0
    for src in dossier["sources"]:
        for img in src.get("images", [])[:5]:
            got = image(img["url"], folder / f"img{n}.jpg")
            n += 1
            if got:
                visuals.append({**got, "kind": "image", "what": f"{img.get('alt') or 'image'} (from {src.get('site')})",
                                "url": img["url"]})
            if sum(v["kind"] == "image" for v in visuals) >= 5:
                break
    subject = dossier.get("subject") or {}
    face = avatar(subject.get("avatar"), folder / "avatar.png")
    for i, v in enumerate(visuals):
        v["i"] = i
    return visuals, face
