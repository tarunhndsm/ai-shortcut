"""Set the try script's stat value to "1M tokens" so try_compose shows the number/unit split."""

import json
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "work" / "try" / "script.json"
script = json.loads(path.read_text())
for scene in script["scenes"]:
    if scene["type"] == "stat":
        scene["value"] = "1M tokens"
path.write_text(json.dumps(script, indent=1, ensure_ascii=False))
print("stat value set")
