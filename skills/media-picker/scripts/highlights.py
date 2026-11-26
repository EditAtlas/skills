#!/usr/bin/env python3
"""Pick the best moments of the person's own clips and cut them to a music track: a recap, a highlight reel, a montage.

    python highlights.py c1.mp4 c2.mp4 c3.mov --music track.mp3 --out work/highlights --target 1080x1920
    python highlights.py c*.mp4 --music track.mp3 --seconds 20 --pace fast --every --out work/highlights --preview

Each clip is sampled about four times a second, and each sample is scored for focus (edge detail), exposure (not
too dark or blown out), colour and steadiness, each against all the clips together. A window of the shot's length
scores the mean of its samples; a window with a cut inside it, or that overlaps one already taken from the clip,
is not used. Shots are taken round-robin across the clips in the order they were filmed (the creation time in the
file, else the file's date), so the cut tells things in order and two shots from one clip never sit side by side
while another clip has a good window left.

With music, every shot is a whole number of beats (long and short in the pattern L S S L L S: the long one the
fewest of 2, 4, 8 or 16 beats that last 1.5 s, the short one half of it when that lasts 0.8 s), so every cut
lands on a beat; the cut ends on a bar; and the song starts on the bar where it lifts the most (its energy over the
next two bars against the bar before), within its first half. Without music, shots last about 2 s in an uneven
rhythm. The length is --seconds, else half the good footage, between 12 and 40 s, and never longer than the song.
--pace calm or fast makes shots longer or shorter; --every takes at least one shot from every clip (shorter shots,
half beats if needed). These are the rules of Editroom's AutoPlanner (MIT), measured here with FFmpeg and numpy.

Writes <out>/highlights.json (the shots with their in and out, the music start, the beats), summary.md, sheet.png
(the middle frame of each shot, numbered, with its clip and time: look at it), and fragment.json, an
editable-export project (footage track and music) for package.py build. --preview also renders preview.mp4, small
and quick, to watch the rhythm. The scores see pixels, not meaning: a sharp, bright, steady shot of a wall can win
over a blurry laugh. Look at the sheet and swap shots by hand (edit highlights.json and run with --from).
"""
import argparse
import datetime
import json
import math
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # also under python -I
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from measure import SR, decode, fail, frame_at, parse_size, probe, run, spectrum, tempo  # noqa: E402

SAMPLE_W, SAMPLE_H = 160, 90
RHYTHM = [True, False, False, True, True, False]
FREE = [2.4, 1.8, 2.1, 2.8, 1.7, 2.2]
PACE = {"calm": 1.7, "normal": 1.0, "fast": 0.55}


# ---- clips

def created(path, info):
    tags = info.get("format", {}).get("tags", {}) or {}
    for s in info.get("streams", []):
        tags = {**(s.get("tags") or {}), **tags}
    stamp = tags.get("creation_time") or tags.get("com.apple.quicktime.creationdate")
    if stamp:
        try:
            return datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return os.path.getmtime(path)


def samples(path, duration):
    """RGB frames at about 4 a second (at most 600), 160x90, and their times in the file."""
    fps = min(4.0, 600 / max(duration, 0.1))
    done = run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-vf",
                f"fps={fps:.4f},scale={SAMPLE_W}:{SAMPLE_H}:force_original_aspect_ratio=disable,format=rgb24", "-f", "rawvideo", "-"])
    size = SAMPLE_W * SAMPLE_H * 3
    count = len(done.stdout) // size
    frames = np.frombuffer(done.stdout[: count * size], np.uint8).reshape(count, SAMPLE_H, SAMPLE_W, 3).astype(np.float32)
    return frames, (np.arange(count) + 0.5) / fps


def measures(frames):
    """Per sample: brightness 0-1, focus (variance of the Laplacian), colourfulness, change since the sample before,
    and whether the picture changes at once there (a cut inside the clip)."""
    gray = frames @ np.array([0.299, 0.587, 0.114], np.float32)
    luma = gray.mean(axis=(1, 2)) / 255
    lap = 4 * gray[:, 1:-1, 1:-1] - gray[:, :-2, 1:-1] - gray[:, 2:, 1:-1] - gray[:, 1:-1, :-2] - gray[:, 1:-1, 2:]
    sharp = lap.var(axis=(1, 2))
    r, g, b = frames[..., 0], frames[..., 1], frames[..., 2]
    rg, yb = r - g, 0.5 * (r + g) - b
    colour = np.sqrt(rg.std(axis=(1, 2)) ** 2 + yb.std(axis=(1, 2)) ** 2) + 0.3 * np.sqrt(rg.mean(axis=(1, 2)) ** 2 + yb.mean(axis=(1, 2)) ** 2)
    diff = np.zeros(len(frames), np.float32)
    cut = np.zeros(len(frames), bool)
    if len(frames) > 1:
        diff[1:] = np.abs(np.diff(gray, axis=0)).mean(axis=(1, 2)) / 255
        hist = np.stack([np.histogram(f, bins=32, range=(0, 256))[0] for f in gray]).astype(float)
        hist /= hist.sum(axis=1, keepdims=True) + 1e-9
        hd = np.zeros(len(frames))
        hd[1:] = 0.5 * np.abs(np.diff(hist, axis=0)).sum(axis=1)
        cut = (hd > 0.35) & (diff > 0.12)
    return {"luma": luma, "sharp": sharp, "colour": colour, "motion": diff, "cut": cut}


def scorer(all_m):
    """Scores 0-1 for each sample, each measure placed between its 10th and 90th percentile over every clip."""
    def span(v):
        lo, hi = np.percentile(v, 10), np.percentile(v, 90)
        return lambda x: np.clip((x - lo) / (hi - lo + 1e-9), 0, 1)
    sharp = span(np.log1p(np.concatenate([m["sharp"] for m in all_m])))
    colour = span(np.concatenate([m["colour"] for m in all_m]))
    motion = span(np.concatenate([m["motion"] for m in all_m]))

    def score(m):
        exposure = np.clip(1 - np.abs(m["luma"] - 0.5) * 2.2, 0, 1)
        exposure = np.where((m["luma"] < 0.1) | (m["luma"] > 0.93), 0, exposure)
        steady = 1 - motion(m["motion"])
        return 0.35 * sharp(np.log1p(m["sharp"])) + 0.25 * exposure + 0.2 * colour(m["colour"]) + 0.2 * steady
    return score


# ---- music

def beat_grid(path):
    """Tempo, beat times, the beat that starts a bar (four beats a bar), and each beat's loudness 0-1."""
    x = decode(path)
    if len(x) < SR * 4:
        fail(f"{path}: under 4 s of sound")
    mags, freqs, step = spectrum(x)
    flux = np.maximum(0, np.diff(np.log1p(mags), axis=0)).sum(axis=1)
    flux = np.concatenate([[0], flux])
    bpm, sure = tempo(flux, step)
    if not bpm:
        fail(f"{path}: no steady beat found")
    # tempo within 3 % and the phase that put the most onset energy on the grid, then each beat moved to its onset
    # (within 50 ms), so cuts land on what is heard, not on a grid that drifts
    best, per, phase = -1, 60 / bpm / step, 0.0
    for b in np.arange(bpm * 0.97, bpm * 1.03, 0.05):
        p = 60 / b / step
        for off in np.arange(0, p, 0.5):
            idx = np.round(np.arange(off, len(flux), p)).astype(int)
            v = flux[idx[idx < len(flux)]].sum()
            if v > best:
                best, per, phase = v, p, off
    bpm, period = 60 / (per * step), per * step
    reach = max(1, int(round(0.05 / step)))
    grid = np.round(np.arange(phase, len(flux), per)).astype(int)
    grid = grid[grid < len(flux)]
    snapped = [max(range(max(0, i - reach), min(len(flux), i + reach + 1)), key=lambda j: flux[j]) for i in grid]
    # a frame of the onset curve starts its window at i * hop; the onset it marks sits about half a window later
    beats = np.array(snapped, float) * step + 1024 / SR
    # the bar starts on the beat of each four with the most low-end onset energy (the kick), as beat_grid.py guesses
    low = np.concatenate([[0], np.maximum(0, np.diff(np.log1p(mags[:, freqs < 150]), axis=0)).sum(axis=1)])
    def at(t):
        return max(0, min(len(low) - 1, int(round((t - 1024 / SR) / step))))
    bar = int(np.argmax([sum(low[at(t)] for t in beats[k::4]) for k in range(4)]))
    rms = np.array([np.sqrt(np.mean(x[int(t * SR): int((t + period) * SR)] ** 2) + 1e-12) for t in beats])
    energy = rms / (rms.max() + 1e-12)
    return {"bpm": float(bpm), "sure": sure, "period": period, "beats": beats, "bar": bar, "energy": energy, "duration": len(x) / SR}


def lift_start(music, need):
    """The bar start where the song lifts the most (its next two bars against the bar before) within its first half,
    with `need` seconds of song after it; the first bar when nothing lifts by a tenth of the song's loudest beat."""
    beats, e = music["beats"], music["energy"]
    starts = [k for k in range(music["bar"], len(beats), 4) if beats[k] + need <= music["duration"] - 0.3]
    if not starts:
        return music["bar"] if music["bar"] < len(beats) else 0
    later = [k for k in starts if k >= 4 and beats[k] <= music["duration"] / 2]
    if not later:
        return starts[0]
    def lift(k):
        return float(e[k: k + 8].mean() - e[k - 4: k].mean())
    best = max(later, key=lift)
    return best if lift(best) >= 0.1 else starts[0]


# ---- the plan

def plan(clips, music, args):
    pace = PACE[args.pace]
    all_scores = np.concatenate([c["scores"] for c in clips])
    floor = np.percentile(all_scores, 30)
    period = music["period"] if music else None
    sub = 1
    long_b, short_b = 4, 2
    if period:
        long_b = next((b for b in (2, 4, 8, 16) if b * period >= 1.5 * pace), 16)
        short_b = long_b // 2 if (long_b // 2) * period >= 0.8 * pace and long_b > 1 else long_b
    good = sum(float((c["scores"] >= floor).sum()) / c["rate"] for c in clips)
    target = args.seconds or min(40.0, max(12.0, good * 0.5))
    per_shot = None
    if args.every:
        per_shot = max(0.35, target / max(1, len(clips)))
        if period and per_shot < period * 0.9:
            sub, period = 2, period / 2
        if period:
            long_b = short_b = max(1, int(per_shot // period))
    if music:
        start_k = lift_start(music, target)
        room = music["duration"] - music["beats"][start_k] - 0.3
        target = min(target, room)

    # with music, shots are counted in beats of the song's own grid (half beats with sub 2), from the start bar on
    grid = None
    if music:
        beats = music["beats"][start_k:]
        if sub == 2:
            mids = (beats[:-1] + beats[1:]) / 2
            beats = np.sort(np.concatenate([beats, mids]))
        grid = beats - beats[0]

    def beats_for(k):
        return long_b if RHYTHM[k % len(RHYTHM)] else short_b

    def span(cursor, nb):
        """Seconds from grid beat `cursor` to `cursor + nb`; past the grid's end, at the tempo."""
        if cursor + nb < len(grid):
            return float(grid[cursor + nb] - grid[cursor])
        return nb * period

    def length(k, cursor=0):
        if grid is not None:
            return span(cursor, beats_for(k))
        if per_shot:
            return per_shot * [1.08, 0.94, 1.0, 1.06, 0.92, 1.0][k % 6]
        return FREE[k % len(FREE)] * pace

    order = sorted(range(len(clips)), key=lambda i: clips[i]["created"])
    taken = {i: [] for i in order}
    shots, total, k, turn, misses, cursor = [], 0.0, 0, 0, 0, 0
    while total < target - 0.2 and misses < len(order):
        i = order[turn % len(order)]
        turn += 1
        L = length(k, cursor)
        if shots and shots[-1]["clip"] == i and any(win_left(clips[j], taken[j], L, floor) for j in order if j != i):
            continue
        if grid is None:
            L = min(L, target - total)
        # with --every, a clip with no shot yet gives its best stretch even when it scores under the others
        w = best_window(clips[i], taken[i], L, -1.0 if args.every and not taken[i] else floor)
        if not w:
            misses += 1
            continue
        misses = 0
        start, score = w
        taken[i].append((start, start + L))
        nb = beats_for(k) if grid is not None else None
        shots.append({"clip": i, "in": round(start, 3), "out": round(start + L, 3), "length": round(L, 3), "score": round(score, 3), "beats": nb})
        total += L
        cursor += nb or 0
        k += 1
    if not shots:
        fail("no clip has a usable stretch: are they very short, dark or blurred all through?")
    if grid is not None:
        # end on a bar: the last shot gives or takes beats so the count is a whole number of bars
        per_bar = 4 * sub
        last = shots[-1]
        first = cursor - last["beats"]
        extra = cursor % per_bar
        room = clips[last["clip"]]["duration"] - last["in"]
        if extra:
            longer, shorter = last["beats"] + per_bar - extra, last["beats"] - extra
            if span(first, longer) <= room and (shorter < 1 or last["beats"] <= extra):
                last["beats"] = longer
            elif shorter >= 1:
                last["beats"] = shorter
            else:
                last["beats"] = longer
        last["length"] = round(min(span(first, last["beats"]), room), 3)
        last["out"] = round(last["in"] + last["length"], 3)
        if sub == 2:
            for s in shots:
                s["beats"] = s["beats"] / 2
    at = 0.0
    for s in shots:
        s["at"] = round(at, 3)
        at += s["length"]
    return shots, (float(music["beats"][start_k]) if music else None), sub


def win_left(clip, taken, L, floor):
    return best_window(clip, taken, L, floor) is not None


def best_window(clip, taken, L, floor, apart=0.3):
    """The best stretch of L seconds in a clip that avoids its cuts and what was taken from it, as (start, score)."""
    t, s, cut = clip["times"], clip["scores"], clip["cut"]
    if L > clip["duration"] - 0.05 or not len(t):
        return None
    n = max(1, int(round(L * clip["rate"])))
    best = None
    for a in range(0, max(1, len(t) - n + 1)):
        start = max(0.0, t[a] - 0.5 / clip["rate"])
        if start + L > clip["duration"]:
            break
        if cut[a + 1: a + n].any() or any(start < e + apart and start + L > b - apart for b, e in taken):
            continue
        v = float(s[a: a + n].mean())
        if v >= floor and (best is None or v > best[1]):
            best = (start, v)
    return best


# ---- outputs

def write_outputs(clips, shots, music, music_start, args, out):
    tw, th = args.target
    data = {"format": "editatlas-highlights/1", "target": f"{tw}x{th}", "length": round(sum(s["length"] for s in shots), 3),
            "music": None if not music else {"file": str(Path(args.music).resolve()), "start": round(music_start, 3), "bpm": round(music["bpm"], 1),
                                             "sure": music["sure"]},
            "shots": [{"n": n, "file": clips[s["clip"]]["file"], "in": s["in"], "out": s["out"], "at": s["at"], "length": s["length"],
                       "beats": s["beats"], "score": s["score"]} for n, s in enumerate(shots, 1)]}
    (out / "highlights.json").write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = [f"# Highlights: {len(shots)} shots, {data['length']:.1f} s", ""]
    if music:
        lines += [f"Music: {Path(args.music).name} from {music_start:.2f} s, about {music['bpm']:.0f} BPM (tempo sureness {music['sure']}; it may be half or double: listen)", ""]
    lines += ["| # | clip | in | out | on the timeline | beats | score |", "|---|---|---|---|---|---|---|"]
    for row in data["shots"]:
        lines.append(f"| {row['n']} | {Path(row['file']).name} | {row['in']:.2f} | {row['out']:.2f} | {row['at']:.2f} | {row['beats'] or ''} | {row['score']:.2f} |")
    unused = [Path(c["file"]).name for i, c in enumerate(clips) if not any(s["clip"] == i for s in shots)]
    if unused:
        lines += ["", "Not used (no good stretch left, or the cut was full): " + ", ".join(unused)]
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    # the sheet
    tiles = []
    for row in data["shots"]:
        img = frame_at(row["file"], (row["in"] + row["out"]) / 2, 320)
        if img is None:
            continue
        d = ImageDraw.Draw(img)
        lab = f"{row['n']} · {Path(row['file']).name} {row['in']:.1f}-{row['out']:.1f}s"
        d.rectangle([0, 0, 10 + 6 * len(lab), 16], fill=(0, 0, 0))
        d.text((4, 2), lab, fill=(255, 255, 255))
        tiles.append(img)
    if tiles:
        cols = min(4, len(tiles))
        w, h = tiles[0].width, max(t.height for t in tiles)
        sheet = Image.new("RGB", (cols * (w + 6) + 6, math.ceil(len(tiles) / cols) * (h + 6) + 6), (24, 24, 26))
        for i, t in enumerate(tiles):
            sheet.paste(t, (6 + (i % cols) * (w + 6), 6 + (i // cols) * (h + 6)))
        sheet.save(out / "sheet.png")
    # the editable-export fragment
    media, v1 = {}, []
    for row in data["shots"]:
        mid = "c" + str(sorted({r["file"] for r in data["shots"]}).index(row["file"]) + 1)
        media[mid] = {"kind": "video", "path": rel(row["file"], out)}
        v1.append({"id": f"s{row['n']}", "media": mid, "in": row["in"], "out": row["out"], "volume": 0 if music else 1, "fit": "cover", "x": 0.5, "y": 0.5})
    tracks = [{"id": "V1", "kind": "video", "name": "Footage", "clips": v1}]
    if music:
        media["music"] = {"kind": "audio", "path": rel(args.music, out), "title": Path(args.music).stem}
        tracks.append({"id": "A1", "kind": "audio", "name": "Music", "items": [
            {"id": "music", "media": "music", "at": 0.0, "in": round(music_start, 3), "out": round(music_start + data["length"], 3), "gain_db": 0.0, "fade_out": 0.5}]})
    frag = {"format": "editatlas-project/1", "title": "Highlights", "canvas": {"width": tw, "height": th, "fps": 30}, "media": media, "tracks": tracks}
    (out / "fragment.json").write_text(json.dumps(frag, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return data


def rel(path, base):
    try:
        return Path(os.path.relpath(Path(path).resolve(), Path(base).resolve())).as_posix()
    except ValueError:  # another drive
        return Path(path).resolve().as_posix()


def preview(data, args, out):
    tw, th = args.target
    w = 540 if th >= tw else 960
    h = int(round(w * th / tw / 2) * 2)
    cmd, parts = ["ffmpeg", "-v", "error", "-y", "-nostdin"], []
    for n, row in enumerate(data["shots"]):
        cmd += ["-ss", f"{row['in']:.3f}", "-t", f"{row['length']:.3f}", "-i", row["file"]]
        parts.append(f"[{n}:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps=30,trim=duration={row['length']:.3f},setpts=PTS-STARTPTS[v{n}]")
    graph = ";".join(parts) + ";" + "".join(f"[v{n}]" for n in range(len(data["shots"]))) + f"concat=n={len(data['shots'])}:v=1:a=0[v]"
    maps = ["-map", "[v]"]
    if data["music"]:
        m = len(data["shots"])
        cmd += ["-ss", f"{data['music']['start']:.3f}", "-t", f"{data['length']:.3f}", "-i", data["music"]["file"]]
        graph += f";[{m}:a]afade=t=out:st={max(0, data['length'] - 0.5):.3f}:d=0.5[a]"
        maps += ["-map", "[a]", "-c:a", "aac", "-b:a", "128k"]
    cmd += ["-filter_complex", graph, *maps, "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p",
            "-threads", "4", str(out / "preview.mp4")]
    done = run(cmd)
    if done.returncode:
        fail("the preview did not render: " + done.stderr.decode(errors="replace")[-400:])
    print(f"Preview: {out / 'preview.mp4'} ({w}x{h}, small and quick: watch the rhythm, not the picture quality)")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("clips", nargs="*")
    p.add_argument("--out", required=True)
    p.add_argument("--music", help="the track to cut to")
    p.add_argument("--seconds", type=float, help="length of the cut (default: half the good footage, 12 to 40 s)")
    p.add_argument("--target", type=parse_size, default=(1080, 1920), help="frame, such as 1080x1920 (default)")
    p.add_argument("--pace", choices=sorted(PACE), default="normal")
    p.add_argument("--every", action="store_true", help="at least one shot from every clip")
    p.add_argument("--preview", action="store_true", help="also render a small preview.mp4")
    p.add_argument("--from", dest="source", help="a highlights.json you edited: write its sheet, fragment and preview again")
    args = p.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.source:
        data = json.loads(Path(args.source).read_text(encoding="utf-8"))
        at = 0.0
        for n, row in enumerate(data["shots"], 1):
            row["n"], row["length"], row["at"] = n, round(row["out"] - row["in"], 3), round(at, 3)
            at += row["length"]
        data["length"] = round(at, 3)
        files = sorted({r["file"] for r in data["shots"]})
        clips = [{"file": f, "duration": 0} for f in files]
        shots = [{"clip": files.index(r["file"]), **{k: r[k] for k in ("in", "out", "length", "score", "beats", "at")}} for r in data["shots"]]
        if data.get("music"):
            args.music = data["music"]["file"]
            music = {"bpm": data["music"]["bpm"], "sure": data["music"].get("sure")}
            data = write_outputs(clips, shots, music, data["music"]["start"], args, out)
        else:
            data = write_outputs(clips, shots, None, None, args, out)
        if args.preview:
            preview(data, args, out)
        return
    if not args.clips:
        fail("give the clips")
    clips = []
    for f in args.clips:
        path = Path(f)
        if not path.is_file():
            fail(f"{f} not found")
        info = probe(path)
        if not any(s.get("codec_type") == "video" for s in info.get("streams", [])):
            fail(f"{f} has no picture")
        duration = float(info.get("format", {}).get("duration") or 0)
        frames, times = samples(path, duration)
        if not len(frames):
            print(f"highlights: {path.name}: no frames read, left out")
            continue
        clips.append({"file": str(path.resolve()), "duration": duration, "created": created(path, info), "times": times,
                      "rate": 1 / (times[1] - times[0]) if len(times) > 1 else 4.0, "m": measures(frames)})
    if not clips:
        fail("no clip could be read")
    score = scorer([c["m"] for c in clips])
    for c in clips:
        c["scores"], c["cut"] = score(c["m"]), c["m"]["cut"]
    music = beat_grid(args.music) if args.music else None
    shots, start, _ = plan(clips, music, args)
    data = write_outputs(clips, shots, music, start, args, out)
    if args.preview:
        preview(data, args, out)
    print(f"Wrote {out / 'highlights.json'}, summary.md, sheet.png and fragment.json. Look at sheet.png before you use it.")


if __name__ == "__main__":
    main()
