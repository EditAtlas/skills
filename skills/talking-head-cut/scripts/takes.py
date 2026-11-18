"""Read a raw take as numbered lines, with what to look at marked, before you decide what to cut.

  takes.py work/t/transcript.json FILM.mp4 --out work/cut

Needs the transcript from the EditAtlas transcribe skill, made with --verbatim (fillers and false starts kept).
Writes takes.md (the lines to read) and takes.json (each line's words and times, for cut.py). Marks:

  NOTE?      words said to the editor ("take two", "nói lại nhé", "cut that")
  RETAKE?    a line said again, nearly the same, a little later: usually keep the later complete one
  UNFINISHED a line Whisper heard break off ("...", "-") or that runs into a note to the editor, and that is said
             again within three lines (a false start)
  BREAKS OFF a line that breaks off and then goes on in the next line ("Và tai này thì... / nó đã có..."): a pause
             in one sentence, not a false start; usually kept
  DOUBLED    the same words twice in a row ("the best part the best part is"), with the plan item that removes
             only the first copy: never remove the whole line for it
  [um]       a sure filler; cut.py removes these unless the plan says "fillers": false
  SOUND?     voice the transcript has no words for: often a false start Whisper skipped; listen or look
  LONG WORD? a word that lasts far longer than this speaker's words do: Whisper may have left out a repeat or a
             false start there (it often writes "and that is that every" once when it was said twice)
  HEARD      what Whisper hears in a LONG WORD? or SOUND? line when it transcribes that line alone (--relisten,
             on by default when faster-whisper is installed): more words than the line has = something to remove

Nothing here is a decision. Read every line, then write the plan (references/formats.md).
"""
import argparse
import difflib
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))  # also under python -I
from common import (HOP, clock, decode, ends_sentence, envelope_db, gaps_between, is_sure_filler, norm, note_hits, read_json,
                    tighten, utf8_stdout, voice_levels, word_tokens, write_json)

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


def long_words(words):
    """Indexes of words lasting over 3 times this speaker's time per letter, and at least 0.9 s."""
    d = np.array([w["end"] - w["start"] for w in words])
    n = np.array([max(1, len("".join(norm(w["w"])))) for w in words])
    rate = float(np.median(d / n)) if len(d) else 0.0
    return [i for i in range(len(words)) if d[i] > max(0.9, 3 * rate * n[i])]


RELISTEN_PROMPT = {"en": "Umm, let me think, like, hmm... Okay, uh, I- I mean, the the thing is.",
                   "vi": "Ờ, ừm, thì là... À, kiểu như, ờ, mình nghĩ là, ừm, vậy đó."}


def relisten(film, spans, language, model, prompt=None):
    """What Whisper hears in each (start, end) when it transcribes that stretch on its own, without the context that
    makes it tidy repeats away. None when faster-whisper is not installed."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    import os
    import subprocess
    import tempfile
    names = {"turbo": "large-v3-turbo"}
    m = WhisperModel(names.get(model, model), device="auto", compute_type="int8", cpu_threads=min(4, os.cpu_count() or 4))
    heard = []
    tmp = Path(tempfile.mkdtemp())
    for k, (s, e) in enumerate(spans):
        wav = tmp / f"line{k}.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-nostdin", "-ss", f"{max(0.0, s):.3f}", "-t", f"{e - s:.3f}", "-i",
                        str(film), "-map", "0:a:0", "-ac", "1", "-ar", "16000", str(wav)], check=True)
        segs, _ = m.transcribe(str(wav), language=language, condition_on_previous_text=False, beam_size=5,
                               initial_prompt=prompt)
        heard.append(" ".join(x.text.strip() for x in segs).strip())
    return heard


def read_take(transcript, film, label, no_relisten):
    """One file's lines with their marks. label is "" for a single file (lines L1, L2...), else "A", "B"... (A1, A2...)."""
    t = read_json(transcript)
    words, lang = t["words"], t.get("language") or "en"
    if not words:
        sys.exit(f"takes.py: {transcript} has no words")
    if not (t.get("settings") or {}).get("verbatim"):
        print(f"note: {Path(transcript).name} was made without --verbatim, so Whisper may have tidied away fillers and "
              "false starts; run transcribe.py again with --verbatim for a cut.")
    audio = decode(film)
    env, thr, speech, floor, how = voice_levels(audio, envelope_db(audio), words)
    toks = word_tokens(words)
    duration = t.get("duration") or len(env) * HOP
    words = tighten(words, env, thr)
    gaps = gaps_between(words, duration)
    lines = split_lines(words, gaps)
    flat = [[x for i in ln for x in toks[i]] for ln in lines]
    name = (lambda n: f"{label}{n}") if label else (lambda n: f"L{n}")
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
                marks.append(f"RETAKE? said again in {name(m + 1)} ({s:.0%} the same)")
                break
        if re.search(r"(\.\.\.|…|-|—)$", words[ln[-1]]["w"].strip()) or (
                n + 1 < len(lines) and not ends_sentence(words[ln[-1]]) and note_hits(" ".join(flat[n + 1]), lang)):
            # A false start is said again; a line that breaks off and then goes on in the next line is a pause.
            again = next((m for m in range(n + 1, min(len(lines), n + 4))
                          if flat[n] and similar(flat[n], flat[m][:len(flat[n]) + 1]) >= 0.6), None)
            if again is not None or any(m.startswith(("NOTE?", "RETAKE?")) for m in marks):
                marks.append("UNFINISHED" + (f", said again in {name(again + 1)}" if again is not None else ""))
            elif n + 1 < len(lines):
                marks.append(f"BREAKS OFF, then {name(n + 2)} goes on: a pause in one sentence, usually kept")
            else:
                marks.append("UNFINISHED")
        joined = flat[n] + (flat[n + 1] if n + 1 < len(lines) and pause < 0.3 else [])
        line_ref = f'"{label}{n + 1}"' if label else n + 1
        for s_, e_, phrase in doubled(joined):
            if s_ < len(flat[n]):
                marks.append(f'DOUBLED "{phrase}": remove only the first copy, {{"quote": "{phrase}", "line": {line_ref}, "nth": 1}}')
        fill = [words[i]["w"].strip() for i in ln if is_sure_filler(words[i])]
        if fill:
            marks.append("fillers " + ", ".join(f"[{f}]" for f in fill))
        row = {"line": f"{label}{n + 1}" if label else n + 1, "first": ln[0], "last": ln[-1], "start": start, "end": end,
               "pause_after": round(pause, 2), "text": text, "marks": marks}
        if label:
            row["source"] = label
        rows.append(row)
    sounds = unheard_sound(env, thr, words, duration)
    for s_, e_ in sounds:
        after = max((r for r in rows if r["end"] <= s_ + 0.05), key=lambda r: r["end"], default=None)
        if after:
            after["marks"].append(f"SOUND? {clock(s_)}-{clock(e_)} after this line has no words")
    longs = set(long_words(words))
    for r in rows:
        for i in range(r["first"], r["last"] + 1):
            if i in longs:
                r["marks"].append(f'LONG WORD? "{words[i]["w"].strip()}" {words[i]["end"] - words[i]["start"]:.1f} s')
    check = [r for r in rows if any(m.startswith(("LONG WORD?", "SOUND?")) for m in r["marks"])]
    if check and not no_relisten:
        model = t.get("model") or "small"
        print(f"listening again to {len(check)} line(s) of {Path(film).name} on their own with {model}...", flush=True)
        # The prompt must be in the take's language: an English one makes Whisper answer a Vietnamese line in English.
        prompt = (t.get("settings") or {}).get("prompt") or RELISTEN_PROMPT.get(lang)
        heard = relisten(film, [(r["start"] - 0.3, r["end"] + 0.3) for r in check], lang, model, prompt)
        for r, h in zip(check, heard or []):
            if len(word_tokens([{"w": h}])[0]) > len(word_tokens([{"w": r["text"]}])[0]):
                r["marks"].append(f'HEARD "{h}"')
    for r in rows:
        r["_toks"] = [x for i in range(r["first"], r["last"] + 1) for x in toks[i]]
    return {"label": label, "transcript": str(Path(transcript).resolve()), "film": str(Path(film).resolve()),
            "language": lang, "thr": thr, "speech": speech, "floor": floor, "how": how, "rows": rows, "sounds": sounds,
            "words": len(words), "duration": t.get("duration", 0)}


def find_in(toks, flat):
    """Where the words of one line are said in another file: (first, last + 1) token of flat, or None. The matched
    words must be 60 % of the line, in one stretch (blocks of 2+ words at about the same offset)."""
    if len(toks) < 3 or not flat:
        return None
    sm = difflib.SequenceMatcher(None, toks, [t for t, _ in flat], autojunk=False)
    blocks = [m for m in sm.get_matching_blocks() if m.size >= 2]
    if not blocks:
        return None
    big = max(blocks, key=lambda m: m.size)
    near = [m for m in blocks if abs((m.b - m.a) - (big.b - big.a)) <= max(3, len(toks) // 3)]
    if sum(m.size for m in near) < 0.6 * len(toks):
        return None
    return min(m.b for m in near), max(m.b + m.size for m in near)


def words_of(toks, n=6):
    return " ".join(toks[:n]) + (" ..." if len(toks) > n else "")


def same_lines(takes):
    """Lines whose words are said in another file too, how each take differs there, and passages: groups of lines,
    across files, that say the same part of the script."""
    flats = {tk["label"]: [(t, k) for k, r in enumerate(tk["rows"]) for t in r["_toks"]] for tk in takes}
    parent = {}

    def root(x):
        while parent.setdefault(x, x) != x:
            x = parent[x]
        return x

    notes = {}
    for tk in takes:
        f = flats[tk["label"]]
        pos = 0
        for r in tk["rows"]:
            mine = r["_toks"]
            after_me = [t for t, _ in f[pos + len(mine):pos + len(mine) + 6]]
            pos += len(mine)
            for other in takes:
                if other is tk:
                    continue
                g = flats[other["label"]]
                hit = find_in(mine, g)
                if not hit:
                    continue
                g0, g1 = hit
                lines = sorted({g[i][1] for i in range(g0, g1)})
                names = [other["rows"][i]["line"] for i in lines]
                for i in lines:
                    parent[root(r["line"])] = root(other["rows"][i]["line"])
                there = [t for t, _ in g[g0:g1]]
                diff = []
                for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, there, mine, autojunk=False).get_opcodes():
                    if op in ("delete", "replace") and i2 - i1 >= 2:
                        diff.append(f'lacks "{words_of(there[i1:i2])}"')
                    if op in ("insert", "replace") and j2 - j1 >= 2:
                        diff.append(f'adds "{words_of(mine[j1:j2])}"')
                then_there = [t for t, _ in g[g1:g1 + 6]]
                if then_there and then_there[:2] != after_me[:2] and similar(then_there, after_me) < 0.5:
                    diff.append(f'then {other["label"]} goes on "{words_of(then_there)}"'
                                + (f', this file "{words_of(after_me)}"' if after_me else ", this file ends"))
                span = names[0] if len(names) == 1 else f"{names[0]}-{names[-1]}"
                notes.setdefault(r["line"], []).append({"in": span, "differs": diff})
    rows = {r["line"]: r for tk in takes for r in tk["rows"]}
    passages = {}
    for tk in takes:
        for r in tk["rows"]:
            if r["line"] in notes or root(r["line"]) != r["line"] or any(root(x) == r["line"] for x in parent):
                passages.setdefault(root(r["line"]), []).append(r["line"])
    out = []
    for members in passages.values():
        if len({rows[m]["source"] for m in members}) < 2:
            continue
        by_file = {}
        for m in members:
            by_file.setdefault(rows[m]["source"], []).append(m)
        out.append({"takes": by_file,
                    "lines": [{"line": m, "length": round(rows[m]["end"] - rows[m]["start"], 2),
                               "also": notes.get(m, [])} for m in members]})
    for g in out:
        for m in g["lines"]:
            if m["also"]:
                rows[m["line"]]["marks"].insert(0, "ALSO IN " + ", ".join(x["in"] for x in m["also"]))
    return out


def bed_note(how):
    if how == "level and VAD":
        return "; music or noise under the voice, so speech is where the level and the speech detector agree"
    return ""


def main():
    utf8_stdout()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("pairs", nargs="+", metavar="TRANSCRIPT FILM",
                   help="transcript.json and its film; for takes spread over several files, one pair per file (they are "
                        "named A, B, C... in this order)")
    p.add_argument("--out", required=True)
    p.add_argument("--no-relisten", action="store_true", help="do not transcribe LONG WORD? and SOUND? lines again")
    a = p.parse_args()
    if len(a.pairs) % 2:
        p.error("give a transcript and its film for every file: T1.json FILM1.mp4 [T2.json FILM2.mp4 ...]")
    pairs = [(a.pairs[k], a.pairs[k + 1]) for k in range(0, len(a.pairs), 2)]
    if len(pairs) > 26:
        p.error("at most 26 files")
    multi = len(pairs) > 1
    takes = [read_take(t, f, chr(65 + k) if multi else "", a.no_relisten) for k, (t, f) in enumerate(pairs)]
    groups = same_lines(takes) if multi else []
    for tk in takes:
        for r in tk["rows"]:
            r.pop("_toks")
    out_dir = Path(a.out)
    if not multi:
        tk = takes[0]
        rows, sounds, thr, speech = tk["rows"], tk["sounds"], tk["thr"], tk["speech"]
        data = {"transcript": tk["transcript"], "film": tk["film"], "language": tk["language"], "quiet_dbfs": round(thr, 1),
                "speech_dbfs": round(speech, 1), "floor_dbfs": round(tk["floor"], 1), "lines": rows,
                "unheard": [[round(s, 2), round(e, 2)] for s, e in sounds]}
        if tk["how"] != "level":
            data["measured_with"] = tk["how"]
        write_json(out_dir / "takes.json", data)
        out = [f"# Takes: {Path(tk['film']).name}", "",
               f"{len(rows)} lines, {tk['words']} words, {tk['duration']:.1f} s. Speech at {speech:.0f} dBFS, quiet under "
               f"{thr:.0f} dBFS{bed_note(tk['how'])}. Pause = silence after the line.", "",
               "| Line | Time | Pause | Text | Look at |", "|---|---|---|---|---|"]
        for r in rows:
            out.append(f"| L{r['line']} | {clock(r['start'])} | {r['pause_after']:.2f} | {r['text']} | {'; '.join(r['marks'])} |")
        (out_dir / "takes.md").write_text("\n".join(out) + "\n", encoding="utf-8")
        flagged = sum(bool(r["marks"]) for r in rows)
        print("\n".join(out[6:]))
        print(f"\n{len(rows)} lines, {flagged} marked, {len(sounds)} stretches of voice without words -> {out_dir / 'takes.md'}")
        return
    write_json(out_dir / "takes.json", {
        "sources": [{"label": tk["label"], "transcript": tk["transcript"], "film": tk["film"], "language": tk["language"],
                     "quiet_dbfs": round(tk["thr"], 1), "speech_dbfs": round(tk["speech"], 1),
                     "floor_dbfs": round(tk["floor"], 1), "measured_with": tk["how"],
                     "unheard": [[round(s, 2), round(e, 2)] for s, e in tk["sounds"]]} for tk in takes],
        "lines": [r for tk in takes for r in tk["rows"]], "passages": groups})
    out = [f"# Takes: {len(takes)} files", "",
           "Lines are named by file: A12 is line 12 of file A. Pause = silence after the line. ALSO IN = the same line "
           "said in another file.", ""]
    for tk in takes:
        rows = tk["rows"]
        out += [f"## {tk['label']}: {Path(tk['film']).name}", "",
                f"{len(rows)} lines, {tk['words']} words, {tk['duration']:.1f} s. Speech at {tk['speech']:.0f} dBFS, quiet "
                f"under {tk['thr']:.0f} dBFS{bed_note(tk['how'])}.", "",
                "| Line | Time | Pause | Text | Look at |", "|---|---|---|---|---|"]
        for r in rows:
            out.append(f"| {r['line']} | {clock(r['start'])} | {r['pause_after']:.2f} | {r['text']} | {'; '.join(r['marks'])} |")
        out.append("")
    out += ["## Said in more than one file", "",
            "Each passage is a part of the script said in several files, with its lines in each file. Pick one take of "
            "each passage, or of each line in it (SKILL.md, step 4b). \"lacks\" and \"adds\" compare a line with the "
            "same words in the other file; \"then B goes on\" means the two files part ways after this line: one of "
            "them breaks off, skips or goes back.", ""]
    for n, g in enumerate(groups, 1):
        takes_txt = " | ".join(f"{lb}: {ms[0]}" + (f"-{ms[-1]}" if len(ms) > 1 else "") for lb, ms in g["takes"].items())
        out += [f"**P{n}** {takes_txt}", "", "| Line | Length | Same words in | How it differs there |", "|---|---|---|---|"]
        for m in g["lines"]:
            for k, x in enumerate(m["also"] or [{"in": "", "differs": []}]):
                first = k == 0
                out.append(f"| {m['line'] if first else ''} | {format(m['length'], '.2f') + ' s' if first else ''} | "
                           f"{x['in']} | {'; '.join(x['differs'])} |")
        out.append("")
    (out_dir / "takes.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))
    print(f"\n{len(takes)} files, {sum(len(tk['rows']) for tk in takes)} lines, {len(groups)} passage(s) said in more than one file "
          f"-> {out_dir / 'takes.md'}")


if __name__ == "__main__":
    main()
