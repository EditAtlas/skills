#!/usr/bin/env bash
# Input: take.mp4, a raw take made fresh with a Microsoft Edge voice (edge-tts), with known mistakes and pauses.
set -eu
python "$(dirname "$0")/../make_raw.py" en_audio_tips
mv en_audio_tips.mp4 take.mp4
