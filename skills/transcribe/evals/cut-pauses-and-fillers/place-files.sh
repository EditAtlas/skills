#!/usr/bin/env bash
# Input: en_tips.mp4, made fresh with Microsoft Edge voices (edge-tts), with known words and pauses.
set -eu
python "$(dirname "$0")/../make_film.py" en_tips
