"""List the Gemini models the AI Shortcut key can call, and try one tiny text request. Never prints the key."""

import json
import os
import sys
import urllib.request
from pathlib import Path

for line in (Path(__file__).resolve().parents[1] / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
KEY = os.environ["AI_GEMINI_API_KEY"]
API = "https://generativelanguage.googleapis.com/v1beta"


def call(path, body=None):
    req = urllib.request.Request(f"{API}/{path}", data=json.dumps(body).encode() if body else None,
                                 headers={"x-goog-api-key": KEY, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=240) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


status, data = call("models?pageSize=200")
names = sorted(m["name"].split("/", 1)[1] for m in data.get("models", []))
print("models:", status, len(names))
print(" ".join(n for n in names if any(s in n for s in ("flash", "tts", "pro", "image", "veo", "embed"))))
model = sys.argv[1] if len(sys.argv) > 1 else "gemini-3.8-flash"
status, data = call(f"models/{model}:generateContent", {"contents": [{"parts": [{"text": "Reply with the single word OK."}]}]})
text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "") if status == 200 else data.get("error", {}).get("message", "")[:200]
print(model, status, text.strip()[:200])
