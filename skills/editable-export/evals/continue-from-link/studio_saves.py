"""Scaffold helper for continue-from-link: acts as the person in the studio. It reads the newest version on the
folder's link, makes the title bigger (80 -> 96) and the click 0.1 s later, puts that on the link as the next version
(by "studio", with a note) and writes message.txt, what the studio gives the person to paste back. It does not touch
the folder: the person's own copy is elsewhere, so Claude has to pull.

  python studio_saves.py SCRIPTS_DIR FOLDER
"""
import copy, json, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import share  # noqa: E402
from package import change_summary  # noqa: E402

folder = Path(sys.argv[2])
link, _ = share.read_state(folder)
info = link.info()
was = link.version(info["version"])
p = copy.deepcopy(was["project"])
p["styles"]["hook"]["size"] = 96
click = next(t for t in p["tracks"] if t["kind"] == "audio")["items"][0]
click["at"] = round(click["at"] + 0.1, 3)
n, note = info["version"] + 1, "title bigger, click a little later"
obj = {"format": share.FORMAT, "version": n, "parent": info["version"], "by": "studio", "name": "", "note": note,
       "made": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"), "project": p,
       "media": was["media"]}
if link.put_version(obj) != 201:
    sys.exit("studio_saves: the link refused the version")
lines = "\n".join("- " + x for x in change_summary(was["project"], p))
# The studio's own wording when the person opened the link without the folder (forAgent in studio-editor.js).
Path("message.txt").write_text(
    f'I fine-tuned "{p["title"]}" in EditAtlas Studio and saved it as version {n} on the studio link.\n'
    f"Link: {link.url}\n\nWhat I changed since version {n - 1}:\n{lines}\n\nNext: {note}\n\n"
    f"Continue from version {n} with the editable-export skill: pull it from the link into the project folder "
    f"(share.py pull), and save your result as the next version there and on the link (share.py push).\n",
    encoding="utf-8", newline="\n")
print(f"version {n} on the link, by the studio")
