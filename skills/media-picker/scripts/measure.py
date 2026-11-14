#!/usr/bin/env python3
"""Measure stock clips, photos, music and sound effects before they go into an edit.

    python measure.py clip1.mp4 https://.../clip2.mp4 photo.jpg track.mp3 --out work/assets --target 1080x1920 --slot 4

Each item is a local file or an http(s) link (downloaded into <out>/files). The kind is read from the file: video,
photo, music (audio over 20 s) or sfx (shorter audio); --kind forces one for every item.

Video: size, frame rate, length, how much survives a crop to --target and how far it must be scaled up, camera shake
(the jitter left after smoothing the camera path, in % of the frame width per tenth of a second), pan speed, cuts
inside the clip, brightness, warm or cool, the steadiest stretch of --slot seconds without a cut, and a sheet of six
frames with the --target crop drawn on each. Photo: size, crop, scale, brightness, warm or cool, a sheet.
Music: length, loudness and its range, tempo (it may be half or double) and how steady the beat is, how many notes and
hits a minute, how long the intro takes to reach full level, how it ends, how bright it sounds, and an energy strip.
No key or mood: they are not measured reliably here, so the person listens. SFX: length, how fast it hits,
its tail, peak and loudness.

Across items it flags two picks that are the same clip and a video whose brightness or colour stands apart.
Writes <out>/assets.json, <out>/summary.md and <out>/sheets/*.png, and prints the summary. Numbers only: whether a
clip shows what the line says, or a track has the right feeling, is for you to look at and for the person to hear.
"""
import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

VERSION = "0.1.0"
SR = 22050
MOTION_FPS = 10
MOTION_WIDTH = 320
MAX_VIDEO_SECONDS = 90
MAX_AUDIO_SECONDS = 300
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}

# From 40 Pexels clips and 15 with added shake (references/reading-the-numbers.md): 18 of 20 clips searched as
# steady read under 0.15; handheld walking clips read 0.25 to 2.9; a 2 px jitter at 640 px wide reads about 0.5.
SHAKE_SLIGHT = 0.25
SHAKE_SHAKY = 0.6


def fail(message):
    sys.exit(f"measure: {message}")


def run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True)
    except FileNotFoundError:
        fail(f"{cmd[0]} is not installed or not in PATH")


def fetch(item, folder):
    """A local path as is; a link downloaded once into folder."""
    if not re.match(r"^https?://", item):
        path = Path(item)
        if not path.is_file():
            fail(f"no such file: {item}")
        return path
    folder.mkdir(parents=True, exist_ok=True)
    name = Path(urllib.parse.urlparse(item).path).name or "download"
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)[-80:]
    target = folder / name
    if target.exists() and target.stat().st_size:
        return target
    request = urllib.request.Request(item, headers={"User-Agent": "Mozilla/5.0 (EditAtlas media-picker)"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, open(target, "wb") as out:
            shutil.copyfileobj(response, out)
    except Exception as error:  # noqa: BLE001 - every download failure is reported the same way
        target.unlink(missing_ok=True)
        fail(f"could not download {item} ({error}). Download it in a browser and pass the file instead.")
    return target


def probe(path):
    done = run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)])
    if done.returncode:
        fail(f"ffprobe could not read {path}")
    return json.loads(done.stdout or b"{}")


def kind_of(path, info):
    streams = info.get("streams", [])
    video = [s for s in streams if s.get("codec_type") == "video"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    duration = float(info.get("format", {}).get("duration") or 0)
    if video:
        single = path.suffix.lower() in IMAGE_EXT or video[0].get("codec_name") in {"mjpeg", "png", "webp", "bmp", "tiff"} and duration < 0.5
        return "photo" if single else "video"
    if audio:
        return "music" if duration > 20 else "sfx"
    fail(f"{path} has no picture and no sound")


def parse_size(text):
    match = re.fullmatch(r"(\d{2,5})x(\d{2,5})", text or "")
    if not match:
        fail(f"--target must look like 1080x1920, not {text!r}")
    return int(match[1]), int(match[2])


def crop_numbers(width, height, target):
    """Share of the frame kept by a centred crop to the target shape, and the scale-up that crop then needs."""
    if not target or not width or not height:
        return None, None
    tw, th = target
    if width / height > tw / th:
        cw, ch = height * tw / th, height
    else:
        cw, ch = width, width * th / tw
    return round(cw * ch / (width * height), 2), round(tw / cw, 2)


def crop_box(width, height, target):
    if not target:
        return None
    tw, th = target
    if width / height > tw / th:
        cw, ch = height * tw / th, height
    else:
        cw, ch = width, width * th / tw
    return ((width - cw) / 2, (height - ch) / 2, (width + cw) / 2, (height + ch) / 2)


# ---------------------------------------------------------------- pictures

def gray_frames(path, seconds):
    height_cmd = f"fps={MOTION_FPS},scale={MOTION_WIDTH}:-2,format=gray"
    done = run(["ffmpeg", "-v", "error", "-nostdin", "-t", str(seconds), "-i", str(path), "-vf", height_cmd, "-f", "rawvideo", "-"])
    info = probe_frame_size(path)
    w = MOTION_WIDTH
    h = int(round(info[1] * MOTION_WIDTH / info[0] / 2) * 2) if info[0] else 0
    if not h or not done.stdout:
        return np.zeros((0, 1, 1), np.float32)
    count = len(done.stdout) // (w * h)
    return np.frombuffer(done.stdout[: count * w * h], np.uint8).reshape(count, h, w).astype(np.float32)


def probe_frame_size(path):
    info = probe(path)
    for stream in info.get("streams", []):
        if stream.get("codec_type") == "video":
            w, h = int(stream.get("width") or 0), int(stream.get("height") or 0)
            if str(stream.get("tags", {}).get("rotate", "0")) in {"90", "270", "-90"}:
                w, h = h, w
            for side in stream.get("side_data_list", []) or []:
                if abs(int(side.get("rotation", 0) or 0)) in (90, 270):
                    w, h = h, w
            return w, h
    return 0, 0


def refine(corr, i, size):
    """Sub-pixel offset of a correlation peak along one axis, from a parabola through it and its neighbours."""
    a, b, c = corr[(i - 1) % size], corr[i], corr[(i + 1) % size]
    den = a - 2 * b + c
    return 0.0 if abs(den) < 1e-12 else float(np.clip(0.5 * (a - c) / den, -0.5, 0.5))


def phase_shift(a, b, h, w):
    cross = a * np.conj(b)
    cross /= np.abs(cross) + 1e-9
    corr = np.fft.irfft2(cross, s=(h, w))
    py, px = np.unravel_index(np.argmax(corr), corr.shape)
    dy = py + refine(corr[:, px], py, h)
    dx = px + refine(corr[py, :], px, w)
    dy = dy - h if dy > h / 2 else dy
    dx = dx - w if dx > w / 2 else dx
    return dx, dy, float(corr.max())


def shifts(frames, grid=3):
    """Camera move between neighbouring frames: dx, dy in pixels at MOTION_WIDTH, and how clear.

    Phase correlation runs on each tile of a grid and the camera move is the median over the tiles whose peak is
    clear, so a pouring liquid or a passing car that fills one part of the frame does not count as the camera.
    """
    if len(frames) < 2:
        return np.zeros((0, 2)), np.zeros(0)
    h, w = frames.shape[1:]
    th, tw = h // grid, w // grid
    window = np.outer(np.hanning(th), np.hanning(tw)).astype(np.float32)
    tiles = []
    for r in range(grid):
        for c in range(grid):
            part = frames[:, r * th:(r + 1) * th, c * tw:(c + 1) * tw]
            tiles.append(np.fft.rfft2((part - part.mean(axis=(1, 2), keepdims=True)) * window))
    moves, clarity = [], []
    for i in range(len(frames) - 1):
        found = [phase_shift(t[i], t[i + 1], th, tw) for t in tiles]
        clear = [f for f in found if f[2] > 0.08] or sorted(found, key=lambda f: -f[2])[: max(1, len(found) // 3)]
        moves.append((float(np.median([f[0] for f in clear])), float(np.median([f[1] for f in clear]))))
        clarity.append(float(np.median([f[2] for f in found])))
    return np.array(moves, float), np.array(clarity)


def cuts_in(frames):
    """Frame indexes where the picture changes at once: a cut inside the clip."""
    if len(frames) < 3:
        return []
    hist = np.stack([np.histogram(f, bins=32, range=(0, 256))[0] for f in frames]).astype(float)
    hist /= hist.sum(axis=1, keepdims=True)
    diff = 0.5 * np.abs(np.diff(hist, axis=0)).sum(axis=1)
    level = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2)) / 255
    base = np.median(diff) + 1e-3
    return [i + 1 for i, (d, l) in enumerate(zip(diff, level)) if d > 0.35 and d > 6 * base and l > 0.12]


def smooth(values, size):
    if len(values) < size:
        return np.repeat(values.mean(axis=0, keepdims=True), len(values), axis=0) if len(values) else values
    kernel = np.ones(size) / size
    padded = np.pad(values, ((size // 2, size - 1 - size // 2), (0, 0)), mode="edge")
    return np.stack([np.convolve(padded[:, i], kernel, mode="valid") for i in range(values.shape[1])], axis=1)


def motion(frames, cuts):
    """Shake (jitter after smoothing, % of width per step), pan speed (% of width per second), per-step jitter."""
    moves, clarity = shifts(frames)
    if not len(moves):
        return None, None, np.zeros(0), 0.0
    for c in cuts:  # a cut is not a camera move
        if 0 < c <= len(moves):
            moves[c - 1] = 0
    path = np.cumsum(moves, axis=0)
    steady = smooth(path, MOTION_FPS)
    residual = np.linalg.norm(path - steady, axis=1)
    jitter = np.abs(np.diff(np.vstack([[0, 0], path - steady]), axis=0)).sum(axis=1) / MOTION_WIDTH * 100
    pan = np.linalg.norm(np.diff(steady, axis=0), axis=1).mean() * MOTION_FPS / MOTION_WIDTH * 100 if len(steady) > 1 else 0.0
    del residual
    return float(np.sqrt(np.mean(jitter ** 2))), float(pan), jitter, float(np.median(clarity))


def steadiest(jitter, cuts, length, slot):
    """Start and end (s) of the slot-long stretch with the least shake and no cut, or None when the clip is shorter."""
    steps = int(round(slot * MOTION_FPS))
    if not len(jitter) or steps < 2 or len(jitter) < steps:
        return None
    best = None
    for start in range(0, len(jitter) - steps + 1):
        if any(start < c <= start + steps for c in cuts):
            continue
        score = float(np.sqrt(np.mean(jitter[start:start + steps] ** 2)))
        if best is None or score < best[0]:
            best = (score, start)
    if best is None:
        return None
    start = best[1] / MOTION_FPS
    return {"start": round(start, 1), "end": round(min(length, start + slot), 1), "shake": round(best[0], 2)}


def colour(path, seconds=None, image=False):
    """Mean brightness (0-255) and red/blue balance from small colour frames."""
    cmd = ["ffmpeg", "-v", "error", "-nostdin"]
    if seconds:
        cmd += ["-t", str(seconds)]
    cmd += ["-i", str(path), "-vf", ("" if image else "fps=1,") + "scale=64:-2,format=rgb24", "-f", "rawvideo", "-"]
    done = run(cmd)
    data = np.frombuffer(done.stdout, np.uint8)
    if not len(data):
        return None, None
    rgb = data[: len(data) // 3 * 3].reshape(-1, 3).astype(float)
    luma = rgb @ np.array([0.2126, 0.7152, 0.0722])
    return round(float(luma.mean()), 1), round(float((rgb[:, 0].mean() + 1) / (rgb[:, 2].mean() + 1)), 2)


def dhash(img):
    small = np.asarray(img.convert("L").resize((9, 8)), float)
    return int("".join("1" if b else "0" for b in (small[:, 1:] > small[:, :-1]).flatten()), 2)


def frame_at(path, t, width=480):
    done = run(["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1",
                "-vf", f"scale={width}:-2", "-f", "image2pipe", "-vcodec", "png", "-"])
    if not done.stdout:
        return None
    from io import BytesIO
    return Image.open(BytesIO(done.stdout)).convert("RGB")


def draw_sheet(images, labels, box, size, title, out):
    """A row (or two) of frames with the target crop outlined and the area outside it dimmed."""
    tile_w = 300 if size[1] >= size[0] else 440
    tiles = []
    for img, label in zip(images, labels):
        if img is None:
            continue
        scale = tile_w / img.width
        tile = img.resize((tile_w, max(1, int(img.height * scale))))
        if box:
            x0, y0, x1, y1 = (v * tile_w / size[0] for v in box)
            shade = Image.new("RGBA", tile.size, (0, 0, 0, 0))
            d = ImageDraw.Draw(shade)
            d.rectangle([0, 0, tile.width, tile.height], fill=(0, 0, 0, 120))
            d.rectangle([x0, y0, x1, y1], fill=(0, 0, 0, 0))
            tile = Image.alpha_composite(tile.convert("RGBA"), shade).convert("RGB")
            ImageDraw.Draw(tile).rectangle([x0, y0, x1 - 1, y1 - 1], outline=(41, 151, 255), width=2)
        ImageDraw.Draw(tile).text((6, 4), label, fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0))
        tiles.append(tile)
    if not tiles:
        return
    per_row = min(3, len(tiles))
    rows = math.ceil(len(tiles) / per_row)
    th = max(t.height for t in tiles)
    sheet = Image.new("RGB", (per_row * tile_w + (per_row + 1) * 8, rows * th + (rows + 1) * 8 + 26), (24, 24, 26))
    ImageDraw.Draw(sheet).text((8, 7), title, fill=(245, 245, 247))
    for i, tile in enumerate(tiles):
        r, c = divmod(i, per_row)
        sheet.paste(tile, (8 + c * (tile_w + 8), 34 + r * (th + 8)))
    sheet.save(out)


def inspect_video(path, info, args, sheets):
    stream = next(s for s in info["streams"] if s.get("codec_type") == "video")
    width, height = probe_frame_size(path)
    rate = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1"
    num, _, den = rate.partition("/")
    fps = round(float(num) / float(den or 1), 2) if float(den or 1) else 0
    length = float(info.get("format", {}).get("duration") or stream.get("duration") or 0)
    frames = gray_frames(path, min(length, MAX_VIDEO_SECONDS) + 0.5)
    cuts = cuts_in(frames)
    shake, pan, jitter, clarity = motion(frames, cuts)
    brightness, warmth = colour(path, min(length, MAX_VIDEO_SECONDS))
    keep, upscale = crop_numbers(width, height, args.target)
    slot = steadiest(jitter, cuts, length, args.slot) if args.slot else None
    times = [length * f for f in (0.05, 0.22, 0.4, 0.58, 0.76, 0.93)]
    images = [frame_at(path, t) for t in times]
    hashes = [dhash(images[i]) for i in (1, 2, 4) if images[i] is not None]
    sheet = sheets / f"{path.stem}.png"
    title = f"{path.name}  {width}x{height}  {length:.1f}s  shake {shake if shake is None else round(shake, 2)}  cuts {len(cuts)}"
    draw_sheet(images, [f"{t:.1f}s" for t in times], crop_box(width, height, args.target), (width, height), title, sheet)
    flags = []
    if shake is not None and shake >= SHAKE_SHAKY:
        flags.append(f"shaky: {shake:.2f} (handheld, over {SHAKE_SHAKY}); a viewer feels it, worse after a crop or speed-up")
    elif shake is not None and shake >= SHAKE_SLIGHT:
        flags.append(f"slight shake: {shake:.2f}; fine for a short cut, not for a slow scene")
    if pan is not None and pan > 25:
        flags.append(f"fast camera move: {pan:.0f}% of the frame a second; hard to read in a quick cut")
    if cuts:
        flags.append(f"cuts inside at {', '.join(f'{c / MOTION_FPS:.1f}s' for c in cuts)}: use one shot between them")
    if keep is not None and keep < 0.5:
        flags.append(f"crop keeps {int(keep * 100)}% of the frame for {args.target[0]}x{args.target[1]}: check the subject stays inside the blue box")
    if upscale and upscale > 1.5:
        flags.append(f"this copy must be scaled up {upscale}x after the crop; for 1.5x at most, the edit needs a file at least {math.ceil(width * upscale / 1.5)}x{math.ceil(height * upscale / 1.5)} (pick it from video_files)")
    if args.slot and length < args.slot:
        flags.append(f"too short: {length:.1f}s for a {args.slot}s slot")
    elif args.slot and slot is None:
        flags.append(f"no {args.slot}s stretch without a cut")
    if brightness is not None and brightness < 45:
        flags.append(f"dark: mean brightness {brightness}")
    if brightness is not None and brightness > 205:
        flags.append(f"very bright: mean brightness {brightness}")
    if clarity is not None and clarity < 0.04 and shake is not None:
        flags.append("camera move unclear (busy or blurred picture): judge the shake by eye on the sheet")
    return {
        "kind": "video", "width": width, "height": height, "fps": fps, "duration": round(length, 2),
        "shake": None if shake is None else round(shake, 2), "pan": None if pan is None else round(pan, 1),
        "cuts": [round(c / MOTION_FPS, 1) for c in cuts], "brightness": brightness, "warmth": warmth,
        "crop_keep": keep, "upscale": upscale, "steadiest": slot, "sheet": str(sheet), "flags": flags, "_hashes": hashes,
    }


def inspect_photo(path, info, args, sheets):
    img = Image.open(path).convert("RGB")
    width, height = img.size
    brightness, warmth = colour(path, image=True)
    keep, upscale = crop_numbers(width, height, args.target)
    sheet = sheets / f"{path.stem}.png"
    draw_sheet([img], [f"{width}x{height}"], crop_box(width, height, args.target), (width, height), path.name, sheet)
    flags = []
    if keep is not None and keep < 0.5:
        flags.append(f"crop keeps {int(keep * 100)}% for {args.target[0]}x{args.target[1]}: check the subject stays inside the blue box")
    if upscale and upscale > 1.5:
        flags.append(f"this copy must be scaled up {upscale}x after the crop; for 1.5x at most, use an image at least {math.ceil(width * upscale / 1.5)}x{math.ceil(height * upscale / 1.5)} (the full-size image_url); a slow zoom needs more")
    if brightness is not None and brightness < 45:
        flags.append(f"dark: mean brightness {brightness}")
    return {"kind": "photo", "width": width, "height": height, "brightness": brightness, "warmth": warmth,
            "crop_keep": keep, "upscale": upscale, "sheet": str(sheet), "flags": flags, "_hashes": [dhash(img)]}


# ---------------------------------------------------------------- sound

def decode(path, seconds=MAX_AUDIO_SECONDS):
    done = run(["ffmpeg", "-v", "error", "-nostdin", "-t", str(seconds), "-i", str(path), "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"])
    return np.frombuffer(done.stdout, np.float32).copy()


def loudness(path):
    done = run(["ffmpeg", "-hide_banner", "-nostdin", "-t", str(MAX_AUDIO_SECONDS), "-i", str(path), "-vn",
                "-af", "loudnorm=print_format=json", "-f", "null", "-"])
    text = done.stderr.decode(errors="replace")
    match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", text, re.S)
    if not match:
        return None, None, None
    data = json.loads(match.group(0))
    num = lambda key: None if data.get(key) in (None, "-inf", "inf") else round(float(data[key]), 1)  # noqa: E731
    return num("input_i"), num("input_tp"), num("input_lra")


def spectrum(x, n=2048, hop=512):
    if len(x) < n:
        x = np.pad(x, (0, n - len(x)))
    k = 1 + (len(x) - n) // hop
    idx = np.arange(n)[None, :] + hop * np.arange(k)[:, None]
    return np.abs(np.fft.rfft(x[idx] * np.hanning(n).astype(np.float32), axis=1)), np.fft.rfftfreq(n, 1 / SR), hop / SR


def tempo(flux, step):
    """BPM from the autocorrelation of the onset curve, folded into 70-180, and how sure (0-1)."""
    env = flux - flux.mean()
    if len(env) < 64 or not env.any():
        return None, 0.0
    ac = np.correlate(env, env, mode="full")[len(env) - 1:]
    ac /= ac[0] + 1e-9
    lags = np.arange(len(ac)) * step
    ok = (lags > 60 / 200) & (lags < 60 / 50)
    if not ok.any():
        return None, 0.0
    lag = np.argmax(np.where(ok, ac, -1))
    bpm = 60 / (lag * step)
    while bpm < 70:
        bpm *= 2
    while bpm > 180:
        bpm /= 2
    return round(float(bpm)), round(float(max(0.0, ac[lag])), 2)


def energy_strip(levels, intro, title, out):
    w, h = 1200, 160
    img = Image.new("RGB", (w, h), (24, 24, 26))
    d = ImageDraw.Draw(img)
    d.text((8, 6), title, fill=(245, 245, 247))
    if len(levels):
        hi = float(np.max(levels)) + 1
        lo = max(-70.0, min(float(np.min(levels)), hi - 24) - 3)
        bar = w / len(levels)
        for i, v in enumerate(levels):
            top = 28 + (h - 36) * (1 - (max(lo, v) - lo) / (hi - lo))
            d.rectangle([i * bar, top, (i + 1) * bar - 1, h - 8], fill=(41, 151, 255))
        if intro is not None:
            x = intro / len(levels) * w
            d.line([x, 24, x, h], fill=(245, 245, 247), width=2)
    img.save(out)


def inspect_audio(path, info, args, sheets, kind):
    x = decode(path)
    length = float(info.get("format", {}).get("duration") or len(x) / SR)
    lufs, peak, lra = loudness(path)
    if not len(x):
        return {"kind": kind, "duration": round(length, 2), "flags": ["no sound decoded"]}
    if kind == "sfx":
        env = np.abs(x)
        top = int(np.argmax(env))
        ref = env[top] + 1e-9
        frame = int(SR * 0.01)
        rms = np.sqrt(np.convolve(x ** 2, np.ones(frame) / frame, mode="same"))
        after = np.where(rms[top:] > ref * 0.01)[0]
        tail = (after[-1] / SR) if len(after) else 0.0
        spec, freqs, _ = spectrum(x)
        centroid = float((spec * freqs).sum() / (spec.sum() + 1e-9))
        flags = []
        if top / SR > 0.25:
            flags.append(f"hits at {top / SR:.2f}s, not at its start: place it {top / SR:.2f}s before the moment")
        if args.slot and length > args.slot * 1.5:
            flags.append(f"long ({length:.1f}s) for a {args.slot}s moment: trim or fade it")
        return {"kind": "sfx", "duration": round(length, 2), "hit_at": round(top / SR, 2), "tail": round(tail, 2),
                "peak_dbfs": round(20 * math.log10(ref), 1), "lufs": lufs, "true_peak": peak, "centroid_hz": round(centroid), "flags": flags}
    spec, freqs, step = spectrum(x)
    logs = np.log1p(spec * 10)
    flux = np.concatenate([[0], np.maximum(0, np.diff(logs, axis=0)).sum(axis=1)])
    flux = np.maximum(flux - np.convolve(flux, np.ones(9) / 9, mode="same"), 0)
    bpm, sure = tempo(flux, step)
    threshold = flux.mean() + 2 * flux.std()
    peaks = np.where((flux[1:-1] > threshold) & (flux[1:-1] >= flux[:-2]) & (flux[1:-1] >= flux[2:]))[0]
    per_minute = round(len(peaks) / (len(x) / SR) * 60)
    second = int(SR)
    levels = np.array([10 * math.log10(float(np.mean(x[i:i + second] ** 2)) + 1e-10) for i in range(0, len(x) - second + 1, second)])
    full = float(np.percentile(levels, 75)) if len(levels) else -60
    reach = np.where(levels >= full - 8)[0]
    intro = int(reach[0]) if len(reach) else None
    tail_level = float(10 * math.log10(float(np.mean(x[-SR // 2:] ** 2)) + 1e-10))
    ending = "ends at full level (cut it on a beat or fade it)" if tail_level > full - 10 else "fades or rings out"
    centroid = float((spec * freqs).sum() / (spec.sum() + 1e-9))
    strip = sheets / f"{path.stem}.png"
    energy_strip(levels, intro, f"{path.name}  {length:.0f}s  about {bpm or '?'} BPM  intro {intro}s  (one bar a second, white line: full level)", strip)
    flags = []
    if sure < 0.25 and per_minute < 80:
        flags.append("no steady beat and few hits: a slow, sparse track (a solo piano, a pad or a drone); whether it carries the scene or reads empty, only listening tells")
    elif sure < 0.25:
        flags.append("no steady beat: cuts on the beat will not line up")
    if intro is not None and intro > 8:
        flags.append(f"takes {intro}s to reach full level: start it later or the opening feels empty")
    if args.slot and length < args.slot:
        flags.append(f"shorter ({length:.0f}s) than the {args.slot}s it must cover: loop it on a bar or pick another")
    if lra is not None and lra > 12:
        flags.append(f"wide loudness range ({lra} LU): quiet parts may vanish under speech, loud ones cover it")
    return {"kind": "music", "duration": round(length, 2), "lufs": lufs, "true_peak": peak, "loudness_range": lra,
            "bpm": bpm, "beat_sure": sure,
            "hits_per_min": per_minute, "intro_s": intro, "ending": ending, "brightness_hz": round(centroid),
            "energy_5s": [round(float(v), 1) for v in levels[::5]], "sheet": str(strip), "flags": flags}


# ---------------------------------------------------------------- across items

def across(results):
    notes = []
    seen = [(name, r["_hashes"]) for name, r in results.items() if r.get("_hashes")]
    for i, (a, ha) in enumerate(seen):
        for b, hb in seen[i + 1:]:
            close = sum(1 for x in ha for y in hb if bin(x ^ y).count("1") <= 6)
            if close >= min(2, len(ha), len(hb)):
                notes.append(f"{a} and {b} look like the same shot: a viewer notices a repeat")
    videos = {n: r for n, r in results.items() if r["kind"] in ("video", "photo") and r.get("brightness") is not None}
    if len(videos) >= 3:
        bright = np.array([r["brightness"] for r in videos.values()])
        warm = np.array([r["warmth"] for r in videos.values()])
        for (name, r), b, w in zip(videos.items(), bright, warm):
            if abs(b - np.median(bright)) > 55:
                notes.append(f"{name} is much {'brighter' if b > np.median(bright) else 'darker'} than the others ({b:.0f} vs {np.median(bright):.0f}): grade it or pick another")
            if abs(w - np.median(warm)) > 0.35:
                notes.append(f"{name} is much {'warmer' if w > np.median(warm) else 'cooler'} than the others: grade it or pick another")
    return notes


def summary(results, notes, args):
    lines = [f"# Assets measured (media-picker measure.py {VERSION})", ""]
    if args.target:
        lines.append(f"Target frame {args.target[0]}x{args.target[1]}" + (f", slot {args.slot}s" if args.slot else ""))
        lines.append("")
    for name, r in results.items():
        k = r["kind"]
        if k == "video":
            head = f"{r['width']}x{r['height']} {r['fps']}fps {r['duration']}s, shake {r['shake']}, pan {r['pan']}, cuts {len(r['cuts'])}, brightness {r['brightness']}, warmth {r['warmth']}"
            if r.get("crop_keep") is not None:
                head += f", crop keeps {int(r['crop_keep'] * 100)}% then x{r['upscale']}"
            if r.get("steadiest"):
                s = r["steadiest"]
                head += f", steadiest {s['start']}-{s['end']}s (shake {s['shake']})"
        elif k == "photo":
            head = f"{r['width']}x{r['height']}, brightness {r['brightness']}, warmth {r['warmth']}"
            if r.get("crop_keep") is not None:
                head += f", crop keeps {int(r['crop_keep'] * 100)}% then x{r['upscale']}"
        elif k == "music":
            head = (f"{r['duration']:.0f}s, {r['lufs']} LUFS, about {r['bpm']} BPM (beat sure {r['beat_sure']}), "
                    f"{r['hits_per_min']} hits/min, intro {r['intro_s']}s, {r['ending']}, brightness {r['brightness_hz']} Hz")
        else:
            head = f"{r['duration']}s, hits at {r.get('hit_at')}s, tail {r.get('tail')}s, peak {r.get('peak_dbfs')} dBFS"
        lines.append(f"- **{name}** ({k}): {head}")
        for flag in r.get("flags", []):
            lines.append(f"  - {flag}")
        if r.get("sheet"):
            lines.append(f"  - sheet: {r['sheet']}")
    if notes:
        lines += ["", "Across the picks:"] + [f"- {n}" for n in notes]
    lines += ["", "Measured only. Look at every sheet, and have the person listen to the music before it goes in."]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("items", nargs="+", help="files or http(s) links")
    parser.add_argument("--out", default="work/assets")
    parser.add_argument("--target", help="frame of the edit, such as 1080x1920")
    parser.add_argument("--slot", type=float, help="seconds the item must cover in the edit")
    parser.add_argument("--kind", choices=["video", "photo", "music", "sfx"])
    parser.add_argument("--version", action="version", version=VERSION)
    args = parser.parse_args()
    args.target = parse_size(args.target) if args.target else None
    out = Path(args.out)
    sheets = out / "sheets"
    sheets.mkdir(parents=True, exist_ok=True)
    results = {}
    for item in args.items:
        path = fetch(item, out / "files")
        info = probe(path)
        kind = args.kind or kind_of(path, info)
        if kind == "video":
            r = inspect_video(path, info, args, sheets)
        elif kind == "photo":
            r = inspect_photo(path, info, args, sheets)
        else:
            r = inspect_audio(path, info, args, sheets, kind)
        r["file"] = str(path)
        if item != str(path):
            r["source"] = item
        name = path.name
        while name in results:
            name = "_" + name
        results[name] = r
    notes = across(results)
    for r in results.values():
        r.pop("_hashes", None)
    (out / "assets.json").write_text(json.dumps({"version": VERSION, "target": args.target, "slot": args.slot,
                                                 "items": results, "across": notes}, indent=2), encoding="utf-8")
    text = summary(results, notes, args)
    (out / "summary.md").write_text(text, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(text)


if __name__ == "__main__":
    main()
