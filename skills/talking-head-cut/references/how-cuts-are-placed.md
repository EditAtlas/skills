# How cuts are placed, and what the check can and cannot catch

## Measuring the sound

The recording's level is measured every 10 ms. "Quiet" is under whichever is highest: the room's floor (its quietest
5 %) plus 6 dB; the level most of the pauses stay under (80 % of the steps at least 0.15 s from any word) plus 3 dB;
or 35 dB below the typical loudest part of a word. It is never closer than 12 dB to the speech. In a quiet room the
floor decides. In a cafe or a street the noise in the pauses does: with a cafe bed 15 dB under the voice, the old
floor-only threshold sat under the noise, every pause read as sound, and a 3 s pause was kept. `takes.md` prints the
threshold and the speech level.

## Why word times are not trusted

Whisper's words are usually right; its times are often not. On a test take with known timings:

- The first word after a pause started up to 1.1 s early, across the pause and over the tail of the word before
  (one word was given 39.18 s; its voice starts at 40.15 s).
- A word said into a silence it could not place got a 1 s span of silence.
- Word ends were the most reliable: usually within 0.15 s.

An edge placed on such a start cuts the word before it, or leaves a pause in. So `tighten()` in `common.py` splits
the sound into chunks wherever it is quiet for 0.1 s or more, gives each word to the chunk that holds its end
(a word whose end sits in a pause goes to the next chunk, unless half of it, or 0.25 s, lies in the chunk before),
and clips its times into that chunk. A chunk's first word starts and its last word ends exactly where the sound
does. Times inside a chunk stay Whisper's.

## Placing a cut

For every run of kept words:

1. Its start and end are the measured sound edges.
2. The quiet on either side is measured (up to 3 s).
3. At each join, the pause the pace asks for is split: about 55% after the last word (a word's release is quiet
   and is clipped first), the rest before the next word, and more from either side when one side has too little.
4. Each edge moves onto the frame grid when a grid point lies inside the quiet. Every piece is then widened to whole
   frames, and picture and sound are both cut over those frames; the sound outside the measured cut points (under a
   frame) is faded to silence. Picture and sound so stay in step at every join, however many there are. In 0.1.0 an
   edge that could not move onto the grid (a short pause, a cut inside sound) cut the sound off the grid, and each
   such join moved the sound up to half a frame against the picture: 66 to 75 ms after 10 joins on a 24 fps take.
5. A pause between kept words is shortened only when it holds no voice. Sound of 0.15 s or more in one stretch
   inside it is speech Whisper did not write (a Vietnamese test take lost "đương nhiên là típ tai" this way in
   0.1.0), so that pause is kept whole, and `verify.py` then lists the words as EXTRA.
6. When kept and removed words touch with no pause between them (a doubled word said in one breath), the cut goes
   at the quietest 10 ms near the word boundary and is marked "cut inside sound".

`render.py` trims every piece from the source in one FFmpeg pass and joins them with the concat filter. Each join
gets a 20 ms fade out and in on the sound. On the test takes the cut's picture-to-sound offset was the same as the
source's at every kept line (3 to 30 ms, from frame rounding), and the picture and sound lengths were equal.

## What verify.py catches

It transcribes the cut film again (no previous-text conditioning, so repeats are not smoothed away) and aligns the
words with the plan's kept words:

- a removed attempt or note that is still in: EXTRA (on a test cut that left in a note to the editor and a
  doubled phrase, both were found, the doubled one also as DOUBLED);
- a kept word that is gone or clipped beyond recognition: MISSING;
- fillers left in, joins in sound, joins with under 0.08 s of quiet, pauses longer than the pace allows, and a
  picture/sound length mismatch.

## Listening again inside the take

Whisper tidies a repeat away: on a real take, "and that is that, and that is that every single project" came out
once, with "every" stretched to 1.1 s. `takes.py` marks words over three times this speaker's time per letter (and
over 0.9 s) as `LONG WORD?`, transcribes those lines and the `SOUND?` lines again on their own, and shows `HEARD`
when that finds more words. On that take it heard "And that is that- and that is that every single project you do".

## What it cannot catch

- **A clipped consonant that Whisper still recognises.** The word is heard, so nothing is listed. The edges come from
  the measured sound, which is what prevents this, but only a person listening can confirm it.
- **A mistake Whisper did not hear in either pass**, such as a mumbled false start under 0.25 s.
- **Meaning.** Whether the right take was kept, whether a lead-in was needed, whether a "so" was a filler: that is
  your decision in step 4, and the person's.
- **A jump in the picture.** `seams.jpg` shows the frames at each join; you have to look at it.

Always tell the person which of these were not checked.
