"""Transcribe a video or audio file on this machine with Whisper (faster-whisper), with a time for every word.

  transcribe.py VIDEO --out work/transcript                          # language detected, model chosen for you
  transcribe.py VIDEO --out work/transcript --language vi --names "Minh Anh, EditAtlas"   # names are checked after, not fed to Whisper
  transcribe.py VIDEO --out work/transcript --verbatim               # keep um, uh, ờ, ừm (for filler cuts)

Writes transcript.json (words, segments, review lists), transcript.srt/.vtt/.txt and review.md: the words a person
should check before the transcript is used for captions or cuts. Nothing leaves this machine.
"""
import argparse
import difflib
import re
import sys
import time
import unicodedata
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))  # also under python -I
from captions import text_of, write_all
from common import HOP, SR, clock, decode, die, envelope_db, probe, utf8_stdout, write_json

MODEL_REPOS = {"small": "small", "medium": "medium", "turbo": "large-v3-turbo", "large-v3": "large-v3"}
# A prompt written with fillers makes Whisper keep them instead of tidying them away.
VERBATIM = {
    "en": "Umm, let me think, like, hmm... Okay, uh, here's what I'm, like, thinking.",
    "vi": "Ờ, ừm, thì là... À, kiểu như, ờ, mình nghĩ là, ừm, vậy đó.",
}
VERBATIM_ANY = "Umm, uh, hmm... okay."
# A punctuated line in front makes Whisper punctuate and write "I" in English: on a real talking-head film it fixed
# 7 lower-case "i" and added sentence ends, with no change in the words. In Vietnamese the same idea cost a word on
# a test film, so other languages get no prompt.
STYLE = {"en": "Yes, I agree. It's simple, isn't it? Let's see."}
# Whisper reads its own previous sentence before the next one only where that was measured to help. On a real
# Vietnamese talk it raised sentence ends in 2 minutes from 6 to 23 with the same words; on a real English film it
# lost every sentence end, so English keeps it off.
CONTEXT = {"vi"}
LOW_P = 0.5
# Lines Whisper is known to invent from silence or music, learned from subtitled video. Measured here too: with the
# default VAD, a Vietnamese test film ended with "Hãy subscribe cho kênh La La School ..." that nobody said.
HALLUCINATIONS = [
    "subscribe", "đăng ký kênh", "cảm ơn các bạn đã theo dõi", "hẹn gặp lại các bạn", "hẹn gặp lại",
    "không bỏ lỡ những video hấp dẫn", "la la school", "ghiền mì gõ", "thanks for watching", "thank you for watching",
    "please like and subscribe", "subtitles by", "amara.org", "transcribed by", "see you in the next video",
]


def choose_model(name, duration, gpu):
    if name != "auto":
        return name
    if gpu:
        return "turbo"
    # Measured on a 12-thread CPU (int8): turbo runs about 2x faster than real time, small about 5x. Turbo got
    # Vietnamese right where small misheard words, so it is the default until a film is long.
    return "turbo" if duration <= 20 * 60 else "small"


def load_model(name, device):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        die("faster-whisper is not installed. Run doctor.py, ask the person, then doctor.py --install.")
    gpu = 0
    if device in ("auto", "cuda"):
        try:
            import ctranslate2
            gpu = ctranslate2.get_cuda_device_count()
        except Exception:
            gpu = 0
    if device == "cuda" and not gpu:
        die("--device cuda but no CUDA GPU is visible")
    dev = "cuda" if gpu else "cpu"
    return WhisperModel, dev, ("float16" if dev == "cuda" else "int8")


def repeats(words, n=3, times=3):
    """Runs where the same n words come back times in a row: Whisper's loop when it hallucinates."""
    toks = [re.sub(r"\W", "", w["w"].lower()) for w in words]
    found, i = [], 0
    while i + n * times <= len(toks):
        gram = toks[i:i + n]
        k = 1
        while toks[i + k * n:i + (k + 1) * n] == gram:
            k += 1
        if k >= times and any(gram):
            found.append((i, i + k * n - 1))
            i += k * n
        else:
            i += 1
    return found


def fold(text):
    """Lower case, no diacritics, letters and digits only: for comparing a heard word with a given name."""
    t = unicodedata.normalize("NFD", text.lower()).replace("đ", "d")
    return "".join(c for c in t if c.isalnum() and not unicodedata.combining(c))


def name_suggestions(words, names):
    """Runs of heard words that look like a given name but are not spelled like it. Exact spellings are found first,
    so "mình là Minh" next to a correct "Minh Anh" is not taken for it."""
    strip = lambda text: re.sub(r"^[\"'(]+|[\"'),.!?;:…]+$", "", text)
    heard = lambda i, n: " ".join(w["w"] for w in words[i:i + n])
    taken, out = set(), []
    for name in names:
        n = len(name.split())
        for i in range(len(words) - n + 1):
            if strip(heard(i, n)) == name:
                taken.update(range(i, i + n))
    for name in names:
        target, size = fold(name), len(name.split())
        if len(target) < 3:
            continue
        for n in sorted({size, size + 1, max(1, size - 1)}, reverse=True):
            for i in range(len(words) - n + 1):
                if any(k in taken for k in range(i, i + n)):
                    continue
                text = heard(i, n)
                if difflib.SequenceMatcher(None, fold(strip(text)), target).ratio() >= 0.8:
                    tail = text[len(text.rstrip(",.!?;:…")):]
                    out.append({"i": i, "to": i + n - 1, "why": f"looks like the name {name}", "fix": name + tail})
                    taken.update(range(i, i + n))
    return out


def invented(segments, words):
    """Segments that match a line Whisper is known to invent."""
    out = []
    for s in segments:
        low = s["text"].lower()
        hit = next((h for h in HALLUCINATIONS if h in low), None)
        if hit and s["last"] >= s["first"]:
            out.append({"i": s["first"], "to": s["last"], "why": f'"{hit}" is a line Whisper often invents: check that it was said'})
    return out


def heard_words(segments, offset=0.0, again=False):
    words, segs = [], []
    for s in segments:
        first = len(words)
        for w in s.words or []:
            if w.word.strip():
                words.append({"w": w.word.strip(), "start": round(w.start + offset, 3), "end": round(w.end + offset, 3),
                              "p": round(w.probability, 3)})
        seg = {"start": round(s.start + offset, 3), "end": round(s.end + offset, 3), "text": s.text.strip(),
               "first": first, "last": len(words) - 1, "avg_logprob": round(s.avg_logprob, 3),
               "no_speech_prob": round(s.no_speech_prob, 3), "compression_ratio": round(s.compression_ratio, 2)}
        if again:
            seg["second_pass"] = True
        segs.append(seg)
    return words, segs


def missed_voice(audio, words):
    """Stretches the voice detector calls speech but where Whisper wrote no word. Measured on real Vietnamese read
    speech (FLEURS): with the voice filter on, a whole 4 s sentence came back empty although the detector marked it as
    speech; transcribed alone, it came back right."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    out = []
    for t in get_speech_timestamps(audio, VadOptions(threshold=0.5, min_silence_duration_ms=500)):
        a, b = t["start"] / SR, t["end"] / SR
        if b - a < 0.8:
            continue
        covered = sum(max(0.0, min(b, w["end"]) - max(a, w["start"])) for w in words)
        if covered < 0.2 * (b - a):
            out.append((a, b))
    return out


def second_pass(model, audio, words, segs, lang, prompt):
    """Transcribe each missed stretch on its own and put its words in place. Returns how many stretches gave words."""
    found = 0
    for a, b in missed_voice(audio, words):
        lo, hi = max(0.0, a - 0.2), min(len(audio) / SR, b + 0.2)
        clip = audio[int(lo * SR):int(hi * SR)]
        got, _ = model.transcribe(clip, language=lang, word_timestamps=True, beam_size=5, vad_filter=False,
                                  condition_on_previous_text=False, initial_prompt=prompt)
        new_words, new_segs = heard_words(list(got), lo, again=True)
        keep = [s for s in new_segs if s["no_speech_prob"] < 0.6 and s["avg_logprob"] > -1.0 and s["last"] >= s["first"]]
        if not keep:
            continue
        new_words = [w for s in keep for w in new_words[s["first"]:s["last"] + 1]]
        found += 1
        at = sum(1 for w in words if w["start"] < lo)
        shift = len(new_words)
        for s in segs:
            if s["first"] >= at:
                s["first"] += shift
                s["last"] += shift
        k = at
        for s in keep:
            n = s["last"] - s["first"] + 1
            s["first"], s["last"] = k, k + n - 1
            k += n
        words[at:at] = new_words
        segs.extend(keep)
        segs.sort(key=lambda s: s["start"])
    return found


def review_lists(words, env, segments, names):
    """Indices of words a person should check, with the reason."""
    out = []
    if len(env):
        spans = [env[int(w["start"] / HOP):max(int(w["start"] / HOP) + 1, int(w["end"] / HOP))] for w in words]
        peaks = np.array([s.max() if len(s) else -140.0 for s in spans])
        speech = float(np.median(peaks)) if len(peaks) else -20.0
        floor = float(np.percentile(env, 10))
        quiet = min(speech - 30.0, floor + 6.0) if speech - floor > 12 else speech - 30.0
    else:
        peaks, quiet = np.zeros(len(words)), -999
    starts = {s["first"] for s in segments}
    named = {k for r in name_suggestions(words, names) for k in range(r["i"], r["to"] + 1)}
    sentence_start = True
    for i, w in enumerate(words):
        sentence_start = sentence_start or i in starts
        t = w["w"].strip()
        reasons = []
        if w["p"] < LOW_P:
            reasons.append(f"unsure ({w['p']:.2f})")
        if len(env) and peaks[i] < quiet:
            reasons.append("heard in near silence: maybe invented")
        if re.search(r"\d", t):
            reasons.append("number")
        elif t[:1].isupper() and not sentence_start and i not in named and t.strip("'\"").lower() not in ("i", "i'm", "i'll", "i've", "i'd"):
            reasons.append("name?")
        if reasons:
            out.append({"i": i, "why": ", ".join(reasons)})
        sentence_start = bool(re.search(r"[.!?…]$", t))
    for s in segments:
        if s.get("second_pass") and s["last"] >= s["first"]:
            out.append({"i": s["first"], "to": s["last"], "why": "missed on the first pass, heard on its own: check it"})
    for a, b in repeats(words):
        out.append({"i": a, "to": b, "why": "the same words repeat: Whisper may be looping"})
    out += name_suggestions(words, names) + invented(segments, words)
    return sorted(out, key=lambda r: r["i"])


def main():
    utf8_stdout()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input")
    p.add_argument("--out", required=True, help="folder")
    p.add_argument("--language", default="auto", help="vi, en, ... or auto")
    p.add_argument("--model", default="auto", choices=["auto", *MODEL_REPOS])
    p.add_argument("--names", default="", help="names, brands and terms spelled the right way, comma separated")
    p.add_argument("--verbatim", action="store_true", help="keep fillers (um, uh, ờ, ừm) and false starts")
    p.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"])
    a = p.parse_args()

    src = Path(a.input).resolve()
    if not src.is_file():
        die(f"{src} not found")
    info = probe(src)
    if not info["has_audio"]:
        die(f"{src.name} has no audio stream: there is nothing to transcribe")
    audio = decode(src)
    env = envelope_db(audio)
    if not len(audio) or env.max() < -60:
        die(f"{src.name}: the audio is silent (loudest {env.max() if len(env) else -140:.0f} dBFS)")
    duration = len(audio) / SR

    WhisperModel, dev, compute = load_model(a.model, a.device)
    name = choose_model(a.model, duration, dev == "cuda")
    lang = None if a.language == "auto" else a.language
    t0 = time.time()
    model = WhisperModel(MODEL_REPOS[name], device=dev, compute_type=compute)
    detected = None
    if not lang:
        code, prob, _ = model.detect_language(audio, vad_filter=True, language_detection_segments=3)
        detected = (code, prob)
        lang = code
    prompt = VERBATIM.get(lang, VERBATIM_ANY) if a.verbatim else STYLE.get(lang)
    names = [n.strip() for n in a.names.split(",") if n.strip()]
    print(f"{src.name}: {clock(duration)} of audio; model {name} on {dev} ({compute}); language {lang}"
          + (f" (detected, {detected[1]:.0%})" if detected else "")
          + (f"; names to check: {', '.join(names)}" if names else "") + ("; verbatim" if a.verbatim else ""))
    segments, _ = model.transcribe(
        audio, language=lang, word_timestamps=True, beam_size=5, vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500}, condition_on_previous_text=lang in CONTEXT,
        initial_prompt=prompt, hallucination_silence_threshold=2.0)
    # Names are not given to Whisper: as hotwords or in the prompt they made it drop punctuation and invent a closing
    # line ("Cảm ơn các bạn đã theo dõi") on a test film with music. They are matched against what it heard instead.
    words, segs, shown = [], [], 0.0
    for s in segments:
        w1, s1 = heard_words([s])
        for w in s1:
            w["first"] += len(words)
            w["last"] += len(words)
        words += w1
        segs += s1
        if s.end - shown >= 60:
            print(f"  ... {clock(s.end)} of {clock(duration)}, {time.time() - t0:.0f} s")
            shown = s.end
    again = second_pass(model, audio, words, segs, lang, prompt) if words else 0
    took = time.time() - t0
    if not words:
        die("Whisper heard no words. Is there speech? Try --language, or a bigger --model.")

    review = review_lists(words, env, segs, names)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    data = {
        "source": str(src), "duration": round(duration, 3), "language": lang,
        "language_probability": round(detected[1], 3) if detected else None, "model": name, "device": dev,
        "settings": {"verbatim": a.verbatim, "prompt": prompt, "names": names, "vad_min_silence_ms": 500,
                     "previous_text": lang in CONTEXT}, "checked": False,
        "words": words, "segments": segs, "review": review,
    }
    write_json(out / "transcript.json", data)
    cues, fast, long_lines = write_all(data, out / "transcript")

    lines = [f"# Words to check in {src.name}", "",
             "Whisper writes what it heard, not what was meant. Check each line with the person. Correct words with "
             "`fix.py transcript.json set N \"text\"` (or `names`, `delete`), which keeps the times and rewrites the "
             "subtitles. Run `fix.py transcript.json checked` only after the person has confirmed names and numbers.", "",
             "| # | time | heard | in context | why | suggested |", "|---|---|---|---|---|---|"]
    for r in review:
        i, j = r["i"], r.get("to", r["i"])
        heard = text_of(words[i:j + 1])
        ctx = text_of(words[max(0, i - 4): j + 5])
        span = f"{i}" if i == j else f"{i}-{j}"
        lines.append(f"| {span} | {clock(words[i]['start'])} | {heard} | {ctx} | {r['why']} | {r.get('fix', '')} |")
    if not review:
        lines.append("| - | - | - | - | nothing flagged; still read it once | |")
    (out / "review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    speech = sum(w["end"] - w["start"] for w in words)
    low = sum(1 for w in words if w["p"] < LOW_P)
    mean_p = sum(w["p"] for w in words) / len(words)
    print(f"took {took:.0f} s ({duration / max(took, 0.01):.1f}x real time)")
    if detected and detected[1] < 0.7:
        print(f"language: {detected[0]} at only {detected[1]:.0%}: ask the person and run again with --language")
    if again:
        print(f"second pass: {again} stretch(es) of voice had no words on the first pass and were transcribed alone (in review)")
    print(f"words: {len(words)}, mean confidence {mean_p:.2f}, unsure {low} ({low / len(words):.0%}); words cover {speech:.1f} s of {duration:.1f} s")
    print(f"review: {len(review)} items -> {out / 'review.md'}")
    print(f"captions: {len(cues)}" + (f", {len(fast)} faster than 17 chars/s" if fast else "") + (f", {len(long_lines)} with a long line" if long_lines else ""))
    print("->", out / "transcript.json", "and transcript.srt, .vtt, .txt")


if __name__ == "__main__":
    main()
