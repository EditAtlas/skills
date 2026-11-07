# Agent Skills spec

Skills in this repository follow the Agent Skills specification at <https://agentskills.io/specification>.

The parts `scripts/validate.py` checks:

| Field | Rule |
|---|---|
| `name` | required; 1–64 characters; `a-z`, `0-9` and single hyphens; no hyphen at either end; equal to the folder name |
| `description` | required; 1–1024 characters; says what the skill does and when to use it |
| `license` | optional; a license name or the name of a bundled license file |
| `compatibility` | optional; 1–500 characters; environment requirements |
| `metadata` | optional; a map of string keys to string values |
| `allowed-tools` | optional, experimental; a space-separated string |

EditAtlas adds these rules on top.

**Names** follow the way Anthropic names its skills: say what the skill does, in a short noun phrase
(`sound-design`, `canvas-design`, `frontend-design`), an object and its maker (`mcp-builder`, `theme-factory`,
`slack-gif-creator`) or a format (`pdf`, `docx`). Do not start with `editatlas`: the repository and the marketplace
already carry the name, and an installed skill appears as `sound-design@editatlas-skills`.

In `metadata`:

| Key | Meaning |
|---|---|
| `author` | `EditAtlas` for skills made by the project |
| `version` | semantic version as a string, for example `"0.1.0"` |
| `status` | `draft`, `beta` or `stable` |
| `library` | which EditAtlas libraries the skill uses: `techniques`, `templates`, `styles`, `sfx` |
| `mcp-tools` | the EditAtlas MCP tools the skill calls, separated by spaces, or `none` |

The `library` and `mcp-tools` keys let the EditAtlas website list each skill next to the library it works with
(`skills/index.json`, written by `scripts/validate.py --write-index`).
