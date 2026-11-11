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

## Checks

| Code | Measured as | Misses or confuses |
|---|---|---|
| `size`, `fps`, `duration`, `pix_fmt`, `pixel_aspect`, `rotation`, `variable_fps` | ffprobe, against `--expect`, `--fps`, `--duration` | Only checked against what you pass; without them only `pix_fmt`, pixel aspect, rotation and VFR are checked |
| `black_frames`, `white_frames`, `black_first_frame`, `white_first_frame`, `black_end` | mean brightness under 0.06 (over 0.94) and spread under 0.03 | A dark scene with a little texture is not "black"; a white page in a design is "white" (declare it) |
| `still`, `still_long`, `still_end` | change under 0.0015 for 1.5 s (P2), 3 s (P1), or 2 s at the end | Film grain or a small moving element (a blinking cursor) keeps a held frame "moving"; a still picture with a slow zoom is not still |
| `one_frame_flash` | one frame that differs from both neighbours (change over 0.03 and 3 times the local median) while the neighbours match each other | Two-frame glitches; a flash that lands on a cut |
| `repeated_frames` | frames identical to the previous one while both neighbours move, over 5% of moving frames; the pattern says how often (one every N frames) and where they come closer together | Cannot tell a low-frame-rate source or animation on twos (expected) from a conversion in the render (a fault); a pattern that changes partway points at the place to look |
| `flash_shot` | a shot under 0.25 s between two cuts | Cut detection is simple (change over 0.08 and 5 times the local median); fast camera moves can look like cuts |
| `loop_repeat`, `loop_jump` (with `--loop`) | change from the last frame to the first against a normal step: the same picture twice, or a jump over 2.5 times a step | Only the seam; the sound at the seam is not checked |
| `no_audio`, `silent_track`, `audio_short` | ffprobe and loudness | Whether silence is wanted |
| `loudness`, `true_peak`, `clipping` | `loudnorm` analysis: integrated LUFS against `--loudness` (±2 LU), true peak over -1 dBTP, over 0 dBTP (over +1 is P0) | Files under about 3 s give unsteady loudness; loudness says nothing about the balance of voice and music |
| `dead_air`, `silent_start` | `silencedetect` at -50 dB for 0.5 s: 2 s or more in the middle, 1 s or more at the start | Quiet room tone above -50 dB counts as sound |
| `abrupt_end` | the last 30 ms louder than -30 dBFS and within 6 dB of the last 0.6 s | A hard ending on a hit may be planned |

What it does not check at all: whether the edit is good, text size and spelling, whether text sits in the safe
area (the sheets mark it; you look), what the sound is, lip sync, colour. Say so in `REVIEW.md`.

## The sheets

- `overview_NN.png`: one frame about every 0.5 s or more, up to about 36 frames, each labelled with its time and
  frame number. Vertical video is drawn 360 px wide, the size a phone shows it; landscape 480 px. On vertical video
  dashed pink lines mark 15% from the top and 25% from the bottom, where platform buttons and captions sit.
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
still above -1 dBTP): single-pass `loudnorm` does not hold its peak target, so check again after every fix, and use
two-pass `loudnorm` or a limiter.
