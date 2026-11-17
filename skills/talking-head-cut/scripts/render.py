"""Render the cut from edl.json: picture and sound cut at the same times, a short fade on the sound at every join.

  render.py work/cut/edl.json --out work/cut/cut.mp4            # full quality (H.264 CRF 18, AAC 192k)
  render.py work/cut/edl.json --out work/cut/preview.mp4 --preview   # 720p, fast, for a first look

Every piece is trimmed from the source in one FFmpeg pass and joined with the concat filter, so sound and picture
stay in step however many joins there are (cutting pieces to files and joining them with stream copy drifts by a
fraction of a frame per join). Pieces are whole frames, and the sound outside a piece's measured cut points (under a
frame) is faded to silence. Each join gets a 20 ms fade out and in on the sound: a cut in silence is then
silent, and a cut that had to land in sound does not click. Afterwards the picture and sound lengths are compared.
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # also under python -I
from common import die, need, probe, read_json, utf8_stdout

FADE = 0.02


def _version():
    r = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, errors="replace")
    try:
        return int(r.stdout.split()[2].lstrip("n").split(".")[0])
    except (IndexError, ValueError):
        return 0


def main():
    utf8_stdout()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("edl")
    p.add_argument("--out", required=True)
    p.add_argument("--preview", action="store_true", help="720p, faster encode")
    p.add_argument("--crf", type=int, default=18)
    a = p.parse_args()
    need("ffmpeg")
    e = read_json(a.edl)
    src = Path(e["source"])
    if not src.is_file():
        die(f"source film not found: {src}")
    info = probe(src)
    pieces = e["pieces"]
    fps = e.get("fps") or info["fps"] or 30
    graph, labels = [], []
    for k, pc in enumerate(pieces):
        length = pc["out"] - pc["in"]
        # The piece is whole frames; the sound plays from sound_in to sound_out and is faded to silence outside them.
        si = max(0.0, pc.get("sound_in", pc["in"]) - pc["in"])
        so = min(length, pc.get("sound_out", pc["out"]) - pc["in"])
        fades = []
        if k > 0 or si > 1e-4:
            fades.append(f"afade=t=in:st={si:.6f}:d={FADE}")
        if k < len(pieces) - 1 or so < length - 1e-4:
            fades.append(f"afade=t=out:st={max(0.0, so - FADE):.6f}:d={FADE}")
        if info["has_video"]:
            # A time on the frame grid is given half a frame early, so rounding never drops or adds that frame.
            vs, ve = (round(x * fps) / fps - 0.5 / fps if abs(x * fps - round(x * fps)) < 0.02 else x
                      for x in (pc["in"], pc["out"]))
            graph.append(f"[0:v]trim=start={max(0.0, vs):.6f}:end={ve:.6f},setpts=PTS-STARTPTS[v{k}]")
            labels.append(f"[v{k}]")
        graph.append(f"[0:a]atrim=start={pc['in']:.6f}:end={pc['out']:.6f},asetpts=PTS-STARTPTS"
                     + "".join("," + f for f in fades) + f"[a{k}]")
        labels.append(f"[a{k}]")
    v = 1 if info["has_video"] else 0
    graph.append("".join(labels) + f"concat=n={len(pieces)}:v={v}:a=1" + ("[vc][ac]" if v else "[ac]"))
    if v and a.preview:
        graph.append("[vc]scale=-2:'min(720,ih)'[vo]")
    script = Path(tempfile.mkdtemp()) / "graph.txt"
    script.write_text(";\n".join(graph), encoding="utf-8")
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # FFmpeg 7 reads a filter graph from a file with -/filter_complex; older versions with -filter_complex_script.
    new = _version() >= 7
    cmd = ["ffmpeg", "-v", "error", "-stats", "-y", "-nostdin", "-i", str(src),
           "-/filter_complex" if new else "-filter_complex_script", str(script)]
    if v:
        cmd += ["-map", "[vo]" if a.preview else "[vc]", "-r", str(fps), "-c:v", "libx264",
                "-preset", "veryfast" if a.preview else "medium", "-crf", str(28 if a.preview else a.crf),
                "-pix_fmt", "yuv420p"]
    cmd += ["-map", "[ac]", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
    r = subprocess.run(cmd)
    if r.returncode:
        die("FFmpeg failed; the command is above. A very long edit list can be split: render half the pieces at a time.")
    got = probe(out)
    expect = e.get("duration_out")
    print(f"{out}: {got['duration']:.2f} s (edit list says {expect:.2f} s), {len(pieces)} pieces")
    if got["v_duration"] and got["a_duration"]:
        diff = abs(got["v_duration"] - got["a_duration"])
        verdict = "in step" if diff <= 1.5 / fps else "NOT in step: check before delivering"
        print(f"picture {got['v_duration']:.3f} s, sound {got['a_duration']:.3f} s: {verdict}")


if __name__ == "__main__":
    main()
