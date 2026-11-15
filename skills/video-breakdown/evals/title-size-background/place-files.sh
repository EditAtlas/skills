#!/usr/bin/env bash
# Input: title.mp4: a 4 s vertical title card drawn in code on a diagonal gradient. Fonts: Anton and Poppins
# (SIL OFL) from github.com/google/fonts.
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

ANTON, PR = ".fonts/Anton-Regular.ttf", ".fonts/Poppins-Regular.ttf"
els = [{"kind": "text", "font": ANTON, "text": "LAUNCH DAY", "size": 0.09, "color": "#ffffff", "x": 0.5, "y": 0.45, "opacity": 0,
        "anim": [a("opacity", 0.3, 0.7, 0, 1, "power2.out")]},
       {"kind": "text", "font": PR, "text": "join us live at 8 pm", "size": 0.032, "color": "#fff3e8", "x": 0.5, "y": 0.53, "opacity": 0,
        "anim": [a("opacity", 0.8, 1.2, 0, 1, "power2.out")]}]
render([{"t0": 0, "bg": {"from": "#ff6a3d", "to": "#7b2ff7", "angle": 45}, "elements": els}], 4.0, "title.mp4")
PY
rm -rf .fonts
