"""Give a footage file of a project its matte, so the studio can cut the person out: a background swap, text or
pictures behind the person, or the person alone over other footage (project-format.md, "Layers").

  python SKILL/scripts/matte.py work/project.json --footage a-roll --from work/a-roll-alpha.mov
  python SKILL/scripts/matte.py work/project.json --footage a-roll --from "work/masks/%05d.png"

--from is what your background-removal or matting tool made for that footage, frame for frame:

- a video with transparency (ProRes 4444 or PNG in .mov, VP8 or VP9 with alpha in .webm, an animated PNG): its alpha
  becomes the matte;
- a video or a numbered image sequence of masks (white where the person is, black elsewhere): used as it is;
- RGBA images (PNG with transparency) in a sequence: their alpha.

It writes the matte as an H.264 MP4 with no sound, at the footage's size and frame rate and exactly as long, next to
the footage as <file>-matte.mp4 (or --out), adds it to media as <id>-matte, and sets media.<id>.matte. Then run
package.py build as usual: the matte is copied into the package with the rest. A matte that is shorter than the
footage by more than a tenth of a second is refused: make it for the whole file, not only for the part you used.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # also under python -I
import package as pk  # noqa: E402


def stream_info(src, rate=None):
    """pix_fmt, codec, duration and whether it has alpha, of the first video stream of src (a file or an image
    sequence pattern). VP8 and VP9 in WebM keep their alpha aside (tag alpha_mode), under a pix_fmt without one."""
    pre = ["-framerate", str(rate)] if rate and "%" in str(src) else []
    r = subprocess.run(["ffprobe", "-v", "error", *pre, "-select_streams", "v:0", "-show_entries", "stream=pix_fmt,codec_name:stream_tags=alpha_mode:format=duration",
                        "-of", "json", str(src)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        pk.die(f"cannot read {src}: {r.stderr.strip()[:300]}")
    d = json.loads(r.stdout)
    s = (d.get("streams") or [{}])[0]
    tags = {k.lower(): v for k, v in (s.get("tags") or {}).items()}
    pix = s.get("pix_fmt") or ""
    return pix, s.get("codec_name") or "", float((d.get("format") or {}).get("duration") or 0), has_alpha(pix) or str(tags.get("alpha_mode")) == "1"


def has_alpha(pix_fmt):
    return pix_fmt.startswith(("yuva", "rgba", "bgra", "argb", "abgr", "gbrap", "ya", "pal8"))


def main():
    pk.utf8_stdout()
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("project", help="project.json (work/project.json before package.py build, or a package's)")
    a.add_argument("--footage", required=True, help="the media id of the footage")
    a.add_argument("--from", dest="src", required=True, help="a video with transparency, a mask video, or an image sequence such as masks/%%05d.png")
    a.add_argument("--out", help="where to write the matte (default: next to the footage, <file>-matte.mp4)")
    o = a.parse_args()
    pk.need("ffmpeg")
    src_path, p = pk.load_project(o.project)
    m = p["media"].get(o.footage)
    if not m or m.get("kind") != "video":
        pk.die(f"{o.footage!r} is not a video in media")
    bases = [src_path.parent, Path.cwd()]
    foot = pk.find_file(m["path"], bases)
    if not foot:
        pk.die(f"file not found: {m['path']}")
    info = pk.probe(foot)
    w, h, fps, dur = info.get("width"), info.get("height"), info.get("fps") or 30, info["duration"]
    if not (w and h and dur):
        pk.die(f"cannot measure {foot}")
    pix, codec, sdur, alpha = stream_info(o.src, fps)
    if sdur and sdur < dur - 0.1:
        pk.die(f"{o.src} lasts {sdur:.2f} s and the footage {dur:.2f} s: make the matte for the whole file")
    out = Path(o.out) if o.out else foot.with_name(foot.stem + "-matte.mp4")
    pre = ["-framerate", str(fps)] if "%" in o.src else []
    if alpha and codec in ("vp8", "vp9"):
        pre += ["-c:v", "libvpx-vp9" if codec == "vp9" else "libvpx"]   # FFmpeg's own VP8/VP9 decoders drop the alpha
    take = "alphaextract," if alpha else ""
    vf = f"{take}format=gray,scale={w}:{h}:flags=bicubic,fps={fps},tpad=stop_mode=clone:stop_duration=1"
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", *pre, "-i", o.src, "-vf", vf, "-t", f"{dur:.3f}", "-an",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16", "-g", str(max(1, round(fps))), str(out)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        pk.die(f"ffmpeg could not make the matte: {r.stderr.strip()[-400:]}")
    got = pk.probe(out)
    if abs(got["duration"] - dur) > 0.1:
        pk.die(f"the matte came out {got['duration']} s long, the footage is {dur} s")
    mid = o.footage + "-matte"
    try:
        rel = out.resolve().relative_to(src_path.parent).as_posix()
    except ValueError:
        rel = out.resolve().as_posix()
    p["media"][mid] = {"kind": "video", "path": rel, "title": (m.get("title") or o.footage) + " (matte)", "duration": got["duration"],
                       "width": got.get("width"), "height": got.get("height"), "fps": got.get("fps"), "has_audio": False}
    m["matte"] = mid
    pk.write_json(src_path, p)
    print(f"{mid}: {rel} ({got.get('width')}x{got.get('height')}, {got['duration']} s, from {'its alpha' if take else 'the masks as they are'})")
    print(f"media.{o.footage}.matte = {mid!r}. Now a clip of it can take a background, and text or pictures can go behind the person.")


if __name__ == "__main__":
    main()
