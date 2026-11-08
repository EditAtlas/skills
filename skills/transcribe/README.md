# transcribe

Transcribe the speech in a video on your own machine with Whisper, with a time for every word. Claude checks the
transcript with you, writes SRT/VTT subtitles, and lists what an edit could cut: long silences, fillers (um, uh, ờ,
ừm) and repeated takes. The checked transcript feeds the [EditAtlas](https://edit.trysometh.ing) caption techniques,
silence and filler removal, and the `verified_transcript` input of every template.

Status: beta (0.1.1).

## Needs

- Python 3.9+ and `pip install faster-whisper` (about 300 MB on disk with its parts; Claude asks before installing)
- FFmpeg with ffprobe in PATH
- About 1.6 GB of disk for the default model, downloaded from Hugging Face on first use. After that it works offline,
  and no audio leaves the machine.

## Files

| Path | What |
|---|---|
| `SKILL.md` | The workflow Claude follows |
| `references/models.md` | Model choice, settings, and what was measured |
| `references/formats.md` | `transcript.json` and `cuts.json` |
| `scripts/doctor.py` | What is installed, which model fits; installs faster-whisper when asked |
| `scripts/transcribe.py` | Whisper with word times, review list, subtitles |
| `scripts/fix.py` | Correct words without breaking times; mark the transcript checked |
| `scripts/captions.py` | SRT, VTT and plain text with the EditAtlas caption rules |
| `scripts/cuts.py` | Silences, fillers and retakes; keep list, FFmpeg expressions, transcript in cut time |
| `evals/` | Test cases in the `claude plugin eval` layout |

## Verified

On 2026-11-08, with faster-whisper 1.2.1 on a 12-thread CPU, model large-v3-turbo:

| Film | Word errors | Speech cut | Longest pause left | Closest cut to a word |
|---|---:|---:|---:|---:|
| 34 s Vietnamese, known pauses | 0% | 0 ms | 0.32 s | 80 ms |
| 31 s English, known pauses | every word right | 0 ms | 0.39 s | 80 ms |
| the Vietnamese film with music under it | 0% | 0 ms | 1.42 s (the voice detector heard voice in the music) | 90 ms |
| 6 min 40 s real Vietnamese read speech (FLEURS, CC BY 4.0) | 9.5% (mostly foreign names and terms) | - | - | - |
| 5 min 45 s real Vietnamese talk with music (Spiderum, CC BY) | read by hand: a few misheard words, 60 sentence ends | not measured | - | - |
| 34 s real English talking head | read through, punctuated | - | - | - |

- Word times after a cut: the cut films were transcribed again and the times in `transcript_cut.json` matched with a
  median difference of 10–20 ms.
- Without the settings in `references/models.md`, Whisper invented a closing line on two of these films.

With the skill, fresh agents passed 8 of 8 checks on three test cases (subtitles in Vietnamese, cuts in English, no
file given); without it 7 of 8 (no word times for the film after the cuts), and they took about twice as long
(269 s against 139 s on average).

Not yet checked: real Vietnamese conversation between several people, files over 7 minutes, GPUs, and Windows paths
with spaces.
