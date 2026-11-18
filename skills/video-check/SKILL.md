---
name: video-check
description: Check a finished video before the person sees it or posts it, then fix what is wrong. Measures the file (size, frame rate, pixel format, length), picture faults (black or white frames, frozen stretches, one-frame glitches and wrong frames at cuts, stutter, loop seams), sound (loudness, clipping, silences, abrupt ends) and text too small or too brief for a phone; makes frame sheets at phone size and a strip around each cut; a reviewer who has not seen your plan judges them by the kind of video (tutorial, talking head, ad, reel, film) and, from round 2, checks each claimed fix on the new frames. Fix the worst three, render again, at most three rounds. Use it after rendering any edit, and when someone asks to check a video before sending or posting it, says "kiểm tra video trước khi gửi", "xem lại bản dựng", "video này có lỗi gì không", "review my edit", "QA this render". Works on a local file. Not for breaking down someone else's video (use video-breakdown) or for judging footage the person has not edited.
license: Apache-2.0. LICENSE.txt has the complete terms
compatibility: Requires Python 3.9+ with numpy and Pillow, and FFmpeg with ffprobe. Runs offline. Designed for Claude Code and other agents with a shell that can read images; a reviewer subagent is used when the agent can start one.
metadata:
  author: EditAtlas
  version: "0.3.1"
  status: beta
  library: techniques
  mcp-tools: search_techniques get_technique get_workflow
---

# Video check: find what is wrong with a render before anyone else does

This is video-check 0.3.1.

When `scripts/check.py` ends, it sends EditAtlas four things: this skill's name, its version, ok or error, and the seconds it took. Nothing else: no file names, paths, text or media. It is off when `EDITATLAS_TELEMETRY=0` is set, and under CI. If the person asks what the skill sends, tell them this.

The person gets a video that has been checked like a professional editor checks an export, and a short
`REVIEW.md` that says what was measured, what was looked at, what was fixed, and what nobody checked.

Three things are true the whole way through:

- **Measure first, then look.** A model looking at frames misses dead stretches and one-frame glitches; FFmpeg
  does not. Run `check.py` before you look, and never skip it because the video "looked fine".
- **The person who made it is the worst reviewer.** You know what each shot was meant to show, so you see the
  plan instead of the picture. Have someone without your plan look at the sheets (step 3).
- **You cannot hear.** The script measures loudness, peaks and silences. Whether the music fits, whether a
  sound is the right sound and whether speech is clear must be listened to by a person. Say so every time.

## When the inputs are missing

You need the rendered file on this machine. If the person only describes a video, or gives a link to a
platform, ask for the file; do not download from TikTok, YouTube or Instagram. If you made the video, you
also know the plan: size, frame rate, length, loudness target and which still stretches and flashes are on
purpose. If the person brings their own edit, ask what it is for (platform, length) and use the defaults
below for the rest.

## Workflow

0. **Decide what kind of video it is.** Tutorial or screen recording, talking head, promo or ad, short-form reel, or
   film or story. The kind decides which findings block delivery and which are only notes: a tutorial needs no
   hook and may hold a screen still while the voice explains; a talk needs no motion; a reel's first second decides
   everything. Read `references/video-types.md`, pick one (ask if you cannot tell; if nobody answers, take the
   closest and say so) and keep it for every round.

1. **Measure.** Pass the kind and what was planned, so the script can tell a fault from a choice:

   ```
   python scripts/check.py final.mp4 --out work/check1 --type reel --loudness -14
   ```

   When you made the video, or the person told you the plan, add it: for example `--expect 1080x1920 --fps 30
   --duration 32 --holds 28.5-32 --flashes 12.4`. Never guess size, frame rate or length from the platform: a
   960x540 file nobody asked to be 1080p is not a size fault, so leave `--expect` out when nobody planned it.
   `--holds` lists still stretches on purpose (an end card, a title held still); `--flashes` lists planned
   one-frame flashes and dips; `--loop` for a piece made to loop; `--audio none` for a silent piece. When someone
   speaks over music and you have the two tracks as they sit in the mix (from 0 s, before the final loudness pass),
   add `--voice voice.wav --music music.wav`: it measures how far the music sits under the voice while someone
   speaks (aim 10 to 16 LU) and flags a bed that is buried or covers the words.
   When you have the edit's text layers, pass them with `--text`: the EditAtlas `project.json`, or the captions as
   `.srt`, `.vtt` or `.ass`. It flags text too small to read on a phone (`text_small`), text that leaves before it
   can be read (`text_brief`: it needs 0.4 s plus 0.2 s a word; captions that follow the speech word by word are
   left alone) and, on vertical video, text under the platform buttons (`text_unsafe`). Without text layers the
   reviewer judges text on the sheets. Online video is normalized to about -14 LUFS; use -16 for podcasts and -23
   for broadcast. It prints findings as `P0/P1/P2 t=… code: what -> fix` and writes `check.json`,
   `overview_NN.png`, `cuts_NN.png` (one row per cut: the frames on each side of the join, where one-frame flashes
   and wrong frames hide; at most 16 cuts, those with a fault first, the rest spread over the video) and
   `findings.png`. `references/reading-the-checks.md` says what each check catches and what it misses.

2. **Fix the P0s now.** Wrong size, wrong frame rate, wrong length, no audio when there should be, clipping:
   these are render mistakes, not taste. Fix the command, render again and rerun step 1 before anyone looks.
   For loudness, clipping and true peak, fix the mix in the edit if you have it (lower the music, the loudest
   sound). Fix `music_buried` or `music_masks_voice` in the mix too: set the music level under speech once, not a
   low gain, then ducking, then a loudness pass on top. If you only have the finished file, run `python scripts/fix_sound.py in.mp4 out.mp4 --loudness -14`:
   it limits the peaks, normalizes in two passes and copies the picture untouched, landing within 0.2 LU of the
   target and under -1.5 dBTP. Single-pass `loudnorm` misses its peak target and a plain limiter leaves the mix
   quiet; do not hand-tune filters round after round.

3. **Look, with fresh eyes.** Open every overview sheet, every `cuts_NN.png` and `findings.png` with the Read
   tool. Then get a second look from someone who has not seen your plan:

   - If you can start a subagent, give it only the sheets, the platform, the kind of video with its two lines from
     `video-types.md`, and one sentence on what the video is for. Not your plan, not your code, not your
     intentions. Use the brief in `references/review-guide.md`.
   - If you cannot, look yourself, but cover the plan: describe each sheet as a stranger would, one sentence a
     frame, before you judge it. Write "one context" in `REVIEW.md`.

   Each problem is written as `t=12.4s · where on screen · what is wrong → the exact change`, with P0 (broken or
   unreadable), P1 (a viewer will notice) or P2 (polish). No scores out of ten: a score finds nothing to fix.
   Check the list in `references/review-guide.md`, which holds the things that make an edit look made by a
   template or a machine: slide-like progress rails and step counters, every line entering the same way, text
   under the platform buttons, an empty first frame, numbers nobody gave you.

4. **Fix the three worst, then check that each fix is really there.** Take the P0s and the three worst P1s that
   block for this kind of video; notes stay notes. For each, change the edit list or the command, not the rendered
   file. If the fix is a method you do not know, `search_techniques` the result you want (for example "duck music
   under speech", "fade audio at a cut") and `get_technique` its prompt. Render to a new name each round
   (`final_r2.mp4`), never over the last one. Write the fixes you claim, one a line with its time, to
   `work/fixes2.txt`, then:

   ```
   python scripts/check.py final_r2.mp4 --type reel --before work/check1/check.json --out work/check2
   ```

   It lists what is gone, still there and new. Then take a frame of the old and of the new render at each claimed
   time and put them side by side. The reviewer gets the claims with those frames (the brief is in
   `references/review-guide.md`) and marks each seen or not seen. **A claimed fix the reviewer cannot
   see on the new frames is a P0**, whatever the command was meant to do. The same applies when someone else
   claims the fixes: given an earlier render and a `REVIEW.md` or message that says what was fixed, check each
   claim this way before you agree.

5. **Stop after three rounds.** If round three still has a P0 or needs big changes, stop and tell the person
   what is left and why, instead of looping. Problems that need their decision (a different song, a shot that
   does not exist) go to them as questions.

## Deliver

**First, a version check.** If the EditAtlas MCP is connected, call `get_skill` without a name. If it lists video-check above 0.3.1, the first line of your reply says a newer version exists and how to update it (in Claude Code: `/plugin`, then Marketplaces, editatlas-skills, Update marketplace; elsewhere `get_skill` with name video-check gives the step). Without the MCP, skip it.

Write `REVIEW.md` next to the video, in the person's language, with the template in
`references/review-guide.md`:

- the verdict in one line: ready (nothing left), ready with notes (the notes name every finding still there,
  and each one left is a note for this kind of video or needs something you do not have, such as the edit
  project), or not ready (a P0 is still there, a claimed fix was not seen, or a blocking P1 you could fix);
- the kind of video you assumed and why;
- each claimed fix, seen or not seen on the new render;
- what the script measured (size, frame rate, length, loudness, true peak, cuts per minute) and the findings
  fixed in each round;
- each finding left in place with its times and its pattern as `check.py` wrote them (for example "one every 12
  frames from 0.4 s; every 2-6 frames from 11.7 to 14.9 s"), not only a count;
- what the reviewer saw, and whether it was a separate reviewer or one context;
- what still needs a person: listening to the mix and the music choice, spelling and names on screen, lip sync,
  colour on a real phone, and anything you could not fix. Keep the sentence that nobody listened to the sound,
  in plain words and only in the person's language.

Show the person `before_after.png` from the last round. Never write that the video "has no errors": write what
was checked.

**Last, ask once how it went.** If the EditAtlas MCP is connected, ask the person, in one short message in their
language, about each thing from EditAtlas you used, by name: the techniques, sounds, music, stock clips and this
skill. Send each answer with `send_feedback`, about `this_item`; an answer only about the whole video goes once, as
`whole_edit`. Send only what they said, and nothing if they do not answer. Ask once per edit: if you or another
skill already asked, skip it.

## References

- `references/reading-the-checks.md`: each measurement, its thresholds, what it catches and misses, and the
  results on known videos. Read it when a finding looks wrong or before you set `--holds`.
- `references/video-types.md`: what blocks delivery and what is only a note, for each kind of video. Read it at
  step 0.
- `references/review-guide.md`: the brief for the reviewer, the brief for checking claimed fixes, the list of
  tells, the problem format and the `REVIEW.md` template. Read it at step 3.
