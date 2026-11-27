#!/usr/bin/env bash
# Input: a 6 s talking clip (a "person" that moves in front of a busy background), the cut-out the person's
# background remover made of it (ProRes 4444 with transparency), and a beach photo. No network.
set -eu
mkdir -p footage
ffmpeg -v error -y -f lavfi -i "testsrc2=size=720x1280:rate=30:duration=6" -f lavfi -i "color=c=0xd9a066:size=260x620:rate=30:duration=6" \
  -f lavfi -i "sine=frequency=220:duration=6" \
  -filter_complex "[0][1]overlay=x='230+60*sin(t*1.5)':y=520[v]" -map "[v]" -map 2 -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest footage/me-talking.mp4
ffmpeg -v error -y -f lavfi -i "color=c=black@0.0:size=720x1280:rate=30:duration=6,format=rgba" -f lavfi -i "color=c=0xd9a066:size=260x620:rate=30:duration=6,format=rgba" \
  -filter_complex "[0][1]overlay=x='230+60*sin(t*1.5)':y=520:format=auto,format=yuva444p10le" -c:v prores_ks -profile:v 4444 footage/me-talking-cutout.mov
ffmpeg -v error -y -f lavfi -i "gradients=size=720x1280:c0=0x2b8cbe:c1=0xf6e8c3:duration=1:speed=0" -frames:v 1 footage/beach.jpg
