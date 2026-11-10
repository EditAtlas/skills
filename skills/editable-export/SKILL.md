---
name: editable-export
description: Give the person an editable copy of a video you made, built from its elements (footage clips, text, graphics, sounds, music), which opens in the EditAtlas studio, a web page with a timeline. There they fix small things themselves and export the MP4 again in their browser, without asking you to edit and re-render. Typical fixes are a sound that comes in a little late, text that sits slightly off, captions that are too small, a typo, a sound that is too loud, or a clip that runs a few frames long. You send the package as an encrypted link that expires after 30 days, or hand over the folder. The copy is optional. Offer it when you deliver a video, and build it only when they want it. Also use it when someone asks for "an editable version", "a project file", a "studio link", to "tweak it myself", "chỉnh lại chút", "tự sửa", "file để sửa", "chỉnh cỡ chữ", or "âm thanh bị trễ" after an edit. It is not a full editor; you cannot add new footage there or change effects that are burned into the clips.
license: Apache-2.0. LICENSE.txt has the complete terms
compatibility: Requires Python 3.9+, FFmpeg with ffprobe, and network access to edit.trysometh.ing. render.py needs Playwright (pip install playwright) and Chrome or Edge. share.py needs the cryptography package. The studio needs Chrome or Edge 94+ (WebCodecs); Safari and Firefox are not tested. Works with the transcribe and sound-design skills.
metadata:
  author: EditAtlas
  version: "0.1.1"
  status: draft
  library: sfx
  mcp-tools: none
---

# Editable export: let the person fix small things themselves

Here is the result. With the finished video, the person gets the same edit as elements, and opens it in the
EditAtlas studio at `https://edit.trysometh.ing/studio`. The studio shows the video, a timeline and a panel. They
can:

- nudge a sound by a frame, or turn it down
- drag a caption up
- make every caption bigger at once
- fix a typo
- trim a clip
- press **Export MP4**

The MP4 is made in their browser, by the same page and the same drawing code that made the video you delivered.
So what they see is what they get.

Four things stay true the whole way through:

- **It is optional.** Never build it without asking, and never hold the video back for it. Offer it in one line
  when you deliver. Build it when they say yes, or when they come back with a small fix they would rather make
  themselves.
- **Ask before you upload.** A link sends the project and its files, the footage included, to EditAtlas. They
  are encrypted on this machine first and EditAtlas cannot read them, but it is still the person's footage
  leaving their computer. Say that in one sentence and wait for a yes. If they say no, hand over the folder:
  it opens in the studio from disk and nothing is uploaded.
- **Only elements can change.** Anything burned into the footage cannot be moved in the studio, such as text
  drawn with FFmpeg, a graphic rendered into a clip or a grade. So the video you deliver must come from the
  package. If you made it another way, say which parts are fixed.
- **Never invent.** Use only the person's own files and the sounds you placed. A missing source file, such as the
  footage, the font or a sound, is a reason to ask, not to guess.

Scripts are in `scripts/`. Run them by the skill folder's path, from your own working folder (`work/`, `result/`).

```
python SKILL/scripts/package.py build work/project.json --out result/NAME.edit            # project.json + media/
python SKILL/scripts/package.py build work/project.json --out result/NAME.edit \
       --cuts work/cuts.json --captions work/transcript.json --sfx result/FILM_sfx_resolved.json
python SKILL/scripts/package.py check result/NAME.edit
python SKILL/scripts/render.py result/NAME.edit --out result/NAME.mp4                     # the MP4 you deliver
python SKILL/scripts/share.py send result/NAME.edit                                       # the link, after a yes
python SKILL/scripts/share.py pull result/NAME.edit                                       # their newest version
python SKILL/scripts/share.py push result/NAME.edit --note "what you changed"            # your next version
python SKILL/scripts/share.py pull "LINK" --out result/NAME.edit                          # a link they pasted
```

## When the inputs are missing

You need what the video is made of, not only the finished MP4:

- the footage, as you processed it
- the times of the parts kept
- the text and when it shows
- the fonts
- the graphics as image files
- the sounds and music with their times and levels

If you have only a finished MP4 with text burned in, say so. The text, graphics and sound in it cannot become
elements. Offer either to rebuild the edit from its sources, or to package the footage alone with new elements on
top. Ask for a font file when the look depends on one you do not have. Do not swap in a lookalike without saying
so.

## 1. Describe the edit as elements

Write `work/project.json` in the format of `references/project-format.md` (`editatlas-project/1`). In short:

- `canvas`: size and fps.
- `media`: every file by id.
- `styles`: shared looks for text, such as `caption` and `hook`.
- `tracks`, drawn in order:
  - one `video` track of clips back to back (source `in`/`out`, crop, a slow zoom)
  - `text` items
  - `image` items
  - `audio` items (`at`, `in`/`out`, `gain_db`, fades)

**Use the footage you processed, not the raw file.** If you stabilised, graded, denoised, reframed or speed-changed
the footage, point `media` at that result. The package then carries the picture the person saw, and they do not
have to find or upload anything themselves. Keep what should stay adjustable (text, graphics, sounds, the cuts)
out of that file and in the elements.

Let the imports write the long parts:

- `--cuts`: transcribe's `cuts.json` becomes the footage clips (the parts kept).
- `--captions`: transcribe's `transcript.json` becomes caption items with word timing, mapped through the clips.
  Use `--words-per-caption`, `--max-chars` and `--caption-style`.
- `--sfx`: sound-design's `_resolved.json` becomes the sounds, at the frames and levels it rendered.

Rules that make the studio useful:

- **Put repeated looks in a style.** In the studio, a change to a styled item can go to the whole style ("All 42
  caption") or to "This one". Without styles, "make the captions bigger" means 42 edits.
- **Give stable ids**: `c1`…, `cap1`…, and names like `s-ding`. A label (`"label": "YES badge"`) helps the person
  find a sound on the timeline.
- **Use editable text.** Make text a `text` item, not part of an image, so the person can fix typos.
- **Keep motion graphics as elements.** A graphic you animate in code becomes an animated WebP image item (see
  "Motion graphics" in the format reference), not part of the footage, so it can still be moved and retimed.
- **One element per object.** Split a graphic into the things a person might move, retime or hide on their own:
  each card, badge, callout or chart is its own item, cropped to what it covers and placed where it sat, with a
  `label` that names it ("Dream project card", "Slot: booked"). Pieces that always move together stay one item.
  Order the items back to front: later items draw on top. Overlapping items in one track are fine; the studio
  shows them in lanes. Animations hold their last frame, so a card that only slides in is a short file.
- **Words stay text.** Draw a card without its words and put each line on it as a text item with `parent` set to
  the card, so a person can fix a word or a price. Give a card or a word its own motion with `keys` (slide, pop,
  dip, fall) instead of baking it into the picture. See "Cards" and "keys" in the format reference.
- **Add the font file** for every font a style uses. Use fonts you may share: Google Fonts are OFL.
- Keep sound levels as rendered (`gain_db` relative to the file). Nothing is normalised later.

## 2. Build and check

Run `package.py build`. It does the following:

- checks the project, and writes nothing if anything is wrong
- copies the files into `NAME.edit/media/`
- measures each file's duration, size and fps
- writes `NAME.edit/project.json`

Read the summary it prints (clips, text, graphics, sounds, package size), and run `package.py check` on the
folder. A link holds up to 300 MB. If the package is larger, encode the footage smaller before you build:
`ffmpeg -i IN -c:v libx264 -crf 20 -preset medium -c:a aac -b:a 192k OUT.mp4`, keeping the frame rate and a frame
at least as large as the canvas.

## 3. Render the video you deliver from the package

Run `render.py`. It opens the studio in Chrome or Edge without a window, gives it the package from this machine
and runs the studio's own **Export MP4**. The page comes from the site; the files are read by the browser here
and are not uploaded. The output is H.264 at the canvas size and fps, with AAC sound at 48 kHz.

It prints:

- frames and seconds
- MB
- how many frames were read while playing and how many by seeking
- whether the sound was turned down to stop clipping

It runs at about 23 frames per second on a 12-thread PC for a 1080×1920 video, so a 35 s video takes 45 s.

Then check the file before you hand it over:

- `ffprobe` for the duration, size and streams
- frames at a few element times, which you look at with the Read tool:
  `ffmpeg -ss T -i NAME.mp4 -frames:v 1 work/fT.png`
- loudness if it matters: `ffmpeg -i NAME.mp4 -af ebur128 -f null -`

When you already have a video made another way (FFmpeg filters, Remotion), it will not match the studio exactly:
fonts, animations and scaling differ. In that case, either deliver the `render.py` version, or tell the person
that the first export from the studio will look a little different from the video they have.

## 4. Hand it over

Give the MP4 first. Then offer the editable copy, in the person's language, and say what a link means: the
project and footage are encrypted here and sent to EditAtlas, which cannot read them; the link works for 30 days;
anyone who has the link can open it.

**With a yes: a link.** Run `share.py send result/NAME.edit` and give them the whole link it prints. The key is
the part after the `#`. It is stored nowhere else, so a link cut short cannot be repaired: send a new one. `send`
also writes `NAME.edit/.studio-link`, which holds the link and the version you have. It contains the key: never
commit it or paste it anywhere but to the person.

**With a no, or without network: the folder.** They open `https://edit.trysometh.ing/studio` in Chrome or Edge,
press **Choose the folder** and pick `NAME.edit`. The files stay on their computer.

Tell them how the studio works:

1. **Click a thing on the video, or on the timeline, to change it.** The panel on the right has:
   - for text: content, size, colour, position and timing
   - for sounds: frame nudges and level in dB
   - for graphics: position, size and timing
   - for clips: trims (what comes after moves with the clip)
2. **Use the keys:**
   - Space plays.
   - ←/→ moves one frame (Shift for 10).
   - ↑/↓ moves the selected text by 2 px (Shift for 20).
   - Delete removes the selected element.
   - Ctrl+Z undoes, and Ctrl+Shift+Z redoes.

   The studio keeps their changes in the browser as they work.
3. **Export MP4** makes the video on their computer.
4. **Continue with Claude** puts their changes on the same link as the next version, asks what you should do
   next, and gives them a message to paste back to you, with the link, what they changed and that note. Only new files are sent; text and timing changes are a few
   KB. The version label next to the title lists every version, theirs and yours. When you save a new version, their open studio shows
   it and offers to open it.
5. **Save** (Ctrl+S) writes the whole package (`project.json` and `media/`) into a folder they choose, then into
   that folder without asking; on a link it also adds their changes as the next version, without a message for you.
   **Export MP4** asks where to save the video before it starts. They can rename the project in the header; the
   new `title` comes to you with the rest of their changes.
   The studio's start screen lists recent project folders, and links they chose to remember, in their browser
   only. To come back later they open the same link (it always shows the newest version) or that folder.

Say what you checked and what you did not. For example: "exported once in Chrome; not tried in Safari".

## 5. Back and forth on the same link

The person can switch between tweaking in the studio and asking you, as often as they like. They paste the
message the studio gave them (a link and a list of changes), or just say they changed something.

1. **Pull their version first.** `share.py pull result/NAME.edit` writes their newest version into the package
   folder and prints who saved it, their note, and every change from what was there: "style caption: size 66 ->
   80", "sound whoosh (s2): at 4.2 -> 4.167". Files you already have are not fetched again. For a link they
   pasted and you have no folder for: `share.py pull "LINK" --out result/NAME.edit`.
2. **Work on the pulled `project.json`.** Their values are now the starting point. Change only what they asked
   for, by id, in `NAME.edit/project.json`. Do not rebuild it from `work/project.json` or any older copy: that
   silently undoes their tweaks. If you must rebuild (new footage, new cuts), carry their changes over from the
   pull summary and say so.
3. **Check and render** with `package.py check` and `render.py`, as in step 3.
4. **Save your version on the same link:** `share.py push result/NAME.edit --note "captions 10% smaller, hook
   moved up"`. The note is shown to them in the studio. Then tell them what you changed; their open studio
   offers your version, and the link they have stays the same.

`push` refuses when they saved a newer version after the one you pulled. Pull again, make your change again on
top of theirs, and push. Use `--force` only when they ask you to replace their version. `share.py versions
result/NAME.edit` lists every version with who saved it and the notes; `pull --version N` gets an older one.

They may also hand back the folder they saved with **Save** instead of a link: it is a whole package, so
`package.py check` it and work from it. If they send only its `project.json`, save it into your package folder, for
example as `NAME.edit/edited.json`, and run `package.py build NAME.edit/edited.json --out NAME.edit`. The media
are already there.

## References

- `references/project-format.md`: every field of `project.json`. Read it before you write one by hand.
