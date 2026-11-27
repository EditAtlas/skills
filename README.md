# EditAtlas Skills

Skills that let Claude and other agents do real video editing work with [EditAtlas](https://edit.trysometh.ing):
a library of editing techniques with correct names and prompts, composed templates, visual styles and sound
effects you can download.

A skill is a folder with a `SKILL.md` (instructions and metadata) and, when needed, scripts and reference files.
The agent loads it when a task matches its description. Skills here follow the
[Agent Skills specification](https://agentskills.io/specification).

## Skills

| Skill | What it does | EditAtlas library | Status |
|---|---|---|---|
| [editable-export](./skills/editable-export) | Gives the person an editable copy of a finished video, built from its elements, as a folder that opens in the EditAtlas studio on their own computer (footage is never uploaded; kept in their Google Drive from the studio, it also gets a link that carries only the encrypted project): on a timeline they nudge a late sound, move or resize text, fix a typo or trim a clip, leave notes for the agent at a moment, then export the MP4 again in their own browser, or take it to Premiere Pro or DaVinci Resolve as FCP7 XML or OpenTimelineIO. Optional, offered at delivery | Studio | beta |
| [media-picker](./skills/media-picker) | Picks background music, stock footage, photos and sound effects that fit the video, before they go into the edit: writes what each slot needs, measures three to five candidates per slot (camera shake, cuts inside a clip, crop loss for 9:16, the same shot twice, music tempo, intro and energy), looks at every frame sheet, drops what does not show the line or breaks the brief, has you listen to the music options first, then places B-roll on the words it shows, colour-matched to the speaker and clear of the face | Sounds | beta |
| [sound-design](./skills/sound-design) | Sound-designs a finished video with real EditAtlas sounds: finds the moments, places each sound on its frame, renders an MP4 and an SFX track, checks sync, pace and loudness in numbers | Sounds | beta |
| [talking-head-cut](./skills/talking-head-cut) | Cuts a raw talking-head take into a clean video: reads it as numbered lines with notes to the editor, retakes, false starts and doubled words marked; you quote what goes, it measures the sound and puts every cut in silence, shortens long pauses to a breath, renders picture and sound in step, then transcribes the cut again to catch leftovers and clipped words; keeps pauses apart from words under music, and picks the best take across several files | Techniques | beta |
| [transcribe](./skills/transcribe) | Transcribes speech on your machine with Whisper, a time for every word; checks names, numbers and invented lines with you; aligns English word times to the sound; writes SRT/VTT and lists silences, fillers and retakes to cut | Techniques, Templates | beta |
| [video-breakdown](./skills/video-breakdown) | Breaks down a video you like shot by shot: measures joins, camera moves, text on screen, motion graphics timing, pacing and the beat, then names each element with its EditAtlas technique and writes a recipe to make one like it; also says what a remake does differently | Techniques, Sounds | beta |
| [video-check](./skills/video-check) | Checks a finished render before anyone sees it: measures size, frame rate, black, frozen and stray frames, loops, loudness, clipping and silences; makes phone-size frame sheets for a reviewer who has not seen the plan; flags wrong frames at cuts and text too small or brief for a phone, judges by kind of video, fixes the worst three problems and checks each claimed fix, at most three rounds; writes what was checked and what nobody listened to | Techniques | beta |

`skills/index.json` lists the same skills as data: the EditAtlas website reads it to show each skill next to the
library it works with.

## Install

### Claude Code

Add this repository as a plugin marketplace, then install a skill:

```
/plugin marketplace add EditAtlas/skills
/plugin install editable-export@editatlas-skills
/plugin install sound-design@editatlas-skills
/plugin install transcribe@editatlas-skills
/plugin install video-breakdown@editatlas-skills
/plugin install video-check@editatlas-skills
```

Or copy a skill folder to `~/.claude/skills/` (Windows: `%USERPROFILE%\.claude\skills\`).

### Updating

Claude Code does not update skills from this marketplace on its own until you ask it to. Open `/plugin`, then
Marketplaces, `editatlas-skills`:

- **Update marketplace** brings every installed EditAtlas skill to the latest version; then run `/reload-plugins`.
- **Enable auto-update** does that by itself from then on.

From a shell: `claude plugin marketplace update editatlas-skills && claude plugin update <skill>@editatlas-skills`,
then restart Claude Code. With `npx skills`, run the install line from the skill's page on
[edit.trysometh.ing/skills](https://edit.trysometh.ing/skills) again; it names the latest release. For a zip or a
copied folder, download the zip again and replace the old one.

Each `SKILL.md` names its version near the top. With the EditAtlas MCP connected, the agent checks for a newer
version when it delivers and may tell you, but it does not always, so turning on auto-update is the sure way.

### Claude.ai

Download the skill's zip from the [latest release](https://github.com/EditAtlas/skills/releases/latest) and upload
it in Settings > Capabilities > Skills. Skills that run scripts need code execution turned on, and skills that
download sounds need network access to the hosts named in their `compatibility` field.

### Claude API

Upload the same zip with the Skills API. See the
[Skills guide](https://docs.claude.com/en/api/skills-guide#creating-a-skill).

### The EditAtlas MCP

Most skills work better with the EditAtlas MCP server connected, so that search ranks well and records stay
current. See [edit.trysometh.ing](https://edit.trysometh.ing) for the install line.

## Telemetry

When a skill's main script finishes, it sends EditAtlas four things: the skill's name, its version, whether it
finished or failed, and how many seconds it took, for example
`{"skill": "sound-design", "version": "0.4.3", "result": "ok", "seconds": 37}`. Nothing else: no ID, no file names
or paths, no text, no media, no system details. EditAtlas keeps only daily totals per skill, version and result, and
deletes them after 180 days ([privacy](https://edit.trysometh.ing/privacy)). It tells us which skills are used and
which fail, so we know what to fix.

To turn it off, set `EDITATLAS_TELEMETRY=0` (or `false`, `off`, `no`). It is also off when `CI` is set. The send runs
in the background and gives up after 2 seconds; a skill never fails or waits longer because of it. The code is
[`scripts/editatlas_signal.py`](./scripts/editatlas_signal.py), copied into each skill's `scripts/`; the script that
sends it:

| Skill | Sends from | Other scripts (they send nothing) |
|---|---|---|
| editable-export | `package.py build` | `package.py check`, `save`, `versions`, `changes`; `render.py`; `share.py`; `matte.py`; `convert.py` |
| media-picker | `measure.py` | `place.py`, only when B-roll goes on the words; `look.py`, `highlights.py` |
| sound-design | `mix.py`, once per render | `moments.py`, `sounds.py`, `check.py`, `beat_grid.py` |
| talking-head-cut | `render.py`, once per cut | `cut.py`, `takes.py`, `verify.py`; it also runs transcribe's `transcribe.py`, which sends for transcribe |
| transcribe | `transcribe.py` | `doctor.py`, `fix.py`, `captions.py`, `cuts.py`, `align.py` |
| video-breakdown | `analyze.py` | `frames.py`, `text_look.py`, `elements.py`, `background.py`, `compare.py`, `report.py` |
| video-check | `check.py`, once per check | `fix_sound.py` |

## Repository layout

```
.claude-plugin/marketplace.json   plugins for Claude Code; every skill belongs to one
skills/<name>/SKILL.md            one folder per skill
skills/<name>/evals/              test cases in the `claude plugin eval` layout
skills/index.json                 written by scripts/validate.py --write-index
template/SKILL.md                 start a new skill from here
spec/agent-skills-spec.md         the spec and the EditAtlas metadata keys
scripts/validate.py               checks every skill; CI runs it
scripts/editatlas_signal.py       the run signal (see Telemetry); each skill keeps an identical copy
scripts/test_editatlas_signal.py  its tests, standard library only; CI runs them on Python 3.11 and 3.13
scripts/test_project_format.py    the editatlas-project/1 schema, package.py check and convert.py (OTIO, FCP7 XML);
                                  needs jsonschema and FFmpeg; CI runs it on Python 3.9 and 3.13 with OpenTimelineIO
scripts/package.py                zips each skill for Claude.ai and the API
```

## Make a new skill

See [CONTRIBUTING.md](./CONTRIBUTING.md). In short: copy `template/` to `skills/<name>/`, write it, add test cases,
add it to `marketplace.json`, copy `scripts/editatlas_signal.py` into its `scripts/`, end its main script with
`run(main)`, add it to `MAIN_SCRIPTS` in `scripts/validate.py` with the line about telemetry near the top of its
SKILL.md, run `python scripts/validate.py --write-index`, and report what was measured.

## License

Apache License 2.0: see [LICENSE](./LICENSE) and [NOTICE](./NOTICE). Each skill carries a copy as
`LICENSE.txt`, so a downloaded skill keeps its terms. The EditAtlas name and logo are not licensed. Sounds the
skills download come from [EditAtlas/sfx](https://github.com/EditAtlas/sfx) and are not part of this
repository.

## Disclaimer

Skills tell an agent how to do a task; they do not guarantee the result. Test a skill in your own environment
before relying on it. Skills that render audio or video say what they measured and what a person still has to
watch or listen to.
