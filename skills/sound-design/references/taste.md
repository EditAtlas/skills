# Taste rules, with numbers

Numbers are guides measured on finished work, not laws. A calm picture is allowed its silence; write down why.

## Pace

- **Hook:** for a film whose sound is only SFX, a sound inside the first 2 s. A film with its own music or voice
  already has its hook.
- **SFX-only films are dense:** finished SFX-only reels run about 7–15 gestures per 10 s (median about 11), with a
  median pause between gestures around 0.7 s and the longest hole around 2.5 s. `check.py` flags under 7 or over 15,
  and holes over 3 s.
- **With music or voice:** fewer sounds, about 3–12 per 10 s; holes up to 5 s are fine because the film's own audio
  fills them. Under speech, prefer the moments between phrases.
- Sounds within 80 ms of each other count as one gesture (a layered moment).

## Weight and variety

- One big moment is up to three layers (hit + whoosh tail + small debris), not one very loud file.
- Heavy hits on at most about a third of the gestures; a hit on every cut stops meaning anything.
- The same file more than twice gives the library away. Use the numbered takes of a family (Whoosh Pass 25, 28, 37).
- Interface sounds speak one language: pick one family of pops/ticks/dings for a film and keep it.
- Real objects get real foley: a glass is glass, ice is a clink, a drink is a sip. A UI pop on a physical object
  reads as a cartoon.

## Levels (peak dBFS per role before the film-wide gain)

| role | peak | default anchor |
|---|---:|---|
| hit, impact, boom | -6 | peak |
| cartoon | -13 | peak |
| whoosh, foley, scifi | -12 / -14 / -14 | peak |
| riser, glitch | -14 | riser: end, glitch: peak |
| paper, chime, bell, magic | -15 | chime/bell: start |
| ui, click, pop | -16 | start |
| typing | -18 | start |
| nature | -24 | start |
| ambience (as a sound, not a bed) | -28 | start |

After placing, `mix.py` scales all sounds together: to -16 LUFS when they are the film's only sound, about 3 LU under
the film's own loudness under music, about 8 LU under it when a voice carries the film (`under_voice`). The limiter
holds true peak near -1 dBFS. Per-cue `gain_db` moves one sound inside that balance.

- Equal peaks are not equal loudness: a bright 50 ms tick at -16 dBFS sounds smaller than a 0.7 s whoosh at -12.
  Use `gain_db` when `check.py`'s listen list points at a sound that may be lost.
- A **bed** (one steady, dark, long ambience) sits at -54 dBFS median: at the edge of hearing. In listening tests
  -56 to -50 read as "right", -44 and up as "too loud", no bed as "empty". Only under SFX-only films.

## Sync

- Clicks, pops, taps and appearances land on their audible start; hits and whooshes on their loudest point; risers
  end on the payoff.
- A sound that swells (attack over ~60 ms) placed by its start is heard late. If the moment is the peak, anchor the
  peak.
- One frame at 30 fps is 33 ms. `check.py` measures every sound's real position in the render and flags more.

## Mono

Half of short-form video is heard on one phone speaker. A sound whose left and right cancel loses 6 dB or more in
mono; `mix.py` plays its louder channel in both. `check.py` reports the mix's mono fold-down.

## Sources of these numbers

Pace, bed level and the role table follow the measurements published with Clipwing's real-sfx skill (nine finished
SFX reels, blind listening ladders), restated here in our own words. The role table was adjusted for EditAtlas
categories.
