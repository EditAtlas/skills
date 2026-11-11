#!/usr/bin/env bash
# Input: the public EditAtlas demo "edit-fast-dialogue", made from His Girl Friday (1940, public domain in the US).
set -eu
curl -fsSL -A "editatlas-skills-eval/1.0" -o dialogue.mp4 https://edit.trysometh.ing/media/demos/edit-fast-dialogue/after.mp4
