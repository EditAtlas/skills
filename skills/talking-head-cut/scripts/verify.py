"""Check the rendered cut by listening to it again with Whisper and comparing with the words you meant to keep.

  verify.py work/cut/cut.mp4 --cut work/cut [--model turbo]

A render that finished is not a cut that is right. This transcribes the cut film again and lines its words up with
transcript_cut.json (the words the plan kept):

  EXTRA      heard but not meant: a false start or a doubled word that rode along with a kept piece
  MISSING    meant but not heard: a word clipped at a join, or a piece lost
  FILLER     an um / uh / ờ still in the cut
  DOUBLED    the same words twice in a row in what was heard

Then it measures the joins (a cut inside sound, a join with no breath left), pauses longer than the pace allows,
and whether picture and sound end together, and writes seams.jpg: the frame before and after every join, so you
can look for a jump that needs a cover (B-roll, a punch-in) or a flash. Writes verify.md and verify.json.

Whisper mishears too: a word heard differently ("20" for "twenty") is listed apart, not as a fault. Every EXTRA or
MISSING line is a place to listen to, and you cannot hear: say what was measured, and ask the person to listen to
the lines this lists.
"""
import argparse
import difflib
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))  # also under python -I
from common import (HOP, SR, clock, decode, die, envelope_db, is_sure_filler, norm, probe, quiet_runs, read_json,
                    utf8_stdout, write_json)


def transcribe(path, language, model, prompt):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        die("faster-whisper is not installed. It comes with the EditAtlas transcribe skill: run its doctor.py --install.")
    import os
    names = {"turbo": "large-v3-turbo"}
    m = WhisperModel(names.get(model, model), device="auto", compute_type="int8",
                     cpu_threads=min(4, os.cpu_count() or 4))
    segs, _ = m.transcribe(str(path), language=language, word_timestamps=True, vad_filter=True,
                           vad_parameters={"min_silence_duration_ms": 300}, condition_on_previous_text=False,
                           initial_prompt=prompt, beam_size=5)
    return [{"w": w.word.strip(), "start": w.start, "end": w.end} for s in segs for w in (s.words or [])]


def flat(words):
    toks, owner = [], []
    for i, w in enumerate(words):
        for t in norm(w["w"]):
            toks.append(t)
            owner.append(i)
    return toks, owner


def to_source(t, pieces):
    for pc in pieces:
        if pc["at"] - 1e-6 <= t <= pc["at"] + pc["out"] - pc["in"] + 1e-6:
            return pc["in"] + t - pc["at"]
    return None


def seam_sheet(film, times, out, fps):
    """Frame before and after each join, side by side, one join per row (up to 24)."""
    rows = []
    for t in times[:24]:
        pair = []
        for x in (max(0.0, t - 1.0 / fps), t + 0.5 / fps):
            r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{x:.3f}", "-i", str(film), "-frames:v", "1",
                                "-vf", "scale=320:-2", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
            pair.append(r.stdout)
        if not all(pair) or len(pair[0]) != len(pair[1]) or len(pair[0]) % (320 * 3):
            continue
        h = len(pair[0]) // (320 * 3)
        a, b = (np.frombuffer(p, np.uint8).reshape(h, 320, 3) for p in pair)
        gap = np.full((h, 8, 3), 255, np.uint8)
        rows.append(np.concatenate([a, gap, b], axis=1))
    if not rows:
        return False
    img = np.concatenate([np.concatenate([r, np.full((6, r.shape[1], 3), 255, np.uint8)]) for r in rows])
    raw = Path(tempfile.mkdtemp()) / "sheet.rgb"
    raw.write_bytes(img.tobytes())
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{img.shape[1]}x{img.shape[0]}",
                    "-i", str(raw), "-q:v", "3", str(out)], check=True)
    return True


def main():
    utf8_stdout()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("film")
    p.add_argument("--cut", required=True, help="folder with edl.json and transcript_cut.json from cut.py")
    p.add_argument("--model", help="Whisper model (default: the one the transcript was made with)")
    a = p.parse_args()
    cut = Path(a.cut)
    edl, tc = read_json(cut / "edl.json"), read_json(cut / "transcript_cut.json")
    info = probe(a.film)
    fps = info["fps"] or edl.get("fps") or 30
    settings = tc.get("settings") or {}
    model = a.model or tc.get("model") or "small"
    heard = transcribe(a.film, tc.get("language"), model, settings.get("prompt") if settings.get("verbatim") else None)
    exp_t, exp_o = flat(tc["words"])
    got_t, got_o = flat(heard)
    findings, misheard = [], []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, exp_t, got_t, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        exp = " ".join(exp_t[i1:i2])
        got = " ".join(got_t[j1:j2])
        # The middle of a word: Whisper often starts the first word after a pause too early.
        w0 = heard[got_o[j1]] if j2 > j1 else tc["words"][exp_o[min(i1, len(exp_o) - 1)]]
        t_cut = (w0["start"] + w0["end"]) / 2
        if op == "replace" and abs((i2 - i1) - (j2 - j1)) <= 1 and max(i2 - i1, j2 - j1) <= 3:
            misheard.append({"at": round(t_cut, 2), "meant": exp, "heard": got})
            continue
        if op in ("insert", "replace") and j2 > j1:
            words = [heard[got_o[j]] for j in sorted(set(got_o[j1:j2]))]
            kind = "FILLER" if all(is_sure_filler(w) for w in words) else "EXTRA"
            findings.append({"kind": kind, "at": round(t_cut, 2), "text": got})
        if op in ("delete", "replace") and i2 > i1:
            findings.append({"kind": "MISSING", "at": round(t_cut, 2), "text": exp})
    for n in range(4, 0, -1):
        for k in range(len(got_t) - 2 * n + 1):
            if got_t[k:k + n] == got_t[k + n:k + 2 * n] and " ".join(got_t[k:k + 2 * n]) not in " ".join(exp_t):
                w0 = heard[got_o[k]]
                findings.append({"kind": "DOUBLED", "at": round((w0["start"] + w0["end"]) / 2, 2), "text": " ".join(got_t[k:k + n])})
    for f in findings:
        src = to_source(f["at"], edl["pieces"])
        f["source"] = None if src is None else round(src, 2)

    # Joins and pauses, measured on the cut's own sound.
    env = envelope_db(decode(a.film))
    thr = edl.get("quiet_dbfs", -50)
    pace = edl.get("pace_values") or {}
    joins = []
    for j in edl.get("joins", []):
        i = int(round(j["at"] / HOP))
        near = env[max(0, i - 2):i + 2]
        runs = [r for r in quiet_runs(env, thr, j["at"] - 2.0, j["at"] + 2.0) if r[0] - 0.02 <= j["at"] <= r[1] + 0.02]
        quiet = (runs[0][1] - runs[0][0]) if runs else 0.0
        joins.append({"at": j["at"], "in_sound": bool(len(near) and near.max() > thr + 10), "pause": round(quiet, 2)})
    for j in joins:
        if j["in_sound"]:
            findings.append({"kind": "JOIN IN SOUND", "at": j["at"], "text": "the cut is not in a pause: listen for a click or a clipped word"})
        elif j["pause"] < 0.08:
            findings.append({"kind": "NO BREATH", "at": j["at"], "text": f"only {j['pause']:.2f} s of quiet at this join"})
    limit = pace.get("keep_up_to", 0.8) + 0.25
    loud = np.nonzero(env > thr)[0]
    if len(loud):
        for s_, e_ in quiet_runs(env, thr, loud[0] * HOP, loud[-1] * HOP):
            if e_ - s_ > limit:
                findings.append({"kind": "LONG PAUSE", "at": round(s_, 2), "text": f"{e_ - s_:.2f} s of quiet"})
    av = None
    if info["v_duration"] and info["a_duration"]:
        av = round(abs(info["v_duration"] - info["a_duration"]), 3)
        if av > 1.5 / fps:
            findings.append({"kind": "A/V", "at": 0, "text": f"picture and sound lengths differ by {av:.3f} s"})
    findings.sort(key=lambda f: f["at"])
    sheet = cut / "seams.jpg"
    has_sheet = info["has_video"] and seam_sheet(a.film, [j["at"] for j in edl.get("joins", [])], sheet, fps)

    write_json(cut / "verify.json", {"film": str(Path(a.film).resolve()), "model": model, "words_meant": len(exp_t),
                                     "words_heard": len(got_t), "findings": findings, "misheard": misheard,
                                     "joins": joins, "av_diff": av})
    md = [f"# Check of {Path(a.film).name}", "",
          f"Whisper ({model}) heard {len(got_t)} words; the plan kept {len(exp_t)}. {len(findings)} thing(s) to listen to, "
          f"{len(misheard)} word(s) heard differently (usually Whisper, not the cut).", ""]
    if findings:
        md += ["| Kind | Cut time | Source time | What |", "|---|---|---|---|"]
        md += [f"| {f['kind']} | {clock(f['at'])} | {'' if f['source'] is None else clock(f['source'])} | {f['text']} |"
               for f in findings]
    else:
        md.append("Nothing extra, missing or doubled was heard; every join is in a pause.")
    if misheard:
        md += ["", "Heard differently: " + "; ".join(f"{clock(m['at'])} \"{m['meant']}\" as \"{m['heard']}\"" for m in misheard)]
    if has_sheet:
        md += ["", f"seams.jpg: frame before | frame after each join, top to bottom in the order of the joins "
                   f"({min(24, len(edl.get('joins', [])))} shown). Look at it."]
    (cut / "verify.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    print(f"-> {cut / 'verify.md'}")


if __name__ == "__main__":
    main()
