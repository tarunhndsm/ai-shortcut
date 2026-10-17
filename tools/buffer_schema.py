"""Print the input fields of Buffer GraphQL types (default: CreatePostInput) through introspection.

    .venv/bin/python tools/buffer_schema.py [TypeName ...]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desk import publish  # noqa: E402

Q = """query T($name: String!) { __type(name: $name) { name kind
  inputFields { name type { kind name ofType { kind name ofType { kind name ofType { kind name ofType { kind name } } } } } }
  enumValues { name } fields { name } } }"""


def _type(t: dict) -> str:
    if t is None or "kind" not in t:
        return "?"
    if t["kind"] == "NON_NULL":
        return _type(t.get("ofType")) + "!"
    if t["kind"] == "LIST":
        return "[" + _type(t.get("ofType")) + "]"
    return t["name"] or "?"


for name in sys.argv[1:] or ["CreatePostInput"]:
    got = publish._buffer(Q, {"name": name})["__type"]
    if not got:
        print(f"{name}: not found")
        continue
    print(f"{got['name']} ({got['kind']})")
    for f in got.get("inputFields") or []:
        print(f"  {f['name']}: {_type(f['type'])}")
    for e in got.get("enumValues") or []:
        print(f"  = {e['name']}")
    for f in (got.get("fields") or [])[:40]:
        print(f"  . {f['name']}")
