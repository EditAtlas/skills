# sound-design

Sound-design a finished video with real sounds from the [EditAtlas](https://edit.trysometh.ing) library. Claude
looks at the picture, picks sounds from the public library, places them on the frame, renders a new MP4 and a
separate SFX track, and checks the result in numbers before showing it.

Status: beta (0.3.0).

## Needs

- Python 3.9+ with numpy and Pillow (`pip install numpy pillow`)
- FFmpeg with ffprobe in PATH
- Network access to raw.githubusercontent.com, or a local clone of
  [EditAtlas/sfx](https://github.com/EditAtlas/sfx) passed as `--mirror`

## Files

| Path | What |
|---|---|
| `SKILL.md` | The workflow Claude follows |
| `references/taste.md` | Pace, level and sync rules with numbers |
| `references/real-sfx.md` | Using Clipwing's real-sfx with the EditAtlas library, and what was verified |
| `scripts/moments.py` | Moments from the picture, frame sheets, a report on the film's own audio |
| `scripts/sounds.py` | Search the index, download with SHA-256 check, measure, draw candidates |
| `scripts/mix.py` | Cue sheet → MP4 + SFX WAV + resolved placements |
| `scripts/check.py` | Sync by waveform matching, pace, holes, loudness, mono, coverage, listen list |
| `scripts/beat_grid.py` | Tempo, first beat, every beat, a guess at bar starts and their frame numbers, from a music track |
| `scripts/realsfx_library.py` | Adapter: EditAtlas/sfx as a real-sfx main pack |
| `evals/` | Test cases in the `claude plugin eval` layout; inputs are downloaded from the EditAtlas site |

## Verified

On 2026-11-07:

- **By ear:** the owner listened to two renders made with this skill and approved them.

| Film | Sounds | Sync | Loudness | True peak |
|---|---:|---|---:|---:|
| 12 s drink reel, SFX only, with a bed | 11 + bed | 0 ms on all 11 | -16.9 LUFS | -0.9 dBFS |
| 34 s talking head, voice kept | 9 | 0 ms on all 9 | -14.7 LUFS (film -14.8) | -1.2 dBFS |

- **Fresh agents:** each test case in `evals/` was run by a new agent with only this skill, and by one without it.

| Case | With the skill | Without |
|---|---:|---:|
| sfx-only-product-reel | 5/5 | 4/5 |
| talking-head-keep-voice | 4/4 | 1/4 |
| no-video-given | 2/2 | 2/2 |
| **Total** | **100%** | **68%** |

  The first grade of the drink reel was 4/5: `check.py` mis-measured three quiet-start whooshes. That was fixed in
  0.3.0 and the same render then measured 0–1 ms on all 17 sounds.
- **Install:** `/plugin marketplace add EditAtlas/skills` and `/plugin install sound-design@editatlas-skills` work;
  the plugin loads one skill (about 240 tokens always, 2.2k when used).

Not yet checked: uploading the zip to Claude.ai, and whether the description triggers the skill reliably.

## Credit

The pace numbers, the bed level and the idea of a numeric self-check come from the measurements published with
Clipwing's [real-sfx](https://github.com/Clipwing/skills) skill by Alexander Korbanov. No code was copied from it.
