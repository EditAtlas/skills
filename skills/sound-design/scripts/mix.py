"""Place EditAtlas sounds on a video from a cue sheet and render it.

  mix.py work/cues.json --out result/film_sfx.mp4

Writes FILM_sfx.mp4 (the video stream copied, new audio), FILM_sfx_track.wav (the sounds alone, same length as
the film), FILM_resolved.json (where every sound really landed and at what level) and prints a short report.

Cue sheet:
{
  "video": "work/film.mp4",
  "keep_audio": true,          # keep the film's own music/voice under the sounds (false: replace it)
  "under_voice": false,        # true: the film is carried by speech; sounds sit ~8 LU under it (else ~3 LU under music)
  "cues": [
    {"t": 1.20, "id": "sfx-...", "role": "whoosh", "label": "card slides in"},
    {"t": 2.05, "id": "sfx-...", "role": "hit", "gain_db": -2, "max_len": 1.2},
    {"t": 0.00, "id": "sfx-...", "role": "ambience", "bed": true}           # one bed under the whole film
  ]
}
Per cue: anchor start|peak|end (default by role), gain_db, max_len (s, then a fade), fade_in, fade_out,
offset_in (s into the file to start from), pan (-1..1).
"""
import argparse
import json
from pathlib import Path

import numpy as np

from common import (ROLE_ANCHOR, ROLE_PEAK_DB, SR, by_id, db, decode, die, fetch, load_index, lufs, measured,
                    probe, run, utf8_stdout, window_db, write_json)

SFX_ONLY_LUFS = -16.0  # a film whose sound is only these sounds is brought to this loudness (social video sits -14..-16)
BED_DBFS = -54.0     # median 250 ms level of a bed in the master: at the edge of hearing
LIMIT_DB = -1.0


def fade(x, n_in, n_out):
    if n_in > 0:
        n_in = min(n_in, len(x))
        x[:n_in] *= np.linspace(0, 1, n_in, dtype=np.float32)[:, None]
    if n_out > 0:
        n_out = min(n_out, len(x))
        x[-n_out:] *= np.linspace(1, 0, n_out, dtype=np.float32)[:, None]
    return x


def prepare(cue, sound, m, path, under_voice):
    role = cue.get("role") or sound["category"]
    x = decode(path)
    off = float(cue.get("offset_in", 0.0))
    if off:
        x = x[int(off * SR):]
    # a sound whose channels cancel disappears on a phone: play its louder channel in both
    notes = []
    if m and m["mono_loss_db"] < -6:
        ch = int(np.argmax((x ** 2).mean(axis=0)))
        x = np.repeat(x[:, ch:ch + 1], 2, axis=1)
        notes.append(f"mono-safe: channels cancelled ({m['mono_loss_db']} dB), used channel {ch}")
    if cue.get("max_len"):
        x = x[: int(float(cue["max_len"]) * SR)]
        x = fade(x, 0, int(SR * float(cue.get("fade_out", 0.08))))
    x = fade(x, int(SR * float(cue.get("fade_in", 0.0))), int(SR * float(cue.get("fade_out", 0.01))))
    if cue.get("pan"):
        p = float(np.clip(cue["pan"], -1, 1))
        x = x * np.array([np.cos((p + 1) * np.pi / 4), np.sin((p + 1) * np.pi / 4)], np.float32) * np.sqrt(2)
    peak = float(np.abs(x).max()) or 1e-9
    target = ROLE_PEAK_DB.get(role, ROLE_PEAK_DB["default"]) + float(cue.get("gain_db", 0))
    x = x * (10 ** (target / 20) / peak)
    anchor = cue.get("anchor") or ROLE_ANCHOR.get(role, "peak")
    a_start = max(0.0, (m["audible_start_s"] if m else 0) - off)
    a_peak = max(0.0, (m["peak_t_s"] if m else 0) - off)
    a_end = max(0.0, min(len(x) / SR, (m["audible_end_s"] if m else len(x) / SR) - off))
    if cue.get("max_len") or off:
        env = np.abs(x).max(axis=1)
        a_peak = float(env.argmax() / SR)
    lead = {"start": a_start, "peak": a_peak, "end": a_end}.get(anchor, a_peak)
    return x.astype(np.float32), role, target, anchor, lead, notes


def main():
    utf8_stdout()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("sheet")
    p.add_argument("--out", required=True)
    p.add_argument("--cache")
    p.add_argument("--mirror")
    p.add_argument("--no-video", action="store_true", help="only write the SFX track")
    a = p.parse_args()
    sheet = json.loads(Path(a.sheet).read_text(encoding="utf-8"))
    video = sheet.get("video") or die("the sheet needs \"video\"")
    info = probe(video)
    n = int(info["duration"] * SR)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    stem = out.with_suffix("")
    index, mirror = load_index(a.cache, a.mirror or sheet.get("mirror"))
    table = by_id(index)
    track = np.zeros((n, 2), np.float32)
    bed = np.zeros((n, 2), np.float32)
    resolved = []
    for k, cue in enumerate(sorted(sheet.get("cues", []), key=lambda c: c["t"])):
        s = table.get(cue.get("id")) or die(f"cue {k} at {cue.get('t')}: unknown id {cue.get('id')}")
        path = fetch(s, a.cache, mirror)
        m = measured(s, a.cache, mirror)
        if cue.get("bed"):
            x = decode(path)
            if len(x) == 0:
                continue
            reps = int(np.ceil(n / max(1, len(x) - SR))) + 1
            xf = fade(x.copy(), SR, SR)                      # 1 s crossfades, no hard loop seam
            hop = max(1, len(x) - SR)
            for r in range(reps):
                i0 = r * hop
                if i0 >= n:
                    break
                seg = xf[: n - i0]
                bed[i0:i0 + len(seg)] += seg
            resolved.append({"t": 0.0, "id": s["id"], "title": s["title"], "role": "bed", "bed": True})
            continue
        x, role, target, anchor, lead, notes = prepare(cue, s, m, path, sheet.get("under_voice"))
        i0 = int(round((float(cue["t"]) - lead) * SR))
        cut = 0.0
        if i0 < 0:
            cut = -i0 / SR
            x, notes = x[-i0:], notes + [f"started {cut:.3f}s into the file (the moment is too early)"]
            lead -= cut
            i0 = 0
        x = x[: max(0, n - i0)]
        track[i0:i0 + len(x)] += x
        resolved.append({"t": float(cue["t"]), "id": s["id"], "title": s["title"], "category": s["category"],
                         "role": role, "anchor": anchor, "placed_at": round(i0 / SR, 3),
                         "lands_at": round(i0 / SR + lead, 3), "len_s": round(len(x) / SR, 3), "lead_s": round(lead, 4),
                         "path": str(path), "offset_in": float(cue.get("offset_in", 0.0)) + cut,
                         "peak_dbfs": round(target, 1), "label": cue.get("label"), "notes": notes,
                         "measured": m})
    keep = sheet.get("keep_audio", True) and info["has_audio"]
    master_db, target_lufs = 0.0, float(sheet.get("target_lufs", SFX_ONLY_LUFS))
    if keep:
        # the sounds sit under the film's own audio: under a voice about 8 LU quieter, under music about 3 LU
        film_I, _ = lufs(video)
        if film_I is not None and film_I > -70:
            target_lufs = film_I - float(sheet.get("under_film_lu", 8 if sheet.get("under_voice") else 3))
    if np.abs(track).max() > 0:
        tmp = Path(str(stem) + "_tmp_level.wav")
        write_wav(tmp, track)
        I, _ = lufs(tmp)
        tmp.unlink()
        if I is not None and I > -70:
            master_db = target_lufs - I
            master_db = min(master_db, 18.0)
            track *= 10 ** (master_db / 20)
            for c in resolved:
                if not c.get("bed"):
                    c["peak_dbfs"] = round(c["peak_dbfs"] + master_db, 1)
    # the bed sits at an absolute level: its median 250 ms window at BED_DBFS
    if np.abs(bed).max() > 0:
        w = window_db(bed.mean(axis=1))
        med = float(np.median(w[w > -100])) if (w > -100).any() else -100
        bed *= 10 ** ((float(sheet.get("bed_dbfs", BED_DBFS)) - med) / 20)
    sfx = track + bed
    pk = float(np.abs(sfx).max())
    if pk > 10 ** (LIMIT_DB / 20):
        print(f"note: sounds overlap to {db(pk):+.1f} dBFS; the final limiter holds the mix at {LIMIT_DB} dBFS")
    wav = Path(str(stem) + "_track.wav")
    nobed = Path(str(stem) + "_track_nobed.wav")
    write_wav(wav, sfx)
    write_wav(nobed, track)
    write_json(str(stem) + "_resolved.json", {"video": str(Path(video).resolve()), "out": str(out.resolve()), "keep_audio": sheet.get("keep_audio", True),
                                               "under_voice": bool(sheet.get("under_voice")),
                                               "duration": info["duration"], "master_gain_db": round(master_db, 1),
                                               "cues": resolved})
    if a.no_video:
        print("->", wav)
        return
    lim = f"alimiter=limit={10 ** (LIMIT_DB / 20):.4f}:level=disabled"
    if keep:
        g = float(sheet.get("film_gain_db", 0))
        filt = (f"[0:a]aresample={SR},aformat=channel_layouts=stereo,volume={g}dB[f];"
                f"[1:a]aformat=channel_layouts=stereo[s];[f][s]amix=inputs=2:normalize=0:duration=first,{lim}[a]")
    else:
        filt = f"[1:a]aformat=channel_layouts=stereo,{lim}[a]"
    r = run(["ffmpeg", "-v", "error", "-y", "-nostdin", "-i", video, "-i", wav, "-filter_complex", filt,
             "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-shortest", out])
    if r.returncode:
        die("ffmpeg failed: " + r.stderr[-600:])
    print(f"{len(resolved)} sounds placed ({sum(1 for c in resolved if c.get('bed'))} bed), "
          f"film audio {'kept' if keep else 'replaced'}"
          + f", sounds set {master_db:+.1f} dB to {target_lufs:.1f} LUFS")
    for c in resolved:
        if not c.get("bed"):
            print(f"  {c['t']:7.3f} {c['role']:<9} {c['anchor']:<5} {c['peak_dbfs']:>6} dB  {c['title'][:36]}"
                  + (f"  ({c['label']})" if c.get("label") else "") + ("  ! " + "; ".join(c["notes"]) if c["notes"] else ""))
    print("->", out, "|", wav)


def write_wav(path, x):
    import wave
    y = np.clip(x, -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((y * 32767).astype("<i2").tobytes())


if __name__ == "__main__":
    main()
