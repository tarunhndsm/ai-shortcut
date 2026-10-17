"""Build (not render) the HyperFrames project from work/try's script with fake word timings, to catch errors early."""

import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desk import compose  # noqa: E402

work = Path(__file__).resolve().parents[1] / "work" / "try"
script = json.loads((work / "script.json").read_text())
dossier = json.loads((work / "dossier.json").read_text())
assets = work / "assets"
assets.mkdir(exist_ok=True)
visuals = []
for i, (name, size) in enumerate([("shot0.jpg", (1920, 2600)), ("img0.jpg", (1600, 900))]):
    img = Image.new("RGB", size, (30 + 40 * i, 60, 90))
    ImageDraw.Draw(img).text((40, 40), name, fill=(255, 255, 255))
    img.save(assets / name)
    visuals.append({"i": i, "kind": "screenshot" if i == 0 else "image", "what": name, "url": "https://example.com",
                    "file": f"assets/{name}", "w": size[0], "h": size[1]})
words, t = [], 0.0
for beat, scene in enumerate(script["scenes"]):
    for w in scene["say"].split():
        words.append({"text": w, "start": round(t, 2), "end": round(t + 0.28, 2), "beat": beat})
        t += 0.31
    t += 0.2
narration = {"wav": str(work / "voice.wav"), "duration": t, "words": words, "model": "fake"}
built = compose.build(script, narration, visuals, None, dossier, assets, work / "project")
html = (work / "project" / "index.html").read_text()
left = re.findall(r"\{\{[A-Z_]+\}\}", html)
print("duration", built["duration"], "events", len(built["events"]), "scenes", len(built["data"]["scenes"]))
print("leftover placeholders:", left)
print([(s["type"], round(s["t0"], 2), round(s["t1"], 2)) for s in built["data"]["scenes"]])
