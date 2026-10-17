"""Paths and settings. Locally a .env beside the repo fills in what CI passes as secrets."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
TEMPLATE = ROOT / "template"
WORK = Path(os.environ.get("DESK_WORK", ROOT / "work"))
CHANNEL = {
    "name": "AI Shortcut",
    "handle": "@AIShortcut-p4k",
    "channel_id": "UCeoPI2OoAWxk-vqPWhgI2SA",
    "tagline": "One AI shortcut a day.",
}


def _load_dotenv() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def need(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not set")
    return value


def in_ci() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"
