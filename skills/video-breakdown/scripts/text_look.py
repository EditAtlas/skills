"""Measure one piece of on-screen text: its colours (solid or gradient, with the stops), outline, glow or shadow,
and, with --text, which free fonts look like it.

  text_look.py VIDEO --at 3.6 --crop 12,24,76,11 --out work/text/title
  text_look.py VIDEO --at 3.6 --crop 12,24,76,11 --text "Caringbah" --fonts sans-heavy,display --out work/text/title
  text_look.py VIDEO --at 3.6 --crop 12,24,76,11 --text-clusters 1,4 --out work/text/title   # fix the text pixels
  text_look.py --list-fonts

--crop is x,y,w,h in percent of the frame. Crop around one line of text with a little background on every side,
at a time when the text has fully come in and is not moving. The script splits the crop's colours into clusters,
takes as text the clusters that do not touch the crop's edge, and draws them in look.png: open it. If the text
pixels are wrong (a face counted as text, a gradient half left out), run again with --text-clusters.

Fonts come from Google Fonts (free, OFL or Apache licensed), downloaded once into a cache folder; that is the only
network use. Each candidate is drawn with the measured fill and outline at the reference's height, with a shape
score. The score is a hint: compare the letter shapes yourself. A font named here is a lookalike, not the font the
creator used, which may be a paid font.
"""
import argparse
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

from common import die, grab, probe, utf8_stdout, write_json

# Free lookalikes, grouped by what the letters look like. "Name:weight"; weight defaults to 400.
FONT_GROUPS = {
    "script-formal": ["Great Vibes", "Pinyon Script", "Alex Brush", "Allura", "Parisienne", "Italianno",
                      "Monsieur La Doulaise", "Rouge Script", "Tangerine:700", "Mr De Haviland"],
    "script-brush": ["Kaushan Script", "Yellowtail", "Damion", "Mr Dafoe", "Marck Script", "Caveat Brush",
                     "Permanent Marker", "Rock Salt"],
    "script-casual": ["Pacifico", "Lobster", "Dancing Script:700", "Satisfy", "Cookie", "Sacramento", "Courgette",
                      "Leckerli One"],
    "handwriting": ["Caveat:600", "Indie Flower", "Patrick Hand", "Shadows Into Light", "Gloria Hallelujah",
                    "Amatic SC:700"],
    "sans-heavy": ["Montserrat:900", "Montserrat:800", "Poppins:800", "Poppins:900", "Inter:900", "Raleway:900",
                   "Archivo Black", "Work Sans:900", "Outfit:900", "Plus Jakarta Sans:800"],
    "sans-rounded": ["Nunito:900", "Poppins:700", "Quicksand:700", "Varela Round", "M PLUS Rounded 1c:800",
                     "Baloo 2:800", "Fredoka:600", "Comfortaa:700"],
    "sans-regular": ["Inter:600", "Roboto:500", "Open Sans:600", "Lato:700", "Figtree:700", "DM Sans:700",
                     "Manrope:700", "Montserrat:600"],
    "sans-condensed": ["Anton", "Bebas Neue", "Oswald:700", "Fjalla One", "League Gothic", "Barlow Condensed:800",
                       "Teko:600", "Archivo Narrow:700"],
    "serif-display": ["Playfair Display:700", "Playfair Display:900", "DM Serif Display", "Abril Fatface",
                      "Bodoni Moda:700", "Cormorant Garamond:700", "Prata", "Libre Baskerville:700"],
    "slab-mono": ["Roboto Slab:800", "Arvo:700", "Zilla Slab:700", "Courier Prime:700", "Special Elite",
                  "Space Mono:700", "IBM Plex Mono:600"],
    "display": ["Bangers", "Luckiest Guy", "Titan One", "Bungee", "Lilita One", "Chewy", "Black Ops One",
                "Rubik Mono One"],
}
CACHE = Path(os.environ.get("EDITATLAS_FONT_CACHE") or Path.home() / ".cache" / "editatlas-fonts")
UA = {"User-Agent": "video-breakdown-skill/0.3 text_look.py"}


def hexc(c):
    return "#%02x%02x%02x" % tuple(int(round(min(255, max(0, v)))) for v in c)


def grow(m, r):
    """Binary dilation by r pixels (square)."""
    out = m.copy()
    for _ in range(r):
        p = np.pad(out, 1)
        out = (p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:] | out)
    return out


def shrink(m, r):
    return ~grow(~m, r)


def kmeans(px, k, seed=0):
    rng = np.random.default_rng(seed)
    sample = px[rng.choice(len(px), min(len(px), 20000), replace=False)]
    # spread the starting centres: k-means++ on the sample
    cent = [sample[rng.integers(len(sample))]]
    for _ in range(k - 1):
        d = np.min([((sample - c) ** 2).sum(1) for c in cent], axis=0)
        cent.append(sample[rng.choice(len(sample), p=d / d.sum())] if d.sum() > 0 else sample[0])
    cent = np.array(cent, np.float32)
    for _ in range(30):
        lab = ((sample[:, None, :] - cent[None]) ** 2).sum(-1).argmin(1)
        new = np.array([sample[lab == j].mean(0) if (lab == j).any() else cent[j] for j in range(k)])
        if np.abs(new - cent).max() < 0.5:
            break
        cent = new
    lab = np.concatenate([((c[:, None, :] - cent[None]) ** 2).sum(-1).argmin(1)
                          for c in np.array_split(px, max(1, len(px) // 50000))])
    return cent, lab


def stops(img, mask, axis, n=5):
    """Mean colour of the masked pixels in n bands along an axis (0 = top to bottom, 1 = left to right)."""
    ys, xs = np.nonzero(mask)
    pos = ys if axis == 0 else xs
    lo, hi = pos.min(), pos.max() + 1
    out = []
    for b in range(n):
        a, z = lo + (hi - lo) * b / n, lo + (hi - lo) * (b + 1) / n
        sel = (pos >= a) & (pos < z)
        out.append(np.median(img[ys[sel], xs[sel]], axis=0) if sel.sum() >= 5 else None)
    return out


def spread(cols):
    cols = [c for c in cols if c is not None]
    if len(cols) < 2:
        return 0.0
    return float(max(np.linalg.norm(a - b) for a in cols for b in cols) / 441.7)


def text_band(crop):
    """Rows of the line of text: the longest run of rows dense with sharp left-right edges."""
    g = crop.astype(np.float32).mean(-1)
    dens = (np.abs(np.diff(g, axis=1)) > 30).mean(1)
    rows = dens >= 0.4 * dens.max() if dens.max() > 0 else np.ones(len(dens), bool)
    best, cur, start = (0, len(dens)), 0, 0
    for i, r in enumerate(list(rows) + [False]):
        if r:
            if cur == 0:
                start = i
            cur += 1
        else:
            if cur > best[1] - best[0] or best == (0, len(dens)):
                best = (start, i) if cur else best
            cur = 0
    a, b = best
    pad = max(2, (b - a) // 3)
    band = np.zeros(crop.shape[:2], bool)
    band[max(0, a - pad):b + pad] = True
    return band


def measure(crop, k, chosen=None, changed=None):
    h, w, _ = crop.shape
    px = crop.reshape(-1, 3).astype(np.float32)
    cent, lab = kmeans(px, k)
    lab = lab.reshape(h, w)
    edge = np.zeros((h, w), bool)
    b = max(2, min(h, w) // 40)
    edge[:b], edge[-b:], edge[:, :b], edge[:, -b:] = True, True, True, True
    clusters = []
    for j in range(k):
        share = float((lab == j).mean())
        eshare = float((lab[edge] == j).mean())
        clusters.append({"id": j, "colour": hexc(cent[j]), "share": round(share, 3), "edge_share": round(eshare, 3)})
    if changed is not None:
        # Text pixels are those that changed when the text came in; a cluster counts when most of it changed.
        for c in clusters:
            m = lab == c["id"]
            c["changed"] = round(float((m & changed).sum() / max(1, m.sum())), 3)
        if chosen is None:
            chosen = [c["id"] for c in clusters if c["share"] >= 0.005 and c["changed"] >= 0.5]
    if chosen is None:
        chosen = [c["id"] for c in clusters if c["share"] >= 0.01 and c["edge_share"] < 0.25 * c["share"]]
    for c in clusters:
        c["text"] = c["id"] in chosen
    # Colours found only in the text are taken everywhere; colours the background shares only in the line of text.
    only = [c["id"] for c in clusters if c["id"] in chosen and c["edge_share"] < 0.25 * c["share"]]
    mask = np.isin(lab, only) | (np.isin(lab, [j for j in chosen if j not in only]) & text_band(crop))
    if changed is not None:
        mask &= grow(changed, 1)
    res = {"clusters": clusters, "text_clusters": chosen, "text_share": round(float(mask.mean()), 3)}
    if mask.sum() < 30:
        res["problem"] = ("no text pixels found: crop closer around the text with a little background on every side, "
                          "or pick the clusters with --text-clusters")
        return res, lab, mask, None
    img = crop.astype(np.float32)
    # Outline or shadow: a cluster that forms the outer layer of the text, around a fill of other colours.
    ys0 = np.nonzero(mask)[0]
    th = int(ys0.max() - ys0.min() + 1)
    outer = mask & ~shrink(mask, max(2, round(0.05 * th)))
    outer_frac = {j: float((outer & (lab == j)).sum() / max(1, (lab == j).sum())) for j in chosen}
    low = min(outer_frac.values())
    deco = [j for j in chosen if outer_frac[j] > 0.6 and outer_frac[j] - low > 0.25] if len(chosen) > 1 else []
    fill_ids = [j for j in chosen if j not in deco] or list(chosen)
    if deco and fill_ids != list(chosen):
        # An outline or shadow wraps the fill: most of the fill's edge touches it, and most of it touches the fill.
        fm, dm = np.isin(lab, fill_ids) & mask, np.isin(lab, deco) & mask
        r = max(2, round(0.03 * th))
        fill_edge = fm & ~shrink(fm, 1)
        wraps = (fill_edge & grow(dm, r)).sum() / max(1, fill_edge.sum())
        hugs = (dm & grow(fm, 2 * r)).sum() / max(1, dm.sum())
        res["wrap_check"] = {"fill_edge_touching": round(float(wraps), 2), "layer_near_fill": round(float(hugs), 2)}
        if wraps < 0.4 or hugs < 0.6:
            deco, fill_ids = [], list(chosen)
    else:
        deco, fill_ids = [], list(chosen)
    outline = None
    if deco:
        fm, dm = np.isin(lab, fill_ids) & mask, np.isin(lab, deco) & mask
        fy, fx = np.nonzero(fm)
        dy, dx = np.nonzero(dm)
        off_y, off_x = (dy.mean() - fy.mean()) / th, (dx.mean() - fx.mean()) / th
        width, ring = 0, fm
        for r in range(1, max(3, th // 6)):
            nxt = grow(fm, r)
            if (nxt & ~ring & dm).sum() < 0.3 * (nxt & ~ring).sum():
                break
            ring, width = nxt, r
        shadow = abs(off_y) > 0.04 or abs(off_x) > 0.04
        if width >= 1 and max(abs(off_x), abs(off_y)) <= 0.25:
            outline = {"kind": "shadow offset from the letters" if shadow else "outline around the letters",
                       "colour": hexc(np.median(img[dm], axis=0)), "width_px": width,
                       "width_of_text_height": round(width / th, 3),
                       "offset_of_text_height": [round(float(off_x), 3), round(float(off_y), 3)],
                       "clusters": deco}
        else:
            fill_ids = list(chosen)
    res["outer_layer_share"] = {str(j): round(v, 2) for j, v in outer_frac.items()}
    fill = np.isin(lab, fill_ids) & mask
    core = shrink(fill, 1)
    if core.sum() < 30:
        core = fill
    vert, horiz = stops(img, core, 0), stops(img, core, 1)
    sv, sh = spread(vert), spread(horiz)
    kind = ("solid" if max(sv, sh) < 0.1 else "gradient top to bottom" if sv >= 1.4 * sh else
            "gradient left to right" if sh >= 1.4 * sv else "gradient on both axes (diagonal, or per letter)")
    res["fill"] = {"kind": kind, "mean": hexc(np.median(img[core], axis=0)),
                   "top_to_bottom": [hexc(c) for c in vert if c is not None], "change_top_to_bottom": round(sv, 2),
                   "left_to_right": [hexc(c) for c in horiz if c is not None], "change_left_to_right": round(sh, 2)}
    res["outline"] = outline
    # Glow or shadow: the band just outside the text against the background further out.
    out_mask = ~mask
    near = grow(mask, max(3, h // 25)) & out_mask
    far = grow(mask, max(10, h // 6)) & ~grow(mask, max(6, h // 10)) & out_mask
    if near.sum() > 20 and far.sum() > 20:
        ln, lf = img[near].mean(), img[far].mean()
        cn = np.median(img[near], axis=0)
        d = float(ln - lf) / 255
        halo = {"near_colour": hexc(cn), "background": hexc(np.median(img[far], axis=0)), "brightness_change": round(d, 3)}
        ys, xs = np.nonzero(near)
        cy, cx = np.nonzero(mask)
        below = img[near & (np.arange(h)[:, None] > cy.mean())].mean() if (near & (np.arange(h)[:, None] > cy.mean())).any() else ln
        above = img[near & (np.arange(h)[:, None] <= cy.mean())].mean() if (near & (np.arange(h)[:, None] <= cy.mean())).any() else ln
        halo["kind"] = ("glow (brighter around the text)" if d > 0.06 else
                        "drop shadow (darker below the text)" if d < -0.04 and below < above - 6 else
                        "shadow or dark halo" if d < -0.04 else "none")
        res["halo"] = halo
    ys, xs = np.nonzero(grow(shrink(fill, 1), 1) if shrink(fill, 1).sum() > 30 else fill)
    x0, x1 = np.percentile(xs, [0.5, 99.5]).astype(int)
    y0, y1 = np.percentile(ys, [0.5, 99.5]).astype(int)
    res["text_box_px"] = [int(x0), int(y0), int(x1 - x0 + 1), int(y1 - y0 + 1)]
    res["slant_deg"] = slant(fill)
    return res, lab, fill, (fill, vert, horiz)


def shear(m, deg):
    """Shear a mask horizontally so that strokes leaning by `deg` stand upright."""
    h, w = m.shape
    k = np.tan(np.radians(deg))
    pad = int(abs(k) * h) + 1
    out = np.zeros((h, w + 2 * pad), bool)
    for y in range(h):
        dx = int(round(k * (y - h / 2)))
        out[y, pad + dx:pad + dx + w] = m[y]
    return out


def slant(m):
    """Lean of the letters in degrees (positive leans right, like italics): the shear that makes stems sharpest."""
    ys, xs = np.nonzero(m)
    m = m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    best, score0 = 0, None
    for deg in range(-30, 31, 2):
        col = shear(m, deg).sum(0).astype(np.float64)
        sc = float((col ** 2).sum())
        if score0 is None or sc > score0:
            best, score0 = deg, sc
    return best


# ------------------------------------------------------------------ fonts
def font_file(spec):
    if Path(spec).suffix.lower() in (".ttf", ".otf") and Path(spec).is_file():
        return Path(spec)
    name, _, weight = spec.partition(":")
    italic = weight.endswith("i")
    weight = weight.rstrip("i") or "400"
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{re.sub(r'[^A-Za-z0-9]+', '', name)}-{weight}{'i' if italic else ''}.ttf"
    if path.is_file():
        return path
    q = name.replace(" ", "+") + (f":ital,wght@1,{weight}" if italic else f":wght@{weight}" if weight != "400" else "")
    try:
        with urllib.request.urlopen(urllib.request.Request(f"https://fonts.googleapis.com/css2?family={q}",
                                                           headers=UA), timeout=30) as r:
            css = r.read().decode("utf-8")
        url = re.search(r"url\((https://[^)]+)\)", css).group(1)
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
            path.write_bytes(r.read())
    except (urllib.error.URLError, OSError, AttributeError) as e:
        print(f"  could not get {spec}: {e}")
        return None
    return path


def render(text, fpath, height, fill_img=None, outline=None, lean=0):
    """The text drawn so its letters are `height` px tall, leaning `lean` degrees more than the font does.
    Returns (RGBA image, mask)."""
    from PIL import Image, ImageDraw, ImageFont
    size = 120
    f = ImageFont.truetype(str(fpath), size)
    box = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((0, 0), text, font=f)
    size = max(8, int(size * height / max(1, box[3] - box[1])))
    f = ImageFont.truetype(str(fpath), size)
    o = outline or {}
    sw = int(round(o.get("width_of_text_height", 0) * height)) if o.get("kind", "").startswith("outline") else 0
    off = [int(round(v * height)) for v in o.get("offset_of_text_height", [0, 0])] if o.get("kind", "").startswith("shadow") else [0, 0]
    box = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((0, 0), text, font=f, stroke_width=sw)
    pad = 4 + max(abs(off[0]), abs(off[1]))
    W, H = box[2] - box[0] + 2 * pad, box[3] - box[1] + 2 * pad
    org = (pad - box[0], pad - box[1])
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).text(org, text, font=f, fill=255)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if o.get("colour") and (sw or off != [0, 0]):
        s = Image.new("L", (W, H), 0)
        ImageDraw.Draw(s).text((org[0] + off[0], org[1] + off[1]), text, font=f, fill=255, stroke_width=sw,
                               stroke_fill=255)
        col = tuple(int(o["colour"][i:i + 2], 16) for i in (1, 3, 5))
        out.paste(Image.new("RGBA", (W, H), col + (255,)), (0, 0), s)
    out.paste(fill_img.resize((W, H)).convert("RGBA") if fill_img else Image.new("RGBA", (W, H), (255, 255, 255, 255)),
              (0, 0), m)
    if abs(lean) >= 1:
        k = np.tan(np.radians(lean))
        W2 = W + int(abs(k) * H)
        shift = -k * H / 2 - (W2 - W) / 2
        data = (1, k, shift, 0, 1, 0)
        out = out.transform((W2, H), Image.AFFINE, data, Image.BICUBIC)
        m = m.transform((W2, H), Image.AFFINE, data, Image.BICUBIC)
    return out, np.array(m) > 127


def strokes(m):
    """Stroke weight (median stroke width over the text height) and contrast (thick strokes over thin ones)."""
    m = grow(shrink(m, 1), 1)
    if m.sum() < 30:
        return None
    d = np.zeros(m.shape, np.int32)
    x = m.copy()
    while x.any():
        d[x] += 1
        x = shrink(x, 1)
    p = np.pad(d, 1)
    nb = np.stack([p[1 + dy:p.shape[0] - 1 + dy, 1 + dx:p.shape[1] - 1 + dx] for dy in (-1, 0, 1) for dx in (-1, 0, 1)])
    w = 2 * d[(d > 0) & (d >= nb.max(0))] - 1
    ys = np.nonzero(m)[0]
    h = max(1.0, float(np.percentile(ys, 99.5) - np.percentile(ys, 0.5)))
    weight = float(np.median(w)) / h
    contrast = float(np.percentile(w, 90)) / max(1.0, float(np.percentile(w, 20)))
    return {"weight": round(weight, 3), "contrast": round(contrast, 2),
            "words": ("light" if weight < 0.06 else "regular" if weight < 0.1 else "bold" if weight < 0.15 else "heavy")
            + ", " + ("even strokes" if contrast < 1.5 else "some thick and thin" if contrast < 2.2
                      else "strong thick and thin (calligraphic or high-contrast)")}


def shape_score(ref, cand):
    """Overlap of two text masks once both are scaled to the reference's box: 0 to 1."""
    from PIL import Image
    ref = grow(shrink(ref, 1), 1)  # drop specks
    ys, xs = np.nonzero(ref)
    y0, y1 = np.percentile(ys, [0.5, 99.5]).astype(int)
    x0, x1 = np.percentile(xs, [0.5, 99.5]).astype(int)
    ref = ref[y0:y1 + 1, x0:x1 + 1]
    ys, xs = np.nonzero(cand)
    cand = cand[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    width_ratio = (cand.shape[1] / cand.shape[0]) / (ref.shape[1] / ref.shape[0])
    H = 48
    W = max(8, int(H * ref.shape[1] / ref.shape[0]))
    a = np.array(Image.fromarray(ref.astype(np.uint8) * 255).resize((W, H))) > 127
    b = np.array(Image.fromarray(cand.astype(np.uint8) * 255).resize((W, H))) > 127
    # soften by one pixel so a stroke one pixel off still counts
    a2, b2 = grow(a, 1), grow(b, 1)
    iou = ((a & b2).sum() + (b & a2).sum()) / max(1, a.sum() + b.sum())
    return round(float(iou) * min(width_ratio, 1 / width_ratio) ** 0.5, 3), round(float(width_ratio), 2)


# ------------------------------------------------------------------ drawing
def draw(out, crop, lab, res, grads, fonts):
    from PIL import Image, ImageDraw
    scale = max(1.0, 520 / crop.shape[1])
    big = Image.fromarray(crop).resize((int(crop.shape[1] * scale), int(crop.shape[0] * scale)))
    W = max(big.width * 2 + 20, 900)
    blocks = []

    def label(img, text):
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, 8 + 6 * len(text), 13], fill=(0, 0, 0))
        d.text((3, 1), text, fill=(255, 255, 255))
        return img

    # the crop, and what was taken as text
    mask = grads[0] if grads is not None else np.isin(lab, res["text_clusters"])
    shown = np.where(mask[..., None], crop, (crop * 0.15 + 30).astype(np.uint8))
    row = Image.new("RGB", (W, big.height), (40, 40, 40))
    row.paste(label(big.copy(), "crop"), (0, 0))
    row.paste(label(Image.fromarray(shown).resize(big.size), "taken as text"), (big.width + 20, 0))
    blocks.append(row)
    # every colour cluster, so a wrong pick can be fixed with --text-clusters
    tw = max(80, (W - 10 * (len(res["clusters"]) - 1)) // len(res["clusters"]))
    th = max(30, int(tw * crop.shape[0] / crop.shape[1]))
    row = Image.new("RGB", (W, th + 34), (40, 40, 40))
    for i, c in enumerate(res["clusters"]):
        m = lab == c["id"]
        t = Image.fromarray(np.where(m[..., None], crop, 30).astype(np.uint8)).resize((tw, th))
        row.paste(t, (i * (tw + 10), 0))
        col = tuple(int(c["colour"][k:k + 2], 16) for k in (1, 3, 5))
        ImageDraw.Draw(row).rectangle([i * (tw + 10), th + 2, i * (tw + 10) + 16, th + 18], fill=col)
        ImageDraw.Draw(row).text((i * (tw + 10) + 20, th + 4), f"{c['id']} {c['colour']}" + (" text" if c["text"] else ""),
                                 fill=(255, 255, 255))
        ImageDraw.Draw(row).text((i * (tw + 10) + 20, th + 18), f"share {c['share']}, edge {c['edge_share']}"
                                 + (f", changed {c['changed']}" if "changed" in c else ""),
                                 fill=(200, 200, 200))
    blocks.append(row)
    # gradient stops
    if res.get("fill"):
        row = Image.new("RGB", (W, 60), (40, 40, 40))
        d = ImageDraw.Draw(row)
        for k, key in enumerate(("top_to_bottom", "left_to_right")):
            x = k * (W // 2)
            d.text((x + 4, 2), key.replace("_", " "), fill=(255, 255, 255))
            for i, hx in enumerate(res["fill"][key]):
                col = tuple(int(hx[j:j + 2], 16) for j in (1, 3, 5))
                d.rectangle([x + 4 + i * 80, 18, x + 80 + i * 80, 42], fill=col)
                d.text((x + 6 + i * 80, 44), hx, fill=(220, 220, 220))
        blocks.append(row)
    # font candidates
    if fonts:
        bg = tuple(int(res.get("halo", {}).get("background", "#3c3c3c")[i:i + 2], 16) for i in (1, 3, 5))
        for name, score, ratio, img, _ in fonts:
            row = Image.new("RGB", (W, max(big.height, img.height) + 4), bg)
            row.paste(big, (0, 0))
            k = min(1.0, (W - big.width - 30) / max(1, img.width))
            im = img.resize((max(1, int(img.width * k)), max(1, int(img.height * k)))) if k < 1 else img
            row.paste(im, (big.width + 20, (row.height - im.height) // 2), im)
            label(row, f"{name}  match {score}  width x{ratio}")
            blocks.append(row)
    H = sum(b.height + 6 for b in blocks)
    s = Image.new("RGB", (W, H), (25, 25, 25))
    y = 0
    for b in blocks:
        s.paste(b, (0, y))
        y += b.height + 6
    s.save(out)
    return out


def main():
    utf8_stdout()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("video", nargs="?")
    p.add_argument("--at", type=float, help="time in seconds, when the text is fully on and still")
    p.add_argument("--crop", help="x,y,w,h in percent of the frame, around one line of text")
    p.add_argument("--out", help="folder")
    p.add_argument("--k", type=int, default=6, help="colour clusters (default 6; more for busy backgrounds)")
    p.add_argument("--before", type=float, help="a time just before the text came in, same framing: text pixels are "
                   "the ones that changed (best when the background has the text's colours)")
    p.add_argument("--text-clusters", help="cluster ids that are text, from look.png, such as 1,4")
    p.add_argument("--text", help="the words exactly as they look on screen (case matters), to compare fonts")
    p.add_argument("--fonts", default="", help="groups or fonts, comma-separated: script-formal,Montserrat:900,my.ttf")
    p.add_argument("--top", type=int, default=8, help="font candidates drawn in look.png (default 8; all go in look.json)")
    p.add_argument("--list-fonts", action="store_true")
    a = p.parse_args()
    if a.list_fonts:
        for g, fs in FONT_GROUPS.items():
            print(f"{g:15} {', '.join(fs)}")
        print(f"cache: {CACHE}")
        return
    if not (a.video and a.at is not None and a.crop and a.out):
        die("give VIDEO --at SECONDS --crop x,y,w,h --out FOLDER (or --list-fonts)")
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        die("text_look.py needs Pillow: pip install pillow")
    info = probe(a.video)
    try:
        cx, cy, cw, ch = [float(x) / 100 for x in a.crop.split(",")]
        assert cw > 0 and ch > 0
    except (ValueError, AssertionError):
        die("--crop takes x,y,w,h in percent, such as 10,20,80,12")
    width = min(info["width"] or 1080, 2160)
    frame = grab(a.video, [a.at], width, info)[0]
    if frame is None:
        die(f"could not read a frame at {a.at} s")
    fh, fw = frame.shape[:2]
    crop = frame[int(cy * fh):int((cy + ch) * fh), int(cx * fw):int((cx + cw) * fw)]
    if crop.shape[0] < 8 or crop.shape[1] < 8:
        die("the crop is too small")
    chosen = [int(x) for x in a.text_clusters.split(",")] if a.text_clusters else None
    changed = None
    if a.before is not None:
        f0 = grab(a.video, [a.before], width, info)[0]
        if f0 is None:
            die(f"could not read a frame at {a.before} s")
        c0 = f0[int(cy * fh):int((cy + ch) * fh), int(cx * fw):int((cx + cw) * fw)]
        diff = np.abs(crop.astype(np.int16) - c0.astype(np.int16)).max(-1)
        changed = shrink(grow(diff > 40, 1), 1)
    res, lab, mask, grads = measure(crop, a.k, chosen, changed)
    if changed is not None:
        res["changed_share"] = round(float(changed.mean()), 3)
    res.update({"video": Path(a.video).name, "at": a.at, "crop": a.crop})
    fonts = []
    if a.text and grads is not None:
        from PIL import Image
        specs = []
        for item in [x.strip() for x in a.fonts.split(",") if x.strip()] or ["sans-heavy"]:
            specs += FONT_GROUPS.get(item, [item])
        fill_img = None
        if res["fill"]["kind"] != "solid":
            key = "top_to_bottom" if "top" in res["fill"]["kind"] else "left_to_right"
            cols = [[int(h[i:i + 2], 16) for i in (1, 3, 5)] for h in res["fill"][key]]
            ramp = np.array(cols, np.uint8)[None] if key == "left_to_right" else np.array(cols, np.uint8)[:, None]
            fill_img = Image.fromarray(ramp).resize((64, 64), Image.BILINEAR)
        else:
            fill_img = Image.new("RGB", (4, 4), tuple(int(res["fill"]["mean"][i:i + 2], 16) for i in (1, 3, 5)))
        res["strokes"] = strokes(mask)
        ref_h = res["text_box_px"][3]
        scale = max(1.0, 520 / crop.shape[1])
        rows = []
        for spec in dict.fromkeys(specs):
            fp = font_file(spec)
            if not fp:
                continue
            try:
                _, m0 = render(a.text, fp, 100)
                lean = res["slant_deg"] - slant(m0)
                lean = lean if abs(lean) >= 6 else 0
                img, m = render(a.text, fp, int(ref_h * scale), fill_img, res.get("outline"), lean)
            except OSError as e:
                print(f"  could not draw {spec}: {e}")
                continue
            score, ratio = shape_score(mask, m)
            st = strokes(m)
            if st and res.get("strokes"):
                # thick-and-thin contrast tells a calligraphic script from a brush or marker; weight is
                # less sure because a glow or outline thickens the reference
                rc, rw = res["strokes"]["contrast"], res["strokes"]["weight"]
                score = round(score * np.exp(-abs(np.log(st["contrast"] / rc))) *
                              np.exp(-0.5 * abs(np.log(max(st["weight"], 1e-3) / max(rw, 1e-3)))), 3)
            rows.append((spec + (f" leaned {lean:+d} deg" if lean else ""), score, ratio, img, st))
        rows.sort(key=lambda r: -r[1])
        fonts = rows[:a.top]
        res["fonts"] = [{"font": r[0], "match": r[1], "width_ratio": r[2], "strokes": r[4]} for r in rows]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "look.json", res)
    draw(out / "look.png", crop, lab, res, grads, fonts)
    print(f"text pixels: clusters {res['text_clusters']} ({res['text_share'] * 100:.0f} % of the crop)")
    if res.get("problem"):
        print("problem:", res["problem"])
    if res.get("fill"):
        f = res["fill"]
        print(f"fill: {f['kind']}; top to bottom {' > '.join(f['top_to_bottom'])} (change {f['change_top_to_bottom']}); "
              f"left to right {' > '.join(f['left_to_right'])} (change {f['change_left_to_right']})")
        o = res.get("outline")
        print(f"{o['kind']}: {o['colour']}, about {o['width_px']} px, offset {o['offset_of_text_height']} of the text height"
              if o else "outline or shadow: none found")
        print(f"letters lean {res['slant_deg']} degrees" + (" (italic or slanted)" if res["slant_deg"] >= 6 else ""))
        if res.get("halo"):
            h = res["halo"]
            print(f"around the text: {h['kind']} (near {h['near_colour']}, background {h['background']}, "
                  f"change {h['brightness_change']})")
    if res.get("strokes"):
        st = res["strokes"]
        print(f"strokes: {st['words']} (weight {st['weight']}, contrast {st['contrast']})")
    if res.get("fonts") and (res.get("slant_deg", 0) >= 15 or (res.get("strokes") or {}).get("contrast", 0) >= 2.2):
        print("  (script or calligraphic letters: the match number is weak here, judge the letter shapes by eye)")
    for r in res.get("fonts", [])[:a.top]:
        cs = r["strokes"] or {}
        print(f"  {r['font']:<34} match {r['match']:<6} width x{r['width_ratio']:<5} "
              f"weight {cs.get('weight')} contrast {cs.get('contrast')}")
    print("->", out / "look.png")
    print("->", out / "look.json")


if __name__ == "__main__":
    main()
