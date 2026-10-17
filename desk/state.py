"""What the desk remembers between runs, kept as JSON files in state/ and committed back by the workflow."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .env import STATE

POSTED = STATE / "posted.json"
SEEN = STATE / "seen.json"
QUEUE = STATE / "queue.json"


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime | None = None) -> str:
    return (moment or now()).astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def load(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    tmp.replace(path)


def posted() -> list[dict]:
    return load(POSTED, [])


def add_posted(entry: dict) -> None:
    items = posted()
    items.append(entry)
    save(POSTED, items[-400:])


def recent_posted(days: float = 10) -> list[dict]:
    cutoff = now() - timedelta(days=days)
    return [p for p in posted() if (parse(p.get("at")) or cutoff) >= cutoff]


def seen() -> dict:
    """First time each scouted item was seen: {key: iso}. Lets a source with no dates still say what is new."""
    return load(SEEN, {})


def mark_seen(stamps: dict[str, str | None]) -> dict:
    """Record when each key was first seen (now, unless a stamp is given). Keys still being seen are kept however
    old, so an old post never comes back as new; the rest are forgotten after three weeks."""
    data = seen()
    stamp = iso()
    for key, when in stamps.items():
        data.setdefault(key, when or stamp)
    cutoff = now() - timedelta(days=21)
    data = {k: v for k, v in data.items() if k in stamps or (parse(v) or cutoff) >= cutoff}
    save(SEEN, data)
    return data
