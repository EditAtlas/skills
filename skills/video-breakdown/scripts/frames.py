"""Draw frames of a video so you can look closely: around one time, at chosen times, or a part of the frame.

  frames.py VIDEO --at 3.2 --out work/look                    # 12 frames, 0.1 s apart, centred on 3.2 s
  frames.py VIDEO --at 3.2 --span 0.5 --step 0.04 --out work/look   # every frame of a fast join (25 fps)
  frames.py VIDEO --times 1.0,4.5,9.2 --out work/look         # just these times
  frames.py VIDEO --at 7.4 --crop 0,60,100,40 --out work/look # bottom 40 % only, larger: read captions

--crop takes x,y,w,h in percent of the frame. Open the PNG with the Read tool.
"""
import argparse
from pathlib import Path

import numpy as np

from common import die, frame_size, grab, probe, sheet, utf8_stdout


def main():
    utf8_stdout()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("video")
    p.add_argument("--out", required=True, help="folder")
    p.add_argument("--at", type=float, help="centre time in seconds")
    p.add_argument("--span", type=float, default=1.2, help="seconds around --at (default 1.2)")
    p.add_argument("--step", type=float, default=0.1, help="seconds between frames (default 0.1)")
    p.add_argument("--times", help="comma-separated times in seconds, instead of --at")
    p.add_argument("--crop", help="x,y,w,h in percent of the frame")
    p.add_argument("--width", type=int, default=0, help="tile width in pixels (default: 200 portrait, 320 landscape)")
    p.add_argument("--cols", type=int, default=6)
    a = p.parse_args()
    info = probe(a.video)
    if a.times:
        try:
            ts = [float(x) for x in a.times.split(",") if x.strip()]
        except ValueError:
            die("--times takes numbers separated by commas, such as 1.0,4.5")
    elif a.at is not None:
        ts = [float(t) for t in np.arange(a.at - a.span / 2, a.at + a.span / 2 + 1e-6, a.step)]
    else:
        die("give --at SECONDS or --times T1,T2,...")
    ts = [t for t in ts if 0 <= t <= info["duration"] + 1e-3]
    if not ts:
        die(f"no times inside the video (it is {info['duration']:.2f} s long)")
    if len(ts) > 48:
        die(f"{len(ts)} frames is too many for one sheet; use a larger --step or a shorter --span")
    portrait = (info["height"] or 0) > (info["width"] or 1)
    width = a.width or (200 if portrait else 320)
    crop = None
    if a.crop:
        try:
            crop = [float(x) / 100 for x in a.crop.split(",")]
            assert len(crop) == 4 and crop[2] > 0 and crop[3] > 0
        except (ValueError, AssertionError):
            die("--crop takes x,y,w,h in percent, such as 0,60,100,40")
        width = int(width / max(crop[2], 0.2))  # grab larger, then cut, so the crop stays sharp
    tiles = grab(a.video, ts, width, info)
    if crop:
        w, h = frame_size(info, width)
        x0, y0 = int(crop[0] * w), int(crop[1] * h)
        x1, y1 = min(w, x0 + int(crop[2] * w)), min(h, y0 + int(crop[3] * h))
        tiles = [t[y0:y1, x0:x1] if t is not None else None for t in tiles]
    out = Path(a.out)
    name = f"at_{a.at:.2f}" if a.at is not None and not a.times else "times"
    if crop:
        name += "_crop"
    path = sheet(tiles, [f"{t:.2f}s" for t in ts], out / f"{name}.png", a.cols)
    if not path:
        die("could not draw the sheet: pip install pillow, and check that FFmpeg can read the video")
    print("->", path)


if __name__ == "__main__":
    main()
