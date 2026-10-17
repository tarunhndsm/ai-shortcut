"""List the channels on AI Shortcut's Buffer account (ids, names, services). Reads AI_BUFFER_API_KEY from .env.

    .venv/bin/python tools/buffer_channels.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desk import env, publish  # noqa: E402,F401

CHANNELS = """query Channels($input: ChannelsInput!) {
  channels(input: $input) { id name displayName service isDisconnected isLocked isQueuePaused timezone } }"""

orgs = publish._buffer("query { account { organizations { id name } } }")["account"]["organizations"]
for org in orgs:
    print(f"organization {org['id']} {org['name']}")
    for ch in publish._buffer(CHANNELS, {"input": {"organizationId": org["id"]}})["channels"]:
        print(f"  {ch['service']:<10} {ch['id']}  {ch['displayName'] or ch['name']}  tz={ch['timezone']}"
              f"{'  DISCONNECTED' if ch['isDisconnected'] else ''}{'  LOCKED' if ch['isLocked'] else ''}"
              f"{'  PAUSED' if ch['isQueuePaused'] else ''}")
