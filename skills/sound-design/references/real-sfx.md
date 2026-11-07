# Using Clipwing's real-sfx with the EditAtlas library

`real-sfx` (github.com/Clipwing/skills, `skills/real-sfx`; README says scripts MIT, uisfx sounds CC0; the repo has
no LICENSE file) is a larger sound-design skill: event lists from a project's own cue file or synth script, screen
recording regions, beat grids, taking a synthesized layer out of a render, YAMNet tags, a nine-axis critique and a
blind A/B listening page. It ships without sounds. EditAtlas can be its main library.

## What was verified (2026-11-07, Windows 10, real-sfx commit edbefcbc)

| Check | Result |
|---|---|
| `tests/selftest.py` with Python 3.11, temp folder under an 8.3 short user path (one with `~1` in it) | 183/188 |
| `tests/selftest.py` with Python 3.14, temp folder on a long path | 188/188 (maskmodel skipped: no numpy in that Python) |
| `build_index.py` over the EditAtlas library | 2,277 of 2,278 sounds (the one `.webm` is not a real-sfx audio type) |
| Picture-only run on a 12 s template preview (`find_moments` → `suggest_cues` → `mix` → `critique`) | PASS on round 1: 8 axes 10/10, loudness 8 (-15.7 LUFS) |

The five 3.11 failures have two causes outside its logic:

- `sheet.py set --at 2.0 gain_db=-3`: argparse in Python 3.11 does not take a `nargs="*"` positional after an
  option. Put `KEY=VALUE` first (`sheet.py set SHEET gain_db=-3 --at 2.0`) or use Python 3.12+.
- `from_synth.py` with a project under an 8.3 short path (`ABCDEF~1`): Node cannot open the script. Use a long path.

One gap showed on the first run: its auto-pick asked for `role: sub_drop` and EditAtlas has none tagged so
(`Sub Impact 01` exists but its words do not match real-sfx's pattern). Change the cue to `role: hit` or pick by id.

## Setup

```
python scripts/realsfx_library.py PATH/EditAtlas-SFX PATH/editatlas-lib   # hard links (or copies) + catalog.json
export REAL_SFX_CONFIG=PATH/real-sfx-config.json                           # keep its config out of the skill folder
python REAL_SFX/scripts/setup.py init --library editatlas=PATH/editatlas-lib
python REAL_SFX/scripts/build_index.py
```

Set `index_path` in that config to an absolute path outside the skill folder. Category → real-sfx type: whoosh,
impact, riser, ui, glitch, foley, ambience, nature, cartoon, scifi as they are; bell and magic → chime; voice →
voice and music → music_transition (both never auto-picked, only taken by `--role`).

## When to use which

- `sound-design` (this skill): any machine, downloads only the sounds a film uses, the agent looks at frames and
  writes the cues itself. Best for short social video and for agents in a sandbox.
- `real-sfx`: a local copy of the whole library (768 MB), projects that already have cue lists or synthesized sound,
  screen recordings, music with a beat grid.
