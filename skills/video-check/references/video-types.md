# Judging by kind of video

The same finding blocks one video and is only a note on another. A tutorial that holds a screen still for five
seconds while the voice explains is doing its job; a reel that does nothing in its first second has lost the viewer.
Before you judge, decide which kind this is, write it at the top of `REVIEW.md` ("Type assumed: tutorial, because
it is a 16:9 screen recording with a voice"), and pass it to `check.py --type`, which grades the findings below.

When it is not clear, ask the person; if they are away, take the closest kind and say which you assumed and why.
A vertical edit under 90 s for TikTok, Reels or Shorts is a reel unless it is a talking head or an ad.

**Blocks** means not ready while it is there. **Note** means it goes in `REVIEW.md` and does not change the
verdict on its own. Anything not listed is judged as in `review-guide.md`. Render faults block every kind: wrong
size, frame rate or length, clipping over +1 dBTP, a missing sound track, a one-frame flash or a wrong frame at a
join that nobody planned.

## Tutorial or screen recording (`tutorial`)

The viewer came to learn a step; they wait for it.

- **Blocks:** the text or the part of the screen being explained cannot be read: judge it as `text_small` does, on a
  phone 360 px wide, where a font under about 6.7 px (1.86% of the frame width) blocks and 6.7 to 8.7 px is a note;
  a caption or face cam covers the part being explained; speech cut
  mid-word, clipped or covered by music; a step the voice describes that is not on screen.
- **Note:** no hook; a title card or a plain first frame; long still stretches while the voice talks (a held screen
  is normal); few cuts; no music.

## Talking head (`talk`)

The words are the content.

- **Blocks:** music that covers the words (`check.py` grades `music_masks_voice` P0 here); dead air in the middle;
  captions under the platform buttons or over the mouth; the face cut off by the crop at the moments that matter; a
  jump cut that flashes a frame.
- **Note:** little motion or few cutaways; a black or plain first frame; repeated frames from a phone recording.

## Promo or ad (`promo`)

It has seconds to show the thing and what to do next.

- **Blocks:** a blank, black or still first second (`black_first_frame` P0, `slow_open` P1); the product or brand not
  on screen by the end of the first few seconds; a price, number, offer or name nobody gave you; text too small or
  under the buttons (`text_small`, `text_unsafe` P0); no clear end card or action when the person asked for one.
- **Note:** music choice, pacing taste, transitions.

## Short-form reel (`reel`)

The first second decides whether anyone sees the rest.

- **Blocks:** the first second blank, black or not moving (`slow_open` P1, `black_first_frame` P0); text under the
  platform buttons or too small at phone width (`text_small`, `text_unsafe` P0); a caption that leaves before it
  can be read (`text_brief`); sound that starts late (`silent_start` P1).
- **Note:** a loop seam on a piece not made to loop; the ending trailing by a second; music choice.

## Film or story (`film`)

Pace and silence are choices.

- **Blocks:** frames that do not belong (flashes, wrong frames at joins, a frame from the next shot); sound that
  clips; a missing scene or a cut that drops words.
- **Note:** no hook; dips to black, long holds, fades and silences (`check.py` grades them P2); slow openings; quiet
  loudness on purpose (still say the measured figure); no captions.
