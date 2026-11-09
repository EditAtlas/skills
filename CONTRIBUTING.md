# Adding or changing a skill

## 1. Start from the template

```
cp -r template skills/<name>
cp LICENSE skills/<name>/LICENSE.txt
```

`<name>`: lowercase letters, digits and single hyphens, the same in the folder and in `name:`. Name the job, the
way Anthropic does: a short noun phrase (`sound-design`), an object and its maker (`mcp-builder`, `theme-factory`)
or a format (`pdf`). No `editatlas-` prefix: the repository and the marketplace already say EditAtlas.

## 2. Write SKILL.md

- **Description** (max 1024 characters): what it does, when to use it, the words a person would type (English and
  Vietnamese if both are expected), and what it is not for. The agent decides to load the skill from this text
  alone.
- **Metadata**: fill `author`, `version`, `status`, `library` and `mcp-tools` (see `spec/agent-skills-spec.md`), and delete the `internal: true` line, which only keeps the template itself out of `npx skills add`. `mcp-tools` must name
  only tools the EditAtlas MCP really has.
- **Body**: under 500 lines. Explain why each step matters, not just what to do. Move long detail into
  `references/` and say when to read each file.
- **Scripts**: self-contained, Python 3.9+ unless stated, errors that say what to do next. Put dependencies in
  `compatibility`.
- **Honesty rules**: the agent never invents inputs, never claims it watched or listened, and reports gaps.

## 3. What must never be in this repository

This repository is public. Keep out:

- private catalog fields: pack, original file name, source URL, rights or license labels of sounds
- personal paths, account names and email addresses
- media files (video, audio): test cases download their inputs from the EditAtlas site in `place-files.sh`
- secrets and API keys

`scripts/validate.py` checks for the common cases, but read your diff too.

## 4. Test cases

Each case is a folder in `skills/<name>/evals/` in the `claude plugin eval` layout: `prompt.md`, `case.yaml`,
`graders/NN-*.md` (one checkable statement each) and, for input files, `place-files.sh`. Include at least one case
where the input is missing and the skill should ask instead of inventing.

## 5. Check and list it

```
pip install pyyaml
python scripts/validate.py --write-index
python scripts/package.py <name>
```

Add the skill to a plugin in `.claude-plugin/marketplace.json` and to the table in `README.md`.

## 6. Report

In the pull request, state what was run and what was measured (for example "2 films, 0 ms sync error, -16.9 LUFS"),
what was not checked, and whether a fresh agent ran the test cases with only the skill to go on.

## License of contributions

By opening a pull request you agree that your contribution is licensed under the Apache License 2.0, as
section 5 of the License says.

## Status

`metadata.status` says how far a skill has been proven. Move it up only when every condition is met, and say in the
pull request which evidence meets each one.

| Status | Conditions |
|---|---|
| `draft` | Written; `validate.py` passes; the author ran it on real inputs |
| `beta` | A person checked real results (watched, listened, read) and approved them; a fresh agent with only the skill ran every test case and passed, and did better than the same agent without the skill; it installs from the marketplace |
| `stable` | Used on real projects with no open bugs; the description was tested for triggering (it loads when it should and not otherwise) |

## Versions and releases

Raise `metadata.version` on every change to a skill (patch for fixes, minor for new behaviour). A tag `vX.Y.Z` on
`main` runs `.github/workflows/release.yml`, which attaches one zip per skill and `skills/index.json` to a GitHub
release.
