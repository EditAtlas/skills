# Choosing a model, and what was measured

All numbers below were measured on 2026-11-08 with faster-whisper 1.2.1, int8 on a 12-thread CPU (no GPU),
with the settings `transcribe.py` uses. Test films:

- `vi_tips`, `en_tips`: 31–34 s of synthetic speech (Microsoft Edge voices) with known words, pauses of 0.5–1.6 s
  placed exactly, two fillers each and one repeated sentence.
- `vi_tips_music`: `vi_tips` with a music bed about 9 LU under the voice.
- `say-no-story`: 34 s of a real person talking fast (3.7 words a second), English, from the EditAtlas
  template previews.
- `fleurs_vi`: 30 sentences of real Vietnamese read speech, 6 min 40 s, from Google's FLEURS set (CC BY 4.0), with
  the reference text.
- A real 5 min 45 s Vietnamese talk with music under it (Spiderum, "Những kinh nghiệm cho người mới đi làm", YouTube,
  CC BY). No reference text; read through by hand.

## Models

| Model | Download | Speed (x real time) | Word errors, Vietnamese | Word errors, Vietnamese + music | English |
|---|---|---:|---:|---:|---|
| `small` | 0.5 GB | 4–5x | 9.3% | 10.5% | 1 word wrong ("twice" heard as "price") |
| `turbo` (large-v3-turbo) | 1.6 GB | 1.2–2.2x | 0% | 0% | every word right |

Word errors are counted after writing numbers the same way on both sides (Whisper writes "3", "45", "400ms";
the script said "ba", "bốn mươi lăm", "bốn trăm mi li giây"). small also wrote "EditAtlas" as "Edith Atlas" and
"Edit Applac", and "45 giây" as "45g".

Speed is seconds of audio per second of work: at 1.2–2.2x, a 10-minute film takes about 5–8 minutes.

On real Vietnamese read speech (`fleurs_vi`) turbo got 9.5% of words wrong. Most errors are foreign names and terms
("Bishkek" heard as "BK", "Ehrenstrahl") and a few misheard syllables ("yên" as "y"). On the real talk it wrote
"cãi tay đò" for "cãi tay đôi", "đeo quan điểm" for "đưa quan điểm", "xếp" for "sếp" and "Spyroom" for "Spiderum";
the review list flagged the name but not the others, so a person still reads the text once.

`auto` uses turbo unless the file is over 20 minutes on a CPU. A one-hour interview on this CPU takes about 30–50
minutes with turbo; offer `--model small` if the person needs it faster and will check the review list.
`medium` and `large-v3` are listed by `doctor.py` but were not measured here.

## Settings and why

| Setting | Value | Measured reason |
|---|---|---|
| voice activity detection | on, 500 ms silence step | With the default step, turbo ended `vi_tips` with an invented "Hãy subscribe cho kênh La La School, để không bỏ lỡ những video hấp dẫn" (17% word errors). With 500 ms: 0%. |
| names in the prompt or as hotwords | never | Hotwords dropped punctuation and wrote "400mg"; names in the prompt made turbo add "Cảm ơn các bạn đã theo dõi và hẹn gặp lại" to the film with music (15% errors). Names are matched after instead. |
| English style prompt | "Yes, I agree. It's simple, isn't it? Let's see." | On `say-no-story` the transcript went from 7 lower-case "i" and 4 sentence ends to 0 and 5, and it found the first word "Learn" that was missed without it. In Vietnamese a similar prompt cost a word, so it is English only. |
| `condition_on_previous_text` | on for Vietnamese, off otherwise | On, `say-no-story` (English) lost every sentence end. In Vietnamese it is the other way: on the real talk, sentence ends went from 10 to 60 with the same words (1354 and 1355); `fleurs_vi` 9.7% → 9.5% errors; the test films stayed at 0%. |
| second pass | stretches the voice detector calls voice but with no words are transcribed alone | On `fleurs_vi` the first pass skipped a whole 4 s sentence ("Cà ri có thể khô hoặc ướt…") that the detector had marked as voice; alone it came back right (11.1% → 9.7%). It did not fire on the test films. |
| `hallucination_silence_threshold` | 2 s | No change on these films; it is there for long silences. |
| beam size | 5 | Beam 1 was 15–20% faster with one fewer sentence end on the real film. |

## Known ways Whisper goes wrong

- It invents stock lines from YouTube subtitles in silence, at the end of a file or under music. `transcribe.py`
  flags lines that match a list of them; the list is not complete, and a real outro that says "subscribe" is flagged
  too, so the flag means "check", not "delete".
- With the voice filter on it can skip a whole sentence; the second pass catches stretches of voice with no words.
- It tidies speech: fillers and false starts often disappear. `--verbatim` asks it to keep them.
- It writes numbers, units and brands in its own way and joins or splits words ("Edit Atlas").
- Word times are good to about 20 ms at word starts in clean speech, but a long spoken number written as one word
  ("400ms" for five syllables) can end 0.3–0.4 s early. `cuts.py` checks every edge against the audio level for
  that reason.
