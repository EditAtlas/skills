---
name: template-skill
description: Replace with what the skill does and when Claude should use it. Name the user's words that should trigger it (in English and Vietnamese if both are expected), the inputs it needs, and what it is not for. Max 1024 characters.
license: Apache-2.0. LICENSE.txt has the complete terms
compatibility: Replace with real requirements (Python version and packages, FFmpeg, network access), or delete this line if there are none.
metadata:
  author: EditAtlas
  version: "0.1.0"
  status: draft
  library: replace with techniques, templates, styles, sfx, studio or several, separated by spaces
  mcp-tools: replace with the MCP tools the skill calls, separated by spaces, or none
  internal: true  # hides this template from `npx skills add`; delete this line in your copy
---

# Skill title

This is template-skill 0.1.0.

One paragraph: the result the person gets, and the one or two things that are always true while doing it (for
example: "you cannot hear", "never invent footage").

## When the inputs are missing

Say what to ask for, and what never to invent.

## Workflow

1. Step, with the exact command or MCP tool call.
2. Step.
3. Check the result in numbers before showing it.

## Deliver

**First, a version check.** If the EditAtlas MCP is connected, call `get_skill` without a name. If it lists template-skill above 0.1.0, the first line of your reply says a newer version exists and how to update it (in Claude Code: `/plugin`, then Marketplaces, editatlas-skills, Update marketplace; elsewhere `get_skill` with name template-skill gives the step). Without the MCP, skip it.

What the person receives, in their language, and what still needs a human to judge.

## References

- `references/...md`: when to read it.
