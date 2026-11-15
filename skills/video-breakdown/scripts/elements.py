"""Follow every graphic, word, shape or logo on a designed background through time: when it comes in and how
(slide, scale, fade, wipe, cut on), how long it holds, how it leaves, which ones come in one after another
(stagger), and which stay in place across a cut (a match cut or a carried element).

  elements.py VIDEO --out work/el                          # the whole video (first 60 s)
  elements.py VIDEO --start 4 --end 9 --crop 0,20,100,60 --out work/el

Works on motion graphics: flat or gradient backgrounds, titles, shapes, logos, charts. Shots with filmed or textured
backgrounds are listed and skipped: for graphics over footage use events.png and frames.py. Writes elements.json and timeline.png (one row per element: a
picture of it, when it is in, holds and leaves). The numbers are hints: check entrances with frames.py.
"""
import argparse
import json
import math
import subprocess
from pathlib import Path

import numpy as np

from common import die, need, probe, utf8_stdout

WIDTH = 360
GRID = 0.008  # cell size as a share of the frame width
CUT = 0.18  # mean change of the whole frame that counts as a cut


def decode(video, info, start, end, crop, fps):
    need("ffmpeg")
    W, H = info["width"], info["height"]
    x, y, w, h = [int(round(v)) for v in (crop[0] * W, crop[1] * H, crop[2] * W, crop[3] * H)]
    w, h = max(16, min(w, W - x)), max(16, min(h, H - y))
    ow = min(WIDTH, w) // 2 * 2
    oh = max(16, int(round(h * ow / w)) // 2 * 2)
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{start:.3f}", "-i", str(video), "-t", f"{end - start:.3f}", "-an",
           "-vf", f"fps={fps},crop={w}:{h}:{x}:{y},scale={ow}:{oh}:flags=area,format=rgb24", "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    n = len(raw) // (ow * oh * 3)
    if n < 3:
        die("no frames in that window. Check --start and --end.")
    return np.frombuffer(raw[: n * ow * oh * 3], np.uint8).reshape(n, oh, ow, 3).astype(np.float32)


def plane_bg(f):
    h, w = f.shape[:2]
    b = max(2, min(h, w) // 25)
    m = np.zeros((h, w), bool)
    m[:b], m[-b:], m[:, :b], m[:, -b:] = True, True, True, True
    yy, xx = np.nonzero(m)
    A = np.stack([np.ones_like(xx), xx / w, yy / h], 1).astype(np.float32)
    vals = f[yy, xx]
    coef, *_ = np.linalg.lstsq(A, vals, rcond=None)
    res = np.abs(A @ coef - vals).max(1)
    keep = res < np.percentile(res, 70) + 1  # refit without border pixels that belong to elements
    coef, *_ = np.linalg.lstsq(A[keep], vals[keep], rcond=None)
    gy, gx = np.mgrid[0:h, 0:w]
    return coef[0] + (gx / w)[..., None] * coef[1] + (gy / h)[..., None] * coef[2], float(np.median(np.abs(A[keep] @ coef - vals[keep]).max(1)))


def components(mask, cell, frame=None):
    """Blobs of a boolean mask on a coarse grid (cell px). Cells join across small gaps (letters of a word: up to three
    empty cells sideways, one up or down) when their colours match, so a white card passing a gold circle stays apart
    from it. Boxes are then fitted to the mask's pixels."""
    h, w = mask.shape
    gh, gw = h // cell, w // cell
    mc = mask[: gh * cell, : gw * cell].reshape(gh, cell, gw, cell)
    cover = mc.mean(axis=(1, 3))
    g = cover > 0.12
    if not g.any():
        return []
    col = None
    if frame is not None:
        fc = frame[: gh * cell, : gw * cell].reshape(gh, cell, gw, cell, 3)
        col = (fc * mc[..., None]).sum(axis=(1, 3)) / np.maximum(mc.sum(axis=(1, 3)), 1)[..., None]
    steps = [(dy, dx) for dy in (-2, -1, 0, 1, 2) for dx in range(-4, 5)
             if (dy, dx) != (0, 0) and (dy == 0 or (abs(dy) == 1 and abs(dx) <= 3) or (abs(dy) == 2 and dx == 0))]
    seen = np.zeros_like(g)
    out = []
    for y, x in zip(*np.nonzero(g)):
        if seen[y, x]:
            continue
        stack, cells = [(y, x)], []
        seen[y, x] = True
        total = col[y, x].copy() if col is not None else None
        while stack:
            cy, cx = stack.pop()
            cells.append((cy, cx))
            for dy, dx in steps:
                ny, nx = cy + dy, cx + dx
                if 0 <= ny < gh and 0 <= nx < gw and g[ny, nx] and not seen[ny, nx]:
                    if col is not None and (np.abs(col[ny, nx] - col[cy, cx]).max() > 70 or
                                            np.abs(col[ny, nx] - total / len(cells)).max() > 110):
                        continue
                    if total is not None:
                        total += col[ny, nx]
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        if len(cells) < 2:
            continue
        ys = np.array([c[0] for c in cells])
        xs = np.array([c[1] for c in cells])
        sub = np.zeros((gh, gw), bool)
        sub[ys, xs] = True
        pm = mask[: gh * cell, : gw * cell] & np.repeat(np.repeat(sub, cell, 0), cell, 1)
        py, px = np.nonzero(pm)
        b = {"x0": int(px.min()), "x1": int(px.max()) + 1, "y0": int(py.min()), "y1": int(py.max()) + 1, "cells": int(len(cells))}
        if min(b["x1"] - b["x0"], b["y1"] - b["y0"]) <= 2:
            continue  # the soft edge of something bigger
        if col is not None:
            b["col"] = col[ys, xs].mean(0)
        out.append(b)
    # the soft outline of a shape, read as a ring around it: drop it
    # (a soft outline read as a ring, or a shaded patch of the same colour inside it): drop it
    def inside(a, b):
        return (b is not a and b["cells"] > a["cells"] and a["x0"] >= b["x0"] - 3 and a["x1"] <= b["x1"] + 3
                and a["y0"] >= b["y0"] - 3 and a["y1"] <= b["y1"] + 3)
    def same_or_ring(a, b):
        ring = (a["x1"] - a["x0"]) * (a["y1"] - a["y0"]) >= 0.6 * (b["x1"] - b["x0"]) * (b["y1"] - b["y0"])
        return ring or ("col" in a and "col" in b and np.abs(a["col"] - b["col"]).max() <= 70)
    out = [a for a in out if not any(inside(a, b) and same_or_ring(a, b) for b in out)]
    return join_lines(out)


def join_lines(blobs):
    """Words of one line become one element: same row, and the gap between them is under about 0.45 of their height."""
    changed = True
    while changed:
        changed = False
        for i in range(len(blobs)):
            for j in range(i + 1, len(blobs)):
                a, b = blobs[i], blobs[j]
                ha, hb = a["y1"] - a["y0"], b["y1"] - b["y0"]
                vo = min(a["y1"], b["y1"]) - max(a["y0"], b["y0"])
                gap = max(a["x0"], b["x0"]) - min(a["x1"], b["x1"])
                same_col = "col" not in a or "col" not in b or np.abs(a["col"] - b["col"]).max() <= 70
                if same_col and vo >= 0.6 * min(ha, hb) and gap <= 0.45 * min(ha, hb) and max(ha, hb) <= 1.6 * min(ha, hb):
                    blobs[i] = {"x0": min(a["x0"], b["x0"]), "x1": max(a["x1"], b["x1"]), "y0": min(a["y0"], b["y0"]),
                                "y1": max(a["y1"], b["y1"]), "cells": a["cells"] + b["cells"]}
                    if "col" in a and "col" in b:
                        blobs[i]["col"] = (a["col"] * a["cells"] + b["col"] * b["cells"]) / (a["cells"] + b["cells"])
                    blobs.pop(j)
                    changed = True
                    break
            if changed:
                break
    return blobs


def iou(a, b):
    ix = max(0, min(a["x1"], b["x1"]) - max(a["x0"], b["x0"]))
    iy = max(0, min(a["y1"], b["y1"]) - max(a["y0"], b["y0"]))
    inter = ix * iy
    ua = (a["x1"] - a["x0"]) * (a["y1"] - a["y0"]) + (b["x1"] - b["x0"]) * (b["y1"] - b["y0"]) - inter
    return inter / ua if ua else 0.0


def centre(b):
    return ((b["x0"] + b["x1"]) / 2, (b["y0"] + b["y1"]) / 2)


def link(prev, cur, w):
    """Match blobs of one frame to tracks of the frame before by overlap, then by nearest centre."""
    pairs, used = {}, set()
    cand = []
    for i, p in enumerate(prev):
        for j, c in enumerate(cur):
            o = iou(p, c)
            (px, py), (cx, cy) = centre(p), centre(c)
            dist = math.hypot(px - cx, py - cy) / w
            size = max(p["x1"] - p["x0"], p["y1"] - p["y0"], c["x1"] - c["x0"], c["y1"] - c["y0"]) / w
            if "col" in p and "col" in c and np.abs(p["col"] - c["col"]).max() > 70:
                continue  # another colour: something passing in front, not the same thing
            if o > 0.05 or dist < max(0.06, 0.6 * size):
                cand.append((-(o - dist), i, j))
    for _, i, j in sorted(cand):
        if i in pairs or j in used:
            continue
        pairs[i] = j
        used.add(j)
    return pairs


def find_cuts(frames):
    d = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2, 3)) / 255
    return [i + 1 for i, v in enumerate(d) if v > CUT]


def strength(f, bg, b):
    reg = np.abs(f[b["y0"]:b["y1"], b["x0"]:b["x1"]] - bg[b["y0"]:b["y1"], b["x0"]:b["x1"]]).max(-1)
    return float(np.percentile(reg, 95)) if reg.size else 0.0


def motion_kind(track, fps, w, h, entering):
    """How it comes in (or leaves): compare its box and strength at the still end with the moving end."""
    seq = track["boxes"]
    st = np.array(track["strength"])
    k = len(seq)
    if k < 2:
        return {"how": "cuts on" if entering else "cuts off", "over_s": 0.0}
    hold = seq[-1] if entering else seq[0]
    area = lambda b: (b["x1"] - b["x0"]) * (b["y1"] - b["y0"])
    while len(seq) > 2 and area(seq[0] if entering else seq[-1]) < 0.015 * area(hold):  # a speck before it shows
        seq, st = (seq[1:], st[1:]) if entering else (seq[:-1], st[:-1])
    k = len(seq)
    still_s = st[-1] if entering else st[0]
    moving = seq[: k - 1] if entering else seq[1:]
    first = moving[0] if entering else moving[-1]
    (hx, hy), (fx, fy) = centre(hold), centre(first)
    hw, hh = hold["x1"] - hold["x0"], hold["y1"] - hold["y0"]
    fw, fh = first["x1"] - first["x0"], first["y1"] - first["y0"]
    words = []
    dx, dy = (hx - fx) / w, (hy - fy) / h
    if not entering:
        dx, dy = -dx, -dy
    sw, sh = fw / max(hw, 1), fh / max(hh, 1)
    s_first = (st[0] if entering else st[-1]) / max(still_s, 1)
    xs0 = [bx["x0"] for bx in moving + [hold]]
    xs1 = [bx["x1"] for bx in moving + [hold]]
    ys0 = [bx["y0"] for bx in moving + [hold]]
    ys1 = [bx["y1"] for bx in moving + [hold]]
    tol = max(3, 0.02 * w)
    edge = max(3, 0.015 * w)
    off_left, off_right = first["x0"] <= edge, first["x1"] >= w - edge
    off_top, off_bottom = first["y0"] <= edge, first["y1"] >= h - edge
    if (off_left or off_right) and abs(dx) > 0.03:
        side = "from the left" if off_left else "from the right"
        if not entering:
            side = "to the left" if off_left else "to the right"
        words.append(f"slides {side}, from outside the frame")
    elif (off_top or off_bottom) and abs(dy) > 0.03:
        side = "from above" if off_top else "from below"
        if not entering:
            side = "upward" if off_top else "downward"
        words.append(f"slides {side}, from outside the frame")
    elif max(xs0) - min(xs0) <= tol and max(xs1) - min(xs1) > 0.25 * hw and max(ys0) - min(ys0) <= tol * 2:
        words.append("wipes or types on from the left" if entering else "wipes off toward the left")
    elif max(xs1) - min(xs1) <= tol and max(xs0) - min(xs0) > 0.25 * hw and max(ys1) - min(ys1) <= tol * 2:
        words.append("wipes or types on from the right" if entering else "wipes off toward the right")
    elif max(abs(dx), abs(dy)) > 0.03 and 0.7 < sw < 1.3 and 0.7 < sh < 1.3:
        side = ("from the left" if dx > 0 else "from the right") if abs(dx) >= abs(dy) else ("from below" if dy < 0 else "from above")
        if not entering:
            side = side.replace("from the left", "to the right").replace("from the right", "to the left").replace(
                "from below", "upward").replace("from above", "downward")
        words.append(f"slides {side} ({abs(dx) * 100:.0f} % of the width)" if abs(dx) >= abs(dy)
                     else f"slides {side} ({abs(dy) * 100:.0f} % of the height)")
    elif sw < 0.9 and sh < 0.9 and abs(sw - sh) < 0.12:
        words.append(f"scales {'up from' if entering else 'down to'} about {min(sw, sh) * 100:.0f} %")
    elif sw < 0.75 <= sh:
        left_fixed = abs(first["x0"] - hold["x0"]) < abs(first["x1"] - hold["x1"])
        words.append(f"wipes or types on from the {'left' if left_fixed else 'right'}" if entering else
                     f"wipes off toward the {'left' if left_fixed else 'right'}")
    elif sh < 0.75 <= sw:
        top_fixed = abs(first["y0"] - hold["y0"]) < abs(first["y1"] - hold["y1"])
        words.append(f"wipes or unfolds {'downward' if top_fixed else 'upward'}" if entering else "folds away")
    if s_first < 0.7:
        words.append("fades in" if entering else "fades out")
    if entering:
        sizes = [math.hypot(b["x1"] - b["x0"], b["y1"] - b["y0"]) for b in seq]
        if 1.06 * sizes[-1] < max(sizes) < 1.6 * sizes[-1]:
            words.append(f"overshoots its size by {round((max(sizes) / sizes[-1] - 1) * 100)} % before it settles")
        xs = [centre(b)[0] for b in seq]
        if abs(xs[-1] - xs[0]) > 4 and (max(xs) - xs[-1]) * np.sign(xs[-1] - xs[0]) > 0.04 * w:
            words.append("goes past its place and comes back")
    return {"how": ", ".join(words) if words else ("cuts on" if entering else "cuts off"), "over_s": round((k - 1) / fps, 2)}


def kind_of(e):
    how = e["enter"]["how"]
    for k in ("slides from the left", "slides from the right", "slides from above", "slides from below", "scales up",
              "wipes or types on from the left", "wipes or types on from the right", "wipes or unfolds", "fades in", "cuts on"):
        if how.startswith(k):
            return k
    return how.split(",")[0]


def hold_span(track, fps):
    """First and last frame of the longest stretch where the box and its strength stay put (the hold)."""
    boxes, st = track["boxes"], track["strength"]
    n = len(boxes)
    stable = []
    for i in range(n - 1):
        a, b = boxes[i], boxes[i + 1]
        size = max(a["x1"] - a["x0"], a["y1"] - a["y0"], 4)
        tol = max(2, 0.03 * size)
        same = max(abs(a["x0"] - b["x0"]), abs(a["x1"] - b["x1"]), abs(a["y0"] - b["y0"]), abs(a["y1"] - b["y1"])) <= tol
        steady = abs(st[i + 1] - st[i]) <= 0.08 * max(st[i], st[i + 1], 1)
        stable.append(same and steady)
    best, s = (0, -1), None
    for i, v in enumerate(stable + [False]):
        if v and s is None:
            s = i
        elif not v and s is not None:
            if i - s > best[1] - best[0]:
                best = (s, i)
            s = None
    if best[1] - best[0] < max(2, int(fps * 0.2)):
        return n - 1, n - 1  # never holds still
    # A slow settle (the tail of an ease) moves little from frame to frame: hold only from where the box is at its
    # held place and size, measured against the middle of the hold.
    i0, i1 = best
    mid = boxes[(i0 + i1) // 2]
    size = max(mid["x1"] - mid["x0"], mid["y1"] - mid["y0"], 4)
    tol = max(1.5, 0.015 * size)
    st_mid = st[(i0 + i1) // 2]
    def at_rest(b, sv):
        return (max(abs(b["x0"] - mid["x0"]), abs(b["x1"] - mid["x1"]), abs(b["y0"] - mid["y0"]), abs(b["y1"] - mid["y1"])) <= tol
                and abs(sv - st_mid) <= 0.05 * max(st_mid, 1))
    while i0 < (i0 + i1) // 2 and not all(at_rest(boxes[j], st[j]) for j in range(i0, min(i0 + 3, i1 + 1))):
        i0 += 1
    while i1 > (best[0] + i1) // 2 and not all(at_rest(boxes[j], st[j]) for j in range(max(i1 - 2, i0), i1 + 1)):
        i1 -= 1
    return i0, i1


def settle_index(track, fps, entering):
    """How many frames the entrance (or exit) takes: until the box and strength stop changing."""
    boxes, st = track["boxes"], track["strength"]
    n = len(boxes)
    ref_i = n - 1 if entering else 0
    ref = boxes[ref_i]
    size = max(ref["x1"] - ref["x0"], ref["y1"] - ref["y0"], 4)
    order = range(n) if entering else range(n - 1, -1, -1)
    for i in order:
        b = boxes[i]
        close = max(abs(b["x0"] - ref["x0"]), abs(b["x1"] - ref["x1"]), abs(b["y0"] - ref["y0"]), abs(b["y1"] - ref["y1"])) <= max(2, 0.04 * size)
        if close and st[i] >= 0.85 * st[ref_i]:
            if entering:
                # stays put from here on?
                if all(max(abs(boxes[j]["x0"] - b["x0"]), abs(boxes[j]["y0"] - b["y0"])) <= max(2, 0.04 * size) for j in range(i, min(n, i + int(fps * 0.3)))):
                    return i
            else:
                return n - 1 - i
    return 0 if not entering else n - 1


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float)
    ap.add_argument("--crop", default="0,0,100,100", help="x,y,w,h in percent")
    ap.add_argument("--fps", type=float, help="frames a second to read (default: the video's, at most 30)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    info = probe(a.video)
    end = min(a.end or info["duration"], info["duration"], a.start + 60)
    fps = a.fps or min(30.0, info["fps"])
    try:
        crop = [float(v) / 100 for v in a.crop.split(",")]
        assert len(crop) == 4
    except (ValueError, AssertionError):
        die("--crop takes x,y,w,h in percent")
    frames = decode(a.video, info, a.start, end, crop, fps)
    n, h, w = frames.shape[:3]
    cell = max(2, int(round(GRID * w)))
    cuts = find_cuts(frames)
    shots = list(zip([0] + cuts, cuts + [n]))
    bgs, footage = [None] * n, []
    for s0, s1 in shots:
        res = [plane_bg(frames[i]) for i in (s0, (s0 + s1 - 1) // 2, s1 - 1)]
        if max(r[1] for r in res) < 14:
            for i in range(s0, s1):
                bgs[i] = plane_bg(frames[i])[0]
        else:  # filmed or textured: not read (a moving picture behind the graphics breaks the background model)
            footage.append([round(a.start + s0 / fps, 2), round(a.start + s1 / fps, 2)])
            for i in range(s0, s1):
                bgs[i] = None
    diffs = np.stack([np.abs(frames[i] - bgs[i]).max(-1) if bgs[i] is not None else np.zeros((h, w), np.float32) for i in range(n)])
    designed = [i for i in range(n) if bgs[i] is not None]
    thr = max(24.0, 0.3 * float(np.percentile(diffs[designed], 99.7))) if designed else 1e9
    tracks, live = [], {}
    shot_of = np.zeros(n, int)
    for k, (s0, s1) in enumerate(shots):
        shot_of[s0:s1] = k
    for i in range(n):
        blobs = components(diffs[i] > thr, cell, frames[i])
        for b in blobs:
            b["s"] = strength(frames[i], bgs[i], b) if bgs[i] is not None else 0.0
        prev_ids = [tid for tid in live]
        prev = [tracks[tid]["boxes"][-1] for tid in prev_ids]
        same_shot = [tracks[tid]["shot"] == shot_of[i] for tid in prev_ids]
        pairs = link([p for p, ok in zip(prev, same_shot) if ok], blobs, w)
        ok_ids = [tid for tid, ok in zip(prev_ids, same_shot) if ok]
        new_live = {}
        for pi, bj in pairs.items():
            tid = ok_ids[pi]
            tracks[tid]["boxes"].append(blobs[bj])
            tracks[tid]["strength"].append(blobs[bj]["s"])
            tracks[tid]["last"] = i
            new_live[tid] = True
        taken = set(pairs.values())
        for j, b in enumerate(blobs):
            if j not in taken:
                tracks.append({"first": i, "last": i, "boxes": [b], "strength": [b["s"]], "shot": int(shot_of[i])})
                new_live[len(tracks) - 1] = True
        live = new_live
    min_len = max(3, int(fps * 0.2))
    keep = [t for t in tracks if t["last"] - t["first"] + 1 >= min_len and
            max(b["cells"] for b in t["boxes"]) * cell * cell >= 0.0015 * w * h]
    elements = []
    for t in keep:
        boxes = t["boxes"]
        s_first, s_last = shots[t["shot"]]
        starts_at_shot = t["first"] <= s_first
        ends_at_shot = t["last"] >= s_last - 1
        i_in, i_hold_end = hold_span(t, fps)
        hb = boxes[(i_in + i_hold_end) // 2]  # where it holds
        if min((hb["x1"] - hb["x0"]) / w, (hb["y1"] - hb["y0"]) / h) < 0.01:
            continue
        if starts_at_shot:
            i_in = 0
        sub_in = {"boxes": boxes[: i_in + 1], "strength": t["strength"][: i_in + 1]}
        rest = len(boxes) - 1
        i_out = rest if ends_at_shot else i_hold_end
        sub_out = {"boxes": boxes[i_out:], "strength": t["strength"][i_out:]}
        el = {"id": len(elements) + 1,
              "box_pct": [round(hb["x0"] / w * 100, 1), round(hb["y0"] / h * 100, 1), round((hb["x1"] - hb["x0"]) / w * 100, 1),
                          round((hb["y1"] - hb["y0"]) / h * 100, 1)],
              "in_s": round(a.start + t["first"] / fps, 2), "out_s": round(a.start + (t["last"] + 1) / fps, 2),
              "enter": ({"how": "there when the shot starts", "over_s": 0.0} if starts_at_shot else motion_kind(sub_in, fps, w, h, True)),
              "leave": ({"how": "there when the shot ends", "over_s": 0.0} if ends_at_shot else motion_kind(sub_out, fps, w, h, False)),
              "_hold": hb, "_first": t["first"], "_last": t["last"], "_shot": t["shot"], "_box0": boxes[0], "_box1": boxes[-1]}
        el["holds_s"] = round(max(0.0, (i_out - i_in) / fps), 2)
        moves = [centre(b) for b in boxes[i_in:i_out + 1]]
        if len(moves) > 2:
            span = max(math.hypot(x - moves[0][0], y - moves[0][1]) for x, y in moves) / w
            if span > 0.02:
                el["while_holding"] = f"drifts {span * 100:.0f} % of the width"
        elements.append(el)
    elements.sort(key=lambda e: (e["in_s"], e["box_pct"][1], e["box_pct"][0]))
    for k, e in enumerate(elements):
        e["id"] = k + 1
    # stagger: elements entering the same way within a short time
    groups = []
    for e in elements:
        if e["enter"]["how"].startswith("there when"):
            continue
        def fits(g):  # same way in, soon after, and at about the same rhythm as the group so far
            gap = e["in_s"] - g[-1]["in_s"]
            first_gap = g[1]["in_s"] - g[0]["in_s"] if len(g) > 1 else None
            return gap <= 0.6 and kind_of(g[-1]) == kind_of(e) and (first_gap is None or gap <= max(0.1, 2 * first_gap))
        g = next((g for g in groups if fits(g)), None)
        (g.append(e) if g else groups.append([e]))
    staggers = []
    for g in groups:
        if len(g) >= 3:
            gaps = np.diff([x["in_s"] for x in g])
            staggers.append({"elements": [x["id"] for x in g], "how": kind_of(g[0]),
                             "gap_s": round(float(np.median(gaps)), 3), "gaps_s": [round(float(v), 3) for v in gaps]})
    # carried across a cut: one element ends on the last frame of a shot, another starts at the next, same place
    carried = []
    for c in cuts:
        before = [e for e in elements if e["_last"] == c - 1]
        after = [e for e in elements if e["_first"] == c]
        for b in before:
            for f in after:
                o = iou(b["_box1"], f["_box0"])
                (bx, by), (fx, fy) = centre(b["_box1"]), centre(f["_box0"])
                if o > 0.3 or math.hypot(bx - fx, by - fy) < 0.05 * w:
                    sb = (b["_box1"]["x1"] - b["_box1"]["x0"]) / max(1, f["_box0"]["x1"] - f["_box0"]["x0"])
                    carried.append({"cut_s": round(a.start + c / fps, 2), "from": b["id"], "to": f["id"], "overlap": round(o, 2),
                                    "size_ratio": round(sb, 2)})
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    draw(a.video, info, a.start, crop, elements, end, out / "timeline.png")
    for e in elements:
        for k in ("_hold", "_first", "_last", "_shot", "_box0", "_box1"):
            e.pop(k, None)
    report = {"video": str(a.video), "window_s": [a.start, round(end, 2)], "fps_read": fps, "cuts_s": [round(a.start + c / fps, 2) for c in cuts],
              "not_read_s": footage, "elements": elements, "staggers": staggers, "carried_across_cuts": carried,
              "timeline": str(out / "timeline.png")}
    (out / "elements.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"{len(elements)} elements, {len(cuts)} cuts")
    if footage:
        print("not read, filmed or textured background (graphics over footage: use events.png and frames.py): " +
              ", ".join(f"{x}-{y} s" for x, y in footage))
    for e in elements:
        line = f"#{e['id']} at {e['box_pct'][0]:.0f},{e['box_pct'][1]:.0f} % ({e['box_pct'][2]:.0f}x{e['box_pct'][3]:.0f} %): in {e['in_s']} s, {e['enter']['how']}"
        if e["enter"]["over_s"]:
            line += f" over {e['enter']['over_s']} s"
        line += f"; holds {e['holds_s']} s" + (f" ({e['while_holding']})" if e.get("while_holding") else "")
        line += f"; out {e['out_s']} s, {e['leave']['how']}" + (f" over {e['leave']['over_s']} s" if e["leave"]["over_s"] else "")
        print(line)
    for s in staggers:
        print(f"stagger: #{', #'.join(map(str, s['elements']))} {s['how']}, {s['gap_s']} s apart (gaps {s['gaps_s']})")
    for c in carried:
        print(f"carried across the cut at {c['cut_s']} s: #{c['from']} -> #{c['to']} in the same place (overlap {c['overlap']}, size x{c['size_ratio']})")
    print(f"timeline: {out / 'timeline.png'}")


def draw(video, info, start, crop, elements, end, out):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    if not elements:
        return None
    from common import grab
    rows = elements[:40]
    W, rh, tw = 900, 54, 120
    img = Image.new("RGB", (W, rh * len(rows) + 30), (250, 250, 250))
    d = ImageDraw.Draw(img)
    span = max(0.1, end - start)
    X = lambda t: tw + 10 + (t - start) / span * (W - tw - 20)
    for t in np.arange(math.ceil(start), end, 1.0):
        d.line([X(t), 0, X(t), img.height], fill=(225, 225, 225))
        d.text((X(t) + 2, img.height - 14), f"{t:.0f}s", fill=(110, 110, 110))
    times = [min(end - 0.05, e["in_s"] + e["enter"]["over_s"] + 0.05) for e in rows]
    pics = grab(video, times, 640, info)
    for r, (e, pic) in enumerate(zip(rows, pics)):
        y = r * rh + 4
        if pic is not None:
            ph, pw = pic.shape[:2]
            x0 = crop[0] * pw + e["box_pct"][0] / 100 * crop[2] * pw
            y0 = crop[1] * ph + e["box_pct"][1] / 100 * crop[3] * ph
            x1 = x0 + max(4, e["box_pct"][2] / 100 * crop[2] * pw)
            y1 = y0 + max(4, e["box_pct"][3] / 100 * crop[3] * ph)
            tile = Image.fromarray(pic).crop((int(x0), int(y0), int(x1), int(y1)))
            tile.thumbnail((tw - 4, rh - 8))
            img.paste(tile, (2, y))
        a, b = X(e["in_s"]), X(e["out_s"])
        ein = X(e["in_s"] + e["enter"]["over_s"])
        eout = max(ein, X(e["out_s"] - e["leave"]["over_s"]))
        b = max(b, eout)
        d.rectangle([a, y + 8, ein, y + 30], fill=(0, 113, 227))
        d.rectangle([ein, y + 8, eout, y + 30], fill=(180, 190, 205))
        d.rectangle([eout, y + 8, b, y + 30], fill=(29, 29, 31))
        d.text((a, y + 33), f"#{e['id']} {e['enter']['how'][:60]}", fill=(29, 29, 31))
    img.save(out)
    return str(out)


if __name__ == "__main__":
    main()
