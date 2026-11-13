# project.json: an edit as elements

`project.json` describes a finished short video as the elements it is made of, so the EditAtlas studio can draw
it, let the person change one element, and export the MP4 again. Format id: `editatlas-project/1`.

Everything the studio shows comes from this file. Anything burned into the footage (text you drew with FFmpeg, a
graphic baked into a clip) cannot be changed there. Put text, graphics and sounds here as elements instead.

## Top level

```json
{
  "format": "editatlas-project/1",
  "title": "Saying no",
  "canvas": {"width": 1080, "height": 1920, "fps": 30, "background": "#000000"},
  "media":  { "<id>": { ... } },
  "styles": { "<name>": { ...text properties... } },
  "tracks": [ { ... }, ... ]
}
```

Times are seconds on the timeline (the finished video), unless a field says it is source time. Positions are
fractions of the canvas: `x: 0.5, y: 0.5` is the centre. Sizes in pixels are canvas pixels.

## media

Every file the edit uses, by id. `path` is relative to `project.json` (package.py copies files into `media/`).

| kind | Fields |
|---|---|
| `video` | `path`; package.py adds `duration`, `width`, `height`, `fps`, `has_audio` |
| `audio` | `path`, optional `title`; package.py adds `duration` |
| `image` | `path` (PNG with transparency, JPG, WebP, SVG; or an animated WebP, GIF or APNG for a motion graphic) |
| `font` | `path` (TTF, OTF, WOFF, WOFF2), `family`, optional `weight` (400), `style` (`normal`/`italic`) |

Use fonts you may redistribute (Google Fonts are OFL): the font file goes into the package folder, which the
person keeps and may pass on.

The studio's Font list adds fonts the same way. A font from its set (https://edit.trysometh.ing/studio-fonts/fonts.json:
18 OFL families with Vietnamese, one WOFF2 per weight) comes with all its weights, as
`media/fonts/<Family>-<weight>.woff2` (`Anton-400.woff2`, `BeVietnamPro-900.woff2`); a studio or `share.py pull`
that lacks such a file fetches it from `/studio-fonts/`. A font file of the person's own keeps its file name under
`media/fonts/`, with `family`, `weight` and `style` read from the file.

## tracks

Drawn in order: later tracks are on top. Each has `id`, `kind`, `name`, optional `hidden` (picture) or `muted`
(sound).

### video: the footage, one track, clips back to back

```json
{"id": "V1", "kind": "video", "name": "Footage", "clips": [
  {"id": "c1", "media": "a-roll", "in": 0.40, "out": 5.20, "volume": 1.0,
   "fit": "cover", "x": 0.5, "y": 0.45, "scale": 1.0, "zoom_to": 1.08}
]}
```

- `in`/`out`: source time of the part used. The clip lasts `out - in` on the timeline; clips play one after the
  other with no gaps, so changing one clip's length moves everything after it (and the studio moves the overlays
  that start after it by the same amount).
- The person can split a clip in the studio (the second part gets a new id, `<id>-2`, and the zoom carries on across
  the cut) and change the order of clips. Text and sounds that sit mostly inside a clip move with it; items over
  several clips stay where they are. Read the order and the ids from their version; do not assume your own.
- The person can also copy, paste and duplicate clips, text, graphics and sounds. A copy gets a new id, `<id>-copy`
  (then `<id>-copy-2`, ...), keeps the look and animation, and a copied text has no `words`. Deleting a clip deletes
  the text and sounds that belong to it by the same rule. "Copy look" sets a text's `style` and look fields from
  another text and keeps its words, timing and position, so a text may end up with a different `style`.
- `fit`: `cover` (fill the canvas, crop) or `contain` (whole frame, bars). `x`, `y`: the point of the source kept
  in the centre when it is cropped (0.5 = middle). `scale`: extra zoom (1 = none). `zoom_to`: if given, the zoom
  moves from `scale` to `zoom_to` over the clip (a slow push-in).
- `volume`: the footage's own sound for this clip (0 mutes it).

### text: captions, hooks, titles

```json
{"id": "T1", "kind": "text", "name": "Captions", "items": [
  {"id": "t1", "style": "caption", "text": "Saying no", "at": 0.40, "dur": 0.9,
   "words": [{"at": 0.0, "dur": 0.42}, {"at": 0.42, "dur": 0.48}]}
]}
```

- `at`, `dur`: when it shows. `words`: optional, one entry per word of `text` (split on spaces), times relative
  to `at`; the word being spoken is drawn in `highlight`, and with `reveal: "word"` words appear as they are said.
- `style`: a name in `styles`. Any text property can also be set on the item itself; the item wins. In the studio,
  a change to a styled item can go to the style (every caption at once) or to that item alone.

Text properties (style or item):

| Property | Default | Meaning |
|---|---|---|
| `font`, `weight`, `italic` | `sans-serif`, 700, false | `font` is a `family` from media fonts |
| `size` | 64 | pixels |
| `color` | `#ffffff` | |
| `x`, `y` | 0.5, 0.75 | centre of the block |
| `max_width` | 0.84 | wrap width, fraction of the canvas width |
| `align` | `center` | `left`, `center`, `right` |
| `line_height` | 1.15 | times `size` |
| `case` | none | `upper` |
| `letter_spacing` | 0 | pixels |
| `stroke` | none | `{"color": "#000", "width": 8}` |
| `shadow` | none | `{"color": "rgba(0,0,0,.5)", "blur": 12, "x": 0, "y": 4}` |
| `box` | none | `{"color": "#fff", "pad_x": 24, "pad_y": 12, "radius": 14, "opacity": 1}` |
| `highlight` | none | colour of the word being spoken |
| `reveal` | `all` | `word`: words appear as they are said |
| `in`, `out` | none | `{"type": "fade" / "pop" / "slide-up", "dur": 0.15}` |
| `opacity` | 1 | |
| `rotation` | 0 | degrees |
| `strike` | none | `{"color": "#ff3b30", "width": 6, "at": 0.4, "dur": 0.3}`: a line drawn through the text, line by line, from `at` s after the item starts, over `dur` s |

### image: logos, stickers, graphics

```json
{"id": "G1", "kind": "image", "name": "Graphics", "items": [
  {"id": "g1", "media": "logo", "at": 2.0, "dur": 2.5, "x": 0.5, "y": 0.2, "width": 0.3,
   "opacity": 1, "rotation": 0, "in": {"type": "pop", "dur": 0.2}}
]}
```

`width` is a fraction of the canvas width; the height keeps the image's shape.

**Motion graphics.** A graphic you animate in code (a chart that grows, a line that draws itself, confetti, a
spinner) can stay an element: render it with a transparent background to an animated WebP and use it as an image
item. The studio draws frame n at `at + ` the time the file gives that frame, so it plays in step with the
timeline, in the preview and in the export. The person can then move it, resize it and retime it; what is drawn
inside it is fixed. Two extra fields:

| Field | Default | Meaning |
|---|---|---|
| `loop` | false | repeat the animation for the item's `dur`; otherwise it holds its last frame |
| `from` | 0 | start this many seconds into the animation |

Make one with Pillow (`frames[0].save("chart.webp", save_all=True, append_images=frames[1:], duration=33, loop=0,
lossless=False, quality=80)`) or FFmpeg (`ffmpeg -framerate 30 -i f%04d.png -c:v libwebp_anim -lossless 0 -q:v 80
-loop 0 chart.webp`). Keep each one short and only as large as it shows on screen: a full-frame 1080×1920 animation
of 2 s is about 0.7 MB, a 900×700 chart of 2.5 s about 0.2 MB. Encoders merge repeated frames into one longer
frame; the studio reads each frame's own duration, so that is fine.

Make one file per object, not one for the whole graphic: draw each object on the graphic's canvas alone, crop every
frame to the union of what the object covers (its alpha bounding box over all frames, plus its shadow), and place
the item at the crop's centre: `x = (canvas_x0 + crop_centre_x * scale) / width`, the same for `y`, and
`width = crop_width * scale / width`, where `scale` is how many video pixels one canvas pixel is. Give each item a
`label`. A month panel, its two slots, a card that flies in and a note that replaces it are five items; in the studio
the person can then nudge one slot, hide the note or move the card without touching the rest.

Words on a card are text items inside it (next section), not part of the picture: draw the card without its words,
so the person can correct a word, a price or a name in the studio.

### Cards: text and pictures inside another element

An item with `parent` is drawn inside that item, a card. Put a card's background (an image item, or a text item with
a `box`) on one track and its words on a text track:

```json
{"id": "g-yes", "media": "yes-card", "at": 1.54, "dur": 5.86, "x": 0.5, "y": 0.59, "width": 0.78, "label": "YES card"}
{"id": "yes-title", "parent": "g-yes", "style": "card", "text": "This client project", "at": 1.54, "dur": 5.86,
 "x": 0.26, "y": 0.42, "align": "left"}
{"id": "yes-pill", "parent": "g-yes", "style": "pill", "text": "YES", "at": 1.70, "dur": 5.70, "x": 0.12, "y": 0.5,
 "keys": [{"t": 0, "scale": 0.6, "opacity": 0}, {"t": 0.25, "scale": 1, "opacity": 1, "ease": "back"}]}
```

- `x`, `y` of an item inside a card are fractions of the card's box (0, 0 is its top-left corner, 0.5, 0.5 its centre),
  not of the canvas. For text, `x` is the edge `align` names: the left edge with `left`. Measure them from where you
  drew the words on the card: `x = (word_x - crop_x0) / crop_width`, `y = (line_middle_y - crop_y0) / crop_height`.
- The item moves, scales, turns and fades with its card, `in` and `keys` included. It shows only while its card shows,
  so keep its `at`…`at + dur` inside the card's. One level only: a card cannot be inside another card.
- `max_width` of an item inside a card is still a fraction of the canvas width.
- In the studio, the card's words fold under it on the timeline and show when the card is selected; moving the card
  in time moves them too, and deleting it deletes them.

### keys: motion of one element

Any text or image item can have `keys`, keyframes of its own motion, on top of `in`/`out`:

```json
"keys": [{"t": 0, "dy": 40, "opacity": 0}, {"t": 0.3, "dy": 0, "opacity": 1, "ease": "out"},
         {"t": 2.2, "rotate": 0}, {"t": 2.6, "rotate": -8, "dy": 600, "ease": "in"}]
```

| Field | Default | Meaning |
|---|---|---|
| `t` | | seconds after the item starts; keys in time order |
| `dx`, `dy` | 0 | move, in canvas pixels |
| `scale` | 1 | times the item's size |
| `rotate` | 0 | degrees, added to `rotation` |
| `opacity` | 1 | times the item's opacity |
| `ease` | `out` | how the move into this key runs: `linear`, `out`, `in`, `in-out`, `back` (overshoots, then settles), `step` |

Each field moves only between keys that set it; before its first key it holds that value, after its last key it holds
the last one. Timing that reads as premium: 0.2–0.35 s with `out` for things arriving, `back` for a pop, `in` for an
exit, and a hold of at least 0.5 s between moves. A card's keys carry its words with it.

### audio: sound effects and music

```json
{"id": "A1", "kind": "audio", "name": "Sounds", "items": [
  {"id": "s1", "media": "pop", "at": 2.68, "in": 0.0, "out": null, "gain_db": -14.0,
   "fade_in": 0.0, "fade_out": 0.01, "label": "YES badge"}
]}
```

- `at`: when the file starts on the timeline. `in`/`out`: the part of the file used (`out: null` = to its end).
- `gain_db`: applied to the file as it is (0 = the file's own level). No normalising happens later: what plays in
  the studio is what is exported.

## Ids

Every clip and item has an `id` unique in the project. Keep ids stable when you rebuild a project, so a person's
saved changes still match.

## The package folder and its versions

```
NAME.edit/
  project.json          the newest version's project: what the studio opens and render.py renders
  media/...             every file any version uses; nothing is ever deleted from here
  versions/v1.json      one file per version: 1, 2, 3 ... with no gaps
```

```json
{"format": "editatlas-version/1", "version": 2, "parent": 1, "by": "studio", "name": "", "note": "captions bigger",
 "made": "2026-11-10T12:00:00.000Z", "project": { ...the whole editatlas-project/1 object... }}
```

- `parent`: the version the writer opened and changed (`null` for version 1). Usually n-1; lower when someone saved
  from an older version.
- `by`: `agent` (written by `package.py`) or `studio` (the person). `name`: the agent's name, `""` for the studio.
- `note`: at most 500 characters. From the studio, what the person wants next; from the agent, what it did.
- `made`: ISO 8601 UTC. Media paths in `project` are relative to the folder (`media/...`).
- A writer writes `versions/v<n>.json` first, then `project.json`, and never overwrites a version file. If the
  newest version is higher than the one it opened, it refuses unless forced; forced, it still writes newest + 1,
  with `parent` = the version it opened.
- A folder with `project.json` and no `versions/` (made before versions) counts as version 1; the first save writes
  it as `versions/v1.json` first.

## The light link (optional)

`https://edit.trysometh.ing/studio#<id>.<key>` holds the same versions, with the same numbers, and nothing else: no
media. `share.py send` makes it, `push` adds the folder's newer versions, `pull` writes the link's newer versions
into the folder. Links have no end date for now (`expires` is null). `NAME.edit/.studio-link` is
`{"link": "<the whole link>", "version": <the newest version both have>}`; it holds the key, so it never goes into Git
or a message other than to the person.

- On the link, version n is the object `v<n>`: a 12-byte nonce, then AES-256-GCM of gzip of the UTF-8 JSON below,
  with `editatlas-share/2|<id>|v<n>` as additional data. The write token is HKDF-SHA256 of the key (no salt, info
  `editatlas-share/2 write`), sent as a Bearer token.
- The JSON is the folder's version with `"format": "editatlas-share/2"` and a `media` list: every media id the
  project uses, with its path in the folder and its size in bytes, so the studio can check the folder it is given.
- Limits: a version at most 256 KiB encrypted; a link at most 2 MiB and 64 versions.
