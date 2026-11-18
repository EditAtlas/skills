"""Re-time Whisper's words against the sound with a small speech model (forced alignment), and flag words that sit on
no voice. Runs on onnxruntime, which faster-whisper already installs; no torch.

  align.py --list                                 # languages with a model: size, license, downloaded or not
  align.py --fetch en                             # download the model for a language now
  align.py work/t/transcript.json                 # re-time a transcript made without alignment (rewrites it)

transcribe.py calls this by itself when the model for the language is downloaded.

How: the sound around each Whisper segment goes through a wav2vec2 CTC model, which says every 20 ms how likely each
letter is. The words Whisper wrote are laid on those frames in order (CTC Viterbi). Whisper keeps the words; only
the times move:
- after a pause a word starts where the sound starts, before a pause it ends where the sound stops: by level in a
  clean recording, by the voice detector under noise or music;
- between two words said without a pause, the boundary is the middle of the model's word gap ("|" frames), moved
  EARLY seconds earlier, and one word ends where the next starts;
- a word without letters the model knows (a number such as "15", a foreign letter) is laid on a wildcard, so it
  takes the stretch between its neighbours;
- a word whose letters found almost no support in the sound (score under LOW_SCORE) where the voice detector hears
  no voice is taken for invented: it is taken out and the rest aligned again, so it cannot pull its neighbours, and
  it keeps Whisper's time. A low score over voice is often a real word the model spells differently ("eye" heard
  as "I"), so it stays.

The idea, laying Whisper's text on CTC frames segment by segment with a wildcard for unknown characters, follows
WhisperX (https://github.com/m-bain/whisperX, BSD-2-Clause, Copyright (c) 2024, Max Bain). See THIRD_PARTY_NOTICES.md.
"""
import argparse
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))  # also under python -I
from common import HOP, SR, clock, decode, die, envelope_db, read_json, utf8_stdout, write_json

# One model per language, already published as ONNX on Hugging Face, pinned to a revision. Only languages where
# alignment measurably beat Whisper's own times are listed (references/models.md): Vietnamese was measured and did
# not, so it keeps Whisper's times.
MODELS = {
    "en": {"repo": "Xenova/wav2vec2-base-960h", "rev": "a19f851b3d42865797e410752b4c570c871e4825",
           "file": "onnx/model_quantized.onnx", "size": "95 MB",
           "license": "Apache-2.0: int8 ONNX copy of facebook/wav2vec2-base-960h (trained on LibriSpeech)"},
}
FILES = ("vocab.json",)
PAD = 0.4            # seconds of sound added on each side of a segment, so a word Whisper placed late still fits
MAX_WINDOW = 30.0    # longer runs are split at their widest pause
LOW_SCORE = 0.15     # under this a word is taken for invented (references/models.md has the measurements)
JOIN = 0.25          # a gap this long between two words' letters is a pause, not a word boundary
CLEAN_DB = 25        # speech this far over the room's floor: pauses can be found by level
TAIL = 0.4           # a word before a pause ends at most this far after its last letter
TAIL_NOISY = 0.06    # with neither level nor voice detector, its last letter's end plus this
# The middle of the model's word gap fell 40-55 ms after the boundary in English (synthetic takes, and real speech
# marked by hand), so English boundaries move 40 ms earlier.
EARLY = {"en": 0.04}
LEAD = 0.15          # how far a word's edge at a pause may move from its letters to the sound


def hf_download(lang, fetch):
    """Local paths of the model files, or None when not downloaded (and fetch is False)."""
    m = MODELS[lang]
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        return None
    paths = {}
    for f in (m["file"], *FILES):
        try:
            paths[f] = hf_hub_download(m["repo"], f, revision=m["rev"], local_files_only=not fetch)
        except Exception as e:
            if fetch:
                die(f"could not download {m['repo']}/{f}: {str(e)[:200]}")
            return None
    return paths


def available(lang):
    return lang in MODELS and hf_download(lang, False) is not None


class Aligner:
    def __init__(self, lang, fetch=False, threads=4):
        import onnxruntime as ort
        paths = hf_download(lang, fetch)
        if paths is None:
            raise FileNotFoundError(f"no alignment model downloaded for {lang}")
        m = MODELS[lang]
        self.repo = m["repo"]
        vocab = json.loads(Path(paths["vocab.json"]).read_text(encoding="utf-8"))
        self.vocab = {unicodedata.normalize("NFC", k): v for k, v in vocab.items()}
        self.blank = next(v for k, v in vocab.items() if k.lower() in ("<pad>", "[pad]"))
        self.sep = vocab.get("|")
        self.upper = not any(k.isalpha() and k.islower() for k in vocab)
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        so.inter_op_num_threads = 1
        so.log_severity_level = 3
        self.sess = ort.InferenceSession(paths[m["file"]], so, providers=["CPUExecutionProvider"])

    def tokens(self, word):
        """Letter ids for one written word; None when it holds a digit or a letter the model does not know."""
        t = unicodedata.normalize("NFC", word.upper() if self.upper else word.lower())
        ids = []
        for c in t:
            if c in self.vocab and c != "|":
                ids.append(self.vocab[c])
            elif c.isalnum():
                return None
        return ids or None

    def emissions(self, x):
        """Log-probabilities, frames x vocabulary (one frame per 20 ms)."""
        x = (x - x.mean()) / np.sqrt(x.var() + 1e-7)
        if len(x) < 400:
            x = np.pad(x, (0, 400 - len(x)))
        logits = self.sess.run(None, {self.sess.get_inputs()[0].name: x[None].astype(np.float32)})[0][0]
        logits = logits - logits.max(1, keepdims=True)
        return logits - np.log(np.exp(logits).sum(1, keepdims=True))


def viterbi(lp, labels):
    """CTC forced alignment: the best path through labels (blank, token, blank, token, ..., blank) over the frames
    of lp. Returns the label index of every frame, or None when the text cannot fit."""
    T, S = lp.shape[0], len(labels)
    if T < (S - 1) // 2:
        return None
    em = lp[:, labels]
    lab = np.array(labels)
    skip = np.zeros(S, bool)
    skip[2:] = (lab[2:] != lab[:-2]) & (lab[2:] != labels[0])
    neg = -1e30
    d = np.full(S, neg)
    d[0], d[1] = em[0, 0], em[0, 1]
    bp = np.zeros((T, S), np.int8)
    for t in range(1, T):
        step = np.concatenate(([neg], d[:-1]))
        jump = np.where(skip, np.concatenate(([neg, neg], d[:-2])), neg)
        best = np.maximum(d, np.maximum(step, jump))
        bp[t] = np.where(best == d, 0, np.where(best == step, 1, 2))
        d = best + em[t]
    s = S - 1 if d[S - 1] >= d[S - 2] else S - 2
    if d[s] < neg / 2:
        return None
    path = np.empty(T, np.int64)
    for t in range(T - 1, -1, -1):
        path[t] = s
        s -= int(bp[t, s])
    return path


def align_window(al, x, t0, words, idx):
    """Align words[idx] in audio x, which starts at t0. Returns {word index: [first letter start, last letter end,
    score, middle of the word gap before it]}. A word without letters is laid on a wildcard (any letter) and gets
    score None."""
    lp = al.emissions(x)
    T, V = lp.shape
    dt = len(x) / SR / T
    star = lp[:, [c for c in range(V) if c != al.blank]].max(1, keepdims=True)
    lp = np.concatenate([lp, star], 1)
    labels, owner, letter = [al.blank], [-1], [False]
    for k in idx:
        if al.sep is not None and len(labels) > 1:
            labels += [al.sep, al.blank]
            owner += [k, -1]
            letter += [False, False]
        for c in (words[k]["_ids"] if words[k]["_ids"] is not None else [V]):
            labels += [c, al.blank]
            owner += [k, -1]
            letter += [True, False]
    path = viterbi(lp, labels)
    if path is None:
        return {}
    spans = {}
    for f, s in enumerate(path):
        k = owner[s]
        if k < 0:
            continue
        d = spans.setdefault(k, {"f": [], "sep": [], "p": {}})
        if letter[s]:
            d["f"].append(f)
            d["p"].setdefault(s, []).append(float(np.exp(lp[f, labels[s]])))
        else:
            d["sep"].append(f)
    res = {}
    for k, d in spans.items():
        if not d["f"]:
            continue
        # a letter's score is how sure the model was of it at its best frame; the word's is the mean over letters
        score = float(np.mean([max(v) for v in d["p"].values()])) if words[k]["_ids"] is not None else None
        sep = t0 + (float(np.mean(d["sep"])) + 0.5) * dt if d["sep"] else None
        res[k] = [t0 + min(d["f"]) * dt, t0 + (max(d["f"]) + 1) * dt, score, sep]
    return res


def windows(words, segments, duration):
    """Runs of word indices to align together, with the audio span of each: one run per Whisper segment, padded by
    PAD into the pause on each side but never past the middle of that pause."""
    runs, seen = [], set()
    for s in sorted(segments, key=lambda s: s["first"]):
        g = [k for k in range(s["first"], s["last"] + 1) if k not in seen]
        seen.update(g)
        if g:
            runs.append(g)
    runs += [[k] for k in range(len(words)) if k not in seen]
    runs.sort(key=lambda g: g[0])
    split = []
    for g in runs:
        while len(g) > 1 and words[g[-1]]["end"] - words[g[0]]["start"] > MAX_WINDOW:
            gaps = [(words[g[i + 1]]["start"] - words[g[i]]["end"], i) for i in range(len(g) - 1)
                    if words[g[i + 1]]["start"] - words[g[0]]["start"] <= MAX_WINDOW]
            cut = max(gaps)[1] + 1 if gaps else len(g) // 2
            split.append(g[:cut])
            g = g[cut:]
        split.append(g)
    out = []
    for n, g in enumerate(split):
        a, b = words[g[0]]["start"], words[g[-1]]["end"]
        lo, hi = a - PAD, b + PAD
        if n:
            prev = words[split[n - 1][-1]]["end"]
            lo = max(lo, (prev + a) / 2 if prev < a else a)
        if n + 1 < len(split):
            nxt = words[split[n + 1][0]]["start"]
            hi = min(hi, (b + nxt) / 2 if nxt > b else b)
        out.append((g, max(0.0, lo), min(duration, max(hi, b))))
    return out


def quiet_mask(audio, words):
    """True every 10 ms where the sound is quiet, or None when the recording is too noisy to tell by level."""
    env = envelope_db(audio)
    if not len(env):
        return None
    peaks = [env[int(w["start"] / HOP):max(int(w["start"] / HOP) + 1, int(w["end"] / HOP))] for w in words]
    peaks = [q.max() for q in peaks if len(q)]
    speech = float(np.median(peaks)) if peaks else -20.0
    floor = float(np.percentile(env, 5))
    # the level of the pauses: steps at least 0.15 s from any word Whisper heard
    away = np.ones(len(env), bool)
    for w in words:
        away[max(0, int((w["start"] - 0.15) / HOP)):int((w["end"] + 0.15) / HOP) + 1] = False
    noise = float(np.percentile(env[away], 80)) if away.sum() >= 50 else floor
    if speech - max(floor, noise) < CLEAN_DB:
        return None
    return env < max(floor + 6.0, noise + 3.0, speech - 35.0)


def voice_mask(audio):
    """True every 10 ms where Silero VAD (shipped with faster-whisper) hears a voice; None if it cannot run."""
    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps
    except ImportError:
        return None
    mask = np.zeros(len(audio) // int(SR * HOP) + 1, bool)
    for seg in get_speech_timestamps(audio, VadOptions(threshold=0.5, min_silence_duration_ms=100, speech_pad_ms=30)):
        mask[int(seg["start"] / SR / HOP):int(seg["end"] / SR / HOP) + 1] = True
    return mask


def voiced(voice, a, b):
    """Share of a..b where a voice is heard (1.0 when there is no detector)."""
    if voice is None or a is None:
        return 1.0
    part = voice[max(0, int(a / HOP)):max(int(a / HOP) + 1, int(b / HOP))]
    return float(part.mean()) if len(part) else 0.0


def quiet_run(quiet, a, b):
    """Longest stretch of quiet, in seconds, between times a and b."""
    best = run = 0
    for q in quiet[max(0, int(a / HOP)):max(0, int(b / HOP))]:
        run = run + 1 if q else 0
        best = max(best, run)
    return best * HOP


def place(words, got, quiet, duration, early=0.0):
    """Word times from the aligned letters (got: {index: [first letter, last letter end, score, gap middle]}).
    quiet: True every 10 ms where nobody speaks (by level in a clean recording, else by the voice detector), or None."""
    def q(t):
        k = int(t / HOP)
        return quiet is not None and 0 <= k < len(quiet) and bool(quiet[k])

    joined = set()                       # i: word i ends where word i + 1 starts
    for i in sorted(got):
        cs, ce = got[i][0], got[i][1]
        prev = got.get(i - 1)
        if prev is None or cs - prev[1] >= JOIN or (quiet is not None and quiet_run(quiet, prev[1], cs) >= 0.06):
            # after a pause the word starts where the sound does: back from its first letter (an "r" or "l" swells
            # before the model is sure of it), or forward when that letter was laid on the pause (noise read as "s")
            s = cs
            if q(cs):
                while q(s) and s + HOP < min(ce, cs + LEAD):
                    s += HOP
            elif quiet is not None:
                lo = max(cs - LEAD, prev[1] + 0.02 if prev is not None else 0.0)
                while s - HOP >= lo and not q(s - HOP):
                    s -= HOP
            words[i]["_s"] = s
        else:
            sep = got[i][3]
            b = sep if sep is not None and prev[1] <= sep <= cs else (prev[1] + cs) / 2
            b = max(prev[1] - 0.02, b - early)
            words[i]["_s"] = b
            words[i - 1]["_e"] = b
            joined.add(i - 1)
    for i in sorted(got):
        if i in joined:
            continue
        ce = got[i][1]
        limit = min(duration, words[i + 1]["_s"] - 0.02 if i + 1 in got else ce + TAIL, ce + TAIL)
        e = ce
        if quiet is None:
            e = ce + TAIL_NOISY
        elif q(ce - HOP):
            # the last letter ran on into the pause: back to where the sound stops
            while q(e - HOP) and e - HOP > max(words[i]["_s"] + 0.05, ce - LEAD):
                e -= HOP
        else:
            while not q(e) and e + HOP <= limit:
                e += HOP
        words[i]["_e"] = max(words[i]["_s"] + 0.02, min(e, limit))


def align(audio, words, segments, lang, fetch=False, threads=4, log=print):
    """Re-time words in place. Adds "score" (0-1; None for a word without letters) and "aligned" (true when its
    letters were found in the sound) to every word. Returns a summary, or None when there is no model."""
    if lang not in MODELS:
        return None
    try:
        al = Aligner(lang, fetch, threads)
    except (FileNotFoundError, ImportError) as e:
        log(f"alignment skipped: {e}")
        return None
    t0, shown = time.time(), 0.0
    duration = len(audio) / SR
    for w in words:
        w["_ids"] = al.tokens(w["w"])
    got, low = {}, []
    voice = voice_mask(audio)
    for g, lo, hi in windows(words, segments, duration):
        x = audio[int(lo * SR):int(hi * SR)]
        res = align_window(al, x, lo, words, g) if len(x) >= int(0.1 * SR) else {}
        # a word whose letters the model barely heard is taken out, and the rest aligned again without it, so an
        # invented word cannot pull its neighbours' times
        bad = [k for k in g if k in res and res[k][2] is not None and res[k][2] < LOW_SCORE
               and min(voiced(voice, words[k]["start"], words[k]["end"]), voiced(voice, res[k][0], res[k][1])) < 0.3]
        if bad:
            rest = [k for k in g if k not in bad]
            again = align_window(al, x, lo, words, rest) if rest else {}
            if again or not rest:
                for k in bad:
                    again[k] = [None, None, res[k][2], None]
                res = again
        for k in g:
            w = words[k]
            start, end, score, sep = res.get(k, (None, None, None, None))
            w["score"] = None if score is None else round(score, 3)
            w["aligned"] = start is not None and score is not None
            if start is not None:
                got[k] = res[k]
            if k in bad:
                low.append(k)
        if hi - shown >= 120:
            log(f"  aligned {clock(hi)} of {clock(duration)}, {time.time() - t0:.0f} s")
            shown = hi
    quiet = quiet_mask(audio, words)
    if quiet is None and voice is not None:
        quiet = ~voice
    place(words, got, quiet, duration, EARLY.get(lang, 0.0))
    # A word the alignment could not place (its window failed) takes the time between its placed neighbours,
    # shared by Whisper's lengths when several follow each other. Low-score words keep Whisper's time.
    n, i = len(words), 0
    while i < n:
        if "_s" in words[i] or i in low:
            i += 1
            continue
        j = i
        while j + 1 < n and "_s" not in words[j + 1] and j + 1 not in low:
            j += 1
        a = words[i - 1]["_e"] if i and "_e" in words[i - 1] else words[i]["start"]
        b = words[j + 1]["_s"] if j + 1 < n and "_s" in words[j + 1] else words[j]["end"]
        if b - a >= 0.02 * (j - i + 1):
            total = sum(max(0.05, words[k]["end"] - words[k]["start"]) for k in range(i, j + 1))
            at = a
            for k in range(i, j + 1):
                d = (b - a) * max(0.05, words[k]["end"] - words[k]["start"]) / total
                words[k]["_s"], words[k]["_e"] = at, at + d
                at += d
        i = j + 1
    aligned = 0
    for w in words:
        if "_s" in w:
            w["start"], w["end"] = round(w["_s"], 3), round(w["_e"], 3)
        aligned += w["aligned"]
        for k in ("_ids", "_s", "_e"):
            w.pop(k, None)
    for i in range(1, n):                       # keep the order Whisper heard them in
        if words[i]["start"] < words[i - 1]["start"]:
            words[i]["start"] = words[i - 1]["start"]
        if words[i]["end"] < words[i]["start"] + 0.02:
            words[i]["end"] = round(words[i]["start"] + 0.02, 3)
    return {"model": al.repo, "aligned": aligned, "words": n, "low_score": low, "took_s": round(time.time() - t0, 1)}


def main():
    utf8_stdout()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("transcript", nargs="?")
    p.add_argument("--fetch", metavar="LANG", choices=list(MODELS), help="download the model for this language")
    p.add_argument("--list", action="store_true", help="languages with a model")
    a = p.parse_args()
    if a.fetch:
        m = MODELS[a.fetch]
        print(f"downloading {m['repo']} ({m['size']}) ...")
        print("->", Path(hf_download(a.fetch, True)[m["file"]]).parent.parent)
    if a.list or not (a.transcript or a.fetch):
        for lang, m in MODELS.items():
            print(f"{lang}  {m['size']:<7} {'downloaded' if available(lang) else 'not downloaded':<15} {m['repo']}  {m['license']}")
    if not a.transcript:
        return
    t = read_json(a.transcript)
    lang = t.get("language")
    if lang not in MODELS:
        die(f"no alignment model for language {lang!r}; Whisper's times stay")
    if t.get("alignment"):
        die("this transcript is already aligned")
    audio = decode(t["source"])
    if not len(audio):
        die(f"cannot read the audio of {t['source']}")
    info = align(audio, t["words"], t.get("segments", []), lang)
    if info is None:
        die(f"the {lang} model is not downloaded: align.py --fetch {lang} ({MODELS[lang]['size']})")
    t["alignment"] = {k: v for k, v in info.items() if k != "low_score"}
    write_json(a.transcript, t)
    print(f"aligned {info['aligned']} of {info['words']} words in {info['took_s']} s with {info['model']}; "
          f"{len(info['low_score'])} with almost no support in the sound")
    print("subtitles and review.md are not rewritten: run transcribe.py again with alignment to get both")


if __name__ == "__main__":
    main()
