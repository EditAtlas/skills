# Reading the checks

What `check.py` measures, the thresholds, what each check misses, and how it did on known videos.

All picture checks run on every decoded frame, scaled so its long side is 128 px and turned grey. "Change" is the
mean absolute difference between two frames on a 0–1 scale. A frame time is its index divided by the frame rate,
so on variable-frame-rate files times drift (the `variable_fps` finding warns about this).

## Levels

| Level | Meaning | What to do |
|---|---|---|
| P0 | the render is wrong: size, frame rate, length, sound clipping above +1 dBTP, a missing audio track you asked for | fix the command and render again before anyone looks |
| P1 | a viewer will notice | fix it, or declare it as planned (`--holds`, `--flashes`, `--audio none`) and say why |
| P2 | worth a look | check the frames; often fine |

A finding is a measurement, not a verdict. A dip to black is "black frames" until you say it is planned.

With `--type`, some codes change level for that kind of video (the old level stays in `check.json` as
`level_default`); `references/video-types.md` says why:

| Type | Raised | Lowered to P2 |
|---|---|---|
| `tutorial` | | `still`, `still_long`, `still_end`, `black_first_frame`, `white_first_frame`, `flash_shot` |
| `talk` | `music_masks_voice` to P0 | `black_first_frame`, `white_first_frame` |
| `promo` | `black_first_frame`, `white_first_frame`, `text_small`, `text_unsafe` to P0; `slow_open`, `abrupt_end` to P1 | |
| `reel` | `black_first_frame`, `white_first_frame`, `text_small`, `text_unsafe` to P0; `slow_open`, `silent_start` to P1 | |
| `film` | | `black_frames`, `white_frames`, `still`, `still_long`, `still_end`, `black_first_frame`, `black_end`, `dead_air`, `silent_start` |

## Checks

| Code | Measured as | Misses or confuses |
|---|---|---|
| `size`, `fps`, `duration`, `pix_fmt`, `pixel_aspect`, `rotation`, `variable_fps` | ffprobe, against `--expect`, `--fps`, `--duration` | Only checked against what you pass; without them only `pix_fmt`, pixel aspect, rotation and VFR are checked |
| `black_frames`, `white_frames`, `black_first_frame`, `white_first_frame`, `black_end` | mean brightness under 0.06 (over 0.94) and spread under 0.03 | A dark scene with a little texture is not "black"; a white page in a design is "white" (declare it) |
| `still`, `still_long`, `still_end` | change under 0.0015 for 1.5 s (P2), 3 s (P1), or 2 s at the end | Film grain or a small moving element (a blinking cursor) keeps a held frame "moving"; a still picture with a slow zoom is not still |
| `one_frame_flash` | one frame that differs from both neighbours (change over 0.03 and 3 times the local median) while the neighbours match each other | Two-frame glitches; a flash that lands on a cut |
| `repeated_frames` | frames identical to the previous one while both neighbours move, over 5% of moving frames; the pattern says how often (one every N frames) and where they come closer together | Cannot tell a low-frame-rate source or animation on twos (expected) from a conversion in the render (a fault); a pattern that changes partway points at the place to look |
| `join_frame` | at a cut, frames that belong to neither shot: two cut-sized changes within two frames (a flash or a stray frame on the join), or a frame just before or after the cut that jumps more than four times the motion of both shots while the step on the other side of the cut is ordinary (a frame from the wrong place in the clip) | A wrong frame that looks like its shot (the next frame of the same take) is not caught; a camera flash on the first frame of a shot is reported (pass `--flashes`); a fast wipe or iris that lands on one frame can be reported. The strip in `cuts_NN.png` shows each one |
| `slow_open` (with `--type reel` or `promo`) | the first second does not change (every step under 0.0015) or is all black or white | A slow zoom on a still picture counts as moving |
| `text_small` (with `--text`) | a text held 0.6 s or more whose font size, scaled to a phone 360 px wide, is under 6.7 px (P1) or 8.7 px (P2): under 1.86% (2.4%) of the frame width, which is 1.05% of the height on 9:16 video and 3.3% on 16:9. The thresholds are take-one's text audit (MIT), which measures on a 360 px wide phone so that tall and wide video are judged by the same eye | Font size, not the drawn letters: a thin or light font at the same size reads worse; key-framed scale is not counted. Capital letters are about 0.7 of the font size, so on a 360 px tile 6.7 px is capitals about 5 px tall |
| `text_brief` (with `--text`) | a text on screen less than 0.4 s + 0.2 s a word (also take-one's rule); P1 under 60% of that. Captions that follow the speech are left out: items with word timings, and cues of up to three words that butt against the next or the last one (within 0.1 s); so is a text that ends in the last 0.3 s | Text burned into the footage, or inside a picture, is not in the layers: the reviewer looks for it on the sheets |
| `text_unsafe` (with `--text`, vertical video) | a text whose centre is in the top 15% or the bottom 25% of the frame | Only the centre: a tall block centred at 74% still reaches under the buttons. Items inside a card are skipped |
| `flash_shot` | a shot under 0.25 s between two cuts | Cut detection is simple (change over 0.08 and 5 times the local median); fast camera moves can look like cuts |
| `loop_repeat`, `loop_jump` (with `--loop`) | change from the last frame to the first against a normal step: the same picture twice, or a jump over 2.5 times a step | Only the seam; the sound at the seam is not checked |
| `no_audio`, `silent_track`, `audio_short` | ffprobe and loudness | Whether silence is wanted |
| `loudness`, `true_peak`, `clipping` | `loudnorm` analysis: integrated LUFS against `--loudness` (±2 LU), true peak over -1 dBTP, over 0 dBTP (over +1 is P0) | Files under about 3 s give unsteady loudness; loudness says nothing about the balance of voice and music: pass `--voice` and `--music` for that |
| `music_buried`, `music_masks_voice` (with `--voice` and `--music`) | `ebur128` momentary loudness every 100 ms on each track; speech is where the voice is within 10 LU of its loud parts; the median music level there against the median voice level: more than 18 LU under, or less than 6 | Needs the two tracks as placed in the mix; music that stops under speech is reported, not flagged; the thresholds come from common mixing practice for beds under a voice, not from listening tests |
| `stem_length` | a `--voice` or `--music` track more than 0.5 s longer or shorter than the video | A track that starts later than 0 s lines up wrong and is not caught |
| `dead_air`, `silent_start` | `silencedetect` at -50 dB for 0.5 s: 2 s or more in the middle, 1 s or more at the start | Quiet room tone above -50 dB counts as sound |
| `abrupt_end` | the last 30 ms louder than -30 dBFS and within 6 dB of the last 0.6 s | A hard ending on a hit may be planned |

What it does not check at all: whether the edit is good, spelling, the size and timing of text that is not in
`--text` (burned into footage or drawn inside pictures: the sheets show it; you look), what the sound is, lip sync,
colour. Say so in `REVIEW.md`.

## The sheets

- `overview_NN.png`: one frame about every 0.5 s or more, up to about 36 frames, each labelled with its time and
  frame number. Vertical video is drawn 360 px wide, the size a phone shows it; landscape 480 px. On vertical video
  dashed pink lines mark 15% from the top and 25% from the bottom, where platform buttons and captions sit.
- `cuts_NN.png`: one row per cut, six frames: the two last frames before the join, the two first after it (marked
  `CUT`), and one about 1/12 s further out on each side; at 24 to 30 fps that is six frames in a row, since a
  one-frame fault sits on one frame and 1/12 s steps would skip it. Frames `check.py` found odd are marked `odd`.
  Vertical video has 4 rows a sheet at 150 px wide, landscape 8 rows at 200 px. At most `--strips` cuts (16): cuts
  with a fault first, then the rest spread evenly, so a long video gives at most 4 sheets.
- `findings.png`: the frame before, at and after each finding that has a place in time, labelled with its code.
  Whole-file findings (loudness, size) have no frames.
- `before_after.png` (with `--before`): the same times from the earlier round and now, side by side.

## Results on known videos (2026-11-11, version 0.1.0)

**17 files made with one known fault each** (FFmpeg test pictures, 8 s, 30 fps): black frames in the middle, black
first frames, a white frame, a stray frame from elsewhere, a 3.5 s freeze, 2.5 s of silence, clipping (+7.4 dBTP),
no audio, yuv444p, 24 fps made 30 fps, audio 3 s short, sound to the last sample, a wrong size, and three loops
(right, last frame equal to the first, cut 20 frames short). Each fault was found with the right code; the clean
file and the right loop gave no findings; no file got a finding it should not have.

**137 finished videos** (125 EditAtlas demo renders and 12 public motion-graphics demos by a design-tool maker):
no crash. What it found, and what it was:

| Finding | Files | What it was |
|---|---|---|
| `no_audio` | 63 | picture-only technique demos: planned; pass `--audio none` |
| `loudness` | 68 | demos not normalized to -14 LUFS: true |
| `clipping` | 7 | true peaks from +0.2 to +4.8 dBTP, including three full-edit demos: true faults |
| `repeated_frames` | 30 | demos made from old films with lower frame rates, and stepped animation: expected |
| black or white frames, first frames | 11 | dips to black or white, an iris, designs that start on a white page: planned |
| `still_long`, `still_end` | 8 | demos made from still pictures, a freeze-frame effect: true, planned |
| `abrupt_end` | 29 | demo clips cut mid-sound: true |

The frames of two of these were opened to confirm (an iris close at 13.1 s, a single take with no cuts); the rest
were judged from the demo's name and recipe.

**A fix round:** on a demo with true peak +2.1 dBTP and -18.1 LUFS, one `loudnorm` pass to -14 LUFS with a -1.5
dBTP target gave -15.3 LUFS and -0.8 dBTP. Round 2 with `--before` reported 4 findings gone and 1 new (true peak
still above -1 dBTP): single-pass `loudnorm` does not hold its peak target, so check again after every fix.

**`fix_sound.py`** limits the peaks at 192 kHz first, low enough to leave room for the gain, then runs two-pass
linear `loudnorm` and measures the encoded file, lowering the ceiling and trying again if the peak is still over.
On four files to -14 LUFS (three demos that clip, from +0.2 to +4.8 dBTP, and one that was already clean) it gave
-14.0 to -14.2 LUFS and -1.6 to -2.4 dBTP; on the +4.8 dBTP demo to -16 and -23 LUFS, -16.0 and -23.0 LUFS. The
+2.1 dBTP demo needed four tries and a -11 dBFS ceiling, so the script warns that the limiter worked hard. It
cannot tell whether the result sounds right: a person still has to listen.

**Peaks the encoder adds (0.2.3).** At AAC 192k the encoder itself raised the peak of bright, noisy sounds such as a
sizzle or ice: on a 12 s sizzle and ice mix the sound was at -1.5 dBTP before encoding and -0.8 after, and up to
+0.8 after harder limiting, because the limiter's work gives the encoder more to overshoot on. The old loop answered
by lowering the ceiling again, down to -22.7 dBFS on that mix (-20.6 on a reel), and the peak stayed over. At 256k the
same sound stayed within 0.1 dB. So the default is now 256k, and when the encoded file is over the script measures the
sound before encoding: if that is over, the ceiling goes down; if not, the bitrate goes up to 320k, and if it is still
over it says by how much the encoder adds and stops. The ceiling also goes down when the loudness falls more than 0.5
LU short, which is the one thing a lower ceiling buys. On that mix: ceiling -19.3 dBFS, -14.4 LUFS, -1.5 dBTP; on an
ordinary kitchen and music mix the result is the same as 0.2.2 (-14.0 LUFS, -2.3 dBTP, one try).

**Music under the voice (0.2.5).** A user said "the music is still too quiet" after an agent mixed a bed at 0.34
gain, ducked it to 0.55 under speech and then normalized the whole mix (2026-11-14). The final loudness was right, so
nothing flagged it. With `--voice` and `--music`, check.py now measures the gap while someone speaks. On test tracks
(pink noise in speech-like bursts and a noise-and-tone bed at four levels) it read 13.4 LU (no finding), 25.4 and 35.3
LU (`music_buried`) and 2.7 LU louder than the voice (`music_masks_voice`); a bed that stops under speech gave a note
and no finding, and a 6 s bed on a 10 s video gave `stem_length`. On a 13.5 s synthetic voice from a TTS model it found
9.5 s of speech and read the gap the same way. Nobody has checked these numbers by ear or on a real edit's tracks.

**Joins, text and long videos (0.3.0, check.py 0.2.0).** 26 planted faults in 25 files (2026-11-17): six at a
cut in film footage (a white frame and a magenta frame on the join, a frame of an earlier shot on the join, a frame
from 6 s later in the next clip just after the join, one from later in the last clip just before it, two wrong frames),
four text faults with the project's text layers (a 9-word caption on screen 0.45 s, the same from an `.srt`, an 18 px
caption on a 1080 px canvas, a caption at 88% of the height) and the 15 files of the 0.1.0 set, rebuilt (the clipping
file is also too loud). check.py 0.2.0 found all 26 with the right code and time and no other finding beyond the
repeated frames of the old film footage, which its clean files show too; 0.1.2 found 15 (none of the joins or texts,
and not the loop that shows its first frame twice: the encoder made that seam 0.0012 against a 0.0006 threshold, now
a quarter of a normal step). Word-at-a-time captions from an `.srt` (0.3 s each, back to back) gave no finding.
On 143 finished videos (the EditAtlas demos, five talking-head takes and 147 s of demos joined end to end) nothing
crashed and every other finding was the same as 0.1.2. `join_frame` first fired in 11 files, all on dissolves and dips
of one to three frames; a frame that is a mix of its neighbours is now left alone (every dissolve and dip was within
0.11 of a mix, every planted fault 0.42 or more off), which left 4 findings in 2 files: a fast move and an iris in a
cartoon, and two ghosted frames where an old film copy blends the shots at a cut, which a viewer can see. On the
147 s file (21 cuts) the strips showed 16 cuts on 2 sheets, 8 images in all; before this version a video with more
than about 100 frames to draw lost its overview and findings sheets (FFmpeg's expression parser), which is fixed.
