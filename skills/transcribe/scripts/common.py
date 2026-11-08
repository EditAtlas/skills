"""Shared helpers: FFmpeg calls, audio decoding, loudness envelopes, JSON and time formats."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

SR = 16000          # Whisper hears 16 kHz mono
HOP = 0.01          # envelope step in seconds


def die(msg):
    sys.exit("transcribe: " + msg)


def utf8_stdout():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def need(tool):
    if not shutil.which(tool):
        die(f"{tool} not found in PATH. Install FFmpeg (it ships ffprobe) and open a new terminal.")


def run(cmd, **kw):
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)


def probe(path):
    need("ffprobe")
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,channels",
             "-of", "json", path])
    if r.returncode:
        die(f"cannot read {path}: {r.stderr.strip()[:300]}")
    d = json.loads(r.stdout)
    streams = d.get("streams", [])
    return {"duration": float(d.get("format", {}).get("duration") or 0),
            "has_audio": any(s.get("codec_type") == "audio" for s in streams),
            "has_video": any(s.get("codec_type") == "video" for s in streams)}


def decode(path, sr=SR):
    """First audio stream as mono float32 at sr. Times match the file's own timeline from 0."""
    need("ffmpeg")
    r = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-map", "0:a:0", "-vn", "-ac", "1",
                        "-ar", str(sr), "-f", "f32le", "-"], capture_output=True)
    if r.returncode and not r.stdout:
        return np.zeros(0, np.float32)
    return np.frombuffer(r.stdout, np.float32).copy()


def envelope_db(x, sr=SR, hop=HOP):
    """RMS level in dBFS every hop seconds (window 2 hops)."""
    h = int(sr * hop)
    if len(x) < h:
        return np.zeros(0)
    n = len(x) // h
    frames = x[: n * h].reshape(n, h).astype(np.float64)
    rms = np.sqrt((frames ** 2).mean(axis=1))
    rms = np.maximum(rms, np.concatenate([rms[1:], rms[-1:]]))      # a touch of look-ahead so word onsets count
    return 20 * np.log10(np.maximum(rms, 1e-7))


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        die(f"{path} not found")


def ts(t, sep=","):
    """Seconds to 00:00:00,000 (SRT) or 00:00:00.000 (VTT)."""
    ms = max(0, int(round(t * 1000)))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def clock(t):
    """Seconds to m:ss.s for reports a person reads."""
    m, s = divmod(max(0.0, t), 60)
    return f"{int(m)}:{s:04.1f}"
