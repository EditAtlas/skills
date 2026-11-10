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

Status: draft (0.1.1).

## How the person gets it

- **A link.** Claude encrypts the project and its files on the person's machine (AES-256-GCM), sends them to
  EditAtlas and gives the person a link. The key is the part of the link after the `#`, which browsers never send
  to a server, so EditAtlas stores bytes it cannot read. No account is needed. The link stops working after 30
  days and the files are deleted. Claude asks before it uploads.
- **A folder.** The person opens the studio, presses **Choose the folder** and picks the package. Nothing is
  uploaded.

## Needs

- Python 3.9+ and FFmpeg with ffprobe in PATH
- Network access to `edit.trysometh.ing`
- `render.py` (the video Claude delivers): `pip install playwright`, and Chrome or Edge installed
- `share.py` (the link): `pip install cryptography`
- The person: Chrome or Edge 94+ (the studio uses WebCodecs). Safari and Firefox are not tested.

## What the person can change

| Element | On the picture | In the panel | On the timeline |
|---|---|---|---|
| Text | click, drag (snaps to the centre), corner to resize | text, size, colour, position, timing; for a style, all items or this one | move, trim both ends |
| Graphics | click, drag, corner to resize | position, size, opacity, timing | move, trim |
| Sounds and music | | nudge by a frame, level in dB, fades | move, trim, mute a track |
| Clips | | trim in and out by a frame; what comes after moves with it | trim the edges |

The studio also has undo and redo, keeps changes in the browser as the person works, makes the MP4 with
**Export MP4**, saves with **Save** (the next version on a link, or the whole package into a folder on their computer). **Continue with Claude** adds their changes to the link
as the next version and gives them a message for Claude; Claude pulls it, carries on from their values and pushes
its own version to the same link, which their open studio offers. Motion graphics drawn in code stay elements as
animated WebP images.

## Files

| Path | What |
|---|---|
| `SKILL.md` | The workflow Claude follows |
| `references/project-format.md` | `project.json`: an edit as elements (`editatlas-project/1`) |
| `scripts/package.py` | Checks a project, imports transcribe's cuts and captions and sound-design's sounds, and writes `NAME.edit/` (project.json, media/) |
| `scripts/render.py` | Runs the studio's own export in Chrome or Edge without a window: the video Claude delivers |
| `scripts/share.py` | `send` makes an encrypted link (version 1); `pull` gets the person's newest version and says what changed; `push` saves Claude's next version on the same link; `versions` lists them |
| `evals/` | Test cases in the `claude plugin eval` layout |

The studio page and the share service are in the EditAtlas website's repository, not here.

## Verified

On 2026-11-10, on a 12-thread Windows PC with Chrome 156, against a local copy of the studio:

- **A 34.5 s 1080×1920 talking head.** It had 42 captions with word timing, a hook, a logo, 3 sounds, music and
  3 clips cut from a 24 fps source: 23.1 MB in 8 files.
  - `render.py`: 1035 frames in 45 s (23 frames/s), H.264 + AAC, 45.5 MB. Every frame was identical to an export
    that seeks to every frame. In earlier runs of the same export code, 1 frame of 1035 showed the next source
    frame.
  - `share.py send`: 23.1 MB in 11 objects, 2 to 3 s to a server on the same machine.
  - `share.py get` (now `pull`): all 8 files came back byte for byte, and `project.json` was identical. A link
    with a wrong key was refused.
- **The studio used like a person would, in Chrome.** These steps all did what they should:
  - open the package from disk
  - captions 66 → 84 px for all 42 at once, and a sound 2 frames earlier
  - Share: a link in 3.5 s; what the server stored could not be read as text
  - open the link in a fresh browser: 1.3 s, the changes were there, no file was missing
  - change the hook and save again: about 9 KB sent
  - Export MP4: 1035 frames in 26 to 28 s
  - a link with a wrong key, and a link that does not exist, each gave a plain message
- **The round trip on one link** (a script driving Chrome and `share.py`): 18 of 18 checks passed.
  - `send` made version 1; the studio opened it, two changes were saved as version 2 with a note, and the message
    for Claude named the link and both changes
  - `pull` printed both changes and the note, and fetched no file again; a hook text change pushed as version 3
    sent 0.01 MB
  - the open studio showed "Version 3 ... by your agent: longer hook" and opened it with both sides' changes
  - a studio save made while Claude pushed version 4 was stopped with a choice, then saved as version 5 from 3
  - `push` from the stale folder was refused and told to pull; `versions` and the studio's list showed all five
- **Heavy graphics** (28 stickers, a full-frame overlay, 10 shadowed labels at once, 4 animated WebP graphics, zooming
  clips, 96 elements): preview frames took 3 ms or less to draw, no footage frame more than 100 ms off at the cuts,
  and 8 exported frames matched the preview at the same time (PSNR 32 to 41 dB, against 19 to 36 dB for the next
  frame).
- **Two eval cases run by hand** (`captions-editable`, `apply-saved-changes`), before the move to the studio.
  Both built, checked and rendered, and their frames were looked at.

Not yet checked:

- the studio and the share service in production
- upload speed over a real connection
- Safari, Firefox, Mac
- videos longer than a minute
- exporting in a visible browser window (the timings above are from Chrome without a window, which varied from
  26 s to 90 s for the same 35 s video between runs)
- real people using it
