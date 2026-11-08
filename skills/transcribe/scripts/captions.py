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
from common import clock, read_json, ts, utf8_stdout

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


# Where a line or caption may break. Vietnamese writes a word of two syllables as two "words" ("sự nghiệp", "nỗ
# lực"), and a break between them reads badly; a fresh-agent test on a real talk found "sự / nghiệp" and
# "khăng / khăng". Without a dictionary, breaks go where a phrase usually starts: after punctuation, at a pause, or
# before a word that opens a phrase. Words that lean on the next or the previous word are never split from it.
OPENS = {
    "vi": {"là", "và", "thì", "mà", "nhưng", "của", "để", "với", "cho", "khi", "nếu", "vì", "rằng", "ở", "trong",
           "hoặc", "hay", "nên", "bởi", "do", "sau", "trước", "còn", "cũng", "đã", "sẽ", "đang",
           "không", "chưa", "được", "bị", "phải", "có", "bạn", "mình", "tôi", "chúng", "họ", "anh", "em", "chị"},
    "en": {"and", "but", "or", "so", "because", "that", "which", "who", "when", "if", "to", "with", "for", "in", "on",
           "at", "of", "from", "the", "a", "an", "is", "are", "was", "i", "you", "we", "they", "it"},
}
LEANS_ON_NEXT = {
    "vi": {"sự", "cái", "con", "những", "các", "một", "mỗi", "người", "việc", "cuộc", "nhà", "rất", "quá", "hơi",
           "thật", "đã", "sẽ", "đang", "không", "chưa", "được", "bị", "của", "và", "là", "với", "cho", "để", "những"},
    "en": {"the", "a", "an", "to", "of", "my", "your", "our", "their", "his", "her", "very", "so", "not"},
}
# Common pairs whose second word would otherwise look like the start of a phrase.
PAIRS = {"vi": {("thay", "vì"), ("bởi", "vì"), ("tại", "vì"), ("vì", "vậy"), ("vì", "thế"), ("cho", "nên"),
                ("có", "thể"), ("có", "lẽ"), ("chúng", "ta"), ("chúng", "mình"), ("chúng", "tôi"), ("không", "phải"),
                ("được", "không"), ("hay", "là"), ("hoặc", "là"), ("nên", "là"), ("thì", "là")}}
LEANS_ON_PREVIOUS = {
    "vi": {"này", "đó", "ấy", "kia", "nữa", "rồi", "lắm", "nhé", "nha", "thôi", "đâu", "vậy", "hơn", "nhất"},
    "en": {"'s", "too", "though"},
}


def bare(word):
    return re.sub(r"[^\w']", "", word.lower())


def break_bonus(words, j, language=None):
    """How good a break before words[j] is; negative means it splits words that belong together."""
    prev, nxt = words[j - 1], words[j]
    lang = (language or "")[:2]
    bonus = 0.0
    if SENTENCE_END.search(prev["w"]):
        bonus += 12
    elif CLAUSE_END.search(prev["w"]):
        bonus += 8
    bonus += min(10.0, max(0.0, nxt["start"] - prev["end"]) * 40)    # 0.1 s of breath = 4
    if bare(nxt["w"]) in OPENS.get(lang, set()):
        bonus += 5
    if bare(prev["w"]) in LEANS_ON_NEXT.get(lang, set()) and not CLAUSE_END.search(prev["w"]):
        bonus -= 8
    if bare(nxt["w"]) in LEANS_ON_PREVIOUS.get(lang, set()):
        bonus -= 8
    if (bare(prev["w"]), bare(nxt["w"])) in PAIRS.get(lang, set()) and not CLAUSE_END.search(prev["w"]):
        bonus -= 14
    if bare(prev["w"]) == bare(nxt["w"]) and not CLAUSE_END.search(prev["w"]):
        bonus -= 14      # "khăng khăng", "từ từ"
    if lang == "vi" and bonus <= 0:
        bonus -= 3       # two syllables with nothing between them are often one word
    return bonus


def split_lines(words, max_chars, max_lines, language=None):
    """Two lines that fit, as even as the phrases allow."""
    full = text_of(words)
    if len(full) <= max_chars or max_lines == 1 or len(words) < 2:
        return [full]
    best = None
    for i in range(1, len(words)):
        a, b = text_of(words[:i]), text_of(words[i:])
        over = max(0, len(a) - max_chars) + max(0, len(b) - max_chars)
        # Vietnamese leans harder on phrase edges: an even split inside a two-syllable word reads worse than
        # uneven lines
        weight = 3.0 if (language or "")[:2] == "vi" else 1.5
        score = (over, abs(len(a) - len(b)) - weight * break_bonus(words, i, language))
        if best is None or score < best[0]:
            best = (score, [a, b])
    return best[1]


def fits(words, max_chars, max_lines):
    lines = split_lines(words, max_chars, max_lines)
    return len(lines) <= max_lines and all(len(l) <= max_chars for l in lines)


def build(words, max_chars=38, max_lines=2, max_dur=6.0, pause=0.5, hold=0.15, gap=0.04, language=None):
    words = [w for w in words if w["w"].strip()]
    cues, cur = [], []
    for i, w in enumerate(words):
        if cur:
            gap_before = w["start"] - cur[-1]["end"]
            longer = not fits(cur + [w], max_chars, max_lines)
            too_long = w["end"] - cur[0]["start"] > max_dur
            if gap_before >= pause:
                cues.append(cur); cur = []
            elif longer or too_long:
                # full: break where a phrase starts in the second half (punctuation, a breath, a word that opens a
                # phrase), not at the last word that fits, so a caption does not end inside "sự / nghiệp"
                k = len(cur)
                if not CLAUSE_END.search(cur[-1]["w"]):
                    lo = max(1, len(cur) // 2)
                    tail = cur + [w]
                    k = max(range(lo, len(cur) + 1), key=lambda j: (break_bonus(tail, j, language) + j * 0.3, j))
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
        lines = split_lines(c, max_chars, max_lines, language)
        chars = sum(len(l) for l in lines)
        out.append({"start": round(start, 3), "end": round(end, 3), "lines": lines,
                    "cps": round(chars / max(end - start, 0.01), 1)})
    return out


def write_review(transcript, path):
    """review.md: every word or run of words a person should check, numbered as fix.py numbers them (from 0)."""
    words, review = transcript["words"], transcript.get("review", [])
    name = Path(transcript.get("source", "")).name
    lines = [f"# Words to check in {name}", "",
             "Whisper writes what it heard, not what was meant. Check each line with the person. Word numbers start "
             "at 0. Correct words with `fix.py transcript.json set N \"text\"` (or `names`, `delete`), which keeps the "
             "times and rewrites the subtitles and this file. Run `fix.py transcript.json checked` only after the "
             "person has confirmed names and numbers. Not every wrong word is listed: on real Vietnamese speech this "
             "list caught about 4 in 10, so read the whole text once too.", "",
             "| # | time | heard | in context | why | suggested |", "|---|---|---|---|---|---|"]
    for r in review:
        i, j = r["i"], r.get("to", r["i"])
        heard = text_of(words[i:j + 1])
        ctx = text_of(words[max(0, i - 4): j + 5])
        span = f"{i}" if i == j else f"{i}-{j}"
        lines.append(f"| {span} | {clock(words[i]['start'])} | {heard} | {ctx} | {r['why']} | {r.get('fix', '')} |")
    if not review:
        lines.append("| - | - | - | - | nothing flagged; still read it once | |")
    if transcript.get("edits"):
        lines += ["", f"{len(transcript['edits'])} edit(s) made with fix.py; checked: {transcript.get('checked', False)}."]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_all(transcript, prefix, max_chars=38, max_lines=2, max_dur=6.0, max_cps=17.0):
    cues = build(transcript["words"], max_chars, max_lines, max_dur, language=transcript.get("language"))
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
