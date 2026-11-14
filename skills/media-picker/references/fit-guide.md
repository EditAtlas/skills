# Fit guide

## The brief (`brief.md`)

One line per slot. Fill what you know from the script, transcript or plan, and ask for the rest once.

```
Video: 30 s lipstick ad, TikTok 1080x1920, romantic Paris feel, voice-over in Vietnamese
Person's own sound or look: none given / "the piano from the last three videos" (file: ...)
Avoid: Christmas and other holidays, other brands' logos, shaky shots (person disliked them before)

| slot | covers                     | must show or sound like          | mood / place / season      | frame     | seconds |
|------|----------------------------|----------------------------------|----------------------------|-----------|---------|
| M1   | whole ad, under the voice  | music, light, no vocals          | romantic, Paris, spring    | -         | 30      |
| B1   | "mỗi sáng mình đi bộ"      | feet walking on a morning street | calm, any city, daylight   | 1080x1920 | 3       |
| B2   | "bước lên cân"             | feet stepping onto a scale       | neutral, home, bright      | 1080x1920 | 2       |
| S1   | logo reveal                | a soft shimmer, under 1 s        | clean                      | -         | 1       |
```

## What to look for

**Stock video and photos**

- What is on screen in the first second: the cut may only show that.
- The subject inside the blue crop box on every frame of the sheet, not only the middle one.
- Steadiness for the use: a slow cutaway or a slowed-down shot needs `shake` under 0.25; a 0.5 s cut on a beat can
  take up to 0.6. Speeding a clip up or cropping it tighter makes shake worse.
- The same light and colour as the shots around it, or a grade that brings it close.
- People: a face looking into the lens, a recognisable person, a place or culture that does not match the video's
  audience. Stock seldom has Vietnamese people, offices or streets; do not pass another country off as Vietnam.
- Text, logos, watermarks, signs in another language.
- Pexels results carry no description, and their `credit_url` may be in another language; only the sheet tells
  you what a clip shows. The order of results is not their fit for your line.

**Music**

- Title, genre and tags against the brief: holiday words ("Christmas", "Jingle", "Xmas", "Halloween"), "epic",
  "trailer", "kids", a place ("Paris", "Tokyo") that the brief does or does not want.
- Length against the section, and how it ends: a track that ends at full level needs a cut on a bar or a fade.
- Intro: how long until it reaches full level. Under an opening that must hit at once, start it later or pick
  another.
- Beat: for cuts on the beat it needs a steady beat (`beat_sure` 0.5 or more). Get the beat grid with
  `beat_grid.py` from the sound-design skill once a track is picked.
- Busy or sparse (`hits_per_min`): under talking, busy drums and melodies fight the voice; a beatless pad with few
  hits can read tense or empty. Neither is wrong on its own: the person listens.
- `has_youtube_content_id`: a YouTube upload may get a claim. Tell the person before they post there.
- `is_ai_generated`: say it; some people and brands do not want it.

Starting points, to search with and to explain a pick, never to replace listening:

| video                         | music that usually fits                                     | usually does not            |
|-------------------------------|-------------------------------------------------------------|-----------------------------|
| calm explainer, documentary   | sparse piano or strings, slow or no drums, short intro      | busy drums, drones with no tune under the opening |
| product ad, unboxing          | steady beat 100-130 BPM, bright, builds within 5 s          | long build, sad minor ballad |
| food, café, lifestyle         | warm acoustic, light percussion, 80-110 BPM                 | heavy bass, aggressive EDM  |
| romantic, fashion, beauty     | soft piano, strings, accordion or jazz for a French feel    | holiday songs, kids' music  |
| tense, mystery, true story    | low pads, pulses, a slow build                              | upbeat corporate            |
| talking head with captions    | quiet bed, narrow loudness range, nothing in the voice's band at full level | vocals, busy leads |

**Sound effects**

- Where it hits (`hit_at`): place the file that much before the moment.
- Its tail against the next sound or cut.
- One family of sounds per video: three different whooshes from three packs sound like a template.

## Asking the person

One message, in their language, short:

```
Mình tìm được 3 bản nhạc cho quảng cáo (30 s, cảm giác Paris lãng mạn). Bạn nghe thử rồi chọn giúp mình nhé:
1. "French Paris Romantic Music" (tên do Pixabay đặt), tác giả ..., nhịp đều khoảng 86 BPM, đủ to từ giây 2, dài 160 s. File: music/347583.mp3
2. "..." – ...
3. "..." – ...
Mình chưa nghe được bản nào: bạn nghe rồi chọn nhé. Mình đã bỏ các bản có tên "Jingle Bells" vì là nhạc Giáng sinh. Bản 2 có thể bị Content ID nếu đăng YouTube.
Nếu bạn có nhạc hay dùng trong các video trước, gửi mình để tìm bản giống vậy.
```

## `ASSETS.md`

```
# Nhạc, cảnh và âm thanh trong video

## Đã chọn
| slot | item (source, id, author) | dùng cho | vì sao | số đo | in-out |
|------|---------------------------|----------|--------|-------|--------|
| M1 | Pixabay 347583 "French Paris Romantic Music", tác giả ... | cả video | bạn chọn sau khi nghe; nhịp đều | 160 s, ~86 BPM, intro 2 s, -11.4 LUFS | 0-30 s, fade 1 s |
| B2 | Pexels 1234567, tác giả ... | "bước lên cân" | đúng hành động, nền sáng | shake 0.08, crop giữ 32%, x1.0 | 2.1-4.1 s |

## Đã bỏ
- Pexels 7654321: một con mèo trên ghế, không phải cái cân.
- Pexels 2345678: cầm tay, rung (shake 0.9), cắt dọc sẽ rung hơn.
- Pixabay 445113 "Jingle Bells": nhạc Giáng sinh.

## Ghi công
- Video: ... (Pexels, link)
- Nhạc: ... (Pixabay, link)

## Chưa ai kiểm tra
- Chưa ai nghe nhạc dưới giọng đọc. Bạn nghe lại trước khi đăng.
- ...
```
