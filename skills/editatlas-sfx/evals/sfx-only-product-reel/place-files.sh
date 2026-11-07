#!/usr/bin/env bash
# Input: the public EditAtlas "pour-ritual" template preview with its audio removed.
# Footage credit (burned into the picture): Alberto Seghezzi on YouTube, CC BY. Edited by EditAtlas.
set -eu
curl -fsSL -A "editatlas-skills-eval/1.0" -o pour-ritual.mp4 https://edit.trysometh.ing/template-previews/pour-ritual.1.0.0.mp4
ffmpeg -v error -y -i pour-ritual.mp4 -an -c:v copy pour-ritual-silent.mp4
rm pour-ritual.mp4
