#!/usr/bin/env bash
# Input: raw.mp4, a Vietnamese raw take made fresh with a Microsoft Edge voice (edge-tts), with known mistakes and pauses.
set -eu
python "$(dirname "$0")/../make_raw.py" vi_rice
mv vi_rice.mp4 raw.mp4
