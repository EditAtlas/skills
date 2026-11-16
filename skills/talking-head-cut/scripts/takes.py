"""Read a raw take as numbered lines, with what to look at marked, before you decide what to cut.

  takes.py work/t/transcript.json FILM.mp4 --out work/cut

Needs the transcript from the EditAtlas transcribe skill, made with --verbatim (fillers and false starts kept).
Writes takes.md (the lines to read) and takes.json (each line's words and times, for cut.py). Marks:

  NOTE?      words said to the editor ("take two", "nói lại nhé", "cut that")
  RETAKE?    a line said again, nearly the same, a little later: usually keep the later complete one
  UNFINISHED a line Whisper heard break off ("...", "-") or that runs into a note to the editor
  DOUBLED    the same words twice in a row ("the best part the best part is")
  [um]       a sure filler; cut.py removes these unless the plan says "fillers": false
  SOUND?     voice the transcript has no words for: often a false start Whisper skipped; listen or look

Nothing here is a decision. Read every line, then write the plan (references/formats.md).
"""
import argparse
import difflib
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))  # also under python -I
from common import (HOP, clock, decode, ends_sentence, envelope_db, gaps_between, is_sure_filler, tighten, levels, norm, note_hits,
                    read_json, utf8_stdout, word_tokens, write_json)

LINE_GAP = 0.4       # a measured pause this long starts a new line even without a full stop


def split_lines(words, gaps):
    lines, cur = [], []
    for i, w in enumerate(words):
        cur.append(i)
        if i + 1 == len(words) or ends_sentence(w) or gaps[i] >= LINE_GAP:
            lines.append(cur)
            cur = []
    return lines


def similar(a, b):
    """How much of the shorter line the longer one repeats, 0 to 1."""
    if not a or not b:
        return 0.0
    m = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return sum(x.size for x in m.get_matching_blocks()) / min(len(a), len(b))


def doubled(tokens):
    """Runs of 1 to 5 tokens said twice in a row."""
    hits = []
    for n in range(5, 0, -1):
        for k in range(len(tokens) - 2 * n + 1):
            if tokens[k:k + n] == tokens[k + n:k + 2 * n] and not any(k < e and k + 2 * n > s for s, e, _ in hits):
                hits.append((k, k + 2 * n, " ".join(tokens[k:k + n])))
    return hits


def unheard_sound(env, thr, words, duration):
    """Stretches of 0.25 s or more louder than the quiet level that no word covers."""
    covered = np.zeros(len(env), bool)
    for w in words:
        covered[max(0, int(w["start"] / HOP) - 5):int(w["end"] / HOP) + 6] = True
    loud = (env > thr + 6) & ~covered
    out, i = [], 0
    while i < len(loud):
        if loud[i]:
            j = i
            while j < len(loud) and loud[j]:
                j += 1
            if (j - i) * HOP >= 0.25:
                out.append((i * HOP, min(duration, j * HOP)))
            i = j
        else:
            i += 1
    return out


def main():
    utf8_stdout()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("transcript")
    p.add_argument("film")
    p.add_argument("--out", required=True)
    a = p.parse_args()
    t = read_json(a.transcript)
    words, lang = t["words"], t.get("language") or "en"
    if not words:
        sys.exit("takes.py: the transcript has no words")
    if not (t.get("settings") or {}).get("verbatim"):
        print("note: this transcript was made without --verbatim, so Whisper may have tidied away fillers and false "
              "starts; run transcribe.py again with --verbatim for a cut.")
    audio = decode(a.film)
    env = envelope_db(audio)
    thr, speech, floor = levels(env, words)
    toks = word_tokens(words)
    duration = t.get("duration") or len(env) * HOP
    words = tighten(words, env, thr)
    gaps = gaps_between(words, duration)
    lines = split_lines(words, gaps)
    flat = [[x for i in ln for x in toks[i]] for ln in lines]
    rows = []
    for n, ln in enumerate(lines):
        text = " ".join(words[i]["w"].strip() for i in ln)
        start, end = words[ln[0]]["start"], words[ln[-1]]["end"]
        pause = gaps[ln[-1]]
        marks = []
        for hit in note_hits(text, lang):
            marks.append(f'NOTE? "{hit}"')
        for m in range(n + 1, min(len(lines), n + 5)):
            s = similar(flat[n], flat[m])
            if min(len(flat[n]), len(flat[m])) >= 3 and s >= 0.6:
                marks.append(f"RETAKE? said again in L{m + 1} ({s:.0%} the same)")
                break
        if re.search(r"(\.\.\.|…|-|—)$", words[ln[-1]]["w"].strip()) or (
                n + 1 < len(lines) and not ends_sentence(words[ln[-1]]) and note_hits(" ".join(flat[n + 1]), lang)):
            marks.append("UNFINISHED")
        joined = flat[n] + (flat[n + 1] if n + 1 < len(lines) and pause < 0.3 else [])
        for s_, e_, phrase in doubled(joined):
            if s_ < len(flat[n]):
                marks.append(f'DOUBLED "{phrase}"')
        fill = [words[i]["w"].strip() for i in ln if is_sure_filler(words[i])]
        if fill:
            marks.append("fillers " + ", ".join(f"[{f}]" for f in fill))
        rows.append({"line": n + 1, "first": ln[0], "last": ln[-1], "start": start, "end": end,
                     "pause_after": round(pause, 2), "text": text, "marks": marks})
    sounds = unheard_sound(env, thr, words, duration)
    for s_, e_ in sounds:
        after = max((r for r in rows if r["end"] <= s_ + 0.05), key=lambda r: r["end"], default=None)
        if after:
            after["marks"].append(f"SOUND? {clock(s_)}-{clock(e_)} after this line has no words")
    write_json(Path(a.out) / "takes.json", {"transcript": str(Path(a.transcript).resolve()), "film": str(Path(a.film).resolve()),
                                            "language": lang, "quiet_dbfs": round(thr, 1), "speech_dbfs": round(speech, 1),
                                            "floor_dbfs": round(floor, 1), "lines": rows,
                                            "unheard": [[round(s, 2), round(e, 2)] for s, e in sounds]})
    out = [f"# Takes: {Path(a.film).name}", "",
           f"{len(rows)} lines, {len(words)} words, {t.get('duration', 0):.1f} s. Speech at {speech:.0f} dBFS, quiet under "
           f"{thr:.0f} dBFS. Pause = silence after the line.", "",
           "| Line | Time | Pause | Text | Look at |", "|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| L{r['line']} | {clock(r['start'])} | {r['pause_after']:.2f} | {r['text']} | {'; '.join(r['marks'])} |")
    (Path(a.out) / "takes.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    flagged = sum(bool(r["marks"]) for r in rows)
    print("\n".join(out[6:]))
    print(f"\n{len(rows)} lines, {flagged} marked, {len(sounds)} stretches of voice without words -> {Path(a.out) / 'takes.md'}")


if __name__ == "__main__":
    main()
