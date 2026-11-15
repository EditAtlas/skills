"""Measure a designed background: flat colour, straight gradient (its angle and end colours) or radial glow, with
a grid of sampled colours, at one or more moments.

  background.py VIDEO --at 1.2,4.0 --out work/bg
  background.py VIDEO --at 2.5 --crop 0,0,100,40 --out work/bg      # only the top 40 %

Text, shapes and people in front are left out as well as can be: each grid cell takes its most common colour, and
cells that differ from the fitted gradient are dropped and the fit repeated. Writes background.png (each moment, the
grid of colours, and the fitted background beside it) and background.json. For filmed backgrounds it says so and
gives the average colours only.
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np

from common import die, grab, probe, utf8_stdout


def hexc(c):
    c = np.clip(np.asarray(c, float), 0, 255).round().astype(int)
    return "#%02x%02x%02x" % tuple(c)


def cell_colours(img, gy, gx):
    h, w = img.shape[:2]
    out = np.zeros((gy, gx, 3), np.float32)
    for y in range(gy):
        for x in range(gx):
            c = img[y * h // gy:(y + 1) * h // gy, x * w // gx:(x + 1) * w // gx].reshape(-1, 3)
            q = (c // 12).astype(np.int32)
            key = q[:, 0] * 10000 + q[:, 1] * 100 + q[:, 2]
            vals, counts = np.unique(key, return_counts=True)
            top = vals[np.argmax(counts)]
            out[y, x] = c[key == top].mean(0)
    return out


def fit_linear(cells, keep):
    gy, gx = cells.shape[:2]
    yy, xx = np.mgrid[0:gy, 0:gx]
    u, v = (xx + 0.5) / gx - 0.5, (yy + 0.5) / gy - 0.5
    A = np.stack([np.ones(gy * gx), u.ravel(), v.ravel()], 1)
    m = keep.ravel()
    coef, *_ = np.linalg.lstsq(A[m], cells.reshape(-1, 3)[m], rcond=None)
    pred = (A @ coef).reshape(gy, gx, 3)
    return coef, pred


def fit_radial(cells, keep, aspect):
    gy, gx = cells.shape[:2]
    yy, xx = np.mgrid[0:gy, 0:gx]
    u, v = (xx + 0.5) / gx - 0.5, ((yy + 0.5) / gy - 0.5) / aspect
    best = None
    for cx in np.linspace(-0.3, 0.3, 7):
        for cy in np.linspace(-0.3, 0.3, 7):
            r = np.sqrt((u - cx) ** 2 + (v - cy / aspect) ** 2)
            A = np.stack([np.ones(gy * gx), r.ravel()], 1)
            m = keep.ravel()
            coef, *_ = np.linalg.lstsq(A[m], cells.reshape(-1, 3)[m], rcond=None)
            pred = (A @ coef).reshape(gy, gx, 3)
            err = float(np.abs(pred - cells)[keep].mean())
            if best is None or err < best[0]:
                best = (err, cx, cy, coef, pred)
    return best


def describe(cells, aspect):
    gy, gx = cells.shape[:2]
    keep = np.ones((gy, gx), bool)
    for _ in range(3):
        coef, pred = fit_linear(cells, keep)
        res = np.abs(pred - cells).max(-1)
        keep = res < max(10.0, np.percentile(res[keep], 75) * 2)
    lin_err = float(np.abs(pred - cells)[keep].mean())
    covered = 1 - keep.mean()
    rad = fit_radial(cells, keep, aspect)
    g = coef[1:]  # colour change per unit across (x) and down (y)
    mag = np.sqrt((g ** 2).sum(1))  # per axis, over channels
    span = float(np.abs(coef[1]).max() + np.abs(coef[2]).max())
    out = {"cells_left_out_pct": round(covered * 100), "fit_error": round(lin_err, 1)}
    if lin_err > 14 and rad[0] > 14:
        out["kind"] = "filmed or textured (no flat or gradient fit)"
        out["average"] = hexc(cells.reshape(-1, 3).mean(0))
        return out, pred
    if rad[0] < 0.7 * lin_err and abs(float(np.abs(rad[3][1]).max())) > 20:
        _, cx, cy, rc, rpred = rad
        centre, edge = rc[0], rc[0] + rc[1] * 0.6
        out.update({"kind": "radial glow" if centre.mean() > edge.mean() else "radial, darker in the middle",
                    "centre_pct": [round((cx + 0.5) * 100), round((cy + 0.5) * 100)],
                    "centre_colour": hexc(centre), "edge_colour": hexc(edge)})
        return out, rpred
    if span < 12:
        out.update({"kind": "flat colour", "colour": hexc(coef[0])})
        return out, pred
    lum = np.array([0.299, 0.587, 0.114])
    dx, dy = float(coef[1] @ lum), float(coef[2] @ lum)
    if abs(dx) < 2 and abs(dy) < 2:  # hue changes, brightness does not: use the largest channel change
        k = int(np.argmax(np.abs(coef[1:]).max(0)))
        dx, dy = float(coef[1][k]), float(coef[2][k])
    ang = math.degrees(math.atan2(dy, dx * aspect)) % 360  # direction the colour moves toward "to"
    if not (-45 < (ang if ang <= 180 else ang - 360) <= 135):  # read it from the top or the left, as gradients are usually written
        ang = (ang + 180) % 360
    a = math.radians(ang)
    corners = [(-0.5, -0.5), (0.5, -0.5), (-0.5, 0.5), (0.5, 0.5)]  # (u across, v down), frame units
    proj = [math.cos(a) * u + math.sin(a) * v * aspect for u, v in corners]
    (u0, v0), (u1, v1) = corners[int(np.argmin(proj))], corners[int(np.argmax(proj))]
    c_from = coef[0] + coef[1] * u0 + coef[2] * v0
    c_to = coef[0] + coef[1] * u1 + coef[2] * v1
    css_deg = round((ang + 90) % 360)
    names = {0: "left to right", 90: "top to bottom", 180: "right to left", 270: "bottom to top", 45: "top-left to bottom-right",
             135: "top-right to bottom-left", 225: "bottom-right to top-left", 315: "bottom-left to top-right"}
    near = min(names, key=lambda k: min(abs(k - ang), 360 - abs(k - ang)))
    out.update({"kind": "straight gradient", "from": hexc(c_from), "to": hexc(c_to), "direction": names[near],
                "angle_deg": round(ang), "css": f"linear-gradient({css_deg}deg, {hexc(c_from)}, {hexc(c_to)})"})
    return out, pred


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--at", required=True, help="seconds, comma separated")
    ap.add_argument("--crop", default="0,0,100,100", help="x,y,w,h in percent")
    ap.add_argument("--grid", default="8x14", help="columns x rows (default 8x14, for 9:16)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    info = probe(a.video)
    times = [float(x) for x in a.at.split(",")]
    gx, gy = [int(x) for x in a.grid.lower().split("x")]
    if (info["width"] or 16) > (info["height"] or 9) and a.grid == "8x14":
        gx, gy = 14, 8
    cx, cy, cw, ch = [float(x) / 100 for x in a.crop.split(",")]
    frames = grab(a.video, times, 480, info)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    results, tiles = [], []
    for t, f in zip(times, frames):
        if f is None:
            die(f"could not read a frame at {t} s")
        h, w = f.shape[:2]
        img = f[int(cy * h):int((cy + ch) * h), int(cx * w):int((cx + cw) * w)].astype(np.float32)
        cells = cell_colours(img, gy, gx)
        aspect = img.shape[0] / img.shape[1]
        r, pred = describe(cells, aspect)
        r["at"] = t
        r["grid"] = [[hexc(c) for c in row] for row in cells]
        results.append(r)
        tiles.append((img, cells, pred))
        line = f"{t} s: {r['kind']}"
        if r["kind"] == "flat colour":
            line += f" {r['colour']}"
        elif r["kind"] == "straight gradient":
            line += f" {r['direction']} ({r['angle_deg']} deg), {r['from']} to {r['to']}; CSS {r['css']}"
        elif r["kind"].startswith("radial"):
            line += f", centre at {r['centre_pct']} % of the frame, {r['centre_colour']} to {r['edge_colour']}"
        else:
            line += f", average {r.get('average')}"
        if r["cells_left_out_pct"] > 30:
            line += f" ({r['cells_left_out_pct']} % of the frame is covered by other things; check the fit in the picture)"
        print(line)
    if len(results) > 1:
        ks = {r["kind"] for r in results}
        cols = [r.get("from", r.get("colour", r.get("centre_colour"))) for r in results]
        print("between moments: " + ("the background stays the same kind" if len(ks) == 1 else "the background changes kind") +
              f"; colours {' -> '.join(c for c in cols if c)}")
    (out / "background.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    try:
        from PIL import Image
        rows = []
        for img, cells, pred in tiles:
            H = 240
            k = H / img.shape[0]
            pic = Image.fromarray(img.astype(np.uint8)).resize((int(img.shape[1] * k), H))
            gc = Image.fromarray(np.clip(cells, 0, 255).astype(np.uint8)).resize(pic.size, Image.NEAREST)
            pf = Image.fromarray(np.clip(pred, 0, 255).astype(np.uint8)).resize(pic.size, Image.BILINEAR)
            row = Image.new("RGB", (pic.width * 3 + 20, H), (40, 40, 40))
            for i, im in enumerate((pic, gc, pf)):
                row.paste(im, (i * (pic.width + 10), 0))
            rows.append(row)
        sheet = Image.new("RGB", (rows[0].width, sum(r.height + 8 for r in rows)), (40, 40, 40))
        y = 0
        for r in rows:
            sheet.paste(r, (0, y))
            y += r.height + 8
        sheet.save(out / "background.png")
        print(f"-> {out / 'background.png'} (frame, grid of colours, fitted background)")
    except ImportError:
        pass


if __name__ == "__main__":
    main()
