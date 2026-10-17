"""Take the desk's screenshots of a few pages into work/shots, to check how they read at phone width.

    .venv/bin/python tools/try_shots.py <url> [url ...]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desk import assets  # noqa: E402

folder = Path(__file__).resolve().parents[1] / "work" / "shots"
targets = [{"url": u, "kind": "github" if "github.com" in u else "page"} for u in sys.argv[1:]]
for shot in assets.screenshots(targets, folder):
    print(shot["file"], shot["w"], "x", shot["h"], shot["what"])
