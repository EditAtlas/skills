# Reading the numbers

`measure.py` reads only the file. It never knows what the clip shows or how a track feels.

## Video

| number | what it is | how to read it |
|--------|------------|----------------|
| `shake` | Frames sampled 10 a second at 320 px wide. The camera move between two frames is the median of a phase correlation on each tile of a 3x3 grid, so one moving object does not count as the camera. The camera path is smoothed over one second; `shake` is the root mean square of what is left, in % of the frame width per step. | Under 0.25: steady. 0.25-0.6: slight, fine for short cuts. 0.6 or more: shaky. |
| `pan` | Speed of the smoothed camera path, in % of the frame width a second. | Over 25: a fast move, hard to read in a quick cut. |
| `cuts` | Times where the picture changes at once (a 32-bin brightness histogram changes by more than 0.35 and six times the clip's usual change). | Stock clips are often several shots joined. Use one shot. |
| `crop_keep` | Share of the frame left by a centred crop to `--target`. | A 16:9 clip cut to 9:16 keeps 32%: check the subject stays in the blue box on every frame. |
| `upscale` | How much the crop of the file you measured must be scaled up to fill `--target`. | It depends on the copy: a 640 px preview always needs a lot. The flag names the smallest file that stays within 1.5x; take that size or larger from `video_files` (or the full-size `image_url`) for the edit. |
| `steadiest` | The `--slot`-long stretch with the least shake and no cut. | A starting point for in and out; the sheet may show a better moment. |
| `brightness`, `warmth` | Mean brightness 0-255, and red over blue. | "Across the picks" flags one far from the others: more than 55 in brightness or 0.35 in warmth from the median. |

What it was measured on (2026-11-14):

- 15 clips made by adding a known shake to three steady Pexels clips (2, 4, 8, 16 px at 640 px wide) read
  about 0.5, 0.9, 1.8 and 3.6: the number grows in step with the shake.
- 40 real Pexels clips, 20 found with steady searches (studio product, tripod interview, timelapse, slow-motion
  pour) and 20 with moving ones (handheld walking, running, vlog, concert crowd): 18 of the 20 steady ones read
  under 0.15; the moving ones read 0.01 to 2.9 (some "handheld" results are in fact steady).
- Wrong: two slow-motion pours where the liquid and the pot fill the frame read 0.75 and 2.0 though the camera
  hardly moves. When the subject fills the frame, judge the shake by eye on the sheet.
- Earlier, with one correlation over the whole frame, the same pour read 4.3 and a walking POV 18.

## Music

| number | what it is | how to read it |
|--------|------------|----------------|
| `lufs`, `true_peak`, `loudness_range` | FFmpeg `loudnorm` measure over the first five minutes. | Loudness only matters after mixing; a wide range (over 12 LU) means quiet parts may vanish under speech. |
| `bpm`, `beat_sure` | Tempo from the autocorrelation of an onset curve, folded into 70-180 BPM, and how strong that period is (0-1). | The tempo may be half or double. Under 0.25: no steady beat. For cut points use `beat_grid.py` from sound-design. |
| `hits_per_min` | Peaks of the onset curve a minute. | Compare tracks with each other, not with a fixed line. On 18 Pixabay tracks: a sparse documentary piano 16, drones 52-65, pop and corporate 110-170. |
| `intro_s` | Seconds until a one-second level first comes within 8 dB of the track's 75th percentile. | Over 8 s: the opening feels empty unless the track starts later. |
| `ending` | Whether the last half second is still near full level. | "Ends at full level": cut on a bar or fade. |
| `brightness_hz` | Mean spectral centroid. | Lower is darker and softer (386-506 Hz for calm documentary beds), higher is brighter (1,200-3,000 Hz for upbeat, corporate and jingle tracks). |

Not measured: key, major or minor, mood, instruments, vocals. A key estimate was tried and dropped: on 18 tracks
it called a piano piece and two "Jingle Bells" versions keyless. Read the title and tags, and let the person
listen.

## Sound effects

`hit_at` is the time of the loudest sample; `tail` is how long the sound stays above 1% of that peak; `peak_dbfs`
and `lufs` are its level as a file, before mixing.
