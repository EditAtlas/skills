# File formats

Times are seconds from the start of the file, rounded to milliseconds. Text is UTF-8 in NFC, as Whisper wrote it.

## transcript.json

```json
{
  "source": "D:/work/film.mp4",
  "duration": 33.56,
  "language": "vi",
  "language_probability": 0.998,
  "model": "turbo",
  "device": "cpu",
  "settings": {"verbatim": false, "prompt": null, "names": ["Minh Anh", "EditAtlas"], "vad_min_silence_ms": 500,
               "previous_text": true},
  "checked": false,
  "words": [
    {"w": "Xin", "start": 0.0, "end": 0.32, "p": 0.98},
    {"w": "chào,", "start": 0.32, "end": 0.66, "p": 0.99}
  ],
  "segments": [
    {"start": 0.0, "end": 1.9, "text": "Xin chào, mình là Minh Anh.", "first": 0, "last": 5,
     "avg_logprob": -0.12, "no_speech_prob": 0.01, "compression_ratio": 1.1}
  ],
  "review": [
    {"i": 80, "to": 81, "why": "looks like the name EditAtlas", "fix": "EditAtlas."}
  ],
  "edits": [
    {"set": [80, 81], "from": "Edit Atlas.", "to": "EditAtlas.", "by": "names"}
  ]
}
```

- `words[].w` keeps the punctuation Whisper attached ("chào,"). In Vietnamese a word is a syllable.
- `p` is Whisper's own probability for the word, 0–1; under 0.5 is listed for review. A corrected word gets `p` 1.0.
- `segments[].first` and `last` index into `words`. A segment with `"second_pass": true` was missed by the first pass and transcribed
  on its own; it is in the review list.
- `checked` becomes true only through `fix.py ... checked`, after the person confirmed the text. Any later edit sets
  it back to false.
- `edits` logs every change made with `fix.py`. Each change also rewrites the subtitles and `review.md`, whose word numbers (from 0)
  match `words`.

EditAtlas techniques and templates read `words`: a caption is built from word starts and ends; a template's
`verified_transcript` is this file with `checked` true.

## cuts.json

```json
{
  "source": "D:/work/film.mp4",
  "duration": 33.56, "after_s": 22.28, "saved_s": 11.28,
  "settings": {"min_silence": 0.4, "pad": 0.12, "quiet_dbfs": -53.0, "pauses_found_by": "level",
               "fillers": true, "take_maybe": false, "take_retakes": false},
  "cuts": [
    {"start": 2.12, "end": 2.77, "kind": "silence", "sure": true, "why": "0.89 s quiet (under -53 dBFS)", "taken": true},
    {"start": 7.82, "end": 8.78, "kind": "filler", "sure": true, "text": "Ờ,", "why": "filler", "taken": true},
    {"start": 20.07, "end": 23.6, "kind": "retake", "sure": false, "text": "Cách thứ ba là chọn đoạn quay tốt nhất.",
     "why": "said again at 0:23.7: keep the last clean take, ask", "taken": false}
  ],
  "merged": [{"start": 2.12, "end": 2.77}],
  "keep": [[0.0, 2.12], [2.77, 6.31]]
}
```

- `kind`: `lead` (before the first word), `silence`, `tail` (after the last word), `filler`, `retake`.
- `merged` is what is actually cut, overlapping cuts joined; `keep` is its complement.
- `quiet_dbfs` is null when the voice detector found the pauses (music or noise under the voice).

`ffmpeg_cut.txt` holds the `-vf` and `-af` expressions with one `between()` per merged cut, as the EditAtlas
silence-removal and filler-removal techniques use them. A comment line lists the joins that came from fillers, in the cut film's time, for the
10–30 ms audio fade the filler-removal technique asks for. `transcript_cut.json` is `transcript.json` with the cut words
removed and every time moved into the cut film's time; its `segments` and `review` are empty. Where a cut word
started a sentence, the next word gets a capital; "second, uh, is" becomes "second is".
