"""Measure a reference video shot by shot, so you can name what it does and look up how to make it.

  analyze.py VIDEO --out work/bd

Writes work/bd/breakdown.json and contact sheets (overview.png, shots_NN.png, joins_NN.png, events.png).
Everything here is measured from pixels and samples. The numbers are hints with known blind spots
(references/reading-the-numbers.md): open the sheets with the Read tool before you name anything.
"""
import argparse
import math
from pathlib import Path

import numpy as np

from common import decode_audio, die, frame_size, grab, iter_frames, lufs, probe, sheet, utf8_stdout, write_json

VERSION = "0.1.0"
DEBUG = bool(__import__("os").environ.get("VB_DEBUG"))
BANDS = 6  # horizontal bands for overlay events (top to bottom)


# ------------------------------------------------------------------ per-frame features
def hist(rgb):
    h = [np.bincount((rgb[..., c] >> 4).ravel(), minlength=16) for c in range(3)]
    v = np.concatenate(h).astype(np.float32)
    return v / (v.sum() / 3)


def layout(gray, gy=8, gx=8):
    h, w = gray.shape
    g = gray[: h - h % gy, : w - w % gx]
    return g.reshape(gy, g.shape[0] // gy, gx, g.shape[1] // gx).mean(axis=(1, 3))


def edges(gray):
    gx = np.abs(np.diff(gray, axis=1))[:-1, :]
    gy = np.abs(np.diff(gray, axis=0))[:, :-1]
    return (gx + gy) > 0.18


def features(video, info, fps, seconds):
    aspect = (info["width"] or 16) / (info["height"] or 9)
    width = int(round(96 * max(1.0, aspect) / 2) * 2)
    w, h = frame_size(info, width)
    gray, H, L, stats, E = [], [], [], [], []
    for rgb in iter_frames(video, fps, w, h, seconds):
        f = rgb.astype(np.float32) / 255
        g = f @ np.array([0.299, 0.587, 0.114], np.float32)
        mx, mn = f.max(axis=2), f.min(axis=2)
        sat = np.where(mx > 0.04, (mx - mn) / (mx + 1e-6), 0)
        lap = g[1:-1, 1:-1] * 4 - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]
        e = edges(g)
        band = np.array_split(np.arange(e.shape[0]), BANDS)
        gray.append((g * 255).astype(np.uint8))
        H.append(hist(rgb))
        L.append(layout(g))
        E.append([float(e[b].mean()) for b in band])
        stats.append((float(g.mean()), float(g.std()), float(sat.mean()), float(f[..., 0].mean() - f[..., 2].mean()),
                      float(lap.var())))
    if len(gray) < 4:
        die("the video is shorter than a few frames, or FFmpeg could not decode it.")
    return np.stack(gray), np.stack(H), np.stack(L), np.array(stats, np.float32), np.array(E, np.float32)


# ------------------------------------------------------------------ global motion
def _phase(a, b, win):
    """Shift (dx, dy) that moves a onto b, and the correlation peak (0..1)."""
    A = np.fft.fft2((a - a.mean()) * win)
    B = np.fft.fft2((b - b.mean()) * win)
    R = B * np.conj(A)
    R /= np.abs(R) + 1e-9
    r = np.fft.ifft2(R).real
    iy, ix = np.unravel_index(int(r.argmax()), r.shape)
    h, w = r.shape

    def sub(c, cm, cp):
        d = cm - 2 * c + cp
        return 0.0 if abs(d) < 1e-9 else 0.5 * (cm - cp) / d
    dy = iy + sub(r[iy, ix], r[(iy - 1) % h, ix], r[(iy + 1) % h, ix])
    dx = ix + sub(r[iy, ix], r[iy, (ix - 1) % w], r[iy, (ix + 1) % w])
    dy = dy - h if dy > h / 2 else dy
    dx = dx - w if dx > w / 2 else dx
    return dx, dy, float(r.max())


def motion(gray):
    """Per frame pair: tx, ty (fraction of width), zoom rate s, roll r (rad), fit residual, confidence."""
    n, h, w = gray.shape
    by, bx = h // 3, w // 3
    win = np.outer(np.hanning(by), np.hanning(bx)).astype(np.float32)
    cy, cx = [(i + 0.5) * by - h / 2 for i in range(3)], [(j + 0.5) * bx - w / 2 for j in range(3)]
    out = np.zeros((n - 1, 6), np.float32)
    g = gray.astype(np.float32) / 255
    for t in range(n - 1):
        rows, rhs, wts = [], [], []
        for i in range(3):
            for j in range(3):
                a = g[t, i * by:(i + 1) * by, j * bx:(j + 1) * bx]
                b = g[t + 1, i * by:(i + 1) * by, j * bx:(j + 1) * bx]
                if a.std() < 0.02 and b.std() < 0.02:
                    continue
                dx, dy, c = _phase(a, b, win)
                x, y = cx[j] / w, cy[i] / w
                rows += [[1, 0, x, -y], [0, 1, y, x]]
                rhs += [dx / w, dy / w]
                wts += [c, c]
        if len(rows) < 8 or sum(wts) <= 1e-6:
            out[t] = (0, 0, 0, 0, 0, 0)
            continue
        A, b, W = np.array(rows), np.array(rhs), np.sqrt(np.array(wts))
        p, *_ = np.linalg.lstsq(A * W[:, None], b * W, rcond=None)
        res = float(np.sqrt(np.average((A @ p - b) ** 2, weights=W ** 2)))
        out[t] = (p[0], p[1], p[2], p[3], res, float(np.mean(wts)))
    return out


# ------------------------------------------------------------------ joins between shots
def mad(x):
    m = float(np.median(x))
    return m, float(np.median(np.abs(x - m))) + 1e-6


def change_curve(H, L):
    dh = 0.5 * np.abs(np.diff(H, axis=0)).sum(axis=1) / 3
    dl = np.abs(np.diff(L, axis=0)).mean(axis=(1, 2))
    return dh, dl, 0.6 * dh + 0.4 * np.minimum(1.0, dl * 4)


def dist(H, L, a, b):
    return 0.6 * 0.5 * np.abs(H[a] - H[b]).sum() / 3 + 0.4 * min(1.0, float(np.abs(L[a] - L[b]).mean()) * 4)


def find_joins(H, L, gray, stats, fps):
    # c[t] is the change from frame t to frame t+1. A join is {"s": last frame of the old shot,
    # "e": first frame of the new one}.
    dh, dl, c = change_curve(H, L)
    med, dev = mad(c)
    hard = max(0.2, med + 10 * dev)
    soft = max(0.03, med + 3 * dev)
    n = len(c)
    joins, t = [], 0
    while t < n:
        if c[t] >= hard:
            e = t
            while e + 1 < n and c[e + 1] >= hard * 0.6:
                e += 1
            j = {"s": t, "e": e + 1}
            g0, g1 = gray[t].astype(np.float32) / 255, gray[min(len(gray) - 1, e + 1)].astype(np.float32) / 255
            if dist_frames(g0, g1) < 0.3 and _is_camera_move(gray, t, min(len(gray) - 1, e + 1)):
                t = e + 1  # a jolt of the camera, not a new shot
                continue
            # a push or slide has one big frame in the middle of many changed ones: take the whole run
            s0, e0 = t, e
            while s0 > 0 and c[s0 - 1] > soft and t - s0 < fps * 2:
                s0 -= 1
            while e0 + 1 < n and c[e0 + 1] > soft and e0 - e < fps * 2:
                e0 += 1
            if (t - s0) + (e0 - e) >= 4:
                inside = float(np.mean(np.r_[c[s0:t], c[e + 1:e0 + 1]]))
                around = np.r_[c[max(0, s0 - int(fps)):s0], c[e0 + 1:e0 + 1 + int(fps)]]
                if len(around) and inside > 2.5 * max(float(np.median(around)), med)                         and c[t:e + 1].sum() < 0.5 * c[s0:e0 + 1].sum():
                    j = {"s": s0, "e": e0 + 1, "gradual": True}
            joins.append(j)
            t = j["e"] + 1
            continue
        t += 1
    # gradual joins (dissolves, dips, wipes, irises) spread their change over many frames, each one small.
    # Compare frames a fixed span apart instead: inside a shot they stay alike, across a join they do not.
    taken = np.zeros(len(H), bool)
    for j in joins:
        taken[max(0, j["s"] - 1): j["e"] + 2] = True
    k = max(3, int(round(fps * 0.4)))
    W = np.zeros(len(H))
    for t in range(k, len(H) - k):
        W[t] = dist(H, L, t - k, t + k)
    mw, dw = mad(W[k: len(H) - k] if len(H) > 2 * k else W)
    thr = min(max(0.12, mw + 6 * dw), max(0.3, mw + 2 * dw))
    low = max(0.006, med + 2 * dev)
    d3 = np.array([dist(H, L, i, i + 3) for i in range(len(H) - 3)] + [0.0] * 3)
    b3 = float(np.median(d3))
    steady = max(1.8 * b3, b3 + 0.03)
    t = k
    while t < len(H) - k:
        if W[t] < thr or taken[t]:
            t += 1
            continue
        e = t
        while e + 1 < len(H) - k and W[e + 1] >= thr:
            e += 1
        # the join sits in the middle of the run; walk out from there to where each picture holds steady
        mid = (t + e) // 2
        s0, e0 = mid, mid
        while s0 > 3 and d3[s0 - 3] > steady and mid - s0 < fps * 1.5:
            s0 -= 1
        while e0 < len(H) - 4 and d3[e0] > steady and e0 - mid < fps * 1.5:
            e0 += 1
        a, b = max(0, s0 - 1), min(len(H) - 1, e0 + 1)
        if DEBUG:
            print("cand", round(t / fps, 2), round(e / fps, 2), "run", round(s0 / fps, 2), round(e0 / fps, 2),
                  "dist", round(dist(H, L, a, b), 3), "thr", round(thr, 3), "cam", _is_camera_move(gray, a, b),
                  "taken", bool(taken[s0:e0 + 1].any()))
        if not taken[s0:e0 + 1].any() and e0 - s0 >= 3 and dist(H, L, a, b) >= thr * 0.8                 and not _is_camera_move(gray, a, b):
            joins.append({"s": s0, "e": e0, "gradual": True})
            taken[max(0, s0 - 1): e0 + 2] = True
        t = max(e, e0) + 1
    # a same-scene cut (jump cut, punch-in) barely moves the histogram: catch isolated layout spikes
    mdl, ddl = mad(dl)
    near = set()
    for j in joins:
        near.update(range(j["s"] - 2, j["e"] + 3))
    for t in range(1, n - 1):
        if t in near:
            continue
        if dl[t] > max(0.03, mdl + 12 * ddl) and dl[t] > 4 * max(dl[t - 1], dl[t + 1]):
            joins.append({"s": t, "e": t + 1, "same_scene": True})
    joins.sort(key=lambda j: j["s"])
    # two joins with only a few frames between them are one join (a dip has a cut on each side of the black)
    merged = []
    for j in joins:
        gap = range(merged[-1]["e"], j["s"] + 1) if merged else range(0)
        blank = len(gap) and all(stats[i, 0] < 0.06 or stats[i, 0] > 0.92 for i in gap)
        if merged and (j["s"] - merged[-1]["e"] <= max(3, int(fps * 0.2)) or (blank and len(gap) <= fps * 1.5)):
            m = merged[-1]
            merged[-1] = {"s": m["s"], "e": max(m["e"], j["e"]), "gradual": True}
            continue
        merged.append(j)
    # the same picture on both sides (a flicker, a flash, a fast zoom on one shot) is not a join
    kept = []
    for j in merged:
        a, b = max(0, j["s"] - 1), min(len(gray) - 1, j["e"] + 1)
        dark = stats[j["s"]: j["e"] + 1, 0].min() < 0.07
        if not j.get("same_scene") and not dark and _is_camera_move(gray, a, b):
            continue
        kept.append(j)
    return kept, c


def _shift(img, dx, dy):
    return np.roll(np.roll(img, int(round(dy)), axis=0), int(round(dx)), axis=1)


def _is_camera_move(gray, a, b):
    """A pan, tilt or zoom drifts the histogram too; a join should not be the same picture moved."""
    g = gray.astype(np.float32) / 255
    A, B = g[a], g[b]
    # compare shapes, not brightness: a flicker or a flash on the same picture is not a new shot
    A = (A - A.mean()) / (A.std() + 0.02) * 0.2
    B = (B - B.mean()) / (B.std() + 0.02) * 0.2
    base = float(np.abs(A - B).mean())
    h, w = A.shape
    m = (slice(h // 6, h - h // 6), slice(w // 6, w - w // 6))
    best = base
    win = np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)
    for s in (1.0, 1.06, 1.12, 1.2, 1.35, 1.5, 1.75, 2.0):
        for X, Y in ((A, B), (B, A)):
            Z = _zoom(X, s) if s != 1.0 else X
            dx, dy, _ = _phase(Z, Y, win)
            best = min(best, float(np.abs(_shift(Z, dx, dy) - Y)[m].mean()))
    return best < 0.035 or best < 0.35 * base


def _zoom(img, s):
    h, w = img.shape
    yy = ((np.arange(h) - h / 2) / s + h / 2).clip(0, h - 1).astype(int)
    xx = ((np.arange(w) - w / 2) / s + w / 2).clip(0, w - 1).astype(int)
    return img[yy][:, xx]


def classify(j, gray, stats, mot, fps):
    g = gray.astype(np.float32) / 255
    n = len(g)
    a, b = max(0, j["s"] - 1), min(n - 1, j["e"] + 1)
    A, B = g[a], g[b]
    span = list(range(j["s"] + 1, j["e"]))  # frames strictly inside the join
    lum = stats[:, 0]
    out = {"frames": j["e"] - j["s"], "seconds": round((j["e"] - j["s"]) / fps, 3)}
    pad = int(fps * 0.4)
    lo, hi = lum[max(0, j["s"] - pad): j["e"] + pad + 1].min(), lum[max(0, j["s"] - pad): j["e"] + pad + 1].max()
    ea, eb = lum[max(0, j["s"] - pad - int(fps * 0.3))], lum[min(n - 1, j["e"] + pad + int(fps * 0.3))]
    edge = min(ea, eb), max(ea, eb)
    if j.get("same_scene"):
        s, gain = best_scale(A, B)
        out["kind"] = "punch-in" if s > 1.04 and gain > 0.3 else ("pull-back cut" if s < 0.96 and gain > 0.3 else "jump cut")
        if s != 1.0:
            out["scale"] = round(s, 2)
        return out
    if lo < 0.07 and lo < edge[0] - 0.08:
        out["kind"] = "dip to black" if out["seconds"] >= 0.2 else "black flash"
        return out
    if hi > 0.82 and hi > edge[1] + 0.12:
        out["kind"] = "dip to white" if out["seconds"] >= 0.25 else "white flash"
        return out
    bright = lum[j["s"]: j["e"] + 1]
    if len(bright) and bright.max() > max(lum[a], lum[b]) + 0.15:
        out["kind"] = "bright flash" if out["seconds"] < 0.25 else "dip through a bright colour"
        return out
    if len(span) < 2:
        out["kind"] = "cut"
        sc, gain = best_scale(A, B)
        if gain > 0.35 and sc != 1.0:
            if True:
                out["kind"] = "snap zoom or punch-in (same picture, closer)" if sc > 1 else "cut back out (same picture, wider)"
                out["scale"] = round(sc, 2)
        return out
    con = stats[:, 1]
    if con[j["s"]: j["e"] + 1].min() < 0.4 * min(con[a], con[b]) and min(con[a], con[b]) > 0.08:
        out["kind"] = "dip through a flat colour"
        return out
    diff = np.abs(A - B)
    sel = diff > 0.12
    if sel.mean() < 0.03:
        sel = diff > 0.05
    if sel.mean() < 0.02:
        out["kind"] = "gradual (unclear: the two pictures are alike)"
        return out
    h, w = A.shape
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.sqrt(((xx - w / 2) / w) ** 2 + ((yy - h / 2) / w) ** 2)
    d = (A - B)[sel]
    al = {m: float(np.dot((g[m] - B)[sel], d) / (np.dot(d, d) + 1e-9)) for m in span}
    mids = [m for m in span if abs(al[m] - 0.5) < 0.2] or [min(span, key=lambda m: abs(al[m] - 0.5))]
    resid, split, rad, cent = [], [], [], []
    for m in mids:
        M = g[m]
        resid.append(float(np.abs(M - (al[m] * A + (1 - al[m]) * B))[sel].mean() / (diff[sel].mean() + 1e-9)))
        # each changed pixel: still the old picture, already the new one, or a mix of both (a dissolve)
        eA, eB = _box(np.abs(M - A)), _box(np.abs(M - B))
        isA, isB = sel & (eA < 0.5 * eB), sel & (eB < 0.5 * eA)
        split.append(float((isA | isB).sum() / sel.sum()))
        if isA.sum() > 20 and isB.sum() > 20:
            def share(region):
                k = (isA | isB) & region
                return float(isB[k].mean()) if k.sum() > 10 else 0.5
            rad.append({"left": share(xx < w / 3), "right": share(xx > 2 * w / 3), "top": share(yy < h / 3),
                        "bottom": share(yy > 2 * h / 3), "center": share(r < 0.12), "edges": share(r > 0.3)})
    sharp = stats[:, 4]
    blur = float(sharp[j["s"]: j["e"] + 1].min() / (min(sharp[a], sharp[b]) + 1e-9))
    mm = mot[j["s"]: j["e"]] if len(mot) else np.zeros((0, 6))
    mm = mm[mm[:, 5] > 0.08] if len(mm) else mm

    def steady_move(col, lim):
        if len(mm) < 2:
            return 0.0
        v = mm[:, col]
        sign = np.sign(np.median(v))
        return float(np.median(np.abs(v))) if sign and (np.sign(v) == sign).mean() >= 0.7 and np.median(np.abs(v)) > lim else 0.0
    tx, ty, zm = steady_move(0, 0.01), steady_move(1, 0.01), steady_move(2, 0.008)
    sp = float(np.median(split))
    out.update({"blend_fit": round(float(np.median(resid)), 2), "split_share": round(sp, 2), "blur_ratio": round(blur, 2)})
    if zm >= 0.02 and zm > max(tx, ty):
        out["kind"] = "zoom transition" + (" with blur" if blur < 0.45 else "")
        out["zoom"] = "in" if np.median(mm[:, 2]) > 0 else "out"
        return out
    if tx or ty:
        out["kind"] = "push or slide" if blur > 0.5 else "whip or push"
        out["moves"] = _dir(mm)
        return out
    if (sp >= 0.4 or (sp >= 0.3 and np.median(resid) >= 0.15)) and rad:
        z = {k: float(np.median([x[k] for x in rad])) for k in rad[0]}
        opts = {"right": z["right"] - z["left"], "left": z["left"] - z["right"], "bottom": z["bottom"] - z["top"],
                "top": z["top"] - z["bottom"], "center outward (iris, box or doors opening)": z["center"] - z["edges"],
                "edges inward (iris, box or doors closing)": z["edges"] - z["center"]}
        best = max(opts, key=opts.get)
        out["kind"] = "wipe"
        out["from"] = best if opts[best] > 0.3 else "unclear (radial, clock or shaped: look at the frames)"
        return out
    if zm:
        out["kind"] = "zoom transition"
        out["zoom"] = "in" if np.median(mm[:, 2]) > 0 else "out"
        return out
    if np.median(resid) < 0.3:
        out["kind"] = "blur dissolve" if blur < 0.45 else "cross-dissolve"
        return out
    if blur < 0.45:
        out["kind"] = "blur transition"
        return out
    out["kind"] = "gradual (other: look at the frames)"
    return out


def _box(x, k=2):
    p = np.pad(x, k, mode="edge")
    c = p.cumsum(0).cumsum(1)
    c = np.pad(c, ((1, 0), (1, 0)))
    n = 2 * k + 1
    return (c[n:, n:] - c[:-n, n:] - c[n:, :-n] + c[:-n, :-n]) / (n * n)


def _dir(mm):
    sx, sy = float(mm[:, 0].sum()), float(mm[:, 1].sum())
    if abs(sx) >= abs(sy):
        return "picture moves left" if sx < 0 else "picture moves right"
    return "picture moves up" if sy < 0 else "picture moves down"


def dist_frames(A, B):
    return float(np.abs(A - B).mean() / (0.5 * (A.std() + B.std()) + 1e-6))


def best_scale(A, B):
    base = float(np.abs(A - B).mean())
    best, s_best = base, 1.0
    for s in np.arange(1.05, 1.81, 0.05):
        for x, y, sign in ((A, B, 1), (B, A, -1)):
            d = float(np.abs(_zoom(x, s) - y).mean())
            if d < best:
                best, s_best = d, (s if sign > 0 else 1 / s)
    return round(float(s_best), 3), (base - best) / (base + 1e-9)


# ------------------------------------------------------------------ shots
def describe_shot(a, b, mot, stats, gray, fps, w_px):
    seg = mot[a:max(a, b - 1)]
    out = {}
    if len(seg) >= 3:
        good = seg[seg[:, 5] > 0.12]
        use = good if len(good) >= max(3, len(seg) // 3) else seg
        tx, ty = float(use[:, 0].sum() * len(seg) / len(use)), float(use[:, 1].sum() * len(seg) / len(use))
        zoom = float(np.exp(np.log1p(use[:, 2].clip(-0.5, 0.5)).sum() * len(seg) / len(use)))
        roll = float(np.degrees(use[:, 3].sum() * len(seg) / len(use)))
        k = min(len(seg), max(3, int(fps * 0.5)))
        sm = np.convolve(seg[:, 0], np.ones(k) / k, mode="same")
        shake = float(np.std(seg[:, 0] - sm) * 100)
        def cons(v):
            return round(float(abs(v.sum()) / (np.abs(v).sum() + 1e-9)), 2)
        out["steadiness"] = {"pan_x": cons(use[:, 0]), "pan_y": cons(use[:, 1]), "zoom": cons(use[:, 2]),
                             "roll": cons(use[:, 3])}
        out.update({"pan_x_pct": round(tx * 100, 1), "pan_y_pct": round(ty * 100, 1), "zoom": round(zoom, 3),
                    "roll_deg": round(roll, 1), "shake_pct": round(shake, 2),
                    "fit_residual": round(float(np.median(seg[:, 4]) * 100), 2)})
        # the fastest scale change over 0.3 s tells a crash or snap zoom from a slow push
        k3 = max(2, int(fps * 0.3))
        ls = np.log1p(seg[:, 2].clip(-0.5, 0.5))
        if len(ls) >= k3:
            fast = np.convolve(ls, np.ones(k3), mode="valid")
            i = int(np.abs(fast).argmax())
            out["fastest_zoom_0_3s"] = round(float(np.exp(fast[i])), 3)
            out["fastest_zoom_at"] = round((a + i + k3 / 2) / fps, 2)
    g = gray[a:b].astype(np.float32) / 255
    if len(g) >= 2:
        d = np.abs(np.diff(g, axis=0)).mean(axis=(1, 2))
        out["activity"] = round(float(d.mean() * 100), 2)
        still = d < 0.0015
        runs, cur, start = [], 0, 0
        for i, s in enumerate(still):
            if s:
                cur, start = (cur + 1, start) if cur else (1, i)
            else:
                if cur:
                    runs.append((start, cur))
                cur = 0
        if cur:
            runs.append((start, cur))
        moving_before = [r for r in runs if r[1] >= fps * 0.3 and r[0] > fps * 0.2 and d[: r[0]].mean() > 0.006]
        if moving_before:
            r0 = max(moving_before, key=lambda r: r[1])
            out["hold"] = {"at": round((a + r0[0] + 1) / fps, 2), "seconds": round(r0[1] / fps, 2)}
        if len(d) >= fps:
            k = max(2, int(fps * 0.3))
            w = np.convolve(d, np.ones(k) / k, mode="valid")
            lo, hi = float(np.percentile(w, 10)), float(np.percentile(w, 90))
            if hi > 0.01 and hi > 4 * max(lo, 0.0015) and "hold" not in out:
                out["speed_change"] = {"slow_at": round((a + int(w.argmin()) + k / 2) / fps, 2),
                                       "fast_at": round((a + int(w.argmax()) + k / 2) / fps, 2),
                                       "ratio": round(hi / max(lo, 0.0015), 1)}
    st = stats[a:b]
    out["look"] = look(st, gray[a:b])
    out["camera"] = camera_words(out)
    return out


def camera_words(m):
    words = []
    if "zoom" not in m:
        return ["too short to measure"]
    st = m["steadiness"]
    if m.get("fastest_zoom_0_3s", 1) >= 1.25:
        words.append(f"fast zoom in (x{m['fastest_zoom_0_3s']} in 0.3 s at {m['fastest_zoom_at']} s)")
    elif m.get("fastest_zoom_0_3s", 1) <= 0.8:
        words.append(f"fast zoom out (x{m['fastest_zoom_0_3s']} in 0.3 s at {m['fastest_zoom_at']} s)")
    elif m["zoom"] >= 1.03 and st["zoom"] >= 0.6 and m["fit_residual"] < 0.3:
        words.append(f"slow push in (x{m['zoom']})")
    elif m["zoom"] <= 0.97 and st["zoom"] >= 0.6 and m["fit_residual"] < 0.3:
        words.append(f"slow pull out (x{m['zoom']})")
    if abs(m["pan_x_pct"]) >= 8 and st["pan_x"] >= 0.5:
        words.append(("content moves left (pan right)" if m["pan_x_pct"] < 0 else "content moves right (pan left)")
                     + f" {abs(m['pan_x_pct'])}% of width")
    if abs(m["pan_y_pct"]) >= 8 and st["pan_y"] >= 0.5:
        words.append(("content moves up (tilt down)" if m["pan_y_pct"] < 0 else "content moves down (tilt up)")
                     + f" {abs(m['pan_y_pct'])}% of width")
    if abs(m["roll_deg"]) >= 4 and st["roll"] >= 0.6 and m["fit_residual"] < 0.3:
        words.append(f"rotates {m['roll_deg']} deg")
    if m["shake_pct"] >= 0.25:
        words.append(f"shake or handheld ({m['shake_pct']}% jitter)")
    if m.get("hold"):
        words.append(f"picture holds still {m['hold']['seconds']} s at {m['hold']['at']} s (freeze?)")
    if m.get("speed_change"):
        sc = m["speed_change"]
        words.append(f"motion speed changes x{sc['ratio']} (slow near {sc['slow_at']} s, fast near {sc['fast_at']} s)")
    if not words:
        words.append("locked off" if m.get("activity", 0) < 0.4 else "static frame, subject moves")
    return words


def look(st, gray):
    lum, con, sat, warm = (float(np.median(st[:, i])) for i in range(4))
    g = gray.astype(np.float32) / 255
    h = g.shape[1]
    rows = g.mean(axis=(0, 2))
    bar_t = int(np.argmax(rows > 0.06)) if (rows > 0.06).any() else 0
    bar_b = int(np.argmax(rows[::-1] > 0.06)) if (rows > 0.06).any() else 0
    mid = g[:, h // 3: 2 * h // 3, g.shape[2] // 3: 2 * g.shape[2] // 3].mean()
    corners = np.mean([g[:, : h // 6, : g.shape[2] // 6].mean(), g[:, : h // 6, -g.shape[2] // 6:].mean(),
                       g[:, -h // 6:, : g.shape[2] // 6].mean(), g[:, -h // 6:, -g.shape[2] // 6:].mean()])
    out = {"brightness": round(lum, 2), "contrast": round(con, 2), "saturation": round(sat, 2),
           "warmth": round(warm, 3)}
    words = []
    if sat < 0.06:
        words.append("black and white or nearly")
    elif sat > 0.45:
        words.append("very saturated")
    if warm > 0.06:
        words.append("warm")
    elif warm < -0.06:
        words.append("cool")
    if lum < 0.25:
        words.append("dark")
    elif lum > 0.7:
        words.append("bright")
    if con > 0.3:
        words.append("high contrast")
    elif con < 0.12:
        words.append("flat")
    if bar_t > h * 0.05 and bar_b > h * 0.05:
        words.append(f"black bars top and bottom ({round(100 * bar_t / h)}% / {round(100 * bar_b / h)}%)")
    if mid > 0.15 and corners < mid * 0.7:
        words.append(f"dark corners (corners {round(float(corners / mid), 2)} of center)")
    out["words"] = words
    return out


# ------------------------------------------------------------------ overlays
def persistent(gray, joins):
    """Regions that stay the same across joins while the rest of the frame changes: logos, captions, frames."""
    g = gray.astype(np.float32) / 255
    n, h, w = g.shape
    gy, gx = 12, max(4, int(round(12 * w / h)))
    keep = np.zeros((gy, gx))
    used = 0
    for j in joins:
        a, b = max(0, j["s"] - 1), min(n - 1, j["e"] + 1)
        d = np.abs(g[a] - g[b])
        if d.mean() < 0.08:
            continue
        used += 1
        dd = d[: h - h % gy, : w - w % gx].reshape(gy, h // gy, gx, w // gx).mean(axis=(1, 3))
        tex = g[b][: h - h % gy, : w - w % gx].reshape(gy, h // gy, gx, w // gx).std(axis=(1, 3))
        keep += (dd < 0.025) & (tex > 0.02)
    if used < 2:
        return []
    mask = keep >= max(2, 0.6 * used)
    out = []
    seen = np.zeros_like(mask)
    for y in range(gy):
        for x in range(gx):
            if mask[y, x] and not seen[y, x]:
                stack, cells = [(y, x)], []
                seen[y, x] = True
                while stack:
                    cy, cx = stack.pop()
                    cells.append((cy, cx))
                    for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                        if 0 <= ny < gy and 0 <= nx < gx and mask[ny, nx] and not seen[ny, nx]:
                            seen[ny, nx] = True
                            stack.append((ny, nx))
                ys, xs = [c[0] for c in cells], [c[1] for c in cells]
                out.append({"x_pct": round(100 * min(xs) / gx), "y_pct": round(100 * min(ys) / gy),
                            "w_pct": round(100 * (max(xs) - min(xs) + 1) / gx),
                            "h_pct": round(100 * (max(ys) - min(ys) + 1) / gy),
                            "kept_through": f"{int(keep[ys, xs].min())} of {used} joins"})
    return out


def overlay_events(gray, E, joins, fps):
    """Moments where one horizontal band changes while the rest stays: text, stickers, graphics coming or going."""
    g = gray.astype(np.float32) / 255
    n, h, w = g.shape
    bands = np.array_split(np.arange(h), BANDS)
    d = np.abs(np.diff(g, axis=0))
    bd = np.stack([d[:, b, :].mean(axis=(1, 2)) for b in bands], axis=1)  # (n-1, BANDS)
    near = np.zeros(n - 1, bool)
    for j in joins:
        near[max(0, j["s"] - 2): min(n - 1, j["e"] + 2)] = True
    med = np.median(bd, axis=0) + 1e-4
    events = []
    for t in range(n - 1):
        if near[t]:
            continue
        hit = [k for k in range(BANDS) if bd[t, k] > max(0.012, 6 * med[k])]
        if not hit or len(hit) > BANDS - 2:
            continue
        rest = [k for k in range(BANDS) if k not in hit]
        if bd[t, rest].mean() > 0.5 * bd[t, hit].mean():
            continue
        lo, hi = max(0, t - 2), min(n - 1, t + 3)
        de = float(E[hi, hit].mean() - E[lo, hit].mean())
        events.append({"t": round((t + 1) / fps, 3), "bands": hit, "edge_change": round(de, 3)})
    merged = []
    for e in events:
        touch = merged and any(abs(x - y) <= 1 for x in e["bands"] for y in merged[-1]["bands"])
        if touch and e["t"] - merged[-1]["t_end"] <= 0.1:
            m = merged[-1]
            m["t_end"] = e["t"]
            m["bands"] = sorted(set(m["bands"]) | set(e["bands"]))
            m["edge_change"] = round(m["edge_change"] + e["edge_change"], 3)
            continue
        merged.append({"t": e["t"], "t_end": e["t"], "bands": e["bands"], "edge_change": e["edge_change"]})
    names = ["top", "upper", "upper middle", "lower middle", "lower", "bottom"]
    for m in merged:
        m["area"] = names[m["bands"][0]] if len(m["bands"]) == 1 else f"{names[m['bands'][0]]} to {names[m['bands'][-1]]}"
        m["guess"] = ("detail appears (text or graphic in?)" if m["edge_change"] > 0.01 else
                      "detail goes (text or graphic out?)" if m["edge_change"] < -0.01 else "changes in place")
    return merged


# ------------------------------------------------------------------ audio
SR = 22050
HOP = 256


def stft(x, n=1024):
    if len(x) < n:
        return np.zeros((1, n // 2 + 1), np.float32)
    k = 1 + (len(x) - n) // HOP
    idx = np.arange(n)[None, :] + HOP * np.arange(k)[:, None]
    return np.abs(np.fft.rfft(x[idx] * np.hanning(n).astype(np.float32), axis=1)).astype(np.float32)


def audio(video, info, cut_times, visual_marks):
    if not info["has_audio"]:
        return {"has_audio": False}
    x = decode_audio(video, SR)
    if len(x) < SR // 2:
        return {"has_audio": False}
    out = {"has_audio": True, "lufs": lufs(video)}
    rms = np.sqrt(np.convolve(x ** 2, np.ones(SR // 10) / (SR // 10), mode="valid")[:: SR // 20] + 1e-12)
    out["silent_share"] = round(float((20 * np.log10(rms + 1e-9) < -50).mean()), 2)
    if out["silent_share"] > 0.95:
        out["note"] = "the track is silent"
        return out
    S = stft(x)
    freqs = np.fft.rfftfreq(1024, 1 / SR)
    logS = np.log1p(S * 10)
    flux = np.maximum(0, np.diff(logS, axis=0)).sum(axis=1)
    flux = np.concatenate([[0], flux])
    ft = HOP / SR
    env = flux - np.convolve(flux, np.ones(9) / 9, mode="same")
    env = np.maximum(env, 0)
    # tempo from the autocorrelation of the onset envelope
    e = env - env.mean()
    ac = np.correlate(e, e, mode="full")[len(e) - 1:]
    ac /= ac[0] + 1e-9
    lags = np.arange(len(ac))
    music = {"beat": False}
    # tempo candidates: autocorrelation peaks between 60 and 200 BPM, folded into 70-180
    lo_l, hi_l = int(60 / 200 / ft), int(60 / 60 / ft) + 1
    peaks = [L for L in range(max(2, lo_l), min(hi_l, len(ac) - 1)) if ac[L] >= ac[L - 1] and ac[L] >= ac[L + 1] and ac[L] > 0.05]
    cands = []
    for L in sorted(peaks, key=lambda L: -ac[L]):
        bpm_ = 60 / (L * ft)
        while bpm_ < 70:
            bpm_ *= 2
        while bpm_ > 180:
            bpm_ /= 2
        if all(abs(bpm_ - c[0]) / c[0] > 0.04 for c in cands):
            cands.append((bpm_, float(ac[L])))
        if len(cands) == 3:
            break
    if cands:
        music.update({"bpm": round(cands[0][0], 1), "beat_strength": round(cands[0][1], 2)})
        listed = []
        for k, (bpm_, strength) in enumerate(cands):
            bpm_, beats = beat_grid(env, bpm_, ft)
            item = {"bpm": round(bpm_, 1), "strength": round(strength, 2)}
            if cut_times and strength >= 0.12:
                bt = np.array(beats)
                dd = np.array([np.min(np.abs(bt - c)) for c in cut_times])
                item["cuts_on_beat"] = f"{int((dd < 0.07).sum())} of {len(cut_times)}"
                item["cuts_on_beat_share"] = round(float((dd < 0.07).mean()), 2)
                item["by_chance_share"] = round(min(1.0, 2 * 0.07 / (60 / bpm_)), 2)
            listed.append(item)
            item["_beats"] = beats
            if k == 0 and strength >= 0.12:
                music.update({"beat": True, "bpm": round(bpm_, 1), "beats": [round(x, 3) for x in beats[:600]]})
        music["tempo_candidates"] = listed
        fits = [c for c in listed if c.get("cuts_on_beat_share", 0) >= max(0.6, 2 * c.get("by_chance_share", 1))]
        if fits:
            best = max(fits, key=lambda c: c["cuts_on_beat_share"])
            music["cuts_follow_beat"] = f"{best['cuts_on_beat']} cuts on a {best['bpm']} BPM grid (by chance about {best['by_chance_share']})"
            if best is not listed[0]:
                music["beats"] = [round(x, 3) for x in best["_beats"][:600]]
                music["bpm"] = best["bpm"]
        for c in listed:
            c.pop("_beats", None)
    out["music"] = music
    # speech-like windows: energy in the voice band that rises and falls at syllable rate (3 to 8 per second)
    vb = (freqs >= 300) & (freqs <= 3400)
    band = S[:, vb].sum(axis=1)
    total = S.sum(axis=1) + 1e-9
    win = int(2 / ft)
    speech = []
    for s in range(0, max(1, len(band) - win), win // 2):
        seg = band[s:s + win]
        if len(seg) < win // 2 or seg.mean() < 1e-3:
            speech.append(False)
            continue
        m = np.abs(np.fft.rfft(seg - seg.mean()))
        mf = np.fft.rfftfreq(len(seg), ft)
        syl = m[(mf >= 3) & (mf <= 8)].sum() / (m[(mf >= 0.5) & (mf <= 20)].sum() + 1e-9)
        share = float(band[s:s + win].sum() / total[s:s + win].sum())
        speech.append(bool(syl > 0.42 and share > 0.5))
    out["speech_like_share"] = round(float(np.mean(speech)) if speech else 0.0, 2)
    # salient transients: candidate sound effects
    m, dv = mad(env)
    peaks, last = [], -1
    for i in range(1, len(env) - 1):
        if env[i] >= env[i - 1] and env[i] > env[i + 1] and env[i] > m + 8 * dv:
            lo, hi = max(0, i - int(1 / ft)), min(len(env), i + int(1 / ft))
            if env[i] < 2.5 * np.median(env[lo:hi]) + 1e-6:
                continue
            if last >= 0 and (i - last) * ft < 0.12:
                if env[i] > env[last]:
                    peaks[-1] = i
                    last = i
                continue
            peaks.append(i)
            last = i
    beats = np.array(music.get("beats", []))
    sfx = []
    marks = np.array(sorted(visual_marks)) if visual_marks else np.array([])
    for i in peaks[:200]:
        t = i * ft
        fr = S[i: i + 6]
        cen = float((fr.sum(axis=0) * freqs).sum() / (fr.sum() + 1e-9))
        lvl = logS[i: i + int(0.6 / ft)].sum(axis=1)
        tail = int(np.argmax(lvl < lvl[0] * 0.35)) * ft if (lvl < lvl[0] * 0.35).any() else 0.6
        kind = ("low hit or boom" if cen < 350 else "click, tick or pop" if cen > 3500 and tail < 0.15 else
                "bright hit or whoosh" if cen > 2500 else "hit")
        ev = {"t": round(t, 3), "kind": kind, "centroid_hz": int(cen), "tail_s": round(tail, 2)}
        if len(beats) and np.min(np.abs(beats - t)) < 0.05:
            ev["on_beat"] = True
        if len(marks):
            k = int(np.argmin(np.abs(marks - t)))
            if abs(marks[k] - t) <= 0.2:
                ev["near_visual"] = round(float(marks[k]), 3)
        sfx.append(ev)
    # swells: broadband level rising steadily for 0.3 to 2 s (risers, whooshes into a moment)
    lv = 20 * np.log10(np.convolve(total, np.ones(4) / 4, mode="same") + 1e-6)
    lv = np.maximum(lv, lv.max() - 60)  # silence counts as 60 dB under the loudest moment, not minus infinity
    swells, i = [], 0
    step = int(0.05 / ft)
    while i < len(lv) - step:
        j = i
        while j + step < len(lv) and lv[j + step] >= lv[j] - 0.5:
            j += step
        dur = (j - i) * ft
        if 0.3 <= dur <= 2.5 and lv[j] - lv[i] >= 12 and lv[j] > lv.max() - 30:
            swells.append({"from": round(i * ft, 2), "peak": round(j * ft, 2), "rise_db": round(float(lv[j] - lv[i]), 1)})
            i = j
        i += step
    out["transients"] = sfx
    out["swells"] = swells[:60]
    return out


def beat_grid(env, bpm, ft):
    """Refine a tempo (within 3 %) and its phase so the beats sit on onsets, then snap each beat to its onset.

    Autocorrelation lags are 11.6 ms apart, which leaves a tempo up to 2 % off; over 15 s that drifts the grid
    by a tenth of a second, enough to miss every cut. Returns (refined bpm, beat times)."""
    envs = np.maximum.reduce([np.roll(env, k) for k in (-2, -1, 0, 1, 2)])
    med = float(np.median(env[env > 0])) + 1e-9 if (env > 0).any() else 1.0
    le = np.log1p(envs / med)
    best = (-1.0, bpm, 0.0)
    for b in np.arange(bpm * 0.97, bpm * 1.03, 0.1):
        period = 60 / b / ft
        for ph in np.arange(0, period, 1.0):
            idx = np.round(np.arange(ph, len(env), period)).astype(int)
            idx = idx[idx < len(env)]
            v = float(le[idx].mean())
            if v > best[0]:
                best = (v, b, ph)
    _, bpm, phase = best
    period = 60 / bpm / ft
    beats = []
    for x in np.arange(phase, len(env), period):
        i = int(round(x))
        lo, hi = max(0, i - 2), min(len(env), i + 3)
        if hi > lo:
            beats.append((lo + int(np.argmax(env[lo:hi]))) * ft)
    return float(bpm), beats


# ------------------------------------------------------------------ main
def main():
    utf8_stdout()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("video")
    p.add_argument("--out", required=True, help="folder for breakdown.json and the sheets")
    p.add_argument("--max-seconds", type=float, default=300, help="analyse only the first N seconds (default 300)")
    a = p.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    info = probe(a.video)
    dur = min(info["duration"], a.max_seconds) if info["duration"] else a.max_seconds
    fps = min(30.0, info["fps"] or 30.0)
    if dur * fps > 9000:
        fps = 9000 / dur
    gray, H, L, stats, E = features(a.video, info, fps, dur)
    n = len(gray)
    mot = motion(gray)
    raw, change = find_joins(H, L, gray, stats, fps)
    joins = []
    for j in raw:
        c = classify(j, gray, stats, mot, fps)
        c.update({"start": round((j["s"] + 1) / fps, 3), "end": round((j["e"] + 0.0) / fps, 3) if j["e"] > j["s"] + 1
                  else round((j["s"] + 1) / fps, 3)})
        c["at"] = round((c["start"] + c["end"]) / 2, 3)
        c["_s"], c["_e"] = j["s"], j["e"]
        joins.append(c)
    # shots run between joins
    bounds = [0] + [((j["_s"] + j["_e"]) // 2) + 1 for j in joins] + [n]
    shots = []
    for k in range(len(bounds) - 1):
        a0, b0 = bounds[k], bounds[k + 1]
        if b0 - a0 < 1:
            continue
        s = {"n": len(shots) + 1, "start": round(a0 / fps, 3), "end": round(b0 / fps, 3),
             "seconds": round((b0 - a0) / fps, 3)}
        s["in"] = joins[k - 1]["kind"] if k > 0 else "start"
        s.update(describe_shot(a0, b0, mot, stats, gray, fps, gray.shape[2]))
        shots.append(s)
    lengths = np.array([s["seconds"] for s in shots])
    # a short join (cut, flash) lands where the new picture starts; a long one is felt at its middle
    cut_times = [j["start"] if j["seconds"] < 0.25 else j["at"] for j in joins]
    events = overlay_events(gray, E, raw, fps)
    zoom_marks = [s["fastest_zoom_at"] for s in shots if abs(math.log(s.get("fastest_zoom_0_3s", 1))) > 0.15]
    marks = cut_times + [j["start"] for j in joins] + [e["t"] for e in events] + zoom_marks
    aud = audio(a.video, info, cut_times, marks)
    pacing = {"shots": len(shots), "joins": len(joins),
              "cuts_per_minute": round(len(joins) / (dur / 60), 1) if dur else None,
              "median_shot_s": round(float(np.median(lengths)), 2) if len(lengths) else None,
              "shortest_s": round(float(lengths.min()), 2) if len(lengths) else None,
              "longest_s": round(float(lengths.max()), 2) if len(lengths) else None,
              "joins_in_first_3s": sum(1 for t in cut_times if t < 3),
              "regularity": (round(float(lengths.std() / lengths.mean()), 2) if len(lengths) > 2 else None)}
    kinds = {}
    for j in joins:
        kinds[j["kind"]] = kinds.get(j["kind"], 0) + 1
    pacing["join_kinds"] = kinds
    w, h = info["width"] or 0, info["height"] or 0
    fmt = ("vertical 9:16" if h and abs(w / h - 9 / 16) < 0.03 else "horizontal 16:9" if h and abs(w / h - 16 / 9) < 0.03
           else "square" if h and abs(w / h - 1) < 0.03 else f"{w}x{h}")
    text_bands = {}
    for e in events:
        text_bands[e["area"]] = text_bands.get(e["area"], 0) + 1
    result = {"tool": f"video-breakdown analyze.py {VERSION}", "video": str(Path(a.video).resolve()),
              "format": {"width": w, "height": h, "shape": fmt, "fps": info["fps"], "duration": round(info["duration"], 3),
                         "analysed_s": round(n / fps, 2), "analysis_fps": round(fps, 2)},
              "pacing": pacing,
              "joins": [{k: v for k, v in j.items() if not k.startswith("_")} for j in joins],
              "shots": shots,
              "overlays": {"persistent": persistent(gray, raw), "events": events, "events_by_area": text_bands},
              "audio": aud}
    write_json(out / "breakdown.json", result)
    sheets = draw(a.video, info, result, out)
    # summary for the terminal
    print(f"{fmt}, {info['duration']:.2f} s at {info['fps']} fps; {len(shots)} shots, {len(joins)} joins {kinds}")
    print(f"pacing: median shot {pacing['median_shot_s']} s, {pacing['cuts_per_minute']} joins/min")
    for j in result["joins"]:
        extra = ", ".join(f"{k} {j[k]}" for k in ("from", "moves", "scale") if k in j)
        print(f"  join {j['at']:7.2f}s  {j['kind']:<24} {j['seconds']} s {extra}")
    for s in shots:
        print(f"  shot {s['n']:>2} {s['start']:6.2f}-{s['end']:6.2f}s  {'; '.join(s['camera'])}  | look: {', '.join(s['look']['words']) or '-'}")
    print(f"overlay events: {len(events)} {text_bands}; persistent regions: {len(result['overlays']['persistent'])}")
    if aud.get("has_audio"):
        mu = aud.get("music", {})
        print(f"audio: {aud.get('lufs')} LUFS, speech-like {aud.get('speech_like_share')}, "
              f"tempo {[(c['bpm'], c['strength'], c.get('cuts_on_beat', '-')) for c in mu.get('tempo_candidates', [])]}, "
              f"{mu.get('cuts_follow_beat', 'cuts do not follow a beat grid')}, {len(aud.get('transients', []))} transients, "
              f"{len(aud.get('swells', []))} swells")
    else:
        print("audio: none")
    print("->", out / "breakdown.json")
    for s in sheets:
        print("->", s)


def draw(video, info, r, out):
    paths = []
    portrait = (info["height"] or 0) > (info["width"] or 1)
    tw = 150 if portrait else 240
    dur = r["format"]["analysed_s"]
    step = max(1.0, dur / 24)
    ts = list(np.arange(min(0.5, dur / 2), dur, step))
    p = sheet(grab(video, ts, tw, info), [f"{t:.1f}s" for t in ts], out / "overview.png", 8 if portrait else 6)
    if p:
        paths.append(p)
    shots = r["shots"]
    per = 6
    for page in range(0, len(shots), per):
        tiles, labels = [], []
        for s in shots[page:page + per]:
            a, b = s["start"], s["end"]
            for t, tag in ((a + min(0.08, (b - a) / 4), "in"), ((a + b) / 2, "mid"), (b - min(0.08, (b - a) / 4), "out")):
                tiles.append(t)
                labels.append(f"#{s['n']} {tag} {t:.2f}s")
        p = sheet(grab(video, tiles, tw, info), labels, out / f"shots_{page // per + 1:02d}.png", 6 if portrait else 3)
        if p:
            paths.append(p)
    joins = [j for j in r["joins"] if j["kind"] != "cut"]
    for k in range(0, len(joins), 4):
        tiles, labels = [], []
        for j in joins[k:k + 4]:
            a, b = j["start"] - 0.12, j["end"] + 0.12
            for t in np.linspace(a, b, 6):
                tiles.append(float(t))
                labels.append(f"{j['kind'][:14]} {t:.2f}s")
        p = sheet(grab(video, tiles, tw * 3 // 4, info), labels, out / f"joins_{k // 4 + 1:02d}.png", 6)
        if p:
            paths.append(p)
    ev = r["overlays"]["events"][:18]
    if ev:
        tiles, labels = [], []
        for e in ev:
            for t, tag in ((e["t"] - 0.1, "before"), (e["t_end"] + 0.12, "after")):
                tiles.append(t)
                labels.append(f"{tag} {t:.2f}s")
        p = sheet(grab(video, tiles, tw * 3 // 4, info), labels, out / "events.png", 6 if portrait else 4)
        if p:
            paths.append(p)
    return paths


if __name__ == "__main__":
    main()
