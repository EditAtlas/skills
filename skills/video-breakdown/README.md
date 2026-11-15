# video-breakdown

Break down a reference video shot by shot and name what it does, with the [EditAtlas](https://edit.trysometh.ing)
technique for each transition, camera move, text style and sound, and a recipe to make one like it. It also
compares a remake with the reference and says what to fix. Claude measures
the video, looks at frame sheets, searches EditAtlas and writes a report.

Status: beta (0.5.0).

## Needs

- Python 3.9+ with numpy and Pillow (`pip install numpy pillow`)
- FFmpeg with ffprobe in PATH
- The EditAtlas MCP for search (or network access to its REST API); the measuring itself runs offline, except
  lookalike fonts, which `text_look.py` downloads once from Google Fonts

## Files

| Path | What |
|---|---|
| `SKILL.md` | The workflow Claude follows |
| `references/reading-the-numbers.md` | Every measurement, how often it was right on known videos, search terms per label |
| `references/notes-format.md` | The notes Claude writes, with an example |
| `scripts/analyze.py` | Joins and their kind (shape wipes included), camera moves, timing of designed motion (in, hold, out, loops), look, overlay events, pacing, tempo and cuts on the beat, sound hits, frame sheets |
| `scripts/frames.py` | Frames around a time, at chosen times, or a cropped part of the frame |
| `scripts/text_look.py` | One piece of text: fill colour or gradient stops, outline, shadow or glow, lean, stroke weight and contrast, free lookalike fonts drawn beside it, and the font size in each |
| `scripts/elements.py` | Motion graphics: each graphic's entrance, hold and exit, things coming in one after another (stagger), shapes carried across a cut |
| `scripts/background.py` | A designed background: flat, straight gradient (direction, hex colours, CSS) or radial glow |
| `scripts/compare.py` | A remake against its reference: timing of moves, cuts, rows of text (how many, how tall, stagger), background and look |
| `scripts/report.py` | Checks the notes (and, with `--check-api`, every slug and sound id) and writes the report |
| `evals/` | Test cases in the `claude plugin eval` layout; inputs are downloaded from the EditAtlas site or drawn in code |

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

### 0.3.0: text colours and fonts

A user remade a 4 s vertical ad after a 0.2.0 breakdown and the text came out wrong: a casual brush script where
the original has a calligraphic one, flat colours where it has gradients, words in front of the person where the
original puts them behind. 0.3.0 adds `text_look.py`, an overview of 24 frames or more, a text checklist in
`SKILL.md`, and a `style` that `report.py` requires for every text element.

On that video, one fresh agent per version, the same request ("what effects, what kind of text, what colours, so I
can remake it"), graded on ten points checked by hand:

| | 0.2.0 | 0.3.0 |
|---|---|---|
| Points | 6 of 10 | 10 of 10 |
| Script named as calligraphic, with a free lookalike | no ("italic handwriting", no font) | yes (Italianno, Pinyon Script) |
| Gradient stops and direction for the three coloured titles | 1 of 3 | 3 of 3 |
| Text behind the person, entrances, grey sans titles | yes | yes |
| Time, tokens | 312 s, 140k | 435 s, 158k |

One run each; the 0.2.0 agent also found one gradient by sampling pixels itself.

### 0.4.0: timing of designed motion

People call some motion graphics "premium"; on 12 public demos from a design-tool maker (logos, titles, a chart,
a brand-guideline reel, looping banners) the difference is mostly timing. 0.4.0 measures it: per shot, how long
things take to come in and whether they settle or speed up, how much of the shot holds still, how they leave, and
whether the exit plays the entrance backwards; whether the video ends on its first frame (made to loop); and a
`shape wipe` join for a flat shape, often the brand's own mark, that grows over the picture.

| Check, the same videos before and after | 0.3.0 | 0.4.0 |
|---|---|---|
| Brand-shape transitions in the guideline reel named as a shape wipe | 0 of 3 (dip, zoom, zoom) | 3 of 3, side and outline right |
| Cuts to a white page called `white flash` | 2 | 0 |
| Banners that end on their first frame marked as loops | not measured | 3 of 3, no false ones |
| Joins changed on the 24 transition demos, the full edit demos and 5 live-action test videos | | none |
| Shots with timing words on the 5 live-action videos | | 5 of 33: freeze frames, title cards, locked-off holds |


### 0.5.0: motion graphics, backgrounds, font size, comparing a remake

Ideas from studying how motion-graphics tools describe motion, built as five candidate features and tested one by
one against 0.4.1 on short test videos drawn in code, where every timing, size and colour is known. Fresh Sonnet
agents ran each case three times; a separate agent graded the replies against the truth.

| Case | 0.4.1 | 0.5.0 |
|---|---|---|
| motion-graphics-stagger: words coming in 0.12 s apart, a circle carried across a cut, a card sliding up | 0.73 | 1.00 (3 of 3 full) |
| compare-remake: a remake with five known differences | 0.56 | 0.83 (all five found in 6 of 6 runs; each run also reported a difference caused by the slower slide or seen by eye) |
| title-size-background: font size, gradient background | 0.73 | 0.73 (title size right in 3 of 3, against 2 of 3) |
| comedy-edit (repo case) | 0.80 | 0.93 |
| space-trailer (repo case) | 0.67 | 0.67 |
| drink-reel-beat (repo case) | 0.78 | 0.89 |
| no-video-given (repo case) | 1.00 | 1.00 |
| vertical-short-captions (repo case) | 0.75 | 0.92 |

Kept: `elements.py`, `compare.py`, `background.py` and the font size per lookalike in `text_look.py`. Dropped after
the same test: an easing-curve fitter (it named the ease right on 61 of 64 test moves, but agents already guessed
common eases from the frames, 0.93 without it against 0.80 with it) and a separate remake brief file (0.60 with and
without; an editor building from the brief alone scored the same). Runs cost about $0.10 to $0.40 each; the four repo
cases with a video cost about $0.10 more a run than with 0.4.1 (agents take more steps). Not tested: real motion-graphics videos (all test videos were drawn
in code, and the tools were tuned on them), models other than Sonnet.
