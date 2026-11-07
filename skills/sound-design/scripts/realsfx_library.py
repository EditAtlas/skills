"""Make the EditAtlas/sfx library readable by the real-sfx skill as a main pack: hard links (no extra disk space,
same drive only) plus a catalog.json that gives every sound its type from the EditAtlas category.
Usage: realsfx_library.py MIRROR_DIR OUT_DIR   (MIRROR_DIR = a clone of github.com/EditAtlas/sfx)"""
import json, os, shutil, sys
from pathlib import Path

TYPE = {  # EditAtlas category -> real-sfx pack type (PACK_TYPE_ROLES)
    "whoosh": "whoosh", "impact": "impact", "riser": "riser", "ui": "ui", "glitch": "glitch",
    "foley": "foley", "ambience": "ambience", "nature": "nature", "cartoon": "cartoon", "bell": "chime",
    "magic": "chime", "scifi": "scifi", "voice": "voice", "music": "music_transition",
}
mirror, out = Path(sys.argv[1]), Path(sys.argv[2])
idx = json.loads((mirror / "index.json").read_text(encoding="utf-8"))
rows, linked = [], 0
for s in idx["sounds"]:
    src, dst = mirror / s["path"], out / s["path"]
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        try:
            os.link(src, dst)
        except OSError:              # another drive: copy instead
            shutil.copy2(src, dst)
        linked += 1
    first = s["description"].split(". ")[0].rstrip(".")
    rows.append({"file": s["path"], "type": TYPE.get(s["category"], "other"),
                 "source": f"{s['category']}/{s['title']} - {first}.mp3".replace("\\", " "),
                 "hit": 1, "hits_in_source": 1, "editatlas_id": s["id"]})
(out / "catalog.json").write_text(json.dumps({"sounds": rows}, ensure_ascii=False, indent=0), encoding="utf-8")
print(f"{len(rows)} rows, {linked} new files ->", out)
