# Review guide

How to look at a render after `check.py` has measured it: the brief for a fresh reviewer, the tells to look
for, how to write a problem, and the `REVIEW.md` the person receives.

## The brief for a fresh reviewer

Give the reviewer only the sheets and this brief. Leave out the plan, the edit list, the code and what each shot
was meant to show: a reviewer who knows the intention sees the intention.

```
You are checking a video before it is posted. You have only these frame sheets: <paths>.
Each tile is labelled with its time and frame number. On vertical video the dashed pink lines mark the
caption-safe area: platform buttons and captions cover the top 15% and bottom 25%.
The video is for: <platform>, <one sentence: what it is for and who watches it>.

1. For each sheet, describe every tile in one plain sentence, as a stranger would. Do not guess what was meant.
2. Then list problems, worst first, one per line:
   t=<seconds>s · <where on screen> · <what is wrong> → <the exact change>  [P0|P1|P2]
   P0 = broken or unreadable, P1 = a viewer will notice, P2 = polish.
3. Go through the tells below and mark each one seen, not seen, or cannot tell from stills.
4. First word of your answer: ship, fix or rebuild.
No scores out of ten. Do not praise. Do not suggest new ideas the video did not try.
```

When you cannot start a subagent, do step 1 yourself before reading your plan again, and write "one context"
in `REVIEW.md`.

## Tells

These make an edit look assembled by a template or a machine. Each one is a P1 unless the person asked for it.

**Picture and layout**

- The subject is small in the frame at the moment that matters; on a phone the main subject should fill a
  third of the height or more at key moments.
- Text, a logo or a sticker sits under the platform buttons (outside the dashed lines on vertical video), or
  covers a face or the product.
- The first frame is empty, black, or a title on a plain background, where a picture would stop the scroll.
- Every scene is a title over a dark or blurred background; there is no real picture: footage, B-roll or a
  drawing of the thing being talked about.
- The same layout repeats scene after scene (headline at the top, three items below).

**Motion**

- Every element enters the same way (all fade up, all slide up) on every line or every beat.
- Several things move at once with no main one; the eye cannot follow.
- Nothing moves for long stretches while speech goes on (the script reports still stretches over 1.5 s).
- Motion that bounces where the tone is calm, or a spring that wobbles twice.

**Text**

- Slide furniture: progress bars or rails, step counters, "1/3" numbering, checklists, numbered bullets, corner
  labels, all-caps small labels above headings.
- More than about seven words on screen at once in a fast edit, or a line that leaves before it can be read
  twice (as a rough floor: letters ÷ 15 + 1.5 s once it is fully in).
- Captions that change style midway, wrap into three lines, or break a name across lines.
- Numbers, quotes, logos or names on screen that the person did not give you. Check each against the source.
- Emoji used as icons.

**Sound** (from the measurements; nobody here can hear)

- Music not ducked where someone speaks: look for speech segments in the plan against the music level.
- A sound effect on every cut; effects should be few and tied to something seen.
- Music cut off at the end instead of ending on a phrase (the script reports an abrupt end).

**Story**

- A shot you could remove without losing anything. If it can go, it goes.
- The ending trails: more than a second after the last thing that matters.

## Writing a problem

One line each, so the fix can be done without asking:

```
t=12.4s · lower third, left · the name sits under the platform buttons → move it up to 70% of the height  [P1]
t=3.0s · whole frame · one white frame between two shots, not in the plan → remove frame 90  [P1]
t=0.0s · first frame · black → start on the first shot and fade up from it  [P1]
```

A problem without a time and a change is not finished: find the place, or write it under "open questions".
After finding one problem, look for others of the same kind elsewhere in the video.

## REVIEW.md

```markdown
# Review: <file name>

**Verdict:** ready / ready with notes / not ready — <one sentence why>
<!-- ready: no finding left. ready with notes: every finding left is named below, and each P1 left needs something
     you do not have, such as the edit project. not ready: a P0 is left, or a P1 you could fix. -->

## Measured (check.py <version>)
<size> · <fps> fps · <length> s · <LUFS> LUFS · true peak <dBTP> · <cuts per minute> cuts a minute

| Round | Findings P0 / P1 / P2 | Fixed | Still there | New |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |

## Looked at
Reviewer: separate (saw only the sheets) / one context.
<the problems found, in the line format above, each marked fixed or left with the reason; for a finding from
check.py, copy its times and pattern, not only a count>

## Not checked
- Nobody listened to the sound: the music choice, how the mix sounds, whether speech is clear. (Keep this line, translated.)
- Spelling and names on screen: <checked against the source / not checked>.
- Lip sync, colour on a real phone screen.
- <anything else you could not fix or judge>
```
