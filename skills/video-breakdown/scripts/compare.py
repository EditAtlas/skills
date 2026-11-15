"""Compare a remake with its reference: timing (length, cuts, when things move and for how long) and look (brightness,
contrast, colour, detail, the size and place of the main graphics) at matching moments.

  compare.py REFERENCE.mp4 REMAKE.mp4 --out work/compare
  compare.py REFERENCE.mp4 REMAKE.mp4 --region 10,20,80,15 --out work/compare     # also the content of one area
  compare.py REFERENCE.mp4 REMAKE.mp4 --offset 0.4 --out work/compare             # the remake starts 0.4 s later

Times are matched second for second (plus --offset). Prints the differences that are large enough to see, in order
of size, and writes compare.png (reference and remake side by side at each moment, with the numbers) and
compare.json. A difference here is a measurement, not a verdict: look at the pairs, and keep what the person changed
on purpose.
"""
import argparse
import json
import math
import re
import subprocess
from pathlib import Path

import numpy as np

from common import die, grab, need, probe, utf8_stdout

SMALL = 160  # px wide for timing


def low_frames(video, info, fps=10):
    need("ffmpeg")
    w = SMALL
    h = max(2, int(round(w * (info["height"] or 9) / (info["width"] or 16) / 2) * 2))
    raw = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(video), "-an", "-vf",
                          f"fps={fps},scale={w}:{h}:flags=area,format=rgb24", "-f", "rawvideo", "-"], capture_output=True).stdout
    n = len(raw) // (w * h * 3)
    return np.frombuffer(raw[: n * w * h * 3], np.uint8).reshape(n, h, w, 3).astype(np.float32)


def row_entrances(video, info, cuts, fps=30, width=120, limit=30.0):
    """When each row of text or shapes comes in, per shot: rows are read on the shot's last still frame; a row is
    in once its band holds a third of its final content. Designed (plain or gradient) backgrounds only."""
    need("ffmpeg")
    h = max(2, int(round(width * (info["height"] or 9) / (info["width"] or 16) / 2) * 2))
    raw = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-t", f"{limit}", "-i", str(video), "-an", "-vf",
                          f"fps={fps},scale={width}:{h}:flags=area,format=rgb24", "-f", "rawvideo", "-"], capture_output=True).stdout
    n = len(raw) // (width * h * 3)
    fr = np.frombuffer(raw[: n * width * h * 3], np.uint8).reshape(n, h, width, 3)
    bounds = [0] + [int(round(c * fps)) for c in cuts if c * fps < n] + [n]
    shots = []
    for s0, s1 in zip(bounds[:-1], bounds[1:]):
        if s1 - s0 < fps * 0.5:
            continue
        last = fr[max(s0, s1 - 1 - int(fps * 0.1))].astype(np.float32)
        b = max(2, min(h, width) // 25)
        border = np.concatenate([last[:b].reshape(-1, 3), last[-b:].reshape(-1, 3), last[:, :b].reshape(-1, 3), last[:, -b:].reshape(-1, 3)])
        bg = np.median(border, axis=0)
        if float(np.median(np.abs(border - bg).max(1))) > 18:
            continue
        on = (np.abs(last - bg).max(-1) > 40).mean(1) > 0.004
        rows, start = [], None
        for y, v in enumerate(list(on) + [False]):
            if v and start is None:
                start = y
            elif not v and start is not None:
                if y - start >= 2:
                    rows.append((start, y))
                start = None
        ins = []
        for y0, y1 in rows:
            cnt = np.array([(np.abs(fr[i][y0:y1].astype(np.float32) - bg).max(-1) > 40).sum() for i in range(s0, s1)])
            final = cnt[-1 - int(fps * 0.1)] if len(cnt) > fps * 0.1 else cnt[-1]
            hit = np.nonzero(cnt >= max(1, final / 3))[0]
            ins.append(round((s0 + int(hit[0])) / fps, 2) if len(hit) else None)
        shots.append({"start": round(s0 / fps, 2), "rows": [[round(y0 / h, 3), round((y1 - y0) / h, 3)] for y0, y1 in rows], "in_s": ins})
    return shots


def cuts_of(fr, fps):
    out = []
    for i in range(1, len(fr)):
        a, b = fr[i - 1], fr[i]
        ha = np.histogramdd(a.reshape(-1, 3), bins=(4, 4, 4), range=[(0, 256)] * 3)[0].ravel()
        hb = np.histogramdd(b.reshape(-1, 3), bins=(4, 4, 4), range=[(0, 256)] * 3)[0].ravel()
        d = 0.5 * np.abs(ha / ha.sum() - hb / hb.sum()).sum()
        if d > 0.35 and np.abs(a - b).mean() > 25:
            out.append(round(i / fps, 2))
    return out


def activity(fr, fps):
    """Motion per frame (0..1) and the stretches where something moves."""
    n, h, w = fr.shape[:3]
    g = np.abs(np.diff(fr, axis=0)).mean(-1) / 255  # (n-1, h, w)
    cells = g[:, : h - h % 4, : w - w % 4].reshape(n - 1, 4, h // 4, 4, w // 4).mean(axis=(2, 4)).reshape(n - 1, 16)
    d = np.concatenate([[0.0], cells.max(1)])  # the most active sixteenth of the frame
    thr = max(0.006, float(np.percentile(d, 30)) * 2)
    moving = d > thr
    runs, s = [], None
    for i, m in enumerate(list(moving) + [False]):
        if m and s is None:
            s = i
        elif not m and s is not None:
            if i - s >= 2:
                runs.append([round((s - 1) / fps, 2), round(i / fps, 2)])
            s = None
    return d, runs


def stats(img):
    f = img.astype(np.float32) / 255
    lum = f @ np.array([0.299, 0.587, 0.114], np.float32)
    mx, mn = f.max(-1), f.min(-1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    gy, gx = np.abs(np.diff(lum, axis=0))[:, :-1], np.abs(np.diff(lum, axis=1))[:-1]
    edge = (np.hypot(gy, gx) > 0.12).mean()
    accent = ((sat > 0.45) & (mx > 0.3)).mean()
    warm = float((f[..., 0] - f[..., 2]).mean())
    return {"brightness": round(float(lum.mean()), 3), "contrast": round(float(lum.std()), 3), "saturation": round(float(sat.mean()), 3),
            "detail": round(float(edge), 4), "accent": round(float(accent), 4), "warmth": round(warm, 3),
            "mean_colour": "#%02x%02x%02x" % tuple((f.reshape(-1, 3).mean(0) * 255).round().astype(int))}


def content_box(img):
    """Box around what differs from the frame's border colour (designed backgrounds), as share of the frame."""
    f = img.astype(np.float32)
    h, w = f.shape[:2]
    b = max(2, min(h, w) // 25)
    border = np.concatenate([f[:b].reshape(-1, 3), f[-b:].reshape(-1, 3), f[:, :b].reshape(-1, 3), f[:, -b:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    spread = float(np.median(np.abs(border - bg).max(1)))
    if spread > 18:
        return None
    m = np.abs(f - bg).max(-1) > 40
    if m.mean() < 0.002:
        return None
    ys, xs = np.nonzero(m)
    x0, x1 = np.percentile(xs, [1, 99])
    y0, y1 = np.percentile(ys, [1, 99])
    rows, on, start = [], m.mean(1) > 0.002, None
    for y, v in enumerate(list(on) + [False]):
        if v and start is None:
            start = y
        elif not v and start is not None:
            if y - start >= 3:
                cols = np.nonzero(m[start:y].any(0))[0]
                rows.append([round(start / h, 3), round((y - start) / h, 3), round(cols.min() / w, 3), round((cols.max() - cols.min() + 1) / w, 3)])
            start = None
    return {"box": [round(x0 / w, 3), round(y0 / h, 3), round((x1 - x0) / w, 3), round((y1 - y0) / h, 3)],
            "background": "#%02x%02x%02x" % tuple(bg.round().astype(int)), "rows": rows}


def region_box(img, region):
    h, w = img.shape[:2]
    x, y, rw, rh = [int(round(v)) for v in (region[0] * w, region[1] * h, region[2] * w, region[3] * h)]
    sub = img[y:y + rh, x:x + rw].astype(np.float32)
    if sub.size == 0:
        return None
    g = sub @ np.array([0.299, 0.587, 0.114], np.float32)
    border = np.concatenate([g[0], g[-1], g[:, 0], g[:, -1]])
    bg = float(np.median(border))
    m = np.abs(g - bg) > 60
    if m.sum() < 10:
        return {"content": "none"}
    ys, xs = np.nonzero(m)
    return {"content_height_px": int(ys.max() - ys.min() + 1), "content_width_px": int(xs.max() - xs.min() + 1),
            "content_left_px": int(xs.min()), "content_top_px": int(ys.min()), "touches_edge": bool(xs.min() == 0 or ys.min() == 0 or
                                                                                                   xs.max() == m.shape[1] - 1 or ys.max() == m.shape[0] - 1)}


def pct(a, b):
    return (b - a) / max(abs(a), 1e-6) * 100


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("reference")
    ap.add_argument("remake")
    ap.add_argument("--times", help="seconds of the reference to compare, comma separated (default: 8 across, plus after each cut)")
    ap.add_argument("--offset", type=float, default=0.0, help="the remake's moment = reference moment + offset")
    ap.add_argument("--region", help="x,y,w,h in percent: also compare the content of this area (a title, a logo)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    ri, mi = probe(a.reference), probe(a.remake)
    diffs = []

    def add(size, text):
        diffs.append((size, text))

    if abs(ri["duration"] - mi["duration"]) > 0.15:
        add(abs(pct(ri["duration"], mi["duration"])), f"length: reference {ri['duration']:.2f} s, remake {mi['duration']:.2f} s")
    if (ri["width"] / ri["height"]) != (mi["width"] / mi["height"]):
        add(100, f"shape: reference {ri['width']}x{ri['height']}, remake {mi['width']}x{mi['height']}")
    rf, mf = low_frames(a.reference, ri), low_frames(a.remake, mi)
    rc, mc = cuts_of(rf, 10), cuts_of(mf, 10)
    if len(rc) != len(mc):
        add(30 + 10 * abs(len(rc) - len(mc)), f"cuts: reference {len(rc)} at {rc} s, remake {len(mc)} at {mc} s")
    else:
        off = [round(y - x - a.offset, 2) for x, y in zip(rc, mc)]
        late = [(x, o) for x, o in zip(rc, off) if abs(o) >= 0.15]
        if late:
            add(20 + 40 * max(abs(o) for _, o in late), "cut timing: " + ", ".join(f"the cut at {x} s comes {abs(o)} s {'later' if o > 0 else 'earlier'}" for x, o in late))
    rd, rruns = activity(rf, 10)
    md, mruns = activity(mf, 10)
    # match moving stretches by order of start
    timing = []
    for r in rruns:
        cand = [m for m in mruns if abs((m[0] - a.offset) - r[0]) <= 0.6]
        if not cand:
            timing.append(f"{r[0]}-{r[1]} s moves in the reference; nothing moves then in the remake")
            continue
        m = min(cand, key=lambda m: abs((m[0] - a.offset) - r[0]))
        dl_r, dl_m = r[1] - r[0], m[1] - m[0]
        if abs(dl_m - dl_r) >= max(0.15, 0.3 * dl_r):
            timing.append(f"the move at {r[0]} s takes {dl_r:.2f} s in the reference and {dl_m:.2f} s in the remake ({'slower' if dl_m > dl_r else 'faster'})")
        elif abs((m[0] - a.offset) - r[0]) >= 0.15:
            timing.append(f"the move at {r[0]} s starts {abs(m[0] - a.offset - r[0]):.2f} s {'later' if m[0] - a.offset > r[0] else 'earlier'} in the remake")
    still_r = float((rd < max(0.006, float(np.percentile(rd, 30)) * 2)).mean())
    still_m = float((md < max(0.006, float(np.percentile(md, 30)) * 2)).mean())
    if abs(still_r - still_m) > 0.15:
        timing.append(f"still for {still_r * 100:.0f} % of the reference and {still_m * 100:.0f} % of the remake")
    for t in timing:
        add(35, "timing: " + t)
    dur = min(ri["duration"], mi["duration"] - a.offset)
    if a.times:
        times = [float(x) for x in a.times.split(",")]
    else:
        times = sorted(set([round(dur * k / 9, 2) for k in range(1, 9)] + [round(c + 0.5, 2) for c in rc if c + 0.5 < dur]))
    region = [float(v) / 100 for v in a.region.split(",")] if a.region else None
    rimgs = grab(a.reference, times, 480, ri)
    mimgs = grab(a.remake, [t + a.offset for t in times], 480, mi)
    pairs = []
    for t, x, y in zip(times, rimgs, mimgs):
        if x is None or y is None:
            continue
        sx, sy = stats(x), stats(y)
        p = {"t": t, "reference": sx, "remake": sy, "ref_box": content_box(x), "remake_box": content_box(y)}
        if region:
            p["ref_region"], p["remake_region"] = region_box(x, region), region_box(y, region)
        pairs.append(p)
    if not pairs:
        die("could not read frames from one of the videos")
    # look: average over moments, and the worst moment
    for key, name, unit, lim in [("brightness", "brightness", "", 0.06), ("contrast", "contrast", "", 0.04), ("saturation", "colour strength", "", 0.06),
                                 ("detail", "detail (edges, lines, small text)", "", None), ("accent", "strong colour area", "", None), ("warmth", "warmth (red against blue)", "", 0.05)]:
        r = np.array([p["reference"][key] for p in pairs])
        m = np.array([p["remake"][key] for p in pairs])
        diff = m - r
        worst = int(np.argmax(np.abs(diff)))
        if lim is None:
            rel = pct(r.mean(), m.mean())
            if abs(rel) >= 30 and max(r.mean(), m.mean()) > 0.01:
                add(abs(rel) / 2, f"{name}: {abs(rel):.0f} % {'more' if rel > 0 else 'less'} in the remake on average")
        elif abs(diff.mean()) >= lim or abs(diff[worst]) >= 2 * lim or (abs(pct(r.mean(), m.mean())) >= 25 and abs(diff.mean()) >= 0.02):
            add(abs(diff.mean()) * 300, f"{name}: reference {r.mean():.2f}, remake {m.mean():.2f} on average; most at {pairs[worst]['t']} s "
                                         f"({r[worst]:.2f} against {m[worst]:.2f})")
    cols_r = [p["reference"]["mean_colour"] for p in pairs]
    cols_m = [p["remake"]["mean_colour"] for p in pairs]
    # graphics: size and place of the main content box
    # layout is compared only where both videos hold still: mid-move, a slower remake differs everywhere
    any_rows = False
    moving_at = []
    for p in pairs:
        row_level = False
        c0, c1 = p["ref_box"], p["remake_box"]
        b0, b1 = (c0 or {}).get("box"), (c1 or {}).get("box")
        if c0 and c1:
            k0 = np.array([int(c0["background"][i:i + 2], 16) for i in (1, 3, 5)], float)
            k1 = np.array([int(c1["background"][i:i + 2], 16) for i in (1, 3, 5)], float)
            if np.linalg.norm(k0 - k1) > 18:
                add(np.linalg.norm(k0 - k1) / 3, f"background at {p['t']} s: {c0['background']} in the reference, {c1['background']} in the remake (edge colour)")
        if any(x - 0.1 <= p["t"] <= y + 0.1 for x, y in rruns) or any(x - 0.1 <= p["t"] + a.offset <= y + 0.1 for x, y in mruns):
            moving_at.append(p["t"])
            continue
        if c0 and c1:
            rows0 = [r for r in c0["rows"] if r[1] > 0.01]
            rows1 = [r for r in c1["rows"] if r[1] > 0.01]
            if len(rows0) != len(rows1):
                row_level = True
                add(30, f"graphics at {p['t']} s: {len(rows0)} rows of text or shapes in the reference, {len(rows1)} in the remake "
                        f"(reference rows at {', '.join(f'{r[0] * 100:.0f}' for r in rows0)} % from the top; remake at "
                        f"{', '.join(f'{r[0] * 100:.0f}' for r in rows1)} %)")
            if rows0 and rows1:
                h0, h1 = float(np.median([r[1] for r in rows0])), float(np.median([r[1] for r in rows1]))
                dh = pct(h0, h1)
                if abs(dh) >= 10:
                    row_level = True
                    add(abs(dh) + 10, f"graphics at {p['t']} s: rows of text or shapes are {abs(dh):.0f} % {'taller' if dh > 0 else 'shorter'} in the remake "
                                      f"(median row {h0 * 100:.1f} % against {h1 * 100:.1f} % of the frame height: drawn {'larger' if dh > 0 else 'smaller'})")
                elif len(rows0) == len(rows1):
                    for r0, r1 in zip(rows0, rows1):
                        d1 = pct(r0[1], r1[1])
                        if abs(d1) >= 12:
                            row_level = True
                            add(abs(d1), f"graphics at {p['t']} s: the row at {r0[0] * 100:.0f} % from the top is {abs(d1):.0f} % {'taller' if d1 > 0 else 'shorter'} in the remake")
        if b0 and b1:
            dh = pct(b0[3], b1[3])
            dw = pct(b0[2], b1[2])
            dx = (b1[0] + b1[2] / 2) - (b0[0] + b0[2] / 2)
            dy = (b1[1] + b1[3] / 2) - (b0[1] + b0[3] / 2)
            if not row_level and (max(abs(dh), abs(dw)) >= 12 or max(abs(dx), abs(dy)) >= 0.04):
                add(max(abs(dh), abs(dw)) / 2 + max(abs(dx), abs(dy)) * 100,
                    f"graphics at {p['t']} s: the content spans {b0[2] * 100:.0f}x{b0[3] * 100:.0f} % of the frame in the reference and "
                    f"{b1[2] * 100:.0f}x{b1[3] * 100:.0f} % in the remake" + (f", its centre moved {dx * 100:+.0f} % across, {dy * 100:+.0f} % down" if max(abs(dx), abs(dy)) >= 0.04 else ""))
        elif bool(b0) != bool(b1) and (b0 or b1):
            add(25, f"graphics at {p['t']} s: {'the reference shows graphics on a plain background, the remake does not' if b0 else 'the remake shows graphics on a plain background, the reference does not'}")
        any_rows = any_rows or row_level
        if region:
            r0, r1 = p.get("ref_region"), p.get("remake_region")
            if r0 and r1 and "content_height_px" in r0 and "content_height_px" in r1:
                d = pct(r0["content_height_px"], r1["content_height_px"])
                if abs(d) >= 10:
                    add(abs(d), f"region at {p['t']} s: content {r0['content_height_px']} px tall in the reference, {r1['content_height_px']} px in the remake "
                                f"({abs(d):.0f} % {'bigger' if d > 0 else 'smaller'}; frames drawn 480 px wide)")
                if r1.get("touches_edge") and not r0.get("touches_edge"):
                    add(30, f"region at {p['t']} s: the remake's content touches the region's edge (cut off or larger)")
            elif r0 and r1 and (("content_height_px" in r0) != ("content_height_px" in r1)):
                add(40, f"region at {p['t']} s: {'empty in the remake' if 'content_height_px' in r0 else 'empty in the reference'}")
    if any_rows:  # less or more detail follows from text drawn smaller or a missing row
        diffs = [d for d in diffs if not d[1].startswith("detail")]
    # rows that come in one after another (stagger)
    try:
        re_, me_ = row_entrances(a.reference, ri, rc), row_entrances(a.remake, mi, mc)
    except Exception:
        re_, me_ = [], []
    for s_r, s_m in zip(re_, me_):
        tr = sorted(t for t in s_r["in_s"] if t is not None and t > s_r["start"] + 0.05)
        tm = sorted(t for t in s_m["in_s"] if t is not None and t > s_m["start"] + 0.05)
        if len(tr) >= 2 and len(tm) >= 2:
            g_r, g_m = float(np.median(np.diff(tr))), float(np.median(np.diff(tm)))
            if abs(g_m - g_r) >= 0.06 and abs(pct(max(g_r, 0.01), max(g_m, 0.01))) >= 40:
                add(40, f"stagger in the shot from {s_r['start']} s: rows come in {g_r:.2f} s apart in the reference "
                        f"({', '.join(map(str, tr))} s) and {g_m:.2f} s apart in the remake ({', '.join(map(str, tm))} s)")
    merged = {}
    for size, text in diffs:  # the same difference at several moments: one line with the moments
        m = re.search(r" at ([\d.]+) s:", text)
        key = re.sub(r" at [\d.]+ s:", ":", text) if m else text
        key = re.sub(r"\(\d+ % (bigger|smaller)", "(", key)
        if key in merged:
            merged[key][0] = max(merged[key][0], size)
            if m:
                merged[key][2].append(m.group(1))
        else:
            merged[key] = [size, text, [m.group(1)] if m else []]
    diffs = []
    for key, (size, text, ts) in merged.items():
        if len(ts) > 1:
            text = re.sub(r" at [\d.]+ s:", f" at {', '.join(ts)} s:", text)
        diffs.append((size, text))
    diffs.sort(key=lambda x: -x[0])
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    report = {"reference": str(a.reference), "remake": str(a.remake), "offset": a.offset, "cuts": {"reference": rc, "remake": mc},
              "moving": {"reference": rruns, "remake": mruns}, "row_entrances": {"reference": re_, "remake": me_}, "pairs": pairs, "differences": [d for _, d in diffs],
              "mean_colours": {"reference": cols_r, "remake": cols_m}}
    (out / "compare.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    draw(rimgs, mimgs, times, pairs, out / "compare.png")
    print(f"reference {ri['width']}x{ri['height']} {ri['duration']:.2f} s, remake {mi['width']}x{mi['height']} {mi['duration']:.2f} s; "
          f"{len(pairs)} moments compared")
    if not diffs:
        print("no difference large enough to see in these numbers; look at the pairs anyway")
    for _, d in diffs:
        print("- " + d)
    print(f"moving stretches: reference {rruns}; remake {mruns}")
    if moving_at:
        print(f"layout (rows, size, place) not compared at {', '.join(map(str, moving_at))} s: something moves there in one of the videos")
    print(f"-> {out / 'compare.png'} (left reference, right remake)")


def draw(rimgs, mimgs, times, pairs, out):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return
    tiles = []
    for t, x, y in zip(times, rimgs, mimgs):
        if x is None or y is None:
            continue
        h = 300
        a = Image.fromarray(x)
        b = Image.fromarray(y)
        a = a.resize((int(a.width * h / a.height), h))
        b = b.resize((int(b.width * h / b.height), h))
        tile = Image.new("RGB", (a.width + b.width + 6, h + 16), (40, 40, 40))
        tile.paste(a, (0, 16))
        tile.paste(b, (a.width + 6, 16))
        ImageDraw.Draw(tile).text((3, 2), f"{t:.2f} s   reference | remake", fill=(255, 255, 255))
        tiles.append(tile)
    if not tiles:
        return
    cols = 3 if tiles[0].width < 700 else 2
    rows = math.ceil(len(tiles) / cols)
    W, H = tiles[0].width, tiles[0].height
    sheet = Image.new("RGB", (W * cols + 8 * (cols - 1), H * rows + 8 * (rows - 1)), (25, 25, 25))
    for i, tl in enumerate(tiles):
        sheet.paste(tl, ((i % cols) * (W + 8), (i // cols) * (H + 8)))
    sheet.save(out)


if __name__ == "__main__":
    main()
