"""Shared helpers: ffmpeg calls, frame and audio decoding, contact sheets, JSON."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np


def die(msg):
    sys.exit("video-breakdown: " + msg)


def need(tool):
    if not shutil.which(tool):
        die(f"{tool} not found in PATH. Install FFmpeg (it ships ffprobe) and open a new terminal.")


def run(cmd, **kw):
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", **kw)


def probe(path):
    need("ffprobe")
    if not Path(path).is_file():
        die(f"no file at {path}. Give the path of a video on this machine.")
    r = run(["ffprobe", "-v", "error", "-show_entries",
             "format=duration:stream=codec_type,width,height,r_frame_rate,avg_frame_rate,sample_rate,channels",
             "-of", "json", path])
    if r.returncode:
        die(f"cannot read {path}: {r.stderr.strip()[:300]}")
    d = json.loads(r.stdout)
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), None)
    if not v:
        die(f"{path} has no video stream.")
    fps = 30.0
    for key in ("avg_frame_rate", "r_frame_rate"):
        val = v.get(key, "0/0")
        if val and val != "0/0":
            n, m = val.split("/")
            if float(m or 1) and float(n) > 0:
                fps = float(n) / float(m or 1)
                break
    return {"duration": float(d.get("format", {}).get("duration") or 0), "fps": round(fps, 3),
            "width": v.get("width"), "height": v.get("height"), "has_audio": a is not None}


def frame_size(info, width):
    h = int(round(width * (info["height"] or 9) / (info["width"] or 16) / 2) * 2)
    return width, max(h, 2)


def iter_frames(video, fps, width, height, seconds=None):
    """Yield RGB frames (uint8, height x width x 3) at a fixed rate, one ffmpeg pass."""
    need("ffmpeg")
    cmd = ["ffmpeg", "-v", "error", "-nostdin"]
    if seconds:
        cmd += ["-t", f"{seconds:.3f}"]
    cmd += ["-i", str(video), "-an", "-vf", f"fps={fps},scale={width}:{height}:flags=area,format=rgb24",
            "-f", "rawvideo", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = width * height * 3
    try:
        while True:
            buf = p.stdout.read(size)
            if len(buf) < size:
                break
            yield np.frombuffer(buf, np.uint8).reshape(height, width, 3)
    finally:
        p.stdout.close()
        p.wait()


def grab(video, times, width, info):
    """RGB frames at the given times (seconds), drawn at `width` pixels wide. One ffmpeg call per frame."""
    w, h = frame_size(info, width)
    out = []
    for t in times:
        r = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{max(0.0, t):.3f}", "-i", str(video),
                            "-frames:v", "1", "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           capture_output=True)
        out.append(np.frombuffer(r.stdout[: w * h * 3], np.uint8).reshape(h, w, 3) if len(r.stdout) >= w * h * 3 else None)
    return out


def sheet(tiles, labels, out, cols):
    """Paste RGB tiles into one labelled PNG. Returns the path, or None without Pillow."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    pairs = [(t, lab) for t, lab in zip(tiles, labels) if t is not None]
    if not pairs:
        return None
    h, w = pairs[0][0].shape[:2]
    rows = (len(pairs) + cols - 1) // cols
    s = Image.new("RGB", (w * min(cols, len(pairs)), h * rows), (40, 40, 40))
    for k, (t, lab) in enumerate(pairs):
        img = Image.fromarray(t)
        d = ImageDraw.Draw(img)
        if lab:
            d.rectangle([0, 0, 8 + 6 * len(lab), 13], fill=(0, 0, 0))
            d.text((3, 1), lab, fill=(255, 255, 255))
        s.paste(img, ((k % cols) * w, (k // cols) * h))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    s.save(out)
    return str(out)


def decode_audio(path, sr=22050):
    """Mono float32 samples; empty when the file has no audio."""
    need("ffmpeg")
    r = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr),
                        "-f", "f32le", "-"], capture_output=True)
    return np.frombuffer(r.stdout, np.float32).copy()


def lufs(path):
    import re
    r = run(["ffmpeg", "-v", "info", "-nostdin", "-i", path, "-map", "0:a:0", "-af", "ebur128=framelog=quiet",
             "-f", "null", "-"])
    m = re.findall(r"I:\s+(-?[0-9.]+) LUFS", r.stderr)
    return float(m[-1]) if m else None


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        die(f"no file at {path}")
    except json.JSONDecodeError as e:
        die(f"{path} is not valid JSON: {e}")


def utf8_stdout():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
