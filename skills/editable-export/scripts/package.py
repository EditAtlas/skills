"""Turn a finished edit into an editable package: its elements and their files, for the EditAtlas studio.

  package.py build work/project.json --out result/my-video.edit           # version 1
  package.py build work/project.json --out result/my-video.edit       --cuts work/cuts.json --captions work/transcript.json --sfx result/film_sfx_resolved.json
  package.py check result/my-video.edit
  package.py versions result/my-video.edit                                # who saved which version
  package.py changes result/my-video.edit                                 # what the newest version changed
  package.py save work/next.json --to result/my-video.edit --from 2 --note "hook shorter"   # your next version

`build` checks project.json (references/project-format.md), copies every file it uses into OUT/media/, measures
the footage and sounds, and writes OUT/versions/v1.json, then OUT/project.json. The folder is what the studio
opens on the person's computer and what render.py renders. Nothing is uploaded anywhere.

The folder holds every version: versions/v1.json, v2.json ... (by "agent" or by "studio", with a parent and a
note), and project.json is always the newest one. `save` adds your next version after the person's, and refuses
when someone saved after the version you started from.

Optional imports for build, so you do not write hundreds of elements by hand:
  --cuts cuts.json        transcribe's cut list -> the footage clips (the parts kept), for --cuts-media
  --captions FILE.json    transcribe's transcript.json -> caption elements with word timing (style "caption")
  --sfx RESOLVED.json     sound-design's _resolved.json -> sound elements at the same times and levels
"""
import argparse
import filecmp
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

FORMAT = "editatlas-project/1"
VERSION_FORMAT = "editatlas-version/1"
KINDS = {"video", "audio", "image", "font"}
TRACK_KINDS = {"video", "text", "image", "audio"}


def die(msg):
    sys.exit("editable-export: " + msg)


def utf8_stdout():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def need(tool):
    if not shutil.which(tool):
        die(f"{tool} not found in PATH. Install FFmpeg (it ships ffprobe) and open a new terminal.")


def probe(path):
    need("ffprobe")
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration:stream=codec_type,width,height,r_frame_rate:stream_tags=rotate",
                        "-of", "json", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        die(f"cannot read {path}: {r.stderr.strip()[:300]}")
    d = json.loads(r.stdout)
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), None)
    out = {"duration": round(float(d.get("format", {}).get("duration") or 0), 3), "has_audio": a is not None}
    if v:
        n, m = (v.get("r_frame_rate") or "30/1").split("/")
        out.update(width=v.get("width"), height=v.get("height"), fps=round(float(n) / float(m or 1), 3))
    return out


# ------------------------------------------------------------------ checking a project
def find_file(path, bases):
    """The file a media path names: relative to one of the bases (in order), or as given."""
    for b in bases:
        if (Path(b) / path).is_file():
            return Path(b) / path
    return Path(path) if Path(path).is_file() else None


def check(p, base=None):
    """A list of problems; empty when the project can be built. base: a folder, or a list of folders, that media
    paths are relative to (None: do not look for the files)."""
    bases = None if base is None else ([base] if isinstance(base, (str, Path)) else list(base))
    errs = []
    if p.get("format") != FORMAT:
        errs.append(f"format must be {FORMAT!r}")
    c = p.get("canvas") or {}
    for k in ("width", "height", "fps"):
        if not isinstance(c.get(k), (int, float)) or c.get(k) <= 0:
            errs.append(f"canvas.{k} must be a positive number")
    if c.get("width", 0) % 2 or c.get("height", 0) % 2:
        errs.append("canvas width and height must be even (H.264)")
    media = p.get("media") or {}
    for mid, m in media.items():
        if m.get("kind") not in KINDS:
            errs.append(f"media {mid}: kind must be one of {sorted(KINDS)}")
        if not m.get("path"):
            errs.append(f"media {mid}: no path")
        elif bases is not None and not find_file(m["path"], bases):
            errs.append(f"media {mid}: file not found: {m['path']}")
        if m.get("kind") == "font" and not m.get("family"):
            errs.append(f"media {mid}: a font needs its family name")
    ids = set()
    styles = p.get("styles") or {}
    nvideo = 0
    for t in p.get("tracks") or []:
        k = t.get("kind")
        if k not in TRACK_KINDS:
            errs.append(f"track {t.get('id')}: kind must be one of {sorted(TRACK_KINDS)}")
            continue
        if not t.get("id"):
            errs.append("a track has no id")
        if k == "video":
            nvideo += 1
            for x in t.get("clips") or []:
                where = f"clip {x.get('id')}"
                if media.get(x.get("media"), {}).get("kind") != "video":
                    errs.append(f"{where}: media {x.get('media')!r} is not a video in media")
                if not (isinstance(x.get("in"), (int, float)) and isinstance(x.get("out"), (int, float)) and x["out"] > x["in"] >= 0):
                    errs.append(f"{where}: needs 0 <= in < out (source seconds)")
                if "speed" in x and not (is_num(x["speed"]) and 0.1 <= x["speed"] <= 10):
                    errs.append(f"{where}: speed must be a number from 0.1 to 10 (1 = as filmed)")
                tr = x.get("transition")
                if tr is not None and not (isinstance(tr, dict) and tr.get("type") in TRANSITIONS and is_num(tr.get("dur", 0.5)) and 0 < tr.get("dur", 0.5) <= 5):
                    errs.append(f"{where}: transition must be {{\"type\": one of {sorted(TRANSITIONS)}, \"dur\": seconds}}")
                ids_add(ids, x.get("id"), where, errs)
            continue
        for x in t.get("items") or []:
            where = f"{k} item {x.get('id')}"
            ids_add(ids, x.get("id"), where, errs)
            if not isinstance(x.get("at"), (int, float)):
                errs.append(f"{where}: needs at (seconds)")
            if k in ("text", "image") and not (isinstance(x.get("dur"), (int, float)) and x["dur"] > 0):
                errs.append(f"{where}: needs dur > 0")
            if k == "text":
                if x.get("style") and x["style"] not in styles:
                    errs.append(f"{where}: style {x['style']!r} is not in styles")
                if x.get("words") and len(x["words"]) != len(str(x.get("text", "")).split()):
                    errs.append(f"{where}: {len(x['words'])} word times for {len(str(x.get('text', '')).split())} words")
            if k in ("image", "audio") and media.get(x.get("media"), {}).get("kind") != k:
                errs.append(f"{where}: media {x.get('media')!r} is not an {k} in media")
            if k == "audio" and "gain_keys" in x:
                ks = x["gain_keys"]
                if not (isinstance(ks, list) and all(isinstance(q, dict) and is_num(q.get("t")) and is_num(q.get("db")) for q in ks)):
                    errs.append(f"{where}: gain_keys must be a list of {{\"t\": seconds into the file, \"db\": change}}")
                elif any(b["t"] < a["t"] for a, b in zip(ks, ks[1:])):
                    errs.append(f"{where}: gain_keys must be in time order")
    if nvideo > 1:
        errs.append("use one video track (the footage); put other pictures on image tracks")
    errs += check_cards(p)
    for name, st in styles.items():
        font = st.get("font")
        if font and font != "sans-serif" and not any(m.get("kind") == "font" and m.get("family") == font for m in media.values()):
            errs.append(f"style {name}: font {font!r} has no font file in media (the studio would fall back to sans-serif)")
    return errs


TRANSITIONS = {"dissolve", "black", "white", "slide", "wipe"}


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


KEY_FIELDS = {"dx", "dy", "scale", "rotate", "opacity"}
EASES = {"linear", "out", "in", "in-out", "back", "step"}


def check_cards(p):
    """parent (text or graphics inside a card), keys (element motion) and strike."""
    errs, items = [], {}
    for t in p.get("tracks") or []:
        if t.get("kind") in ("text", "image"):
            for x in t.get("items") or []:
                items[x.get("id")] = x
    for i, x in items.items():
        where = f"item {i}"
        if x.get("parent") is not None:
            par = items.get(x["parent"])
            if not par:
                errs.append(f"{where}: parent {x['parent']!r} is not a text or image item")
            elif par.get("parent"):
                errs.append(f"{where}: parent {x['parent']!r} is itself inside {par['parent']!r}; one level only")
            elif isinstance(x.get("at"), (int, float)) and isinstance(par.get("at"), (int, float)) and (
                    x["at"] < par["at"] - 1e-6 or x["at"] + x.get("dur", 0) > par["at"] + par.get("dur", 0) + 1e-6):
                errs.append(f"{where}: shows {x['at']}-{x['at'] + x.get('dur', 0):.3f} s, outside its parent's "
                            f"{par['at']}-{par['at'] + par.get('dur', 0):.3f} s (it is drawn only while the parent is)")
        keys = x.get("keys")
        if keys is not None:
            if not isinstance(keys, list) or not keys:
                errs.append(f"{where}: keys must be a list of keyframes")
                continue
            last = -1e9
            for n, k in enumerate(keys):
                if not isinstance(k, dict) or not isinstance(k.get("t"), (int, float)):
                    errs.append(f"{where}: key {n} needs t (seconds from the item's start)")
                    continue
                if k["t"] < last:
                    errs.append(f"{where}: keys must be in time order (key {n})")
                last = k["t"]
                extra = set(k) - KEY_FIELDS - {"t", "ease"}
                if extra:
                    errs.append(f"{where}: key {n} has {sorted(extra)}; use {sorted(KEY_FIELDS)}, t and ease")
                if k.get("ease") is not None and k["ease"] not in EASES:
                    errs.append(f"{where}: key {n} ease must be one of {sorted(EASES)}")
                if not set(k) & KEY_FIELDS:
                    errs.append(f"{where}: key {n} sets none of {sorted(KEY_FIELDS)}")
    for name, st in (p.get("styles") or {}).items():
        sk = st.get("strike")
        if sk is not None and not (isinstance(sk, dict) and isinstance(sk.get("dur", 0), (int, float))):
            errs.append(f"style {name}: strike must be {{color, width, at, dur}}")
    return errs


def ids_add(ids, i, where, errs):
    if not i:
        errs.append(f"{where}: no id")
    elif i in ids:
        errs.append(f"{where}: id used twice")
    ids.add(i)


# ------------------------------------------------------------------ imports
def track_of(p, kind, tid, name):
    t = next((t for t in p["tracks"] if t.get("id") == tid), None)
    if not t:
        t = {"id": tid, "kind": kind, "name": name}
        t["clips" if kind == "video" else "items"] = []
        p["tracks"].append(t)
    return t


def import_cuts(p, cuts_path, media_id):
    d = json.loads(Path(cuts_path).read_text(encoding="utf-8"))
    dur = float(d["duration"])
    taken = sorted((c["start"], c["end"]) for c in d.get("cuts", []) if c.get("taken"))
    keep, t = [], 0.0
    for a, b in taken:
        if a > t + 0.02:
            keep.append((t, a))
        t = max(t, b)
    if dur > t + 0.02:
        keep.append((t, dur))
    v = track_of(p, "video", "V1", "Footage")
    v["clips"] = [{"id": f"c{i + 1}", "media": media_id, "in": round(a, 3), "out": round(b, 3)} for i, (a, b) in enumerate(keep)]
    return len(keep), sum(b - a for a, b in keep)


def source_to_timeline(p, media_id, s):
    t = 0.0
    for c in next((t for t in p["tracks"] if t["kind"] == "video"), {"clips": []})["clips"]:
        sp = c.get("speed") or 1
        d = (c["out"] - c["in"]) / sp
        if c["media"] == media_id and c["in"] - 1e-6 <= s < c["out"]:
            return t + (s - c["in"]) / sp
        t += d
    return None


def import_captions(p, transcript_path, media_id, words_per, style, max_chars):
    d = json.loads(Path(transcript_path).read_text(encoding="utf-8"))
    words = []
    has_clips = any(t["kind"] == "video" and t.get("clips") for t in p["tracks"])
    for w in d["words"]:
        txt = str(w.get("w", "")).strip()
        if not txt:
            continue
        a = source_to_timeline(p, media_id, float(w["start"])) if has_clips else float(w["start"])
        if a is None:
            continue                                  # the word was cut out
        b = a + max(0.05, float(w["end"]) - float(w["start"]))
        words.append({"w": txt, "a": a, "b": b})
    groups, cur = [], []
    for w in words:
        if cur and (len(cur) >= words_per or w["a"] - cur[-1]["b"] > 0.6
                    or len(" ".join(x["w"] for x in cur + [w])) > max_chars or w["a"] < cur[-1]["a"]):
            groups.append(cur)
            cur = []
        cur.append(w)
        if re.search(r"[.!?…]$", w["w"]):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    t = track_of(p, "text", "T1", "Captions")
    t["items"] = []
    for i, g in enumerate(groups):
        at = g[0]["a"]
        end = g[-1]["b"]
        if i + 1 < len(groups):
            end = min(max(end, min(end + 0.25, groups[i + 1][0]["a"])), groups[i + 1][0]["a"])
        t["items"].append({"id": f"cap{i + 1}", "style": style, "text": " ".join(x["w"] for x in g), "at": round(at, 3),
                           "dur": round(max(0.1, end - at), 3),
                           "words": [{"at": round(x["a"] - at, 3), "dur": round(x["b"] - x["a"], 3)} for x in g]})
    p.setdefault("styles", {}).setdefault(style, {"weight": 800, "size": 72, "color": "#ffffff", "y": 0.72,
                                                   "stroke": {"color": "#000000", "width": 10}, "highlight": "#ffd60a",
                                                   "in": {"type": "pop", "dur": 0.12}})
    return len(groups), len(words)


def import_sfx(p, resolved_path):
    d = json.loads(Path(resolved_path).read_text(encoding="utf-8"))
    t = track_of(p, "audio", "A1", "Sounds")
    n = 0
    for k, c in enumerate(d.get("cues", [])):
        if c.get("bed") or not c.get("path"):
            continue
        mid = c["id"]
        p["media"].setdefault(mid, {"kind": "audio", "path": c["path"], "title": c.get("title")})
        m = c.get("measured") or {}
        gain = round(float(c["peak_dbfs"]) - float(m.get("peak_dbfs", 0.0)), 1) if c.get("peak_dbfs") is not None else 0.0
        t["items"].append({"id": f"s{k + 1}", "media": mid, "at": round(float(c["placed_at"]), 3),
                           "in": round(float(c.get("offset_in") or 0), 3),
                           "out": round(float(c.get("offset_in") or 0) + float(c["len_s"]), 3), "gain_db": gain,
                           "fade_out": 0.01, "label": c.get("label") or c.get("title")})
        n += 1
    return n


# ------------------------------------------------------------------ the folder: media and versions
def write_json(path, obj, new=False):
    """UTF-8, indent 1, newline at the end. new=True never overwrites (a version file is written once)."""
    with open(path, "x" if new else "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(obj, indent=1, ensure_ascii=False) + "\n")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def version_files(folder):
    """{n: path} of FOLDER/versions/v<n>.json, in order."""
    d = Path(folder) / "versions"
    out = {}
    if d.is_dir():
        for f in d.iterdir():
            m = re.fullmatch(r"v([1-9]\d*)\.json", f.name)
            if m and f.is_file():
                out[int(m.group(1))] = f
    return dict(sorted(out.items()))


def read_version(f):
    return json.loads(Path(f).read_text(encoding="utf-8"))


def who(v):
    return "the person (studio)" if v.get("by") == "studio" else f"{v.get('name') or 'an agent'} (agent)"


def free_name(src, media_dir):
    """A name in media/ for src: the same name when that file is already there with the same bytes, otherwise the
    first name-2, name-3 ... that is free. A file already in media/ is never replaced: older versions may use it."""
    stem, ext = os.path.splitext(re.sub(r"[^\w.\-]+", "-", src.name).strip("-") or "file")
    k = 1
    while True:
        name = stem + ext if k == 1 else f"{stem}-{k}{ext}"
        dst = media_dir / name
        if not dst.exists() or (dst.is_file() and filecmp.cmp(src, dst, shallow=False)):
            return name
        k += 1


def place_media(p, bases, out):
    """Copy every file the project uses into OUT/media/ (new or changed files only; nothing is deleted), point the
    project at them and measure the footage and sounds. Returns the bytes the project uses."""
    media_dir = out / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    root = media_dir.resolve()
    total = 0
    for mid, m in p["media"].items():
        f = find_file(m["path"], bases).resolve()
        try:
            name = f.relative_to(root).as_posix()            # already in this folder's media/
            dst = f
        except ValueError:
            name = free_name(f, media_dir)
            dst = media_dir / name
            if not dst.is_file():
                shutil.copy2(f, dst)
        m["path"] = "media/" + name
        if m["kind"] in ("video", "audio"):
            info = probe(dst)
            m["duration"] = info["duration"]
            if m["kind"] == "video":
                m.update({k: info.get(k) for k in ("width", "height", "fps", "has_audio")})
        total += dst.stat().st_size
    for t in p["tracks"]:
        if t["kind"] == "video":
            for c in t["clips"]:
                d = p["media"][c["media"]].get("duration")
                if d and c["out"] > d + 0.01:
                    die(f"clip {c['id']}: out {c['out']} is past the end of {c['media']} ({d} s)")
    return total


def write_version(out, p, n, parent, note, name):
    """versions/v<n>.json first, then project.json, so project.json never holds what has no version file."""
    (out / "versions").mkdir(parents=True, exist_ok=True)
    v = {"format": VERSION_FORMAT, "version": n, "parent": parent, "by": "agent", "name": (name or "Claude")[:40],
         "note": (note or "")[:500], "made": now_iso(), "project": p}
    try:
        write_json(out / "versions" / f"v{n}.json", v, new=True)
    except FileExistsError:
        die(f"versions/v{n}.json appeared while saving (someone saved at the same time); nothing written. "
            f"Run package.py versions {out} and start again from the newest.")
    write_json(out / "project.json", p)


def print_summary(p, total, notes=()):
    dur = timeline_duration(p)
    counts = {k: sum(len(t.get("items") or t.get("clips") or []) for t in p["tracks"] if t["kind"] == k) for k in TRACK_KINDS}
    for n in notes:
        print(n)
    print(f"{p['canvas']['width']}x{p['canvas']['height']} at {p['canvas']['fps']} fps, {dur:.2f} s: "
          f"{counts['video']} clips, {counts['text']} text, {counts['image']} graphics, {counts['audio']} sounds")
    print(f"package {total / 1e6:.1f} MB in {len(p['media'])} files; footage: "
          + ", ".join(m["path"] for m in p["media"].values() if m["kind"] == "video"))


def load_project(path):
    src = Path(path).resolve()
    p = json.loads(src.read_text(encoding="utf-8"))
    p.setdefault("media", {})
    p.setdefault("tracks", [])
    p.setdefault("styles", {})
    return src, p


def report_errors(errs, src):
    if errs:
        for e in errs:
            print("error:", e)
        die(f"{len(errs)} problem(s) in {src.name}; nothing written")


# ------------------------------------------------------------------ build: version 1
def cmd_build(a):
    src, p = load_project(a.project)
    out = Path(a.out)
    if version_files(out) or (out / "project.json").is_file():
        die(f"{out} already holds a project and its versions. To add your next version, edit a copy of its "
            f"project.json and run: package.py save COPY.json --to {out} --from N (N: the version you started from; "
            f"package.py versions {out} lists them). If the person has not had this folder yet, you may delete it "
            "and build again.")
    notes = []
    if a.cuts:
        n, d = import_cuts(p, a.cuts, a.cuts_media or first_video(p))
        notes.append(f"footage: {n} clips from the cut list, {d:.2f} s kept")
    if a.captions:
        n, w = import_captions(p, a.captions, a.captions_media or first_video(p), a.words_per_caption,
                               a.caption_style, a.max_chars)
        notes.append(f"captions: {n} elements from {w} words")
    if a.sfx:
        notes.append(f"sounds: {import_sfx(p, a.sfx)} elements from the sound-design render")
    report_errors(check(p, src.parent), src)
    total = place_media(p, [src.parent], out)
    write_version(out, p, 1, None, a.note, a.name)
    print_summary(p, total, notes)
    print("->", out, "(version 1)")
    blocked = chrome_blocked(out)
    if blocked:
        print(f"note: Chrome will not let the studio open a folder inside {blocked} (it says the folder \"contains system "
              f"files\"). Move {out.name} to Documents, the Desktop or the person's project folder before you give it "
              "to them, or build it there.")


def chrome_blocked(folder):
    """The system folder a path is in that Chrome's folder picker refuses on this computer, or None. Only Windows and
    macOS: in a sandbox the person downloads the folder anyway."""
    path = Path(folder).resolve()
    if sys.platform.startswith("win"):
        roots = [("AppData", Path.home() / "AppData"), ("Temp", Path(tempfile.gettempdir())),
                 ("Program Files", Path(os.environ.get("ProgramFiles", r"C:\Program Files"))),
                 ("Windows", Path(os.environ.get("SystemRoot", r"C:\Windows")))]
    elif sys.platform == "darwin":
        roots = [("Library", Path.home() / "Library"), ("a temporary folder", Path(tempfile.gettempdir()).resolve()),
                 ("System", Path("/System"))]
    else:
        return None
    for name, root in roots:
        try:
            path.relative_to(root.resolve())
            return name
        except (ValueError, OSError):
            continue
    return None


# ------------------------------------------------------------------ save: the agent's next version
def cmd_save(a):
    src, p = load_project(a.project)
    out = Path(a.to)
    if not (out / "project.json").is_file():
        die(f"no project.json in {out}; run package.py build first")
    have = version_files(out)
    if not have:                                     # made before versions: project.json counts as version 1
        old = json.loads((out / "project.json").read_text(encoding="utf-8"))
        write_version(out, old, 1, None, "", "Claude")
        print(f"{out} had no versions/: wrote its project.json as version 1")
        have = version_files(out)
    newest = max(have)
    if a.from_ not in have:
        die(f"there is no version {a.from_} in {out}; it has " + ", ".join(f"v{n}" for n in have))
    if newest > a.from_ and not a.force:
        v = read_version(have[newest])
        die(f"version {newest} was saved by {who(v)} at {v.get('made')}, after version {a.from_}"
            + (f' (note: "{v["note"]}")' if v.get("note") else "") + ". Nothing written. Read it with package.py "
            f"changes {out}, make your change on top of its project.json and save with --from {newest}. Use --force "
            f"only to save from version {a.from_} anyway.")
    report_errors(check(p, [out, src.parent]), src)
    total = place_media(p, [out, src.parent], out)
    n = newest + 1
    write_version(out, p, n, a.from_, a.note, a.name)
    print_summary(p, total)
    lines = change_summary(read_version(have[a.from_]).get("project") or {}, p)
    print(f"changes from version {a.from_}:" if lines else f"no changes from version {a.from_}")
    for line in lines:
        print("-", line)
    print("->", out, f"(version {n}, from version {a.from_}"
          + (f"; saved over version {newest} with --force" if newest > a.from_ else "") + ")")
    print(f"version {n}")


# ------------------------------------------------------------------ versions and changes
def cmd_versions(a):
    out = Path(a.folder)
    have = version_files(out)
    pj = out / "project.json"
    if not have:
        print(f"{out}: no versions/ yet" + (": project.json counts as version 1" if pj.is_file() else ""))
        return
    current = json.loads(pj.read_text(encoding="utf-8")) if pj.is_file() else None
    match = None
    for n in sorted(have, reverse=True):
        v = read_version(have[n])
        if match is None and current is not None and v.get("project") == current:
            match = n
        par = "first" if v.get("parent") is None else f"from v{v['parent']}"
        print(f"v{n}  {who(v)}  {v.get('made')}  {par}" + (f'  "{v["note"]}"' if v.get("note") else ""))
    newest = max(have)
    if current is None:
        print("project.json: missing")
    elif match == newest:
        print(f"project.json = v{newest} (the newest)")
    elif match:
        print(f"project.json = v{match}, not the newest (v{newest})")
    else:
        print("project.json matches no version: it was edited without saving a version")


def cmd_changes(a):
    out = Path(a.folder)
    have = version_files(out)
    if not have:
        die(f"{out} has no versions/")
    to = a.to or max(have)
    if to not in have:
        die(f"there is no version {to} in {out}")
    vt = read_version(have[to])
    frm = a.from_ if a.from_ is not None else vt.get("parent")
    print(f"v{to} by {who(vt)}, {vt.get('made')}" + ("" if vt.get("parent") is None else f", from v{vt['parent']}"))
    if vt.get("note"):
        print("note:", vt["note"])
    if frm is None:
        print(f"v{to} is the first version; nothing to compare it with")
        return
    if frm not in have:
        die(f"there is no version {frm} in {out}")
    lines = change_summary(read_version(have[frm])["project"], vt["project"])
    print(f"changes from v{frm} to v{to}:" if lines else f"no changes from v{frm} to v{to}")
    for line in lines:
        print("-", line)


# ------------------------------------------------------------------ what changed, in the studio's words
# A port of the studio's changeSummary(a, b), so the agent and the person read the same lines. JS details kept:
# JSON.stringify for equality, `||` (an empty list is truthy), Math.round, String(number), UTF-16 string lengths.
MISSING = object()                                    # JS undefined
NAMES = {"at": "start", "dur": "length", "in": "in point", "out": "out point", "gain_db": "volume (dB)",
         "fade_in": "fade in", "fade_out": "fade out", "x": "x", "y": "y", "width": "width", "size": "size",
         "text": "text", "color": "colour", "rotation": "rotation", "opacity": "opacity", "volume": "volume",
         "scale": "zoom", "zoom_to": "zoom at the end", "style": "style", "speed": "speed"}


def js_truthy(v):
    if v is MISSING or v is None or v is False:
        return False
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return not (v == 0 or v != v)
    return v != ""


def js_or(*vs):
    for v in vs[:-1]:
        if js_truthy(v):
            return v
    return vs[-1]


def js_num(x):
    """String(x) for a JS number."""
    if isinstance(x, int):
        return str(x)
    if x != x:
        return "NaN"
    if x in (math.inf, -math.inf):
        return "Infinity" if x > 0 else "-Infinity"
    if x == 0:
        return "0"
    sign, s = ("-" if x < 0 else ""), repr(abs(x))
    mant, _, e = s.partition("e")
    ip, _, fp = mant.partition(".")
    digits, exp = (ip + fp).lstrip("0"), int(e or 0) - len(fp)
    while digits.endswith("0"):
        digits, exp = digits[:-1], exp + 1
    k, n = len(digits), len(digits) + exp           # value = 0.digits * 10^n
    if k <= n <= 21:
        return sign + digits + "0" * (n - k)
    if 0 < n <= 21:
        return sign + digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return sign + "0." + "0" * -n + digits
    ee = n - 1
    return sign + (digits if k == 1 else digits[0] + "." + digits[1:]) + "e" + ("+" if ee >= 0 else "-") + str(abs(ee))


ESCAPES = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def js_str(s):
    """JSON.stringify for a string (control characters and lone surrogates escaped, as JS does)."""
    out = []
    for ch in s:
        o = ord(ch)
        if ch in ESCAPES:
            out.append(ESCAPES[ch])
        elif o < 0x20 or 0xD800 <= o <= 0xDFFF:
            out.append(f"\\u{o:04x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def js_keys(o):
    """Object.keys order: array-index keys ascending, then the rest in insertion order."""
    if not isinstance(o, dict):
        return []
    idx = [k for k in o if re.fullmatch(r"0|[1-9]\d*", k) and int(k) < 4294967295]
    return sorted(idx, key=int) + [k for k in o if k not in idx]


def js_json(v):
    """JSON.stringify(v); MISSING (undefined) gives None, as JS gives undefined."""
    if v is MISSING:
        return None
    if v is None:
        return "null"
    if v is True or v is False:
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return "null" if isinstance(v, float) and (v != v or v in (math.inf, -math.inf)) else js_num(v)
    if isinstance(v, str):
        return js_str(v)
    if isinstance(v, list):
        return "[" + ",".join(js_json(x) or "null" for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ",".join(js_str(k) + ":" + js_json(v[k]) for k in js_keys(v) if v[k] is not MISSING) + "}"
    return js_str(str(v))


def u16_slice(s, n):
    """s.slice(0, n), counted in UTF-16 units as JS does."""
    return s.encode("utf-16-le", "surrogatepass")[:2 * n].decode("utf-16-le", "surrogatepass")


def u16_len(s):
    return len(s.encode("utf-16-le", "surrogatepass")) // 2


def js_template(v):
    """`${v}` in a JS template string."""
    if v is MISSING:
        return "undefined"
    if v is None:
        return "null"
    if v is True or v is False:
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return js_num(v)
    if isinstance(v, list):
        return ",".join("" if x is None or x is MISSING else js_template(x) for x in v)
    if isinstance(v, dict):
        return "[object Object]"
    return str(v)


def js_is(a, b):
    """a === b for values read from JSON."""
    if a is MISSING or b is MISSING or a is None or b is None or isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    return a is b


def get(o, k):
    return o.get(k, MISSING) if isinstance(o, dict) else MISSING


def r3(x):
    """Math.round(x * 1000) / 1000 (Math.round: halves go up)."""
    y = x * 1000
    if y != y or y in (math.inf, -math.inf):
        return y
    r = math.floor(y)
    return (r + 1 if y - r >= 0.5 else r) / 1000


def val(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return js_num(r3(v))
    if isinstance(v, str):
        return js_str(u16_slice(v, 48) + "…" if u16_len(v) > 48 else v)
    if v is None or v is MISSING:
        return "none"
    return u16_slice(js_json(v), 60)


def anim(v):
    """How a text or graphic appears or leaves, in words: its style's way when it has none of its own."""
    if v is MISSING:
        return "as its style"
    if v is None or not isinstance(v, dict) or not js_truthy(get(v, "type")):
        return "off"
    return js_template(get(v, "type"))


def js_plus(v):
    """+v in JS for a value read from JSON."""
    if v is MISSING:
        return math.nan
    if v is None or v is False:
        return 0
    if v is True:
        return 1
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        try:
            return float(v.strip()) if v.strip() else 0
        except ValueError:
            return math.nan
    return math.nan


def trans(v):
    """A transition into a clip, in words."""
    if not js_truthy(v) or not js_truthy(get(v, "type")):
        return "cut"
    d = js_plus(get(v, "dur"))
    return f"{js_template(get(v, 'type'))} {js_num(r3(d if js_truthy(d) else 0.5))} s"


def pts(v):
    """The points of a sound's volume line, in words."""
    if not js_truthy(v) or not isinstance(v, list) or not v:
        return "flat"

    def one(k):
        db, t = js_plus(get(k, "db")), js_plus(get(k, "t"))
        sign = "+" if isinstance(get(k, "db"), (int, float)) and not isinstance(get(k, "db"), bool) and get(k, "db") > 0 else ""
        return f"{sign}{js_num(r3(db if js_truthy(db) else 0))} dB at {js_num(r3(t if js_truthy(t) else 0))} s"
    return f"{len(v)} point{'s' if len(v) > 1 else ''} (" + ", ".join(one(k) for k in v[:4]) + (", …" if len(v) > 4 else "") + ")"


def change_summary(a, b):
    """The studio's changeSummary(a, b): lines that say what changed from project a to project b."""
    out = []

    def keys(*os):
        return list(dict.fromkeys(k for o in os for k in js_keys(js_or(o, {}))))

    def same(x, y):
        return js_json(x) == js_json(y)

    def name(k):
        return NAMES.get(k) or k.replace("_", " ")

    def find(lst, i):
        return next((x for x in lst if js_is(get(x, "id"), i)), None)

    def label(tr, it):
        kind, i = get(tr, "kind"), js_template(get(it, "id"))
        if kind == "text":
            return f"text {val(get(it, 'text'))} ({i})"
        if kind == "audio":
            return f"sound {js_template(js_or(get(it, 'label'), get(it, 'media')))} ({i})"
        if kind == "video":
            return f"clip {i}"
        return f"graphic {js_template(get(it, 'media'))} ({i})"

    ta_title, tb_title = js_or(get(a, "title"), ""), js_or(get(b, "title"), "")
    if not js_is(ta_title, tb_title):
        out.append(f"project name {val(ta_title)} → {val(tb_title)}")
    ma, mb = js_or(get(a, "media"), {}), js_or(get(b, "media"), {})
    for k in keys(get(a, "media"), get(b, "media")):
        x, y = get(ma, k), get(mb, k)
        m = y if js_truthy(y) else x
        if js_truthy(x) == js_truthy(y):
            continue
        if js_is(get(m, "kind"), "font"):
            what = f"font {val(get(m, 'family'))} {js_template(js_or(get(m, 'weight'), 400))}{' italic' if js_is(get(m, 'style'), 'italic') else ''}"
        else:
            what = js_template(get(m, "kind"))
        out.append(f"{what} file {js_template(get(m, 'path'))}: {'added' if js_truthy(y) else 'removed'}")
    sa, sb = js_or(get(a, "styles"), {}), js_or(get(b, "styles"), {})
    for k in keys(get(a, "styles"), get(b, "styles")):
        x, y = get(sa, k), get(sb, k)
        if not js_truthy(x):
            out.append(f"style {k}: added")
        elif not js_truthy(y):
            out.append(f"style {k}: removed")
        else:
            for f in keys(x, y):
                if not same(get(x, f), get(y, f)):
                    out.append(f"style {k} (every element that uses it): {name(f)} {val(get(x, f))} → {val(get(y, f))}")
    tracks_a, tracks_b = js_or(get(a, "tracks"), []), js_or(get(b, "tracks"), [])
    for tb in tracks_b:
        ta = find(tracks_a, get(tb, "id"))
        tname = js_template(js_or(get(tb, "name"), get(tb, "id")))
        if ta is None:
            out.append(f"track {tname}: added")
            for it in js_or(get(tb, "clips"), get(tb, "items"), []):
                out.append(f"{label(tb, it)}: added")
            continue
        if js_truthy(get(ta, "hidden")) != js_truthy(get(tb, "hidden")):
            out.append(f"track {tname}: {'hidden' if js_truthy(get(tb, 'hidden')) else 'shown'}")
        if js_truthy(get(ta, "muted")) != js_truthy(get(tb, "muted")):
            out.append(f"track {tname}: {'muted' if js_truthy(get(tb, 'muted')) else 'unmuted'}")
        ia = js_or(get(ta, "clips"), get(ta, "items"), [])
        ib = js_or(get(tb, "clips"), get(tb, "items"), [])
        for it in ia:
            if find(ib, get(it, "id")) is None:
                out.append(f"{label(ta, it)}: removed")
        for it in ib:
            was = find(ia, get(it, "id"))
            if was is None:
                out.append(f"{label(tb, it)}: added")
                continue
            for f in keys(was, it):
                if not same(get(was, f), get(it, f)):
                    if f in ("in", "out") and get(tb, "kind") in ("text", "image"):
                        out.append(f"{label(tb, was)}: {'appears' if f == 'in' else 'disappears'} {anim(get(was, f))} → {anim(get(it, f))}")
                    elif f == "transition":
                        out.append(f"{label(tb, was)}: transition into it {trans(get(was, f))} → {trans(get(it, f))}")
                    elif f == "gain_keys":
                        out.append(f"{label(tb, was)}: volume line {pts(get(was, f))} → {pts(get(it, f))}")
                    else:
                        out.append(f"{label(tb, was)}: word timings" if f == "words" else
                                   f"{label(tb, was)}: {name(f)} {val(get(was, f))} → {val(get(it, f))}")
        if js_truthy(get(tb, "clips")) and not same([get(c, "id") for c in ia],
                                                    [get(c, "id") for c in ib if find(ia, get(c, "id")) is not None]):
            out.append(f"track {tname}: clips in a new order")
    for ta in tracks_a:
        if find(tracks_b, get(ta, "id")) is None:
            out.append(f"track {js_template(js_or(get(ta, 'name'), get(ta, 'id')))}: removed")
    return out


# ------------------------------------------------------------------ check
def check_folder(d):
    """Problems and warnings for the versions in a package folder."""
    errs, warns = [], []
    have = version_files(d)
    pj = d / "project.json"
    if not have:
        if pj.is_file():
            warns.append("no versions/ yet: project.json counts as version 1 (the first save writes versions/v1.json)")
        return errs, warns
    nums = list(have)
    if nums != list(range(1, len(nums) + 1)):
        errs.append("version numbers must be 1, 2, 3 ... with no gaps; found " + ", ".join(f"v{n}" for n in nums))
    newest = None
    for n in nums:
        where = f"versions/v{n}.json"
        try:
            v = read_version(have[n])
        except ValueError as e:
            errs.append(f"{where}: not JSON ({e})")
            continue
        if v.get("format") != VERSION_FORMAT:
            errs.append(f"{where}: format must be {VERSION_FORMAT!r}")
        if v.get("version") != n:
            errs.append(f"{where}: says version {v.get('version')!r}")
        par = v.get("parent")
        if n == 1 and par is not None:
            errs.append(f"{where}: version 1 has parent null")
        if n > 1 and not (isinstance(par, int) and not isinstance(par, bool) and 1 <= par < n):
            errs.append(f"{where}: parent must be an earlier version (1 to {n - 1}), not {par!r}")
        if v.get("by") not in ("agent", "studio"):
            errs.append(f"{where}: by must be 'agent' or 'studio'")
        if not isinstance(v.get("name"), str):
            errs.append(f"{where}: name must be text")
        if not isinstance(v.get("note"), str) or len(v["note"]) > 500:
            errs.append(f"{where}: note must be text of at most 500 characters")
        try:
            datetime.fromisoformat(str(v.get("made")).replace("Z", "+00:00"))
        except ValueError:
            errs.append(f"{where}: made must be an ISO 8601 time, not {v.get('made')!r}")
        p = v.get("project")
        if not isinstance(p, dict):
            errs.append(f"{where}: no project")
            continue
        errs += [f"{where}: {e}" for e in check(p)]
        for mid, m in (p.get("media") or {}).items():
            if m.get("path") and not (d / m["path"]).is_file():
                errs.append(f"{where}: media {mid}: {m['path']} is not in the folder")
        if n == nums[-1]:
            newest = p
    if newest is not None and pj.is_file() and json.loads(pj.read_text(encoding="utf-8")) != newest:
        warns.append(f"project.json is not the newest version (v{nums[-1]}): someone edited it without saving a "
                     "version. See what differs before you render or hand it over.")
    return errs, warns


def cmd_check(a):
    d = Path(a.package)
    f = d / "project.json" if d.is_dir() else d
    errs, warns = [], []
    if f.is_file():
        errs = check(json.loads(f.read_text(encoding="utf-8")), f.parent)
    elif d.is_dir():
        errs.append("no project.json")
    else:
        die(f"no such file or folder: {d}")
    if d.is_dir():
        e2, warns = check_folder(d)
        errs += e2
    for e in errs:
        print("error:", e)
    for w in warns:
        print("warning:", w)
    n = len(version_files(d)) if d.is_dir() else 0
    print(f"{f}: " + ("ok" if not errs else f"{len(errs)} problem(s)") + (f", {n} versions" if n else ""))
    sys.exit(1 if errs else 0)


def first_video(p):
    return next((k for k, m in p["media"].items() if m.get("kind") == "video"), None) or die("no video in media")


def timeline_duration(p):
    v = next((t for t in p["tracks"] if t["kind"] == "video" and t.get("clips")), None)
    if v:
        return sum((c["out"] - c["in"]) / (c.get("speed") or 1) for c in v["clips"])
    end = 0.0
    for t in p["tracks"]:
        for x in t.get("items") or []:
            end = max(end, x["at"] + (x.get("dur") or 0))
    return end


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="check, copy the files, write versions/v1.json and project.json")
    b.add_argument("project")
    b.add_argument("--out", required=True, help="the package folder to write (NAME.edit)")
    b.add_argument("--cuts", help="transcribe's cuts.json: footage clips are the parts kept")
    b.add_argument("--cuts-media", help="media id the cut list is for (default: the first video)")
    b.add_argument("--captions", help="transcribe's transcript.json: caption elements with word timing")
    b.add_argument("--captions-media", help="media id the transcript is for (default: the first video)")
    b.add_argument("--caption-style", default="caption")
    b.add_argument("--words-per-caption", type=int, default=3)
    b.add_argument("--max-chars", type=int, default=24)
    b.add_argument("--sfx", help="sound-design's _resolved.json: sound elements at their rendered times and levels")
    b.add_argument("--note", default="", help="what you made, kept with the version")
    b.add_argument("--name", default="Claude", help="who saved it (default: %(default)s)")
    s = sub.add_parser("save", help="your next version: check, add new files to media/, write versions/v<n>.json "
                                    "and project.json")
    s.add_argument("project", help="your edited copy of the folder's project.json")
    s.add_argument("--to", required=True, help="the package folder (NAME.edit)")
    s.add_argument("--from", dest="from_", type=int, required=True, help="the version you started from")
    s.add_argument("--note", default="", help="what you changed, shown to the person in the studio")
    s.add_argument("--name", default="Claude", help="who saved it (default: %(default)s)")
    s.add_argument("--force", action="store_true", help="save even when someone saved after --from")
    c = sub.add_parser("check", help="check a project.json, or a package folder and every version in it")
    c.add_argument("package")
    v = sub.add_parser("versions", help="list the versions in a package folder, newest first")
    v.add_argument("folder")
    g = sub.add_parser("changes", help="what changed between two versions (default: the newest and its parent)")
    g.add_argument("folder")
    g.add_argument("--from", dest="from_", type=int)
    g.add_argument("--to", type=int)
    a = ap.parse_args()
    {"build": cmd_build, "save": cmd_save, "check": cmd_check, "versions": cmd_versions, "changes": cmd_changes}[a.cmd](a)


if __name__ == "__main__":
    main()
