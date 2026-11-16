#!/usr/bin/env bash
# Input: demo_take.mp4, a raw take made fresh with a Microsoft Edge voice (edge-tts), with known mistakes and pauses.
set -eu
python "$(dirname "$0")/../make_raw.py" en_app_demo
mv en_app_demo.mp4 demo_take.mp4
