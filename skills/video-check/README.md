# video-check

Check a finished render before anyone sees it, then fix what is wrong. Claude measures the file, the picture and the
sound with FFmpeg, makes frame sheets at phone size, has a reviewer who has not seen the plan look at them, fixes the
three worst problems, checks again (at most three rounds), and writes a `REVIEW.md` that says what was measured,
what was looked at and what nobody listened to.

Status: draft (0.1.0).

## Needs

- Python 3.9+ with numpy and Pillow (`pip install numpy pillow`)
- FFmpeg with ffprobe in PATH (4.x and later; tested on 9.0)
- Optional: the EditAtlas MCP, to look up a method for a fix (`search_techniques`, `get_technique`)

## Files

| Path | What |
|---|---|
| `SKILL.md` | The workflow Claude follows |
| `scripts/check.py` | File spec, black, white, frozen, stray and repeated frames, cuts, loop seam, loudness, true peak, silences, audio length and ending; overview and findings sheets; `--before` compares with an earlier round |
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

Not yet done for beta: a person reviewing real results, the other two test cases, an install from the marketplace.
