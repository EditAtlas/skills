#!/usr/bin/env python3
"""Place picked B-roll on the words of a voice-over or talking head, match its colour, and keep it off the face.

    python place.py --words work/transcript.json --picks work/picks.json --out work/place \\
        --speaker work/talking-head.mp4 --target 1080x1920

--words: word times as the transcribe skill writes them ({"words": [{"w", "start", "end"}]}), on the timeline of
the finished video (transcript_cut.json after a cut). --picks: the clips you chose, in timeline order, each with the
words it shows:

    {"clips": [{"id": "jar", "file": "work/assets/files/jar.mp4", "shows": "a big glass jar"},
               {"id": "ice", "file": "work/assets/files/ice.mp4", "shows": "over ice", "layout": "pip"}]}

Optional per clip: "layout" ("cutaway", the default: the clip fills the frame; "pip": a box beside the speaker),
"word" (the index of the word to start on, when "shows" is ambiguous), "in" (source second to start from, instead of
the steadiest stretch), "max" (longest it may stay), "credit".

Each clip starts LEAD s before the first word of what it shows, stays MIN to MAX s, and ends at a sentence or phrase
end, at the next clip, or at the end of its own footage; never inside a word. Clips do not overlap, and the speaker
gets at least GAP s back between two clips (or the clips are joined cut to cut). The part of the clip used is its
steadiest stretch of exactly that length (measure.py's shake). Each clip's colour is measured against the speaker
(or --match-to, or the middle of the picks) in Lab, and a 3D LUT moves it STRENGTH of the way there.

Writes <out>/placements.json and placements.md (read these), fragment.json (an editable-export project with the
B-roll, the voice and the speaker; run package.py build on it, or pass --into to merge into an existing
project.json), luts/*.cube, media/ (graded copies, the voice, PiP animations; skipped with --no-media), and
speaker_grid.png (the speaker on the canvas with a grid, to read the face box from).
"""
import argparse
import difflib
import json
import math
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure  # noqa: E402  (same folder)

VERSION = "0.1.0"
THREADS = "4"
# Phrase ends: punctuation, or a pause of PAUSE s before the next word.
PAUSE = 0.3
SENTENCE_END = re.compile(r"[.!?…。！？][\"'”’)\]]*$")
PHRASE_END = re.compile(r"[,;:—–][\"'”’)\]]*$")
# Head box around a detected or marked face: room for hair above, ears beside, chin below (fractions of the face).
HEAD_ABOVE, HEAD_SIDES, HEAD_BELOW = 0.5, 0.2, 0.25
# Colour moves are capped so a sunset stays warm and a night shot stays dark (Lab units; spread ratios).
CAP_L, CAP_AB = 20.0, 8.0
CAP_SPREAD_L, CAP_SPREAD_AB = (0.8, 1.25), (0.75, 1.3)
LUT_SIZE = 33
# Words a clip does not start on when they open what it shows.
LEADING = {"a", "an", "the", "some", "my", "your", "this", "that"}


def fail(message):
    sys.exit(f"place: {message}")


def run(cmd, **kw):
    try:
        return subprocess.run(cmd, capture_output=True, **kw)
    except FileNotFoundError:
        fail(f"{cmd[0]} is not installed or not in PATH")


# ---------------------------------------------------------------- words

def load_words(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    raw = data["words"] if isinstance(data, dict) else data
    words = []
    for w in raw:
        text = str(w.get("w", w.get("word", w.get("text", "")))).strip()
        if text and w.get("start") is not None and w.get("end") is not None:
            words.append({"w": text, "start": float(w["start"]), "end": float(w["end"])})
    if not words:
        fail(f"no words with start and end in {path}")
    words.sort(key=lambda w: w["start"])
    duration = float(data.get("duration") or words[-1]["end"]) if isinstance(data, dict) else words[-1]["end"]
    return words, max(duration, words[-1]["end"])


def norm(text):
    text = unicodedata.normalize("NFC", text).lower()
    return [t for t in re.split(r"[^\w']+", text) if t.strip("'")]


def tokens(words):
    """Sub-word tokens with the index of their word: "noise-cancelling" gives two tokens of one word."""
    flat = []
    for i, w in enumerate(words):
        flat += [(t, i) for t in norm(w["w"])]
    return flat


def similar(a, b):
    """The same word, or the same word spelled a little differently (canceling, cancelling)."""
    return a == b or (min(len(a), len(b)) >= 4 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.85)


def find_phrase(words, flat, phrase, after):
    """Index of the first and last word of `phrase` in the words: the first exact match starting at or after word
    `after`, else the first exact match anywhere, else the best loose match. Returns (first, last, how, others)."""
    want = norm(phrase)
    if not want:
        return None
    toks = [t for t, _ in flat]
    n = len(want)
    exact = [k for k in range(len(toks) - n + 1) if toks[k:k + n] == want]
    if exact:
        pick = next((k for k in exact if flat[k][1] >= after), exact[0])
        how = "exact" if flat[pick][1] >= after else "exact, but before the clip listed above it"
        return flat[pick][1], flat[pick + n - 1][1], how, [round(words[flat[k][1]]["start"], 2) for k in exact if k != pick]
    best = None
    for k in range(len(toks)):
        window = toks[k:k + n + 2]
        hits, j = 0, 0
        for t in want:  # in order; "canceling" counts for "cancelling", a missing word is skipped, not searched past
            near = next((x for x in range(j, len(window)) if similar(t, window[x])), None)
            if near is not None:
                hits, j = hits + 1, near + 1
        score = hits / n
        if score >= 0.6 and (best is None or score > best[0] or (score == best[0] and flat[best[1]][1] < after <= flat[k][1])):
            first = k + next(j for j, t in enumerate(window) if any(similar(t, x) for x in want))
            last = k + max(j for j, t in enumerate(window) if any(similar(t, x) for x in want))
            best = (score, first, last)
    if best is None:
        return None
    return flat[best[1]][1], flat[best[2]][1], f"loose ({int(best[0] * 100)}% of the words): check it", []


def boundaries(words):
    """For each word: 'sentence', 'phrase' or '' for what follows it, and the time just after it (never in a word)."""
    out = []
    for i, w in enumerate(words):
        nxt = words[i + 1]["start"] if i + 1 < len(words) else w["end"] + 1.0
        gap = max(0.0, nxt - w["end"])
        kind = "sentence" if SENTENCE_END.search(w["w"]) else "phrase" if PHRASE_END.search(w["w"]) or gap >= PAUSE else ""
        if i + 1 == len(words):
            kind = "sentence"
        out.append((kind, w["end"] + min(0.12, gap / 2)))
    return out


# ---------------------------------------------------------------- clips

def usable_runs(cuts, length):
    """Stretches of the clip between its inside cuts, as (start, end) seconds."""
    marks = [0.0] + [c / measure.MOTION_FPS for c in cuts] + [length]
    return [(a, b) for a, b in zip(marks, marks[1:]) if b - a > 0.2]


def clip_info(path):
    info = measure.probe(path)
    kind = measure.kind_of(path, info)
    if kind == "photo":
        w, h = Image.open(path).size
        return {"kind": "photo", "width": w, "height": h, "duration": None, "longest": float("inf"), "fps": None}
    if kind != "video":
        fail(f"{path} is {kind}, not a video or photo")
    width, height = measure.probe_frame_size(path)
    stream = next(s for s in info["streams"] if s.get("codec_type") == "video")
    num, _, den = (stream.get("avg_frame_rate") or "30/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 30.0
    length = float(info.get("format", {}).get("duration") or stream.get("duration") or 0)
    frames = measure.gray_frames(path, min(length, measure.MAX_VIDEO_SECONDS) + 0.5)
    cuts = measure.cuts_in(frames)
    _, _, jitter, _ = measure.motion(frames, cuts)
    runs = usable_runs(cuts, length)
    return {"kind": "video", "width": width, "height": height, "duration": length, "fps": fps, "cuts": cuts,
            "jitter": jitter, "longest": max((b - a for a, b in runs), default=length)}


def stretch(info, length, start_at=None):
    """The source in and out for `length` s of the clip: from start_at, or its steadiest stretch without a cut."""
    if info["kind"] == "photo":
        return 0.0, length, None
    if start_at is not None:
        a = max(0.0, min(float(start_at), info["duration"] - length))
        return a, a + length, None
    s = measure.steadiest(info["jitter"], info["cuts"], info["duration"], length)
    if s is None:
        return 0.0, min(length, info["duration"]), None
    a = min(s["start"], max(0.0, info["duration"] - length))
    return a, a + length, s["shake"]


# ---------------------------------------------------------------- timing

def plan(words, picks, infos, args, duration):
    toks = tokens(words)
    ends = boundaries(words)
    fps = args.fps
    snap = lambda t: round(round(t * fps) / fps, 3)  # noqa: E731
    rows, after = [], 0
    for pick in picks:
        row = {"id": pick["id"], "file": pick["file"], "shows": pick.get("shows", ""), "layout": pick.get("layout", "cutaway"),
               "flags": []}
        if "word" in pick:
            first = int(pick["word"])
            found = (first, first + max(0, len(norm(pick.get("shows", ""))) - 1), "word given", [])
        else:
            found = find_phrase(words, toks, pick.get("shows", ""), after)
        if not found:
            row["flags"].append(f"the words {pick.get('shows')!r} are not in the transcript: give \"word\" (an index) or fix \"shows\"")
            row["skip"] = True
            rows.append(row)
            continue
        first, last, how, others = found
        last = min(max(first, last), len(words) - 1)
        while first < last and (norm(words[first]["w"]) or [""])[0] in LEADING:  # start on "fridge", not "the"
            first += 1
        after = first + 1
        word = words[first]
        lead_room = word["start"] - (words[first - 1]["end"] if first else 0.0)
        start = word["start"] - min(args.lead, max(0.0, lead_room))
        row.update(word_index=first, word=word["w"], word_at=round(word["start"], 3), last_word=last,
                   said=" ".join(w["w"] for w in words[first:last + 1]), start=snap(max(0.0, start)), match=how)
        if how != "exact":
            row["flags"].append(f"matched {how}: '{row['said']}'")
        if others:
            row["flags"].append(f"these words are also said at {', '.join(f'{t:.2f}s' for t in others)}: give \"word\" if you meant another")
        rows.append(row)
    live = sorted([r for r in rows if not r.get("skip")], key=lambda r: r["start"])
    for k, row in enumerate(live):
        info = infos[row["id"]]
        pick = next(p for p in picks if p["id"] == row["id"])
        s = row["start"]
        nxt = live[k + 1]["start"] if k + 1 < len(live) else None
        top = min(float(pick.get("max", args.max_len)), info["longest"], duration - s)
        limit = min(s + top, nxt) if nxt is not None else s + top
        need = words[row["last_word"]]["end"]
        cands = [(i, kind, t) for i, (kind, t) in enumerate(ends) if i >= row["last_word"] and kind and t <= limit + 1e-6]
        long_enough = [c for c in cands if c[2] - s >= args.min_len]
        sentence = [c for c in long_enough if c[1] == "sentence"]
        if sentence:
            i, kind, end = sentence[0]
            why = f"sentence end after '{words[i]['w']}'"
        elif long_enough:
            i, kind, end = long_enough[0]
            why = f"phrase end after '{words[i]['w']}'"
        elif nxt is not None and nxt <= s + top + 1e-6:
            end, why = nxt, "the next clip starts"
        else:
            inside = [(i, t) for i, (kind, t) in enumerate(ends) if t <= limit + 1e-6 and t > s]
            if inside:
                i, end = inside[-1]
                where = f"{ends[i][0]} end" if ends[i][0] else "between words"
                why = f"{where} after '{words[i]['w']}' ({'its own footage ends' if info['longest'] < args.max_len and limit - s >= info['longest'] - 0.05 else 'the longest it may stay'})"
                if not ends[i][0]:
                    row["flags"].append("ends between two words of a phrase: no phrase end fits; shorten what it shows or pick a longer clip")
            else:
                end, why = min(limit, need), "no word end fits"
        # Back to the speaker for at least GAP s, or join to the next clip.
        if nxt is not None and args.speaker and 0 < nxt - end < args.gap:
            if nxt - s <= top + 1e-6:
                end, why = nxt, f"joined to the next clip (the speaker would be back for only {nxt - end:.1f}s)"
            else:
                earlier = [t for kind, t in ends if t - s >= args.min_len and nxt - t >= args.gap and t < end]
                if earlier:
                    end, why = earlier[-1], f"earlier phrase end, so the speaker is back {args.gap}s or more before the next clip"
                else:
                    row["flags"].append(f"the speaker is back for only {nxt - end:.1f}s before the next clip: drop one of the two or move it")
        if nxt is not None and not args.speaker and nxt - end > 0.05:
            if nxt - s <= info["longest"] + 1e-6:
                end, why = nxt, "runs to the next clip (no speaker shot under it)"
            else:
                row["flags"].append(f"nothing on screen from {end:.2f}s to {nxt:.2f}s: add a clip or pass --speaker with the footage under it")
        end = snap(end)
        length = round(end - s, 3)
        if length > args.max_len + 0.05:
            row["flags"].append(f"stays {length:.1f}s (over {args.max_len}s) to fill the picture: add a clip in between")
        if length < args.min_len - 1e-6:
            row["flags"].append(f"short: {length:.1f}s (under {args.min_len}s) because {why}; a viewer may read it as a flash")
        if length < 1.0:
            row["flags"].append("under 1 s: drop it or give it its own line")
        src_in, src_out, shake = stretch(info, length, pick.get("in"))
        row.update(end=end, length=length, why_end=why, src_in=round(src_in, 2), src_out=round(src_out, 2), shake=shake)
        if shake is not None and shake >= measure.SHAKE_SHAKY:
            row["flags"].append(f"its steadiest {length:.1f}s still shakes ({shake}): pick another or stabilise it")
    if live and not args.speaker and live[0]["start"] > 0.05:
        first = live[0]  # with no footage under the B-roll, the video opens on the first clip
        first["flags"].append(f"opens the video: moved from {first['start']:.2f}s to 0s, since nothing is under it")
        first["src_in"] = round(max(0.0, first["src_in"] - first["start"]), 2) if infos[first["id"]]["kind"] == "video" else 0.0
        first["length"], first["start"] = round(first["end"], 3), 0.0
        first["src_out"] = round(first["src_in"] + first["length"], 2)
    return rows


# ---------------------------------------------------------------- colour

def srgb_to_lab(rgb):
    rgb = np.asarray(rgb, np.float64)
    lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
    xyz = lin @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > (6 / 29) ** 3, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], axis=-1)


def lab_to_srgb(lab):
    lab = np.asarray(lab, np.float64)
    fy = (lab[..., 0] + 16) / 116
    f = np.stack([fy + lab[..., 1] / 500, fy, fy - lab[..., 2] / 200], axis=-1)
    xyz = np.where(f > 6 / 29, f ** 3, 3 * (6 / 29) ** 2 * (f - 4 / 29)) * np.array([0.95047, 1.0, 1.08883])
    m = np.array([[3.2404542, -1.5371385, -0.4985314], [-0.9692660, 1.8760108, 0.0415560], [0.0556434, -0.2040259, 1.0572252]])
    lin = np.clip(xyz @ m.T, 0, 1)
    return np.clip(np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055), 0, 1)


def pixels(path, start, end, target, image=False, samples=12):
    """RGB pixels (0-1) of what the canvas shows: frames from start to end, centre-cropped to the target shape."""
    tw, th = target
    crop = f"crop='min(iw,ih*{tw}/{th})':'min(ih,iw*{th}/{tw})',scale=96:-2"
    if image:
        cmd = ["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-vf", crop + ",format=rgb24", "-f", "rawvideo", "-"]
    else:
        span = max(0.2, end - start)
        rate = min(4.0, samples / span)
        cmd = ["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{start:.3f}", "-t", f"{span:.3f}", "-i", str(path),
               "-vf", f"fps={rate:.4f},{crop},format=rgb24", "-threads", THREADS, "-f", "rawvideo", "-"]
    data = np.frombuffer(run(cmd).stdout, np.uint8)
    if not len(data):
        return None
    return data[: len(data) // 3 * 3].reshape(-1, 3).astype(np.float64) / 255


def lab_stats(px):
    lab = srgb_to_lab(px)
    return {"mean": lab.mean(axis=0), "spread": lab.std(axis=0) + 1e-6}


def delta_e(a, b):
    return float(np.linalg.norm(np.asarray(a["mean"]) - np.asarray(b["mean"])))


def move(clip, ref, strength):
    """How far to move each Lab channel's mean and spread: `strength` of the way, within caps."""
    shift = strength * (ref["mean"] - clip["mean"])
    shift[0] = np.clip(shift[0], -CAP_L, CAP_L)
    shift[1:] = np.clip(shift[1:], -CAP_AB, CAP_AB)
    ratio = (ref["spread"] / clip["spread"]) ** strength
    ratio[0] = np.clip(ratio[0], *CAP_SPREAD_L)
    ratio[1:] = np.clip(ratio[1:], *CAP_SPREAD_AB)
    if np.hypot(*clip["spread"][1:]) < 3:  # black and white footage keeps its look
        shift[1:], ratio[1:] = 0, 1
    return {"mean": clip["mean"], "shift": shift, "ratio": ratio}


def apply_move(rgb, m):
    lab = srgb_to_lab(rgb)
    lab = (lab - m["mean"]) * m["ratio"] + m["mean"] + m["shift"]
    lab[..., 0] = np.clip(lab[..., 0], 0, 100)
    return lab_to_srgb(lab)


def write_cube(path, m):
    g = np.linspace(0, 1, LUT_SIZE)
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")  # red changes fastest in a .cube file
    out = apply_move(np.stack([r, gg, b], axis=-1).reshape(-1, 3), m)
    lines = [f"TITLE \"media-picker colour match\"", f"LUT_3D_SIZE {LUT_SIZE}"]
    lines += [f"{x:.6f} {y:.6f} {z:.6f}" for x, y, z in out]
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def ff_path(path):
    """A path inside an FFmpeg filter: forward slashes, the drive colon escaped, in single quotes."""
    text = Path(path).resolve().as_posix().replace(":", r"\:")
    return f"'{text}'"


def colour_match(rows, infos, args, out):
    tw, th = args.target
    ref, ref_name = None, None
    if args.match_to or args.speaker:
        src = Path(args.match_to or args.speaker)
        info = measure.probe(src)
        length = float(info.get("format", {}).get("duration") or 0)
        px = pixels(src, 0, length, (tw, th), image=measure.kind_of(src, info) == "photo", samples=30)
        if px is not None:
            ref, ref_name = lab_stats(px), src.name
    stats = {}
    for r in rows:
        if r.get("skip"):
            continue
        info = infos[r["id"]]
        px = pixels(r["file"], r["src_in"], r["src_out"], (tw, th), image=info["kind"] == "photo")
        if px is not None:
            stats[r["id"]] = (lab_stats(px), px)
    if ref is None and len(stats) >= 2:
        means = np.median([s["mean"] for s, _ in stats.values()], axis=0)
        spreads = np.median([s["spread"] for s, _ in stats.values()], axis=0)
        ref, ref_name = {"mean": means, "spread": spreads}, "the middle of the picks"
    (out / "luts").mkdir(parents=True, exist_ok=True)
    for r in rows:
        if r["id"] not in stats or ref is None:
            continue
        s, px = stats[r["id"]]
        m = move(s, ref, args.strength)
        after = lab_stats(apply_move(px, m))
        cube = out / "luts" / f"{r['id']}.cube"
        write_cube(cube, m)
        r["colour"] = {
            "against": ref_name, "delta_e_before": round(delta_e(s, ref), 1), "delta_e_after": round(delta_e(after, ref), 1),
            "clip_lab": [round(float(v), 1) for v in s["mean"]], "target_lab": [round(float(v), 1) for v in ref["mean"]],
            "lut": str(cube), "filter": f"lut3d=file={ff_path(cube)}:interp=tetrahedral", "strength": args.strength,
        }
        if r["colour"]["delta_e_after"] > 10:
            r["flags"].append(f"colour still {r['colour']['delta_e_after']} ΔE from {ref_name} after the grade (over 10 stands out): "
                              "pick a clip shot in similar light, or say it will look different")
    return ref_name


# ---------------------------------------------------------------- face and captions

def canvas_frame(path, t, target, width=540):
    tw, th = target
    done = run(["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1", "-vf",
                f"crop='min(iw,ih*{tw}/{th})':'min(ih,iw*{th}/{tw})',scale={width}:-2", "-f", "image2pipe", "-vcodec", "png", "-"])
    if not done.stdout:
        return None
    from io import BytesIO
    return Image.open(BytesIO(done.stdout)).convert("RGB")


def grid_sheet(path, length, target, out_png):
    """Three speaker frames as the canvas shows them, with a 10% grid, so a face box can be read off in fractions."""
    frames = [canvas_frame(path, length * f, target, 360) for f in (0.15, 0.5, 0.85)]
    frames = [f for f in frames if f is not None]
    if not frames:
        return None
    w, h = frames[0].size
    sheet = Image.new("RGB", (len(frames) * (w + 40) + 20, h + 60), (24, 24, 26))
    d = ImageDraw.Draw(sheet)
    d.text((10, 6), "speaker on the canvas; grid lines every 0.1 (x across, y down): read the face box as x0,y0,x1,y1", fill=(245, 245, 247))
    for k, f in enumerate(frames):
        x0, y0 = 30 + k * (w + 40), 40
        sheet.paste(f, (x0, y0))
        for i in range(11):
            colour = (41, 151, 255) if i % 5 == 0 else (120, 120, 128)
            d.line([x0 + w * i / 10, y0, x0 + w * i / 10, y0 + h], fill=colour, width=1)
            d.line([x0, y0 + h * i / 10, x0 + w, y0 + h * i / 10], fill=colour, width=1)
            d.text((x0 - 24, y0 + h * i / 10 - 5), f"{i / 10:.1f}", fill=(245, 245, 247))
    sheet.save(out_png)
    return str(out_png)


def detect_faces(path, length, target):
    """Face boxes over time with OpenCV's bundled Haar cascade, if OpenCV is installed. [(t, box)], box in fractions."""
    try:
        import cv2  # noqa: PLC0415 - optional
    except ImportError:
        return None
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    found = []
    step = max(0.5, length / 120)
    t = 0.2
    while t < length:
        img = canvas_frame(path, t, target, 360)
        if img is not None:
            gray = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2GRAY)
            faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(int(img.width * 0.08),) * 2)
            if len(faces):
                x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                found.append((t, (x / img.width, y / img.height, (x + w) / img.width, (y + h) / img.height)))
        t += step
    if len(found) >= 3:  # drop boxes far from the usual face: the cascade sees faces in shelves and curtains
        boxes = np.array([b for _, b in found])
        cx, cy = np.median((boxes[:, 0] + boxes[:, 2]) / 2), np.median((boxes[:, 1] + boxes[:, 3]) / 2)
        size = np.median(boxes[:, 2] - boxes[:, 0])
        found = [(t, b) for t, b in found if abs((b[0] + b[2]) / 2 - cx) < 0.6 * size and abs((b[1] + b[3]) / 2 - cy) < 0.6 * size
                 and 0.6 < (b[2] - b[0]) / size < 1.6]
    return found


def head(box):
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    return (x0 - HEAD_SIDES * w, y0 - HEAD_ABOVE * h, x1 + HEAD_SIDES * w, y1 + HEAD_BELOW * h)


def union(boxes):
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def gap(a, b, target):
    """Gap between two boxes in canvas pixels; negative when they overlap."""
    tw, th = target
    dx = max(b[0] - a[2], a[0] - b[2]) * tw
    dy = max(b[1] - a[3], a[1] - b[3]) * th
    return max(dx, dy)


def face_at(faces, start, end):
    near = [b for t, b in faces if start - 0.5 <= t <= end + 0.5]
    return union(near) if near else union([b for _, b in faces])


def pip_box(row, info, head_box, caption, args):
    """A box for a picture-in-picture clip that clears the head and the captions, trying corners then sides."""
    tw, th = args.target
    aspect = (info["height"] / info["width"]) if info.get("width") else 9 / 16
    m = args.margin_px / tw
    for width in (0.45, 0.38, 0.32):
        h = width * tw * aspect / th
        spots = [(m, 0.06), (1 - m - width, 0.06), (m, 0.5 - h / 2), (1 - m - width, 0.5 - h / 2),
                 (m, 0.84 - h), (1 - m - width, 0.84 - h), (0.5 - width / 2, 0.06)]
        best = None
        for x, y in spots:
            box = (x, y, x + width, y + h)
            clear = min(gap(box, head_box, args.target) if head_box else 9e9, gap(box, caption, args.target) if caption else 9e9)
            if best is None or clear > best[0]:
                best = (clear, box)
        if best[0] >= args.margin_px:
            return best[1], round(best[0])
    return best[1], round(best[0])


def caption_box(args):
    if args.captions:
        return tuple(float(v) for v in args.captions.split(","))
    return None


# ---------------------------------------------------------------- editable-export

def rel(path, base):
    try:
        return Path(os.path.relpath(Path(path).resolve(), Path(base).resolve())).as_posix()
    except ValueError:  # another drive
        return Path(path).resolve().as_posix()


def make_media(rows, infos, args, out):
    """Graded copies of the parts used (with 1 s either side to trim), PiP animations, and the voice as a sound."""
    media = out / "media"
    media.mkdir(parents=True, exist_ok=True)
    tw, th = args.target
    for r in rows:
        if r.get("skip") or infos[r["id"]]["kind"] != "video":
            continue
        info = infos[r["id"]]
        a = max(0.0, r["src_in"] - 1.0)
        b = min(info["duration"], r["src_out"] + 1.0)
        grade = r.get("colour", {}).get("filter")
        if r["layout"] == "pip":
            px_w = int(round(r["box"][2] - r["box"][0], 4) * tw) // 2 * 2
            a, b = r["src_in"], r["src_out"]
            vf = ",".join(x for x in (grade, f"scale={px_w}:-2", f"fps={args.fps}") if x)
            dst = media / f"{r['id']}-pip.webp"
            cmd = ["ffmpeg", "-y", "-v", "error", "-nostdin", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", r["file"], "-vf", vf,
                   "-an", "-c:v", "libwebp_anim", "-lossless", "0", "-q:v", "70", "-loop", "0", "-threads", THREADS, str(dst)]
        else:
            vf = ",".join(x for x in (grade, "format=yuv420p") if x)
            dst = media / f"{r['id']}.mp4"
            cmd = ["ffmpeg", "-y", "-v", "error", "-nostdin", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", r["file"], "-vf", vf,
                   "-an", "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-threads", THREADS, str(dst)]
        r["command"] = cmd
        if not args.no_media:
            done = run(cmd)
            if done.returncode:
                r["flags"].append(f"FFmpeg could not write {dst.name}: {done.stderr.decode(errors='replace')[-300:]}")
                continue
        r["media_file"], r["media_offset"] = str(dst), round(a, 3)
    voice = None
    if args.speaker or args.voice:
        src = Path(args.voice or args.speaker)
        voice = media / "voice.m4a"
        cmd = ["ffmpeg", "-y", "-v", "error", "-nostdin", "-i", str(src), "-vn", "-ac", "2", "-c:a", "aac", "-b:a", "192k", str(voice)]
        if not args.no_media and run(cmd).returncode:
            fail(f"could not take the sound out of {src}")
    return voice


def fragment(rows, infos, args, out, voice, duration):
    """An editable-export project: V1 = speaker and cutaways back to back, B-roll pictures on top, the voice as a sound."""
    tw, th = args.target
    media, v1, pics, audio = {}, [], [], []
    live = sorted([r for r in rows if not r.get("skip") and r.get("end")], key=lambda r: r["start"])
    if args.speaker:
        media["speaker"] = {"kind": "video", "path": rel(args.speaker, out)}
    if voice:
        media["voice"] = {"kind": "audio", "path": rel(voice, out), "title": "voice"}
        audio.append({"id": "voice", "media": "voice", "at": 0.0, "in": 0.0, "out": None, "gain_db": 0.0, "label": "voice"})
    t, n = 0.0, 0

    def speaker_until(end):
        nonlocal t, n
        if args.speaker and end - t > 1e-3:
            n += 1
            v1.append({"id": f"a{n}", "media": "speaker", "in": round(t, 3), "out": round(end, 3), "volume": 0 if voice else 1})
        t = max(t, end)

    for r in live:
        info = infos[r["id"]]
        file = r.get("media_file") or r["file"]
        offset = r.get("media_offset", 0.0) if r.get("media_file") else 0.0
        if r["layout"] == "cutaway" and info["kind"] == "video":
            speaker_until(r["start"])
            media[r["id"]] = {"kind": "video", "path": rel(file, out)}
            v1.append({"id": r["id"], "media": r["id"], "in": round(r["src_in"] - offset, 3), "out": round(r["src_out"] - offset, 3),
                       "volume": 0, "fit": "cover", "x": 0.5, "y": 0.5, "label": r["shows"]})
            t = r["end"]
        else:
            mid = r["id"] + ("-pip" if r["layout"] == "pip" else "")
            media[mid] = {"kind": "image", "path": rel(file, out)}
            if r["layout"] == "pip":
                x0, y0, x1, y1 = r["box"]
                pics.append({"id": f"{r['id']}-pip", "media": mid, "at": r["start"], "dur": r["length"], "x": round((x0 + x1) / 2, 4),
                             "y": round((y0 + y1) / 2, 4), "width": round(x1 - x0, 4), "label": r["shows"],
                             "in": {"type": "fade", "dur": 0.15}, "out": {"type": "fade", "dur": 0.15}})
            else:
                cover = max(1.0, (info["width"] / info["height"]) * th / tw)
                pics.append({"id": r["id"], "media": mid, "at": r["start"], "dur": r["length"], "x": 0.5, "y": 0.5,
                             "width": round(cover, 4), "label": r["shows"]})
    speaker_until(duration)
    tracks = []
    if v1:
        tracks.append({"id": "V1", "kind": "video", "name": "Footage", "clips": v1})
    if pics:
        tracks.append({"id": "B1", "kind": "image", "name": "B-roll", "items": pics})
    if audio:
        tracks.append({"id": "VO", "kind": "audio", "name": "Voice", "items": audio})
    return {"format": "editatlas-project/1", "title": "B-roll placed", "canvas": {"width": tw, "height": th},
            "media": media, "tracks": tracks}


def merge_into(project_path, frag, frag_dir, out_path):
    """Put the cutaways into an existing project's footage track (splitting its clips on the timeline), keep the
    footage's own sound under the cutaways as sound items, and add the B-roll pictures right above the footage."""
    p = json.loads(Path(project_path).read_text(encoding="utf-8"))
    base = Path(project_path).resolve().parent
    for m in p.get("media", {}).values():
        if m.get("path") and not Path(m["path"]).is_absolute():
            m["path"] = rel(base / m["path"], out_path.parent)
    for mid, m in frag["media"].items():
        if mid not in ("speaker", "voice"):
            p["media"][mid] = dict(m, path=rel(frag_dir / m["path"], out_path.parent))
    spans, t = [], 0.0
    for c in next((x for x in frag["tracks"] if x["kind"] == "video"), {"clips": []})["clips"]:
        if c["media"] != "speaker":
            spans.append((t, t + c["out"] - c["in"], c))
        t += c["out"] - c["in"]
    v = next((x for x in p["tracks"] if x["kind"] == "video"), None)
    notes = []
    if v and spans:
        new, sound, t = [], [], 0.0
        for c in v["clips"]:
            sp = c.get("speed") or 1
            d = (c["out"] - c["in"]) / sp
            m = p["media"].get(c["media"], {})
            carry = m.get("kind") == "video" and c.get("volume", 1) != 0 and any(s0 < t + d and s1 > t for s0, s1, _ in spans)
            if carry and sp != 1:
                notes.append(f"clip {c['id']} plays at speed {sp}: its sound stops under the cutaway; check it")
                carry = False
            if carry:
                sid = f"{c['media']}-sound"
                p["media"].setdefault(sid, {"kind": "audio", "path": m["path"], "title": f"sound of {c['media']}"})
                sound.append({"id": f"{c['id']}-snd", "media": sid, "at": round(t, 3), "in": c["in"], "out": c["out"],
                              "gain_db": round(20 * math.log10(max(1e-4, c.get("volume", 1))), 1), "label": f"sound of {c['id']}"})
            pieces, a = [], t

            def piece(x0, x1):
                part = dict(c, **{"in": round(c["in"] + (x0 - t) * sp, 3), "out": round(c["in"] + (x1 - t) * sp, 3)})
                if pieces:
                    part["id"] = f"{c['id']}-{len(pieces) + 1}"
                    part.pop("transition", None)
                if carry:
                    part["volume"] = 0
                pieces.append(part)
                new.append(part)

            for s0, s1, b in spans:
                if s1 <= a + 1e-3 or s0 >= t + d - 1e-3:
                    continue
                if s0 > a + 1e-3:
                    piece(a, s0)
                if not any(x["id"] == b["id"] for x in new):
                    new.append(dict(b))
                a = max(a, s1)
            if a < t + d - 1e-3:
                piece(a, t + d)
            t += d
        v["clips"] = new
        if sound:
            p["tracks"].append({"id": "VO", "kind": "audio", "name": "Voice", "items": sound})
            notes.append("the footage's own sound now plays from sound items (track VO), so it carries on under the cutaways")
    pics = next((x for x in frag["tracks"] if x["kind"] == "image" and x["id"] == "B1"), None)
    if pics:
        at = next((i for i, x in enumerate(p["tracks"]) if x["kind"] == "video"), -1) + 1
        p["tracks"].insert(at, pics)
    out_path.write_text(json.dumps(p, indent=1, ensure_ascii=False), encoding="utf-8")
    return notes


def render(rows, infos, args, duration, dst):
    """A plain MP4 of the placements with FFmpeg: the speaker (or black) under the graded clips, the voice as sound."""
    tw, th = args.target
    cover = f"scale={tw}:{th}:force_original_aspect_ratio=increase,crop={tw}:{th},setsar=1"
    cmd = ["ffmpeg", "-y", "-v", "error", "-nostdin"]
    if args.speaker:
        cmd += ["-i", str(args.speaker)]
    else:
        cmd += ["-f", "lavfi", "-i", f"color=black:s={tw}x{th}:r={args.fps}:d={duration:.3f}"]
    live = sorted([r for r in rows if not r.get("skip") and r.get("end")], key=lambda r: r["start"])
    for r in live:
        if infos[r["id"]]["kind"] == "photo":
            cmd += ["-loop", "1", "-t", f"{r['length']:.3f}", "-i", r["file"]]
        else:
            cmd += ["-ss", f"{r['src_in']:.3f}", "-t", f"{r['length']:.3f}", "-i", r["file"]]
    sound = None
    if args.voice:
        cmd += ["-i", str(args.voice)]
        sound = f"{len(live) + 1}:a"
    elif args.speaker:
        sound = "0:a?"
    graph = [f"[0:v]{cover},fps={args.fps},format=yuv420p[v0]"]
    last = "v0"
    for k, r in enumerate(live, start=1):
        grade = (r.get("colour", {}).get("filter") + ",") if r.get("colour") else ""
        if r["layout"] == "pip" and r.get("box"):
            x0, y0, x1, y1 = r["box"]
            size = f"scale={int((x1 - x0) * tw) // 2 * 2}:-2"
            pos = f"x={int(x0 * tw)}:y={int(y0 * th)}"
        else:
            size, pos = cover, "x=0:y=0"
        graph.append(f"[{k}:v]{grade}{size},fps={args.fps},format=yuv420p,setpts=PTS-STARTPTS+{r['start']:.3f}/TB[c{k}]")
        graph.append(f"[{last}][c{k}]overlay={pos}:enable='between(t,{r['start']:.3f},{r['end']:.3f})':eof_action=pass[v{k}]")
        last = f"v{k}"
    cmd += ["-filter_complex", ";".join(graph), "-map", f"[{last}]"]
    if sound:
        cmd += ["-map", sound, "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-t", f"{duration:.3f}", "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-threads", THREADS,
            "-movflags", "+faststart", str(dst)]
    done = run(cmd)
    if done.returncode:
        fail(f"FFmpeg could not render {dst}: {done.stderr.decode(errors='replace')[-600:]}")
    return dst


# ---------------------------------------------------------------- report

def report(rows, args, checks, ref_name, notes):
    lines = [f"# B-roll placed (media-picker place.py {VERSION})", "",
             f"Lead {args.lead}s, length {args.min_len}-{args.max_len}s, speaker back for {args.gap}s or more, "
             f"colour {int(args.strength * 100)}% toward {ref_name or 'nothing (no reference)'}.", "",
             "| clip | starts on | at | in-out (timeline) | length | ends at | source in-out | shake | colour ΔE before → after | layout |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted([r for r in rows if not r.get("skip")], key=lambda r: r["start"]):
        c = r.get("colour")
        col = f"{c['delta_e_before']} → {c['delta_e_after']}" if c else "-"
        lay = r["layout"] + (f" x {r['box'][0]:.2f}-{r['box'][2]:.2f}, y {r['box'][1]:.2f}-{r['box'][3]:.2f}" if r.get("box") else "")
        lines.append(f"| {r['id']} | '{r['said']}' | {r['word_at']:.2f}s | {r['start']:.2f}-{r['end']:.2f}s | {r['length']:.1f}s | "
                     f"{r['why_end']} | {r['src_in']:.1f}-{r['src_out']:.1f}s | {r['shake'] if r['shake'] is not None else '-'} | {col} | {lay} |")
    flagged = [(r["id"], f) for r in rows for f in r["flags"]]
    if flagged:
        lines += ["", "Check:"] + [f"- {i}: {f}" for i, f in flagged]
    if checks:
        lines += ["", "Face and captions:"] + [f"- {c}" for c in checks]
    if notes:
        lines += ["", "Written:"] + [f"- {n}" for n in notes]
    lines += ["", "Timing and colour are measured. Whether each clip shows its words is for you to look at on its sheet."]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--words", required=True, help="transcribe JSON (word times on the finished timeline)")
    ap.add_argument("--picks", required=True, help='JSON: {"clips": [{"id", "file", "shows", "layout"?}]}')
    ap.add_argument("--out", default="work/place")
    ap.add_argument("--speaker", help="the talking-head footage under the B-roll (its timeline = the words' times)")
    ap.add_argument("--voice", help="the voice-over sound file, when there is no speaker footage")
    ap.add_argument("--target", default="1080x1920")
    ap.add_argument("--fps", type=float, default=30)
    ap.add_argument("--lead", type=float, default=0.1, help="seconds a clip starts before its word")
    ap.add_argument("--min", dest="min_len", type=float, help="shortest stay (default 2.0 for vertical, 2.5 otherwise)")
    ap.add_argument("--max", dest="max_len", type=float, help="longest stay (default 6.0 for vertical, 8.0 otherwise)")
    ap.add_argument("--gap", type=float, default=1.0, help="least time back on the speaker between two clips")
    ap.add_argument("--match-to", help="footage or photo to match colour to, when there is no speaker")
    ap.add_argument("--strength", type=float, default=0.7, help="how far to move colour toward the reference (0-1)")
    ap.add_argument("--face", help="face box x0,y0,x1,y1 in canvas fractions, or 'auto' (needs OpenCV)")
    ap.add_argument("--captions", help="caption area x0,y0,x1,y1 in canvas fractions")
    ap.add_argument("--margin-px", type=float, default=24, help="least room between a box and the head, in canvas pixels")
    ap.add_argument("--into", help="an editable-export project.json to merge the B-roll into")
    ap.add_argument("--no-media", action="store_true", help="only plan: do not write graded copies or the voice")
    ap.add_argument("--render", help="also write a plain MP4 of the placements here (FFmpeg), outside the studio")
    ap.add_argument("--version", action="version", version=VERSION)
    args = ap.parse_args()
    args.target = measure.parse_size(args.target)
    vertical = args.target[1] > args.target[0]
    args.min_len = args.min_len or (2.0 if vertical else 2.5)
    args.max_len = args.max_len or (6.0 if vertical else 8.0)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    words, duration = load_words(args.words)
    picks = json.loads(Path(args.picks).read_text(encoding="utf-8"))
    picks = picks["clips"] if isinstance(picks, dict) else picks
    for k, p in enumerate(picks):
        p.setdefault("id", f"b{k + 1}")
        p["id"] = re.sub(r"[^A-Za-z0-9_-]", "-", str(p["id"]))
        if not Path(p.get("file", "")).is_file():
            fail(f"clip {p['id']}: no such file {p.get('file')!r}")
    if len({p["id"] for p in picks}) != len(picks):
        fail("two clips have the same id")
    if args.speaker:
        sp = measure.probe(Path(args.speaker))
        duration = max(duration, float(sp.get("format", {}).get("duration") or 0))
    infos = {p["id"]: clip_info(Path(p["file"])) for p in picks}
    rows = plan(words, picks, infos, args, duration)
    ref_name = colour_match(rows, infos, args, out)

    checks = []
    caption = caption_box(args)
    faces = None
    if args.speaker:
        grid = grid_sheet(Path(args.speaker), duration, args.target, out / "speaker_grid.png")
        if args.face == "auto":
            faces = detect_faces(Path(args.speaker), duration, args.target)
            if faces is None:
                checks.append(f"OpenCV is not installed: open {grid} and pass --face x0,y0,x1,y1 (the face, as fractions)")
            elif not faces:
                checks.append(f"no face found automatically: open {grid} and pass --face x0,y0,x1,y1")
                faces = None
            else:
                checks.append(f"face found automatically in {len(faces)} frames, from x {min(b[0] for _, b in faces):.2f}-{max(b[2] for _, b in faces):.2f}, y {min(b[1] for _, b in faces):.2f}-{max(b[3] for _, b in faces):.2f}: look at {grid} to confirm")
        elif args.face:
            faces = [(0.0, tuple(float(v) for v in args.face.split(",")))]
        elif any(r.get("layout") == "pip" for r in rows) or caption:
            checks.append(f"no face box given: open {grid}, read the face box and run again with --face x0,y0,x1,y1 (or --face auto)")
    for r in rows:
        if r.get("skip") or r["layout"] != "pip":
            continue
        hb = head(face_at(faces, r["start"], r["end"])) if faces else None
        r["box"], clear = pip_box(r, infos[r["id"]], hb, caption, args)
        r["box"] = [round(v, 4) for v in r["box"]]
        if hb is None:
            r["flags"].append("PiP box placed without a face box: check it does not cover the face")
        elif clear < args.margin_px:
            r["flags"].append(f"no PiP box clears the face by {args.margin_px:.0f}px (best {clear}px): use a cutaway for this clip")
        else:
            checks.append(f"{r['id']} PiP clears the head by {clear}px")
    if faces and caption:
        speaker_times = []  # caption over the face matters only while the speaker shows
        cut = sorted((r["start"], r["end"]) for r in rows if not r.get("skip") and r["layout"] == "cutaway")
        t = 0.0
        for a, b in cut:
            if a > t:
                speaker_times.append((t, a))
            t = max(t, b)
        if t < duration:
            speaker_times.append((t, duration))
        worst = min((gap(caption, head(face_at(faces, a, b)), args.target), a, b) for a, b in speaker_times) if speaker_times else None
        if worst and worst[0] < args.margin_px:
            hb = head(face_at(faces, worst[1], worst[2]))
            tall = caption[3] - caption[1]
            room = [f"with their top below y {hb[3] + 0.02:.2f}" for _ in [0] if hb[3] + 0.02 + tall <= 0.9]
            room += [f"with their bottom above y {hb[1] - 0.02:.2f}" for _ in [0] if hb[1] - 0.02 - tall >= 0.05]
            checks.append(f"captions overlap the head while the speaker shows ({worst[0]:.0f}px, {worst[1]:.1f}-{worst[2]:.1f}s): "
                          + (f"move them {' or '.join(room)}" if room else "no room above or below the head: make them smaller or show them only over the cutaways"))
        elif worst:
            checks.append(f"captions clear the head by {worst[0]:.0f}px or more while the speaker shows")

    voice = make_media(rows, infos, args, out)
    frag = fragment(rows, infos, args, out, voice, duration)
    (out / "fragment.json").write_text(json.dumps(frag, indent=1, ensure_ascii=False), encoding="utf-8")
    notes = merge_into(args.into, frag, out, out / "project_with_broll.json") if args.into else []
    keep = [{k: v for k, v in r.items() if k not in ("last_word",)} for r in rows]
    (out / "placements.json").write_text(json.dumps({"version": VERSION, "target": args.target, "lead": args.lead,
                                                     "min": args.min_len, "max": args.max_len, "gap": args.gap,
                                                     "colour_reference": ref_name, "placements": keep, "checks": checks},
                                                    indent=1, ensure_ascii=False), encoding="utf-8")
    if args.render:
        notes.append(f"rendered {render(rows, infos, args, duration, Path(args.render))}")
    text = report(rows, args, checks, ref_name, notes)
    (out / "placements.md").write_text(text, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(text)
    print(f"Wrote {out / 'placements.json'}, {out / 'fragment.json'}" + (f", {out / 'project_with_broll.json'}" if args.into else ""))


if __name__ == "__main__":
    main()
