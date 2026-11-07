#!/usr/bin/env bash
# Input: the public EditAtlas "say-no-story" template preview, with its voice.
# Footage credit (burned into the picture): Chris Hufnagel on YouTube, CC BY. Edited by EditAtlas.
set -eu
curl -fsSL -A "editatlas-skills-eval/1.0" -o say-no-story.mp4 https://edit.trysometh.ing/template-previews/say-no-story.1.0.0.mp4
