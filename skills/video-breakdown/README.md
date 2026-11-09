# video-breakdown

Break down a reference video shot by shot and name what it does, with the [EditAtlas](https://edit.trysometh.ing)
technique for each transition, camera move, text style and sound, and a recipe to make one like it. Claude measures
the video, looks at frame sheets, searches EditAtlas and writes a report.

Status: beta (0.2.0).

## Needs

- Python 3.9+ with numpy and Pillow (`pip install numpy pillow`)
- FFmpeg with ffprobe in PATH
- The EditAtlas MCP for search (or network access to its REST API); the measuring itself runs offline

## Files

| Path | What |
|---|---|
| `SKILL.md` | The workflow Claude follows |
| `references/reading-the-numbers.md` | Every measurement, how often it was right on known videos, search terms per label |
| `references/notes-format.md` | The notes Claude writes, with an example |
| `scripts/analyze.py` | Joins and their kind, camera moves, look, overlay events, pacing, tempo and cuts on the beat, sound hits, frame sheets |
| `scripts/frames.py` | Frames around a time, at chosen times, or a cropped part of the frame |
| `scripts/report.py` | Checks the notes (and, with `--check-api`, every slug and sound id) and writes the report |
| `evals/` | Test cases in the `claude plugin eval` layout; inputs are downloaded from the EditAtlas site |

## Verified

On 2026-11-09, on EditAtlas demos whose edits are known:

| Set | Result |
|---|---|
| 24 transition demos | join found at the right time in 23; kind right in 17 |
| 3 full edits, 5 to 7 shots | every designed join found; a silent film with flicker gave 14 joins for 5 |
| 4 product reels cut on the beat | cuts on the beat 9/9, 10/13, 5/8, 0/10 (the last: a grid that drifts) |
| 1 full run (comedy edit, 17 s) | 9 elements named with EditAtlas techniques, all slugs confirmed by `--check-api`; missed the freeze frame and the speed ramp |

Fresh agents ran the five test cases in `evals/` on 2026-11-09, one run each, with and without the skill:

| Case | With the skill | Without |
|---|---|---|
| comedy-edit | 100% | 83% |
| drink-reel-beat | 100% | 100% |
| no-video-given | 100% | 50% (tried to download from TikTok) |
| vertical-short-captions | 100% (0.1.0: 67%) | 33% (no EditAtlas techniques named) |
| space-trailer | 100% | 83% |

Mean 100% with the skill, 70% without; 267 s against 341 s a run. Every technique slug in all replies exists on
EditAtlas. `/plugin marketplace add EditAtlas/skills` and `/plugin install video-breakdown@editatlas-skills` work.

The owner read the reports and approved beta on 2026-11-09.
