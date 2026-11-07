"""Measure a rendered sound design and say where it is weak. Claude cannot hear: these numbers and the listen
list are the ears. Run it after every mix.py and fix what it flags before showing the result.

  check.py result/film_sfx_resolved.json [--moments work/moments/moments.json] [--listen-out result/listen.wav]

Exit code 0: nothing flagged. 1: something to fix or to ask the person about.
"""
import argparse
import json
import re
from pathlib import Path

import numpy as np

from common import SR, db, decode, die, envelope, lufs, utf8_stdout, window_db, write_json

HEAVY = {"hit", "impact", "boom"}


def events(cues, merge=0.08):
    ts = sorted(c["lands_at"] for c in cues if not c.get("bed"))
    out = []
    for t in ts:
        if not out or t - out[-1] > merge:
            out.append(t)
    return out


def sync_errors(track, cues):
    """Find each sound in the rendered track by matching its own waveform (neighbours do not fool this), and
    compare where its anchor really is with where the cue asked for it. Milliseconds, + = late."""
    mono = track.mean(axis=1)
    errs = []
    for c in cues:
        if c.get("bed") or not c.get("path"):
            continue
        solo = decode(c["path"], channels=1, start=c.get("offset_in") or None)[:, 0]
        if c.get("len_s"):
            solo = solo[: int(c["len_s"] * SR)]
        if len(solo) < 64 or np.abs(solo).max() == 0:
            errs.append((c, None))
            continue
        # match the LOUDEST 0.3 s of the sound: a whoosh that starts very quietly is otherwise lost under a
        # louder neighbour, and the match lands on the neighbour instead
        env = envelope(solo, hop=0.005)
        pk = int(env.argmax() * 0.005 * SR)
        s0 = max(0, pk - int(0.15 * SR))
        probe_ = solo[s0: s0 + int(0.3 * SR)]
        want = c["placed_at"] + s0 / SR                      # where that piece should start in the track
        i0 = int(max(0.0, want - 0.2) * SR)
        win = mono[i0: i0 + int(0.4 * SR) + len(probe_)]
        if len(probe_) < 64 or len(win) <= len(probe_):
            errs.append((c, None))
            continue
        n = 1 << int(np.ceil(np.log2(len(win) + len(probe_))))
        corr = np.fft.irfft(np.fft.rfft(win, n) * np.conj(np.fft.rfft(probe_, n)), n)[: len(win) - len(probe_) + 1]
        # normalise by the window's own energy so a loud neighbour cannot win on level alone
        cs = np.concatenate([[0.0], np.cumsum(win.astype(np.float64) ** 2)])
        energy = np.sqrt(np.maximum(cs[len(probe_):len(probe_) + len(corr)] - cs[:len(corr)], 0))
        energy = np.maximum(energy, 0.25 * energy.max() + 1e-9)   # silence must not win by dividing by ~0
        found = (i0 + int(np.argmax(corr / energy))) / SR
        anchor_at = found - s0 / SR + c.get("lead_s", 0)
        errs.append((c, round((anchor_at - c["t"]) * 1000)))
    return errs


def main():
    utf8_stdout()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("resolved")
    p.add_argument("--moments")
    p.add_argument("--listen-out")
    p.add_argument("--sfx-only", action="store_true", help="the film has no music or voice of its own")
    a = p.parse_args()
    R = json.loads(Path(a.resolved).read_text(encoding="utf-8"))
    stem = str(Path(a.resolved)).replace("_resolved.json", "")
    for need in ("_track_nobed.wav", "_track.wav"):
        if not Path(stem + need).is_file():
            die(f"{Path(stem + need).name} is missing next to {Path(a.resolved).name}: keep mix.py's outputs together")
    track = decode(stem + "_track_nobed.wav")
    full = decode(stem + "_track.wav")
    cues = R["cues"]
    dur = R["duration"]
    sfx_only = a.sfx_only or not R.get("keep_audio", True)
    voice = not sfx_only and R.get("under_voice", False)
    # what the film's own audio carries decides how dense the sounds should be and how long a quiet stretch may last
    kind = "with SFX only" if sfx_only else ("carried by a voice" if voice else "with its own music")
    lo, hi, hole = (7.0, 15.0, 3.0) if sfx_only else ((1.5, 8.0, 8.0) if voice else (3.0, 12.0, 5.0))
    flags, lines = [], []

    ev = events(cues)
    gaps = np.diff([0.0] + ev + [dur]) if ev else np.array([dur])
    per10 = len(ev) / dur * 10 if dur else 0
    lines.append(f"gestures: {len(ev)} in {dur:.1f}s = {per10:.1f} per 10 s; median gap {np.median(np.diff(ev)) if len(ev) > 1 else 0:.2f}s; "
                 f"longest hole {gaps.max():.2f}s")
    if not ev:
        flags.append("no sounds placed")
    else:
        if ev[0] > 2.0 and sfx_only:
            flags.append(f"hook: first sound at {ev[0]:.2f}s; a film wants a sound in its first 2 s (or its own music/voice)")
        if per10 < lo:
            flags.append(f"pace: {per10:.1f} gestures per 10 s, under {lo} for a film {kind}")
        if per10 > hi:
            flags.append(f"pace: {per10:.1f} gestures per 10 s, over {hi} for a film {kind}: busy; drop the weakest")
        if gaps.max() > hole:
            i = int(gaps.argmax())
            start = ([0.0] + ev)[i]
            flags.append(f"hole: {gaps.max():.2f}s without a sound from {start:.2f}s (fill it or say why it is quiet)")
    heavy = [c for c in cues if c.get("role") in HEAVY]
    if ev and len(heavy) > max(2, len(ev) / 3):
        flags.append(f"weight: {len(heavy)} heavy hits of {len(ev)} gestures; keep them to about a third")
    ids = [c["id"] for c in cues if not c.get("bed")]
    reps = {i: ids.count(i) for i in set(ids) if ids.count(i) > 2}
    for i, k in reps.items():
        flags.append(f"repeat: {i} used {k} times; alternate takes of the same family")
    errs = sync_errors(track, cues)
    bad = [(c, e) for c, e in errs if e is not None and abs(e) > 1000 / 30]
    lines.append("sync: " + (", ".join(f"{c['t']:.2f}s {e:+d}ms" for c, e in errs if e is not None) or "-"))
    for c, e in bad:
        flags.append(f"sync: {c['title']} at {c['t']:.2f}s lands {e:+d} ms off (more than a frame)")
    for c, e in errs:
        if e is None:
            flags.append(f"lost: nothing audible near {c['t']:.2f}s ({c['title']})")
    for c in cues:
        m = c.get("measured") or {}
        if c.get("anchor") == "start" and m.get("attack_s", 0) > 0.06 and not c.get("offset_in"):
            lines.append(f"note: {c['title']} at {c['t']:.2f}s swells for {int(m['attack_s'] * 1000)} ms before its peak; "
                         "if its peak is the moment, use anchor peak")
        if m.get("audible_s", 0) > 0 and c.get("len_s") and m["audible_s"] - m.get("audible_start_s", 0) > c["len_s"] + 0.05 and c["len_s"] < 0.15:
            flags.append(f"cut short: {c['title']} plays {c['len_s']}s of {m['audible_s']}s")

    w = window_db(full.mean(axis=1))
    if len(w):
        silent = float((w < -70).mean())
        q10 = float(np.percentile(w, 10))
        lines.append(f"sfx track: loudest 250 ms {w.max():.1f} dBFS, quietest tenth {q10:.1f} dBFS, digital silence {silent:.0%}")
        if sfx_only and silent > 0.1:
            flags.append(f"silence: {silent:.0%} of the film is digital silence; an SFX-only film sounds bare without a bed")
    out_mp4 = R.get("out")
    if out_mp4 and not Path(out_mp4).is_file() and Path(stem + ".mp4").is_file():
        out_mp4 = stem + ".mp4"                                      # the folder was moved after mix.py
    if out_mp4 and Path(out_mp4).is_file():
        I, TP = lufs(out_mp4)
        lines.append(f"master: {I} LUFS integrated, true peak {TP} dBFS")
        if TP is not None and TP > -0.5:
            flags.append(f"clip risk: true peak {TP} dBFS")
        if I is not None and (I < -24 or I > -9):
            flags.append(f"loudness: {I} LUFS; social video sits near -14 (film_gain_db / gain_db)")
        mix = decode(out_mp4)
        if len(mix):
            st = db(np.sqrt((mix ** 2).mean()))
            mo = db(np.sqrt((mix.mean(axis=1) ** 2).mean()))
            lines.append(f"mono fold: {mo - st:+.1f} dB")
            if mo - st < -3:
                flags.append(f"mono: the mix loses {mo - st:.1f} dB on one speaker")
    if a.moments:
        M = json.loads(Path(a.moments).read_text(encoding="utf-8"))["moments"]
        strong = [m for m in M if m["kind"] == "cut" or m.get("strength", 0) >= 0.6]
        # a whoosh lands on the arrival, after the motion peak, so a sound within 0.35 s covers the moment
        quiet = [m for m in strong if all(abs(m["t"] - t) > 0.35 for t in ev)]
        lines.append(f"coverage: {len(strong) - len(quiet)} of {len(strong)} strong picture moments have a sound")
        if strong and len(quiet) / len(strong) > 0.5:
            flags.append("coverage: quiet strong moments at " + ", ".join(f"{m['t']:.2f}s {m['kind']}" for m in quiet[:8]))

    # five places a person should listen to: the loudest overlaps, the first sound, the biggest gap's edge
    picks = []
    if ev:
        picks.append(("first sound", ev[0]))
        env = envelope(track.mean(axis=1), hop=0.25)
        for i in np.argsort(env)[::-1]:
            t = i * 0.25
            if all(abs(t - q) > 1.5 for _, q in picks):
                picks.append(("loudest", t))
            if len(picks) >= 3:
                break
        dense = max(ev, key=lambda t: sum(1 for u in ev if abs(u - t) < 1.0))
        if all(abs(dense - q) > 1.5 for _, q in picks):
            picks.append(("densest", dense))
        if gaps.max() > 1.5:
            i = int(gaps.argmax())
            edge = ([0.0] + ev)[i]
            if all(abs(edge - q) > 1.5 for _, q in picks):
                picks.append(("before the longest hole", edge))
    lines.append("listen to: " + "; ".join(f"{t:.2f}s ({why})" for why, t in picks[:5]))
    if a.listen_out and picks and out_mp4 and Path(out_mp4).is_file():
        mix = decode(out_mp4)
        parts = []
        for _, t in picks[:5]:
            i0, i1 = int(max(0, t - 1.0) * SR), int(min(dur, t + 1.5) * SR)
            parts += [mix[i0:i1], np.zeros((int(0.6 * SR), 2), np.float32)]
        from mix import write_wav
        write_wav(a.listen_out, np.concatenate(parts))
        lines.append(f"listen file: {a.listen_out}")
    report = {"flags": flags, "lines": lines, "listen": [{"why": w_, "t": round(t, 2)} for w_, t in picks[:5]]}
    write_json(stem + "_check.json", report)
    for l in lines:
        print(l)
    print("\n" + ("FLAGS:\n- " + "\n- ".join(flags) if flags else "nothing flagged by the numbers (still listen)"))
    raise SystemExit(1 if flags else 0)


if __name__ == "__main__":
    main()
