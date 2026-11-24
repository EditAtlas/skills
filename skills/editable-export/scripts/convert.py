"""Export an EditAtlas project (editatlas-project/1) to a timeline that editing apps import. Standard library only.

  convert.py otio result/NAME.edit --out result/NAME.otio   # OpenTimelineIO (.otio)
  convert.py xml  result/NAME.edit --out result/NAME.xml    # Final Cut Pro 7 XML (xmeml 4): Premiere Pro, DaVinci Resolve

The input is a package folder (its project.json), a project.json, or a versions/v<n>.json. Media paths become
absolute file URLs, because editing apps look for the files by their full path; --relative keeps them relative to
the output file (move the output next to the folder, or the app asks where the files are).

What comes across: the footage clips in order (source in/out, speed, the footage's own sound and its volume), each
sound and music item (file in/out, level), pictures (timing only), and text and notes as markers. A dissolve, and in
XML a dip to black or white, becomes a transition. Everything else is printed as lost: text looks and positions,
picture position, size and animation, framing (fit, x, y, scale, zoom_to), fades and volume lines, keys, slide and
wipe. The .otio file also keeps each element as it was under metadata "editatlas", so a tool that reads OTIO can
recover what the timeline cannot show.

Times are frames at canvas.fps (30 when it is missing); every edge is rounded to the nearest frame from the time in
seconds, so rounding never adds up along the timeline.
"""
import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # also under python -I
import package as pk  # noqa: E402

STILL_FRAMES = 10 * 60 * 60  # what a still image "lasts" in an editing app: long enough for any item


def die(msg):
    sys.exit("convert: " + msg)


def load(src):
    """(project, folder its media paths are relative to)."""
    s = Path(src)
    f = s / "project.json" if s.is_dir() else s
    if not f.is_file():
        die(f"no project.json at {s}" if s.is_dir() else f"no such file: {s}")
    try:
        obj = json.loads(f.read_text(encoding="utf-8"))
    except ValueError as e:
        die(f"{f} is not JSON: {e}")
    if isinstance(obj, dict) and obj.get("format") == pk.VERSION_FORMAT:
        obj = obj.get("project")
    if not isinstance(obj, dict):
        die(f"{f} holds no project")
    p = json.loads(json.dumps(obj))
    p.setdefault("canvas", {}).setdefault("fps", 30)   # readers use 30 when it is missing
    errs = pk.check(p)
    if errs:
        die(f"{f} is not a project this can convert:\n  " + "\n  ".join(errs[:20]))
    return p, f.parent


# ------------------------------------------------------------------ the timeline, in frames
class Plan:
    """The project as an editing app sees it: tracks of clips placed in whole frames, markers, and what is lost."""

    def __init__(self, p, base, out_dir, relative):
        self.p, self.base, self.out_dir, self.relative = p, Path(base).resolve(), Path(out_dir).resolve(), relative
        self.fps = float(p["canvas"]["fps"])
        self.title = p.get("title") or "EditAtlas project"
        self.media = p.get("media") or {}
        self.lost, self.counts = [], {}
        self.video, self.footage_sound, self.pictures, self.sounds, self.markers = [], [], [], [], []
        self._plan()

    def f(self, seconds):
        return int(round(seconds * self.fps + 1e-9))

    def lose(self, what):
        if what not in self.lost:
            self.lost.append(what)

    def url(self, mid):
        path = Path(self.media[mid]["path"])
        full = path if path.is_absolute() else (self.base / path)
        full = full.resolve()
        if self.relative:
            try:
                return Path(os.path.relpath(full, self.out_dir)).as_posix()
            except ValueError:
                pass
        return full.as_uri()

    def duration_of(self, mid):
        """Seconds of a media file: media.duration, else ffprobe, else None."""
        m = self.media.get(mid) or {}
        if isinstance(m.get("duration"), (int, float)) and m["duration"] > 0:
            return float(m["duration"])
        path = Path(m.get("path", ""))
        full = path if path.is_absolute() else self.base / path
        if shutil.which("ffprobe") and full.is_file():
            r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(full)],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            try:
                d = float(json.loads(r.stdout)["format"]["duration"])
                m["duration"] = d
                return d
            except (ValueError, KeyError, TypeError):
                return None
        return None

    def _plan(self):
        p = self.p
        tracks = p.get("tracks") or []
        # footage: clips back to back from 0
        vt = next((t for t in tracks if t["kind"] == "video"), None)
        t = 0.0
        prev = None
        for c in (vt or {}).get("clips") or []:
            speed = float(c.get("speed") or 1)
            length = (c["out"] - c["in"]) / speed
            row = {"id": c["id"], "media": c["media"], "start": self.f(t), "end": self.f(t + length), "speed": speed,
                   "src_in": float(c["in"]), "src_out": float(c["out"]), "volume": float(c.get("volume", 1)),
                   "enabled": not (vt.get("hidden")), "item": c, "transition": None}
            t += length
            if row["end"] <= row["start"]:
                self.lose(f"clip {c['id']} is shorter than one frame at {self.fps:g} fps; left out")
                continue
            tr = c.get("transition")
            if tr and prev is not None:
                row["transition"] = {"type": tr["type"], "dur": float(tr.get("dur", 0.5))}
            for k, default in (("fit", "cover"), ("x", 0.5), ("y", 0.5), ("scale", 1)):
                if c.get(k, default) != default:
                    self.lose("framing of clips (fit, x, y, scale)")
            if c.get("zoom_to") is not None:
                self.lose("slow zooms (zoom_to)")
            self.video.append(row)
            prev = row
            m = self.media.get(c["media"]) or {}
            if m.get("has_audio") is not False:
                # the footage's own sound cuts at every cut, transition or not (as in the studio)
                self.footage_sound.append(dict(row, transition=None, enabled=not vt.get("muted") and row["volume"] > 0))
        self.counts["clips"] = len(self.video)
        # pictures: one lane per run of items that do not overlap
        for tr in tracks:
            if tr["kind"] != "image":
                continue
            items = sorted(tr.get("items") or [], key=lambda x: x["at"])
            rows = [(self.f(x["at"]), self.f(x["at"] + x["dur"]), x) for x in items]
            for r in rows:
                if r[1] <= r[0]:
                    self.lose(f"picture {r[2]['id']} is shorter than one frame at {self.fps:g} fps; left out")
            for lane in lanes([r for r in rows if r[1] > r[0]]):
                self.pictures.append({"track": tr, "enabled": not tr.get("hidden"), "items": lane})
            for x in items:
                if any(k in x for k in ("x", "y", "width", "rotation", "opacity", "keys", "parent")):
                    self.lose("picture position, size and motion (x, y, width, rotation, opacity, keys, cards)")
                if x.get("in") or x.get("out"):
                    self.lose("how pictures appear and leave (in, out)")
                if str(self.media.get(x["media"], {}).get("path", "")).lower().endswith((".webp", ".gif", ".apng", ".svg")):
                    self.lose("animated WebP, GIF, APNG and SVG pictures (most editing apps cannot read them)")
        self.counts["pictures"] = sum(len(x["items"]) for x in self.pictures)
        # sounds: one lane per run of items that do not overlap, in track order
        for tr in tracks:
            if tr["kind"] != "audio":
                continue
            rows = []
            for x in tr.get("items") or []:
                a = float(x.get("in") or 0)
                b = x.get("out")
                if b is None:
                    d = self.duration_of(x["media"])
                    if d is None:
                        die(f"sound {x['id']}: out is null and the length of {x['media']} is unknown: it has no duration, "
                            f"and {self.media.get(x['media'], {}).get('path')} cannot be read with ffprobe")
                    b = d
                b = float(b)
                if b <= a:
                    self.lose(f"sound {x['id']} has no length (out <= in); left out")
                    continue
                start = self.f(x["at"])
                rows.append((start, start + max(1, self.f(b - a)), dict(x, _in=a, _out=b)))
                if x.get("fade_in") or x.get("fade_out"):
                    self.lose("sound fades (fade_in, fade_out)")
                if x.get("gain_keys"):
                    self.lose("volume lines (gain_keys)")
            for lane in lanes(sorted(rows, key=lambda r: r[0])):
                self.sounds.append({"track": tr, "enabled": not tr.get("muted"), "items": lane})
        self.counts["sounds"] = sum(len(x["items"]) for x in self.sounds)
        # text and notes: markers
        n = 0
        for tr in tracks:
            if tr["kind"] != "text":
                continue
            for x in tr.get("items") or []:
                self.markers.append({"name": str(x.get("text", "")), "comment": f"text {x['id']}" + (f", style {x['style']}" if x.get("style") else ""),
                                     "start": self.f(x["at"]), "dur": max(1, self.f(x["at"] + x["dur"]) - self.f(x["at"])),
                                     "color": "GREEN", "item": x, "kind": "text"})
                n += 1
        if n:
            self.lose("text looks, positions and animation: text comes across as markers with its words and timing")
        self.counts["text"] = n
        for note in p.get("notes") or []:
            self.markers.append({"name": "Note: " + str(note.get("text", "")), "comment": f"note {note['id']}",
                                 "start": self.f(note["at"]), "dur": 0, "color": "RED", "item": note, "kind": "note"})
        self.counts["notes"] = len(p.get("notes") or [])
        self.markers.sort(key=lambda m: m["start"])
        self.end = max([r["end"] for r in self.video] + [r[1] for g in self.pictures + self.sounds for r in g["items"]]
                       + [m["start"] + m["dur"] for m in self.markers] + [0])

    def transition_frames(self, a, b):
        """Frames on each side of the cut between clips a and b that a centred transition of b can use (0: none)."""
        tr = b["transition"]
        half = self.f(tr["dur"]) // 2
        # an editing app needs footage past a's out and before b's in; the studio holds a frame instead
        after_a = self.duration_of(a["media"])
        room_a = half if after_a is None else int((after_a - a["src_out"]) * self.fps / a["speed"])
        room_b = int(b["src_in"] * self.fps / b["speed"])
        return max(0, min(half, room_a, room_b))


def lanes(rows):
    """Rows (start, end, item) in start order -> lists of rows that do not overlap, first lane first."""
    out, ends = [], []
    for r in rows:
        for i, e in enumerate(ends):
            if e <= r[0]:
                out[i].append(r)
                ends[i] = r[1]
                break
        else:
            out.append([r])
            ends.append(r[1])
    return out


def db_to_level(db):
    return min(3.98109, 10 ** (db / 20))   # FCP7's Audio Levels: 1 = 0 dB, at most +12 dB


# ------------------------------------------------------------------ OpenTimelineIO
def to_otio(plan):
    rate = plan.fps
    if abs(rate - 30000 / 1001) < 0.005:
        rate = 30000 / 1001
    elif abs(rate - 24000 / 1001) < 0.005:
        rate = 24000 / 1001
    elif abs(rate - 60000 / 1001) < 0.005:
        rate = 60000 / 1001

    def rt(v):
        return {"OTIO_SCHEMA": "RationalTime.1", "rate": rate, "value": float(v)}

    def trange(start, dur):
        return {"OTIO_SCHEMA": "TimeRange.1", "duration": rt(dur), "start_time": rt(start)}

    def ref(mid):
        m = plan.media.get(mid) or {}
        d = plan.duration_of(mid) if m.get("kind") in ("video", "audio") else None
        return {"OTIO_SCHEMA": "ExternalReference.1", "metadata": {"editatlas": {"media": mid, **m}},
                "name": Path(m.get("path", mid)).name,
                "available_range": trange(0, plan.f(d)) if d else None, "available_image_bounds": None,
                "target_url": plan.url(mid)}

    def clip(name, mid, start, dur, meta, enabled=True, effects=()):
        return {"OTIO_SCHEMA": "Clip.2", "metadata": {"editatlas": meta}, "name": name,
                "source_range": trange(start, dur), "effects": list(effects), "markers": [], "enabled": enabled,
                "media_references": {"DEFAULT_MEDIA": ref(mid)}, "active_media_reference_key": "DEFAULT_MEDIA"}

    def gap(dur):
        return {"OTIO_SCHEMA": "Gap.1", "metadata": {}, "name": "", "source_range": trange(0, dur), "effects": [],
                "markers": [], "enabled": True}

    def track(name, kind, children, enabled=True, meta=None):
        return {"OTIO_SCHEMA": "Track.1", "metadata": {"editatlas": meta or {}}, "name": name, "source_range": None,
                "effects": [], "markers": [], "enabled": enabled, "children": children, "kind": kind}

    def warp(speed):
        return [] if speed == 1 else [{"OTIO_SCHEMA": "LinearTimeWarp.1", "metadata": {}, "name": "speed",
                                        "effect_name": "LinearTimeWarp", "time_scalar": speed}]

    def footage(rows):
        children = []
        for i, r in enumerate(rows):
            if r["transition"] and i:
                h = plan.transition_frames(rows[i - 1], r)
                if h:
                    typ = r["transition"]["type"]
                    children.append({"OTIO_SCHEMA": "Transition.1", "metadata": {"editatlas": r["transition"]},
                                     "name": typ, "in_offset": rt(h), "out_offset": rt(h),
                                     "transition_type": "SMPTE_Dissolve" if typ == "dissolve" else "Custom_Transition"})
                    if typ != "dissolve":
                        plan.lose(f"{typ} transitions are Custom_Transition in OTIO (named, not drawn)")
                else:
                    plan.lose(f"transition into {r['id']}: no footage around the cut for it; a plain cut")
            meta = {"element": r["item"], "speed": r["speed"], "volume": r["volume"]}
            # source_range starts at the source time where the clip starts; its duration is its length on the
            # timeline, and LinearTimeWarp.time_scalar is the speed: the source used is duration x speed.
            children.append(clip(r["id"], r["media"], plan.f(r["src_in"]), r["end"] - r["start"], meta, r["enabled"],
                                 warp(r["speed"])))
        return children

    def placed(rows, mk):
        children, at = [], 0
        for start, end, x in rows:
            if start > at:
                children.append(gap(start - at))
            children.append(mk(start, end, x))
            at = end
        return children

    tracks = []
    if plan.video:
        tracks.append(track("Footage", "Video", footage(plan.video)))
    for g in plan.pictures:
        tracks.append(track(g["track"].get("name") or g["track"]["id"], "Video",
                            placed(g["items"], lambda s, e, x: clip(x.get("label") or x["id"], x["media"], plan.f(x.get("from") or 0), e - s, {"element": x})),
                            g["enabled"], {"track": g["track"]["id"]}))
    if plan.footage_sound:
        tracks.append(track("Footage sound", "Audio", placed([(r["start"], r["end"], r) for r in plan.footage_sound], lambda s, e, r: clip(
            r["id"], r["media"], plan.f(r["src_in"]), e - s, {"element": r["item"], "speed": r["speed"], "volume": r["volume"]},
            r["enabled"], warp(r["speed"])))))
    for g in plan.sounds:
        tracks.append(track(g["track"].get("name") or g["track"]["id"], "Audio",
                            placed(g["items"], lambda s, e, x: clip(x.get("label") or x["id"], x["media"], plan.f(x["_in"]), e - s,
                                                                   {"element": {k: v for k, v in x.items() if not k.startswith("_")}})),
                            g["enabled"], {"track": g["track"]["id"]}))
    if plan.sounds or plan.footage_sound:
        plan.lose("sound levels: OTIO has no standard volume, so gain_db and clip volume are in metadata only")
    markers = [{"OTIO_SCHEMA": "Marker.2", "metadata": {"editatlas": {m["kind"]: m["item"]}}, "name": m["name"],
                "color": m["color"], "marked_range": trange(m["start"], m["dur"]), "comment": m["comment"]}
               for m in plan.markers]
    p = plan.p
    return {"OTIO_SCHEMA": "Timeline.1",
            "metadata": {"editatlas": {"format": p["format"], "title": p.get("title"), "canvas": p["canvas"],
                                       "styles": p.get("styles") or {}}},
            "name": plan.title, "global_start_time": None,
            "tracks": {"OTIO_SCHEMA": "Stack.1", "metadata": {}, "name": "tracks", "source_range": None, "effects": [],
                       "markers": markers, "enabled": True, "children": tracks}}


# ------------------------------------------------------------------ Final Cut Pro 7 XML (xmeml)
def sub(parent, tag, text=None, **attrib):
    e = ET.SubElement(parent, tag, {k: str(v) for k, v in attrib.items()})
    if text is not None:
        e.text = str(text)
    return e


def to_xml(plan):
    timebase = max(1, int(math.ceil(plan.fps - 1e-6)))
    ntsc = abs(plan.fps - timebase * 1000 / 1001) < 0.005
    if not ntsc and abs(plan.fps - timebase) > 1e-6:
        timebase = max(1, int(round(plan.fps)))
        plan.lose(f"a frame rate of {plan.fps:g} fps: FCP7 XML has whole rates (and NTSC), so it is {timebase} fps")

    def rate(parent):
        r = sub(parent, "rate")
        sub(r, "timebase", timebase)
        sub(r, "ntsc", "TRUE" if ntsc else "FALSE")
        return r

    files = {}

    def file_el(parent, mid):
        m = plan.media.get(mid) or {}
        if mid in files:
            return sub(parent, "file", id=files[mid])
        files[mid] = f"file-{len(files) + 1}"
        f = sub(parent, "file", id=files[mid])
        sub(f, "name", Path(m.get("path", mid)).name)
        url = plan.url(mid)
        sub(f, "pathurl", url.replace("file:///", "file://localhost/", 1) if url.startswith("file:///") else url)
        rate(f)
        d = plan.duration_of(mid) if m.get("kind") in ("video", "audio") else None
        sub(f, "duration", plan.f(d) if d else STILL_FRAMES)
        med = sub(f, "media")
        if m.get("kind") in ("video", "image"):
            v = sub(med, "video")
            sc = sub(v, "samplecharacteristics")
            if m.get("width") and m.get("height"):
                sub(sc, "width", m["width"])
                sub(sc, "height", m["height"])
        if m.get("kind") == "audio" or (m.get("kind") == "video" and m.get("has_audio") is not False):
            sub(med, "audio")
        return f

    ids = {"n": 0}

    def new_id(kind):
        ids["n"] += 1
        return f"{kind}-{ids['n']}"

    def level(parent, db):
        fl = sub(parent, "filter")
        ef = sub(fl, "effect")
        sub(ef, "name", "Audio Levels")
        sub(ef, "effectid", "audiolevels")
        sub(ef, "effectcategory", "audiolevels")
        sub(ef, "effecttype", "audiolevels")
        sub(ef, "mediatype", "audio")
        pa = sub(ef, "parameter")
        sub(pa, "parameterid", "level")
        sub(pa, "name", "Level")
        sub(pa, "valuemin", 0)
        sub(pa, "valuemax", 3.98109)
        sub(pa, "value", f"{db_to_level(db):.5f}")

    def timeremap(parent, speed):
        fl = sub(parent, "filter")
        ef = sub(fl, "effect")
        sub(ef, "name", "Time Remap")
        sub(ef, "effectid", "timeremap")
        sub(ef, "effectcategory", "motion")
        sub(ef, "effecttype", "motion")
        sub(ef, "mediatype", "video")
        for pid, value in (("variablespeed", 0), ("speed", f"{speed * 100:g}"), ("reverse", "FALSE"), ("frameblending", "FALSE")):
            pa = sub(ef, "parameter")
            sub(pa, "parameterid", pid)
            sub(pa, "name", pid)
            sub(pa, "value", value)

    def item(track_e, name, mid, start, end, src_in, speed=1.0, enabled=True, edges=(0, 0), file_frames=None, cid=None):
        """A clipitem. FCP7 gives in/out of a clip with a speed change in its new timing (source frames / speed),
        so out - in = end - start. edges: frames of a transition on each side (start/end -1, in/out widened)."""
        ci = sub(track_e, "clipitem", id=cid or new_id("clipitem"))
        sub(ci, "name", name)
        sub(ci, "enabled", "TRUE" if enabled else "FALSE")
        sub(ci, "duration", file_frames if file_frames is not None else STILL_FRAMES)
        rate(ci)
        a = int(round(src_in * plan.fps / speed))
        sub(ci, "start", -1 if edges[0] else start)
        sub(ci, "end", -1 if edges[1] else end)
        sub(ci, "in", a - edges[0])
        sub(ci, "out", a + (end - start) + edges[1])
        file_el(ci, mid)
        return ci

    root = ET.Element("xmeml", version="4")
    seq = sub(root, "sequence", id="sequence-1")
    sub(seq, "name", plan.title)
    sub(seq, "duration", plan.end)
    rate(seq)
    tc = sub(seq, "timecode")
    rate(tc)
    sub(tc, "string", "00:00:00:00")
    sub(tc, "frame", 0)
    sub(tc, "displayformat", "NDF")
    media = sub(seq, "media")
    video = sub(media, "video")
    fmt = sub(sub(video, "format"), "samplecharacteristics")
    rate(fmt)
    sub(fmt, "width", plan.p["canvas"]["width"])
    sub(fmt, "height", plan.p["canvas"]["height"])
    sub(fmt, "pixelaspectratio", "square")
    sub(fmt, "fielddominance", "none")

    def footage(track_e, rows, audio):
        edges = []
        for i, r in enumerate(rows):
            h = plan.transition_frames(rows[i - 1], r) if (r["transition"] and i) else 0
            typ = r["transition"]["type"] if r["transition"] else None
            if r["transition"] and i and (not h or typ in ("slide", "wipe")):
                plan.lose(f"{typ} transitions (a plain cut in FCP7 XML)" if h else f"transition into {r['id']}: no footage around the cut for it; a plain cut")
                h = 0
            edges.append(h)
        out = []
        for i, r in enumerate(rows):
            left, right = edges[i], (edges[i + 1] if i + 1 < len(rows) else 0)
            if left:
                ti = sub(track_e, "transitionitem")
                sub(ti, "start", r["start"] - left)
                sub(ti, "end", r["start"] + left)
                sub(ti, "alignment", "center")
                rate(ti)
                ef = sub(ti, "effect")
                typ = r["transition"]["type"]
                name = "Cross Dissolve" if typ == "dissolve" else "Dip to Color Dissolve"
                sub(ef, "name", name)
                sub(ef, "effectid", name)
                sub(ef, "effectcategory", "Dissolve")
                sub(ef, "effecttype", "transition")
                sub(ef, "mediatype", "audio" if audio else "video")
                if typ in ("black", "white"):
                    pa = sub(ef, "parameter")
                    sub(pa, "parameterid", "color")
                    sub(pa, "name", "Color")
                    v = sub(pa, "value")
                    for k, x in (("alpha", 255), ("red", 255 if typ == "white" else 0), ("green", 255 if typ == "white" else 0), ("blue", 255 if typ == "white" else 0)):
                        sub(v, k, x)
            d = plan.duration_of(r["media"])
            ff = int(round(d * plan.fps / r["speed"])) if d else None
            cid = ("a-" if audio else "v-") + r["id"]
            ci = item(track_e, r["id"], r["media"], r["start"], r["end"], r["src_in"], r["speed"], r["enabled"], (left, right), ff, cid)
            if audio:
                st = sub(ci, "sourcetrack")
                sub(st, "mediatype", "audio")
                sub(st, "trackindex", 1)
                if r["volume"] != 1:
                    level(ci, 20 * math.log10(max(1e-5, r["volume"])))
            if r["speed"] != 1:
                timeremap(ci, r["speed"])
            out.append((ci, r))
        return out

    vclips = []
    if plan.video:
        vclips = footage(sub(video, "track"), plan.video, False)
    for g in plan.pictures:
        tr = sub(video, "track")
        for start, end, x in g["items"]:
            item(tr, x.get("label") or x["id"], x["media"], start, end, float(x.get("from") or 0), enabled=g["enabled"])
    audio_e = sub(media, "audio")
    sub(audio_e, "numOutputChannels", 2)
    afmt = sub(sub(audio_e, "format"), "samplecharacteristics")
    sub(afmt, "depth", 16)
    sub(afmt, "samplerate", 48000)
    if plan.footage_sound:
        aclips = footage(sub(audio_e, "track"), plan.footage_sound, True)
        # each clip's picture and its own sound move together
        by_id = {r["id"]: (k, ci) for k, (ci, r) in enumerate(aclips, 1)}
        for n, (ci, r) in enumerate(vclips, 1):
            pair = ((ci, "video", n), (by_id[r["id"]][1], "audio", by_id[r["id"]][0])) if r["id"] in by_id else ()
            for el, _, _ in pair:
                for target, kind, index in pair:
                    lk = sub(el, "link")
                    sub(lk, "linkclipref", target.get("id"))
                    sub(lk, "mediatype", kind)
                    sub(lk, "trackindex", 1)
                    sub(lk, "clipindex", index)
    for g in plan.sounds:
        tr = sub(audio_e, "track")
        if not g["enabled"]:
            sub(tr, "enabled", "FALSE")
        for start, end, x in g["items"]:
            d = plan.duration_of(x["media"])
            ci = item(tr, x.get("label") or x["id"], x["media"], start, end, x["_in"], enabled=g["enabled"],
                      file_frames=plan.f(d) if d else None)
            st = sub(ci, "sourcetrack")
            sub(st, "mediatype", "audio")
            sub(st, "trackindex", 1)
            if x.get("gain_db"):
                level(ci, float(x["gain_db"]))
    for m in plan.markers:
        mk = sub(seq, "marker")
        sub(mk, "comment", m["comment"])
        sub(mk, "name", m["name"])
        sub(mk, "in", m["start"])
        sub(mk, "out", m["start"] + m["dur"] if m["dur"] else -1)
    ET.indent(root, " ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + ET.tostring(root, encoding="unicode") + "\n"


def main():
    pk.utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("to", choices=["otio", "xml"], help="otio: OpenTimelineIO; xml: Final Cut Pro 7 XML (Premiere Pro, DaVinci Resolve)")
    ap.add_argument("project", help="a package folder (NAME.edit), a project.json or a versions/v<n>.json")
    ap.add_argument("--out", required=True, help="the file to write (.otio or .xml)")
    ap.add_argument("--relative", action="store_true", help="media paths relative to the output file instead of absolute")
    a = ap.parse_args()
    p, base = load(a.project)
    out = Path(a.out)
    plan = Plan(p, base, out.parent if str(out.parent) else ".", a.relative)
    if a.to == "otio":
        text = json.dumps(to_otio(plan), indent=2, ensure_ascii=False) + "\n"
    else:
        text = to_xml(plan)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    c = plan.counts
    print(f"{out}: {c['clips']} clips, {c['pictures']} pictures, {c['sounds']} sounds, {c['text']} text and "
          f"{c['notes']} notes as markers; {plan.end} frames at {plan.fps:g} fps ({plan.end / plan.fps:.2f} s)")
    for x in plan.lost:
        print("  not carried over:", x)


if __name__ == "__main__":
    main()
