"""Find, fetch and measure EditAtlas sounds.

  sounds.py search "soft whoosh" [--category whoosh] [--max-dur 1.5] [--limit 12]
  sounds.py info sfx-ID [sfx-ID ...]           # downloads once, checks SHA-256, prints measured numbers
  sounds.py sheet sfx-ID [...] --out FILE.png  # waveform + spectrogram of each, labelled with its id

Search here is plain keyword matching over the public index. When the EditAtlas MCP is connected, its
search_sfx ranks better (it also knows Vietnamese terms); take the ids it returns and use `info` here.
"""
import argparse
import re

import numpy as np

from common import (by_id, decode, fetch, load_index, measured, utf8_stdout, SR, die)

# Words people use for a sound that the titles often avoid. Each query word also matches its synonyms.
SYNONYMS = {
    "hit": ["impact", "punch", "slam", "thud", "boom", "knock"], "impact": ["hit", "boom", "slam", "thud"],
    "whoosh": ["swoosh", "swish", "swipe", "woosh", "pass", "sweep"], "swoosh": ["whoosh", "swish"],
    "click": ["tap", "tick", "button", "press"], "tap": ["click", "tick"], "pop": ["bubble", "plop", "pluck"],
    "ding": ["chime", "bell", "ring"], "chime": ["ding", "bell", "sparkle"], "riser": ["rise", "build", "swell"],
    "drop": ["sub", "boom", "fall"], "typing": ["keyboard", "keys", "keystroke"], "keyboard": ["typing", "keys"],
    "camera": ["shutter", "lens", "aperture", "snapshot"], "shutter": ["camera", "lens", "aperture"],
    "paper": ["page", "sheet", "flip"], "cash": ["coin", "register", "money", "till"], "coin": ["cash", "money"],
    "ambient": ["ambience", "background", "room", "atmosphere"], "ambience": ["ambient", "background"],
    "glitch": ["static", "digital", "error", "stutter"], "error": ["fail", "wrong", "buzz"],
    "success": ["correct", "win", "complete", "ding"], "magic": ["sparkle", "shimmer", "twinkle", "fairy"],
}


def words(s):
    return re.findall(r"[a-z0-9]+", (s or "").lower())


def score(sound, terms):
    title = set(words(sound.get("title")))
    cat = sound.get("category", "")
    desc = set(words(sound.get("description")))
    total = 0.0
    for t in terms:
        alts = [t] + SYNONYMS.get(t, [])
        best = 0.0
        for k, a in enumerate(alts):
            w = 1.0 if k == 0 else 0.6
            if a in title or any(x.startswith(a) and len(a) >= 4 for x in title):
                best = max(best, 3 * w)
            elif a == cat:
                best = max(best, 2 * w)
            elif a in desc or any(x.startswith(a) and len(a) >= 4 for x in desc):
                best = max(best, 1.5 * w)
        total += best
    return total


def cmd_search(a):
    index, _ = load_index(a.cache, a.mirror)
    terms = words(a.query)
    rows = []
    for s in index["sounds"]:
        if a.category and s["category"] not in a.category.split(","):
            continue
        d = s.get("duration_s") or 0
        if (a.max_dur and d > a.max_dur) or (a.min_dur and d < a.min_dur):
            continue
        sc = score(s, terms) if terms else 1.0
        if sc > 0:
            rows.append((sc, s))
    rows.sort(key=lambda r: (-r[0], r[1].get("duration_s") or 0))
    for sc, s in rows[: a.limit]:
        print(f"{s['id']:<16} {s['category']:<9} {s.get('duration_s', 0):>6.2f}s  {s['title'][:34]:<34}  "
              f"{s['description'][:90]}")
    print(f"{len(rows)} match(es) for {terms or '(all)'}" + (f" in {a.category}" if a.category else ""))


def cmd_info(a):
    index, mirror = load_index(a.cache, a.mirror)
    table = by_id(index)
    for i in a.ids:
        s = table.get(i) or die(f"unknown id {i}")
        m = measured(s, a.cache, mirror)
        print(f"{i}  {s['title']}  [{s['category']}]")
        print(f"   {s['description']}")
        print("   " + "  ".join(f"{k}={v}" for k, v in m.items()))
        if a.paths:
            print("   path:", fetch(s, a.cache, mirror))


def cmd_sheet(a):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        die("sheet needs Pillow: pip install pillow")
    index, mirror = load_index(a.cache, a.mirror)
    table = by_id(index)
    W, H = 520, 150
    tiles = []
    for i in a.ids:
        s = table.get(i) or die(f"unknown id {i}")
        x = decode(fetch(s, a.cache, mirror), channels=1)[:, 0][: SR * 6]
        img = Image.new("RGB", (W, H), (18, 18, 20))
        dr = ImageDraw.Draw(img)
        if len(x):
            # spectrogram in the lower part, log frequency, 60 dB range
            n, hop = 1024, max(1, len(x) // W)
            cols = []
            for c in range(W):
                seg = x[c * hop: c * hop + n]
                if len(seg) < n:
                    seg = np.pad(seg, (0, n - len(seg)))
                cols.append(np.abs(np.fft.rfft(seg * np.hanning(n))))
            S = 20 * np.log10(np.array(cols).T + 1e-9)
            S = np.clip((S - (S.max() - 60)) / 60, 0, 1)
            fr = np.geomspace(1, S.shape[0] - 1, 80).astype(int)[::-1]
            spec = (S[fr] * 255).astype(np.uint8)
            sp = Image.fromarray(np.stack([spec, (spec * 0.6).astype(np.uint8), 255 - spec], -1)).resize((W, 80))
            img.paste(sp, (0, H - 80))
            env = np.abs(x[: (len(x) // W) * W]).reshape(W, -1).max(axis=1) if len(x) >= W else np.abs(x)
            pk = env.max() or 1
            for c, v in enumerate(env):
                h = int(25 * v / pk)
                dr.line([(c, 45 - h), (c, 45 + h)], fill=(41, 151, 255))
        dr.text((4, 2), f"{i}  {s['title'][:40]}  {s.get('duration_s', 0):.2f}s", fill=(240, 240, 240))
        tiles.append(img)
    sheet = Image.new("RGB", (W * min(2, len(tiles)), H * ((len(tiles) + 1) // 2)), (0, 0, 0))
    for k, t in enumerate(tiles):
        sheet.paste(t, ((k % 2) * W, (k // 2) * H))
    sheet.save(a.out)
    print("->", a.out, "(top: waveform of the first 6 s; bottom: spectrogram, low notes at the bottom)")


def main():
    utf8_stdout()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cache")
    p.add_argument("--mirror", help="local EditAtlas-SFX checkout (else the index and files come from GitHub)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("query", nargs="?", default="")
    s.add_argument("--category")
    s.add_argument("--max-dur", type=float)
    s.add_argument("--min-dur", type=float)
    s.add_argument("--limit", type=int, default=12)
    i = sub.add_parser("info")
    i.add_argument("ids", nargs="+")
    i.add_argument("--paths", action="store_true")
    h = sub.add_parser("sheet")
    h.add_argument("ids", nargs="+")
    h.add_argument("--out", required=True)
    a = p.parse_args()
    {"search": cmd_search, "info": cmd_info, "sheet": cmd_sheet}[a.cmd](a)


if __name__ == "__main__":
    main()
