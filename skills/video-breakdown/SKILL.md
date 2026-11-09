---
name: video-breakdown
description: Break down a reference video shot by shot and name what it does, so the person can make one like it. Measures cuts and transitions (dissolve, dip, wipe, iris, push, zoom, flash, punch-in), camera moves (push in, crash zoom, pan, shake, freeze, speed change), text and graphics coming on screen, the look, pacing, music tempo and whether cuts follow the beat, and sound hits; you look at the frame sheets, then look up each element in EditAtlas (search_techniques, get_technique, search_sfx) and write a report with technique names, links, sounds and a recipe. Use it when someone shares a video they like and asks what effect, transition or edit is in it, how it was made, or how to remake it; says "video này dùng hiệu ứng gì", "phân tích video mẫu", "làm sao để edit giống video này", "hiệu ứng chuyển cảnh này tên gì", "reverse engineer this edit", "what transition is this". Works on a file on this machine. Not for downloading videos from TikTok or YouTube, telling filmed from AI footage, or editing the video itself.
license: Apache-2.0. LICENSE.txt has the complete terms
compatibility: Requires Python 3.9+ with numpy and Pillow, and FFmpeg with ffprobe. Runs offline; only the optional --check-api step and the EditAtlas MCP use the network. Designed for Claude Code and other agents with a shell that can read images.
metadata:
  author: EditAtlas
  version: "0.2.0"
  status: beta
  library: techniques sfx
  mcp-tools: search_techniques get_technique search_sfx get_workflow
---

# Video breakdown: from a video someone likes to named techniques and a recipe

The person has a video they like and cannot name what is in it. You give them, shot by shot, the correct name of
each transition, camera move, text style and sound, the EditAtlas technique that makes it, and the steps to make
one like it with their own footage.

Three things are true the whole way through:

- **The numbers are hints, the frames are the evidence.** `analyze.py` measures pixels and samples. It confuses a
  crash zoom with a join, an iris with a dip to black, an old film's flicker with cuts. Every element you name must
  come from frames you opened with the Read tool. Say which ones you only measured.
- **You cannot hear.** Audio numbers say where something sudden happens, how loud, how bright, and the tempo.
  They do not say what the sound is. Never write "a whoosh" for a transient you have not identified; write
  "a short bright hit at 4.9 s, near the zoom".
- **Never invent.** Work only on the file the person gave. Every technique slug and sound id in the report comes
  from an EditAtlas search or get call in this session. If nothing fits, say so.

Scripts are in `scripts/` (Python 3.9+, numpy, Pillow, FFmpeg with ffprobe in PATH). Run them with the skill
folder's path, from a working folder of your own (`work/`); never write into the person's folders.

```
python SKILL/scripts/analyze.py VIDEO --out work/bd                      # breakdown.json + sheets
python SKILL/scripts/frames.py VIDEO --at 6.8 --span 0.6 --step 0.04 --out work/look   # every frame of a join
python SKILL/scripts/frames.py VIDEO --at 7.9 --crop 0,60,100,40 --out work/look      # bottom 40 %, to read text
python SKILL/scripts/report.py work/bd/breakdown.json work/bd/notes.json --out result/breakdown.md --check-api
```

## When the inputs are missing

- **No file, only a link** (TikTok, Reels, YouTube): ask the person to download the video and give you the file
  path. This skill does not fetch from platforms. A screen recording of the video also works.
- **No video at all**: ask for it. Do not describe what such a video "usually" has.
- **Very long video** (over 5 minutes): `analyze.py` reads the first 300 s. Ask which part matters, or pass
  `--max-seconds`.

Breakdowns are for learning how a video was edited. The recipe uses the person's own footage; do not suggest
reusing the reference's footage, music or characters.

## 1. Measure

Run `analyze.py`. It prints a summary and writes `breakdown.json` with:

| Part | What it holds |
|---|---|
| `format` | size, shape (9:16, 16:9), fps, duration |
| `pacing` | shots, joins a minute, median / shortest / longest shot, joins in the first 3 s, regularity |
| `joins` | each change of shot: time, length, kind (`cut`, `cross-dissolve`, `dip to black`, `white flash`, `bright flash`, `wipe` with the side it comes from, `push or slide` with the direction, `zoom transition`, `blur transition`, `snap zoom or punch-in`, `jump cut`, `gradual (other)`) |
| `shots` | per shot: measured camera words (push in, fast zoom, pan, shake, hold, speed change) and the look (dark, warm, black and white, black bars, dark corners) |
| `overlays` | `events`: moments one band of the frame changes while the rest holds (text, stickers, graphics coming or going); `persistent`: regions that stay through joins (logo, frame, caption bar) |
| `audio` | loudness, speech-like share, tempo candidates and whether cuts land on the beat, transients (sudden sounds) with the nearest picture event, swells (rises into a moment) |

What each number means and where it goes wrong: `references/reading-the-numbers.md`. Read it before your first
breakdown of a session.

## 2. Look

Open, with the Read tool, in this order:

1. `overview.png`: the whole video, about one frame a second. Get the story and the style first.
2. `shots_NN.png`: first, middle and last frame of every shot. Check each shot is real: a crash zoom, a flash or
   a flicker can split one shot in two; a dissolve inside the source footage can look like a join.
3. `joins_NN.png`: six frames across every join that is not a plain cut. Name the transition from these.
4. `events.png`: before and after each overlay event. This is where captions, stickers and graphics show.

Then use `frames.py` wherever you are not sure: `--step 0.04` (one frame at 25 fps) across a join to see its
shape, `--crop` to read small text or see how a word enters (pop, bounce, slide, typewriter), `--times` for a
few moments side by side. Two or three close looks are normal; a short video with many effects may need more.

Check the format against the picture. A 9:16 video whose shots look cut out of wider footage (a film, a podcast, a
game: faces and objects cropped at the sides, a frame that sits differently in each shot) is a reframe: say so, and
search `reframe to vertical`. Wide footage with black bars is letterboxed or pillarboxed instead.

Write down, for every element, what you see in plain words before you look for a name: "the old picture is
squeezed into a horizontal line while the new one shows behind it", not "a squeeze".

## 3. Name it with EditAtlas

For each element, search by the result, not by a guessed name:

- `search_techniques` with the plain description ("circle closes to black then opens", "words bounce in one at
  a time", "sudden fast zoom into subject"). Use `category` to narrow (transition, captions, motion, vfx, color).
  Search terms that work for each analyzer label are in `references/reading-the-numbers.md`.
- `get_technique` on the best one or two, and keep the one whose description matches what you saw. Copy its
  `slug` and `name` exactly. Mark the match `exact`, `close` (same idea, a detail differs) or `partial`.
- Sounds: `search_sfx` by what the moment needs (pop for text appearing, riser into a hit, whoosh on a push). The
  sound in the reference is unknown to you; you are suggesting an EditAtlas sound for the same moment, so say so.
- `get_workflow` with the video type (`short_vertical`, `product_ad`, `food_review`, ...) for the pacing and
  structure EditAtlas recommends; compare it with what you measured.

Without the MCP, the REST API answers the same searches: `https://edit.trysometh.ing/api/v1/techniques?q=...`
and `/api/v1/sfx?q=...`.

A plain cut, a talking stretch or the footage itself needs no technique: give it a `gap` saying so. When nothing
in EditAtlas fits a real effect, write what you searched in `gap`; that tells EditAtlas what is missing.

## 4. Write the notes and the report

Write `notes.json` next to `breakdown.json` (format and an example: `references/notes-format.md`): what is on
screen in every shot, every element with its time, plain description, evidence and EditAtlas technique or sound,
corrections where the measurements were wrong, a recipe, and what you did not check. Set `lang` to the person's
language (`vi` or `en`).

Run `report.py ... --check-api`. It refuses notes that skip a shot, leave an element without a technique or a
reason, or leave out what was not checked, and with `--check-api` it confirms every slug and sound id exists on
EditAtlas and that names match. Fix what it lists and run it again.

## Deliver

Give the person, in their language:

1. Two or three sentences: what kind of edit this is and what makes it work (pace, the one signature effect).
2. The elements in time order with their names and links: the report's table, or the main rows of it.
3. The recipe: steps with their own footage, technique by technique. Offer to do the edit, which starts with
   `get_workflow`; and for the sounds, the `sound-design` skill (`get_skill`).
4. What is measured, what you looked at, and what is unknown: font names, exact speeds and curves, what each
   sound actually is, whether footage was filmed or generated.
5. The report file (`result/breakdown.md`).

After delivery, ask whether the names and techniques were right and send the answer with `send_feedback` when
that tool is available.

## References

- `references/reading-the-numbers.md`: every measurement, its known errors, and search terms per label. Read before
  the first breakdown of a session.
- `references/notes-format.md`: the notes.json fields with a complete example. Read before writing notes.
