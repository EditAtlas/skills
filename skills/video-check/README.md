# video-check

Check a finished render before anyone sees it, then fix what is wrong. Claude measures the file, the picture and the
sound with FFmpeg, makes frame sheets at phone size, has a reviewer who has not seen the plan look at them, fixes the
three worst problems, checks again (at most three rounds), and writes a `REVIEW.md` that says what was measured,
what was looked at and what nobody listened to.

Status: beta (0.3.0).

## Needs

- Python 3.9+ with numpy and Pillow (`pip install numpy pillow`)
- FFmpeg with ffprobe in PATH (4.x and later; tested on 9.0)
- Optional: the EditAtlas MCP, to look up a method for a fix (`search_techniques`, `get_technique`)

## Files

| Path | What |
|---|---|
| `SKILL.md` | The workflow Claude follows |
| `scripts/check.py` | File spec, black, white, frozen, stray and repeated frames, cuts and wrong frames at joins, loop seam, loudness, true peak, silences, audio length and ending, music under the voice (with the two tracks), text too small, too brief or under the buttons (with the text layers); levels by kind of video (`--type`); overview, cut-strip and findings sheets; `--before` compares with an earlier round |
| `scripts/fix_sound.py` | Loudness and true peak fixed on a finished file in one go: peaks limited, two-pass `loudnorm`, picture copied, result measured |
| `references/reading-the-checks.md` | Every check, its thresholds, what it misses, and the results on known videos |
| `references/video-types.md` | What blocks delivery and what is only a note, for a tutorial, a talking head, a promo, a reel and a film |
| `references/review-guide.md` | The brief for a fresh reviewer, the brief for checking claimed fixes, the tells of a template-made edit, the problem format, the `REVIEW.md` template |
| `evals/` | Test cases in the `claude plugin eval` layout; inputs are downloaded from the EditAtlas site |

## Verified

On 2026-11-11, `check.py` 0.1.0:

| Set | Result |
|---|---|
| 17 files with one known fault each (black, white, stray and frozen frames, silence, clipping, no audio, pixel format, frame-rate stutter, short audio, abrupt end, wrong size, three loops) | every fault found with the right code; no finding on the clean file or the right loop; no extra findings |
| 137 finished videos (125 EditAtlas demo renders, 12 public motion-graphics demos) | no crash; found 7 that clip (+0.2 to +4.8 dBTP); the rest were planned (silent picture demos, dips, stills) or true (not normalized, cut mid-sound) |
| One fix round on a clipping demo | round 2 found the single-pass loudness fix left the true peak at -0.8 dBTP |

A fresh agent ran `clipping-dialogue` once with the skill and once without (2026-11-11):

| | With the skill | Without |
|---|---|---|
| Graders passed | 5 of 5 | 2 of 5 (one grader asks for `check.py`, which it did not have) |
| Clipping (+4.8 dBTP) found and fixed | yes, -2.4 dBTP | yes, -2.0 dBFS sample peak |
| Loudness brought to -14 LUFS | yes, -14.4 | no (offered) |
| Checked again after the fix, against round 1 | yes (`--before`) | its own measurements |
| Fresh reviewer, review file, "nobody listened" | yes | no |
| Time, tokens | 295 s, 94k | 606 s, 149k |

The agent without the skill found something the skill missed: four places where two burned-in captions overlap for
0.1 s, which sheets at 0.5 s steps cannot show. One run each.

### Eval, version 0.2.0 (2026-11-11)

All three test cases, three runs each, with the skill and without. Each run was a fresh `claude -p` agent (Sonnet
5.5) with no user settings, hooks or MCP servers, and the tools the case allows; the run with the skill had only
this skill, without `evals/` or this README. A Sonnet judge graded each run from its full trace against the case's
graders; where a grader names `check.py` or an overview sheet, any measurement or extracted frames counted for the
run without the skill. The harness measured every MP4 the runs left on its own. (`claude plugin eval` refuses to run
shell tools on Windows, where it has no sandbox, so the same cases ran through this harness.)

| Case | With the skill | Without |
|---|---|---|
| `clipping-dialogue` | 1.00, 3 of 3 runs passed | 0.20, 0 of 3 |
| `vertical-short-clean` | 1.00, 3 of 3 | 0.25, 0 of 3 |
| `no-video-given` | 1.00, 3 of 3 | 1.00, 3 of 3 |
| Mean time, cost per run (first two cases) | 41 s, $0.15 | 41 s, $0.13 |

On `clipping-dialogue` every run with the skill delivered -14.03 LUFS and -1.62 dBTP, measured by the harness; the
runs without it fixed the clipping but left the sound at -16.5 to -17.0 LUFS, missed the repeated frames, and wrote
no review file.

Four earlier rounds led to the changes in this version: one run hand-tuned filters for three rounds and delivered
-18 LUFS, which `fix_sound.py` now prevents; one review shortened the repeated-frame pattern to a count and left out
that nobody listened, which `SKILL.md` and the template now require; two runs guessed a 1080p target for a 540p file
from the example command, which now leaves `--expect` out; one called a review "ready with notes" with P1s left that
it could not fix without the project, which the verdict rule now allows by name. The table is the last round of the
case with the final text (`no-video-given` from the round before, unchanged by the last edits).

On 2026-11-11 the owner looked at the results of the last round (both videos, their `REVIEW.md` files, the sheets
and `before_after.png`) and approved the skill for beta.

### Eval, version 0.3.0 (2026-11-17)

`check.py` 0.2.0 against 0.1.2 (the script in 0.2.5) on 26 planted faults in 25 files: six at cuts in film footage
(a white frame, a magenta frame and a frame of an earlier shot on the join; a frame from later in the clip just after
or just before the join; two wrong frames), four text faults read from the project's text layers or an `.srt`, and
the 0.1.0 set rebuilt. Details are in `references/reading-the-checks.md`.

| | 0.3.0 | 0.2.5 |
|---|---|---|
| Planted faults found | 26 of 26 | 15 of 26 (no joins, no text, one loop seam) |
| Findings not planted | 0 | 0 |
| 143 finished videos: crashes | 0 | 0 |
| 143 finished videos: new `join_frame` findings | 4, in 2 files (a fast move, an iris, two ghosted frames) | - |
| 147 s video with 21 cuts: images to read | 8 (5 overview, 2 cut strips, 1 findings) | 0 (sheets were lost past about 100 frames) |

Fresh agents (Sonnet 5.5, `claude -p` with no settings, no MCP and one plugin holding only this skill), 0.3.0 against
0.2.5, two runs a case (three for the tutorial), all told not to edit:

| Case | 0.3.0 | 0.2.5 |
|---|---|---|
| Reel with a white frame and a stray frame at cuts, a tiny and a brief caption, and its `project.json` | 8 of 8 faults found | 6 of 8 (the stray frame missed both times) |
| Editor's review claims three fixes, a caption was not moved | false fix caught 2 of 2, no fix wrongly called made | 2 of 2, none |
| Agency's review claims three fixes, a frame at a cut was not trimmed | 2 of 2, none | 2 of 2, none |
| Help-center screen recording with long held screens and no hook | 3 wrong blockers in 3 runs; "ready with notes" 2 of 3 | 6 in 3 runs; "not ready" 3 of 3 |
| Wrong blockers, all cases | 5 | 10 |
| Cost per run | $0.13 to $0.20 | $0.12 to $0.17 |

Pairs, each judged twice with A and B swapped (Sonnet, shown the person's request and what is really in the video):
0.3.0 won 5, tied 2 and lost 2 of 9; the judge picked the ideal answer over a poor one in all 4 controls and never
chose the same letter in both orders (0 of 13). The two losses: a tutorial run that called small 960x540 interface
text a blocker (the rubric now gives the phone numbers for it), and a promo run that blocked on "no product on
screen". Checking claimed fixes made no measurable difference with these agents: 0.2.5 caught every false claim too,
by pulling the frames at the claimed times itself. A script that did it for them (`verify_fixes.py`) was tried and left out;
the brief for checking claims stays.
