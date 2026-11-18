# talking-head-cut

Cut a raw talking-head recording into a clean video. Claude reads the take as numbered lines with the likely
mistakes marked, decides what goes (false starts, failed and repeated takes, notes to the editor, doubled words,
fillers), names it by quoting the words, and the scripts put every cut in silence, shorten long pauses to a breath,
render picture and sound in step, and transcribe the cut again to catch anything left in or clipped. With music or
loud noise under the voice, a speech detector (Silero VAD, shipped with faster-whisper) tells pauses from words.
When the same script was recorded several times across files, Claude picks the best take of each line.

Status: beta (0.3.0).

## Needs

- Python 3.9+ with numpy
- FFmpeg with ffprobe in PATH (tested on 9.0)
- The EditAtlas transcribe skill and its faster-whisper (for the transcript and for `verify.py`)
- For music under the voice: the Silero VAD model and onnxruntime that faster-whisper already installs (nothing
  more to add; without them the level alone is used, as in 0.2.0)

## Files

| Path | What |
|---|---|
| `SKILL.md` | The workflow Claude follows |
| `scripts/takes.py` | The take as numbered lines with measured pauses; marks notes to the editor, retakes, false starts, lines that break off and go on, doubled words (with the plan item), fillers, voice with no words and over-long words, and transcribes those last two again on their own. With several files: lines named by file (A12), and the passages said in more than one file with how each take differs |
| `scripts/cut.py` | Turns the plan (lines and quotes to remove; with several files, the takes to use in order) into an edit list: measures where each kept word's sound starts and ends, puts cuts in the quiet, shortens pauses by the pace, aligns edges to the frame grid; writes `cuts.md` and a transcript in the cut film's time |
| `scripts/render.py` | One FFmpeg pass: every piece trimmed and joined with the concat filter, 20 ms fades on the sound at each join, picture and sound lengths compared; pieces from files with another frame rate or size converted to the cut's |
| `scripts/verify.py` | Transcribes the cut again and lines it up with the kept words (extra, missing, doubled, fillers), measures joins and pauses, writes `seams.jpg` |
| `scripts/common.py` | Shared helpers, including `tighten()`, which moves Whisper's word times onto the measured sound, and `voice_levels()`, which adds the speech detector when music is under the voice |
| `references/formats.md` | Every field of the plan and the output files |
| `references/how-cuts-are-placed.md` | How cuts are placed, and what the check can and cannot catch |
| `evals/` | Test cases in the `claude plugin eval` layout; `make_raw.py` makes the raw takes fresh with Microsoft Edge voices |

## Verified

### 0.3.0: music under the voice, several takes in several files

New cases built from the takes below. Music: three tracks from Pixabay (found through the EditAtlas MCP) mixed 6, 12
and 18 LU under the voice of the English real take, the Vietnamese real take and the English synthetic take, the
mistakes still in. Several takes: the English real speaker's script cut into 8 lines and spread over three files
(34, 50 and 28 s; the third at 1280x720, the others 960x540), six of the lines said in two files, one copy faulty (a
stumble, a cut-off mid-sentence, or said twice inside the file); the truth is the take a careful editor would pick. The
scorer was checked first: an ideal cut gets full marks on all ten cases.

Scripts alone, same transcript and plan, 0.2.0 against 0.3.0, over the nine music cases: kept lines whole 162 to 169
of 189; cuts with a pause over 1.3 s 5 to 3 (longest 3.5 to 1.74 s, all three on the English real take). With no
music (the five takes above) `takes.json` and `edl.json` are the same as 0.2.0's, byte for byte. Several takes, with
the expected picks as the plan: 8 of 8 lines, nothing left in, sync within 41 ms, the 1280x720 file scaled to match.

A fresh Sonnet agent with every released skill, 0.2.0 ("base") against 0.3.0 ("new"), two runs each (2026-11-17):

| Case | base | new |
|---|---|---|
| English synthetic, music 6 LU under | 0.71, 0.71 | 1.00, 1.00 |
| English real, music 6 LU under | 0.71, 0.71 | 0.86, 0.86 |
| English real, music 12 LU under | 0.71, 0.57 | 0.71, 0.86 |
| Vietnamese real, music 6 LU under | 0.57, 0.71 | 0.86, 0.86 |
| Three files, eight lines | 0.29, 0.43 | 0.57, 0.57 |

- Blind pairs (a Sonnet judge reads the transcripts of both cuts, asked twice with the order swapped; a win counts only
  if both answers agree): new won 9, tied 0, lost 1. The loss: the judge found one new cut's last section too tight.
- With music, base left a mistake in (Vietnamese), joined lines without a breath and left pauses up to 3.2 s; new
  missed only the drawn-out first word of one line on the English real take (0.75 s), which the scripts also miss with
  the ideal plan.
- Three files: base kept 4 and 5 of 8 lines, left 2 to 3 faulty copies in and rendered at the third file's size, so its sync could not be measured;
  new kept 6 of 8 and both runs made the same choice the truth calls wrong: they finished a take that broke off with
  the end of the sentence from the other file, a change of file in mid-sentence, where the truth uses the take that
  says it whole.
- Cost per run: new $0.14 to $0.53, base $0.14 to $0.64 on Sonnet.

### 0.2.0

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

Not checked: a person listening to the cuts, music at 18 LU under the voice with an agent, real recordings made with
music in the room (the music here was mixed in), two people talking, takes longer than two
minutes, models other than Sonnet and Haiku.
