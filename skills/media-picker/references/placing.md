# Placing B-roll on the words

`place.py` takes the clips you picked and puts each one on the words it shows. It decides when each clip starts
and ends, which part of it is used, how its colour is moved toward the speaker's shot, and where a box beside the
speaker goes. It does not decide what a clip shows: that is your look at the sheet (step 4).

## Inputs

- `--words`: word times from the transcribe skill (`transcript.json`), on the timeline of the video the B-roll goes
  over. After a cut, use `transcript_cut.json` and the cut video as `--speaker`. Any JSON with `words` of
  `w` (or `word`, `text`), `start` and `end` works.
- `--picks`: `{"clips": [...]}` in timeline order. Each clip: `id`, `file`, `shows` (the words, copied from the
  transcript, from the word the picture should appear on), and optionally `layout` (`cutaway` or `pip`), `word`
  (the index in `words` to start on, when the words are said more than once), `in` (the source second to start
  from, when the sheet shows a better moment than the steadiest one), `max` (the longest this clip may stay).
- `--speaker` (a talking head, whose time is the words' time) or `--voice` (a voice-over with no one on screen).
- `--target` (default 1080x1920), `--fps` (30).

## Timing

| rule | default | why |
|---|---|---|
| Start | 0.1 s before the first word of `shows` (less when the word before ends later) | The picture is there as the word lands. A leading "the", "a", "my" is skipped, so "the fridge" starts on "fridge". |
| Length | 2.0-6.0 s for a vertical frame, 2.5-8.0 s for a wide one (`--min`, `--max`) | Under 2 s a cutaway reads as a flash; short vertical videos cut faster than long wide ones. yap-studio uses 2.5-8 s for its edits. |
| End | the first sentence end after the shown words that keeps the length in range; else the first phrase end; else the next clip; else the last word end before the clip's footage or `--max` runs out | Back to the speaker on a full stop or a breath, never inside a word. A phrase end is a comma, a semicolon, a colon, a dash, or a pause of 0.3 s or more. |
| Between clips | the speaker is back for at least 1.0 s (`--gap`), or the two clips are joined cut to cut | A speaker shot of a few frames between two cutaways looks like a mistake. |
| Overlaps | none: a clip ends at the latest where the next starts | |
| Part used | the steadiest stretch of exactly the placed length with no cut inside (measure.py's shake) | |
| No speaker (`--voice`) | each clip runs to the next one, and the first opens the video at 0 s | Nothing else is under the B-roll. A clip that must then stay over `--max` is flagged: add a clip. |

Every row of `placements.md` says why its clip ends where it does. Flags under "Check" name what to fix.

## Colour

The speaker's shot (or `--match-to`, or the middle of all the picks when there is neither) and the part of each
clip that is used are sampled as the canvas shows them (centre crop to the target frame), converted to CIE Lab,
and summarised by the mean and the spread of L, a and b. The clip is moved `--strength` (0.7) of the way toward the
speaker: each channel's mean shifts by 0.7 of the difference, and its spread is scaled by the ratio of the spreads
to the power 0.7. Caps keep a clip's character: brightness moves at most 20 L, colour at most 8 in a and b, spread
0.8-1.25x in L and 0.75-1.3x in a and b; black and white footage keeps no colour. The move is written as a 33-point
3D LUT (`luts/<id>.cube`) and applied with FFmpeg's `lut3d`.

`ΔE` in `placements.md` is the CIE76 distance between the mean Lab colours of the clip and the speaker, before and
after the move. As a rough guide: under 5 the two look like one scene, 5-10 the change is noticeable, over 10 the
clip stands out.

Measured on 2026-11-17 on 10 Pexels clips against two talking heads shot indoors in warm light: the clips stood
5.1 to 33.6 ΔE from the speaker, mean 21.5; after the grade 1.5 to 21.1, mean 9.3. On the five cutaways whose
graded files FFmpeg wrote, the ΔE measured on the file was within 0.7 of what place.py predicted. Clips shot in
very different light (a cool blue laptop shot, an orange pour-over) stayed 20 to 21 ΔE away because of the caps:
place.py flags those, and the honest fix is another clip or saying so.

## Face and captions

A cutaway hides the speaker, so it cannot cover the face. A `pip` box and captions can. The head box is the face
box made larger: half a face above for hair, a fifth either side, a quarter below for the chin.

- `--face auto` finds the face with OpenCV's bundled Haar cascade every 0.5 s, if OpenCV is installed. It is never
  needed: without it, open `speaker_grid.png` (three frames of the speaker as the canvas shows them, with a line
  every 0.1) and read the box yourself: `--face 0.30,0.18,0.70,0.42`.
- A `pip` box is 45% of the canvas width (then 38%, then 32%) at the clip's own shape, tried top left, top right,
  middle left, middle right, lower left, lower right and top centre; the spot farthest from the head and the
  captions wins, if it is at least `--margin-px` (24) away. If none is, the clip is flagged: make it a cutaway.
- `--captions x0,y0,x1,y1` is where the captions sit. While the speaker shows, place.py checks them against the
  head and says where to move them.

Measured on 2026-11-17 on two 9:16 talking heads (close framing, the face about half the canvas width): the
cascade found the face in 34 and 42 of 45 sampled frames once boxes far from the usual face were dropped, and
the five PiP boxes it placed cleared the head by 253 to 322 px. In fresh agent runs one agent's Python could not
import OpenCV; it read the face box off `speaker_grid.png` and its boxes still cleared the face.

## Into editable-export

`fragment.json` is an `editatlas-project/1` project:

- `V1`: the speaker in pieces with the cutaways between them, back to back, every piece muted;
- `VO`: the voice as one sound from 0 s (`media/voice.m4a`, taken from the speaker or `--voice`), so it carries on
  under the cutaways;
- `B1`: picture-in-picture clips as image items (animated WebP of the graded part, faded in and out over 0.15 s),
  and photos;
- graded copies of the parts used, with 1 s either side so the person can trim, in `media/`.

`package.py build work/place/fragment.json --out result/NAME.edit` makes the package. For captions, build the
speaker's own project with `--captions` first, then place with `--into result/NAME.edit/project.json` and save the
result as the next version (`package.py save work/place/project_with_broll.json --to result/NAME.edit --from 1`).
`--into` splits the footage clips at the cutaways (the second part of a split clip `c1` is `c1-2`, as the studio
names a split), moves the footage's own sound to sound items so it plays on under the cutaways, and puts the B-roll
picture track right above the footage, under the captions. A clip played at another speed loses its sound under a
cutaway; place.py says so.

The colour grade is burned into the graded copies: the studio cannot change it. Say so when you deliver.

## What it was measured on

Two voice-overs made with a Microsoft Edge voice, whose word times are known exactly, over two 9:16 talking heads,
with five B-roll clips each, placed from a Whisper (large-v3-turbo) transcript as an agent would have it, once with
the speaker and once as a voice-over alone (18 placements):

- 16 of 18 start within 0.2 s of their word's true start (mean error 0.09 s); the two misses are 0.22 and 0.31 s
  early, where Whisper put the word early. No clip ends inside a word, and none overlap.
- Snapping a word's start to the sound (the rise of the level after a pause) was tried. On 22 words after a pause
  it halved the error against the true times, but on the 18 placed words it changed nothing that counts: 16 of 18
  within 0.2 s either way, mean error 0.095 s against 0.087 s. It was left out; Whisper's times are used as they
  are.
- Phrase matching takes words spelled differently by Whisper ("noise -canceling" for "noise cancelling") as a
  loose match and says so.
