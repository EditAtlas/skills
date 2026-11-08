"""Turn a word-level transcript into subtitle files. Run it again after correcting words in the JSON.

  captions.py work/transcript/transcript.json                 # transcript.srt, .vtt, .txt next to it
  captions.py work/cuts/transcript_cut.json --max-chars 32    # captions for the cut film, narrower lines

Rules (from EditAtlas caption techniques): at most 2 lines of --max-chars, a caption breaks at a sentence end, a
pause or --max-dur, each one stays up for its phrase plus 150 ms without touching the next, and a caption read
faster than --max-cps characters per second is flagged.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # also under python -I
from common import read_json, ts, utf8_stdout

SENTENCE_END = re.compile(r"[.!?…。]$")
CLAUSE_END = re.compile(r"[,;:]$")


def text_of(words):
    out = ""
    for w in words:
        t = w["w"].strip()
        if not t:
            continue
        out += t if (not out or re.match(r"^[,.!?;:…%)\]]", t)) else " " + t
    return out


def split_lines(words, max_chars, max_lines):
    """Balanced lines: try every break and keep the one with the most even lengths that fits."""
    full = text_of(words)
    if len(full) <= max_chars or max_lines == 1 or len(words) < 2:
        return [full]
    best = None
    for i in range(1, len(words)):
        a, b = text_of(words[:i]), text_of(words[i:])
        over = max(0, len(a) - max_chars) + max(0, len(b) - max_chars)
        score = (over, abs(len(a) - len(b)) - (4 if CLAUSE_END.search(a) else 0))
        if best is None or score < best[0]:
            best = (score, [a, b])
    return best[1]


def build(words, max_chars=38, max_lines=2, max_dur=6.0, pause=0.5, hold=0.15, gap=0.04):
    words = [w for w in words if w["w"].strip()]
    cues, cur = [], []
    limit = max_chars * max_lines
    for i, w in enumerate(words):
        if cur:
            gap_before = w["start"] - cur[-1]["end"]
            longer = len(text_of(cur + [w])) > limit
            too_long = w["end"] - cur[0]["start"] > max_dur
            if gap_before >= pause:
                cues.append(cur); cur = []
            elif longer or too_long:
                # full: break at the longest pause in the second half (a breath between phrases), not at the last
                # word that fits, so a caption does not end in the middle of "you are / also saying"
                lo = max(1, len(cur) // 2)
                k = max(range(lo, len(cur)), key=lambda j: (cur[j]["start"] - cur[j - 1]["end"], j), default=len(cur))
                if CLAUSE_END.search(cur[-1]["w"]) or cur[k]["start"] - cur[k - 1]["end"] < 0.08:
                    k = len(cur)
                cues.append(cur[:k]); cur = cur[k:]
        cur.append(w)
        # close on a sentence end once the caption has some body, so lines start with a new sentence
        if SENTENCE_END.search(w["w"].strip()) and len(text_of(cur)) >= max_chars * 0.5:
            cues.append(cur); cur = []
    if cur:
        cues.append(cur)
    out = []
    for k, c in enumerate(cues):
        start = c[0]["start"]
        end = c[-1]["end"] + hold
        if k + 1 < len(cues):
            end = min(end, cues[k + 1][0]["start"] - gap)
        end = max(end, c[-1]["end"])
        lines = split_lines(c, max_chars, max_lines)
        chars = sum(len(l) for l in lines)
        out.append({"start": round(start, 3), "end": round(end, 3), "lines": lines,
                    "cps": round(chars / max(end - start, 0.01), 1)})
    return out


def write_all(transcript, prefix, max_chars=38, max_lines=2, max_dur=6.0, max_cps=17.0):
    cues = build(transcript["words"], max_chars, max_lines, max_dur)
    prefix = str(prefix)
    with open(prefix + ".srt", "w", encoding="utf-8") as f:
        for i, c in enumerate(cues, 1):
            f.write(f"{i}\n{ts(c['start'])} --> {ts(c['end'])}\n" + "\n".join(c["lines"]) + "\n\n")
    with open(prefix + ".vtt", "w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n")
        for c in cues:
            f.write(f"{ts(c['start'], '.')} --> {ts(c['end'], '.')}\n" + "\n".join(c["lines"]) + "\n\n")
    paras, cur, last = [], [], None
    for w in transcript["words"]:
        if last is not None and w["start"] - last > 1.5 and cur:
            paras.append(text_of(cur)); cur = []
        cur.append(w); last = w["end"]
    if cur:
        paras.append(text_of(cur))
    Path(prefix + ".txt").write_text("\n\n".join(paras) + "\n", encoding="utf-8")
    fast = [c for c in cues if c["cps"] > max_cps]
    long_lines = [c for c in cues if any(len(l) > max_chars for l in c["lines"])]
    return cues, fast, long_lines


def main():
    utf8_stdout()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("transcript")
    p.add_argument("--max-chars", type=int, default=38, help="characters per line (38 landscape; about 32 for 9:16)")
    p.add_argument("--max-lines", type=int, default=2)
    p.add_argument("--max-dur", type=float, default=6.0)
    p.add_argument("--max-cps", type=float, default=17.0)
    a = p.parse_args()
    t = read_json(a.transcript)
    prefix = str(Path(a.transcript).with_suffix(""))
    cues, fast, long_lines = write_all(t, prefix, a.max_chars, a.max_lines, a.max_dur, a.max_cps)
    print(f"{len(cues)} captions -> {prefix}.srt, .vtt, .txt")
    for c in fast:
        print(f"  fast: {c['start']:.2f}s {c['cps']} chars/s: {' / '.join(c['lines'])}")
    for c in long_lines:
        print(f"  long line: {c['start']:.2f}s: {' / '.join(c['lines'])}")


if __name__ == "__main__":
    main()
