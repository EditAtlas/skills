#!/usr/bin/env bash
# Input: a 6 s vertical test clip and a click.
set -eu
ffmpeg -v error -f lavfi -i testsrc2=size=1080x1920:rate=30:duration=6 -c:v libx264 -pix_fmt yuv420p clip.mp4
ffmpeg -v error -f lavfi -i "sine=frequency=2000:duration=0.05" -af "afade=t=out:d=0.04" click.wav
