# video-check

Check a finished render before anyone sees it, then fix what is wrong. Claude measures the file, the picture and the
sound with FFmpeg, makes frame sheets at phone size, has a reviewer who has not seen the plan look at them, fixes the
three worst problems, checks again (at most three rounds), and writes a `REVIEW.md` that says what was measured,
what was looked at and what nobody listened to.

Status: beta (0.2.0).

## Needs

- Python 3.9+ with numpy and Pillow (`pip install numpy pillow`)
- FFmpeg with ffprobe in PATH (4.x and later; tested on 9.0)
- Optional: the EditAtlas MCP, to look up a method for a fix (`search_techniques`, `get_technique`)

## Files

| Path | What |
|---|---|
| `SKILL.md` | The workflow Claude follows |
| `scripts/check.py` | File spec, black, white, frozen, stray and repeated frames, cuts, loop seam, loudness, true peak, silences, audio length and ending; overview and findings sheets; `--before` compares with an earlier round |
| `scripts/fix_sound.py` | Loudness and true peak fixed on a finished file in one go: peaks limited, two-pass `loudnorm`, picture copied, result measured |
| `references/reading-the-checks.md` | Every check, its thresholds, what it misses, and the results on known videos |
| `references/review-guide.md` | The brief for a fresh reviewer, the tells of a template-made edit, the problem format, the `REVIEW.md` template |
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
