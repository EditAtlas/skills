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


def main():
    utf8_stdout()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("transcript")
    p.add_argument("film")
    p.add_argument("--out", required=True)
    p.add_argument("--no-relisten", action="store_true", help="do not transcribe LONG WORD? and SOUND? lines again")
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
            # A false start is said again; a line that breaks off and then goes on in the next line is a pause.
            again = next((m for m in range(n + 1, min(len(lines), n + 4))
                          if flat[n] and similar(flat[n], flat[m][:len(flat[n]) + 1]) >= 0.6), None)
            if again is not None or any(m.startswith(("NOTE?", "RETAKE?")) for m in marks):
                marks.append("UNFINISHED" + (f", said again in L{again + 1}" if again is not None else ""))
            elif n + 1 < len(lines):
                marks.append(f"BREAKS OFF, then L{n + 2} goes on: a pause in one sentence, usually kept")
            else:
                marks.append("UNFINISHED")
        joined = flat[n] + (flat[n + 1] if n + 1 < len(lines) and pause < 0.3 else [])
        for s_, e_, phrase in doubled(joined):
            if s_ < len(flat[n]):
                marks.append(f'DOUBLED "{phrase}": remove only the first copy, {{"quote": "{phrase}", "line": {n + 1}, "nth": 1}}')
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
    longs = set(long_words(words))
    for r in rows:
        for i in range(r["first"], r["last"] + 1):
            if i in longs:
                r["marks"].append(f'LONG WORD? "{words[i]["w"].strip()}" {words[i]["end"] - words[i]["start"]:.1f} s')
    check = [r for r in rows if any(m.startswith(("LONG WORD?", "SOUND?")) for m in r["marks"])]
    if check and not a.no_relisten:
        model = t.get("model") or "small"
        print(f"listening again to {len(check)} line(s) on their own with {model}...", flush=True)
        # The prompt must be in the take's language: an English one makes Whisper answer a Vietnamese line in English.
        prompt = (t.get("settings") or {}).get("prompt") or RELISTEN_PROMPT.get(lang)
        heard = relisten(a.film, [(r["start"] - 0.3, r["end"] + 0.3) for r in check], lang, model, prompt)
        for r, h in zip(check, heard or []):
            if len(word_tokens([{"w": h}])[0]) > len(word_tokens([{"w": r["text"]}])[0]):
                r["marks"].append(f'HEARD "{h}"')
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
