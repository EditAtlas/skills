"""Check a finished video before anyone sees it: file spec, picture faults, sound levels, and review sheets.

  check.py VIDEO --out work/check [--expect 1080x1920] [--fps 30] [--duration 30] [--loudness -14]
                 [--audio required|none|any] [--loop] [--holds 4-6,12.5-14] [--flashes 3.2,9.8]
                 [--before work/check-round1/check.json]

Writes OUT/check.json, OUT/overview_NN.png (frames at phone size, with the caption safe area marked on vertical
video) and OUT/findings.png (the frames around each finding). With --before, also OUT/before_after.png and a list
of findings gone, still there and new.

The numbers find faults a viewer would notice; they cannot tell whether the edit is good. Open the sheets with
the Read tool, and read references/reading-the-checks.md for what each check misses.
"""
import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

VERSION = "0.1.1"
STILL = 0.0015      # mean absolute change (0..1) under which two frames count as the same picture
DUPE = 0.0006       # an exact repeat, after compression noise
MOVING = 0.004      # change per frame above which the picture is moving
SAFE_TOP, SAFE_BOTTOM = 0.15, 0.25   # caption-safe area on vertical video: stay out of the top 15% and bottom 25%


def die(msg):
    sys.exit("video-check: " + msg)


def need(tool):
    if not shutil.which(tool):
        die(f"{tool} not found in PATH. Install FFmpeg (it ships ffprobe) and open a new terminal.")


def run(cmd):
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8", errors="replace")


_SYNC = []


def passthrough():
    """Keep every decoded frame: -fps_mode on FFmpeg 5.1 and later, -vsync before."""
    if not _SYNC:
        r = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i", "color=s=16x16:d=0.1",
                            "-fps_mode", "passthrough", "-f", "null", "-"], capture_output=True)
        _SYNC.append(["-fps_mode", "passthrough"] if r.returncode == 0 else ["-vsync", "0"])
    return _SYNC[0]


def rate(val):
    try:
        n, m = (val or "0/0").split("/")
        return float(n) / float(m) if float(m) else 0.0
    except ValueError:
        return 0.0


# ------------------------------------------------------------------ file spec
def probe(path):
    need("ffprobe")
    if not Path(path).is_file():
        die(f"no file at {path}. Give the path of the rendered video on this machine.")
    r = run(["ffprobe", "-v", "error", "-show_entries",
             "format=duration:stream=index,codec_type,codec_name,width,height,pix_fmt,sample_aspect_ratio,"
             "r_frame_rate,avg_frame_rate,nb_frames,duration,sample_rate,channels:stream_side_data=rotation",
             "-of", "json", path])
    if r.returncode:
        die(f"cannot read {path}: {r.stderr.strip()[:300]}")
    d = json.loads(r.stdout)
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), None)
    if not v:
        die(f"{path} has no video stream.")
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(float(sd["rotation"]))
    fps_r, fps_avg = rate(v.get("r_frame_rate")), rate(v.get("avg_frame_rate"))
    return {
        "duration": float(d.get("format", {}).get("duration") or v.get("duration") or 0),
        "width": v.get("width"), "height": v.get("height"), "codec": v.get("codec_name"),
        "pix_fmt": v.get("pix_fmt"), "sar": v.get("sample_aspect_ratio") or "1:1", "rotation": rot,
        "fps": round(fps_avg or fps_r or 30.0, 3), "fps_declared": round(fps_r, 3),
        "audio": None if not a else {
            "codec": a.get("codec_name"), "sample_rate": int(a.get("sample_rate") or 0),
            "channels": a.get("channels"), "duration": float(a.get("duration") or 0)},
    }


# ------------------------------------------------------------------ picture
def gray_frames(video, info):
    """Every decoded frame as a small grey image (long side 128 px), in one ffmpeg pass."""
    need("ffmpeg")
    w0, h0 = info["width"] or 16, info["height"] or 9
    if abs(info["rotation"]) in (90, 270):
        w0, h0 = h0, w0
    s = 128 / max(w0, h0)
    w, h = max(2, int(round(w0 * s / 2) * 2)), max(2, int(round(h0 * s / 2) * 2))
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-nostdin", "-i", str(video), "-an", *passthrough(),
                          "-vf", f"scale={w}:{h}:flags=area,format=gray", "-f", "rawvideo", "-"],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    out = []
    try:
        while True:
            buf = p.stdout.read(w * h)
            if len(buf) < w * h:
                break
            out.append(np.frombuffer(buf, np.uint8).reshape(h, w))
    finally:
        p.stdout.close()
        p.wait()
    if len(out) < 3:
        die("FFmpeg decoded fewer than 3 frames. Check that the file plays.")
    return np.stack(out).astype(np.float32) / 255


def runs(mask):
    """(start, end) index pairs of True runs, end exclusive."""
    out, start = [], None
    for i, m in enumerate(list(mask) + [False]):
        if m and start is None:
            start = i
        elif not m and start is not None:
            out.append((start, i))
            start = None
    return out


def parse_ranges(text):
    out = []
    for part in (text or "").split(","):
        part = part.strip()
        if not part:
            continue
        a, _, b = part.partition("-")
        try:
            out.append((float(a), float(b or a)))
        except ValueError:
            die(f"cannot read the time range '{part}'. Write seconds, like 4-6,12.5-14.")
    return out


def inside(t0, t1, ranges, slack):
    return any(t0 >= a - slack and t1 <= b + slack for a, b in ranges)


def cadence(d, fps):
    """Describe where single repeated frames fall: a steady one-in-N, and stretches where they come closer."""
    rep = [i for i in range(2, len(d)) if d[i] < DUPE and d[i - 1] >= STILL]
    if len(rep) < 3:
        return "too few to tell"
    gaps = np.diff(rep)
    vals, counts = np.unique(gaps, return_counts=True)
    m = int(vals[counts.argmax()])
    words = [f"one every {m} frames from {rep[0] / fps:.1f} s ({int(counts.max())} of {len(gaps)} gaps)"]
    dense = [rep[k + 1] for k, gp in enumerate(gaps) if gp < m / 1.5]
    if len(dense) >= 3:
        words.append(f"closer together (every {int(gaps[gaps < m / 1.5].min())}-{int(gaps[gaps < m / 1.5].max())} frames) "
                     f"from {dense[0] / fps:.1f} to {dense[-1] / fps:.1f} s")
    return "; ".join(words)


def picture(g, fps, args, findings):
    n = len(g)
    t = lambda i: round(i / fps, 3)
    mean = g.mean(axis=(1, 2))
    std = g.std(axis=(1, 2))
    d = np.r_[0.0, np.abs(np.diff(g, axis=0)).mean(axis=(1, 2))]   # d[i]: change from frame i-1 to i
    holds, flashes = parse_ranges(args.holds), [a for a, _ in parse_ranges(args.flashes)]
    slack = 2 / fps

    med = np.array([np.median(d[max(1, i - 6): i + 7]) for i in range(n)])
    pops = []
    for i in range(1, n - 1):
        a_, b_ = d[i], d[i + 1]
        c = float(np.abs(g[i + 1] - g[i - 1]).mean())
        if min(a_, b_) > max(0.03, 3 * med[i]) and c < 0.4 * min(a_, b_):
            if any(abs(t(i) - f) <= slack for f in flashes):
                continue
            pops.append(i)
            kind = "white" if mean[i] > 0.85 else "black" if mean[i] < 0.08 else "different"
            findings.append(dict(level="P1", code="one_frame_flash", t=t(i), t_end=t(i),
                                 what=f"one {kind} frame between two similar ones (a glitch or a stray frame)",
                                 fix=f"remove frame {i}, or pass --flashes {t(i)} if it is a planned flash"))

    black = (mean < 0.06) & (std < 0.03)
    white = (mean > 0.94) & (std < 0.03)
    for name, mask, word in (("black", black, "black"), ("white", white, "white")):
        for a, b in runs(mask):
            t0, t1 = t(a), t((b - 1))
            if any(abs(t0 - f) <= slack for f in flashes) or inside(t0, t1, holds, slack):
                continue
            if b - a == 1 and a in pops:
                continue
            if a == 0:
                findings.append(dict(level="P1", code=f"{name}_first_frame", t=t0, t_end=t1,
                                     what=f"the video opens on {b} {word} frame(s): the thumbnail and the first look are {word}",
                                     fix="start on a picture; fade up from it, not from " + word))
            elif b == n and name == "black":
                if (b - a) / fps > 1.5:
                    findings.append(dict(level="P2", code="black_end", t=t0, t_end=t1,
                                         what=f"{(b - a) / fps:.1f} s of black at the end",
                                         fix="shorten the tail to under 1 s unless it is wanted"))
            else:
                lvl = "P1" if b - a >= 2 or name == "black" else "P2"
                findings.append(dict(level=lvl, code=f"{name}_frames", t=t0, t_end=t1,
                                     what=f"{b - a} {word} frame(s) in the middle",
                                     fix=(f"if not planned, cut them; if planned (a dip, an iris), pass --holds {t0}-{t1}" if b - a > 1
                                          else f"if not a planned flash, cut it or pass --flashes {t0}")))

    still = d < STILL
    still[0] = still[1] if n > 1 else False
    for a, b in runs(still):
        a0 = max(a - 1, 0)
        sec = (b - a0) / fps
        t0, t1 = t(a0), t(b - 1)
        if sec < 1.0 or inside(t0, t1, holds, 0.3):
            continue
        if b == n and sec >= 2.0:
            findings.append(dict(level="P1", code="still_end", t=t0, t_end=t1,
                                 what=f"the picture stops moving for the last {sec:.1f} s",
                                 fix="end the video sooner, or hold an end card on purpose and pass --holds"))
        elif sec >= 3.0:
            findings.append(dict(level="P1", code="still_long", t=t0, t_end=t1,
                                 what=f"nothing on screen changes for {sec:.1f} s",
                                 fix="add movement or cut it shorter; if it is a designed hold, pass --holds"))
        elif sec >= 1.5 and b < n:
            findings.append(dict(level="P2", code="still", t=t0, t_end=t1,
                                 what=f"a still stretch of {sec:.1f} s",
                                 fix="fine for a title or logo hold; check it is wanted"))

    moving = np.zeros(n, bool)
    moving[1:-1] = (d[:-2] > MOVING) & (d[2:] > MOVING)
    dupes = [i for i in range(1, n - 1) if moving[i] and d[i] < DUPE]
    n_moving = int(moving.sum())
    if len(dupes) >= 3 and n_moving and len(dupes) / n_moving > 0.05:
        findings.append(dict(level="P2", code="repeated_frames", t=t(dupes[0]), t_end=t(dupes[-1]),
                             what=f"{len(dupes)} repeated frames while the picture moves ({100 * len(dupes) / n_moving:.0f}% of moving frames): "
                                  f"motion steps or stutters; pattern: {cadence(d, fps)}",
                             fix="a steady one-in-N pattern through a whole clip comes from a frame-rate change, in the source "
                                 "(old film, animation on twos: leave it) or in the render (deliver at the source rate); "
                                 "a pattern that changes partway marks where another clip, a speed change or a dropped-frame stretch starts: look there"))

    cut_thr = np.maximum(0.08, 5 * med)
    cuts = [i for i in range(1, n) if d[i] > cut_thr[i] and i not in pops and i - 1 not in pops]
    merged = []
    for i in cuts:
        if not merged or i - merged[-1] > 2:
            merged.append(i)
    bounds = [0] + merged + [n]
    shots = [(bounds[k + 1] - bounds[k]) / fps for k in range(len(bounds) - 1)]
    blank = black | white
    short = [round(bounds[k] / fps, 2) for k, s in enumerate(shots)
             if s < 0.25 and 0 < k < len(shots) - 1 and not blank[bounds[k]:bounds[k + 1]].all()
             and not any(abs(bounds[k] / fps - f) <= slack for f in flashes)
             and not inside(bounds[k] / fps, bounds[k + 1] / fps, holds, slack)]
    if short:
        findings.append(dict(level="P2", code="flash_shot", t=short[0], t_end=short[-1],
                             what=f"{len(short)} shot(s) under 0.25 s, at {', '.join(map(str, short[:6]))} s",
                             fix="check each is a planned flash cut and not a leftover frame"))

    loop = None
    if args.loop:
        seam = float(np.abs(g[0] - g[-1]).mean())
        steps = [float(d[-1]), float(d[1])]
        ref = max(steps)
        if ref > MOVING and seam < DUPE:
            state = "first frame shows twice"
            findings.append(dict(level="P1", code="loop_repeat", t=t(n - 1), t_end=t(n - 1),
                                 what="the last frame equals the first, so one picture shows twice on every loop (a stutter)",
                                 fix="render up to one frame before the full length: the picture at the full length is the first frame"))
        elif seam > 2.5 * ref + 0.01:
            state = "visible jump"
            findings.append(dict(level="P1", code="loop_jump", t=t(n - 1), t_end=t(n - 1),
                                 what=f"the loop jumps at the seam (change {seam:.3f} against {ref:.3f} for a normal step)",
                                 fix="make the picture at the full length equal the first frame"))
        else:
            state = "seamless"
        loop = {"seam_change": round(seam, 4), "normal_steps": [round(s, 4) for s in steps], "state": state}

    longest_still = max([(b - max(a - 1, 0)) / fps for a, b in runs(still)] or [0])
    return {
        "frames": n,
        "cuts": [t(i) for i in merged],
        "cuts_per_minute": round(len(merged) / (n / fps) * 60, 1) if n else 0,
        "shot_seconds": {"shortest": round(min(shots), 2), "median": round(float(np.median(shots)), 2),
                         "longest": round(max(shots), 2)},
        "still_share": round(float(still.mean()), 3),
        "longest_still_seconds": round(longest_still, 2),
        "black_frames": int(black.sum()), "white_frames": int(white.sum()),
        "one_frame_flashes": [t(i) for i in pops],
        "repeated_frames_in_motion": len(dupes),
        "loop": loop,
    }


# ------------------------------------------------------------------ sound
def sound(video, info, args, findings):
    a = info["audio"]
    if not a:
        if args.audio == "required":
            findings.append(dict(level="P0", code="no_audio", t=0, t_end=0, what="the file has no audio track",
                                 fix="mux the mix into the file; check -map and -an in the render command"))
        elif args.audio == "any":
            findings.append(dict(level="P1", code="no_audio", t=0, t_end=0, what="the file has no audio track",
                                 fix="if silence is not intended, mux the mix in; pass --audio none if it is"))
        return None
    r = run(["ffmpeg", "-v", "info", "-nostdin", "-i", video, "-map", "0:a:0", "-af",
             "silencedetect=noise=-50dB:d=0.5,loudnorm=print_format=json", "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"silence_start: (-?[0-9.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: (-?[0-9.]+)", r.stderr)]
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr)
    ln = json.loads(m.group(0)) if m else {}
    num = lambda k: float(ln[k]) if k in ln and ln[k] not in ("-inf", "inf") else None
    lufs, tp, lra = num("input_i"), num("input_tp"), num("input_lra")
    dur = info["duration"]
    silences = []
    for k, s in enumerate(starts):
        e = ends[k] if k < len(ends) else dur
        silences.append((round(max(s, 0), 2), round(min(e, dur), 2)))

    if lufs is None or lufs < -60:
        findings.append(dict(level="P1", code="silent_track", t=0, t_end=round(dur, 2),
                             what="the audio track is there but silent", fix="check the mix was written to the file"))
    else:
        if abs(lufs - args.loudness) > 2:
            findings.append(dict(level="P1", code="loudness", t=0, t_end=round(dur, 2),
                                 what=f"loudness {lufs:.1f} LUFS against a target of {args.loudness:g}",
                                 fix=f"normalize the final mix once to {args.loudness:g} LUFS (EditAtlas: audio-loudness-normalization)"))
        if tp is not None and tp > 0:
            findings.append(dict(level="P0" if tp > 1 else "P1", code="clipping", t=0, t_end=round(dur, 2),
                                 what=f"true peak {tp:+.1f} dBTP: the sound clips",
                                 fix="lower the gain or add a limiter with a ceiling of -1 dBTP"))
        elif tp is not None and tp > -1:
            findings.append(dict(level="P1", code="true_peak", t=0, t_end=round(dur, 2),
                                 what=f"true peak {tp:+.1f} dBTP: platforms that re-encode will clip it",
                                 fix="limit to -1 dBTP"))
        for s, e in silences:
            if e - s >= 2 and s > 0.3 and e < dur - 0.3:
                findings.append(dict(level="P1", code="dead_air", t=s, t_end=e,
                                     what=f"{e - s:.1f} s of silence in the middle",
                                     fix="fill it with music or room tone, or cut it"))
            elif s <= 0.05 and e >= 1.0 and e < dur - 0.3:
                findings.append(dict(level="P2", code="silent_start", t=s, t_end=e,
                                     what=f"the sound starts only at {e:.1f} s",
                                     fix="start sound on the first frame unless the silence is meant"))
    if a["duration"] and dur - a["duration"] > 0.5:
        findings.append(dict(level="P1", code="audio_short", t=round(a["duration"], 2), t_end=round(dur, 2),
                             what=f"the audio ends {dur - a['duration']:.1f} s before the picture",
                             fix="extend or loop the music, or pad with silence on purpose (apad)"))

    tail = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-sseof", "-0.6", "-i", video, "-vn", "-ac", "1",
                           "-ar", "16000", "-f", "f32le", "-"], capture_output=True).stdout
    x = np.frombuffer(tail, np.float32)
    end_db = None
    if len(x) > 2000:
        last = x[-480:]
        rms = lambda y: 20 * math.log10(float(np.sqrt(np.mean(y.astype(np.float64) ** 2))) + 1e-9)
        end_db = round(rms(last), 1)
        if end_db > -30 and end_db > rms(x) - 6:
            findings.append(dict(level="P2", code="abrupt_end", t=round(dur - 0.03, 2), t_end=round(dur, 2),
                                 what=f"the sound is still at {end_db} dBFS in the last 30 ms: it stops abruptly",
                                 fix="fade the music out over 1 to 2 s, ending on a phrase"))
    return {"lufs": lufs, "true_peak_dbtp": tp, "loudness_range": lra, "target_lufs": args.loudness,
            "silences": silences, "last_30ms_dbfs": end_db, **a}


# ------------------------------------------------------------------ sheets
def frames_at(video, idx, w, h):
    """RGB frames by decoded index, in one ffmpeg pass."""
    idx = sorted(set(int(i) for i in idx))
    if not idx:
        return {}
    expr = "+".join(f"eq(n\\,{i})" for i in idx)
    r = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(video), "-an", *passthrough(), "-vf",
                        f"select='{expr}',scale={w}:{h}:flags=area,format=rgb24", "-f", "rawvideo", "-"],
                       capture_output=True)
    size = w * h * 3
    got = [np.frombuffer(r.stdout[k * size:(k + 1) * size], np.uint8).reshape(h, w, 3)
           for k in range(len(r.stdout) // size)]
    return dict(zip(idx, got))


def draw_sheet(tiles, out, cols, guides):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    tiles = [(img, lab) for img, lab in tiles if img is not None]
    if not tiles:
        return None
    h, w = tiles[0][0].shape[:2]
    rows = (len(tiles) + cols - 1) // cols
    s = Image.new("RGB", (w * min(cols, len(tiles)) + 4 * (min(cols, len(tiles)) - 1), (h + 4) * rows), (24, 24, 24))
    for k, (img, lab) in enumerate(tiles):
        im = Image.fromarray(img)
        dr = ImageDraw.Draw(im, "RGBA")
        if guides:
            for y in (int(h * SAFE_TOP), int(h * (1 - SAFE_BOTTOM))):
                for x in range(0, w, 8):
                    dr.line([(x, y), (x + 4, y)], fill=(255, 0, 200, 200))
        dr.rectangle([0, 0, 8 + 6 * len(lab), 13], fill=(0, 0, 0, 200))
        dr.text((3, 1), lab, fill=(255, 255, 255))
        s.paste(im, ((k % cols) * (w + 4), (k // cols) * (h + 4)))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    s.save(out)
    return str(out)


def tile_size(info, width):
    w0, h0 = info["width"] or 16, info["height"] or 9
    if abs(info["rotation"]) in (90, 270):
        w0, h0 = h0, w0
    return width, max(2, int(round(width * h0 / w0 / 2) * 2))


def sheets(video, info, n, fps, findings, out, every, before=None):
    portrait = (tile_size(info, 100)[1] > 100)
    w, h = tile_size(info, 360 if portrait else 480)
    dur = n / fps
    step = every or max(0.5, round(dur / 36 * 2) / 2)
    idx = sorted(set([0] + [min(n - 1, int(round(k * step * fps))) for k in range(1, int(dur / step) + 1)] + [n - 1]))
    near, tag = [], {}
    for f in findings:
        a = int(round(f["t"] * fps))
        b = int(round(f.get("t_end", f["t"]) * fps))
        if b - a > 0.8 * n or f["code"] in ("size", "fps", "pix_fmt", "pixel_aspect", "rotation", "variable_fps",
                                            "no_audio", "duration"):
            continue   # about the whole file: frames show nothing
        for i in sorted({a - 1, a, a + 1, (a + b) // 2, b}):
            if 0 <= i < n:
                near.append(i)
        tag.setdefault(a, f["code"])
    got = frames_at(video, idx + near, w, h)
    lab = lambda i: f"{i / fps:.2f}s f{i}"
    paths = []
    per = 12 if portrait else 9
    cols = 6 if portrait else 3
    for k in range(0, len(idx), per):
        p = draw_sheet([(got.get(i), lab(i)) for i in idx[k:k + per]], Path(out) / f"overview_{k // per + 1:02d}.png",
                       cols, portrait)
        if p:
            paths.append(p)
    fp = None
    if near:
        fp = draw_sheet([(got.get(i), lab(i) + (" " + tag[i] if i in tag else "")) for i in sorted(set(near))[:60]],
                        Path(out) / "findings.png",
                        6 if portrait else 4, portrait)
    ba = None
    if before:
        bv = before.get("video")
        if bv and Path(bv).is_file():
            binfo = probe(bv)
            bfps = binfo["fps"]
            times = [i / fps for i in idx][:12]
            bgot = frames_at(bv, [min(int(round(x * bfps)), int(binfo["duration"] * bfps) - 1) for x in times], w, h)
            tiles = []
            for x in times:
                tiles.append((bgot.get(min(int(round(x * bfps)), int(binfo["duration"] * bfps) - 1)), f"before {x:.2f}s"))
                tiles.append((got.get(min(n - 1, int(round(x * fps)))), f"now {x:.2f}s"))
            ba = draw_sheet(tiles, Path(out) / "before_after.png", 6 if portrait else 4, portrait)
    return {"overview": paths, "findings": fp, "before_after": ba, "every_seconds": step,
            "tile": [w, h], "safe_area_marked": portrait}


# ------------------------------------------------------------------ main
def compare(before, findings):
    old = before.get("findings", [])
    same = lambda f, o: f["code"] == o["code"] and abs(f["t"] - o["t"]) <= 0.5
    gone = [o for o in old if not any(same(f, o) for f in findings)]
    still = [f for f in findings if any(same(f, o) for o in old)]
    new = [f for f in findings if not any(same(f, o) for o in old)]
    return {"gone": gone, "still": still, "new": new}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("video")
    ap.add_argument("--out", default="work/check")
    ap.add_argument("--expect", help="output size, like 1080x1920")
    ap.add_argument("--fps", type=float, help="output frame rate the edit was planned at")
    ap.add_argument("--duration", type=float, help="planned length in seconds")
    ap.add_argument("--loudness", type=float, default=-14.0, help="target LUFS (online video -14)")
    ap.add_argument("--audio", choices=["required", "none", "any"], default="any")
    ap.add_argument("--loop", action="store_true", help="the video is made to loop")
    ap.add_argument("--holds", help="planned still stretches, seconds: 4-6,12.5-14")
    ap.add_argument("--flashes", help="planned one-frame flashes or black/white frames, seconds: 3.2,9.8")
    ap.add_argument("--every", type=float, help="seconds between overview frames (default: about 36 frames)")
    ap.add_argument("--before", help="check.json of an earlier round, to list what changed")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    video = str(Path(args.video).resolve())
    info = probe(video)
    findings = []
    w, h = info["width"], info["height"]
    if abs(info["rotation"]) in (90, 270):
        findings.append(dict(level="P1", code="rotation", t=0, t_end=0,
                             what=f"the picture is stored {w}x{h} with a {info['rotation']} degree rotation flag; some players ignore it",
                             fix="render the rotation into the pixels and drop the flag"))
    if args.expect:
        m = re.match(r"^(\d+)x(\d+)$", args.expect)
        if not m:
            die("write --expect as WIDTHxHEIGHT, like 1080x1920.")
        if (w, h) != (int(m.group(1)), int(m.group(2))):
            findings.append(dict(level="P0", code="size", t=0, t_end=0, what=f"size {w}x{h}, planned {args.expect}",
                                 fix="scale and pad to the planned size in the final render"))
    if info["sar"] not in ("1:1", "0:1", "N/A"):
        findings.append(dict(level="P1", code="pixel_aspect", t=0, t_end=0,
                             what=f"pixel aspect {info['sar']}: players may stretch it",
                             fix="add scale=iw*sar:ih,setsar=1"))
    if info["codec"] == "h264" and info["pix_fmt"] not in ("yuv420p", "yuvj420p"):
        findings.append(dict(level="P1", code="pix_fmt", t=0, t_end=0,
                             what=f"H.264 in {info['pix_fmt']}: many phones and browsers will not play it",
                             fix="add -pix_fmt yuv420p"))
    if args.fps and abs(info["fps"] - args.fps) > 0.05:
        findings.append(dict(level="P0", code="fps", t=0, t_end=0, what=f"{info['fps']} fps, planned {args.fps:g}",
                             fix=f"conform with fps={args.fps:g} before the final encode"))
    if info["fps_declared"] and abs(info["fps_declared"] - info["fps"]) > 0.5:
        findings.append(dict(level="P2", code="variable_fps", t=0, t_end=0,
                             what=f"variable frame rate ({info['fps_declared']} declared, {info['fps']} average)",
                             fix="add -r or fps= to make it constant; editors and some platforms drift with VFR"))
    fps = info["fps"]
    if args.duration and abs(info["duration"] - args.duration) > 1.5 / fps:
        findings.append(dict(level="P0", code="duration", t=0, t_end=round(info["duration"], 2),
                             what=f"{info['duration']:.2f} s long, planned {args.duration:g} s",
                             fix="check the cut list and the last transition: a join can end the output early"))

    g = gray_frames(video, info)
    pic = picture(g, fps, args, findings)
    snd = sound(video, info, args, findings)
    findings.sort(key=lambda f: ({"P0": 0, "P1": 1, "P2": 2}[f["level"]], f["t"]))
    before = None
    if args.before:
        try:
            before = json.loads(Path(args.before).read_text(encoding="utf-8"))
        except OSError as e:
            die(f"cannot read --before {args.before}: {e}")
        except ValueError:
            # A video or other binary file gives UnicodeDecodeError, a wrong text file JSONDecodeError.
            die(f"--before takes the check.json an earlier round wrote, such as work/check1/check.json, "
                f"not a video or another file: {args.before}")
        if not isinstance(before, dict) or "findings" not in before:
            die(f"--before {args.before} is not a check.json from check.py: it has no findings")
    sh = sheets(video, info, len(g), fps, findings, args.out, args.every, before)
    result = {"version": VERSION, "video": video, "spec": info, "picture": pic, "sound": snd,
              "findings": findings, "sheets": sh,
              "planned": {k: getattr(args, k) for k in ("expect", "fps", "duration", "loudness", "audio", "loop",
                                                         "holds", "flashes")},
              "not_checked": ["whether it is good: story, pacing, taste", "spelling and meaning of on-screen text",
                              "text size and position (look at the sheets)", "what the sound is: nobody listened",
                              "lip sync and sound against picture", "colour and grade"]}
    if before:
        result["compared_with_before"] = compare(before, findings)
    Path(args.out).mkdir(parents=True, exist_ok=True)
    Path(args.out, "check.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")

    s = info
    print(f"{Path(video).name}: {s['width']}x{s['height']} {s['fps']} fps {s['duration']:.2f} s {s['codec']} {s['pix_fmt']}"
          + (f", audio {s['audio']['codec']} {s['audio']['sample_rate']} Hz" if s["audio"] else ", no audio"))
    print(f"picture: {pic['frames']} frames, {len(pic['cuts'])} cuts ({pic['cuts_per_minute']}/min), shots "
          f"{pic['shot_seconds']['shortest']}-{pic['shot_seconds']['longest']} s, still {100 * pic['still_share']:.0f}%"
          + (f", loop {pic['loop']['state']}" if pic["loop"] else ""))
    if snd:
        print(f"sound: {snd['lufs']} LUFS (target {args.loudness:g}), true peak {snd['true_peak_dbtp']} dBTP, "
              f"{len(snd['silences'])} silence(s) over 0.5 s")
    for f in findings:
        span = f"{f['t']:.2f}s" + (f"-{f['t_end']:.2f}s" if f.get("t_end", f["t"]) != f["t"] else "")
        print(f"  {f['level']} t={span} {f['code']}: {f['what']} -> {f['fix']}")
    if not findings:
        print("  no machine findings. That says nothing about whether the edit is good: look at the sheets.")
    if before:
        c = result["compared_with_before"]
        print(f"against the earlier round: {len(c['gone'])} gone (fixed, or now declared as planned), "
              f"{len(c['still'])} still there, {len(c['new'])} new")
    print("sheets: " + ", ".join(sh["overview"] + [p for p in (sh["findings"], sh["before_after"]) if p]))


if __name__ == "__main__":
    main()
