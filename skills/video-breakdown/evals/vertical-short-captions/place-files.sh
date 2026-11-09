#!/usr/bin/env bash
# Input: the public EditAtlas demo "edit-vertical-short", made from Charade (1963, public domain in the US).
set -eu
curl -fsSL -A "editatlas-skills-eval/1.0" -o short.mp4 https://edit.trysometh.ing/media/demos/edit-vertical-short/after.mp4
