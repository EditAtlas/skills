#!/usr/bin/env bash
# Input: the public EditAtlas demo "edit-cartoon-comedy", made from Big Buck Bunny (CC BY, Blender Foundation).
set -eu
curl -fsSL -A "editatlas-skills-eval/1.0" -o comedy.mp4 https://edit.trysometh.ing/media/demos/edit-cartoon-comedy/after.mp4
