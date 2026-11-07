# sound-design

Sound-design a finished video with real sounds from the [EditAtlas](https://edit.trysometh.ing) library. Claude
looks at the picture, picks sounds from the public library, places them on the frame, renders a new MP4 and a
separate SFX track, and checks the result in numbers before showing it.

Status: draft (0.2.0).

## Needs

- Python 3.9+ with numpy and Pillow (`pip install numpy pillow`)
- FFmpeg with ffprobe in PATH
- Network access to raw.githubusercontent.com, or a local clone of
  [EditAtlas-SFX](https://github.com/ptrgiang/EditAtlas-SFX) passed as `--mirror`

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
| `scripts/realsfx_library.py` | Adapter: EditAtlas-SFX as a real-sfx main pack |
| `evals/` | Test cases in the `claude plugin eval` layout; inputs are downloaded from the EditAtlas site |

## Verified

On 2026-11-07, two films were run through this skill, rendered and checked. The skill's author ran both
following `SKILL.md`; no fresh agent has run them yet.

| Film | Sounds | Sync | Loudness | True peak |
|---|---:|---|---:|---:|
| 12 s drink reel, SFX only, with a bed | 11 + bed | 0 ms on all 11 | -16.9 LUFS | -0.9 dBFS |
| 34 s talking head, voice kept | 9 | 0 ms on all 9 | -14.7 LUFS (film -14.8) | -1.2 dBFS |

Nobody has listened to either result yet.

## Credit

The pace numbers, the bed level and the idea of a numeric self-check come from the measurements published with
Clipwing's [real-sfx](https://github.com/Clipwing/skills) skill by Alexander Korbanov. No code was copied from it.
