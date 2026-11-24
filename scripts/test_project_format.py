"""Tests for the editatlas-project/1 format: its JSON Schema, package.py's check, and the converters in
editable-export/scripts/convert.py.

  pip install jsonschema                          # the schema checks
  pip install opentimelineio otio-fcp-adapter     # optional: read the .otio and the FCP7 XML back with them
  python scripts/test_project_format.py

Needs FFmpeg for the projects package.py builds. Nothing reaches the network.

- The schema is valid JSON Schema 2020-12, at the address the site serves it from.
- Projects as package.py builds and saves them, and one that uses every field, pass the schema and package.py check.
- Broken projects and versions fail the schema; the ones package.py check can see fail there too.
- convert.py writes OTIO and FCP7 XML whose frames match the project: read with the standard library, and, when they
  are installed, with OpenTimelineIO and its FCP XML adapter.
"""
import copy
import json
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "editable-export"
SCHEMA_FILE = SKILL / "references" / "editatlas-project-1.schema.json"
sys.path.insert(0, str(SKILL / "scripts"))
import package as pk  # noqa: E402

try:
    import jsonschema
    import referencing
except ImportError:
    sys.exit("pip install jsonschema (it brings referencing)")

failures = []


def check(name, ok, detail=""):
    print(("PASS" if ok else "FAIL"), name, ("" if ok else detail))
    if not ok:
        failures.append(name)


SCHEMA = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
FC = jsonschema.Draft202012Validator.FORMAT_CHECKER
REG = referencing.Registry().with_resource(SCHEMA["$id"], referencing.Resource.from_contents(SCHEMA))
PROJECT = jsonschema.Draft202012Validator(SCHEMA, format_checker=FC)
VERSION = jsonschema.Draft202012Validator({"$ref": SCHEMA["$id"] + "#/$defs/version"}, registry=REG, format_checker=FC)


def errors(obj, v=PROJECT):
    return ["/".join(map(str, e.absolute_path)) + ": " + e.message for e in v.iter_errors(obj)]


# ------------------------------------------------------------------ the schema itself
try:
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    check("the schema is valid JSON Schema 2020-12", True)
except jsonschema.SchemaError as e:
    check("the schema is valid JSON Schema 2020-12", False, str(e)[:300])
check("the schema says 2020-12 and lives at /schemas/editatlas-project-1.schema.json on the site",
      SCHEMA["$schema"] == "https://json-schema.org/draft/2020-12/schema"
      and SCHEMA["$id"] == "https://edit.trysometh.ing/schemas/editatlas-project-1.schema.json")
check("the format reference links the schema", SCHEMA_FILE.name in (SKILL / "references" / "project-format.md").read_text(encoding="utf-8"))

# Every field the format reference names, in one project.
FULL = {
    "format": "editatlas-project/1", "title": "Every field",
    "canvas": {"width": 1080, "height": 1920, "fps": 30, "background": "#000000"},
    "media": {
        "a-roll": {"kind": "video", "path": "media/a.mp4", "duration": 10.0, "width": 1080, "height": 1920, "fps": 29.97, "has_audio": True},
        "b-roll": {"kind": "video", "path": "media/b.mp4", "duration": 8.0, "width": 1920, "height": 1080, "fps": 60, "has_audio": False, "title": "Beach"},
        "pop": {"kind": "audio", "path": "media/pop.wav", "duration": 0.4, "title": "pop"},
        "music": {"kind": "audio", "path": "media/music.mp3", "title": None},
        "card": {"kind": "image", "path": "media/card.webp", "width": 900, "height": 700, "fps": 60, "duration": 2.5},
        "anton": {"kind": "font", "path": "media/fonts/Anton-400.woff2", "family": "Anton", "weight": 400, "style": "normal"},
    },
    "styles": {
        "caption": {"font": "Anton", "weight": 400, "size": 72, "color": "#ffffff", "y": 0.72, "stroke": {"color": "#000", "width": 10},
                    "highlight": "#ffd60a", "reveal": "word", "in": {"type": "pop", "dur": 0.12}, "case": "upper"},
        "card": {"size": 40, "color": "#111", "align": "left", "box": {"color": "#fff", "pad_x": 24, "pad_y": 12, "radius": 14, "opacity": 1},
                 "shadow": {"color": "rgba(0,0,0,.5)", "blur": 12, "x": 0, "y": 4}, "line_height": 1.2, "letter_spacing": 1,
                 "max_width": 0.6, "italic": False, "opacity": 1, "rotation": 0, "out": None,
                 "strike": {"color": "#ff3b30", "width": 6, "at": 0.4, "dur": 0.3}},
    },
    "tracks": [
        {"id": "V1", "kind": "video", "name": "Footage", "hidden": False, "muted": False, "clips": [
            {"id": "c1", "media": "a-roll", "in": 0.4, "out": 5.2, "volume": 1.0, "fit": "cover", "x": 0.5, "y": 0.45, "scale": 1.0, "zoom_to": 1.08, "label": "hook"},
            {"id": "c2", "media": "b-roll", "in": 2.0, "out": 6.0, "speed": 2, "fit": "contain", "transition": {"type": "dissolve", "dur": 0.5}},
            {"id": "c2-2", "media": "a-roll", "in": 6.0, "out": 8.0, "transition": None}]},
        {"id": "T1", "kind": "text", "name": "Captions", "items": [
            {"id": "t1", "style": "caption", "text": "Saying no", "at": 0.4, "dur": 0.9, "words": [{"at": 0.0, "dur": 0.42}, {"at": 0.42, "dur": 0.48}]},
            {"id": "t1-2", "style": "caption", "text": "is fine", "at": 1.3, "dur": 0.8, "in": None, "out": None, "case": ""}]},
        {"id": "G1", "kind": "image", "name": "Graphics", "hidden": False, "items": [
            {"id": "g-yes", "media": "card", "at": 1.5, "dur": 5.9, "x": 0.5, "y": 0.59, "width": 0.78, "opacity": 1, "rotation": 0,
             "in": {"type": "pop", "dur": 0.2}, "out": {"type": "fade", "dur": 0.15}, "loop": False, "from": 0, "label": "YES card",
             "keys": [{"t": 0, "dy": 40, "opacity": 0}, {"t": 0.3, "dy": 0, "opacity": 1, "ease": "out"}, {"t": 2.6, "rotate": -8, "dx": 3, "scale": 1.1, "ease": "back"}]}]},
        {"id": "T2", "kind": "text", "name": "Card words", "items": [
            {"id": "yes-title", "parent": "g-yes", "style": "card", "text": "This client project", "at": 1.54, "dur": 5.86, "x": 0.26, "y": 0.42,
             "keys": [{"t": 0, "scale": 0.6, "opacity": 0}, {"t": 0.25, "scale": 1, "opacity": 1, "ease": "back"}]}]},
        {"id": "A1", "kind": "audio", "name": "Sounds", "muted": False, "items": [
            {"id": "s1", "media": "pop", "at": 2.68, "in": 0.0, "out": None, "gain_db": -14.0, "fade_in": 0.0, "fade_out": 0.01, "label": "YES badge"},
            {"id": "m1", "media": "music", "at": 0, "in": 3.0, "out": 20.0, "gain_db": -18, "gain_keys": [{"t": 3.0, "db": 0}, {"t": 3.5, "db": -12}]}]},
    ],
    "notes": [{"id": "note-1", "at": 2.4, "text": "cut this faster"}],
    "x-other-tool": {"anything": True},
    "$schema": "https://edit.trysometh.ing/schemas/editatlas-project-1.schema.json",
}
check("a project with every field passes the schema", not errors(FULL), errors(FULL)[:5])
check("... and package.py check", not pk.check(FULL), pk.check(FULL)[:5])


# ------------------------------------------------------------------ projects package.py writes
def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def make_sources(d):
    """Footage A (4 s, 30 fps, with sound), footage B (3 s, no sound), a picture and a tone, in d."""
    d.mkdir(parents=True, exist_ok=True)
    ffmpeg("-f", "lavfi", "-i", "testsrc2=size=360x640:rate=30:duration=4", "-f", "lavfi", "-i", "sine=frequency=330:duration=4",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(d / "a.mp4"))
    ffmpeg("-f", "lavfi", "-i", "testsrc=size=360x640:rate=30:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(d / "b.mp4"))
    ffmpeg("-f", "lavfi", "-i", "color=c=red:s=200x100", "-frames:v", "1", str(d / "badge.png"))
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=880:duration=1.5", str(d / "tone.wav"))


SOURCE = {
    "format": "editatlas-project/1", "title": "Convert test",
    "canvas": {"width": 360, "height": 640, "fps": 30},
    "media": {"a": {"kind": "video", "path": "a.mp4"}, "b": {"kind": "video", "path": "b.mp4"},
              "badge": {"kind": "image", "path": "badge.png"}, "tone": {"kind": "audio", "path": "tone.wav", "title": "tone"}},
    "styles": {"caption": {"size": 40}},
    "tracks": [
        {"id": "V1", "kind": "video", "name": "Footage", "clips": [
            {"id": "c1", "media": "a", "in": 0.5, "out": 2.5},                                                  # 0.0-2.0 s
            {"id": "c2", "media": "b", "in": 0.5, "out": 2.5, "speed": 2, "transition": {"type": "dissolve", "dur": 0.4}},  # 2.0-3.0
            {"id": "c3", "media": "a", "in": 3.0, "out": 3.9, "speed": 0.5, "volume": 0.5, "transition": {"type": "black", "dur": 0.2}}]},  # 3.0-4.8
        {"id": "T1", "kind": "text", "name": "Captions", "items": [
            {"id": "cap1", "style": "caption", "text": "first <b>words</b> & more", "at": 0.2, "dur": 1.0},
            {"id": "cap2", "style": "caption", "text": "second", "at": 2.5, "dur": 1.5}]},
        {"id": "G1", "kind": "image", "name": "Badges", "items": [
            {"id": "g1", "media": "badge", "at": 1.0, "dur": 2.0, "x": 0.5, "y": 0.2, "width": 0.3, "label": "badge"}]},
        {"id": "A1", "kind": "audio", "name": "Sounds", "items": [
            {"id": "s1", "media": "tone", "at": 1.0, "in": 0.1, "out": None, "gain_db": -6, "label": "tone"},       # 1.0-2.4 s
            {"id": "s2", "media": "tone", "at": 2.0, "in": 0.0, "out": 0.5, "gain_db": 0, "fade_out": 0.1}]},     # overlaps s1: lane 2
    ],
    "notes": [{"id": "note-1", "at": 3.5, "text": "end on the black dip"}],
}

if not shutil.which("ffmpeg"):
    sys.exit("FFmpeg not found: the build and convert checks need it")

tmp = Path(tempfile.mkdtemp(prefix="project-format-test-"))
try:
    work = tmp / "work"
    make_sources(work)
    (work / "project.json").write_text(json.dumps(SOURCE), encoding="utf-8")
    script = SKILL / "scripts" / "package.py"
    env = {**__import__("os").environ, "EDITATLAS_TELEMETRY": "0"}
    r = subprocess.run([sys.executable, str(script), "build", str(work / "project.json"), "--out", str(tmp / "test.edit"), "--note", "first"],
                       capture_output=True, text=True, env=env)
    check("package.py build makes a folder", r.returncode == 0, r.stdout + r.stderr)
    folder = tmp / "test.edit"
    built = json.loads((folder / "project.json").read_text(encoding="utf-8"))
    v1 = json.loads((folder / "versions" / "v1.json").read_text(encoding="utf-8"))
    check("the project.json package.py writes passes the schema", not errors(built), errors(built)[:5])
    check("its versions/v1.json passes the version schema", not errors(v1, VERSION), errors(v1, VERSION)[:5])
    nxt = copy.deepcopy(built)
    nxt["tracks"][3]["items"][1]["gain_db"] = -3
    (work / "next.json").write_text(json.dumps(nxt), encoding="utf-8")
    r = subprocess.run([sys.executable, str(script), "save", str(work / "next.json"), "--to", str(folder), "--from", "1", "--note", "quieter"],
                       capture_output=True, text=True, env=env)
    v2 = json.loads((folder / "versions" / "v2.json").read_text(encoding="utf-8"))
    check("a version package.py save writes passes the version schema", r.returncode == 0 and not errors(v2, VERSION), r.stderr + str(errors(v2, VERSION)[:5]))
    r = subprocess.run([sys.executable, str(script), "check", str(folder)], capture_output=True, text=True, env=env)
    check("package.py check agrees", r.returncode == 0, r.stdout)

    # ------------------------------------------------------------------ broken projects and versions
    def broken(change):
        p = copy.deepcopy(FULL)
        change(p)
        return p

    def setp(path, value):
        def go(p):
            o = p
            for k in path[:-1]:
                o = o[k]
            if value is DELETE:
                del o[path[-1]]
            else:
                o[path[-1]] = value
        return go

    DELETE = object()
    clip = ("tracks", 0, "clips", 0)
    text = ("tracks", 1, "items", 0)
    pic = ("tracks", 2, "items", 0)
    sound = ("tracks", 4, "items", 0)
    # (what, change, package.py check sees it too)
    CASES = [
        ("another format id", setp(("format",), "editatlas-project/2"), True),
        ("no canvas", setp(("canvas",), DELETE), True),
        ("a canvas width as text", setp(("canvas", "width"), "1080"), True),
        ("a canvas fps of 0", setp(("canvas", "fps"), 0), True),
        ("a media kind the format does not have", setp(("media", "pop", "kind"), "sticker"), True),
        ("media with no path", setp(("media", "pop", "path"), DELETE), True),
        ("a font without its family", setp(("media", "anton", "family"), DELETE), True),
        ("a track kind the format does not have", setp(("tracks", 1, "kind"), "subtitle"), True),
        ("a clip without out", setp(clip + ("out",), DELETE), True),
        ("a clip with in below 0", setp(clip + ("in",), -1), True),
        ("a clip at speed 20", setp(clip + ("speed",), 20), True),
        ("a transition the studio cannot draw", setp(("tracks", 0, "clips", 1, "transition"), {"type": "spin", "dur": 0.5}), True),
        ("a transition of 6 s", setp(("tracks", 0, "clips", 1, "transition"), {"type": "wipe", "dur": 6}), True),
        ("a text item without at", setp(text + ("at",), DELETE), True),
        ("a text item of length 0", setp(text + ("dur",), 0), True),
        ("a key with a field keys do not have", setp(pic + ("keys",), [{"t": 0, "skew": 4}]), True),
        ("a key that moves nothing", setp(pic + ("keys",), [{"t": 0, "ease": "out"}]), True),
        ("an ease the studio does not have", setp(pic + ("keys",), [{"t": 0, "dx": 1, "ease": "bounce"}]), True),
        ("empty keys", setp(pic + ("keys",), []), True),
        ("a volume point without db", setp(("tracks", 4, "items", 1, "gain_keys"), [{"t": 3.0}]), True),
        ("a note of 501 characters", setp(("notes", 0, "text"), "x" * 501), True),
        ("a note without id", setp(("notes", 0, "id"), DELETE), True),
        ("a note at -1 s", setp(("notes", 0, "at"), -1), True),
        ("a sound without media", setp(sound + ("media",), DELETE), True),
        ("an image item without dur", setp(pic + ("dur",), DELETE), True),
        # what only the schema sees
        ("a misspelt field on a text item (durr)", setp(text + ("durr",), 1.0), False),
        ("a dur on a sound (its length is in and out)", setp(sound + ("dur",), 2.0), False),
        ("a text alignment the studio does not have", setp(text + ("align",), "justify"), False),
        ("an appear animation the studio does not have", setp(text + ("in",), {"type": "zoom", "dur": 0.2}), False),
        ("a canvas width of 1080.5", setp(("canvas", "width"), 1080.5), False),
        ("a clip volume of 3", setp(clip + ("volume",), 3), False),
        ("a field on the project that is neither known nor x-", setp(("editor",), "mine"), False),
        ("an opacity of 2", setp(pic + ("opacity",), 2), False),
        ("a style property that does not exist", setp(("styles", "caption", "glow"), True), False),
        ("tracks that are not a list", setp(("tracks",), {"V1": {}}), True),
    ]
    for what, change, both in CASES:
        p = broken(change)
        es = errors(p)
        check(f"broken: {what} fails the schema", bool(es), "")
        if both:
            try:
                pe = pk.check(p)
            except (AttributeError, TypeError, KeyError) as e:     # package.py stops on some shapes instead
                pe = [repr(e)]
            check(f"broken: {what} fails package.py check", bool(pe), "")
    VCASES = [
        ("by a robot", "by", "robot"), ("parent 0", "parent", 0), ("made yesterday", "made", "yesterday"),
        ("version 0", "version", 0), ("a note of 501 characters", "note", "x" * 501), ("no project", "project", DELETE),
        ("a project with another format", "project", {"format": "x"}),
    ]
    for what, k, value in VCASES:
        v = copy.deepcopy(v1)
        if value is DELETE:
            del v[k]
        else:
            v[k] = value
        check(f"broken version: {what} fails the schema", bool(errors(v, VERSION)), "")

    # ------------------------------------------------------------------ converters
    conv = SKILL / "scripts" / "convert.py"
    out = tmp / "out"
    runs = {}
    for to, name in (("otio", "test.otio"), ("xml", "test.xml")):
        r = subprocess.run([sys.executable, str(conv), to, str(folder), "--out", str(out / name)], capture_output=True, text=True, encoding="utf-8")
        runs[to] = r
        check(f"convert.py {to} runs", r.returncode == 0, r.stdout + r.stderr)
        print("   ", r.stdout.strip().replace("\n", "\n    "))
    # what the project says, in frames at 30 fps: (timeline start, end, source in) and speed
    want_clips = {"c1": (0, 60, 15, 1), "c2": (60, 90, 15, 2), "c3": (90, 144, 90, 0.5)}
    otio = json.loads((out / "test.otio").read_text(encoding="utf-8"))
    check("the .otio is a Timeline with the project's title", otio.get("OTIO_SCHEMA") == "Timeline.1" and otio["name"] == "Convert test")
    tracks = otio["tracks"]["children"]
    footage = next(t for t in tracks if t["name"] == "Footage")

    def otio_ranges(track):
        at, got = 0, {}
        for ch in track["children"]:
            if ch["OTIO_SCHEMA"].startswith("Transition"):
                continue
            d = int(ch["source_range"]["duration"]["value"])
            if ch["OTIO_SCHEMA"].startswith("Clip"):
                warp = [e["time_scalar"] for e in ch["effects"] if e["OTIO_SCHEMA"].startswith("LinearTimeWarp")]
                got[ch["name"]] = (at, at + d, int(ch["source_range"]["start_time"]["value"]), warp[0] if warp else 1)
            at += d
        return got

    check("OTIO: each clip at its frames, from its source frame, at its speed", otio_ranges(footage) == want_clips, str(otio_ranges(footage)))
    trans = [ch for ch in footage["children"] if ch["OTIO_SCHEMA"].startswith("Transition")]
    check("OTIO: the dissolve is a SMPTE_Dissolve of 6 + 6 frames, the dip a named Custom_Transition",
          [(t["transition_type"], t["in_offset"]["value"], t["out_offset"]["value"]) for t in trans] == [("SMPTE_Dissolve", 6, 6), ("Custom_Transition", 3, 3)],
          str([(t["transition_type"], t["in_offset"]["value"]) for t in trans]))
    sound_lanes = [t for t in tracks if t["kind"] == "Audio" and t["name"] == "Sounds"]
    check("OTIO: overlapping sounds go on two lanes, at their frames", [otio_ranges(t) for t in sound_lanes] == [{"tone": (30, 72, 3, 1)}, {"s2": (60, 75, 0, 1)}],
          str([otio_ranges(t) for t in sound_lanes]))
    fs = next((t for t in tracks if t["name"] == "Footage sound"), None)
    check("OTIO: the footage's own sound follows the clips that have sound (c1, c3; b.mp4 has none)",
          fs is not None and otio_ranges(fs) == {k: v for k, v in want_clips.items() if k != "c2"}, str(fs and otio_ranges(fs)))
    marks = otio["tracks"]["markers"]
    check("OTIO: text and notes are markers at their frames, the text as written",
          [(m["name"], m["marked_range"]["start_time"]["value"], m["marked_range"]["duration"]["value"]) for m in marks]
          == [("first <b>words</b> & more", 6, 30), ("second", 75, 45), ("Note: end on the black dip", 105, 0)], str([(m["name"], m["marked_range"]["start_time"]["value"]) for m in marks]))
    check("OTIO: each element is kept as it was under metadata editatlas",
          footage["children"][0]["metadata"]["editatlas"]["element"]["id"] == "c1" and marks[0]["metadata"]["editatlas"]["text"]["style"] == "caption")
    urls = [ch["media_references"]["DEFAULT_MEDIA"]["target_url"] for t in tracks for ch in t["children"] if ch["OTIO_SCHEMA"].startswith("Clip")]
    check("OTIO: media are absolute file URLs into the folder", all(u.startswith("file:///") and "/test.edit/media/" in u for u in urls), str(urls[:2]))
    check("convert.py says what it could not carry over", "not carried over: text looks" in runs["otio"].stdout and "fades" in runs["otio"].stdout)

    x = ET.parse(out / "test.xml").getroot()
    check("FCP7 XML: xmeml version 4 with one sequence at 30 fps, 360x640",
          x.tag == "xmeml" and x.get("version") == "4" and x.findtext("sequence/rate/timebase") == "30" and x.findtext("sequence/rate/ntsc") == "FALSE"
          and x.findtext("sequence/media/video/format/samplecharacteristics/width") == "360")
    vtracks = x.findall("sequence/media/video/track")
    atracks = x.findall("sequence/media/audio/track")

    def xml_clips(track):
        got = {}
        for ci in track.findall("clipitem"):
            sp = ci.find("filter/effect[effectid='timeremap']/parameter[parameterid='speed']/value")
            got[ci.findtext("name")] = [int(ci.findtext(k)) for k in ("start", "end", "in", "out")] + [float(sp.text) / 100 if sp is not None else 1]
        return got

    v = xml_clips(vtracks[0])
    # FCP7: in/out of a clip with a speed change are in its new timing (source frame / speed); a transition makes the
    # edges at the cut -1 and widens in/out by its frames
    check("FCP7 XML: clips at their frames, in/out in each clip's timing, the speed as Time Remap",
          v == {"c1": [0, -1, 15, 81, 1], "c2": [-1, -1, 2, 41, 2], "c3": [-1, 144, 177, 234, 0.5]}, str(v))
    ti = vtracks[0].findall("transitionitem")
    check("FCP7 XML: a Cross Dissolve centred on the first cut and a Dip to Color Dissolve (black) on the second",
          [(t.findtext("effect/name"), t.findtext("start"), t.findtext("end")) for t in ti] == [("Cross Dissolve", "54", "66"), ("Dip to Color Dissolve", "87", "93")]
          and ti[1].findtext("effect/parameter/value/red") == "0", str([(t.findtext("effect/name"), t.findtext("start")) for t in ti]))
    check("FCP7 XML: the picture on its own video track", len(vtracks) == 2 and xml_clips(vtracks[1]) == {"badge": [30, 90, 0, 60, 1]}, str(xml_clips(vtracks[1]) if len(vtracks) > 1 else vtracks))
    a = [xml_clips(t) for t in atracks]
    check("FCP7 XML: footage sound for c1 and c3, then the two sound lanes", len(a) == 3 and a[0] == {"c1": [0, 60, 15, 75, 1], "c3": [90, 144, 180, 234, 0.5]} and a[1] == {"tone": [30, 72, 3, 45, 1]} and a[2] == {"s2": [60, 75, 0, 15, 1]}, str(a))
    lv = atracks[1].find("clipitem/filter/effect[effectid='audiolevels']/parameter/value")
    c3l = atracks[0].find("clipitem[name='c3']/filter/effect[effectid='audiolevels']/parameter/value")
    check("FCP7 XML: -6 dB is level 0.50119, a clip at volume 0.5 is 0.5", lv is not None and lv.text == "0.50119" and c3l is not None and c3l.text == "0.50000",
          f"{lv is not None and lv.text} {c3l is not None and c3l.text}")
    vc1 = vtracks[0].find("clipitem[name='c1']")
    check("FCP7 XML: a clip's picture and its sound are linked", [lk.findtext("linkclipref") for lk in vc1.findall("link")] == ["v-c1", "a-c1"])
    check("FCP7 XML: text and notes are sequence markers; a note is a point (out -1)",
          [(m.findtext("name"), m.findtext("in"), m.findtext("out")) for m in x.findall("sequence/marker")]
          == [("first <b>words</b> & more", "6", "36"), ("second", "75", "120"), ("Note: end on the black dip", "105", "-1")])
    check("FCP7 XML: each file is written once, then referred to by id",
          len([f for f in x.iter("file") if f.find("pathurl") is not None]) == 4 and all(f.findtext("pathurl", "file://localhost/").startswith("file://localhost/") for f in x.iter("file")))

    # A project with no transitions room and a pasted project with no durations measured.
    p2 = json.loads(json.dumps(SOURCE))
    p2["tracks"][0]["clips"][1]["in"] = 0.0                          # nothing before c2's in: no room for the dissolve
    p2["tracks"][0]["clips"][1]["out"] = 2.0
    for m in p2["media"].values():
        m["path"] = str((work / m["path"]).resolve())
    (work / "pasted.json").write_text(json.dumps(p2), encoding="utf-8")
    r = subprocess.run([sys.executable, str(conv), "xml", str(work / "pasted.json"), "--out", str(out / "pasted.xml")], capture_output=True, text=True, encoding="utf-8")
    check("a transition without footage around its cut becomes a plain cut, and says so", r.returncode == 0 and "transition into c2: no footage around the cut" in r.stdout, r.stdout + r.stderr)
    r = subprocess.run([sys.executable, str(conv), "otio", str(work / "pasted.json"), "--out", str(out / "rel" / "pasted.otio"), "--relative"], capture_output=True, text=True, encoding="utf-8")
    rel = json.loads((out / "rel" / "pasted.otio").read_text(encoding="utf-8")) if r.returncode == 0 else {}
    first = rel.get("tracks", {}).get("children", [{}])[0].get("children", [{}])[0]
    check("--relative writes media paths relative to the output file", first.get("media_references", {}).get("DEFAULT_MEDIA", {}).get("target_url") == "../../work/a.mp4", r.stdout + r.stderr + str(first)[:200])
    bad = copy.deepcopy(SOURCE)
    bad["tracks"][0]["clips"][0]["out"] = 0.1
    (work / "bad.json").write_text(json.dumps(bad), encoding="utf-8")
    r = subprocess.run([sys.executable, str(conv), "xml", str(work / "bad.json"), "--out", str(out / "bad.xml")], capture_output=True, text=True, encoding="utf-8")
    check("a broken project is refused with package.py's reasons, and nothing is written", r.returncode != 0 and "needs 0 <= in < out" in r.stderr and not (out / "bad.xml").exists(), r.stderr)

    # ------------------------------------------------------------------ read back with OpenTimelineIO, when installed
    try:
        import opentimelineio as otio_lib
    except ImportError:
        otio_lib = None
        print("SKIP OpenTimelineIO is not installed: pip install opentimelineio otio-fcp-adapter")
    if otio_lib:
        tl = otio_lib.adapters.read_from_file(str(out / "test.otio"))
        vt = tl.video_tracks()[0]

        def placed(track):
            got = {}
            for i, ch in enumerate(track):
                if isinstance(ch, otio_lib.schema.Clip):
                    r_ = track.range_of_child_at_index(i)
                    got[ch.name] = (round(r_.start_time.value), round(r_.end_time_exclusive().value), round(ch.source_range.start_time.value))
            return got

        check("OpenTimelineIO reads the .otio: clips at the same frames", placed(vt) == {k: v[:3] for k, v in want_clips.items()}, str(placed(vt)))
        check("OpenTimelineIO: the timeline lasts 144 frames (4.8 s)", round(tl.duration().value) == 144 and tl.duration().rate == 30, str(tl.duration()))
        check("OpenTimelineIO: 3 markers on the stack", [m.name for m in tl.tracks.markers] == ["first <b>words</b> & more", "second", "Note: end on the black dip"])
        again = json.loads(otio_lib.adapters.write_to_string(tl, "otio_json"))
        check("OpenTimelineIO writes it back with the same tracks and clips", [len(t["children"]) for t in again["tracks"]["children"]] == [len(t["children"]) for t in otio["tracks"]["children"]])
        try:
            xtl = otio_lib.adapters.read_from_file(str(out / "test.xml"), adapter_name="fcp_xml")
        except Exception as e:  # noqa: BLE001 - the adapter is optional
            xtl = None
            print("SKIP the FCP XML adapter is not installed:", str(e)[:120])
        if xtl is not None:
            xv = xtl.video_tracks()[0]
            got = placed(xv)
            # the adapter reads in/out as they are, so c2 and c3 come back in their own (retimed) frames
            check("the FCP XML adapter reads the XML: the same clips at the same timeline frames",
                  {k: v[:2] for k, v in got.items()} == {k: v[:2] for k, v in want_clips.items()}, str(got))
            check("the FCP XML adapter: c1's source frame is 15, c2's and c3's are in their retimed timing (8, 180)",
                  {k: v[2] for k, v in got.items()} == {"c1": 15, "c2": 8, "c3": 180}, str(got))
            check("the FCP XML adapter: two transitions on the footage", len([c for c in xv if isinstance(c, otio_lib.schema.Transition)]) == 2)
            check("the FCP XML adapter: the same 3 markers at the same frames",
                  [(m.name, round(m.marked_range.start_time.value)) for m in xtl.tracks.markers] == [("first <b>words</b> & more", 6), ("second", 75), ("Note: end on the black dip", 105)],
                  str([(m.name, m.marked_range.start_time.value) for m in xtl.tracks.markers]))
            check("the FCP XML adapter: one picture track and three sound tracks", len(xtl.video_tracks()) == 2 and len(xtl.audio_tracks()) == 3)
            check("the FCP XML adapter: the timeline lasts 144 frames", round(xtl.duration().value) == 144, str(xtl.duration()))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n{len(failures)} failed" if failures else "\nall passed")
sys.exit(1 if failures else 0)
