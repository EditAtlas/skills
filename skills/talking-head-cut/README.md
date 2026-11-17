# talking-head-cut

Cut a raw talking-head recording into a clean video. Claude reads the take as numbered lines with the likely
mistakes marked, decides what goes (false starts, failed and repeated takes, notes to the editor, doubled words,
fillers), names it by quoting the words, and the scripts put every cut in silence, shorten long pauses to a breath,
render picture and sound in step, and transcribe the cut again to catch anything left in or clipped.

Status: beta (0.2.0).

## Needs

- Python 3.9+ with numpy
- FFmpeg with ffprobe in PATH (tested on 9.0)
- The EditAtlas transcribe skill and its faster-whisper (for the transcript and for `verify.py`)

## Files

| Path | What |
|---|---|
| `SKILL.md` | The workflow Claude follows |
| `scripts/takes.py` | The take as numbered lines with measured pauses; marks notes to the editor, retakes, false starts, lines that break off and go on, doubled words (with the plan item), fillers, voice with no words and over-long words, and transcribes those last two again on their own |
| `scripts/cut.py` | Turns the plan (lines and quotes to remove) into an edit list: measures where each kept word's sound starts and ends, puts cuts in the quiet, shortens pauses by the pace, aligns edges to the frame grid; writes `cuts.md` and a transcript in the cut film's time |
| `scripts/render.py` | One FFmpeg pass: every piece trimmed and joined with the concat filter, 20 ms fades on the sound at each join, picture and sound lengths compared |
| `scripts/verify.py` | Transcribes the cut again and lines it up with the kept words (extra, missing, doubled, fillers), measures joins and pauses, writes `seams.jpg` |
| `scripts/common.py` | Shared helpers, including `tighten()`, which moves Whisper's word times onto the measured sound |
| `references/formats.md` | Every field of the plan and the output files |
| `references/how-cuts-are-placed.md` | How cuts are placed, and what the check can and cannot catch |
| `evals/` | Test cases in the `claude plugin eval` layout; `make_raw.py` makes the raw takes fresh with Microsoft Edge voices |

## Verified

Five raw takes with known answers. Three are synthetic (`evals/make_raw.py`: Microsoft Edge voices, each line said on
its own and joined with known pauses): a 54 s English tip video, a 49 s Vietnamese one and a 46 s Reels take whose
notes to the editor use words the scripts do not list. Two are real recordings with mistakes spliced in from the
speaker's own voice (each copy resampled by 4 %, so it can be told apart from the original):

- an 88 s English take from Chris Hufnagel's "12 years of freelance advice in under 10 minutes" (YouTube, CC BY),
  with a cafe recording mixed in about 15 dB under the voice: two false starts, two retakes (one the closing line),
  a doubled phrase, two long pauses, and the speaker's own deliberate repeats ("show up... show up");
- a 121 s Vietnamese take from Duy Ngông Kệ's "Truthear Zero Red Review" (YouTube, CC BY, an uncut series): the same
  kinds of mistakes, plus his own hesitations, which may be kept or cut.

The picture carries the source frame number, so sync is measured. A scorer finds every spoken piece in the cut by
waveform correlation and measures what is kept, clipped, left in, the pauses and the sync. Score = share of 7
graders: every kept line present and unclipped, nothing to cut left in, fillers gone, no long pause (1 s; 1.3 s
between lines for the real takes, where an ideal cut measures 0.86 and 1.02 s) and no join without a breath, sync
within a frame, removals named by their words, no claim of having listened. A fresh agent with all EditAtlas skills
ran each take; "without" had every released skill but this one (2026-11-16 and 17).

| Take | Sonnet without | Sonnet with | Haiku without | Haiku with |
|---|---|---|---|---|
| English YouTube take (synthetic) | 0.71, 0.71, 0.86 | 1.00, 1.00, 1.00 | | 0.86 |
| Vietnamese take (synthetic) | 0.86, 0.71, 0.71 | 0.86, 1.00, 1.00 | | 1.00 |
| Reels take, unlisted notes (synthetic) | 0.57, 0.71, 0.71 | 1.00, 1.00, 1.00 | | 1.00 |
| English, real, cafe noise | 0.43, 0.43 | 1.00, 1.00 | 0.57 | 1.00 |
| Vietnamese, real | 0.71, 0.43 | 1.00, 0.86 | 0.29 | 1.00 |

- With the skill, every Sonnet run passed every measured grader. The two 0.86 are replies that said Whisper "listened"
  to the cut ("nghe lại"); 0.2.0 now says how to word it. The Haiku 0.86 removed the deliberate "Never.".
- Without it, on the real takes: a doubled phrase left in, parts of kept lines cut, pauses of 1.2 to 2.9 s left,
  picture and sound 50 to 83 ms apart (2 frames at 24 fps); on the synthetic ones the deliberate "Never." removed and
  46 to 60 ms of drift.
- Cost per run with the skill: $0.14 to $0.20 on Sonnet, $0.01 to $0.02 on Haiku; without, $0.13 to $0.27 on Sonnet.

The real takes found five faults in 0.1.0, fixed in 0.2.0: in a cafe the quiet threshold sat under the noise, so
pauses were not found and a 3 s pause stayed; sound cut off the frame grid drifted from the picture by up to half a
frame per join (66 to 75 ms); `verify.py` stopped on join findings; speech Whisper did not write was cut as if it
were a pause; and a phrase said twice was written once. The Vietnamese real take was run again after the last
change to the marks (`BREAKS OFF`, the plan item on `DOUBLED`); the other rows ran just before it, with the same
scripts for cutting.

Not checked: a person listening to the cuts, music under the voice, two people talking, takes longer than two
minutes, models other than Sonnet and Haiku.
