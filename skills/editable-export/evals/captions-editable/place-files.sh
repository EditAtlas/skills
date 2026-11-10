#!/usr/bin/env bash
# Input: a 12 s landscape test film with a tone, and a word-level transcript in the transcribe skill's format.
set -eu
ffmpeg -v error -f lavfi -i testsrc2=size=1920x1080:rate=30:duration=12 -f lavfi -i sine=frequency=220:duration=12 \
  -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest talk.mp4
python - <<'PY'
import json
text = ("saying no is the fastest way to protect your time every yes is a no to something else "
        "so pick the work that matters and let the rest go").split()
words, t = [], 0.3
for i, w in enumerate(text):
    words.append({"w": w, "start": round(t, 2), "end": round(t + 0.32, 2), "p": 0.95})
    t += 0.42 + (0.5 if i in (8, 17) else 0)
json.dump({"source": "talk.mp4", "duration": 12.0, "language": "en", "words": words, "checked": True},
          open("transcript.json", "w"), indent=1)
PY
