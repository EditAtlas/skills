#!/usr/bin/env python3
"""Fix loudness and true peak of a finished video in one go, picture copied untouched.

Single-pass loudnorm misses its peak target, and two-pass linear loudnorm cannot raise a quiet mix whose peaks
already clip. So: limit the peaks first, low enough to leave room for the gain the loudness needs, then run
two-pass linear loudnorm on the limited sound, then measure the result.

    python fix_sound.py in.mp4 out.mp4 [--loudness -14] [--peak -1.5]

Prints the loudness and true peak before and after. Never writes over the input.
"""
import argparse, json, re, subprocess, sys
from pathlib import Path

VERSION = "0.2.0"


def loudnorm(src, chain, target, peak):
    """Run loudnorm in measuring mode after `chain` and return its JSON."""
    af = f"{chain}loudnorm=I={target}:TP={peak}:LRA=11:print_format=json"
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-af", af, "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p.stderr)
    if not m:
        sys.exit(f"could not measure the sound of {src}: {p.stderr[-400:]}")
    return json.loads(m.group(0))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--loudness", type=float, default=-14.0, help="target LUFS (online -14, podcast -16, broadcast -23)")
    ap.add_argument("--peak", type=float, default=-1.5, help="true-peak target in dBTP; -1.5 leaves room for the AAC encode")
    ap.add_argument("--bitrate", default="192k")
    a = ap.parse_args()
    src, dst = Path(a.src), Path(a.dst)
    if src.resolve() == dst.resolve():
        sys.exit("write to a new file; the input is the first round's evidence")

    before = loudnorm(src, "", a.loudness, a.peak)
    if float(before["input_i"]) < -60:
        sys.exit(f"{src} is silent or nearly so ({before['input_i']} LUFS): there is no mix to fix")
    gain = a.loudness - float(before["input_i"])
    # Peaks must sit low enough that the gain loudnorm adds keeps them under the peak target, with 1 dB spare.
    # The limiter runs at 192 kHz so it catches peaks between samples too. If the encoded file still peaks
    # above the target, lower the ceiling by the overshoot and try again.
    ceiling_db = min(a.peak, a.peak - max(gain, 0.0) - 1.0)
    for attempt in range(4):
        limiter = (f"aresample=192000,alimiter=limit={10 ** (ceiling_db / 20):.4f}:level=disabled"
                   f":attack=1:release=50,aresample=48000,")
        m = loudnorm(src, limiter, a.loudness, a.peak)
        chain = (f"{limiter}loudnorm=I={a.loudness}:TP={a.peak}:LRA=11:measured_I={m['input_i']}"
                 f":measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
                 f":offset={m['target_offset']}:linear=true,aresample=48000")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-map", "0", "-c", "copy", "-c:a", "aac",
                        "-b:a", a.bitrate, "-af", chain, "-movflags", "+faststart", str(dst)], check=True)
        after = loudnorm(dst, "", a.loudness, a.peak)
        over = float(after["input_tp"]) - a.peak
        if over <= 0.05:
            break
        ceiling_db -= over + 0.5
    print(f"fix_sound {VERSION}: limiter ceiling {ceiling_db:.1f} dBFS (try {attempt + 1}), then two-pass loudnorm to {a.loudness} LUFS")
    print(f"before: {float(before['input_i']):.1f} LUFS, true peak {float(before['input_tp']):+.1f} dBTP")
    print(f"after:  {float(after['input_i']):.1f} LUFS, true peak {float(after['input_tp']):+.1f} dBTP")
    if over > 0.05:
        print(f"still {over:.1f} dB above the peak target after {attempt + 1} tries: lower the music or the loudest"
              " sound in the mix and render again")
    if ceiling_db < a.peak - max(gain, 0.0) - 4.0:
        print("the limiter had to work hard: listen for pumping or dulled hits before you deliver")
    print("Run check.py on the new file with --before to confirm; nobody has listened to it yet.")


if __name__ == "__main__":
    main()
