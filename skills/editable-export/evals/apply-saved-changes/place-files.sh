#!/usr/bin/env bash
# Input: Claude's earlier edit in work/, and the package the person saved from the studio.
set -eu
mkdir -p work tweak.edit/media
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
e = copy.deepcopy(p)
for m in e["media"].values():
    m["path"] = "media/" + m["path"]
e["tracks"][1]["items"][0]["at"] = 0.9
e["styles"]["hook"]["size"] = 90
e["tracks"][2]["items"][0]["gain_db"] = -9
json.dump(e, open("../tweak.edit/project.json", "w"), indent=1)
shutil.copy("clip.mp4", "../tweak.edit/media/clip.mp4"); shutil.copy("click.wav", "../tweak.edit/media/click.wav")
PY
