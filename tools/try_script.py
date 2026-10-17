"""Local check of the newsroom half (scouts, editor, researcher, writer, fact-checker): no voice, no render."""

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desk import editor, research, scouts, writer  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S")
out = Path(__file__).resolve().parents[1] / "work" / "try"
out.mkdir(parents=True, exist_ok=True)
board = scouts.scan()
picks = editor.pick(board, [])
print(json.dumps([{k: v for k, v in p.items() if k != "items"} | {"urls": [i["url"] for i in p["items"]]} for p in picks],
                 indent=1, ensure_ascii=False))
dossier = research.dossier(picks[0])
(out / "dossier.json").write_text(json.dumps(dossier, indent=1, ensure_ascii=False))
visuals = [{"i": 0, "kind": "screenshot", "what": f"screenshot of {dossier['sources'][0]['url']}", "w": 1920, "h": 2600,
            "file": "assets/shot0.jpg", "url": dossier["sources"][0]["url"]}]
visuals += [{"i": k + 1, "kind": "image", "what": img.get("alt") or "image", "w": 1600, "h": 900, "file": f"assets/img{k}.jpg",
             "url": img["url"]} for k, img in enumerate(dossier["sources"][0].get("images", [])[:3])]
script = writer.write(dossier, visuals)
(out / "script.json").write_text(json.dumps(script, indent=1, ensure_ascii=False))
print(json.dumps(script, indent=1, ensure_ascii=False))
