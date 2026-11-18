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

## Review list and captions

- Unsure words: on `fleurs_vi` (reference text, 77 wrong words of 913) words under p 0.5 caught 8% of the errors,
  under 0.7 caught 42% with 64% of the flagged words really wrong, under 0.9 caught 71% at 39%. `transcribe.py`
  uses 0.7. Many wrong words have high p ("cãi tay đò" 0.80, "nỡ lòng mạng lời" 0.92), so a person reads the text.
- Caption breaks: before phrase-aware breaks, the 90 s Spiderum clip had captions ending inside two-syllable words
  ("sự / nghiệp", "tất / cả", "sự chính / xác") and lines split "khăng / khăng", "ghi / nhận", "nỗ / lực". After,
  none of those; "tiết / kiệm" on a test film still splits, as there is no dictionary.

## Installing on a fresh machine

Measured 2026-11-08 in an empty Python 3.11 venv with an empty model cache: `doctor.py --install` 34–39 s and 302 MB
on disk (faster-whisper 1.2.1 with ctranslate2, onnxruntime, av, numpy), `doctor.py --fetch turbo` 26–28 s for 1.6 GB.
A fresh agent following the skill asked before installing, installed, and delivered an SRT and its open questions for a 90 s
Vietnamese clip in about 5 minutes.

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

## Word alignment (0.3.0)

`align.py` re-times Whisper's words with a wav2vec2 CTC model on onnxruntime (no torch). Measured on 2026-11-17 on a
12-thread CPU with 4 alignment threads, against:

- six synthetic takes from Microsoft Edge voices with the synthesizer's own word boundaries (two English and two
  Vietnamese paragraphs said without pauses, 32–46 s each; one take per language with 1.2–7 s pauses; 4 min 03 s,
  591 words). Edge's boundary after a pause starts 50–150 ms before the sound, so at pause edges the truth was moved
  to where the level rises above the room tone (+12 dB); the level-based corrections below are partly scored by the
  same kind of measure there;
- edges marked by hand on two real takes (a 14 s English talking head, 23 edges; an 8 s Vietnamese product talk, 17
  edges), read from spectrograms and level lines at about ±15–30 ms: level onset and offset at pauses, the onset of
  hiss for s, sh, f, ch, the release for other stops. Nobody listened.

"Tighten" is the correction talking-head-cut applies to Whisper's times (word edges at pauses moved to measured
sound); "align" is `align.py`. Errors in ms: median / 95th percentile / share over 50 ms.

| English | Whisper | Whisper + tighten | Whisper + align |
|---|---|---|---|
| synthetic, starts inside speech (n 251) | 32 / 103 / 31% | 32 / 107 / 32% | **20 / 61 / 8%** |
| synthetic, ends inside speech | 36 / 88 / 35% | 37 / 89 / 36% | 33 / 68 / 19% |
| synthetic, starts after a pause (n 34) | 323 / 444 / 88% | 5 / 59 / 6% | 9 / 63 / 9% |
| synthetic, ends before a pause | 103 / 230 / 83% | 5 / 164 / 17% | 12 / 110 / 25% |
| real take, starts inside speech (n 12) | 50 / 127 / 50% | 60 / 394 / 50% | **31** / 141 / 33% |
| real take, edges at pauses (n 11) | 250 / 465 / 91% | 30 / 125 / 30% | 27 / 344 / 45% |
| synthetic with cafe noise 21 dB under the voice, starts inside speech | 24 / 70 / 15% | 27 / 106 / 24% | 23 / 46 / 3% |
| the same, starts after a pause / ends before one | 280 / 89% ; 103 / 90% | 5 / 0% ; 25 / 40% | 20 / 22% ; 78 / 100% |

| Vietnamese | Whisper | Whisper + tighten | Whisper + align |
|---|---|---|---|
| synthetic, starts inside speech (n 260) | 24 / 63 / 13% | 24 / 68 / 15% | 40 / 66 / 27% |
| synthetic, starts after a pause (n 28) | 292 / 390 / 96% | 5 / 5 / 0% | 9 / 14 / 0% |
| real take, starts inside speech (n 11) | 35 / 115 / 27% | 35 / 70 / 27% | 39 / 120 / 27% |

In the noisy rows the last two columns give median / share over 50 ms. Under noise the pause edges come from the voice
detector, which lets go of a voice 50–80 ms late, so ends before a pause sit that much after the sound.

So alignment ships for English only. Inside continuous speech it is the only one of the three that moves Whisper's
times closer; at pauses it is about as good as tighten. The CTC letters fire late, so English word boundaries are
moved 40 ms earlier (`EARLY`); that shift was chosen on the synthetic takes and checked on the hand-marked real take
(inner bias +42 ms before, +2 ms after). Vietnamese Whisper (turbo) times inside speech are already good, the
Vietnamese model was later still, and the synthetic and hand-marked takes disagreed on which way to shift it.

Where it goes wrong: on the real English take, in a stretch the model barely recognised ("really fail at, and",
letter scores 0.0–0.43), "and" was laid on the end of "at" before the pause, 0.52 s early (Whisper: 0.25 s early);
three other pause edges ended up 0.11–0.17 s off (Whisper itself was 0.05–0.27 s off on those). On that take 29
of 186 words scored under 0.3. Cuts keep checking every edge against the sound.

### Invented words

Whisper's invented words were placed in every pause of 2 s or more (7 per take): "you" / "Thank you." in English,
"ạ." / "Cảm ơn." in Vietnamese, either as their own segment in the middle of the pause, or added to the end of the
sentence before it (Whisper's usual way), with Whisper-like times.

| Take | 0.2.4 level check | voice detector alone | alignment (score < 0.15 and no voice) |
|---|---|---|---|
| English, own segment | 7 of 7, no real word flagged | 7 of 7, 1 real word | 7 of 7, none |
| English, end of sentence | 2 of 7 | 3 of 7, 1 real word | 4 of 7, none |
| Vietnamese, own segment | 7 of 7 | 7 of 7, 1 real word | 7 of 7, none |
| Vietnamese, end of sentence | 5 of 7 | 6 of 7, 1 real word | 7 of 7, none |
| continuous English / Vietnamese (no pauses) | none flagged | 6 and 1 real words | none |
| English with cafe noise, own segment | 1 of 7 | 7 of 7, 2 real words | 6 of 7, none |
| English with cafe noise, end of sentence | 0 of 7 | 3 of 7, 2 real words | 3 of 7, none |
| real English take (186 words) | - | - | none flagged |

A low score alone is not enough: "eye" (heard as "I") and Vietnamese "ý", "ấy" scored under 0.01 although they were
said, so a word counts as invented only when the voice detector also hears no voice under it.

### Models looked at

Only models already published as ONNX were tried, downloaded at run time from Hugging Face; nothing was converted or
published. Speed is seconds of audio per second of work, 4 threads.

| Model (Hugging Face) | Language | Size | License (and training data) | Result |
|---|---|---|---|---|
| `Xenova/wav2vec2-base-960h`, int8 (5–11x real time; first call includes about 4 s of loading) | English | 95 MB | Apache-2.0 (ONNX copy of facebook/wav2vec2-base-960h; LibriSpeech, CC BY 4.0) | **used** |
| `linandrea/wav2vec2-large-960h-lv60-self-onnx`, int8 | English | 355 MB | no license on the copy; base Apache-2.0 | later (+84 ms inside speech) |
| `Xenova/wav2vec2-large-xlsr-53-english`, int8 | English | 318 MB | Apache-2.0 (Common Voice) | same as base, 3x larger |
| `NewComer00/wav2vec2-xlsr-multilingual-56-ONNX`, q4 | 56 languages incl. en, vi | 248 MB | Apache-2.0 (Common Voice only) | close in English; Vietnamese scores useless (median 0.12) |
| `XDcobra/wav2vec2-large-xlsr-53-vietnamese-ONNX`, int8 | Vietnamese | 355 MB | Apache-2.0 on the card, but trained on VIVOS (CC BY-NC-SA) besides Common Voice and FOSD | measured above, not shipped |
| `dragonSwing/wav2vec2-base-vietnamese` | Vietnamese | 378 MB (PyTorch) | Apache-2.0 on the card; fine-tuned on VLSP data, whose own terms are not stated | no ONNX copy; not tried |
| `nguyenvulebinh/wav2vec2-base-vi-vlsp2020` (WhisperX's default) | Vietnamese | 385 MB | CC BY-NC 4.0 | not usable |
| MMS forced aligner ONNX copies | many | 317 MB int8 | CC BY-NC 4.0 | not usable |
