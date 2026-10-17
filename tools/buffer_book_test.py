"""Book a post exactly as the desk does (publish.post with a due time 30 days out) on every connected channel, report
what Buffer made of it, then delete it. Nothing is published.

    .venv/bin/python tools/buffer_book_test.py <video url>
"""

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desk import publish, run  # noqa: E402

POST = "query Post($input: PostInput!) { post(input: $input) { id status dueAt error { message } } }"
DELETE = """mutation Delete($input: DeletePostInput!) { deletePost(input: $input) { __typename
  ... on MutationError { message } } }"""

meta = {"id": "booking-check", "title": "Booking check, deleted straight away", "description": "Booking check.",
        "source": "https://github.com/tarunhndsm/ai-shortcut", "hashtags": ["#Shorts"], "disclosure": run.DISCLOSURE}
got = publish.post(sys.argv[1], meta, due=datetime.now(timezone.utc) + timedelta(days=30))
print("create:", got)
try:
    time.sleep(5)
    for service, r in got.items():
        if "id" in r:
            post = publish._buffer(POST, {"input": {"id": r["id"]}})["post"]
            print(service, "status:", post["status"], "| due:", post["dueAt"], "| error:",
                  (post.get("error") or {}).get("message"))
finally:
    for service, r in got.items():
        if "id" in r:
            print(service, "delete:", publish._buffer(DELETE, {"input": {"id": r["id"]}})["deletePost"])
