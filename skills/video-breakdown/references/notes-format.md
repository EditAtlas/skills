# notes.json

Your notes turn the measurements into a breakdown. `report.py` checks them and writes the report from them and
from `breakdown.json`. Write them after you have looked at the sheets and searched EditAtlas.

| Field | Required | What |
|---|---|---|
| `lang` | yes | `vi` or `en`: the person's language; it sets the report's headings |
| `title` | no | a short name for the video |
| `summary` | no | two or three sentences: the kind of edit and what makes it work |
| `shots` | yes | one entry per shot in `breakdown.json`: `{"n": 3, "seen": "what is on screen"}` |
| `corrections` | no | where the measurements were wrong ("5.02 s is a crash zoom, not a join: shots 2 and 3 are one") |
| `elements` | yes | everything worth naming, see below |
| `recipe` | yes | steps to make one like it with the person's own footage |
| `not_checked` | yes | what you could not know or did not look at |

Write `seen`, `summary`, `recipe`, `corrections` and `not_checked` in the person's language. Keep technique names
as EditAtlas gives them.

## Elements

| Field | Required | What |
|---|---|---|
| `at` | yes | a time in seconds, or `[start, end]` |
| `kind` | yes | `transition`, `camera`, `text`, `graphic`, `look`, `effect`, `speed`, `sound`, `music`, `voice`, `layout`, `pacing` or `other` |
| `seen` | yes | what happens, in plain words, before any name |
| `evidence` | yes | `measured` (from the numbers only), `looked` (from frames you opened), `measured+looked`, or `guessed` |
| `technique` | one of these two | `{"slug", "name", "match"}` copied from `get_technique`; `match` is `exact`, `close` or `partial` |
| `gap` | one of these two | why there is no technique: "plain cut", or "searched 'paper tear transition', 'ripped paper reveal': nothing close" |
| `sfx` | no | `{"category": "...", "example_id": "sfx-..."}`: an EditAtlas sound you suggest for this moment |
| `note` | no | anything the reader needs: "followed by Iris Open", "the speed is a guess" |

`sound`, `music`, `voice` and `pacing` elements need neither a technique nor a gap. Every other element needs one
of them. Do not put a technique you did not get from EditAtlas in this session; `--check-api` refuses unknown
slugs and names that do not match.

## Example

```json
{
 "lang": "en",
 "title": "Cartoon comedy clip",
 "summary": "A 17 s comedy cut: five cartoon shots, a different join each time, meme captions and a pop on every caption.",
 "shots": [
  {"n": 1, "seen": "White rabbit in a meadow, a pink butterfly; meme caption at the bottom"},
  {"n": 2, "seen": "Squirrel close-up grabbing the butterfly; pink sticker 'THE NEIGHBORS'; fast zoom at the end"},
  {"n": 3, "seen": "Same squirrel shot after the zoom: one shot with #2, split by the crash zoom"}
 ],
 "corrections": ["5.02 s is a crash zoom inside the squirrel shot, not a join."],
 "elements": [
  {"at": 3.98, "kind": "transition", "seen": "Straight cut to the squirrel", "evidence": "measured+looked",
   "gap": "plain cut"},
  {"at": [4.84, 5.2], "kind": "camera", "seen": "Very fast zoom into the wing in 0.3 s, then hold",
   "evidence": "measured+looked", "technique": {"slug": "motion-crash-zoom", "name": "Crash Zoom", "match": "exact"},
   "sfx": {"category": "riser", "example_id": "sfx-mi517010"}},
  {"at": [12.92, 13.66], "kind": "transition", "seen": "A circle closes to black on the rabbit, then opens on the sky",
   "evidence": "looked", "technique": {"slug": "transition-iris-close", "name": "Iris Close", "match": "close"},
   "note": "followed by Iris Open"},
  {"at": 0.57, "kind": "sound", "seen": "A short bright transient as the caption appears", "evidence": "measured",
   "sfx": {"category": "cartoon", "example_id": "sfx-746bc6f1d9"}}
 ],
 "recipe": [
  "Pick five 2 to 4 s shots, one gag each.",
  "Join them with a different transition each time: cut, Squeeze, Push Left, Iris Close into Iris Open; end on Fade to Black.",
  "Crash Zoom on the surprise, with a riser just before it."
 ],
 "not_checked": ["What each sound actually is: nothing was heard.", "The caption font."]
}
```
