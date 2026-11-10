#!/usr/bin/env bash
# Input: Claude's earlier edit in work/, and the package folder the person saved in the studio: version 1 by Claude,
# version 2 by the person (Save, no note), project.json = version 2.
set -eu
mkdir -p work tweak.edit/media tweak.edit/versions
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
import copy, shutil
json.dump(p, open("project.json", "w"), indent=1)
v1 = copy.deepcopy(p)
for m in v1["media"].values():
    m["path"] = "media/" + m["path"]
e = copy.deepcopy(v1)
e["tracks"][1]["items"][0]["at"] = 0.9
e["styles"]["hook"]["size"] = 90
e["tracks"][2]["items"][0]["gain_db"] = -9
dump = lambda o: json.dumps(o, indent=1, ensure_ascii=False) + "\n"
version = lambda n, parent, by, name, made, proj: {"format": "editatlas-version/1", "version": n, "parent": parent,
                                                   "by": by, "name": name, "note": "", "made": made, "project": proj}
open("../tweak.edit/versions/v1.json", "w", encoding="utf-8", newline="\n").write(
    dump(version(1, None, "agent", "Claude", "2026-11-10T10:00:00.000Z", v1)))
open("../tweak.edit/versions/v2.json", "w", encoding="utf-8", newline="\n").write(
    dump(version(2, 1, "studio", "", "2026-11-10T11:00:00.000Z", e)))
open("../tweak.edit/project.json", "w", encoding="utf-8", newline="\n").write(dump(e))
shutil.copy("clip.mp4", "../tweak.edit/media/clip.mp4"); shutil.copy("click.wav", "../tweak.edit/media/click.wav")
PY
