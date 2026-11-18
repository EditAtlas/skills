# media-picker

Pick background music, stock footage, photos and sound effects that fit the video, check them before they go
into the edit, and place B-roll on the words of a voice-over or talking head.
Claude writes what each slot needs, gathers three to five candidates per slot, measures them with `measure.py`,
looks at a frame sheet of each, drops what does not show the line or breaks the brief, has the person listen to two
or three music options first, and writes an `ASSETS.md` with the picks, the reasons, the dropped candidates and the
credits. When Claude makes the edit, `place.py` puts each clip on the word it shows, uses its steadiest stretch,
grades it part of the way toward the speaker's colour, keeps picture-in-picture boxes and captions off the face, and
writes the result as an editable-export project.

Status: beta (0.3.0).

## Why

Notes users sent through `send_feedback` between 2026-11-10 and 2026-11-13 named the same gap: a stock search was
used as the pick. B-roll for "stepping on a scale" came back as a cat on a bench and a lizard; a shaky handheld pan,
made worse by a tight 9:16 crop, went into a screen-replacement shot; a Christmas track went under a beauty ad that
wanted a romantic Paris feel; a beatless drone went under a calm documentary opening and the person asked for the
music of their earlier videos. In the usage log of the same weeks, 188 of 551 `search_videos` calls and 156 of 510
`search_music` calls were searched again within three minutes.

## Needs

- Python 3.9+ with numpy and Pillow (`pip install numpy pillow`)
- FFmpeg with ffprobe in PATH
- Network access to download candidates, or the files downloaded by the person
- For placing: word times from the transcribe skill. Optional: OpenCV, only if it is already installed, to find the
  face by itself
- Optional: the EditAtlas MCP, for `search_music`, `search_videos`, `search_photos`, `search_sfx` and `send_feedback`

## Files

| Path | What |
|---|---|
| `SKILL.md` | The workflow Claude follows |
| `scripts/measure.py` | Video: size, shake, pan, cuts inside, crop kept for a target frame, smallest file for the edit, steadiest stretch, brightness and colour, a six-frame sheet with the crop outlined. Photo: crop, size, brightness, a sheet. Music: length, loudness and range, tempo and beat strength, hits a minute, intro, ending, brightness, an energy strip. SFX: hit time, tail, level. Across items: the same shot twice, a clip whose light stands apart |
| `scripts/place.py` | B-roll on the words: start 0.1 s before the word, 2-6 s (2.5-8 s wide), end at a sentence or phrase end, no overlaps, at least 1 s of speaker between cutaways; steadiest stretch; colour match in Lab with a LUT; PiP boxes and captions off the face; editable-export fragment or merge, and an optional plain MP4 |
| `references/placing.md` | How place.py times, grades and frames each clip, its options, the hand-off, and what it was measured on |
| `references/fit-guide.md` | The brief and `ASSETS.md` templates, what to look for per kind, music starting points by video type, the message that asks the person to choose |
| `references/reading-the-numbers.md` | Every number, its thresholds, what it was measured on and where it is wrong |
| `evals/` | Test cases in the `claude plugin eval` layout; inputs are downloaded from Pixabay or found by the agent |

## Verified

### 0.3.0: placing (2026-11-17, `place.py` 0.1.0)

Two voice-overs read by a Microsoft Edge voice (so every word's true time is known) over two 9:16 talking heads,
a cold brew how-to with five cutaways and a desk setup with five picture-in-picture clips, five Pexels clips each.
`place.py` worked from a Whisper large-v3-turbo transcript, as an agent would, with the speaker and as a voice-over
alone:

- Timing, 18 placements: 16 start within 0.2 s of their word's true start (mean error 0.09 s; the two misses are
  0.22 and 0.31 s early, where Whisper put the word early). No clip ends inside a word; none overlap.
- Colour, 10 clips against the speaker: ΔE (CIE76 of the mean Lab colour) 5.1 to 33.6, mean 21.5, before the
  grade; 1.5 to 21.1, mean 9.3, after. Measured again on the five graded files FFmpeg wrote: within 0.7 of the
  prediction. Two clips shot in very different light stay about 20 away and are flagged.
- Face: OpenCV found the face in 34 and 42 of 45 frames; the five PiP boxes cleared the head by 253 to 322 px.
- Hand-off: the fragment and a project merged with `--into` (captions built first) both built and passed
  editable-export's `package.py check`.
- Tried and left out: snapping each word's start to the rise of the sound. It halved the error on 22 words after a
  pause, but on the placed words it changed nothing (16 of 18 within 0.2 s either way).

A/B runs on 2026-11-17 and 18: fresh `claude -p` (Sonnet 5.5) agents asked to add the five B-roll clips to each
talking head (cutaways for the cold brew, picture-in-picture for the desk), one arm with 0.2.0 and one with 0.3.0,
two runs each. Every render was measured frame by frame against the speaker: when each clip shows, which clip it
is, the true words said under it, colour against the speaker and how much of the head a box covers.

| | 0.2.0 (4 runs) | 0.3.0 (4 runs) |
|---|---|---|
| Starts within 0.2 s of the noun that names the clip | 11 of 19 | 15 of 18 |
| Noun said from 0.2 s before to 1.5 s into the clip | 19 of 19 | 18 of 18 |
| Clips that end inside a word | 4 (one run) | 0 |
| ΔE to the speaker after the edit, run means | 16.8 to 20.5 | 7.6 to 9.1 |
| Share of the head covered by a PiP box (desk) | 3.8% and 13.1% | 0 and 0 |
| Clips used, of five | 19 of 20 | 18 of 20 |

The desk runs with 0.3.0 left out the laptop-stand clip because it did not show a stand. A separate Sonnet judge
compared each pair of edits from those measurements, twice with the order swapped, a win only if chosen both times:
0.3.0 won 1, tied 2, lost 1. Its reason for the win was colour and the face; in the loss, two clips came in on
their noun late in the sentence ("paper filter", "splash of milk") and it preferred the edit without the skill. The
two ties were the judge picking the same letter both times. Control pairs (an edit placed from the true word times
against a sloppy one) went to the right edit 2 of 2. Tried and left out: advice and a flag to start each clip where
its phrase starts. The judge then gave 2 wins, 2 ties, 0 losses, but clips came in before their noun (12 of 18
within 0.2 s, one 1.1 s early), so 0.3.0 starts on the noun. About 4.20 USD for all agent and judge runs.

### 0.2.0: picking

On 2026-11-14, `measure.py` 0.1.0:

- Camera shake: 15 clips with a known added shake (2 to 16 px at 640 px wide) read in step with it (about 0.5 to
  3.6). On 40 real Pexels clips, 18 of 20 found with steady searches read under 0.15 and handheld walking clips
  read 0.25 to 2.9. Two slow-motion pours where the liquid fills the frame read 0.75 and 2.0: the skill tells
  Claude to judge those by eye.
- Music: 18 Pixabay tracks from six searches. Calm documentary beds measured darker (386 to 506 Hz) than upbeat,
  corporate and jingle tracks (1,200 to 3,000 Hz); beatless drones and a sparse piano were flagged as having no
  steady beat. A key and mode estimate was tried and dropped because it called a piano piece and two "Jingle Bells"
  versions keyless.

A/B runs on 2026-11-14: fresh `claude -p` (Sonnet 5.5) agents connected to the production EditAtlas MCP, one arm with
only this skill and one without, graded by a separate Sonnet judge on each case's graders:

| case | without skill (2 runs) | with, first draft (2 runs) | with, second draft (2 runs) | with, final as media-picker (2 runs) |
|---|---|---|---|---|
| music-paris-ad | 0.20, 0.40 | 0.80, 0.60 | 1.00, 1.00 | 0.80, 1.00 |
| broll-weight-loss-short | 0.00, 0.20 | 0.60, 0.80 | 1.00, 0.80 | 1.00, 1.00 |
| calm-opening-music-disliked | 0.25, 0.50 | 0.75, 1.00 | 1.00, 1.00 | 1.00, 1.00 |
| no-brief-given (1 run) | 0.00 | 1.00 | 1.00 | |

The skill was first named asset-check and renamed media-picker, since it works before the edit and video-check
after the render. Renamed with a description that began "Pick ...", it loaded on "Tìm nhạc nền cho video giúp mình"
in 1 of 5 runs; with "Find and pick ..." and "tìm nhạc nền" and "find background music" among its trigger words, in
5 of 5, and in all 6 runs of the three cases above. The one miss in the final round offered four tracks instead of
two or three.

Without the skill, agents offered the first search results without downloading or measuring them, and wrote their
own words for how tracks sound. The first draft's misses (its own mood words for tracks, credits and dropped
clips only in `ASSETS.md`, no question about the person's earlier music, half a line called a fit) were fixed in
the final text. The one miss left: for "salad with chicken" no candidate showed both, and the agent said so and
offered two short shots. The four B-roll files of one final run were measured again: 1080x1920, shake 0.0 to 0.1,
and the scale clip shows a foot stepping onto a scale. About 7.50 USD for all agent runs.

For beta, on 2026-11-14:

- Installed from the marketplace (`claude plugin marketplace add EditAtlas/skills`, then
  `claude plugin install media-picker@editatlas-skills`) into a clean config: enabled, and the installed files match
  the repo. The A/B runs below used those installed files.
- Opus 5.5 and Haiku 5.5, one run each, with only the skill and without it (table below).
- Opus's B-roll miss: a salad clip only on Pexels at 1920x1080 was cropped to 9:16 and scaled up 1.78x, above the
  1.5x the guide allows; it told the person the clip might look soft. Two of Haiku's Paris misses were the judge's:
  it read the tool results cut at 2,500 characters and called a track that was in them unseen.
- Haiku did not load the skill for the B-roll case, so 0.2.0 leads its description with B-roll and says to use it
  before `search_videos` or a Pexels download. Haiku loaded it for the B-roll case in 3 of 5 runs before and 4 of 4
  after (scores 0.40 to 1.00); for music-paris-ad in 5 of 5 before and 4 of 5 after. Sonnet loaded it in both runs
  with the new description and scored 1.00 on both.
- The owner listened to the music options and watched the B-roll picks of the Sonnet runs and approved them.

| case | Opus without | Opus with | Haiku without | Haiku with |
|---|---|---|---|---|
| music-paris-ad | 0.40 | 1.00 | 0.20 | 0.60 |
| broll-weight-loss-short | 0.40 | 0.60 | 0.00 | 0.20 (skill not loaded) |
| calm-opening-music-disliked | 1.00 | 1.00 | 0.25 | 1.00 |
| no-brief-given | 0.00 | 1.00 | 0.00 | 1.00 |
