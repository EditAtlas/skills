"""Turn a finished edit into an editable package: its elements and their files, for the EditAtlas studio.

  package.py build work/project.json --out result/my-video.edit
  package.py build work/project.json --out result/my-video.edit \
      --cuts work/cuts.json --captions work/transcript.json --sfx result/film_sfx_resolved.json
  package.py check result/my-video.edit

`build` checks project.json (references/project-format.md), copies every file it uses into OUT/media/, measures
the footage and sounds, and writes OUT/project.json. The folder is what the studio opens (Choose the folder),
what render.py renders and what share.py sends.

Optional imports, so you do not write hundreds of elements by hand:
  --cuts cuts.json        transcribe's cut list -> the footage clips (the parts kept), for --cuts-media
  --captions FILE.json    transcribe's transcript.json -> caption elements with word timing (style "caption")
  --sfx RESOLVED.json     sound-design's _resolved.json -> sound elements at the same times and levels
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

FORMAT = "editatlas-project/1"
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
def check(p, base=None):
    """A list of problems; empty when the project can be built."""
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
        elif base is not None and not (Path(base) / m["path"]).is_file() and not Path(m["path"]).is_file():
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
    if nvideo > 1:
        errs.append("use one video track (the footage); put other pictures on image tracks")
    errs += check_cards(p)
    for name, st in styles.items():
        font = st.get("font")
        if font and font != "sans-serif" and not any(m.get("kind") == "font" and m.get("family") == font for m in media.values()):
            errs.append(f"style {name}: font {font!r} has no font file in media (the studio would fall back to sans-serif)")
    return errs


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
        d = c["out"] - c["in"]
        if c["media"] == media_id and c["in"] - 1e-6 <= s < c["out"]:
            return t + (s - c["in"])
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


# ------------------------------------------------------------------ build
def cmd_build(a):
    src = Path(a.project).resolve()
    base = src.parent
    p = json.loads(src.read_text(encoding="utf-8"))
    p.setdefault("media", {})
    p.setdefault("tracks", [])
    p.setdefault("styles", {})
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
    errs = check(p, base)
    if errs:
        for e in errs:
            print("error:", e)
        die(f"{len(errs)} problem(s) in {src.name}; nothing written")

    out = Path(a.out)
    (out / "media").mkdir(parents=True, exist_ok=True)
    used = set()
    total = 0
    for mid, m in p["media"].items():
        f = (base / m["path"]) if (base / m["path"]).is_file() else Path(m["path"])
        name = safe_name(f.name, used)
        dst = out / "media" / name
        if not dst.is_file() or dst.stat().st_size != f.stat().st_size:
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

    (out / "project.json").write_text(json.dumps(p, indent=1, ensure_ascii=False), encoding="utf-8", newline="\n")

    dur = timeline_duration(p)
    counts = {k: sum(len(t.get("items") or t.get("clips") or []) for t in p["tracks"] if t["kind"] == k) for k in TRACK_KINDS}
    for n in notes:
        print(n)
    print(f"{p['canvas']['width']}x{p['canvas']['height']} at {p['canvas']['fps']} fps, {dur:.2f} s: "
          f"{counts['video']} clips, {counts['text']} text, {counts['image']} graphics, {counts['audio']} sounds")
    print(f"package {total / 1e6:.1f} MB in {len(p['media'])} files; footage: "
          + ", ".join(m["path"] for m in p["media"].values() if m["kind"] == "video"))
    if total > 300e6:
        print("warning: over 300 MB, more than a studio link holds. share.py says how to make the footage smaller.")
    print("->", out)


def first_video(p):
    return next((k for k, m in p["media"].items() if m.get("kind") == "video"), None) or die("no video in media")


def safe_name(name, used):
    stem, ext = os.path.splitext(re.sub(r"[^\w.\-]+", "-", name).strip("-") or "file")
    n, k = stem + ext, 2
    while n.lower() in used:
        n, k = f"{stem}-{k}{ext}", k + 1
    used.add(n.lower())
    return n


def timeline_duration(p):
    v = next((t for t in p["tracks"] if t["kind"] == "video" and t.get("clips")), None)
    if v:
        return sum(c["out"] - c["in"] for c in v["clips"])
    end = 0.0
    for t in p["tracks"]:
        for x in t.get("items") or []:
            end = max(end, x["at"] + (x.get("dur") or 0))
    return end


def cmd_check(a):
    d = Path(a.package)
    f = d / "project.json" if d.is_dir() else d
    p = json.loads(f.read_text(encoding="utf-8"))
    errs = check(p, f.parent)
    for e in errs:
        print("error:", e)
    print(f"{f}: " + ("ok" if not errs else f"{len(errs)} problem(s)"))
    sys.exit(1 if errs else 0)


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="check, copy the files, write project.json")
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
    c = sub.add_parser("check", help="check a project.json or a package folder")
    c.add_argument("package")
    a = ap.parse_args()
    (cmd_build if a.cmd == "build" else cmd_check)(a)


if __name__ == "__main__":
    main()
