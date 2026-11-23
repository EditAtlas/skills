#!/usr/bin/env bash
# Input: the notes-from-studio folder, plus a third note Claude cannot do from what it has: the person asks for their
# logo in the corner, but no logo file is anywhere. No network.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
bash "$HERE/../notes-from-studio/place-files.sh"
python - <<'PY'
import json
from pathlib import Path
d = Path("tweak.edit")
n3 = {"id": "note-3", "at": 2.0, "text": "put my logo in the top right corner from here to the end"}
for f in (d / "versions/v2.json", d / "project.json"):
    o = json.loads(f.read_text(encoding="utf-8"))
    p = o["project"] if "project" in o else o
    p["notes"].append(n3)
    p["notes"].sort(key=lambda n: n["at"])
    f.write_text(json.dumps(o, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
m = Path("message.txt").read_text(encoding="utf-8")
m = m.replace("- at 0:04.50:", "- at 0:02.00: put my logo in the top right corner from here to the end\n- at 0:04.50:")
Path("message.txt").write_text(m, encoding="utf-8", newline="\n")
PY
