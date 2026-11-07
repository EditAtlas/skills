"""Shared helpers: ffmpeg calls, audio decoding, the EditAtlas sound index and its cache."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import numpy as np

SR = 48000
INDEX_URL = "https://raw.githubusercontent.com/ptrgiang/EditAtlas-SFX/main/index.json"
USER_AGENT = "sound-design-skill/0.2"

# Peak level (dBFS) a sound of each role is set to before the cue's own gain_db.
# Loud, short accents sit high; textures and beds sit low so they never cover the accents.
ROLE_PEAK_DB = {
    "hit": -6, "impact": -6, "boom": -6, "whoosh": -12, "riser": -14, "glitch": -14, "ui": -16, "click": -16,
    "pop": -16, "chime": -15, "bell": -15, "typing": -18, "foley": -14, "paper": -15, "cartoon": -13,
    "magic": -15, "scifi": -14, "nature": -24, "ambience": -28, "voice": -10, "music": -16, "default": -12,
}
# Where in the sound the picture's moment lands. "start": the audible start (clicks, taps, typing, beds);
# "peak": the loudest point (hits, whooshes). Risers usually want "end" (their peak or tail lands on the moment).
ROLE_ANCHOR = {"ui": "start", "click": "start", "pop": "start", "typing": "start", "ambience": "start",
               "nature": "start", "chime": "start", "bell": "start", "riser": "end"}


def die(msg):
    sys.exit("sound-design: " + msg)


def need(tool):
    if not shutil.which(tool):
        die(f"{tool} not found in PATH. Install FFmpeg (it ships ffprobe) and open a new terminal.")


def run(cmd, **kw):
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", **kw)


def probe(path):
    need("ffprobe")
    r = run(["ffprobe", "-v", "error", "-show_entries",
             "format=duration:stream=codec_type,width,height,r_frame_rate,channels,sample_rate",
             "-of", "json", path])
    if r.returncode:
        die(f"cannot read {path}: {r.stderr.strip()[:300]}")
    d = json.loads(r.stdout)
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), None)
    fps = 30.0
    if v and v.get("r_frame_rate", "0/0") != "0/0":
        n, m = v["r_frame_rate"].split("/")
        fps = float(n) / float(m or 1)
    return {"duration": float(d.get("format", {}).get("duration") or 0), "fps": fps,
            "width": v and v.get("width"), "height": v and v.get("height"), "has_video": v is not None,
            "has_audio": a is not None}


def decode(path, channels=2, sr=SR, start=None, dur=None):
    """Audio as float32 array (samples, channels). Empty array when the file has no audio."""
    need("ffmpeg")
    cmd = ["ffmpeg", "-v", "error", "-nostdin"]
    if start is not None:
        cmd += ["-ss", f"{start:.4f}"]
    if dur is not None:
        cmd += ["-t", f"{dur:.4f}"]
    cmd += ["-i", str(path), "-vn", "-ac", str(channels), "-ar", str(sr), "-f", "f32le", "-"]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode and not r.stdout:
        return np.zeros((0, channels), np.float32)
    return np.frombuffer(r.stdout, np.float32).reshape(-1, channels).copy()


def db(x):
    return 20 * np.log10(max(float(x), 1e-9))


def window_db(mono, sr=SR, win=0.25):
    """RMS level in dBFS of consecutive windows."""
    n = int(sr * win)
    k = len(mono) // n
    if k == 0:
        return np.array([])
    w = mono[: k * n].reshape(k, n)
    return 20 * np.log10(np.sqrt((w ** 2).mean(axis=1)) + 1e-9)


def envelope(mono, sr=SR, hop=0.005):
    n = max(1, int(sr * hop))
    k = len(mono) // n
    if k == 0:
        return np.array([0.0])
    return np.abs(mono[: k * n]).reshape(k, n).max(axis=1)


def measure(path):
    """Numbers that let you choose a sound without hearing it."""
    x = decode(path)
    if len(x) == 0:
        return None
    mono = x.mean(axis=1)
    env = envelope(mono)
    hop = 0.005
    peak = float(env.max()) or 1e-9
    above40 = np.nonzero(env > peak * 10 ** (-40 / 20))[0]
    above50 = np.nonzero(env > peak * 10 ** (-50 / 20))[0]
    start = float(above40[0] * hop) if len(above40) else 0.0
    end = float((above50[-1] + 1) * hop) if len(above50) else len(mono) / SR
    peak_t = float(env.argmax() * hop)
    # attack: time from audible start to 90 % of the peak
    a90 = np.nonzero(env >= 0.9 * peak)[0]
    attack = float(a90[0] * hop - start) if len(a90) else 0.0
    # channels that cancel each other vanish on a phone speaker
    l, r = x[:, 0], x[:, 1]
    corr = float(np.corrcoef(l, r)[0, 1]) if l.std() > 1e-6 and r.std() > 1e-6 else 1.0
    mono_loss = db(np.sqrt((mono ** 2).mean())) - db(np.sqrt(((l ** 2 + r ** 2) / 2).mean()))
    spec = np.abs(np.fft.rfft(mono[: min(len(mono), SR * 4)] * np.hanning(min(len(mono), SR * 4))))
    freqs = np.fft.rfftfreq(min(len(mono), SR * 4), 1 / SR)
    centroid = float((spec * freqs).sum() / (spec.sum() + 1e-9))
    return {"file_s": round(len(mono) / SR, 3), "audible_start_s": round(start, 3),
            "audible_end_s": round(end, 3), "audible_s": round(end - start, 3), "peak_t_s": round(peak_t, 3),
            "peak_dbfs": round(db(peak), 1), "attack_s": round(max(attack, 0.0), 3),
            "centroid_hz": int(centroid), "lr_corr": round(corr, 2), "mono_loss_db": round(mono_loss, 1)}


# ------------------------------------------------------------------ the EditAtlas index and cache
def cache_dir(arg=None):
    p = Path(arg or os.environ.get("EDITATLAS_SFX_CACHE") or Path.home() / ".cache" / "editatlas-sfx")
    p.mkdir(parents=True, exist_ok=True)
    return p


def _get(url, dst):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    tmp = Path(str(dst) + ".part")
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    tmp.replace(dst)


def load_index(cache=None, mirror=None, refresh=False):
    """The public sound index: from a local EditAtlas-SFX checkout (--mirror / EDITATLAS_SFX_MIRROR) or GitHub."""
    mirror = mirror or os.environ.get("EDITATLAS_SFX_MIRROR")
    if mirror:
        f = Path(mirror) / "index.json"
        if not f.is_file():
            die(f"no index.json in {mirror}")
        return json.loads(f.read_text(encoding="utf-8")), Path(mirror)
    c = cache_dir(cache)
    f = c / "index.json"
    if refresh or not f.is_file():
        try:
            _get(INDEX_URL, f)
        except OSError as e:
            if not f.is_file():
                die(f"cannot download the sound index ({e}). Clone https://github.com/ptrgiang/EditAtlas-SFX "
                    "and pass --mirror PATH.")
    return json.loads(f.read_text(encoding="utf-8")), None


def by_id(index):
    return {s["id"]: s for s in index["sounds"]}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(sound, cache=None, mirror=None):
    """Local path of a sound, downloaded once and checked against its SHA-256."""
    if mirror:
        p = Path(mirror) / sound["path"]
        if p.is_file():
            return p
    c = cache_dir(cache) / "files"
    dst = c / sound["path"]
    if dst.is_file() and dst.stat().st_size == sound.get("bytes", dst.stat().st_size):
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    _get(sound["url"], dst)
    got = sha256(dst)
    if sound.get("sha256") and got != sound["sha256"]:
        dst.unlink()
        die(f"{sound['id']}: SHA-256 mismatch after download ({got[:12]} != {sound['sha256'][:12]})")
    return dst


def measured(sound, cache=None, mirror=None):
    """measure() of a sound, cached next to the files."""
    c = cache_dir(cache)
    mf = c / "measure.json"
    table = json.loads(mf.read_text(encoding="utf-8")) if mf.is_file() else {}
    key = sound["id"] + ":" + (sound.get("sha256") or "")[:16]
    if key not in table:
        path = fetch(sound, cache, mirror)
        table[key] = measure(path)
        mf.write_text(json.dumps(table, indent=0), encoding="utf-8")
    return table[key]


def lufs(path):
    """(integrated LUFS, true peak dBFS) of a media file's first audio stream, by ffmpeg's EBU R128 meter."""
    import re
    r = run(["ffmpeg", "-v", "info", "-nostdin", "-i", path, "-map", "0:a:0", "-af",
             "ebur128=framelog=quiet:peak=true", "-f", "null", "-"])
    i = re.findall(r"I:\s+(-?[0-9.]+) LUFS", r.stderr)
    tp = re.findall(r"Peak:\s+(-?[0-9.]+) dBFS", r.stderr)
    return (float(i[-1]) if i else None), (float(tp[-1]) if tp else None)


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def utf8_stdout():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
