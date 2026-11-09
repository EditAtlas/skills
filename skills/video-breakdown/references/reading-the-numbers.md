# Reading the numbers

`analyze.py` works on small grey frames (about 96 px on the short side) at up to 30 frames a second and on mono
audio at 22 kHz. Everything below is what each field means, how far it was right on videos where the answer was
known, and what to search for in EditAtlas.

## How well it was measured (2026-11-09, version 0.1.0 and 0.2.0)

On the 24 EditAtlas transition demos (two shots joined by one known FFmpeg transition, 16:9, 24 fps):

- The join was found at the right time (within 0.35 s of its middle) in 23 of 24. The miss was a dark blur
  dissolve, which the analyzer called a short zoom transition at the wrong time.
- The kind was right in 17 of 24: cross-dissolve, dip to black, dip to white, push left, slide up, iris open, barn
  doors, and the linear, diagonal, clock, radial, slice, smooth and wind wipes (all as `wipe`), zoom in, squeeze (as
  a wipe from the edges) and distance melt (as a dissolve, which is what it looks like).
- Wrong or vague in 7: cover slide (called a zoom transition), fade through grey (called a cut), horizontal blur
  and pixel dissolve (called wipes), pixelate (`wipe`, side unclear), iris close (a wipe, but "from bottom"
  instead of "edges inward") and the blur dissolve above.
- About one demo in three had one extra join: most are real cuts or dissolves inside the source footage.

On three full EditAtlas edits (17 to 33 s, 5 to 7 shots each):

- Every designed join was found. In the comedy edit the analyzer called a crash zoom a join and an iris a dip to
  black; the frames showed both at once.
- A silent film with heavy exposure flicker produced 14 joins for 5 real ones. **Flicker, strobe, and flashing
  lights over-count joins.** Look at the shots sheet before trusting the count.

On four 9:16 product reels cut on the beat by design (12 to 18 s, 8 to 13 cuts):

- Cuts on the beat: 9 of 9, 10 of 13, 5 of 8 and 0 of 10. In the last one the cuts fall every 0.93 s, two beats
  of a 129 BPM track, while the analyzer fitted a 127.8 BPM grid that drifts off them. So "cuts do not follow a
  beat grid" can be wrong; compare the cut spacing (`pacing.regularity` low, shot lengths alike) with 60/BPM.
- On the drink reel, the four flash cuts checked in the frames (a light frame on each cut) were all called
  `bright flash`.

Speech-like share on three talking-head previews: 0.13, 0.41 and 0.45; on four music-only reels: 0.0. But a 13 s film
phone call with music under it measured 0.0, and a cartoon with music and no words reached 0.3 in some windows. So 0
does not mean nobody talks: captions that follow speech, moving lips and faces turned to each other are the evidence.
For the words, use the `transcribe` skill.

Run time: 9 to 15 s for a 12 to 34 s 720x1280 video on one desktop CPU, sheets included.

## Joins

| Field | Meaning |
|---|---|
| `start`, `end`, `at` | first and last changed frame, and the middle, in seconds |
| `seconds` | length of the join; a cut is one or two frames (0.03 to 0.08 s) |
| `kind` | see below |
| `from` | wipes: the side the new picture comes from, or `center outward` / `edges inward` |
| `moves` | pushes: the direction the picture travels |
| `scale` | snap zoom or punch-in: how much closer the new frame is |
| `blend_fit` | how well the middle frames are a mix of the two pictures (low = a dissolve) |
| `split_share` | share of changed pixels that are clearly one picture or the other (high = a wipe or a shape) |
| `blur_ratio` | sharpness in the middle of the join against the shots on either side (low = blurred) |

| `kind` | What it usually is | Search terms that work |
|---|---|---|
| `cut` | a straight cut | none needed; `cut on beat` if it hits the music |
| `cross-dissolve` | one picture fades through the other | `cross dissolve`, `blur dissolve` |
| `dip to black`, `black flash` | fade through black, or a few black frames | `dip to black`, `fade to black`; check for an iris |
| `dip to white`, `white flash`, `bright flash` | fade through white, or a flash frame on the cut | `white flash transition`, `flash cut` |
| `dip through a flat colour` | fades through grey or a colour | `fade through color` |
| `wipe` + `from` | a line or shape reveals the new picture | `wipe from right`, `iris open`, `barn door`, `clock wipe` |
| `push or slide` + `moves` | the picture travels across the frame | `push left`, `slide up`, `cover slide` |
| `whip or push` | the picture travels and blurs | `whip pan transition` |
| `zoom transition` | scale change across the join | `zoom in transition`; often a crash zoom inside one shot |
| `blur transition` | the join goes soft | `blur transition` |
| `snap zoom or punch-in` | same picture, suddenly closer | `snap zoom`, `punch in` |
| `jump cut` | same scene, small jump | `jump cut` |
| `gradual (...)` | something else: look at the frames | describe what you see |

## Shots

| Field | Meaning |
|---|---|
| `camera` | words built from the numbers below |
| `pan_x_pct`, `pan_y_pct` | how far the content travelled over the shot, in % of the frame width; negative x = moves left (the camera pans right) |
| `zoom` | total scale change over the shot (1.10 = 10 % closer) |
| `fastest_zoom_0_3s`, `fastest_zoom_at` | biggest scale change in any 0.3 s, and when: 1.25 or more is a crash or snap zoom |
| `roll_deg` | rotation; only reported when the fit is clean |
| `shake_pct` | jitter of the picture, % of width; 0.25 or more reads as handheld or added shake |
| `steadiness` | 0 to 1 per axis: 1 = the move keeps one direction; under 0.5 the "move" is jitter or subject motion |
| `fit_residual` | how badly the frame moves as one flat picture; high (0.3 or more) = people or objects move a lot, so camera words are unreliable |
| `activity` | how much the picture changes per frame, any cause |
| `hold` | a run of still frames after movement: a freeze frame, or a subject that stops |
| `speed_change` | motion 4 or more times faster in one part of the shot than another: a speed ramp, slow motion, or just action |
| `look` | median brightness, contrast, saturation, warmth; words for black and white, warm, cool, dark, flat, black bars, dark corners (vignette) |

Search terms: `crash zoom`, `snap zoom`, `slow push in`, `Ken Burns`, `camera shake`, `freeze frame`,
`speed ramp`, `slow motion`, `letterbox`, `vignette`, `teal and orange`, `black and white`, `film grain`.

The camera numbers cannot tell a real camera move from a zoom added in the edit, and they read subject motion as
camera motion when the subject fills the frame. Grain, light leaks, glitches, colour shifts and most filters are
not measured; name them from the frames.

## Overlays

`events`: a moment where one horizontal band (`top`, `upper`, `upper middle`, `lower middle`, `lower`, `bottom`)
changes while the rest of the frame holds. `edge_change` positive means more detail appeared (text or a graphic
in), negative means it went. Word-by-word captions show as a run of events in one band a few tenths of a second
apart. On moving footage, events are missed; on a talking head they also fire when the speaker's hands move into
a band. Check every one in `events.png` or with `frames.py --crop`.

`persistent`: blocks of the frame that stayed the same through at least 60 % of the joins: a logo, a frame, a
fixed caption bar, a burned-in credit.

Search terms: `meme caption`, `word by word pop`, `bouncing words`, `typewriter caption`, `karaoke`,
`tilted sticker`, `lower third`, `callout label`, `progress bar`, `logo watermark`.

On a 4 s vertical ad with a slow push in, analyze.py found 1 overlay event where eight words or titles came in.
The overview sheet (24 frames or more) is where those show; open it before trusting `events`.

Search terms for how text comes in and where it sits: `text behind subject` (Text behind object), `word slides in
with motion blur` (Whip In), `word drops in from above` (Drop Down), `words appear one by one` (Per-Word
Stagger), `bouncing words`, `gradient sweep text` (only for a gradient that moves). EditAtlas has no technique for
a still gradient fill on its own; give its colours in the text style and say so in `gap` if it is the element.

## Text colours and fonts (text_look.py)

`text_look.py` splits a crop into colour clusters and takes as text the clusters that do not touch the crop's
edge. Colours the background shares (white text over a white shirt) only count inside the line of text, found
from rows dense with sharp edges.

- **fill**: the median colour of the text in five bands top to bottom and five left to right. A change of 0.1 or
  more is a gradient; the direction with the larger change names it. "Both axes" is a diagonal gradient, a
  gradient per letter, or words in different colours: look at the crop.
- **outline or shadow**: a cluster that forms the outer layer of the letters. Offset by more than 4 % of the text
  height, it is a shadow. A soft glow often comes out as a thick outline; the halo line says which.
- **halo**: the ring just outside the letters against the background further out: brighter is a glow, darker
  below is a drop shadow.
- **lean**: the shear that makes stems upright, in 2 degree steps. 6 degrees or more is italic or slanted.
- **strokes**: weight is the median stroke width over the text height; contrast is thick strokes over thin. Drawn
  about 100 px tall, brush, marker and casual scripts measured 1.2 to 1.9; Arizonia, Playball, Lobster and Alex
  Brush 2.3 to 4.3; but thin formal scripts (Great Vibes, Pinyon Script, Petit Formal Script) only 1.0 to 1.7,
  because their hairlines are one pixel. So 2.2 or more says thick and thin; a low number does not rule out a
  formal script. A glow thickens the reference's strokes, so its weight reads high.
- **match**: overlap of the letter shapes, scaled to the same box, weighed by stroke contrast and weight. On a
  bold italic title with a gradient and a drop shadow it put Montserrat Black Italic first, which matched letter
  for letter. On a glowing calligraphic script partly hidden by other words, it ranked brush scripts first, the
  same mistake a remake made by eye. Judge scripts by the letters: the capitals, the loops, thick downstrokes.

Where it fails: busy backgrounds in the text's colours (raise `--k`, pick clusters with `--text-clusters`), text
still moving or fading in (pick a later time), text smaller than about 20 px tall (use a higher resolution source).
`--before` takes the frame before the text came in and keeps only what changed; it helps on a still shot and fails
when the camera or the subject moves.

## Audio

| Field | Meaning |
|---|---|
| `lufs` | integrated loudness of the whole video (EBU R128) |
| `silent_share` | share of 50 ms windows under -50 dBFS |
| `speech_like_share` | share of 2 s windows whose voice band rises and falls at syllable rate; a hint only, it misses dialogue under music |
| `music.tempo_candidates` | up to three tempos, strongest first, each refined to 0.1 BPM, with how many cuts land within 70 ms of its beats and how many would by chance |
| `music.cuts_follow_beat` | present when one candidate holds at least 60 % of the cuts and twice the chance rate |
| `transients` | sudden sounds: time, a rough kind from brightness (`low hit or boom`, `hit`, `bright hit or whoosh`, `click, tick or pop`), tail length, `on_beat`, and `near_visual` (a join, overlay event or fast zoom within 0.2 s) |
| `swells` | the level rising steadily 12 dB or more over 0.3 to 2.5 s: a riser, a whoosh into a moment, or a music build |

A transient with `near_visual` is likely a sound effect placed on that moment; one with `on_beat` and no
`near_visual` is likely the music. Drum hits and speech also make transients; the kind is a guess from brightness.
Do not name a sound from these numbers. Suggest an EditAtlas sound for the moment instead (`search_sfx`), and say
it is a suggestion.
