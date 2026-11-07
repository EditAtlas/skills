"""Find the moments in a video that may want a sound, and draw frames so you can see them.

  moments.py VIDEO --out work/moments          # moments.json + sheet.png (+ audio.json about the existing sound)
  moments.py VIDEO --at 3.2 --span 1.2 --out work/at3   # frames around one time, to look closely

Kinds: cut (the picture changes at once), move (motion starts or peaks), land (motion stops: something settles).
These are hints from pixel differences. Soft animation often moves without a cut; look at the sheet and write
the event list yourself where the numbers miss things.
"""
import argparse
import re
import subprocess
from pathlib import Path

import numpy as np

from common import decode, need, probe, utf8_stdout, window_db, write_json, run

W = 96  # analysis width in pixels


def gray_frames(video, fps):
    need("ffmpeg")
    info = probe(video)
    h = int(round(W * (info["height"] or 9) / (info["width"] or 16) / 2) * 2) or 54
    r = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(video), "-vf",
                        f"fps={fps},scale={W}:{h},format=gray", "-f", "rawvideo", "-"], capture_output=True)
    return np.frombuffer(r.stdout, np.uint8).reshape(-1, h, W).astype(np.float32), h


def scene_cuts(video, thr):
    r = run(["ffmpeg", "-v", "info", "-nostdin", "-i", video, "-vf", f"select='gt(scene,{thr})',showinfo",
             "-an", "-f", "null", "-"])
    return [float(m) for m in re.findall(r"pts_time:([0-9.]+)", r.stderr)]


def peaks(x, t, thr, min_gap):
    out = []
    for i in range(1, len(x) - 1):
        if x[i] >= thr and x[i] >= x[i - 1] and x[i] > x[i + 1]:
            if out and t[i] - out[-1][0] < min_gap:
                if x[i] > out[-1][1]:
                    out[-1] = (t[i], x[i])
                continue
            out.append((t[i], x[i]))
    return out


def find(video, fps=30, cut_thr=0.32):
    frames, _ = gray_frames(video, fps)
    if len(frames) < 3:
        return [], {}
    diff = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2))           # motion between frames
    t = (np.arange(len(diff)) + 1) / fps
    k = max(1, int(fps * 0.1))
    sm = np.convolve(diff, np.ones(k) / k, mode="same")
    med = float(np.median(sm))
    mad = float(np.median(np.abs(sm - med))) + 1e-6
    still = med * 0.35 + 0.05
    moments = []
    cuts = scene_cuts(str(video), cut_thr)
    for c in cuts:
        moments.append({"t": round(c, 3), "kind": "cut", "strength": 1.0})
    for tt, v in peaks(sm, t, med + 3 * mad, 0.35):
        if all(abs(tt - c) > 0.15 for c in cuts):
            moments.append({"t": round(float(tt), 3), "kind": "move", "strength": round(min(1.0, v / (sm.max() + 1e-9)), 2)})
    # landing: a clear burst of motion that falls to under 40 % of its peak within 0.4 s. A face that keeps
    # moving a little (a talking head) crosses a plain threshold all the time, so the burst must stand well above
    # the film's own median motion, and landings closer than 0.5 s count once.
    moving = sm > max(still * 3, med)
    last_land = -1.0
    for i in range(1, len(sm)):
        if moving[i - 1] and not moving[i] and sm[i] < still * 3:
            back = sm[max(0, i - int(fps * 0.4)): i]
            if len(back) and back.max() > med + 4 * mad and sm[i] < 0.4 * back.max():
                tt = float(t[i])
                if tt - last_land >= 0.5 and all(abs(tt - m["t"]) > 0.12 for m in moments):
                    moments.append({"t": round(tt, 3), "kind": "land", "strength": round(float(back.max() / (sm.max() + 1e-9)), 2)})
                    last_land = tt
    moments.sort(key=lambda m: m["t"])
    curve = {"fps": fps, "motion": [round(float(v), 3) for v in sm[:: max(1, fps // 10)]], "step_s": max(1, fps // 10) / fps}
    return moments, curve


def audio_report(video, info):
    if not info["has_audio"]:
        return {"has_audio": False}
    x = decode(video)
    if len(x) == 0:
        return {"has_audio": False}
    mono = x.mean(axis=1)
    w = window_db(mono)
    r = run(["ffmpeg", "-v", "info", "-nostdin", "-i", video, "-map", "0:a:0", "-af", "ebur128=framelog=quiet",
             "-f", "null", "-"])
    m = re.findall(r"I:\s+(-?[0-9.]+) LUFS", r.stderr)
    silent = float((w < -60).mean()) if len(w) else 1.0
    return {"has_audio": True, "lufs": float(m[-1]) if m else None,
            "silent_share": round(silent, 2), "loudest_dbfs": round(float(w.max()), 1) if len(w) else None,
            "note": "silent_share near 1.0 means the track is empty: treat the film as picture only"}


def sheet(video, times, out, labels=None, cols=6, width=240):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    info = probe(video)
    h = int(width * (info["height"] or 9) / (info["width"] or 16))
    tiles = []
    for k, tt in enumerate(times):
        r = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{max(0.0, tt):.3f}", "-i", str(video),
                            "-frames:v", "1", "-vf", f"scale={width}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           capture_output=True)
        if len(r.stdout) < width * h * 3:
            continue
        img = Image.fromarray(np.frombuffer(r.stdout[: width * h * 3], np.uint8).reshape(h, width, 3))
        d = ImageDraw.Draw(img)
        lab = f"{tt:.2f}s" + (f" {labels[k]}" if labels else "")
        d.rectangle([0, 0, 8 + 7 * len(lab), 14], fill=(0, 0, 0))
        d.text((3, 1), lab, fill=(255, 255, 255))
        tiles.append(img)
    if not tiles:
        return None
    rows = (len(tiles) + cols - 1) // cols
    s = Image.new("RGB", (width * min(cols, len(tiles)), h * rows))
    for k, t in enumerate(tiles):
        s.paste(t, ((k % cols) * width, (k // cols) * h))
    s.save(out)
    return out


def main():
    utf8_stdout()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("video")
    p.add_argument("--out", required=True, help="folder")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--cut", type=float, default=0.32, help="scene-change threshold 0..1")
    p.add_argument("--at", type=float, help="only draw frames around this time")
    p.add_argument("--span", type=float, default=1.2)
    p.add_argument("--step", type=float, default=0.1)
    a = p.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    info = probe(a.video)
    if a.at is not None:
        ts = list(np.arange(a.at - a.span / 2, a.at + a.span / 2 + 1e-6, a.step))
        print("->", sheet(a.video, ts, out / f"at_{a.at:.2f}.png", cols=6))
        return
    moments, curve = find(a.video, a.fps, a.cut)
    aud = audio_report(a.video, info)
    write_json(out / "moments.json", {"video": str(Path(a.video).resolve()), "duration": info["duration"],
                                      "fps": info["fps"], "audio": aud, "moments": moments, "motion": curve})
    s = sheet(a.video, [m["t"] for m in moments][:48], out / "sheet.png", [m["kind"] for m in moments][:48])
    # an overview of the whole film, one frame a second, helps more than the moments alone
    ov = sheet(a.video, list(np.arange(0.5, info["duration"], max(1.0, info["duration"] / 24))), out / "overview.png")
    kinds = {}
    for m in moments:
        kinds[m["kind"]] = kinds.get(m["kind"], 0) + 1
    print(f"{info['duration']:.2f}s at {info['fps']:.0f} fps, {len(moments)} moments {kinds}")
    print(f"existing audio: {aud}")
    for m in moments:
        print(f"  {m['t']:7.3f}  {m['kind']:<5} {m['strength']}")
    print("->", out / "moments.json", s or "(no sheet: pip install pillow)", ov or "")


if __name__ == "__main__":
    main()
