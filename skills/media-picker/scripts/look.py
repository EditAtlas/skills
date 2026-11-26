#!/usr/bin/env python3
"""Look at the person's own footage once, and keep what you saw, so the next edit does not look again.

    python look.py clip1.mp4 clip2.mov photo.jpg --out work/look            # one sheet per file, notes already kept
    python look.py clip1.mp4 --times 3.5,4,4.5 --out work/look              # just these times, to look closely
    python look.py clip1.mp4 --note "0-3s ...; best 5s" --by Claude --out work/look   # keep what you saw
    python look.py --notes --out work/look                                  # every kept note whose file is unchanged
    python look.py --into result/NAME.edit/project.json --out work/look     # notes into the project's media (seen)
    python look.py --from result/NAME.edit/project.json --out work/look     # notes back from a project

A sheet is up to 12 frames from across a video in a grid, each marked with its time in the file (a photo is shown
as it is). Open it with the Read tool. A note is two or three short lines: what happens and where (times in the
file), the people, the place, the light, how steady, the best and the weakest moments. Notes are kept in
<out>/seen.json by the file's fingerprint (its size and a SHA-256 of its first and last MiB), so a copy of the file,
such as the one in an editable-export folder, keeps its note, and a file that was changed or re-exported does not.
In a project they go in media.<id>.seen ({text, by, at, fingerprint}); the studio shows them under Media and keeps
them, so the note travels with the project between you and the person.
"""
import argparse
import datetime
import hashlib
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # also under python -I
from PIL import Image, ImageDraw  # noqa: E402

from measure import IMAGE_EXT, fail, frame_at, kind_of, probe  # noqa: E402

MAX_NOTE = 800
MIB = 1 << 20


def fingerprint(path):
    """Size and a SHA-256 of the first and last MiB: the same for a copy, different once the file is changed."""
    path = Path(path)
    size = path.stat().st_size
    h = hashlib.sha256(str(size).encode())
    with open(path, "rb") as f:
        h.update(f.read(MIB))
        if size > 2 * MIB:
            f.seek(size - MIB)
            h.update(f.read(MIB))
    return f"{size}:{h.hexdigest()[:32]}"


def load(out):
    p = Path(out) / "seen.json"
    if not p.exists():
        return {"format": "editatlas-seen/1", "notes": {}}
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("format") != "editatlas-seen/1":
        fail(f"{p} is not a notes file of look.py")
    return data


def save(out, data):
    Path(out).mkdir(parents=True, exist_ok=True)
    (Path(out) / "seen.json").write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def clean(text):
    text = " ".join(str(text).split())
    if not text:
        fail("the note is empty")
    if len(text) > MAX_NOTE:
        print(f"look: the note was cut to {MAX_NOTE} characters; keep it to two or three short lines")
    return text[:MAX_NOTE]


def times_for(duration, count):
    count = max(1, min(12, count))
    return [round((i + 0.5) * duration / count, 2) for i in range(count)]


def draw(images, labels, title, out):
    tiles = [(img, lab) for img, lab in zip(images, labels) if img is not None]
    if not tiles:
        return None
    w = 240 if tiles[0][0].height > tiles[0][0].width else 320
    cells = [(img.resize((w, max(1, round(img.height * w / img.width)))), lab) for img, lab in tiles]
    cols = len(cells) if len(cells) <= 4 else 3 if len(cells) <= 6 else 4
    rows = math.ceil(len(cells) / cols)
    th = max(c.height for c, _ in cells)
    sheet = Image.new("RGB", (cols * w + (cols + 1) * 6, rows * th + (rows + 1) * 6 + 24), (24, 24, 26))
    d = ImageDraw.Draw(sheet)
    d.text((6, 6), title, fill=(245, 245, 247))
    for i, (cell, lab) in enumerate(cells):
        r, c = divmod(i, cols)
        x, y = 6 + c * (w + 6), 30 + r * (th + 6)
        sheet.paste(cell, (x, y))
        box = d.textbbox((0, 0), lab)
        d.rectangle([x + 4, y + 4, x + 12 + box[2], y + 10 + box[3]], fill=(0, 0, 0))
        d.text((x + 8, y + 6), lab, fill=(255, 255, 255))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


def sheet_for(path, args, index):
    info = probe(path)
    kind = kind_of(path, info)
    duration = float(info.get("format", {}).get("duration") or 0)
    out = Path(args.out) / "sheets" / f"{index:02d}-{path.stem}.png"
    if kind == "photo" or path.suffix.lower() in IMAGE_EXT:
        img = Image.open(path).convert("RGB")
        img.thumbnail((768, 768))
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out.with_suffix(".jpg"))
        return "photo", 0.0, str(out.with_suffix(".jpg")), []
    if kind != "video":
        return kind, duration, None, []
    times = [float(t) for t in args.times.split(",")] if args.times else times_for(duration, args.frames)
    times = [min(max(0.0, t), max(0.0, duration - 0.05)) for t in times][:12]
    width = 480
    images = [frame_at(path, t, width) for t in times]
    title = f"{path.name} · {duration:.1f} s · times in the file"
    return kind, duration, draw(images, [f"{t:.1f}s" for t in times], title, out), times


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("files", nargs="*")
    p.add_argument("--out", required=True, help="folder for the sheets and seen.json")
    p.add_argument("--frames", type=int, default=12, help="frames from across each video (default 12, at most 12)")
    p.add_argument("--times", help="comma-separated times in the file, instead of --frames (one file)")
    p.add_argument("--note", help="what you saw in the one file given, to keep")
    p.add_argument("--by", default=None, help="who wrote the note, such as Claude")
    p.add_argument("--notes", action="store_true", help="print every kept note whose file is unchanged")
    p.add_argument("--into", help="a project.json: put the kept notes into media.<id>.seen")
    p.add_argument("--from", dest="source", help="a project.json: keep the notes found in media.<id>.seen")
    args = p.parse_args()
    data = load(args.out)
    notes = data["notes"]

    if args.into or args.source:
        project_path = Path(args.into or args.source)
        project = json.loads(project_path.read_text(encoding="utf-8"))
        base = project_path.resolve().parent
        moved, stale = 0, []
        for mid, m in (project.get("media") or {}).items():
            f = base / m.get("path", "")
            if m.get("kind") not in ("video", "image") or not f.is_file():
                continue
            fp = fingerprint(f)
            if args.into and fp in notes:
                n = notes[fp]
                m["seen"] = {"text": n["text"], "by": n.get("by"), "at": n["at"], "fingerprint": fp}
                moved += 1
            elif args.source and isinstance(m.get("seen"), dict) and m["seen"].get("text"):
                if m["seen"].get("fingerprint") not in (None, fp):
                    stale.append(mid)
                    continue
                notes[fp] = {"text": clean(m["seen"]["text"]), "by": m["seen"].get("by"), "at": m["seen"].get("at") or today(), "file": str(f)}
                moved += 1
        if args.into:
            project_path.write_text(json.dumps(project, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"look: {moved} note(s) put into {project_path} (media.<id>.seen); save it as a version with package.py save")
        else:
            save(args.out, data)
            print(f"look: {moved} note(s) kept from {project_path}")
        for mid in stale:
            print(f"look: {mid}: its file changed after the note was written; look at it again")
        return

    if args.notes:
        shown = 0
        for fp, n in notes.items():
            f = Path(n.get("file", ""))
            if not f.is_file():
                print(f"{n.get('file')}: not found here; its note is kept for when it is")
                continue
            if fingerprint(f) != fp:
                print(f"{f}: changed since the note; look at it again")
                continue
            print(f"{f}: {n['text']}  ({n.get('by') or 'unknown'}, {n['at']})")
            shown += 1
        if not shown:
            print("look: no notes for files as they are now")
        return

    files = [Path(f) for f in args.files]
    if not files:
        fail("give the files to look at, or --notes, --into or --from")
    for f in files:
        if not f.is_file():
            fail(f"{f} not found")
    if args.note is not None:
        if len(files) != 1:
            fail("--note goes with one file")
        fp = fingerprint(files[0])
        notes[fp] = {"text": clean(args.note), "by": args.by, "at": today(), "file": str(files[0].resolve())}
        save(args.out, data)
        print(f"look: kept the note for {files[0].name}")
        return
    if args.times and len(files) != 1:
        fail("--times goes with one file")
    for i, f in enumerate(files, 1):
        kind, duration, sheet, _ = sheet_for(f, args, i)
        kept = notes.get(fingerprint(f))
        line = f"{f.name}: {kind}, {duration:.1f} s" if kind == "video" else f"{f.name}: {kind}"
        print(line + (f", sheet {sheet}" if sheet else ", no picture"))
        if kept:
            print(f"    seen before ({kept.get('by') or 'unknown'}, {kept['at']}): {kept['text']}")
    print("Open each sheet with the Read tool. Keep what you saw with --note, so the next edit need not look again.")


def today():
    return datetime.date.today().isoformat()


if __name__ == "__main__":
    main()
