#!/usr/bin/env python3
"""Find the beat of a music track: tempo, the first beat, every beat, a guess at bar starts, and frame numbers.

    python beat_grid.py music.mp3 [--fps 30] [--out work/beats.json] [--bpm 120] [--beats-per-bar 4]

Prints the tempo, the first beat and how sure the grid is, and writes the JSON. With --fps every beat also gets
its frame number at that rate, ready for cuts, titles or sounds. --bpm skips the tempo search when you know it.

How: a spectral-flux onset curve, its autocorrelation for tempo candidates folded into 70-180 BPM, then a search
of tempo (within 3 %) and phase that puts the beats on onsets, each beat snapped to its onset. Bar starts are the
beat in each group of beats-per-bar with the most low-end onset energy (the kick): a guess, so listen to the first
two bars before cutting on them. The same method as video-breakdown's analyze.py, measured there on real shorts.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

VERSION = "0.1.0"
SR = 22050
HOP = 256
FT = HOP / SR
WINDOW = 1024
# A frame of the onset curve starts its window at i * HOP; the onset it marks sits about half a window later.
CENTER = WINDOW / 2 / SR


def decode(path):
    """Mono float32 samples at SR; empty when the file has no audio."""
    try:
        done = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-vn", "-ac", "1", "-ar", str(SR),
                               "-f", "f32le", "-"], capture_output=True)
    except FileNotFoundError:
        sys.exit("beat_grid: FFmpeg is not installed or not in PATH")
    if done.returncode:
        sys.exit(f"beat_grid: FFmpeg could not read {path}: {done.stderr.decode(errors='replace')[-300:]}")
    return np.frombuffer(done.stdout, np.float32).copy()


def onsets(x):
    """Onset curve over all frequencies, and one over the low end (under 200 Hz) for the kick."""
    n = WINDOW
    k = 1 + (len(x) - n) // HOP
    idx = np.arange(n)[None, :] + HOP * np.arange(k)[:, None]
    spec = np.abs(np.fft.rfft(x[idx] * np.hanning(n).astype(np.float32), axis=1)).astype(np.float32)
    logs = np.log1p(spec * 10)
    freqs = np.fft.rfftfreq(n, 1 / SR)

    def flux(cols):
        f = np.concatenate([[0], np.maximum(0, np.diff(logs[:, cols], axis=0)).sum(axis=1)])
        return np.maximum(f - np.convolve(f, np.ones(9) / 9, mode="same"), 0)

    return flux(slice(None)), flux(freqs < 200)


def candidates(env):
    """Up to three tempi from the autocorrelation of the onset curve, strongest first, as (bpm, strength)."""
    e = env - env.mean()
    ac = np.correlate(e, e, mode="full")[len(e) - 1:]
    ac /= ac[0] + 1e-9
    lo, hi = int(60 / 200 / FT), int(60 / 60 / FT) + 1
    peaks = [L for L in range(max(2, lo), min(hi, len(ac) - 1)) if ac[L] >= ac[L - 1] and ac[L] >= ac[L + 1] and ac[L] > 0.05]
    found = []
    for L in sorted(peaks, key=lambda L: -ac[L]):
        bpm = 60 / (L * FT)
        while bpm < 70:
            bpm *= 2
        while bpm > 180:
            bpm /= 2
        if all(abs(bpm - b) / b > 0.04 for b, _ in found):
            found.append((bpm, float(ac[L])))
        if len(found) == 3:
            break
    return found


def grid(env, bpm):
    """Refine the tempo (within 3 %) and phase so the beats sit on onsets, then snap each beat to its onset."""
    envs = np.maximum.reduce([np.roll(env, k) for k in (-2, -1, 0, 1, 2)])
    med = float(np.median(env[env > 0])) + 1e-9 if (env > 0).any() else 1.0
    le = np.log1p(envs / med)
    best = (-1.0, bpm, 0.0)
    for b in np.arange(bpm * 0.97, bpm * 1.03, 0.1):
        period = 60 / b / FT
        for ph in np.arange(0, period, 1.0):
            idx = np.round(np.arange(ph, len(env), period)).astype(int)
            idx = idx[idx < len(env)]
            v = float(le[idx].mean())
            if v > best[0]:
                best = (v, b, ph)
    _, bpm, phase = best
    period = 60 / bpm / FT
    beats = []
    for x in np.arange(phase, len(env), period):
        i = int(round(x))
        lo, hi = max(0, i - 2), min(len(env), i + 3)
        if hi > lo:
            beats.append((lo + int(np.argmax(env[lo:hi]))) * FT + CENTER)
    # The grid reaches back to the start of the file; drop the beats before the music starts playing.
    strength = np.array([env[min(len(env) - 1, int(round((t - CENTER) / FT)))] for t in beats])
    if len(strength):
        floor = 0.25 * float(np.median(strength))
        first = next((k for k, v in enumerate(strength) if v > floor), 0)
        beats = beats[first:]
    return float(bpm), beats


def bar_starts(beats, low, per_bar):
    """The beat in each bar that carries the most low-end onset energy, as an offset 0..per_bar-1, and its share."""
    if len(beats) < per_bar * 2:
        return 0, None
    energy = np.array([low[min(len(low) - 1, int(round((t - CENTER) / FT)))] for t in beats])
    sums = [float(energy[k::per_bar].mean()) for k in range(per_bar)]
    k = int(np.argmax(sums))
    return k, round(sums[k] / (sum(sums) + 1e-9), 2)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("music", help="an audio file, or a video whose sound is the music")
    ap.add_argument("--fps", type=float, help="also give each beat its frame number at this frame rate")
    ap.add_argument("--out", help="where to write the JSON (default: next to the music, NAME.beats.json)")
    ap.add_argument("--bpm", type=float, help="the tempo, when you know it: skips the tempo search")
    ap.add_argument("--beats-per-bar", type=int, default=4)
    a = ap.parse_args()
    src = Path(a.music)
    x = decode(src)
    if len(x) < SR * 4:
        sys.exit(f"beat_grid: {src} has under 4 seconds of sound; a beat needs more")
    env, low = onsets(x)
    found = [(a.bpm, None)] if a.bpm else candidates(env)
    if not found:
        sys.exit(f"beat_grid: no steady beat found in {src}; cut to phrases or to the picture instead")
    bpm, strength = found[0]
    bpm, beats = grid(env, bpm)
    offset, bar_share = bar_starts(beats, low, a.beats_per_bar)
    bars = beats[offset::a.beats_per_bar]
    result = {
        "version": VERSION, "music": str(src), "duration_s": round(len(x) / SR, 3),
        "bpm": round(bpm, 2), "beat_s": round(60 / bpm, 4), "first_beat_s": round(beats[0], 3) if beats else None,
        "beat_strength": None if strength is None else round(strength, 2),
        "steady": strength is None or strength >= 0.12,
        "other_tempi": [{"bpm": round(b, 1), "strength": round(s, 2)} for b, s in found[1:]],
        "beats_per_bar": a.beats_per_bar, "bar_start_offset": offset, "bar_start_share": bar_share,
        "beats": [round(t, 3) for t in beats], "bar_starts": [round(t, 3) for t in bars],
    }
    if a.fps:
        result["fps"] = a.fps
        result["beat_frames"] = [int(round(t * a.fps)) for t in beats]
        result["bar_start_frames"] = [int(round(t * a.fps)) for t in bars]
    out = Path(a.out) if a.out else src.with_name(src.stem + ".beats.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    sure = "steady" if result["steady"] else "weak: check by ear before cutting on it"
    print(f"beat_grid {VERSION}: {result['bpm']} BPM ({sure}), first beat at {result['first_beat_s']} s, {len(beats)} beats")
    if result["other_tempi"]:
        print("other tempi it could be: " + ", ".join(f"{t['bpm']} BPM" for t in result["other_tempi"]))
    print(f"bar starts (a guess from the kick, {a.beats_per_bar} beats a bar): beat {offset + 1} of each bar, first at "
          f"{result['bar_starts'][0] if bars else '-'} s. Listen to the first two bars before cutting on them.")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
