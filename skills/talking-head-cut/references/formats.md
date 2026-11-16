# File formats

Times are seconds. "Source" is the raw recording; "cut" is the rendered cut film.

## plan.json (you write it)

```json
{
  "pace": "natural",
  "fillers": true,
  "remove": [
    {"lines": "6-7", "why": "false start, then 'sorry, start over'"},
    {"lines": "9, 11", "why": "two failed tries"},
    {"quote": "the best part", "line": 12, "nth": 1, "why": "doubled words: the first copy goes"},
    {"quote": "you know what I mean", "near": 41.5, "why": "the speaker trails off and restarts"},
    {"from": 63.2, "to": 63.9, "why": "a false start with no words in the transcript (SOUND? in takes.md)"}
  ],
  "keep": [
    {"quote": "uh", "line": 30, "why": "part of the joke"}
  ]
}
```

| Field | Meaning |
|---|---|
| `pace` | `natural` (default), `tight` or `keep`; see the table below. `cut.py --pace` overrides it. |
| `fillers` | `true` (default): sure fillers (um, uh, er, ah, hmm, ờ, ơ, ừm, ưm...) are removed wherever they are. `false` leaves them. |
| `remove[].lines` | line numbers from `takes.md`: `"5"`, `"5-7"`, `"5, 8"`. The whole line goes. |
| `remove[].quote` | words to remove, as the transcript has them. Case and punctuation are ignored; every word must be there, in order. |
| `remove[].line` | look for the quote only in this line |
| `remove[].nth` | the quote's nth time (from 1) when it is said more than once |
| `remove[].near` | the time of the quote nearest this many seconds into the source |
| `remove[].from`, `to` | a stretch of source time to remove whatever it holds. Only for sound with no words (a `SOUND?` mark); for speech, quote it. |
| `remove[].why` | your reason, in a few words. It is shown in `cuts.md`; write it so the person understands it. |
| `keep[]` | quotes to keep even though they are sure fillers |

Line numbers are only stable for the `takes.json` they came from: run `takes.py` again after a transcript edit, and
check the numbers.

### Pace values

| Pace | Pause left alone up to | Longer pause between sentences becomes | ...inside a sentence | Before first word | After last word |
|---|---|---|---|---|---|
| `natural` | 0.8 s | 0.45 s | 0.25 s | 0.15 s | 0.4 s |
| `tight` | 0.5 s | 0.30 s | 0.18 s | 0.10 s | 0.3 s |
| `keep` | every pause | (unchanged) | (unchanged) | 0.15 s | 0.4 s |

The same pause values apply where something was removed: the join keeps the pause the pace gives, taken from the
quiet on either side.

## takes.json (takes.py)

`lines[]`: `line` (from 1), `first` and `last` (word numbers in `transcript.json`, from 0), `start`, `end` (measured
on the sound), `pause_after` (measured silence after the line), `text`, `marks`. Also `quiet_dbfs` (the level under
which the recording counts as quiet), `speech_dbfs`, `floor_dbfs` and `unheard` (stretches of voice with no words).

## edl.json (cut.py)

```json
{
  "source": "raw.mp4", "fps": 30.0, "width": 1080, "height": 1920,
  "duration_in": 54.2, "duration_out": 30.03, "pace": "natural", "pace_values": {"keep_up_to": 0.8},
  "quiet_dbfs": -50.0,
  "pieces": [{"in": 1.266667, "out": 5.266667, "at": 0.0}, {"in": 6.333333, "out": 7.833333, "at": 4.0}],
  "joins": [{"at": 4.0, "source_from": 5.266667, "source_to": 6.333333, "pause": 0.47,
             "removed": ["Um,"], "why": ["filler"], "inside_sound": false}],
  "removed": [{"from": 5.95, "to": 6.21, "why": "filler", "text": "Um,"}]
}
```

- `pieces`: the source stretches to keep, in order; `at` is where each starts in the cut. Edges sit on the frame
  grid wherever the pause allows, so picture and sound cut at the same time.
- `joins[].pause`: the silence the join keeps, from the last word before to the first word after.
- `joins[].inside_sound`: there was no pause to cut in; listen there.

The EditAtlas studio (editable-export skill) can take `pieces` as the clips of the main track: each piece is the
source file from `in` to `out`, placed at `at`.

## transcript_cut.json (cut.py)

The transcribe skill's `transcript.json` format, with only the kept words and their times moved into the cut film's
time; `segments`, `review` and `edits` are empty and `cut_from` names the source. Word times are the measured ones
(see `how-cuts-are-placed.md`), so caption timing follows the sound. The transcribe skill's `captions.py` writes
subtitles from it.

## verify.json (verify.py)

`findings[]`: `kind` (EXTRA, MISSING, FILLER, DOUBLED, JOIN IN SOUND, NO BREATH, LONG PAUSE, A/V), `at` (cut time),
`source` (source time, when it maps), `text`. `misheard[]`: words heard differently. `joins[]`: each join's measured
quiet and whether it is in sound. `av_diff`: seconds between the picture and sound lengths.
