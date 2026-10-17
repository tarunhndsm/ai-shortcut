"""Top of the scouts' board with ages and cross-source families, plus each scout's item count."""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desk import scouts, state  # noqa: E402

counts = {}


class Grab(logging.Handler):
    def emit(self, record):
        if record.getMessage().startswith("scouts: "):
            counts["report"] = record.args  # logging unwraps a lone dict argument into record.args


logging.getLogger("desk.scouts").addHandler(Grab())
logging.getLogger("desk.scouts").setLevel(logging.INFO)
board = scouts.scan()
report = counts.get("report", {})
print("new feeds:", {k: report.get(k) for k in ("mistral", "google-research", "microsoft-research", "microsoft-ai",
                                                "meta-engineering", "tldr-ai", "latent-space", "techmeme", "google-ai",
                                                "reddit")})
print("failed:", {k: v for k, v in report.items() if not isinstance(v, int)})
for item in board[:16]:
    published = state.parse(item.get("published"))
    age = f"{(state.now() - published).total_seconds() / 3600:5.1f}h" if published else "  ?  "
    print(f"{item['heat']:5.1f} {age} {item['kind']:12} {item['label'][:26]:26} {item['title'][:58]:58} {item.get('also_on', '')}")
