"""Find what an edit could cut from speech: long silences, filler words and repeated takes. Nothing is rendered.

  cuts.py work/transcript/transcript.json --out work/cuts                    # silences over 0.4 s, sure fillers
  cuts.py work/transcript/transcript.json --out work/cuts --min-silence 0.6 --pad 0.15
  cuts.py work/transcript/transcript.json --out work/cuts --take-retakes     # also cut earlier takes of a line

Writes cuts.json (every candidate, the keep list, seconds saved), cuts.md (the list to show the person),
transcript_cut.json/.srt/.vtt (word times in the cut film's time, for captions after the cut) and ffmpeg_cut.txt
(the select/aselect expressions for the EditAtlas silence-removal and filler-removal techniques).

Silences come from the gaps between words, then the audio level moves each edge to where it is really quiet:
Whisper's word ends often run into the pause. --pad is kept around every word (EditAtlas: 100 to 200 ms).
"""
import argparse
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))  # also under python -I
from captions import text_of, write_all
from common import HOP, SR, clock, decode, die, envelope_db, read_json, utf8_stdout, write_json

# Sure fillers are cut by default; maybe fillers are listed for the person, because they are often real words.
FILLERS = {
    "en": ({"um", "umm", "uh", "uhm", "uhh", "erm", "er", "ah", "hmm", "mm", "mhm"},
           {"like", "you know", "i mean", "sort of", "kind of", "basically", "actually", "so", "okay so"}),
    "vi": ({"ờ", "ơ", "ừ", "ừm", "ưm", "ừ m", "ầm", "à", "ờm", "hừm", "hmm", "um", "uh"},
           {"kiểu", "kiểu như", "thì là", "nói chung", "nói chung là", "đại loại", "thực ra", "thật ra", "nhé", "đấy"}),
}


def norm(t):
    return re.sub(r"[^\w\s']", "", t.lower()).strip()


def voice_mask(audio, n):
    """True where Silero VAD (shipped with faster-whisper) hears a voice, per envelope step. It ignores most music
    and steady noise, which a level threshold cannot."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    mask = np.zeros(n, bool)
    opts = VadOptions(threshold=0.5, min_silence_duration_ms=100, speech_pad_ms=30)
    for seg in get_speech_timestamps(audio, opts):
        mask[int(seg["start"] / SR / HOP):int(seg["end"] / SR / HOP) + 1] = True
    return mask


def quiet_level(env, words):
    """dBFS under which the film counts as quiet: between its noise floor and its speech."""
    spans = [env[int(w["start"] / HOP):max(int(w["start"] / HOP) + 1, int(w["end"] / HOP))] for w in words]
    speech = float(np.median([s.max() for s in spans if len(s)])) if spans else -20.0
    floor = float(np.percentile(env, 5))
    return max(floor + 0.5 * (speech - floor) - 6.0, speech - 40.0), speech, floor


def silences(words, env, audio, duration, min_sil, pad):
    thr, speech, floor = quiet_level(env, words)
    # A clean recording is quiet between words, and its level is the sharpest guide. Under music or room noise
    # the pauses are not quiet, so the voice detector decides instead.
    clean = speech - floor >= 30
    # Whisper's word times are not trusted on their own: it wrote "400ms" for five spoken syllables and ended the
    # word 0.36 s early. Where the detector hears a voice in music, the pause is left in rather than risk a word.
    quiet = env < thr if clean else ~voice_mask(audio, len(env))
    out = []
    edges = [(0.0, words[0]["start"], None, 0)] + [(words[k]["end"], words[k + 1]["start"], k, k + 1) for k in range(len(words) - 1)] + [(words[-1]["end"], duration, len(words) - 1, None)]
    for a, b, before, after in edges:
        if b - a < min_sil * 0.6:
            continue
        # widen to the real quiet: Whisper's word end can sit 100-300 ms inside the pause, or before a trailing sound
        i0, i1 = int(a / HOP), int(b / HOP)
        lo, hi = i0, i1
        while lo > (int(words[before]["start"] / HOP) if before is not None else 0) and lo > 0 and quiet[lo - 1] and lo > i0 - 30:
            lo -= 1
        while hi < len(quiet) - 1 and (after is None or hi < int(words[after]["end"] / HOP)) and quiet[hi] and hi < i1 + 30:
            hi += 1
        # inside the gap, the cut is the longest quiet run, so a breath or a click is kept as sound
        best, run = None, None
        for k in range(lo, min(hi, len(quiet))):
            if quiet[k]:
                run = (run[0], k + 1) if run else (k, k + 1)
                if best is None or run[1] - run[0] > best[1] - best[0]:
                    best = run
            else:
                run = None
        if best is None:
            continue
        qa, qb = best[0] * HOP, best[1] * HOP
        start = qa + (pad if before is not None else 0.0)
        end = qb - (pad if after is not None else 0.0)
        if qb - qa >= min_sil and end - start >= 0.05:
            kind = "lead" if before is None else "tail" if after is None else "silence"
            out.append({"start": round(start, 3), "end": round(min(end, duration), 3), "kind": kind, "sure": True,
                        "why": f"{qb - qa:.2f} s " + (f"quiet (under {thr:.0f} dBFS)" if clean else "without voice")})
    return out, (round(thr, 1) if clean else None), clean


def snap(env, t, lo, hi):
    """The quietest envelope step within 60 ms of t, kept inside lo..hi: a cut edge sits in a dip, not on a word."""
    a, b = max(int(lo / HOP), int((t - 0.06) / HOP)), min(int(hi / HOP), int((t + 0.06) / HOP))
    if b <= a or b > len(env):
        return t
    return (a + int(np.argmin(env[a:b]))) * HOP


def fillers(words, language, pad, env, clean=True):
    sure, maybe = FILLERS.get(language, FILLERS["en"])
    out, k = [], 0
    while k < len(words):
        hit = None
        for n in (3, 2, 1):
            phrase = norm(" ".join(w["w"] for w in words[k:k + n]))
            if phrase in sure or phrase in maybe:
                hit = (n, phrase in sure and clean, phrase)
                break
        if hit:
            n, is_sure, phrase = hit
            a, b = words[k]["start"], words[k + n - 1]["end"]
            # the cut takes the filler and the pause around it (up to 0.25 s a side), keeping --pad next to the
            # real words, so no hole is left where it was
            prev_end = words[k - 1]["end"] if k else a - 0.25
            next_start = words[k + n]["start"] if k + n < len(words) else b + 0.25
            start = min(a, max(prev_end + pad, a - 0.25))
            end = max(b, min(next_start - pad, b + 0.25))
            # Whisper's filler edges can run into the next word; never closer than 40 ms to it, and in a dip
            end = snap(env, min(end, next_start - 0.04), a, next_start - 0.04)
            start = snap(env, max(start, prev_end + 0.04), prev_end + 0.04, b)
            out.append({"start": round(start, 3), "end": round(end, 3),
                        "kind": "filler", "sure": is_sure, "text": text_of(words[k:k + n]),
                        "why": "filler" if is_sure else ("filler, but music or noise under the voice hides its edges: preview it" if phrase in sure else "often a filler, sometimes meant: ask")})
            k += n
        else:
            k += 1
    return out


def sentences(words):
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(i)
        if re.search(r"[.!?…]$", w["w"]) or (i + 1 < len(words) and words[i + 1]["start"] - w["end"] > 0.7):
            out.append(cur); cur = []
    if cur:
        out.append(cur)
    return out


def retakes(words):
    """A sentence whose words come back at the start of the next one or two: the speaker said it again."""
    sents = sentences(words)
    toks = [[norm(words[i]["w"]) for i in s if norm(words[i]["w"])] for s in sents]
    out = []
    for a in range(len(sents)):
        for b in (a + 1, a + 2):
            if b >= len(sents) or len(toks[a]) < 3:
                continue
            x, y = toks[a], toks[b]
            n = 0
            while n < min(len(x), len(y)) and x[n] == y[n]:
                n += 1
            if n >= 3 and n >= 0.6 * len(x):
                s0, s1 = sents[a][0], sents[b][0]
                out.append({"start": round(words[s0]["start"], 3), "end": round(words[s1]["start"] - 0.05, 3), "kind": "retake",
                            "sure": False, "text": text_of([words[i] for i in sents[a]]),
                            "why": f"said again at {clock(words[s1]['start'])}: keep the last clean take, ask"})
                break
    return out


def merge(cuts):
    cuts = sorted(cuts, key=lambda c: c["start"])
    out = []
    for c in cuts:
        if out and c["start"] <= out[-1]["end"] + 0.02:
            out[-1]["end"] = max(out[-1]["end"], c["end"])
        else:
            out.append({"start": c["start"], "end": c["end"]})
    return out


def remap(t, merged):
    """Word times in the cut film. A word inside a cut is dropped."""
    def to_out(x):
        gone = 0.0
        for c in merged:
            if x >= c["end"]:
                gone += c["end"] - c["start"]
            elif x > c["start"]:
                return c["start"] - gone
        return x - gone
    words, dropped, starts = [], None, True
    for w in t["words"]:
        mid = (w["start"] + w["end"]) / 2
        if any(c["start"] <= mid < c["end"] for c in merged):
            if dropped is None:
                dropped = {"sentence_start": starts}
            dropped["last"] = w["w"]
            starts = bool(re.search(r"[.!?…]$", w["w"]))
            continue
        text = w["w"]
        if dropped:
            # "Um, the first" -> "The first"; "The second, uh, is" -> "The second is"
            if dropped["sentence_start"] and text[:1].islower():
                text = text[:1].upper() + text[1:]
            if dropped["last"].endswith(",") and words and words[-1]["w"].endswith(","):
                words[-1]["w"] = words[-1]["w"][:-1]
            dropped = None
        starts = bool(re.search(r"[.!?…]$", text))
        words.append(dict(w, w=text, start=round(to_out(w["start"]), 3), end=round(to_out(w["end"]), 3)))
    return words


def main():
    utf8_stdout()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("transcript")
    p.add_argument("--out", required=True, help="folder")
    p.add_argument("--min-silence", type=float, default=0.4, help="seconds of quiet before it is cut (EditAtlas: 0.4)")
    p.add_argument("--pad", type=float, default=0.12, help="seconds kept on each side of a word")
    p.add_argument("--keep-lead", action="store_true", help="do not cut quiet before the first word or after the last")
    p.add_argument("--no-fillers", action="store_true")
    p.add_argument("--take-maybe", action="store_true", help="also cut the maybe fillers")
    p.add_argument("--take-retakes", action="store_true", help="also cut earlier takes of a repeated line")
    a = p.parse_args()
    t = read_json(a.transcript)
    words = t["words"]
    if not words:
        die("the transcript has no words")
    if not t.get("checked"):
        print("note: the transcript is not marked checked; cuts on unchecked words can cut real speech")
    audio = decode(t["source"])
    if not len(audio):
        die(f"cannot read the audio of {t['source']}")
    env = envelope_db(audio)
    duration = t["duration"]

    found, thr, clean = silences(words, env, audio, duration, a.min_silence, a.pad)
    if a.keep_lead:
        found = [c for c in found if c["kind"] == "silence"]
    if not a.no_fillers:
        found += fillers(words, t.get("language", "en"), a.pad, env, clean)
    found += retakes(words)
    found.sort(key=lambda c: c["start"])
    take = [c for c in found if c["sure"] or (a.take_maybe and c["kind"] == "filler") or (a.take_retakes and c["kind"] == "retake")]
    merged = merge(take)
    keep, at = [], 0.0
    for c in merged:
        if c["start"] > at:
            keep.append([round(at, 3), c["start"]])
        at = c["end"]
    if at < duration:
        keep.append([round(at, 3), round(duration, 3)])
    saved = sum(c["end"] - c["start"] for c in merged)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    data = {"source": t["source"], "duration": duration, "after_s": round(duration - saved, 3), "saved_s": round(saved, 3),
            "settings": {"min_silence": a.min_silence, "pad": a.pad, "quiet_dbfs": thr, "pauses_found_by": "level" if thr is not None else "voice detector (music or noise under the voice)", "fillers": not a.no_fillers,
                         "take_maybe": a.take_maybe, "take_retakes": a.take_retakes},
            "cuts": [dict(c, taken=c in take) for c in found], "merged": merged, "keep": keep}
    write_json(out / "cuts.json", data)
    cut_t = dict(t, words=remap(t, merged), duration=round(duration - saved, 3), cut_from=str(Path(a.transcript).resolve()),
                 segments=[], review=[])
    write_json(out / "transcript_cut.json", cut_t)
    write_all(cut_t, out / "transcript_cut")
    expr = "+".join(f"between(t,{c['start']:.3f},{c['end']:.3f})" for c in merged) or "0"
    gone, joins = 0.0, []
    for m in merged:
        if any(c["kind"] == "filler" and c["start"] < m["end"] and c["end"] > m["start"] for c in take):
            joins.append(f"{m['start'] - gone:.3f}")
        gone += m["end"] - m["start"]
    fade = (f"# These expressions cut hard. Joins that came from a filler, in the cut film's time; give each a 10-30 ms\n"
            f"# audio fade, as the EditAtlas filler-removal technique asks: {', '.join(joins)}\n") if joins else ""
    (out / "ffmpeg_cut.txt").write_text(
        f"# {len(merged)} cuts, {saved:.2f} s of {duration:.2f} s. Picture and sound are cut at the same times.\n"
        + fade +
        f"-vf \"select='not({expr})',setpts=N/FRAME_RATE/TB\"\n"
        f"-af \"aselect='not({expr})',asetpts=N/SR/TB\"\n", encoding="utf-8")
    rows = ["| # | from | to | length | kind | words | why | cut |", "|---|---|---|---|---|---|---|---|"]
    for k, c in enumerate(found, 1):
        rows.append(f"| {k} | {clock(c['start'])} | {clock(c['end'])} | {c['end'] - c['start']:.2f} s | {c['kind']} | {c.get('text', '')} | {c['why']} | {'yes' if c in take else 'ask'} |")
    (out / "cuts.md").write_text(f"# Cuts for {Path(t['source']).name}\n\n{duration:.1f} s -> {duration - saved:.1f} s ({saved:.1f} s cut, {len(merged)} cuts)\n\n" + "\n".join(rows) + "\n", encoding="utf-8")

    kinds = {}
    for c in take:
        kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
    asks = [c for c in found if c not in take]
    print(f"{duration:.1f} s -> {duration - saved:.1f} s: {saved:.1f} s in {len(merged)} cuts {kinds}; "
          + (f"quiet under {thr:.0f} dBFS" if thr is not None else "pauses found by the voice detector: there is sound under the voice, so each cut also cuts it (music jumps)"))
    for c in asks:
        print(f"  ask: {clock(c['start'])} {c['kind']} {c.get('text', '')!r}: {c['why']}")
    print("->", out / "cuts.json", out / "cuts.md", out / "transcript_cut.json", out / "ffmpeg_cut.txt")


if __name__ == "__main__":
    main()
