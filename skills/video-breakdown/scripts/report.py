"""Check your notes against the measurements and write the breakdown report.

  report.py work/bd/breakdown.json work/bd/notes.json --out result/breakdown.md
  report.py ... --check-api            # also confirm every technique slug and sound id exists on EditAtlas

notes.json is yours: what you saw in each shot, the elements you named, the EditAtlas technique or sound for each,
a recipe and what you did not check (format in references/notes-format.md). The script refuses notes that skip a
shot, cite a technique without its name, or leave out what was not checked.
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from common import read_json, utf8_stdout

SITE = "https://edit.trysometh.ing"
KINDS = {"transition", "camera", "text", "graphic", "look", "effect", "speed", "sound", "music", "voice", "layout",
         "pacing", "other"}
EVIDENCE = {"measured", "looked", "measured+looked", "guessed"}
SLUG = re.compile(r"^[a-z0-9][a-z0-9.\-]*$")
SFX_ID = re.compile(r"^sfx-[a-z0-9]+$")

WORDS = {
    "en": {"title": "Breakdown", "video": "Video", "format": "Format", "shots": "Shots", "pace": "Pace",
           "audio": "Audio", "summary": "In short", "shot_table": "Shot by shot", "n": "#", "time": "Time",
           "len": "Length", "in": "In", "camera": "Camera (measured)", "seen": "What is on screen",
           "elements": "What it does, and how to make it", "at": "At", "what": "What", "how": "EditAtlas",
           "ev": "Evidence", "nomatch": "no match", "sound": "Sound", "recipe": "To make one like it",
           "corrections": "Where the measurements were wrong", "unchecked": "Not checked",
           "measured_note": "Measured by analyze.py; the agent looked at the frames to name each element. "
                            "Evidence: measured = from the numbers, looked = from the frames, guessed = neither.",
           "median": "median shot", "per_min": "joins a minute", "beat": "tempo", "speech": "speech-like",
           "follow": "cuts follow the beat", "nofollow": "cuts do not follow a beat grid", "none": "no audio"},
    "vi": {"title": "Phân tích video mẫu", "video": "Video", "format": "Khung hình", "shots": "Số cảnh",
           "pace": "Nhịp", "audio": "Âm thanh", "summary": "Tóm tắt", "shot_table": "Từng cảnh", "n": "#",
           "time": "Thời điểm", "len": "Dài", "in": "Vào cảnh bằng", "camera": "Camera (đo được)",
           "seen": "Trên hình có gì", "elements": "Hiệu ứng trong video và cách làm", "at": "Lúc",
           "what": "Là gì", "how": "EditAtlas", "ev": "Căn cứ", "nomatch": "chưa có kỹ thuật khớp",
           "sound": "Âm thanh", "recipe": "Để làm một video như vậy",
           "corrections": "Chỗ số đo sai", "unchecked": "Chưa kiểm tra",
           "measured_note": "Số đo từ analyze.py; agent xem khung hình để gọi tên từng hiệu ứng. "
                            "Căn cứ: measured = từ số đo, looked = từ khung hình, guessed = đoán.",
           "median": "cảnh trung vị", "per_min": "lần chuyển mỗi phút", "beat": "tempo", "speech": "giống giọng nói",
           "follow": "điểm cắt theo beat", "nofollow": "điểm cắt không theo beat", "none": "không có tiếng"},
}


def problems(bd, notes):
    out = []
    dur = bd["format"]["analysed_s"]
    seen = {s.get("n"): s for s in notes.get("shots", []) if isinstance(s, dict)}
    for s in bd["shots"]:
        if s["n"] not in seen or not str(seen[s["n"]].get("seen", "")).strip():
            out.append(f"shot {s['n']} ({s['start']}-{s['end']} s) has no 'seen' in notes.shots. Look at it and say "
                       "what is on screen, or explain in 'corrections' why it is not a real shot.")
    els = notes.get("elements") or []
    if not els:
        out.append("notes.elements is empty: name at least the joins, the camera moves and the text you saw.")
    for i, e in enumerate(els):
        tag = f"elements[{i}]"
        if e.get("kind") not in KINDS:
            out.append(f"{tag}.kind must be one of {sorted(KINDS)}")
        if not str(e.get("seen", "")).strip():
            out.append(f"{tag}.seen is empty: describe what happens in plain words")
        if e.get("evidence") not in EVIDENCE:
            out.append(f"{tag}.evidence must be one of {sorted(EVIDENCE)}")
        at = e.get("at")
        ts = at if isinstance(at, list) else [at]
        if at is None or not all(isinstance(t, (int, float)) and -0.01 <= t <= dur + 0.5 for t in ts):
            out.append(f"{tag}.at must be a time or [start, end] inside the video (0-{dur} s)")
        t = e.get("technique")
        if t:
            if not SLUG.match(str(t.get("slug", ""))):
                out.append(f"{tag}.technique.slug '{t.get('slug')}' is not a technique slug")
            if not str(t.get("name", "")).strip():
                out.append(f"{tag}.technique.name is empty: copy the name get_technique returned")
        elif e.get("kind") not in {"sound", "music", "voice", "pacing"} and not str(e.get("gap", "")).strip():
            out.append(f"{tag} has no technique and no 'gap': say what you searched and why nothing fit")
        sfx = e.get("sfx")
        if sfx and sfx.get("example_id") and not SFX_ID.match(str(sfx["example_id"])):
            out.append(f"{tag}.sfx.example_id '{sfx['example_id']}' is not an EditAtlas sound id")
    if not notes.get("recipe"):
        out.append("notes.recipe is empty: give the steps to make a video like this with the person's own footage")
    if not notes.get("not_checked"):
        out.append("notes.not_checked is empty: list what you could not know (fonts, exact speeds, sources, ...)")
    if notes.get("lang", "en") not in WORDS:
        out.append(f"notes.lang must be one of {sorted(WORDS)}")
    return out


def check_api(notes, api):
    """Every slug and sound id must exist. Returns a list of problems."""
    out = []
    def get(url):
        req = urllib.request.Request(url, headers={"User-Agent": "video-breakdown-skill/0.1"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    cache = {}
    for i, e in enumerate(notes.get("elements") or []):
        for key, path in (("technique", "techniques"), ("sfx", "sfx")):
            item = e.get(key)
            ident = item and (item.get("slug") if key == "technique" else item.get("example_id"))
            if not ident:
                continue
            url = f"{api.rstrip('/')}/api/v1/{path}/{ident}"
            if url not in cache:
                try:
                    cache[url] = get(url)
                except urllib.error.HTTPError as err:
                    cache[url] = None if err.code == 404 else {"_error": f"HTTP {err.code}"}
                except OSError as err:
                    cache[url] = {"_error": str(err)}
            row = cache[url]
            if row is None:
                out.append(f"elements[{i}].{key} '{ident}' does not exist on EditAtlas: use an id that a search returned")
            elif "_error" in row:
                out.append(f"could not check '{ident}' ({row['_error']}); run again or check it with get_technique/get_sfx")
            elif key == "technique" and item.get("name") and row.get("name") and \
                    item["name"].strip().lower() != str(row["name"]).strip().lower():
                out.append(f"elements[{i}].technique '{ident}' is named '{row['name']}' on EditAtlas, not '{item['name']}'")
    return out


def fmt_t(t):
    if isinstance(t, list):
        return f"{t[0]:.2f}-{t[1]:.2f} s"
    return f"{t:.2f} s"


def esc(x):
    return str(x).replace("|", "\\|").replace("\n", " ")


def render(bd, notes):
    W = WORDS[notes.get("lang", "en")]
    f, p, a = bd["format"], bd["pacing"], bd["audio"]
    L = [f"# {W['title']}: {esc(notes.get('title') or Path(bd['video']).name)}", ""]
    if notes.get("summary"):
        L += [f"**{W['summary']}.** {notes['summary']}", ""]
    if a.get("has_audio"):
        mu = a.get("music", {})
        aud = f"{a.get('lufs')} LUFS; {W['speech']} {a.get('speech_like_share')}"
        if mu.get("bpm"):
            aud += f"; {W['beat']} ~{mu['bpm']} BPM; " + (mu.get("cuts_follow_beat") or W["nofollow"])
    else:
        aud = W["none"]
    L += [f"| {W['video']} | |", "|---|---|",
          f"| {W['format']} | {f['shape']}, {f['fps']} fps, {f['duration']} s |",
          f"| {W['shots']} | {p['shots']} |",
          f"| {W['pace']} | {W['median']} {p['median_shot_s']} s, {p['cuts_per_minute']} {W['per_min']} |",
          f"| {W['audio']} | {esc(aud)} |", ""]
    seen = {s.get("n"): s for s in notes.get("shots", [])}
    L += [f"## {W['shot_table']}", "",
          f"| {W['n']} | {W['time']} | {W['len']} | {W['in']} | {W['camera']} | {W['seen']} |",
          "|---|---|---|---|---|---|"]
    for s in bd["shots"]:
        L.append(f"| {s['n']} | {s['start']:.2f}-{s['end']:.2f} | {s['seconds']:.2f} | {esc(s['in'])} | "
                 f"{esc('; '.join(s.get('camera', [])))} | {esc(seen.get(s['n'], {}).get('seen', ''))} |")
    L += ["", f"## {W['elements']}", "", f"| {W['at']} | {W['what']} | {W['how']} | {W['sound']} | {W['ev']} |",
          "|---|---|---|---|---|"]
    for e in sorted(notes.get("elements", []), key=lambda e: e["at"][0] if isinstance(e["at"], list) else e["at"]):
        t = e.get("technique")
        how = (f"[{esc(t['name'])}]({SITE}/techniques/{t['slug']}) (`{t['slug']}`)" + (f", {t['match']}" if t.get("match") else "")
               if t else f"{W['nomatch']}: {esc(e.get('gap', ''))}" if e.get("gap") else "")
        sfx = e.get("sfx") or {}
        snd = " ".join(x for x in (esc(sfx.get("category", "")), f"`{sfx['example_id']}`" if sfx.get("example_id") else "") if x)
        what = f"**{esc(e['kind'])}**: {esc(e['seen'])}" + (f" ({esc(e['note'])})" if e.get("note") else "")
        L.append(f"| {fmt_t(e['at'])} | {what} | {how} | {snd} | {e['evidence']} |")
    L += ["", f"## {W['recipe']}", ""] + [f"{i}. {r}" for i, r in enumerate(notes.get("recipe", []), 1)]
    if notes.get("corrections"):
        L += ["", f"## {W['corrections']}", ""] + [f"- {c}" for c in notes["corrections"]]
    L += ["", f"## {W['unchecked']}", ""] + [f"- {c}" for c in notes.get("not_checked", [])]
    L += ["", f"_{W['measured_note']} ({bd.get('tool', 'analyze.py')})_", ""]
    return "\n".join(L)


def main():
    utf8_stdout()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("breakdown")
    p.add_argument("notes")
    p.add_argument("--out", required=True, help="markdown file to write")
    p.add_argument("--check-api", nargs="?", const=SITE, default=None, metavar="URL",
                   help=f"confirm slugs and sound ids against the EditAtlas REST API (default {SITE})")
    a = p.parse_args()
    bd, notes = read_json(a.breakdown), read_json(a.notes)
    issues = problems(bd, notes)
    if not issues and a.check_api:
        issues = check_api(notes, a.check_api)
    if issues:
        print("notes need work before the report:")
        for i in issues:
            print("  -", i)
        sys.exit(1)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(bd, notes), encoding="utf-8")
    n_t = sum(1 for e in notes["elements"] if e.get("technique"))
    print(f"{len(notes['elements'])} elements, {n_t} with an EditAtlas technique, "
          f"{sum(1 for e in notes['elements'] if (e.get('sfx') or {}).get('example_id'))} with a sound id")
    print("->", out)


if __name__ == "__main__":
    main()
