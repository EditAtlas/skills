#!/usr/bin/env bash
# Input: Claude's edit in work/, and the package folder tweak.edit after a round in the studio: version 1 by Claude,
# version 2 by the person, who changed nothing but left two notes on the timeline (the title should say "Two ways",
# the video should end at 5 seconds), project.json = version 2, and message.txt, the message the studio gave the
# person to paste back. No network.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS="$HERE/../../scripts"
mkdir -p work
cd work
ffmpeg -v error -f lavfi -i testsrc2=size=1080x1920:rate=30:duration=6 -c:v libx264 -pix_fmt yuv420p clip.mp4
ffmpeg -v error -f lavfi -i "sine=frequency=2000:duration=0.05" -af "afade=t=out:d=0.04" click.wav
python - <<'PY'
import json
p = {"format": "editatlas-project/1", "title": "Tweak test",
     "canvas": {"width": 1080, "height": 1920, "fps": 30, "background": "#000000"},
     "media": {"clip": {"kind": "video", "path": "clip.mp4"}, "click": {"kind": "audio", "path": "click.wav"}},
     "styles": {"hook": {"size": 80, "y": 0.2, "color": "#ffffff", "stroke": {"color": "#000000", "width": 8}}},
     "tracks": [
         {"id": "V1", "kind": "video", "name": "Footage", "clips": [{"id": "c1", "media": "clip", "in": 0, "out": 6}]},
         {"id": "T1", "kind": "text", "name": "Text", "items": [
             {"id": "hook", "style": "hook", "text": "Three ways to cut faster", "at": 0.5, "dur": 3}]},
         {"id": "A1", "kind": "audio", "name": "Sounds", "items": [
             {"id": "s-click", "media": "click", "at": 0.5, "gain_db": -6, "label": "hook in"}]}]}
json.dump(p, open("project.json", "w"), indent=1)
PY
cd ..
python "$SCRIPTS/package.py" build work/project.json --out tweak.edit --note "title and click" > /dev/null
python - "$SCRIPTS" <<'PY'
import copy, json, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from package import change_summary          # the same lines the studio writes
d = Path("tweak.edit")
v1 = json.loads((d / "versions/v1.json").read_text(encoding="utf-8"))
p = copy.deepcopy(v1["project"])
p["notes"] = [{"id": "note-1", "at": 0.8, "text": "say Two ways instead of Three ways"},
              {"id": "note-2", "at": 4.5, "text": "end the video at 5 seconds"}]
note = ""
v2 = {"format": "editatlas-version/1", "version": 2, "parent": 1, "by": "studio", "name": "", "note": note,
      "made": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"), "project": p}
dump = lambda o: json.dumps(o, indent=1, ensure_ascii=False) + "\n"
(d / "versions/v2.json").write_text(dump(v2), encoding="utf-8", newline="\n")
(d / "project.json").write_text(dump(p), encoding="utf-8", newline="\n")
lines = "\n".join("- " + x for x in change_summary(v1["project"], p))
Path("message.txt").write_text(
    f'I fine-tuned "{p["title"]}" in EditAtlas Studio and saved it as version 2 in the project folder tweak.edit.\n\n'
    f"What I changed since version 1:\n{lines}\n\n"
    "My notes on the timeline (work on each one, then take it out of the project's \"notes\"):\n"
    "- at 0:00.80: say Two ways instead of Three ways\n- at 0:04.50: end the video at 5 seconds\n\n"
    "Continue from version 2 in that folder with the editable-export skill, and save your result there as the next "
    "version.\n", encoding="utf-8", newline="\n")
PY
