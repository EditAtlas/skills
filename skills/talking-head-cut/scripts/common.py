"""Shared helpers: FFmpeg calls, audio decoding, level envelopes, transcript words, JSON and time formats."""
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

import numpy as np

SR = 16000          # analysis rate; Whisper hears 16 kHz mono too
HOP = 0.01          # envelope step in seconds

# Sure fillers: hesitation sounds with no meaning. Words that are only sometimes fillers (so, like, kiểu, thì) are
# never on this list: whether they carry meaning is a judgment, made line by line.
SURE_FILLERS = {"um", "umm", "uh", "uhm", "uhh", "erm", "er", "ah", "hmm", "mm", "mhm",
                "ờ", "ơ", "ừm", "ưm", "ầm", "ờm", "hừm", "ừ m", "uhm"}

# Words a speaker says to the editor, not to the viewer. A match is a question for you, not a cut.
NOTES = {
    "en": [r"\blet me (say|start|do|try) (that|this|it) again\b", r"\bone more time\b", r"\b(scratch|cut|delete|remove) (that|this)\b",
           r"\bno,? wait\b", r"\bstart (over|again)\b", r"\bfrom the top\b", r"\b(other|another) take\b",
           r"\btake (two|2|three|3)\b", r"\bsorry,? (i mean|let me)\b", r"\bredo (that|this|it)\b", r"\bagain,? sorry\b"],
    "vi": [r"\blàm lại\b", r"\bnói lại\b", r"\bquay lại\b", r"\b(cắt|bỏ|xoá|xóa) (đoạn|chỗ|câu) (này|đó|kia)\b",
           r"\bà không\b", r"\bnhầm\b", r"\btừ đầu\b", r"\blại nhé\b", r"\bthôi (để|cho) mình nói lại\b"],
}


def die(msg):
    sys.exit(f"{Path(sys.argv[0]).stem}: {msg}")


def utf8_stdout():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def need(tool):
    if not shutil.which(tool):
        die(f"{tool} not found in PATH. Install FFmpeg (it ships ffprobe) and open a new terminal.")


def run(cmd, **kw):
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)


def probe(path):
    """Length, frame rate, display size (phone footage: the rotation is applied) and stream lengths."""
    need("ffprobe")
    r = run(["ffprobe", "-v", "error", "-show_entries",
             "format=duration:stream=codec_type,width,height,r_frame_rate,avg_frame_rate,duration:stream_side_data=rotation",
             "-of", "json", path])
    if r.returncode:
        die(f"cannot read {path}: {r.stderr.strip()[:300]}")
    d = json.loads(r.stdout)
    info = {"duration": float(d.get("format", {}).get("duration") or 0), "has_audio": False, "has_video": False,
            "fps": None, "width": None, "height": None, "v_duration": None, "a_duration": None}
    for s in d.get("streams", []):
        if s.get("codec_type") == "video" and not info["has_video"]:
            info["has_video"] = True
            num, den = (s.get("avg_frame_rate") or s.get("r_frame_rate") or "0/1").split("/")
            fps = float(num) / float(den) if float(den) else 0
            if not fps or fps > 240:
                num, den = (s.get("r_frame_rate") or "30/1").split("/")
                fps = float(num) / float(den)
            info["fps"] = round(fps, 3)
            w, h = s.get("width"), s.get("height")
            rot = 0
            for sd in s.get("side_data_list", []) or []:
                rot = int(sd.get("rotation", 0) or 0)
            info["width"], info["height"] = (h, w) if abs(rot) % 180 == 90 else (w, h)
            info["v_duration"] = float(s["duration"]) if s.get("duration") else None
        elif s.get("codec_type") == "audio" and not info["has_audio"]:
            info["has_audio"] = True
            info["a_duration"] = float(s["duration"]) if s.get("duration") else None
    return info


def decode(path, sr=SR):
    """First audio stream as mono float32 at sr. Times match the file's own timeline from 0."""
    need("ffmpeg")
    r = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-map", "0:a:0", "-vn", "-ac", "1",
                        "-ar", str(sr), "-f", "f32le", "-"], capture_output=True)
    if r.returncode and not r.stdout:
        die(f"no audio could be read from {path}")
    return np.frombuffer(r.stdout, np.float32).copy()


def envelope_db(x, sr=SR, hop=HOP):
    """RMS level in dBFS every hop seconds."""
    h = int(sr * hop)
    n = len(x) // h
    if n == 0:
        return np.zeros(0)
    frames = x[: n * h].reshape(n, h).astype(np.float64)
    return 20 * np.log10(np.maximum(np.sqrt((frames ** 2).mean(axis=1)), 1e-7))


def levels(env, words):
    """(quiet threshold, speech level, floor) in dBFS.

    Quiet = within 35 dB of the speech, never under the room's own noise: the floor (the quietest 5 %) plus 6 dB, and
    the level most of the pauses stay under (80 % of the steps 0.15 s or more from any word) plus 3 dB. In a quiet
    room the floor decides; in a cafe or a street the noise in the pauses does, so it is not taken for speech. The
    threshold stays at least 12 dB under the speech, so soft words are never taken for quiet."""
    peaks = [env[int(w["start"] / HOP):max(int(w["start"] / HOP) + 1, int(w["end"] / HOP))] for w in words]
    peaks = [p.max() for p in peaks if len(p)]
    speech = float(np.median(peaks)) if peaks else -20.0
    floor = float(np.percentile(env, 5)) if len(env) else -90.0
    away = np.ones(len(env), bool)
    for w in words:
        away[max(0, int((w["start"] - 0.15) / HOP)):int((w["end"] + 0.15) / HOP) + 1] = False
    noise = float(np.percentile(env[away], 80)) if away.sum() >= 50 else floor
    thr = max(floor + 6.0, noise + 3.0, speech - 35.0)
    return min(thr, speech - 12.0), speech, floor


def speech_prob(x, sr=SR):
    """Probability that each HOP step is speech, from the Silero VAD model that faster-whisper ships
    (faster_whisper/assets/silero_vad_v6.onnx), run with onnxruntime, which faster-whisper installs. None when either
    is missing. The model reads 32 ms windows (512 samples at 16 kHz, each with the 64 samples before it); each step
    gets the value of the window that holds its middle."""
    try:
        import faster_whisper
        import onnxruntime
    except ImportError:
        return None
    model = Path(faster_whisper.__file__).resolve().parent / "assets" / "silero_vad_v6.onnx"
    if sr != 16000 or not model.is_file() or not len(x):
        return None
    opts = onnxruntime.SessionOptions()
    opts.intra_op_num_threads = opts.inter_op_num_threads = 1
    opts.log_severity_level = 3
    sess = onnxruntime.InferenceSession(str(model), sess_options=opts, providers=["CPUExecutionProvider"])
    win, ctx = 512, 64
    n = -(-len(x) // win)
    y = np.zeros(n * win, np.float32)
    y[:len(x)] = x
    y = y.reshape(n, win)
    before = np.zeros((n, ctx), np.float32)
    before[1:] = y[:-1, -ctx:]
    feed = np.concatenate([before, y], axis=1)
    h = np.zeros((1, 1, 128), np.float32)
    c = np.zeros((1, 1, 128), np.float32)
    probs = []
    for k in range(0, n, 2048):       # the state carries over, so the windows are read in order
        p, h, c = sess.run(None, {"input": feed[k:k + 2048], "h": h, "c": c})
        probs.append(np.asarray(p, np.float32).reshape(-1))
    p = np.concatenate(probs)[:n]
    steps = int(len(x) // int(sr * HOP))
    return p[np.minimum(((np.arange(steps) + 0.5) * HOP * sr / win).astype(int), n - 1)]


VAD_START, VAD_HOLD = 0.5, 0.35   # speech starts where the probability rises over START and lasts until it falls under HOLD
VAD_PAD = 0.1                     # seconds added before a speech run: the model's 32 ms windows start late
VAD_PAD_END = 0.2                 # seconds added after one: soft line ends fall under HOLD while still voiced
VAD_LOWER = 6.0                   # inside a speech run the level counts as sound from this many dB under the threshold
BED_GAP = 20.0                    # the bed between words is loud when it is less than this many dB under the speech


def bed_level(env, words):
    """The level most of the pauses stay under: 80 % of the steps 0.15 s or more from any word (None if too few)."""
    away = np.ones(len(env), bool)
    for w in words:
        away[max(0, int((w["start"] - 0.15) / HOP)):int((w["end"] + 0.15) / HOP) + 1] = False
    return float(np.percentile(env[away], 80)) if away.sum() >= 50 else None


def speech_runs(prob):
    """True where the VAD calls it speech: from a rise over VAD_START until a fall under VAD_HOLD, widened by VAD_PAD
    before and VAD_PAD_END after."""
    on = np.zeros(len(prob), bool)
    state = False
    for i, q in enumerate(prob):
        state = q >= (VAD_HOLD if state else VAD_START)
        on[i] = state
    before, after = int(round(VAD_PAD / HOP)), int(round(VAD_PAD_END / HOP))
    if on.any():
        idx = np.flatnonzero(np.diff(np.concatenate([[0], on.view(np.int8), [0]])))
        for a, b in zip(idx[::2], idx[1::2]):
            on[max(0, a - before):b + after] = True
    return on


def voice_levels(x, env, words):
    """(envelope to measure with, quiet threshold, speech level, floor, how).

    With a quiet room or steady noise under the voice the level alone finds speech and pauses (how = "level"). With
    music or loud noise under it, the pauses are not quiet: the bed between words is less than BED_GAP dB under the
    speech. Then a step counts as sound only where the Silero VAD calls it speech and the level is over the threshold
    (VAD_LOWER dB lower there, so soft word ends under the music are kept); every other step is moved 40 dB down
    (under the threshold), so the code that finds pauses, edges and the quietest point to cut at works unchanged and
    the order of levels inside a pause is kept. Numbers measured on takes with music 6 to 18 LU under the voice."""
    thr, speech, floor = levels(env, words)
    bed = bed_level(env, words)
    if bed is None or speech - bed >= BED_GAP:
        return env, thr, speech, floor, "level"
    gated = gate_env(x, env, thr)
    if gated is None:
        return env, thr, speech, floor, "level (no speech detector: faster-whisper missing)"
    return gated, thr, speech, floor, "level and VAD"


def gate_env(x, env, thr):
    """env with every step the VAD does not call speech moved 40 dB down and under thr; None without the VAD."""
    prob = speech_prob(x)
    if prob is None:
        return None
    on = np.zeros(len(env), bool)
    on[:min(len(env), len(prob))] = speech_runs(prob)[:len(env)]
    # Inside a speech run a soft word end under the music still counts (the threshold is VAD_LOWER dB lower there:
    # steps are raised by that much); outside one, every step is moved 40 dB down and under the threshold.
    return np.where(on, env + VAD_LOWER, np.minimum(env - 40.0, thr - 1.0))


def quiet_runs(env, thr, a, b):
    """(start, end) of every run of quiet envelope steps between times a and b."""
    i0, i1 = max(0, int(a / HOP)), min(len(env), int(b / HOP) + 1)
    out, i = [], i0
    while i < i1:
        if env[i] <= thr:
            j = i
            while j < i1 and env[j] <= thr:
                j += 1
            out.append((i * HOP, j * HOP))
            i = j
        else:
            i += 1
    return out


def islands(mask, min_gap):
    """(first, last+1) of runs of True in mask, joining runs separated by fewer than min_gap False steps."""
    idx = np.nonzero(mask)[0]
    if not len(idx):
        return []
    out, s0, prev = [], idx[0], idx[0]
    for i in idx[1:]:
        if i - prev > min_gap:
            out.append((s0, prev + 1))
            s0 = i
        prev = i
    out.append((s0, prev + 1))
    return out


def tighten(words, env, thr, join=0.1):
    """Copies of the words with times moved onto the sound, and "chunk": the stretch of sound each belongs to.

    Whisper's word times drift: the first word after a pause often starts a second early, across the pause and
    over the tail of the word before, and last words run into the silence. Word ends drift least. So the sound is
    split into chunks wherever it is quiet for `join` seconds or more, each word goes to the chunk holding its end
    (a word whose end sits in a pause goes to the chunk after it, unless half of it, or 0.25 s, lies in the chunk before, or Whisper heard it break off),
    and its times are clipped into that chunk, the chunk's first word starting and its last word ending with it.
    Chunk edges are measured; times inside a chunk are Whisper's."""
    isl = [(a * HOP, b * HOP) for a, b in islands(env > thr, int(round(join / HOP)))]
    out = [dict(w) for w in words]
    if not isl:
        return out
    # A word's soft last sound (the "t" of "checklist", a breath out) can sit apart from the rest by more than `join`.
    # A short stretch of sound that no word ends in is joined to the chunk before when it follows within 0.2 s, or to
    # the chunk after when it leads into it within 0.15 s, so the pause is measured after the release, not before it.
    ends = sorted(w["end"] - 0.04 for w in words)
    owned = [any(a - 0.05 <= t <= b + 0.05 for t in ends) for a, b in isl]
    merged = []
    for k, (a, b) in enumerate(isl):
        if merged:
            pa, pb, po = merged[-1]
            if not owned[k] and b - a <= 0.2 and a - pb <= 0.2 and po:      # a release after a word
                merged[-1] = [pa, b, po]
                continue
            if not po and pb - pa <= 0.2 and a - pb <= 0.15:                 # a breath or click leading into one
                merged[-1] = [pa, b, owned[k]]
                continue
        merged.append([a, b, owned[k]])
    isl = [(a, b) for a, b, _ in merged if b - a >= 0.04]
    starts = np.array([a for a, _ in isl])
    for w in out:
        t = w["end"] - 0.04
        k = int(np.searchsorted(starts, t, side="right")) - 1
        if k >= 0 and t <= isl[k][1]:
            w["chunk"] = k
        elif k >= 0 and (min(isl[k][1], w["end"]) - max(isl[k][0], w["start"]) >= min(0.25, 0.5 * (w["end"] - w["start"])) or
                         (re.search(r"(\.\.\.|…|-|—)$", w["w"].strip()) and w["start"] <= isl[k][1] + 0.3)):
            w["chunk"] = k            # its end ran on into the pause, but the word itself is in the chunk before
        else:
            w["chunk"] = min(k + 1, len(isl) - 1)
    for k in range(1, len(out)):          # chunks never go backwards
        out[k]["chunk"] = max(out[k]["chunk"], out[k - 1]["chunk"])
    for i, w in enumerate(out):
        a, b = isl[w["chunk"]]
        first = i == 0 or out[i - 1]["chunk"] != w["chunk"]
        last = i + 1 == len(out) or out[i + 1]["chunk"] != w["chunk"]
        w["start"] = round(a if first else min(max(w["start"], a), b), 3)
        w["end"] = round(b if last else min(max(w["end"], w["start"] + 0.02), b), 3)
    for k in range(1, len(out)):
        if out[k]["start"] < out[k - 1]["end"]:
            out[k]["start"] = out[k - 1]["end"]
            out[k]["end"] = max(out[k]["end"], out[k]["start"] + 0.02)
    return out


def gaps_between(words, duration):
    """Silence after each word, from tightened times."""
    return [round(max(0.0, (words[i + 1]["start"] if i + 1 < len(words) else duration) - w["end"]), 3)
            for i, w in enumerate(words)]


def norm(t):
    t = unicodedata.normalize("NFC", t.lower())
    return re.sub(r"[^\w\s']", " ", t).split()


def word_tokens(words):
    """One normalized token list per transcript word (a word can hold two, as in "ừ m")."""
    return [norm(w["w"]) for w in words]


def is_sure_filler(w):
    toks = norm(w["w"])
    return bool(toks) and " ".join(toks) in SURE_FILLERS


def ends_sentence(w):
    return bool(re.search(r"[.?!…。]['\"”’)]*$", w["w"].strip()))


def note_hits(text, lang):
    t = " ".join(norm(text))
    pats = NOTES.get(lang, []) + (NOTES["en"] if lang != "en" else [])
    return [m.group(0) for p in pats for m in [re.search(p, t)] if m]


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        die(f"{path} not found")
    except json.JSONDecodeError as e:
        die(f"{path} is not valid JSON: {e}")


def clock(t):
    """Seconds to m:ss.ss for reports a person reads."""
    m, s = divmod(max(0.0, t), 60)
    return f"{int(m)}:{s:05.2f}"
