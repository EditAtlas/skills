# media-picker

Pick background music, stock footage, photos and sound effects that fit the video, and check them before they go
into the edit.
Claude writes what each slot needs, gathers three to five candidates per slot, measures them with `measure.py`,
looks at a frame sheet of each, drops what does not show the line or breaks the brief, has the person listen to two
or three music options first, and writes an `ASSETS.md` with the picks, the reasons, the dropped candidates and the
credits.

Status: draft (0.1.0).

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
- Optional: the EditAtlas MCP, for `search_music`, `search_videos`, `search_photos`, `search_sfx` and `send_feedback`

## Files

| Path | What |
|---|---|
| `SKILL.md` | The workflow Claude follows |
| `scripts/measure.py` | Video: size, shake, pan, cuts inside, crop kept for a target frame, smallest file for the edit, steadiest stretch, brightness and colour, a six-frame sheet with the crop outlined. Photo: crop, size, brightness, a sheet. Music: length, loudness and range, tempo and beat strength, hits a minute, intro, ending, brightness, an energy strip. SFX: hit time, tail, level. Across items: the same shot twice, a clip whose light stands apart |
| `references/fit-guide.md` | The brief and `ASSETS.md` templates, what to look for per kind, music starting points by video type, the message that asks the person to choose |
| `references/reading-the-numbers.md` | Every number, its thresholds, what it was measured on and where it is wrong |
| `evals/` | Test cases in the `claude plugin eval` layout; inputs are downloaded from Pixabay or found by the agent |

## Verified

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

Not yet: a person reviewing real picks, Opus and Haiku runs, the marketplace install.
