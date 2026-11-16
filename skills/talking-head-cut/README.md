# talking-head-cut

Cut a raw talking-head recording into a clean video. Claude reads the take as numbered lines with the likely
mistakes marked, decides what goes (false starts, failed and repeated takes, notes to the editor, doubled words,
fillers), names it by quoting the words, and the scripts put every cut in silence, shorten long pauses to a breath,
render picture and sound in step, and transcribe the cut again to catch anything left in or clipped.

Status: draft (0.1.0).

## Needs

- Python 3.9+ with numpy
- FFmpeg with ffprobe in PATH (tested on 9.0)
- The EditAtlas transcribe skill and its faster-whisper (for the transcript and for `verify.py`)

## Files

| Path | What |
|---|---|
| `SKILL.md` | The workflow Claude follows |
| `scripts/takes.py` | The take as numbered lines with measured pauses; marks notes to the editor, retakes, unfinished lines, doubled words, fillers and voice with no words |
| `scripts/cut.py` | Turns the plan (lines and quotes to remove) into an edit list: measures where each kept word's sound starts and ends, puts cuts in the quiet, shortens pauses by the pace, aligns edges to the frame grid; writes `cuts.md` and a transcript in the cut film's time |
| `scripts/render.py` | One FFmpeg pass: every piece trimmed and joined with the concat filter, 20 ms fades on the sound at each join, picture and sound lengths compared |
| `scripts/verify.py` | Transcribes the cut again and lines it up with the kept words (extra, missing, doubled, fillers), measures joins and pauses, writes `seams.jpg` |
| `scripts/common.py` | Shared helpers, including `tighten()`, which moves Whisper's word times onto the measured sound |
| `references/formats.md` | Every field of the plan and the output files |
| `references/how-cuts-are-placed.md` | How cuts are placed, and what the check can and cannot catch |
| `evals/` | Test cases in the `claude plugin eval` layout; `make_raw.py` makes the raw takes fresh with Microsoft Edge voices |

## Verified

Three raw takes made with `evals/make_raw.py`, each line said on its own and joined with known pauses, so the
answer is known exactly: a 54 s English tip video (13 lines to keep; a false start, a wrong try, two notes to the
editor, a doubled phrase, a replaced closing line, two fillers, a deliberate repetition), a 49 s Vietnamese one (9
to keep) and a 46 s Reels take whose notes to the editor use words the script does not list. The picture carries
the source frame number, so sync is measured. A scorer finds every spoken piece in the cut by waveform correlation
and measures what is kept, clipped, left in, the pauses and the sync.

A fresh Sonnet agent with all EditAtlas skills ran each take; "without" had every released skill but this one
(2026-11-16). Score = share of 7 graders (all kept lines present and unclipped, nothing to cut left in, fillers
gone, no pause over 1 s and no glued join, sync within 45 ms, removals named by their words, no claim of having
listened):

| Take | Without | With |
|---|---|---|
| English YouTube take | 0.71, 0.71 | 1.00, 1.00 |
| Vietnamese take | 0.86, 0.71 | 1.00, 1.00 |
| Reels take, unlisted notes | 0.57, 0.71 | 1.00, 1.00 |

- Without the skill, both English runs removed the deliberate "Never." (taken as a repeat), one Reels run clipped
  80 ms off a line end and another glued two sentences, and picture and sound drifted by 46 to 60 ms (1.5 to 2
  frames) at some lines in every run. With it, the sync matched the source at every line (at most 31 ms, the
  source's own frame rounding) and pauses stayed between 0.31 and 0.45 s.
- Cost per run: $0.12 to $0.14 with the skill, $0.13 to $0.22 without.
- Two runs of each arm per take; a third was cut off by an account usage limit and is not counted.

Not checked: real recordings (room noise, breaths, music under the voice, people talking over each other), a person
listening to the cuts, models other than Sonnet, takes longer than a minute.
