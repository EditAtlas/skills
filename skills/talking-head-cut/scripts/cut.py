"""Turn your plan (what to remove, by quoting the words) into an edit list whose every cut sits in silence.

  cut.py work/t/transcript.json FILM.mp4 work/cut/plan.json --out work/cut [--pace natural|tight|keep]

You never type a time for a word. You quote it, and this script finds it, measures where its sound really starts
and ends, and puts each cut in the quiet beside it. Pauses longer than the pace allows are shortened to a natural
breath, not removed. Writes:

  edl.json             the pieces of the source to keep, in order, for render.py and for the EditAtlas studio
  transcript_cut.json  the kept words with times in the cut film (for captions; same format as the transcribe skill)
  cuts.md              every removal with its words, reason and length, every join with its pause; show the person

Plan format and every field: references/formats.md.
"""
import argparse
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))  # also under python -I
from common import (HOP, clock, decode, die, ends_sentence, envelope_db, is_sure_filler, islands, levels, norm, probe, read_json,
                    tighten, utf8_stdout, word_tokens, write_json)

# Pauses, in seconds. keep_up_to: a pause this short inside kept speech is left as it is. sentence / phrase: what a
# longer pause becomes between sentences / inside one. lead / tail: silence kept before the first and after the last
# word. Measured preferences for cleaned-up speech: 0.3-0.5 s between sentences (vlogs and lessons), about 0.3 s for
# fast short-form.
PACES = {
    "natural": {"keep_up_to": 0.8, "sentence": 0.45, "phrase": 0.25, "lead": 0.15, "tail": 0.4},
    "tight": {"keep_up_to": 0.5, "sentence": 0.3, "phrase": 0.18, "lead": 0.1, "tail": 0.3},
    "keep": {"keep_up_to": 1e9, "sentence": 1e9, "phrase": 1e9, "lead": 0.15, "tail": 0.4},
}
MIN_TAIL = 0.06       # always keep this much after a last word when there is that much silence: releases are quiet


def find_quote(item, words, toks, lines):
    """Word indexes [a, b) the quote names. Lines narrow the search; "near" picks among several."""
    q = norm(item["quote"])
    if not q:
        die(f"empty quote in {item}")
    lo, hi = 0, len(words)
    if "line" in item:
        ln = next((x for x in lines if x["line"] == int(item["line"])), None)
        if not ln:
            die(f"line {item['line']} is not in takes.json")
        lo, hi = ln["first"], ln["last"] + 1
    flat, owner = [], []
    for i in range(lo, hi):
        for tk in toks[i]:
            flat.append(tk)
            owner.append(i)
    hits = [k for k in range(len(flat) - len(q) + 1) if flat[k:k + len(q)] == q]
    if not hits:
        best = max(range(max(1, len(flat) - len(q) + 1)), key=lambda k: sum(a == b for a, b in zip(flat[k:k + len(q)], q)))
        near = " ".join(words[i]["w"] for i in sorted(set(owner[best:best + len(q) + 2])))
        die(f'quote not found: "{item["quote"]}". Quote the words exactly as the transcript has them '
            f'(fix.py in the transcribe skill corrects a misheard word first). Closest: "{near}"')
    if len(hits) > 1:
        if "near" in item:
            hits = [min(hits, key=lambda k: abs(words[owner[k]]["start"] - float(item["near"])))]
        elif "nth" in item:
            hits = [hits[int(item["nth"]) - 1]]
        else:
            where = ", ".join(f"{clock(words[owner[k]]['start'])}" for k in hits)
            die(f'"{item["quote"]}" is said {len(hits)} times (at {where}); add "line": N or "near": seconds')
    k = hits[0]
    return owner[k], owner[k + len(q) - 1] + 1


def parse_lines(spec, lines):
    out = []
    for part in str(spec).replace(" ", "").split(","):
        a, _, b = part.partition("-")
        for n in range(int(a.lstrip("L")), int((b or a).lstrip("L")) + 1):
            ln = next((x for x in lines if x["line"] == n), None)
            if not ln:
                die(f"line {n} is not in takes.json")
            out.append((ln["first"], ln["last"] + 1))
    return out


def loud_edge(env, thr, t, direction, limit):
    """Seconds of quiet from t going forward (+1) or back (-1), up to limit."""
    i = int(round(t / HOP))
    n = 0
    while n * HOP < limit:
        j = i + direction * (n + (0 if direction > 0 else 1))
        if j < 0 or j >= len(env) or env[j] > thr:
            break
        n += 1
    return n * HOP


def quietest(env, a, b):
    """Time of the quietest 10 ms step between a and b."""
    i0, i1 = max(0, int(a / HOP)), min(len(env), max(int(a / HOP) + 1, int(math.ceil(b / HOP))))
    if i1 <= i0:
        return a
    return (i0 + int(np.argmin(env[i0:i1]))) * HOP + HOP / 2


def voiced_between(env, thr, a, b):
    """True when the gap between two kept words holds 0.15 s or more of sound: words Whisper did not write (SOUND? in
    takes.md). Such a gap is not shortened, so unwritten speech is never cut as if it were a pause; the plan removes
    it by "from"/"to" when it should go."""
    i0, i1 = int((a + 0.1) / HOP), int((b - 0.1) / HOP)
    if i1 <= i0:
        return False
    # one unbroken stretch (gaps under 50 ms bridged): noise in a cafe pops over the threshold only briefly
    return any((y - x) * HOP >= 0.15 for x, y in islands(env[i0:i1] > thr, 5))


def on_grid(t, fps, lo, hi):
    """t moved onto the frame grid if a grid point lies within [lo, hi], so picture and sound cut at the same time."""
    for g in sorted((math.floor(t * fps) / fps, math.ceil(t * fps) / fps), key=lambda g: abs(g - t)):
        if lo - 1e-6 <= g <= hi + 1e-6:
            return round(g, 6)
    return round(t, 6)


def main():
    utf8_stdout()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("transcript")
    p.add_argument("film")
    p.add_argument("plan")
    p.add_argument("--out", required=True)
    p.add_argument("--takes", help="takes.json from takes.py (default: the one in --out)")
    p.add_argument("--pace", choices=sorted(PACES), help="overrides the plan's pace")
    a = p.parse_args()
    t = read_json(a.transcript)
    plan = read_json(a.plan)
    takes = read_json(a.takes or Path(a.out) / "takes.json")
    pace_name = a.pace or plan.get("pace", "natural")
    if pace_name not in PACES:
        die(f"pace must be one of {sorted(PACES)}")
    pace = PACES[pace_name]
    info = probe(a.film)
    fps = info["fps"] or 30.0
    duration = info["duration"] or t.get("duration")
    env = envelope_db(decode(a.film))
    thr, speech, floor = levels(env, t["words"])
    words = tighten(t["words"], env, thr)
    toks = word_tokens(words)
    lines = takes["lines"]
    n = len(words)

    why = [None] * n            # reason a word is removed
    sound_cuts = []             # (from, to, why) stretches with no words
    for item in plan.get("remove", []):
        reason = item.get("why") or "removed"
        if "lines" in item:
            spans = parse_lines(item["lines"], lines)
        elif "quote" in item:
            spans = [find_quote(item, words, toks, lines)]
        elif "from" in item and "to" in item:
            f0, f1 = float(item["from"]), float(item["to"])
            sound_cuts.append((f0, f1, reason))
            spans = [(i, i + 1) for i, w in enumerate(words) if w["start"] < f1 and w["end"] > f0]
        else:
            die(f"a remove item needs lines, quote, or from and to: {item}")
        for s_, e_ in spans:
            for i in range(s_, e_):
                why[i] = why[i] or reason
    kept_fillers = set()
    for item in plan.get("keep", []):
        s_, e_ = find_quote(item, words, toks, lines)
        kept_fillers.update(range(s_, e_))
        for i in range(s_, e_):
            why[i] = None
    if plan.get("fillers", True):
        for i, w in enumerate(words):
            if why[i] is None and i not in kept_fillers and is_sure_filler(w):
                why[i] = "filler"
    keep = [why[i] is None for i in range(n)]
    if not any(keep):
        die("the plan removes every word")

    # Atoms: runs of kept words with no removed word between and no pause longer than keep_up_to.
    atoms, cur = [], []
    for i in range(n):
        if not keep[i]:
            if cur:
                atoms.append(cur)
                cur = []
            continue
        if cur and words[i]["start"] - words[cur[-1]]["end"] > pace["keep_up_to"] and not voiced_between(
                env, thr, words[cur[-1]]["end"], words[i]["start"]):
            atoms.append(cur)
            cur = []
        if cur and any(s_ < words[i]["start"] and e_ > words[cur[-1]]["end"] for s_, e_, _ in sound_cuts):
            atoms.append(cur)
            cur = []
        cur.append(i)
    if cur:
        atoms.append(cur)

    # Each atom's sound edges and the quiet around them, measured.
    edge = []
    for at in atoms:
        s0, e0 = words[at[0]]["start"], words[at[-1]]["end"]
        rb, ra = loud_edge(env, thr, s0, -1, 3.0), loud_edge(env, thr, e0, +1, 3.0)
        edge.append({"s": s0, "e": e0, "rb": rb, "ra": ra,
                     "in_sound_before": at[0] > 0 and not keep[at[0] - 1] and rb < 0.03,
                     "in_sound_after": at[-1] + 1 < n and not keep[at[-1] + 1] and ra < 0.03})
    head = [min(edge[0]["rb"], pace["lead"])] + [0.0] * (len(atoms) - 1)
    tail = [0.0] * (len(atoms) - 1) + [min(edge[-1]["ra"], pace["tail"])]
    for k in range(1, len(atoms)):
        a_, b_ = edge[k - 1], edge[k]
        long_gap = b_["s"] - a_["e"] >= 0.6
        target = pace["sentence"] if ends_sentence(words[atoms[k - 1][-1]]) or long_gap else pace["phrase"]
        tl = min(a_["ra"], max(MIN_TAIL, target * 0.55))
        hd = min(b_["rb"], max(0.0, target - tl))
        if tl + hd < target:
            tl = min(a_["ra"], target - hd)
        tail[k - 1], head[k] = tl, hd

    segs, tight = [], []
    for k, at in enumerate(atoms):
        e = edge[k]
        prev_end = words[at[0] - 1]["end"] if at[0] > 0 else 0.0
        next_start = words[at[-1] + 1]["start"] if at[-1] + 1 < n else duration
        if e["in_sound_before"]:
            cin = quietest(env, max(prev_end - 0.03, e["s"] - 0.12), e["s"] + 0.03)
            tight.append(("start", at[0], cin))
        else:
            cin = on_grid(e["s"] - head[k], fps, e["s"] - e["rb"], e["s"] - 0.01)
        if e["in_sound_after"]:
            cout = quietest(env, e["e"] - 0.03, min(next_start + 0.03, e["e"] + 0.12))
            tight.append(("end", at[-1], cout))
        else:
            cout = on_grid(e["e"] + tail[k], fps, e["e"] + 0.01, e["e"] + e["ra"])
        segs.append([max(0.0, cin), min(duration, cout)])

    # Merge pieces that touch, then write the edit list with each piece's place in the cut film.
    merged = []
    for s_, e_ in segs:
        if merged and s_ <= merged[-1][1] + 1e-3:
            merged[-1][1] = max(merged[-1][1], e_)
        else:
            merged.append([s_, e_])
    # Picture and sound are cut over the same whole frames ("in", "out"), so they stay in step at every join however
    # many there are. The sound is kept from "sound_in" to "sound_out", the measured cut points; render.py fades the
    # sliver of sound outside them (less than a frame) to silence.
    pos, pieces, prev = 0.0, [], 0.0
    end_grid = math.floor(duration * fps + 1e-6) / fps if duration else None
    for s_, e_ in merged:
        gi = max(math.floor(s_ * fps + 1e-6) / fps, prev)
        go = math.ceil(e_ * fps - 1e-6) / fps
        if end_grid is not None and go > end_grid:
            go = max(end_grid, gi + 1 / fps) if e_ > end_grid else end_grid
        if go - gi < 1 / fps - 1e-6:
            continue
        pieces.append({"in": round(gi, 6), "out": round(go, 6), "at": round(pos, 6),
                       "sound_in": round(max(s_, gi), 6), "sound_out": round(min(e_, go), 6)})
        pos += go - gi
        prev = go

    def to_cut(x):
        for pc in pieces:
            if pc["in"] - 1e-6 <= x <= pc["out"] + 1e-6:
                return round(pc["at"] + x - pc["in"], 3)
        return None

    removed = []
    i = 0
    while i < n:
        if keep[i]:
            i += 1
            continue
        j = i
        while j < n and not keep[j] and why[j] == why[i]:
            j += 1
        removed.append({"from": words[i]["start"], "to": words[j - 1]["end"], "why": why[i],
                        "text": " ".join(words[x]["w"].strip() for x in range(i, j))})
        i = j
    for f0, f1, reason in sound_cuts:
        removed.append({"from": f0, "to": f1, "why": reason, "text": "(sound without words)"})
    removed.sort(key=lambda r: r["from"])

    join_list = []
    for k in range(1, len(pieces)):
        a_, b_ = pieces[k - 1], pieces[k]
        ao, bi = a_["sound_out"], b_["sound_in"]
        lw = max((w for i, w in enumerate(words) if keep[i] and w["end"] <= ao + 1e-6), key=lambda w: w["end"])
        rw = min((w for i, w in enumerate(words) if keep[i] and w["start"] >= bi - 1e-6), key=lambda w: w["start"])
        gone = [r for r in removed if r["from"] >= ao - 0.2 and r["to"] <= bi + 0.2]
        join_list.append({"at": round(b_["at"] + bi - b_["in"], 6), "source_from": ao, "source_to": bi,
                          "pause": round((ao - lw["end"]) + (rw["start"] - bi), 3),
                          "removed": [g["text"] for g in gone], "why": sorted({g["why"] for g in gone}) or ["pause shortened"],
                          "inside_sound": any(abs(x[2] - ao) < 0.05 or abs(x[2] - bi) < 0.05 for x in tight)})

    cut_words = []
    for i, w in enumerate(words):
        if keep[i]:
            s_, e_ = to_cut(w["start"]), to_cut(w["end"])
            if s_ is not None and e_ is not None:
                cut_words.append({"w": w["w"], "start": s_, "end": e_, "p": w.get("p", 1.0)})
    out = Path(a.out)
    total = pieces[-1]["at"] + pieces[-1]["out"] - pieces[-1]["in"]
    write_json(out / "edl.json", {"source": str(Path(a.film).resolve()), "fps": fps, "width": info["width"],
                                  "height": info["height"], "duration_in": round(duration, 3), "duration_out": round(total, 3),
                                  "pace": pace_name, "pace_values": pace, "quiet_dbfs": round(thr, 1),
                                  "pieces": pieces, "joins": join_list, "removed": removed})
    tc = {k: v for k, v in t.items() if k not in ("words", "segments", "review", "edits")}
    tc.update({"source": str((out / "cut.mp4").resolve()), "duration": round(total, 3), "words": cut_words,
               "segments": [], "review": [], "edits": [], "cut_from": str(Path(a.film).resolve())})
    write_json(out / "transcript_cut.json", tc)

    md = [f"# Cut list: {Path(a.film).name}", "",
          f"{clock(duration)} -> {clock(total)} ({duration - total:.1f} s out), {len(pieces)} pieces, {len(join_list)} joins, "
          f"pace {pace_name}.", "", "## Removed", "", "| Source time | Words | Why | Length |", "|---|---|---|---|"]
    for r in removed:
        md.append(f"| {clock(r['from'])} | {r['text']} | {r['why']} | {r['to'] - r['from']:.2f} s |")
    md += ["", "## Joins (time in the cut film)", "", "| At | Pause kept | What was between | Note |", "|---|---|---|---|"]
    for j in join_list:
        note = "cut inside sound: listen here" if j["inside_sound"] else ""
        md.append(f"| {clock(j['at'])} | {j['pause']:.2f} s | {'; '.join(j['removed']) or 'a long pause'} | {note} |")
    (out / "cuts.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md[2:]))
    if tight:
        print(f"\n{len(tight)} cut(s) fall inside continuous sound (no pause to cut in): listen to those joins after "
              "rendering, or remove a little more so the cut lands in a pause.")
    print(f"-> {out / 'edl.json'}, transcript_cut.json, cuts.md")


if __name__ == "__main__":
    main()
