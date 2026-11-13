# editable-export

With a finished video, give the person an editable copy built from its elements: footage clips, text, graphics,
sounds and music. The copy opens in the [EditAtlas studio](https://edit.trysometh.ing/studio), a web page with
the video, a timeline and a panel. There they can fix small things themselves, then export the MP4 again on their
own computer, without asking Claude to edit and render again. Things they can fix:

- a sound a little late, or too loud
- a caption slightly off, or too small
- a typo
- a clip a few frames long

The copy is optional. Claude offers it when it delivers a video and builds it only when asked.

Status: beta (0.3.2).

## How the person gets it

A folder, `NAME.edit`, with `project.json`, `media/` and `versions/`. The person opens the studio in Chrome or
Edge, presses **Choose the folder** and picks it. The page reads the folder and saves into it in the browser; the
footage is never uploaded and there is no account. In a sandbox such as a Claude.ai chat, Claude zips the folder
for download and the person unzips it.

If the person wants it, Claude also makes a light link (`share.py send`, after a yes). It holds only the project's
versions, the text and timings, gzipped and encrypted on their machine with AES-256-GCM; never a media file. The key
is the part of the link after the `#`, which browsers never send to a server, so EditAtlas stores bytes it cannot
read. Links have no end date for now; the folder keeps every version either way. The person opens the link and, the
first time in that browser, chooses the folder for the media. In a sandbox the link is how they hand back: Claude
pulls their version, saves its own and pushes it to the same link.

Every save is a new version in `versions/` (`v1.json`, `v2.json` ...), by Claude or by the person, with a note.
`project.json` is always the newest. So the person and Claude can take turns on the same folder: the studio's
**Continue with Claude** gives the person a message to paste back, and Claude carries on from their version.

## Needs

- Python 3.9+ and FFmpeg with ffprobe in PATH
- `render.py` (the video Claude delivers): `pip install playwright`, Chrome or Edge installed, and network access
  to `edit.trysometh.ing` to load the studio page (the files stay on the machine)
- `share.py` (the optional link): `pip install cryptography`, and network access to `edit.trysometh.ing`
- The person: Chrome or Edge 94+ (the studio uses WebCodecs, and saves into the folder). Safari and Firefox are
  not tested.

## What the person can change

| Element | On the picture | In the panel | On the timeline |
|---|---|---|---|
| Text | click, drag (snaps to the centre), corner to resize | text, size, colour, font (the project's, 18 from EditAtlas with Vietnamese, or a file of their own) and weight, position, timing; for a style, this one (the default) or all items; copy, paste at the playhead, duplicate; copy the look of one text onto another | move, trim both ends |
| Graphics | click, drag, corner to resize | position, size, opacity, timing; copy, paste, duplicate | move, trim |
| Sounds and music | | nudge by a frame, level in dB, fades; copy, paste, duplicate | move, trim, mute a track |
| Clips | | trim in and out by a frame; what comes after moves with it; split at the playhead; move earlier or later; duplicate; delete, with the text and sounds on it | trim the edges, split (S), drag to another place |

The picture zooms in (up to 400 %) and **Bigger picture** hides the timeline; **Guides** show the centre lines and, on a
vertical video, the area that app buttons leave clear. The studio also has undo and redo, makes the MP4 with **Export MP4**, and saves the person's changes into the
folder as the next version with **Save** (and onto the link, when there is one). **Continue with Claude** saves
too and gives them a message for Claude; Claude reads their version (`share.py pull` first with a link), saves its own
as the next one with `package.py save` (then `share.py push`), and the studio offers it when the person comes back. Motion graphics drawn in code stay elements as animated WebP images.

## Files

| Path | What |
|---|---|
| `SKILL.md` | The workflow Claude follows |
| `references/project-format.md` | `project.json`: an edit as elements (`editatlas-project/1`) |
| `scripts/package.py` | `build`: checks a project, imports transcribe's cuts and captions and sound-design's sounds, and writes `NAME.edit/` (version 1). `save`: Claude's next version. `versions`, `changes` (in the studio's words) and `check` |
| `scripts/render.py` | Runs the studio's own export in Chrome or Edge without a window: the video Claude delivers |
| `scripts/share.py` | The optional link, project versions only: `send` makes it, `pull` writes the person's newer versions into the folder (never media; it lists media the folder lacks), `push` puts Claude's newer versions on it, `versions` lists them |
| `evals/` | Test cases in the `claude plugin eval` layout |

The studio page and the link service are in the EditAtlas website's repository, not here.

## Verified

Beta (0.3.0), on 2026-11-10. The owner read the results and approved; the evidence for each beta condition:

- **Every test case, with and without the skill.** A fresh agent ran all 7 cases in `evals/` against the production
  studio and link service, once with only this skill and once with no skill. With the skill it passed 22 of 22
  checks, without it 14 of 23, in 75 s against 124 s on average, with about the same tokens (68k a run). Without
  the skill it rendered with its own FFmpeg script and Arial, so the MP4 can differ from the studio (3 cases); it
  gave a JSON, a Python script and an ASS file instead of a studio copy for captions; it blurred burned-in captions
  and drew new ones on top. It did re-implement the link from the public studio code and push version 3 correctly,
  in 150 s against 71 s. `no-offer-subtitles-only` passed in both runs, so it shows only that the skill adds no
  unwanted offer.
- **Real results looked at.** Rendered files checked with ffprobe, frames and sound levels in every run; the
  versions each run saved hold the person's values (size 96 or 90, click at 0.6 s or -9 dB) and pass `check`. The
  studio itself was used by hand in Chrome on the owner's projects during 0.1 and 0.2.
- **Studio and agent on one folder and one link.** The studio's flow test (53 checks), the folder round trip
  `package.py` <-> studio (9 of 9) and the link round trip `share.py` <-> studio against production (26 of 26).
- **Installs from the marketplace.** A fresh Claude Code with an empty config added the marketplace from GitHub
  (v0.10.1) and installed the plugin, then ran it end to end with the production MCP to version 3 on one link.
- Each case ran once per arm, so how much a run varies is not measured.

0.2.0 (versions in the folder, no upload), on 2026-11-10, on a 12-thread Windows PC with Chrome 156:

- `package.py` end to end on a 4 s 1080×1920 test package: `build` wrote version 1 and refused to build into the
  same folder again; a hand-written studio version 2 (hook size 96, click 0.1 s later) was listed by `versions` and
  described by `changes` as the studio does; `save --from 2` wrote version 3 with a new sound and a changed file of
  the same name (copied as `click-2.wav`, nothing overwritten); `save --from 1` was refused and named version 3 and
  its author; `--force` wrote version 4 from 1; `check` passed, flagged a gap in the numbers and a `project.json`
  edited without a version; a folder without `versions/` got its version 1 written on the first save.
- `changes` gives the same lines as the studio's own `changeSummary` on 425 pairs of projects (25 made by hand, 400
  random), run against the JS function in Node.
- `render.py` on that package with `versions/`, against the production studio page: 120 frames in 2 s, H.264
  1080×1920 30 fps with AAC 48 kHz, 4.01 s.
- `share.py` sealing against a WebCrypto reference in Node (AES-GCM with the contract's additional data, HKDF write
  token, gzip): 5 projects up to 7 KB sealed, Python sealed and Node opened, Node sealed and Python opened, the
  write tokens were equal, and a wrong object name or share id was refused on both sides (25 of 25 checks).
- `share.py` against a local mock of the link API (not the real server): send, a studio version put by the eval
  helper, versions, pull, save and push; push refused after the studio saved meanwhile, pull refused the clash and
  `--set-aside` resolved it; a studio version with a new logo listed the missing file; pull of the link into an empty
  folder wrote 5 versions and listed the 3 missing media; an expired link (410) printed the server's message.

Earlier (0.1.x), against a local copy of the studio:

- **A 34.5 s 1080×1920 talking head.** It had 42 captions with word timing, a hook, a logo, 3 sounds, music and
  3 clips cut from a 24 fps source: 23.1 MB in 8 files. `render.py`: 1035 frames in 45 s (23 frames/s), H.264 +
  AAC, 45.5 MB. Every frame was identical to an export that seeks to every frame.
- **The studio used like a person would, in Chrome:** open the package from disk; captions 66 → 84 px for all 42
  at once, and a sound 2 frames earlier; Export MP4: 1035 frames in 26 to 28 s.
- **Heavy graphics** (28 stickers, a full-frame overlay, 10 shadowed labels at once, 4 animated WebP graphics, zooming
  clips, 96 elements): preview frames took 3 ms or less to draw, no footage frame more than 100 ms off at the cuts,
  and 8 exported frames matched the preview at the same time (PSNR 32 to 41 dB, against 19 to 36 dB for the next
  frame).
- **Two eval cases run by hand** (`captions-editable`, `apply-saved-changes`), before the move to the studio.
  Both built, checked and rendered, and their frames were looked at.

Not yet checked:

- the zip hand-over in a Claude.ai chat
- Safari, Firefox, Mac
- videos longer than a minute
- exporting in a visible browser window (Chrome without a window varied from 26 s to 90 s for the same 35 s video
  between runs)
- real people using it
