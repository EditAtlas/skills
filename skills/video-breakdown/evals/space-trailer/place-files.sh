#!/usr/bin/env bash
# Input: the public EditAtlas demo "edit-to-the-moon", made from NASA footage (public domain).
set -eu
curl -fsSL -A "editatlas-skills-eval/1.0" -o trailer.mp4 https://edit.trysometh.ing/media/demos/edit-to-the-moon/after.mp4
