#!/usr/bin/env bash
# Input: bakery.mp4: a 6 s vertical bakery promo drawn in code (words come in one after another, a circle
# carried across a cut, a card sliding up). Fonts: Anton and Poppins (SIL OFL) from github.com/google/fonts.
set -eu
FONTS=https://raw.githubusercontent.com/google/fonts/main/ofl
mkdir -p .fonts
for f in anton/Anton-Regular.ttf poppins/Poppins-Bold.ttf poppins/Poppins-Regular.ttf; do
  curl -fsSL -A "editatlas-skills-eval/1.0" -o ".fonts/${f#*/}" "$FONTS/$f"
done
python - <<'PY'
import math, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont
EASE = {"linear": lambda t: t, "power2.out": lambda t: 1 - (1 - t) ** 3, "power3.out": lambda t: 1 - (1 - t) ** 4,
        "back.out": lambda t: 1 + 2.70158 * (t - 1) ** 3 + 1.70158 * (t - 1) ** 2}
def a(prop, t0, t1, fr, to, ease="linear"):
    return (prop, t0, t1, fr, to, ease)
def val(el, prop, t, default):
    anims = [x for x in el.get("anim", []) if x[0] == prop]
    v = el.get(prop, default)
    for i, (_, t0, t1, fr, to, e) in enumerate(anims):
        if t >= t0:
            v = to if t >= t1 else fr + (to - fr) * EASE[e]((t - t0) / (t1 - t0))
        elif i == 0:
            v = fr
    return v
def bg_image(bg, w, h):
    if "from" not in bg:
        return Image.new("RGB", (w, h), bg["color"])
    r = math.radians(bg["angle"])
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = (xx - w / 2) * math.cos(r) + (yy - h / 2) * math.sin(r)
    u = np.clip((d / (abs(w / 2 * math.cos(r)) + abs(h / 2 * math.sin(r))) + 1) / 2, 0, 1)[..., None]
    c0, c1 = (np.array(Image.new("RGB", (1, 1), c).getpixel((0, 0)), np.float32) for c in (bg["from"], bg["to"]))
    return Image.fromarray((c0 + (c1 - c0) * u).astype(np.uint8))
def render(shots, dur, out, W=1080, H=1920, fps=30):
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps),
                          "-i", "-", "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-pix_fmt", "yuv420p", out], stdin=subprocess.PIPE)
    fonts, bgs = {}, {}
    for i in range(int(round(dur * fps))):
        t = i / fps
        shot = [s for s in shots if s["t0"] <= t + 1e-9][-1]
        k = repr(shot["bg"])
        if k not in bgs:
            bgs[k] = bg_image(shot["bg"], W, H).convert("RGBA")
        frame = bgs[k].copy()
        for el in shot["elements"]:
            x, y, s, o = val(el, "x", t, .5) * W, val(el, "y", t, .5) * H, val(el, "scale", t, 1.), val(el, "opacity", t, 1.)
            if o <= .001 or s <= .001:
                continue
            layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)
            if el["kind"] == "text":
                size = max(1, int(el["size"] * H * s))
                fonts.setdefault((el["font"], size), ImageFont.truetype(el["font"], size))
                d.text((x, y), el["text"], font=fonts[(el["font"], size)], fill=el["color"], anchor="mm")
            else:
                ew, eh = el["w"] * W * s, el["h"] * W * s
                (d.ellipse if el["kind"] == "circle" else d.rectangle)([x - ew / 2, y - eh / 2, x + ew / 2, y + eh / 2], fill=el["color"])
            if o < 1:
                layer.putalpha(layer.getchannel("A").point(lambda v: int(v * o)))
            frame.alpha_composite(layer)
        p.stdin.write(np.asarray(frame.convert("RGB")).tobytes())
    p.stdin.close()
    assert p.wait() == 0

ANTON, PB, PR = ".fonts/Anton-Regular.ttf", ".fonts/Poppins-Bold.ttf", ".fonts/Poppins-Regular.ttf"
def bakery(size=0.07, gap=0.12, words=("FRESH", "BREAD", "EVERY", "MORNING"), cream="#fff4e0", slide=0.6):
    els1 = []
    for i, wd in enumerate(words):
        t0 = 0.5 + gap * i
        els1.append({"kind": "text", "font": ANTON, "text": wd, "size": size, "color": "#3b2416", "x": 0.5, "y": 0.22 + 0.09 * i,
                     "scale": 0.6, "opacity": 0, "anim": [a("scale", t0, t0 + 0.35, 0.6, 1, "back.out"), a("opacity", t0, t0 + 0.15, 0, 1)]})
    els1.append({"kind": "circle", "color": "#e8a33d", "w": 0.3, "h": 0.3, "x": 0.5, "y": 0.72, "scale": 0,
                 "anim": [a("scale", 1.3, 1.8, 0, 1, "power3.out")]})
    els2 = [{"kind": "circle", "color": "#e8a33d", "w": 0.3, "h": 0.3, "x": 0.5, "y": 0.72},
            {"kind": "rect", "color": "#ffffff", "w": 0.8, "h": 0.22, "x": 0.5, "y": 1.2, "anim": [a("y", 3.6, 3.6 + slide, 1.2, 0.35, "power3.out")]},
            {"kind": "text", "font": PB, "text": "open 6 am", "size": 0.04, "color": "#0b3d2e", "x": 0.5, "y": 1.2,
             "anim": [a("y", 3.7, 3.7 + slide, 1.2, 0.35, "power3.out")]}]
    return [{"t0": 0, "bg": {"color": cream}, "elements": els1},
            {"t0": 3.0, "bg": {"from": "#0b3d2e", "to": "#06261d", "angle": 90}, "elements": els2}]
render(bakery(), 6.0, "bakery.mp4")
PY
rm -rf .fonts
