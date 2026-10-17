"""Rendering: HyperFrames turns the project into an MP4 in headless Chrome, then frames are pulled for the judge."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

from . import ff

log = logging.getLogger(__name__)

HYPERFRAMES = os.environ.get("DESK_HYPERFRAMES", "hyperframes@0.8.134")


def render(project: Path, out: Path) -> Path:
    exe = os.environ.get("HYPERFRAMES_BIN") or shutil.which("hyperframes")
    cmd = ([exe] if exe else ["npx", "--yes", HYPERFRAMES]) + [
        "render", str(project), "-o", str(out), "--fps", "30", "--crf", "20", "--workers", "auto"]
    started = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out.exists():
        tail = (proc.stdout + proc.stderr)[-4000:]
        raise RuntimeError(f"hyperframes render failed ({proc.returncode}): {tail}")
    log.info("rendered %s in %.0f s", out.name, time.time() - started)
    return out


def frames(video: Path, times: list[float], folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for k, t in enumerate(times):
        path = folder / f"f{k:02d}_{t:05.1f}.jpg"
        ff.run("-ss", f"{max(0.0, t):.2f}", "-i", video, "-frames:v", "1", "-q:v", "3", "-vf", "scale=540:-2", path)
        paths.append(path)
    return paths


def sheet(paths: list[Path], out: Path, cols: int = 4) -> Path:
    from PIL import Image

    imgs = [Image.open(p) for p in paths]
    w, h = imgs[0].size
    rows = (len(imgs) + cols - 1) // cols
    board = Image.new("RGB", (cols * w + (cols + 1) * 8, rows * h + (rows + 1) * 8), (20, 20, 24))
    for k, img in enumerate(imgs):
        board.paste(img, (8 + (k % cols) * (w + 8), 8 + (k // cols) * (h + 8)))
    board.save(out, quality=88)
    return out


def probe(video: Path) -> dict:
    """Duration, size and whether there is sound, from ffmpeg's banner."""
    proc = subprocess.run([ff.exe(), "-hide_banner", "-i", str(video)], capture_output=True, text=True)
    text = proc.stderr
    import re

    size = re.search(r"Video: .*?(\d{3,4})x(\d{3,4})", text)
    return {"duration": ff.duration(video), "width": int(size.group(1)) if size else 0,
            "height": int(size.group(2)) if size else 0, "audio": "Audio:" in text, "bytes": video.stat().st_size}
