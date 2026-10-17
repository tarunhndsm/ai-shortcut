"""Check that Buffer accepts a hosted video URL: create a draft (never published) on the YouTube channel, report what
Buffer made of the video, then delete the draft. With --scheduled, a private post 30 days out instead of a draft.

    .venv/bin/python tools/buffer_draft_test.py <video url> [--scheduled]
"""

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desk import env, publish  # noqa: E402

url = next(a for a in sys.argv[1:] if not a.startswith("--"))
POST = """query Post($input: PostInput!) { post(input: $input) { id status error { message }
  assets { id type mimeType source thumbnail } } }"""
DELETE = """mutation Delete($input: DeletePostInput!) { deletePost(input: $input) { __typename
  ... on MutationError { message } } }"""

payload = {"channelId": env.need("AI_BUFFER_YOUTUBE_ID"), "text": "Hosting check, deleted straight away.",
           "schedulingType": "automatic", "mode": "addToQueue", "saveToDraft": True,
           "assets": [{"video": {"url": url}}],
           "metadata": {"youtube": {"title": "Hosting check", "categoryId": "28", "privacy": "private",
                                    "madeForKids": False, "notifySubscribers": False}}}
if "--scheduled" in sys.argv:
    payload.pop("saveToDraft")
    payload["mode"] = "customScheduled"
    payload["dueAt"] = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
got = publish._buffer(publish.CREATE, {"input": payload})["createPost"]
print("create:", got.get("__typename"), got.get("message", ""))
if got.get("__typename") != "PostActionSuccess":
    sys.exit(1)
pid = got["post"]["id"]
try:
    for _ in range(6):
        post = publish._buffer(POST, {"input": {"id": pid}})["post"]
        assets = [{k: (a[k] if k != "thumbnail" else bool(a[k])) for k in ("type", "mimeType", "thumbnail")}
                  for a in post["assets"] or []]
        print("status:", post["status"], "| error:", (post.get("error") or {}).get("message"), "| assets:", assets)
        if any(a["thumbnail"] for a in assets) or post.get("error"):
            break
        time.sleep(10)
finally:
    print("delete:", publish._buffer(DELETE, {"input": {"id": pid}})["deletePost"])
