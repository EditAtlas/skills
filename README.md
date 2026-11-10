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
| [editable-export](./skills/editable-export) | Gives the person an editable copy of a finished video, built from its elements, as an encrypted link to the EditAtlas studio: on a timeline they nudge a late sound, move or resize text, fix a typo or trim a clip, then export the MP4 again in their own browser. Optional, offered at delivery | Sounds | draft |
| [sound-design](./skills/sound-design) | Sound-designs a finished video with real EditAtlas sounds: finds the moments, places each sound on its frame, renders an MP4 and an SFX track, checks sync, pace and loudness in numbers | Sounds | beta |
| [transcribe](./skills/transcribe) | Transcribes speech on your machine with Whisper, a time for every word; checks names, numbers and invented lines with you; writes SRT/VTT and lists silences, fillers and retakes to cut | Techniques, Templates | beta |
| [video-breakdown](./skills/video-breakdown) | Breaks down a video you like shot by shot: measures joins, camera moves, text on screen, pacing and the beat, then names each element with its EditAtlas technique and writes a recipe to make one like it | Techniques, Sounds | beta |

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
```

Or copy a skill folder to `~/.claude/skills/` (Windows: `%USERPROFILE%\.claude\skills\`).

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

## Repository layout

```
.claude-plugin/marketplace.json   plugins for Claude Code; every skill belongs to one
skills/<name>/SKILL.md            one folder per skill
skills/<name>/evals/              test cases in the `claude plugin eval` layout
skills/index.json                 written by scripts/validate.py --write-index
template/SKILL.md                 start a new skill from here
spec/agent-skills-spec.md         the spec and the EditAtlas metadata keys
scripts/validate.py               checks every skill; CI runs it
scripts/package.py                zips each skill for Claude.ai and the API
```

## Make a new skill

See [CONTRIBUTING.md](./CONTRIBUTING.md). In short: copy `template/` to `skills/<name>/`, write it, add test cases,
add it to `marketplace.json`, run `python scripts/validate.py --write-index`, and report what was measured.

## License

Apache License 2.0: see [LICENSE](./LICENSE) and [NOTICE](./NOTICE). Each skill carries a copy as
`LICENSE.txt`, so a downloaded skill keeps its terms. The EditAtlas name and logo are not licensed. Sounds the
skills download come from [EditAtlas/sfx](https://github.com/EditAtlas/sfx) and are not part of this
repository.

## Disclaimer

Skills tell an agent how to do a task; they do not guarantee the result. Test a skill in your own environment
before relying on it. Skills that render audio or video say what they measured and what a person still has to
watch or listen to.
