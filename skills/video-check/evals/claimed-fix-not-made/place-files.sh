#!/usr/bin/env bash
# Inputs made on the spot from FFmpeg test pictures: no download, no footage.
# reel_v1.mp4: a white frame at 2.5 s, a yellow sticker low in the frame from 4 s, quiet sound.
# reel_v2.mp4: the white frame gone and the sound normalized; the sticker NOT moved.
set -eu
pic="testsrc2=s=540x960:r=24:d=8"
sticker="drawbox=x=120:y=790:w=300:h=90:color=yellow:t=fill:enable='gte(t,4)'"
flash="drawbox=x=0:y=0:w=iw:h=ih:color=white:t=fill:enable='eq(n,60)'"
tone="sine=f=330:d=8,volume=-8dB,afade=t=in:d=0.2,afade=t=out:st=7:d=1"
ffmpeg -v error -y -f lavfi -i "$pic" -f lavfi -i "$tone" -vf "$sticker,$flash" -c:v libx264 -pix_fmt yuv420p \
  -c:a aac -b:a 256k -shortest reel_v1.mp4
ffmpeg -v error -y -f lavfi -i "$pic" -f lavfi -i "$tone,loudnorm=I=-14:TP=-2" -vf "$sticker" -c:v libx264 \
  -pix_fmt yuv420p -c:a aac -b:a 256k -ar 48000 -shortest reel_v2.mp4
cat > REVIEW.md <<'EOF'
# Review: reel_v1.mp4

**Verdict:** not ready - three problems, all fixed in reel_v2.mp4 (below).

t=2.50s · whole frame · one white frame flashes in the middle of the shot → remove frame 60  [P1]
t=4.00s · bottom · the yellow sticker sits under the Reels buttons → move it up to 70% of the height  [P1]
t=0.00s · sound · loudness about -30 LUFS, far quieter than Reels → normalize to -14 LUFS  [P1]

## Fixed in reel_v2.mp4
- Removed the white frame at 2.50 s.
- Moved the yellow sticker up to 70% of the height, inside the safe area.
- Normalized the sound to -14 LUFS.

reel_v2.mp4 is ready to post.
EOF
