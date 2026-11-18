"""Turn your plan (what to remove, by quoting the words) into an edit list whose every cut sits in silence.

  cut.py work/t/transcript.json FILM.mp4 work/cut/plan.json --out work/cut [--pace natural|tight|keep]
  cut.py work/tA/transcript.json A.mp4 work/tB/transcript.json B.mp4 ... work/cut/plan.json --out work/cut

You never type a time for a word. You quote it, and this script finds it, measures where its sound really starts
and ends, and puts each cut in the quiet beside it. Pauses longer than the pace allows are shortened to a natural
breath, not removed. With several files (takes of the same script), give every transcript and film in the order
takes.py named them (A, B, C...), and the plan's "takes" list picks the lines to use, in the order they play.
Writes:

  edl.json             the pieces of the source(s) to keep, in order, for render.py and for the EditAtlas studio
  transcript_cut.json  the kept words with times in the cut film (for captions; same format as the transcribe skill)
  cuts.md              every removal with its words, reason and length, every join with its pause; show the person

Plan format and every field: references/formats.md.
"""
import argparse
import math
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))  # also under python -I
from common import (HOP, clock, decode, die, ends_sentence, envelope_db, is_sure_filler, islands, norm, probe, read_json,
                    tighten, utf8_stdout, voice_levels, word_tokens, write_json)

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


def line_ref(ref, multi):
    """A line as takes.json names it: 12 for one file, "B12" for several."""
    r = str(ref).strip().upper()
    if not multi:
        return int(r.lstrip("L"))
    if not re.fullmatch(r"[A-Z]\d+", r):
        die(f'line "{ref}": with several files, name lines by file and number, as takes.md does ("B12")')
    return r


def find_line(lines, ref, multi):
    want = line_ref(ref, multi)
    ln = next((x for x in lines if x["line"] == want), None)
    if not ln:
        die(f"line {ref} is not in takes.json")
    return ln


def find_quote(item, words, toks, lines, multi=False):
    """Word indexes [a, b) the quote names. Lines narrow the search; "near" picks among several."""
    q = norm(item["quote"])
    if not q:
        die(f"empty quote in {item}")
    lo, hi = 0, len(words)
    if "line" in item:
        ln = find_line(lines, item["line"], multi)
        lo, hi = ln["first"], ln["last"] + 1
    elif multi:
        die(f'with several files, a quote needs "line" (as takes.md names it, "B12"): {item}')
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


def parse_lines(spec, lines, multi=False):
    """[(source label or None, first word, last word + 1)] for "5", "5-7", "5, 8" (one file) or "B5", "B5-B7", "B5-7"."""
    out = []
    for part in str(spec).replace(" ", "").split(","):
        a, _, b = part.partition("-")
        if multi:
            a = line_ref(a, True)
            b = line_ref(b if b and not b.isdigit() else a[0] + (b or a[1:]), True)
            if a[0] != b[0]:
                die(f'"{part}": a range of lines stays in one file')
            nums = range(int(a[1:]), int(b[1:]) + 1)
            refs = [f"{a[0]}{n}" for n in nums]
        else:
            refs = list(range(int(a.lstrip("L")), int((b or a).lstrip("L")) + 1))
        for r in refs:
            ln = find_line(lines, r, multi)
            out.append((ln.get("source"), ln["first"], ln["last"] + 1))
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


class Source:
    """One recording: its transcript words moved onto the measured sound, its levels and its frame rate."""

    def __init__(self, label, transcript, film):
        self.label, self.film = label, film
        self.t = read_json(transcript)
        self.info = probe(film)
        self.fps = self.info["fps"] or 30.0
        self.duration = self.info["duration"] or self.t.get("duration")
        audio = decode(film)
        self.env, self.thr, self.speech, self.floor, self.how = voice_levels(audio, envelope_db(audio), self.t["words"])
        self.words = tighten(self.t["words"], self.env, self.thr)
        self.toks = word_tokens(self.words)
        self.n = len(self.words)
        self.why = [None] * self.n          # reason a word is removed
        self.sound_cuts = []                # (from, to, why) stretches with no words
        self.kept_fillers = set()


def main():
    utf8_stdout()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("files", nargs="+", metavar="TRANSCRIPT FILM ... PLAN",
                   help="transcript.json and film (one pair per file, in takes.py's order), then plan.json")
    p.add_argument("--out", required=True)
    p.add_argument("--takes", help="takes.json from takes.py (default: the one in --out)")
    p.add_argument("--pace", choices=sorted(PACES), help="overrides the plan's pace")
    a = p.parse_args()
    if len(a.files) < 3 or len(a.files) % 2 == 0:
        p.error("give TRANSCRIPT FILM (one pair per file), then PLAN")
    pairs = [(a.files[k], a.files[k + 1]) for k in range(0, len(a.files) - 1, 2)]
    multi = len(pairs) > 1
    plan = read_json(a.files[-1])
    takes = read_json(a.takes or Path(a.out) / "takes.json")
    pace_name = a.pace or plan.get("pace", "natural")
    if pace_name not in PACES:
        die(f"pace must be one of {sorted(PACES)}")
    pace = PACES[pace_name]
    if multi and len(takes.get("sources", [])) != len(pairs):
        die(f"takes.json has {len(takes.get('sources', [])) or 1} file(s) and you gave {len(pairs)}: run takes.py with the "
            "same files, in the same order")
    labels = [chr(65 + k) for k in range(len(pairs))] if multi else [None]
    src = {lb: Source(lb, t_, f_) for lb, (t_, f_) in zip(labels, pairs)}
    lines = takes["lines"]

    def lines_of(lb):
        return [x for x in lines if x.get("source") == lb] if multi else lines

    def source_of(item, what):
        if not multi:
            return src[None]
        if "line" in item:
            return src[line_ref(item["line"], True)[0]]
        if "file" in item and str(item["file"]).upper() in src:
            return src[str(item["file"]).upper()]
        die(f'with several files, {what} needs "line" ("B12") or "file" ("B"): {item}')

    # The takes to use, in the order they play. One file: the whole recording.
    units = []
    if multi:
        if not plan.get("takes"):
            die('with several files the plan needs "takes": the lines to use, in order, each with a quote and why '
                '(references/formats.md)')
        for pick in plan["takes"]:
            if "lines" not in pick or "quote" not in pick:
                die(f'every item in "takes" needs "lines" ("B4-B6") and "quote" (words from those lines): {pick}')
            spans = parse_lines(pick["lines"], lines, True)
            lb = spans[0][0]
            if any(s[0] != lb for s in spans):
                die(f'"{pick["lines"]}": one take is one range of lines in one file; list another file as its own item')
            first, last = min(s[1] for s in spans), max(s[2] for s in spans)
            sub = [x for x in lines_of(lb) if x["first"] >= first and x["last"] < last]
            s_ = src[lb]
            qt = norm(pick["quote"])
            flat = [tk for i in range(first, last) for tk in s_.toks[i]]
            if not qt or not any(flat[k:k + len(qt)] == qt for k in range(len(flat) - len(qt) + 1)):
                die(f'the quote "{pick["quote"]}" is not in {pick["lines"]}, which says: '
                    f'"{" ".join(x["text"] for x in sub)[:300]}". Check the line numbers in takes.md.')
            units.append({"src": lb, "first": first, "last": last, "pick": pick})
        used = {}
        for u in units:
            for i in range(u["first"], u["last"]):
                if (u["src"], i) in used:
                    die(f'{u["pick"]["lines"]} and {used[(u["src"], i)]} use the same words; each line plays once')
                used[(u["src"], i)] = u["pick"]["lines"]
    else:
        units.append({"src": None, "first": 0, "last": src[None].n, "pick": None})

    for item in plan.get("remove", []):
        reason = item.get("why") or "removed"
        s_ = source_of(item, "a remove item") if ("line" in item or "file" in item or not multi) else None
        if "lines" in item:
            spans = parse_lines(item["lines"], lines, multi)
            s_ = src[spans[0][0]]
            spans = [(x[1], x[2]) for x in spans if x[0] == spans[0][0]]
        elif "quote" in item:
            s_ = source_of(item, "a quote")
            spans = [find_quote(item, s_.words, s_.toks, lines_of(s_.label), multi)]
        elif "from" in item and "to" in item:
            s_ = source_of(item, '"from"/"to"')
            f0, f1 = float(item["from"]), float(item["to"])
            s_.sound_cuts.append((f0, f1, reason))
            spans = [(i, i + 1) for i, w in enumerate(s_.words) if w["start"] < f1 and w["end"] > f0]
        else:
            die(f"a remove item needs lines, quote, or from and to: {item}")
        for a_, b_ in spans:
            for i in range(a_, b_):
                s_.why[i] = s_.why[i] or reason
    for item in plan.get("keep", []):
        s_ = source_of(item, "a keep item")
        a_, b_ = find_quote(item, s_.words, s_.toks, lines_of(s_.label), multi)
        s_.kept_fillers.update(range(a_, b_))
        for i in range(a_, b_):
            s_.why[i] = None
    picked = {lb: np.zeros(s_.n, bool) for lb, s_ in src.items()}
    for u in units:
        picked[u["src"]][u["first"]:u["last"]] = True
    for lb, s_ in src.items():
        if plan.get("fillers", True):
            for i, w in enumerate(s_.words):
                if s_.why[i] is None and i not in s_.kept_fillers and is_sure_filler(w):
                    s_.why[i] = "filler"
        s_.keep = [s_.why[i] is None and bool(picked[lb][i]) for i in range(s_.n)]
    if not any(any(s_.keep) for s_ in src.values()):
        die("the plan removes every word")

    # Output frame rate and size: the file that gives the most kept time; the others are converted to it.
    kept_time = Counter()
    for lb, s_ in src.items():
        kept_time[lb] = sum(w["end"] - w["start"] for i, w in enumerate(s_.words) if s_.keep[i])
    main_src = src[kept_time.most_common(1)[0][0]] if multi else src[None]
    fps = main_src.fps

    # Atoms: runs of kept words of one take with no removed word between and no pause longer than keep_up_to.
    atoms = []      # (source label, [word indexes], unit number)
    for un, u in enumerate(units):
        s_ = src[u["src"]]
        words, env, thr, keep = s_.words, s_.env, s_.thr, s_.keep
        cur = []
        for i in range(u["first"], u["last"]):
            if not keep[i]:
                if cur:
                    atoms.append((u["src"], cur, un))
                    cur = []
                continue
            if cur and words[i]["start"] - words[cur[-1]]["end"] > pace["keep_up_to"] and not voiced_between(
                    env, thr, words[cur[-1]]["end"], words[i]["start"]):
                atoms.append((u["src"], cur, un))
                cur = []
            if cur and any(f0 < words[i]["start"] and f1 > words[cur[-1]]["end"] for f0, f1, _ in s_.sound_cuts):
                atoms.append((u["src"], cur, un))
                cur = []
            cur.append(i)
        if cur:
            atoms.append((u["src"], cur, un))

    # Each atom's sound edges and the quiet around them, measured.
    edge = []
    for lb, at, _ in atoms:
        s_ = src[lb]
        s0, e0 = s_.words[at[0]]["start"], s_.words[at[-1]]["end"]
        rb, ra = loud_edge(s_.env, s_.thr, s0, -1, 3.0), loud_edge(s_.env, s_.thr, e0, +1, 3.0)
        edge.append({"s": s0, "e": e0, "rb": rb, "ra": ra,
                     "in_sound_before": at[0] > 0 and not s_.keep[at[0] - 1] and rb < 0.03,
                     "in_sound_after": at[-1] + 1 < s_.n and not s_.keep[at[-1] + 1] and ra < 0.03})
    head = [min(edge[0]["rb"], pace["lead"])] + [0.0] * (len(atoms) - 1)
    tail = [0.0] * (len(atoms) - 1) + [min(edge[-1]["ra"], pace["tail"])]
    for k in range(1, len(atoms)):
        a_, b_ = edge[k - 1], edge[k]
        prev_words = src[atoms[k - 1][0]].words
        if atoms[k - 1][2] == atoms[k][2]:
            long_gap = b_["s"] - a_["e"] >= 0.6
        else:
            long_gap = True      # another take starts: a breath between sentences
        target = pace["sentence"] if ends_sentence(prev_words[atoms[k - 1][1][-1]]) or long_gap else pace["phrase"]
        tl = min(a_["ra"], max(MIN_TAIL, target * 0.55))
        hd = min(b_["rb"], max(0.0, target - tl))
        if tl + hd < target:
            tl = min(a_["ra"], target - hd)
        tail[k - 1], head[k] = tl, hd

    segs, tight = [], []
    for k, (lb, at, _) in enumerate(atoms):
        s_ = src[lb]
        words, env = s_.words, s_.env
        e = edge[k]
        prev_end = words[at[0] - 1]["end"] if at[0] > 0 else 0.0
        next_start = words[at[-1] + 1]["start"] if at[-1] + 1 < s_.n else s_.duration
        if e["in_sound_before"]:
            cin = quietest(env, max(prev_end - 0.03, e["s"] - 0.12), e["s"] + 0.03)
            tight.append((lb, "start", at[0], cin))
        else:
            cin = on_grid(e["s"] - head[k], fps, e["s"] - e["rb"], e["s"] - 0.01)
        if e["in_sound_after"]:
            cout = quietest(env, e["e"] - 0.03, min(next_start + 0.03, e["e"] + 0.12))
            tight.append((lb, "end", at[-1], cout))
        else:
            cout = on_grid(e["e"] + tail[k], fps, e["e"] + 0.01, e["e"] + e["ra"])
        segs.append([lb, max(0.0, cin), min(s_.duration, cout)])

    # Merge pieces of one file that touch, then write the edit list with each piece's place in the cut film.
    merged = []
    for lb, s_, e_ in segs:
        if merged and merged[-1][0] == lb and s_ <= merged[-1][2] + 1e-3 and (not multi or merged[-1][1] <= s_):
            merged[-1][2] = max(merged[-1][2], e_)
        else:
            merged.append([lb, s_, e_])
    # Picture and sound are cut over the same whole frames ("in", "out"), so they stay in step at every join however
    # many there are. The sound is kept from "sound_in" to "sound_out", the measured cut points; render.py fades the
    # sliver of sound outside them (less than a frame) to silence. With several files the frames are those of the
    # output frame rate, counted from the start of each file.
    pos, pieces, prev = 0.0, [], None
    for lb, s_, e_ in merged:
        dur = src[lb].duration
        end_grid = math.floor(dur * fps + 1e-6) / fps if dur else None
        gi = math.floor(s_ * fps + 1e-6) / fps
        if prev and prev[0] == lb and prev[1] <= s_ + 1e-6:      # the same file, going on: never overlap the piece before
            gi = max(gi, prev[2])
        go = math.ceil(e_ * fps - 1e-6) / fps
        if end_grid is not None and go > end_grid:
            go = max(end_grid, gi + 1 / fps) if e_ > end_grid else end_grid
        if go - gi < 1 / fps - 1e-6:
            continue
        pc = {"in": round(gi, 6), "out": round(go, 6), "at": round(pos, 6),
              "sound_in": round(max(s_, gi), 6), "sound_out": round(min(e_, go), 6)}
        if multi:
            pc = {"src": lb, **pc}
        pieces.append(pc)
        pos += go - gi
        prev = (lb, gi, go)

    def to_cut(lb, x):
        for pc in pieces:
            if pc.get("src") == lb and pc["in"] - 1e-6 <= x <= pc["out"] + 1e-6:
                return round(pc["at"] + x - pc["in"], 3)
        return None

    removed = []
    for lb, s_ in src.items():
        words, keep, why = s_.words, s_.keep, s_.why
        i = 0
        while i < s_.n:
            if keep[i] or why[i] is None:      # kept, or (several files) a line no take uses
                i += 1
                continue
            j = i
            while j < s_.n and not keep[j] and why[j] == why[i]:
                j += 1
            r = {"from": words[i]["start"], "to": words[j - 1]["end"], "why": why[i],
                 "text": " ".join(words[x]["w"].strip() for x in range(i, j))}
            removed.append({"src": lb, **r} if multi else r)
            i = j
        for f0, f1, reason in s_.sound_cuts:
            r = {"from": f0, "to": f1, "why": reason, "text": "(sound without words)"}
            removed.append({"src": lb, **r} if multi else r)
    removed.sort(key=lambda r: (r.get("src") or "", r["from"]))

    join_list = []
    for k in range(1, len(pieces)):
        a_, b_ = pieces[k - 1], pieces[k]
        la, lb_ = a_.get("src"), b_.get("src")
        ao, bi = a_["sound_out"], b_["sound_in"]
        sa, sb = src[la], src[lb_]
        lw = max((w for i, w in enumerate(sa.words) if sa.keep[i] and w["end"] <= ao + 1e-6), key=lambda w: w["end"])
        rw = min((w for i, w in enumerate(sb.words) if sb.keep[i] and w["start"] >= bi - 1e-6), key=lambda w: w["start"])
        same = la == lb_ and ao <= bi
        gone = [r for r in removed if same and r.get("src") == la and r["from"] >= ao - 0.2 and r["to"] <= bi + 0.2]
        j = {"at": round(b_["at"] + bi - b_["in"], 6), "source_from": ao, "source_to": bi,
             "pause": round((ao - lw["end"]) + (rw["start"] - bi), 3),
             "removed": [g["text"] for g in gone],
             "why": sorted({g["why"] for g in gone}) or (["pause shortened"] if same else ["next take"]),
             "inside_sound": any(x[0] == la and abs(x[3] - ao) < 0.05 for x in tight) or
             any(x[0] == lb_ and abs(x[3] - bi) < 0.05 for x in tight)}
        if multi:
            j = {"from_src": la, "to_src": lb_, **j}
        join_list.append(j)

    cut_words = []
    for lb, at, _ in atoms:
        for i in at:
            w = src[lb].words[i]
            s_, e_ = to_cut(lb, w["start"]), to_cut(lb, w["end"])
            if s_ is not None and e_ is not None:
                cut_words.append({"w": w["w"], "start": s_, "end": e_, "p": w.get("p", 1.0)})
    out = Path(a.out)
    total = pieces[-1]["at"] + pieces[-1]["out"] - pieces[-1]["in"]
    first = src[labels[0]]
    duration = sum(s_.duration for s_ in src.values())
    measured = {s_.how for s_ in src.values()}
    edl = {"source": str(Path(first.film).resolve()), "fps": fps, "width": main_src.info["width"],
           "height": main_src.info["height"], "duration_in": round(duration, 3), "duration_out": round(total, 3),
           "pace": pace_name, "pace_values": pace, "quiet_dbfs": round(max(s_.thr for s_ in src.values()), 1)}
    if measured != {"level"}:
        edl["measured_with"] = "level and VAD" if "level and VAD" in measured else sorted(measured)[0]
    if multi:
        edl["sources"] = [{"label": lb, "path": str(Path(s_.film).resolve()), "fps": s_.fps, "width": s_.info["width"],
                           "height": s_.info["height"], "duration": round(s_.duration, 3), "quiet_dbfs": round(s_.thr, 1),
                           "measured_with": s_.how} for lb, s_ in src.items()]
        edl["takes"] = [{"src": u["src"], "lines": u["pick"]["lines"], "quote": u["pick"]["quote"],
                         "why": u["pick"].get("why", "")} for u in units]
        convert = [s_ for s_ in src.values() if s_.fps != fps or (s_.info["width"], s_.info["height"]) !=
                   (main_src.info["width"], main_src.info["height"])]
        edl["normalised"] = [f"{s_.label}: {s_.info['width']}x{s_.info['height']} at {s_.fps:g} fps -> "
                             f"{main_src.info['width']}x{main_src.info['height']} at {fps:g} fps" for s_ in convert]
    edl.update({"pieces": pieces, "joins": join_list, "removed": removed})
    write_json(out / "edl.json", edl)
    t = first.t
    tc = {k: v for k, v in t.items() if k not in ("words", "segments", "review", "edits")}
    tc.update({"source": str((out / "cut.mp4").resolve()), "duration": round(total, 3), "words": cut_words,
               "segments": [], "review": [], "edits": [], "cut_from": str(Path(first.film).resolve())})
    if multi:
        tc["cut_from"] = [str(Path(s_.film).resolve()) for s_ in src.values()]
    write_json(out / "transcript_cut.json", tc)

    name = Path(first.film).name if not multi else ", ".join(f"{lb} {Path(s_.film).name}" for lb, s_ in src.items())
    md = [f"# Cut list: {name}", "",
          f"{clock(duration)} -> {clock(total)} ({duration - total:.1f} s out), {len(pieces)} pieces, {len(join_list)} joins, "
          f"pace {pace_name}.", ""]
    if multi:
        md += ["## Takes used, in order", "", "| Lines | Starts with | Why this take |", "|---|---|---|"]
        md += [f"| {x['lines']} | {x['quote']} | {x['why']} |" for x in edl["takes"]]
        for x in edl["normalised"]:
            md.append(f"\nConverted to match: {x} (scaled to fit, bars where the shape differs; frames repeated or "
                      "dropped to the frame rate).")
        md += ["", "## Removed inside the takes used", "", "| File | Source time | Words | Why | Length |", "|---|---|---|---|---|"]
        for r in removed:
            md.append(f"| {r['src']} | {clock(r['from'])} | {r['text']} | {r['why']} | {r['to'] - r['from']:.2f} s |")
    else:
        md += ["## Removed", "", "| Source time | Words | Why | Length |", "|---|---|---|---|"]
        for r in removed:
            md.append(f"| {clock(r['from'])} | {r['text']} | {r['why']} | {r['to'] - r['from']:.2f} s |")
    md += ["", "## Joins (time in the cut film)", "", "| At | Pause kept | What was between | Note |", "|---|---|---|---|"]
    for j in join_list:
        note = "cut inside sound: listen here" if j["inside_sound"] else ""
        between = "; ".join(j["removed"]) or ("a long pause" if j["why"] != ["next take"] else
                                              f"from {j['from_src']} to {j['to_src']}" if multi else "")
        md.append(f"| {clock(j['at'])} | {j['pause']:.2f} s | {between} | {note} |")
    (out / "cuts.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md[2:]))
    if tight:
        print(f"\n{len(tight)} cut(s) fall inside continuous sound (no pause to cut in): listen to those joins after "
              "rendering, or remove a little more so the cut lands in a pause.")
    print(f"-> {out / 'edl.json'}, transcript_cut.json, cuts.md")


if __name__ == "__main__":
    main()
